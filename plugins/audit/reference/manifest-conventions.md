# Manifest conventions

Shared rules for every command that reads or mutates the audit manifest
(`/audit`, `/audit:init`, `/audit:task`, `/audit:bug`). Read this file FIRST.

## Locating the manifest

Read `.claude/audit.config.json` in the consuming repo → `manifestPath`
(default `docs/audit/audit-plan.json`). The manifest is the single source of
truth — never track phase/task/bug state anywhere else.

## Edit-and-revalidate rule

Every manifest mutation goes through `Edit`/`Write` and must keep the JSON valid.
After EVERY mutation, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>
```

Exit 0 = valid. On findings: fix the manifest and re-run before doing anything else.

## ID allocation

- **Task**: `<phaseId>.<n>` where `n` = highest existing numeric suffix in that phase + 1 (`P2.4` → next is `P2.5`).
- **Bug**: `BUG-<n>` where `n` = highest existing bug number + 1, repo-wide (`BUG-3` → next is `BUG-4`).
- **Bugfix phase**: `BF<n>` where `n` = highest existing `BF` number + 1 (`BF1`, `BF2`, …).

## Status enums

- Phase/task: `pending | in_progress | blocked | done`
- Bug: `open | triaged | in_progress | fixed | wontfix`
- `tests.mode`: `tdd | regression | gate-only` · `risk`: `low | med | high`

## New task template

Every newly created task MUST be initialized with ALL of:
`status: "pending"`, `attempts: 0`, `maxAttempts: 3`, `commit: null`,
`outcome: {technical: null, descriptive: null}`, `startedAt: null`,
`completedAt: null`, `verifiedBy: []`, plus explicit `blockedBy: []` /
`dependsOn: []` (empty when none) and a `tests` object with `mode`, `add`,
`expectRedFirst`, `gate`.

## New phase template

A newly created phase MUST be initialized with: `status: "pending"`,
`baseRef: null`, `branch: null`, `mergedAt: null`,
`review: {tool: null, model: "sonnet", status: "pending", findings: []}`,
`summary: null`, and a `testGate` derived from `meta.buildCommands` keys.

## fileIndex maintenance

Adding a task with `files` MUST add/extend the matching top-level `fileIndex`
entries (`"<file>": [..., "<taskId>"]`). Never remove other tasks' ids.

## Immutable history

Phases with `status: "done"` are history — never append tasks to them.
Route new work to an open phase or create a new one.
