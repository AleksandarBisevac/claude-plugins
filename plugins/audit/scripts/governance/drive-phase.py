#!/usr/bin/env python3
"""The step driver: a phase's run, with the main loop left only the judgement.

WHY IT EXISTS. A task used to take eight or more main-loop requests, and most of
them were a script's job done by the model: run a verb, read its output, type the
next command. The main loop is the dearest place in the pipeline to spend a round
trip, because every request re-reads everything the session has said. So one
entry point now does every step that is due and needs no judgement, and prints
exactly one instruction for the model:

  * `dispatch` - an agent type, the task, the model, and the brief file
    `audit-lookup.py brief` wrote;
  * `decide`   - a named decision with its options, answered with
    `next <phase> --answer <option>`;
  * `done`     - every task of the phase is closed.

The command body is the loop: run `next`, do what it prints, run `next` again.
A task then costs four requests - dispatch the executor, `next` (the recorded
gate, the stamp grade, the reviewer's brief), dispatch the reviewer, `next` (the
findings, the commit, the close, and the next task's start and brief).

EVERY STEP IS AN EXISTING VERB, CALLED AS A SUBPROCESS. An entry point may not
import another entry point, so each verb is resolved by basename through
`_loader.script_path` and run: `audit-lock.py`, `audit-task.py` (start, block,
finding, done), `audit-lookup.py brief`, `run-test-gate.py --record`,
`stamp-verification.py compare` and `commit-task-work.py`. Nothing here
re-decides what a verb decides; the driver reads exit codes and the one line a
verb prints, and a verb that refuses stops the drive with its own words printed
whole - the refusal and the remedy it names - and exit 1.

THE RECORDED GATE STAYS BEFORE THE REVIEWER. The reviewer reads the run the
driver recorded rather than making its own, which is why a task takes four
requests and not three: the gate cannot be folded into the reviewer's dispatch
without the reviewer being briefed before the measurement it is handed exists.

ONE TASK AT A TIME, IN ID ORDER, EVEN WHEN SEVERAL ARE READY. A recorded gate run
while sibling executors edit the same tree measures their half-finished work, and
a gate that must not overlap another run is the half of a wave that cannot be
parallel; `next_task` is the one place that choice is made.

WHAT THE DRIVER KEEPS: one file per phase under `stateDir/drive/`, holding what no
verb records - which brief it handed to an agent for which start, whether it
took the phase lock or was handed it, the findings it already filed, and the
decision it is waiting on. A decision printed once is printed again until it is
answered, so a `next` with no answer never walks past it. `done` releases the
lock only when this driver took it, and removes the file.

WHERE THE TEXT COMES FROM. Every line the model is shown is rendered from
`STEPS`, one entry per step, so the rule a step applies can be printed at that
step rather than read from a reference document beforehand.

WHERE THE PER-TASK REVIEWER IS DECIDED: `reviewer_due`, alone, from the task's
`review.perTask` - `always` dispatches it, `phase` never does (the close records
`deferred` and the phase review answers the task at sign-off, which refuses
until it has), `signals` only where `signals_fired` names a signal. Under every
key the recorded gate runs before the reviewer or the close.

Usage:
  drive-phase.py next <phaseId> [manifest] [--project-dir DIR]
                 [--answer OPTION] [--reason TEXT] [--verbose]

Exit codes:
  0  an instruction was printed - dispatch, decide or done
  1  a verb refused, or a filed return will not read: the drive stopped and the
     words that stopped it are printed
  2  usage error - no manifest, no such phase, an answer no pending decision
     offers, or an option that needs --reason given none

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_drive_phase.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _loader  # noqa: E402  (script_path: every verb resolved by basename, never
#                              loaded - the subprocess boundary is why no edge to
#                              any of them is counted by `_deps`; load_hooks_config
#                              for `stateDir`)
import _manifest_io as _mio  # noqa: E402  (loader, phase resolver, TERMINAL)
import _evidence_io as _evio  # noqa: E402  (project_config_for, evidence_dir)
import _filed_returns as _fr  # noqa: E402  (where a filed return lives, and its read;
#                                            the per-task review key a task holds)
import _config_rules  # noqa: E402  (review_per_task_mode: the config's reading now)
import _status_facts  # noqa: E402  (ready_tasks: the one readiness rule)

E_OK, E_STOPPED, E_USAGE = 0, 1, 2
PREFIX = "[drive-phase]"

# The bound every print that is not a stop stays inside. A stop prints a verb's
# own words whole, so it is the one print that may run longer.
INSTRUCTION_BYTES = 300

EXECUTOR_AGENT = "audit:audit-executor"
REVIEWER_AGENT = "audit:audit-reviewer"
DRIVE_DIRNAME = "drive"

# The words the did-line uses for a task the driver started or closed. They are
# what `did_tasks` reads back, and what `tools/stream-cost.py` reads a driver
# session's task cycle from - the driver's own start and close happen in its
# subprocesses, where the session's stream cannot see them.
STARTED, CLOSED = "started", "closed"


# --- the text of every step ------------------------------------------------------
# One entry per step: `line` is the instruction the model is shown, `rule` the
# lines of the rule that applies at that step, printed under it. A step whose
# rule is empty prints its line alone.
STEPS = {
    "dispatch-executor": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": ()},
    "dispatch-reviewer": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": ()},
    "decide-gate-red": {
        "line": "decide gate-red %(task)s: its recorded gate is red (%(why)s)",
        "rule": ()},
    "decide-no-executor-return": {
        "line": "decide no-executor-return %(task)s: the executor was dispatched "
                "and filed no return for this start",
        "rule": ()},
    "decide-no-reviewer-return": {
        "line": "decide no-reviewer-return %(task)s: the reviewer was dispatched "
                "and filed no return for this start",
        "rule": ()},
    "decide-high-risk": {
        "line": "decide high-risk %(task)s: risk is high, so a human confirms "
                "before its commit",
        "rule": ()},
    "decide-no-change": {
        "line": "decide no-change %(task)s: the commit found nothing to commit",
        "rule": ()},
    "decide-review-answer": {
        "line": "decide review-answer %(task)s: %(why)s - a human action item",
        "rule": ()},
    "decide-stalled": {
        "line": "decide stalled %(phase)s: no task is ready - %(why)s",
        "rule": ()},
    "answer": {
        "line": "answer: next %(phase)s --answer %(options)s%(reason)s",
        "rule": ()},
    "done": {
        "line": "done %(phase)s: every task is closed; sign-off is next",
        "rule": ()},
}

# Each decision's options, and the ones that need `--reason`. A decision with no
# options is one only the plan can change; nothing here answers it.
DECISIONS = {
    "gate-red": (("retry", "block"), ("block",)),
    "no-executor-return": (("retry", "block"), ("block",)),
    "no-reviewer-return": (("redispatch", "not-asked"), ("not-asked",)),
    "high-risk": (("confirm", "block"), ("block",)),
    "no-change": (("no-change", "retry"), ("no-change",)),
    "review-answer": (("continue",), ()),
    "stalled": ((), ()),
}


def step_text(name, **fields):
    """The lines one step prints: its line, then its rule."""
    entry = STEPS[name]
    return [entry["line"] % fields] + list(entry["rule"])


def did_tasks(text):
    """`{"started": [...], "closed": [...]}` - the tasks a driver's printed text
    says it started and closed, in order, read off its did-lines only."""
    found = {STARTED: [], CLOSED: []}
    pattern = re.compile(r"\b(%s|%s) (\S+?)(?=[;,\s]|$)" % (STARTED, CLOSED))
    for line in (text or "").splitlines():
        if not line.startswith(PREFIX):
            continue
        for word, task in pattern.findall(line):
            found[word].append(task)
    return found


# --- running a verb ----------------------------------------------------------------
def run_verb(ctx, script, args, stdin=None):
    """`(code, stdout, stderr)` of one verb run as a subprocess from the project,
    logged on `ctx` for `--verbose`."""
    cmd = [sys.executable, _loader.script_path(script)] + list(args)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = ctx["project"]
    done = subprocess.run(cmd, cwd=ctx["project"], env=env, input=stdin,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    ctx["log"].append((script, list(args), done.returncode,
                       (done.stdout or "") + (done.stderr or "")))
    return done.returncode, done.stdout or "", done.stderr or ""


def relay_refusal(ctx, script, code, text):
    """`(E_STOPPED, text)` for a verb that refused: the verb named, then its own
    words whole - the refusal and the remedy it gives."""
    head = "%s %s: stopped - %s refused (exit %d); its own words follow" % (
        PREFIX, ctx["phase"], script, code)
    return E_STOPPED, "%s\n%s" % (head, (text or "").rstrip("\n"))


def _verb_or_stop(ctx, script, args, stdin=None):
    """`(stdout, None)` when the verb succeeded, else `(None, stop)`."""
    code, out, err = run_verb(ctx, script, args, stdin=stdin)
    if code != 0:
        return None, relay_refusal(ctx, script, code, out + err)
    return out, None


def _task_args(ctx, verb, task_id, *extra):
    return [verb, task_id, ctx["manifest"], "--project-dir", ctx["project"]] \
        + list(extra)


# --- the driver's own state -----------------------------------------------------
def state_path(ctx):
    return os.path.join(ctx["stateDir"], DRIVE_DIRNAME, "%s.json" % (ctx["phase"],))


def read_state(ctx):
    path = state_path(ctx)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ValueError("the driver's state %s cannot be read (%s); remove it "
                         "to start the drive afresh" % (path, exc))
    return body if isinstance(body, dict) else {}


def write_state(ctx, state):
    path = state_path(ctx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")


def start_key(task):
    return _fr.return_start_key(task.get("startedAt"))


def _mark(state, kind, task, value=True):
    """Record `kind` for `task`'s current start; a mark from an earlier start
    no longer applies."""
    state.setdefault(kind, {})[task["id"]] = {"start": start_key(task),
                                              "value": value}


def _marked(state, kind, task):
    entry = (state.get(kind) or {}).get(task["id"]) or {}
    return entry.get("value") if entry.get("start") == start_key(task) else None


# --- reading the plan -------------------------------------------------------------
def load_phase(ctx):
    """`(manifest, phase)` read fresh: every verb the driver calls writes."""
    manifest = _mio.load_manifest(ctx["manifest"])
    for phase in manifest.get("phases") or []:
        if isinstance(phase, dict) and phase.get("id") == ctx["phase"]:
            return manifest, phase
    raise ValueError("phase %s is no longer in %s" % (ctx["phase"], ctx["manifest"]))


def _tasks(phase):
    return [t for t in phase.get("tasks") or [] if isinstance(t, dict) and t.get("id")]


def next_task(manifest, phase):
    """`(task, how)`: the task the drive is on - the first in progress in id
    order - else the first ready one, which the drive starts. One at a time: a
    recorded gate must not run while another executor edits the tree."""
    tasks = _tasks(phase)
    running = [t for t in tasks if t.get("status") == "in_progress"]
    if running:
        return running[0], "running"
    ready = set(_status_facts.ready_tasks(manifest))
    waiting = [t for t in tasks if t["id"] in ready]
    return (waiting[0], "ready") if waiting else (None, None)


def filed(ctx, task, role):
    """`(body, problem)` of `task`'s `role` return for its current start."""
    _text, body, problem = _fr.read_filed_return(
        _fr.return_path(ctx["evidence"], task, role))
    return body, problem


