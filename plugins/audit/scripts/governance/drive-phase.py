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
  * `done`     - the phase is signed off, committed and landed.

The command body is the loop: run `next`, do what it prints, run `next` again.
A task then costs four requests - dispatch the executor, `next` (the recorded
gate, the stamp grade, the reviewer's brief), dispatch the reviewer, `next` (the
findings, the commit, the close, and the next task's start and brief).

SIGN-OFF IS THE SAME LOOP, AND ITS LAST STEP IS ONE STEP. Once every task is
closed, `next` prints the phase reviewer's dispatch with the brief
`audit-lookup.py brief --role phase` wrote - when a review skill resolves or a
task is owed its answers there - and the reviewer files through `submit
--head`. The `next` after it records the review's findings in one `finding`
call and prints one `decide triage`: each open finding with its options, and
what a fix task is predicted to cost, with the basis of that figure. Answered
`fix`, each named finding becomes a task through `audit-task.py add --fixes`,
which the drive then runs like any other, and the triage is printed again.
Answered `sign-off` with the summary, one `next` runs the phase gate, the
invariants check, the sign-off verb, the commit, the landing and the lock
release, and prints `done`. A red phase gate stops that step before the
sign-off verb: the verdict is never recorded over it.

EVERY STEP IS AN EXISTING VERB, CALLED AS A SUBPROCESS. An entry point may not
import another entry point, so each verb is resolved by basename through
`_loader.script_path` and run: `audit-lock.py`, `audit-task.py` (start, block,
finding, done), `audit-lookup.py brief`, `run-test-gate.py --record`,
`stamp-verification.py compare` and `commit-task-work.py`; at sign-off
`derive-phase-gate.py`, `verify-invariants.py`, `audit-task.py signoff` and
`add --fixes`, `commit-audit-state.py`, `commit-manifest-index.py` and
`close-phase.py`. Nothing here
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

AN AGENT'S LAST ACT IS `submit`, AND IT IS THE SAME KIND OF STEP. Filing a
return used to be three procedures the agent's prompt explained and the agent
ran by hand: take the stamp, prove the red in a throwaway tree, hand the object
to the filing verb. Each is a verb already, so `submit` runs them in that order
and the prompt only names the call:

  * the return arrives on stdin and its shape is checked first, with the fields
    `submit` fills set aside, so a malformed one costs no red run and writes
    nothing;
  * an executor's red-first block is `stamp-verification.py red`'s, run with
    the test command given after `--` - owed on a `tdd` task, and refused
    there without one;
  * an executor's `stamp` is `stamp-verification.py take`'s, taken after the
    red run, the last claim; a take that names no tree (no `audit-stamp:`
    line, or a stamp git could put no HEAD in) is refused as a missing stamp;
  * the filing is `audit-task.py file-return`'s, which writes once - a second
    filing for one start, or for one head of a phase review, is refused there
    and the first stays as filed. A reviewer's return, and a phase review's
    under `--head`, go to the same verb unchanged.

A TASK ID IN THE PHASE'S PLACE DRIVES THAT ONE TASK. `next <taskId>` starts
it, runs the same steps and prints `done <taskId>` once it is closed, leaving
its siblings and the phase's sign-off alone - the run `/audit:run` and
`/audit:next` make, which execute exactly one task.

Usage:
  drive-phase.py next <phaseId|taskId> [manifest] [--project-dir DIR]
                 [--answer OPTION] [--reason TEXT] [--fix FINDING[,FINDING]]
                 [--verbose]
  drive-phase.py submit <taskId|phaseId> --role executor|reviewer [manifest]
                 [--head SHA] [--project-dir DIR] [--case ID ...]
                 [--introduces SYMBOL ...] [--deps-from DIR] [--verbose]
                 [-- <test command>]  < return.json

Exit codes:
  0  an instruction was printed - dispatch, decide or done; or, for `submit`,
     the return was filed
  1  a verb refused, or a filed return will not read: the drive stopped and the
     words that stopped it are printed; for `submit`, the return was refused and
     nothing was written
  2  usage error - no manifest, no such phase, an answer no pending decision
     offers, or an option that needs --reason given none; for `submit`, no such
     task or phase, or red-first options with no test command

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
import _areas  # noqa: E402  (resolve_review_skill: whether the phase review has a skill)
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
#
# THIS IS WHERE A FOLLOWED RULE LIVES NOW. No pipeline command makes the main loop
# read reference prose first (`tools/measure-context.py --gate` holds that), so a
# rule the model must follow at a step is stated here, at that step, or in the
# prompt of the agent that acts on it. The README's followed table names each
# rule's step, and `_refs.followed_anchor_drift()` holds that every step it names
# is here with a rule that is not empty. A rule printed on a success step costs
# bytes inside `INSTRUCTION_BYTES` on every task, so each is one short line.
DISPATCH_RULE = "Description starts with the id; dispatch nothing alongside."
STEPS = {
    "dispatch-executor": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "dispatch-reviewer": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "decide-gate-red": {
        "line": "decide gate-red %(task)s: recorded gate red (%(why)s)",
        "rule": ("rerun spends no attempt (GATE COULD NOT RUN); retry spends "
                 "one; past maxAttempts, block and tell the human.",)},
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
        "rule": ("Ask the human (AskUserQuestion); confirm only on their yes, "
                 "else block with their reason.",)},
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
    "dispatch-phase-review": {
        "line": "dispatch %(agent)s %(phase)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "decide-triage": {
        "line": "decide triage %(phase)s: %(why)s",
        "rule": ("Fix tasks come first: their edits invalidate a gate taken "
                 "before them. Then: gate, invariants, verdict, commit, landing.",)},
    "decide-no-phase-review-return": {
        "line": "decide no-phase-review-return %(phase)s: the phase reviewer was "
                "dispatched for head %(why)s and filed no return",
        "rule": ()},
    "decide-invariant-breach": {
        "line": "decide invariant-breach %(phase)s: %(why)s",
        "rule": ("verify-invariants.py found a breach; signing off over it is a "
                 "human's decision, and the reason is kept in the summary",)},
    "decide-not-fast-forward": {
        "line": "decide not-fast-forward %(phase)s: the parent moved during the "
                "phase, so close-phase.py did not merge (%(why)s)",
        "rule": ()},
    "done": {
        "line": "done %(phase)s: %(why)s",
        "rule": ("Report where it landed: a parent that is not the development "
                 "branch does not hold the work yet.",)},
    "done-task": {
        "line": "done %(task)s: %(why)s",
        "rule": ()},
    "ado-echo": {
        "line": "ado echo owed: %(items)s",
        "rule": ("Update each linked item's board state as reference/tracker-sync.md "
                 "says - never create one, never ask, a failure is one report line.",)},
    "stop-blocked": {
        "line": "[drive-phase] %(phase)s: stopped - %(task)s is blocked: %(why)s",
        "rule": ("Ask the human; only on their yes run audit-task.py start "
                 "<id> (it spends an attempt), then next again.",)},
    "stop-lock": {
        "line": "",
        "rule": ("Held by a live run: stop, never take it over. Looks abandoned: "
                 "ask the human before --takeover.",)},
    "stopped": {
        "line": "",
        "rule": ("Relay these words and act on the remedy they name; never edit "
                 "the plan or the journal by hand to get past them.",)},
}

