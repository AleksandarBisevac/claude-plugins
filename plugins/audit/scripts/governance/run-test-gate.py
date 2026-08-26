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

  * DID THE GATE CHANGE THE TREE? `git status --porcelain` before and after. A
    gate is a MEASUREMENT; one with side effects has answered a different
    question than the one asked, and a commit built on it carries work nobody
    reviewed. Any difference refuses the commit step regardless of the gate's own
    exit code.
  * DID ANYTHING ACTUALLY RUN? Runners that say so are read and the count is
    reported. `pre-commit` prints one line per hook and says `Skipped`; nothing
    read it. A count of zero is reported as `NO CHECK RAN`, which is not the same
    answer as green and must never be spelled like it.

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
  1  a command failed, or the gate mutated the tree, or nothing ran
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
CANNOT_RUN = "could-not-run"

DEFAULT_TIMEOUT_SECONDS = 3600
# How long a torn-down group is given to die politely before SIGKILL. Small on
# purpose: this runs after a step has already overrun its whole budget.
GRACE_SECONDS = 5

# --- how much did it do -------------------------------------------------------
# Runners that report their own step count, and the words they end a step with.
# Read as a COUNT and never as a verdict - the verdict is the exit code's job, and
# what was missing is the SIZE of the thing behind it. A runner absent from this
# table yields `None`, which is reported as "not knowable from this runner" and
# never as zero: guessing zero would refuse a passing gate, and guessing one would
# bless a skipped one.
_STEP_WORDS = {
    "pre-commit": ("Passed", "Failed", "Skipped"),
}


