---
description: 'Audit pipeline: resume an interrupted run — find the in-progress phase and continue from the first uncommitted task.'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:resume — continue an interrupted run

For a run a crash, a lost session or an interrupted `/audit:phase`, `/audit:next` or `/audit:run`
left behind. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" --short`: the
phase it flags resumable is the one to continue. None flagged → say so and stop.

**Sweep the interrupted session's record first**, before anything else touches the tree:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-audit-state.py" <manifestPath> <phaseId>
```

It commits the phase's manifest file, the journal and the evidence directory, and never a task's
`files` - so the rows a torn-down gate wrote reach git, and the interrupted task's own edits stay
untrusted and unstaged. With nothing uncommitted it says so and commits nothing; run it on every
resume rather than deciding first.

**Then the step driver continues the phase.** It keeps its state per phase, so a task in progress
resumes at the step it stopped on - an agent that filed nothing becomes a named decision rather
than a silent second dispatch:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <phaseId> --signal
```

Do what its one line says, `audit <phase> <verb> <subject> ... | <basis> | next: <command>`,
until `done`; the whole step is `next <phaseId> --explain <subject>`.

- `dispatch` → an Agent per subject (`subagent_type`, `model`: the basis), the prompt
  `Follow the brief this prints: python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" brief --manifest "<manifest>" --project-dir "<project>" --role <role> <id>`.
  Wait for each one-line hand-back, then `next <phaseId> --signal`.
- `judge`, `wait` → do `next:`; `ask` → the human first (AskUserQuestion), then `next:` with
  their option; `review` → read it whole under `--explain`, and answer.
  **The operator's words go in VERBATIM**: a `--reason` is theirs, unparaphrased, and reaches the
  hash-chained journal.
- `done` → report the outcome, and stop.
- `stop` → relay it to the human whole, as `--explain` prints it.

**An interrupted task's uncommitted edits are untrusted.** Never discard them, and never let a
commit settle them, without the human's confirmation (AskUserQuestion).
