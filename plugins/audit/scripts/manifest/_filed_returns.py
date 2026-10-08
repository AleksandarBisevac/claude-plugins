#!/usr/bin/env python3
"""
Where an agent's filed return lives, what shape it must have, and how it is read;
and the one property a phase's landing asks of the plan under `review.perTask`.

An agent's return used to be prose the main loop read and retyped, so nothing
checked its shape and a close carried whatever the retyping kept. A return is now
FILED: `audit-task.py file-return` writes it - an agent reaches it through
`drive-phase.py submit`, which first takes an executor's stamp and, given a test
command, its red-first block - `audit-task.py done` and
`audit-lookup.py brief` read it, and `commit-task-work.py` reads its `claims`.
Those are entry points at one layer, which may not import each other, so the
three facts they share live here, once:

  * the path - `<evidence dir>/returns/<taskId>/<start>.<role>.json`, where
    `<start>` is the task's current `startedAt`. A re-start re-stamps it, so a
    retry's return lands beside the earlier attempt's and never over it, and a
    return from an earlier start is never read as this one's;
  * the shape each role's agent definition declares, as a list of sentences
    naming what is missing - empty is the one answer that files;
  * the write: an exclusive create, so a second filing for one task, role and
    start is refused and the first stays byte-identical.

The evidence directory is the caller's to resolve and hand in: resolving it is
`_evidence_io`'s, one layer up, and keeping it out leaves this module at the
floor with nothing to import but `_output`.

A PHASE-MODE REVIEW FILES TOO, under the phase id, keyed on the head its brief
was computed at (`phase_return_rel`), and it carries one `tasks` entry per task
owed an answer. The property a landing asks of the record (`landing_refusals`)
lives here because two entry points ask it, `audit-task.py signoff` and
`close-phase.py`, and a rule held twice is two rules. Which of a phase return's
answers only a human settles (`needs_human`) lives here for the same reason:
`drive-phase.py`'s triage and `audit-task.py signoff` both stop on them, and the
settlement both read is the driver's state file (`settlement_record`). A
settlement binds the answer it settled - the content signature of the return
it sits in, written beside its key (`settlement_after`) - and the checkouts
whose records `audit-task.py signoff` and `close-phase.py` both honour are
one helper's answer (`settlement_checkouts`), so the two verbs read one set.

WHAT A VERDICT READ is here for the same reason. `audit-task.py signoff`
records on the phase review the signature of every filed phase return it read
(`read_record`, under `READ_RETURNS_FIELD`), and `close-phase.py` compares every
return it can find against that set (`read_set`, `return_signature`): two
verbs, one definition of when two copies are the same answer. Reading a ref's
committed returns (`ref_phase_returns`, `tip_phase_returns`) asks git directly,
which is the one place this module runs a command.

WHAT NOTHING HERE CHECKS: the task id, the role and the head are the caller's
word.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__filed_returns.py` - see `plugins/audit/tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
import hashlib
import json
import os
import posixpath
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


# --- the vocabulary ---------------------------------------------------------------
RETURN_ROLES = ("executor", "reviewer")
RETURNS_DIRNAME = "returns"

# The words a task-mode reviewer answers the intent question with; `not-asked`
# is the orchestrator's own word and no reviewer files it.
REVIEW_ANSWERS = ("matches", "diverges", "cannot-tell")
REVIEW_VERDICTS = ("clean", "findings")

# The executor's red-first words: the schema's `redFirst.status` enum, which is
# the one source. Written here because the plugin runs from an installed copy,
# where the schema is not where the repository's lint reads it;
# `fr7` in `plugins/audit/tests/test__filed_returns.py` holds this tuple equal to
# the enum.
RED_FIRST_WORDS = ("proved", "could-not-prove", "not-attempted")

# The grade only a reviewer gives - `_refs.RED_FIRST_REVIEWER_ONLY`, held equal
# to it by `pk4` in the tests - and the words of the inherited-test question,
# held equal to the plan schema's `intentCheck.inheritedTests` enum the same way.
REVIEWER_ONLY_RED_FIRST = ("not-proved",)
INHERITED_WORDS = ("none-found", "flagged", "not-asked")


# --- the path ---------------------------------------------------------------------
def return_start_key(started_at):
    """`startedAt` as a file-name part: letters and digits only, so no colon a
    file name on Windows refuses."""
    return re.sub(r"[^0-9A-Za-z]", "", str(started_at or ""))


def return_rel(task_id, started_at, role):
    """The filed return's path below the evidence directory, `/`-separated."""
    return "%s/%s/%s.%s.json" % (RETURNS_DIRNAME, task_id,
                                 return_start_key(started_at), role)


