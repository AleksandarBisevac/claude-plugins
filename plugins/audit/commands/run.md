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
Run it, do exactly what it prints, and run it again:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <taskId>
```

- `dispatch <agent> <id> model=<m> brief=<path>` → one Agent call with that `subagent_type`
  and `model`, the prompt `Read your brief at <path> and follow it.`, and the rule printed under
  it. Wait for its one-line hand-back.
- `decide <name> ...` → answer with one printed option:
  `next <taskId> --answer <option> [--reason "<words>"]`. A decision the printed rule gives to a
  human goes to the human first (AskUserQuestion).
- `done <taskId>: ...` → report the outcome and what is ready next (`/audit:status`), and stop.
- a `stopped` print → relay it to the human as printed, with the rule under it.

**Guards the driver hands back.** `done <taskId>: already done` means the task was closed before
this run: report its commit and offer (AskUserQuestion) a re-open, never a silent re-run. On a yes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" reopen <taskId> --reason "<their why>"
```

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The
operator's words go in unchanged*: `--reason` reaches the hash-chained journal (`-` reads it off
stdin). A task with an `ado` link then owes its board card the move back to the pending state,
with the comment `reopened by /audit:run`. Then run `next <taskId>` again. A blocked task stops
the drive with its recorded reason
and the rule for it; an `in_progress` one resumes from where its last run stopped.
