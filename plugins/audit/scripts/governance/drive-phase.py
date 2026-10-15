#!/usr/bin/env python3
"""The step driver: a phase's run, with the main loop left only the judgement.

WHY IT EXISTS. A task used to take eight or more main-loop requests, and most of
them were a script's job done by the model: run a verb, read its output, type the
next command. The main loop is the dearest place in the pipeline to spend a round
trip, because every request re-reads everything the session has said. So one
entry point now does every step that is due and needs no judgement, and prints
exactly one instruction for the model. Under `--signal` it is one line of at
most `SIGNAL_BYTES`, `audit <phase> <verb> <subject> [did] | <basis> | next:
<command>`, its verb one of `VERBS`, and `next <phase> --explain <subject>`
prints the block the line stands for: the dispatch with its brief and prompt,
a decision with its options (answered with `--answer <option>`), a stop's own
words. An agent is dispatched with `DISPATCH_PROMPT` and its id, and the
command it names, `brief --manifest <manifest> --project-dir <project> --role
<role> <id>`, prints the brief written for it from wherever the agent stands.

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
                 [--verbose] [--signal | --explain ID]
  drive-phase.py brief <id> --role executor|reviewer|phase [manifest]
                 [--project-dir DIR]
  drive-phase.py submit <taskId|phaseId> --role executor|reviewer [manifest]
                 [--head SHA] [--project-dir DIR] [--case ID ...]
                 [--introduces SYMBOL ...] [--deps-from DIR] [--verbose]
                 [-- <test command>]  < return.json

Exit codes:
  0  an instruction was printed - dispatch, decide or done; or, for `submit`,
     the return was filed; for `brief` and `--explain`, the text was printed
  1  a verb refused, or a filed return will not read: the drive stopped and the
     words that stopped it are printed; for `submit`, the return was refused and
     nothing was written
  2  usage error - no manifest, no such phase, an answer no pending decision
     offers, or an option that needs --reason given none; for `submit`, no such
     task or phase, or red-first options with no test command; for `brief`, no
     brief written for the id's current start; for `--explain`, nothing to
     explain for the id

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test_drive_phase.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

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
import _excerpt  # noqa: E402  (a failing verb's output is quoted both ends, never head-cut)
import _invariants  # noqa: E402  (is_record_path: which changed paths are records)
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
import _doctor_setup  # noqa: E402  (hooks_task_binding: whether the loaded hooks bind a task tree)
import _runner_collects  # noqa: E402  (collects: whether a runner takes a test path)
import _gate_derive  # noqa: E402  (entry_runner: which runner a gate entry invokes)
import _tree_stamp  # noqa: E402  (parse_stamp, declared_scope: the scope a filing was made under)
import _scope_companions  # noqa: E402  (derive: the runner config a widen declares)

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
        "rule": ("redo recuts its tree at the phase HEAD with the work carried "
                 "over and spends no attempt; block keeps the tree and tells "
                 "the human.",)},
    "decide-undeclared-change": {
        "line": "decide undeclared-change %(task)s: changed outside its files: "
                "%(why)s",
        "rule": ("widen declares them and re-gates; discard drops them; block "
                 "keeps the tree. Never drop one silently.",)},
    "decide-scope-gap": {
        "line": "decide scope-gap %(task)s: %(why)s",
        "rule": ("widen declares the runner config beside the task's files and "
                 "selects again; block keeps the task and tells the human.",)},
    "follow-browser": {
        "line": "follow %(task)s: run `%(recipe)s` in %(tree)s, then next %(phase)s",
        "rule": ("It needs a browser: the orchestrator runs it, never an agent.",)},
    "decide-gate-red": {
        "line": "decide gate-red %(task)s: recorded gate red (%(why)s)",
        "rule": ("rerun spends no attempt (GATE COULD NOT RUN); retry spends "
                 "one; past maxAttempts, block and tell the human.",)},
    "decide-no-executor-return": {
        "line": "decide no-executor-return %(task)s: the executor was dispatched "
                "and filed no return for this start",
        "rule": ("recommended: resume - it spends no attempt; retry spends one "
                 "and recuts work that may be finished.",)},
    "decide-scope-changed": {
        "line": "decide scope-changed %(task)s: the filing was made under a "
                "different file list: %(why)s",
        "rule": ("retry dispatches the executor again under the scope the task "
                 "holds now and spends an attempt; close goes on with --reason "
                 "recorded; block needs a reason.",)},
    "resume-executor": {
        "line": "resume the executor dispatched for %(task)s (the agent id your "
                "dispatch returned) and have it run its submit block",
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
    "dispatch-phase-review": {
        "line": "dispatch %(agent)s %(phase)s model=%(model)s brief=%(brief)s",
        "rule": (DISPATCH_RULE,)},
    "decide-triage": {
        "line": "decide triage %(phase)s: %(why)s",
        "rule": ("Fix tasks come first: their edits invalidate a gate taken "
                 "before them. Then: gate, invariants, verdict, commit, landing.",)},
    "decide-round-cap": {
        "line": "decide round-cap %(phase)s: %(why)s",
        "rule": ("Ask the human once (AskUserQuestion): carry every open finding "
                 "to a task or bug of the plan, one more review round, or sign "
                 "off accepting them open.",)},
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
    # Printed ONLY when the plan's own readiness names a phase beyond the one
    # that just finished - never a guess, and never for the phase that just
    # closed, which has nothing left ready. A phase boundary is a context
    # boundary: everything the next phase needs is on disk (manifest, journal,
    # evidence, drive state, briefs), so nothing is lost by starting it clean.
    "done-chain-next": {
        "line": "chain: clear context, then re-enter with /audit:phase %(phase)s "
                "for a fresh start",
        "rule": ()},
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
    "stop-index-lock": {
        "line": "",
        "rule": ("The plan's index lock is held by a live run: wait and run next "
                 "again; never --takeover or edit the plan by hand.",)},
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
    "no-executor-return": (("resume", "retry", "block"), ("block",)),
    "no-reviewer-return": (("redispatch", "not-asked"), ("not-asked",)),
    # A filed executor return whose stamp holds a file list other than the one
    # the task declares now: `retry` dispatches again under the new scope (an
    # attempt spent), `close` goes on with the reason recorded.
    "scope-changed": (("retry", "close", "block"), ("close", "block")),
    "high-risk": (("confirm", "block"), ("block",)),
    "no-change": (("no-change", "retry"), ("no-change",)),
    # A wave member's integration onto the phase tree: refused by name (a
    # conflict, a lockfile, a dirty phase tree), or owed a word on paths the
    # task changed and never declared.
    "integration-refused": (("redo", "block"), ("block",)),
    "undeclared-change": (("widen", "discard", "block"), ("block",)),
    # Before the start: a test the task declares and its runner will never
    # collect (`scope_gap`).
    "scope-gap": (("widen", "block"), ("block",)),
    "review-answer": (("continue",), ("continue",)),
    "stalled": ((), ()),
    # `accept` settles the reviewer answers a human decides and `decline` is
    # their no, and `re-review` dispatches the phase review again over fix
    # tasks it never saw; the triage refuses each where it has nothing to act
    # on (`answer_refusal`). Every decision a human can say no to takes
    # `decline`, which hands back to the work (`decline_answer`). `carry` hands
    # the open low findings to the task or bug `--to` names, recorded at
    # sign-off: the answer the triage recommends for a low.
    "triage": (("sign-off", "fix", "carry", "accept", "decline", "re-review"),
               ("sign-off", "accept", "decline")),
    # At `review.maxRounds` with a round still wanted: `carry` hands every open
    # finding to `--to` and signs off with `--reason` as the summary;
    # `one-more-round` raises this phase's cap by one; `sign-off` accepts the
    # open findings open, as the triage's does.
    "round-cap": (("carry", "one-more-round", "sign-off"), ("carry", "sign-off")),
    "no-phase-review-return": (("redispatch",), ()),
    "invariant-breach": (("accept", "decline"), ("accept", "decline")),
    "gate-coverage": (("accept", "decline"), ("accept", "decline")),
    "runtime-boot": (("booted", "not-reachable", "decline"),
                     ("booted", "not-reachable", "decline")),
    "not-fast-forward": (("no-ff", "leave"), ("leave",)),
}
# The decisions sign-off owns, answered by `apply_phase_answer`.
PHASE_DECISIONS = ("triage", "round-cap", "no-phase-review-return",
                   "invariant-breach", "gate-coverage", "runtime-boot",
                   "not-fast-forward")
# A decision's own answer line, printed under it: not a step, since it is never
# printed alone.
ANSWER_LINE = "answer: next %(phase)s --answer %(options)s%(reason)s"

# --- the signal: one line per step -------------------------------------------------
# `next --signal` prints each step as ONE line,
#   audit <phase> <verb> <subject> [what it did] | <basis> | next: <command or wait>
# so the main loop reads a line where it read a block, and the block is printed by
# `next <phase> --explain <subject>`. Every step maps to one verb of `VERBS`;
# `signal_verb_gaps()` names a step that maps to none, and `sn1` in
# `test_drive_phase.py` fails on it, so a step cannot ship without a signal.
# `judge` is a decision the orchestrator answers itself, `ask` one it puts to the
# human first, `review` the phase review's triage, `wait` a step something outside
# the drive must finish before the next `next`.
SIGNAL_BYTES = 200
EXPLAIN_BYTES = 2048
VERBS = ("dispatch", "wait", "ask", "judge", "review", "done", "stop")
SIGNAL_VERBS = {
    "dispatch-executor": "dispatch", "dispatch-reviewer": "dispatch",
    "dispatch-wave": "dispatch", "dispatch-phase-review": "dispatch",
    "resume-executor": "dispatch",
    "decide-integration-refused": "judge", "decide-undeclared-change": "judge",
    "decide-scope-gap": "judge", "decide-gate-red": "judge",
    "decide-no-executor-return": "judge", "decide-scope-changed": "judge",
    "decide-no-reviewer-return": "judge", "decide-no-change": "judge",
    "decide-no-phase-review-return": "judge", "decide-runtime-boot": "judge",
    "decide-high-risk": "ask", "decide-review-answer": "ask",
    "decide-stalled": "ask", "decide-round-cap": "ask",
    "decide-invariant-breach": "ask", "decide-not-fast-forward": "ask",
    "decide-gate-coverage": "ask",
    "decide-triage": "review",
    "follow-browser": "wait", "stop-index-lock": "wait",
    "done": "done", "done-chain-next": "done", "done-task": "done",
    "ado-echo": "done", "handback-filed": "done",
    "stop-blocked": "stop", "stop-lock": "stop", "stopped": "stop",
    "handback-refused": "stop",
}
SIGNAL_HEAD = "audit "
# The prompt every dispatch sends: one fixed sentence, the role and the id last,
# so two prompts differ by nothing but the id. It names the manifest absolutely
# and the project: an agent's shell may stand in a wave member's own tree, which
# holds a committed copy of the manifest and none of the briefs, with no
# CLAUDE_PROJECT_DIR to say where they are. `commands/phase.md` states it in
# these words, and `sn4` holds the two together.
DISPATCH_PROMPT = ('Follow the brief this prints: python3 "%(script)s" brief '
                   '--manifest "%(manifest)s" --project-dir "%(project)s" '
                   '--role %(role)s ')
EXPLAIN_SUFFIX = ".explain"

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
# The severity a finding is carried at by default rather than fixed, and whose
# fix closes on its own green gate with no re-review. Every other word - and a
# finding with none - owes the review a look at its fix: an unknown severity
# is not a low one.
CARRY_SEVERITY = "low"
# The driver's state: which open findings a `carry` answer handed to which task
# or bug (recorded at sign-off as `--carried`), how many phase reviews this
# phase has filed, and the cap a `one-more-round` answer raised.
CARRIED_FIELD = "carried"
ROUNDS_FIELD = "reviewRounds"
CAP_FIELD = "roundCap"
EXTRA_ROUNDS_FIELD = "extraRounds"
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


def did_bodies(text):
    """The clauses part of every did-line in a driver's printed text: after
    `[drive-phase] <phase>: ` on a plain line, and the what-it-did words of a
    signal line, between its subject and its first ` | `."""
    out = []
    for line in (text or "").splitlines():
        if line.startswith(PREFIX):
            out.append(line.partition(": ")[2])
        elif line.startswith(SIGNAL_HEAD) and " | " in line:
            words = line.split(" | ", 1)[0].split(" ", 4)
            if len(words) == 5:
                out.append(words[4])
    return out


def join_ids(ids):
    """`ids` as one comma-joined word, each after the first that shares its
    phase written from its `.` on - `P1.4,.5,.6` - which `split_ids` reads back
    whole. The signal carries every start and close it read, and an id spelled
    out in full each time is what made several of them overflow the line."""
    phase = ids[0].split(".", 1)[0] + "." if "." in ids[0] else None
    return ",".join([ids[0]] + [i[len(phase) - 1:] if phase and i.startswith(phase)
                                else i for i in ids[1:]])


def split_ids(word):
    """The ids one `join_ids` word stands for, in order; a plain id is itself."""
    parts = [p for p in word.split(",") if p]
    phase = parts[0].split(".", 1)[0] if parts and "." in parts[0] else None
    return parts[:1] + [phase + p if phase is not None and p.startswith(".") else p
                        for p in parts[1:]]


def did_tasks(text):
    """`{"started": [...], "closed": [...]}` - the tasks a driver's printed text
    says it started and closed, in order, read off its did-lines only: one id
    after the word on a plain did-line, a `join_ids` word on a signal line."""
    found = {STARTED: [], CLOSED: []}
    pattern = re.compile(r"\b(%s|%s) ([^;,\s]+(?:,[^;,\s]+)*)" % (STARTED, CLOSED))
    for body in did_bodies(text):
        for word, tasks in pattern.findall(body):
            found[word].extend(split_ids(tasks))
    return found


def _is_fix_added(words):
    """The words of a clause `did_events` reads a fix task's addition from."""
    return " ".join(words[:2]) == FIX_ADDED and words[3:5] == ["added", "for"]


