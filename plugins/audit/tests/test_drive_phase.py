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
`_harness.staged_main`, shared with every staged suite. `--stage` still runs the
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
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

import _harness                                   # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path, load_script)
import _manifest_io as _mio                        # noqa: E402  (load_manifest, tasks_by_id)
import _evidence_io as _evio                       # noqa: E402  (read_rows, project_config_for)
import _filed_returns as _fr                       # noqa: E402  (return_path)

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
          phase_gate=None):
    """A committed repository holding the plan, one source file per task, and
    a `.gitignore` for the driver's and the briefs' state directory. `per_task`
    is `review.perTask`: `always` is the reviewer-per-task drive most cases here
    are about, and the `dk` cases drive the other two readings. `phase_gate`
    is the phase's own `testGate` when it differs from the tasks' gate."""
    root = os.path.realpath(_harness.fixture_root("drive-%s-" % (prefix,)))
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    os.makedirs(os.path.join(root, "src"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json",
                   "review": {"perTask": per_task}}, fh)
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
# answers an argument-less `time.gmtime()` - the stamp a verb writes - with one
# fixed second, and leaves every other clock reading alone. A child, because the
# verbs the driver calls are processes of their own and an in-process patch
# would never reach them.
_PINNED_GMTIME = (
    "import time as _time\n"
    "_real_gmtime = _time.gmtime\n"
    "def _pinned_gmtime(secs=None):\n"
    "    return _real_gmtime(%d if secs is None else secs)\n"
    "_time.gmtime = _pinned_gmtime\n")


@contextlib.contextmanager
def _pinned_clock(at):
    """Every Python child started inside the block reads `time.gmtime()` as the
    epoch second `at`."""
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

    def watching_dispatch(ctx, state, phase, task, role):
        if role == "reviewer":
            gate_before[task["id"]] = _ledger_has_green(root, mpath, task["id"])
        return real_dispatch(ctx, state, phase, task, role)
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

    def watch_m(ctx, state, phase, task, role):
        if role == "reviewer":
            seen[task["id"]] = _ledger_has_green(root_m, mpath_m, task["id"])
        return real_m(ctx, state, phase, task, role)
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
    check("ds7g THE ALLOW TWIN: `--selftest` as the driver's own argument still "
          "prints its pointer and exits 0: %r" % ((code, text),),
          code == 0 and "has no inline --selftest" in text
          and "test_drive_phase.py" in text)

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
    label = ("plugins/audit/tests/test_drive_phase.py: a verb's stdin reaches "
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
          "and clears the block - and not `unblock`, which refuses it: %r"
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
               spare_file=False):
    """A two-task fixture whose config sets `executor.waveWidth` to `width`
    (left out when None) and roots task trees in a fixture directory of their
    own, and whose tasks' gates are the own-diff check - or a gate that always
    fails, for each id in `red`. `setup` is `executor.worktreeSetup`, and
    `spare_file` commits a third source file, for a task added later."""
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


