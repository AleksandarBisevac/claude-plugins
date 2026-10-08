---
description: 'Audit pipeline: everything a phase has done to it — add one to a plan that already exists, run it end to end (every ready task, parallel where safe, then sign-off), pin which phase the pipeline reaches for first, or cancel one that will not be done. A bare `<phaseId>` runs it; --dry-run previews the run without mutating.'
argument-hint: '<phaseId> [--dry-run] [--confirm-high-risk "<your words>"] | add "<title>" --outcome "<what success is>" [--park] [--id P7] [--description TEXT] [--area a,b] [--gate <entry>] [--gate-clear] [--blocked-by id,id] [--review-skill NAME] | retarget <phaseId> [--gate <entry>] [--gate-clear] [--gate-set <entry> ...] [--gate-drop <entry>] [--area a,b] [--outcome TEXT] [--description TEXT] [--rename TITLE] | priority <phaseId> <tier> [--force] | priority <phaseId> --clear | cancel <phaseId> --reason "<why>" | signoff <phaseId[,phaseId...]> --verdict VERDICT --summary TEXT [--review-outcome TEXT] [--no-evidence-reason TEXT] [--branch NAME] [--plan] [--bind] [--accept SHA --reason TEXT] | settle'
allowed-tools: Read, Write, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:phase — add a phase, run it, order it, or close it

`S` below is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts`.

## 0. Which verb

The first token of `$ARGUMENTS` decides: `add`, `retarget`, `priority`, `cancel`, `signoff` or
`settle`; any other first token is a phase id and runs it. If the manifest names a phase whose id
is that reserved word, ask (AskUserQuestion) which was meant.

## Run a phase — `<phaseId> [--dry-run] [--confirm-high-risk "<your words>"]`

0. `--dry-run`: `S/git/close-phase.py" <manifest> <phaseId> --project <dir> --dry-run` and
   `S/manifest/resolve-branch.py" <manifest> --phase <phaseId>`; print the plan and stop.
1. `--confirm-high-risk "<your words>"`: run `S/governance/record-risk-confirmation.py"
   <manifest> <phaseId> --confirm-high-risk "<your words>"` first and print the task ids it covers
   verbatim in your own reply - a high-risk task not on that list still stops and asks.
   **The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The
   operator's words go in unchanged*.
2. Run `S/governance/drive-phase.py" next <phaseId>`, do what it prints, and run it again:
   `dispatch <agent> <id> model=<m> brief=<path>` → one Agent call with that `subagent_type` and
   `model`, the prompt `Read your brief at <path> and follow it.`, and the rule printed under it;
   `decide <name> ...` → `next <phaseId> --answer <option> [--reason "<words>"]`, a human's
   decision going to the human first (AskUserQuestion); a `stopped` print → relay it as printed.
3. A finished wave is not a stop: run `next` again until it prints `done`.
4. `done` → report what landed and where. **Phase sign-off** (orchestrator) is the drive's last
   step: a fix task comes first, because its edits invalidate a gate taken before them; the
   driver gates once, after the triage. Nothing measures whether you held the order when a gate
   is run by hand.

## Subcommand: `add "<title>" --outcome "<what success looks like>"`

Gather only what the conversation lacks: the outcome, the tasks (title, description, files, test
mode) and the open choices the request leaves (`[]` when none). Write the plan file with the Write
tool, outside the tracked tree: `{"request": "<as typed>", "openChoices": [...], "phase":
{"title", "desiredOutcome", "description"}, "tasks": [{"key", "title", "description", "files",
"tests": {"mode", "add": ["<path>: <what it asserts>"]}, "dependsOn"}]}`. Omit `id`: over a plan
holding `P0`, `P1` and `P3`, the next id is `P4`, and never the `P2` the gap makes look free.
Then run `S/manifest/audit-task.py" add --from-file <the file>` and print its line. On a phase
branch, ask first: work the phase needs is `/audit:task add --phase <id>`; new work is
`add-phase "<title>" --outcome "<..>" --park`. **`/audit:phase add --risk` is refused** - a
phase carries no risk. Exit 3: the index lock is held - stop; 4: it looks abandoned - ask the
human before `--takeover`.

## Subcommand: `retarget <phaseId>`

`S/manifest/audit-task.py" retarget <phaseId>` with the flags the hint lists; relay a refusal.

## Subcommand: `priority <phaseId> <tier>` (or `priority <phaseId> --clear`)

`S/manifest/set-priority.py" <manifest> <phaseId> <tier> [--force]`, or `--clear`. A second
holder of tier 1 is refused naming it - offer clearing it before `--force`.

## Subcommand: `signoff <phaseId> --verdict passed|skipped --summary TEXT`

`S/manifest/audit-task.py" signoff <phaseId> --verdict ... --summary "<..>"`. The drive runs it at
sign-off; relay a refusal.

## Subcommand: `settle`

`S/manifest/audit-task.py" settle`: stores stale derived values, when the plan owner says.

## Subcommand: `cancel <phaseId> --reason "<why>"`

The writer is `commands/task.md`'s `cancel`, with the id a phase id. A task id is refused before
any write, naming `/audit:task cancel <taskId> --reason "<why>"`.
