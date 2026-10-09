---
description: Add a tracked task to the audit manifest — every answer is a flag, and the dialogue only covers what the caller did not pass — promote one to running, close one that landed, move one between phases, or cancel work that will not be done. `add` allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates; `start` promotes a task to in_progress so the plan gate resolves its files, without spawning anything; `done` closes it against the commit its work landed in, writing status, completedAt, commit, outcome and verifiedBy in one write — or, with `--no-change --reason`, closes a task whose answer was that nothing needed to change; `reopen` puts a done task back to pending with the reason recorded; `move` renumbers a task into another phase, rewrites every reference, and records a chained task.move journal row; `block` sets a task blocked with the reason beside the status; `unblock` resets the attempts a task has spent, on a human's recorded reason; `note` appends a dated note, the one addition a started task takes; `cancel` closes a task — or, as the legacy spelling of `/audit:phase cancel`, a whole phase — as terminal-but-not-done, recording the reason, the moment and a journal row. `priority` is the legacy spelling of `/audit:phase priority` and still works.
argument-hint: 'add "<title>" [--phase <id>] [--description TEXT] [--files a,b] [--outputs pat,pat] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--failing-from RUNID] [--risk RISK] [--model NAME] [--skills a,b] [--blocked-by ids] [--depends-on ids] [--dry-run] [--from-file PATH] [--fixes findingIds] [--bug bugId] | start <taskId> [--force --reason "<why>"] | done <taskId> [--commit <sha>] [--no-change --reason "<why>"] [--descriptive TEXT] [--technical TEXT] [--verified-by t1,t2] [--intent ANSWER] [--intent-basis TEXT] [--override-verdict TEXT] [--from-return] | reopen <taskId> --reason "<why>" | scope <taskId> [--files a,b] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--description TEXT] [--risk RISK] [--blocked-by ids] [--depends-on ids] | move <taskId> --to <phaseId> | block <taskId> --reason "<why>" | unblock <taskId> --reason "<why>" | note <taskId> --text TEXT | couple --test <path> --sources a,b --basis-run <runId> --basis-head <sha> [--phases id,id], or --test <path> --caught <runId> | uncouple --test <path> | mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId> | unmute --test <path> | cancel <id> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest, promote one, close one, re-open one, move one between phases, block one, note on one, or cancel one

Every verb is one call to the writer, which takes the index lock, revalidates, rolls back on a
finding and journals the write itself - so nothing here is a hand edit and no lock is held by
hand. `T` below is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py"`. An unknown or
empty verb: print the hint and stop.

**The flags are the interface; the dialogue is the fallback.** Pass what the caller already
decided as flags, and ask only for what is missing. A flag another verb reads exits 2 naming that
verb (`scope --outcome` is refused); relay it rather than retrying.

**The operator's words go in VERBATIM**: a `--reason` is theirs, unparaphrased, and reaches the
hash-chained journal, as do `--text` and `--description`; `-` reads the value off stdin. **Print
the writer's output as it came** - a line naming what was written and the file, then any gate
basis, `ready now` command and warning about the id it wrote; `--verbose` prints the rest.

**Exit codes, every verb:** `0` written. `1` the write would leave the plan invalid - rolled back,
the findings printed; fix the inputs. `2` usage - the message names the choices; ask, adjust,
re-run. `3` the index lock is held by a live run - stop, do not take it over. `4` the lock looks
abandoned - ask the human (AskUserQuestion), then re-run with `--takeover`.

## Subcommand: `add "<title>" [--phase <id>]`

1. **Phase.** Pass `--phase` when given. Without it the writer takes the one running phase, or
   exits 2 naming the choices: ask which (AskUserQuestion), or offer `/audit:phase add` for a new
   one - on a phase branch, `/audit:phase add ... --park`. A parked proposal already covering the
   work → offer `/audit:propose materialize <PROP-id>` first.