def did_events(text):
    """`{"started", "closed", "added": [ids], "signedOff", "landed", "released"}`
    - what a driver's printed text says it did, read off its did-lines only,
    one `; `-separated clause at a time."""
    found = dict(did_tasks(text), added=[], signedOff=False, landed=False,
                 released=False)
    for body in did_bodies(text):
        for clause in body.split("; "):
            words = clause.split(" ")
            if _is_fix_added(words):
                found["added"].append(words[2])
            elif clause == SIGNED:
                found["signedOff"] = True
            elif words[0] == LANDED:
                found["landed"] = True
            elif clause == RELEASED:
                found["released"] = True
    return found


# --- running a verb ----------------------------------------------------------------
def run_verb(ctx, script, args, stdin=None, record=False):
    """`(code, stdout, stderr)` of one verb run as a subprocess from the project,
    logged on `ctx` for `--verbose`.

    The run is in bytes. In text mode Windows writes `input` through a text
    wrapper that turns every "\\n" into "\\r\\n", so a return filed through
    `file-return` was CRLF there and LF elsewhere - one record, two byte
    strings. `stdin` goes as its UTF-8 bytes instead.

    TWO READINGS OF WHAT COMES BACK, by what the verb prints. A MESSAGE - a
    did-line, a refusal, a `written:` path, everything the drive parses - is
    read as text mode read it (`_verb_text`), so every caller keeps the str it
    parsed before and a Windows verb's CRLF line endings never reach a regex.
    A RECORD is printed for an agent to read as it was written, and a carriage
    return its CONTENT carries is part of it: `record=True` decodes stdout and
    translates nothing (`_record_text`). `brief <id>` is the one record verb
    the drive runs; stderr is a message either way."""
    cmd = [sys.executable, _loader.script_path(script)] + list(args)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = ctx["project"]
    sent = stdin.encode("utf-8") if stdin is not None else None
    done = subprocess.run(cmd, cwd=ctx["project"], env=env, input=sent,
                          capture_output=True)
    out = (_record_text if record else _verb_text)(done.stdout)
    err = _verb_text(done.stderr)
    ctx["log"].append((script, list(args), done.returncode, out + err))
    return done.returncode, out, err


def _verb_text(raw):
    """A verb's captured bytes as the str text mode gave: UTF-8 with
    replacement, and "\\r\\n" and a lone "\\r" read as "\\n"."""
    text = _record_text(raw)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _record_text(raw):
    """A verb's captured bytes as UTF-8 with replacement, newlines untouched."""
    return (raw or b"").decode("utf-8", "replace")


def write_record(text):
    """Print `text` and a newline on stdout as their UTF-8 bytes.

    The command line's own half of a record: stdout's text layer would write
    the "\\n" of a CRLF the record carries as "\\r\\n" on Windows, so the
    bytes go to the stream's buffer. A stream with no buffer is an in-memory
    one, which translates nothing."""
    stream = sys.stdout
    raw = getattr(stream, "buffer", None)
    if raw is None:
        stream.write(text + "\n")
        return
    stream.flush()
    raw.write((text + "\n").encode("utf-8"))
    raw.flush()


def relay_refusal(ctx, script, code, text):
    """`(E_STOPPED, text)` for a verb that refused: the verb named, then its own
    words whole - the refusal and the remedy it gives - then the rule for a
    stop, which for a held lock is the lock's own."""
    head = "%s %s: stopped - %s refused (exit %d); its own words follow" % (
        PREFIX, ctx["phase"], script, code)
    if script == "audit-lock.py":
        kind = "stop-lock"
    elif script == "audit-task.py" and code == 3:
        kind = "stop-index-lock"
    else:
        kind = "stopped"
    ctx["stop"] = kind
    rule = STEPS[kind]["rule"]
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


def _spend(state, kind, task):
    """`_marked`, and the mark dropped: a mark that holds for ONE use."""
    held = _marked(state, kind, task)
    marks = state.get(kind) or {}
    marks.pop(task["id"], None)
    if not marks:
        state.pop(kind, None)
    return held


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
    """`(body, problem)` of `task`'s `role` return for its current start, read
    through the journal row that filed it: the drive closes a task on what this
    hands back, so a return edited after filing is a problem that stops it. A
    return no row names reads as it stands; the close verb is what says so."""
    try:
        rows = _journal_io.read_all(ctx["project"], ctx.get("config"))
    except Exception:                                          # noqa: BLE001
        rows = None
    _text, body, problem, _unchecked = _fr.read_filed_return_checked(
        _fr.return_path(ctx["evidence"], task, role), rows, ctx["project"])
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
def instruction(kind, lines, signal_fields=None):
    """One print: its kind, its lines, and the fields its `--signal` line is
    built from (`signal_of`)."""
    out = {"kind": kind, "lines": list(lines)}
    if signal_fields is not None:
        out["signal"] = signal_fields
    return out


def signal_of(step, subject, basis, nxt, prompts=(), subjects=()):
    """The fields of one signal line: the step (its verb is `SIGNAL_VERBS`'),
    what it is about, the basis, the one command to run next, the prompts a
    dispatch sends and every other id `--explain` answers for it."""
    return {"step": step, "subject": subject, "basis": basis, "next": nxt,
            "prompts": list(prompts), "subjects": list(subjects)}


def drive_target(ctx):
    """What `next` is driving: the one task a task-scoped drive names, else the
    phase."""
    return ctx.get("only") or ctx["phase"]


def explain_command(ctx, subject):
    return "next %s --explain %s" % (drive_target(ctx), subject)


def answer_command(ctx, options, needs):
    return "next %s --signal --answer %s%s" % (
        drive_target(ctx), "|".join(options),
        " --reason (%s)" % ("/".join(needs),) if needs else "")


def dispatch_prompt(ctx, role, node_id):
    """The prompt an agent is dispatched with: `DISPATCH_PROMPT`, then the id."""
    return DISPATCH_PROMPT % {"script": _loader.script_path("drive-phase.py"),
                              "manifest": os.path.abspath(ctx["manifest"]),
                              "project": os.path.abspath(ctx["project"]),
                              "role": role} + node_id


def dispatch_said(ctx, role, node_id, agent, model, brief):
    """The dispatch of `role` for `node_id` - a task's executor or reviewer, or
    the phase reviewer for `phase` - with the brief it was written."""
    if role == "phase":
        step = "dispatch-phase-review"
        lines = step_text(step, agent=agent, phase=node_id, model=model,
                          brief=brief)
        lines = lines[:1] + [ADVANCE_LINE % {"phase": ctx["phase"]}] + lines[1:]
        basis = ("%s model=%s; once it files: --answer sign-off --reason <the "
                 "summary>" % (agent, model))
    else:
        step = "dispatch-%s" % (role,)
        lines = step_text(step, agent=agent, task=node_id, model=model,
                          brief=brief)
        basis = "%s model=%s" % (agent, model)
    return instruction("dispatch", lines, signal_of(
        step, node_id, basis, "Agent: brief --role %s %s" % (role, node_id),
        prompts=[dispatch_prompt(ctx, role, node_id)]))


def wave_said(ctx, members):
    """One print of every member dispatch that is due, sent together."""
    ids = [m["signal"]["subject"] for m in members]
    subject = ",".join(ids)
    if len(subject.encode("utf-8")) > 60:
        subject = "%s+%d" % (ids[0], len(ids) - 1)
    basis = "wave of %d: %s" % (len(ids), "; ".join(sorted(set(
        m["signal"]["basis"] for m in members))))
    return instruction(
        "dispatch", [m["lines"][0] for m in members]
        + list(STEPS["dispatch-wave"]["rule"]),
        signal_of("dispatch-wave", subject, basis,
                  "one Agent per member, in one message: brief --role <role> <id>",
                  prompts=[p for m in members for p in m["signal"]["prompts"]],
                  subjects=ids))


def follow_said(ctx, task_id, recipes, tree):
    """The browser recipes a task's gate owes, which the orchestrator runs."""
    lines = [STEPS["follow-browser"]["line"] % {
        "task": task_id, "recipe": recipe, "tree": tree, "phase": ctx["phase"]}
        for recipe in recipes]
    nxt = ("%s in %s, then next %s --signal" % (recipes[0], tree, drive_target(ctx))
           if len(recipes) == 1 else explain_command(ctx, task_id))
    return instruction("follow", lines + list(STEPS["follow-browser"]["rule"]),
                       signal_of("follow-browser", task_id, "browser recipe owed "
                                 "in %s" % (tree,), nxt))


def resume_said(ctx, task_id):
    return instruction("resume", step_text("resume-executor", task=task_id),
                       signal_of("resume-executor", task_id, "the executor "
                                 "dispatched for it filed no return",
                                 "SendMessage to that executor: run your "
                                 "submit block"))


def done_said(ctx, why, next_phase):
    lines = step_text("done", phase=ctx["phase"], why=why)
    if next_phase:
        lines = lines + step_text("done-chain-next", phase=next_phase)
    return instruction("done", lines, signal_of(
        "done", ctx["phase"], why,
        "/clear, then /audit:phase %s" % (next_phase,) if next_phase else "wait"))


def done_task_said(ctx, task_id, why):
    return instruction("done", step_text("done-task", task=task_id, why=why),
                       signal_of("done-task", task_id, why, "wait"))


def stalled_said(ctx, tasks, why):
    """No task is ready: the open tasks' remedies, put to the human."""
    lines = blocked_stop("decide-stalled", tasks, phase=ctx["phase"], why=why)
    remedy = blocked_remedy(tasks)
    return instruction("decide", lines, signal_of(
        "decide-stalled", ctx["phase"], "stalled: %s%s" % (
            why, "; %s" % (remedy[0],) if remedy else ""),
        explain_command(ctx, ctx["phase"])))


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
    if name == "round-cap":
        return render_round_cap(ctx, pending)
    options, needs = DECISIONS[name]
    lines = step_text("decide-%s" % (name,), task=pending.get("task"),
                      phase=ctx["phase"], why=pending.get("why") or "")
    if options:
        lines.append(ANSWER_LINE % {
            "phase": ctx["phase"], "options": "|".join(options),
            "reason": (" (%s needs --reason)" % ("/".join(needs),)) if needs else ""})
    subject = pending.get("task") or ctx["phase"]
    return instruction("decide", lines, signal_of(
        "decide-%s" % (name,), subject, "%s: %s" % (name, pending.get("why") or ""),
        answer_command(ctx, options, needs) if options
        else explain_command(ctx, subject)))


def scope_gap(ctx, state, task):
    """The task-start preflight: ask the runner of the task's gate whether it
    collects each declared `tests.add` path. A definite NOT_COLLECTED is the
    `scope-gap` decision, unless the task already declares the runner config
    (a widen was answered); COULD_NOT_TELL prints one line and the start goes
    on. None, or the result to return before any start."""
    manifest, phase = load_phase(ctx)
    task = _mio.tasks_by_id(manifest).get(task["id"]) or task
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    paths = [p for p in (_phases.tests_add_path(e) for e in tests.get("add") or []
                         if isinstance(e, str)) if p and _phases.is_suite_path(p)]
    build = (manifest.get("meta") or {}).get("buildCommands")
    build = build if isinstance(build, dict) else {}
    entries, _source = _mio.gate_entries(phase, task)
    runners = []
    for entry in entries:
        runner = _gate_derive.entry_runner(build.get(entry, entry))
        if runner in _gate_derive.UNIT_RUNNERS and runner not in runners:
            runners.append(runner)
    for path in paths:
        answers = [(r, _runner_collects.collects(path, r, ctx["project"]))
                   for r in runners]
        if not answers or any(a["answer"] == _runner_collects.COLLECTED
                              for _r, a in answers):
            continue
        if any(a["answer"] == _runner_collects.COULD_NOT_TELL for _r, a in answers):
            ctx["did"].append("could not tell whether %s collects %s: %s" % (
                answers[0][0], path, _clip(answers[0][1]["basis"], 100)))
            continue
        runner, got = answers[0]
        found = _scope_companions.derive(
            {"tests": [path], "runner": runner, "files": task.get("files") or []},
            ctx["project"])["companions"]
        config = found[0]["path"] if found else None
        if config is None and any(
                f == c for f in task.get("files") or []
                for c in _scope_companions_configs(runner)):
            continue
        why = "%s does not collect %s (%s); %s" % (
            runner, path, _clip(got["basis"], 100),
            "widen adds %s" % (config,) if config
            else "no runner config file exists to widen")
        return E_OK, decision(ctx, state, "scope-gap", task, why,
                              extra={"config": config})
    return None


def _scope_companions_configs(runner):
    """The file names a runner reads its configuration from."""
    return {"vitest": _runner_collects.VITEST_CONFIGS + _runner_collects.VITE_CONFIGS,
            "jest": _runner_collects.JEST_CONFIGS,
            "pytest": _runner_collects.PYTEST_CONFIG_FILES}.get(runner, ())


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
    _mark(state, "dispatched-%s" % (role,), task,
          {"scope": brief_scope(task)} if role == "executor" else True)
    write_state(ctx, state)
    model = (task.get("model") if role == "executor"
             else (phase.get("review") or {}).get("model")) or "unset"
    agent = EXECUTOR_AGENT if role == "executor" else REVIEWER_AGENT
    return dispatch_said(ctx, role, task["id"], agent, model,
                         project_relative(ctx, found.group(1).strip()))


