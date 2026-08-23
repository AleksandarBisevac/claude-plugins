---
description: 'Sync the audit manifest with Azure DevOps work items — push manifest bugs/tasks/phases to ADO (board states, sprint stamp, Remaining Work, comments), pull assigned ADO bugs or sprint items into the manifest, or show link status. Explicit, idempotent, one direction per invocation; configured via meta.ado.'
argument-hint: 'push [bugs|tasks|all] [--task <id> | --phase <id>] | pull [bugs|sprint] | parents | status'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__azure-devops__wit_*, mcp__azure-devops__work
---

# /audit:sync — Azure DevOps work-item sync

Mirrors the manifest's `bugs[]`, tasks and (via `phaseWorkItems`) phases into Azure
DevOps work items and back. **No background magic**: every invocation does exactly one
direction, shows its plan, and is idempotent (re-running converges; nothing duplicates).
The orchestrator additionally **echoes** already-linked items on status transitions
(update-only — see `orchestrator.md` → "ADO echo"); this command is the reconciler that
heals whatever the echo missed.

**`$ARGUMENTS`**: first token is the subcommand — `push`, `pull`, `parents` or
`status`. Unknown/empty → print usage and stop.

## 0. Preflight

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` and
   `${CLAUDE_PLUGIN_ROOT}/reference/tracker-sync.md` (the shared contract + the ADO
   binding: field reference names, state fallback, parent links, iteration resolution).
   Resolve and read the manifest. Missing → stop, point to `/audit:init`.
2. **`meta.ado` must exist** — else stop and print the setup snippet:
   ```json
   "ado": { "organization": "<org>", "project": "<project>",
            "areaPath": null, "iterationPath": null,
            "types": { "bug": "Bug", "task": "Task" } }
   ```
   (The v2 keys — `stateMap`, `sprint`, `pull`, `onComplete`, `comments`, `echo`,
   `phaseWorkItems`, `enabled` — are optional; the panel's ADO card edits them all.)
3. **`meta.ado.enabled: false` disables writes**: `push` and `pull` STOP with
   `connector disabled — re-enable in the panel's ADO card (or set meta.ado.enabled)`;
   `status` still runs (read-only is the drift lens you need to decide whether to
   re-enable) and leads with `connector DISABLED — N linked item(s) frozen, links kept`.
4. **Transport**: if `mcp__azure-devops__wit_*` / `mcp__azure-devops__work` MCP tools
   are available in this session, you MAY use them (same field mapping below).
   Otherwise use the `az` CLI via Bash:
   `az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>`
   then `az boards ...`. If `az` is missing or the `azure-devops` extension isn't installed,
   STOP with install guidance (`az extension add --name azure-devops`; auth via `az login`,
   or the `AZURE_DEVOPS_EXT_PAT` environment variable in CI).
5. **Credentials are never yours to handle**: never write a PAT/token into the manifest,
   the config, or any file; never echo one (the secret guard blocks it anyway). Auth
   belongs to `az` / the MCP server.
