---
description: 'Audit pipeline: print manifest status — phases, tasks, bugs, the ready-now list and what each pending task is waiting on; or, with --gate, turn that same state into a CI pass/fail verdict over conditions you pick with --fail-on. Read-only, no locks, no mutations.'
argument-hint: '[--gate] [--fail-on <c1,c2,...>] [--json] [--color auto|always|never]'
allowed-tools: Bash
---

# /audit:status — pipeline status report

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**

It already renders the whole report: an overall line with a progress bar, the usage
line when metering is on, one aligned table across every phase (markers `[x]` done ·
`[~]` in_progress · `[!]` blocked · `[ ]` pending), what each pending task is waiting
on, the ready-now list with a copy-pasteable `/audit:run <id>`, open bugs, parked
proposals when `/audit:init` parked any (plus a one-line footer counting free-form
legacy proposals, which `/audit:propose list` still reads), a `BY AREA` rollup when the
plan tags areas (per tag: phases and done/total tasks, ` - <owner>` when the area
declares its advisory owner, an `untagged` footer, and — only when a phase actually
carries several tags — the caveat that such a phase counts under each), and a
RESUMABLE line when a phase was interrupted.

This used to be prose telling you how to lay the rollup out. That cost tokens on every
call and produced a different layout each time — the same self-defeating shape
`/audit:usage` already refuses. You do **not** need to read the manifest either: the
renderer reads it in-process, so the per-task detail that once required a second read
is in the output already.

Pass `$ARGUMENTS` through unchanged. `--json` emits the machine-readable rollup
instead, for CI or another tool.

## Gate mode (`--gate`, `--fail-on`)

The same rollup, turned into a pass/fail signal — this is the half of the command a
pipeline runs with no Claude session involved. `--gate` prints one
`GATE FAILED: <condition> (<detail>)` line per tripped condition and exits **1**, or
`GATE PASSED: <conditions>` and exits **0**. `docs/examples/azure-pipelines.yml` runs
exactly this to block a merge on manifest state.

**With `--json` those lines go to stderr instead**, so stdout stays parseable — it used
to print the JSON and then the `GATE ...` line on the same stream, which is not JSON and
which nothing could pipe into `jq`. The verdict is not lost by the move: `.gate` in the
payload carries `conditions`, `failed` and `passed` in full, and the exit code says the
same. Without `--json` stdout is unchanged, which is what the pipeline above reads.

`--fail-on <c1,c2,...>` chooses the conditions, and it **replaces** the default set
(`invalid,open-high-bugs,blocked-tasks`) rather than adding to it — `--fail-on in-progress`
gates on in-progress work and on nothing else. The seven names:

- `invalid` — the structural validator reports findings
- `open-high-bugs` — a bug of high-or-worse severity is not yet `fixed`/`wontfix`
- `open-bugs` — **any** bug is not yet `fixed`/`wontfix`
- `blocked-tasks` — any task has status `blocked`
- `in-progress` — any phase or task is `in_progress` (release-freeze gates)
- `over-budget` — a phase is at or past 100% of its `budgetUSD`
- `budget-80` — a phase is at or past 80% of its `budgetUSD`

Neither budget condition is in the default, deliberately: spend is a signal, not a
defect, and a phase at 105% may be entirely justified. Opt in when a budget is a
commitment rather than an estimate.

Three things to get right when building the invocation:

- **`--fail-on` without `--gate` gates nothing.** The conditions are parsed and then
  ignored; you get the human report and exit 0. Pass both, always.
- A name that is not on the list is a **usage error** — exit 2, and the message names
  the known set. Nothing is silently dropped, so never guess a condition: run it and
  read the exit code.
- `--gate --json` prints the rollup (with a `gate` block naming `conditions`, `failed`
  and `passed`) **and then** the `GATE …` line, so that stream is not parseable JSON on
  its own. Pick one, or run the two invocations separately.

Preflight is not needed here — this command takes no lock and mutates nothing. Read
`${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` only if the human then asks you to
act on what the output says.

## If the output reports a problem

- **INVALID MANIFEST** — relay it and stop. `/audit:doctor` names the findings.
- **RESUMABLE** — offer `/audit:resume`.
- **nothing ready** — the plan is either complete or fully blocked. The `waiting on`
  column says which, per task, so do not guess.

Do not modify anything. Related: `/audit:doctor`, `/audit:next`, `/audit:run`,
`/audit:phase`, `/audit:report`, `/audit:usage`, `/audit:init`, `/audit:task`,
`/audit:bug`, `/audit:sync`.
