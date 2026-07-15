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

## Subcommand: `push [bugs|tasks|all]` (default `bugs`)

1. Build the plan: for each in-scope item —
   - `item.ado` **null/absent** → CREATE (`az boards work-item create --type <type>
     --title ... --fields ... --output json`);
   - `item.ado.id` set → fetch current (`az boards work-item show --id <id> --output json`),
     **diff the mapped fields**, and only when something differs → UPDATE
     (`az boards work-item update`). No-op items are skipped.
2. Print the plan (`N creates, M updates, K in sync`) and **confirm via AskUserQuestion
   before the first write** — ADO writes are outward-facing and visible to the whole team.
3. Execute item by item. After each successful create, IMMEDIATELY Edit the manifest:
   `item.ado = {id, url, lastSyncedAt: <ISO now>}` (then revalidate). After each update,
   bump `lastSyncedAt`. On any failure: report it, keep what succeeded, stop — a re-run
   continues where it left off.
4. When pushing a `fixed` bug with `fixedIn`, add a work-item comment
   (`az boards work-item update --id <id> --discussion "Fixed in <sha>"`).
5. Report: table of `manifest id | ado id | action taken`.

## Subcommand: `pull`

1. Query candidate bugs:
   `az boards query --wiql "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = '<project>' AND [System.WorkItemType] = '<types.bug>' AND [System.State] <> 'Closed'"`
   (add an AreaPath clause when `meta.ado.areaPath` is set).
2. Drop work items already linked (their id appears in some manifest `ado.id`).
3. For each remaining item, show `id | title | state | assignee` and ask
   (AskUserQuestion, multi-select) which to import.
4. Import each selected item as a manifest bug following `/audit:bug add`'s shape and the
   conventions doc: next `BUG-<n>`, `status: "open"`, title/description from the work
   item, `repro` from its repro steps, `reportedBy: "ado:<assignee-or-creator>"`,
   `ado: {id, url, lastSyncedAt}`. Revalidate. Never modify ADO during `pull`.
5. Report + handoff: `/audit:bug fix BUG-<n>` to materialize a fix task.

## Subcommand: `status`

Read-only, no ADO writes, no manifest writes.
1. Count linked vs unlinked bugs/tasks.
2. For linked items, batch-fetch the ADO side (`az boards work-item show`) and print:
   `manifest id | title | manifest status | ado id | ado state | drift?` — drift = the
   mapped state differs from the ADO state (fix by running `push`, or by updating the
   manifest if ADO is the truth).
3. Suggest the next action (`push` / `pull`) based on what drifted.

## Non-goals (say no when asked)

- No two-way merge in one run — one direction per invocation keeps conflicts human-visible.
- No deletion of ADO work items, ever. Closing happens via state mapping.
- No syncing of `deferred`/`proposals` — they are not work items yet by definition.
