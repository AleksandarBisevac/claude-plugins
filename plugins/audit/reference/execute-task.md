# Execute the task — orchestrator reference

Read `reference/orchestrator.md` and `reference/manifest-conventions.md` first. This is the
one section every execution command that actually runs a task defers to — split out of
`orchestrator.md` so a command that never runs a task does not have to read it: `next`,
`phase` and `run` read this file too; `status`, `report`, `resume`, `worktree` and `layout` do
not need to.

## Execute the task

1. **Phase entry** (first started task of the phase, or after an interruption):
   a. Set `phase.status = "in_progress"` if it isn't already (Edit the phase's manifest file — the
      shard when sharded) — resume depends on this write.
   b. If `phase.baseRef` is null → `git rev-parse HEAD` (Bash), write it back.
   c. Create or switch to the phase branch per `reference/orchestrator.md`'s
      **Branch-per-phase** (including the development-branch verification — it applies on
      the `run` and `next` paths too).
   d. **Claim the phase** (sharded layout only): write `phase.claim = {sessionId, host, branch, at}`
      into the shard — optimistic cross-machine coordination, so a same-phase double-claim on another
      branch surfaces as a shard merge conflict. The FS phase-lock is the same-machine guard; the
      claim is the durable, pushed record for other machines. It is released at sign-off.
      `sessionId` is **`$CLAUDE_CODE_SESSION_ID`** — say which one, because a session has more than
      one name and the hooks see a different id in their payload. `meter-usage` accepts either, so
      spend still lands on the claimed phase; write this one so the record is consistent.