6. After EVERY manifest mutation: revalidate with
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>`.
7. `push`/`pull` write the manifest — hold the **concurrency lock** (see conventions →
   Concurrency lock) around those writes; `status` is read-only and never locks.

## Field mapping (both transports)

| Manifest | ADO (defaults; types from `meta.ado.types`) |
|---|---|
| bug → work item type | `types.bug` (default `Bug`) |
| task → work item type | `types.task` (default `Task`) |
| phase → work item type (`phaseWorkItems`, absent = on) | `types.pbi` (null = auto-detect, see tracker-sync.md) |
| `bug.title` / task: `[<taskId>] <title>` / phase: `[<phaseId>] <title>` | Title |
| `bug.description` + `repro` + `expected`/`actual` | Repro Steps (Bug) / Description |
| `bug.severity` high/med/low | Severity `2 - High` / `3 - Medium` / `4 - Low` |
| bug status (default `open` → `New` · `triaged`/`in_progress` → `Active` · `fixed` → `Resolved` · `wontfix` → `Closed`) | State via `meta.ado.stateMap.bug` |
| task status (default `pending` → `New` · `in_progress` → `Active` · `blocked` → `Active` + tag `blocked` · `done` → `Closed` · `cancelled` → `Removed`) | State via `meta.ado.stateMap.task` |
| phase status via `meta.ado.stateMap.phase` (defaults = the task defaults; NOTE phase-item vocabularies differ — a Scrum PBI knows no "In Progress", see tracker-sync.md) | State |
| task `done` + `meta.ado.onComplete.remainingWork` (default 0 when `onComplete` present) | `Microsoft.VSTS.Scheduling.RemainingWork`, same update call — stock processes REFUSE it (they force-clear the field at done) → retry state-only, report the skip (tracker-sync.md) |
| `meta.ado.areaPath` (when set) | Area |
| resolved sprint (`meta.ado.sprint`) else `meta.ado.iterationPath` (when set) | Iteration |
| `meta.ado.fields.<work item type>` (when set) | those fields verbatim on CREATE — merged by `check-ado-item.py` **before** the conformance gate, so a board that requires e.g. `Microsoft.VSTS.Common.Activity` can be satisfied; a field this table already maps, or one ADO reports read-only, is refused at validation |
| always | provenance tag from `meta.ado.tag` (absent = `audit-plugin`; null = none) — tag writes READ-MERGE-WRITE the item's tag list, never wholesale; comment with `fixedIn` SHA when a bug closes |

A `stateMap` value of `null` = **never move state for that transition** — skip the
State field, the team moves that card by hand. **States are applied by UPDATE, never
at create** — ADO allows only the initial state at creation (tracker-sync.md →
"States are applied by UPDATE"), so every non-initial target is a second call after
the create. A state the process rejects degrades per item (retry without State,
report, hint at `stateMap`) — tracker-sync.md → "Invalid-state fallback". The
built-in defaults name Agile-process states; Scrum projects set `stateMap` (doctor
carries the advisory).

The manifest side of a link is the item's `ado` field — `{id, url, lastSyncedAt}`
(plus `iterationPath` on sprint-stamped items) — **written only by this command and
the orchestrator echo's `lastSyncedAt` bump**, immediately after each successful
create (so an interrupted run resumes idempotently).

## Sprint resolution (shared by push and pull)

When `meta.ado.sprint` is set: resolve the team's CURRENT iteration ONCE per run
(tracker-sync.md → "Current-iteration resolution"); stamp `System.IterationPath` on
creates/updates, and record the stamped path on each touched item's
`ado.iterationPath` (phases included). Resolution failure → ONE warning, fall back to
static `meta.ado.iterationPath` (or no stamp), continue — never abort over a sprint.

## Identity mapping (`meta.ado.identityMap`, advisory)

`meta.ado.identityMap` is an OPTIONAL map from a **ledger identity** — the same form
`usage.authorMode` records authors and `meta.areas[*].owner` is written in (git
`user.email` under the default `email` mode, `user.name` under `name`) — to that
person's ADO identity (email/UPN). The ledger identity is the KEY because it is the
identity this plugin already owns: the usage ledger's author column, area owners and
this map are one namespace, and ADO is the foreign side being mapped to. Advisory
only: nothing in this command gates, refuses or assigns on the map by itself — push
PROPOSES, pull LABELS, status DISPLAYS, and an absent/null/empty map degrades every
flow below to exactly today's behavior. ADO identities compare **case-insensitively**
wherever this command matches them (ADO's directory does).

## Subcommand: `push [bugs|tasks|all]` (default `bugs`)

Optional scope flags: `--task <id>` / `--phase <id>` narrow the plan to one task (or
one phase: its PBI + its tasks/bugs) — the cheap way to heal one item's drift after a
failed echo.

1. **Phase work items** (when `phaseWorkItems` is not `false` and scope includes
   tasks): resolve `types.pbi` — null/absent → auto-detect and WRITE THE PICK BACK
   into `meta.ado.types.pbi` (tracker-sync.md → "Process templates"); the write-back
   happens inside this confirm-gated, index-locked run. Every in-scope phase lacking
   `phase.ado` gets a CREATE in the plan.

   **Where that branch hangs — per item, resolved by one function.** A phase may
   declare its own `adoParent`; `meta.ado.parentWorkItem` is the manifest-wide
   FALLBACK, still read and still the right answer for "all of this audit hangs
   under Feature X". Do NOT re-derive the precedence here — run the door, which is
   the same code the validator and the panel ask:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-ado-parent.py" \
     <manifest> [--all | --phase <id> | --task <id>] [--json]
   ```

   Exit 0 = every in-scope item has a place (**including "no parent anywhere"** —
   uncategorised work is an answer and a create, not an error). **Exit 1 = a
   hierarchy violation: do NOT create those parent links**, carry the findings into
   the plan below. Exit 2 = unreadable input or a scope naming nothing — stop, and
   never read it as a pass.

   The rules it applies, so the plan can be read: a task under `phaseWorkItems`
   hangs under its phase's work item and its own `adoParent` is INERT (warned, not
   ignored); an item's own `adoParent` beats the fallback; an explicit `null` means
   it hangs under nothing *even when the fallback is set*; absent falls through to
   `meta.ado.parentWorkItem`; neither is a free-standing branch nobody planning from
   that board will see.
