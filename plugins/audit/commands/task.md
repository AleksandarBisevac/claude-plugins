---
description: Add a tracked task to the audit manifest — every answer is a flag, and the dialogue only covers what the caller did not pass — promote one to running, close one that landed, move one between phases, or cancel work that will not be done. `add` allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates; `start` promotes a task to in_progress so the plan gate resolves its files, without spawning anything; `done` closes it against the commit its work landed in, writing status, completedAt, commit, outcome and verifiedBy in one write; `move` renumbers a task into another phase, rewrites every reference, and records a chained task.move journal row; `cancel` closes a task — or, as the legacy spelling of `/audit:phase cancel`, a whole phase — as terminal-but-not-done, recording the reason, the moment and a journal row. `priority` is the legacy spelling of `/audit:phase priority` and still works.
argument-hint: 'add "<title>" [--phase <id>] [--description TEXT] [--files a,b] [--outputs pat,pat] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--risk RISK] [--model NAME] [--skills a,b] [--blocked-by ids] [--depends-on ids] | start <taskId> | done <taskId> --commit <sha> [--descriptive TEXT] [--technical TEXT] [--verified-by t1,t2] [--intent ANSWER] | scope <taskId> [--files a,b] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--description TEXT] [--risk RISK] [--blocked-by ids] [--depends-on ids] | move <taskId> --to <phaseId> | cancel <id> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest, promote one, close one, move one between phases, or cancel one

**`$ARGUMENTS`**: subcommand `add` followed by a quoted title and any of the
flags in the `argument-hint` above;
or subcommand `start` followed by a task id;
or subcommand `done` followed by a task id and `--commit <sha>`;
or subcommand `scope` followed by a task id and any of its flags;
or subcommand `move` followed by a task id and `--to <phaseId>`;
or subcommand `cancel` followed by an id and `--reason "<why>"`;
or subcommand `priority`, the legacy spelling covered at the end of this file.
Unknown/empty subcommand → print usage and stop.

