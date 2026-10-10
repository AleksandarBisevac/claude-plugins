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
The triage also puts to a human what the review answered that only a human
settles - a task that diverges, a red-first not proved - and refuses
`sign-off` until `accept` gives their reason. Every decision a human can say
no to - those answers, the runtime boot, the gate's banners, an invariant
breach - takes `decline`, which keeps their words and hands back to the work;
an accept or a boot holds only at the HEAD it was given at. The triage lists
a fix task closed after the review's head with `re-review` beside it, and
dispatches the review again when a task added since is owed its answers.
Answered `sign-off` with the summary, one `next` runs the phase gate, the
invariants check, the sign-off verb, the commit, the landing and the lock
release, and prints `done`. A red phase gate stops that step before the
sign-off verb: the verdict is never recorded over it.

THE SIGN-OFF CAN BE SENT BEFORE THE TRIAGE IS PRINTED. The phase reviewer's
dispatch also prints the call to send after the review files, `next <phase>
--answer sign-off --reason <the summary>`. That call is taken only once every
task is terminal (`advance_admissible`); it is applied only where the triage
it answers would offer nothing else - a `clean` review, no finding open, no
answer waiting on a human, no fix task closed after the review's head
(`advance_applies`). Anywhere else that triage is printed as before and the
did-line says the answer was not applied, so a finding or a human's answer
still stops at the triage, and the main loop can still hold the landing by
not sending the call.

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

ONE TASK AT A TIME IN THE PHASE TREE, IN ID ORDER. A recorded gate run while
sibling executors edit the same tree measures their half-finished work, so two
tasks never share it; `next_task` is the one place the serial choice is made.

