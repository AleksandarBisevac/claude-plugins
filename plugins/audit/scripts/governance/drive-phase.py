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

WHERE A FILED MEMBER'S WORK LIVES BETWEEN FILING AND CLOSE: in its tree, and also
in `refs/audit/carry/<taskId>`, a commit on the tree's HEAD that `submit` writes
(in a scratch index, so the tree is untouched). The ref stays in this
repository: the driver pushes it to `origin` only where the config sets
`ci.pushCarry` to true, because a push publishes unfinished work to a remote the
operator never named, and a driver that pushes of its own accord is not one to
leave running. A hand-off that moves machines carries the records and not
the trees, so with the key set the next `next` with no wave recorded reopens one
over the in-progress tasks whose return is filed and whose carry exists here or
on `origin`, and a tree cut for a filed member starts from its carry; without it
the same reopening finds the carries of this clone only, and a carry made on
another machine is not there to find. A `submit` that did not push says so on its
did-line, and why: the work is then in this repository's ref alone. A task's
carry is taken down when it is terminal, on `origin` too only under the key.

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
    the test command given after `--` - owed on a task that owes a red-first
    proof (`_filed_returns.owes_red_first`: `tdd`, its stored `expectRedFirst`
    not false), and refused there without one; a `tdd` task whose
    `expectRedFirst` is false needs none and is filed `not-attempted` with
    that as the basis;
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

THE WRITER MAY BE A HEADLESS SESSION INSTEAD OF AN AGENT. With
`executor.writerModel` and `executor.writerBudgetUsd` set, the executor's
dispatch is `dispatch-writer`: `brief --role writer` writes the plain prompt, the
print names `run-agent-session.py --role writer`, the task and the model, and
`--explain` prints the whole command as its `run:` line. Each dispatch names a
record file of its own (`session_record`) the runner appends its one line to on
every run, and each step notes every outcome it has not seen once on the task
through `audit-task.py note` - the session id and the cost the session's own
result printed, every path spelled as a committed row may say it
(`note_sessions`); a note the verb refuses is said on the step and not asked
again, since no step waits on a note. While the latest dispatch's record holds
nothing the step is `wait-writer`: the session is running or was never
started, and only the main loop knows which. A red task gate on a task with a
recorded session asks `gate-red-writer`, whose recommended `resume` sends the
gate's failing lines to the latest session and spends no attempt; once
`MAX_RESUME_ROUNDS` are spent the plain `gate-red` is asked, after a note naming
each resumed run, and its `retry` starts a fresh session.

THE PER-TASK REVIEWER IS A SESSION UNDER THE SAME KEYS, AND ITS STREAM IS READ.
Its dispatch names `run-agent-session.py --role reviewer`, on the model
`review.model` when that is a full id and the writer's otherwise, and its prompt
says the session files nothing: the drive files its last message through
`submit` (`reviewer_session_step`). It counts the `tool_use` blocks in the
saved stream first (`stream_tool_calls`), because a review of code no tool
opened is a guess. None is recorded on the task as cannot-tell and the reviewer
is dispatched once more (`MAX_REVIEWER_REDISPATCH`); a second such stream stops
with a note naming both sessions and dispatches no third; a stream nobody can
count in is a stop of its own, never read as a count of none. Nothing enforces
that a session opened the RIGHT files, only that it opened some.

THE WRITER RUNS NO `submit`, SO THE DRIVE RUNS ITS VERBS (`writer_settle`), once
per dispatch whose record holds a session's result; a round that produced none
proves nothing and files nothing, and meets `no-executor-return`. Each dispatch
keeps the commit HEAD named when it was printed. Commits descending from it that
touch the task's files are `writer-committed`, naming the commit: `recheck` once
a human has taken it out, or `block`. Any other move is `head-moved`, and a HEAD
git cannot name on either side is `head-unknown`; both take `file`, which reads
HEAD again. Nothing is filed before any of them is answered.
Otherwise the work is proved - `stamp-verification.py red` with `red_args`, the
arguments `submit` builds, over `_filed_returns.red_command`, the gate command
naming a `tests.add` file, in a throwaway at HEAD with the task's test files
copied over it - and the proof is HELD until the recorded gate is green: a filing
is once per start, and a resume round may change the work. Only a task that
`_filed_returns.owes_red_first` names owes the red; any other is `not-attempted`
with its mode, or for a `tdd` task its false `expectRedFirst`, as the basis, and a tdd
task whose gate names no `tests.add` file is `could-not-prove` with that basis.
THE INVARIANT: the held proof records what it was made over - the HEAD its
throwaway ran at, the `testDigest` of the task's declared test files (locked) and
the `implementationDigest` of its declared implementation files, the ones the fix
run read - and `tree_since_proof` is the one reading of whether those three still
match. Every settle and `file_writer_return` itself ask it: a HEAD or a declared
file that moved is proved again before anything is filed, the changed test files
noted on the task. A file the task does not declare is not in that reading: one
the diff touches is caught at the close, where `commit-task-work.py`'s
`attempt_refusal` refuses by name a path changed during the attempt that no
in_progress task declares. On the writer path that refusal, when it is the
whole of what the commit refused, SETS THE PATHS ASIDE (`writer_commit`): the
writer's prompt is plain's and names no scope, so its edit outside the task is
kept as a patch under the drive's state, put back to HEAD and noted on the task;
the proof is asked again (`prove_and_hold`), the gate is measured again - the
ledger records no list of what a run read - and the commit is asked once more.
Only a path the commit's own attribution shows clean at the start
(`attempt.cleanAtStart`: absent from the start snapshot, so HEAD's bytes are the
ones the attempt began from) is put back; one dirty before the attempt, or with
no snapshot to tell, keeps the refusal, named with that reason. A plugin-owned
path (`_manifest_io.PLUGIN_OWNED_IN_CLAUDE`), or one the writer's answer cites
for a clause, is never set aside either: the refusal is relayed with why.
The executor path keeps the refusal. A red the
helper will not grade (a test that passes without the fix, a test file gone),
or a re-proof that no longer proves what the held proof did, is
`red-refused-writer`, whose `resume` sends the helper's words to the session;
nothing is filed and the lock stays. At the green gate the stamp is taken and
`audit-task.py file-return` files a return built here: the diff's paths, the
proof's block with its HEAD and digest, every re-proof, the stamp, why no
`casesAdded` is bound (`casesAddedBasis`), and the last session's final message
in `writerClaim` - kept as the session wrote it except that `file-return` scrubs
machine paths from every committed return - a claim the gate and the reviewer
grade. `close_task` refuses the commit with `tests-moved`, naming the files,
while a test file differs from the locked digest: the filing and its review were
of other bytes, so `retry` (a new start) is the way on. A file added under a
declared test directory after the lock is not among the locked paths and is not
compared. THE LAST MESSAGE IS ALSO READ FOR CLAUSE COVERAGE, at the green gate and
before the stamp (`_clause_coverage.check`): its closing JSON object must answer every
clause `task_clauses` numbers, and a `delivered` answer must cite a path the diff
touches. A gap - an unanswered or malformed clause, a path outside the diff, or no
JSON object at all - files nothing and asks `clauses-uncovered-writer`, whose `resume`
sends the uncovered clauses to the session as a round of `MAX_RESUME_ROUNDS`; past
them, or with `executor.writerModel` no longer set, it is the plain
`clauses-uncovered` (and `red-refused` for the red), whose `retry` is the way on.
What the writer wrote stays a claim: only whether each clause was answered and
whether the cited file changed is checked.
Without `executor.writerModel` the executor Agent is dispatched as
before.

UNDER A WRITER SESSION A PHASE-REVIEW FINDING BLOCKS ONLY ONCE A SECOND PASS
CONFIRMS IT (`review_findings_step`, run before the triage), and a finding is a
note only on positive evidence: it is low, or that pass withdrew it or confirmed
it as a kind other than correctness or requirement (`sort_findings`). Every
other open finding no pass has judged at HEAD goes to a validation session
(`dispatch-validation`, the reviewer's runner role) whose stream must show a
tool call and whose last message must answer each finding once, `confirmed` or
`withdrawn` with a kind - anything less validates nothing and stops. Its prompt
names the phase's base and each task's commit, and a withdrawal - or `other` -
of a med-or-worse finding is taken only when the stream read a file that
finding cites (`unread_demotions`); otherwise the drive stops. A verdict is
read only while HEAD is the commit it was given at. The triage leaves a note
out, and sign-off records it `--accept-open` with the note as its reason. A
confirmed blocking finding re-opens every task whose own diff - in the
coordinates the phase brief showed it, a deleted line or file included
(`finding_owners`) - holds a cited line; that task's next writer dispatch
resumes its last session when the session's saved stream was last written under
`CACHE_LIFE_SECONDS` ago in the same tree, else starts a fresh session on the
task's brief and the findings. The finding is fixed (`resolve-finding`) only
when the pass re-reads it at the fix's commit and withdraws it. One confirmed in
lines no task's diff holds stops for a human. No fix task is added. A finding
spends a round per filed review or per hand-back, and one still confirmed at
`review.maxRounds` stops the phase and is noted on its task. The commit a re-open
cleared and the findings it was for are read off the journal's re-open row
(`reopen_record`), so a lost state file loses neither.

Usage:
  drive-phase.py next <phaseId|taskId> [manifest] [--project-dir DIR]
                 [--answer OPTION] [--reason TEXT] [--fix FINDING[,FINDING]]
                 [--verbose] [--signal | --explain ID]
  drive-phase.py brief <id> --role executor|reviewer|phase [manifest]
                 [--project-dir DIR]
  drive-phase.py submit <taskId|phaseId> --role executor|reviewer [manifest]
                 [--head SHA] [--shown ID@SHA,...]
                 [--project-dir DIR] [--case ID ...]
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
`tests/test_drive_phase.py`.

Stdlib only, Python 3.8 compatible.
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
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
import _areas  # noqa: E402  (resolve_review_skill: whether the phase review has a skill; resolve_skills: what a session starts with)
import _status_facts  # noqa: E402  (ready_tasks: the one readiness rule)
import _verdict_binding as _vb  # noqa: E402  (phase_binding: whether a held phase
#                                              gate run is still the one sign-off binds)
import _wave  # noqa: E402  (select: which ready tasks may run together)
import _doctor_setup  # noqa: E402  (hooks_task_binding: whether the loaded hooks bind a task tree)
import _runner_collects  # noqa: E402  (collects: whether a runner takes a test path)
import _gate_derive  # noqa: E402  (entry_collector: what collects a gate entry's tests)
import _tree_stamp  # noqa: E402  (parse_stamp, declared_scope: the scope a filing was made under)
import _clause_coverage as _cc  # noqa: E402  (check: whether the writer answered every clause)
import _scope_companions  # noqa: E402  (derive: the runner config a widen declares)
import _worktrees  # noqa: E402  (read_provenance: whether a kept tree's marker names its task)
import _scoped_commit  # noqa: E402  (plugin_owned_rels: the one table of what the plugin owns under .claude/)

E_OK, E_STOPPED, E_USAGE = 0, 1, 2
PREFIX = "[drive-phase]"
# The bound every print that is not a stop stays inside. A stop prints a verb's
# own words whole, so it is the one print that may run longer.
INSTRUCTION_BYTES = 300

EXECUTOR_AGENT = "audit:audit-executor"
REVIEWER_AGENT = "audit:audit-reviewer"

# THE WRITER AS A HEADLESS SESSION. With `executor.writerModel` set, a task's
# writer is not an Agent carrying the executor body: the main loop runs
# `run-agent-session.py --role writer` on the prompt `brief --role writer` wrote,
# and the session's own result prices it. Without the key the executor Agent is
# dispatched as before - the rollback path while the session path is new.
# The effort is one value for every writer, so two writers' costs compare like
# with like; routing it by task is not done here.
WRITER_RUNNER = "run-agent-session.py"
WRITER_EFFORT = "high"
WRITER_MODEL_KEY = "writerModel"
# How often a red task gate goes back to the session that wrote the task before
# the plain gate-red is asked, whose `retry` starts a fresh one.
MAX_RESUME_ROUNDS = 2
# THE PER-TASK REVIEWER AS A SESSION, under the same two keys: the runner is
# given the reviewer's agent body, and the drive files the reviewer's return
# itself from the session's last message - after reading the saved stream. A
# stream with no tool call is a review of nothing opened, and a session that
# could run `submit` itself would have made one call, so the check could not
# tell a read from a filing. Its dispatches are kept beside the writer's under
# a key of their own.
REVIEWER_KEY = "reviewerSession"
# How many times a reviewer that opened nothing is dispatched once more.
MAX_REVIEWER_REDISPATCH = 1
REVIEWER_SESSION_RULE = (
    "This session files nothing: do not run the brief's submit block. Open "
    "each changed function in the tree before you judge, then end your last "
    "message with the return object as one JSON object and nothing after it - "
    "the drive files it.")
# The one line the runner prints for a session that produced a result; anything
# else it prints (could-not-run, io-error, a usage refusal) carries no session.
_SESSION_LINE = re.compile(r"^session=(\S+) subtype=(\S+) is_error=(\S+) "
                           r"total_cost_usd=(\S+) exit=(\S+) stream=(.*)$")
# The most failing lines a resume prompt carries, and the width of each.
RESUME_LINES, RESUME_LINE_BYTES = 40, 300

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
WRITER_RULE = ("Run the run: line --explain prints in Bash, in the background, "
               "and call next after it exits.")
# The one statement of whose money a session spends. The run: line is a separate
# process with its own --budget-usd, which an orchestrator capped by its own
# --max-budget-usd compared with what it had left and stopped on. The text is
# printed under every session dispatch and quoted verbatim in the command docs
# that describe that dispatch; `sn4d` reads them against this constant.
SESSION_BUDGET_RULE = ("The session is its own process under its own --budget-usd, "
                       "set by executor.writerBudgetUsd; it is not drawn from this "
                       "session's budget, so launch the run: line as printed.")
STEPS = {
    "dispatch-writer": {
        "line": "dispatch run-agent-session.py --role writer --task %(task)s "
                "--model %(model)s prompt=%(prompt)s",
        "rule": (WRITER_RULE, SESSION_BUDGET_RULE)},
    "resume-writer": {
        "line": "dispatch run-agent-session.py --role writer --task %(task)s "
                "--model %(model)s --resume %(session)s prompt=%(prompt)s",
        "rule": (WRITER_RULE, SESSION_BUDGET_RULE)},
    "wait-writer": {
        "line": "wait %(task)s: the writer session has written no record at "
                "%(record)s yet",
        "rule": ("Started: wait for it to exit, then next. Not started: run the "
                 "run: line --explain prints, in the background.",)},
    "dispatch-reviewer-session": {
        "line": "dispatch run-agent-session.py --role reviewer --task %(task)s "
                "--model %(model)s prompt=%(prompt)s",
        "rule": (WRITER_RULE, SESSION_BUDGET_RULE)},
    "wait-reviewer-session": {
        "line": "wait %(task)s: the reviewer session has written no record at "
                "%(record)s yet",
        "rule": ("Started: wait for it to exit, then next. Not started: run the "
                 "run: line --explain prints, in the background.",)},
    "dispatch-validation": {
        "line": "dispatch run-agent-session.py --role reviewer --task %(phase)s "
                "--model %(model)s validates %(ids)s prompt=%(prompt)s",
        "rule": (WRITER_RULE, SESSION_BUDGET_RULE)},
    "wait-validation": {
        "line": "wait %(task)s: the validation session has written no record at "
                "%(record)s yet",
        "rule": ("Started: wait for it to exit, then next. Not started: run the "
                 "run: line --explain prints, in the background.",)},
    "decide-gate-red-writer": {
        "line": "decide gate-red-writer %(task)s: recorded gate red (%(why)s)%(run)s",
        "rule": ("recommended: resume - the session that wrote it gets the "
                 "failing lines and no attempt is spent; retry spends one.",)},
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
        "line": "decide gate-red %(task)s: recorded gate red (%(why)s)%(run)s",
        "rule": ("rerun spends no attempt (GATE COULD NOT RUN); retry spends "
                 "one; past maxAttempts, block and tell the human.",)},
    "decide-writer-committed": {
        "line": "decide writer-committed %(task)s: the writer session committed "
                "the task's files (%(why)s); nothing was filed",
        "rule": ("The drive commits a writer's work: a human takes the commit "
                 "out of history, keeping its changes, then recheck files them; "
                 "block keeps the task.",)},
    "decide-head-moved": {
        "line": "decide head-moved %(task)s: HEAD moved past the dispatch "
                "(%(why)s) by commits touching none of its files; nothing was "
                "filed",
        "rule": ("file proves and files the work against the new HEAD; block "
                 "keeps the task.",)},
    "decide-head-unknown": {
        "line": "decide head-unknown %(task)s: git named no HEAD to check the "
                "session's commits against (%(why)s); nothing was filed",
        "rule": ("file reads HEAD again and, when git names it, proves and "
                 "files the work; block keeps the task.",)},
    "decide-red-refused-writer": {
        "line": "decide red-refused-writer %(task)s: the red-first proof of the "
                "writer's work did not hold (%(why)s); nothing was filed",
        "rule": ("recommended: resume - the helper's words go to the session that "
                 "wrote it and no attempt is spent; block keeps the task.",)},
    "decide-clauses-uncovered-writer": {
        "line": "decide clauses-uncovered-writer %(task)s: the writer's last "
                "message leaves acceptance clauses unanswered (%(why)s); "
                "nothing was filed",
        "rule": ("recommended: resume - the uncovered clauses go to the session "
                 "that wrote it and no attempt is spent; block keeps the task.",)},
    "decide-clauses-uncovered": {
        "line": "decide clauses-uncovered %(task)s: the writer's last message "
                "leaves acceptance clauses unanswered (%(why)s); nothing was "
                "filed",
        "rule": ("retry starts a fresh session and spends an attempt; block keeps "
                 "the task.",)},
    "decide-red-refused": {
        "line": "decide red-refused %(task)s: the red-first proof of the writer's "
                "work did not hold (%(why)s); nothing was filed",
        "rule": ("retry starts a fresh session and spends an attempt; block keeps "
                 "the task.",)},
    "decide-tests-moved": {
        "line": "decide tests-moved %(task)s: test files changed after the filed "
                "proof: %(why)s; the commit is refused",
        "rule": ("The filing and its review cover other bytes: retry starts the "
                 "task again and spends an attempt; block keeps the task.",)},
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

# The decisions whose `resume` goes to the recorded writer session, each with
# the kind of round it spends; every kind spends the one `MAX_RESUME_ROUNDS`.
RESUME_KINDS = {"gate-red-writer": "red gate",
                "red-refused-writer": "red-first proof",
                "clauses-uncovered-writer": "clause coverage"}

# Each decision's options, and the ones that need `--reason`. A decision with no
# options is one only the plan can change; nothing here answers it.
DECISIONS = {
    "gate-red": (("retry", "rerun", "block"), ("block",)),
    # A red gate on a task whose writer session is recorded, with a resume
    # round left: `resume` sends the failing lines to that session.
    "gate-red-writer": (("resume", "retry", "rerun", "block"), ("block",)),
    "no-executor-return": (("resume", "retry", "block"), ("block",)),
    # A writer session that committed the task's files past its dispatch:
    # nothing is filed until a human takes the commit out (`recheck`).
    "writer-committed": (("recheck", "block"), ("block",)),
    # HEAD moved past the dispatch by commits that are not the session's:
    # `file` proves and files the work against the new HEAD.
    "head-moved": (("file", "block"), ("block",)),
    # git named no HEAD before or after the session: the commit check could not
    # be made, so nothing is filed until `file` reads HEAD again.
    "head-unknown": (("file", "block"), ("block",)),
    # The red-first proof of a writer's work did not hold: back to its session.
    "red-refused-writer": (("resume", "block"), ("block",)),
    "red-refused": (("retry", "block"), ("block",)),
    # A green gate over a writer's work whose last message leaves a clause
    # unanswered: back to the session while a round is left, else a fresh retry.
    "clauses-uncovered-writer": (("resume", "block"), ("block",)),
    "clauses-uncovered": (("retry", "block"), ("block",)),
    # A test file changed after the filed proof the commit is bound to.
    "tests-moved": (("retry", "block"), ("block",)),
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
    "resume-executor": "dispatch", "dispatch-writer": "dispatch",
    "resume-writer": "dispatch", "decide-gate-red-writer": "judge",
    "wait-writer": "wait", "decide-writer-committed": "ask",
    "dispatch-reviewer-session": "dispatch", "wait-reviewer-session": "wait",
    "dispatch-validation": "dispatch", "wait-validation": "wait",
    "decide-head-moved": "judge", "decide-head-unknown": "judge",
    "decide-red-refused-writer": "judge",
    "decide-red-refused": "judge", "decide-tests-moved": "judge",
    "decide-clauses-uncovered-writer": "judge", "decide-clauses-uncovered": "judge",
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
# A PHASE-REVIEW FINDING UNDER A WRITER SESSION BLOCKS ONLY ONCE IT IS VALIDATED.
# A second reviewer session re-reads the code each finding cites and answers
# `confirmed` or `withdrawn`, with the finding's kind; only a confirmed finding
# of a blocking kind goes back to a writer, and every other finding is a note.
# The verdicts are held per finding with the HEAD they were given at, and read
# only while HEAD is still that commit: a fix round moves the code they judged.
VALIDATE_KEY = "validationSession"
VERDICTS_FIELD = "findingVerdicts"
# The tools whose `tool_use` reads a file: a pass's withdrawal of a finding is
# taken only when its stream holds one of these over a path the finding cites.
READ_TOOLS = ("Read", "NotebookRead", "Grep")
FINDING_VERDICTS = ("confirmed", "withdrawn")
BLOCKING_KINDS = ("correctness", "requirement")
FINDING_KINDS = BLOCKING_KINDS + ("other",)
# The notes the last sort made, beside the HEAD it was made at: what the triage
# leaves out of its offered findings and sign-off records as each one's reason.
NOTED_FIELD = "findingNotes"
# A confirmed finding's way back: each task whose own diff holds the cited
# lines is re-opened, and its entry here holds the findings, the commit it
# carried and its last writer session's id, stream and tree, read before the
# re-open. What must outlive a lost state file - the commit it carried and the
# findings handed to it - is in the re-open's journal row (`reopen_record`),
# whose reason is `REOPEN_REASON`.
REVIEW_FIX_FIELD = "reviewFixes"
# The marks of a task its close under a task-scoped drive keeps (`finish_task`).
KEPT_AT_TASK_CLOSE = (REVIEW_FIX_FIELD, "writer")
REOPEN_REASON = ("the phase review's finding(s) %s, confirmed by the validation "
                 "pass at %s, go back to this task's writer")
_REOPEN_IDS = re.compile(r"^the phase review's finding\(s\) ([^\s,]+(?:,[^\s,]+)*),"
                         r" confirmed by the validation pass")
# The HEAD the cap's note was made at, so a repeated stop notes nothing again.
CAP_NOTED_FIELD = "reviewCapNoted"
# How long a writer session's prompt cache lives: a session last active longer
# ago than this is resumed at a full re-read, so a fresh one is started instead.
CACHE_LIFE_SECONDS = 3600
# What a triage returns when a confirmed finding re-opened a task: the drive
# goes on to that task's writer in the same step.
HANDED_BACK = object()
VALIDATE_HEAD = ("The phase review of %(phase)s at head %(head)s raised the "
                 "findings below. Re-read the code each one cites as it stands "
                 "in this tree. Confirm a finding only when that code really has "
                 "the defect and this phase's work wrote it; withdraw it "
                 "otherwise - code no task of the phase changed is pre-existing, "
                 "and a defect a fix has since removed is gone.")
VALIDATE_RULE = (
    "kind: correctness (the code does the wrong thing), requirement (it does not "
    "do what its task or the phase asked) or other (style, naming, a missing "
    "case). Open each file a finding cites with the Read tool before you answer "
    "withdrawn or other for it: the drive takes such an answer only when your "
    "session holds a Read of a file that finding cites, and a withdrawal "
    "without one is not accepted. This session files nothing: run no submit "
    "block. End your last "
    "message with one JSON object and nothing after it: {\"findings\": "
    "[{\"id\": \"<id>\", \"verdict\": \"confirmed|withdrawn\", \"kind\": "
    "\"correctness|requirement|other\", \"basis\": \"<file:line read and what "
    "it shows>\"}]}")
REVIEW_FIX_HEAD = ("The phase review raised these findings on the code your task "
                   "wrote, and a second reviewer pass re-read the cited lines and "
                   "confirmed each:")
# A hunk header of a task's own diff: its old side, then its new side.
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
# A cited line in a finding's `file`: `path:291-294,308` (the shape the
# reviewer is asked for), `path:L5`, `path#L5-L7`, `path line 5`, `path (lines
# 5-6)`.
_CITED = re.compile(
    r"([^\s,;:#()]+)(?::|#|,?\s+\(?lines?\s+)"
    r"(L?\d+(?:\s*[-–]\s*L?\d+)?(?:\s*,\s*L?\d+(?:\s*[-–]\s*L?\d+)?)*)")
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
# The index a phase brief past the reader budget is written as, one line per
# slice: `slice <n>/<total>: <path>`, the line `audit-lookup.py` writes.
_BRIEF_SLICE = re.compile(r"^slice (\d+)/(\d+): (.+?)\s*$", re.M)
_SLICE_SPEC = re.compile(r"^(\d+)/(\d+)$")
# The rule under the dispatch of a sliced phase review: every slice goes out in
# one message, and the return of the last one files the review.
SLICE_RULE = ("dispatch the slices together in one message; each files its own "
              "slice, the last files the review; then next")
# The finding and preExisting lists of a sliced review are numbered afresh, and
# the intent of the slice that answered worst stands for the phase.
INTENT_WORST_FIRST = ("diverges", "cannot-tell", "matches")
# The run id a gate's output names. A green run's terse line joins its records
# with "; " (`run-test-gate.success_line`), so the id ends at a ";" as well as
# at a space - read whole, it named no run in the ledger.
_RUN_ID = re.compile(r"evidence: recorded ([^\s;]+)")
# The most a gate-red decision says about the task's base, in bytes: the task
# to run first leads, so a clip keeps the suggestion and cuts the suite list.
BASE_CLAUSE_BYTES = 100
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


def _verb_with_text(ctx, script, args, flag, text):
    """`_verb_or_stop` for a verb whose prose flag `flag` carries `text` the
    drive built: the flag goes as `flag -` and the text on stdin, so no shell
    and no argv stands between the drive and the manifest.

    A verb reads the marks a shell leaves (a run of spaces, whitespace before
    punctuation) off every prose value that arrives on argv and refuses it - the
    right test for a line a person typed, and wrong for text assembled here,
    which holds a doubled space whenever a piece it was built from did. The
    stdin route is the one that arrives verbatim. Stdin carries ONE flag per
    call. An EMPTY text goes on argv as it is: a verb reads an empty value as
    none, which is legal. A text of whitespace alone is neither: on stdin the
    verb refuses it as holding no text, and on argv spaces or tabs are the
    leading-whitespace mark it refuses, so it is refused here with a sentence
    naming the flag, and nothing is run."""
    if not text:
        return _verb_or_stop(ctx, script, list(args) + [flag, text or ""])
    if not text.strip():
        return None, _stopped(ctx, "%s was built as %r, whitespace alone, which "
                              "holds no text for %s to write; nothing was run"
                              % (flag, text, script))
    return _verb_or_stop(ctx, script, list(args) + [flag, "-"], stdin=text)


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


def next_task(manifest, phase, red_at_base=None):
    """`(task, how)`: the task the drive is on - the first in progress in id
    order - else the first ready one, which the drive starts, a task fixing a
    suite in `red_at_base` ahead of the rest (`_wave.base_red_first`). One at
    a time: a recorded gate must not run while another executor edits the
    tree."""
    tasks = _tasks(phase)
    running = [t for t in tasks if t.get("status") == "in_progress"]
    if running:
        return running[0], "running"
    ready = set(_status_facts.ready_tasks(manifest))
    waiting = _wave.base_red_first([t for t in tasks if t["id"] in ready],
                                   red_at_base)
    return (waiting[0], "ready") if waiting else (None, None)


def gate_step_names(manifest, phase, task_ids):
    """The gate entries that measure the tasks in `task_ids` (`_mio.gate_entries`,
    each under its own phase), each once in first-seen order - or `phase`'s own
    gate when none of them is in the plan. These are the step names a run of
    those gates records."""
    names, found = [], False
    for each in manifest.get("phases") or []:
        if not isinstance(each, dict):
            continue
        for task in each.get("tasks") or []:
            if isinstance(task, dict) and task.get("id") in task_ids:
                found = True
                names += [e for e in _mio.gate_entries(each, task)[0]
                          if e not in names]
    return names if found else list(_mio.gate_entries(phase)[0])


def red_at_base(ctx, task_ids=(), names=None):
    """`(suites, run_id)` - the suites the newest run that tested HEAD itself
    names as failing, which every task started from HEAD inherits.

    The run is `_evidence_io.base_run`'s: on a clean tree at HEAD, so a task
    gate red on its own uncommitted work never reorders anybody, and by no
    task in `task_ids` - the ones being ordered, none of which may vouch for
    itself. `([], None)` when no such run is recorded or the ledger cannot be
    read, so nothing is reordered on a reading nobody took.

    `names` (`gate_step_names`) are the steps of the gates in question: a run
    of none of them is passed over, and only those steps' suites are read -
    the filter `run-test-gate.base_red` applies to the same question, so a
    newer clean run of another gate cannot answer for this one."""
    head = git_head(ctx)
    if not head:
        return [], None
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception:                                          # noqa: BLE001
        return [], None
    base = _evio.base_run(rows, head, task_ids, names)
    if base is None:
        return [], None
    steps = [st for st in base.get("steps") or [] if names is None
             or isinstance(st, dict) and st.get("name") in names]
    return _evio.named_failing_suites(steps), base.get("runId")


def base_red_why(ctx, text, manifest, phase, task):
    """The clause a gate-red decision adds about the task's base, off the row
    the gate run says it recorded: the base run and what it charges to the
    base, and the ready task that fixes a suite red there, to run first. ""
    when the row carries no base reading. Clipped, because the decision is
    printed whole into the main loop; the gate's own output and the row hold
    the reading unclipped."""
    found = _RUN_ID.search(text or "")
    if not found:
        return ""
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception:                                          # noqa: BLE001
        return ""
    reading = (_evio.row_by_run(rows, found.group(1)) or {}).get(_evio.BASE_RED_KEY)
    if not isinstance(reading, dict):
        return ""
    if not reading.get("run"):
        if reading.get("verdict") == "unreadable":
            return "; could not read the ledger"
        # A reading that carries a `head` key holding nothing is a run git
        # named no HEAD for; a row from before the key has no answer either way.
        if "head" in reading and not reading["head"]:
            return "; git named no HEAD for that run"
        return "; no base run recorded"
    clause = ""
    if reading.get("atBase"):
        clause = "; red at base too: %s - run %s" % (
            ", ".join(reading["atBase"]), reading["run"])
    if reading.get("introduced"):
        clause += "; red the task introduced: %s" % (
            ", ".join(reading["introduced"]),)
    ready = set(_status_facts.ready_tasks(manifest))
    fixers = [t["id"] for t in _tasks(phase) if t["id"] in ready
              and t["id"] != task["id"]
              and _wave.fixes_red_at_base(t, reading.get("atBase"))]
    if fixers:
        clause = "; run %s first%s" % (", ".join(fixers), clause)
    return _clip(clause, BASE_CLAUSE_BYTES)


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


def signal_of(step, subject, basis, nxt, prompts=(), subjects=(), runs=()):
    """The fields of one signal line: the step (its verb is `SIGNAL_VERBS`'),
    what it is about, the basis, the one command to run next, the prompts a
    dispatch sends, the commands it runs instead (a writer session's) and every
    other id `--explain` answers for it."""
    return {"step": step, "subject": subject, "basis": basis, "next": nxt,
            "prompts": list(prompts), "subjects": list(subjects),
            "runs": list(runs)}


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


def dispatch_prompt(ctx, role, node_id, part=None):
    """The prompt an agent is dispatched with: `DISPATCH_PROMPT`, then the id -
    and, for one slice of a phase brief cut at the reader budget, its number."""
    return DISPATCH_PROMPT % {"script": _loader.script_path("drive-phase.py"),
                              "manifest": os.path.abspath(ctx["manifest"]),
                              "project": os.path.abspath(ctx["project"]),
                              "role": role} + node_id + (
        "" if part is None else " --slice %d" % (part,))


def dispatch_said(ctx, role, node_id, agent, model, brief):
    """The dispatch of `role` for `node_id` - a task's executor or reviewer, or
    the phase reviewer for `phase` - with the brief it was written. For the
    phase reviewer `brief` may be the list of a sliced brief's paths: one
    reviewer is dispatched for each, in one print."""
    if role == "phase" and isinstance(brief, list):
        step = "dispatch-phase-review"
        total = len(brief)
        lines = [step_text(step, agent=agent, phase="%s slice %d/%d" % (
            node_id, n, total), model=model, brief=path)[0]
            for n, path in enumerate(brief, 1)]
        lines += [ADVANCE_LINE % {"phase": ctx["phase"]}, SLICE_RULE]
        basis = ("%s model=%s, %d slices; once the last files: --answer "
                 "sign-off --reason <the summary>" % (agent, model, total))
        return instruction("dispatch", lines, signal_of(
            step, node_id, basis, "Agent per slice: brief --role phase %s "
            "--slice <n>" % (node_id,), prompts=[
                dispatch_prompt(ctx, role, node_id, n)
                for n in range(1, total + 1)]))
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


def writer_said(ctx, task_id, model, prompt, argv, resume=None, round_n=0,
                role="writer"):
    """The dispatch of a writer session for `task_id`: the line naming the
    runner, the role, the task and the full model id, and the command itself,
    whole, as the `run:` line `--explain` prints - too long for any line the
    bound allows. `resume` is the recorded session a red gate goes back to, in
    round `round_n` - round 0 is a phase review's confirmed findings going
    back to it, which spends no round. `role` `reviewer` is the per-task
    reviewer's session, which is never resumed."""
    step = ("dispatch-reviewer-session" if role == "reviewer"
            else "resume-writer" if resume else "dispatch-writer")
    lines = step_text(step, task=task_id, model=model, prompt=prompt,
                      session=resume or "")
    basis = "%s --role %s model=%s%s" % (
        WRITER_RUNNER, role, model, "" if not resume
        else " --resume %s round %d/%d" % (resume[:8], round_n, MAX_RESUME_ROUNDS)
        if round_n else " --resume %s for the phase review's findings" % (resume[:8],))
    command = " ".join(shlex.quote(word) for word in argv)
    return instruction("dispatch", lines, signal_of(
        step, task_id, basis, command, runs=[command]))


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
                  subjects=ids,
                  runs=[r for m in members for r in m["signal"].get("runs") or []]))


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
                      phase=ctx["phase"], why=pending.get("why") or "",
                      run=verdict_said(pending))
    if options:
        lines.append(ANSWER_LINE % {
            "phase": ctx["phase"], "options": "|".join(options),
            "reason": (" (%s needs --reason)" % ("/".join(needs),)) if needs else ""})
    subject = pending.get("task") or ctx["phase"]
    return instruction("decide", lines, signal_of(
        "decide-%s" % (name,), subject, "%s: %s" % (name, pending.get("why") or ""),
        answer_command(ctx, options, needs) if options
        else explain_command(ctx, subject)))


