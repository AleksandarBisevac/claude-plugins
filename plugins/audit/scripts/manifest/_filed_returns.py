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
    `<start>` is the task's current `startedAt`. A re-start re-stamps it
    through `next_start_at`, which keeps a task's starts strictly increasing
    even inside one second, so a retry's return lands beside the earlier
    attempt's and never over it, and a return from an earlier start is never
    read as this one's;
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

THE ANSWERS A SCRIPT GIVES are here for the same reason: the filing verb
fills them into a phase return (`complete_phase_return`) and the phase brief
tells the reviewer which they are, both from `phase_answers`.

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
`tests/test__filed_returns.py` - see `tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
import ast
import calendar
import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
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

import _machine_paths  # noqa: E402  (what a committed file may not say, and its redaction)


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
# `fr7` in `tests/test__filed_returns.py` holds this tuple equal to
# the enum.
RED_FIRST_WORDS = ("proved", "could-not-prove", "not-attempted")

# The executor's binding of each declared test to the case that carries it: a
# list parallel to `tests.add`, by index.
CASES_FIELD = "casesAdded"
# The drive's own reading of that binding, written into the filed return at
# `submit` beside the stamp: what the reviewer's brief prints as the gaps.
GAPS_FIELD = "testsAddGaps"
# The entries whose ids were never compared with a printed label because the
# submit's command did not run their suite (`case_binding_unchecked`): filed
# beside the gaps, so the reviewer's brief shows what no one graded and an id
# that was never compared does not read as one that passed.
UNCHECKED_FIELD = "testsAddUnchecked"

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


START_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _start_epoch(stamp):
    """`stamp` as epoch seconds, or None when it is not a `START_AT_FORMAT`
    stamp."""
    try:
        return calendar.timegm(time.strptime(str(stamp), START_AT_FORMAT))
    except (TypeError, ValueError):
        return None


def next_start_at(previous, now):
    """The `startedAt` a start of a task stamps, given the task's `previous`
    one and the clock's `now`, both `START_AT_FORMAT`.

    Every place that keys by start - the return path above, the driver's
    per-start marks, the brief file, the retry reason - reads
    `return_start_key(startedAt)`, and the stamp has one-second resolution, so a
    restart inside the second of the start it replaces would share that start's
    key and read its return, marks and brief as its own. The identity is made
    here instead, once, at the one place a start is stamped: a `now` at or
    before `previous` becomes the second after `previous`, so a task's starts
    are strictly increasing and no two share a key. The key's spelling is left
    as it was, which is what keeps every return already filed under it found
    for the start it answers. A `now` in a later second is returned as read,
    so `startedAt` is the wall clock except in that one case, where it runs
    ahead of it by the restarts that shared a second.

    A `previous` that is not a stamp of this format bounds nothing and `now`
    is returned; a hand-written `startedAt` the format does not read is the
    one start this cannot order."""
    last = _start_epoch(previous)
    read = _start_epoch(now)
    if last is None or read is None or read > last:
        return now
    return time.strftime(START_AT_FORMAT, time.gmtime(last + 1))


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


# The floor below which an outcome's text reads as unwritten rather than
# reported, not merely terse: a bare word standing in for the real text
# ("placeholder" and "pending" among them) always falls under it, while a
# sentence stating what changed does not. Stated beside the check so the
# number and its reason travel together.
_OUTCOME_FLOOR = 12
# The words that stand in for unwritten text WHOLE - the entire trimmed
# outcome, folded to one case, is one of these, never a word met in passing.
# A real sentence is free to use any of them while describing what it did
# (this very check among the things worth describing as a "placeholder"), so
# the match is against the whole text, not a substring search.
_TEMPLATE_WORD = ("placeholder", "pending", "todo", "tbd")
# The shape a template leaves when nobody fills it in (`<what changed>`) -
# again read WHOLE: real prose naming a path (`<home>/...`) or an id
# (`<taskId>`) carries the same bracket shape as a substring without being
# one, so only a text that IS nothing but one such token is refused.
_TEMPLATE_ANGLE_WHOLE = re.compile(r"^<[^<>]{1,80}>$")


def _template_reason(text):
    """Why `text` reads as a template left unfilled rather than a written
    outcome, or None: the WHOLE trimmed text is one of the bare template
    words, or the whole text is a single unfilled `<...>` token - never a
    template word or an angle-bracket span merely present somewhere in a
    real sentence."""
    if text.lower() in _TEMPLATE_WORD:
        return "is the bare template word `%s` in place of the real text" % (text.lower(),)
    if _TEMPLATE_ANGLE_WHOLE.match(text):
        return "is an unfilled `<...>` placeholder, not the real text"
    return None


def _outcome_problems(outcome):
    """What `outcome.technical`/`outcome.descriptive` lack beyond being
    present and non-empty: either text under `_OUTCOME_FLOOR`, either carrying
    a template word or an unfilled `<...>`, or the two given identical - the
    shapes every outcome this check exists to catch took, so the same start
    can be resubmitted with the real text rather than the filing staying
    uncorrectable."""
    problems = []
    texts = {}
    for half in ("technical", "descriptive"):
        text = outcome.get(half)
        if not (isinstance(text, str) and text.strip()):
            continue
        stripped = text.strip()
        texts[half] = stripped
        if len(stripped) < _OUTCOME_FLOOR:
            problems.append(
                "`outcome.%s` is %d character(s), under the floor of %d "
                "characters beside this check - it reads as unwritten, not "
                "merely terse" % (half, len(stripped), _OUTCOME_FLOOR))
        reason = _template_reason(stripped)
        if reason:
            problems.append("`outcome.%s` %s" % (half, reason))
    if len(texts) == 2 and texts["technical"] == texts["descriptive"]:
        problems.append(
            "`outcome.technical` and `outcome.descriptive` are identical "
            "(%r) - say what changed and what it means for a reader "
            "separately" % (texts["technical"],))
    return problems


def _tests_add_empty_problem(added, task):
    """Why `added` (the return's `testsAdded`) is refused for `task`, or
    None: a tdd or regression task whose plan declares `tests.add` cases owes
    at least one filed title, so an empty list under those modes is the shape
    every return that filed no test at all took."""
    if not isinstance(task, dict) or added != []:
        return None
    tests = task.get("tests") or {}
    mode = tests.get("mode")
    declared = tests.get("add") or []
    if mode not in ("tdd", "regression") or not declared:
        return None
    return ("`testsAdded` is empty while the task's tests.add names %d "
            "case(s) and tests.mode is %s - name the filed titles"
            % (len(declared), mode))


def _cases_added_problems(cases):
    """Why the return's `casesAdded` cannot be read as a binding, as a list of
    sentences. The field is optional in the shape - an absent one is a gap per
    declared entry (`case_binding_gaps`), which is what a reviewer reads - but
    one that is present must hold, per entry, a case id, a list of ids, or null
    for an entry that carries no case."""
    if not isinstance(cases, list):
        return ["`%s` is not a list (one case id per tests.add entry, by index)"
                % (CASES_FIELD,)]
    return ["`%s[%d]` is %r, not a case id, a list of case ids or null"
            % (CASES_FIELD, i, item) for i, item in enumerate(cases)
            if item is not None and _bound_ids(item) is None]


def _executor_problems(body, task=None):
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
        problems += _outcome_problems(outcome)
    added = body.get("testsAdded")
    if not (isinstance(added, list) and all(isinstance(t, str) for t in added)):
        problems.append("`testsAdded` is missing or not a list of names")
    else:
        gap = _tests_add_empty_problem(added, task)
        if gap:
            problems.append(gap)
    if CASES_FIELD in body:
        problems += _cases_added_problems(body[CASES_FIELD])
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


def _clause_quoted(description, note, span=4):
    """Whether `note` quotes a run of `span` consecutive words from
    `description` verbatim (case/whitespace folded only, no stemming or
    synonym matching). Probe 2 (24 reviewer runs, Opus/Sonnet/Haiku, the real
    P5.3 brief section) found that judging `matches` against the executor's
    restatement alone found 0/3 divergences on every phrasing tried; only
    requiring the note to quote the task's own clause found the planted
    divergence on all three models. A description shorter than `span` words
    is quoted only by containing it whole."""
    d_words = (description or "").lower().split()
    note_n = " ".join((note or "").lower().split())
    if not d_words:
        return False
    if len(d_words) < span:
        return " ".join(d_words) in note_n
    return any(" ".join(d_words[i:i + span]) in note_n
              for i in range(len(d_words) - span + 1))


def unsupported_match_basis(description, note):
    """None, or why a `matches` intent is unsupported: `note` quotes no
    clause of the task's own `description`, so the answer is graded against
    the executor's restatement alone rather than against what was asked -
    exactly the gap P5.3 fell through (its text said a card's `src` is set
    when it ENTERS the viewport; the executor's note said only that a 200px
    `rootMargin` makes the card load, and a reviewer handed that restatement
    alone answered `matches`)."""
    if not isinstance(description, str) or not description.strip():
        return None
    if not isinstance(note, str) or not note.strip():
        return None
    if _clause_quoted(description, note):
        return None
    return ("quotes no clause of the task's own description - note: %r; "
            "description: %r" % (note.strip(), description.strip()))


def claim_section(task, filed_return):
    """The reviewer-facing block for one task: the task's own `description`
    FIRST, then the executor's filed return LAST and labelled as the claim
    under review - never the reverse. A brief that put the executor's
    restatement ahead of (or in place of) the task's own words let a reviewer
    grade a renamed scope against itself: P5.3's text said a card's `src` is
    set when it ENTERS the viewport, the executor shipped a 200px
    `rootMargin` and renamed its test to "once the card is near the
    viewport", and a reviewer handed only that restatement answered
    `matches`. Putting the task text first and labelling the return as the
    claim is what a reader - human or model - needs to judge one against the
    other instead of reading the second as a paraphrase of the first.

    `filed_return` is either the return AS FILED (a string, printed
    byte-identical - the rule `audit-lookup.py`'s module docstring states for
    the reviewer's brief) or a dict, for a caller with no literal text on
    hand (`json.dumps`'d, sorted).

    IN `_filed_returns.py` RATHER THAN IN EITHER ENTRY POINT THAT CALLS IT.
    `audit-lookup.py` composes the brief and `drive-phase.py` grades the
    tests.add gap the same brief states - two entry points, which
    `_deps.layer_violations()` refuses to let runtime-load each other - so
    the one home for logic both need is a module below them both, the same
    reason `case_binding_gaps` and `floor_contradicted_clause` sit here too."""
    body = (filed_return if isinstance(filed_return, str)
            else json.dumps(filed_return, indent=2, sort_keys=True))
    return "\n".join([
        "## Task", (task.get("description") or "").strip(), "",
        "## Claim under review (the executor's filed return)", body])


def title_names_clause(title, clause):
    """Whether a case's printed title is `clause`, or `clause` followed by its
    detail after ` (` - the red-first helper's reading of `--case NAME`. It is
    not how a declared test is matched to the case that carries it: that is a
    binding by id (`case_binding_gaps`). A paraphrase, a title that merely starts
    with the clause's letters, and an empty clause do not match. Read in place,
    so a long detail costs no prefix copy.

    The suites print a case as `<id> <title>`, so exactly one leading case-id
    token and one space may come before the clause. The id shape is the one
    the runner's output reader treats as a case id (`_CASE_ID_TOKEN`); a second
    token, an id glued to the clause and a paraphrase still do not match."""
    if not clause or not title:
        return False
    return (_names_at(title, clause, 0)
            or _names_at(title, clause, _after_case_id(title)))


# The shape of a case id as the runner's output reader reads one.
_CASE_ID_TOKEN = re.compile(r"^[A-Za-z][A-Za-z_-]*[0-9][A-Za-z0-9_-]*$")


def _after_case_id(title):
    """Offset just past a leading `<id> `, or -1 when the title opens with no
    case-id token followed by one space."""
    gap = title.find(" ")
    if gap < 1 or not _CASE_ID_TOKEN.match(title[:gap]):
        return -1
    return gap + 1


def _names_at(title, clause, start):
    """Whether `title` carries `clause` at `start`, ending the title or
    followed by ` (`."""
    if start < 0 or not title.startswith(clause, start):
        return False
    end = start + len(clause)
    return end == len(title) or title.startswith(" (", end)


def _bound_ids(binding):
    """The case ids one `casesAdded` item names, or None when it names none: a
    non-empty word, or a non-empty list of them."""
    items = [binding] if isinstance(binding, str) else binding
    if not isinstance(items, list) or not items:
        return None
    if not all(isinstance(i, str) and i.strip() for i in items):
        return None
    return [i.strip() for i in items]


def _printed_ids(printed):
    """What a bound id may equal: each printed label whole, and its leading
    token when that token is id-shaped (`_CASE_ID_TOKEN`) - so an id-less
    label's first word is no id, and a prefix of an id is none either."""
    ids = set()
    for label in printed:
        label = str(label).strip()
        ids.add(label)
        head = label.split(None, 1)
        if head and _CASE_ID_TOKEN.match(head[0]):
            ids.add(head[0])
    return ids


def _entry_suite(entry):
    """The suite path a `tests.add` entry names: the text before its first colon."""
    return str(entry).split(":", 1)[0].strip().replace("\\", "/")


def _command_names_suite(command, suite):
    """Whether one argv token of `command` is `suite`, a path ending in it or a
    path it ends, with a `::selector` left off - so a `./`-prefixed path, the
    bare file name run from its own directory and the path with a pytest-style
    selector after it all name the same suite."""
    for token in command:
        token = str(token).split("::", 1)[0].replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        if token and (token == suite or suite.endswith("/" + token)
                      or token.endswith("/" + suite)):
            return True
    return False


def _suites_run(task, command):
    """The set of declared suite paths `command` names, or None when it names
    none of them (a runner given a directory or a whole sweep): then nothing
    says which suites ran and every entry is graded as before."""
    if command is None:
        return None
    suites = {_entry_suite(e) for e in
              ((task or {}).get("tests") or {}).get("add") or []}
    named = {s for s in suites if _command_names_suite(command, s)}
    return named or None


def case_binding_unchecked(task, command):
    """One sentence per declared `tests.add` entry whose suite the submit's
    `command` did not run, each opening with the entry itself. Those ids are
    not graded against what the command printed - it printed nothing of that
    suite - so they are reported as not checked and never as unprinted. Empty
    when `command` names none of the declared suites, since nothing then says
    which ran."""
    ran = _suites_run(task, command)
    if ran is None:
        return []
    return ["%s - not checked: the submit's command did not run `%s`, so the "
            "ids bound to it were not compared with any printed label"
            % (str(e), _entry_suite(e))
            for e in ((task or {}).get("tests") or {}).get("add") or []
            if _entry_suite(e) not in ran]


def case_binding_gaps(task, cases_added, printed, command=None):
    """One sentence per declared `tests.add` entry the return does not bind to
    a case the suite printed, each opening with the entry itself.

    THE BINDING IS BY ID AND BY INDEX. `cases_added[i]` is the case id (or list
    of ids, when one entry covers several cases) the executor says carries
    `tests.add[i]`; the wording of a title is nobody's business, which is why a
    return naming the right case draws nothing whatever its titles say. An
    entry with no item, a null one or one not readable as ids is a gap; so is
    an id the suite did not print. `printed` is the list of labels the test
    command printed, or None when its runner prints none the drive reads - then
    only the presence of a binding is graded, and the caller says the ids were
    not checked. Items past the declared list add nothing.

    AN ID IS GRADED ONLY AGAINST THE SUITE ITS ENTRY NAMES. `command` is the
    argv the submit ran: an entry whose suite it did not run has its ids left
    ungraded (`case_binding_unchecked` says so), because the labels printed are
    another suite's and the id can only read as missing from them."""
    declared = [str(e) for e in ((task or {}).get("tests") or {}).get("add") or []]
    given = cases_added if isinstance(cases_added, list) else []
    seen = _printed_ids(printed) if printed is not None else None
    ran = _suites_run(task, command)
    gaps = []
    for index, entry in enumerate(declared):
        ids = _bound_ids(given[index]) if index < len(given) else None
        if ids is None:
            gaps.append("%s - no case id bound (`%s[%d]` is absent or not an id)"
                        % (entry, CASES_FIELD, index))
            continue
        if ran is not None and _entry_suite(entry) not in ran:
            continue
        gaps += ["%s - bound to `%s`, which the suite did not print"
                 % (entry, one) for one in ids
                 if seen is not None and one not in seen]
    return gaps


_CONTRADICTED_CLAUSE_MARKER = "contradicts task clause"


def floor_contradicted_clause(findings):
    """`findings` with a `low` severity raised to `med` wherever its `issue`
    names a contradicted task clause (`_CONTRADICTED_CLAUSE_MARKER`). Probe 2
    measured 4 of 6 Opus/Sonnet runs rating a contradicted clause `low`,
    which review-convergence would park as a carried low rather than a
    finding a fix task is owed for - so the floor is mechanical, not left to
    the model that wrote the finding."""
    out = []
    for finding in findings or []:
        if (isinstance(finding, dict) and finding.get("severity") == "low"
                and _CONTRADICTED_CLAUSE_MARKER in (finding.get("issue") or "")):
            finding = dict(finding, severity="med")
        out.append(finding)
    return out


def _reviewer_problems(body, task=None):
    problems = []
    if not isinstance(body.get("findings"), list):
        problems.append("`findings` is missing or not a list")
    intent = body.get("intent")
    if not isinstance(intent, dict):
        problems.append("`intent` is missing or not an object")
    elif intent.get("answer") not in REVIEW_ANSWERS:
        problems.append("`intent.answer` is %r, not one of %s"
                        % (intent.get("answer"), ", ".join(REVIEW_ANSWERS)))
    elif intent.get("answer") == "matches" and isinstance(task, dict):
        unsupported = unsupported_match_basis(task.get("description"),
                                              intent.get("note"))
        if unsupported:
            problems.append("`intent.answer` is `matches` but `intent.note` %s"
                            % (unsupported,))
    if body.get("verdict") not in REVIEW_VERDICTS:
        problems.append("`verdict` is %r, not one of %s"
                        % (body.get("verdict"), ", ".join(REVIEW_VERDICTS)))
    return problems


def return_problems(role, body, task=None):
    """Every way `body` falls short of the shape `role` files with, as sentences
    naming the field - `agents/audit-executor.md`'s and
    `agents/audit-reviewer.md`'s return blocks, plus the executor's `stamp`,
    which `drive-phase.py submit` takes rather than the agent. Empty is the one
    answer that files; a role this module does not know is a problem too,
    never a pass. `task` is the reviewed task (when the caller has one, in
    `mode: task`): a reviewer's `matches` answer whose `intent.note` quotes
    none of the task's own `description` is refused as unsupported, not
    merely accepted as a shape match."""
    if role not in RETURN_ROLES:
        return ["the role %r is not one of %s" % (role, ", ".join(RETURN_ROLES))]
    if not isinstance(body, dict):
        return ["the return is a JSON %s, not an object" % type(body).__name__]
    return _executor_problems(body, task) if role == "executor" \
        else _reviewer_problems(body, task)


# --- the write and the read -------------------------------------------------------
def _checkout_above(path):
    """The directory above `path` holding a `.git`, else None - the root the
    scrub spells in-repo paths against."""
    here = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def scrubbed_return_text(path, text):
    """`text` as a committed return may say it: a JSON document has every string
    passed through `_machine_paths.scrubbed_values`, and one with no machine
    path comes back byte for byte. Text that does not parse is returned as it is
    - the callers judge the shape before they write."""
    try:
        body = json.loads(text)
    except ValueError:
        return text
    clean = _machine_paths.scrubbed_values(_checkout_above(path), body)
    return text if clean == body else json.dumps(clean, indent=2) + "\n"


def file_once(path, text):
    """Write `text` to `path` scrubbed of machine paths, creating it; raises
    `FileExistsError` when a return is already filed there, which leaves that
    one untouched.

    THE ONE WRITER OF A COMMITTED RETURN, and the scrub is its own so no caller
    has to remember it: a stamp taken in a task's worktree, or a claim quoting a
    path, lands under `docs/audit/evidence/returns` like any other committed
    file. `_output.returns_writer_violations()` refuses a second route."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = scrubbed_return_text(path, text)
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


def claims_from_return(evidence_dir, task, journal_rows, checkout):
    """`(claims, problem)` - the `claims` text of `task`'s executor return for its
    current start, verbatim, or None when there is none to carry: no start, no
    return filed, or a return that carries no `claims`. A filed return that will
    not parse is the problem, not an absence, and so is one edited after its
    filing row recorded it: the read is `read_filed_return_checked`'s, and there
    is no plain-read form left to fall back to, because the claims go into the
    commit a close stands on. `journal_rows` None is a journal the caller could
    not read; the read then goes on unchecked, as the checked read describes."""
    path = return_path(evidence_dir, task, "executor")
    _text, body, problem, _unchecked = read_filed_return_checked(
        path, journal_rows, checkout)
    if problem:
        return None, problem
    claims = (body or {}).get("claims")
    return (claims if isinstance(claims, str) and claims.strip() else None), None


# --- the filed-return journal row --------------------------------------------------
# A FILED RETURN'S "ONCE" USED TO REST ON THE FILE ALONE. `file_once`'s exclusive
# create refuses a second write to a path that still exists, but an executor once
# filed a placeholder return, DELETED it, and filed again - and nothing recorded
# either filing, because nothing but the file's own presence ever asked the
# question. `RETURN_FILED_ACTION` is the journal row kind this adds: once a
# return is written, the caller that can also reach `_journal_io` appends one, and
# a later filing is refused by that ROW even with the first file gone.
#
# WHY THE APPEND AND THE REFUSAL LIVE HERE AND THE WRITE DOES NOT. `_journal_io`
# sits in this module's OWN LAYER (`_deps.LAYERS`), and a layer-mate may not
# import another - the same rule that keeps `_manifest_io` and `_journal_io`
# apart. So this module owns the row's SHAPE (what a filing puts in it, what a
# later filing's own path must match to be refused, what a changed file's digest
# must match to read clean) and never calls `_journal_io` itself: `drive-phase.py
# submit` is the one caller that writes the file (through `audit-task.py
# file-return`) AND can reach the journal, so it is the one that reads the rows
# in, asks `refiling_refusal` (through its `already_filed`) before asking the
# filing verb to write and puts that refusal, which names the first filing's
# row, into its stop, and appends `filed_return_row`'s entry once that write
# succeeds. A closer reads the
# rows in the same way and hands them to `read_filed_return_checked`.
RETURN_FILED_ACTION = "task.return.filed"


def return_target(path, checkout):
    """`path` spelled repo-relative to `checkout`, posix-separated - the same
    spelling `_journal_io.append`'s `_normalised_target` leaves an already
    relative target at, so a row this module reads back compares like with
    like. None when `path` names no checkout, or sits outside it, or the two
    paths cannot be compared at all (a different drive on Windows)."""
    if not (path and checkout):
        return None
    try:
        rel = os.path.relpath(os.path.realpath(str(path)),
                              os.path.realpath(str(checkout)))
    except ValueError:
        return None
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


def return_digest(path):
    """sha256:<hex> of `path`'s bytes, spelled exactly as `_journal_io.file_hash`
    spells a row's `stateHash` - duplicated rather than imported, for the layer
    reason `RETURN_FILED_ACTION`'s note states, and pinned equal to it by a case
    in `tests/test__filed_returns.py` so the two spellings cannot
    drift apart in silence. None when `path` cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError:
        return None


def _opens_for_reading(call):
    """True when `call` is `open(...)`, or `<x>.open(...)`, in a reading mode:
    no mode at all, or one with no write, append, create or update in it."""
    func = call.func
    if getattr(func, "id", None) != "open" and getattr(func, "attr", None) != "open":
        return False
    modes = [kw.value for kw in call.keywords if kw.arg == "mode"]
    mode = call.args[1] if len(call.args) > 1 else (modes[0] if modes else None)
    if mode is None:
        return True
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return True
    return not set(mode.value) & set("wax+")


def _calls_sha256(call):
    func = call.func
    return (getattr(func, "attr", None) == "sha256"
            and getattr(getattr(func, "value", None), "id", None) == "hashlib")


def file_digest_sites(source):
    """The names of every function in `source` that opens a file to read and
    takes a sha256 in the same body, sorted - each one a place a file's digest
    is computed.

    A filing row's digest and the checked read's must come from one reading of
    the bytes on disk. The row's is `_journal_io.file_hash`, taken at the
    append, and the read's is `return_digest`; a third site - most dangerously
    one hashing what a text-mode read hands back, which on Windows is the text
    after newline translation rather than the bytes - would disagree with the
    row on every CRLF file while agreeing with it on this platform. Hashing text
    a caller handed over is not a site: no file is opened there."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)]
        if (any(_opens_for_reading(c) for c in calls)
                and any(_calls_sha256(c) for c in calls)):
            found.append(node.name)
    return sorted(found)


def filed_return_row(path, checkout, task_id, role, red_status):
    """The journal entry `drive-phase.py submit` appends right after `path` is
    written: `action` names the row kind, and `target` is `path` spelled the
    way a later filing's own target is compared against (`already_filed_row`).
    The task, the start and the role all travel in it already - `return_rel`
    already spells them into the path `target` carries - and `summary` restates
    the task, the role and the red-first verdict for a human reading the trail
    without parsing it. `details.taskId` repeats the task id as a STRUCTURED
    field besides: it is already one of `_journal_io.DETAILS_KEYS`, so carrying
    it there asks for no new allow-listed key. None when `path` names no target
    at all - nothing this module can file a row about."""
    target = return_target(path, checkout)
    if target is None:
        return None
    return {"action": RETURN_FILED_ACTION, "target": target,
            "summary": "%s %s return filed (redFirst: %s)"
                      % (task_id, role, red_status or "n/a"),
            "details": {"taskId": str(task_id)}}


def already_filed_row(rows, path, checkout):
    """The `RETURN_FILED_ACTION` row among `rows` (a journal's full read,
    oldest first - `_journal_io.read_all`'s list) that already names `path`'s
    own target, else None: the signal a retry is refused by even once the
    first filing's FILE has been deleted."""
    target = return_target(path, checkout)
    if target is None:
        return None
    for row in rows or []:
        if (isinstance(row, dict) and row.get("action") == RETURN_FILED_ACTION
                and row.get("target") == target):
            return row
    return None


def refiling_refusal(rows, path, checkout):
    """Why `path` may not be filed again, naming the earlier filing's own
    journal row, or None: the row is what makes a filing stay "once" even
    after its file is deleted, which the exclusive create alone cannot do."""
    row = already_filed_row(rows, path, checkout)
    if row is None:
        return None
    return ("a %s row already filed this return, at %s (stateHash %s) - "
            "deleting the file does not undo that filing"
            % (RETURN_FILED_ACTION, row.get("ts") or "an unknown time",
               row.get("stateHash") or "none recorded"))


def _missing_problem(path, recorded):
    """Why a return the journal recorded filed is refused when its file is
    gone: deleting it undoes nothing the row recorded, and reading it as
    unfiled would let a close fall through to a rule meant for a review nobody
    ran."""
    return ("%s is missing: the journal recorded it filed (digest %s) and the "
            "file is gone" % (path, recorded or "none recorded"))


def filed_digest_problem(path, row):
    """None, or why `path` is refused against the `RETURN_FILED_ACTION` row
    that named it: the row's own recorded `stateHash` and what `path` hashes to
    NOW, stated together, when the two disagree - a return edited after it was
    filed, never read silently as it now stands. None too when `row` carries
    no `stateHash` to compare against (a row from before this field, or none
    at all)."""
    recorded = row.get("stateHash") if isinstance(row, dict) else None
    if not recorded:
        return None
    present = return_digest(path)
    if present == recorded:
        return None
    if present is None:
        return _missing_problem(path, recorded)
    return ("%s has changed since the journal recorded it filed: the row "
            "carries %s and it now hashes to %s" % (path, recorded, present))


def filed_mismatch(path, rows, checkout):
    """`filed_digest_problem` against the `RETURN_FILED_ACTION` row among
    `rows` that names `path`, or None when none names it - the refusal half of
    `read_filed_return_checked`, for a close that must refuse an edited return
    without taking anything else from it."""
    row = already_filed_row(rows, path, checkout)
    return filed_digest_problem(path, row) if row is not None else None


# The words a read with nothing to check against carries, which a close prints.
UNCHECKED_LEAD = "not checked against a filing row"


def _unchecked_note(path, rows, checkout, row):
    """The sentence a return read with no digest to compare carries."""
    named = return_target(path, checkout) or path
    if rows is None:
        why = "no journal was read to check it against"
    elif row is None:
        why = ("no %s journal row names it (a return filed before such rows "
               "were written, or by a route that writes none)"
               % (RETURN_FILED_ACTION,))
    else:
        why = "the %s row naming it records no digest" % (RETURN_FILED_ACTION,)
    return "%s - %s, so it was read as it stands: %s" % (UNCHECKED_LEAD, why,
                                                          named)


def read_filed_return_checked(path, rows, checkout):
    """`(text, body, problem, unchecked)`: `read_filed_return`, refused when
    `path`'s current bytes disagree with the `RETURN_FILED_ACTION` row the
    journal already carries for it. THE READ EVERY CLOSER MAKES -
    `plain_read_violations` reports a closer reaching the plain one - so a
    return edited after it was filed is a problem, never read as it now stands
    with nothing to say so. A return whose file is GONE while a filing row
    names it is a problem too (the row's digest and the missing file), never
    four Nones: only a return no row names reads as unfiled.

    `rows` is the journal's full read (`_journal_io.read_all`), or None when the
    caller could not read it; this module may not import `_journal_io`, so the
    read is the caller's. `unchecked` is None when a row's digest vouched for
    the bytes, or when nothing was read; otherwise it is the sentence saying
    the return was read with nothing to compare it against - a return filed
    before filing rows existed reads as it always did, and says so, rather
    than being refused or passing as checked."""
    text, body, problem = read_filed_return(path)
    if text is None:
        if problem is None and not (path and os.path.isfile(path)):
            gone = already_filed_row(rows, path, checkout)
            if gone is not None:
                return None, None, _missing_problem(
                    path, gone.get("stateHash")), None
        return text, body, problem, None
    row = already_filed_row(rows, path, checkout)
    if row is None or not row.get("stateHash"):
        return text, body, problem, _unchecked_note(path, rows, checkout, row)
    mismatch = filed_digest_problem(path, row)
    if mismatch:
        return None, None, mismatch, None
    return text, body, problem, None


# --- the closers' one read --------------------------------------------------------
# THE INVARIANT, NOT A LIST OF CALL SITES. The checked read existed for a while
# with no closer calling it, so a return edited after filing still closed its
# task. Every module under `scripts/` but this one is held to it: a call to the
# plain read anywhere else is reported by file and function, unless the table
# below names that function with its reason. A reason is owed because the
# exemption is a claim that the read closes nothing.
PLAIN_READ = "read_filed_return"
PLAIN_READ_HOME = "manifest/_filed_returns.py"
PLAIN_READ_EXEMPT = {
    "governance/drive-phase.py::filed_at_head":
        "a PHASE review's return, read for its findings and the mark the drive "
        "keeps: it closes no task, and no filing row is written for one",
    "governance/drive-phase.py::triage":
        "a PHASE review's return, read to triage its findings: it closes no "
        "task, and no filing row is written for one",
}


def _plain_read_sites(tree):
    """`[(line, function)]` for every call reaching the plain read in `tree`:
    an attribute or a bare name spelled `PLAIN_READ`, and any name an
    `from ... import` binds it to under an alias."""
    aliases = set([PLAIN_READ])
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            aliases.update(a.asname or a.name for a in node.names
                           if a.name == PLAIN_READ)
    sites = []

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            here = (child.name if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else where)
            if isinstance(child, ast.Call):
                fn = child.func
                if ((isinstance(fn, ast.Attribute) and fn.attr == PLAIN_READ)
                        or (isinstance(fn, ast.Name) and fn.id in aliases)):
                    sites.append((child.lineno, here))
            visit(child, here)
    visit(tree, "<module>")
    return sorted(sites)


def plain_read_violations(script_dir=None, exempt=None):
    """`(file, what)` for every call to the plain read outside this module that
    the exemption table does not name, for every exemption naming a function
    that no longer makes one, and for a tree without this module - BLIND, not
    clean.

    WHAT IT CANNOT SEE: a read reached through `getattr` or a name assigned
    from the function at runtime, and a module that parses a return's file
    itself without calling either read."""
    script_dir = script_dir or _output.SCRIPTS_DIR
    exempt = PLAIN_READ_EXEMPT if exempt is None else exempt
    violations, seen, home = [], set(), False
    for rel, path in _output.lint_py_files(script_dir):
        rel = rel.replace(os.sep, "/")
        if rel == PLAIN_READ_HOME:
            home = True
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, SyntaxError, ValueError):
            continue
        for line, where in _plain_read_sites(tree):
            key = "%s::%s" % (rel, where)
            if key in exempt:
                seen.add(key)
                continue
            violations.append(("scripts/%s" % (rel,), "line %d (%s): calls %s, "
                               "the plain read - a closer reads a filed return "
                               "through read_filed_return_checked, or names "
                               "this read in PLAIN_READ_EXEMPT with why it "
                               "closes nothing" % (line, where, PLAIN_READ)))
    if not home:
        violations.append(("scripts/%s" % (PLAIN_READ_HOME,),
                           "the home module is missing, so no closer's read "
                           "was judged"))
    for key in sorted(set(exempt) - seen):
        violations.append(("scripts/%s" % (key.split("::")[0],),
                           "PLAIN_READ_EXEMPT names %s, which calls no %s - "
                           "a stale exemption would excuse the next read under "
                           "that name" % (key, PLAIN_READ)))
    return violations


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


# WHAT A ROUND REVIEWED IS WHAT ITS BRIEF SHOWED, NOT ONLY WHAT IT OWED. A fix
# task is owed no `tasks` entry, so the entries cannot say a round read its
# diff. The brief prints the set it showed on its filing command (`--shown`),
# and the filing verb writes it here. Recomputing that set later is not
# possible: it depends on the plan as it stood when the brief was composed,
# which no record keeps. A return filed before the list existed reads as its
# entries alone.
SHOWN_FIELD = "shown"
_SHOWN_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


def parse_shown(text):
    """`([(task id, commit), ...], None)` off a `--shown` value - comma-separated
    `id@commit` pairs, in the order given - or `([], problem)`."""
    pairs, seen = [], set()
    items = [p.strip() for p in str(text or "").split(",")]
    if items == [""]:
        return [], "`--shown` names no task"
    for item in items:
        tid, at, commit = item.partition("@")
        if not tid or not at or not commit:
            return [], "`--shown` item %r is not `id@commit`" % (item,)
        if not _SHOWN_COMMIT.match(commit):
            return [], ("`--shown` item %r names %r, not a commit SHA in "
                        "lower-case hex" % (item, commit))
        if tid in seen:
            return [], "`--shown` names %s twice" % (tid,)
        seen.add(tid)
        pairs.append((tid, commit))
    return pairs, None


def shown_record(pairs):
    """The `shown` list a filed return carries for `parse_shown`'s pairs."""
    return [{"id": tid, "commit": commit} for tid, commit in pairs]


# THE SET A BRIEF SHOWED IS RECORDED WHERE THE BRIEF IS, KEYED BY ITS HEAD. A
# return filed without `--shown` reads as the shape that predates the list, so
# with nothing to compare against the omission is silent and the next round
# shows every fix task again. The brief writes this record when it is composed;
# the filing verb holds a phase return for that head to it. A head no brief was
# recorded for has nothing to compare against and files as it always did.
BRIEFS_DIRNAME = "briefs"


def shown_argument_of(pairs):
    """`(id, commit)` pairs spelled as the `--shown` value a brief prints."""
    return ",".join("%s@%s" % (tid, commit) for tid, commit in pairs)


def shown_brief_path(state_dir, phase_id, head):
    """Where a phase brief composed at `head` records the set it showed."""
    return os.path.join(state_dir, BRIEFS_DIRNAME, str(phase_id),
                        "phase.shown.%s.json" % (return_start_key(head),))


def shown_brief_text(head, pairs):
    """The record `shown_brief_path` holds, as written."""
    return json.dumps({"head": head, SHOWN_FIELD: shown_record(pairs)},
                      indent=2) + "\n"


def read_shown_brief(state_dir, phase_id, head):
    """`(pairs, None)` off the record a brief composed at `head` wrote, `(None,
    None)` when none was written, or `(None, problem)` when one exists and
    cannot be read - which is not the same as none."""
    path = shown_brief_path(state_dir, phase_id, head)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, "the record at %s cannot be read (%s)" % (path, exc)
    entries = body.get(SHOWN_FIELD) if isinstance(body, dict) else None
    if not isinstance(entries, list) or body.get("head") != head:
        return None, ("the record at %s is not a `shown` list for head %s"
                      % (path, head))
    if not entries:
        return [], None
    pairs, problem = parse_shown(shown_argument_of(
        (e.get("id"), e.get("commit")) if isinstance(e, dict) else ("", "")
        for e in entries))
    if problem:
        return None, "the record at %s does not parse: %s" % (path, problem)
    return pairs, None


def shown_brief_refusal(recorded, given, path, head):
    """Why a phase return for `head` carrying `given` (`parse_shown`'s pairs,
    or None with no `--shown`) does not file against the `recorded` set its
    brief showed, or None when the two name the same pairs."""
    if sorted(recorded) == sorted(given or []):
        return None
    want = shown_argument_of(recorded)
    carried = ("no `--shown`" if given is None
               else "`--shown %s`" % (shown_argument_of(given),))
    asked = ("`--shown %s`" % (want,) if recorded else
             "no `--shown`, since it showed no task")
    return ("the phase brief composed at head %s showed %s (recorded at %s), "
            "and this return carries %s. Run the filing command that brief "
            "prints under `## Your return`, as printed - it carries %s"
            % (head, want or "no task", path, carried, asked))


def reviewed_entries(returns):
    """`{(task id, commit): rel}` off `phase_returns`'s list - every commit a
    filed round reviewed: its `tasks` entries and its `shown` list, the first
    return to name a commit winning."""
    seen = {}
    for rel, body, _problem in returns:
        if not isinstance(body, dict):
            continue
        for key in ("tasks", SHOWN_FIELD):
            entries = body.get(key)
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict) and entry.get("id") \
                        and entry.get("commit"):
                    seen.setdefault((str(entry["id"]), entry["commit"]), rel)
    return seen


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


