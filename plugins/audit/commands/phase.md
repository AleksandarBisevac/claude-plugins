---
description: 'Audit pipeline: everything a phase has done to it — add one to a plan that already exists, run it end to end (every ready task, one at a time or as waves, then sign-off), pin which phase the pipeline reaches for first, or cancel one that will not be done. A bare `<phaseId>` runs it; --dry-run previews the run without mutating.'
argument-hint: '<phaseId> [--dry-run] [--confirm-high-risk "<your words>"] | add "<title>" --outcome "<what success is>" [--park] [--id P7] [--description TEXT] [--area a,b] [--gate <entry>] [--gate-clear] [--blocked-by id,id] [--review-skill NAME] [--parent-branch NAME] | retarget <phaseId> [--gate <entry>] [--gate-clear] [--gate-set <entry> ...] [--gate-drop <entry>] [--area a,b] [--outcome TEXT] [--description TEXT] [--rename TITLE] [--parent-branch NAME] | priority <phaseId> <tier> [--force] | priority <phaseId> --clear | cancel <phaseId> --reason "<why>" | signoff <phaseId[,phaseId...]> --verdict VERDICT --summary TEXT [--review-outcome TEXT] [--no-evidence-reason TEXT] [--accept-open ID=REASON] [--carried ID=ID] [--branch NAME] [--plan] [--bind] [--accept SHA --reason TEXT] | settle'
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:phase — add, run, order, close a phase

`S` below is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts`.

## 0. Which verb

`$ARGUMENTS`' first token: `add`, `retarget`, `priority`, `cancel`, `signoff`, `settle`, or a
phase id to run. A phase id spelling a verb: ask (AskUserQuestion) which.

## Run a phase — `<phaseId> [--dry-run] [--confirm-high-risk "<your words>"]`

0. `--dry-run`: `S/status/audit-status.py" --phase <phaseId>`,
   `S/manifest/resolve-branch.py" <manifest> --phase <phaseId>` and `S/git/close-phase.py"
   <manifest> <phaseId> --project <dir> --dry-run`, whose `no branch is recorded` exit 1 reads
   `not started yet`, never a refusal - print the plan, stop.
1. `--confirm-high-risk "<your words>"`: run `S/governance/record-risk-confirmation.py"
   <manifest> <phaseId> --confirm-high-risk "<your words>"` first; print the ids it covers
   verbatim in your reply - a task off it asks unless the owner typed `#approve-high-risk`
   (`#revoke-high-risk` disarms). **The operator's words go in VERBATIM**.
2. Run `S/governance/drive-phase.py" next <phaseId> --signal` and do what its line says until
   `done`: `audit <phase> <verb> <subject> ... | <basis> | next: <command>`, whole under
   `next <phaseId> --explain <subject>`.
3. `dispatch` → a `run:` line under `--explain`: background Bash. The session is its own
   process under its own --budget-usd, set by executor.writerBudgetUsd; it is not drawn from this
   session's budget, so launch the run: line as printed. Else an Agent per
   subject (`subagent_type`, `model`: basis), prompt
   `Follow the brief this prints: S/governance/drive-phase.py" brief --manifest "<manifest>" --project-dir "<project>" --role <role> <id>`; `judge`,
   `wait` → do `next:`; `ask` → the human first (AskUserQuestion); `review` → read it whole,
   answer; `stop` → relay it whole.
4. `done` → report what landed and where. **Phase sign-off** (orchestrator) is the drive's last
   step: a fix task comes first, its edits invalidate an earlier gate. Nothing measures whether you held the order
   for a hand-run gate. A `chain:` line: clear context, then re-enter with `/audit:phase <next id>`.

## Subcommand: `add "<title>" --outcome "<..>"`

Ask what is missing, run `S/manifest/audit-task.py" add --from-file - <<'PLAN'`
with this body and a closing line `PLAN`; print its line: `{"request": "<as typed>",
"openChoices": [<each choice it left open>], "phase": {"title", "desiredOutcome", "description"},
"tasks": [{"key", "title", "description", "files", "tests": {"mode", "add": ["<path>: <what it
asserts>"]}, "dependsOn"}]}`. A hint flag given sets the `phase` key
`S/manifest/audit-task.py" add-phase --help` prints beside it.
Omit `id`: over `P0`, `P1`, `P3` the next is `P4`, never `P2`.
`--park`, or no tasks yet: `S/manifest/audit-task.py" add-phase "<title>" --outcome "<..>"` with the flags. On a
phase branch ask first: phase work is `/audit:task add --phase <id>`; new work is
`add-phase ... --park`. **`/audit:phase add --risk` is refused** - phases carry no risk.
No plan yet: created, no placeholder.
Exit 3 (lock held): stop; 4 (looks abandoned): ask the human before `--takeover`.

## Subcommand: `retarget <phaseId>`

`S/manifest/audit-task.py" retarget <phaseId>` with the hint's flags; relay a refusal.

## Subcommand: `priority <phaseId> <tier|--clear>`

`S/manifest/set-priority.py" <manifest> <phaseId> <tier> [--force]`, or `--clear`. A second
holder of tier 1 is refused by name - offer clearing before `--force`.

## Subcommand: `signoff <phaseId> --verdict passed|skipped --summary TEXT`

`S/manifest/audit-task.py" signoff <phaseId> --verdict ... --summary "<..>"`; relay a refusal.

## Subcommand: `settle`

`S/manifest/audit-task.py" settle`: stores stale values, per the plan owner.

## Subcommand: `cancel <phaseId> --reason "<why>"`

`commands/task.md`'s `cancel` for a phase id; a task id is refused, naming `/audit:task cancel <taskId> --reason "<why>"`.
