#!/usr/bin/env python3
"""Cases for `governance/drive-phase.py`.

WHAT THIS FILE IS ABOUT, in one line: the main loop used to run every step of a
task itself - start, the brief, the gate, the stamp, the reviewer's brief, the
commit, the close - one request each, and the step driver runs every step that
needs no judgement so the main loop makes four requests a task.

EVERY DRIVE HERE IS REAL. The fixture is a committed git repository with a
three-task, one-wave plan, and the driver calls the real verbs as subprocesses:
`audit-task.py`, `audit-lookup.py`, `run-test-gate.py`, `stamp-verification.py`,
`commit-task-work.py` and `audit-lock.py`. The test plays the main loop: it
calls `next`, and when told to dispatch an agent it plays that agent by making
the agent's last act, `drive-phase.py submit`, as a command - which takes the
stamp and files through `audit-task.py file-return`, the one door a return is
written through. The `ds` cases hold `submit` itself: each refusal writes
nothing, and each has the twin that files.

EACH PROPERTY IS SHOWN RED AGAINST A MUTATED DRIVER, inside this suite: a fresh
copy of the module is loaded, one function is replaced with the defect the
property exists against, and the same predicate that holds for the real driver
must fail for the mutant. A predicate that the mutant also satisfies would be
asserting nothing, and the twin is what says so.

A FULL RUN DRIVES ITS STAGES SIDE BY SIDE, each block in a process of its own.
The time goes to the verbs, not to the fixture: every step of a real drive is a
fresh interpreter running a verb, and building a fixture's git repository is a
small share beside them. A block shares no state with another - each builds its
own repositories - so the blocks run concurrently and the parent replays every
case they report, in block order, through one `_harness.run`. The runner is
`_harness.staged_main`, shared with every staged suite. Under the sweep the
blocks are the sweep's own jobs, drawn from its one budget beside every other
suite's, and `--replay` prints what they reported. `--stage` still runs the
named blocks in this process, for a red-first proof in a throwaway tree.

A FULL RUN LASTS AS LONG AS ITS LONGEST BLOCK, at best, so no block may grow
into one. The windows leg starts a process far slower than the others and has
few cores, and a block of many drives held the whole file past the sweep's
per-file cap there while the rest had long finished. So a long block is cut
where no later case reads a name an earlier one bound - at a call to another
block that ended it, or between two groups that each build their own fixture -
and the second half is a `STAGES` row of its own, placed right after the first
so the replayed case order is the one a run in one process gives. `sb1` reads
that each block runs in exactly one stage, since a cut half-made runs cases
twice or never and a green run looks the same either way.
"""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

import _harness                                   # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT)
import _output_lints  # noqa: E402  (the lint half, development code)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path, load_script)
import _manifest_io as _mio                        # noqa: E402  (load_manifest, tasks_by_id)
import _manifest_vocab as _vocab                   # noqa: E402  (LINT_PROBE_KEY: the key the driver and the default gate share)
import _evidence_io as _evio                       # noqa: E402  (read_rows, project_config_for)
import _tree_stamp                                 # noqa: E402  (the dirty digest a row records)
import _filed_returns as _fr                       # noqa: E402  (return_path)
import _machine_paths as _mpaths                   # noqa: E402  (machine_path_shape)

DRIVER = "drive-phase.py"
PHASE = "P1"
TASKS = ("P1.1", "P1.2", "P1.3")
SESSION = "drive-fixture-session"
BOUND = 300

_GIT = list(_harness.GIT)
# What a fixture repository's own config adds after `init`: the identity and the
# signing switch the verbs' commits read, since they run without `_GIT`'s flags.
_FIXTURE_IDENTITY = ("[user]\n\temail = fixture@example.com\n\tname = Fixture\n"
                     "[commit]\n\tgpgsign = false\n")


def _load(modname):
    """A fresh copy of the driver, or `(None, why)` when it cannot be loaded -
    a driver that is not there yet is a failing case, never a raise that ends
    the suite before any case ran."""
    try:
        return _loader.load_script(DRIVER, modname, cache=False), None
    except Exception as exc:                                   # noqa: BLE001
        return None, "%s: %s" % (type(exc).__name__, exc)


# --- the fixture -------------------------------------------------------------
def _plan(task_ids, gate, phase_gate=None):
    tasks = []
    for n, tid in enumerate(task_ids, 1):
        tasks.append({
            "id": tid, "title": "task %d" % (n,), "status": "pending",
            "files": ["src/f%d.txt" % (n,)],
            "description": "change src/f%d.txt" % (n,),
            "dependsOn": [], "blockedBy": [], "attempts": 0, "maxAttempts": 3,
            "commit": None, "outcome": None, "startedAt": None,
            "completedAt": None, "verifiedBy": [], "risk": "low", "skills": [],
            "model": "sonnet",
            "tests": {"mode": "gate-only", "add": [], "gate": list(gate),
                      "expectRedFirst": False}})
    return {"meta": {"version": 2, "developmentBranch": "main",
                     "branchPrefix": "audit"},
            "fileIndex": dict(("src/f%d.txt" % (n,), [tid])
                              for n, tid in enumerate(task_ids, 1)),
            "phases": [{"id": PHASE, "title": "one", "status": "pending",
                        "desiredOutcome": "three files changed",
                        "review": {"model": "sonnet"},
                        "testGate": list(gate if phase_gate is None
                                         else phase_gate), "tasks": tasks}]}


def _repo(prefix, task_ids=TASKS, gate=("true",), per_task="always",
          phase_gate=None, executor=None):
    """A committed repository holding the plan, one source file per task, and
    a `.gitignore` for the driver's and the briefs' state directory. `per_task`
    is `review.perTask`: `always` is the reviewer-per-task drive most cases here
    are about, and the `dk` cases drive the other two readings. `phase_gate`
    is the phase's own `testGate` when it differs from the tasks' gate.
    `executor` is the config's `executor` object, absent when None - the `ws`
    cases set the writer-session keys there, committed with the fixture so the
    tree a gate measures holds no change of the config's own."""
    root = os.path.realpath(_harness.fixture_root("drive-%s-" % (prefix,)))
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    os.makedirs(os.path.join(root, "src"))
    config = {"manifestPath": "docs/audit/audit-plan.json",
              "review": {"perTask": per_task}}
    if executor is not None:
        config["executor"] = executor
    with open(os.path.join(root, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump(config, fh)
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as fh:
        fh.write(".claude/state/\n")
    # At least three sources: the findings these cases hand in name `src/f1.txt`
    # to `src/f3.txt`, and a fix task is scoped only onto a path that exists.
    for n in range(1, max(len(task_ids), 3) + 1):
        with open(os.path.join(root, "src", "f%d.txt" % (n,)), "w",
                  encoding="utf-8") as fh:
            fh.write("v0\n")
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(_plan(task_ids, gate, phase_gate), fh, indent=2)
    # The identity is the repository's own, not only this call's: the verbs the
    # driver runs commit in it too, and a sweep pins HOME and refuses a guessed
    # identity, so nothing else would supply one. It is appended to the config
    # `init` wrote rather than set with one `git config` per key: every fixture
    # pays for each process it starts, and on the windows leg a start is what a
    # full run is made of. `fx1` asks git itself whether it reads the identity.
    _harness.git(root, "init", "-q")
    with open(os.path.join(root, ".git", "config"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_FIXTURE_IDENTITY)
    for argv in (["add", "-A"], ["commit", "-qm", "fixture"]):
        _harness.git(root, *argv)
    return root, mpath


class _Env(object):
    """The session the drive runs under: one session id, so the phase lock the
    driver takes is re-entered by the verbs it calls, and no identity from the
    caller's own session."""

    PINNED = {"CLAUDE_CODE_SESSION_ID": SESSION}
    DROPPED = ("CLAUDE_PID", "AUDIT_LOCK_TOKENS")

    def __init__(self, root):
        self.root = root
        self.held = {}

    # Claude Code's home, which the driver reads for the copy of the plugin
    # whose hooks are loaded: a directory that does not exist unless a case
    # that needs an install record puts one in `CLAUDE_HOME[0]`, so the
    # machine's own installed copy never decides a wave here.
    CLAUDE_HOME = [None]

    def __enter__(self):
        names = list(self.PINNED) + list(self.DROPPED) + [
            "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR"]
        self.held = dict((n, os.environ.get(n)) for n in names)
        for name in self.DROPPED:
            os.environ.pop(name, None)
        os.environ.update(self.PINNED)
        os.environ["CLAUDE_PROJECT_DIR"] = self.root
        os.environ["CLAUDE_CONFIG_DIR"] = (
            self.CLAUDE_HOME[0] or os.path.join(self.root, ".no-claude-home"))
        return self

    def __exit__(self, *exc):
        for name, value in self.held.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return False


def _script(name):
    return [sys.executable, _loader.script_path(name)]


# A `sitecustomize` every child interpreter imports before its script runs: it
# answers an argument-less `time.gmtime()` - the stamp a verb writes, including
# `_utc_stamp.utc_stamp` when it is given no epoch - with one fixed second, and
# leaves every other clock reading alone. A child, because the verbs the driver
# calls are processes of their own and an in-process patch would never reach them.
_PINNED_GMTIME = (
    "import time as _time\n"
    "_real_gmtime = _time.gmtime\n"
    "def _pinned_gmtime(secs=None):\n"
    "    return _real_gmtime(%d if secs is None else secs)\n"
    "_time.gmtime = _pinned_gmtime\n")


@contextlib.contextmanager
def _pinned_clock(at):
    """Every Python child started inside the block stamps the epoch second `at`:
    `time.gmtime()` and `_utc_stamp.utc_stamp()` both read it."""
    where = os.path.realpath(_harness.fixture_root("drive-clock-"))
    with open(os.path.join(where, "sitecustomize.py"), "w", encoding="utf-8") as fh:
        fh.write(_PINNED_GMTIME % (at,))
    held = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = where + (os.pathsep + held if held else "")
    try:
        yield where
    finally:
        if held is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = held
        _harness.remove_tree(where)


# The newline half of a Windows stdout, given to a POSIX child: its text stream
# writes every "\n" as "\r\n", as the Windows text wrapper does, while its byte
# buffer stays untranslated, as it does there too. Only the text layer differs.
_WINDOWS_STDOUT = (
    "import sys as _sys\n"
    "_sys.stdout.reconfigure(newline='\\r\\n')\n")


@contextlib.contextmanager
def _windows_stdout():
    """Every Python child started inside the block writes its text stdout the
    way a Windows one does."""
    where = os.path.realpath(_harness.fixture_root("drive-crlf-"))
    with open(os.path.join(where, "sitecustomize.py"), "w", encoding="utf-8") as fh:
        fh.write(_WINDOWS_STDOUT)
    held = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = where + (os.pathsep + held if held else "")
    try:
        yield where
    finally:
        if held is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = held
        _harness.remove_tree(where)


def _verb(root, name, args, stdin=None):
    # The verbs write UTF-8 whatever the console's code page; decoding them in
    # the locale's would fail on Windows on the first arrow a verb prints.
    done = subprocess.run(_script(name) + args, cwd=root, input=stdin,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    return done.returncode, done.stdout + done.stderr


def _write_lf(path, text):
    """A member's change as the bytes it names: text mode would write CRLF on
    Windows, and the member's own work would then be CRLF before the driver
    carried anything - and the locale's encoding there, cp1252, cannot spell
    every character a change carries."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _edit(root, task_id, text):
    """Write `text` into the task's own file: `src/f<n>.txt` for a fixture task,
    the first file the plan declares for any other - a fix task added in the
    drive."""
    if task_id in TASKS:
        rel = "src/f%d.txt" % (TASKS.index(task_id) + 1,)
    else:
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        rel = (tasks_of(mpath).get(task_id, {}).get("files") or ["src/f1.txt"])[0]
    _write_lf(os.path.join(root, *rel.split("/")), text)


def _executor_body(task_id, over=None):
    """An executor's return as the agent sends it: no `stamp`, which is
    `submit`'s to take."""
    body = {"gates": {}, "outcome": {"technical": "edited the file",
                                     "descriptive": "%s changed" % (task_id,)},
            "testsAdded": [],
            "redFirst": {"status": "not-attempted",
                         "basis": "gate-only: no test is owed"}}
    body.update(over or {})
    return body


def _file_executor(root, mpath, task_id, over=None):
    """Play the executor: change the task's file and make its last act, the
    driver's `submit`, as a command the way an agent runs it. Returns its
    `(code, text)`."""
    _edit(root, task_id, "changed by %s\n" % (task_id,))
    # A tdd task's red-first block is the helper's, so `submit` refuses one
    # with no test command: a fix task the drive adds over a finding naming a
    # source file is tdd, and this fixture has no suite to prove a red with,
    # so the helper is asked over `true` and files what it can say.
    tdd = ((tasks_of(mpath).get(task_id) or {}).get("tests") or {}).get("mode") == "tdd"
    return _verb(root, DRIVER, ["submit", task_id, "--role", "executor", mpath,
                                "--project-dir", root] + (["--", "true"] if tdd else []),
                 stdin=json.dumps(_executor_body(task_id, over)))


def _file_reviewer(root, mpath, task_id, answer="matches"):
    # The note quotes the task's own `description` so a `matches` answer is
    # supported - `_filed_returns.unsupported_match_basis` refuses one that
    # restates the claim with none of the task's own words.
    described = (tasks_of(mpath).get(task_id) or {}).get("description") or ""
    body = {"findings": [],
            "intent": {"answer": answer, "note": "as asked: %s" % (described,)},
            "verdict": "clean"}
    return _verb(root, DRIVER, ["submit", task_id, "--role", "reviewer", mpath,
                                "--project-dir", root], stdin=json.dumps(body))


_BRIEF = re.compile(r"\bbrief=(\S+)")
_HEAD_LINE = re.compile(r"^head: ([0-9a-f]{7,40})\s*$", re.M)


def _answered(root, mpath):
    """`{(task id, commit)}` some filed phase return already answers."""
    project, config = _evio.project_config_for(mpath, root)
    return set(_fr.answered_entries(_fr.phase_returns(
        _evio.evidence_dir(project, config), PHASE)))


def _file_phase_review(root, mpath, text, findings=(), entry_over=None,
                       phase_intent="matches"):
    """Play the phase reviewer: read the head off the brief the dispatch names,
    answer every task the plan holds as `deferred` that no filed phase return
    answers yet - the tasks owed their answers - and file through `submit
    --head`. `entry_over` maps a task id to the fields its entry answers
    differently; `phase_intent` is the phase-level answer. Returns its
    `(code, text)`."""
    brief = _BRIEF.search(text)
    with open(os.path.join(root, *brief.group(1).split("/")), encoding="utf-8") as fh:
        brief_text = fh.read()
    head = _HEAD_LINE.search(brief_text).group(1)
    # Filed as the brief prints it: the set it showed rides on `--shown`, and
    # the verb refuses a return for this head without it.
    shown = re.search(r" --shown (\S+)", brief_text)
    answered = _answered(root, mpath)
    entries = [dict({"id": tid, "commit": t.get("commit"), "answer": "matches",
                     "note": "as asked", "missing": [], "redFirst": "not-attempted",
                     "redFirstBasis": "gate-only: no test is owed",
                     "inheritedTests": "not-asked",
                     "inheritedTestsBasis": "the gate is `true` and selects no "
                                            "test file"},
                    **((entry_over or {}).get(tid) or {}))
               for tid, t in sorted(tasks_of(mpath).items())
               if (t.get("intentCheck") or {}).get("answer") == "deferred"
               and (tid, t.get("commit")) not in answered]
    review = {"findings": list(findings),
              "intent": {"answer": phase_intent, "note": "the phase as asked"},
              "verdict": "findings" if findings else "clean", "tasks": entries}
    return _verb(root, DRIVER, ["submit", PHASE, "--role", "reviewer", mpath,
                                "--project-dir", root, "--head", head]
                 + (["--shown", shown.group(1)] if shown else []),
                 stdin=json.dumps(review))


# --- reading what the driver printed ------------------------------------------
_DISPATCH = re.compile(r"^dispatch (\S+) (\S+)")


def instruction(text):
    """`(kind, agent, task)` of one print: the instruction line, read by this
    file's own pattern rather than the driver's parser, so a parser that drifted
    from what the driver prints cannot agree with itself here."""
    for line in text.splitlines():
        hit = _DISPATCH.match(line)
        if hit:
            role = "executor" if hit.group(1).endswith("executor") else "reviewer"
            return ("dispatch", role, hit.group(2))
        if line.startswith("decide "):
            return ("decide", line.split()[1], None)
        if line.startswith("done "):
            return ("done", None, None)
    return ("none", None, None)


SUMMARY = "three files changed, as the phase asked"


def sign_off(kind, text):
    """The default answer to a decision: the triage signs the phase off with
    its summary; any other decision is left for the case to read."""
    if kind[1] == "triage":
        return ["--answer", "sign-off", "--reason", SUMMARY]
    return None


def drive(M, root, mpath, on_dispatch=None, cap=40, returns=None,
          answer=sign_off, phase_review=True, findings=(), target=PHASE,
          entry_over=None, phase_intent="matches", reviewer_answers=None):
    """Play the main loop until `done`, a stop, or `cap` calls.

    -> {"prints": [(code, text)], "steps": [instruction], "nexts", "dispatches"}
    `on_dispatch(role, task)` runs after the test filed that agent's return,
    for a case that changes the tree between two steps. `answer(kind, text)`
    gives the flags that answer a printed decision, None to run a plain `next`
    again, or False to stop there; `answer=None` stops at the first decision.
    With `phase_review` False the drive stops at the phase review's dispatch
    rather than filing it, and `findings` is what a filed one carries.
    `reviewer_answers` maps a task id to the intent its per-task reviewer
    answers, `matches` where it names none."""
    prints, steps = [], []
    dispatches = 0
    reply = []
    with _Env(root):
        for _ in range(cap):
            said = []
            code = M.main(["next", target, mpath, "--project-dir", root] + reply,
                          out=said.append)
            reply = []
            text = "\n".join(said)
            prints.append((code, text))
            kind = instruction(text)
            steps.append(kind)
            if code != 0 or kind[0] in ("done", "none"):
                break
            if kind[0] == "decide":
                if answer is None:
                    break
                reply = answer(kind, text)
                if reply is False:
                    break
                reply = reply or []
                continue
            if kind[0] == "dispatch":
                _, role, tid = kind
                if tid == PHASE and not phase_review:
                    break
                dispatches += 1
                if role == "executor":
                    _file_executor(root, mpath, tid, (returns or {}).get(tid))
                elif tid == PHASE:
                    _file_phase_review(root, mpath, text, findings,
                                       entry_over, phase_intent)
                else:
                    _file_reviewer(root, mpath, tid, (reviewer_answers or {})
                                   .get(tid, "matches"))
                if on_dispatch is not None:
                    on_dispatch(role, tid)
    return {"prints": prints, "steps": steps, "nexts": len(prints),
            "dispatches": dispatches}


def model_steps(run):
    """The requests the main loop makes for the tasks: every `next` but the one
    that opened the drive, and every dispatch."""
    return run["nexts"] - 1 + run["dispatches"]


TRIAGE = ("decide", "triage", None)
DONE = ("done", None, None)


def expected_sequence(task_ids):
    """Executor and reviewer for each task, then sign-off: with no review
    skill and no task owed a phase answer, the triage and the final step."""
    seq = []
    for tid in task_ids:
        seq += [("dispatch", "executor", tid), ("dispatch", "reviewer", tid)]
    return seq + [TRIAGE, DONE]


def tasks_of(mpath):
    return _mio.tasks_by_id(_mio.load_manifest(mpath))


def _ledger_has_green(root, mpath, task_id):
    project, config = _evio.project_config_for(mpath, root)
    rows = _evio.read_rows(project, config)["rows"]
    return any(isinstance(r, dict) and r.get("taskId") == task_id
               and r.get("status") == "passed" for r in rows)


# --- the cases -----------------------------------------------------------------
def _drive_cases(check):
    M, why = _load("drive_phase_real")
    if M is None:
        for label in ("dp1 the driver loads", ):
            check(label, False, why)
        return
    root, mpath = _repo("main")
    gate_seen = {}

    def note_gate(role, tid):
        # When the reviewer is dispatched, the recorded gate must already be in
        # the ledger: the reviewer reads that run, never makes its own.
        if role == "executor":
            gate_seen[tid] = None
        if tid == "P1.2" and role == "executor":
            # The tree moves under the executor's claim after it was filed.
            _edit(root, tid, "moved after the claim was stamped\n")

    gate_before = {}
    real_dispatch = M.dispatch

    def watching_dispatch(ctx, state, phase, task, role, *tree):
        if role == "reviewer":
            gate_before[task["id"]] = _ledger_has_green(root, mpath, task["id"])
        return real_dispatch(ctx, state, phase, task, role, *tree)
    M.dispatch = watching_dispatch
    try:
        run = drive(M, root, mpath, on_dispatch=note_gate)
    finally:
        M.dispatch = real_dispatch
    steps = run["steps"]
    check("dp1 a drive over a three-task, one-wave plan prints executor, reviewer "
          "for each task in id order, then done: %r" % (steps,),
          steps == expected_sequence(TASKS))
    check("dp2 the main loop makes four requests a task - dispatch the executor, "
          "next, dispatch the reviewer, next - plus the one next that opened the "
          "drive and the one that answers the triage: %d requests for %d tasks"
          % (model_steps(run), len(TASKS)),
          model_steps(run) == 4 * len(TASKS) + 1
          and run["nexts"] == 2 * len(TASKS) + 2)
    sizes = [len(text.encode("utf-8")) for code, text in run["prints"]]
    check("dp3 every success print is at most %d bytes: %r" % (BOUND, sizes),
          all(code == 0 for code, _t in run["prints"])
          and sizes and max(sizes) <= BOUND)
    check("dp4 the recorded gate stays before the reviewer: a green row for the "
          "task is in the ledger at each reviewer dispatch: %r" % (gate_before,),
          gate_before == dict((t, True) for t in TASKS))
    rev = [text for (code, text), s in zip(run["prints"], steps)
           if s[0] == "dispatch" and s[1] == "reviewer"]
    moved = [("scopeDigest" in t) for t in rev]
    check("dp5 a stale stamp prints the field that moved - the task whose file "
          "moved after its claim names scopeDigest, and the twin whose file did "
          "not move does not: %r" % (rev,),
          moved == [False, True, False]
          and all("stamp" in t for t in rev))
    tasks = tasks_of(mpath)
    check("dp6 every task is closed against a commit, and the drive leaves no "
          "lock and no drive state behind: %r"
          % ([(t, tasks.get(t, {}).get("status")) for t in TASKS],),
          all(tasks.get(t, {}).get("status") == "done"
              and tasks.get(t, {}).get("commit") for t in TASKS)
          and not os.path.exists(os.path.join(root, ".claude", "state", "drive"))
          and "phase-%s" % (PHASE,) not in _verb(
              root, "audit-lock.py", ["status", "--project", root])[1])
    marks = M.did_tasks("\n".join(t for _c, t in run["prints"]))
    check("dp7 the driver's own start and close lines are read back as the tasks "
          "it started and closed - what stream-cost's task cycle reads: %r"
          % (marks,),
          marks == {"started": list(TASKS), "closed": list(TASKS)})


def _drive_mutant_cases(check):
    """The drive's properties, each red against a mutated driver - a block of its
    own, because it builds a repository per mutant and nothing above it."""
    # --- each property, red against a mutated driver --------------------------
    mutant, _w = _load("drive_phase_stop_after_close")
    real_close = mutant.close_task

    def close_then_stop(ctx, state, phase, task, intent_basis=None):
        stopped = real_close(ctx, state, phase, task, intent_basis=intent_basis)
        if stopped is not None:
            return stopped
        return mutant.instruction("decide", ["decide continue %s: closed"
                                             % (task["id"],)])
    mutant.close_task = close_then_stop
    root_m, mpath_m = _repo("steps")
    run_m = drive(mutant, root_m, mpath_m)
    check("dp2m RED TWIN: a driver that stops after each close instead of going "
          "on to the next task's dispatch costs more than four requests a task, "
          "and dp2's count catches it - over a drive that still closed every task, "
          "so the extra requests are the mutation's and not a broken drive's: %d"
          % (model_steps(run_m),),
          model_steps(run_m) == 5 * len(TASKS) + 1
          and run_m["steps"][-1] == ("done", None, None))

    mutant, _w = _load("drive_phase_echo")
    mutant.echo_steps = lambda ctx: True
    root_m, mpath_m = _repo("echo", task_ids=TASKS[:1])
    run_m = drive(mutant, root_m, mpath_m, cap=1)
    sizes_m = [len(t.encode("utf-8")) for _c, t in run_m["prints"]]
    check("dp3m RED TWIN: a driver that echoes each verb's output into its print "
          "goes past %d bytes, and dp3's bound catches it: %r" % (BOUND, sizes_m),
          sizes_m and max(sizes_m) > BOUND)

    mutant, _w = _load("drive_phase_no_gate")
    mutant.record_gate = lambda ctx, phase, task: (0, "skipped", "")
    root_m, mpath_m = _repo("nogate", task_ids=TASKS[:1])
    seen = {}
    real_m = mutant.dispatch

    def watch_m(ctx, state, phase, task, role, *tree):
        if role == "reviewer":
            seen[task["id"]] = _ledger_has_green(root_m, mpath_m, task["id"])
        return real_m(ctx, state, phase, task, role, *tree)
    mutant.dispatch = watch_m
    drive(mutant, root_m, mpath_m, cap=2)
    check("dp4m RED TWIN: a driver that dispatches the reviewer without recording "
          "the gate leaves no green row at the dispatch, and dp4 catches it: %r"
          % (seen,), seen == {"P1.1": False})

    mutant, _w = _load("drive_phase_no_field")
    mutant.moved_fields = lambda result: []
    root_m, mpath_m = _repo("nofield", task_ids=TASKS[:1])

    def move(role, tid):
        if role == "executor":
            _edit(root_m, tid, "moved after the claim\n")
    run_m = drive(mutant, root_m, mpath_m, on_dispatch=move, cap=2)
    rev_m = [t for (_c, t), s in zip(run_m["prints"], run_m["steps"])
             if s[0] == "dispatch" and s[1] == "reviewer"]
    check("dp5m RED TWIN: a driver that says only 'stale' and drops the field "
          "never names scopeDigest, and dp5 catches it: %r" % (rev_m,),
          rev_m and not any("scopeDigest" in t for t in rev_m))


def _refusal_cases(check):
    M, why = _load("drive_phase_refusal")
    if M is None:
        check("dr1 the driver loads", False, why)
        return

    def refuse_at_commit(module, prefix):
        """Drive one task to its reviewer, then edit its file after the gate was
        recorded: `commit-task-work.py` refuses a commit the recorded gate no
        longer binds."""
        root, mpath = _repo(prefix, task_ids=TASKS[:1])

        def after(role, tid):
            if role == "reviewer":
                _edit(root, tid, "edited after the gate\n")
        run = drive(module, root, mpath, on_dispatch=after, cap=4)
        return root, mpath, run

    root, mpath, run = refuse_at_commit(M, "refuse")
    code, text = run["prints"][-1]
    task = tasks_of(mpath).get("P1.1", {})
    check("dr1 a refused verb stops the drive: exit 1, no instruction after it, "
          "and the task is not closed: %r" % ((code, run["steps"][-1],
                                               task.get("status")),),
          code == 1 and run["steps"][-1] == ("none", None, None)
          and task.get("status") == "in_progress" and not task.get("commit"))
    check("dr2 the stop prints the verb's own refusal, naming the verb: %r"
          % (text[:400],),
          "[commit-task-work]" in text and "REFUSED" in text
          and any("stopped" in ln and "commit-task-work.py" in ln
                  for ln in text.splitlines()[:2]))

    mutant, _w = _load("drive_phase_refusal_mute")
    mutant.relay_refusal = lambda ctx, script, code, text: (
        mutant.E_STOPPED, "%s %s: stopped" % (mutant.PREFIX, ctx["phase"]))
    _r, _m, run_m = refuse_at_commit(mutant, "mute")
    code_m, text_m = run_m["prints"][-1]
    check("dr2m RED TWIN: a driver that stops with its own sentence instead of the "
          "verb's words loses the refusal and its remedy, and dr2 catches it: %r"
          % (text_m,),
          code_m == 1 and "[commit-task-work]" not in text_m)


def _decide_cases(check):
    M, why = _load("drive_phase_decide")
    if M is None:
        check("dd1 the driver loads", False, why)
        return
    root, mpath = _repo("red", task_ids=TASKS[:1], gate=("false",))
    run = drive(M, root, mpath, cap=3)
    code, text = run["prints"][-1]
    check("dd1 a red recorded gate is a named decision with its options, not a "
          "reviewer dispatch, and fits the bound: %r" % (text,),
          code == 0 and run["steps"][-1] == ("decide", "gate-red", None)
          and "retry" in text and "block" in text
          and len(text.encode("utf-8")) <= BOUND)
    with _Env(root):
        said = []
        again = M.main(["next", PHASE, mpath, "--project-dir", root],
                       out=said.append)
        wrong = []
        bad = M.main(["next", PHASE, mpath, "--project-dir", root,
                      "--answer", "continue"], out=wrong.append)
        bare = []
        unreasoned = M.main(["next", PHASE, mpath, "--project-dir", root,
                             "--answer", "block"], out=bare.append)
        said_b = []
        blocked = M.main(["next", PHASE, mpath, "--project-dir", root,
                          "--answer", "block", "--reason", "the gate is red"],
                         out=said_b.append)
    status = tasks_of(mpath).get("P1.1", {}).get("status")
    check("dd2 an unanswered decision is printed again, an option it does not "
          "offer and a block with no reason are refused, and a block with its "
          "reason blocks the task through the verb: %r"
          % ((again, bad, unreasoned, blocked, status),),
          again == 0 and instruction("\n".join(said))[1] == "gate-red"
          and bad == M.E_USAGE and unreasoned == M.E_USAGE
          and blocked == 0 and status == "blocked")
    dirty = _harness.git(root, "status", "--porcelain", "--", "docs/audit",
                         prefix=("git",))
    check("dd4 a task blocked over its red gate keeps the record of that gate: the "
          "rows the gate wrote and the block are committed through the audit-state "
          "verb, since no task commit is coming to carry them: %r" % (dirty,),
          blocked == 0 and dirty.strip() == ""
          and "record committed" in "\n".join(said_b))


def _attempts(mpath, task_id):
    return tasks_of(mpath).get(task_id, {}).get("attempts")


def _rerun_cases(check):
    """A gate that reached no verdict is the runner's, not the work's: `rerun`
    measures again without re-starting the task, so it spends no attempt, and the
    decision's printed rule says which answer spends one."""
    M, why = _load("drive_phase_rerun")
    if M is None:
        check("dd3 the driver loads", False, why)
        return
    root, mpath = _repo("rerun", task_ids=TASKS[:1], gate=("false",))
    run = drive(M, root, mpath, cap=3)
    _code, text = run["prints"][-1]
    rule = list((M.STEPS.get("decide-gate-red") or {}).get("rule") or ())
    before = _attempts(mpath, "P1.1")
    with _Env(root):
        said = []
        rerun = M.main(["next", PHASE, mpath, "--project-dir", root,
                        "--answer", "rerun"], out=said.append)
    after = _attempts(mpath, "P1.1")
    check("dd3 a red gate's decision offers `rerun` beside `retry` and prints the "
          "rule saying which spends an attempt; answered `rerun`, the gate runs "
          "again and the task is not re-started - its attempts stay %r: %r"
          % (before, (rerun, after, said, text)),
          rule and all(line in text for line in rule)
          and "rerun" in text and rerun == 0 and after == before
          and instruction("\n".join(said))[1] == "gate-red"
          and len(text.encode("utf-8")) <= BOUND)
    with _Env(root):
        said_r = []
        retry = M.main(["next", PHASE, mpath, "--project-dir", root,
                        "--answer", "retry"], out=said_r.append)
    check("dd3m THE TWIN: `retry` re-starts the task and spends one attempt, so the "
          "two answers are not the same answer under two names: %r"
          % ((retry, before, _attempts(mpath, "P1.1")),),
          retry == 0 and _attempts(mpath, "P1.1") == (before or 0) + 1)


def _resume_cases(check):
    """An executor that ended without running its submit block is resumed, not
    retried: `resume` is offered first, spends no attempt and prints one
    instruction; `retry` still spends one."""
    M, why = _load("drive_phase_resume")
    if M is None:
        check("rs1 the driver loads", False, why)
        return
    root, mpath = _repo("resume", task_ids=TASKS[:1])
    _next(M, root, mpath)                       # dispatches the executor
    _code, text = _next(M, root, mpath)         # it filed nothing
    before = _attempts(mpath, "P1.1")
    check("rs1 an executor dispatched and never filed is a decision whose FIRST "
          "option is `resume`, with the rule saying it spends no attempt: %r"
          % (text,),
          instruction(text)[1] == "no-executor-return"
          and "answer: next %s --answer resume|retry|block" % (PHASE,) in text
          and "no attempt" in text and len(text.encode("utf-8")) <= BOUND)
    code, said = _next(M, root, mpath, "--answer", "resume")
    after = _attempts(mpath, "P1.1")
    check("rs2 `--answer resume` spends no attempt and prints the one instruction "
          "- resume the dispatched executor and run its submit block: %r"
          % ((code, said, before, after),),
          code == 0 and after == before and "resume" in said
          and "submit" in said and len(said.splitlines()) <= 2
          and len(said.encode("utf-8")) <= BOUND)
    _file_executor(root, mpath, "P1.1")
    _code, moved = _next(M, root, mpath)
    check("rs4 once the resumed executor files, the drive goes on past the "
          "decision: %r" % (moved,), instruction(moved)[0] != "decide")
    root3, mpath3 = _repo("resume-unfiled", task_ids=TASKS[:1])
    _next(M, root3, mpath3)
    _next(M, root3, mpath3)
    _next(M, root3, mpath3, "--answer", "resume")
    _code, again = _next(M, root3, mpath3)
    check("rs3 until the return is filed the decision is asked again: %r"
          % (again,), instruction(again)[1] == "no-executor-return")
    root2, mpath2 = _repo("resume-retry", task_ids=TASKS[:1])
    _next(M, root2, mpath2)
    _next(M, root2, mpath2)
    b2 = _attempts(mpath2, "P1.1")
    _next(M, root2, mpath2, "--answer", "retry")
    check("rs5 THE TWIN: `retry` still spends one attempt: %r"
          % ((b2, _attempts(mpath2, "P1.1")),),
          _attempts(mpath2, "P1.1") == (b2 or 0) + 1)


def _retry_reason_cases(check):
    """The reason typed beside `--answer retry` is recorded by the driver itself
    and reaches the next attempt's brief. The state is read after a real `next`,
    never written by hand, so removing the recording turns this red."""
    M, why = _load("drive_phase_retry_reason")
    if M is None:
        check("answering retry with --reason records the reason keyed to the new "
              "start, and the generated brief carries it (the driver loads): %r"
              % (why,), False)
        return
    root, mpath = _repo("retry-reason", task_ids=TASKS[:1])
    _next(M, root, mpath)                       # dispatches the executor
    _code, text = _next(M, root, mpath)         # it filed nothing
    old_start = tasks_of(mpath).get("P1.1", {}).get("startedAt")
    reason = "flaky-infra-rr7 rerun as-is"
    code, said = _next(M, root, mpath, "--answer", "retry", "--reason", reason)
    new_start = tasks_of(mpath).get("P1.1", {}).get("startedAt")
    entry = (_drive_state(root).get("retryReason") or {}).get("P1.1") or {}
    want_key = M.start_key({"startedAt": new_start})
    brc, _printed = _verb(root, "audit-lookup.py",
                          [mpath, "brief", "P1.1", "--role", "executor",
                           "--project", root])
    brief = _read(os.path.join(root, ".claude", "state", "briefs", "P1.1",
                               "%s.executor.md" % (want_key,))
                  ).decode("utf-8", "replace")
    line = "operator's reason for --answer retry: %s" % (reason,)
    check("answering retry with --reason records the reason keyed to the new "
          "start, and the generated brief carries it (the decision was %r; "
          "answered code %r; start %r -> %r; recorded %r; brief exit %r, "
          "reason lines %r)"
          % (instruction(text)[1], code, old_start, new_start, entry, brc,
             [ln for ln in brief.splitlines() if "reason for" in ln]),
          instruction(text)[1] == "no-executor-return" and code == 0
          and bool(new_start) and bool(want_key)
          and entry == {"start": want_key, "value": reason}
          and brc == 0 and brief.count(line) == 1)


# --- the writer as a headless session ------------------------------------------
# A full model id in the shape the session runner accepts, a session id in the
# shape the CLI writes, and three costs no two of which share a digit run, so a
# note carrying the wrong session's figure cannot read as the right one.
WRITER_MODEL = "claude-sonnet-4-5"
WRITER_SESSION = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
WRITER_EXECUTOR = {"writerModel": WRITER_MODEL, "writerBudgetUsd": 2.5}
WRITER_COSTS = ("0.4242", "0.5151", "0.6161")

# The `claude` the session runner finds on PATH: it keeps what reached it - its
# argv and the prompt on its stdin - one JSON line per run, writes the files
# `WS_EDIT` maps (and commits them under `WS_COMMIT`), as a writer would, and
# ends the stream with the one `result` event the runner reads the session id
# and cost from, its `result` text `WS_RESULT`.
_WRITER_STUB = r'''
import json, os, subprocess, sys
prompt = sys.stdin.buffer.read().decode("utf-8")
with open(os.environ["WS_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "stdin": prompt}) + "\n")
for rel, text in sorted(json.loads(os.environ.get("WS_EDIT") or "{}").items()):
    with open(os.path.join(*rel.split("/")), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(text)
if os.environ.get("WS_COMMIT"):
    for argv in (["git", "add", "-A"], ["git", "commit", "-qm", "the writer"]):
        subprocess.run(argv, check=True)
sid = os.environ["WS_SESSION"]
if os.environ.get("WS_MODE") == "none":
    sys.stdout.write(json.dumps({"type": "system", "subtype": "init"}) + "\n")
    sys.stdout.flush()
    raise SystemExit(7)
reads = json.loads(os.environ.get("WS_READS") or "null")
if reads is None:
    reads = ["src/mine.py"] * int(os.environ.get("WS_TOOLS") or 0)
tools = [{"type": "tool_use", "id": "t%d" % n, "name": "Read",
          "input": {"file_path": path}} for n, path in enumerate(reads)]
for event in ({"type": "system", "subtype": "init", "session_id": sid},
              {"type": "assistant", "session_id": sid,
               "message": {"role": "assistant",
                           "content": [{"type": "text", "text": "working"}] + tools}},
              {"type": "result", "subtype": "success", "is_error": False,
               "session_id": sid, "total_cost_usd": float(os.environ["WS_COST"]),
               "result": os.environ.get("WS_RESULT") or "done"}):
    sys.stdout.write(json.dumps(event) + "\n")
sys.stdout.flush()
'''


def _writer_stub(where):
    """A PATH directory holding the stub `claude`: a shell wrapper on POSIX and a
    batch file on Windows, each quoting both paths, since the spaced sweep leg
    puts TMPDIR under a directory with a space in it."""
    bindir = os.path.join(where, "bin")
    os.makedirs(bindir)
    stub_py = os.path.join(where, "claude_stub.py")
    with open(stub_py, "w", encoding="utf-8") as fh:
        fh.write(_WRITER_STUB)
    if os.name == "nt":
        with open(os.path.join(bindir, "claude.cmd"), "w", encoding="utf-8") as fh:
            fh.write('@"%s" "%s" %%*\r\n' % (sys.executable, stub_py))
    else:
        path = os.path.join(bindir, "claude")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, stub_py))
        os.chmod(path, 0o755)
    return bindir


def _signal_next(M, root, mpath, *extra):
    """`(code, line)` of one `next --signal`, the form every command runs."""
    with _Env(root):
        said = []
        code = M.main(["next", PHASE, mpath, "--project-dir", root, "--signal"]
                      + list(extra), out=said.append)
    return code, "\n".join(said)


def _explain_of(M, root, mpath, subject):
    """`(code, text)` of `next --explain <subject>`."""
    with _Env(root):
        said = []
        code = M.main(["next", PHASE, mpath, "--project-dir", root, "--explain",
                       subject], out=said.append)
    return code, "\n".join(said)


def _run_argv(text):
    """The argv of the one `run:` line an explain prints, read back the way a
    POSIX shell reads it; None when there is none, and when there are two."""
    runs = [ln[len("run: "):] for ln in text.splitlines() if ln.startswith("run: ")]
    return shlex.split(runs[0]) if len(runs) == 1 else None


def _flag(argv, flag):
    """The value that follows `flag` in `argv`, or None."""
    argv = list(argv or [])
    return argv[argv.index(flag) + 1] if flag in argv[:-1] else None


def _play_session(root, argv, bindir, log, cost, session=WRITER_SESSION,
                  mode="ok", edit=None, result=None, commit=False, tools=0,
                  reads=None):
    """Run the printed session command as the main loop does - its interpreter
    word replaced by this one - with the stub standing for `claude`. `mode`
    `none` makes the stub exit 7 with no result event. `edit` maps the paths
    the stub writes to their text, `result` is its last message, `commit`
    has it commit what it wrote and `tools` is how many tool calls its stream
    holds, each a Read of src/mine.py - or, given `reads`, one Read of each
    path it lists. Returns `(code, output)`."""
    env = dict(os.environ)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    # A TEMP DIRECTORY OF THE FIXTURE'S, removed with it: the runner makes the
    # session's own TMPDIR under the temp directory it is handed and leaves it
    # there, recorded in the scratch, so handed this suite's it left one per
    # session where the sweep's watch reads a leak.
    held = _harness.fixture_root("drive-session-tmp-")
    env.update(TMPDIR=held, TMP=held, TEMP=held)
    env.update(WS_LOG=log, WS_SESSION=session, WS_COST=cost, WS_MODE=mode,
               WS_EDIT=json.dumps(edit or {}), WS_RESULT=(result if result is not None
                          else _said("the session is done")),
               WS_COMMIT="1" if commit else "", WS_TOOLS=str(tools),
               WS_READS=json.dumps(reads) if reads is not None else "")
    done = subprocess.run([sys.executable] + list(argv[1:]), cwd=root, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    return done.returncode, done.stdout + done.stderr


def _stub_runs(log):
    try:
        with open(log, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]
    except OSError:
        return []


def _notes(mpath, task_id):
    return [str((n or {}).get("text") or "")
            for n in tasks_of(mpath).get(task_id, {}).get("notes") or []]


def _streams(text):
    """The stream paths a session runner's printed lines name."""
    return re.findall(r"stream=(.+?)\s*$", text, re.M)


def _writer_session_cases(check):
    """With `executor.writerModel` set, the writer is a headless session the main
    loop runs through `run-agent-session.py`, never an Agent carrying the executor
    body; the cost each session's own result printed is noted on the task; and a
    red task gate resumes the session that wrote the task, spending no attempt,
    for at most two rounds before a fresh retry is the way on."""
    M, why = _load("drive_phase_writer")
    if M is None:
        check("ws1 the driver loads", False, why)
        return
    root, mpath = _repo("writer", task_ids=TASKS[:1], gate=("false",),
                        executor=WRITER_EXECUTOR)
    stubs = os.path.realpath(_harness.fixture_root("drive-writer-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    argv = _run_argv(block) or []
    prompt = _flag(argv, "--prompt-file")
    prompt_text = (_read(prompt).decode("utf-8", "replace")
                   if prompt and os.path.isfile(prompt) else "")
    head = ([ln for ln in block.splitlines() if ln.startswith("dispatch ")]
            or [""])[0]
    check("ws1 the dispatch line for a writer names run-agent-session.py with the "
          "writer role, the task id and the full model id, and names no executor "
          "agent; the run line --explain prints runs that script on the prompt "
          "brief --role writer wrote, resuming nothing: %r"
          % ((code, line, head, argv),),
          code == 0 and "run-agent-session.py --role writer" in line
          and " P1.1 " in line and WRITER_MODEL in line
          and "audit-executor" not in line + block
          and head.startswith("dispatch run-agent-session.py --role writer "
                              "--task P1.1 --model %s" % (WRITER_MODEL,))
          and argv[:1] == ["python3"]
          and os.path.basename(argv[1] if len(argv) > 1 else "")
          == "run-agent-session.py"
          and _flag(argv, "--role") == "writer" and _flag(argv, "--task") == "P1.1"
          and _flag(argv, "--model") == WRITER_MODEL
          and _flag(argv, "--budget-usd") == "2.5" and "--resume" not in argv
          and prompt_text.startswith("Implement the following task in this "
                                     "repository."))
    early, waiting = _signal_next(M, root, mpath)
    _c, wait_block = _explain_of(M, root, mpath, "P1.1")
    record_rel = os.path.relpath(_flag(argv, "--record") or "", root).replace(os.sep, "/")
    check("ws10 a next before the session wrote its record is a wait naming the "
          "record relative to the project, never no-executor-return, and its "
          "explain still holds the run line; no attempt is spent: %r"
          % ((early, waiting, wait_block),),
          early == 0 and " wait P1.1" in waiting
          and "no-executor-return" not in waiting + wait_block
          and record_rel in wait_block
          and not [ln for ln in [waiting] + wait_block.splitlines()
                   if root in ln and not ln.startswith("run: ")]
          and _run_argv(wait_block) == argv
          and _attempts(mpath, "P1.1") == 1)
    # The session writes the task's file; the drive files the return itself at
    # the next step, so nothing here plays an executor.
    ran, said = _play_session(root, argv, bindir, log, WRITER_COSTS[0],
                              edit={"src/f1.txt": "changed by the writer\n"})
    streams = _streams(said)
    before = _attempts(mpath, "P1.1")
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    noted = [n for n in _notes(mpath, "P1.1") if WRITER_SESSION in n]
    check("ws2 the session the runner ran is noted on the task once, naming its "
          "session id and the cost its own result printed: %r"
          % ((ran, said[-200:], noted),),
          ran == 0 and len(noted) == 1 and WRITER_COSTS[0] in noted[0])
    check("ws3 a red task gate on a task with a recorded session is a decision "
          "whose first option is resume, with the rule saying it spends no "
          "attempt: %r" % ((code, line, block),),
          code == 0 and "gate-red-writer" in line
          and "answer: next %s --answer resume|retry|rerun|block" % (PHASE,) in block
          and "no attempt" in block and _attempts(mpath, "P1.1") == before)
    rounds, waits = [], []
    for n, cost in enumerate(WRITER_COSTS[1:], 1):
        code, line = _signal_next(M, root, mpath, "--answer", "resume")
        _c, block = _explain_of(M, root, mpath, "P1.1")
        again = _run_argv(block) or []
        fed = _flag(again, "--prompt-file")
        fed_text = (_read(fed).decode("utf-8", "replace")
                    if fed and os.path.isfile(fed) else "")
        held_code, held = _signal_next(M, root, mpath)
        waits.append((n, held_code, held))
        ran, said = _play_session(root, again, bindir, log, cost)
        streams += _streams(said)
        reached = (_stub_runs(log) or [{}])[-1]
        rounds.append((n, code, line, again, fed_text, ran, reached,
                       _attempts(mpath, "P1.1")))
        code, line = _signal_next(M, root, mpath)
    check("ws4 each resume dispatch runs run-agent-session.py --resume on the "
          "recorded session with the gate's failing lines as its prompt, reaching "
          "claude as such, and spends no attempt: %r" % (rounds,),
          len(rounds) == 2 and all(
              c == 0 and "run-agent-session.py --role writer" in ln
              and _flag(a, "--resume") == WRITER_SESSION
              and _flag(a, "--role") == "writer" and _flag(a, "--task") == "P1.1"
              and _flag(a, "--model") == WRITER_MODEL
              and "GATE RED" in f and not f.startswith("Implement the following")
              and r == 0 and _flag(got.get("argv"), "--resume") == WRITER_SESSION
              and "GATE RED" in (got.get("stdin") or "") and spent == before
              for _n, c, ln, a, f, r, got, spent in rounds))
    check("ws11 a next while a resumed session has written no record is a wait, "
          "so the unfixed tree is not gated and no round is spent on it: %r"
          % (waits,),
          len(waits) == 2 and all(c == 0 and " wait P1.1" in w
                                  and "gate-red" not in w for _n, c, w in waits))
    _c, block = _explain_of(M, root, mpath, "P1.1")
    resumed = streams[1:]
    named = [n for n in _notes(mpath, "P1.1")
             if len(resumed) == 2 and all(os.path.basename(s) in n for s in resumed)]
    check("ws5 the third red after two resumes stops at the plain gate-red, which "
          "offers no resume and keeps a fresh retry, with a note on the task "
          "naming both resumed runs: %r" % ((line, block, resumed, named),),
          "gate-red-writer" not in line
          and block.startswith("decide gate-red P1.1")
          and "answer: next %s --answer retry|rerun|block" % (PHASE,) in block
          and len(named) == 1 and _attempts(mpath, "P1.1") == before)
    # A session's own note carries one cost; the note at the cap names the
    # resumed runs' costs together and is ws5's.
    single = [c[0] for c in ([x for x in WRITER_COSTS if x in n]
                             for n in _notes(mpath, "P1.1")) if len(c) == 1]
    check("ws6 every session the task ran is on it with its own cost, each once, "
          "after more nexts than sessions: %r" % (_notes(mpath, "P1.1"),),
          sorted(single) == sorted(WRITER_COSTS))
    code, line = _signal_next(M, root, mpath, "--answer", "retry")
    _c, block = _explain_of(M, root, mpath, "P1.1")
    fresh = _run_argv(block) or []
    check("ws7 THE TWIN: retry after the cap spends one attempt and dispatches a "
          "fresh writer session, resuming nothing: %r" % ((code, line, fresh),),
          code == 0 and _attempts(mpath, "P1.1") == (before or 0) + 1
          and "run-agent-session.py --role writer" in line
          and _flag(fresh, "--role") == "writer" and "--resume" not in fresh)

    off_root, off_mpath = _repo("writer-off", task_ids=TASKS[:1])
    code, line = _signal_next(M, off_root, off_mpath)
    check("ws8 THE ROLLBACK TWIN: with no executor.writerModel the dispatch is the "
          "executor Agent, as before, and names no session runner: %r" % ((code, line),),
          code == 0 and M.EXECUTOR_AGENT in line
          and "run-agent-session.py" not in line)
    bad_root, bad_mpath = _repo("writer-nobudget", task_ids=TASKS[:1],
                                executor={"writerModel": WRITER_MODEL})
    code, line = _signal_next(M, bad_root, bad_mpath)
    _c, block = _explain_of(M, bad_root, bad_mpath, PHASE)
    check("ws9 a writer model with no per-session budget stops the drive naming "
          "executor.writerBudgetUsd, and dispatches nothing: %r" % ((code, line, block),),
          code == 1 and "executor.writerBudgetUsd" in line + block
          and "run-agent-session.py --role" not in line + block)
    _writer_no_result_cases(check, M, bindir, log)
    _writer_twice_cases(check, M, bindir, log)


# --- after the writer's session: the drive proves, stamps and files ----------------
# The house tally a fixture suite prints, BUILT: the literal is the contract CI
# reads, and a spelled one in a fixture reads as a suite of its own.
_WF_TALLY = "%s: %d/%d cases " + "passed"
_WF_TEST = "tests/test_mine.py"
_WF_SRC = "src/mine.py"
# What the writer's session says last: several lines and a JSON object, so a
# claim kept verbatim is told apart from one trimmed, re-joined or parsed.
def _answer_json(numbers, path=_WF_SRC):
    """The JSON object a writer ends its message with: `numbers` each delivered,
    citing `path` - the file every round of these fixtures leaves in the diff."""
    return json.dumps(dict((str(n), {"delivered": True, "file": path, "line": 1})
                           for n in numbers), sort_keys=True)


def _said(text, numbers=(1,), path=_WF_SRC):
    """`text`, then the answer object as the message's last thing."""
    return "%s\n%s" % (text, _answer_json(numbers, path))


_WF_CLAIM = "All clauses done.\n%s\n  " % (_answer_json((1,)),)


def _wf_suite(cases):
    """A house suite over `src/mine.py`: one PASS/FAIL line per `(label, cond)`
    and the tally, exiting 1 on any failure. Bytecode writing is off before
    the import: the cache is keyed on the source's mtime in whole seconds and
    its size, so two same-size rewrites inside one second would otherwise run
    the first version's code."""
    body = ["import os, sys", "sys.dont_write_bytecode = True",
            "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath("
            "__file__)), '..', 'src'))", "import mine", "results = []"]
    for label, cond in cases:
        body += ["ok = bool(%s)" % (cond,), "results.append(ok)",
                 "print('%%s %s' %% ('PASS' if ok else 'FAIL'))" % (label,)]
    body += ["n = sum(results)",
             "print(%r %% ('ALL PASS' if n == len(results) else 'SELFTEST FAILED',"
             " n, len(results)))" % (_WF_TALLY,),
             "sys.exit(0 if n == len(results) else 1)"]
    return "\n".join(body) + "\n"


_WF_HEAD_TEST = _wf_suite([("old1", "mine.v >= 1")])
_WF_NEW_TEST = _wf_suite([("old1", "mine.v >= 1"), ("new1", "mine.v == 2")])


def _wf_gate():
    """The gate entry that runs the task's suite: this interpreter on the file,
    so the command names the `tests.add` file and the drive can derive it."""
    return '"%s" %s' % (sys.executable.replace("\\", "/"), _WF_TEST)


def _tdd_writer_repo(prefix, gate, description=None, per_task="always",
                     review=None, skills=None):
    """A one-task plan whose task is tdd over `src/mine.py` and its suite,
    under a writer session: HEAD holds `v = 1` and a suite whose one case
    passes there. `gate` is the task's and the phase's gate; `description`
    replaces the task's, which numbers no acceptance clause of its own.
    `per_task` is `review.perTask`, and `review` more keys of the config's
    `review` block, committed with the fixture."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], gate=gate,
                        executor=WRITER_EXECUTOR, per_task=per_task)
    if review:
        cfg = os.path.join(root, ".claude", "audit.config.json")
        with open(cfg, encoding="utf-8") as fh:
            config = json.load(fh)
        config["review"].update(review)
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
    os.makedirs(os.path.join(root, "tests"))
    # The gate runs the suite in this tree, and the bytecode it may leave beside
    # the source is no change of the task's.
    with open(os.path.join(root, ".gitignore"), "a", encoding="utf-8") as fh:
        fh.write("__pycache__/\n")
    _write_lf(os.path.join(root, *_WF_SRC.split("/")), "v = 1\n")
    _write_lf(os.path.join(root, *_WF_TEST.split("/")), _WF_HEAD_TEST)
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    task = plan["phases"][0]["tasks"][0]
    task["files"] = [_WF_SRC, _WF_TEST]
    task["description"] = description or "make v two, and prove it with a case"
    task["tests"] = {"mode": "tdd", "add": ["%s: v is two" % (_WF_TEST,)],
                     "gate": list(gate), "expectRedFirst": True}
    if skills is not None:
        task["skills"] = list(skills)
    plan["fileIndex"] = {_WF_SRC: ["P1.1"], _WF_TEST: ["P1.1"]}
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "the task's suite"]):
        _harness.git(root, *argv)
    return root, mpath


def _filed_body(mpath, task_id):
    """The executor return filed for `task_id`'s current start, or None."""
    path = _filed_path(mpath, task_id)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sha_of(root, rel):
    with open(os.path.join(root, *rel.split("/")), "rb") as fh:
        return "sha256:" + hashlib.sha256(fh.read()).hexdigest()


def _head_of(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def _writer_round(M, root, mpath, bindir, log, cost, **play):
    """Dispatch (or read back) the writer, run its session with `play`, and
    take the next step. Returns `(code, line)` of that step."""
    _c, block = _explain_of(M, root, mpath, "P1.1")
    _play_session(root, _run_argv(block) or [], bindir, log, cost, **play)
    return _signal_next(M, root, mpath)


def _writer_files_cases(check):
    """After a writer session the drive runs what `submit` ran for an executor:
    the red in a throwaway at HEAD on the session's uncommitted change, held
    with its test digest locked until the recorded gate is green, then the
    stamp and the filing - the session's last message kept as its claim."""
    M, why = _load("drive_phase_writer_files")
    if M is None:
        check("wf1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-wf-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("wf-proved", (_wf_gate(),))
    _signal_next(M, root, mpath)
    code, line = _writer_round(M, root, mpath, bindir, log, "0.31",
                               edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                               result=_WF_CLAIM)
    body = _filed_body(mpath, "P1.1") or {}
    red = body.get("redFirst") or {}
    digest = red.get("testDigest") or {}
    files = dict((f.get("path"), f.get("sha256")) for f in digest.get("files") or []
                 if isinstance(f, dict))
    check("wf1 after the session the drive files the return itself: its red-first "
          "block is the helper's and proved, carries the sha256 of the task's test "
          "file as the session left it, and keeps the session's last message as "
          "the writer's claim; the diff's paths and a stamp ride with it: %r"
          % ((code, line, body),),
          code == 0 and red.get("status") == "proved"
          and red.get("source") == _fr.HELPER_SOURCE
          and files == {_WF_TEST: _sha_of(root, _WF_TEST)}
          and re.match(r"^sha256:[0-9a-f]{64}$", str(digest.get("sha256") or ""))
          and body.get("writerClaim") == _WF_CLAIM
          and sorted(body.get("diffPaths") or []) == sorted([_WF_SRC, _WF_TEST])
          and str(body.get("stamp") or "").startswith("audit-stamp:")
          and body.get("gates") == {})
    check("wf2 THE CLAIM IS NOT A VERDICT: the filed outcome says the writer's "
          "words are its claim, and the gate the drive ran is what turned the "
          "step green, not the message: %r" % ((line, body.get("outcome")),),
          "claim" in json.dumps(body.get("outcome") or {})
          and "reviewer" in line and "gate-red" not in line)
    _file_reviewer(root, mpath, "P1.1")
    code2, line2 = _signal_next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1") or {}
    check("wf3 THE TWIN of the refused commit: with the test file as the proof "
          "left it, the close commits and the task is done: %r"
          % ((code2, line2, task.get("status")),),
          task.get("status") == "done" and task.get("commit"))

    root_n, mpath_n = _tdd_writer_repo("wf-nocmd", ("true",))
    _signal_next(M, root_n, mpath_n)
    _writer_round(M, root_n, mpath_n, bindir, log, "0.32",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                  result=_said("done"))
    red_n = (_filed_body(mpath_n, "P1.1") or {}).get("redFirst") or {}
    check("wf4 a tdd task whose gate names no tests.add file has no derivable test "
          "command, so its return is filed with red-first could-not-prove naming "
          "that basis and the file, never proved: %r" % (red_n,),
          red_n.get("status") == "could-not-prove"
          and _WF_TEST in str(red_n.get("basis") or "")
          and "no test command" in str(red_n.get("basis") or ""))
    _writer_commit_cases(check, M, bindir, log)


# --- a writer's edit outside the task's files ---------------------------------
# A tracked document no task declares, as the measured writer edited one: the
# writer's prompt states no scope, so its aside is set apart, never refused.
_XS_ASIDE = "GUIDE.md"
_XS_HEAD = "the guide as committed\n"
_XS_EDIT = "the guide as the writer rewrote it\n"
_XS_PATCH = re.compile(r"(\S+\.patch)\b")
# And a file the writer creates that no task declares: untracked, so it is put
# back to HEAD by being removed, and its patch is a new file's.
_XS_NEW = "notes/scratch.md"
_XS_NEW_TEXT = "a note the writer left beside its work\n"


def _xs_with_aside(root):
    """Commit `_XS_ASIDE` into the fixture: a path the plan never declares."""
    _write_lf(os.path.join(root, _XS_ASIDE), _XS_HEAD)
    _harness.git(root, "add", _XS_ASIDE)
    _harness.git(root, "commit", "-qm", "fixture: a document no task declares")


def _xs_patch_notes(mpath, task_id):
    """`[(note, patch path)]` for each note on the task naming a patch."""
    return [(n, _XS_PATCH.search(n).group(1)) for n in _notes(mpath, task_id)
            if _XS_PATCH.search(n)]


def _writer_scope_cases(check):
    """On the writer path an edit outside the task's files is saved as a patch
    under the run's state, put back to HEAD, named in a note, and left out of
    a commit that carries the declared work; on the executor path the same
    edit still refuses the close."""
    M, why = _load("drive_phase_writer_scope")
    if M is None:
        check("xs1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-xs-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("xs-writer", (_wf_gate(),))
    _xs_with_aside(root)
    os.makedirs(os.path.join(root, "notes"))
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.41",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST,
                        _XS_ASIDE: _XS_EDIT, _XS_NEW: _XS_NEW_TEXT},
                  result=_WF_CLAIM)
    _file_reviewer(root, mpath, "P1.1")
    code, line = _signal_next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1") or {}
    committed = sorted(_git_out(root, "show", "--name-only", "--format=",
                                task.get("commit") or "HEAD").split())
    with open(os.path.join(root, _XS_ASIDE), encoding="utf-8") as fh:
        left = fh.read()
    noted = _xs_patch_notes(mpath, "P1.1")
    patch = noted[0][1] if len(noted) == 1 else ""
    held = ""
    if patch and not os.path.isabs(patch) and os.path.isfile(
            os.path.join(root, *patch.split("/"))):
        with open(os.path.join(root, *patch.split("/")), encoding="utf-8") as fh:
            held = fh.read()
    # Mutations this is the red for: no revert at all (the commit refuses and
    # the task stays in progress); a revert of every changed path (the
    # declared work is gone from the commit); a revert with no patch kept, or
    # no note, or a note that names a declared path or a machine path.
    work = [p for p in committed if not p.startswith("docs/audit/")]
    created = os.path.exists(os.path.join(root, *_XS_NEW.split("/")))
    check("xs1 a writer session that also edited a tracked file and created one, "
          "neither declared by the task: the task closes on a commit of its "
          "declared files and the plan's records, without either; the edited "
          "file is back at HEAD's bytes and the created one is gone; one note "
          "names both and a patch under the run's state, relative to the "
          "project, that holds both of the writer's changes and names no "
          "declared file: %r"
          % ((code, line[-400:], task.get("status"), committed, left, created,
              noted, held[-600:]),),
          task.get("status") == "done" and bool(task.get("commit"))
          and work == sorted([_WF_SRC, _WF_TEST])
          and left == _XS_HEAD and not created
          and len(noted) == 1 and _XS_ASIDE in noted[0][0]
          and _XS_NEW in noted[0][0]
          and _WF_SRC not in noted[0][0] and _WF_TEST not in noted[0][0]
          and root not in noted[0][0]
          and patch.startswith(".claude/state/")
          and _XS_EDIT.strip() in held and _XS_ASIDE in held
          and _XS_NEW_TEXT.strip() in held and _XS_NEW in held
          and _WF_SRC not in held and _WF_TEST not in held)
    applies = subprocess.run(_GIT + ["apply", "--check", patch], cwd=root,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace") if held else None
    check("xs2 the kept patch is the writer's edit as git reads it: it applies "
          "to the tree the commit left, so the aside can be taken back by hand: "
          "%r" % ((applies.returncode, applies.stderr[-300:]) if applies else
                  "no patch read",),
          applies is not None and applies.returncode == 0)
    project, config = _evio.project_config_for(mpath, root)
    runs = [r for r in _evio.read_rows(project, config)["rows"]
            if isinstance(r, dict) and r.get("taskId") == "P1.1"]
    # The red for a set-aside that commits on the gate measured before it: the
    # ledger records no list of what a run read, so the gate is measured again.
    check("xs4 the gate is measured again on the tree the set-aside left: two "
          "green runs of the task are recorded, the newest after the patch was "
          "kept: %r" % (([(r.get("status"), r.get("ts")) for r in runs], patch),),
          len(runs) == 2 and all(r.get("status") == "passed" for r in runs)
          and bool(re.search(r"-(\d{8}T\d{6}Z)\.patch$", patch))
          and max(str(r.get("ts") or "") for r in runs).replace("-", "")
          .replace(":", "") >= re.search(r"-(\d{8}T\d{6}Z)", patch).group(1))

    root_c, mpath_c = _tdd_writer_repo("xs-cited", (_wf_gate(),))
    _xs_with_aside(root_c)
    _signal_next(M, root_c, mpath_c)
    _writer_round(M, root_c, mpath_c, bindir, log, "0.43",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST,
                        _XS_ASIDE: _XS_EDIT},
                  result=_said("clause one is in the guide", (1,), _XS_ASIDE))
    _file_reviewer(root_c, mpath_c, "P1.1")
    code_c, line_c = _signal_next(M, root_c, mpath_c)
    _c, block_c = _explain_of(M, root_c, mpath_c, PHASE)
    with open(os.path.join(root_c, _XS_ASIDE), encoding="utf-8") as fh:
        left_c = fh.read()
    # The red for a set-aside blind to the writer's own answer: a clause the
    # writer delivered in that file would become a gap nobody was told of.
    check("xs5 a file the writer's answer cites for a clause is not set aside: "
          "the commit's refusal is relayed with why, the edit stays and no "
          "patch is noted: %r" % ((code_c, line_c, block_c[-600:], left_c,
                                   _xs_patch_notes(mpath_c, "P1.1")),),
          code_c != 0
          and (tasks_of(mpath_c).get("P1.1") or {}).get("status") == "in_progress"
          and "not set aside" in line_c + block_c and "clause" in line_c + block_c
          and left_c == _XS_EDIT and _xs_patch_notes(mpath_c, "P1.1") == [])

    # GIT CANNOT SAY WHETHER THE CONFIGURATION FILE IS TRACKED. The set-aside
    # reads the plugin-owned rows as what it must NOT revert, so for it an
    # unknown answer protects the file; the same unknown refuses the commit and
    # the close (the `sc-ua13` to `sc-ua16` cases). Two shapes: the placement
    # alone, and the whole drive over a writer that edited the committed config
    # - where the red is a config put back to HEAD, whose patch the note names.
    config_rel = ".claude/audit.config.json"
    root_g, mpath_g = _tdd_writer_repo("xs-blind", (_wf_gate(),))
    real_run_git = M._scoped_commit.run_git

    def blind_to_tracking(git_root, args, *rest, **kwargs):
        if list(args[:3]) == ["ls-files", "-z", "--"]:
            return None, "", "git could not be run (fixture)"
        return real_run_git(git_root, args, *rest, **kwargs)

    M._scoped_commit.run_git = blind_to_tracking
    try:
        unit_blind = M.plugin_owned_paths({"project": root_g, "gitRoot": root_g},
                                          [config_rel, _XS_ASIDE])
        _signal_next(M, root_g, mpath_g)
        with open(os.path.join(root_g, *config_rel.split("/")),
                  encoding="utf-8") as fh:
            config_head = fh.read()
        config_edit = config_head + "\n"
        _writer_round(M, root_g, mpath_g, bindir, log, "0.46",
                      edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST,
                            config_rel: config_edit},
                      result=_WF_CLAIM)
        _file_reviewer(root_g, mpath_g, "P1.1")
        code_g, line_g = _signal_next(M, root_g, mpath_g)
        _c, block_g = _explain_of(M, root_g, mpath_g, PHASE)
    finally:
        M._scoped_commit.run_git = real_run_git
    with open(os.path.join(root_g, *config_rel.split("/")),
              encoding="utf-8") as fh:
        config_after = fh.read()
    check("xs6b where git cannot say whether the configuration file is tracked, "
          "the set-aside protects it - the placement names it plugin-owned, a "
          "writer's edit of it is neither reverted nor deleted, no patch is "
          "noted, the refusal is relayed saying the file is plugin-owned state "
          "no set-aside reverts, and the task stays in progress: %r"
          % ((unit_blind, code_g, line_g[-300:], block_g[-300:],
              _xs_patch_notes(mpath_g, "P1.1")),),
          unit_blind == [config_rel] and code_g != 0
          and (tasks_of(mpath_g).get("P1.1") or {}).get("status") == "in_progress"
          and config_after == config_edit and config_after != config_head
          and _xs_patch_notes(mpath_g, "P1.1") == []
          and "plugin-owned state, which no set-aside reverts"
              in line_g + block_g and config_rel in line_g + block_g)

    root_d, mpath_d = _tdd_writer_repo("xs-dirty", (_wf_gate(),))
    _xs_with_aside(root_d)
    os.makedirs(os.path.join(root_d, "notes"))
    # An edit that is not the writer's, there before the start: an owner's, or
    # another session's in the shared checkout.
    owner = _XS_HEAD + "an owner's line, uncommitted\n"
    _write_lf(os.path.join(root_d, _XS_ASIDE), owner)
    _signal_next(M, root_d, mpath_d)
    both = owner + "and the writer's line\n"
    _writer_round(M, root_d, mpath_d, bindir, log, "0.45",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST,
                        _XS_ASIDE: both, _XS_NEW: _XS_NEW_TEXT},
                  result=_WF_CLAIM)
    _file_reviewer(root_d, mpath_d, "P1.1")
    code_d, line_d = _signal_next(M, root_d, mpath_d)
    _c, block_d = _explain_of(M, root_d, mpath_d, PHASE)
    with open(os.path.join(root_d, _XS_ASIDE), encoding="utf-8") as fh:
        left_d = fh.read()
    noted_d = _xs_patch_notes(mpath_d, "P1.1")
    said_d = line_d + "\n" + block_d
    # The red for a set-aside that reverts to HEAD whatever the start held: the
    # owner's line would be gone and the note would call it the writer's.
    check("xs7 a file dirty before the start and touched by the writer too is "
          "never put back: its bytes stay as the tree held them, the task is "
          "refused naming it as dirty before the attempt, and a file clean at "
          "the start in the same run is still set aside, its patch noted: %r"
          % ((code_d, said_d[-700:], left_d, noted_d),),
          code_d != 0
          and (tasks_of(mpath_d).get("P1.1") or {}).get("status") == "in_progress"
          and left_d == both
          and "%s %s not set aside: dirty before the attempt, or no start "
              "snapshot to tell" % (M.PREFIX, _XS_ASIDE) in said_d
          and not os.path.exists(os.path.join(root_d, *_XS_NEW.split("/")))
          and len(noted_d) == 1 and _XS_NEW in noted_d[0][0]
          and _XS_ASIDE not in noted_d[0][0])

    refused = {"committed": False, "refused": "x"}
    shapes = [
        M.undeclared_split(dict(refused, attempt={
            "during": ["c.md", "b.md", "a.md", "b.md"], "declaredPredates": [],
            "mixed": [], "cleanAtStart": ["b.md", "a.md"]})),
        M.undeclared_split(dict(refused, attempt={
            "during": ["a.md"], "declaredPredates": [], "mixed": []})),
        M.undeclared_split(dict(refused, attempt={
            "during": ["a.md"], "declaredPredates": ["src/mine.py"], "mixed": [],
            "cleanAtStart": ["a.md"]})),
        M.undeclared_split(dict(refused, attempt={
            "during": ["a.md"], "declaredPredates": [], "mixed": ["src/mine.py"],
            "cleanAtStart": ["a.md"]})),
        M.undeclared_split(dict(refused, attempt=None)),
        M.undeclared_split({"committed": True, "refused": "x",
                            "attempt": {"during": ["a.md"],
                                        "cleanAtStart": ["a.md"]}}),
        M.undeclared_split(None)]
    # The fixture commits its config, so the table's untracked-only row is not
    # the plugin's here; the same call after the config leaves the index is.
    root_o, _mpath_o = _repo("xs-owned", task_ids=TASKS[:1], per_task="phase")
    owned_paths = [
        ".claude/audit-backups/plan.json", ".claude/.gitignore",
        ".claude/audit.config.json", ".claude/audit-backups-not/x", "GUIDE.md",
        "docs/.claude/audit-backups/y"]
    owned_tracked = M.plugin_owned_paths(
        {"project": root_o, "gitRoot": root_o}, owned_paths)
    _harness.git(root_o, "rm", "--cached", "-q", "--",
                 ".claude/audit.config.json")
    owned = M.plugin_owned_paths({"project": root_o, "gitRoot": root_o},
                                 owned_paths)
    # Both directions: a refusal with any other part beside the undeclared
    # paths sets nothing aside, and only the table's rows are plugin-owned.
    check("xs6 only a refusal whose whole reason is undeclared paths names "
          "paths to set aside - those the commit shows clean at the start, each "
          "once and sorted - and holds back the rest; an answer naming no "
          "cleanAtStart shows none clean; a declared file older than the start, "
          "one of mixed age, any other arm, or a commit made names none - and "
          "only the plugin-owned table's rows under .claude/ are never "
          "reverted - a config git tracks is a project file, so a task's edit "
          "of it is set aside like any other undeclared one: %r"
          % ((shapes, owned, owned_tracked),),
          shapes == [(["a.md", "b.md"], ["c.md"]), ([], ["a.md"]), ([], []),
                     ([], []), ([], []), ([], []), ([], [])]
          and owned == [".claude/audit-backups/plan.json", ".claude/.gitignore",
                        ".claude/audit.config.json"]
          and owned_tracked == [".claude/audit-backups/plan.json",
                                ".claude/.gitignore"])

    root_e, mpath_e = _repo("xs-executor", task_ids=TASKS[:1], per_task="phase")
    _xs_with_aside(root_e)
    _next(M, root_e, mpath_e)
    _write_lf(os.path.join(root_e, _XS_ASIDE), _XS_EDIT)
    _file_executor(root_e, mpath_e, "P1.1")
    code_e, text_e = _next(M, root_e, mpath_e)
    task_e = tasks_of(mpath_e).get("P1.1") or {}
    with open(os.path.join(root_e, _XS_ASIDE), encoding="utf-8") as fh:
        left_e = fh.read()
    # The twin for a revert that fires on every path: the subagent executor
    # path keeps refusing, the file untouched and no patch noted.
    check("xs3 THE TWIN: the same undeclared edit on the executor path still "
          "refuses the close by name, leaves the edit in the tree and keeps no "
          "patch: %r" % ((code_e, task_e.get("status"), text_e[-500:], left_e,
                          _xs_patch_notes(mpath_e, "P1.1")),),
          code_e != 0 and task_e.get("status") == "in_progress"
          and _XS_ASIDE in text_e and M.CLOSED not in text_e
          and left_e == _XS_EDIT and _xs_patch_notes(mpath_e, "P1.1") == [])


def _writer_commit_cases(check, M, bindir, log):
    """A session that committed is told from HEAD moved by something else: its
    own commit (descending from the dispatch, touching the task's files) is
    named and files nothing until a human takes it out; any other move says
    only that HEAD moved, and the work may be filed against the new HEAD."""
    root_c, mpath_c = _tdd_writer_repo("wf-commit", (_wf_gate(),))
    _signal_next(M, root_c, mpath_c)
    start_head = _head_of(root_c)
    spent = _attempts(mpath_c, "P1.1")
    code_c, line_c = _writer_round(M, root_c, mpath_c, bindir, log, "0.33",
                                   edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                                   commit=True)
    _c, block_c = _explain_of(M, root_c, mpath_c, "P1.1")
    left = _head_of(root_c)
    check("wf5 a session that left a commit of the task's files stops with a "
          "decision naming that commit, offering only what works with it there - "
          "block, or recheck once a human took it out - and files nothing: %r"
          % ((code_c, line_c, block_c, left[:12]),),
          code_c == 0 and left != start_head
          and "writer-committed" in line_c and left[:12] in line_c + block_c
          and "--answer recheck|block" in block_c and "retry" not in block_c
          and _filed_body(mpath_c, "P1.1") is None)
    again_code, again = _signal_next(M, root_c, mpath_c, "--answer", "recheck")
    still = _filed_body(mpath_c, "P1.1")
    _harness.git(root_c, "reset", "-q", "--soft", start_head)
    back_code, back = _signal_next(M, root_c, mpath_c, "--answer", "recheck")
    filed_back = (_filed_body(mpath_c, "P1.1") or {}).get("redFirst") or {}
    check("wf6 recheck while the commit is still there asks again and files "
          "nothing; once a human took it out of history (its changes kept), "
          "recheck files the work, proved, spending no attempt: %r"
          % ((again_code, again, back_code, back, filed_back.get("status")),),
          "writer-committed" in again and still is None
          and filed_back.get("status") == "proved"
          and _attempts(mpath_c, "P1.1") == spent)

    root_o, mpath_o = _tdd_writer_repo("wf-other", (_wf_gate(),))
    _signal_next(M, root_o, mpath_o)
    _c, block_o = _explain_of(M, root_o, mpath_o, "P1.1")
    _play_session(root_o, _run_argv(block_o) or [], bindir, log, "0.34",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST})
    # Another session in the same checkout commits a file of no task's.
    _write_lf(os.path.join(root_o, "src", "f3.txt"), "a sibling's commit\n")
    for argv in (["add", "src/f3.txt"], ["commit", "-qm", "a sibling"]):
        _harness.git(root_o, *argv)
    code_o, line_o = _signal_next(M, root_o, mpath_o)
    _c, explain_o = _explain_of(M, root_o, mpath_o, "P1.1")
    check("wf7 HEAD moved by a commit that touches none of the task's files is "
          "not called the writer's: the decision says HEAD moved past the "
          "dispatch, and files nothing yet: %r" % ((code_o, line_o, explain_o),),
          code_o == 0 and "writer-committed" not in line_o + explain_o
          and "head-moved" in line_o and "HEAD moved past the dispatch" in explain_o
          and _filed_body(mpath_o, "P1.1") is None)
    file_code, filed_line = _signal_next(M, root_o, mpath_o, "--answer", "file")
    red_o = (_filed_body(mpath_o, "P1.1") or {}).get("redFirst") or {}
    check("wf8 ...and `file` files the uncommitted work against the new HEAD, "
          "red proved there: %r" % ((file_code, filed_line, red_o.get("status")),),
          red_o.get("status") == "proved")
    manifest = _mio.load_manifest(mpath_o)
    phase = (manifest.get("phases") or [{}])[0]
    task = dict(tasks_of(mpath_o).get("P1.1") or {},
                tests={"mode": "tdd", "add": ["%s: v is two" % (_WF_TEST,)],
                       "gate": ['python3 %s_old' % (_WF_TEST,)]})
    cmd, basis = M.writer_test_command(manifest, phase, task)
    check("wf9 the writer's test command is the one reader's: a gate naming "
          "only a longer path beginning with the file's name derives none: %r"
          % ((cmd, basis),), cmd is None and "no test command" in str(basis))


def _writer_lock_cases(check):
    """The digest locked at the proof binds the commit; a resume round that
    changes a test file is proved again before anything is filed, and a
    re-proof that no longer proves, or a red the helper refuses, is a
    decision that goes back to the writer, never a filing."""
    M, why = _load("drive_phase_writer_lock")
    if M is None:
        check("wl1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-wl-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("wl-moved", (_wf_gate(),))
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.41",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, result=_said("done"))
    _file_reviewer(root, mpath, "P1.1")
    head = _head_of(root)
    _write_lf(os.path.join(root, *_WF_TEST.split("/")),
              _WF_NEW_TEST + "# edited after the proof\n")
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    task = tasks_of(mpath).get("P1.1") or {}
    check("wl1 a test file edited after the filed proof and its review makes the "
          "commit refuse naming the file, offering no re-proof - the filing and "
          "the review were of other bytes - and the task stays open: %r"
          % ((code, line, block, task.get("status")),),
          "tests-moved" in line and _WF_TEST in line + block
          and "--answer retry|block" in block and "reprove" not in block
          and _head_of(root) == head and task.get("status") == "in_progress")
    spent = _attempts(mpath, "P1.1")
    refused_code, refused = _signal_next(M, root, mpath, "--answer", "reprove")
    retry_code, retried = _signal_next(M, root, mpath, "--answer", "retry")
    check("wl2 ...`reprove` is not an answer it takes, and `retry` starts the "
          "task again - a fresh writer session, an attempt spent, no commit made: "
          "%r" % ((refused_code, refused, retry_code, retried),),
          refused_code == 2 and retry_code == 0
          and "run-agent-session.py --role writer" in retried
          and _attempts(mpath, "P1.1") == (spent or 0) + 1 and _head_of(root) == head)

    # The first session's fix is wrong (v = 3), so the gate is red; the resume
    # round fixes it and changes the test file.
    root_r, mpath_r = _tdd_writer_repo("wl-resume", (_wf_gate(),))
    _signal_next(M, root_r, mpath_r)
    code_r, line_r = _writer_round(M, root_r, mpath_r, bindir, log, "0.42",
                                   edit={_WF_SRC: "v = 3\n", _WF_TEST: _WF_NEW_TEST},
                                   result=_said("first try"))
    early = _filed_body(mpath_r, "P1.1")
    _signal_next(M, root_r, mpath_r, "--answer", "resume")
    moved = _WF_NEW_TEST + "# the resume round touched the suite\n"
    # The module under test is imported by the gate's suite, so the round-0
    # gate left bytecode for `v = 3` keyed on the source's mtime (whole
    # seconds) and size. Two rewrites inside one second of the same size are
    # what CI produced by chance; here the mtime is put back after the resume
    # session so every run meets it, and the probe checks it applied.
    src_r = os.path.join(root_r, *_WF_SRC.split("/"))
    before = os.stat(src_r)
    _c, block_r = _explain_of(M, root_r, mpath_r, "P1.1")
    _play_session(root_r, _run_argv(block_r) or [], bindir, log, "0.43",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: moved},
                  result=_said("second try"))
    after = os.stat(src_r)
    os.utime(src_r, ns=(before.st_atime_ns, before.st_mtime_ns))
    pinned = os.stat(src_r)
    check("wl3p the resume session rewrote src/mine.py to the same size with new "
          "bytes, and its mtime was put back to the value the round-0 gate's "
          "bytecode was keyed on, so the probe applies: %r"
          % ((before.st_size, after.st_size, before.st_mtime_ns, pinned.st_mtime_ns),),
          after.st_size == before.st_size and _read(src_r) == b"v = 2\n"
          and pinned.st_mtime_ns == before.st_mtime_ns)
    code_s, line_s = _signal_next(M, root_r, mpath_r)
    listed = [n for n in _notes(mpath_r, "P1.1")
              if _WF_TEST in n and "re-prove" in n and "proved" in n]
    late = _filed_body(mpath_r, "P1.1") or {}
    late_red = late.get("redFirst") or {}
    late_files = dict((f.get("path"), f.get("sha256"))
                      for f in (late_red.get("testDigest") or {}).get("files") or [])
    check("wl3 nothing is filed while the gate is red; the resume round that "
          "changed a test file is proved again, the change noted on the task and "
          "listed in the return, and the return filed at the green gate carries "
          "the re-proof's block and digest and the last session's message: %r"
          % ((line_r, early, line_s, _notes(mpath_r, "P1.1"), late),),
          "gate-red-writer" in line_r and early is None and len(listed) == 1
          and "reviewer" in line_s and late_red.get("status") == "proved"
          and late_files == {_WF_TEST: _sha_of(root_r, _WF_TEST)}
          and [r.get("changed") for r in late.get("reproofs") or []] == [[_WF_TEST]]
          and late.get("writerClaim") == _said("second try"))
    _file_reviewer(root_r, mpath_r, "P1.1")
    _signal_next(M, root_r, mpath_r)
    check("wl4 ...and the close commits: %r"
          % (tasks_of(mpath_r).get("P1.1", {}).get("status"),),
          tasks_of(mpath_r).get("P1.1", {}).get("status") == "done")
    _writer_refused_cases(check, M, bindir, log)
    _writer_clause_cases(check, M, bindir, log)


# Two Acceptance items beside the one `tests.add` entry: three clauses the
# writer's last message owes an answer to, numbered by the lookup's own list.
_WC_DESCRIPTION = ("make v two, and prove it. Acceptance: (1) v is two; "
                   "(2) the suite proves it")


def _clause_prompt(M, root, mpath):
    """The prompt text the next dispatch of the task's writer is fed, read off
    the command `--explain` prints."""
    _c, block = _explain_of(M, root, mpath, "P1.1")
    argv = _run_argv(block) or []
    fed = _flag(argv, "--prompt-file")
    text = (_read(fed).decode("utf-8", "replace")
            if fed and os.path.isfile(fed) else "")
    return argv, text


def _writer_clause_cases(check, M, bindir, log):
    """A green gate does not file a return whose clauses the writer left
    unanswered: the session is resumed with the uncovered ones, the round counts
    toward the two, and once they are spent the plain decision is asked."""
    edit = {_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}
    root, mpath = _tdd_writer_repo("wc-gap", (_wf_gate(),), _WC_DESCRIPTION)
    _signal_next(M, root, mpath)
    code, line = _writer_round(M, root, mpath, bindir, log, "0.51", edit=edit,
                               result=_said("done", (1, 3)))
    _c, block = _explain_of(M, root, mpath, "P1.1")
    check("wk1 the gate is green, yet clause 2 has no answer: nothing is filed "
          "and the decision going back to the writer names clause 2 and no "
          "other: %r" % ((code, line, block),),
          code == 0 and "clauses-uncovered-writer" in line
          and "clause 2" in line and "clause 1" not in line
          and "clause 3" not in line and "--answer resume|block" in block
          and _filed_body(mpath, "P1.1") is None)

    resumed_code, resumed = _signal_next(M, root, mpath, "--answer", "resume")
    argv, fed_text = _clause_prompt(M, root, mpath)
    check("wk2 `resume` sends the uncovered clause's number and words to the "
          "session that wrote the task, in a prompt that does not repeat the "
          "answered ones: %r" % ((resumed_code, resumed, fed_text[:300]),),
          resumed_code == 0 and _flag(argv, "--resume") == WRITER_SESSION
          and "clause 2: v is two" in fed_text
          and "the suite proves it" not in fed_text
          and "test_mine.py: v is two" not in fed_text)

    code_b, line_b = _writer_round(M, root, mpath, bindir, log, "0.52", edit={},
                                   result=_said("now all of it", (1, 2, 3)))
    body = _filed_body(mpath, "P1.1") or {}
    check("wk3 the resumed session answers every clause: the gate is measured "
          "again over its fix, the return is filed with that message as the "
          "claim, and the reviewer is next: %r" % ((code_b, line_b, body.get(
              "writerClaim")),),
          code_b == 0 and "reviewer" in line_b
          and body.get("writerClaim") == _said("now all of it", (1, 2, 3)))

    # The resumed session leaves a file behind that a second gate command
    # refuses; the proof of the declared files still holds, so only a gate
    # measured again can notice.
    flag_gate = '"%s" -c "import os, sys; sys.exit(1 if os.path.exists(\'bad.flag\') else 0)"' % (
        sys.executable.replace("\\", "/"),)
    again, again_path = _tdd_writer_repo("wc-regate", (_wf_gate(), flag_gate),
                                         _WC_DESCRIPTION)
    _signal_next(M, again, again_path)
    _writer_round(M, again, again_path, bindir, log, "0.58", edit=edit,
                  result=_said("partial", (1, 3)))
    _signal_next(M, again, again_path, "--answer", "resume")
    _c, regated = _writer_round(M, again, again_path, bindir, log, "0.59",
                                edit={"bad.flag": "x\n"},
                                result=_said("all of it", (1, 2, 3)))
    check("wk7 the green gate that asked for the clause is not the last word: the "
          "resumed session left what the gate refuses, so the gate is measured "
          "again over its work - red, going back to the writer - and nothing is "
          "filed on the strength of the earlier green: %r" % (regated,),
          "gate-red-writer" in regated and _filed_body(again_path, "P1.1") is None)

    capped, capped_path = _tdd_writer_repo("wc-cap", (_wf_gate(),), _WC_DESCRIPTION)
    _signal_next(M, capped, capped_path)
    seen = []
    result = _said("partial", (1, 3))
    _c, first = _writer_round(M, capped, capped_path, bindir, log, "0.53",
                              edit=edit, result=result)
    seen.append(first)
    for cost in ("0.54", "0.55"):
        _signal_next(M, capped, capped_path, "--answer", "resume")
        _c, again = _writer_round(M, capped, capped_path, bindir, log, cost,
                                  edit={}, result=result)
        seen.append(again)
    _c, last_block = _explain_of(M, capped, capped_path, "P1.1")
    check("wk4 a clause gap counts as a resume round: the first two gaps go back "
          "to the writer, and the third - the two rounds spent - is the plain "
          "decision whose answers are retry and block, with nothing filed: %r"
          % (seen,),
          "clauses-uncovered-writer" in seen[0] and "clauses-uncovered-writer" in seen[1]
          and "clauses-uncovered-writer" not in seen[2]
          and "clauses-uncovered" in seen[2] and "--answer retry|block" in last_block
          and _filed_body(capped_path, "P1.1") is None)

    outside, outside_path = _tdd_writer_repo("wc-path", (_wf_gate(),),
                                             _WC_DESCRIPTION)
    _signal_next(M, outside, outside_path)
    _writer_round(M, outside, outside_path, bindir, log, "0.56", edit=edit,
                  result=_said("done", (1, 2, 3), path="src/nowhere.py"))
    _c, said_outside = _explain_of(M, outside, outside_path, "P1.1")
    check("wk5 a delivered answer that cites a file the diff does not touch is a "
          "gap, and the decision names the path: %r" % (said_outside,),
          "clauses-uncovered-writer" in said_outside and "src/nowhere.py" in said_outside
          and _filed_body(outside_path, "P1.1") is None)

    bare, bare_path = _tdd_writer_repo("wc-bare", (_wf_gate(),), _WC_DESCRIPTION)
    _signal_next(M, bare, bare_path)
    _writer_round(M, bare, bare_path, bindir, log, "0.57", edit=edit,
                  result="done, all of it")
    _c, said_bare = _explain_of(M, bare, bare_path, "P1.1")
    check("wk6 a message with no JSON object is a gap of every clause - three "
          "numbers named, nothing filed: %r" % (said_bare,),
          "clauses-uncovered-writer" in said_bare and "clause 1:" in said_bare
          and "clause 2:" in said_bare and "clause 3:" in said_bare
          and _filed_body(bare_path, "P1.1") is None)


def _writer_refused_cases(check, M, bindir, log):
    """A re-proof that stops proving and a red the helper will not grade both
    go back to the writer as a decision, and file nothing."""
    # A gate that stays red whatever the suite does, so the resume round comes.
    root, mpath = _tdd_writer_repo("wl-weakened", (_wf_gate(), "false"))
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.44",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, result=_said("one"))
    _signal_next(M, root, mpath, "--answer", "resume")
    crashing = _wf_suite([("old1", "mine.v >= 1"), ("new1", "1 / (mine.v - 1) == 1")])
    code, line = _writer_round(M, root, mpath, bindir, log, "0.45",
                               edit={_WF_TEST: crashing}, result=_said("two"))
    _c, block = _explain_of(M, root, mpath, "P1.1")
    check("wl5 a resume round whose test change leaves the red no longer proved "
          "(the new case crashes at HEAD) is a decision going back to the writer, "
          "naming what the re-proof found; the lock stays and nothing is filed: %r"
          % ((code, line, block),),
          code == 0 and "red-refused-writer" in line and "could-not-prove" in block
          and "--answer resume|block" in block
          and _filed_body(mpath, "P1.1") is None)

    root_p, mpath_p = _tdd_writer_repo("wl-passing", (_wf_gate(),))
    _signal_next(M, root_p, mpath_p)
    passing = _wf_suite([("old1", "mine.v >= 1"), ("new1", "mine.v >= 1")])
    code_p, line_p = _writer_round(M, root_p, mpath_p, bindir, log, "0.46",
                                   edit={_WF_SRC: "v = 2\n", _WF_TEST: passing},
                                   result=_said("done"))
    resumed_code, resumed = _signal_next(M, root_p, mpath_p, "--answer", "resume")
    _c, run_block = _explain_of(M, root_p, mpath_p, "P1.1")
    again = _run_argv(run_block) or []
    fed = _flag(again, "--prompt-file")
    fed_text = (_read(fed).decode("utf-8", "replace")
                if fed and os.path.isfile(fed) else "")
    check("wl6 a test that passes without the fix gets no block from the helper: "
          "the writer path asks red-refused-writer rather than stopping, files "
          "nothing, and resume sends the helper's words to the session that "
          "wrote it: %r" % ((code_p, line_p, resumed_code, resumed, fed_text[:200]),),
          code_p == 0 and "red-refused-writer" in line_p and " stop " not in line_p
          and _filed_body(mpath_p, "P1.1") is None
          and _flag(again, "--resume") == WRITER_SESSION
          and "red-first" in fed_text)


def _sibling_commit(root, text):
    """Another session in the same checkout commits a file of no task's."""
    _write_lf(os.path.join(root, "src", "f3.txt"), text)
    for argv in (["add", "src/f3.txt"], ["commit", "-qm", "a sibling"]):
        _harness.git(root, *argv)


def _filed_stamp_head(body):
    """The HEAD a filed return's stamp names (git's short spelling), or why
    none reads."""
    stamp, problem = _tree_stamp.parse_stamp(str((body or {}).get("stamp") or ""))
    return (stamp or {}).get("head") or problem


def _names_head(spelled, head):
    """Whether `spelled` (a stamp's short HEAD) is a spelling of `head`."""
    return bool(spelled) and len(spelled) >= 7 and str(head or "").startswith(spelled)


def _proved_then_red(M, root, mpath, bindir, log):
    """Round 0 proves and holds, and the gate stays red on a word the fix lacks,
    so the resume round comes. Returns round 0's red-first `at`."""
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.51",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, result=_said("zero"))


def _writer_invariant_cases(check):
    """THE INVARIANT: a writer's return is filed only with a proof made over the
    HEAD and the declared test and implementation files it is filed with -
    whichever way HEAD moved, and never from a round that produced no result."""
    M, why = _load("drive_phase_writer_invariant")
    if M is None:
        check("wi1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-wi-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    gate = (_wf_gate(), "grep -q fixed src/mine.py")

    root, mpath = _tdd_writer_repo("wi-moved", gate)
    _proved_then_red(M, root, mpath, bindir, log)
    _signal_next(M, root, mpath, "--answer", "resume")
    _sibling_commit(root, "a sibling, during the resume round\n")
    code, line = _writer_round(M, root, mpath, bindir, log, "0.52",
                               edit={_WF_SRC: "v = 2  # fixed\n"}, result=_said("one"))
    filed_code, filed_line = _signal_next(M, root, mpath, "--answer", "file")
    body = _filed_body(mpath, "P1.1") or {}
    red = body.get("redFirst") or {}
    now = _head_of(root)
    check("wi1 HEAD moved by a sibling during a resume round, answered `file`: "
          "the return is filed with a proof made at the HEAD it is filed at, "
          "the one its stamp names, never round 0's: %r"
          % ((line, filed_line, red.get("head"), _filed_stamp_head(body), now),),
          "head-moved" in line and red.get("status") == "proved"
          and red.get("head") == now and _names_head(_filed_stamp_head(body), now))

    # The gate waits on a word in a file no task declares; the sibling's commit
    # before the resume carries it, and the round changes nothing, so HEAD is
    # the only thing that moved since the proof.
    root_v, mpath_v = _tdd_writer_repo("wi-before", (_wf_gate(),
                                                     "grep -q fixed src/f3.txt"))
    _proved_then_red(M, root_v, mpath_v, bindir, log)
    _sibling_commit(root_v, "fixed by a sibling, before the resume\n")
    _signal_next(M, root_v, mpath_v, "--answer", "resume")
    code_v, line_v = _writer_round(M, root_v, mpath_v, bindir, log, "0.53",
                                   edit={}, result=_said("one"))
    body_v = _filed_body(mpath_v, "P1.1") or {}
    red_v = body_v.get("redFirst") or {}
    now_v = _head_of(root_v)
    check("wi2 ...and a sibling commit that lands before the resume, so no "
          "head-moved is ever asked and HEAD is all that moved, still files only "
          "a proof made at the HEAD it is filed at: %r"
          % ((line_v, red_v.get("head"), now_v),),
          red_v.get("status") == "proved" and red_v.get("head") == now_v
          and _names_head(_filed_stamp_head(body_v), now_v))

    root_i, mpath_i = _tdd_writer_repo("wi-impl", gate)
    _proved_then_red(M, root_i, mpath_i, bindir, log)
    _signal_next(M, root_i, mpath_i, "--answer", "resume")
    _writer_round(M, root_i, mpath_i, bindir, log, "0.55",
                  edit={_WF_SRC: "v = 2  # fixed\n"}, result=_said("one"))
    impl_i = dict((f.get("path"), f.get("sha256")) for f in (
        ((_filed_body(mpath_i, "P1.1") or {}).get("redFirst") or {})
        .get("implementationDigest") or {}).get("files") or [])
    check("wi4 a resume round that changed only the implementation is proved "
          "again: the filed block names the implementation bytes it is filed "
          "with: %r" % (impl_i,), impl_i == {_WF_SRC: _sha_of(root_i, _WF_SRC)})

    root_f, mpath_f = _tdd_writer_repo("wi-late", (_wf_gate(),
                                                   "grep -q fixed src/f3.txt"))
    _proved_then_red(M, root_f, mpath_f, bindir, log)
    # Between the settled round and the green gate, outside any session, the
    # gate's word lands and the implementation moves: only the filing's own
    # check sees it.
    _write_lf(os.path.join(root_f, "src", "f3.txt"), "fixed\n")
    _write_lf(os.path.join(root_f, *_WF_SRC.split("/")), "v = 2  # moved late\n")
    _signal_next(M, root_f, mpath_f, "--answer", "rerun")
    impl_f = dict((f.get("path"), f.get("sha256")) for f in (
        ((_filed_body(mpath_f, "P1.1") or {}).get("redFirst") or {})
        .get("implementationDigest") or {}).get("files") or [])
    check("wi5 a tree that moved after the round settled, before the green gate, "
          "is proved again by the filing itself before it files: %r" % (impl_f,),
          impl_f == {_WF_SRC: _sha_of(root_f, _WF_SRC)})

    root_b, mpath_b = _tdd_writer_repo("wi-noresult", gate)
    _proved_then_red(M, root_b, mpath_b, bindir, log)
    _signal_next(M, root_b, mpath_b, "--answer", "resume")
    weakened = _wf_suite([("old1", "mine.v >= 1"), ("new1", "mine.v >= 1")])
    code_b, line_b = _writer_round(M, root_b, mpath_b, bindir, log, "0.54",
                                   mode="none",
                                   edit={_WF_SRC: "v = 2  # fixed\n",
                                         _WF_TEST: weakened})
    check("wi3 a resume round whose session produced no result files nothing - "
          "not round 0's proof over a test it no longer is - and dispatches no "
          "reviewer: %r" % ((code_b, line_b),),
          code_b == 0 and _filed_body(mpath_b, "P1.1") is None
          and "reviewer" not in line_b)

    # The same round with nothing the proof would refuse: the implementation
    # alone changes, so a re-proof would prove - and still no result, no filing.
    root_n, mpath_n = _tdd_writer_repo("wi-noresult-impl", gate)
    _proved_then_red(M, root_n, mpath_n, bindir, log)
    _signal_next(M, root_n, mpath_n, "--answer", "resume")
    code_n, line_n = _writer_round(M, root_n, mpath_n, bindir, log, "0.56",
                                   mode="none", edit={_WF_SRC: "v = 2  # fixed\n"})
    check("wi6 ...and a no-result round whose change a re-proof would prove "
          "files nothing either: the round, not the proof, is what is missing: %r"
          % ((code_n, line_n),),
          code_n == 0 and _filed_body(mpath_n, "P1.1") is None
          and "no-executor-return" in line_n)


def _writer_reading_cases(check):
    """What the writer path owes and says: red-first from a tdd task alone, a
    HEAD git cannot name asked about rather than passed, and the case binding's
    absence explained in the return."""
    M, why = _load("drive_phase_writer_reading")
    if M is None:
        check("wj1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-wj-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("wj-regression", (_wf_gate(),))
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["phases"][0]["tasks"][0]["tests"]["mode"] = "regression"
    plan["phases"][0]["tasks"][0]["tests"]["expectRedFirst"] = False
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "regression mode"]):
        _harness.git(root, *argv)
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.61",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, result=_said("done"))
    red = (_filed_body(mpath, "P1.1") or {}).get("redFirst") or {}
    check("wj1 a regression-mode writer task is not asked for red-first: its "
          "return is filed not-attempted with the mode as the basis, and goes "
          "to the gate: %r" % (red,),
          red.get("status") == "not-attempted"
          and "regression" in str(red.get("basis") or "")
          and red.get("source") is None)

    root_u, mpath_u = _tdd_writer_repo("wj-unknown", (_wf_gate(),))
    _signal_next(M, root_u, mpath_u)
    _c, block = _explain_of(M, root_u, mpath_u, "P1.1")
    _play_session(root_u, _run_argv(block) or [], bindir, log, "0.62",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST})
    real = M.tree_head
    M.tree_head = lambda ctx, tree=None: None
    try:
        code_u, line_u = _signal_next(M, root_u, mpath_u)
    finally:
        M.tree_head = real
    check("wj2 a HEAD git cannot name after the session is a decision saying so, "
          "never a pass of the commit check, and nothing is filed: %r"
          % ((code_u, line_u),),
          code_u == 0 and "head-unknown" in line_u
          and _filed_body(mpath_u, "P1.1") is None)
    _c2, line_f = _signal_next(M, root_u, mpath_u, "--answer", "file")
    body_u = _filed_body(mpath_u, "P1.1") or {}
    check("wj3 THE TWIN: with HEAD readable again, `file` proves and files: %r"
          % ((line_f, (body_u.get("redFirst") or {}).get("status")),),
          (body_u.get("redFirst") or {}).get("status") == "proved")
    check("wj4 a drive-filed return says why it carries no casesAdded, and its "
          "gap list names the tests.add entry: %r"
          % ((body_u.get("casesAddedBasis"), body_u.get(_fr.GAPS_FIELD)),),
          "casesAdded" not in body_u
          and "writer" in str(body_u.get("casesAddedBasis") or "")
          and len(body_u.get(_fr.GAPS_FIELD) or []) == 1)


def _no_machine_path(text, root):
    """Whether `text` names no absolute path of the fixture or the machine: the
    shapes `audit-task.py note` refuses, and the fixture root in any spelling."""
    return (root not in text and os.path.realpath(root) not in text
            and _mpaths.machine_path_shape(text) is None)


def _writer_no_result_cases(check, M, bindir, log):
    """A session that ends without a result - claude exiting with no result
    event, or the runner unable to make a directory it needs - leaves a note
    naming no machine path, and the drive goes on; a note the verb refuses is
    recorded and never asked again; the cap's note names a missing record
    relative to the project."""
    root, mpath = _repo("writer-noresult", task_ids=TASKS[:1],
                        executor=WRITER_EXECUTOR)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    argv = _run_argv(block) or []
    ran, said = _play_session(root, argv, bindir, log, "0.1", mode="none")
    code, line = _signal_next(M, root, mpath)
    notes = _notes(mpath, "P1.1")
    check("ws12 a session that ended with no result (could-not-run naming its "
          "stream) is noted with no machine path and no cost, and the drive goes "
          "on rather than stopping: %r" % ((ran, said[-160:], code, line, notes),),
          ran == 3 and "could-not-run" in said and code == 0
          and " stop " not in line and len(notes) == 1
          and "no result" in notes[0] and _no_machine_path(notes[0], root))
    blocker = os.path.join(root, ".claude", "state", "a-file")
    with open(blocker, "w", encoding="utf-8") as fh:
        fh.write("x\n")
    io_argv = list(argv)
    io_argv[io_argv.index("--scratch") + 1] = os.path.join(blocker, "scratch")
    # The same printed command run again, its scratch below a file.
    ran2, said2 = _play_session(root, io_argv, bindir, log, "0.1")
    code2, line2 = _signal_next(M, root, mpath)
    notes = _notes(mpath, "P1.1")
    check("ws13 an io-error line is noted with no machine path either, and the "
          "drive goes on: %r" % ((ran2, said2[-160:], code2, line2, notes),),
          ran2 == 5 and "io-error" in said2 and code2 == 0
          and " stop " not in line2 and len(notes) == 2
          and all(_no_machine_path(n, root) for n in notes))
    # A note the verb refuses: recorded, the drive goes on, and the same
    # record is not offered to the verb again at the next step.
    root3, mpath3 = _repo("writer-refused", task_ids=TASKS[:1],
                          executor=WRITER_EXECUTOR)
    _signal_next(M, root3, mpath3)
    _c, block3 = _explain_of(M, root3, mpath3, "P1.1")
    _play_session(root3, _run_argv(block3) or [], bindir, log, "0.2")
    calls = []
    real = M.run_verb

    def refusing(ctx, script, args, stdin=None, record=False):
        if script == "audit-task.py" and "note" in args:
            calls.append(list(args))
            return 1, "[audit-task] REFUSED: a refusal this case stands in\n", ""
        return real(ctx, script, args, stdin=stdin, record=record)
    M.run_verb = refusing
    try:
        first, said_a = _next(M, root3, mpath3)
        second, said_b = _next(M, root3, mpath3)
    finally:
        M.run_verb = real
    check("ws14 a note the verb refuses does not stop the drive: the step says it "
          "was not noted, goes on, and the record is not offered again: %r"
          % ((first, said_a, second, said_b, len(calls)),),
          first == 0 and second == 0 and len(calls) == 1
          and "not noted" in said_a and " stop " not in said_a + said_b)
    ctx = {"project": root, "stateDir": os.path.join(root, ".claude", "state")}
    record = os.path.join(ctx["stateDir"], "sessions", "drive", "P1.1.x.2.jsonl")
    note = M.cap_note(ctx, {"dispatches": [{"seq": 2, "round": 1, "record": record}],
                            "runs": []}, WRITER_SESSION)
    check("ws15 the cap's note names a resume round whose record never appeared "
          "relative to the project, with no machine path: %r" % (note,),
          ".claude/state/sessions/drive/P1.1.x.2.jsonl" in note
          and _no_machine_path(note, root))
    _cap_kinds_cases(check, M)


def _cap_kinds_cases(check, M):
    """The cap's note says what spent the budget: a clause round and a red
    gate round are named as such, not all taken for the red gate's."""
    stubs = os.path.realpath(_harness.fixture_root("drive-ck-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    flag_gate = '"%s" -c "import os, sys; sys.exit(1 if os.path.exists(\'bad.flag\') else 0)"' % (
        sys.executable.replace("\\", "/"),)
    root, mpath = _tdd_writer_repo("ck", (_wf_gate(), flag_gate), _WC_DESCRIPTION)
    _signal_next(M, root, mpath)
    _writer_round(M, root, mpath, bindir, log, "0.61",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                  result=_said("partial", (1, 3)))
    _signal_next(M, root, mpath, "--answer", "resume")
    _writer_round(M, root, mpath, bindir, log, "0.62", edit={"bad.flag": "x\n"},
                  result=_said("all", (1, 2, 3)))
    _signal_next(M, root, mpath, "--answer", "resume")
    _c, last = _writer_round(M, root, mpath, bindir, log, "0.63", edit={},
                             result=_said("all", (1, 2, 3)))
    capped = [n for n in _notes(mpath, "P1.1") if "still red after" in n]
    note = capped[0] if len(capped) == 1 else ""
    check("ck1 a clause round and a red gate round that spend the budget are each "
          "named for what they were in the cap's note: %r" % ((capped, last),),
          "round 1 (clause coverage)" in note and "round 2 (red gate)" in note
          and "red-first proof" in note)
    twin = M.cap_note({"project": root, "stateDir": os.path.join(root, ".claude", "state")},
                      {"dispatches": [{"seq": 1, "round": 1, "record": "/x/r.jsonl"}],
                       "runs": []}, WRITER_SESSION)
    check("ck2 THE TWIN: a round whose dispatch recorded no kind is named by its "
          "number alone - a kind is never made up for it: %r" % (twin,),
          "round 1: no record" in twin and "round 1 (" not in twin)


def _writer_twice_cases(check, M, bindir, log):
    """The printed command run twice in one dispatch: both sessions are noted,
    each once with its own cost, and a red gate resumes the later one."""
    later = "9a8b7c6d-5e4f-4a3b-9c2d-1e0f9a8b7c6d"
    root, mpath = _repo("writer-twice", task_ids=TASKS[:1], gate=("false",),
                        executor=WRITER_EXECUTOR)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    argv = _run_argv(block) or []
    _play_session(root, argv, bindir, log, "0.7311")
    _play_session(root, argv, bindir, log, "0.8422", session=later,
                  edit={"src/f1.txt": "changed by the later session\n"})
    code, line = _signal_next(M, root, mpath)
    notes = _notes(mpath, "P1.1")
    _signal_next(M, root, mpath, "--answer", "resume")
    _c, block = _explain_of(M, root, mpath, "P1.1")
    again = _run_argv(block) or []
    check("ws16 a command run twice leaves both sessions on the task, each once "
          "with its own cost, and the resume goes to the later session: %r"
          % ((line, notes, _flag(again, "--resume")),),
          "gate-red-writer" in line
          and len([n for n in notes if WRITER_SESSION in n and "0.7311" in n]) == 1
          and len([n for n in notes if later in n and "0.8422" in n]) == 1
          and _flag(again, "--resume") == later)


def _review_json(mpath, task_id="P1.1"):
    """The reviewer return a session ends its message with: clean, its intent
    note quoting the task's own description."""
    described = (tasks_of(mpath).get(task_id) or {}).get("description") or ""
    return json.dumps({"findings": [], "verdict": "clean", "intent": {
        "answer": "matches", "note": "as asked: %s" % (described,)}})


RV_SESSIONS = ("11111111-2222-4333-8444-555555555551",
               "11111111-2222-4333-8444-555555555552",
               "11111111-2222-4333-8444-555555555553")


def _reviewer_dispatch(M, bindir, log):
    """A tdd task whose writer session already ran and was filed by the drive,
    so the step now printed dispatches its reviewer. Returns `(root, mpath,
    line)`."""
    root, mpath = _tdd_writer_repo("rv", (_wf_gate(),))
    _signal_next(M, root, mpath)
    code, line = _writer_round(M, root, mpath, bindir, log, "0.31",
                               edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                               result=_WF_CLAIM)
    return root, mpath, line


def _skill_flags(argv):
    """Every value that follows a `--skill` in `argv`, in order."""
    argv = list(argv or [])
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--skill"]


def _session_skill_cases(check):
    """The drive hands the task's resolved skills to the session runner, for the
    writer and for the reviewer alike, and to neither when the task resolves none.
    The skills are project skills committed into the fixture, because the stub
    session is the real runner and a name it cannot find refuses to start."""
    M, why = _load("drive_phase_session_skills")
    if M is None:
        check("sk1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-sk-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    named = ["alpha-house", "beta-house"]
    root, mpath = _tdd_writer_repo("sk", (_wf_gate(),), skills=named)
    for name in named:
        folder = os.path.join(root, ".claude", "skills", name)
        os.makedirs(folder)
        _write_lf(os.path.join(folder, "SKILL.md"),
                  "---\nname: %s\n---\nbody of %s\n" % (name, name))
    for argv in (["add", "-A"], ["commit", "-qm", "the task's skills"]):
        _harness.git(root, *argv)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    wargv = _run_argv(block) or []
    _writer_round(M, root, mpath, bindir, log, "0.31",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, result=_WF_CLAIM)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    rargv = _run_argv(block) or []
    check("sk1 the writer's printed command carries one --skill per skill the task "
          "resolves to, in order: %r" % ((wargv,),),
          _flag(wargv, "--role") == "writer" and _skill_flags(wargv) == named)
    check("sk2 ...and the reviewer's carries the same, beside its own role: %r"
          % ((rargv,),),
          _flag(rargv, "--role") == "reviewer" and _skill_flags(rargv) == named)
    root, mpath = _tdd_writer_repo("sk0", (_wf_gate(),))
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    bare = _run_argv(block) or []
    check("sk3 a task that resolves no skill gets no --skill at all - the flag is not "
          "added with an empty name: %r" % ((bare,),),
          _flag(bare, "--role") == "writer" and "--skill" not in bare)


def _reviewer_session_cases(check):
    """With a writer session set, the per-task reviewer is a headless session the
    main loop runs through `run-agent-session.py --role reviewer`, and the drive
    files its return from the session's last message only when the saved stream
    shows a tool call: a stream with none is recorded cannot-tell on the task and
    the reviewer is dispatched once more, a second such stream stops with a note,
    and a session that read files is accepted."""
    M, why = _load("drive_phase_reviewer_session")
    if M is None:
        check("rv1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-rv-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")

    root, mpath, line = _reviewer_dispatch(M, bindir, log)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    first = _run_argv(block) or []
    check("rv1 the reviewer's dispatch names run-agent-session.py with the reviewer "
          "role, the task and a full model id, and names no reviewer agent: %r"
          % ((line, first),),
          "run-agent-session.py --role reviewer" in line
          and "audit-reviewer" not in line + block
          and _flag(first, "--role") == "reviewer" and _flag(first, "--task") == "P1.1"
          and (_flag(first, "--model") or "").startswith("claude-"))
    _play_session(root, first, bindir, log, "0.21", session=RV_SESSIONS[0],
                  result=_review_json(mpath), tools=0)
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    second = _run_argv(block) or []
    notes = [n for n in _notes(mpath, "P1.1") if RV_SESSIONS[0] in n]
    check("rv2 a reviewer session whose stream holds no tool call is recorded "
          "cannot-tell on the task, files no return, and the reviewer is "
          "dispatched once more on a record of its own: %r"
          % ((code, line, notes, second),),
          code == 0 and "run-agent-session.py --role reviewer" in line
          and len(notes) >= 1 and any("cannot-tell" in n for n in notes)
          and _filed_path(mpath, "P1.1", "reviewer") is not None
          and not os.path.exists(_filed_path(mpath, "P1.1", "reviewer"))
          and _flag(second, "--record") not in (None, _flag(first, "--record")))
    _play_session(root, second, bindir, log, "0.22", session=RV_SESSIONS[1],
                  result=_review_json(mpath), tools=0)
    code, line = _signal_next(M, root, mpath)
    again, full = _next(M, root, mpath)
    check("rv3 a second zero-tool reviewer session stops with a note naming both "
          "sessions instead of a third dispatch, and files nothing: %r"
          % ((code, line, full),),
          code == 1 and "run-agent-session.py --role reviewer" not in line
          and all(s in "\n".join(_notes(mpath, "P1.1")) for s in RV_SESSIONS[:2])
          and "no third dispatch" in full
          and all(s in full for s in RV_SESSIONS[:2])
          and not os.path.exists(_filed_path(mpath, "P1.1", "reviewer")))
    check("rv4 the stop is repeated, not dispatched past, by a later next: %r"
          % ((again, full[:200]),),
          again == 1 and "run-agent-session.py --role reviewer" not in full
          and len([n for n in _notes(mpath, "P1.1") if "cannot-tell" in n]) == 2)

    root2, mpath2, _line = _reviewer_dispatch(M, bindir, log)
    _c, block2 = _explain_of(M, root2, mpath2, "P1.1")
    _play_session(root2, _run_argv(block2) or [], bindir, log, "0.23",
                  session=RV_SESSIONS[2], result=_review_json(mpath2), tools=3)
    code2, line2 = _signal_next(M, root2, mpath2)
    body = json.loads(_read(_filed_path(mpath2, "P1.1", "reviewer")).decode("utf-8")) \
        if os.path.exists(_filed_path(mpath2, "P1.1", "reviewer")) else {}
    task = tasks_of(mpath2).get("P1.1") or {}
    check("rv5 THE TWIN: a reviewer session whose stream holds tool calls is "
          "accepted as before - the drive files its last message as the "
          "reviewer's return and goes on, with no cannot-tell note: %r"
          % ((code2, line2, body.get("verdict"), task.get("status")),),
          code2 == 0 and body.get("verdict") == "clean"
          and "run-agent-session.py --role reviewer" not in line2
          and not [n for n in _notes(mpath2, "P1.1") if "cannot-tell" in n])
    off_root, off_mpath = _repo("rv-off", task_ids=TASKS[:1])
    _signal_next(M, off_root, off_mpath)
    _file_executor(off_root, off_mpath, "P1.1")
    code3, line3 = _signal_next(M, off_root, off_mpath)
    check("rv6 THE ROLLBACK TWIN: with no writer session the reviewer is still the "
          "Agent, and names no session runner: %r" % ((code3, line3),),
          M.REVIEWER_AGENT in line3 and "run-agent-session.py" not in line3)


# --- a phase-review finding blocks only once a second pass confirms it ---------
# The validation sessions' ids, and the suite a fix round leaves: v three, its
# new case red on the v-two code the task's first commit holds.
PV_SESSIONS = ("22222222-3333-4444-8555-666666666661",
               "22222222-3333-4444-8555-666666666662",
               "22222222-3333-4444-8555-666666666663")
_PV_THREE_TEST = _wf_suite([("old1", "mine.v >= 1"), ("new3", "mine.v == 3")])
# Each issue opens with a tag the cases find the finding's id by. Two cite the
# line the task's commit wrote; the third cites a fixture file no task touched.
_PV_FINDINGS = (
    {"severity": "med", "file": "src/mine.py:1",
     "issue": "pv-withdrawn: v is assigned with no guard",
     "resolution": "guard the assignment"},
    {"severity": "high", "file": "src/mine.py:1",
     "issue": "pv-confirmed: the phase asked for v three and the code sets two",
     "resolution": "set v to three"},
    {"severity": "med", "file": "src/f2.txt:1",
     "issue": "pv-outside: src/f2.txt still reads v0",
     "resolution": "change src/f2.txt"},
    {"severity": "low", "file": "src/mine.py:1",
     "issue": "pv-low: the name v says little",
     "resolution": "rename v"})
# A tdd task's red-first is the helper's block, which the phase reviewer
# answers as it reads.
_PV_ENTRY = {"P1.1": {"redFirst": "proved",
                      "redFirstBasis": "the red-first helper's block"}}


def _pv_findings(mpath):
    """`{issue tag: finding}` of the phase review's recorded findings."""
    phase = [p for p in _mio.load_manifest(mpath).get("phases") or []
             if p.get("id") == PHASE][0]
    return dict(((f.get("issue") or "").split(":", 1)[0], f)
                for f in (phase.get("review") or {}).get("findings") or []
                if isinstance(f, dict))


def _pv_phase(mpath):
    return [p for p in _mio.load_manifest(mpath).get("phases") or []
            if p.get("id") == PHASE][0]


def _pv_verdicts(verdicts):
    """The last message of a validation session: a sentence, then one object
    with a verdict for each `(finding id, verdict, kind[, basis])`."""
    return "Each cited line re-read.\n%s" % (json.dumps({"findings": [
        {"id": row[0], "verdict": row[1], "kind": row[2],
         "basis": row[3] if len(row) > 3 else "src/mine.py:1 read at HEAD"}
        for row in verdicts]}),)


_PV_PRE_PHASE = "src/f2.txt:1 is pre-existing, outside the phase diff"


def _prompt_text(argv):
    prompt = _flag(argv, "--prompt-file")
    return (_read(prompt).decode("utf-8", "replace")
            if prompt and os.path.isfile(prompt) else "")


def _pv_to_review(M, root, mpath, bindir, log):
    """Run the task's writer session to the task's close: `(stream, code, line,
    block)` - the writer's saved stream and the step after it, the phase
    review's dispatch, whose `--explain` block names the brief."""
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    _ran, said = _play_session(root, _run_argv(block) or [], bindir, log, "0.31",
                               edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST},
                               result=_WF_CLAIM)
    code, line = _signal_next(M, root, mpath)
    _c, review = _explain_of(M, root, mpath, PHASE)
    return (_streams(said) or [None])[0], code, line, review


def _pv_fix_round(M, root, mpath, bindir, log, cost):
    """Run the writer dispatch now printed for P1.1 as a fix round - v three, a
    case red on v two - and take the step after it: `(code, line, block)`, the
    block the phase's `--explain` prints then."""
    _c, block = _explain_of(M, root, mpath, "P1.1")
    _play_session(root, _run_argv(block) or [], bindir, log, cost,
                  edit={_WF_SRC: "v = 3\n", _WF_TEST: _PV_THREE_TEST},
                  result=_WF_CLAIM)
    code, line = _signal_next(M, root, mpath)
    _c, after = _explain_of(M, root, mpath, PHASE)
    return code, line, after


def _phase_validation_cases(check):
    """Under a writer session a phase review's finding blocks only once a second
    reviewer pass re-reads the cited code and confirms it as a correctness or
    requirement finding; a low one and one the pass withdraws - the one citing
    pre-phase code among them - are notes on the phase. A confirmed finding goes
    back to the writer session of the task whose diff holds the cited lines -
    resumed while its last activity is under an hour - is fixed only once the
    pass re-reads it at the fix and withdraws it, and no fix task is added."""
    M, why = _load("drive_phase_validation")
    if M is None:
        check("pv1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-pv-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("pv-warm", (_wf_gate(),), per_task="phase")
    _stream, code, line, review = _pv_to_review(M, root, mpath, bindir, log)
    filed_code, filed_text = _file_phase_review(root, mpath, review, _PV_FINDINGS,
                                                _PV_ENTRY)
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, PHASE)
    vargv = _run_argv(block) or []
    vprompt = _prompt_text(vargv)
    ids = dict((tag, f.get("id")) for tag, f in _pv_findings(mpath).items())
    check("pv1 the phase review's findings go to a second reviewer pass first: a "
          "reviewer session for the phase whose prompt names every med-or-worse "
          "finding - the one citing a file no task changed included, since the "
          "drive failing to place a finding is no evidence it does not block - "
          "and not the low one: %r"
          % ((filed_code, filed_text[-200:], code, line, ids, vargv),),
          filed_code == 0 and code == 0 and len(ids) == 4
          and "run-agent-session.py --role reviewer" in line
          and _flag(vargv, "--role") == "reviewer"
          and _flag(vargv, "--task") == PHASE and "--resume" not in vargv
          and ids["pv-withdrawn"] in vprompt and ids["pv-confirmed"] in vprompt
          and ids["pv-outside"] in vprompt and "pv-low" not in vprompt)
    commit_1 = tasks_of(mpath)["P1.1"].get("commit") or "no commit"
    check("pv1b the validation prompt gives the pass what it judges 'this phase's "
          "work wrote it' by: the phase's base commit (or that none is recorded) "
          "and each task's own commit: %r"
          % ([ln for ln in vprompt.splitlines() if "commit" in ln or "base" in ln],),
          "phase base:" in vprompt and ("P1.1 %s" % (commit_1,)) in vprompt)
    _play_session(root, vargv, bindir, log, "0.12", session=PV_SESSIONS[0],
                  result=_pv_verdicts([(ids["pv-withdrawn"], "withdrawn",
                                        "correctness"),
                                       (ids["pv-confirmed"], "confirmed",
                                        "requirement"),
                                       (ids["pv-outside"], "withdrawn",
                                        "other", _PV_PRE_PHASE)]),
                  reads=["src/mine.py", "src/f2.txt"])
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    wargv = _run_argv(block) or []
    wprompt = _prompt_text(wargv)
    tasks = tasks_of(mpath)
    check("pv2 a confirmed finding resumes the session of the task whose diff "
          "holds the cited lines while its last activity is under an hour: "
          "P1.1 runs again with --resume on its own writer session, prompted with "
          "the confirmed finding and neither the withdrawn one nor the one "
          "outside the diff, and no fix task is added: %r"
          % ((code, line, wargv, sorted(tasks)),),
          code == 0 and "run-agent-session.py --role writer" in line
          and _flag(wargv, "--resume") == WRITER_SESSION
          and _flag(wargv, "--task") == "P1.1"
          and "pv-confirmed" in wprompt and "pv-withdrawn" not in wprompt
          and "pv-outside" not in wprompt
          and sorted(tasks) == ["P1.1"]
          and tasks["P1.1"].get("status") == "in_progress")
    # The re-open cleared P1.1's `commit`; the commit it carried is read off
    # the journal's task.reopen row, so no drive state is consulted at all.
    phase_now = _pv_phase(mpath)
    record = M.reopen_record({"project": root, "gitRoot": root}, phase_now)
    owners = (M.finding_owners({"project": root, "gitRoot": root}, record[0],
                               {"file": "src/mine.py:1"})
              if record[0] is not None else (None, "no record"))
    bare = M.finding_owners({"project": root, "gitRoot": root},
                            M.task_commits(phase_now, {}),
                            {"file": "src/mine.py:1"})
    check("pv9 the commit a re-opened task carried is attributed from the "
          "journal's re-open row with no drive state at all, and P1.1 still "
          "owns the line its old commit wrote - which the task records alone, "
          "its commit cleared, no longer say: %r" % ((record, owners, bare),),
          record[0] is not None and owners == (["P1.1"], None)
          and bare == ([], None) and tasks_of(mpath)["P1.1"].get("commit") is None)
    code, line, review2 = _pv_fix_round(M, root, mpath, bindir, log, "0.33")
    second = _file_phase_review(root, mpath, review2, (), _PV_ENTRY)
    # Every verdict was given at the head before the fix: the code each cites
    # moved since, so the pass is asked again - the handed-back one included,
    # which is fixed only once the pass re-reads it and withdraws it.
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, PHASE)
    vargv2 = _run_argv(block) or []
    _play_session(root, vargv2, bindir, log, "0.13", session=PV_SESSIONS[1],
                  result=_pv_verdicts([
                      (ids["pv-withdrawn"], "withdrawn", "correctness"),
                      (ids["pv-confirmed"], "withdrawn", "requirement",
                       "src/mine.py:1 now sets v to three"),
                      (ids["pv-outside"], "withdrawn", "other", _PV_PRE_PHASE)]),
                  reads=["src/mine.py", "src/f2.txt"])
    code, line = _signal_next(M, root, mpath)
    triage_line = line
    signed, said = _signal_next(M, root, mpath, "--answer", "sign-off",
                                "--reason", SUMMARY)
    if " gate-coverage:" in said:
        # This fixture's phase gate names no path of the work, which a human
        # accepts once; the notes are recorded by the sign-off verb after it.
        signed, said = _signal_next(M, root, mpath, "--answer", "accept",
                                    "--reason", "the fixture's gate is the suite")
    found = _pv_findings(mpath)
    phase = _pv_phase(mpath)
    check("pv3 a finding is a note only on positive evidence - withdrawn by the "
          "pass, the pre-phase one among them, or low - and none blocks: after "
          "the fix round the pass re-checks the handed-back finding too, the "
          "drive reaches the triage and signs off, each note recorded on the "
          "phase with a reason saying why, the re-checked one fixed by P1.1's "
          "own new commit, and still no fix task: %r"
          % ((second[0], _prompt_text(vargv2)[:200], triage_line, signed, said,
              found, (phase.get("review") or {}).get("status")),),
          second[0] == 0 and "pv-withdrawn" in _prompt_text(vargv2)
          and "pv-confirmed" in _prompt_text(vargv2)
          and "triage:" in triage_line and signed == 0
          and (phase.get("review") or {}).get("status") == "passed"
          and found["pv-withdrawn"].get("status") == "accepted-open"
          and "note" in (found["pv-withdrawn"].get("acceptedReason") or "")
          and "withdr" in (found["pv-withdrawn"].get("acceptedReason") or "")
          and found["pv-outside"].get("status") == "accepted-open"
          and "note" in (found["pv-outside"].get("acceptedReason") or "")
          and "phase diff" in (found["pv-outside"].get("acceptedReason") or "")
          and found["pv-low"].get("status") == "accepted-open"
          and "note" in (found["pv-low"].get("acceptedReason") or "")
          and "low" in (found["pv-low"].get("acceptedReason") or "")
          and found["pv-confirmed"].get("status") == "fixed"
          and found["pv-confirmed"].get("fixTask") == "P1.1"
          and sorted(tasks_of(mpath)) == ["P1.1"])
    # A triage showing notes stands on the HEAD they were sorted at: the
    # decision is read only while HEAD is still that commit.
    here = _head_of(root)
    shown = {"decision": "triage", "task": None, "findings": [],
             "noted": [{"id": "P1-R1", "why": "withdrawn"}]}
    plan = _mio.load_manifest(mpath)
    holds = [M.pending_still_applies({"gitRoot": root}, plan,
                                     dict(shown, notedHead=head))
             for head in (here, "0" * 40)]
    bare = M.pending_still_applies({"gitRoot": root}, plan, dict(
        shown, noted=[], notedHead="0" * 40))
    check("pv6 a triage showing notes still applies while HEAD is the commit "
          "they were sorted at and no longer once HEAD moved, and a triage "
          "holding no note is not held to any HEAD (the over-fire twin): %r"
          % ((here, holds, bare),),
          len(here) == 40 and holds == [True, False] and bare is True)


def _phase_cold_cases(check):
    """A confirmed finding on a session idle past the cache's hour starts a
    fresh writer session with the task text and the findings, and an open
    finding after `review.maxRounds` rounds stops the phase with a note - no
    fix task in either."""
    M, why = _load("drive_phase_validation_cold")
    if M is None:
        check("pv4 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-pv4-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _tdd_writer_repo("pv-cold", (_wf_gate(),), per_task="phase",
                                   review={"maxRounds": 2})
    stream, code, line, review = _pv_to_review(M, root, mpath, bindir, log)
    _file_phase_review(root, mpath, review, _PV_FINDINGS[1:2], _PV_ENTRY)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, PHASE)
    confirmed = _pv_findings(mpath)["pv-confirmed"].get("id")
    _play_session(root, _run_argv(block) or [], bindir, log, "0.14",
                  session=PV_SESSIONS[2],
                  result=_pv_verdicts([(confirmed, "confirmed", "correctness")]),
                  tools=1)
    # The writer's last activity, put two hours back: past the cache's life.
    aged = time.time() - 2 * 3600
    if stream and os.path.isfile(stream):
        os.utime(stream, (aged, aged))
    code, line = _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    wargv = _run_argv(block) or []
    wprompt = _prompt_text(wargv)
    described = tasks_of(mpath)["P1.1"].get("description") or "?"
    check("pv4 a confirmed finding whose writer session was last active over an "
          "hour ago starts a fresh writer session for that task, resuming "
          "nothing, given the task text and the finding, and no fix task is "
          "added: %r" % ((stream, code, line, wargv, wprompt[:300]),),
          stream is not None and code == 0
          and "run-agent-session.py --role writer" in line
          and "--resume" not in wargv and _flag(wargv, "--task") == "P1.1"
          and described in wprompt and "pv-confirmed" in wprompt
          and sorted(tasks_of(mpath)) == ["P1.1"])
    code, line, review2 = _pv_fix_round(M, root, mpath, bindir, log, "0.35")
    still = {"severity": "med", "file": "src/mine.py:1",
             "issue": "pv-still: three is not bounded either",
             "resolution": "bound v"}
    _file_phase_review(root, mpath, review2, [still], _PV_ENTRY)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, PHASE)
    open_id = _pv_findings(mpath)["pv-still"].get("id")
    recheck = _prompt_text(_run_argv(block) or [])
    # The handed-back finding is re-checked against the fix's commit, and the
    # pass finds it still there: a new commit alone fixes nothing.
    _play_session(root, _run_argv(block) or [], bindir, log, "0.15",
                  session=PV_SESSIONS[0],
                  result=_pv_verdicts([(open_id, "confirmed", "correctness"),
                                       (confirmed, "confirmed", "correctness")]),
                  tools=1)
    code, text = _next(M, root, mpath)
    again, text2 = _next(M, root, mpath)
    phase = _pv_phase(mpath)
    noted = [n for n in _notes(mpath, "P1.1") if open_id and open_id in n]
    check("pv5 after the last round an open confirmed finding stops the phase - "
          "never a silent pass, never a third round - with a note naming it on "
          "the task whose lines it cites, and no fix task; the handed-back "
          "finding the pass re-checked and confirmed is not marked fixed by the "
          "task's new commit and is named in the stop; a later next stops the "
          "same way and runs no session: %r"
          % ((code, text[-400:], again, noted,
              (phase.get("review") or {}).get("status"),
              _pv_findings(mpath)["pv-confirmed"].get("status")),),
          code == 1 and open_id is not None and open_id in text
          and confirmed in recheck and confirmed in text
          and _pv_findings(mpath)["pv-confirmed"].get("status") != "fixed"
          and "maxRounds" in text
          and (phase.get("review") or {}).get("status") not in ("passed",
                                                                 "skipped")
          and len(noted) == 1 and sorted(tasks_of(mpath)) == ["P1.1"]
          and again == 1 and open_id in text2
          and "run-agent-session.py" not in text2)


def _pv_blame_repo():
    """`(root, {sha: task id})` - a repository where P1.1 writes x.py with its
    defect on line 5, P1.2 then deletes x.py's first two lines and y.py's third,
    and P1.3 deletes gone.py: the coordinates each task's own diff shows are no
    longer HEAD's."""
    root = os.path.realpath(_harness.fixture_root("drive-pv-blame-"))
    _harness.git(root, "init", "-q")
    with open(os.path.join(root, ".git", "config"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_FIXTURE_IDENTITY)

    def commit(files, gone=(), message="work"):
        for rel, text in sorted(files.items()):
            _write_lf(os.path.join(root, rel), text)
        for rel in gone:
            os.remove(os.path.join(root, rel))
        _harness.git(root, "add", "-A")
        _harness.git(root, "commit", "-qm", message)
        return _head_of(root)
    commit({"gone.py": "a\nb\nc\n", "y.py": "a\nb\nc\nd\n"}, message="base")
    one = commit({"x.py": "l1\nl2\nl3\nl4\nbug = 1\nl6\n"})
    two = commit({"x.py": "l3\nl4\nbug = 1\nl6\n", "y.py": "a\nb\nd\n"})
    three = commit({}, gone=("gone.py",))
    return root, {one: "P1.1", two: "P1.2", three: "P1.3"}


def _pv_unit_cases(check):
    """The rule a finding is sorted by, case by case: it is placed by each
    task's own diff in the coordinates the brief showed, in every common cite
    spelling; a finding the drive cannot place is validated, never noted; a
    re-open is recorded only once the verb took it, and re-opens every task a
    finding spans; and a validation answer naming a finding twice is refused."""
    M, why = _load("drive_phase_validation_unit")
    if M is None:
        check("pv7 the driver loads", False, why)
        return
    root, commits = _pv_blame_repo()
    ctx = {"project": root, "gitRoot": root}
    cites = {"x.py:5": ["P1.1"], "x.py#L5": ["P1.1"], "x.py:L5": ["P1.1"],
             "x.py line 5": ["P1.1"], "x.py lines 5-6": ["P1.1"],
             "y.py:3": ["P1.2"], "gone.py:2": ["P1.3"], "x.py": []}
    got = dict((cite, M.finding_owners(ctx, commits, {"file": cite}))
               for cite in cites)
    check("pv7 a finding is placed by the task whose own diff the brief showed "
          "the cited line in, in that diff's coordinates: the defect P1.1 wrote "
          "at x.py:5 is P1.1's though P1.2 shifted it off line 5 at HEAD, in "
          "each spelling (#L5, :L5, line 5, lines 5-6); a deleted line is the "
          "deleting task's and so is a deleted file's; a cite with no line is "
          "placed nowhere: %r" % (got,),
          all(got[cite] == (want, None) for cite, want in cites.items()))
    head = _head_of(root)
    tasks = [{"id": tid, "status": "done", "commit": sha}
             for sha, tid in sorted(commits.items(), key=lambda kv: kv[1])]
    findings = [
        {"id": "P1-R1", "severity": "high", "file": "x.py", "issue": "i",
         "resolution": "r"},
        {"id": "P1-R2", "severity": "high", "file": "elsewhere.py:1", "issue": "i",
         "resolution": "r"},
        {"id": "P1-R3", "severity": "med", "file": "elsewhere.py:1", "issue": "i",
         "resolution": "r"},
        {"id": "P1-R4", "severity": "low", "file": "x.py:5", "issue": "i",
         "resolution": "r"},
        {"id": "P1-R5", "severity": "med", "file": "x.py:5", "issue": "i",
         "resolution": "r"}]
    phase = {"id": PHASE, "tasks": tasks, "review": {"findings": findings}}
    state = {M.VERDICTS_FIELD: {
        "P1-R2": {"verdict": "confirmed", "kind": "correctness", "basis": "b",
                  "head": head},
        "P1-R3": {"verdict": "withdrawn", "kind": None, "basis": "b", "head": head},
        "P1-R5": {"verdict": "confirmed", "kind": "requirement", "basis": "b",
                  "head": head}}}
    sorted_, why = M.sort_findings(ctx, state, phase, head, (commits, {}))
    shape = (why, sorted((sorted_ or {}).get("notes") or {}),
             [f["id"] for f in (sorted_ or {}).get("candidates") or []],
             [f["id"] for f in (sorted_ or {}).get("unowned") or []],
             [(f["id"], o) for f, o in (sorted_ or {}).get("blocking") or []])
    check("pv8 a finding is a note only on positive evidence: the low one and the "
          "one the pass withdrew are notes; one the drive cannot place and no pass "
          "has judged goes to the pass; one the pass confirmed that no task's "
          "diff holds is held for a human, never a note; one confirmed in P1.1's "
          "lines blocks there: %r" % (shape,),
          shape == (None, ["P1-R3", "P1-R4"], ["P1-R1"], ["P1-R2"],
                    [("P1-R5", ["P1.1"])]))
    calls = []

    def refused(_ctx, script, args, flag, text):
        calls.append(args[1])
        return None, (1, "[audit-task] refused")
    M._verb_with_text = refused
    held = {}
    plan_ctx = dict(ctx, phase=PHASE, manifest=os.path.join(root, "plan.json"),
                    did=[], stateDir=os.path.join(root, "drive-state"))
    stop = M.hand_back(plan_ctx, held, phase, head, [(findings[4], ["P1.1"])])
    check("pv10 a re-open the verb refuses leaves no hand-back on record, so no "
          "later step reads a hand-back that never happened: %r" % ((stop, held),),
          stop is not None and stop[0] != 0 and calls == ["P1.1"]
          and not held.get(M.REVIEW_FIX_FIELD))

    def took(_ctx, script, args, flag, text):
        calls.append(args[1])
        return "re-opened", None
    M._verb_with_text = took
    del calls[:]
    held = {}
    stop = M.hand_back(plan_ctx, held, phase, head,
                       [(findings[4], ["P1.1", "P1.2"])])
    check("pv12 a confirmed finding spanning two tasks' diffs re-opens each of "
          "them, and the verb's yes is what records each hand-back (the twin of "
          "pv10): %r" % ((stop, calls, sorted(held.get(M.REVIEW_FIX_FIELD) or {})),),
          stop is None and calls == ["P1.1", "P1.2"]
          and sorted(held.get(M.REVIEW_FIX_FIELD) or {}) == ["P1.1", "P1.2"])
    twice = M.read_verdicts({"findings": [
        {"id": "P1-R1", "verdict": "withdrawn", "kind": "other", "basis": "b"},
        {"id": "P1-R1", "verdict": "confirmed", "kind": "correctness",
         "basis": "b"}]}, ["P1-R1"])
    once = M.read_verdicts({"findings": [
        {"id": "P1-R1", "verdict": "withdrawn", "kind": "other", "basis": "b"}]},
        ["P1-R1"])
    check("pv11 a validation answer naming one finding twice is refused - never "
          "the last entry winning - and one naming it once is read: %r"
          % ((twice, once),),
          twice[1] != [] and any("P1-R1" in p for p in twice[1])
          and once[1] == [] and once[0]["P1-R1"]["verdict"] == "withdrawn")
    high = dict(findings[0], file="x.py:5", severity="high")
    runs = dict((name, _pv_validation_run(M, root, head, phase, high, reads, answer))
                for name, reads, answer in (
                    ("unrelated", ["y.py"], ("withdrawn", "other")),
                    ("unrelated-other", ["y.py"], ("confirmed", "other")),
                    ("cited", [os.path.join(root, "x.py")], ("withdrawn", "other")),
                    ("confirmed", ["y.py"], ("confirmed", "correctness"))))
    shape = dict((name, (r[0], (r[1] or (None, ""))[0], r[2]))
                 for name, r in runs.items())
    low = dict(high, severity="low")
    check("pv13 a pass's withdrawal - or its `other` - of a med-or-worse finding "
          "counts only when its stream read a file that finding cites: one that "
          "read only an unrelated file is not taken (the drive stops, nothing "
          "held, never a note), one that read the cited file is (an absolute "
          "path reads as the project's own), a confirmation of a blocking kind "
          "needs no read (the over-fire twin), and a low finding needs none "
          "either: %r" % ((shape, M.unread_demotions(
              [low], {low["id"]: {"verdict": "withdrawn"}}, set())),),
          shape["unrelated"][:3] == (None, 1, None)
          and high["id"] in str(runs["unrelated"][1])
          and shape["unrelated-other"][:3] == (None, 1, None)
          and shape["cited"] == (True, None, "withdrawn")
          and shape["confirmed"] == (True, None, "confirmed")
          and M.unread_demotions([low], {low["id"]: {"verdict": "withdrawn"}},
                                 set()) == [])
    open_one = {"id": PHASE, "tasks": [], "review": {"findings": [
        {"id": "P1-R9", "severity": "med", "file": "x.py:5", "issue": "i",
         "resolution": "r"}]}}
    stale = {M.NOTED_FIELD: {"head": head, "notes": {"P1-R9": "withdrawn"}}}
    off = M.noted_now({"gitRoot": root, "config": {}}, stale, open_one, head)
    on = M.noted_now({"gitRoot": root, "config": {"executor": WRITER_EXECUTOR}},
                     stale, open_one, head)
    check("pv15 a note an earlier writer-session run left in the drive's state is "
          "not honoured once executor.writerModel is unset - the finding is "
          "offered as before - and is while it is set (the twin): %r" % ((off, on),),
          off == {} and on == {"P1-R9": "withdrawn"})


def _pv_validation_run(M, root, head, phase, finding, reads, answer):
    """`validation_step` over one finding, its session already run: a record
    and a saved stream made here - one Read of each of `reads`, and a last
    message answering `answer` `(verdict, kind)`. Returns `(done, said,
    verdict held)`."""
    where = os.path.realpath(_harness.fixture_root("drive-pv-vrun-"))
    stream = os.path.join(where, "stream.jsonl")
    body = json.dumps({"findings": [{"id": finding["id"], "verdict": answer[0],
                                     "kind": answer[1], "basis": "read"}]})
    with open(stream, "w", encoding="utf-8") as fh:
        for event in ({"type": "assistant", "message": {"content": [
                          {"type": "tool_use", "id": "t%d" % n, "name": "Read",
                           "input": {"file_path": path}}
                          for n, path in enumerate(reads)]}},
                      {"type": "result", "result": body}):
            fh.write(json.dumps(event) + "\n")
    record = os.path.join(where, "record.jsonl")
    with open(record, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"exit": 0, "line": (
            "session=%s subtype=success is_error=false total_cost_usd=0.01 "
            "exit=0 stream=%s" % (PV_SESSIONS[0], stream))}) + "\n")
    state = {}
    node = M.validation_node(phase, head)
    M._mark(state, M.VALIDATE_KEY, node, {
        "seq": 1, "asked": [finding["id"]],
        "dispatches": [{"seq": 0, "round": 0, "record": record, "argv": []}]})
    ctx = {"project": root, "gitRoot": root, "phase": PHASE, "did": [],
           "stateDir": os.path.join(where, "state")}
    done, said = M.validation_step(ctx, state, phase, head, [finding])
    held = (state.get(M.VERDICTS_FIELD) or {}).get(finding["id"]) or {}
    return done, said, held.get("verdict")


# --- a task the phase review handed back is judged on its own work -------------
# A file only the task's FIRST commit writes: a clause cited to it is delivered
# by that commit, and the fix round that follows a hand-back never touches it.
_RW_NOTES = "src/notes.txt"
_RW_FINDING = ({"severity": "high", "file": "src/mine.py:1",
                "issue": "rw-confirmed: the phase asked for v three and the code "
                         "sets two",
                "resolution": "set v to three"},)
# A gate command red while `bad.flag` exists, so a fix round can leave the
# proof standing and the gate red - the decision that offers a retry.
_RW_FLAG_GATE = ('"%s" -c "import os, sys; sys.exit(1 if os.path.exists('
                 '\'bad.flag\') else 0)"' % (sys.executable.replace("\\", "/"),))


def _rw_answer(cites):
    """A writer's last message: a sentence, then one delivered answer per
    clause, `cites` mapping each clause number to the file it is cited to."""
    return "Done.\n%s" % (json.dumps(dict(
        (str(n), {"delivered": True, "file": path, "line": 1})
        for n, path in sorted(cites.items())), sort_keys=True),)


def _rw_handed_back(M, prefix, gate, bindir, log):
    """A writer task over `src/mine.py`, its suite and `src/notes.txt`, whose
    first session writes all three and cites clause 2 to the notes; the phase
    review files one high finding on `src/mine.py:1`, the validation pass
    confirms it, and the next step hands it back. Returns `(root, mpath,
    finding id, the task's first commit, (code, line) of the hand-back step)`."""
    root, mpath = _tdd_writer_repo(prefix, gate, _WC_DESCRIPTION, per_task="phase")
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["phases"][0]["tasks"][0]["files"].append(_RW_NOTES)
    plan["fileIndex"][_RW_NOTES] = ["P1.1"]
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _write_lf(os.path.join(root, *_RW_NOTES.split("/")), "v0\n")
    for argv in (["add", "-A"], ["commit", "-qm", "the notes the task owns"]):
        _harness.git(root, *argv)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, "P1.1")
    _play_session(root, _run_argv(block) or [], bindir, log, "0.61",
                  edit={_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST,
                        _RW_NOTES: "v is two\n"},
                  result=_rw_answer({1: _WF_SRC, 2: _RW_NOTES, 3: _WF_SRC}))
    _signal_next(M, root, mpath)
    _c, review = _explain_of(M, root, mpath, PHASE)
    first = tasks_of(mpath)["P1.1"].get("commit")
    _file_phase_review(root, mpath, review, _RW_FINDING, _PV_ENTRY)
    _signal_next(M, root, mpath)
    _c, block = _explain_of(M, root, mpath, PHASE)
    fid = (_pv_findings(mpath).get("rw-confirmed") or {}).get("id")
    _play_session(root, _run_argv(block) or [], bindir, log, "0.62",
                  session=PV_SESSIONS[0],
                  result=_pv_verdicts([(fid, "confirmed", "requirement")]),
                  reads=["src/mine.py"])
    return root, mpath, fid, first, _signal_next(M, root, mpath)


def _rw_unreachable_commit(root, rel, text):
    """A commit of HEAD's tree plus `rel` holding `text`, whose parent is HEAD
    and which no ref names - a commit reset out of history - made without
    touching the work tree or the index. Its sha."""
    blob_src = os.path.join(_harness.fixture_root("drive-rw-blob-"), "blob")
    _write_lf(blob_src, text)
    blob = _harness.git(root, "hash-object", "-w", blob_src).strip()
    index = os.path.join(os.path.dirname(blob_src), "index")

    def run(*argv):
        done = subprocess.run(_GIT + ["-C", root] + list(argv), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, GIT_INDEX_FILE=index), timeout=60)
        if done.returncode != 0:
            raise RuntimeError("%r: %s" % (argv, done.stderr))
        return done.stdout.strip()
    run("read-tree", "HEAD")
    run("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, rel))
    written = run("write-tree")
    return run("commit-tree", written, "-p", "HEAD", "-m", "reset out of history")


def _reopened_writer_cases(check):
    """A task the phase review handed back is judged on its own work: a clause
    its first commit delivered still counts once the fix round leaves that file
    alone, a dispatch after the first fix dispatch still carries the confirmed
    findings, and closing the task under a task-scoped drive keeps the
    hand-back's record and the writer's session for the next hand-back."""
    M, why = _load("drive_phase_reopened_writer")
    if M is None:
        check("rw1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-rw-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath, fid, first, handed = _rw_handed_back(
        M, "rw-clause", (_wf_gate(),), bindir, log)
    # Besides the commit the hand-back cleared, the record names one commit a
    # reset took out of HEAD's history - the only one that wrote src/side.txt -
    # and one sha git does not know at all.
    gone = _rw_unreachable_commit(root, "src/side.txt", "only the reset commit\n")
    unknown = "f" * 40
    real_record = M.reopen_record

    def record_with_strays(ctx, phase):
        carried, handed_ids, why_r = real_record(ctx, phase)
        if carried is None:
            return carried, handed_ids, why_r
        return dict(carried, **{gone: "P1.1", unknown: "P1.1"}), handed_ids, why_r
    M.reopen_record = record_with_strays
    try:
        _reopened_clause_steps(check, M, root, mpath, bindir, log,
                               (fid, first, handed, gone, unknown))
    finally:
        M.reopen_record = real_record
    _reopened_retry_cases(check, M, bindir, log)
    _reopened_finish_cases(check, M)
    _review_fix_bound_cases(check, M)


def _reopened_clause_steps(check, M, root, mpath, bindir, log, held):
    """The fix rounds of a handed-back task whose re-open record also names a
    commit out of HEAD's history and an unknown sha (`held`)."""
    fid, first, handed, gone, unknown = held
    fix = {_WF_SRC: "v = 3\n", _WF_TEST: _PV_THREE_TEST}
    _c, untouched = _writer_round(M, root, mpath, bindir, log, "0.63", edit=fix,
                                  result=_rw_answer({1: _WF_SRC, 2: "src/f2.txt",
                                                     3: _WF_SRC}))
    _c, untouched_block = _explain_of(M, root, mpath, "P1.1")
    check("rw0 THE OVER-FIRE TWIN: the hand-back re-opened P1.1 with its first "
          "commit recorded, and in the fix round a clause cited to a file neither "
          "that commit nor the fix touched is still a gap naming the file - the "
          "first commit's paths are added, not every path in the tree: %r"
          % ((handed, first, untouched, untouched_block[-300:]),),
          handed[0] == 0 and "run-agent-session.py --role writer" in handed[1]
          and fid and first
          and "clauses-uncovered-writer" in untouched
          and "src/f2.txt" in untouched + untouched_block
          and _filed_body(mpath, "P1.1") is None)
    _signal_next(M, root, mpath, "--answer", "resume")
    _c, reset = _writer_round(M, root, mpath, bindir, log, "0.66", edit={},
                              result=_rw_answer({1: _WF_SRC, 2: "src/side.txt",
                                                 3: _WF_SRC}))
    _c, reset_block = _explain_of(M, root, mpath, "P1.1")
    check("rw5 a carried commit reset out of HEAD's history does not cover its "
          "clause: clause 2 cited to src/side.txt, which only that commit wrote, "
          "is a gap naming the file, the decision names the commit as left out "
          "of the carried paths, and nothing is filed: %r"
          % ((gone[:12], reset, reset_block[-400:]),),
          "clauses-uncovered-writer" in reset
          and "src/side.txt" in reset + reset_block
          and gone[:12] in reset_block and "not in HEAD's history" in reset_block
          and _filed_body(mpath, "P1.1") is None)
    _signal_next(M, root, mpath, "--answer", "resume")
    claim = _rw_answer({1: _WF_SRC, 2: _RW_NOTES, 3: _WF_SRC})
    _c, covered = _writer_round(M, root, mpath, bindir, log, "0.64", edit={},
                                result=claim)
    body = _filed_body(mpath, "P1.1") or {}
    named = [n for n in _notes(mpath, "P1.1")
             if unknown[:12] in n and gone[:12] in n and "unknown" in n]
    check("rw6 an unknown sha in the re-open record is named and the filing "
          "proceeds on the rest: the return is filed, and one note on the task "
          "names the unknown sha and the commit out of history as left out of "
          "clause coverage: %r" % ((covered, _notes(mpath, "P1.1")),),
          body.get("writerClaim") == claim and len(named) == 1)
    check("rw1 a re-opened task whose fix round touches src/mine.py and its suite "
          "only, with clause 2 cited to src/notes.txt that its first commit "
          "wrote, passes clause coverage: the return is filed with that message "
          "as the claim, and the step names no uncovered clause: %r"
          % ((covered, body.get("writerClaim"), body.get("diffPaths")),),
          "clauses-uncovered" not in covered
          and body.get("writerClaim") == claim
          and _RW_NOTES not in (body.get("diffPaths") or []))
    # The fix round closes at its own commit under a task-scoped drive, as
    # `/audit:run P1.1` closes it - which keeps the hand-back's entry - and a
    # human then re-opens P1.1 for a reason of their own, which is no hand-back.
    def task_next(*extra):
        with _Env(root):
            said = []
            code = M.main(["next", "P1.1", mpath, "--project-dir", root]
                          + list(extra), out=said.append)
        return code, "\n".join(said)
    task_next("--signal")
    closed = dict(tasks_of(mpath)["P1.1"])
    reopened = _verb(root, "audit-task.py", [
        "reopen", "P1.1", mpath, "--project-dir", root, "--reason",
        "the human wants the docstring reworded"])
    later_code, later = task_next("--signal")
    said = [task_next("--explain", "P1.1")[1]]
    later_argv = _run_argv("\n".join(said)) or []
    fed = _flag(later_argv, "--prompt-file")
    later_prompt = (_read(fed).decode("utf-8", "replace")
                    if fed and os.path.isfile(fed) else "")
    check("rw8 a later manual re-open does not re-inject the old findings: once "
          "the fix round closed at a commit of its own and a human re-opened "
          "P1.1, its next writer dispatch is the plain brief - no confirmed "
          "finding and no resume: %r"
          % ((closed.get("status"), closed.get("commit"), reopened, later_code,
              later, later_argv, later_prompt[-300:]),),
          closed.get("status") == "done" and closed.get("commit")
          and closed.get("commit") != first and reopened[0] == 0
          and "run-agent-session.py --role writer" in later
          and "--resume" not in later_argv
          and later_prompt.startswith("Implement the following task")
          and M.REVIEW_FIX_HEAD not in later_prompt and fid not in later_prompt)


def _reopened_retry_cases(check, M, bindir, log):
    """A retry after the first fix dispatch still carries the findings."""
    fix = {_WF_SRC: "v = 3\n", _WF_TEST: _PV_THREE_TEST}
    root_r, mpath_r, fid_r, _first_r, handed_r = _rw_handed_back(
        M, "rw-retry", (_wf_gate(), _RW_FLAG_GATE), bindir, log)
    first_argv, first_prompt = _clause_prompt(M, root_r, mpath_r)
    spent = _attempts(mpath_r, "P1.1")
    _c, red = _writer_round(M, root_r, mpath_r, bindir, log, "0.65",
                            edit=dict(fix, **{"bad.flag": "x\n"}),
                            result=_rw_answer({1: _WF_SRC, 2: _RW_NOTES, 3: _WF_SRC}))
    retried_code, retried = _signal_next(M, root_r, mpath_r, "--answer", "retry")
    argv, prompt = _clause_prompt(M, root_r, mpath_r)
    check("rw2 a retry after the first fix dispatch still carries the confirmed "
          "finding: the first dispatch resumed the warm session with it, the "
          "gate went red, and `retry` - an attempt spent - starts a fresh writer "
          "session whose prompt is the task's brief and then the finding: %r"
          % ((handed_r, red, retried_code, retried, argv, prompt[-400:]),),
          fid_r and _flag(first_argv, "--resume") == WRITER_SESSION
          and fid_r in first_prompt
          and "gate-red-writer" in red and retried_code == 0
          and "run-agent-session.py --role writer" in retried
          and _attempts(mpath_r, "P1.1") == (spent or 0) + 1
          and "--resume" not in argv
          and prompt.startswith("Implement the following task")
          and M.REVIEW_FIX_HEAD in prompt and fid_r in prompt)


def _review_fix_bound_cases(check, M):
    """A hand-back's entry reads only for its own round, by the task's commit."""
    state = {M.REVIEW_FIX_FIELD: {"P1.1": {"from": "a" * 40, "findings": ["P1-R1"],
                                           "dispatched": []}}}
    seen = dict((label, M.review_fix(state, {"id": "P1.1", "commit": commit})
                 is not None)
                for label, commit in (("closed-anew", "b" * 40), ("open", None),
                                      ("closed-at-from", "a" * 40)))
    check("rw7 a hand-back's entry is bound to its round: once the task records "
          "a commit other than the one the hand-back cleared, review_fix gives "
          "nothing; while it records none (the fix round open) or the cleared "
          "one (closed at no new commit), the entry still reads (the twin): %r"
          % (seen,),
          seen == {"closed-anew": False, "open": True, "closed-at-from": True})


def _reopened_finish_cases(check, M):
    """`finish_task` over a re-opened writer task keeps the hand-back's record
    and the writer's session, and still drops every other mark of the task."""
    where = os.path.realpath(_harness.fixture_root("drive-rw-finish-"))
    ctx = {"stateDir": os.path.join(where, "state"), "phase": PHASE, "did": [],
           "gitRoot": where, "project": where}
    task = {"id": "P1.1", "status": "done", "commit": "a" * 40,
            "startedAt": "2026-10-21T10:00:00Z"}
    stream = os.path.join(where, "writer.jsonl")
    _write_lf(stream, "{}\n")
    state = {M.REVIEW_FIX_FIELD: {"P1.1": {
        "from": "a" * 40, "findings": ["P1-R1"], "head": "c" * 40,
        "session": WRITER_SESSION, "stream": stream, "tree": None,
        "dispatched": True}}}
    M._mark(state, "writer", task, {
        "seq": 1, "runs": [{"seq": 0, "session": WRITER_SESSION, "stream": stream}],
        "dispatches": [{"seq": 0, "round": 0, "record": "r", "argv": []}]})
    M._mark(state, "dispatched-executor", task, {"scope": "s"})
    said = M.finish_task(ctx, state, task)
    kept = M.read_state(ctx)
    session = M.last_writer_session(kept, task) or {}
    phase = {"id": PHASE, "tasks": [task]}
    finding = {"id": "P1-R1", "severity": "high", "file": "src/mine.py:1",
               "issue": "i", "resolution": "r"}
    reopened = []

    def took(_ctx, script, args, flag, text):
        reopened.append(args[1])
        return "re-opened", None
    real = M._verb_with_text
    M._verb_with_text = took
    try:
        again = M.hand_back(dict(ctx, manifest=os.path.join(where, "plan.json")),
                            kept, phase, "d" * 40, [(finding, ["P1.1"])])
    finally:
        M._verb_with_text = real
    check("rw3 after a task-scoped drive closes the task, the hand-back's "
          "from-commit and the warm session are still found: the state keeps "
          "the review-fix entry and the writer's record of the start, so a "
          "second hand-back of a fix closed at no new commit is refused, while "
          "the task's other marks are dropped: %r"
          % ((said, kept, session, again, reopened),),
          (kept.get(M.REVIEW_FIX_FIELD) or {}).get("P1.1", {}).get("from") == "a" * 40
          and session.get("session") == WRITER_SESSION
          and "dispatched-executor" not in kept
          and again is not None and "closed again at no new commit" in again[1]
          and reopened == [])
    bare_ctx = dict(ctx, stateDir=os.path.join(where, "bare-state"), did=[])
    bare = {}
    M._mark(bare, "dispatched-executor", task, {"scope": "s"})
    M.finish_task(bare_ctx, bare, task)
    check("rw4 THE TWIN: a task with no hand-back and no writer record leaves no "
          "drive state behind once it closes: %r"
          % (os.listdir(os.path.dirname(M.state_path(bare_ctx)))
             if os.path.isdir(os.path.dirname(M.state_path(bare_ctx))) else [],),
          not os.path.exists(M.state_path(bare_ctx)))


def _gate_calls(module):
    """Wrap `module.run_verb` so each `run-test-gate.py` call is kept as
    `(args, output)` - which flags it was given, and what it printed."""
    calls = []
    real = module.run_verb

    def kept(ctx, script, args, stdin=None):
        code, out, err = real(ctx, script, args, stdin=stdin)
        if script == "run-test-gate.py":
            calls.append((list(args), out + err))
        return code, out, err
    module.run_verb = kept
    return calls


def _rerun_measures_cases(check):
    """`--answer rerun` on a red gate is a request to MEASURE: the gate run it
    leads to is given `--no-reuse`, so a red verdict is never repeated back as
    the answer to a rerun, and the mark is spent on that one run - the next
    plain gate run may repeat a verdict again."""
    M, why = _load("drive_phase_rerun_measures")
    if M is None:
        check("rm1 the driver loads", False, why)
        return
    calls = _gate_calls(M)
    root, mpath = _repo("rerun-measures", task_ids=TASKS[:1], gate=("false",))
    run = drive(M, root, mpath, cap=3)
    first = run["steps"][-1]
    code, text = _next(M, root, mpath, "--answer", "rerun")
    rerun_call = calls[1] if len(calls) > 1 else ([], "")
    check("rm1 a rerun after a red gate runs the gate with --no-reuse, and what "
          "it printed is a measurement - no GATE VERDICT REUSED line: %r"
          % ((first, code, rerun_call[0], rerun_call[1][-300:]),),
          first == ("decide", "gate-red", None) and code == 0
          and len(calls) == 2 and "--no-reuse" in rerun_call[0]
          and "GATE VERDICT REUSED" not in rerun_call[1]
          and "REUSED" not in text)
    state = _drive_state(root)
    check("rm2 the rerun mark is spent on that run: none is left in the drive "
          "state once the gate measured: %r" % (state.get("rerun"),),
          not (state.get("rerun") or {}).get("P1.1"))
    # The decision the measured run printed is taken back out, so the next
    # plain `next` meets the gate step afresh, as it would after a decision
    # that no longer applies.
    state.pop("pending", None)
    with open(os.path.join(root, ".claude", "state", "drive", "%s.json"
                           % (PHASE,)), "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    _next(M, root, mpath)
    plain = calls[2] if len(calls) > 2 else (["--no-reuse"], "")
    check("rm3 THE TWIN: the next plain gate run is given no --no-reuse, and on "
          "this unchanged tree it repeats the recorded red - so the reuse rm1 "
          "avoided is real here, and the mark was spent once: %r"
          % ((plain[0], plain[1][:200]),),
          "--no-reuse" not in plain[0] and "GATE VERDICT REUSED" in plain[1])
    _rerun_after_record_cases(check, M)


def _rerun_after_record_cases(check, M):
    """One tree identity, an older red the drive measured and a newer green
    recorded by hand: `rerun` closes on a green and never prints the red the
    newer row superseded, and a plain gate run after it repeats the GREEN."""
    flagdir = os.path.realpath(_harness.fixture_root("drive-rerun-flag-"))
    flag = os.path.join(flagdir, "flag")
    probe = os.path.join(flagdir, "probe.py")
    with open(probe, "w", encoding="utf-8") as fh:
        fh.write("import os, sys\nsys.exit(0 if os.path.exists(%r) else 1)\n"
                 % (flag,))
    root, mpath = _repo("rerun-after-record", task_ids=TASKS[:1],
                        gate=('"%s" "%s"' % (sys.executable, probe),))
    calls = _gate_calls(M)
    run = drive(M, root, mpath, cap=3)
    check("rm4 the fixture's gate is red first, and the drive asks: %r"
          % (run["steps"][-1],), run["steps"][-1] == ("decide", "gate-red", None))
    with open(flag, "w", encoding="utf-8") as fh:
        fh.write("x\n")
    with _Env(root):
        hand = M.run_verb({"project": root, "log": []}, "run-test-gate.py", [
            mpath, PHASE, "--task", "P1.1", "--record", "--no-reuse",
            "--project-dir", root])
    check("rm5 the hand-recorded run over the same tree is green: %r"
          % (hand[0],), hand[0] == 0 and "GATE GREEN" in hand[1] + hand[2])
    before = len(calls)
    code, text = _next(M, root, mpath, "--answer", "rerun")
    seen = calls[before:]
    said = text + "".join(out for _a, out in seen)
    check("rm6 `rerun` after the newer recorded green closes on a green and "
          "never prints the red it superseded: %r" % ((code, said[-300:]),),
          code == 0 and seen and "GATE RED" not in said
          and "GATE-RED" not in text and "gate-red" not in text)
    state = _drive_state(root)
    state.pop("pending", None)
    with open(os.path.join(root, ".claude", "state", "drive", "%s.json"
                           % (PHASE,)), "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    before = len(calls)
    _next(M, root, mpath)
    plain = "".join(out for _a, out in calls[before:])
    check("rm7 THE TWIN: a plain gate run on this identity repeats a verdict "
          "only if it is the GREEN one - the red is never what it names: %r"
          % (plain[:300],), "GATE RED" not in plain)


# --- a stored gate verdict, shown only while its basis holds -------------------
# A build command a gate entry names, red and green, spelled so a change between
# two of them is a change of `meta.buildCommands` alone: the entry names stay.
_SV_RED = '"%s" -c "import sys; sys.exit(1)"' % (sys.executable,)
_SV_GREEN = '"%s" -c "import sys; sys.exit(0)"' % (sys.executable,)
_SV_GREEN_TOO = '"%s" -c "import sys; sys.exit(0)" again' % (sys.executable,)
# The run id and its age a gate-red line carries: `run <runId>, <n><unit> old`.
_SV_RUN = re.compile(r"\brun (\S+), (\d+)([smhd]) old\b")
# Two members gated by two entries, so each is red on a step of its own.
_SV_TWO_STEPS = ("unit-a", "unit-b")


def _sv_build(command, entries=("unit", "unit")):
    """`edit(plan)` for `_commit_plan`: the wave's two members gated by the
    entries `entries` names - one entry, or a tuple of them, per member - each
    resolved to `command` through `meta.buildCommands`."""
    gates = [list(e) if isinstance(e, tuple) else [e] for e in entries]

    def edit(plan):
        plan["meta"]["buildCommands"] = dict((k, command) for g in gates for k in g)
        for task, gate in zip(plan["phases"][0]["tasks"], gates):
            task["tests"]["gate"] = list(gate)
    return edit


def _sv_set_command(mpath, command):
    """Change what every `meta.buildCommands` key resolves to, the entry names
    left as they are - the plan edited by hand, uncommitted."""
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["meta"]["buildCommands"] = dict(
        (k, command) for k in plan["meta"]["buildCommands"])
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)


def _sv_red_wave(M, prefix, entries=("unit", "unit")):
    """A two-member wave whose members are both red under `entries`, each
    resolved to the red command: `(root, mpath, calls, second)`, `second` the
    print that measured both - the first member's decision, the second's
    parked."""
    calls = _gate_calls(M)
    root, mpath = _wave_repo(prefix, 2)
    _commit_plan(root, mpath, _sv_build(_SV_RED, entries), "both members red")
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    _code, second = _next_wave(M, root, mpath)
    return root, mpath, calls, second


def _sv_parked(root, task_id):
    return (((_drive_state(root).get("wave") or {}).get("parked") or {})
            .get(task_id) or {})


def _sv_task_calls(calls, task_id):
    """The gate calls among `calls` that measured `task_id`."""
    return [(a, out) for a, out in calls if _flag(a, "--task") == task_id]


def _sv_newest_run(root, mpath, task_id):
    rows = _evio.oldest_first(_rows_of(root, mpath, task_id))
    return rows[-1].get("runId") if rows else None


def _stored_red_cases(check):
    """A pending or parked gate-red decision is shown only while the run it
    stands on still answers the gate the task resolves to now: once
    `meta.buildCommands` changes, the drive measures each member again rather
    than replaying the red the old command gave - the one a rerun answered and
    the one that was parked behind it alike - and every gate-red line names the
    run and its age."""
    M, why = _load("drive_phase_stored_red")
    if M is None:
        check("sv1 the driver loads", False, why)
        return
    # Red on two different steps, so a rerun answered on the first member does
    # not reach the second (`sv4m`): what measures the second here is its
    # decision asking whether its run still answers the gate, and nothing else.
    root, mpath, calls, second = _sv_red_wave(M, "storedred", _SV_TWO_STEPS)
    parked = _sv_parked(root, "P1.2")
    line = next((ln for ln in second.splitlines() if ln.startswith("decide ")), "")
    shown = _SV_RUN.search(line)
    check("sv1 both members are red under the one build command, the first "
          "member's decision is printed and the second's waits parked, and the "
          "printed gate-red line names the run it stands on and its age: %r"
          % ((line, parked.get("decision"), _sv_newest_run(root, mpath, "P1.1")),),
          instruction(second) == ("decide", "gate-red", None)
          and line.startswith("decide gate-red P1.1")
          and parked.get("decision") == "gate-red"
          and shown is not None
          and shown.group(1) == _sv_newest_run(root, mpath, "P1.1"))
    before = len(calls)
    _code, again = _next(M, root, mpath)
    again_line = next((ln for ln in again.splitlines()
                       if ln.startswith("decide ")), "")
    check("sv2 THE TWIN: with the build command and the tree unchanged, the "
          "stored red is shown again as before - no gate runs, and the line "
          "still names its run: %r" % ((again_line, calls[before:]),),
          instruction(again) == ("decide", "gate-red", None)
          and "P1.1" in again_line and len(calls) == before
          and _SV_RUN.search(again_line) is not None
          and _SV_RUN.search(again_line).group(1) == shown.group(1)
          if shown else False)
    said, second_runs, tasks = _sv_after_change(M, root, mpath, calls)
    check("sv3 after the build command changed and `rerun` was answered on the "
          "first member, the second member's parked red is not replayed: its "
          "gate is measured under the new command and it closes, as the first "
          "does - no gate-red is printed for either: %r"
          % ((said[-600:], [a for a, _o in second_runs],
              [(t, tasks[t].get("status")) for t in ("P1.1", "P1.2")]),),
          _sv_measured_again(said, second_runs, tasks))
    # RED TWIN: the same wave under a driver whose decisions never ask whether
    # their run still answers the gate - the parked red is replayed, so sv3's
    # predicate fails for it, which is what says the predicate reads the check.
    mutant, _w = _load("drive_phase_stored_red_mutant")
    mutant.gate_basis_holds = lambda ctx, manifest, pending: True
    root_m, mpath_m, calls_m, _second_m = _sv_red_wave(mutant, "storedredm",
                                                       _SV_TWO_STEPS)
    said_m, runs_m, tasks_m = _sv_after_change(mutant, root_m, mpath_m, calls_m)
    check("sv3m RED TWIN: a driver that shows a stored red without asking its "
          "basis replays the second member's red under the old command: %r"
          % ((said_m[-300:], [t.get("status") for t in tasks_m.values()]),),
          not _sv_measured_again(said_m, runs_m, tasks_m))
    _sv_pure_cases(check, M)


def _sv_after_change(M, root, mpath, calls):
    """Change the build command to the green one, answer `rerun` on the printed
    decision and drive on: `(said, second_runs, tasks)` - every print, the
    gate calls that measured the second member, and the plan's tasks."""
    _sv_set_command(mpath, _SV_GREEN)
    before = len(calls)
    prints = [_next(M, root, mpath, "--answer", "rerun")[1]]
    for _ in range(3):
        if instruction(prints[-1])[0] != "dispatch" and all(
                t.get("status") == "done" for t in tasks_of(mpath).values()):
            break
        prints.append(_next(M, root, mpath)[1])
    return ("\n".join(prints), _sv_task_calls(calls[before:], "P1.2"),
            tasks_of(mpath))


def _sv_measured_again(said, second_runs, tasks):
    return bool("decide gate-red" not in said and second_runs
                and all("GATE VERDICT REUSED" not in out for _a, out in second_runs)
                and tasks["P1.1"].get("status") == "done"
                and tasks["P1.2"].get("status") == "done")


def _sv_pure_cases(check, M):
    """The comparison a stored verdict passes, asked of rows built here, and
    the tree name it compares held to the one the gate runner records."""
    rtg = _loader.load_script("run-test-gate.py", "rtg_tree_key", cache=False)
    where = os.path.realpath(_harness.fixture_root("drive-treekey-"))
    try:
        keys = (_evio.tree_key(where), rtg.tree_key(where))
    finally:
        _harness.remove_tree(where)
    check("sv7 the tree name a stored verdict is compared on is the one "
          "run-test-gate records as testedState.tree.key: %r" % (keys,),
          keys[0] == keys[1] and len(keys[0]) == 12)
    row = {"runId": "r1", "ts": "2026-10-21T10:00:00Z", "gateDigest": "sha256:a",
           "testedState": {"scopeDigest": "s1", "tree": {"key": "k1"}},
           "steps": [{"name": "unit", "exit": 1}]}
    undigested = dict(row, runId="r2")
    undigested.pop("gateDigest")
    # A repeat of r1 taken in another tree, as `run-test-gate` writes one: the
    # verdict copied, the gate digest of its own run, and no testedState - its
    # identity is the content, not the tree. And a repeat that did record a
    # tree, which then is what it is compared on.
    repeat = {"runId": "r3", "ts": "2026-10-21T11:00:00Z", "gateDigest": "sha256:a",
              "verdictSource": _evio.REUSED, "reusedFrom": {"runId": "r1"},
              "testedState": {}, "steps": []}
    placed = dict(repeat, runId="r4", testedState={"tree": {"key": "k2"}})
    now = {"gateDigest": "sha256:a", "tree": "k1"}
    said = dict((label, _evio.stored_verdict_moved(rows, run, dict(now, **over))[0])
                for label, rows, run, over in (
                    ("holds", [row], "r1", {}),
                    ("gate", [row], "r1", {"gateDigest": "sha256:b"}),
                    ("tree", [row], "r1", {"tree": None}),
                    ("edited", [dict(row, testedState={
                        "scopeDigest": "s2", "tree": {"key": "k1"}})], "r1", {}),
                    ("gone", [], "r1", {}),
                    ("none", [row], None, {}),
                    ("undigested", [undigested], "r2", {}),
                    ("repeat-elsewhere", [row, repeat], "r3", {"tree": "k2"}),
                    ("repeat-placed", [row, placed], "r4", {"tree": "k2"}),
                    ("repeat-moved", [row, placed], "r4", {"tree": "k3"})))
    # `edited` is the bytes in the tree moving under an unchanged gate: not this
    # comparison's question (the committer refuses that), so it still holds.
    check("sv8 a stored verdict holds only while the gate digest and the tree "
          "agree; either disagreeing is moved, edited bytes under the same gate "
          "are left to the committer, and a run the ledger lacks or a row with "
          "no gate digest is unknown - never agreement: %r" % (said,),
          said == {"holds": _evio.STORED_HOLDS, "gate": _evio.STORED_MOVED,
                   "tree": _evio.STORED_MOVED, "edited": _evio.STORED_HOLDS,
                   "gone": _evio.STORED_UNKNOWN, "none": _evio.STORED_UNKNOWN,
                   "undigested": _evio.STORED_UNKNOWN,
                   "repeat-elsewhere": _evio.STORED_HOLDS,
                   "repeat-placed": _evio.STORED_HOLDS,
                   "repeat-moved": _evio.STORED_MOVED})
    # The id a green run's terse line names, read as the drive reads it: the
    # records are joined with "; ", so a reading that ran to the next space
    # took the separator with it and named no row.
    terse = rtg.success_line(["GATE GREEN: unit", "  evidence: recorded r-5.abc",
                              "  pointer: P1.1 now names it"])
    old = re.compile(r"evidence: recorded (\S+)").search(terse)
    read = M._RUN_ID.search(terse)
    check("sv9 the run id the drive reads off a green run's terse line is the id "
          "itself, where a reading to the next space took the separator: %r"
          % ((terse, read and read.group(1), old and old.group(1)),),
          read is not None and read.group(1) == "r-5.abc"
          and old is not None and old.group(1) == "r-5.abc;")


def _stored_rerun_cases(check):
    """A rerun answered on one wave member is a request to measure every member
    whose parked red failed on the same step - never one measured and the
    other's stored red replayed; a member red on another step is still asked
    on its own."""
    M, why = _load("drive_phase_stored_rerun")
    if M is None:
        check("sv4 the driver loads", False, why)
        return
    root, mpath, calls, _second = _sv_red_wave(M, "storedrerun")
    before = len(calls)
    _code, text = _next(M, root, mpath, "--answer", "rerun")
    second_runs = _sv_task_calls(calls[before:], "P1.2")
    check("sv4 both members red on the same step: `rerun` answered on the first "
          "measures the second too, with --no-reuse, in the same next: %r"
          % ((text[-300:], [a for a, _o in second_runs]),),
          second_runs and all("--no-reuse" in a for a, _o in second_runs))
    # RED TWIN: a rerun that marks only the member it was answered on leaves
    # the other's red parked and its gate unrun, so sv4's predicate fails.
    mutant, _w = _load("drive_phase_stored_rerun_mutant")
    mutant.rerun_alongside = lambda ctx, state, manifest, pending: []
    root_m, mpath_m, calls_m, _second_m = _sv_red_wave(mutant, "storedrerunm")
    before = len(calls_m)
    _next(mutant, root_m, mpath_m, "--answer", "rerun")
    runs_m = _sv_task_calls(calls_m[before:], "P1.2")
    check("sv4r RED TWIN: a driver whose rerun reaches only the member it was "
          "answered on measures nothing for the second: %r"
          % ([a for a, _o in runs_m],),
          not (runs_m and all("--no-reuse" in a for a, _o in runs_m)))
    root_b, mpath_b, calls_b, _second_b = _sv_red_wave(M, "storedrerunb",
                                                       _SV_TWO_STEPS)
    before = len(calls_b)
    _code, text_b = _next(M, root_b, mpath_b, "--answer", "rerun")
    other_runs = _sv_task_calls(calls_b[before:], "P1.2")
    check("sv4m THE TWIN: red on different steps, the rerun answered on the "
          "first member does not reach the second - its decision stays parked "
          "for its own answer and its gate is not run: %r"
          % ((text_b[-300:], [a for a, _o in other_runs],
              _sv_parked(root_b, "P1.2").get("decision")),),
          not other_runs and _sv_parked(root_b, "P1.2").get("decision")
          == "gate-red")
    # Overlapping, not equal: the first member red on one step, the second on
    # that step and another. "The same failing step" is a step both share.
    root_c, mpath_c, calls_c, _second_c = _sv_red_wave(
        M, "storedrerunc", ("unit-a", ("unit-a", "unit-b")))
    shared = ((_sv_parked(root_c, "P1.2").get("verdict") or {}).get("failing"))
    before = len(calls_c)
    _code, text_c = _next(M, root_c, mpath_c, "--answer", "rerun")
    shared_runs = _sv_task_calls(calls_c[before:], "P1.2")
    check("sv4o a member red on that step and another is reached by the rerun "
          "answered on a member red on the one step - measured with --no-reuse "
          "in the same next: %r" % ((shared, [a for a, _o in shared_runs]),),
          shared == ["unit-a", "unit-b"]
          and shared_runs and all("--no-reuse" in a for a, _o in shared_runs))


def _stored_explain_cases(check):
    """`--explain` is a path that shows a stored decision too: once the run a
    gate-red stood on no longer answers the gate, it says so - why, and what the
    next `next` does - and never replays the text the last signal kept."""
    M, why = _load("drive_phase_stored_explain")
    if M is None:
        check("sv10 the driver loads", False, why)
        return
    root, mpath = _repo("storedexplain", task_ids=TASKS[:1], gate=("unit",),
                        per_task="phase")
    _commit_plan(root, mpath, lambda plan: plan["meta"].update(
        buildCommands={"unit": _SV_RED}), "the gate's build command, red")
    _code, first = _next(M, root, mpath)
    if instruction(first) == ("dispatch", "executor", "P1.1"):
        _file_executor(root, mpath, "P1.1")
    # The form every command runs: the decision goes out as a signal, and its
    # text is what a later explain could replay.
    _code, line = _signal_next(M, root, mpath)
    code, held = _explain_of(M, root, mpath, "P1.1")
    check("sv10 THE TWIN: with the build command unchanged, explain shows the "
          "waiting gate-red with its run and its answers: %r" % ((line, held),),
          "gate-red" in line and code == 0 and "decide gate-red P1.1" in held
          and _SV_RUN.search(held) is not None and "--answer" in held)
    _sv_set_command(mpath, _SV_GREEN)
    code, after = _explain_of(M, root, mpath, "P1.1")
    check("sv11 after the build command changed, explain says the gate-red no "
          "longer stands on a run that answers the gate, why, and that the next "
          "next measures again - no decide line and no answer offered: %r"
          % ((code, after),),
          code == 0 and "decide gate-red" not in after and "--answer" not in after
          and "no longer answers its gate" in after
          and "other commands" in after and "next measures" in after)


def _stored_green_cases(check):
    """The green a task's gate recorded is the drive's stored verdict until the
    close: once `meta.buildCommands` resolves the gate to another command, the
    drive measures it again rather than closing on the old green; unchanged, it
    closes on it as before."""
    M, why = _load("drive_phase_stored_green")
    if M is None:
        check("sv5 the driver loads", False, why)
        return

    def to_reviewer(module, prefix):
        root, mpath = _repo(prefix, task_ids=TASKS[:1], gate=("unit",))
        _commit_plan(root, mpath, lambda plan: plan["meta"].update(
            buildCommands={"unit": _SV_GREEN}), "the gate's build command")
        calls = _gate_calls(module)
        texts = []
        for _ in range(4):
            texts.append(_next(module, root, mpath)[1])
            kind = instruction(texts[-1])
            if kind == ("dispatch", "executor", "P1.1"):
                _file_executor(root, mpath, "P1.1")
            elif kind[0] != "dispatch" or kind[1] == "reviewer":
                break
        return root, mpath, calls, texts

    def changed_then_closed(module, prefix):
        """The command changed after the green and the reviewer filed: `(text,
        measured, status, reached)` of the next that follows, `reached` the
        last print and the gate calls before the change."""
        root, mpath, calls, texts = to_reviewer(module, prefix)
        reached = (texts[-1], list(calls))
        _sv_set_command(mpath, _SV_GREEN_TOO)
        _file_reviewer(root, mpath, "P1.1")
        before = len(calls)
        _code, text = _next(module, root, mpath)
        return (text, calls[before:], tasks_of(mpath)["P1.1"].get("status"),
                reached)

    def measured_again(measured, status):
        return bool(len(measured) == 1
                    and "GATE VERDICT REUSED" not in measured[0][1]
                    and "GATE GREEN" in measured[0][1] and status == "done")

    text, measured, status, (last, gated) = changed_then_closed(M, "storedgreen")
    check("sv5 the fixture reaches the per-task reviewer with the gate measured "
          "green once: %r" % ((last[-200:], len(gated)),),
          instruction(last) == ("dispatch", "reviewer", "P1.1")
          and len(gated) == 1 and "GATE GREEN" in gated[0][1])
    check("sv6 a stored green whose build command changed since is measured "
          "again before the close - one gate run, not a repeat - and the task "
          "closes on that run: %r"
          % ((text[-300:], [o[-120:] for _a, o in measured]),),
          measured_again(measured, status))
    # RED TWIN: a driver whose green mark is read as it was - present, so held
    # - closes on the old green, and sv6's predicate fails for it.
    mutant, _w = _load("drive_phase_stored_green_mutant")
    mutant.stored_green = lambda ctx, state, manifest, task, kind: (
        mutant._evio.STORED_HOLDS if mutant._marked(state, kind, task) else None)
    text_m, measured_m, status_m, _reached = changed_then_closed(mutant,
                                                                 "storedgreenm")
    check("sv6r RED TWIN: a driver that closes on a stored green without asking "
          "its basis measures nothing after the command changed: %r"
          % ((text_m[-200:], len(measured_m), status_m),),
          not measured_again(measured_m, status_m))
    root_t, mpath_t, calls_t, _texts_t = to_reviewer(M, "storedgreent")
    _file_reviewer(root_t, mpath_t, "P1.1")
    before = len(calls_t)
    _code, text_t = _next(M, root_t, mpath_t)
    check("sv6m THE TWIN: with the build command and the tree unchanged, the "
          "stored green is reused as before - the close runs no gate: %r"
          % ((text_t[-300:], len(calls_t) - before),),
          len(calls_t) == before
          and tasks_of(mpath_t)["P1.1"].get("status") == "done")


def _single_task_cases(check):
    """`next <taskId>` drives that one task and stops: the run of `/audit:run`
    and `/audit:next`, which execute exactly one task, through the same steps."""
    M, why = _load("drive_phase_single")
    if M is None:
        check("dt1 the driver loads", False, why)
        return
    root, mpath = _repo("single")
    run = drive(M, root, mpath, target="P1.2")
    tasks = tasks_of(mpath)
    check("dt1 `next P1.2` dispatches that task's executor and reviewer, closes it "
          "and prints `done`, leaving its siblings pending, the phase unsigned, "
          "the lock released and no drive state behind: %r"
          % ((run["steps"], [(t, tasks.get(t, {}).get("status")) for t in TASKS]),),
          run["steps"] == [("dispatch", "executor", "P1.2"),
                           ("dispatch", "reviewer", "P1.2"), ("done", None, None)]
          and tasks.get("P1.2", {}).get("status") == "done"
          and [tasks.get(t, {}).get("status") for t in ("P1.1", "P1.3")]
          == ["pending", "pending"]
          and not os.path.exists(os.path.join(root, ".claude", "state", "drive"))
          and "phase-%s" % (PHASE,) not in _verb(
              root, "audit-lock.py", ["status", "--project", root])[1])
    again = drive(M, root, mpath, target="P1.2", cap=2)
    check("dt2 a task already done is reported done at once, and nothing is "
          "started: %r" % ((again["steps"], _attempts(mpath, "P1.2")),),
          again["steps"] == [("done", None, None)]
          and tasks_of(mpath).get("P1.2", {}).get("status") == "done")
    whole = drive(M, root, mpath, cap=3)
    check("dt3 THE TWIN: `next P1` still drives the phase - its first dispatch is "
          "the first pending task, so the task scope narrows only when asked: %r"
          % (whole["steps"],),
          whole["steps"][:1] == [("dispatch", "executor", "P1.1")])
    root_t, mpath_t = _repo("task-form")
    refused = []
    with _Env(root_t):
        for given in ("p1", "P1", "1"):
            said, errs = [], io.StringIO()
            with contextlib.redirect_stderr(errs):
                code = M.main(["next", given, mpath_t, "--project-dir", root_t,
                               "--task"], out=said.append)
            refused.append((given, code, said, errs.getvalue()))
    after = tasks_of(mpath_t)
    check("dt7 the one-task form given a phase id (p1, P1, 1) exits 2 on one line "
          "naming /audit:phase P1 and the tasks it would run, one at a time on a "
          "plan with no waveWidth, and starts nothing: %r" % (refused,),
          all(c == 2 and s == [] and e.count("\n") == 1
              and "`/audit:phase P1`" in e and "P1.1, P1.2, P1.3" in e
              and "one at a time" in e for _g, c, s, e in refused)
          and all(t.get("status") == "pending" for t in after.values())
          and not os.path.exists(os.path.join(root_t, ".claude", "state", "drive")))
    with open(os.path.join(root_t, ".claude", "audit.config.json"),
              encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["executor"] = {"waveWidth": 3}
    with open(os.path.join(root_t, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump(cfg, fh)
    errs = io.StringIO()
    with _Env(root_t), contextlib.redirect_stderr(errs):
        M.main(["next", "P1", mpath_t, "--project-dir", root_t, "--task"],
               out=[].append)
    check("dt8 with executor.waveWidth above 1 the same refusal says the phase "
          "verb runs them in waves: %r" % (errs.getvalue(),),
          "in waves of up to 3" in errs.getvalue()
          and "one at a time" not in errs.getvalue())
    said = []
    with _Env(root_t):
        code = M.main(["next", "P1.2", mpath_t, "--project-dir", root_t, "--task"],
                      out=said.append)
    kind = instruction("\n".join(said))
    check("dt9 THE TWIN: a task id with the one-task flag still drives that task: "
          "%r" % ((code, kind),), code == 0 and kind == ("dispatch", "executor", "P1.2"))
    echo_free = [t for _c, t in run["prints"] + again["prints"] + whole["prints"]
                 if "ado echo" in t]
    check("dt5 THE ALLOW TWIN: a plan with no board owes no ADO echo, and no print "
          "says one is owed: %r" % (echo_free,), echo_free == [])
    root_a, mpath_a = _repo("single-ado")
    with open(mpath_a, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["meta"]["ado"] = {"organization": "o", "project": "p"}
    plan["phases"][0]["tasks"][1]["ado"] = {"id": 4242}
    with open(mpath_a, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root_a, "commit", "-qam", "board")
    run_a = drive(M, root_a, mpath_a, target="P1.2")
    owed = [t for _c, t in run_a["prints"] if "ado echo owed: P1.2" in t]
    rule_a = list((M.STEPS.get("ado-echo") or {}).get("rule") or ())
    check("dt6 a linked task the drive closed owes the board its echo, and the print "
          "that reports the close says so with the rule for it - no verb sends it, "
          "so the instruction is the whole of it: %r" % (owed,),
          len(owed) == 1 and rule_a and all(line in owed[0] for line in rule_a)
          and run_a["steps"][-1] == ("done", None, None))
    rule = list((M.STEPS.get("dispatch-executor") or {}).get("rule") or ())
    first = run["prints"][0][1] if run["prints"] else ""
    check("dt4 the executor's dispatch prints the rule that applies at it, under "
          "the instruction, inside the bound: %r" % (first,),
          rule and all(line in first for line in rule)
          and len(first.encode("utf-8")) <= BOUND)


def _lock_stop_cases(check):
    """A lock another live run holds stops the drive, and the stop carries the
    rule for it: wait, never take it over by hand."""
    M, why = _load("drive_phase_lock")
    if M is None:
        check("dl1 the driver loads", False, why)
        return
    real = M.run_verb

    def held(ctx, script, args, stdin=None):
        if script == "audit-lock.py" and args[:1] == ["acquire"]:
            return 3, "[audit-lock] phase-P1 is held by a live session\n", ""
        return real(ctx, script, args, stdin=stdin)
    M.run_verb = held
    root, mpath = _repo("lock", task_ids=TASKS[:1])
    run = drive(M, root, mpath, cap=1)
    code, text = run["prints"][-1]
    rule = list((M.STEPS.get("stop-lock") or {}).get("rule") or ())
    check("dl1 a held lock stops the drive with the lock verb's own words and the "
          "rule printed under them: %r" % ((code, text),),
          code == 1 and "[audit-lock]" in text and rule
          and all(line in text for line in rule))

    def index_held(ctx, script, args, stdin=None):
        if script == "audit-task.py" and args[:1] == ["start"]:
            return 3, "[audit-lock] the index lock is held by a live session\n", ""
        return real(ctx, script, args, stdin=stdin)
    M.run_verb = index_held
    root, mpath = _repo("lockidx", task_ids=TASKS[:1])
    run = drive(M, root, mpath, cap=1)
    code, text = run["prints"][-1]
    state_file = os.path.join(root, ".claude", "state", "drive")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl2 a drive that took the phase lock and then stops on a verb refusal "
          "(the index lock held during start, exit 3) releases phase-%s and leaves "
          "no taken lock in its state: %r" % (PHASE, (code, text, held_now)),
          code == 1 and "audit-task.py" in text and not held_now
          and not os.path.exists(state_file))
    rule = list((M.STEPS.get("stop-index-lock") or {}).get("rule") or ())
    check("dl3 an index-lock exit 3 from audit-task has its own followed rule, "
          "printed under the verb's words: %r" % (text,),
          rule and all(line in text for line in rule))

    # A phase that vanishes from the plan after the lock was taken raises out of
    # the locked body; that stop must give the lock back like any other.
    M.run_verb = real
    real_load = M.load_phase

    def vanished(ctx):
        raise ValueError("phase %s is no longer in the plan" % (ctx["phase"],))
    M.load_phase = vanished
    root, mpath = _repo("lockgone", task_ids=TASKS[:1])
    try:
        run = drive(M, root, mpath, cap=1)
    finally:
        M.load_phase = real_load
    code, text = run["prints"][-1]
    state_file = os.path.join(root, ".claude", "state", "drive")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl5 a phase that vanishes after the lock is taken stops the drive and "
          "releases phase-%s, leaving no taken lock in its state: %r"
          % (PHASE, (code, text, held_now)),
          code == 1 and "stopped" in text and not held_now
          and not os.path.exists(state_file))

    # Any other error raised after the lock was taken gives the lock back and
    # still surfaces: releasing must not swallow what nobody expected.
    def broken(ctx):
        raise RuntimeError("the plan read blew up")
    M.load_phase = broken
    root, mpath = _repo("lockboom", task_ids=TASKS[:1])
    raised = None
    try:
        drive(M, root, mpath, cap=1)
    except RuntimeError as exc:
        raised = exc
    finally:
        M.load_phase = real_load
    state_file = os.path.join(root, ".claude", "state", "drive")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl6 an unexpected error raised after the lock is taken surfaces to the "
          "caller and phase-%s is released first, with no taken lock in the state: %r"
          % (PHASE, (raised, held_now)),
          raised is not None and "blew up" in str(raised) and not held_now
          and not os.path.exists(state_file))

    # A usage refusal with no decision pending leaves nothing for a later next to
    # answer, so the lock goes back; with one pending it is still this run's.
    M.run_verb = real
    root, mpath = _repo("lockusage", task_ids=TASKS[:1])
    code, text = _next(M, root, mpath, "--answer", "fix", "--reason", "x")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl7 a refused --answer with no decision pending exits 2 and releases "
          "phase-%s, leaving no taken lock in its state: %r"
          % (PHASE, (code, text, held_now)),
          code == 2 and "answers nothing" in text and not held_now
          and _drive_state(root).get("lock") != "taken")
    root, mpath, _t = _at_phase_review(M, "lockreason")
    code, text = _next(M, root, mpath, "--answer", "sign-off")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl8 a --answer sign-off sent without --reason exits 2 and releases "
          "phase-%s: %r" % (PHASE, (code, text, held_now)),
          code == 2 and "needs --reason" in text and not held_now
          and _drive_state(root).get("lock") != "taken")
    root, mpath = _repo("lockpending", task_ids=TASKS[:1], per_task="phase")
    drive(M, root, mpath, findings=FINDINGS, answer=None)
    pending_before = _drive_state(root).get("pending")
    code, text = _next(M, root, mpath, "--answer", "no-such-option", "--reason", "x")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    after = _drive_state(root)
    check("dl9 a refused --answer while a decision IS pending exits 2, keeps "
          "phase-%s and leaves the decision answerable: %r"
          % (PHASE, (code, pending_before is not None, held_now)),
          code == 2 and pending_before is not None and held_now
          and after.get("pending") == pending_before)

    # A refused --answer while an executor dispatch is out answers "nothing
    # pending" but the executor still owes its return: the lock stays taken.
    root, mpath = _repo("lockdispatch", task_ids=TASKS[:1])
    code0, text0 = _next(M, root, mpath)
    code, text = _next(M, root, mpath, "--answer", "fix", "--reason", "x")
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl10 a refused --answer while an executor dispatch is out exits 2 and "
          "keeps phase-%s taken: %r" % (PHASE, (code0, code, text, held_now)),
          code0 == 0 and "dispatch" in text0 and code == 2 and "answers nothing" in text
          and held_now and _drive_state(root).get("lock") == "taken")

    # The dispatch check reads the plan a second time; when that read fails the
    # drive cannot tell whether an executor is out, so the lock is kept, the
    # reason is printed, and nothing crashes. No dispatch is out here, so once
    # the plan reads again a further next gives the kept lock back.
    root, mpath = _repo("lockunread", task_ids=TASKS[:1])
    real_locked = M.drive_locked
    real_load = M.load_phase

    def unreadable(ctx):
        raise OSError("the plan vanished")

    def arm_after(ctx, state, *rest):
        result = real_locked(ctx, state, *rest)
        M.load_phase = unreadable
        return result
    M.drive_locked = arm_after
    crashed = None
    try:
        code, text = _next(M, root, mpath, "--answer", "fix", "--reason", "x")
    except Exception as exc:
        code, text, crashed = None, "", exc
    finally:
        M.drive_locked = real_locked
        M.load_phase = real_load
    held_now = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl11 a usage refusal whose dispatch check cannot read the plan (OSError) "
          "neither crashes the drive nor leaves the outcome unstated: the lock is "
          "kept and the line says why: %r" % ((code, text, crashed, held_now),),
          crashed is None and code == 2 and held_now
          and _drive_state(root).get("lock") == "taken"
          and "lock kept" in text and "the plan vanished" in text)
    code2, text2 = _next(M, root, mpath, "--answer", "fix", "--reason", "x")
    held_later = "phase-%s" % (PHASE,) in _verb(
        root, "audit-lock.py", ["status", "--project", root])[1]
    check("dl11b the kept lock is released by the next refusal over a readable "
          "plan, as the printed line promises: %r" % ((code2, text2, held_later),),
          code2 == 2 and not held_later
          and _drive_state(root).get("lock") != "taken")

    # The project a context carries is the manifest's own when no --project-dir
    # was typed: the session's directory may be another checkout.
    M.run_verb = real
    root, mpath = _repo("ctxproj", task_ids=TASKS[:1])
    other = os.path.realpath(_harness.fixture_root("drive-ctxother-"))
    held_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = other
    try:
        ns = argparse.Namespace(project_dir=None, manifest=mpath, verbose=False)
        _m, ctx = M.project_context(ns)
        ns_typed = argparse.Namespace(project_dir=root, manifest=mpath,
                                      verbose=False)
        _m, typed = M.project_context(ns_typed)
    finally:
        if held_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = held_env
    check("dl4 with no --project-dir the context's project is the manifest's own "
          "project, not the session's directory: %r" % (ctx["project"],),
          os.path.realpath(ctx["project"]) == root
          and os.path.realpath(typed["project"]) == root)


def _key_cases(check):
    """`review.perTask` read by the driver, in `reviewer_due` alone: `phase`
    dispatches no per-task reviewer and closes each task `deferred`, `signals`
    dispatches exactly the reviewers its two conditions select."""
    M, why = _load("drive_phase_keys")
    if M is None:
        check("dk1 the driver loads", False, why)
        return
    root, mpath = _repo("phase", per_task="phase")
    run = drive(M, root, mpath, phase_review=False)
    tasks = tasks_of(mpath)
    check("dk1 under `phase` the drive dispatches the executor of each task and "
          "no per-task reviewer - the one reviewer is the phase's, at sign-off - "
          "records each task's gate, and every task it closes records `deferred` "
          "bound to its commit: %r"
          % ((run["steps"], [(t, (tasks.get(t, {}).get("intentCheck") or {})
                                .get("answer")) for t in TASKS]),),
          run["steps"] == [("dispatch", "executor", t) for t in TASKS]
          + [("dispatch", "reviewer", PHASE)]
          and all(_ledger_has_green(root, mpath, t) for t in TASKS)
          and all((tasks.get(t, {}).get("intentCheck") or {}).get("answer")
                  == "deferred"
                  and (tasks.get(t, {}).get("intentCheck") or {}).get("commit")
                  == tasks.get(t, {}).get("commit") for t in TASKS))
    mutant, _w = _load("drive_phase_keys_always_due")
    mutant.reviewer_due = lambda *a, **k: True
    root_m, mpath_m = _repo("phase-mut", task_ids=TASKS[:1], per_task="phase")
    run_m = drive(mutant, root_m, mpath_m, cap=3)
    check("dk1m RED TWIN: a driver whose `reviewer_due` answers yes under every "
          "key dispatches a reviewer under `phase`, and dk1 catches it: %r"
          % (run_m["steps"],),
          ("dispatch", "reviewer", "P1.1") in run_m["steps"])

    signals = {"P1.1": {"redFirst": {"status": "proved",
                                     "basis": "t.py exit 1, its own case"}},
               "P1.2": {},
               "P1.3": {"redFirst": {"status": "proved",
                                     "basis": "t.py exit 1, its own case"},
                        "gates": {"true": "fail"}}}
    root, mpath = _repo("signals", per_task="signals")
    run = drive(M, root, mpath, returns=signals)
    tasks = tasks_of(mpath)
    reviewed = [s[2] for s in run["steps"] if s[:2] == ("dispatch", "reviewer")]
    plain = (tasks.get("P1.1", {}).get("intentCheck") or {})
    check("dk2 under `signals` a reviewer is dispatched exactly where a signal "
          "fires - a red-first proof not `proved` (P1.2), a return whose gates "
          "disagree with the recorded green (P1.3) - and the task with neither "
          "closes `not-asked` with the signals named as its basis: %r"
          % ((reviewed, plain),),
          reviewed == ["P1.2", "P1.3"]
          and plain.get("answer") == "not-asked"
          and "signals" in (plain.get("basis") or "")
          and all(tasks.get(t, {}).get("status") == "done" for t in TASKS))


def _filed_path(mpath, task_id, role="executor"):
    """Where `task_id`'s `role` return for its current start is filed, or None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(mpath)))
    project, config = _evio.project_config_for(mpath, root)
    return _fr.return_path(_evio.evidence_dir(project, config),
                           tasks_of(mpath).get(task_id), role)


def _unjournal_return(root, path):
    """Test-only reset: forget `path` as filed, both the file and the
    `task.return.filed` row the real fix now makes refuse a refiling
    on its own - two sub-cases below reuse ONE start across tries and used to
    rely on the file alone being the whole guard. A real retry gets a new
    start and a new path instead; nothing production runs calls this."""
    if os.path.exists(path):
        os.remove(path)
    import _journal_io
    rel = _output.posix_rel(path, root)
    directory = _journal_io.journal_dir(root)
    for jpath in _journal_io.journal_files(directory):
        with open(jpath, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        kept, changed = [], False
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                kept.append(line)
                continue
            if (isinstance(row, dict)
                    and row.get("action") == _fr.RETURN_FILED_ACTION
                    and row.get("target") == rel):
                changed = True
                continue
            kept.append(line)
        if changed:
            with open(jpath, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(ln + "\n" for ln in kept))


def _started(M, prefix):
    """A one-task repository whose task the driver has started and dispatched."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1])
    with _Env(root):
        said = []
        M.main(["next", PHASE, mpath, "--project-dir", root], out=said.append)
    return root, mpath, "\n".join(said)


def _submit(M, root, mpath, task_id, body, role="executor", tail=()):
    """`(code, text)` of one `submit` with `body` on stdin. With `M` None it is
    the command an agent runs, printed through its terse door; a mutant is
    driven in-process, the one way a replaced function is reached."""
    stdin = body if isinstance(body, str) else json.dumps(body)
    argv = ["submit", task_id, "--role", role, mpath, "--project-dir",
            root] + list(tail)
    with _Env(root):
        if M is None:
            return _verb(root, DRIVER, argv, stdin=stdin)
        said = []
        code = M.main(argv, out=said.append, stdin=stdin)
    return code, "\n".join(said)


def _head(root):
    return _harness.git(root, "rev-parse", "HEAD", prefix=("git",)).strip()


def _stamp_head(line):
    """The HEAD a stamp line names, or None."""
    try:
        return json.loads(str(line).split(":", 1)[1]).get("head")
    except (IndexError, ValueError, AttributeError):
        return None


def _stamp_field(line, key):
    """One field of a stamp line's JSON, or None."""
    try:
        return json.loads(str(line).split(":", 1)[1]).get(key)
    except (IndexError, ValueError, AttributeError):
        return None


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _submit_cases(check):
    """`submit`: the executor's and the reviewer's last act. It takes the stamp,
    runs the red-first helper on a tdd task, and files through the write-once
    verb; each refusal below writes nothing, and its allow twin files."""
    M, why = _load("drive_phase_submit")
    if M is None:
        check("ds1 the driver loads", False, why)
        return

    # A missing stamp: git cannot name the tree, so `take` puts no HEAD in it.
    root, mpath, _t = _started(M, "nostamp")
    _edit(root, "P1.1", "changed\n")
    away = os.path.join(root, ".git-away")
    os.rename(os.path.join(root, ".git"), away)
    try:
        code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    finally:
        os.rename(away, os.path.join(root, ".git"))
    path = _filed_path(mpath, "P1.1")
    check("ds1 a missing stamp is refused: with no tree git can name, submit "
          "exits 1 naming the missing stamp and files nothing: %r" % (text,),
          code == 1 and "stamp is missing" in text
          and path is not None and not os.path.exists(path))
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path) else {}
    check("ds2 THE ALLOW TWIN: the same return on the same task, git back, is "
          "filed with the stamp submit took, naming HEAD, in one line above the "
          "hand-back: %r" % ((code, text, filed.get("stamp")),),
          code == 0 and len(text.splitlines()) == 2
          and "filed" in text.splitlines()[0]
          and str(filed.get("stamp", "")).startswith("audit-stamp:")
          and _head(root).startswith(_stamp_head(filed.get("stamp")) or "-"))
    import _journal_io
    rel = _output.posix_rel(path, root)
    journaled = [r for r in _journal_io.read_all(root)
                if isinstance(r, dict) and r.get("action") == _fr.RETURN_FILED_ACTION]
    check("ds2j a submit appends exactly one task.return.filed row, carrying "
          "the return's own sha256 and the start it answers: %r" % (journaled,),
          len(journaled) == 1 and journaled[0].get("target") == rel
          and journaled[0].get("stateHash") == _journal_io.file_hash(path)
          and (journaled[0].get("details") or {}).get("taskId") == "P1.1")
    first = _read(path) if os.path.exists(path) else None
    code, text = _submit(None, root, mpath, "P1.1", _executor_body(
        "P1.1", {"outcome": {"technical": "resubmitted the same claim a second time",
                             "descriptive": "still the same change as before"}}))
    check("ds3 a second filing is refused before anything runs, and the first "
          "stays byte-identical: %r" % (text,),
          code == 1 and "already filed" in text and "stamp taken" not in text
          and first is not None and _read(path) == first)
    os.remove(path)
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    row_ts = (journaled[0].get("ts") if journaled else None) or "-"
    row_hash = (journaled[0].get("stateHash") if journaled else None) or "-"
    check("a return deleted after filing and submitted again is refused through "
          "refiling_refusal, and the refusal names the journal row of the first "
          "filing (the file is gone, the stop still quotes the row's %s and "
          "stateHash): %r" % (_fr.RETURN_FILED_ACTION, text),
          code == 1 and not os.path.exists(path)
          and "stamp taken" not in text
          and "a %s row already filed this return" % (_fr.RETURN_FILED_ACTION,)
          in text
          and row_ts in text and row_hash in text and row_hash != "-")

    # A malformed return: the shape is checked before anything runs.
    root, mpath, _t = _started(M, "malformed")
    _edit(root, "P1.1", "changed\n")
    bad = _executor_body("P1.1")
    del bad["outcome"]
    code, text = _submit(None, root, mpath, "P1.1", bad)
    code_j, text_j = _submit(None, root, mpath, "P1.1", "{not json")
    path = _filed_path(mpath, "P1.1")
    check("ds4 a malformed return writes nothing: a missing field is named and "
          "refused before the stamp is taken, and text that is not JSON is "
          "refused too: %r" % ((text, text_j),),
          code == 1 and "`outcome`" in text and "stamp taken" not in text
          and code_j == 1 and "does not parse" in text_j
          and not os.path.exists(path))
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    check("ds5 THE ALLOW TWIN: the same task takes the whole return, and files "
          "it: %r" % (text,), code == 0 and os.path.exists(path))

    # A placeholder outcome is refused before the stamp is taken or the
    # red-first helper runs, and the same start takes the corrected return
    # right after - the refusal filed nothing, so nothing blocks the retry.
    root, mpath, _t = _started(M, "placeholder")
    _edit(root, "P1.1", "changed\n")
    path = _filed_path(mpath, "P1.1")
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1", {
        "outcome": {"technical": "placeholder", "descriptive": "placeholder"}}))
    check("ds5p a placeholder outcome is refused by name, before the stamp is "
          "taken, and nothing is written: %r" % (text,),
          code == 1 and "placeholder" in text and "stamp taken" not in text
          and not os.path.exists(path))
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    check("ds5q THE ALLOW TWIN: the same start accepts the corrected return "
          "right after the refusal: %r" % (text,),
          code == 0 and os.path.exists(path))

    # A machine path in any string of a return is refused where it is typed:
    # the filed copy lands in a committed, hash-chained directory, and the
    # writer's own scrub would otherwise rewrite the claim silently. The
    # fixture path is built here, never written out, so no scan of this file
    # reads it as a leak; the user segment is distinctive so an echo is seen.
    leak = "/".join(["", "Users", "zq7user", "dev", "proj", "mod.py"])
    root, mpath, _t = _started(M, "machinepath")
    _edit(root, "P1.1", "changed\n")
    path = _filed_path(mpath, "P1.1")
    dirty = _executor_body("P1.1", {
        "outcome": {"technical": "edited %s and ran it" % (leak,),
                    "descriptive": "mod.py changed"},
        "testsAdded": ["the case that reads %s" % (leak,), "a clean entry"]})
    code, text = _submit(None, root, mpath, "P1.1", dirty)
    check("ds5r a return holding a machine path in a nested string is refused "
          "before the stamp is taken: it names each field that carries one "
          "(outcome.technical, testsAdded[0]) and none that is clean, offers "
          "the remedy, never echoes the path, and writes nothing: %r" % (text,),
          code == 1 and "stamp taken" not in text
          and "outcome.technical" in text and "testsAdded[0]" in text
          and "testsAdded[1]" not in text and "outcome.descriptive" not in text
          and "<home>/" in text and "zq7user" not in text
          and not os.path.exists(path))
    clean = _executor_body("P1.1", {
        "outcome": {"technical": "edited <home>/dev/proj/mod.py and "
                                 "plugins/audit/mod.py and ran it",
                    "descriptive": "mod.py changed"},
        "testsAdded": ["the case that reads <scratchpad>/out.txt"]})
    code, text = _submit(None, root, mpath, "P1.1", clean)
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path) else {}
    check("ds5s THE ALLOW TWIN: the same return spelled with <home>/..., "
          "<scratchpad>/... and a repo-relative path is filed, and those "
          "spellings reach the file as written: %r" % (text,),
          code == 0 and os.path.exists(path)
          and filed.get("outcome", {}).get("technical") ==
          clean["outcome"]["technical"]
          and filed.get("testsAdded") == clean["testsAdded"])
    root, mpath, _t = _started(M, "machinepath-rv")
    described = (tasks_of(mpath).get("P1.1") or {}).get("description") or ""
    rpath = _filed_path(mpath, "P1.1", "reviewer")
    code, text = _submit(None, root, mpath, "P1.1", {
        "findings": [], "verdict": "clean",
        "intent": {"answer": "matches",
                   "note": "as asked: %s (read in %s)" % (described, leak)}},
        role="reviewer")
    check("ds5t a reviewer's return is held to the same rule: a machine path "
          "in intent.note is refused by field and nothing is filed: %r" % (text,),
          code == 1 and "intent.note" in text and "zq7user" not in text
          and (rpath is None or not os.path.exists(rpath)))

    # A tdd task: the red-first block is the helper's.
    plan = _plan(TASKS[:1], ("true",))
    task = plan["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", "tests/test_mine.py"]
    plan["fileIndex"] = dict((f, ["P1.1"]) for f in task["files"])
    task["tests"] = {"mode": "tdd", "add": ["tests/test_mine.py: v is two"],
                     "gate": ["true"], "expectRedFirst": True}
    root, mpath = _repo("tdd", task_ids=TASKS[:1])
    os.makedirs(os.path.join(root, "tests"))
    for rel, text in (("src/mine.py", "v = 1\n"),
                      ("tests/test_mine.py", _house_suite([("old1", "mine.v >= 1")]))):
        with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "tdd")
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root], out=[].append)
    with open(os.path.join(root, "src", "mine.py"), "w", encoding="utf-8") as fh:
        fh.write("v = 2\n")
    with open(os.path.join(root, "tests", "test_mine.py"), "w", encoding="utf-8") as fh:
        fh.write(_house_suite([("old1", "mine.v >= 1"), ("new1", "mine.v == 2")]))
    body = _executor_body("P1.1", {"testsAdded": ["tests/test_mine.py: new1"]})
    del body["redFirst"]
    code, text = _submit(None, root, mpath, "P1.1", body)
    path = _filed_path(mpath, "P1.1")
    check("ds6 a tdd task's submit with no test command is refused, naming the "
          "command it needs, and files nothing: %r" % (text,),
          code == 1 and "after `--`" in text and not os.path.exists(path))
    code, text = _submit(None, root, mpath, "P1.1", body,
                         tail=["--", sys.executable, "tests/test_mine.py"])
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path) else {}
    red = filed.get("redFirst") or {}
    check("ds7 THE ALLOW TWIN: with the command, submit runs the red-first helper "
          "and files its block - `proved`, with the time the helper printed: %r"
          % ((code, text, red),),
          code == 0 and red.get("status") == "proved" and red.get("at")
          and "red-first proved" in text)
    # A stub that read `--selftest` off the whole of argv answered the
    # forwarded command's flag with its own pointer and exit 0.
    _unjournal_return(root, path)
    code, text = _submit(None, root, mpath, "P1.1", body,
                         tail=["--", sys.executable, "tests/test_mine.py",
                               "--selftest"])
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path) else {}
    red = filed.get("redFirst") or {}
    check("ds7f a forwarded test command that carries `--selftest` after `--` "
          "runs: submit files the helper's `proved` block, and the driver's own "
          "pointer is not what answered: %r" % ((code, text, red),),
          code == 0 and red.get("status") == "proved" and "has no inline" not in text)
    code, text = _verb(root, DRIVER, ["--selftest"])
    check("ds7g THE FLAG IS NO LONGER ANSWERED: `--selftest` as the driver's own "
          "argument is an ordinary usage error - exit 2, argparse's own complaint - "
          "and not a pointer to a suite the installed copy does not carry: %r"
          % ((code, text),),
          code == 2 and "has no inline" not in text and "usage:" in text)

    # No --introduces: the helper is handed the symbols the task's diff adds, so
    # a test red on a name that does not exist at HEAD proves instead of grading
    # could-not-prove.
    plan = _plan(TASKS[:1], ("true",))
    task = plan["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", "tests/test_mine.py"]
    plan["fileIndex"] = dict((f, ["P1.1"]) for f in task["files"])
    task["tests"] = {"mode": "tdd", "add": ["tests/test_mine.py: foo is two"],
                     "gate": ["true"], "expectRedFirst": True}
    root, mpath = _repo("introduced", task_ids=TASKS[:1])
    os.makedirs(os.path.join(root, "tests"))
    for rel, text in (("src/mine.py", "v = 1\n"),
                      ("tests/test_mine.py", _house_suite([("old1", "mine.v >= 1")]))):
        with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "tdd")
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root], out=[].append)
    with open(os.path.join(root, "src", "mine.py"), "w", encoding="utf-8") as fh:
        fh.write("v = 1\n\n\ndef foo():\n    return 2\n")
    with open(os.path.join(root, "tests", "test_mine.py"), "w", encoding="utf-8") as fh:
        fh.write(_house_suite([("old1", "mine.v >= 1"), ("new1", "mine.foo() == 2")]))
    body = _executor_body("P1.1", {"testsAdded": ["tests/test_mine.py: new1"]})
    code, text = _submit(None, root, mpath, "P1.1", body,
                         tail=["--", sys.executable, "tests/test_mine.py"])
    path = _filed_path(mpath, "P1.1")
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path or "-") else {}
    red = filed.get("redFirst") or {}
    check("ds7h submit with no --introduces hands the helper the symbols the task's "
          "diff adds: a test red on `foo`, a name HEAD does not have, is `proved`, "
          "and the block is marked as the helper's: %r" % ((code, text, red),),
          code == 0 and red.get("status") == "proved"
          and red.get("source") == _fr.HELPER_SOURCE)

    # The brief prints the manifest relative to the project; the agent's shell
    # may stand elsewhere.
    root, mpath, _t = _started(M, "relative")
    _edit(root, "P1.1", "changed\n")
    elsewhere = os.path.dirname(root)
    with _Env(root):
        done_r = subprocess.run(
            _script(DRIVER) + ["submit", "P1.1", "--role", "executor",
                               os.path.relpath(mpath, root), "--project-dir", root],
            cwd=elsewhere, input=json.dumps(_executor_body("P1.1")),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120)
    path = _filed_path(mpath, "P1.1")
    check("ds9 the manifest a brief prints relative to the project is read from "
          "that project, whatever directory the agent's shell stands in: %r"
          % ((done_r.returncode, done_r.stdout + done_r.stderr),),
          done_r.returncode == 0 and os.path.exists(path)
          and not os.path.exists(os.path.join(elsewhere, "docs", "audit",
                                              "audit-plan.json")))

    # A wave executor stands in its task tree, which holds its own committed
    # copy of the same relative manifest with the task still pending; the
    # filing belongs to the plan of the project it names.
    root, mpath, _t = _started(M, "waveproj")
    _edit(root, "P1.1", "changed\n")
    decoy, dpath = _repo("wavetree", task_ids=TASKS[:1])
    rel = os.path.relpath(mpath, root)
    for label, cwd, want in (("ds9w a relative manifest is read from --project-dir, "
                              "never from the task tree the shell stands in", decoy, True),
                             ("ds9x THE ALLOW TWIN: the shell standing in the "
                              "project itself files the same way", root, True)):
        held_path = _filed_path(mpath, "P1.1")
        if held_path:
            _unjournal_return(root, held_path)
        with _Env(root):
            done_w = subprocess.run(
                _script(DRIVER) + ["submit", "P1.1", "--role", "executor", rel,
                                   "--project-dir", root],
                cwd=cwd, input=json.dumps(_executor_body("P1.1")),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
        check("%s: %r" % (label, (done_w.returncode, done_w.stdout + done_w.stderr)),
              (done_w.returncode == 0) == want
              and os.path.exists(_filed_path(mpath, "P1.1") or "-") == want)
    check("ds9y the decoy tree's own plan was left alone",
          os.path.isfile(dpath) and not os.path.exists(_filed_path(dpath, "P1.1") or "-"))

    # The phase review files through the same door, keyed on its head.
    root, mpath = _repo("phasereturn", task_ids=TASKS[:1], per_task="phase")
    drive(M, root, mpath, phase_review=False)
    done = tasks_of(mpath)["P1.1"]
    entry = {"id": "P1.1", "commit": done.get("commit"), "answer": "matches",
             "note": "as asked", "missing": [], "redFirst": "not-attempted",
             "redFirstBasis": "gate-only", "inheritedTests": "not-asked",
             "inheritedTestsBasis": "the gate is `true` and selects no test file"}
    review = {"findings": [], "intent": {"answer": "matches", "note": "done"},
              "verdict": "clean", "tasks": [entry]}
    head = _head(root)
    # The drive composed this head's phase brief, so the filing carries the
    # set it showed, as its printed command does.
    shown = ["--shown", "P1.1@%s" % (done.get("commit"),)]
    code, text = _submit(None, root, mpath, PHASE, review, role="reviewer",
                         tail=["--head", head] + shown)
    code_2, text_2 = _submit(None, root, mpath, PHASE, review, role="reviewer",
                             tail=["--head", head] + shown)
    check("ds8 a phase review files through submit under --head, and a second "
          "filing for that head is the verb's refusal: %r" % ((text, text_2),),
          code == 0 and "filed" in text and code_2 == 1
          and "already answers P1.1" in text_2)

    # A commit or head spelled as a prefix of the one the plan or git holds is
    # the same commit; the filing keys and records the longer spelling.
    root_p, mpath_p = _repo("phaseprefix", task_ids=TASKS[:1], per_task="phase")
    drive(M, root_p, mpath_p, phase_review=False)
    done_p = tasks_of(mpath_p)["P1.1"]
    recorded = done_p.get("commit") or ""
    whole = _git_out(root_p, "rev-parse", recorded).strip()
    entry_p = dict(entry, commit=whole)
    review_p = {"findings": [], "intent": {"answer": "matches", "note": "done"},
                "verdict": "clean", "tasks": [entry_p]}
    head_p = _head(root_p)
    code_p, text_p = _submit(None, root_p, mpath_p, PHASE, review_p,
                             role="reviewer", tail=["--head", head_p[:12],
                                                    "--shown",
                                                    "P1.1@%s" % (recorded,)])
    project_p, config_p = _evio.project_config_for(mpath_p, root_p)
    filed_p = _fr.phase_returns(_evio.evidence_dir(project_p, config_p), PHASE)
    check("ds8p a phase review whose entry names the whole commit the plan records "
          "in twelve characters, and whose --head is twelve characters of HEAD, "
          "files keyed on the whole head and records the plan's spelling: %r"
          % ((code_p, text_p, [(rel, (body or {}).get("tasks"))
                               for rel, body, _why in filed_p]),),
          len(whole) > len(recorded) and code_p == 0 and "filed" in text_p
          and [rel for rel, _b, _w in filed_p] and all(
              rel.endswith("%s.reviewer.json" % (head_p,))
              and [e.get("commit") for e in body["tasks"]] == [recorded]
              for rel, body, _w in filed_p))
    ambiguous = dict(entry, commit="0" * 12)
    code_q, text_q = _submit(None, root_p, mpath_p, PHASE, dict(
        review_p, tasks=[ambiguous]), role="reviewer",
        tail=["--head", "f" * 12])
    check("ds8q ALLOW: a prefix that is not the recorded commit's is still the "
          "verb's refusal: %r" % ((code_q, text_q),), code_q == 1)

    # The set a phase brief showed reaches the filing verb unchanged: the brief
    # prints it as `--shown` on this command, and the verb records it.
    root_s, mpath_s = _repo("phaseshown", task_ids=TASKS[:1], per_task="phase")
    drive(M, root_s, mpath_s, phase_review=False)
    recorded_s = tasks_of(mpath_s)["P1.1"].get("commit") or ""
    review_s = {"findings": [], "intent": {"answer": "matches", "note": "done"},
                "verdict": "clean",
                "tasks": [dict(entry, commit=recorded_s)]}
    head_s = _head(root_s)
    code_s, text_s = _submit(None, root_s, mpath_s, PHASE, review_s,
                             role="reviewer",
                             tail=["--head", head_s, "--shown",
                                   "P1.1@%s" % (recorded_s,)])
    project_s, config_s = _evio.project_config_for(mpath_s, root_s)
    filed_s = _fr.phase_returns(_evio.evidence_dir(project_s, config_s), PHASE)
    check("ds8s a phase review submitted with `--shown` files a return "
          "recording that set: %r"
          % ((code_s, text_s, [(body or {}).get("shown")
                               for _rel, body, _why in filed_s]),),
          code_s == 0 and recorded_s != "" and len(filed_s) == 1
          and (filed_s[0][1] or {}).get("shown")
          == [{"id": "P1.1", "commit": recorded_s}])

    # The hand-back line is `submit`'s too, so its cases run in this block,
    # reading the phase review's two prints above for the reviewer's half.
    _handback_cases(check, M, ((code, text), (code_2, text_2)))


def _owed_task_repo(M, prefix, expect):
    """A one-task repository whose task is tdd over `src/mine.py` with an EMPTY
    `tests.add` - a fix task born from a finding that named no case - and
    `expectRedFirst` as `expect`, started and its file changed. Only that stored
    field differs between the two repositories a case builds."""
    plan = _plan(TASKS[:1], ("true",))
    task = plan["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py"]
    plan["fileIndex"] = {"src/mine.py": ["P1.1"]}
    task["tests"] = {"mode": "tdd", "add": [], "gate": ["true"],
                     "expectRedFirst": expect}
    root, mpath = _repo(prefix, task_ids=TASKS[:1])
    _write_lf(os.path.join(root, "src", "mine.py"), "v = 1\n")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "tdd fix task")
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root], out=[].append)
    _write_lf(os.path.join(root, "src", "mine.py"), "v = 2\n")
    return root, mpath


def _owed_red_first_cases(check):
    """Every reader of a fix task's red-first obligation asks the stored
    `expectRedFirst` beside the mode: `submit`, the writer path's command and
    block, and the fix prompt. Each case pairs a task with the field false and a
    twin with it true - same mode, same empty `tests.add`, same gate."""
    M, why = _load("drive_phase_owed_red_first")
    if M is None:
        check("ow1 the driver loads", False, why)
        return
    root, mpath = _owed_task_repo(M, "ow-false", False)
    body = _executor_body("P1.1", {"testsAdded": []})
    del body["redFirst"]
    code, text = _submit(None, root, mpath, "P1.1", body)
    path = _filed_path(mpath, "P1.1")
    filed = json.loads(_read(path).decode("utf-8")) if path and os.path.exists(path) else {}
    red = filed.get("redFirst") or {}
    check("ow1 a tdd task whose stored expectRedFirst is false submits with no "
          "command after `--`: it is filed, red-first not-attempted, the basis "
          "naming the field and saying nothing is owed, and no helper mark on "
          "it: %r" % ((code, text, red),),
          code == 0 and red.get("status") == "not-attempted"
          and "expectRedFirst" in str(red.get("basis")) and red.get("at")
          and "source" not in red and "after `--`" not in text)
    root, mpath = _owed_task_repo(M, "ow-typed", False)
    code, text = _submit(None, root, mpath, "P1.1", _executor_body(
        "P1.1", {"testsAdded": [], "redFirst": {
            "status": "proved", "basis": "typed, no helper ran", "at": "z"}}))
    path = _filed_path(mpath, "P1.1")
    filed = json.loads(_read(path).decode("utf-8")) if path and os.path.exists(path) else {}
    check("ow2 a `proved` the agent typed on such a task is not what is filed: "
          "no helper ran, so the driver's not-attempted block replaces it: %r"
          % ((code, filed.get("redFirst")),),
          code == 0 and (filed.get("redFirst") or {}).get("status") == "not-attempted")
    root, mpath = _owed_task_repo(M, "ow-true", True)
    body = _executor_body("P1.1", {"testsAdded": []})
    del body["redFirst"]
    code, text = _submit(None, root, mpath, "P1.1", body)
    path = _filed_path(mpath, "P1.1")
    check("ow3 THE TWIN: the same task with expectRedFirst true is still "
          "refused without a command, naming it, and files nothing - the mutant "
          "that stops asking at all goes red here: %r" % (text,),
          code == 1 and "after `--`" in text and path is not None
          and not os.path.exists(path))

    unowed = {"id": "P1.1", "tests": {"mode": "tdd", "add": [],
                                      "expectRedFirst": False, "gate": []}}
    owed = {"id": "P1.1", "tests": {"mode": "tdd", "add": [],
                                    "expectRedFirst": True, "gate": []}}
    got = (M.writer_test_command({}, {}, unowed), M.writer_test_command({}, {}, owed))
    check("ow4 the writer path derives no command and no could-not-prove basis "
          "for the unowed task, and keeps its basis for the owed twin: %r" % (got,),
          got[0] == (None, None) and got[1][0] is None
          and isinstance(got[1][1], str) and "no file" in got[1][1])
    blocks = (M.unowed_red_first(unowed), M.unowed_red_first(owed),
              M.unowed_red_first({"id": "P1.2", "tests": {
                  "mode": "regression", "add": [], "expectRedFirst": False}}))
    check("ow5 the not-attempted block says why: the field for a tdd task, the "
          "mode for another, and none for a task that owes the proof: %r" % (blocks,),
          blocks[0].get("status") == "not-attempted"
          and "expectRedFirst" in blocks[0].get("basis", "")
          and blocks[1] is None
          and "regression" in blocks[2].get("basis", ""))
    check("ow6 the fix prompt asks for a case that fails at HEAD only of a task "
          "that owes a red-first proof: %r" % ((M.fix_prove_lines(unowed),
                                               M.fix_prove_lines(owed)),),
          M.fix_prove_lines(unowed) == [] and len(M.fix_prove_lines(owed)) == 1)


def _submit_mutant_cases(check):
    """Each refusal of `submit`, red against a driver with that refusal taken
    out. In-process, the one way a replaced function is reached, and after the
    real cases, so a driver that cannot be driven in-process stops only these."""
    mutant, _w = _load("drive_phase_submit_any_stamp")
    mutant.take_stamp = lambda ctx, task: ("audit-stamp: {}", None)
    root_m, mpath_m, _t = _started(mutant, "anystamp")
    os.rename(os.path.join(root_m, ".git"), os.path.join(root_m, ".git-away"))
    try:
        code_m, text_m = _submit(mutant, root_m, mpath_m, "P1.1",
                                 _executor_body("P1.1"))
    finally:
        os.rename(os.path.join(root_m, ".git-away"), os.path.join(root_m, ".git"))
    path_m = _filed_path(mpath_m, "P1.1")
    check("ds1m RED TWIN: a submit that files whatever the take printed files a "
          "claim bound to no tree, and ds1 catches it: %r" % ((code_m, text_m),),
          code_m == 0 and os.path.exists(path_m))

    mutant, _w = _load("drive_phase_submit_no_early")
    mutant.already_filed = lambda ctx, task: None
    root, mpath, _t = _started(mutant, "noearly")
    _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    path = _filed_path(mpath, "P1.1")
    first = _read(path) if os.path.exists(path) else None
    code_m, text_m = _submit(mutant, root, mpath, "P1.1", _executor_body("P1.1"))
    check("ds3m RED TWIN: a submit that does not look for the filed return first "
          "takes a stamp before the filing verb refuses, and ds3 catches it - the "
          "first still stays as filed, so the refusal itself is the verb's: %r"
          % (text_m,),
          code_m == 1 and "stamp taken" in text_m and first is not None
          and _read(path) == first)

    mutant, _w = _load("drive_phase_submit_no_shape")
    mutant.submitted_shape = lambda role, body, fills, task=None: []
    root_m, mpath_m, _t = _started(mutant, "noshape")
    bad = _executor_body("P1.1")
    del bad["outcome"]
    code_m, text_m = _submit(mutant, root_m, mpath_m, "P1.1", bad)
    check("ds4m RED TWIN: a submit that does not check the shape first takes the "
          "stamp before the filing verb refuses, and ds4 catches it: %r"
          % (text_m,),
          code_m == 1 and "stamp taken" in text_m)
    _stdin_bytes_case(check)


def _windows_text_run(real, received):
    """`subprocess.run` as Windows runs it in text mode, for a POSIX host: a
    str `input` reaches the child through a text wrapper that writes every
    "\\n" as "\\r\\n", and the captured output is decoded and newline-translated
    back. Bytes in, bytes out, untouched. Each input the child got is kept on
    `received`, as the bytes it got."""
    def run(*args, **kw):
        text = bool(kw.pop("text", False))
        text = bool(kw.pop("universal_newlines", False)) or text
        encoding = kw.pop("encoding", None)
        errors = kw.pop("errors", None)
        text = text or encoding is not None or errors is not None
        encoding, errors = encoding or "utf-8", errors or "strict"
        data = kw.pop("input", None)
        if text and isinstance(data, str):
            data = data.replace("\n", "\r\n").encode(encoding, errors)
        received.append(data)
        done = real(*args, input=data, **kw)
        if text:
            for name in ("stdout", "stderr"):
                raw = getattr(done, name)
                if isinstance(raw, bytes):
                    setattr(done, name, raw.decode(encoding, errors)
                            .replace("\r\n", "\n").replace("\r", "\n"))
        return done
    return run


def _stdin_bytes_case(check):
    """A return filed through `submit` goes to `file-return` on its stdin, and
    the driver's own copy of `subprocess` here translates the way Windows' text
    wrapper does, so a POSIX run sees what a Windows run files."""
    M, why = _load("drive_phase_windows_stdin")
    label = ("tests/test_drive_phase.py: a verb's stdin reaches "
             "it as the exact UTF-8 bytes it was given, with no newline "
             "translation, so a return filed through submit is byte-identical "
             "on every platform (%r)")
    if M is None:
        check(label % (why,), False)
        return
    import types
    received = []
    stand_in = types.ModuleType("subprocess")
    stand_in.__dict__.update(vars(subprocess))
    stand_in.run = _windows_text_run(subprocess.run, received)
    M.subprocess = stand_in
    root, mpath, _t = _started(M, "winstdin")
    try:
        _edit(root, "P1.1", "changed\n")
        code, text = _submit(M, root, mpath, "P1.1", _executor_body("P1.1"))
        path = _filed_path(mpath, "P1.1")
        filed = _read(path) if path and os.path.exists(path) else b""
        given = [d for d in received if d is not None and b'"stamp"' in d]
        check(label % ((code, text, filed[:80], [d[:80] for d in given]),),
              code == 0 and filed.count(b"\n") > 1 and b"\r" not in filed
              and len(given) == 1 and isinstance(given[0], bytes)
              and b"\r" not in given[0] and given[0].count(b"\n") > 1)
    finally:
        _harness.remove_tree(root)


def _handback_lines(M):
    """`(filed, refused)` - the two hand-back instructions the driver prints as
    `submit`'s last line, or None for one the driver does not define."""
    steps = getattr(M, "STEPS", {}) or {}
    return tuple((steps.get(name) or {}).get("line")
                 for name in ("handback-filed", "handback-refused"))


def _ends_with(text, line):
    lines = text.rstrip("\n").splitlines()
    return bool(line) and bool(lines) and lines[-1] == line


def _handback_cases(check, M, phase_prints):
    """`submit`'s last printed line is what the agent hands back: after a filing,
    the instruction to hand back the filed line above it as the whole reply;
    after a refusal, the instruction to hand back the refusal verbatim. The agent
    reads the print last, so the instruction lives there and not in its prompt.
    `phase_prints` is a phase review's `(code, text)` filed, then refused."""
    filed_line, refused_line = _handback_lines(M)

    root, mpath, _t = _started(M, "handback")
    _edit(root, "P1.1", "changed\n")
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    lines = text.rstrip("\n").splitlines()
    check("dh1 a filed executor return prints the filed line, then the hand-back "
          "instruction as the last line; the filed line occurs once and the "
          "whole print keeps the bound: %r" % ((code, text, filed_line),),
          code == 0 and _ends_with(text, filed_line) and len(lines) == 2
          and "P1.1 executor return filed" in lines[0]
          and text.count("return filed") == 1
          and len(text.encode("utf-8")) <= BOUND)

    # The refusal twin, against the same driver: a second filing is refused.
    code, text = _submit(None, root, mpath, "P1.1", _executor_body("P1.1"))
    check("dh2 THE REFUSAL TWIN: a refused submit prints the refusal and, as its "
          "last line, the instruction to hand it back verbatim - never the filed "
          "line nor the filing's instruction: %r" % ((code, text, refused_line),),
          code == 1 and _ends_with(text, refused_line) and "already filed" in text
          and "return filed" not in text
          and (filed_line or "-") not in text)

    root, mpath, _t = _started(M, "handbackshape")
    _edit(root, "P1.1", "changed\n")
    bad = _executor_body("P1.1")
    del bad["outcome"]
    code, text = _submit(None, root, mpath, "P1.1", bad)
    code_n, text_n = _submit(None, root, mpath, "P9.9", _executor_body("P9.9"))
    check("dh3 every refusal ends on the same instruction - a malformed return, "
          "and an id the plan does not hold: %r" % ((text, text_n),),
          code == 1 and _ends_with(text, refused_line) and "`outcome`" in text
          and code_n == 2 and _ends_with(text_n, refused_line)
          and "P9.9" in text_n)

    check("dh4 the two instructions differ, and only the refusal's says "
          "verbatim: %r" % ((filed_line, refused_line),),
          bool(filed_line) and bool(refused_line) and filed_line != refused_line
          and "verbatim" in refused_line and "verbatim" not in filed_line)

    # The phase reviewer files through `submit --head` and reads the same print.
    (code, text), (code_2, text_2) = phase_prints
    check("dh5 the phase reviewer's submit --head ends on the same instructions: "
          "the filing's after it files, the refusal's after the second: %r"
          % ((text, text_2),),
          code == 0 and _ends_with(text, filed_line)
          and text.count("return filed") == 1
          and code_2 == 1 and _ends_with(text_2, refused_line)
          and "return filed" not in text_2)

    # The prompts no longer carry the sentence the print now carries.
    agents = os.path.join(_output.PLUGIN_ROOT, "agents")
    said = {}
    for name in ("audit-executor.md", "audit-reviewer.md"):
        with open(os.path.join(agents, name), "r", encoding="utf-8") as fh:
            said[name] = " ".join(fh.read().split()).lower()
    left = dict((name, text.count("hand back")) for name, text in said.items())
    check("dh6 neither agent's prompt states the hand-back itself, since "
          "submit's last line carries it: %r" % (left,),
          all(n == 0 for n in left.values())
          and all("drive-phase.py submit" in t for t in said.values()))


# --- sign-off -------------------------------------------------------------------
FINDINGS = [{"severity": "med", "file": "src/f1.txt:1", "issue": "f1 says too little",
             "resolution": "say what changed"},
            {"severity": "low", "file": "src/f2.txt", "issue": "f2 has no newline",
             "resolution": "end it with one"},
            {"severity": "low", "file": "src/f3.txt", "issue": "f3 repeats f2",
             "resolution": "leave it"}]


def _phase_of(mpath):
    return [p for p in _mio.load_manifest(mpath)["phases"] if p["id"] == PHASE][0]


def _signoff_steps(run):
    """The instructions printed after the last task's executor dispatch."""
    steps = run["steps"]
    last = max(i for i, s in enumerate(steps) if s[:2] == ("dispatch", "executor"))
    return steps[last + 1:]


def _git_out(root, *args):
    # git writes UTF-8 whatever the locale: decoded in the locale's, a file
    # carrying an arrow raises in the reader thread, and on Windows the run
    # then hands back no output at all rather than an error.
    return subprocess.run(_GIT + list(args), cwd=root, capture_output=True,
                          encoding="utf-8", errors="replace").stdout


def _counting(module):
    """Wrap `module.run_verb` so each verb it runs is counted by its words:
    `{(script, first argument): calls}`."""
    seen = {}
    real = module.run_verb

    def counted(ctx, script, args, stdin=None):
        key = (script, (list(args) or [""])[0])
        seen[key] = seen.get(key, 0) + 1
        return real(ctx, script, args, stdin=stdin)
    module.run_verb = counted
    return seen


def _signoff_cases(check):
    """Sign-off as one step: the phase review's dispatch, one triage decision,
    then the gate, the invariants, the sign-off verb, the commit, the landing
    and the lock release, run by one `next`."""
    M, why = _load("drive_phase_signoff")
    if M is None:
        check("sg1 the driver loads", False, why)
        return
    root, mpath = _repo("signoff", per_task="phase")
    run = drive(M, root, mpath)
    tail = _signoff_steps(run)
    phase = _phase_of(mpath)
    check("sg1 under `phase` the model-facing steps of sign-off are the phase "
          "review's dispatch, the triage decision and the final step: %r"
          % (tail,),
          tail == [("dispatch", "reviewer", PHASE), TRIAGE, DONE])
    tasks = tasks_of(mpath)
    plan_dirt = _git_out(root, "status", "--porcelain", "--", "docs").strip()
    check("sg2 the final step signed the phase off with the triage's summary, "
          "the phase review's answers reached every task, the sign-off is "
          "committed with the plan clean in git, and the drive left no lock and "
          "no state: %r"
          % (((phase.get("review") or {}).get("status"), phase.get("summary"),
              [(t, (tasks[t].get("intentCheck") or {}).get("answer"))
               for t in TASKS], plan_dirt, run["prints"][-1][1]),),
          (phase.get("review") or {}).get("status") == "passed"
          and phase.get("summary") == SUMMARY
          and all((tasks[t].get("intentCheck") or {}).get("answer") == "matches"
                  for t in TASKS)
          and plan_dirt == ""
          and "chore(audit-state): phase P1 - sign-off" in _git_out(
              root, "log", "--format=%s")
          and not os.path.exists(os.path.join(root, ".claude", "state", "drive"))
          and "phase-%s" % (PHASE,) not in _verb(
              root, "audit-lock.py", ["status", "--project", root])[1])

    # A red phase gate: every task's gate is green, the phase's is not.
    def red_gate(module, prefix):
        root, mpath = _repo(prefix, task_ids=TASKS[:1], phase_gate=("false",))
        seen = _counting(module)
        return root, mpath, drive(module, root, mpath), seen
    root, mpath, run, seen = red_gate(M, "redgate")
    code, text = run["prints"][-1]
    phase = _phase_of(mpath)
    check("sg3 a red phase gate stops the step before the sign-off verb: exit 1, "
          "the stop names the gate, `audit-task.py signoff` never ran, and the "
          "phase records no verdict and no summary: %r"
          % ((code, seen.get(("audit-task.py", "signoff")),
              (phase.get("review") or {}).get("status"), phase.get("summary"),
              text[:300]),),
          code == 1 and run["steps"][-1] == ("none", None, None)
          and "phase gate is red" in text
          and not seen.get(("audit-task.py", "signoff"))
          and (phase.get("review") or {}).get("status") not in ("passed",
                                                                 "skipped")
          and not phase.get("summary"))
    with _Env(root):
        said = []
        again = M.main(["next", PHASE, mpath, "--project-dir", root],
                       out=said.append)
    check("sg3b ...and the next `next` prints the triage again, so the step is "
          "answered afresh once the gate is fixed: %r" % ("\n".join(said)[:200],),
          again == 0 and instruction("\n".join(said)) == TRIAGE)
    mutant, _w = _load("drive_phase_signoff_no_gate")
    # A driver with no phase gate to replace has no gate step at all, and the
    # mutant is that driver unchanged - its own call count is still the reading.
    real_gate = getattr(mutant, "phase_gate", None)
    if real_gate is not None:
        mutant.phase_gate = lambda ctx, phase: (0,) + tuple(
            real_gate(ctx, phase)[1:])
    _r, mpath_m, run_m, seen_m = red_gate(mutant, "redgate-mut")
    check("sg3m RED TWIN: a driver that reads the red phase gate as green goes "
          "on to the sign-off verb, and sg3's count of its calls catches it: %r"
          % (seen_m.get(("audit-task.py", "signoff")),),
          seen_m.get(("audit-task.py", "signoff"), 0) >= 1)


def _signoff_findings_cases(check):
    """Sign-off over a phase review with several findings, and the fix one of
    them is driven through - a block of its own, built from its own repository."""
    # A phase review with several findings: recorded in one call, triaged once.
    root, mpath = _repo("findings", per_task="phase")
    M2, _w = _load("drive_phase_signoff_count")
    seen = _counting(M2)
    run = drive(M2, root, mpath, findings=FINDINGS, answer=None)
    recorded = (_phase_of(mpath).get("review") or {}).get("findings") or []
    triage = run["prints"][-1][1]
    calls = seen.get(("audit-task.py", "finding"), 0)
    check("sg4 a phase review of several findings records all of them in ONE "
          "`finding` call, before the triage: %d call(s), %r"
          % (calls, [f.get("id") for f in recorded]),
          calls == 1 and [f.get("id") for f in recorded]
          == ["P1-R1", "P1-R2", "P1-R3"]
          and run["steps"][-1] == TRIAGE)
    lines = triage.splitlines()
    bound = getattr(M2, "TRIAGE_LINE_BYTES", 0)
    check("sg5 the triage lists each finding with its options, and a fix task's "
          "predicted price with its basis, every line inside %d bytes: %r"
          % (bound, lines),
          all(any(fid in ln for ln in lines)
              for fid in ("P1-R1", "P1-R2", "P1-R3"))
          and "--fix" in triage and "sign-off" in triage
          and "predicted" in triage and "benchmark" in triage
          and all(len(ln.encode("utf-8")) <= bound for ln in lines))
    mutant, _w = _load("drive_phase_signoff_each")
    seen_m = _counting(mutant)
    real_record = getattr(mutant, "record_findings", None)
    if real_record is not None:
        mutant.record_findings = lambda ctx, phase, found: [
            real_record(ctx, phase, [one]) for one in found][-1]
    root_m, mpath_m = _repo("findings-mut", task_ids=TASKS[:1], per_task="phase")
    drive(mutant, root_m, mpath_m, findings=FINDINGS, answer=None)
    check("sg4m RED TWIN: a driver that records each finding with its own call "
          "makes one call per finding, and sg4's count catches it: %r"
          % (seen_m.get(("audit-task.py", "finding")),),
          seen_m.get(("audit-task.py", "finding"), 0) == len(FINDINGS))

    # Fix one finding: a task added with --fixes, driven, then the triage again.
    answers = iter([["--answer", "fix", "--fix", "P1-R1"],
                    ["--answer", "sign-off", "--reason", SUMMARY]])
    with _Env(root):
        said = []
        M2.main(["next", PHASE, mpath, "--project-dir", root, "--answer",
                 "bogus"], out=said.append)
    run = drive(M2, root, mpath, answer=lambda kind, text: next(answers, None))
    tasks = tasks_of(mpath)
    fix = [t for t in tasks.values() if t.get("fixes") == ["P1-R1"]]
    found = dict((f.get("id"), f) for f in (_phase_of(mpath).get("review") or {})
                 .get("findings") or [])
    triages = [t for (_c, t), s in zip(run["prints"], run["steps"]) if s == TRIAGE]
    check("sg6 a fix task from a finding is added with --fixes, driven like any "
          "task, and the triage then lists only what is still open before the "
          "phase signs off: %r"
          % ((run["steps"], [t.get("id") for t in fix],
              (found.get("P1-R1") or {}).get("fixTask")),),
          len(fix) == 1 and fix[0].get("status") == "done"
          and (found.get("P1-R1") or {}).get("fixTask") == fix[0].get("id")
          and ("dispatch", "executor", fix[0].get("id")) in run["steps"]
          and len(triages) == 2 and "P1-R1" in triages[0]
          and "P1-R1" not in triages[1] and "P1-R2" in triages[1]
          and run["steps"][-1] == DONE
          and (_phase_of(mpath).get("review") or {}).get("status") == "passed")
    summary = _phase_of(mpath).get("summary") or ""
    fix_id = fix[0].get("id") if fix else "-"
    check("sf4 a phase signed off over a fix task closed after the review's head "
          "records that in its summary: the fix's own diff went unreviewed, by "
          "name, beside the summary given: %r" % (summary,),
          summary.startswith(SUMMARY) and fix_id in summary
          and "unreviewed" in summary)
    events = getattr(M2, "did_events", None)
    got = events("\n".join(t for _c, t in run["prints"])) if events else None
    check("dw1 the driver's did-lines carry stable words for a fix task added, the "
          "phase signed off, landed and the lock released, and `did_events` reads "
          "them back - what stream-cost reads a driven sign-off's spans from: %r"
          % (got,),
          bool(got) and got.get("added") == [fix_id] and got.get("signedOff")
          and got.get("landed") and got.get("released"))
    quiet = events("\n".join(t for _c, t in run["prints"][:1])) if events else None
    check("dw2 THE OVER-FIRE TWIN: a print from before any of those happened reads "
          "none of them - a reader that answered yes to every print would put the "
          "whole session in the close: %r" % (quiet,),
          bool(quiet) is True and quiet.get("added") == []
          and not quiet.get("signedOff") and not quiet.get("landed")
          and not quiet.get("released"))


# The call the phase reviewer's dispatch prints to send after it, and what the
# drive says when that call meets a triage with more than one answer.
ADVANCE = ["--answer", "sign-off", "--reason", SUMMARY]
ADVANCE_CALL = "next %s --answer sign-off --reason <the summary>" % (PHASE,)
NOT_APPLIED = "sign-off answered in advance, not applied"


def _at_phase_review(M, prefix):
    """A one-task phase under `phase`, driven to the phase reviewer's dispatch
    and no further: `(root, mpath, the dispatch's print)`."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    run = drive(M, root, mpath, phase_review=False)
    return root, mpath, run["prints"][-1][1]


def _advance_over_fix_after(M):
    """A clean phase review filed at head H, then a finding recorded and a fix
    task for it added and closed after H, the triage that close printed taken
    back out of the driver's state - so the advance call meets the triage
    afresh, with only the fix task's unreviewed diff to tell it apart from a
    clean one. `(code, text, signoff calls, signed)` of that call."""
    root, mpath, text = _at_phase_review(M, "advance-fixafter")
    _file_phase_review(root, mpath, text)
    _verb(root, "audit-task.py", [
        "finding", PHASE, mpath, "--project-dir", root, "--findings-file", "-"],
        stdin=json.dumps(FINDINGS[:1]))
    _verb(root, "audit-task.py", [
        "add", "fix P1-R1", mpath, "--project-dir", root, "--phase", PHASE,
        "--fixes", "P1-R1", "--files", "src/f1.txt", "--description",
        "say what changed", "--gate", "true", "--json"])
    drive(M, root, mpath, answer=None)
    path = os.path.join(root, ".claude", "state", "drive", "%s.json" % (PHASE,))
    state = _drive_state(root)
    state.pop("pending", None)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    seen = _counting(M)
    code, out = _next(M, root, mpath, *ADVANCE)
    return code, out, seen.get(("audit-task.py", "signoff"), 0), _signed(mpath)


def _advance_signoff_cases(check):
    """A clean phase review answered in advance: the dispatch prints the call
    to send after it, and that one call signs off when the triage it would
    print has `sign-off` as its only admissible answer. With a finding open or
    an answer waiting on a human, the same call prints the triage instead."""
    M, why = _load("drive_phase_advance")
    if M is None:
        check("sq1 the driver loads", False, why)
        return
    root, mpath = _repo("advance", task_ids=TASKS[:1], per_task="phase")
    early, early_text = _next(M, root, mpath, *ADVANCE)
    run = drive(M, root, mpath, phase_review=False)
    text = run["prints"][-1][1]
    check("sq0 mid-phase, with no decision pending and a task still open, the "
          "same call is refused as it always was - an advance answer exists "
          "only once every task is closed: %r" % ((early, early_text),),
          early == M.E_USAGE and "no decision is pending" in early_text)
    calls = [ln for ln in text.splitlines() if ADVANCE_CALL in ln]
    check("sq1 the phase reviewer's dispatch prints, once, the call to send "
          "after the reviewer files, inside the print bound: %r" % (text,),
          run["steps"][-1] == ("dispatch", "reviewer", PHASE)
          and len(calls) == 1 and len(text.encode("utf-8")) <= BOUND)
    _file_phase_review(root, mpath, text)
    seen = _counting(M)
    code, out = _next(M, root, mpath, *ADVANCE)
    phase = _phase_of(mpath)
    did = M.did_events(out)
    check("sq2 a clean review answered in advance signs off in that one call: "
          "exit 0, `done`, the sign-off verb ran once, the summary is the one "
          "given, and its did-line says signed off, landed and released - the "
          "words stream-cost places the close by: %r"
          % ((code, out, seen.get(("audit-task.py", "signoff")),
              phase.get("summary")),),
          code == 0 and instruction(out) == DONE
          and seen.get(("audit-task.py", "signoff")) == 1
          and _signed(mpath) and phase.get("summary") == SUMMARY
          and did["signedOff"] and did["landed"] and did["released"]
          and NOT_APPLIED not in out)


def _advance_refused(module, prefix, **filing):
    """A one-task phase review filed with `filing`, then the advance call:
    `(code, print, signoff calls, signed)`."""
    root, mpath, text = _at_phase_review(module, prefix)
    _file_phase_review(root, mpath, text, **filing)
    seen = _counting(module)
    code, out = _next(module, root, mpath, *ADVANCE)
    return code, out, seen.get(("audit-task.py", "signoff"), 0), \
        _signed(mpath)


def _advance_refused_cases(check):
    """The advance call where the triage has more than `sign-off` to offer: it
    prints the triage and applies nothing, and each refusal has its red twin."""
    M, why = _load("drive_phase_advance_refused")
    if M is None:
        check("sq3 the driver loads", False, why)
        return
    refused = _advance_refused
    for label, prefix, filing in (
            ("sq3 with a finding open", "advance-finding",
             {"findings": FINDINGS[:1]}),
            ("sq4 with an answer waiting on a human", "advance-answer",
             {"entry_over": {"P1.1": {"answer": "diverges",
                                      "note": "it edits f2, not f1"}}})):
        code, out, ran, signed = refused(M, prefix, **filing)
        check("%s, the same call prints the triage, says the answer was not "
              "applied, and runs no sign-off: %r" % (label, (code, out, ran)),
              code == 0 and instruction(out) == TRIAGE and NOT_APPLIED in out
              and ran == 0 and not signed)
    code, out, ran, signed = _advance_over_fix_after(M)
    check("sq5 with a clean review whose head precedes a closed fix task - a "
          "diff no review saw - the same call prints the triage, says the "
          "answer was not applied, and runs no sign-off: %r" % ((code, out, ran),),
          code == 0 and instruction(out) == TRIAGE and NOT_APPLIED in out
          and "re-review" in out and ran == 0 and not signed)
    mutant, _w = _load("drive_phase_advance_always")
    if getattr(mutant, "advance_applies", None) is not None:
        mutant.advance_applies = lambda review, pending: True
    _c, _o, ran_m, signed_m = refused(mutant, "advance-mut",
                                      findings=FINDINGS[:1])
    check("sq3m RED TWIN: a driver that applies the advance answer over an open "
          "finding signs the phase off, and sq3's count catches it: %r"
          % ((ran_m, signed_m),),
          # The driver hands the verb the answer's reason as the disposition,
          # so the verb's own refusal is not the defence here: sq3's refusal
          # in the driver is the only line that stops this sign-off.
          ran_m == 1 and signed_m)
    if getattr(mutant, "advance_admissible", None) is not None:
        mutant.advance_admissible = lambda phase: True
    root_m, mpath_m = _repo("advance-early-mut", task_ids=TASKS[:1],
                            per_task="phase")
    early_m, _t = _next(mutant, root_m, mpath_m, *ADVANCE)
    check("sq0m RED TWIN: a driver that takes the advance answer while a task is "
          "still open accepts sq0's call rather than refusing it: exit %r"
          % (early_m,), early_m == 0)


# --- what a human decides before the landing ----------------------------------
def _next(M, root, mpath, *extra):
    """`(code, text)` of one `next` with `extra` flags."""
    with _Env(root):
        said = []
        code = M.main(["next", PHASE, mpath, "--project-dir", root] + list(extra),
                      out=said.append)
    return code, "\n".join(said)


def _stop_at_other(kind, text):
    """Sign the triage off; stop at any other decision for the case to read."""
    if kind[1] == "triage":
        return ["--answer", "sign-off", "--reason", SUMMARY]
    return False


def _signed(mpath):
    return (_phase_of(mpath).get("review") or {}).get("status") in ("passed",
                                                                    "skipped")


def _commit_plan(root, mpath, edit, message):
    """Apply `edit(plan)` to the fixture's plan and commit it."""
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    edit(plan)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "commit", "-qam", message)


def _answer_lines(text):
    """The triage lines that put a reviewer's answer to a human."""
    return [ln for ln in text.splitlines()
            if ln.startswith("  ") and ln.rstrip().endswith("[accept]")]


def _review_answer_cases(check):
    """Under `phase`, the phase review's per-task answers and its phase-level
    intent reach a human before the landing: a `diverges`, `cannot-tell` or
    red-first `not-proved` is a triage line, and sign-off waits until a human
    accepts them with a reason the summary keeps."""
    M, why = _load("drive_phase_answers")
    if M is None:
        check("sa1 the driver loads", False, why)
        return
    root, mpath = _repo("answers", task_ids=TASKS[:2], per_task="phase")
    over = {"P1.1": {"answer": "diverges", "note": "it edits f2, not f1"},
            "P1.2": {"redFirst": "not-proved",
                     "redFirstBasis": "the basis names no failing case"}}
    run = drive(M, root, mpath, entry_over=over, phase_intent="cannot-tell",
                answer=None)
    triage = run["prints"][-1][1]
    lines = _answer_lines(triage)
    check("sa1 a phase review whose findings are empty but whose answers say "
          "P1.1 diverges, P1.2's red-first is not proved and the phase intent "
          "cannot tell prints one triage line for each, beside no finding: %r"
          % (lines,),
          run["steps"][-1] == TRIAGE and len(lines) == 3
          and any("P1.1" in ln and "diverges" in ln for ln in lines)
          and any("P1.2" in ln and "not-proved" in ln for ln in lines)
          and any("phase" in ln and "cannot-tell" in ln for ln in lines)
          and all(len(ln.encode("utf-8")) <= M.TRIAGE_LINE_BYTES
                  for ln in triage.splitlines()))
    check("sa1m the state the driver wrote on dispatching the phase review is "
          "one `_filed_returns.review_marked` reads as marked - the reading the "
          "sign-off verb's remedy rests on: %r" % (sorted(_drive_state(root)),),
          _fr.review_marked(_drive_state(root)))
    code, text = _next(M, root, mpath, "--answer", "sign-off", "--reason", SUMMARY)
    check("sa2 sign-off is refused while those answers wait on a human, and "
          "nothing is signed off: %r" % ((code, text),),
          code == M.E_USAGE and "accept" in text and not _signed(mpath))
    bare, _t = _next(M, root, mpath, "--answer", "accept")
    words = "the human: P1.1 was asked to edit f2 after all"
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    after = _answer_lines(text)
    held = _drive_state(root).get(_fr.SETTLED_FIELD) or {}
    filed = _fr.phase_returns(os.path.join(root, "docs", "audit", "evidence"),
                              PHASE)
    want = [{"key": a["key"], "sha256": a["sha256"]}
            for a in _fr.needs_human(filed)]
    check("sa3s the accept records each settled answer's key beside the "
          "signature of the return it sits in - the content the human "
          "settled - and keeps the key list an older reader reads: %r"
          % (held,),
          len(want) == 3 and held.get(_fr.SIGNATURES_FIELD) == want
          and held.get("keys") == [w["key"] for w in want])
    code_s, text_s = _next(M, root, mpath, "--answer", "sign-off", "--reason",
                           SUMMARY)
    summary = _phase_of(mpath).get("summary") or ""
    check("sa3 accept needs a reason; given one, the triage is printed again "
          "with the answers settled, sign-off then lands, and the summary keeps "
          "the human's words: %r" % ((bare, code, after, code_s, summary),),
          bare == M.E_USAGE and code == 0
          and instruction(text) == TRIAGE and after == []
          and code_s == 0 and instruction(text_s) == DONE
          and summary.startswith(SUMMARY) and words in summary)
    # The over-fire twin: a review that answers `matches` everywhere puts
    # nothing to a human. A triage that listed every entry would make every
    # phase stop for an `accept`, and only this case says so.
    root, mpath = _repo("answers-ok", task_ids=TASKS[:1], per_task="phase")
    run = drive(M, root, mpath, answer=None)
    triage = run["prints"][-1][1]
    check("sa4 THE OVER-FIRE TWIN: a review answering `matches` everywhere puts "
          "no answer line and no `accept` in the triage: %r" % (triage,),
          run["steps"][-1] == TRIAGE and _answer_lines(triage) == []
          and "--answer accept" not in triage)
    _name_only_triage_cases(check, M, over)


def _name_only_triage_cases(check, M, over):
    """A settlement an older driver recorded by key alone binds no answer, so
    the triage puts each answer to the human again - its accept is what
    records the signature the sign-off verb honours."""
    root, mpath = _repo("answers-legacy", task_ids=TASKS[:2], per_task="phase")
    drive(M, root, mpath, entry_over=over, phase_intent="cannot-tell",
          answer=None)
    filed = _fr.phase_returns(os.path.join(root, "docs", "audit", "evidence"),
                              PHASE)
    asked = _fr.needs_human(filed)
    path = os.path.join(root, ".claude", "state", "drive", "%s.json" % (PHASE,))
    seen = []
    for by_name in (True, False):
        state = _drive_state(root)
        state.pop("pending", None)
        block = _fr.settlement_after({}, asked, "an older driver's accept")
        if by_name:
            block.pop(_fr.SIGNATURES_FIELD, None)
        state[_fr.SETTLED_FIELD] = block
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        _code, text = _next(M, root, mpath)
        seen.append(_answer_lines(text))
    check("sa5 a settlement recorded by key alone - an older driver's record - "
          "settles nothing in the triage: every answer is put to the human "
          "again, so the accept records its signature: %r" % (seen[0],),
          len(asked) == 3 and len(seen[0]) == 3)
    check("sa5b THE ALLOW TWIN: the same settlement bound to each answer's "
          "signature settles them all: %r" % (seen[1],),
          seen[1] == [])


def _continue_cases(check):
    """Under `always`, a per-task reviewer's `diverges` is `decide
    review-answer`, and its `continue` is a human's word on it: it takes
    `--reason`, and the summary keeps that reason as it keeps the triage's
    accept."""
    M, why = _load("drive_phase_continue")
    if M is None:
        check("ct1 the driver loads", False, why)
        return
    root, mpath = _repo("continue", task_ids=TASKS[:1])
    run = drive(M, root, mpath, answer=None,
                reviewer_answers={"P1.1": "diverges"})
    last = run["prints"][-1][1]
    bare, bare_text = _next(M, root, mpath, "--answer", "continue")
    check("ct1 a per-task `diverges` is `decide review-answer`, whose print says "
          "`continue` needs --reason, and a bare continue is refused: %r"
          % ((run["steps"][-1], last, bare, bare_text),),
          run["steps"][-1] == ("decide", "review-answer", None)
          and "continue needs --reason" in last and bare == M.E_USAGE
          and len(last.encode("utf-8")) <= BOUND)
    check("ct1r ...and its print carries the rule the triage's accept carries: "
          "the answer is the human's (AskUserQuestion), and --reason is their "
          "words verbatim - without it the model can write the reason itself: %r"
          % (last,),
          "AskUserQuestion" in last and "verbatim" in last
          and "human" in last)
    words = "the human: P1.1 was meant to diverge, the plan was stale"
    code, text = _next(M, root, mpath, "--answer", "continue", "--reason", words)
    rest = drive(M, root, mpath)
    summary = _phase_of(mpath).get("summary") or ""
    check("ct2 ALLOW: continue with the human's words goes on, the phase signs "
          "off, and the summary keeps those words beside the triage's: %r"
          % ((code, rest["steps"][-1], summary),),
          code == 0 and rest["steps"][-1] == DONE
          and summary.startswith(SUMMARY) and words in summary)


def _redispatch_cases(check):
    """A task added after the phase review's head is owed its answers, so the
    drive dispatches a fresh phase review rather than a triage the sign-off verb
    then refuses."""
    M, why = _load("drive_phase_redispatch")
    if M is None:
        check("sr1 the driver loads", False, why)
        return
    root, mpath = _repo("readd", task_ids=TASKS[:1], per_task="phase",
                        phase_gate=("false",))
    first = drive(M, root, mpath)
    code, out = _verb(root, "audit-task.py", [
        "add", "the fix the red phase gate asked for", mpath, "--project-dir",
        root, "--phase", PHASE, "--files", "src/f1.txt", "--description",
        "fix what the phase gate found", "--gate", "true", "--json"])
    try:
        added = json.loads(out).get("id")
    except ValueError:
        added = None
    run = drive(M, root, mpath, phase_review=False)
    steps = run["steps"]
    check("sr1 after a red phase gate and a task added with no --fixes, the "
          "added task is driven and sign-off dispatches a new phase review at "
          "the new head - not a triage over a review that never saw the task: %r"
          % ((first["steps"][-1], code, added, steps),),
          first["prints"][-1][0] == 1 and code == 0 and added
          and ("dispatch", "executor", added) in steps
          and steps[-1] == ("dispatch", "reviewer", PHASE))


def _reuse_review_cases(check):
    """With no phase review marked in the driver's state, a phase return filed
    at the current head is the review: the sign-off verb refuses a second
    filing at that head, so a fresh dispatch would pay for a review whose
    return can never be filed."""
    M, why = _load("drive_phase_reuse_review")
    if M is None:
        check("rr1 the driver loads", False, why)
        return

    def to_triage(prefix):
        root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="always")
        _commit_plan(root, mpath, lambda p: p["meta"].__setitem__(
            "reviewSkill", "code-review"), "skill")
        run = drive(M, root, mpath, answer=None, phase_intent="diverges")
        state = os.path.join(root, ".claude", "state", "drive", "%s.json"
                             % (PHASE,))
        if os.path.isfile(state):
            os.remove(state)
        return root, mpath, run

    def filed_returns(root):
        rdir = os.path.join(root, "docs", "audit", "evidence", "returns", PHASE)
        return sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []

    root, mpath, run = to_triage("reuse-review")
    filed = filed_returns(root)
    code, text = _next(M, root, mpath)
    mark = _drive_state(root).get("phaseReview") or {}
    check("rr1 the drive state lost after the phase review was filed: the next "
          "`next` reads the return filed at the current head, records the mark "
          "at that head, and prints the triage over it - no second dispatch: %r"
          % ((run["steps"][-1], code, text, mark),),
          run["steps"][-1] == TRIAGE and code == 0 and instruction(text) == TRIAGE
          and "intent diverges" in text and mark.get("head") == _head(root)
          and len(text.splitlines()[0].encode("utf-8")) <= BOUND
          and filed != [] and filed == filed_returns(root))
    root, mpath, run = to_triage("reuse-review-none")
    rdir = os.path.join(root, "docs", "audit", "evidence", "returns", PHASE)
    for name in filed_returns(root):
        os.remove(os.path.join(rdir, name))
    code, text = _next(M, root, mpath)
    check("rr2 THE TWIN: with no return filed at the current head, the same "
          "`next` dispatches the phase review - a reuse that read any filed "
          "return, or none, would print a triage here: %r" % ((code, text),),
          code == 0 and instruction(text) == ("dispatch", "reviewer", PHASE))
    _reuse_findings_cases(check, M)


def _reuse_findings_cases(check, M):
    """A phase return reused at the current head carries findings the plan may
    already hold - recorded when the drive state that is now lost marked them.
    `finding` appends rather than deduplicates, so recording them again would
    double the review's findings."""
    def recorded(mpath):
        return [(f.get("severity"), f.get("file"), f.get("issue"))
                for f in (_phase_of(mpath).get("review") or {}).get("findings")
                or []]

    def to_triage(prefix):
        root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="always")
        _commit_plan(root, mpath, lambda p: p["meta"].__setitem__(
            "reviewSkill", "code-review"), "skill")
        run = drive(M, root, mpath, answer=None, findings=FINDINGS[:2])
        os.remove(os.path.join(root, ".claude", "state", "drive", "%s.json"
                               % (PHASE,)))
        return root, mpath, run

    root, mpath, run = to_triage("reuse-findings")
    before = recorded(mpath)
    code, text = _next(M, root, mpath)
    after = recorded(mpath)
    mark = _drive_state(root).get("phaseReview") or {}
    check("rr3 the return reused at the head holds findings the plan already "
          "records: the next `next` records none of them again and marks them "
          "recorded - each finding stays once: %r"
          % ((run["steps"][-1], before, after, code, mark),),
          run["steps"][-1] == TRIAGE and len(before) == 2 and after == before
          and code == 0 and instruction(text) == TRIAGE
          and mark.get("findings") is True)

    root, mpath, run = to_triage("reuse-findings-none")

    # Written, not committed: a commit moves HEAD, and a return filed at the
    # old head is then no longer the one at the current head.
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    for phase in plan["phases"]:
        if phase["id"] == PHASE:
            phase["review"]["findings"] = []
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    code, text = _next(M, root, mpath)
    after = recorded(mpath)
    check("rr4 THE TWIN: the same reused return with the plan holding none of "
          "its findings records each of them once - a mark set whenever a "
          "return is reused would record none here: %r" % ((after, code),),
          code == 0 and instruction(text) == TRIAGE
          and after == [(f["severity"], f["file"], f["issue"])
                        for f in FINDINGS[:2]])


def _late_return_cases(check):
    """A recorded verdict is what close-phase reads as every human answer its
    checkout holds settled, so a phase return cannot be filed there after it:
    the landing that follows would carry an answer nobody was asked about."""
    M, why = _load("drive_phase_late")
    if M is None:
        check("lr1 the driver loads", False, why)
        return

    def to_signed(prefix):
        root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="always")
        _commit_plan(root, mpath, lambda p: p["meta"].__setitem__(
            "reviewSkill", "code-review"), "skill")
        drive(M, root, mpath, answer=None)
        with _Env(root):
            gate = _verb(root, "run-test-gate.py", [mpath, PHASE, "--record",
                                                    "--project-dir", root])
            signed = _verb(root, "audit-task.py", [
                "signoff", PHASE, mpath, "--project-dir", root, "--verdict",
                "passed", "--summary", "by hand"])
        subprocess.run(_GIT + ["add", "-A"], cwd=root, capture_output=True,
                       timeout=60)
        subprocess.run(_GIT + ["commit", "-qm", "signoff"], cwd=root,
                       capture_output=True, timeout=60)
        return root, mpath, gate[0], signed[0]

    root, mpath, gate, signed = to_signed("late-return")
    rdir = os.path.join(root, "docs", "audit", "evidence", "returns", PHASE)

    def listed():
        return sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []
    before = listed()
    head = _head(root)
    late = {"findings": [], "preExisting": [], "verdict": "clean", "tasks": [],
            "intent": {"answer": "diverges", "missing": [],
                       "note": "late review: the phase missed its outcome"}}
    with _Env(root):
        code, text = _verb(root, "audit-task.py", [
            "file-return", PHASE, "--role", "reviewer", mpath, "--project-dir",
            root, "--head", head], stdin=json.dumps(late))
    check("lr1 a `diverges` phase return filed after the sign-off verdict, "
          "before the landing, is refused and files nothing - filed, the "
          "landing would carry an answer no human was asked about: %r"
          % ((gate, signed, code, text[-240:]),),
          gate == 0 and signed == 0 and code != 0 and "signed off" in text
          and listed() == before)
    with _Env(root):
        landed = _verb(root, "close-phase.py", [mpath, PHASE, "--project", root])
    check("lr2 THE TWIN: with no return arriving after the verdict, the same "
          "phase lands - a refusal that held every signed-off phase would stop "
          "here too: %r" % ((landed[0], landed[1][-200:]),),
          landed[0] == 0 and bool(_phase_of(mpath).get("mergedAt")))


def _fix_review_cases(check):
    """A fix task closed after the phase review's head has a diff no review
    saw: the triage says so, offers `re-review`, and the re-review is the phase
    reviewer dispatched at the new head."""
    M, why = _load("drive_phase_rereview")
    if M is None:
        check("sf1 the driver loads", False, why)
        return
    root, mpath = _repo("rereview", task_ids=TASKS[:1], per_task="phase")
    answers = iter([["--answer", "fix", "--fix", "P1-R1"]])
    run = drive(M, root, mpath, findings=FINDINGS[:1],
                answer=lambda kind, text: next(answers, False))
    # The brief file is rewritten at each dispatch, so its head is read now.
    heads = [_head_of_brief(root, b.group(1)) for b in (
        _BRIEF.search(t) for (_c, t), s in zip(run["prints"], run["steps"])
        if s == ("dispatch", "reviewer", PHASE)) if b]
    triage = run["prints"][-1][1]
    fix = [t for t in tasks_of(mpath).values() if t.get("fixes") == ["P1-R1"]]
    fix_id = fix[0].get("id") if fix else "-"
    basis = ((fix[0].get("intentCheck") or {}).get("basis") or "") if fix else ""
    check("sf1 after the fix task closes, the triage names it as closed after "
          "the review's head and offers `re-review`, and its close basis says "
          "its own diff is unreviewed: %r" % ((triage, basis),),
          run["steps"][-1] == TRIAGE and fix_id in triage
          and "--answer re-review" in triage and "unreviewed" in basis)
    code, text = _next(M, root, mpath, "--answer", "re-review")
    old = heads[0] if heads else None
    new = _BRIEF.search(text)
    check("sf2 `re-review` dispatches the phase reviewer again, with a brief at "
          "a head after the fix's commit: %r" % ((code, text, old),),
          code == 0 and instruction(text) == ("dispatch", "reviewer", PHASE)
          and new and old and _head_of_brief(root, new.group(1)) != old)
    if new:
        _file_phase_review(root, mpath, text)
    code, text = _next(M, root, mpath)
    check("sf3 THE TWIN: once the re-review is filed, the triage names no fix "
          "task as unreviewed and offers no `re-review`: %r" % (text,),
          code == 0 and instruction(text) == TRIAGE
          and "--answer re-review" not in text and fix_id not in text)
    _rereview_scope_cases(check)
    _fix_scope_cases(check, M)


def _fix_scope_cases(check, M):
    """The fix task the drive adds covers every path its finding names, where it
    used to cover the text up to the first colon."""
    multi = dict(FINDINGS[0], file="src/f1.txt:1 and src/f2.txt:9, src/f3.txt")
    for label, finding, want in (("fs1 three paths in one finding", multi,
                                  ["src/f1.txt", "src/f2.txt", "src/f3.txt"]),
                                 ("fs2 ALLOW: one path with a line", FINDINGS[0],
                                  ["src/f1.txt"])):
        root, mpath = _repo("fixscope-" + label[:3], task_ids=TASKS[:1],
                            per_task="phase")
        answers = iter([["--answer", "fix", "--fix", "P1-R1"]])
        drive(M, root, mpath, findings=[finding],
              answer=lambda kind, text: next(answers, False))
        fix = [t for t in tasks_of(mpath).values() if t.get("fixes") == ["P1-R1"]]
        got = fix[0].get("files") if fix else None
        check("%s: the fix task's `files` is every path the finding names: %r"
              % (label, got), got == want)


# --- sign-off converges: re-review only where it can change the answer --------
def _carry_target(root, mpath):
    """A later phase holding one pending task, made through the verbs: where a
    carried finding goes. Its id, or the refusal's text."""
    with _Env(root):
        code_p, out_p = _verb(root, "audit-task.py", [
            "add-phase", "later work", mpath, "--project-dir", root, "--id",
            "P2", "--outcome", "what the first phase carried is done"])
        code, out = _verb(root, "audit-task.py", [
            "add", "carried findings", mpath, "--project-dir", root, "--phase",
            "P2", "--files", "src/f3.txt", "--description",
            "the findings P1 carried", "--gate", "true", "--json"])
    try:
        return json.loads(out).get("id")
    except ValueError:
        return "(add-phase exit %d: %s; add exit %d: %s)" % (
            code_p, out_p[-200:], code, out[-200:])


def _phase_review_briefs(root, run):
    """The brief text of the last phase-review dispatch the run printed, and
    how many phase reviews it dispatched."""
    briefs = [_BRIEF.search(t) for (_c, t), s in zip(run["prints"], run["steps"])
              if s == ("dispatch", "reviewer", PHASE)]
    briefs = [b.group(1) for b in briefs if b]
    text = ""
    if briefs:
        with open(os.path.join(root, *briefs[-1].split("/")), encoding="utf-8") as fh:
            text = fh.read()
    return text, len(briefs)


def _converge_cases(check):
    """A review returning one med and two lows dispatches one fix task and one
    re-review over that fix's diff; the two lows end carried, and no third
    review is dispatched."""
    M, why = _load("drive_phase_converge")
    if M is None:
        check("cv1 the driver loads", False, why)
        return
    root, mpath = _repo("converge", task_ids=TASKS[:1], per_task="phase")
    target = _carry_target(root, mpath)
    live = list(FINDINGS)

    def cleared(role, tid):
        # The re-review finds nothing new: only the first review's findings.
        if tid == PHASE:
            del live[:]

    def answer(kind, text):
        if kind[1] != "triage":
            return False
        if "--answer re-review" in text:
            return ["--answer", "re-review"]
        if any("P1-R1" in ln and "[fix|leave]" in ln for ln in text.splitlines()):
            return ["--answer", "fix", "--fix", "P1-R1"]
        if "--answer carry" in text:
            return ["--answer", "carry", "--to", target]
        return ["--answer", "sign-off", "--reason", SUMMARY]
    run = drive(M, root, mpath, findings=live, on_dispatch=cleared,
                answer=answer, cap=30)
    brief, reviews = _phase_review_briefs(root, run)
    fixes = [t for t in tasks_of(mpath).values() if t.get("fixes")]
    fix_id = fixes[0].get("id") if fixes else "-"
    found = dict((f.get("id"), f) for f in
                 (_phase_of(mpath).get("review") or {}).get("findings") or [])
    lows = [(found.get(f) or {}) for f in ("P1-R2", "P1-R3")]
    check("cv1 one med and two lows: ONE fix task (for the med), TWO phase "
          "reviews - the second over that fix's diff alone - and the phase "
          "signed off with no third review: %r"
          % ((run["steps"][-4:], [t.get("fixes") for t in fixes], reviews),),
          len(fixes) == 1 and fixes[0].get("fixes") == ["P1-R1"]
          and reviews == 2 and run["steps"][-1] == DONE
          and "Re-review scope" in brief and fix_id in brief
          and _signed(mpath))
    check("cv2 both lows end `carried`, each naming the task it went to (%s), "
          "and the med ends fixed by its task's commit: %r"
          % (target, (lows, found.get("P1-R1"))),
          all(f.get("status") == "carried" and f.get("carriedTo") == target
              for f in lows)
          and (found.get("P1-R1") or {}).get("fixTask") == fix_id
          and bool((found.get("P1-R1") or {}).get("commit")))
    triages = [t for (_c, t), s in zip(run["prints"], run["steps"]) if s == TRIAGE]
    first = triages[0] if triages else ""
    recommend = [ln for ln in first.splitlines() if "--answer carry" in ln]
    check("cv3 the first triage recommends carrying the lows - their lines "
          "offer carry first, the answer line says it is the recommended one - "
          "while the med keeps fix|leave: %r" % (first,),
          all(any(fid in ln and "[carry|fix|leave]" in ln
                  for ln in first.splitlines()) for fid in ("P1-R2", "P1-R3"))
          and any("P1-R1" in ln and "[fix|leave]" in ln
                  and "carry" not in ln for ln in first.splitlines())
          and len(recommend) == 1 and "recommended" in recommend[0])

    # The fix task's mode comes from its finding: one over a test file alone
    # adds a case over code already at HEAD, so no red can be shown first.
    pin = [{"severity": "med", "file": "tests/test_f1.py",
            "issue": "nothing pins f1's text", "resolution": "add a case"}]
    root_t, mpath_t = _triage_with(M, "converge-pin", pin)
    _next(M, root_t, mpath_t, "--answer", "fix", "--fix", "P1-R1")
    made = [t for t in tasks_of(mpath_t).values() if t.get("fixes") == ["P1-R1"]]
    mode = ((made[0].get("tests") or {}).get("mode")) if made else None
    check("cv4 a fix task over a finding naming only a test file is "
          "`regression`, never `tdd` the red-first helper must refuse: %r"
          % ((mode, made and made[0].get("tests")),), mode == "regression")


# A gate green while the repository's own exclude file names `src/` and red once
# it does not: git on every platform, and whatever task file a gate's
# derivation re-spells its operand onto lies under `src/` either way.
_FLIP_GATE = "git check-ignore -q --no-index src/f1.txt"


def _low_fix_cases(check):
    """A fixed low whose gate is green closes without a re-review; a fixed low
    whose gate went red owes one."""
    M, why = _load("drive_phase_low_fix")
    if M is None:
        check("lf1 the driver loads", False, why)
        return
    low = [dict(FINDINGS[1])]
    root, mpath = _repo("low-fix", task_ids=TASKS[:1], per_task="phase")
    answers = iter([["--answer", "fix", "--fix", "P1-R1"]])
    run = drive(M, root, mpath, findings=low,
                answer=lambda kind, text: next(answers, False))
    # The decision alone: the did-line above it names the fix task it closed.
    triage = "\n".join(ln for ln in run["prints"][-1][1].splitlines()
                       if not ln.startswith("[drive-phase]"))
    fix = [t for t in tasks_of(mpath).values() if t.get("fixes") == ["P1-R1"]]
    fix_id = fix[0].get("id") if fix else "-"
    basis = ((fix[0].get("intentCheck") or {}).get("basis") or "") if fix else ""
    check("lf1 a fixed low whose gate went green closes on it: the triage after "
          "it names no unreviewed fix and offers no re-review, and the close "
          "basis says none is owed: %r" % ((run["steps"][-3:], triage, basis),),
          run["steps"][-1] == TRIAGE and fix and fix[0].get("status") == "done"
          and "--answer re-review" not in triage and fix_id not in triage
          and "no re-review" in basis)

    # The twin: the same low, its fix's gate red once and then green.
    root_r, mpath_r = _repo("low-fix-red", task_ids=TASKS[:1],
                            gate=(_FLIP_GATE,), per_task="phase")
    exclude = os.path.join(root_r, ".git", "info", "exclude")

    def flip(text):
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        _write_lf(exclude, text)

    def make_green():
        flip("src/\n")
    make_green()
    reds = []

    def red_once(kind, text):
        if kind[1] == "triage" and not reds and "--answer fix" in text:
            flip("")
            return ["--answer", "fix", "--fix", "P1-R1"]
        if kind[1] == "gate-red" and not reds:
            reds.append(text)
            make_green()
            return ["--answer", "rerun"]
        return False
    run_r = drive(M, root_r, mpath_r, findings=low, answer=red_once)
    triage_r = run_r["prints"][-1][1]
    fix_r = [t for t in tasks_of(mpath_r).values() if t.get("fixes") == ["P1-R1"]]
    fix_r_id = fix_r[0].get("id") if fix_r else "-"
    project, config = _evio.project_config_for(mpath_r, root_r)
    red_rows = [r for r in _evio.read_rows(project, config)["rows"]
                if isinstance(r, dict) and r.get("taskId") == fix_r_id
                and r.get("status") == "failed"]
    check("lf2 THE TWIN: a fixed low whose own gate went red before it went "
          "green owes the re-review - the triage names it unreviewed and offers "
          "`re-review`: %r" % ((run_r["steps"], len(red_rows), reds, triage_r),),
          run_r["steps"][-1] == TRIAGE and ("decide", "gate-red", None)
          in run_r["steps"] and red_rows and fix_r_id in triage_r
          and "--answer re-review" in triage_r)


_USAGE_ROWS = (
    # A phase-level row (the reviews and the main loop) priced on the shipped
    # table: one million input tokens.
    {"ts": "2026-10-13T10:00:00Z", "phaseId": PHASE, "model": "claude-opus-4-8",
     "in": 1000000, "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0,
     "msgs": 1},
    # The original task's own spend: not a review round's, so not counted.
    {"ts": "2026-10-13T10:00:00Z", "phaseId": PHASE, "taskId": "P1.1",
     "model": "claude-opus-4-8", "in": 3000000, "out": 0, "cacheW5m": 0,
     "cacheW1h": 0, "cacheR": 0, "msgs": 1},
    # A model no rate covers: its tokens are said to be unpriced.
    {"ts": "2026-10-13T10:00:00Z", "phaseId": PHASE, "model": "claude-nobody-1",
     "in": 777, "out": 0, "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0, "msgs": 1})


def _round_line(text):
    return [ln for ln in text.splitlines() if "review round" in ln]


def _round_cap_cases(check):
    """At review.maxRounds the driver stops with the open findings, the rounds'
    cost and one question, and a deleted state file re-derives the same round
    count rather than resetting it."""
    M, why = _load("drive_phase_round_cap")
    if M is None:
        check("rc1 the driver loads", False, why)
        return
    root, mpath = _repo("round-cap", task_ids=TASKS[:1], per_task="phase")
    live = [dict(FINDINGS[0])]
    second = {"severity": "med", "file": "src/f1.txt",
              "issue": "the fix left f1 half said", "resolution": "say it all"}
    reviews = []

    def next_round(role, tid):
        if tid != PHASE:
            return
        reviews.append(tid)
        if len(reviews) == 1:
            live[:] = [second]
            return
        ledger = os.path.join(root, ".claude", "usage")
        os.makedirs(ledger, exist_ok=True)
        with open(os.path.join(ledger, "2026-10.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in _USAGE_ROWS))

    def answer(kind, text):
        if kind[1] != "triage":
            return False
        if "--answer re-review" in text:
            return ["--answer", "re-review"]
        if any("P1-R1" in ln and "[fix|leave]" in ln for ln in text.splitlines()):
            return ["--answer", "fix", "--fix", "P1-R1"]
        return False
    run = drive(M, root, mpath, findings=live, on_dispatch=next_round,
                answer=answer)
    code, text = run["prints"][-1]
    asks = [ln for ln in text.splitlines() if ln.startswith("answer:")]
    check("rc1 at review.maxRounds (2, the default) the drive stops at one "
          "`round-cap` decision naming the finding still open, with ONE answer "
          "line offering carry, one more round and sign-off: %r"
          % ((run["steps"][-3:], text),),
          code == 0 and run["steps"][-1] == ("decide", "round-cap", None)
          and len(reviews) == 2 and "P1-R2" in text and len(asks) == 1
          and all(w in asks[0] for w in ("carry", "one-more-round", "sign-off")))
    check("rc2 the rounds' cost is read from the usage ledger by phase - the "
          "phase-level row at its shipped rate (5.00), not the original task's "
          "own spend - with its rate basis, and the tokens no rate covers said "
          "to be unpriced: %r" % (text,),
          "5.00 USD-eq" in text and "20.00" not in text
          and "shipped table" in text and "unpriced" in text)
    before = _round_line(text)
    os.remove(os.path.join(root, ".claude", "state", "drive", "%s.json" % (PHASE,)))
    code_d, text_d = _next(M, root, mpath)
    check("rc3 with the driver's state file deleted, the next `next` re-derives "
          "the same round count from the filed phase returns and asks the same "
          "question, rather than starting again at zero: %r"
          % ((before, code_d, text_d),),
          code_d == 0 and instruction(text_d) == ("decide", "round-cap", None)
          and before and _round_line(text_d) == before
          and _drive_state(root).get("reviewRounds") == 2)

    mutant, _w = _load("drive_phase_round_cap_bad")
    root_m, mpath_m = _repo("round-cap-mut", task_ids=TASKS[:1], per_task="phase")
    live[:] = [dict(FINDINGS[0])]
    del reviews[:]
    drive(mutant, root_m, mpath_m, findings=live, on_dispatch=next_round,
          answer=answer)
    if hasattr(mutant, "filed_review_rounds"):
        mutant.filed_review_rounds = lambda ctx, phase: 0
    os.remove(os.path.join(root_m, ".claude", "state", "drive",
                           "%s.json" % (PHASE,)))
    code_m, text_m = _next(mutant, root_m, mpath_m)
    check("rc3m RED TWIN: a driver that counts rounds only in its state file "
          "forgets them with it, and rc3's question is not asked again: %r"
          % ((code_m, text_m[-300:]),),
          instruction(text_m) != ("decide", "round-cap", None))


# Two med findings for one triage; the second carries ` :400`, the text the
# argv prose check refuses as a flag value and stdin never sees as one.
COLON_FINDINGS = [
    {"severity": "med", "file": "src/f1.txt", "issue": "f1 says too little",
     "resolution": "say what changed"},
    {"severity": "med", "file": "src/f1.txt", "issue": "the bound reads 1 :400",
     "resolution": "keep the bound at :400 bytes"}]


def _triage_with(M, prefix, findings):
    """A one-task phase under `phase`, driven to the triage over `findings`:
    `(root, mpath)`."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    drive(M, root, mpath, findings=findings, answer=None)
    return root, mpath


def _fix_task_over(M, prefix, finding, extra_files=()):
    """`(task, code, text)` - the one fix task `--answer fix` adds over `finding`
    in a phase whose runner takes paths (`vitest run` behind the `test` key, a
    sibling's gate pointed at one suite). `extra_files` are written into the
    fixture first: a fix task is scoped only onto paths that exist."""
    root, mpath = _triage_with(M, prefix, [finding])
    for rel in extra_files:
        full = os.path.join(root, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(full)):
            os.makedirs(os.path.dirname(full))
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("v0\n")

    def spell(plan):
        plan["meta"]["buildCommands"] = {"test": "vitest run"}
        phase = plan["phases"][0]
        phase["testGate"] = ["test"]
        phase["tasks"][0]["tests"]["gate"] = ["vitest run src/f1.test.ts"]
    _commit_plan(root, mpath, spell, "a runner that takes paths")
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "the files the findings name")
    code, text = _next(M, root, mpath, "--answer", "fix", "--fix", "P1-R1")
    mine = [t for t in tasks_of(mpath).values() if t.get("fixes") == ["P1-R1"]]
    return (mine[0] if mine else {}), code, text


def _fix_gate_cases(check, M):
    """The gate of a fix task made at the triage is derived from the suite
    paths among the finding's files, never from a workflow or a source file,
    and a fix task that owes no test is not born asking for a red first."""
    workflow = ".github/workflows/ci.yml"
    suite, source = "src/Button.test.tsx", "src/Button.tsx"
    base = {"severity": "med", "issue": "it is wrong", "resolution": "rework it"}

    with_suite, code, text = _fix_task_over(
        M, "fix-gate-suite", dict(base, file=", ".join((source, suite, workflow))),
        (source, suite, workflow))
    tests = with_suite.get("tests") or {}
    check("fb5 a fix task over a finding naming a workflow file and a suite "
          "gets a gate that names only the suite: %r"
          % ((code, tests.get("gate"), tests.get("gateBasis"), text[-200:]),),
          code == 0 and tests.get("gate") == ["vitest run %s" % (suite,)]
          and workflow not in " ".join(tests.get("gate") or []))

    no_suite, code, text = _fix_task_over(
        M, "fix-gate-nosuite", dict(base, file=", ".join((source, workflow))),
        (source, workflow))
    tests = no_suite.get("tests") or {}
    check("fb6 a fix task over a finding naming a workflow file and a source "
          "file, and no suite, gets the phase's gate with a gateBasis that "
          "says no path was there to point it at, and no gate entry names the "
          "workflow: %r" % ((code, tests.get("gate"), tests.get("gateBasis")),),
          code == 0 and tests.get("gate") == ["test"]
          and tests.get("gateBasis") == "files-no-suite"
          and not any(workflow in e or source in e
                      for e in tests.get("gate") or []))

    doc, code, text = _fix_task_over(
        M, "fix-gate-doc", dict(base, file="docs/guide.md",
                                resolution="reword the paragraph"),
        ("docs/guide.md",))
    comment, code_c, text_c = _fix_task_over(
        M, "fix-gate-comment", dict(base, file=source, issue="the comment lies",
                                    resolution="No code change: update the "
                                    "comment to say what the loop does"),
        (source,))
    code_s = _fix_task_over(M, "fix-gate-source", dict(base, file=source),
                            (source,))
    plain = code_s[0].get("tests") or {}
    modes = [((t.get("tests") or {}).get("mode"),
              (t.get("tests") or {}).get("expectRedFirst")) for t in (doc, comment)]
    check("fb7 a fix task over a finding whose files are only a document, or "
          "whose resolution says no code changes, is gate-only with "
          "expectRedFirst false: %r" % ((modes, code, code_c),),
          code == 0 and code_c == 0 and modes == [("gate-only", False)] * 2)
    check("fb8 ALLOW CASE, the twin of fb7: a finding naming a source file "
          "whose resolution asks for a change stays tdd, and a tdd task "
          "naming no case does not write expectRedFirst true beside an empty "
          "tests.add: %r" % ((plain.get("mode"), plain.get("expectRedFirst"),
                              plain.get("add")),),
          plain.get("mode") == "tdd" and not plain.get("add")
          and plain.get("expectRedFirst") is False)


def _fix_batch_cases(check):
    """`--answer fix` hands every named finding to ONE `add --from-file -` call
    on stdin: no finding's text passes through argv, and the batch lands whole
    or not at all."""
    M, why = _load("drive_phase_fix_batch")
    if M is None:
        check("fb1 the driver loads", False, why)
        return
    seen = _counting(M)
    root, mpath = _triage_with(M, "fix-batch", COLON_FINDINGS)
    code, text = _next(M, root, mpath, "--answer", "fix", "--fix", "P1-R1,P1-R2")
    tasks = tasks_of(mpath)
    fixes = sorted(tuple(t.get("fixes") or ()) for t in tasks.values()
                   if t.get("fixes"))
    found = dict((f.get("id"), f.get("fixTask")) for f in
                 (_phase_of(mpath).get("review") or {}).get("findings") or [])
    check("fb1 --answer fix over two findings, one whose text carries ' :400', "
          "adds a fix task for each in ONE add call, each finding naming its "
          "task back, and the drive goes on to dispatch: %r"
          % ((code, seen.get(("audit-task.py", "add")), fixes, found, text[-300:]),),
          code == 0 and seen.get(("audit-task.py", "add")) == 1
          and fixes == [("P1-R1",), ("P1-R2",)]
          and all(found.get(f) for f in ("P1-R1", "P1-R2"))
          and instruction(text)[0] == "dispatch")
    fix_id = instruction(text)[2]
    mode = ((tasks.get(fix_id) or {}).get("tests") or {}).get("mode")
    code_s, text_s = _file_executor(root, mpath, fix_id)
    path = _filed_path(mpath, fix_id)
    filed = json.loads(_read(path).decode("utf-8")) if path and os.path.exists(path) else {}
    red = filed.get("redFirst") or {}
    check("fb3 the fix task over a finding naming only source is tdd, and with no "
          "test file declared its executor return is still filed - red-first "
          "`could-not-prove`, carrying the helper's own refusal - rather than "
          "stopping every submit: %r" % ((mode, code_s, red, text_s[-200:]),),
          mode == "tdd" and code_s == 0 and red.get("status") == "could-not-prove"
          and "declares no test file" in (red.get("basis") or "")
          and red.get("at"))

    spaced = [dict(COLON_FINDINGS[0],
                   issue="the split reads wrong, see `(split_not_commands at :4809)`")]
    root_p, mpath_p = _triage_with(M, "fix-batch-paren", spaced)
    code_p, text_p = _next(M, root_p, mpath_p, "--answer", "fix", "--fix", "P1-R1")
    fix_p = [t for t in tasks_of(mpath_p).values() if t.get("fixes") == ["P1-R1"]]
    check("fb4 --answer fix over a finding whose issue holds a backtick span with "
          "a spaced paren adds its fix task, carrying that text whole: %r"
          % ((code_p, [t.get("id") for t in fix_p], text_p[-300:]),),
          code_p == 0 and len(fix_p) == 1
          and "`(split_not_commands at :4809)`" in (fix_p[0].get("description") or "")
          and instruction(text_p)[0] == "dispatch")

    _fix_gate_cases(check, M)

    mutant, _w = _load("drive_phase_fix_batch_bad")
    real_verb = mutant.run_verb

    def spoil_second(ctx, script, args, stdin=None):
        # The second task of the batch names a finding the phase never had,
        # which the verb refuses: the whole batch must be refused with it.
        if script == "audit-task.py" and list(args)[:1] == ["add"] and stdin:
            doc = json.loads(stdin)
            if len(doc.get("tasks") or []) > 1:
                doc["tasks"][1]["fixes"] = ["P1-R9"]
                stdin = json.dumps(doc)
        return real_verb(ctx, script, args, stdin=stdin)
    mutant.run_verb = spoil_second
    root_b, mpath_b = _triage_with(mutant, "fix-batch-bad", COLON_FINDINGS)
    before = sorted(tasks_of(mpath_b))
    code_b, text_b = _next(mutant, root_b, mpath_b, "--answer", "fix", "--fix",
                           "P1-R1,P1-R2")
    found_b = [f.get("fixTask") for f in
               (_phase_of(mpath_b).get("review") or {}).get("findings") or []]
    check("fb2 a batch whose second task the verb refuses writes neither task: "
          "the drive stops with the verb's refusal, and no finding names a fix "
          "task: %r" % ((code_b, sorted(tasks_of(mpath_b)), found_b, text_b[-300:]),),
          code_b != 0 and sorted(tasks_of(mpath_b)) == before
          and found_b == [None, None] and "P1-R9" in text_b)


def _handed_triage_cases(check):
    """A triage whose every med+ open finding a human already handed to a fix
    task (`add --fixes` by hand) is satisfied without an answer: the drive runs
    those tasks, and the triage comes back after them. A finding handed to a
    live fix task is offered neither `fix` nor a sign-off disposition."""
    M, why = _load("drive_phase_handed")
    if M is None:
        check("ht1 the driver loads", False, why)
        return

    def hand_fix(root, mpath, fid):
        with _Env(root):
            code, out = _verb(root, "audit-task.py", [
                "add", "fix %s by hand" % (fid,), mpath, "--project-dir", root,
                "--phase", PHASE, "--fixes", fid, "--tests-mode", "gate-only",
                "--gate", "true", "--json"])
        try:
            return json.loads(out).get("id")
        except ValueError:
            return "refused: %s" % (out[-200:],)

    root, mpath = _triage_with(M, "handed", FINDINGS[:2])
    fix_id = hand_fix(root, mpath, "P1-R1")
    code, text = _next(M, root, mpath)
    check("ht1 once the one med finding names a pending fix task added by hand, "
          "the pending triage is satisfied without an answer: the next `next` "
          "dispatches that task's executor instead of printing the triage: %r"
          % ((fix_id, code, text[-300:]),),
          code == 0 and instruction(text) == ("dispatch", "executor", fix_id))

    root_t, mpath_t = _triage_with(M, "handed-low", FINDINGS[:2])
    low_id = hand_fix(root_t, mpath_t, "P1-R2")
    code_t, text_t = _next(M, root_t, mpath_t)
    offered = [ln for ln in text_t.splitlines() if "[fix|leave]" in ln]
    check("ht2 THE TWIN: with the med finding still unhanded the triage stays "
          "pending - and the low finding handed to %s is no longer offered for "
          "a fix: %r" % (low_id, (code_t, offered)),
          code_t == 0 and instruction(text_t) == TRIAGE
          and any("P1-R1" in ln for ln in offered)
          and not any("P1-R2" in ln for ln in offered))
    code_r, text_r = _next(M, root_t, mpath_t, "--answer", "fix", "--fix",
                           "P1-R2")
    check("ht3 --answer fix naming the handed finding is refused with the "
          "'already names a fix task' wording, not 'not open': %r"
          % ((code_r, text_r),),
          code_r == M.E_USAGE and "P1-R2 already names a fix task" in text_r
          and "not open" not in text_r)


def _head_of_brief(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        found = _HEAD_LINE.search(fh.read())
    return found.group(1) if found else None


def _risk_cases(check):
    """A high-risk confirmation given before the run covers the tasks it named;
    any other high-risk task still stops and asks."""
    M, why = _load("drive_phase_risk")
    if M is None:
        check("hr1 the driver loads", False, why)
        return
    root, mpath = _repo("risk", task_ids=TASKS[:2])

    def risky(ids):
        def edit(plan):
            for task in plan["phases"][0]["tasks"]:
                if task["id"] in ids:
                    task["risk"] = "high"
        return edit
    _commit_plan(root, mpath, risky(("P1.1",)), "P1.1 is high risk")
    code, said = _verb(root, "record-risk-confirmation.py", [
        mpath, PHASE, "--confirm-high-risk", "yes, commit P1.1 unattended",
        "--project", root])
    _commit_plan(root, mpath, risky(("P1.2",)), "P1.2 became high risk after")
    run = drive(M, root, mpath, answer=None)
    asked = [s for s in run["steps"] if s[:2] == ("decide", "high-risk")]
    last = run["prints"][-1][1]
    text = "\n".join(t for _c, t in run["prints"])
    check("hr1 a task the pre-given confirmation covers commits without asking, "
          "and the print says it was confirmed in advance: %r"
          % ((code, said, asked, text[-600:]),),
          code == 0 and tasks_of(mpath).get("P1.1", {}).get("status") == "done"
          and "high-risk P1.1 confirmed in advance" in text)
    check("hr2 THE TWIN: a task that became high-risk after the confirmation is "
          "not covered by it, and still stops at the high-risk decision: %r"
          % (last,),
          run["steps"][-1] == ("decide", "high-risk", None)
          and "decide high-risk P1.2" in last
          and tasks_of(mpath).get("P1.2", {}).get("status") == "in_progress")
    # A confirmation covers open work as it stood when it was given: a task
    # reopened after it is run again on a commit nobody confirmed.
    root, mpath = _repo("risk-reopen", task_ids=TASKS[:2])
    _commit_plan(root, mpath, risky(("P1.1",)), "P1.1 is high risk")
    _verb(root, "record-risk-confirmation.py", [
        mpath, PHASE, "--confirm-high-risk", "yes, commit P1.1 unattended",
        "--project", root])
    reopened = []

    def reopen_first(role, tid):
        if role == "executor" and tid == "P1.2" and not reopened:
            reopened.append(_verb(root, "audit-task.py", [
                "reopen", "P1.1", mpath, "--project-dir", root, "--reason",
                "the human wants P1.1 done again"]))
    run = drive(M, root, mpath, answer=None, on_dispatch=reopen_first)
    last = run["prints"][-1][1]
    check("hr3 a high-risk task reopened after the confirmation stops at the "
          "high-risk decision on its second run: %r" % ((reopened, last),),
          reopened and reopened[0][0] == 0
          and run["steps"][-1] == ("decide", "high-risk", None)
          and "decide high-risk P1.1" in last)


def _owner_types(root, prompt):
    """The owner typing `prompt`: the prompt hook run as Claude Code runs it,
    over the fixture project. Returns its exit code."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    done = subprocess.run(
        [sys.executable, os.path.join(_harness.HOOKS_DIR, "detect-plan-skip.py")],
        input=json.dumps({"hook_event_name": "UserPromptSubmit",
                          "session_id": "owner-session", "prompt": prompt}),
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)
    return done.returncode


def _standing_risk_cases(check):
    """A standing approval the owner armed lets a high-risk commit through with
    no decision, and every such commit leaves one row; with none armed the
    decision is asked as before."""
    M, why = _load("drive_phase_standing")
    if M is None:
        check("sh1 the driver loads", False, why)
        return
    import _journal_io
    import _tree_stamp

    def risky(plan):
        for task in plan["phases"][0]["tasks"]:
            if task["id"] == "P1.1":
                task["risk"] = "high"

    root, mpath = _repo("standing", task_ids=TASKS[:2])
    _commit_plan(root, mpath, risky, "P1.1 is high risk")
    armed_rc = _owner_types(root, "#approve-high-risk for the whole of P1")
    run = drive(M, root, mpath, answer=None)
    asked = [s for s in run["steps"] if s[:2] == ("decide", "high-risk")]
    rows = _journal_io.read_all(root)
    arms = [r for r in rows if r.get("action") == "risk.standing.armed"]
    uses = [r for r in rows if r.get("action") == "risk.standing.used"]
    digest, _basis = _tree_stamp.scope_digest(root, ["src/f1.txt"])
    use = (uses[0].get("details") or {}) if len(uses) == 1 else {}
    named = " ".join(str(v) for v in use.values())
    text = "\n".join(t for _c, t in run["prints"])
    check("sh1a with the approval armed, P1.1 commits and no high-risk decision "
          "is printed: %r" % ((armed_rc, asked, text[-500:]),),
          armed_rc == 0 and asked == []
          and tasks_of(mpath).get("P1.1", {}).get("status") == "done")
    check("sh1b ...and exactly one use row names P1.1, its scope digest and "
          "the arming row it used: %r" % ((uses, digest),),
          len(uses) == 1 and use.get("taskId") == "P1.1" and bool(digest)
          and digest in named and len(arms) == 1
          and str(arms[0].get("hash"))[:12] in named)

    root2, mpath2 = _repo("standing-none", task_ids=TASKS[:2])
    _commit_plan(root2, mpath2, risky, "P1.1 is high risk")
    run2 = drive(M, root2, mpath2, answer=None)
    last2 = run2["prints"][-1][1]
    uses2 = [r for r in _journal_io.read_all(root2)
             if r.get("action") == "risk.standing.used"]
    check("sh1c THE TWIN: with none armed the drive stops at the high-risk "
          "decision for P1.1, and writes no use row: %r" % ((last2, uses2),),
          run2["steps"][-1] == ("decide", "high-risk", None)
          and "decide high-risk P1.1" in last2 and uses2 == [])

    # Revoked after arming: the drive asks again, which is what a revocation
    # is for. A reader that took the first arming row and never looked
    # further would let this one through.
    root3, mpath3 = _repo("standing-revoked", task_ids=TASKS[:2])
    _commit_plan(root3, mpath3, risky, "P1.1 is high risk")
    _owner_types(root3, "#approve-high-risk")
    _owner_types(root3, "#revoke-high-risk")
    run3 = drive(M, root3, mpath3, answer=None)
    check("sh1d armed and then revoked, the drive stops at the high-risk "
          "decision again: %r" % (run3["steps"][-1:],),
          run3["steps"][-1] == ("decide", "high-risk", None))
    check("sh1 with a standing approval armed, a high-risk task's commit "
          "proceeds with no decision, and one journal row names the task, its "
          "scope digest and the approval it used; with none armed, the "
          "decision is asked as today",
          asked == [] and tasks_of(mpath).get("P1.1", {}).get("status") == "done"
          and len(uses) == 1 and use.get("taskId") == "P1.1" and bool(digest)
          and digest in named
          and run2["steps"][-1] == ("decide", "high-risk", None))


# A lint probe the plan names in `meta.buildCommands.lintProbe`, answering the
# `--changed` protocol the way `tools/prove-gates.py` does: it holds one lint, in
# the file `LP_PROBE_LINT` names, and runs that lint's rows only when the paths it
# is handed include that file. `LP_PROBE_MODE` picks what its rows do - all go
# red, one survives, a run that leaves a stray file behind, one that appends to
# the file `LP_PROBE_TOUCH` names, or one that hangs - and every argv it was
# started with is appended to `LP_PROBE_LOG`, outside the fixture.
_LINT_PROBE_STUB = (
    "import json, os, sys, time\n"
    "argv = sys.argv[1:]\n"
    "with open(os.environ['LP_PROBE_LOG'], 'a', encoding='utf-8') as fh:\n"
    "    fh.write(json.dumps(argv) + '\\n')\n"
    "changed = argv[argv.index('--changed') + 1:] if '--changed' in argv else None\n"
    "lint = os.environ.get('LP_PROBE_LINT', 'src/f1.txt')\n"
    "if changed is None:\n"
    "    print('stub probe: run without --changed')\n"
    "    sys.exit(2)\n"
    "if lint not in changed:\n"
    "    print('no changed file holds a lint a row names, so ran none')\n"
    "    sys.exit(0)\n"
    "mode = os.environ.get('LP_PROBE_MODE', 'green')\n"
    "if mode == 'hang':\n"
    "    time.sleep(40)\n"
    "if mode == 'survive':\n"
    "    print('  demo_drift   STAYED GREEN   the gate asserts nothing about this')\n"
    "    print('  ROW NOT PROVEN: red demo_drift in %s - STAYED GREEN' % (lint,))\n"
    "    sys.exit(1)\n"
    "if mode == 'dirty':\n"
    "    with open('stray-probe.txt', 'w', encoding='utf-8') as fh:\n"
    "        fh.write('left behind\\n')\n"
    "if mode == 'touch':\n"
    "    with open(os.environ['LP_PROBE_TOUCH'], 'a', encoding='utf-8') as fh:\n"
    "        fh.write('the probe left this\\n')\n"
    "print('2 of 2 gates proven red')\n"
    "print('2 of 2 guards proven to stay quiet on known-good input')\n")

LP_PROBE_KEY = "lintProbe"


def _probe_repo(prefix, probe=True, named=True):
    """A one-task phase-reviewed fixture, with the stub probe committed at
    `tools/prove-gates.py` when `probe` is set, and the plan naming it in
    `meta.buildCommands.lintProbe` when `named` is."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    if probe:
        os.makedirs(os.path.join(root, "tools"))
        _write_lf(os.path.join(root, "tools", "prove-gates.py"), _LINT_PROBE_STUB)
        _harness.git(root, "add", "tools/prove-gates.py")
        _harness.git(root, "commit", "-qm", "lint probe")
    if named:
        command = '"%s" tools/prove-gates.py' % (
            sys.executable.replace("\\", "/"),)
        _commit_plan(root, mpath, lambda plan: plan["meta"].setdefault(
            "buildCommands", {}).update({LP_PROBE_KEY: command}),
            "the plan names its lint probe")
    return root, mpath


@contextlib.contextmanager
def _probe_env(**pinned):
    """`LP_PROBE_LOG` at a fresh file outside the fixture, with every other
    `LP_PROBE_*` variable given set for the block; yields the log's path."""
    logdir = os.path.realpath(_harness.fixture_root("drive-probe-log-"))
    pinned = dict(pinned, LP_PROBE_LOG=os.path.join(logdir, "calls.jsonl"))
    held = dict((n, os.environ.get(n)) for n in pinned)
    os.environ.update(pinned)
    try:
        yield pinned["LP_PROBE_LOG"]
    finally:
        for name, value in held.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _harness.remove_tree(logdir)


def _probe_calls(log):
    """Every argv the stub probe logged, in order."""
    if not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def _probe_drive(M, prefix, lint="src/f1.txt", mode="green", probe=True,
                 named=True):
    """`(run, calls, root, mpath, seen)`: the drive to its end over a fixture
    whose stub probe holds `lint` and behaves as `mode`; `calls` is every argv
    the probe was started with, `seen` the verbs the drive ran."""
    root, mpath = _probe_repo(prefix, probe=probe, named=named)
    seen = _counting(M)
    with _probe_env(LP_PROBE_LINT=lint, LP_PROBE_MODE=mode) as log:
        run = drive(M, root, mpath, answer=_stop_at_other)
        calls = _probe_calls(log)
    return run, calls, root, mpath, seen


def _probe_ctx(root, mpath):
    """The drive context `lint_probe` reads, for a case calling it directly."""
    return {"project": root, "gitRoot": root, "manifest": mpath, "config": None,
            "phase": PHASE, "did": [], "log": [],
            "stateDir": os.path.join(root, ".claude", "state")}


def _probe_direct(M, root, mpath, state, head, **pinned):
    """`(result, did, calls, seconds)` of one `lint_probe` call over the
    fixture's phase with the `LP_PROBE_*` variables `pinned`."""
    ctx = _probe_ctx(root, mpath)
    with _probe_env(**pinned) as log:
        began = time.time()
        result = M.lint_probe(ctx, state, _phase_of(mpath), head)
        seconds = time.time() - began
        calls = _probe_calls(log)
    return result, ctx["did"], calls, seconds


def _lint_probe_cases(check):
    """At sign-off the lint probe the plan names runs over the files the phase
    changed: the rows of a lint the phase touched, both directions; none when it
    touched none, said so; a surviving row stops the sign-off naming it, and so
    does a probe that left the checkout changed or ran past its bound."""
    M, why = _load("drive_phase_lint_probe")
    if M is None:
        check("lp1 the driver loads", False, why)
        return
    run, calls, root, _mpath, _seen = _probe_drive(M, "probe-green")
    text = "\n".join(t for _c, t in run["prints"])
    sizes_green = [len(t.encode("utf-8")) for _c, t in run["prints"]]
    changed = calls[0][calls[0].index("--changed") + 1:] \
        if len(calls) == 1 and "--changed" in calls[0] else None
    check("lp1 a phase whose diff touches a lint's file runs the probe once at "
          "sign-off with --changed naming that file and no direction flag - "
          "so both directions run - signs off, and the did-line says the probe "
          "was green: %r" % ((calls, run["steps"][-1], text[-400:]),),
          changed is not None and "src/f1.txt" in changed
          and "--red" not in calls[0] and "--allow" not in calls[0]
          and run["steps"][-1] == DONE and _signed(_mpath)
          and "lint probe green" in run["prints"][-1][1])

    run, calls, root, mpath, _seen = _probe_drive(M, "probe-none",
                                                  lint="src/elsewhere.py")
    text = "\n".join(t for _c, t in run["prints"])
    sizes_none = [len(t.encode("utf-8")) for _c, t in run["prints"]]
    check("lp2 a phase touching no lint file runs none, and the did-line SAYS it "
          "ran none rather than reading as a proof: %r"
          % ((len(calls), run["steps"][-1], text[-400:]),),
          len(calls) == 1 and run["steps"][-1] == DONE and _signed(mpath)
          and "ran none" in text)

    # The byte bound over drives whose sign-off DID run the probe: dp3 measures
    # a fixture keeping none, so a probe clause that pushed the last print past
    # the bound was green there. The sign-off's did-line rides on two prints -
    # `done`, and the decision a moved parent stops at - so both are measured.
    M_nf, _w = _load("drive_phase_lint_probe_nff")
    real_verb = M_nf.run_verb

    def parent_moved(ctx, script, args, stdin=None):
        if script == "close-phase.py" and "--no-ff" not in args:
            return 3, "[close-phase] the parent moved\n", ""
        return real_verb(ctx, script, args, stdin=stdin)
    M_nf.run_verb = parent_moved
    run_nf, calls_nf, _r, _m, _seen = _probe_drive(M_nf, "probe-nff")
    sizes_nf = [len(t.encode("utf-8")) for _c, t in run_nf["prints"]]
    check("lp7 every success print of a drive whose sign-off ran the probe - "
          "green, ran-none, and the decision a moved parent stops at - is at "
          "most %d bytes: %r" % (BOUND, (sizes_green, sizes_none, sizes_nf)),
          sizes_green and sizes_none and len(calls_nf) == 1
          and run_nf["steps"][-1] == ("decide", "not-fast-forward", None)
          and all(c == 0 for c, _t in run_nf["prints"])
          and max(sizes_green + sizes_none + sizes_nf) <= BOUND)

    run, calls, root, mpath, seen = _probe_drive(M, "probe-survive",
                                                 mode="survive")
    code, last = run["prints"][-1]
    check("lp3 a surviving mutation stops the sign-off before the verb, naming "
          "the row: exit 1, the stop carries the probe's ROW NOT PROVEN line, "
          "`audit-task.py signoff` never ran and nothing is signed off: %r"
          % ((code, seen.get(("audit-task.py", "signoff")), last[-400:]),),
          code == 1 and "ROW NOT PROVEN: red demo_drift" in last
          and not seen.get(("audit-task.py", "signoff"))
          and not _signed(mpath))

    run, calls, root, mpath, seen = _probe_drive(M, "probe-dirty", mode="dirty")
    code, last = run["prints"][-1]
    check("lp4 a probe that leaves the checkout's status changed stops the "
          "sign-off naming what it left, even though it exited 0 - restoring "
          "the tree is part of its contract: %r"
          % ((code, seen.get(("audit-task.py", "signoff")), last[-400:]),),
          code == 1 and "stray-probe.txt" in last
          and not seen.get(("audit-task.py", "signoff"))
          and not _signed(mpath))

    # The probe a project keeps is run only when the plan names it: a file at
    # the path a release once hard-coded is not a command anybody declared.
    run, calls, root, mpath, _seen = _probe_drive(M, "probe-unnamed",
                                                  named=False)
    text = "\n".join(t for _c, t in run["prints"])
    check("lp5 a plan naming no meta.buildCommands.%s does not run the probe "
          "sitting at tools/prove-gates.py, signs off, and its did-line SAYS the "
          "step had no command - the key, unset: %r"
          % (LP_PROBE_KEY, (calls, run["steps"][-1], text[-300:]),),
          calls == [] and run["steps"][-1] == DONE and _signed(mpath)
          and "%s unset" % (LP_PROBE_KEY,) in text)

    # A green run held at a HEAD is not paid for again at that HEAD; at any
    # other it is - the twin, at a SHA of its own, so a hold that ignored the
    # head and swallowed every later run fails.
    root, mpath = _probe_repo("probe-held")
    same, did_same, ran_same, _s = _probe_direct(
        M, root, mpath, {"lintProbe": {"head": "a" * 40, "word": "green"}},
        "a" * 40)
    other, _did, ran_other, _s = _probe_direct(
        M, root, mpath, {"lintProbe": {"head": "a" * 40, "word": "green"}},
        "b" * 40)
    check("lp6 a green probe held at this HEAD is not run again, and is said "
          "held; asked at another HEAD it runs once: %r"
          % ((same, did_same, other, len(ran_same), len(ran_other)),),
          same is None and other is None and ran_same == []
          and len(ran_other) == 1
          and did_same == ["lint probe green (held)"])

    # The word the hold stores is the word it prints back: a run that ran none,
    # met again at its HEAD, is not a proof either.
    state = {}
    first, did_first, ran_first, _s = _probe_direct(
        M, root, mpath, state, "c" * 40, LP_PROBE_LINT="src/elsewhere.py")
    again, did_again, ran_again, _s = _probe_direct(
        M, root, mpath, state, "c" * 40, LP_PROBE_LINT="src/elsewhere.py")
    check("lp8 a run that ran none, held and met again at its HEAD, prints ran "
          "none and never green, and does not run the probe again: %r"
          % ((first, did_first, again, did_again, len(ran_first),
              len(ran_again)),),
          first is None and again is None and len(ran_first) == 1
          and ran_again == []
          and any("ran none" in d and "held" in d for d in did_again)
          and not any("green" in d for d in did_again))

    # A probe that does not come back is a stop naming the bound it ran past,
    # inside that bound - not a sign-off waiting on it.
    held_bound = getattr(M, "SIGNOFF_STEP_SECONDS", None)
    M.SIGNOFF_STEP_SECONDS = 2
    try:
        hung, did_hung, _ran, seconds = _probe_direct(
            M, root, mpath, {}, None, LP_PROBE_MODE="hang")
    finally:
        if held_bound is None:
            delattr(M, "SIGNOFF_STEP_SECONDS")
        else:
            M.SIGNOFF_STEP_SECONDS = held_bound
    hung_text = hung[1] if isinstance(hung, tuple) else ""
    check("lp9 a probe that runs past the drive's step bound is stopped and "
          "reported as a stop naming the timeout and the bound, well before "
          "the stub's own sleep would have ended: %r" % ((hung, did_hung, seconds),),
          isinstance(hung, tuple) and hung[0] == 1
          and "timed out" in hung_text and "2 s" in hung_text
          and seconds < 30)

    # A file another session had already modified keeps its two status letters
    # whatever the probe does to it, so only its bytes can say it moved. The
    # twin leaves it alone, so a comparison that always differs is red too.
    root, mpath = _probe_repo("probe-premod")
    with open(os.path.join(root, "src", "f2.txt"), "a", encoding="utf-8") as fh:
        fh.write("another session's edit\n")
    left, _did, _ran, _s = _probe_direct(
        M, root, mpath, {}, None, LP_PROBE_MODE="touch",
        LP_PROBE_TOUCH=os.path.join(root, "src", "f2.txt"))
    left_text = left[1] if isinstance(left, tuple) else ""
    with open(os.path.join(root, "src", "f2.txt"), "w", encoding="utf-8") as fh:
        fh.write("v0\nanother session's edit\n")
    quiet, did_quiet, _ran, _s = _probe_direct(M, root, mpath, {}, None)
    check("lp10 a file modified before the run and changed again by the probe "
          "stops the sign-off naming it, worded so it does not tell the "
          "operator to discard the edits that were there before; the same "
          "file left alone by a green probe is no stop: %r"
          % ((left, quiet, did_quiet),),
          isinstance(left, tuple) and left[0] == 1
          and "src/f2.txt" in left_text
          and "restore the tree" not in left_text
          and quiet is None and any("green" in d for d in did_quiet))
    # The key the driver reads and the key the default gate skips are one
    # name: a driver holding its own copy could be renamed without the gate's
    # default noticing, and the probe would be a gate step again.
    with open(_loader.script_path(DRIVER), encoding="utf-8") as fh:
        driver_source = fh.read()
    own_literal = re.findall(r'^LINT_PROBE_KEY\s*=\s*"', driver_source, re.M)
    check("lp11 the key naming the lint probe is read from the manifest "
          "vocabulary, not spelled a second time in the driver, and is the "
          "key a new phase's default gate skips: %r"
          % ((M.LINT_PROBE_KEY, own_literal),),
          M.LINT_PROBE_KEY is _vocab.LINT_PROBE_KEY
          and M.LINT_PROBE_KEY == LP_PROBE_KEY and own_literal == []
          and _vocab.signoff_only_entry(M.LINT_PROBE_KEY))


def _boot_cases(check):
    """`meta.runtimeBoot`, when the phase touched its app root, is a human's
    answer before the verdict: booted, or not reachable and not signed off."""
    M, why = _load("drive_phase_boot")
    if M is None:
        check("rb1 the driver loads", False, why)
        return

    def booting(app_root):
        def edit(plan):
            plan["meta"]["runtimeBoot"] = {"appRootPath": app_root,
                                           "launch": "open the app",
                                           "verify": "the home screen renders"}
        return edit
    root, mpath = _repo("boot", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, booting("src"), "boot")
    run = drive(M, root, mpath, answer=_stop_at_other)
    last = run["prints"][-1][1]
    check("rb1 a phase that touched meta.runtimeBoot.appRootPath stops before "
          "the verdict at a runtime-boot decision, and nothing is signed off: "
          "%r" % (last,),
          run["steps"][-1] == ("decide", "runtime-boot", None)
          and "runtimeBoot" in last and not _signed(mpath)
          and len(last.encode("utf-8")) <= BOUND)
    code_n, text_n = _next(M, root, mpath, "--answer", "not-reachable",
                           "--reason", "no simulator on this machine")
    code_r, text_r = _next(M, root, mpath)
    check("rb2 answered not-reachable, the drive stops with the phase unsigned, "
          "and the next `next` asks the boot question again: %r"
          % ((code_n, text_n, text_r),),
          code_n == 1 and "not signed off" in text_n and not _signed(mpath)
          and code_r == 0 and instruction(text_r)[1] == "runtime-boot")
    bare, _t = _next(M, root, mpath, "--answer", "booted")
    seen = "booted on the simulator; home renders, settings and back"
    code, text = _next(M, root, mpath, "--answer", "booted", "--reason", seen)
    summary = _phase_of(mpath).get("summary") or ""
    check("rb3 booted needs a reason; given one, the phase signs off and lands, "
          "and the summary keeps what was seen: %r" % ((bare, code, summary),),
          bare == M.E_USAGE and code == 0 and instruction(text) == DONE
          and _signed(mpath) and seen in summary)
    # The over-fire twin: a phase that touched nothing under the app root owes
    # no boot. A driver asking whenever `meta.runtimeBoot` is set fails here.
    root, mpath = _repo("boot-other", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, booting("app"), "boot elsewhere")
    run = drive(M, root, mpath, answer=_stop_at_other)
    check("rb4 THE OVER-FIRE TWIN: a phase whose files lie outside the app root "
          "signs off with no boot decision: %r" % (run["steps"][-3:],),
          run["steps"][-1] == DONE
          and not any(s[1] == "runtime-boot" for s in run["steps"]))


UNRELATED_GATE = "echo tests/unrelated_test.py 1 passed"


def _banner_cases(check):
    """A green gate that printed NO OVERLAP or TREE CHANGED is not reported as
    a plain green: the task's did-line carries it, and at the phase gate it is a
    decision before the verdict."""
    M, why = _load("drive_phase_banner")
    if M is None:
        check("gb1 the driver loads", False, why)
        return
    root, mpath = _repo("banner", task_ids=TASKS[:1], gate=(UNRELATED_GATE,),
                        per_task="phase", phase_gate=(UNRELATED_GATE,))
    run = drive(M, root, mpath, answer=_stop_at_other)
    text = "\n".join(t for _c, t in run["prints"])
    last = run["prints"][-1][1]
    check("gb1 a task gate that ran none of the task's paths is printed as "
          "`gate P1.1 green (NO OVERLAP)`, not a plain green: %r" % (text[:500],),
          "gate P1.1 green (NO OVERLAP)" in text)
    check("gb2 the same banner on the phase gate is a decision before the "
          "verdict, and nothing is signed off: %r" % (last,),
          run["steps"][-1] == ("decide", "gate-coverage", None)
          and "NO OVERLAP" in last and not _signed(mpath)
          and len(last.encode("utf-8")) <= BOUND)
    words = "the human: the suite exercises f1 through its import"
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    check("gb3 accepted with a reason, the phase signs off and the summary "
          "keeps the reason: %r" % ((code, text),),
          code == 0 and instruction(text) == DONE
          and words in (_phase_of(mpath).get("summary") or ""))


def _landing_cases(check):
    """A parent that moved is a human's call between a merge commit and leaving
    the phase unmerged, and the rule says never to rebase."""
    M, why = _load("drive_phase_landing")
    if M is None:
        check("nf1 the driver loads", False, why)
        return
    real = M.run_verb

    def moved(ctx, script, args, stdin=None):
        if script == "close-phase.py" and "--no-ff" not in args:
            return 3, "[close-phase] the parent moved\n", ""
        return real(ctx, script, args, stdin=stdin)
    M.run_verb = moved
    root, mpath = _repo("nff", task_ids=TASKS[:1], per_task="phase")
    run = drive(M, root, mpath, answer=_stop_at_other)
    last = run["prints"][-1][1]
    check("nf1 a moved parent offers no-ff and leave, with the rule that a "
          "human decides and that a rebase is never the answer: %r" % (last,),
          run["steps"][-1] == ("decide", "not-fast-forward", None)
          and "no-ff|leave" in last and "never rebase" in last
          and len(last.encode("utf-8")) <= BOUND)
    bare, _t = _next(M, root, mpath, "--answer", "leave")
    code, text = _next(M, root, mpath, "--answer", "leave", "--reason",
                       "the human merges it by hand tomorrow")
    phase = _phase_of(mpath)
    check("nf2 leave needs a reason; given one, the drive is done with the phase "
          "signed off and not merged, and the lock released: %r"
          % ((bare, code, text),),
          bare == M.E_USAGE and code == 0 and instruction(text) == DONE
          and "left unmerged" in text and _signed(mpath)
          and not phase.get("mergedAt")
          and "phase-%s" % (PHASE,) not in _verb(
              root, "audit-lock.py", ["status", "--project", root])[1])
    _landing_word_cases(check)


def _blocked_cases(check):
    """A blocked task has a way forward, named where the drive stops on it."""
    M, why = _load("drive_phase_blocked")
    if M is None:
        check("bk1 the driver loads", False, why)
        return
    root, mpath = _repo("stall", task_ids=TASKS[:1], gate=("false",))

    def block_it(kind, text):
        if kind[1] == "gate-red":
            return ["--answer", "block", "--reason", "the gate is red"]
        return False
    run = drive(M, root, mpath, answer=block_it)
    last = run["prints"][-1][1]
    attempts = _attempts(mpath, "P1.1")
    check("bk1 a phase whose only task is blocked with attempts left prints "
          "`decide stalled` with that task's remedy - `start`, which runs it "
          "and clears the block - and not `unblock`, which clears the block "
          "without running it: %r"
          % ((attempts, last),),
          run["steps"][-1] == ("decide", "stalled", None) and attempts == 1
          and _remedy(last) == ["start P1.1"]
          and len(last.encode("utf-8")) <= BOUND)
    single = drive(M, root, mpath, target="P1.1", cap=2)
    code, text = single["prints"][-1]
    ran = _verb(root, "audit-task.py", ["start", "P1.1", mpath,
                                        "--project-dir", root])
    check("bk2 the task drive's stop on the same blocked task names the same "
          "remedy, and the real verb takes it: %r" % ((text, ran),),
          code == 1 and _remedy(text) == ["start P1.1"] and ran[0] == 0)
    # The twin: a task whose attempts are spent is `unblock`'s, with the
    # human's reason. A remedy that named `start` for every blocked task fails
    # here, as the old single `unblock` rule fails bk1.
    root, mpath = _repo("stall-spent", task_ids=TASKS[:1], gate=("false",))

    def one_attempt(plan):
        plan["phases"][0]["tasks"][0]["maxAttempts"] = 1
    _commit_plan(root, mpath, one_attempt, "one attempt")
    run = drive(M, root, mpath, answer=block_it)
    last = run["prints"][-1][1]
    ran = _verb(root, "audit-task.py", ["unblock", "P1.1", mpath,
                                        "--project-dir", root, "--reason",
                                        "the human: try once more"])
    check("bk3 THE TWIN: a task blocked with its attempts spent is named "
          "`unblock` with the human's reason, and the real verb takes it: %r"
          % ((last, ran),),
          run["steps"][-1] == ("decide", "stalled", None)
          and _remedy(last) == ['unblock P1.1 --reason "<their words>"']
          and ran[0] == 0 and len(last.encode("utf-8")) <= BOUND)


def _remedy(text):
    """The per-task remedies a blocked stop names, in order, read off its
    `remedy (audit-task.py):` line."""
    for line in text.splitlines():
        if line.startswith("remedy (audit-task.py): "):
            return line[len("remedy (audit-task.py): "):].split("; ")
    return []


# --- a human's no hands back to the work ---------------------------------------
def _drive_state(root):
    """The driver's own state for the fixture phase, or {} when it has none."""
    path = os.path.join(root, ".claude", "state", "drive", "%s.json" % (PHASE,))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _add_task(root, mpath, gate="true", title="the remedy a human asked for"):
    """A task added to the phase the way a human's remedy is: through the verb."""
    with _Env(root):
        code, out = _verb(root, "audit-task.py", [
            "add", title, mpath, "--project-dir", root, "--phase", PHASE,
            "--files", "src/f1.txt", "--description", "do what the human asked",
            "--gate", gate, "--json"])
    try:
        return json.loads(out).get("id")
    except ValueError:
        return "(add exit %d: %s)" % (code, out[:200])


def _phase_gate_runs(module):
    """Count the phase gate's recorded runs - `run-test-gate.py` with no
    `--task` - through `module.run_verb`."""
    seen = {"runs": 0}
    real = module.run_verb

    def counted(ctx, script, args, stdin=None):
        if script == "run-test-gate.py" and "--task" not in args:
            seen["runs"] += 1
        return real(ctx, script, args, stdin=stdin)
    module.run_verb = counted
    return seen


def _decline_coverage_cases(check):
    """A gate that graded none of this work: `decline` keeps the human's words,
    drops the decision and hands back to the work; the gate after the remedy
    task is asked about again."""
    M, why = _load("drive_phase_decline_gate")
    if M is None:
        check("dc1 the driver loads", False, why)
        return
    root, mpath = _repo("decline-gc", task_ids=TASKS[:1], gate=(UNRELATED_GATE,),
                        per_task="phase", phase_gate=(UNRELATED_GATE,))
    run = drive(M, root, mpath, answer=_stop_at_other)
    words = "the human: no - the suite never imports f1"
    code, text = _next(M, root, mpath, "--answer", "decline", "--reason", words)
    check("dc1 decline on gate-coverage, with no task open, stops with the remedy "
          "of adding the task and drops the pending decision, the phase "
          "unsigned: %r" % ((run["steps"][-1], code, text),),
          run["steps"][-1] == ("decide", "gate-coverage", None)
          and code == M.E_STOPPED and "audit-task.py add" in text
          and "pending" not in _drive_state(root) and not _signed(mpath)
          and len(text.encode("utf-8")) <= BOUND)
    added = _add_task(root, mpath, gate=UNRELATED_GATE)
    run = drive(M, root, mpath, answer=_stop_at_other)
    check("dc2 the drive then runs the task added as the remedy, and the phase "
          "gate after it asks gate-coverage again: %r" % ((added, run["steps"]),),
          ("dispatch", "executor", added) in run["steps"]
          and run["steps"][-1] == ("decide", "gate-coverage", None))
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason",
                       "the human: the new suite reaches f1")
    summary = _phase_of(mpath).get("summary") or ""
    check("dc3 THE TWIN: an accept then signs off, and the summary keeps the "
          "human's no beside their yes: %r" % ((code, summary),),
          code == 0 and instruction(text) == DONE and words in summary)


def _reuse_gate_cases(check):
    """An accept at the head the green run was taken at reuses that run; a task
    closed after the accept is a new tree, so its gate is asked about again."""
    M2, why = _load("drive_phase_reuse_gate")
    if M2 is None:
        check("dc4 the driver loads", False, why)
        return
    seen = _phase_gate_runs(M2)
    root, mpath = _repo("reuse-gc", task_ids=TASKS[:1], gate=(UNRELATED_GATE,),
                        per_task="phase", phase_gate=(UNRELATED_GATE,))
    drive(M2, root, mpath, answer=_stop_at_other)
    held = _drive_state(root).get("phaseGate") or {}
    project, config = _evio.project_config_for(mpath, root)
    named = _evio.row_by_run(_evio.read_rows(project, config)["rows"],
                             held.get("runId"))
    check("dc4p the held phase-gate green names its run as the ledger keeps it - "
          "a row of the phase, at the head the drive holds it at - so a reuse "
          "below is a reuse of that run and not of an id no row carries: %r"
          % ((held, (named or {}).get("phaseId")),),
          named is not None and named.get("phaseId") == PHASE
          and not named.get("taskId") and held.get("head") == _head(root))
    before = seen["runs"]
    added = _add_task(root, mpath, gate=UNRELATED_GATE)
    code, text = _next(M2, root, mpath, "--answer", "accept", "--reason",
                       "the human: a false yes, given before the task ran")
    check("dc4 an accept at an unchanged head, gate and tree reuses the recorded "
          "green phase gate rather than running the suite again, and says so: %r"
          % ((before, seen["runs"], code, text),),
          before == 1 and seen["runs"] == before and "reused" in text)
    check("dc4b ...and the sign-off verb refusing after it (a task is open) drops "
          "the run the drive held, so the next sign-off measures again: %r"
          % ((code, sorted(_drive_state(root))),),
          code != 0 and "phaseGate" not in _drive_state(root))
    run = drive(M2, root, mpath, answer=_stop_at_other)
    check("dc5 THE TWIN: once the added task closes, the phase gate runs again "
          "at the new head and gate-coverage is asked again - the accept given "
          "before the task no longer holds: %r" % ((seen["runs"], run["steps"]),),
          seen["runs"] == before + 1
          and ("dispatch", "executor", added) in run["steps"]
          and run["steps"][-1] == ("decide", "gate-coverage", None)
          and not _signed(mpath))


RELATED_GATE = "echo src/f1.txt 1 passed"
STALE_WORDS = "the human: the suite reaches f1 after all"


def _to_coverage(prefix):
    """A one-task phase whose gate reaches none of the work, driven to the
    gate-coverage decision: `(driver, phase gate run count, root, mpath, run)`."""
    M, why = _load("drive_phase_stale_%s" % (prefix,))
    seen = _phase_gate_runs(M)
    root, mpath = _repo(prefix, task_ids=TASKS[:1], gate=(UNRELATED_GATE,),
                        per_task="phase", phase_gate=(UNRELATED_GATE,))
    run = drive(M, root, mpath, answer=_stop_at_other)
    return M, seen, root, mpath, run


def _stale_gate_cases(check):
    """A green phase gate held for reuse is reused only while the sign-off verb
    would still bind it: the same newest run, measured under the gate declared
    now, over the declared files as they stand. HEAD alone is not that - the
    gate can be retargeted, a declared file edited or a run recorded by hand
    with no commit."""
    to_coverage, words = _to_coverage, STALE_WORDS
    M, seen, root, mpath, run = to_coverage("stale-retarget")
    before = seen["runs"]
    with _Env(root):
        moved = _verb(root, "audit-task.py", ["retarget", PHASE, mpath,
                                              "--project-dir", root,
                                              "--gate-set", RELATED_GATE])
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    check("gr1 a gate retargeted after gate-coverage, at the same head: the "
          "accept signs off on ONE fresh run measured under the new gate, not "
          "the held run the verb would refuse: %r"
          % ((run["steps"][-1], moved[0], before, seen["runs"], code, text),),
          run["steps"][-1] == ("decide", "gate-coverage", None) and moved[0] == 0
          and code == 0 and instruction(text) == DONE and _signed(mpath)
          and seen["runs"] == before + 1 and "reused" not in text
          and len(text.encode("utf-8")) <= BOUND)

    M, seen, root, mpath, run = to_coverage("stale-edit")
    before = seen["runs"]
    with open(os.path.join(root, "src", "f1.txt"), "w", encoding="utf-8") as fh:
        fh.write("edited after the gate, never committed\n")
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    runs = seen["runs"]
    again, again_text = _next(M, root, mpath, "--answer", "accept", "--reason",
                              words)
    check("gr2 a declared file edited after the gate, uncommitted: the accept "
          "measures again rather than reusing a run whose scopeDigest moved, and "
          "that new run's banner is asked about again - the accept was given "
          "over the old run; a second accept reuses the new run and the sign-off "
          "verb takes the verdict. The landing after it may still refuse - the "
          "edit is in no commit, and close-phase grades the tip: %r"
          % ((before, runs, code, text, seen["runs"], again, again_text),),
          runs == before + 1 and "reused" not in text
          and instruction(text) == ("decide", "gate-coverage", None)
          and seen["runs"] == runs and "reused" in again_text and _signed(mpath)
          and "audit-task.py refused" not in again_text)

    M, seen, root, mpath, run = to_coverage("stale-handrun")
    before = seen["runs"]
    with _Env(root):
        hand = _verb(root, "run-test-gate.py", [mpath, PHASE, "--record",
                                                "--project-dir", root])
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    runs = seen["runs"]
    again, again_text = _next(M, root, mpath, "--answer", "accept", "--reason",
                              words)
    check("gr3 a run recorded by hand after the held one, at the same head: the "
          "verdict would bind the newer run, so the drive measures again rather "
          "than reading the held run's banners - and that run repeats the "
          "banners of the verdict it reuses, so they are asked about again "
          "(they were dropped on a reuse, which signed off over a banner nobody "
          "was shown); the second accept is over the new run: %r"
          % ((hand[0], before, runs, code, text, again, again_text),),
          hand[0] == 0 and runs == before + 1 and "reused" not in text
          and instruction(text) == ("decide", "gate-coverage", None)
          and "NO OVERLAP" in text and "reused" in again_text
          and again == 0 and _signed(mpath))


def _stale_reaccept_cases(check):
    """The accept answers the run whose banners it was shown, not the HEAD: a
    gate retargeted at the same head is another run, with banners of its own."""
    to_coverage, words = _to_coverage, STALE_WORDS
    other = "echo tests/elsewhere_spec.py 3 passed"
    M, seen, root, mpath, run = to_coverage("stale-reaccept")
    before = seen["runs"]
    with _Env(root):
        moved = _verb(root, "audit-task.py", ["retarget", PHASE, mpath,
                                              "--project-dir", root,
                                              "--gate-set", other])
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    check("gr4 a gate retargeted at the same head to another gate that reaches "
          "none of the work: the accept given over the old run's banners does "
          "not cover the new run's, so gate-coverage is asked again and nothing "
          "is signed off: %r" % ((moved[0], before, seen["runs"], code, text),),
          moved[0] == 0 and code == 0 and seen["runs"] == before + 1
          and instruction(text) == ("decide", "gate-coverage", None)
          and not _signed(mpath) and len(text.encode("utf-8")) <= BOUND)
    M, seen, root, mpath, run = to_coverage("stale-related-summary")
    with _Env(root):
        _verb(root, "audit-task.py", ["retarget", PHASE, mpath, "--project-dir",
                                      root, "--gate-set", RELATED_GATE])
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    summary = _phase_of(mpath).get("summary") or ""
    check("gr4b ...and a retarget to a gate that reaches the work signs off with "
          "a summary that keeps no accept of the old gate's banner - the run the "
          "verdict stands on printed none: %r" % ((code, summary),),
          code == 0 and _signed(mpath) and words not in summary
          and "Gate banner accepted" not in summary)
    M, seen, root, mpath, run = to_coverage("stale-same-run")
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    summary = _phase_of(mpath).get("summary") or ""
    check("gr4c THE TWIN: an accept over the run it was shown - no retarget, no "
          "edit - signs off on that run, reused, and the summary keeps the "
          "human's words: %r" % ((code, text, summary),),
          code == 0 and instruction(text) == DONE and "reused" in text
          and _signed(mpath) and "Gate banner accepted: %s" % (words,) in summary)


def _decline_boot_cases(check):
    """A boot that failed: `decline` hands back to the work, the remedy task is
    driven on its own, and the boot is asked again over the new tree."""
    M, why = _load("drive_phase_decline_boot")
    if M is None:
        check("db1 the driver loads", False, why)
        return

    def booting(plan):
        plan["meta"]["runtimeBoot"] = {"appRootPath": "src",
                                       "launch": "open the app",
                                       "verify": "the home screen renders"}
    root, mpath = _repo("decline-boot", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, booting, "boot")
    run = drive(M, root, mpath, answer=_stop_at_other)
    words = "the human: it boots and crashes on the settings screen"
    code, text = _next(M, root, mpath, "--answer", "decline", "--reason", words)
    check("db1 decline on runtime-boot stops with the remedy of adding the task "
          "and drops the pending decision: %r" % ((run["steps"][-1], code, text),),
          run["steps"][-1] == ("decide", "runtime-boot", None)
          and code == M.E_STOPPED and "audit-task.py add" in text
          and "pending" not in _drive_state(root) and not _signed(mpath))
    added = _add_task(root, mpath)
    single = drive(M, root, mpath, target=added)
    check("db2 the task added as the remedy is driven on its own, not refused "
          "for a decision the human already answered: %r" % (single["prints"][-1],),
          single["steps"][-1] == DONE
          and tasks_of(mpath).get(added, {}).get("status") == "done")
    run = drive(M, root, mpath, answer=_stop_at_other)
    seen = "booted on the simulator; settings renders now"
    code, text = _next(M, root, mpath, "--answer", "booted", "--reason", seen)
    summary = _phase_of(mpath).get("summary") or ""
    check("db3 the sign-off after it asks the boot again, booted then lands, and "
          "the summary keeps the human's no and their yes: %r"
          % ((run["steps"][-1], code, summary),),
          run["steps"][-1] == ("decide", "runtime-boot", None)
          and code == 0 and instruction(text) == DONE
          and words in summary and seen in summary)
    # A boot confirmed before a task closed was a boot of the old tree.
    root, mpath = _repo("reboot", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, booting, "boot")
    drive(M, root, mpath, answer=_stop_at_other)
    added = _add_task(root, mpath)
    code, text = _next(M, root, mpath, "--answer", "booted", "--reason",
                       "booted the tree before the task ran")
    run = drive(M, root, mpath, answer=_stop_at_other)
    check("db4 a boot confirmed before a task closed is asked again after it: "
          "%r" % ((code, text[-300:], run["steps"]),),
          ("dispatch", "executor", added) in run["steps"]
          and run["steps"][-1] == ("decide", "runtime-boot", None)
          and not _signed(mpath))


def _decline_answer_cases(check):
    """A reviewer answer a human says no to: `decline` on the triage keeps their
    words and hands back to the work; it is refused where nothing waits."""
    M, why = _load("drive_phase_decline_answers")
    if M is None:
        check("da1 the driver loads", False, why)
        return
    root, mpath = _repo("decline-ans", task_ids=TASKS[:1], per_task="phase")
    over = {"P1.1": {"answer": "diverges", "note": "it edits f2, not f1"}}
    run = drive(M, root, mpath, entry_over=over, answer=None)
    words = "the human: no - P1.1 must edit f1; fix it"
    code, text = _next(M, root, mpath, "--answer", "decline", "--reason", words)
    check("da1 decline on the triage's answers stops with the remedy of adding "
          "the task and drops the pending triage: %r" % ((code, text),),
          run["steps"][-1] == TRIAGE and "decline" in run["prints"][-1][1]
          and code == M.E_STOPPED and "audit-task.py add" in text
          and "pending" not in _drive_state(root) and not _signed(mpath))
    added = _add_task(root, mpath)
    run = drive(M, root, mpath, answer=None)
    _c, text_a = _next(M, root, mpath, "--answer", "accept", "--reason",
                       "the human: %s edits f1 now" % (added,))
    code, text = _next(M, root, mpath, "--answer", "sign-off", "--reason", SUMMARY)
    summary = _phase_of(mpath).get("summary") or ""
    check("da2 the remedy task is driven, the triage comes back with the answer "
          "still for a human, and once accepted the summary keeps the no: %r"
          % ((run["steps"], code, summary),),
          ("dispatch", "executor", added) in run["steps"]
          and run["steps"][-1] == TRIAGE
          and code == 0 and instruction(text) == DONE and words in summary)
    root, mpath = _repo("decline-none", task_ids=TASKS[:1], per_task="phase")
    drive(M, root, mpath, answer=None)
    code, text = _next(M, root, mpath, "--answer", "decline", "--reason", "no")
    check("da3 THE OVER-FIRE TWIN: a triage with no answer for a human refuses "
          "decline, and keeps the decision: %r" % ((code, text),),
          code == M.E_USAGE and "decline" in text
          and (_drive_state(root).get("pending") or {}).get("decision") == "triage")


def _decline_breach_cases(check):
    """An invariant breach is the same shape: a human's no hands back."""
    M, why = _load("drive_phase_decline_breach")
    if M is None:
        check("di1 the driver loads", False, why)
        return
    real = M.run_verb

    def breaching(ctx, script, args, stdin=None):
        if script == "verify-invariants.py":
            return 1, "BREACH src-untouched: src/f1.txt changed\n", ""
        return real(ctx, script, args, stdin=stdin)
    M.run_verb = breaching
    root, mpath = _repo("decline-inv", task_ids=TASKS[:1], per_task="phase")
    run = drive(M, root, mpath, answer=_stop_at_other)
    code, text = _next(M, root, mpath, "--answer", "decline", "--reason",
                       "the human: that invariant must hold")
    check("di1 decline on invariant-breach stops with the remedy of adding the "
          "task and drops the pending decision: %r"
          % ((run["steps"][-1], code, text),),
          run["steps"][-1] == ("decide", "invariant-breach", None)
          and code == M.E_STOPPED and "audit-task.py add" in text
          and "pending" not in _drive_state(root) and not _signed(mpath))
    _next(M, root, mpath)
    _c, said = _next(M, root, mpath, "--answer", "sign-off", "--reason", SUMMARY)
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason",
                       "the human: accepted after all")
    check("di2 THE TWIN: the breach is asked again at the next sign-off, and an "
          "accept then signs off: %r" % ((said, code, text),),
          instruction(said) == ("decide", "invariant-breach", None)
          and code == 0 and instruction(text) == DONE and _signed(mpath))


def _rereview_scope_cases(check):
    """Only a fix task closed `not-asked` under the phase key went unreviewed;
    one its own per-task reviewer answered did not."""
    M, why = _load("drive_phase_fix_scope")
    if M is None:
        check("fa1 the driver loads", False, why)
        return
    M.is_ancestor = lambda ctx, commit, head: False
    phase = {"id": PHASE, "reviewPerTask": "phase", "review": {"findings": [
        {"id": "P1-R1", "fixTask": "P1.4"}, {"id": "P1-R2", "fixTask": "P1.5"},
        {"id": "P1-R3", "fixTask": "P1.6"}]}, "tasks": [
        {"id": "P1.4", "fixes": ["P1-R1"], "commit": "a" * 40,
         "intentCheck": {"answer": "not-asked", "basis": "a fix task"}},
        {"id": "P1.5", "fixes": ["P1-R2"], "commit": "b" * 40,
         "reviewPerTask": "always",
         "intentCheck": {"answer": "matches", "basis": "its reviewer"}},
        {"id": "P1.6", "fixes": ["P1-R3"], "commit": "c" * 40,
         "intentCheck": {"answer": "matches", "basis": "answered"}}]}
    got = M.fixes_after({"config": {}, "gitRoot": "/nowhere"}, phase, "d" * 40)
    check("fa1 fixes_after lists the fix task closed `not-asked` under the phase "
          "key, and not one its own reviewer answered: %r" % (got,),
          got == ["P1.4"])


def _open_finding_cases(check):
    """The driver offers a sign-off the findings the verb would refuse it over:
    the one predicate is the verb's, so a fix task with no commit is still open."""
    M, why = _load("drive_phase_open_findings")
    if M is None:
        check("of1 the driver loads", False, why)
        return
    verb = _loader.load_script("audit-task.py", "audit_task_of")
    shapes = [
        {"id": "F-none", "severity": "med"},
        {"id": "F-nochange", "fixTask": "P1.4"},
        {"id": "F-cancelled", "fixTask": "P1.5", "status": "open"},
        {"id": "F-landed", "fixTask": "P1.6", "commit": "a" * 40},
        {"id": "F-fixed", "status": "fixed"},
        {"id": "F-carried", "status": "carried"}]
    phase = {"id": PHASE, "review": {"findings": shapes}}
    got = [f["id"] for f in M.open_findings(phase)]
    check("of1 a finding naming a fix task closed --no-change (no commit) is "
          "offered for disposition at sign-off, with the finding no task names "
          "and the one whose task never landed; landed, fixed and carried "
          "ones are not: %r" % (got,),
          got == ["F-none", "F-nochange", "F-cancelled"])
    check("of2 the driver's open set is the verb's, id for id: %r" % (got,),
          got == [f["id"] for f in verb.open_findings(phase)])
    # The other direction: a finding that IS settled by a landed fix is never
    # offered, so an over-wide predicate fails here.
    settled = {"id": PHASE, "review": {"findings": [shapes[3], shapes[4]]}}
    # The stuck-drive half: the verb refuses `add --fixes` for a finding that
    # already names a task, so the driver must not take `fix` for it.
    pending = {"decision": "triage", "findings": [
        {"id": "F-none"}, {"id": "F-nochange", "fixTask": "P1.4"}]}
    stuck = M.answer_refusal({"phase": PHASE}, pending, "fix", None,
                             ["F-nochange"])
    check("of4 --answer fix over a finding naming a task that never landed is "
          "refused by the driver, which says the finding already names a fix "
          "task and is dispositioned at sign-off - never that it is not open, "
          "since it is: %r" % (stuck,),
          bool(stuck) and "F-nochange already names a fix task (P1.4)" in stuck
          and "dispositioned at sign-off" in stuck and "not open" not in stuck)
    unknown = M.answer_refusal({"phase": PHASE}, pending, "fix", None,
                               ["F-gone"])
    check("of4b THE TWIN: a finding the triage does not hold at all is still "
          "refused as not open, not as naming a fix task: %r" % (unknown,),
          bool(unknown) and "not open: F-gone" in unknown
          and "already names" not in unknown)
    free = M.answer_refusal({"phase": PHASE}, pending, "fix", None, ["F-none"])
    check("of5 --answer fix over a finding no task names is not refused: %r"
          % (free,), free is None)
    check("of3 a phase whose findings are all settled offers none: %r"
          % (M.open_findings(settled),), M.open_findings(settled) == [])


def _landing_word_cases(check):
    """A stamp close-phase left uncommitted is named where the drive reports
    the landing."""
    M, why = _load("drive_phase_landing_word")
    if M is None:
        check("lw1 the driver loads", False, why)
        return
    said = {"out": ""}
    M.run_verb = lambda ctx, script, args, stdin=None: (0, said["out"], "")
    ctx = {"manifest": "m.json", "project": "/p", "phase": PHASE, "did": [],
           "log": []}
    said["out"] = ("[close-phase] P1 landed: audit/p1 fast-forwarded into main\n"
                   "  the stamp is not committed here: /p/main holds uncommitted "
                   "changes this landing did not write (x)\n")
    skipped, _s = M.land(ctx, {}, {"id": PHASE, "branch": "audit/p1"})
    said["out"] = ("[close-phase] P1 landed: audit/p1 fast-forwarded into main\n"
                   "  the stamp is NOT committed: the audit-state verb refused\n")
    failed, _s = M.land(ctx, {}, {"id": PHASE, "branch": "audit/p1"})
    said["out"] = ("[close-phase] P1 landed: audit/p1 fast-forwarded into main\n"
                   "  the stamp committed in /p as abc123\n")
    plain, _s = M.land(ctx, {}, {"id": PHASE, "branch": "audit/p1"})
    check("lw1 a landing whose stamp was not committed says so on the did-line, "
          "naming where it sits; one whose stamp was committed does not: %r"
          % ((skipped, plain),),
          (skipped or "").startswith("landed (") and "/p/main" in (skipped or "")
          and "uncommitted" in (skipped or "")
          and "uncommitted" in (failed or "") and "refused" in (failed or "")
          and (plain or "").startswith("landed (")
          and "uncommitted" not in (plain or ""))


def _chain_next_cases(check):
    """`finish`'s `done` print carries the chain's own fresh-context step
    exactly when the plan's own readiness names a phase beyond the one that
    just closed - never a guess, and never when nothing is ready."""
    M, why = _load("dp_chain_mod")
    check("cn0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return

    root = _harness.fixture_root("drive-chain-")
    mpath = os.path.join(root, "audit-plan.json")

    def _manifest(next_task_status):
        return {
            "meta": {"version": 2, "developmentBranch": "main"},
            "fileIndex": {},
            "phases": [
                {"id": "P1", "title": "first", "status": "done",
                 "desiredOutcome": "x", "blockedBy": [], "tasks": [
                    {"id": "P1.1", "status": "done", "blockedBy": [],
                     "dependsOn": []}]},
                {"id": "P2", "title": "second", "status": "pending",
                 "desiredOutcome": "y", "blockedBy": [], "tasks": [
                    {"id": "P2.1", "status": next_task_status,
                     "blockedBy": [], "dependsOn": []}]},
            ]}

    ctx = {"manifest": mpath, "project": root, "phase": "P1", "did": [],
          "log": []}
    M.release_lock = lambda ctx, state: None
    M.drop_state = lambda ctx: None

    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(_manifest("pending"), fh)
    out = M.finish(ctx, {}, "signed off (passed)")
    # Whether the next phase then starts from a cleared context is not measured
    # here: no recorded transcript of two real phases exists to read it from.
    check("cn1 a next phase the plan's own readiness names beyond the one "
          "that just closed gets the chain's fresh-context step, naming it: "
          "%r" % (out["lines"],),
          out["kind"] == "done"
          and any("clear context" in line and "P2" in line
                  for line in out["lines"]))

    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(_manifest("done"), fh)
    out2 = M.finish(ctx, {}, "signed off (passed)")
    check("cn2 THE TWIN: with nothing left ready, done carries no chain line "
          "at all - never printed on a guess: %r" % (out2["lines"],),
          out2["kind"] == "done"
          and not any("clear context" in line for line in out2["lines"]))


# --- waves: ready disjoint tasks run together, each in a tree of its own -------
# The gate every wave task declares asks the tree it runs in which source files
# differ from the commit the tree was cut at, and passes only when the answer is
# exactly the task's own file. A gate run in the phase tree while a sibling has
# edited it, or in a tree holding a sibling's bytes, is red by construction - so
# a green row is the evidence that the measured tree held only its own diff.
_OWN_DIFF = ("import subprocess, sys\n"
             "out = subprocess.run(['git', 'status', '--porcelain', '--', 'src'],\n"
             "                     capture_output=True, text=True).stdout\n"
             "seen = sorted(l[3:].strip() for l in out.splitlines() if l.strip())\n"
             "sys.exit(0 if seen == [sys.argv[1]] else 1)\n")
WAVE_LINE_BYTES = 200


def _wave_repo(prefix, width, red=(), per_task="phase", setup=None,
               spare_file=False, ci=None):
    """A two-task fixture whose config sets `executor.waveWidth` to `width`
    (left out when None) and roots task trees in a fixture directory of their
    own, and whose tasks' gates are the own-diff check - or a gate that always
    fails, for each id in `red`. `setup` is `executor.worktreeSetup`, and
    `spare_file` commits a third source file, for a task added later, and `ci`
    is the config's `ci` block when given."""
    root, mpath = _repo(prefix, task_ids=TASKS[:2], per_task=per_task)
    trees = os.path.realpath(_harness.fixture_root("drive-trees-%s-" % (prefix,)))
    cfg_path = os.path.join(root, ".claude", "audit.config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    executor = {"worktreeRoot": trees}
    if width is not None:
        executor["waveWidth"] = width
    if setup is not None:
        executor["worktreeSetup"] = setup
    if spare_file:
        with open(os.path.join(root, "src", "f3.txt"), "w", encoding="utf-8") as fh:
            fh.write("v0\n")
    cfg["executor"] = executor
    if ci is not None:
        cfg["ci"] = ci
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    with open(os.path.join(root, "check_own.py"), "w", encoding="utf-8") as fh:
        fh.write(_OWN_DIFF)
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    for n, task in enumerate(plan["phases"][0]["tasks"], 1):
        task["tests"]["gate"] = [
            '"%s" -c "import sys; sys.exit(1)"' % (sys.executable,)
            if task["id"] in red else
            '"%s" check_own.py src/f%d.txt' % (sys.executable, n)]
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "wave fixture"]):
        _harness.git(root, *argv)
    return root, mpath


def _dispatched(text, role="executor"):
    """The task ids every `dispatch` line of one print names for `role`."""
    found = []
    for line in text.splitlines():
        hit = _DISPATCH.match(line)
        if hit and hit.group(1).endswith(role):
            found.append(hit.group(2))
    return found


def _tree_of(root, task_id):
    return ((_drive_state(root).get("wave") or {}).get("trees") or {}).get(task_id)


def _file_wave_executor(root, mpath, task_id, text=None, then=None):
    """Play a wave executor: edit the task's file in ITS tree - to `text` when
    given - run `then(tree)` when given (what else the agent does there before
    filing), then make the agent's last act from the project, as an agent's
    shell does."""
    tree = _tree_of(root, task_id)
    if not tree:
        return 99, "no tree recorded for %s" % (task_id,)
    rel = "src/f%d.txt" % (TASKS.index(task_id) + 1,)
    _write_lf(os.path.join(tree, *rel.split("/")),
              text if text is not None else "changed by %s\n" % (task_id,))
    if then is not None:
        then(tree)
    return _verb(root, DRIVER, ["submit", task_id, "--role", "executor", mpath,
                                "--project-dir", root],
                 stdin=json.dumps(_executor_body(task_id)))


def _actions(root):
    import _journal_io
    return [r.get("action") for r in _journal_io.read_all(root)
            if isinstance(r, dict)]


def _rows_of(root, mpath, task_id):
    project, config = _evio.project_config_for(mpath, root)
    return [r for r in _evio.read_rows(project, config)["rows"]
            if isinstance(r, dict) and r.get("taskId") == task_id]


def _next_wave(M, root, mpath):
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root], out=said.append)
    return code, "\n".join(said)


def _wave_cases(check):
    M, why = _load("drive_phase_wave")
    if M is None:
        check("wv1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("wave", 2)
    code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    check("wv1 at waveWidth 2 two ready tasks with disjoint files are dispatched "
          "in ONE next, one dispatch line each, in id order, under the rule that "
          "sends them together: %r" % (first,),
          code == 0 and sent == ["P1.1", "P1.2"]
          and "dispatch these together in one message; then next" in first)
    lines = [ln for ln in first.splitlines() if ln.startswith("dispatch ")]
    check("wv2 every dispatch line of a wave stays inside %d bytes: %r"
          % (WAVE_LINE_BYTES, [len(ln.encode("utf-8")) for ln in lines]),
          lines and all(len(ln.encode("utf-8")) <= WAVE_LINE_BYTES for ln in lines))
    trees = [_tree_of(root, t) for t in ("P1.1", "P1.2")]
    check("wv3 each task has a tree of its own, outside the project: %r" % (trees,),
          all(trees) and trees[0] != trees[1]
          and not any(t.startswith(root + os.sep) for t in trees if t))
    filed = [_file_wave_executor(root, mpath, t) for t in sent]
    check("wv4 each executor's submit from the project files its return: %r"
          % (filed,), [c for c, _t in filed] == [0, 0])
    texts = dict((t, _read(_filed_path(mpath, t)).decode("utf-8")
                  if _filed_path(mpath, t) and os.path.exists(_filed_path(mpath, t))
                  else "") for t in sent)
    labels = dict((t, _stamp_field(json.loads(x or "{}").get("stamp"), "manifest"))
                  for t, x in texts.items())
    spelled = [p for t in sent for p in (root, _tree_of(root, t),
                                         os.path.realpath(root),
                                         os.path.realpath(_tree_of(root, t) or "-"))
               if p and any(p in x for x in texts.values())]
    check("wv4a a wave executor's filed return names its stamp's manifest by a "
          "project-relative label and carries no absolute machine path - neither "
          "the project's, nor the task tree's - anywhere in it: %r %r"
          % (labels, spelled),
          all(texts.values())
          and all(l and not os.path.isabs(l) for l in labels.values())
          and not spelled)
    code, second = _next_wave(M, root, mpath)
    rows = dict((t, _rows_of(root, mpath, t)) for t in ("P1.1", "P1.2"))
    green = dict((t, [r.get("status") for r in rs]) for t, rs in rows.items())
    keyed = dict((t, [((r.get("testedState") or {}).get("tree") or {}).get("key")
                      for r in rs]) for t, rs in rows.items())
    check("wv5 each task's recorded gate ran in its own tree and was green - the "
          "gate passes only where the tree's changed sources are exactly the "
          "task's own file - and each row names a tree: %r %r %r"
          % (green, keyed, second),
          green == {"P1.1": ["passed"], "P1.2": ["passed"]}
          and all(keyed[t] and keyed[t][0] for t in keyed)
          and keyed["P1.1"] != keyed["P1.2"])
    tasks = tasks_of(mpath)
    with open(os.path.join(root, "src", "f1.txt"), encoding="utf-8") as fh:
        f1 = fh.read()
    with open(os.path.join(root, "src", "f2.txt"), encoding="utf-8") as fh:
        f2 = fh.read()
    check("wv6 both tasks are integrated into the phase tree and closed against "
          "a commit each: %r" % ([(t, tasks[t].get("status"), tasks[t].get("commit"))
                                  for t in ("P1.1", "P1.2")],),
          all(tasks[t].get("status") == "done" and tasks[t].get("commit")
              for t in ("P1.1", "P1.2"))
          and tasks["P1.1"]["commit"] != tasks["P1.2"]["commit"]
          and f1 == "changed by P1.1\n" and f2 == "changed by P1.2\n")
    acts = [a for a in _actions(root) if a.startswith("wave.")
            or a in ("task.worktree", "task.integrated",
                     "task.integration.refused")]
    check("wv7 the journal records the wave: its start, a tree per task, an "
          "integration per task in id order, and its end: %r" % (acts,),
          acts == ["wave.start", "task.worktree", "task.worktree",
                   "task.integrated", "task.integrated", "wave.done"])
    gone = [t for t in trees if t and os.path.isdir(t)]
    check("wv8 a clean task tree is taken down once its task is closed: %r"
          % (gone,), all(trees) and not gone)

    # RED TWIN: the same wave with the gate measured in the phase tree. The
    # own-diff gate is red there - the executors' edits are in their trees -
    # so wv5's predicate fails for the mutant, which is what says it reads.
    mutant, _w = _load("drive_phase_wave_no_tree")
    real_gate = mutant.record_gate
    mutant.record_gate = lambda ctx, phase, task, tree=None: real_gate(
        ctx, phase, task)
    root_m, mpath_m = _wave_repo("wavem", 2)
    _code, first_m = _next_wave(mutant, root_m, mpath_m)
    for t in _dispatched(first_m):
        _file_wave_executor(root_m, mpath_m, t)
    _next_wave(mutant, root_m, mpath_m)
    green_m = dict((t, [r.get("status") for r in _rows_of(root_m, mpath_m, t)])
                   for t in ("P1.1", "P1.2"))
    check("wv5m RED TWIN: a driver that measures a wave task's gate in the phase "
          "tree records no green row for it: %r" % (green_m,),
          "passed" not in green_m["P1.1"] and "passed" not in green_m["P1.2"])


def _wave_red_sibling_cases(check):
    M, why = _load("drive_phase_wave_red")
    if M is None:
        check("wr1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("wavered", 2, red=("P1.1",))
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    for t in sent:
        _file_wave_executor(root, mpath, t)
    code, second = _next_wave(M, root, mpath)
    tasks = tasks_of(mpath)
    check("wr1 a red sibling does not hold back a green one: the first task's "
          "gate is red and the second is integrated and closed in the same next, "
          "and the red one's decision is what is printed: %r %r" % (sent, second),
          sent == ["P1.1", "P1.2"]
          and tasks["P1.2"].get("status") == "done" and tasks["P1.2"].get("commit")
          and tasks["P1.1"].get("status") == "in_progress"
          and instruction(second) == ("decide", "gate-red", None))
    check("wr2 the red task's tree is kept for its retry: %r"
          % (_tree_of(root, "P1.1"),),
          _tree_of(root, "P1.1") and os.path.isdir(_tree_of(root, "P1.1")))
    code, again = _next_wave(M, root, mpath)
    check("wr3 the decision is printed again until it is answered: %r" % (again,),
          code == 0 and instruction(again) == ("decide", "gate-red", None))


def _wave_parked_return_cases(check):
    M, why = _load("drive_phase_wave_parked")
    if M is None:
        check("wp1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("waveparked", 2, per_task="always")
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    # Only the first member's executor comes back; the second is graded as one
    # that returned nothing, and its decision is parked behind the first's
    # reviewer dispatch, which is due in the same print.
    _file_wave_executor(root, mpath, "P1.1")
    _code, second = _next_wave(M, root, mpath)
    parked = (((_drive_state(root).get("wave") or {}).get("parked") or {})
              .get("P1.2") or {})
    check("wp0 the fixture parks where it means to: the first member's reviewer "
          "is dispatched while the second's no-executor-return decision waits "
          "parked: %r %r %r" % (sent, parked, second),
          sent == ["P1.1", "P1.2"]
          and _dispatched(second, "reviewer") == ["P1.1"]
          and parked.get("decision") == "no-executor-return")
    # The return the decision is about is filed late, by the member itself.
    late = _file_wave_executor(root, mpath, "P1.2")
    _code, third = _next_wave(M, root, mpath)
    state = _drive_state(root)
    held = ((state.get("wave") or {}).get("parked") or {}).get("P1.2")
    pending = state.get("pending") or {}
    rows = [r.get("status") for r in _rows_of(root, mpath, "P1.2")]
    check("wp1 a no-executor-return decision parked while other dispatches were "
          "due is dropped on the next run once the member's return is filed, and "
          "the member advances: %r %r %r %r %r"
          % (late, held, pending, rows, third),
          late[0] == 0 and held is None
          and pending.get("decision") != "no-executor-return"
          and "no-executor-return" not in third and rows == ["passed"])


def _drive_source_decisions():
    """Every `no-<role>-return` name the driver's source can emit: the
    DECISIONS table's keys and any string constant of that shape in its AST, so
    a decision raised from a call site the table forgot is still named."""
    import ast
    with open(os.path.join(_output.SCRIPTS_DIR, "governance", DRIVER),
              encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    shape = re.compile(r"^no-.+-return$")
    return sorted(set(n.value for n in ast.walk(tree)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)
                      and shape.match(n.value)))


def _parked_return_cases(check):
    """One rule over every parked no-<role>-return decision: it is dropped once
    that role's return is filed for the start it was raised for."""
    M, why = _load("drive_phase_parked_return")
    if M is None:
        check("nr1 the driver loads", False, why)
        return
    root, mpath = _repo("parked-reviewer", task_ids=TASKS[:1], per_task="always")
    _next(M, root, mpath)
    _file_executor(root, mpath, "P1.1")
    _code, sent = _next(M, root, mpath)
    _code, asked = _next(M, root, mpath)
    held = (_drive_state(root).get("pending") or {})
    check("nr0 the fixture parks where it means to: the reviewer is dispatched, "
          "no return comes, and the next run parks the no-reviewer-return "
          "decision: %r %r" % ((instruction(sent), instruction(asked)), held),
          instruction(sent) == ("dispatch", "reviewer", "P1.1")
          and instruction(asked)[1] == "no-reviewer-return"
          and held.get("decision") == "no-reviewer-return")
    late = _file_reviewer(root, mpath, "P1.1")
    code, third = _next(M, root, mpath)
    pending = _drive_state(root).get("pending") or {}
    task = tasks_of(mpath).get("P1.1", {})
    check("nr1 a no-reviewer-return decision parked while the reviewer worked "
          "is dropped on the next run once the reviewer return is filed, and "
          "the task advances to its close: %r %r %r %r"
          % (late, third, pending, task.get("status")),
          late[0] == 0 and code == 0
          and pending.get("decision") != "no-reviewer-return"
          and "no-reviewer-return" not in third
          and task.get("status") == "done" and task.get("commit"))

    # The same decision parked in a wave, behind a sibling's printed one.
    wroot, wmpath = _wave_repo("parkedwave", 2, per_task="always")
    _code, first = _next_wave(M, wroot, wmpath)
    for t in _dispatched(first):
        _file_wave_executor(wroot, wmpath, t)
    _next_wave(M, wroot, wmpath)
    _next_wave(M, wroot, wmpath)
    wstate = _drive_state(wroot)
    parked = ((wstate.get("wave") or {}).get("parked") or {}).get("P1.2") or {}
    check("nr2 the fixture parks the second member's no-reviewer-return decision "
          "behind the first's: %r %r" % (wstate.get("pending"), parked),
          (wstate.get("pending") or {}).get("task") == "P1.1"
          and parked.get("decision") == "no-reviewer-return")
    # The first member's return comes; the second's has not. Its parked decision
    # still holds (the twin that fails a rule dropping parked decisions blindly)
    # and is what the drive prints once the first member has closed.
    _file_reviewer(wroot, wmpath, "P1.1")
    _code, held_text = _next_wave(M, wroot, wmpath)
    check("nr3 a parked no-reviewer-return decision whose reviewer return is "
          "still missing is kept and printed once the sibling has closed: %r"
          % (held_text,),
          "decide no-reviewer-return P1.2:" in held_text
          and tasks_of(wmpath)["P1.1"].get("status") == "done")
    wlate = _file_reviewer(wroot, wmpath, "P1.2")
    _code, after = _next_wave(M, wroot, wmpath)
    wstate = _drive_state(wroot)
    check("nr3b a no-reviewer-return decision parked in a wave is dropped on the "
          "next run once that member's reviewer return is filed, and the member "
          "closes: %r %r %r"
          % (wlate, after, wstate.get("pending")),
          wlate[0] == 0 and "no-reviewer-return" not in after
          and (wstate.get("pending") or {}).get("decision") != "no-reviewer-return"
          and tasks_of(wmpath)["P1.2"].get("status") == "done")

    # The rule is keyed by role: every role the drive files a return for, and
    # every no-<role>-return name its source can emit.
    names = _drive_source_decisions()
    roles = sorted(_fr.RETURN_ROLES)
    check("nr4 the source emits a no-<role>-return decision for each task role "
          "and the rule names exactly that role for it: %r %r"
          % (names, roles),
          all(M.parked_return_role("no-%s-return" % (r,)) == r for r in roles)
          and all("no-%s-return" % (r,) in names for r in roles))
    unhandled = [n for n in names
                 if M.parked_return_role(n) is None and n not in M.PHASE_DECISIONS]
    check("nr5 every no-*-return decision name the drive can emit is a task role "
          "the parked-return rule drops once filed, or a sign-off decision of "
          "no task - a new role's decision name fails here by name: %r"
          % (unhandled,), names and not unhandled)
    check("nr6 ALLOW: a decision of the same shape that names no role of "
          "RETURN_ROLES is not read as a role's: %r"
          % ([M.parked_return_role(n) for n in ("no-phase-review-return",
                                                "no-banana-return", "no-return",
                                                "gate-red", None)],),
          [M.parked_return_role(n) for n in ("no-phase-review-return",
                                             "no-banana-return", "no-return",
                                             "gate-red", None)] == [None] * 5)


# A member's record check, run as a gate entry in the member's tree: every
# record file the phase tree has committed is, in this tree, the phase tree's
# committed bytes, and no record file the phase tree no longer has is left over.
# The phase tree is the repository's main worktree, read off git's own list -
# a path written into the gate would be scrubbed from the recorded row, and the
# commit would then refuse a verdict measured under a different gate. Line
# endings are folded on both sides, since a checkout may convert them.
_RECORDS_MATCH = (
    "import os, subprocess, sys\n"
    "def git(cwd, *args):\n"
    "    return subprocess.run(['git', '-C', cwd] + list(args),\n"
    "                          capture_output=True).stdout\n"
    "root = git('.', 'worktree', 'list', '--porcelain').decode('utf-8')\\\n"
    "    .splitlines()[0][len('worktree '):]\n"
    "def names(raw):\n"
    "    return [p for p in raw.decode('utf-8').split('\\0') if p]\n"
    "def mine(rel):\n"
    "    try:\n"
    "        with open(rel, 'rb') as fh:\n"
    "            return fh.read().replace(b'\\r\\n', b'\\n')\n"
    "    except OSError:\n"
    "        return None\n"
    "want = names(git(root, 'ls-tree', '-r', '-z', '--name-only', 'HEAD', '--',\n"
    "                 'docs/audit'))\n"
    "bad = [p for p in want\n"
    "       if mine(p) != git(root, 'show', 'HEAD:' + p).replace(b'\\r\\n', b'\\n')]\n"
    "bad += [p for p in names(git('.', 'ls-files', '-z', '--', 'docs/audit'))\n"
    "        if p not in want and os.path.exists(p)]\n"
    "sys.stdout.write('records %d, differ %r\\n' % (len(want), bad))\n"
    "sys.exit(0 if want and not bad else 1)\n")


def _wave_records_repo(prefix):
    """The two-task wave fixture, P1.1's gate adding the record check against
    the phase tree and P1.2's gate red, so P1.2's tree is still there to read
    once the drive has gated it."""
    root, mpath = _wave_repo(prefix, 2, red=("P1.2",))
    with open(os.path.join(root, "check_records.py"), "w", encoding="utf-8") as fh:
        fh.write(_RECORDS_MATCH)
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    first = plan["phases"][0]["tasks"][0]
    first["tests"]["gate"].append('"%s" check_records.py' % (sys.executable,))
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "the record check"]):
        _harness.git(root, *argv)
    return root, mpath


def _work_bytes(tree):
    """`{path: bytes}` of every file in a tree outside its git link and the
    record directory - the member's work as it stands."""
    found = {}
    for here, dirs, files in os.walk(tree):
        rel_dir = os.path.relpath(here, tree).replace(os.sep, "/")
        dirs[:] = [d for d in dirs if d != ".git"
                   and (rel_dir + "/" + d).lstrip("./") != "docs/audit"]
        for name in files:
            rel = (rel_dir + "/" + name) if rel_dir != "." else name
            if rel == ".git":
                continue
            with open(os.path.join(here, name), "rb") as fh:
                found[rel] = fh.read()
    return found


def _records_wave(M, prefix):
    """Drive a records wave to its second `next`: the wave is cut, the phase
    tree then commits a task add, both executors file, and the drive gates.
    -> {root, mpath, added, committed, tree2, before, after, second}"""
    root, mpath = _wave_records_repo(prefix)
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    added = _add_task(root, mpath)
    # The added task's own gate, recorded on the phase tree, so the record-only
    # commit carries an evidence row beside the manifest and the journal.
    with _Env(root):
        gated = _verb(root, "run-test-gate.py", [mpath, PHASE, "--task", added,
                                                 "--record", "--project-dir", root])
    for argv in (["add", "--", "docs/audit"],
                 ["commit", "-qm", "record-only: a task add"]):
        _harness.git(root, *argv)
    committed = [p for p in _git_out(root, "show", "--name-only", "--format=",
                                     "HEAD").splitlines() if p.strip()]
    for t in sent:
        _file_wave_executor(root, mpath, t)
    tree2 = _tree_of(root, "P1.2")
    before = _work_bytes(tree2) if tree2 else {}
    base2 = _git_out(tree2, "rev-parse", "HEAD").strip() if tree2 else None
    _code, second = _next_wave(M, root, mpath)
    after = _work_bytes(tree2) if tree2 and os.path.isdir(tree2) else {}
    # The drive brings a member's tree to the phase head before its gate, so a
    # file the phase moved meanwhile (a sibling's integrated work) holds the
    # head's bytes afterwards - by design, and not the refresh's doing.
    moved = [p for p in _git_out(tree2, "diff", "--name-only", base2,
                                 "HEAD").splitlines() if p.strip()] \
        if base2 and os.path.isdir(tree2) else []
    # ...and each such file is then the head's, byte for byte: what the move
    # was for, and what a move that left a stale copy behind would not be.
    stale = [p for p in moved if not p.startswith("docs/audit/")
             and after.get(p) != _blob(tree2, "HEAD", p)]
    return {"root": root, "mpath": mpath, "added": added, "sent": sent,
            "committed": committed, "tree2": tree2, "before": before,
            "after": after, "second": second, "gated": gated, "moved": moved,
            "stale": stale}


def _blob(repo, rev, rel):
    """The bytes commit `rev` holds at `rel`, or None."""
    done = subprocess.run(_GIT + ["show", "%s:%s" % (rev, rel)], cwd=repo,
                          capture_output=True, timeout=60)
    return done.stdout if done.returncode == 0 else None


def _unmoved(run, key):
    """`run[key]`'s `{path: bytes}` without the paths the phase moved under the
    member's tree between its old base and the head it was brought to."""
    return dict((p, b) for p, b in run[key].items() if p not in run["moved"])


def _tree_plan_ids(tree):
    """The task ids the plan IN a member's tree holds, or None unreadable."""
    try:
        return sorted(_mio.tasks_by_id(_mio.load_manifest(os.path.join(
            tree, "docs", "audit", "audit-plan.json"))))
    except Exception:                                          # noqa: BLE001
        return None


def _wave_record_cases(check):
    M, why = _load("drive_phase_wave_records")
    if M is None:
        check("wq1 the driver loads", False, why)
        return
    run = _records_wave(M, "waverec")
    root, mpath = run["root"], run["mpath"]
    rows = [r.get("status") for r in _rows_of(root, mpath, "P1.1")]
    tasks = tasks_of(mpath)
    kinds = sorted(set(p.split("/")[2] if p.count("/") > 2 else "manifest"
                       for p in run["committed"] if p.startswith("docs/audit/")))
    check("wq1 a wave is cut, the phase tree then commits a record-only commit "
          "(a task add), and the member's gate is green: its record checks see "
          "the phase tree's manifest pair, journal and evidence: rows=%r "
          "status=%r committed=%r gated=%r %r" % (rows, (tasks.get("P1.1") or {}).get(
              "status"), run["committed"], run["gated"][0], run["second"][-300:]),
          run["sent"] == ["P1.1", "P1.2"] and run["added"] in tasks
          and kinds == ["evidence", "journal", "manifest"]
          and rows == ["passed"]
          and (tasks.get("P1.1") or {}).get("status") == "done")
    tree2 = run["tree2"]
    listed = _git_out(tree2, "diff", "--cached", "--name-only") if tree2 else "?"
    ids = _tree_plan_ids(tree2) if tree2 else None
    before, after = _unmoved(run, "before"), _unmoved(run, "after")
    check("wq2 the refresh touches record paths only - a member's work files, and "
          "every file the phase did not move, are byte-identical before and "
          "after it, and every file it moved holds the head's bytes: work=%r "
          "moved=%r stale=%r plan-ids=%r staged=%r"
          % (sorted(set(before) ^ set(after))
             or [p for p in before if before[p] != after.get(p)],
             run["moved"], run["stale"], ids, listed),
          tree2 and before and before == after and not run["stale"]
          and "src/f2.txt" not in run["moved"]
          and before.get("src/f2.txt") == b"changed by P1.2\n"
          and ids is not None and run["added"] in ids and listed == "")
    kept = [t for t in (_tree_of(root, "P1.1"),) if t and os.path.isdir(t)]
    check("wq3 a closed member's tree whose only difference from the phase tree "
          "is its refreshed records is still taken down: %r" % (kept,),
          not kept and (tasks.get("P1.1") or {}).get("status") == "done")


def _wave_record_mutant_cases(check):
    # RED TWINS, one per direction: a refresh that does nothing leaves the
    # member's record check red, and a refresh that also rewrites work paths
    # fails wq2's byte comparison - so both predicates are seen to read.
    idle, _w = _load("drive_phase_wave_records_idle")
    idle.refresh_member_records = lambda ctx, state, task, tree: None
    # Bringing the tree to the phase head brings the committed records too, so
    # the twin turns off both ways the records reach a member's tree.
    idle.advance_member = lambda ctx, state, task, tree: None
    run = _records_wave(idle, "waverecm")
    rows = [r.get("status") for r in _rows_of(run["root"], run["mpath"], "P1.1")]
    check("wq1m RED TWIN: a driver that does not refresh a member's records "
          "records no green row for the member whose gate reads them: %r"
          % (rows,), "passed" not in rows)
    wide, _w = _load("drive_phase_wave_records_wide")
    real = getattr(wide, "refresh_member_records", None)

    def over_work(ctx, state, task, tree):
        said = real(ctx, state, task, tree) if real is not None else None
        subprocess.run(["git", "-C", tree, "checkout", "-q", "HEAD", "--", "src"],
                       capture_output=True, timeout=60)
        return said
    wide.refresh_member_records = over_work
    run = _records_wave(wide, "waverecw")
    check("wq2m RED TWIN: a refresh that also checks out work paths leaves a "
          "member's work files changed: %r" % (run["after"].get("src/f2.txt"),),
          run["tree2"] and run["before"] != run["after"])


# A member's gate entry that validates the plan its own tree holds, with the
# plugin's validator: the validator's path is written into this file rather than
# into the gate text, which the recorded row scrubs of machine paths.
_VALIDATE_TREE = (
    "import subprocess, sys\n"
    "done = subprocess.run([sys.executable, %r, 'docs/audit/audit-plan.json'],\n"
    "                      capture_output=True, text=True, encoding='utf-8',\n"
    "                      errors='replace')\n"
    "sys.stdout.write(done.stdout[-600:] + done.stderr[-600:])\n"
    "sys.exit(done.returncode)\n")


def _sibling_records_repo(prefix):
    """The two-task wave fixture in the sharded layout with a SIBLING phase
    beside the wave's: P1.1's gate validates the plan in its own tree, and P1.2's
    gate is red, so P1.2's tree is still there to read once the drive gated it."""
    root, mpath = _wave_repo(prefix, 2, red=("P1.2",))
    with open(os.path.join(root, "check_valid.py"), "w", encoding="utf-8") as fh:
        fh.write(_VALIDATE_TREE % (_loader.script_path("validate-manifest.py"),))
    plan = _mio.load_manifest(mpath)
    first = plan["phases"][0]["tasks"][0]
    first["tests"]["gate"].append('"%s" check_valid.py' % (sys.executable,))
    sibling = json.loads(json.dumps(plan["phases"][0]["tasks"][1]))
    sibling.update({"id": "P2.1", "title": "the sibling's task",
                    "files": ["src/f3.txt"], "description": "change src/f3.txt"})
    sibling["tests"]["gate"] = ["true"]
    plan["phases"].append({"id": "P2", "title": "two", "status": "pending",
                           "desiredOutcome": "a sibling phase",
                           "review": {"model": "sonnet"}, "testGate": ["true"],
                           "tasks": [sibling]})
    plan["fileIndex"]["src/f3.txt"] = ["P2.1"]
    os.remove(mpath)
    _mio.save_sharded(mpath, plan)
    for argv in (["add", "-A"], ["commit", "-qm", "sharded, with a sibling phase"]):
        _harness.git(root, *argv)
    return root, mpath


def _sibling_add(root, mpath):
    """A task added to the SIBLING phase on the project, through the verb, and
    committed - the index and the sibling's shard in one commit."""
    with _Env(root):
        code, out = _verb(root, "audit-task.py", [
            "add", "a task the sibling phase gained", mpath, "--project-dir", root,
            "--phase", "P2", "--files", "src/f3.txt", "--description",
            "a sibling's task, added mid-wave", "--gate", "true", "--json"])
    try:
        added = json.loads(out).get("id")
    except ValueError:
        added = "(add exit %d: %s)" % (code, out[:200])
    for argv in (["add", "--", "docs/audit"],
                 ["commit", "-qm", "record-only: a sibling phase's task add"]):
        _harness.git(root, *argv)
    committed = [p for p in _git_out(root, "show", "--name-only", "--format=",
                                     "HEAD").splitlines() if p.strip()]
    return added, committed


def _wave_sibling_record_cases(check):
    M, why = _load("drive_phase_wave_sibling_records")
    if M is None:
        check("wq4 the driver loads", False, why)
        return
    root, mpath = _sibling_records_repo("wavesib")
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    added, committed = _sibling_add(root, mpath)
    for t in sent:
        _file_wave_executor(root, mpath, t)
    tree2 = _tree_of(root, "P1.2")
    _code, second = _next_wave(M, root, mpath)
    valid = _verb(tree2, "validate-manifest.py", ["docs/audit/audit-plan.json"]) \
        if tree2 and os.path.isdir(tree2) else (None, "no tree for P1.2")
    rows = [r.get("status") for r in _rows_of(root, mpath, "P1.1")]
    status = (tasks_of(mpath).get("P1.1") or {}).get("status")
    undeclared = [ln for ln in second.splitlines() if "undeclared-change" in ln]
    check("wq4 a task added to a sibling phase while a wave member is in flight "
          "leaves that member's records valid and its gate green (the sibling's "
          "add commits the index and its own shard; the member's tree then "
          "validates, its record-reading gate records a green row, and the drive "
          "reports no undeclared change): sent=%r added=%r committed=%r "
          "validate=%r rows=%r status=%r undeclared=%r second=%r"
          % (sent, added, committed, (valid[0], valid[1][-300:]), rows, status,
             undeclared, second[-300:]),
          sent == ["P1.1", "P1.2"] and str(added).startswith("P2.")
          and "docs/audit/phases/P2.json" in committed
          and "docs/audit/audit-plan.json" in committed
          and valid[0] == 0 and rows == ["passed"] and status == "done"
          and not undeclared)


def _wave_crash_cases(check):
    M, why = _load("drive_phase_wave_crash")
    if M is None:
        check("wc1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("wavecrash", 2)
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    real_close = M.close_task

    def crash_on_second(ctx, state, phase, task, intent_basis=None):
        if task["id"] == "P1.2":
            raise RuntimeError("the session died after P1.2 was integrated")
        return real_close(ctx, state, phase, task, intent_basis=intent_basis)
    M.close_task = crash_on_second
    crashed = None
    try:
        _next_wave(M, root, mpath)
    except RuntimeError as exc:
        crashed = str(exc)
    finally:
        M.close_task = real_close
    before = tasks_of(mpath)
    check("wc1 the fixture crashed where it means to: P1.1 closed, P1.2 "
          "integrated and not committed: %r %r"
          % (crashed, [(t, before[t].get("status")) for t in ("P1.1", "P1.2")]),
          crashed and before["P1.1"].get("status") == "done"
          and before["P1.2"].get("status") == "in_progress")
    calls = []
    real_run = M.run_verb

    def counting(ctx, script, args, stdin=None):
        calls.append(script)
        return real_run(ctx, script, args, stdin=stdin)
    M.run_verb = counting
    try:
        code, resumed = _next_wave(M, root, mpath)
    finally:
        M.run_verb = real_run
    after = tasks_of(mpath)
    integrated = [a for a in _actions(root) if a == "task.integrated"]
    check("wc2 a rerun after the crash neither re-integrates nor re-dispatches: "
          "no integration verb runs, no executor is dispatched, one row per "
          "integration, and P1.2 is closed: %r %r %r"
          % (calls, _dispatched(resumed), resumed),
          "integrate-task.py" not in calls and not _dispatched(resumed)
          and len(integrated) == 2 and after["P1.2"].get("status") == "done"
          and after["P1.2"].get("commit"))


def _preflight_repo(prefix, include, tasks=1):
    """A one-task fixture shaped like a testbed's P1.3: a vitest config whose
    `include` is `include` (JS source), a gate running vitest on the one test
    the task adds, and that test declared in `tests.add`."""
    root, mpath = _repo(prefix, task_ids=TASKS[:tasks],
                        gate=("npx vitest run lib/store.test.ts",))
    with open(os.path.join(root, "vitest.config.ts"), "w", encoding="utf-8") as fh:
        fh.write("const INCLUDE = %s;\nexport default { test: { include: %s } };\n"
                 % ("['tests/unit/**/*.test.ts']", include))
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["phases"][0]["tasks"][0]["tests"]["add"] = [
        "lib/store.test.ts: the store keeps its items"]
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "preflight fixture"]):
        _harness.git(root, *argv)
    return root, mpath


def _preflight_cases(check):
    """Task start refuses a declared test the runner will never collect: a
    definite NOT_COLLECTED is a `scope-gap` decision before any dispatch, and
    `widen` declares the runner config; a could-not-tell runner prints one line
    and the run dispatches."""
    M, why = _load("drive_phase_preflight")
    if M is None:
        check("pf1 the driver loads", False, why)
        return
    root, mpath = _preflight_repo("pfgap", "['tests/unit/**/*.test.ts']")
    code, text = _next_wave(M, root, mpath)
    task = tasks_of(mpath)["P1.1"]
    check("pf1 a vitest include of tests/unit/** and a test at lib/store.test.ts "
          "stops at decide scope-gap naming vitest and vitest.config.ts, before "
          "any dispatch, with the task still pending: %r" % (text,),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "vitest.config.ts" in text and "vitest" in text.split("vitest.config.ts")[0]
          and "widen|block" in text and not _dispatched(text)
          and task.get("status") == "pending")
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root, "--answer",
                       "widen"], out=said.append)
    after = "\n".join(said)
    task = tasks_of(mpath)["P1.1"]
    check("pf2 widen declares the runner config beside the task's files and the "
          "run goes on to dispatch it: %r %r" % (after, task.get("files")),
          code == 0 and "vitest.config.ts" in (task.get("files") or [])
          and "src/f1.txt" in (task.get("files") or [])
          and _dispatched(after) == ["P1.1"])
    root, mpath = _preflight_repo("pfblock", "['tests/unit/**/*.test.ts']")
    _next_wave(M, root, mpath)
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root, "--answer",
                       "block", "--reason", "the human will widen it by hand"],
                      out=said.append)
    check("pf3 block blocks the task and dispatches nothing: %r" % ("\n".join(said),),
          code == 0 and tasks_of(mpath)["P1.1"].get("status") == "blocked"
          and not _dispatched("\n".join(said)))
    root, mpath = _preflight_repo("pfunsure", "INCLUDE")
    code, text = _next_wave(M, root, mpath)
    lines = [ln for ln in text.splitlines() if "could not tell" in ln]
    check("pf4 a runner whose include is a variable could not be read: ONE line "
          "says so and the run dispatches: %r" % (text,),
          code == 0 and len(lines) == 1 and _dispatched(text) == ["P1.1"]
          and "scope-gap" not in text)
    root, mpath = _preflight_repo("pfwave", "['tests/unit/**/*.test.ts']", tasks=2)
    cfg_path = os.path.join(root, ".claude", "audit.config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["executor"] = {"waveWidth": 2}
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    code, text = _next_wave(M, root, mpath)
    check("pf5 the same stop holds at a wave width above 1: %r" % (text,),
          instruction(text) == ("decide", "scope-gap", None)
          and not _dispatched(text))
    root, mpath = _preflight_repo("pftask", "['tests/unit/**/*.test.ts']")
    said = []
    with _Env(root):
        code = M.main(["next", "P1.1", mpath, "--project-dir", root],
                      out=said.append)
    text = "\n".join(said)
    check("pf6 a width-1 run of ONE task, named by its id, stops at the same "
          "scope-gap before any start: %r" % (text,),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and not _dispatched(text)
          and tasks_of(mpath)["P1.1"].get("status") == "pending")
    root, mpath = _preflight_repo("pfrule", "['tests/unit/**/*.test.ts']")
    _next_wave(M, root, mpath)
    _code, after = _answer_wave(M, root, mpath, "--answer", "widen")
    rule = _loader.load_script("audit-lookup.py", "lookup_for_pf7",
                               cache=False).WIDEN_RULE
    brief = _brief_of(root, after, "P1.1")
    plain_root, plain_mpath = _repo("pfplain", task_ids=TASKS[:1])
    _code, plain = _next_wave(M, plain_root, plain_mpath)
    check("pf7 the executor of a task that declares a test is dispatched with "
          "the widen rule in its brief, and a task declaring none is not: %r %r"
          % (rule, _dispatched(after)),
          _dispatched(after) == ["P1.1"] and rule in brief
          and rule not in _brief_of(plain_root, plain, "P1.1"))


def _wave_width_cases(check):
    """A width outside the vocabulary stops the drive by name; `auto` is read
    with its basis; an undeclared path is a decision, and `widen` declares it,
    re-gates on the phase tree and closes the task."""
    M, why = _load("drive_phase_wave_width")
    if M is None:
        check("wz1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("wavezero", 0)
    code, text = _next_wave(M, root, mpath)
    check("wz1 executor.waveWidth 0 stops the drive by name and starts nothing - "
          "never a drive that runs no task, successfully: %r" % (text,),
          code == 1 and "executor.waveWidth" in text
          and all(t.get("status") == "pending" for t in tasks_of(mpath).values()))
    cores = os.cpu_count()
    width, basis, problem = M.wave_width({"executor": {"waveWidth": "auto"}})
    check("wa1 `auto` is the core count less two, at least 1, with that basis: "
          "%r" % ((width, basis, problem, cores),),
          problem is None and width == max(1, (cores or 3) - 2)
          and (("%d cores less two" % (cores,)) in basis if cores else "1" in basis))
    check("wa2 an absent key is width 1 and says so: %r" % (M.wave_width({}),),
          M.wave_width({})[:1] == (1,) and "absent" in M.wave_width({})[1])

    root, mpath = _wave_repo("waveundeclared", 2)
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    tree = _tree_of(root, "P1.2")
    if tree:
        with open(os.path.join(tree, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("written by P1.2, declared by nobody\n")
    for t in sent:
        _file_wave_executor(root, mpath, t)
    code, second = _next_wave(M, root, mpath)
    acts = [a for a in _actions(root) if a.startswith("task.integ")]
    check("wu1 a path the task changed and never declared is a decision naming "
          "it, reached after the sibling closed, and nothing of it is in the "
          "phase tree yet: %r %r" % (second, acts),
          instruction(second) == ("decide", "undeclared-change", None)
          and "notes.txt" in second
          and tasks_of(mpath)["P1.1"].get("status") == "done"
          and not os.path.exists(os.path.join(root, "notes.txt"))
          and acts == ["task.integrated"])
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root, "--answer",
                       "widen"], out=said.append)
    third = "\n".join(said)
    task = tasks_of(mpath)["P1.2"]
    check("wu2 widen declares the path, integrates it, re-gates on the phase tree "
          "and closes the task: %r %r" % (third, task.get("files")),
          code == 0 and "notes.txt" in (task.get("files") or [])
          and task.get("status") == "done" and task.get("commit")
          and "re-gate P1.2 green" in third
          and os.path.isfile(os.path.join(root, "notes.txt")))


# --- a follower a red gate owes: regenerated, or widened, from its row ----------
# The gate a follower case declares: green while `path` holds `want`, else red
# with the one line a step prints for the follower it owes - spelled here from
# the format, not by `_evidence_io.follower_line`, so the reader is held to the
# line as documented rather than to whatever its own writer emits.
_FOLLOWER_GATE = ("import sys\n"
                  "with open(%r) as fh:\n"
                  "    ok = fh.read().strip() == %r\n"
                  "if not ok:\n"
                  "    print(%r)\n"
                  "sys.exit(0 if ok else 1)\n")


def _follower_repo(prefix, rel, recipe, owner, wave=False, browser=False):
    """A one-task fixture (two in a wave) whose last task's gate owes `rel` while
    it does not read `current`; `rel` is committed `stale`, and `map.fresh`
    holds what a recipe copies in."""
    root, mpath = (_wave_repo(prefix, 2) if wave
                   else _repo(prefix, task_ids=TASKS[:1]))
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    _write_lf(os.path.join(root, *rel.split("/")), "stale\n")
    _write_lf(os.path.join(root, "map.fresh"), "current\n")
    record = dict({"path": rel, "recipe": recipe, "owner": owner},
                  **({"needsBrowser": True} if browser else {}))
    _write_lf(os.path.join(root, "check_follower.py"), _FOLLOWER_GATE % (
        rel, "current", "FOLLOWER-OWED " + json.dumps(record)))
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["phases"][0]["tasks"][-1]["tests"]["gate"] = [
        '"%s" check_follower.py' % (sys.executable,)]
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "follower fixture"]):
        _harness.git(root, *argv)
    return root, mpath


def _follower_cases(check):
    M, why = _load("drive_phase_follower")
    if M is None:
        check("fw0 the driver loads", False, why)
        return
    root, mpath = _follower_repo("follow", "docs/map.txt",
                                 "git show HEAD:map.fresh > docs/map.txt", "check_map")
    run = drive(M, root, mpath, cap=8)
    task = tasks_of(mpath)["P1.1"]
    sha = task.get("commit") or "HEAD"
    carried = _git_out(root, "show", "--name-only", "--format=", sha).split()
    held = _git_out(root, "show", "%s:docs/map.txt" % (sha,)).strip()
    said = "\n".join(t for _c, t in run["prints"])
    gates = [r.get("status") for r in _rows_of(root, mpath, "P1.1")]
    check("the drive regenerates that follower by its recipe in the task tree, the "
          "task commit carries it, and the second gate is green with no decision "
          "printed: %r" % ((run["steps"], carried, held, gates),),
          run["steps"] == expected_sequence(["P1.1"])
          and task.get("status") == "done" and "docs/map.txt" in carried
          and held == "current" and gates == ["failed", "passed"]
          and "docs/map.txt" in (task.get("files") or [])
          and "decide gate-red" not in said and "docs/map.txt regenerated" in said)

    recipe = "git show HEAD:map.fresh > docs/map.txt"
    root, mpath = _follower_repo("followshot", "docs/map.txt", recipe, "shots",
                                 browser=True)
    run = drive(M, root, mpath, cap=2)
    left = _read(os.path.join(root, "docs", "map.txt"))
    told = run["prints"][-1][1]
    subprocess.run(recipe, shell=True, cwd=root, check=True, timeout=60)
    after = drive(M, root, mpath, cap=1)
    check("fw2 a recipe that needs a browser is never run by the drive: it prints "
          "the orchestrator one instruction naming it, and the next drive after "
          "the orchestrator ran it gates green and goes on: %r"
          % ((told, left, after["steps"]),),
          "follow P1.1: run `%s`" % (recipe,) in told and left == b"stale\n"
          and "docs/map.txt" in (tasks_of(mpath)["P1.1"].get("files") or [])
          and after["steps"] == [("dispatch", "reviewer", "P1.1")])


def _follower_wave_cases(check):
    M, why = _load("drive_phase_follower_wave")
    if M is None:
        check("fh0 the driver loads", False, why)
        return
    root, mpath = _follower_repo("followhand", "notes.txt", None, "check_notes",
                                 wave=True)
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    prints, reply = [], []
    for _ in range(6):
        said = []
        with _Env(root):
            M.main(["next", PHASE, mpath, "--project-dir", root] + reply,
                   out=said.append)
        text = "\n".join(said)
        prints.append(text)
        reply = []
        if instruction(text) == ("decide", "gate-red", None) and "P1.2" in text:
            # The hand the lint asked for, in the member's own tree.
            _write_lf(os.path.join(_tree_of(root, "P1.2"), "notes.txt"), "current\n")
            reply = ["--answer", "rerun"]
        elif all(t.get("status") == "done" for t in tasks_of(mpath).values()):
            break
    task = tasks_of(mpath)["P1.2"]
    notes = " ".join(str(n) for n in task.get("notes") or [])
    said = "\n".join(prints)
    check("a hand-edited follower owed by a lint is widened with the lint's record "
          "as its basis, and no undeclared-change decision is printed: %r"
          % ((task.get("status"), task.get("files"), notes, prints),),
          task.get("status") == "done" and "notes.txt" in (task.get("files") or [])
          and "owed by check_notes on run" in notes
          and "undeclared-change" not in said
          and _read(os.path.join(root, "notes.txt")) == b"current\n")


def _follower_map_cases(check):
    """A green gate owes nothing, so the module map a member regenerated itself
    reaches integration undeclared: its owner's recipe is what decides it."""
    M, why = _load("drive_phase_follower_map")
    if M is None:
        check("fm0 the driver loads", False, why)
        return
    import _deps
    root, mpath, guide, fresh, prints = _drive_follower_map(M, "followmap")
    task = tasks_of(mpath)["P1.2"]
    notes = " ".join(str(n) for n in task.get("notes") or [])
    said = "\n".join(prints)
    held = _git_out(root, "show", "%s:%s" % (task.get("commit") or "HEAD", guide))
    check("a wave member that regenerated the module map itself, with its gate "
          "green, is integrated with the map widened on the owner's basis and no "
          "undeclared-change decision printed (%r)"
          % ((task.get("status"), task.get("files"), notes, prints),),
          task.get("status") == "done" and guide in (task.get("files") or [])
          and "_deps.map_drift" in notes and _deps.MAP_RECIPE in notes
          and "undeclared-change" not in said
          and fresh is not None and "a map from before" not in fresh
          and held == fresh)


def _drive_follower_map(M, prefix, sharded=False):
    """The two-member wave whose second member regenerated the module map in
    its own tree, the map undeclared; in the sharded layout when `sharded`, so
    the task commit is held to the index HEAD carries. Up to six `next`s, until
    every task is done. `(root, mpath, guide, fresh, prints)`, `fresh` the map
    the member wrote, None when the wave made no tree."""
    import _deps
    root, mpath = _wave_repo(prefix, 2)
    if sharded:
        plan = _mio.load_manifest(mpath)
        os.remove(mpath)
        _mio.save_sharded(mpath, plan)
    # THE ANCHOR ALONE, NOT THE PLUGIN'S SCRIPTS: the map's owner here is the
    # fixture's own `_deps.py`, which needs `_output` to start and maps the
    # modules it finds beside it. Over a copy of every script it read the whole
    # plugin on each of its runs - the member's and the recipe's - and the copy
    # was committed, then checked out into every task tree; over the anchor it
    # reads one module, and the recipe still writes the map the same way.
    os.makedirs(os.path.join(root, "plugins", "audit", "scripts"))
    shutil.copy(os.path.join(_output.SCRIPTS_DIR, "_output.py"),
                os.path.join(root, "plugins", "audit", "scripts", "_output.py"))
    shutil.copytree(_output.LINTS_DIR, os.path.join(root, "tools", "lints"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    guide = "PLUGIN-BUILD-GUIDE.md"
    with open(os.path.join(_output.REPO_ROOT, guide), encoding="utf-8") as fh:
        text = fh.read()
    block = _deps._fenced_block_after(text, _deps._GUIDE_HEADING)
    _write_lf(os.path.join(root, guide),
              text.replace(block, "a map from before this change\n", 1))
    with open(os.path.join(root, ".gitignore"), "a", encoding="utf-8") as fh:
        fh.write("__pycache__/\n")
    for argv in (["add", "-A"], ["commit", "-qm", "the module map's owner"]):
        _harness.git(root, *argv)
    _code, first = _next_wave(M, root, mpath)
    tree, fresh = _tree_of(root, "P1.2"), None
    if tree:
        subprocess.run([sys.executable, os.path.join(
            tree, "tools", "lints", "_deps.py"), "--write-map"],
            cwd=tree, check=True, capture_output=True, timeout=120)
        fresh = _read(os.path.join(tree, guide)).decode("utf-8")
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    prints = []
    for _ in range(6):
        said = []
        with _Env(root):
            M.main(["next", PHASE, mpath, "--project-dir", root], out=said.append)
        prints.append("\n".join(said))
        if all(t.get("status") == "done" for t in tasks_of(mpath).values()):
            break
    return root, mpath, guide, fresh, prints


# The case's title is the task's tests.add clause, verbatim.
_FOLLOWER_INDEX_CLAUSE = ("a wave member widened by a follower path at integration "
                          "is committed and closed in one next, with no refusal "
                          "for an uncommitted index")


def _follower_index_cases(check):
    """The widening `scope` writes a fileIndex row; the task commit is held to
    the index HEAD carries, so that row has to be committed before it."""
    M, why = _load("drive_phase_follower_index")
    if M is None:
        check("fi0 the driver loads", False, why)
        return
    root, mpath, guide, _fresh, prints = _drive_follower_map(
        M, "followindex", sharded=True)
    task = tasks_of(mpath)["P1.2"]
    widened = [p for p in prints if "P1.2 widened by %s" % (guide,) in p]
    refused = [p for p in prints if "REFUSED" in p or "stopped" in p]
    head_index = _git_out(root, "show", "HEAD:docs/audit/audit-plan.json")
    try:
        row = (json.loads(head_index).get("fileIndex") or {}).get(guide)
    except ValueError:
        row = None
    carried = _git_out(root, "show", "--name-only", "--format=",
                       task.get("commit") or "HEAD").split()
    check("%s (the print that widens the member by %s also closes it; no print "
          "refuses or stops; HEAD's index carries the row and the task commit "
          "the map): widened=%r refused=%r row=%r carried=%r status=%r"
          % (_FOLLOWER_INDEX_CLAUSE, guide, widened, refused, row, carried,
             task.get("status")),
          len(widened) == 1 and "closed P1.2 at" in widened[0]
          and not refused and task.get("status") == "done"
          and "P1.2" in (row or []) and guide in carried)


def _follower_retire_cases(check):
    """A follower path the integration wrote is the phase tree's to hold: its
    bytes are its owner's recipe run over the phase tree, so a member's own
    copy differing from them is not work the phase tree lacks."""
    M, why = _load("drive_phase_follower_retire")
    if M is None:
        check("fr0 the driver loads", False, why)
        return
    base = _harness.fixture_root("drive-retire-")
    try:
        tree, phase_tree = os.path.join(base, "member"), os.path.join(base, "phase")
        os.makedirs(phase_tree)
        os.makedirs(tree)
        _harness.git(tree, "init", "-q")
        for rel in ("map.md", "src.txt"):
            _write_lf(os.path.join(tree, rel), "base\n")
        for argv in (["add", "-A"], ["commit", "-qm", "base"]):
            _harness.git(tree, *argv)
        _write_lf(os.path.join(tree, "map.md"), "the member's map\n")
        _write_lf(os.path.join(phase_tree, "map.md"), "the phase tree's map\n")
        _write_lf(os.path.join(phase_tree, "src.txt"), "base\n")
        ctx = {"gitRoot": phase_tree}
        check("fr1 a member whose only differing path is a follower the "
              "integration wrote holds nothing the phase tree lacks",
              M.tree_holds_only_integrated(ctx, tree, (), ["map.md"]) is True)
        # The other direction: a guard that skipped every path would pass fr1.
        check("fr2 (DENY: the same difference at a path that is not a follower "
              "still keeps the tree)",
              M.tree_holds_only_integrated(ctx, tree, (), ["src.txt"]) is False
              and M.tree_holds_only_integrated(ctx, tree, ()) is False)

        # The retirement reads the follower paths the integration mark holds.
        seen = []
        M.tree_holds_only_integrated = (
            lambda c, t, records=(), followers=(): seen.append(list(followers)))
        task = {"id": "P1.2", "status": "done", "startedAt": "2026-10-15T00:00:00Z"}
        state = {"wave": {"trees": {"P1.2": tree}}}
        M._mark(state, "integrated", task, {"regate": True, "followers": ["map.md"]})
        rctx = {"gitRoot": phase_tree, "stateDir": os.path.join(base, "state"),
                "phase": PHASE, "did": []}
        M.retire_member(rctx, state, task)
        check("fr3 retiring a member hands the check the follower paths its "
              "integration wrote: %r" % (seen,), seen == [["map.md"]])
    finally:
        _harness.remove_tree(base)


# --- an undeclared path only a browser recipe writes -----------------------------
_SHOT_RECIPE = "git show HEAD:map.fresh > docs/shot.png"


def _shot_owner_wave(M, prefix):
    """A two-member wave whose second member's tree holds `docs/shot.png`
    undeclared, as its executor wrote it, and a follower owner that claims that
    path with a browser recipe copying `map.fresh` over it. The two byte strings
    differ, so whether the recipe ran is visible in the tree. `(root, mpath,
    tree)`, the tree None when the wave made none."""
    root, mpath = _wave_repo(prefix, 2)
    recipe = _SHOT_RECIPE
    _write_lf(os.path.join(root, "map.fresh"), "captured\n")
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    owner = [o for o in _evio.FOLLOWER_OWNERS if o.startswith("tools/")
             and o.endswith(".py")][0]
    os.makedirs(os.path.join(root, *owner.split("/")[:-1]), exist_ok=True)
    _write_lf(os.path.join(root, *owner.split("/")), (
        "import json, sys\n"
        "for rel in sys.argv[2:]:\n"
        "    if rel == 'docs/shot.png':\n"
        "        print('FOLLOWER-OWED ' + json.dumps({'path': rel, 'recipe': %r,\n"
        "              'owner': 'shots', 'needsBrowser': True}))\n" % (recipe,)))
    for argv in (["add", "-A"], ["commit", "-qm", "a browser owner"]):
        _harness.git(root, *argv)
    _code, first = _next_wave(M, root, mpath)
    tree = _tree_of(root, "P1.2")
    if tree:
        _write_lf(os.path.join(tree, "docs", "shot.png"), "by the executor\n")
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    return root, mpath, tree


def _drive_shot_wave(M, root, mpath, tree, run_recipe):
    """Up to six drives of that wave. On the first follow print the recipe is
    run in the member's tree when `run_recipe`, and left unrun otherwise; the
    loop ends on a decision or when every task is done. `(prints, followed,
    ran)`."""
    prints, followed, ran = [], False, False
    for _ in range(6):
        said = []
        with _Env(root):
            M.main(["next", PHASE, mpath, "--project-dir", root], out=said.append)
        prints.append("\n".join(said))
        if "follow P1.2: run `%s`" % (_SHOT_RECIPE,) in prints[-1] and not followed:
            followed = True
            if run_recipe and tree:
                subprocess.run(_SHOT_RECIPE, shell=True, cwd=tree, check=True,
                               timeout=60)
                ran = True
        elif instruction(prints[-1])[0] == "decide":
            break
        elif all(t.get("status") == "done" for t in tasks_of(mpath).values()):
            break
    return prints, followed, ran


def _follower_shot_cases(check):
    """An owner whose recipe needs a browser, standing at the path the protocol
    asks: its bytes cannot be reproduced, so the orchestrator is told to run it,
    and only what that run moved is widened."""
    M, why = _load("drive_phase_follower_shot")
    if M is None:
        check("fs0 the driver loads", False, why)
        return
    root, mpath, tree = _shot_owner_wave(M, "followshotwave")
    prints, _followed, ran = _drive_shot_wave(M, root, mpath, tree, True)
    task = tasks_of(mpath)["P1.2"]
    notes = " ".join(str(n) for n in task.get("notes") or [])
    check("fm2 an undeclared path whose owner's recipe needs a browser is never run "
          "by the drive: it prints the orchestrator the follow, and the next drive "
          "widens what that run wrote and closes, with no undeclared-change "
          "decision: %r" % ((task.get("status"), task.get("files"), notes, prints),),
          ran and task.get("status") == "done"
          and "docs/shot.png" in (task.get("files") or [])
          and "on the drive's follow" in notes
          and "undeclared-change" not in "\n".join(prints)
          and _read(os.path.join(root, "docs", "shot.png")) == b"captured\n")

    # The same follow, and the orchestrator calls the drive again without
    # running the recipe: the executor's bytes never moved, so nothing vouches
    # for them and the path is put to the human like any other undeclared one.
    root, mpath, tree = _shot_owner_wave(M, "followshotunrun")
    prints, followed, _ran = _drive_shot_wave(M, root, mpath, tree, False)
    task = tasks_of(mpath)["P1.2"]
    last = prints[-1] if prints else ""
    check("fm3 a browser path whose bytes did not move under the recipe stays the "
          "undeclared-change decision (the follow printed, the drive called again "
          "with the recipe unrun: the decision names the path, the scope is not "
          "widened and the task is not closed): %r"
          % ((task.get("status"), task.get("files"), prints),),
          followed and instruction(last) == ("decide", "undeclared-change", None)
          and "docs/shot.png" in last
          and "docs/shot.png" not in (task.get("files") or [])
          and task.get("status") != "done"
          and tree is not None
          and _read(os.path.join(tree, "docs", "shot.png")) == b"by the executor\n")

    # The browser owner the protocol actually names, asked the way integration
    # asks it. A sibling directory sharing the capture directory's name as a
    # prefix is in the set, so a match on the bare prefix would claim it too.
    node = shutil.which("node")
    if node is None:
        print("SKIP fm4 (node is not on PATH; the capture owner is a node script)")
        return
    asked = ["docs/screenshots/x.png", "docs/screenshots-old/x.png", "docs/x.png",
             "README.md"]
    done = subprocess.run([node, os.path.join(_output.REPO_ROOT, "tools",
                                              "capture-screenshots.mjs"),
                           "--follower-for"] + asked,
                          cwd=_output.REPO_ROOT, capture_output=True, timeout=120)
    records, unread = _evio.followers_in(done.stdout.decode("utf-8", "replace"))
    check("fm4 capture-screenshots.mjs --follower-for claims docs/screenshots/x.png "
          "and nothing outside (one browser record for the capture path; the "
          "prefix sibling, a docs path and README.md unclaimed): %r"
          % ((done.returncode, records, unread, done.stderr[-300:]),),
          done.returncode == 0 and unread == 0
          and records == [{"path": "docs/screenshots/x.png",
                           "recipe": "node tools/capture-screenshots.mjs",
                           "owner": "capture-screenshots", "needsBrowser": True}])


# --- a wave member's tree outlives a crash, a failed setup and a block ----------
# The setup every case below declares: it appends the directory it ran in to a
# log outside the fixture, so the log is the evidence a tree was provisioned -
# and, while a flag file exists, it removes the flag and fails instead, once.
_SETUP = ("import os, sys\n"
          "flag, log = sys.argv[1], sys.argv[2]\n"
          "if os.path.exists(flag):\n"
          "    os.remove(flag)\n"
          "    sys.exit(3)\n"
          "with open(log, 'a') as fh:\n"
          "    fh.write(os.path.realpath(os.getcwd()) + '\\n')\n")


def _setup_fixture(prefix, fail_first=False):
    """`(command, log)` - an `executor.worktreeSetup` running `_SETUP`, which
    fails its first run when `fail_first`."""
    aux = os.path.realpath(_harness.fixture_root("drive-setup-%s-" % (prefix,)))
    script = os.path.join(aux, "setup.py")
    flag, log = os.path.join(aux, "fail-once"), os.path.join(aux, "provisioned.log")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_SETUP)
    if fail_first:
        with open(flag, "w", encoding="utf-8") as fh:
            fh.write("fail the first setup\n")
    return '"%s" "%s" "%s" "%s"' % (sys.executable, script, flag, log), log


def _provisioned(log):
    """The trees the setup completed in, in order."""
    try:
        with open(log, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        return []


def _tree_expected(root, task_id):
    """Where `tree_path` puts a task's tree in a `_wave_repo` fixture."""
    with open(os.path.join(root, ".claude", "audit.config.json"),
              encoding="utf-8") as fh:
        where = json.load(fh)["executor"]["worktreeRoot"]
    return os.path.join(where, "%s-%s" % (os.path.basename(root), task_id))


def _brief_of(root, text, task_id, role="executor"):
    """The text of the brief one dispatch line of `text` names for `task_id`."""
    for line in text.splitlines():
        hit = _DISPATCH.match(line)
        brief = _BRIEF.search(line)
        if hit and brief and hit.group(1).endswith(role) and hit.group(2) == task_id:
            with open(os.path.join(root, *brief.group(1).split("/")), encoding="utf-8") as fh:
                return fh.read()
    return ""


def _wave_resume_cases(check):
    """Tree setup resumes through the marker: a crash inside the setup and a
    setup that failed both leave a marked tree that the next drive finds and
    provisions again before any dispatch, spending no attempt."""
    M, why = _load("drive_phase_wave_resume")
    if M is None:
        check("wt1 the driver loads", False, why)
        return
    cmd, log = _setup_fixture("crash")
    root, mpath = _wave_repo("wavesetupcrash", 2, setup=cmd)
    tree = _tree_expected(root, "P1.1")
    MW = _loader.load_script("manage-worktrees.py", "mw_crash_in_setup", cache=False)

    def die_in_setup(command, cwd, timeout=None):
        raise RuntimeError("the session died inside the setup of %s" % (cwd,))
    MW.run_setup = die_in_setup
    real_run = M.run_verb
    crashes = []

    def crash_once(ctx, script, args, stdin=None):
        # The real verb, in this process, dying where the session would: after
        # the marker is written and before the setup returns.
        if script == "manage-worktrees.py" and args[:1] == ["task-add"] \
                and args[2] == "P1.1" and not crashes:
            crashes.append(args)
            MW.main(list(args), out=lambda *_a: None)
        return real_run(ctx, script, args, stdin=stdin)
    M.run_verb = crash_once
    crashed = None
    try:
        _next_wave(M, root, mpath)
    except RuntimeError as exc:
        crashed = str(exc)
    finally:
        M.run_verb = real_run
    marked = MW._wt.read_provenance(tree, expect_task="P1.1") \
        if os.path.isdir(tree) else {}
    check("wt1 the fixture crashed where it means to: the tree of P1.1 exists and "
          "is marked for it, its setup never completed, and the driver recorded "
          "no tree: %r %r %r" % (crashed, marked.get("ours"), _provisioned(log)),
          crashed and marked.get("ours") is True and not _provisioned(log)
          and not _tree_of(root, "P1.1")
          and _attempts(mpath, "P1.1") == 1)
    code, resumed = _next_wave(M, root, mpath)
    check("wt2 the next drive finds that tree through its marker, runs its setup "
          "again before dispatching, and spends no attempt: %r %r %r"
          % (resumed, _provisioned(log), _attempts(mpath, "P1.1")),
          code == 0 and _dispatched(resumed) == ["P1.1", "P1.2"]
          and os.path.realpath(_tree_of(root, "P1.1") or "-") == os.path.realpath(tree)
          and os.path.realpath(tree) in _provisioned(log)
          and _attempts(mpath, "P1.1") == 1)

    cmd, log = _setup_fixture("fail", fail_first=True)
    root, mpath = _wave_repo("wavesetupfail", 2, setup=cmd)
    tree = _tree_expected(root, "P1.1")
    code, first = _next_wave(M, root, mpath)
    check("wt3 a setup that fails stops the drive as could-not-run, dispatching "
          "nothing, with the tree kept: %r" % (first,),
          code != 0 and "setup" in first and not _dispatched(first)
          and os.path.isdir(tree) and not _provisioned(log))
    code, second = _next_wave(M, root, mpath)
    check("wt4 the next drive runs the failed setup again before it dispatches "
          "the task, in the same tree, and spends no attempt: %r %r"
          % (second, _provisioned(log)),
          code == 0 and "P1.1" in _dispatched(second)
          and os.path.realpath(tree) in _provisioned(log)
          and _attempts(mpath, "P1.1") == 1)


def _wave_adopt_cases(check):
    """A blocked member's tree is kept when its wave closes, and a later wave
    that runs the task again adopts it - at the base it was cut from."""
    M, why = _load("drive_phase_wave_adopt")
    if M is None:
        check("wt5 the driver loads", False, why)
        return
    root, mpath = _wave_repo("waveadopt", 2, red=("P1.1",), spare_file=True)

    def one_attempt(plan):
        plan["phases"][0]["tasks"][0]["maxAttempts"] = 1
    _commit_plan(root, mpath, one_attempt, "one attempt for P1.1")
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    _next_wave(M, root, mpath)
    tree = _tree_of(root, "P1.1")
    base = (_drive_state(root).get("wave") or {}).get("base")
    said = []
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root, "--answer", "block",
                "--reason", "the gate is red"], out=said.append)
    blocked = "\n".join(said)
    state = _drive_state(root)
    check("wt5 when the wave closes over a blocked member, its tree is kept on "
          "disk, recorded, and named: %r %r" % (blocked, state.get("keptTrees")),
          tree and not state.get("wave") and os.path.isdir(tree)
          and (state.get("keptTrees") or {}).get("P1.1") == tree
          and tree in blocked
          and tasks_of(mpath)["P1.1"].get("status") == "blocked")
    with _Env(root):
        unblocked = _verb(root, "audit-task.py", [
            "unblock", "P1.1", mpath, "--project-dir", root, "--reason",
            "the human: run it again"])
        added = _verb(root, "audit-task.py", [
            "add", "a third file", mpath, "--project-dir", root, "--phase", PHASE,
            "--files", "src/f3.txt", "--description", "change src/f3.txt",
            "--gate", '"%s" check_own.py src/f3.txt' % (sys.executable,), "--json"])
    code, again = _next_wave(M, root, mpath)
    wave = _drive_state(root).get("wave") or {}
    brief = _brief_of(root, again, "P1.1")
    check("wt6 a later wave that runs the task again adopts the kept tree, and "
          "its executor's brief names that tree and the base it was cut at, not "
          "the new wave's: %r %r %r" % (again, (unblocked[0], added[0]),
                                        wave.get("base")),
          code == 0 and "P1.1" in _dispatched(again)
          and len(_dispatched(again)) == 2
          and _tree_of(root, "P1.1") == tree and wave.get("base") != base
          and ("tree: %s" % (tree,)) in brief and ("base: %s" % (base,)) in brief
          and "P1.1" not in (_drive_state(root).get("keptTrees") or {}))


# A gate that passes wherever it runs and logs the directory it ran in, outside
# the fixture: green in the phase tree as in the task tree, which is the shape
# that let a close commit nothing of the task - the log is what says where.
_CWD_LOG = ("import os\n"
            "with open(os.environ['DRIVE_CWD_LOG'], 'a') as fh:\n"
            "    fh.write(os.path.realpath(os.getcwd()) + '\\n')\n")

KEPT_RESTART_CLAUSE = ("a restarted task whose kept worktree holds changes is "
                       "not dispatched or gated in the phase tree, and the "
                       "drive names the kept tree")


def _kept_restart_cases(check):
    """A wave member blocked with its work in its kept tree, then restarted by
    hand with `start`, is never run in the phase tree: the drive either runs it
    in the kept tree or stops naming it, and a close never commits it empty."""
    M, why = _load("drive_phase_kept_restart")
    if M is None:
        check("kr1 the driver loads", False, why)
        return
    for unmark in (False, True):
        _kept_restart_fixture(M, check, unmark)
    _kept_tree_stop_case(M, check)


def _kept_tree_stop_case(M, check):
    """`kept_tree_stop` asked directly: a standing kept tree stops a serial step
    naming the tree and the task, and nothing else does - a tree gone from disk,
    another task's tree, a state recording none."""
    tree = tempfile.mkdtemp(prefix="drive-kept-stop-")
    try:
        task = {"id": "P1.1"}
        state = {"keptTrees": {"P1.1": tree, "P1.2": tree + "-gone"}}
        ctx = {"phase": "P1"}
        stood = M.kept_tree_stop(ctx, state, task)
        other = M.kept_tree_stop({"phase": "P1"}, state, {"id": "P1.3"})
        gone = M.kept_tree_stop({"phase": "P1"}, state, {"id": "P1.2"})
        bare = M.kept_tree_stop({"phase": "P1"}, {}, task)
    finally:
        _harness.remove_tree(tree)
    check("kr3 kept_tree_stop stops a serial step on a task whose kept tree "
          "stands, naming the tree and the task, and answers None for a tree "
          "gone from disk, for another task and for a state recording none: %r"
          % ((stood, other, gone, bare),),
          isinstance(stood, tuple) and stood[0] == M.E_STOPPED
          and tree in stood[1] and "P1.1" in stood[1] and "stopped" in stood[1]
          and ctx.get("stop") == "stopped"
          and other is None and gone is None and bare is None)


def _kept_restart_fixture(M, check, unmark):
    """One repository for `_kept_restart_cases`: kr1 with the kept tree as a
    closed wave leaves it, kr2 with its marker removed first."""
    root, mpath = _wave_repo("keptrestart%d" % (int(unmark),), 2,
                             red=("P1.1",))
    # The logging gate is committed before the first wave, so the tree cut
    # for it holds the script; its log is named by the environment, since a
    # path outside the repository in the gate's text is not the same gate.
    _write_lf(os.path.join(root, "log_cwd.py"), _CWD_LOG)
    _harness.git(root, "add", "--", "log_cwd.py")
    _harness.git(root, "commit", "-qm", "the logging gate")
    aux = os.path.realpath(_harness.fixture_root("drive-cwdlog-"))
    log = os.path.join(aux, "cwd.log")
    held = os.environ.get("DRIVE_CWD_LOG")
    os.environ["DRIVE_CWD_LOG"] = log
    try:
        _kept_restart_run(M, check, root, mpath, log, unmark)
    finally:
        if held is None:
            os.environ.pop("DRIVE_CWD_LOG", None)
        else:
            os.environ["DRIVE_CWD_LOG"] = held
        _harness.remove_tree(aux)


def _worktree_paths(root):
    """The real paths of every worktree git lists for `root`, sorted."""
    return sorted(os.path.realpath(ln[len("worktree "):]) for ln in _harness.git(
        root, "worktree", "list", "--porcelain").splitlines()
        if ln.startswith("worktree "))


def _kept_restart_run(M, check, root, mpath, log, unmark=False):
    """The block, restart and drive of `_kept_restart_cases`, and its case."""
    def one_attempt(plan):
        plan["phases"][0]["tasks"][0]["maxAttempts"] = 1
    _commit_plan(root, mpath, one_attempt, "one attempt for P1.1")
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    _next_wave(M, root, mpath)
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root, "--answer", "block",
                "--reason", "the gate is red"], out=lambda *_a: None)
    kept = (_drive_state(root).get("keptTrees") or {}).get("P1.1")
    kept_stood = bool(kept) and os.path.isdir(kept)

    def green_anywhere(plan):
        task = plan["phases"][0]["tasks"][0]
        task["maxAttempts"] = 3
        task["tests"]["gate"] = ['"%s" log_cwd.py' % (sys.executable,)]
    _commit_plan(root, mpath, green_anywhere, "P1.1: a gate green anywhere")
    with _Env(root):
        started = _verb(root, "audit-task.py", ["start", "P1.1", mpath,
                                                "--project-dir", root])
    unmarked = False
    if unmark and kept_stood:
        admin = M._worktrees.admin_dir(kept)
        marker = os.path.join(admin, M._worktrees.PROVENANCE_FILE) if admin else ""
        if os.path.isfile(marker):
            os.remove(marker)
            unmarked = True
    trees_before = _worktree_paths(root)
    prints, briefs = [], []
    with _Env(root):
        for _ in range(8):
            said = []
            code = M.main(["next", PHASE, mpath, "--project-dir", root],
                          out=said.append)
            text = "\n".join(said)
            prints.append(text)
            kind = instruction(text)
            if code != 0 or kind[0] != "dispatch" or kind[2] != "P1.1":
                break
            briefs.append(_brief_of(root, text, "P1.1"))
            # The executor changes nothing: its work is already in the kept
            # tree, which is where a run of the task has to find it.
            _verb(root, DRIVER, ["submit", "P1.1", "--role", "executor", mpath,
                                 "--project-dir", root],
                  stdin=json.dumps(_executor_body("P1.1")))
    task = tasks_of(mpath).get("P1.1") or {}
    sha = task.get("commit")
    carried = (_harness.git(root, "show", "--name-only", "--pretty=format:", sha)
               .split() if sha else [])
    gated_in = _provisioned(log)
    said_all = "\n".join(prints + briefs)
    if unmark:
        check("kr2 a kept tree with no marker naming its task stops the drive, "
              "naming the tree, before any dispatch, gate or fresh tree: %r" % ((
                  kept, unmarked, started[0], [p[-500:] for p in prints],
                  len(briefs), gated_in, task.get("status"), sha,
                  trees_before, _worktree_paths(root)),),
              kept_stood and unmarked and started[0] == 0
              and len(prints) == 1 and kept in prints[0]
              and "stopped" in prints[0] and "marker" in prints[0]
              and briefs == [] and gated_in == []
              and task.get("status") == "in_progress" and sha is None
              and _worktree_paths(root) == trees_before
              and os.path.realpath(kept) in trees_before)
        return
    check("kr1 %s: %r" % (KEPT_RESTART_CLAUSE, (
              kept, started[0], [p[-400:] for p in prints], gated_in,
              task.get("status"), carried)),
          kept_stood and started[0] == 0
          and kept in said_all
          and all(("tree: %s" % (kept,)) in b for b in briefs)
          and root not in gated_in
          and sha is not None and "src/f1.txt" in carried)


def _discard_run(M, prefix):
    """A wave where P1.2 also writes an undeclared file, answered `discard`:
    `(tree, the answer's print, state after)`."""
    root, mpath = _wave_repo(prefix, 2)
    _code, first = _next_wave(M, root, mpath)
    tree = _tree_of(root, "P1.2")
    if tree:
        with open(os.path.join(tree, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("written by P1.2, declared by nobody\n")
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    _code, second = _next_wave(M, root, mpath)
    said = []
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root, "--answer",
                "discard"], out=said.append)
    return (root, mpath, tree, instruction(second), "\n".join(said),
            _drive_state(root))


def _wave_review_discard_cases(check):
    """A per-task reviewer in a wave reads its own task's diff, from its tree
    and base; a discarded undeclared change keeps its tree, named."""
    M, why = _load("drive_phase_wave_review")
    if M is None:
        check("wt7 the driver loads", False, why)
        return
    root, mpath = _wave_repo("wavereview", 2, per_task="always")
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    code, second = _next_wave(M, root, mpath)
    base = (_drive_state(root).get("wave") or {}).get("base")
    briefs = dict((t, _brief_of(root, second, t, role="reviewer"))
                  for t in ("P1.1", "P1.2"))
    trees = dict((t, _tree_of(root, t)) for t in ("P1.1", "P1.2"))
    check("wt7 under review.perTask always each wave member's reviewer is "
          "dispatched with a brief naming its task tree and base, whose diff "
          "holds that task's own change and not its sibling's: %r %r"
          % (second, dict((t, b[-600:]) for t, b in briefs.items())),
          code == 0 and _dispatched(second, "reviewer") == ["P1.1", "P1.2"]
          and all(trees.values()) and base
          and all(("tree: %s" % (trees[t],)) in briefs[t]
                  and ("base: %s" % (base,)) in briefs[t]
                  and ("+changed by %s" % (t,)) in briefs[t] for t in trees)
          and "+changed by P1.2" not in briefs["P1.1"])

    root, mpath, tree, asked, answered, state = _discard_run(M, "wavediscard")
    check("wt8 answering discard closes the task, keeps its tree with the "
          "undeclared bytes in it and out of the phase tree, and names the tree "
          "where it is kept: %r %r %r" % (asked, answered, state.get("keptTrees")),
          asked == ("decide", "undeclared-change", None)
          and tasks_of(mpath)["P1.2"].get("status") == "done"
          and tree and os.path.isfile(os.path.join(tree, "notes.txt"))
          and not os.path.exists(os.path.join(root, "notes.txt"))
          and tree in answered
          and (state.get("keptTrees") or {}).get("P1.2") == tree)
    # RED TWIN for `tree_holds_only_integrated`: a guard that never reports a
    # difference takes the tree down with the discarded bytes in it.
    mutant, _w = _load("drive_phase_wave_discard_mutant")
    mutant.tree_holds_only_integrated = \
        lambda ctx, tree, records=(), followers=(): True
    _r, mpath_m, tree_m, _a, answered_m, _s = _discard_run(mutant, "wavediscardm")
    check("wt8m RED TWIN: a driver whose guard never sees a difference removes "
          "the discarded change's tree, so wt8's predicate fails for it: %r"
          % (answered_m,),
          tree_m and not os.path.isdir(tree_m)
          and tasks_of(mpath_m)["P1.2"].get("status") == "done")


# The 3.2.0 drive of two tasks under `review.perTask: always`, read off its
# did-lines (commit SHAs written as <sha>) and the journal's action sequence.
# Taken from a drive by the v3.2.0 plugin itself; `w1` holds width 1 and an
# absent key to it, and `w1m` is the case that says the comparison can fail.
# One clause departs from that drive's text and is not about width: the sign-off
# line now says the lint-probe step was skipped for a plan naming no
# `meta.buildCommands.lintProbe`, a step the 3.2.0 drive did not have.
PINNED_320_DID = [
    "started P1.1",
    "gate P1.1 green; stamp current",
    "closed P1.1 at <sha>; started P1.2",
    "gate P1.2 green; stamp current",
    "closed P1.2 at <sha>",
    "phase gate green; invariants clean; lintProbe unset; signed off; "
    "committed <sha>; landed "
    "(audit/p1-one -> main (no-checkout); mergedAt = <ts>...); lock released",
]
# One tuple per journal file - each file is one writer's chain, in append order.
# The files are read apart because `read_all` orders rows by a one-second stamp
# and then by file NAME, and a name carries a worktree key that differs per
# fixture path: two runs of one drive interleave the writers differently.
#
# `task.return.filed` is the row `drive-phase.py submit` appends
# right after the executor's return is written, so it sits beside every
# `task.start` here - the row that lets a filing stay "once" even once its
# file is deleted, which the exclusive create alone could not do.
#
# The two `audit.state.committed` rows - the sign-off's state commit and the
# landing's - carry the session id like every other row the session's verbs
# write, so they land in the session's file; `phase.merged` alone is filed by
# the landing under the checkout's writer token.
PINNED_320_ACTIONS = sorted([
    ("phase.merged",),
    ("task.start", "task.return.filed", "test.evidence.recorded",
     "task.testEvidence", "meta.evidenceSince", "audit.task.committed",
     "task.done", "task.start", "task.return.filed", "test.evidence.recorded",
     "task.testEvidence", "audit.task.committed", "task.done",
     "test.evidence.recorded", "phase.testEvidence", "phase.verdict",
     "audit.state.committed", "audit.state.committed"),
])


def _actions_by_writer(root):
    """The journal's action sequences, one tuple per file, sorted."""
    import _journal_io
    seqs = []
    for path in _journal_io.journal_files(_journal_io.journal_dir(root)):
        rows, _torn = _journal_io.read_file(path)
        seqs.append(tuple(r.get("action") for r in rows if isinstance(r, dict)))
    return sorted(seqs)


def _normal_did(text):
    """The did-lines of one print, a SHA as <sha> and a filed path as <path>."""
    out = []
    for line in text.splitlines():
        if not line.startswith("[drive-phase] "):
            continue
        clause = line.partition(": ")[2]
        clause = re.sub(r"\bat \S+\.json\b", "at <path>", clause)
        clause = re.sub(r"mergedAt = \d{4}-\d\d-\d\d\S*?\.\.\.",
                        "mergedAt = <ts>...", clause)
        out.append(re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", clause))
    return out


def _width_one_run(M, prefix, width, trees=None):
    """A drive of two tasks at `width`. `trees` roots any task tree in a fixture
    directory: a driver that waves where it should not would otherwise cut its
    trees beside the fixture, in the temp directory itself, and leave them."""
    root, mpath = _repo(prefix, task_ids=TASKS[:2])
    if width is not None:
        cfg_path = os.path.join(root, ".claude", "audit.config.json")
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        cfg["executor"] = {"waveWidth": width}
        if trees:
            cfg["executor"]["worktreeRoot"] = trees
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        for argv in (["add", "-A"], ["commit", "-qm", "width"]):
            _harness.git(root, *argv)
    run = drive(M, root, mpath)
    did = []
    for _code, text in run["prints"]:
        did.extend(_normal_did(text))
    return did, _actions_by_writer(root), run["steps"]


def _width_one_cases(check):
    M, why = _load("drive_phase_width_one")
    if M is None:
        check("w1 the driver loads", False, why)
        return
    absent = _width_one_run(M, "wabsent", None)
    one = _width_one_run(M, "wone", 1)
    check("w1 an absent executor.waveWidth and a width of 1 give the same "
          "did-lines and the same journal action sequence, and both are the "
          "3.2.0 drive's: %r %r" % (absent[0], absent[1]),
          absent[:2] == one[:2] and absent[0] == PINNED_320_DID
          and absent[1] == PINNED_320_ACTIONS
          and absent[2] == expected_sequence(TASKS[:2]))
    mutant, _w = _load("drive_phase_width_forced")
    mutant.wave_width = lambda config: (2, "forced by the mutant", None)
    forced = _width_one_run(mutant, "wforced", 1, trees=os.path.realpath(
        _harness.fixture_root("drive-trees-wforced-")))
    check("w1m RED TWIN: a driver that waves at width 1 departs from the pinned "
          "did-lines and actions, and w1 catches it: %r" % (forced[1],),
          forced[0] != PINNED_320_DID or forced[1] != absent[1])


def _answer_wave(M, root, mpath, *flags):
    """One `next` over a wave fixture carrying `flags`: `(code, print)`."""
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root] + list(flags),
                      out=said.append)
    return code, "\n".join(said)


def _wave_redo_cases(check):
    """A wave member whose integration the phase tree refuses is offered `redo`
    - its tree recut at the phase HEAD with the work carried over, no attempt
    spent - and never a `retry`, which would spend one for work that was fine."""
    M, why = _load("drive_phase_wave_redo")
    if M is None:
        check("wd1 the driver loads", False, why)
        return
    root, mpath = _wave_repo("waveredo", 2)
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t)
    stray = os.path.join(root, "stray.txt")
    with open(stray, "w", encoding="utf-8") as fh:
        fh.write("a change the phase tree holds that no task made\n")
    _code, refused = _next_wave(M, root, mpath)
    check("wd1 a dirty phase tree refuses the integration, and the decision "
          "offers redo and block - not retry: %r" % (refused,),
          instruction(refused) == ("decide", "integration-refused", None)
          and "answer: next %s --answer redo|block" % (PHASE,) in refused
          and "retry" not in refused)
    code, wrong = _answer_wave(M, root, mpath, "--answer", "retry")
    check("wd2 `retry` is not an answer to it any more: %r" % (wrong,),
          code == 2 and "redo|block" in wrong)
    os.remove(stray)
    with open(os.path.join(root, "moved.txt"), "w", encoding="utf-8") as fh:
        fh.write("the phase tree moved on\n")
    for argv in (["add", "moved.txt"], ["commit", "-qm", "the phase tree moved"]):
        _harness.git(root, *argv)
    head = _git_out(root, "rev-parse", "HEAD").strip()
    made = len([a for a in _actions(root) if a == "task.worktree"])
    code, after = _answer_wave(M, root, mpath, "--answer", "redo")
    state = _drive_state(root)
    check("wd3 redo recuts the member's tree at the phase HEAD - a new tree row, "
          "a new base - dispatches no executor, spends no attempt, and carries "
          "the work over so the task closes: %r %r"
          % (after, (state.get("wave") or {}).get("bases")),
          code == 0 and not _dispatched(after)
          and (state.get("wave") or {}).get("bases", {}).get("P1.1") == head
          and len([a for a in _actions(root) if a == "task.worktree"]) == made + 1
          and _attempts(mpath, "P1.1") == 1
          and tasks_of(mpath)["P1.1"].get("status") == "done"
          and tasks_of(mpath)["P1.1"].get("commit"))
    check("wd3a the carried work is the member's own bytes: %r"
          % (_read(os.path.join(root, "src", "f1.txt")),),
          _read(os.path.join(root, "src", "f1.txt")) == b"changed by P1.1\n")
    probe = os.path.join(root, "lf-probe.txt")
    _write_lf(probe, "a\nb\n")
    check("wd3c the fixture writes a member's change as the bytes it names, LF "
          "on every OS (text mode gives CRLF on Windows): %r" % (_read(probe),),
          _read(probe) == b"a\nb\n")
    os.remove(probe)
    check("wd3b the redo leaves no patch file behind once it applied: %r"
          % (os.listdir(os.path.join(root, ".claude", "state", "drive")),),
          not [n for n in os.listdir(os.path.join(root, ".claude", "state", "drive"))
               if n.endswith(".patch")])
    code, last = _answer_wave(M, root, mpath, "--answer", "redo")
    check("wd4 the sibling the same stray refused is redone the same way and the "
          "wave ends with both closed and no attempt past the first: %r" % (last,),
          code == 0 and all(tasks_of(mpath)[t].get("status") == "done"
                            for t in ("P1.1", "P1.2"))
          and _attempts(mpath, "P1.2") == 1)


def _wave_regate_cases(check):
    """An integration that cannot say whether it overlapped a sibling
    (`regate: null`) is re-gated on the phase tree, like an overlap; one that
    says it did not (`regate: false`) is not."""
    M, why = _load("drive_phase_wave_regate")
    if M is None:
        check("wg1 the driver loads", False, why)
        return
    seen = {}
    for label, forced in (("null", None), ("false", False)):
        root, mpath = _wave_repo("waveregate-" + label, 2)
        _code, first = _next_wave(M, root, mpath)
        for t in _dispatched(first):
            _file_wave_executor(root, mpath, t)
        real_run = M.run_verb
        gates = []

        def saying(ctx, script, args, stdin=None):
            code, out, err = real_run(ctx, script, args, stdin=stdin)
            if script == "run-test-gate.py":
                gates.append((args[args.index("--task") + 1],
                              "--tree" in args))
            if script == "integrate-task.py":
                body = json.loads(out)
                body["regate"] = forced
                out = json.dumps(body)
            return code, out, err
        M.run_verb = saying
        try:
            _code, text = _next_wave(M, root, mpath)
        finally:
            M.run_verb = real_run
        seen[label] = (gates, text)
    null_gates, null_text = seen["null"]
    false_gates, false_text = seen["false"]
    check("wg1 regate null re-gates each member on the phase tree after its own "
          "tree's gate, and says so: %r %r" % (null_gates, null_text),
          sorted(g for g in null_gates if not g[1]) == [("P1.1", False),
                                                        ("P1.2", False)]
          and "re-gate P1.1 green" in null_text
          and "re-gate P1.2 green" in null_text)
    check("wg2 ALLOW: regate false measures the gate once, in the member's tree: "
          "%r %r" % (false_gates, false_text),
          not [g for g in false_gates if not g[1]]
          and "re-gate" not in false_text)


# A gate the base fails and the phase fixes later: it passes only where the
# measured tree holds `fixed.txt`, a file no task writes and the phase tree
# commits after the wave's trees were cut.
_AB_FIXED = '"%s" -c "import os, sys; sys.exit(0 if os.path.exists(\'fixed.txt\') ' \
    'else 1)"' % (sys.executable,)


def _ab_red_at_base(M, prefix, phase_edit=None, base=None, work=None, then=None,
                    prepare=None):
    """A two-member wave whose first member is red only on a check the base
    fails, with the phase tree then committing the fix - and `phase_edit`
    `(rel, text)` beside it when given. `base` is what `src/f1.txt` holds when
    the trees are cut, `work` what the first member writes there, and `then` what
    else it does in its tree before filing, each the fixture's default when
    None; `prepare(root)` commits what else the base holds before the trees are
    cut. `(root, mpath, head, tree)` once the first member's gate-red decision
    stands."""
    root, mpath = _wave_repo(prefix, 2)
    if prepare is not None:
        prepare(root)
    if base is not None:
        _write_lf(os.path.join(root, "src", "f1.txt"), base)

    def edit(plan):
        plan["phases"][0]["tasks"][0]["tests"]["gate"] = [_AB_FIXED]
    _commit_plan(root, mpath, edit, "the first member's gate needs the fix")
    _code, first = _next_wave(M, root, mpath)
    for t in _dispatched(first):
        _file_wave_executor(root, mpath, t, work if t == "P1.1" else None,
                            then if t == "P1.1" else None)
    _code, _second = _next_wave(M, root, mpath)
    tree = _tree_of(root, "P1.1")
    for rel, text in [("fixed.txt", "the phase fixed what the base broke\n")] + (
            [phase_edit] if phase_edit else []):
        _write_lf(os.path.join(root, *rel.split("/")), text)
        _harness.git(root, "add", rel)
    _harness.git(root, "commit", "-qm", "the phase fixes the base's red")
    return root, mpath, _git_out(root, "rev-parse", "HEAD").strip(), tree


def _ab_last_row(root, mpath, task_id):
    rows = _evio.oldest_first(_rows_of(root, mpath, task_id))
    return rows[-1] if rows else {}


def _wave_advance_cases(check):
    """A member red only on what the base carried, answered `rerun` after the
    phase landed the fix, is measured in its tree brought to the phase head -
    not in the tree at the old base, where the same red would come back."""
    M, why = _load("drive_phase_wave_advance")
    if M is None:
        check("ab1 the driver loads", False, why)
        return
    root, mpath, head, tree = _ab_red_at_base(M, "waveadvance")
    base = _git_out(tree, "rev-parse", "HEAD").strip() if tree else None
    code, text = _next(M, root, mpath, "--answer", "rerun")
    row = _ab_last_row(root, mpath, "P1.1")
    check("ab1 a rerun after the phase head moved runs in the tree brought to "
          "the head: the gate's row records the head, and it is green: %r"
          % ((code, (row.get("testedState") or {}).get("head"), row.get("status"),
              text[-400:]),),
          base and base != head
          and _evio.same_head((row.get("testedState") or {}).get("head"), head)
          and row.get("status") == "passed")
    import _journal_io
    moves = [r for r in _journal_io.read_all(root)
             if isinstance(r, dict) and r.get("action") == "task.tree.advanced"]
    said = (moves[-1].get("details") or {}) if moves else {}
    check("ab2 the base change is recorded: one journal row naming the old base, "
          "the new base and the files that moved: %r" % (said,),
          len(moves) == 1 and said.get("taskId") == "P1.1"
          and said.get("parent") == base and said.get("commit") == head
          and "fixed.txt" in [c.get("id") for c in said.get("changes") or []])
    check("ab3 ...and the member closes on that green with its own bytes "
          "integrated: %r" % (tasks_of(mpath)["P1.1"].get("status"),),
          tasks_of(mpath)["P1.1"].get("status") == "done"
          and _read(os.path.join(root, "src", "f1.txt")) == b"changed by P1.1\n")

    # RED TWIN: a driver that never moves the tree measures the rerun at the old
    # base, where the base's red is still there - ab1's predicate fails for it.
    mutant, _w = _load("drive_phase_wave_advance_mutant")
    mutant.advance_member = lambda ctx, state, task, tree: None
    root_m, mpath_m, head_m, _tree_m = _ab_red_at_base(mutant, "waveadvancem")
    _next(mutant, root_m, mpath_m, "--answer", "rerun")
    row_m = _ab_last_row(root_m, mpath_m, "P1.1")
    check("ab1m RED TWIN: a driver that reruns in the tree at the old base "
          "records a red at that base: %r"
          % (((row_m.get("testedState") or {}).get("head"), row_m.get("status")),),
          not _evio.same_head((row_m.get("testedState") or {}).get("head"), head_m)
          and row_m.get("status") != "passed")

    # A wave that has not cached its record paths yet - a later wave adopting a
    # kept tree, or a first gate - still knows which dirty paths are records:
    # the drive's refreshed plan and journal are not the task's work.
    root_r, mpath_r, head_r, tree_r = _ab_red_at_base(M, "waveadvancer")
    state_file = os.path.join(root_r, ".claude", "state", "drive", "%s.json" % (PHASE,))
    with open(state_file, encoding="utf-8") as fh:
        state = json.load(fh)
    cached = (state.get("wave") or {}).pop("records", None)
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    # The tree holds records refreshed from the moved head - the state a kept
    # tree is adopted in - so they are dirty AND among the paths that moved.
    with _Env(root_r):
        refreshed = _verb(root_r, "integrate-task.py", [
            mpath_r, "P1.1", "--project", root_r, "--refresh-records", "--json"])
    dirty = [p for p in _git_out(tree_r, "status", "--porcelain").splitlines()
             if "docs/audit" in p] if tree_r else []
    _code, text_r = _next(M, root_r, mpath_r, "--answer", "rerun")
    row_r = _ab_last_row(root_r, mpath_r, "P1.1")
    check("ab5 with no record paths cached on the wave, the member's refreshed "
          "records are still not read as its work: the tree moves and the rerun "
          "is green at the head: %r" % ((cached, refreshed[0], dirty,
                                          row_r.get("status"), text_r[-300:]),),
          cached and tree_r and refreshed[0] == 0 and dirty
          and _evio.same_head((row_r.get("testedState") or {}).get("head"), head_r)
          and row_r.get("status") == "passed")

    # A copy beside the member's tree that the mover cannot read is a move whose
    # outcome nobody can tell: the drive stops there rather than gate the tree.
    root_k, mpath_k, _head_k, tree_k = _ab_red_at_base(M, "waveadvancek")
    copy_k = os.path.join(_git_out(tree_k, "rev-parse", "--absolute-git-dir").strip(),
                          "audit-advance") if tree_k else ""
    if copy_k:
        os.makedirs(copy_k)
        with open(os.path.join(copy_k, "index.json"), "w", encoding="utf-8") as fh:
            fh.write("not a copy this plugin wrote")
    rows_before = len(_rows_of(root_k, mpath_k, "P1.1"))
    code_k, text_k = _next(M, root_k, mpath_k, "--answer", "rerun")
    check("ab6 a copy the mover cannot read stops the drive, naming it, and the "
          "member's gate is not run in a tree whose state nobody can tell: %r"
          % ((code_k, text_k[-300:]),),
          copy_k and code_k != 0 and "stopped" in text_k and "audit-advance" in text_k
          and len(_rows_of(root_k, mpath_k, "P1.1")) == rows_before)

    # A copy that will not come down - a handle another process holds open in
    # it, as Windows does - is a tree not settled however the move itself went:
    # the drive stops on what is on disk, after a move that counted (ab7) and
    # after one that was undone (ab8).
    wt = M._worktrees
    for cid, prefix, undone in (("ab7", "waveadvanced", False),
                                ("ab8", "waveadvanceu", True)):
        root_d, mpath_d, head_d, tree_d = _ab_red_at_base(M, prefix)
        rows_d = len(_rows_of(root_d, mpath_d, "P1.1"))
        # Read before the run: a drive that goes on removes the tree.
        copy_d = os.path.join(_git_out(tree_d, "rev-parse", "--absolute-git-dir")
                              .strip(), "audit-advance") if tree_d else ""
        f1_d = os.path.join(tree_d, "src", "f1.txt") if tree_d else ""
        real_rename, real_runner = wt.os.rename, wt._runner

        def flaky(src, dst, *rest, **kw):
            if str(src).endswith("audit-advance"):
                raise PermissionError(13, "fixture: a handle is open in the copy")
            return real_rename(src, dst, *rest, **kw)

        def refusing(run, _head=head_d, _undone=undone):
            fn = real_runner(run)

            def answer(cwd, args, timeout=60):
                if _undone and args[:3] == ["checkout", "-q", "--detach"] \
                        and _head in args:
                    return 1, "", "error: fixture: the checkout died"
                return fn(cwd, args, timeout)
            return answer
        wt.os.rename, wt._runner = flaky, refusing
        try:
            code_d, text_d = _next(M, root_d, mpath_d, "--answer", "rerun")
        finally:
            wt.os.rename, wt._runner = real_rename, real_runner
        check("%s a copy that will not come down after a move that %s stops the "
              "drive, naming it, with no gate run in that tree: %r"
              % (cid, "was undone" if undone else "counted", (code_d, text_d[-300:]),),
              tree_d and code_d != 0 and "stopped" in text_d
              and "audit-advance" in text_d and os.path.isdir(copy_d)
              and len(_rows_of(root_d, mpath_d, "P1.1")) == rows_d
              and os.path.isfile(f1_d) and _read(f1_d) == b"changed by P1.1\n")

    # The deny direction: the phase moved the member's own file too, so the
    # tree is not moved, the drive names the file, and the work stays put.
    root_o, mpath_o, head_o, tree_o = _ab_red_at_base(
        M, "waveadvanceo", ("src/f1.txt", "the phase's own edit of f1\n"))
    base_o = _git_out(tree_o, "rev-parse", "HEAD").strip() if tree_o else None
    _code, text_o = _next(M, root_o, mpath_o, "--answer", "rerun")
    check("ab4 a member whose work overlaps a file the phase moved is NOT "
          "brought to the head: the drive names the file, the tree stays at its "
          "base and its work is untouched: %r" % (text_o[-500:],),
          tree_o and _git_out(tree_o, "rev-parse", "HEAD").strip() == base_o
          and base_o != head_o and "src/f1.txt" in text_o
          and _read(os.path.join(tree_o, "src", "f1.txt")) == b"changed by P1.1\n"
          and not [r for r in _journal_io.read_all(root_o)
                   if isinstance(r, dict)
                   and r.get("action") == "task.tree.advanced"])


# A file a member and the phase both edit, on lines a three-way apply tells
# apart: the member's first line, the phase's third. The phase's line sits in
# the context of the member's hunk, so a plain apply at the head refuses what
# the three-way merge takes - the fixture tells the two apart. A mover refuses
# it by path all the same, which is what puts the member at the recut decision.
_AR_BASE = "one\ntwo\nthree\nfour\nfive\nsix\n"
_AR_WORK = "one by P1.1\ntwo\nthree\nfour\nfive\nsix\n"
_AR_PHASE = ("src/f1.txt", "one\ntwo\nthree by the phase\nfour\nfive\nsix\n")
_AR_MERGED = b"one by P1.1\ntwo\nthree by the phase\nfour\nfive\nsix\n"
_AR_OFFERS = re.compile(r"--answer [a-z|-]*\bredo\b")


def _carry_at(root, task_id):
    """The commit `refs/audit/carry/<task_id>` names in `root`, or ''."""
    return _git_out(root, "rev-parse", "-q", "--verify",
                    "refs/audit/carry/%s" % (task_id,)).strip()


def _ar_at_decision(M, prefix, phase_edit=_AR_PHASE, work=_AR_WORK, then=None,
                    prepare=None):
    """The member's gate-red decision answered `rerun` after the phase moved a
    file its work also edits; `then` and `prepare` are `_ab_red_at_base`'s.
    -> (root, mpath, head, tree, base, rows, code, text): `rows` is the
    member's gate row count before the answer."""
    root, mpath, head, tree = _ab_red_at_base(
        M, prefix, phase_edit, base=_AR_BASE if work == _AR_WORK else None,
        work=work, then=then, prepare=prepare)
    base = _git_out(tree, "rev-parse", "HEAD").strip() if tree else ""
    rows = len(_rows_of(root, mpath, "P1.1"))
    code, text = _next(M, root, mpath, "--answer", "rerun")
    return root, mpath, head, tree, base, rows, code, text


def _recut_refused_move_cases(check):
    """A member whose work overlaps a file the phase head moved is not gated at
    the base the phase has left: the drive stops at a decision that offers
    `redo`, and `redo` recuts the tree at the head carrying the work - or, when
    the work does not apply there, refuses by name and leaves it all as it was."""
    M, why = _load("drive_phase_recut_refused")
    if M is None:
        check("ar1 the driver loads", False, why)
        return
    root, mpath, head, tree, base, rows, code, text = _ar_at_decision(M, "arecut")
    check("ar1 a move the mover refuses for overlap records no gate run on the "
          "old base: the drive stops at a decision offering redo, naming the "
          "file, with the tree and its work where they were: %r"
          % ((code, rows, len(_rows_of(root, mpath, "P1.1")), text[-600:]),),
          tree and base and base != head
          and instruction(text)[0] == "decide" and _AR_OFFERS.search(text)
          and "src/f1.txt" in text
          and len(_rows_of(root, mpath, "P1.1")) == rows
          and _git_out(tree, "rev-parse", "HEAD").strip() == base
          and _read(os.path.join(tree, "src", "f1.txt")) == _AR_WORK.encode())
    made = len([a for a in _actions(root) if a == "task.worktree"])
    code, after = _next(M, root, mpath, "--answer", "redo")
    state = _drive_state(root)
    row = _ab_last_row(root, mpath, "P1.1")
    check("ar2 redo recuts the member's tree at the phase head with its work "
          "merged three-way, gates it there green, spends no attempt, and the "
          "member closes on both edits: %r"
          % ((code, (state.get("wave") or {}).get("bases"), row.get("status"),
              _attempts(mpath, "P1.1"), after[-600:]),),
          code == 0
          and len([a for a in _actions(root) if a == "task.worktree"]) == made + 1
          and _evio.same_head((row.get("testedState") or {}).get("head"), head)
          and row.get("status") == "passed"
          and _attempts(mpath, "P1.1") == 1
          and tasks_of(mpath)["P1.1"].get("status") == "done"
          and _read(os.path.join(root, "src", "f1.txt")) == _AR_MERGED)
    check("ar2b ...and its did-line says what each carried path got: the moved "
          "one merged three-way, and no byte-for-byte claim with nothing compared "
          "that way; the pinned work ref is gone once it succeeded: %r"
          % ((after[-500:], _git_out(root, "for-each-ref", "refs/audit/redo/")),),
          "merged three-way (src/f1.txt)" in after
          and "verified byte for byte" not in after
          and not _git_out(root, "for-each-ref", "refs/audit/redo/").strip())

    # The work and the phase's edit touch the same line: the patch does not
    # apply, so the redo refuses by name and moves nothing.
    root_c, mpath_c, head_c, tree_c, base_c, rows_c, _code, text_c = \
        _ar_at_decision(M, "arecutc", ("src/f1.txt", "the phase's own edit\n"),
                        work=None)
    carry_c = _carry_at(root_c, "P1.1")
    bases_c = dict((_drive_state(root_c).get("wave") or {}).get("bases") or {})
    code_c, refused = _next(M, root_c, mpath_c, "--answer", "redo")
    check("ar3 a redo whose patch conflicts is refused by name, listing the "
          "path, and the old tree, its work, its base and the carry ref are "
          "unchanged, with no gate run: %r"
          % ((code_c, carry_c, refused[-600:]),),
          _AR_OFFERS.search(text_c) and carry_c
          and code_c != 0 and "src/f1.txt" in refused and "redo" in refused
          and os.path.isdir(tree_c) and _tree_of(root_c, "P1.1") == tree_c
          and _git_out(tree_c, "rev-parse", "HEAD").strip() == base_c
          and _read(os.path.join(tree_c, "src", "f1.txt")) == b"changed by P1.1\n"
          and _carry_at(root_c, "P1.1") == carry_c
          and dict((_drive_state(root_c).get("wave") or {}).get("bases") or {})
          == bases_c
          and len(_rows_of(root_c, mpath_c, "P1.1")) == rows_c
          and tasks_of(mpath_c)["P1.1"].get("status") == "in_progress")
    code_c2, again = _next(M, root_c, mpath_c)
    check("ar3b ...and the decision still stands, to be answered again: %r"
          % ((code_c2, again[-300:]),),
          instruction(again)[0] == "decide" and _AR_OFFERS.search(again))

    # The tree holds the plan's records refreshed from the head - dirty, and
    # among the paths that moved. They are the drive's, not the member's work,
    # so the recut carries none of them and the work alone applies.
    root_r, mpath_r, head_r, tree_r = _ab_red_at_base(
        M, "arecutr", _AR_PHASE, base=_AR_BASE, work=_AR_WORK)
    with _Env(root_r):
        refreshed = _verb(root_r, "integrate-task.py", [
            mpath_r, "P1.1", "--project", root_r, "--refresh-records", "--json"])
    dirty = [p for p in _git_out(tree_r, "status", "--porcelain").splitlines()
             if "docs/audit" in p] if tree_r else []
    _next(M, root_r, mpath_r, "--answer", "rerun")
    code_r, after_r = _next(M, root_r, mpath_r, "--answer", "redo")
    recut = _tree_of(root_r, "P1.1")
    check("ar4 the plan's record files are never carried: with them dirty in "
          "the old tree the redo still applies the work alone and the member "
          "closes on both edits: %r"
          % ((refreshed[0], dirty, code_r, recut, after_r[-600:]),),
          refreshed[0] == 0 and dirty and code_r == 0
          and "merged three-way (src/f1.txt)" in after_r
          and "docs/audit" not in after_r.split("merged three-way", 1)[-1]
          .split(")", 1)[0]
          and tasks_of(mpath_r)["P1.1"].get("status") == "done"
          and _read(os.path.join(root_r, "src", "f1.txt")) == _AR_MERGED)

    # The filed carry holds a path the tree's work no longer does: a recut from
    # the tree would drop it, so the redo is refused before anything moves.
    root_l, mpath_l, _head_l, tree_l, base_l, rows_l, _c, _t = _ar_at_decision(
        M, "arecutl")
    carry_l = _carry_with(root_l, "P1.1", "src/lost.txt", "filed, then lost\n")
    code_l, said_l = _next(M, root_l, mpath_l, "--answer", "redo")
    check("ar8 a carry ref holding a path the tree's work lacks refuses the redo "
          "by name, and the tree, its work and the carry ref are as they were: %r"
          % ((code_l, carry_l, said_l[-400:]),),
          carry_l and code_l != 0 and "redo refused" in said_l
          and "src/lost.txt" in said_l
          and _carry_at(root_l, "P1.1") == carry_l
          and _tree_of(root_l, "P1.1") == tree_l
          and _git_out(tree_l, "rev-parse", "HEAD").strip() == base_l
          and _read(os.path.join(tree_l, "src", "f1.txt")) == _AR_WORK.encode()
          and len(_rows_of(root_l, mpath_l, "P1.1")) == rows_l
          and not [n for n in os.listdir(os.path.join(root_l, ".claude", "state",
                                                      "drive"))
                   if n.endswith(".patch")])

    _recut_crash_cases(check, M)
    _recut_precondition_cases(check, M)
    _recut_describes_cases(check, M)


_AR_ANSWERS = re.compile(r"--answer ([a-z|-]+)")


def _offers(text):
    """The answers the last decision printed in `text` offers, in order."""
    found = _AR_ANSWERS.findall(text or "")
    return found[-1].split("|") if found else []


def _tree_rows(root):
    return len([a for a in _actions(root) if a == "task.worktree"])


def _commit_in(tree, message="the agent commits its work"):
    """Commit the task's file in its own tree, as an agent may; HEAD after."""
    _harness.git(tree, "add", "src/f1.txt")
    _harness.git(tree, "commit", "-qm", message)
    return _git_out(tree, "rev-parse", "HEAD").strip()


def _nested_repo(tree):
    """A nested repository with a commit of its own at `src/sub` of `tree`; the
    path of its one file."""
    sub = os.path.join(tree, "src", "sub")
    os.makedirs(sub)
    _harness.git(sub, "init", "-q")
    _write_lf(os.path.join(sub, "lib.txt"), "nested work\n")
    _harness.git(sub, "add", "-A")
    _harness.git(sub, "commit", "-qm", "nested")
    return os.path.join(sub, "lib.txt")


def _gone(root, tree):
    """The member's tree deleted and git told to forget it."""
    _harness.remove_tree(tree)
    _harness.git(root, "worktree", "prune")


def _kept_named(root, said):
    """Whether `said` names every patch a redo kept in `root`'s drive state,
    and at least one is kept."""
    drive = os.path.join(root, ".claude", "state", "drive")
    kept = [os.path.join(drive, n) for n in os.listdir(drive) if n.endswith(".patch")]
    return bool(kept) and all(k in said for k in kept)


def _no_patch(root):
    return not [n for n in os.listdir(os.path.join(root, ".claude", "state", "drive"))
                if n.endswith(".patch")]


def _recut_precondition_cases(check, M):
    """`redo` is offered for one refusal only - work that moved under the tree -
    and the recut checks what it stands on before anything comes down: a tree
    with its marker, HEAD at the recorded base, no nested repository the work
    would carry as a link. Every other way the mover declines offers `block`."""
    # The mover declines a tree that is not at its recorded base (the agent
    # committed there): block only, nothing gated, the commit still the tree's.
    def committing(tree):
        _commit_in(tree)
        _write_lf(os.path.join(tree, "src", "extra.txt"), "extra, uncommitted\n")
    root, mpath, _head, tree = _ab_red_at_base(M, "arecutk", then=committing)
    agent = _git_out(tree, "rev-parse", "HEAD").strip() if tree else ""
    rows = len(_rows_of(root, mpath, "P1.1"))
    code, text = _next(M, root, mpath, "--answer", "rerun")
    code_r, said_r = _next(M, root, mpath, "--answer", "redo")
    check("ar9 a tree standing on a commit the agent made is not offered redo: "
          "the drive stops at a decision offering block alone, gates nothing, and "
          "redo is no answer to it; the commit is still the tree's HEAD: %r"
          % ((code, _offers(text), code_r, text[-400:]),),
          agent and instruction(text)[0] == "decide" and _offers(text) == ["block"]
          and len(_rows_of(root, mpath, "P1.1")) == rows
          and code_r == 2 and _git_out(tree, "rev-parse", "HEAD").strip() == agent
          and _read(os.path.join(tree, "src", "f1.txt")) == b"changed by P1.1\n"
          and os.path.isfile(os.path.join(tree, "src", "extra.txt")))

    # Offered redo for a genuine overlap, then the agent commits in the tree:
    # the recut refuses on HEAD, before anything comes down.
    root_h, mpath_h, _hh, tree_h, base_h, _rh, _c, text_h = _ar_at_decision(
        M, "arecuth")
    carry_h = _carry_at(root_h, "P1.1")
    agent_h = _commit_in(tree_h)
    made_h = _tree_rows(root_h)
    code_h, said_h = _next(M, root_h, mpath_h, "--answer", "redo")
    check("ar10 a redo over a tree whose HEAD is no longer its recorded base is "
          "refused by name before anything comes down: the commit stays the "
          "tree's HEAD, no tree is cut, the carry ref is as it was: %r"
          % ((code_h, said_h[-400:]),),
          "redo" in _offers(text_h) and code_h != 0 and "redo refused" in said_h
          and base_h[:12] in said_h
          and _tree_of(root_h, "P1.1") == tree_h
          and _git_out(tree_h, "rev-parse", "HEAD").strip() == agent_h
          and _read(os.path.join(tree_h, "src", "f1.txt")) == _AR_WORK.encode()
          and _tree_rows(root_h) == made_h and _carry_at(root_h, "P1.1") == carry_h
          and _no_patch(root_h))
    code_h2, again_h = _next(M, root_h, mpath_h)
    check("ar10b ...and the next run, asking the mover again, offers block alone: "
          "%r" % ((code_h2, again_h[-300:]),),
          instruction(again_h)[0] == "decide" and _offers(again_h) == ["block"])

    # The tree is gone and git has forgotten it: the work is in the carry ref
    # alone, and a recut would cut an empty tree and close on nothing.
    root_g, mpath_g, _hg, tree_g, _bg, _rg, _c, _t = _ar_at_decision(M, "arecutg")
    carry_g = _carry_at(root_g, "P1.1")
    _gone(root_g, tree_g)
    made_g = _tree_rows(root_g)
    code_g, said_g = _next(M, root_g, mpath_g, "--answer", "redo")
    check("ar11 a redo with the tree gone is refused, naming the carry ref as "
          "where the work is; no tree is cut and the carry ref is as it was: %r"
          % ((code_g, said_g[-400:]),),
          carry_g and code_g != 0 and "redo refused" in said_g
          and "refs/audit/carry/P1.1" in said_g
          and _tree_rows(root_g) == made_g and _carry_at(root_g, "P1.1") == carry_g
          and tasks_of(mpath_g)["P1.1"].get("status") == "in_progress"
          and _no_patch(root_g))

    root_p, mpath_p, _hp, tree_p = _ab_red_at_base(M, "arecutp")
    _gone(root_p, tree_p)
    rows_p = len(_rows_of(root_p, mpath_p, "P1.1"))
    code_p, text_p = _next(M, root_p, mpath_p, "--answer", "rerun")
    check("ar12 a member whose tree is gone, at the mover, is offered block alone "
          "and gated nowhere: %r" % ((code_p, _offers(text_p), text_p[-400:]),),
          instruction(text_p)[0] == "decide" and _offers(text_p) == ["block"]
          and len(_rows_of(root_p, mpath_p, "P1.1")) == rows_p)

    # A nested repository in the tree: the mover will not copy it, and a recut
    # would carry it as a link to objects the tree's removal deletes.
    root_n, mpath_n, _hn, tree_n = _ab_red_at_base(M, "arecutn")
    lib_n = _nested_repo(tree_n)
    rows_n = len(_rows_of(root_n, mpath_n, "P1.1"))
    code_n, text_n = _next(M, root_n, mpath_n, "--answer", "rerun")
    check("ar13 a tree holding a nested repository, at the mover, is offered "
          "block alone, gated nowhere, the nested repository untouched: %r"
          % ((code_n, _offers(text_n), text_n[-400:]),),
          instruction(text_n)[0] == "decide" and _offers(text_n) == ["block"]
          and len(_rows_of(root_n, mpath_n, "P1.1")) == rows_n
          and _read(lib_n) == b"nested work\n")

    root_s, mpath_s, _hs, tree_s, base_s, _rs, _c, _t = _ar_at_decision(
        M, "arecutsub")
    carry_s = _carry_at(root_s, "P1.1")
    lib_s = _nested_repo(tree_s)
    code_s, said_s = _next(M, root_s, mpath_s, "--answer", "redo")
    check("ar14 a redo over a tree holding a nested repository the base lacks is "
          "refused by name before anything comes down; the nested repository, "
          "the tree and the carry ref are as they were: %r"
          % ((code_s, said_s[-400:]),),
          code_s != 0 and "redo refused" in said_s and "src/sub" in said_s
          and os.path.isfile(lib_s) and _read(lib_s) == b"nested work\n"
          and _git_out(tree_s, "rev-parse", "HEAD").strip() == base_s
          and _carry_at(root_s, "P1.1") == carry_s and _no_patch(root_s))

    # A file the agent staged with `add -f` over an ignore rule is work the
    # tree's own index holds: a recut that reads the work any other way drops
    # it and then removes the only tree that held it.
    root_f, mpath_f, _hf, _tf, _bf, _rf, _c, text_f = _ar_at_decision(
        M, "arecutf", then=_force_added)
    code_f, said_f = _next(M, root_f, mpath_f, "--answer", "redo")
    recut_f = _tree_of(root_f, "P1.1")
    forced_f = os.path.join(recut_f or "", *_AR_FORCED.split("/"))
    held_f = _read(forced_f) if recut_f and os.path.isfile(forced_f) else None
    carried_f = _git_out(root_f, "show", "refs/audit/carry/P1.1:" + _AR_FORCED)
    check("ar15 a file force-added over an ignore rule is carried by the redo: "
          "the recut tree holds it as the old tree did, the did-line names it "
          "among what was carried, and the carry ref moved to the recut tree "
          "holds it: %r" % ((code_f, held_f, carried_f, said_f[-500:]),),
          "redo" in _offers(text_f) and code_f == 0
          and _AR_FORCED in said_f.split("its work carried over", 1)[-1]
          and held_f == _AR_FORCED_TEXT.encode()
          and carried_f == _AR_FORCED_TEXT)

    # Whatever the read of the work misses, the commit it builds is checked
    # against what git status lists in the tree: here the seed from the tree's
    # own index reads nothing, as a read from HEAD would, and the redo is
    # refused before anything comes down rather than dropping the file. The
    # filed carry ref is taken away first - a filing made on another machine,
    # or one that carried nothing - so the carry's own lost-path refusal
    # (ar8) cannot be what stops it.
    real_git = M.carry_git

    def unseeded(where, argv, env=None, stdin=None):
        if argv[:1] == ["ls-files"] and "-s" in argv:
            return 0, b"", ""
        return real_git(where, argv, env=env, stdin=stdin)
    root_u, mpath_u, _hu, tree_u, base_u, _ru, _c, text_u = _ar_at_decision(
        M, "arecutu", then=_force_added)
    carry_u = _drop_carry(root_u, "P1.1")
    made_u = _tree_rows(root_u)
    M.carry_git = unseeded
    try:
        code_u, said_u = _next(M, root_u, mpath_u, "--answer", "redo")
    finally:
        M.carry_git = real_git
    check("ar17 a read of the work that misses a path git status lists in the "
          "tree refuses the redo by name before anything comes down: the old "
          "tree, its forced file and the carry ref are as they were: %r"
          % ((code_u, said_u[-500:]),),
          "redo" in _offers(text_u) and code_u != 0
          and _AR_FORCED in said_u and "nothing was recut" in said_u
          and _tree_of(root_u, "P1.1") == tree_u and _tree_rows(root_u) == made_u
          and _git_out(tree_u, "rev-parse", "HEAD").strip() == base_u
          and _read(os.path.join(tree_u, *_AR_FORCED.split("/")))
          == _AR_FORCED_TEXT.encode()
          and carry_u and not _carry_at(root_u, "P1.1") and _no_patch(root_u))

    # The other half of that check: a path the commit would hold with bytes
    # other than the tree's file - here `add -A` takes nothing from the files,
    # so the edited source stays at its base bytes in the commit.
    def unadded(where, argv, env=None, stdin=None):
        if argv == ["add", "-A"]:
            return 0, b"", ""
        return real_git(where, argv, env=env, stdin=stdin)
    root_v, mpath_v, _hv, tree_v, base_v, _rv, _c, text_v = _ar_at_decision(
        M, "arecutv")
    carry_v = _drop_carry(root_v, "P1.1")
    M.carry_git = unadded
    try:
        code_v, said_v = _next(M, root_v, mpath_v, "--answer", "redo")
    finally:
        M.carry_git = real_git
    check("ar17b a read of the work holding a path with bytes other than the "
          "tree's file refuses the redo by name before anything comes down: %r"
          % ((code_v, said_v[-500:]),),
          "redo" in _offers(text_v) and code_v != 0
          and "src/f1.txt" in said_v and "nothing was recut" in said_v
          and _tree_of(root_v, "P1.1") == tree_v
          and _git_out(tree_v, "rev-parse", "HEAD").strip() == base_v
          and _read(os.path.join(tree_v, "src", "f1.txt")) == _AR_WORK.encode()
          and carry_v and _no_patch(root_v))

    # A submodule the base holds, whose pointer the task moved: its commit
    # lives in the tree's own modules directory, which removing the tree
    # deletes, and the superproject's work names it without keeping it.
    root_m, mpath_m, _hm, tree_m, base_m, _rm, _c, text_m = _ar_at_decision(
        M, "arecutm", prepare=_with_submodule)
    carry_m = _carry_at(root_m, "P1.1")
    moved_m = _move_submodule(tree_m)
    made_m = _tree_rows(root_m)
    code_m, said_m = _next(M, root_m, mpath_m, "--answer", "redo")
    mod_m = os.path.join(tree_m, *_AR_MODULE.split("/"))
    check("ar16 a redo over a tree whose work moves a submodule pointer is "
          "refused by name before anything comes down: the tree, its submodule "
          "commit and the carry ref are as they were: %r"
          % ((code_m, said_m[-400:]),),
          "redo" in _offers(text_m) and moved_m
          and code_m != 0 and "redo refused" in said_m and _AR_MODULE in said_m
          and _tree_of(root_m, "P1.1") == tree_m and _tree_rows(root_m) == made_m
          and _git_out(tree_m, "rev-parse", "HEAD").strip() == base_m
          and _git_out(mod_m, "rev-parse", "HEAD").strip() == moved_m
          and _carry_at(root_m, "P1.1") == carry_m and _no_patch(root_m))


_AR_FORCED = "src/schema.gen"
_AR_FORCED_TEXT = "generated, and wanted by P1.1\n"
_AR_MODULE = "vendor/mod"
# A submodule cloned from a local path: git refuses the file transport for
# submodules unless asked, which is the only thing this switch changes.
_FILE_PROTOCOL = ("-c", "protocol.file.allow=always")


def _force_added(tree):
    """Ignore `*.gen` for every tree of the repository, then stage
    `_AR_FORCED` in `tree` over that rule, as an agent's `git add -f` does."""
    common = _git_out(tree, "rev-parse", "--git-common-dir").strip()
    info = os.path.join(tree, common, "info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "exclude"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write("*.gen\n")
    _write_lf(os.path.join(tree, *_AR_FORCED.split("/")), _AR_FORCED_TEXT)
    _harness.git(tree, "add", "-f", _AR_FORCED)


def _with_submodule(root):
    """Commit a submodule at `_AR_MODULE` in `root`, cloned from a repository
    of its own in a fixture directory."""
    src = os.path.realpath(_harness.fixture_root("drive-modsrc-"))
    _harness.git(src, "init", "-q")
    _write_lf(os.path.join(src, "lib.txt"), "module v1\n")
    _harness.git(src, "add", "-A")
    _harness.git(src, "commit", "-qm", "module")
    _harness.git(root, *(_FILE_PROTOCOL + ("submodule", "add", "-q", src,
                                           _AR_MODULE)))
    _harness.git(root, "commit", "-qm", "a submodule")


def _move_submodule(tree):
    """Check the submodule out in `tree` and commit in it, moving the pointer
    the tree's work holds; the new submodule commit."""
    _harness.git(tree, *(_FILE_PROTOCOL + ("submodule", "update", "--init", "-q")))
    mod = os.path.join(tree, *_AR_MODULE.split("/"))
    _write_lf(os.path.join(mod, "lib.txt"), "module moved by P1.1\n")
    _harness.git(mod, "commit", "-qam", "the task moves the module")
    return _git_out(mod, "rev-parse", "HEAD").strip()


def _drop_carry(root, task_id):
    """Take `task_id`'s carry ref away; the commit it named, or '' when there
    was none."""
    carry = _carry_at(root, task_id)
    if carry:
        _harness.git(root, "update-ref", "-d", "refs/audit/carry/%s" % (task_id,))
    return carry


def _carry_with(root, task_id, rel, text):
    """Point `task_id`'s carry ref at a commit holding `rel` beside what the
    carry held, built in a scratch index so no tree is touched. The new sha, or
    '' when there was no carry to add to."""
    import tempfile
    carry = _carry_at(root, task_id)
    if not carry:
        return ""
    scratch = tempfile.mkdtemp(prefix="arecut-carry-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(scratch, "index"))

        def git(*args, **kw):
            return subprocess.run(_GIT + list(args), cwd=root, env=env,
                                  capture_output=True, input=kw.get("data")
                                  ).stdout.decode("utf-8").strip()
        git("read-tree", carry)
        blob = git("hash-object", "-w", "--stdin", data=text.encode("utf-8"))
        git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, rel))
        sha = git("commit-tree", git("write-tree"), "-p", carry + "^", "-m", "carry")
        git("update-ref", "refs/audit/carry/%s" % (task_id,), sha)
    finally:
        _harness.remove_tree(scratch)
    return _carry_at(root, task_id) if sha else ""


_AR_IDLE = "src/f3.txt"
_AR_IDLE_BASE = "v0\n"


def _redo_refused_intact(M, root, mpath, tree, base, name):
    """Answer `redo`. -> (refused, code, said): `refused` when the drive stopped
    naming `name` and saying nothing was recut, with the old tree where it was,
    at its base, no tree cut and no patch kept."""
    made = _tree_rows(root)
    code, said = _next(M, root, mpath, "--answer", "redo")
    refused = (code != 0 and name in said and "nothing was recut" in said
               and _tree_of(root, "P1.1") == tree and os.path.isdir(tree)
               and _tree_rows(root) == made
               and _git_out(tree, "rev-parse", "HEAD").strip() == base
               and _no_patch(root))
    return refused, code, said


def _carried_part(said):
    """What the recut's did-line lists as carried, '' when it printed none."""
    return said.split("its work carried over", 1)[-1].split("\n", 1)[0] \
        if "its work carried over" in said else ""


def _exclude(tree, pattern):
    """Ignore `pattern` for every tree of `tree`'s repository."""
    common = _git_out(tree, "rev-parse", "--git-common-dir").strip()
    info = os.path.join(tree, common, "info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "exclude"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(pattern + "\n")


def _submodule_ignoring(value):
    """A `prepare` committing `_AR_MODULE` as a submodule whose `.gitmodules`
    entry says `ignore = value`."""
    def prepare(root):
        _with_submodule(root)
        _harness.git(root, "config", "-f", ".gitmodules",
                     "submodule.%s.ignore" % (_AR_MODULE,), value)
        _harness.git(root, "commit", "-qam", "the submodule is ignored: %s" % (value,))
    return prepare


def _dirty_submodule(tree):
    """Check the submodule out in `tree` and edit its file without committing;
    the file's path."""
    _harness.git(tree, *(_FILE_PROTOCOL + ("submodule", "update", "--init", "-q")))
    edited = os.path.join(tree, *(_AR_MODULE.split("/") + ["lib.txt"]))
    _write_lf(edited, "edited by P1.1, never committed\n")
    return edited


def _with_tracked_log(root):
    """Commit `build.log` in `root`, as a base that tracked a build product."""
    _write_lf(os.path.join(root, "build.log"), "a log the base tracked\n")
    _harness.git(root, "add", "build.log")
    _harness.git(root, "commit", "-qm", "a tracked log")


def _recut_describes_cases(check, M):
    """The recut takes the old tree down only when the work it read, with what
    the tree's own index records, describes that tree whole and nothing in it is
    a repository a commit cannot carry. Each refusal stops before anything comes
    down; each has a case beside it where the same check must stay quiet."""
    # A submodule whose `.gitmodules` entry says ignore=all: git status, add -A
    # and every diff that honours the setting are blind to the commit the task
    # made in it, which lives in the tree's own modules directory.
    root_a, mpath_a, _h, tree_a, base_a, _r, _c, text_a = _ar_at_decision(
        M, "arecutia", prepare=_submodule_ignoring("all"))
    moved_a = _move_submodule(tree_a)
    refused_a, code_a, said_a = _redo_refused_intact(M, root_a, mpath_a, tree_a,
                                                     base_a, _AR_MODULE)
    mod_a = os.path.join(tree_a, *_AR_MODULE.split("/"))
    check("ar18 a tree holding a submodule git is told to ignore entirely "
          "refuses the redo by name before anything comes down, its commit in "
          "the submodule kept: %r" % ((code_a, said_a[-400:]),),
          "redo" in _offers(text_a) and refused_a
          and _git_out(mod_a, "rev-parse", "HEAD").strip() == moved_a)

    # ignore=dirty: the uncommitted edit inside the submodule is invisible the
    # same way. It is the submodule's own change, not the task's work, so it
    # stops no redo; the old tree is set aside and kept, the edit in it, since
    # a removal would delete it.
    root_d, mpath_d, _h, tree_d, base_d, _r, _c, text_d = _ar_at_decision(
        M, "arecutid", prepare=_submodule_ignoring("dirty"))
    _dirty_submodule(tree_d)
    code_d, said_d = _next(M, root_d, mpath_d, "--answer", "redo")
    aside_d = _aside_said(said_d)
    edited_d = os.path.join(aside_d, *(_AR_MODULE.split("/") + ["lib.txt"]))
    check("ar18b a tree holding a submodule whose dirt git is told to ignore is "
          "recut, its old tree set aside and kept for the submodule, the edit "
          "inside it as it was: %r" % ((code_d, aside_d, said_d[-500:]),),
          "redo" in _offers(text_d) and code_d == 0 and aside_d
          and "set aside at %s, kept (%s" % (aside_d, _AR_MODULE) in said_d
          and os.path.isfile(edited_d)
          and _read(edited_d) == b"edited by P1.1, never committed\n")

    # The repository-wide setting hides every submodule from every diff.
    root_g, mpath_g, _h, tree_g, base_g, _r, _c, text_g = _ar_at_decision(
        M, "arecutig", prepare=_with_submodule)
    _harness.git(tree_g, "config", "diff.ignoreSubmodules", "all")
    moved_g = _move_submodule(tree_g)
    refused_g, code_g, said_g = _redo_refused_intact(M, root_g, mpath_g, tree_g,
                                                     base_g, _AR_MODULE)
    mod_g = os.path.join(tree_g, *_AR_MODULE.split("/"))
    check("ar18c a tree under diff.ignoreSubmodules=all whose work moves a "
          "submodule refuses the redo by name, the submodule commit kept: %r"
          % ((code_g, said_g[-400:]),),
          "redo" in _offers(text_g) and refused_g
          and _git_out(mod_g, "rev-parse", "HEAD").strip() == moved_g)

    # A submodule the base holds and the tree never checked out holds nothing
    # and stops no redo: `ta2` in `_set_aside_cases` drives it.

    # A repository inside an ignored directory: no git listing of the tree
    # names it, and the tree's removal deletes its commits.
    root_n, mpath_n, _h, tree_n, base_n, _r, _c, text_n = _ar_at_decision(M, "arecutin")
    _exclude(tree_n, "out/")
    nested_n = os.path.join(tree_n, "out", "cache")
    os.makedirs(nested_n)
    _harness.git(nested_n, "init", "-q")
    _write_lf(os.path.join(nested_n, "lib.txt"), "nested work\n")
    _harness.git(nested_n, "add", "-A")
    _harness.git(nested_n, "commit", "-qm", "nested")
    refused_n, code_n, said_n = _redo_refused_intact(M, root_n, mpath_n, tree_n,
                                                     base_n, "out/cache")
    check("ar18d a repository nested in an ignored directory of the tree refuses "
          "the redo by name, its commit kept: %r" % ((code_n, said_n[-400:]),),
          "redo" in _offers(text_n) and refused_n
          and _git_out(nested_n, "log", "--format=%s", "-1").strip() == "nested")

    # OVER-FIRE of ar18d: names that merely begin with `.git` are files, not
    # repositories - a nested-repository check that matched a prefix, or any
    # dot-name, would refuse this tree.
    root_o, mpath_o, _h, tree_o, _b, _r, _c, _t = _ar_at_decision(M, "arecutio")
    _write_lf(os.path.join(tree_o, "src", ".gitkeep"), "")
    _write_lf(os.path.join(tree_o, "src", ".git-notes.txt"), "a note\n")
    code_o, said_o = _next(M, root_o, mpath_o, "--answer", "redo")
    recut_o = _tree_of(root_o, "P1.1")
    check("ar18e a tree whose work adds files named like .gitkeep is recut, those "
          "files carried: %r" % ((code_o, said_o[-500:]),),
          code_o == 0 and recut_o
          and "src/.gitkeep" in _carried_part(said_o)
          and _read(os.path.join(recut_o, "src", ".git-notes.txt")) == b"a note\n")

    # OVER-FIRE: an ignored file the task untracked (`git rm --cached`, the
    # ordinary clean-up of a committed build product) is not work the carry
    # lacks: the index and the carry both drop it, and git ignores the file.
    root_l, mpath_l, _h, tree_l, _b, _r, _c, _t = _ar_at_decision(
        M, "arecutil", prepare=_with_tracked_log)
    _exclude(tree_l, "build.log")
    _harness.git(tree_l, "rm", "-q", "--cached", "build.log")
    code_l, said_l = _next(M, root_l, mpath_l, "--answer", "redo")
    check("ar19 a tracked file the task untracked and git ignores is carried as "
          "the deletion it is, and the redo recuts: %r" % ((code_l, said_l[-500:]),),
          code_l == 0 and "could not be read" not in said_l
          and "build.log" in _carried_part(said_l))

    # A file the index marks assume-unchanged is one git status does not look
    # at. The check looks at it anyway, so a read of the work that misses its
    # bytes - here `add -A` is made to pass over it - is refused, not trusted.
    real_git = M.carry_git

    def passing_over(where, argv, env=None, stdin=None):
        if argv == ["add", "-A"]:
            argv = ["add", "-A", "--", ".", ":(exclude)" + _AR_IDLE]
        return real_git(where, argv, env=env, stdin=stdin)
    root_w, mpath_w, _h, tree_w, base_w, _r, _c, _t = _ar_at_decision(M, "arecutaw")
    _drop_carry(root_w, "P1.1")
    _harness.git(tree_w, "update-index", "--assume-unchanged", _AR_IDLE)
    idle_w = os.path.join(tree_w, *_AR_IDLE.split("/"))
    _write_lf(idle_w, "edited under assume-unchanged\n")
    M.carry_git = passing_over
    try:
        refused_w, code_w, said_w = _redo_refused_intact(
            M, root_w, mpath_w, tree_w, base_w, _AR_IDLE)
    finally:
        M.carry_git = real_git
    check("ar17c a read of the work missing a file the index marks "
          "assume-unchanged refuses the redo by name, the edit kept: %r"
          % ((code_w, said_w[-400:]),),
          refused_w and _read(idle_w) == b"edited under assume-unchanged\n")

    # The index holds a deletion the files do not show: `git rm --cached` of a
    # file nothing ignores. A commit of the tree's files cannot hold it.
    root_c, mpath_c, _h, tree_c, base_c, _r, _c, _t = _ar_at_decision(M, "arecutrc")
    _harness.git(tree_c, "rm", "-q", "--cached", _AR_IDLE)
    refused_c, code_c, said_c = _redo_refused_intact(M, root_c, mpath_c, tree_c,
                                                     base_c, _AR_IDLE)
    check("ar20 a staged deletion of a file still on disk refuses the redo by "
          "name, the tree's index as it was: %r" % ((code_c, said_c[-400:]),),
          refused_c and _git_out(tree_c, "ls-files", "--", _AR_IDLE).strip() == ""
          and _read(os.path.join(tree_c, *_AR_IDLE.split("/")))
          == _AR_IDLE_BASE.encode())

    # The index holds an edit the file no longer shows: staged, then the file
    # put back. Its only copy is the index entry.
    root_m, mpath_m, _h, tree_m, base_m, _r, _c, _t = _ar_at_decision(M, "arecutmm")
    idle_m = os.path.join(tree_m, *_AR_IDLE.split("/"))
    _write_lf(idle_m, "staged by P1.1\n")
    _harness.git(tree_m, "add", _AR_IDLE)
    _write_lf(idle_m, _AR_IDLE_BASE)
    refused_m, code_m, said_m = _redo_refused_intact(M, root_m, mpath_m, tree_m,
                                                     base_m, _AR_IDLE)
    check("ar20b a staged edit whose file was put back refuses the redo by name, "
          "the staged copy kept in the tree's index: %r" % ((code_m, said_m[-400:]),),
          refused_m and _git_out(tree_m, "show", ":" + _AR_IDLE) == "staged by P1.1\n")

    # OVER-FIRE of ar20/ar20b: a staged edit the file still shows is held by
    # the carry as the index holds it - an index check that refused every
    # staged path would refuse this tree.
    root_s, mpath_s, _h, tree_s, _b, _r, _c, _t = _ar_at_decision(M, "arecutst")
    _harness.git(tree_s, "add", "src/f1.txt")
    code_s, said_s = _next(M, root_s, mpath_s, "--answer", "redo")
    check("ar20c a staged edit the file still shows is carried and the redo "
          "recuts: %r" % ((code_s, said_s[-500:]),),
          code_s == 0 and "merged three-way (src/f1.txt)" in said_s
          and tasks_of(mpath_s)["P1.1"].get("status") == "done"
          and _read(os.path.join(root_s, "src", "f1.txt")) == _AR_MERGED)

    # OVER-FIRE of ar20/ar20b: a record path staged in the tree's index is the
    # phase's, refreshed into the new tree and never carried, so the carry
    # lacking it is no staged state left behind.
    root_p, mpath_p, _h, tree_p, _b, _r, _c, _t = _ar_at_decision(M, "arecutrp")
    plan_p = os.path.relpath(mpath_p, root_p).replace(os.sep, "/")
    with open(os.path.join(tree_p, *plan_p.split("/")), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write("\n")
    _harness.git(tree_p, "add", plan_p)
    staged_p = _git_out(tree_p, "diff", "--cached", "--name-only").split()
    code_p, said_p = _next(M, root_p, mpath_p, "--answer", "redo")
    check("ar20d a record path staged in the tree's index does not refuse the "
          "redo, and is not carried: %r" % ((staged_p, code_p, said_p[-500:]),),
          staged_p == [plan_p] and code_p == 0
          and "merged three-way (src/f1.txt)" in said_p
          and plan_p not in _carried_part(said_p))

    # A skip-worktree entry absent from disk is a file the tree does not check
    # out, not one the task deleted: the carry keeps it as the index does.
    root_k, mpath_k, _h, tree_k, _b, _r, _c, _t = _ar_at_decision(M, "arecutsk")
    _harness.git(tree_k, "update-index", "--skip-worktree", _AR_IDLE)
    os.remove(os.path.join(tree_k, *_AR_IDLE.split("/")))
    code_k, said_k = _next(M, root_k, mpath_k, "--answer", "redo")
    check("ar21 a skip-worktree file absent from disk is not carried as a "
          "deletion: the recut carries the work alone and the member closes with "
          "the file as the base held it: %r" % ((code_k, said_k[-500:]),),
          code_k == 0 and "merged three-way (src/f1.txt)" in said_k
          and _AR_IDLE not in _carried_part(said_k)
          and tasks_of(mpath_k)["P1.1"].get("status") == "done"
          and _read(os.path.join(root_k, *_AR_IDLE.split("/")))
          == _AR_IDLE_BASE.encode())

    # A path git names in bytes that are not UTF-8 must reach git again as the
    # same bytes: a pathspec decoded with replacement characters matches
    # nothing, so the path reads as held. Asked of the functions directly, as
    # some filesystems refuse such a name outright.
    raw = b"caf\xe9.txt"
    seen = []

    def lister(where, argv, env=None, stdin=None):
        seen.append(list(argv))
        if "status" in argv:
            return 0, b" M " + raw + b"\0", ""
        if argv[:1] == ["diff"] and "--name-only" in argv and "--" not in argv:
            return 0, raw + b"\0", ""
        return 0, b"", ""
    real_git = M.carry_git
    M.carry_git = lister
    try:
        listed, _w = M.tree_changed("/nowhere")
        between, _w = M._changed_between("/nowhere", "a", "b")
        M._unheld("/nowhere", {}, listed or [])
    finally:
        M.carry_git = real_git
    specs = [os.fsencode(a) for argv in seen for a in argv
             if isinstance(a, str) and a.startswith(":(literal)")]
    check("ar22 a path git lists in bytes that are not UTF-8 keeps its bytes: "
          "the listings return it whole, and the pathspec handed back to git "
          "names those bytes: %r" % ((listed, between, specs),),
          [os.fsencode(p) for p in listed or []] == [raw]
          and [os.fsencode(p) for p in between or []] == [raw]
          and specs and all(s == b":(literal)" + raw for s in specs))


def _recut_crash_cases(check, M):
    """A redo that fails part way leaves the work where a human finds it: before
    the old tree is taken down, the tree itself, untouched; after, the patch the
    redo kept, with the carry ref as it was."""
    real_git = M.carry_git

    def refusing_check(where, argv, env=None, stdin=None):
        if argv[:1] == ["apply"] and "--cached" in argv:
            return 1, b"", "fixture: the check could not run"
        return real_git(where, argv, env=env, stdin=stdin)
    root, mpath, _head, tree, base, _rows, _code, _text = _ar_at_decision(
        M, "arecutx")
    carry = _carry_at(root, "P1.1")
    status = _git_out(tree, "status", "--porcelain") if tree else ""
    M.carry_git = refusing_check
    try:
        code, said = _next(M, root, mpath, "--answer", "redo")
    finally:
        M.carry_git = real_git
    check("ar5 a redo that fails before the old tree comes down leaves that "
          "tree, its base, its work, its index and the carry ref as they were: "
          "%r" % ((code, said[-400:]),),
          code != 0 and "fixture: the check could not run" in said
          and carry and _tree_of(root, "P1.1") == tree
          and _git_out(tree, "rev-parse", "HEAD").strip() == base
          and _git_out(tree, "status", "--porcelain") == status
          and _read(os.path.join(tree, "src", "f1.txt")) == _AR_WORK.encode()
          and _carry_at(root, "P1.1") == carry)

    real_verb = M.run_verb

    def refusing_add(ctx, script, args, stdin=None):
        if script == "manage-worktrees.py" and args[:1] == ["task-add"]:
            return 1, "", "fixture: task-add refused"
        return real_verb(ctx, script, args, stdin=stdin)
    root_a, mpath_a, _head_a, _tree_a, _base_a, _rows_a, _c, _t = \
        _ar_at_decision(M, "arecuta")
    carry_a = _carry_at(root_a, "P1.1")
    M.run_verb = refusing_add
    try:
        code_a, said_a = _next(M, root_a, mpath_a, "--answer", "redo")
    finally:
        M.run_verb = real_verb
    kept = [os.path.join(root_a, ".claude", "state", "drive", n)
            for n in os.listdir(os.path.join(root_a, ".claude", "state", "drive"))
            if n.endswith(".patch")]
    check("ar6 a redo that fails after the old tree came down stops, naming the "
          "patch it kept, which holds the work, and the carry ref is as it was: "
          "%r" % ((code_a, kept, said_a[-400:]),),
          code_a != 0 and len(kept) == 1 and kept[0] in said_a
          and b"one by P1.1" in _read(kept[0])
          and _carry_at(root_a, "P1.1") == carry_a and carry_a)
    pinned = _git_out(root_a, "show", "refs/audit/redo/P1.1:src/f1.txt")
    check("ar6c ...and the work commit is pinned to refs/audit/redo/P1.1 until a "
          "redo succeeds, so no gc takes the objects the patch names: %r"
          % (pinned,), pinned == _AR_WORK)
    rows_a = len(_rows_of(root_a, mpath_a, "P1.1"))
    code_a2, said_a2 = _next(M, root_a, mpath_a)
    check("ar6b ...and the next run measures, integrates and closes nothing over "
          "a tree that may lack that work: it stops naming the patch: %r"
          % ((code_a2, said_a2[-400:]),),
          code_a2 != 0 and kept and kept[0] in said_a2
          and len(_rows_of(root_a, mpath_a, "P1.1")) == rows_a
          and tasks_of(mpath_a)["P1.1"].get("status") == "in_progress")
    # The other direction of ar6d: a tree that lacks the work is still told to
    # take the patch in, never that it holds it already.
    check("ar6e ...and, its tree lacking that work, the stop prescribes the "
          "three-way apply there: %r" % (said_a2[-400:],),
          "git apply --3way" in said_a2 and "already holds" not in said_a2)

    # Stopped with the patch kept while the old tree still stands - the move
    # that sets it aside failed - so the tree holds the work, and an apply
    # there would fail on every path it names. The marker the move rewrote is
    # put back, so the tree still answers to the task.
    real_rename = os.rename
    root_d, mpath_d, _head_d, tree_d, base_d, _rows_d, _c, _t = \
        _ar_at_decision(M, "arecutd")

    def refusing_move(src, dst, *rest, **kw):
        if os.path.realpath(str(src)) == os.path.realpath(tree_d):
            raise OSError(13, "fixture: the tree could not be moved")
        return real_rename(src, dst, *rest, **kw)
    M.os.rename = refusing_move
    try:
        code_d, said_d = _next(M, root_d, mpath_d, "--answer", "redo")
    finally:
        M.os.rename = real_rename
    code_d2, said_d2 = _next(M, root_d, mpath_d)
    marked_d = M._worktrees.read_provenance(tree_d, expect_task="P1.1").get("ours")
    asides_d = [k for k in (_drive_state(root_d).get("keptTrees") or {})
                if "set aside" in k]
    check("ar6d a redo stopped before its old tree was set aside leaves that "
          "tree holding the work, its marker naming the task and no set-aside "
          "recorded, and the stop says so instead of prescribing an apply "
          "there: %r" % ((code_d, said_d[-300:], code_d2, said_d2[-500:],
                          marked_d, asides_d),),
          code_d != 0 and "fixture: the tree could not be moved" in said_d
          and code_d2 != 0 and not _no_patch(root_d)
          and _tree_of(root_d, "P1.1") == tree_d and marked_d is True
          and not asides_d
          and _git_out(tree_d, "rev-parse", "HEAD").strip() == base_d
          and _read(os.path.join(tree_d, "src", "f1.txt")) == _AR_WORK.encode()
          and "already holds" in said_d2 and "git apply" not in said_d2
          and _kept_named(root_d, said_d2))

    # Where the tree could not be read at all, the stop gives no rule a recut
    # tree would break: a path the head moved reads there as the three-way
    # merge left it, never as the pinned work holds it, so "a diff against the
    # pin printing nothing" would send a human to apply over work already in.
    real_held = M.redo_held
    M.redo_held = lambda ctx, state, task_id, tree: (
        None, "fixture: the tree could not be read")
    try:
        code_f, said_f = _next(M, root_d, mpath_d)
    finally:
        M.redo_held = real_held
    check("ar6f a stop that could not read its tree prescribes the apply only "
          "where the tree lacks the work, and gives no diff-against-the-pin "
          "rule a path the head moved would break: %r" % ((code_f, said_f[-500:]),),
          code_f != 0 and "fixture: the tree could not be read" in said_f
          and "only where" in said_f and "printing nothing" not in said_f
          and "moved" in said_f and _kept_named(root_d, said_f))

    # A carried path the head never moved must read in the recut tree as the
    # work held it; one that does not stops the redo by name, the patch kept.
    def scribbling(where, argv, env=None, stdin=None):
        said = real_git(where, argv, env=env, stdin=stdin)
        if argv[:1] == ["apply"] and "--cached" not in argv:
            _write_lf(os.path.join(where, "src", "extra.txt"), "scribbled\n")
        return said
    root_s, mpath_s, head_s, tree_s = _ab_red_at_base(
        M, "arecuts", _AR_PHASE, base=_AR_BASE, work=_AR_WORK)
    _write_lf(os.path.join(tree_s, "src", "extra.txt"), "extra by P1.1\n")
    _next(M, root_s, mpath_s, "--answer", "rerun")
    M.carry_git = scribbling
    try:
        code_s, said_s = _next(M, root_s, mpath_s, "--answer", "redo")
    finally:
        M.carry_git = real_git
    check("ar7 a recut tree whose carried path does not read as the work held it "
          "stops the redo, naming the path and the patch it kept: %r"
          % ((code_s, said_s[-400:]),),
          code_s != 0 and "src/extra.txt" in said_s and ".patch" in said_s
          and tasks_of(mpath_s)["P1.1"].get("status") == "in_progress")


# --- a redo sets the old tree aside; one remover keeps a tree on any doubt -----
_TA_SETTLED = _AR_WORK.replace("six\n", "six, settled by hand\n")
_TA_SETTLED_MERGED = _AR_MERGED.replace(b"six\n", b"six, settled by hand\n")
_TA_ASIDE = re.compile(r"old tree set aside at (.+?)(?: and removed|, kept)")


def _aside_said(said):
    """The set-aside path the redo's did-line names, or ''."""
    hit = _TA_ASIDE.search(said or "")
    return hit.group(1) if hit else ""


def _retire_fixture(prefix, prepare=None, then=None):
    """A one-task plan whose P1.1 has a tree of its own: a linked worktree of
    the fixture repository, detached at its HEAD, carrying the marker naming
    the task, in a fixture directory beside the repository. `prepare(root)`
    commits what else the base holds before the tree is cut, and `then(tree)`
    is what the task did in it. -> (root, mpath, tree)."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1])
    if prepare is not None:
        prepare(root)
    trees = os.path.realpath(_harness.fixture_root("drive-trees-%s-" % (prefix,)))
    tree = os.path.join(trees, "P1.1")
    _harness.git(root, "worktree", "add", "-q", "--detach", tree)
    M, _why = _load("drive_phase_ta_marker")
    M._worktrees.write_record(tree, {
        "createdBy": "audit", "taskId": "P1.1", "phaseId": PHASE,
        "base": _git_out(root, "rev-parse", "HEAD").strip()})
    if then is not None:
        then(tree)
    return root, mpath, tree


def _git_said(root, *args):
    """`(code, stdout and stderr)` of one git call whose refusal is the answer."""
    run = subprocess.run(_GIT + list(args), cwd=root, capture_output=True,
                         encoding="utf-8", errors="replace")
    return run.returncode, run.stdout + run.stderr


def _worktree_block(root, path):
    """The `git worktree list --porcelain` lines of the record whose path is
    `path`, or [] when git lists none there."""
    want = os.path.realpath(path)
    for block in _git_out(root, "worktree", "list", "--porcelain").split("\n\n"):
        lines = block.strip().splitlines()
        if lines and lines[0].startswith("worktree ") \
                and os.path.realpath(lines[0][len("worktree "):]) == want:
            return lines
    return []


def _is_locked(block):
    return any(ln == "locked" or ln.startswith("locked ") for ln in block)


def _drive_ctx(root, mpath):
    """The context a drive step hands the tree functions, for the fixture."""
    return {"gitRoot": root, "project": root, "manifest": mpath, "phase": PHASE,
            "stateDir": os.path.join(root, ".claude", "state"), "did": [],
            "log": [], "config": {}}


def _retired(M, root, mpath, tree, kept=None):
    """Retire P1.1, closed, whose wave tree is `tree` and whose `keptTrees` are
    `kept`, as the drive does once a member is terminal. -> (stop, did,
    standing), and with `kept` given, the `keptTrees` the retirement left."""
    ctx = _drive_ctx(root, mpath)
    state = {"wave": {"trees": {"P1.1": tree}, "records": ["docs/audit"]}}
    if kept is not None:
        state["keptTrees"] = dict(kept)
    task = {"id": "P1.1", "status": "done", "startedAt": "2026-10-28T00:00:00Z"}
    with _Env(root):
        stop = M.retire_member(ctx, state, task)
    if kept is None:
        return stop, ctx["did"], os.path.isdir(tree)
    return stop, ctx["did"], os.path.isdir(tree), state.get("keptTrees") or {}


def _set_aside_cases(check):
    """No drive step destroys a task tree it cannot show holds nothing but
    what is integrated or carried. A redo sets the old tree aside rather than
    taking it down, and removes it only once the recut holds its work whole;
    retiring a closed member goes through the same one remover, which keeps
    the tree on any doubt and says why. Each keep has the twin a remover that
    kept everything would fail: a clean tree is removed."""
    M, why = _load("drive_phase_set_aside")
    if M is None:
        check("ta1 the driver loads", False, why)
        return
    # The integrator stages the member's work in the tree's own index (`git
    # add -A`); a human then settles the refusal by editing the file. The
    # index holds a state the disk has moved past: not work, so the redo goes
    # on - and the old tree, whose index still differs, is set aside, not lost.
    root, mpath, _head, tree, _base, _rows, _c, text = _ar_at_decision(M, "tasettle")
    _harness.git(tree, "add", "-A")
    _write_lf(os.path.join(tree, "src", "f1.txt"), _TA_SETTLED)
    code, said = _next(M, root, mpath, "--answer", "redo")
    aside = _aside_said(said)
    kept = dict(_drive_state(root).get("keptTrees") or {})
    check("ta1 a redo over a tree whose index holds the integrator's staging, "
          "edited since, recuts: the old tree is set aside beside the task's "
          "tree path, named in the did-line and recorded, its index and file "
          "as they were, and the member closes on the settled work merged: %r"
          % ((code, aside, kept, said[-700:]),),
          "redo" in _offers(text) and code == 0 and "redo refused" not in said
          and aside and aside != tree and os.path.isdir(aside)
          and os.path.dirname(aside) == os.path.dirname(tree)
          and aside in kept.values()
          and _git_out(aside, "show", ":src/f1.txt") == _AR_WORK
          and _read(os.path.join(aside, "src", "f1.txt")) == _TA_SETTLED.encode()
          and tasks_of(mpath)["P1.1"].get("status") == "done"
          and _read(os.path.join(root, "src", "f1.txt")) == _TA_SETTLED_MERGED)
    status = _loader.load_script("audit-status.py", "audit_status_ta", cache=False)
    with _Env(root):
        listed = status.kept_trees_block(mpath, root)
    check("ta1b ...and status lists the set-aside tree among the trees a wave "
          "left standing: %r" % (listed,),
          aside and aside in [t.get("path") for t in listed.get("trees") or []])
    # OVER-FIRE twin of ta11: the lock a set-aside takes while it moves the
    # tree is given back once git reads the tree at its new path.
    block = _worktree_block(root, aside) if aside else []
    check("ta1c ...and git lists the set-aside tree at its new path, unlocked: "
          "%r" % (block,), block and not _is_locked(block))

    # A submodule the base holds and the tree never checked out holds nothing:
    # the redo recuts, and the old tree, holding nothing the recut lacks, is
    # removed once the recut holds the work. OVER-FIRE twin of ta1: a set-aside
    # that kept every tree would leave this one standing.
    root_u, mpath_u, _h, tree_u, _b, _r, _c, text_u = _ar_at_decision(
        M, "tauninit", prepare=_with_submodule)
    bare_u = not os.path.lexists(os.path.join(tree_u, *(_AR_MODULE.split("/")
                                                       + [".git"])))
    code_u, said_u = _next(M, root_u, mpath_u, "--answer", "redo")
    aside_u = _aside_said(said_u)
    check("ta2 a tree whose base holds a submodule it never checked out is "
          "recut, and its old tree, set aside, is removed once the recut holds "
          "its work: %r" % ((bare_u, code_u, aside_u, said_u[-600:]),),
          "redo" in _offers(text_u) and bare_u and code_u == 0
          and "redo refused" not in said_u and aside_u
          and "set aside at %s and removed" % (aside_u,) in said_u
          and not os.path.lexists(aside_u)
          and tasks_of(mpath_u)["P1.1"].get("status") == "done")

    # Retire: the same remover. Each keep names what it kept the tree for.
    _root, _mpath, tree_m = _retire_fixture("tamod", prepare=_with_submodule,
                                            then=_move_submodule)
    moved = _git_out(os.path.join(tree_m, *_AR_MODULE.split("/")),
                     "rev-parse", "HEAD").strip()
    stop, did, standing = _retired(M, _root, _mpath, tree_m)
    check("ta3 retiring a closed member whose tree holds a commit in its "
          "submodule keeps the tree, the commit in it, and says why without "
          "stopping: %r" % ((stop, did, standing),),
          stop is None and standing and moved
          and _git_out(os.path.join(tree_m, *_AR_MODULE.split("/")),
                       "rev-parse", "HEAD").strip() == moved
          and any("kept" in d and _AR_MODULE in d for d in did))

    _root, _mpath, tree_n = _retire_fixture("tanest", then=_nested_repo)
    lib_n = os.path.join(tree_n, "src", "sub", "lib.txt")
    stop, did, standing = _retired(M, _root, _mpath, tree_n)
    check("ta4 retiring a closed member whose tree holds a nested repository "
          "keeps the tree and the repository's commit, and says why: %r"
          % ((stop, did, standing),),
          stop is None and standing and os.path.isfile(lib_n)
          and any("kept" in d and "src/sub" in d for d in did))

    _root, _mpath, tree_a = _retire_fixture(
        "taign", prepare=_submodule_ignoring("all"), then=_move_submodule)
    stop, did, standing = _retired(M, _root, _mpath, tree_a)
    check("ta5 retiring a closed member whose tree holds a commit in a "
          "submodule git is told to ignore entirely keeps the tree, and says "
          "why: %r" % ((stop, did, standing),),
          stop is None and standing
          and any("kept" in d and _AR_MODULE in d for d in did))

    # OVER-FIRE twins of ta3-ta5: a clean tree whose work the phase tree holds
    # is removed - with no submodule, and with one the tree never checked out.
    for cid, prefix, prepare in (("ta6", "taclean", None),
                                 ("ta6b", "tacleanmod", _with_submodule)):
        root_c, mpath_c, tree_c = _retire_fixture(prefix, prepare=prepare)
        _write_lf(os.path.join(tree_c, "src", "f1.txt"), "integrated\n")
        _write_lf(os.path.join(root_c, "src", "f1.txt"), "integrated\n")
        stop, did, standing = _retired(M, root_c, mpath_c, tree_c)
        check("%s OVER-FIRE: retiring a closed member whose tree holds only "
              "work the phase tree holds%s removes the tree: %r"
              % (cid, " and a submodule it never checked out" if prepare else "",
                 (stop, did, standing)),
              stop is None and not standing
              and "tree of P1.1 removed" in did)

    # A commit the agent made in the tree, which no branch holds: the work is
    # integrated byte for byte, and only the commit would be lost.
    def committed(tree):
        _write_lf(os.path.join(tree, "src", "f1.txt"), "integrated\n")
        _harness.git(tree, "commit", "-qam", "the agent commits in its tree")
    root_h, mpath_h, tree_h = _retire_fixture("tahead", then=committed)
    _write_lf(os.path.join(root_h, "src", "f1.txt"), "integrated\n")
    agent = _git_out(tree_h, "rev-parse", "HEAD").strip()
    stop, did, standing = _retired(M, root_h, mpath_h, tree_h)
    check("ta8 retiring a closed member whose tree stands on a commit the phase "
          "head does not hold keeps the tree and names that commit: %r"
          % ((stop, did, standing),),
          stop is None and standing and agent
          and any("kept" in d and agent[:12] in d for d in did))

    # A tree whose marker names another task is not this task's to take down.
    root_o, mpath_o, tree_o = _retire_fixture("taother")
    M._worktrees.write_record(tree_o, {
        "createdBy": "audit", "taskId": "P1.9", "phaseId": PHASE,
        "base": _git_out(root_o, "rev-parse", "HEAD").strip()})
    stop, did, standing = _retired(M, root_o, mpath_o, tree_o)
    check("ta9 retiring a member whose tree's marker names another task keeps "
          "the tree, says so, and does not stop the drive: %r"
          % ((stop, did, standing),),
          stop is None and standing
          and any("kept" in d and "P1.9" in d for d in did))

    # A tree a redo set aside, clean and integrated, goes when the task is
    # retired, and its entry with it; the member's own tree too.
    root_s, mpath_s, tree_s = _retire_fixture("tasetaside")
    aside_s = tree_s + ".aside-1"
    _harness.git(root_s, "worktree", "add", "-q", "--detach", aside_s)
    M._worktrees.write_record(aside_s, {
        "createdBy": "audit", "taskId": "P1.1 set aside 1", "phaseId": PHASE,
        "setAsideFrom": "P1.1",
        "base": _git_out(root_s, "rev-parse", "HEAD").strip()})
    stop, did, standing, left = _retired(M, root_s, mpath_s, tree_s,
                                         {"P1.1 set aside 1": aside_s})
    check("ta10 retiring a closed member takes down the clean tree a redo of it "
          "set aside, through the same remover, and forgets its entry: %r"
          % ((stop, did, standing, left),),
          stop is None and not standing and not os.path.isdir(aside_s)
          and not left
          and "set-aside tree of P1.1 removed from %s" % (aside_s,) in did)

    # The filing's carry: a submodule's own dirt is not the task's work.
    def dirty_module(tree):
        _harness.git(tree, *(_FILE_PROTOCOL + ("submodule", "update", "--init", "-q")))
        _write_lf(os.path.join(tree, "src", "f1.txt"), "carried\n")
    root_d, mpath_d, tree_d = _retire_fixture("tadirty", prepare=_with_submodule,
                                              then=dirty_module)
    task = {"id": "P1.1"}
    clean_ctx = {"gitRoot": root_d, "config": {}, "did": []}
    M.carry_work(clean_ctx, task, tree_d, ["docs/audit"])
    _write_lf(os.path.join(tree_d, *(_AR_MODULE.split("/") + ["build.out"])),
              "a build product inside the submodule\n")
    _harness.git(root_d, "update-ref", "-d", "refs/audit/carry/P1.1")
    ctx_d = {"gitRoot": root_d, "config": {}, "did": []}
    M.carry_work(ctx_d, task, tree_d, ["docs/audit"])
    carried = _git_out(root_d, "show", "refs/audit/carry/P1.1:src/f1.txt")
    check("ta7 a dirty submodule the tree checked out does not stop the "
          "filing's carry: the carry ref holds the task's work, and the "
          "did-line says the submodule's own changes were left: %r"
          % ((carried, ctx_d["did"]),),
          carried == "carried\n"
          and any(_AR_MODULE in d and "left" in d for d in ctx_d["did"]))
    check("ta7b OVER-FIRE: a carry over the same submodule with nothing in it "
          "to leave says nothing about it: %r" % (clean_ctx["did"],),
          clean_ctx["did"] and not any(_AR_MODULE in d for d in clean_ctx["did"]))
    # The phase tree holds the task's work, so the submodule is all that
    # can keep the tree.
    _write_lf(os.path.join(root_d, "src", "f1.txt"), "carried\n")
    stop, did, standing = _retired(M, root_d, mpath_d, tree_d)
    check("ta7c ...and retiring that member, its work integrated, keeps its "
          "tree, whose submodule holds what no commit carries: %r"
          % ((stop, did, standing),),
          stop is None and standing
          and os.path.isfile(os.path.join(tree_d, *(_AR_MODULE.split("/")
                                                    + ["build.out"])))
          and any("kept" in d and _AR_MODULE in d for d in did))
    _set_aside_repair_cases(M, check)


def _checked_out(tree):
    """Check the submodule the base holds out in `tree`, at its recorded commit."""
    _harness.git(tree, *(_FILE_PROTOCOL + ("submodule", "update", "--init", "-q")))


def _set_aside_repair_cases(M, check):
    """Between the move of a set-aside tree and git reading it at its new path,
    git's record of the tree names the old path, which `git worktree prune`
    reads as gone - deleting the record's directory, the tree's index, its
    marker and every submodule repository kept there - and which `git worktree
    add -f` takes over. The record is locked from before the move until git
    reads the tree where it went, and a repair that failed is run again on the
    next step."""
    root, mpath, _h, tree, _b, _r, _c, text = _ar_at_decision(
        M, "tarepair", prepare=_with_submodule)
    _checked_out(tree)
    admin = M._worktrees.admin_dir(tree)
    real_git = M.carry_git

    def failing_repair(where, argv, env=None, stdin=None):
        if argv[:2] == ["worktree", "repair"]:
            return 1, b"", "fixture: the repair failed"
        return real_git(where, argv, env=env, stdin=stdin)
    M.carry_git = failing_repair
    try:
        code, said = _next(M, root, mpath, "--answer", "redo")
    finally:
        M.carry_git = real_git
    asides = [p for k, p in (_drive_state(root).get("keptTrees") or {}).items()
              if "set aside" in k]
    aside = asides[0] if len(asides) == 1 else ""
    block = _worktree_block(root, tree)
    code_p, pruned = _git_said(root, "worktree", "prune", "-n", "-v")
    check("ta11 a set-aside whose repair fails leaves git's record of the tree "
          "locked, so a prune names nothing and the record's directory - the "
          "submodule repository under it too - stands; the stop names the "
          "repair: %r" % ((code, aside, block, code_p, pruned, said[-500:]),),
          "redo" in _offers(text) and code != 0 and aside
          and os.path.isdir(aside) and "fixture: the repair failed" in said
          and "git worktree repair %s" % (aside,) in said
          and _is_locked(block) and code_p == 0 and not pruned.strip()
          and os.path.isdir(os.path.join(admin, "modules")))
    code_f, forced = _git_said(root, "worktree", "add", "-f", "--detach", tree)
    check("ta11b ...and a forced add at the task's path is refused over the "
          "locked record, so no second tree shares its git directory: %r"
          % ((code_f, forced),), code_f != 0 and not os.path.lexists(tree))
    _next(M, root, mpath)
    moved = _worktree_block(root, aside) if aside else []
    code_p, pruned = _git_said(root, "worktree", "prune", "-n", "-v")
    mod = os.path.join(aside, *_AR_MODULE.split("/")) if aside else ""
    check("ta11c ...and the next step runs the repair again: git lists the tree "
          "at its new path, unlocked, a prune names nothing, and its submodule "
          "reads there: %r" % ((moved, code_p, pruned),),
          moved and not _is_locked(moved) and code_p == 0 and not pruned.strip()
          and os.path.isdir(os.path.join(admin, "modules"))
          and _git_said(mod, "status", "--porcelain")[0] == 0)

    # The move fails and so does putting the marker back: the stop says the
    # marker still names the set-aside key rather than that all is as it was.
    root_x, mpath_x, tree_x = _retire_fixture("tarestore")
    ctx_x = _drive_ctx(root_x, mpath_x)
    state_x = {"wave": {"trees": {"P1.1": tree_x}, "records": ["docs/audit"]}}
    real_rename, real_record = os.rename, M._worktrees.write_record
    written = []

    def refusing_move(src, dst, *rest, **kw):
        if os.path.realpath(str(src)) == os.path.realpath(tree_x):
            raise OSError(13, "fixture: the tree could not be moved")
        return real_rename(src, dst, *rest, **kw)

    def failing_restore(path, record, run=None):
        written.append(record.get("taskId"))
        if len(written) > 1:
            return "", "fixture: the marker could not be written back"
        return real_record(path, record, run=run)
    M.os.rename, M._worktrees.write_record = refusing_move, failing_restore
    try:
        with _Env(root_x):
            aside_x, stop_x = M.set_aside_tree(ctx_x, state_x, "P1.1")
    finally:
        M.os.rename, M._worktrees.write_record = real_rename, real_record
    told = (stop_x or (0, ""))[1]
    check("ta12 a set-aside whose move and marker restore both fail says the "
          "marker still names the set-aside key: %r" % ((aside_x, told),),
          aside_x is None and "fixture: the tree could not be moved" in told
          and "fixture: the marker could not be written back" in told
          and "P1.1 set aside 1" in told)
    # The lock taken before the move goes with a move that never happened.
    block_x = _worktree_block(root_x, tree_x)
    check("ta12b ...and git's record of the tree, which never moved, is left "
          "unlocked: %r" % (block_x,), block_x and not _is_locked(block_x))

    # A run that dies after the lock and the marker, before the move: the next
    # step finds the tree still at its own path and takes the set-aside back.
    class _Died(Exception):
        pass
    root_k, mpath_k, tree_k = _retire_fixture("tadied")
    ctx_k = _drive_ctx(root_k, mpath_k)
    state_k = {"wave": {"trees": {"P1.1": tree_k}, "records": ["docs/audit"]}}

    def dying_move(src, dst, *rest, **kw):
        raise _Died("fixture: the run dies before the move")
    M.os.rename = dying_move
    try:
        with _Env(root_k):
            M.set_aside_tree(ctx_k, state_k, "P1.1")
    except _Died:
        pass
    finally:
        M.os.rename = real_rename
    died_locked = _is_locked(_worktree_block(root_k, tree_k))
    with _Env(root_k):
        stop_k = M.repair_asides(ctx_k, state_k)
    mine_k = M._worktrees.read_provenance(tree_k, expect_task="P1.1").get("ours")
    check("ta14 a run that died between locking the tree and moving it is taken "
          "back on the next step: the record unlocked, the marker naming the "
          "task, no set-aside recorded: %r" % ((died_locked, stop_k, mine_k,
                                                state_k, ctx_k["did"]),),
          died_locked and stop_k is None and mine_k is True
          and not _is_locked(_worktree_block(root_k, tree_k))
          and not state_k.get("keptTrees") and not state_k.get("asideMoves")
          and any("never moved" in d for d in ctx_k["did"]))

    # A lock someone else put on the record is theirs: the set-aside refuses
    # rather than taking it, and nothing is moved or recorded.
    root_o, mpath_o, tree_o = _retire_fixture("taforeign")
    _harness.git(root_o, "worktree", "lock", "--reason", "a human's lock", tree_o)
    ctx_o = _drive_ctx(root_o, mpath_o)
    state_o = {"wave": {"trees": {"P1.1": tree_o}, "records": ["docs/audit"]}}
    with _Env(root_o):
        aside_o, stop_o = M.set_aside_tree(ctx_o, state_o, "P1.1")
    block_o = _worktree_block(root_o, tree_o)
    check("ta14b a tree whose record someone else locked is not set aside, and "
          "their lock stays: %r" % ((aside_o, stop_o, block_o, state_o),),
          aside_o is None and stop_o and "locked" in stop_o[1]
          and os.path.isdir(tree_o) and "locked a human's lock" in block_o
          and not state_o.get("keptTrees") and not state_o.get("asideMoves")
          and M._worktrees.read_provenance(tree_o, expect_task="P1.1").get("ours"))
    # A move recorded over that record - the run died before its own lock -
    # is taken back without taking their lock off.
    state_o2 = {"keptTrees": {"P1.1 set aside 1": tree_o + ".aside-1"},
                "asideMoves": {"P1.1 set aside 1": {
                    "from": tree_o, "admin": M._worktrees.admin_dir(tree_o),
                    "record": M._worktrees.read_provenance(
                        tree_o, expect_task="P1.1").get("record")}}}
    with _Env(root_o):
        stop_o2 = M.repair_asides(ctx_o, state_o2)
    block_o2 = _worktree_block(root_o, tree_o)
    check("ta14c ...and a set-aside recorded over it, taken back on the next "
          "step, leaves their lock on: %r" % ((stop_o2, block_o2, state_o2),),
          stop_o2 is None and "locked a human's lock" in block_o2
          and not state_o2.get("keptTrees") and not state_o2.get("asideMoves"))

    # What a submodule's config holds is read after the move: bytes no decoder
    # reads, or a path on another drive, are a reason, never a traceback.
    root_e, _mpath_e, tree_e = _retire_fixture("tadecode")
    admin_e = M._worktrees.admin_dir(tree_e)
    aside_e = tree_e + ".aside-1"
    os.rename(tree_e, aside_e)
    bad = os.path.join(admin_e, "modules", "bad")
    os.makedirs(bad)
    with open(os.path.join(bad, "config"), "wb") as fh:
        fh.write(b"[core]\n\tworktree = ../\xff\xfe\n")
    try:
        said_e = M._repair_moved_tree(root_e, tree_e, aside_e, admin_e)
    except Exception as exc:  # the case reports what escaped
        said_e = exc
    check("ta13 a submodule config whose worktree no decoder reads is a reason "
          "the repair names, not an exception: %r" % (said_e,),
          isinstance(said_e, str) and os.path.join(bad, "config") in said_e)

    root_v, _mpath_v, tree_v = _retire_fixture(
        "tadrive", prepare=_with_submodule, then=_checked_out)
    admin_v = M._worktrees.admin_dir(tree_v)
    aside_v = tree_v + ".aside-1"
    os.rename(tree_v, aside_v)
    real_relpath = M.os.path.relpath

    def across_drives(path, start=None):
        raise ValueError("fixture: path is on mount 'D:', start on mount 'C:'")
    M.os.path.relpath = across_drives
    try:
        said_v = M._repair_moved_tree(root_v, tree_v, aside_v, admin_v)
    except Exception as exc:  # the case reports what escaped
        said_v = exc
    finally:
        M.os.path.relpath = real_relpath
    check("ta13b a submodule checkout on another drive than its repository is "
          "a reason the repair names, not an exception: %r" % (said_v,),
          isinstance(said_v, str) and "fixture: path is on mount" in said_v)


def _wave_hooks_cases(check):
    """Before a wave opens the driver asks which hooks Claude Code loads: a copy
    whose hooks lack the task-tree binding runs the phase at width 1 and says
    why; a copy that carries it, or no record at all, leaves the width alone."""
    M, why = _load("drive_phase_wave_hooks")
    if M is None:
        check("wh1 the driver loads", False, why)
        return
    import tempfile
    base = os.path.realpath(tempfile.mkdtemp(prefix="drive-hooks-"))
    try:
        def copy_of(name, binding):
            root = os.path.join(base, name)
            os.makedirs(os.path.join(root, "hooks"))
            for fname, body in (("_config.py", "def task_binding(t, m):\n    pass\n"),
                                ("require-plan.py", "x = task_binding(r, m)\n")):
                with open(os.path.join(root, "hooks", fname), "w", encoding="utf-8") as fh:
                    fh.write(body if binding else "pass\n")
            return root

        def installed(path):
            home = os.path.join(base, "home-%d" % (len(os.listdir(base)),))
            os.makedirs(os.path.join(home, "plugins"))
            with open(os.path.join(home, "plugins", "installed_plugins.json"),
                      "w", encoding="utf-8") as fh:
                json.dump({"plugins": {"audit@quality-gates": [
                    {"scope": "user", "installPath": path, "version": "1.0.0"}]}}, fh)
            _Env.CLAUDE_HOME[0] = home

        installed(copy_of("old", False))
        root, mpath = _wave_repo("wavehooks-old", 2)
        code, text = _next_wave(M, root, mpath)
        check("wh1 hooks without the task-tree binding: the phase runs at width 1 "
              "- one task dispatched, no wave recorded - and the print names the "
              "copy and the width it ran at: %r" % (text,),
              code == 0 and len(_dispatched(text)) == 1
              and not _drive_state(root).get("wave")
              and "task-tree binding" in text and os.path.join(base, "old") in text
              and "width 1" in text)
        installed(copy_of("new", True))
        root, mpath = _wave_repo("wavehooks-new", 2)
        code, text = _next_wave(M, root, mpath)
        check("wh2 THE TWIN: hooks that carry it open the wave as asked, and "
              "print nothing about the binding: %r" % (text,),
              code == 0 and _dispatched(text) == ["P1.1", "P1.2"]
              and "task-tree binding" not in text)
        _Env.CLAUDE_HOME[0] = os.path.join(base, "no-home")
        root, mpath = _wave_repo("wavehooks-none", 2)
        code, text = _next_wave(M, root, mpath)
        check("wh3 no record of a loaded copy: the wave opens as asked and the "
              "print says the binding was not established, with what was looked "
              "for: %r" % (text,),
              code == 0 and _dispatched(text) == ["P1.1", "P1.2"]
              and "task-tree binding not established" in text
              and "installed_plugins.json" in text)
    finally:
        _Env.CLAUDE_HOME[0] = None
        _harness.remove_tree(base)


def _text_cases(check):
    """The texts a user meets name nothing a plugin install does not ship."""
    M, why = _load("drive_phase_text")
    if M is None:
        check("tx1 the driver loads", False, why)
        return
    echo = " ".join((M.STEPS.get("ado-echo") or {}).get("rule") or ())
    check("tx1 the ADO echo's rule states its hard rules itself - update only, "
          "never create, never ask - and sends the model to no reference "
          "file: %r" % (echo,),
          "reference/" not in echo and "never create" in echo
          and "never ask" in echo)
    basis = getattr(M, "FIX_TASK_PRICE_BASIS", "")
    check("tx2 the fix-task price names its basis as a benchmark prediction, not "
          "a section of a design document the install does not ship: %r"
          % (basis,),
          "benchmark" in basis and "design" not in basis)


def _submit_unchanged(root, mpath, task_id, over=None):
    """Play an executor that was blocked: it files its return and changes
    nothing in the tree."""
    return _verb(root, DRIVER, ["submit", task_id, "--role", "executor", mpath,
                                "--project-dir", root],
                 stdin=json.dumps(_executor_body(task_id, over)))


TESTS_ADD_FILE = "tests/test_f1.py"


def _with_tests_add(plan):
    """P1.1 owes the test file `tests.add` names, as a regression task."""
    task = plan["phases"][0]["tasks"][0]
    task["files"] = ["src/f1.txt", TESTS_ADD_FILE]
    task["tests"] = {"mode": "regression", "add": [
        "%s: the f1 case" % (TESTS_ADD_FILE,)], "gate": ["true"],
        "expectRedFirst": False}
    plan["fileIndex"][TESTS_ADD_FILE] = ["P1.1"]


def _close_evidence_cases(check):
    """A green gate over an unchanged tree proves only that nothing broke: the
    close refuses a return that attempted nothing over an empty change, and a
    `tests.add` file that was never written; real work with its tests present
    closes."""
    M, why = _load("drive_phase_close_evidence")
    if M is None:
        check("ce1 the driver loads", False, why)
        return
    blocked = {"outcome": {"technical": "blocked: the guard refused the edit",
                           "descriptive": "nothing was changed"}}
    root, mpath = _repo("ce-empty", task_ids=TASKS[:1], per_task="phase")
    _next(M, root, mpath)
    _submit_unchanged(root, mpath, "P1.1", blocked)
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("ce1 a return filed `not-attempted` over an empty change is refused at "
          "the close - the task stays in progress, nothing is printed closed, "
          "and the refusal names the evidence and offers restart or cancel: %r"
          % ((code, task.get("status"), text[:600]),),
          code != 0 and task.get("status") == "in_progress"
          and not task.get("commit") and M.CLOSED not in text
          and "not-attempted" in text and "cancel" in text)

    root, mpath = _repo("ce-absent", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, _with_tests_add, "fixture: tests.add")
    _next(M, root, mpath)
    _file_executor(root, mpath, "P1.1",
                   {"testsAdded": ["%s: the f1 case" % (TESTS_ADD_FILE,)]})
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("ce2 a `tests.add` file absent at the close refuses it by name, with "
          "the source change made and the gate green: %r"
          % ((code, task.get("status"), text[:600]),),
          code != 0 and task.get("status") == "in_progress"
          and not task.get("commit") and TESTS_ADD_FILE in text
          and M.CLOSED not in text)

    root, mpath = _repo("ce-present", task_ids=TASKS[:1], per_task="phase")
    _commit_plan(root, mpath, _with_tests_add, "fixture: tests.add")
    _next(M, root, mpath)
    os.makedirs(os.path.join(root, "tests"))
    with open(os.path.join(root, "tests", "test_f1.py"), "w", encoding="utf-8") as fh:
        fh.write("assert True\n")
    _file_executor(root, mpath, "P1.1",
                   {"testsAdded": ["%s: the f1 case" % (TESTS_ADD_FILE,)]})
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("ce3 ALLOW: a real change with its `tests.add` file present closes - "
          "and a `not-attempted` red-first beside a real change is no refusal: %r"
          % ((code, task.get("status"), text[:400]),),
          task.get("status") == "done" and task.get("commit")
          and "%s P1.1" % (M.CLOSED,) in text)

    # The binding is the executor's `casesAdded`, read by id; the drive files
    # its own reading beside the claim, so the reviewer's brief prints a gap the
    # drive saw rather than one it recomputes blind to the suite's output.
    entry = "%s: the f1 case" % (TESTS_ADD_FILE,)
    filed_gaps = {}
    for tag, over in (("unbound", {"testsAdded": ["f1 a title nobody matches"]}),
                      ("bound", {"testsAdded": ["whatever words"],
                                 "casesAdded": ["f11"]})):
        root, mpath = _repo("ce-bind-%s" % (tag,), task_ids=TASKS[:1],
                            per_task="phase")
        _commit_plan(root, mpath, _with_tests_add, "fixture: tests.add")
        _next(M, root, mpath)
        code, text = _file_executor(root, mpath, "P1.1", over)
        path = _filed_path(mpath, "P1.1")
        with open(path, "r", encoding="utf-8") as fh:
            filed = json.load(fh)
        filed_gaps[tag] = (code, filed.get(_fr.GAPS_FIELD), text)
    check("ce6 a return with no `casesAdded` is filed with the entry named in "
          "`testsAddGaps` and the filing says so, however its titles read; one "
          "binding the entry to an id is filed with no gap, and says the id was "
          "not checked because no test command ran: %r"
          % ({k: (v[0], v[1], v[2][-300:]) for k, v in filed_gaps.items()},),
          filed_gaps["unbound"][0] == 0 and filed_gaps["bound"][0] == 0
          and len(filed_gaps["unbound"][1]) == 1
          and filed_gaps["unbound"][1][0].startswith(entry)
          and "not bound to a printed case" in filed_gaps["unbound"][2]
          and filed_gaps["bound"][1] == []
          and "not bound to a printed case" not in filed_gaps["bound"][2]
          and "not checked" in filed_gaps["bound"][2])

    root, mpath = _repo("ce-tracked", task_ids=TASKS[:1], per_task="phase")
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("v0\n")
    _harness.git(root, "add", "notes.txt")
    _harness.git(root, "commit", "-qm", "fixture: notes")
    _next(M, root, mpath)
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("an allowlist the gate needed\n")
    _file_executor(root, mpath, "P1.1")
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("ce4 a TRACKED file outside the task's files, clean at the start and "
          "modified during the attempt, refuses the close by name and offers "
          "the scope widening - the drive never prints it closed: %r"
          % ((code, task.get("status"), text[:600]),),
          code != 0 and task.get("status") == "in_progress"
          and "notes.txt" in text and "/audit:task scope" in text
          and M.CLOSED not in text)

    root, mpath = _repo("ce-older", task_ids=TASKS[:1], per_task="phase")
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("v0\n")
    _harness.git(root, "add", "notes.txt")
    _harness.git(root, "commit", "-qm", "fixture: notes")
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("dirty before the start\n")
    _next(M, root, mpath)
    _file_executor(root, mpath, "P1.1")
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("ce5 ALLOW: the same tracked file already dirty before `start` is not "
          "this task's, and the close goes through without it: %r"
          % ((code, task.get("status"), text[:400]),),
          task.get("status") == "done" and task.get("commit")
          and "notes.txt" not in _git_out(root, "show", "--name-only",
                                          "--format=", task["commit"]))


def _brief_scope_cases(check):
    """A brief printed and then made stale by a scope widening was never the
    current scope's dispatch: the next `next` issues it again, spending no
    attempt, rather than grading an executor that never received it."""
    M, why = _load("drive_phase_brief_scope")
    if M is None:
        check("bs1 the driver loads", False, why)
        return
    root, mpath = _repo("brief-scope", task_ids=TASKS[:1])
    _code, first = _next(M, root, mpath)
    before = _attempts(mpath, "P1.1")
    with _Env(root):
        scode, sout = _verb(root, "audit-task.py", [
            "scope", "P1.1", mpath, "--project-dir", root,
            "--files", "src/f1.txt,src/extra.txt"])
    code, again = _next(M, root, mpath)
    brief = _BRIEF.search(again)
    held = ""
    if brief:
        with open(os.path.join(root, *brief.group(1).split("/")), encoding="utf-8") as fh:
            held = fh.read()
    check("bs1 after `scope` widens a task whose brief was printed and no return "
          "filed, `next` issues the brief again over the widened scope - not "
          "`decide no-executor-return` - and spends no attempt: %r"
          % ((instruction(first), scode, sout[-300:], code, again,
              before, _attempts(mpath, "P1.1")),),
          instruction(first) == ("dispatch", "executor", "P1.1")
          and scode == 0 and code == 0
          and instruction(again) == ("dispatch", "executor", "P1.1")
          and "src/extra.txt" in held
          and _attempts(mpath, "P1.1") == before)
    _code, third = _next(M, root, mpath)
    check("bs2 THE TWIN: with the scope unchanged since the brief was issued, "
          "an unfiled executor is still the no-executor-return decision: %r"
          % (third,), instruction(third)[1] == "no-executor-return")


def _scope_change_cases(check):
    """A scope widened after the executor filed is a decision naming both lists,
    never a close; with the scope as filed the close goes on."""
    M, why = _load("drive_phase_scope_change")
    if M is None:
        check("sc1 the driver loads", False, why)
        return
    root, mpath = _repo("scope-change", task_ids=TASKS[:1], per_task="phase")
    _next(M, root, mpath)
    _file_executor(root, mpath, "P1.1")
    with _Env(root):
        scode, sout = _verb(root, "audit-task.py", [
            "scope", "P1.1", mpath, "--project-dir", root,
            "--files", "src/f1.txt,src/f2.txt"])
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("sc1 an executor files, the task's files are then widened by scope, and "
          "the next drive step prints a decision (dispatch again under the new "
          "scope, or close with a recorded reason), never a close: %r"
          % ((scode, sout[-200:], code, task.get("status"), text[:500]),),
          scode == 0 and instruction(text)[1] == "scope-changed"
          and task.get("status") == "in_progress" and M.CLOSED not in text
          and "src/f2.txt" in text and "added" in text and "dropped" in text)
    code, again = _next(M, root, mpath)
    check("sc1b the decision is held, not re-derived into a close, until it is "
          "answered: %r" % (again[:300],),
          instruction(again)[1] == "scope-changed"
          and tasks_of(mpath).get("P1.1", {}).get("status") == "in_progress")
    code, closed = _next(M, root, mpath, "--answer", "close", "--reason",
                         "the widened file is context only")
    task = tasks_of(mpath).get("P1.1", {})
    check("sc2 `close` with a reason goes on to the close under the widened scope: "
          "%r" % ((code, task.get("status"), closed[:400]),),
          task.get("status") == "done" and "%s P1.1" % (M.CLOSED,) in closed)

    root, mpath = _repo("scope-same", task_ids=TASKS[:1], per_task="phase")
    _next(M, root, mpath)
    _file_executor(root, mpath, "P1.1")
    code, text = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    check("sc3 with no scope change after the filing the close proceeds as today: "
          "%r" % ((code, task.get("status"), text[:400]),),
          task.get("status") == "done" and "%s P1.1" % (M.CLOSED,) in text
          and "scope-changed" not in text)

    state = _scope_retry_run(M, "scope-retry", 0)
    check("sc4 a retry whose new start falls in the same second as the start it "
          "replaces dispatches the executor again and does not read the "
          "previous start's return, marks or brief: %r" % (state["detail"],),
          _scope_retry_ok(state))
    # The first start is held 1.2 seconds before it runs, as a loaded
    # runner holds it: the pinned second has to reach the stamp, not the real
    # clock's guess at it, or the retry's start is no longer in the same second.
    # The case is there for a pin that reaches nothing: it passes on the real
    # clock whenever the run is quick and fails when the first call is slow.
    slow = _scope_retry_run(M, "scope-retry-slow", 1.2)
    check("sc4b sc4 holds its same-second precondition when the first in-process "
          "drive call takes longer than a second: %r" % (slow["detail"],),
          _scope_retry_ok(slow)
          and slow["restarted"] == time.strftime(
              "%Y-%m-%dT%H:%M:%SZ", time.gmtime(slow["pin"] + 1)))


def _scope_retry_run(M, prefix, delay):
    """One scope-changed retry, both starts under one pinned second, the first
    drive call held `delay` seconds after the pin is read. Both starts run under
    the pin, which is what a fast runner does by accident: left to the real
    clock the retry usually lands a second later and a case about the retry's
    identity passes whatever the start's identity is."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    pin = int(time.time())
    time.sleep(delay)
    with _pinned_clock(pin):
        _code, first = _next(M, root, mpath)
    started = tasks_of(mpath).get("P1.1", {}).get("startedAt")
    _file_executor(root, mpath, "P1.1")
    old_return = _filed_path(mpath, "P1.1")
    with _Env(root):
        _verb(root, "audit-task.py", ["scope", "P1.1", mpath, "--project-dir",
                                      root, "--files", "src/f1.txt,src/f2.txt"])
    _next(M, root, mpath)
    before = _attempts(mpath, "P1.1")
    with _pinned_clock(pin):
        code, again = _next(M, root, mpath, "--answer", "retry")
    restarted = tasks_of(mpath).get("P1.1", {}).get("startedAt")
    new_return = _filed_path(mpath, "P1.1")
    briefs = [_BRIEF.search(text) for text in (first, again)]
    briefs = [b.group(1) if b else None for b in briefs]
    return {
        "pin": pin, "started": started, "restarted": restarted, "code": code,
        "again": again, "before": before, "after": _attempts(mpath, "P1.1"),
        "old_return": old_return, "new_return": new_return, "briefs": briefs,
        "detail": (code, started, restarted, before, _attempts(mpath, "P1.1"),
                   old_return, new_return, briefs, again[:300])}


def _scope_retry_ok(state):
    """`_scope_retry_run`'s verdict: the first start took the pinned second and
    the retry re-dispatched under a start of its own."""
    started, restarted = state["started"], state["restarted"]
    old_return, new_return = state["old_return"], state["new_return"]
    briefs = state["briefs"]
    return (started == time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime(state["pin"]))
            and instruction(state["again"]) == ("dispatch", "executor", "P1.1")
            and state["after"] == state["before"] + 1
            and _fr.return_start_key(restarted) != _fr.return_start_key(started)
            and old_return is not None and os.path.isfile(old_return)
            and new_return is not None and new_return != old_return
            and not os.path.exists(new_return)
            and None not in briefs and briefs[0] != briefs[1])


# --- the signal: one line per step, the full text behind --explain ----------
# Spelled here rather than read off the driver, so a verb added to or dropped
# from the driver's table is a red case and not a table agreeing with itself.
SIGNAL_VERB_WORDS = ("dispatch", "wait", "ask", "judge", "review", "done", "stop")
SIGNAL_BYTES = 200
EXPLAIN_BYTES = 2048
_SIGNAL = re.compile(r"^audit (\S+) (%s) (\S+)(?: (.*?))? \| (.*) \| next: (\S.*)$"
                     % ("|".join(SIGNAL_VERB_WORDS),))
# The lines a step prints beside another rather than alone: each folds into the
# signal of the step it follows, so the corpus never prints one by itself.
_FOLDED_STEPS = ("ado-echo", "done-chain-next", "handback-filed",
                 "handback-refused")


def _signal_ok(line):
    """None when `line` is one signal inside the bound, else what is wrong."""
    if "\n" in line:
        return "more than one line"
    if len(line.encode("utf-8")) > SIGNAL_BYTES:
        return "%d bytes" % (len(line.encode("utf-8")),)
    return None if _SIGNAL.match(line) else "not the signal's shape"


def _corpus_ctx(mpath):
    """A context whose did-line carries several clauses, the shape a `next`
    that closes one task and starts the next prints - long enough, with ids
    past the line's bound, that a line cut by bytes cuts an id."""
    return {"phase": "P125", "only": None, "manifest": mpath,
            "project": os.path.dirname(mpath), "verbose": False,
            "log": [], "did": ["closed P125.54-0h5 at 4cd8900",
                               "started P125.55-0h5", "gate P125.55-0h5 green",
                               "stamp current",
                               "fix task P125.60-0h5 added for P125-R1",
                               "closed P125.55-0h5 at ef37f58",
                               "started P125.56-0h5", "closed P125.56-0h5 at 21d7ea5",
                               "started P125.57-0h5"]}


# The did-line of the `next` that signs a phase off: the gate, the sign-off, the
# commit, the landing and the release - the events after the task cycle that
# `did_events` reads, which the task-cycle context above never carries.
_SIGNOFF_DID = ["phase gate green", "invariants clean", "signed off",
                "record committed at 9a8b7c6",
                "landed (" + "merged into main at 9a8b7c6 " * 4 + ")",
                "lock released"]
# What `did_events` must read back off a corpus line, by which did-line it was
# drawn from: the ids are the context's own, written out rather than parsed, so
# the expectation shares no code with the line under test.
_CYCLE_EVENTS = {"started": ["P125.55-0h5", "P125.56-0h5", "P125.57-0h5"],
                 "closed": ["P125.54-0h5", "P125.55-0h5", "P125.56-0h5"],
                 "added": ["P125.60-0h5"], "signedOff": False, "landed": False,
                 "released": False}
_SIGNOFF_EVENTS = {"started": [], "closed": [], "added": [], "signedOff": True,
                   "landed": True, "released": True}


def _corpus_findings(count, severity="med"):
    return [{"id": "P125-R%d" % (n,), "severity": severity,
             "file": "plugins/audit/scripts/governance/drive-phase.py",
             "issue": "the step prints a rule that sits past its bound " * 4}
            for n in range(count)]


def _signal_corpus(M, mpath):
    """`[(step, said, ctx_extra)]` - every decision the drive can wait on, and
    every other step it prints, built through the driver's own constructors
    with text long enough that an unbounded line overflows: a why past the
    bound, a triage of many findings with answers waiting, a wave of many
    members and a recipe longer than the line."""
    why = "the recorded gate went red on " + "a very long step name " * 12
    ctx = _corpus_ctx(mpath)
    out = []
    for name in sorted(M.DECISIONS):
        phase_level = name in M.PHASE_DECISIONS
        pending = {"decision": name, "why": why,
                   "task": None if phase_level else "P125.55-0h5",
                   "start": None if phase_level else "20261014T182420Z"}
        if name in ("triage", "round-cap"):
            pending.update(findings=_corpus_findings(9) + _corpus_findings(3, "low"),
                           answers=[{"who": "P125.3", "what": "diverges",
                                     "note": "a note " * 30}],
                           fixesAfter=["P125.60-0h5", "P125.61-0h5"],
                           head="ef37f58e", cost=["  rounds cost " + "x" * 200])
        out.append(("decide-%s" % (name,), M.render_decision(ctx, pending), {}))
    clean = {"decision": "triage", "why": "clean review", "findings": [],
             "answers": [], "fixesAfter": [], "head": "ef37f58e"}
    out.append(("decide-triage", M.render_decision(ctx, clean), {}))
    brief = ".claude/state/briefs/P125.55-0h5/20261014T182420Z.executor.md"
    for role, agent in (("executor", M.EXECUTOR_AGENT), ("reviewer", M.REVIEWER_AGENT)):
        out.append(("dispatch-%s" % (role,), M.dispatch_said(
            ctx, role, "P125.55-0h5", agent, "opus", brief), {}))
    out.append(("dispatch-phase-review", M.dispatch_said(
        ctx, "phase", "P125", M.REVIEWER_AGENT, "opus", brief), {}))
    members = [M.dispatch_said(ctx, "executor", "P125.%d-0h5" % (n,),
                               M.EXECUTOR_AGENT, "sonnet", brief)
               for n in range(40, 52)]
    out.append(("dispatch-wave", M.wave_said(ctx, members), {}))
    out.append(("follow-browser", M.follow_said(
        ctx, "P125.55-0h5", ["node tools/capture-screenshots.mjs --update " + "a" * 150],
        "../trees/P125.55-0h5"), {}))
    out.append(("resume-executor", M.resume_said(ctx, "P125.55-0h5"), {}))
    session_argv = ["python3", "/a/long/plugin/path/" * 8 + "run-agent-session.py",
                    "--role", "writer", "--task", "P125.55-0h5"]
    out.append(("dispatch-writer", M.writer_said(
        ctx, "P125.55-0h5", "claude-sonnet-4-5-20250929", brief, session_argv), {}))
    out.append(("resume-writer", M.writer_said(
        ctx, "P125.55-0h5", "claude-sonnet-4-5-20250929", brief, session_argv,
        resume=WRITER_SESSION, round_n=2), {}))
    out.append(("wait-writer", M.wait_said(
        ctx, "P125.55-0h5", ".claude/state/sessions/drive/P125.55-0h5."
        "20261014T182420Z.12.jsonl", session_argv), {}))
    out.append(("dispatch-reviewer-session", M.writer_said(
        ctx, "P125.55-0h5", "claude-sonnet-4-5-20250929", brief,
        session_argv[:2] + ["--role", "reviewer", "--task", "P125.55-0h5"],
        role="reviewer"), {}))
    out.append(("wait-reviewer-session", M.wait_said(
        ctx, "P125.55-0h5", ".claude/state/sessions/drive/P125.55-0h5."
        "20261014T182420Z.reviewer.1.jsonl", session_argv,
        "wait-reviewer-session"), {}))
    out.append(("dispatch-validation", M.validation_said(
        ctx, "P125", "claude-sonnet-4-5-20250929",
        ["P125-R%d" % (n,) for n in range(1, 30)],
        ".claude/state/sessions/scratch/P125/validate-ef37f58e1234.0.prompt",
        session_argv[:2] + ["--role", "reviewer", "--task", "P125"]), {}))
    out.append(("wait-validation", M.wait_said(
        ctx, "P125", ".claude/state/sessions/drive/P125.validateef37f58e."
        "reviewer.0.jsonl", session_argv, "wait-validation"), {}))
    out.append(("done", M.done_said(ctx, "landed (" + "merged into main " * 10 + ")",
                                    "P126"), {"did": _SIGNOFF_DID}))
    out.append(("done", M.done_said(ctx, "landed", None), {"did": _SIGNOFF_DID}))
    out.append(("done-task", M.done_task_said(ctx, "P125.55-0h5", "done at 4cd8900"), {}))
    out.append(("decide-stalled", M.stalled_said(
        ctx, [{"id": "P125.%d" % (n,), "status": "blocked", "attempts": 3,
               "maxAttempts": 3} for n in range(5)], why), {}))
    stop = ("[drive-phase] P125: stopped - audit-lock.py refused (exit 3); its own "
            "words follow\n" + "[audit-lock] held by a live run " * 20)
    for kind in ("stopped", "stop-lock", "stop-index-lock", "stop-blocked"):
        out.append((kind, stop, {"stop": kind}))
    return out


def _signal_cases(check):
    """The signal: one line per step, inside its bound, with a verb from the
    seven; a table that maps every step to one of them; and the dispatch
    prompts, which differ only by the id they end in."""
    M, why = _load("signal_mod")
    check("sn0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    scratch = _harness.fixture_root("drive-signal-corpus-")
    try:
        mpath = os.path.join(scratch, "plan.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(_plan(TASKS[:1], ("true",)), fh)
        try:
            corpus = _signal_corpus(M, mpath)
            lines = [(step, M.signal(dict(_corpus_ctx(mpath), **extra),
                                     0 if isinstance(said, dict) else 1,
                                     said)["line"])
                     for step, said, extra in corpus]
        except Exception as exc:                               # noqa: BLE001
            corpus, lines = [], [("raised", "%s: %s" % (type(exc).__name__, exc))]
    finally:
        _harness.remove_tree(scratch)
    bad = [(step, _signal_ok(line), line) for step, line in lines if _signal_ok(line)]
    table = getattr(M, "SIGNAL_VERBS", {})
    reached = set(step for step, _said, _extra in corpus)
    unreached = sorted(set(M.STEPS) - set(_FOLDED_STEPS) - reached)
    check("sn1 every line next --signal prints over the recorded decision corpus "
          "is at most 200 bytes and uses one of the seven verbs: %r"
          % ((bad[:3], unreached),),
          lines and not bad and not unreached
          and tuple(getattr(M, "VERBS", ())) == SIGNAL_VERB_WORDS
          and set(table) == set(M.STEPS)
          and set(table.values()) <= set(SIGNAL_VERB_WORDS)
          and M.signal_verb_gaps() == [])
    # Every line, not most: stream-cost bounds a session's close, fix-task and
    # sign-off spans by these events, so one dropped from any line moves a span.
    read_back = [(step, line, M.did_events(line),
                  _SIGNOFF_EVENTS if extra.get("did") is _SIGNOFF_DID
                  else _CYCLE_EVENTS)
                 for (step, _said, extra), (_s, line) in zip(corpus, lines)]
    lost = [(step, line, got) for step, line, got, want in read_back
            if got != want]
    check("tests/test_drive_phase.py: every event stream-cost reads "
          "survives on the signal line, at the longest task ids the corpus holds "
          "(sn8: each of %d line(s) reads back every start, close, fix task, "
          "sign-off, landing and release its did-line holds; lost on %r)"
          % (len(read_back), lost[:2]),
          len(read_back) == len(corpus) > 0 and not lost
          and any(want is _SIGNOFF_EVENTS for _s, _l, _g, want in read_back))
    # Past what any one line holds: the events still print whole, so the line
    # runs over its bound rather than dropping one - and a task id of another
    # phase in the same word is spelled in full, not expanded into this one's.
    many = ["P125.%d-0h5" % (n,) for n in range(40, 60)] + ["P7.1"]
    wide = M.signal_line(dict(_corpus_ctx(mpath), did=[]), "dispatch", "P125",
                         ["%s %s" % (w, t) for t in many for w in ("closed", "started")]
                         + ["gate P125.40-0h5 green"], "wave", "wait")
    back = M.did_events(wide)
    check("sn8b a signal whose read events alone are past the bound carries every "
          "one of them, past the bound: %r" % ((len(wide.encode("utf-8")), back),),
          back["closed"] == many and back["started"] == many
          and len(wide.encode("utf-8")) > SIGNAL_BYTES)
    # THE RED TWIN of the table half: a step added with no verb is named.
    mutant, _why = _load("signal_mod_gap")
    if mutant is not None:
        mutant.STEPS = dict(mutant.STEPS, **{"decide-new-thing": {
            "line": "decide new-thing %(task)s", "rule": ()}})
        gaps = mutant.signal_verb_gaps()
    else:
        gaps = None
    check("sn1m RED TWIN: a step the table gives no verb is named by "
          "signal_verb_gaps, so a step that prints no signal cannot ship: %r"
          % (gaps,), gaps == ["decide-new-thing: no verb"])
    where = {"manifest": os.path.join("proj", "plan.json"), "project": "proj"}
    first = M.dispatch_prompt(where, "executor", "P125.55-0h5")
    second = M.dispatch_prompt(where, "executor", "P3.1")
    check("sn2u the dispatch prompt is one fixed sentence and the id, last, naming "
          "the manifest and the project absolutely: %r" % ((first, second),),
          first.endswith(" P125.55-0h5") and second.endswith(" P3.1")
          and first[:-len("P125.55-0h5")] == second[:-len("P3.1")]
          and "\n" not in first
          and '--manifest "%s"' % (os.path.abspath(where["manifest"]),) in first
          and '--project-dir "%s"' % (os.path.abspath("proj"),) in first)
    with open(os.path.join(_output.PLUGIN_ROOT, "commands", "phase.md"), "r",
              encoding="utf-8") as fh:
        phase_md = fh.read()
    template = M.DISPATCH_PROMPT % {"script": "S/governance/drive-phase.py",
                                    "manifest": "<manifest>",
                                    "project": "<project>", "role": "<role>"}
    said = template.replace('python3 "S/', 'S/')
    missing = [w for w in SIGNAL_VERB_WORDS if "`%s`" % (w,) not in phase_md]
    check("sn4 commands/phase.md states the dispatch prompt in the driver's own "
          "words and names each verb the signal uses: %r" % ((said, missing),),
          said in phase_md and not missing and "--signal" in phase_md)
    # THE SESSION'S BUDGET IS ITS OWN. An orchestrator running under its own
    # --max-budget-usd read the writer's run line, saw a --budget-usd larger than
    # what it had left, and stopped to ask whether the child's spend was its own.
    # The child is a separate process; one sentence, from one constant, says so.
    rule = getattr(M, "SESSION_BUDGET_RULE", None)
    argv = ["python3", "run-agent-session.py", "--role", "writer", "--task", "P1.1"]
    said = [("dispatch-writer", M.writer_said(None, "P1.1", "claude-x", "p", argv)),
            ("resume-writer", M.writer_said(None, "P1.1", "claude-x", "p", argv,
                                            resume=WRITER_SESSION, round_n=1)),
            ("dispatch-reviewer-session", M.writer_said(
                None, "P1.1", "claude-x", "p", argv, role="reviewer")),
            ("dispatch-validation", M.validation_said(
                None, "P1", "claude-x", ["P1-R1"], "p", argv))]
    held = [(step, got["lines"].count(rule)) for step, got in said]
    agent = M.step_text("dispatch-executor", agent=M.EXECUTOR_AGENT, task="P1.1",
                        model="opus", brief="b")
    check("sn4s every session dispatch the drive prints - writer, resume, per-task "
          "reviewer, phase validation - carries the budget sentence once, read "
          "from SESSION_BUDGET_RULE and naming executor.writerBudgetUsd and "
          "--budget-usd, while an Agent dispatch, which has no process of its "
          "own, carries none: %r" % ((rule, held, agent),),
          isinstance(rule, str) and "executor.writerBudgetUsd" in rule
          and "--budget-usd" in rule and len(held) == 4
          and all(n == 1 for _step, n in held) and rule not in "\n".join(agent))
    shown = os.path.join(_output.PLUGIN_ROOT, "commands")
    docs = {}
    for name in sorted(os.listdir(shown)):
        if name.endswith(".md"):
            with open(os.path.join(shown, name), "r", encoding="utf-8") as fh:
                docs[name] = " ".join(fh.read().split())
    # The marker is the phrase every doc shares, the `run:` line under
    # `--explain`; the longer "a writer's `dispatch` is a" form is only the four
    # prose docs' spelling, and phase.md's numbered step words it otherwise.
    describing = sorted(n for n, text in docs.items()
                        if "`run:` line under `--explain`" in text)
    # A constant that is not there yet is a failing case, never a raise: its
    # count is -1 in every doc, which no doc can hold.
    lacking = [(n, docs[n].count(rule) if isinstance(rule, str) else -1)
               for n in describing
               if not isinstance(rule, str) or docs[n].count(rule) != 1]
    check("sn4d every command doc that tells the orchestrator a writer's dispatch is "
          "a run: line carries SESSION_BUDGET_RULE's text once - run.md and "
          "next.md among them - so a reword of the constant cannot leave one "
          "stale: %r" % ((describing, lacking),),
          isinstance(rule, str) and "run.md" in describing and "next.md" in describing
          and "phase.md" in describing and not lacking)
    # A WAVE PRINTS ITS MEMBERS' FIRST LINES ONLY, so a writer member's rule lines
    # were dropped and the one print an orchestrator reads before launching
    # several sessions said nothing about whose money they spend. Once, whatever
    # the number of session members; none when no member is a session.
    where = {"manifest": os.path.join("proj", "plan.json"), "project": "proj"}
    sessions = [M.writer_said(where, "P1.%d" % (n,), "claude-x", "p", argv)
                for n in (1, 2)]
    sessions.append(M.writer_said(where, "P1.3", "claude-x", "p", argv,
                                  role="reviewer"))
    agents = [M.dispatch_said(where, "executor", "P1.%d" % (n,), M.EXECUTOR_AGENT,
                              "opus", "b") for n in (4, 5)]
    waves = [("sessions", M.wave_said(where, sessions)),
             ("mixed", M.wave_said(where, sessions[:1] + agents)),
             ("agents", M.wave_said(where, agents))]
    counted = [(name, w["lines"].count(rule)) for name, w in waves]
    check("sn4w a wave dispatch carries SESSION_BUDGET_RULE once however many of "
          "its members are sessions, and none when every member is an Agent, "
          "which has no process of its own: %r" % (counted,),
          isinstance(rule, str)
          and counted == [("sessions", 1), ("mixed", 1), ("agents", 0)])
    # THE BUDGET A REVIEWER OR VALIDATION SESSION RUNS UNDER is the writer's:
    # `reviewer_session_setting` swaps the model and keeps the rest, so the
    # sentence's "set by executor.writerBudgetUsd" is true of them as worded.
    # A setting that dropped or replaced the budget would make it false.
    def _budgets(mod):
        session = mod.writer_setting({"executor": {
            "writerModel": "claude-opus-4-1", "writerBudgetUsd": 7.5}})[0]
        return [mod.reviewer_session_setting(phase, session).get("budget")
                for phase in ({"review": {"model": "claude-sonnet-4-5"}},
                              {"review": {"model": "sonnet"}}, {})]
    mutant, _why = _load("budget_mod_gap")
    if mutant is not None:
        mutant.reviewer_session_setting = lambda phase, session: {
            "model": session["model"]}
    check("sn4r a reviewer or validation session's --budget-usd is the writer "
          "setting's, for a full-id review model, an alias and none, and a "
          "reviewer_session_setting that dropped it is seen: %r"
          % ((_budgets(M), mutant is not None and _budgets(mutant)),),
          _budgets(M) == ["7.5"] * 3
          and mutant is not None and _budgets(mutant) == [None] * 3)


def _explain_cases(check):
    """--explain prints the text a signal stands for: the pending decision in
    full, bounded, with every option it takes, read without the lock."""
    M, why = _load("explain_mod")
    check("sn3a the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    root, mpath = _repo("explain", task_ids=TASKS[:2])
    try:
        with open(mpath, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        plan["phases"][0]["tasks"][0].update(status="in_progress",
                                             startedAt="2026-01-01T00:00:00Z")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        spath = _fr.drive_state_path(os.path.join(root, ".claude", "state"), PHASE)
        os.makedirs(os.path.dirname(spath), exist_ok=True)
        lows = [dict(f, id="P1-L%d" % (n,), severity="low")
                for n, f in enumerate(_corpus_findings(6))]
        cases = []
        for name, (options, _needs) in sorted(M.DECISIONS.items()):
            if not options:
                continue
            phase_level = name in M.PHASE_DECISIONS
            subject = PHASE if phase_level else ("P1.2" if name == "scope-gap"
                                                 else "P1.1")
            pending = {"decision": name, "why": "w " * 200,
                       "task": None if phase_level else subject,
                       "start": None if phase_level else "20260101T000000Z"}
            offered = set(options)
            if name in ("triage", "round-cap"):
                pending.update(findings=_corpus_findings(30) + lows, answers=[],
                               fixesAfter=["P1.2"], head="abc1234",
                               cost=["  rounds cost " + "y" * 150])
            if name == "triage":
                offered -= {"accept", "decline"}
            cases.append((name, subject, pending, offered))
        cases.append(("triage+answers", PHASE, {
            "decision": "triage", "why": "w", "task": None, "start": None,
            "findings": _corpus_findings(30) + lows, "fixesAfter": ["P1.2"],
            "head": "abc1234", "answers": [{"who": "P1.1", "what": "diverges",
                                            "note": "n " * 40}]},
            {"carry", "fix", "re-review", "accept", "decline"}))
        results = []
        for name, subject, pending, offered in cases:
            with open(spath, "w", encoding="utf-8") as fh:
                json.dump({"pending": pending}, fh)
            with open(spath, "rb") as fh:
                before = fh.read()
            said = []
            with _Env(root):
                code = M.main(["next", PHASE, mpath, "--project-dir", root,
                               "--explain", subject], out=said.append)
            text = "\n".join(said)
            answers = " ".join(ln for ln in text.splitlines()
                               if ln.startswith("answer:"))
            with open(spath, "rb") as fh:
                after = fh.read()
            results.append((name, code, len(text.encode("utf-8")),
                            sorted(o for o in offered if o not in answers),
                            before == after))
        bad = [r for r in results if r[1] != 0 or r[2] > EXPLAIN_BYTES or r[3]
               or not r[4]]
        check("sn3 --explain for a pending decision prints at most 2048 bytes "
              "and names the options the decision takes: %r" % (bad or results,),
              len(results) == len(cases) and not bad
              and any(r[0] == "triage" for r in results))
        stray = []
        with _Env(root):
            code = M.main(["next", PHASE, mpath, "--project-dir", root,
                           "--explain", "P1.9"], out=stray.append)
        check("sn3b THE MISS: --explain for an id nothing waits on and no signal "
              "named says so, exit 2, rather than printing another step's text: %r"
              % (stray,), code == 2 and "P1.9" in "\n".join(stray))
    finally:
        _harness.remove_tree(root)


def _brief_difference(role, wrote, shown):
    """None when the brief read back is the brief written, else `(role, offset,
    written side, shown side)`: the first offset at which they differ and the
    repr of about forty characters of each around it. A bare False said only
    that some brief differed, which on a leg nobody runs locally is no lead."""
    if wrote == shown:
        return None
    at = next((i for i, (a, b) in enumerate(zip(wrote, shown)) if a != b),
              min(len(wrote), len(shown)))
    lo = max(0, at - 20)
    return (role, at, repr(wrote[lo:at + 20]), repr(shown[lo:at + 20]))


def _brief_difference_case(check):
    """sn6's report for a mismatch, over the pair a Windows leg produced: a
    written brief embedding a CRLF return, read back with LF. A red there is on
    a platform nobody runs locally, so the report has to say where it differs."""
    wrote = "# Brief\n\n## The executor's return\n{\r\n  \"gates\": {}\r\n}\n"
    shown = "# Brief\n\n## The executor's return\n{\n  \"gates\": {}\n}\n"
    at = wrote.index("\r")
    said = _brief_difference("reviewer", wrote, shown)
    same = _brief_difference("executor", shown, shown)
    check("tests/test_drive_phase.py: a brief read back that "
          "differs from the written brief is reported with its role, the first "
          "differing offset and both sides around it (%r)" % ((said, same),),
          same is None and isinstance(said, tuple) and len(said) == 4
          and said[0] == "reviewer" and said[1] == at
          and repr("{\r\n") [1:-1] in said[2] and "return" in said[2]
          and repr("{\n  ")[1:-1] in said[3] and "\\r" not in said[3])


def _signal_drive_cases(check):
    """A real drive under --signal: one line per step from the first dispatch
    to `done`, each agent briefed by `brief --role <role> <id>`, the dispatch prompts
    differing only by the id, and the did-words still read off the lines."""
    _brief_difference_case(check)
    M, why = _load("signal_drive_mod")
    check("sn5a the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    root, mpath = _repo("signal", task_ids=TASKS[:2])
    # A wave member's own tree: a checkout of the same commit, so it holds the
    # manifest and the config at the paths the project does, and no state.
    trees = os.path.realpath(_harness.fixture_root("drive-signal-tree-"))
    tree = os.path.join(trees, "member")
    try:
        _harness.git(root, "worktree", "add", "-q", "--detach", tree)
        printed, prompts, briefs = [], {}, []
        reply = []
        with _Env(root):
            for _ in range(30):
                said = []
                code = M.main(["next", PHASE, mpath, "--project-dir", root,
                               "--signal"] + reply, out=said.append)
                reply = []
                text = "\n".join(said)
                printed.append(text)
                hit = _SIGNAL.match(text)
                if code != 0 or not hit or hit.group(2) == "done":
                    break
                verb, subject = hit.group(2), hit.group(3)
                explain = []
                M.main(["next", PHASE, mpath, "--project-dir", root, "--explain",
                        subject], out=explain.append)
                explain = "\n".join(explain)
                if verb == "review":
                    reply = ["--answer", "sign-off", "--reason", SUMMARY]
                    continue
                role = re.search(r"\bbrief --role (executor|reviewer|phase) ",
                                 hit.group(6))
                if verb != "dispatch" or role is None:
                    break
                role = role.group(1)
                prompts[(role, subject)] = [ln[len("prompt: "):] for ln in
                                            explain.splitlines()
                                            if ln.startswith("prompt: ")]
                briefs.append((role, subject, _brief_from_prompt(
                    prompts[(role, subject)], tree)))
                if role == "executor":
                    _file_executor(root, mpath, subject)
                elif role == "phase":
                    _file_phase_review(root, mpath, explain)
                else:
                    _file_reviewer(root, mpath, subject)
        bad = [(t, _signal_ok(t)) for t in printed if _signal_ok(t)]
        verbs = [_SIGNAL.match(t).group(2) for t in printed if _SIGNAL.match(t)]
        check("sn5 a two-task drive under --signal prints one signal per step, each "
              "inside the bound, dispatch to done: %r" % ((bad, verbs),),
              not bad and verbs == ["dispatch"] * 4 + ["review", "done"])
        one = prompts.get(("executor", "P1.1")) or []
        two = prompts.get(("executor", "P1.2")) or []
        check("sn2 two executor dispatch prompts for different tasks are identical "
              "up to the task id, and the id comes last: %r" % ((one, two),),
              len(one) == 1 and len(two) == 1
              and one[0].endswith(" P1.1") and two[0].endswith(" P1.2")
              and one[0][:-len("P1.1")] == two[0][:-len("P1.2")]
              and "P1.1" not in one[0][:-len("P1.1")])
        differ = []
        for role, subject, shown in briefs:
            folder = os.path.join(root, ".claude", "state", "briefs", subject)
            names = sorted(n for n in os.listdir(folder)
                           if n.endswith(".%s.md" % (role,)) or
                           (role == "phase" and n == "phase.md"))
            with open(os.path.join(folder, names[-1]), "rb") as fh:
                wrote = fh.read().decode("utf-8", "replace")
            differ.append(_brief_difference(role, wrote.rstrip("\n"),
                                            shown.rstrip("\n")))
        check("tests/test_drive_phase.py: the brief command parsed out "
              "of the printed dispatch prompt, run from a wave tree with no "
              "CLAUDE_PROJECT_DIR, prints that task's brief (sn6: the brief the "
              "drive wrote for that dispatch, byte for byte, for every agent of "
              "the drive: %r)"
              % ((len(briefs), [d for d in differ if d is not None]),),
              len(briefs) == 4 and differ == [None] * 4)
        did = M.did_tasks("\n".join(printed))
        check("sn7 the did-words a session's stream is read from are still read "
              "off the signal lines: %r" % (did,),
              did["started"] == ["P1.1", "P1.2"] and did["closed"] == ["P1.1", "P1.2"])
    finally:
        _harness.remove_tree(trees)
        _harness.remove_tree(root)


def _brief_from_prompt(prompts, tree):
    """What the command a dispatch prompt names prints when an agent standing in
    `tree` runs it, with no CLAUDE_PROJECT_DIR: the command is the prompt's
    words after its fixed sentence, as a shell splits them, and the interpreter
    it spells is this one. A failed run is its own words, so a mismatch says
    why rather than only that it differs."""
    if len(prompts) != 1:
        return "no single prompt to run: %r" % (prompts,)
    argv = shlex.split(prompts[0].partition(": ")[2])
    if argv[:1] == ["python3"]:
        argv[0] = sys.executable
    env = dict((k, v) for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR")
    run = subprocess.run(argv, cwd=tree, env=env, capture_output=True,
                         timeout=120)
    shown = run.stdout.decode("utf-8", "replace")
    if run.returncode != 0:
        return "exit %d: %s%s" % (run.returncode, shown,
                                  run.stderr.decode("utf-8", "replace"))
    return shown


def _brief_crlf_cases(check):
    """A reviewer brief embeds the task's diff, and a diff's CONTENT may hold a
    carriage return - a CRLF file, which every fixture written in text mode on
    Windows is. `brief <id>` is how the agent reads that record, so it has to
    print those bytes exactly, in process and through the command line, with
    every child's text stdout Windows-shaped (`_windows_stdout`). That is where
    the record was lost: a verb whose stdout is held and printed again through
    the text layer writes the embedded CRLF as CR CR LF, and a newline-
    translating read of it then shows two line breaks for one."""
    title = ("a reviewer brief whose embedded diff carries a carriage return is "
             "printed by brief <id> byte for byte")
    M, why = _load("brief_crlf_mod")
    if M is None:
        check("%s (the driver did not load: %r)" % (title, why), False)
        return
    root, mpath = _repo("brief-crlf", task_ids=TASKS[:1])
    try:
        with open(os.path.join(root, "src", "f1.txt"), "wb") as fh:
            fh.write(b"v0\r\nkept\r\n")
        _harness.git(root, "commit", "-qam", "fixture: a CRLF source")
        _next(M, root, mpath)
        _file_executor(root, mpath, "P1.1")
        _code, dispatched = _next(M, root, mpath)
        folder = os.path.join(root, ".claude", "state", "briefs", "P1.1")
        names = sorted(n for n in os.listdir(folder) if n.endswith(".reviewer.md"))
        with open(os.path.join(folder, names[-1]), "rb") as fh:
            wrote = fh.read()
        shown = []
        with _windows_stdout(), _Env(root):
            code = M.main(["brief", "P1.1", mpath, "--role", "reviewer",
                           "--project-dir", root], out=shown.append)
            probe = subprocess.run([sys.executable, "-c", "print('a')"],
                                   capture_output=True, timeout=60).stdout
            cli = subprocess.run(_script(DRIVER) + [
                "brief", "P1.1", mpath, "--role", "reviewer", "--project-dir",
                root], cwd=root, capture_output=True, timeout=120)
    finally:
        _harness.remove_tree(root)
    inproc = "\n".join(shown).encode("utf-8")
    # The premise, counted rather than found: the fixture's CRLF line and the
    # diff's own LF lines both reach the brief, so a brief written all-LF or
    # all-CRLF tells the cases nothing.
    crlf = wrote.count(b"\r\n")
    check("%s (premise: the written brief holds %d CRLF beside its LF lines, "
          "and a child under the emulation prints CRLF from its text stream: "
          "%r; in process exit %d, first difference %r; command line exit %d, "
          "first difference %r, stderr %r; dispatched %r)"
          % (title, crlf, probe, code,
             _brief_difference("reviewer", wrote.rstrip(b"\n").decode("utf-8"),
                               inproc.decode("utf-8")),
             cli.returncode,
             _brief_difference("reviewer", wrote.decode("utf-8", "replace"),
                               cli.stdout.decode("utf-8", "replace")),
             cli.stderr[:300], dispatched[:200]),
          crlf >= 1 and wrote.count(b"\n") > crlf and probe == b"a\r\n"
          and code == 0 and inproc == wrote.rstrip(b"\n")
          and cli.returncode == 0 and cli.stdout == wrote)


# The same generator under the name the later cases use: both built the same
# suite line for line, so one definition carries the bytecode switch.
_house_suite = _wf_suite


CARRY_CLAUSE = ("tests/test_drive_phase.py: a pause with a filed "
                "wave member, its tree deleted and the drive resumed on a fresh "
                "clone, finds the member's work")


def _carry_refs(repo):
    """The task ids a repository holds a carry ref for."""
    out = _git_out(repo, "for-each-ref", "--format=%(refname)",
                   "refs/audit/carry/")
    return sorted(line.rsplit("/", 1)[-1] for line in out.splitlines()
                  if line.strip())


def _carry_pause(root, bare):
    """The hand-off a human makes before a machine move: the records committed
    and pushed, the working trees of the wave deleted. -> the trees deleted."""
    for argv in (["add", "-A", "--", "docs/audit"],
                 ["commit", "-qm", "pause: the records of a filed wave"],
                 ["push", "-q", "origin", "HEAD:refs/heads/main"]):
        _harness.git(root, *argv)
    gone = []
    for task_id in TASKS[:2]:
        tree = _tree_of(root, task_id)
        if tree and os.path.isdir(tree):
            shutil.rmtree(tree)
            gone.append(tree)
    _harness.git(root, "worktree", "prune")
    return gone


def _carry_cases(check):
    def clause(detail):
        return "%s (%s)" % (CARRY_CLAUSE, detail)

    M, why = _load("drive_phase_carry")
    if M is None:
        check(clause("the driver loads"), False, why)
        return
    root, mpath = _wave_repo("carry", 2, ci={"pushCarry": True})
    bare = os.path.realpath(_harness.fixture_root("drive-origin-"))
    _harness.git(bare, "init", "-q", "--bare")
    _harness.git(root, "remote", "add", "origin", bare)
    _harness.git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    filed = [_file_wave_executor(root, mpath, t)[0] for t in sent]
    check(clause("both wave members filed, and the origin holds a carry ref for "
                 "each: %r %r" % (filed, _carry_refs(bare))),
          sent == ["P1.1", "P1.2"] and filed == [0, 0]
          and _carry_refs(bare) == ["P1.1", "P1.2"])
    held = dict((t, _git_out(root, "diff", "--name-only", "refs/audit/carry/%s^"
                             % (t,), "refs/audit/carry/%s" % (t,)).split())
                for t in sent)
    check(clause("each carry holds the member's own file and nothing else: %r"
                 % (held,)),
          held == {"P1.1": ["src/f1.txt"], "P1.2": ["src/f2.txt"]})
    gone = _carry_pause(root, bare)
    check(clause("the pause deleted both trees: %r" % (gone,)), len(gone) == 2)

    fresh_parent = os.path.realpath(_harness.fixture_root("drive-fresh-"))
    fresh = os.path.join(fresh_parent, "clone")
    _harness.git(None, "clone", "-q", bare, fresh)
    with open(os.path.join(fresh, ".git", "config"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_FIXTURE_IDENTITY)
    fmpath = os.path.join(fresh, "docs", "audit", "audit-plan.json")
    check(clause("the fresh clone holds no carry ref of its own before the "
                 "drive runs: %r" % (_carry_refs(fresh),)),
          _carry_refs(fresh) == [])
    said = []
    for _ in range(4):
        _c, text = _next_wave(M, fresh, fmpath)
        said.append(text)
        done = tasks_of(fmpath)
        if all(done[t].get("status") == "done" for t in sent):
            break
    done = tasks_of(fmpath)
    rows = dict((t, [r.get("status") for r in _rows_of(fresh, fmpath, t)])
                for t in sent)
    with open(os.path.join(fresh, "src", "f1.txt"), encoding="utf-8") as fh:
        f1 = fh.read()
    with open(os.path.join(fresh, "src", "f2.txt"), encoding="utf-8") as fh:
        f2 = fh.read()
    check(clause("the drive resumed on the clone gates each member over its own "
                 "work and closes it against a commit holding that work: %r %r %r"
                 % ([(t, done[t].get("status"), done[t].get("commit"))
                     for t in sent], rows, said[-1][:300])),
          all(done[t].get("status") == "done" and done[t].get("commit")
              for t in sent)
          and f1 == "changed by P1.1\n" and f2 == "changed by P1.2\n"
          and all("passed" in rows[t] for t in sent))
    check(clause("a member that closed leaves no carry behind, on the clone or on "
                 "the origin: %r %r" % (_carry_refs(fresh), _carry_refs(bare))),
          _carry_refs(fresh) == [] and _carry_refs(bare) == [])

    # No origin: the filing stands, the carry is local, and the print says so.
    solo, solo_path = _wave_repo("carrysolo", 2, ci={"pushCarry": True})
    _code, sent_first = _next_wave(M, solo, solo_path)
    code, text = _file_wave_executor(solo, solo_path, _dispatched(sent_first)[0])
    check(clause("with no origin the carry stays in a local ref and the filing "
                 "says it is local only: %r %r" % (text, _carry_refs(solo))),
          code == 0 and "local only: the repository has no origin" in text
          and _carry_refs(solo) == ["P1.1"])


CARRY_LOCAL_CLAUSE = ("tests/test_drive_phase.py: with no carry "
                      "setting a filed wave member writes refs/audit/carry/<taskId> "
                      "locally and makes no push to any remote, and only an "
                      "explicit opt-in pushes it to origin")
# A git push as the trace names it, whatever flags precede the verb.
_GIT_PUSH = re.compile(r"\bgit (?:-\S+ (?:\S+ )?)*push\b")


def _traced_filing(M, ci, name):
    """File the first wave member of a fixture whose origin is a bare repository,
    with git's own trace recording every command the filing starts. -> `(root,
    mpath, bare, text, pushes, sent)`: `pushes` is the number of `git push` the
    trace names, which counts an attempt the remote refused or never saw."""
    root, mpath = _wave_repo(name, 2, ci=ci)
    bare = os.path.realpath(_harness.fixture_root("drive-origin-"))
    _harness.git(bare, "init", "-q", "--bare")
    _harness.git(root, "remote", "add", "origin", bare)
    _harness.git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    _code, first = _next_wave(M, root, mpath)
    sent = _dispatched(first)
    fd, trace = tempfile.mkstemp(prefix="git-trace-")
    os.close(fd)
    held = os.environ.get("GIT_TRACE")
    os.environ["GIT_TRACE"] = trace
    try:
        _code, text = _file_wave_executor(root, mpath, sent[0])
    finally:
        if held is None:
            os.environ.pop("GIT_TRACE", None)
        else:
            os.environ["GIT_TRACE"] = held
    with open(trace, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    os.unlink(trace)
    return root, mpath, bare, text, len([ln for ln in lines if _GIT_PUSH.search(ln)]), sent


def _carry_local_cases(check):
    def clause(detail):
        return "%s (%s)" % (CARRY_LOCAL_CLAUSE, detail)

    M, why = _load("drive_phase_carry_local")
    if M is None:
        check(clause("the driver loads"), False, why)
        return
    for label, ci in (("no ci block", None),
                      ("ci block without the key", {"workflow": "ci.yml"}),
                      ("pushCarry false", {"pushCarry": False}),
                      ("pushCarry the string yes", {"pushCarry": "yes"})):
        root, mpath, bare, text, pushes, sent = _traced_filing(
            M, ci, "carrylocal")
        check(clause("%s: the filing wrote the carry in the repository and the "
                     "origin holds none, with %d git push in the trace: %r %r"
                     % (label, pushes, _carry_refs(root), _carry_refs(bare))),
              sent[:1] == ["P1.1"] and _carry_refs(root) == ["P1.1"]
              and _carry_refs(bare) == [] and pushes == 0)
        check(clause("%s: the filing says the carry is local and does not travel "
                     "to another machine: %r" % (label, text)),
              "local only" in text and "does not travel to another machine" in text
              and "ci.pushCarry" in text)
    # The resume path: a tree lost on THIS machine is recut from the local carry.
    gone = _tree_of(root, "P1.1")
    shutil.rmtree(gone)
    _harness.git(root, "worktree", "prune")
    state_path = os.path.join(root, ".claude", "state", "drive", "%s.json" % (PHASE,))
    with open(state_path, encoding="utf-8") as fh:
        state = json.load(fh)
    state["wave"]["trees"].pop("P1.1", None)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    _code, again = _next_wave(M, root, mpath)
    check(clause("a tree lost where the carry was made is recut from the local "
                 "carry: %r" % (again[:400],)),
          "work of P1.1 restored from refs/audit/carry/P1.1" in again)
    # Opt-in: the same filing pushes, and the trace names the push.
    root, mpath, bare, text, pushes, sent = _traced_filing(
        M, {"pushCarry": True}, "carrypush")
    check(clause("pushCarry true: the origin holds the carry and the trace names "
                 "exactly one git push: %d %r %r"
                 % (pushes, _carry_refs(bare), text)),
          _carry_refs(bare) == ["P1.1"] and pushes == 1
          and "and pushed to origin" in text)


NESTED_PROJECT_CLAUSE = ("for a nested project, follow_red_gate runs a follower "
                         "recipe in the project's directory inside the member "
                         "tree (ctx project with no tree), and phase_gate and "
                         "the invariants run are handed the nested project "
                         "directory")


class _Reached(Exception):
    """Raised by a stubbed verb once the call under test has been recorded."""


def _nested_project_cases(check):
    """A recipe is printed by a gate step, which runs in the project directory,
    so its paths are project-relative: for a project under its git root it runs
    in the project's directory inside the member tree, and the phase gate and the
    invariants are handed the project directory, never the checkout's top."""
    def clause(detail):
        return "%s (%s)" % (NESTED_PROJECT_CLAUSE, detail)

    M, why = _load("drive_phase_nested_project")
    if M is None:
        check(clause("np0 the driver loads: %r" % (why,)), False)
        return
    scratch = _harness.fixture_root("nested-project-")
    try:
        top = os.path.join(scratch, "top")
        app = os.path.join(top, "app")
        member = os.path.join(scratch, "member")
        plan = os.path.join(scratch, "audit-plan.json")
        with open(plan, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 3}, "phases": []}, fh)
        nested = {"project": app, "gitRoot": top, "manifest": plan, "did": [],
                  "phase": PHASE, "config": {}}
        flat = dict(nested, project=top)
        task, phase = {"id": "P1.1", "attempts": 0}, {"id": PHASE}
        ran = []
        M.owed_followers = lambda ctx, text: ("run1", [
            {"path": "docs/map.txt", "recipe": "regen map", "owner": "o"}])
        M.widen_task = lambda *a, **kw: None
        M.write_state = lambda *a, **kw: None
        M.task_gate = lambda *a, **kw: (0, "", "")
        M._evio = argparse.Namespace(run_recipe=lambda recipe, cwd: (ran.append(cwd) or (0, ())))

        def where(ctx, tree):
            del ran[:]
            M.follow_red_gate(ctx, {}, phase, task, "", tree=tree)
            return ran[0] if ran else None
        got = [where(nested, member), where(nested, None), where(flat, member),
               where(flat, None)]
        want = [os.path.join(member, "app"), app, member, top]
        check(clause("np1 the recipe runs in app/ inside the member tree for a "
                     "nested project, in the project directory with no tree, and "
                     "at the tree's top for a project that is its git root: "
                     "got=%r want=%r" % (got, want)),
              got == want)

        seen = []

        def verb(ctx, script, args, **kw):
            seen.append((script, list(args)))
            if script == "verify-invariants.py":
                raise _Reached()
            return 0, "", ""
        M.run_verb = verb
        M.phase_gate(nested, phase)
        gate = [a for s, a in seen if s == "run-test-gate.py"]
        del seen[:]
        try:
            M.red_gate_stop(nested, phase, "", "")
        except _Reached:
            pass
        stop_inv = [a for s, a in seen if s == "verify-invariants.py"]
        del seen[:]
        M.git_head = lambda ctx: "head"
        M.green_phase_gate = lambda ctx, state, phase, head: ([], None)
        M.runtime_boot_root = lambda manifest, phase: (False, None)
        try:
            M.run_signoff(nested, {}, phase)
        except _Reached:
            pass
        inv = [a for s, a in seen if s == "verify-invariants.py"]
        check(clause("np2 phase_gate hands run-test-gate --project-dir the nested "
                     "project directory with no --tree, and the sign-off's "
                     "invariants run, red or green, gets it as --project: "
                     "gate=%r invariants=%r red-gate invariants=%r"
                     % (gate, inv, stop_inv)),
              len(gate) == 1 and gate[0][gate[0].index("--project-dir") + 1] == app
              and "--tree" not in gate[0]
              and all(len(i) == 1 and i[0][i[0].index("--project") + 1] == app
                      for i in (inv, stop_inv)))
    finally:
        _harness.remove_tree(scratch)

SCOPE_LANGUAGE_CLAUSE = (
    "tests/test_drive_phase.py: scope_gap on a task whose tests.add "
    "is a tests/test_*.py path and whose gate holds selftests and "
    "vitest returns no decision; a .mjs path vitest does not collect still returns "
    "the scope-gap decision naming vitest.config.mjs; a Python path under a gate "
    "with neither the sweep nor pytest is still reported")

SWEEP_GATE = "python3 tools/sweep-selftests.py"
VITEST_GATE = "npx vitest run"
# The sweep script's root list, the one thing the preflight reads from it.
SWEEP_ROOTS = ('SWEEP_DIRS = (\n    os.path.join("backend", "tests"),\n'
               '    "tools",\n)\n')


def _language_repo(prefix, add_path, gate, config="vitest.config.mjs"):
    """A one-task fixture whose gate is `gate`, whose only declared test is
    `add_path`, with a sweep script and a vitest config that includes only
    `tests/unit/**` (`config` names the config file; None writes none)."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], gate=gate)
    with open(mpath, encoding="utf-8") as fh:
        plan = json.load(fh)
    plan["phases"][0]["tasks"][0]["tests"]["add"] = ["%s: it holds" % (add_path,)]
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    os.makedirs(os.path.join(root, "tools"))
    with open(os.path.join(root, "tools", "sweep-selftests.py"), "w",
              encoding="utf-8") as fh:
        fh.write(SWEEP_ROOTS)
    if config:
        with open(os.path.join(root, config), "w", encoding="utf-8") as fh:
            fh.write("export default { test: { include: ['tests/unit/**/*.test.ts'] } };\n")
    for argv in (["add", "-A"], ["commit", "-qm", "language fixture"]):
        _harness.git(root, *argv)
    return root, mpath


def _scope_language_cases(check):
    def clause(detail):
        return "%s (%s)" % (SCOPE_LANGUAGE_CLAUSE, detail)

    M, why = _load("drive_phase_language")
    if M is None:
        check(clause("the driver loads"), False, why)
        return

    def run(prefix, add_path, gate, config="vitest.config.mjs"):
        root, mpath = _language_repo(prefix, add_path, gate, config)
        code, text = _next_wave(M, root, mpath)
        return code, text, tasks_of(mpath)["P1.1"]

    both = (SWEEP_GATE, VITEST_GATE)
    code, text, task = run("pyboth", "backend/tests/test_mine.py", both)
    check(clause("a Python suite under the sweep and vitest draws no scope-gap and "
                 "no could-not-tell line, and the task is dispatched: %r" % (text,)),
          code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text
          and "could not tell" not in text)
    code, text, task = run("mjs", "lib/store.test.mjs", both)
    check(clause("a .mjs test vitest does not collect still stops at scope-gap "
                 "naming vitest and vitest.config.mjs, with the widen remedy and "
                 "the task still pending: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "vitest.config.mjs" in text and "widen|block" in text
          and "vitest does not collect lib/store.test.mjs" in text
          and not _dispatched(text) and task.get("status") == "pending")
    code, text, task = run("pyvitest", "backend/tests/test_mine.py",
                           (VITEST_GATE,))
    check(clause("a Python suite under a gate holding neither the sweep nor pytest "
                 "is reported as a scope-gap that says no runner of the gate takes "
                 "it: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "no runner in this gate takes backend/tests/test_mine.py" in text
          and not _dispatched(text))
    code, text, task = run("jsonly", "lib/store.test.mjs", (SWEEP_GATE,))
    check(clause("a .mjs test under a gate holding only the sweep is reported the "
                 "same way: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "no runner in this gate takes lib/store.test.mjs" in text)
    code, text, task = run("pyoutside", "docs/test_mine.py", both)
    check(clause("a Python suite outside the sweep's roots is still reported "
                 "though the sweep is in the gate (the guard must not pass every "
                 ".py): %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "sweep does not collect docs/test_mine.py" in text)
    code, text, task = run("pypytest", "tests/test_mine.py", ("python3 -m pytest",),
                           config=None)
    check(clause("a Python suite under a gate holding pytest is asked of pytest "
                 "alone and, collected by its defaults, draws no decision: %r"
                 % (text,)),
          code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text)


UNCLASSIFIED_CLAUSE = (
    "a gate holding an entry no known runner classifies answers could-not-tell for "
    "a path no known runner takes, and the task starts")


def _unclassified_entry_cases(check):
    def clause(cid, detail):
        return "%s %s (%s)" % (cid, UNCLASSIFIED_CLAUSE, detail)

    M, why = _load("drive_phase_unclassified")
    if M is None:
        check(clause("uc0", "the driver loads: %r" % (why,)), False)
        return

    def run(prefix, add_path, gate):
        root, mpath = _language_repo(prefix, add_path, gate)
        code, text = _next_wave(M, root, mpath)
        return code, text, tasks_of(mpath)["P1.1"]

    node = "node --test lib/store.test.mjs"
    unit = "python3 -m unittest discover -s backend/tests"
    code, text, task = run("ucjs", "lib/store.test.mjs", (SWEEP_GATE, node))
    check(clause("uc1", "a .mjs suite, a gate of the sweep and `node --test`: one "
                 "could-not-tell line, the task dispatched, no scope-gap: %r" % (text,)),
          code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text
          and text.count("could not tell") == 1)
    code, text, task = run("ucpy", "backend/tests/test_mine.py", (VITEST_GATE, unit))
    check(clause("uc2", "a .py suite, a gate of vitest and `python3 -m unittest`: "
                 "the same answer: %r" % (text,)),
          code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text
          and text.count("could not tell") == 1)
    code, text, task = run("ucknown", "lib/store.test.mjs", (SWEEP_GATE,))
    check(clause("uc3", "the other direction: a gate whose every entry the preflight "
                 "classifies has no unclassified one, so the real misroute still "
                 "stops: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "no runner in this gate takes lib/store.test.mjs" in text
          and not _dispatched(text))
    code, text, task = run("ucdefinite", "docs/test_mine.py", (SWEEP_GATE, unit))
    check(clause("uc4", "a known runner's own definite no is not softened by the "
                 "unclassified entry beside it: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "sweep does not collect docs/test_mine.py" in text)
    _unclassified_lint_entry_cases(check, run, clause)


# The shape this repo's own gate has: the sweep plus entries that validate, lint,
# render or screenshot and run no test of a language the sweep leaves out.
REALISTIC_GATE = (
    SWEEP_GATE,
    "python3 plugins/audit/scripts/manifest/validate-manifest.py docs/audit/audit-plan.json",
    "claude plugin validate . && claude plugin validate plugins/audit",
    "python3 plugins/audit/scripts/status/audit-status.py docs/audit/audit-plan.json --gate",
    "python3 plugins/audit/scripts/report/render-report.py docs/audit/audit-plan.json "
    "--out-dir /tmp/audit-report",
    "ruff check plugins/audit tools && vermin -t=3.8- --no-tips --violations "
    "plugins/audit/scripts plugins/audit/hooks tests",
    "node tools/capture-screenshots.mjs --check",
    "node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html",
)


def _unclassified_lint_entry_cases(check, run, clause):
    code, text, task = run("uclint", "lib/store.test.mjs", REALISTIC_GATE)
    check(clause("uc5", "the sweep beside validate, lint, report and screenshot "
                 "entries, none of which runs a test: the real misroute still "
                 "stops at scope-gap: %r" % (text,)),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "no runner in this gate takes lib/store.test.mjs" in text
          and "could not tell" not in text and not _dispatched(text)
          and task.get("status") == "pending")
    for cid, prefix, extra in (
            ("uc6", "ucmocha", "npx mocha lib/"),
            ("uc7", "ucrunner", "node tools/run-suites.mjs lib/store.test.mjs"),
            ("uc8", "ucavatap", "npx ava lib/store.test.mjs")):
        code, text, task = run(prefix, "lib/store.test.mjs", REALISTIC_GATE + (extra,))
        check(clause(cid, "the same gate with `%s` added, an entry that can run "
                     "tests and that no runner classifies: could-not-tell, "
                     "dispatched, no scope-gap: %r" % (extra, text)),
              code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text
              and text.count("could not tell") == 1)


IMPORT_NOTE = re.compile(r"^import (\w+)(?: as (\w+))?\s+# noqa: E402\s+"
                         r"\(((?:\w+, )*\w+):", re.M)


def _import_note_cases(check):
    """An import's note names what the driver takes from that module; a note
    naming a function the driver never calls sends a reader to the wrong one."""
    with open(_loader.script_path(DRIVER), "r", encoding="utf-8") as fh:
        source = fh.read()
    notes = [(m.group(2) or m.group(1), name)
             for m in IMPORT_NOTE.finditer(source)
             for name in m.group(3).split(", ")]
    unused = ["%s.%s" % pair for pair in notes if "%s.%s" % pair not in source]
    # The reading must see the notes at all, or an empty list proves nothing.
    check("imc1 every name an import note in the driver gives is one the driver "
          "uses from that module (%d notes read): %r" % (len(notes), unused),
          len(notes) >= 10 and unused == [])


def _playwright_gate_cases(check):
    """A gate of vitest beside `npx playwright test`: an e2e spec vitest's
    config leaves out may be the browser runner's, whose config this reading
    does not read - so it is could-not-tell, never a scope-gap stop."""
    M, why = _load("drive_phase_playwright")
    if M is None:
        check("pw1 the driver loads: %r" % (why,), False)
        return

    def run(prefix, gate):
        root, mpath = _language_repo(prefix, "e2e/checkout.spec.ts", gate)
        code, text = _next_wave(M, root, mpath)
        return code, text, tasks_of(mpath)["P1.1"]

    code, text, task = run("pwtest", (VITEST_GATE, "npx playwright test"))
    check("pw1 a gate of vitest plus npx playwright test does not stop on a "
          "declared e2e spec vitest does not collect - one could-not-tell line "
          "naming playwright, the task dispatched: %r" % (text,),
          code == 0 and _dispatched(text) == ["P1.1"] and "scope-gap" not in text
          and text.count("could not tell") == 1 and "playwright" in text)
    # SECOND-DIRECTION CASE, for a token read as any mention of the runner:
    # `playwright install` runs no test, so vitest's definite no still stops.
    code, text, task = run("pwinstall", (VITEST_GATE, "npx playwright install"))
    check("pw2 ALLOW: a gate of vitest plus `npx playwright install`, which runs "
          "no test, still stops at scope-gap on the spec vitest does not "
          "collect: %r" % (text,),
          code == 0 and instruction(text) == ("decide", "scope-gap", None)
          and "vitest does not collect e2e/checkout.spec.ts" in text
          and not _dispatched(text) and task.get("status") == "pending")


UNCHECKED_CLAUSE = ("ids bound to a suite the submit's command did not run are "
                    "filed on the return beside testsAddGaps, and the reviewer's "
                    "brief shows them")


def _unchecked_ids_cases(check):
    """A tdd task binding ids in two suites, submitted with a command that runs
    one: the other suite's id is neither graded nor a gap, and it must still
    reach the reviewer, who prints the return's fields and nothing else."""
    M, why = _load("drive_phase_unchecked")
    check("ucs0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    plan = _plan(TASKS[:1], ("true",))
    task = plan["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", "tests/test_mine.py", "tests/test_other.py"]
    plan["fileIndex"] = dict((f, ["P1.1"]) for f in task["files"])
    ran_entry = "tests/test_mine.py: new1"
    skipped_entry = "tests/test_other.py: oth1"
    task["tests"] = {"mode": "tdd", "add": [ran_entry, skipped_entry],
                     "gate": ["true"], "expectRedFirst": True}
    root, mpath = _repo("unchecked", task_ids=TASKS[:1])
    os.makedirs(os.path.join(root, "tests"))
    for rel, text in (("src/mine.py", "v = 1\n"),
                      ("tests/test_mine.py", _house_suite([("old1", "mine.v >= 1")])),
                      ("tests/test_other.py", _house_suite([("old2", "mine.v >= 1")]))):
        with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "tdd")
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root], out=[].append)
    with open(os.path.join(root, "src", "mine.py"), "w", encoding="utf-8") as fh:
        fh.write("v = 2\n")
    with open(os.path.join(root, "tests", "test_mine.py"), "w", encoding="utf-8") as fh:
        fh.write(_house_suite([("old1", "mine.v >= 1"), ("new1", "mine.v == 2")]))
    with open(os.path.join(root, "tests", "test_other.py"), "w", encoding="utf-8") as fh:
        fh.write(_house_suite([("old2", "mine.v >= 1"), ("oth1", "mine.v == 2")]))
    body = _executor_body("P1.1", {"testsAdded": [ran_entry, skipped_entry],
                                   "casesAdded": ["new1", "oth1"]})
    code, text = _submit(None, root, mpath, "P1.1", body,
                         tail=["--", sys.executable, "tests/test_mine.py"])
    path = _filed_path(mpath, "P1.1")
    filed = json.loads(_read(path).decode("utf-8")) if os.path.exists(path or "-") else {}
    held = filed.get(_fr.UNCHECKED_FIELD)
    lookup = _loader.load_script("audit-lookup.py", "drive_unchecked_lookup")
    shown = "\n".join(lookup._tests_add_review_lines(task, filed))
    quiet = "\n".join(lookup._tests_add_review_lines(
        task, dict(filed, **{_fr.UNCHECKED_FIELD: []})))
    check("ucs1 %s: %r" % (UNCHECKED_CLAUSE, (code, filed.get(_fr.GAPS_FIELD), held)),
          code == 0 and filed.get(_fr.GAPS_FIELD) == []
          and isinstance(held, list) and len(held) == 1
          and held[0].startswith(skipped_entry) and "not checked" in held[0]
          and held[0] in shown and ran_entry not in held[0])
    # THE OTHER DIRECTION: a return whose submit graded every entry (the field is
    # an empty list) shows no such section, so a brief that always printed one
    # would pass the case above.
    check("ucs2 ALLOW: a filed return with no unchecked entry shows the reviewer "
          "no 'never compared' section: %r" % (quiet[-200:],),
          "never compared" not in quiet and "never compared" in shown)


def _recorded_dispatches(root, member, key="writer"):
    """The dispatches the drive state holds for `member`'s session under `key`
    (`writer`, or `reviewerSession`) - each with the argv it printed and the
    HEAD it recorded. An explain names one subject, which a wave of several
    members does not give a run line per member."""
    return ((((_drive_state(root).get(key) or {}).get(member) or {})
             .get("value") or {}).get("dispatches")) or []


def _unset_writer(root):
    """The config with `executor.writerModel` taken out, written over the
    committed one and left uncommitted so HEAD stays where the session was
    dispatched."""
    cfg_path = os.path.join(root, ".claude", "audit.config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.pop("executor", None)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


def _offered(text):
    """The answers the `--answer a|b|c` word of a decision's text offers."""
    found = re.search(r"--answer ([a-z-]+(?:\|[a-z-]+)*)", text or "")
    return found.group(1).split("|") if found else []


def _writer_off_cases(check):
    """A decision that asks `resume` of a writer session is asked only while
    the writer path is on; with `executor.writerModel unset` the same red-first
    or clause gap offers an answer that leaves the decision, and a pending one
    that outlived the setting names an answer it does offer - never `retry`
    where it is not one."""
    M, why = _load("drive_phase_writer_off")
    if M is None:
        check("wo1 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-wo-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    passing = _wf_suite([("old1", "mine.v >= 1"), ("new1", "mine.v >= 1")])
    kinds = (("clauses-uncovered", _WC_DESCRIPTION,
              {_WF_SRC: "v = 2\n", _WF_TEST: _WF_NEW_TEST}, _said("done", (1, 3))),
             ("red-refused", None, {_WF_SRC: "v = 2\n", _WF_TEST: passing},
              _said("done")))
    for n, (plain, description, edit, result) in enumerate(kinds, 1):
        root, mpath = _tdd_writer_repo("wo-%s" % (plain,), (_wf_gate(),), description)
        _signal_next(M, root, mpath)
        _c, block = _explain_of(M, root, mpath, "P1.1")
        _play_session(root, _run_argv(block) or [], bindir, log, "0.4%d" % (n,),
                      edit=edit, result=result)
        _unset_writer(root)
        code, line = _signal_next(M, root, mpath)
        _c, block = _explain_of(M, root, mpath, "P1.1")
        offered = _offered(block)
        before = _attempts(mpath, "P1.1")
        check("wo%da the session ran, then executor.writerModel was unset: the "
              "%s the work earns is asked as a decision that does not send "
              "anything to a session, and offers an answer other than block: %r"
              % (n, plain, (code, line, block)),
              code == 0 and ("decide %s " % (plain,)) in block
              and "resume" not in offered and "retry" in offered)
        code_r, line_r = _signal_next(M, root, mpath, "--answer", "retry")
        check("wo%db that decision's own answer leaves it: one attempt is spent "
              "and the next step is not the same decision again: %r"
              % (n, (code_r, line_r)),
              code_r == 0 and _attempts(mpath, "P1.1") == before + 1
              and ("decide %s " % (plain,)) not in line_r
              and "-writer" not in line_r)

        # The decision was asked while the writer path was on and is answered
        # after it went off: the stop names only what the decision offers.
        root2, mpath2 = _tdd_writer_repo("wo2-%s" % (plain,), (_wf_gate(),), description)
        _signal_next(M, root2, mpath2)
        _writer_round(M, root2, mpath2, bindir, log, "0.5%d" % (n,), edit=edit,
                      result=result)
        _c, asked = _explain_of(M, root2, mpath2, "P1.1")
        _unset_writer(root2)
        stop_code, stop_line = _signal_next(M, root2, mpath2, "--answer", "resume")
        _c, again = _explain_of(M, root2, mpath2, "P1.1")
        named = re.findall(r"answer ([a-z]+)", stop_line)
        check("wo%dc a `resume` answered after the writer path went off stops "
              "with a word naming only answers that decision offers (%s), and "
              "names at least one: %r"
              % (n, "|".join(_offered(asked)), (stop_code, stop_line, again)),
              stop_code == 1 and named and all(a in _offered(asked) for a in named)
              and "retry" not in named)


def _redispatch_wave_cases(check):
    """A reviewer session dispatched again for a wave member runs in the member's
    own tree: the command names that tree, and the dispatch records the HEAD
    that tree is at, not the phase tree's."""
    M, why = _load("drive_phase_redispatch_wave")
    if M is None:
        check("sr2 the driver loads", False, why)
        return
    stubs = os.path.realpath(_harness.fixture_root("drive-sr-stub-"))
    bindir = _writer_stub(stubs)
    log = os.path.join(stubs, "runs.jsonl")
    root, mpath = _wave_repo("rdwave", 2, per_task="always")
    cfg_path = os.path.join(root, ".claude", "audit.config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["executor"].update(WRITER_EXECUTOR)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    _harness.git(root, "commit", "-qam", "the writer session")
    _signal_next(M, root, mpath)
    for n, member in enumerate(TASKS[:2], 1):
        _play_session(root, _recorded_dispatches(root, member)[-1]["argv"], bindir,
                      log, "0.31", session=RV_SESSIONS[n - 1],
                      edit={"src/f%d.txt" % (n,): "changed by %s\n" % (member,)},
                      result=_said("done", (1,), path="src/f%d.txt" % (n,)))
    _signal_next(M, root, mpath)
    first, member = TASKS[0], TASKS[1]
    tree = _tree_of(root, member)
    # The first member's reviewer returns a clean answer, so its work lands in
    # the phase tree and moves that tree's HEAD past where the second member's
    # tree was cut; the second's read files but ended with no return object.
    _play_session(root, _recorded_dispatches(root, first, "reviewerSession")[-1]["argv"],
                  bindir, log, "0.32", session=RV_SESSIONS[2],
                  result=_review_json(mpath, first), tools=2)
    _play_session(root, _recorded_dispatches(root, member, "reviewerSession")[-1]["argv"],
                  bindir, log, "0.33", session=RV_SESSIONS[1],
                  result="no object here", tools=2)
    _code, asked = _signal_next(M, root, mpath)
    redispatched, said = _signal_next(M, root, mpath, "--answer", "redispatch")
    dispatches = _recorded_dispatches(root, member, "reviewerSession")
    last = dispatches[-1] if dispatches else {}
    member_head = _head_of(tree)
    check("sr2 a reviewer session dispatched again for a wave member names the "
          "member's own tree and records the HEAD that tree is at - not the "
          "phase tree's, which a commit has moved on: %r"
          % ((asked, redispatched, said, tree, last.get("head"), member_head),),
          redispatched == 0 and tree and member_head and member_head != _head_of(root)
          and last.get("head") == member_head
          and _flag(last.get("argv"), "--tree") == tree
          and _flag(last.get("argv"), "--role") == "reviewer"
          and len(dispatches) == 2)


STAGES = (("dp-block", "_drive_cases"), ("dpm-block", "_drive_mutant_cases"),
          ("dr-block", "_refusal_cases"),
          ("ucs-block", "_unchecked_ids_cases"),
          ("dd-block", "_decide_cases"), ("ct-block", "_continue_cases"),
          ("dd3-block", "_rerun_cases"), ("rs-block", "_resume_cases"),
          ("ws-block", "_writer_session_cases"),
          ("rv-block", "_reviewer_session_cases"),
          ("sk-block", "_session_skill_cases"),
          ("pv-block", "_phase_validation_cases"),
          ("pv4-block", "_phase_cold_cases"),
          ("pv7-block", "_pv_unit_cases"),
          ("rw-block", "_reopened_writer_cases"),
          ("wf-block", "_writer_files_cases"),
          ("xs-block", "_writer_scope_cases"),
          ("wl-block", "_writer_lock_cases"),
          ("wi-block", "_writer_invariant_cases"),
          ("wj-block", "_writer_reading_cases"),
          ("rrs-block", "_retry_reason_cases"),
          ("rm-block", "_rerun_measures_cases"),
          ("sv-block", "_stored_red_cases"),
          ("sv4-block", "_stored_rerun_cases"),
          ("sv5-block", "_stored_green_cases"),
          ("sv10-block", "_stored_explain_cases"),
          ("fx-block", "_fix_batch_cases"), ("ht-block", "_handed_triage_cases"),
          ("dt-block", "_single_task_cases"), ("dl-block", "_lock_stop_cases"),
          ("dk-block", "_key_cases"), ("ds-block", "_submit_cases"),
          ("ow-block", "_owed_red_first_cases"),
          ("dsm-block", "_submit_mutant_cases"), ("sg-block", "_signoff_cases"),
          ("sgf-block", "_signoff_findings_cases"),
          ("sq-block", "_advance_signoff_cases"),
          ("sq3-block", "_advance_refused_cases"),
          ("sa-block", "_review_answer_cases"),
          ("da-block", "_decline_answer_cases"),
          ("sr-block", "_redispatch_cases"),
          ("sr2-block", "_redispatch_wave_cases"),
          ("wo-block", "_writer_off_cases"), ("rr-block", "_reuse_review_cases"),
          ("lr-block", "_late_return_cases"),
          ("sf-block", "_fix_review_cases"),
          ("cv-block", "_converge_cases"), ("lf-block", "_low_fix_cases"),
          ("rc-block", "_round_cap_cases"), ("hr-block", "_risk_cases"),
          ("sh-block", "_standing_risk_cases"),
          ("rb-block", "_boot_cases"), ("db-block", "_decline_boot_cases"),
          ("lp-block", "_lint_probe_cases"),
          ("gb-block", "_banner_cases"), ("dc-block", "_decline_coverage_cases"),
          ("dc4-block", "_reuse_gate_cases"), ("gr-block", "_stale_gate_cases"),
          ("gr4-block", "_stale_reaccept_cases"),
          ("di-block", "_decline_breach_cases"),
          ("of-block", "_open_finding_cases"),
          ("nf-block", "_landing_cases"), ("bk-block", "_blocked_cases"),
          ("cn-block", "_chain_next_cases"),
          ("wv-block", "_wave_cases"), ("wr-block", "_wave_red_sibling_cases"),
          ("wp-block", "_wave_parked_return_cases"),
          ("nr-block", "_parked_return_cases"),
          ("wq-block", "_wave_record_cases"),
          ("wqm-block", "_wave_record_mutant_cases"),
          ("wq4-block", "_wave_sibling_record_cases"),
          ("wc-block", "_wave_crash_cases"), ("w1-block", "_width_one_cases"),
          ("wz-block", "_wave_width_cases"),
          ("fw-block", "_follower_cases"), ("fh-block", "_follower_wave_cases"),
          ("fm-block", "_follower_map_cases"),
          ("fi-block", "_follower_index_cases"),
          ("fr-block", "_follower_retire_cases"),
          ("fm2-block", "_follower_shot_cases"),
          ("al-block", "_ascii_locale_cases"),
          ("wt-block", "_wave_resume_cases"), ("wt5-block", "_wave_adopt_cases"),
          ("kr-block", "_kept_restart_cases"),
          ("wt7-block", "_wave_review_discard_cases"),
          ("wd-block", "_wave_redo_cases"), ("wg-block", "_wave_regate_cases"),
          ("ab-block", "_wave_advance_cases"),
          ("ar-block", "_recut_refused_move_cases"),
          ("ta-block", "_set_aside_cases"),
          ("wh-block", "_wave_hooks_cases"),
          ("pf-block", "_preflight_cases"),
          ("pg-block", "_scope_language_cases"),
          ("pu-block", "_unclassified_entry_cases"),
          ("pw-block", "_playwright_gate_cases"),
          ("imc-block", "_import_note_cases"),
          ("tx-block", "_text_cases"),
          ("sn-block", "_signal_cases"), ("sn3-block", "_explain_cases"),
          ("sn5-block", "_signal_drive_cases"),
          ("bc-block", "_brief_crlf_cases"),
          ("ce-block", "_close_evidence_cases"),
          ("bs-block", "_brief_scope_cases"),
          ("sc-block", "_scope_change_cases"), ("fv-block", "_review_rules_cases"),
          ("fp-block", "_retired_falsifier_cases"),
          ("mt-block", "_machine_text_cases"),
          ("gt-block", "_git_stdin_cases"),
          ("ci-block", "_ci_cadence_cases"),
          ("cr-block", "_carry_cases"),
          ("cl-block", "_carry_local_cases"),
          ("sl-block", "_slice_cases"),
          ("np-block", "_nested_project_cases"),
          ("bb-block", "_base_red_drive_cases"),
          ("tcc-block", "_committed_close_cases"),
          ("oc-block", "_own_commit_cases"),
          ("sb-block", "_stage_cases"))


CI_CADENCE_CLAUSE = ("tests/test_drive_phase.py: with ci.cadence "
                     "every 3 closes the drive dispatches CI on the third close "
                     "and not before, never waits on it, and reads its verdict "
                     "at the next close; absent, it dispatches only at landing")
CI_TASKS = ("P1.1", "P1.2", "P1.3", "P1.4")


def _ci_repo(prefix, ci):
    """A four-task fixture whose config carries `ci` (None: no `ci` key)."""
    root, mpath = _repo(prefix, task_ids=CI_TASKS, per_task="phase")
    cfg = os.path.join(root, ".claude", "audit.config.json")
    with open(cfg, encoding="utf-8") as fh:
        config = json.load(fh)
    if ci is None:
        return root, mpath
    config["ci"] = ci
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    _harness.git(root, "commit", "-qam", "config")
    return root, mpath


def _ci_fake(root, runs):
    """`(fake, calls)` - a stand-in for the driver's one seam to git's remote
    and to `gh`, recording every argv and answering `gh run list` with `runs`
    (a function of the sha the last push carried). No remote is touched."""
    calls = []
    pushed = []

    def fake(ctx, argv):
        calls.append(tuple(argv))
        if "push" in argv:
            pushed.append(argv[-1].split(":", 1)[0].lstrip("+"))
            return 0, "", ""
        if argv[:3] == ["gh", "workflow", "run"]:
            return 0, "", ""
        if argv[:3] == ["gh", "run", "list"]:
            return 0, json.dumps(runs(pushed[-1] if pushed else None)), ""
        return 1, "", "unexpected %r" % (argv,)
    return fake, calls, pushed


def _ci_run(M, root, mpath, runs):
    """Drive the whole phase with the CI seam faked. -> (calls, events, pushed,
    heads, run): `events` is the calls interleaved with a marker per close, in
    the order they happened; `heads` is HEAD as each push was made."""
    fake, calls, pushed = _ci_fake(root, runs)
    events, heads = [], []

    def seam(ctx, argv):
        if "push" in argv:
            heads.append(_head(root))
        events.append(("call", tuple(argv)))
        return fake(ctx, argv)
    real_ci, real_close = M.ci_run, M.close_task

    def closing(ctx, state, phase, task, intent_basis=None):
        said = real_close(ctx, state, phase, task, intent_basis=intent_basis)
        if any(d.startswith("%s %s" % (M.CLOSED, task["id"])) for d in ctx["did"]):
            events.append(("close", task["id"]))
        return said
    M.ci_run, M.close_task = seam, closing
    try:
        run = drive(M, root, mpath)
    finally:
        M.ci_run, M.close_task = real_ci, real_close
    return calls, events, pushed, heads, run


def _segments(events):
    """The calls made DURING each close, then after the last: `[[argv, ...],
    ...]`, one more segment than closes. A close's marker is written when it
    returns, so the calls its own CI step made sit in the segment before it."""
    out = [[]]
    for kind, value in events:
        if kind == "close":
            out.append([])
        else:
            out[-1].append(value)
    return out


def _ci_cadence_cases(check):
    """`ci.cadence`: the drive pushes the phase tip to `ci/<phase>` and
    dispatches the workflow every N closes, without waiting, and reads the run
    at the next close; a red files a bug; no cadence, no CI call at all."""
    def clause(detail):
        return "%s (%s)" % (CI_CADENCE_CLAUSE, detail)

    M, why = _load("ci_cadence_mod")
    if M is None:
        check(clause("the driver loads"), False, why)
        return

    def green(sha):
        return [{"databaseId": 501, "headSha": sha, "status": "completed",
                 "conclusion": "success", "url": "https://example.invalid/r/501"}]

    root, mpath = _ci_repo("cadence", {"cadence": {"closes": 3}})
    calls, events, pushed, heads, run = _ci_run(M, root, mpath, green)
    seg = _segments(events)
    closes = [v for k, v in events if k == "close"]
    shape = [[(a[0], a[1]) if a[0] == "gh" else ("git", a[3]) for a in s]
             for s in seg]
    check(clause("the drive closed all four tasks and finished: %r"
                 % ((closes, run["steps"][-1]),)),
          closes == list(CI_TASKS) and run["steps"][-1] == DONE)
    check(clause("no CI call is made at the first or second close; the push and "
                 "the dispatch are made at the third and only there: %r"
                 % (shape,)),
          len(seg) == 5 and seg[0] == [] and seg[1] == []
          and [a[3] for a in seg[2]][:1] == ["push"]
          and seg[2][1][:3] == ("gh", "workflow", "run") and len(seg[2]) == 2
          and not [a for s in seg[3:] for a in s if "push" in a])
    check(clause("the push carries the phase tip as it stood at the third close "
                 "to ci/p1, and the workflow is dispatched on that same branch: "
                 "%r" % (calls[:2],)),
          len(heads) == 1 and pushed == heads
          and calls[0][-1] == "+%s:refs/heads/ci/p1" % (heads[0],)
          and calls[1][-2:] == ("--ref", "ci/p1"))
    check(clause("it never waits: no `watch`, no exit-status polling, and the "
                 "fourth task is dispatched and closed while the run is out: %r"
                 % (calls,)),
          not [c for c in calls if "watch" in c or "--exit-status" in c]
          and closes[3] == "P1.4")
    reads = [c for c in calls if c[:3] == ("gh", "run", "list")]
    check(clause("the verdict is read once, at the next close - the fourth - and "
                 "never twice for a run already read: %r" % (shape,)),
          len(reads) == 1 and shape[3] == [("gh", "run")]
          and seg[4] == [])
    check(clause("a green verdict files no bug: %r"
                 % (_mio.load_manifest(mpath).get("bugs"),)),
          not _mio.load_manifest(mpath).get("bugs"))

    def red(sha):
        return [{"databaseId": 777, "headSha": sha, "status": "completed",
                 "conclusion": "failure", "url": "https://example.invalid/r/777"}]
    root2, mpath2 = _ci_repo("cadence-red", {"cadence": {"closes": 3}})
    _calls2, _events2, _pushed2, _heads2, _run2 = _ci_run(M, root2, mpath2, red)
    bugs = _mio.load_manifest(mpath2).get("bugs") or []
    check(clause("a red run read at the next close files one bug naming the run "
                 "and the branch: %r" % (bugs,)),
          len(bugs) == 1 and "777" in json.dumps(bugs[0])
          and "ci/p1" in json.dumps(bugs[0]) and bugs[0].get("status") == "open")

    def running(sha):
        return [{"databaseId": 901, "headSha": sha, "status": "in_progress",
                 "conclusion": "", "url": "https://example.invalid/r/901"}]
    root3, mpath3 = _ci_repo("cadence-run", {"cadence": {"closes": 3}})
    calls3, _e3, _p3, _h3, run3 = _ci_run(M, root3, mpath3, running)
    check(clause("a run still going at the next close is left alone - no second "
                 "dispatch is piled on it, nothing is filed, and the drive "
                 "finishes without waiting: %r" % (calls3,)),
          len([c for c in calls3 if c[:3] == ("gh", "workflow", "run")]) == 1
          and run3["steps"][-1] == DONE
          and not _mio.load_manifest(mpath3).get("bugs"))

    root4, mpath4 = _ci_repo("cadence-absent", None)
    calls4, _e4, _p4, _h4, run4 = _ci_run(M, root4, mpath4, green)
    check(clause("with no ci key the drive makes no push and no dispatch at any "
                 "close, and reads no run: %r" % (calls4,)),
          calls4 == [] and run4["steps"][-1] == DONE)

    # hours: a pure reading of the clock, asked with an injected `now`.
    cadence = {"closes": None, "hours": 2}
    base = {"at": 1000.0, "closes": 1}
    check(clause("hours: due only once the hours since the last dispatch have "
                 "elapsed, and closes counted since then do not matter when "
                 "closes is unset: %r"
                 % ((M.ci_due(cadence, base, 1000.0 + 7199),
                     M.ci_due(cadence, base, 1000.0 + 7200)),)),
          not M.ci_due(cadence, base, 1000.0 + 7199)
          and M.ci_due(cadence, base, 1000.0 + 7200))
    both = {"closes": 3, "hours": 2}
    check(clause("closes and hours together: either one is enough: %r"
                 % ((M.ci_due(both, {"at": 0.0, "closes": 3}, 10.0),
                     M.ci_due(both, {"at": 0.0, "closes": 1}, 7200.0),
                     M.ci_due(both, {"at": 0.0, "closes": 2}, 7199.0)),)),
          M.ci_due(both, {"at": 0.0, "closes": 3}, 10.0)
          and M.ci_due(both, {"at": 0.0, "closes": 1}, 7200.0)
          and not M.ci_due(both, {"at": 0.0, "closes": 2}, 7199.0))
    rules = _loader.load_script("_config_rules.py", "ci_rules_mod", cache=False)
    ok, ok_why = rules.ci_cadence_setting({"ci": {"cadence": {"closes": 3}}})
    absent, absent_why = rules.ci_cadence_setting({})
    bad, bad_why = rules.ci_cadence_setting({"ci": {"cadence": {"closes": 0}}})
    empty, empty_why = rules.ci_cadence_setting({"ci": {"cadence": {}}})
    check(clause("the config reads closes and hours; an absent key is no "
                 "cadence, and a zero, a non-number or an empty cadence is "
                 "refused with a reason, never read as the default: %r"
                 % ((ok, absent, bad, bad_why, empty_why),)),
          ok and ok["closes"] == 3 and ok_why is None
          and absent is None and absent_why is None
          and bad is None and bad_why and empty is None and empty_why
          and not rules.validate_config({"ci": {"cadence": {"hours": 4}}})[0]
          and rules.validate_config({"ci": {"cadence": {"closes": 0}}})[0]
          and "ci" in rules.KNOWN_ROOT)


MACHINE_TEXT_CLAUSE = ("a scope widening whose note text holds a run of spaces and "
                       "a backtick is written verbatim, and no verb call in "
                       "drive-phase.py passes a built string as an argv prose "
                       "value")

# The flags whose value a verb reads for the marks a shell leaves in a typed
# line are READ FROM THE VERB (`audit-task.py` `PROSE_FLAGS`, in the spelling
# argparse derives the option from), never copied here: a copy omitted eight
# of them the day it was typed. `review_outcome` is left out on purpose:
# `signoff` reads `--summary` in the same call and stdin carries one flag, and
# what the drive builds into the other is a hex head prefix, which holds none
# of those marks.
ARGV_PROSE_EXEMPT = ("review_outcome",)
STDIN_TEXT_HELPER = "_verb_with_text"


def argv_prose_flags():
    """The prose options of `audit-task.py` as they are typed (`--no-evidence-
    reason`), less `ARGV_PROSE_EXEMPT`, sorted - read off the loaded script's
    `PROSE_FLAGS`."""
    verb = _loader.load_script("audit-task.py", "argv_prose_flags_mod")
    return tuple(sorted("--" + dest.replace("_", "-") for dest in verb.PROSE_FLAGS
                        if dest not in ARGV_PROSE_EXEMPT))


def _template_head(node):
    """The literal text a built string opens with - `"--text=" + x`, `"--text=%s"
    % x`, `"--text={}".format(x)` or an f-string - or "" for anything else
    (a plain literal included: it is whole, nothing is built into it)."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = node.left
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add):
            left = left.left
        return left.value if (isinstance(left, ast.Constant)
                              and isinstance(left.value, str)) else ""
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        return first.value if (isinstance(first, ast.Constant)
                               and isinstance(first.value, str)) else ""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)):
        return node.func.value.value
    return ""


def _scope_nodes(scope):
    """The nodes of one function (or of the module's own statements), not those
    of a function defined inside it: a name in two functions is two lists."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _appended(scope):
    """`{target: [item, ...]}` - every item a function (or the module) adds to a
    list by name, in source order: the elements of `x = [...]`, `x += [...]`
    and `x.extend([...])`, and the argument of `x.append(...)`. Two calls that
    add a flag and then its value are one argv, and this is where it is seen."""
    entries = []
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    entries.append((node.lineno, node.col_offset, target.id,
                                    list(node.value.elts)))
        elif (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add)
              and isinstance(node.target, ast.Name)
              and isinstance(node.value, ast.List)):
            entries.append((node.lineno, node.col_offset, node.target.id,
                            list(node.value.elts)))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name)):
            if node.func.attr == "append" and len(node.args) == 1:
                entries.append((node.lineno, node.col_offset, node.func.value.id,
                                [node.args[0]]))
            elif (node.func.attr == "extend" and len(node.args) == 1
                  and isinstance(node.args[0], ast.List)):
                entries.append((node.lineno, node.col_offset, node.func.value.id,
                                list(node.args[0].elts)))
    out = {}
    for _line, _col, target, items in sorted(entries, key=lambda e: e[:2]):
        out.setdefault(target, []).extend(items)
    return out


def _bindings(scope):
    """`{name: [value, ...]}` for the names one function (or the module's own
    statements) binds: the string a plain `name = "literal"` gives it, or None
    for any other binding - a parameter, a built value, a loop or `with` target,
    an unpacking, an augmented assignment."""
    held = {}
    args = getattr(scope, "args", None)
    for arg in (list(args.args) + list(args.kwonlyargs)
                + [a for a in (args.vararg, args.kwarg) if a]
                if args is not None else []):
        held.setdefault(arg.arg, []).append(None)
    nodes = list(_scope_nodes(scope))
    counted = set()
    for node in nodes:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    counted.add(id(target))
                    held.setdefault(target.id, []).append(node.value.value)
    for node in nodes:
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                and id(node) not in counted):
            held.setdefault(node.id, []).append(None)
    return held


def _in_scopes(scope, chain):
    """`(node, chain)` for every node of `scope` and of the functions inside it,
    `chain` being the binding tables of the scopes it stands in, innermost first."""
    here = [_bindings(scope)] + chain
    for node in _scope_nodes(scope):
        yield node, here
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                             ast.ClassDef)):
            for inner in _in_scopes(node, here):
                yield inner


def _held_by(name, chain):
    """What the innermost scope that binds `name` says it holds (`_bindings`'
    list), or [] for a name no scope here binds."""
    for table in chain:
        if name in table:
            return table[name]
    return []


def argv_prose_violations(source, flags=None):
    """`["line N: <flag>"]` for every place `source` puts a prose flag beside a
    value that is not a literal. The pairing is read over the whole argv
    expression, in every shape one is built in: a list, a tuple or a call's
    positional arguments (neighbours); two calls that append the flag and then
    the value, or `+=` them in two steps (`_appended`); a flag and value joined
    into one string (`"--text=" + built`, `%`, `.format`, an f-string); and a
    flag held in a name. The only spared sequence is the positional list of a
    call to `_verb_with_text` itself, whose flag and text are separate
    parameters because it sends the text on stdin - the calls nested in its
    other arguments are read like any other.

    A NAME IS READ IN ITS OWN FUNCTION (`_bindings`): the innermost scope that
    binds it decides, and the module's assignments reach only a function that
    never binds the name itself. It is the flag when any of its bindings there
    is a prose flag - a name that is the flag on one path is reported - and it
    is a literal value, like a string constant, only when every one of them is a
    string literal.

    `flags` defaults to `argv_prose_flags()`: the verb's own list."""
    flags = tuple(argv_prose_flags() if flags is None else flags)
    tree = ast.parse(source)

    def flag_of(node, chain):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value if node.value in flags else None
        if isinstance(node, ast.Name):
            return next(iter(sorted(
                set(v for v in _held_by(node.id, chain) if v is not None)
                & set(flags))), None)
        return None

    def literal(node, chain):
        if isinstance(node, ast.Constant):
            return True
        held = _held_by(node.id, chain) if isinstance(node, ast.Name) else []
        return bool(held) and all(isinstance(v, str) for v in held)

    spared = set(id(node) for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == STDIN_TEXT_HELPER)
    found = []

    def read(seq, chain):
        for here, after in zip(seq, seq[1:]):
            flag = flag_of(here, chain)
            if flag and not literal(after, chain):
                found.append("line %d: %s" % (here.lineno, flag))

    for node, chain in _in_scopes(tree, []):
        if isinstance(node, (ast.List, ast.Tuple)):
            read(node.elts, chain)
        elif isinstance(node, ast.Call) and id(node) not in spared:
            read(node.args, chain)
        head = _template_head(node)
        for flag in flags:
            if head.startswith(flag + "="):
                found.append("line %d: %s" % (node.lineno, flag))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for items in _appended(node).values():
                read(items, [_bindings(node)] + chain)
    for items in _appended(tree).values():
        read(items, [_bindings(tree)])
    return sorted(set(found))


def _machine_text_cases(check):
    """Text a script built goes to a verb on stdin, so a verb's shell-damage
    check never judges text no shell touched."""
    def clause(case, detail):
        return "%s %s (%s)" % (case, MACHINE_TEXT_CLAUSE, detail)

    M, why = _load("machine_text_mod")
    check("mt0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    root, mpath = _repo("machine-text", task_ids=TASKS[:1])
    basis = "owed by  `lint`  on run 7"
    ns = argparse.Namespace(project_dir=root, manifest=mpath, verbose=False,
                            phase=PHASE, task_only=False)
    with _Env(root):
        ctx = M.context(ns)
        task = tasks_of(mpath)["P1.1"]
        stop = M.widen_task(ctx, {}, task, ["src/f2.txt"], basis)
    wanted = "files widened by src/f2.txt: %s" % (basis,)
    notes = _notes_of(mpath, "P1.1")
    check(clause("mt1", "widen_task with a basis holding two spaces and backticks "
                 "stops on nothing and the note is the built text byte for "
                 "byte; stop=%r notes=%r" % (stop, notes)),
          stop is None and notes == [wanted]
          and "src/f2.txt" in (tasks_of(mpath)["P1.1"].get("files") or []))

    with open(_loader.script_path(DRIVER), "r", encoding="utf-8") as fh:
        source = fh.read()
    seen = argv_prose_violations(source)
    helper_calls = [n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == STDIN_TEXT_HELPER]
    check(clause("mt2", "the driver as shipped passes no non-literal after a prose "
                 "flag in any argv it builds, and does send text through the "
                 "helper (%d calls); found %r" % (len(helper_calls), seen)),
          seen == [] and len(helper_calls) >= 5)

    list_form = ('def regress(ctx, built):\n'
                 '    return _verb_or_stop(ctx, "audit-task.py", _task_args(\n'
                 '        ctx, "note", "P1.1", "--text", built))\n')
    tuple_form = ('def regress(ctx, built):\n'
                  '    for args in (("note", "P1.1", "--text", built),):\n'
                  '        _verb_or_stop(ctx, "audit-task.py", args)\n')
    extend_form = ('def regress(ctx, built):\n'
                   '    args = ["bug-add", "t"]\n'
                   '    args += ["--description", built]\n')
    reds = [argv_prose_violations(source + "\n\n" + extra)
            for extra in (list_form, tuple_form, extend_form)]
    check(clause("mt3", "a scratch copy of the driver with a call carrying a built "
                 "string after a prose flag is reported, in each of the three "
                 "shapes an argv is built in; got %r" % (reds,)),
          all(len(r) == 1 for r in reds))
    # THE OTHER DIRECTION: a lint that reported every flag would pass mt3 too.
    fine = ('def ok(ctx, built):\n'
            '    _verb_with_text(ctx, "audit-task.py", _task_args(\n'
            '        ctx, "note", "P1.1"), "--text", built)\n'
            '    return ["--text", "a literal", "--severity", built]\n')
    check(clause("mt4", "a literal after a prose flag, a text handed to the helper "
                 "and a non-prose flag beside a built value are not reported; "
                 "got %r" % (argv_prose_violations(fine),)),
          argv_prose_violations(fine) == [])

    # THE FLAG SET IS THE VERB'S, read from it: every dest `audit-task.py`
    # lists, less the one exemption, and the eight a hand-typed copy once left
    # out among them.
    verb = _loader.load_script("audit-task.py", "argv_prose_flags_mod")
    wanted = sorted("--" + d.replace("_", "-") for d in verb.PROSE_FLAGS
                    if d not in ARGV_PROSE_EXEMPT)
    omitted = ("--rename", "--no-evidence-reason", "--issue", "--resolution",
               "--repro", "--expected", "--actual", "--override-verdict")
    check(clause("mt5", "the lint's prose flags are the verb's PROSE_FLAGS as "
                 "typed, read from audit-task.py, and include every flag the "
                 "earlier copy omitted; got %r" % (argv_prose_flags(),)),
          list(argv_prose_flags()) == wanted
          and all(f in argv_prose_flags() for f in omitted)
          and "--review-outcome" not in argv_prose_flags())
    omitted_forms = ['def r(ctx, built):\n    return ["%s", built]\n' % (f,)
                     for f in omitted]
    check(clause("mt6", "a built value after each flag the earlier copy omitted "
                 "is reported; got %r"
                 % ([argv_prose_violations(f) for f in omitted_forms],)),
          all(len(argv_prose_violations(f)) == 1 for f in omitted_forms))
    # Each shape the reviewer found the neighbour-only reading blind to.
    two_calls = ('def r(ctx, built):\n    args = ["note", "P1.1"]\n'
                 '    args.append("--text")\n    args.append(built)\n')
    two_steps = ('def r(ctx, built):\n    args = ["note", "P1.1"]\n'
                 '    args += ["--description"]\n    args += [built]\n')
    joined = ('def r(ctx, built):\n    return ["note", "--text=" + built]\n')
    joined_fmt = ('def r(ctx, built):\n    return ["note", "--text=%s" % built,'
                  ' "--reason={}".format(built)]\n')
    named = ('def r(ctx, built):\n    flag = "--summary"\n'
             '    return _task_args(ctx, "signoff", "P1", flag, built)\n')
    nested = ('def r(ctx, built):\n    return _verb_with_text(ctx, "audit-task.py",'
              ' _task_args(ctx, "note", "P1.1", "--text", built), "--text", built)\n')
    shapes = dict((name, argv_prose_violations(text)) for name, text in (
        ("two-call append", two_calls), ("two-step +=", two_steps),
        ("joined =", joined), ("joined % and format", joined_fmt),
        ("flag in a name", named), ("nested in helper args", nested)))
    check(clause("mt7", "the argv expression is read whole: two appends, two "
                 "`+=`, a joined `--flag=value`, a flag held in a name and a call "
                 "nested in the helper's arguments are each reported; got %r"
                 % (shapes,)),
          len(shapes["two-call append"]) == 1 and len(shapes["two-step +="]) == 1
          and len(shapes["joined ="]) == 1
          and len(shapes["joined % and format"]) == 2
          and len(shapes["flag in a name"]) == 1
          and len(shapes["nested in helper args"]) == 1)
    # THE OTHER DIRECTION, so no widening above is a lint that reports a flag
    # wherever it stands: separate functions share no list, a literal value is
    # no built one, and a non-prose flag is not a prose flag.
    apart = ('def a(ctx):\n    args = []\n    args.append("--text")\n'
             'def b(ctx, built):\n    args = []\n    args.append(built)\n')
    literal_pair = ('def r(ctx):\n    args = ["note"]\n    args.append("--text")\n'
                    '    args.append("a literal")\n    args += ["--severity"]\n'
                    '    args += ["x"]\n    return ["--text=a literal"]\n')
    quiet = ('def r(ctx, built):\n    flag = "--severity"\n'
             '    args = ["bug-add", flag, built]\n    args.append("--files")\n'
             '    args.append(built)\n    return "--texture=" + built\n')
    check(clause("mt8", "a flag in one function and a built value in another, "
                 "literal values, and non-prose flags built from values are not "
                 "reported; got %r"
                 % ((argv_prose_violations(apart),
                     argv_prose_violations(literal_pair),
                     argv_prose_violations(quiet)),)),
          argv_prose_violations(apart) == []
          and argv_prose_violations(literal_pair) == []
          and argv_prose_violations(quiet) == [])
    # `_verb_with_text`: a blank text is not sent on argv, which the verb would
    # refuse for the marks it reads; the helper says so and runs nothing.
    with _Env(root):
        ctx2 = M.context(ns)
        calls = []
        real_verb = M._verb_or_stop
        M._verb_or_stop = lambda *a, **k: calls.append((a, k)) or ("ok", None)
        try:
            blank = M._verb_with_text(ctx2, "audit-task.py", ["note"], "--text", "")
            spaces = M._verb_with_text(ctx2, "audit-task.py", ["note"], "--text",
                                       "   ")
            full = M._verb_with_text(ctx2, "audit-task.py", ["note"], "--text",
                                     "a  b")
        finally:
            M._verb_or_stop = real_verb
    check(clause("mt9", "a whitespace-only text is refused by the helper with a "
                 "sentence naming the flag and sends nothing, an empty text goes "
                 "on argv as the verb's own legal 'none', and a built text goes "
                 "on stdin; got %r" % ((blank, spaces, full, calls),)),
          spaces[0] is None and isinstance(spaces[1], tuple)
          and "--text" in spaces[1][1] and "whitespace" in spaces[1][1]
          and blank == ("ok", None) and full == ("ok", None) and len(calls) == 2
          and calls[0][0][2][-2:] == ["--text", ""]
          and calls[1][0][2][-2:] == ["--text", "-"]
          and calls[1][1].get("stdin") == "a  b")

    # NAMES ARE RESOLVED IN THEIR OWN FUNCTION (reviewer's two over-fires), and a
    # module-level name still reaches a function that never assigns it.
    shadowed = ('x = "--text"\n'
                'def r(b):\n    x = b\n    return [x, b]\n')
    const_value = ('T = "a"\n'
                   'def r():\n    return ["--text", T]\n'
                   'def s():\n    v = "b"\n    return ["--text", v]\n')
    check(clause("mt10", "ALLOW: a name that holds a built value in its own "
                 "function is not the flag a module-level assignment gave the "
                 "same name, and a name whose assignments are string literals "
                 "is a literal value, not a built one; got %r"
                 % ((argv_prose_violations(shadowed),
                     argv_prose_violations(const_value)),)),
          argv_prose_violations(shadowed) == []
          and argv_prose_violations(const_value) == [])
    inherited = ('FLAG = "--summary"\n'
                 'def r(built):\n    return ["x", FLAG, built]\n')
    mixed = ('def r(built, c):\n    flag = "--text"\n    if c:\n'
             '        flag = built\n    return ["x", flag, built]\n')
    check(clause("mt11", "a flag held in a module-level name and used in a "
                 "function that never assigns it is reported, and so is a name "
                 "that is the flag on one path and a built value on another; "
                 "got %r" % ((argv_prose_violations(inherited),
                              argv_prose_violations(mixed)),)),
          len(argv_prose_violations(inherited)) == 1
          and len(argv_prose_violations(mixed)) == 1)
    # THE LINT READS THE OTHER SCRIPT THAT SENDS BUILT TEXT TO A VERB TOO.
    with open(_loader.script_path("full-gate.py"), "r", encoding="utf-8") as fh:
        gate_source = fh.read()
    gate_seen = argv_prose_violations(gate_source)
    gate_helpers = [n for n in ast.walk(ast.parse(gate_source))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == STDIN_TEXT_HELPER]
    gate_red = argv_prose_violations(
        gate_source + "\n\ndef regress(built):\n"
        "    return ['bug-add', '--reason', built]\n")
    check(clause("mt12", "full-gate.py as shipped passes no non-literal after a "
                 "prose flag in any verb argv it builds, and does send its "
                 "description through the helper (%d calls); a scratch copy with "
                 "a built string after a second prose flag is reported; found %r, "
                 "scratch %r" % (len(gate_helpers), gate_seen, gate_red)),
          gate_seen == [] and len(gate_helpers) >= 1 and len(gate_red) == 1)


EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
GIT_STDIN_CLAUSE = ("tests/test_drive_phase.py: a fixture git call "
                    "runs with stdin closed, and one that times out reports the "
                    "tail of its GIT_TRACE2 trace, so a hang names the step it "
                    "stopped in")


def _trace_files():
    """The trace scratch files `_harness.git` leaves in the temp directory."""
    import tempfile
    return sorted(n for n in os.listdir(tempfile.gettempdir())
                  if n.startswith("git-trace2-"))


def _git_stdin_cases(check):
    """`_harness.git` never waits on stdin, and a hang names where git was.

    The stdin case runs the call in a child whose own stdin is an OPEN pipe
    nobody writes to: a git that inherited it would block on `--stdin` until
    the timeout, which is the hang this exists against. The hang case stalls
    `status` inside its fsmonitor hook, a step git traces as a region."""
    import tempfile

    def clause(detail):
        return "%s (%s)" % (GIT_STDIN_CLAUSE, detail)

    before = _trace_files()
    code = ("import sys; sys.path.insert(0, %r); import _harness; "
            "print(_harness.git(None, 'hash-object', '--stdin'))"
            % os.path.dirname(os.path.abspath(__file__)))
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.wait(timeout=30)
        done = True
    except subprocess.TimeoutExpired:
        done = False
        child.kill()
        child.wait()
    out = child.stdout.read().decode("utf-8", "replace")
    err = child.stderr.read().decode("utf-8", "replace")
    for pipe in (child.stdin, child.stdout, child.stderr):
        pipe.close()
    check(clause("hash-object --stdin returns the empty blob at once while the "
                 "caller's stdin stays open; got done=%s out=%r err=%r"
                 % (done, out.strip(), err.strip()[-200:])),
          done and out.strip() == EMPTY_BLOB)

    where = tempfile.mkdtemp(prefix="drive-trace-")
    try:
        _harness.git(where, "init", "-q")
        with open(os.path.join(where, "f"), "w", encoding="utf-8") as fh:
            fh.write("a\n")
        _harness.git(where, "add", "f")
        slow = ("-c", "core.fsmonitor=sleep 10; echo")
        try:
            _harness.git(where, "status", prefix=_harness.GIT + slow, timeout=3)
            msg = "(no RuntimeError: the call finished)"
        except RuntimeError as exc:
            msg = str(exc)
    finally:
        _harness.remove_tree(where)
    tail = msg.split("trace2 tail:", 1)[-1]
    regions = [ln for ln in tail.splitlines() if "region_enter" in ln]
    check(clause("a call stopped at its timeout reports a trace2 tail holding a "
                 "region_enter line, the fsm_hook region it stalled in; got %r"
                 % (msg[-300:],)),
          "did not finish within 3s" in msg and len(regions) >= 1
          and any("fsm_hook" in ln for ln in regions))
    check(clause("the trace scratch is removed after a success and after a "
                 "timeout; left behind: %r"
                 % (sorted(set(_trace_files()) - set(before)),)),
          set(_trace_files()) <= set(before))


def _review_rules_cases(check):
    """The reviewer-brief ordering rule, the tests.add-vs-filed-return gap
    check and the contradicted-clause severity floor, as pure functions over
    `drive-phase.py`."""
    M, why = _load("fv_mod")
    check("fv0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return

    task = {"id": "P5.3", "description": "src is set when the card enters the "
                                         "viewport"}
    claim = M.claim_section(task, {"outcome": {"technical": "t"}})
    task_at = claim.find(task["description"])
    claim_at = claim.find("Claim under review")
    check("fv1 the task's own description comes before the return, which is "
          "labelled as the claim under review: %r" % (claim,),
          task_at != -1 and claim_at != -1 and task_at < claim_at)

    matching_task = dict(task)
    matched = {"gates": {}, "redFirst": {"status": "proved", "basis": "x", "at": "z"},
               "outcome": {"technical": "t", "descriptive": "d"},
               "testsAdded": ["one"], "stamp": "audit-stamp: v2 x",
               "intent": {"answer": "matches",
                          "note": "the diff does what the description says - "
                                  "src is set when the card enters the "
                                  "viewport, nothing more."},
               "findings": [], "verdict": "clean"}
    restated_only = dict(matched, intent={
        "answer": "matches",
        "note": "ships a 200px rootMargin so the card loads near the "
                "viewport before it is visible"})
    import _filed_returns as fr_mod
    held = fr_mod.return_problems("reviewer", matched, matching_task)
    unsupported = fr_mod.return_problems("reviewer", restated_only, matching_task)
    check("fv2 a `matches` note quoting the task's own clause files; one "
          "that restates the claim with none of the task's words is refused "
          "as unsupported: %r" % ((held, unsupported),),
          held == [] and any("unsupported" in p or "quotes no clause" in p
                             for p in unsupported))

    add_task = {"tests": {"add": ["tests/test_x.py: once the card enters "
                                 "the viewport", "tests/test_y.py: isto"]}}
    printed = ["fv31 once the card enters the viewport", "fv32 isto je to"]
    present = M.case_binding_gaps(add_task, ["fv31", "fv32"], printed)
    wrong_id = M.case_binding_gaps(add_task, ["fv31", "fv99"], printed)
    unbound = M.case_binding_gaps(add_task, ["fv31"], printed)
    check("fv3 a declared case bound to a printed case id names no gap, in any "
          "language of title; an id the suite did not print, or an entry with "
          "no id, is named by the drive with its entry: %r"
          % ((present, wrong_id, unbound),),
          present == []
          and len(wrong_id) == 1 and wrong_id[0].startswith("tests/test_y.py: isto")
          and "`fv99`" in wrong_id[0]
          and len(unbound) == 1 and unbound[0].startswith("tests/test_y.py: isto"))

    low = [{"id": 1, "severity": "low", "file": "a:1",
            "issue": "contradicts task clause: scope widened", "resolution": "r"}]
    other_low = [{"id": 2, "severity": "low", "file": "a:2",
                 "issue": "an ordinary nitpick", "resolution": "r"}]
    floored = M.floor_contradicted_clause(low)
    untouched = M.floor_contradicted_clause(other_low)
    check("fv4 a low finding naming a contradicted task clause is raised to "
          "med; an ordinary low finding is untouched: %r"
          % ((floored, untouched),),
          floored[0]["severity"] == "med" and untouched[0]["severity"] == "low")


# The plan still validates with `tests.falsifiers` in it (the schema keeps the
# field, read by nothing), so a fixture can plan one and the drive must go past
# it as if the key were not there.
RETIRED_CLOSE_CLAUSE = ("a task whose tests carry falsifiers closes after a green "
                        "gate without applying any mutation and without a "
                        "falsifier decision")
RETIRED_RETURN_CLAUSE = ("an executor return that still carries a falsifiers "
                         "field is filed and the field is not written to the "
                         "task")
_FV_ADD = "src/f1.txt: the file says the task changed it"
_FP_WEAK = {"file": "src/f1.txt", "find": "changed", "replace": "broken",
            "command": [sys.executable, "-c", "pass"], "timeout": 60}


def _planned_falsifier_repo(prefix, ran_marker):
    """A one-task drive whose task plans one test and carries a falsifier whose
    command writes `ran_marker` (an absolute path, outside the repo, so a copy
    of the tree being thrown away cannot hide that it ran)."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    with open(mpath, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    tests = plan["phases"][0]["tasks"][0]["tests"]
    tests["add"] = [_FV_ADD]
    tests["falsifiers"] = {_FV_ADD: {
        "file": "src/f1.txt", "find": "changed", "replace": "broken",
        "command": [sys.executable, "-c",
                    "open(%r, 'w').write('ran')" % (ran_marker,)],
        "timeout": 60}}
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "commit", "-qam", "plan the falsifier")
    return root, mpath


def _notes_of(mpath, task_id):
    return [str(n.get("text") or "") for n in
            tasks_of(mpath).get(task_id, {}).get("notes") or []
            if isinstance(n, dict)]


def _retired_falsifier_cases(check):
    """A planned `tests.falsifiers` is read by nothing: the close goes past it,
    and a return that still declares one is filed and not recorded."""
    M, why = _load("fp_mod")
    check("fp0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    gone = [name for name in ("run_falsifier", "mutation_site", "note_falsifiers",
                              "record_falsifiers", "falsify", "FALSIFIER_TIMEOUT",
                              "returned_falsifier_problems")
            if hasattr(M, name)]
    check("fp0b the drive holds none of the falsifier stage's names (%r still "
          "defined)" % (gone,), gone == [])

    scratch = _harness.fixture_root("retired-falsifier-")
    marker = os.path.join(scratch, "ran")
    try:
        root, mpath = _planned_falsifier_repo("retired-close", marker)
        _next(M, root, mpath)
        _file_executor(root, mpath, "P1.1")
        _code, text = _next(M, root, mpath)
        with open(os.path.join(root, "src", "f1.txt"), "r", encoding="utf-8") as fh:
            left = fh.read()
        task = tasks_of(mpath).get("P1.1", {})
        check("%s (fp1: with a falsifier planned, `next` closes the task, the "
              "falsifier's command never ran - %s absent - the executor's file "
              "is as the executor left it, no `falsifier` decision or word is "
              "printed and the task holds no note: %r)"
              % (RETIRED_CLOSE_CLAUSE, marker,
                 (task.get("status"), os.path.exists(marker), left, text[:300],
                  _notes_of(mpath, "P1.1"))),
              task.get("status") == "done" and M.CLOSED in text
              and not os.path.exists(marker) and left == "changed by P1.1\n"
              and "falsifier" not in text.lower() and not _notes_of(mpath, "P1.1"))
    finally:
        _harness.remove_tree(scratch)

    clause = _FV_ADD.split(": ", 1)[1]
    for name, over in (("fp2", {"falsifiers": {_FV_ADD: _FP_WEAK}}),
                       # An agent body older than this change may declare it
                       # in a shape nothing reads any more; it is not refused.
                       ("fp2b", {"falsifiers": "not an object"}),
                       ("fp2c", {"falsifiers": {_FV_ADD: "not an object"}})):
        root, mpath = _repo("retired-%s" % (name,), task_ids=TASKS[:1],
                            per_task="phase")
        with open(mpath, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        tests = plan["phases"][0]["tasks"][0]["tests"]
        tests.update({"mode": "tdd", "expectRedFirst": True, "add": [_FV_ADD]})
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2)
        _harness.git(root, "commit", "-qam", "plan the task")
        _next(M, root, mpath)
        filed = _file_executor(root, mpath, "P1.1",
                               dict(over, testsAdded=[clause]))
        _code, closed = _next(M, root, mpath)
        task = tasks_of(mpath).get("P1.1", {})
        check("%s (%s: the return carrying %r is filed (exit %r), the task's "
              "tests gain no `falsifiers` key, it closes, and no word of a "
              "falsifier is printed or noted: %r)"
              % (RETIRED_RETURN_CLAUSE, name, sorted(over), filed[0],
                 (filed[1][:300], closed[:200], task.get("tests"),
                  task.get("notes"))),
              filed[0] == 0 and "falsifiers" not in (task.get("tests") or {})
              and task.get("status") == "done" and M.CLOSED in closed
              and "falsifier" not in (filed[1] + closed).lower()
              and not task.get("notes"))



def unencoded_text_opens(source):
    """The line of every text-mode open or subprocess call in `source` that
    names no encoding, sorted - `_output`'s walker, the one the tree-wide lint
    runs over scripts/ and hooks/, asked of this suite's own source too."""
    return [line for line, _what in _output_lints.unencoded_text_io(source)]


# The block re-run under a locale that cannot spell UTF-8: it drives a wave
# whose member regenerates a document full of non-ASCII text, integrates it as
# a follower and closes, so every decode between the verbs and this suite is
# on its path.
ASCII_BLOCK = "fm-block"
INTEGRATE_SUITE = "test_integrate_task.py"
# What makes a locale's preferred encoding ASCII on POSIX; on Windows the
# variables are ignored and the ANSI code page stands in, which spells no more.
ASCII_ENV = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}
_UTF8_NAMES = ("utf-8", "utf8", "cp65001")


def _ascii_coverage_case(check):
    """The coverage `_ascii_locale_cases` states, held to what exists: the
    re-run block is a stage, is not the stage that runs it, and the sweep's
    encoding pass pins a locale on macOS, none on Linux and none on Windows."""
    sweep = _harness._load_sweep()
    posix = sweep.locale_decision("posix", ("ascii", "utf-8"), "cp1252")
    linux = sweep.locale_decision("posix", ("ANSI_X3.4-1968", "ascii"),
                                  "cp1252")
    nt = sweep.locale_decision("nt", None, "cp1252")
    names = [name for name, _fn in STAGES]
    doc = " ".join(_ascii_locale_cases.__doc__.split())
    check("tests/test_drive_phase.py: the case P125-R147 asks "
          "for, locking the behaviour at HEAD (ASCII_BLOCK names a stage other "
          "than the one that re-runs it, the docstring states the macOS, "
          "Linux and Windows coverage, and the sweep's encoding pass pins the "
          "locale on macOS and none on Linux or Windows): %r"
          % ((ASCII_BLOCK, names.count(ASCII_BLOCK), posix["locale"],
              nt["locale"]),),
          names.count(ASCII_BLOCK) == 1 and ASCII_BLOCK != "al-block"
          and ("al-block", "_ascii_locale_cases") in STAGES
          and "on macOS the sweep's `--encoding` pass covers them" in doc
          and "on Linux the locale is not pinned, only the stdio codec is set"
              in doc
          and "on Windows the sweep pins no locale, so nothing re-runs "
              "them under a non-UTF-8 locale" in doc
          and bool(posix["locale"]) and nt["locale"] == {})
    check("tests/test_drive_phase.py: the case P125-R165 asks "
          "for, locking the behaviour at HEAD (a Linux-shaped report, "
          "ANSI_X3.4-1968 with an ASCII filesystem, leaves the locale "
          "unpinned and sets only the stdio codec): %r"
          % ((linux["locale"], linux["problem"]),),
          linux["locale"] == {} and linux["problem"] is None
          and "only the stdio half ran" in linux["line"])


def _ascii_locale_cases(check):
    """`ASCII_BLOCK` run again as a child whose locale's preferred encoding is
    not UTF-8: every case it reports passes there, as it does in this suite's
    own run of that block.

    WHAT IS COVERED, per platform. `ASCII_BLOCK` is re-run under the pinned
    ASCII locale on every platform. The drive suite's other blocks are not
    re-run here: on macOS the sweep's `--encoding` pass covers them, since it
    pins the locale there and file names stay UTF-8 under C; on Linux the
    locale is not pinned, only the stdio codec is set, because C makes the
    filesystem encoding ASCII too, so no run re-runs them under a non-UTF-8
    locale; on Windows the sweep pins no locale, so nothing re-runs them
    under a non-UTF-8 locale. `ASCII_BLOCK` was chosen because
    it is the block whose path crosses every decode between the verbs and
    this suite. Re-running the whole drive suite per Windows encoding shard
    would add about the suite's full runtime, beyond the CI wall-time budget.
    `_ascii_coverage_case` pins this paragraph to the stage table and to what
    the sweep's encoding pass does per platform."""
    _ascii_coverage_case(check)
    probe = subprocess.run(
        [sys.executable, "-c",
         "import locale; print(locale.getpreferredencoding(False))"],
        env=dict(os.environ, **ASCII_ENV), capture_output=True,
        encoding="utf-8", errors="replace", timeout=60)
    preferred = probe.stdout.strip()
    if preferred.lower().replace("_", "-") in _UTF8_NAMES or not preferred:
        check("tests/test_drive_phase.py: under a locale whose "
              "preferred encoding is ASCII, a drive whose verbs print non-ASCII "
              "text integrates and closes as it does under UTF-8 (COULD NOT "
              "SET UP: the child's preferred encoding under %r is %r, so this "
              "run would prove nothing)" % (ASCII_ENV, preferred), False)
        return
    out_dir = _harness.fixture_root("drive-ascii-")
    held = dict((k, os.environ.get(k)) for k in ASCII_ENV)
    try:
        os.environ.update(ASCII_ENV)
        # Under the block's own budget, which the sweep sets from the file's
        # timeout, so the re-run is reported by its own label before this block
        # is reported as not having finished at all.
        res = _harness.run_stage(
            os.path.abspath(__file__), ASCII_BLOCK, out_dir,
            timeout=max(1, _harness.stage_timeout()
                        - _harness.STAGE_TIMEOUT_MARGIN))
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _harness.remove_tree(out_dir)
    cases = (res["report"] or {}).get("cases") or []
    failed = [label[:120] for label, ok, _detail in cases if not ok]
    check("tests/test_drive_phase.py: under a locale whose "
          "preferred encoding is ASCII, a drive whose verbs print non-ASCII "
          "text integrates and closes as it does under UTF-8 (%s re-run with "
          "%r, preferred encoding %r: it reports its cases, and every one "
          "passes): %r"
          % (ASCII_BLOCK, ASCII_ENV, preferred,
             (len(cases), failed, res["why"],
              _harness.tail_bytes(res["err"], 600))),
          res["report"] is not None and bool(cases) and not failed)
    _integrate_ascii_case(check, preferred)
    _integrate_tail_case(check, preferred)
    _fixture_git_case(check, preferred)


def _integrate_ascii_verdict(argv, preferred):
    """`argv` run as a child under `ASCII_ENV`, judged as the integrate suite
    is judged: exit 0 and a tally whose every case passed.
    -> (label, ok, clipped stderr)."""
    done = subprocess.run(
        argv, env=dict(os.environ, **ASCII_ENV),
        capture_output=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=600)
    tally = re.findall(r"(\d+)/(\d+) cases passed", done.stdout)
    passed, total = (int(tally[-1][0]), int(tally[-1][1])) if tally else (0, 0)
    err = _harness.tail_bytes(done.stderr, 600)
    label = ("tests/test_drive_phase.py: under a locale whose "
             "preferred encoding is ASCII, the integrate suite runs whole and "
             "every case it reports passes (%s, %r, preferred encoding %r): %r"
             % (INTEGRATE_SUITE, ASCII_ENV, preferred,
                (done.returncode, passed, total, err)))
    return label, done.returncode == 0 and total > 0 and passed == total, err


def _integrate_ascii_case(check, preferred):
    """The integrate suite, whole, as a child under the same pinned locale: it
    exits 0 and its tally says every case it ran passed. The sweep's encoding
    pass also runs every suite under a legacy locale, but only where the sweep
    can pin one - it pins nothing on Windows and falls back to the stdio half
    where file names would turn non-UTF-8 - so this run is the one that holds
    on every platform this suite runs on."""
    suite = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         INTEGRATE_SUITE)
    label, ok, _err = _integrate_ascii_verdict(
        [sys.executable, suite, "--selftest"], preferred)
    check(label, ok)


# A child that fails the way the integrate suite once did on a CI runner: a
# long stretch of stderr, then the integrate suite's own `_run` raising on a
# git call. The verb is one no git has, so the call fails the same way inside
# a repository and outside one, and never touches whatever repository holds
# the scratch directory.
_TAIL_CHILD = (
    "import importlib.util, os, sys\n"
    "tests, scratch = sys.argv[1], sys.argv[2]\n"
    "sys.path.insert(0, tests)\n"
    "spec = importlib.util.spec_from_file_location(\n"
    "    'integrate_suite', os.path.join(tests, %r))\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(mod)\n"
    "sys.stderr.write('noise before the failure\\n' * 200)\n"
    "sys.stderr.flush()\n"
    "mod._run(scratch, 'no-such-verb')\n" % (INTEGRATE_SUITE,))
# The raised error's own line as `_run` must word it: git's message decoded,
# not the bytes repr of it.
_TAIL_NEEDLE = ("RuntimeError: git no-such-verb failed: git: 'no-such-verb' "
                "is not a git command")


def _integrate_tail_case(check, preferred):
    """A failing child is reported by the END of its stderr - where Python
    prints the exception that stopped it - and the integrate suite's `_run`
    words git's error as text. The fixture's head alone outruns the byte
    budget, so a report clipped from the front cannot hold the needle."""
    scratch = _harness.fixture_root("drive-tail-")
    try:
        label, ok, err = _integrate_ascii_verdict(
            [sys.executable, "-c", _TAIL_CHILD,
             os.path.dirname(os.path.abspath(__file__)), scratch], preferred)
    finally:
        _harness.remove_tree(scratch)
    check("tests/test_drive_phase.py: a child suite that fails "
          "under the pinned locale is reported by the tail of its stderr, so "
          "the raised error's own line is in the message: %r"
          % ((ok, err[-300:]),),
          not ok and _TAIL_NEEDLE in err and repr(err) in label
          and len(err.encode("utf-8")) <= 600)


# A child that fails the way the fm-block re-run did on a CI runner: a long
# stretch of stderr, then a fixture's git call raising through the helper.
_GIT_CHILD = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import _harness\n"
    "sys.stderr.write('noise before the failure\\n' * 200)\n"
    "sys.stderr.flush()\n"
    "_harness.git(sys.argv[2], 'no-such-verb')\n")
# Built rather than written, so this block's own text cannot satisfy or trip
# the reading of the locale-pinned reporters below.
_HEAD_CLIP = "clip" + "_bytes("
_TAIL_REPORTERS = ("_harness.tail_" + 'bytes(res["err"], ',
                   "_harness.tail_" + "bytes(done.stderr, ")


_CHECKED_RUNNERS = ("run", "check_call", "check_output")


def _names_git(node, bound=()):
    """Whether a command expression spells git: the literal word, a name or
    attribute ending in git in either case - `GIT`, `_GIT`, a local `git` list
    - or a name `bound` holds, one assigned from an expression that spells it."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == "git":
            return True
        if isinstance(sub, ast.Name) and (sub.id.lower().endswith("git")
                                          or sub.id in bound):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr.lower().endswith("git"):
            return True
    return False


def _git_bound_names(tree):
    """Every name the module assigns from an expression spelling git, followed
    through chains of assignment - so `cmd = ["git", "init"]` and a second
    name copied from it are both read as git."""
    bound = set()
    while True:
        more = set(t.id for node in ast.walk(tree)
                   if isinstance(node, ast.Assign) and _names_git(node.value, bound)
                   for t in node.targets
                   if isinstance(t, ast.Name) and t.id not in bound)
        if not more:
            return bound
        bound |= more


def _subprocess_spellings(tree):
    """`(module names, {local name: runner})`: `subprocess` itself and every
    alias it is imported as, and which of its checked runners are imported
    bare."""
    modules, direct = {"subprocess"}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= set(a.asname or a.name for a in node.names
                           if a.name == "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            direct.update((a.asname or a.name, a.name) for a in node.names
                          if a.name in _CHECKED_RUNNERS)
    return modules, direct


def _runner_of(func, modules, direct):
    """The subprocess runner a call's `func` names, or None."""
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id in modules):
        return func.attr
    if isinstance(func, ast.Name):
        return direct.get(func.id)
    return None


def bare_git_calls(source):
    """The line of every checked git call in `source` that bypasses the fixture
    helper, sorted: `run(<git ...>, check=True)`, `check_call` or
    `check_output` on `subprocess` under any name it is imported as - a call
    whose failure would raise without git's own message. A `run` with no
    `check` reads its own exit and is not one."""
    tree = ast.parse(source)
    modules, direct = _subprocess_spellings(tree)
    bound = _git_bound_names(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        runner = _runner_of(node.func, modules, direct)
        checked = runner in ("check_call", "check_output") or (
            runner == "run"
            and any(kw.arg == "check" and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True for kw in node.keywords))
        if checked and _names_git(node.args[0], bound):
            found.append(node.lineno)
    return sorted(found)


def tests_dir_git_bypasses(tests_dir):
    """`(scanned file names, {file: lines})` over every `.py` in `tests_dir`:
    the set is the directory's, so a suite added later is read too."""
    names = sorted(n for n in os.listdir(tests_dir) if n.endswith(".py"))
    bare = {}
    for name in names:
        with open(os.path.join(tests_dir, name), "r", encoding="utf-8") as fh:
            lines = bare_git_calls(fh.read())
        if lines:
            bare[name] = lines
    return names, bare


def _fixture_git_case(check, preferred):
    """A fixture git call that fails raises with git's own message and the argv,
    one that hangs names its timeout, a child failing in one under the pinned
    locale is reported by the tail that holds the raised line, no pinned child
    is reported by its head, and no suite in the tests directory reaches git
    around the helper."""
    here = os.path.dirname(os.path.abspath(__file__))
    scratch = _harness.fixture_root("drive-fixture-git-")
    try:
        failed, said = _harness.attempt(_harness.git, scratch, "no-such-verb")
        hung, waited = _harness.attempt(
            _harness.git, scratch, "status",
            prefix=(sys.executable, "-c", "import time; time.sleep(30)"),
            timeout=1)
        _label, ok, err = _integrate_ascii_verdict(
            [sys.executable, "-c", _GIT_CHILD, here, scratch], preferred)
    finally:
        _harness.remove_tree(scratch)
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as fh:
        pinned = _harness.between(fh.read(), 'ASCII_BLOCK = "fm-block"',
                                  "def _stage_cases(")
    heads = pinned.count(_HEAD_CLIP)
    tails = [r for r in _TAIL_REPORTERS if r not in pinned]
    check("tests/test_drive_phase.py: a fixture git call that "
          "fails raises with git's own decoded message, and every "
          "locale-pinned child case reports the tail of the child's stderr, "
          "through one helper each (the failing call's message, the hung "
          "call's, the pinned child's reported tail, head clips and missing "
          "tail reporters in the pinned-child block): %r"
          % ((said, waited, err[-300:], heads, tails),),
          not failed and _TAIL_NEEDLE in said and "(exit " in said
          and not hung and "did not finish within 1s" in waited
          and not ok and _TAIL_NEEDLE in err
          and len(err.encode("utf-8")) <= 600
          and heads == 0 and tails == [])
    scanned, bare = tests_dir_git_bypasses(_harness.TESTS_DIR)
    # Each call in the twin is one spelling: the calls on lines 2, 4, 5, 7 and
    # 10 are checked git calls (an alias, a bare `check_output`, `check_call`,
    # a local lower-case prefix, a name copied from one assigned a git argv);
    # the last three lines are not (an unchecked run, a checked run of
    # something else, the helper). A scan reporting every call fails the
    # second half; the old reading - `subprocess.run` and an upper-case prefix
    # only - fails the first.
    wide = ("import subprocess as _sp\n"
            "_sp.run(['git', 'init'], check=True)\n"
            "from subprocess import check_output as co\n"
            "co(['git', 'rev-parse', 'HEAD'])\n"
            "_sp.check_call(['git', 'add', '-A'])\n"
            "git = ['git', '-c', 'user.name=t']\n"
            "_sp.run(git + ['commit'], check=True)\n"
            "_ini = ['git', 'init', '-q']\n"
            "again = _ini\n"
            "_sp.run(again, cwd=root, check=True)\n"
            "_sp.run(_ini, cwd=root)\n"
            "_sp.run([sys.executable, 'x.py'], check=True)\n"
            "_harness.git(root, 'add', '-A')\n")
    check("the case P125-R156 asks for, locking the behaviour at HEAD (every "
          ".py in the tests directory is read - the set is the directory's, "
          "not a list - and none reaches git through a checked subprocess "
          "call around the fixture helper; a twin spelling each shape the "
          "scan must read is reported on exactly those lines: %d file(s) "
          "scanned, bypasses %r, twin %r)"
          % (len(scanned), bare, bare_git_calls(wide)),
          len(scanned) > 10 and "test_drive_phase.py" in scanned
          and "_harness.py" in scanned and bare == {}
          and bare_git_calls(wide) == [2, 4, 5, 7, 10])
    twin = ("subprocess.run(_GIT + argv, cwd=root, check=True)\n"
            "subprocess.run(['git', '-C', root, 'add', '-A'], check=True)\n"
            "subprocess.run(_GIT + argv, cwd=root, capture_output=True)\n"
            "subprocess.run([sys.executable, 'x.py'], check=True)\n"
            "_harness.git(root, 'add', '-A')\n")
    check("fg1m RED TWIN: a checked `subprocess.run` naming git through a "
          "prefix or the literal word is reported by line, while an unchecked "
          "git call, a checked call of anything else and the helper are not: %r"
          % (bare_git_calls(twin),),
          bare_git_calls(twin) == [1, 2])


# --- a phase brief past the reader's budget ------------------------------------
SLICE_CLAUSE = ("tests/test_drive_phase.py: a phase brief past the "
                "reader budget is written as task-boundary slices with the header "
                "and owed lines each, one reviewer is dispatched per slice, and "
                "their returns aggregate into the one filed return")
_SLICE_DISPATCH = re.compile(r"^dispatch \S+ (\S+)(?: slice (\d+)/(\d+))? "
                             r"model=\S+ brief=(\S+)", re.M)
_SLICE_SECTION = re.compile(r"^## (P1\.\d+) ", re.M)
_SLICE_OWED = re.compile(r"^owed: (\S+)$", re.M)
_SLICE_FLAG = re.compile(r" --slice (\d+)/(\d+)")


def _inflate(root, mpath, size):
    """Give every task a description of about `size` bytes and commit the
    plan, so a phase brief that embeds each task's claim outgrows the reader's
    budget. The filler is many short lines, as prose is, not one long one."""
    with open(mpath, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    for task in plan["phases"][0]["tasks"]:
        filler = "".join("filler line %05d of the %s record\n" % (n, task["id"])
                         for n in range(size // 40))
        task["description"] = task["description"] + "\n" + filler
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    for argv in (["add", "-A"], ["commit", "-qm", "long descriptions"]):
        _harness.git(root, *argv)


def _read_text(root, rel):
    with open(os.path.join(root, *rel.split("/")), "r", encoding="utf-8",
              newline="") as fh:
        return fh.read()


def _slice_entries(tasks, ids):
    return [{"id": tid, "commit": tasks[tid].get("commit"), "answer": "matches",
             "note": "as asked", "missing": [], "redFirst": "not-attempted",
             "redFirstBasis": "gate-only: no test is owed",
             "inheritedTests": "not-asked",
             "inheritedTestsBasis": "the gate is `true` and selects no test file"}
            for tid in ids]


def _file_slice(root, mpath, brief_text, entries_for=None, finding=True):
    """Play one slice reviewer: answer the tasks its brief owes and run the
    filing command it prints, `--slice` and `--shown` included. Returns
    `(code, text)`."""
    head = _HEAD_LINE.search(brief_text).group(1)
    shown = re.search(r" --shown (\S+)", brief_text)
    mark = _SLICE_FLAG.search(brief_text)
    owed = _SLICE_OWED.findall(brief_text)
    tasks = tasks_of(mpath)
    n = mark.group(1) if mark else "0"
    body = {"findings": ([{"id": 1, "severity": "low", "file": "src/f1.txt:1",
                           "issue": "slice %s finding" % (n,),
                           "resolution": "none"}] if finding else []),
            "intent": {"answer": "matches", "note": "slice %s as asked" % (n,)},
            "verdict": "findings" if finding else "clean",
            "tasks": _slice_entries(tasks, owed if entries_for is None
                                    else entries_for)}
    argv = ["submit", PHASE, "--role", "reviewer", mpath, "--project-dir", root,
            "--head", head]
    if mark:
        argv += ["--slice", "%s/%s" % (mark.group(1), mark.group(2))]
    if shown:
        argv += ["--shown", shown.group(1)]
    return _verb(root, DRIVER, argv, stdin=json.dumps(body))


def _slice_cases(check):
    """A phase whose brief outgrows the reader's budget: sliced at task
    boundaries, one reviewer per slice, one return filed once all are in."""
    def clause(detail):
        return "%s (%s)" % (SLICE_CLAUSE, detail)

    M, why = _load("drive_phase_sliced")
    if M is None:
        check(clause("the driver loads: %s" % (why,)), False)
        return
    lookup = _loader.load_script("audit-lookup.py", "lookup_sliced", cache=False)
    budget = lookup.PHASE_BRIEF_BUDGET

    # UNDER THE BUDGET, nothing is sliced: the over-fire twin, which goes red
    # for a driver that slices every phase.
    root, mpath = _repo("unsliced", per_task="phase")
    run = drive(M, root, mpath, phase_review=False)
    text = run["prints"][-1][1]
    lines = _SLICE_DISPATCH.findall(text)
    whole = _read_text(root, lines[0][3]) if lines else ""
    check(clause("a brief inside the budget is one dispatch, written whole, with "
                 "no slice named: %r" % ((lines, _SLICE_FLAG.findall(whole)),)),
          len(lines) == 1 and lines[0][1] == "" and _SLICE_FLAG.search(whole) is None
          and len(whole.encode("utf-8")) <= budget)

    root, mpath = _repo("sliced", per_task="phase")
    _inflate(root, mpath, budget * 6 // 10)
    run = drive(M, root, mpath, phase_review=False, cap=60)
    text = run["prints"][-1][1]
    sent = _SLICE_DISPATCH.findall(text)
    count = len(sent)
    briefs = [_read_text(root, brief) for _p, _k, _n, brief in sent]
    sizes = [len(b.encode("utf-8")) for b in briefs]
    sections = [_SLICE_SECTION.findall(b) for b in briefs]
    owed = [_SLICE_OWED.findall(b) for b in briefs]
    heads = set(_HEAD_LINE.search(b).group(1) for b in briefs if _HEAD_LINE.search(b))
    check(clause("one dispatch per slice, numbered 1 to N in one print, each brief "
                 "inside the budget and each holding the header (the question "
                 "and the head): %r" % ((count, [(k, n) for _p, k, n, _b in sent],
                                          sizes, heads),)),
          count >= 2
          and [(k, n) for _p, k, n, _b in sent]
          == [(str(i), str(count)) for i in range(1, count + 1)]
          and all(size <= budget for size in sizes) and len(heads) == 1
          and all("## The question" in b for b in briefs))
    flat = [tid for group in sections for tid in group]
    check(clause("every task section is in exactly one slice, a slice names the "
                 "tasks it owes, and the owed lines of all slices are the tasks "
                 "of the phase once each: %r" % ((sections, owed),)),
          sorted(flat) == sorted(TASKS) and sorted(sum(owed, [])) == sorted(TASKS)
          and all(sorted(a) == sorted(b) for a, b in zip(sections, owed)))
    check(clause("each slice prints its own filing command, keyed on its number: "
                 "%r" % ([_SLICE_FLAG.search(b).groups() if _SLICE_FLAG.search(b)
                          else None for b in briefs],)),
          count >= 2 and all(_SLICE_FLAG.search(b) and _SLICE_FLAG.search(b).groups()
                             == (str(i), str(count))
                             for i, b in enumerate(briefs, 1)))
    if count < 2:
        return

    # A slice that leaves its owed task out is refused and stores nothing.
    code, said = _file_slice(root, mpath, briefs[0], entries_for=[])
    project, config = _evio.project_config_for(mpath, root)
    evidence = _evio.evidence_dir(project, config)
    check(clause("a slice return missing an entry its slice owes is refused, "
                 "naming the task: %r" % ((code, said[:300]),)),
          code != 0 and owed[0][0] in said
          and _fr.phase_returns(evidence, PHASE) == [])
    # ...then the slices file, in turn, and only the last one files the review.
    filed = []
    for brief in briefs[:-1]:
        _file_slice(root, mpath, brief)
        filed.append(len(_fr.phase_returns(evidence, PHASE)))
    code, said = _file_slice(root, mpath, briefs[-1])
    returns = _fr.phase_returns(evidence, PHASE)
    body = returns[0][1] if len(returns) == 1 else {}
    answered = sorted(e.get("id") for e in (body.get("tasks") or []))
    ids = [f.get("id") for f in body.get("findings") or []]
    issues = sorted(f.get("issue") for f in body.get("findings") or [])
    check(clause("no return is filed while a slice is missing; the last slice "
                 "files ONE phase return answering every task once, with each "
                 "slice's finding kept under its own id and the verdict "
                 "`findings`: %r" % ((filed, code, len(returns), answered, ids,
                                      issues, body.get("verdict")),)),
          code == 0 and filed == [0] * len(filed) and len(returns) == 1
          and answered == sorted(TASKS) and len(set(ids)) == count == len(ids)
          and issues == sorted("slice %d finding" % (i,) for i in range(1, count + 1))
          and body.get("verdict") == "findings"
          and sorted(e.get("id") for e in body.get("shown") or [])
          == sorted(TASKS))
    # A slice filed twice is refused and the filed review stays as it was.
    code, said = _file_slice(root, mpath, briefs[0])
    check(clause("a second filing of a slice is refused: %r" % ((code, said[:200]),)),
          code != 0 and len(_fr.phase_returns(evidence, PHASE)) == 1)
    with _Env(root):
        said = []
        again = M.main(["next", PHASE, mpath, "--project-dir", root],
                       out=said.append)
    check(clause("the next `next` reads the aggregated return and prints the "
                 "triage over its findings: %r" % ("\n".join(said)[:200],)),
          again == 0 and instruction("\n".join(said)) == TRIAGE
          and "slice 1 finding" in "\n".join(said) + json.dumps(
              _phase_of(mpath).get("review")))


def _base_red_drive_cases(check):
    """The drive's two readers of a red the base carries: the serial pick puts
    the task fixing that suite first, and a gate-red decision names the base
    run and that task. Pure: the ledger read is the one seam replaced."""
    M, why = _load("drive_phase_base_red")
    if M is None:
        check("bb1 the driver loads", False, why)
        return
    suite = "tests/test_s.py"
    phase = {"id": PHASE, "status": "in_progress", "tasks": [
        {"id": "P1.1", "status": "pending", "files": ["a.py"]},
        {"id": "P1.2", "status": "pending", "files": ["b.py"]},
        {"id": "P1.3", "status": "pending", "files": ["c.py"],
         "tests": {"add": ["%s: the case that fixes it" % (suite,)]}}]}
    manifest = {"meta": {}, "phases": [phase]}
    picks = [M.next_task(manifest, phase, red)[0]["id"]
             for red in (None, [], [suite], ["tests/test_other.py"])]
    check("bb1 the serial pick takes the ready task fixing a suite red at base "
          "first, and id order otherwise - also when the red suite is one no "
          "task names: %r" % (picks,),
          picks == ["P1.1", "P1.1", "P1.3", "P1.1"])

    rows = [{"runId": "r-task", "ts": "2026-10-19T06:00:00Z", "taskId": "P1.1",
             _evio.BASE_RED_KEY: {"run": "r-base", "atBase": [suite],
                                  "introduced": [], "verdict": "base-only"}},
            {"runId": "r-none", "ts": "2026-10-19T06:10:00Z", "taskId": "P1.1",
             _evio.BASE_RED_KEY: {"run": None, "verdict": "no-base"}},
            {"runId": "r-plain", "ts": "2026-10-19T06:20:00Z", "taskId": "P1.1"},
            {"runId": "r-unread", "ts": "2026-10-19T06:30:00Z", "taskId": "P1.1",
             _evio.BASE_RED_KEY: {"run": None, "verdict": "unreadable",
                                  "basis": "could not read the ledger (denied)"}}]
    head = "b6252aae"
    clean = _tree_stamp.dirty_digest([])[0]
    dirty = _tree_stamp.dirty_digest([" M a.py"])[0]

    def _at_head(run_id, ts, task_id, digest):
        return {"runId": run_id, "ts": ts, "taskId": task_id,
                "testedState": {"head": head, "dirtyDigest": digest},
                "steps": [{"name": "unit", "exit": 1, "failingSuites": [suite],
                           "failingSuitesBasis": "the 1 suite file(s) pytest %s, "
                           "read from its lines" % (_evio.NAMED_FAILING,)}]}
    # Each ledger the HEAD reading is asked of: a dirty-tree red by another
    # task; a clean red by a task being ordered; a clean red by a third task.
    ledgers = ([_at_head("h-dirty", "2026-10-19T07:00:00Z", "P1.9", dirty)],
               [_at_head("h-own", "2026-10-19T07:00:00Z", "P1.3", clean)],
               [_at_head("h-clean", "2026-10-19T06:00:00Z", "P1.9", clean),
                _at_head("h-dirty", "2026-10-19T07:00:00Z", "P1.9", dirty)])
    real, real_head = M._evio.read_rows, M.git_head
    M.git_head = lambda _ctx: head
    try:
        ctx = {"project": "unused", "config": {}}
        M._evio.read_rows = lambda _p, _c=None: {"rows": rows}
        said = [M.base_red_why(ctx, "evidence: recorded %s\n" % (run,), manifest,
                               phase, phase["tasks"][0])
                for run in ("r-task", "r-none", "r-plain", "r-unread")]
        at_head = []
        for ledger in ledgers:
            M._evio.read_rows = lambda _p, _c=None, _l=ledger: {"rows": _l}
            at_head.append(M.red_at_base(ctx, ["P1.1", "P1.2", "P1.3"]))
        # A newer clean run of ANOTHER gate, red on a suite of its own: the
        # reading filters by the gate's step names, as `run-test-gate.base_red`
        # does, so the older run of the gate in question is the one read.
        other_gate = dict(_at_head("h-lint", "2026-10-19T08:00:00Z", "P1.9", clean),
                          steps=[{"name": "lint", "exit": 1,
                                  "failingSuites": ["tests/test_lint.py"],
                                  "failingSuitesBasis": "the 1 suite file(s) "
                                  "pytest %s, read from its lines"
                                  % (_evio.NAMED_FAILING,)}])
        mixed = [_at_head("h-unit", "2026-10-19T06:00:00Z", "P1.9", clean),
                 other_gate]
        M._evio.read_rows = lambda _p, _c=None: {"rows": mixed}
        try:
            by_name = [M.red_at_base(ctx, ["P1.1"], names)
                       for names in (["unit"], None)]
        except TypeError as exc:
            by_name = ["red_at_base takes no step names: %s" % (exc,)]
        gated = dict(phase, testGate=["unit"])
        names_of = getattr(M, "gate_step_names", None)
        step_names = (names_of({"meta": {}, "phases": [gated]}, gated, ["P1.1"])
                      if names_of else None)
    finally:
        M._evio.read_rows, M.git_head = real, real_head
    check("bb5 the HEAD reading filters by the gate's step names as the "
          "gate-red reading does: a newer clean run of another gate is passed "
          "over for the gate's own, and the drive's callers name the gate's "
          "entries: %r, names %r" % (by_name, step_names),
          by_name == [([suite], "h-unit"), (["tests/test_lint.py"], "h-lint")]
          and step_names == ["unit"])
    check("bb3 the HEAD reading the pick orders by takes only a run on a clean "
          "tree at HEAD, never a candidate task's own run: %r" % (at_head,),
          at_head == [([], None), ([], None), ([suite], "h-clean")])
    check("bb4 a gate-red decision over a ledger that would not read says it "
          "could not read the ledger, not that no base run was recorded: %r"
          % (said[3:],),
          said[3:] == ["; could not read the ledger"])
    check("bb2 a gate-red decision over a red the base carries names the base run "
          "and the ready task to run first, says when no base run was recorded, "
          "and adds nothing for a row with no base reading: %r" % (said,),
          said[0].startswith("; run P1.3 first; red at base too: %s" % (suite,))
          and "r-base" in said[0]
          and said[1] == "; no base run recorded" and said[2] == "")


def _next_text(M, root, mpath):
    """`(code, text)` of one plain `next` of the phase."""
    said = []
    with _Env(root):
        code = M.main(["next", PHASE, mpath, "--project-dir", root],
                      out=said.append)
    return code, "\n".join(said)


def _to_close(M, root, mpath):
    """Play the main loop up to the step that commits and closes P1.1: its
    executor and its reviewer have filed, nothing else has happened."""
    _next_text(M, root, mpath)
    _file_executor(root, mpath, "P1.1")
    _next_text(M, root, mpath)
    _file_reviewer(root, mpath, "P1.1")


def _after_verb(M, script, then):
    """Make `M.run_verb` run `then(code, out, err)` after every run of `script`;
    the replacement a result returns stands in for the verb's own. Returns the
    function to put back."""
    real = M.run_verb

    def wrapped(ctx, name, args, *rest, **kw):
        got = real(ctx, name, args, *rest, **kw)
        return then(*got) if name == script else got
    M.run_verb = wrapped
    return real


def _committed_close_cases(check):
    """A task whose work the drive committed, and whose close was then refused,
    closes on that commit at the next step: the commit step finds nothing left
    to commit, and the answer is neither no-change (a false outcome) nor retry
    (a writer paid to redo committed work). The sequence is stage 1's: the
    commit lands with its journal row, the close is refused over a stray file,
    the file is removed, and `next` is asked again."""
    M, why = _load("drive_phase_committed_close")
    if M is None:
        check("tcc1 the driver loads", False, why)
        return
    root, mpath = _repo("tcc", task_ids=TASKS[:1])
    _to_close(M, root, mpath)
    stray = os.path.join(root, "stray.txt")

    def leave_stray(code, out, err):
        # After the commit and before the close: a file nobody declares and the
        # plugin does not own, changed since the attempt began.
        if code == 0 and "committed" in out:
            _write_lf(stray, "a file the commit never saw\n")
        return code, out, err

    real = _after_verb(M, "commit-task-work.py", leave_stray)
    try:
        code1, text1 = _next_text(M, root, mpath)
    finally:
        M.run_verb = real
    carriers = _git_out(root, "log", "--format=%H", "--grep=Audit-Row: ").split()
    task = tasks_of(mpath).get("P1.1") or {}
    check("tcc1 the setup is the sequence stage 1 met: the commit landed carrying "
          "one Audit-Row, the close was refused over the stray file, and the "
          "task stands in progress with no commit recorded: %r"
          % ((code1, text1[-300:], carriers, task.get("status"),
              task.get("commit")),),
          code1 != 0 and os.path.isfile(stray) and len(carriers) == 1
          and task.get("status") == "in_progress" and not task.get("commit"))
    code2, text2 = _next_text(M, root, mpath)
    task2 = tasks_of(mpath).get("P1.1") or {}
    check("tcc2 while the stray file stays the close is refused again, in the "
          "verb's words, and no-change is not offered: %r"
          % ((code2, text2[-300:], task2.get("status")),),
          code2 != 0 and "no-change" not in text2
          and task2.get("status") == "in_progress" and not task2.get("commit"))
    os.remove(stray)
    head = _git_out(root, "rev-parse", "HEAD").strip()
    code3, text3 = _next_text(M, root, mpath)
    task3 = tasks_of(mpath).get("P1.1") or {}
    # The red for the defect: `decide no-change P1.1: the commit found nothing
    # to commit`, answered no-change|retry.
    check("tcc3 with the stray file removed, the next step closes the task on "
          "the commit that carries its row - not on no-change, not on retry: %r"
          % ((code3, text3[-400:], task3.get("status"), task3.get("commit"),
              carriers, head),),
          code3 == 0 and "closed P1.1 at %s" % (carriers[0][:7],) in text3
          and "no-change" not in text3 and "retry" not in text3
          and task3.get("status") == "done"
          and bool(task3.get("commit")) and len(carriers) == 1
          and carriers[0].startswith(str(task3.get("commit")))
          and head.startswith(str(task3.get("commit"))))

    # The twin that keeps the fix from firing on everything, with a REAL carrier:
    # the commit step makes the commit and reports nothing to commit, and a
    # withdrawal row then takes its row back (as the writer appends when the
    # commit it announced was not made). The commit stands in history carrying
    # its trailer, and the task still has no commit of its own - no-change is
    # the question it is asked. A step that listed every carrier would close it.
    root_n, mpath_n = _repo("tcc-none", task_ids=TASKS[:1])
    _to_close(M, root_n, mpath_n)

    def commit_then_withdraw(code, out, err):
        for row in M._journal_io.read_all(root_n):
            details = row.get("details") if isinstance(row, dict) else None
            nonce = (details or {}).get(M._invariants.NONCE_KEY)
            if nonce and details.get("taskId") == "P1.1":
                M._journal_io.append(root_n, {
                    "action": M._invariants.ACTION_COMMIT_WITHDRAWN,
                    "actor": {"via": "fixture"}, "target": "P1.1",
                    "summary": "the commit was refused",
                    "details": {"taskId": "P1.1", M._invariants.NONCE_KEY: nonce,
                                "reason": "a hook refused it"}})
        return 0, "nothing to commit\n", ""

    real = _after_verb(M, "commit-task-work.py", commit_then_withdraw)
    try:
        code_n, text_n = _next_text(M, root_n, mpath_n)
    finally:
        M.run_verb = real
    task_n = tasks_of(mpath_n).get("P1.1") or {}
    carriers_n = _git_out(root_n, "log", "--format=%H", "--grep=Audit-Row: ").split()
    check("tcc4 a task whose only carrier in the range is a commit its row "
          "withdrew is still asked no-change - the carrier is really in history: %r"
          % ((code_n, text_n[-300:], task_n.get("status"), carriers_n),),
          len(carriers_n) == 1
          and instruction(text_n) == ("decide", "no-change", None)
          and "no-change" in text_n and task_n.get("status") == "in_progress"
          and not task_n.get("commit"))

    # ...and the plain twin: a commit step that made no commit and left the work
    # in the tree is a task with no commit of its own.
    root_p, mpath_p = _repo("tcc-plain", task_ids=TASKS[:1])
    _to_close(M, root_p, mpath_p)
    real = M.run_verb

    def no_commit(ctx, name, args, *rest, **kw):
        if name == "commit-task-work.py":
            return 0, "nothing to commit\n", ""
        return real(ctx, name, args, *rest, **kw)
    M.run_verb = no_commit
    try:
        code_p, text_p = _next_text(M, root_p, mpath_p)
    finally:
        M.run_verb = real
    task_p = tasks_of(mpath_p).get("P1.1") or {}
    check("tcc5 a task that made no commit at all is still asked no-change: %r"
          % ((code_p, text_p[-300:], task_p.get("status")),),
          instruction(text_p) == ("decide", "no-change", None)
          and task_p.get("status") == "in_progress")


# --- own_commit, one filter at a time ----------------------------------------
# Each case below builds the one scenario in which exactly ONE condition of
# `own_commit` is what refuses, every other condition holding; `oc1` is the
# scenario with all of them holding, so a refusal elsewhere is not a fixture
# that can never close.
_OWN_EPOCH = 1760000000


def _own_stamp(offset):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_OWN_EPOCH + offset))


def _own_row(action, offset, **details):
    return {"action": action, "ts": _own_stamp(offset), "details": details}


def _own_start(offset, head, attempt=1):
    return _own_row("task.start", offset, taskId="P1.1", attempt=attempt,
                    commit=head)


def _own_nonce(offset, nonce):
    return _own_row("task.commit", offset, taskId="P1.1", commitNonce=nonce)


def _own_withdrawn(M, offset, nonce):
    return _own_row(M._invariants.ACTION_COMMIT_WITHDRAWN, offset, taskId="P1.1",
                    commitNonce=nonce)


def _own_task(**over):
    task = {"id": "P1.1", "status": "in_progress", "attempts": 1, "commit": None,
            "files": ["src/f1.txt"]}
    task.update(over)
    return task


def _own_made(root, nonce, text, subject="chore(P1.1): audit - the work",
              last=True, path="src/f1.txt"):
    """Commit `text` to `path` under `subject`, its `Audit-Row` line in the last
    paragraph (or, with `last` False, in a paragraph another follows). The SHA."""
    _write_lf(os.path.join(root, *path.split("/")), text)
    paragraphs = [subject, "Audit-Row: %s" % (nonce,)]
    if not last:
        paragraphs.append("Reviewed-by: a paragraph after the trailer")
    _harness.git(root, "add", "-A")
    argv = ["commit", "-q"]
    for paragraph in paragraphs:
        argv += ["-m", paragraph]
    _harness.git(root, *argv)
    return _head_of(root)


def _own_ask(M, root, task, rows):
    """`own_commit` over the repository `root` with `rows` as the journal."""
    ctx = {"project": root, "gitRoot": root, "config": None}
    real = M._journal_io.read_all
    M._journal_io.read_all = lambda project, config=None: list(rows)
    try:
        return M.own_commit(ctx, task)
    finally:
        M._journal_io.read_all = real


def _own_repo(prefix):
    root, _mpath = _repo(prefix, task_ids=TASKS[:1])
    return root, _head_of(root)


def _own_commit_cases(check):
    """`own_commit` closes on the attempt's own, still-present task commit and
    on nothing else. Every case but `oc1` expects None - the caller then keeps
    asking no-change - and names the condition it isolates."""
    M, why = _load("drive_phase_own_commit")
    if M is None:
        check("oc0 the driver loads", False, why)
        return

    root, base = _own_repo("oc1")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, base), _own_nonce(5, "n1")]
    got = _own_ask(M, root, _own_task(), rows)
    check("oc1 with every condition holding - a carrier of this attempt's row, "
          "its header, the trailer last, the newest commit to change a declared "
          "file - the commit is named: %r" % ((got, sha),),
          got is not None and got == sha)

    # RANGE: the start was recorded after the commit, so the span holds nothing.
    # The row is ordered after the start row and unwithdrawn, so only the span
    # refuses.
    root, base = _own_repo("oc2")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, sha), _own_nonce(5, "n1")]
    got = _own_ask(M, root, _own_task(), rows)
    check("oc2 a carrier before the head the attempt's start recorded is not the "
          "attempt's: %r" % ((got, sha),), got is None)

    # REOPEN AND RESTART with attempt 1's commit present: the second start
    # records a head past it.
    root, base = _own_repo("oc3")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, base), _own_nonce(5, "n1"),
            _own_start(100, sha, attempt=2)]
    got = _own_ask(M, root, _own_task(attempts=2), rows)
    check("oc3 a task reopened and restarted past attempt 1's commit has no "
          "commit of its own - no-change is still asked: %r" % ((got, sha),),
          got is None)

    # NONCES OF THIS ATTEMPT ONLY: the second start records a head OLDER than
    # attempt 1's commit, so the commit is inside the span and only the
    # attempt's own rows can tell it is not this attempt's.
    root, base = _own_repo("oc4")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, base), _own_nonce(5, "n1"),
            _own_start(100, base, attempt=2)]
    got = _own_ask(M, root, _own_task(attempts=2), rows)
    check("oc4 a row written before the current attempt's start names no commit "
          "of it, though the commit stands in the span: %r" % ((got, sha),),
          got is None)

    # ANCESTRY: the recorded head survives off HEAD's history (a rebase or a
    # reset since); `head..HEAD` over it lists every commit since the merge
    # base, the carrier among them.
    root, base = _own_repo("oc5")
    branch = _git_out(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    _harness.git(root, "checkout", "-q", "--detach", base)
    _write_lf(os.path.join(root, "src", "f2.txt"), "side\n")
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "a commit off the branch")
    off = _head_of(root)
    _harness.git(root, "checkout", "-q", branch)
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, off), _own_nonce(5, "n1")]
    got = _own_ask(M, root, _own_task(), rows)
    check("oc5 a start head that is no ancestor of HEAD bounds no span: the "
          "carrier past the merge base is not named: %r" % ((got, sha, off),),
          got is None)

    # REVERT: the carrier's change was taken back, and closing on it would
    # record work that is not in the tree.
    root, base = _own_repo("oc6")
    sha = _own_made(root, "n1", "v1\n")
    _harness.git(root, "revert", "--no-edit", sha)
    rows = [_own_start(0, base), _own_nonce(5, "n1")]
    got = _own_ask(M, root, _own_task(), rows)
    check("oc6 a carrier whose change a later commit reverted is not named: %r"
          % ((got, sha, _git_out(root, "log", "--format=%s", "-3")),),
          got is None)
    # ...and the allow case for it: a later commit that changes only a file no
    # task declares leaves the carrier the newest to touch a declared one.
    root, base = _own_repo("oc6b")
    sha = _own_made(root, "n1", "v1\n")
    _write_lf(os.path.join(root, "src", "f2.txt"), "another task's file\n")
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-qm", "chore(P1.2): audit - elsewhere")
    got = _own_ask(M, root, _own_task(), [_own_start(0, base), _own_nonce(5, "n1")])
    check("oc6b a later commit that leaves the declared files alone does not "
          "hide the carrier: %r" % ((got, sha),), got == sha)

    # HEADER: a carrier is the task commit only under the task commit's header.
    for tag, subject in (("squash", "Squashed work of several tasks"),
                         ("other", "chore(P1.2): audit - another task's header")):
        root, base = _own_repo("oc7-" + tag)
        sha = _own_made(root, "n1", "v1\n", subject=subject)
        got = _own_ask(M, root, _own_task(),
                       [_own_start(0, base), _own_nonce(5, "n1")])
        check("oc7-%s a carrier whose subject does not open with this task's "
              "header is not named: %r" % (tag, (got, sha)), got is None)

    # LAST PARAGRAPH: a message that absorbed the trailer in its middle.
    root, base = _own_repo("oc8")
    sha = _own_made(root, "n1", "v1\n", last=False)
    got = _own_ask(M, root, _own_task(), [_own_start(0, base), _own_nonce(5, "n1")])
    check("oc8 a carrier with the Audit-Row line in a paragraph another follows "
          "is not named: %r" % ((got, sha),), got is None)

    # WITHDRAWN: the row was taken back, the commit it announced was not made.
    root, base = _own_repo("oc9")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, base), _own_nonce(5, "n1"), _own_withdrawn(M, 6, "n1")]
    got = _own_ask(M, root, _own_task(), rows)
    check("oc9 a carrier of a nonce a withdrawal row took back is not named: %r"
          % ((got, sha),), got is None)

    # RECORDED COMMIT and STATUS: a closed (or not started) task is nobody's
    # to close; the carrier is otherwise exactly oc1's.
    root, base = _own_repo("oc10")
    sha = _own_made(root, "n1", "v1\n")
    rows = [_own_start(0, base), _own_nonce(5, "n1")]
    recorded = _own_ask(M, root, _own_task(commit="abc1234"), rows)
    pending = _own_ask(M, root, _own_task(status="pending"), rows)
    check("oc10 a task with a recorded commit, or one not in progress, is "
          "named no commit though a carrier stands in its range: %r"
          % ((recorded, pending, sha),), recorded is None and pending is None)

    # CANNOT TELL: no start head, a start row of another attempt, no readable
    # journal - none of them a licence to name a commit.
    root, base = _own_repo("oc11")
    sha = _own_made(root, "n1", "v1\n")
    nonce_only = [_own_nonce(5, "n1")]
    other_attempt = [_own_start(0, base, attempt=2), _own_nonce(5, "n1")]
    no_head = [_own_row("task.start", 0, taskId="P1.1", attempt=1),
               _own_nonce(5, "n1")]
    got = [_own_ask(M, root, _own_task(), rows)
           for rows in (nonce_only, other_attempt, no_head)]
    real = M._journal_io.read_all

    def unreadable(project, config=None):
        raise OSError("the journal is gone")
    M._journal_io.read_all = unreadable
    try:
        got.append(M.own_commit({"project": root, "gitRoot": root, "config": None},
                                _own_task()))
    finally:
        M._journal_io.read_all = real
    check("oc11 a start that names no head of this attempt, or a journal that "
          "cannot be read, names no commit: %r" % ((got, sha),),
          got == [None, None, None, None])


def _stage_cases(check):
    """The stages cover every block once, the fixture's hand-written identity
    is one git reads, and every file the drive and this suite open as text,
    or read a subprocess's text from, names its encoding."""
    scanned = {}
    for rel, path in (("governance/%s" % (DRIVER,), _loader.script_path(DRIVER)),
                      ("tests/test_drive_phase.py", os.path.abspath(__file__))):
        with open(path, "r", encoding="utf-8") as fh:
            scanned[rel] = ["%s:%d" % (rel, line)
                            for line in unencoded_text_opens(fh.read())]
    found = [site for rel in sorted(scanned) for site in scanned[rel]]
    # Each line of the twin is one shape: lines 1-3 and 6 must be reported
    # (a write, an append, a bare read, a keyword mode), lines 4, 5 and 7 must
    # not (binary, an encoding named, `io.open` with one). A check reporting
    # every open fails the second half; one reporting none fails the first.
    twin = ("a = open(p, 'w')\n"
            "b = open(p, 'a', newline='')\n"
            "c = open(p)\n"
            "d = open(p, 'wb')\n"
            "e = open(p, 'w', encoding='utf-8')\n"
            "f = io.open(p, mode='w')\n"
            "g = io.open(p, 'r', encoding='utf-8', newline='')\n")
    twin_lines = unencoded_text_opens(twin)
    check("tests/test_drive_phase.py: every file the drive and its "
          "fixtures write in text mode names its encoding (a write without one "
          "is reported by file and line) (and a text-mode read too, which "
          "misreads UTF-8 the same way): %r" % ((found, twin_lines),),
          sorted(scanned) == ["governance/%s" % (DRIVER,),
                              "tests/test_drive_phase.py"]
          and found == [] and twin_lines == [1, 2, 3, 6])
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as fh:
        src = fh.read()
    got = _harness.stage_reach(src, STAGES)
    check("sb1 every case block of this file runs in exactly one stage - none "
          "left out of `STAGES`, none run both as a stage and by its old "
          "caller: %r" % (got,),
          got == {"orphans": [], "doubled": []})
    twin = ("def _a_cases(check):\n    _b_cases(check)\n\n\n"
            "def _b_cases(check):\n    pass\n\n\n"
            "def _c_cases(check):\n    pass\n")
    bad = _harness.stage_reach(twin, (("a-block", "_a_cases"), ("b-block", "_b_cases")))
    good = _harness.stage_reach(twin, (("a-block", "_a_cases"), ("c-block", "_c_cases")))
    check("sb1m RED TWIN: a block lifted into a stage while its caller still "
          "calls it reads as doubled, a block no stage reaches as an orphan - "
          "and the same blocks staged once each read clean: %r" % ((bad, good),),
          bad == {"orphans": ["_c_cases"], "doubled": ["_b_cases"]}
          and good == {"orphans": [], "doubled": []})
    root, _mpath = _repo("identity", task_ids=TASKS[:1])
    said = dict((key, _git_out(root, "config", "--local", "--get", key).strip())
                for key in ("user.email", "user.name", "commit.gpgsign"))
    check("fx1 a fixture repository's own config, written after `init` rather "
          "than through `git config`, is what git reads back: %r" % (said,),
          said == {"user.email": "fixture@example.com", "user.name": "Fixture",
                   "commit.gpgsign": "false"})


if __name__ == "__main__":
    safe_stdio()
    raise SystemExit(_harness.staged_main(sys.argv[1:], STAGES, globals(),
                                          "drive-stages-"))
