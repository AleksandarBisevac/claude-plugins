#!/usr/bin/env python3
"""
Whether a writer answered every clause its task owes, and whether the file an
answer cites is one the diff touches.

WHY THIS IS A MODULE. A writer is a plain session that ends its message with one
JSON object keyed by clause number; the drive has to decide, from that message
and the diff alone, whether the task may go on to its gate's filing. The numbering
lives here too, and only here: `audit-lookup.py` builds the writer's closing line
from `task_clauses` and this check reads the answer against the same list, so a
clause the writer was asked about and a clause this check holds it to cannot be
two different clauses. The list is the task's `tests.add` entries first, then the
items of its description after the LAST `Acceptance:` marker, read in one of the
shapes `acceptance_reading` names.

WHAT IS CHECKED, AND WHAT IS NOT. Four things make a clause a gap: no entry for
its number, an entry that is not shaped as the closing line asks, a `delivered`
entry whose cited file the diff does not touch, and - for every clause at once -
a message that ends with no JSON object at all. A missing or unreadable answer is
never read as covered, because the one reading that would let it through is the
one a writer that says nothing relies on. What the writer WRITES is not graded:
that a cited line delivers the clause is the recorded gate's and the reviewer's
to judge, and `delivered: false` with a reason is an answer, reported as
`declined` so the drive can say so rather than file it unmentioned. A task that
numbers no clause owes none; the result says `owed: 0` rather than that
everything was answered.

This module carries no `--selftest` of its own; its cases live in
`tests/test__clause_coverage.py`.

Stdlib only, Python 3.8 compatible.
"""

import json
import os
import posixpath
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

# --- the clauses ----------------------------------------------------------------
ACCEPTANCE_MARK = "Acceptance:"

# The shapes an Acceptance list is read in, tried in this order; the first
# that yields an item decides, so the shapes never mix.
SHAPE_PARENTHESISED = "parenthesised"
SHAPE_LINE_NUMBERED = "line-numbered"
SHAPE_UNNUMBERED = "unnumbered"

_PAREN_NUMBER = re.compile(r"\((\d+)\)")
# A number closed by a full stop or a parenthesis, at the start of a line (or of
# the text right after the marker, which ends a label rather than a sentence),
# after at most an indent, and followed by whitespace: `version 2. then` sits
# mid-line and `1.5` has no space after its stop, so neither opens anything.
_LINE_NUMBER = re.compile(r"(?m)^[ \t]*(\d+)[.)](?=\s|\Z)")


def _sequence_items(pattern, body):
    """The items `pattern`'s numbers open in `body`, by sequence: `2` opens the
    second item only once `1` has opened the first, so a number that is not the
    next one stays inside the item it sits in. Each item is the text up to the
    next opening number, with its surrounding whitespace removed."""
    opens, want = [], 1
    for m in pattern.finditer(body):
        if int(m.group(1)) == want:
            opens.append((m.start(), m.end()))
            want += 1
    return [body[end:(opens[i + 1][0] if i + 1 < len(opens) else len(body))].strip()
            for i, (_start, end) in enumerate(opens)]


def acceptance_reading(description):
    """`{"shape", "items"}` - how the description's Acceptance list reads, and
    its items in order. `shape` is None exactly when there are no items.

    Read after the LAST `Acceptance:` - a description numbers its own steps
    before it - in these shapes, the first that yields an item deciding:

    - parenthesised, `(1) ... (2) ...`: the recommended form, and the only one
      read before the other two existed - so it is tried first and reads exactly
      as it always did. A number inside an item's own words (`the last of (7)
      lines`) is not the next in sequence and stays in that item.
    - line-numbered, Markdown's own list (`1.` or `1)` starting a line): what an
      author writes by habit. Read by the same sequence rule, and only at a line
      start, so a version number or a decimal inside a sentence opens nothing.
    - unnumbered: a marker followed by prose (`Acceptance: the sweep is green.`)
      is still acceptance, so the whole text, its surrounding whitespace
      removed, is ONE item.

    There is no silent other reading: before the line-numbered and unnumbered
    shapes, a list written either way read as no item at all, and a check holding a writer to its clauses passed
    because it had read nothing. A description with no marker, or a marker
    followed by nothing but whitespace, has no items."""
    text = description if isinstance(description, str) else ""
    at = text.rfind(ACCEPTANCE_MARK)
    if at < 0:
        return {"shape": None, "items": []}
    body = text[at + len(ACCEPTANCE_MARK):]
    for shape, pattern in ((SHAPE_PARENTHESISED, _PAREN_NUMBER),
                           (SHAPE_LINE_NUMBERED, _LINE_NUMBER)):
        items = _sequence_items(pattern, body)
        if items:
            return {"shape": shape, "items": items}
    whole = body.strip()
    if whole:
        return {"shape": SHAPE_UNNUMBERED, "items": [whole]}
    return {"shape": None, "items": []}


