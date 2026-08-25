---
description: Add a tracked task to the audit manifest (interactive), move one between phases, or cancel work that will not be done. `add` allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates; `move` renumbers a task into another phase, rewrites every reference, and records a chained task.move journal row; `cancel` closes a task — or, as the legacy spelling of `/audit:phase cancel`, a whole phase — as terminal-but-not-done, recording the reason, the moment and a journal row. `priority` is the legacy spelling of `/audit:phase priority` and still works.
argument-hint: 'add "<title>" [--phase <id>] | scope <taskId> --files a,b | move <taskId> --to <phaseId> | cancel <id> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest, move one between phases, or close one

**`$ARGUMENTS`**: subcommand `add` followed by a quoted title, optional `--phase <id>`;
or subcommand `move` followed by a task id and `--to <phaseId>`;
or subcommand `cancel` followed by an id and `--reason "<why>"`;
or subcommand `priority`, the legacy spelling covered at the end of this file.
Unknown/empty subcommand → print usage and stop.

**`priority` is deliberately absent from the `argument-hint` above** while remaining a
working subcommand. The hint is what a reader is offered when they type the command, and
offering the old spelling there is how the old spelling keeps being learned — the
opposite of what an alias is for.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).
`add` writes through `scripts/manifest/audit-task.py`, which takes and releases the **index lock**
itself; hold the lock by hand (conventions → Concurrency lock) only around writes YOU make
with Edit — which is now the `move` subcommand and nothing else. **Creating a phase is
`/audit:phase add` and is no longer done here by hand** (see step 1).

## Subcommand: `add "<title>" [--phase <id>]`

The add is a SCRIPT call, not a hand-templated edit. `scripts/manifest/audit-task.py` allocates
the id under the index lock, initializes every orchestrator field from the conventions'
new-task template exactly once, extends `fileIndex`, revalidates from disk (rolling the
write back on findings) and journals a `task.add` row. Your job is to gather the answers
and pass them as flags — NEVER hand-write the task JSON; hand-templating fifteen fields
per add is the class of error the script exists to delete.

1. **Target phase**:
   - `--phase <id>` given → pass it through. The script refuses a `done` phase
     (immutable history) and a phase id reserved by a parked proposal (pointing to
     `/audit:propose materialize`) — relay those refusals, then offer the
     alternatives below.
   - Otherwise call without `--phase`: the script defaults to the single
     `in_progress` phase, or exits 2 NAMING the choices. On that exit 2, ask
     (AskUserQuestion): one of the named phases, or **new phase**. A new phase is
     `/audit:phase add "<title>" --outcome "<what success looks like>"` — follow
     `${CLAUDE_PLUGIN_ROOT}/commands/phase.md` → *Subcommand: `add`*, which takes
     the index lock itself, then re-run this add with `--phase <newId>`. **Do not
     hand-write the phase.** This step used to say "create it with Edit under the
     index lock", and that instruction was wrong in the sharded layout in a way
     a reader could not see: a phase there is a shard file AND an index stub, and
     an Edit that produced one of them leaves a manifest the next command cannot
     read.
   - When a still-parked proposal (`proposals[]`, status `proposed`) already
     covers this work (title/scope overlap), say so and offer
     `/audit:propose materialize <PROP-id>` as the alternative before creating a
     parallel task by hand.
