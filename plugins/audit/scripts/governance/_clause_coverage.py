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

WHAT THE AUTHOR IS TOLD. A reading that differs from what the author wrote is
only cheap to fix at the write, so it is never left unsaid, and that is computed
rather than enumerated: the reading carries, as spans of the description, every
item and every part it left out of all items, so "nothing dropped" is a
subtraction (`unaccounted` is its remainder); and what could be read another way
- a list number inside an item that is not its opener, the marker word where it
was not counted, a fence never closed - is scanned off the description itself,
not off the reading. `reading_line` names each, so the one line `add` and
`scope` print is empty only for a plain parenthesised list with nothing found.

SILENT ONLY ON AGREEMENT. A list of departures only names the shapes someone
thought of, so the silence is also a comparison: the reader's choices - what
spells the marker, what may stand before it, whether the word counts without
its colon, what opens an item, whether the text is folded first - are one
table, `READING_CHOICES`, and the description is read twice by the same reader,
once with the strict column (what a task is held to) and once with the wide
one. The wide column takes the word without its colon only where it opens a
line and a list numbered one opens directly under it, so a line that merely
begins with the word - an item wrapping there, a closing paragraph - is prose
to both. The line is empty only when the strict reading is the plain one,
nothing is scanned as above, and the wide reading finds the same items, each
with the same text; otherwise it adds how many the wide reading finds - or that
it finds the same number, placed differently - and the first line holding text
where the two part. The scans stay beside the comparison because the wide
reading does not answer them: it reads a fenced marker word as an example and
opens items by sequence, so a mention inside a fence and a skipped or repeated
list number would read the same both ways.

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

import bisect
import json
import os
import posixpath
import re
import sys
import textwrap
import unicodedata

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
# The wide reading's one shape: every opener form at once (`_ANY_FORM`).
SHAPE_ANY_NUMBERED = "any-numbered"

# The digit runs are bounded: `int()` of a run past the interpreter's
# integer-string limit raises, and a reader that raises takes `add`, `scope`
# and the drive's filing down with it. No list numbers past six digits. Every
# opener pattern names its number's group last, so `m.lastgroup` finds it in
# each, and the indent before a line-start number `indent`.
#
# A parenthesised number opens an item unless the character before it is a
# letter, a digit, an underscore or a closing bracket: `sys.exit(1)` and
# `rows[0](2)` stay inside their item, while the `(2)` of `a;(2) b` - after a
# semicolon, a comma, a quote or a dash - opens one.
_PAREN_NUMBER = re.compile(r"(?<![\w)\]}])\((?P<n>\d{1,6})\)")
# A number closed by a full stop or a parenthesis, at the start of a line (or of
# the text right after the marker, which ends a label rather than a sentence),
# after an indent, and followed by whitespace: `version 2. then` sits mid-line
# and `1.5` has no space after its stop, so neither opens anything.
_LINE_NUMBER = re.compile(r"(?m)^(?P<indent>[ \t]*)(?P<n>\d{1,6})[.)](?=\s|\Z)")
# The wide reading's one opener: either form above, and a number in square
# brackets, at a line start after an indent and a bullet; or the parenthesised
# form after a blank or punctuation, as above.
_ANY_NUMBER = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:[-*+][ \t]+)?"
    r"(?:\((?P<pn>\d{1,6})\)|\[(?P<bn>\d{1,6})\]|(?P<dn>\d{1,6})[.)])(?=\s|\Z)"
    r"|(?<![\w)\]}])\((?P<mn>\d{1,6})\)")