# Each decision's options, and the ones that need `--reason`. A decision with no
# options is one only the plan can change; nothing here answers it.
DECISIONS = {
    "gate-red": (("retry", "rerun", "block"), ("block",)),
    "no-executor-return": (("retry", "block"), ("block",)),
    "no-reviewer-return": (("redispatch", "not-asked"), ("not-asked",)),
    "high-risk": (("confirm", "block"), ("block",)),
    "no-change": (("no-change", "retry"), ("no-change",)),
    "review-answer": (("continue",), ()),
    "stalled": ((), ()),
    "triage": (("sign-off", "fix"), ("sign-off",)),
    "no-phase-review-return": (("redispatch",), ()),
    "invariant-breach": (("accept",), ("accept",)),
    "not-fast-forward": (("no-ff",), ()),
}

# --- sign-off's constants -------------------------------------------------------
# The triage print holds one line per open finding, so it is bounded per line
# rather than as a whole: a review with many findings is a longer decision, not a
# cut one.
TRIAGE_LINE_BYTES = 160
# What a fix task is predicted to cost, in USD-equivalent: the range the
# pipeline-cost design gives for rung 1 (section 5.4: the sign-off with a fix
# task less the sign-off without, in two benchmark sessions). A prediction for a
# task of that benchmark's size, never a measurement of this project's.
FIX_TASK_PREDICTED = (0.1045, 0.1192)
FIX_TASK_PRICE_BASIS = ("pipeline-cost design 5.4, rung 1, predicted for a "
                        "benchmark-size task; not measured here")
# The verdict sign-off records, and the word a phase's review status carries
# once it is recorded.
SIGNED_OFF = ("passed", "skipped")
_BRIEF_HEAD = re.compile(r"^head: ([0-9a-f]{7,40})\s*$", re.M)
_RUN_ID = re.compile(r"evidence: recorded (\S+)")


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
    words whole - the refusal and the remedy it gives - then the rule for a
    stop, which for a held lock is the lock's own."""
    head = "%s %s: stopped - %s refused (exit %d); its own words follow" % (
        PREFIX, ctx["phase"], script, code)
    rule = STEPS["stop-lock" if script == "audit-lock.py" else "stopped"]["rule"]
    return E_STOPPED, "\n".join([head, (text or "").rstrip("\n")] + list(rule))


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


def decision(ctx, state, name, task, why, extra=None):
    """Record `name` as the decision the drive waits on, and its instruction."""
    state["pending"] = dict({"decision": name,
                             "task": task["id"] if task else None,
                             "start": start_key(task) if task else None,
                             "why": why}, **(extra or {}))
    write_state(ctx, state)
    return render_decision(ctx, state["pending"])


def render_decision(ctx, pending):
    name = pending["decision"]
    if name == "triage":
        return render_triage(ctx, pending)
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
                            (said[0].strip() if said else "exit 1")[:80])
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
    if key == _fr.KEY_PHASE and _fr.is_fix_task(task, phase):
        # A fix task answers to the phase review that raised its findings, and
        # the landing reads `not-asked` with this basis as its answer.
        return close_task(ctx, state, phase, task, intent_basis=(
            "a fix task for %s: the phase review that raised the finding is its "
            "review" % (", ".join(str(f) for f in task.get("fixes") or []),)))
    return close_task(ctx, state, phase, task)