# --- the answers a script gives ---------------------------------------------------
# A phase review's red-first and inherited-test answers follow a rule with no
# reading in it: a red-first block the helper wrote is echoed, and a gate whose
# every command is its runner alone puts the inherited-test question out of
# reach (`not-asked`).
# The filing verb fills those from their sources (`complete_phase_return`), and
# the phase brief says which they are (`audit-lookup.py`'s `answer_lines`), so
# the reviewer types only the answers that need reading. The intent answer is
# never one of them. A computed answer only ever lowers the work: a typed answer
# only a human settles is kept over it, and the override recorded.
#
# WHAT THIS CANNOT TELL. The helper's block is recognised by its shape - the
# basis `stamp-verification.py red` writes and the time it stamps - because the
# filed executor return records no provenance for it. A block typed by hand in
# the helper's words reads as the helper's. The gate reading sees the command
# line and nothing behind it: a selection made in the runner's configuration
# (an `addopts`, a package script running a subset), in the environment, or
# inside a script the command runs reads as the whole project, because the
# command line passes the runner nothing.
COMPUTED_FIELD = "computedAnswers"
# Where the filing verb records each computed answer a typed escalation
# overrode: `{task id: {word: {"computed": ..., "basis": ...}}}`.
OVERRIDDEN_FIELD = "computedOverridden"
_ANSWER_PAIRS = (("redFirst", "redFirstBasis"),
                 ("inheritedTests", "inheritedTestsBasis"))
