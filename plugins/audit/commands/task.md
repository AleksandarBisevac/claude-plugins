---
description: Add a tracked task to the audit manifest — every answer is a flag, and the dialogue only covers what the caller did not pass — promote one to running, close one that landed, move one between phases, or cancel work that will not be done. `add` allocates the id, initializes all orchestrator fields, updates fileIndex, and revalidates; `start` promotes a task to in_progress so the plan gate resolves its files, without spawning anything; `done` closes it against the commit its work landed in, writing status, completedAt, commit, outcome and verifiedBy in one write — or, with `--no-change --reason`, closes a task whose answer was that nothing needed to change; `reopen` puts a done task back to pending with the reason recorded; `move` renumbers a task into another phase, rewrites every reference, and records a chained task.move journal row; `block` sets a task blocked with the reason beside the status; `note` appends a dated note, the one addition a started task takes; `cancel` closes a task — or, as the legacy spelling of `/audit:phase cancel`, a whole phase — as terminal-but-not-done, recording the reason, the moment and a journal row. `priority` is the legacy spelling of `/audit:phase priority` and still works.
argument-hint: 'add "<title>" [--phase <id>] [--description TEXT] [--files a,b] [--outputs pat,pat] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--failing-from RUNID] [--risk RISK] [--model NAME] [--skills a,b] [--blocked-by ids] [--depends-on ids] [--dry-run] | start <taskId> [--force --reason "<why>"] | done <taskId> [--commit <sha>] [--no-change --reason "<why>"] [--descriptive TEXT] [--technical TEXT] [--verified-by t1,t2] [--intent ANSWER] [--intent-basis TEXT] [--override-verdict TEXT] | reopen <taskId> --reason "<why>" | scope <taskId> [--files a,b] [--tests-mode MODE] [--tests-add TEXT] [--gate CMD] [--gate-clear] [--description TEXT] [--risk RISK] [--blocked-by ids] [--depends-on ids] | move <taskId> --to <phaseId> | block <taskId> --reason "<why>" | note <taskId> --text TEXT | couple --test <path> --sources a,b --basis-run <runId> --basis-head <sha> [--phases id,id], or --test <path> --caught <runId> | uncouple --test <path> | mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId> | unmute --test <path> | cancel <id> --reason "<why>"'
allowed-tools: Read, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:task — add a task to the manifest, promote one, close one, re-open one, move one between phases, block one, note on one, or cancel one

**`$ARGUMENTS`**: subcommand `add` followed by a quoted title and any of the
flags in the `argument-hint` above;
or subcommand `start` followed by a task id;
or subcommand `done` followed by a task id and `--commit <sha>` (or `--no-change --reason "<why>"`);
or subcommand `reopen` followed by a done task's id and `--reason "<why>"`;
or subcommand `scope` followed by a task id and any of its flags;
or subcommand `move` followed by a task id and `--to <phaseId>`;
or subcommand `block` followed by a task id and `--reason "<why>"`;
or subcommand `note` followed by a task id and `--text TEXT`;
or subcommand `couple` followed by `--test <path> --sources a,b --basis-run <runId> --basis-head <sha>` (or by `--test <path> --caught <runId>`);
or subcommand `uncouple` followed by `--test <path>`;
or subcommand `mute` followed by `--test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId>`;
or subcommand `unmute` followed by `--test <path>`;
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
Every subcommand here writes through `scripts/manifest/audit-task.py`, which takes and
releases the **index lock** itself — `move` included, which used to be the one procedure
done with Edit — so no write in this file is made by hand, and no lock is held by hand.
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

### A failed-first fix task is gated on what the run named

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
read; a phase-level blocker reads `<id> (phase)`). `--force --reason "<why>"` starts it anyway:
that is the route for promoting a task by hand so the plan gate resolves its files, and the
`task.start` row records the exception. The door refuses `--force` without `--reason`, and
`--reason` without `--force`; `--reason -` reads the text off stdin like every prose flag. A
re-start of a task already `in_progress` is the retry above and is never refused for
readiness — it prints a `NOTE:` naming what is still unmet. Under `--json` the result carries
`ready`, `waitingOn`, `forced` and `forcedReason`.

**Another session's claim is refused the same way.** On the sharded layout, a phase whose
`claim.sessionId` is not this session's is refused with exit 2 and nothing written, and the
refusal names the claim's session, branch and moment. `--force --reason "<why>"` is the
one way past: it replaces the claim with this session's, and the `task.start` row keeps the
replaced session as the `from` of its `claim.sessionId` row and in its `basis`. Under `--json`
the result carries `claim`, `claimAction` (`none`, `keep`, `take`, `contested` or
`no-session`) and `claimReplaced`.