def review_key(ctx, phase, task):
    """`(key, problem)` - `review.perTask` as this task holds it: its own
    recorded value, else its phase's, else the config's now, which is refused
    rather than defaulted when it is outside the vocabulary."""
    key, source = _fr.review_key(task, phase, None)
    if source != "config":
        return key, None
    return _config_rules.review_per_task_mode(ctx["config"])


def signals_fired(executor):
    """The computed signals that call for a per-task reviewer under `signals`,
    as clauses: a red-first proof that did not come back `proved`, and a filed
    return whose gates disagree with the recorded run - which was green, or the
    drive would have stopped at its decision. A gate the return names as
    anything but `pass` is that disagreement; a return naming no gate claims
    nothing to disagree with."""
    fired = []
    red = (executor or {}).get("redFirst") or {}
    if red.get("status") != "proved":
        fired.append("red-first %s" % (red.get("status") or "absent",))
    gates = (executor or {}).get("gates") or {}
    off = sorted(name for name, word in gates.items() if word != "pass")
    if off:
        fired.append("the return's gate(s) %s disagree with the recorded green"
                     % (", ".join(off),))
    return fired


def reviewer_due(key, executor):
    """Whether this task's reviewer is dispatched before its close - the one
    place it is decided. `always` dispatches every task's; `phase` none, since
    the phase review answers each task at sign-off; `signals` only where
    `signals_fired` names a signal."""
    if key == _fr.KEY_PHASE:
        return False
    if key == "signals":
        return bool(signals_fired(executor))
    return True