# `red_verdict` in `stamp-verification.py` opens every basis with the command
# and the throwaway it ran in; `ma1` in the tests reads a block it wrote.
# The value of `redFirst.source` on a block `drive-phase.py submit` filled from
# the helper's output; the filing verb trusts this mark and not the wording.
HELPER_SOURCE = "red-first-helper"
_HELPER_BASIS = re.compile(r"^`.+?` in a throwaway tree at HEAD(?: exited -?\d+|:)",
                           re.S)
# A gate entry shaped `key:project` that names no build command resolves to
# nothing; `audit-lookup.py`'s gate lines say so with this same shape.
GATE_KEY_SHAPE = re.compile(r"^[^\s:]+:[^\s]+$")
TEST_DIRS = ("test", "tests", "__tests__", "spec", "specs")
_TEST_NAME = re.compile(r"^(?:test_.+|.+_test|.+\.(?:test|spec))\.[A-Za-z0-9]+$")
SELECTION_FLAGS = ("-k", "-t", "-g", "-run", "--run", "--grep", "--filter",
                   "--testNamePattern", "--test-name-pattern")
# What a command may pass its runner and still read as the whole project. The
# reading is positive: any word after the runner outside these reads `unknown`,
# so a selection this table has never heard of (`-m`, `--deselect`,
# `--testPathPattern`, a package path, a module name) leaves the inherited-test
# question to the reviewer rather than putting it out of reach. Each flag here
# changes how a run reports or when it stops, never which tests it collects; a
# flag is matched by its name, so `--tb=short` is `--tb`. A flag whose value is a
# separate word (`--tb short`) reads that value as an operand, and so `unknown`.
NO_SELECTION_FLAGS = ("-q", "-qq", "-v", "-vv", "-s", "-x", "--quiet",
                      "--verbose", "--exitfirst", "--failfast", "--tb",
                      "--color", "--colors", "--no-header", "--ci", "--silent",
                      "--reporter", "--no-tips", "-race", "--race")
