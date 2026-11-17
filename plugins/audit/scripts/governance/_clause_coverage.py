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
items of its description's Acceptance list - which marker counts and which shape
reads it are `acceptance_reading`'s rules.

WHO IS HELD. `check` is called only where the drive files a headless writer's
work (`executor.writerModel` set). The executor subagent filing through `submit`
is asked for no clause and checked against none; the line `reading_line` prints
says which route it is true of.

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
import textwrap

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

# The shapes an Acceptance list is read in. When both numbered shapes yield
# items the one whose first item opens earlier in the body is read, and the
# other is named in the reading line rather than mixed in.
SHAPE_PARENTHESISED = "parenthesised"
SHAPE_LINE_NUMBERED = "line-numbered"
SHAPE_UNNUMBERED = "unnumbered"
NUMBERED_SHAPES = (SHAPE_PARENTHESISED, SHAPE_LINE_NUMBERED)

# The digit runs are bounded: `int()` of a run past the interpreter's
# integer-string limit raises, and a reader that raises takes `add`, `scope`
# and the drive's filing down with it. No list numbers past six digits.
#
# A parenthesised number opens an item only at the body's start or after
# whitespace: `sys.exit(1)` inside an item is a call, not item one.
_PAREN_NUMBER = re.compile(r"(?<!\S)\((\d{1,6})\)")
# A number closed by a full stop or a parenthesis, at the start of a line (or of
# the text right after the marker, which ends a label rather than a sentence),
# after an indent kept in group 1, and followed by whitespace: `version 2. then`
# sits mid-line and `1.5` has no space after its stop, so neither opens anything.
_LINE_NUMBER = re.compile(r"(?m)^([ \t]*)(\d{1,6})[.)](?=\s|\Z)")
# What may stand before the marker on its line for it to open the line: an
# indent and Markdown's heading, quote, list and emphasis marks.
_LINE_OPENER = re.compile(r"[ \t#>*_+-]*\Z")
# What may stand before the marker for it to open a sentence part-way along a
# line: a sentence's end, a closing quote or bracket, whitespace, emphasis.
_SENTENCE_OPENER = re.compile(r"[.!?][\"')\]*_]*[ \t]+[*_]*\Z")
_FENCE = re.compile(r"(?m)^[ \t]{0,3}(```|~~~)")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}(?:[ \t]|$)")
_CLOSING_EMPHASIS = re.compile(r"[*_]+")


def _fenced_spans(text):
    """`[(start, end)]` of every code fence in `text`, its fence lines included;
    an unclosed fence runs to the end. A marker, a number or a heading inside
    one is an example, not the description's own structure."""
    spans, opened = [], None
    for m in _FENCE.finditer(text):
        if opened is None:
            opened = m
        elif m.group(1) == opened.group(1):
            end = text.find("\n", m.end())
            spans.append((opened.start(), len(text) if end < 0 else end))
            opened = None
    if opened is not None:
        spans.append((opened.start(), len(text)))
    return spans


def _inside(at, spans):
    return any(start <= at < end for start, end in spans)


def _markers(text, fences):
    """`[{"at", "cut", "indent", "line"}]` of each marker that counts: one
    opening a line (after an indent and Markdown marks) or a sentence, outside
    a code fence. A marker inside a sentence, behind a backtick or a quotation
    mark, or in a fence is a mention of the word, never the list's start.
    `cut` is where the text before it ends - its line's start, or the end of
    the sentence it follows - and `indent` its line's indent."""
    found = []
    for m in re.finditer(re.escape(ACCEPTANCE_MARK), text):
        at = m.start()
        line_start = text.rfind("\n", 0, at) + 1
        before = text[line_start:at]
        if _inside(at, fences):
            continue
        if _LINE_OPENER.match(before) is not None:
            cut = line_start
        elif _SENTENCE_OPENER.search(before) is not None:
            cut = line_start + len(before.rstrip(" \t*_"))
        else:
            continue
        found.append({"at": at, "cut": cut, "line": text.count("\n", 0, at) + 1,
                      "indent": re.match(r"[ \t]*", before).group(0)})
    return found


def _body(text, fences, marker, end):
    """`(offset, body)` - the text a marker heads: from after it (closing
    emphasis of a bold marker dropped) to `end`, cut at the first heading line
    after the marker's own line that sits outside a fence."""
    start = marker["at"] + len(ACCEPTANCE_MARK)
    closing = _CLOSING_EMPHASIS.match(text, start)
    if closing is not None:
        start = closing.end()
    for m in _HEADING.finditer(text, start, end):
        if m.start() > start and not _inside(m.start(), fences):
            end = m.start()
            break
    return start, text[start:end]