# What may stand before the marker on its line for it to open the line: an
# indent and Markdown's heading, quote, list and emphasis marks - and, for the
# wide reading, a backtick too.
_LINE_OPENER = re.compile(r"[ \t#>*_+-]*")
_ANY_LINE_OPENER = re.compile(r"[ \t#>*_+`-]*")
# The marker as a task is held to it, and the marker word as the wide reading
# takes it: any case, whole, with whatever emphasis, blanks and colon follow it
# taken into the marker so they open no item. The colon is optional in the
# pattern only; a match without it counts as a marker where the `bare` choice
# says so (`_markers`).
_MARK_EXACT = re.compile(re.escape(ACCEPTANCE_MARK))
_MARK_ANY = re.compile(r"(?i)(?<![^\W_])acceptance(?![^\W_])(?:[ \t*_`]*:)?")
_INDENT = re.compile(r"[ \t]*")
# What may stand between a bare marker word and a list opening on its own line:
# blanks and closing emphasis. An opener numbered one is short, so the rest of
# the line is read no further than `_OPENER_REACH` characters.
_AFTER_BARE = " \t*_`"
_OPENER_REACH = 16
# A line holding no text: blanks only, up to its end.
_BLANK_LINE = re.compile(r"[^\S\n]*(?:\n|\Z)")
# What may stand before the marker for it to open a sentence part-way along a
# line, read backwards from the marker: emphasis, whitespace (at least one),
# closing quotes, brackets or emphasis, then a sentence's end.
_SENTENCE_LEAD = "*_"
_SENTENCE_GAP = " \t"
_SENTENCE_CLOSERS = "\"')]*_"
_SENTENCE_ENDS = ".!?"
# Every spelling of the marker word a reader might take for the marker: any
# case, spaces before the colon, an ASCII or a full-width colon. Only the exact
# `ACCEPTANCE_MARK` at a place that counts is a marker; every other match is a
# mention the reading line names.
_MARKER_WORD = re.compile(r"(?i)(?<![^\W_])acceptance[ \t]*[:" + chr(0xFF1A) + "]")
# CommonMark's fences: an opening run of three or more backticks or tildes
# indented at most three spaces, whose info string - for a backtick fence -
# holds no backtick; a closing run of the same character, at least as long,
# with nothing but spaces or tabs after it.
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*\Z")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}(?:[ \t]|$)")
_CLOSING_EMPHASIS = re.compile(r"[*_]+")

# The forms a numbered list is opened in - see `_opens`. `bind`: items open
# only at the indent of the first; `restart`: a 1 opens a new item; `nest`: a 1
# written another way than the list's openers (another form, another indent)
# starts a nested list, and that way opens nothing until the list's own does.
_PAREN_FORM = {"shape": SHAPE_PARENTHESISED, "pattern": _PAREN_NUMBER,
               "bind": False, "restart": False, "nest": False}
_LINE_FORM = {"shape": SHAPE_LINE_NUMBERED, "pattern": _LINE_NUMBER,
              "bind": True, "restart": True, "nest": False}
_ANY_FORM = {"shape": SHAPE_ANY_NUMBERED, "pattern": _ANY_NUMBER,
             "bind": False, "restart": True, "nest": True}

# THE READER'S CHOICES, one row each: the STRICT reading is what a task is held
# to; the WIDE reading takes every choice at its widest. Both are `_read` called
# with one column, so the wide reading is the same reader and never a second
# parser, and the line is silent only when the two find the same items.
READING_CHOICES = (
    # (choice, strict, wide)
    # the text is read as written, or folded to Unicode's compatibility form
    # with its format characters dropped (`_fold`)
    ("fold", False, True),
    # what spells the marker
    ("marker", _MARK_EXACT, _MARK_ANY),
    # what may stand before it on its line for it to open the line
    ("opener", _LINE_OPENER, _ANY_LINE_OPENER),
    # whether a marker ending in a colon counts anywhere, not only where it
    # opens a line or, the first, a sentence
    ("colonAnywhere", False, True),
    # whether the marker word WITHOUT its colon counts where it opens a line
    # and a list numbered one opens directly under it (`_list_opens_under`); a
    # line that merely begins with the word is prose either way
    ("bare", False, True),
    # the opener forms, each tried alone, the earliest-opening one read
    ("forms", (_PAREN_FORM, _LINE_FORM), (_ANY_FORM,)),
)
STRICT = dict((name, strict) for name, strict, _wide in READING_CHOICES)
WIDE = dict((name, wide) for name, _strict, wide in READING_CHOICES)

# A quoted part is cut to this many characters where it is taken, so a reading
# holds no copy of the rest of a line per place it names; `_quoted` reads no
# further than this either.
_QUOTE_WIDTH = 60
_TAKE = _QUOTE_WIDTH * 4

# The kinds of text the reading leaves out of every item; each is named by the
# reading line with its start quoted.
LEFT_LEAD_IN = "lead-in"
LEFT_MARKER_BODY = "marker-body"
LEFT_AFTER_HEADING = "after-heading"