# An operand meaning every package rather than one: `go test ./...`.
WHOLE_OPERANDS = ("./...",)
# Runners whose first word takes a subcommand that is part of the runner, not
# an operand: `go test`, `npm test`. `npx <tool>` takes the tool's name too
# (`run` as well, for vitest).
#
# THE ONE RULE FOR A NAMED SCRIPT. A word naming a script is part of the runner
# only where the plan itself vouches for it as the suite, and is an operand
# everywhere else, because a script is how a project selects a subset as often
# as how it runs everything. A package script (`npm|yarn|pnpm run <script>`)
# is the runner only when the script is `test`, the name the package manager
# itself runs as the suite. A script file run by an interpreter
# (`python3 tools/x.py`, `node scripts/test.js`) is the runner only when one of
# `meta.buildCommands` is exactly that interpreter and that file, nothing after
# them; that is how `python3 tools/sweep-selftests.py` reads `whole` in a plan
# declaring it. `-m <module>` is not a script: the module is the runner.
_SUBCOMMANDS = {"go": ("test",), "cargo": ("test",), "npm": ("test", "t"),
                "yarn": ("test",), "pnpm": ("test",)}
_INTERPRETER = re.compile(r"^(?:python[0-9.]*|py|node)(?:\.exe)?$")


def helper_red_first(executor):
    """The executor return's `redFirst` when it is the red-first helper's block
    - a word of the vocabulary, the helper's basis, its time, and the mark
    `drive-phase.py submit` puts on the block it fills - else None. The words
    alone prove nothing: a block typed in the helper's wording carries no mark."""
    red = executor.get("redFirst") if isinstance(executor, dict) else None
    if not (isinstance(red, dict) and red.get("source") == HELPER_SOURCE
            and red.get("status") in RED_FIRST_WORDS
            and _said(red, "at") and _said(red, "basis")
            and _HELPER_BASIS.match(red["basis"])):
        return None
    return red


