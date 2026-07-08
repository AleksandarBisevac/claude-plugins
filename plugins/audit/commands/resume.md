---
description: 'Audit pipeline: resume an interrupted run — find the in-progress phase and continue from the first uncommitted task.'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:resume — continue an interrupted run

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first. Run the full preflight
(steps 1–5, including the lock).

Run the **Resume after interruption** procedure (orchestrator): find the in-progress phase and its
branch, compare committed work, and continue from the first task whose `commit` is null/missing.
Use after a crash, a lost session, or any interrupted `/audit:phase` / `/audit:next` / `/audit:run`
(`/audit:status` flags when a phase is resumable). Then follow **Reporting** and release the lock.
