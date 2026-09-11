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
    `_porcelain`: it expands a wholly untracked directory into its files, so a
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

Exit codes:
  0  every command passed, the tree is unchanged, and at least one check ran
  1  a command failed, or the gate mutated the tree, or nothing ran, or the OS
     ended a step, or a stop signal cut the run short before every step had
     reported
  2  the gate could not be asked (no manifest, no such phase)
"""
import argparse
import hashlib
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

import _journal_io  # noqa: E402  (the ONE canonical spelling and file digest)
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


def _porcelain(project):
    """`git status --porcelain -uall` as a set of lines, or None when git cannot answer.

    None is NOT an empty tree. A repository git refuses to describe is a basis
    this script does not have, and reporting that as "nothing changed" would be
    the false clean sheet the whole file exists to prevent.

    `-uall` IS THAT SAME REFUSAL, ONE CAUSE OVER (F224). Git collapses a WHOLLY
    UNTRACKED directory to a single `?? dir/` entry, so without the flag a
    fix-in-place gate that CREATES a file inside one moves no line at all and the
    bracket answers `treeMutated == []` -- the value that means KNOWN CLEAN. That
    is not a corner: a subject tree nobody has committed yet, a first audit run,
    a brand-new source directory are all exactly it. Every other porcelain reader
    in this plugin already passes the flag and says why beside it
    (`_journal_io._git_status_sets`, `commit-audit-state`, `guard-bash-writes`);
    this was the reader that did not.

    AND IT DOES NOT MAKE THE BRACKET CONTENT-AWARE, which is the reading the flag
    invites and the one to refuse. Porcelain reports STATUS, never bytes: a file
    that was ALREADY untracked keeps its one `?? path` entry when a gate REWRITES
    it, with the flag exactly as without it. So a rewrite of an already-untracked
    file is invisible to this comparison either way -- `dirty_digest` states the
    matching limit for an already-dirty TRACKED file further down -- and the
    limit is pinned by a case of its own, so nobody can read the flag as having
    repaired what it did not touch.
    """
    try:
        out = subprocess.run(["git", "-C", project, "status", "--porcelain",
                              "-uall"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return set(ln for ln in out.stdout.decode("utf-8", "replace").splitlines()
               if ln.strip())


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

    `_porcelain` describes the WHOLE repository with no pathspec, so the bracket
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


# --- what state was actually tested -------------------------------------------
# `head` cannot answer this and never could. A TASK gate runs BEFORE the task
# commit, so a run executes against HEAD plus staged edits plus unstaged ones plus
# untracked files: two failed retries at one HEAD were indistinguishable, which
# defeats the point of recording retries. So `head` is demoted to what it actually
# is and a digest of the DECLARED work is recorded beside it.
#
# NOT A SECOND HASHING SUBSYSTEM. `_journal_io.canonical` is the one spelling this
# tree hashes with and `_journal_io.file_hash` is the one file digest; both are
# reused verbatim. What is new here is only WHICH bytes get fed to them.
HEAD_BASIS = ("repository HEAD at execution time; it does not identify the "
              "tested state, because a task gate runs before the task commit")


def _head(project):
    """The short HEAD sha, or None when git will not say.

    None rather than a placeholder, for `_porcelain`'s reason: a repository git
    cannot describe has not got a HEAD this run can name, and inventing one would
    put a false anchor on a real row."""
    try:
        out = subprocess.run(["git", "-C", project, "rev-parse", "--short", "HEAD"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").strip() or None


def _digest(payload):
    """`sha256:<hex>` over one canonical spelling of `payload`, or None.

    The prefix is `file_hash`'s, so a reader meets one shape for every digest a
    row carries rather than having to know which field wears one."""
    try:
        return "sha256:" + hashlib.sha256(
            _journal_io.canonical(payload).encode("utf-8")).hexdigest()
    except Exception:
        return None


def scope_digest(project, owns):
    """`(digest, basis)` for the DECLARED work as it stands right now.

    EXACT FOR THE DECLARED SCOPE and nothing wider, which is the whole claim: two
    runs sharing this digest measured identical declared-file contents, and a
    differing one means the declared work changed between them.

    A MISSING FILE HASHES AS NULL RATHER THAN BEING DROPPED. Absent is itself
    evidence about the state under test, and skipping it would let a scope of
    three files and a scope of two share a digest.

    None when nothing is declared, the shape `coverage()` already uses one
    question over: a digest of an empty list is a real digest that would compare
    equal across every such run and read as agreement.
    """
    declared = [f for f in (owns or []) if isinstance(f, str) and f.strip()]
    if not declared:
        return None, ("the work under test declares no files, so there is "
                      "nothing to fingerprint")
    entries, missing = [], 0
    for rel in sorted(set(declared)):
        digest = _journal_io.file_hash(os.path.join(project, rel))
        if digest is None:
            missing += 1
        entries.append([rel, digest])
    return _digest(entries), ("%d declared file(s); %d read, %d missing"
                              % (len(entries), len(entries) - missing, missing))


def dirty_digest(before):
    """`(digest, basis)` over the porcelain lines taken BEFORE the run.

    Reuses the snapshot the mutation bracket already takes, so this costs no
    extra git call at all.

    WHAT IT DOES AND DOES NOT SAY: it records WHICH paths were dirty, never their
    contents. Editing an already-dirty file outside the declared scope moves
    neither this nor `scope_digest`, and that limit is stated here and pinned by a
    case rather than left for a reader to discover. This is a retry
    discriminator, not a reproducible snapshot of the repository.
    """
    if before is None:
        return None, "git could not describe the tree, so it has no fingerprint"
    return (_digest(sorted(before)),
            "git described the tree before the run; %d dirty path(s)"
            % (len(before),))


def tested_state(project, owns, before):
    """The three identity fields, each with the basis that bounds it."""
    scope, sbasis = scope_digest(project, owns)
    dirty, dbasis = dirty_digest(before)
    return {"head": _head(project), "headBasis": HEAD_BASIS,
            "scopeDigest": scope, "scopeBasis": sbasis,
            "dirtyDigest": dirty, "dirtyBasis": dbasis}


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
    for _name, line_re, words in _SUMMARY_READERS:
        found = line_re.findall(text)
        if not found:
            continue
        joined = " ".join(found)
        pairs = _SUMMARY_PAIR.findall(joined)
        if pairs or _NO_TESTS.search(joined):
            return sum(int(n) for n, word in pairs if word in words)
    return None


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


def counts_basis(steps):
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
    """
    if not steps:
        return "no step reported, so there is no count to explain"
    counted = [st for st in steps if st.get("ran") is not None]
    silent = [str(st.get("name")) for st in steps if st.get("ran") is None]
    if not counted:
        return ("no step printed a summary this reader can count (%s), so the "
                "size of this gate is not knowable from its output"
                % (_output.some_of(silent, budget=SAMPLE_BUDGET),))
    if silent:
        return ("%d of %d step(s) printed a summary this reader counted; %s did "
                "not, so this total is a floor and not a size"
                % (len(counted), len(steps),
                   _output.some_of(silent, budget=SAMPLE_BUDGET)))
    return ("counted from each runner's own summary line, over %d step(s)"
            % (len(steps),))


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

    None is NOT an empty set, for `_porcelain`'s reason one function over: a
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
    return [(e, ("%s && %s" % (lead, build.get(e, e))) if lead
             else build.get(e, e))
            for e in entries if isinstance(e, str) and e.strip()]


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