def brief_scope(task):
    """What an executor's brief was written over: the task's `files` and
    `tests`, in one canonical spelling. A brief printed under one scope and
    then overtaken by a widening was never the dispatch of the scope the task
    holds now."""
    return json.dumps({"files": list(task.get("files") or []),
                       "tests": task.get("tests")
                       if isinstance(task.get("tests"), dict) else {}},
                      sort_keys=True)


def stale_brief(state, task):
    """Whether `task`'s executor brief was printed under a scope the task no
    longer holds - a widening between the print and any return. A mark from
    before the scope was recorded beside it answers False: it says nothing
    about which scope it was printed under."""
    held = _marked(state, "dispatched-executor", task)
    return isinstance(held, dict) and held.get("scope") != brief_scope(task)


def scope_change(executor, task):
    """`(was, now)` when the stamp on `executor`'s filing holds a file list other
    than the one `task` declares now, else None. A filing with no readable stamp
    says nothing about the scope it was made under, so it is no change."""
    stamp, problem = _tree_stamp.parse_stamp((executor or {}).get("stamp"))
    if problem is not None:
        return None
    was = list(stamp.get("scope") or [])
    now = _tree_stamp.declared_scope(task.get("files"))
    return None if was == now else (was, now)


def scope_change_why(was, now):
    """The two lists a scope change is between, as the decision's one clause."""
    added = [f for f in now if f not in was]
    dropped = [f for f in was if f not in now]
    return _clip("filed under %d files, now %d; added [%s]; dropped [%s]" % (
        len(was), len(now), ", ".join(added), ", ".join(dropped)), 180)


def accept_scope(ctx, state, task, why):
    """Record that the scope `task` holds now is the one its filing is closed
    under, so the drive does not ask about it again within this start."""
    manifest, _phase = load_phase(ctx)
    held = _mio.tasks_by_id(manifest).get(task["id"]) or task
    _mark(state, "scopeAccepted", held, {
        "scope": _tree_stamp.declared_scope(held.get("files")), "why": why})
    write_state(ctx, state)


def project_relative(ctx, path):
    """`path` from the project root when it lies inside it, else as given. The
    agent works from the project root, and a print whose size grew with where
    the project happens to sit on disk could not keep `INSTRUCTION_BYTES`."""
    full = os.path.abspath(os.path.join(ctx["project"], path))
    rel = os.path.relpath(full, ctx["project"])
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def record_gate(ctx, phase, task, tree=None, no_reuse=False):
    """`(code, stdout, stderr)` of the task's recorded gate run - measured in
    `tree` when the task runs in a tree of its own, and recorded in the
    project's ledger either way. `no_reuse` measures even where an earlier
    verdict on the same tree could be repeated: what a `rerun` asks for."""
    return run_verb(ctx, "run-test-gate.py", [
        ctx["manifest"], phase["id"], "--task", task["id"], "--record",
        "--project-dir", ctx["project"]] + (["--tree", tree] if tree else [])
        + (["--no-reuse"] if no_reuse else []))


def task_gate(ctx, state, phase, task, tree=None):
    """The task's recorded gate run, measured afresh when a `rerun` answer
    marked this start - the mark is spent on this one run, so a later plain run
    may repeat a verdict again. A rerun the gate answered by repeating the red
    it was asked about would hand the same decision straight back."""
    kw = {}
    if tree:
        kw["tree"] = tree
    if _spend(state, "rerun", task):
        kw["no_reuse"] = True
        write_state(ctx, state)
    return record_gate(ctx, phase, task, **kw)


def owed_followers(ctx, text):
    """`(runId, records)` - the `followersOwed` of the row a gate run's output
    says it recorded; `[]` when it names no row, or the ledger cannot be read
    (the red then stands as the decision it always was)."""
    found = _RUN_ID.search(text or "")
    if not found:
        return None, []
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception:                                          # noqa: BLE001
        return found.group(1), []
    row = _evio.row_by_run(rows, found.group(1)) or {}
    return found.group(1), [f for f in row.get(_evio.FOLLOWERS_KEY) or []
                            if isinstance(f, dict) and isinstance(f.get("path"), str)]


def widen_task(ctx, state, task, paths, basis):
    """Declare `paths` beside the task's files with `basis` noted, and accept
    that scope so no scope-changed decision asks about it. None, or the stop."""
    manifest, _phase = load_phase(ctx)
    files = list((_mio.tasks_by_id(manifest).get(task["id"]) or task).get("files") or [])
    new = [p for p in dict.fromkeys(paths) if p not in files]
    if not new:
        return None
    for args in (("scope", task["id"], "--files", ",".join(files + new)),
                 ("note", task["id"], "--text", "files widened by %s: %s"
                  % (", ".join(new), basis))):
        _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(ctx, *args))
        if stop is not None:
            return stop
    accept_scope(ctx, state, task, basis)
    ctx["did"].append("%s widened by %s (%s)" % (task["id"], ", ".join(new), basis))
    return None


def follow_red_gate(ctx, state, phase, task, text, tree=None):
    """`(print, gate)` for a red gate whose row owes followers, once per start.

    Every follower path joins the task's files first, the row that owed it
    noted as the basis, so neither the task's commit nor its integration asks
    about it. A generated follower is then regenerated by its recipe in the
    task's tree and the gate measured again: `gate` is that `(code, out, err)`.
    A recipe that needs a browser is `print`, the orchestrator's instruction;
    a recipe that fails is `print`, a stop. `(None, None)` when nothing was
    owed or nothing could be regenerated - the red stands."""
    if _marked(state, "followed", task):
        return None, None
    run_id, owed = owed_followers(ctx, text)
    if not owed:
        return None, None
    _mark(state, "followed", task)
    write_state(ctx, state)
    stop = widen_task(ctx, state, task, [f["path"] for f in owed], "owed by %s on run %s"
                      % (", ".join(sorted(set(str(f.get("owner")) for f in owed))), run_id))
    if stop is not None:
        return stop, None
    where = tree or ctx["gitRoot"]
    made = [f for f in owed if f.get("recipe") and not f.get("needsBrowser")]
    for follower in made:
        code, said = _evio.run_recipe(follower["recipe"], where)
        if code != 0:
            return _stopped(ctx, "the recipe for %s %s: %s" % (
                follower["path"], "could not run" if code is None else "exited %d"
                % (code,), _excerpt.reason_of(*said) or "no output")), None
        ctx["did"].append("%s regenerated by its recipe" % (follower["path"],))
    browser = [f for f in owed if f.get("recipe") and f.get("needsBrowser")]
    if browser:
        return follow_said(ctx, task["id"], [f["recipe"] for f in browser],
                           project_relative(ctx, where)), None
    if not made:
        return None, None
    return None, task_gate(ctx, state, phase, task, tree)


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
            code, _excerpt.reason_of(err, out) or "no output")
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


# `claim_section`, `tests_add_gaps` and `floor_contradicted_clause` live in
# `_filed_returns.py`, not here - ONE HOME for logic the reviewer brief
# (`audit-lookup.py`) and this driver both need, below both in the layer
# graph. Two entry points may not runtime-load each other
# (`_deps.layer_violations()`), which is what putting the first version of
# `claim_section` here and loading it FROM `audit-lookup.py` tripped - a
# same-layer edge neither module's own layer may carry. Aliased here, not
# re-defined, so this file's own cases (`test_drive_phase.py`) and anything
# that reads `M.claim_section` off this module keep working unchanged.
claim_section = _fr.claim_section
tests_add_gaps = _fr.tests_add_gaps
floor_contradicted_clause = _fr.floor_contradicted_clause


def run_falsifier(cmd, tree, mutation):
    """Run `cmd` (a list) against a COPY of `tree` with `mutation` applied -
    `{"file": <relative path>, "find": <text>, "replace": <text>}` - and grade
    the planned test: `"survived"` when the command still exits 0 against the
    broken code (the test could not kill its own mutant), `"killed"` when the
    command fails as it should, `"could-not-run"` when the mutation's `find`
    is not in the file (so no mutant was ever applied) or the command cannot
    even be collected (a non-zero exit with no test run, read from `cmd`'s own
    output being empty is not inferred here - the caller reads the exit code
    alone, which is the bound a build-breaking patch is asked to fail under).
    Runs in a TEMPORARY COPY, never `tree` itself, so the caller's own tree is
    byte-identical before and after."""
    work = tempfile.mkdtemp(prefix="audit-falsifier-")
    try:
        copied = os.path.join(work, "tree")
        shutil.copytree(tree, copied, symlinks=True,
                        ignore=shutil.ignore_patterns(".git"))
        target = os.path.join(copied, mutation["file"])
        try:
            with open(target, "r", encoding="utf-8") as fh:
                original = fh.read()
        except OSError as exc:
            return "could-not-run", "could not read %s: %s" % (mutation["file"], exc)
        if mutation["find"] not in original:
            return "could-not-run", ("the mutation's `find` text is not in %s - "
                                     "no mutant was applied" % (mutation["file"],))
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(original.replace(mutation["find"], mutation["replace"], 1))
        try:
            # The test command's words are quoted, never parsed: a byte that is
            # not UTF-8 is replaced rather than allowed to end the run.
            done = subprocess.run(cmd, cwd=copied, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            return "could-not-run", "the command could not run: %s" % (exc,)
        if done.returncode == 0:
            return "survived", "the command still exited 0 against the mutant"
        combined = done.stdout + done.stderr
        if _BUILD_BROKEN.search(combined):
            return "could-not-run", ("the mutation broke the build rather than "
                                     "failing the test - %s"
                                     % (_excerpt_build_line(combined),))
        return "killed", "the command exited %d against the mutant" % (done.returncode,)
    finally:
        shutil.rmtree(work, ignore_errors=True)


_BUILD_BROKEN = re.compile(
    r"SyntaxError|IndentationError|ModuleNotFoundError|ImportError"
    r"|collected 0 items|no tests ran", re.IGNORECASE)


def _excerpt_build_line(text):
    for line in text.splitlines():
        if _BUILD_BROKEN.search(line):
            return line.strip()
    return "no matching line"


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
        if stale_brief(state, task):
            # The brief went out before a scope widening, so no executor holds
            # the task as it stands: it is issued again, with no decision and
            # no attempt spent, rather than graded as one that returned nothing.
            ctx["did"].append("%s's brief issued again: its scope changed after "
                              "the last one was printed" % (task["id"],))
            return dispatch(ctx, state, phase, task, "executor")
        if _marked(state, "dispatched-executor", task):
            return decision(ctx, state, "no-executor-return", task, "")
        return dispatch(ctx, state, phase, task, "executor")
    changed = scope_change(executor, task)
    if changed is not None:
        # Before the gate mark is read: a gate recorded under the old scope does
        # not make the new one decided, and the close refuses a changed list
        # three steps later with a sentence about digests.
        accepted = _marked(state, "scopeAccepted", task)
        if not (isinstance(accepted, dict) and accepted.get("scope") == changed[1]):
            return decision(ctx, state, "scope-changed", task,
                            scope_change_why(*changed),
                            extra={"was": changed[0], "now": changed[1]})
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
        if tree:
            stop = refresh_member_records(ctx, state, task, tree)
            if stop is not None:
                return stop
        code, out, err = task_gate(ctx, state, phase, task, tree)
        if code == 1:
            followed, again = follow_red_gate(ctx, state, phase, task, out + err, tree)
            if followed is not None:
                return followed
            if again is not None:
                code, out, err = again
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
        if task["id"] in confirmed_in_advance(ctx, phase["id"]):
            said = "high-risk %s confirmed in advance" % (task["id"],)
        else:
            said = standing_use(ctx, phase, task, tree)
            if said is None:
                return decision(ctx, state, "high-risk", task, "")
        _mark(state, "confirmed", task)
        write_state(ctx, state)
        ctx["did"].append(said)
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
        # its diff is the triage's to put to a re-review (`fixes_after`) where
        # it owes one, and a fixed low whose gate never went red owes none.
        named = ", ".join(str(f) for f in task.get("fixes") or [])
        owes = owes_rereview(phase, task, gate_went_red(ctx)
                             if fixes_only_lows(phase, task) else set())
        return close_task(ctx, state, phase, task, intent_basis=(
            "a fix task for %s: the phase review raised the finding; the fix's "
            "own diff is unreviewed unless sign-off re-reviews it" % (named,)
            if owes else
            "a fix task for %s, every finding it fixes raised low and its gate "
            "never red: it closes on its own green gate, and no re-review is "
            "owed" % (named,)))
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


def standing_use(ctx, phase, task, tree=None):
    """The did-line for a high-risk commit the owner's standing approval lets
    through, once its journal row is written; None when no approval is armed,
    or when the row could not be written - the decision is then asked, as it
    is with none armed, because an unrecorded use is the gate skipped rather
    than answered. The row names the task, the digest of its declared files
    as they stand before the commit, and the arming row it used; a digest
    that cannot be taken is the same refusal, said on the did-line.

    The reading of the trail is the hooks' own (`_config.standing_approval`),
    the module whose prompt hook writes the arming rows."""
    try:
        rows = _journal_io.read_all(ctx["project"])
        cfg_mod = _loader.load_hooks_config(modname="audit__config")
        approval = cfg_mod.standing_approval(rows)
    except Exception as exc:                                   # noqa: BLE001
        ctx["did"].append("standing approval not read for %s (%s: %s)"
                          % (task["id"], type(exc).__name__, exc))
        return None
    if not approval["armed"]:
        return None
    excluded, _dropped = _evio.recorded_paths(ctx["project"], ctx["manifest"],
                                              ctx["config"])
    digest, basis = _tree_stamp.scope_digest(tree or ctx["project"],
                                             task.get("files"), excluded=excluded)
    if digest is None:
        ctx["did"].append("standing approval not used for %s: its scope digest "
                          "could not be taken (%s)" % (task["id"], basis))
        return None
    entry = cfg_mod.standing_use_entry(task["id"], phase["id"], digest, approval)
    entry["target"] = _output.posix_rel(ctx["manifest"], ctx["project"])
    written, why = _journal_io.append_from_cli_why(ctx["project"], entry)
    if not written:
        ctx["did"].append("standing approval not used for %s: its journal row "
                          "was not written (%s)" % (task["id"], why))
        return None
    return ("high-risk %s commits under the standing approval armed %s"
            % (task["id"], approval["since"]))


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


def hooks_width(ctx, width, basis):
    """`(width, basis)` for opening a wave: the asked width where the hooks
    Claude Code loads carry the task-tree binding (or no record says which
    copy that is, which the print says), and 1 - with the copy and the file
    that lack it - where a record names a copy whose hooks do not. A wave's
    trees are judged by that binding, so a copy without it would hold an
    executor to a tree it cannot tell from the project's."""
    seen = _doctor_setup.hooks_task_binding(
        ctx["project"], ctx["config"], _loader.load_hooks_config(
            modname="audit__config"))
    if seen["verdict"] == "lacks":
        ctx["did"].append("the hooks Claude Code loads lack the task-tree binding, "
                          "so this phase runs at width 1: %s" % (seen["why"],))
        return 1, "width 1: the loaded hooks lack the task-tree binding"
    if seen["verdict"] == "unestablished":
        ctx["did"].append("task-tree binding not established for the loaded "
                          "hooks: %s" % (_clip(seen["why"], 300),))
    return width, basis


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
    """`(path, None)` - the task's tree, made detached at the wave's base, or
    the one already marked for it adopted at the base it was cut from, and
    recorded with that base - or `(None, stop)`. A tree whose setup did not
    complete is not recorded: the next step asks `task-add` again, which finds
    it by its marker and runs the setup again before anything is dispatched."""
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
        return None, _stopped(ctx, "the tree of %s is made, and its setup did "
                              "not complete - could not run, not red, and no "
                              "attempt is spent; the next run sets it up again: "
                              "%s" % (task["id"], _clip(made.get("error") or "", 200)))
    if code != 0 or not path:
        return None, relay_refusal(ctx, "manage-worktrees.py", code, out + err)
    base = made.get("base") or wave["base"]
    wave["trees"][task["id"]] = path
    wave.setdefault("bases", {})[task["id"]] = base
    (state.get("keptTrees") or {}).pop(task["id"], None)
    if not state.get("keptTrees"):
        state.pop("keptTrees", None)
    write_state(ctx, state)
    setup = (made.get("setup") or {}).get("status") or "none"
    adopted = "adopted, " if made.get("adopted") else ""
    wave_row(ctx, TASK_WORKTREE, "%s: a worktree of its own at %s (%ssetup %s)" % (
        task["id"], base[:12], adopted, setup), {
            "taskId": task["id"], "phaseId": ctx["phase"], "commit": base,
            "mode": "%ssetup %s" % (adopted, setup)})
    ctx["did"].append("tree for %s%s" % (task["id"], " adopted at %s" % (path,)
                                         if adopted else ""))
    return path, None


def reopen_integration(ctx, task_id):
    """Let `integrate-task.py` carry a task's tree again after a new start: its
    state calls (task, base) done once, so the entry is marked reopened. The
    paths stay, so the bytes the last integration placed are still read as
    this task's, not as a stray change in the phase tree."""
    try:
        # A path, so a byte that is not UTF-8 is kept as the same byte
        # (surrogateescape) rather than replaced by one that names another file.
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "rev-parse",
                               "--git-path", INTEGRATION_STATE],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="surrogateescape", timeout=60)
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