2. **Gather the answers** (ask only for what's missing; propose sensible defaults):
   - `--description` — problem, approach, key decisions.
   - `--files a,b` — repo-relative paths this task touches (Glob/Grep to verify they
     exist; the script notes misses but allows new-file paths).
   - `--tests-mode` (`tdd` for incorrect current behavior / `regression` for
     behavior-preserving / `gate-only` for mechanical — the script sets
     `expectRedFirst` true iff tdd), `--tests-add "<desc>"` (repeatable, one test
     description each), `--gate "<entry>"` (repeatable; default: the phase's
     `testGate`).
   - `--model` (default `sonnet` — the floor for all fix work; the script escalates
     `risk: high` to `opus` when no model is passed; do NOT use `haiku` for
     audit-fix work), `--risk` (`low`/`med`/`high`).
   - **Skills** — do not scan the filesystem for skills yourself; there is ONE
     mechanical source. Run (Bash):
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --json --discovery
     ```
     The payload's `discovery` block lists every skill this project can actually
     see (`{"skills": [{"name", "description", "source"}, …]}` — project
     `.claude/`, user `~/.claude/`, installed plugins). A `discovery.error` key
     means the scan failed and the lists are empty (fail-open, not wrong): say
     so and offer only the area defaults below. Then ask "which skills should
     the executor load for this task?" (AskUserQuestion), offering:
     - the phase's **area default skills** from the `meta.areas` registry (the
       manifest you already read: match the task's `--files` against the area
       `root` prefixes) — mark them as the default (they load first for every
       task in the area anyway; naming them on the task is a no-op kept for
       readability);
     - **discovery names as options** — `discovery.skills` entries whose
       names/descriptions match the task's files and subject — offer names the
       payload carries and nothing else, never invented ones;
     - **"null — none applies"** — the explicit opt-out, written as JSON `null`:
       it STOPS the area fallback so nothing loads. Distinct from leaving skills
       unconsidered (`[]`, the default), where the area default stays in force.
     Then `--skills a,b`, `--skills null`, or omit the flag for unconsidered.
   - `--blocked-by` / `--depends-on` — comma-separated ids (omit when none).
3. **Run it** (Bash):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" add "<title>" \
           --phase <id> --description "<why & how>" --files a,b \
           --tests-mode regression --risk low --skills a,b
   ```
   **Print the script's output verbatim — validator findings and warnings
   included. Do NOT re-format, summarize, or "improve" it.** The report already
   names the id, what was written, the journal outcome, and whether the task is
   ready now (with the `/audit:run <taskId>` handoff).
4. **Exit codes**: `0` done. `2` usage — the message names the choices (ambiguous
   phase, done phase, reserved id, missing manifest): ask the human, adjust, re-run.
   `1` the add would leave the manifest invalid — it was rolled back byte-for-byte
   and the findings are printed; fix the inputs (e.g. a `--blocked-by` id that does
   not resolve) and re-run. `3` the index lock is held by a live run — stop; do not
   take it over. `4` the lock looks abandoned — confirm with the human
   (AskUserQuestion), then re-run the same add with `--takeover`.

## Subcommand: `cancel <id> --reason "<why>"`

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.

Close a task — or a whole phase — that will **not** be done. The feature was dropped, the
approach was abandoned, the phase ends with whatever landed. This is not failure and it is
not `done`: `cancelled` is the second TERMINAL state (the phase/task twin of a bug's
`wontfix`), and the report files it under **Archived** beside the finished work.

Like `add`, this is a SCRIPT call — `scripts/manifest/audit-task.py cancel <id> --reason "<why>"`,
which takes the index lock itself. Never hand-edit the status: the script is what records
all three things a hand-edit loses — the reason, the moment, and the journal row.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" cancel P3.2 \
  --reason "search rewrite dropped; the endpoint stays as-is" [--json]
```

What it writes:

- **task** → `status: "cancelled"`, `completedAt` stamped (it stopped being work then),
  and the reason into `outcome.descriptive` as `Cancelled: <why>` — the field the report's
  detail row already reads, so no new field is invented for it.
- **phase** → the same status, the reason appended to `summary`, its `claim` released
  (a claim on a finished phase is stale, and the validator says so), **and every task in it
  that is not already finished is cancelled too** — a pending task under a dropped phase is
  a task `/audit:next` would otherwise still offer. **`/audit:phase cancel <phaseId>` is
  where a phase is spelled now**, and this section is the procedure it follows; taking a
  phase id here still does exactly this, as the legacy spelling.
- **journal** → one `task.cancel` / `phase.cancel` row carrying the reason twice over —
  in the row's `summary` sentence and in `details.reason` — so the why outlives the
  session and a reader parsing rows never has to parse prose to recover it. `details`
  is an allow-list, so the second of those is a decision recorded in
  `_journal_io.DETAILS_KEYS` beside the key rather than something a writer chose.
- **ADO** (when linked) → the next echo/sync moves the card to the mapped state,
  `Removed` by default.

**Refusals, all before any write:** an id that resolves to nothing; a missing or blank
`--reason` (a status flipped with no why is exactly the hand-edit this replaces); and a
target that is already `done` or `cancelled` — terminal work is not re-decided here. As
with `add`, the manifest is validated from disk afterwards and **every written file rolls
back** on findings.

Readiness treats a cancelled blocker as settled, so a plan never deadlocks on work nobody
will do — a task that was waiting on the cancelled one becomes ready, and is worth a look
before it runs.

## Subcommand: `scope <taskId> --files a,b`

Give a **pending** task the files it touches, and optionally its tests and its
description: `--tests-mode tdd|regression|gate-only`, `--tests-add TEXT`
(repeatable), `--gate CMD` (repeatable), `--description TEXT`. Runs `scripts/manifest/audit-task.py scope` — the same
lock, the same revalidate-or-roll-back, the same journal row shape as `add`.

**Why the verb exists.** `/audit:sync pull sprint` imports tasks with `files: []` and
tells the reader to scope them before running. Nothing could: `add` creates, `cancel`
closes, `move` relocates, and the panel's composition card reaches `skills` and `model`
but not `files`. The only way to obey that instruction was the hand edit this file
forbids for adds — for the reason that applies here too.

**And the cost was not tidiness.** `files` is what `fileIndex` is built from, and
`fileIndex` is what the plan gate matches an edit against. An unscoped phase ran with
its central guard **inert** — not failing, because it had nothing to match.

**PENDING only, and the refusal says why**: a task that has started has a scope its
attempts were already judged against, and rewriting that changes retroactively what the
gate allowed while the work was done. `cancel`'s rule, for `cancel`'s reason. **Status is
not the whole test** — a task that ran, failed and was put back to `pending` still carries
`attempts` and an `outcome` describing work judged under the old scope, so a non-zero
`attempts` is refused too, pointing at `cancel` plus a fresh `add`.

**The fileIndex is re-derived, not appended to.** A scope call takes files away as well
as adding them, and an index that only grew would keep matching edits to a scope the task
no longer claims.

Refuses, each naming the reason: a phase id (it takes a task), an id that is not in the
manifest, a task that is not pending, and a call that would change nothing — a lock taken
for no reason is worth saying out loud.

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
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-journal.py" append --action task.move \
           --target <manifest rel> \
           --summary "<oldId> -> <newId> (<oldPhase> -> <newPhase>)" \
           --details '{"fromId":"<oldId>","toId":"<newId>","fromPhase":"<oldPhase>","toPhase":"<newPhase>"}'
   ```
5. **Revalidate**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` —
   fix and re-run until clean (the id-prefix warning for the moved task must be gone).
6. **Release the lock**, then **report**: old id, new id, target phase, whether the task is
   **ready now** (readiness rule), and this ledger note verbatim in spirit:
   *historical ledger rows keep the old taskId — history is never rewritten; new spend
   attributes to the new id; `movedFrom` plus the journal's `task.move` row are what let a
   reader join the two.*

## Subcommand: `priority <phaseId> <tier|--clear>` — the legacy spelling

**This still works.** It is what `/audit:phase priority <phaseId> <tier|--clear>` was called
before a verb that mutates a phase moved under the command named for the noun it mutates.
Kept so existing transcripts, runbooks and older docs resolve; new work says
`/audit:phase priority`.

**Do that, not something of your own.** Read
`${CLAUDE_PLUGIN_ROOT}/commands/phase.md` → *Subcommand: `priority`* and follow it, passing
the phase id and the tier (or `--clear`) through from `$ARGUMENTS` unchanged. There is no
second procedure here on purpose, and no second invocation either: two spellings reach one
writer, and two copies of a rule is one copy and one lie.

**Say the new name once, in the report — then get on with it.** Something like *"`/audit:task
priority` is the old name for `/audit:phase priority`; both do this."* One line, not a
lecture, and never a refusal to run.

**Why it was renamed.** `phase.priority` is the field —
`${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json` is where that is settled — and there
is no `task.priority` at all. So a command called `task` took a phase id and changed a
phase, and a reader of the command list reasonably concluded the opposite of the truth:
that tasks have priorities and phases do not.

**No removal is scheduled.** When one is, the changelog announces it before it happens —
`/audit:migrate` is the precedent. `COMPATIBILITY.md` counts a new command as a minor
release and makes no promise about taking a spelling away, so the announcement is the whole
contract here.