# --- answering a decision ---------------------------------------------------------
def answer_refusal(ctx, pending, answer, reason, fixes=()):
    """A usage refusal for an answer this decision does not take, or None."""
    if pending is None:
        return "no decision is pending for %s, so --answer %s answers nothing" % (
            ctx["phase"], answer)
    options, needs = DECISIONS[pending["decision"]]
    if answer not in options:
        return "decision %s offers %s, not %r" % (
            pending["decision"], "|".join(options) or "no option", answer)
    if answer in needs and not (reason or "").strip():
        return "--answer %s needs --reason: it is recorded with the %s" % (
            answer, "phase" if pending.get("task") is None else "task")
    if answer == "fix":
        open_ids = [f.get("id") for f in pending.get("findings") or []]
        unknown = [f for f in fixes if f not in open_ids]
        if not fixes or unknown:
            return ("--answer fix names the findings to fix with --fix, from the "
                    "open ones: %s%s" % (", ".join(open_ids) or "none",
                                         "; not open: %s" % (", ".join(unknown),)
                                         if unknown else ""))
    elif fixes:
        return "--fix belongs to --answer fix"
    return None


def keep_record(ctx, phase):
    """Commit a failed run's record - the plan, the journal and the evidence the
    gate wrote, never the task's files - through the audit-state verb. A blocked
    task gets no task commit, so nothing else would carry the rows that say why
    it stopped. None, or the stop."""
    out, stop = _verb_or_stop(ctx, "commit-audit-state.py", [
        ctx["manifest"], phase["id"], "--project", ctx["project"], "--json"])
    if stop is not None:
        return stop
    try:
        made = json.loads(out).get("commit")
    except ValueError:
        made = None
    ctx["did"].append("record committed at %s" % (made[:7],) if made
                      else "record: nothing to commit")
    return None


def apply_answer(ctx, state, manifest, phase, pending, answer, reason,
                 fixes=()):
    """Act on an answer to the pending decision; None when the drive goes on."""
    task = _mio.tasks_by_id(manifest).get(pending.get("task")) if pending.get("task") else None
    state.pop("pending", None)
    write_state(ctx, state)
    if pending["decision"] in ("triage", "no-phase-review-return",
                               "invariant-breach", "not-fast-forward"):
        return apply_phase_answer(ctx, state, manifest, phase, pending, answer,
                                  reason, fixes)
    if answer == "block":
        _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
            ctx, "block", task["id"], "--reason", reason))
        if stop is not None:
            return stop
        ctx["did"].append("blocked %s" % (task["id"],))
        return keep_record(ctx, phase)
    if answer == "rerun":
        # The gate is not marked as run for this start, so the drive measures
        # again; the task is not re-started, so no attempt is spent.
        return None
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


def finish(ctx, state, why):
    """The phase is through: give back a lock this drive took, drop the state."""
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
    return instruction("done", step_text("done", phase=ctx["phase"], why=why))


# --- sign-off --------------------------------------------------------------------
def signed_off(phase):
    return (phase.get("review") or {}).get("status") in SIGNED_OFF


def git_head(ctx):
    """The commit HEAD names in the project's repository, or None."""
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def review_due(ctx, manifest, phase):
    """`(due, problem)` - whether sign-off dispatches the phase reviewer: a
    review skill resolves for the phase, or a task is owed its answers there."""
    skill, _basis = _areas.resolve_review_skill(manifest, phase)
    if skill:
        return True, None
    live, problem = None, None
    if any(t.get("commit") and _fr.review_key(t, phase, None)[1] == "config"
           for t in _tasks(phase)):
        live, problem = _config_rules.review_per_task_mode(ctx["config"])
    if problem:
        return False, problem
    answered = _fr.answered_entries(_fr.phase_returns(ctx["evidence"],
                                                      phase["id"]))
    return any(_fr.owed_answer(t, phase, live, answered)
               for t in _tasks(phase)), None


def dispatch_phase_review(ctx, state, phase):
    """Write the phase brief through `audit-lookup.py` and hand back the phase
    reviewer's dispatch, remembering the head the brief names."""
    out, stop = _verb_or_stop(ctx, "audit-lookup.py", [
        ctx["manifest"], "brief", phase["id"], "--role", "phase",
        "--project", ctx["project"]])
    if stop is not None:
        return stop
    found = re.search(r"written: (.+)$", out.strip())
    brief = found.group(1).strip() if found else ""
    try:
        with open(os.path.join(ctx["project"], brief), "r",
                  encoding="utf-8") as fh:
            head = _BRIEF_HEAD.search(fh.read())
    except OSError:
        head = None
    if not head:
        return relay_refusal(ctx, "audit-lookup.py", 0,
                             "%s\n(the driver found no brief naming a head in "
                             "this)" % (out,))
    state["phaseReview"] = {"head": head.group(1)}
    write_state(ctx, state)
    return instruction("dispatch", step_text(
        "dispatch-phase-review", agent=REVIEWER_AGENT, phase=phase["id"],
        model=(phase.get("review") or {}).get("model") or "unset",
        brief=project_relative(ctx, brief)))


def record_findings(ctx, phase, found):
    """Every finding of the phase review, recorded in ONE `finding` call; None,
    or the stop."""
    _out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "finding", phase["id"], ctx["manifest"], "--project-dir", ctx["project"],
        "--findings-file", "-"], stdin=json.dumps(found))
    return stop


def open_findings(phase):
    """The phase review's findings no fix task names yet, in plan order."""
    return [f for f in (phase.get("review") or {}).get("findings") or []
            if isinstance(f, dict) and f.get("id") and not f.get("fixTask")]


def _clip(text, width):
    data = (text or "").encode("utf-8")
    if len(data) <= width:
        return text or ""
    return data[:max(width - 3, 0)].decode("utf-8", "ignore") + "..."


