---
description: 'Audit pipeline: run a whole phase — execute every ready task (parallel where safe) until none remain, then Phase sign-off. --dry-run previews the plan without mutating.'
argument-hint: '<phaseId> [--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:phase — run a phase and sign it off

`$ARGUMENTS` = the phase id (plus optional `--dry-run`). Read
`${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

**If `--dry-run` is present:** follow the orchestrator's **Dry-run / preview** section instead —
read-only preflight, print the plan (branch, ready tasks, parallel groups, merge target), and STOP.

Otherwise run the full preflight (steps 1–5, including the lock) and emit **Progress output** as you go:

1. If the phase is `done` → refuse; point to `/audit:review <phaseId>` to re-run sign-off.
2. Execute every **ready** task in the phase in parallel where safe (disjoint `files` and satisfied
   `dependsOn`), sequentially otherwise. (**Execute the task** performs phase entry — branch,
   `baseRef`, phase status — on its first run.)
3. Re-evaluate readiness and repeat until no task in the phase is ready.
4. When **all** tasks in the phase are `done`, run **Phase sign-off** (orchestrator).

Then follow **Reporting** and release the lock.