def _layout(text):
    """`{"lines", "fences", "starts", "open"}` - the offset each line starts
    at, every code fence as `(start, end)` with its fence lines included, the
    fences' starts for a bisect, and the line an unclosed fence opens on (None
    when every fence closes). An unclosed fence runs to the end. A marker, a
    number or a heading inside a fence is an example, not the description's own
    structure."""
    lines = [0] + [m.end() for m in re.finditer("\n", text)]
    spans, opened = [], None
    for number, start in enumerate(lines, 1):
        end = lines[number] - 1 if number < len(lines) else len(text)
        line = text[start:end]
        if opened is None:
            m = _FENCE_OPEN.match(line)
            if m is not None and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                opened = (start, m.group(1)[0], len(m.group(1)), number)
            continue
        m = _FENCE_CLOSE.match(line)
        if (m is not None and m.group(1)[0] == opened[1]
                and len(m.group(1)) >= opened[2]):
            spans.append((opened[0], end))
            opened = None
    if opened is not None:
        spans.append((opened[0], len(text)))
    return {"lines": lines, "fences": spans, "starts": [s for s, _e in spans],
            "open": opened[3] if opened is not None else None}


def _inside(at, layout):
    i = bisect.bisect_right(layout["starts"], at) - 1
    return i >= 0 and at < layout["fences"][i][1]


def _line_of(at, layout):
    return bisect.bisect_right(layout["lines"], at)


def _sentence_cut(text, line_start, at):
    """Where the sentence before a marker part-way along a line ends, or None
    when the marker does not open a sentence - read backwards from `at`, so no
    call costs more than the run of marks it walks over."""
    i = at
    while i > line_start and text[i - 1] in _SENTENCE_LEAD:
        i -= 1
    gap = i
    while gap > line_start and text[gap - 1] in _SENTENCE_GAP:
        gap -= 1
    if gap == i:
        return None
    end = gap
    while end > line_start and text[end - 1] in _SENTENCE_CLOSERS:
        end -= 1
    if end == line_start or text[end - 1] not in _SENTENCE_ENDS:
        return None
    cut = at
    while cut > line_start and text[cut - 1] in " \t*_":
        cut -= 1
    return cut


def _opens_one(text, at, forms):
    """Whether an item numbered one, in one of `forms`, opens at `at`."""
    for form in forms:
        m = form["pattern"].match(text, at)
        if m is not None and int(m.group(m.lastgroup)) == 1:
            return True
    return False


def _list_opens_under(text, end, layout, forms):
    """Whether a list numbered one opens directly under a marker word ending
    at `end`: on the rest of its line, past blanks and closing emphasis, or at
    the start of the next line holding text, outside a code fence. Words of a
    label may stand between the word and its line's end (`Acceptance criteria`)
    when the list opens on the next line; a line that only begins with the word
    has prose, or a list opening at another number, after it."""
    line = _line_of(end, layout)
    starts = layout["lines"]
    line_end = starts[line] - 1 if line < len(starts) else len(text)
    at = end
    while at < line_end and text[at] in _AFTER_BARE:
        at += 1
    if _opens_one(text[at:min(line_end, at + _OPENER_REACH)], 0, forms):
        return True
    at = line_end + 1
    while at < len(text):
        blank = _BLANK_LINE.match(text, at)
        if blank is None:
            return not _inside(at, layout) and _opens_one(text, at, forms)
        if text[blank.end() - 1] != "\n":
            return False
        at = blank.end()
    return False