# --- the steps ---------------------------------------------------------------------
def instruction(kind, lines):
    return {"kind": kind, "lines": list(lines)}


def decision(ctx, state, name, task, why):
    """Record `name` as the decision the drive waits on, and its instruction."""
    state["pending"] = {"decision": name, "task": task["id"] if task else None,
                        "start": start_key(task) if task else None, "why": why}
    write_state(ctx, state)
    return render_decision(ctx, state["pending"])


def render_decision(ctx, pending):
    name = pending["decision"]
    options, needs = DECISIONS[name]
    lines = step_text("decide-%s" % (name,), task=pending.get("task"),
                      phase=ctx["phase"], why=pending.get("why") or "")
    if options:
        lines += step_text(
            "answer", phase=ctx["phase"], options="|".join(options),
            reason=(" (%s needs --reason)" % ("/".join(needs),)) if needs else "")
    return instruction("decide", lines)


def start_task(ctx, task):
    """Start (or re-start) `task` through the verb; None, or the stop."""
    _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(ctx, "start", task["id"]))
    if stop is None:
        ctx["did"].append("%s %s" % (STARTED, task["id"]))
    return stop


def dispatch(ctx, state, phase, task, role):
    """Write `role`'s brief through `audit-lookup.py` and hand back the dispatch."""
    out, stop = _verb_or_stop(ctx, "audit-lookup.py", [
        ctx["manifest"], "brief", task["id"], "--role", role,
        "--project", ctx["project"]])
    if stop is not None:
        return stop
    found = re.search(r"written: (.+)$", out.strip())
    if not found:
        return relay_refusal(ctx, "audit-lookup.py", 0,
                             "%s\n(the driver found no `written:` path in this)"
                             % (out,))
    _mark(state, "dispatched-%s" % (role,), task)
    write_state(ctx, state)
    model = (task.get("model") if role == "executor"
             else (phase.get("review") or {}).get("model")) or "unset"
    agent = EXECUTOR_AGENT if role == "executor" else REVIEWER_AGENT
    return instruction("dispatch", step_text(
        "dispatch-%s" % (role,), agent=agent, task=task["id"], model=model,
        brief=project_relative(ctx, found.group(1).strip())))


