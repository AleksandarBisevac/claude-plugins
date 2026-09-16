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
   **`mode: phase`** — it invokes the
   skill itself and returns structured findings (it has no edit tools by design, and the diff stays out of YOUR
   context). The mode is what tells it there is no single task description or executor claim to bind
   here: the intent question was already asked per task, against each task's own description and its own
   executor's `outcome`, and this diff cannot say which task produced which line. What sign-off adds is the
   review skill over the whole phase. Record results in `phase.review.findings` — each one in the
   **finding shape** (`id`, `severity` from `low|med|high`, `file`, `issue`, `resolution`); the
   validator warns on a finding missing a field or carrying a severity outside that vocabulary,
   because a finding nothing can read back is a finding no later run can act on. Then, for each
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
2. **`testGateGreen`** — run the gate **through the script**, not by hand:
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" \
       <manifestPath> <phaseId> --record
   ```
   (the script applies `meta.nodePreamble` itself). All commands must pass **after** any
   review-driven changes. Tests are the final signer. Surface manual items as human action items.

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
   up. Everything it writes happens after the verdict is complete, so the recording can never
   appear in the tree comparison it is being judged by.

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
   how a real failure becomes an infrastructure excuse. And a step ended by a signal on **both**
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
   Exit 0 = no breach found · 1 = at least one · 2 = it could not be asked. It re-derives, from git
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
   a. Set `phase.status = "done"`, `phase.review.status = "passed"` (or `"skipped"`), write `phase.review.outcome`
      and `phase.summary` (short paragraph: what was done + impact; when `phase.desiredOutcome` is set,
      the summary must state how the phase met — or didn't meet — it). **Clear `phase.claim`** if set —
      the run is finishing, release the claim. (All these are shard writes in the sharded layout.)
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
      | 1 | a precondition failed or git refused | the output names the path or ref that has to change |

      **When the resolved parent is not the development branch, the sign-off report must say so** —
      name the branch the work merged into and state that it has NOT reached the development branch
      until that parent is itself merged. `resolve-branch.py … --phase <phaseId>` prints exactly
      that sentence; a report that stays quiet reads as "landed", which is the one thing it must
      not do.
   d. `close-phase.py` wrote `phase.mergedAt` — **into the copy of the plan that survives**, which
      is not always the one you are looking at: a phase that ran in a worktree merges into the
      parent's tree, and the worktree is removed moments later. The output names the file it wrote.
      Then **ADO echo** the phase: its PBI (when `phase.ado` is linked) moves to the done-state
      (`reference/orchestrator.md` → **ADO echo**).
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
      - A **dirty** worktree is never removed, because removal also destroys ignored files — a
        `.env`, a `node_modules` — that `git status` never mentioned.
