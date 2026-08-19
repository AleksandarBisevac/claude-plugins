---
description: 'Sync the audit manifest with Azure DevOps work items — push manifest bugs/tasks/phases to ADO (board states, sprint stamp, Remaining Work, comments), pull assigned ADO bugs or sprint items into the manifest, or show link status. Explicit, idempotent, one direction per invocation; configured via meta.ado.'
argument-hint: 'push [bugs|tasks|all] [--task <id> | --phase <id>] | pull [bugs|sprint] | status'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__azure-devops__wit_*, mcp__azure-devops__work
---

# /audit:sync — Azure DevOps work-item sync

Mirrors the manifest's `bugs[]`, tasks and (via `phaseWorkItems`) phases into Azure
DevOps work items and back. **No background magic**: every invocation does exactly one
direction, shows its plan, and is idempotent (re-running converges; nothing duplicates).
The orchestrator additionally **echoes** already-linked items on status transitions
(update-only — see `orchestrator.md` → "ADO echo"); this command is the reconciler that
heals whatever the echo missed.

**`$ARGUMENTS`**: first token is the subcommand. Unknown/empty → print usage and stop.

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

   **Where that branch hangs.** With `meta.ado.parentWorkItem` set, every created
   phase item gets it as its parent (and with `phaseWorkItems` false, tasks do), so
   audit work lands INSIDE the team's existing Feature/Epic rather than beside it.
   Absent/null keeps today's behaviour — the connector builds a free-standing branch,
   which is correct and which nobody planning from that board will see. Say which
   happened in the plan: `parent: #<id>` or `parent: none (free-standing branch)`.
2. Build the plan: for each in-scope item —
   - `item.ado` **null/absent** → CREATE (`az boards work-item create --type <type>
     --title ... --fields ... --output json`);
   - `item.ado.id` set → fetch current (`az boards work-item show --id <id> --output json`),
     **diff the mapped fields**, and only when something differs → UPDATE
     (`az boards work-item update`). No-op items are skipped.
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

   **Do not reimplement the rule here.** It is Python with cases precisely because
   prose cannot be tested — a second copy in this file is a second answer, and the
   first time they disagree the board is what tells you.

3. Print the plan (`N creates [of which K PBIs], M updates, J in sync`, plus the
   `types.pbi` auto-detect pick when it happened, plus `R refused by
   meta.ado.conventions` with each item's findings when the gate refused any) and
   **confirm via AskUserQuestion before the first write** — ADO writes are
   outward-facing and visible to the whole team. A refused item is never offered for
   creation; fix the manifest (or the conventions) and re-run.
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
   the manifest: `item.ado = {id, url, lastSyncedAt: <ISO now>}` (then revalidate).
   After each update, bump `lastSyncedAt`. On any failure: report it, keep what
   succeeded, stop — a re-run continues where it left off. Per item:
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
   - **Parent links** (`phaseWorkItems`): after a phase's children exist, link each to
     the phase PBI (`az boards work-item relation add --id <child> --relation-type
     parent --target-id <pbi>`) — read existing relations first, skip if linked.
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

1. Query candidate bugs:
   `az boards query --wiql "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] = '<types.bug>' AND [System.State] <> 'Closed'"`
   (add an AreaPath clause when `meta.ado.areaPath` is set).
2. Drop already-linked items (dedup rule above).
3. For each remaining item, show `id | title | state | assignee` and ask
   (AskUserQuestion, multi-select) which to import.
4. Import each selected item as a manifest bug following `/audit:bug add`'s shape and the
   conventions doc: next `BUG-<n>`, `status: "open"`, title/description from the work
   item, `repro` from its repro steps, `ado: {id, url, lastSyncedAt}`. `reportedBy`
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
   `ado: {id, url, lastSyncedAt, iterationPath}` on the phase, child tasks from the
   PBI's child work items (each carrying its own `ado` link, `files: []`), and a
   description noting `imported from ADO — scope files/tests before running`. Orphan
   sprint tasks (no selected parent) group under one final proposal. Revalidate.
6. Report + handoff: `/audit:propose list` → `materialize`.

## Subcommand: `status`

Read-only, no ADO writes, no manifest writes.
1. Lead with the connector line: `enabled`/`echo`/`phaseWorkItems` state (and the
   DISABLED banner from Preflight 3 when off), `sprint: <resolved path>` or
   `sprint: unresolvable (team '<t>')` when resolution fails.
2. Count linked vs unlinked bugs/tasks/phases.
3. For linked items, batch-fetch the ADO side (`az boards work-item show`) and print:
   `manifest id | title | manifest status | ado id | ado state | drift?` — drift = the
   `stateMap`-mapped state differs from the ADO state (fix by running `push`, or by
   updating the manifest if ADO is the truth). Add sprint drift where stamped:
   `ado.iterationPath` ≠ the currently-resolved iteration → `sprint drift (push restamps)`.
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

6. Suggest the next action (`push` / `pull`) based on what drifted.

## Non-goals (say no when asked)

- No two-way merge in one run — one direction per invocation keeps conflicts human-visible.
- No deletion of ADO work items, ever. Closing happens via state mapping.
- No syncing of `deferred` — and `proposals` sync only in the ONE direction `pull
  sprint` creates them; they become pushable work items after materialization.
- No board-column (`WEF_`) writes, ever — cards move via `System.State` only, and a
  column not backed by a state is reported as unreachable, not faked (tracker-sync.md).
- No creation from the orchestrator echo — the echo UPDATES linked items only;
  creation lives here, behind this command's confirm gate.
- No silent assignment from `identityMap`, and no `task.assignee` field — the map lives
  in `meta.ado`, push asks before every `--assigned-to`, and pull labels new imports
  without ever rewriting existing rows.