def _items_between(body, opens):
    return [body[end:(opens[i + 1][0] if i + 1 < len(opens) else len(body))].strip()
            for i, (_start, end) in enumerate(opens)]


def _paren_opens(body, offset, fences):
    """The `(start, end)` of each `(n)` that opens an item, by sequence: `(2)`
    opens the second item only once `(1)` has opened the first, so a number
    that is not the next stays inside the item it sits in."""
    opens, want = [], 1
    for m in _PAREN_NUMBER.finditer(body):
        if int(m.group(1)) == want and not _inside(offset + m.start(), fences):
            opens.append((m.start(), m.end()))
            want += 1
    return {"opens": opens, "restart": False}


def _line_opens(body, offset, fences, marker_indent):
    """The `(start, end)` of each line-start number that opens an item, and
    whether the numbering restarted. Items open only at the indent of the first
    `1.` - a nested sub-step opens nothing - and by sequence, except that a `1.`
    at that indent opens a new item and is reported as a restart: Markdown
    numbers `1. 1. 1.` as three items, and folding them into one would hold the
    writer to a single clause holding three. A number on the marker's own line
    sits at the marker line's indent."""
    opens, want, indent, restart = [], 1, None, False
    for m in _LINE_NUMBER.finditer(body):
        if _inside(offset + m.start(), fences):
            continue
        n = int(m.group(2))
        here = marker_indent if m.start() == 0 else m.group(1)
        if indent is None:
            if n == 1:
                opens.append((m.start(), m.end()))
                indent, want = here, 2
            continue
        if here != indent:
            continue
        if n == want or n == 1:
            restart = restart or n == 1
            opens.append((m.start(), m.end()))
            want = n + 1
    return {"opens": opens, "restart": restart}


def _read_body(body, offset, fences, marker_indent):
    """One marker's reading: the numbered shape whose first item opens earlier,
    the other shape's item count when it yielded items too, the text before
    the first item, and the unnumbered reading when no number opened one."""
    tried = [(SHAPE_PARENTHESISED, _paren_opens(body, offset, fences)),
             (SHAPE_LINE_NUMBERED, _line_opens(body, offset, fences, marker_indent))]
    yielded = sorted((t for t in tried if t[1]["opens"]),
                     key=lambda t: t[1]["opens"][0][0])
    if not yielded:
        whole = body.strip()
        return {"shape": SHAPE_UNNUMBERED if whole else None,
                "items": [whole] if whole else [], "leadIn": "", "other": None,
                "restart": False}
    shape, got = yielded[0]
    other = None
    if len(yielded) > 1:
        other = {"shape": yielded[1][0], "count": len(yielded[1][1]["opens"])}
    return {"shape": shape, "items": _items_between(body, got["opens"]),
            "leadIn": body[:got["opens"][0][0]].strip(), "other": other,
            "restart": got["restart"]}


