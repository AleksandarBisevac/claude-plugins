# The Azure DevOps connector — a field guide

How to wire the audit manifest to an Azure DevOps board: setup, every configuration
key with an example, recipes for the common team shapes, what updates automatically,
and what to do when something drifts. The normative contract behind all of it lives in
[`plugins/audit/reference/tracker-sync.md`](../plugins/audit/reference/tracker-sync.md);
this guide is the tutorial layer.

## What it does

The flows, and only one of them is automatic:

| Flow | Command | Direction | What happens |
|---|---|---|---|
| **Push** | `/audit:sync push [bugs\|tasks\|all]` | manifest → ADO | Creates/updates work items (optionally one PBI per phase with its items parent-linked). Shows the plan, asks before the first write. |
| **Pull** | `/audit:sync pull [bugs\|sprint]` | ADO → manifest | Imports unlinked ADO bugs as manifest bugs, or the current sprint's PBIs/tasks as **parked proposals**. Never modifies ADO. |
| **Parents** | `/audit:sync parents` | ADO → manifest (cache only) | Asks the project which work-item type may parent which, and lists the parent-shaped items on the board, into `meta.ado.hierarchy` and `meta.ado.parentCandidates`. Creates nothing, moves nothing, writes no `adoParent`. |
| **Status** | `/audit:sync status` | read-only | Drift table: manifest state vs board state, sprint drift, connector switches. Works even when the connector is disabled. |
| **Echo** | (automatic, during `/audit:next` / `/audit:run` / `/audit:phase`) | manifest → ADO | Best-effort **update** of already-linked cards when a task goes done/blocked/reopened and at phase sign-off. Never creates anything. |

The manifest side of every link is the item's `ado` field — `{id, url, lastSyncedAt}` —
written immediately after each successful create, so an interrupted push resumes without
duplicating and a re-run converges. Link creation is recorded in the tamper-evident
journal (`ado.link` row); routine `lastSyncedAt` bumps deliberately are not.

## Prerequisites

1. **Transport.** The `az` CLI with the DevOps extension:

   ```bash
   az extension add --name azure-devops
   az login                       # or a PAT — see CI below
   ```

   In a Claude Code session that has the Azure DevOps **MCP** server connected, sync may
   use those tools instead — same behavior, no `az` needed.

2. **Auth is never the plugin's.** Credentials live in `az login` or the
   `AZURE_DEVOPS_EXT_PAT` environment variable. Nothing is ever written into the
   manifest or config — the secrets guard blocks it anyway. For a PAT, the minimal
   scope is **Work Items (Read & Write)**; add **Project and Team (Read)** only if you
   use sprint resolution (`meta.ado.sprint`). `connect` probes inside the Work Items
   scope alone for that reason — a probe that reached for the second one would report a
   false failure on a PAT scoped exactly right for everything this connector does.

3. **`/audit:sync connect` is the guided version of all of the above**, and it is the
   right first command on a new board: it verifies each of these in order and stops on
   whichever one is not true, instead of leaving you to find out at the first `push`.

4. `/audit:doctor` verifies the setup offline: transport present, switches in effect,
   what the links prove. Run it when anything looks wrong afterwards — it reads the
   manifest and never phones the board, which is exactly the half `connect` cannot be.

## Five-minute start

```
/audit:sync connect
```

**That is the whole of it**, and every step before the last is read-only: it finds the
transport, tells you which auth path is actually in effect, proves access with one
Work-Items query, reads that same query for the board's process, and only then asks
before writing `meta.ado`. The next section is what it does and why each rung is there.

Prefer to write the block yourself? Add the minimal shape to your manifest's `meta` (or
open `/audit:panel` → Composition tab → **Azure DevOps connector** card, which edits the
same block with validation):

```json
"ado": {
  "organization": "contoso",
  "project": "web-shop",
  "areaPath": null,
  "iterationPath": null,
  "types": { "bug": "Bug", "task": "Task" }
}
```

Then:

```
/audit:sync push all
```

You will see a plan first — `N creates (of which K PBIs), M updates, J in sync` — and
nothing is written until you confirm. After the run, every pushed item carries its link:

```json
"ado": { "id": 1508, "url": "https://dev.azure.com/contoso/web-shop/_workitems/edit/1508",
         "lastSyncedAt": "2026-08-15T10:12:00Z" }
```

From that moment the **echo** keeps those cards current as the orchestrator works
(see below), and `/audit:sync status` shows any drift.

## `connect`, rung by rung

It exists because of one asymmetry: **the first thing that used to prove access was a
`push`, which is also the first thing that can CREATE items on somebody’s real board.**
So `connect` is four read-only questions and one write, in that order, and any rung can
stop the run with its own message.

### 1. Transport

MCP `azure-devops` tools if this session has them; otherwise `az` plus its `azure-devops`
extension; otherwise it stops with `az extension add --name azure-devops` (or the
install-azure-cli line, which is a different rung and a different message).

An extension list that *did not answer* is its own stop, and deliberately not read as
"installed". Unknown is not present, and treating it as present would send the run on to
a board call whose failure names the wrong cause.

### 2. Which auth path is in effect — not which one exists

This is the rung that repays reading. It reports three facts, none of them a secret:

| fact | how it is observed |
|---|---|
| the `AZURE_DEVOPS_EXT_PAT` variable is set | membership in the environment — **never its value** |
| you are signed in to Azure as *X* | `az account show` (which prints no token) |
| `az devops login` holds a PAT **for this organization** | `~/.azure/azuredevops/organization_list`, a file of organization URLs |