def project_relative(ctx, path):
    """`path` from the project root when it lies inside it, else as given. The
    agent works from the project root, and a print whose size grew with where
    the project happens to sit on disk could not keep `INSTRUCTION_BYTES`."""
    full = os.path.abspath(os.path.join(ctx["project"], path))
    rel = os.path.relpath(full, ctx["project"])
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def record_gate(ctx, phase, task):
    """`(code, stdout, stderr)` of the task's recorded gate run."""
    return run_verb(ctx, "run-test-gate.py", [
        ctx["manifest"], phase["id"], "--task", task["id"], "--record",
        "--project-dir", ctx["project"]])


def moved_fields(result):
    """The fields a stale comparison names as moved, each with the paths a moved
    `content` names."""
    moved = []
    for field in (result or {}).get("fields") or []:
        if field.get("state") != "moved":
            continue
        paths = field.get("paths") or []
        moved.append("%s: %s" % (field["field"], ", ".join(paths[:2])
                                 + (" +%d" % (len(paths) - 2) if len(paths) > 2 else ""))
                     if paths else field["field"])
    return moved


def grade_stamp(ctx, stamp):
    """The did-line clause for the executor's stamp, graded against the tree now:
    current, stale with the fields that moved, or why it could not be graded."""
    if not isinstance(stamp, str) or not stamp.strip():
        return "stamp not graded (the return carries none)"
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "compare", "--project", ctx["gitRoot"], "--stamp", stamp, "--json"])
    try:
        result = json.loads(out)
    except ValueError:
        return "stamp not graded (compare exit %d: %s)" % (
            code, ((err or out).strip().splitlines() or ["no output"])[0][:80])
    verdict = result.get("verdict")
    if verdict == "stale":
        return "stamp stale (moved %s)" % ("; ".join(moved_fields(result)) or "?",)
    if verdict == "current":
        return "stamp current"
    return "stamp %s (git could not answer; not unchanged)" % (verdict,)


def review_items(reviewer):
    """What in the reviewer's return only a human can settle, as one clause."""
    intent = (reviewer or {}).get("intent") or {}
    items = []
    if intent.get("answer") in ("diverges", "cannot-tell"):
        items.append("intent %s" % (intent["answer"],))
    if intent.get("redFirst") == "not-proved":
        items.append("red-first not-proved")
    return ", ".join(items)