def run_status(steps, failed, ran_total, cancelled_by, refused):
    """The run's one word, from what its steps did, what stopped it, and what it
    rewrote.

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

    `cancelled_by` AND `refused` HAVE NO DEFAULT. There is one production caller,
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
    if failed:
        return "failed"
    if TIMED_OUT in outcomes:
        return TIMED_OUT
    if CANNOT_RUN in outcomes:
        return CANNOT_RUN
    if cancelled_by is not None:
        return CANCELLED
    if ran_total == 0:
        return "no-checks"
    if refused:
        return GATE_MUTATED
    return "passed"


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
    before = _porcelain(project)
    # PRE-EXECUTION, and the placement is load-bearing: a fix-in-place gate
    # rewrites the very files it checks, so a fingerprint taken after the run
    # would describe what the gate PRODUCED rather than what it was asked to
    # judge. Both digests are spent from `before`, above the first command.
    state = tested_state(project, owns, before)
    started = time.monotonic()
    steps, texts = [], []
    cancelled_by = None
    try:
        for name, command in commands:
            step_started = time.monotonic()
            code, text, facts = runner(project, command, timeout)
            texts.append(text or "")
            step = {"name": name, "command": command, "exit": code,
                    "ran": ran_count(command, text),
                    "durationMs": _elapsed_ms(step_started)}
            step.update(facts or {})
            # F302, AND IT SITS BETWEEN THE TWO FOR A REASON. The wrapper's own
            # facts outrank it: a timed-out step was killed by OUR teardown, so
            # its `-15` is this process's signal and not the OS ending the run,
            # and reading it here would relabel every timeout as infrastructure.
            # `never_started` below is an inference off two numbers, so it comes
            # after something the OS reported. The signal and its basis ride on
            # the step because that is where a per-step observation belongs; the
            # LEDGER needs no copy of either, since it already records `exit`
            # and `outcome` and a claim a row can be read for is not cached
            # twice (`_evidence_io.row_for` makes that argument for
            # `treeMutatedOwned`).
            if not step.get("outcome"):
                # THE STEP'S TEXT AND NOT ITS `ran` (F323). What the arm has to
                # know is whether the runner reached its own last line, and
                # `step["ran"]` answers a different question one of whose two
                # provenances is a line tally this reader did. The COMMAND goes
                # with it (F352): a marker in the output of a step that wraps
                # other runners belongs to one of them, not to the step.
                sig_name, sig_basis = ended_by_signal(step["exit"], text,
                                                      command)
                if sig_name:
                    step["outcome"] = CANNOT_RUN
                    step["signal"] = sig_name
                    step["signalBasis"] = sig_basis
            # AFTER the wrapper's own facts, never instead of them: `_shell`
            # observed the failure to spawn directly, and an inference must not
            # overwrite an observation. No basis key is written beside this
            # because the step already carries both halves of it - `exit` and a
            # `ran` of zero ARE the evidence, and a second copy could disagree
            # with them.
            if never_started(step["exit"], step["ran"], step.get("outcome")):
                step["outcome"] = CANNOT_RUN
            steps.append(step)
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
    after = _porcelain(project)
    interrupted = (cancelled_by is not None
                   or any(st.get("outcome") == TIMED_OUT for st in steps))
    if interrupted:
        # A torn-down group is not a stopped one: a descendant that escaped the
        # kill keeps writing, so comparing the two snapshots would be a race whose
        # answer changes with timing. `_porcelain` already refuses to call a tree
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
    counts = [s["ran"] for s in steps if s["ran"] is not None]
    named = files_named("".join(texts)) if texts else None
    overlap, cbasis = coverage(owns, named)
    ran_total = sum(counts) if counts else None
    failed = failed_steps(steps)
    # THE VERDICT READS THE SAME LIST THE VERDICT LINE REFUSES ON. `render` and
    # `--json` take the other half of this pair; before F280 the status word took
    # neither and could only ever say `passed` over a gate that had rewritten its
    # own subject.
    refused, _reported = attributed_mutations(mutated, owned_changes,
                                              foreign_changes)
    return {"steps": steps, "testedState": state,
            "treeMutated": mutated, "treeBasis": basis,
            # THE FULL SET STAYS `treeMutated`, and the split is additive: the
            # ledger keeps recording every path that moved, so nothing a reader
            # could have seen before this is lost, and a consumer that never
            # heard of the split reads exactly what it read before.
            "treeMutatedOwned": owned_changes,
            "treeMutatedForeign": foreign_changes,
            "ranTotal": ran_total, "countsBasis": counts_basis(steps),
            "durationMs": _elapsed_ms(started),
            "status": run_status(steps, failed, ran_total, cancelled_by,
                                 refused),
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
        out("  %-12s exit %-3d %s"
            % (step["name"], step["exit"],
               "%d check(s) ran" % ran if ran is not None
               else "check count not knowable from this runner"))
    code = E_OK
    if res["failed"]:
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
    if unstarted or killed:
        out("GATE COULD NOT RUN: %s reached no verdict. That is an "
            "INFRASTRUCTURE failure and not this work's, so it is not a red "
            "suite and must not be recorded as one. Fix the runner and re-run; "
            "do not spend a retry on the task."
            % (", ".join(unstarted + [st["name"] for st in killed]),))
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
    if res["ranTotal"] == 0 and not unstarted and not killed:
        # `unstarted` OWNS THIS SENTENCE WHEN IT FIRES. The claim below is "that
        # is exit 0", and a step that died at exit 48 having collected no test
        # makes it false - the same zero, a different fact, and the line above
        # already said which. `killed` is here for exactly that reason one cause
        # over: a runner that printed `0 passed` and was then SIGKILLed also
        # reaches a positive zero, and "that is exit 0" is false of `-9` too.
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
    ids = {"phaseId": args.phase}
    if source == "task" or args.task:
        ids["taskId"] = args.task
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
    # ARMED AROUND THE MEASUREMENT AND NOWHERE ELSE. This is the window a stop
    # signal actually lands in - a gate step is where the wall clock goes - and
    # arming it wider would mean holding a handler over the recording below, where
    # a second Ctrl-C should be free to stop a session that is already stopping.
    previous = _arm_interrupt()
    try:
        res = run_gate(project, commands, owns=owns, timeout=args.timeout)
    finally:
        _disarm_interrupt(previous)
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
    return render(res, out=out)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("run-test-gate.py: cases live in "
              "plugins/audit/tests/test_run_test_gate.py")
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