**A stored PAT is per-organization.** Measured on one machine: `uptimize` resolved through
a stored PAT while `test-audit-lab` resolved through the Azure sign-in — at the same
moment, in the same shell. So "am I logged in?" has no answer until you say *to what*.

**When more than one path is present, `connect` says so and picks none.** Nothing
observable from outside says which one `az` answered with, and a precedence rule the
command cannot verify would be a confident wrong answer. What holds either way is the
sentence worth keeping: **a board command that succeeds proves the ORGANIZATION is
reachable, never which identity reached it.**

The scope this connector needs is **Work Items → Read & write**, and nothing else.

### 3. A probe that proves access without creating anything

One WIQL over `<org>/<project>`. Work Items scope on purpose: it is the only scope this
connector needs and the only one a careful person will have granted, so probing with
`az devops project list` would report a false failure on a PAT scoped exactly right.

Two failure texts, and one of them misleads:

| what `az` says | what it means |
|---|---|
| `The project specified is not found in hierarchy` | the credential worked; the **project name** is wrong |
| `you need to run the login command` | either the identity cannot reach this organization **or the organization name is wrong** — a nonexistent organization produces this text identically, so it does not say which |

`connect` grades the second as one verdict naming both readings, because "log in again"
is the wrong advice half the time it would be given.

An **exit 0 with no rows** is still a pass: an empty project proves access exactly as a
full one does.

### 4. Process detection — the same query, read again

The rows carry each item’s type and state, and **the type is the discriminator**:

| the board carries | process | `types.pbi` | `stateMap` |
|---|---|---|---|
| `Product Backlog Item` | Scrum | `Product Backlog Item` | **required** |
| `User Story` | Agile | `User Story` | not needed |
| `Requirement` | CMMI | `Requirement` | **required** |
| `Issue` | Basic | `Issue` (and `types.bug` too) | **required** |

**Not the states**, and that came from measuring rather than from the process
documentation: on the lab’s Agile board, `User Story` was present while the Task states
in use were only `New` and `Closed`, because nothing was sitting in `Active` or
`Resolved`. Observed states are a subset of defined states forever — a state with no item
in it does not appear in a query over items — so `connect` prints them as corroboration
and says which of the two each line is.

The built-in `stateMap` defaults name **Agile** states, so every other process needs a
map or a task reaching done is refused its state. This rung is what turns that from a
first-push surprise into a line you read before the first push.

**Three ways it detects nothing, and they are three answers.** An empty project; a board
with no phase-level item on it yet; a customised board carrying two phase-level types.
None is a failure, none is a reason to guess, and in all three `types` is simply not
proposed.

### 5. The write — the only step that writes

`organization`, `project`, `enabled`, `types` when a process was detected, and
`connection` (below). Confirmed first, applied under the concurrency lock, revalidated
after. **Run it against a manifest that is already configured** and it re-probes and
reports: each difference is an offered `CHANGE`, never an edit, because the value already
in the file may be the one somebody chose against this command’s advice.

### What `connect` records, and the one thing it will not invent

```json
"connection": {
  "process": "Scrum",
  "pbiType": "Product Backlog Item",
  "stateMapNeeded": true,
  "authPath": "stored",
  "fetchedAt": "2026-08-24T09:12:00Z",
  "basis": "read-only work-item query over contoso/web-shop proved access; ..."
}
```

Same evidence shape as the two caches `/audit:sync parents` writes — a moment and a basis,
so it can be aged and checked rather than trusted. The panel’s ADO card reads it.

**There is no expiry date, and its absence is the answer.** Neither transport can be asked
when a credential expires: a PAT’s expiry needs the token itself or an organization-admin
scope this connector never requests, and the Azure sign-in’s access token expires hourly
and renews itself — printing *that* as "credential expiry" would be worse than printing
nothing. A field holding a date nothing can supply would be rendered as `null` by every
surface and read as "does not expire" by every reader.

What is recorded instead is **which auth path was in effect and when access was last
proven**, which is what gives a later failure a class: a stored PAT that worked on a named
day and stops is an expired token, not a broken configuration — and everyone’s expires on
their own schedule.

## Configuration reference

All keys in the table below live under `meta.ado`; one more — `phases[].adoParent` —
lives on the phase and has its own section under it. Everything beyond
`organization`/`project` is optional; **absent keys mean today's defaults**, so a
pre-v2 config keeps behaving exactly as it did — with one deliberate exception, `echo`,
which is ON by default (set it to `false` for manual-only sync).

