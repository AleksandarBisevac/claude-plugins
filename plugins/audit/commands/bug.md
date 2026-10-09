---
description: 'Track bugs in the audit manifest — report (add), list, materialize a TDD fix task (fix), or close. Execution of the fix stays in /audit; the repro test must fail red-first, proving the bug.'
argument-hint: 'add "<title>" [--severity SEVERITY] [--description TEXT] [--files a,b] [--repro TEXT] [--expected TEXT] [--actual TEXT] | list [all|<status>] | fix <bugId> [--phase <id>] | close <bugId> [wontfix|not_a_bug|fixed]'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:bug — bug tracking on the audit manifest

Bugs live in the manifest's top-level `bugs[]`, OUTSIDE phases — a reported bug is not
yet a plan. `fix` materializes a bug into a **tdd task** (red-first repro test) — or a **regression task** when every file the bug names is a test file — that
`/audit:run` executes; the orchestrator flips the bug to `fixed` when that task commits.
Bug lifecycle: `open → triaged → in_progress (materialized) → fixed | wontfix | not_a_bug`.

**Three words close a bug and they are three different answers.** `fixed` says the
behaviour changed; `wontfix` says the report is real and the fix will not be made;
`not_a_bug` says somebody investigated and the reported behaviour turned out to be
correct. The last one exists because a verified negative had no word at all, so an
investigation that found nothing left no row and the next reader ran it again.

**`$ARGUMENTS`**: first token is the subcommand. Unknown/empty → print usage and stop.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).
After EVERY hand mutation: revalidate with
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>`.
`add` writes through `audit-task.py bug-add`, which takes the **concurrency lock**, revalidates
and rolls back itself — do not hold the lock around that call. `fix`/`close` hold the lock
(see conventions → Concurrency lock) around their writes; `list` is read-only and never locks.

## Subcommand: `add "<title>"`

**Every answer is a flag, and the dialogue only covers what the caller did not pass.** The
bug is written by a verb, never by an Edit of `bugs[]`.

1. Gather (ask only for what's missing): `--severity` (low/med/high) and `--description`
   are required; `--repro`, `--expected`, `--actual` and the suspected `--files` (verify
   with Glob/Grep; empty is allowed) may be absent.
2. **The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. A value holding backticks or a run of spaces goes on stdin as `-`, which no shell rewrites — but only ONE value per call — the title or a single prose flag — may take `-`, because they would share the one stdin stream and the verb refuses a call where two claim it. Pass every other value single-quoted, which a POSIX shell leaves exactly as typed, so backticks and `$` survive. The verb still reads an argv value for the marks a shell leaves when it eats a span — whitespace before punctuation, a run of spaces — and refuses one that carries them, and a value holding a single quote cannot be single-quoted; either of those is the value to send on stdin.
3. Write it:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" bug-add "<title>" \
     --severity <low|med|high> --description "<text>" [--files a,b] \
     [--repro "<steps>"] [--expected "<text>"] [--actual "<text>"] [<manifestPath>]
   ```
   The verb creates `bugs` when the plan has none, takes the id from the same allocator
   `next-id bug` prints (`BUG-<max+1>`, and off the development branch
   `BUG-<max+1>-<suffix>`, so two branches filing a bug each from one base never mint the
   same id), and writes exactly
   `{id, title, status: "open", severity, reportedAt: <ISO now>, reportedBy: null,
   description, repro, expected, actual, files, taskId: null, fixedIn: null, notes: null}` —
   every key present, an absent answer as `null` (`files` as `[]`). It holds the lock,
   revalidates and rolls back on a finding, and records a `bug.add` journal row. A missing
   title, severity or description is refused, exit 2, with nothing written.
4. Report the bug id the verb printed and the handoff: `/audit:bug fix <id>` when ready.

## Subcommand: `list [all|<status>]`

Read-only. Print a table `id | severity | status | title | taskId | reportedAt`.
Default filter: everything NOT `fixed`/`wontfix`/`not_a_bug`. `list all` shows everything;
`list <status>` filters to that status. Empty result → say so and point to `add`.

## Subcommand: `fix <bugId> [--phase <id>]`

1. **Refuse when**: the bug doesn't exist; its status is `fixed`/`wontfix`/`not_a_bug`; or its
   `taskId` is already set and that task is not `done` → point to `/audit:run <taskId>`
   instead (one bug = one live task; no second execution engine).