# Words that make a gate entry a test run, for the entries `entry_collector` cannot
# classify. A tuple matches as a contiguous run of words' basenames; a bare word
# matches a command's basename (`./node_modules/.bin/mocha`). Everything else in a
# gate - validate, lint, report, screenshots - runs no suite and cannot be the one
# that collects a path no known runner takes.
#
# The browser runner is one of them, and more: it takes the languages vitest
# takes, and its config (`testDir`, `testMatch`) is not read here, so a spec
# vitest leaves out may be its. Only its `test` subcommand runs tests -
# `playwright install` does not.
PLAYWRIGHT_TOKEN = ("playwright", "test")
TEST_RUNNER_TOKENS = (("-m", "unittest"), ("-m", "pytest"), ("node", "--test"),
                      PLAYWRIGHT_TOKEN,
                      "mocha", "tap", "ava", "jasmine", "karma")


def _bases(command):
    """`(words, basenames)` of a gate entry, quotes stripped."""
    words = [w.strip("\"'") for w in str(command or "").split()]
    return words, [w.rsplit("/", 1)[-1] for w in words]


def _carries(base, token):
    """Whether the basenames `base` hold `token`: a tuple as a contiguous run,
    a bare word anywhere."""
    if isinstance(token, tuple):
        return any(tuple(base[i:i + len(token)]) == token
                   for i in range(len(base)))
    return token in base


def can_run_tests(command):
    """Whether an unclassified gate entry could run tests: it carries a known
    test-runner token, or names a suite FILE (a word whose last segment has an
    extension and reads as a suite - a directory such as `tests`
    handed to a linter is not one)."""
    words, base = _bases(command)
    if any(_carries(base, token) for token in TEST_RUNNER_TOKENS):
        return True
    return any("." in b and _phases.is_suite_path(w) for w, b in zip(words, base))


def runs_playwright(command):
    """Whether a gate entry runs the browser runner's tests."""
    return _carries(_bases(command)[1], PLAYWRIGHT_TOKEN)


def _playwright_language(path):
    """Whether `path` is in a language the browser runner reads - the one
    vitest and jest read (`_runner_collects.JS_EXTENSIONS`)."""
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return "." in name and name.rpartition(".")[2] in _runner_collects.JS_EXTENSIONS


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
    unclassified = []
    for entry in entries:
        runner = _gate_derive.entry_collector(build.get(entry, entry))
        if runner is None:
            if can_run_tests(build.get(entry, entry)):
                unclassified.append(entry)
        elif runner not in runners:
            runners.append(runner)
    for path in paths:
        if not runners:
            continue
        takers = _runner_collects.runners_taking(path, runners)
        if not takers and unclassified:
            # The runners this reading knows are not the gate's whole set: an
            # entry it cannot classify (`node --test`, `python3 -m unittest`) may
            # be the one that runs this suite, so "no runner takes it" is not
            # known - say so once and let the start go on.
            ctx["did"].append("could not tell whether the gate runs %s: no known "
                              "runner (%s) takes it and the entry %s is not one "
                              "this reading classifies" % (
                                  path, ", ".join(runners), _clip(unclassified[0], 60)))
            continue
        if not takers:
            # The gate names runners and none of them reads this path's language.
            return E_OK, decision(
                ctx, state, "scope-gap", task,
                "no runner in this gate takes %s (the gate runs %s); no runner "
                "config file exists to widen" % (path, ", ".join(runners)),
                extra={"config": None})
        answers = [(r, _runner_collects.collects(path, r, ctx["project"]))
                   for r in takers]
        if any(a["answer"] == _runner_collects.COLLECTED for _r, a in answers):
            continue
        if any(a["answer"] == _runner_collects.COULD_NOT_TELL for _r, a in answers):
            ctx["did"].append("could not tell whether %s collects %s: %s" % (
                answers[0][0], path, _clip(answers[0][1]["basis"], 100)))
            continue
        runner, got = answers[0]
        browser = [e for e in unclassified if runs_playwright(build.get(e, e))]
        if browser and _playwright_language(path):
            # A definite no from the runners this reading knows, beside a
            # browser runner whose config it does not read: the spec may be
            # that runner's, so the gate's answer is not known.
            ctx["did"].append("could not tell whether the gate runs %s: %s does "
                              "not collect it, and the entry %s runs playwright, "
                              "whose config this reading does not read" % (
                                  path, runner, _clip(browser[0], 60)))
            continue
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


def dispatch(ctx, state, phase, task, role, tree=None):
    """Write `role`'s brief through `audit-lookup.py` and hand back the dispatch:
    for the executor under `executor.writerModel`, the writer session's, run in
    `tree` when the task has one of its own."""
    session, problem = writer_setting(ctx["config"]) if role in (
        "executor", "reviewer") else (None, None)
    if problem:
        return _stopped(ctx, problem)
    writer = session if role == "executor" else None
    out, stop = _verb_or_stop(ctx, "audit-lookup.py", [
        ctx["manifest"], "brief", task["id"], "--role",
        "writer" if writer else role, "--project", ctx["project"]])
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
    brief = project_relative(ctx, found.group(1).strip())
    fix, spent, why_fix = (standing_review_fix(ctx, state, task) if writer
                           else (None, None, None))
    if why_fix is not None:
        return _stopped(ctx, "%s, so whether %s's writer takes a phase review's "
                        "findings is not known" % (why_fix, task["id"]))
    if spent:
        ctx["did"].append(_clip(spent, 160))
    if fix is not None:
        return review_fix_dispatch(ctx, state, phase, task, writer, os.path.abspath(
            os.path.join(ctx["project"], found.group(1).strip())), fix, tree)
    if writer:
        prompt = os.path.abspath(os.path.join(ctx["project"], found.group(1).strip()))
        _record, argv = open_dispatch(ctx, state, task, 0, lambda record: writer_argv(
            ctx, task, writer, prompt, record, tree), tree)
        return writer_said(ctx, task["id"], writer["model"], brief, argv)
    if session:
        return reviewer_dispatch(ctx, state, phase, task, session, brief, tree)
    model = (task.get("model") if role == "executor"
             else (phase.get("review") or {}).get("model")) or "unset"
    agent = EXECUTOR_AGENT if role == "executor" else REVIEWER_AGENT
    return dispatch_said(ctx, role, task["id"], agent, model, brief)


# --- the writer's session ----------------------------------------------------------
def writer_setting(config):
    """`(setting, problem)` - `_config_rules.writer_session_setting`, the one
    reading of `executor.writerModel` and `executor.writerBudgetUsd`."""
    return _config_rules.writer_session_setting(config)


def sessions_dir(ctx):
    """Where the runner keeps each session's stream, under `stateDir`."""
    return os.path.join(ctx["stateDir"], "sessions")


def session_record(ctx, task, seq, role="writer"):
    """The file the runner appends its outcome to for dispatch `seq` of `task`'s
    current start - one per dispatch, so a brief issued again or a resume never
    shares a file with the dispatch before it. A reviewer's carries its role,
    so it never shares one with a writer's of the same sequence."""
    return os.path.join(sessions_dir(ctx), "drive", "%s.%s.%s%d.jsonl" % (
        re.sub(r"[^A-Za-z0-9._-]", "_", task["id"]), start_key(task),
        "" if role == "writer" else role + ".", seq))


def session_skills(ctx, task):
    """The skills `task`'s session starts with: `_areas.resolve_skills` over the
    plan as it stands now - the one resolver, so the writer, the reviewer and the
    executor subagent are given the same names."""
    manifest, phase = load_phase(ctx)
    return _areas.resolve_skills(manifest, phase, task)


def writer_argv(ctx, task, writer, prompt, record, tree=None, resume=None,
                role="writer"):
    """The command that runs `task`'s writer session - or its reviewer's, under
    `role` - in the task's own tree when it has one, else the project; its
    scratch and its stream under `stateDir`, and one `--skill` per skill the task
    resolves to, which the runner puts in the session's system prompt."""
    skills = [flag for name in session_skills(ctx, task) for flag in ("--skill", name)]
    argv = ["python3", _loader.script_path(WRITER_RUNNER), "--role", role,
            "--task", task["id"],
            "--tree", member_project(ctx, tree) or ctx["project"],
            "--scratch", os.path.join(sessions_dir(ctx), "scratch", task["id"]),
            "--state-dir", ctx["stateDir"], "--model", writer["model"],
            "--effort", WRITER_EFFORT, "--budget-usd", writer["budget"],
            "--prompt-file", prompt, "--record", record] + skills
    return argv + (["--resume", resume] if resume else [])


def reviewer_session_setting(phase, session):
    """The writer session's setting with the reviewer's model: the phase's
    `review.model` when it is a full id, which the runner insists on, else the
    writer's model - an alias such as `sonnet` names whatever is newest that
    day, and a reviewer priced against a different model than the one the plan
    names is still one whose cost is its own session's."""
    model = (phase.get("review") or {}).get("model")
    return dict(session, model=model if _config_rules.is_full_model_id(model)
                else session["model"])


def reviewer_dispatch(ctx, state, phase, task, session, brief, tree=None):
    """The dispatch of `task`'s per-task reviewer as a session: its prompt is
    the Agent dispatch's own words, then `REVIEWER_SESSION_RULE`, written to
    the task's scratch; the command names the reviewer role."""
    setting = reviewer_session_setting(phase, session)
    seq = writer_state(state, task, REVIEWER_KEY)["seq"]
    prompt = os.path.join(sessions_dir(ctx), "scratch", task["id"],
                          "reviewer-%s.%d.prompt" % (start_key(task), seq))
    os.makedirs(os.path.dirname(prompt), exist_ok=True)
    with open(prompt, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s\n\n%s\n" % (dispatch_prompt(ctx, "reviewer", task["id"]),
                                   REVIEWER_SESSION_RULE))
    _record, argv = open_dispatch(
        ctx, state, task, 0, lambda record: writer_argv(
            ctx, task, setting, prompt, record, tree, role="reviewer"),
        tree, REVIEWER_KEY)
    return writer_said(ctx, task["id"], setting["model"], brief, argv,
                       role="reviewer")


def writer_state(state, task, key="writer"):
    """The writer-session record for `task`'s current start: every dispatch
    (its sequence number, resume round, record file, command and HEAD), the
    lines of each record already noted, the runs read back, the resume rounds
    spent, whether the cap's note was asked for, the last dispatch settled
    after its session, the proof held for the green gate, the test digest it
    locked and each re-proof over changed test files."""
    held = _marked(state, key, task)
    base = {"seq": 0, "dispatches": [], "noted": {}, "runs": [], "resumes": 0,
            "capNoted": False, "settled": None, "lock": None, "reproofs": [],
            "proof": None}
    return dict(base, **(held if isinstance(held, dict) else {}))


def open_dispatch(ctx, state, task, round_n, build, tree=None, key="writer",
                  kind=None):
    """Allocate the next dispatch of `task`'s writer: its record file, and the
    command `build(record)` makes for it, kept so a wait can print it again,
    beside the commit HEAD names in the tree it runs in - what a session that
    commits is told apart by - and, for a resume round, the `kind` of round it
    is (`RESUME_KINDS`). Returns `(record, argv)`."""
    held = writer_state(state, task, key)
    seq = held["seq"]
    record = session_record(ctx, task, seq, "writer" if key == "writer" else "reviewer")
    argv = build(record)
    held["seq"] = seq + 1
    entry = {"seq": seq, "round": round_n, "record": record, "argv": argv,
             "head": tree_head(ctx, tree)}
    if kind:
        entry["kind"] = kind
    held["dispatches"] = list(held["dispatches"]) + [entry]
    _mark(state, key, task, held)
    write_state(ctx, state)
    return record, argv


def read_sessions(path):
    """Each outcome the runner appended to one record, in order, as `{"session",
    "cost", "stream", "line", "exit"}` - `session` and `cost` None for an
    outcome that carries no session. Reading stops at a line that does not
    parse: the runner may be part-way through writing it. `[]` when there is no
    record yet (the run has not happened, or is running)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    runs = []
    for text in raw.split("\n"):
        if not text.strip():
            continue
        try:
            body = json.loads(text)
        except ValueError:
            break
        if not isinstance(body, dict):
            break
        line = str(body.get("line") or "")
        hit = _SESSION_LINE.match(line)
        runs.append({"session": hit.group(1) if hit else None,
                     "cost": hit.group(4) if hit else None,
                     "stream": hit.group(6).strip() if hit else None,
                     "line": line, "exit": body.get("exit")})
    return runs


def session_note(round_n, run, who="writer"):
    """The note one session leaves on its task: the cost its own result printed,
    or - for a run that produced no result - the runner's words, with no cost.
    `note_task` scrubs any path it still holds."""
    if run["session"]:
        return ("%s session %s round %d: total_cost_usd=%s (from its own "
                "result; stream %s, runner exit %s)" % (
                    who, run["session"], round_n, run["cost"],
                    os.path.basename(run["stream"]), run["exit"]))
    return ("%s session round %d produced no result, so no cost is recorded: "
            "%s (runner exit %s)" % (who, round_n, _clip(run["line"], 200),
                                     run["exit"]))


def note_task(ctx, task, text):
    """Note `text` on `task` through the verb, every path in it spelled the way
    a committed row may say it (`redacted_free_text`: project-relative inside
    the project, a token outside it), since the verb refuses a machine path.
    None, or the verb's refusal - which the caller records and goes past: a
    note is a record of a session, and no step waits on it."""
    clean = _journal_io.redacted_free_text(ctx["project"], text)
    code, out, err = run_verb(ctx, "audit-task.py", _task_args(
        ctx, "note", task["id"]) + ["--text", "-"], stdin=clean)
    if code == 0:
        return None
    return _clip(" ".join((out + err).split()) or "exit %d" % (code,), 160)


def note_sessions(ctx, state, task, key="writer"):
    """Note each outcome the task's writer records - or its reviewer's, under
    `key` - hold that the last step had not seen - once, whether the verb took
    the note or refused it."""
    who = "writer" if key == "writer" else "reviewer"
    held = writer_state(state, task, key)
    for each in held["dispatches"]:
        seen = int(held["noted"].get(str(each["seq"])) or 0)
        runs = read_sessions(each["record"])
        for run in runs[seen:]:
            refused = note_task(ctx, task, session_note(each["round"], run, who))
            held["runs"] = list(held["runs"]) + [dict(run, round=each["round"],
                                                      seq=each["seq"])]
            held["noted"] = dict(held["noted"], **{str(each["seq"]): seen + 1})
            seen += 1
            _mark(state, key, task, held)
            write_state(ctx, state)
            label = (run["session"] or "with no result")[:13]
            ctx["did"].append("%s session %s round %d %s" % (
                who, label, each["round"], "noted" if refused is None
                else "not noted (%s)" % (refused,)))


def writer_wait(ctx, state, task):
    """The wait printed while the latest writer dispatch has written no record:
    the session is running, or has not been started. Its command is printed
    again, since only the main loop knows which of the two it is. None once a
    record holds an outcome, or when no writer was dispatched."""
    held = writer_state(state, task)
    if not held["dispatches"]:
        return None
    last = held["dispatches"][-1]
    if read_sessions(last["record"]):
        return None
    return wait_said(ctx, task["id"], project_relative(ctx, last["record"]),
                     last.get("argv") or [])


def wait_said(ctx, task_id, record, argv, step="wait-writer"):
    """The wait on a writer session - or the reviewer's, under `step` - that
    has written no record at `record`, with its command printed again as the
    `run:` line."""
    command = " ".join(shlex.quote(word) for word in argv)
    return instruction("wait", step_text(step, task=task_id,
                                         record=record), signal_of(
        step, task_id, "no record at %s yet" % (record,),
        "wait for the session to exit, then next %s --signal" % (
            drive_target(ctx),), runs=[command] if command else []))


# --- the reviewer's session ----------------------------------------------------------
def stream_tool_calls(stream):
    """`(count, None)` - the `tool_use` blocks the assistant events of a saved
    stream hold - or `(None, why)` when the stream cannot be read or holds no
    assistant message to count in: a stream nobody can count in is not a stream
    with none, and reads as neither a read nor an unread."""
    try:
        with open(stream, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, TypeError) as exc:
        return None, "its stream could not be read (%s)" % (exc.__class__.__name__,)
    calls, seen = 0, False
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if event.get("type") != "assistant" or not isinstance(content, list):
            continue
        seen = True
        calls += len([b for b in content
                      if isinstance(b, dict) and b.get("type") == "tool_use"])
    if not seen:
        return None, "its stream holds no assistant message to count calls in"
    return calls, None


def return_object(text):
    """The JSON object a session's last message ends with, or None: the whole
    text when it parses, else what lies between its first `{` and last `}` -
    the fence or the sentence around it is the model's, not part of the return."""
    if not isinstance(text, str):
        return None
    for candidate in (text.strip(), text[text.find("{"):text.rfind("}") + 1]):
        try:
            body = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(body, dict):
            return body
    return None