**The start that enters a phase warns about what sign-off will ask for** — an empty
`testGate` (sign-off then rests on review alone) and a missing `desiredOutcome` — as
`WARNING: phase entry: ...` lines and `entryWarnings` under `--json`. Never a refusal: an
empty gate is a designed state, and this is the last moment either is cheap to set. A start
inside a phase already running prints neither.

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
  [--intent matches|diverges|cannot-tell|not-asked] [--intent-basis TEXT] [--json]
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
  **`--intent not-asked --intent-basis "<why>"`** is the fourth word, and the only one no
  reviewer gives: the question was deliberately not put (a two-string edit, a close with no
  diff). It is refused without `--intent-basis`, because a skip with no reason on the record
  reads exactly like a reviewer call that never came back; `--intent-basis` alone, with no
  `--intent` beside it, is refused too. `/audit:phase signoff` and `/audit:status` (on a
  phase whose sign-off is due) name the done tasks that carry **no** answer — `not-asked`
  is an answer, so it is not among them.
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
written `null`, and **said**, when git cannot name one. The `task.done` row carries the reason
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
non-SHA `--commit` (with no `--no-change`); a SHA git can be asked about and does not have; and a task that was
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

## Subcommand: `reopen <taskId> --reason "<why>"`

`--reason` goes in unchanged, by the rule stated under `cancel` below: it reaches the hash-chained journal.

Put a **done** task back to `pending`, with the reason recorded. `commands/run.md` → step 1 is
where a re-open is offered and says what it clears; this is the same verb:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" reopen P3.2 \
  --reason "<why the close is undone>" [--json]
```

It resets `status`, `attempts`, `commit`, `completedAt`, `verifiedBy`, `outcome` and
`intentCheck`, puts a linked bug back to `in_progress` with no `fixedIn`, and writes a
`task.reopen` row carrying the reason. **Refused:** a task that is not done, a phase id, and a
task whose phase is signed off (done, or signed off and awaiting its merge) — the new work
there is a new task in an open phase or a bug.

## Subcommand: `block <taskId> --reason "<why>"`

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

## Subcommand: `note <taskId> --text TEXT`

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

## Subcommand: `couple --test <path> --sources a,b --basis-run <runId> --basis-head <sha> [--phases id,id]` / `uncouple --test <path>`

Both write `meta.coupling`, the record a derived phase gate reads back to widen itself onto a
test whose own run named a source it depends on. Neither takes a task or phase id — the
positional slot is the manifest, the same way `settle` reads it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" couple \
  --test plugins/audit/tests/test_<name>.py --sources src/a.ts,src/b.ts \
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
  --test plugins/audit/tests/test_<name>.py --caught <runId> [--json]
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
  --test plugins/audit/tests/test_<name>.py [--json]
```

`uncouple --test` drops the one entry it names. **Refused, exit 2:** `--test` naming a test
`meta.coupling` carries no entry for, and (on `couple`) an empty `--sources`, a missing
`--basis-run`/`--basis-head`, a `--basis-run` the evidence ledger does not hold, a
`--basis-head` that is not a commit SHA or that git can be asked about and does not have, or a
`--phases` id this plan does not hold.
`--sources`, `--basis-run`/`--basis-head`/`--phases` and `--caught` belong to `couple` alone; `--test` is
the one flag the two verbs share.

## Subcommand: `mute --test <path> --reason TEXT --owner NAME --until <YYYY-MM-DD> --bug <bugId>` / `unmute --test <path>`

Both write `meta.muted`, the quarantine the gate runner reads: a muted suite still runs and its
failure is still recorded, but that failure does not fail the run. These two are its only
writers. Neither takes a task or phase id — the positional slot is the manifest, `couple`'s
own spelling.

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/audit-task.py" mute \
  --test plugins/audit/tests/test_<name>.py --reason "<why it is muted, not fixed>" \
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
  --test plugins/audit/tests/test_<name>.py [--json]
```

`unmute` removes exactly the entry its `--test` names, with a `test.unmuted` row. A test
carrying no mute is refused, exit 2. **An expired mute is a warning, not a finding**, so a plan that
carries one is not refused by the check every verb runs first: `unmute` and an extending `mute`
run on it like every other verb.

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
that is not `/audit:phase retarget`'s. That verb *replaces* `testGate` too, so the
replacement itself still left the empty gate unspellable; `scope` **replaces**
`tests.gate` outright, and the gap is in the values — no `--gate` value says *none*,
because `--gate ""` writes a
gate holding an empty command, which is a gate that cannot run rather than the absence
of one. It refuses alongside `--gate` exactly as `retarget` does. Measured live: a phase
retargeted to `testGate: []` (nothing in that repo could grade markdown and config) left
its pending tasks holding the `["lint"]` they had inherited at creation, and the only
routes to the state the phase had just reached were a rescope mid-run or the hand edit
this file forbids. An emptied gate is reported as such rather than in silence — the
task then runs no gate command of its own (`run-test-gate.py --task` reads its
`gateBasis: cleared` and answers EMPTY), and the phase's `testGate` at sign-off is
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