def refresh_member_records(ctx, state, task, tree):
    """Bring a member tree's record paths to the phase tree's committed records
    before anything reads them there. None, or the stop.

    The tree was cut at the wave's base, and the phase tree goes on committing
    records after that, so a check the member's gate runs over the plan, the
    journal or the evidence would read a plan the phase tree no longer holds -
    red for nothing the member did. `integrate-task.py --refresh-records` does
    it over `record_paths`, the one set the integration already treats as
    record, so a refreshed record is never carried back as the member's work.
    The set it names is kept on the wave: retiring a tree reads it too."""
    code, out, err = run_verb(ctx, "integrate-task.py", [
        ctx["manifest"], task["id"], "--project", ctx["project"],
        "--refresh-records", "--json"])
    try:
        answer = json.loads(out)
    except ValueError:
        answer = None
    if code != 0 or not isinstance(answer, dict):
        return relay_refusal(ctx, "integrate-task.py", code, out + err)
    records = [p for p in answer.get("records") or [] if isinstance(p, str)]
    wave = state.get("wave")
    if isinstance(wave, dict) and wave.get("records") != records:
        wave["records"] = records
        write_state(ctx, state)
    ctx["did"].append("records of %s at %s" % (
        task["id"], (answer.get("head") or "?")[:7]))
    return None


def _path_digest(tree, rel):
    """`_journal_io.file_hash` of `rel` in `tree`: None when there is no such
    file. The driver opens no file to hash it itself - `_filed_returns`'
    `file_digest_sites` reads this module for such a site and a case fails on
    one."""
    return _journal_io.file_hash(os.path.join(tree, *rel.split("/")))


def _shot_follow(tree, paths, recipes):
    """The mark a browser follow leaves: the tree, and each path's bytes as the
    follow found them, so the next drive can tell whether the recipe ran."""
    return {"tree": tree, "paths": list(paths), "recipes": list(recipes),
            "before": dict((p, _path_digest(tree, p)) for p in paths)}


def _after_shot_follow(ctx, state, task, followed):
    """`(word, stop)` on the drive after a browser follow. Every path whose
    bytes moved since the follow is the recipe's work and is widened on that
    basis; a path whose bytes did not move was not vouched for by anything, so
    the whole set is the undeclared-change decision, as it would be with no
    owner at all."""
    tree, paths = followed.get("tree") or ctx["gitRoot"], followed.get("paths") or []
    before = followed.get("before") or {}
    still = [p for p in paths if _path_digest(tree, p) == before.get(p)]
    if still:
        return None, decision(ctx, state, "undeclared-change", task, _clip(
            "%s (bytes unchanged since the follow asked for `%s`)" % (
                ", ".join(still), "`, `".join(followed.get("recipes") or [])), 120),
            extra={"paths": paths})
    word = {"answer": "widen", "paths": paths,
            "basis": "written by `%s` on the drive's follow" % (
                "`, `".join(followed.get("recipes") or []),)}
    _mark(state, "undeclared", task, word)
    write_state(ctx, state)
    return word, None


def integrate_member(ctx, state, phase, task):
    """Carry a wave member's tree into the phase tree once per start, and
    re-gate on the phase tree where the integration overlapped a sibling, cannot
    say whether it did, or widened the scope. A follower the integration
    reproduced is widened on its owner's basis; undeclared paths only a browser
    recipe writes are the orchestrator's follow, and on the next drive the paths
    whose bytes that run moved are widened - one it left unmoved makes the set
    the undeclared-change decision. None when the close may run, else the
    decision or the stop."""
    held = _marked(state, "integrated", task)
    if held is None:
        prior = (state.get("integrated") or {}).get(task["id"])
        if prior:
            reopen_integration(ctx, task["id"])
        word = _marked(state, "undeclared", task) or {}
        followed = None if word else _spend(state, "shotFollow", task)
        if followed:
            write_state(ctx, state)
            word, stop = _after_shot_follow(ctx, state, task, followed)
            if stop is not None:
                return stop
        if word.get("answer") == "widen":
            stop = widen_task(ctx, state, task, word.get("paths") or [],
                              word.get("basis") or "widened by the integration answer")
            if stop is not None:
                return stop
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
            asked = answer.get("decision") or {}
            paths = asked.get("paths") or []
            shots = [r for r in asked.get("browser") or [] if r.get("path") in paths]
            if shots and len(shots) == len(paths) and not word:
                # Bytes a browser wrote cannot be reproduced here: the recipe is
                # the orchestrator's to run in the member's tree. Nothing is
                # widened yet - the next drive reads which bytes that run moved.
                recipes = sorted(set(r["recipe"] for r in shots))
                _mark(state, "shotFollow", task, _shot_follow(os.path.join(
                    ctx["gitRoot"], answer.get("tree") or ctx["gitRoot"]), paths, recipes))
                write_state(ctx, state)
                return follow_said(ctx, task["id"], recipes, project_relative(
                    ctx, answer.get("tree") or ctx["gitRoot"]))
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
        followers = [f for f in answer.get("followers") or [] if isinstance(f, dict)]
        stop = widen_task(ctx, state, task, [f["path"] for f in followers],
                          "written byte for byte at integration by %s" % ("; ".join(
                              "`%s` (%s)" % (f["recipe"], f["owner"]) for f in followers),))
        if stop is not None:
            return stop
        # A widened scope is a change to what the gate covered, so it re-gates.
        regate = True if word.get("answer") == "widen" or followers \
            else answer.get("regate")
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
        code, out, err = task_gate(ctx, state, phase, task)
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