def close_task(ctx, state, phase, task, intent_basis=None):
    """Findings, commit and close for a task whose returns are filed; None when
    the drive goes on, else the instruction or stop to print."""
    reviewer, problem = filed(ctx, task, "reviewer")
    if problem:
        return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], problem)
    findings = (reviewer or {}).get("findings") or []
    if findings and not _marked(state, "findings", task):
        _out, stop = _verb_or_stop(ctx, "audit-task.py", [
            "finding", phase["id"], ctx["manifest"], "--project-dir", ctx["project"],
            "--findings-file", "-"], stdin=json.dumps(findings))
        if stop is not None:
            return stop
        _mark(state, "findings", task)
        write_state(ctx, state)
        ctx["did"].append("%d finding(s) of %s filed" % (len(findings), task["id"]))
    out, stop = _verb_or_stop(ctx, "commit-task-work.py", [
        ctx["manifest"], task["id"], "--project", ctx["project"],
        "--subject", str(task.get("title") or task["id"])])
    if stop is not None:
        return stop
    sha = re.search(r"\bcommitted ([0-9a-f]{7,40})\b", out)
    if not sha:
        return decision(ctx, state, "no-change", task, "")
    extra = ["--commit", sha.group(1), "--from-return"]
    if intent_basis is not None:
        extra += ["--intent", "not-asked", "--intent-basis", intent_basis]
    _out, stop = _verb_or_stop(ctx, "audit-task.py",
                               _task_args(ctx, "done", task["id"], *extra))
    if stop is not None:
        return stop
    ctx["did"].append("%s %s at %s" % (CLOSED, task["id"], sha.group(1)[:7]))
    items = review_items(reviewer)
    if items:
        return decision(ctx, state, "review-answer", task, items)
    return None


def advance(ctx, state, manifest, phase, task):
    """The next due step for the task the drive is on; None when the drive goes
    on to the next task, else what to print."""
    executor, problem = filed(ctx, task, "executor")
    if problem:
        return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], problem)
    if executor is None:
        if _marked(state, "dispatched-executor", task):
            return decision(ctx, state, "no-executor-return", task, "")
        return dispatch(ctx, state, phase, task, "executor")
    key, problem = review_key(ctx, phase, task)
    if problem:
        return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], problem)
    due = reviewer_due(key, executor)
    reviewer = None
    if due:
        reviewer, problem = filed(ctx, task, "reviewer")
        if problem:
            return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], problem)
        if reviewer is None and _marked(state, "dispatched-reviewer", task):
            return decision(ctx, state, "no-reviewer-return", task, "")
    # THE RECORDED GATE RUNS ONCE PER START, BEFORE THE REVIEWER OR THE CLOSE,
    # whatever the key: a task whose review is carried to the phase still owes
    # the measurement its close and its commit are bound to.
    if (reviewer is None or not due) and not _marked(state, "gated", task):
        code, out, err = record_gate(ctx, phase, task)
        if code == 1:
            said = [ln for ln in (out + err).splitlines() if "GATE" in ln]
            return decision(ctx, state, "gate-red", task,
                            (said[0].strip() if said else "exit 1")[:90])
        if code != 0:
            return relay_refusal(ctx, "run-test-gate.py", code, out + err)
        _mark(state, "gated", task)
        write_state(ctx, state)
        ctx["did"].append("gate %s green" % (task["id"],))
        ctx["did"].append(grade_stamp(ctx, executor.get("stamp")))
    if due and reviewer is None:
        return dispatch(ctx, state, phase, task, "reviewer")
    if task.get("risk") == "high" and not _marked(state, "confirmed", task):
        return decision(ctx, state, "high-risk", task, "")
    if key == "signals" and not due:
        return close_task(ctx, state, phase, task, intent_basis=(
            "review.perTask signals: no signal fired - red-first proved and the "
            "return's gates agree with the recorded green"))
    return close_task(ctx, state, phase, task)


# --- answering a decision ---------------------------------------------------------
def answer_refusal(ctx, pending, answer, reason):
    """A usage refusal for an answer this decision does not take, or None."""
    if pending is None:
        return "no decision is pending for %s, so --answer %s answers nothing" % (
            ctx["phase"], answer)
    options, needs = DECISIONS[pending["decision"]]
    if answer not in options:
        return "decision %s offers %s, not %r" % (
            pending["decision"], "|".join(options) or "no option", answer)
    if answer in needs and not (reason or "").strip():
        return "--answer %s needs --reason: it is recorded with the task" % (answer,)
    return None