def reviewer_unread(ctx, state, phase, task, run, seq, tree=None):
    """What a reviewer session whose stream holds no tool call leads to: a
    note on the task that its review is cannot-tell (once per session), then
    the reviewer dispatched once more - and, when that one also opened
    nothing, a stop that names both sessions and dispatches no third."""
    held = writer_state(state, task, REVIEWER_KEY)
    if seq not in held.get("unread", []):
        refused = note_task(ctx, task, (
            "reviewer session %s opened no file - its saved stream %s holds no "
            "tool call - so its review is recorded as cannot-tell and filed "
            "nothing" % (run["session"], os.path.basename(run["stream"]))))
        held["unread"] = list(held.get("unread", [])) + [seq]
        held["unreadSessions"] = list(held.get("unreadSessions", [])) \
            + [run["session"]]
        _mark(state, REVIEWER_KEY, task, held)
        write_state(ctx, state)
        ctx["did"].append("reviewer session %s opened no file: cannot-tell%s" % (
            run["session"][:8], "" if refused is None
            else " (not noted: %s)" % (refused,)))
    if held.get("redispatched", 0) < MAX_REVIEWER_REDISPATCH:
        held["redispatched"] = held.get("redispatched", 0) + 1
        _mark(state, REVIEWER_KEY, task, held)
        write_state(ctx, state)
        return dispatch(ctx, state, phase, task, "reviewer", tree)
    return _stopped(ctx, "%s's reviewer sessions %s opened no file, so no review "
                    "is on record (cannot-tell) and there is no third dispatch. "
                    "The task's notes name them; read the changed code and "
                    "file the reviewer's return by hand, or block the task." % (
                        task["id"], " and ".join(held["unreadSessions"])))


def reviewer_session_step(ctx, state, manifest, phase, task, tree=None):
    """`(reviewer, stop)` for a dispatched reviewer that has filed nothing: when
    it ran as a session, the wait while its record is empty, the redispatch or
    the stop for a stream with no tool call, and - for one that opened files -
    its last message filed as the return through `submit`, read back as
    `filed` reads it. `(None, None)` when no session was dispatched or the last
    one produced no result or no return object, which the caller asks about as
    the plain no-reviewer-return."""
    held = writer_state(state, task, REVIEWER_KEY)
    if not held["dispatches"]:
        return None, None
    note_sessions(ctx, state, task, REVIEWER_KEY)
    last = held["dispatches"][-1]
    runs = read_sessions(last["record"])
    if not runs:
        return None, wait_said(ctx, task["id"], project_relative(
            ctx, last["record"]), last.get("argv") or [], "wait-reviewer-session")
    run = runs[-1]
    if not run["session"]:
        return None, None
    calls, why = stream_tool_calls(run["stream"])
    if calls is None:
        return None, _stopped(ctx, "%s's reviewer session %s left a stream the "
                              "drive cannot count tool calls in (%s), so whether "
                              "it opened a file is not known and nothing was "
                              "filed" % (task["id"], run["session"], why))
    if calls == 0:
        return None, reviewer_unread(ctx, state, phase, task, run, last["seq"],
                                     tree)
    text, _why = session_last_message(run["stream"])
    body = return_object(text)
    if body is None:
        return None, None
    code, said = submit(ctx, manifest, argparse.Namespace(
        id=task["id"], role="reviewer", head=None, slice=None, shown=None), None,
        json.dumps(body, indent=2) + "\n")
    if code != E_OK:
        return None, (code, said)
    reviewer, problem = filed(ctx, task, "reviewer")
    if problem:
        return None, _stopped(ctx, problem)
    return reviewer, None


def recorded_session(state, task):
    """The session id a resume goes to: the latest outcome that carried one.
    None when no session produced a result."""
    for run in reversed(writer_state(state, task)["runs"]):
        if run.get("session"):
            return run["session"]
    return None


def failing_lines(text):
    """The lines of a red gate's output a writer acts on: every verdict line,
    every step line that exited non-zero and the lines indented under it. When
    the output holds none of those shapes, its last lines, so a resume prompt
    is never empty."""
    kept, under = [], False
    for line in (text or "").splitlines():
        step = re.match(r"^  \S+\s+exit (-?\d+)\s", line)
        if step:
            under = step.group(1) != "0"
            if under:
                kept.append(line)
        elif under and line.startswith("      "):
            kept.append(line)
        elif "GATE " in line:
            under = False
            kept.append(line)
        else:
            under = False
    lines = kept or [ln for ln in (text or "").splitlines() if ln.strip()][-RESUME_LINES:]
    return [_clip(ln.rstrip(), RESUME_LINE_BYTES) for ln in lines[:RESUME_LINES]]


GATE_RED_HEAD = "The task gate the drive ran after your session is red. Its failing lines:"


def resume_prompt(lines, head=None):
    return "\n".join([head or GATE_RED_HEAD, ""] + list(lines) + [
                         "", "Fix what fails. Leave the changes uncommitted: the "
                         "drive commits them. End with the same JSON object, one "
                         "entry per acceptance clause."]) + "\n"


def writer_path_on(ctx):
    """Whether `executor.writerModel` is set and reads whole, so a `resume`
    has a session to send to."""
    writer, problem = writer_setting(ctx["config"])
    return bool(writer) and not problem


def without_writer_way(name):
    """What to answer instead of `resume` on decision `name` when the writer
    path is off, read off the answers `DECISIONS` gives it: a fresh `retry`
    where it offers one, else `block` - or the setting put back."""
    options, needs = DECISIONS[name]
    if "retry" in options:
        return "answer retry"
    return "answer block%s, or set executor.%s again and answer resume" % (
        " with --reason" if "block" in needs else "", WRITER_MODEL_KEY)