2. Build the plan: for each in-scope item —
   - `item.ado` **null/absent** → CREATE (`az boards work-item create --type <type>
     --title ... --fields ... --output json`);
   - `item.ado.id` set → fetch current (`az boards work-item show --id <id> --output json`),
     **diff the mapped fields**, and only when something differs → UPDATE
     (`az boards work-item update`). No-op items are skipped.

   The fetch above already returns `System.ChangedBy` and `System.ChangedDate`;
   keep them, they are what step 2c reads.
2c. **Whose card is this, and who moved it last — every UPDATE, before the confirm.**
   Write the items you fetched as a JSON list (each `{id, fields, mapped}`, where
   `mapped` is the `stateMap`-translated status from the table above) and run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/explain-ado-drift.py" \
     <manifest> --items <fetched.json>
   ```

   Exit 0 = answered; **exit 2 = could not read the input, so stop rather than
   push blind**. There is no exit 1: "somebody else moved this card" is the normal
   state of a board several teams write to, and refusing over it would make this
   command useless where it matters most. Do not reimplement the comparison here —
   `_ado_drift` owns it, and a second copy in prose is a second answer.
2b. **Conformance gate — every CREATE, before the confirm.** `meta.ado.conventions`
   says what an item must look like to BELONG on this board (skeleton, mandatory
   markers, tag vocabulary, parent). For each CREATE, write the payload you are about
   to send and run:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/check-ado-item.py" \
     <manifest> --item <payload.json>
   ```

   Exit 0 = create it. **Exit 1 = do NOT create it**; carry its findings into the plan
   printed below so the operator sees the refusal before deciding anything, not after
   the item is on the board. Exit 2 is unreadable input — stop, do not treat it as a
   pass. A board with no `conventions` block exits 0 and says nothing was checked;
   that is an answer ("this board has no standard"), not a silent success.

   **The command MERGES `meta.ado.fields` into the payload before it grades it, so
   send back what it hands you** — the fields it printed (`MERGED: …`), or `payload`
   under `--json`. Sending the payload you wrote instead creates an item without the
   fields the gate just counted as present, which is how a green gate still lands a
   non-conforming item. A malformed `meta.ado.fields` is exit 2, not 1: the config
   could not be applied, which is not the item's fault.

   **Do not reimplement the rule here.** It is Python with cases precisely because
   prose cannot be tested — a second copy in this file is a second answer, and the
   first time they disagree the board is what tells you.