def is_test_path(path):
    """Whether `path` (a `::case` suffix ignored) is a file named as a test,
    or a file inside a test directory. A bare test directory is not."""
    parts = [p for p in str(path or "").split("::", 1)[0].replace("\\", "/")
             .split("/") if p not in ("", ".")]
    if not parts:
        return False
    return bool(_TEST_NAME.match(parts[-1])) or any(p in TEST_DIRS
                                                    for p in parts[:-1])


def _names_tests(token):
    name = token.split("=", 1)[0]
    if name in SELECTION_FLAGS:
        return True
    return not token.startswith("-") and "=" not in token and is_test_path(token)


def _declared_scripts(build):
    """The `[interpreter, script]` word pairs `meta.buildCommands` declares as
    a whole command - the only script files `_runner_width` reads as a runner."""
    pairs = []
    for command in build.values():
        try:
            words = shlex.split(command) if isinstance(command, str) else []
        except ValueError:
            continue
        if len(words) == 2 and _INTERPRETER.match(os.path.basename(words[0])):
            pairs.append(words)
    return pairs


def _runner_width(words, declared):
    """How many leading `words` are the runner: an interpreter with its `-m`
    module, or with a script file `declared` names; a package manager's
    `run test`; a known runner with its subcommand; else the first word."""
    head = os.path.basename(words[0]) if words else ""
    nxt = words[1] if len(words) > 1 else None
    if _INTERPRETER.match(head):
        if nxt == "-m" and len(words) > 2:
            return 3
        return 2 if words[:2] in declared else 1
    if head in ("npm", "yarn", "pnpm") and nxt == "run" and len(words) > 2:
        return 3 if words[2] == "test" else 2
    if nxt is not None and nxt in _SUBCOMMANDS.get(head, ()):
        return 2
    if head == "npx" and nxt is not None:
        return 3 if nxt == "vitest" and words[2:3] == ["run"] else 2
    return 1


