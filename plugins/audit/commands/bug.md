---
description: Track bugs in the audit manifest — report (add), list, materialize a TDD fix task (fix), or close. Execution of the fix stays in /audit; the repro test must fail red-first, proving the bug.
argument-hint: add "<title>" | list [all|<status>] | fix <bugId> [--phase <id>] | close <bugId> [wontfix]
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:bug — bug tracking on the audit manifest

Bugs live in the manifest's top-level `bugs[]`, OUTSIDE phases — a reported bug is not
yet a plan. `fix` materializes a bug into a **tdd task** (red-first repro test) that
`/audit run` executes; the orchestrator flips the bug to `fixed` when that task commits.
Bug lifecycle: `open → triaged → in_progress (materialized) → fixed | wontfix`.

**`$ARGUMENTS`**: first token is the subcommand. Unknown/empty → print usage and stop.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).
After EVERY mutation: revalidate with
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>`.

## Subcommand: `add "<title>"`

1. If the manifest has no top-level `bugs` array, create it (`"bugs": []`) via Edit.
2. Gather (ask only for what's missing): `severity` (low/med/high), `description`,
   `repro` (steps, string or array), `expected`, `actual`, suspected `files`
   (verify with Glob/Grep; empty is allowed).
3. Allocate `BUG-<max existing bug number + 1>` and append:
   `{id, title, status: "open", severity, reportedAt: <ISO now>, reportedBy: null,
   description, repro, expected, actual, files, taskId: null, fixedIn: null, notes: null}`.
4. Revalidate. Report the bug id and the handoff: `/audit:bug fix <id>` when ready.

## Subcommand: `list [all|<status>]`

Read-only. Print a table `id | severity | status | title | taskId | reportedAt`.
Default filter: everything NOT `fixed`/`wontfix`. `list all` shows everything;
`list <status>` filters to that status. Empty result → say so and point to `add`.

## Subcommand: `fix <bugId> [--phase <id>]`

1. **Refuse when**: the bug doesn't exist; its status is `fixed`/`wontfix`; or its
   `taskId` is already set and that task is not `done` → point to `/audit run <taskId>`
   instead (one bug = one live task; no second execution engine).
2. **Target phase**: `--phase <id>` if given (must not be `done`); else the latest
   `BF<n>` phase whose status != `done`; else CREATE `BF<max+1>`
   (title `Bugfix batch <n>`, the conventions doc's new-phase template,
   `testGate` from `meta.buildCommands` — at minimum the `test` key).
3. **Materialize the task** (new-task template + these specifics):
   - id `<phaseId>.<next>`; title `Fix <bugId>: <bug title>`.
   - `description` embedding the bug's repro / expected / actual verbatim.
   - `files` = bug's `files`; `bugId: "<bugId>"`.
   - `tests: {mode: "tdd", add: ["repro test that FAILS on current code: <expected> vs <actual>"], expectRedFirst: true, gate: [<phase testGate>]}`.
   - `risk`: bug severity high → `high`, med → `med`, else `low`.
   - `model`: `sonnet` (or stronger for `risk: "high"`).
4. **Update the bug**: `status: "in_progress"`, `taskId: <new task id>`.
5. Extend `fileIndex` with the task's files. Revalidate.
6. **Report + handoff**: `Materialized <taskId> for <bugId> — run /audit run <taskId>`.
   Do NOT execute the fix here — execution, commits, and the red-first check are
   `/audit`'s job (it also flips the bug to `fixed` + `fixedIn` on the task commit).

## Subcommand: `close <bugId> [wontfix]`

1. Refuse if the bug's materialized task is `in_progress` (finish or unblock it via
   `/audit` first).
2. Set `status` to `wontfix` (default) — or `fixed` only if the human explicitly says
   it was fixed outside the pipeline — and record a one-line `notes` justification.
3. Revalidate and report.
