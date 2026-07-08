---
description: 'Audit pipeline: print manifest status — phases, tasks, bugs, and the ready-now list. Read-only, no locks, no mutations.'
allowed-tools: Read, Bash, Glob, Grep
---

# /audit:status — pipeline status report

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run preflight steps 1–2 only
(read-only: no git-root/submodule check, no lock). Then read the manifest and print:

1. Per-phase line: `id — title — status (done/total tasks) — branch (if set) — desiredOutcome (if set)`.
2. Per-task rows grouped by phase: `id | title | status | model | unmet blockers | commit (short SHA or —)`.
3. A **"Ready now"** list: every ready task (per the orchestrator's Readiness rule), with its model.
4. If any phase is `in_progress` with a non-null `branch` (or contains an `in_progress` task):
   flag it as **resumable** — "interrupted? run `/audit:resume`".
5. If `bugs[]` exists and is non-empty: counts by bug status, plus every non-closed bug whose
   materialized task (`taskId`) is ready now.

Do not modify anything. Related: `/audit:next`, `/audit:run`, `/audit:phase`, `/audit:report`,
`/audit:init`, `/audit:task`, `/audit:bug`, `/audit:sync`.