def _markers(text, layout, choices):
    """`[{"at", "end", "cut", "indent", "line"}]` of each marker that counts,
    outside a code fence: one opening a line (after an indent and the marks
    `choices["opener"]` allows), and - for the first only - one opening a
    sentence, so a description written as one paragraph still has its list.
    At a line's start the marker word without its colon counts only under the
    `bare` choice, and only where a list numbered one opens directly under it
    (`_list_opens_under`). Away from a line's start the marker holds its colon.
    Strictly, inside a body a marker ends the body before it only when it opens
    a line; one that opens a sentence there, or sits inside a sentence, behind a
    backtick or a quotation mark, is a mention of the word, never the list's
    start - the wide reading (`colonAnywhere`) counts the word with its colon
    there too. `end` is where the marker's text ends, `cut` where the text
    before it ends - its line's start, the end of the sentence it follows, or
    the marker itself - and `indent` its line's indent."""
    found, opener_end = [], {}
    for m in choices["marker"].finditer(text):
        at = m.start()
        if _inside(at, layout):
            continue
        line = _line_of(at, layout)
        line_start = layout["lines"][line - 1]
        if line_start not in opener_end:
            opener_end[line_start] = choices["opener"].match(text, line_start).end()
        bare = not m.group(0).endswith(":")
        if opener_end[line_start] >= at:
            if bare and not (choices["bare"] and _list_opens_under(
                    text, m.end(), layout, choices["forms"])):
                continue
            cut = line_start
        elif bare:
            continue
        else:
            cut = None if found else _sentence_cut(text, line_start, at)
            if cut is None and choices["colonAnywhere"]:
                cut = at
            if cut is None:
                continue
        found.append({"at": at, "end": m.end(), "cut": cut, "line": line,
                      "indent": _INDENT.match(text, line_start, at).group(0)})
    return found


def _mentions(text, markers):
    """`[at]` of every place the marker word occurs - in any case, with spaces
    before its colon, in a fence, in backticks - that was not counted as a
    marker."""
    counted = set(marker["at"] for marker in markers)
    return [m.start() for m in _MARKER_WORD.finditer(text) if m.start() not in counted]


def _body(text, layout, marker, end):
    """`(start, stop, end)` - the text a marker heads runs from `start`, after
    it (closing emphasis of a bold marker dropped), to `stop`: the first
    heading line after the marker's own line that sits outside a fence, or
    `end` when there is none. Text from `stop` to `end` is left out."""
    start = marker["end"]
    closing = _CLOSING_EMPHASIS.match(text, start)
    if closing is not None:
        start = closing.end()
    for m in _HEADING.finditer(text, start, end):
        if m.start() > start and not _inside(m.start(), layout):
            return start, m.start(), end
    return start, end, end