def _selects_nothing(word):
    if word in WHOLE_OPERANDS:
        return True
    return word.startswith("-") and word.split("=", 1)[0] in NO_SELECTION_FLAGS


def gate_reading(build, resolved):
    """`(kind, basis)` for a task's gate - `resolved` is
    `_evidence_io.resolved_commands`'s `[(entry, command)]`, `build` the plan's
    `meta.buildCommands`. `named` when a command names a test path or a
    selection flag; `whole` only when every entry resolves and every command
    is its runner (`_runner_width`, a script counted only by the one rule
    stated above `_SUBCOMMANDS`) followed by nothing but
    `NO_SELECTION_FLAGS` and `WHOLE_OPERANDS`; `unknown` otherwise - no entry,
    an entry resolving to nothing, a command that does not split into words or
    is empty, or one passing its runner anything else."""
    build = build if isinstance(build, dict) else {}
    if not resolved:
        return "unknown", "no tests.gate entry is declared for it or its phase"
    loose = [e for e, _c in resolved if e not in build and GATE_KEY_SHAPE.match(e)]
    if loose:
        return "unknown", ("%s resolves to no meta.buildCommands entry, so which "
                           "tests it selects is not on the record"
                           % (", ".join(loose),))
    named, split = [], []
    for _entry, command in resolved:
        try:
            words = shlex.split(command)
        except ValueError as exc:
            return "unknown", "`%s` does not split into words (%s)" % (command, exc)
        named += [w for w in words if _names_tests(w) and w not in named]
        split.append((command, words))
    shown = "; ".join("`%s`" % (c,) for _e, c in resolved)
    declared = _declared_scripts(build)
    if named:
        return "named", "the gate names %s (%s)" % (", ".join(named), shown)
    for command, words in split:
        if not words:
            return "unknown", "a gate command is empty (%s)" % (shown,)
        width = _runner_width(words, declared)
        passed = [w for w in words[width:] if not _selects_nothing(w)]
        if passed:
            return "unknown", (
                "`%s` passes %s to its runner `%s`, which this reading does not "
                "know to select nothing, so whether the gate runs the whole "
                "project is the reviewer's to read"
                % (command, ", ".join("`%s`" % (w,) for w in passed),
                   " ".join(words[:width])))
    return "whole", ("each gate command is its runner with no operand and no "
                     "flag outside the no-selection set (%s), so the gate is "
                     "read as running the whole project" % (shown,))


