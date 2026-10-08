---
description: 'Audit pipeline: diagnose the setup before it bites — interpreter the hooks will use, git root, config, manifest + shard integrity, which plan-gate tier is active, submodule conflicts, build runners, whether the skills the plan names would resolve from a clone or only here, whether hooks have ever fired and which copy of the plugin ran them, the usage ledger, whether the audit trail still holds, and whether the capability policy is inert, contradicted by the plan, or never enforced. Read-only, no locks, no mutations.'
argument-hint: '[--deep] [--json] [--color auto|always|never] [--transcript <path>]'
allowed-tools: Bash
---

# /audit:doctor — is this setup actually working?

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-doctor.py" --project "$(pwd)" $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**
**Print it in your own reply, inside a fenced block** — a tool result is collapsed behind the tool
call, so running the command is not delivering it.
It already renders plain ASCII with one line per check, an indented `->` fix under anything
actionable, and a totals line. Re-narrating it costs tokens and loses the alignment that
makes the output scannable.

Pass `$ARGUMENTS` through unchanged (`--json` for a machine-readable form). Nothing here
needs interpreting on your side.

## `--deep` — hold the task commits against the journal

Off by default, and off is right for a routine run. `--deep` adds one arm to the
**completions** check: for each done task in the completion-record era that names both a
commit SHA and a journal row, it asks git whether that commit's tree actually contains the
journal file recording the task. That is one `git ls-tree` per such task, so the cost
scales with how much completed history the plan has — which is why it is opt-in rather
than always on. It writes nothing and takes no lock, exactly like the default run.

Its only verdict is a **WARNING** — `--deep: the task commit does not carry the journal
file that records it` — so it cannot turn a passing run into a failing one; a run that
exits 0 today still exits 0 with `--deep`. Reach for it when the question is about the
**audit trail** rather than the setup: the journal's git anchor only pins the journal files
the task commits actually carry, and the default run never looks at that.

## `--transcript <path>` — the main-loop cache TTL trade

Off by default, and the row prints no figure without it: name a session's own transcript
`.jsonl` and the `ttl trade` line reports that session's longest gap between main-loop
requests, its one-hour cache writes, and what those same writes would have cost at a
five-minute TTL instead. Once a gap reaches five minutes that price is a floor, printed `at
least`: it leaves out the re-writes the expired cache forces. Documentation only — it recommends nothing the gaps do not
support, and the setting stays yours.

## The `evidence` line — the plan's pointers against the ledger, both ways

In every run, no flag. A `testEvidence` block is a *cache*: it names a `runId`, and the run
itself lives in the append-only evidence ledger beside the manifest. Those two can come apart
in two directions, and they are different problems with different repairs, so the check asks
both and never folds them together:

- **A pointer naming a run no row in this checkout carries** — `the plan refers to evidence
  that is not here`. A clone that received the plan without the evidence directory, a file
  that was removed, or a block written by hand. The plan is claiming a record it cannot show.
- **A recorded run whose subject's pointer does not name it** — `the record is ahead of the
  plan`. This is not damage: it is exactly what a **refused pointer** leaves behind when
  another live session held the phase lock while the gate was recorded. The repair is one
  pass over the ledger, and the warning names it:

  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" \
      <manifestPath> <phaseId> --reconcile
  ```

  The phase id is required by the parser and **not read by this pass** — reconcile re-derives
  the pointer of every subject the ledger names, whatever phase it was handed, and runs no
  gate and no subprocess. It exits non-zero only when a pointer was refused again, naming
  which subjects it left behind. It also **writes**: it edits the phase shard, which is why
  it is a command to hand the user rather than something this read-only command does for
  them.

**Everything here is a WARNING at most, and that is the division of labour rather than
leniency.** The working tree is where a mismatch is routine and repairable, so a run that
exits 0 today still exits 0 with this line present. The same question asked of what is
**committed** — does the plan HEAD carries name runs HEAD holds, as a clone would receive
them — is `evidence-committed` in `verify-invariants.py`, and there a mismatch is a breach;
`/audit:status --gate --fail-on invariant-breach` is the CI spelling of it.

A ledger this command could not read is a **WARNING that says so**, and it clears nothing —
the same class as the `sandbox` and `secret rules` rows below: a fact that could not be
established is not a clean bill of health. Rows that could not be parsed are counted and
reported rather than dropped, so an evidence directory nobody ever wrote is never confused
with one whose lines are torn. When neither direction has anything to say, the OK line names
both sides — how many pointers the plan carries and how many runs this checkout holds — so
the reader can see that the comparison was actually made.

## What to do with the result

Exit code is the summary: **0** healthy (warnings allowed), **1** one or more findings,
**2** a usage error. The three levels mean different things and should be treated
differently:

- **FINDING** — broken now. The named command or gate will fail. Fix these first; each one
  carries its own `->` fix line.
- **WARNING** — works today, will bite later. A missing manifest, no evidence the hooks have
  run, an empty ledger (told apart from a ledger nothing ever created — that one reads
  `no ledger yet` and names the path metering will write), a stale lock, journal files
  uncommitted for over a week (the git anchor only pins committed history), journal files
  the anchor could not be asked about at all (the `journal anchor` row — the chain may hold
  perfectly and still have been checked against nothing, which is a weaker sentence than it
  reads as), an area owner
  the ledger's author column has never seen (usually an identity written differently from
  what `usage.authorMode` records). Worth reading, not worth blocking on.
  It also covers a second, different thing: a fact this read-only command **could not
  establish**. The `sandbox` and `secret rules` rows read settings files, and managed
  policy plus a `--settings` flag outrank every file they can see — so "no file declares
  it" is reported as *not established*, never as *off*, and never fails the run. An
  explicitly disabled sandbox is a FINDING, because that one is read off a file.
- **OK** — checked and healthy. Included deliberately: knowing the plan gate is in `warn`
  rather than `deny` is as useful as knowing something is broken. The plan-gate line names
  the tier **and what put it there** — `planGate`, legacy `enforce`, or the graded ladder —
  and pinning `planGate: "observe"` while a phase is running is the one setting that warns,
  because it holds the gate below what the evidence would enforce.

The **layout** line is the other one worth reading rather than skimming: it names which of
the two manifest layouts is in use, **and what that layout costs**. Single-file is a supported
shape, not a pending upgrade — `/audit:layout` is how someone *changes* the layout, in either
direction, not how they fix it — so an OK line naming it is a statement of fact and must not be
relayed as a to-do. The line deliberately names no command for that reason; if the user reads
the cost and wants the other shape, that is when `/audit:layout` comes up.

The **merge driver** line says whether this clone merges the manifest by record, and **what
not doing so has cost this repository** - measured, not inferred from a phase count. The
recent merges whose two sides BOTH changed the plan are replayed with `git merge-tree` and
git's own line merge (what a clone without the driver runs), and the line says how many
conflicted in the plan. Not installed with none conflicted is an OK line naming no command,
for the layout line's reason: using the driver is a choice. Not installed with conflicted
merges is a WARNING with `/audit:layout merge-driver install` as its fix - relay the count
and its basis with it, because the count is the argument. "Nothing to measure" means no
recent merge changed the plan on both sides; it is not evidence that the driver is unneeded.
Two per-clone states warn too: `.gitattributes` routes the plan to the driver and this
clone does not configure it (a teammate who has not installed), and a shim whose plugin root
is gone after an upgrade.

The layout is read from the phase stubs (`_manifest_io.is_sharded()`), which is the one reading
the whole plugin shares. A `meta.version` of 3 with no stub carrying a `shard` is therefore a
FINDING about the two disagreeing, not a layout — relay it as a broken index, because that is
what every reader is already treating it as.

If the run reports **no hook state**, the most likely cause is not a broken hook but a
plugin that is installed yet not enabled for this project — check `/plugin` → Installed.

## The `running plugin` line — the copy in force, not the copy on disk

Directly under `hooks`, and it completes it: `hooks` says whether anything has run here,
this says **which copy of the plugin ran it**. They can be different copies.
`CLAUDE_PLUGIN_ROOT` is fixed when a session starts, so a session that began before an
upgrade goes on executing the copy it started with — a guard several releases behind can be
silently in force while this command answers about the installation. That is the harness's
behaviour and nothing here changes it; what this row does is let a user find out.

This command cannot see the hooks' root directly — a hook is a different process, and the
harness substitutes that variable into a command string instead of exporting it, so there is
nothing in this process's environment to read. Disk is the whole channel, and it carries two
kinds of evidence: a **stamp** each session writes on every prompt, which names a root and a
version, and the **shape** of what the guards wrote, where a state file missing a key this
release writes was written by a copy that predates it. The second is the only one that works
against a copy too old to have ever stamped anything.

So there are **three** outcomes, not two, and the row says which it is:

- **OK** — every live stamp here names the copy this command is running from.
- **WARNING, they differ** — a stamp names another copy, or a state file's shape proves one
  did. The line names both copies and the basis (`stamp`, `state shape`, or both), and the
  fix is the only one that works: **start a new session**. A running session cannot be made
  to reload its plugin root.
- **WARNING, NOT ESTABLISHED** — nothing stamped and nothing drifted, or a stamp was there
  and could not be read. This is deliberately not an OK line: the same class as `sandbox`
  and `secret rules` above, a fact this command could not establish rather than one it
  cleared. Relay it as *unknown*, never as *they agree*.