def acceptance_items(description):
    """The texts of the description's Acceptance items, in order - see
    `acceptance_reading` for the shapes they are read in."""
    return acceptance_reading(description)["items"]


def reading_line(description, subject=None):
    """The one line a write that sets a description prints about how its
    Acceptance list was read, or "" when there is nothing new to say.

    The executor is held to every item, so an author whose list was read by
    the line-numbered or the unnumbered shape is told the count and the shape at
    the write, where a misreading is still cheap to fix. The parenthesised form
    and a description with no item print nothing. `subject` names the task when
    one write sets several descriptions."""
    reading = acceptance_reading(description)
    count = len(reading["items"])
    if reading["shape"] == SHAPE_LINE_NUMBERED:
        said = ("%d item%s, read from a list numbered at line starts - the "
                "executor answers each" % (count, "" if count == 1 else "s"))
    elif reading["shape"] == SHAPE_UNNUMBERED:
        said = ("1 item, the whole unnumbered text after the marker - the "
                "executor answers it as one clause")
    else:
        return ""
    return ("acceptance (%s): %s" % (subject, said) if subject
            else "acceptance: %s" % (said,))


def task_clauses(task):
    """`[{"n", "kind", "text"}]` - the clauses a task owes an answer to, numbered
    from one: its `tests.add` entries first, in order, then the items of
    its description's Acceptance list. THE ONE NUMBERING: the writer's closing
    line (`audit-lookup.py`) is built from this list and `check` reads the
    writer's answer against the same list rather than number the clauses a
    second time."""
    added = [a for a in ((task.get("tests") or {}).get("add") or [])
             if isinstance(a, str) and a.strip()]
    rows = ([("tests.add", a) for a in added]
            + [("acceptance", a) for a in acceptance_items(task.get("description"))])
    return [{"n": n, "kind": kind, "text": text}
            for n, (kind, text) in enumerate(rows, 1)]


# --- the writer's answer ----------------------------------------------------------
def parse_answer(message):
    """`(object, None)` - the JSON object the message ends with - or `(None,
    why)`. The object must be the LAST thing in the message, a closing code
    fence aside: one in the middle of prose is a quotation, and reading it as
    the answer would grade a sentence the writer did not mean as its answer. The
    outermost object that reaches the end is the one read."""
    body = message.rstrip() if isinstance(message, str) else ""
    if body.endswith("```"):
        body = body[:-3].rstrip()
    if not body:
        return None, "the message is empty"
    if not body.endswith("}"):
        return None, "the message does not end with a JSON object"
    decoder = json.JSONDecoder()
    start = body.find("{")
    while start >= 0:
        try:
            found, end = decoder.raw_decode(body, start)
        except ValueError:
            found, end = None, 0
        if isinstance(found, dict) and not body[end:].strip():
            return found, None
        start = body.find("{", start + 1)
    return None, "no JSON object that ends the message parses"


def _slashed(path, root):
    """`path` in the plan's spelling - forward slashes, no `./`, a path under
    `root` made relative to it - or None for a value that is not a path. An
    absolute path outside `root` becomes a `../` path (or stays absolute when
    it sits on another drive than `root`, which `relpath` cannot bridge), so it
    matches nothing the diff names, whatever its tail."""
    if not isinstance(path, str) or not path.strip():
        return None
    text = path.strip()
    if root and os.path.isabs(text):
        try:
            text = os.path.relpath(text, root)
        except ValueError:
            return text.replace("\\", "/")
    return posixpath.normpath(text.replace("\\", "/"))