**The flags ARE the interface; the dialogue is the fallback.** Every answer the
`add` and `scope` sections gather is a flag on `scripts/manifest/audit-task.py`, so a
caller who already holds the specification passes it and is asked nothing — step 2's
*ask only for what's missing* is what happens to whatever is left. The hint above used
to advertise `--phase` alone, and what that cost was measured live: an operator holding
files, gate, risk, tests-mode and description was taken through a round of
`AskUserQuestion` per value, and every question that did not need asking is another
chance to **paraphrase** a value the caller had already decided — the defect `--reason`
had (see *The operator's words go in VERBATIM* below).

**A flag belongs to the verb whose hint carries it, and passing it to another one is a
usage error.** One `argparse` parser serves every verb of the writer script, so it accepts every
flag on every one of them — and each verb's writer only ever read its own subset, so
half the pairs used to be accepted, write nothing and report success with exit 0
(`scope --outcome`, `add --id`, `add-phase --risk`, `retarget --files`). Those now exit
2 with a message naming the verb that does read the flag. **Relay that message rather
than retrying**: it is telling you which command you meant.

**`priority` is deliberately absent from the `argument-hint` above** while remaining a
working subcommand. The hint is what a reader is offered when they type the command, and
offering the old spelling there is how the old spelling keeps being learned — the
opposite of what an alias is for.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init` (or the starter template).
`add` writes through `scripts/manifest/audit-task.py`, which takes and releases the **index lock**
itself; hold the lock by hand (conventions → Concurrency lock) only around writes YOU make
with Edit — which is now the `move` subcommand and nothing else. **Creating a phase is
`/audit:phase add` and is no longer done here by hand** (see step 1).

**In the sharded layout, a write here can leave the shared index sitting dirty beside the
phase shard it also touched** — `add-phase` always does; `add`/`scope`/`retarget`/`cancel`/
`start`/`done` do it whenever a mirrored stub key (`status`, `title`, …) or `fileIndex` moves.
A task commit will not carry that index (`orchestrator.md` step 4c refuses it on purpose, so
two phases can merge without a conflict there), so it needs its own commit —
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/commit-manifest-index.py" <manifestPath>
<phaseId>` lands it alone, under the same lock. **The script prints this itself, naming that
exact command, the moment its own write leaves the index dirty** — read it off the output
rather than remembering the rule here.

## Subcommand: `add "<title>" [--phase <id>]`

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
     `in_progress` phase, or exits 2 NAMING the choices. On that exit 2, ask
     (AskUserQuestion): one of the named phases, or **new phase**. A new phase is
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
     still grades it.
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
   - `--blocked-by` / `--depends-on` — comma-separated ids (omit when none).
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

### The task gate is derived, and the report says from what

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
`tests.gateBasis` — `tests.add`, `files`, `phase-no-spelling`, `phase-no-paths`, or
`declared`/`cleared` for the two flags. The sentence is for a person and is gone after
one screen; the word is what `validate-manifest.py` reads when it asks whether a task
carrying its phase's gate verbatim is holding a default or an answer. It is silent on
`phase-no-spelling` (this project records no path-scoped spelling, so there is nothing to
narrow with) and on `declared` (a caller named these commands), and it names everything
else — including a task that records no basis at all, which is what a hand-written or
generated plan carries.

**`scope --gate` is how an existing task answers that line.** It rewrites `tests.gateBasis`
to `declared`, and it does so **even when the command list does not move** — declaring the
wide gate outright is exactly the call an operator makes here, and a verb that compared
lists alone would report "already reads that way", write nothing, and leave the only
remaining route a sentence in the `description` that no rule opens.

### A brief the shell has eaten is refused

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

**The route out is `--description -`**, and it is the fix rather than a bypass: the
brief is read from **stdin**, which no shell rewrites and which this stores verbatim.
`-` where a value goes means stdin throughout this plugin — `scripts/manifest/check-ado-item.py`
and its ADO siblings read a payload the same way — so there is no `--description-file`
to learn.

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

## Subcommand: `start <taskId>`

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
spawns, and the hand edit this file forbids everywhere else.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" start P3.2 [--json]
```

What it writes — exactly the fields `reference/execute-task.md` → *Execute the task*,
step 2 prescribes as an orchestrator `Edit`, and nothing besides:

- `status: "in_progress"`, `startedAt` stamped at the moment of the call, and
  `attempts` incremented.
- **the phase around it, when that phase is still `pending`** — `status` and a `startedAt`
  of its own, from the same instant, in the same write. Until this, the control panel's
  save was the only thing in the plugin that promoted a phase at all, so a plan driven
  entirely from the command line left every phase pending and recorded nowhere when its
  work began. The phase's rows come back under `healed`, apart from `changes`, which is
  the task's own fields. A phase already running is left alone, and one that already
  carries a `startedAt` keeps the moment it recorded.
- **journal** → one `task.start` row whose `details.changes` names each field with the
  value it held, plus `details.attempt` — both keys the `_journal_io.DETAILS_KEYS`
  allow-list already carries, so nothing is written that the trail would drop in silence.
  A phase the write promoted is named in the row's summary.
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
task; and a start that would take `attempts` past the task's `maxAttempts`. That last one
refuses rather than writing `blocked` itself: that transition also owes an ADO echo and a
human, both of which belong to the orchestrator, and the refusal names the count and the
ceiling so the caller can make it.

**Readiness is reported, never enforced.** A task with unmet `blockedBy`/`dependsOn` is
still promoted, with a `NOTE:` naming what it waits on — `/audit:run` is where readiness
decides a spawn, and the case this verb exists for is a task whose edits are being denied
right now. **Nothing refuses a promotion of unready work**, here or in the script; the
note is the whole of it.

## Subcommand: `done <taskId> --commit <sha>`

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
  [--intent matches|diverges|cannot-tell] [--json]
```

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
- `intentCheck` from `--intent` — the reviewer's own per-task answer to whether the diff
  does what `description` asked (`matches` / `diverges` / `cannot-tell`), carried into the
  SAME commit this call already names. **Omitted means no answer was recorded, never
  agreement** — a close that received none reads apart from one that received a negative,
  which is the whole reason this is its own field rather than folded into `outcome`.
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

**Refusals, all before any write:** an id that resolves to nothing; a **phase** id (a
phase reaches `done` only through sign-off, which writes a review verdict and a merge
stamp beside the status); a `done` or `cancelled` task, named as such; a missing or
non-SHA `--commit`; a SHA git can be asked about and does not have; and a task that was
**never started** — `pending` with no attempt recorded means no spawn was ever written
down, so the close would lay a terminal state over a hole, which is also the shape
`/audit:doctor` grades as positive evidence of an edit outside the pipeline. Run
`/audit:task start <taskId>` first.

**A SHA git could not be asked about is written, not refused**, and the report says so:
with no git on PATH, or in a **shallow** clone where the object is past the cut, a failed
`rev-parse` means the question was never put — and the doctor's remedy for a false
*missing* nulls the SHA, so grading the unasked question as a negative would refuse
honest closes on CI's default checkout and then invite destroying an intact trail.

**Closing the last open task does not close the phase, and nothing here ever will.**
`phase.status = "done"` is written only by the last step of sign-off, beside
`phase.review.status`, `phase.review.outcome` and `mergedAt` — the status **is** the claim
that review, the test gate, the invariant check and the merge all happened, and this verb
saw none of them. So the last close reports that sign-off is due (`/audit:review
<phaseId>`) and leaves the field alone. **Nothing refuses a close that leaves a phase
complete-but-unsigned**; the line is the whole of it, and the `pd` group in
`plugins/audit/tests/test_audit_task.py` is what keeps the field untouched in both
directions.

## Subcommand: `cancel <id> --reason "<why>"`

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

## Subcommand: `scope <taskId> [--files a,b]`

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
that is not `/audit:phase retarget`'s. That verb *appends* to `testGate`, so the append
itself left the empty gate unspellable; `scope` **replaces** `tests.gate` outright, and
the gap is in the values — no `--gate` value says *none*, because `--gate ""` writes a
gate holding an empty command, which is a gate that cannot run rather than the absence
of one. It refuses alongside `--gate` exactly as `retarget` does. Measured live: a phase
retargeted to `testGate: []` (nothing in that repo could grade markdown and config) left
its pending tasks holding the `["lint"]` they had inherited at creation, and the only
routes to the state the phase had just reached were a rescope mid-run or the hand edit
this file forbids. An emptied gate is reported as such rather than in silence — the
task then runs no gate command of its own, and the phase's `testGate` at sign-off is
what still grades it.

**Why the verb exists.** `/audit:sync pull sprint` imports tasks with `files: []` and
tells the reader to scope them before running. Nothing could: `add` creates, `cancel`
closes, `move` relocates, and the panel's composition card reaches `skills` and `model`
but not `files`. The only way to obey that instruction was the hand edit this file
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
three times, because the verb refused and this file forbids that edit. It is **not**
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
each time was the hand edit this file forbids. A widening **says when it happened** —
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

## Subcommand: `move <taskId> --to <phaseId>`

Relocate a pending/blocked task into another open phase. This is the ONLY sanctioned
way to move a task: a hand-drag keeps the old id, which the validator flags
(`id does not follow its phase's prefix`) and which breaks the ledger join. This is a
**structural** mutation — take the **index lock** (conventions → Concurrency lock)
around every write below and release it before reporting.

**Refusals — all BEFORE any write** (check in this order; on refusal print why and stop):

1. `<taskId>` does not resolve to a task, or `<phaseId>` to a phase → refuse, list what exists.
2. Target phase == the task's current phase → refuse (no-op; nothing to move).
3. Task `status == "done"` → refuse: done tasks are history. Offer the `/audit:run <taskId>`
   **re-open** path first (it resets status/commit/outcome under its own guards); move only
   after that has run.
4. Task `status == "in_progress"` → refuse: likely a live or interrupted run — point to
   `/audit:resume`, or to the human-confirmed re-execution path in `run.md`, before any move.
5. Target phase `status == "done"` → refuse (done phases are immutable history — same rule
   as `add`).

A `blocked` task MAY move: it moves **with its blockers** — its own `blockedBy`/`dependsOn`
lists travel unchanged (only references *to its old id* elsewhere are rewritten, step 3).

**Steps** (index lock held throughout; in the sharded layout the task body moves between
the two phase SHARDS while `fileIndex`/`bugs[]` edits go to the index):

1. **Allocate the new id** `<targetPhaseId>.<n>` — `n` = highest existing numeric suffix in
   the target phase + 1, computed over the **whole assembled manifest AND every reserved
   `proposals[].payload` id** (conventions → ID allocation / Reserved ids).
2. **Move the task object** into the target phase's `tasks[]` with its new id, adding
   `movedFrom: {"id": "<oldId>", "phase": "<oldPhaseId>", "at": "<ISO now>"}`. Remove it
   from the source phase. All other fields travel byte-for-byte.
3. **Rewrite every reference** to the old id, across the index AND all shards:
   - every `blockedBy` / `dependsOn` entry equal to `<oldId>` → `<newId>` (phases and tasks);
   - every `fileIndex` value array: `<oldId>` → `<newId>`;
   - every `bugs[].taskId` equal to `<oldId>` → `<newId>` (the task's own `bugId` travels with it).
4. **Record the move** — the explicit mapping row, appended by YOU via the CLI (this is the
   one journal action a command writes; the completion events stay hook-only):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-journal.py" append --action task.move \
           --target <manifest rel> \
           --summary "<oldId> -> <newId> (<oldPhase> -> <newPhase>)" \
           --details '{"fromId":"<oldId>","toId":"<newId>","fromPhase":"<oldPhase>","toPhase":"<newPhase>"}'
   ```
5. **Revalidate**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` —
   fix and re-run until clean (the id-prefix warning for the moved task must be gone).
6. **Release the lock**, then **report**: old id, new id, target phase, whether the task is
   **ready now** (readiness rule), and this ledger note verbatim in spirit:
   *historical ledger rows keep the old taskId — history is never rewritten; new spend
   attributes to the new id; `movedFrom` plus the journal's `task.move` row are what let a
   reader join the two.*

## Subcommand: `priority <phaseId> <tier|--clear>` — the legacy spelling

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