**Live and history.** A stamp's age is the last prompt or guarded tool call of the session
that wrote it: every prompt re-stamps, and `guard-secrets-read` refreshes the stamp on every
call its `hooks.json` matcher, `Read|Grep|Bash|mcp__.*`, selects - a subagent's calls included,
since they carry the parent's session. A copy other than the one this command runs from is
**history** only when its newest stamp is older than the idle bound, which the row prints with
its number: no guarded tool call within it, so the session ended or is idle waiting on its
user. History is reported as the file, the copy it names and its age, with the path to delete
if you want it gone, and it never turns the row yellow. A foreign copy inside the bound is
**live**: a WARNING that says when it was last active and that it may still be running. The
session asking is never the measure — it has always just prompted — so relay a live foreign
copy as a possible stale session, and history as history. The limit: a tool OUTSIDE that
matcher refreshes nothing, so a session using only such tools, or waiting on its user, for
longer than the bound reads as history until its next prompt or matched call.

It is a WARNING at worst in every branch. A stale plugin copy is a thing to tell someone,
not a thing to block on, so a run that exits 0 today still exits 0 with this row present.

This command is **read-only**: it takes no lock, writes nothing, and never executes a
`meta.buildCommands` entry (it resolves the program each one names and reports whether that
program exists). It is safe to run mid-phase, and safe to run in CI.

## The `task restarts` and `gate patterns` lines — what keeps happening, not only what is true now

