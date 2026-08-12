---
description: Add a tracked task to the audit manifest (interactive), or move one between phases. `add` allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates; `move` renumbers a task into another phase, rewrites every reference, and records a chained task.move journal row.
argument-hint: 'add "<title>" [--phase <id>] | move <taskId> --to <phaseId>'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest, or move one between phases

**`$ARGUMENTS`**: subcommand `add` followed by a quoted title, optional `--phase <id>`;
or subcommand `move` followed by a task id and `--to <phaseId>`.
Unknown/empty subcommand → print usage and stop.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).
This command mutates the manifest — hold the **concurrency lock** (see conventions →
Concurrency lock) around your writes and release it before reporting.

## Subcommand: `add "<title>" [--phase <id>]`

1. **Target phase**:
   - `--phase <id>` given → use it. If that phase's `status == "done"`, REFUSE
     (done phases are immutable history) and offer the alternatives below.
   - Otherwise ask (AskUserQuestion): one of the existing non-`done` phases, or
     **new phase**. A new phase gets the conventions doc's new-phase template
     (id continues the `P<n>` sequence, counting live phases AND every reserved
     `proposals[].payload` phase id — see conventions → ID allocation; ask for
     its title; `testGate` from `meta.buildCommands` keys).
   - When a still-parked proposal (`proposals[]`, status `proposed`) already
     covers this work (title/scope overlap), say so and offer
     `/audit:propose materialize <PROP-id>` as the alternative before creating a
     parallel task by hand.
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

## Subcommand: `move <taskId> --to <phaseId>`

Relocate a pending/blocked task into another open phase. This is the ONLY sanctioned
way to move a task: a hand-drag keeps the old id, which the validator flags
(`id does not follow its phase's prefix`) and which breaks the ledger join. This is a
**structural** mutation — take the **index lock** (conventions → Concurrency lock)
around every write below and release it before reporting.

**Refusals — all BEFORE any write** (check in this order; on refusal print why and stop):

1. `<taskId>` does not resolve to a task, or `<phaseId>` to a phase → refuse, list what exists.
2. Target phase == the task's current phase → refuse (no-op; nothing to move).
3. Task `status == "done"` → refuse: done tasks are history. Offer the `/audit:run <taskId>`
   **re-open** path first (it resets status/commit/outcome under its own guards); move only
   after that has run.
4. Task `status == "in_progress"` → refuse: likely a live or interrupted run — point to
   `/audit:resume`, or to the human-confirmed re-execution path in `run.md`, before any move.
5. Target phase `status == "done"` → refuse (done phases are immutable history — same rule
   as `add`).

A `blocked` task MAY move: it moves **with its blockers** — its own `blockedBy`/`dependsOn`
lists travel unchanged (only references *to its old id* elsewhere are rewritten, step 3).

**Steps** (index lock held throughout; in the sharded layout the task body moves between
the two phase SHARDS while `fileIndex`/`bugs[]` edits go to the index):

1. **Allocate the new id** `<targetPhaseId>.<n>` — `n` = highest existing numeric suffix in
   the target phase + 1, computed over the **whole assembled manifest AND every reserved
   `proposals[].payload` id** (conventions → ID allocation / Reserved ids).
2. **Move the task object** into the target phase's `tasks[]` with its new id, adding
   `movedFrom: {"id": "<oldId>", "phase": "<oldPhaseId>", "at": "<ISO now>"}`. Remove it
   from the source phase. All other fields travel byte-for-byte.
3. **Rewrite every reference** to the old id, across the index AND all shards:
   - every `blockedBy` / `dependsOn` entry equal to `<oldId>` → `<newId>` (phases and tasks);
   - every `fileIndex` value array: `<oldId>` → `<newId>`;
   - every `bugs[].taskId` equal to `<oldId>` → `<newId>` (the task's own `bugId` travels with it).
4. **Record the move** — the explicit mapping row, appended by YOU via the CLI (this is the
   one journal action a command writes; the completion events stay hook-only):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-journal.py" append --action task.move \
           --target <manifest rel> \
           --summary "<oldId> -> <newId> (<oldPhase> -> <newPhase>)" \
           --details '{"fromId":"<oldId>","toId":"<newId>","fromPhase":"<oldPhase>","toPhase":"<newPhase>"}'
   ```
5. **Revalidate**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>` —
   fix and re-run until clean (the id-prefix warning for the moved task must be gone).
6. **Release the lock**, then **report**: old id, new id, target phase, whether the task is
   **ready now** (readiness rule), and this ledger note verbatim in spirit:
   *historical ledger rows keep the old taskId — history is never rewritten; new spend
   attributes to the new id; `movedFrom` plus the journal's `task.move` row are what let a
   reader join the two.*