def _porcelain(project):
    """`git status --porcelain` as a set of lines, or None when git cannot answer.

    None is NOT an empty tree. A repository git refuses to describe is a basis
    this script does not have, and reporting that as "nothing changed" would be
    the false clean sheet the whole file exists to prevent.
    """
    try:
        out = subprocess.run(["git", "-C", project, "status", "--porcelain"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=60)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return set(ln for ln in out.stdout.decode("utf-8", "replace").splitlines()
               if ln.strip())


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


def ran_count(command, text):
    """How many checks a runner reported doing, or None when it does not say."""
    words = None
    for name, tup in sorted(_STEP_WORDS.items()):
        if name in command:
            words = tup
            break
    if words is None:
        return None
    passed, failed, _skipped = words
    ran = 0
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith(passed) or stripped.endswith(failed):
            ran += 1
    return ran


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


def coverage(task_files, named):
    """`(overlap, basis)` -- which of the task's files the run actually named."""
    owned = [f for f in (task_files or []) if isinstance(f, str) and f.strip()]
    if not owned:
        return None, ("the work under test declares no files, so there is "
                      "nothing to relate a run to")
    if named is None:
        return None, ("this runner printed no file paths, so coverage is not "
                      "knowable from its output")
    hits = sorted(f for f in owned
                  if any(n == f or n.endswith("/" + f) or f.endswith("/" + n)
                         for n in named))
    return hits, ("the runner named %d path(s); the work under test declares "
                  "%d file(s)" % (len(named), len(owned)))


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


def _resolved(entries, build):
    """`[(name, command)]` - gate entries through `meta.buildCommands`, once.

    THE ONE RESOLUTION, shared by both scopes on purpose. A task gate and a phase
    gate are two declarations of the same kind, and resolving them in two places
    would be two answers to "what is a gate entry" the first time the map grew a
    rule. An entry naming no build command is carried VERBATIM, because it may be
    a literal shell command and refusing it would make this script decide what a
    gate is allowed to be.
    """
    return [(e, build.get(e, e)) for e in entries
            if isinstance(e, str) and e.strip()]


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
    if task_id is not None:
        tasks = [t for t in (phases[0].get("tasks") or [])
                 if isinstance(t, dict) and t.get("id") == task_id]
        if not tasks:
            return None, None, "no task %r in phase %r" % (task_id, phase_id)
        tests = tasks[0].get("tests")
        entries = (tests.get("gate") or []) if isinstance(tests, dict) else []
        resolved = _resolved(entries, build)
        if resolved:
            return resolved, "task", None
    return _resolved(phases[0].get("testGate") or [], build), "phase", None


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


def run_status(steps, failed, ran_total):
    """The run's one word, from what its steps did.

    PRECEDENCE, AND WHY IT IS THIS ORDER. `failed` sits ABOVE the two no-verdict
    words deliberately: a step that ran and exited non-zero is a CERTAIN red, and
    reporting that as "timed out" downgrades a finding a reader can act on into
    one they have to reproduce first. Nothing is lost by the ordering, because
    every step keeps its own `outcome` - a run that failed AND timed out says both,
    one level down. That is the same rule `render` already follows for a gate that
    failed and also rewrote the tree: two facts, two sentences, never one.

    `no-checks` sits below `failed` for that reason and above `passed` for the
    opposite one - it is exit 0 and it is still not a verdict.

    AND IT IS READ FROM A POSITIVE ZERO ONLY. `ran_total is None` means the runner
    does not report a count; it is not evidence that nothing ran, so it leaves the
    status alone. Spelling that `not ran_total` would merge the two.
    """
    outcomes = [st.get("outcome") for st in steps]
    if failed:
        return "failed"
    if TIMED_OUT in outcomes:
        return TIMED_OUT
    if CANNOT_RUN in outcomes:
        return CANNOT_RUN
    if ran_total == 0:
        return "no-checks"
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
    for name, command in commands:
        step_started = time.monotonic()
        code, text, facts = runner(project, command, timeout)
        texts.append(text or "")
        step = {"name": name, "command": command, "exit": code,
                "ran": ran_count(command, text),
                "durationMs": _elapsed_ms(step_started)}
        step.update(facts or {})
        steps.append(step)
    after = _porcelain(project)
    interrupted = any(st.get("outcome") == TIMED_OUT for st in steps)
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
    counts = [s["ran"] for s in steps if s["ran"] is not None]
    named = files_named("".join(texts)) if texts else None
    overlap, cbasis = coverage(owns, named)
    ran_total = sum(counts) if counts else None
    failed = failed_steps(steps)
    return {"steps": steps, "testedState": state,
            "treeMutated": mutated, "treeBasis": basis,
            "ranTotal": ran_total, "durationMs": _elapsed_ms(started),
            "status": run_status(steps, failed, ran_total),
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
    if res["treeMutated"]:
        # Said even when the gate also failed: two different facts, and a reader
        # who fixed the failure would otherwise meet the rewrite afterwards.
        # `None` and `[]` are both silent HERE because neither names a file - the
        # difference between them is a claim about the tree, and it is printed by
        # the basis line below rather than being read out of a falsy value.
        out("GATE MUTATED THE TREE: %s" % ", ".join(res["treeMutated"]))
        out("  a gate is a measurement. Do NOT commit on this run - the diff now "
            "carries work no task owns and no review saw. Revert those files, "
            "then either use the read-only spelling of the check (`--check` "
            "rather than `--write`, `ruff check` rather than `ruff --fix`) or "
            "scope the gate to the task's own files.")
        code = E_FAIL
    if res["ranTotal"] == 0:
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
        out("GATE GREEN: %s, tree unchanged%s"
            % (", ".join(s["name"] for s in res["steps"]) or "no commands",
               "" if res["ranTotal"] is None
               else ", %d check(s) ran" % res["ranTotal"]))
    return code


def _record_run(project, args, res, source, commands, out=print):
    """Record the run, then try to point the plan at it. Reports both outcomes.

    THE POINTER IS ALLOWED TO FAIL AND THE ROW IS NOT. The ledger is the source of
    truth; the manifest block is a cache, so a pointer refused by another live
    session leaves the record standing and names the repair. That asymmetry is
    printed rather than folded into one word, because "your run was not recorded"
    and "your plan has not caught up yet" are different problems.
    """
    ids = {"phaseId": args.phase}
    if source == "task" or args.task:
        ids["taskId"] = args.task
    identity = {"runId": _ev.new_run_id(), "via": "cli",
                "sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID") or None}
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
        return {"recorded": False, "pointer": False}
    out("  evidence: recorded %s" % (identity["runId"],))
    pointer = _ev.write_pointer(project, args.manifest, source, ids,
                                recorded["row"],
                                session_id=identity["sessionId"])
    if pointer["written"]:
        out("  pointer:  %s now names it" % (ids.get("taskId") or args.phase,))
    else:
        out("  pointer:  NOT updated - %s" % (pointer["reason"],))
    return {"recorded": True, "pointer": bool(pointer["written"])}


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
    res = run_gate(project, commands, owns=owns, timeout=args.timeout)
    res["gateSource"] = source
    res["subject"] = subject
    # STRICTLY AFTER THE VERDICT, and that placement is the whole of it: the
    # evidence file, the journal and the manifest all live inside the repository
    # this run has just described with `git status --porcelain`, so a write above
    # this line would appear in the very comparison it is being judged by. Every
    # measurement `run_gate` makes is complete before anything here writes.
    if args.record:
        res["recorded"] = _record_run(project, args, res, source, commands,
                                      out=out)
    if args.as_json:
        out(json.dumps(res, indent=2, sort_keys=True))
        # The overlap is absent from this expression ON PURPOSE: it is reported,
        # not enforced, and a machine reader that wants to act on it has the
        # field. Folding it in here would make the decision this entry declined.
        return E_OK if res["status"] == "passed" and not res["treeMutated"] \
            else E_FAIL
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