def apply_answer(ctx, state, manifest, phase, pending, answer, reason):
    """Act on an answer to the pending decision; None when the drive goes on."""
    task = _mio.tasks_by_id(manifest).get(pending.get("task")) if pending.get("task") else None
    state.pop("pending", None)
    write_state(ctx, state)
    if answer == "block":
        _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
            ctx, "block", task["id"], "--reason", reason))
        if stop is None:
            ctx["did"].append("blocked %s" % (task["id"],))
        return stop
    if answer == "retry":
        return start_task(ctx, task)
    if answer == "redispatch":
        (state.get("dispatched-reviewer") or {}).pop(task["id"], None)
        write_state(ctx, state)
        return dispatch(ctx, state, phase, task, "reviewer")
    if answer == "not-asked":
        return close_task(ctx, state, phase, task, intent_basis=reason)
    if answer == "confirm":
        _mark(state, "confirmed", task)
        write_state(ctx, state)
        return None
    if answer == "no-change":
        _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
            ctx, "done", task["id"], "--no-change", "--reason", reason))
        if stop is None:
            ctx["did"].append("%s %s (no change)" % (CLOSED, task["id"]))
        return stop
    return None


def pending_still_applies(manifest, pending):
    """A decision about a task that was since closed, cancelled or re-started by
    hand is about a state that no longer exists."""
    if not pending.get("task"):
        return True
    task = _mio.tasks_by_id(manifest).get(pending["task"]) or {}
    if pending["decision"] == "review-answer":
        return True
    return (task.get("status") == "in_progress"
            and start_key(task) == pending.get("start"))


# --- the drive ---------------------------------------------------------------------
def take_lock(ctx, state):
    """Take or re-enter the phase lock; None, or the stop."""
    out, stop = _verb_or_stop(ctx, "audit-lock.py", [
        "acquire", "phase-%s" % (ctx["phase"],), "--project", ctx["gitRoot"],
        "--note", "drive-phase next %s" % (ctx["phase"],)])
    if stop is None and out.lstrip().startswith("[audit-lock] acquired"):
        state["lock"] = "taken"
        write_state(ctx, state)
    return stop


def finish(ctx, state):
    """Every task is terminal: give back a lock this drive took, drop the state."""
    if state.get("lock") == "taken":
        _out, stop = _verb_or_stop(ctx, "audit-lock.py", [
            "release", "phase-%s" % (ctx["phase"],), "--project", ctx["gitRoot"]])
        if stop is not None:
            return stop
    try:
        os.remove(state_path(ctx))
        os.rmdir(os.path.dirname(state_path(ctx)))
    except OSError:
        pass
    return instruction("done", step_text("done", phase=ctx["phase"]))


def stalled_why(manifest, phase):
    unmet = _status_facts.unmet_refs(manifest)
    open_tasks = [t for t in _tasks(phase) if t.get("status") not in _mio.TERMINAL]
    parts = []
    for task in open_tasks[:3]:
        waits = unmet.get(task["id"]) or []
        parts.append("%s %s%s" % (task["id"], task.get("status"),
                                  (" on " + ",".join(waits[:2])) if waits else ""))
    more = len(open_tasks) - 3
    return "; ".join(parts) + (" +%d more" % (more,) if more > 0 else "")


def drive(ctx, answer=None, reason=None):
    """`(code, instruction_or_text)` for one `next`."""
    state = read_state(ctx)
    stop = take_lock(ctx, state)
    if stop is not None:
        return stop
    manifest, phase = load_phase(ctx)
    pending = state.get("pending")
    if pending and not pending_still_applies(manifest, pending):
        state.pop("pending", None)
        write_state(ctx, state)
        pending = None
    if answer is not None:
        refused = answer_refusal(ctx, pending, answer, reason)
        if refused:
            return E_USAGE, "%s %s: %s" % (PREFIX, ctx["phase"], refused)
        said = apply_answer(ctx, state, manifest, phase, pending, answer, reason)
        if said is not None:
            return _as_result(said)
    elif pending:
        return E_OK, render_decision(ctx, pending)
    for _ in range(4 * len(_tasks(phase)) + 4):
        manifest, phase = load_phase(ctx)
        task, how = next_task(manifest, phase)
        if task is None:
            if all(t.get("status") in _mio.TERMINAL for t in _tasks(phase)):
                return _as_result(finish(ctx, state))
            return E_OK, instruction("decide", step_text(
                "decide-stalled", phase=ctx["phase"],
                why=stalled_why(manifest, phase)))
        if how == "ready":
            stop = start_task(ctx, task)
            if stop is not None:
                return stop
            continue
        said = advance(ctx, state, manifest, phase, task)
        if said is not None:
            return _as_result(said)
    return E_STOPPED, ("%s %s: stopped - the drive made no progress over every "
                       "step the plan allows; run with --verbose to see each "
                       "verb's answer" % (PREFIX, ctx["phase"]))