def _file_wave_executor(root, mpath, task_id):
    """Play a wave executor: edit the task's file in ITS tree, then make the
    agent's last act from the project, as an agent's shell does."""
    tree = _tree_of(root, task_id)
    if not tree:
        return 99, "no tree recorded for %s" % (task_id,)
    rel = "src/f%d.txt" % (TASKS.index(task_id) + 1,)
    _write_lf(os.path.join(tree, *rel.split("/")), "changed by %s\n" % (task_id,))
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
    _code, second = _next_wave(M, root, mpath)
    after = _work_bytes(tree2) if tree2 and os.path.isdir(tree2) else {}
    return {"root": root, "mpath": mpath, "added": added, "sent": sent,
            "committed": committed, "tree2": tree2, "before": before,
            "after": after, "second": second, "gated": gated}


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
    check("wq2 the refresh touches record paths only - a member's work files are "
          "byte-identical before and after it: work=%r plan-ids=%r staged=%r"
          % (sorted(set(run["before"]) ^ set(run["after"]))
             or [p for p in run["before"] if run["before"][p] != run["after"].get(p)],
             ids, listed),
          tree2 and run["before"] and run["before"] == run["after"]
          and run["before"].get("src/f2.txt") == b"changed by P1.2\n"
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
    shutil.copytree(_output.SCRIPTS_DIR,
                    os.path.join(root, "plugins", "audit", "scripts"),
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
            tree, "plugins", "audit", "scripts", "_deps.py"), "--write-map"],
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
        shutil.rmtree(base, ignore_errors=True)


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
    os.makedirs(os.path.join(root, "tools"))
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    owner = [o for o in _evio.FOLLOWER_OWNERS if o.startswith("tools/")
             and o.endswith(".py")][0]
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
PINNED_320_DID = [
    "started P1.1",
    "gate P1.1 green; stamp current",
    "closed P1.1 at <sha>; started P1.2",
    "gate P1.2 green; stamp current",
    "closed P1.2 at <sha>",
    "phase gate green; invariants clean; signed off; committed <sha>; landed "
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
PINNED_320_ACTIONS = sorted([
    ("audit.state.committed", "phase.merged", "audit.state.committed"),
    ("task.start", "task.return.filed", "test.evidence.recorded",
     "task.testEvidence", "meta.evidenceSince", "audit.task.committed",
     "task.done", "task.start", "task.return.filed", "test.evidence.recorded",
     "task.testEvidence", "audit.task.committed", "task.done",
     "test.evidence.recorded", "phase.testEvidence", "phase.verdict"),
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

    # Both starts run under one pinned second, which is what a fast runner
    # does by accident: left to the real clock the retry usually lands a
    # second later and the case passes whatever the start's identity is.
    root, mpath = _repo("scope-retry", task_ids=TASKS[:1], per_task="phase")
    pin = int(time.time())
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
    check("sc4 a retry whose new start falls in the same second as the start it "
          "replaces dispatches the executor again and does not read the "
          "previous start's return, marks or brief: %r"
          % ((code, started, restarted, before, _attempts(mpath, "P1.1"),
              old_return, new_return, briefs, again[:300]),),
          started == time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pin))
          and instruction(again) == ("dispatch", "executor", "P1.1")
          and _attempts(mpath, "P1.1") == before + 1
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
    check("plugins/audit/tests/test_drive_phase.py: every event stream-cost reads "
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
    check("plugins/audit/tests/test_drive_phase.py: a brief read back that "
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
        check("plugins/audit/tests/test_drive_phase.py: the brief command parsed out "
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


_TALLY = "%s: %d/%d cases " + "passed"


def _house_suite(cases):
    """A house-style suite over `src/mine.py`: one line per `(label, cond)` and
    the tally, which is BUILT because a spelled one reads as a suite of its own."""
    body = ["import os, sys",
            "sys.path.insert(0, os.path.join(os.path.dirname("
            "os.path.abspath(__file__)), '..', 'src'))",
            "import mine", "results = []"]
    for label, cond in cases:
        body += ["ok = bool(%s)" % (cond,), "results.append(ok)",
                 "print('%%s %s' %% ('PASS' if ok else 'FAIL'))" % (label,)]
    body += ["n = sum(results)",
             "print(%r %% ('ALL PASS' if n == len(results) else 'SELFTEST FAILED',"
             " n, len(results)))" % (_TALLY,),
             "sys.exit(0 if n == len(results) else 1)"]
    return "\n".join(body) + "\n"


CARRY_CLAUSE = ("plugins/audit/tests/test_drive_phase.py: a pause with a filed "
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
    root, mpath = _wave_repo("carry", 2)
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
    solo, solo_path = _wave_repo("carrysolo", 2)
    _code, sent_first = _next_wave(M, solo, solo_path)
    code, text = _file_wave_executor(solo, solo_path, _dispatched(sent_first)[0])
    check(clause("with no origin the carry stays in a local ref and the filing "
                 "says it is local only: %r %r" % (text, _carry_refs(solo))),
          code == 0 and "local only: the repository has no origin" in text
          and _carry_refs(solo) == ["P1.1"])


STAGES = (("dp-block", "_drive_cases"), ("dpm-block", "_drive_mutant_cases"),
          ("dr-block", "_refusal_cases"),
          ("dd-block", "_decide_cases"), ("ct-block", "_continue_cases"),
          ("dd3-block", "_rerun_cases"), ("rs-block", "_resume_cases"),
          ("rrs-block", "_retry_reason_cases"),
          ("rm-block", "_rerun_measures_cases"),
          ("fx-block", "_fix_batch_cases"), ("ht-block", "_handed_triage_cases"),
          ("dt-block", "_single_task_cases"), ("dl-block", "_lock_stop_cases"),
          ("dk-block", "_key_cases"), ("ds-block", "_submit_cases"),
          ("dsm-block", "_submit_mutant_cases"), ("sg-block", "_signoff_cases"),
          ("sgf-block", "_signoff_findings_cases"),
          ("sq-block", "_advance_signoff_cases"),
          ("sq3-block", "_advance_refused_cases"),
          ("sa-block", "_review_answer_cases"),
          ("da-block", "_decline_answer_cases"),
          ("sr-block", "_redispatch_cases"), ("rr-block", "_reuse_review_cases"),
          ("lr-block", "_late_return_cases"),
          ("sf-block", "_fix_review_cases"),
          ("cv-block", "_converge_cases"), ("lf-block", "_low_fix_cases"),
          ("rc-block", "_round_cap_cases"), ("hr-block", "_risk_cases"),
          ("sh-block", "_standing_risk_cases"),
          ("rb-block", "_boot_cases"), ("db-block", "_decline_boot_cases"),
          ("gb-block", "_banner_cases"), ("dc-block", "_decline_coverage_cases"),
          ("dc4-block", "_reuse_gate_cases"), ("gr-block", "_stale_gate_cases"),
          ("gr4-block", "_stale_reaccept_cases"),
          ("di-block", "_decline_breach_cases"),
          ("of-block", "_open_finding_cases"),
          ("nf-block", "_landing_cases"), ("bk-block", "_blocked_cases"),
          ("cn-block", "_chain_next_cases"),
          ("wv-block", "_wave_cases"), ("wr-block", "_wave_red_sibling_cases"),
          ("wp-block", "_wave_parked_return_cases"),
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
          ("wt7-block", "_wave_review_discard_cases"),
          ("wd-block", "_wave_redo_cases"), ("wg-block", "_wave_regate_cases"),
          ("wh-block", "_wave_hooks_cases"),
          ("pf-block", "_preflight_cases"),
          ("tx-block", "_text_cases"),
          ("sn-block", "_signal_cases"), ("sn3-block", "_explain_cases"),
          ("sn5-block", "_signal_drive_cases"),
          ("bc-block", "_brief_crlf_cases"),
          ("ce-block", "_close_evidence_cases"),
          ("bs-block", "_brief_scope_cases"),
          ("sc-block", "_scope_change_cases"), ("fv-block", "_falsifier_cases"),
          ("fp-block", "_falsifier_producer_cases"),
          ("gt-block", "_git_stdin_cases"),
          ("ci-block", "_ci_cadence_cases"),
          ("cr-block", "_carry_cases"),
          ("sl-block", "_slice_cases"),
          ("sb-block", "_stage_cases"))


CI_CADENCE_CLAUSE = ("plugins/audit/tests/test_drive_phase.py: with ci.cadence "
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


EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
GIT_STDIN_CLAUSE = ("plugins/audit/tests/test_drive_phase.py: a fixture git call "
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


def _falsifier_cases(check):
    """The reviewer-brief ordering rule, the tests.add-vs-filed-return gap
    check, the contradicted-clause severity floor, and the falsifier-per-test
    run - the reviewer-brief ordering, the gap check and the severity floor
    this phase added, as pure functions over `drive-phase.py`."""
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
                                 "the viewport"],
                         "addMap": {"tests/test_y.py: isto": "test_y_case"}}}
    add_task["tests"]["add"].append("tests/test_y.py: isto")
    present = M.tests_add_gaps(
        add_task, ["once the card enters the viewport", "test_y_case"])
    mapped_only = M.tests_add_gaps(
        add_task, ["something unrelated", "test_y_case"])
    missing = M.tests_add_gaps(add_task, ["something unrelated"])
    check("fv3 a declared case matched by its own verbatim clause, or (across "
          "languages) by an explicit addMap entry, names no gap; one matched "
          "by neither is named by the drive: %r"
          % ((present, mapped_only, missing),),
          present == []
          and mapped_only == ["tests/test_x.py: once the card enters the "
                             "viewport"]
          and len(missing) == 2)

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

    root = _harness.fixture_root("falsifier-")
    try:
        src_dir = os.path.join(root, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "mine.py"), "w", encoding="utf-8") as fh:
            fh.write("def enters(margin):\n    return margin == 0\n")
        _preamble = ("import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname("
                    "os.path.abspath(__file__)), 'src'))\n"
                    "import mine\n")
        with open(os.path.join(root, "t_strict.py"), "w", encoding="utf-8") as fh:
            # The plan's own test: asserts BOTH the positive and the negative
            # case, so a mutant that blurs the boundary is caught.
            fh.write(_preamble + "assert mine.enters(0) is True\n"
                               "assert mine.enters(200) is False\n")
        with open(os.path.join(root, "t_weak.py"), "w", encoding="utf-8") as fh:
            # A test "renamed to near the viewport": asserts only the
            # positive case, so widening the margin never fails it - this is
            # a lazy-load test that cannot fail.
            fh.write(_preamble + "assert mine.enters(0) is True\n")
        mutation = {"file": "src/mine.py", "find": "margin == 0",
                   "replace": "True"}
        before = sorted(os.listdir(root))
        survived_status, survived_why = M.run_falsifier(
            [sys.executable, "t_weak.py"], root, mutation)
        after = sorted(os.listdir(root))
        killed_status, killed_why = M.run_falsifier(
            [sys.executable, "t_strict.py"], root, mutation)
        broken_status, broken_why = M.run_falsifier(
            [sys.executable, "t_strict.py"], root,
            {"file": "src/mine.py", "find": "def enters",
             "replace": "def enters(:::"})
        absent_status, absent_why = M.run_falsifier(
            [sys.executable, "t_strict.py"], root,
            {"file": "src/mine.py", "find": "no such text", "replace": "x"})
        check("fv5 a mutant the test cannot fail against is `survived`; one "
              "a real assertion catches is `killed`; a patch that will not "
              "even parse, or whose `find` names no real mutant, is "
              "`could-not-run` - never a kill either way; and the tree is "
              "byte-identical before and after every run: %r"
              % ((killed_status, survived_status, broken_status, absent_status,
                 killed_why, survived_why, broken_why, absent_why),),
              killed_status == "killed" and survived_status == "survived"
              and broken_status == "could-not-run"
              and absent_status == "could-not-run" and before == after)
    finally:
        _harness.remove_tree(root)
    _falsifier_drive_cases(check, M)


FALSIFIER_DRIVE_CLAUSE = ("a planned test that carries a 'must fail if' line has "
                          "it applied by the drive in a throwaway tree after "
                          "the executor files, and a test that still passes "
                          "under the mutation stops the close")
_FV_ADD = "src/f1.txt: the file says the task changed it"
# The planned test's own check, run from the copy's root: green while the file
# still opens with what the executor wrote, red once the mutation rewrites it.
_FV_STRICT = ("import sys; sys.exit(0 if open('src/f1.txt', encoding='utf-8')"
              ".read().startswith('changed') else 1)")


def _falsifier_repo(prefix, command, find="changed"):
    """A one-task drive whose task plans one test and carries its falsifier -
    `None` for `command` plans the test with no falsifier at all."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    with open(mpath, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    tests = plan["phases"][0]["tasks"][0]["tests"]
    tests["add"] = [_FV_ADD]
    if command is not None:
        tests["falsifiers"] = {_FV_ADD: {
            "file": "src/f1.txt", "find": find, "replace": "broken",
            "command": [sys.executable, "-c", command], "timeout": 60}}
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "commit", "-qam", "plan the falsifier")
    return root, mpath


def _falsifier_drive_cases(check, M):
    """The drive applies a task's declared falsifiers between the green gate
    and the close: a mutant the test survives, and one that could not be run,
    each stop the close as a decision; a killed one goes on to the close."""
    outcomes = {}
    for name, command, find in (("weak", "pass", "changed"),
                                ("strict", _FV_STRICT, "changed"),
                                ("absent", _FV_STRICT, "no such text"),
                                ("none", None, "changed")):
        root, mpath = _falsifier_repo("falsifier-%s" % (name,), command, find)
        _next(M, root, mpath)
        _file_executor(root, mpath, "P1.1")
        _code, text = _next(M, root, mpath)
        with open(os.path.join(root, "src", "f1.txt"), "r", encoding="utf-8") as fh:
            left = fh.read()
        outcomes[name] = (instruction(text)[1],
                          tasks_of(mpath).get("P1.1", {}).get("status"),
                          M.CLOSED in text, text, left, root, mpath)
    weak, strict, absent, none = (outcomes[n] for n in
                                  ("weak", "strict", "absent", "none"))
    check("%s (fv6: a test that exits 0 under its declared mutation is the "
          "`falsifier` decision naming `survived`, the task stays in progress "
          "and nothing is closed, and the executor's own file is untouched by "
          "the mutant; one the mutation turns red closes, its did-line naming "
          "the kill; a mutation whose `find` is not in the file is the same "
          "decision as `could-not-run`, never a pass; a task declaring no "
          "falsifier closes with no falsifier line at all: %r)"
          % (FALSIFIER_DRIVE_CLAUSE,
             [(n, o[0], o[1], o[2], o[3][:300], o[4])
              for n, o in sorted(outcomes.items())]),
          weak[0] == "falsifier" and weak[1] == "in_progress" and not weak[2]
          and "survived" in weak[3] and weak[4] == "changed by P1.1\n"
          and strict[1] == "done" and strict[2]
          and "falsifier" in strict[3] and "killed" in strict[3]
          and absent[0] == "falsifier" and absent[1] == "in_progress"
          and not absent[2] and "could-not-run" in absent[3]
          and none[1] == "done" and none[2] and "falsifier" not in none[3])
    _w0, _w1, _w2, _w3, _w4, root, mpath = weak
    _code, held = _next(M, root, mpath)
    _code, closed = _next(M, root, mpath, "--answer", "accept", "--reason",
                          "the weak test is known and tracked")
    check("fv7 the falsifier decision is held until answered, and `accept` "
          "with a reason goes on to the close: %r" % ((held[:300], closed[:300]),),
          instruction(held)[1] == "falsifier"
          and tasks_of(mpath).get("P1.1", {}).get("status") == "done"
          and "%s P1.1" % (M.CLOSED,) in closed)


FALSIFIER_PRODUCED_CLAUSE = (
    "a planned test's falsifier is produced in the normal flow - the "
    "executor's filed return declares it and the plan records it - and a "
    "survived or accepted falsifier leaves a durable record naming the mutated "
    "file and the test")
# The weak falsifier the executor declares: its command exits 0 whatever the
# file holds, so the mutant survives. A literal no other line of a note holds.
_FP_WEAK = {"file": "src/f1.txt", "find": "changed", "replace": "broken",
            "command": [sys.executable, "-c", "pass"], "timeout": 60}
_FP_REASON = "accepted-for-the-fixture: the weak test is tracked elsewhere"


def _producer_repo(prefix, mode, add):
    """A one-task drive whose task is graded `mode` and plans `add`, and whose
    plan declares no falsifier: whatever the plan holds afterwards was produced
    by the flow."""
    root, mpath = _repo(prefix, task_ids=TASKS[:1], per_task="phase")
    with open(mpath, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    tests = plan["phases"][0]["tasks"][0]["tests"]
    tests.update({"mode": mode, "expectRedFirst": mode == "tdd",
                  "add": list(add)})
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    _harness.git(root, "commit", "-qam", "plan the task")
    return root, mpath


def _notes_of(mpath, task_id):
    return [str(n.get("text") or "") for n in
            tasks_of(mpath).get(task_id, {}).get("notes") or []
            if isinstance(n, dict)]


def _falsifier_producer_cases(check):
    """The executor's filed return is the falsifier's producer: the plan
    records what it declares, the drive runs it, a survivor stops the close
    with a note on the task, and an accept leaves a second note carrying the
    reason. A task with no new test owes none and is told nothing."""
    M, why = _load("fp_mod")
    check("fp0 the driver loads: %r" % (why,), M is not None)
    if M is None:
        return
    clause = _FV_ADD.split(": ", 1)[1]
    root, mpath = _producer_repo("producer-tdd", "tdd", [_FV_ADD])
    _code, begun = _next(M, root, mpath)
    briefs = {"tdd": _brief_of(root, begun, "P1.1")}
    filed = _file_executor(root, mpath, "P1.1", {
        "testsAdded": [clause], "falsifiers": {_FV_ADD: _FP_WEAK}})
    _code, stopped = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    recorded = (task.get("tests") or {}).get("falsifiers")
    held_notes = _notes_of(mpath, "P1.1")
    _code, closed = _next(M, root, mpath, "--answer", "accept", "--reason",
                          _FP_REASON)
    after_notes = _notes_of(mpath, "P1.1")
    accepted = [n for n in after_notes if _FP_REASON in n]
    survived = [n for n in held_notes if "survived" in n]
    check("%s (fp1: the executor's `falsifiers` field lands in the task's "
          "tests.falsifiers, the drive runs it and the survivor is the "
          "`falsifier` decision with the task still in progress, a note naming "
          "the mutated file:line and the test entry is on the task before any "
          "answer, and `accept` closes with a second note carrying the reason: "
          "%r)" % (FALSIFIER_PRODUCED_CLAUSE,
                   (filed, recorded, instruction(stopped)[1],
                    task.get("status"), held_notes, after_notes,
                    tasks_of(mpath).get("P1.1", {}).get("status"))),
          filed[0] == 0
          and recorded == {_FV_ADD: _FP_WEAK}
          and instruction(stopped)[1] == "falsifier" and "survived" in stopped
          and task.get("status") == "in_progress"
          and len(survived) == 1 and "src/f1.txt:1" in survived[0]
          and _FV_ADD in survived[0]
          and len(accepted) == 1 and "src/f1.txt:1" in accepted[0]
          and _FV_ADD in accepted[0]
          and tasks_of(mpath).get("P1.1", {}).get("status") == "done"
          and "%s P1.1" % (M.CLOSED,) in closed)

    # The deny twin, for the over-fire mutation: a regression task that plans
    # no new test owes no falsifier, so it closes with no falsifier line, no
    # note and no tests.falsifiers - a gap line that fired on every task would
    # turn this red.
    for name, add, over in (("fp2", [], None),
                            ("fp2b", [_FV_ADD], {"testsAdded": [clause]})):
        root, mpath = _producer_repo("producer-%s" % (name,), "regression", add)
        _code, begun = _next(M, root, mpath)
        briefs[name] = _brief_of(root, begun, "P1.1")
        plain = _file_executor(root, mpath, "P1.1", over)
        _code, done = _next(M, root, mpath)
        task = tasks_of(mpath).get("P1.1", {})
        check("%s a regression task needs no falsifier (tests.add %r) - the "
              "mode, not the empty list, is what exempts it: it closes, nothing "
              "names a falsifier and nothing is recorded: %r"
              % (name, add, (plain, done[:400], task.get("notes"),
                             task.get("tests"))),
              plain[0] == 0 and task.get("status") == "done"
              and "falsifier" not in (plain[1] + done).lower()
              and not task.get("notes")
              and "falsifiers" not in (task.get("tests") or {}))

    # A tdd task whose return declares none is a recorded gap, not a stop.
    root, mpath = _producer_repo("producer-gap", "tdd", [_FV_ADD])
    _next(M, root, mpath)
    bare = _file_executor(root, mpath, "P1.1", {"testsAdded": [clause]})
    _code, gap = _next(M, root, mpath)
    task = tasks_of(mpath).get("P1.1", {})
    gaps = [n for n in _notes_of(mpath, "P1.1") if "no falsifier" in n]
    check("fp3 a tdd task whose return declares no falsifier for an added test "
          "is named at submit and recorded as a note naming the entry, and the "
          "close goes on: %r" % ((bare, gap[:400], task.get("notes")),),
          bare[0] == 0 and "no falsifier" in bare[1]
          and len(gaps) == 1 and _FV_ADD in gaps[0]
          and task.get("status") == "done")
    asks = dict((k, v.count("declare one in your return's `falsifiers`"))
                for k, v in briefs.items())
    check("fp4 the executor's brief asks a tdd task for its falsifiers, once, "
          "and asks a regression task for none - with or without a planned "
          "test: %r" % ((asks, dict((k, len(v)) for k, v in briefs.items())),),
          asks == {"tdd": 1, "fp2": 0, "fp2b": 0}
          and all(briefs.values()))


def unencoded_text_opens(source):
    """The line of every text-mode open or subprocess call in `source` that
    names no encoding, sorted - `_output`'s walker, the one the tree-wide lint
    runs over scripts/ and hooks/, asked of this suite's own source too."""
    return [line for line, _what in _output.unencoded_text_io(source)]


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
    check("plugins/audit/tests/test_drive_phase.py: the case P125-R147 asks "
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
    check("plugins/audit/tests/test_drive_phase.py: the case P125-R165 asks "
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
        check("plugins/audit/tests/test_drive_phase.py: under a locale whose "
              "preferred encoding is ASCII, a drive whose verbs print non-ASCII "
              "text integrates and closes as it does under UTF-8 (COULD NOT "
              "SET UP: the child's preferred encoding under %r is %r, so this "
              "run would prove nothing)" % (ASCII_ENV, preferred), False)
        return
    out_dir = _harness.fixture_root("drive-ascii-")
    held = dict((k, os.environ.get(k)) for k in ASCII_ENV)
    try:
        os.environ.update(ASCII_ENV)
        res = _harness.run_stage(os.path.abspath(__file__), ASCII_BLOCK, out_dir)
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _harness.remove_tree(out_dir)
    cases = (res["report"] or {}).get("cases") or []
    failed = [label[:120] for label, ok, _detail in cases if not ok]
    check("plugins/audit/tests/test_drive_phase.py: under a locale whose "
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
    label = ("plugins/audit/tests/test_drive_phase.py: under a locale whose "
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
    check("plugins/audit/tests/test_drive_phase.py: a child suite that fails "
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
    check("plugins/audit/tests/test_drive_phase.py: a fixture git call that "
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
SLICE_CLAUSE = ("plugins/audit/tests/test_drive_phase.py: a phase brief past the "
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
    check("plugins/audit/tests/test_drive_phase.py: every file the drive and its "
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
