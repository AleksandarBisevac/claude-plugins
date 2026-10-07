#!/usr/bin/env python3
"""
Where an agent's filed return lives, what shape it must have, and how it is read.

An agent's return used to be prose the main loop read and retyped, so nothing
checked its shape and a close carried whatever the retyping kept. A return is now
FILED: `audit-task.py file-return` writes it, `audit-task.py done` and
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

WHAT NOTHING HERE CHECKS: the task id and the role are the caller's word.

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
    """Every way `body` falls short of the shape `role` declares, as sentences
    naming the field - read off `agents/audit-executor.md`'s and
    `agents/audit-reviewer.md`'s return blocks. Empty is the one answer that
    files; a role this module does not know is a problem too, never a pass."""
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