def _as_result(said):
    """An instruction is exit 0; a stop is already `(code, text)`."""
    return said if isinstance(said, tuple) else (E_OK, said)


def echo_steps(ctx):
    """Whether each verb's run is printed above the instruction."""
    return ctx["verbose"]


def render(ctx, code, said):
    """The text of one `next`: the did-line, then the instruction or the stop."""
    lines = []
    if echo_steps(ctx):
        for script, args, rc, text in ctx["log"]:
            lines.append("$ %s %s  -> exit %d" % (script, " ".join(args), rc))
            lines.extend("  " + ln for ln in text.rstrip("\n").splitlines())
    if isinstance(said, dict):
        if ctx["did"]:
            lines.append("%s %s: %s" % (PREFIX, ctx["phase"], "; ".join(ctx["did"])))
        lines.extend(said["lines"])
    else:
        if ctx["did"]:
            lines.append("%s %s: %s" % (PREFIX, ctx["phase"], "; ".join(ctx["did"])))
        lines.append(said)
    return "\n".join(lines)


# --- the command line -------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="drive-phase.py", add_help=True, allow_abbrev=False,
        description="Run every step of a phase that needs no judgement and print "
                    "one instruction: dispatch, decide or done.")
    sub = parser.add_subparsers(dest="action")
    sub.required = True
    nxt = sub.add_parser("next", help="perform the due steps, print one instruction")
    nxt.add_argument("phase", help="the phase id")
    nxt.add_argument("manifest", nargs="?", default=None,
                     help="the manifest (default: the project's configured one)")
    nxt.add_argument("--project-dir", dest="project_dir", default=None)
    nxt.add_argument("--answer", default=None,
                     help="answer the pending decision with one of its options")
    nxt.add_argument("--reason", default=None,
                     help="the reason an option that records one needs")
    nxt.add_argument("--verbose", action="store_true",
                     help="print each verb's run above the instruction")
    return _claude_home.attach_usage_hint(parser)


def context(args):
    """Everything one `next` resolves once, or raises ValueError naming why not."""
    project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR")
                              or os.getcwd())
    found = _mio.resolve_manifest(project, args.manifest)
    if not found.get("path"):
        raise ValueError(found.get("problem") or "no manifest at %s" % (
            ", ".join(p for p, _w in found.get("looked") or []),))
    manifest_path = os.path.abspath(found["path"])
    manifest = _mio.load_manifest(manifest_path)
    phase_id, problem = _mio.resolve_phase_id(manifest, args.phase)
    if problem:
        raise ValueError(problem)
    project, config = _evio.project_config_for(manifest_path, project)
    hc = _loader.load_hooks_config(modname="audit__config")
    return {"project": project, "manifest": manifest_path, "phase": phase_id,
            "config": config,
            "gitRoot": os.path.abspath(os.path.join(
                project, (config or {}).get("gitRoot") or ".")),
            "evidence": _evio.evidence_dir(project, config),
            "stateDir": str(hc.state_dir(pathlib.Path(project), config or {})),
            "verbose": bool(args.verbose), "log": [], "did": []}


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    try:
        ctx = context(args)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("drive-phase.py: %s\n" % (exc,))
        return E_USAGE
    try:
        code, said = drive(ctx, answer=args.answer, reason=args.reason)
    except ValueError as exc:
        code, said = E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], exc)
    out(render(ctx, code, said))
    return code


def success_line(lines):
    """None, always: the driver's print IS the instruction, already inside
    `INSTRUCTION_BYTES`, and a cut one would hand the model part of it."""
    return None


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to a usage error. It deliberately
        # does NOT print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("drive-phase.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_drive_phase.py - run that file instead.")
        sys.exit(0)
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line, keep_verbose=True))