def tree_holds_only_integrated(ctx, tree, records=()):
    """True when every path the tree changed holds the bytes the phase tree
    holds - nothing in it would be lost with it; False when one differs; None
    when git could not say. A path under `records` is left out: those bytes
    are the phase tree's own committed records, put there by the refresh, and
    the phase tree's working copy of them moves on with every row it writes."""
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
        if not rel or _invariants.is_record_path(rel, records):
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
    clean = tree_holds_only_integrated(ctx, tree, wave.get("records")) \
        if os.path.isdir(tree) else True
    if clean is not True:
        write_state(ctx, state)
        ctx["did"].append("tree of %s kept at %s (%s)" % (
            task["id"], tree, "it holds bytes the phase tree lacks" if clean is False
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
    """Take a member's tree down whatever it holds - a `redo` the human chose
    recuts it at the phase HEAD - so a fresh one is made. None, or the stop."""
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
    (wave.get("bases") or {}).pop(task_id, None)
    wave["base"] = git_head(ctx) or wave.get("base")
    write_state(ctx, state)
    return None


def tree_work(tree):
    """`(patch, why)` - everything the tree changed against its base, untracked
    files included, as one binary patch; `patch` is None beside the reason git
    could not say. Staging in the tree is harmless: it is about to be taken
    down."""
    for argv in (["add", "-A"], ["diff", "--cached", "--binary", "HEAD"]):
        try:
            done = subprocess.run(["git", "-C", tree] + argv, capture_output=True,
                                  timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, exc.__class__.__name__
        if done.returncode != 0:
            return None, _clip(done.stderr.decode("utf-8", "replace").strip(), 120)
    return done.stdout, ""


def recut_tree(ctx, state, task):
    """Recut a member's tree at the phase HEAD with its work in it, and measure
    its gate again over the new tree. None, or the stop. The work is read before
    the tree is taken down and kept in a file of the state directory until it
    has applied, so a patch the new base refuses is never the only copy lost."""
    tree = ((state.get("wave") or {}).get("trees") or {}).get(task["id"])
    patch, why = (tree_work(tree) if tree and os.path.isdir(tree) else (b"", ""))
    if patch is None:
        return _stopped(ctx, "the work in the tree of %s could not be read (%s), "
                        "so nothing was recut and no attempt is spent"
                        % (task["id"], why))
    kept = os.path.join(os.path.dirname(state_path(ctx)),
                        "redo-%s.patch" % (task["id"],))
    if patch:
        with open(kept, "wb") as fh:
            fh.write(patch)
    stop = drop_tree(ctx, state, task["id"])
    if stop is not None:
        return stop
    _new, stop = add_tree(ctx, state, task)
    if stop is not None:
        return stop
    if patch:
        done = subprocess.run(["git", "-C", state["wave"]["trees"][task["id"]],
                               "apply", "--binary", "--whitespace=nowarn", kept],
                              capture_output=True, timeout=120)
        if done.returncode != 0:
            return _stopped(ctx, "the tree of %s is recut at %s and its work does "
                            "not apply there (%s); the work is kept as %s and no "
                            "attempt is spent"
                            % (task["id"], state["wave"]["base"][:12],
                               _clip(done.stderr.decode("utf-8", "replace").strip(),
                                     120), kept))
        os.remove(kept)
    (state.get("gated") or {}).pop(task["id"], None)
    if not state.get("gated"):
        state.pop("gated", None)
    write_state(ctx, state)
    ctx["did"].append("tree of %s recut at %s, its work carried over" % (
        task["id"], state["wave"]["base"][:12]))
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
    dropped so the next one is selected. A tree still standing - a blocked
    member's, or one holding bytes the phase tree lacks - is carried into
    `keptTrees` and named, never dropped with the wave: `task-add` adopts a
    blocked member's tree by its marker when a later wave runs the task."""
    wave = state.pop("wave")
    by_id = _mio.tasks_by_id(manifest)
    ended = [(t, (by_id.get(t) or {}).get("status")) for t in wave["tasks"]]
    kept = dict(wave.get("trees") or {})
    if kept:
        state.setdefault("keptTrees", {}).update(kept)
    write_state(ctx, state)
    for task_id in sorted(kept, key=_id_key):
        if task_id not in (wave.get("retired") or []):
            ctx["did"].append("tree of %s kept for a later wave at %s" % (
                task_id, kept[task_id]))
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
            sent.append(said)
    if sent:
        return wave_said(ctx, sent)
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
        by_id = _mio.tasks_by_id(manifest)
        for task_id in picked:
            stop = scope_gap(ctx, state, by_id[task_id])
            if stop is not None:
                return stop
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
    if pending["decision"] == "scope-gap" and answer == "widen" \
            and not pending.get("config"):
        return ("no runner config file exists to widen, so --answer widen has "
                "nothing to declare; answer block")
    if answer == "fix":
        return fix_refusal(pending, fixes)
    elif fixes:
        return "--fix belongs to --answer fix"
    if answer == "carry" and not (ctx.get("carryTo") or "").strip():
        return ("--answer carry needs --to <task or bug id>: the carried "
                "finding is recorded as now held there")
    if answer != "carry" and ctx.get("carryTo"):
        return "--to belongs to --answer carry"
    if pending["decision"] == "triage":
        return triage_refusal(pending, answer)
    return None


def carry_target_refusal(ctx, manifest, phase, answer):
    """`--answer carry --to <id>` refused for a target the sign-off verb would
    refuse, or a task of the phase being signed off - which would run before
    the sign-off rather than carry anything past it. None when it may carry."""
    if answer != "carry":
        return None
    target = ctx["carryTo"].strip()
    mine = set(t.get("id") for t in _tasks(phase))
    bugs = set(str(b.get("id")) for b in manifest.get("bugs") or []
               if isinstance(b, dict))
    if target in mine:
        return ("--to %s is a task of %s itself, which runs before this sign-off "
                "rather than carrying the finding past it: name a task of a "
                "later phase, or a bug" % (target, phase["id"]))
    if target not in _mio.tasks_by_id(manifest) and target not in bugs:
        return ("--to %s names no task or bug of this plan: add the task that "
                "will hold the carried finding first (/audit:task add --phase "
                "<a later phase>), then carry to its id" % (target,))
    return None


def carry_ids(pending):
    """The findings a `carry` answer hands on: the open lows at a triage - the
    answer it recommends for them - and every open finding at the round cap."""
    found = pending.get("findings") or []
    if pending.get("decision") == "round-cap":
        return [f.get("id") for f in found]
    return [f.get("id") for f in found if f.get("severity") == CARRY_SEVERITY]


def fix_refusal(pending, fixes):
    """`--answer fix` refused for the findings it names, or None. A finding
    that already names a fix task - landed never, or still to run - is open,
    but the verb refuses it a second task: it is said to name one, and to be
    dispositioned at sign-off, never to be "not open" when it is."""
    found = list(pending.get("findings") or []) + list(pending.get("handed") or [])
    named = dict((f.get("id"), f.get("fixTask")) for f in found if f.get("fixTask"))
    open_ids = [f.get("id") for f in pending.get("findings") or []
                if not f.get("fixTask")]
    taken = [f for f in fixes if f in named]
    unknown = [f for f in fixes if f not in open_ids and f not in named]
    if fixes and not taken and not unknown:
        return None
    said = ["--answer fix names the findings to fix with --fix, from the open "
            "ones no fix task names: %s" % (", ".join(open_ids) or "none",)]
    said += ["%s already names a fix task (%s), so it is dispositioned at "
             "sign-off rather than given a second" % (f, named[f]) for f in taken]
    if unknown:
        said.append("not open: %s" % (", ".join(unknown),))
    return "; ".join(said)


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
    if answer == "carry" and not carry_ids(pending):
        return "no open low finding is offered here, so carry hands on nothing"
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
    if answer == "close":
        accept_scope(ctx, state, task, reason)
        ctx["did"].append("%s: scope change accepted (%s)" % (
            task["id"], _clip(reason, 80)))
        return None
    if answer == "resume":
        # The dispatch mark stays, so a return still unfiled is asked about
        # again on the next `next`; no attempt is spent.
        return resume_said(ctx, task["id"])
    if answer == "rerun":
        # The gate is not marked as run for this start, so the drive measures
        # again - with `--no-reuse`, through the mark `task_gate` spends - and
        # the task is not re-started, so no attempt is spent.
        _mark(state, "rerun", task)
        write_state(ctx, state)
        return None
    if answer == "redo":
        # The work was fine and the phase tree refused it, so no attempt is
        # spent: the tree is recut at the phase HEAD with the work in it, and
        # the gate is measured again over the new tree.
        return recut_tree(ctx, state, task)
    if answer == "retry":
        stop = start_task(ctx, task)
        # The human's own words beside `--answer retry` are what the NEXT
        # attempt's brief quotes - `_mark` keys them to the start that is
        # ABOUT TO BEGIN (read after `start_task` re-stamps it), never to the
        # one that just ended, so the brief for the new attempt finds them
        # and an unrelated later retry cannot be read as belonging to this one.
        if stop is None and (reason or "").strip():
            manifest2, _phase2 = load_phase(ctx)
            task2 = _mio.tasks_by_id(manifest2).get(task["id"])
            if task2 is not None:
                _mark(state, "retryReason", task2, reason)
                write_state(ctx, state)
        return stop
    if pending["decision"] == "scope-gap":
        # Declared before the start: the selection runs again, because the
        # config may belong to a sibling's files, and the preflight now sees
        # the config declared.
        files = list(task.get("files") or [])
        if pending["config"] not in files:
            files.append(pending["config"])
        _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
            ctx, "scope", task["id"], "--files", ",".join(files)))
        if stop is None:
            ctx["did"].append("%s widened by %s" % (task["id"], pending["config"]))
        return stop
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
    if pending["decision"] == "scope-gap":
        return task.get("status") == "pending"
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


def release_lock(ctx, state):
    """Give back the phase lock when this drive holds it; None, or the stop. The
    one release every way out of a drive goes through."""
    if state.get("lock") != "taken":
        return None
    _out, stop = _verb_or_stop(ctx, "audit-lock.py", [
        "release", "phase-%s" % (ctx["phase"],), "--project", ctx["gitRoot"]])
    if stop is not None:
        return stop
    state.pop("lock", None)
    ctx["did"].append(RELEASED)
    return None


def drop_state(ctx):
    try:
        os.remove(state_path(ctx))
        os.rmdir(os.path.dirname(state_path(ctx)))
    except OSError:
        pass


def _next_chain_phase(ctx):
    """The phase id the plan's own readiness names next, once this phase's
    `done` is on disk - `None` when nothing is ready, read as "no chain to
    continue" rather than as a phase named `none`.

    Reads the manifest FRESH, after sign-off's own write, through the same
    `ready_by_phase` every other surface derives its ready list from - never
    a second readiness rule kept only for this message. The phase that just
    finished holds no ready task of its own any more (it is done), so the
    first key is always a DIFFERENT phase; nothing here excludes `ctx["phase"]`
    by name, because the set it reads already cannot contain it."""
    try:
        manifest = _mio.load_manifest(ctx["manifest"])
    except Exception:
        return None
    for phase_id in _status_facts.ready_by_phase(manifest):
        if phase_id:
            return phase_id
    return None


def finish(ctx, state, why):
    """The phase is through: give back a lock this drive took, drop the state."""
    stop = release_lock(ctx, state)
    if stop is not None:
        return stop
    drop_state(ctx)
    return done_said(ctx, why, _next_chain_phase(ctx))


# --- sign-off --------------------------------------------------------------------
def signed_off(phase):
    return (phase.get("review") or {}).get("status") in SIGNED_OFF


def git_head(ctx):
    """The commit HEAD names in the project's repository, or None."""
    try:
        done = subprocess.run(["git", "-C", ctx["gitRoot"], "rev-parse", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
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
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(done.returncode)


def fixes_after(ctx, phase, head):
    """The recorded fix tasks closed `not-asked` under the phase key at a
    commit the phase review's `head` does not hold - diffs no review saw - that
    owe a re-review (`owes_rereview`). A fix task its own per-task reviewer
    answered was reviewed, so it is not listed. One git could not place is
    listed: an unknown is not a reviewed diff."""
    unseen = [t for t in _tasks(phase)
              if t.get("commit") and _fr.is_fix_task(t, phase)
              and (t.get("intentCheck") or {}).get("answer") == "not-asked"
              and review_key(ctx, phase, t)[0] == _fr.KEY_PHASE
              and is_ancestor(ctx, t["commit"], head) is not True]
    red = gate_went_red(ctx) if any(fixes_only_lows(phase, t)
                                    for t in unseen) else set()
    return [t["id"] for t in unseen if owes_rereview(phase, t, red)]


def fixes_only_lows(phase, task):
    """Whether every finding fix task `task` names was raised `low`. A finding
    the review does not hold, or one with no severity, is not a low one."""
    severity = dict((str(f.get("id")), f.get("severity"))
                    for f in (phase.get("review") or {}).get("findings") or []
                    if isinstance(f, dict))
    fixes = task.get("fixes") or []
    return bool(fixes) and all(severity.get(str(fid)) == CARRY_SEVERITY
                               for fid in fixes)


def owes_rereview(phase, task, red):
    """Whether fix task `task`'s diff owes the phase review another look: one
    of its findings was med or high, or its own gate went red on the way -
    `red` is `gate_went_red`'s set, None where the ledger could not be read,
    which owes one: an unread ledger is not a green one. A fixed low whose gate
    was only ever green closes on that gate."""
    if not fixes_only_lows(phase, task):
        return True
    return red is None or task.get("id") in red


def gate_went_red(ctx):
    """The ids of the tasks whose recorded gate ever came back `failed` in
    the project's evidence ledger, or None when the ledger cannot be read."""
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception:                                          # noqa: BLE001
        return None
    return set(r.get("taskId") for r in rows if isinstance(r, dict)
               and r.get("taskId") and r.get("status") == "failed")


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
    return dispatch_said(ctx, "phase", phase["id"], REVIEWER_AGENT,
                         (phase.get("review") or {}).get("model") or "unset",
                         project_relative(ctx, brief))


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


# The fields of an open finding the triage carries in its pending decision.
TRIAGE_FINDING_KEYS = ("id", "severity", "file", "issue", "fixTask")


def live_fix_task(phase, finding):
    """The task the finding's `fixTask` names while it is still to run -
    pending or in progress - else None. A fix task that never landed (closed
    --no-change, cancelled) leaves the finding open for a disposition; a live
    one is the finding's answer, still being carried out."""
    tid = finding.get("fixTask")
    if not tid:
        return None
    return next((t for t in _tasks(phase) if t.get("id") == tid
                 and t.get("status") in ("pending", "in_progress")), None)


def triage_findings(phase):
    """`(offered, handed)` - the open findings the triage offers a word on,
    and those already handed to a live fix task, which it offers neither `fix`
    nor a sign-off disposition: their answer is the task, and the drive runs
    it before the triage comes back."""
    offered, handed = [], []
    for finding in open_findings(phase):
        entry = dict((k, finding.get(k)) for k in TRIAGE_FINDING_KEYS)
        (handed if live_fix_task(phase, finding) else offered).append(entry)
    return offered, handed


def triage_handed_off(phase):
    """Whether a pending triage is satisfied without an answer: some open
    finding names a live fix task - added by hand with `add --fixes` - and no
    med-or-worse finding is left unhanded. The drive then runs those tasks,
    and the review and the triage come after them."""
    offered, handed = triage_findings(phase)
    return bool(handed) and all(f.get("severity") == "low" for f in offered)


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
    lines = head[:1] + finding_lines(found, pending)
    lows = carry_ids(pending)
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
    if lows:
        lines.append(_clip("answer: next %s --answer carry --to <task or bug id> "
                           "(recommended for the low finding(s): %s)" % (
                               ctx["phase"], ", ".join(lows)), TRIAGE_LINE_BYTES))
    if found:
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
    parts = (["%d finding(s) open" % (len(found),)] if found else ["no finding open"])
    if answers:
        parts.append("%d answer(s) a human settles" % (len(answers),))
    if after:
        parts.append("%s closed after the review's head" % (", ".join(after),))
    clean = not (found or answers or after)
    return instruction("decide", lines + head[1:]
                       + ([ANSWERS_RULE] if answers else []), signal_of(
        "decide-triage", ctx["phase"], "triage: %s" % ("; ".join(parts),),
        "next %s --signal --answer sign-off --reason <the summary>"
        % (ctx["phase"],) if clean else explain_command(ctx, ctx["phase"])))


def finding_lines(found, pending, offer=True):
    """One line per open finding with the answers it takes - a low offers
    `carry` first, the answer the triage recommends for it; none with `offer`
    False, where the decision's own answer line is the only one - then one per
    finding handed to a fix task still to run and one per finding a `carry`
    answer already handed on. The options are appended after the bound, so a
    long issue is cut and its options never are."""
    lines = []
    for f in found:
        options = ("" if not offer else " [carry|fix|leave]"
                   if f.get("severity") == CARRY_SEVERITY else " [fix|leave]")
        lines.append(_clip("  %s %s %s - %s" % (
            f.get("id"), f.get("severity"), f.get("file"), f.get("issue")),
            TRIAGE_LINE_BYTES - len(options)) + options)
    for f in pending.get("handed") or []:
        lines.append(_clip("  %s %s - handed to %s, which runs before sign-off"
                           % (f.get("id"), f.get("severity"), f.get("fixTask")),
                           TRIAGE_LINE_BYTES))
    for f in pending.get("carried") or []:
        lines.append(_clip("  %s - carried to %s, recorded so at sign-off"
                           % (f.get("id"), f.get("to")), TRIAGE_LINE_BYTES))
    return lines


def render_round_cap(ctx, pending):
    """The round cap's one question: the findings still open, each fix no
    review saw, what the rounds cost and on what basis, and the three answers
    on one line."""
    head = step_text("decide-round-cap", phase=ctx["phase"],
                     why=pending.get("why") or "")
    lines = head[:1] + finding_lines(pending.get("findings") or [], pending,
                                     offer=False)
    after = pending.get("fixesAfter") or []
    if after:
        lines.append(_clip("  %s: fix task(s) closed after the review's head %s, "
                           "their diff unreviewed" % (
                               ", ".join(after), pending.get("head") or "?"),
                           TRIAGE_LINE_BYTES))
    lines += list(pending.get("cost") or [])
    lines.append("answer: next %s --answer carry --to <task or bug id> --reason "
                 "<the summary> | one-more-round | sign-off --reason <the "
                 "summary>" % (ctx["phase"],))
    return instruction("decide", lines + head[1:], signal_of(
        "decide-round-cap", ctx["phase"], "round-cap: %s" % (pending.get("why") or "",),
        explain_command(ctx, ctx["phase"])))


def filed_review_rounds(ctx, phase):
    """How many phase reviews `phase` has filed: one return per round, keyed on
    the head its brief named, so the count survives the driver's state."""
    return len(_fr.phase_returns(ctx["evidence"], phase["id"]))


def review_rounds(ctx, state, phase):
    """`(rounds, cap, problem)` - the phase reviews filed so far and the cap
    sign-off stops at: `review.maxRounds`, raised by each `one-more-round`.
    Both are kept in the driver's state, and the count is re-derived from the
    filed returns on every read, so a lost state file never resets it to zero."""
    base, problem = _config_rules.review_max_rounds(ctx["config"])
    if problem:
        return None, None, problem
    held = state.get(ROUNDS_FIELD)
    held = held if isinstance(held, int) and not isinstance(held, bool) else 0
    rounds = max(filed_review_rounds(ctx, phase), held)
    extra = state.get(EXTRA_ROUNDS_FIELD)
    extra = extra if isinstance(extra, int) and not isinstance(extra, bool) \
        and extra > 0 else 0
    cap = base + extra
    if state.get(ROUNDS_FIELD) != rounds or state.get(CAP_FIELD) != cap:
        state[ROUNDS_FIELD], state[CAP_FIELD] = rounds, cap
        write_state(ctx, state)
    return rounds, cap, None


# The `--by task` key `audit-usage.py` files a row under when it names no task:
# the phase's own turns - its reviews and the main loop's - rather than a task's.
NO_TASK_KEY = "--"


def rounds_cost_lines(ctx, phase):
    """What the review rounds have cost so far, read from the usage ledger by
    phase through `audit-usage.py --phase --json` - the one reader every cost
    surface prices through: the phase's rows with no task (its reviews and the
    main loop's own turns) and its fix tasks' rows, with the rate basis beside
    the figure, the tokens no rate covers said to be unpriced, and a ledger
    that is absent or unreadable said so."""
    code, out, err = run_verb(ctx, "audit-usage.py", [
        ctx["manifest"], "--phase", phase["id"], "--json", "--project-dir",
        ctx["project"]])
    try:
        usage = json.loads(out) if code == 0 else None
    except ValueError:
        usage = None
    if not isinstance(usage, dict):
        return ["  rounds' cost: not known - audit-usage.py exit %d: %s" % (
            code, _clip(_excerpt.reason_of(err, out) or "no output", 80))]
    fixers = set(t.get("id") for t in _tasks(phase) if _fr.is_fix_task(t, phase))
    slots = [slot for key, slot in (usage.get("byTask") or {}).items()
             if key == NO_TASK_KEY or key in fixers]
    rows = sum(slot.get("msgs") or 0 for slot in slots)
    tokens = sum(slot.get("tokens") or 0 for slot in slots)
    unpriced = sum(slot.get("unpricedTokens") or 0 for slot in slots)
    if not slots:
        return ["  rounds' cost: not known - the usage ledger%s attributes "
                "nothing to %s's reviews or fix tasks" % (
                    "" if usage.get("ledgerDir") else " (none found)",
                    phase["id"])]
    if unpriced and unpriced >= tokens:
        return ["  rounds' cost: unpriced - %d token(s) over %d message(s), on "
                "models no rate covers" % (unpriced, rows)]
    cost = sum(slot.get("costUSD") or 0.0 for slot in slots)
    return ["  rounds' cost so far: %.2f USD-eq over %d message(s) of the "
            "phase's reviews, main loop and fix tasks%s" % (
                cost, rows, "; %d token(s) unpriced" % (unpriced,)
                if unpriced else ""),
            "  priced at %s" % (usage.get("rateBasis")
                                or "a rate basis audit-usage.py did not name",)]


def round_wanted(still, after):
    """Whether the triage would ask for another review round: a fix closed
    since the last review owes one, or a med-or-worse finding is still open,
    whose fix would. Open lows are carried, which needs no round."""
    return bool(after) or any(f.get("severity") != CARRY_SEVERITY for f in still)


def carried_now(state, phase):
    """`{finding id: target}` of the `carry` answers whose finding is still
    open - a finding fixed or dispositioned since is no longer carried."""
    held = state.get(CARRIED_FIELD) if isinstance(state.get(CARRIED_FIELD),
                                                  dict) else {}
    open_ids = set(f.get("id") for f in open_findings(phase))
    return dict((fid, to) for fid, to in held.items() if fid in open_ids)


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
    still, handed = triage_findings(phase)
    carried = carried_now(state, phase)
    still = [f for f in still if f.get("id") not in carried]
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
    extra = {"findings": still, "handed": handed, "answers": answers,
             "fixesAfter": after, "head": (mark.get("head") or "")[:12],
             "carried": [{"id": fid, "to": to}
                         for fid, to in sorted(carried.items())]}
    if ctx.get("advance") is not None:
        reason = ctx.pop("advance")
        if advance_applies(review, extra):
            ctx["did"].append("sign-off answered in advance")
            return apply_phase_answer(ctx, state, manifest, phase, dict(
                extra, decision="triage", task=None, start=None, why=said),
                ADVANCE_ANSWER, reason, ())
        ctx["did"].append(ADVANCE_NOT_APPLIED % (
            "the triage below has more than one answer",))
    rounds, cap, problem = review_rounds(ctx, state, phase)
    if problem:
        return _stopped(ctx, problem)
    if rounds >= cap and round_wanted(still, after) and not answers:
        # THE LOOP STOPS HERE, ONCE: another round is wanted and the cap is
        # spent, so the human is asked whether it is worth one - with what is
        # open and what the rounds cost - rather than offered `fix` and
        # `re-review` again. A reviewer answer waiting on a human is settled
        # at the triage first: no answer here would settle it.
        return decision(ctx, state, "round-cap", None, (
            "%d of %d review round(s) spent; %d finding(s) open%s" % (
                rounds, cap, len(still), "; %d fix(es) unreviewed" % (
                    len(after),) if after else "")), extra=dict(
            extra, rounds=rounds, cap=cap,
            cost=rounds_cost_lines(ctx, phase)))
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


def fix_tests(fid, finding):
    """The `tests` block a fix task over `finding` is added with, or None to
    leave the mode to the verb. A finding whose `file` names only test files -
    a missing case, a pin over code already at HEAD - is resolved by adding a
    case, which passes at HEAD with or without the fix: no red can be shown
    first, so it is `regression`, its red shown by restoring the old code in a
    scratch copy. The verb would give a test file that does not exist yet
    `tdd`, which the red-first helper rightly refuses."""
    paths = _phases.gate_entry_paths(finding.get("file") or "")
    if not paths or not all(_fr.is_test_path(p) for p in paths):
        return None
    return {"mode": "regression",
            "add": ["%s: the case %s asks for, locking the behaviour at HEAD"
                    % (p, fid) for p in paths]}


def add_fix_tasks(ctx, phase, fixes):
    """A task for each named finding, every one in ONE `audit-task.py add
    --from-file -` call; None, or the stop.

    THE BATCH GOES ON STDIN, WHERE NO VALUE IS A FLAG. A finding's issue and
    resolution are free text, and passed one call each as `--description` the
    argv prose check refused a text holding ` :400` part-way through, leaving
    some findings with a task and the rest without. The batch form writes each
    task's `fixes` and each finding's `fixTask` as `--fixes` does, scopes each
    task from every path its finding names, and lands whole or not at all."""
    by_id = dict((f.get("id"), f) for f in open_findings(phase))
    tasks = []
    for fid in fixes:
        found = by_id.get(fid) or {}
        task = {"title": _clip("fix %s: %s" % (fid, found.get("issue") or ""), 80),
                "description": "%s\n\nResolution asked: %s" % (
                    found.get("issue") or "", found.get("resolution") or ""),
                "fixes": [fid]}
        tests = fix_tests(fid, found)
        if tests:
            task["tests"] = tests
        tasks.append(task)
    out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "add", ctx["manifest"], "--project-dir", ctx["project"], "--from-file",
        "-", "--json"], stdin=json.dumps({"phase": {"id": phase["id"]},
                                          "tasks": tasks}))
    if stop is not None:
        return stop
    try:
        added = json.loads(out).get("tasks") or []
    except ValueError:
        added = []
    for i, fid in enumerate(fixes):
        ctx["did"].append("fix task %s added for %s"
                          % (added[i] if i < len(added) else "?", fid))
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
    # THE HUMAN'S WORDS ARE THE DISPOSITION. A `sign-off` answered over an
    # open finding - one no fix task landed for - is the human accepting it
    # open, and the verb refuses a sign-off that leaves one unsaid, so each is
    # recorded with the reason the answer carried. A finding handed to a fix
    # task still to run is not offered one: that task is its answer. One a
    # `carry` answer handed on is recorded as carried to the id it named.
    carried = carried_now(state, phase)
    for finding in triage_findings(phase)[0]:
        args += (["--carried", "%s=%s" % (finding["id"], carried[finding["id"]])]
                 if finding["id"] in carried else
                 ["--accept-open", "%s=%s" % (finding["id"], summary)])
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
    if answer == "carry":
        ids = carry_ids(pending)
        held = dict(state.get(CARRIED_FIELD) or {})
        held.update((fid, ctx["carryTo"].strip()) for fid in ids)
        state[CARRIED_FIELD] = held
        write_state(ctx, state)
        ctx["did"].append("carried %s to %s" % (", ".join(ids) or "nothing",
                                                ctx["carryTo"].strip()))
        if name == "triage":
            return None
    if answer == "one-more-round":
        state[EXTRA_ROUNDS_FIELD] = (state.get(EXTRA_ROUNDS_FIELD) or 0) + 1
        write_state(ctx, state)
        ctx["did"].append("one more review round allowed")
        if not pending.get("fixesAfter"):
            return None
        answer = "re-review"
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
    if answer in ("sign-off", "carry"):
        # At the round cap `carry` signs off too, its reason the summary.
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
    stop = release_lock(ctx, state)
    if stop is not None:
        return stop
    for kind in [k for k, v in state.items() if isinstance(v, dict)]:
        state[kind].pop(task["id"], None)
        if not state[kind]:
            state.pop(kind)
    if state:
        write_state(ctx, state)
    else:
        drop_state(ctx)
    closed = any(d.startswith("%s %s" % (CLOSED, task["id"])) for d in ctx["did"])
    why = "%s%s" % ("" if closed else "already ", task.get("status") or "?")
    if task.get("commit"):
        why = "%s at %s" % (why, str(task["commit"])[:7])
    return done_task_said(ctx, task["id"], why)


def drive_task(ctx, state):
    """The steps of the one task `ctx["only"]` names: start it, advance it, and
    finish when it is terminal. Its siblings and sign-off are not touched."""
    for _ in range(8):
        manifest, phase = load_phase(ctx)
        task = _mio.tasks_by_id(manifest).get(ctx["only"]) or {}
        if task.get("status") in _mio.TERMINAL:
            return _as_result(finish_task(ctx, state, task))
        if task.get("status") == "blocked":
            ctx["stop"] = "stop-blocked"
            return E_STOPPED, "\n".join(blocked_stop(
                "stop-blocked", [task], phase=ctx["phase"], task=task["id"],
                why=_clip(str(task.get("blockedReason") or "no reason recorded"), 120)))
        if task.get("status") != "in_progress":
            stop = scope_gap(ctx, state, task) or start_task(ctx, task)
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
    """`(code, instruction_or_text)` for one `next`. The lock is kept only while
    a decision is PENDING (handed to the human, the next `--answer` must find
    it) or a dispatch is OUT (a task started whose executor or reviewer return
    is not filed yet); every other non-zero return after it was taken
    gives it back here, the one exit every arm shares, so no refusal strands it.
    The one exception is a usage refusal whose plan cannot be read to tell
    whether a dispatch is out: the lock is kept, because releasing it could let
    a second session take a phase whose executor may still be running, and the
    next drive over a readable plan gives it back."""
    state = read_state(ctx)
    stop = take_lock(ctx, state)
    if stop is not None:
        return stop
    try:
        code, said = drive_locked(ctx, state, answer, reason, fixes)
    except ValueError as exc:
        code, said = E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], exc)
    except BaseException:
        # Not a stop this driver knows: give the lock back, then let it surface.
        if state.get("lock") == "taken":
            give_back_lock(ctx, state)
        raise
    give, kept_why = lock_to_give_back(code, state, ctx)
    if kept_why:
        said = "%s\n%s" % (said, kept_why)
    if not give:
        return code, said
    refused = give_back_lock(ctx, state)
    if refused is not None:
        return code, "%s\n%s" % (said, refused[1])
    return code, said


