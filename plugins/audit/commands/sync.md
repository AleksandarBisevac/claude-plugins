---
description: 'Sync the audit manifest with Azure DevOps work items — push manifest bugs/tasks to ADO, pull assigned ADO bugs into the manifest, or show link status. Explicit, idempotent, one direction per invocation; configured via meta.ado.'
argument-hint: 'push [bugs|tasks|all] | pull | status'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion, mcp__azure-devops__wit_*
---

# /audit:sync — Azure DevOps work-item sync

Mirrors the manifest's `bugs[]` (and optionally tasks) into Azure DevOps work items and
back. **No background magic**: every invocation does exactly one direction, shows its plan,
and is idempotent (re-running converges; nothing duplicates).

**`$ARGUMENTS`**: first token is the subcommand. Unknown/empty → print usage and stop.

## 0. Preflight

1. Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md`; resolve and read the
   manifest. Missing → stop, point to `/audit:init`.
2. **`meta.ado` must exist** — else stop and print the setup snippet:
   ```json
   "ado": { "organization": "<org>", "project": "<project>",
            "areaPath": null, "iterationPath": null,
            "types": { "bug": "Bug", "task": "Task" } }
   ```
3. **Transport**: if `mcp__azure-devops__wit_*` MCP tools are available in this session,
   you MAY use them (same field mapping below). Otherwise use the `az` CLI via Bash:
   `az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>`
   then `az boards ...`. If `az` is missing or the `azure-devops` extension isn't installed,
   STOP with install guidance (`az extension add --name azure-devops`; auth via `az login`,
   or the `AZURE_DEVOPS_EXT_PAT` environment variable in CI).
4. **Credentials are never yours to handle**: never write a PAT/token into the manifest,
   the config, or any file; never echo one (the secret guard blocks it anyway). Auth
   belongs to `az` / the MCP server.
5. After EVERY manifest mutation: revalidate with
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>`.
6. `push`/`pull` write the manifest — hold the **concurrency lock** (see conventions →
   Concurrency lock) around those writes; `status` is read-only and never locks.

## Field mapping (both transports)

| Manifest | ADO (defaults; types from `meta.ado.types`) |
|---|---|
| bug → work item type | `types.bug` (default `Bug`) |
| task → work item type | `types.task` (default `Task`) |
| `bug.title` / task: `[<taskId>] <title>` | Title |
| `bug.description` + `repro` + `expected`/`actual` | Repro Steps (Bug) / Description |
| `bug.severity` high/med/low | Severity `2 - High` / `3 - Medium` / `4 - Low` |
| bug status `open` → `New` · `triaged`/`in_progress` → `Active` · `fixed` → `Resolved` · `wontfix` → `Closed` | State |
| task status `pending` → `New` · `in_progress` → `Active` · `blocked` → `Active` + tag `blocked` · `done` → `Closed` | State |
| `meta.ado.areaPath` / `iterationPath` (when set) | Area / Iteration |
| always | tag `audit-plugin`; comment with `fixedIn` SHA when a bug closes |

The manifest side of a link is the item's `ado` field — `{id, url, lastSyncedAt}` —
**written only by this command**, immediately after each successful create (so an
interrupted run resumes idempotently).

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

1. Build the plan: for each in-scope item —
   - `item.ado` **null/absent** → CREATE (`az boards work-item create --type <type>
     --title ... --fields ... --output json`);
   - `item.ado.id` set → fetch current (`az boards work-item show --id <id> --output json`),
     **diff the mapped fields**, and only when something differs → UPDATE
     (`az boards work-item update`). No-op items are skipped.
2. Print the plan (`N creates, M updates, K in sync`) and **confirm via AskUserQuestion
   before the first write** — ADO writes are outward-facing and visible to the whole team.
3. **Assignment proposal** (only when `meta.ado.identityMap` has entries): for each
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
4. Execute item by item. After each successful create, IMMEDIATELY Edit the manifest:
   `item.ado = {id, url, lastSyncedAt: <ISO now>}` (then revalidate). After each update,
   bump `lastSyncedAt`. On any failure: report it, keep what succeeded, stop — a re-run
   continues where it left off.
5. When pushing a `fixed` bug with `fixedIn`, add a work-item comment
   (`az boards work-item update --id <id> --discussion "Fixed in <sha>"`).
6. Report: table of `manifest id | ado id | action taken` (assigned-to noted where
   applied).

## Subcommand: `pull`

1. Query candidate bugs:
   `az boards query --wiql "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] = '<types.bug>' AND [System.State] <> 'Closed'"`
   (add an AreaPath clause when `meta.ado.areaPath` is set).
2. Drop work items already linked (their id appears in some manifest `ado.id`).
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
   at import time, not a live view. Revalidate. Never modify ADO during `pull`.
5. Report + handoff: `/audit:bug fix BUG-<n>` to materialize a fix task.

## Subcommand: `status`

Read-only, no ADO writes, no manifest writes.
1. Count linked vs unlinked bugs/tasks.
2. For linked items, batch-fetch the ADO side (`az boards work-item show`) and print:
   `manifest id | title | manifest status | ado id | ado state | drift?` — drift = the
   mapped state differs from the ADO state (fix by running `push`, or by updating the
   manifest if ADO is the truth).
3. **Identity mapping** (only when `meta.ado.identityMap` has entries): per item, append
   one compact `owner` column to the table above, resolving the item's phase-area owner
   exactly as push step 3 does — `<ledger id> → <mapped ADO identity>` when mapped,
   `<ledger id> (unmapped)` when an owner exists without an entry, `—` when no owner
   resolves. Close with one summary line: `identityMap: N owner(s) mapped, M unmapped`
   (distinct owners across the areas in play). Display only — `status` stays read-only
   and proposes nothing here; an unmapped owner is push's business.
4. Suggest the next action (`push` / `pull`) based on what drifted.

## Non-goals (say no when asked)

- No two-way merge in one run — one direction per invocation keeps conflicts human-visible.
- No deletion of ADO work items, ever. Closing happens via state mapping.
- No syncing of `deferred`/`proposals` — they are not work items yet by definition.
- No silent assignment from `identityMap`, and no `task.assignee` field — the map lives
  in `meta.ado`, push asks before every `--assigned-to`, and pull labels new imports
  without ever rewriting existing rows.
