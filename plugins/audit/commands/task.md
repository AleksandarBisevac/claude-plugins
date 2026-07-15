---
description: Add a tracked task to the audit manifest (interactive). Allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates — the task is then executable via /audit.
argument-hint: 'add "<title>" [--phase <id>]'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest

**`$ARGUMENTS`**: subcommand `add` followed by a quoted title, optional `--phase <id>`.
Unknown/empty subcommand → print usage and stop.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).

## Subcommand: `add "<title>" [--phase <id>]`

1. **Target phase**:
   - `--phase <id>` given → use it. If that phase's `status == "done"`, REFUSE
     (done phases are immutable history) and offer the alternatives below.
   - Otherwise ask (AskUserQuestion): one of the existing non-`done` phases, or
     **new phase**. A new phase gets the conventions doc's new-phase template
     (id continues the `P<n>` sequence; ask for its title; `testGate` from
     `meta.buildCommands` keys).
2. **Gather the task** (ask only for what's missing; propose sensible defaults):
   - `description` — problem, approach, key decisions.
   - `files` — repo-relative paths this task touches (Glob/Grep to verify they exist;
     warn on misses but allow new-file paths).
   - `tests` — `mode` (`tdd` for incorrect current behavior / `regression` for
     behavior-preserving / `gate-only` for mechanical), `add` descriptions,
     `expectRedFirst` (true iff tdd), `gate` entries (default: the phase's `testGate`).
   - `model` (default `sonnet` — the floor for all fix work; `opus` for `risk: "high"`; do NOT
     use `haiku` for audit-fix work), `risk`
     (`low`/`med`/`high`), `skills`, `blockedBy`/`dependsOn` (default `[]`).
3. **Allocate the id**: `<phaseId>.<max existing numeric suffix + 1>`.
4. **Write** (Edit): append the task with ALL initialized fields from the new-task
   template; extend the top-level `fileIndex` with every entry in `files`.
5. **Revalidate**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>` —
   fix and re-run until clean.
6. **Report**: the created task (id, phase, tests.mode, model, risk), whether it is
   **ready now** (evaluate the orchestrator's readiness rule), and the handoff:
   `/audit:run <taskId>` (or what blocks it).