def render_triage(ctx, pending):
    """The triage decision: each open finding with its options, a fix task's
    predicted price with its basis, and how to answer."""
    found = pending.get("findings") or []
    head = step_text("decide-triage", phase=ctx["phase"], why=pending.get("why") or "")
    lines = head[:1]
    for f in found:
        lines.append(_clip("  %s %s %s - %s [fix|leave]" % (
            f.get("id"), f.get("severity"), f.get("file"), f.get("issue")),
            TRIAGE_LINE_BYTES))
    if found:
        lines.append(_clip("  a fix task: %.2f-%.2f USD-eq predicted (%s)" % (
            FIX_TASK_PREDICTED + (FIX_TASK_PRICE_BASIS,)), TRIAGE_LINE_BYTES))
        lines.append("answer: next %s --answer fix --fix <id>[,<id>]" % (
            ctx["phase"],))
    lines.append("answer: next %s --answer sign-off --reason <the summary>%s" % (
        ctx["phase"], " (a finding left is kept as recorded)" if found else ""))
    return instruction("decide", lines + head[1:])


def triage(ctx, state, manifest, phase):
    """The phase review, its findings and the triage: the dispatch, a decision,
    or a stop."""
    mark = state.get("phaseReview") or {}
    if not mark.get("head"):
        due, problem = review_due(ctx, manifest, phase)
        if problem:
            return _stopped(ctx, problem)
        if due:
            return dispatch_phase_review(ctx, state, phase)
    review = None
    if mark.get("head"):
        _text, review, problem = _fr.read_filed_return(os.path.join(
            ctx["evidence"], *_fr.phase_return_rel(phase["id"],
                                                   mark["head"]).split("/")))
        if problem:
            return _stopped(ctx, problem)
        if review is None:
            return decision(ctx, state, "no-phase-review-return", None,
                            mark["head"][:12])
        found = review.get("findings") or []
        if found and not mark.get("findings"):
            stop = record_findings(ctx, phase, found)
            if stop is not None:
                return stop
            mark["findings"] = True
            state["phaseReview"] = mark
            write_state(ctx, state)
            ctx["did"].append("%d finding(s) of the phase review filed"
                              % (len(found),))
            manifest, phase = load_phase(ctx)
    still = [dict((k, f.get(k)) for k in ("id", "severity", "file", "issue"))
             for f in open_findings(phase)]
    said = ("the phase review returned `%s`" % ((review or {}).get("verdict")
                                                 or "no verdict",)
            if review is not None else "no phase review is due")
    return decision(ctx, state, "triage", None, "%s; %s" % (
        said, "%d finding(s) open" % (len(still),) if still
        else "no finding open"), extra={"findings": still})


def add_fix_tasks(ctx, phase, fixes):
    """A task for each named finding through `audit-task.py add --fixes`, in one
    call each; None, or the stop."""
    by_id = dict((f.get("id"), f) for f in open_findings(phase))
    for fid in fixes:
        found = by_id.get(fid) or {}
        path = str(found.get("file") or "").split(":", 1)[0].strip()
        args = ["add", _clip("fix %s: %s" % (fid, found.get("issue") or ""), 80),
                ctx["manifest"], "--project-dir", ctx["project"],
                "--phase", phase["id"], "--fixes", fid, "--description",
                "%s\n\nResolution asked: %s" % (found.get("issue") or "",
                                                found.get("resolution") or ""),
                "--json"]
        if path:
            args += ["--files", path]
        out, stop = _verb_or_stop(ctx, "audit-task.py", args)
        if stop is not None:
            return stop
        try:
            added = json.loads(out).get("id")
        except ValueError:
            added = None
        ctx["did"].append("fix task %s added for %s" % (added or "?", fid))
    return None


def phase_gate(ctx, phase):
    """`(code, stdout, stderr)` of the phase's recorded gate run, derived first
    when `meta.phaseGate.mode` asks for a derived gate."""
    manifest = _mio.load_manifest(ctx["manifest"])
    if ((manifest.get("meta") or {}).get("phaseGate") or {}).get("mode"):
        code, out, err = run_verb(ctx, "derive-phase-gate.py", [
            ctx["manifest"], phase["id"]])
        if code != 0:
            return code, out, err
    return run_verb(ctx, "run-test-gate.py", [
        ctx["manifest"], phase["id"], "--record", "--project-dir", ctx["project"]])


def red_gate_stop(ctx, phase, out, err):
    """The stop for a red phase gate: its own GATE lines, the invariants run
    beside it, and the remedy. Nothing after the gate has run."""
    said = [ln for ln in (out + err).splitlines() if "GATE" in ln][:3]
    run_id = _RUN_ID.search(out + err)
    code, inv_out, inv_err = run_verb(ctx, "verify-invariants.py", [
        ctx["manifest"], phase["id"], "--project", ctx["project"]])
    breaches = [ln.strip() for ln in (inv_out + inv_err).splitlines()
                if ln.strip().startswith("BREACH")][:3]
    lines = ["%s %s: stopped - the phase gate is red, so the sign-off verb did not "
             "run" % (PREFIX, ctx["phase"])] + ["  " + ln.strip() for ln in said]
    lines.append("  invariants: %s" % (
        "; ".join(breaches) if breaches else "exit %d, no breach printed" % (code,)))
    lines.append("  fix it in a new task: audit-task.py add \"<the fix>\" --phase "
                 "%s --files <files>%s, then next %s" % (
                     phase["id"], " --failing-from %s" % (run_id.group(1),)
                     if run_id else "", ctx["phase"]))
    return E_STOPPED, "\n".join(lines)