def acceptance_reading(description):
    """How the description's Acceptance list reads: `{"shape", "items",
    "markers", "markerLine", "why", "leadIn", "other", "restart"}`. `shape` is
    None exactly when there are no items.

    THE MARKER counts only where it opens a line - after an indent and
    Markdown's heading, quote, list or emphasis marks - or opens a sentence,
    and never inside a code fence; a mention inside a sentence or behind a
    backtick is no marker. Its body runs to the next such marker and ends at
    the first heading line after it. With more than one marker (`markers`),
    the one whose body holds a numbered list is read when exactly one does,
    and otherwise the last (`why`: `numbered` or `last`; `markerLine` is the
    line it sits on).

    THE SHAPES of one body:

    - parenthesised, `(1) ... (2) ...`: the recommended form. A `(n)` opens an
      item only at the body's start or after whitespace, and only as the next
      in sequence, so `sys.exit(1)` and `the last of (7) lines` stay inside
      their item.
    - line-numbered, Markdown's own list (`1.` or `1)` starting a line), read
      at the indent of its first `1.` - see `_line_opens`.
    - unnumbered: a marker followed by prose (`Acceptance: the sweep is green.`)
      is still acceptance, so the whole text, its surrounding whitespace
      removed, is ONE item.

    When both numbered shapes yield items, the one opening first is read and
    the other's count is kept in `other`; text before the first item is kept
    in `leadIn`; a restarted numbering sets `restart`. Each of those is said
    by `reading_line`, so no reading other than a parenthesised list covering
    the whole body goes unsaid at the write. A description with no marker, or
    a marker followed by nothing but whitespace, has no items."""
    text = description if isinstance(description, str) else ""
    text = text.replace("\r\n", "\n")
    fences = _fenced_spans(text)
    markers = _markers(text, fences)
    if not markers:
        return {"shape": None, "items": [], "markers": 0, "markerLine": None,
                "why": None, "leadIn": "", "other": None, "restart": False}
    readings = []
    for i, marker in enumerate(markers):
        end = markers[i + 1]["cut"] if i + 1 < len(markers) else len(text)
        offset, body = _body(text, fences, marker, end)
        readings.append((marker, _read_body(body, offset, fences, marker["indent"])))
    numbered = [r for r in readings if r[1]["shape"] in NUMBERED_SHAPES]
    why = None
    if len(readings) > 1:
        why = "numbered" if len(numbered) == 1 else "last"
    marker, reading = numbered[0] if why == "numbered" else readings[-1]
    return dict(reading, markers=len(readings), markerLine=marker["line"], why=why)


def acceptance_items(description):
    """The texts of the description's Acceptance items, in order - see
    `acceptance_reading` for the shapes they are read in."""
    return acceptance_reading(description)["items"]


def is_plain(reading):
    """A parenthesised list that accounts for its whole body under the one
    marker: the reading that needs no word at the write."""
    return (reading["shape"] == SHAPE_PARENTHESISED and reading["markers"] == 1
            and not reading["leadIn"])


def _quoted(text, width=60):
    """`text` on one line, quoted, shortened at a word with ` ...` marking the cut."""
    return '"%s"' % (textwrap.shorten(text, width, placeholder=" ..."),)


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _notes(reading):
    """The clauses of the reading line that say how the reading differs from
    the plain one - each only when it is true of this reading."""
    notes = []
    if reading["markers"] > 1:
        notes.append("%d Acceptance markers open a line or a sentence, read the "
                     "one on line %d (%s)" % (
                         reading["markers"], reading["markerLine"],
                         "the only one holding a numbered list"
                         if reading["why"] == "numbered" else "the last"))
    if reading["other"]:
        notes.append("the %s shape would give %s" % (
            reading["other"]["shape"], _plural(reading["other"]["count"], "item")))
    if reading["leadIn"]:
        notes.append("text before the first item is in no item: %s"
                     % (_quoted(reading["leadIn"]),))
    if reading["restart"]:
        notes.append("the numbering restarts at 1, each restart read as a new item")
    return notes


def describe_reading(reading):
    """The line's words for one reading (no `acceptance:` label), or "" for
    the plain reading and for no item."""
    count = len(reading["items"])
    if reading["shape"] is None or is_plain(reading):
        return ""
    if reading["shape"] == SHAPE_UNNUMBERED:
        said = "1 item, the whole unnumbered text after the marker"
        held = "the writer answers it as one clause"
    else:
        said = "%s, read from %s" % (
            _plural(count, "item"),
            "a list numbered at line starts"
            if reading["shape"] == SHAPE_LINE_NUMBERED else "a parenthesised list")
        held = "the writer answers each"
    return "%s - held on the headless-writer route (executor.writerModel set): %s" % (
        "; ".join([said] + _notes(reading)), held)


def reading_summary(description):
    """`{"shape", "items", "line"}` for a write's JSON result - the shape, the
    item count, and the line the human form prints ("" for the plain reading) -
    or None when the description holds no item."""
    reading = acceptance_reading(description)
    if reading["shape"] is None:
        return None
    said = describe_reading(reading)
    return {"shape": reading["shape"], "items": len(reading["items"]),
            "line": "acceptance: %s" % (said,) if said else ""}


def reading_line(description, subject=None):
    """The one line a write that sets a description prints about how its
    Acceptance list was read, or "" when there is nothing new to say.

    On the headless-writer route the writer is held to every item, so an
    author whose list was read any way other than a parenthesised list
    covering the whole body is told the count, the shape and each departure
    at the write, where a misreading is still cheap to fix. `subject` names
    the task when one write sets several descriptions."""
    said = describe_reading(acceptance_reading(description))
    if not said:
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