def return_path(evidence_dir, task, role):
    """Absolute path of `task`'s `role` return for its CURRENT start, or None
    when the task records no start to file under."""
    if not (isinstance(task, dict) and task.get("startedAt")):
        return None
    rel = return_rel(str(task.get("id")), task["startedAt"], role)
    return os.path.join(evidence_dir, *rel.split("/"))


# --- the shape --------------------------------------------------------------------
def _text_field(body, key):
    return isinstance(body.get(key), str) and body.get(key).strip() != ""


def _executor_problems(body):
    problems = []
    if not isinstance(body.get("gates"), dict):
        problems.append("`gates` is missing or not an object")
    outcome = body.get("outcome")
    if not isinstance(outcome, dict):
        problems.append("`outcome` is missing or not an object")
    else:
        problems += ["`outcome.%s` is missing or empty" % half
                     for half in ("technical", "descriptive")
                     if not _text_field(outcome, half)]
    added = body.get("testsAdded")
    if not (isinstance(added, list) and all(isinstance(t, str) for t in added)):
        problems.append("`testsAdded` is missing or not a list of names")
    red = body.get("redFirst")
    if not isinstance(red, dict):
        problems.append("`redFirst` is missing or not an object")
    else:
        if red.get("status") not in RED_FIRST_WORDS:
            problems.append("`redFirst.status` is %r, not one of %s"
                            % (red.get("status"), ", ".join(RED_FIRST_WORDS)))
        if not _text_field(red, "basis"):
            problems.append("`redFirst.basis` is missing or empty")
    if not _text_field(body, "stamp"):
        problems.append("`stamp` is missing or empty")
    if "claims" in body and not isinstance(body.get("claims"), str):
        problems.append("`claims` is not text")
    return problems


def _reviewer_problems(body):
    problems = []
    if not isinstance(body.get("findings"), list):
        problems.append("`findings` is missing or not a list")
    intent = body.get("intent")
    if not isinstance(intent, dict):
        problems.append("`intent` is missing or not an object")
    elif intent.get("answer") not in REVIEW_ANSWERS:
        problems.append("`intent.answer` is %r, not one of %s"
                        % (intent.get("answer"), ", ".join(REVIEW_ANSWERS)))
    if body.get("verdict") not in REVIEW_VERDICTS:
        problems.append("`verdict` is %r, not one of %s"
                        % (body.get("verdict"), ", ".join(REVIEW_VERDICTS)))
    return problems


def return_problems(role, body):
    """Every way `body` falls short of the shape `role` files with, as sentences
    naming the field - `agents/audit-executor.md`'s and
    `agents/audit-reviewer.md`'s return blocks, plus the executor's `stamp`,
    which `drive-phase.py submit` takes rather than the agent. Empty is the one
    answer that files; a role this module does not know is a problem too,
    never a pass."""
    if role not in RETURN_ROLES:
        return ["the role %r is not one of %s" % (role, ", ".join(RETURN_ROLES))]
    if not isinstance(body, dict):
        return ["the return is a JSON %s, not an object" % type(body).__name__]
    return _executor_problems(body) if role == "executor" \
        else _reviewer_problems(body)


