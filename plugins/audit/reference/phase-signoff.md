# Phase sign-off — orchestrator reference

Read `reference/orchestrator.md` and `reference/manifest-conventions.md` first. This is the
one section every execution command that signs a phase off defers to — split out of
`orchestrator.md` so a command that never reaches sign-off does not have to read it: `phase`
and `review` read this file too; `status`, `report`, `resume`, `next`, `run`, `worktree` and
`layout` do not need to.

## Phase sign-off (Definition of Done — strict order)

Run only when **all** tasks in the phase are `done`. All review/test work runs on the phase branch.

1. **`reviewResolved`** — compute the phase's changed files (union of `files` across its tasks, cross-checked with
   the manifest's top-level `fileIndex`). Resolve the review skill as
   **`phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`** — the first level that is
   **present** answers, an explicit `null` **is** an answer (skip review), and with several tags written
   order decides. (A monorepo reviews backend vs mobile phases with different reviewers by registering
   the area once instead of repeating `reviewSkill` on every phase.) `/audit:status` prints the resolved
   value and its basis; do not re-derive it from the file if the output is in front of you.
   **If the resolved review skill is set**, spawn the plugin's reviewer agent
   (`subagent_type: "audit:audit-reviewer"`, `model = phase.review.model`) with the diff scope
   (`git diff <phase.baseRef> -- <files>`), the phase's `desiredOutcome`, the resolved skill name, and
   **`mode: phase`**. The derived gate basis is a conditional input: hand `derive-phase-gate.py
   --brief`'s line and the runId only when `phase.testGateDerived` is already recorded — a
   re-review after a gate has run. This step runs before step 2a, so at a first sign-off nothing
   is recorded yet; hand nothing, and the reviewer reads the input as absent rather than assuming
   one. It invokes the
   skill itself and returns structured findings (it has no edit tools by design, and the diff stays out of YOUR
   context). The mode is what tells it there is no single task description or executor claim to bind
   here: the intent question was already asked per task, against each task's own description and its own
   executor's `outcome`, and this diff cannot say which task produced which line. What sign-off adds is the
   review skill over the whole phase. **Record the review's findings through the verb, all of
   them in one call:**

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" finding <phaseId> \
       --findings-file - <<'FINDINGS'
   [{"severity": "med", "file": "<path[:lines]>", "issue": "...", "resolution": "..."}]
   FINDINGS
   ```

   That is the reviewer's findings array as it came back, read verbatim off stdin, so backticks
   and quotes in a finding survive; a reviewer's own `id` is ignored. It appends each to
   `phase.review.findings` in the **finding shape** (`id`, `severity`, `file`, `issue`,
   `resolution`), allocating ids as `<phaseId>-R<n>`, in ONE write under the index lock with
   revalidate-or-roll-back, and journals one `review.finding` row per finding. A batch with one
   entry missing a field, or carrying a severity outside `low|med|high`, is refused whole
   before anything is written. The per-finding form — `--severity`, `--file`, `--issue`,
   `--resolution` in place of the file — records one finding per call. **Run those calls one
   at a time, never as parallel tool calls:** the lock now makes a second process of the same
   session wait for the first (only a child carrying the holder's token re-enters), but a
   caller holding the index lock BY HAND (`audit-lock.py acquire index`) lets its whole
   session back in, and parallel calls under that hold still overwrite each other. The batch
   form has no such hazard. A phase that has already landed (`mergedAt` set) is refused, naming
   `/audit:review`; a phase signed off and not yet landed takes the finding, and its output and
   journal row say which verdict it arrived after. When a finding's fix task lands, record it:
   `audit-task.py resolve-finding <findingId> --fix-task <taskId>` — the fix task must be
   `done`; its own recorded commit is written, `--commit <sha>` supplies one a done task did not
   record (and is refused when it contradicts one it has), and a task that is not done is
   refused whatever `--commit` says, because a fix that has not landed has no commit. Re-opening
   the fix task (`audit-task.py reopen`) takes that commit back off the finding. Every one of
   these writes, and `signoff`'s `--review-outcome`, ends `review.outcome` with a
   `[findings: …]` tally **derived** from the list, so never type a count into the outcome: a
   typed tally at its end is replaced. Its last clause counts only the findings whose fix task
   and commit `resolve-finding` recorded — a fix written into a resolution's prose by hand is
   not one of them, and the clause says nothing about it. A later typo in the outcome or the
   summary is `audit-task.py correct <phaseId> --review-outcome TEXT --summary TEXT`, which
   rewrites the text with a `review.correct` row and reads no `--verdict`.
   **Nothing refuses a hand edit of the shard** — the validator's shape warning is the only
   backstop, and a hand-written finding carries no journal row and no tally. Then, for each
   actionable finding, **create and start its task** (the two commands below) and spawn an
   `audit:audit-executor` fix run (`model = phase.review.model`) that may edit implementation AND tests; loop until
   clean or each remaining finding is explicitly triaged with a written justification. Fall back to a
   general-purpose subagent with the same rules if the agent type is unavailable. **If the resolved review skill is
   null**, skip this step — tests are the signer.

   **A finding gets a NEW TASK, and YOU create and start it before you spawn anything.**
   Not "a finding in a file no task declares" — every actionable finding. Sign-off happens when
   every task in the phase is `done`, and the plan gate opens a file only through a task that is
   **running**, so a fix run has nothing open to it whatever the `fileIndex` says. Two commands,
   run by you, in this order:

   ```
   /audit:task add "<the finding>" --phase <phaseId> --files <the files it touches>
   /audit:run <the id that add printed>
   ```

   `add` works while the phase is in sign-off; it lands `pending` and prints
   `ready now -- /audit:run <id>`. Run that, and the fix executor edits inside an open task.
   **`/audit:task scope` is not that route**, and it is where the old wording sent
   people. It no longer refuses a finished
   task — that refusal narrowed to `cancelled` alone,
   and a `done` task will take a widening — one that settles the `fileIndex` and deliberately
   records no new work: the task's `outcome` still describes the run that happened, so the finding
   would get no commit, no gate run and no evidence row of its own — and the task stays `done`,
   which is exactly the state the plan gate will not open a file for. The verb prints that
   reasoning itself when it accepts one, which is the line to read if you reach for it anyway.

   That order matters and it was measured: a live run spawned three fix-run subagents for findings
   in undeclared files, `require-plan` refused all three before an edit landed — correctly, the
   file was in no task's scope — and they had to be re-driven after the tasks were created by hand.
   **172,417 tokens.** The plan gate was doing its job; the sequence was wrong, and this paragraph
   is the sequence. The heading above used to carry that run's condition — *in a file NO task
   declares* — and a reader whose finding sat in a declared file read the whole route as somebody
   else's, reached for `scope`, and was refused on the second file of the fix. The condition was
   never the rule; the rule is that sign-off has no running task.

   And the reason it is a new task rather than a widened one: the fix is **new work**. It needs its
   own commit, its own gate run and its own evidence row. Widening a finished task would make it
   claim a file its recorded commit never staged, and its `outcome` describe a run that did not
   happen.
2a. **When `meta.phaseGate.mode` is set, derive before you gate.** Run this first, before the
   `run-test-gate.py --record` call below:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/derive-phase-gate.py" <manifestPath> <phaseId>
   ```
   Read the `DERIVED sign-off gate for <phaseId>: ...` line it prints (or the "could not be
   bounded" line, when no sibling task carries a path-scoped gate for it to repoint) before
   moving to step 2. This is what writes `phase.testGateDerived` and `phase.testGateBasis` —
   `run-test-gate.py` reads them, it never derives them itself.

2. **`testGateGreen`** — run the gate **through the script**, not by hand:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" \
       <manifestPath> <phaseId> --record
   ```
   (the script applies `meta.nodePreamble` itself). All commands must pass **after** any
   review-driven changes. Tests are the final signer. Surface manual items as human action items.

   **Route on the two lines a derived gate adds, after the verdict.** In `shadow` mode, over a
   run that measured a real failure, a `shadow: derived would have listed N of M failing
   suite(s)` line reports what the derived set would have caught — advisory, and it moves
   nothing: the wide gate just run is still the phase's whole answer. In `enforce` mode, a
   `NARROWED sign-off: this run measured the DERIVED gate (N of M listed checks; basis on
   phase.testGateBasis). It is evidence about this phase's own tests and their recorded
   couplings. meta.fullGate was not run here and is owed before <phase> is whole` line says
   the run you just took as evidence measured the narrower set and not the wide one, and names
   the third place — `meta.fullGate` — as what it still has not measured; read
   `phase.testGateBasis` for why the derived set narrowed the way it did. And when the derived step's own
   output did not name every suite `phase.testGateDerived` listed, the step reads
   `could-not-run` with a `DERIVED RUN NAMED k OF N LISTED SUITES: ...` basis: that run answered
   a narrower question than the phase recorded, so its exit code is not this run's verdict —
   re-derive and re-run, the same repair as any other `could-not-run`, never a retry on the task.
   **In exactly that case the NARROWED line itself changes, and it replaces the measured one
   rather than sitting beside it**: `NARROWED sign-off: the derived gate was declared for this
   phase, but this run did not name every listed suite, so it certifies nothing about that gate
   - see the GATE COULD NOT RUN line above for what it did not measure.` This run reached no
   verdict on the derived gate — read it as `could-not-run` exactly as the basis line above says,
   and fix the runner or the listing before signing off on it. The two NARROWED wordings are
   mutually exclusive per run: the measured one and this one never both print.

   **A red sign-off gate's fix is a NEW TASK, gated on what this run named as failing** — the
   same rule step 1 states for a review finding, and the same reason: sign-off has no running
   task open, so a fix cannot edit anywhere until one exists.
   ```
   /audit:task add "<the fix>" --phase <phaseId> --files <the files it touches> \
       --failing-from <runId>
   /audit:run <the id that add printed>
   ```
   `<runId>` is this run's own `evidence: recorded <runId>` line. `--failing-from` reads the row's
   steps for the suite(s) they NAMED as failing and narrows the new task's gate to them, unioned
   with whatever it also declares in `--tests-add` — see `commands/task.md` → *A failed-first fix
   task is gated on what the run named* for the refusals and the fall-through to the ordinary
   derivation when the row named no suite.

   **Why the gate is step 2 and not step 1 — it measures the phase ONCE.** A reviewer's findings
   become fix tasks, and a fix task's edits invalidate a gate taken before them: a gate run ahead
   of the review graded a tree that no longer exists by the time the phase is signed off, so it
   has to be run again. Review, then the fixes, then the gate measures this phase a single time;
   gating first measures it twice and signs off on the second measurement anyway. **Nothing
   measures whether you held the order.** A second phase-scope run simply supersedes the first in
   the evidence ledger — `_evidence_io.latest_by_subject` keeps the newest row per subject, and no
   reader counts the rows a phase left behind — so the order is held here or nowhere.

   `--record` writes the row, anchors it in the trail and points `phase.testEvidence` at it — the
   phase's own gate run, kept apart from its tasks' so a reader can follow either. As at task
   level, a **refused pointer is not a failure**: the row stands and `--reconcile` catches the plan
   up. It does not block sign-off either — step 5a grades the phase's NEWEST ledger row, not the
   pointer — but reconcile before signing off, so the plan's cache names the run that backs the
   verdict. Everything it writes happens after the verdict is complete, so the recording can never
   appear in the tree comparison it is being judged by.

   **A phase gate expected to outlast the Bash tool's foreground bound runs under
   `run_in_background`, and its verdict is read from the ledger, never from a truncated
   terminal.** The command is unchanged; `evidence: recorded <runId>` prints only once the row is
   already written, so the run has recorded before its own terminal is ever read again. Read the
   verdict back with `scripts/status/audit-lookup.py <manifestPath> run <runId>` (the id off that
   line) or `run latest --phase <phaseId>` — never by re-reading a background job's scrolled-past
   output — exactly as `reference/orchestrator.md`'s **Answering one question about the trail**
   describes.

   **`PHASE GATE RAN NO SUITE` and the `excluded:` line are what the phase's own gate has to say
   about `meta.phaseGate.exclude` before you read the verdict as coverage.** `excluded:` names the
   `meta.buildCommands` keys `meta.phaseGate.exclude` declares out of THIS run — only the ones this
   run actually did not execute, never the whole declared list — so a phase whose `testGate` still
   carries a since-excluded key is not told it skipped a suite it in fact ran. `PHASE GATE RAN NO
   SUITE` fires when none of the steps that DID run carry a recognised test runner's summary
   (`suiteReader`, read off the counts reader `summary_reader` already computes per step): a green
   verdict built entirely of lint and typecheck entries is not evidence that any behaviour was
   exercised, and this line is what says so before you sign off on it. Neither line moves the exit
   code. The remedy is the same one `/audit:doctor`'s gate-economy row prints for the same
   condition: `/audit:phase retarget <phaseId> --gate-drop <entry>` for a phase not yet signed off,
   or `meta.phaseGate.exclude`/taking the entry out of `meta.phaseGate.always` for the next phase
   this plan mints.

   **`SAME SUITE COUNTED ONCE` prints its own remedy line** — `/audit:phase retarget <phaseId>
   --gate-drop <name>` for the duplicate entry — when two or more gate entries reported the same
   check count over the same suite file(s): read it before signing off, because a duplicated entry costs
   wall clock and exposure to flakiness without adding assurance.

   **It brackets the gate, and that is why it is a script.** A gate is a MEASUREMENT.
   Exit 1 is not one answer, and the output says which: a command failed, the gate
   **changed the working tree**, **nothing actually ran**, a step **reached no verdict** (it
   never started, the OS ended it, or it was stopped at its bound), or a **stop signal** cut the
   run short before every step had reported. Each arm has its own banner and its own repair —
   **route on the banner, not on the exit code**, since the code is the same for every arm — and
   the ones that are not this work's failure are called out below. The tree-change and
   nothing-ran arms were both exit 0 before this existed — a `pre-commit run --all-files`
   gate on a docs task rewrote five backend
   files and reported `Passed` *because* `isort` and `black` are fix-in-place; narrowed to the
   task's own markdown files it then SKIPPED every hook on a Python-only config and the task
   went to `done` on a gate that verified nothing.

   **`NO OVERLAP WITH THIS WORK` is a REPORT, not a refusal.** The third way a gate
   says nothing, after doing too much and doing nothing: it ran, it passed, and none of the
   paths it printed is a file the phase's tasks declare. Measured live — a UI suite, two files,
   nine tests, all green, against a diff that was a one-value edit to a JSON manifest. The
   check count cannot see that, because the count was real. **Read the line before signing
   off** and decide whether this gate can grade this work; the exit code deliberately does not
   read it, because the overlap comes from paths a runner happens to print and a heuristic that
   refuses manufactures false refusals. Where the runner prints no paths the line says the
   question is not knowable from its output, which is not the same answer and is never spelled
   like it. `--task <taskId>` narrows the question to one task. The line NAMES a bounded sample
   of the paths the runner actually printed, which is what tells "these are my suites and
   none of them touched my files" apart from "these are `node_modules` stack frames and a config
   file" — two counts could not, and the line was reported firing on every gate run of one
   session because of it.

   **`GATE MUTATED THE TREE` refuses the commit step regardless of the gate's exit code.** Do
   not commit on that run: the gate rewrote a file the work under test DECLARES, so its own
   verdict is a claim about bytes it produced. Revert those files, then either use the read-only
   spelling of the check (`--check` not `--write`, `ruff check` not `ruff --fix`) or
   `/audit:phase retarget <phaseId> --gate <read-only entry>`.

   **`TREE CHANGED OUTSIDE THIS WORK` is a REPORT and moves the exit code not at all.**
   Paths moved in the window that the work under test does not declare. `git status --porcelain`
   describes the WHOLE repository, so a task you are running in parallel — this file tells you to
   do that whenever `files` are disjoint — puts its executor's writes inside every sibling's
   bracket. Porcelain reports *what* moved and never *who* moved it, so this line cannot separate
   that from a gate writing outside its own subject, and it refuses neither. **Read it before you
   commit**: check the paths against what else you have running, and stage by name.

   **What makes not-refusing affordable is `reference/execute-task.md`'s step 4c pathspec, and the two are one decision.**
   Before it, a gate that rewrote files outside its subject reached the commit through a bare
   `git commit` — a documentation task once came within one command of carrying
   +33/-62 of backend reformatting. Committing with an explicit pathspec means those paths cannot
   ride in whoever wrote them, so the remaining exposure is that they sit in the working tree
   unnoticed, and a line that names them is the answer to that. **Weaken either half and the other
   stops being enough**: refuse on the unattributable half and correct parallel runs halt again;
   drop the pathspec and a foreign rewrite is back in somebody's commit with only a printed line
   between it and the reader.

   **`GATE COULD NOT RUN` is not the task's failure.** A step reached no verdict — a
   missing command, a runner that died before its first test, a port it could not bind in a
   sandbox, or **the OS ending the runner** (an out-of-memory reaper, a crash inside it, a cgroup
   limit, another measurement on the host starving it of CPU). The first three exit non-zero having
   run ZERO checks; the last is reported by the kill itself, and the banner names which member it
   was underneath. **A red that measured NOTHING and named a file that was already dirty when the
   run started and that this work does not declare is the same answer one cause over** — a
   whole-program check fails on a sibling executor's half-written file whatever the work under
   test is, and the mutation bracket cannot see that file because it was already half-written
   before the first snapshot. Every clause is required and `run-test-gate.unattributable_failure`
   is what holds them: a gate that measured nothing stays **red** when the tree was clean (a task
   whose own test file does not compile collects nothing too), when the dirty file is one this
   work declares, and when no step's output blamed it — that last one because your own step 2
   leaves `attempts` and `status` uncommitted in the plan at every run, so ambient dirt proves
   nothing. The line under the banner names the file the run blamed. This is the "infrastructure failure"
   arm of `reference/execute-task.md`'s step 4c, now measured
   rather than judged: fix the runner and re-run, do **not** spend a retry on the task, and do
   **not** record it as a red suite. `GATE TIMED OUT` is the same shape one cause over — the step
   was stopped at its bound and reached no verdict, so read nothing about the work into it.

   **`RETRIED AFTER A SIGNAL` means the verdict under it is a SECOND attempt's, at a bound the
   first attempt did not have.** A step the OS ended reached no verdict, so the runner runs that
   step once more before answering — at a lowered worker bound where the command declares one it
   can read, and unchanged where it does not, and the line says which of those happened. **Read
   it as a different measurement, never as the first one confirmed**: the step's exit code, check
   count and duration all describe the attempt that answered, and nothing else on the row or in
   the output says an earlier attempt was ended and thrown away — which is why a green gate
   carrying this line is still a green gate, and still not the gate the plan declared. Put the
   line in `task.outcome.technical` when you report the run, because the recorded row keeps it
   (`steps[].retriedAfterSignal` and `steps[].retryBasis`) and your summary is where a reader
   meets it first.

   **Two things this never does, and the cases that hold them are in
   `plugins/audit/tests/test_run_test_gate.py` — run it with `--selftest`.** It never retries a
   step that exited non-zero **having printed its own end-of-run report**, whatever the exit code:
   a suite that reported has measured, and re-running a measurement until it comes back green is
   how a real failure becomes an infrastructure excuse. One report is the exception, and it is
   read narrowly: a jest run whose **every** failure is `Test suite failed to run` naming a worker
   terminated by a signal is jest reporting the kill, not a measurement of the suites that died -
   so it is retried like any other kill, at a halved `--maxWorkers` where the command declares
   one. One real assertion failure beside the kill keeps it a measurement, and no retry. And a step ended by a signal on **both**
   attempts is not a third attempt — it is a `GATE COULD NOT RUN` naming both attempts and both
   signals, which is the arm above: fix the host, spend no retry.

   **`NO CHECK RAN` is not green.** A gate that skipped everything and a gate that verified
   everything are the same exit code; only the count separates them. jest, vitest, mocha and
   pytest are read from their own summary lines, and only the words that mean a check EXECUTED
   are counted — a skipped test is exactly what this line exists to catch. Where the count is
   unknowable the script says so rather than filling it in, and `observations.countsBasis` on the
   recorded row says which steps were counted and which printed nothing it could read.

   **The count on `GATE GREEN` is the size of the GATE, not the sum of its runs, and two lines
   above it say when those differ.** `SAME SUITE COUNTED ONCE` means two entries printed the same
   count over the same suite files, so the total holds that count once — a duplicated command
   (the same runner with and without coverage is the reported shape) doubles the wall clock and
   the exposure to a flaky suite while adding no assurance. `SAME COUNT, SAME SUITE NOT
   ESTABLISHED` means a step named no suite file, so the two are ADDED and the total is an upper
   bound. **Neither is a refusal and neither moves the exit code** — they correct the number, and
   `run-test-gate.shared_counts` is what decides between them, with `sc3` and `sc5` pinning both
   directions. Report the line to the human with the verdict; do not spend a retry on it and do
   not edit `meta.buildCommands` on your own account, because which of two entries a project
   wants kept is not a question this run answers. **Every step's line now carries what that step
   cost**, so a doubled run is visible on a green gate without anyone deciding to measure it.

   **Three lines arrive around the verdict rather than in it, and each answers something an exit
   code cannot.** `covers:` prints before the table and says **what this gate never measures**:
   it runs commands, it opens no browser and starts no server, so a green verdict is evidence
   about those commands and about nothing that only happens at runtime. That boundary is
   reasonable and was unstated, and a green gate set read without it reads as broader coverage
   than was taken — when `meta.runtimeBoot` is set the line says so, and sign-off step 4 is what
   runs it. `machine:` and `claimed:` come after the run and are covered under
   `reference/orchestrator.md`'s **Parallel safety** note. And the **coverage answer that needs nothing from the run arrives before it**:
   a task declaring no files can be related to no run at all, which is knowable from the plan, so
   it is said before the first command instead of after a whole suite has been paid for. Nothing
   the gate does can change that answer; every other way the coverage question ends needs the
   run's own output and is still reported at the end.
3. **`invariantsChecked`** — run this **even when step 2 came back red**, and even though signing
   off will not follow. A red test gate is the loud failure and it is where a human's attention
   goes; it says nothing about whether this same run also pushed, force-updated or staged files
   `commit-scope` would refuse, and a governance breach sitting beside a failing suite is not
   excused by the suite failing. Skipping this step because step 2 already gave you something to
   report is how the quieter breach goes unlooked-at behind the louder one.
   Run it, from the project directory and **before** step 5c, because
   `close-phase.py` deletes the branch by default and that takes with it the reflog this reads.
   The ordering is not advice: it is why this step is numbered ahead of the landing step rather
   than beside it:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/verify-invariants.py" <manifestPath> <phaseId>
   ```
   Exit 0 = no breach found · 1 = at least one · 2 = it could not be asked. When the project keeps
   an `invariants-baseline.json` beside the manifest, a breach it holds is counted rather than
   printed and does not make exit 1; entries that no longer match are printed with a reason.
   `--write-baseline` is not a step of sign-off, and here it cannot run: it refuses (exit 2) while
   any phase it covers is in flight, because baselining a breach is accepting it, which is the human decision
   described below. The baseline is a human's commit on the development branch, outside any phase
   commit - a task, audit-state or manifest-index commit that staged it would breach its own scope.
   It re-derives, from git
   and the shard and the journal and the usage ledger, the rules **this file states** and nothing
   enforces: a task commit staged only its own `files`, its phase's manifest file and the journal;
   no push, no forced update and no `git stash` touched the phase branch; every manifest state the
   phase committed still validates; a `risk: "high"` task ran on neither a declared nor a metered
   `haiku`; and `phase.baseRef` is on the resolved parent branch.
   **A breach is a human decision, not an automatic stop.** Print the lines it printed — verbatim,
   because each carries the SHA or the file name that makes it checkable, and a paraphrase is a
   claim with its basis removed — and ask (AskUserQuestion) whether to sign off anyway: a commit
   that carried one extra file is often explicable, a push is not.
   Lines reading `no-basis` or `partial` are **not** failures. They name what could not be checked
   (a deleted branch, an unmetered repository, a manifest state no commit preserved); read them,
   do not block on them.
4. **`runtimeBootGreen`** — **only if `meta.runtimeBoot` is set** and the phase touched app source under
   `meta.runtimeBoot.appRootPath`. Cold-boot the app and verify the primary screen renders + one navigation
   away-and-back (jest mocks and tsc miss module-init/require-cycle boot crashes). Use the runtime steps in
   `meta.runtimeBoot`; if the runtime is unreachable, STOP and hand the human an explicit boot-check action item —
   the phase may NOT be signed off until the human confirms. If `meta.runtimeBoot` is null, skip this step.
5. Only if all applicable gates pass:
   a. **Record the sign-off through the verb, never by hand:**
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" signoff <phaseId> \
          --verdict passed|skipped --summary "<what was done + impact>" \
          [--review-outcome "<the review's one-line result>"] \
          [--no-evidence-reason "<why no gate run backs a passed verdict>"]
      ```
      **`--verdict passed` is refused unless step 2's run binds the phase's work** — the same
      rule a task commit is bound by (`_verdict_binding`): the phase's newest ledger row is
      `passed`, measured under the gate the phase declares now, over its declared files as they
      stand (the recorder's own writes left out), and a verdict the gate REPEATED is graded
      against the run it repeats; a phase whose gate declares no entry is bound to no run. The
      refusal names the run and the command that supplies one. Where no gate run can back the
      verdict, `--no-evidence-reason` is the operator's words, recorded verbatim on
      `review.noEvidenceReason` and shown where the evidence badge's basis goes — it is not a
      run, so `--fail-on no-test-evidence` still names the phase. `skipped` needs neither.
      The summary is a short paragraph: what was done and its impact, and when
      `phase.desiredOutcome` is set, how the phase met — or didn't meet — it. The verb writes
      `phase.review.status` (the verdict), `phase.review.outcome` and `phase.summary`, **clears
      `phase.claim`** (the run is finishing), and journals `phase.verdict`, under the index lock
      with revalidate-or-roll-back. A phase's status is derived
      (`_manifest_io.effective_phase_status`) and reads `done` once every task is terminal, the
      verdict is recorded and — for a phase with a branch — step c has stamped `mergedAt`; the
      verb then **stores** that derived status on the shard and the index stub, so a reader of the
      field alone (an older plugin's hooks, `jq`, an agent) is not left reading `in_progress`. A
      phase with no branch is `done` here; one with a branch stays `in_progress` until step c's
      stamp stores `done`. **Never write `phase.status` by hand**: a hand-written `done` is what
      used to be lost when a phase was worked on its parent branch and never merged, and
      `validate-manifest` warns about a stored status its derivation disagrees with, naming
      `audit-task.py settle`. (All shard writes in the sharded layout; the stub mirror and a
      settle write the index.)
   b. **Sign-off commit** on the phase branch (`<meta.commit.type>(<phaseId>): phase sign-off — …`, + coauthor;
      the subject and body rule is `reference/execute-task.md`'s step 4c, and a phase TITLE pasted in whole is what overruns it here).
      Stage the journal directory **and the evidence directory** here too, for the same reason as
      the task commits: the sign-off gate's own run was recorded a moment ago, and its row has to
      reach the same clone as the pointer that names it.
   c. **Land the phase — through the script, not by hand:**
      ```
      python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/close-phase.py" <manifestPath> <phaseId> \
          --project <projectDir>
      ```
      It merges into the phase's **resolved parent** (`phase.parentBranch ?? meta.developmentBranch`),
      writes `phase.mergedAt`, and performs whatever `meta.merge` asks for — steps c, d and e used
      to be three paragraphs of git here and are one call now. `--dry-run` prints the plan without
      writing. **Do not compose these git commands yourself**; three of them were wrong in this
      document for as long as it existed:

      - **`git switch <parent>` CANNOT RUN from a worktree.** `/audit:worktree` exists to run
        phases in linked worktrees, and inside one the parent is already checked out in the main
        tree: `fatal: '<parent>' is already used by worktree at '<path>'`, exit 128. The
        documented sign-off was unavailable on exactly the runs this file recommends. The script
        merges **in the worktree that already holds the parent**, or — when nothing holds it —
        fast-forwards without a checkout. It never moves your HEAD.
      - **`git branch -d` grades against HEAD, not against the parent.** Measured: it deleted a
        branch whose `parentBranch` was `develop` while the work had only reached `main`, exit 0.
        The script gates deletion on `git merge-base --is-ancestor <branch> <parent>` and never on
        git's own net.
      - **The two merge paths disagree about an already-landed phase.** `git merge --ff-only` says
        `Already up to date.` exit 0; `git fetch . <b>:<p>` says `! [rejected] (non-fast-forward)`
        exit 1 — byte-identical to a real divergence. The script asks the ancestry first, so an
        already-landed phase is never reported as a conflict.

      **Read the exit code, because three of them are not "it failed":**

      | exit | means | what to do |
      |---|---|---|
      | 0 | the parent contains the branch — merged now, or already did | continue to (d) |
      | 0 + `NOT MERGED` in the output | `meta.merge.auto` is **false** | the human merges; the phase is signed off and deliberately unlanded. Say so in the report and **do not** stamp `mergedAt` yourself |
      | 3 | **not a fast-forward** — the parent moved during the phase | ask the human (AskUserQuestion): `--no-ff` (recommended — preserves the branch history and keeps every `task.commit` SHA, and the `bug.fixedIn` derived from it, valid), or stop and leave it unmerged. **Never rebase**: that rewrites the SHAs the manifest records |
      | 4 | git could not be **asked** | report it; it is not a refusal, and retrying the same command will not help |
      | 1 | a precondition failed or git refused | the output names the path or ref that has to change. Two of these are the command itself: a branch that is its own parent (`--branch` or `phase.branch` naming the parent — nothing lands, and the cleanup would delete the parent), and a phase that records no branch whose composed name is not one — pass `--branch <name>`, and sign phases built on one combined branch off as a group (below). Or the phase's newest gate verdict no longer holds (`_verdict_binding.CLOSE_REFUSING_ARMS`, read at the branch tip and in the worktree holding the branch, the declared files as committed at the tip, whichever tree `--project` names; a group member is asked through its carrier's run and refused by a red on its own rows newer than that run; a sign-off recorded with `--no-evidence-reason` is refused only by a red recorded after it): the output names the run, and nothing was merged. The two ways out are a green run recorded on the work (`run-test-gate.py <manifestPath> <phaseId> --record`), or `--override-verdict "<why>"`, journaled as `audit.verdict.close-overridden` before the merge. A branch that has already landed is never refused on its verdict |

      **When the resolved parent is not the development branch, the sign-off report must say so** —
      name the branch the work merged into and state that it has NOT reached the development branch
      until that parent is itself merged. `resolve-branch.py … --phase <phaseId>` prints exactly
      that sentence; a report that stays quiet reads as "landed", which is the one thing it must
      not do.
   d. `close-phase.py` wrote `phase.mergedAt` — **into the copy of the plan that survives**, which
      is not always the one you are looking at: a phase that ran in a worktree merges into the
      parent's tree, and the worktree is removed moments later. The output names the file it wrote.
      The same write stores the phase's derived `done`, and the index stub is re-mirrored from the
      shard under the index lock; when the output says the stub was NOT re-mirrored (the lock was
      held), run `audit-task.py settle` once the holder is done rather than editing the index.
      Then **ADO echo** the phase: its PBI (when `phase.ado` is linked) moves to the done-state
      (`reference/orchestrator.md` → **ADO echo**).
      **When the output lists proposals parked on this branch**, they are the new work this phase
      branch deferred instead of minting phases on it (phases are minted on the development branch).
      They are materializable now that it has landed: relay the list to the user, and with their
      go-ahead run each printed `/audit:propose materialize <PROP-id>` ON THE PARENT BRANCH, commit
      that branch, and only then start the new phases. The list is read from the copy the merge
      landed in, so it is the parent's truth, not this branch's.

      **The same write also stamped `phase.mergedHead`** — the oldest commit on the parent's
      first-parent chain that contains the tip: the commit on that chain that brought the tip in -
      the tip itself for a fast-forward, the merge commit for a direct merge, the parent's merge of
      an intermediate branch for a nested one - and, when the phase records task commits, only
      if it contains every one of them. Right after this run's own merge
      that is the parent's head; for a branch merged by hand and closed later it is recovered from
      the parent's history — which is what lets the third
      place ask whether a later full run's own head contains this phase. A merge recorded before
      the field existed gets it on a re-run: the same recovered commit while the branch still
      resolves; once the branch is gone, the parent's head at that moment, written only when every
      task commit the phase records is contained in it, and marked with `phase.mergedHeadAt` - a
      parent that does not hold every recorded task commit (a rewound one, a squash merge, a wrong
      one lacking the work) gets no head.
      That head is stricter than the merge commit (a run containing the merge but not it reads
      provisional), and a full run counts as "after" it from `mergedHeadAt`, not `mergedAt`. Until such a run does, the phase reads `provisional`, and
      `/audit:status`, the report and the panel all say so in the same word; this repository's
      own release guard refuses a release while it does. With no `meta.fullGate` declared, none
      of this applies — no phase is ever provisional for a third place this plan never named.
   e. Cleanup is `meta.merge`'s to decide and the script's to do — `removeWorktree` and
      `deleteBranch`, both on by default. **It cleans up only what the plugin started and has
      finished with**, and the refusals below are the rule working rather than something to route
      around:
      - **A worktree the plugin did not create is never removed.** `/audit:worktree add` records
        that it made one; a worktree the human opened by hand carries no such record and is left
        alone, whatever its branch did. Say so in the sign-off report — the merge happened and the
        directory stayed, and a reader who is not told will go looking for a bug.
      - **A phase that has not settled is not cleaned up either** — sign-off passed, no task still
        open, the merge recorded. A branch can be contained in its parent while the phase is
        mid-flight.
      - A run **standing inside** the worktree it was asked to remove cannot finish its own
        cleanup (git would delete the caller's own directory, silently, exit 0); the output hands
        you the command to finish from the main tree.
      - A phase branch **checked out in the main worktree** lands, and the main tree is never
        removed or switched. The output prints the two commands that free the branch, to run
        there yourself: `git switch <parent>` (or `git switch --detach <parent>` when another
        worktree holds the parent, which leaves the main tree on a detached HEAD at the parent,
        and the output says so), then `git branch -d <branch>`. Under `--dry-run` the same
        commands are worded as what the cleanup will need once the merge lands.
      - A **dirty** worktree is never removed, because removal also destroys ignored files — a
        `.env`, a `node_modules` — that `git status` never mentioned.

### Signing off a group of phases built on one branch

Phases built on **one combined branch** record no `branch` and no `baseRef` of their own: step 1
has no `git diff <baseRef>` to review, and step 5c has no name to land (`close-phase.py` refuses
and asks for `--branch`). Sign them off together, through the same verb with the ids as a comma
list. Start with the plan — it writes nothing and prints the command each step below runs:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" signoff P1,P2 \
    --branch <combined-branch> --plan
```

It refuses, naming every reason, what the group cannot be signed off with: a member with open
work or already signed off, a member recording another branch, members resolving to different
parents, a `--branch` that is that parent, a finished task with no `commit`, a task commit the
branch does not carry (asked of git, not read off the plan; `repair-commits.py` re-points a task
whose commit a rebase moved), a commit the branch carries past its fork that nothing accounts
for, and a union no member's gate holds. The plan and the record ask the same planner, so what
the plan accepts the record re-checks under the lock.

**What the branch may carry.** Every commit in `git rev-list <fork>..<branch>` is a member task's
`commit`, an audit-state or index commit the journal records for a member, or a MERGE whose every
parent is one of those or lies on the parent side of the fork AND whose tree is exactly the
automatic merge of its parents (`git merge-tree --write-tree`). That last check is what makes a
merge accounted, and it has three answers. A merge whose tree differs — a conflict resolution,
an edit made inside the merge commit, or a change of one side it dropped — carries content no
parent does: it is refused by SHA, naming `git diff <recomputed tree> <sha>`, the comparison the
check made (`git show --cc` hides a path whose result equals one parent, which is exactly how a
dropped change looks). A merge the check could not recompute — an octopus merge, which
merge-tree takes two parents at a time for, or a git before 2.38, which has no `--write-tree` —
is refused as a question not asked, with git's own line, and never called an edit; its review
command is `git show -m <sha>`, a diff against each parent, which shows a dropped side on any git.
A merge above a refused one is judged now, as if the one below were accounted: if it recomputes
clean it is named as waiting on that one and is accounted once it is; if it carries content of
its own, or could not be asked, it is refused with its own reason in the same refusal. Any other
commit — a hand-made planning commit, a journal-only commit nobody recorded — is refused by SHA
too, and `--accept <sha> --reason "<why>"` takes any of these into the review instead; an
accepted commit counts as accounted for the merges above it. `--accept` takes a hex SHA or a
unique hex prefix of at least 4 digits, resolved (`git rev-parse --verify <sha>^{commit}`) to
exactly one commit on the branch and recorded in full; a ref or a revision expression, which
would re-resolve on every call, and an ambiguous or unknown prefix are refused by name. The
plan lists an accepted commit beside the task commits, the record writes it and the reason on
every member's `review.acceptedCommits`, and the report and the panel show it beside the
sign-off. A journal that cannot be read is said as that, never as a commit nobody records.
`--plan`, `--bind`, `--accept` and `--reason` belong to the group form alone: on one phase's
sign-off they are refused, naming it, with nothing written. Then, in this order:

1. **Bind** with `--bind` in place of `--plan`: each member gets the branch as `branch` and the
   point it left the parent (`git merge-base <parent> <branch>`) as `baseRef`, nothing of a
   verdict, and a `phase.bind` journal row. The record refuses a member that is not bound,
   because step 4 grades the base-ref and branch-history checks off those two fields and would
   otherwise not apply them.
2. **Review** from the commit list the plan prints — the tasks' commits and any accepted ones,
   with the files union — in place of `git diff <baseRef> -- <files>`. Findings become tasks
   exactly as in step 1, in the member whose files they touch.
3. **One gate run**: the plan names the member whose `testGate` holds the union of every member's
   gate, and prints its `run-test-gate.py … --also <the others> --record` call. `--also` makes the
   one run own the union of every member's files, so a rewrite of a file only another member
   declares reads `gate-mutated` rather than passing, the tree stamp covers all of them, and the
   run's ledger row names the members it owned (`groupWith`).
4. **One invariants run**: `verify-invariants.py <manifestPath> --all`, the one spelling that
   covers more than one phase — read the rows for the group's members. A breach is the human
   decision it is in step 3.
5. **Record** with the same command, `--verdict` and `--summary` in place of `--plan`. A `passed`
   verdict is step 5a's rule over the carrier's newest run and every member's files, and that
   run must have owned every other member (`groupWith`) — or `--no-evidence-reason "<why>"`,
   recorded on every member's review. Every member is written in one write, all or nothing, and
   each non-carrier member takes the carrier's run as its `testEvidence` with
   `gradedBy: <carrier>`, journaled as a `phase.testEvidence` row. The report and the panel render
   that pointer as the carrier's run ("graded by P1's run …"), never as the member's own, and
   `--fail-on no-test-evidence` reads it as the member's evidence. A copied pointer is the one
   pointer no run records for its subject, so `--reconcile` does not restore it.
6. **Commit** the sign-off with the lines the record prints — in the sharded layout one
   `commit-audit-state.py` per member and then `commit-manifest-index.py`, because one commit
   carrying two members' shards reads as a scope breach for each; in the single-file layout one
   `commit-audit-state.py`, because there is one file.
7. **Land each phase** with the `close-phase.py --branch` lines, in order. The first merges the
   whole branch and keeps it (`--keep-worktree --keep-branch`); each later one finds it already
   contained and stamps its own `mergedAt`; only the last may take the branch and its worktree
   away.
