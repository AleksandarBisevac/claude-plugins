---
description: 'Audit pipeline: print manifest status — phases, tasks, bugs, the ready-now list and what each pending task is waiting on; or, with --gate, turn that same state into a CI pass/fail verdict over conditions you pick with --fail-on. Read-only, no locks, no mutations.'
argument-hint: '[--gate] [--fail-on <c1,c2,...>] [--phase <id>] [--json] [--color auto|always|never]'
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
on, a `tests` column carrying the verdict of the run that last exercised each task
exactly as the manifest recorded it — shown only when a task in view has recorded
one, so a plan that has never run a gate renders exactly as it did before the column
existed, and `-` inside it means no run was recorded, which is not a failure — the
ready-now list with a copy-pasteable `/audit:run <id>`, open bugs, parked
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

`--phase <id>` scopes the **human render** to one phase - the table lists that phase
alone, and the render says so on a line of its own. **Totals stay whole-plan**: the
overall line, the usage line and the bug counts are the project's, not the phase's,
because a phase view that silently rescoped them would misreport the project. **And it
does not scope the other modes** - `--gate` evaluates its conditions over the whole
manifest and `--json` emits the whole rollup, whatever `--phase` says, so
`--phase P3 --gate` still gates on a task in P7. That last reading has already been got
wrong here. An id no phase carries is a usage error (exit 2) naming the ids there are.

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
gates on in-progress work and on nothing else. `--help` prints the names with their
meanings, rendered from the same tuple the gate evaluates:

- `invalid` — the structural validator reports findings
- `open-high-bugs` — a bug of high-or-worse severity is not yet `fixed`/`wontfix`
- `open-bugs` — **any** bug is not yet `fixed`/`wontfix`
- `blocked-tasks` — any task has status `blocked`
- `in-progress` — any phase or task is `in_progress` (release-freeze gates)
- `over-budget` — a phase is at or past 100% of its `budgetUSD`
- `budget-80` — a phase is at or past 80% of its `budgetUSD`
- `invariant-breach` — a started phase breaks one of the orchestrator's invariants,
  checked **after the fact** by `scripts/governance/verify-invariants.py` against git,
  the phase shard, the journal and the usage ledger
- `failing-tests` — a task or phase whose recorded `testEvidence.status` cannot sign
  work off: `failed`, `no-checks` (exit 0, and still not a verdict — the gate ran and
  found nothing to check), `timed-out`, `cancelled` (both stopped rather than
  answered) or `could-not-run` (the runner never started). `passed` and `empty-gate`
  do not trip it
- `no-test-evidence` — a `done` task **or phase** carrying no `testEvidence` at
  all **that could have carried one**. Both scopes, exactly like `failing-tests`: a
  phase's sign-off gate records a run of its own, and no task's pointer stands in
  for it. Work that finished before the *evidence boundary* is excused rather than
  failed — see below

Neither budget condition is in the default, deliberately: spend is a signal, not a
defect, and a phase at 105% may be entirely justified. Opt in when a budget is a
commitment rather than an estimate.

**Neither test-evidence condition is in the default either, and both refuse to read a
silence as a failure.** A manifest written before the field existed, a task nobody has
run and a block somebody deleted are one state — *no run was recorded* — so a plan
that has never recorded a run trips neither condition and a default holding them would
fail every build on the day the plugin was upgraded. `no-test-evidence` is the way to
ask for the opposite reading, and it asks it of every subject the plan already calls
`done` — a phase as readily as a task, because a phase is signed off by a gate run of
its own. A `status` word this build does not recognise trips nothing: the enum may gain
members, so it is reported as itself rather than folded into `failed`.

**The evidence boundary is what makes `no-test-evidence` usable for a plan adopted
mid-flight.** A project that starts using the plugin part-way through carries tasks
that were finished before the recorder existed, and without a boundary every one of
them fails this condition with no setting that helps — `--phase` scopes the human
render, and says so in its own help, not the gate. The boundary is the earliest
moment anything says recording existed at all: the **earlier** of
`meta.evidenceSince.at` and the first run in the evidence file beside the plan.
Earlier, because excused work is *before* the boundary, so the earlier value is the
safer one — delete the key and the file still answers, archive the file and the key
still answers. Work that finished before it is **excused**, and the gate prints the
basis it excused on, on a passing run as well as a failing one.

**The other states are named apart because the repairs differ.** A subject the plan
cannot date — no `completedAt` on a task, no `mergedAt` on a phase — fails in its
own sentence, because the repair there is to set the stamp rather than to run the
gate. A plan where *nothing* says when recording began excuses everything in it,
which is the state a mid-flight adopter is in before anything has run. And when a
source of the boundary could not be **read** — an unparseable plan, a torn line in
the evidence file — work excused on it **fails** instead of passing: the unreachable
source may have held an earlier moment, which would make the excuse wider than it
should be, and a widened excuse turns a build green where nobody is looking.

**No backfill is offered, and that is a decision rather than an omission.** A gate
run today measures one tree once, so writing a pointer onto every historical subject
would manufacture claims out of a single measurement — the shape recorded evidence
exists to remove, not one to add. `/audit:run-gate` is for a subject or a few; it is
not a history tool.

**Neither condition resolves a pointer.** The block is a *cache* of a run recorded
in the evidence file beside the plan; `failing-tests` opens nothing at all, and
`no-test-evidence` opens that file only to date the boundary above — for the
earliest run in it, never to ask whether a subject's own `runId` still resolves.
That question belongs to
`/audit:doctor` and to `--fail-on invariant-breach`. The `tests` column in the render
carries the same word where a task has one, and a phase's own verdict is a `tests
<word>` clause on its head line.

`invariant-breach` is out of the default for a different reason: it reads git several
times per started phase, and a default that slow is a default somebody replaces. What
it buys is the half of this plugin's rules that no hook can enforce — a task commit
staging only its own files, no push or forced update or stash on the phase branch,
every committed manifest state still validating, a `risk: "high"` task off `haiku`, and
`phase.baseRef` on the branch the phase forks from. **A missing basis does not trip
it**: a phase whose branch was deleted at sign-off has no reflog left to read, and the
verdict for that check is the word `no-basis` in the output rather than a failed build.
A block that was never computed *does* trip it — a gate cannot report a clean bill of
health over checks that did not run. Run the checker directly for the detail:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/verify-invariants.py" <manifestPath> --all
```

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