2. **Target phase**: `--phase <id>` if given (must not be `done`); else, on a phase
   branch, **the phase whose branch is checked out** - a bug found while working a phase is
   fixed in that phase (`/audit:task add` picks the same one, see `commands/task.md`); else
   the latest `BF<n>` phase whose status != `done`; else CREATE `BF<max+1>` with
   `/audit:phase add "Bugfix batch <n>" --id BF<max+1> --outcome "..."` (the script writes
   the new-phase template and `testGate` from `meta.buildCommands`). **Never create a `BF`
   phase on a phase branch**: phases are minted on the development branch (a phase id is a
   branch, lock and shard name, and two branches would both mint `BF<max+1>`). On a phase
   branch with no phase of its own, ask the user: fix it in a running phase, or park the
   bugfix phase (`/audit:phase add ... --park`) to materialize after the branch merges.
3. **Materialize the task** (new-task template + these specifics):
   - id from the allocator, never by hand: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" next-id task --phase <phaseId> <manifestPath>`
     (it counts reserved ids and carries the branch suffix); title `Fix <bugId>: <bug title>`.
   - `description` embedding the bug's repro / expected / actual verbatim.
   - `files` = bug's `files`; `bugId: "<bugId>"`. Write the task with
     `audit-task.py add "Fix <bugId>: <title>" --phase <phaseId> --bug <bugId> --files <bug files> ...`:
     `--bug` sets `bugId`, links the bug back (`taskId`, `status: in_progress`) and **chooses the
     discipline from the bug's files** — omit `--tests-mode` to take it.
   - **The discipline follows from the files.** When every file the bug names is a test path, the
     task is `regression` and carries a note saying why (the defect is in the test, so a red-first
     run at HEAD passes with the fixed test); otherwise it is `tdd`. Pass `--tests-mode` only to
     overrule that on a reason.
   - For a `tdd` task: `tests: {mode: "tdd", add: ["<testFile>: repro that FAILS on current code — <expected> vs <actual>"], expectRedFirst: true, gate: [<phase testGate>]}`.
     **`<testFile>` is a real repo-relative path you substitute, and it has to come
     first.** The leading path is what joins the task's `files` and the `fileIndex`,
     so an entry that opens with prose puts nothing there — the case file stays
     outside the scope commit-scope grades the fix against, and the validator warns
     (a finding from 3.0.0). Name the file the repro will live in, even when it does
     not exist yet.
   - `risk`: bug severity high → `high`, med → `med`, else `low`.
   - `model`: `sonnet` (or stronger for `risk: "high"`).
4. **Update the bug**: `status: "in_progress"`, `taskId: <new task id>` (`add --bug` already wrote both).
5. Extend `fileIndex` with the task's files. Revalidate.

   **A mute on this bug does not hold in this task's gate.** If `meta.muted` quarantines a suite
   under this bug, a gate run for the task (`run-test-gate.py … --task <taskId>`) does not
   honour that mute — the bug's `taskId` is the task under test, and a quarantined failure would
   let the gate go green whether the fix worked or not (`run-test-gate.withheld_mutes`). Other
   runs keep honouring it while the bug is open. **Once the bug is closed**, by its own status or
   by its fix task reaching `done`, no run honours the mute any more and `validate-manifest.py`
   warns (`rules.muted.bug-closed`); lift it with
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" unmute --test <path> <manifestPath>`.
6. **Report + handoff**: `Materialized <taskId> for <bugId> — run /audit:run <taskId>`.
   Do NOT execute the fix here — execution, commits, and the red-first check are the
   `/audit:run`/`/audit:phase` job (it also flips the bug to `fixed` + `fixedIn` on the task commit).
   That run records what happened to the proof on `task.redFirst`: `proved` when the repro
   was watched failing, `not-attempted` when none was owed, and `could-not-prove` — with the
   refusal verbatim — when something that is not the work stopped it, such as a host
   refusing the edit that temporarily undoes the fix. The third word is not a failed proof
   and costs the task no retry; it is there so a closed bug cannot quietly rest on a repro
   nobody ever saw fail.

## Subcommand: `close <bugId> [wontfix|not_a_bug|fixed]`

1. Refuse if the bug's materialized task is `in_progress` (finish or unblock it via
   `/audit:run` / `/audit:phase` first).
2. Set `status` to the word the caller passed, `wontfix` when they passed none.
   **Ask rather than guess between the two closed-without-a-change answers** — a
   report that was real and will not be fixed, and a report somebody checked and
   found correct, are different facts about the codebase and only the human knows
   which happened. `fixed` only if the human explicitly says it was fixed outside
   the pipeline. Record a one-line `notes` justification either way.

   **A `not_a_bug` row is the whole point of the word**, so do not delete the bug
   instead: a verified negative with no row is an investigation the next reader
   repeats.

   **The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.
3. Revalidate and report.