def lock_to_give_back(code, state, ctx):
    """`(give_back, note)`: whether a drive that returned `code` still holds a
    lock nobody will answer for - the lock is taken and the return is a stop,
    or a usage refusal with no decision pending and no dispatch out to keep it
    for - and a line to print when the lock was kept for want of an answer."""
    if state.get("lock") != "taken":
        return False, None
    if code == E_STOPPED:
        return True, None
    if code != E_USAGE or state.get("pending") is not None:
        return False, None
    out, why = dispatch_out(ctx, state)
    if why:
        return False, "%s %s: phase lock kept - the plan could not be read to tell " \
                      "whether a dispatch is out (%s); a later next releases it" \
                      % (PREFIX, ctx["phase"], why)
    return not out, None


def dispatch_out(ctx, state):
    """`(out, why)`: whether a task of the phase was dispatched and its return
    is not filed - an in-progress task holding a dispatch mark for its current
    start, with no filed return of that role. A phase that has vanished has
    none. `why` names the read error when the plan could not be read, in which
    case `out` is False and means nothing."""
    try:
        _manifest, phase = load_phase(ctx)
    except ValueError:
        return False, None
    except OSError as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    for task in _tasks(phase):
        if task.get("status") != "in_progress":
            continue
        for role in ("executor", "reviewer"):
            if (_marked(state, "dispatched-%s" % (role,), task)
                    and filed(ctx, task, role) == (None, None)):
                return True, None
    return False, None


