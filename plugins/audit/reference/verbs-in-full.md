# The command verbs, in full

What each pipeline command's verbs write, refuse and why - the explanation behind
`commands/run.md`, `next.md`, `resume.md`, `review.md`, `phase.md` and `task.md`, whose bodies
carry only the step driver's loop and each verb's command line. **No command reads this file
first** - `tools/measure-context.py --gate` holds that no pipeline command makes the main loop
read a reference file before its work - and the rule a step needs is printed by the step
driver (`scripts/governance/drive-phase.py`) at that step, or stated in the prompt of the agent
that acts on it. This file is for `/audit:guide` and for a reader who asks how a verb behaves.
Where it says "you", read the caller of the verb. Its `## ` sections are declared in
`scripts/manifest/_areas.py`'s `UNANCHORED_SECTIONS`, each with why nothing anchors it.

## What the run commands leave behind

`/audit:run <taskId>` and `/audit:next` run one task through `drive-phase.py next <taskId>`;
`/audit:resume` sweeps an interrupted run's record and then continues the phase through
`drive-phase.py next <phaseId>`. This is what each guard and each record means, for a reader who
asks.

### The status guards of `/audit:run`

The step driver hands three of these back itself: a task already `done` or `cancelled` is reported
`done <taskId>: already ...` with nothing started, a `blocked` one stops the drive with its
recorded reason, and an `in_progress` one resumes at the step its last run stopped on. What
follows is what each guard is for.

Execute exactly `<taskId>`, with status guards:
1. `status == "done"` → refuse: report its `commit`/`outcome`. Offer (AskUserQuestion) an explicit
   **re-open**, and on confirmation run the verb, never a hand edit:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" reopen <taskId> \
           --reason "<the human's why, verbatim>"
   ```
   **The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The
   operator's words go in unchanged*: `--reason` reaches the hash-chained journal, and `-` reads it
   off stdin. It resets `status = "pending"`, `attempts = 0`, clears `commit`, `outcome`, `completedAt`,
   `verifiedBy` and `intentCheck`, and puts a linked bug back to `in_progress` with no `fixedIn`, so
   a re-opened bugfix task never leaves its bug marked `fixed` at a stale SHA — under the index lock,
   revalidated, with a `task.reopen` journal row. **It refuses a task whose phase is signed off**
   (done, or signed off and awaiting its merge): that verdict reviewed the work as it stands and
   sign-off is not re-decided, so the phase could never be signed again, and a stored `done` over
   an open task is a plan every later verb refuses as invalid. Relay the refusal: the new work is a
   new task in an open phase or a bug (`/audit:bug`). On exit 0, execute. Never silently re-run a
   done task.
   A reopened task with an `ado` link gets the **ADO echo** (orchestrator.md → "ADO echo"): its card
   moves back to the pending-state with the comment `reopened by /audit:run` — the reopen was
   human-confirmed, so the board move inherits that consent.
   **`testEvidence` is deliberately not on that list.** The block is a cache of a run that
   really happened, the evidence ledger still holds that run, and `run-test-gate.py
   --reconcile` re-derives every subject's pointer from that ledger — so a cleared pointer is
   put straight back by the next reconcile or the next recorded run, and clearing it buys a
   reader nothing but a disagreement between the plan and the record, which
   `/audit:doctor` will then report. What marks the verdict as stale is the task
   reading `pending` again beside an `at` stamp older than the reopen, not a missing block.
2. `status == "blocked"` → the drive stops, naming the `blockedReason` the block recorded
   (exhausted attempts, a blocker, or `audit-task.py block`'s own reason), and prints the remedy
   as the rule under that stop; the human answers it, never a hand edit of the plan. The remedy
   is named per task, from its attempts against `maxAttempts`: a task with attempts left is
   restarted by `audit-task.py start`, which clears `blockedReason` and records the old reason in
   its `task.start` row — a pending task still carrying one would read as waiting; a task whose
   attempts are spent is `audit-task.py unblock <id> --reason "<their words>"`'s, since `start`
   refuses it and `unblock` refuses a task with attempts left.
3. `status == "in_progress"` → the drive resumes it at the step its last run stopped on: the
   driver keeps its state per phase, so no re-execution question is asked, and an agent that
   filed nothing becomes a named decision rather than a silent second dispatch.
4. Unmet blockers, or a phase claimed by a session that may still be live → relay `audit-task.py
   start`'s refusal the way `reference/manifest-conventions.md` → *The operator's words go in
   unchanged* states.
5. Otherwise run **Execute the task** (orchestrator).

### Which run becomes evidence, and a failed run's record


**The gate run that becomes evidence is yours, not the subagent's.** The orchestrator's
*Execute the task* holds the invocation and the reason; what matters here is that the
subagent's own run is what it develops against, and the recorded one has to be the
wrapper's — the bracket, the check count, the coverage answer and the tree comparison are
only true of a run the wrapper made. `--record` prints two lines: one says the row was
written, the other whether the plan now names it. Read both. A **refused pointer is not a
failure** — another live session may hold the phase lock — so do not retry the gate to
chase one; the row stands either way and `--reconcile` catches the plan up later.

A step that outruns `--timeout` (the script's own default when nothing passes one) is torn
down and recorded as having timed out, and the tree comparison is then **refused rather than
guessed**: a descendant that escaped the kill is still writing, so comparing the snapshots
would be a race whose answer changes with timing.

**A single-task run is the case where a failed gate has nothing to ride out on.** A task
commit stages the evidence directory, so inside a phase run an attempt that failed and was
retried is made durable by whatever commits next. This command commits only when the task
reaches `done` — so when it ends `blocked` with its attempts exhausted, and on the
infrastructure path that stops without committing, the rows just written sit in the working
tree with nothing coming behind them. Both are named points in the orchestrator's
*Keeping a failed run's record*; run
`commit-audit-state.py` at them. It stages the phase's manifest file, the journal and the
evidence directory and **never the task's `files`** — the implementation stays unstaged,
which is what makes committing a failed task's state possible at all.

Under the step driver a task blocked over its red gate is committed this way at once: answering
`block` runs `commit-audit-state.py` after the block, so the rows the gate wrote reach git.

### The resume sweep

`/audit:resume` runs `commit-audit-state.py <manifestPath> <phaseId>` before it continues.
**This is the point the record of an interrupted run depends on.** A gate that was torn down
records its row and returns — git belongs to the orchestrator, and a commit made while
stopping is how a half-made one happens — so what a lost session leaves behind is a row in
the working tree that nothing is going to carry. A task commit would have carried it; an
interrupted run never reached one. This is that sweep, and it is the resume entry among the
points the orchestrator's *Keeping a failed run's record* names.

**It stages the phase's manifest file, the journal and the evidence directory, and never the
task's `files`** — which is exactly what makes it safe to run here. The interrupted task's
working-tree changes are the thing the orchestrator's own resume step calls **untrusted**
and refuses to discard without confirmation; this commit must not settle that question in
the other direction by sweeping them into git on its way past. The
exclusion is enforced rather than intended: paths are staged by name, the index is read back
and compared against the same allow-list before anything is committed, and
`verify-invariants.py`'s `audit-state-scope` re-derives the rule from git afterwards.

**Calling it when nothing is wrong costs a line of output.** With nothing uncommitted it
makes no commit and says so. Journal rows another writer left are committed like the other
records: the row this command writes to name its commit is inside that commit, so a second run
finds nothing and stops. So run it on every resume rather than first deciding whether this
particular interruption left anything; deciding is what it is for.

## `/audit:task`'s verbs

What each `/audit:task` verb writes, refuses and why - the explanation behind
`commands/task.md`, which carries each verb's command line and the few rules the main loop
follows. Where it says "you", read the caller of the verb.

**The flags ARE the interface; the dialogue is the fallback.** Every answer the
`add` and `scope` sections gather is a flag on `scripts/manifest/audit-task.py`, so a
caller who already holds the specification passes it and is asked nothing — step 2's
*ask only for what's missing* is what happens to whatever is left. `commands/task.md`'s hint used
to advertise `--phase` alone, and what that cost was measured live: an operator holding
files, gate, risk, tests-mode and description was taken through a round of
`AskUserQuestion` per value, and every question that did not need asking is another
chance to **paraphrase** a value the caller had already decided — the defect `--reason`
had (see *Subcommand: `cancel`* below).

**A flag belongs to the verb whose hint carries it, and passing it to another one is a
usage error.** One `argparse` parser serves every verb of the writer script, so it accepts every
flag on every one of them — and each verb's writer only ever read its own subset, so
half the pairs used to be accepted, write nothing and report success with exit 0
(`scope --outcome`, `add --id`, `add-phase --risk`, `retarget --files`). Those now exit
2 with a message naming the verb that does read the flag. **Relay that message rather
than retrying**: it is telling you which command you meant.

**`priority` is deliberately absent from `commands/task.md`'s `argument-hint`** while remaining a
working subcommand. The hint is what a reader is offered when they type the command, and
offering the old spelling there is how the old spelling keeps being learned — the
opposite of what an alias is for.

### 0. Conventions

A manifest that does not exist yet points to `/audit:init` (or the starter template).
Every subcommand writes through `scripts/manifest/audit-task.py`, which takes and
releases the **index lock** itself — `move` included, which used to be the one procedure
done with Edit — so no write described here is made by hand, and no lock is held by hand.
**Creating a phase is `/audit:phase add` and is no longer done here by hand** (see step 1).

**In the sharded layout, a write here can leave the shared index sitting dirty beside the
phase shard it also touched** — `add-phase` always does; `add`/`scope`/`retarget`/`cancel`/
`start`/`done`/`reopen`/`block`/`note` do it whenever a mirrored stub key (`status`, `title`, …)
or `fileIndex` moves, and `move` whenever it rewrites a `fileIndex` row, a bug's `taskId` or a
parked proposal.
A task commit will not carry that index (`orchestrator.md` step 4c refuses it on purpose, so
two phases can merge without a conflict there), so it needs its own commit —
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-manifest-index.py" <manifestPath>
<phaseId>` lands it alone, under the same lock, **after** the shard it names is committed - it
refuses an index that names a task or phase the committed shard does not hold yet, because
that commit would record a plan that does not validate. **The script prints this itself, naming that
exact command, the moment its own write leaves the index dirty** — read it off the output
rather than remembering the rule here. It is printed only when the index **bytes** changed:
a write whose index would come out identical does not rewrite it, and `scope` touches only
the `fileIndex` rows it claims or releases, so a shared row keeps its order on a call that
moves nothing.

### Subcommand: `add "<title>" [--phase <id>]`

The add is a SCRIPT call, not a hand-templated edit. `scripts/manifest/audit-task.py` allocates
the id under the index lock, initializes every orchestrator field from the conventions'
new-task template exactly once, extends `fileIndex`, revalidates from disk (rolling the
write back on findings) and journals a `task.add` row. Your job is to gather the answers
and pass them as flags — NEVER hand-write the task JSON; hand-templating fifteen fields
per add is the class of error the script exists to delete.

1. **Target phase**:
   - `--phase <id>` given → pass it through. The script refuses a `done` phase
     (immutable history) and a phase id reserved by a parked proposal (pointing to
     `/audit:propose materialize`) — relay those refusals, then offer the
     alternatives below.
   - Otherwise call without `--phase`: the script defaults to the single
     `in_progress` phase; with SEVERAL running (several developers, each on a phase
     branch of their own) it takes the one whose recorded `branch` is checked out
     here, and says so on a `phase:` line (`phaseBasis` under `--json`); otherwise
     it exits 2 NAMING the choices. On that exit 2, ask
     (AskUserQuestion): one of the named phases, or **new phase**. On a phase branch,
     a new phase is usually the wrong answer: phases are minted on the development
     branch, so offer `/audit:phase add ... --park` (a proposal materialized after the
     branch merges) - see `commands/phase.md`. A new phase is
     `/audit:phase add "<title>" --outcome "<what success looks like>"` — follow
     `${CLAUDE_PLUGIN_ROOT}/commands/phase.md` → *Subcommand: `add`*, which takes
     the index lock itself, then re-run this add with `--phase <newId>`. **Do not
     hand-write the phase.** This step used to say "create it with Edit under the
     index lock", and that instruction was wrong in the sharded layout in a way
     a reader could not see: a phase there is a shard file AND an index stub, and
     an Edit that produced one of them leaves a manifest the next command cannot
     read.
   - When a still-parked proposal (`proposals[]`, status `proposed`) already
     covers this work (title/scope overlap), say so and offer
     `/audit:propose materialize <PROP-id>` as the alternative before creating a
     parallel task by hand.
