# Execute the task — orchestrator reference

**No pipeline command reads this file first, and the main loop does not perform these steps
by hand any more.** The step driver, `scripts/governance/drive-phase.py`, performs every step
below that needs no judgement - the start, the computed brief, the recorded gate, the stamp
grade, the commit and the close - as the existing verbs, in this order, and prints the rule a
step needs at that step; the agents file their returns through `drive-phase.py submit`.
`tools/measure-context.py --gate` holds that no pipeline command reads a reference file first.
This file is the reference for what each step does and why, for the guide agent and for a
reader who asks: where it says "you", read the step the driver runs. What each `/audit:task`
verb writes and refuses, and what the run commands leave behind, is
`reference/verbs-in-full.md`.

## Execute the task

1. a. **Phase entry** (first started task of the phase, or after an interruption) is the verb's in
   step 2: `audit-task start` sets `phase.status`, and on the sharded layout writes
   `phase.claim`, in the same write as the task. **On a claim refusal, relay it the way
   `reference/manifest-conventions.md` → *The operator's words go in unchanged* states** — it
   refuses only while another session's claim may still be live or unaskable.
   b.–c. **The branch and `phase.baseRef` are the verb's in step 2.** `audit-task start` cuts
      the phase branch from its resolved parent on the phase's first task (or records the one
      `/audit:worktree add` checked out), writes `baseRef`, and refuses — naming why — when HEAD
      is anywhere else; see `reference/orchestrator.md`'s **Phase entry**. Do not cut or switch
      the branch by hand first: on a refusal, stop and ask the human.