2. **Promote the task — through the script, not by hand:**
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" start <taskId>
   ```
   It sets `task.status = "in_progress"`, stamps `startedAt`, and does `task.attempts += 1` — in
   the phase's manifest file (the shard when sharded), under the lock, revalidated and journaled.
   **If the increment would take `attempts` past `maxAttempts` (default 3), it REFUSES rather than
   spawn** — that transition still owes an ADO echo and a human, neither of which the verb can
   supply — so on that refusal do NOT spawn: set `task.status = "blocked"` yourself and surface it
   to the human. A task entering `blocked` gets the **ADO echo** (`reference/orchestrator.md` → **ADO echo**).
3. **Spawn the plugin's executor agent** via the `Agent` tool —
   `subagent_type: "audit:audit-executor"`, `model = task.model`, and **`description` starting with
   the task id** (e.g. `"P3.2 shard writer"`). The id prefix is what makes token metering exact:
   every subagent gets its own transcript, and `meter-usage.py` reads the id back out of the
   spawn record — so three tasks running in parallel still get three separate token totals
   instead of collapsing to a phase average. It costs nothing and nothing breaks without it
   (spend just falls back to phase-level), so never let it block a run. Pass **only** the model;
   do **not** set reasoning effort — effort is pinned in each audit agent's own definition
   (`effort:` in its frontmatter), deliberately **decoupled from the calling session** so an
   audit's cost/latency is reproducible no matter what effort the invoking session runs at.
   (There is no per-spawn effort override anyway; the frontmatter is the only lever. On the
   general-purpose fallback below, effort cannot be pinned and reverts to the session's — an
   accepted degradation.) Its tool list is pinned (no web tools, no nested agents) and its
   system prompt carries the invariants; if that agent type is unavailable (older Claude
   Code), fall back to a general-purpose subagent and **paste `agents/audit-executor.md` into
   its prompt** rather than restating the rules below from memory. That file is the
   declaration of both the rules and the return shape, and restating it is how this path came
   to ask for no `testsAdded` — the field `task.verifiedBy` is filled from — while every rule
   beside it was faithfully copied. In the spawn prompt:
   - Tell it to **first invoke each resolved skill** via the `Skill` tool (load conventions before coding).
     Resolve them as **each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped, area
     first** — house conventions before task specifics, because a subagent that reads the specifics
     first has already made the decisions the conventions were meant to inform. With no registered
     area this is exactly `task.skills`, unchanged.
   - **Resolve `executor.runsGate` the same way — at spawn, by you, and stated in the prompt as a
     word rather than left for the subagent to look up.** Read `.claude/audit.config.json` (through
     `hooks/_config.load()` and `executor_gate_policy(cfg)`); absent config, or the key absent from
     it, is `own-tests`, the cheap default. Tell the subagent which reading it got: `never` (run
     nothing itself — the recorded run below is the only evidence this task gets), `own-tests` (run
     only the test(s) `task.tests.add` names, as its own quick check — `gate-only` tasks add none, so
     this is the same as `never` for them), or `full` (every command in `task.tests.gate`, unchanged
     from before this key existed). **An unrecognized value is refused, not folded into the
     default** — `executor_gate_policy` returns `None` for it; stop and ask the human rather than
     guessing which reading a typo meant. This changes only what the SUBAGENT does before it hands
     back — the recorded run two steps below is unconditional and is what becomes evidence either way.
   - Give it `task.description`, `task.files`, `task.docs`, the phase's `desiredOutcome` (so the work
     aims at the phase's stated goal), and the repo hard-rules (no token logging, no secret
     reads, plus any `meta`-level conventions). It must load project skills for domain rules.
   - **Test discipline by `task.tests.mode`:**
     - `tdd` → write a test asserting each item in `task.tests.add` that **FAILS on current code** first
       (run it, confirm red — proves the bug), THEN implement until green. (`tests.expectRedFirst` should be true.)
     - `regression` → implement the fix and add a test locking the corrected behavior (`task.tests.add`).
     - `gate-only` → no new test; only ensure `task.tests.gate` stays green.

     **Ask what happened to the PROOF, not only to the gate.** A gate verdict says the
     suite is green; it cannot say whether the new assertion was ever watched failing, and
     an assertion nobody has seen fail may be asserting nothing. So the outcome carries
     `redFirst` = `{status, basis}` beside the gates, in one of three words: `proved` (it
     was watched going red, and the basis is the command and its exit code),
     `could-not-prove` (the proof was attempted and something that is not the work refused
     it — typically the host's own permission classifier declining the edit that
     temporarily undoes the fix, which from outside looks like removing a test; the basis
     is that refusal **verbatim**), or `not-attempted` (none was owed, and the basis says
     why). `agents/audit-executor.md` states the rule for the executor and
     `schema/audit-plan.schema.json`'s `redFirst` block declares the words. **Nothing
     checks that a returned outcome carries the block** — `red_first_drift()` in
     `plugins/audit/scripts/_refs.py` holds only that every document naming a red-first
     proof offers the third word, and the `redFirst` enum refuses a fourth spelling only
     once one is written down and only under the `ajv` step CI and `tools/verify.sh` run;
     nothing under `scripts/` reads this vocabulary. So asking for the block is yours, and
     one that did not come back is recorded as absent rather than filled in.
   - **A reported verification carries the tree it was taken on.** Evidence names a command and
     an exit code; it does not say *which tree*, and a claim about a tree that has since moved
     reads exactly like one that is still true. That is one structure behind five separate
     failures in a single parallel run here — case counts quoted after the patch they described
     had landed on a different tree, a patch taken against a branch that had moved and silently
     reverting a sibling's work, a green gate still being cited after an edit landed. So tell the
     executor to stamp what it verified and hand the line back in `stamp`:

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/stamp-verification.py" take \
         --project <gitRoot> --manifest <manifestPath> --task <taskId>
     ```

     Resolve `${CLAUDE_PLUGIN_ROOT}` yourself and put the finished command in the spawn prompt —
     a subagent's prompt is not a hook command string, so the variable may reach it unsubstituted.
   - **It must run whichever reading of `executor.runsGate` you handed it** — the whole of
     `task.tests.gate` on `full` (through `run-test-gate.py`, which applies `meta.nodePreamble`
     itself), only its own added test(s) on `own-tests`, or nothing on `never` — and return **the
     shape `agents/audit-executor.md` declares** — `gates` per gate command it actually ran (`{}`
     on `never`), `outcome` = `{ technical, descriptive }`, `testsAdded` (the test names that
     become `task.verifiedBy`), `redFirst` (above) and `stamp` (the tree its claims are about). The
     brief holds the wording of each, including
     the pass/fail/could-not-run distinction the arms in step 4 turn on;
     `return_shape_drift()` in `plugins/audit/scripts/_refs.py` fails the build when this list
     falls behind the brief's, which is the only part of the return anything can check —
     **the return itself is prose, and nothing parses it**, so a field that did not come back
     is recorded as absent and never filled in.
   - **After the subagent returns, YOU run the task's gate through the script and record it:**

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" \
         <manifestPath> <phaseId> --task <taskId> --record
     ```

     The subagent's own run is what it develops against; **this** run is the one that becomes
     evidence. It has to be yours and not its, for the reason the script exists at all: the
     bracket, the check count, the coverage answer and the tree comparison are only true of a run
     the wrapper made. `--task` resolves that task's `tests.gate` when it declares one and falls
     back to the phase's otherwise, saying which — so a task with no gate of its own is never
     credited with having passed one.

     **Grade the returned `stamp` before you quote anything the return says.** A claim whose
     stamp is stale is **re-taken, never argued with** — and re-taking is cheap, because the
     comparison names which field moved rather than saying only "stale":

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/stamp-verification.py" compare \
         --project <gitRoot> --stamp "<the line the executor returned>"
     ```

     `current` exits 0, `stale` exits 1, and a tree git could not describe exits 3 — which is
     **not** "unchanged", and must not be read as one: a comparison that could not be made is
     the one answer that lets a wrong claim go on being cited. `head` moved means the branch
     moved under the work; `scopeDigest` moved means the declared files changed; `dirtyDigest`
     moved means some path's dirty status changed somewhere in the tree. **Nothing enforces that
     a return carries a stamp at all.** `return_shape_drift()` in
     `plugins/audit/scripts/_refs.py` holds only that this document asks for every field
     `agents/audit-executor.md` declares — it cannot see whether an executor filled one in, and
     the return is prose nothing parses. The command makes a stamp checkable once it is there;
     asking for it, and re-asking when it is absent, is yours.

     **When the return and the row disagree, that is a DISCREPANCY and not a correction.**
     A return calling every gate green, against a row whose `status` is anything but
     `passed`, used to be settled by silently preferring this run: the plan came out right and
     the disagreement was written down nowhere. Record both readings in
     `task.outcome.technical` — what the return claimed, what the row answered, and its
     `runId` — and take whichever arm the gates below ask for; the arm is unchanged, what
     changes is that the record says the claim was wrong once, and the retry bullet below is
     what carries that into the next attempt. **It is not a verdict on the executor**, and
     reading it as one is the way to get it wrong: the tree is shared, so a sibling landing
     between the two runs turns a green into a red honestly, and the row's
     `attributionBasis` — plus `could-not-run`, which is what the gate answers when the red
     is in files this task does not declare — is what separates that case from a false claim.
     Nothing compares the two for you: the return is prose and no script reads it, so a
     comparison you did not make reads afterwards exactly like one that agreed.

     **And the RECORD says which, not just the terminal.** The row carries `gateSource`,
     `task` or `phase`, beside the `steps` that ran. Read that and never `scope`: `scope` is the
     pointer subject — it is what decides whether the plan's `testEvidence` block lands on the
     task or on the phase — so on a fallback run it reads `phase` beside a `taskId`, and a
     reader taking it for provenance is reading a contract about where the pointer went. A row
     recorded before the field existed carries no `gateSource` at all, and that means *unknown*
     rather than either answer.

     **Every entry of a gate runs, in the order it is declared.** There is no short
     circuit: an entry that exits non-zero does not stop the ones after it, so `steps` is both
     what ran and the whole declared list — which is what lets `failed` be read against it and
     `ranTotal` be a total rather than a floor. Two consequences for how you compose a gate.
     Putting a cheap entry first buys a reader the earlier line and buys the wall clock nothing,
     so do not order entries expecting a saving. And a cheap entry never stands in for an
     expensive one: a typecheck asks whether the program still type-checks and a suite asks
     whether behaviour still holds, and a task that changes a validation decorator so every
     schema default begins taking effect can type-check impeccably. The entry that asks the
     behaviour question belongs in every gate that could pass.

     **Read the two lines it prints ABOVE the verdict block.** `evidence: recorded <runId>` is the row;
     `pointer:` is whether the plan now names it. A pointer can be **refused** — another live
     session may hold the phase lock — and that is a designed state, not an error: the run is
     recorded either way, and `--reconcile` catches the plan up later. Do not retry the gate to
     chase a refused pointer.
   - **Then ask the reviewer the intent question — one call per task, and only when the gate
     you just ran came back green.** A red gate already has its answer and the task goes back
     through step 2; there is nothing to bind a claim to yet. Spawn
     `subagent_type: "audit:audit-reviewer"`, `model = phase.review.model`, `description`
     starting with the task id, and **`mode: task`** in the prompt. Pass each of these, naming
     it, so the reviewer can report which input it did NOT get instead of assuming one:
     - the diff you are about to commit (`git diff -- <task.files>`), and `task.description`
       **verbatim** — what the task asked for, not your paraphrase of it;
     - the phase's `desiredOutcome`;
     - the executor's returned `outcome`, `technical` and `descriptive`, unedited. **This is
       the CLAIM, and it is the input sign-off cannot supply**: the phase diff has no way back
       to the task that produced each line, so a claim is bindable to its task only here;
     - its test evidence — the per-gate results it reported, `testsAdded`, and its `redFirst`
       word if it returned one. If it returned none, say that it returned none rather than
       leaving the input unmentioned.
     - the gate run you just recorded (`evidence: recorded <runId>`), so the reviewer reads
       your measurement instead of making a second one. Do **not** pass a review skill and do
       not ask it to invoke one — that is sign-off's call, and leaving it out is what keeps
       this one cheap;
     - the task's `tests.gate` **commands themselves**, resolved through `meta.buildCommands`
       where an entry is a `key:project` name. The run tells the reviewer the gate passed; the
       commands tell it which test files that gate selects, and that selection is the whole
       bound on the inherited-test question in `agents/audit-reviewer.md`. Hand it the phase's
       gate instead when the task declares none, saying which — an unbounded question is one
       the reviewer answers `not-asked`, which is the honest outcome and not a free one.

     It returns `intent.answer` — `matches` / `diverges` / `cannot-tell` — beside its ordinary
     `findings`, and the two are **routed apart** because they are different classes of
     problem: a finding names a file:line an executor can fix, a divergence names a
     disagreement between the diff, the description and the claim that only a human can
     settle. Read one as the other and one of them is lost.
     - `findings` → record them in `phase.review.findings` and handle them at sign-off the
       ordinary way (every actionable finding gets a NEW TASK there, created and started
       before any fix run — the file being declared or not is beside the point, since sign-off
       has no task running). Do not open
       a fix loop here; the per-task call is a check, not the review.
     - `matches` → **carried into the close below and nowhere else.** A gate proves the suite
       is green and says nothing about whether the green change is the change somebody wanted
       — so a `matches` answer that reached no field would read afterwards exactly like an
       answer nobody asked for, which is the failure this whole call exists against: an answer
       that is yes by default.
     - `diverges` → write it into `task.outcome.technical` so the commit carries it, and
       surface it as a **human action item**. Do not spawn a fix run from it: the wrong half
       may be the code, the description or the claim, and a fix run would edit code to match
       a description nobody checked.
     - `cannot-tell` → record it WITH the reviewer's `missing` list, and read it as neither of
       the other two. A missing input is a gap in what YOU passed — repair the spawn prompt,
       not the code.
     - `redFirst` of `not-proved` on a `tdd` task → a human action item too. A test seen only
       passing may assert nothing, and the task's own gate cannot tell you that.
     - `inheritedTests` of `flagged` → the entries are already in `findings` and route the
       ordinary way, so this word is not a second channel — it is what tells you a `findings`
       entry naming a file no task declares is a vacuous test rather than a bug. Read its
       `resolution` as a task that PROVES the test can fail: the reviewer judged it by reading
       and has no edit tools, so the red belongs to an executor that does. `not-asked` →
       record the word and its `inheritedTestsBasis` in `task.outcome.technical`. It is what a
       gate naming no test files earns, and a gap the record shows is worth more than a clean
       sheet the record invented.

     **`intent.answer` itself is carried forward to the close, whichever of the three words it
     was.** The call happens here, against the uncommitted diff; the close happens in step 4c,
     once the SHA exists — so pass the word straight through on the SAME `/audit:task done` call
     that already carries `--commit`, `--descriptive`, `--technical` and `--verified-by`:
     `--intent matches`, `--intent diverges` or `--intent cannot-tell`. That single write is what
     makes the answer NAME the diff it was given — `task.intentCheck.commit` becomes the same SHA
     `task.commit` carries, because both are written in the one call. **If the reviewer call
     produced nothing usable — it died, timed out, or returned no parseable `intent` — do not
     guess: omit `--intent` entirely.** An omitted flag and a recorded `diverges` are opposite
     facts, and a guessed `matches` filling the gap is exactly the failure this call exists to
     close.

     None of this blocks the commit and that is deliberate: `run-test-gate.py` is the one
     measurement that decides whether a task is done, and a cheap per-task reviewer that could
     hold up a commit would be a second gate with none of the first one's bracketing. Nothing
     enforces this routing either — no hook reads a subagent's return — so the run's own
     recorded outcome is the verdict either way.
   - **A widened scope CONTINUES the executor; it does not replace it.** When the plan gate refuses
     a file the task genuinely needs, you widen `task.files` (`/audit:task scope`) and then send the
     running executor a message telling it to carry on — you do **not** spawn a fresh one. A
     re-spawn throws away everything it has read and re-reads it: measured on a live run, five
     refusals out of twelve tasks were resolved by re-spawning at 60–150k tokens each, about a
     third of that phase's whole cost. The gate was right every time; the re-spawn was the waste.
   - **A message that hands a running executor a DIFFERENT task starts with that task's id** —
     the same convention as the `description` in step 3, one message later. A continued agent
     keeps the spawn record it was created with, so without the id every token it spends on the
     next task is billed to the one it was spawned for and the next task reads as free:
     `meter-usage.py` reads the id off the first line you wrote and moves the attribution from
     there on. Carrying on with the SAME task needs nothing — a message naming no task leaves
     attribution where the spawn description put it, which is coarse rather than wrong. It costs
     nothing and nothing breaks without it, so never let it hold up a hand-off.
   - **A retry is not a fresh start: when `task.attempts > 1`, the prompt carries what the
     last attempt already proved.** Nothing of one attempt reaches the next on its own, so an
     executor re-runs the gate to rediscover a red you have already recorded and then walks
     the same dead end. Read each of these back and put it in the prompt:
     - `task.outcome.technical` — where you wrote what the last attempt did and why you
       stopped it. It is the only place any of that is in prose.
     - `task.testEvidence` — `runId`, `status`, `at`. That is the WHOLE of what the plan
       caches (`_evidence_io.pointer_for`, deliberately nothing countable): it says a run
       happened and what word it got, and nothing else.
     - the gate's own output if this session printed it — `GATE RED: <entries>`, and the
       per-step `exit` and check-count lines above the banner. On a resumed session that
       output is gone, and the ledger row under `evidence.dir` keyed by that `runId` is
       where it still is.
     - `task.redFirst` when it is set, so a proof that could not be MADE is not walked into
       the same refusal twice.

     **What the gate records is the failing gate ENTRY, never the failing test.** `GATE RED`
     names entries, the row's `failed` list is those same names, and `_evidence_io.row_for()`
     assembles a row from named fields with no runner output crossing into it — so the test's
     name is nowhere on the record. If the last attempt named it, it is in `outcome.technical`
     and only there: quote it from there, and where it is not there say the record does not
     carry it rather than sending the retry to re-derive a red you already have.

     It does **not** carry the last attempt's diff. A red gate commits nothing and reverts
     nothing, so those edits are in the working tree the retry inherits: the tree is the
     attempt, and the brief is the record of what the attempt ANSWERED.

     **Nothing checks that a re-spawn carried any of this** — `attempts` is incremented in
     step 2 and no gate reads a prompt — so it is yours, and a retry briefed with nothing
     looks afterwards exactly like one briefed well.
   - The subagent does **not** commit — the orchestrator commits (step 4).
   - **The subagent must NEVER run `git stash`** (a stash in a shared working tree destroys sibling tasks' work).
     For baselines it should use `git diff`/`git show HEAD:<file>` instead. Put this in every subagent prompt.
   - **No usable return** (the subagent died, timed out, or came back with no parseable outcome / no
     file changes) is a **failure**, not a success — handle it exactly like a test failure in step 4
     (leave `in_progress`, do not commit; retry until `attempts >= maxAttempts`, then `blocked`).
4. On the subagent's return:
   - **success** (all gates green):
     a. **Risk gate first:** if `task.risk == "high"`, **stop and ask the human to confirm**
        (AskUserQuestion) before committing — always, no exceptions.

        **The answer may have been given before the run rather than during it, and then it is
        already an answer.** `/audit:phase <phaseId> --confirm-high-risk "<their words>"` runs
        `scripts/governance/record-risk-confirmation.py`, which prints **the task ids the answer
        covers** and writes them into a `risk.confirmed` journal row in the operator's own words.
        A task on that printed list is confirmed: commit it, and say in the run report that the
        confirmation was pre-given, naming the row. This is why the rule above still reads
        *always* — the asking happened, earlier.

        **A high-risk task that is not on the list stops and asks, and that includes one whose
        `risk` became `high` after the row was written** — retargeted, or added mid-run. The list
        is the task ids that existed and were high-risk **at the moment the human answered**,
        which is what makes it an answer rather than a rule: a confirmation covering whatever
        appears next has deleted the gate and left a flag where it used to be. The scope is
        bounded by `record-risk-confirmation.py`'s `covered_tasks()` — one phase, `risk: "high"`,
        open work only — so an answer given about one phase cannot discharge the gate in another,
        and the command refuses outright when the phase has no open high-risk task.

        **Nothing mechanically stops you committing a task the list does not name.** The script
        bounds what may be *claimed* and the row is what a reader checks the claim against
        afterwards (`audit-journal.py show --target <phaseId>`); obeying the list is yours, exactly
        as obeying the ask is. And there is no pre-given answer without a trail: with
        `journal.enabled` false, or an append that does not land, the command exits 1 saying the
        confirmation was NOT recorded — go back to asking per task.
     b. **Nothing to `Edit` at this letter — the close is one script call, made at the end of (c).**
        `task.status = "done"`, `completedAt`, `outcome` and `verifiedBy` are not written here by
        hand: writing them ahead of the commit is the sequence this letter used to prescribe, and
        it is exactly the hand edit `/audit:task done` (below, in (c)) exists to replace. Doing it
        here does not merely duplicate that later write — a task already `"done"` is terminal, so
        the call in (c) would refuse to close it again, over a task the gates just passed. (The
        **orchestrator**, not the subagent, supplies `outcome`.)
     c. **Commit the task's work — through the script, not by hand:**
        ```
        python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-task-work.py" \
            <manifestPath> <taskId> --project <projectDir> --subject "<short subject>"
        ```
        It stages the task's own `files`, the phase's manifest file, the journal and the evidence,
        commits them with an explicit pathspec, and **names any staged path outside that list
        instead of sweeping it in**. Read the exit code: **0** it committed (the SHA is printed) or
        there was nothing to commit and it said which; **1** git refused, or the index already held
        paths this commit may not carry, each one named — unstage them, or declare them with
        `/audit:task scope`; **2** the manifest will not load, or there is no such task.

        **Do not compose these git commands yourself.** This was the one git operation this
        document described in prose and nothing scripted, and prose cannot refuse: four scope
        breaches on one program came from widening two words of the paragraph that used to sit
        here — a file "obviously" part of the change, a sibling the editor had also touched, the
        shared index because the phase file was allowed. Every one of them is a commit nobody
        reviewed, made against the record everything else is graded by.

        What the script does for you, so you know what you are no longer responsible for: the
        `<gitRoot>/` prefix and any `:line-range` suffix are stripped; a declared path outside the
        git root, or one that is neither in the working tree nor tracked (the red-first case a
        task names before writing it), is **reported and passed over** rather than failing the
        commit; the manifest **index** is refused with a sentence of its own; and the staged list
        is read back after staging as well as before it. `verify-invariants.py`'s `commit-scope`
        re-derives the same allow-list from git afterwards, so these commits are graded by
        something that did not make them.

        The rest of this step is still yours:
        - **A widened scope cannot pair with `fileIndex` at this commit, and that is
          expected.** `task.files` lives in the shard you just staged; `fileIndex` lives in the index
          you may not. So a task whose scope you corrected mid-run commits a state where the two
          disagree — measured on live runs at 39 and 93 occurrences — and `manifest-revalidated`
          records those as **deferred** rather than as breaches. It then asks the pairing of the
          manifest **as it stands**, so the debt is real and is settled once: land the index change
          in its own commit before sign-off. `/audit:task scope` re-derives `fileIndex` for you.
        - **The journal and the evidence travel in this commit, and the script stages both** —
          `journal.dir` (default `<manifest dir>/journal`) and `evidence.dir` (default
          `<manifest dir>/evidence`), each only if it exists inside `<gitRoot>`, and each reported
          as skipped when it does not. The reason is worth knowing even though you no longer type
          it: the audit trail records the manifest writes this commit is carrying, and a record
          committed a week later cannot be checked against the change it describes; the rows this
          commit's `testEvidence` pointers name have to travel with the pointers, or a clone
          receives a plan referring to runs it does not have. `verify-invariants.py`'s
          `evidence-committed` is what says so afterwards. One file per writer per month, so
          parallel phases never conflict on either — one writer on two BRANCHES still can, and
          `audit-journal.py merge` is what resolves that without recomputing anything a row says.
        - **The explicit pathspec is the script's, and it is what makes the gate's
          `TREE CHANGED OUTSIDE THIS WORK` line affordable.** **The index does not arrive empty**:
          a previous task's `git mv` leaves paths staged, and a bare `git commit` sweeps every one
          of them into this task's commit — which is where two `commit-scope` breaches on one
          commit came from, and by the time `verify-invariants.py` reports them the only remedy
          is a rebase this document forbids. The script commits with `-- <the paths it staged>`
          and refuses outright when the index already holds something else, so neither half of
          that is yours to remember any more.
        - **Completion rows are hook-emitted.** The `journal-writes` hook derives `task.complete`,
          `task.commit` and `phase.signoff` rows from your manifest writes — whichever tool made them,
          a shell command inside a `Bash` call included — NEVER append those actions by hand (two
          writers means duplicate rows and a doctor that cannot trust the count).
        - **And re-`git add` anything `git mv` moved.** `git mv` stages the file at its **pre-edit**
          content, so a task that moves a file and then edits it commits the OLD bytes unless the new
          path is added again. **No gate can catch this**, and that is why it is called out here
          rather than left to one: `run-test-gate.py` measures the WORKING TREE, and this defect
          lives in the INDEX — the tests pass on the files you have while the commit carries files
          nobody ran. A live run came within one commit of shipping a shared module importing a
          feature while the manifest recorded the opposite.
        - The message is `<meta.commit.type>(<taskId>): audit - <your --subject>`, and
          `meta.commit.coauthor` is appended as its own paragraph when set — the script composes
          both. What is yours is the **subject**: say what the task did, in a few words.
        - **Write the subject to fit a commit linter's header cap, and hard-wrap the body** —
          this applies to every commit this run writes, the sign-off commit `reference/phase-signoff.md` describes included. The
          prefix plus `audit - ` already spends part of that budget before your words start, so
          the task's **title pasted in whole** is what pushes a subject over; write a short
          subject instead of restating the title, and wrap body lines rather than leaving one
          long line. Measured on a live run: the first task commit of a session was refused on
          header length, and an unwrapped body line was refused later in the same session. **The
          limits are the PROJECT's, not this plugin's** — the plugin adds no linter, reads no
          config for one, and cannot know whether the repository runs `commitlint` or anything
          else; what it ships is the template, which is why the guidance sits here. If the
          project's own rules are stricter than a short subject and a wrapped body, they win.
        - Take the SHA the script printed and write it into `task.commit` (`/audit:task done
          <taskId> --commit <sha>`, which writes it with the rest of the close in one write). The
          script deliberately does not: the SHA is only knowable after the commit it makes and the
          shard is inside that commit, so writing it there would need a second commit or the amend
          this document forbids. It leaves an `audit.task.committed` journal row in the meantime,
          so the gap between the commit and this write is not a commit nothing points at.
          **Do NOT write `bugs[]`.** A bug materialized into this task (`bug.taskId` ↔ `task.bugId`)
          reads as **fixed** automatically once the task is `done` — the rollup derives it (with
          `fixedIn` = this `task.commit`) — so the shared index stays untouched and parallel phases
          merge clean. (`/audit:bug close` still records a human `wontfix` / `not_a_bug` / `fixed`
          on the index, under the index lock — a structural decision, not part of a run.)
        - The `task.commit` write rides along with the next task's commit (or the sign-off commit) — do NOT amend.
     d. **ADO echo** — now that the SHA is captured, echo the done transition
        (`reference/orchestrator.md` → **ADO echo**; an `onComplete` comment carries this
        `task.commit`).
   - **a proof that could not be made** (the returned `redFirst.status` is
     `could-not-prove`) → **record it and carry on.** Copy the block onto `task.redFirst`
     before the commit in step 4c — the refusal in `basis` verbatim, the classifier's own
     words rather than your summary of them — so it lands with the work instead of in a
     session note. Then take whichever arm the gates ask for; this arm changes none of them.

     **It neither blocks nor retries, and both halves are decisions rather than
     omissions.** A retry spends an attempt on a re-spawn that meets the same classifier
     and is refused the same way, which is the same reason `could-not-run` costs no retry
     below; `attempts` is untouched here for the same reason. Blocking would stop a task
     whose deliverable is present — the fix is in, the assertion is in, and the gate
     ANSWERED — when what is missing is the weaker claim that the assertion can fail. And
     there is no human action item to raise, which is where this parts company with the
     infrastructure arm: a missing interpreter is fixed before the next run, while a host
     that refuses the edit refuses it again. So the record is the whole remedy, and
     **nothing grades it** — no gate reads `task.redFirst` today — which is exactly why the
     word and its verbatim basis have to be on the record rather than in your report.
   - **test failure** (gates RAN and are red) → leave `status = "in_progress"` (or `"blocked"` if attempts
     exhausted), put the reason in `task.outcome.technical`, and report it. Do not mark done, do not commit.
     A transition to `blocked` gets the **ADO echo** (`reference/orchestrator.md` → **ADO echo**).
   - **infrastructure failure** (gates could NOT run: missing command, runner crash before tests,
     zero tests collected where `tests.add` expects some) → this is NOT the task's failure:
     **revert the `attempts` increment from step 2** (Edit it back down), record the cause in
     `task.outcome.technical`, leave `status = "in_progress"`, and **STOP with a human action item**
     (fix `meta.buildCommands` / `tests.gate` first). Never burn retries on missing infrastructure.
5. Manual gate items (e.g. `"manual: <checklist>"`) cannot be auto-run — surface them as **human action items**.