def give_back_lock(ctx, state):
    """None once the phase lock is released and the state rewritten (or dropped
    when nothing else is left in it); else release_lock's own refusal."""
    refused = release_lock(ctx, state)
    if refused is not None:
        return refused
    if state:
        write_state(ctx, state)
    else:
        drop_state(ctx)
    return None


def refresh_triage(ctx, state, phase, pending):
    """The pending triage as the plan stands now, or None when it no longer
    waits on anyone. A fix task added by hand since it was printed answers the
    finding it names: with every med-or-worse finding handed to one, the triage
    is satisfied and the drive goes on to run them; otherwise the handed ones
    leave the offered list, so `--answer fix` is never offered for a finding
    the verb would refuse a second task."""
    if triage_handed_off(phase):
        state.pop("pending", None)
        write_state(ctx, state)
        ctx["did"].append("triage satisfied: %s handed to fix task(s) to run" % (
            ", ".join(f.get("id") for f in triage_findings(phase)[1]),))
        return None
    offered, handed = triage_findings(phase)
    carried = carried_now(state, phase)
    offered = [f for f in offered if f.get("id") not in carried]
    if offered != pending.get("findings") or handed != (pending.get("handed") or []):
        pending = dict(pending, findings=offered, handed=handed)
        state["pending"] = pending
        write_state(ctx, state)
    return pending


def drive_locked(ctx, state, answer, reason, fixes):
    """The body of `drive`, run with the phase lock held."""
    manifest, phase = load_phase(ctx)
    pending = state.get("pending")
    if pending and not pending_still_applies(manifest, pending):
        state.pop("pending", None)
        write_state(ctx, state)
        pending = None
    if pending and pending["decision"] == "triage":
        pending = refresh_triage(ctx, state, phase, pending)
    if ctx.get("only") and pending and pending.get("task") != ctx["only"]:
        return E_STOPPED, ("%s %s: stopped - this phase's drive waits on a %s "
                           "decision; answer it with next %s first"
                           % (PREFIX, ctx["phase"], pending["decision"], ctx["phase"]))
    if (answer == ADVANCE_ANSWER and pending is None and not ctx.get("only")
            and not fixes and not ctx.get("carryTo")
            and advance_admissible(phase)):
        if not (reason or "").strip():
            return E_USAGE, "%s %s: --answer %s needs --reason: it is recorded " \
                            "with the phase" % (PREFIX, ctx["phase"], answer)
        ctx["advance"] = reason
        code, said = drive_phase(ctx, state, phase)
        if ctx.pop("advance", None) is not None:
            ctx["did"].append(ADVANCE_NOT_APPLIED % ("no triage was reached",))
        return code, said
    if answer is not None:
        refused = (answer_refusal(ctx, pending, answer, reason, fixes)
                   or carry_target_refusal(ctx, manifest, phase, answer))
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
    if width > 1 and not state.get("wave"):
        width, basis = hooks_width(ctx, width, basis)
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
            return E_OK, stalled_said(
                ctx, [t for t in _tasks(phase)
                      if t.get("status") not in _mio.TERMINAL],
                stalled_why(manifest, phase))
        if how == "ready":
            stop = scope_gap(ctx, state, task) or start_task(ctx, task)
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
    ctx["stop"] = "stopped"
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


def submitted_shape(role, body, fills, task=None):
    """The ways `body` falls short of `role`'s shape, judged with each field in
    `fills` set aside: those are `submit`'s to supply, not the agent's. `task`
    is passed through for a reviewer in `mode: task`, so an unsupported
    `matches` is refused rather than filed."""
    if not isinstance(body, dict):
        return _fr.return_problems(role, body, task)
    held = dict(body)
    held.update((name, _FILLED_LATER[name]) for name in fills)
    return _fr.return_problems(role, held, task)


def already_filed(ctx, task):
    """The project-relative path of `task`'s executor return for its current
    start when one is filed - on disk, or when a `task.return.filed` journal
    row already names it, EVEN WITH THE FILE DELETED (an executor once
    filed a placeholder, deleted it, and filed again, and nothing recorded
    either filing) - else None. The filing verb refuses a second
    filing on its own; asking first is what keeps a refusal from costing a
    red run and a stamp."""
    path = _fr.return_path(ctx["evidence"], task, "executor")
    if not path:
        return None
    if os.path.exists(path):
        return project_relative(ctx, path)
    try:
        rows = _journal_io.read_all(ctx["project"], ctx["config"])
    except Exception:                                          # noqa: BLE001
        return None
    return (project_relative(ctx, path)
           if _fr.already_filed_row(rows, path, ctx["project"]) else None)


def _journal_filed_return(ctx, task, role, path, red_status):
    """Append `_fr.filed_return_row`'s entry for the return just written at
    `path` - the one thing that lets a filing stay "once" even after
    its file is deleted, which the exclusive create alone cannot do. Fail-soft
    like every journal append here: reported on the did-line, never raised."""
    row = _fr.filed_return_row(path, ctx["project"], task["id"], role,
                               red_status)
    if row is None:
        return
    row["actor"] = {"sessionId": os.environ.get("CLAUDE_CODE_SESSION_ID"),
                    "via": "cli"}
    written, why = _journal_io.append_from_cli_why(ctx["project"], row)
    if not written:
        ctx["did"].append("journal row %s not written (%s)"
                          % (_fr.RETURN_FILED_ACTION, why))


def _utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def declares_test(task):
    """Whether `task` names a test file - in `files` or as a `tests.add` case -
    for the red-first helper to copy over HEAD."""
    tests = task.get("tests") or {}
    named = [str(f) for f in task.get("files") or []] + [
        str(a).split(":", 1)[0] for a in tests.get("add") or []]
    return any(_fr.is_test_path(p.strip()) for p in named)


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
    extra.append("--derive-introduces")
    code, out, err = run_verb(ctx, "stamp-verification.py", [
        "red", "--project", tree or ctx["gitRoot"], "--manifest", ctx["manifest"],
        "--task", task["id"], "--json"] + extra + ["--"] + list(cmd))
    try:
        payload = json.loads(out)
    except ValueError:
        if not declares_test(task):
            # A PROOF THE PLAN GAVE NOTHING TO MAKE WITH. A tdd task naming no
            # test file - a fix task over a finding that names only source -
            # has no case to copy over HEAD, and the helper refuses before
            # anything runs. That is `could-not-prove` with its words, filed so
            # the reviewer reads it, rather than a stop no return can pass.
            return {"status": "could-not-prove", "at": _utc_stamp(),
                    "basis": "%s declares no test file in `files` or `tests.add`, "
                             "so no red could be run; the helper said: %s"
                             % (task["id"], " ".join((out + err).split()))}, None
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
                              % (code, STAMP_TOKEN, _excerpt.reason_of(err, out)))
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


_HEX_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def whole_head(ctx, head):
    """`head` as the whole commit id a phase return is keyed on and the driver
    looks it up under, when git resolves a shorter spelling of it to exactly one
    commit; `head` unchanged otherwise, so an unknown or ambiguous one is still
    the filing verb's refusal."""
    if not isinstance(head, str) or not _HEX_SHA.match(head) or len(head) == 40:
        return head
    try:
        done = subprocess.run(
            ["git", "-C", ctx["gitRoot"], "rev-parse", "--verify", "--quiet",
             head + "^{commit}"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return head
    found = done.stdout.strip()
    return found if done.returncode == 0 and found.startswith(head) else head


def agreed_commits(phase, entries):
    """`entries` (a phase return's per-task answers) with each commit spelled as
    the plan records it, where the two are the same commit written at different
    lengths: the plan keeps twelve characters and git prints forty, and a
    prefix of one is the other. An entry naming another commit, or a task the
    phase does not hold, is left as typed for the verb to refuse."""
    recorded = dict((t["id"], t.get("commit")) for t in _tasks(phase))
    out = []
    for entry in entries:
        said = entry.get("commit") if isinstance(entry, dict) else None
        want = recorded.get(entry.get("id")) if isinstance(entry, dict) else None
        if (isinstance(said, str) and isinstance(want, str) and said != want
                and _HEX_SHA.match(said) and _HEX_SHA.match(want)
                and (said.startswith(want) or want.startswith(said))):
            entry = dict(entry, commit=want)
        out.append(entry)
    return out


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
    problems = (submitted_shape(args.role, body, fills, task)
               if task is not None else [])
    if problems:
        return _stopped(ctx, "the %s return for %s does not have the shape its "
                        "role declares. Nothing filed:\n%s" % (
                            args.role, args.id,
                            "\n".join("  " + p for p in problems)))
    if args.role == "reviewer" and isinstance(body.get("findings"), list):
        floored = floor_contradicted_clause(body["findings"])
        if floored != body["findings"]:
            body["findings"] = floored
            text = json.dumps(body, indent=2) + "\n"
            ctx["did"].append("a contradicted-clause finding was raised to med")
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
            body["redFirst"] = dict(block, source=_fr.HELPER_SOURCE)
            ctx["did"].append("red-first %s" % (block.get("status"),))
        if not cmd and isinstance(body.get("redFirst"), dict):
            # No helper ran, so the mark is not ours to leave on a typed block.
            body["redFirst"].pop("source", None)
        line, stop = take_stamp(ctx, task, tree) if tree else take_stamp(ctx, task)
        if stop is not None:
            return stop
        body["stamp"] = line
        ctx["did"].append("stamp taken")
        gaps = tests_add_gaps(task, body.get("testsAdded"))
        if gaps:
            ctx["did"].append(
                "tests.add names %d case(s) with no filed counterpart: %s"
                % (len(gaps), "; ".join(gaps)))
        text = json.dumps(body, indent=2) + "\n"
    head = args.head
    if task is None and args.role == "reviewer":
        head = whole_head(ctx, head)
        if isinstance(body, dict) and isinstance(body.get("tasks"), list):
            body["tasks"] = agreed_commits(phase, body["tasks"])
            text = json.dumps(body, indent=2) + "\n"
    extra = ["--head", head] if head else []
    out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "file-return", args.id, "--role", args.role, ctx["manifest"],
        "--project-dir", ctx["project"]] + extra, stdin=text)
    if stop is not None:
        return stop
    written = re.search(r"written: (.+)$", out.strip())
    if executor and written:
        path = _fr.return_path(ctx["evidence"], task, "executor")
        if path:
            _journal_filed_return(ctx, task, args.role, path,
                                  (body.get("redFirst") or {}).get("status"))
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


# --- the signal and its explain ----------------------------------------------------
def _width(text):
    return len(text.encode("utf-8"))


def _flat(text):
    """One line, its ` | ` separators taken by the signal itself."""
    return " ".join(str(text or "").replace(" | ", " / ").split())


def _fit(text, width):
    """`text` inside `width` bytes, cut with `...`; nothing when no room is left
    for a cut that says it was cut."""
    if _width(text) <= width:
        return text
    return _clip(text, width) if width >= 4 else ""


def signal_verb_gaps():
    """Every step `SIGNAL_VERBS` gives no verb of `VERBS`, and every entry of it
    naming no step. Empty is the one answer that holds."""
    out = ["%s: no verb" % (s,) for s in sorted(STEPS) if s not in SIGNAL_VERBS]
    out += ["%s: verb %r is not one of VERBS" % (s, v)
            for s, v in sorted(SIGNAL_VERBS.items()) if v not in VERBS]
    out += ["%s: has a verb and is no step" % (s,)
            for s in sorted(SIGNAL_VERBS) if s not in STEPS]
    return out


def did_word_clause(clause):
    """A did-line clause as the signal carries it: the words `did_events` reads
    and no more - a start or a close and its id, a fix task's added-for words,
    a landing - and any other clause whole."""
    words = _flat(clause).split(" ")
    if clause.startswith(FIX_ADDED + " "):
        return " ".join(words[:6])
    if words[0] in (STARTED, CLOSED):
        return " ".join(words[:2])
    return LANDED if words[0] == LANDED else " ".join(words)


def read_clauses(clauses):
    """`(read, rest)` of the did-line clauses as the signal carries them. `read`
    is every one `did_events` reads, losslessly and compactly: the starts as
    one `join_ids` word, the closes as another, each fix task's added-for words,
    then a sign-off, a landing and a release once each. `rest` is every other
    clause, in order, as `did_word_clause` gives it."""
    said = [did_word_clause(c) for c in clauses if _flat(c)]
    ids, order, fixes, flags, rest = {STARTED: [], CLOSED: []}, [], [], [], []
    for clause in said:
        words = clause.split(" ")
        if words[0] in ids and len(words) == 2:
            order += [] if ids[words[0]] else [words[0]]
            ids[words[0]].append(words[1])
        elif _is_fix_added(words):
            fixes.append(clause)
        elif clause in (SIGNED, LANDED, RELEASED):
            flags += [] if clause in flags else [clause]
        else:
            rest.append(clause)
    read = ["%s %s" % (word, join_ids(ids[word])) for word in order]
    return read + fixes + [f for f in (SIGNED, LANDED, RELEASED) if f in flags], rest