def run_signoff(ctx, state, phase):
    """The phase gate, the invariants and the sign-off verb - None when the
    verdict is recorded, else the decision or the stop."""
    code, out, err = phase_gate(ctx, phase)
    if code == 1:
        return red_gate_stop(ctx, phase, out, err)
    if code != 0:
        return relay_refusal(ctx, "run-test-gate.py", code, out + err)
    ctx["did"].append("phase gate green")
    if not state.get("breachAccepted"):
        code, out, err = run_verb(ctx, "verify-invariants.py", [
            ctx["manifest"], phase["id"], "--project", ctx["project"]])
        if code == 1:
            first = [ln.strip() for ln in (out + err).splitlines()
                     if ln.strip().startswith("BREACH")]
            return decision(ctx, state, "invariant-breach", None,
                            _clip(first[0] if first else "exit 1", 140))
        if code != 0:
            return relay_refusal(ctx, "verify-invariants.py", code, out + err)
        ctx["did"].append("invariants clean")
    summary = state.get("summary") or ""
    if state.get("breachAccepted"):
        summary = "%s Invariant breach accepted: %s" % (summary,
                                                        state["breachAccepted"])
    args = ["signoff", phase["id"], ctx["manifest"], "--project-dir",
            ctx["project"], "--verdict", "passed", "--summary", summary]
    mark = state.get("phaseReview") or {}
    if mark.get("head"):
        args += ["--review-outcome", "phase review filed at head %s"
                 % (mark["head"][:12],)]
    _out, stop = _verb_or_stop(ctx, "audit-task.py", args)
    if stop is not None:
        return stop
    ctx["did"].append("signed off")
    return None


def commit_signoff(ctx, phase):
    """The sign-off committed through the audit-state verb, and the index verb
    after it in a sharded plan; `(sha or None, None)`, or `(None, stop)`."""
    commits = [("commit-audit-state.py", "sign-off")]
    try:
        if _mio.is_sharded(_mio.read_json(ctx["manifest"])):
            commits.append(("commit-manifest-index.py", "sign-off"))
    except Exception as exc:                                   # noqa: BLE001
        return None, _stopped(ctx, "%s cannot be read to tell its layout (%s)"
                              % (ctx["manifest"], exc))
    made = None
    for script, subject in commits:
        out, stop = _verb_or_stop(ctx, script, [
            ctx["manifest"], phase["id"], "--project", ctx["project"],
            "--subject", subject, "--json"])
        if stop is not None:
            return None, stop
        try:
            made = made or json.loads(out).get("commit")
        except ValueError:
            pass
    return made, None


def land(ctx, state, phase):
    """`(said, None)` - what the landing did, in a clause - or `(None, stop)`."""
    if not phase.get("branch"):
        return "no branch recorded, so nothing to land", None
    args = [ctx["manifest"], phase["id"], "--project", ctx["project"]]
    if state.get("noFf"):
        args.append("--no-ff")
    code, out, err = run_verb(ctx, "close-phase.py", args)
    if code == 3:
        return None, decision(ctx, state, "not-fast-forward", None,
                              "close-phase exit 3")
    if code != 0:
        return None, relay_refusal(ctx, "close-phase.py", code, out + err)
    if "NOT MERGED" in out:
        return "meta.merge.auto is false, so the merge is handed to a human", None
    return "landed (%s)" % (_clip((out.strip().splitlines() or [""])[0], 90),), None


def finish_signoff(ctx, state, phase):
    """The commit, the landing and the lock release after a recorded verdict;
    the `done` instruction, or the decision or stop that held it."""
    sha, stop = commit_signoff(ctx, phase)
    if stop is not None:
        return stop
    if sha:
        ctx["did"].append("committed %s" % (sha[:7],))
    said, stop = land(ctx, state, phase)
    if stop is not None:
        return stop
    return finish(ctx, state, "signed off (%s); %s" % (
        (phase.get("review") or {}).get("status") or "passed", said))


def signoff_step(ctx, state, phase):
    """The one step a `sign-off` answer runs."""
    if not signed_off(phase):
        stop = run_signoff(ctx, state, phase)
        if stop is not None:
            return stop
        _manifest, phase = load_phase(ctx)
    return finish_signoff(ctx, state, phase)


def apply_phase_answer(ctx, state, manifest, phase, pending, answer, reason,
                       fixes):
    """Act on an answer to one of sign-off's decisions."""
    if answer == "fix":
        return add_fix_tasks(ctx, phase, fixes)
    if answer == "redispatch":
        state.pop("phaseReview", None)
        write_state(ctx, state)
        return dispatch_phase_review(ctx, state, phase)
    if answer == "sign-off":
        state["summary"] = reason
    elif answer == "accept":
        state["breachAccepted"] = reason
    elif answer == "no-ff":
        state["noFf"] = True
    write_state(ctx, state)
    return signoff_step(ctx, state, phase)


def sign_off(ctx, state, manifest, phase):
    """Every task is terminal: the phase review, the triage, or - for a phase
    already signed off - the rest of the one step."""
    if signed_off(phase):
        if phase.get("mergedAt") or not phase.get("branch"):
            return finish(ctx, state, "already signed off (%s)%s" % (
                phase["review"]["status"], ", and landed"
                if phase.get("mergedAt") else ""))
        return finish_signoff(ctx, state, phase)
    return triage(ctx, state, manifest, phase)


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


