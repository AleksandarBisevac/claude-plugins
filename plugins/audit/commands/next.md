---
description: 'Audit pipeline: execute the next ready task (phase order, then task-id order), then report what is ready next. --dry-run previews without mutating.'
argument-hint: '[--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:next — execute the next ready task

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

**If `$ARGUMENTS` contains `--dry-run`:** follow the orchestrator's **Dry-run / preview** section —
show the next ready task and what would run, and STOP without mutating.

Otherwise run the full preflight (steps 1–5, including acquiring the lock) and emit **Progress output**.

0. **Print the entry view first, verbatim:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath>` — it names
   every ready task, in order, with what the rest are waiting on. Do not re-tabulate it and
   do not re-derive the readiness rule by hand; the first entry under READY NOW is the task
   this command runs.
1. Find the first **ready** task (phase order, then task-id order) per the Readiness rule.
2. If none is ready: the entry view's `waiting on` column already says why, per task —
   relay it rather than restating it. Release the lock and stop.
3. Otherwise run **Execute the task** (orchestrator), then follow **Reporting** — outcome +
   what is ready next. Release the lock.