2. **Promote the task — through the script, not by hand:**
   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" start <taskId>
   ```
   **On a readiness refusal, relay it the same way** (`reference/manifest-conventions.md` →
   *The operator's words go in unchanged*). It sets `task.status = "in_progress"`, stamps
   `startedAt`, and does `task.attempts += 1` — in
   the phase's manifest file (the shard when sharded), under the lock, revalidated and journaled.
   **If the increment would take `attempts` past `maxAttempts` (default 3), it REFUSES rather than
   spawn** — that transition still owes an ADO echo and a human, neither of which the verb can
   supply — so on that refusal do NOT spawn: set the task blocked through the verb,
   `audit-task.py block <taskId> --reason "<attempts exhausted: the last red gate's reason>"`,
   and surface it to the human. The verb writes `status` and `blockedReason` with a `task.block`
   row; nothing refuses a hand edit of the status, but only the verb records why. A task entering
   `blocked` gets the **ADO echo** (`reference/orchestrator.md` → **ADO echo**), which the verb
   does not send.
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
   - **The brief is computed, and the executor is handed its path.**
     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-lookup.py" <manifestPath> brief <taskId> --role executor
     ```
     writes the whole brief to a file under `stateDir` and prints one line naming it; the spawn
     prompt is that path and the task id. The bullets below are what the script puts in it —
     read them as its specification, not as text to compose: the resolved skills, the
     description verbatim, the files with their last declarer, the docs, the desired outcome,
     the gate resolved, the `executor.runsGate` reading with its command, the stamp and red-first
     helpers resolved against this plugin copy, the filing command, and the retry context when
     `attempts > 1`. A brief typed by hand instead is checked by nothing; the computed one is
     held by `audit-lookup.py`'s cases in `plugins/audit/tests/test_audit_lookup.py`.
   - Tell it to **first invoke each resolved skill** via the `Skill` tool (load conventions before coding).
     Resolve them as **each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped, area
     first** — house conventions before task specifics, because a subagent that reads the specifics
     first has already made the decisions the conventions were meant to inform. With no registered
     area this is exactly `task.skills`, unchanged.
   - Give it `task.description`, `task.files`, `task.docs`, the phase's `desiredOutcome` (so the work
     aims at the phase's stated goal), and the repo hard-rules (no token logging, no secret
     reads, plus any `meta`-level conventions). It must load project skills for domain rules.
   - **Alongside `task.files`, run the one question an executor would otherwise grep the manifest
     or the journal for, and paste the answer in — never the command.**
     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-lookup.py" <manifestPath> brief <taskId>
     ```
     This folds `fileIndex` over the task's own `files`, one call, and answers which task last
     declared each of them. It is context the plan already carries, so an executor that has it
     has no need to search the tree for it — which is what turns exploring from this agent's
     default first move into a deliberate step it justifies in its own outcome when it does reach
     for one. A task with no declared files yet gets an empty answer, which is itself worth
     pasting in rather than silently skipping the step: it tells the executor the plan has nothing
     to say about its files, not that you forgot to ask. Its last line,
     `executor.runsGate: <word> (<basis>)`, is the reading the executor runs — paste it with the
     rest; with `own-tests`, also hand it the command the *What you run* section of
     `audit-lookup.py brief <taskId> --role executor` prints. That section chooses between
     `run-test-gate.py ... --own --quiet` and a command that can run when `--own` would find
     nothing of the task's own; pass on what it printed, and do not write the `--own` line
     yourself.
     When `brief` exits non-zero and names the config instead, the value is unrecognised or the
     file does not parse: stop and ask the human — `audit-lookup.py` refuses to print a default
     there, and you must not supply one.
   - **Test discipline by `task.tests.mode`:**
     - `tdd` → write a test asserting each item in `task.tests.add` that **FAILS on current code** first
       (run it, confirm red — proves the bug), THEN implement until green. (`tests.expectRedFirst` should be true.)
     - `regression` → implement the fix and add a test locking the corrected behavior (`task.tests.add`).
     - `gate-only` → no new test; only ensure `task.tests.gate` stays green.

     **Ask what happened to the PROOF, not only to the gate.** A gate verdict says the
     suite is green; it cannot say whether the new assertion was ever watched failing, and
     an assertion nobody has seen fail may be asserting nothing. So the outcome carries
     `redFirst` = `{status, basis, at}` beside the gates, in one of three words: `proved` (it
     was watched going red — at least one test collected and an assertion failing — and the
     basis is the command, its exit code and the tally), `could-not-prove` (the proof was
     attempted and something that is not the work refused it, or the run reached no
     assertion: a compile error, an import error or zero tests collected is not a red
     unless the task introduces the symbol the run fails on; a refusal goes in the basis
     **verbatim**), or `not-attempted` (none was owed, and the basis says why).
     `agents/audit-executor.md` states the rule for the executor and
     `schema/audit-plan.schema.json`'s `redFirst` block declares the words.

     **A red proved after the fix is in runs in a throwaway tree, never in the shared one.**
     Put the resolved helper in the spawn prompt beside the stamp command below:

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/stamp-verification.py" red \
         --project <gitRoot> --manifest <manifestPath> --task <taskId> -- <test command>
     ```

     It checks HEAD out with `git worktree add --detach` into a temp directory, copies the
     task's declared test files from the working tree over it, runs the command there,
     removes the throwaway in a `finally` and reports whether the removal held, and prints
     the `redFirst` block, naming the failing case it rests on — which must be one of the
     task's own. A red counts only against a GREEN baseline: HEAD's own test files, run FIRST
     with the same command on HEAD's code and every declared test file new at HEAD laid
     over as an empty file (a jest or vitest one is left absent instead), must be green —
     exit 0 with no failure, or an exit 5 whose one runner's tally counts nothing run and
     nothing failed, or, for a file left absent, the runner's own no-test-file sentence
     with no case or failure counted (step 1 of the `stamp-verification.py` section of
     `PLUGIN-BUILD-GUIDE.md` is the full rule) — and the fix run (the task's
     test files on the working tree's code) must turn every failure green. A failure is
     the task's own, a new case or an edited one, only where the runner locates it in a
     declared test file (a pytest node id's path, unittest `-v`'s module matched by its
     trailing components, or a run of exactly one declared file), the class the runner
     names there defines it (its last real binding there, read by ast, and not replaced
     later by an assignment to `<class>.<case>` or a `setattr` naming it literally; any
     other attribute or subscript assignment binds nothing), and no test file anywhere in
     HEAD's tree holds an ast-identical def under the same class chain and name; a house
     run's one script is
     compared whole, and a script identical to one of HEAD's test files is refused. So a
     HEAD case the task's file imports, inherits or loads, a moved file's case and a copied
     case are not credited unless the task edited the definition (under a house run, the
     script), and a runner that locates no
     failure is `could-not-prove`. Every run has a
     fresh home and temp directory of its own. A command
     already red at HEAD is `could-not-prove`: narrow the command to the task's cases.
     `--case` narrows to the ids or labels it names, held to that same test: it must name a
     case that failed an assertion in the task's run. Its
     `--introduces <symbol>` is where "the task introduces the symbol" is decided: an
     identifier absent from HEAD's copy of every declared implementation file and present
     in the working tree's, a final import/attribute/name error naming it, and a second run
     with the working tree's implementation copied in that loses that error and reaches its
     assertions. The throwaway holds tracked files only and runs with a scrubbed
     environment; `--deps-from <dir>` (`--project` by default) links in its ignored
     dependency directories (`node_modules` at any depth, `.venv`) entry by entry, named
     on the output's `dependencies:` line. Its leaks are named, not closed: a link landing
     in the shared tree outside every dependency directory (a workspace package, an
     editable install) is found by `workspace_links()`, the directory holding it is
     skipped and named on the `dependencies:` line, and the run goes ahead without it;
     a runner's write into a linked entry lands in the
     source checkout unwatched; the user's `~/.npmrc` and an untracked project one never
     reach the fresh home. Any other untracked dependency still comes back
     `could-not-prove`. The runners whose tally the helper reads are `house`, `pytest`,
     `unittest`, `jest` and `vitest`. The output decides rather than the command, so a
     wrapper counts when the runner it wraps prints its own tally, and a run printing
     none of theirs is `could-not-prove` whatever was linked in. `runner_list_drift()`
     in `plugins/audit/scripts/_refs.py` reads that list off `TALLY_READERS` and fails
     the build when this sentence or the executor's drifts from it. The executor used to be
     told to undo its fix in the shared tree for the length of the run, which is a write
     over ground siblings are editing; a host refused it beside a sibling's uncommitted
     work. Nothing stops an executor overwriting a file anyway — the plan gate grades which
     files it touches, not why — so asking for the helper is yours.

     **One vocabulary, checked.** The schema enum is the one source: the executor's return
     offers exactly its words, and the reviewer's offers those plus its declared
     reviewer-only `not-proved` — `red_first_vocabulary_drift()` in
     `plugins/audit/scripts/_refs.py` fails the build otherwise, and `red_first_drift()`
     beside it holds that every document naming a red-first proof offers the third word.
     **A FILED return carries the block, and the filing verb is what checks it**:
     `audit-task.py file-return` refuses an executor return whose `redFirst` is missing, has
     no basis, or holds a word outside the schema enum, writing nothing. A return the
     executor handed back without filing is checked by nothing — the `redFirst` enum refuses
     a fourth spelling only once one is written down and only under the `ajv` step CI and
     `tools/verify.sh` run — so asking for the filing is yours, and a block that did not
     come back is recorded as absent rather than filled in.
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

     Resolve `${CLAUDE_PLUGIN_ROOT}` yourself, per spawn, from the copy THIS SESSION is running —
     a subagent's prompt is not a hook command string, so the variable may reach it unsubstituted —
     and put the finished command in the spawn prompt. Re-resolve it if the plugin updates mid-run
     rather than reusing a root a brief resolved before the update, and say in the run's output that
     you re-resolved and why; `reference/orchestrator.md`'s non-negotiable guardrails say where a
     session still spawning from the old copy would show up.
   - **It must run whichever reading of `executor.runsGate` you handed it** — the whole of
     `task.tests.gate` on `full` (through `run-test-gate.py`, which applies `meta.nodePreamble`
     itself), only its own added test(s) on `own-tests`, or nothing on `never` — and return **the
     shape `agents/audit-executor.md` declares** — `gates` per gate command it actually ran (`{}`
     on `never`), `outcome` = `{ technical, descriptive }`, `testsAdded` (the test names that
     become `task.verifiedBy`), `redFirst` (above), `stamp` (the tree its claims are about) and,
     when a skill asked for one, `claims`. The
     brief holds the wording of each, including
     the pass/fail/could-not-run distinction the arms in step 4 turn on;
     `return_shape_drift()` in `plugins/audit/scripts/_refs.py` fails the build when this list
     falls behind the brief's. **The executor files that object through `drive-phase.py
     submit <taskId> --role executor`** (the object on stdin, the test command after `--` on a
     `tdd` task): `submit` checks the shape and writes nothing when a field is missing, runs
     the red-first helper, takes the stamp after it, and hands the object to `audit-task.py
     file-return`. `file-return` checks the shape again - it exits 2 naming a missing field and
     writes nothing - and writes a well-formed return once, to a path it derives from the task
     and its current start. The agent hands back the one line `submit` printed.
     **A return handed back without filing is prose, and nothing parses it**, so a field
     that did not come back is recorded as absent and never filled in.
   - **After the subagent returns, YOU run the task's gate through the script and record it:**

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/run-test-gate.py" \
         <manifestPath> <phaseId> --task <taskId> --record
     ```

     The subagent's own run is what it develops against; **this** run is the one that becomes
     evidence. It has to be yours and not its, for the reason the script exists at all: the
     bracket, the check count, the coverage answer and the tree comparison are only true of a run
     the wrapper made. `--task` resolves that task's `tests.gate` when it declares one and falls
     back to the phase's otherwise, saying which — the preamble names the task and the phase, and
     a `graded by:` line sits under the `GATE …` banner — so a task with no gate of its own is never
     credited with having passed one. **A gate cleared on purpose is not "no gate":** a task whose
     `tests.gateBasis` is `cleared` (what `--gate-clear` writes) resolves EMPTY at task scope and
     the script says so and exits 0 without running anything - and under `--record` it writes an
     `empty-gate` row and pointer, so the done task carries evidence of that answer rather than
     tripping `--fail-on no-test-evidence`. The phase's `testGate` at sign-off is what still
     grades it, and where that is EMPTY too the line says review alone. Under `--task` the coverage lines also carry one `breadth:` clause
     when the run named suites the task neither declares nor is named after — both counts, never
     a refusal.

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
     moved means some path's dirty status changed somewhere in the tree; `content` moved means
     the bytes git reports changed, which includes the case none of the other three fields can
     see: a rewrite of an already-dirty file the task does not declare, which in a shared tree
     is a sibling's in-flight edit. A moved `content` names the path(s) that moved on a
     `moved:` line when both stamps kept their per-path list. That list is bounded
     (`_tree_stamp.DIRTY_PATHS_LIMIT`), and over the bound the line says the path cannot be
     named rather than naming some. The paths this plugin's own recorder writes
     (`_evidence_io.recorded_paths`, derived again from the manifest the stamp stores) are left
     out of `content`, so your manifest and journal writes between take and compare do not stale
     a stamp. A version-1 stamp carries no `content` field: it is graded on the other three and
     the comparison says that a rewrite of an undeclared dirty file was not compared. Every field
     prints its own limit (`says:`) beside it. **A filed return carries a stamp, because
     `file-return` refuses one without it**; a return handed back without filing is checked
     by nothing. `return_shape_drift()` in
     `plugins/audit/scripts/_refs.py` holds only that this document asks for every field
     `agents/audit-executor.md` declares — it cannot see whether an executor filled one in. The
     command makes a stamp checkable once it is there; asking for the filing, and re-asking when
     it is absent, is yours.

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

     **A gate expected to outlast the Bash tool's foreground bound runs under
     `run_in_background`, and its verdict is read from the ledger, never from a truncated
     terminal.** The command above is unchanged; what changes is that you do not wait on its own
     terminal to scroll to the end. `evidence: recorded <runId>` is written **before** the banner
     prints, so the row is durable the moment the background job has one to show — read it back
     with `scripts/status/audit-lookup.py <manifestPath> run <runId>` (the id off that line) or
     `run latest --task <taskId>` when the id was not kept, exactly as
     `reference/orchestrator.md`'s **Answering one question about the trail** describes.
   - **Which task gets a reviewer of its own is `review.perTask`'s answer, read by the driver's
     `reviewer_due` and nowhere else.** Under `phase` - the shipped default - no per-task
     reviewer runs at all: the close records `intentCheck.answer = "deferred"` itself, refuses
     every `--intent` word (a recorded fix task's `not-asked` excepted), and the phase review
     answers each task at sign-off, which refuses until it has. Under `signals` a reviewer runs
     only where a computed signal fires - a red-first proof that is not `proved`, or a return
     whose gates disagree with the recorded green - and a task with neither closes `not-asked`
     with the signals as its basis. Under `always`, every task gets the call below.
   - **Where it is due, ask the reviewer the intent question — one call per task, and only when
     the gate you just ran came back green.** A red gate already has its answer and the task goes
     back through step 2; there is nothing to bind a claim to yet. Spawn
     `subagent_type: "audit:audit-reviewer"`, `model = phase.review.model`, `description`
     starting with the task id, and **`mode: task`** in the prompt. **Its brief is computed
     too** —
     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-lookup.py" <manifestPath> brief <taskId> --role reviewer
     ```
     — and the reviewer is handed its path. It carries the executor's return byte-identical
     as filed, so it is REFUSED (exit 4, no brief written) while that return is not filed for
     the task's current start: a reviewer cannot be briefed before the claim it checks exists.
     The brief holds each of these, naming it, so the reviewer can report which input it did
     NOT get instead of assuming one:
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

     **`intent.answer` itself reaches the close through the reviewer's FILED return, whichever
     of the three words it was.** The reviewer files its return with `drive-phase.py submit
     <taskId> --role reviewer`, which hands it to `audit-task.py file-return` — its one write —
     and the close in
     step 4c reads it: `/audit:task done <taskId> --commit <sha> --from-return` takes the
     outcome, `verifiedBy` and the red-first block from the executor's filed return and the
     intent answer from the reviewer's, in one write. That single write is what makes the
     answer NAME the diff it was given — `task.intentCheck.commit` becomes the same SHA
     `task.commit` carries. **Under `always` and `signals`, `done` enforces this on every form
     that passes `--commit`**, in `_locked_done`: with no reviewer return filed for the task's
     current start it refuses,
     writing nothing, unless the close says the question was deliberately not put —
     `--intent not-asked --intent-basis "<why>"`; and a typed `--intent` word that differs from
     the filed answer is refused, `not-asked` included. **If the reviewer call produced nothing
     usable — it died, timed out, or filed nothing — do not guess and do not type its word:**
     a guessed `matches` filling the gap is exactly the failure this call exists to close, so
     re-spawn the reviewer, or close `not-asked` with the basis that it did not answer. A
     `--no-change` close has no diff to bind and keeps its rule: `--intent` is optional there,
     and `not-asked` still needs its basis. Sign-off lists every done task with NO answer, which
     a deliberate `not-asked` is not.

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
   - **One task per agent is the default shape, and continuing across the bullet above is a
     bounded exception to it, not a standing preference.** Below `executor.maxHours` (default 3
     when the key is absent — `hooks/_config.executor_context_bound_hours(cfg)`, refusing rather
     than guessing on anything that is not a positive number) the bullet above is still the right
     call: hand the running agent its next task's id and let it keep the context it has already
     paid for. AT OR PAST it, stop preferring that. Every later turn of a continued agent still
     carries everything earlier, and the cache backing that context is rewritten as it lapses, so
     an agent continued past the bound pays close to three times per turn what it paid before —
     almost all of it material it had already read once — for reasons that have nothing to do
     with the difficulty of the task in front of it. So: ask it to hand back instead of handing it
     another task — a short summary a fresh agent starts from (what is finished, what is left,
     anything not already in the plan), never a stop mid-task — then spawn a FRESH executor for
     the next ready task, briefed from that summary the same way a retry is briefed from the last
     attempt below. **Nothing measures an agent's own elapsed time for you** — no hook watches a
     subagent's clock, so reading the bound against how long THIS agent has actually been running,
     from when it was spawned (step 3) or last continued, is yours.
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
     - the `raw log:` path the last attempt's own `--own` run printed, when this session still
       has it — the whole of that run's output, which the terminal never carried in the first
       place, so a retry told only the gate entry that failed re-derives the reason for itself
       unless the log's path travels with it.

     **What the gate records is the failing gate ENTRY, never the failing test.** `GATE RED`
     names entries, the row's `failed` list is those same names, and `_evidence_io.row_for()`
     assembles a row from named fields with no runner output crossing into it — so the test's
     name is nowhere on the record. If the last attempt named it, it is in `outcome.technical`
     and only there: quote it from there, and where it is not there say the record does not
     carry it rather than sending the retry to re-derive a red you already have.

     It does **not** carry the last attempt's diff. A red gate commits nothing and reverts
     nothing, so those edits are in the working tree the retry inherits: the tree is the
     attempt, and the brief is the record of what the attempt ANSWERED.

     **The computed brief carries this when `attempts > 1`**: `audit-lookup.py brief
     --role executor` puts `outcome.technical` verbatim, `testEvidence` and `redFirst` in a
     retry section, and `bf3` in `plugins/audit/tests/test_audit_lookup.py` holds it. The
     gate's own output and the `raw log:` path are this session's, not the record's, so adding
     them to the prompt beside the path is still yours; and a retry briefed by hand instead of
     by the script is checked by nothing — no gate reads a prompt.
   - The subagent does **not** commit — the orchestrator commits (step 4).
   - **The subagent must NEVER run `git stash`** (a stash in a shared working tree destroys sibling tasks' work).
     To read a baseline it should use `git diff`/`git show HEAD:<file>` to stdout instead, never redirected
     over a file; a red against HEAD is `stamp-verification.py red`'s job. Put this in every subagent prompt.
   - **No usable return** (the subagent died, timed out, or came back with no parseable outcome / no
     file changes) is a **failure**, not a success — handle it exactly like a test failure in step 4
     (leave `in_progress`, do not commit; retry until `attempts >= maxAttempts`, then `blocked`
     through `audit-task.py block`, as step 2 says).
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
        there was nothing to commit and it said which; **1** git refused (a commit hook, or a
        partial commit git will not make during a merge), the index already held paths this commit
        may not carry, each one named — unstage them, or declare them with `/audit:task scope`,
        which widens the scope and so means **recording the gate again** before this commit — a
        declared file git ignores was named (`ignored; -f is yours to decide`: the script never
        forces one in), a record path git ignores was named (un-ignore it), the index could not be
        read to be put back, or the task's verdict refused the commit; **2** the manifest will not
        load, there is no such task, or an override carries no reason.

        **The commit is bound to the gate you recorded above, and the script enforces it.** It
        reads the task's newest evidence row — the rows carrying its task id, so a task measured
        by its phase's gate under `--task` counts and a sign-off run does not — and refuses unless
        that row is `passed`, was measured under the gate the task declares now (the row's steps
        and the count of steps it dropped, against `tests.gate` or the phase's, and the row's
        `gateDigest` — so a `meta.buildCommands` edit that changes what an entry runs is a changed
        gate too), and its `testedState.scopeDigest` still matches the declared files it is about
        to commit. So the order of this step is load-bearing: record the gate, then commit, and
        **any edit to a declared file, any change to the declared scope and any change to the gate
        or to what its entries resolve to after the gate ran means recording it again** — the
        refusal names the run, says whether the declared LIST or the files' CONTENTS moved, and
        gives the command to run. The digest is taken the same way on both sides: a `:line-range`
        entry is hashed as its file, a directory as the files git lists under it (a directory git
        lists nothing under as a defined empty entry), and the paths
        the recorder itself writes (the manifest, its shards, the ledger, the trail) are left
        out. A verdict the recorder repeated rather than re-measured is graded against the run it
        names. A ledger line that will not parse refuses unless it names another task's id, and
        the refusal names the file and line (`audit-journal.py verify` shows it). A task nothing
        can measure — its task gate cleared on purpose (`gateBasis: cleared`), or its own
        `tests.gate` and its phase's `testGate` both empty — commits and the output says it is
        bound to no verdict, and says which of the two it is (a cleared task gate is still graded
        by the phase's `testGate` at sign-off). **A red recorded under the gate after the last
        green refuses that commit**, and neither emptying the gate nor the `empty-gate` row
        `--record` then writes retires it: only a green, or `--override-verdict` with a reason,
        does. With no such red, the `empty-gate` row is the gate's recorded answer and binds it;
        the same row under a gate that declares entries now is refused as a gate changed after the
        measurement, so record the gate again.
        `--override-verdict "<reason>"` commits over a refusal and writes an
        `audit.task.verdict-overridden` journal row naming the commit, the run and the reason; it
        is refused while `journal.enabled` is false. An override is a human's call, like the risk
        gate in (a): do not pass it to get a red task committed. **Nothing stops you passing it** —
        the script cannot tell who typed the reason — so the journal row is the whole of the
        control, and it is what a reader checks afterwards (`audit-journal.py show --target
        <taskId>`).

        **Do not compose these git commands yourself.** This was the one git operation this
        document described in prose and nothing scripted, and prose cannot refuse: four scope
        breaches on one program came from widening two words of the paragraph that used to sit
        here — a file "obviously" part of the change, a sibling the editor had also touched, the
        shared index because the phase file was allowed. Every one of them is a commit nobody
        reviewed, made against the record everything else is graded by.

        What the script does for you, so you know what you are no longer responsible for: the
        `<gitRoot>/` prefix and any `:line-range` suffix are stripped; a declared path outside the
        git root, or one that is neither in the working tree, the index nor HEAD (the red-first
        case a task names before writing it), is **reported and passed over** rather than failing
        the commit; a declared path only HEAD still holds — the source of a staged `git mv`, or a
        staged `git rm` — is committed as the rename or deletion it is, and so is a file taken out
        of the index with `git rm --cached` and then ignored (that one commit is a real
        `git commit` against a temporary index built from the HEAD read before staging, so it
        carries exactly the allowed paths and runs the project's `pre-commit` and `commit-msg`
        hooks like every other commit; a hook that refuses leaves your index as it was, and if
        HEAD moved underneath the script refuses, names both SHAs and resets nothing); a tracked file under
        a gitignored directory is staged as the tracked file it is, and so are the tracked files of
        a declared directory git ignores as a whole; a conflict resolved in the working tree is
        resolved by the staging, as plain `git add` would; the manifest **index** is refused with a
        sentence of its own; the staged list is read back after staging as well as before it; and
        any refusal after staging puts the allowed paths' index entries back as they were found —
        an entry you had staged at its own bytes, a conflict's stages and an intent-to-add path
        included, in a SHA-256 repository as in a SHA-1 one; stat data and a skip-worktree bit are
        not restored.
        `verify-invariants.py`'s `commit-scope` re-derives the same allow-list from git
        afterwards, so these commits are graded by something that did not make them.

        The rest of this step is still yours:
        - **A widened scope cannot pair with `fileIndex` at this commit, and that is
          expected.** `task.files` lives in the shard you just staged; `fileIndex` lives in the index
          you may not. So a task whose scope you corrected mid-run commits a state where the two
          disagree — measured on live runs at 39 and 93 occurrences — and `manifest-revalidated`
          records those as **deferred** rather than as breaches. It then asks the pairing of the
          manifest **as it stands**, so the debt is real and is settled once: land the index change
          in its own commit before sign-off, with the script that already does this correctly —
          `/audit:task scope` re-derives `fileIndex` for you, and
          ```
          python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-manifest-index.py" \
              <manifestPath> <phaseId>
          ```
          commits the index and the one journal file holding the row that names the commit, and
          **nothing else**, under the lock, and refuses rather than committing nothing
          or committing it beside work that does not belong with it. Its name used to reach a human
          only inside `commit-task-work.py`'s refusal — after a task commit had already been turned
          away for staging the index — which is too late for a caller who commits by hand instead:
          a hand commit that sweeps up the index without the shard it now names leaves the manifest
          invalid **at that commit**, because the index then names a task the checked-out shard does
          not carry. `/audit:task add`, `add-phase`, `scope`, `retarget`, `cancel`, `start` and
          `done` each print this same pointer themselves, the moment a write of theirs leaves the
          index dirty, so the tool is discoverable before that mistake and not only after it.
          **The order is the shard first.** The script itself committed an index ahead of its
          shard until it learned not to: it now refuses an index that names a task or phase the
          shard committed at HEAD does not hold yet, names each reference and the shard, and asks
          for the shard to be committed first - the task commit, which carries it, or
          `commit-audit-state.py`.
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
          `audit-journal.py merge --file <journal or evidence file>` is what resolves that without
          recomputing anything a row says: one implementation for both records, the same
          refusals, and a same-second tie ordered by content only when its rows touch different
          targets (a journal row's `target`; for a run, every key a ledger reader files it under,
          the plan's moved task ids included), with the order written down -
          in the journal file's `journal.merge` row, or for a ledger file in an `evidence.merge`
          journal row naming it, because every row in the ledger is read as a recorded run.
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
        - **Declare BOTH halves of anything `git mv` moved.** `git mv` stages the file at its
          **pre-edit** content, so a task that moves a file and then edits it would commit the OLD
          bytes if the new path were not added again. The script re-stages every declared index
          entry at its working-tree bytes, and it commits the source through its pathspec — but
          only for paths the task declares: an undeclared source is refused as a staged path this
          commit may not carry. **No gate can catch a hand commit getting this wrong**:
          `run-test-gate.py` measures the WORKING TREE, and this defect lives in the INDEX — the
          tests pass on the files you have while the commit carries files nobody ran. A live run
          came within one commit of shipping a shared module importing a feature while the
          manifest recorded the opposite.
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
          <taskId> --commit <sha> --from-return`, which writes it with the rest of the close,
          read off the filed returns, in one write). The
          script deliberately does not: the SHA is only knowable after the commit it makes and the
          shard is inside that commit, so writing it there would need a second commit or the amend
          this document forbids. It leaves an `audit.task.committed` journal row in the meantime,
          so the gap between the commit and this write is not a commit nothing points at. That
          row is INSIDE the commit it names: it is written first, keyed by a nonce the commit
          message carries as its `Audit-Row` trailer, and `git log --grep "Audit-Row: <nonce>"`
          finds the commit from it. A commit refused after the row was written leaves an
          `audit.commit.withdrawn` row naming the nonce.
          **Do NOT write `bugs[]` by hand.** A bug materialized into this task (`bug.taskId` ↔
          `task.bugId`) reads as **fixed** once the task is `done` — the rollup derives it (with
          `fixedIn` = this `task.commit`) — and `/audit:task done` stores both values on the bug in
          the same write, under the index lock. That is the one write a task close makes to the
          index, and the verb says so with the `commit-manifest-index.py` line that lands it on its
          own; a close of a task no bug links to leaves the index untouched. (`/audit:bug close` still records a human `wontfix` / `not_a_bug` / `fixed`
          on the index, under the index lock — a structural decision, not part of a run.)
        - The `task.commit` write rides along with the next task's commit (or the sign-off commit) — do NOT amend.
     d. **ADO echo** — now that the SHA is captured, echo the done transition
        (`reference/orchestrator.md` → **ADO echo**; an `onComplete` comment carries this
        `task.commit`).
   - **a proof that could not be made** (the returned `redFirst.status` is
     `could-not-prove`) → **record it and carry on.** `done --from-return` copies the filed
     block onto `task.redFirst` in the close's own write — the refusal in `basis` verbatim, the
     classifier's own words rather than your summary of them — so it lands with the work
     instead of in a session note. Then take whichever arm the gates ask for; this arm changes none of them.

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
   - **test failure** (gates RAN and are red) → leave `status = "in_progress"` (or, if attempts are
     exhausted, set it blocked through `audit-task.py block <taskId> --reason "<the red gate's
     reason>"`), put the reason in `task.outcome.technical`, and report it. Do not mark done, do not
     commit.
     A transition to `blocked` gets the **ADO echo** (`reference/orchestrator.md` → **ADO echo**).
   - **infrastructure failure** (gates could NOT run: missing command, runner crash before tests,
     zero tests collected where `tests.add` expects some, a filter that selected no test file, a
     worker the OS killed — `GATE COULD NOT RUN` and a `could-not-run` row) → this is NOT the task's failure:
     **revert the `attempts` increment from step 2** (Edit it back down), record the cause in
     `task.outcome.technical`, leave `status = "in_progress"`, and **STOP with a human action item**
     (fix `meta.buildCommands` / `tests.gate` first). Never burn retries on missing infrastructure.
   - **classifier gave no verdict** (a tool call refused with text containing
     `auto mode cannot determine the safety` or `gave no verdict` — the wording
     seen in 2.1.2xx transcripts) → the auto-mode permission classifier produced
     **no verdict** on that step, which this pipeline used to read as a failed
     attempt. It sits beside the infrastructure arm rather than inside it:
     **revert the `attempts` increment from step 2** (Edit it back down), record
     the refusal **verbatim** in `task.outcome.technical`, leave
     `status = "in_progress"`, and report the classifier as **unavailable** —
     raise **no human action item**, because there is no infrastructure to
     repair here: the same classifier meets the same step again regardless. This
     is `could-not-run`, never rendered as a failure.
5. Manual gate items (e.g. `"manual: <checklist>"`) cannot be auto-run — surface them as **human action items**.
