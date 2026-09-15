#!/usr/bin/env python3
"""Run a phase's test gate, and answer the two questions an exit code cannot.

F193, measured live. A docs task's gate was `pre-commit run --all-files`, which
`/audit:init` had read off the repo's own config. Running it MODIFIED five source
files the task does not own -- `isort` and `black` are fix-in-place, and they
reported `Passed` BECAUSE they rewrote them. Had the run reached its commit step,
a documentation task would have carried +33/-62 of backend reformatting.

Then the same run produced the opposite failure. Narrowed to
`pre-commit run --files <the task's two markdown files>`, every hook SKIPPED --
that repo configures Python hooks only. Exit 0, zero checks performed, and the
task went to `done` on it.

SO ONE DESIGN PRODUCED BOTH FAILURE MODES, AND THE EXIT CODE SEPARATED NEITHER
FROM A REAL VERDICT: a gate that did too much, and a gate that did nothing. This
script exists because the two questions that tell them apart are cheap and
nobody was asking either:

  * DID THE GATE CHANGE THE TREE? `git status --porcelain -uall` before and
    after. A gate is a MEASUREMENT; one with side effects has answered a
    different question than the one asked, and a commit built on it carries work
    nobody reviewed. Any difference refuses the commit step regardless of the
    gate's own exit code. The flag is load-bearing and its limit is stated at
    `_tree_stamp.porcelain`: it expands a wholly untracked directory into its
    files, so a
    file CREATED in one is seen; it does not make the bracket content-aware, so a
    REWRITE of a file that was already untracked is invisible to it. And the
    answer is a STATUS WORD and not only an exit code (F280, `GATE_MUTATED`): the
    refusal used to survive in the code this process returned and in a paragraph
    addressed to the model, while the row it wrote said `passed`.
  * DID ANYTHING ACTUALLY RUN? Runners that say so are read and the count is
    reported. `pre-commit` prints one line per hook and says `Skipped`; nothing
    read it. A count of zero is reported as `NO CHECK RAN`, which is not the same
    answer as green and must never be spelled like it.
  * DID THE OS END IT, RATHER THAN THE RUN ANSWERING? F302, driven here. A child
    the kernel kills comes back with a code that is merely `!= 0`, so the verdict
    read `sh -c 'kill -9 $$'` and `sh -c 'exit 1'` as ONE answer: exit -9 and
    exit 1, both `GATE RED`, both recorded `failed`. The signal was ALREADY on
    the record as `steps[].exit`, so this runner had observed it and the verdict
    threw the observation away -- and on another project 2 of 10 recorded
    failures were exit 139, which is the shell's spelling of a segfault. The cost
    is not only the wrong word: it writes a false red into a hash-chained ledger,
    and it spends a `maxAttempts` retry on something no code change can fix,
    which is the opposite of what `reference/orchestrator.md` says an
    infrastructure failure costs. A killed step is `could-not-run`, and the
    signal travels beside it with the basis naming WHICH of the two channels
    reported it -- see `ended_by_signal`.

WHY A SCRIPT AND NOT AN INSTRUCTION. `reference/orchestrator.md` could tell the
orchestrator to bracket the gate, and it would -- most of the time. That is the
argument `journal-writes.py` makes against a prompt in its own docstring: a rule
depending on the model remembering holds until a session forgets, a harness runs
a different orchestrator, or somebody adds a gate by hand next year. The bracket
lives in code so the gate cannot be run without it.

  * DID IT TOUCH WHAT THE TASK OWNS? F204, and the third shape of the same
    design. Measured live: a UI vitest suite, two files, nine tests, all green,
    against a diff that was a one-value edit to a JSON manifest. Exit 0, a real
    non-zero count, and no relationship between what ran and what changed. The
    count above exists so a ZERO cannot pass for green; a non-zero count that
    overlaps the diff nowhere is the same false verdict with better cover. The
    paths the runner prints are intersected with the `files` the work under test
    declares -- the phase's tasks, or one task with `--task` -- and the answer is
    STATED.

WHAT IT DOES NOT DO. It does not narrow the gate to the task's files, and the
overlap above does not refuse -- it reports. That distinction is the whole of
F204's decision. Narrowing changes what a per-task gate MEANS for every manifest
already written; and the overlap is derived from paths a runner HAPPENS to print,
which is a heuristic, and a heuristic that refuses manufactures false refusals in
a guard people would then learn to route around. Where the runner prints no paths
at all the answer is "not knowable from this output" and never "no overlap" --
the same rule the check count follows, for the same reason. What this guarantees
is that no outcome is silent.

AND THE CHEAPEST GATE IS THE ONE THAT DOES NOT RUN TWICE. A phase signed off more
than once runs its gate again over bytes nothing has touched, and the ledger
beside it already holds what that gate answered - so a run whose tree content and
whose declared gate match a recorded one REPEATS that verdict instead of taking
it again. The identity is a content digest and never `testedState`, whose dirty
half records which paths were dirty and not what is in them; `REUSE_LIMIT` states
what a match does and does not establish, `--no-reuse` is the way back to a
measurement, and every surface that shows the verdict says it was repeated and
names the run it came from. A repeat is not a run, and nothing here lets a reader
read it as one.

Exit codes:
  0  every command passed, the tree is unchanged, and at least one check ran
  1  a command failed, or the gate mutated the tree, or nothing ran, or the OS
     ended a step, or a stop signal cut the run short before every step had
     reported
  2  the gate could not be asked (no manifest, no such phase)
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _tree_stamp  # noqa: E402  (the ONE tree identity: porcelain + the three fields)
import _evidence_io as _ev  # noqa: E402  (where a run is recorded, and the pointer)
import _manifest_io as _mio  # noqa: E402  (dual-format loader: single file OR shards)

E_OK, E_FAIL, E_ASK = 0, 1, 2

# --- what did not finish ------------------------------------------------------
# The two ways a step produces no verdict, kept APART because they are different
# repairs. Before this they were one: `_shell` caught `TimeoutExpired` and
# `FileNotFoundError` in one `except Exception` and reported exit 127 for both, so
# "the suite hung" and "the binary is missing" arrived identical.
#
# NOT SPELLED AS EXIT CODES. 124 and 127 are conventions a real command may also
# return on its own, so reading a category out of the number would let a child
# claim a category by exiting with it. The category comes from what the WRAPPER
# observed and travels beside the code.
TIMED_OUT = "timed-out"
# ...and `could-not-run` IS THE CLASS "this step produced no verdict, for a
# reason that is not the work's", which is WIDER than the sentence the schema
# used to carry for it ("the runner never started -- no interpreter, an
# unreadable command"). The widening is F302's decision and it is recorded here
# rather than only in a plan, because the next reader meets the word before they
# meet the fault:
#
#   * THE CLASS ALREADY HELD MORE THAN THE SENTENCE ADMITTED. `never_started`
#     below assigns this word off a POSITIVE ZERO - a runner that started, died
#     before its first test and printed a summary saying none ran - and
#     `render`'s own banner has described the class as "a missing command, A
#     RUNNER THAT DIED BEFORE ITS FIRST TEST, a port it could not bind" for as
#     long as that arm has existed. So the description lagged its own code before
#     F302, and a killed child is a new MEMBER of an existing class rather than
#     a new class.
#   * THE WORD IS THE REPAIR, AND THE REPAIR IS THE SAME ONE. Fix the runner and
#     re-run; do not spend a retry on the task. That is correct verbatim for a
#     missing interpreter, for a sandbox that could not bind a port, and for an
#     out-of-memory reaper.
#   * THE PRECISION IS NOT LOST, IT IS PLACED. A verdict word is the coarse
#     summary a threshold reads; WHICH infrastructure failure this was is a
#     per-step observation, so it rides on the step as `signal` plus the basis
#     that says how it was known. This repo's rule is that a claim carries its
#     basis, not that every diagnostic distinction earns a word a gate switches
#     on.
#
# WHAT THE ALTERNATIVE WOULD HAVE COST, stated as a fact and not as the reason:
# a fourth no-verdict member reaches the schema enum, `_status_facts`, both
# renderers' label tables and sort orders, two stylesheets, `audit-status.py`'s
# condition help, `reference/orchestrator.md`, the README and the build guide -
# and a word shipped ahead of the two label tables is a verdict the panel and
# the report cannot name.
CANNOT_RUN = "could-not-run"

# ...and the third one, which is NOT a step's. A stop signal arrives at THIS
# process rather than at one command, so it has no step to hang off, and the step
# it cut short reported nothing: the run keeps the steps that FINISHED and stops
# there rather than inventing a row for work that never came back.
#
# THE WORD SHIPPED FOR RELEASES WITH NOTHING PRODUCING IT. It was in the plan
# schema's enum, in both renderers, and in two documents listing what gets
# written -- and `run_status` could only ever answer the four words above it. That
# made the fourth commit point of the negative-evidence policy, the sweep at
# `/audit:resume`, a sweep with nothing to sweep: an interrupted run left no
# record at all, which is the exact hole the policy was written to close.
CANCELLED = "cancelled"

# What a cancelled run names as its cause when the interrupt carried no name.
# REACHABLE, not defensive: `run_gate` is a library function, and a caller that
# never armed the handlers below meets Python's own bare `KeyboardInterrupt`. A
# `cancelled` status with no basis beside it is the one thing this record may not
# write, so the gap is filled by SAYING it is a gap.
UNNAMED_SIGNAL = "an unnamed interrupt"

DEFAULT_TIMEOUT_SECONDS = 3600
# How long a torn-down group is given to die politely before SIGKILL. Small on
# purpose: this runs after a step has already overrun its whole budget.
GRACE_SECONDS = 5

# How many characters of a sample a basis line may spend before `_output.some_of`
# stops and says how many it did not show. In CHARACTERS rather than elements,
# which is that helper's whole argument: a step name is short and a
# `node_modules/...` stack frame is not, so an element count says nothing about
# how long the line comes out. These strings are copied verbatim into a COMMITTED
# ledger row, so the budget is a size limit on the record and not only on a
# terminal.
SAMPLE_BUDGET = 160

# --- how much did it do -------------------------------------------------------
# Runners that report their own step count, and the words they end a step with.
# Read as a COUNT and never as a verdict - the verdict is the exit code's job, and
# what was missing is the SIZE of the thing behind it. A runner absent from BOTH
# tables below yields `None`, which is reported as "not knowable from this runner"
# and never as zero: guessing zero would refuse a passing gate, and guessing one
# would bless a skipped one.
_STEP_WORDS = {
    "pre-commit": ("Passed", "Failed", "Skipped"),
}

# ...AND THE TABLE ABOVE WAS ONE ENTRY WIDE, WHICH MADE A DOCUMENTED RULE
# UNREACHABLE (F276). `reference/orchestrator.md` step 4c asks a caller to tell
# "the gates ran and failed" apart from "the gates could NOT run: missing command,
# runner crash before tests, zero tests collected" -- and every real test runner
# answered `None` to "how many ran", so the zero that distinction turns on could
# not occur outside a `pre-commit` gate. Measured live: `mongodb-memory-server`
# could not bind a port in a sandbox, the suite died at exit 48 with no test
# executed, and the ledger recorded GATE RED against the task's name.
#
# MATCHED ON THE OUTPUT, NOT ON THE COMMAND, which is the half `_STEP_WORDS`
# cannot do: a gate entry is as often `npm test`, `yarn test` or `make check` as
# it is the runner's own name, and the summary line is the runner's signature
# either way. `_STEP_WORDS` is still asked FIRST, so a `pre-commit` gate that
# wraps a test hook keeps counting hooks and not the tests inside one of them.
#
# THE WORDS ARE THE ONES THAT MEAN A CHECK EXECUTED, and `skipped`, `pending`,
# `todo`, `deselected` and `total` are deliberately absent from every row. A
# skipped check is the exact thing `NO CHECK RAN` exists to catch, so counting
# jest's own `N total` -- which includes them -- would re-open F193's second
# failure mode one runner along. `error` is out for the same reason from the
# other end: a pytest collection error is a test that never started.
_SUMMARY_PAIR = re.compile(r"(\d+) ([a-z]+)")
# The phrasing both vitest and pytest use for "there were none", which carries no
# `N word` pair at all and would otherwise read as a runner this cannot count.
_NO_TESTS = re.compile(r"\bno tests\b")
_SUMMARY_READERS = (
    # jest:   `Tests:       1 failed, 2 skipped, 3 passed, 6 total`
    ("jest", re.compile(r"^[ \t]*Tests:[ \t]+(.*)$", re.M), ("passed", "failed")),
    # vitest: `Tests  1 failed | 4 passed (5)`, `Tests  no tests`. No colon, which
    # is what keeps this off jest's line, and `Test Files` is a different word.
    ("vitest", re.compile(r"^[ \t]*Tests[ \t]+(.*)$", re.M), ("passed", "failed")),
    # mocha:  `  5 passing (23ms)` and `  1 failing` on SEPARATE lines, which is
    # why every match is joined before the pairs are read out of it.
    ("mocha", re.compile(r"^[ \t]*(\d+ (?:passing|failing|pending).*)$", re.M),
     ("passing", "failing")),
    # pytest: `=== 3 passed in 0.12s ===`, and bare under `-q`. `no tests ran` and
    # `1 error` are both real summaries reporting zero, so both must MATCH here
    # and count nothing, rather than falling through as "not knowable".
    ("pytest",
     re.compile(r"^[=\s]*((?:no tests ran|\d+ \w+(?:, \d+ \w+)*)"
                r" in [\d.]+m?s.*)$", re.M),
     ("passed", "failed", "xpassed", "xfailed")),
)


# --- whose writes did the bracket catch ---------------------------------------
# F280. THE REFUSAL LIVED ONLY IN THE EXIT CODE AND IN PROSE. `render` has printed
# `GATE MUTATED THE TREE` and returned E_FAIL for as long as the bracket has
# existed, and `reference/orchestrator.md` tells the model not to commit on such a
# run -- but `run_status` took no tree argument and had no tree arm, so the ROW
# said `passed` and `pointer_for` cached that word onto `task.testEvidence`. The
# live signal was right and the record was wrong, which is the worse half: the
# exit code is read once, by whoever was watching, and the record is what a reader
# consults a week later. `--fail-on failing-tests` read the record and passed the
# run.
#
# THE WORD NAMES THE ACTOR, not the event, and that is the whole content of the
# split below: `treeMutated` says WHAT moved, `owned` is the half attributable to
# the gate, and this is the word for that half. The event already had a spelling -
# the `tree-mutated` observation mark both surfaces render off the FULL set - and
# reusing it here would have put one string in two vocabularies, one of which
# cannot attribute anything.
GATE_MUTATED = "gate-mutated"


def _norm(path):
    """One spelling for a path, so two readings of one file compare equal."""
    text = str(path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _declared_by(line, declared):
    """Whether a porcelain LINE names a path the work under test declares.

    Every path the line names is asked and not only the one that exists now
    (`_evidence_io.porcelain_paths`): a rename takes a declared file away under
    one name and brings it back under another, and either half is the gate
    rewriting its own subject.

    A DECLARED ENTRY IS ALSO TRIED AS A DIRECTORY PREFIX, which widens toward the
    refusing class on purpose. A manifest entry naming a directory means the
    files under it, and the direction a guard may be wrong in is claiming a path
    it might own rather than handing it to the half that only reports.
    """
    for path in _ev.porcelain_paths(line):
        path = _norm(path)
        for entry in declared:
            if path == entry or path.startswith(entry + "/"):
                return True
    return False


def classify_mutations(mutated, owns):
    """`(owned, foreign, basis)` - whose writes the tree bracket caught (F273).

    `_tree_stamp.porcelain` describes the WHOLE repository with no pathspec, so
    the bracket
    sees every write that lands between its two snapshots and not only the
    gate's. `reference/orchestrator.md` encourages running tasks with disjoint
    `files` in PARALLEL, which makes a sibling executor's writes land inside that
    window as a matter of course. Measured live on a project whose gates are all
    read-only -- `eslint` with no `--fix`, `tsc --noEmit`, `vitest run`,
    `vite build` -- one run named a file owned by a DIFFERENT task, and another
    went red across dozens of paths and green on an identical re-run.
    `GATE MUTATED THE TREE` refuses the commit step whatever the gate's own exit
    code says, so a false positive there halts a correct run.

    THE REPAIR IS A CLASSIFICATION AND NEVER A MUTE. That same verdict correctly
    revealed a second session writing into one working directory on another
    project, and that has to keep working - so this is two sets with two meanings
    and two responses, not one set with the volume turned down.

    AND THE COST IS REAL, SO IT IS STATED HERE RATHER THAN FOUND LATER. F193
    ITSELF -- a docs task whose `pre-commit run --all-files` gate rewrote five
    backend source files -- lands in `foreign` under `--task`, because those
    files are precisely what that task does not declare. Porcelain reports WHAT
    moved and never WHO moved it, so a gate writing outside its own subject and a
    sibling writing anywhere at all are indistinguishable from these two
    snapshots. That half is therefore reported with both readings named, and no
    longer refused. What still refuses is `owned`: a gate that rewrote the files
    it was grading has made its own verdict a claim about bytes it produced, and
    there is no benign reading of that one.

    NOTHING IS GUESSED WHERE NOTHING IS KNOWN. With no declared files there is no
    ownership to sort by, so both halves come back None and the basis says so;
    `render` then attributes the whole set to the gate, which is what it did
    before this existed and the direction a guard is allowed to be wrong in.
    """
    if mutated is None:
        return None, None, "no comparison was made, so nothing can be attributed"
    declared = [_norm(f) for f in (owns or [])
                if isinstance(f, str) and f.strip()]
    if not declared:
        return None, None, ("the work under test declares no files, so a changed "
                            "path can be attributed neither to it nor away from it")
    owned, foreign = [], []
    for line in mutated:
        (owned if _declared_by(line, declared) else foreign).append(line)
    return owned, foreign, ("%d of %d changed path(s) are declared by the work "
                            "under test" % (len(owned), len(mutated)))


def attributed_mutations(mutated, owned, foreign):
    """`(refused, reported)` - which changed paths refuse a verdict, and which
    may only be named beside one.

    ONE EXPRESSION, THREE READERS. `run_status`, `render` and `main`'s `--json`
    arm each had to decide what "the gate rewrote its own subject" meant, and two
    of them wrote the fallback out by hand while the third had no arm at all -
    which is F280 in one sentence. A rule spelled once cannot let the record and
    the exit code disagree about the same run.

    THE FALLBACK IS THE DIRECTION A GUARD MAY BE WRONG IN. `owned is None` means
    `classify_mutations` had no declared files to sort by, so nothing can be
    attributed either way; the whole set is then charged to the gate, which is
    what this verdict did before the split existed. `mutated is None` - no
    comparison was made at all - comes back as an empty refusal, because a
    comparison nobody made cannot refuse anything; `treeBasis` is what says so.
    """
    if owned is None:
        return list(mutated or []), []
    return list(owned), list(foreign or [])


# --- what the tree ALREADY carried, and the one red it excuses ----------------
# THE SNAPSHOT IS THE EARLIER ONE, AND THAT IS THE WHOLE FAULT. Everything above
# sorts `after - before`: what moved DURING the run. The row this exists for had
# `treeMutated == []` - the value that means KNOWN CLEAN - because the sibling
# executor's file was ALREADY half-written when the gate started, so nothing moved
# between the two snapshots and the bracket had nothing to attribute. The state
# that broke the gate was in `before` the whole time and no reader looked at it.
#
# WHAT WAS REPORTED. Three "false red" rows were brought by an operator; asked for
# the raw rows he withdrew two, which were real failures with counts in the
# thousands. The survivor was a task gate whose typecheck exited non-zero and
# whose jest step collected nothing, run in a shared tree while a sibling task's
# executor was editing files. `tsc` compiles the WHOLE PROGRAM, so a half-written
# file belonging to another task fails it regardless of whose file it is.
#
# NOTHING HERE EXCUSES ANYTHING ON ITS OWN. `unattributable_failure` below is the
# decision and every clause it asks is stated there with what goes wrong without
# it; these two functions only answer the questions it asks.


def dirty_outside(before, owns):
    """`(paths, basis)` - what the tree already carried that this work does not declare.

    THE SPLIT IS `classify_mutations`' AND IS NOT COPIED, because the question is
    the same question - does this porcelain line name a declared file - asked of
    a different set of lines. A second spelling of that would answer a rename or
    a git-quoted path differently the first time either was fixed in one place.

    NOTHING IS EXCUSED WHERE NOTHING CAN BE ATTRIBUTED, which is the direction
    this function has to be wrong in. With no declared files EVERY dirty path is
    trivially "outside the declared scope", so reading an empty scope as foreign
    dirt would excuse every failing run on every dirty tree - real failures turned
    into infrastructure, permanently, in a hash-chained row. `classify_mutations`
    already answers None for exactly that state and this keeps it a None.
    """
    if before is None:
        return None, ("git could not describe the tree before the run, so what "
                      "it already carried is not knowable")
    if not before:
        return [], "the tree carried no dirty path when the run started"
    _owned, foreign, _basis = classify_mutations(before, owns)
    if foreign is None:
        return None, ("the work under test declares no files, so a path that was "
                      "already dirty can be attributed neither to it nor away "
                      "from it")
    if not foreign:
        return [], ("every path dirty at run start is one the work under test "
                    "declares")
    return foreign, ("%d of %d path(s) dirty at run start name no file this work "
                     "declares: %s"
                     % (len(foreign), len(before),
                        _output.some_of(foreign, budget=SAMPLE_BUDGET)))


def _named_by_run(line, named):
    """Whether the run's own output mentioned a path this porcelain line names.

    BOTH OF THE LINE'S NAMES ARE ASKED, for `_declared_by`'s reason: a rename
    carries two, and a runner blaming either of them is blaming this line.

    `_PATHISH` over-matches on purpose and that is tolerable here for a narrower
    reason than the one `files_named` gives. A spurious token can only widen the
    excuse if it is spelled EXACTLY like a path git reports as dirty, which is a
    far smaller set than "any token that looks path-shaped".
    """
    if not named:
        return False
    spellings = set(_norm(p) for p in _ev.porcelain_paths(line))
    return any(_norm(tok) in spellings for tok in named)


def unattributable_failure(failed, ran_total, before, owns, named):
    """`(paths, basis)` for a red that is NOT this work's; `(None, None)` for one
    that is.

    EVERY CONJUNCT OR NEITHER, and the ones after the first are what keep this
    honest. A suite that collects nothing because THIS work left a syntax error
    in a test file, and a red-first test written against a module that does not
    exist yet, both measure exactly nothing and are both the work's own failure.
    Excusing those records no verdict, spends no retry on work that needs one,
    and hides the defect - the F323 class, real failures excused as
    infrastructure. So the zero moves nothing on its own.

    AND AMBIENT DIRT IS NOT EVIDENCE EITHER, WHICH IS THE THIRD CONJUNCT AND WAS
    MEASURED RATHER THAN REASONED. Driven end to end on a scratch project: the
    second run of the same gate was excused by the FIRST run's own bookkeeping -
    the manifest pointer, the evidence ledger and the journal, none of which a
    task declares and none of which can fail a typecheck. That is not a corner
    either: `reference/orchestrator.md` step 2 edits the phase's manifest file
    (`status`, `attempts`, `startedAt`) before the executor is spawned, so the
    plan's own state is dirty and undeclared at EVERY gate run in the real
    workflow, and a rule reading tree state alone would excuse every red that
    measured nothing, permanently, and make the paragraph above unreachable.
    So the dirty path must be one the RUN ITSELF BLAMED: the reported row's
    typecheck printed `other/sibling.ts(2,1): error TS1005` - the very file the
    sibling executor was half way through writing. That is attribution evidence
    rather than a coincidence of timing, and it is the operation the excuse now
    reads instead of the weather.

    WHAT THAT COSTS, STATED RATHER THAN FOUND LATER: a runner that prints no
    paths, or prints them in a shape `files_named` does not recognise, never
    reaches this arm however dirty the tree was. Its red STANDS - which is the
    direction an excuse has to be wrong in, because the other one is a verdict
    nobody records and a retry nobody spends.

    IT ONLY EVER DISPLACES `failed`, so it is asked only where there is a red to
    attribute. A gate that came back green having measured nothing is
    `no-checks`, which blames nobody and names its own repair (the gate skipped
    everything - fix the gate), and a tree somebody else made dirty explains none
    of that.

    THE ZERO IS THE RUN'S, READ FROM `ran_total` AND NOWHERE ELSE. That is the
    same number `measured_state` reads one row down to write `nothing` on a step,
    and asking the two questions off two values is how a row and a verdict come
    to disagree about one run. It is a POSITIVE zero: `ran_total is None` means no
    runner in this gate published a count, which is not evidence that nothing ran
    - the rule `run_status` and `never_started` already follow.
    """
    if not failed or ran_total != 0:
        return None, None
    paths, basis = dirty_outside(before, owns)
    if not paths:
        return None, None
    blamed = [line for line in paths if _named_by_run(line, named)]
    if not blamed:
        return None, None
    return blamed, ("this gate measured nothing and came back red naming a file "
                    "that was already dirty when it started and that this work "
                    "does not declare, so its red is not evidence about this "
                    "work: %s; the run named %s"
                    % (basis, _output.some_of(blamed, budget=SAMPLE_BUDGET)))


# --- what state was actually tested -------------------------------------------
# THE THREE IDENTITY FIELDS LIVE IN `_tree_stamp`, NOT HERE. They were written for
# this file and they are still what this file records; what changed is that the
# orchestrator needs the same fingerprint for a claim it carries in prose, and a
# second expression of "which tree was this" would BE a second tree identity. The
# module holds `porcelain()`, `HEAD_BASIS`, `scope_digest()`, `dirty_digest()` and
# `tested_state()` unchanged, plus the comparison this file never needed.


def _elapsed_ms(started):
    """Whole milliseconds since a `time.monotonic()` reading.

    Monotonic rather than wall clock because this measures a DURATION: a wall
    clock can step backwards mid-run and produce one that reads as negative.

    NO CLAMP, deliberately. `max(0, ...)` was here and guarded nothing a case
    could reach - `time.monotonic()` is non-decreasing by contract, so the branch
    was unreachable defence that would have read as covered. The mutation battery
    is what said so: deleting it changed no verdict.
    """
    return int((time.monotonic() - started) * 1000)


def summary_reader(text):
    """`(name, joined, words)` of the reader whose summary this output carries.

    `(None, "", ())` FOR A RUNNER NONE OF THEM RECOGNISES, which is the same
    answer `summary_count` has always returned as `None` - this is that decision
    lifted out of it, unchanged, so that "which runner is this" is asked once and
    answered in one place. It was already asked twice the moment a second reader
    wanted the names of the checks that failed, and two spellings of one
    recognition rule drift the first time either table grows a row.
    """
    for name, line_re, words in _SUMMARY_READERS:
        found = line_re.findall(text or "")
        if not found:
            continue
        joined = " ".join(found)
        if _SUMMARY_PAIR.findall(joined) or _NO_TESTS.search(joined):
            return name, joined, words
    return None, "", ()


def summary_count(text):
    """How many checks a runner's own SUMMARY line says executed, or None (F276).

    Derived from the runner's arithmetic and never from this reader's: counting
    output lines would go wrong the first time a suite name wrapped or a reporter
    was configured, and re-adding jest's categories to check its `total` would
    disagree with jest the first time it grew one.

    None IS STILL THE ANSWER FOR A RUNNER WITH NO SUMMARY HERE, and that is the
    rule this widening had to keep rather than the rule it replaces. A reader
    that returned 0 for "I did not recognise this output" would refuse every
    passing gate whose runner is not in the table above.
    """
    name, joined, words = summary_reader(text)
    if name is None:
        return None
    return sum(int(n) for n, word in _SUMMARY_PAIR.findall(joined)
               if word in words)


def wrapper_words(command):
    """The per-sub-run words `command`'s runner prints, or None if it wraps none.

    ONE TABLE, TWO QUESTIONS, AND THEY ARE THE SAME QUESTION (F352). A runner
    earns a row in `_STEP_WORDS` precisely because its output is a LIST OF
    OTHER RUNS - `Passed` / `Failed` / `Skipped`, one line per hook - so the
    table that tells `ran_count` to tally lines is the table that tells
    `reached_a_verdict` that an end-of-run report inside this output belongs to
    a HOOK and not to the step. A second table naming "composite runners" would
    be a second answer to one question and the two would drift apart the first
    time either grew a row.
    """
    for name, tup in sorted(_STEP_WORDS.items()):
        if name in (command or ""):
            return tup
    return None


def ran_count(command, text):
    """How many checks a runner reported doing, or None when it does not say.

    TWO PROVENANCES BEHIND ONE NUMBER, AND `ended_by_signal` MUST NOT READ IT
    (F323). Below `_STEP_WORDS` this counts LINES - it is this reader's own
    arithmetic over a runner that publishes no total - while `summary_count`
    returns the runner's. Both are honest counts and neither is a claim that the
    run reached its end, which is why the question "did the runner speak for its
    exit code" is asked by `reached_a_verdict` and not by looking at this.
    """
    words = wrapper_words(command)
    if words is None:
        return summary_count(text or "")
    passed, failed, _skipped = words
    ran = 0
    for line in (text or "").splitlines():
        stripped = line.rstrip()
        if stripped.endswith(passed) or stripped.endswith(failed):
            ran += 1
    return ran


# --- what that count SAYS, which is an observation and not a verdict ----------
# The reading of `ran`, spelled once as a word so that no reader has to spell it
# again. The answers are not points on a scale and a number cannot keep them
# apart on its own: a positive zero is a measurement that came back EMPTY, and a
# `None` is no measurement at all.
MEASURED_CHECKS = "checks"
MEASURED_NOTHING = "nothing"
MEASURED_UNKNOWN = "not-knowable"


def measured_state(ran):
    """Whether a step measured checks, measured nothing, or reports no count.

    `ran` ALREADY HOLDS THIS AND READERS STILL GET IT WRONG, which is the whole
    argument for a word beside the number. Every consumer that wants "did
    anything run" has to spell the distinction itself, and the shortest spelling
    - `not ran` - reads a runner that publishes no count as a runner that ran
    nothing. This file already refuses that merge one function at a time
    (`run_status` leaves the status alone on a `None`; `never_started` fires off
    a POSITIVE zero only); here it is refused once, for every reader of the row.
    Measured in the field: an operator holding a red row whose step had collected
    nothing reported it as a false red, and the rows he reported beside it had
    collected checks in the thousands and were real failures. The column that
    separated them was on the row the whole time, as a number nobody was reading
    as a three-way answer.

    DERIVED FROM `ran` AND FROM NOTHING ELSE, so it cannot disagree with the
    number it sits beside. That is also why no basis key travels with it: `ran`
    IS the basis and is already on the row, and a second copy of an observation
    is a thing that can contradict the first - the argument `run_gate` makes
    where it declines to write one beside `never_started`.

    AND IT IS AN OBSERVATION, DELIBERATELY NOT A VERDICT. "This step measured
    nothing" does not by itself say the gate is not red, because the verdict
    needs a second fact this function does not have: whether the failure is
    attributable to the work under test. A suite that collects nothing because
    this work left a syntax error in a test file is the work's own failure and
    reads identically here. So nothing in this file switches on this word, and
    whatever decides a verdict from it decides it elsewhere, on this plus that
    attribution. The schema draws the same line for the no-verdict class - which
    member it was "is a per-step observation in the ledger row's `steps[]` ...
    rather than a word of its own here, because a verdict word is what a gate
    switches on".
    """
    if ran is None:
        return MEASURED_UNKNOWN
    return MEASURED_NOTHING if ran == 0 else MEASURED_CHECKS


# --- which checks failed, or the tail that stands in for their names ----------
# WHAT THIS IS FOR, reported three times by two projects: a red row carried the
# status, the failing gate ENTRY names and how many checks ran, and nothing about
# WHICH tests failed. Both operators wrote their own failing-test reporter around
# the gate, and one of them recovered the names twice out of a project artefact
# the next run overwrites - so the obvious reflex, re-run and read the output,
# destroys the evidence. The text was in hand the whole time: `_shell` merges
# stderr into stdout, `ran_count` reads it and `files_named` scrapes it, and then
# it reached neither the result nor the row.
#
# ONE ROW PER RUNNER `_SUMMARY_READERS` ALREADY COUNTS, AND NO OTHER. A parser
# for a runner whose summary this file cannot read would be naming failures
# beside a check count that says "not knowable from this runner" - a claim with
# no measurement under it, which is the shape this file exists to refuse. `fr0`
# is the case that reads the two tables against each other, so a reader added to
# one and not the other fails rather than silently falling through to a tail.
#
# MATCHED ON THE OUTPUT, NOT ON THE COMMAND, for the reason `_SUMMARY_READERS`
# states: a gate entry is as often `npm test` or `make check` as it is the
# runner's own name, and the failure lines are the runner's signature either way.
_FAILURE_READERS = {
    # jest heads each failure block with a bullet. `Console` is a console dump
    # under the same bullet and not a failing check; `Test suite failed to run`
    # is one and is deliberately kept.
    "jest": re.compile("^[ \t]*●[ \t]+(?!Console[ \t]*$)(.+?)[ \t]*$",
                       re.M),
    # vitest marks a failure beside a cross in the file tree and again as
    # `FAIL  <file> > <suite> > <name>` under `Failed Tests`. Both are read
    # because which of them a reporter prints depends on how it was configured;
    # the two spell the test differently, so this collapses only EXACT repeats
    # and a run printing both carries both spellings of the same failure.
    "vitest": re.compile("^[ \t]*(?:×|FAIL)[ \t]+(.+?)[ \t]*$", re.M),
    # mocha NUMBERS its failures, and the number is the only mark on the line.
    "mocha": re.compile(r"^[ \t]*\d+\)[ \t]*(.+?)[ \t]*$", re.M),
    # pytest's short summary. `ERROR` is here and is NOT the same claim as
    # `error` being absent from the counting words above: a collection error is
    # not a check that ran, and it is still the thing the operator has to fix.
    "pytest": re.compile(r"^(?:FAILED|ERROR)[ \t]+(.+?)[ \t]*$", re.M),
}


def _distinct(items):
    """`items` with repeats dropped, first occurrence order kept."""
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def failing_lines(text, limit):
    """`(lines, basis)` - the names of the checks that failed, or a capped tail.

    TWO ANSWERS AND THE ROW SAYS WHICH, which is the whole contract: where the
    summary reader recognises the runner these are the names it gave the checks
    that failed, and where it does not they are the last lines of the output,
    standing in for names nobody can parse. A reader who cannot tell those apart
    would read a stack frame as a test name, so the basis names the runner when
    there is one and says "tail" when there is not.

    A RECOGNISED RUNNER THAT NAMED NOTHING FALLS TO THE TAIL TOO, and that arm is
    the point rather than a leftover. Returning an empty list because jest was
    recognised and printed no bullet would be this whole defect back again, one
    branch in: the operator gets a red verdict and no text, which is what they
    already had. `limit` bounds both arms identically - the row is hash-chained,
    so a field with unbounded content is a row with unbounded size - and the
    basis carries the count, so a cut announces itself rather than reading as
    all there was.

    Nothing here redacts. That is `_evidence_io`'s job, done at the moment the
    row is assembled, because the TERMINAL wants the operator's own absolute
    paths and the committed file may never carry them.
    """
    body = text or ""
    name, _joined, _words = summary_reader(body)
    # `.get`, NEVER `[name]`. The two tables are held together by a case rather
    # than by this line, and the case is the right mechanism - but a KeyError
    # here would abort `run_gate` mid-gate and lose the run, which is a far worse
    # answer to a drifted table than the tail this falls through to. `fl0` is
    # what reports the drift; this is only what survives it.
    reader = _FAILURE_READERS.get(name)
    if reader is not None:
        named = _distinct(reader.findall(body))
        if named:
            kept = named[:limit]
            if len(named) > len(kept):
                return kept, ("%d of the %d check(s) %s named as failing; the "
                              "rest are not carried"
                              % (len(kept), len(named), name))
            return kept, ("the %d check(s) %s named as failing, read from its "
                          "own failure lines" % (len(kept), name))
    lines = [ln.rstrip() for ln in body.splitlines() if ln.strip()]
    tail = lines[-limit:] if limit > 0 else []
    if not tail:
        return [], ("the step printed nothing, so its own output names neither "
                    "a failing check nor anything else")
    if name is None:
        return tail, ("no runner this gate can count wrote a summary line, so "
                      "these are the last %d line(s) of the step's output and "
                      "NOT a list of failing checks" % (len(tail),))
    return tail, ("%s's summary was read for the check count and its output "
                  "named no failing check, so these are the last %d line(s) of "
                  "it and NOT a list of failing checks" % (name, len(tail)))


# --- did the runner get to the end of its run ---------------------------------
# The END-OF-RUN reports a machine-readable reporter writes, for runners whose
# exit status may itself be a count. Deliberately a WEAKER question than
# `_SUMMARY_READERS` asks: those have to parse arithmetic, and this only has to
# recognise that a terminal report is present - which is why it reaches shapes
# the counting readers cannot, and why it is allowed to.
#
# EVERY ONE OF THESE IS WRITTEN WHEN THE RUN ENDS. A JSON or xunit reporter
# buffers and emits its document at the end; a TAP harness closes with its
# tallies; `Test Count:` and `Checkstyle ends with` are last lines. So their
# presence is evidence the runner finished, which is exactly the claim being
# made - a marker a runner emitted mid-flight would let a killed step pass for
# one that answered.
#
# AND ONE OF THEM WAS EXACTLY THAT (F352). The TAP row matched a bare `1..N`
# anywhere in the output, and a TAP PLAN is legal at EITHER end - the classic
# form prints it FIRST. Driven: a plan-first stream killed after its second
# test answered `reached_a_verdict` True, so a SIGKILLed run was graded `failed`
# rather than `could-not-run` and spent a retry on work never measured, which is
# the F302 fault this whole arm exists to prevent. The plan is still read, but
# only in the position that makes it a close.
_END_OF_RUN = (
    # mocha `--reporter json`, jest `--json`, vitest `--reporter=json`. This is
    # F323's own measured case: `mocha --reporter json` at exit 139 carries a
    # full report and its `stats` object, and the counting readers see none of it.
    ("json-report",
     re.compile(r'"(?:failures|passes|numTotalTests|numFailedTests|'
                r'testsCompleted)"[ \t]*:[ \t]*\d+')),
    # mocha `--reporter xunit`, nunit's and pytest's junit-xml.
    ("xunit", re.compile(r'<testsuites?\b[^>]*\b(?:tests|failures)="\d+"')),
    # TAP, the tallies a harness closes with. These are written after the last
    # test by construction, wherever the plan sits.
    ("tap-tallies",
     re.compile(r'^[ \t]*# (?:fail|pass|tests)[ \t]+\d+[ \t]*$', re.M)),
    # ...and the TAP plan, ONLY as the last thing in the output. `done_testing()`
    # and every harness that counts as it goes print `1..N` at the end and no
    # tallies at all, so dropping the shape would lose them; matching it anywhere
    # read the CLASSIC form's opening line as a close (F352). `\s*\Z` allows the
    # trailing newline and nothing else after it.
    ("tap-plan", re.compile(r'^[ \t]*1\.\.\d+[ \t]*\s*\Z', re.M)),
    # nunit3-console, whose exit status IS the failure count.
    ("nunit", re.compile(r'^[ \t]*Test Count:[ \t]*\d+', re.M)),
    # checkstyle, likewise - its status is the violation count.
    ("checkstyle", re.compile(r'Checkstyle ends with \d+ error')),
    # `dotnet test` / vstest, whose status is not a count but whose report is as
    # easy to recognise as the ones that are.
    ("vstest", re.compile(r'^[ \t]*Total tests:[ \t]*\d+', re.M)),
)


def reached_a_verdict(text, command=None):
    """Whether the runner's output carries an END-OF-RUN report (F323).

    THE QUESTION `ended_by_signal` ACTUALLY NEEDS, asked on its own rather than
    borrowed from the counter. A process the OS ends does not finish, so it does
    not print the report it finishes with; a run that printed one has spoken for
    whatever exit status follows it, count or not.

    WHY IT IS NOT `ran is not None`, which is what stood here. That expression
    answers "did THIS READER count something", and the two directions it was
    wrong in were both measured:

      * `mocha --reporter json` answers None to every counting reader in this
        file, so exit 139 - which for mocha is 139 FAILING TESTS - was recorded
        `could-not-run`, landed in `_status_facts.NO_VERDICT_EVIDENCE` ("nothing
        about the work under test may be read into it"), and told the
        orchestrator not to spend a retry. Real failures became an infrastructure
        excuse, permanently, in a hash-chained row. `--reporter xunit` did the
        same, and `nunit3-console` and `checkstyle` also encode a count in their
        status.
      * ...and for `pre-commit` - the only entry in `_STEP_WORDS`, the shape the
        table exists for - the arm could never fire AT ALL, because `ran_count`
        counts LINES there and so never answers None. An OOM-killed
        `pre-commit run --all-files` that had logged one `Passed` hook was
        recorded `failed` against the task and spent a retry: F302's founding
        fault, unrepaired for the configuration it was reported against. A line
        tally is not a verdict, and this function cannot be fooled by one.

    A COMPOSITE RUNNER SPEAKS FOR NO STEP BUT ITS OWN, WHICH IS THE OTHER HALF
    OF F352. `pre-commit` runs OTHER runners and prints one line per hook, so a
    pytest hook's `1 failed, 3 passed in 0.42s` is an end-of-run report for that
    HOOK and mid-flight for the step - the next hook has not started. Measured:
    that exact stream, killed with `mypy`'s line unfinished, made
    `summary_count` answer 4 and this function answer True, so an OOM-killed
    composite was graded `failed` and spent a retry - F302's founding
    configuration, reached this time through the summary arm rather than through
    the line tally. So for a runner `wrapper_words` knows, NOTHING in the output
    is a verdict for the step: not a summary, and not an `_END_OF_RUN` document
    a hook emitted either. `pre-commit` publishes no closing report of its own
    and its exit status is not a count, so nothing is lost by refusing to find
    one.

    THE RESIDUAL RISK, NAMED RATHER THAN ARGUED AWAY. No discriminator closes
    this: some runner somewhere encodes a count in its exit status and reports in
    a shape nothing here recognises, and for that runner a status in the
    terminating band is read as a kill. The error therefore falls toward
    `could-not-run` - a run that refuses, carries a word no surface may sign off,
    and costs a retry not spent. That is a stall a reader can see, never a green
    over red, and the repair is one row in `_END_OF_RUN`. The opposite error is
    real too and smaller: a runner that printed its report and was killed
    afterwards is graded `failed`, which spends a retry on something no code
    change fixes - it is bounded to the window between the last line and the
    exit, and the negative-code channel catches it whenever the shell did not
    stand in the way. The TAP plan keeps a sliver of that window all to itself:
    a run killed between its opening plan and its first test line has an output
    whose last line IS a plan, and there is nothing in the bytes to tell that
    from a harness that closed with one.
    """
    body = text or ""
    if wrapper_words(command):
        return False
    if summary_count(body) is not None:
        return True
    return any(pattern.search(body) for _name, pattern in _END_OF_RUN)


# --- what a count may be ADDED to, and what each step COST ---------------------
# P46.5, reported from a live audit. A project's `meta.buildCommands` mapped one
# entry to a plain runner invocation and another to the SAME runner with coverage
# on. The gate ran both, so the identical checks executed twice, and the TOTAL it
# printed was the suite counted twice - which the operator and the reviewer both
# read as thoroughness, because a bigger count reads as more assurance. The number
# that should have exposed the duplication is the number that concealed it.
#
# AND THE DUPLICATE STEP COULD ONLY COST. On a later sign-off the plain step
# PASSED and the coverage step came back RED on the identical checks - a flaky
# index-build race, not a threshold. A step that can only agree with another step
# or be flaky adds no assurance; it doubles the exposure to every nondeterminism
# in the suite and buys a re-run.
#
# WHERE THE WARNING LIVES, AND THE PLACES IT DELIBERATELY DOES NOT. Here, in the
# process that ran both commands, because the evidence that two entries are one
# suite is the OUTPUT - the count each printed and the suite files each named -
# and nothing but the run holds it.
#
#   * NOT `scripts/manifest/validate-manifest.py`. It sees the command STRINGS,
#     so the only comparison available to it is over the spelling: `vitest run`
#     and `vitest run --coverage` differ as text and are one suite, while
#     `npm test` in two workspaces is the same text and two suites. A check that
#     reads what a command SAYS instead of what it DOES is the class this plugin
#     keeps being repaired for, and here it would both miss the reported run and
#     refuse honest manifests.
#   * NOT the config reference. A sentence there is read once, when the manifest
#     is first written; the duplicate entry is added later, by somebody who is
#     not reading it. It would also enforce nothing, which is this repo's
#     definition of a rule that is absent.
#
# ONE OF THEM AND NOT TWO. A second copy of this warning somewhere that cannot
# see the run's output would disagree with this one the first time either moved,
# and the copy that cannot measure would be the one people learned to ignore.


def suite_paths(named):
    """The paths a runner printed AS TESTS IT RAN - what identifies a suite.

    NOT every path in the output, and that narrowing is the whole reason this
    comparison can be made at all. `--coverage` prints a table naming the
    SOURCES under a suite, so the two runs of one suite print different path
    sets while running identical tests; the suites they name are the same
    either way. `_is_suite_path` is this file's existing reading of "the runner
    printed this as a test", and asking it here keeps one answer to that
    question rather than a second one that can drift from it.

    EMPTY IS NOT AN ANSWER ABOUT THE SUITE, which is why the caller treats it as
    NOT KNOWABLE rather than as "ran nothing": a `pre-commit` gate names hooks,
    and an eslint run names the sources it linted, and neither has said which
    suite it was.
    """
    return frozenset(p for p in (named or ()) if _is_suite_path(p))


# What a pair of equal counts turned out to be. Spelled as words for
# `measured_state`'s reason: the answers are not points on a scale, and the
# difference between PROVEN and NOT ESTABLISHED is exactly the difference this
# change must not blur.
SAME_SUITE = "same-suite"
MAYBE_SAME = "not-established"


def shared_counts(steps, named):
    """Steps whose check counts are one measurement rather than two - or may be.

    `named` is parallel to `steps`: each entry is `files_named`'s answer for
    that step, so a set of paths or None.

    THREE READINGS OF ONE EQUALITY, and only the first may change the total:

      * the steps printed the SAME non-empty set of suite paths -> they ran the
        same suite, so the second count is the first count again and adding them
        would report a gate twice its size;
      * at least one of them printed NO suite path -> nothing here can compare
        what they ran. Reported as MAY BE the same and still ADDED, because
        de-duplicating on a resemblance would quietly delete a real count;
      * they printed DIFFERENT suite paths -> they are demonstrably different
        suites that happen to be the same size, which is an ordinary thing for a
        gate to be. Nothing is said and both are added.

    THE THIRD READING IS THE ONE THIS FUNCTION IS GRADED ON. Two suites of equal
    size are common, and a version that collapsed them would under-report every
    such gate - a lie in the opposite direction and a harder one to notice,
    since a total that is too small looks like caution. `sc5` is the allow case
    that goes red the moment the set comparison is weakened to a count
    comparison.

    A ZERO IS NEVER GROUPED. It is additively identical either way, so a group
    over it could only add noise to a run `NO CHECK RAN` already owns entirely.
    """
    by_count = {}
    for idx, step in enumerate(steps or ()):
        ran = step.get("ran")
        if not ran:
            continue
        by_count.setdefault(ran, []).append(idx)
    groups = []
    for ran in sorted(by_count):
        idxs = by_count[ran]
        if len(idxs) < 2:
            continue
        buckets, silent = {}, []
        for idx in idxs:
            suites = suite_paths((named or [])[idx]
                                 if idx < len(named or []) else None)
            if suites:
                buckets.setdefault(suites, []).append(idx)
            else:
                silent.append(idx)
        for suites in sorted(buckets, key=lambda s: sorted(s)):
            members = buckets[suites]
            if len(members) < 2:
                continue
            groups.append({"verdict": SAME_SUITE, "ran": ran,
                           "names": [steps[i]["name"] for i in members],
                           "files": sorted(suites), "silent": None})
        if silent:
            # EVERY STEP AT THIS COUNT, not only the quiet ones: a step that
            # named no suite could be the same run as ANY of the others, so a
            # group listing only the quiet ones would name the wrong parts.
            groups.append({"verdict": MAYBE_SAME, "ran": ran,
                           "names": [steps[i]["name"] for i in idxs],
                           "files": None,
                           "silent": [steps[i]["name"] for i in silent]})
    return groups


def additive_total(steps, shared):
    """`ranTotal`: the SIZE of the gate, with a proven duplicate counted once.

    None WHEN NO STEP ANSWERED, unchanged and load-bearing: a gate whose runners
    publish no count has not told us it ran nothing, and this function may not
    invent a zero to subtract from.
    """
    counts = [st.get("ran") for st in (steps or ()) if st.get("ran") is not None]
    if not counts:
        return None
    total = sum(counts)
    for grp in (shared or ()):
        if grp["verdict"] == SAME_SUITE:
            total -= grp["ran"] * (len(grp["names"]) - 1)
    return total


def human_duration(ms):
    """A step's `durationMs` in the unit a reader compares two steps in.

    None IN, None OUT, the rule the rest of this file follows: a step carrying no
    duration has not told us it was instant, and the caller says so rather than
    printing a zero it measured nowhere.
    """
    if not isinstance(ms, int) or isinstance(ms, bool) or ms < 0:
        return None
    if ms < 1000:
        return "%d ms" % (ms,)
    if ms < 60000:
        return "%.1f s" % (ms / 1000.0,)
    return "%d m %02d s" % (ms // 60000, (ms % 60000) // 1000)


def counts_basis(steps, shared):
    """Why `ranTotal` is the number it is - or why it is not a number at all.

    WRITTEN BY NOTHING BEFORE THIS, WHILE BEING READ BY FOUR THINGS.
    `observations.countsBasis` has been copied by `_evidence_io.row_for` since
    the ledger existed, and the panel and the report both render it - so every
    committed row carried `None` there and the panel printed a hard-coded
    sentence in its place. A three-valued count whose unknown arm ships without
    the basis that explains the unknown is precisely the shape this repo's own
    rule refuses: the claim went out and the thing that makes it checkable did
    not.

    THE PARTIAL CASE IS THE ONE WORTH THE FUNCTION. `ranTotal` is the sum over
    the steps that ANSWERED, so on a mixed gate it is a floor and not a size, and
    a reader with the number alone cannot tell that from a complete count.

    AND `shared` IS WHY THE TOTAL IS NOT ALWAYS THAT SUM (P46.5). Where two
    steps ran one suite the number below counts it once, and where this reader
    could not establish that it adds them and says so - see `shared_counts`. The
    clause is appended HERE rather than given a key of its own for `treeBasis`'s
    reason: the ledger, the report and the panel all render this string already,
    so a field of its own would reach a terminal and none of the three surfaces
    on which a committed row is read.
    """
    if not steps:
        return "no step reported, so there is no count to explain"
    counted = [st for st in steps if st.get("ran") is not None]
    silent = [str(st.get("name")) for st in steps if st.get("ran") is None]
    if not counted:
        basis = ("no step printed a summary this reader can count (%s), so the "
                 "size of this gate is not knowable from its output"
                 % (_output.some_of(silent, budget=SAMPLE_BUDGET),))
    elif silent:
        basis = ("%d of %d step(s) printed a summary this reader counted; %s "
                 "did not, so this total is a floor and not a size"
                 % (len(counted), len(steps),
                    _output.some_of(silent, budget=SAMPLE_BUDGET)))
    else:
        basis = ("counted from each runner's own summary line, over %d step(s)"
                 % (len(steps),))
    for grp in (shared or ()):
        names = _output.some_of(grp["names"], budget=SAMPLE_BUDGET)
        if grp["verdict"] == SAME_SUITE:
            basis += ("; %s each reported %d check(s) over the same suite "
                      "file(s), so that count is in this total ONCE and is not "
                      "added" % (names, grp["ran"]))
        else:
            basis += ("; %s each reported %d check(s) and %s named no suite "
                      "file, so they are ADDED here and may be one suite twice"
                      % (names, grp["ran"],
                         _output.some_of(grp["silent"], budget=SAMPLE_BUDGET)))
    return basis


def never_started(exit_code, ran, outcome):
    """Whether a non-zero step never got as far as running a check (F276).

    `orchestrator.md` step 4c has always drawn this line -- "gates could NOT run
    ... zero tests collected where `tests.add` expects some -> this is NOT the
    task's failure" -- and nothing implemented it, so a runner that died before
    its first test was recorded as a red suite with the task's name on the row.
    That is a false red in a COMMITTED record, which outlives the session that
    could have explained it.

    READ FROM A POSITIVE ZERO ONLY, the rule `run_status` already follows: `ran
    is None` means the runner does not say, which is not evidence that nothing
    ran, and `None == 0` is False rather than a branch to write. A step that
    already carries an `outcome` keeps it: `_shell` observed something more
    specific than this can infer.
    """
    return not outcome and exit_code != 0 and ran == 0


# --- what ENDED the run, as opposed to what it answered -----------------------
# The signals whose DEFAULT DISPOSITION IS TO TERMINATE the process. Spelled as
# NAMES and resolved through `signal.Signals` on the machine the gate is running
# on, because the numbers are not portable: `SIGBUS` is 7 on linux and 10 on
# darwin, where 7 is `SIGEMT` - so a numeric table would name the wrong signal on
# one of the two platforms this plugin supports and there would be no way to see
# it from the other one.
#
# THE SET EXISTS TO NARROW THE CONVENTION ARM AND NOTHING ELSE. `128 + 28` is
# `SIGWINCH`, a signal that is IGNORED by default: nothing was ever killed by it,
# so a step exiting 156 chose that code and must keep it.
TERMINATING_SIGNALS = frozenset((
    "SIGHUP", "SIGINT", "SIGQUIT", "SIGILL", "SIGTRAP", "SIGABRT", "SIGBUS",
    "SIGFPE", "SIGKILL", "SIGUSR1", "SIGSEGV", "SIGUSR2", "SIGPIPE", "SIGALRM",
    "SIGTERM", "SIGXCPU", "SIGXFSZ", "SIGVTALRM", "SIGPROF", "SIGSYS",
))


def _signal_name(number):
    """This platform's name for signal `number`, or None when it names none.

    None rather than a number formatted as a name: a code outside the signal
    range is not a signal, and `ended_by_signal` reads that as "the child chose
    this code" rather than guessing at a kill."""
    try:
        return signal.Signals(number).name
    except (ValueError, AttributeError):
        return None


def ended_by_signal(exit_code, text, command=None):
    """`(name, basis)` for a step the OS ENDED; `(None, None)` for one that answered.

    F302. `sh -c 'kill -9 $$'` and `sh -c 'exit 1'` were one row - both `!= 0`,
    both graded a failing test - while the signal sat on the record as
    `steps[].exit` the whole time.

    TWO CHANNELS WITH TWO DIFFERENT STANDINGS, AND THEY ARE NOT MERGED.

      * A NEGATIVE CODE IS AN OBSERVATION. `waitpid` reported the child as
        signalled and CPython negates the signal number, so `-9` is not a value
        any child CAN return. Nothing can claim this category by exiting with
        it, which is why this arm asks nothing else.
      * `128 + N` IS THE SHELL'S CONVENTION, and it is the only channel that
        exists for the case actually measured. Every step runs under
        `shell=True`, so a runner two levels down that segfaults is reaped by
        `sh`, which then exits 139 - the negative code stops at the shell. A
        reader that took the observation alone would have left the field's own
        instances (2 of 10 recorded failures at exit 139) exactly as they were.

    SO THE CONVENTION ARM IS NARROWED TWICE RATHER THAN TRUSTED, because `lc16`
    pins the objection to it: 127 is NOT read as "could not run", since a real
    command may return 127 deliberately and reading a category out of a number
    lets a child claim the category by exiting with it. This arm fires only for
    a signal that TERMINATES by default, and only where the step's runner printed
    no END-OF-RUN REPORT for the code to be an answer to. A runner that reached
    its own last line has spoken for its exit code - which is what keeps mocha
    where it was, since mocha exits with the NUMBER OF FAILING TESTS and 139
    failures really is exit 139.

    AND THE SECOND NARROWING IS THE RUNNER'S OWN REPORT, NEVER THIS READER'S
    COUNT (F323). It used to be `ran is not None`, which is a fact about whether
    the counting readers in this file recognised the output - a different
    question, wrong in both directions and measured in both:
    `mocha --reporter json` at exit 139 excused 139 real failures as
    infrastructure, and `pre-commit` could never reach this arm at all because
    its count is a tally of LINES and so is never None. `reached_a_verdict` is
    the question this actually needed, and it carries the residual risk it cannot
    close. `command` is handed to it rather than kept here: whether a marker in
    the output speaks for THIS step depends on whether the step is one runner or
    a wrapper around several (F352), and that is a fact about the command.

    THE BAND IS DERIVED AND NOT PASTED, which is the difference between this and
    the two numbers a field report can hand you. The reported band is 128 to 165;
    what is asked here instead is whether `code - 128` names a signal ON THIS
    MACHINE that terminates by default, so the answer is narrower at the top (the
    upper reaches of that band name no signal at all) and narrower INSIDE it -
    `SIGCHLD`, `SIGCONT`, `SIGURG` and `SIGWINCH` all live in there and nothing
    is ever killed by one. `TERMINATING_SIGNALS` above is the whole of that
    judgement and `sk6` in `plugins/audit/tests/test_run_test_gate.py` is what
    prints the accepted codes, so neither has to be taken on trust from a
    sentence here.

    AND THE REMAINING FALSE POSITIVE IS IN THE TOLERABLE DIRECTION, which is the
    honest way to state a heuristic's cost. A silent runner that chose exit 137
    on its own would be called infrastructure: the run still refuses, still
    carries a word no surface may sign off, and the loss is a retry not spent -
    a stall a reader can see, never a green over red.

    WHAT IT DOES NOT READ. On windows a crash arrives as an NTSTATUS in the exit
    code (an access violation is 3221225477, not 139) and this decodes none of
    them, so a crashed step there is still graded as a failing one. That is a
    stated gap with a case on it, not a silent one.
    """
    try:
        code = int(exit_code)
    except (TypeError, ValueError):
        return None, None
    if code < 0:
        name = _signal_name(-code) or "signal %d" % (-code,)
        return name, ("the OS reported this child as killed by %s; a child "
                      "cannot RETURN a negative code, so this is observed and "
                      "not inferred" % (name,))
    # `<= 128` and not `< 128`: 128 would be signal 0, which kills nothing.
    if code <= 128 or reached_a_verdict(text, command):
        return None, None
    name = _signal_name(code - 128)
    if name not in TERMINATING_SIGNALS:
        return None, None
    return name, ("exit %d is the shell's convention for a child killed by %s, "
                  "and this step's runner printed no end-of-run report of its "
                  "own for the code to be an answer to" % (code, name))


# --- what a SECOND attempt may change, and what it may not --------------------
# THE CLASSIFICATION ABOVE IS THE PRECONDITION AND THIS IS WHAT IT BUYS. A step
# the OS ended reached no verdict, so the run refuses and an operator re-runs it
# by hand - which is where a whole session of them went, one command at a time,
# for a cause the command itself declares.
#
# THE KNOB IS IN THE COMMAND. A parallel suite whose workers each start their own
# in-memory database is bounded by memory PER WORKER, and the same gate was
# answered at a lower worker count and killed at a higher one, run for run. So a
# second attempt at a lower bound asks a question the first attempt could not
# answer, rather than rolling the same dice again.
#
# AND IT MAY NEVER REACH A STEP THAT REPORTED. A non-zero exit BESIDE an
# end-of-run report is a measurement, and re-running a measurement until it comes
# back green is the fault the whole no-verdict vocabulary exists to prevent, one
# door along. `ended_by_signal` is the separation and nothing here re-decides it:
# the retry is keyed on the signal that function reports, never on an exit code,
# so a suite that spoke for its own status cannot be reached from here at all.
#
# The flags a runner is told its worker count through, and the runner name a
# SHORT spelling has to appear beside. A long flag names its own subject; one
# letter does not - `-n` is the worker count for pytest-xdist and the LINE COUNT
# for a pager, and a gate entry is as often a pipeline as it is one command. So a
# short spelling is read only where the command also names the runner that spells
# it that way, which is the narrowing `_STEP_WORDS` already makes for a different
# question. The direction that costs is stated where it is taken: a bound this
# reader cannot see is reported as one it cannot lower, never as a reduction it
# did not make.
_PARALLEL_FLAGS = (
    ("--jobs", None),
    ("-j", None),
    ("--numprocesses", None),
    ("-n", "pytest"),
    ("--maxWorkers", None),
    ("--max-workers", None),
    ("--workers", None),
)

# Where one program in a gate entry ends and the next begins. A gate entry is a
# SHELL STRING - `meta.nodePreamble` is joined onto the front of one with `&&`,
# and piping a runner into a pager is ordinary - so "the command names pytest"
# is not the same question as "THIS program is pytest", and only the second one
# licenses reading a one-letter flag as a worker count.
_SHELL_BREAK = re.compile(r"[|&;]+")


def _program_at(command, index):
    """The one program's worth of `command` that position `index` falls inside.

    NOT A SHELL PARSER AND IT DOES NOT NEED TO BE. A break character inside a
    quoted argument splits a segment that should not have been split, which can
    only make a flag fail to be attributed to its runner - the direction this
    whole reader is allowed to be wrong in, since the answer there is "no bound
    this reader can lower" and the command runs again unchanged.
    """
    text = command or ""
    start = 0
    for match in _SHELL_BREAK.finditer(text):
        if match.start() > index:
            return text[start:match.start()]
        start = match.end()
    return text[start:]


def parallelism_flags(command):
    """Every worker bound `command` declares: `(flag, value, start, end)`, in order.

    `value` IS THE RAW TOKEN and the span is where it sits in the string, so a
    caller lowers a number by splicing rather than by rebuilding the command.
    Splitting a shell command on whitespace and joining it back collapses the
    spacing inside a quoted argument, which would make the second attempt a
    differently-spelled command for a reason nobody asked for.

    EVERY HIT COMES BACK AND NONE IS PREFERRED. Which of two parallelism-shaped
    flags bounds the workers is not a question a string can answer, and the
    caller's answer to more than one is to lower neither and say so - a guess
    there rewrites a flag that may belong to a different program in the pipeline.
    """
    hits = []
    for flag, runner_name in _PARALLEL_FLAGS:
        # A long flag takes its value after a separator; a short one may carry it
        # with none at all (`-j4`). The lookbehind is what keeps `-j` from
        # matching inside `--jobs` and `-n` from matching inside
        # `--numprocesses`, so one spelling is never counted as two.
        gap = "[= \t]*" if len(flag) == 2 else "[= \t]+"
        pattern = "(?<![\\w=/.-])%s%s([^\\s]*)" % (re.escape(flag), gap)
        for match in re.finditer(pattern, command or ""):
            # THE RUNNER MUST BE THIS PROGRAM AND NOT MERELY SOMEWHERE IN THE
            # LINE. `pytest -q | head -n 20` names pytest and the `-n` belongs
            # to the pager; asking the whole string would have lowered the
            # pager's line count and called the result a smaller measurement.
            program = _program_at(command, match.start())
            if runner_name and runner_name not in program:
                continue
            hits.append((flag, match.group(1), match.start(1), match.end(1)))
    return sorted(hits, key=lambda hit: hit[2])


def lowered_parallelism(command):
    """`(command, basis)` - the same gate under a smaller bound, or None and why not.

    THE NUMBER IS DERIVED FROM WHAT THE COMMAND DECLARED, never chosen here. A
    figure written into this file would be a claim about somebody else's host -
    the ceiling is memory per worker, so it moves with the machine and with the
    suite - and it would stop being derived the moment either changed. Halving is
    the largest single step that still leaves the gate running in parallel, and a
    step down BY ONE from a large bound barely moves the memory it is the bound
    on.

    None IS A REAL ANSWER AND IT IS THE MAJORITY ONE. Four separate states reach
    it - no flag this reader knows, more than one candidate, a value that is not
    a number, and a bound with nothing below it that is still a run - and each
    says which it was, because "the second attempt ran the same command" and "the
    second attempt ran a smaller one" are different claims about what was
    measured and the caller has to be able to say which happened.
    """
    hits = parallelism_flags(command)
    if not hits:
        return None, ("this command declares no worker bound this reader can "
                      "see, so the second attempt ran it UNCHANGED - nothing "
                      "about the work was made smaller, only the moment it ran")
    if len(hits) > 1:
        # THE SPELLINGS ARE PRINTED AS WRITTEN AND NOT DE-DUPLICATED: one flag
        # appearing twice is the shape this arm exists for - a runner and a pager
        # in one pipeline agreeing on a letter - and collapsing the two would
        # print a sentence about "more than one" beside a single name.
        return None, ("this command carries %d parallelism-shaped flag(s) (%s), "
                      "so which of them bounds the workers is not knowable from "
                      "the string - the second attempt ran it UNCHANGED rather "
                      "than lowering one that may belong to another program in "
                      "the pipeline"
                      % (len(hits),
                         ", ".join("%s %s" % (hit[0], hit[1]) for hit in hits)))
    flag, value, start, end = hits[0]
    try:
        workers = int(value)
    except ValueError:
        return None, ("this command declares its parallelism as `%s`, whose "
                      "value is not a number this reader can lower, so the "
                      "second attempt ran it UNCHANGED" % (flag,))
    if workers <= 1:
        return None, ("`%s` is already %d here, and there is no bound below it "
                      "that is still a run - so the second attempt ran the "
                      "command UNCHANGED" % (flag, workers))
    lowered = workers // 2
    return (command[:start] + "%d" % (lowered,) + command[end:],
            "`%s` was lowered from %d to %d for the second attempt, so it "
            "measured the same gate under a smaller bound"
            % (flag, workers, lowered))


def retry_note(signal_name, change):
    """The sentence a retried step carries on every surface that shows its verdict.

    IT SAYS WHICH ATTEMPT THE VERDICT BESIDE IT IS, and that is the one fact a
    reader cannot recover from anything else on the row. `exit`, `ran`,
    `durationMs` and `outcome` all describe the attempt that produced them, and
    none of them says an earlier attempt was ended and thrown away - so a green
    line with nothing beside it reads as a gate that answered, when what happened
    is that a gate was killed and a different question was then asked.
    """
    return ("the OS ended the FIRST attempt of this step (%s), so it was run "
            "once more and the verdict beside this note is the SECOND "
            "attempt's: %s. A second attempt is a different measurement and not "
            "a confirmation of the first." % (signal_name, change))


# --- did it touch what the task owns ------------------------------------------
# Paths as a runner prints them. Deliberately not a general path grammar: a token
# is a candidate only if it carries a `/` or a dot-extension, which is what keeps
# `Passed`, `9 tests` and a hook's name out of the set. Over-matching here is
# harmless (a spurious path can only ADD overlap, and overlap is reported rather
# than enforced) but under-matching is not, which is why the empty result is
# reported as NOT KNOWABLE rather than as "nothing overlapped".
_PATHISH = re.compile(r"[A-Za-z0-9_.@/\\-]*[/][A-Za-z0-9_.@/\\-]*"
                      r"|[A-Za-z0-9_@-]+\.[A-Za-z][A-Za-z0-9]{0,8}")


def files_named(text):
    """The paths a runner's output mentions, POSIX-spelled, or None if it names none.

    None is NOT an empty set, for `_tree_stamp.porcelain`'s reason one module
    over: a
    runner that prints no paths has told us nothing about coverage, and rendering
    that as "none of them names a file this task owns" would be the false claim
    this whole file exists to prevent.
    """
    found = set()
    for raw in _PATHISH.findall(text or ""):
        tok = raw.strip().strip(":,;\"'()[]").replace("\\", "/")
        if tok and not tok.endswith("/"):
            found.add(tok.lstrip("./"))
    return found or None


# The suffixes a test file carries in front of its extension, across the runners
# this script actually meets. Used to relate `src/foo.test.ts` to `src/foo.ts`
# (F255) and NOWHERE ELSE: a path that is not test-shaped is never re-spelled.
_TEST_MARKS = (".test", ".spec", "_test", "_spec", "-test", "-spec")


def _subject_of(path):
    """The file a TEST path is about, or None when the path is not test-shaped.

    `tests/foo.spec.ts` -> `foo`, `src/foo.test.ts` -> `foo`, `src/foo.ts` -> None.
    The basename alone, because the two live in different directories as often as
    not - `src/foo.ts` tested from `tests/foo.spec.ts` is the ordinary layout.

    DELIBERATELY NARROW. `_PATHISH` above can over-match harmlessly because a
    spurious path only ADDS overlap and overlap is reported rather than enforced.
    That reasoning does NOT carry here: a false overlap tells the reader their work
    was exercised when it was not, which is the exact false comfort `NO OVERLAP`
    exists to prevent. So this fires only on a path that really is spelled like a
    test, and only onto a file whose stem it matches exactly.
    """
    base = str(path or "").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for mark in _TEST_MARKS:
        if stem.endswith(mark) and len(stem) > len(mark):
            return stem[:-len(mark)]
    return None


# The directory names a vendored dependency tree wears. A path inside one is code
# NOBODY'S task declares, so it can never be evidence about the work under test -
# and on a failing jest run the stack frames under `node_modules` are the bulk of
# what `_PATHISH` harvests.
_VENDOR_DIRS = frozenset((
    "node_modules", "bower_components", "site-packages", "vendor", "venv",
    ".venv", ".tox",
))
# ...and the directory names a suite lives in when its FILE NAME does not say so.
# `__tests__/order.ts` is jest's own layout and carries no `.test` mark at all, so
# `_subject_of` cannot see it. Read for the CLASSIFICATION only and never for the
# match - a directory is far too weak to re-spell a path onto another file's stem,
# which is the thing `_subject_of` guards.
_TEST_DIRS = frozenset((
    "__tests__", "__test__", "test", "tests", "spec", "specs", "e2e",
))


def _extension(path):
    """The suffix a path is spelled with, lowercased - `""` when it carries none.

    Read off the BASENAME, so a dotted DIRECTORY cannot lend its suffix to a file
    that has none. A leading dot is a NAME and not a suffix: `.gitignore` has no
    extension, which is why the scan starts at the second character.
    """
    base = str(path or "").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[1].lower() if "." in base[1:] else ""


def _kinds(paths):
    """The extensions a path set is spelled with, ordered, `""` shown as itself."""
    return sorted(set(_extension(p) or "(no extension)" for p in (paths or ())))


def _segments(path):
    """A path's directory segments, POSIX-spelled, without its basename."""
    return str(path or "").replace("\\", "/").split("/")[:-1]


def _is_suite_path(path):
    """Whether the runner printed this as a TEST IT RAN rather than as a file it
    processed.

    TWO READINGS, and the second is why this is not `_subject_of` under another
    name: a suite says so in its FILE NAME (`order.test.ts`) or in its DIRECTORY
    (`__tests__/order.ts`, jest's own layout, which carries no mark).
    `_subject_of` may use only the first, because it re-spells a path onto
    another file's stem and a directory is far too weak to justify that.
    Classifying is the weaker job, so it may read the weaker signal.
    """
    return (_subject_of(path) is not None
            or any(seg in _TEST_DIRS for seg in _segments(path)))


def evidence_paths(owned, named):
    """The printed paths an EMPTY overlap could be negative evidence from (F307).

    THE POPULATION TEST. It decides only what an empty overlap MEANS and never
    what matches - the match is untouched, because widening the stem match is
    what would make this check mean less: a false overlap tells a reader their
    work was exercised when it was not, which is the comfort `NO OVERLAP` exists
    to refuse.

    THE FAULT. `NO OVERLAP WITH THIS WORK` fired on roughly 20 of 30 runs in one
    jest repository, INCLUDING runs whose coverage was obvious, because jest
    prints the SUITE it ran while `task.files` lists the sources under it. The
    only bridge between the two is `_subject_of`'s naming convention, so where a
    suite is named for a feature rather than for a file the overlap is a real
    empty set over a real path set: literally true, and useless. A line that
    fires on two runs in three teaches a reader to skim the block a real finding
    appears in, which is the opposite of what it is for.

    SO THE QUESTION IS THE ONE NOBODY WAS ASKING: could a run that DID exercise
    this work have printed one of these paths AS the declared file? Three ways
    the answer is no, each with its own reason:

      * A VENDORED PATH is a dependency nobody declares - a stack frame under
        `node_modules` is not a file any task owns, so its presence says nothing
        either way.
      * A SUITE PATH OF THE WORK'S OWN KIND is the F307 case exactly. Jest never
        prints the sources a suite exercised, so the naming convention was the
        only bridge and it missed - and what the empty overlap then measured is
        the naming convention.
      * ...WHILE A SUITE PATH OF A DIFFERENT KIND IS THE OPPOSITE, and it is the
        firing this keeps. F204's founding run - a vitest UI suite, two
        `.test.js` files, nine tests green, against a one-value edit to a
        `.json` manifest - printed nothing spelled like that manifest at all.
        Those suites demonstrably are not about that file, and saying so IS the
        finding.

    ANYTHING ELSE IS A PATH THE RUNNER PROCESSED and is kept, which is the other
    firing that had to survive: F255's second field report is eslint and tsc
    naming real `.ts` sources, none of them the `.md` that task owned - and so
    is the same runner against a `.ts`-owning task whose file it never linted. A
    rule reading extensions alone would have gone quiet on the second of those,
    which is why the suite/processed split is the primary reading and the
    extension only chooses between the two SUITE cases.

    THE LIMIT, STATED. A task declaring a TEST file of its own, measured by a
    runner naming other suites in the same language, comes back "not knowable"
    where "no overlap" would have been true. That is a weaker claim rather than
    a false one, and it is the direction this repair is allowed to be wrong in.
    """
    kinds = set(_extension(f) for f in (owned or ()))
    keep = []
    for path in (named or ()):
        if any(seg in _VENDOR_DIRS for seg in _segments(path)):
            continue
        if _is_suite_path(path) and _extension(path) in kinds:
            continue
        keep.append(path)
    return sorted(keep)


def coverage(task_files, named):
    """`(overlap, basis)` -- which of the task's files the run actually named.

    A RUNNER THAT PRINTS ONLY SUITE PATHS STILL NAMES YOUR WORK (F255). Two field
    reports disagreed about this line and both were right about their own run:
    one saw `NO OVERLAP` on 9 of 12 tasks because jest prints suite paths while
    `task.files` lists the sources under them, and the other called this line the
    best thing in the plugin because eslint and tsc named real files and none of
    them was the Markdown that task owned. The two are different situations that
    the old comparison rendered identically.

    The repair is the MATCH, never a threshold or a mute. `src/foo.test.ts` is
    related to `src/foo.ts` and is counted; `src/a.ts` is unrelated to `docs/x.md`
    and is not - so the first report's tasks report coverage they really had, and
    the second report's `NO OVERLAP` still fires exactly where it did.
    """
    owned = [f for f in (task_files or []) if isinstance(f, str) and f.strip()]
    if not owned:
        return None, ("the work under test declares no files, so there is "
                      "nothing to relate a run to")
    if named is None:
        return None, ("this runner printed no file paths, so coverage is not "
                      "knowable from its output")
    subjects = set(s for s in (_subject_of(n) for n in named) if s)

    def _stem(path):
        base = str(path).rsplit("/", 1)[-1]
        return base.rsplit(".", 1)[0] if "." in base else base

    hits = sorted(f for f in owned
                  if any(n == f or n.endswith("/" + f) or f.endswith("/" + n)
                         for n in named)
                  or _stem(f) in subjects)
    basis = ("the runner named %d path(s); the work under test declares "
             "%d file(s)" % (len(named), len(owned)))
    if subjects:
        basis += ("; %d of them are test paths, matched to the files they are "
                  "named after" % (len([n for n in named if _subject_of(n)]),))
    # F270. TWO COUNTS ARE NOT A DIAGNOSIS. `NO OVERLAP WITH THIS WORK` was
    # reported firing on every gate run of one session, including tasks whose own
    # suite went green - and at that rate a line becomes noise people skip, which
    # is the opposite of what it is for. The reported cause was wrong: `named` is
    # not empty, it is UNRELATED. `_PATHISH` harvests `node_modules` stack frames,
    # `jest.config.js`, the echoed command line, URLs and dotted identifiers, so
    # the overlap is a real empty set over a real path set and the verdict is
    # literally true and practically useless. Naming a bounded sample is what
    # lets a reader see in one second that the runner printed config files and
    # stack frames rather than suites - the thing two counts can never show.
    basis += ("; among them: %s"
              % (_output.some_of(sorted(named), budget=SAMPLE_BUDGET),))
    # F307. AN EMPTY OVERLAP IS ONLY EVIDENCE FROM PATHS THAT COULD HAVE NAMED
    # THIS WORK, and this is the one place the difference shows: a HIT needs no
    # population test at all, because a match is its own proof that the two sets
    # meet. So the question is asked here and nowhere else - see `evidence_paths`
    # for what it asks and for the two firings it deliberately keeps.
    if not hits and not evidence_paths(owned, named):
        return None, ("%s; and not one of those could have named this work - "
                      "every one is a suite of the kind the work itself is "
                      "spelled in (%s) or a vendored dependency, and a runner "
                      "that prints the suites it ran has not said which sources "
                      "they exercised. So whether this run touched the declared "
                      "work is NOT KNOWABLE from its output; it is not evidence "
                      "that it did not"
                      % (basis, _output.some_of(_kinds(owned),
                                                budget=SAMPLE_BUDGET)))
    return hits, basis


def owned_files(manifest, phase_id, task_id=None):
    """`(files, error)` -- what the work under test declares it owns.

    Computed for the PHASE by default and not only for a named task, because the
    phase gate is the call site this script actually has: `orchestrator.md` runs
    it as `<manifestPath> <phaseId>` at sign-off. A `--task` that nothing invokes
    would be a capability with no caller, which is a fact nobody reads.
    """
    for phase in (manifest.get("phases") or []):
        if not isinstance(phase, dict) or phase.get("id") != phase_id:
            continue
        tasks = [t for t in (phase.get("tasks") or []) if isinstance(t, dict)]
        if task_id is None:
            seen, union = set(), []
            for task in tasks:
                for f in (task.get("files") or []):
                    if f not in seen:
                        seen.add(f)
                        union.append(f)
            return union, None
        for task in tasks:
            if task.get("id") == task_id:
                return list(task.get("files") or []), None
        return None, "no task %r in phase %r" % (task_id, phase_id)
    return None, "no phase %r in this manifest" % (phase_id,)


def attempt_of(manifest, task_id):
    """Which attempt this run is, when the plan RECORDS one -- else None.

    THE ROW COPIES WHAT THE PLAN SAYS AND COUNTS NOTHING ITSELF. `attempts` is
    the orchestrator's field: it increments per execution, and two documented
    paths take it back DOWN -- a reverted increment after an infrastructure
    failure, and `/audit:run` resetting a blocked or re-opened task. A runner
    that added one of its own, or that read a recorded 0 as "surely at least
    one", would put a number on a committed record that no field of the plan
    holds. `_manifest_io.recorded_attempt` is where that reading lives, once.

    NO TASK IN QUESTION MEANS NO ANSWER, and that is the plan being read
    correctly rather than a gap: `attempts` is a TASK field
    (`_manifest_vocab.KNOWN_TASK`), so a phase-scope run has nothing to read and
    an absent `attempt` is the only true thing to say about it. The same holds
    for a `--task` naming something this manifest does not carry, which
    `owned_files` and `gate_of` have already refused by the time this is asked.

    WHAT IT DOES NOT EVIDENCE. This answers "was this task run more than once?"
    across the retries the orchestrator drives. It is NOT a red-then-green
    record: `reference/orchestrator.md` runs the recorded gate AFTER the executor
    subagent returns, so a correct TDD cycle records one row and it is green.
    Nothing downstream may read a failing attempt into its absence.
    """
    if task_id is None:
        return None
    return _mio.recorded_attempt(_mio.tasks_by_id(manifest).get(task_id))


def declared_gate(entries, build):
    """`[(name, command)]` - what the MANIFEST says this gate is, and nothing else.

    THE DECLARATION, SEPARATED FROM THE EXECUTION. `_resolved` puts the
    operator's preamble in front of each of these before a shell sees it, and the
    two are different things to compare: the preamble is a property of the
    machine the gate is being run on, and two machines running the same declared
    gate must not read as two different gates. Spelled once and called twice so
    the pair cannot come apart.
    """
    return [(e, build.get(e, e)) for e in entries
            if isinstance(e, str) and e.strip()]


def _resolved(entries, build, preamble=None):
    """`[(name, command)]` - gate entries through `meta.buildCommands`, once.

    THE ONE RESOLUTION, shared by both scopes on purpose. A task gate and a phase
    gate are two declarations of the same kind, and resolving them in two places
    would be two answers to "what is a gate entry" the first time the map grew a
    rule. An entry naming no build command is carried VERBATIM, because it may be
    a literal shell command and refusing it would make this script decide what a
    gate is allowed to be.

    `meta.nodePreamble` IS APPLIED HERE, and it was applied nowhere (F253). The
    document has instructed callers to run it before every build gate since it
    shipped; this script spawns its OWN shell per command, so a preamble the caller
    exported into a different one reaches nothing. Measured on a live run: two gate
    rows recorded exit 127 for a `PATH` problem, so a committed ledger carries two
    false failures permanently. A gate that records a false red is worse than a gate
    that does not run, because the row outlives the session that could explain it.

    JOINED WITH `&&`, which is what "un-piped" in `orchestrator.md` asks for: a pipe
    would hand the gate's exit status to the preamble's tail and lose the verdict.
    A whitespace-only value is not a preamble - prefixing it would make every gate
    on that manifest die of a shell syntax error, which is the same false red one
    door along.
    """
    lead = (preamble or "").strip() if isinstance(preamble, str) else ""
    return [(e, ("%s && %s" % (lead, command)) if lead else command)
            for e, command in declared_gate(entries, build)]


def gate_of(manifest, phase_id, task_id=None):
    """`(commands, source, error)` -- the gate to run, and WHOSE it is.

    `source` is `"task"` or `"phase"`, and it is returned rather than inferred by
    the caller because the fallback must not be silent: a task that declares no
    gate of its own is measured by the PHASE's, and "this task's gate passed" and
    "the phase's gate passed while pointed at this task's files" are different
    claims for a record to make.

    ABSENT AND EMPTY ARE ONE ANSWER. A task with no `tests` block and a task with
    `tests.gate: []` both declare no gate, so they take one path; making them two
    would be two chances to disagree about the same question.

    AN UNKNOWN TASK IS AN ERROR, never a quiet fall back to the phase - the
    distinction `owned_files` already draws, and for its reason: "declares no
    gate" and "there is no such task" must not print the same way.
    """
    phases = [p for p in (manifest.get("phases") or [])
              if isinstance(p, dict) and p.get("id") == phase_id]
    if not phases:
        return None, None, "no phase %r in this manifest" % (phase_id,)
    build = ((manifest.get("meta") or {}).get("buildCommands") or {})
    if not isinstance(build, dict):
        build = {}
    # Read beside `buildCommands` because it is the same kind of declaration: what a
    # gate entry becomes before a shell sees it (F253).
    preamble = (manifest.get("meta") or {}).get("nodePreamble")
    if task_id is not None:
        tasks = [t for t in (phases[0].get("tasks") or [])
                 if isinstance(t, dict) and t.get("id") == task_id]
        if not tasks:
            return None, None, "no task %r in phase %r" % (task_id, phase_id)
        tests = tasks[0].get("tests")
        entries = (tests.get("gate") or []) if isinstance(tests, dict) else []
        resolved = _resolved(entries, build, preamble)
        if resolved:
            return resolved, "task", None
    return (_resolved(phases[0].get("testGate") or [], build, preamble),
            "phase", None)


# --- a verdict already measured on these bytes --------------------------------
# WHAT MAKES TWO GATE RUNS THE SAME RUN. Three things, and the identity is the
# digest of all three together:
#
#   * THE TREE'S CONTENT, through `_tree_stamp.content_digest`. Not
#     `testedState`: that block's dirty digest records WHICH paths were dirty and
#     never their contents, so keying on it would repeat a verdict across a real
#     edit to any file the work does not declare - a stale answer standing in for
#     a real one, which is the failure this runner has already been repaired for
#     from the other end.
#   * THE GATE THE MANIFEST DECLARES - `declared_gate`, the entries and what each
#     one names. NOT the executed string, which is what the row stores verbatim:
#     that string carries `meta.nodePreamble` in front of it, which is the shell
#     prelude the machine needs, and two operators whose preludes differ would
#     never match though they declared one gate between them. What an entry
#     RESOLVES to is in the comparison because an entry alone is a label: remap
#     `lint` and the label holds still while the gate becomes a different one.
#   * THE FILES THE WORK DECLARES, because they are not a label either. The
#     ownership split, the coverage answer and the excused red are all read
#     against that list, so two runs over one tree with different declared files
#     reach different verdicts and are not one run.
#
# WHAT THE IDENTITY DOES NOT ESTABLISH IS PRINTED BESIDE IT, in `REUSE_LIMIT`.
REUSE_LIMIT = ("the tree's content and the gate the manifest declares - not that "
               "the machine is the one that measured. A file git ignores, an "
               "installed package, an environment variable, the clock, the "
               "network and a check that answers differently twice are all "
               "outside it, and so are this plugin's own records: the manifest, "
               "its shards, the ledger and the trail are left out because a "
               "recorded run rewrites them")

# WHICH VERDICTS SURVIVE BEING REPEATED, and it is a short list on purpose.
# `passed` and `failed` are statements about the work under test that the same
# bytes through the same commands have to reproduce. The other four are not:
#
#   * `could-not-run`, `timed-out` and `cancelled` are facts about the machine or
#     the operator - a missing interpreter, a load spike, a Ctrl-C. Repeating one
#     would cache an infrastructure failure the operator has probably just fixed,
#     and the fix is not in the tree.
#   * `gate-mutated` and `no-checks` are true of the tree, and repeating them
#     would still be a lie about THIS run: the first says the gate rewrote files
#     it was grading and nothing was rewritten here, the second says every step
#     reported zero checks and no step reported anything here.
#
# SPELLED AS TWO SETS RATHER THAN ONE AND A SUBTRACTION, so a word added to the
# runner's vocabulary lands in neither and is caught by the case that asks for
# the union, instead of falling into whichever half the arithmetic hands it.
REUSABLE_STATUS = frozenset(("passed", "failed"))
NOT_REUSABLE_STATUS = frozenset((GATE_MUTATED, "no-checks", TIMED_OUT,
                                 CANNOT_RUN, CANCELLED))


def subject_ids(phase_id, task_id, source):
    """The identity keys a run is filed under, spelled once.

    The lookup and the write have to agree about what "the same work" is: an
    answer computed twice is two answers, and the failure would be a verdict
    repeated from a run about somebody else's task.
    """
    ids = {"phaseId": phase_id}
    if source == "task" or task_id:
        ids["taskId"] = task_id
    return ids


def grades_left_out(gate, excluded):
    """The gate entries whose command NAMES a path this identity leaves out.

    WHY AN ENTRY CAN BE ITS OWN COUNTER-EXAMPLE. The content identity drops the
    paths this plugin writes itself - the manifest, its shards, the ledger, the
    trail - because a recorded run rewrites all four and no later run could
    otherwise ever match. That reasoning is about the RECORDER. It says nothing
    about an entry whose subject happens to be one of those files, and for such
    an entry the exclusion removes exactly the bytes it is grading: driven, a
    gate whose one entry validates the plan reported green over a plan that no
    longer validated, and wrote `passed` into the phase.

    WHAT IS ESTABLISHED HERE IS THAT THE COMMAND NAMES THE PATH, and not that it
    reads it - nothing short of running it could establish that, and running it
    is the cost this whole feature exists to avoid. So the conclusion is the
    conservative one and the sentence says which it is: a named path means the
    verdict is MEASURED rather than repeated. Wrong in this direction costs a run;
    wrong in the other direction is a stale pass, which is the failure the rest of
    this module is written against.

    The basename is matched as well as the path, because a gate entry commonly
    names the plan the way the operator types it rather than the way the manifest
    resolves it.
    """
    named = []
    for name, command in gate or []:
        text = command if isinstance(command, str) else ""
        for path in excluded or []:
            if not (isinstance(path, str) and path.strip()):
                continue
            if path in text or os.path.basename(path) in text:
                named.append((name, path))
                break
    return named


def reuse_identity(project, manifest_path, manifest, commands, owns):
    """`{key, basis, limit, grading}` - what this run would have to match to be a
    repeat, and the entries that stop it being one.

    `key` is None when the tree's content could not be established; the basis
    then says why, and a None never matches a None - `reusable_run` refuses an
    empty key outright, for `field_state`'s reason one module over.

    `grading` is non-empty when an entry names a path the identity leaves out.
    The key is still computed and still recorded in that case, because the row
    has to carry what this run was taken on whether or not a repeat was allowed -
    a run that recorded no identity leaves the next one nothing to match.
    """
    excluded = _ev.recorded_paths(project, manifest_path)
    content, cbasis = _tree_stamp.content_digest(project, excluded=excluded)
    build = ((manifest.get("meta") or {}).get("buildCommands") or {})
    if not isinstance(build, dict):
        build = {}
    gate = [[name, command] for name, command
            in declared_gate([n for n, _c in (commands or [])], build)]
    scope = _tree_stamp.declared_scope(owns)
    grading = grades_left_out(gate, excluded)
    if content is None:
        return {"key": None, "basis": cbasis, "limit": REUSE_LIMIT,
                "grading": grading}
    return {"key": _tree_stamp.identity_of([content, gate, scope]),
            "basis": "%s; over that, the %d gate command(s) this manifest "
                     "declares and the %d file(s) the work under test declares"
                     % (cbasis, len(gate), len(scope)),
            "limit": REUSE_LIMIT,
            "grading": grading}


def reused_result(identity, row, elapsed_ms):
    """`run_gate`'s shape for a verdict that was NOT taken here.

    THE SHAPE IS KEPT AND THE CLAIMS ARE NOT. Every observation a run makes is
    None on this dict with the sentence that says why, because nothing was
    observed: no command ran, so no tree bracket was taken, no runner named a
    path and no check was counted. An empty list in any of those places would be
    a measurement, and this run made none.

    `status` AND `failed` ARE COPIED, which is the one claim that crosses. They
    are the verdict being repeated - that is the whole point - and `reusedFrom`
    names the row they came from on the same dict, so a reader who doubts the
    copy has the original.
    """
    return {
        _ev.VERDICT_SOURCE: _ev.REUSED,
        "status": row.get("status"),
        "failed": list(row.get("failed") or []),
        "steps": [],
        "reusedFrom": {"runId": row.get("runId"), "ts": row.get("ts"),
                       "status": row.get("status")},
        _ev.REUSE_KEY: identity.get("key"),
        "reuseBasis": identity.get("basis"),
        "durationMs": elapsed_ms,
        "treeMutated": None,
        "treeBasis": "no command ran, so the tree was not bracketed",
        "treeMutatedOwned": None, "treeMutatedForeign": None,
        "ranTotal": None,
        "countsBasis": "no command ran, so nothing here counted a check",
        "sharedCounts": [],
        "notAttributable": None, "attributionBasis": None,
        "cancelledBy": None,
        "overlap": None,
        "coverageBasis": ("no command ran, so no runner named a path here; the "
                          "run named above is where that question was asked"),
    }


def render_reuse(res, out=print):
    """Print a verdict nothing here measured, and return the code it earns.

    THE BLOCK COMES FIRST AND THE BANNER STILL COMES. `reference/orchestrator.md`
    keys its arms on the banner literals, so a repeat printed under a banner of
    its own would be a line that document has never heard of and an orchestrator
    reading it would fall through - the same consequence chain a killed step's
    member was given its existing banner to avoid. So the reader meets "nothing
    ran" before they meet the verdict, and the machine still meets the word it
    switches on.
    """
    prior = res.get("reusedFrom") or {}
    out("GATE VERDICT REUSED: nothing ran here. This verdict was MEASURED by run "
        "%s at %s, on a tree with the identity below, and is being repeated "
        "rather than re-taken." % (prior.get("runId"), prior.get("ts")))
    out("  identity: %s" % (res.get(_ev.REUSE_KEY),))
    out("  basis:    %s" % (res.get("reuseBasis"),))
    out("  says:     %s" % (REUSE_LIMIT,))
    out("  measure:  re-run with --no-reuse to take this gate again on this tree.")
    if res["status"] == "failed":
        out("GATE RED: %s" % ", ".join(res.get("failed") or []))
        return E_FAIL
    if res["status"] != "passed":
        # REACHABLE THROUGH THIS FUNCTION AND NOT THROUGH `main`, which only ever
        # repeats a `REUSABLE_STATUS` word. Refusing loudly rather than falling
        # through to the green line is what stops a word added to one of those
        # sets and forgotten here from being printed as a pass.
        out("GATE COULD NOT RUN: the recorded verdict is %r, which is not a word "
            "this repeat knows how to state. Nothing was measured here and "
            "nothing may be read from it - re-run with --no-reuse."
            % (res["status"],))
        return E_FAIL
    out("GATE GREEN: verdict reused from run %s; no check ran here."
        % (prior.get("runId"),))
    return E_OK


def _spawn_kwargs():
    """Popen kwargs that put the child in a group we can tear down whole.

    POSIX gets `start_new_session` (setsid), so the shell becomes a process-group
    LEADER and `killpg` reaches everything it started. Windows gets its own
    process group for the same purpose. A platform offering neither is left alone
    rather than guessed at - `_tear_down` then reports that it could not confirm.

    THE TRADE IS DELIBERATE AND IS THE REASON THE HANDLER IN `main` EXISTS.
    Detaching from the controlling terminal means a Ctrl-C no longer reaches the
    children BY ACCIDENT; we give that up to gain a teardown that is the same on
    all three paths - timeout, SIGINT and SIGTERM - instead of one that happens to
    work on one of them.
    """
    kwargs = {"shell": True, "stdout": subprocess.PIPE,
              "stderr": subprocess.STDOUT}
    if hasattr(os, "setsid"):
        kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return kwargs


def shares_our_group(pid):
    """Whether `pid` sits in THIS process's group - i.e. whether signalling that
    group would signal us.

    A NAMED PREDICATE RATHER THAN AN INLINE COMPARISON, because the branch it
    guards cannot be covered by observing the alternative: a case that removed
    the guard and called `_tear_down` would signal its own runner and die, which
    reads as infrastructure trouble rather than as a caught defect. The decision
    is testable here, and `_tear_down`'s use of it is reached by swapping this
    name - the same seam `test__journal_io` uses on `_git_anchor_finding`.

    True on any error, which is the safe direction: unable to tell whether we
    would hit ourselves means do not aim at the group.
    """
    try:
        return os.getpgid(pid) == os.getpgid(0)
    except Exception:
        return True


def _tear_down(proc):
    """Kill the process GROUP. True when that could be confirmed, False when not.

    THE FAULT THIS EXISTS FOR: `subprocess.run(timeout=)` kills the DIRECT child,
    and under `shell=True` the direct child is the shell. `npx` -> `node` -> its
    workers outlive it, keep running, and keep WRITING - into the very tree this
    script is about to describe with `git status --porcelain`. A survivor does not
    merely leak a process; it turns the after-snapshot into a race.

    SIGTERM, a grace period, then SIGKILL, because a test runner asked to stop
    politely usually flushes its output and a runner that ignores that is not
    going to be reasoned with. The return value is what the row records: a
    teardown that could not be confirmed is a fact about the run, and reporting it
    as a clean stop would be a claim with nothing behind it.
    """
    try:
        if hasattr(os, "killpg"):
            gid = os.getpgid(proc.pid)
            if shares_our_group(proc.pid):
                # THE CHILD IS IN OUR OWN GROUP, so `killpg` here would signal
                # THIS process - the caller - and not the child's tree. That is
                # not hypothetical: with `start_new_session` removed the whole
                # test runner died mid-suite, which is how this branch was found.
                # A platform with no `setsid` reaches the same state honestly, so
                # the narrow kill is taken and the answer is `False`: the direct
                # child goes, its descendants are not accounted for, and the row
                # says the teardown could not be confirmed rather than implying a
                # clean stop.
                proc.kill()
                try:
                    proc.wait(timeout=GRACE_SECONDS)
                except Exception:
                    pass
                return False
            os.killpg(gid, signal.SIGTERM)
            try:
                proc.wait(timeout=GRACE_SECONDS)
            except Exception:
                os.killpg(gid, signal.SIGKILL)
                proc.wait(timeout=GRACE_SECONDS)
            return True
        completed = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return completed.returncode == 0
    except Exception:
        return False


def _drain(proc):
    """Whatever the child had already written, after the group is gone.

    Called AFTER the kill and never instead of it: a timed-out child is often
    blocked on a full pipe, so reading first would wait on a process nothing is
    going to stop. Failure here costs a diagnostic, never the teardown."""
    try:
        out, _err = proc.communicate(timeout=GRACE_SECONDS)
        return (out or b"").decode("utf-8", "replace")
    except Exception:
        return ""


def _shell(project, command, timeout=None):
    """`(exit, text, facts)` - one gate command, with its whole tree accounted for.

    `facts` is what the wrapper OBSERVED that the exit code cannot carry: which
    of the two no-verdict outcomes happened, the bound that was hit, and whether
    the teardown could be confirmed. `{}` for a step that simply ran and finished,
    which is the overwhelming majority and pays nothing for the rest.
    """
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        proc = subprocess.Popen(command, cwd=project, **_spawn_kwargs())
    except Exception as exc:
        return 127, "could not run: %s" % (exc,), {"outcome": CANNOT_RUN}
    try:
        out, _err = proc.communicate(timeout=timeout)
        return proc.returncode, (out or b"").decode("utf-8", "replace"), {}
    except subprocess.TimeoutExpired:
        confirmed = _tear_down(proc)
        text = _drain(proc)
        facts = {"outcome": TIMED_OUT, "timeoutSeconds": timeout}
        if not confirmed:
            facts["teardown"] = "unconfirmed"
        code = proc.returncode if proc.returncode is not None else 124
        return code, text, facts
    except BaseException:
        # SIGINT and SIGTERM land here too, and the group has to go before this
        # leaves: an interrupted run that left its children running is the one
        # state in which every later answer this script gives is a guess.
        _tear_down(proc)
        _drain(proc)
        raise


def failed_steps(steps):
    """The steps that ran to completion and came back non-zero.

    A STEP WITH A NO-VERDICT OUTCOME IS NOT ONE OF THEM, and that exclusion is the
    point. A timed-out step's exit code is an artefact of the kill that stopped it
    - `-9`, or 124 where the platform gave nothing better - and counting it as a
    failure would report "your tests are red" about a suite that never finished.
    """
    return [st["name"] for st in steps
            if st["exit"] != 0 and not st.get("outcome")]


def run_status(steps, failed, ran_total, cancelled_by, refused, unattributable):
    """The run's one word, from what its steps did, what stopped it, what it
    rewrote, and what the tree already carried.

    PRECEDENCE, AND WHY IT IS THIS ORDER. `failed` sits ABOVE the no-verdict
    words deliberately: a step that ran and exited non-zero is a CERTAIN red, and
    reporting that as "timed out" downgrades a finding a reader can act on into
    one they have to reproduce first. Nothing is lost by the ordering, because
    every step keeps its own `outcome` - a run that failed AND timed out says both,
    one level down. That is the same rule `render` already follows for a gate that
    failed and also rewrote the tree: two facts, two sentences, never one.

    `no-checks` sits below `failed` for that reason and above `passed` for the
    opposite one - it is exit 0 and it is still not a verdict.

    AND THAT REASONING EXTENDS TO AN INTERRUPT, WHICH IS WHY `cancelled` SITS AT
    THE BOTTOM OF THE NO-VERDICT GROUP. A signal does not retract a measurement
    that already completed, so a run whose first step failed and whose second was
    cut short is still `failed` - and the same holds one step weaker for the other
    two: a step that timed out and a runner that never started are each a finding
    with a repair attached (raise the bound or fix the hang; fix
    `meta.buildCommands`, and do not burn a retry). `cancelled` is the ONLY word
    in this set that names no repair and says nothing whatever about the work
    under test - it is a fact about the operator - so anything that does name one
    outranks it. What it does not sit below is `no-checks`: a count of zero taken
    over a TRUNCATED run is not the "the gate ran and skipped everything" claim
    that word makes, and reading it as one would sign off a gate that never
    finished. `cancelledBy` travels on the run for the same reason every step
    keeps its `outcome` - the fact the precedence hides is still on the record.

    AND IT IS READ FROM A POSITIVE ZERO ONLY. `ran_total is None` means the runner
    does not report a count; it is not evidence that nothing ran, so it leaves the
    status alone. Spelling that `not ran_total` would merge the two.

    AND `gate-mutated` SITS AT THE VERY BOTTOM, DIRECTLY ABOVE `passed`, BECAUSE
    IT REPLACES THAT WORD AND NO OTHER (F280). Its claim is "every command ran and
    came back green, and the gate rewrote files the work under test declares" - so
    the first half of it is exactly `passed`'s claim, and every word above denies
    that half: `failed` came back red, `no-checks` counted nothing, and the three
    no-verdict words never finished. Ranking the rewrite above any of them would
    swap a fact about whether the suite ANSWERED for a fact about the tree, and
    tell a reader checks ran when none did. Two of those cannot co-occur with it
    at all: an interrupted or timed-out run sets `mutated` to None one function
    over, because a torn-down process group makes the comparison a race.

    Nothing is lost at the bottom either, which is the same reason the ordering
    above is safe: `treeMutated`, `treeMutatedOwned` and `treeBasis` all travel on
    the result whatever this word comes out as, `render` prints the rewrite as its
    own sentence even when the gate also failed, and both rendering surfaces carry
    it as an observation mark beside the badge. What may never happen again is
    `passed`.

    AND `failed` IS THE ONLY WORD `unattributable` DISPLACES, which is where the
    F323 objection lands: a red excused is a verdict nobody records and a retry
    nobody spends, so the excuse is allowed exactly where the red says nothing
    about the work - `unattributable_failure` is the whole of that judgement and
    holds both halves of it. Every more specific no-verdict word above still wins
    on a run that is also one of them: `could-not-run` here names a run whose red
    cannot be read, and `timed-out` names the step that was stopped at its bound,
    which is the finding with the repair attached.

    `cancelled_by`, `refused` AND `unattributable` HAVE NO DEFAULT. There is one
    production caller,
    and an argument nobody has to pass is an argument a later caller forgets -
    which would spell an interrupted run `passed` and lose it silently, and is
    literally how F280 got here: a `run_status` that could not see the tree
    recorded `passed` over its own `GATE MUTATED THE TREE`. Missing is a
    TypeError; an empty `refused` is the caller SAYING the gate rewrote nothing it
    owns. `refused` is `attributed_mutations`' first half, never `treeMutated`
    itself - the foreign half is the one nothing can attribute (F273) and refusing
    on it is what halted correct runs.
    """
    outcomes = [st.get("outcome") for st in steps]
    if failed and not unattributable:
        return "failed"
    if TIMED_OUT in outcomes:
        return TIMED_OUT
    if CANNOT_RUN in outcomes:
        return CANNOT_RUN
    if failed:
        # Reached only through the guard on the arm above, so this is the excused
        # red and nothing else: the two words between them describe a run this
        # one does not, and a red that was never excused has already returned.
        return CANNOT_RUN
    if cancelled_by is not None:
        return CANCELLED
    if ran_total == 0:
        return "no-checks"
    if refused:
        return GATE_MUTATED
    return "passed"


def observed_step(name, command, code, text, facts, duration_ms):
    """One step's row, from what the runner returned and from nothing else.

    A FUNCTION BECAUSE A STEP IS RUN MORE THAN ONCE. A step the OS ended is run a
    second time, and the second attempt has to be read by exactly the rules the
    first was: a copy of this arithmetic beside the retry would be a second
    answer to "what did this step do", and the first thing to drift would be the
    signal classification the retry is keyed on.

    `command` IS THE GATE'S OWN DECLARATION AND STAYS IT on both attempts. Where
    a second attempt lowered a worker bound, what changed is a number inside that
    string, and `retryBasis` names the flag and both values - so the row keeps
    the command the manifest published, which is the only spelling
    `_evidence_io` may store verbatim, and the change is stated beside it rather
    than substituted for it.
    """
    step = {"name": name, "command": command, "exit": code,
            "ran": ran_count(command, text),
            "durationMs": duration_ms}
    step.update(facts or {})
    # READ OFF THE `ran` THE ROW WILL CARRY, never off a copy taken before the
    # wrapper's facts landed: this word is a reading of that number, and a
    # reading taken from a different value than the one recorded beside it is
    # exactly the disagreement `measured_state` exists to make impossible. Above
    # the outcome arms below, and not among them, because it takes part in none
    # of them - it says what was measured, never what the run is worth.
    step["measured"] = measured_state(step["ran"])
    # F302, AND IT SITS BETWEEN THE TWO FOR A REASON. The wrapper's own facts
    # outrank it: a timed-out step was killed by OUR teardown, so its `-15` is
    # this process's signal and not the OS ending the run, and reading it here
    # would relabel every timeout as infrastructure. `never_started` below is an
    # inference off two numbers, so it comes after something the OS reported. The
    # signal and its basis ride on the step because that is where a per-step
    # observation belongs; the LEDGER needs no copy of either, since it already
    # records `exit` and `outcome` and a claim a row can be read for is not
    # cached twice (`_evidence_io.row_for` makes that argument for
    # `treeMutatedOwned`).
    if not step.get("outcome"):
        # THE STEP'S TEXT AND NOT ITS `ran` (F323). What the arm has to know is
        # whether the runner reached its own last line, and `step["ran"]` answers
        # a different question one of whose two provenances is a line tally this
        # reader did. The COMMAND goes with it (F352): a marker in the output of
        # a step that wraps other runners belongs to one of them, not to the
        # step.
        sig_name, sig_basis = ended_by_signal(step["exit"], text, command)
        if sig_name:
            step["outcome"] = CANNOT_RUN
            step["signal"] = sig_name
            step["signalBasis"] = sig_basis
    # AFTER the wrapper's own facts, never instead of them: `_shell` observed the
    # failure to spawn directly, and an inference must not overwrite an
    # observation. No basis key is written beside this because the step already
    # carries both halves of it - `exit` and a `ran` of zero ARE the evidence,
    # and a second copy could disagree with them.
    if never_started(step["exit"], step["ran"], step.get("outcome")):
        step["outcome"] = CANNOT_RUN
    # ON A STEP THAT DID NOT COME BACK ZERO, AND ON NO OTHER. The claim is "here
    # is what went wrong in this step", and a green step has nothing to say under
    # it - so carrying a tail there would put an arbitrary slice of a passing
    # runner's output into a committed row on every run this plugin ever records.
    # `fl6` is the allow case that holds that line, and it is the direction an
    # over-firing version of this breaks in.
    #
    # `exit` AND NOT `failed_steps`, deliberately wider by two members: a step
    # the OS killed and a step stopped at its bound both printed whatever they
    # got to, and that text is the only thing on the row that says how far they
    # got. They are not failures and nothing here calls them one - the word stays
    # `outcome`'s, and this is an observation beside it.
    if step["exit"] != 0:
        step["failing"], step["failingBasis"] = failing_lines(text,
                                                              _ev.MAX_FAILING)
    return step


def run_gate(project, commands, runner=None, owns=None, timeout=None):
    """Run each command bracketed by a working-tree snapshot; return the answer.

    A dict rather than an exit code, for `verify-invariants.py`'s reason: a
    function that only returned a verdict could not be tested without building a
    repository around it, and `runner` is the seam the cases drive.

    NOTHING HERE WRITES. The snapshot pair and the verdict are complete before the
    caller records anything, which is what keeps a recorder out of the measurement
    it is recording - an evidence file written inside this function would appear in
    the very `git status --porcelain` it is being judged by.
    """
    runner = runner or _shell
    before = _tree_stamp.porcelain(project)
    # PRE-EXECUTION, and the placement is load-bearing: a fix-in-place gate
    # rewrites the very files it checks, so a fingerprint taken after the run
    # would describe what the gate PRODUCED rather than what it was asked to
    # judge. Both digests are spent from `before`, above the first command.
    state = _tree_stamp.tested_state(project, owns, before)
    started = time.monotonic()
    steps, texts = [], []
    # STRICTLY PARALLEL TO `steps`, which `texts` is not: it is appended the
    # moment the runner returns, so a stop signal arriving while a step's row is
    # still being built leaves it one entry long. `shared_counts` indexes one
    # list by the other, and a list that can be off by one is a list that would
    # attribute one step's paths to another.
    step_named = []
    cancelled_by = None
    try:
        for name, command in commands:
            step_started = time.monotonic()
            code, text, facts = runner(project, command, timeout)
            texts.append(text or "")
            step = observed_step(name, command, code, text, facts,
                                 _elapsed_ms(step_started))
            # ONE SECOND ATTEMPT, AND ONLY FOR A STEP THE OS ENDED. The key read
            # here is the one `ended_by_signal` wrote, never the exit code: a
            # non-zero exit beside an end-of-run report is a measurement, and a
            # re-run of a measurement is a red rolled again until it comes back
            # green. Nor does a timeout or a runner that never started reach
            # this - our own teardown is not the OS ending the run, and a
            # missing interpreter answers the same way however many workers it
            # is asked for. What a kill has that neither of those has is a cause
            # the command declares a bound for.
            #
            # THE SECOND ATTEMPT REPLACES THE ROW AND CARRIES THE FIRST ON IT.
            # Its exit, its count and its duration are the ones a reader acts
            # on, and they are the SECOND attempt's - so the thing that cannot
            # be recovered from any of them is that there was a first, which
            # signal ended it, and whether the bound moved between the two.
            if step.get("signal"):
                retry_started = time.monotonic()
                lowered, change = lowered_parallelism(command)
                code, text, facts = runner(project, lowered or command, timeout)
                # APPENDED FOR ITS OWN ATTEMPT. `texts` is joined for the
                # coverage question alone, and both attempts really did print -
                # so a retried step contributes two entries here and still one
                # to each of the two lists that must stay parallel.
                texts.append(text or "")
                first = step
                step = observed_step(name, command, code, text, facts,
                                     _elapsed_ms(retry_started))
                step["retriedAfterSignal"] = first["signal"]
                step["retryBasis"] = retry_note(first["signal"], change)
            steps.append(step)
            # APPENDED WITH THE ROW AND NEVER BEFORE IT, so the two lists cannot
            # come apart. Scraped per step rather than sliced out of the joined
            # text below, because which STEP printed a path is the whole
            # question here and the join throws that away.
            step_named.append(files_named(text))
    except KeyboardInterrupt as exc:
        # THE ONE THING THE INTERRUPT PATH DOES IS LET THE ROW BE WRITTEN. The
        # child's group is already gone - `_shell`'s own `except BaseException`
        # tears it down before re-raising, which is why the exception arrives here
        # with nothing still running - and what was missing was a verdict and a
        # write. So the exception is turned into a fact ON THE RESULT and the
        # function returns normally; `main` records it, and NOTHING HERE COMMITS.
        # Git durability arrives later, at the `/audit:resume` sweep. A commit made
        # while stopping is a half-made one nobody reviewed, on the one path where
        # nobody is going to look.
        #
        # THE STEP THAT WAS IN FLIGHT GETS NO ROW, and the steps after it get none
        # either. It reported nothing, so a row for it would be a fabricated entry
        # in the one record that exists to be true; `status` is what says the list
        # is short.
        #
        # AND THE CATCH IS `KeyboardInterrupt`, NOT `BaseException`. `_shell` needs
        # the wide arm because its job there is teardown, which every escape owes;
        # this one assigns a MEANING, and calling a `MemoryError` or a `SystemExit`
        # "cancelled" would be the silent mislabel the rest of this file exists to
        # prevent. Anything else still escapes, loudly.
        cancelled_by = str(exc) or UNNAMED_SIGNAL
    after = _tree_stamp.porcelain(project)
    interrupted = (cancelled_by is not None
                   or any(st.get("outcome") == TIMED_OUT for st in steps))
    if interrupted:
        # A torn-down group is not a stopped one: a descendant that escaped the
        # kill keeps writing, so comparing the two snapshots would be a race whose
        # answer changes with timing. `porcelain` already refuses to call a tree
        # it cannot describe clean; this is the same refusal, one cause over.
        mutated = None
        basis = "the run was interrupted, so a tree comparison would be a race"
    elif before is None or after is None:
        mutated = None
        basis = "git could not describe the tree, so mutation is UNKNOWN"
    else:
        mutated = sorted(after - before)
        basis = "git described the tree before and after"
    owned_changes, foreign_changes, own_basis = classify_mutations(mutated, owns)
    if mutated:
        # Appended to `treeBasis` rather than given a key of its own, because the
        # ledger, the report and the panel all render THAT string already: a
        # fourth field would reach the terminal and none of the three surfaces
        # where a committed row is read.
        #
        # AND ONLY WHERE SOMETHING MOVED. "0 of 0 changed path(s) are declared"
        # is a basis with no claim under it, which this file's own rule calls
        # noise - and it would be on the overwhelming majority of rows.
        basis = "%s; %s" % (basis, own_basis)
    named = files_named("".join(texts)) if texts else None
    overlap, cbasis = coverage(owns, named)
    # P46.5. THE TOTAL IS THE SIZE OF THE GATE AND NOT THE SIZE OF ITS RUNS. A
    # plain sum over the steps reported one suite twice as twice as much
    # assurance, which is the reading that concealed a duplicated command for a
    # whole audit. `shared_counts` decides what may be added; `additive_total`
    # does the adding, so the decision and the arithmetic cannot disagree.
    shared = shared_counts(steps, step_named)
    ran_total = additive_total(steps, shared)
    failed = failed_steps(steps)
    # THE VERDICT READS THE SAME LIST THE VERDICT LINE REFUSES ON. `render` and
    # `--json` take the other half of this pair; before F280 the status word took
    # neither and could only ever say `passed` over a gate that had rewritten its
    # own subject.
    refused, _reported = attributed_mutations(mutated, owned_changes,
                                              foreign_changes)
    # OFF `before`, NEVER OFF `mutated`. The bracket above answers what moved
    # DURING the run and the reported row's answer to that was `[]`; the paths
    # that broke that gate were already dirty when the first command started, and
    # `before` is the only snapshot that holds them.
    not_attributable, attribution = unattributable_failure(failed, ran_total,
                                                           before, owns, named)
    return {"steps": steps, "testedState": state,
            "treeMutated": mutated, "treeBasis": basis,
            # THE FULL SET STAYS `treeMutated`, and the split is additive: the
            # ledger keeps recording every path that moved, so nothing a reader
            # could have seen before this is lost, and a consumer that never
            # heard of the split reads exactly what it read before.
            "treeMutatedOwned": owned_changes,
            "treeMutatedForeign": foreign_changes,
            "ranTotal": ran_total, "countsBasis": counts_basis(steps, shared),
            # THE PARTS, SO THE TOTAL IS NEVER THE ONLY THING ON OFFER. The
            # basis above carries the same finding as a sentence for the three
            # surfaces that render it; this is the structured half, for `--json`
            # and for `render`, which prints each group beside the steps it is
            # about. `[]` on the ordinary run, not None: nothing was undecided,
            # which is a measurement rather than a missing one.
            "sharedCounts": shared,
            "durationMs": _elapsed_ms(started),
            # THE PATHS AND THE SENTENCE TRAVEL TOGETHER OR NOT AT ALL. Both are
            # None on the ordinary run, which is this file's shape for a claim
            # nobody is making: a basis with no claim under it is noise, and a
            # verdict word with no basis beside it is the thing this whole file
            # exists to prevent.
            "notAttributable": not_attributable,
            "attributionBasis": attribution,
            "status": run_status(steps, failed, ran_total, cancelled_by,
                                 refused, not_attributable),
            # ALWAYS PRESENT, None WHEN NOTHING STOPPED THE RUN - the shape
            # `treeMutated` and `overlap` already use. A key that appeared only on
            # an interrupted run could not be told from a build that does not
            # write it, which is the reading that would let a `cancelled` row
            # arrive with no basis at all.
            "cancelledBy": cancelled_by,
            "overlap": overlap, "coverageBasis": cbasis,
            "failed": failed}


def render(res, out=print):
    """Print the answer and return the exit code it earns."""
    for step in res["steps"]:
        ran = step["ran"]
        # WHAT THE STEP COST, ON THE STEP'S OWN LINE AND NOT AS A TOTAL (P46.5).
        # `durationMs` has been recorded per step and for the run since this
        # script existed, and the terminal printed neither - so "where does the
        # time go" needed somebody to decide to go and measure it, and a gate
        # running one suite twice looked exactly like a gate running two. Per
        # step and right-aligned in a column of its own, because the reading
        # that matters is one step against another.
        took = human_duration(step.get("durationMs"))
        out("  %-12s exit %-3d %10s  %s"
            % (step["name"], step["exit"], took or "(not timed)",
               "%d check(s) ran" % ran if ran is not None
               else "check count not knowable from this runner"))
        # UNDER THE STEP AND NOT UNDER THE VERDICT, because this is a per-step
        # fact and the step's own line is the only place it needs no attribution
        # written beside it. It also leaves the verdict banners below unbroken:
        # `reference/orchestrator.md` keys its arms on those literal lines, so a
        # dump interleaved among them changes a surface another document reads.
        #
        # RAW, where the row's copy is redacted. A terminal belongs to the
        # operator whose machine the paths name, and a path rewritten to the
        # outside token is one they cannot open; the committed file is the
        # surface where the opposite holds.
        if step.get("failing") is not None:
            for line in step["failing"]:
                out("      %s" % (line,))
            out("      basis: %s" % (step["failingBasis"],))
    # THE PARTS, PRINTED WHERE THE TOTAL IS READ (P46.5). Above the verdict
    # banners and below the steps, because this is a statement about the steps
    # and `reference/orchestrator.md` keys its arms on the banner literals - a
    # line interleaved among those changes a surface another document reads.
    # NEITHER LINE IS A REFUSAL. `GATE GREEN` is still green with a duplicated
    # step in it: the duplication costs wall clock and exposure to flakiness,
    # and neither is evidence about the work under test. What it corrects is the
    # NUMBER, which was the thing being read as assurance.
    for grp in (res.get("sharedCounts") or ()):
        if grp["verdict"] == SAME_SUITE:
            out("SAME SUITE COUNTED ONCE: %s each reported %d check(s) over the "
                "same suite file(s) - %s - so the total below holds that count "
                "ONCE. A second command over the same suite can only agree with "
                "the first or be flaky, so it adds no assurance while doubling "
                "what a nondeterminism in that suite costs."
                % (", ".join(grp["names"]), grp["ran"],
                   _output.some_of(grp["files"], budget=SAMPLE_BUDGET)))
        else:
            out("SAME COUNT, SAME SUITE NOT ESTABLISHED: %s each reported %d "
                "check(s), and %s named no suite file - so nothing here can "
                "compare what they ran. They MAY be one suite run twice; the "
                "total below ADDS them, which makes it an upper bound until "
                "somebody looks."
                % (", ".join(grp["names"]), grp["ran"],
                   _output.some_of(grp["silent"], budget=SAMPLE_BUDGET)))
    # ABOVE THE VERDICT AND NOT BESIDE THE STEP, because the reader this is for
    # is the one who scrolls to the banner. A retried step's own line carries the
    # exit, the count and the duration of the attempt that answered, and every
    # one of those reads as an ordinary measurement - so a run that comes back
    # `GATE GREEN` with nothing here would tell a reader the gate answered, when
    # what happened is that it was killed and then asked under a different bound.
    # The banner literals `reference/orchestrator.md` keys its arms on are left
    # unbroken, which is why this sits here rather than among them.
    for st in res["steps"]:
        if st.get("retryBasis"):
            out("RETRIED AFTER A SIGNAL: %s - %s" % (st["name"],
                                                     st["retryBasis"]))
    code = E_OK
    # THE SAME LIST THE STATUS WORD READS, for F280's reason: the verdict line and
    # the record disagreeing about one run is the fault this file keeps being
    # repaired for, and `GATE RED` over a run whose row says `could-not-run` is
    # exactly that shape with the halves swapped.
    excused = res.get("notAttributable")
    if res["failed"] and not excused:
        out("GATE RED: %s" % ", ".join(res["failed"]))
        code = E_FAIL
    # THE NO-VERDICT WORDS HAD NO ARM HERE AT ALL, and that was worth finding
    # before F276 widened the count vocabulary: with `failed` empty, `treeMutated`
    # empty and `ranTotal` unknowable, a run whose step never STARTED fell all the
    # way through to `GATE GREEN` and exit 0. `run_status` had said `could-not-run`
    # the whole time and this function printed the opposite of it. Widening the
    # count without these two arms would have turned an exit-48 sandbox failure
    # from a false red into a false GREEN, which is strictly the worse of the two.
    # F302. THE BANNER IS THE CLASS AND THE SENTENCE UNDER IT IS THE MEMBER, and
    # that division is load-bearing rather than cosmetic. `reference/
    # orchestrator.md` keys its infrastructure arm on this literal by name -
    # "`GATE COULD NOT RUN` is not the task's failure ... do NOT spend a retry" -
    # so a kill printed under a banner of its own would be a line the document
    # has never heard of, and an orchestrator following the document would fall
    # through to "gates RAN and are red" and burn all three `maxAttempts` on
    # something no code change can fix. That is the consequence chain this fault
    # is really about, so the fix has to reach the EXISTING rule rather than
    # invent a second one.
    #
    # AND THE MEMBER SENTENCE HAD TO SPLIT ANYWAY, because the old one was false
    # of half its own class: "never got as far as a check" is not true of a suite
    # the kernel killed mid-run, and "fix `meta.buildCommands`" is not the repair
    # a kill needs.
    killed = [st for st in res["steps"]
              if st.get("outcome") == CANNOT_RUN and st.get("signal")]
    unstarted = [st["name"] for st in res["steps"]
                 if st.get("outcome") == CANNOT_RUN and not st.get("signal")]
    stalled = [st["name"] for st in res["steps"]
               if st.get("outcome") == TIMED_OUT]
    # THE THIRD MEMBER REACHES THE BANNER THE DOCUMENT ALREADY KEYS ON, which is
    # the whole of how it costs no retry: `reference/orchestrator.md` keys its
    # infrastructure arm on this literal - "`GATE COULD NOT RUN` is not the
    # task's failure ... do NOT spend a retry" - so a member printed under a
    # banner of its own would be a line that document has never heard of, and an
    # orchestrator following it would fall through to "gates RAN and are red" and
    # burn every `maxAttempts` on a tree state no code change fixes. Nothing here
    # touches `attempts`: this script never has, the signal member did not either,
    # and a second convention for the same decision is one that can disagree.
    #
    # AND IT IS A RUN-LEVEL MEMBER WHERE THE OTHER TWO ARE A STEP'S. The steps
    # that went red really did exit non-zero and each one's row still says so;
    # what cannot be attributed is the run, because the fact that excuses it is a
    # fact about the TREE the whole run was measured against.
    if unstarted or killed or excused:
        out("GATE COULD NOT RUN: %s reached no verdict. That is an "
            "INFRASTRUCTURE failure and not this work's, so it is not a red "
            "suite and must not be recorded as one. Fix the runner and re-run; "
            "do not spend a retry on the task."
            % (", ".join(unstarted + [st["name"] for st in killed]
                         + (res["failed"] if excused else [])),))
        if excused:
            out("  %s came back RED having measured nothing, and it named a "
                "file that was ALREADY dirty when the run started and that this "
                "work does not declare: %s. A whole-program check fails on "
                "somebody else's half-written file whatever the work under test "
                "is, so this red is not evidence about it. Re-run once nobody "
                "else is writing here."
                % (", ".join(res["failed"]),
                   _output.some_of(excused, budget=SAMPLE_BUDGET)))
            if res.get("attributionBasis"):
                out("  basis: %s" % (res["attributionBasis"],))
        if unstarted:
            out("  %s never got as far as a check - a missing command, a runner "
                "that died before its first test, a port it could not bind."
                % (", ".join(unstarted),))
        for st in killed:
            # ONE SENTENCE PER KILLED STEP, carrying the signal AND the basis:
            # the two channels are not equally strong - one is what the OS
            # reported and one is a shell convention this reader chose to trust -
            # and a reader deciding whether to believe the word needs to know
            # which of the two they have.
            out("  THE OS ENDED %s (%s): the run did not answer, so nothing "
                "about the work under test may be read into it. An "
                "out-of-memory reaper, a crash inside the runner, a cgroup "
                "limit, or ANOTHER MEASUREMENT on this host starving this one "
                "of CPU." % (st["name"], st["signal"]))
            if st.get("signalBasis"):
                out("  basis: %s" % (st["signalBasis"],))
            if st.get("retriedAfterSignal"):
                # THE HONEST END OF A RETRY, and the sentence that says there is
                # no next one. A step ended by a signal twice - once under the
                # bound the gate declared and once under a smaller one - is a
                # host that cannot run this gate, which is a thing to repair and
                # not a thing to keep rolling for. Both attempts are named
                # because they are two observations and a reader deciding what
                # to fix needs both.
                out("  and the FIRST attempt was ended by %s, so this step has "
                    "been ended by a signal on BOTH attempts and there is no "
                    "third: re-running it again measures the host, not the "
                    "work." % (st["retriedAfterSignal"],))
        code = E_FAIL
    if stalled:
        out("GATE TIMED OUT: %s was stopped at its bound rather than answering. "
            "No verdict was reached, so this is neither green nor red - raise "
            "--timeout or fix the hang, and read nothing about the work into it."
            % (", ".join(stalled),))
        code = E_FAIL
    if res.get("cancelledBy") is not None:
        # SAID EVEN WHEN THE GATE ALSO FAILED, and printed from the FACT rather
        # than from the status word: `run_status` puts `failed` above `cancelled`,
        # so a run that is both says `failed` - and a reader who only saw that
        # would believe the remaining steps had their say. Two facts, two
        # sentences, which is the rule the mutated-tree line one block down has
        # followed all along.
        out("GATE CANCELLED: %s stopped this run. The steps after it never "
            "reported, so this record is SHORT, not green - nothing was measured "
            "past the signal and no verdict here covers it."
            % (res["cancelledBy"],))
        out("  the row is written locally and committed by nobody: git belongs to "
            "the orchestrator, and commit-audit-state.py at the next "
            "/audit:resume is what makes this durable.")
        code = E_FAIL
    # F273. TWO SETS, TWO MEANINGS, TWO RESPONSES - see `classify_mutations` for
    # what each one can and cannot claim, and `attributed_mutations` for the
    # fallback when there is no ownership to sort by. That fallback was written
    # out by hand here and again in `--json` while the status word had no arm at
    # all, which is what let one run carry two answers (F280).
    owned_changes, foreign_changes = attributed_mutations(
        res["treeMutated"], res.get("treeMutatedOwned"),
        res.get("treeMutatedForeign"))
    if owned_changes:
        # Said even when the gate also failed: two different facts, and a reader
        # who fixed the failure would otherwise meet the rewrite afterwards.
        # `None` and `[]` are both silent HERE because neither names a file - the
        # difference between them is a claim about the tree, and it is printed by
        # the basis line below rather than being read out of a falsy value.
        out("GATE MUTATED THE TREE: %s" % ", ".join(owned_changes))
        out("  a gate is a measurement, and this one rewrote the very files it "
            "was grading. Do NOT commit on this run - the diff now carries work "
            "no review saw. Revert those files, then either use the read-only "
            "spelling of the check (`--check` rather than `--write`, `ruff "
            "check` rather than `ruff --fix`) or scope the gate to the task's "
            "own files.")
        code = E_FAIL
    if foreign_changes:
        out("TREE CHANGED OUTSIDE THIS WORK: %s" % ", ".join(foreign_changes))
        out("  none of those is a file the work under test declares, and this "
            "bracket cannot say who wrote them: a gate writing outside its own "
            "subject and a SIBLING writer - a parallel task's executor, or a "
            "second session in this working directory - move the same paths. "
            "NOT refused here, because refusing on the half that cannot be "
            "attributed is what halted correct runs. Check them against what "
            "else is running before you commit.")
    if (owned_changes or foreign_changes) and res.get("treeBasis"):
        out("  basis: %s" % res["treeBasis"])
    if res["ranTotal"] == 0 and not unstarted and not killed and not excused:
        # `unstarted` OWNS THIS SENTENCE WHEN IT FIRES. The claim below is "that
        # is exit 0", and a step that died at exit 48 having collected no test
        # makes it false - the same zero, a different fact, and the line above
        # already said which. `killed` is here for exactly that reason one cause
        # over: a runner that printed `0 passed` and was then SIGKILLed also
        # reaches a positive zero, and "that is exit 0" is false of `-9` too.
        # `excused` is the third: that zero sits beside a step that came back
        # RED, so "that is exit 0" is false of it as well, and the banner above
        # has already said what the zero means on this run.
        out("NO CHECK RAN: every step reported zero checks. That is exit 0 and it "
            "is not a verdict - a gate that skipped everything and a gate that "
            "verified everything are the same exit code, and this is the one that "
            "cannot sign anything off.")
        code = E_FAIL
    if res["treeMutated"] is None:
        # STRUCTURAL, not a string prefix. The old test read `treeBasis` for the
        # words "git could not", which stopped covering the case the moment a
        # second reason to skip the comparison existed - an interrupted run.
        # `None` IS the claim "no comparison was made"; the basis says which.
        out("  basis: %s" % res["treeBasis"])
    # F204. SAID, NEVER ENFORCED, and said in three distinguishable ways: the
    # overlap is empty, the overlap is real, or the question could not be asked.
    # The third is not the first -- see `coverage`.
    if res.get("overlap") is None:
        if res.get("coverageBasis"):
            out("  coverage: %s" % res["coverageBasis"])
    elif not res["overlap"]:
        out("NO OVERLAP WITH THIS WORK: the gate ran, and none of the paths it "
            "printed is a file this task owns. That is not a failure and is not "
            "refused here - it is the third way a gate says nothing, after doing "
            "too much and doing nothing. Decide whether this gate can grade this "
            "work before signing it off.")
        out("  basis: %s" % res["coverageBasis"])
    else:
        out("  coverage: %d declared file(s) named by the run: %s"
            % (len(res["overlap"]), ", ".join(res["overlap"])))
    if code == E_OK:
        # THE TREE CLAUSE IS COMPUTED, because this line was making two claims it
        # had no basis for: `tree unchanged` printed unchanged over a run where
        # git could not describe the tree at ALL, and - once the split above
        # existed - over one where paths outside the work really had moved. A
        # green verdict is the last place a sentence may say more than was
        # measured.
        if res["treeMutated"] is None:
            tree = "tree NOT compared"
        elif foreign_changes:
            tree = "no declared file changed"
        else:
            tree = "tree unchanged"
        out("GATE GREEN: %s, %s%s"
            % (", ".join(s["name"] for s in res["steps"]) or "no commands", tree,
               "" if res["ranTotal"] is None
               else ", %d check(s) ran" % res["ranTotal"]))
    return code


# --- stopping this process ----------------------------------------------------
# A TERMINAL'S Ctrl-C DOES NOT REACH THE CHILDREN, by construction rather than by
# accident: `_spawn_kwargs` puts every step in a session of its own, so the signal
# arrives HERE and nowhere else. That trade is stated there - one teardown that is
# the same on all three paths instead of one that happens to work on one of them -
# and these two functions are the half of it that was never written. SIGTERM has
# no default that could stand in either: with no handler the interpreter simply
# dies, the detached group outlives it, and the run leaves neither a record nor a
# stopped child.
INTERRUPT_SIGNALS = ("SIGINT", "SIGTERM")


def _raiser(word):
    """A handler that raises the interrupt NAMING the signal it was installed for.

    The name is bound at install time because that is the only place it is known
    without a second table to keep in step - and a `cancelled` row owes its reader
    the thing that stopped the run, which is the whole of that row's basis.

    `KeyboardInterrupt` rather than an exception of this file's own: SIGINT already
    raises it, so ONE arm in `run_gate` covers both signals instead of two that can
    drift apart. It is a `BaseException`, which is what carries it past every
    `except Exception` between here and there.
    """
    def _handler(_signum, _frame):
        raise KeyboardInterrupt(word)
    return _handler


def _arm_interrupt():
    """Install the handlers; return what they displaced, for `_disarm_interrupt`.

    NOT GUARDED AGAINST `ValueError`. `signal.signal` refuses off the main thread,
    and this file is an entry point - a caller that reaches that state has a
    defect, and swallowing it would hide the one fact that matters here, which is
    that the interrupt path is NOT armed.
    """
    previous = []
    for name in INTERRUPT_SIGNALS:
        sig = getattr(signal, name)
        previous.append((sig, signal.signal(sig, _raiser(name))))
    return previous


def _disarm_interrupt(previous):
    """Put back exactly what `_arm_interrupt` displaced.

    A handler left installed outlives the call, and `main` is a function the
    suites drive many times in one process - so this is a `finally`, not a
    courtesy.

    `None` is what `signal.signal` returns for a handler that was not set from
    Python, and it cannot be handed back: `signal.signal(sig, None)` is a
    TypeError. The default is restored in that case, which is the honest reading -
    there is no Python handler to return to.
    """
    for sig, handler in previous:
        signal.signal(sig, signal.SIG_DFL if handler is None else handler)


def _record_run(project, args, res, source, commands, manifest, out=print):
    """Record the run, point the plan at it, and date the plan's first recording.

    THE POINTER IS ALLOWED TO FAIL AND THE ROW IS NOT. The ledger is the source of
    truth; the manifest block is a cache, so a pointer refused by another live
    session leaves the record standing and names the repair. That asymmetry is
    printed rather than folded into one word, because "your run was not recorded"
    and "your plan has not caught up yet" are different problems.

    THE BOUNDARY IS ALLOWED TO FAIL AND OWES NO REPAIR AT ALL, which is the third
    outcome and not a variation on the second. It is written once in a plan's life
    and only when absent, and both of its sources are independent -- so a refused
    stamp leaves the ledger dating the boundary exactly as it did a moment before.
    """
    ids = subject_ids(args.phase, args.task, source)
    # ABSENT IS AN ANSWER HERE, and `row_for` is what keeps it one: it drops an
    # identity key whose value is None, so a task whose plan records no attempts
    # leaves the field OFF the row instead of defaulting it to a number nobody
    # wrote. `sessionId` is spelled the same way one line up, for the same reason.
    identity = {"runId": _ev.new_run_id(), "via": "cli",
                "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
                "attempt": attempt_of(manifest, args.task)}
    # FROM `gate_of`, NEVER FROM THE STEPS. `published` is what decides whether a
    # command is stored verbatim or as a digest, and the steps carry the very
    # commands being judged - deriving it from them would make every command its
    # own permission and the rule vacuous. `commands` is the manifest-resolved
    # list by construction, which is exactly the claim the rule rests on.
    published = [command for _name, command in (commands or [])]
    try:
        recorded = _ev.record(project, res, source, ids, identity,
                              published=published)
    except Exception as exc:
        out("  evidence: NOT recorded - %s" % (exc,))
        return {"recorded": False, "pointer": False, "boundary": None,
                "boundaryWritten": False}
    out("  evidence: recorded %s" % (identity["runId"],))
    pointer = _ev.write_pointer(project, args.manifest, source, ids,
                                recorded["row"],
                                session_id=identity["sessionId"])
    if pointer["written"]:
        out("  pointer:  %s now names it" % (ids.get("taskId") or args.phase,))
    else:
        out("  pointer:  NOT updated - %s" % (pointer["reason"],))
    # A LOCK THAT REFUSED TO BE GIVEN BACK IS ITS OWN LINE. It does not say the
    # pointer failed - it did not - it says another session held this phase while
    # the write was happening, which is a fact about everything written here and
    # not only about the pointer.
    if pointer.get("releaseRefused"):
        out("  lock:     %s" % (pointer["releaseRefused"],))
    # ASKED ON ITS OWN TERMS, NEVER OFF THE POINTER'S ANSWER. The two writes have
    # different subjects and different guards - a pointer refused because the plan
    # has no such task says nothing about whether this plan has ever recorded a run
    # - so reading `pointer["written"]` here would make one refusal cause another
    # for a reason that was never true.
    since = _ev.write_evidence_since(project, args.manifest, ids.get("phaseId"),
                                     session_id=identity["sessionId"])
    if since["written"]:
        out("  boundary: recording began %s - work finished before it could not "
            "carry evidence" % (since["at"],))
    elif since["at"] is not None:
        out("  boundary: %s, already stated by the plan" % (since["at"],))
    else:
        # THREE OUTCOMES, THREE SENTENCES. "Written now", "already there" and
        # "could not be written" are three different facts about the plan, and a
        # reader who saw one word for all three would have to open the manifest to
        # find out which.
        out("  boundary: NOT stamped - %s" % (since["reason"],))
    # THE SAME LINE THE POINTER GETS, for the same reason and on either verdict:
    # a lock that refused to be given back says another session held it while
    # this stamp was being written, which is a fact about the plan rather than
    # about whether the stamp landed.
    for said in (since.get("releaseRefused") or []):
        out("  lock:     %s" % (said,))
    return {"recorded": True, "pointer": bool(pointer["written"]),
            "boundary": since["at"], "boundaryWritten": bool(since["written"])}


def main(argv, out=print):
    p = argparse.ArgumentParser(prog="run-test-gate.py", add_help=True)
    p.add_argument("manifest")
    p.add_argument("phase")
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--json", action="store_true", dest="as_json")
    # NARROWS the coverage question to one task. Without it the question is asked
    # of the PHASE, which is where this script is invoked from - the live F204
    # incident was a task-level gate, but a flag with no caller states nothing.
    p.add_argument("--task", dest="task", default=None)
    # The bound a step is held to, recorded on the row that reports a timeout so
    # "timed out" carries the number that makes it actionable rather than leaving
    # a reader to guess which limit was hit.
    p.add_argument("--timeout", dest="timeout", type=int,
                   default=DEFAULT_TIMEOUT_SECONDS)
    # RECORDING IS OPT-IN FOR NOW. The orchestrator is what will pass it; until
    # that instruction exists, a flag nothing sets is better than a default that
    # writes into every repository the gate has ever been run in.
    p.add_argument("--record", dest="record", action="store_true")
    # THE OPERATOR'S WAY BACK TO A MEASUREMENT, and the reason a repeat is
    # allowed to be the default at all: a cache with no override is a cache that
    # gets deleted by hand. It suppresses the LOOKUP and not the identity - the
    # row this run writes still carries one, or a forced run would leave nothing
    # for the next one to match.
    p.add_argument("--no-reuse", dest="no_reuse", action="store_true")
    # The repair a refused pointer names. It runs the ledger against the plan and
    # nothing else - no gate, no subprocess - so it is safe to hand a human who
    # has just been told their pointer did not land.
    p.add_argument("--reconcile", dest="reconcile", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return E_ASK if exc.code else E_OK
    project = args.project_dir or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(args.manifest))))
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        out("[run-test-gate] cannot read the manifest: %s" % exc)
        return E_ASK
    if args.reconcile:
        report = _ev.reconcile(project, args.manifest,
                               session_id=os.environ.get("CLAUDE_CODE_SESSION_ID"))
        out("[run-test-gate] reconcile: %d subject(s) in the ledger"
            % (report["subjects"],))
        for line in report["moved"]:
            out("  moved:    %s" % (line,))
        for line in report["already"]:
            out("  already:  %s" % (line,))
        for line in report["refused"]:
            out("  REFUSED:  %s" % (line,))
        if report["unreadable"]:
            out("  %d unreadable row(s) were skipped - a torn line is counted "
                "here rather than dropped in silence" % (report["unreadable"],))
        return E_FAIL if report["refused"] else E_OK
    commands, source, err = gate_of(manifest, args.phase, args.task)
    if err:
        out("[run-test-gate] %s" % err)
        return E_ASK
    subject = args.task if source == "task" else args.phase
    if not commands:
        # The EMPTY gate is a designed state (`audit-task.py:_phase_gate`), so it
        # is reported as itself rather than as a pass: sign-off rests on review
        # alone, and saying "green" here would claim a measurement nobody made.
        # It names the PHASE even under `--task`, because an empty answer here is
        # always the phase's: a task with a gate of its own never reaches this.
        out("[run-test-gate] %s declares an EMPTY gate: nothing here can prove it "
            "done, so sign-off rests on review alone" % (args.phase,))
        return E_OK
    owns, terr = owned_files(manifest, args.phase, args.task)
    if terr:
        out("[run-test-gate] %s" % terr)
        return E_ASK
    # ASKED BEFORE THE GATE AND WHATEVER THE ANSWER IS. The identity is what the
    # row this run writes has to carry, so a `--no-reuse` run computes one too -
    # a forced measurement that recorded no identity would leave the next run
    # nothing to match, which turns one operator's override into everybody's.
    started = time.monotonic()
    identity = reuse_identity(project, args.manifest, manifest, commands, owns)
    prior = None
    if identity.get("grading"):
        # THE ONE SUBJECT THIS IDENTITY CANNOT SPEAK FOR. Driven before this
        # line existed: a gate whose single entry validates the plan reported
        # GREEN over a plan that no longer validated, because the plan is among
        # the paths the identity leaves out. The refusal is printed rather than
        # silent, and it names the entry - an operator who sees a gate measure
        # every time is owed the reason, or the next reader removes the cache.
        for name, path in identity["grading"]:
            out("[run-test-gate] %s names %s, which this identity leaves out, so "
                "this run is MEASURED and not repeated. Whether the command reads "
                "that path is not established here; naming it is enough, because "
                "the other way round is a verdict that no longer describes the "
                "thing it graded" % (name, path))
    elif not args.no_reuse:
        prior = _ev.reusable_run(_ev.read_rows(project)["rows"], source,
                                 subject_ids(args.phase, args.task, source),
                                 identity["key"], REUSABLE_STATUS)
    if prior is not None:
        res = reused_result(identity, prior, _elapsed_ms(started))
    else:
        # ARMED AROUND THE MEASUREMENT AND NOWHERE ELSE. This is the window a stop
        # signal actually lands in - a gate step is where the wall clock goes - and
        # arming it wider would mean holding a handler over the recording below, where
        # a second Ctrl-C should be free to stop a session that is already stopping.
        previous = _arm_interrupt()
        try:
            res = run_gate(project, commands, owns=owns, timeout=args.timeout)
        finally:
            _disarm_interrupt(previous)
        # ON THE MEASURED RUN AND NOT ON THE REPEAT'S SOURCE. `run_gate` takes no
        # manifest and must not: it is the function the cases drive without a
        # repository around it, and an identity computed inside it would be a
        # second reading of the tree taken after the first command had already
        # had its chance to rewrite one.
        res[_ev.REUSE_KEY] = identity["key"]
        res["reuseBasis"] = identity["basis"]
    # `gateSource` IS RECORDED AND `subject` IS NOT, and the split is the rule
    # about a cached claim rather than an oversight (F312). Provenance is not
    # recoverable from the row - `_evidence_io.row_for` carries the reasoning -
    # while the subject is: it is the `taskId` the row already holds whenever
    # `gateSource` is `task`, and the `phaseId` otherwise. So one crosses into the
    # ledger and the other stays a fact of this process's own output.
    res["gateSource"] = source
    res["subject"] = subject
    # STRICTLY AFTER THE VERDICT, and that placement is the whole of it: the
    # evidence file, the journal and the manifest all live inside the repository
    # this run has just described with `git status --porcelain`, so a write above
    # this line would appear in the very comparison it is being judged by. Every
    # measurement `run_gate` makes is complete before anything here writes.
    if args.record:
        res["recorded"] = _record_run(project, args, res, source, commands,
                                      manifest, out=out)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        # ONE TERM, BECAUSE THE STATUS NOW CARRIES BOTH FACTS (F280). This read
        # the owned writes as a SECOND term beside the word, which is precisely
        # the shape of the fault: the exit code refused a run the record called
        # `passed`, and only the exit code was ever right. `run_status` answers
        # `gate-mutated` for exactly the set this expression used to add on, so
        # a `passed` here is now a run that rewrote nothing it owns - by
        # construction rather than by a second opinion that can drift.
        #
        # The overlap is absent from this expression ON PURPOSE: it is reported,
        # not enforced, and a machine reader that wants to act on it has the
        # field. Folding it in here would make the decision this entry declined.
        # `treeMutatedForeign` is absent for the same reason and a second one -
        # it is the half nothing can attribute (F273).
        return E_OK if res["status"] == "passed" else E_FAIL
    # WHOSE gate ran is printed, not left to be inferred from the id: under
    # `--task` a task with no gate of its own is measured by the PHASE's, and a
    # reader who assumed otherwise would credit the wrong declaration.
    out("[run-test-gate] %s: %d command(s), %s gate"
        % (subject, len(commands), source))
    if identity["key"] is None:
        # THE MISSING BASIS IS THE THING TO SAY. Every other run records an
        # identity and this one cannot, so no verdict taken here will ever be
        # repeated and no earlier one could have been - and silence would leave
        # a reader wondering why their repeat did not fire, with nothing in the
        # output to read it off.
        out("  identity: NOT established - %s. Nothing measured on this tree "
            "can be repeated, in either direction." % (identity["basis"],))
    # A REPEAT IS NOT A RUN AND IS NOT RENDERED AS ONE. `render` prints a step
    # table, a tree comparison and a count, and a repeat has none of those to
    # print - filling them with the earlier run's would be this process stating
    # observations it never made.
    if res.get(_ev.VERDICT_SOURCE) == _ev.REUSED:
        return render_reuse(res, out=out)
    return render(res, out=out)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("run-test-gate.py: cases live in "
              "plugins/audit/tests/test_run_test_gate.py")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
