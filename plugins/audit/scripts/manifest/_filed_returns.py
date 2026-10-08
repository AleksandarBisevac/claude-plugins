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
`close-phase.py`, and a rule held twice is two rules.

WHAT NOTHING HERE CHECKS: the task id, the role and the head are the caller's
word.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__filed_returns.py` - see `plugins/audit/tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
import json
import os
import re
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
        return text, json.loads(text), None
    except (OSError, ValueError) as exc:
        return None, None, "%s cannot be read as JSON (%s)" % (path, exc)


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