def _stripped(text, start, end):
    """`(start, end)` narrowed past the whitespace at either end."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _opens(body, offset, layout, marker_indent, form):
    """The `(start, end)` of each number that opens an item in one `form`, the
    indent the list opened at, and whether the numbering restarted.

    Items open by sequence: the first at a 1, and each later one only as the
    next number, so a number that is not the next stays inside the item it
    sits in - `(2)` opens the second item only once `(1)` has opened the first.
    A form that `bind`s opens items only at the indent of its first opener, so
    a nested sub-step opens nothing; one that may `restart` opens a new item at
    a 1, reported as a restart: Markdown numbers `1. 1. 1.` as three items, and
    folding them into one would hold the writer to a single clause holding
    three. A form that may `nest` reads a 1 written another way than the list's
    last opener - another form, another indent - as a nested list, whose way
    of numbering opens nothing until the list's own opens again. A number on
    the marker's own line sits at the marker line's indent."""
    opens, want, indent, restart = [], 1, None, False
    current, nested = None, None
    for m in form["pattern"].finditer(body):
        if _inside(offset + m.start(), layout):
            continue
        n = int(m.group(m.lastgroup))
        here = marker_indent if m.start() == 0 else m.groupdict().get("indent")
        way = (m.lastgroup, m.group(0)[-1], here)
        if not opens:
            if n == 1:
                opens.append((m.start(), m.end()))
                indent, want, current = here, 2, way
            continue
        if form["bind"] and here != indent:
            continue
        if form["nest"] and (way == nested or (n == 1 and way != current)):
            nested = way
            continue
        if n == want or (form["restart"] and n == 1):
            restart = restart or n == 1
            opens.append((m.start(), m.end()))
            want, current, nested = n + 1, way, None
    return {"opens": opens, "restart": restart, "indent": indent}


def _read_body(text, start, stop, layout, marker_indent, forms):
    """One marker's reading of `text[start:stop]`: the numbered shape whose
    first item opens earlier, the other shape's item count when it yielded
    items too, the text before the first item, and the unnumbered reading when
    no number opened one - each item, opener and lead-in also as a `(start,
    end)` span of `text`."""
    body = text[start:stop]
    tried = [(form["shape"], _opens(body, start, layout, marker_indent, form))
             for form in forms]
    yielded = sorted((t for t in tried if t[1]["opens"]),
                     key=lambda t: t[1]["opens"][0][0])
    if not yielded:
        whole = _stripped(text, start, stop)
        spans = [whole] if whole[0] < whole[1] else []
        return {"shape": SHAPE_UNNUMBERED if spans else None,
                "itemSpans": spans, "openers": [], "lead": None, "other": None,
                "restart": False, "indent": None}
    shape, got = yielded[0]
    other = None
    if len(yielded) > 1:
        other = {"shape": yielded[1][0], "count": len(yielded[1][1]["opens"])}
    opens = [(start + s, start + e) for s, e in got["opens"]]
    ends = [s for s, _e in opens[1:]] + [stop]
    lead = _stripped(text, start, opens[0][0])
    return {"shape": shape, "openers": opens, "other": other,
            "itemSpans": [_stripped(text, e, end) for (_s, e), end in zip(opens, ends)],
            "lead": lead if lead[0] < lead[1] else None,
            "restart": got["restart"], "indent": got["indent"]}


def _left_part(text, kind, span, line):
    start, end = _stripped(text, span[0], span[1])
    if start >= end:
        return []
    return [{"kind": kind, "line": line, "start": start, "end": end,
             "text": text[start:end]}]


def _stray_numbers(text, shape, spans, indent, layout):
    """`[at]` of each number inside an item that could have opened one by its
    position and did not - a skip, a repeat, a number out of order after
    whitespace or punctuation. In a parenthesised list that is a `(n)` not glued
    to a word; in a line-numbered one a line-start number at the list's indent;
    in unnumbered text either, at any indent. A number glued to a letter, a
    digit, an underscore or a closing bracket is no candidate, and one inside a
    code fence is an example."""
    found = []
    for start, end in spans:
        if shape != SHAPE_LINE_NUMBERED:
            found.extend(m.start() for m in _PAREN_NUMBER.finditer(text, start, end))
        if shape != SHAPE_PARENTHESISED:
            found.extend(m.start("n") for m in _LINE_NUMBER.finditer(text, start, end)
                         if shape == SHAPE_UNNUMBERED or m.group("indent") == indent)
    return sorted(at for at in found if not _inside(at, layout))


def _unaccounted(text, region, covered):
    """`[(start, end)]` of the stretches of `region` that hold a non-space
    character and lie in no `covered` span - the subtraction that says the
    reading dropped nothing: from the first marker to the end, every character
    is in an item, in a part named as left out, in a marker or a list number,
    or is whitespace."""
    gaps, at = [], region[0]
    for start, end in sorted(covered) + [(region[1], region[1])]:
        if start > at and text[at:start].strip():
            gaps.append(_stripped(text, at, start))
        at = max(at, end)
    return gaps


def _empty_reading(text, layout, mentions, wide):
    return {"shape": None, "items": [], "markers": 0, "markerLine": None,
            "why": None, "leadIn": "", "other": None, "restart": False,
            "leftOut": [], "itemSpans": [], "strayNumbers": [], "unaccounted": [],
            "mentions": [_tail(text, at) for at in mentions],
            "openFence": layout["open"], "region": None, "wide": wide}


def _tail(text, at):
    """`{"at", "text"}` - a place, and its line's text from there on to quote,
    cut at `_TAKE` characters here rather than when it is printed: a line
    holding thousands of places would otherwise hold a copy of its rest per
    place."""
    end = text.find("\n", at, at + _TAKE)
    return {"at": at, "text": text[at:at + _TAKE if end < 0 else end]}


def _fold(text):
    """`text` in Unicode's compatibility form with its format characters
    dropped - the one normalisation the wide reading reads through, so
    full-width brackets and digits, a no-break space and a character without
    width read as their plain twins. It keeps every line break, so a line
    number of the folded text is a line number of the text as written."""
    if text.isascii():
        return text
    folded = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")


def _is_numbered(shape):
    return shape not in (None, SHAPE_UNNUMBERED)


def _read(text, choices):
    """`(text read, layout, markers, readings, chosen, why)` - one reading of a
    description, its choices one column of `READING_CHOICES`. `readings` is
    `(marker, (start, stop, end), body reading)` per marker; `chosen` the one
    read (None with no marker): the one whose body holds a numbered list when
    exactly one does, otherwise the last (`why`: `numbered` or `last`, None
    with one marker)."""
    if choices["fold"]:
        text = _fold(text)
    layout = _layout(text)
    markers = _markers(text, layout, choices)
    readings = []
    for i, marker in enumerate(markers):
        end = markers[i + 1]["cut"] if i + 1 < len(markers) else len(text)
        start, stop, end = _body(text, layout, marker, end)
        readings.append((marker, (start, stop, end),
                         _read_body(text, start, stop, layout, marker["indent"],
                                    choices["forms"])))
    numbered = [r for r in readings if _is_numbered(r[2]["shape"])]
    why = None
    if len(readings) > 1:
        why = "numbered" if len(numbered) == 1 else "last"
    chosen = None
    if readings:
        chosen = numbered[0] if why == "numbered" else readings[-1]
    return text, layout, markers, readings, chosen, why


def _item_lines(text, spans, layout, fold):
    """`{line: [(item index, folded text of the item on that line)]}` - where
    each item sits, line by line, for finding where two readings part. A line
    holding no text once folded is not recorded: a blank line between an item
    and the next text places nothing, so the line two readings part on is
    always one holding text."""
    parts = {}
    for i, (start, end) in enumerate(spans):
        first = _line_of(start, layout)
        for j, piece in enumerate(text[start:end].split("\n")):
            held = fold(piece).strip()
            if held:
                parts.setdefault(first + j, []).append((i, held))
    return parts


def _wide_reading(text, layout, chosen):
    """None when the wide reading of `text` finds the items the strict reading
    `chosen` found - the same count, each the same text once both are folded -
    else `{"count", "line", "text"}`: how many items the wide reading finds, and
    the first line holding text where the two readings part, with its text as
    written. Equal counts with different text are a departure too."""
    spans = chosen[2]["itemSpans"] if chosen else []
    folded, wide_layout, _m, _r, wide, _why = _read(text, WIDE)
    wide_spans = wide[2]["itemSpans"] if wide else []
    if [folded[s:e] for s, e in wide_spans] == [_fold(text[s:e]) for s, e in spans]:
        return None
    strict_lines = _item_lines(text, spans, layout, _fold)
    wide_lines = _item_lines(folded, wide_spans, wide_layout, lambda piece: piece)
    parted = [n for n in sorted(set(strict_lines) | set(wide_lines))
              if strict_lines.get(n) != wide_lines.get(n)]
    line = parted[0] if parted else _line_of((spans or wide_spans)[0][0], layout)
    return {"count": len(wide_spans), "line": line,
            "text": _tail(text, layout["lines"][line - 1])["text"]}


def acceptance_reading(description, wide=True):
    """How the description's Acceptance list reads: `{"shape", "items",
    "markers", "markerLine", "why", "leadIn", "other", "restart", "leftOut",
    "itemSpans", "strayNumbers", "mentions", "openFence", "unaccounted",
    "region", "wide"}`. `shape` is None exactly when there are no items.
    Offsets index the description with each `\\r\\n` read as one `\\n`.

    THE MARKER counts where it opens a line - after an indent and Markdown's
    heading, quote, list or emphasis marks - and, when it is the first, where
    it opens a sentence; never inside a code fence (CommonMark's: a run of
    three or more backticks or tildes, closed only by a run of the same
    character at least as long, a backtick run with a backtick after it being
    an inline span and no fence). Its body runs to the next marker and ends at
    the first heading line after it. With more than one marker (`markers`), the
    one whose body holds a numbered list is read when exactly one does, and
    otherwise the last (`why`: `numbered` or `last`; `markerLine` is the line it
    sits on).

    THE SHAPES of one body:

    - parenthesised, `(1) ... (2) ...`: the recommended form. A `(n)` opens an
      item unless a letter, a digit, an underscore or a closing bracket stands
      right before it, and only as the next in sequence, so `sys.exit(1)` and
      `the last of (7) lines` stay inside their item.
    - line-numbered, Markdown's own list (`1.` or `1)` starting a line), read
      at the indent of its first `1.` - see `_opens`.
    - unnumbered: a marker followed by prose (`Acceptance: the sweep is green.`)
      is still acceptance, so the whole text, its surrounding whitespace
      removed, is ONE item.

    CONSERVATION. From the first marker to the end, every character is in an
    item (`itemSpans`), in a part left out (`leftOut`: the text before the
    first item, the body of a marker not read, the text from a heading that
    ended the body - each `{"kind", "line", "start", "end", "text"}`), in a
    marker or a list number, or is whitespace. `unaccounted` is the
    subtraction's remainder and is empty unless a shape forgot a span; the line
    names it either way.

    WHAT COULD BE READ ANOTHER WAY, scanned off the description rather than
    the reading: `mentions` (the marker word anywhere it was not counted - any
    case, a space before the colon, in backticks, in a fence), `strayNumbers`
    (a number inside an item that could have opened one by its position and
    did not - see `_stray_numbers`) and `openFence` (the line of a fence never
    closed). `reading_line` names each of these, and every part left out, so
    nothing the reader departs from is unsaid at the write.

    THE WIDE READING (`wide`; False skips it, for a caller that needs only the
    items). The reading above is the STRICT one, and it is what a task is held
    to; the wide reading is the same reader with every choice in
    `READING_CHOICES` at its widest - among them the marker word without its
    colon, where a list numbered one opens directly under it. `wide` is None
    when the two find the same items, else what the wide reading finds and the
    first line holding text where the two part - so a departure no list of
    shapes names is still said."""
    text = description if isinstance(description, str) else ""
    text = text.replace("\r\n", "\n")
    _text, layout, markers, readings, chosen, why = _read(text, STRICT)
    mentions = _mentions(text, markers)
    disagree = _wide_reading(text, layout, chosen) if wide else None
    if not markers:
        return _empty_reading(text, layout, mentions, disagree)
    marker, (start, stop, end), reading = chosen
    left = []
    for other_marker, bounds, _other in readings:
        if other_marker is not marker:
            left += _left_part(text, LEFT_MARKER_BODY, (bounds[0], bounds[2]),
                               other_marker["line"])
    if reading["lead"]:
        left += _left_part(text, LEFT_LEAD_IN, reading["lead"], marker["line"])
    left += _left_part(text, LEFT_AFTER_HEADING, (stop, end), _line_of(stop, layout))
    left.sort(key=lambda part: part["start"])
    covered = ([(m["cut"], b[0]) for m, b, _r in readings] + reading["openers"]
               + reading["itemSpans"] + [(p["start"], p["end"]) for p in left])
    region = (markers[0]["cut"], len(text))
    strays = _stray_numbers(text, reading["shape"], reading["itemSpans"],
                            reading["indent"], layout)
    return {"shape": reading["shape"],
            "items": [text[s:e] for s, e in reading["itemSpans"]],
            "markers": len(readings), "markerLine": marker["line"], "why": why,
            "leadIn": text[reading["lead"][0]:reading["lead"][1]]
            if reading["lead"] else "",
            "other": reading["other"], "restart": reading["restart"],
            "leftOut": left, "itemSpans": reading["itemSpans"],
            "strayNumbers": [_tail(text, at) for at in strays],
            "mentions": [_tail(text, at) for at in mentions],
            "openFence": layout["open"], "region": region, "wide": disagree,
            "unaccounted": [_tail(text, s) for s, _e in
                            _unaccounted(text, region, covered)]}


def acceptance_items(description):
    """The texts of the description's Acceptance items, in order - see
    `acceptance_reading` for the shapes they are read in. The strict reading
    alone: the wide one changes what is said, never the items."""
    return acceptance_reading(description, wide=False)["items"]


def is_plain(reading):
    """A parenthesised list that accounts for its whole body under the one
    marker, with nothing left out: the reading itself needs no word at the
    write. Whether anything in the description could be read another way is
    `_departures`', and is said even of a plain reading."""
    return (reading["shape"] == SHAPE_PARENTHESISED and reading["markers"] == 1
            and not reading["leadIn"] and not reading["leftOut"]
            and not reading["unaccounted"])


def _quoted(text, width=_QUOTE_WIDTH):
    """`text` on one line, quoted, shortened at a word with ` ...` marking the
    cut - or cut mid-word when it holds no break to shorten at."""
    flat = " ".join(text[:_TAKE].split())
    short = textwrap.shorten(flat, width, placeholder=" ...")
    if len(flat) > width and short == "...":
        short = flat[:width - 4] + " ..."
    return '"%s"' % (short,)


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


_LEFT_WORDS = {
    LEFT_LEAD_IN: "text before the first item",
    LEFT_MARKER_BODY: "the body of the marker on line %d",
    LEFT_AFTER_HEADING: "the text from the heading on line %d",
}


def _left_notes(reading):
    """One clause per part left out of every item, in the order they stand."""
    notes = []
    for part in reading["leftOut"]:
        words = _LEFT_WORDS[part["kind"]]
        if "%d" in words:
            words = words % (part["line"],)
        notes.append("%s is in no item: %s" % (words, _quoted(part["text"])))
    if reading["unaccounted"]:
        count = len(reading["unaccounted"])
        notes.append("%d %s of text after the first marker in no item and in no "
                     "part named here, first %s" % (
                         count, "stretch" if count == 1 else "stretches",
                         _quoted(reading["unaccounted"][0]["text"])))
    return notes


def _departures(reading):
    """The clauses saying what in the description could be read another way -
    each with its count and its first instance quoted, and each only when it is
    true. They are scans of the description, so they are said whether or not
    the reading itself is the plain one - the first of them the wide reading,
    whenever it finds other items than the strict one."""
    notes = []
    wide = reading.get("wide")
    if wide:
        # Equal counts are no difference of count: what differs is where the
        # items fall, and the line says that rather than repeat the count.
        found = ("the same number of items, placed differently"
                 if wide["count"] == len(reading["items"])
                 else _plural(wide["count"], "item"))
        notes.append("a wider reading of the same text finds %s, and the two "
                     "readings first part on line %d: %s" % (
                         found, wide["line"], _quoted(wide["text"])))
    if reading["strayNumbers"]:
        notes.append("%s inside an item, not its opener, first %s" % (
            _plural(len(reading["strayNumbers"]), "list number"),
            _quoted(reading["strayNumbers"][0]["text"])))
    if reading["mentions"]:
        notes.append("%s of the marker word not read as a marker, first %s" % (
            _plural(len(reading["mentions"]), "mention"),
            _quoted(reading["mentions"][0]["text"])))
    if reading["openFence"] is not None:
        notes.append("a code fence opened on line %d is never closed, so the "
                     "text after it is read as an example" % (reading["openFence"],))
    return notes


def _notes(reading):
    """The clauses of the reading line that say how the reading differs from
    the plain one - each only when it is true of this reading."""
    notes = []
    if reading["markers"] > 1:
        notes.append("%d Acceptance markers, read the one on line %d (%s)" % (
            reading["markers"], reading["markerLine"],
            "the only one holding a numbered list"
            if reading["why"] == "numbered" else "the last"))
    if reading["other"]:
        notes.append("the %s shape would give %s" % (
            reading["other"]["shape"], _plural(reading["other"]["count"], "item")))
    notes += _left_notes(reading)
    if reading["restart"]:
        notes.append("the numbering restarts at 1, each restart read as a new item")
    return notes + _departures(reading)


_HELD = "held on the headless-writer route (executor.writerModel set)"


def describe_reading(reading):
    """The line's words for one reading (no `acceptance:` label), or "" when
    the reading is the plain one and nothing could be read another way, or
    when the description holds no marker word at all."""
    count = len(reading["items"])
    notes = _notes(reading)
    if reading["shape"] is None:
        if not notes and not reading["markers"]:
            return ""
        if not notes:
            notes = ["the marker on line %d is followed by no text"
                     % (reading["markerLine"],)]
        return "no clause was read; %s - %s: the writer is held to no " \
               "acceptance clause" % ("; ".join(notes), _HELD)
    # A plain list whose items hold Markdown sub-steps also yields a
    # line-numbered reading; that alone is no departure from what the author
    # wrote, so the other shape is said only on a line printed for another reason.
    if is_plain(reading) and not _departures(reading):
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
    return "%s - %s: %s" % ("; ".join([said] + notes), _HELD, held)


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