def _shape(entry, root):
    """`(state, detail, path)` of one answer: `state` is `delivered`,
    `declined`, or `malformed` with what was wrong."""
    if not isinstance(entry, dict):
        return "malformed", "the answer is not a JSON object", None
    flag = entry.get("delivered")
    if flag is True:
        cited = _slashed(entry.get("file"), root)
        line = entry.get("line")
        if cited is None:
            return "malformed", "a delivered answer names no file", None
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            return "malformed", "a delivered answer names no line number", cited
        return "delivered", "", cited
    if flag is False:
        reason = entry.get("reason")
        if isinstance(reason, str) and reason.strip():
            return "declined", "", None
        return "malformed", "a not-delivered answer gives no reason", None
    return "malformed", "`delivered` is neither true nor false", None


def _gap(clause, reason, detail, path=None):
    gap = {"n": clause["n"], "kind": clause["kind"], "text": clause["text"],
           "reason": reason, "detail": detail}
    if path is not None:
        gap["path"] = path
    return gap


def check(clauses, message, changed, root=None):
    """`{"covered", "owed", "gaps", "declined", "unknown"}` - `clauses` (from
    `task_clauses`) read against the JSON object `message` ends with and the
    paths the diff touches (`changed`; `root` is the directory those paths are
    relative to, for a writer that cites an absolute one).

    `gaps` is one record per clause with no answer (`no-answer`), a malformed
    one (`malformed`), a delivered one citing a file the diff does not touch
    (`path-not-in-diff`, with the `path`), or - for every clause at once - no
    readable JSON object (`no-json`). `declined` is the numbers the writer says
    it did not deliver, with a reason: answered, so not a gap. `unknown` is the
    keys the object holds that no clause carries. `covered` is True only with
    no gap, and a task that owes nothing is covered with `owed` 0."""
    touched = set(_slashed(p, root) for p in changed or [])
    if not clauses:
        return {"covered": True, "owed": 0, "gaps": [], "declined": [],
                "unknown": []}
    answer, problem = parse_answer(message)
    if answer is None:
        return {"covered": False, "owed": len(clauses), "declined": [],
                "unknown": [], "gaps": [_gap(c, "no-json", problem)
                                        for c in clauses]}
    gaps, declined = [], []
    for clause in clauses:
        key = str(clause["n"])
        if key not in answer:
            gaps.append(_gap(clause, "no-answer", "the message's JSON object "
                             "has no entry for this clause"))
            continue
        state, detail, cited = _shape(answer[key], root)
        if state == "malformed":
            gaps.append(_gap(clause, "malformed", detail))
        elif state == "declined":
            declined.append(clause["n"])
        elif cited not in touched:
            gaps.append(_gap(clause, "path-not-in-diff", "the file it cites, %s, "
                             "is not among the paths the work changed" % (cited,),
                             cited))
    owed = set(str(c["n"]) for c in clauses)
    return {"covered": not gaps, "owed": len(clauses), "gaps": gaps,
            "declined": declined,
            "unknown": sorted((k for k in answer if k not in owed),
                              key=lambda k: (len(k), k))}


def gap_summary(result):
    """One clause per gap, for a decision's one-line reason: the clause number,
    the gap's reason word and the cited path where there is one, in clause
    order. Short on purpose - the full words go to the writer in `resume_text`."""
    return "; ".join("clause %d: %s%s" % (g["n"], g["reason"], (" " + g["path"])
                                            if "path" in g else "")
                     for g in result["gaps"])


def resume_text(result, clauses):
    """What to tell the writer: each uncovered clause with its number, its words
    and what was wrong with its answer. `""` when nothing is uncovered, so a
    caller testing the text cannot resume a session with nothing to say."""
    if not result["gaps"]:
        return ""
    lines = ["These acceptance clauses have no usable answer in your last message:"]
    for gap in result["gaps"]:
        lines.append("clause %d: %s - %s" % (
            gap["n"], " ".join(gap["text"].split()), gap["detail"]))
    return "\n".join(lines)