def mechanical_answers(executor, gate):
    """`(answers, owed)` for one task: the fields a script fills, and for each
    answer it does not fill, why it stays the reviewer's. `executor` is
    `(rel, body, problem)` of its filed executor return - body None when none
    is filed - and `gate` is `gate_reading`'s answer."""
    rel, body, problem = executor
    answers, owed = {}, {}
    block = None if problem else helper_red_first(body)
    if block is not None:
        answers["redFirst"] = block["status"]
        answers["redFirstBasis"] = "%s (the red-first helper's block in %s, at %s)" \
            % (block["basis"], rel, block["at"])
    elif problem:
        owed["redFirst"] = problem
    elif body is None:
        owed["redFirst"] = "no executor return is filed at %s" % (rel,)
    else:
        owed["redFirst"] = ("the `redFirst` in %s is not the red-first helper's "
                            "block, so it is graded by reading" % (rel,))
    kind, basis = gate
    if kind == "whole":
        answers["inheritedTests"] = "not-asked"
        answers["inheritedTestsBasis"] = "computed: %s" % (basis,)
    else:
        owed["inheritedTests"] = basis
    return answers, owed


def task_gate_entries(phase, task):
    """`(entries, whose)` - the task's own `tests.gate`, else its phase's
    `testGate`: the gate a reviewer's question is bounded by."""
    own = (task.get("tests") or {}).get("gate")
    if isinstance(own, list) and own:
        return own, "the task's own tests.gate"
    return list(phase.get("testGate") or []), \
        "the phase's testGate (the task declares no gate of its own)"


def tests_add_files(task):
    """The file half of each `tests.add` entry (`<file>: <the case>`), in order,
    an entry naming no file left out."""
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    return [f for f in (str(a).split(":", 1)[0].strip()
                        for a in tests.get("add") or [] if isinstance(a, str)) if f]


# What may stand on either side of a path a command names: the command's ends,
# whitespace, a quote, and the separators a word list or a shell line uses;
# before it also `=` (`--flag=path`), and after it `:` (a `::case` suffix).
_PATH_BEFORE = " \t\"'=,;"
_PATH_AFTER = " \t\"',;:"
_VAR_PREFIX = re.compile(r"\$(?:\w+|\{\w+\})/$")


def names_path(command, path):
    """Whether `command` names `path` as a path of its own: led by the
    command's start, a `_PATH_BEFORE` character, `./`, or a `$VAR/` prefix, and
    ended by its end or a `_PATH_AFTER` character. A longer path that only
    begins or ends with `path`'s spelling is not it."""
    for hit in re.finditer(re.escape(path), command):
        before, after = command[:hit.start()], command[hit.end():]
        led = (not before or before[-1] in _PATH_BEFORE
               or (before.endswith("./") and (len(before) == 2
                                              or before[-3] in _PATH_BEFORE))
               or _VAR_PREFIX.search(before) is not None)
        if led and (not after or after[0] in _PATH_AFTER):
            return True
    return False


def _paths_ending(command, basename):
    """The paths `command`'s words name that end in `/<basename>`, a word's
    `--flag=` head and `::case` tail left off."""
    try:
        words = shlex.split(command)
    except ValueError:
        return set()
    found = set()
    for word in words:
        for part in re.split(r"[,;]", word.split("=", 1)[-1]):
            part = part.split("::", 1)[0]
            if part.endswith("/" + basename):
                found.add(part)
    return found