# --- the write and the read -------------------------------------------------------
def file_once(path, text):
    """Write `text` to `path` verbatim, creating it; raises `FileExistsError`
    when a return is already filed there, which leaves that one untouched."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read_filed_return(path):
    """`(text, body, problem)` for a filed return; all None when none is filed.

    A file that is there and will not parse is a PROBLEM, never "not filed":
    reading it as absent would let a close fall through to a rule meant for a
    review nobody ran."""
    if not path or not os.path.isfile(path):
        return None, None, None
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, ValueError) as exc:
        return None, None, "%s cannot be read as JSON (%s)" % (path, exc)
    body, problem = return_body(text, path)
    return (text if problem is None else None), body, problem


def return_body(text, label):
    """`(body, problem)` - a filed return's text parsed, or why it was not:
    `text` None is a return that could not be read at all, which is a problem
    here too, never "not filed". `label` names it in the problem."""
    if text is None:
        return None, "%s could not be read" % (label,)
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, "%s cannot be read as JSON (%s)" % (label, exc)


def claims_from_return(evidence_dir, task):
    """`(claims, problem)` - the `claims` text of `task`'s executor return for its
    current start, verbatim, or None when there is none to carry: no start, no
    return filed, or a return that carries no `claims`. A filed return that will
    not parse is the problem, not an absence."""
    _text, body, problem = read_filed_return(
        return_path(evidence_dir, task, "executor"))
    if problem:
        return None, problem
    claims = (body or {}).get("claims")
    return (claims if isinstance(claims, str) and claims.strip() else None), None


# --- the per-task review's key, and the property a landing asks ---------------
# `review.perTask` says where a task's three review answers - the intent binding,
# the red-first grade and the inherited-test question - are given: by a reviewer
# per task (`always`), by the phase review at sign-off (`phase`), or per task only
# where a computed signal fires (`signals`). Its value is recorded on the phase at
# its first start and on each task at its own, so a key switched mid-phase, or a
# task moved between phases, keeps the reading its work began under.
REVIEW_KEY_FIELD = "reviewPerTask"
KEY_PHASE = "phase"
# The intent word `done` writes for a task whose answers the phase review owes.
# No caller can type it: `--intent` offers the answers, never this.
INTENT_DEFERRED = "deferred"


def review_key(task, phase, live):
    """`(value, source)` - the task's recorded key, else its phase's, else
    `live`, the config's reading now; `source` is `task`, `phase` or `config`.
    A key recorded nowhere is never read as `always`."""
    if isinstance(task, dict) and task.get(REVIEW_KEY_FIELD):
        return task[REVIEW_KEY_FIELD], "task"
    if isinstance(phase, dict) and phase.get(REVIEW_KEY_FIELD):
        return phase[REVIEW_KEY_FIELD], "phase"
    return live, "config"


def is_fix_task(task, phase):
    """Whether `task` is a fix task the plan records as one: it carries `fixes`,
    and each finding named there sits in `phase`'s own review naming it as its
    `fixTask`. A finding moved to another task, or a task moved away from its
    findings, ends it."""
    fixes = task.get("fixes") if isinstance(task, dict) else None
    if not (isinstance(fixes, list) and fixes):
        return False
    review = phase.get("review") if isinstance(phase, dict) else None
    found = dict((str(f.get("id")), f) for f in
                 ((review or {}).get("findings") or []) if isinstance(f, dict))
    return all((found.get(str(fid)) or {}).get("fixTask") == task.get("id")
               for fid in fixes)


def _said(block, key):
    return isinstance(block.get(key), str) and block[key].strip() != ""


def landing_problem(task, phase, live):
    """None when `task` may reach its phase's landing, else what it lacks.

    Asked only of a task that records a commit and whose key reads `phase`: its
    `intentCheck` must carry an intent answer other than `deferred`, a red-first
    grade and an inherited-test answer, each with its basis where it is
    `not-asked`, bound to the commit the task records now. A recorded fix task
    may carry `not-asked` with its basis instead."""
    commit = task.get("commit") if isinstance(task, dict) else None
    if not commit or review_key(task, phase, live)[0] != KEY_PHASE:
        return None
    block = task.get("intentCheck") if isinstance(task.get("intentCheck"),
                                                  dict) else {}
    if block.get("commit") != commit:
        return ("no review answers are bound to its commit %s (intentCheck "
                "names %s)" % (str(commit)[:12],
                               str(block.get("commit") or "none")[:12]))
    answer = block.get("answer")
    if answer == "not-asked" and _said(block, "basis") \
            and is_fix_task(task, phase):
        return None
    lacks = []
    if answer in (None, "", INTENT_DEFERRED):
        lacks.append("an intent answer (it reads %s)" % (answer or "none",))
    elif answer == "not-asked" and not _said(block, "basis"):
        lacks.append("the basis of its `not-asked`")
    if not _said(block, "redFirst"):
        lacks.append("a red-first grade")
    if not _said(block, "inheritedTests"):
        lacks.append("an inherited-test answer")
    elif block["inheritedTests"] == "not-asked" \
            and not _said(block, "inheritedTestsBasis"):
        lacks.append("the basis of its inherited-test `not-asked`")
    return ("it lacks %s" % (", ".join(lacks),)) if lacks else None


def landing_refusals(phase, live):
    """`[(task id, why), ...]` - every task of `phase` the property refuses,
    in plan order. Empty is the one answer that lands."""
    held = []
    for task in (phase.get("tasks") or []) if isinstance(phase, dict) else []:
        if not isinstance(task, dict):
            continue
        why = landing_problem(task, phase, live)
        if why:
            held.append((str(task.get("id")), why))
    return held


def owed_answer(task, phase, live, answered):
    """Whether a phase review owes `task` its answers: it records a commit, its
    key reads `phase`, it is not a recorded fix task, and no filed phase return
    answers that commit (`answered` is `answered_entries`'s map)."""
    commit = task.get("commit") if isinstance(task, dict) else None
    return bool(commit
                and review_key(task, phase, live)[0] == KEY_PHASE
                and not is_fix_task(task, phase)
                and (str(task.get("id")), commit) not in answered)


# --- the phase return -------------------------------------------------------------
# The keys of one `tasks` entry, read by the filing verb and held equal to the
# return format in `agents/audit-reviewer.md` by `_refs.phase_return_key_drift`.
PHASE_ENTRY_KEYS = ("id", "commit", "answer", "note", "missing", "redFirst",
                    "redFirstBasis", "inheritedTests", "inheritedTestsBasis")
_HEAD_SHAPE = re.compile(r"^[0-9a-f]{7,40}$")


def phase_return_rel(phase_id, head):
    """A phase review's filed return below the evidence directory: keyed on the
    head its brief was computed at, so a review after fix tasks files beside the
    earlier one and a second filing for one head is refused."""
    return "%s/%s/%s.reviewer.json" % (RETURNS_DIRNAME, phase_id,
                                       return_start_key(head))


def head_problem(head):
    """Why `head` cannot key a phase return, or None."""
    return None if _HEAD_SHAPE.match(str(head or "")) else (
        "the head %r is not a commit SHA in lower-case hex" % (head,))


def phase_returns(evidence_dir, phase_id):
    """`[(rel, body, problem), ...]` - every phase return filed for `phase_id`,
    in file-name order. A file that will not parse is listed with its problem,
    never dropped."""
    folder = os.path.join(evidence_dir, RETURNS_DIRNAME, str(phase_id))
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.endswith(".reviewer.json"))
    except OSError:
        return []
    found = []
    for name in names:
        _text, body, problem = read_filed_return(os.path.join(folder, name))
        found.append(("%s/%s/%s" % (RETURNS_DIRNAME, phase_id, name), body,
                      problem))
    return found