2. **Gather the answers** (ask only for what's missing; propose sensible defaults):
   - `--description` — problem, approach, key decisions. **If the brief contains
     backticks, OR any code-shaped punctuation next to whitespace (a ternary, a
     colon-joined pair), pass it on stdin with `--description -`** (see *A brief
     the shell has eaten is refused* below) — inside double quotes a backtick
     span is command substitution and the shell deletes it before this script is
     started, but the script's own check tests the whitespace SHAPE such a
     deletion leaves and never the backtick itself, so brief text with none can
     still be refused off argv.
   - `--files a,b` — repo-relative paths this task touches (Glob/Grep to verify they
     exist; the script notes misses but allows new-file paths).
   - `--outputs docs/audit/evidence/**,docs/reports/*.md` — patterns for what this
     task **produces** rather than edits: the documents a run writes, an evidence
     directory, a generated report. Use it whenever the work's own output is a file
     the task cannot name in `--files` because it does not exist yet and its name is
     not known in advance. While the task is `in_progress` the plan gate treats a
     write matching one of these as covered, which is what stops a documentation
     write being reported as uncovered on every save — and a gate whose warnings are
     noise is a gate that is off.
     **Each pattern starts with a literal directory name.** `docs/**` is accepted;
     `**`, `**/*.md`, `.`, `*/x`, an absolute path and anything with a `..` segment
     are refused, naming the pattern — a task that covers the whole tree would turn
     the plan gate off through the door built to keep it on. `**` spans directories,
     `*` stays inside one, and a trailing `/` means the same as `/**`.
     `add` is the only verb that takes it; declaring artefacts is part of writing the
     task down.
   - `--tests-mode` (`tdd` for incorrect current behavior / `regression` for
     behavior-preserving / `gate-only` for mechanical — the script sets
     `expectRedFirst` true iff tdd), `--tests-add "<desc>"` (repeatable, one test
     description each — **write it as `"<path>: <what it asserts>"`**, because
     the leading path is what joins `files` and the `fileIndex`, and an entry
     that names no file adds nothing to either and is reported as adding
     nothing; the field is free prose and the script will not guess a filename
     out of a sentence. On a `tdd` task that is neither `done` nor `cancelled`
     the validator **warns** when an entry names no file, and that becomes a
     **finding at 3.0.0** — `COMPATIBILITY.md` → *Validation stays additive* is
     where the window is recorded), `--gate "<entry>"` (repeatable; pass it only to
     OVERRIDE — with no `--gate` the script DERIVES the gate from this task and
     reports which of three defaults it took, see *The task gate is derived* below),
     `--gate-clear` for the **empty** gate — the state a phase can
     be created in and `scope --gate-clear` can move a task to, which `add`
     accepted and silently ignored until it read the flag, so a new task whose
     work nothing here can grade inherited the phase's gate and had to be
     rescoped straight afterwards. It refuses alongside `--gate`, as `scope` and
     `/audit:phase retarget` do; a task created with no gate is **reported** as
     such rather than in silence, and the phase's `testGate` at sign-off is what
     still grades it. It records `tests.gateBasis: cleared`, and that word is what
     `run-test-gate.py --task` reads: such a task resolves EMPTY at task scope
     rather than borrowing the phase's gate, while a task that merely declares no
     gate still falls back to the phase's and says so.
   - `--failing-from <runId>` — for a FIX task opened after a red sign-off run:
     point the new task's gate at the suite(s) that run's own steps NAMED as
     failing, unioned with this task's `--tests-add` paths, in the phase's
     path-scoped spelling. See *A failed-first fix task is gated on what the run
     named* below for the refusals and the fall-through.
   - `--model` (default `sonnet` — the floor for all fix work; the script escalates
     `risk: high` to `opus` when no model is passed; do NOT use `haiku` for
     audit-fix work), `--risk` (`low`/`med`/`high`).
   - **Skills** — do not scan the filesystem for skills yourself; there is ONE
     mechanical source. Run (Bash):
     ```bash
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-status.py" <manifestPath> --json \
         --discovery --section discovery
     ```
     `--section` projects the one block this step needs, so the printed object lists
     every skill this project can actually see directly
     (`{"skills": [{"name", "description", "source"}, …]}` — project
     `.claude/`, user `~/.claude/`, installed plugins). A top-level `error` key
     means the scan failed and the lists are empty (fail-open, not wrong): say
     so and offer only the area defaults below. Then ask "which skills should
     the executor load for this task?" (AskUserQuestion), offering:
     - the phase's **area default skills** from the `meta.areas` registry (the
       manifest you already read: match the task's `--files` against the area
       `root` prefixes) — mark them as the default (they load first for every
       task in the area anyway; naming them on the task is a no-op kept for
       readability);
     - **discovery names as options** — `skills` entries whose
       names/descriptions match the task's files and subject — offer names the
       printed object carries and nothing else, never invented ones;
     - **"null — none applies"** — the explicit opt-out, written as JSON `null`:
       it STOPS the area fallback so nothing loads. Distinct from leaving skills
       unconsidered (`[]`, the default), where the area default stays in force.
     Then `--skills a,b`, `--skills null`, or omit the flag for unconsidered.
   - `--blocked-by` / `--depends-on` — comma-separated ids (omit when none). These two,
     `--files` and `done --verified-by` also REPEAT, and every value is still split on
     commas: `--depends-on P2.1 --depends-on P2.2` and `--depends-on P2.1,P2.2` are the
     same list. `--help` says so on each flag, with an example.
3. **Run it** (Bash) — the brief on **stdin**, which is the only form a shell
   cannot rewrite:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" add "<title>" \
           --phase <id> --description - --files a,b \
           --tests-mode regression --risk low --skills a,b <<'BRIEF'
   <why & how — backticks, quotes and $ signs all survive this route>
   BRIEF
   ```
   `--description "<why & how>"` still works and is fine for a brief with no
   backticks in it; the heredoc form is the one to reach for by default, because
   whether a brief needs it is a judgement made *before* seeing what the shell
   did.
   **Print the script's output verbatim — validator findings and warnings
   included. Do NOT re-format, summarize, or "improve" it.** The report already
   names the id, what was written, the journal outcome, and whether the task is
   ready now (with the `/audit:run <taskId>` handoff).
4. **Exit codes**: `0` done. `2` usage — the message names the choices (ambiguous
   phase, done phase, reserved id, missing manifest, a `--description` off argv
   with a shell-eaten hole in it): ask the human, adjust, re-run.
   `1` the add would leave the manifest invalid — it was rolled back byte-for-byte
   and the findings are printed; fix the inputs (e.g. a `--blocked-by` id that does
   not resolve) and re-run. `3` the index lock is held by a live run — stop; do not
   take it over. `4` the lock looks abandoned — confirm with the human
   (AskUserQuestion), then re-run the same add with `--takeover`.

#### `--fixes <findingId>[,<findingId>]` — a fix task the plan records as one

A task added to fix review findings names them: `--fixes P3-R1,P3-R2` writes `task.fixes` and
each finding's `fixTask`, in the write that adds the task. It refuses, writing nothing, a
finding outside the new task's own phase and one that already names a fix task; no other verb
takes the flag. Under `review.perTask: phase` this is what lets the task close `--intent
not-asked --intent-basis "<why>"` instead of owing the phase review its answers — and only
while each finding it names still names it: a `resolve-finding` that points one at another
task, or a `move` taking the task away from its findings, ends it, and the landing then
refuses the task until a phase review answers it.

#### The task gate is derived, and the report says from what

**With no `--gate`, `tests.gate` is derived from the task being added** — it is not a
copy of `phase.testGate` any more. `commands/init.md` → step 5.3 carries the reasoning
and this is the same rule at the other door: the phase gate is wide because its question
is wide, and a task gate is narrowed to the task's own files — a wider one does not
answer its question any better, it answers the PHASE's question again, once per attempt,
per task, per phase running in parallel.

Three defaults, taken in order, and **the script prints which one it took** on the
`gate:` line (and as `testGateBasis` under `--json`):

1. **the task's own `tests.add` paths**, written into the path-scoped spelling a
   sibling task in the phase already carries. First, because a task whose gate never
   runs the case it just wrote has bought a green with nothing behind it.
2. **the task's `files`**, in that same sibling spelling, when no case is named.
3. **the phase's `testGate`** — the wide one — when no sibling carries a path-scoped
   entry, or when this task names no file at all. The two reasons print differently
   because they are repaired differently: the first wants a narrow `--gate` typed once
   (every later add in that phase then reads the spelling off it), the second wants
   `--files` or `--tests-add`.

**A wide gate the plan chose stays wide, and that is the load-bearing half.** Nothing
outside the gates themselves records how a project narrows one, so a phase whose tasks
all carry the wide entry has recorded no spelling — and narrowing on a resemblance
there would be a guess in the direction that never gets noticed. Read the printed basis
rather than the entries: a narrow gate and a wide one look alike once written, and the
sentence is what tells them apart without opening the shard.

**And the arm is written down, not only printed.** The same derivation sets
`tests.gateBasis` — `tests.add`, `files`, `phase-no-spelling`, `phase-no-paths`,
`gate-only-no-suite`, or `declared`/`cleared` for the two flags. **`gate-only-no-suite` is
`gate-only`'s own arm**, and it fires only for that mode: a `gate-only` task names no `tests.add`
case at all, so a source file among its `files` is not evidence the project's suite-running
command has anything of this task's to run, and narrowing to it would buy a green on work nobody
wrote. When none of the task's `files` is a suite path (`_manifest_phases.is_suite_path`), the
gate becomes `meta.phaseGate.always` where the plan declares one, else the sibling's own shared
keys and path-less entries carried through — **never** the phase's wide `testGate`, which an
operator already gets warned about running every attempt. The sentence is for a person and is gone after
one screen; the word is what `validate-manifest.py` reads when it asks whether a task
carrying its phase's gate verbatim is holding a default or an answer. It is silent on
`phase-no-spelling` (this project records no path-scoped spelling, so there is nothing to
narrow with), on `gate-only-no-suite` (a `gate-only` task's own files name no suite to narrow to,
which is its own answer) and on
`declared` (a caller named these commands), and it names everything
else — including a task that records no basis at all, which is what a hand-written or
generated plan carries.

**`scope --gate` is how an existing task answers that line.** It rewrites `tests.gateBasis`
to `declared`, and it does so **even when the command list does not move** — declaring the
wide gate outright is exactly the call an operator makes here, and a verb that compared
lists alone would report "already reads that way", write nothing, and leave the only
remaining route a sentence in the `description` that no rule opens.

#### A failed-first fix task is gated on what the run named

**`--failing-from <runId>` reads the evidence ledger before the three ordinary defaults,
never instead of them** — `--gate`/`--gate-clear` still answer first, exactly as they do
for every other verb. The runId is looked up (`_evidence_io.row_by_run`), never parsed:
the schema calls a runId opaque, and reading structure into one here would be a second,
silently different answer to a question the lookup already answers.

**Three things have to be true of the row, each refused by naming the actual value:**
it must EXIST (a mistyped runId is told there is no such run, never handed the ordinary
derivation in silence); it must be scoped to **this phase** (a task's own run, or another
phase's, cannot license a gate narrowed to suites this phase never ran); and it must carry
`status: "failed"` (a fix task opened from a run that PASSED is not failed-first, and the
sentence names the actual status).

**Only a suite the row's failed steps NAMED counts.** A step's `failingSuites` is read —
never `failing`, which carries a CHECK's own title and no path — and only when its
`failingSuitesBasis` says the runner NAMED them; `run-test-gate.py` falls back to a capped
tail of a step's own output when no runner it recognises wrote a summary, and a tail
excerpt is not a list of failing tests. The suites are UNIONED with this task's own
`--tests-add` paths — a fix task may still be asked to write a NEW case beside the failure
it repairs — and pointed through the phase's path-scoped sibling spelling exactly as the
three ordinary defaults are. `tests.gateBasis` is written `failing-from-run:<runId>`:
compare the word before the colon, and look the runId up rather than parsing further.

**The gate is never empty just because `--failing-from` could not narrow anything.** A row
whose failed steps named no suite (a tail basis) or a phase with no path-scoped sibling to
narrow through falls all the way through to the ordinary `tests.add` → `files` →
phase-wide chain, with the reason it fell through printed FIRST in the `gate:` line — the
same three defaults a call with no `--failing-from` gets, never silence and never the
empty gate as though `--failing-from` were a second spelling of `--gate-clear`.

#### A brief the shell has eaten is refused

**`--description` carries the operator's own words and reaches the script through a
shell.** Inside double quotes a backtick span is **command substitution**: the shell
runs whatever sits between the backticks and puts its output there instead — for a
sentence of prose, nothing. Measured live: a brief that backticked the one condition
the work turned on was stored as `… gating on , returning the response untouched
otherwise.` The clause marked as the point was the clause that was deleted, the
script accepted it, and a whole phase ran against a brief with a hole in it.

So a `--description` that arrives **off argv** carrying the whitespace such a
deletion leaves behind — a gap before a comma, a run of spaces inside a sentence, a
full stop with nothing in front of it — is **refused**, exit `2`, before the lock is
taken and with nothing written. The message marks the exact characters it matched
inside the printed window and names the route out.

**The check tests that whitespace SHAPE and never a backtick**, so a brief with no
shell and no backtick anywhere in it can still be refused — a nested ternary
(`foo() ? (a ? 280 : 70) : 0`) trips the identical refusal, because ` :` hugs the
word in front of it the same way a shell-deleted clause would. The message says so:
it names the shape it matched rather than assuming a shell was ever involved, and
the marker is what lets you tell your own punctuation from real damage without
reading the regex. **This is the route to reach for whether or not you see a
backtick** — `--help` on the flag says as much now, which it did not before.

**A colon that starts an identifier is not a hole**: `params :id and :key` is written as
typed. **A colon before a digit after whitespace is still refused, on purpose**: the plan's
commonest citation is "`path`:line", and inside double quotes the shell substitutes the
backticked path and leaves exactly ` :2680` — so a line reference written after a space goes
in on stdin. A colon with whitespace on both sides (` : `) is refused as before.

**The refusal is short**: the heredoc to retype, the marked span, and one line of cause.
For a **leading space, two spaces in a row or a trailing space** — the shapes a
substituted backtick span leaves on its own, at the start, between two words or at the end — it names command substitution as the likely cause and points at
the shell's own stderr, which says `<word>: command not found` for every span it ran. For
the other shapes it says the check cannot tell substitution from code quoted into the
brief.

**The route out is `--description -`**, and it is the fix rather than a bypass: the
brief is read from **stdin**, which no shell rewrites and which this stores verbatim.
`-` where a value goes means stdin for `audit-task.py`'s prose flags, its `--from-file` and
its `--findings-file` — and `scripts/manifest/check-ado-item.py` and its ADO siblings read a
payload the same way — so there is no `--description-file` to learn.

```bash
… scope <taskId> --description - <<'BRIEF'
transformErrorResponse gating on `if (response.status !== 409) return response`,
returning the response untouched otherwise.
BRIEF
```

**Quote the heredoc word.** `<<'BRIEF'` turns expansion off; a bare `<<BRIEF` expands
its body exactly as the double quotes did, and you get the same hole a different way.

**Text arriving on stdin is not checked**, deliberately. The refusal's evidence is
that a *shell* handled the value, which is not true there — and a guard whose only
escape is to mangle your own prose is a guard that gets routed around. So a brief
that genuinely contains one of those shapes has somewhere to go: this route, which
writes it exactly as typed. What is **not** refused is an absent description; a task
with none shows as having none on every surface that renders it, and this is about
the brief that still *reads* complete and is not.

Every verb here that takes `--description` refuses the same way, because the flag
is one flag on one parser and each of them writes the value straight into the manifest.

**`--dry-run`** builds the task exactly as the call would and validates the plan with it
**in memory** — same allocator, same derived gate, same validator the real write re-reads
from disk — and writes nothing: no manifest, no journal row. A finding exits `1` with the
`FINDING:` lines, as the real add would have rolled back on; a clean one prints the id it
would take. **Under `--json` every refusal is one JSON object** —
`{"ok": false, "exit": <code>, "refused": "<message>", "findings": [...]}` — the validator's,
the argv-gap refusal and every usage refusal alike; a success is the verb's own object,
unwrapped, and a `scope` or `retarget` call that changes nothing is `{"ok": true,
"changed": false, ...}` — so a caller parsing stdout does not meet prose. (An argparse error, before any verb
runs, still goes to stderr as argparse prints it.)

**A gate entry that is a directory is warned about**, on `add` and on `scope --gate`: an
entry that is one token, no `meta.buildCommands` key, and a directory in the project tree
names nothing to run. A command that merely mentions a directory (`pytest tests/`) draws
nothing. A warning, never a refusal.

### Subcommand: `start <taskId>`

Promote a task to `in_progress` **without spawning anything**. This is the verb for the
case `add` creates: a task added to a phase that is already running is written
`status: "pending"`, `startedAt: null`, `attempts: 0`, and the plan gate resolves an
allowed path only through tasks that are `in_progress` — `hooks/require-plan.py` reads
`hooks/_config.in_progress_task_map`, which skips every other status and whose
`fileIndex` arm only re-adds paths for ids already in that filtered set. So the new
task's **own** declared files are refused on its first `Edit`. Measured: two executors
returned zero edits, each having spent a subagent's budget, both denied on a path their
task's `files` declared.

Until this verb the only promotions were `/audit:run <taskId>`, which promotes **and**
spawns, and the hand edit `commands/task.md` forbids everywhere else.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" start P3.2 [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" start P3.2 --force --reason "<why>"
```