3. Print the plan (`N creates [of which K PBIs], M updates, J in sync`, plus the
   `types.pbi` auto-detect pick when it happened, plus `R refused by
   meta.ado.conventions` with each item's findings when the gate refused any) and
   **confirm via AskUserQuestion before the first write** — ADO writes are
   outward-facing and visible to the whole team. A refused item is never offered for
   creation; fix the manifest (or the conventions) and re-run.

   Carry step 2c's answer into that plan, because it is the part the confirm gate
   exists for:
   - the count line, **printed even when it is zero** — `K update(s) would
     overwrite a change made after our last sync` — with the ids, the writer's name
     and the moment for each. A number that appears only on bad news cannot be told
     apart from a number nobody computed;
   - per UPDATE row, whose card it is: `created here` / `imported from ADO` /
     `origin unknown (link written before the field existed)`.

   **This changes nothing about what the command may do.** No extra question, no
   refusal, no new switch: several writers on one board is normal, and this plugin
   does not arbitrate who owns a card. It just stops describing somebody else's
   card as if it were ours, and stops reporting a difference as if only two
   readings existed.

3b. **The parent block, printed verbatim from the door.** `resolve-ado-parent.py`
   emits one line per item — `<kind> <id> -> #<parent> -- <basis>` — plus a head
   line carrying BOTH counts, `R refused by the hierarchy check` and `U
   uncategorised (no parent anywhere)`, **and both are printed even at zero**: a
   number that appears only on bad news cannot be told apart from a number nobody
   computed, and the confirm gate is where the operator has no other way to learn
   the check ran. Below them come the links the type check could not verify, with
   the reason (`meta.ado.hierarchy` not cached → run `/audit:sync parents`), and the
   equal-rank NOTES, which are never refusals.

   Do not re-render those lines — paste what the door printed. A second rendering
   is a second answer, and the first thing to disagree would be a count.

   A refused item is never offered for creation, exactly like a
   `meta.ado.conventions` refusal: fix the declaration (or the board) and re-run.
4. **Assignment proposal** (only when `meta.ado.identityMap` has entries): for each
   CREATE in the plan, resolve the item's phase — a task's own phase; a bug reaches a
   phase only through its materialized `taskId` (an unmaterialized bug has no phase and
   draws no proposal). Resolve that phase's area **owner** the way every other surface
   does (`meta.areas`, written order; explicit `owner: null` is an answer — "nobody owns
   this" — and stops the lookup). An owner WITH an identityMap entry gives the item a
   proposed assignee. Then ask ONE AskUserQuestion, **batched by proposed assignee**
   (multi-select; one option per assignee: `<mapped ADO identity> — owner of area <tag>
   — N item(s)`; more than 4 distinct assignees → chunk into further questions):
   accepted groups get `--assigned-to <mapped>` on their creates, declined groups are
   created unassigned as today. Batched because a push routinely carries many same-area
   items and the decision is per-person, not per-item — asking the same question N times
   trains the user to stop reading it. **Never assign silently**: no accepted answer, no
   `--assigned-to`. When an owner exists but has NO identityMap entry, say so in one
   line — `owner <ledger id> (area <tag>) has no identityMap entry — no assignment
   proposed` — so the missing mapping is visible instead of silently skipped. UPDATEs
   never get an assignment proposal: the ADO-side assignee may have been set by a human
   in ADO since the create, and this command must not fight that — assignment is
   proposed at an item's birth only.
5. Execute item by item, phases first. After each successful create, IMMEDIATELY Edit
   the manifest: `item.ado = {id, url, lastSyncedAt: <ISO now>, origin: "created"}`
   (then revalidate).
   After each update, bump `lastSyncedAt` — and **never touch `origin` on an
   update**: where a card came from does not change, and rewriting it on the first
   push after an import would erase the only record that it was somebody else's.
   A link that carries no `origin` (written before the field existed) stays without
   one rather than being backfilled with a guess. On any failure: report it, keep
   what succeeded, stop — a re-run continues where it left off. Per item:
   - **State** per `stateMap` (defaults above; `null` = skip State), applied as a
     SECOND call after the create (only the initial state is settable at creation);
     a rejected state degrades per tracker-sync.md and never aborts the batch.
   - **Sprint stamp** per "Sprint resolution" above.
   - **Remaining Work**: a task moving to its done-state with `onComplete` configured
     attempts `remainingWork` (default 0; explicit `null` = never) in the SAME update
     as the state; a field-rule refusal (stock processes force-clear it at done) →
     retry state-only, report the skip.
   - **Tags**: read the item's current tags, merge in the provenance tag
     (`meta.ado.tag`; absent = `audit-plugin`, null = none), write the union —
     never write the tag list blind.
   - **Parent links**: the resolved parent from step 1 for each phase (and, with
     `phaseWorkItems` false, each task); with `phaseWorkItems` on, each of a phase's
     children is linked to the phase PBI after it exists. **The argument contract
     and the read-back are in tracker-sync.md → "Parent links"** and are not
     restated here, because a second spelling of that call is where a swap hides.
     Three things are non-negotiable at this step:
     - **the item being UPDATED is the CHILD** — both transports agree, and the
       table there shows them side by side;
     - **read `System.Parent` back off the child and assert it equals the intended
       parent.** A swapped call SUCCEEDS — both ids are legal work items and the
       response says nothing about direction — so the read-back is the only thing
       that catches it. It is one field on an item this step already touched;
     - **a mismatch, or a link the server rejects, degrades PER ITEM**: report it
       with both ids, keep the item and everything that succeeded, and continue —
       the same shape as the invalid-state fallback. Never abort the batch over a
       parent link.
     Read existing relations first and skip when the link is already there.
     **A parent is applied at CREATE only.** A changed `adoParent` on an
     already-linked item is reported by `status` as parent drift and never silently
     re-parented: the board side may have been moved by a person, and re-parenting
     behind their back is the same override this feature exists to undo.
   - **Comments** (opt-in via `meta.ado.comments`): `onBlocked` → on a task entering
     its blocked-state, comment with attempts, last `outcome.technical` and blockers;
     `onComplete` → on the done move, comment with the sign-off note and the task's
     `commit` SHA. Generated comments name their actor (`audit-plugin`).
6. When pushing a `fixed` bug with `fixedIn`, add a work-item comment
   (`az boards work-item update --id <id> --discussion "Fixed in <sha>"`) — this
   legacy comment is unconditional, independent of `meta.ado.comments`.
7. Report: table of `manifest id | ado id | action taken` (assigned-to and sprint
   stamp noted where applied).

## Subcommand: `pull [bugs|sprint]` (default `bugs`)

**Dedup rule (both flavors)**: a candidate whose id appears in ANY manifest `ado.id`
— live tasks, bugs, phases, AND parked `proposals[].payload` items — is dropped. A
re-pull imports nothing. Never modify ADO during `pull`.

### `pull bugs`

1. Query candidate bugs, **selecting the parent in the SAME query** — WIQL can
   `SELECT [System.Parent]`, so capturing where a card already hangs costs nothing
   and adds no per-item call:
   `az boards query --wiql "SELECT [System.Id], [System.Parent] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] = '<types.bug>' AND [System.State] <> 'Closed'"`
   (add an AreaPath clause when `meta.ado.areaPath` is set).
2. Drop already-linked items (dedup rule above).
3. For each remaining item, show `id | title | state | assignee` and ask
   (AskUserQuestion, multi-select) which to import.
4. Import each selected item as a manifest bug following `/audit:bug add`'s shape and the
   conventions doc: next `BUG-<n>`, `status: "open"`, title/description from the work
   item, `repro` from its repro steps,
   `ado: {id, url, lastSyncedAt, origin: "imported"}` — the card was made by
   somebody else and a later push has to be able to say so.
   **When the card has a board parent, write `adoParent: {id, type, title, url,
   source: "imported", observedAt: <ISO now>}`** — a SIBLING of `ado`, never a field
   inside it, because `ado` is the link sync writes and `adoParent` is a declaration
   about where the work belongs. **A card with NO parent gets no `adoParent` key at
   all — not `null`.** Absent means "fall through to `meta.ado.parentWorkItem`";
   `null` means "hangs under nothing", and a pull is not entitled to make that
   declaration on the operator's behalf. `type` and `title` come from the same
   fetch; they are the BASIS the hierarchy check reads, and without them every link
   reports `not verified`. `reportedBy`
   comes from the work item's assignee (creator when unassigned) via **reverse lookup**
   in `meta.ado.identityMap`: when some entry's VALUE matches that ADO identity
   (case-insensitively), write the LEDGER identity — the key — so the imported bug's
   `reportedBy` speaks the same form the usage ledger's author column and
   `meta.areas[*].owner` do, and the author/owner filters in status/report/panel line
   up. Two keys sharing one value (the validator warns about that map) → the FIRST in
   map order wins; name the pick in the report. No matching entry → today's
   `reportedBy: "ado:<assignee-or-creator>"`, unchanged. The lookup applies ONLY to the
   bug being imported right now: **existing manifest rows are never rewritten** — not by
   `pull`, not by a later identityMap edit. `reportedBy` is a record of what was known
   at import time, not a live view. Revalidate.
5. Report + handoff: `/audit:bug fix BUG-<n>` to materialize a fix task.

### `pull sprint`

Imports the current sprint's PBIs and tasks as **parked proposals** — nothing enters
the live plan without `/audit:propose materialize`.

1. Resolve the iteration: `meta.ado.sprint` set → current-iteration resolution;
   else `meta.ado.iterationPath` set → use it; else STOP — a sprint pull needs an
   iteration to pull from.
2. **Scope the query** — one sprint can span multiple repos, and the filters say
   which items belong to THIS manifest: `meta.ado.pull.areaPath` (falls back to
   `meta.ado.areaPath`) → `[System.AreaPath] UNDER '<path>'`; each `meta.ado.pull.tags`
   entry → `[System.Tags] CONTAINS '<tag>'`. Filters AND-compose. **No filter
   configured → refuse to import blind**: list the sprint's items read-only, require
   explicit selection (picked items or entered ids), and OFFER to persist the chosen
   filter into `meta.ado.pull` (a manifest edit, under the lock, revalidated).
3. Query `<types.pbi>` items in the iteration (WIQL on `[System.IterationPath]`),
   plus their child tasks (relations); apply the dedup rule.
4. Show candidates grouped by PBI (`id | title | state | children`) and ask
   (AskUserQuestion, multi-select) which PBIs to import.
5. Import each selected PBI as ONE parked proposal (conventions doc → Proposals):
   next `PROP-<n>`, `origin: "ado:sprint <iterationPath>"`, `payload.phase` = a
   synthesized phase with the next reserved `P<n>` id, title from the PBI,
   `ado: {id, url, lastSyncedAt, iterationPath, origin: "imported"}` on the phase
   (the proposal's own `origin` above says which SPRINT it came from; `ado.origin`
   says who made the CARD, and both are needed once a push starts writing to it),
   plus `adoParent` on the phase when the PBI has a board parent — same rule and
   same reason as `pull bugs` above: `SELECT [System.Parent]` in the same query, no
   key at all when there is none,
   child tasks from the PBI's child work items (each carrying its own `ado` link
   with `origin: "imported"`, `files: []`), and a
   description noting `imported from ADO — scope files/tests before running`. Orphan
   sprint tasks (no selected parent) group under one final proposal. Revalidate.
6. Report + handoff: `/audit:propose list` → `materialize`.

## Subcommand: `parents`

**Read-only against ADO.** It writes exactly two keys of the manifest —
`meta.ado.hierarchy` and `meta.ado.parentCandidates` — under the concurrency lock,
and revalidates after. It creates nothing, updates no work item, and changes no
`adoParent`: a declaration about where work belongs is the operator's, and a fetch
is not entitled to make one.

Both keys are **cached evidence**, so both carry a `fetchedAt` and a one-sentence
`basis` naming the query. Evidence with no moment cannot be aged, and evidence with
no basis has to be trusted rather than checked.

1. **The ladder** — which work item type may parent which, asked of THIS project:

   ```bash
   az devops invoke --area work --resource backlogconfiguration \
     --route-parameters project=<project> --api-version 7.1
   ```

   Write `meta.ado.hierarchy = {levels: {<type>: <rank>}, fetchedAt, basis}` from
   `taskBacklog`, `requirementBacklog` and each `portfolioBacklogs[]` — and place
   `Bug` from the payload's `bugsBehavior`, which is the only field that says where
   it goes (the type lists do not name it). tracker-sync.md → "Backlog levels"
   carries the shape. **No table ships with the plugin**: the same organization runs
   one project at `asRequirements` and another at `asTasks`, so a shipped ladder
   would be wrong on the second board and confidently so.

2. **The candidates** — the parent-shaped items on this board right now, so a picker
   can offer them instead of asking for an id from memory. WIQL over the types that
   rank ABOVE the audit's own (from step 1), scoped by `meta.ado.pull.areaPath` or
   `meta.ado.areaPath` when either is set:

   ```
   SELECT [System.Id], [System.WorkItemType], [System.Title], [System.State], [System.AreaPath]
   FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] IN (...)
   ```

   Write `meta.ado.parentCandidates = {items: [{id, type, title, state, areaPath,
   url}], fetchedAt, basis}`. **Never an authority**: nothing resolves, validates or
   refuses against this list, and an item missing from it is not a wrong parent —
   only one created since the fetch. Say how the list was scoped in `basis`, so an
   empty list can be told from an unfiltered one.

3. Report what was written, then run the resolver over the whole plan so the
   operator sees what the new ladder changes:
   `resolve-ado-parent.py <manifest> --all`. A link that read `not verified` before
   this run may now be a NOTE or a refusal, and that is the point of having fetched.

## Subcommand: `status`

Read-only, no ADO writes, no manifest writes.
1. Lead with the connector line: `enabled`/`echo`/`phaseWorkItems` state (and the
   DISABLED banner from Preflight 3 when off), `sprint: <resolved path>` or
   `sprint: unresolvable (team '<t>')` when resolution fails.
2. Count linked vs unlinked bugs/tasks/phases.
3. For linked items, batch-fetch the ADO side (`az boards work-item show`) and print:
   `manifest id | title | manifest status | ado id | ado state | drift?` — drift = the
   `stateMap`-mapped state differs from the ADO state. Add sprint drift where stamped:
   `ado.iterationPath` ≠ the currently-resolved iteration → `sprint drift (push restamps)`.

   **A difference has THREE readings, not two**, and the third is the common one on
   a board several teams write to: somebody else moved this card after we last
   touched it, and neither side is wrong. Do not decide that here — run the same
   door push step 2c runs (`explain-ado-drift.py <manifest> --items <fetched.json>`,
   `--json` when you want to compose the table yourself) and print what it answers
   in the `drift?` cell:
   - `local ahead — push is the fix` (nobody wrote after our `lastSyncedAt`);
   - `external (<who>, <when>) — push would overwrite it`, naming the writer from
     `System.ChangedBy` so the reader can go and ask that person;
   - `unknown — never synced or unstamped`, which draws **no** suggested action:
     the basis for one is missing, and saying so is the answer.

   Append each row's card provenance from `ado.origin` — `created here` /
   `imported from ADO` / `origin unknown` — because "we made this card" and "we
   adopted somebody's card" are different things to be about to write to.
3b. **Parent drift** — one more cell on the same row, `parent?`. A parent is
   applied at CREATE only, so a linked item whose `adoParent` no longer matches the
   board is a difference to REPORT and never one to fix silently: the card may have
   been moved by a person, and re-parenting behind them is the same override this
   feature exists to undo. From the `System.Parent` you already fetched in step 3
   (it comes back on a plain `show`, no `--expand relations`) against the resolved
   parent from `resolve-ado-parent.py --json`:
   - `parent ok` — they agree;
   - `parent drift: manifest #<a>, board #<b> — applied at create only, so push
     will NOT re-parent` — say both ids and say that push leaves it alone, or the
     reader will wait for a fix that is not coming;
   - `parent: none declared, board #<b>` — the board hangs it somewhere this
     manifest does not describe, which is information and not a defect;
   - `parent: #<a> declared, board none` — declared but never applied, usually an
     item linked before the declaration was written.

   Close with the counts, **printed even at zero**: `parents: N ok, M drifted, K
   uncategorised`. Suggest nothing per row here — `status` is read-only, and the
   remedy for real drift is a human decision about somebody's board.

4. **Identity mapping** (only when `meta.ado.identityMap` has entries): per item, append
   one compact `owner` column to the table above, resolving the item's phase-area owner
   exactly as push step 4 does — `<ledger id> → <mapped ADO identity>` when mapped,
   `<ledger id> (unmapped)` when an owner exists without an entry, `—` when no owner
   resolves. Close with one summary line: `identityMap: N owner(s) mapped, M unmapped`
   (distinct owners across the areas in play). Display only — `status` stays read-only
   and proposes nothing here; an unmapped owner is push's business.
5. **Conformance of what is already there** (only when `meta.ado.conventions` is set).
   For each linked item you fetched in step 3, run the same gate over the ADO side's
   own fields and append `conforms` / `N violation(s)` to its row, closing with
   `conventions: N of M linked item(s) conform`.

   This is the half that makes the push gate honest. The gate above lives in prose,
   and prose is the one surface here nothing can test — so *did the orchestrator
   actually run it* is unprovable at the point of writing. It is provable afterwards:
   a non-conforming item sitting on the board is evidence the check was skipped, and
   this line is where that shows up. Read-only as the rest of `status` is — it reports,
   it never fixes.

6. Suggest the next action (`push` / `pull`) **per drift class, not per
   difference** — that distinction is the whole point of step 3. `local ahead` →
   `push`. `external` → say what each choice costs (`push` overwrites their change,
   editing the manifest keeps it) and let the human pick; recommending `push` here
   would be recommending that somebody's work be overwritten sight unseen.
   `unknown` → suggest nothing and say why, then close with the origin split so a
   reader knows how much of this board is even ours.

## Non-goals (say no when asked)

- No two-way merge in one run — one direction per invocation keeps conflicts human-visible.
- No deletion of ADO work items, ever. Closing happens via state mapping.
- No syncing of `deferred` — and `proposals` sync only in the ONE direction `pull
  sprint` creates them; they become pushable work items after materialization.
- No board-column (`WEF_`) writes, ever — cards move via `System.State` only, and a
  column not backed by a state is reported as unreachable, not faked (tracker-sync.md).
- No creation from the orchestrator echo — the echo UPDATES linked items only;
  creation lives here, behind this command's confirm gate.
- No silent RE-parenting. A parent is applied at CREATE; a changed `adoParent` on a
  linked item is reported as drift by `status` and left alone, because the board side
  may have been moved by a person and this command does not fight that.
- No hierarchy table shipped with the plugin, and no guessing when the cache is
  absent: `parents` asks the project, and an unfetched ladder reports every link as
  `not verified` while the create proceeds. A missing basis is a thing to say.
- No silent assignment from `identityMap`, and no `task.assignee` field — the map lives
  in `meta.ado`, push asks before every `--assigned-to`, and pull labels new imports
  without ever rewriting existing rows.