def finish_task(ctx, state, task):
    """A task-scoped drive is through: give back a lock this drive took, drop the
    marks of this task, and drop the state when nothing else is in it."""
    if state.get("lock") == "taken":
        _out, stop = _verb_or_stop(ctx, "audit-lock.py", [
            "release", "phase-%s" % (ctx["phase"],), "--project", ctx["gitRoot"]])
        if stop is not None:
            return stop
        state.pop("lock", None)
    for kind in [k for k, v in state.items() if isinstance(v, dict)]:
        state[kind].pop(task["id"], None)
        if not state[kind]:
            state.pop(kind)
    if state:
        write_state(ctx, state)
    else:
        try:
            os.remove(state_path(ctx))
            os.rmdir(os.path.dirname(state_path(ctx)))
        except OSError:
            pass
    closed = any(d.startswith("%s %s" % (CLOSED, task["id"])) for d in ctx["did"])
    why = "%s%s" % ("" if closed else "already ", task.get("status") or "?")
    if task.get("commit"):
        why = "%s at %s" % (why, str(task["commit"])[:7])
    return instruction("done", step_text("done-task", task=task["id"], why=why))


def drive_task(ctx, state):
    """The steps of the one task `ctx["only"]` names: start it, advance it, and
    finish when it is terminal. Its siblings and sign-off are not touched."""
    for _ in range(8):
        manifest, phase = load_phase(ctx)
        task = _mio.tasks_by_id(manifest).get(ctx["only"]) or {}
        if task.get("status") in _mio.TERMINAL:
            return _as_result(finish_task(ctx, state, task))
        if task.get("status") == "blocked":
            return E_STOPPED, "\n".join(step_text(
                "stop-blocked", phase=ctx["phase"], task=task["id"],
                why=_clip(str(task.get("blockedReason") or "no reason recorded"), 120)))
        if task.get("status") != "in_progress":
            stop = start_task(ctx, task)
            if stop is not None:
                return stop
            continue
        said = advance(ctx, state, manifest, phase, task)
        if said is not None:
            return _as_result(said)
    return E_STOPPED, ("%s %s: stopped - the drive of %s made no progress; run "
                       "with --verbose to see each verb's answer"
                       % (PREFIX, ctx["phase"], ctx["only"]))


def drive(ctx, answer=None, reason=None, fixes=()):
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
    if ctx.get("only") and pending and pending.get("task") != ctx["only"]:
        return E_STOPPED, ("%s %s: stopped - this phase's drive waits on a %s "
                           "decision; answer it with next %s first"
                           % (PREFIX, ctx["phase"], pending["decision"], ctx["phase"]))
    if answer is not None:
        refused = answer_refusal(ctx, pending, answer, reason, fixes)
        if refused:
            return E_USAGE, "%s %s: %s" % (PREFIX, ctx["phase"], refused)
        said = apply_answer(ctx, state, manifest, phase, pending, answer, reason,
                            fixes)
        if said is not None:
            return _as_result(said)
    elif pending:
        return E_OK, render_decision(ctx, pending)
    if ctx.get("only"):
        return drive_task(ctx, state)
    for _ in range(4 * len(_tasks(phase)) + 4):
        manifest, phase = load_phase(ctx)
        task, how = next_task(manifest, phase)
        if task is None:
            if all(t.get("status") in _mio.TERMINAL for t in _tasks(phase)):
                return _as_result(sign_off(ctx, state, manifest, phase))
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


# --- submit: the agent's own last act ----------------------------------------
STAMP_TOKEN = "audit-stamp:"
# What a placeholder stands in for while the shape is checked before the fields
# `submit` fills exist: the check is about what the AGENT sent.
_FILLED_LATER = {"stamp": "filled by submit",
                 "redFirst": {"status": "proved", "basis": "filled by submit"}}


def _stopped(ctx, why):
    return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], why)


def submit_target(manifest, target):
    """`(task, phase)` the id names - a task with its phase, or `(None, phase)`
    for a phase id - or `(None, None)` when it names neither."""
    for phase in manifest.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        if phase.get("id") == target:
            return None, phase
        for task in _tasks(phase):
            if task["id"] == target:
                return task, phase
    return None, None


def submitted_shape(role, body, fills):
    """The ways `body` falls short of `role`'s shape, judged with each field in
    `fills` set aside: those are `submit`'s to supply, not the agent's."""
    if not isinstance(body, dict):
        return _fr.return_problems(role, body)
    held = dict(body)
    held.update((name, _FILLED_LATER[name]) for name in fills)
    return _fr.return_problems(role, held)


def already_filed(ctx, task):
    """The project-relative path of `task`'s executor return for its current
    start when one is filed, else None. The filing verb refuses a second
    filing on its own; asking first is what keeps a refused one from costing a
    red run and a stamp."""
    path = _fr.return_path(ctx["evidence"], task, "executor")
    return project_relative(ctx, path) if path and os.path.exists(path) else None


def red_block(ctx, task, args, cmd):
    """`(block, None)` - the helper's `redFirst` block for `task` - or
    `(None, stop)`. A test that passed without the fix gets no block from the
    helper, and so no filing: the work is to fix the test."""
    extra = []
    for flag, values in (("--case", args.case), ("--introduces", args.introduces)):
        for value in values:
            extra += [flag, value]
    if args.deps_from:
        extra += ["--deps-from", args.deps_from]
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "red", "--project", ctx["gitRoot"], "--manifest", ctx["manifest"],
        "--task", task["id"], "--json"] + extra + ["--"] + list(cmd))
    try:
        payload = json.loads(out)
    except ValueError:
        return None, relay_refusal(ctx, "stamp-verification.py", code, out + err)
    block = payload.get("redFirst") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None, _stopped(ctx, "the red-first helper gave no block (exit %d): "
                              "%s Nothing filed." % (code, payload.get("note")
                                                     or "no note"))
    return block, None