**It performs phase entry first** (`reference/orchestrator.md` → *Phase entry*). On a phase's
first task it cuts the phase branch from the resolved parent — or records the one
`/audit:worktree add` checked out — and writes `phase.branch` and `phase.baseRef`; a phase that
records a branch is started only from that branch. It refuses, naming why and writing nothing,
when HEAD is off the parent, detached, on a repository with no commit, or when the name is
illegal or taken by a branch the phase does not record. Outside a git repository the phase
runs with no branch and the output says so.

What it writes besides — exactly the fields `reference/execute-task.md` → *Execute the task*,
step 2 prescribes as an orchestrator `Edit`:

- `status: "in_progress"`, `startedAt` stamped at the moment of the call, and
  `attempts` incremented.
- **the phase around it, when that phase is still `pending`** — `status` and a `startedAt`
  of its own, from the same instant, in the same write. Until this, the control panel's
  save was the only thing in the plugin that promoted a phase at all, so a plan driven
  entirely from the command line left every phase pending and recorded nowhere when its
  work began. The phase's rows come back under `healed`, apart from `changes`, which is
  the task's own fields. A phase already running is left alone, and one that already
  carries a `startedAt` keeps the moment it recorded.
- **the phase's claim, on the sharded layout** — `phase.claim = {sessionId, branch, at}`
  in the phase's shard, from the same write: `sessionId` is `$CLAUDE_CODE_SESSION_ID`, `branch`
  the phase's, `at` the start's own instant. Two machines entering one phase then meet a merge
  conflict in that shard rather than running it twice. Sign-off releases it. It carries no
  `host`: the shard is committed, so a machine name there would be published, which is why
  the journal drops `actor.host` too and `tools/check-committed-pii.py` reports a `host` under
  a claim. A claim this session already holds is left exactly as it was; a single-file
  plan gets none (it has no shard to conflict in); and with `$CLAUDE_CODE_SESSION_ID` unset no
  claim is written and the output says so, because a claim naming no session is one no later
  start can recognise as its own.
- **journal** → one `task.start` row whose `details.changes` names each field with the
  value it held, plus `details.attempt` — both keys the `_journal_io.DETAILS_KEYS`
  allow-list already carries, so nothing is written that the trail would drop in silence.
  A phase the write promoted is named in the row's summary. A claim the write took adds
  `changes` rows keyed by the **phase** id — `claim.sessionId`, `claim.branch` and `claim.at`,
  each with the value it replaced — and names the session in the summary. A **forced** start (below) adds
  `details.mode: "forced"`, `details.reason` and `details.basis` naming what it was forced
  past — the unmet references, another session's claim, or both — and says `FORCED past ...`
  in the summary.
- Same index lock, same revalidate-from-disk, same byte-for-byte rollback on findings as
  `add`.

**The plan gate does not change, and the promotion must not be read as unblocking it.** A
running task under a pending phase already counted as a running phase — a hand-started
task is still a repository executing its plan — so what the phase write adds is the
record and nothing else.

**It is not idempotent, and that is deliberate.** `attempts` counts spawns, not states:
step 4 of the orchestrator leaves a task `in_progress` when its gates run red and sends
it back through step 2, so calling `start` on a running task **is** that retry and spends
an attempt. The report says `RE-STARTED` and names the attempt every time, so a double
call is visible rather than silent. A verb that returned success having written nothing
would freeze the count `blocked` is derived from.

**Refusals, all before any write:** an id that resolves to nothing; a **phase** id (this
verb takes a task, and the phase around that task is promoted by the same write; a phase
with no task to start is entered by the run that enters it); a `done` or `cancelled` task, named
as such — terminal work is not re-opened by flipping a status, and the follow-up is a new
task; a task that is not ready, or a phase another session has claimed, without
`--force --reason` (below); and a start that would
take `attempts` past the task's `maxAttempts`. That last one
refuses rather than writing `blocked` itself: that transition also owes an ADO echo and a
human, both of which belong to the orchestrator, and the refusal names the count and the
ceiling so the caller can make it.

**Readiness is refused, with one recorded way past it.** A task that is not already
`in_progress` and still waits on an unmet reference — its own `blockedBy` or `dependsOn`, or
its phase's `blockedBy` — is refused with exit 2 and nothing written, and the refusal names
each reference the way `/audit:status` does (`_status_facts.unmet_refs` is the one answer both
read; a phase-level blocker reads `<id> (phase)`). `--force --reason "<why>"` is the
recorded way past it, and the `task.start` row keeps it — see
`reference/manifest-conventions.md` → *The operator's words go in unchanged*. The door refuses
`--force` without `--reason`, and `--reason` without `--force`; `--reason -` reads the text off
stdin like every prose flag. A re-start of
a task already `in_progress`
is the retry above and is never refused for readiness — it prints a `NOTE:` naming what is
still unmet. Under `--json` the result carries `ready`, `waitingOn`, `forced` and
`forcedReason`.

**A claim is refused only while its holder may still be live.** On the sharded layout, a phase
whose `claim.sessionId` is not this session's is refused with exit 2 and nothing written only
when the claim's `phase-<id>` lock is still live under another session, or when it is
**unaskable** — no such lock in this clone, or one `judge` could only place by its age, neither
of which says the holder's run has stopped (`_holder_under_claim`) — the refusal names the
claim's session, branch, moment and which of those it is. Otherwise this start **takes the
claim over**: the lock's run was observed to end (`_locks.holder_gone`), or the live
`phase-<id>` lock it names is this run's own (`_locks.held_by_us`) — and the takeover is
recorded (`_claim_plan`); there is nothing here for `--force` to replace. **With no session
id (`$CLAUDE_CODE_SESSION_ID` unset), `claimAction` is `no-session` and nothing is written over
any claim already held** — a claim naming no session answers no later start's question of whose
it is, so a held one stays exactly as it stands rather than being replaced; with none held, none
is written either.

**Taking the `phase-<id>` lock a written claim needs is a second, separate door.** A start that
is about to write a claim takes that lock first (`reference/orchestrator.md` →
*Branch-per-phase*); any live phase lock this run does not hold refuses the start outright,
naming the holder — whether or not the claim check above also had something to say.

**On either refusal, relay it the way `reference/manifest-conventions.md` → *The operator's
words go in unchanged* states.** Forcing a claim refusal replaces the claim with this session's,
with the `task.start` row keeping the replaced session as the `from` of its `claim.sessionId`
row and in its `basis`.