def answered_entries(returns):
    """`{(task id, commit): (rel, entry)}` off `phase_returns`'s list - the
    first return to answer a commit; the filing verb refuses a second."""
    answered = {}
    for rel, body, _problem in returns:
        entries = body.get("tasks") if isinstance(body, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("id") and entry.get("commit"):
                answered.setdefault((str(entry["id"]), entry["commit"]),
                                    (rel, entry))
    return answered


def _entry_problems(entry, label):
    problems = ["%s lacks `%s`" % (label, key) for key in PHASE_ENTRY_KEYS
                if key not in entry]
    words = (("answer", REVIEW_ANSWERS),
             ("redFirst", RED_FIRST_WORDS + REVIEWER_ONLY_RED_FIRST),
             ("inheritedTests", INHERITED_WORDS))
    problems += ["%s: `%s` is %r, not one of %s"
                 % (label, key, entry.get(key), ", ".join(vocab))
                 for key, vocab in words
                 if key in entry and entry.get(key) not in vocab]
    if "missing" in entry and not isinstance(entry.get("missing"), list):
        problems.append("%s: `missing` is not a list" % (label,))
    if "redFirstBasis" in entry and not _said(entry, "redFirstBasis"):
        problems.append("%s: `redFirstBasis` is empty" % (label,))
    if entry.get("inheritedTests") == "not-asked" \
            and not _said(entry, "inheritedTestsBasis"):
        problems.append("%s: `inheritedTests` is not-asked with no basis"
                        % (label,))
    return problems


def phase_return_problems(body, phase, live, answered):
    """Every way a phase-mode reviewer return falls short, as sentences: the
    reviewer's shape, then a `tasks` entry for each task owed an answer, whole,
    naming a task of this phase at the commit it records and at a commit no
    earlier filed return answers. Empty is the one answer that files."""
    if not isinstance(body, dict):
        return ["the return is a JSON %s, not an object" % type(body).__name__]
    problems = _reviewer_problems(body)
    tasks = dict((str(t.get("id")), t) for t in (phase.get("tasks") or [])
                 if isinstance(t, dict))
    owed = [tid for tid, t in tasks.items()
            if owed_answer(t, phase, live, answered)]
    entries = body.get("tasks")
    if not isinstance(entries, list):
        return problems + [
            "`tasks` is missing or not a list - a phase review answers each "
            "task owed an answer in its own entry, and this one owes: %s"
            % (", ".join(owed) or "none")]
    seen = []
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            problems.append("tasks entry %d is not an object" % (n,))
            continue
        tid = str(entry.get("id"))
        label = "the entry for %s" % (tid,)
        if tid in seen:
            problems.append("%s is given twice" % (label,))
            continue
        seen.append(tid)
        task = tasks.get(tid)
        if task is None:
            problems.append("%s names a task outside phase %s"
                            % (label, phase.get("id")))
            continue
        problems += _entry_problems(entry, label)
        prior = answered.get((tid, entry.get("commit")))
        if entry.get("commit") != task.get("commit"):
            problems.append("%s names commit %s, and %s records %s"
                            % (label, str(entry.get("commit"))[:12], tid,
                               str(task.get("commit") or "none")[:12]))
        elif prior is not None:
            problems.append("%s: %s already answers %s at %s, so each commit of "
                            "a task is answered once"
                            % (label, prior[0], tid, str(task["commit"])[:12]))
        elif tid not in owed:
            problems.append("%s: %s is owed no answer by this review (its key "
                            "does not read phase, or it is a recorded fix task)"
                            % (label, tid))
    problems += ["the return lacks the entry for %s, which is owed an answer "
                 "at commit %s" % (tid, str(tasks[tid].get("commit"))[:12])
                 for tid in owed if tid not in seen]
    return problems


# --- the answers only a human settles ---------------------------------------------
# A reviewer's `diverges` or `cannot-tell`, a red-first grade of `not-proved` and
# an inherited test `flagged` are the answers no agent settles. The driver's
# triage stops on them and the sign-off verb refuses over them, through this one
# predicate, so the documented verb run by hand cannot sign off what the driver
# would have stopped. A phase intent counts under every review key.
HUMAN_ANSWERS = ("diverges", "cannot-tell")
HUMAN_RED_FIRST = ("not-proved",)
HUMAN_INHERITED = ("flagged",)

# Where a human's settlement is recorded: the driver's state for the phase,
# under `<stateDir>/drive/<phase>.json`, whose `answersAccepted` the triage's
# `--answer accept --reason` writes as `{"keys": [...], "reasons": [...],
# "signatures": [{"key", "sha256"}, ...]}` (`settlement_after`). A key names
# the answer's place - the return's name, the task and the word - and two
# answers filed under one name share it; the signature is the settled return's
# content (`return_signature`), which is what a settlement binds to wherever a
# verdict records what it read. `keys` stays for a reader older than the
# signatures, which reads them alone.
DRIVE_DIRNAME = "drive"
SETTLED_FIELD = "answersAccepted"
SIGNATURES_FIELD = "signatures"
# The driver's mark of a phase review dispatched, `{"head": <sha>, ...}`.
REVIEW_MARK_FIELD = "phaseReview"


def needs_human(returns, settled=(), bound=()):
    """`[{"key", "who", "what", "note", "sha256"}]` - every answer in
    `returns` (`phase_returns`' list) that only a human settles and is not
    settled: a task entry answering `diverges` or `cannot-tell`, grading
    red-first `not-proved` or inherited tests `flagged`, and a phase intent of
    `diverges` or `cannot-tell`. `sha256` is the signature of the return the
    answer sits in. An answer is settled when its key is in `settled` - a
    settlement by name, which only the reading of a verdict recording no read
    set honours - or its `(key, sha256)` pair is in `bound`. Every filed
    return is read, so a review dispatched again does not drop an answer an
    earlier one gave; a return that did not parse adds nothing here, because
    its reader refuses it."""
    found = []
    for rel, body, problem in returns:
        if not isinstance(body, dict):
            continue
        sig = return_signature((rel, body, problem))
        entries = body.get("tasks") if isinstance(body.get("tasks"), list) else []
        for entry in [e for e in entries if isinstance(e, dict)]:
            said = []
            if entry.get("answer") in HUMAN_ANSWERS:
                said.append(("intent %s" % (entry["answer"],), entry.get("note")))
            if entry.get("redFirst") in HUMAN_RED_FIRST:
                said.append(("red-first %s" % (entry["redFirst"],),
                             entry.get("redFirstBasis")))
            if entry.get("inheritedTests") in HUMAN_INHERITED:
                said.append(("inherited tests %s" % (entry["inheritedTests"],),
                             entry.get("inheritedTestsBasis")))
            found += [{"key": "%s#%s#%s" % (rel, entry.get("id"), what),
                       "who": str(entry.get("id")), "what": what, "note": note,
                       "sha256": sig}
                      for what, note in said]
        intent = body.get("intent") if isinstance(body.get("intent"), dict) else {}
        if intent.get("answer") in HUMAN_ANSWERS:
            found.append({"key": "%s#phase" % (rel,), "who": "phase",
                          "what": "intent %s" % (intent["answer"],),
                          "note": intent.get("note"), "sha256": sig})
    taken, pairs = set(settled or ()), set(bound or ())
    return [a for a in found if a["key"] not in taken
            and (a["key"], a["sha256"]) not in pairs]


def drive_state_path(state_dir, phase_id):
    """The driver's state file for `phase_id` under `state_dir`."""
    return os.path.join(str(state_dir), DRIVE_DIRNAME, "%s.json" % (phase_id,))


def drive_state(state_dir, phase_id):
    """`(body, problem)` - the driver's state for the phase, `{}` when it keeps
    none, or why it could not be read; a record that will not parse is a
    problem, never read as an empty one."""
    path = drive_state_path(state_dir, phase_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as exc:
        return {}, "the settlement record %s cannot be read (%s)" % (path, exc)
    return (body if isinstance(body, dict) else {}), ""


def review_marked(body):
    """Whether the driver's state `body` marks a phase review as dispatched at
    a head. Without the mark, the driver's next sign-off pass dispatches the
    phase review again wherever a review skill resolves, before any triage."""
    mark = body.get(REVIEW_MARK_FIELD) if isinstance(body, dict) else None
    return isinstance(mark, dict) and bool(mark.get("head"))


def settlement_record(state_dir, phase_id):
    """`{"keys", "pairs", "reasons", "problem"}` - what the driver's record
    in `state_dir` says a human settled for the phase: the answer keys, the
    `(key, sha256)` pairs binding a key to the content settled, the words they
    were settled with, and why the record could not be read. No record is
    nothing settled; a record that will not parse is a problem, never read as
    nothing settled. A record written before signatures were kept holds keys
    and no pairs."""
    body, problem = drive_state(state_dir, phase_id)
    if problem:
        return {"keys": set(), "pairs": set(), "reasons": [], "problem": problem}
    return settlement_block(body.get(SETTLED_FIELD),
                            drive_state_path(state_dir, phase_id))


def settlement_block(held, path):
    """`settlement_record`'s reading of one `SETTLED_FIELD` block `held`, as
    the record at `path` holds it - the driver reads the state it already
    holds through this rather than the file a second time."""
    nothing = {"keys": set(), "pairs": set(), "reasons": [], "problem": ""}
    if held is None:
        return nothing
    if not isinstance(held, dict):
        return dict(nothing, problem=(
            "the settlement record %s holds `%s` that is not an object"
            % (path, SETTLED_FIELD)))
    signed = held.get(SIGNATURES_FIELD)
    return {"keys": set(str(k) for k in held.get("keys") or []
                        if isinstance(k, str)),
            "pairs": set((s["key"], s["sha256"])
                         for s in (signed if isinstance(signed, list) else [])
                         if isinstance(s, dict) and isinstance(s.get("key"), str)
                         and isinstance(s.get("sha256"), str)),
            "reasons": [str(r) for r in held.get("reasons") or []
                        if isinstance(r, str)],
            "problem": ""}


def settled_answers(state_dir, phase_id):
    """`(keys, reasons, problem)` - `settlement_record`'s keys, words and
    problem, for the reading that honours a settlement by name."""
    record = settlement_record(state_dir, phase_id)
    return record["keys"], record["reasons"], record["problem"]


def settlements(state_dirs, phase_id):
    """`{"keys", "pairs", "reasons", "problems"}` - `settlement_record` read in
    every directory of `state_dirs`, each once, as one union: a settlement any
    of them records is a human's word, and a record that could not be read is
    kept as a problem rather than read as nothing settled there."""
    union = {"keys": set(), "pairs": set(), "reasons": [], "problems": []}
    seen = []
    for state_dir in state_dirs:
        real = os.path.realpath(str(state_dir))
        if real in seen:
            continue
        seen.append(real)
        record = settlement_record(state_dir, phase_id)
        union["keys"] |= record["keys"]
        union["pairs"] |= record["pairs"]
        union["reasons"] += record["reasons"]
        if record["problem"]:
            union["problems"].append(record["problem"])
    return union


def settlement_after(held, answers, reason):
    """The `SETTLED_FIELD` block after a human settled `answers`
    (`needs_human`'s dicts) in the words `reason`, on top of `held`: each
    answer's key appended for an older reader, and its key with the signature
    of the content settled, which is what a newer reader honours. An answer
    carrying no signature - one put to the human before signatures were kept -
    adds its key alone."""
    held = held if isinstance(held, dict) else {}
    return {"keys": list(held.get("keys") or []) + [a["key"] for a in answers],
            "reasons": list(held.get("reasons") or []) + [reason],
            SIGNATURES_FIELD: list(held.get(SIGNATURES_FIELD) or []) + [
                {"key": a["key"], "sha256": a["sha256"]}
                for a in answers if a.get("sha256")]}


def settled_by_name_only(answers, record):
    """The answers in `answers` that `record` (`settlement_record` or
    `settlements`) names by key and binds no signature for: settled before
    signatures were kept, so nothing says which content the human saw."""
    return [a for a in answers if a["key"] in record["keys"]
            and (a["key"], a.get("sha256")) not in record["pairs"]]


def project_in_tree(git_root, project, tree_path):
    """The directory `project` - a directory inside the checkout at
    `git_root` - is in the checkout at `tree_path`, or None when that
    checkout holds none or `project` lies outside `git_root`."""
    if not tree_path:
        return None
    rel = os.path.relpath(os.path.realpath(str(project)),
                          os.path.realpath(str(git_root)))
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    found = os.path.normpath(os.path.join(str(tree_path), rel))
    return found if os.path.isdir(found) else None


def settlement_checkouts(git_root, project, trees):
    """`project` and the same project in every worktree of `trees` (the
    worktree list's records) that git does not report prunable, each once:
    the checkouts whose settlement records a sign-off and a landing both
    honour, so the two read one set."""
    found = [str(project)]
    for tree in trees or []:
        if not isinstance(tree, dict) or tree.get("prunable"):
            continue
        there = project_in_tree(git_root, project, tree.get("path"))
        if there and not any(os.path.realpath(there) == os.path.realpath(f)
                             for f in found):
            found.append(there)
    return found


# --- what a sign-off read ---------------------------------------------------------
# The phase review's record of the filed phase returns its verdict was taken
# over: one `{"return", "sha256"}` row per distinct return. Absent on a verdict
# written before the field existed, which a landing then reads the older way;
# an empty list is a sign-off that read none, which is not the same answer.
READ_RETURNS_FIELD = "readReturns"


def return_signature(entry):
    """The sha256 of one filed return as an answer - `(rel, body, problem)` as
    `phase_returns` lists it: its name, what it holds and why it could not be
    read. Where it sits is not part of it, so a copy is the same answer in any
    checkout or ref; another answer under the name, or the answer under
    another name, is another signature."""
    rel, body, problem = entry
    text = json.dumps([rel, body, problem or ""], sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_record(entries):
    """The rows a sign-off writes under `READ_RETURNS_FIELD` for `entries`,
    one per distinct signature, ordered by name then signature."""
    rows = dict(((rel, return_signature((rel, body, problem))), None)
                for rel, body, problem in entries)
    return [{"return": rel, "sha256": sig} for rel, sig in sorted(rows)]


def read_set(review):
    """The signatures a verdict records as read, or None when the review
    records no read set - a verdict written before the field."""
    held = review.get(READ_RETURNS_FIELD) if isinstance(review, dict) else None
    if not isinstance(held, list):
        return None
    return set(str(r.get("sha256")) for r in held
               if isinstance(r, dict) and r.get("sha256"))


def read_names(review):
    """The return names a verdict records as read - empty when it records no
    read set. A later return under one of them with another signature is
    another answer under a name the verdict read."""
    held = review.get(READ_RETURNS_FIELD) if isinstance(review, dict) else None
    return set(str(r.get("return")) for r in (held if isinstance(held, list)
                                               else [])
               if isinstance(r, dict) and r.get("return"))


def _git(git_root, args):
    """`(code, stdout bytes)` of one git call; code None when git could not
    be run at all."""
    try:
        done = subprocess.run(["git", "-C", git_root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        return None, b""
    return done.returncode, done.stdout


def ref_known(git_root, ref):
    """True when `ref` names a branch, False when git says it names none, None
    when git could not be asked."""
    code, _out = _git(git_root, ["rev-parse", "--verify", "-q",
                                 "refs/heads/%s" % (ref,)])
    return {0: True, 1: False}.get(code)


def ref_phase_returns(git_root, ref, rel, phase_id):
    """`[(rel, body, problem)]` - the phase returns branch `ref` commits under
    `rel` (root-relative, `/`-separated), named as the filing verb names them
    on disk. A listing git would not give is a problem entry, never no return
    filed: an unread tree is not an empty one."""
    code, out = _git(git_root, ["ls-tree", "-r", "--name-only", "-z",
                                "refs/heads/%s" % (ref,), "--", rel])
    if code != 0:
        return [("%s:%s" % (ref, rel), None,
                 "git would not list %s at %s" % (rel, ref))]
    paths = [p for p in out.decode("utf-8", "replace").split("\0") if p]
    found = []
    for path in sorted(p for p in paths if p.endswith(".reviewer.json")
                       and posixpath.dirname(p) == rel):
        code, raw = _git(git_root, ["cat-file", "blob", "refs/heads/%s:%s"
                                    % (ref, path)])
        text = raw.decode("utf-8", "replace") if code == 0 else None
        body, problem = return_body(text, "%s:%s" % (ref, path))
        found.append(("%s/%s/%s" % (RETURNS_DIRNAME, phase_id,
                                    posixpath.basename(path)), body, problem))
    return found


def tip_phase_returns(checkout, evidence_dir, ref, phase_id):
    """`(returns, why)` - the phase returns branch `ref` commits in the
    repository holding `checkout`, at the place `evidence_dir` sits in it.
    `why` says, with no returns, why none could be read: no repository, an
    evidence directory outside it, or a ref git does not have."""
    code, out = _git(checkout, ["rev-parse", "--show-toplevel"])
    if code != 0:
        return [], "%s is in no git repository git would name" % (checkout,)
    top = out.decode("utf-8", "replace").strip()
    folder = os.path.join(evidence_dir, RETURNS_DIRNAME, str(phase_id))
    rel = os.path.relpath(os.path.realpath(folder),
                          os.path.realpath(top)).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return [], "%s lies outside the repository at %s" % (folder, top)
    known = ref_known(top, ref)
    if known is not True:
        return [], ("%s is not a branch in %s" % (ref, top) if known is False
                    else "git could not say whether %s is a branch" % (ref,))
    return ref_phase_returns(top, ref, rel, phase_id), ""
