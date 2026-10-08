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
"""
import json
import os
import re
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
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

_GIT = ["git", "-c", "user.email=fixture@example.com", "-c", "user.name=Fixture",
        "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


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
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json",
                   "review": {"perTask": per_task}}, fh)
    with open(os.path.join(root, ".gitignore"), "w") as fh:
        fh.write(".claude/state/\n")
    for n in range(1, len(task_ids) + 1):
        with open(os.path.join(root, "src", "f%d.txt" % (n,)), "w") as fh:
            fh.write("v0\n")
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    with open(mpath, "w") as fh:
        json.dump(_plan(task_ids, gate, phase_gate), fh, indent=2)
    # The identity is the repository's own, not only this call's: the verbs the
    # driver runs commit in it too, and a sweep pins HOME and refuses a guessed
    # identity, so nothing else would supply one.
    for argv in (["init", "-q"],
                 ["config", "user.email", "fixture@example.com"],
                 ["config", "user.name", "Fixture"],
                 ["config", "commit.gpgsign", "false"],
                 ["add", "-A"], ["commit", "-qm", "fixture"]):
        subprocess.run(_GIT + argv, cwd=root, check=True, capture_output=True,
                       timeout=60)
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

    def __enter__(self):
        names = list(self.PINNED) + list(self.DROPPED) + ["CLAUDE_PROJECT_DIR"]
        self.held = dict((n, os.environ.get(n)) for n in names)
        for name in self.DROPPED:
            os.environ.pop(name, None)
        os.environ.update(self.PINNED)
        os.environ["CLAUDE_PROJECT_DIR"] = self.root
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


def _verb(root, name, args, stdin=None):
    done = subprocess.run(_script(name) + args, cwd=root, input=stdin,
                          capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr


def _edit(root, task_id, text):
    """Write `text` into the task's own file: `src/f<n>.txt` for a fixture task,
    the first file the plan declares for any other - a fix task added in the
    drive."""
    if task_id in TASKS:
        rel = "src/f%d.txt" % (TASKS.index(task_id) + 1,)
    else:
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        rel = (tasks_of(mpath).get(task_id, {}).get("files") or ["src/f1.txt"])[0]
    with open(os.path.join(root, *rel.split("/")), "w") as fh:
        fh.write(text)


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
    return _verb(root, DRIVER, ["submit", task_id, "--role", "executor", mpath,
                                "--project-dir", root],
                 stdin=json.dumps(_executor_body(task_id, over)))


def _file_reviewer(root, mpath, task_id, answer="matches"):
    body = {"findings": [], "intent": {"answer": answer, "note": "as asked"},
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
    with open(os.path.join(root, *brief.group(1).split("/"))) as fh:
        head = _HEAD_LINE.search(fh.read()).group(1)
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
                                "--project-dir", root, "--head", head],
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
          entry_over=None, phase_intent="matches"):
    """Play the main loop until `done`, a stop, or `cap` calls.

    -> {"prints": [(code, text)], "steps": [instruction], "nexts", "dispatches"}
    `on_dispatch(role, task)` runs after the test filed that agent's return,
    for a case that changes the tree between two steps. `answer(kind, text)`
    gives the flags that answer a printed decision, None to run a plain `next`
    again, or False to stop there; `answer=None` stops at the first decision.
    With `phase_review` False the drive stops at the phase review's dispatch
    rather than filing it, and `findings` is what a filed one carries."""
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
                    _file_reviewer(root, mpath, tid)
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
          and "commit-task-work.py" in text.splitlines()[0])

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
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "docs/audit"],
                           cwd=root, capture_output=True, text=True).stdout
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
    echo_free = [t for _c, t in run["prints"] + again["prints"] + whole["prints"]
                 if "ado echo" in t]
    check("dt5 THE ALLOW TWIN: a plan with no board owes no ADO echo, and no print "
          "says one is owed: %r" % (echo_free,), echo_free == [])
    root_a, mpath_a = _repo("single-ado")
    with open(mpath_a) as fh:
        plan = json.load(fh)
    plan["meta"]["ado"] = {"organization": "o", "project": "p"}
    plan["phases"][0]["tasks"][1]["ado"] = {"id": 4242}
    with open(mpath_a, "w") as fh:
        json.dump(plan, fh, indent=2)
    subprocess.run(_GIT + ["commit", "-qam", "board"], cwd=root_a, check=True,
                   capture_output=True, timeout=60)
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
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _stamp_head(line):
    """The HEAD a stamp line names, or None."""
    try:
        return json.loads(str(line).split(":", 1)[1]).get("head")
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
          "filed with the stamp submit took, naming HEAD, in one line: %r"
          % ((code, text, filed.get("stamp")),),
          code == 0 and len(text.splitlines()) == 1 and "filed" in text
          and str(filed.get("stamp", "")).startswith("audit-stamp:")
          and _head(root).startswith(_stamp_head(filed.get("stamp")) or "-"))
    first = _read(path) if os.path.exists(path) else None
    code, text = _submit(None, root, mpath, "P1.1", _executor_body(
        "P1.1", {"outcome": {"technical": "a second claim",
                             "descriptive": "again"}}))
    check("ds3 a second filing is refused before anything runs, and the first "
          "stays byte-identical: %r" % (text,),
          code == 1 and "already filed" in text and "stamp taken" not in text
          and first is not None and _read(path) == first)

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
        with open(os.path.join(root, *rel.split("/")), "w") as fh:
            fh.write(text)
    with open(mpath, "w") as fh:
        json.dump(plan, fh, indent=2)
    subprocess.run(_GIT + ["add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(_GIT + ["commit", "-qm", "tdd"], cwd=root, check=True,
                   capture_output=True)
    with _Env(root):
        M.main(["next", PHASE, mpath, "--project-dir", root], out=[].append)
    with open(os.path.join(root, "src", "mine.py"), "w") as fh:
        fh.write("v = 2\n")
    with open(os.path.join(root, "tests", "test_mine.py"), "w") as fh:
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
            capture_output=True, text=True, timeout=120)
    path = _filed_path(mpath, "P1.1")
    check("ds9 the manifest a brief prints relative to the project is read from "
          "that project, whatever directory the agent's shell stands in: %r"
          % ((done_r.returncode, done_r.stdout + done_r.stderr),),
          done_r.returncode == 0 and os.path.exists(path)
          and not os.path.exists(os.path.join(elsewhere, "docs", "audit",
                                              "audit-plan.json")))

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
    code, text = _submit(None, root, mpath, PHASE, review, role="reviewer",
                         tail=["--head", head])
    code_2, text_2 = _submit(None, root, mpath, PHASE, review, role="reviewer",
                             tail=["--head", head])
    check("ds8 a phase review files through submit under --head, and a second "
          "filing for that head is the verb's refusal: %r" % ((text, text_2),),
          code == 0 and "filed" in text and code_2 == 1
          and "already answers P1.1" in text_2)


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
    mutant.submitted_shape = lambda role, body, fills: []
    root_m, mpath_m, _t = _started(mutant, "noshape")
    bad = _executor_body("P1.1")
    del bad["outcome"]
    code_m, text_m = _submit(mutant, root_m, mpath_m, "P1.1", bad)
    check("ds4m RED TWIN: a submit that does not check the shape first takes the "
          "stamp before the filing verb refuses, and ds4 catches it: %r"
          % (text_m,),
          code_m == 1 and "stamp taken" in text_m)


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
    return subprocess.run(_GIT + list(args), cwd=root, capture_output=True,
                          text=True).stdout


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
    with open(mpath) as fh:
        plan = json.load(fh)
    edit(plan)
    with open(mpath, "w") as fh:
        json.dump(plan, fh, indent=2)
    subprocess.run(_GIT + ["commit", "-qam", message], cwd=root, check=True,
                   capture_output=True, timeout=60)


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
    code, text = _next(M, root, mpath, "--answer", "sign-off", "--reason", SUMMARY)
    check("sa2 sign-off is refused while those answers wait on a human, and "
          "nothing is signed off: %r" % ((code, text),),
          code == M.E_USAGE and "accept" in text and not _signed(mpath))
    bare, _t = _next(M, root, mpath, "--answer", "accept")
    words = "the human: P1.1 was asked to edit f2 after all"
    code, text = _next(M, root, mpath, "--answer", "accept", "--reason", words)
    after = _answer_lines(text)
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


def _head_of_brief(root, rel):
    with open(os.path.join(root, *rel.split("/"))) as fh:
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
    check("bk1 a phase whose only task is blocked prints `decide stalled` with "
          "the rule naming the remedy - audit-task.py unblock with the human's "
          "reason: %r" % (last,),
          run["steps"][-1] == ("decide", "stalled", None)
          and "audit-task.py unblock" in last and "--reason" in last
          and len(last.encode("utf-8")) <= BOUND)
    single = drive(M, root, mpath, target="P1.1", cap=2)
    code, text = single["prints"][-1]
    check("bk2 the task drive's stop on the same blocked task names the same "
          "remedy, and no longer `start`, which refuses a task past its "
          "attempts: %r" % (text,),
          code == 1 and "audit-task.py unblock" in text
          and "audit-task.py start" not in text)


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


STAGES = (("dp-block", "_drive_cases"), ("dr-block", "_refusal_cases"),
          ("dd-block", "_decide_cases"), ("dd3-block", "_rerun_cases"),
          ("dt-block", "_single_task_cases"), ("dl-block", "_lock_stop_cases"),
          ("dk-block", "_key_cases"), ("ds-block", "_submit_cases"),
          ("dsm-block", "_submit_mutant_cases"), ("sg-block", "_signoff_cases"),
          ("sa-block", "_review_answer_cases"), ("sr-block", "_redispatch_cases"),
          ("sf-block", "_fix_review_cases"), ("hr-block", "_risk_cases"),
          ("rb-block", "_boot_cases"), ("gb-block", "_banner_cases"),
          ("nf-block", "_landing_cases"), ("bk-block", "_blocked_cases"),
          ("tx-block", "_text_cases"))


def _selftest(only=()):
    """Every stage, or only the ones `--stage <label>` names - a narrowed run
    for one block, which a red-first proof in a throwaway tree can afford."""
    unknown = [o for o in only if o not in dict(STAGES)]

    def body(check):
        if unknown:
            check("--stage names a block of this suite: %r" % (unknown,), False)
        for label, fn in STAGES:
            if not only or label in only:
                _harness.stage(check, label, globals()[fn])
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        args = sys.argv[1:]
        raise SystemExit(_selftest([args[i + 1] for i, a in enumerate(args[:-1])
                                    if a == "--stage"]))
    sys.stderr.write("usage: test_drive_phase.py --selftest [--stage LABEL ...]\n")
    raise SystemExit(2)
