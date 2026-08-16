# The Azure DevOps connector — a field guide

How to wire the audit manifest to an Azure DevOps board: setup, every configuration
key with an example, recipes for the common team shapes, what updates automatically,
and what to do when something drifts. The normative contract behind all of it lives in
[`plugins/audit/reference/tracker-sync.md`](../plugins/audit/reference/tracker-sync.md);
this guide is the tutorial layer.

## What it does

Four flows, and only one of them is automatic:

| Flow | Command | Direction | What happens |
|---|---|---|---|
| **Push** | `/audit:sync push [bugs\|tasks\|all]` | manifest → ADO | Creates/updates work items (optionally one PBI per phase with its items parent-linked). Shows the plan, asks before the first write. |
| **Pull** | `/audit:sync pull [bugs\|sprint]` | ADO → manifest | Imports unlinked ADO bugs as manifest bugs, or the current sprint's PBIs/tasks as **parked proposals**. Never modifies ADO. |
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
   scope is **Work Items (Read & Write)** plus **Project and Team (Read)** (the latter
   for sprint resolution).

3. `/audit:doctor` verifies the setup offline: transport present, switches in effect,
   what the links prove. Run it first when anything looks wrong.

## Five-minute start

Add the minimal block to your manifest's `meta` (or open `/audit:panel` → Composition
tab → **Azure DevOps connector** card, which edits the same block with validation):

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

## Configuration reference

All keys live under `meta.ado`. Everything beyond `organization`/`project` is optional;
**absent keys mean today's defaults**, so a pre-v2 config keeps behaving exactly as it
did — with one deliberate exception, `echo`, which is ON by default (set it to `false`
for manual-only sync).

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
| `stateMap` | built-ins | Manifest status → ADO state name, per transition and per kind (`task`/`bug`/**`phase`** — phase items like PBIs carry a *different* state vocabulary than tasks: a Scrum PBI knows New/Approved/Committed/Done and no "In Progress"). A `null` value = *never move state on this transition*. States are always applied by an UPDATE after the create — ADO only allows the initial state at creation. |
| `tag` | `audit-plugin` | Provenance tag stamped on every pushed/echoed item. A per-repo value (e.g. `repo-storefront`) pairs with `pull.tags` so a shared sprint's push and pull are symmetric; explicit `null` = no tag. Always **merged** into the item's existing tags — never replacing them. |
| `onComplete` | `null` | What the done-move writes besides state — today `remainingWork` (present without a value = `0`; explicit `null` = never touch the field). |
| `comments` | none | Generated comments: `onBlocked`, `onComplete` (both default `false`). |
| `sprint` | `null` | `{ "team": "<team>" }` — resolve the team's **current** iteration at push time instead of a static path. |
| `pull` | `null` | Sprint-pull scoping: `areaPath` and/or `tags` (AND-composed). |
| `identityMap` | `null` | Ledger identity (git email/name) → ADO email/UPN. Advisory. |

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

### 3. "When a task is done, the card goes to Review with zero remaining work"

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

### 4. Scrum project

```json
"stateMap": {
  "task": { "pending": "To Do", "in_progress": "In Progress", "blocked": "In Progress", "done": "Done" },
  "bug":  { "open": "New", "triaged": "Approved", "in_progress": "Committed", "fixed": "Done", "wontfix": "Removed" }
}
```

Without this, a Scrum Task's done-move is rejected (`Closed` does not exist there);
push and echo degrade gracefully — the update is retried without the state field and
the report says which map entry to fix — but set the map and it just works.

### 5. Sprints that move by themselves

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

### 6. One sprint, many repos — pulling only *your* items

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

### 7. Mapping people

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

### 8. Turning it down, or off

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

`/audit:panel` → Composition tab → **Azure DevOps connector**. Every key above is a
control; saving shows dotted change rows (`meta · ado.enabled  true → false`) and goes
through the same validator the CLI uses, so the two cannot disagree. The banner at the
top is computed from **manifest evidence only** (the panel never calls ADO):

| Banner | Meaning |
|---|---|
| *Not configured* | No `meta.ado`. Nothing syncs. |
| *Turned off* | `enabled: false` — N linked items frozen, links kept. |
| *Configured, but no item has ever synced* | Everything below is configuration, not evidence — run `/audit:sync push`. |
| *Linked: N tasks · M bugs · K phases* | What the file proves, with the newest sync stamp. |

## CI / headless

Provide a PAT via the `AZURE_DEVOPS_EXT_PAT` secret variable and `/audit:sync` runs
headless — [`docs/examples/azure-pipelines.yml`](examples/azure-pipelines.yml) shows
the validate → gate → report pipeline it slots into. Scope the PAT to Work Items
(Read & Write) + Project and Team (Read); nothing in the connector needs more.

## Troubleshooting

Start with `/audit:doctor` — the connector has four rows there:

| Row | What it tells you |
|---|---|
| `ado` | Configured? Which switches are in effect (enabled/echo/PBI/sprint)? |
| `ado transport` | `az` + extension present? (A missing az is a warning — MCP may still carry an interactive session.) |
| `ado state map` | The Scrum-vs-Agile advisory when `stateMap` is unset. |
| `ado links` | What the manifest proves: links per kind + newest sync stamp, or "configuration, not evidence". |

Common symptoms:

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

## Security & non-goals

Credentials are never written to the manifest, the config, or any file, and never
echoed. Work items are never deleted — closing happens via state mapping. No
`WEF_` board-column writes, ever. No silent assignment. One direction per sync
invocation — conflicts stay human-visible. The full list lives at the end of
[`plugins/audit/commands/sync.md`](../plugins/audit/commands/sync.md).

## JIRA?

Planned as a sibling, not a rewrite: the contract half of
[`tracker-sync.md`](../plugins/audit/reference/tracker-sync.md) is written
tracker-neutrally, and every v2 key name (`enabled`, `echo`, `stateMap`, `sprint`,
`pull`, `onComplete`, `comments`, `identityMap`, `phaseWorkItems`, `types`) transfers
1:1 to a future `meta.jira` — with string keys (`PROJ-123`) in its own `jira` link
field. Not implemented yet.
