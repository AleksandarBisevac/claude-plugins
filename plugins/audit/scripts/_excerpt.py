#!/usr/bin/env python3
"""
How a failing tool's output is shortened for a sentence that names the failure - stdlib only.

WHY THIS IS ONE HELPER AND NOT A CHOICE OF END. A refusal reason used to cut the
tool's output at its head (`.strip()[:200]`) and a failing-step print kept only
its tail, and each is wrong for the tools that matter: a pre-commit hook opens
with a progress preamble and puts the failing check in the middle or at the end,
a test runner opens with the failing test and closes with a summary. Choosing an
end is the bug, so the excerpt keeps BOTH ends and, from what it dropped, every
line shaped like a failure -- and says how much it dropped, because a short
output and a shortened one must not read alike.

A TITLE OR A SUMMARY CUT IS A DIFFERENT THING and stays a plain slice: this is
for the output of a subprocess that is being quoted as the reason something
failed. `_output.bare_output_cut_violations()` fails a head-only cut of a name
bound from such output, so the next site cannot choose an end again.

The cases for this file live in `tests/test__excerpt.py`.
"""
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

HEAD_CHARS = 100
TAIL_CHARS = 220
LINE_CHARS = 100
MAX_LINES = 3
# What one excerpt can come to at most: both ends, the kept lines with their
# separators, and the marker around them. A writer that must keep an excerpt
# whole sizes its field from this rather than from a number of its own.
MAX_CHARS = HEAD_CHARS + TAIL_CHARS + MAX_LINES * (LINE_CHARS + 3) + 120

# The shapes of a failure line across the tools this plugin quotes: lint-staged
# and eslint's cross, a test runner's FAIL, node's ERR_ codes, and any "error".
FAILURE_LINE = re.compile("✖|(?i:error)|FAIL|ERR_")


def failure_lines(text, limit=MAX_LINES, width=LINE_CHARS):
    """`(kept, more)` - the first `limit` distinct lines of `text` shaped like a
    failure, each bounded to `width`, and how many further ones there were."""
    seen = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and FAILURE_LINE.search(line) and line not in seen:
            seen.append(line)
    kept = [ln if len(ln) <= width else ln[:width - 3] + "..." for ln in seen[:limit]]
    return kept, max(0, len(seen) - limit)


def elided_marker(count, kept, more):
    """The words between the two ends: how much went, and the failure lines that
    were rescued from it."""
    if not kept:
        return " [... %d chars elided ...] " % (count,)
    tail = " (+%d more)" % (more,) if more else ""
    return " [... %d chars elided; failure lines among them: %s%s ...] " % (
        count, " | ".join(kept), tail)


_MARKER = re.compile(r"\[\.\.\. \d+ chars elided")


def is_excerpt(text):
    """True when `text` carries the marker `excerpt` leaves where it dropped a
    middle - how a writer that bounds its fields tells a quoted tool output,
    already bounded by `MAX_CHARS`, from free text that still needs a clip."""
    return _MARKER.search(text or "") is not None


def excerpt(text, head=HEAD_CHARS, tail=TAIL_CHARS):
    """`text` stripped and, when longer than `head + tail`, its head, its tail
    and between them a marker naming the count dropped and the failure lines
    found in the dropped middle. Text that fits is returned whole."""
    text = (text or "").strip()
    if len(text) <= head + tail:
        return text
    middle = text[head:len(text) - tail]
    kept, more = failure_lines(middle)
    return text[:head] + elided_marker(len(middle), kept, more) + text[len(text) - tail:]


def reason_of(*streams):
    """`excerpt` of the first of `streams` that says anything - the `(err or out)`
    idiom every git wrapper spelled by hand."""
    for stream in streams:
        if stream and stream.strip():
            return excerpt(stream)
    return ""


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