def resume_writer(ctx, state, task, pending, tree=None):
    """`--answer resume` on a red gate: the failing lines go to the recorded
    session as its prompt, in the next round, and no attempt is spent."""
    writer, problem = writer_setting(ctx["config"])
    if problem or not writer:
        return _stopped(ctx, problem or "executor.%s is no longer set, so there "
                        "is no writer session to resume; %s" % (
                            WRITER_MODEL_KEY, without_writer_way(pending["decision"])))
    held = writer_state(state, task)
    round_n = held["resumes"] + 1
    prompt = session_record(ctx, task, held["seq"])[:-len(".jsonl")] + ".prompt.md"
    try:
        os.makedirs(os.path.dirname(prompt), exist_ok=True)
        with open(prompt, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(resume_prompt(pending.get("failing") or [], pending.get("prompt")))
    except OSError as exc:
        return _stopped(ctx, "the resume prompt could not be written to %s (%s)"
                        % (prompt, exc))
    _record, argv = open_dispatch(ctx, state, task, round_n, lambda record: writer_argv(
        ctx, task, writer, prompt, record, tree, resume=pending["session"]), tree,
        kind=RESUME_KINDS.get(pending["decision"]))
    held = writer_state(state, task)
    held["resumes"] = round_n
    _mark(state, "writer", task, held)
    write_state(ctx, state)
    return writer_said(ctx, task["id"], writer["model"],
                       project_relative(ctx, prompt), argv,
                       resume=pending["session"], round_n=round_n)


# --- a stored gate verdict, shown only while its basis holds -----------------------
# The decisions that stand on one recorded gate run. Each carries the run under
# `verdict` (`verdict_taken`), and every path that shows or acts on one - the
# pending decision, a member's parked one, `explain` - asks `pending_still_applies`,
# which asks `verdict_basis`. The two green marks a step closes on (`gated`,
# `regated`) carry the same record and are asked the same question
# (`stored_green`), so no stored verdict is shown past a change of what its gate
# resolves to or of the tree it was taken in.
GATE_VERDICT_DECISIONS = ("gate-red", "gate-red-writer")


def verdict_taken(ctx, text, tree=None):
    """The record a gate run's output names, kept beside a verdict the drive
    shows later: `{runId, at, tree, failing}` - the run id, the moment the run
    it stands on was measured (its source's, for a repeat), the tree the drive
    ran it in (None for the project), and the steps that did not exit 0. A run
    that printed no id, or a ledger that will not read, keeps what it has:
    `verdict_basis` says that the basis is missing."""
    found = _RUN_ID.search(text or "")
    held = {"runId": found.group(1) if found else None, "at": None,
            "tree": tree or None, "failing": []}
    if not found:
        return held
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception:                                          # noqa: BLE001
        return held
    row = _evio.row_by_run(rows, held["runId"])
    measured = _evio.measured_row(rows, row) or row or {}
    held["at"] = measured.get("ts")
    held["failing"] = _evio.red_step_names(measured)
    return held


def verdict_basis(ctx, manifest, task_id, held):
    """`(word, why)` - THE ONE CHECK a stored task-gate verdict passes before it
    is shown or closed on: the run `held` names, read back from the ledger,
    against the gate `task_id` resolves to now (`_evidence_io.gate_digest` over
    its entries and `meta.buildCommands`) and the tree the drive ran it in
    (`_evidence_io.stored_verdict_moved`, which says why the bytes in it are
    not asked here)."""
    if not isinstance(held, dict):
        return _evio.STORED_UNKNOWN, "no run was recorded with it"
    task = _mio.tasks_by_id(manifest).get(task_id) or {}
    phase = next((p for p in manifest.get("phases") or [] if isinstance(p, dict)
                  and any(isinstance(t, dict) and t.get("id") == task_id
                          for t in p.get("tasks") or [])), {})
    entries, _source = _mio.gate_entries(phase, task)
    build = (manifest.get("meta") or {}).get("buildCommands")
    where = member_project(ctx, held.get("tree"))
    if where and not os.path.isdir(where):
        return _evio.STORED_MOVED, "the tree it was measured in is gone"
    measured_in = (None if not where or os.path.realpath(where)
                   == os.path.realpath(ctx["project"]) else where)
    try:
        rows = _evio.read_rows(ctx["project"], ctx["config"])["rows"]
    except Exception as exc:                                   # noqa: BLE001
        return _evio.STORED_UNKNOWN, "the ledger could not be read (%s)" % (exc,)
    return _evio.stored_verdict_moved(rows, held.get("runId"), {
        "gateDigest": _evio.gate_digest(entries, build),
        "tree": _evio.tree_key(measured_in) if measured_in else None})


def note_basis(ctx, task_id, what, held, word, why):
    """Say once per run why a stored verdict about `task_id` was measured again
    (`word` moved) or shown with its basis unestablished (unknown)."""
    seen = ctx.setdefault("basisNoted", {})
    key = (task_id, what, (held or {}).get("runId") if isinstance(held, dict) else None)
    if key in seen:
        return
    seen[key] = why
    ctx.setdefault("did", []).append(
        "%s's %s no longer stands - %s; measured again" % (task_id, what, why)
        if word == _evio.STORED_MOVED else
        "%s's %s: whether it still answers its gate is not established - %s"
        % (task_id, what, why))


def verdict_moved(ctx, pending):
    """The sentence `pending` was dropped with because its run no longer answers
    its gate, or None - read off the note `note_basis` made this run."""
    held = pending.get("verdict") if isinstance(pending, dict) else None
    key = (pending.get("task"), pending.get("decision"),
           held.get("runId") if isinstance(held, dict) else None)
    why = (ctx.get("basisNoted") or {}).get(key)
    return why if key in (ctx.get("basisMoved") or ()) else None


def gate_basis_holds(ctx, manifest, pending):
    """False when `pending` stands on a gate run that no longer answers its gate:
    the decision is about a verdict nobody measured under the gate as it is."""
    if pending.get("decision") not in GATE_VERDICT_DECISIONS:
        return True
    held = pending.get("verdict")
    word, why = verdict_basis(ctx, manifest, pending["task"], held)
    if word == _evio.STORED_HOLDS:
        return True
    note_basis(ctx, pending["task"], pending["decision"], held, word, why)
    if word != _evio.STORED_MOVED:
        return True
    ctx.setdefault("basisMoved", set()).add(
        (pending["task"], pending["decision"],
         held.get("runId") if isinstance(held, dict) else None))
    return False


def stored_green(ctx, state, manifest, task, kind):
    """`holds`, `moved` or None: whether the green mark `kind` (`gated`,
    `regated`) holds for `task`'s start, asked through `verdict_basis`. A moved
    one is spent, so the step measures again; a mark from before the record was
    kept (`True`) reads as unknown and still holds, said once."""
    held = _marked(state, kind, task)
    if not held:
        return None
    word, why = verdict_basis(ctx, manifest, task["id"],
                              held if isinstance(held, dict) else None)
    if word == _evio.STORED_HOLDS:
        return word
    note_basis(ctx, task["id"], "stored green", held, word, why)
    if word != _evio.STORED_MOVED:
        return _evio.STORED_HOLDS
    _spend(state, kind, task)
    write_state(ctx, state)
    return word


def age_words(at):
    """How long ago the stamp `at` was, in its largest whole unit (`12s`,
    `4m`, `3h`, `2d`); None when it names no moment."""
    moment = _evio.stamp_moment(at) if at else None
    if moment is None:
        return None
    secs = max(0, int(ci_now() - moment))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return "%d%s" % (secs // size, unit)
    return "%ds" % (secs,)


def verdict_said(pending):
    """The clause a gate-verdict decision's line ends with: the run it stands
    on and its age, or that no run was recorded with it. "" for any other."""
    if pending.get("decision") not in GATE_VERDICT_DECISIONS:
        return ""
    held = pending.get("verdict")
    if not isinstance(held, dict) or not held.get("runId"):
        return "; no run recorded with it"
    age = age_words(held.get("at"))
    return "; run %s, %s" % (held["runId"], "%s old" % (age,) if age
                             else "age unknown")


def rerun_alongside(ctx, state, manifest, pending):
    """The parked wave members a `rerun` answered on `pending` reaches: each
    whose parked gate red failed on a step the answered one failed on too, its
    decision taken back and its next gate run marked to measure. A member red
    only on other steps keeps its decision for its own answer - it is asked,
    never replayed."""
    failing = set((pending.get("verdict") or {}).get("failing") or [])
    parked = (state.get("wave") or {}).get("parked") or {}
    by_id = _mio.tasks_by_id(manifest)
    reached, shared = [], set()
    for task_id in sorted(parked, key=_id_key):
        held = parked[task_id]
        other = by_id.get(task_id)
        common = failing & set((held.get("verdict") or {}).get("failing") or [])
        if (not common or other is None
                or held.get("decision") not in GATE_VERDICT_DECISIONS):
            continue
        shared |= common
        parked.pop(task_id)
        _mark(state, "rerun", other)
        reached.append(task_id)
    if reached:
        write_state(ctx, state)
        ctx["did"].append("rerun reaches %s too: red on the same step (%s)"
                          % (", ".join(reached), ", ".join(sorted(shared))))
    return reached


def gate_red_decision(ctx, state, manifest, phase, task, text, tree=None):
    """The decision a red task gate asks: resume of the recorded writer session
    while a round is left, carrying the failing lines; past the last round, the
    plain gate-red, after a note on the task naming each resumed run. Every one
    carries the run it stands on (`verdict_taken`)."""
    said = [ln for ln in (text or "").splitlines() if "GATE" in ln]
    why = ((said[0].strip() if said else "exit 1")[:80]
           + base_red_why(ctx, text, manifest, phase, task))
    verdict = {"verdict": verdict_taken(ctx, text, tree)}
    session = recorded_session(state, task)
    if session is None:
        return decision(ctx, state, "gate-red", task, why, extra=verdict)
    held = writer_state(state, task)
    if held["resumes"] < MAX_RESUME_ROUNDS:
        return decision(ctx, state, "gate-red-writer", task, "%s; session %s, "
                        "round %d/%d" % (why, session[:8], held["resumes"] + 1,
                                         MAX_RESUME_ROUNDS),
                        extra=dict(verdict, session=session,
                                   failing=failing_lines(text)))
    if not held["capNoted"]:
        refused = note_task(ctx, task, cap_note(ctx, held, session))
        if refused is not None:
            ctx["did"].append("the resume cap was not noted (%s)" % (refused,))
        held["capNoted"] = True
        _mark(state, "writer", task, held)
        write_state(ctx, state)
    return decision(ctx, state, "gate-red", task, "%s; still red after %d "
                    "resume rounds, named in the task's notes" % (
                        why, MAX_RESUME_ROUNDS), extra=verdict)


def cap_note(ctx, held, session):
    """The note naming every resumed run when the gate is still red after the
    last round: each run's stream and cost, a run with no result by the
    runner's words, and a round whose record never appeared by that record,
    project-relative. Each round is named by the kind it was (`RESUME_KINDS`),
    since a refused red-first proof and an unanswered clause spend the same
    budget as a red gate does."""
    named = []
    for round_n in range(1, MAX_RESUME_ROUNDS + 1):
        kinds = [d["kind"] for d in held.get("dispatches") or []
                 if d.get("round") == round_n and d.get("kind")]
        label = "round %d%s" % (round_n, " (%s)" % (kinds[-1],) if kinds else "")
        runs = [r for r in held.get("runs") or [] if r.get("round") == round_n]
        for run in runs:
            named.append("%s: stream %s, total_cost_usd=%s" % (
                label, os.path.basename(run["stream"]), run["cost"])
                if run.get("stream") else
                "%s: no result (%s)" % (label, _clip(run["line"], 120)))
        if not runs:
            records = [d["record"] for d in held.get("dispatches") or []
                       if d.get("round") == round_n]
            named.append("%s: %s" % (label, "no record at %s" % (
                project_relative(ctx, records[-1]),) if records
                else "never dispatched"))
    return ("writer session %s: the task gate is still red after its resume "
            "rounds (rounds of any kind - %s - spend the same budget): %s; a "
            "retry starts a fresh session" % (
                session, ", ".join(RESUME_KINDS.values()), "; ".join(named)))


# --- after the writer's session: prove, hold, file at the green gate -------------
# The writer runs no `submit`, so the drive runs its verbs. A filing is once per
# start, and a resume round may change the test files, so the proof is HELD in the
# drive's state until the recorded gate is green and filed then: the return always
# carries the proof made over the bytes it is filed with.
WRITER_CLAIM_FIELD = "writerClaim"
DIFF_PATHS_FIELD = "diffPaths"
REPROOFS_FIELD = "reproofs"
# Why a drive-filed return binds no case to a `tests.add` entry: the binding is
# a judgement by index the writer would make, and a printed label alone does
# not say which entry it answers.
CASES_BASIS_FIELD = "casesAddedBasis"
CASES_BASIS = ("absent: a writer session names no case per tests.add entry, and "
               "the drive binds no printed label to an entry by itself; every "
               "entry is listed among the gaps")
CLAUSES_UNCOVERED_HEAD = ("The clause coverage the drive checked after your session "
                          "did not hold. What it found:")
RED_REFUSED_HEAD = ("The red-first proof the drive ran after your session did not "
                    "hold. The helper's words:")


def tree_head(ctx, tree=None):
    """The commit HEAD names in `tree` (the task's own worktree), else in the
    project's repository; None when git cannot say."""
    if not tree:
        return git_head(ctx)
    try:
        done = subprocess.run(["git", "-C", tree, "rev-parse", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def head_move(ctx, task, since, now, tree=None):
    """`"writer"` when HEAD's move from `since` to `now` is commits descending
    from `since` that touch one of the task's declared files - what the session
    left; `"other"` for any other move (a sibling's commit in a shared checkout,
    a branch switched); None when git cannot say."""
    where = tree or ctx["gitRoot"]
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(where) or where
    project = member_project(ctx, tree) or ctx["project"]
    try:
        above = subprocess.run(["git", "-C", top, "merge-base", "--is-ancestor",
                                since, now], capture_output=True, timeout=60)
        if above.returncode == 1:
            return "other"
        if above.returncode != 0:
            return None
        done = subprocess.run(["git", "-C", top, "log", "--format=", "--name-only",
                               "--no-renames", "%s..%s" % (since, now)],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    touched = set(hc.git_to_plan(p, top, project) for p in done.stdout.decode(
        "utf-8", "replace").splitlines() if p.strip())
    declared = [str(f).replace("\\", "/").rstrip("/") for f in task.get("files") or []
                if isinstance(f, str) and f.strip()]
    hit = any(p == f or p.startswith(f + "/") for p in touched for f in declared)
    return "writer" if hit else "other"


def writer_test_command(manifest, phase, task):
    """`(argv, None)` - the resolved gate command naming one of the task's
    `tests.add` files, split into words: `_filed_returns.red_command`, the one
    reader the executor's brief prints after `--` - or `(None, basis)` saying
    why there is none. A task that owes no red-first proof
    (`_filed_returns.owes_red_first`: not `tdd`, or its stored `expectRedFirst`
    false) is `(None, None)`, whatever its `tests.add` names."""
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    added = _fr.tests_add_files(task)
    if not _fr.owes_red_first(task):
        return None, None
    if not added:
        return None, ("%s is %s and its tests.add names no file, so no test "
                      "command could be derived" % (task["id"], tests.get("mode")))
    entries, _whose = _fr.task_gate_entries(phase, task)
    cmd = _fr.red_command(task, _evio.resolved_commands(manifest, entries))
    if cmd is None:
        return None, ("no gate entry of %s names its tests.add file (%s) as a "
                      "path, so no test command could be derived and no red was "
                      "run" % (task["id"], ", ".join(added)))
    try:
        return shlex.split(cmd), None
    except ValueError as exc:
        return None, ("the gate command naming %s does not split into words "
                      "(%s), so no test command could be derived"
                      % (", ".join(added), exc))


def session_last_message(stream):
    """`(text, None)` - the `result` text of the last result event the session's
    stream holds, as the session wrote it - or `(None, why)`."""
    try:
        with open(stream, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, TypeError) as exc:
        return None, "its stream could not be read (%s)" % (exc.__class__.__name__,)
    text = None
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            text = event.get("result")
    if not isinstance(text, str):
        return None, "its stream holds no result text"
    return text, None


def diff_paths(ctx, phase, tree=None):
    """The paths the tree changed against HEAD, untracked ones included, with
    the plan's own records left out (`_invariants.record_rels`), each spelled
    as the plan spells it (`_config.git_to_plan`, read from the checkout's top):
    the writer's diff as the return names it. None when git cannot say."""
    where = tree or ctx["gitRoot"]
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(where) or where
    project = member_project(ctx, tree) or ctx["project"]
    try:
        done = subprocess.run(["git", "-C", where, "status", "--porcelain", "-z",
                               "--untracked-files=all", "--no-renames"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    records = _invariants.record_rels(ctx["manifest"], phase, ctx["project"],
                                      ctx["gitRoot"], config=ctx["config"])
    paths = [item[3:].decode("utf-8", "replace") for item in done.stdout.split(b"\0")]
    return sorted(set(hc.git_to_plan(p, top, project) for p in paths
                      if p and not _invariants.is_record_path(p, records)))


def _git_run(where, argv):
    """`(returncode, stdout bytes, None)` of one git call in `where`, or `(None,
    None, why)` when git could not be run at all."""
    try:
        done = subprocess.run(["git", "-C", where] + list(argv),
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, exc.__class__.__name__
    return done.returncode, done.stdout, None


def carried_paths(ctx, phase, task, tree=None):
    """`(paths, left, None)` - the paths changed by each commit `task` carried
    before a re-open cleared it, read off the journal's `task.reopen` rows
    (`reopen_record`) and spelled as `diff_paths` spells them, the plan's own
    records left out - or `(None, None, why)` when the journal cannot be read
    or git cannot be run. `([], [], None)` for a task never re-opened. A
    re-opened task's first commit is already in HEAD, so `diff_paths` alone
    never shows the files it wrote.

    A carried commit counts only while `git merge-base --is-ancestor <sha>
    HEAD` says it is in HEAD's history: one a reset took out, or a sha git does
    not know, delivers nothing at this HEAD. It is left out and named in
    `left`, one `"<sha12> <reason>"` each, never counted and never a stop."""
    carried, _handed, why = reopen_record(ctx, phase)
    if why is not None:
        return None, None, why
    shas = sorted(sha for sha, tid in carried.items() if tid == task["id"])
    if not shas:
        return [], [], None
    where = tree or ctx["gitRoot"]
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(where) or where
    project = member_project(ctx, tree) or ctx["project"]
    records = _invariants.record_rels(ctx["manifest"], phase, ctx["project"],
                                      ctx["gitRoot"], config=ctx["config"])
    paths, left = set(), []
    for sha in shas:
        code, _out, why = _git_run(where, ["merge-base", "--is-ancestor", sha, "HEAD"])
        if why is not None:
            return None, None, "git could not be run (%s)" % (why,)
        if code == 1:
            left.append("%s not in HEAD's history" % (sha[:12],))
            continue
        if code != 0:
            left.append("%s unknown to git (merge-base exit %d)" % (sha[:12], code))
            continue
        code, out, why = _git_run(where, [
            "diff-tree", "--root", "-r", "-z", "--no-commit-id", "--name-only",
            "--no-renames", sha])
        if why is not None:
            return None, None, "git could not be run (%s)" % (why,)
        if code != 0:
            left.append("%s unlisted by git (diff-tree exit %d)" % (sha[:12], code))
            continue
        paths.update(hc.git_to_plan(p, top, project)
                     for p in out.decode("utf-8", "replace").split("\0")
                     if p and not _invariants.is_record_path(p, records))
    return sorted(paths), left, None


def locked_paths_now(ctx, lock, tree=None):
    """The locked digest's own paths hashed as the tree holds them now -
    `_journal_io.file_hash`, the sha256 of the bytes in the spelling
    `stamp-verification.py red` reports them in (`testDigest`) - relative to
    the checkout's top of `tree`, else of the project's repository. Only the
    per-file hashes are compared, so the digest over the list is not
    recomputed here; the `wf3` twin is what holds the two readings equal on an
    unchanged file. A file added under a declared test directory after the
    lock is not among its paths, so it is not compared."""
    where = tree or ctx["gitRoot"]
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(where) or where
    files = []
    for entry in lock.get("files") or []:
        rel = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(rel, str):
            continue
        files.append({"path": rel, "sha256": _journal_io.file_hash(
            os.path.join(top, *rel.split("/")))})
    return {"files": files}


def changed_tests(lock, now):
    """The test paths whose bytes differ between the digest a proof locked and
    `now`, sorted: a path in either that the other lacks counts as changed."""
    def files(d):
        return dict((f.get("path"), f.get("sha256"))
                    for f in (d or {}).get("files") or [] if isinstance(f, dict))
    was, cur = files(lock), files(now)
    return sorted(p for p in set(was) | set(cur) if was.get(p) != cur.get(p))


def lock_moved(ctx, state, task, tree=None):
    """The test files changed since the digest the task's red proof locked,
    sorted; `[]` when nothing was locked or nothing moved."""
    lock = writer_state(state, task).get("lock")
    if not isinstance(lock, dict):
        return []
    return changed_tests(lock, locked_paths_now(ctx, lock, tree))


def unowed_red_first(task):
    """The `not-attempted` block, without its time, of a task that owes no
    red-first proof (`_filed_returns.owes_red_first`), its basis naming which
    stored field says so - or None for a task that does owe one."""
    if _fr.owes_red_first(task):
        return None
    tests = task.get("tests") or {}
    if tests.get("mode") == "tdd":
        basis = ("tests.expectRedFirst is false on this tdd task: it names no "
                 "case to prove a red by, so no red-first proof is owed")
    else:
        basis = ("tests.mode %s: only a tdd task owes a red-first proof"
                 % (tests.get("mode") or "unset",))
    return {"status": "not-attempted", "basis": basis}


def fix_prove_lines(task):
    """The fix prompt's instruction to prove each finding with a case failing at
    HEAD, as lines: empty for a task that owes no red-first proof."""
    if not _fr.owes_red_first(task):
        return []
    return ["Prove each with a case that fails on the code at HEAD."]


def writer_prove(ctx, manifest, phase, task, tree=None):
    """`(block, payload, None)` - the red-first block for the writer's work: the
    helper's over the derived test command, carrying the digest it was proved
    over and the HEAD its throwaway ran at; `could-not-prove` naming the basis
    where no command can be derived; `not-attempted` where the task owes no
    red-first proof (`unowed_red_first`) - or `(None, None, why)` with the
    helper's own words when it gave no block or refused."""
    cmd, basis = writer_test_command(manifest, phase, task)
    if cmd is None and basis is None:
        return dict(unowed_red_first(task), at=_utc_stamp(),
                    head=tree_head(ctx, tree)), None, None
    if cmd is None:
        return {"status": "could-not-prove", "at": _utc_stamp(),
                "head": tree_head(ctx, tree), "basis": basis}, None, None
    block, payload, why = red_reading(ctx, task, red_args(
        tree or ctx["gitRoot"], ctx["manifest"], task["id"], cmd))
    if why is not None:
        return None, None, "%s (exit %d): %s" % (
            "the helper refused" if why[0] == "refused" else
            "the helper gave no block", why[1], " ".join(str(why[2]).split()))
    block = dict(block, source=_fr.HELPER_SOURCE) if payload else dict(block)
    ran_at = ((payload or {}).get("throwaway") or {}).get("head") \
        if isinstance(payload, dict) else None
    block["head"] = ran_at or tree_head(ctx, tree)
    digest = payload.get("testDigest") if isinstance(payload, dict) else None
    if isinstance(digest, dict):
        block["testDigest"] = digest
    impl = payload.get("implementationDigest") if isinstance(payload, dict) else None
    if isinstance(impl, dict):
        block["implementationDigest"] = impl
    return block, dict(payload or {}, implementationDigest=impl), None


def hold_proof(ctx, state, task, block, payload=None):
    """Hold `block` as the proof the writer's return is filed with, beside what
    it was proved over: the HEAD, the test digest (locked) and the digest of
    the implementation files the fix run read."""
    held = writer_state(state, task)
    impl = (payload or {}).get("implementationDigest")
    held["proof"] = {"block": block, "printed": ctx.get("printed"),
                     "head": block.get("head"),
                     "implementation": impl if isinstance(impl, dict) else None}
    digest = block.get("testDigest")
    held["lock"] = dict(digest, at=block.get("at")) if isinstance(digest, dict) \
        else None
    _mark(state, "writer", task, held)
    write_state(ctx, state)


def tree_since_proof(ctx, state, task, tree=None):
    """`(drift, changed_tests)` - how the tree the work would be filed or
    committed with differs from what the held proof was made over, in the
    three things the proof records - HEAD, a declared test file, a declared
    implementation file - as phrases, and the test files among them. `([],
    [])` when those match, or no proof is held. A file the task does not
    declare is not read here; `commit-task-work.py`'s `attempt_refusal` is what
    refuses one the attempt changed, and on the writer path `settle_aside`
    sets it aside instead. THE ONE READING every filing and every
    re-proof decision asks."""
    proof = writer_state(state, task).get("proof")
    if not isinstance(proof, dict):
        return [], []
    drift = []
    now = tree_head(ctx, tree)
    if proof.get("head") != now:
        drift.append("HEAD %s, proved at %s" % ((now or "unknown")[:12],
                                                (proof.get("head") or "unknown")[:12]))
    tests = lock_moved(ctx, state, task, tree)
    if tests:
        drift.append("test files changed: %s" % (", ".join(tests),))
    impl = proof.get("implementation")
    moved = changed_tests(impl, locked_paths_now(ctx, impl, tree)) \
        if isinstance(impl, dict) else []
    if moved:
        drift.append("implementation changed: %s" % (", ".join(moved),))
    return drift, tests


def red_refused(ctx, state, task, why):
    """The decision a red-first proof that did not hold asks - the helper gave
    no block (a test passing without the fix), refused (a test file gone), or a
    re-proof no longer proves: back to the session that wrote it while a round
    is left, else a fresh retry. Nothing is filed and no lock moves."""
    session = recorded_session(state, task)
    if (session and writer_path_on(ctx)
            and writer_state(state, task)["resumes"] < MAX_RESUME_ROUNDS):
        return decision(ctx, state, "red-refused-writer", task, _clip(why, 160),
                        extra={"session": session, "failing": [_clip(why, 2000)],
                               "prompt": RED_REFUSED_HEAD})
    return decision(ctx, state, "red-refused", task, _clip(why, 160))


def clauses_uncovered(ctx, state, task, result, clauses, left=()):
    """The decision a writer's unanswered clause asks, at a green gate: back to
    the session that wrote it while a round is left - the round counts toward
    `MAX_RESUME_ROUNDS`, as every resume does - else a fresh retry. Nothing is
    filed and the held proof stays. `left` names each carried commit
    `carried_paths` left out, which the reason carries after the gaps."""
    why = _clip(_cc.gap_summary(result), 160)
    if left:
        why = "%s; carried commit(s) left out: %s" % (why, _clip("; ".join(left), 160))
    session = recorded_session(state, task)
    if (session and writer_path_on(ctx)
            and writer_state(state, task)["resumes"] < MAX_RESUME_ROUNDS):
        return decision(ctx, state, "clauses-uncovered-writer", task, why, extra={
            "session": session, "prompt": CLAUSES_UNCOVERED_HEAD,
            "failing": _cc.resume_text(result, clauses).splitlines()})
    return decision(ctx, state, "clauses-uncovered", task, why)


def note_reproof(ctx, state, task, when, changed, block):
    """Keep a re-proof over changed test files, for the return and the task."""
    held = writer_state(state, task)
    held["reproofs"] = list(held["reproofs"]) + [
        {"when": when, "changed": list(changed), "status": block.get("status"),
         "at": block.get("at")}]
    _mark(state, "writer", task, held)
    write_state(ctx, state)
    refused = note_task(ctx, task, "test files changed after the red proof (%s): "
                        "%s; re-proved red over them: %s - %s" % (
                            when, ", ".join(changed), block.get("status"),
                            _clip(str(block.get("basis") or ""), 300)))
    ctx["did"].append("red-first re-proved %s over %s%s" % (
        block.get("status"), ", ".join(changed),
        "" if refused is None else " (not noted: %s)" % (refused,)))


def prove_and_hold(ctx, state, manifest, phase, task, when, tree=None):
    """Prove the work as the tree holds it now and hold that proof - unless it
    is already held over this very tree and proved (or owed none). A proof
    that no longer proves what the held one did, or that the helper will not
    grade, is `red_refused`. None, or the decision."""
    held = writer_state(state, task)
    proof = held.get("proof")
    drift, changed = tree_since_proof(ctx, state, task, tree)
    was = ((proof or {}).get("block") or {}).get("status") \
        if isinstance(proof, dict) else None
    if isinstance(proof, dict) and not drift and was in ("proved", "not-attempted"):
        return None
    block, payload, why = writer_prove(ctx, manifest, phase, task, tree)
    if why is not None:
        return red_refused(ctx, state, task, why)
    if was == "proved" and block.get("status") != "proved":
        return red_refused(ctx, state, task, "the re-proof (%s) is %s: %s" % (
            "; ".join(drift) or "the held tests", block.get("status"),
            " ".join(str(block.get("basis") or "").split())))
    hold_proof(ctx, state, task, block, payload)
    if changed:
        note_reproof(ctx, state, task, when, changed, block)
    ctx["did"].append("red-first %s%s" % (block.get("status"), (
        " again (%s)" % ("; ".join(drift),)) if proof else ""))
    return None


def writer_settle(ctx, state, manifest, phase, task, tree=None):
    """What follows a writer session whose record holds a result, once per
    dispatch: a move of HEAD stops it - `writer-committed` naming the commit
    when the session committed the task's files, `head-moved` otherwise, and
    `head-unknown` when git names no HEAD on either side - and nothing is
    filed; else the work is proved and the proof held (`prove_and_hold`). None
    when the drive goes on - also when the latest run produced no result,
    which `no-executor-return` meets as before."""
    held = writer_state(state, task)
    if not held["dispatches"]:
        return None
    last = held["dispatches"][-1]
    if held.get("settled") == last["seq"]:
        return None
    if not writer_round_done(state, task):
        return None
    now = tree_head(ctx, tree)
    if not (last.get("head") and now):
        return decision(ctx, state, "head-unknown", task, "HEAD %s, %s at the "
                        "dispatch" % ((now or "unknown")[:12],
                                      (last.get("head") or "unknown")[:12]),
                        extra={"head": now})
    if now != last["head"]:
        whose = head_move(ctx, task, last["head"], now, tree)
        if whose == "writer":
            return decision(ctx, state, "writer-committed", task, "commit %s on "
                            "the dispatch's %s" % (now[:12], last["head"][:12]),
                            extra={"commit": now})
        return decision(ctx, state, "head-moved", task, "HEAD %s, %s at the "
                        "dispatch" % (now[:12], last["head"][:12]),
                        extra={"head": now})
    if already_filed(ctx, task) is None:
        stop = prove_and_hold(ctx, state, manifest, phase, task,
                              "resume round %d" % (last["round"],), tree)
        if stop is not None:
            return stop
    held = writer_state(state, task)
    held["settled"] = last["seq"]
    _mark(state, "writer", task, held)
    write_state(ctx, state)
    return None


def writer_round_done(state, task):
    """Whether the latest writer dispatch's record holds a session's result: a
    round that produced none - the session could not run, or ended with no
    result - files nothing and proves nothing."""
    held = writer_state(state, task)
    if not held["dispatches"]:
        return False
    return any(r.get("session") for r in read_sessions(held["dispatches"][-1]["record"]))


def writer_holds(state, task):
    """Whether a writer's proof is held for `task`'s current start, waiting on
    the green gate to be filed, and the latest round ended with a result."""
    return (isinstance(writer_state(state, task).get("proof"), dict)
            and writer_round_done(state, task))


def writer_return(task, paths, block, stamp, claim, claim_why, reproofs=()):
    """The return the drive files for a writer session: the diff's paths, the
    red-first block, the stamp, every re-proof over changed test files, and the
    last session's final message as the writer's CLAIM - which the recorded
    gate and the reviewer grade, never a verdict itself. `file-return` scrubs
    machine paths from it as from every committed return."""
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    added = [a for a in tests.get("add") or []
             if isinstance(a, str) and a.split(":", 1)[0].strip() in paths]
    return {
        "gates": {},
        "outcome": {
            "technical": "Filed by the drive at the writer's green gate: the diff "
                         "touches %s; red-first %s. The session's last message %s "
                         "%s as the writer's claim, not a verdict: the recorded "
                         "gate and the reviewer grade the work." % (
                             ", ".join(paths) or "no path", block.get("status"),
                             "is kept in" if claim_why is None
                             else "is absent (%s) from" % (claim_why,),
                             WRITER_CLAIM_FIELD),
            "descriptive": "%s written by a headless writer session and filed by "
                           "the drive" % (task["id"],)},
        "testsAdded": added,
        "redFirst": block,
        "stamp": stamp,
        WRITER_CLAIM_FIELD: claim,
        DIFF_PATHS_FIELD: list(paths),
        REPROOFS_FIELD: list(reproofs)}


def file_writer_return(ctx, state, manifest, phase, task, tree=None):
    """Take the stamp and file the writer's return through `audit-task.py
    file-return` with the held proof, once the recorded gate is green; None
    when it is filed, else the stop."""
    # THE INVARIANT: a return is filed only with a proof made over the HEAD and
    # the declared test and implementation files it is filed with. A HEAD or a
    # declared file that moved since the held proof is proved again first (or
    # goes back to the writer); an undeclared file is commit-task-work's to
    # refuse, which the writer's close meets by setting it aside (`settle_aside`).
    stop = prove_and_hold(ctx, state, manifest, phase, task, "before the filing",
                          tree)
    if stop is not None:
        return stop
    drift, _changed = tree_since_proof(ctx, state, task, tree)
    if drift:
        return _stopped(ctx, "the tree of %s moved while its proof ran (%s), so "
                        "nothing was filed; next proves it again"
                        % (task["id"], "; ".join(drift)))
    held = writer_state(state, task)
    proof = held.get("proof") or {}
    block = proof.get("block") or {}
    paths = diff_paths(ctx, phase, tree)
    if paths is None:
        return _stopped(ctx, "git could not list what the writer session of %s "
                        "changed, so nothing was filed" % (task["id"],))
    claim, why = writer_claim(state, task)
    # CLAUSE COVERAGE, after the proof and before the stamp: a clause the
    # writer left unanswered, or answered with a file the diff does not touch,
    # goes back to the session instead of being filed in silence. A message the
    # stream could not give is a gap of every clause, never covered. A
    # re-opened task's clauses are read against the commits it carried that
    # HEAD still holds, as well as this start's diff: what such a commit
    # delivered is its own work. A carried commit HEAD does not hold is named.
    carried, left, why_carried = carried_paths(ctx, phase, task, tree)
    if carried is None:
        return _stopped(ctx, "%s, so the clauses of %s cannot be read against the "
                        "commit it carried, and nothing was filed"
                        % (why_carried, task["id"]))
    clauses = _cc.task_clauses(task)
    covered = _cc.check(clauses, claim, sorted(set(paths) | set(carried)),
                        root=member_project(ctx, tree) or ctx["project"])
    if not covered["covered"]:
        return clauses_uncovered(ctx, state, task, covered, clauses, left)
    if left:
        said = ("clause coverage left out the carried commit(s) %s, so no clause "
                "was covered by them" % ("; ".join(left),))
        refused = note_task(ctx, task, said)
        ctx["did"].append("%s: %s%s" % (task["id"], said, "" if refused is None
                                        else " (not noted: %s)" % (refused,)))
    if covered["declined"]:
        ctx["did"].append("%s: the writer reports clause %s as not delivered"
                          % (task["id"], ", ".join(str(n) for n in covered["declined"])))
    line, stop = take_stamp(ctx, task, tree) if tree else take_stamp(ctx, task)
    if stop is not None:
        return stop
    body = writer_return(task, paths, block, line, claim, why, held["reproofs"])
    cmd, _basis = writer_test_command(manifest, phase, task)
    printed = proof.get("printed") if cmd else None
    body[_fr.GAPS_FIELD] = case_binding_gaps(task, None, printed, cmd)
    body[_fr.UNCHECKED_FIELD] = (_fr.case_binding_unchecked(task, cmd)
                                 if cmd and printed is not None else [])
    body[CASES_BASIS_FIELD] = CASES_BASIS
    out, stop = _verb_or_stop(ctx, "audit-task.py", [
        "file-return", task["id"], "--role", "executor", ctx["manifest"],
        "--project-dir", ctx["project"]], stdin=json.dumps(body, indent=2) + "\n")
    if stop is not None:
        return stop
    path = _fr.return_path(ctx["evidence"], task, "executor")
    if path and re.search(r"written: (.+)$", out.strip()):
        _journal_filed_return(ctx, task, "executor", path, block.get("status"))
    if tree:
        carry_work(ctx, task, tree, (state.get("wave") or {}).get("records"))
    ctx["did"].append("%s writer return filed by the drive, red-first %s; stamp "
                      "taken after the gate" % (task["id"], block.get("status")))
    return None


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


def member_project(ctx, tree):
    """The project's directory inside `tree`, a checkout of the git root: `tree`
    itself where the project IS the git root (or `tree` is None), else `tree`
    with the project's place under `ctx["gitRoot"]` appended.

    A member's worktree is a checkout of the whole repository, so for a project
    nested under its git root its top is not where the project's files, the
    gate's commands or the project-relative record paths are. Everything that
    reads a task's declared `files` or runs the gate's commands reads them from
    here. The stamp helper is handed the checkout's top instead and finds the
    project itself: it prefixes the project's offset under its git root (read
    off the manifest it is given) onto the task's declared entries, so the
    paths it digests, copies and names are checkout-relative while the plan's
    stay project-relative."""
    if not tree:
        return tree
    rel = os.path.relpath(ctx["project"], ctx["gitRoot"])
    if rel == "." or rel == ".." or rel.startswith(".." + os.sep):
        return tree
    return os.path.join(tree, *rel.split(os.sep))


def record_gate(ctx, phase, task, tree=None, no_reuse=False):
    """`(code, stdout, stderr)` of the task's recorded gate run - measured in
    the project's directory inside `tree` (`member_project`) when the task runs
    in a tree of its own, and recorded in the project's ledger either way.
    `no_reuse` measures even where an earlier verdict on the same tree could be
    repeated: what a `rerun` asks for."""
    where = member_project(ctx, tree)
    return run_verb(ctx, "run-test-gate.py", [
        ctx["manifest"], phase["id"], "--task", task["id"], "--record",
        "--project-dir", ctx["project"]] + (["--tree", where] if where else [])
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


def commit_scope_index(ctx, subject):
    """Commit the index a `scope` the drive ran rewrote, in a sharded plan;
    None, or the stop. `scope` writes the path's fileIndex row into the index
    and the task's own shard, and the task commit carries the shard alone - it
    refuses a shard declaring a path the index HEAD holds has no row for. So
    the index is committed here, on its own, as a hand `scope` is followed by
    it; the index is shared by every phase, and a task commit carrying it
    would carry other phases' rows with it. A plan in one file has no index
    apart from the task's own declaration, so nothing is committed."""
    try:
        sharded = _mio.is_sharded(_mio.read_json(ctx["manifest"]))
    except Exception as exc:                                   # noqa: BLE001
        return _stopped(ctx, "%s cannot be read to tell its layout (%s)"
                        % (ctx["manifest"], exc))
    if not sharded:
        return None
    _out, stop = _verb_or_stop(ctx, "commit-manifest-index.py", [
        ctx["manifest"], ctx["phase"], "--project", ctx["project"],
        "--subject", subject, "--json"])
    return stop


def widen_task(ctx, state, task, paths, basis):
    """Declare `paths` beside the task's files with `basis` noted, and accept
    that scope so no scope-changed decision asks about it. None, or the stop."""
    manifest, _phase = load_phase(ctx)
    files = list((_mio.tasks_by_id(manifest).get(task["id"]) or task).get("files") or [])
    new = [p for p in dict.fromkeys(paths) if p not in files]
    if not new:
        return None
    _out, stop = _verb_or_stop(ctx, "audit-task.py", _task_args(
        ctx, "scope", task["id"], "--files", ",".join(files + new)))
    if stop is not None:
        return stop
    _out, stop = _verb_with_text(
        ctx, "audit-task.py", _task_args(ctx, "note", task["id"]), "--text",
        "files widened by %s: %s" % (", ".join(new), basis))
    if stop is not None:
        return stop
    stop = commit_scope_index(ctx, "%s widened by %s" % (task["id"], ", ".join(new)))
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
    # A recipe is printed by a gate step, which runs in the project directory,
    # so its paths are project-relative: it runs where the project is, inside
    # the member tree when the task has one.
    where = member_project(ctx, tree) or ctx["project"]
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


# `claim_section`, `case_binding_gaps` and `floor_contradicted_clause` live in
# `_filed_returns.py`, not here - ONE HOME for logic the reviewer brief
# (`audit-lookup.py`) and this driver both need, below both in the layer
# graph. Two entry points may not runtime-load each other
# (`_deps.layer_violations()`), which is what putting the first version of
# `claim_section` here and loading it FROM `audit-lookup.py` tripped - a
# same-layer edge neither module's own layer may carry. Aliased here, not
# re-defined, so this file's own cases (`test_drive_phase.py`) and anything
# that reads `M.claim_section` off this module keep working unchanged.
claim_section = _fr.claim_section
case_binding_gaps = _fr.case_binding_gaps
floor_contradicted_clause = _fr.floor_contradicted_clause


# --- CI at a cadence --------------------------------------------------------------
# A phase that runs for days used to meet CI only when it landed, so what it
# broke on another platform surfaced after the work on top of it was done.
# `ci.cadence` asks earlier: at a close that makes it due the driver pushes the
# phase tip to `ci/<phase>` and dispatches the workflow there, and it never
# waits - the verdict is read at the NEXT close (and at sign-off, so the last
# run is not dropped). A red files a bug; a run still going is left alone.
# Absent, the driver makes no CI call at all.
CI_TIMEOUT = 120
CI_RED = ("failure", "timed_out", "startup_failure")
CI_LIST_FIELDS = "databaseId,headSha,status,conclusion,url"


def ci_run(ctx, argv):
    """`(code, stdout, stderr)` of one git or `gh` call, from the git root. The
    one seam to a remote: it never raises, never reads stdin and never prompts
    for credentials, so a missing `gh` or a refused push is a code, not a hang."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        done = subprocess.run(argv, cwd=ctx["gitRoot"], env=env, text=True,
                              encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=CI_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", "%s: %s" % (type(exc).__name__, exc)
    return done.returncode, done.stdout, done.stderr


def ci_now():
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def ci_started(phase):
    """The epoch second the phase's `startedAt` names, or None."""
    try:
        moment = datetime.datetime.strptime(
            str(phase.get("startedAt") or ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return moment.replace(tzinfo=datetime.timezone.utc).timestamp()


def ci_due(cadence, held, now):
    """Whether a dispatch is owed: `closes` task closes since the last one, or
    `hours` of phase time since it. Either is enough; one left unset never is."""
    closes, hours = cadence.get("closes"), cadence.get("hours")
    if closes and held.get("closes", 0) >= closes:
        return True
    return bool(hours and now - held.get("at", now) >= hours * 3600)


def ci_branch(phase):
    return "ci/%s" % (str(phase["id"]).lower(),)


def ci_file_red(ctx, run, row):
    """The stop, or None, of filing the bug a red run owes: its title names the
    branch, the commit and the run, so it cannot be mistaken for another."""
    title = "CI red on %s at %s (run %s)" % (run["branch"], run["sha"][:7],
                                             row.get("databaseId"))
    why = ("The phase's CI run %s on %s at %s ended %s. %s - open the run for "
           "the failing jobs and cases. Filed by the drive's ci.cadence read."
           % (row.get("databaseId"), run["branch"], run["sha"],
              row.get("conclusion"), row.get("url") or "no run URL"))
    _out, stop = _verb_with_text(ctx, "audit-task.py", [
        "bug-add", title, ctx["manifest"], "--project-dir", ctx["project"],
        "--severity", "high"], "--description", why)
    return stop


def ci_settle(ctx, state, cadence):
    """Read the run the last dispatch left out, without waiting for it: `(done,
    stop)`. `done` is False while it is unread or still going, so nothing is
    dispatched on top of it. A run that cannot be read is said, never filed."""
    held = state.get("ci") or {}
    run = held.get("run")
    if not run:
        return True, None
    code, out, err = ci_run(ctx, [
        "gh", "run", "list", "--workflow", cadence["workflow"], "--branch",
        run["branch"], "--limit", "10", "--json", CI_LIST_FIELDS])
    try:
        rows = json.loads(out) if code == 0 else None
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        ctx["did"].append("CI %s unread: %s" % (run["sha"][:7], _clip(
            (err or out or "exit %d" % (code,)).strip(), 80)))
        return False, None
    mine = [r for r in rows if isinstance(r, dict) and r.get("headSha") == run["sha"]]
    if not mine:
        ctx["did"].append("CI %s not listed yet" % (run["sha"][:7],))
        return False, None
    row = mine[0]
    if row.get("status") != "completed":
        ctx["did"].append("CI %s still running" % (run["sha"][:7],))
        return False, None
    if row.get("conclusion") in CI_RED:
        stop = ci_file_red(ctx, run, row)
        if stop is not None:
            return False, stop
        ctx["did"].append("CI %s red: bug filed" % (run["sha"][:7],))
    else:
        ctx["did"].append("CI %s %s" % (run["sha"][:7], "green"
                          if row.get("conclusion") == "success" else
                          "ended %s, no bug" % (row.get("conclusion"),)))
    held.pop("run", None)
    write_state(ctx, state)
    return True, None


def ci_dispatch(ctx, state, phase, cadence, now):
    """Push the phase tip to its `ci/` branch and dispatch the workflow there;
    the run is remembered for the next close. A failed push or dispatch is said
    and tried again at the next close, since nothing was left out to read."""
    sha = git_head(ctx)
    branch = ci_branch(phase)
    if not sha:
        ctx["did"].append("CI not dispatched: HEAD unreadable")
        return
    code, out, err = ci_run(ctx, ["git", "-C", ctx["gitRoot"], "push", "origin",
                                  "+%s:refs/heads/%s" % (sha, branch)])
    if code == 0:
        code, out, err = ci_run(ctx, ["gh", "workflow", "run",
                                      cadence["workflow"], "--ref", branch])
    if code != 0:
        ctx["did"].append("CI not dispatched: %s" % (_clip(
            (err or out or "exit %d" % (code,)).strip(), 80),))
        return
    state["ci"].update(run={"sha": sha, "branch": branch}, closes=0, at=now)
    write_state(ctx, state)
    ctx["did"].append("CI dispatched on %s at %s" % (branch, sha[:7]))


def ci_after_close(ctx, state, phase):
    """What `ci.cadence` owes a close: the verdict of the run left out, then -
    when the cadence says so and nothing is out - a new dispatch. The stop, or
    None. No cadence, no call."""
    cadence, problem = _config_rules.ci_cadence_setting(ctx["config"])
    if problem:
        ctx["did"].append("ci.cadence unread: %s" % (_clip(problem, 100),))
        return None
    if cadence is None:
        return None
    now = ci_now()
    held = state.setdefault("ci", {})
    held.setdefault("at", ci_started(phase) or now)
    held["closes"] = held.get("closes", 0) + 1
    settled, stop = ci_settle(ctx, state, cadence)
    if stop is not None:
        return stop
    if settled and ci_due(cadence, held, now):
        ci_dispatch(ctx, state, phase, cadence, now)
    else:
        write_state(ctx, state)
    return None


def ci_before_signoff(ctx, state):
    """Sign-off reads the run the last close left out, so a verdict that arrived
    after the final close is not dropped. The stop, or None."""
    cadence, _problem = _config_rules.ci_cadence_setting(ctx["config"])
    if cadence is None or not (state.get("ci") or {}).get("run"):
        return None
    return ci_settle(ctx, state, cadence)[1]


# --- a writer's edit outside the task's files -------------------------------------
# The writer's prompt is plain's and states no scope, so a writer session may edit
# a file the task does not declare. On the writer path that edit is SET ASIDE
# before the commit instead of refusing the whole task: kept as a patch under the
# drive's state, put back to HEAD, named in a note. Which paths those are is
# `commit-task-work.py`'s own answer - the `attempt.during` of its `--json`
# refusal, paths changed during the attempt that no in_progress task declares -
# so the drive holds no second reading of "undeclared". The executor path keeps
# the refusal: an agent's brief names the task's files.
SET_ASIDE_DIR = "set-aside"
_COMMITTED = re.compile(r"\bcommitted ([0-9a-f]{7,40})\b")


def commit_args(ctx, task):
    """The arguments every `commit-task-work.py` run of `task` takes."""
    return [ctx["manifest"], task["id"], "--project", ctx["project"],
            "--subject", str(task.get("title") or task["id"])]


def committed_sha(out):
    """The commit a `commit-task-work.py` run printed it made, or None."""
    found = _COMMITTED.search(out or "")
    return found.group(1) if found else None


def refusal_answer(ctx, task):
    """The JSON answer (`_scoped_commit.answer`'s shape) of a `commit-task-work.py
    --json` run, asked after a refusal to read WHICH arm refused; None when its
    stdout holds no object. A refusal stages nothing, so the run asks the same
    question of the same tree - and a refusal that came and went commits here,
    which the answer then says."""
    _code, out, _err = run_verb(ctx, "commit-task-work.py",
                                commit_args(ctx, task) + ["--json"])
    try:
        answer = json.loads(out)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


HELD_ASIDE = "dirty before the attempt, or no start snapshot to tell"


def undeclared_split(answer):
    """`(clean, held)` - the git-root paths a refused commit names as changed
    during the attempt with no in_progress task declaring them, when that is the
    WHOLE of its refusal (`attempt.during`, with no declared file older than the
    start - `declaredPredates` - or of mixed age - `mixed` - beside them), split
    by the commit's own `attempt.cleanAtStart`: `clean` the ones HEAD's bytes
    were the start of, which alone may be put back to HEAD, and `held` the rest
    - dirty before the attempt, or with no snapshot to tell - never reverted. An
    answer naming no `cleanAtStart` shows none clean. `([], [])` for any other
    refusal: one from another arm carries no `attempt`."""
    if not isinstance(answer, dict) or answer.get("committed") \
            or not answer.get("refused"):
        return [], []
    attempt = answer.get("attempt")
    if not isinstance(attempt, dict) or attempt.get("declaredPredates") \
            or attempt.get("mixed"):
        return [], []
    during = sorted(set(p for p in attempt.get("during") or []
                        if isinstance(p, str) and p.strip()))
    shown = attempt.get("cleanAtStart")
    shown = set(shown) if isinstance(shown, list) else set()
    return ([p for p in during if p in shown],
            [p for p in during if p not in shown])


def plugin_owned_paths(ctx, paths):
    """The git-root paths among `paths` under a row of
    `_manifest_io.PLUGIN_OWNED_IN_CLAUDE`, placed under the project's
    `.claude/` and the checkout's. The commit leaves these out already; the
    set-aside asks the same table again because a revert is not undone by a
    refusal that follows it. The table and its placement are
    `_scoped_commit.plugin_owned_rels`, the same the commit and the close ask,
    and where git cannot say whether the configuration file is tracked this
    reader asks with `UNKNOWN_PROTECTS`: it reverts what is not placed, so an
    unknown must not leave the file unplaced."""
    _others, named = _scoped_commit.split_plugin_owned(
        paths, _scoped_commit.plugin_owned_rels(
            ctx["project"], ctx["gitRoot"], _scoped_commit.UNKNOWN_PROTECTS))
    return [path for path, _why in named]


def writer_claim(state, task):
    """`(text, None)` - the last session's final message, the writer's claim -
    or `(None, why)`."""
    streams = [r.get("stream") for r in writer_state(state, task)["runs"]
               if r.get("session")]
    return session_last_message(streams[-1] if streams else None)


def aside_specs(ctx, plan_paths):
    """`(hooks config, top, specs)` - the checkout's top and each of
    `plan_paths` as the pathspec git reads from there (`_config.plan_to_git`);
    `specs` None when one lies outside the checkout, which no set-aside
    touches."""
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(ctx["gitRoot"]) or ctx["gitRoot"]
    specs = [hc.plan_to_git(p, top, ctx["project"]) for p in plan_paths]
    return hc, top, (None if any(s is None for s in specs) else specs)


def aside_plan_paths(ctx, paths):
    """`paths` as the refused commit names them - from the checkout's top - in
    the plan's spelling (`_config.git_to_plan`), sorted."""
    hc = _loader.load_hooks_config(modname="audit__config")
    top = hc.checkout_top(ctx["gitRoot"]) or ctx["gitRoot"]
    return sorted(set(hc.git_to_plan(p, top, ctx["project"]) for p in paths))


def aside_gap(ctx, state, phase, task, plan_paths):
    """Why setting `plan_paths` aside would open a clause gap, or None: the
    writer's answer read again (`_clause_coverage.check`) against the diff
    without them and the commits the task carried. A clause whose `delivered`
    answer cites one of them is work the writer claims, and a revert would turn
    it into a gap nobody was told of."""
    claim, _why = writer_claim(state, task)
    now = diff_paths(ctx, phase)
    carried, _left, why = carried_paths(ctx, phase, task)
    if now is None or carried is None:
        return ("what the tree changed, or the commits %s carried, could not be "
                "read (%s), so whether a clause cites them is not established"
                % (task["id"], why or "git could not list the diff"))
    result = _cc.check(_cc.task_clauses(task), claim,
                       sorted((set(now) - set(plan_paths)) | set(carried)),
                       root=ctx["project"])
    if result["covered"]:
        return None
    return "the writer's answer cites a path set aside for a clause (%s)" % (
        _clip(_cc.gap_summary(result), 200),)


def set_aside_file(ctx, task):
    """Where one set-aside of `task` is kept: the drive's state directory, a file
    per set-aside, never one written before."""
    base = os.path.join(ctx["stateDir"], SET_ASIDE_DIR, ctx["phase"], "%s-%s" % (
        task["id"], datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ")))
    path, n = base + ".patch", 1
    while os.path.exists(path):
        n += 1
        path = "%s-%d.patch" % (base, n)
    return path


def _git_literal(where, argv, env=None):
    """`(returncode, stdout, stderr)` of one git call over literal pathspecs - a
    path holding `*` names that path - or `(None, b"", why)`."""
    try:
        done = subprocess.run(["git", "-C", where, "--literal-pathspecs"] + list(argv),
                              capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, b"", exc.__class__.__name__.encode("utf-8")
    return done.returncode, done.stdout, done.stderr


def _git_said(argv, code, err):
    return "git %s %s (%s)" % (argv[0], "could not be run" if code is None
                               else "exited %d" % (code,),
                               _clip(" ".join(err.decode("utf-8", "replace").split()),
                                     160))


def aside_patch(ctx, plan_paths):
    """`(patch bytes, None)` - the binary diff from HEAD of `plan_paths`, a new
    file included, from the checkout's top, in the form `git apply` takes back
    there - or `(None, why)`. Read through a scratch copy of the index: a new
    file has no diff against the index, and staging it in the real one is the
    very stage the commit refuses."""
    _hc, top, specs = aside_specs(ctx, plan_paths)
    if specs is None:
        return None, "a path lies outside the checkout, where git cannot name it"
    code, out, err = _git_literal(top, ["rev-parse", "--git-path", "index"])
    if code != 0:
        return None, _git_said(["rev-parse"], code, err)
    index = out.decode("utf-8", "replace").strip()
    index = index if os.path.isabs(index) else os.path.join(top, index)
    scratch = tempfile.mkdtemp(prefix="drive-aside-")
    try:
        copy = os.path.join(scratch, "index")
        if os.path.isfile(index):
            shutil.copyfile(index, copy)
        env = dict(os.environ, GIT_INDEX_FILE=copy)
        for argv in (["add", "-A", "--"] + specs,
                     ["diff", "--cached", "--binary", "--no-renames", "HEAD", "--"]
                     + specs):
            code, out, err = _git_literal(top, argv, env=env)
            if code != 0:
                return None, _git_said(argv, code, err)
        return out, None
    except OSError as exc:
        return None, "the scratch index could not be made (%s)" % (exc,)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def set_aside(ctx, task, plan_paths):
    """Keep `plan_paths` as one patch under the drive's state, check that it
    reverses to the tree as it stands, then put each back to HEAD - checked
    out where HEAD holds it, removed where the writer created it. `(patch path,
    None)`, or `(None, why)`. Before the first revert the patch is made,
    written and checked to reverse to the tree, and HEAD's listing read; a
    failure there reverts nothing. A removal that fails after the checkout
    names the paths already put back, and the written patch holds them all."""
    patch, why = aside_patch(ctx, plan_paths)
    if why is not None:
        return None, why
    if not patch.strip():
        return None, "git shows no change of them against HEAD"
    hc, top, specs = aside_specs(ctx, plan_paths)
    path = set_aside_file(ctx, task)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(patch)
    except OSError as exc:
        return None, "the patch could not be written to %s (%s)" % (
            project_relative(ctx, path), exc)
    for argv in (["apply", "--check", "-R", path],
                 ["ls-tree", "-r", "-z", "--name-only", "HEAD", "--"] + specs):
        code, out, err = _git_literal(top, argv)
        if code != 0:
            return None, _git_said(argv, code, err)
    # `ls-tree` prints from its cwd, the top it ran in.
    held = set(hc.git_to_plan(p, top, ctx["project"], cwd=top)
               for p in out.decode("utf-8", "replace").split("\0") if p)
    tracked = [s for p, s in zip(plan_paths, specs) if p in held]
    if tracked:
        argv = ["checkout", "-q", "HEAD", "--"] + tracked
        code, _out, err = _git_literal(top, argv)
        if code != 0:
            return None, _git_said(argv, code, err)
    for plan, spec in zip(plan_paths, specs):
        if plan in held:
            continue
        try:
            os.remove(os.path.join(top, *spec.split("/")))
        except FileNotFoundError:
            pass
        except OSError as exc:
            return None, "%s could not be removed (%s), after %s was put back" % (
                plan, exc, ", ".join(tracked) or "nothing")
    return path, None


def settle_aside(ctx, state, phase, task, paths, code, text):
    """Set `paths` aside (`set_aside`), note them on the task, and stand the
    work on the tree that leaves: prove again where the proof's own reading
    moved (`prove_and_hold`), and measure the gate again, as the ledger records
    no list of what a gate run read and a reverted path may be one of them.
    None when the commit may be asked again, else the stop or the decision.
    Nothing is reverted, and the refusal `text` is relayed with why, when one of
    `paths` is plugin-owned or a clause the writer answered cites it."""
    owned = plugin_owned_paths(ctx, paths)
    plan_paths = aside_plan_paths(ctx, paths)
    why = (("%s %s plugin-owned state, which no set-aside reverts"
            % (", ".join(owned), "is" if len(owned) == 1 else "are"))
           if owned else aside_gap(ctx, state, phase, task, plan_paths))
    patch = None
    if why is None:
        patch, why = set_aside(ctx, task, plan_paths)
    if why is not None:
        return relay_refusal(ctx, "commit-task-work.py", code, "%s\n%s %s not set "
                             "aside: %s" % (text.rstrip("\n"), PREFIX,
                                            ", ".join(plan_paths), why))
    rel = project_relative(ctx, patch)
    said = ("set aside before the commit, outside the task's files: %s - the "
            "writer's change kept as %s (`git apply` it from the checkout's top to "
            "take it back) and put back to HEAD; the declared work is proved and "
            "gated again before it is committed" % (", ".join(plan_paths), rel))
    refused = note_task(ctx, task, said)
    ctx["did"].append("%s: %s%s" % (task["id"], said, "" if refused is None
                                    else " (not noted: %s)" % (refused,)))
    manifest, phase_now = load_phase(ctx)
    task_now = _mio.tasks_by_id(manifest).get(task["id"]) or task
    stop = prove_and_hold(ctx, state, manifest, phase_now, task_now,
                          "after the set-aside")
    if stop is not None:
        return stop
    _mark(state, "rerun", task_now)
    write_state(ctx, state)
    return gate_step(ctx, state, manifest, phase_now, task_now)


def writer_commit(ctx, state, phase, task):
    """`(sha, None)` for a commit made, `(None, None)` when there was nothing to
    commit, else `(None, stop)`: the writer path's `commit-task-work.py`. A
    refusal is read again through `--json` (`refusal_answer`); one whose whole
    reason is paths no in_progress task declares (`undeclared_split`) sets aside
    those clean at the start (`settle_aside`) and asks the commit once more. A
    path dirty before the attempt, or with no snapshot to tell, is never put
    back: the refusal is relayed naming it - after the clean ones are set aside
    and the work gated again, so a later close stands on that gate. Any other
    refusal is relayed in the verb's own words."""
    code, out, err = run_verb(ctx, "commit-task-work.py", commit_args(ctx, task))
    if code == 0:
        return committed_sha(out), None
    answer = refusal_answer(ctx, task)
    if isinstance(answer, dict) and answer.get("committed") and answer.get("commit") \
            and not answer.get("refused"):
        return str(answer["commit"]), None
    clean, held = undeclared_split(answer)
    said = ("\n%s %s not set aside: %s" % (
        PREFIX, ", ".join(aside_plan_paths(ctx, held)), HELD_ASIDE)) if held else ""
    if not clean:
        return None, relay_refusal(ctx, "commit-task-work.py", code,
                                   (out + err).rstrip("\n") + said)
    stop = settle_aside(ctx, state, phase, task, clean, code,
                        (out + err).rstrip("\n") + said)
    if stop is not None:
        return None, stop
    # Asked again, so a refusal relayed now names what the tree still holds.
    code, out, err = run_verb(ctx, "commit-task-work.py", commit_args(ctx, task))
    if code != 0:
        return None, relay_refusal(ctx, "commit-task-work.py", code,
                                   (out + err).rstrip("\n") + said)
    return committed_sha(out), None


def _attempt_start_moment(rows, task):
    """The moment of the newest `task.start` row of `task`'s current attempt,
    or None. It is the row `_scoped_commit.start_head_of` reads its head from,
    found by the same three fields."""
    moment = None
    for row in rows or []:
        details = row.get("details") if isinstance(row, dict) else None
        if (row.get("action") == "task.start" and isinstance(details, dict)
                and details.get("taskId") == task.get("id")
                and details.get("attempt") == task.get("attempts")):
            moment = _journal_io.row_moment(row)
    return moment


def _attempt_nonces(rows, task, began):
    """The `Audit-Row` nonces of `task`'s rows written at or after `began` (the
    attempt's start moment, epoch seconds), each once, in journal order, leaving
    out every nonce a withdrawal row took back. `>=` and not `>`: the trail's
    grain is a second, so a row written in the start's own second is on the
    attempt's side of it, and an earlier attempt's row in that second is kept
    out by the span, not by this."""
    withdrawn = _invariants.withdrawn_nonces(rows)
    nonces = []
    for row in rows:
        details = row.get("details") if isinstance(row, dict) else None
        if not isinstance(details, dict) or details.get("taskId") != task["id"]:
            continue
        moment = _journal_io.row_moment(row)
        if moment is None or moment < began:
            continue
        nonce = str(details.get(_invariants.NONCE_KEY) or "")
        if nonce and nonce not in withdrawn and nonce not in nonces:
            nonces.append(nonce)
    return nonces


def own_commit(ctx, task):
    """The SHA of the commit the drive already made of `task`'s work this
    attempt, or None: an in_progress task with no recorded commit, and a commit
    that
    - carries the `Audit-Row` trailer of a journal row of this attempt naming the
      task (`_attempt_nonces`; a row a withdrawal took back names none), in the
      last paragraph where the writer puts it (`trailer_carriers`), under the
      subject header a task commit opens with (`type(<taskId>): `, which a
      squash or a commit that absorbed the message does not), and
    - is the NEWEST commit of the attempt's span that changed a declared file
      (`_scoped_commit.attempt_span`, the one reader of that span).

    WHY THE COMMIT STEP CANNOT BE THE ONLY ANSWER. A close refused after the
    commit landed leaves the work committed and the task open; the commit step,
    asked again, finds nothing to commit and says so - which reads as a task
    that changed nothing. None here is "no such commit found", including when
    the start head or the journal cannot be read: the caller then keeps the
    decision it always made, and never claims a commit it could not name.

    WHY ONLY THE NEWEST ONE. A later commit that changed a declared file again
    - a revert is the plain case - means the tree no longer holds what the
    carrier committed, and closing on the carrier would record work that is not
    there. `attempt_span` is also what answers a start head that is no ancestor
    of HEAD (a rebase or a reset since): `touched` is then None, the span is
    unread, and a listing of everything since the merge base is never taken for
    the attempt's commits."""
    if task.get("status") != "in_progress" or task.get("commit"):
        return None
    try:
        rows = _journal_io.read_all(ctx["project"], ctx.get("config"))
    except Exception:                                          # noqa: BLE001
        return None
    start = _scoped_commit.start_head_of(rows, task)
    began = _attempt_start_moment(rows, task)
    if not start or began is None:
        return None
    names = [name for name, _rel in _scoped_commit.declared_work(
        task, ctx["project"], ctx["gitRoot"])]
    touched, _why = _scoped_commit.attempt_span(
        ctx["gitRoot"], ctx["project"], None, task, names, start)
    if not touched:
        return None
    carried, _why = _invariants.trailer_carriers(
        ctx["gitRoot"], _attempt_nonces(rows, task, began))
    if not carried:
        return None
    header = re.compile(r"^[^\s()]+\(%s\): " % (re.escape(str(task["id"])),))
    held = set(c["sha"] for found in carried.values() for c in found
               if c["inLast"] and header.match(c["subject"]))
    newest = touched[0][1]
    return newest if newest in held else None


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
    # THE DIGEST THE RED PROOF LOCKED BINDS THE COMMIT: a test file changed
    # after the filed proof is not the test that was watched failing, nor the
    # one the review read, so the commit is refused; only a new start proves
    # and files it again.
    changed = lock_moved(ctx, state, task)
    if changed:
        return decision(ctx, state, "tests-moved", task, ", ".join(changed),
                        extra={"changed": changed})
    if writer_path_on(ctx) and recorded_session(state, task):
        sha, stop = writer_commit(ctx, state, phase, task)
        if stop is not None:
            return stop
    else:
        out, stop = _verb_or_stop(ctx, "commit-task-work.py", commit_args(ctx, task))
        if stop is not None:
            return stop
        sha = committed_sha(out)
    if not sha:
        # A close refused after the commit landed leaves the work committed:
        # close on that commit through the same verb and checks, rather than
        # offer no-change (a false outcome) or retry (the work redone).
        sha = own_commit(ctx, task)
    if not sha:
        return decision(ctx, state, "no-change", task, "")
    extra = ["--commit", sha, "--from-return"]
    done_args = _task_args(ctx, "done", task["id"], *extra)
    if intent_basis is None:
        _out, stop = _verb_or_stop(ctx, "audit-task.py", done_args)
    else:
        _out, stop = _verb_with_text(
            ctx, "audit-task.py", done_args + ["--intent", "not-asked"],
            "--intent-basis", intent_basis)
    if stop is not None:
        return stop
    ctx["did"].append("%s %s at %s" % (CLOSED, task["id"], sha[:7]))
    stop = ci_after_close(ctx, state, phase)
    if stop is not None:
        return stop
    items = review_items(reviewer)
    if items:
        return decision(ctx, state, "review-answer", task, items)
    return None


def advance(ctx, state, manifest, phase, task, tree=None):
    """The next due step for the task the drive is on; None when the drive goes
    on to the next task, else what to print. `tree` is the task's own worktree
    when it runs in a wave: its gate is measured there, its stamp graded there,
    and its bytes are integrated into the phase tree before the close. A
    serial step (`tree` None) on a task whose kept tree stands is stopped
    instead: it would run the task in the phase tree, without its work."""
    if tree is None:
        stop = kept_tree_stop(ctx, state, task)
        if stop is not None:
            return stop
    # Before anything reads the session: a writer session that ended since the
    # last step leaves its cost on the task whatever the step does next, and a
    # session that has written nothing yet is waited for rather than graded -
    # neither as a writer that returned nothing nor by a gate over its tree.
    note_sessions(ctx, state, task)
    waiting = writer_wait(ctx, state, task)
    if waiting is not None:
        return waiting
    settled = writer_settle(ctx, state, manifest, phase, task, tree)
    if settled is not None:
        return settled
    executor, problem = filed(ctx, task, "executor")
    if problem:
        return E_STOPPED, "%s %s: stopped - %s" % (PREFIX, ctx["phase"], problem)
    if executor is None and writer_holds(state, task):
        # A WRITER'S RETURN IS FILED AT ITS GREEN GATE, with the proof held
        # since its session: a red gate goes back to the session, and the
        # return then carries the proof of the bytes it is filed with.
        if stored_green(ctx, state, manifest, task, "gated") != _evio.STORED_HOLDS:
            stop = gate_step(ctx, state, manifest, phase, task, tree)
            if stop is not None:
                return stop
        stop = file_writer_return(ctx, state, manifest, phase, task, tree)
        if stop is not None:
            return stop
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
            return dispatch(ctx, state, phase, task, "executor", tree)
        if _marked(state, "dispatched-executor", task):
            return decision(ctx, state, "no-executor-return", task, "")
        return dispatch(ctx, state, phase, task, "executor", tree)
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
            reviewer, stop = reviewer_session_step(ctx, state, manifest, phase,
                                                   task, tree)
            if stop is not None:
                return stop
            if reviewer is None:
                return decision(ctx, state, "no-reviewer-return", task, "")
    # THE RECORDED GATE RUNS ONCE PER START, BEFORE THE REVIEWER OR THE CLOSE,
    # whatever the key: a task whose review is carried to the phase still owes
    # the measurement its close and its commit are bound to - and again, past a
    # filed reviewer, when the green it stood on no longer answers the gate.
    green = stored_green(ctx, state, manifest, task, "gated")
    if green != _evio.STORED_HOLDS and (reviewer is None or not due
                                        or green == _evio.STORED_MOVED):
        stop = gate_step(ctx, state, manifest, phase, task, tree)
        if stop is not None:
            return stop
        ctx["did"].append(grade_stamp(ctx, executor.get("stamp"), tree)
                          if tree else grade_stamp(ctx, executor.get("stamp")))
    if due and reviewer is None:
        return dispatch(ctx, state, phase, task, "reviewer", tree)
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


def gate_step(ctx, state, manifest, phase, task, tree=None):
    """The task's recorded gate, once per start: None when it is green (and
    marked so), else the decision or stop a red or unrun gate asks."""
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
        return gate_red_decision(ctx, state, manifest, phase, task, out + err,
                                 tree)
    if code != 0:
        return relay_refusal(ctx, "run-test-gate.py", code, out + err)
    _mark(state, "gated", task, verdict_taken(ctx, out + err, tree))
    write_state(ctx, state)
    banners = gate_banners(out + err)
    ctx["did"].append("gate %s green%s" % (task["id"], " (%s)" % (
        "; ".join(banners),) if banners else ""))
    return None


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
    # `excluded` and the declared `files` are both project-relative, so the
    # digest reads them where the project is in the member's tree, not at the
    # top of its checkout.
    digest, basis = _tree_stamp.scope_digest(
        member_project(ctx, tree) or ctx["project"], task.get("files"),
        excluded=excluded)
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
        held = {"regate": regate, "followers": [f["path"] for f in followers]}
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
    if held.get("regate") is not False and stored_green(
            ctx, state, load_phase(ctx)[0], task, "regated") != _evio.STORED_HOLDS:
        code, out, err = task_gate(ctx, state, phase, task)
        if code == 1:
            said = [ln for ln in (out + err).splitlines() if "GATE" in ln]
            return decision(ctx, state, "gate-red", task, (
                "re-gate on the phase tree: %s" % (
                    said[0].strip() if said else "exit 1",))[:80],
                extra={"verdict": verdict_taken(ctx, out + err)})
        if code != 0:
            return relay_refusal(ctx, "run-test-gate.py", code, out + err)
        _mark(state, "regated", task, verdict_taken(ctx, out + err))
        write_state(ctx, state)
        ctx["did"].append("re-gate %s green" % (task["id"],))
    return None


def tree_holds_only_integrated(ctx, tree, records=(), followers=()):
    """True when every path the tree changed holds the bytes the phase tree
    holds - nothing in it would be lost with it; False when one differs; None
    when git could not say. A path under `records` is left out: those bytes
    are the phase tree's own committed records, put there by the refresh, and
    the phase tree's working copy of them moves on with every row it writes.
    So is a path in `followers`, one the integration took as a follower its
    owner's recipe writes: the phase tree's copy is that recipe's output over
    the phase tree - a sibling's change merged in moves it - so a member's
    copy differing from it is a stale render, not work the phase tree lacks."""
    skip = set(followers or ())
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
        if not rel or rel in skip or _invariants.is_record_path(rel, records):
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
    held = (((state.get("integrated") or {}).get(task["id"]) or {}).get("value")
            or {})
    followers = held.get("followers") if isinstance(held, dict) else None
    clean = tree_holds_only_integrated(ctx, tree, wave.get("records"),
                                       followers or ()) \
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


# --- a filed member's work, carried in a ref -----------------------------------
# A wave member's bytes live in its tree until the drive integrates them. A hand
# off that moves machines takes the records and not the tree, so the plan reads
# "filed" while the work is gone. The filing therefore leaves the work in a ref
# of the repository (objects are shared with the trees) and pushes it to the
# remote, and the next tree cut for a member whose return is filed starts from it.
CARRY_NS = "refs/audit/carry/"
CARRY_REMOTE = "origin"
CARRY_IDENT = {"GIT_AUTHOR_NAME": "audit-carry", "GIT_COMMITTER_NAME": "audit-carry",
               "GIT_AUTHOR_EMAIL": "audit-carry@localhost",
               "GIT_COMMITTER_EMAIL": "audit-carry@localhost"}


def carry_ref(task_id):
    """The ref holding a task's carried work."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", str(task_id)).strip(".-") or "task"
    return CARRY_NS + safe


def carry_git(where, argv, env=None, stdin=None):
    """`(code, stdout_bytes, stderr_text)` of one git call in `where`; code 127
    and the exception's name when git could not be started."""
    try:
        done = subprocess.run(["git", "-C", where] + list(argv), input=stdin,
                              env=env, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, b"", exc.__class__.__name__
    return done.returncode, done.stdout, _clip(
        done.stderr.decode("utf-8", "replace").strip(), 120)


def carry_commit(tree, records, task_id):
    """`(sha, why)` - a commit on HEAD of `tree` holding everything the tree
    changed, untracked files included and the record paths left out (those are
    the phase tree's own, put there by the refresh). Built in a scratch index, so
    the tree's index, HEAD and files are untouched; `sha` is None beside the
    reason git could not say."""
    scratch = tempfile.mkdtemp(prefix="audit-carry-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(scratch, "index"),
                   **CARRY_IDENT)
        for argv in (["read-tree", "HEAD"], ["add", "-A"]):
            code, _out, err = carry_git(tree, argv, env)
            if code != 0:
                return None, err or "git %s exited %d" % (argv[0], code)
        code, out, err = carry_git(tree, ["diff", "--cached", "--name-only", "-z",
                                          "HEAD"], env)
        if code != 0:
            return None, err or "git diff exited %d" % (code,)
        names = [n.decode("utf-8", "replace") for n in out.split(b"\0") if n]
        records_in = [n for n in names if _invariants.is_record_path(n, records)]
        for at in range(0, len(records_in), 100):
            code, _out, err = carry_git(tree, ["reset", "-q", "HEAD", "--"]
                                        + records_in[at:at + 100], env)
            if code != 0:
                return None, err or "git reset exited %d" % (code,)
        code, out, err = carry_git(tree, ["write-tree"], env)
        if code != 0:
            return None, err or "git write-tree exited %d" % (code,)
        code, head, err = carry_git(tree, ["rev-parse", "HEAD"], env)
        if code != 0:
            return None, err or "git named no HEAD"
        code, out2, err = carry_git(tree, [
            "commit-tree", out.decode("utf-8").strip(), "-p",
            head.decode("utf-8").strip(), "-m", "work of %s" % (task_id,)], env)
        if code != 0:
            return None, err or "git commit-tree exited %d" % (code,)
        return out2.decode("utf-8").strip(), ""
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def carry_pushes(ctx):
    """Whether the project asked for carries to travel: `ci.pushCarry` is true.
    A value the config rules refuse reads as no, not as yes - the unreadable
    setting is said by `carry_work`, and the validator and the doctor name it."""
    push, _problem = _config_rules.carry_push_setting(ctx["config"])
    return push is True


def carry_remote(ctx):
    """The remote the carry travels by, or None when the carry travels by none:
    the project did not set `ci.pushCarry`, or the repository has no `origin`.
    Every contact with the remote - the push, the fetch that finds a carry made
    elsewhere, the delete that takes one down - asks here, so the opt-in is read
    in one place and a default drive starts no git call that names a remote."""
    if not carry_pushes(ctx):
        return None
    code, out, _err = carry_git(ctx["gitRoot"], ["remote"])
    names = out.decode("utf-8", "replace").split() if code == 0 else []
    return CARRY_REMOTE if CARRY_REMOTE in names else None


def carry_work(ctx, task, tree, records):
    """Leave a filed member's work in `refs/audit/carry/<id>` and push it. What
    could not be done is said on the did-line, never raised and never silent:
    the filing stands, but the work then lives in the tree alone."""
    sha, why = carry_commit(tree, records, task["id"])
    if sha is None:
        ctx["did"].append("work of %s not carried: %s" % (task["id"], why))
        return
    ref = carry_ref(task["id"])
    code, _out, err = carry_git(ctx["gitRoot"], ["update-ref", ref, sha])
    if code != 0:
        ctx["did"].append("work of %s not carried: update-ref %s" % (task["id"], err))
        return
    if not carry_pushes(ctx):
        _push, problem = _config_rules.carry_push_setting(ctx["config"])
        ctx["did"].append("work of %s carried in %s, local only: %s, so it does "
                          "not travel to another machine" % (
                              task["id"], ref, _clip(problem, 100) if problem else
                              "nothing is pushed unless ci.pushCarry is true"))
        return
    remote = carry_remote(ctx)
    if remote is None:
        ctx["did"].append("work of %s carried in %s, local only: the repository "
                          "has no %s, so it does not travel to another machine"
                          % (task["id"], ref, CARRY_REMOTE))
        return
    code, _out, err = carry_git(ctx["gitRoot"], ["push", "-q", remote,
                                                 "+%s:%s" % (ref, ref)])
    ctx["did"].append("work of %s carried in %s%s" % (
        task["id"], ref, (" and pushed to %s" % (remote,)) if code == 0 else
        ", local only: the push to %s failed (%s)" % (remote, err)))


def carried_commit(ctx, task_id):
    """The commit `refs/audit/carry/<id>` names here, fetched from the remote
    when this repository does not hold it; None when neither has it."""
    ref = carry_ref(task_id)
    for fetch in (False, True):
        if fetch:
            remote = carry_remote(ctx)
            if remote is None or carry_git(ctx["gitRoot"], [
                    "fetch", "-q", remote, "+%s:%s" % (ref, ref)])[0] != 0:
                return None
        code, out, _err = carry_git(ctx["gitRoot"], [
            "rev-parse", "--verify", "--quiet", ref + "^{commit}"])
        if code == 0 and out.strip():
            return out.decode("utf-8").strip()
    return None


def restore_carry(ctx, task, tree):
    """Put the work a filed member left in its carry ref into `tree`, a tree cut
    fresh for it. Only for a member whose return is filed for its current start,
    and only into a tree that holds nothing yet, so a carry from an earlier
    attempt, or a tree adopted with its work, is never laid over. Said on the
    did-line either way; the gate that follows is what measures the result."""
    if not already_filed(ctx, task):
        return
    sha = carried_commit(ctx, task["id"])
    if sha is None:
        where = ("here or on %s" % (CARRY_REMOTE,) if carry_pushes(ctx) else
                 "here (carries are pushed only under ci.pushCarry, so one "
                 "filed on another machine did not travel)")
        ctx["did"].append("%s is filed and its tree is new, and no %s exists %s: "
                          "the work cannot be recovered" % (
                              task["id"], carry_ref(task["id"]), where))
        return
    code, out, err = carry_git(tree, ["status", "--porcelain", "--untracked-files=all"])
    if code != 0 or out.strip():
        ctx["did"].append("tree of %s already holds changes, so its carry is not "
                          "applied%s" % (task["id"], (": " + err) if err else ""))
        return
    code, patch, err = carry_git(tree, ["diff", "--binary", sha + "^", sha])
    if code != 0:
        ctx["did"].append("carry of %s unreadable: %s" % (task["id"], err))
        return
    if patch:
        code, _out, err = carry_git(tree, ["apply", "--binary", "--whitespace=nowarn"],
                                    stdin=patch)
        if code != 0:
            ctx["did"].append("carry of %s does not apply to its tree: %s"
                              % (task["id"], err))
            return
    ctx["did"].append("work of %s restored from %s" % (task["id"], carry_ref(task["id"])))


def drop_carry(ctx, task_id):
    """Take a closed task's carry down, here and on the remote. Nothing is run
    for a task that left none."""
    ref = carry_ref(task_id)
    if carry_git(ctx["gitRoot"], ["rev-parse", "--verify", "--quiet", ref])[0] != 0:
        return
    carry_git(ctx["gitRoot"], ["update-ref", "-d", ref])
    remote = carry_remote(ctx)
    if remote is not None:
        code, _out, err = carry_git(ctx["gitRoot"], ["push", "-q", remote, ":" + ref])
        if code != 0:
            ctx["did"].append("carry of %s dropped here, not on %s (%s)" % (
                task_id, remote, err))


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
            drop_carry(ctx, task_id)
            stop = retire_member(ctx, state, task)
            return ("stop", stop) if stop is not None else ("idle", None)
        if status == "blocked":
            return "idle", None
        parked = (state["wave"].get("parked") or {}).get(task_id)
        if parked is not None:
            if pending_still_applies(ctx, manifest, parked):
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
            restore_carry(ctx, task, tree)
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
        if pending_still_applies(ctx, manifest, parked[task_id]):
            state["pending"] = parked.pop(task_id)
            write_state(ctx, state)
            return render_decision(ctx, state["pending"])
    if all((by_id.get(t) or {}).get("status") in _mio.TERMINAL + ("blocked",)
           for t in state["wave"]["tasks"]):
        close_wave(ctx, state, manifest)
    return None


def carried_members(ctx, phase):
    """The ids of the in-progress tasks that were wave members whose state this
    machine lacks: each one's executor return is filed for its current start and
    its work waits in a carry ref. Asked only where no wave is recorded and the
    width allows one - a carry is left only by a wave member, so a drive that
    never ran a wave asks nothing of the remote."""
    return sorted((t["id"] for t in _tasks(phase)
                   if t.get("status") == "in_progress" and already_filed(ctx, t)
                   and carried_commit(ctx, t["id"])), key=_id_key)


def kept_tree(state, task):
    """The tree a closed wave kept for `task` when it still stands on disk, else
    None. A blocked member's finished work stays in that tree after its wave
    closes, so a run of the task anywhere else - the phase tree above all -
    measures and commits bytes that are not its work."""
    path = (state.get("keptTrees") or {}).get(task.get("id"))
    return path if isinstance(path, str) and os.path.isdir(path) else None


def kept_members(state, phase):
    """The ids of the in-progress tasks whose kept tree still stands: each was
    a wave member blocked or left behind and then started again by hand, which
    makes a task `in_progress` with no wave recorded to run it in."""
    return sorted((t["id"] for t in _tasks(phase)
                   if t.get("status") == "in_progress" and kept_tree(state, t)),
                  key=_id_key)


def kept_marker(path, task_id):
    """`(True, basis)` when the kept tree at `path` carries the marker naming
    `task_id` - the one `manage-worktrees.py task-add` adopts a tree by - else
    `(False, why)`. A wave opened over a tree without it would not adopt the
    tree: `task-add` would cut a fresh one and leave the work orphaned there."""
    held = _worktrees.read_provenance(path, expect_task=str(task_id))
    return held.get("ours") is True, held.get("basis") or ""


def unmarked_kept_stop(ctx, state, kept):
    """The stop for the kept members whose tree lacks its marker, or None."""
    unmarked = []
    for tid in kept:
        path = state["keptTrees"][tid]
        ours, why = kept_marker(path, tid)
        if not ours:
            unmarked.append((tid, path, why))
    if not unmarked:
        return None
    return _stopped(ctx, "%s: the kept tree holding the task's work from an "
                    "earlier wave carries no marker naming the task, so a wave "
                    "would cut a fresh tree beside it rather than adopt it, and "
                    "the serial step would run the task in the phase tree "
                    "without that work. Carry the tree's diff into the phase "
                    "tree and remove the tree, then drive the phase again"
                    % ("; ".join("%s's tree at %s (%s)" % (tid, path, why)
                                 for tid, path, why in unmarked),))


def kept_tree_stop(ctx, state, task):
    """The stop for a serial step on a task whose kept tree stands, or None.
    Every serial step runs in the phase tree, so it is never taken for such a
    task: the work in the tree would be left out of the gate and the close."""
    path = kept_tree(state, task)
    if path is None:
        return None
    return _stopped(ctx, "%s has a kept tree at %s holding its work from an "
                    "earlier wave, and this step would run it in the phase tree "
                    "instead - dispatched, gated and closed without that work. "
                    "Drive the phase (next %s) at executor.waveWidth 2 or more, "
                    "which runs it in that tree when its marker names the task, "
                    "or carry the tree's diff into the phase tree and remove the "
                    "tree" % (task["id"], path, ctx["phase"]))


def wave_step(ctx, state, manifest, phase, width, basis):
    """The wave's step: walk the one open, else open one when no task is in
    progress and `_wave.select` picks two or more ready tasks. NO_WAVE when
    neither applies, so the serial step runs."""
    if not state.get("wave"):
        if width < 2:
            return NO_WAVE
        carried = carried_members(ctx, phase)
        if carried:
            ctx["did"].append("wave resumed over %s: no wave is recorded here, and "
                              "their filed work waits in carry refs" % (
                                  ", ".join(carried),))
            return open_wave(ctx, state, carried, width, basis)
        # AHEAD OF THE IN-PROGRESS TEST BELOW: a hand `start` on a blocked
        # member makes it in_progress with no wave, and that test would hand it
        # to the serial step, in the phase tree, while its work sits in its tree.
        kept = kept_members(state, phase)
        stop = unmarked_kept_stop(ctx, state, kept) if kept else None
        if stop is not None:
            return stop
        if kept:
            ctx["did"].append("wave resumed over %s: started again with no wave "
                              "recorded, its work waits in its kept tree (%s)" % (
                                  ", ".join(kept), ", ".join(
                                      state["keptTrees"][t] for t in kept)))
            return open_wave(ctx, state, kept, width, basis)
        if any(t.get("status") == "in_progress" for t in _tasks(phase)):
            return NO_WAVE
        ready = set(_status_facts.ready_tasks(manifest))
        picked = _wave.select(sorted((t for t in _tasks(phase) if t["id"] in ready),
                                     key=lambda t: _id_key(t["id"])), width,
                              red_at_base=red_at_base(
                                  ctx, sorted(ready), gate_step_names(
                                      manifest, phase, ready))[0])["wave"]
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
        _out, stop = _verb_with_text(
            ctx, "audit-task.py", _task_args(ctx, "block", task["id"]),
            "--reason", reason)
        if stop is not None:
            return stop
        ctx["did"].append("blocked %s" % (task["id"],))
        return keep_record(ctx, phase)
    if answer == "close":
        accept_scope(ctx, state, task, reason)
        ctx["did"].append("%s: scope change accepted (%s)" % (
            task["id"], _clip(reason, 80)))
        return None
    if answer == "recheck":
        # The settle runs again: a commit a human took out of history leaves
        # HEAD back at the dispatch, and the work is proved and held as usual.
        return None
    if answer == "file":
        # HEAD moved by commits that are not the session's, or git could not
        # name it: the dispatch is read as made at HEAD as it is now, and the
        # work is proved against that (the filing re-proves whatever moved).
        held = writer_state(state, task)
        tree = ((state.get("wave") or {}).get("trees") or {}).get(task["id"])
        if held["dispatches"]:
            held["dispatches"] = held["dispatches"][:-1] + [
                dict(held["dispatches"][-1], head=tree_head(ctx, tree))]
            _mark(state, "writer", task, held)
            write_state(ctx, state)
        return None
    if answer == "resume" and pending["decision"] in RESUME_KINDS:
        # The task is not re-started, so no attempt is spent; the gate is not
        # marked as run, so the next `next` measures the session's fix. A
        # clause gap is asked at a GREEN gate, whose mark is spent here for it.
        _spend(state, "gated", task)
        return resume_writer(ctx, state, task, pending, (
            (state.get("wave") or {}).get("trees") or {}).get(task["id"]))
    if answer == "resume":
        # The dispatch mark stays, so a return still unfiled is asked about
        # again on the next `next`; no attempt is spent.
        return resume_said(ctx, task["id"])
    if answer == "rerun":
        # The gate is not marked as run for this start, so the drive measures
        # again - with `--no-reuse`, through the mark `task_gate` spends - and
        # the task is not re-started, so no attempt is spent. A wave member
        # parked red on the same steps is measured with it, never replayed.
        _mark(state, "rerun", task)
        write_state(ctx, state)
        rerun_alongside(ctx, state, manifest, pending)
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
            stop = commit_scope_index(ctx, "%s widened by %s" % (
                task["id"], pending["config"]))
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
        # A reviewer session reads the tree it runs in, and records that tree's
        # HEAD: a wave member's is its own, as the first dispatch ran it.
        return dispatch(ctx, state, phase, task, "reviewer", (
            (state.get("wave") or {}).get("trees") or {}).get(task["id"]))
    if answer == "not-asked":
        return close_task(ctx, state, phase, task, intent_basis=reason)
    if answer == "confirm":
        _mark(state, "confirmed", task)
        write_state(ctx, state)
        return None
    if answer == "no-change":
        _out, stop = _verb_with_text(
            ctx, "audit-task.py",
            _task_args(ctx, "done", task["id"], "--no-change"), "--reason", reason)
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


# A decision parked because a role's return was missing: `no-<role>-return`.
_NO_RETURN = re.compile(r"^no-(.+)-return$")


def parked_return_role(decision_name):
    """The role whose filed return a `no-<role>-return` decision is waiting on,
    else None. The role comes off the name and is held to `_fr.RETURN_ROLES`,
    so a role added there is covered by `pending_still_applies` with no second
    edit; a name of that shape naming no task role (the phase review's, which
    belongs to no task) reads None and is the sign-off's."""
    hit = _NO_RETURN.match(decision_name or "")
    return hit.group(1) if hit and hit.group(1) in _fr.RETURN_ROLES else None


def pending_still_applies(ctx, manifest, pending):
    """A decision about a task that was since closed, cancelled or re-started by
    hand is about a state that no longer exists - and so is a no-<role>-return
    decision once that role's return is filed for the start it was raised for:
    the task is in progress under the same start, so the status and the start
    alone keep it, and a parked one would stop the drive on a line about a
    return that is there. A decision standing on a gate run is about that run,
    so it no longer applies once the run stops answering the gate
    (`gate_basis_holds`). A triage showing a phase review's findings as notes
    stands on the HEAD they were sorted at, and no longer applies once HEAD
    moved: the next triage sorts - and validates - them over the code as it
    is. Every path that shows a waiting decision - printed again, a member's
    parked one, `explain` - asks here."""
    if not pending.get("task"):
        return not pending.get("noted") or pending.get("notedHead") == git_head(ctx)
    task = _mio.tasks_by_id(manifest).get(pending["task"]) or {}
    if pending["decision"] == "review-answer":
        return True
    if pending["decision"] == "scope-gap":
        return task.get("status") == "pending"
    if not (task.get("status") == "in_progress"
            and start_key(task) == pending.get("start")):
        return False
    role = parked_return_role(pending["decision"])
    if role is not None:
        return role_return_filed(ctx, task, role) is None
    return gate_basis_holds(ctx, manifest, pending)


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
            text = fh.read()
    except OSError:
        text = ""
    head = _BRIEF_HEAD.search(text)
    if not head:
        return relay_refusal(ctx, "audit-lookup.py", 0,
                             "%s\n(the driver found no brief naming a head in "
                             "this)" % (out,))
    state["phaseReview"] = {"head": head.group(1)}
    write_state(ctx, state)
    model = (phase.get("review") or {}).get("model") or "unset"
    cut = _BRIEF_SLICE.findall(text)
    if not cut:
        return dispatch_said(ctx, "phase", phase["id"], REVIEWER_AGENT, model,
                             project_relative(ctx, brief))
    # A brief past the reader budget: a slice return left by an earlier dispatch
    # at this head is dropped, so this round is the one the last slice completes.
    for held in slice_return_paths(ctx, phase["id"], head.group(1)):
        os.remove(held)
    return dispatch_said(ctx, "phase", phase["id"], REVIEWER_AGENT, model,
                         [project_relative(ctx, path.strip())
                          for _n, _total, path in cut])


# --- a phase review cut into slices ---------------------------------------------
def state_root(ctx):
    """The state directory the briefs and the driver's state sit under: the one
    `next` resolved, or - for `submit`, which resolves no phase first - the
    hooks' own reading of it for this project."""
    if "stateDir" not in ctx:
        hc = _loader.load_hooks_config(modname="audit__config")
        ctx["stateDir"] = str(hc.state_dir(pathlib.Path(ctx["project"]),
                                           ctx["config"] or {}))
    return ctx["stateDir"]


def slice_return_paths(ctx, phase_id, head, number=None):
    """The slice returns held for the phase brief at `head`, in slice order -
    or, with `number`, the one path that slice's return is held at."""
    base = _fr.shown_brief_path(state_root(ctx), phase_id, head)[:-len(".json")]
    if number is not None:
        return "%s.slice%d.return.json" % (base, number)
    folder, name = os.path.split(base)
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.startswith(name + ".slice") and n.endswith(".return.json"))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names]


def slices_record(ctx, phase_id, head):
    """`(slices, None)` - the `slices` list the phase brief at `head` recorded
    beside its shown set - or `(None, why)` when it was not written as slices."""
    path = _fr.shown_brief_path(state_root(ctx), phase_id, head)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "the record of the brief at head %s cannot be read (%s)" % (
            head[:12], exc)
    slices = body.get("slices") if isinstance(body, dict) else None
    if not isinstance(slices, list) or not slices:
        return None, ("the phase brief at head %s was not written as slices, so "
                      "`--slice` has nothing to file against" % (head[:12],))
    return slices, None


def aggregate_slice_returns(bodies):
    """The one phase return the slice returns `bodies` make, in slice order:
    their findings and pre-existing findings numbered afresh (every slice
    numbers from one), their `tasks` entries joined, the verdict `findings` when
    any slice found something, and the intent of the slice that answered worst
    - its notes and missing inputs joined - standing for the phase."""
    def joined(key):
        items = [item for body in bodies for item in body.get(key) or []]
        return [dict(item, id=n) for n, item in enumerate(items, 1)]

    def rank(intent):
        word = intent.get("answer")
        return (INTENT_WORST_FIRST.index(word) if word in INTENT_WORST_FIRST
                else len(INTENT_WORST_FIRST))

    intents = [body.get("intent") or {} for body in bodies]
    intent = dict(min(intents, key=rank))
    intent["note"] = " | ".join("slice %d: %s" % (n, one.get("note") or "")
                                for n, one in enumerate(intents, 1))
    if any("missing" in one for one in intents):
        intent["missing"] = sorted(set(m for one in intents
                                       for m in one.get("missing") or []))
    findings = joined("findings")
    out = {"findings": findings, "intent": intent,
           "verdict": "findings" if findings or any(
               body.get("verdict") == "findings" for body in bodies) else "clean",
           "tasks": [entry for body in bodies for entry in body.get("tasks") or []]}
    if any("preExisting" in body for body in bodies):
        out["preExisting"] = joined("preExisting")
    return out


def take_slice(ctx, phase, args, body):
    """`(aggregated, None)` once this slice's return is the last of its brief's,
    `(None, None)` while others are outstanding, or `(None, stop)` when the
    return is refused - nothing held then. A slice return is held to what its
    slice recorded: the `--shown` set it was briefed with and an entry for each
    task it is owed, no other."""
    spec = _SLICE_SPEC.match(args.slice or "")
    head = whole_head(ctx, args.head)
    if not spec or not head:
        return None, _stopped(ctx, "`--slice` is `<n>/<total>` and goes with the "
                              "`--head` the slice's brief prints. Nothing filed.")
    number, total = int(spec.group(1)), int(spec.group(2))
    record, why = slices_record(ctx, phase["id"], head)
    if record is None:
        return None, _stopped(ctx, "%s. Nothing filed." % (why,))
    if total != len(record) or not 1 <= number <= total:
        return None, _stopped(ctx, "slice %s names no slice of the %d that brief "
                              "was written as. Nothing filed." % (args.slice, len(record)))
    mine = record[number - 1]
    held = slice_return_paths(ctx, phase["id"], head, number)
    if os.path.exists(held):
        return None, _stopped(ctx, "slice %d/%d of the review at head %s is "
                              "already filed and stays as filed. Nothing filed."
                              % (number, total, head[:12]))
    given, bad = (_fr.parse_shown(args.shown) if args.shown is not None
                  else (None, None))
    recorded = [(e.get("id"), e.get("commit")) for e in mine.get("shown") or []]
    refusal = bad or _fr.shown_brief_refusal(
        recorded, given, _fr.shown_brief_path(state_root(ctx), phase["id"], head),
        head)
    problems = [refusal] if refusal else []
    entries = [e for e in body.get("tasks") or [] if isinstance(e, dict)]
    answered = sorted(str(e.get("id")) for e in entries)
    if answered != sorted(mine.get("owed") or []):
        problems.append("the `tasks` entries answer %s and slice %d/%d is owed "
                        "%s" % (", ".join(answered) or "no task", number, total,
                                ", ".join(mine.get("owed") or []) or "no task"))
    problems += submitted_shape("reviewer", body, [])
    if problems:
        return None, _stopped(ctx, "the slice return does not file. Nothing "
                              "filed:\n%s" % ("\n".join("  " + p for p in problems)))
    os.makedirs(os.path.dirname(held), exist_ok=True)
    with open(held, "w", encoding="utf-8", newline="") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")
    ctx["did"].append("slice %d/%d of the phase review held" % (number, total))
    bodies = []
    for n in range(1, total + 1):
        try:
            with open(slice_return_paths(ctx, phase["id"], head, n), "r",
                      encoding="utf-8") as fh:
                bodies.append(json.load(fh))
        except (OSError, ValueError):
            return None, None
    ctx["did"].append("all %d slices in, one phase return aggregated" % (total,))
    return aggregate_slice_returns(bodies), None


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
    for f in pending.get("noted") or []:
        lines.append(_clip("  %s - a note, not a block: %s" % (f.get("id"), f.get("why")),
                           TRIAGE_LINE_BYTES))
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
    held = review_findings_step(ctx, state, phase, review)
    if held is not None:
        return held
    manifest, phase = load_phase(ctx)
    still, handed = triage_findings(phase)
    carried = carried_now(state, phase)
    noted = noted_now(ctx, state, phase)
    still = [f for f in still if f.get("id") not in carried and f.get("id") not in noted]
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
                         for fid, to in sorted(carried.items())],
             "noted": [{"id": fid, "why": why} for fid, why in sorted(noted.items())]}
    if noted:
        # The notes stand on the code they were sorted over: the triage
        # showing them holds only while HEAD is that commit
        # (`pending_still_applies`).
        extra["notedHead"] = (state.get(NOTED_FIELD) or {}).get("head")
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


# --- a phase-review finding, validated and handed back to its writer ----------
def finding_list(ids):
    """Finding ids as one comma-joined word, `none` for no id: a finding id
    holds no `.`, so `join_ids`' shortening never applies to one."""
    return ",".join(str(i) for i in ids) or "none"


def cited_ranges(file_field):
    """`[(path, first, last)]` - every line range a finding's `file` cites, in
    the spellings a reviewer writes: `path:291-294,308`, `path:L5`,
    `path#L5-L7`, `path line 5`, `path (lines 5-6)`. A path with no line, or a
    word that is no path, cites no line."""
    out = []
    for hit in _CITED.finditer(str(file_field or "").replace("\\", "/")):
        path = hit.group(1)
        if "." not in path and "/" not in path:
            continue
        for part in hit.group(2).replace("L", "").split(","):
            bounds = [int(b) for b in re.split(r"\s*[-–]\s*", part.strip()) if b]
            if bounds and min(bounds) >= 1:
                out.append((path, min(bounds), max(bounds)))
    return out


def commit_hunks(ctx, sha, path, cache=None):
    """`((new, old), None)` - the line ranges `sha`'s own diff of `path` shows,
    on its new side and its old side, in the coordinates of that diff (`git
    show`, the comparison a phase brief prints for the task, three lines of
    context) - or `(None, why)` when git could not say. `cache` keeps one
    answer per `(sha, path)` for the call that passes it."""
    key = (sha, path)
    if cache is not None and key in cache:
        return cache[key], None
    # The cite is project-relative and git reads a pathspec from the checkout's
    # top: one base, through the plan's own pair, or a nested project's path
    # names nothing. A path outside the checkout is in no task's diff.
    top = ctx.get("gitRoot") or ctx["project"]
    spec = _loader.load_hooks_config(modname="audit__config").plan_to_git(
        path, top, ctx["project"])
    if spec is None:
        return ([], []), None
    try:
        done = subprocess.run(
            ["git", "-C", top, "show", "--format=", "--no-color",
             "--no-ext-diff", "--no-renames", sha, "--", spec],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "git show could not run (%s)" % (exc,)
    if done.returncode != 0:
        return None, "git show %s -- %s exited %d: %s" % (
            sha[:12], path, done.returncode, _clip(done.stderr.strip(), 160))
    new, old = [], []
    for hit in _HUNK.finditer(done.stdout):
        for side, start, count in ((old, hit.group(1), hit.group(2)),
                                   (new, hit.group(3), hit.group(4))):
            count = 1 if count is None else int(count)
            if count:
                side.append((int(start), int(start) + count - 1))
    if cache is not None:
        cache[key] = (new, old)
    return (new, old), None


def task_commits(phase, carried):
    """`{sha: task id}` - each commit a task of the phase records, and each
    one `carried` names: a commit a task held before a re-open cleared it."""
    held = dict(carried or {})
    held.update((str(t["commit"]), t["id"]) for t in _tasks(phase) if t.get("commit"))
    return held


def reopen_record(ctx, phase):
    """`(carried, handed, None)` off the journal's `task.reopen` rows for the
    phase - `carried` `{sha: task id}`, the commit each re-open cleared, and
    `handed` `{finding id: [task id, ...]}`, one entry per hand-back the drive
    made, read off the reason it writes - or `(None, None, why)` when the
    journal cannot be read. The journal, not the drive's state, because the
    state file can be lost and the commit a task carried is then nowhere else."""
    try:
        rows = _journal_io.read_all(ctx["project"])
    except Exception as exc:                                   # noqa: BLE001
        return None, None, "the journal could not be read (%s)" % (exc,)
    ids = set(t.get("id") for t in _tasks(phase))
    carried, handed = {}, {}
    for row in rows:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        tid = details.get("taskId")
        if row.get("action") != TASK_REOPEN or tid not in ids:
            continue
        carried.update((str(c.get("from")), tid) for c in details.get("changes") or []
                       if isinstance(c, dict) and c.get("field") == "commit"
                       and c.get("from"))
        mine = _REOPEN_IDS.match(str(details.get("reason") or ""))
        for fid in (mine.group(1).split(",") if mine else []):
            handed.setdefault(fid, []).append(tid)
    return carried, handed, None


def _overlap(first, last, ranges):
    return sum(max(0, min(last, b) - max(first, a) + 1) for a, b in ranges)


def finding_owners(ctx, commits, finding, cache=None):
    """`(owners, None)` - the tasks whose own diff, as the phase brief showed
    it, holds a line the finding cites, the most cited lines first and then by
    id - or `(None, why)` when git could not say. The cite is read in each
    task's own coordinates, not HEAD's: a later task that moved the lines
    leaves them the earlier task's. A diff's new side is read first; its old
    side - a deleted line, a deleted file - only when no new side holds the
    cite. `[]` when no task's diff holds it, which is no evidence about the
    finding: the caller validates it like any other."""
    ranges = cited_ranges(finding.get("file"))
    new_counts, old_counts = {}, {}
    for sha, tid in sorted(commits.items()):
        for path, first, last in ranges:
            hunks, why = commit_hunks(ctx, sha, path, cache)
            if hunks is None:
                return None, why
            new_counts[tid] = new_counts.get(tid, 0) + _overlap(first, last, hunks[0])
            old_counts[tid] = old_counts.get(tid, 0) + _overlap(first, last, hunks[1])
    counts = new_counts if any(new_counts.values()) else old_counts
    return sorted([t for t, n in counts.items() if n],
                  key=lambda t: (-counts[t], _id_key(t))), None


def held_verdict(state, fid, head):
    """The validation verdict held for finding `fid`, only while HEAD is still
    the commit it was given at; None otherwise."""
    held = (state.get(VERDICTS_FIELD) or {}).get(fid)
    return held if isinstance(held, dict) and held.get("head") == head else None


def fixed_by(phase, handed, fid):
    """The task a withdrawn finding was fixed by: the last task it was handed
    back to, once that task is done again at a commit of its own - the pass
    then re-read the fix and found the defect gone. None otherwise, and the
    withdrawal is a note."""
    tasks = dict((t["id"], t) for t in _tasks(phase))
    tid = (handed.get(fid) or [None])[-1]
    task = tasks.get(tid) or {}
    return tid if task.get("status") == "done" and task.get("commit") else None


def sort_findings(ctx, state, phase, head, record):
    """`(sorted, None)` over the open findings no live fix task holds, or
    `(None, why)` when git could not place a confirmed one. `record` is
    `(commits, handed)`: `task_commits` and `reopen_record`'s hand-backs.

    ONE RULE: A FINDING IS A NOTE ONLY ON POSITIVE EVIDENCE - it is low, or the
    validation pass withdrew it, or confirmed it as a kind that does not block.
    The drive failing to place a finding is never a reason: a finding no pass
    has judged at `head` is a `candidate`, whatever it cites. `sorted` holds
    `notes` `{id: why}`, `candidates`, `fixed` `[(finding, task id)]` - withdrawn
    once handed back and re-checked - `blocking` `[(finding, owners)]`, each
    confirmed as a blocking kind in a task's diff, and `unowned`: confirmed as a
    blocking kind in lines no task's diff holds, which only a human settles."""
    commits, handed = record
    out = {"notes": {}, "candidates": [], "fixed": [], "blocking": [], "unowned": []}
    cache = {}
    for finding in open_findings(phase):
        fid = finding["id"]
        if live_fix_task(phase, finding):
            continue
        verdict = held_verdict(state, fid, head)
        if finding.get("severity") == CARRY_SEVERITY:
            out["notes"][fid] = ("a low finding: only a confirmed correctness or "
                                 "requirement finding blocks")
        elif verdict is None:
            out["candidates"].append(finding)
        elif verdict.get("verdict") == "withdrawn" and fixed_by(phase, handed, fid):
            out["fixed"].append((finding, fixed_by(phase, handed, fid)))
        elif verdict.get("verdict") == "withdrawn":
            out["notes"][fid] = ("the validation pass withdrew it at %s: %s"
                                 % (head[:12], verdict.get("basis")))
        elif verdict.get("kind") not in BLOCKING_KINDS:
            out["notes"][fid] = ("the validation pass confirmed it as %s, which "
                                 "does not block: %s" % (verdict.get("kind"),
                                                         verdict.get("basis")))
        else:
            owners, why = finding_owners(ctx, commits, finding, cache)
            if owners is None:
                return None, "%s: %s" % (fid, why)
            out["blocking" if owners else "unowned"].append(
                (finding, owners) if owners else finding)
    return out, None


def noted_now(ctx, state, phase, head=None):
    """`{finding id: why}` of the notes the last sort made, while HEAD is still
    the commit it sorted at and each finding is still open; `{}` once HEAD
    moved, so a note is never shown over code it did not judge - and `{}`
    without a writer session, the only route that makes a note: one an earlier
    run left in the state is not honoured once `executor.writerModel` is
    unset, and the finding is offered as the triage always offered it."""
    writer, problem = writer_setting(ctx.get("config"))
    if problem or not writer:
        return {}
    held = state.get(NOTED_FIELD) if isinstance(state.get(NOTED_FIELD), dict) else {}
    if held.get("head") != (head or git_head(ctx)):
        return {}
    open_ids = set(f.get("id") for f in open_findings(phase))
    return dict((fid, why) for fid, why in (held.get("notes") or {}).items()
                if fid in open_ids)


def read_verdicts(body, ids):
    """`(verdicts, problems)` - `{id: {"verdict", "kind", "basis"}}` from a
    validation session's return object - and what keeps it from answering:
    no `findings` list, an entry for a finding it was not asked about, a word
    outside the vocabulary, a finding answered twice - never the last entry
    winning - or a finding left with no verdict."""
    if not isinstance(body, dict) or not isinstance(body.get("findings"), list):
        return {}, ["its last message ends with no JSON object holding a "
                    "`findings` list"]
    got, problems, seen = {}, [], []
    for entry in body["findings"]:
        fid = str((entry or {}).get("id")) if isinstance(entry, dict) else None
        if fid not in ids:
            problems.append("an entry for %s, which it was not asked about" % (fid,))
            continue
        if fid in seen:
            problems.append("two entries for %s" % (fid,))
            got.pop(fid, None)
            continue
        seen.append(fid)
        verdict, kind = entry.get("verdict"), entry.get("kind")
        if verdict not in FINDING_VERDICTS or (verdict == "confirmed"
                                               and kind not in FINDING_KINDS):
            problems.append("%s answered verdict %r kind %r, not %s with a kind "
                            "of %s" % (fid, verdict, kind, "|".join(FINDING_VERDICTS),
                                       "|".join(FINDING_KINDS)))
            continue
        got[fid] = {"verdict": verdict, "kind": kind,
                    "basis": _clip(str(entry.get("basis") or "no basis given"), 200)}
    missing = [fid for fid in ids if fid not in got]
    if missing:
        problems.append("no verdict for %s" % (", ".join(missing),))
    return got, problems


def stream_reads(stream, project):
    """The project-relative paths a saved stream's `tool_use` blocks read a file
    at: `Read` and `NotebookRead` by their path, `Grep` by a `path` naming a
    file - an absolute path read as the project's own. Empty for a stream
    that cannot be read: no read is shown, and nothing is taken on one."""
    try:
        with open(stream, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, TypeError):
        return set()
    out = set()
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not (isinstance(block, dict) and block.get("type") == "tool_use"
                    and block.get("name") in READ_TOOLS):
                continue
            given = block.get("input") if isinstance(block.get("input"), dict) else {}
            for key in ("file_path", "notebook_path", "path"):
                path = given.get(key)
                if isinstance(path, str) and path:
                    if os.path.isabs(path):
                        path = os.path.relpath(os.path.realpath(path),
                                               os.path.realpath(project))
                    out.add(os.path.normpath(path).replace(os.sep, "/"))
    return out


def cited_paths(file_field):
    """Every path a finding's `file` names - with a line or without one."""
    paths = set(path for path, _f, _l in cited_ranges(file_field))
    paths.update(word for word in re.findall(r"[^\s,;:#()]+",
                                             str(file_field or "").replace("\\", "/"))
                 if "." in word or "/" in word)
    return set(os.path.normpath(p).replace(os.sep, "/") for p in paths)


def unread_demotions(candidates, verdicts, reads):
    """The ids of the med-or-worse candidates whose verdict would demote them -
    `withdrawn`, or confirmed as a kind that does not block - while `reads`
    holds no path the finding cites. A low finding is a note without any pass,
    so it needs no read; a confirmation of a blocking kind demotes nothing."""
    out = []
    for finding in candidates:
        verdict = verdicts.get(finding["id"]) or {}
        demotes = (verdict.get("verdict") == "withdrawn"
                   or verdict.get("kind") not in BLOCKING_KINDS)
        if (finding.get("severity") != CARRY_SEVERITY and demotes
                and not cited_paths(finding.get("file")) & set(reads)):
            out.append(finding["id"])
    return out


def validation_node(phase, head):
    """The record a validation pass's sessions are kept under: the phase, at
    one HEAD - a pass at a moved HEAD is a new one."""
    return {"id": phase["id"], "startedAt": "validate-%s" % (head,)}


def validation_dispatch(ctx, state, phase, head, candidates):
    """The validation session's dispatch: its prompt - every candidate, then
    `VALIDATE_RULE` - written beside the sessions, the reviewer's runner role on
    the reviewer session's model, and the ids it was asked about kept."""
    setting = reviewer_session_setting(phase, writer_setting(ctx["config"])[0])
    node = validation_node(phase, head)
    ids = [f["id"] for f in candidates]
    seq = writer_state(state, node, VALIDATE_KEY)["seq"]
    prompt = os.path.join(sessions_dir(ctx), "scratch", phase["id"],
                          "validate-%s.%d.prompt" % (head[:12], seq))
    lines = [VALIDATE_HEAD % {"phase": phase["id"], "head": head[:12]}, "",
             "phase base: %s" % (phase.get("baseRef")
                                 or "not recorded (phase.baseRef is absent)",),
             "task commits (git show <commit> is a task's own diff):"]
    lines += ["  %s %s" % (t["id"], t.get("commit") or "no commit")
              for t in _tasks(phase)]
    lines.append("")
    for f in candidates:
        lines += ["- %s %s %s: %s" % (f["id"], f.get("severity"), f.get("file"),
                                      f.get("issue")),
                  "  resolution asked: %s" % (f.get("resolution") or "none",)]
    os.makedirs(os.path.dirname(prompt), exist_ok=True)
    with open(prompt, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines + ["", VALIDATE_RULE]) + "\n")
    _record, argv = open_dispatch(ctx, state, node, 0, lambda record: writer_argv(
        ctx, node, setting, prompt, record, role="reviewer"), None, VALIDATE_KEY)
    held = writer_state(state, node, VALIDATE_KEY)
    held["asked"] = ids
    _mark(state, VALIDATE_KEY, node, held)
    write_state(ctx, state)
    return validation_said(ctx, phase["id"], setting["model"], ids,
                           project_relative(ctx, prompt), argv)


def validation_said(ctx, phase_id, model, ids, prompt, argv):
    """The validation session's dispatch print: the runner, the phase, the
    model and the finding ids it validates, and the command as its `run:`
    line."""
    command = " ".join(shlex.quote(word) for word in argv)
    return instruction("dispatch", step_text(
        "dispatch-validation", phase=phase_id, model=model,
        ids=finding_list(ids), prompt=prompt), signal_of(
        "dispatch-validation", phase_id, "%s --role reviewer model=%s; "
        "validates %s" % (WRITER_RUNNER, model, finding_list(ids)),
        command, runs=[command]))


def validation_step(ctx, state, phase, head, candidates):
    """`(True, None)` once the pass at `head` answered for every candidate -
    each verdict held with that HEAD - else `(None, said)`: the dispatch, the
    wait while its record is empty, the dispatch once more for a stream with
    no tool call, or the stop. A pass that opened no file re-read nothing, and
    one whose return does not answer every finding validates none of them."""
    node = validation_node(phase, head)
    held = writer_state(state, node, VALIDATE_KEY)
    ids = [f["id"] for f in candidates]
    if not held["dispatches"] or not set(ids) <= set(held.get("asked") or []):
        return None, validation_dispatch(ctx, state, phase, head, candidates)
    last = held["dispatches"][-1]
    runs = read_sessions(last["record"])
    if not runs:
        return None, wait_said(ctx, phase["id"], project_relative(
            ctx, last["record"]), last.get("argv") or [], "wait-validation")
    run = runs[-1]
    if not run["session"]:
        return None, _stopped(ctx, "the validation session for %s produced no "
                              "result (%s), so no finding was validated" % (
                                  finding_list(ids), _clip(run["line"], 160)))
    calls, why = stream_tool_calls(run["stream"])
    if calls is None:
        return None, _stopped(ctx, "validation session %s left a stream the drive "
                              "cannot count tool calls in (%s), so whether it "
                              "re-read the cited code is not known"
                              % (run["session"], why))
    if calls == 0:
        if held.get("redispatched", 0) < MAX_REVIEWER_REDISPATCH:
            held["redispatched"] = held.get("redispatched", 0) + 1
            held["asked"] = []
            _mark(state, VALIDATE_KEY, node, held)
            write_state(ctx, state)
            ctx["did"].append("validation session %s opened no file" % (
                run["session"][:8],))
            return None, validation_dispatch(ctx, state, phase, head, candidates)
        return None, _stopped(ctx, "validation sessions for %s opened no file, so "
                              "none of them re-read the cited code and no finding "
                              "was validated; there is no third dispatch" % (
                                  finding_list(ids),))
    text, _why = session_last_message(run["stream"])
    got, problems = read_verdicts(return_object(text), ids)
    if problems:
        return None, _stopped(ctx, "validation session %s validated nothing: %s"
                              % (run["session"], "; ".join(problems)))
    reads = stream_reads(run["stream"], ctx["project"])
    unread = unread_demotions(candidates, got, reads)
    if unread:
        # A demotion stands on the code the pass read: one that read none of a
        # finding's cited files re-read nothing of it, and its verdict is not
        # taken - never a note, never held: the drive stops for a human.
        return None, _stopped(ctx, "validation session %s withdrew or set aside "
                              "%s without reading a file it cites (it read: %s), "
                              "so that verdict is not taken and nothing was "
                              "validated; a human settles it" % (
                                  run["session"], finding_list(unread),
                                  ", ".join(sorted(reads)) or "nothing"))
    verdicts = dict(state.get(VERDICTS_FIELD) or {})
    verdicts.update((fid, dict(v, head=head, session=run["session"],
                               cost=run["cost"])) for fid, v in got.items())
    state[VERDICTS_FIELD] = verdicts
    write_state(ctx, state)
    ctx["did"].append("validation session %s: %d confirmed, %d withdrawn "
                      "(total_cost_usd=%s)" % (
                          run["session"][:8],
                          len([v for v in got.values() if v["verdict"] == "confirmed"]),
                          len([v for v in got.values() if v["verdict"] == "withdrawn"]),
                          run["cost"]))
    return True, None


def last_writer_session(state, task):
    """`{"session", "stream", "tree"}` of the latest writer run of `task`'s
    current start that produced a session, or None - read before a re-open
    starts the task again, after which that start's record no longer reads."""
    held = writer_state(state, task)
    for run in reversed(held["runs"]):
        if not run.get("session"):
            continue
        argv = next((d.get("argv") for d in held["dispatches"]
                     if d.get("seq") == run.get("seq")), None) or []
        return {"session": run["session"], "stream": run.get("stream"),
                "tree": argv[argv.index("--tree") + 1] if "--tree" in argv[:-1]
                else None}
    return None


def hand_back(ctx, state, phase, head, blocking):
    """Each confirmed finding back to every task whose own diff holds its
    cited lines (`blocking` is `[(finding, owners)]`): the task re-opened, so
    the drive starts it and its writer takes the findings, and - only once the
    verb took the re-open - its entry kept: its findings, the commit it
    carried and its last writer session, read before the re-open. The re-open
    row the verb journals is the durable record (`reopen_record`). No fix task
    is added. None, or the stop."""
    by_task = {}
    for finding, owners in blocking:
        for tid in owners:
            by_task.setdefault(tid, []).append(finding["id"])
    tasks = dict((t["id"], t) for t in _tasks(phase))
    for tid in sorted(by_task, key=_id_key):
        task = tasks.get(tid) or {}
        if task.get("status") != "done":
            return _stopped(ctx, "the confirmed finding(s) %s cite lines %s's diff "
                            "holds, and %s is %s, so there is no closed task to "
                            "re-open for its writer" % (
                                finding_list(by_task[tid]), tid, tid,
                                task.get("status")))
        held = (state.get(REVIEW_FIX_FIELD) or {}).get(tid)
        if isinstance(held, dict) and task.get("commit") in (None, held.get("from")):
            # Its last hand-back closed at no commit of its own: re-opening it
            # again would run the same writer over the same findings without end.
            return _stopped(ctx, "%s was re-opened for %s and closed again at no "
                            "new commit, so the finding(s) %s are still open and "
                            "%s is not re-opened again; fix them by hand or settle "
                            "each at sign-off" % (
                                tid, finding_list(held.get("findings") or []),
                                finding_list(by_task[tid]), tid))
        session = last_writer_session(state, task) or {}
        _out, stop = _verb_with_text(
            ctx, "audit-task.py", _task_args(ctx, "reopen", tid), "--reason",
            REOPEN_REASON % (finding_list(by_task[tid]), head[:12]))
        if stop is not None:
            return stop
        state.setdefault(REVIEW_FIX_FIELD, {})[tid] = dict(
            session, findings=by_task[tid], head=head, dispatched=[],
            **{"from": task.get("commit")})
        write_state(ctx, state)
        ctx["did"].append("%s re-opened for %s" % (tid, finding_list(by_task[tid])))
    return None


def review_fix(state, task):
    """The handed-back findings every writer dispatch of `task` takes while the
    hand-back stands - a retry under a start of its own and a brief issued
    again included - or None when there is none. Its `dispatched` lists the
    start of each dispatch that carried them (a `true` written before it was
    a list reads as one such dispatch), so only the first resumes a session.
    The entry is bound to its round: None once the task records a commit other
    than the one the hand-back cleared, which only a later close can write."""
    held = (state.get(REVIEW_FIX_FIELD) or {}).get(task["id"])
    if not isinstance(held, dict):
        return None
    if task.get("commit") and task.get("commit") != held.get("from"):
        return None
    return held


def standing_review_fix(ctx, state, task):
    """`(fix, spent, None)` - `review_fix`, while the newest `task.reopen` row
    the journal holds for `task` is the drive's hand-back (its reason in
    `REOPEN_REASON`'s shape). A re-open clears the commit `review_fix` reads,
    so a human's re-open after the fix round closed is told apart here: that
    start is not the hand-back's round, and `spent` says why its findings are
    not carried. `(None, None, why)` when the journal cannot be read."""
    fix = review_fix(state, task)
    if fix is None:
        return None, None, None
    try:
        rows = _journal_io.read_all(ctx["project"])
    except Exception as exc:                                   # noqa: BLE001
        return None, None, "the journal could not be read (%s)" % (exc,)
    last = None
    for row in rows:
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        if row.get("action") == TASK_REOPEN and details.get("taskId") == task["id"]:
            last = details
    if last is not None and _REOPEN_IDS.match(str(last.get("reason") or "")):
        return fix, None, None
    return None, ("%s's hand-back of %s is not carried: the newest re-open of it "
                  "is %s, not the drive's hand-back" % (
                      task["id"], finding_list(fix.get("findings") or []),
                      "absent from the journal" if last is None
                      else "a re-open for '%s'" % (
                          _clip(str(last.get("reason") or ""), 60),))), None


def _fix_dispatched(fix):
    """The starts whose dispatch already carried `fix`'s findings."""
    held = fix.get("dispatched")
    if isinstance(held, list):
        return list(held)
    return ["unrecorded"] if held else []


def warm_session(ctx, fix, tree=None):
    """`(session, why)` - the writer session a fix round resumes, its last
    activity (its saved stream's last write) under `CACHE_LIFE_SECONDS` ago in
    the tree this round runs in - or `(None, why)` a fresh one starts."""
    if not fix.get("session"):
        return None, "no writer session of the task's last start is recorded"
    here = member_project(ctx, tree) or ctx["project"]
    if fix.get("tree") and os.path.realpath(fix["tree"]) != os.path.realpath(here):
        return None, ("its session %s ran in another tree, where a resume would "
                      "not find it" % (fix["session"][:8],))
    try:
        idle = time.time() - os.path.getmtime(fix.get("stream") or "")
    except OSError as exc:
        return None, ("the last write of session %s's stream cannot be read (%s)"
                      % (fix["session"][:8], exc.__class__.__name__))
    said = "session %s was last active %d min ago; the cache lives %d min" % (
        fix["session"][:8], max(idle, 0) // 60, CACHE_LIFE_SECONDS // 60)
    return (fix["session"] if idle < CACHE_LIFE_SECONDS else None), said


def review_fix_dispatch(ctx, state, phase, task, writer, brief, fix, tree=None):
    """A re-opened task's writer dispatch, carrying the confirmed findings:
    the first one `--resume`s its last session while that is warm
    (`warm_session`), prompted with the findings alone; otherwise - a cold
    session, or any dispatch after the first, which a resume would hand only
    the findings and not the brief it was re-issued for - a fresh session
    whose prompt is the task's own brief - its text - and then the findings.
    `fix` is the entry `standing_review_fix` found standing."""
    carried = _fix_dispatched(fix)
    _manifest, phase = load_phase(ctx)
    held = dict((f.get("id"), f) for f in (phase.get("review") or {}).get("findings")
                or [] if isinstance(f, dict))
    lines = []
    for fid in fix.get("findings") or []:
        found = held.get(fid) or {}
        lines += ["- %s %s %s: %s" % (fid, found.get("severity"), found.get("file"),
                                      found.get("issue")),
                  "  resolution asked: %s" % (found.get("resolution") or "none",)]
    lines += fix_prove_lines(task)
    if carried:
        session, why = None, ("a dispatch of start %s already carried them, so "
                              "this one starts afresh with the task's brief"
                              % (carried[-1],))
    else:
        session, why = warm_session(ctx, fix, tree)
    prompt = session_record(ctx, task, writer_state(state, task)["seq"])[
        :-len(".jsonl")] + ".prompt.md"
    try:
        with open(brief, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return _stopped(ctx, "the writer brief %s could not be read (%s)" % (brief, exc))
    os.makedirs(os.path.dirname(prompt), exist_ok=True)
    with open(prompt, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(resume_prompt(lines, REVIEW_FIX_HEAD) if session else
                 "%s\n\n%s\n\n%s\n" % (text.rstrip("\n"), REVIEW_FIX_HEAD,
                                       "\n".join(lines)))
    _record, argv = open_dispatch(ctx, state, task, 0, lambda record: writer_argv(
        ctx, task, writer, prompt, record, tree, resume=session), tree)
    state[REVIEW_FIX_FIELD][task["id"]] = dict(
        fix, dispatched=carried + [start_key(task)], resumed=session, why=why)
    write_state(ctx, state)
    said = "%s go to %s (%s)" % (
        finding_list(fix.get("findings") or []), "a resume of session %s" % (
            session,) if session else "a fresh writer session", why)
    refused = note_task(ctx, task, "the phase review's confirmed finding(s) " + said)
    ctx["did"].append(_clip(said, 120) + ("" if refused is None
                                          else " (not noted: %s)" % (refused,)))
    return writer_said(ctx, task["id"], writer["model"],
                       project_relative(ctx, prompt), argv, resume=session)


def resolve_fixed(ctx, state, fixed):
    """Each handed-back finding the validation pass re-read at the fix's commit
    and withdrew, recorded fixed by `resolve-finding --fix-task`, which writes
    that task's own commit on it - never on a new commit alone. A task's entry
    goes once none of its findings is left. None, or the stop."""
    fixes = dict(state.get(REVIEW_FIX_FIELD) or {})
    for finding, tid in fixed:
        _out, stop = _verb_or_stop(ctx, "audit-task.py", [
            "resolve-finding", finding["id"], ctx["manifest"], "--project-dir",
            ctx["project"], "--fix-task", tid])
        if stop is not None:
            return stop
        ctx["did"].append("%s fixed by %s, re-checked" % (finding["id"], tid))
        entry = dict(fixes.get(tid) or {})
        entry["findings"] = [f for f in entry.get("findings") or []
                             if f != finding["id"]]
        if entry["findings"]:
            fixes[tid] = entry
        else:
            fixes.pop(tid, None)
        state[REVIEW_FIX_FIELD] = fixes
        write_state(ctx, state)
    return None


def cap_stop(ctx, state, phase, head, blocking, rounds, cap):
    """The stop once `review.maxRounds` rounds are spent with a confirmed
    finding open: never a sign-off over it and never another round. Each task
    whose diff holds a finding's lines gets a note naming them, once per HEAD."""
    said = ["%s %s %s - %s" % (f["id"], f.get("severity"), f.get("file"),
                               _clip(f.get("issue") or "", 80))
            for f, _owners in blocking]
    if state.get(CAP_NOTED_FIELD) != head:
        tasks = dict((t["id"], t) for t in _tasks(phase))
        for tid in sorted(set(t for _f, owners in blocking for t in owners
                              if t in tasks), key=_id_key):
            refused = note_task(ctx, tasks[tid], "review round %d of %d spent with "
                                "the confirmed finding(s) still open on this task's "
                                "lines: %s" % (rounds, cap, "; ".join(
                                    s for (_f, owners), s in zip(blocking, said)
                                    if tid in owners)))
            if refused is not None:
                ctx["did"].append("%s not noted: %s" % (tid, refused))
        state[CAP_NOTED_FIELD] = head
        write_state(ctx, state)
    return _stopped(ctx, "review.maxRounds is %d and %d review round(s) are spent, "
                    "so no writer takes these confirmed finding(s) and the phase is "
                    "not signed off: %s. Raise review.maxRounds for another round, "
                    "or settle each at sign-off with audit-task.py signoff "
                    "--accept-open <id>=<the human's reason>." % (
                        cap, rounds, "; ".join(said)))


def review_findings_step(ctx, state, phase, review):
    """Under a writer session, what the phase review's open findings lead to
    before the triage: sorted (`sort_findings`), every finding no pass has
    judged at this HEAD through the validation pass - a handed-back one
    included, which is fixed only when the pass re-reads it and withdraws it -
    then the stop for a confirmed finding no task's diff holds, the stop past
    the cap, or each confirmed blocking finding handed back to its tasks.
    None when the triage goes on as before: no writer session, no review
    filed, or nothing confirmed left open.

    A ROUND, for one finding, is a filed phase review or a hand-back of it,
    whichever count is higher, so the cap holds under every `review.perTask`:
    a key that files no second review still spends a round on each re-open."""
    writer, problem = writer_setting(ctx["config"])
    if problem or not writer or review is None:
        return None
    head = git_head(ctx)
    if not head:
        return _stopped(ctx, "git named no HEAD, so no finding can be judged at it")
    carried, handed, why = reopen_record(ctx, phase)
    if why is not None:
        return _stopped(ctx, "%s, so the commits a re-opened task carried and the "
                        "findings handed back are not known" % (why,))
    record = (task_commits(phase, carried), handed)
    found, why = sort_findings(ctx, state, phase, head, record)
    if why is None and found["candidates"]:
        done, said = validation_step(ctx, state, phase, head, found["candidates"])
        if done is None:
            return said
        found, why = sort_findings(ctx, state, phase, head, record)
    if why is not None:
        return _stopped(ctx, "git could not read a task's own diff for a confirmed "
                        "finding, so whose lines it cites is not known: %s" % (why,))
    stop = resolve_fixed(ctx, state, found["fixed"])
    if stop is not None:
        return stop
    state[NOTED_FIELD] = {"head": head, "notes": found["notes"]}
    write_state(ctx, state)
    if found["unowned"]:
        return _stopped(ctx, "the validation pass confirmed %s as blocking, and no "
                        "task's own diff holds a line it cites (or it cites none in "
                        "a form the drive reads), so no writer can take it: a human "
                        "decides - add a task that fixes it, or settle it at "
                        "sign-off with audit-task.py signoff --accept-open "
                        "<id>=<the human's reason>" % (
                            "; ".join("%s %s %s" % (f["id"], f.get("severity"),
                                                    f.get("file"))
                                      for f in found["unowned"]),))
    blocking = found["blocking"]
    if not blocking:
        return None
    filed_rounds, cap, problem = review_rounds(ctx, state, phase)
    if problem:
        return _stopped(ctx, problem)
    rounds = max([filed_rounds] + [1 + len(handed.get(f["id"]) or [])
                                   for f, _owners in blocking])
    if rounds >= cap:
        return cap_stop(ctx, state, phase, head, blocking, rounds, cap)
    stop = hand_back(ctx, state, phase, head, blocking)
    return HANDED_BACK if stop is None else stop


# --- sign-off's last step: the gate, the verdict, the landing -------------------
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
            ctx["project"], "--verdict", "passed"]
    # THE HUMAN'S WORDS ARE THE DISPOSITION. A `sign-off` answered over an
    # open finding - one no fix task landed for - is the human accepting it
    # open, and the verb refuses a sign-off that leaves one unsaid, so each is
    # recorded with the reason the answer carried. A finding handed to a fix
    # task still to run is not offered one: that task is its answer. One a
    # `carry` answer handed on is recorded as carried to the id it named. One
    # the sort left a note at this HEAD (`noted_now`) never blocked, and is
    # recorded with its note as the reason rather than the summary's words.
    carried = carried_now(state, phase)
    noted = noted_now(ctx, state, phase, head)
    for finding in triage_findings(phase)[0]:
        args += (["--carried", "%s=%s" % (finding["id"], carried[finding["id"]])]
                 if finding["id"] in carried else
                 ["--accept-open", "%s=a note, not a block - %s" % (
                     finding["id"], noted[finding["id"]])]
                 if finding["id"] in noted else
                 ["--accept-open", "%s=%s" % (finding["id"], summary)])
    mark = state.get("phaseReview") or {}
    if mark.get("head"):
        args += ["--review-outcome", "phase review filed at head %s"
                 % (mark["head"][:12],)]
    _out, stop = _verb_with_text(ctx, "audit-task.py", args, "--summary", summary)
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
    stop = ci_before_signoff(ctx, state)
    if stop is not None:
        return stop
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
    """Whether `task` has spent the attempts it may take - the line past which
    `start` refuses it and `unblock` is the only verb that takes it back; below
    it `start` runs the task, and `unblock` would clear a block without
    running it."""
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
    marks of this task but those `KEPT_AT_TASK_CLOSE` names, and drop the state
    when nothing else is in it. Those two stay until the phase's own `finish`
    drops the whole state: a later phase review hands findings back through
    them - the hand-back's record holds the closed-at-no-new-commit guard, and
    the writer's record of the start is the session a hand-back resumes."""
    stop = release_lock(ctx, state)
    if stop is not None:
        return stop
    for kind in [k for k, v in state.items()
                 if isinstance(v, dict) and k not in KEPT_AT_TASK_CLOSE]:
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
    noted = noted_now(ctx, state, phase)
    offered = [f for f in offered if f.get("id") not in carried
               and f.get("id") not in noted]
    if offered != pending.get("findings") or handed != (pending.get("handed") or []):
        pending = dict(pending, findings=offered, handed=handed)
        state["pending"] = pending
        write_state(ctx, state)
    return pending


def drive_locked(ctx, state, answer, reason, fixes):
    """The body of `drive`, run with the phase lock held."""
    manifest, phase = load_phase(ctx)
    pending = state.get("pending")
    if pending and not pending_still_applies(ctx, manifest, pending):
        state.pop("pending", None)
        write_state(ctx, state)
        moved = verdict_moved(ctx, pending)
        if moved is not None and answer not in (None, "rerun"):
            return E_USAGE, ("%s %s: the %s decision on %s stood on a run that "
                             "no longer answers its gate (%s), so --answer %s "
                             "answers nothing; next measures it again"
                             % (PREFIX, ctx["phase"], pending["decision"],
                                pending["task"], moved, answer))
        if moved is not None:
            # A rerun asks for the measurement the moved verdict owes anyway.
            answer = None
        pending = None
    if pending and pending["decision"] == "triage":
        pending = refresh_triage(ctx, state, phase, pending)
    if pending and pending.get("task"):
        # A writer session run while the decision waited is noted before the
        # decision is printed again or answered: a `retry` starts a new start,
        # whose record no longer reads this one's.
        waiting_on = _mio.tasks_by_id(manifest).get(pending["task"])
        if waiting_on is not None:
            note_sessions(ctx, state, waiting_on)
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
        idle = not any(t.get("status") == "in_progress" for t in _tasks(phase))
        ready = sorted(_status_facts.ready_tasks(manifest)) if idle else []
        task, how = next_task(manifest, phase, red_at_base(
            ctx, ready, gate_step_names(manifest, phase, ready))[0]
            if idle else None)
        if task is None:
            if all(t.get("status") in _mio.TERMINAL for t in _tasks(phase)):
                said = sign_off(ctx, state, manifest, phase)
                if said is HANDED_BACK:
                    continue
                return _as_result(said)
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


def string_fields(value, field=""):
    """`[(field, string)]` for every string leaf under `value`, each field named
    the way a reader finds it again: `outcome.technical`, `testsAdded[0]`."""
    if isinstance(value, str):
        return [(field or "the return", value)]
    if isinstance(value, dict):
        return [pair for key, item in value.items()
                for pair in string_fields(
                    item, "%s.%s" % (field, key) if field else str(key))]
    if isinstance(value, list):
        return [pair for index, item in enumerate(value)
                for pair in string_fields(item, "%s[%d]" % (field, index))]
    return []


def machine_path_refusal(project, body):
    """None when no string in `body` carries a machine path, else the refusal.

    The same predicate `audit-task.py add` refuses a description with,
    `_journal_io.check_free_text`, asked of every string in the return: a filed
    return lands in a committed, hash-chained directory, and the writer's own
    scrub would otherwise rewrite what the agent claimed without telling it. The
    first field's refusal carries the remedy; the rest are named after it, and
    no value is ever echoed."""
    refusals = [(field, why) for field, why in
                ((field, _journal_io.check_free_text(project, field, text))
                 for field, text in string_fields(body)) if why]
    if not refusals:
        return None
    others = [field for field, _why in refusals[1:]]
    return refusals[0][1] + ((" Also: %s." % (", ".join(others),)) if others else "")


def already_filed(ctx, task):
    """`role_return_filed` for the executor: the one the filing verb and the
    submit's early look ask about."""
    return role_return_filed(ctx, task, "executor")


def role_return_filed(ctx, task, role):
    """The project-relative path of `task`'s `role` return for its current
    start when one is filed - on disk, or when a `task.return.filed` journal
    row already names it, EVEN WITH THE FILE DELETED (an executor once
    filed a placeholder, deleted it, and filed again, and nothing recorded
    either filing) - else None. The filing verb refuses a second
    filing on its own; asking first is what keeps a refusal from costing a
    red run and a stamp."""
    path = _fr.return_path(ctx["evidence"], task, role)
    if not path:
        return None
    if os.path.exists(path):
        return project_relative(ctx, path)
    try:
        rows = _journal_io.read_all(ctx["project"], ctx["config"])
    except Exception:                                          # noqa: BLE001
        return None
    why = _fr.refiling_refusal(rows, path, ctx["project"])
    return ("%s: %s" % (project_relative(ctx, path), why)) if why else None


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


def red_args(project, manifest, task_id, cmd, cases=(), introduces=(),
             deps_from=None):
    """The arguments of `stamp-verification.py red` for `task_id` over `cmd`, in
    the tree `project`: the one spelling `submit` runs for an executor and the
    drive runs after a writer session, so the two proofs cannot differ by how
    they were asked for."""
    extra = []
    for flag, values in (("--case", cases), ("--introduces", introduces)):
        for value in values:
            extra += [flag, value]
    if deps_from:
        extra += ["--deps-from", deps_from]
    extra.append("--derive-introduces")
    return ["red", "--project", project, "--manifest", manifest, "--task",
            task_id, "--json"] + extra + ["--"] + list(cmd)


def red_block(ctx, task, args, cmd, tree=None):
    """`(block, None)` - the helper's `redFirst` block for `task` - or
    `(None, stop)`. A test that passed without the fix gets no block from the
    helper, and so no filing: the work is to fix the test. `tree` is the
    task's own worktree in a wave, whose test files and HEAD the red run reads."""
    block, _payload, stop = red_run(ctx, task, red_args(
        tree or ctx["gitRoot"], ctx["manifest"], task["id"], cmd, args.case,
        args.introduces, args.deps_from))
    return block, stop


def red_run(ctx, task, argv):
    """`(block, payload, None)` for one `stamp-verification.py red` run over
    `argv` (`red_args`) - the helper's block and its whole payload, which
    carries the test files' digest - or `(None, None, stop)`: the helper's
    refusal relayed whole, or the sentence that it gave no block."""
    block, payload, why = red_reading(ctx, task, argv)
    if why is None:
        return block, payload, None
    kind, code, text = why
    if kind == "refused":
        return None, None, relay_refusal(ctx, "stamp-verification.py", code, text)
    return None, None, _stopped(ctx, "the red-first helper gave no block (exit "
                                "%d): %s Nothing filed." % (code, text))


def red_reading(ctx, task, argv):
    """`(block, payload, None)` - as `red_run` - or `(None, None, why)`, `why`
    being `("refused", exit, the helper's words)` or `("no-block", exit, its
    note)`: what each caller turns into its own stop or decision."""
    code, out, err = run_verb(ctx, "stamp-verification.py", argv)
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
                             % (task["id"], " ".join((out + err).split()))}, {}, None
        return None, None, ("refused", code, out + err)
    block = payload.get("redFirst") if isinstance(payload, dict) else None
    printed = payload.get("printed") if isinstance(payload, dict) else None
    ctx["printed"] = printed if isinstance(printed, list) else None
    if not isinstance(block, dict):
        return None, None, ("no-block", code, (payload.get("note") if isinstance(
            payload, dict) else None) or "no note")
    return block, payload, None


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


def wave_state(ctx, phase):
    """The driver's recorded wave for `phase`, `{}` when it has none or its state
    does not read. Read from the state file, never from the agent's working
    directory."""
    hc = _loader.load_hooks_config(modname="audit__config")
    state_dir = str(hc.state_dir(pathlib.Path(ctx["project"]), ctx["config"] or {}))
    path = _fr.drive_state_path(state_dir, phase["id"])
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    wave = state.get("wave") if isinstance(state, dict) else None
    return wave if isinstance(wave, dict) else {}


def submit_tree(ctx, phase, task):
    """`(tree, None)` - the worktree the driver's open wave gave `task`, or None
    when the task runs in the phase tree - or `(None, stop)` when the wave names
    a tree that is gone. Read from the driver's state, never from the agent's
    working directory: an agent's shell does not stay where it was put."""
    wave = wave_state(ctx, phase)
    tree = (wave.get("trees") or {}).get(task["id"])
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
    machine = machine_path_refusal(ctx["project"], body)
    if machine:
        return _stopped(ctx, "the %s return for %s: %s" % (
            args.role, args.id, machine))
    owed = task is not None and _fr.owes_red_first(task)
    executor = task is not None and args.role == "executor"
    if executor and owed and not cmd:
        return _stopped(ctx, "%s is a tdd task, so its red-first block is the "
                        "helper's: name the test command after `--`. Nothing "
                        "filed." % (task["id"],))
    # A tdd task that owes nothing (`expectRedFirst` false) and is given no
    # command: the driver files the not-attempted block itself, since no helper
    # ran and a typed block would claim a proof nothing made.
    unowed = (executor and not cmd and isinstance(body, dict) and
              (task.get("tests") or {}).get("mode") == "tdd" and not owed)
    if unowed:
        body["redFirst"] = dict(unowed_red_first(task), at=_utc_stamp())
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
        printed = ctx.get("printed") if cmd else None
        gaps = case_binding_gaps(task, body.get(_fr.CASES_FIELD), printed,
                                 list(cmd) if cmd else None)
        unchecked = (_fr.case_binding_unchecked(task, list(cmd))
                     if cmd and printed is not None else [])
        if unchecked:
            ctx["did"].append(
                "tests.add: %d entr%s not checked against a printed case: %s"
                % (len(unchecked), "y was" if len(unchecked) == 1 else "ies were",
                   "; ".join(unchecked)))
        # The drive's own reading, filed beside the claim: the reviewer's brief
        # prints these and not a recomputation that could not see the output.
        # The unchecked entries ride with the gaps: ids no one compared with a
        # printed label are as much the reviewer's to know as ids that failed.
        body[_fr.GAPS_FIELD] = gaps
        body[_fr.UNCHECKED_FIELD] = unchecked
        if gaps:
            ctx["did"].append(
                "tests.add: %d entr%s not bound to a printed case: %s"
                % (len(gaps), "y is" if len(gaps) == 1 else "ies are",
                   "; ".join(gaps)))
        elif printed is None and (task.get("tests") or {}).get("add"):
            ctx["did"].append(
                "tests.add: the case ids were not checked against what the "
                "suite printed - %s" % (
                    "no test command was given" if not cmd else
                    "its runner prints no per-case labels the drive reads"))
        text = json.dumps(body, indent=2) + "\n"
    head = args.head
    if args.slice is not None and (task is not None or args.role != "reviewer"):
        return _stopped(ctx, "`--slice` files one slice of a phase review: give a "
                        "phase id and `--role reviewer`. Nothing filed.")
    if args.slice is not None:
        whole, stop = take_slice(ctx, phase, args, body)
        if stop is not None:
            return stop
        if whole is None:
            return E_OK, instruction("filed", [])
        body, text = whole, json.dumps(whole, indent=2) + "\n"
        pairs, _why = _fr.read_shown_brief(state_root(ctx), phase["id"],
                                           whole_head(ctx, args.head))
        args.shown = _fr.shown_argument_of(pairs) if pairs else None
    if task is None and args.role == "reviewer":
        head = whole_head(ctx, head)
        if isinstance(body, dict) and isinstance(body.get("tasks"), list):
            body["tasks"] = agreed_commits(phase, body["tasks"])
            text = json.dumps(body, indent=2) + "\n"
    extra = ["--head", head] if head else []
    if args.shown is not None:
        extra += ["--shown", args.shown]
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
        if tree:
            carry_work(ctx, task, tree, wave_state(ctx, phase).get("records"))
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
    runs = list((fields or {}).get("runs") or [])
    return {"line": signal_line(ctx, SIGNAL_VERBS.get(step, "stop"), subject,
                                ctx["did"], basis, nxt),
            "subjects": [subject] + list((fields or {}).get("subjects") or []),
            "explain": "\n".join([full] + ["prompt: %s" % (p,) for p in prompts]
                                 + ["run: %s" % (r,) for r in runs])}


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
        if not (isinstance(pending, dict)
                and subject == (pending.get("task") or ctx["phase"])):
            continue
        if pending_still_applies(ctx, manifest, pending):
            return E_OK, explain_text(render_decision(ctx, pending)["lines"])
        moved = verdict_moved(ctx, pending)
        if moved is not None:
            # The kept text is the decision as it was printed, about a run that
            # no longer answers the gate: replaying it would offer its answers.
            return E_OK, explain_text([
                "%s %s: the %s decision on %s stood on run %s, which no longer "
                "answers its gate - %s" % (
                    PREFIX, ctx["phase"], pending["decision"], subject,
                    (pending.get("verdict") or {}).get("runId"), moved),
                "next measures the gate again: next %s" % (ctx["phase"],)])
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
        "--project", ctx["project"]] + (
            [] if args.slice is None else ["--slice", str(args.slice)]),
        record=True)
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
    brf.add_argument("--slice", type=int, default=None, metavar="N",
                     help="with `--role phase`: the slice of a brief cut at the "
                          "reader budget that this reviewer holds")
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
    sbm.add_argument("--shown", default=None, metavar="ID@SHA,...",
                     help="the tasks a phase review's brief showed, as its "
                          "filing command names them; recorded by the verb")
    sbm.add_argument("--slice", default=None, metavar="N/TOTAL",
                     help="a phase review's slice, as its brief prints it: the "
                          "return is held until every slice has filed, then "
                          "they file as the one phase return")
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
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if _output.own_args(sys.argv[1:])[:1] == ["brief"]:
        # A record, not a step: `terse_cli` would hold it and print it again
        # through stdout's text layer, which is the translation it must not get.
        sys.exit(main(sys.argv[1:], out=write_record))
    sys.exit(_output.terse_cli(main, sys.argv[1:], success_line, keep_verbose=True))