| Key | Default | What it does |
|---|---|---|
| `organization` | — | Org name or `https://dev.azure.com/<org>` URL. |
| `project` | — | Project name. |
| `areaPath` | `null` | Stamped on every pushed item; also filters `pull bugs`. |
| `iterationPath` | `null` | Static iteration stamp. Superseded by `sprint` when set. |
| `types` | `Bug`/`Task` | Work-item type names. `types.pbi` is the phase-level type: leave it `null` and the first phase push detects the process's own type (Product Backlog Item → User Story → Requirement → Issue) and writes the pick back. |
| `enabled` | on | Master switch. `false` freezes push/pull/echo; links are kept, `status` still reports. |
| `echo` | **on** | The automatic flow. `false` = only explicit `/audit:sync` ever touches ADO. |
| `phaseWorkItems` | on | One PBI per phase, task/bug items parent-linked under it. `false` = flat push. |
| `parentWorkItem` | `null` | The **existing** work item audit work hangs under — typically a Feature or Epic already on the team's backlog. Now the manifest-wide **fallback**: a phase declaring its own `adoParent` wins. Absent/null = the connector builds a free-standing branch, which is correct and which nobody planning from that board will see. An id, so an integer — `"103205"` as a string is named as a typo rather than coerced, because coercing hides it. |
| `hierarchy` | `null` | **Cached evidence**, written by `/audit:sync parents` and never by hand: `{levels: {<type>: <rank>}, fetchedAt, basis}`. Absent = no basis for the type check, so every parent link reports `not verified` and the create proceeds. |
| `parentCandidates` | `null` | **Cached convenience**, written by the same command: the parent-shaped items on the board at the moment of the fetch, so a picker can offer them instead of asking for an id from memory. Never an authority — nothing resolves, validates or refuses against this list, and an item missing from it is one created since the fetch, not a wrong parent. |
| `stateMap` | built-ins | Manifest status → ADO state name, per transition and per kind (`task`/`bug`/**`phase`** — phase items like PBIs carry a *different* state vocabulary than tasks: a Scrum PBI knows New/Approved/Committed/Done and no "In Progress"). A `null` value = *never move state on this transition*. States are always applied by an UPDATE after the create — ADO only allows the initial state at creation. |
| `tag` | `audit-plugin` | Provenance tag stamped on every pushed/echoed item. A per-repo value (e.g. `repo-storefront`) pairs with `pull.tags` so a shared sprint's push and pull are symmetric; explicit `null` = no tag. Always **merged** into the item's existing tags — never replacing them. |
| `onComplete` | `null` | What the done-move writes besides state — today `remainingWork` (present without a value = `0`; explicit `null` = never touch the field). |
| `comments` | none | Generated comments: `onBlocked`, `onComplete` (both default `false`). |
| `sprint` | `null` | `{ "team": "<team>" }` — resolve the team's **current** iteration at push time instead of a static path. |
| `pull` | `null` | Sprint-pull scoping: `areaPath` and/or `tags` (AND-composed). |
| `identityMap` | `null` | Ledger identity (git email/name) → ADO email/UPN. Advisory. |
| `conventions` | `null` | What an item must look like to **belong** on this board: `requiredFields`, `descriptionMustContain`, `tagVocabulary`, `requireParent`. A property of the board, so absent means there is no standard to meet — "there is nothing to check", not "could not check". Graded by `scripts/manifest/_ado_conventions.py`, which is the same code every CREATE is run through before the confirm gate. |
| `fields` | `null` | `{work item type: {ADO field: literal value}}` — what this project **supplies** to a governed board, merged into the create payload *before* `conventions` grades it. Graded by `scripts/manifest/_ado_fields.py`. |

The built-in state defaults (used when `stateMap` is absent):

| Manifest | ADO state |
|---|---|
| task `pending` / `in_progress` / `blocked` / `done` / `cancelled` | `New` / `Active` / `Active` + tag `blocked` / `Closed` / `Removed` |
| bug `open` / `triaged`,`in_progress` / `fixed` / `wontfix` | `New` / `Active` / `Resolved` / `Closed` |

> **`cancelled` is the phase/task twin of a bug's `wontfix`** — the work will not be done,
> and the card follows: `Removed` on both stock processes. Nothing is deleted on either
> side; a cancelled item keeps its history, its commits and its link.

> **These names are Agile-process names.** On a Scrum project a Task has no `Closed`
> state (`To Do / In Progress / Done`) — set `stateMap`, or every done-move will report
> a state rejection and leave the card's state alone. `/audit:doctor` carries this
> advisory whenever `stateMap` is unset.

### The one key that is not under `meta.ado`: `phases[].adoParent`

Where **this** phase hangs, overriding `meta.ado.parentWorkItem` for this phase alone.
It is a **sibling** of the phase's `ado` link and never a field inside it, because the
two are written by different hands: `ado` is a link only `/audit:sync` writes, and
`adoParent` is a declaration — by you, or by a `pull` that read it off the board.

| Written as | Means |
|---|---|
| **absent** | fall through to `meta.ado.parentWorkItem` — byte-identical to the behaviour before the key existed |
| **an object** | `{id, type, title, url, source, observedAt}` — that work item. Only `id` is required; the rest is the **basis**, and `type` is the half the hierarchy check reads. Without it the link reports `not verified` rather than being graded against a guess |
| **explicit `null`** | hangs under nothing, **even when the fallback is set** — uncategorised on purpose, which is a legitimate outcome and never an error |

An object rather than a bare integer because two spellings of one answer are two
answers, and because the push plan, the hierarchy check and `status` all need the
basis beside the id.

With `phaseWorkItems` on, a **task**'s own `adoParent` is inert — the task hangs under
its phase's work item — and `/audit:sync` says so in a warning rather than dropping the
declaration silently. With `phaseWorkItems` false, the same key is read on a task.

Precedence lives in one function (`scripts/manifest/_ado_parent.py`) and every surface
asks it rather than restating it. Ask it yourself, without a push:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-ado-parent.py" \
  <manifest> --all
```

Exit 0 = every in-scope item has a place, **including "no parent anywhere"**. Exit 1 =
a hierarchy violation, and those links are not created. Exit 2 = unreadable input, or a
scope naming nothing — never a pass.

## Recipes

### 1. Bugs only (the classic)

The minimal config above + `/audit:sync push` (bugs is the default scope). Closing a
bug with a recorded fix commit adds the work-item comment `Fixed in <sha>` — that
legacy comment is always on, independent of the `comments` key.

### 2. The whole plan on the board

```json
"ado": { "organization": "contoso", "project": "web-shop",
         "types": { "bug": "Bug", "task": "Task", "pbi": null } }
```

`/audit:sync push all` → each phase becomes a PBI (type auto-detected and written back
into `types.pbi`, inside the same confirmed run), each task/bug a child work item under
it. The board shows your plan as a hierarchy; `/audit:sync push --phase P3` later heals
just that phase's drift cheaply.

### 3. Where audit work hangs

Your board is somebody's tree, and audit work belongs *inside* it rather than beside
it. Four steps, and the first two touch nothing.

**a. Ask the board what its ladder is.** Which work-item type may parent which is a
property of the **project**, not of this plugin: the same organization can run one
project at `bugsBehavior: asRequirements` and the next at `asTasks`, so a ladder
shipped with the plugin would be wrong on the second board and confidently so.

```
/audit:sync parents
```

That caches `meta.ado.hierarchy` (the type ranks) and `meta.ado.parentCandidates` (the
parent-shaped items on the board at that moment), each with a `fetchedAt` and a
one-sentence `basis` naming the query — evidence with no moment is evidence nobody can
age. It is read-only against ADO: it creates no work item, moves none, and writes no
`adoParent`, because a declaration about where work belongs is yours to make. Skip the
step and nothing breaks: every parent link simply reports `not verified`, which is what
a missing basis is for.

The ranks are not transcribed out of that response by hand — `az devops invoke --area
work --resource backlogconfiguration` fetches it and
`resolve-ado-parent.py <manifest> --hierarchy-from <payload>` prints the block, which
is written in verbatim. One consequence of that is visible from outside: the payload
ranks a bug but never names its type, so the rung is filed under **your**
`types.bug`. Rename that key afterwards and the cached rung stops matching — bugs go
back to `not verified` until you re-run the fetch, which is the honest answer rather
than a bug graded against the wrong rank.

**b. Point each phase at its own parent.** Beside the phase's `ado` link, never inside
it:

```json
"phases": [
  { "id": "P1", "title": "Storefront checkout",
    "adoParent": { "id": 103205, "type": "Feature",
                   "title": "Q3 platform hardening", "source": "declared" } },
  { "id": "P2", "title": "Warehouse sync",
    "adoParent": { "id": 104112, "type": "Feature",
                   "title": "Fulfilment reliability", "source": "declared" } },
  { "id": "P3", "title": "Spike: request tracing", "adoParent": null }
]
```

`P3` is the row worth reading twice: an explicit `null` says *this one hangs under
nothing*, even though step **c** sets a fallback. Uncategorised on purpose is an
answer, and the connector treats it as one. `type` and `title` are not decoration —
`type` is the only offline way to know what the parent is, and it is what the
hierarchy check grades against; `title` is what makes a push plan readable
(`#103205 (Q3 platform hardening)`) instead of a bare number.

**c. Keep the fallback for everything that declares nothing.**
`meta.ado.parentWorkItem` is still read and is still the right answer for "all of this
audit hangs under Feature X":

```json
"ado": { "...": "...", "parentWorkItem": 103000 }
```

Nothing about it is deprecated and nothing warns — a warning on a key that is still
the right answer only teaches people to skip warnings.

**d. Read the plan before anything is written.** `/audit:sync push all` prints one line
per item, `<kind> <id> -> #<parent> -- <basis>`, above a head line carrying the
refusals and the uncategorised count — **both printed even at zero**, because a number
that appears only on bad news cannot be told apart from a number nobody computed.
Below them sit the links the type check could not verify, with the reason, and the
equal-rank notes, which are never refusals. The same answer without a push:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-ado-parent.py" \
  <manifest> --all
```

**Why the plugin checks the shape of the tree at all.** ADO does not enforce its own
type hierarchy on an API-created link — measured against a live board on 2026-08-24,
where a Product Backlog Item ended up hanging under a Task that was meant to be its
child, accepted on write and never reported by anything on the ADO side. So the check
lives here or nowhere, in two tiers that fail differently:

- **structural**, offline, and always with a basis — an item declared as its own
  parent, or a pair that would close a loop. It reads only ids the manifest already
  carries, so it needs no cache and no network, and it **refuses**;
- **by rank**, which needs `meta.ado.hierarchy`. A parent below its child is a
  refusal. Equal ranks are a **note and never a refusal** — a Bug under a Product
  Backlog Item is rank 2 under rank 2 wherever `bugsBehavior` is `asRequirements`, and
  teams do that deliberately. With no cached ladder every link reports `not verified`
  and the create proceeds: a missing basis is not evidence of a defect.

A parent is applied at **create** only. Change an `adoParent` afterwards and
`/audit:sync status` reports it as parent drift naming both ids; push leaves it alone,
because the board side may have been moved by a person and re-parenting behind them is
the same override this key exists to undo.

### 4. A governed board: what it refuses, and what you supply

A board with a standard — a description skeleton, a mandatory "Done when", a closed
tag vocabulary, an `Activity` on every Task — needs both halves of this connector.
They are separate keys because they answer separate questions.

**`conventions` is what the board REFUSES.** A property of the board, so an absent
block means there is no standard to meet — "there is nothing to check", not "we could
not check":

```json
"conventions": {
  "requiredFields": { "Task": ["Microsoft.VSTS.Common.Activity"] },
  "descriptionMustContain": { "Product Backlog Item": ["Done when:"] },
  "tagVocabulary": { "type": ["refactor", "bug"], "*": [] },
  "requireParent": true
}
```

Every CREATE is graded against it before the confirm gate, and a refused item is never
offered for creation. `"*"` is the explicit opt-in for bare, unprefixed tags — spelled
rather than implied, because the connector's own provenance tag (`audit-plugin`) has no
prefix, and a vocabulary that admits only prefixed tags would otherwise refuse every item
a push creates while each block validated clean on its own. **Its list restricts like every
other key's**: `"*": []` admits any bare tag, `"*": ["FE", "BE"]` admits only those. The
empty list is the free-form spelling and keeps meaning that.

`requireParent` is what makes recipe 3 compulsory rather than tidy: with it on, the
validator names every item that resolves to no parent at all, and the gate refuses
their creates — so a push would create nothing for them.

**It is scoped to the items this connector parents**, which is phases and — with
`phaseWorkItems` off — tasks. A push creates a **bug** card with no parent link at all
and names no third kind to hang, so reading the key as *every* item made a governed
board one this connector could never receive a bug on, and said so only at create time.
A bug create is exempt now, the gate prints a `NOTE:` naming the rule it did not apply
and the item it did not apply it to, and validation warns up front that this board asks
for a parent the connector cannot supply for those cards. Parent them by hand once they
exist, or leave `requireParent` off if that is not a bargain you want.

**`fields` is what this project SUPPLIES.** Without it the honest block above gated out
every create: the connector's payload is title, description, state, area, iteration,
tags and a parent link, so there was no way to put an `Activity` on a Task, and the
only `conventions` block that let a push through was a deliberately weakened
description of the board. The template is merged into the payload **before** the gate
grades it:

```json
"fields": {
  "Task": { "Microsoft.VSTS.Common.Activity": "Development",
            "Microsoft.VSTS.Scheduling.OriginalEstimate": 4 },
  "Product Backlog Item": { "Microsoft.VSTS.Common.BusinessValue": 100 }
}
```

Keyed by **work item type name** — the same vocabulary `types.{bug,task,pbi}` resolve
to, so a board that renames its types is configured in one vocabulary rather than two.
Values are literals: numbers stay numbers, and there is no substitution language. That
is a decision and not an omission — the fields that would carry manifest data (title,
description, tags) are exactly the ones a template may not name, so a `{taskId}` could
only ever write into a field the connector does not map. A value that *looks* like a
placeholder is warned about and then written to the board exactly as typed, because
`{taskId}` on a card is visible garbage and the silence is the bug.

What the validator refuses, and why each refusal happens at authoring time rather than
at push time:

- **A field the connector already maps** — title, description, repro steps, severity,
  state, area, iteration, tags, work item type, assignee. There is no later state in
  which such a setting quietly starts working: a template winning over one of them
  would make the field mapping in `commands/sync.md` a lie, and losing to one silently
  would make your config one.
- **`Microsoft.VSTS.Scheduling.RemainingWork` is deliberately NOT on that list.** The
  connector writes it at DONE through `onComplete` and never at create — and a
  governed board that requires it *at create* is the exact case this key exists for.
  Seeding it draws a warning about the later overwrite (a second moment, not a
  collision) and both keys stand; `onComplete.remainingWork: null` keeps the seeded
  value.
- **A read-only field, and this is the sentence to take away.**
  `System.BoardColumn` refuses out loud (`TF401326: Invalid field status 'ReadOnly'`).
  `System.Parent`, `System.Id` and `System.CreatedBy` each **create the item, report
  success, and leave the field unset** — a silent no-op reported as a create that
  worked. Measured against a live board on 2026-08-24. For the field people most want
  to set, validation is therefore the only thing that can say anything at all:
  "attempt it and report what ADO said" would report success and no parent. Re-derive
  the list with `az devops invoke --area wit --resource fields --api-version 7.1` and
  keep the entries whose `readOnly` is true.
- **Nothing about the spelling.** ADO resolves a display name as readily as a
  reference name (`Activity` reaching `Microsoft.VSTS.Common.Activity`, measured the
  same day), so both spellings are recognised and compared as whole strings — never by
  last dotted segment, which would refuse a perfectly legal `Custom.Severity` for
  colliding with `Microsoft.VSTS.Common.Severity`.

One thing to get right at push time: `check-ado-item.py` **merges the template into
the payload and hands it back**, so send back what it printed (`MERGED: …`, or
`payload` under `--json`). Sending the payload you wrote instead creates an item
without the fields the gate has just counted as present — which is how a green gate
still lands a non-conforming item.

**The same gate grades the board, and it is a different flag.** `--item` takes a payload
about to be CREATED: the work item type at the top level, a resolved `parent` beside it,
`meta.ado.fields` merged in first, and exit 1 meaning *do not create this*. `--fetched`
takes the rows `fetch-ado-items.py --out` writes — items already ON the board, with the
type and the parent inside `fields` — and asks whether they still conform;
`/audit:sync status` runs it over the payload it has already fetched. Its exit 1 is a
**finding about cards somebody is looking at**, not a refusal of anything, and nothing is
being created, so the template is deliberately not merged: supplying a field the board
does not have would grade a fiction. Exit 2 means a row was not graded at all — an unreadable
payload, or a row carrying no work item type — and it is a missing basis to report, never
a clean board.

Feeding a fetched payload to `--item` is the mistake worth naming, because it failed
*quietly in both directions*: `requireParent` looked for a top-level key that shape does
not have and refused items whose parent was in fact set, while every type-scoped rule
matched nothing and checked nothing. `--item` refuses that shape outright now.

**And a `NOTE:` line beside exit 0 is not a refusal.** When `requireParent` narrows —
a bug create, on a board that asks for a parent on every card — the gate prints which
rule it did not apply and to which item, and `--json` carries it as
`parentRuleExemption`. It moves neither the exit code nor `conforms`. Put it in front of
whoever is confirming the push: a standard that quietly stopped applying is exactly the
silent pass the printing exists to prevent.

### 5. "When a task is done, the card goes to Review with zero remaining work"

The exact scenario this connector was grown for — a process whose Tasks have a
`Review` state:

```json
"ado": {
  "organization": "contoso", "project": "web-shop",
  "stateMap": { "task": { "done": "Review" } },
  "onComplete": { "remainingWork": 0 },
  "comments": { "onComplete": true, "onBlocked": true }
}
```

Now, the moment the orchestrator marks a task done, the echo moves its card to
`Review`, attempts `Remaining Work = 0` **in the same update call**, and comments with
the sign-off note and the task's commit SHA. A blocked task gets its state move, the
`blocked` tag, and a comment carrying attempts, the last technical outcome and the
blockers.

One live-proven nuance about Remaining Work: **both stock processes (Scrum at
`Done`, Agile at `Closed`) force-clear the field at done and refuse the combined
write** — the connector then retries with the state alone and reports the skip.
That is not a loss: the process emptying the field IS "zero remaining"; the
`remainingWork` key matters for custom processes without the clear rule (like the
`Review` state above, which is exactly such a customization).

Two honesty notes, straight from the contract:

- Cards move via **`System.State` only**. If your team's "Review" is a board *column*
  not backed by a state of its own, the connector cannot reach it — it reports the
  rejection instead of faking the move (never writes `WEF_` column fields).
- A transition you want left alone is written as `null`:
  `"stateMap": { "task": { "in_progress": null } }` — "the team moves that card by hand".

### 6. Scrum project

```json
"stateMap": {
  "task": { "pending": "To Do", "in_progress": "In Progress", "blocked": "In Progress", "done": "Done" },
  "bug":  { "open": "New", "triaged": "Approved", "in_progress": "Committed", "fixed": "Done", "wontfix": "Removed" }
}
```

Without this, a Scrum Task's done-move is rejected (`Closed` does not exist there);
push and echo degrade gracefully — the update is retried without the state field and
the report says which map entry to fix — but set the map and it just works.

### 7. Sprints that move by themselves

```json
"ado": { "organization": "contoso", "project": "web-shop",
         "sprint": { "team": "Web Team" } }
```

Every push resolves *Web Team*'s **current** iteration
(`az boards iteration team list --timeframe current`) and stamps pushed items into it;
the stamped path is recorded on each item's link. After a sprint rollover,
`/audit:sync status` prints `sprint drift (push restamps)` for items stamped into the
old sprint, and the next `push` restamps them. If resolution ever fails (team renamed,
no dated iteration), sync warns once and falls back to the static `iterationPath` —
a sprint is decoration on a push, never the reason it aborts.

### 8. One sprint, many repos — pulling only *your* items

A shared sprint holds PBIs for several applications across several repositories. The
pull scoping says which items belong to THIS repo's manifest:

```json
"tag": "repo-storefront",
"pull": { "areaPath": "web-shop\\Storefront", "tags": ["repo-storefront"] }
```

(`tag` closes the loop: your pushes stamp `repo-storefront`, your pulls filter by
it — each repo owns its slice of the shared sprint in both directions.)

- `areaPath` → WIQL `UNDER` filter (ADO's native partitioning axis; falls back to
  `meta.ado.areaPath` when unset). `tags` → `System.Tags CONTAINS` filters. They
  AND-compose; either alone is enough.
- `/audit:sync pull sprint` queries the current sprint's PBIs (+ child tasks) through
  those filters, shows the candidates grouped by PBI, and asks which to import —
  the list is **always** confirmed before anything is written.
- **No filter configured? Pull refuses to import blind.** It lists the sprint
  read-only, requires explicit selection, and offers to persist your choice into
  `meta.ado.pull` so the next pull is scoped.
- Selected PBIs land as **parked proposals** (`origin: "ado:sprint <path>"`), each
  carrying its child tasks with their `ado` links and empty `files` — review and
  `/audit:propose materialize` moves them into the live plan; the imported tasks say
  "scope files/tests before running" for a reason. A re-pull imports nothing: dedup
  scans every link in the manifest, parked proposals included.

### 9. Mapping people

```json
"identityMap": {
  "ana@corp.dev":  "ana.kovacevic@contoso.com",
  "marko@corp.dev": "marko.j@contoso.com"
}
```

The key is always the **ledger identity** — the same form the usage ledger records
authors in and `meta.areas[*].owner` is written in (git `user.email` under the default
`authorMode`). Advisory in every direction:

- **push** proposes `--assigned-to` for creates whose area owner is mapped — one
  batched question per person, never silently, and never on updates (a human may have
  reassigned in ADO; the connector must not fight that);
- **pull** reverse-maps a known ADO assignee into the imported bug's `reportedBy`
  (unknown ones keep the `ado:<name>` prefix; existing rows are never rewritten);
- **status** shows mapped/unmapped owner coverage.

The panel card has a pair editor for this map, with the validator's duplicate-value
warning mirrored live.

**Worked example, straight from the live gate.** Manifest:

```json
"areas": { "gate": { "root": "src", "owner": "gate@local" } },
"ado":   { "...": "...", "identityMap": { "gate@local": "bisevac.ns@gmail.com" } }
```

with phase `P1` tagged `"area": "gate"` and a new task `P1.3` in the push plan.
Push resolved P1's area owner (`gate@local`), found its mapping, and asked ONE
batched question — *"bisevac.ns@gmail.com — owner of area gate — 1 item(s)"* —
before writing anything. Accepting it created the work item with
`--assigned-to bisevac.ns@gmail.com`; the board shows the assignee. In the other
direction, a bug created in ADO assigned to that same identity was imported by
`pull bugs` with `reportedBy: "gate@local"` — the ledger key, recovered by
case-insensitive reverse lookup — so the author/owner filters in status, report
and panel line up with the usage ledger. Declining the question (or an unmapped
owner, reported in one line) creates unassigned, exactly as before.

### 10. Turning it down, or off

```json
"echo": false     // manual-only: nothing automatic, /audit:sync still works
"enabled": false  // full stop: push/pull refuse, echo stops, links are KEPT,
                  // /audit:sync status still reports the frozen links
```

Both are one key in the panel card. Re-enabling needs no repair — push is idempotent
and converges.

## The echo, precisely

Runs only when **all** hold: `meta.ado` exists · `enabled` is not `false` · `echo` is
not `false` · the item already has `ado.id`. Then:

| Transition | Card gets |
|---|---|
| task → done | `stateMap` done-state + `onComplete.remainingWork` (same call) + `onComplete` comment when enabled |
| task → blocked | blocked-state + tag `blocked` + `onBlocked` comment when enabled |
| task reopened (`/audit:run`, human-confirmed) | pending-state + comment `reopened by /audit:run` |
| phase sign-off | the phase PBI moves to the done-state |

What the echo will **never** do: create work items (creation is consent-gated in
`push`), ask questions, retry failures, block or slow a run, or stamp iterations
(sync's job). A failed echo is one report line — `ADO echo: N updated, M skipped
(unlinked), K failed` — and whatever it missed is exactly what the next
`/audit:sync push` reconciles, because board state is externally diffable. Missed
echoes are drift, not loss.

## The panel card

`/audit:panel` → Composition tab → **Azure DevOps connector**. Saving shows dotted
change rows (`meta · ado.enabled  true → false`) and goes through the same validator
the CLI uses, so the two cannot disagree. The banner at the top is computed from
**manifest evidence only** (the panel never calls ADO):

| Banner | Meaning |
|---|---|
| *Not configured* | No `meta.ado`. Nothing syncs. |
| *Turned off* | `enabled: false` — N linked items frozen, links kept. |
| *Configured, but no item has ever synced* | Everything below is configuration, not evidence — run `/audit:sync push`. |
| *Linked: N tasks · M bugs · K phases* | What the file proves, with the newest sync stamp. |

**What `connect` discovered rides the same payload.** The panel authenticates nothing, so
it cannot *run* `connect` — but it can show what `connect` proved, from `meta.ado.connection`
and by the same manifest-evidence-only rule as the banner above. Four named states, because
the ways of knowing nothing are not one way:

| State | Meaning |
|---|---|
| *never probed* | Nobody has run `/audit:sync connect` here. The connector may still be configured and working — what is missing is the evidence, not the connection. |
| *probed, process undecidable* | Access was proven, but the board carries no phase-level item yet (or two). The shipped `stateMap` defaults name Agile states and nothing says whether that fits. |
| *needs a stateMap* | This board runs a non-Agile process and `stateMap` is not set — a task reaching done will be refused its state. Set the map on this same card. |
| *probed, nothing outstanding* | Process, phase-level type, the auth path that answered, and when. |

Every state carries the moment, the basis and `/audit:sync connect` as the command that
re-derives it. The auth path is a **word naming a mechanism** (`stored`, `env`, `signin`) —
never a token and never a person: the panel is a shared screen, and the only useful fact
about a 401 six weeks from now is which *kind* of credential lapsed.

The card also holds **`meta.ado.fields`** — the per-work-item-type template merged into
a create payload before the conformance gate grades it. Type, field and literal value
per row; a value that spells a number exactly is stored as one, so an estimate stays an
estimate. What a template may *not* name (a field the connector already maps, or one ADO
reports read-only) is decided by the manifest validator when you save, not by a second
list in the browser.

**Not every key has a control.** `conventions`, the two `parents` caches and `connection`
are edited in the manifest (or written by the command that owns them), not here. They are **carried through a save untouched** rather than dropped,
because the card's draft is a deep copy of the saved block
(`ADRAFT=saved===null?null:JSON.parse(JSON.stringify(saved))`) and only the paths a
control owns are ever written.

**`phases[].adoParent` is not on this card, and that is deliberate.** `PUT /api/ado`
replaces `meta.ado` and nothing else, so a per-phase control here would describe a write
its own Save cannot make. The card holds the **fallback** (`parentWorkItem`); each
phase's own answer is a column in the Composition table — *use the fallback* (naming
what that currently resolves to), any candidate `/audit:sync parents` last cached,
*none — uncategorised on purpose* (the explicit `null`, which hangs the phase under
nothing even when the fallback is set), or an id typed by hand. A line under the table
says whether a candidate list has ever been fetched, when, and how it was scoped —
because a board with no parent-shaped items and a board nobody has asked are different
answers that would otherwise both arrive as an empty menu.

## CI / headless

Provide a PAT via the `AZURE_DEVOPS_EXT_PAT` secret variable and `/audit:sync` runs
headless — [`docs/examples/azure-pipelines.yml`](examples/azure-pipelines.yml) shows
the validate → gate → report pipeline it slots into. Scope the PAT to Work Items
(Read & Write) + Project and Team (Read); nothing in the connector needs more.

## Troubleshooting

**On a board that has never worked, start with `/audit:sync connect`** — it stops on the
first rung that is not true and says which one, which is the question `doctor` cannot
answer because `doctor` deliberately never phones the board. On a board that *used* to
work, start with `doctor` — the connector has four rows there:

| Row | What it tells you |
|---|---|
| `ado` | Configured? Which switches are in effect (enabled/echo/PBI/sprint)? |
| `ado transport` | `az` + extension present? (A missing az is a warning — MCP may still carry an interactive session.) |
| `ado state map` | The Scrum-vs-Agile advisory when `stateMap` is unset. |
| `ado links` | What the manifest proves: links per kind + newest sync stamp, or "configuration, not evidence". |

Common symptoms:

- **`you need to run the login command`** → this text does **not** mean "not logged in".
  An organization that does not exist produces it identically, so read it as *az could
  not authenticate to this organization* and check the organization name before touching
  any credential. `/audit:sync connect` grades it as exactly that.
- **A `push` or `pull` that worked for weeks starts returning 401** → look at
  `meta.ado.connection.authPath` and `fetchedAt`. `stored` or `env` on a day access was
  proven, failing now, is an **expired token** rather than a broken configuration —
  and everyone's expires on their own schedule, so a teammate's working setup proves
  nothing about yours. There is no expiry date to read: see *What `connect` records*.
- **`state '<X>' rejected`** in a push/echo report → the target process does not
  define that state for that type — remember phase items (PBI/User Story) have a
  different vocabulary than tasks (`stateMap.phase`). List the type's states in ADO
  and set `meta.ado.stateMap`. The item's other fields were still written.
- **`TF401320 Rule Error for field Remaining Work`** → the process force-clears
  Remaining Work at done (both stock processes do). The connector retries
  state-only and reports the skip; the field ends empty, which is the "0 left"
  you wanted.
- **`sprint: unresolvable (team '…')`** in `status` → team renamed or no current
  dated iteration; sync falls back to the static path. Fix `sprint.team` or the
  team's iteration dates.
- **Pull imports nothing** → everything matching your filters is already linked
  (dedup covers parked proposals too). That is the designed steady state.
- **A card someone moved by hand keeps "drifting"** → set that transition to `null`
  in `stateMap`; the connector then leaves that move to the team permanently.
- **Typo'd config key silently ignored?** No — since v2 the validator enumerates
  `meta.ado` keys and warns with did-you-mean (`statemap` → `stateMap`).
- **`a parent must sit ABOVE its child`** in a push plan → the declared parent ranks
  at or below its child on this project's ladder, and the link is refused. Equal ranks
  are a note, never a refusal. Fix the `adoParent`, or re-run `/audit:sync parents` if
  the board's backlog levels have changed since the cache was written.
- **Every parent link says `not verified`** → `meta.ado.hierarchy` has never been
  fetched, so there is no basis for the type check. Run `/audit:sync parents`. The
  creates proceed either way; the structural checks (an item under itself, a declared
  loop) run offline and are unaffected.
- **Only the BUGS say `not verified`** → the cache was fetched under a different
  `types.bug`. The payload ranks a bug and never names its type, so the cached rung
  carries whatever that key said at fetch time, and a rename afterwards leaves the
  ladder keyed to a name no bug row carries. Re-run `/audit:sync parents`.
- **A phase's `adoParent` did nothing for its tasks** → with `phaseWorkItems` on, a
  task hangs under its phase's own work item. A task's own `adoParent` is inert there
  and sync warns about it; move the declaration to the phase, or set `phaseWorkItems`
  to `false`.
- **`parent drift: manifest #a, board #b`** in `status` → a parent is applied at
  create only, so push will not re-parent it. Somebody moved that card, and deciding
  what to do about it is a human's call, not this connector's.
- **`names <field>, which the connector itself maps`** at validation → drop that field
  from `meta.ado.fields`; the manifest key named in the message is what decides it.
- **A `fields` template validated, but the created item came back empty** → the
  payload that was sent was the one you wrote, not the merged one `check-ado-item.py`
  handed back. Send back what it printed.

## Security & non-goals

Credentials are never written to the manifest, the config, or any file, and never
echoed. Work items are never deleted — closing happens via state mapping. No
`WEF_` board-column writes, ever. No silent assignment. No silent **re-parenting**: a
parent is applied at create, and a later change is reported as drift rather than
written behind whoever moved the card. No hierarchy table ships with the plugin, and
none is guessed when the cache is absent. One direction per sync invocation —
conflicts stay human-visible. The full list lives at the end of
[`plugins/audit/commands/sync.md`](../plugins/audit/commands/sync.md).

## JIRA?

Planned as a sibling, not a rewrite: the contract half of
[`tracker-sync.md`](../plugins/audit/reference/tracker-sync.md) is written
tracker-neutrally, and every v2 key name (`enabled`, `echo`, `stateMap`, `sprint`,
`pull`, `onComplete`, `comments`, `identityMap`, `phaseWorkItems`, `types`) transfers
1:1 to a future `meta.jira` — with string keys (`PROJ-123`) in its own `jira` link
field. Not implemented yet.
