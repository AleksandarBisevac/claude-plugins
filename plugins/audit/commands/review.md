---
description: 'Audit pipeline: re-run Phase sign-off for a phase on demand (e.g. after fixes) — review, test gate, invariant check, optional runtime boot, merge.'
argument-hint: '<phaseId> [--full]'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit:review — re-run a phase's sign-off

`$ARGUMENTS` = the phase id, plus optional `--full`. For a phase whose tasks are all closed - the
recovery path after fixes. The step driver runs sign-off; run it, do exactly what it prints, and
run it again:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/drive-phase.py" next <phaseId>
```

- `dispatch <agent> <id> model=<m> brief=<path>` → one Agent call with that `subagent_type`
  and `model`, the prompt `Read your brief at <path> and follow it.`, and the rule printed under
  it. Wait for its one-line hand-back.
- `decide <name> ...` → answer with one printed option:
  `next <phaseId> --answer <option> [--reason "<words>"]`. A decision the printed rule gives to
  a human goes to the human first (AskUserQuestion). **The operator's words go in VERBATIM** —
  see `reference/manifest-conventions.md` → *The operator's words go in unchanged*: a `--reason`
  is theirs, unparaphrased, and reaches the hash-chained journal.
- `done <phaseId>: ...` → report the verdict and where the phase landed, and stop.
- a `stopped` print → relay it to the human as printed, with the rule under it.

Once every task is closed it dispatches the phase reviewer, records the review's findings in one
write and prints one `decide triage`; `sign-off` with the summary then runs the phase gate, the
invariants check, the verdict, the commit, the landing and the lock release as one step, and
stops before the verdict when the phase gate is red. A phase already signed off goes straight to
its commit and landing, which are safe to re-run: a branch already in its parent reports
`already-contained` and keeps its `mergedAt`.

**Every actionable finding gets a NEW TASK, and the drive creates and starts it** - you do not
hand the operator a command. Answer the triage `fix --fix <findingId>[,<findingId>]`: each named
finding becomes a task through `/audit:task add --fixes`, which the drive then runs the way
`/audit:run` runs one. The plan gate opens a file only through a RUNNING task, so a fix made
any other way is refused on its first edit; `/audit:task scope` on a done task opens nothing.

The reviewer is **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** - the
first level that is present answers, and an explicit `null` is an answer (no review; the tests
sign). `/audit:status --phase <phaseId>` prints the resolved skill and its basis.

A re-run after the branch was deleted is legitimate: the invariants check answers `no-basis` for
`branch-history` - the evidence is gone, not a problem with this run.

**`--full`** runs the third place after sign-off completes:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/full-gate.py" <manifest> [--project-dir <dir>]
```

It measures the whole product rather than this phase and exits with the runner's code. Read its
answer afterwards in `/audit:status`'s tests column and `/audit:doctor`'s `full run` row. A plan
with no `meta.fullGate` prints that it names no third place and exits 0. A red run files what it
taught - a coupling and a bug per selection miss - under `[full-gate]`, and stays red: report the
coupling and the bug with the rest of the sign-off.

What each step checks, and why, is `reference/phase-signoff.md` for a reader who asks.
