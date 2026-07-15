---
description: 'Audit pipeline: execute exactly one task by id, with status guards (done/blocked/in_progress) and blocker checks. --dry-run previews without mutating.'
argument-hint: '<taskId> [--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:run — execute one task

`$ARGUMENTS` = the task id to run (plus optional `--dry-run`). Read
`${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

**If `--dry-run` is present:** follow the orchestrator's **Dry-run / preview** section — preview
whether the task is ready + what would run, and STOP without mutating.

Otherwise run the full preflight (steps 1–5, including the lock) and emit **Progress output** as you go.

Execute exactly `<taskId>`, with status guards:
1. `status == "done"` → refuse: report its `commit`/`outcome`. Offer (AskUserQuestion) an explicit
   **re-open**: on confirmation, reset `status = "pending"`, `attempts = 0`, clear `commit`,
   `outcome`, `completedAt`, `verifiedBy` — and **if `task.bugId` is set, reopen the linked bug too**
   (its `bugs[]` entry back to `status: "in_progress"`, clear `fixedIn`) so a re-opened bugfix task
   never leaves its bug marked `fixed` at a stale SHA — then execute. Never silently re-run a done task.
2. `status == "blocked"` → refuse: report why (exhausted attempts / blockers). Offer a confirmed
   reset of `attempts` to 0 (back to `pending`), then execute.
3. `status == "in_progress"` → warn: likely an interrupted run — point to `/audit:resume`.
   Proceed only if the human explicitly confirms re-execution.
4. Unmet blockers → refuse and list them.
5. Otherwise run **Execute the task** (orchestrator).

Then follow **Reporting** and release the lock.