SEVERAL AT ONCE ONLY IN TREES OF THEIR OWN - A WAVE. `executor.waveWidth` above 1
(an int, or `auto`: the core count less two) lets `next` open a wave when no task
is in progress and `_wave.select` picks two or more ready tasks with disjoint
declared files. Each member is started and given a detached worktree at the
phase HEAD (`manage-worktrees.py task-add`), and one print dispatches every
member's executor together. Each `next` walks the members in id order through
the same `advance`, with the gate measured in the member's tree (`run-test-gate.py
--tree`) and its stamp graded there; before the close, `integrate-task.py`
carries the tree's bytes into the phase tree, a re-gate runs on the phase tree
when the integration overlapped a sibling or cannot say, and the close is the
serial one. A member's decision is parked while a sibling still has a step due,
so a red sibling holds back no green one. A closed member's tree is taken down
when it holds nothing the phase tree lacks; when every member is terminal or
blocked the wave ends and the next is selected. An absent width, or 1, never
reaches any of this: the drive is the serial one, row for row.

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
    under `--head`, go to the same verb unchanged;
  * the last line printed is the hand-back - the filed line above it, or the
    refusal above it verbatim, as the agent's whole reply (`handback_lines`).
    It sits where the agent reads last, and the prompts no longer state it.

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
import _manifest_phases as _phases  # noqa: E402  (FINDING_FIELDS: what a finding is)
import _evidence_io as _evio  # noqa: E402  (project_config_for, evidence_dir)
import _journal_io  # noqa: E402  (read_all: a high-risk answer given before the run)
import _filed_returns as _fr  # noqa: E402  (where a filed return lives, and its read;
#                                            the per-task review key a task holds;
#                                            the driver's state path, needs_human)
import _config_rules  # noqa: E402  (review_per_task_mode: the config's reading now)
import _areas  # noqa: E402  (resolve_review_skill: whether the phase review has a skill)
import _status_facts  # noqa: E402  (ready_tasks: the one readiness rule)
import _verdict_binding as _vb  # noqa: E402  (phase_binding: whether a held phase
#                                              gate run is still the one sign-off binds)
import _wave  # noqa: E402  (select: which ready tasks may run together)

E_OK, E_STOPPED, E_USAGE = 0, 1, 2
PREFIX = "[drive-phase]"

# The bound every print that is not a stop stays inside. A stop prints a verb's
# own words whole, so it is the one print that may run longer.
INSTRUCTION_BYTES = 300

EXECUTOR_AGENT = "audit:audit-executor"
REVIEWER_AGENT = "audit:audit-reviewer"

# The words the did-line uses for a task the driver started or closed. They are
# what `did_tasks` reads back, and what `tools/stream-cost.py` reads a driver
# session's task cycle from - the driver's own start and close happen in its
# subprocesses, where the session's stream cannot see them.
STARTED, CLOSED = "started", "closed"
# The did-line words for the steps after the task cycle, read back by
# `did_events` - stream-cost's sign-off, fix-task and close spans. A fix task
# added inside the driver, its landing and its lock release happen in
# subprocesses too, so a session's stream sees no planning verb, no landing and
# no release of its own.
FIX_ADDED = "fix task"            # "fix task <id> added for <finding>"
SIGNED = "signed off"
LANDED = "landed"                 # "landed (<close-phase's line>)"
RELEASED = "lock released"


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
# A wave's dispatches are one print, one line per member: sent together, each
# member works in its own tree, and the next `next` reads every return.
WAVE_RULE = "dispatch these together in one message; then next"
UNBLOCK_RULE = ("A blocked task moves only on a human's yes, then next again; "
                "each task's remedy is named above.")
# The remedy line under a blocked stop, one entry per blocked task, rendered by
# `blocked_remedy` from the task's attempts.
REMEDY_HEAD = "remedy (audit-task.py): "
# The triage's rule when a reviewer's answer waits on a human; printed only then,
# so a clean review's triage carries no line it does not need.
ANSWERS_RULE = ("Each [accept] line is the human's to settle (AskUserQuestion): "
                "accept on their yes, decline on their no, with their words.")
# What a `decline` hands back when no task is open to run: the remedy is work,
# and work enters the plan as a task.
DECLINE_REMEDY = ("Add the task that answers it: audit-task.py add \"<the fix>\" "
                  "--phase %s --files <files>, then next %s")
# The call the phase reviewer's dispatch prints to send once it files: the
# triage's `sign-off`, answered before the triage is printed. It is applied only
# where that triage would admit no other answer (`advance_applies`); anywhere
# else the triage prints and the did-line says the answer was not applied.
ADVANCE_ANSWER = "sign-off"
ADVANCE_LINE = "then: next %(phase)s --answer sign-off --reason <the summary>"
ADVANCE_NOT_APPLIED = "sign-off answered in advance, not applied: %s"
STEPS = {
    "dispatch-executor": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "dispatch-reviewer": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "dispatch-wave": {
        "line": "dispatch %(agent)s %(task)s model=%(model)s brief=%(brief)s",
        "rule": (WAVE_RULE,)},
    "decide-integration-refused": {
        "line": "decide integration-refused %(task)s: %(why)s",
        "rule": ("retry recuts its tree at the phase HEAD and spends an attempt; "
                 "block keeps the tree and tells the human.",)},
    "decide-undeclared-change": {
        "line": "decide undeclared-change %(task)s: changed outside its files: "
                "%(why)s",
        "rule": ("widen declares them and re-gates; discard drops them; block "
                 "keeps the tree. Never drop one silently.",)},
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
        "rule": ("Ask the human (AskUserQuestion); continue only on their yes, "
                 "their words verbatim as --reason.",)},
    "decide-stalled": {
        "line": "decide stalled %(phase)s: no task is ready - %(why)s",
        "rule": (UNBLOCK_RULE,)},
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
        "line": "decide not-fast-forward %(phase)s: the parent moved, so "
                "close-phase made no merge (%(why)s)",
        "rule": ("Ask the human; never rebase - it rewrites the task commit SHAs.",)},
    "decide-runtime-boot": {
        "line": "decide runtime-boot %(phase)s: meta.runtimeBoot is set and the "
                "phase touched %(why)s",
        "rule": ("Cold-boot per meta.runtimeBoot: primary screen, one navigation "
                 "away and back. Unreachable: ask the human.",)},
    "decide-gate-coverage": {
        "line": "decide gate-coverage %(phase)s: the green phase gate printed "
                "%(why)s",
        "rule": ("A gate that ran none of this work, or beside a changed tree, may "
                 "grade nothing: ask the human; the reason is kept.",)},
    "done": {
        "line": "done %(phase)s: %(why)s",
        "rule": ("Report where it landed: a parent that is not the development "
                 "branch does not hold the work yet.",)},
    "done-task": {
        "line": "done %(task)s: %(why)s",
        "rule": ()},
    "ado-echo": {
        "line": "ado echo owed: %(items)s",
        "rule": ("Update each item's board state only: never create one, never ask, "
                 "no retry; a failure is one report line - /audit:sync push mends it.",)},
    "stop-blocked": {
        "line": "[drive-phase] %(phase)s: stopped - %(task)s is blocked: %(why)s",
        "rule": (UNBLOCK_RULE,)},
    "stop-lock": {
        "line": "",
        "rule": ("Held by a live run: stop, never take it over. Looks abandoned: "
                 "ask the human before --takeover.",)},
    "stopped": {
        "line": "",
        "rule": ("Relay these words and act on the remedy they name; never edit "
                 "the plan or the journal by hand to get past them.",)},
    # The agent's, not the main loop's: `submit`'s last line, the last thing the
    # agent reads before it replies. Its prompt no longer states the hand-back,
    # so this print is the one place it is said; nothing enforces it, and the
    # report bytes a session's agents wrote are its reading.
    "handback-filed": {
        "line": "hand back the line above as your whole reply",
        "rule": ()},
    "handback-refused": {
        "line": "hand back the refusal above verbatim as your whole reply",
        "rule": ()},
}

# Each decision's options, and the ones that need `--reason`. A decision with no
# options is one only the plan can change; nothing here answers it.
DECISIONS = {
    "gate-red": (("retry", "rerun", "block"), ("block",)),
    "no-executor-return": (("retry", "block"), ("block",)),
    "no-reviewer-return": (("redispatch", "not-asked"), ("not-asked",)),
    "high-risk": (("confirm", "block"), ("block",)),
    "no-change": (("no-change", "retry"), ("no-change",)),
    # A wave member's integration onto the phase tree: refused by name (a
    # conflict, a lockfile, a dirty phase tree), or owed a word on paths the
    # task changed and never declared.
    "integration-refused": (("retry", "block"), ("block",)),
    "undeclared-change": (("widen", "discard", "block"), ("block",)),
    "review-answer": (("continue",), ("continue",)),
    "stalled": ((), ()),
    # `accept` settles the reviewer answers a human decides and `decline` is
    # their no, and `re-review` dispatches the phase review again over fix
    # tasks it never saw; the triage refuses each where it has nothing to act
    # on (`answer_refusal`). Every decision a human can say no to takes
    # `decline`, which hands back to the work (`decline_answer`).
    "triage": (("sign-off", "fix", "accept", "decline", "re-review"),
               ("sign-off", "accept", "decline")),
    "no-phase-review-return": (("redispatch",), ()),
    "invariant-breach": (("accept", "decline"), ("accept", "decline")),
    "gate-coverage": (("accept", "decline"), ("accept", "decline")),
    "runtime-boot": (("booted", "not-reachable", "decline"),
                     ("booted", "not-reachable", "decline")),
    "not-fast-forward": (("no-ff", "leave"), ("leave",)),
}
# The decisions sign-off owns, answered by `apply_phase_answer`.
PHASE_DECISIONS = ("triage", "no-phase-review-return", "invariant-breach",
                   "gate-coverage", "runtime-boot", "not-fast-forward")

# --- sign-off's constants -------------------------------------------------------
# The triage print holds one line per open finding, so it is bounded per line
# rather than as a whole: a review with many findings is a longer decision, not a
# cut one.
TRIAGE_LINE_BYTES = 160
# What a fix task is predicted to cost, in USD-equivalent: the sign-off with a
# fix task less the sign-off without, in two benchmark sessions of the plugin's
# own cost work. A prediction for a task of that benchmark's size, never a
# measurement of this project's - and the printed basis says only that, since
# the document the range came from is not part of an install.
FIX_TASK_PREDICTED = (0.1045, 0.1192)
FIX_TASK_PRICE_BASIS = ("a benchmark prediction for a small task, not this "
                        "project's measurement")
# The gate's banners a green exit still prints, and the clause each becomes.
GATE_BANNERS = (("NO OVERLAP WITH THIS WORK", "NO OVERLAP"),
                ("TREE CHANGED OUTSIDE THIS WORK", "TREE CHANGED"))
# The journal row `record-risk-confirmation.py` writes, and the sentence its
# summary carries the covered ids in. An entry point may not import another,
# so both are spelled here; the `hr` cases drive the real verb, which is what
# goes red if either drifts.
RISK_CONFIRMED = "risk.confirmed"
RISK_COVERED = "%s: high-risk commits confirmed in advance for "
# The journal row `audit-task.py reopen` writes; `hr3` drives the real verb.
TASK_REOPEN = "task.reopen"
TRUNCATED = " [truncated]"
# The verdict sign-off records, and the word a phase's review status carries
# once it is recorded.
SIGNED_OFF = ("passed", "skipped")
_BRIEF_HEAD = re.compile(r"^head: ([0-9a-f]{7,40})\s*$", re.M)
_RUN_ID = re.compile(r"evidence: recorded (\S+)")
# close-phase's lines for a landing whose `mergedAt` stamp it did not commit:
# skipped, opening with the path the stamp sits in, or a commit that failed.
_STAMP_LEFT = re.compile(r"the stamp is not committed here: (\S+)")
_STAMP_FAILED = re.compile(r"the stamp is NOT committed: (.+)")


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


def did_events(text):
    """`{"started", "closed", "added": [ids], "signedOff", "landed", "released"}`
    - what a driver's printed text says it did, read off its did-lines only,
    one `; `-separated clause at a time."""
    found = dict(did_tasks(text), added=[], signedOff=False, landed=False,
                 released=False)
    for line in (text or "").splitlines():
        if not line.startswith(PREFIX):
            continue
        for clause in line.partition(": ")[2].split("; "):
            words = clause.split(" ")
            if clause.startswith(FIX_ADDED + " ") and words[3:5] == ["added", "for"]:
                found["added"].append(words[2])
            elif clause == SIGNED:
                found["signedOff"] = True
            elif words[0] == LANDED:
                found["landed"] = True
            elif clause == RELEASED:
                found["released"] = True
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
    return _fr.drive_state_path(ctx["stateDir"], ctx["phase"])


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


def record_gate(ctx, phase, task, tree=None):
    """`(code, stdout, stderr)` of the task's recorded gate run - measured in
    `tree` when the task runs in a tree of its own, and recorded in the
    project's ledger either way."""
    return run_verb(ctx, "run-test-gate.py", [
        ctx["manifest"], phase["id"], "--task", task["id"], "--record",
        "--project-dir", ctx["project"]] + (["--tree", tree] if tree else []))


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


def grade_stamp(ctx, stamp, tree=None):
    """The did-line clause for the executor's stamp, graded against the tree it
    was taken in as it stands now - the task's own tree in a wave, else the
    phase tree: current, stale with the fields that moved, or why it could not
    be graded."""
    if not isinstance(stamp, str) or not stamp.strip():
        return "stamp not graded (the return carries none)"
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "compare", "--project", tree or ctx["gitRoot"], "--stamp", stamp, "--json"])
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


def advance(ctx, state, manifest, phase, task, tree=None):
    """The next due step for the task the drive is on; None when the drive goes
    on to the next task, else what to print. `tree` is the task's own worktree
    when it runs in a wave: its gate is measured there, its stamp graded there,
    and its bytes are integrated into the phase tree before the close."""
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
        code, out, err = (record_gate(ctx, phase, task, tree=tree) if tree
                          else record_gate(ctx, phase, task))
        if code == 1:
            said = [ln for ln in (out + err).splitlines() if "GATE" in ln]
            return decision(ctx, state, "gate-red", task,
                            (said[0].strip() if said else "exit 1")[:80])
        if code != 0:
            return relay_refusal(ctx, "run-test-gate.py", code, out + err)
        _mark(state, "gated", task)
        write_state(ctx, state)
        banners = gate_banners(out + err)
        ctx["did"].append("gate %s green%s" % (task["id"], " (%s)" % (
            "; ".join(banners),) if banners else ""))
        ctx["did"].append(grade_stamp(ctx, executor.get("stamp"), tree)
                          if tree else grade_stamp(ctx, executor.get("stamp")))
    if due and reviewer is None:
        return dispatch(ctx, state, phase, task, "reviewer")
    if task.get("risk") == "high" and not _marked(state, "confirmed", task):
        if task["id"] not in confirmed_in_advance(ctx, phase["id"]):
            return decision(ctx, state, "high-risk", task, "")
        _mark(state, "confirmed", task)
        write_state(ctx, state)
        ctx["did"].append("high-risk %s confirmed in advance" % (task["id"],))
    if tree:
        said = integrate_member(ctx, state, phase, task)
        if said is not None:
            return said
    if key == "signals" and not due:
        return close_task(ctx, state, phase, task, intent_basis=(
            "review.perTask signals: no signal fired - red-first proved and the "
            "return's gates agree with the recorded green"))
    if key == _fr.KEY_PHASE and _fr.is_fix_task(task, phase):
        # A fix task closes `not-asked`, the answer the landing takes from one;
        # its diff is the triage's to put to a re-review (`fixes_after`).
        return close_task(ctx, state, phase, task, intent_basis=(
            "a fix task for %s: the phase review raised the finding; the fix's "
            "own diff is unreviewed unless sign-off re-reviews it"
            % (", ".join(str(f) for f in task.get("fixes") or []),)))
    return close_task(ctx, state, phase, task)


def gate_banners(text):
    """The clauses for the banners a green gate printed - a run that named none
    of the work's paths, a tree changed outside the work - in a fixed order."""
    lines = (text or "").splitlines()
    return [clause for banner, clause in GATE_BANNERS
            if any(ln.startswith(banner) for ln in lines)]


def confirmed_in_advance(ctx, phase_id):
    """The task ids a `risk.confirmed` row of this phase names - the answer to
    the high-risk gate given before the run, for exactly the tasks it covered.
    A clipped summary's last id may be cut, so it is not read as covered, and a
    journal that cannot be read covers nothing: the gate then asks, as it would
    with no answer given. The answer covers open work as it stood when it was
    given, so a `task.reopen` row after it takes the task back out: its next
    run is a commit nobody confirmed. The rows are read oldest first."""
    try:
        rows = _journal_io.read_all(ctx["project"])
    except Exception:                                          # noqa: BLE001
        return set()
    head = RISK_COVERED % (phase_id,)
    covered = set()
    for row in rows:
        summary = str(row.get("summary") or "")
        if row.get("action") == TASK_REOPEN:
            covered.discard(str((row.get("details") or {}).get("taskId")))
            continue
        if row.get("action") != RISK_CONFIRMED or str(row.get("target")) != phase_id \
                or not summary.startswith(head):
            continue
        ids = summary[len(head):]
        clipped = ids.endswith(TRUNCATED)
        ids = [i.strip() for i in ids[:-len(TRUNCATED)].split(",")] if clipped \
            else [i.strip() for i in ids.split(",")]
        covered.update(i for i in (ids[:-1] if clipped else ids) if i)
    return covered


# --- waves: ready disjoint tasks, each in a tree of its own ---------------------
# The journal actions a wave writes. Free strings, as every action is; the `wv`
# cases pin the sequence one wave writes.
WAVE_START, WAVE_DONE = "wave.start", "wave.done"
TASK_WORKTREE = "task.worktree"
TASK_INTEGRATED, TASK_INTEGRATION_REFUSED = "task.integrated", "task.integration.refused"
# `integrate-task.py`'s exit codes and its state file's name. An entry point may
# not import another, so they are mirrored here; the `wv`/`wc` cases drive the
# real verb, which is what goes red if either drifts.
INTEGRATE_REFUSED, INTEGRATE_DECIDE = 1, 3
INTEGRATION_STATE = "audit-wave-integration.json"
# `manage-worktrees.py task-add`'s exit when the tree was made and its declared
# setup failed in it: could-not-run, never a red.
SETUP_FAILED = 6
# Returned by `wave_step` when no wave applies, so the serial step runs; None
# already means "a step was taken, go round again".
NO_WAVE = object()


def wave_width(config):
    """`(width, basis, problem)` - how many tasks run at once, and the words
    that say why: `executor.waveWidth` as `_config_rules.wave_width_setting`
    reads it, with `auto` resolved to the core count less two (at least 1). A
    value outside the vocabulary is `(None, None, problem)`, never 1."""
    value, problem = _config_rules.wave_width_setting(config)
    if problem:
        return None, None, problem
    executor = (config or {}).get("executor")
    if value != _config_rules.WAVE_WIDTH_AUTO:
        said = ("executor.waveWidth %d" % (value,)
                if isinstance(executor, dict) and "waveWidth" in executor
                else "executor.waveWidth absent, so 1")
        return value, said, None
    cores = os.cpu_count()
    if not cores:
        return 1, "auto: the core count is unknown, so 1", None
    return max(1, cores - 2), "auto: %d cores less two" % (cores,), None


def _id_key(task_id):
    """A task id in natural order: `P1.10` after `P1.9`, not after `P1.1`."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in re.split(r"[.]", str(task_id))]


def wave_row(ctx, action, summary, details):
    """One journal row for a wave step, written the way a plugin script run
    from Bash writes one. A row the journal would not take is said on the
    did-line rather than dropped."""
    entry = {"action": action, "summary": summary, "details": details,
             "target": _output.posix_rel(ctx["manifest"], ctx["project"]),
             "actor": {"sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                       "via": "cli"}}
    written, why = _journal_io.append_from_cli_why(ctx["project"], entry)
    if not written:
        ctx["did"].append("journal row %s not written (%s)" % (action, why))


def tree_path(ctx, task_id):
    """`--path` for a task's tree when `executor.worktreeRoot` names a root -
    `<root>/<repo>-<taskId>`, a relative root read from the git root - else None,
    and `task-add` places it beside the git root."""
    root = ((ctx["config"] or {}).get("executor") or {}).get("worktreeRoot")
    if not isinstance(root, str) or not root.strip():
        return None
    root = os.path.abspath(os.path.join(ctx["gitRoot"], root))
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", str(task_id)).strip(".-") or "task"
    return os.path.join(root, "%s-%s" % (os.path.basename(ctx["gitRoot"]), safe))


def add_tree(ctx, state, task):
    """`(path, None)` - the task's tree, made detached at the wave's base and
    recorded - or `(None, stop)`."""
    wave = state["wave"]
    args = ["task-add", ctx["manifest"], task["id"], "--base", wave["base"],
            "--project", ctx["project"], "--json"]
    where = tree_path(ctx, task["id"])
    if where:
        args += ["--path", where]
    code, out, err = run_verb(ctx, "manage-worktrees.py", args)
    try:
        made = json.loads(out)
    except ValueError:
        made = {}
    path = made.get("path") if isinstance(made, dict) else None
    if code == SETUP_FAILED and path:
        wave["trees"][task["id"]] = path
        write_state(ctx, state)
        return None, _stopped(ctx, "the tree of %s was made, and its setup did "
                              "not complete - could not run, not red, and no "
                              "attempt is spent: %s" % (
                                  task["id"], _clip(made.get("error") or "", 200)))
    if code != 0 or not path:
        return None, relay_refusal(ctx, "manage-worktrees.py", code, out + err)
    wave["trees"][task["id"]] = path
    write_state(ctx, state)
    setup = (made.get("setup") or {}).get("status") or "none"
    wave_row(ctx, TASK_WORKTREE, "%s: a worktree of its own at %s (setup %s)" % (
        task["id"], wave["base"][:12], setup), {
            "taskId": task["id"], "phaseId": ctx["phase"], "commit": wave["base"],
            "mode": "setup %s" % (setup,)})
    ctx["did"].append("tree for %s" % (task["id"],))
    return path, None


def reopen_integration(ctx, task_id):
    """Let `integrate-task.py` carry a task's tree again after a new start: its
    state calls (task, base) done once, so the entry is marked reopened. The
    paths stay, so the bytes the last integration placed are still read as
    this task's, not as a stray change in the phase tree."""
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "rev-parse",
                               "--git-path", INTEGRATION_STATE],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return
    rel = done.stdout.strip()
    path = rel if os.path.isabs(rel) else os.path.join(ctx["gitRoot"], rel)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError):
        return
    entry = ((body.get("tasks") if isinstance(body, dict) else None) or {}).get(task_id)
    if not isinstance(entry, dict) or entry.get("status") != "done":
        return
    entry["status"] = "reopened"
    _mio.atomic_write_text(path, json.dumps(body, indent=2, sort_keys=True) + "\n")


def integrate_member(ctx, state, phase, task):
    """Carry a wave member's tree into the phase tree once per start, and
    re-gate on the phase tree where the integration overlapped a sibling or
    cannot say whether it did. None when the close may run, else the decision
    or the stop."""
    held = _marked(state, "integrated", task)
    if held is None:
        prior = (state.get("integrated") or {}).get(task["id"])
        if prior:
            reopen_integration(ctx, task["id"])
        word = _marked(state, "undeclared", task) or {}
        if word.get("answer") == "widen":
            files = list(task.get("files") or [])
            files += [p for p in word.get("paths") or [] if p not in files]
            _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
                ctx, "scope", task["id"], "--files", ",".join(files)))
            if stop is not None:
                return stop
            ctx["did"].append("%s widened by %d path(s)" % (
                task["id"], len(word.get("paths") or [])))
        args = [ctx["manifest"], task["id"], "--project", ctx["project"], "--json"]
        if word.get("answer"):
            args += ["--undeclared", word["answer"]]
        code, out, err = run_verb(ctx, "integrate-task.py", args)
        try:
            answer = json.loads(out)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            return relay_refusal(ctx, "integrate-task.py", code, out + err)
        if code == INTEGRATE_DECIDE:
            paths = (answer.get("decision") or {}).get("paths") or []
            return decision(ctx, state, "undeclared-change", task,
                            _clip(", ".join(paths), 120), extra={"paths": paths})
        if code == INTEGRATE_REFUSED:
            refused = answer.get("refused") or {}
            wave_row(ctx, TASK_INTEGRATION_REFUSED, "%s: integration refused "
                     "(%s): %s" % (task["id"], refused.get("kind"),
                                   ", ".join(refused.get("paths") or [])), {
                         "taskId": task["id"], "phaseId": ctx["phase"],
                         "mode": refused.get("kind"),
                         "changes": [{"id": t, "field": "task"}
                                     for t in refused.get("tasks") or []]
                         + [{"id": p, "field": "path"}
                            for p in refused.get("paths") or []]})
            return decision(ctx, state, "integration-refused", task, _clip(
                "%s, %s (tasks %s)" % (refused.get("kind"), ", ".join(
                    refused.get("paths") or []) or "no path",
                    ", ".join(refused.get("tasks") or [])), 140))
        if code != 0:
            return relay_refusal(ctx, "integrate-task.py", code, out + err)
        regate = answer.get("regate")
        if word.get("answer") == "widen":
            regate = True
        held = {"regate": regate}
        _mark(state, "integrated", task, held)
        write_state(ctx, state)
        wave_row(ctx, TASK_INTEGRATED, "%s: %d path(s) integrated%s" % (
            task["id"], len(answer.get("paths") or []),
            "; overlaps %s" % (", ".join(answer.get("overlapWith") or []),)
            if answer.get("overlapWith") else ""), {
                "taskId": task["id"], "phaseId": ctx["phase"],
                "commit": answer.get("base"), "parent": answer.get("headBefore"),
                "mode": "regate %s" % ({True: "true", False: "false"}.get(
                    regate, "unknown"),),
                "changes": [{"id": p, "field": "path"}
                            for p in answer.get("paths") or []]})
        ctx["did"].append("integrated %s%s" % (task["id"], " (already)"
                                               if answer.get("already") else ""))
    if held.get("regate") is not False and not _marked(state, "regated", task):
        code, out, err = record_gate(ctx, phase, task)
        if code == 1:
            said = [ln for ln in (out + err).splitlines() if "GATE" in ln]
            return decision(ctx, state, "gate-red", task, (
                "re-gate on the phase tree: %s" % (
                    said[0].strip() if said else "exit 1",))[:80])
        if code != 0:
            return relay_refusal(ctx, "run-test-gate.py", code, out + err)
        _mark(state, "regated", task)
        write_state(ctx, state)
        ctx["did"].append("re-gate %s green" % (task["id"],))
    return None


def tree_holds_only_integrated(ctx, tree):
    """True when every path the tree changed holds the bytes the phase tree
    holds - nothing in it would be lost with it; False when one differs; None
    when git could not say."""
    try:
        done = subprocess.run(["git", "-C", tree, "status", "--porcelain", "-z",
                               "--untracked-files=all", "--no-renames"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    for item in done.stdout.split(b"\0"):
        rel = item[3:].decode("utf-8", "replace")
        if not rel:
            continue
        sides = []
        for root in (tree, ctx["gitRoot"]):
            try:
                with open(os.path.join(root, rel), "rb") as fh:
                    sides.append(fh.read())
            except OSError:
                sides.append(None)
        if sides[0] != sides[1]:
            return False
    return True


def retire_member(ctx, state, task):
    """Take down a closed member's tree when it holds nothing the phase tree
    lacks; otherwise keep it and say so. A blocked member's tree is kept for
    whoever unblocks it. None, or the stop."""
    wave = state["wave"]
    tree = (wave.get("trees") or {}).get(task["id"])
    if not tree or task["id"] in (wave.get("retired") or []):
        return None
    if task.get("status") not in _mio.TERMINAL:
        return None
    wave.setdefault("retired", []).append(task["id"])
    clean = tree_holds_only_integrated(ctx, tree) if os.path.isdir(tree) else True
    if clean is not True:
        write_state(ctx, state)
        ctx["did"].append("tree of %s kept (%s)" % (task["id"], "it holds bytes the "
                                                    "phase tree lacks" if clean is False
                                                    else "git could not describe it"))
        return None
    if os.path.isdir(tree):
        _out, stop = _verb_or_stop(ctx, "manage-worktrees.py", [
            "task-remove", ctx["manifest"], task["id"], "--project", ctx["project"],
            "--force"])
        if stop is not None:
            return stop
    wave["trees"].pop(task["id"], None)
    write_state(ctx, state)
    ctx["did"].append("tree of %s removed" % (task["id"],))
    return None


def drop_tree(ctx, state, task_id):
    """Take a member's tree down whatever it holds - a retry the human chose
    recuts it at the phase HEAD - so the walk makes a fresh one. None, or the
    stop."""
    wave = state.get("wave") or {}
    tree = (wave.get("trees") or {}).get(task_id)
    if not tree:
        return None
    if os.path.isdir(tree):
        _out, stop = _verb_or_stop(ctx, "manage-worktrees.py", [
            "task-remove", ctx["manifest"], task_id, "--project", ctx["project"],
            "--force"])
        if stop is not None:
            return stop
    wave["trees"].pop(task_id, None)
    wave["base"] = git_head(ctx) or wave.get("base")
    write_state(ctx, state)
    return None


def open_wave(ctx, state, picked, width, basis):
    """Record a wave of `picked` at the phase HEAD, and its `wave.start` row."""
    base = git_head(ctx)
    if not base:
        return _stopped(ctx, "git named no HEAD in %s, so a wave has no commit to "
                        "cut its trees from" % (ctx["gitRoot"],))
    number = int(state.get("waves") or 0) + 1
    state["waves"] = number
    state["wave"] = {"id": "%s-w%d" % (ctx["phase"], number), "base": base,
                     "tasks": list(picked), "width": width, "widthBasis": basis,
                     "trees": {}, "parked": {}}
    write_state(ctx, state)
    wave_row(ctx, WAVE_START, "%s: %s at width %d (%s), base %s" % (
        state["wave"]["id"], ", ".join(picked), width, basis, base[:12]), {
            "phaseId": ctx["phase"], "commit": base, "basis": basis,
            "mode": "width %d" % (width,),
            "changes": [{"id": t, "field": "task"} for t in picked]})
    ctx["did"].append("wave of %s at width %d (%s)" % (", ".join(picked), width, basis))
    return None


def close_wave(ctx, state, manifest):
    """Every member is terminal or blocked: the `wave.done` row, and the wave
    dropped so the next one is selected."""
    wave = state.pop("wave")
    by_id = _mio.tasks_by_id(manifest)
    ended = [(t, (by_id.get(t) or {}).get("status")) for t in wave["tasks"]]
    write_state(ctx, state)
    wave_row(ctx, WAVE_DONE, "%s: %s" % (wave["id"], ", ".join(
        "%s %s" % pair for pair in ended)), {
            "phaseId": ctx["phase"], "commit": wave.get("base"),
            "changes": [{"id": t, "field": "status", "to": s} for t, s in ended]})
    ctx["did"].append("wave %s done" % (wave["id"],))


def step_member(ctx, state, task_id):
    """One member's due steps until it prints something or stops moving:
    `("dispatch", instruction)`, `("parked", None)`, `("idle", None)` or
    `("stop", stop)`."""
    for _ in range(8):
        manifest, phase = load_phase(ctx)
        task = _mio.tasks_by_id(manifest).get(task_id) or {}
        status = task.get("status")
        if status in _mio.TERMINAL:
            stop = retire_member(ctx, state, task)
            return ("stop", stop) if stop is not None else ("idle", None)
        if status == "blocked":
            return "idle", None
        parked = (state["wave"].get("parked") or {}).get(task_id)
        if parked is not None:
            if pending_still_applies(manifest, parked):
                return "parked", None
            state["wave"]["parked"].pop(task_id, None)
            write_state(ctx, state)
        if status != "in_progress":
            stop = start_task(ctx, task)
            if stop is not None:
                return "stop", stop
            continue
        tree = (state["wave"].get("trees") or {}).get(task_id)
        if not tree:
            tree, stop = add_tree(ctx, state, task)
            if stop is not None:
                return "stop", stop
        said = advance(ctx, state, manifest, phase, task, tree=tree)
        if said is None:
            continue
        if isinstance(said, tuple):
            return "stop", said
        if said["kind"] == "decide":
            state["wave"].setdefault("parked", {})[task_id] = state.pop("pending")
            write_state(ctx, state)
            return "parked", None
        return "dispatch", said
    return "idle", None


def walk_wave(ctx, state):
    """Every member's due steps in id order: one print of every dispatch that
    is due, else - when nothing else is - the first parked decision, else None
    once the wave is through."""
    sent = []
    for task_id in sorted(state["wave"]["tasks"], key=_id_key):
        kind, said = step_member(ctx, state, task_id)
        if kind == "stop":
            return said
        if kind == "dispatch":
            sent.append(said["lines"][0])
    if sent:
        return instruction("dispatch", sent + list(STEPS["dispatch-wave"]["rule"]))
    manifest, _phase = load_phase(ctx)
    by_id = _mio.tasks_by_id(manifest)
    parked = state["wave"].get("parked") or {}
    for task_id in sorted(parked, key=_id_key):
        if pending_still_applies(manifest, parked[task_id]):
            state["pending"] = parked.pop(task_id)
            write_state(ctx, state)
            return render_decision(ctx, state["pending"])
    if all((by_id.get(t) or {}).get("status") in _mio.TERMINAL + ("blocked",)
           for t in state["wave"]["tasks"]):
        close_wave(ctx, state, manifest)
    return None


def wave_step(ctx, state, manifest, phase, width, basis):
    """The wave's step: walk the one open, else open one when no task is in
    progress and `_wave.select` picks two or more ready tasks. NO_WAVE when
    neither applies, so the serial step runs."""
    if not state.get("wave"):
        if width < 2 or any(t.get("status") == "in_progress" for t in _tasks(phase)):
            return NO_WAVE
        ready = set(_status_facts.ready_tasks(manifest))
        picked = _wave.select(sorted((t for t in _tasks(phase) if t["id"] in ready),
                                     key=lambda t: _id_key(t["id"])), width)["wave"]
        if len(picked) < 2:
            return NO_WAVE
        return open_wave(ctx, state, picked, width, basis)
    return walk_wave(ctx, state)


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
        # A finding already naming a fix task that never landed is open, but the
        # verb refuses a second task for it: it is dispositioned, not fixed.
        open_ids = [f.get("id") for f in pending.get("findings") or []
                    if not f.get("fixTask")]
        unknown = [f for f in fixes if f not in open_ids]
        if not fixes or unknown:
            return ("--answer fix names the findings to fix with --fix, from the "
                    "open ones: %s%s" % (", ".join(open_ids) or "none",
                                         "; not open: %s" % (", ".join(unknown),)
                                         if unknown else ""))
    elif fixes:
        return "--fix belongs to --answer fix"
    if pending["decision"] == "triage":
        return triage_refusal(pending, answer)
    return None


def triage_refusal(pending, answer):
    """A triage answer refused for what this triage holds, or None: sign-off
    while a reviewer answer waits on a human, and `accept` or `re-review` where
    there is nothing for it to act on."""
    answers = pending.get("answers") or []
    if answer == "sign-off" and answers:
        return ("sign-off waits on %d reviewer answer(s) a human settles: answer "
                "accept --reason <their word on each> first" % (len(answers),))
    if answer in ("accept", "decline") and not answers:
        return ("no reviewer answer waits on a human here, so %s settles nothing"
                % (answer,))
    if answer == "re-review" and not pending.get("fixesAfter"):
        return "no fix task closed after the review's head, so there is no " \
               "unreviewed diff to re-review"
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
    if pending["decision"] in PHASE_DECISIONS:
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
        if pending["decision"] == "integration-refused":
            # The tree was cut from a base the phase tree has moved past; the
            # retry is cut from the phase HEAD, so its work starts from there.
            stop = drop_tree(ctx, state, task["id"])
            if stop is not None:
                return stop
        return start_task(ctx, task)
    if answer in ("widen", "discard"):
        # Integration asks again with the human's word; a widened scope is
        # declared before it, and the gate is taken again over it after.
        _mark(state, "undeclared", task, {"answer": answer,
                                          "paths": list(pending.get("paths") or [])})
        write_state(ctx, state)
        return None
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
    if answer == "continue":
        # The human's word on a per-task reviewer answer, kept for the summary
        # as the triage's accept is.
        state.setdefault("continued", []).append("%s %s: %s" % (
            pending.get("task"), pending.get("why") or "", reason))
        write_state(ctx, state)
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
        ctx["did"].append(RELEASED)
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


def owed_tasks(ctx, phase):
    """`(ids, problem)` - the tasks a phase review owes its answers: each one
    whose commit no filed phase return answers yet."""
    live, problem = None, None
    if any(t.get("commit") and _fr.review_key(t, phase, None)[1] == "config"
           for t in _tasks(phase)):
        live, problem = _config_rules.review_per_task_mode(ctx["config"])
    if problem:
        return [], problem
    answered = _fr.answered_entries(_fr.phase_returns(ctx["evidence"],
                                                      phase["id"]))
    return [t["id"] for t in _tasks(phase)
            if _fr.owed_answer(t, phase, live, answered)], None


def review_due(ctx, manifest, phase):
    """`(due, problem)` - whether sign-off dispatches the phase reviewer: a
    review skill resolves for the phase, or a task is owed its answers there."""
    skill, _basis = _areas.resolve_review_skill(manifest, phase)
    if skill:
        return True, None
    owed, problem = owed_tasks(ctx, phase)
    return bool(owed), problem


def human_answers(ctx, phase):
    """`[{"key", "who", "what", "note"}]` - every reviewer answer in a filed
    phase return that only a human settles, by `_fr.needs_human`: the one
    predicate the sign-off verb refuses over too, so the triage and the verb
    run by hand cannot disagree about which answers wait on a human. Under
    `always` the per-task reviewer's `review_items` raise the same answers at
    each close; the triage is where every key meets them before the landing."""
    return _fr.needs_human(_fr.phase_returns(ctx["evidence"], phase["id"]))


def is_ancestor(ctx, commit, head):
    """True when `commit` is in `head`'s history, False when it is not, None
    when git cannot say."""
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "merge-base",
                               "--is-ancestor", str(commit), str(head)],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


def fixes_after(ctx, phase, head):
    """The recorded fix tasks closed `not-asked` under the phase key at a
    commit the phase review's `head` does not hold - diffs no review saw. A fix
    task its own per-task reviewer answered was reviewed, so it is not listed.
    One git could not place is listed: an unknown is not a reviewed diff."""
    return [t["id"] for t in _tasks(phase)
            if t.get("commit") and _fr.is_fix_task(t, phase)
            and (t.get("intentCheck") or {}).get("answer") == "not-asked"
            and review_key(ctx, phase, t)[0] == _fr.KEY_PHASE
            and is_ancestor(ctx, t["commit"], head) is not True]


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
    lines = step_text(
        "dispatch-phase-review", agent=REVIEWER_AGENT, phase=phase["id"],
        model=(phase.get("review") or {}).get("model") or "unset",
        brief=project_relative(ctx, brief))
    return instruction("dispatch", lines[:1] + [ADVANCE_LINE % {
        "phase": ctx["phase"]}] + lines[1:])


def filed_at_head(ctx, state, phase):
    """The phase review mark for a return already filed at HEAD, recorded in
    the state, or {} when none is filed there.

    A STATE WITH NO MARK DOES NOT MEAN NO REVIEW: the state file can be lost,
    or the sign-off verb run by hand, after the review filed. `file-return`
    refuses a second return at the same head, so dispatching again would pay
    for a review whose return can never be filed, while the triage read the
    first one anyway.

    THE MARK SAYS ITS FINDINGS ARE RECORDED only where the plan's review
    already holds each of them (`findings_held`): the lost state may have
    recorded them, and `finding` appends rather than deduplicates."""
    head = git_head(ctx)
    path = (os.path.join(ctx["evidence"], *_fr.phase_return_rel(
        phase["id"], head).split("/")) if head else None)
    if not path or not os.path.isfile(path):
        return {}
    _text, review, _problem = _fr.read_filed_return(path)
    mark = {"head": head}
    if findings_held(phase, (review or {}).get("findings") or []):
        mark["findings"] = True
    state["phaseReview"] = mark
    write_state(ctx, state)
    ctx["did"].append("phase review filed at %s read" % (head[:7],))
    return state["phaseReview"]


def _finding_key(finding):
    """A finding as `finding` records it, less the id the plan allocates."""
    return tuple((finding.get(field) or "").strip()
                 if isinstance(finding.get(field), str) else ""
                 for field in _phases.FINDING_FIELDS if field != "id")


def findings_held(phase, found):
    """True when the phase's recorded review already holds every finding in
    `found` - as many times as `found` lists it - so recording them again
    would double them: `finding` appends, it does not deduplicate. False for
    an empty `found`, which has nothing to mark."""
    found = [f for f in found if isinstance(f, dict)]
    if not found:
        return False
    held = [_finding_key(f) for f in (phase.get("review") or {}).get("findings")
            or [] if isinstance(f, dict)]
    for key in [_finding_key(f) for f in found]:
        if key not in held:
            return False
        held.remove(key)
    return True


def record_findings(ctx, phase, found):
    """Every finding of the phase review, recorded in ONE `finding` call; None,
    or the stop."""
    _out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "finding", phase["id"], ctx["manifest"], "--project-dir", ctx["project"],
        "--findings-file", "-"], stdin=json.dumps(found))
    return stop


def open_findings(phase):
    """The phase review's findings still open, in plan order. What open means
    is `_manifest_phases.open_findings` and nothing here restates it: a finding
    whose fix task never landed (closed --no-change, cancelled) is open to the
    verb, so it is offered for a disposition the verb will accept."""
    return [f for f in _phases.open_findings(phase) if f.get("id")]


def _clip(text, width):
    data = (text or "").encode("utf-8")
    if len(data) <= width:
        return text or ""
    return data[:max(width - 3, 0)].decode("utf-8", "ignore") + "..."


def render_triage(ctx, pending):
    """The triage decision: each open finding with its options, a fix task's
    predicted price with its basis, each reviewer answer a human settles, each
    fix task no review saw, and how to answer. Sign-off is not offered while an
    answer waits on a human."""
    found = pending.get("findings") or []
    answers = pending.get("answers") or []
    after = pending.get("fixesAfter") or []
    head = step_text("decide-triage", phase=ctx["phase"], why=pending.get("why") or "")
    lines = head[:1]
    for f in found:
        lines.append(_clip("  %s %s %s - %s [fix|leave]" % (
            f.get("id"), f.get("severity"), f.get("file"), f.get("issue")),
            TRIAGE_LINE_BYTES))
    for a in answers:
        lines.append(_clip("  %s %s - %s" % (a.get("who"), a.get("what"),
                                             a.get("note") or "no note"),
                           TRIAGE_LINE_BYTES - len(" [accept]")) + " [accept]")
    if after:
        lines.append(_clip("  %s: fix task(s) closed after the review's head %s, "
                           "their diff unreviewed [re-review|sign-off]" % (
                               ", ".join(after), pending.get("head") or "?"),
                           TRIAGE_LINE_BYTES))
    if found:
        lines.append(_clip("  a fix task: %.2f-%.2f USD-eq predicted (%s)" % (
            FIX_TASK_PREDICTED + (FIX_TASK_PRICE_BASIS,)), TRIAGE_LINE_BYTES))
        lines.append("answer: next %s --answer fix --fix <id>[,<id>]" % (
            ctx["phase"],))
    if after:
        lines.append("answer: next %s --answer re-review" % (ctx["phase"],))
    if answers:
        lines.append("answer: next %s --answer accept|decline --reason <the "
                     "human's word on each>" % (ctx["phase"],))
    else:
        lines.append("answer: next %s --answer sign-off --reason <the summary>%s" % (
            ctx["phase"], " (a finding left is kept as recorded)" if found else ""))
    return instruction("decide", lines + head[1:]
                       + ([ANSWERS_RULE] if answers else []))


def triage(ctx, state, manifest, phase):
    """The phase review, its findings and the triage: the dispatch, a decision,
    or a stop. A review filed at the marked head is dispatched afresh when a
    task added since is owed its answers - the sign-off verb would refuse a
    triage over a review that never saw it."""
    mark = state.get("phaseReview") or {}
    if not mark.get("head"):
        due, problem = review_due(ctx, manifest, phase)
        if problem:
            return _stopped(ctx, problem)
        mark = filed_at_head(ctx, state, phase) if due else {}
        if due and not mark:
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
        owed, problem = owed_tasks(ctx, phase)
        if problem:
            return _stopped(ctx, problem)
        if owed:
            state.pop("phaseReview", None)
            write_state(ctx, state)
            ctx["did"].append("phase review again: %s owed" % (", ".join(owed[:3]),))
            return dispatch_phase_review(ctx, state, phase)
    keys = ("id", "severity", "file", "issue", "fixTask")
    still = [dict((k, f.get(k)) for k in keys) for f in open_findings(phase)]
    # A settlement counts for the content it was given for: an answer settled
    # by name alone is put to the human again, so its accept records the
    # signature the sign-off verb honours.
    settled = _fr.settlement_block(state.get(_fr.SETTLED_FIELD), state_path(ctx))
    answers = [a for a in human_answers(ctx, phase)
               if (a["key"], a["sha256"]) not in settled["pairs"]]
    after = fixes_after(ctx, phase, mark["head"]) if mark.get("head") else []
    said = ("the phase review returned `%s`" % ((review or {}).get("verdict")
                                                 or "no verdict",)
            if review is not None else "no phase review is due")
    extra = {"findings": still, "answers": answers, "fixesAfter": after,
             "head": (mark.get("head") or "")[:12]}
    if ctx.get("advance") is not None:
        reason = ctx.pop("advance")
        if advance_applies(review, extra):
            ctx["did"].append("sign-off answered in advance")
            return apply_phase_answer(ctx, state, manifest, phase, dict(
                extra, decision="triage", task=None, start=None, why=said),
                ADVANCE_ANSWER, reason, ())
        ctx["did"].append(ADVANCE_NOT_APPLIED % (
            "the triage below has more than one answer",))
    return decision(ctx, state, "triage", None, "%s; %s%s" % (
        said, "%d finding(s) open" % (len(still),) if still
        else "no finding open", "; %d answer(s) for a human" % (len(answers),)
        if answers else ""), extra=extra)


def advance_applies(review, triage_fields):
    """Whether a triage holding `triage_fields` admits `sign-off` as its one
    answer, so a sign-off sent before it was printed can be applied: a filed
    review whose verdict is `clean`, no finding open, no reviewer answer
    waiting on a human, and no fix task closed after the review's head. Each
    of those is what `fix`, `accept`, `decline` or `re-review` would act on
    (`answer_refusal`, `triage_refusal`); with none of them, those four are
    refused and only `sign-off` is left."""
    return (review is not None and review.get("verdict") == "clean"
            and not triage_fields.get("findings")
            and not triage_fields.get("answers")
            and not triage_fields.get("fixesAfter"))


def advance_admissible(phase):
    """Whether a sign-off sent with no decision pending is taken as an answer in
    advance: every task of the phase is terminal and the phase is not signed
    off yet, so the next step is the triage it answers. Anywhere else no
    triage is due, and the call is refused as answering nothing."""
    return (not signed_off(phase)
            and all(t.get("status") in _mio.TERMINAL for t in _tasks(phase)))


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


def runtime_boot_root(manifest, phase):
    """`(due, root)` - whether sign-off owes a runtime boot: `meta.runtimeBoot`
    is set and a file of the phase lies under its `appRootPath` (every file,
    when it names none)."""
    boot = (manifest.get("meta") or {}).get("runtimeBoot")
    if not isinstance(boot, dict):
        return False, None
    root = str(boot.get("appRootPath") or "").strip().strip("/")
    if not root or root == ".":
        return True, "the app (no appRootPath, so every file counts)"
    files = [_posix_rel(f) for t in _tasks(phase) for f in t.get("files") or []]
    return any(f == root or f.startswith(root + "/") for f in files), root


def _posix_rel(path):
    text = str(path).replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def held_at(state, key, head):
    """The human's words a head-bound answer (`bootConfirmed`,
    `coverageAccepted`, `breachAccepted`) holds while HEAD is still the commit
    it was given at, else None. A task closed after it is a commit, so the
    boot, the gate's banners and the breach it answered were of a tree that is
    gone, and the question is asked again."""
    held = state.get(key)
    if not isinstance(held, dict) or held.get("head") != head:
        return None
    return held.get("reason")


def bind_at(state, key, reason, head):
    state[key] = {"reason": reason, "head": head}


def coverage_held(state, phase, head):
    """The human's words on a gate banner while the run they were shown is still
    the run sign-off reads, else None: the same HEAD, the same held run id, and
    the gate the phase declares now. HEAD alone is not the run - a gate
    retargeted, a declared file edited or a run recorded by hand at the same
    head is another run, whose banners nobody was asked about."""
    held = state.get("coverageAccepted")
    if not held_at(state, "coverageAccepted", head):
        return None
    run = (state.get("phaseGate") or {}).get("runId")
    if held.get("runId") != run \
            or held.get("gate") != _mio.gate_entries(phase, None)[0]:
        return None
    return held.get("reason")


def bind_coverage(state, phase, reason, head):
    """Bind a gate banner's accept to the run it was given over (`coverage_held`)."""
    state["coverageAccepted"] = {
        "reason": reason, "head": head,
        "runId": (state.get("phaseGate") or {}).get("runId"),
        "gate": _mio.gate_entries(phase, None)[0]}


def signoff_summary(state, phase, head):
    """The summary the sign-off verb records: the one the triage was answered
    with, then every answer a human gave on the way - each kept in their
    words, a `decline` included - with a head-bound answer kept only while it
    still holds at `head`, and a gate banner's accept only while it answers
    the run the verdict stands on."""
    parts = [state.get("summary") or ""]
    reasons = (state.get("answersAccepted") or {}).get("reasons") or []
    if reasons:
        parts.append("Reviewer answers accepted: %s" % ("; ".join(reasons),))
    if state.get("declined"):
        parts.append("Declined on the way: %s" % ("; ".join(state["declined"]),))
    if state.get("continued"):
        parts.append("Per-task reviewer answers continued over: %s"
                     % ("; ".join(state["continued"]),))
    if state.get("unreviewedFixes"):
        parts.append("Fix task(s) %s signed off with their diff unreviewed."
                     % (", ".join(state["unreviewedFixes"]),))
    for key, said in (("bootConfirmed", "Runtime boot: %s"),
                      ("coverageAccepted", "Gate banner accepted: %s"),
                      ("breachAccepted", "Invariant breach accepted: %s")):
        reason = (coverage_held(state, phase, head) if key == "coverageAccepted"
                  else held_at(state, key, head))
        if reason:
            parts.append(said % (reason,))
    return " ".join(p for p in parts if p)


def held_gate_binds(ctx, phase, held, head):
    """Whether the green run `held` names may be reused at `head`: recorded at
    that head, and still the run the sign-off verb would bind - the newest
    phase verdict, measured under the gate the phase declares now, over its
    declared files as they stand (`_verdict_binding.phase_binding`, the
    question the verb asks). HEAD alone is not that: a gate retargeted, a
    declared file edited or a run recorded by hand leaves HEAD where it was,
    and a reused run the verb then refuses is a sign-off that loops."""
    if not (isinstance(held, dict) and held.get("runId")
            and held.get("head") == head):
        return False
    manifest = _mio.load_manifest(ctx["manifest"])
    bound = _vb.phase_binding(
        ctx["project"], ctx["manifest"], manifest, phase,
        _vb.phase_files([phase]), "the drive measures again",
        "the phase declares no gate")
    return (bound.get("state") == "bound"
            and (bound.get("row") or {}).get("runId") == held["runId"])


def drop_held_gate(ctx, state):
    """Forget the held green run, so the next sign-off measures again: a step
    after the gate refused, and the run it was asked over is not reused."""
    if state.pop("phaseGate", None) is not None:
        write_state(ctx, state)


def green_phase_gate(ctx, state, phase, head):
    """`(banners, None)` for a green phase gate, or `(None, stop)`. A green run
    held from an earlier pass is reused, banners and all, while
    `held_gate_binds` says the verb would still bind it: the answer a human
    gave was about that run, and the verdict binds to it. Otherwise the gate
    runs again and its banners are the ones read. A run that printed no run id
    is not recorded for reuse, so the next pass measures."""
    held = state.get("phaseGate")
    if held_gate_binds(ctx, phase, held, head):
        ctx["did"].append("phase gate green (reused %s)" % (held["runId"],))
        return list(held.get("banners") or []), None
    drop_held_gate(ctx, state)
    code, out, err = phase_gate(ctx, phase)
    if code == 1:
        return None, red_gate_stop(ctx, phase, out, err)
    if code != 0:
        return None, relay_refusal(ctx, "run-test-gate.py", code, out + err)
    banners = gate_banners(out + err)
    run_id = _RUN_ID.search(out + err)
    if run_id and head:
        state["phaseGate"] = {"head": head, "runId": run_id.group(1),
                              "banners": banners}
        write_state(ctx, state)
    ctx["did"].append("phase gate green")
    return banners, None


def run_signoff(ctx, state, phase):
    """The runtime boot's answer, the phase gate, the invariants and the
    sign-off verb - None when the verdict is recorded, else the decision or the
    stop."""
    head = git_head(ctx)
    due, root = runtime_boot_root(_mio.load_manifest(ctx["manifest"]), phase)
    if due and not held_at(state, "bootConfirmed", head):
        return decision(ctx, state, "runtime-boot", None, _clip(root, 60))
    banners, stop = green_phase_gate(ctx, state, phase, head)
    if stop is not None:
        return stop
    # The decision names the banners and, once accepted, the summary keeps
    # them; the did-line stays plain, since the final print carries the landing.
    if banners and not coverage_held(state, phase, head):
        return decision(ctx, state, "gate-coverage", None, "; ".join(banners))
    if not held_at(state, "breachAccepted", head):
        code, out, err = run_verb(ctx, "verify-invariants.py", [
            ctx["manifest"], phase["id"], "--project", ctx["project"]])
        if code == 1:
            first = [ln.strip() for ln in (out + err).splitlines()
                     if ln.strip().startswith("BREACH")]
            return decision(ctx, state, "invariant-breach", None,
                            _clip(first[0] if first else "exit 1", 140))
        if code != 0:
            drop_held_gate(ctx, state)
            return relay_refusal(ctx, "verify-invariants.py", code, out + err)
        ctx["did"].append("invariants clean")
    summary = signoff_summary(state, phase, head)
    args = ["signoff", phase["id"], ctx["manifest"], "--project-dir",
            ctx["project"], "--verdict", "passed", "--summary", summary]
    # THE HUMAN'S WORDS ARE THE DISPOSITION. A `sign-off` answered over a
    # finding no fix task names is the human accepting it open, and the verb
    # refuses a sign-off that leaves one unsaid, so each is recorded with the
    # reason the answer carried.
    for finding in open_findings(phase):
        if finding.get("status") not in ("accepted-open", "carried"):
            args += ["--accept-open", "%s=%s" % (finding["id"], summary)]
    mark = state.get("phaseReview") or {}
    if mark.get("head"):
        args += ["--review-outcome", "phase review filed at head %s"
                 % (mark["head"][:12],)]
    _out, stop = _verb_or_stop(ctx, "audit-task.py", args)
    if stop is not None:
        drop_held_gate(ctx, state)
        return stop
    ctx["did"].append(SIGNED)
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
    """`(said, None)` - what the landing did, in a did-line clause - or `(None,
    stop)`. Only a merge close-phase made is said with `LANDED`."""
    if not phase.get("branch"):
        return "no branch recorded, so nothing to land", None
    if state.get("leave"):
        return _clip("left unmerged: %s" % (state["leave"],), 100), None
    args = [ctx["manifest"], phase["id"], "--project", ctx["project"]]
    if state.get("noFf"):
        args.append("--no-ff")
    code, out, err = run_verb(ctx, "close-phase.py", args)
    if code == 3:
        return None, decision(ctx, state, "not-fast-forward", None, "exit 3")
    if code != 0:
        return None, relay_refusal(ctx, "close-phase.py", code, out + err)
    if "NOT MERGED" in out:
        return "meta.merge.auto is false, so the merge is handed to a human", None
    first = (out.strip().splitlines() or [""])[0]
    if first.startswith("[close-phase] "):
        first = first[len("[close-phase] "):]
    said = "%s (%s)" % (LANDED, _clip(first, 60))
    left, failed = _STAMP_LEFT.search(out), _STAMP_FAILED.search(out)
    if left:
        said += ("; stamp left uncommitted in %s - re-run close-phase there once "
                 "it is clean" % (_clip(left.group(1), 60),))
    elif failed:
        said += "; stamp left uncommitted: %s" % (_clip(failed.group(1), 80),)
    return said, None


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
    ctx["did"].append(said)
    return finish(ctx, state, "signed off (%s)" % (
        (phase.get("review") or {}).get("status") or "passed",))


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
    name = pending["decision"]
    if answer == "fix":
        return add_fix_tasks(ctx, phase, fixes)
    if answer in ("redispatch", "re-review"):
        state.pop("phaseReview", None)
        write_state(ctx, state)
        return dispatch_phase_review(ctx, state, phase)
    if answer == "not-reachable":
        # The question stays open: the next `next` asks it again, and nothing
        # signs the phase off until a human answers booted.
        state["pending"] = pending
        write_state(ctx, state)
        return _stopped(ctx, "the runtime boot was not confirmed (%s), so the "
                        "phase is not signed off; answer booted once a human "
                        "has booted it, or decline with what failed"
                        % (_clip(reason, 120),))
    if answer == "decline":
        return decline_answer(ctx, state, phase, name, reason)
    if name == "triage" and answer == "accept":
        state[_fr.SETTLED_FIELD] = _fr.settlement_after(
            state.get(_fr.SETTLED_FIELD), pending.get("answers") or [], reason)
        write_state(ctx, state)
        ctx["did"].append("%d reviewer answer(s) accepted"
                          % (len(pending.get("answers") or []),))
        return None
    if answer == "sign-off":
        state["summary"] = reason
        state["unreviewedFixes"] = list(pending.get("fixesAfter") or [])
    elif answer == "accept" and name == "gate-coverage":
        bind_coverage(state, phase, reason, git_head(ctx))
    elif answer == "accept":
        bind_at(state, "breachAccepted", reason, git_head(ctx))
    elif answer == "booted":
        bind_at(state, "bootConfirmed", reason, git_head(ctx))
    elif answer == "no-ff":
        state["noFf"] = True
    elif answer == "leave":
        state["leave"] = reason
    write_state(ctx, state)
    return signoff_step(ctx, state, phase)


def decline_answer(ctx, state, phase, name, reason):
    """A human's no to one of sign-off's decisions: their words are kept for
    the summary, the decision is dropped, and the green gate it was asked over
    is no longer reused. The drive goes on to any task still open - the remedy
    a human added - and with none, stops naming how to add one."""
    state.setdefault("declined", []).append("%s: %s" % (name, reason))
    state.pop("phaseGate", None)
    write_state(ctx, state)
    ctx["did"].append("%s declined" % (name,))
    if any(t.get("status") not in _mio.TERMINAL for t in _tasks(phase)):
        return None
    return _stopped(ctx, "the human declined %s; their words are kept for the "
                    "summary. %s" % (name, DECLINE_REMEDY % (phase["id"],
                                                             phase["id"])))


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


# The ceiling a task records nothing usable for: the new-task template's.
# `audit-task.py`'s `_attempt_ceiling` is the rule `start` and `unblock` refuse
# by, and an entry point may not import another, so it is mirrored here; the
# `bk` cases run each printed remedy through the real verb, which is what goes
# red if the two disagree.
DEFAULT_MAX_ATTEMPTS = 3


def attempts_spent(task):
    """Whether `task` has spent the attempts it may take - the line between
    `unblock`, which refuses a task with attempts left, and `start`, which
    refuses one without."""
    ceiling = task.get("maxAttempts")
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
        ceiling = DEFAULT_MAX_ATTEMPTS
    return (_mio.recorded_attempt(task) or 0) >= ceiling


def blocked_remedy(tasks):
    """The remedy line for each blocked task among the first three of `tasks`
    (the ones a stalled print names): `unblock` with the human's words once
    its attempts are spent, else `start`. Empty when none is blocked."""
    said = [('unblock %s --reason "<their words>"' if attempts_spent(t)
             else "start %s") % (t["id"],)
            for t in tasks[:3] if t.get("status") == "blocked"]
    return [REMEDY_HEAD + "; ".join(said)] if said else []


def blocked_stop(name, tasks, **fields):
    """A blocked print's lines: its line, each blocked task's remedy, then the
    rule under it."""
    lines = step_text(name, **fields)
    return lines[:1] + blocked_remedy(tasks) + lines[1:]


def finish_task(ctx, state, task):
    """A task-scoped drive is through: give back a lock this drive took, drop the
    marks of this task, and drop the state when nothing else is in it."""
    if state.get("lock") == "taken":
        _out, stop = _verb_or_stop(ctx, "audit-lock.py", [
            "release", "phase-%s" % (ctx["phase"],), "--project", ctx["gitRoot"]])
        if stop is not None:
            return stop
        state.pop("lock", None)
        ctx["did"].append(RELEASED)
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
            return E_STOPPED, "\n".join(blocked_stop(
                "stop-blocked", [task], phase=ctx["phase"], task=task["id"],
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
    if (answer == ADVANCE_ANSWER and pending is None and not ctx.get("only")
            and not fixes and advance_admissible(phase)):
        if not (reason or "").strip():
            return E_USAGE, "%s %s: --answer %s needs --reason: it is recorded " \
                            "with the phase" % (PREFIX, ctx["phase"], answer)
        ctx["advance"] = reason
        code, said = drive_phase(ctx, state, phase)
        if ctx.pop("advance", None) is not None:
            ctx["did"].append(ADVANCE_NOT_APPLIED % ("no triage was reached",))
        return code, said
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
    return drive_phase(ctx, state, phase)


def drive_phase(ctx, state, phase):
    """The steps of the whole phase, from wherever its tasks stand: start and
    advance each in turn - or, at a width above 1, a wave of them at once -
    then sign-off once every one is terminal."""
    width, basis, problem = wave_width(ctx["config"])
    if problem:
        return _stopped(ctx, problem)
    for _ in range(4 * len(_tasks(phase)) + 4):
        manifest, phase = load_phase(ctx)
        if width > 1 or state.get("wave"):
            said = wave_step(ctx, state, manifest, phase, width, basis)
            if said is None:
                continue
            if said is not NO_WAVE:
                return _as_result(said)
        task, how = next_task(manifest, phase)
        if task is None:
            if all(t.get("status") in _mio.TERMINAL for t in _tasks(phase)):
                return _as_result(sign_off(ctx, state, manifest, phase))
            return E_OK, instruction("decide", blocked_stop(
                "decide-stalled", [t for t in _tasks(phase)
                                   if t.get("status") not in _mio.TERMINAL],
                phase=ctx["phase"], why=stalled_why(manifest, phase)))
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


def red_block(ctx, task, args, cmd, tree=None):
    """`(block, None)` - the helper's `redFirst` block for `task` - or
    `(None, stop)`. A test that passed without the fix gets no block from the
    helper, and so no filing: the work is to fix the test. `tree` is the
    task's own worktree in a wave, whose test files and HEAD the red run reads."""
    extra = []
    for flag, values in (("--case", args.case), ("--introduces", args.introduces)):
        for value in values:
            extra += [flag, value]
    if args.deps_from:
        extra += ["--deps-from", args.deps_from]
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "red", "--project", tree or ctx["gitRoot"], "--manifest", ctx["manifest"],
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


def take_stamp(ctx, task, tree=None):
    """`(line, None)` - the `audit-stamp:` line for the tree now, over the task's
    declared files - or `(None, stop)` when the take names no tree. The tree is
    the task's own worktree in a wave, else the phase tree."""
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "take", "--project", tree or ctx["gitRoot"], "--manifest", ctx["manifest"],
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
                              "Nothing filed." % (tree or ctx["gitRoot"],))
    return line, None


def submit_tree(ctx, phase, task):
    """`(tree, None)` - the worktree the driver's open wave gave `task`, or None
    when the task runs in the phase tree - or `(None, stop)` when the wave names
    a tree that is gone. Read from the driver's state, never from the agent's
    working directory: an agent's shell does not stay where it was put."""
    hc = _loader.load_hooks_config(modname="audit__config")
    state_dir = str(hc.state_dir(pathlib.Path(ctx["project"]), ctx["config"] or {}))
    path = _fr.drive_state_path(state_dir, phase["id"])
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None, None
    tree = (((state if isinstance(state, dict) else {}).get("wave") or {})
            .get("trees") or {}).get(task["id"])
    if not tree:
        return None, None
    if not os.path.isdir(tree):
        return None, _stopped(ctx, "the wave gave %s the tree %s, and it is gone. "
                              "Nothing filed." % (task["id"], tree))
    return tree, None


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
        tree, stop = submit_tree(ctx, phase, task)
        if stop is not None:
            return stop
        if cmd:
            block, stop = (red_block(ctx, task, args, cmd, tree) if tree
                           else red_block(ctx, task, args, cmd))
            if stop is not None:
                return stop
            body["redFirst"] = block
            ctx["did"].append("red-first %s" % (block.get("status"),))
        line, stop = take_stamp(ctx, task, tree) if tree else take_stamp(ctx, task)
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


def handback_lines(code):
    """The line `submit` ends on: hand back the filed line, or the refusal."""
    return step_text("handback-filed" if code == E_OK else "handback-refused")


def run_submit(args, cmd, out, stdin):
    if (args.case or args.introduces or args.deps_from) and not cmd:
        sys.stderr.write("drive-phase.py: --case, --introduces and --deps-from are "
                         "the red-first helper's, and need a test command after "
                         "`--`\n%s\n" % ("\n".join(handback_lines(E_USAGE)),))
        return E_USAGE
    try:
        manifest, ctx = project_context(args)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("drive-phase.py: %s\n%s\n" % (
            exc, "\n".join(handback_lines(E_USAGE))))
        return E_USAGE
    if stdin is None:
        stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    ctx["phase"] = args.id
    code, said = submit(ctx, manifest, args, cmd, stdin)
    out("\n".join([render(ctx, code, said)] + handback_lines(code)))
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
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to a usage error. It deliberately
        # does NOT print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("drive-phase.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_drive_phase.py - run that file instead.")
        sys.exit(0)
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line, keep_verbose=True))