Under `--json` the result carries `claim`, `claimAction` (`none`, `keep`, `take`, `takeover`,
`contested` or `no-session`), `claimReplaced` (the claim this start wrote over), `claimKept`
(the other session's claim this start left standing), `claimHolder` (the liveness
`_phase_holder` read, asked only when another session's claim was in play), `claimTakeoverBasis`
(a `takeover`'s own reason) and `phaseLock` (the `phase-<id>` lock's own state).

**The start that enters a phase warns about what sign-off will ask for** — an empty
`testGate` (sign-off then rests on review alone) and a missing `desiredOutcome` — as
`WARNING: phase entry: ...` lines and `entryWarnings` under `--json`. Never a refusal: an
empty gate is a designed state, and this is the last moment either is cheap to set. A start
inside a phase already running prints neither.

### Subcommand: `done <taskId> --commit <sha>`

Close a task that **landed**. This is `start`'s twin at the other end of the lifecycle,
and it exists because there was no verb for the close: `reference/execute-task.md` →
*Execute the task*, step 4 prescribed two hand `Edit`s — 4b's status and completion
stamp, 4c's SHA — and a hand edit writes wherever the hand goes. Measured in this
repository: one run wrote a task's completion into the phase **shard** and the manifest
**index**, a later `git reset --hard` reverted the index, the shard turned out never to
have carried the marks at all, and the record of three finished tasks survived only in
their commit subjects. Two places for one fact is one place and one lie.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" done P3.2 \
  --commit "$(git -C <gitRoot> rev-parse HEAD)" \
  --descriptive "<one-line impact>" --technical "<what was actually done>" \
  --verified-by "<test names this task added>" \
  [--intent matches|diverges|cannot-tell|not-asked] [--intent-basis TEXT] [--json]

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" done P3.2 \
  --commit "$(git -C <gitRoot> rev-parse HEAD)" --from-return [--json]
```

**`--from-return` is the ordinary close of a task run through the pipeline.** It takes the
outcome, `verifiedBy` (from `testsAdded`) and the red-first block — its word `proved`,
`could-not-prove` or `not-attempted` with the basis verbatim, written onto
`task.redFirst` — from the executor's return filed for the task's current start, and the
intent answer from the reviewer's (below). It is refused, writing nothing, when the
executor's return for the current start is not filed, and beside a typed `--descriptive`,
`--technical` or `--verified-by`: one close takes its account from one place.

**Call it at the END of step 4c, after `git rev-parse HEAD`** — the SHA does not exist
until the commit does. The manifest write then rides along with the next task's commit
or with sign-off, which is exactly what step 4c already prescribes for `task.commit`;
what changes is that one write carries both halves instead of two writes carrying one
each. Do **not** amend.

What it writes — exactly the fields step 4 prescribes, and nothing besides:

- `status: "done"`, `completedAt` stamped at the moment of the call, and `commit` set to
  the SHA you passed.
- `outcome.descriptive` / `outcome.technical` from `--descriptive` / `--technical`, and
  `verifiedBy` from `--verified-by` (a comma list; `--verified-by ""` empties it). **A
  half you do not name is left exactly as it was** — step 4's test-failure arm writes the
  last red gate's reason into `outcome.technical` and the retry brief quotes it from
  there, so a close that rewrote the whole object would delete that on its way to
  recording success. The report says which of them went unrecorded rather than leaving
  you to notice.
- `intentCheck` — the reviewer's own per-task answer to whether the diff does what
  `description` asked (`matches` / `diverges` / `cannot-tell`), bound to the SAME commit this
  call names. **On every close that passes `--commit` the answer is read from the
  reviewer's FILED return** for the task's current start (`file-return`, below), and the
  record names that file in `intentCheck.return`. Without one the close is **refused,
  writing nothing**, unless it says the question was deliberately not put: **`--intent
  not-asked --intent-basis "<why>"`**, the one word no reviewer gives (a two-string edit, a
  reviewer that never answered). A typed `--intent` word that differs from the filed answer
  is refused, `not-asked` included, so a typed word cannot replace an answer a reviewer
  filed; one that agrees with it closes as if it were not typed. A return filed under an
  earlier start does not count. **A `--no-change` close has no diff to bind and keeps the
  rule it had**: `--intent` is optional there, and omitting it records no answer at all —
  which reads apart from a negative one. `not-asked` is refused without `--intent-basis`,
  because a skip with no reason on the record reads exactly like a reviewer call that never
  came back; `--intent-basis` alone, with no `--intent` beside it, is refused too.
  `/audit:phase signoff` and `/audit:status` (on a phase whose sign-off is due) name the
  done tasks that carry **no** answer — `not-asked` is an answer, so it is not among them.
- **Under `review.perTask: phase` — the shipped default — the rule above is replaced.** No
  reviewer runs per task, so a close that passes `--commit`, with or without
  `--from-return`, records **`intentCheck.answer = "deferred"`** itself and **refuses every
  `--intent` word**, `not-asked` included, writing nothing. `deferred` is a word only this
  verb writes; `--intent` does not offer it. The phase review answers the task at sign-off
  (below), and `/audit:phase signoff` and `close-phase.py` refuse while it has not. The one
  exception is a **fix task the plan records as one**: a task `add --fixes` wrote `fixes` on,
  each of whose findings still names it as `fixTask` in its own phase's review, may close
  `--intent not-asked --intent-basis "<why>"`. A `--no-change` close keeps the rule above.
  Which reading a task is held to is recorded on it: `start` writes the phase's
  `reviewPerTask` (the config's value at the phase's first start) onto each task, a `move`
  carries it along, and a close of a task nothing recorded it on takes its phase's, else the
  config's now, and writes it there — so switching the config mid-phase changes nothing
  for a phase already under way. Set `review.perTask: always` to keep the rule above.
- **journal** → one `task.done` row carrying the SHA in its summary and `details`.
  It is deliberately **not** `task.complete`: that action and `task.commit` are derived
  by `hooks/journal-writes.py` from the write itself and step 4c forbids appending them
  by hand, so this row is the verb's own — and it is what records the close on a machine
  where no hook is watching.
- Same index lock, same revalidate-from-disk, same byte-for-byte rollback on findings as
  `add`.

**`--commit` is required, and it is what makes this a record rather than a status flip.**
A `done` task with no SHA is a state `/audit:doctor` already reports, and because `done`
is terminal here nothing in this command can correct it afterwards. The value must be an
object id (7–40 hex): `HEAD`, a branch and a tag all *resolve*, and writing one into a
field the schema calls a SHA leaves a row that means something different next month.

**A task whose answer was that nothing needed to change closes with `--no-change
--reason "<why>"` instead of `--commit`**, and that is the only close without a SHA:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" done P3.2 \
  --no-change --reason "<why nothing needed to change>" [--json]
```

It writes `commit: null` and `outcome.noChange = {reason, examinedAt}`, where `examinedAt` is
the HEAD SHA the task was examined at — the commit the claim was measured against — and is
written `null`, and **said**, when git cannot name one. **A no-change close is refused while the task's declared files show a change since its current start** - a commit or an uncommitted edit - **but it looks no further back than that start**, so work committed under an earlier start and then reopened is not seen, and a task with no commit is never asked for review answers. It is a way past the landing property the README's followed table names (the row on answers not routed around), and its evidence is post-hoc: the commits past `baseRef` that no task records. The `task.done` row carries the reason
in its summary and in `details.reason`. `/audit:doctor`'s *done task(s) carry no commit SHA*
warning leaves such a task out and names it on a line of its own. `--commit` and `--no-change`
together are refused, as are `--no-change` with no `--reason` and a `--reason` on a close
that is not a no-change close. **A bug's fix task is refused a no-change close**: a done fix
task derives its bug `fixed`, and a bug is never fixed without a fix commit — if nothing
needed to change, cancel the task first (`/audit:task cancel <taskId> --reason ...` - `/audit:bug
close` refuses while the bug's task is in progress), then record the verdict on the bug
(`/audit:bug close <bugId> not_a_bug|wontfix`). Everything else about the verb is unchanged — including the
refusal of a task that was never started.

**Refusals, all before any write:** an id that resolves to nothing; a **phase** id (a
phase reaches `done` only through sign-off, which writes a review verdict and a merge
stamp beside the status); a `done` or `cancelled` task, named as such; a missing or
non-SHA `--commit` (with no `--no-change`); a SHA git can be asked about and does not have; a
`--commit` close with no reviewer return filed for the current start and no `--intent
not-asked`, or with a typed `--intent` that differs from the filed answer; under
`review.perTask: phase`, any `--intent` word on a `--commit` close of a task that is not a
recorded fix task; a `--from-return`
close with no executor return filed for the current start; and a task that was
**never started** — `pending` with no attempt recorded means no spawn was ever written
down, so the close would lay a terminal state over a hole, which is also the shape
`/audit:doctor` grades as positive evidence of an edit outside the pipeline. Run
`/audit:task start <taskId>` first.

**A close never vouches for a verdict that no longer holds.** Before any write, `done` — with
`--commit` or with `--no-change` — asks the task's newest recorded gate verdict
(`_verdict_binding.close_refusal`) and refuses, naming the run, on every arm listed in
`_verdict_binding.CLOSE_REFUSING_ARMS` — a red above all, and a green whose declared files
changed since it measured them. A no-change close asks it too: its claim is that the code as it
stands needed nothing, and such a verdict is a measurement of that code saying otherwise. No
recorded run at all, or an `empty-gate` answer, does not refuse: there is no measurement to vouch
for, and the close's `gate:` line says so. The two ways out are a green run recorded on the work,
or `--override-verdict "<why>"` — the flag `commit-task-work.py` takes for the same act — which
closes anyway and is **journaled** as an `audit.verdict.close-overridden` row naming the task,
the run and the reason; with `journal.enabled` false the close is refused, and a row that will
not write rolls the close back. Given with nothing to go over, the flag closes, says it was not
needed, and journals nothing.

**A SHA git could not be asked about is written, not refused**, and the report says so:
with no git on PATH, or in a **shallow** clone where the object is past the cut, a failed
`rev-parse` means the question was never put — and the doctor's remedy for a false
*missing* nulls the SHA, so grading the unasked question as a negative would refuse
honest closes on CI's default checkout and then invite destroying an intact trail.

**Closing the last open task does not close the phase, and nothing here ever will.**
A phase reads `done` only once its sign-off verdict is recorded (`/audit:phase signoff`,
after the review, the test gate and the invariant check) and, for a phase with a branch,
`close-phase.py` has stamped `mergedAt` — the derived status **is** the claim that all of
that happened, and this verb saw none of it. So the last close reports that sign-off is
due (`/audit:review <phaseId>`, then `/audit:phase signoff <phaseId>`) and writes nothing
on the phase. **Nothing refuses a close that leaves a phase
complete-but-unsigned**; the line is the whole of it, and the `pd` group in
`plugins/audit/tests/test_audit_task.py` is what keeps the field untouched in both
directions.

#### `file-return <taskId> --role executor|reviewer` — the one write a returning agent makes

Not typed by a person, and not by an agent either any more: an agent's last act is
`drive-phase.py submit`, which takes the stamp, runs the red-first helper on a `tdd` task and then
runs this verb once with the return on stdin. The agent hands back the one line `submit`
printed.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" file-return P3.2 \
  --role executor < <the return object, as a file>
```

The return arrives as JSON on **stdin**. The verb checks the shape the role's agent
definition declares (`agents/audit-executor.md`, `agents/audit-reviewer.md`) and exits 2
naming every missing or malformed field, writing nothing. It takes **no path**: an id or a
role that reads as one is refused, and the one file it writes is derived from the task id,
the role and the task's current `startedAt` — `<evidence dir>/returns/<taskId>/<start>.<role>.json`,
the text kept verbatim. The create is exclusive, so a **second filing for one task, role
and start is refused** and the first stays byte-identical; a re-start re-stamps `startedAt`,
so a retry files beside the earlier attempt's return rather than over it. A task with no
start, or one already `done` or `cancelled`, is refused. The evidence directory travels in
the close commit, so a clone receives the claim beside the gate row it can be compared with;
an executor return's optional `claims` text becomes its own paragraph of that commit's
message. **What it cannot hold:** the task id and the role are the caller's word — a filing
under the wrong role, or for a task nobody has filed for yet, is not refused.

**A phase review files too:** `file-return <phaseId> --role reviewer --head <sha>`, the head
the phase brief (`audit-lookup.py brief <phaseId> --role phase`) was computed at and prints.
The brief names that filing whatever `review.perTask` reads - with `"tasks": []` when no task
is owed its answers - because the step driver reads the review's findings from the filed
return. It writes `<evidence dir>/returns/<phaseId>/<head>.reviewer.json`
once per head, so a review after fix tasks files beside the earlier one. It refuses, writing
nothing and naming each entry: a return with no `tasks` entry for a task owed its answers (a
task with a commit whose key reads `phase`, not a recorded fix task, whose commit no filed
return answers yet); an entry missing a key of the reviewer's return format or one of the
three answers, or giving `not-asked` with no basis; an entry naming a task outside the phase,
a commit other than the one its task records, or a commit an earlier filed return already
answers. `--head` on a task's return is refused, and a phase return without it is too.
`/audit:phase signoff` reads every return filed for the phase, writes each entry whose
`commit` is the one its task records now onto that task's `intentCheck`, and then refuses —
under `--verdict passed` and `--verdict skipped` alike — while any task owed its answers lacks
one; `close-phase.py` asks the same of the plan's record before it merges.

### Subcommand: `reopen <taskId> --reason "<why>"`

**Under `review.perTask: phase`, a reopen followed by `cancel`, `move` or a `--no-change` close takes a committed task's work off its record before the landing;** nothing refuses the cancel or the move, and a no-change close looks back only to the task's current start. It is a way past the landing property the README's followed table names (the row on answers not routed around), and its evidence is post-hoc: the commits past `baseRef` that no task records.

`--reason` goes in unchanged, by the rule stated under `cancel` below: it reaches the hash-chained journal.

Put a **done** task back to `pending`, with the reason recorded. `/audit:run` offers it when the
step driver reports the task already done; this is the same verb:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" reopen P3.2 \
  --reason "<why the close is undone>" [--json]
```

It resets `status`, `attempts`, `commit`, `completedAt`, `verifiedBy`, `outcome` and
`intentCheck`, puts a linked bug back to `in_progress` with no `fixedIn`, and writes a
`task.reopen` row carrying the reason. **Refused:** a task that is not done, a phase id, and a
task whose phase is signed off (done, or signed off and awaiting its merge) — the new work
there is a new task in an open phase or a bug.

### Subcommand: `block <taskId> --reason "<why>"`

`--reason` goes in unchanged, by the rule stated under `cancel` below: it reaches the hash-chained journal.

Set a task `blocked` and say what it is waiting on. It is the transition the orchestrator makes
when attempts run out (`reference/execute-task.md` → step 2 and step 4) and the one an operator
makes for a dependency **no id can name** — another team's endpoint, a reply nobody has sent —
which `blockedBy` refuses on purpose, because nothing in the plan could ever clear it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" block P3.2 \
  --reason "<what it is waiting on>" [--json]
```

It writes `status: "blocked"` and `blockedReason`, and a `task.block` row carrying the reason.
**`start` clears `blockedReason`** when the task runs again, and its `task.start` row keeps the
old reason as the value it moved from. **Refused:** no reason, a phase id, a done or
cancelled task, and a task already blocked (its reason on record stands — add what changed
with `note`). **The ADO echo is not sent by this verb**; on a plan with a board it says the
echo is owed (`reference/orchestrator.md` → *ADO echo*).

### Subcommand: `note <taskId> --text TEXT`

`--text` goes in unchanged, by the rule stated under `cancel` below: it reaches the hash-chained journal.

Append one dated `{at, text}` entry to the task's `notes[]`. **Append-only, which is why it
reaches a STARTED task**: `scope` refuses to rewrite the `description` of a task that has
started, because its brief is what its attempts were judged against, so a finding that arrived
since goes here, beside the brief, rather than in place of it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" note P3.2 \
  --text "<what was learned>" [--json]
```

One `task.note` row per call. **Refused:** empty text, a phase id, and a `notes` value that is
not a list (an append onto another shape would replace it). A note never changes status.

### Subcommand: `couple --test <path> --sources a,b --basis-run <runId> --basis-head <sha> [--phases id,id]` / `uncouple --test <path>`

Both write `meta.coupling`, the record a derived phase gate reads back to widen itself onto a
test whose own run named a source it depends on. Neither takes a task or phase id — the
positional slot is the manifest, the same way `settle` reads it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" couple \
  --test <the suite's path> --sources src/a.ts,src/b.ts \
  --basis-run <runId> --basis-head <sha> [--phases P2,P3] [--json]
```

`--test` names the entry, and it must read as a suite path the project already recognises
(`tests_add_path` and `is_suite_path` both have to accept it). `--sources` names every file
this test is coupled to, and each one is checked the same way. `--basis-run` is looked up in
the evidence ledger, never merely typed — a run id the ledger does not hold is refused,
because a coupling states what taught it. `--basis-head` is asked of git the same way
`done`'s own SHA is: refused, exit 2, when git can be asked and the SHA resolves to
nothing in this project's repository; written and reported unverified, never refused, when
git cannot be asked at all (no git on PATH, or a shallow clone). `--phases` is checked against
the plan this call is writing into — an id that plan does not hold is refused, exit 2, naming
it. A test coupled for the first time gets a new entry; a test already coupled has its
`sources` WIDENED (unioned) with the ones just named, and its `basis` (`runId`/`head`/`phases`)
and `learnedAt` stay exactly what the first call wrote — a re-couple's own `--basis-run`/
`--basis-head`/`--phases` are still validated, but never written over the first call's basis.
A coupling is a fact that grows and is never silently replaced. A coupling written this way
carries no `lastCaught`: being learned from a miss is not the same as having caught one.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" couple \
  --test <the suite's path> --caught <runId> [--json]
```

`couple --caught` records that an already-coupled test earned its place: the run it names is
looked up in the evidence ledger the same way `--basis-run` is, and it must be a third-place
row (scope `full`) whose runner NAMED this test as failing — a suite list read off a tail
excerpt, or off a step the row marks muted, is not a catch. The entry's `lastCaught` becomes
that row's `ts`, one `coupling.caught` journal row is written, and nothing else on the entry
changes. `--caught` never creates a coupling and never changes `sources` or `basis`.
A catch that is **not newer** than the `lastCaught` already recorded — an older run imported
late, or the same run replayed by a retry — writes nothing and adds no journal row, and exits
0 with a line saying `lastCaught` already records a newer or the same catch: `lastCaught` is the
newest catch and never moves back, and offering it again is not an error. The two timestamps
are compared as moments, never as text, so an offset against `Z` or a fractional second
orders by time. **Refused, exit 2:** a test with no entry, `--caught` beside any of
`--sources`/`--basis-run`/`--basis-head`/`--phases`, a run the ledger does not hold, a row of
any scope other than `full`, a row that did not name this test on such a step, a row whose
name for the test fits several coupled tests at once (a bare `test_c.py` beside two
`*/test_c.py` couplings — it cannot say which one failed, so it credits none), and a row whose
`ts` does not read as a moment (the refusal names it). When the run is not found and some of
the ledger could not be read, the refusal names the files that could not be read in full —
the run may be on the line that was lost — and `--basis-run` refuses the same way.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" uncouple \
  --test <the suite's path> [--json]
```

`uncouple --test` drops the one entry it names. **Refused, exit 2:** `--test` naming a test
`meta.coupling` carries no entry for, and (on `couple`) an empty `--sources`, a missing
`--basis-run`/`--basis-head`, a `--basis-run` the evidence ledger does not hold, a
`--basis-head` that is not a commit SHA or that git can be asked about and does not have, or a
`--phases` id this plan does not hold.
`--sources`, `--basis-run`/`--basis-head`/`--phases` and `--caught` belong to `couple` alone; `--test` is
the one flag the two verbs share.

### Subcommand: `mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId>` / `unmute --test <path>`

Both write `meta.muted`, the quarantine the gate runner reads: a muted suite still runs and its
failure is still recorded, but that failure does not fail the run. These two are its only
writers. Neither takes a task or phase id — the positional slot is the manifest, `couple`'s
own spelling.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" mute \
  --test <the suite's path> --reason "<why it is muted, not fixed>" \
  --owner <who lifts it> --until <YYYY-MM-DD> --bug <bugId> [--json]
```

`--reason` is the operator's own sentence and reaches the plan and the `test.muted` journal row exactly as passed — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*.

**A mute names the bug tracking the failure it hides.** File one with `/audit:bug add` first.
`--bug` absent is refused, exit 2, before anything is read. A `--bug` naming a bug the plan
does not hold is NOT looked up by the verb: the write is revalidated, the validator's own
finding (`meta.muted[n]: bugId ... names no bug in bugs[]`) refuses it, and every written file
is rolled back — **exit 1**, the output a `REFUSED:` line followed by the `FINDING:` line, and
under `--json` one `{ok: false, exit: 1, refused, findings}` object carrying that finding.

`--until` is the last UTC calendar day the mute holds, inclusive — the one reading the
validator and the runner share. An unreadable day, or one already past, is refused, exit 2:
the runner would not honour it. `--test` must read as a suite path the project recognises,
`couple`'s own check. A test already muted is **extended** by a mute whose `--until` is later:
the one entry is rewritten with the new values and a `test.muted` row records the old day. A
re-mute that does not move `until` later is refused, exit 2 — lift it with `unmute` to shorten
it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" unmute \
  --test <the suite's path> [--json]
```

`unmute` removes exactly the entry its `--test` names, with a `test.unmuted` row. A test
carrying no mute is refused, exit 2. **An expired mute is a warning, not a finding**, so a plan that
carries one is not refused by the check every verb runs first: `unmute` and an extending `mute`
run on it like every other verb.

### Subcommand: `cancel <id> --reason "<why>"`

**Under `review.perTask: phase`, cancelling a reopened task whose work was committed takes that work off its record, and nothing refuses it.** It is a way past the landing property the README's followed table names (the row on answers not routed around), and its evidence is post-hoc: the commits past `baseRef` that no task records.

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.

Close a task — or a whole phase — that will **not** be done. The feature was dropped, the
approach was abandoned, the phase ends with whatever landed. This is not failure and it is
not `done`: `cancelled` is the second TERMINAL state (the phase/task twin of a bug's
`wontfix`), and the report files it under **Archived** beside the finished work.

Like `add`, this is a SCRIPT call — `scripts/manifest/audit-task.py cancel <id> --reason "<why>"`,
which takes the index lock itself. Never hand-edit the status: the script is what records
all three things a hand-edit loses — the reason, the moment, and the journal row.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" cancel P3.2 \
  --reason "search rewrite dropped; the endpoint stays as-is" [--json]
```

What it writes:

- **task** → `status: "cancelled"`, `completedAt` stamped (it stopped being work then),
  and the reason into `outcome.descriptive` as `Cancelled: <why>` — the field the report's
  detail row already reads, so no new field is invented for it.
- **phase** → the same status, the reason appended to `summary`, its `claim` released
  (a claim on a finished phase is stale, and the validator says so), **and every task in it
  that is not already finished is cancelled too** — a pending task under a dropped phase is
  a task `/audit:next` would otherwise still offer. **`/audit:phase cancel <phaseId>` is
  where a phase is spelled now**, and this section is the procedure it follows; taking a
  phase id here still does exactly this, as the legacy spelling.
- **journal** → one `task.cancel` / `phase.cancel` row carrying the reason twice over —
  in the row's `summary` sentence and in `details.reason` — so the why outlives the
  session and a reader parsing rows never has to parse prose to recover it. `details`
  is an allow-list, so the second of those is a decision recorded in
  `_journal_io.DETAILS_KEYS` beside the key rather than something a writer chose.
- **ADO** (when linked) → the next echo/sync moves the card to the mapped state,
  `Removed` by default.

**Refusals, all before any write:** an id that resolves to nothing; a missing or blank
`--reason` (a status flipped with no why is exactly the hand-edit this replaces); and a
target that is already `done` or `cancelled` — terminal work is not re-decided here. As
with `add`, the manifest is validated from disk afterwards and **every written file rolls
back** on findings.

Readiness treats a cancelled blocker as settled, so a plan never deadlocks on work nobody
will do — a task that was waiting on the cancelled one becomes ready, and is worth a look
before it runs.

### Subcommand: `scope <taskId> [--files a,b]`

Give a task the files it touches, and optionally its tests, its
description and the three fields that decide how and when it runs:
`--tests-mode tdd|regression|gate-only`, `--tests-add TEXT`
(repeatable — `"<path>: <what it asserts>"`, since the leading path is what
reaches `files`), `--gate CMD` (repeatable), `--gate-clear`, `--description TEXT`
(or `--description -` to read the brief from stdin — see *A brief the shell has
eaten is refused* above, and prefer it whenever the text holds backticks),
`--risk low|med|high`, `--blocked-by ids`, `--depends-on ids`. Runs `scripts/manifest/audit-task.py scope` — the same
lock, the same revalidate-or-roll-back, the same journal row shape as `add`. At least
one of them is required; a call that would change nothing is refused.

**`--risk` / `--blocked-by` / `--depends-on` are the fields nothing could
correct.** `add` sets them, the panel's composition card reaches `model` and
`skills` instead, and every other field of the template already had a route here.
Measured live: a task filed `--depends-on P0.3,P0.4` against tasks parked behind
an environment nobody had created — shipping the describable half of it meant
removing one id, and the only route was `cancel` plus a fresh `add`, losing the
id, the journal continuity and the description somebody had written. `risk` is
the sharpest of the three: it feeds the executor's model floor and whether a
commit needs human confirmation, and it is a judgement made *before* the work was
looked at.

**Empty is a value, not a clear flag.** `--blocked-by ""` and `--depends-on ""`
empty those fields, because a comma list of **ids** has no value that reads as
content — unlike `--gate ""`, which writes a gate holding an empty command. That
is the line `/audit:phase retarget --area ""` already draws for a CSV field, and
it is why there is no `--depends-on-clear`.

**It does not re-derive `model`.** The escalation from `risk: high` to `opus`
happens at creation, when no `--model` was passed; a rescope to `high` leaves the
model where it is and **says so**, because `model` belongs to `/audit:panel` and
`add --model`, and a second writer of it here would journal a change the caller
never asked for while overruling one they had. Pass `--model` on `add`, or set it
in the panel.

**A call that moved `blockedBy` or `dependsOn` reports readiness** — `waiting on:`
or the `/audit:run <taskId>` handoff, the same two sentences `add` prints. That
is the question such a call is asking, and a `--blocked-by` or `--depends-on` id
that resolves to nothing is a validator finding: exit 1, every written file rolled
back. Readiness is the **whole** rule, all four of its terms, and the owning phase's
`blockedBy` is the one this used to miss: a task whose phase is parked prints
`waiting on: <id> (phase)` rather than a handoff nobody could run. Both verbs read
`_status_facts.unmet_refs`, which is the same answer `/audit:status` gives — the two
said opposite things about one manifest for as long as there were two copies of it.

**`--gate-clear` is how a task reaches the EMPTY gate**, and it is here for a reason
that is not `/audit:phase retarget`'s. That verb *replaces* `testGate` too, so the
replacement itself still left the empty gate unspellable; `scope` **replaces**
`tests.gate` outright, and the gap is in the values — no `--gate` value says *none*,
because `--gate ""` writes a
gate holding an empty command, which is a gate that cannot run rather than the absence
of one. It refuses alongside `--gate` exactly as `retarget` does. Measured live: a phase
retargeted to `testGate: []` (nothing in that repo could grade markdown and config) left
its pending tasks holding the `["lint"]` they had inherited at creation, and the only
routes to the state the phase had just reached were a rescope mid-run or the hand edit
`commands/task.md` forbids. An emptied gate is reported as such rather than in silence — the
task then runs no gate command of its own (`run-test-gate.py --task` reads its
`gateBasis: cleared` and answers EMPTY), and the phase's `testGate` at sign-off is
what still grades it.

**Why the verb exists.** `/audit:sync pull sprint` imports tasks with `files: []` and
tells the reader to scope them before running. Nothing could: `add` creates, `cancel`
closes, `move` relocates, and the panel's composition card reaches `skills` and `model`
but not `files`. The only way to obey that instruction was the hand edit `commands/task.md`
forbids for adds — for the reason that applies here too.

**And the cost was not tidiness.** `files` is what `fileIndex` is built from, and
`fileIndex` is what the plan gate matches an edit against. An unscoped phase ran with
its central guard **inert** — not failing, because it had nothing to match.

**Settled work is refused outright, and a started task takes a WIDENING or a new gate.**
A `done` or `cancelled` task has a scope its commit was graded against and its sign-off
accepted, so nothing written here would describe the run that happened — the refusal says
that and points at a new task. Everything short of that is reachable, but once a task has
started — `in_progress`, or put back to `pending` still carrying `attempts` — the changes
it will take are the one that **adds** and the one that points **forwards**: `files` and
`tests.add` may gain entries and never lose them, `tests.gate` may be replaced outright,
and no other field may move at all. `--risk`, `--description`, `--tests-mode`,
`--blocked-by` and `--depends-on` all keep the old refusal, which still points at `cancel`
plus a fresh `add`.

**`--gate` and `--gate-clear` cross that line because a gate is not a scope claim.**
Every other field above is graded **backwards** against work already recorded, which is
what makes only growth safe there. `tests.gate` is read **forwards** and nowhere else —
the gate runner builds the next run's steps from it, an evidence row carries the commands
that **actually ran**, and the pointer cached on the task holds that run's id, verdict and
time — so replacing it moves no recorded row and no cached verdict, in either direction.
Measured live: the field was hand-edited inside a phase shard with a Python one-liner,
three times, because the verb refused and `commands/task.md` forbids that edit. It is **not**
narrowed to a started task with no green run recorded: a task holding a green pointer over
a gate too wide to be worth re-running is the case that costs the most, and that green row
measured the gate that was there rather than the one being written. The change gets its own
report line and its **own journal row**, dated by attempt, beside the widening's — one
summary carries one event, and `audit-journal list` prints summaries alone.

**Append-only is the exact operation that cannot re-judge what already happened**, which
is why it is the one thing on offer. The invariant check grades a task's **recorded**
commit against the task's **current** `files`, so growing that list can only turn a breach
into a pass — while shrinking it can turn a commit that was clean when it was made into a
breach, retroactively, on work nobody can go back and redo. The plan gate reads the same
list forward, so a widening only ever *allows* an edit it was refusing.

**And that is the case the verb exists for.** `reference/execute-task.md` prescribes
`/audit:task scope` for the moment the plan gate refuses a file a running task genuinely
needs — a task which is, by then, `in_progress` with an attempt on it. Measured live: hit
three times in one phase while the guard excluded exactly that state, and the only escape
each time was the hand edit `commands/task.md` forbids. A widening **says when it happened** —
which attempt it landed under, and what it gained — and the journal row carries the same
attempt, because a trail that recorded only the new list would let every earlier record be
read as though the scope had always been this one.

**The fileIndex is re-derived, not appended to.** A scope call takes files away as well
as adding them, and an index that only grew would keep matching edits to a scope the task
no longer claims.

Refuses, each naming the reason: a phase id (it takes a task), an id that is not in the
manifest, a task whose work is settled, a change on a task that has started which is
neither a widening nor a gate, a `--files` entry that cannot be a repository-relative path,
and a call that would change nothing — a lock taken for no
reason is worth saying out loud.

**`--files` is the replacement list, and it is not a delta.** The incremental spelling
neighbouring tools offer — a `+` or `-` in front of each path — is refused rather than
written, on both this verb and `add`: measured live, those prefixes went into the task's
`files` as part of the filenames, into `fileIndex`, into a journal row that recorded it as
legitimate, and the only output was the not-on-disk note below. A leading `/` or `~` and a
`..` segment are refused for the same reason — none of them is a path the plan can key an
index on. **A file that does not exist yet is not one of these**: a task whose `tests.mode`
is `tdd` names the case it is about to author before that file exists, so declaring one
stays legal and stays quiet. It is reported as a note naming the paths, the root that was
searched, and both readings of the silence — a file this task will create, or a scope
resolved against a root these paths are not relative to.

### Subcommand: `move <taskId> --to <phaseId>`

**Under `review.perTask: phase`, moving a reopened task whose work was committed takes that work off this phase's record, and nothing refuses it.** It is a way past the landing property the README's followed table names (the row on answers not routed around), and its evidence is post-hoc: the commits past `baseRef` that no task records.

Relocate a pending/blocked task into another open phase. This is the ONLY sanctioned
way to move a task: a hand-drag keeps the old id, which the validator flags
(`id does not follow its phase's prefix`) and which breaks the ledger join. It is a SCRIPT
call, which takes the index lock itself — it used to be a six-step procedure done with Edit,
and every step of it is now the verb's:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" move P3.2 --to P5 [--json]
```

**Refusals — all BEFORE any write**, in this order:

1. no `--to`; `<taskId>` does not resolve to a task (the refusal lists the task ids), or
   `<phaseId>` to a live phase (the refusal lists the phases, or names the parked proposal
   that reserves the id);
2. the target is the task's current phase (nothing to move);
3. the task is `done` — done tasks are history; re-open it first (`reopen` above), then move it —
   or `cancelled`;
4. the task is `in_progress` — likely a live or interrupted run: finish or `/audit:resume` it first;
5. the target phase is done, signed off or cancelled — the same target-phase refusals
   `/audit:task add` gives, judged only after the task's own status.

A `blocked` task MAY move: it moves **with its blockers** — its own `blockedBy`/`dependsOn`
lists travel unchanged (only references *to its old id* elsewhere are rewritten).

**What it does** (index lock held throughout; in the sharded layout the task body moves between
the two phase SHARDS while `fileIndex`/`bugs[]`/`proposals[]` edits go to the index):

1. **Allocates the new id** from the same allocator `next-id task --phase <targetPhaseId>`
   prints — it counts the whole assembled manifest AND every reserved `proposals[].payload`
   id, and off the development branch it carries the branch suffix (conventions → ID
   allocation / Reserved ids).
2. **Rewrites every reference** to the old id through `_id_refs.rename`, the one list of
   fields that hold an id: every `blockedBy` / `dependsOn` (phases and tasks, parked proposal
   payloads included — the reference most often missed), every `fileIndex` value, every
   `bugs[].taskId`. The task's other fields travel unchanged; `movedFrom` is never rewritten.
3. **Moves the task object** into the target phase's `tasks[]` with its new id and
   `movedFrom: {"id": "<oldId>", "phase": "<oldPhaseId>", "at": "<ISO now>"}`; a task moved
   before keeps its earlier record as `movedFrom.previous`. **Every id in that chain stays
   taken**: the allocator never mints one again, so rows written under an old id cannot attach
   to an unrelated task.
4. **Revalidates from disk** and rolls every written file back on findings.
5. **Journals one `task.move` row** — `fromId`, `toId`, `fromPhase`, `toPhase` — the explicit
   mapping; the completion events stay hook-only.

**What it leaves behind, and says.** The evidence ledger is append-only, so runs recorded
under the old id keep that id; the report counts them, and `/audit:doctor` and
`run-test-gate.py --reconcile` join them to the live task through the `movedFrom` chain. The
report's per-task run history does not: it still lists those runs under the old id. A chain
naming an id a live task holds, or one two chains both claim, is joined by neither reader and
drawn as a validator warning - a verb-made plan reaches neither shape. A `blockedBy`/`dependsOn` on the old id written on **another branch** is not
rewritten here, and surfaces as a validator finding at the merge.

It **reports** the old id, the new id, the number of references rewritten, whether the task is
**ready now**, and the ledger note: *historical ledger rows keep the old taskId — history is
never rewritten; new spend attributes to the new id; `movedFrom` plus the journal's `task.move`
row are what let a reader join the two.*

### Subcommand: `priority <phaseId> <tier|--clear>` — the legacy spelling

**This still works.** It is what `/audit:phase priority <phaseId> <tier|--clear>` was called
before a verb that mutates a phase moved under the command named for the noun it mutates.
Kept so existing transcripts, runbooks and older docs resolve; new work says
`/audit:phase priority`.

**Do that, not something of your own.** Read
`${CLAUDE_PLUGIN_ROOT}/commands/phase.md` → *Subcommand: `priority`* and follow it, passing
the phase id and the tier (or `--clear`) through from `$ARGUMENTS` unchanged. There is no
second procedure here on purpose, and no second invocation either: two spellings reach one
writer, and two copies of a rule is one copy and one lie.

**Say the new name once, in the report — then get on with it.** Something like *"`/audit:task
priority` is the old name for `/audit:phase priority`; both do this."* One line, not a
lecture, and never a refusal to run.

**Why it was renamed.** `phase.priority` is the field —
`${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json` is where that is settled — and there
is no `task.priority` at all. So a command called `task` took a phase id and changed a
phase, and a reader of the command list reasonably concluded the opposite of the truth:
that tasks have priorities and phases do not.

**No removal is scheduled.** When one is, the changelog announces it before it happens —
`/audit:migrate` is the precedent. `COMPATIBILITY.md` counts a new command as a minor
release and makes no promise about taking a spelling away, so the announcement is the whole
contract here.

## Re-running sign-off (`/audit:review`)

`/audit:review <phaseId> [--full]` re-runs sign-off through `drive-phase.py next <phaseId>`, the
recovery path after fixes. What a re-run meets, for a reader who asks:

**The invariant check (sign-off step 3) reads the phase BRANCH.** Re-running sign-off after the
branch was deleted is legitimate, and `verify-invariants.py` will answer `no-basis` for
`branch-history` rather than `clean` — read that as "the evidence is gone", not as a problem with
this run. `meta.merge.deleteBranch` is on by default, so on a phase that already landed this is
the **normal** outcome of a re-run, not a sign that something went wrong.

**Re-running the landing step is safe and says so.** `close-phase.py` asks the ancestry before it
writes anything, so a phase whose branch is already contained in its parent reports
`already-contained`, makes no merge write, and exits 0 - keeping the `mergedAt` it recorded
rather than moving it. A phase that landed and whose branch is already gone reports that and exits
0 too. The sign-off it judges the cleanup by is the phase as the BRANCH holds it, so a phase
signed off in its worktree lands and is cleaned up in one run from the parent's tree. What a re-run WILL still do is the
cleanup the first run could not — a worktree that was dirty then and is clean now, or one the
first run was standing inside. Its `--dry-run` shows exactly that before you commit to it.

**The landing commits the stamp it writes.** `mergedAt` and the stored `done` go into the
parent's copy of the plan, and `close-phase.py` commits them there through
`commit-audit-state.py` (and `commit-manifest-index.py` in a sharded plan), subject `landed on
<parent>`. With the parent checked out nowhere and the main tree on the phase branch, the commit
goes on that branch and the parent is fast-forwarded to it once more. A re-run commits a stamp an
earlier landing left uncommitted, and makes no commit when there is none.
The `landing-committed` invariant - in `verify-invariants.py` and `/audit:status --gate` alike -
reports a landed phase whose stamp is still
an edit in the tree it runs in.

**`--full`** runs the third place after the ordinary sign-off completes, through its one command:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/full-gate.py" <manifest> [--project-dir <dir>]`
— the same command the README's pre-push snippet runs. It runs `run-test-gate.py <manifest>
--full --record` as a subprocess, measured against the whole product rather than this one phase,
streams what the runner prints and exits with the runner's code. Neither script prints the
phase's full-run answer; read it afterwards where it is printed — `/audit:status`'s tests column
(`full whole`, `full provisional (since …)`, `full unknown - <reason>`) and `/audit:doctor`'s
`full run` row (a WARNING naming a PROVISIONAL or UNKNOWN phase with its basis, one OK row when
every merged phase reads WHOLE), both off `_evidence_io.full_status`. `/audit:status` asks git
from `CLAUDE_PROJECT_DIR`, or the directory it runs in when that is unset, so run it from the
project's own checkout. A plan with no
`meta.fullGate` declared prints that the plan names no third place and exits 0; that is not a
failure of this command, it is the plan's own state.

**A red `--full` files what the run taught, and stays red.** After the runner exits non-zero,
`full-gate.py` reads the row it recorded and runs `audit-task.py` itself: a `couple` and a
`bug-add` for each selection miss the runner named, and a `couple --caught` for each coupled suite
it named failing and did not list as a miss (orchestrator → **What a red full run teaches**). Each verb's own lines and exit
code are printed under `[full-gate]`, and so is every reason nothing was learned. The exit is
still the runner's, and the phase's full-run answer is still the one the ledger holds; a filed
miss does not make the red run anything but red. Report the coupling and the bug it filed with
the rest of the sign-off.

## `/audit:phase`'s verbs

What each `/audit:phase` verb does, refuses and why - the explanation behind
`commands/phase.md`, which carries each verb's command line and the rules the main loop follows,
while the step driver prints the rule each step of a run needs at that step.

### 0. Which verb — read off `$ARGUMENTS`, before the manifest is

The FIRST token decides, and the reserved words are `add`, `retarget`, `priority`, `cancel`,
`signoff` and `settle`.
**Any other first token is a phase id**, and the command is the run form below — the
shape this command has always had, unchanged.

**Lexical, never inferred from the plan.** Deciding the verb by asking the manifest
whether the first token happens to name a phase would give one command line two
meanings on two machines, and the argument has to be read before the manifest is even
located. So the rule is about the word, and it is the same word everywhere.

**The one collision, and it is asked rather than guessed.** `phase.id` is a free-text
string in `${CLAUDE_PLUGIN_ROOT}/schema/audit-plan.schema.json` — `P<n>` / `BF<n>` is
the allocation convention (conventions → ID allocation), not a shape the validator
holds — so a hand-written manifest MAY carry a phase whose id is one of the reserved
words. Once the manifest is read, if it names a phase whose id equals the word you
dispatched on, **STOP**: print both readings and ask (AskUserQuestion) which was meant,
then follow the answer. Never resolve it silently and never refuse outright — both
readings stay reachable, one question apart. There is no arity exception either: three
tokens are no more decidable than one when a rule has a carve-out nobody remembers.

### Run a phase — `<phaseId> [--dry-run] [--confirm-high-risk "<your words>"]`

`$ARGUMENTS` = the phase id (plus optional `--dry-run`, `--confirm-high-risk`).

**If `--dry-run` is present:** a read-only preview, then STOP. It prints the phase's tasks with
`audit-status.py --phase <phaseId>` (the drive starts the first READY task in id order and runs
one task at a time, so there are no parallel groups to print), the branch and merge target, and
**what happens after the merge**. On a phase not yet started, `close-phase.py --dry-run` exits 1
saying no branch is recorded and the composed name is not a branch here: that reads as *not
started yet*, never as a refusal of the run.
The branch and the merge target both come from
`resolve-branch.py <manifestPath> --phase <phaseId>` — never composed here — and when the
merge target is not `meta.developmentBranch`, the plan says so: signing off there does not put
the work on the development branch.

**What happens after the merge is `meta.merge`'s answer, and the preview owes it too** — whether
the branch will be merged at all (`auto`), and whether the worktree and the branch go afterwards
(`removeWorktree`, `deleteBranch`). All three default to on, so a plan that says nothing about
merging behaves exactly as it always has; a plan with `auto: false` signs the phase off and leaves
the landing to a human, which the preview must say rather than let the reader assume a merge.
`close-phase.py … --dry-run` prints the whole thing, including the exact git command it would run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/close-phase.py" <manifestPath> <phaseId> \
    --project <projectDir> --dry-run
```

**The landing is stamped in the tree the merge lands in** - the parent branch's checkout - whatever
manifest path is passed, whether the merge is made now or the branch already landed (a re-run, or a
merge made by hand): `mergedAt`, the derived status and the index stub go to that tree's copy,
never to the one inside the phase's own worktree, which is removed moments later. A follow-up the
preview prints (run from the main tree when this one stands inside the worktree) names that
surviving manifest. When the parent branch is checked out in no worktree and the manifest given is
the phase worktree's own copy, the landing has no surviving copy to stamp: close-phase refuses
before merging (exit 2), naming the branch - check it out in a worktree, or run close-phase from
its checkout - so the ref never moves without the record of the landing. With `meta.merge.auto`
false nothing is written, so that run is not refused: it exits 0 and hands over the merge command.

**If `--confirm-high-risk "<your words>"` is present:** the human is answering the high-risk gate
**before** the run instead of during it. Run this FIRST, before the preflight, and print its output
verbatim — in your own reply, inside a fenced block:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/record-risk-confirmation.py" \
    <manifestPath> <phaseId> --confirm-high-risk "<your words>"
```

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.

**Why the flag exists.** The orchestrator's risk gate stops and asks a human before a
`risk: "high"` task's commit, always. An operator running the pipeline unattended has nobody to
ask — asking parks the run for hours — so the run instruction itself gets treated as the
confirmation and the report says so afterwards. That is a safety rule overridden quietly, which is
worse than a stall. This is the third option: the answer is given early and recorded. *Always ask*
stays true; the asking happened earlier, and the trail says who answered and in what words.

**What it covers is a LIST OF TASK IDS, and the command prints it.** The covered set is computed
from the manifest as it stands at that moment — this phase, `risk: "high"`, open work only — and
written into a `risk.confirmed` journal row. **A high-risk task that is not on that list still
stops and asks**, including one whose `risk` became high after the row was written. That is the
whole safety property: an answer that covered any future high-risk task would not be an answer,
it would be the gate deleted with a flag left where it used to be. Say this back to the operator
when you relay the covered list, because a flag named *confirm* reads like a blanket permission
and is not one.

**Refused rather than recorded:** a blank value; a phase with no open high-risk task (a
confirmation with no subject is a standing permission — exit 2, and the message says whether the
phase is genuinely clear or the risk is simply not on the tasks yet); and, exit 1, a journal that
is off or an append that did not land, which means there is **no** pre-given answer and every
high-risk task in the phase goes back to asking. Relay the refusal and ask per task; do not
re-run the run command without the flag and treat that as the same thing.

Otherwise the step driver runs it: `drive-phase.py next <phaseId>`, run again after each
instruction it prints. It takes the phase lock, then works one task at a time in id order - a
recorded gate must not run while another executor edits the tree - each through its executor's
dispatch, its recorded gate, its reviewer where `review.perTask` asks for one, its commit and its
close, and then signs the phase off. **A wave finishing is not a stopping point.** A run that
committed one wave and reported "next up is the next wave" left the command undischarged and sat
idle for a day with nothing wrong - lock held, manifest valid, the rest still ready. The run is
finished when the drive prints `done`, and `/audit:status` reports a phase whose lock is held
while a task is ready as an unfinished run.

**Sign-off measures the phase ONCE, and the order is what buys that: review first, then the fix
tasks its findings become, then the gate.** Carry the reason with the order, because without it
the order reads as arbitrary and gets reordered by whoever is optimising something else — a
reviewer's findings become fix tasks, and a fix task's edits invalidate a gate taken before them,
so a gate run before the review graded a tree that no longer exists and has to be run again.
Gating first is this phase measured twice. **The step driver holds the order on its own path**: it
runs the phase gate only once the triage is answered `sign-off`, after every fix task it added has
closed. A gate run by hand before the review is not refused, and nothing measures whether that
happened: the second run supersedes the first in the evidence ledger and no reader counts the rows
a phase left behind. The steps themselves — what each one checks, the exit codes, what each gate
banner means — are `reference/phase-signoff.md`'s **Phase sign-off** section.

**What a phase run records, and where those records have to end up.** Every task's gate run
is recorded against that task; **Phase sign-off's own gate run is recorded against the
phase**, kept apart from its tasks' so a reader can follow either — the phase's gate and its
tasks' gates measure different work over different files, and merging them would claim a
measurement nobody made. Each task commit and the sign-off commit stage the evidence
directory alongside the journal, for the same reason the journal is staged: a `testEvidence`
pointer that reaches a clone without the row it names points at nothing, and
`verify-invariants.py`'s `evidence-committed` is what says so afterwards.

**A red sign-off gate is where a phase run stops committing.** The phase stays
`in_progress`, nothing is committed, and the rows the gate just wrote have nothing behind
them — a named point in the orchestrator's *Keeping a failed run's record*, where
`commit-audit-state.py` makes them durable without staging any implementation. Read the
gate's own lines before signing off rather than reading the exit code alone: a rewritten
tree and a gate that checked nothing each turn the run red and say which, while
`NO OVERLAP WITH THIS WORK` **moves the exit code not at all** — the gate ran, it passed, and
none of the paths it printed is a file this phase's tasks declare. That last one is reported
and never refused, because the overlap is derived from paths a runner happens to print and a
heuristic that refused would manufacture false refusals. Deciding whether this gate can grade
this work is therefore yours, and the line is what puts the question in front of you — with a
bounded sample of the paths the runner actually printed under it, so you can see whether they
are suites or stack frames without re-running anything.

**`TREE CHANGED OUTSIDE THIS WORK` moves the exit code not at all either.** Paths changed during
the gate that this work does not declare. The bracket describes the whole repository, so a task
running in PARALLEL puts its executor's writes inside every sibling's window; porcelain reports
what moved and never who moved it, so this is reported with both readings named rather than
refused. `GATE MUTATED THE TREE` is the other half — a declared file, which the gate itself was
grading — and that one still refuses.

**`GATE COULD NOT RUN` is not a red suite.** The step reached no verdict, for a reason that is
not the work's: the runner never started (a missing command, a gate entry the shell could not
find), it started and never reached a check (a port it could not bind, a filter that selected no
test file), or the OS ended it - which can come after checks ran, and for a jest worker is read
from jest's own report while other suites passed. Fix the runner and re-run rather than spending
a retry on the task, and do not let it be recorded as the task's failure.

**A runner that prints only SUITE paths still names your work.** `tests/parser.spec.ts` is matched
to `src/parser.ts` — the stem the test is named after, across directories, because `src/` tested
from `tests/` is the ordinary layout. Without that, a jest-shaped runner produced this line on
almost every task while the gate really had exercised the files, and a warning that fires almost
always is one people learn to skip past. The match is deliberately narrow: only test-shaped paths,
only onto the exact stem they carry, so a test named after a *different* file is not coverage. A
false overlap would tell you your work was exercised when it was not, which is the comfort this
line exists to refuse.

### Subcommand: `add "<title>" --outcome "<what success looks like>"`

A new phase and its tasks, planned from the human's request and written in **one
call**. The script takes the index lock itself, so hold no lock by hand around it.

**1. Gather** only what `$ARGUMENTS` and the conversation do not already carry:

- **the outcome** — the one-line `desiredOutcome`. `/audit:status` shows it, task
  subagents receive it, and sign-off must address it. A phase whose success cannot be
  stated in a line is too big; split it.
- **the tasks** — each with a title, a description, the files it edits, and a test mode.
- **the open choices** — every decision the request leaves to whoever implements it (a
  rounding rule, a name, a default). List them rather than settling them silently; the
  phase reviewer asks where a task chose one. Write `[]` when the request leaves none.

Check the alternatives first and say which you ruled out: a parked proposal already
covering the work → `/audit:propose materialize <PROP-id>`, which is a move; an open
phase whose `desiredOutcome` this work serves → `/audit:task add --phase <id>`.

**2. Run it with the plan on stdin**, a quoted heredoc, so planning writes no file of
its own — no scratch path to collide on, and no file write to be refused and fall back
from — and print its line verbatim:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" add --from-file - [--json] <<'PLAN'
{
  "request": "<the request, exactly as the human typed it>",
  "openChoices": ["<a choice the request left open>"],
  "phase": {"title": "<title>", "desiredOutcome": "<one line>",
            "description": "<why and how>"},
  "tasks": [
    {"key": "sum", "title": "<task>", "description": "<what to do>",
     "files": ["src/b.ts"],
     "tests": {"mode": "tdd", "add": ["tests/b.test.ts: <what it asserts>"]}},
    {"title": "<task>", "description": "<what to do>", "files": ["docs/b.md"],
     "dependsOn": ["sum"]}
  ]
}
PLAN
```

**Quote the heredoc word** (`<<'PLAN'`): a bare `<<PLAN` expands `$` and backticks in
the request, and the request is saved as typed. `--from-file <path>` still reads a file
through the same checks; `--from-file -` reads stdin, as `audit-task.py`'s prose flags do.

Optional on the phase: `testGate` (omitted, the plan's `meta.buildCommands`; `[]`, no
gate, so sign-off rests on review alone), `blockedBy`, `area`, `reviewSkill`, and `id`.
Omit `id`: the script takes the **highest** `P<n>` in use and adds one, over live
phases and every id a parked proposal reserves. Over a plan holding `P0`, `P1` and `P3`, the next id is `P4`, and never the `P2` the gap makes look free:
a gap is a phase that happened, and `meta.branch` derives branch names from the id.
Optional on a task: `key`, `outputs`, `risk`, `model`, `skills`, `tests.gate`,
`blockedBy`. A `key` is the name the batch's other tasks use in `dependsOn` or
`blockedBy` before the task has an id; every other reference names an id the plan
already holds.

**3. What it does.** It allocates the phase id and each task's id, resolves every `key`, and writes the
phase, with `request` and `openChoices` on it, and every task in one write — the new
shard and its index stub in the sharded layout, **appended last**, because the written
order is the plan's order. It re-reads the plan from disk and validates once, and on a
finding rolls every written file back byte for byte. Then it journals one `phase.add`
row and one `task.add` row per task. `--verbose` adds the gate and its basis, the open
choices it saved, and the validator's warnings.

**Every refusal comes before any write, and the batch is the thing to fix:** an empty
stdin; a batch that is not JSON or carries a key the batch does not read; a missing request, open-choices
list, title, outcome or task list; a dependency neither the plan nor the batch holds,
named; a task `key` that is already an id; a phase `id` that is live, reserved by a
parked proposal, a task id, or stored in a shard file another phase occupies; and any
other `audit-task.py add` flag beside `--from-file`.

**Which branch are you on? Phases are minted on the development branch.** A phase id is
a branch name, a lock name and a shard name, so two phase branches that each added a
phase would both mint the next `P<n>`. On a phase branch, ask the user before running:
work **needed by the phase in hand** is a task in it (`/audit:task add --phase <that
phase>`); **new work** is parked with the single-phase verb below and `--park`, then
materialized with `/audit:propose materialize` after this branch merges. The first
phase minted on a side branch prints a WARNING naming `--park`; relay it verbatim — it
is addressed to the user.

**One phase with no tasks yet**, or a parked one, is the single-phase verb — the same
template, refusals and rollback:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" add-phase "<title>" \
        --outcome "<what success looks like>" \
        [--park] [--id P7] [--description "<why & how>"] [--area a,b] \
        [--gate "<entry>" ... | --gate-clear] [--blocked-by id,id] [--review-skill NAME] [--json]
```

**A flag belongs to the verb whose alternative in the hint carries it.** One parser
serves every verb, so a pair like `/audit:phase add --files` is refused with exit 2,
and the message names the verb that does read it; relay it rather than retrying.
**`--risk` is one of those here and not on `/audit:task`** — a phase carries no risk and a
task does, so `/audit:phase add --risk` is refused.

**Exit codes:** `0` written. `1` the plan was already invalid, or the write would have
left it invalid and was rolled back. `2` usage — the refusals above. `3` the index lock
is held by a live run — stop; do not take it over. `4` the lock looks abandoned —
confirm with the human (AskUserQuestion), then re-run with `--takeover`.

**Then hand off:** `/audit:phase <newId>` runs it, and `/audit:status` shows it in the plan.

### Subcommand: `retarget <phaseId>`

Correct a phase that already exists: `--gate <entry>` (repeatable), `--gate-clear`,
`--gate-set <entry> ...` (repeatable-in-one-flag), `--gate-drop <entry>` (repeatable),
`--area a,b`, `--outcome TEXT`, `--description TEXT`, `--rename TITLE`. Runs
`scripts/manifest/audit-task.py retarget` — same lock, same revalidate-or-roll-back,
same journal shape as `add`.

**`--gate-set` is `--gate`'s own operation under a name that takes several values at
once** — both REPLACE the gate outright; `--gate-set lint typecheck` and two repeats of
`--gate` write the identical list. An empty `--gate-set` (no value at all, or every value
blank) is refused with the same sentence `--gate-drop`-to-nothing uses below, because a
caller who typed nothing meant the empty gate and not a gate of blank commands — unlike
plain `--gate ""`, which still writes that odd literal, since `--gate-set` exists for a
caller naming several entries at once rather than for one flag repeated.

**`--gate-drop <entry>` narrows the CURRENT gate by name, the other operation.** Every
named entry must already be in the phase's `testGate` — an entry it does not name is
refused, naming the missing entry and the gate as it stands, so a typo is never a silent
no-op. A drop that would leave nothing is refused with **the same empty-gate sentence**:
`an empty gate is --gate-clear, which says so` — that state is reached by SAYING so, not
as a side effect of what got dropped.

**`--rename` is the flag, not `--title`** — the positional slot on this verb is called
`title` and carries the phase id, so a `--title` flag would shadow it.

**And a rename is refused once the phase is on a branch.** A title is not a label here:
`_branch.slugify` turns it into the branch's `{slug}`, so before phase entry the title
decides which branch will be cut and renaming is exactly right. Afterwards the readers
part company — `close-phase.py` and `manage-worktrees.py` prefer the recorded
`phase.branch`, `resolve-branch.py` composes from the title unconditionally — and a
renamed phase would have two names with no reader agreeing on which. Rename before entry,
or leave the title as the record of what the branch was cut for.

**Why a verb and not a flag on `add`.** The values already exist and are wrong.
`/audit:init` and `/audit:sync pull sprint` synthesize a phase and choose its
`testGate`; from that moment the choice was unreachable, and one wrong choice is enough
to make a phase unable to pass its own sign-off. Measured: an imported phase was given
`testGate: ["lint"]` because a build key existed, `lint` on that repo runs a Python
pre-commit suite, and the phase's tasks touched only JSON and Markdown. Every route out
was outside the plugin — a hand edit the plugin forbids, a `buildCommands` value that is
a shell hack, or installing a third-party tool to satisfy a gate the plugin itself
picked.

**`--gate-clear` is the point, not a convenience.** `--gate` replaces, so without an
explicit clear there is no spelling for the EMPTY gate — and the empty gate is a
designed state, not a hole: `audit-task.py:_phase_gate` returns it with a basis, and its
docstring says why it needs one, because *a phase nothing can prove done is a phase
sign-off signs on review alone*. `/audit:phase add --gate` could already reach it for a
NEW phase. An imported one could not, which is what turned a guessed gate into a trap.
The report says so when the gate ends up empty, rather than leaving silence to be read
as breakage.

**Not a done or cancelled phase, and not one whose sign-off is recorded.** Its sign-off
was given against the gate it had, and moving that afterwards rewrites what the sign-off
attested - which holds as much for a phase signed off and still awaiting its merge as for
one that reads done. A `pending` or `in_progress` phase with no verdict recorded - one only
awaiting sign-off included - is exactly the case this verb is for.

**Retargeting changes what the next run measures and rewrites nothing that already
happened.** A recorded run is graded by the gate it ran under, and its ledger row keeps the
steps it actually ran — so the phase's `testEvidence` goes on pointing at a run of the old
gate until a new one is recorded, which is the honest reading and not staleness to repair.
A phase whose gate has been cleared records nothing at all: the runner reports the EMPTY
gate and returns before writing a row, so the report and the panel read the phase — and
every task in it that declares no `tests.gate` of its own — as `No gate configured`,
*nothing could have run*, rather than as a run that answered nothing.

Any TWO of `--gate`, `--gate-clear`, `--gate-set` and `--gate-drop` together are refused:
two answers about one field, and guessing which was meant is the fault this closes.
`--area` with an empty value REMOVES
the key rather than writing `null`, because the conventions default it to absent and a
`null` would make an untagged phase claim to have considered the question.

### Subcommand: `priority <phaseId> <tier>` (or `priority <phaseId> --clear`)

Say which phase the pipeline should reach for first. Until this verb the order was implicit
in the array — `phases[]` as written, then task id inside a phase — so "run this one next"
meant physically moving the phase, a structural edit of the whole file that nobody performs
in flight.

**It re-sorts only work that is ALREADY ready.** A priority never makes an unready task ready
and never skips a dependency: a pinned phase still waiting on its `blockedBy` is skipped, and
`/audit:status` prints the note saying so and naming the task that ran instead. It is a wish
about the schedule, not a permission.

This is a SCRIPT call — it takes the index lock itself, so hold no lock by hand around it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/set-priority.py" \
  <manifestPath> P5 1 [--force] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/set-priority.py" \
  <manifestPath> P5 --clear
```

- **Tier 1 is unique**; 2, 3, 4 … are shared. Without `--force` a second holder of tier 1 is
  refused and the refusal **names the phase that already has it** — relay that name, and offer
  clearing it or picking another tier before reaching for `--force`. With `--force` both are
  written and the one that comes FIRST in the manifest wins; the validator says so as a warning.
- **No priority at all means unprioritised** — the phase sorts after every pinned one and keeps
  its written position among its peers. Clearing a pin is `--clear`, which removes the key; there
  is no "priority 0".
- **`priority.maxTier`** in `.claude/audit.config.json` is advisory. A phase pinned above it keeps
  the tier it was given and simply sorts after every tier at or under the maximum — nothing is
  clamped, and the command says so.
- The value lives on the **index stub** in the sharded layout, so one file is written and a phase
  run editing its own shard cannot collide with it.

**Exit codes:** `0` written (or already that value — it says so and writes nothing). `1` the
manifest was already invalid, or the write would have left it invalid and was rolled back.
`2` unknown phase, a tier that is not a positive integer, or a second holder of tier 1 without
`--force`. `3` the index lock is held by a live run — stop; do not take it over. `4` the lock
looks abandoned — confirm with the human (AskUserQuestion), then re-run with `--takeover`.

**Display order does not change.** `/audit:status`, both reports and the panel keep showing the
plan in the order it was written — the written plan IS the plan. The pin shows as a badge on the
phase row and decides which READY task comes first.

**`/audit:task priority <phaseId> <tier|--clear>` is the legacy spelling** and still does exactly
this. It is documented in `${CLAUDE_PLUGIN_ROOT}/commands/task.md`; new work says
`/audit:phase priority`, because the field is `phase.priority` and no task has one.

### Subcommand: `signoff <phaseId> --verdict passed|skipped --summary TEXT`

**A phase's status is derived**: it reads `done` once every task is terminal, sign-off is
recorded, and - for a phase with a branch - that branch has merged. This verb records the
sign-off and then stores the status it derives, so a reader of the field alone reads it too:
`done` now for a phase with no branch; for one with a branch, `close-phase.py` stores it when it
stamps the merge. Run it at the step of `reference/phase-signoff.md` that used to say "set
`phase.status = done`", once the review and the gates it lists have passed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" signoff <phaseId> \
        --verdict passed|skipped --summary "<what the phase did, and how it met its outcome>" \
        [--review-outcome "<the review's one-line result>"]
```

It writes `review.status` (the verdict), `review.outcome`, `summary`, the status that record
derives (on the shard and, sharded, the index stub), clears `claim`, and appends a
`phase.verdict` journal row, under the index lock with revalidate-or-roll-back (`phase.signoff` is
the row the journal-writes hook derives once the phase reaches done). It refuses a phase
with open work (naming the open tasks), a phase with no task, one already signed off, and one
already `done` or `cancelled`. Its output says what the phase now reads: `done` for a phase with no
branch, and "done once `<branch>` lands" for one with a branch - `close-phase.py` then merges it
and stamps `mergedAt`, which completes the derivation. `--summary` and `--review-outcome` are the
operator's and the reviewer's words: pass them verbatim, or `-` to read them off stdin.

`--verdict` is the reviewer's call and has no default. `skipped` is honest where no review ran -
say so in `--summary` - and is never a way to sign off work nobody looked at as if it had passed.

**`passed` needs the gate run it rests on.** The verb refuses `--verdict passed` unless the
phase's newest recorded gate run binds its work — the rule a task commit is bound by, which grades
a repeated verdict against the run it repeats and leaves the recorder's own writes out — and
prints the gate call that supplies one. A phase whose gate declares no entry is bound to no run.
Where no gate run can back the verdict, pass `--no-evidence-reason "<why>"`: it is the operator's
words, recorded verbatim on `review.noEvidenceReason` and shown where the evidence badge's basis
goes. It is not a run, so `--fail-on no-test-evidence` still names such a phase. `skipped` needs
neither.

#### The review's own record — findings, their fixes, and a text correction

Sign-off's review step records what the reviewer found before the verdict is written, and that
record has three writes of its own, each a script call with a journal row, under the index lock
with revalidate-or-roll-back. They are not `/audit:phase` subcommands; `reference/phase-signoff.md`
step 1 is where they are run.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" finding <phaseId> \
        --severity low|med|high --file <path[:lines]> --issue - --resolution "<the change>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" resolve-finding <findingId> \
        --fix-task <taskId> [--commit <sha>]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" correct <phaseId> \
        [--review-outcome TEXT] [--summary TEXT]
```

`finding` appends one entry to `review.findings` in the schema's shape, with the id allocated as
`<phaseId>-R<n>`, and journals `review.finding`. It refuses, before any write, a finding missing
a field and a severity outside `low|med|high`. `resolve-finding` writes the fix task and its
commit onto the finding — the task's recorded commit, or `--commit` for one it has not recorded —
and journals `review.resolve`; a fix task that is not `done`, or has no commit, has not landed,
and is refused. `finding --findings-file PATH|-` records a whole review's findings in one write
and is the form to use for more than one: the per-finding form takes the index lock per call, so
run those calls one at a time. `finding` refuses a phase that has already landed (`mergedAt` set);
on a phase signed off but not landed it records the finding and says it came after the verdict.
`reopen` on a fix task takes its commit back off every finding that recorded it.
`correct` rewrites the review's outcome or the phase's summary on a phase that already carries a
verdict, and journals `review.correct`; it never touches the verdict or its `phase.verdict` row,
and `correct --verdict` is refused as a flag the verb does not read.

**The `[findings: …]` tally at the end of `review.outcome` is derived**, by these three verbs and
by `signoff --review-outcome`, from `review.findings` as it stands after the write. The text
before it is kept verbatim; a tally typed at its end is replaced by the derived one.

#### A group of phases built on one branch — `signoff <P1,P2,...> --branch NAME`

Phases whose work was built on **one combined branch** record no branch and no `baseRef` of their
own, so the single-phase sign-off has no diff to review and `close-phase.py` has no name to land.
The same verb signs them off together; it is a flag here rather than a verb of its own because it
writes the single sign-off's record — plus each member's `branch` and `baseRef`, and the carrier's
evidence pointer on the other members — under the single sign-off's refusals plus the group's.
Preview first — it writes nothing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" signoff P1,P2 \
        --branch <combined-branch> --plan
```

It prints the whole sign-off with the command each step runs, and
`reference/phase-signoff.md` → *Signing off a group* is the procedure: **`--bind`** records each
member's branch and fork point first, so the invariants run grades them; the **review is scoped by
the tasks' `commit`s**, which must be every commit the branch carries past its fork (or a member's
journaled audit-state or index commit); **one gate run** over the union of the members'
`testGate`, carried by the member whose gate holds all of it and owning every member's files
(the gate's `--also`); **one invariants run**; the record, which needs that run to be
current for `passed`; the commit — sharded, one `commit-audit-state.py` per member and then the
index; single-file, one; and **one
`close-phase.py --branch` per phase** — every one but the last keeps the branch and its worktree,
because the first landing merges the whole branch. It refuses — naming every reason — a member with
open work or already signed off, a member recording another branch, members that resolve to
different parents, a `--branch` that is that parent, a finished task with no `commit`, a commit
the branch does not carry (naming `repair-commits.py` for a rebase), a commit it carries that no
member records - a merge counts only when its tree is the automatic merge of its parents,
recomputed with `git merge-tree` (git 2.38+; a merge it cannot recompute is refused as not
asked, never as an edit) - and `--accept <sha> --reason "<why>"`, which takes a hex SHA naming
exactly one commit on the branch, takes one into the review, recorded on every member and shown
beside the sign-off — and a union no member's gate holds (`/audit:phase
retarget` gives one member the missing entries).

### Subcommand: `settle`

**Stores every derived value a plan carries stale.** A plan signed off, merged or closed before
the verbs stored the derived status — or edited by hand since — reads correctly to every surface
that derives, and wrongly to every reader of the stored field alone: an older plugin's hooks,
`jq`, an agent reading the file. `validate-manifest` warns about each such value (a warning, never
a finding) and names this command:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" settle
```

It stores a phase's derived `status`, a bug's derived `status` and `fixedIn`, and re-mirrors any
index stub fallen behind its shard — under the index lock, revalidated, rolled back on findings,
with one `plan.settle` journal row naming each value it moved. It only ever moves a value towards
what the derivation already answers, so a stored `done`/`cancelled` and a person's
`wontfix`/`not_a_bug` are never touched. A plan with nothing stale is reported as such, with what
was examined, and nothing is written. Show the validator's warning to the human and let them
decide when to run it; it is the plan owner's write, not a run's.

### Subcommand: `cancel <phaseId> --reason "<why>"`

**The operator's words go in VERBATIM** — see `reference/manifest-conventions.md` → *The operator's words go in unchanged*. This value reaches the hash-chained journal, so a paraphrase makes the trail guarantee a sentence its subject never wrote.

Close a phase that will **not** be done — the feature was dropped, the approach was
abandoned, the phase ends with whatever landed. Not failure and not `done`: `cancelled`
is the second TERMINAL state, and the report files it under **Archived** beside the
finished work.

**The procedure is *`/audit:task`'s verbs* → *Subcommand: `cancel`* in this file,**
followed with the id fixed to a phase id. There is no second copy of it here
on purpose: one writer means one description of what it writes, what it refuses and what
it rolls back, and two copies of that is one copy and one lie. The cascade to the work
still open inside the phase, the released claim and the journal row are all stated there.

**What this spelling adds is a narrowing.** `<phaseId>` must resolve to a **phase**. An id
that resolves to a task → **refuse before any write**, and name the spelling that takes
one: `/audit:task cancel <taskId> --reason "<why>"`. A command called `phase` mutating a
task is the same noun/verb mismatch this spelling exists to remove, so it is refused
rather than accepted quietly.

**`/audit:task cancel <phaseId>` still does exactly this** — the legacy spelling for a
phase, kept so existing transcripts and runbooks resolve. New work says
`/audit:phase cancel`.
