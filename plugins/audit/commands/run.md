---
description: 'Audit pipeline: execute exactly one task by id, with status guards (done/blocked/in_progress) and blocker checks. --dry-run previews without mutating.'
argument-hint: '<taskId> [--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:run — execute one task

`$ARGUMENTS` = the task id, plus optional `--dry-run`.

**`--dry-run`:** run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" --short`,
say whether the task is ready and what would run, and stop without changing anything.

**Otherwise the step driver runs it.** `drive-phase.py next <taskId>` drives that one task: it
takes the phase lock, starts the task (a refused start names what it waits on), writes each
agent's brief, records the gate, commits and closes - and leaves its siblings and sign-off alone.
The `--task` flag is what makes this the one-task form: given a phase id (`p1`, `P1`, `1`) it
exits 2 with one line naming `/audit:phase <id>` and the tasks that verb would run, and starts
nothing and picks no task. `/audit:phase` runs those tasks in waves when `executor.waveWidth` is
above 1 and one at a time otherwise. Relay that line; never choose a task for the user.
Run it, do exactly what it prints, and run it again:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <taskId> --task --signal
```

Its one line is `audit <phase> <verb> <subject> ... | <basis> | next: <command>`; the whole
step is `next <taskId> --explain <subject>`.

- `dispatch` → an Agent (`subagent_type`, `model`: the basis), the prompt
  `Follow the brief this prints: python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" brief --manifest "<manifest>" --project-dir "<project>" --role <role> <id>`.
  Wait for its one-line hand-back, then `next <taskId> --task --signal`.
  With `executor.writerModel` set, a writer's `dispatch` is a `run:` line under `--explain`
  instead: run it in background Bash and call next after it exits.
- `judge`, `wait` → do `next:`; `ask` → the human first (AskUserQuestion), then `next:` with
  their option.
- `done` → report the outcome and what is ready next (`/audit:status`), and stop.
- `stop` → relay it to the human whole, as `--explain` prints it.

**Guards the driver hands back.** A `done` whose basis reads `already done` means the task was closed before
this run: report its commit and offer (AskUserQuestion) a re-open, never a silent re-run. On a yes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" reopen <taskId> --reason "<their why>"
```

**The operator's words go in VERBATIM**, unparaphrased: `--reason` reaches the hash-chained
journal (`-` reads it off stdin). A task with an `ado` link then owes its board card the move back to the pending state,
with the comment `reopened by /audit:run`. Then run `next <taskId> --task --signal` again. A blocked task stops
the drive with its recorded reason
and the rule for it; an `in_progress` one resumes from where its last run stopped.
