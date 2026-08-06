---
description: 'Audit pipeline: print manifest status — phases, tasks, bugs, the ready-now list and what each pending task is waiting on. Read-only, no locks, no mutations.'
argument-hint: '[--json]'
allowed-tools: Bash
---

# /audit:status — pipeline status report

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-status.py" <manifestPath> $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**

It already renders the whole report: an overall line with a progress bar, the usage
line when metering is on, one aligned table across every phase (markers `[x]` done ·
`[~]` in_progress · `[!]` blocked · `[ ]` pending), what each pending task is waiting
on, the ready-now list with a copy-pasteable `/audit:run <id>`, open bugs, and a
RESUMABLE line when a phase was interrupted.

This used to be prose telling you how to lay the rollup out. That cost tokens on every
call and produced a different layout each time — the same self-defeating shape
`/audit:usage` already refuses. You do **not** need to read the manifest either: the
renderer reads it in-process, so the per-task detail that once required a second read
is in the output already.

Pass `$ARGUMENTS` through unchanged. `--json` emits the machine-readable rollup
instead, for CI or another tool.

Preflight is not needed here — this command takes no lock and mutates nothing. Read
`${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` only if the human then asks you to
act on what the output says.

## If the output reports a problem

- **INVALID MANIFEST** — relay it and stop. `/audit:doctor` names the findings.
- **RESUMABLE** — offer `/audit:resume`.
- **nothing ready** — the plan is either complete or fully blocked. The `waiting on`
  column says which, per task, so do not guess.

Do not modify anything. Related: `/audit:doctor`, `/audit:next`, `/audit:run`,
`/audit:phase`, `/audit:report`, `/audit:usage`, `/audit:init`, `/audit:task`,
`/audit:bug`, `/audit:sync`.