2. **Gather the answers (ask only for what's missing):** `--description` (the brief - on stdin
   with `--description -` and a quoted heredoc whenever it holds backticks or code punctuation,
   since a shell eats a backticked span and the writer refuses the hole it leaves); `--files`;
   `--outputs` for files the task produces; `--tests-mode tdd|regression|gate-only`;
   `--tests-add "<path>: <what it asserts>"` - the leading path is what reaches `files` and
   `fileIndex`; `--gate` only to override the derived gate, `--gate-clear` for none;
   `--failing-from <runId>` for a fix task after a red sign-off run; `--risk`; `--model`
   (`sonnet` is the floor for fix work, never `haiku`); `--blocked-by` / `--depends-on`.
   **Skills** come from one source:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" --json --discovery --section discovery
   ```
   Offer the area defaults, names that output carries (never invented ones), and `null` (none
   applies; it stops the area fallback); then `--skills a,b`, `--skills null`, or omit the flag.
3. **Run it**, the brief on stdin:
   ```bash
   T add "<title>" --phase <id> --description - --files a,b --tests-mode regression <<'BRIEF'
   <why & how>
   BRIEF
   ```
   `--dry-run` validates and writes nothing. `--fixes <findingId>` adds a fix task for review
   findings - the drive's triage does that itself.

## Subcommand: `start <taskId>`

`T start <taskId>` promotes it (phase entry, branch and attempts included) without spawning. An
unready task or another live session's claim is refused, naming why; `--force --reason "<why>"`
is the human's recorded way past it. A `tdd` or `regression` task that declares no `files` is
refused too: nothing says what its work is. Declare them with `scope <taskId> --files a,b`.

## Subcommand: `done <taskId> --commit <sha>`

`T done <taskId> --commit <sha> --from-return`, or `--no-change --reason "<why>"`. The drive
closes its own tasks; this is for a close made by hand. A refusal names the run or answer it
needs - relay it, never type an `--intent` word a reviewer did not file. A `--commit` close is
also refused, naming the paths, while the working tree still changes files that commit does
not carry: those the task's `files` cover, or, for a task declaring none, any change no other
`in_progress` task covers (the plan's journal, evidence and manifest files never count). Commit
them or widen the task with `scope <taskId> --files a,b`.

## Subcommand: `reopen <taskId> --reason "<why>"`

`T reopen <taskId> --reason "<why>"` puts a done task back to pending.

## Subcommand: `block <taskId> --reason "<why>"`

`T block <taskId> --reason "<what it waits on>"`.

## Subcommand: `unblock <taskId> --reason "<why>"`

`T unblock <taskId> --reason "<the human's words>"` - only after a human says try again: it
resets the spent attempts (a blocked task goes back to pending) and journals the reason.

## Subcommand: `note <taskId> --text TEXT`

`T note <taskId> --text "<what was learned>"` - the one addition a started task takes.

## Subcommand: `couple --test <path> --sources a,b --basis-run <runId> --basis-head <sha> [--phases id,id]` / `uncouple --test <path>`

`T couple ...` / `T uncouple --test <path>`, with the hint's flags.

## Subcommand: `mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId>` / `unmute --test <path>`

`T mute ...` / `T unmute --test <path>`. A mute names the bug tracking what it hides: file it
with `/audit:bug add` first.

## Subcommand: `cancel <id> --reason "<why>"`

`T cancel <id> --reason "<why>"` closes a task, or a whole phase and its open tasks, as
`cancelled`, with the reason in `outcome.descriptive` and the journal row.

## Subcommand: `scope <taskId> [--files a,b]`

`T scope <taskId>` with the hint's flags. On a started task `--risk`, `--description`,
`--tests-mode`, `--blocked-by` and `--depends-on` all keep the old refusal; `--files` and
`--tests-add` may only grow, and `tests.gate` may be replaced outright - it is read forwards only.

## Subcommand: `move <taskId> --to <phaseId>`

`T move <taskId> --to <phaseId>` renumbers a pending or blocked task and rewrites every reference.

## Subcommand: `priority <phaseId> <tier|--clear>` — the legacy spelling

Still works: follow `/audit:phase priority` with the same arguments, and say the new name once.
