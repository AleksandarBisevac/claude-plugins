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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <taskId>
```

Do exactly what each print says and run it again:

- `dispatch <agent> <id> model=<m> brief=<path>` → one Agent call with that `subagent_type`
  and `model`, the prompt `Read your brief at <path> and follow it.`, and the rule printed under
  it. Wait for its one-line hand-back.
- `decide <name> ...` → answer with one printed option:
  `next <taskId> --answer <option> [--reason "<words>"]`. A decision the printed rule gives to a
  human goes to the human first (AskUserQuestion). **The operator's words go in VERBATIM** — see
  `reference/manifest-conventions.md` → *The operator's words go in unchanged*: a `--reason` is
  theirs, unparaphrased, and reaches the hash-chained journal.
- `done <taskId>: ...` → report the outcome and what is ready next, and stop.
- a `stopped` print → relay it to the human as printed, with the rule under it.
