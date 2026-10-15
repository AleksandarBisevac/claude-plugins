---
description: 'Audit pipeline: execute the next ready task (phase order, then task-id order), then report what is ready next. --dry-run previews without mutating.'
argument-hint: '[--dry-run]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:next — execute the next ready task

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" --short`. Its first entry
under READY NOW is the task this command runs; do not re-derive the readiness rule. Show that
list verbatim in your own reply, as a short fenced block, since a tool result is collapsed behind
the call.

**`--dry-run`** (in `$ARGUMENTS`): say which task would run and stop, changing nothing. **No
ready task:** relay the `waiting on` column it printed per task, and stop.

Otherwise run that one task through the step driver, exactly as `/audit:run` does - `next
<taskId>` drives that task alone, and the two commands differ only in how the task is chosen:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <taskId> --signal
```

Do what its one line says, `audit <phase> <verb> <subject> ... | <basis> | next: <command>`,
until `done`; the whole step is `next <taskId> --explain <subject>`.

- `dispatch` → an Agent per subject (`subagent_type`, `model`: the basis), the prompt
  `Follow the brief this prints: python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" brief --manifest "<manifest>" --project-dir "<project>" --role <role> <id>`.
  Wait for its one-line hand-back, then `next <taskId> --signal`.
- `judge`, `wait` → do `next:`; `ask` → the human first (AskUserQuestion), then `next:` with
  their option. **The operator's words go in VERBATIM**: a `--reason` is theirs, unparaphrased,
  and reaches the hash-chained journal.
- `done` → report the outcome and what is ready next, and stop.
- `stop` → relay it to the human whole, as `--explain` prints it.