def red_command(task, resolved):
    """The resolved gate command that names one of the task's `tests.add` files
    (`names_path`), or None: the command the red-first helper is handed - after
    `--` in the executor's brief, and by the step driver after a writer session.
    `resolved` is `_evidence_io.resolved_commands`' `[(entry, command)]` over the
    task's gate (`task_gate_entries`). Only a command naming the file is taken:
    a whole-project gate is a red the helper would grade against every test HEAD
    carries, and an entry naming no file names nothing. An entry spelled as a
    bare basename is the file only when exactly one path the gate's commands
    name ends in `/<basename>` - two such paths are two files it might mean."""
    added = tests_add_files(task)
    commands = [c for _e, c in resolved or [] if isinstance(c, str)]
    for cmd in commands:
        if any(names_path(cmd, f) for f in added):
            return cmd
    for name in [f for f in added if "/" not in f]:
        ending = [(cmd, _paths_ending(cmd, name)) for cmd in commands]
        paths = set().union(*[p for _c, p in ending]) if ending else set()
        if len(paths) == 1:
            return next(cmd for cmd, p in ending if p)
    return None


def phase_answers(evidence_dir, phase, build, resolve):
    """`{task id: (answers, owed)}` for every task of `phase` recording a
    commit. `resolve` turns gate entries into `[(entry, command)]` - the
    caller's `_evidence_io.resolved_commands` over its manifest."""
    found = {}
    for task in phase.get("tasks") or []:
        if not (isinstance(task, dict) and task.get("commit")):
            continue
        tid = str(task.get("id"))
        rel = return_rel(tid, task.get("startedAt"), "executor")
        _text, body, problem = read_filed_return(
            return_path(evidence_dir, task, "executor"))
        entries, _whose = task_gate_entries(phase, task)
        found[tid] = mechanical_answers(
            (rel, body, problem), gate_reading(build, resolve(entries)))
    return found


def complete_phase_return(body, computed):
    """`(body, filled, problems)` - a phase return with each entry's absent
    mechanical pair filled from `computed` (`{task id: answers}`), what was
    filled per task, recorded on the body under `COMPUTED_FIELD`, and every
    disagreement: a word typed that differs from the computed one without
    escalating it, an escalation typed without its basis, a basis typed
    without its word, or a typed `COMPUTED_FIELD` or `OVERRIDDEN_FIELD`. A
    word typed equal to the computed one is kept as typed, basis and all.

    A computed answer only ever lowers the work, so it never blocks a word
    only a human settles (`ESCALATIONS`): that word is kept with its basis,
    and the computed one it overrode recorded under `OVERRIDDEN_FIELD`.
    `COMPUTED_FIELD` is then written too, empty when nothing was filled - it
    is the mark the filing verb writes a completed body by."""
    if not isinstance(body, dict):
        return body, {}, []
    forged = [f for f in (COMPUTED_FIELD, OVERRIDDEN_FIELD) if f in body]
    if forged:
        return body, {}, ["`%s` is the filing verb's record of what it filled or "
                          "overrode, never typed in a return" % (f,)
                          for f in forged]
    entries = body.get("tasks")
    if not isinstance(entries, list):
        return body, {}, []
    out, filled, overridden, problems = [], {}, {}, []
    for entry in entries:
        answers = computed.get(str(entry.get("id"))) \
            if isinstance(entry, dict) else None
        if not answers:
            out.append(entry)
            continue
        tid, entry, took, over = str(entry.get("id")), dict(entry), [], {}
        for word, basis in _ANSWER_PAIRS:
            if word not in answers:
                continue
            if word in entry:
                record, refusal = _typed_over(tid, entry, answers, word, basis)
                if record:
                    over[word] = record
                problems += [refusal] if refusal else []
                continue
            if basis in entry:
                problems.append("the entry for %s: `%s` is given without `%s` "
                                "- leave both out and the filing verb files them"
                                % (tid, basis, word))
                continue
            entry[word], entry[basis] = answers[word], answers[basis]
            took += [word, basis]
        if took:
            filled[tid] = took
        if over:
            overridden[tid] = over
        out.append(entry)
    done = dict(body, tasks=out)
    if filled or overridden:
        done[COMPUTED_FIELD] = filled
    if overridden:
        done[OVERRIDDEN_FIELD] = overridden
    return done, filled, problems


def _typed_over(tid, entry, answers, word, basis):
    """`(record, refusal)` for a typed `word` over a computed one: both None
    when they agree, the override record `{"computed", "basis"}` when the
    typed word escalates and says why, else the refusal sentence."""
    typed, ups = entry[word], ESCALATIONS.get(word, ())
    if typed == answers[word]:
        return None, None
    if typed in ups and _said(entry, basis):
        return {"computed": answers[word], "basis": answers[basis]}, None
    if typed in ups:
        return None, ("the entry for %s: `%s` is %r, which puts the answer to "
                      "a human over the computed %r, and `%s` is absent or "
                      "empty - say why"
                      % (tid, word, typed, answers[word], basis))
    return None, ("the entry for %s: `%s` is %r, and the filing verb computes "
                  "%r (%s) - leave `%s` and `%s` out and it files them, or "
                  "type %s with its basis to put the answer to a human"
                  % (tid, word, typed, answers[word], answers[basis], word,
                     basis, " or ".join("`%s`" % (u,) for u in ups)))


# --- the answers only a human settles ---------------------------------------------
# A reviewer's `diverges` or `cannot-tell`, a red-first grade of `not-proved` and
# an inherited test `flagged` are the answers no agent settles. The driver's
# triage stops on them and the sign-off verb refuses over them, through this one
# predicate, so the documented verb run by hand cannot sign off what the driver
# would have stopped. A phase intent counts under every review key.
HUMAN_ANSWERS = ("diverges", "cannot-tell")
HUMAN_RED_FIRST = ("not-proved",)
HUMAN_INHERITED = ("flagged",)
# The words a reviewer may type over a computed answer (`_typed_over`): per
# field, the answers only a human settles, so a computed answer never stands
# between a reviewer and the human it escalates to.
ESCALATIONS = {"redFirst": HUMAN_RED_FIRST, "inheritedTests": HUMAN_INHERITED}

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


def ref_phase_returns(git_root, ref, rel, phase_id, commit=None):
    """`[(rel, body, problem)]` - the phase returns branch `ref` commits under
    `rel` (root-relative, `/`-separated), named as the filing verb names them
    on disk; with `commit`, the ones that commit holds instead of the branch
    tip. A return is labelled by `ref` either way, so one return read at the
    tip and at a commit is one signature (`return_signature`). A listing git
    would not give is a problem entry, never no return filed: an unread tree
    is not an empty one."""
    rev = commit or "refs/heads/%s" % (ref,)
    code, out = _git(git_root, ["ls-tree", "-r", "--name-only", "-z",
                                rev, "--", rel])
    if code != 0:
        return [("%s:%s" % (ref, rel), None,
                 "git would not list %s at %s" % (rel, commit or ref))]
    paths = [p for p in out.decode("utf-8", "replace").split("\0") if p]
    found = []
    for path in sorted(p for p in paths if p.endswith(".reviewer.json")
                       and posixpath.dirname(p) == rel):
        code, raw = _git(git_root, ["cat-file", "blob", "%s:%s" % (rev, path)])
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