def take_stamp(ctx, task):
    """`(line, None)` - the `audit-stamp:` line for the tree now, over the task's
    declared files - or `(None, stop)` when the take names no tree."""
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "take", "--project", ctx["gitRoot"], "--manifest", ctx["manifest"],
        "--task", task["id"], "--json"])
    try:
        taken = json.loads(out)
    except ValueError:
        taken = {}
    line = taken.get("line") if isinstance(taken, dict) else None
    head = ((taken.get("stamp") or {}) if isinstance(taken, dict) else {}).get("head")
    if code != 0 or not isinstance(line, str) or not line.startswith(STAMP_TOKEN):
        return None, _stopped(ctx, "the stamp is missing - `stamp-verification.py "
                              "take` exited %d with no %s line: %s Nothing filed."
                              % (code, STAMP_TOKEN, (err or out).strip()[:200]))
    if not head:
        return None, _stopped(ctx, "the stamp is missing - git named no HEAD for "
                              "%s, so the stamp binds the claims to no tree. "
                              "Nothing filed." % (ctx["gitRoot"],))
    return line, None


def submit(ctx, manifest, args, cmd, text):
    """`(code, instruction_or_text)` for one `submit`."""
    task, phase = submit_target(manifest, args.id)
    if phase is None:
        return E_USAGE, "%s submit: no task or phase %r in %s" % (
            PREFIX, args.id, ctx["manifest"])
    ctx["phase"] = phase["id"]
    try:
        body = json.loads(text)
    except ValueError as exc:
        return _stopped(ctx, "the return on stdin does not parse as JSON (%s). "
                        "Nothing filed." % (exc,))
    tdd = task is not None and (task.get("tests") or {}).get("mode") == "tdd"
    executor = task is not None and args.role == "executor"
    if executor and tdd and not cmd:
        return _stopped(ctx, "%s is a tdd task, so its red-first block is the "
                        "helper's: name the test command after `--`. Nothing "
                        "filed." % (task["id"],))
    fills = (["stamp"] + (["redFirst"] if cmd else [])) if executor else []
    problems = submitted_shape(args.role, body, fills) if task is not None else []
    if problems:
        return _stopped(ctx, "the %s return for %s does not have the shape its "
                        "role declares. Nothing filed:\n%s" % (
                            args.role, args.id,
                            "\n".join("  " + p for p in problems)))
    if executor:
        held = already_filed(ctx, task)
        if held:
            return _stopped(ctx, "the executor return for %s is already filed for "
                            "this start (%s) and stays as filed. Nothing run."
                            % (task["id"], held))
        if cmd:
            block, stop = red_block(ctx, task, args, cmd)
            if stop is not None:
                return stop
            body["redFirst"] = block
            ctx["did"].append("red-first %s" % (block.get("status"),))
        line, stop = take_stamp(ctx, task)
        if stop is not None:
            return stop
        body["stamp"] = line
        ctx["did"].append("stamp taken")
        text = json.dumps(body, indent=2) + "\n"
    extra = ["--head", args.head] if args.head else []
    out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "file-return", args.id, "--role", args.role, ctx["manifest"],
        "--project-dir", ctx["project"]] + extra, stdin=text)
    if stop is not None:
        return stop
    written = re.search(r"written: (.+)$", out.strip())
    ctx["did"].insert(0, "%s %s return filed%s" % (
        args.id, args.role, (" at %s" % (written.group(1).strip(),))
        if written else ""))
    return E_OK, instruction("filed", [])


def echo_steps(ctx):
    """Whether each verb's run is printed above the instruction."""
    return ctx["verbose"]


def _ado_on(meta):
    """Whether the plan's board takes the echo: `meta.ado` present, and neither
    `enabled` nor `echo` set false."""
    ado = (meta or {}).get("ado")
    return (isinstance(ado, dict) and ado.get("enabled") is not False
            and ado.get("echo") is not False)