Every row above answers a question about this moment. These two fold the whole trail into a
claim about a REPEATED fact instead: whether any task has been started more times than the
rest (the journal's `task.start` rows, grouped by task), and whether any gate has run
repeatedly and never once failed (the same tally a plan proposal draws on in
`propose-gates.py`). Neither is visible from a snapshot — a manifest only ever shows a task's
*current* status, never how many times it got there.

**ONE OCCURRENCE IS NOT A PATTERN**, so both hold the same floor before naming one: a trail
thinner than that floor is **WARNING, NOT ESTABLISHED** — never a clean OK and never a
finding it cannot support, the same taxonomy the `running plugin`/`sandbox` rows already use
above. Once the floor is cleared, `task restarts` is a WARNING naming the task with the most
recorded starts, and `gate patterns` is a WARNING naming any gate that has run past the floor
and never failed — a candidate a human may want to stop paying for. Neither is ever a
FINDING: a repeated restart or a gate that keeps passing is advice, not proof that anything
is broken, and a run that exits 0 today still exits 0 with these rows present.

**That is why cleaning up is a different command.** `/audit:logs prune` removes rows from
`<logsDir>/plan-gate-events.jsonl` — the feed the plan gate writes and the panel's Plan gate
card shows — and it writes, so it is not a flag here. If a user asks to clean that file,
point them there rather than reaching for this command.

## The `gate economy` row, after `gate patterns`

`gate patterns` asks whether a gate ever fails; this row asks the question a never-failed gate
still owes an answer to — what it costs — and grades ONLY the gates `gate patterns` would
already call a candidate to drop, because a gate that has failed at least once earns its keep
whatever it costs. **With no `meta.gateBudgetMs` declared, this is an OK row saying so, never
silence**: the budget is opt-in, and a plan that never declared one has not been told its gates
are cheap — it has been told nothing. Past the floor `gate patterns` already needs, a gate whose
mean recorded cost exceeds the budget is named on a WARNING, never a FINDING, with the same
remedies every time: `/audit:phase retarget <phaseId> --gate-drop <entry>` for each phase not yet
signed off whose `testGate` still carries it, adding the entry to `meta.phaseGate.exclude` so the
next phase this plan mints does not inherit it, and — when the entry is also named in
`meta.phaseGate.always`, which outranks `exclude` — taking it out of `always` too, or the exclude
alone will not stick. It **never** grades an unmeasured step as cheap: a step that carried no
recorded `durationMs` is named on its own line rather than folded into the count that passed.
Like every row in this section, a WARNING here changes nothing about the exit code.

## The `shadow recall` row — whether the derived gate would have caught what actually failed

Read only when `meta.phaseGate.mode` is set. It computes two different recalls over every
shadow run recorded in the evidence ledger — never written anywhere, re-derived from the ledger
each time — asking Meta's own predictive-test-selection definitions: **test recall** is
suite-weighted (of every failing suite seen across every shadow run, what share did the derived
set list — `sum(listed) / sum(full)`); **change recall** is run-weighted (of every RED shadow run,
what share had at least one failing suite the derived set listed at all). The two disagree on
purpose — a history where every run caught at least one of several failing suites reads as a
perfect per-run share while the suite-weighted figure is lower, and only the second tells an
operator whether the derived set gives REAL coverage.

**No `meta.phaseGate.mode`** is an OK row saying so — nothing is derived, so there is nothing to
grade recall over. **A mode declared with no shadow run recorded yet** is also an OK row: "none
recorded" is the honest answer for a project that has not hit a real failure since deriving
began, not a gap in what this check could establish. **An unreadable ledger** is a WARNING naming
that it could not be read — never folded into "no shadow runs", because a torn row or a directory
this check cannot list is a different problem from a project with a clean trail. Past all three,
it is a WARNING carrying both percentages and the raw counts behind each, with one remedy
whatever the numbers say: set `meta.phaseGate.mode` to `"enforce"` once this recall is enough for
this project — nothing switches it for you, because no threshold here decides that judgement
call.

## The `full run` row — the third place, read off the ledger

Read only when `meta.fullGate` is declared. **No `meta.fullGate` is an OK row saying so**, the
same reading `shadow recall` gives its own opt-in switch: a plan that never declared a third
place has not been told it is missing one. Past that, it reuses `_evidence_io.full_status` —
the same function `/audit:status`, the report and the panel all read — rather than re-deriving
whether a merged phase is whole, so this row and those three surfaces can never disagree about
one phase.

Every merged phase is asked, whole or not: a **PROVISIONAL** phase draws a WARNING naming the
command that would settle it (`/audit:review <phaseId> --full`, or the pre-push hook, or CI);
an **UNKNOWN** phase draws a WARNING naming `full_status`'s own basis — no `mergedHead`
recorded, or ancestry itself could not be asked. A phase that failed a whole-bearing rule is
named with the rule it failed, in the identical sentence `full_status` composed for it — a
second wording of the same fact here would be a second implementation to keep in step with the
first. When every merged phase reads **WHOLE**, one OK row names the newest whole-bearing full
run and how long ago it ran.

**An unreadable ledger is a WARNING that says so and clears nothing**, exactly the `sandbox`/
`secret rules` class above. Advisory in every branch, like the rest of this section: a WARNING
here changes nothing about the exit code, and the release guard is the one place a PROVISIONAL
phase actually blocks anything.

## The `coupling` row — learned couplings that are gone, or no longer catching anything

`_doctor_trail.check_couplings` asks separate questions of `meta.coupling`, below, and never
folds them into one. **No `meta.coupling` is an OK row saying so.** A value that is not an array, or entries none
of which names a test, is a WARNING pointing at `validate-manifest.py`.

- **Is every coupled path still tracked?** One `git ls-files` over every test and source the
  entries name. A path git does not track, or one outside the repository, is a WARNING naming the
  entry and the path, with `audit-task.py uncouple --test <path>` as the fix. When git cannot be
  asked — no git root, or `git ls-files` unable to run or exiting non-zero — the row is a WARNING saying the tracking half
  was **not checked**, with the `git ls-files` command to run by hand; it never reads as every
  path tracked. When every path is tracked, it is an OK row.
- **Has any coupling stopped catching?** Asked only when `meta.fullGate` is declared — with none,
  no run can age a coupling and the row is OK saying so. Each entry is aged by counting the green
  measured full runs recorded after its `lastCaught`, or after its `learnedAt` when it was never
  caught (`_doctor_trail._measured_run_moments`) — a run with no tested head counts, since it
  still ran every coupled suite; only a full run does, so time with no full run ages nothing.
  **A run whose mute excused that coupling's test is not counted for it**
  (`_doctor_trail._muted_tests`, read off the row's own `muted` list and every step's): the row
  reads green because the mute hid the failure, not because the test passed, so counting it would
  read "failed every run" as "caught nothing". An entry at or past `UNCOUPLE_AFTER_FULL_RUNS` of
  them is a **CANDIDATE for uncouple**
  WARNING, with the constant printed as the basis and the `uncouple` command for each. An entry
  carrying neither stamp, or one that does not read as a moment, is a WARNING that it cannot be
  aged, with the `uncouple`-then-`couple` pair that learns it again — `audit-task.py couple
  --test <path> --sources <its sources> --basis-run <runId of a full run it failed in>
  --basis-head <sha that run examined> --phases <phase ids that run covered, if any>`, which
  carries `--basis-run` and `--basis-head`, the flags `couple` refuses to learn without
  (`_doctor_trail._relearn_fix`); `--phases` is optional. A ledger that cannot be read
  in full ages nothing and says so. Otherwise an OK row names how many couplings were aged over
  how many runs, and the oldest.

**Neither half removes anything.** Every `uncouple` it prints ends by saying it is never run for you:
dropping a coupling narrows the sign-off gate, and that is the operator's judgement, taken with
`audit-task.py uncouple`. Advisory like the rest of this section: a WARNING here changes nothing
about the exit code.

Do not modify anything. Related: `/audit:status`, `/audit:init`, `/audit:panel`,
`/audit:usage`, `/audit:layout`, `/audit:logs`, `/audit:review --full`.