def fit_rest(rest, width):
    """The clauses `did_events` does not read, inside `width` bytes, whole or not
    at all: in order while they fit, and `+N` for the ones left out. A clause is
    never cut, since a cut id would be read back as another task's."""
    def text(keep):
        left = len(rest) - len(keep)
        return "; ".join([rest[i] for i in keep] + (["+%d" % (left,)] if left else []))
    keep = []
    for i in range(len(rest)):
        if _width(text(keep + [i])) <= width:
            keep.append(i)
    return text(keep) if _width(text(keep)) <= width else ""


def signal_line(ctx, verb, subject, clauses, basis, nxt):
    """The one line: the head, then every did-clause `did_events` reads, never
    dropped; then the next command whole or, when it cannot fit beside them
    with room for the start of the basis, the `--explain` that prints it; then
    the other did-clauses while they fit, and the basis in what is left.

    The read clauses are what a session's cost is attributed by afterwards -
    `tools/stream-cost.py` reads them off this line in the transcript, and the
    `.explain` file is overwritten by the next signal - so the basis and the
    `next:` field shrink for them instead. Inside `SIGNAL_BYTES` whenever those
    clauses and the shorter of the two commands fit beside the head; a step
    whose read events alone are longer prints them whole past the bound, since
    a dropped one would move a span with nothing saying so."""
    subject = _fit(_flat(subject) or ctx["phase"], 60)
    head = "audit %s %s %s" % (ctx["phase"], verb, subject)
    read, rest = read_clauses(clauses)
    did = "; ".join(read)
    fixed = _width(head) + (_width(did) + 1 if did else 0) + _width(" |  | next: ")
    nxt = _flat(nxt) or "wait"
    explain = explain_command(ctx, subject)
    if fixed + _width(nxt) > SIGNAL_BYTES - 40 and _width(explain) < _width(nxt):
        nxt = explain
    room = SIGNAL_BYTES - fixed - _width(nxt)
    basis = _flat(basis)
    joint = 2 if did else 1
    more = fit_rest(rest, room - min(_width(basis), 40) - joint)
    if more:
        room -= _width(more) + joint
    auto = "; ".join(read + ([more] if more else []))
    return "%s%s | %s | next: %s" % (head, " " + auto if auto else "",
                                     _fit(basis, room), nxt)


def stop_basis(text):
    """A stop's first two lines, the driver's prefix dropped."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "the drive stopped and printed nothing"
    if lines[0].startswith(PREFIX):
        lines[0] = lines[0].partition(": ")[2]
    return " / ".join(lines[:2])


def signal(ctx, code, said):
    """`{"line", "subjects", "explain"}` for one `next --signal`: the line, the
    ids `--explain` answers for it, and the whole text the line stands for."""
    fields = said.get("signal") if isinstance(said, dict) else None
    target = drive_target(ctx)
    if fields is not None:
        step, subject = fields["step"], fields["subject"]
        basis, nxt = fields["basis"], fields["next"]
    elif isinstance(said, dict):
        step, subject, nxt = "stopped", target, explain_command(ctx, target)
        basis = "the drive printed a %s step that carries no signal" % (
            said.get("kind"),)
    else:
        step, subject = ctx.get("stop") or "stopped", target
        basis = stop_basis(said)
        nxt = ("wait" if SIGNAL_VERBS.get(step) == "wait"
               else explain_command(ctx, target))
    full = render(ctx, code, said)
    echo = ado_echo_lines(ctx)
    if echo:
        basis = "%s; %s" % (basis, echo[0])
    prompts = list((fields or {}).get("prompts") or [])
    return {"line": signal_line(ctx, SIGNAL_VERBS.get(step, "stop"), subject,
                                ctx["did"], basis, nxt),
            "subjects": [subject] + list((fields or {}).get("subjects") or []),
            "explain": "\n".join([full] + ["prompt: %s" % (p,) for p in prompts])}


def explain_text(lines):
    """`lines` inside `EXPLAIN_BYTES`: the first line and every `answer:` line
    are kept, so the options always print; the others in order while they fit,
    and a last line says how many were cut."""
    text = "\n".join(lines)
    if _width(text) <= EXPLAIN_BYTES:
        return text
    must = set([0] + [i for i, ln in enumerate(lines) if ln.startswith("answer:")])
    shown = dict((i, _fit(lines[i], 300)) for i in must)
    budget = EXPLAIN_BYTES - 80 - sum(_width(v) + 1 for v in shown.values())
    for i, line in enumerate(lines):
        if i not in shown and _width(line) + 1 <= budget:
            shown[i] = line
            budget -= _width(line) + 1
    return "\n".join([shown[i] for i in sorted(shown)] + [
        "... %d line(s) cut to stay inside %d bytes" % (
            len(lines) - len(shown), EXPLAIN_BYTES)])


def explain_path(ctx):
    return state_path(ctx)[:-len(".json")] + EXPLAIN_SUFFIX


def write_explain(ctx, said):
    """Keep the text the last signal stands for; None, or why it was not kept."""
    path = explain_path(ctx)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            json.dump({"subjects": said["subjects"], "text": said["explain"]}, fh)
    except OSError as exc:
        return "the text --explain prints was not kept at %s (%s)" % (path, exc)
    return None


def read_explain(ctx):
    try:
        with open(explain_path(ctx), "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def explain(ctx, subject):
    """`(code, text)` - the step a signal about `subject` stands for: a decision
    waiting on it, rendered from the plan now, else the text the last signal
    kept. Read only: no lock is taken and nothing is written."""
    state = read_state(ctx)
    manifest = _mio.load_manifest(ctx["manifest"])
    parked = ((state.get("wave") or {}).get("parked") or {}).values()
    for pending in [state.get("pending")] + list(parked):
        if (isinstance(pending, dict)
                and subject == (pending.get("task") or ctx["phase"])
                and pending_still_applies(manifest, pending)):
            return E_OK, explain_text(render_decision(ctx, pending)["lines"])
    kept = read_explain(ctx)
    if kept and subject in (kept.get("subjects") or []):
        return E_OK, explain_text(str(kept.get("text") or "").splitlines())
    return E_USAGE, ("%s %s: nothing to explain for %s - no decision waits on "
                     "it and the last signal named %s" % (
                         PREFIX, ctx["phase"], subject,
                         ", ".join((kept or {}).get("subjects") or ["nothing"])))


def run_brief(args, out):
    """`brief <id> --role <role>`: print the brief the drive wrote for that dispatch,
    as `audit-lookup.py brief --read` reads it for the id's current start - a
    record, so read back with its bytes as they are (`run_verb`)."""
    if args.manifest and args.manifest_named and args.manifest != args.manifest_named:
        out("drive-phase.py: two manifests named, %s and --manifest %s"
            % (args.manifest, args.manifest_named))
        return E_USAGE
    args.manifest = args.manifest or args.manifest_named
    try:
        _manifest, ctx = project_context(args)
    except Exception as exc:                                   # noqa: BLE001
        out("drive-phase.py: %s" % (exc,))
        return E_USAGE
    code, said, err = run_verb(ctx, "audit-lookup.py", [
        ctx["manifest"], "brief", args.id, "--role", args.role, "--read",
        "--project", ctx["project"]], record=True)
    if code != 0:
        out("drive-phase.py: no brief to print - %s" % ((err or said).strip(),))
        return E_USAGE
    out(said.rstrip("\n"))
    return E_OK


# --- the command line -------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="drive-phase.py", add_help=True, allow_abbrev=False,
        description="Run every step of a phase that needs no judgement and print "
                    "one instruction; --signal prints it as one line.")
    sub = parser.add_subparsers(dest="action")
    sub.required = True
    nxt = sub.add_parser("next", help="perform the due steps, print one instruction")
    nxt.add_argument("phase", help="the phase id, or a task id to drive that "
                                   "one task")
    nxt.add_argument("manifest", nargs="?", default=None,
                     help="the manifest (default: the project's configured one)")
    nxt.add_argument("--project-dir", dest="project_dir", default=None)
    nxt.add_argument("--task", dest="task_only", action="store_true",
                     help="the one-task form `/audit:run` passes: a phase id is "
                          "refused, naming /audit:phase, and no task is picked")
    nxt.add_argument("--answer", default=None,
                     help="answer the pending decision with one of its options")
    nxt.add_argument("--reason", default=None,
                     help="the reason an option that records one needs; for "
                          "the triage's sign-off, the phase's summary")
    nxt.add_argument("--fix", action="append", default=[],
                     metavar="FINDING[,FINDING]",
                     help="with --answer fix: the findings to fix, each "
                          "becoming a task through `add --fixes`")
    nxt.add_argument("--to", dest="carry_to", default=None, metavar="ID",
                     help="with --answer carry: the task of a later phase, or "
                          "the bug, that now holds the carried findings")
    nxt.add_argument("--verbose", action="store_true",
                     help="print each verb's run above the instruction")
    nxt.add_argument("--signal", action="store_true",
                     help="print the step as one line of at most %d bytes; "
                          "--explain prints the text it stands for" % (SIGNAL_BYTES,))
    nxt.add_argument("--explain", default=None, metavar="ID",
                     help="print, within %d bytes, the step the last signal "
                          "about ID stands for, or the decision waiting on it; "
                          "drives nothing" % (EXPLAIN_BYTES,))
    brf = sub.add_parser("brief", help="print the brief written for an agent's "
                         "dispatch: the dispatch prompt runs this")
    brf.add_argument("id", help="the task id, or the phase id for `--role phase`")
    brf.add_argument("--role", required=True, choices=("executor", "reviewer", "phase"))
    brf.add_argument("manifest", nargs="?", default=None,
                     help="the manifest (default: the project's configured one)")
    brf.add_argument("--manifest", dest="manifest_named", default=None,
                     metavar="PATH", help="the manifest, named where the id "
                     "must come last - the dispatch prompt's spelling")
    brf.add_argument("--project-dir", dest="project_dir", default=None)
    brf.add_argument("--verbose", action="store_true")
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
    # may stand anywhere - a wave member's own tree holds a committed copy of
    # the same relative path - so a relative path is always read from the
    # project it names, never from the cwd.
    if named and not os.path.isabs(named):
        named = os.path.join(project, named)
    found = _mio.resolve_manifest(project, named)
    if not found.get("path"):
        raise ValueError(found.get("problem") or "no manifest at %s" % (
            ", ".join(p for p, _w in found.get("looked") or []),))
    manifest_path = os.path.abspath(found["path"])
    manifest = _mio.load_manifest(manifest_path)
    # The session's directory only STARTS the search for a manifest; once one is
    # found, the project is --project-dir when typed and otherwise the one the
    # manifest belongs to, so the evidence lands where the gate and the report
    # read it whatever directory the run was started from.
    project, config = _evio.project_config_for(
        manifest_path, os.path.abspath(args.project_dir) if args.project_dir
        else None)
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


def phase_form_refusal(manifest, config, phase_id):
    """The one line `next --task` answers a phase-shaped id with: it names
    `/audit:phase <id>` and the tasks that verb would run, in waves when
    `executor.waveWidth` is above 1 and one at a time otherwise."""
    phase = next((ph for ph in manifest.get("phases") or []
                  if isinstance(ph, dict) and ph.get("id") == phase_id), {})
    ready = set(_status_facts.ready_tasks(manifest))
    running = [t["id"] for t in _tasks(phase) if t.get("status") == "in_progress"]
    would = running + [t["id"] for t in _tasks(phase) if t["id"] in ready]
    width, _basis, _problem = wave_width(config)
    how = ("in waves of up to %d" % (width,) if width and width > 1
           else "one at a time")
    return ("%s is a phase, and /audit:run runs exactly one task: run "
            "`/audit:phase %s` to run %s %s, or name one task id%s" % (
                phase_id, phase_id, ", ".join(would) or "its tasks", how,
                "" if would else " (none is ready now)"))


def context(args):
    """Everything one `next` resolves once, or raises ValueError naming why not.
    A task id in the phase's place scopes the drive to that one task."""
    manifest, ctx = project_context(args)
    phase_id, problem = _mio.resolve_phase_id(manifest, args.phase)
    if not problem and getattr(args, "task_only", False):
        raise ValueError(phase_form_refusal(manifest, ctx["config"], phase_id))
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
    if args.action == "brief" and cmd is None:
        return run_brief(args, out)
    if cmd is not None:
        sys.stderr.write("drive-phase.py: only `submit` takes a command after "
                         "`--`\n")
        return E_USAGE
    try:
        ctx = context(args)
    except Exception as exc:                                   # noqa: BLE001
        sys.stderr.write("drive-phase.py: %s\n" % (exc,))
        return E_USAGE
    if args.explain:
        if args.answer is not None or args.signal:
            out("drive-phase.py: --explain only reads; it takes no --answer "
                "and no --signal")
            return E_USAGE
        try:
            code, text = explain(ctx, args.explain)
        except (ValueError, OSError) as exc:
            code, text = E_USAGE, "%s %s: nothing explained - %s" % (
                PREFIX, ctx["phase"], exc)
        out(text)
        return code
    ctx["carryTo"] = args.carry_to
    try:
        fixes = [f.strip() for given in args.fix for f in given.split(",")
                 if f.strip()]
        code, said = drive(ctx, answer=args.answer, reason=args.reason,
                           fixes=fixes)
    except ValueError as exc:
        code, said = E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], exc)
    if not args.signal:
        out(render(ctx, code, said))
        return code
    said = signal(ctx, code, said)
    problem = write_explain(ctx, said)
    if problem:
        sys.stderr.write("drive-phase.py: %s\n" % (problem,))
    out(said["line"])
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
    if _output.own_args(sys.argv[1:])[:1] == ["brief"]:
        # A record, not a step: `terse_cli` would hold it and print it again
        # through stdout's text layer, which is the translation it must not get.
        sys.exit(main(sys.argv[1:], out=write_record))
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line, keep_verbose=True))