def ado_echo_lines(ctx):
    """The echo owed for this call's transitions: every task it closed or
    blocked, and the phase it signed off, that carries an `ado` link - the
    board update the main loop makes, since no verb here sends one. Empty when
    the plan has no board or nothing linked moved."""
    moved = []
    for did in ctx["did"]:
        word = did.split(" ", 1)
        if word[0] in (CLOSED, "blocked") and len(word) > 1:
            moved.append(word[1].split(" ", 1)[0])
        elif did == "signed off":
            moved.append(ctx["phase"])
    if not moved:
        return []
    try:
        manifest = _mio.load_manifest(ctx["manifest"])
    except Exception as exc:                                   # noqa: BLE001
        return ["ado echo: not judged - the plan could not be read (%s)" % (exc,)]
    if not _ado_on(manifest.get("meta")):
        return []
    nodes = dict(_mio.tasks_by_id(manifest))
    nodes.update((p.get("id"), p) for p in manifest.get("phases") or []
                 if isinstance(p, dict))
    linked = [i for i in moved if ((nodes.get(i) or {}).get("ado") or {}).get("id")]
    if not linked:
        return []
    return step_text("ado-echo", items=", ".join(linked))


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
        lines.extend(ado_echo_lines(ctx))
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
    nxt.add_argument("phase", help="the phase id, or a task id to drive that "
                                   "one task")
    nxt.add_argument("manifest", nargs="?", default=None,
                     help="the manifest (default: the project's configured one)")
    nxt.add_argument("--project-dir", dest="project_dir", default=None)
    nxt.add_argument("--answer", default=None,
                     help="answer the pending decision with one of its options")
    nxt.add_argument("--reason", default=None,
                     help="the reason an option that records one needs; for "
                          "the triage's sign-off, the phase's summary")
    nxt.add_argument("--fix", action="append", default=[],
                     metavar="FINDING[,FINDING]",
                     help="with --answer fix: the findings to fix, each "
                          "becoming a task through `add --fixes`")
    nxt.add_argument("--verbose", action="store_true",
                     help="print each verb's run above the instruction")
    sbm = sub.add_parser("submit", help="file an agent's return, read on stdin: "
                         "the stamp taken, the red-first helper run, then filed once")
    sbm.add_argument("id", help="the task id, or the phase id of a phase review")
    sbm.add_argument("manifest", nargs="?", default=None,
                     help="the manifest (default: the project's configured one)")
    sbm.add_argument("--role", required=True, choices=_fr.RETURN_ROLES)
    sbm.add_argument("--head", default=None, metavar="SHA",
                     help="a phase review's head, as its brief names it")
    sbm.add_argument("--project-dir", dest="project_dir", default=None)
    sbm.add_argument("--case", action="append", default=[],
                     help="passed to the red-first helper; needs a test command")
    sbm.add_argument("--introduces", action="append", default=[],
                     help="passed to the red-first helper; needs a test command")
    sbm.add_argument("--deps-from", dest="deps_from", default=None,
                     help="passed to the red-first helper; needs a test command")
    sbm.add_argument("--verbose", action="store_true",
                     help="print each verb's run above the result")
    return _claude_home.attach_usage_hint(parser)


def project_context(args):
    """`(manifest, ctx)` - what every action resolves once - or raises
    ValueError naming why not."""
    project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR")
                              or os.getcwd())
    named = args.manifest
    # A brief prints the manifest relative to the project, and an agent's shell
    # may stand anywhere; a relative path that is not there from here is read
    # from the project it names.
    if named and not os.path.isabs(named) and not os.path.exists(named):
        named = os.path.join(project, named)
    found = _mio.resolve_manifest(project, named)
    if not found.get("path"):
        raise ValueError(found.get("problem") or "no manifest at %s" % (
            ", ".join(p for p, _w in found.get("looked") or []),))
    manifest_path = os.path.abspath(found["path"])
    manifest = _mio.load_manifest(manifest_path)
    project, config = _evio.project_config_for(manifest_path, project)
    return manifest, {
        "project": project, "manifest": manifest_path, "phase": None,
        "config": config,
        "gitRoot": os.path.abspath(os.path.join(
            project, (config or {}).get("gitRoot") or ".")),
        "evidence": _evio.evidence_dir(project, config),
        "verbose": bool(args.verbose), "log": [], "did": []}


def task_phase(manifest, task_id):
    """The id of the phase holding task `task_id`, or None."""
    for phase in manifest.get("phases") or []:
        if isinstance(phase, dict) and any(
                isinstance(t, dict) and t.get("id") == task_id
                for t in phase.get("tasks") or []):
            return phase.get("id")
    return None


def context(args):
    """Everything one `next` resolves once, or raises ValueError naming why not.
    A task id in the phase's place scopes the drive to that one task."""
    manifest, ctx = project_context(args)
    phase_id, problem = _mio.resolve_phase_id(manifest, args.phase)
    ctx["only"] = None
    if problem:
        phase_id = task_phase(manifest, args.phase)
        if phase_id is None:
            raise ValueError("%s; and no task has the id %r" % (problem, args.phase))
        ctx["only"] = args.phase
    hc = _loader.load_hooks_config(modname="audit__config")
    ctx.update(phase=phase_id, stateDir=str(
        hc.state_dir(pathlib.Path(ctx["project"]), ctx["config"] or {})))
    return ctx


def run_submit(args, cmd, out, stdin):
    if (args.case or args.introduces or args.deps_from) and not cmd:
        sys.stderr.write("drive-phase.py: --case, --introduces and --deps-from are "
                         "the red-first helper's, and need a test command after "
                         "`--`\n")
        return E_USAGE
    try:
        manifest, ctx = project_context(args)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("drive-phase.py: %s\n" % (exc,))
        return E_USAGE
    if stdin is None:
        stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    ctx["phase"] = args.id
    code, said = submit(ctx, manifest, args, cmd, stdin)
    out(render(ctx, code, said))
    return code


def main(argv, out=print, stdin=None):
    argv = list(argv)
    # Everything after the first `--` is the red-first run's test command, kept
    # from the parser so that command's own flags are never read as these.
    cmd = argv[argv.index("--") + 1:] if "--" in argv else None
    argv = argv[:argv.index("--")] if "--" in argv else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    if args.action == "submit":
        return run_submit(args, cmd, out, stdin)
    if cmd is not None:
        sys.stderr.write("drive-phase.py: only `submit` takes a command after "
                         "`--`\n")
        return E_USAGE
    try:
        ctx = context(args)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("drive-phase.py: %s\n" % (exc,))
        return E_USAGE
    try:
        fixes = [f.strip() for given in args.fix for f in given.split(",")
                 if f.strip()]
        code, said = drive(ctx, answer=args.answer, reason=args.reason,
                           fixes=fixes)
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
