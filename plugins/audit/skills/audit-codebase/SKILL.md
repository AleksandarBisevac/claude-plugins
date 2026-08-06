---
name: audit-codebase
description: Use when someone wants a whole codebase audited and fixed as tracked, resumable work — "audit this codebase", "find and fix everything wrong in this repo", "go through the app and clean it up", "set up an audit plan", "what audit phase is next" — rather than a one-shot look at the current diff. Routes to the /audit:* commands, which own the actual procedure.
---

# Auditing a codebase with the `audit` plugin

This skill exists to be **found**, not to explain anything. Everything it knows is one of
three files; read the one that matches and follow it exactly.

## Do not use this for

A one-shot review of the working diff or a pull request. `/review`, `/security-review` and
the native code-review tooling are the right answer there, and reaching for a manifest to
look at ten changed lines is pure overhead. This is for work that spans sessions and has to
survive being interrupted.

## Route

Check for a manifest first — `docs/audit/audit-plan.json` by default, or `manifestPath` in
`.claude/audit.config.json`.

| Situation | Command |
|---|---|
| No manifest yet | `/audit:init` — generates one from the codebase |
| A manifest exists, and the question is "where are we" | `/audit:status` |
| A manifest exists, and the question is "what now" | `/audit:next` |
| Run the next phase end to end | `/audit:phase <id>` |
| Something is not working and it is not obvious why | `/audit:doctor` |

Read `${CLAUDE_PLUGIN_ROOT}/commands/<name>.md` and do what it says. Those files are the
source of truth; nothing here restates their procedure, because two copies of a procedure
is one copy and one lie.

## The one thing worth knowing before starting

`/audit:init` spawns several agents and is the most expensive command here. If the person
has not committed to the pipeline yet, `/audit:usage --backfill` costs nothing, reads
transcripts already on disk, and shows them what their existing work has cost — see the
`audit-spend` skill. That is a better first move than a manifest they did not ask for.
