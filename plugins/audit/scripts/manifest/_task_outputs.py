"""What a task's `outputs` entry may be, and what an honoured one reaches.

`files` names what a task EDITS and is enumerated, so every entry can owe a
`fileIndex` row. `outputs` names what a run PRODUCES - the documents it writes,
the evidence rows it appends, a report it renders - which cannot be enumerated
before the run makes them. So it is patterns, and a pattern is the one thing on a
task that can WIDEN what the plan gate allows.

THE BOUND IS THE WHOLE FEATURE, which is why it is a module and not a helper.
`outputs` exists so documentation and evidence writes have a place in the plan
instead of being reported as uncovered on every save - a gate whose warnings are
noise is a gate that is off, and the repair is a place in the plan rather than an
exception. But a plan that may declare an output pattern may also declare one
covering the whole tree, which would switch the gate off through the door built
to keep it on. `output_pattern_problem` is where that is refused, by name.

ONE MODULE, THREE READERS, AND THEY SIT IN TREES THAT CANNOT IMPORT EACH OTHER.
`audit-task.py` asks before writing an entry; the validator asks of an entry
already written, so a manifest cannot carry one the writer would have refused;
and the plan gate under `hooks/` asks the same functions, loading this file by
path because a hook may not import `scripts/`. Both halves - which patterns are
legal, and what a legal one reaches - live here together: two modules holding one
half each is how a pattern comes to be refused by the writer and matched by the
reader, or the other way about.

WHY IT IS NOT IN `_manifest_vocab.py`, which is where it started. That module is
the manifest's WORDS, and a test there walks the import graph out of everything
`hooks/` runtime-loads to hold a premise: nothing on the per-tool-call path
reaches it, so deriving its enums from the schema would cost the validator and the
panel rather than every edit. Putting a rule the plan gate must ask into it spent
that premise for an unrelated reason. `_locks` and `_journal_io` are at this layer
for the same argument stated the other way round - the hook resolves them by path
on every tool call, so the SMALLER the module it loads, the better - and a path
rule is not vocabulary in any case.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__task_outputs.py` - see `plugins/audit/tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
import fnmatch
import os
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


# --- what an `outputs` entry may be ----------------------------------------------
# The characters that make a path segment a pattern rather than a name. Spelled once
# because the rule below asks the question of ONE segment - the first, which decides
# whether the pattern is anchored at all. A wildcard BELOW an anchored head is the
# whole point of the key and is never asked about.
PATTERN_CHARS = "*?["

# The spellings whose first segment is the repository itself. Kept apart from the
# wildcard arm because the refusal has to name which mistake was made: `**` reaches
# every directory, `.` names the root, and a reader who typed one of them meant
# "everything under here" and needs to be told which "here" that was.
ROOT_HEADS = ("", ".", "..", "**")


def output_pattern_problem(pattern):
    """Why this `outputs` entry may not be honoured, or None when it may be.

    THE RULE IS NOT "A GLOB". It is a glob whose FIRST SEGMENT IS A LITERAL
    DIRECTORY NAME. Everything under that name may be a pattern; the name itself
    may not, because that is the segment deciding how much of the repository the
    entry can reach - and an entry reaching all of it is the plan gate switched
    off by a plan.

    Returns the reason as a sentence that NAMES the entry, because a refusal over
    a list is read beside the list and "one of your patterns is too wide" sends
    the reader back to guess which.
    """
    if not isinstance(pattern, str) or not pattern.strip():
        return ("%r is not a path pattern: an `outputs` entry is a "
                "repository-relative prefix, and an empty one names nothing"
                % (pattern,))
    text = pattern.replace("\\", "/").strip()
    if text.startswith("/"):
        return ("%r starts at the filesystem root, and `outputs` is read "
                "relative to the project root" % (pattern,))
    if text.startswith("~"):
        return ("%r is a home path, and `outputs` is read relative to the "
                "project root" % (pattern,))
    segments = text.split("/")
    if ".." in segments:
        return ("%r climbs out of the tree with a `..` segment, so the plan "
                "would cover a file it cannot name twice the same way"
                % (pattern,))
    head = segments[0]
    if head in ROOT_HEADS:
        return ("%r begins at the repository itself (%r), so it covers the "
                "whole tree - and a task that covers the whole tree turns the "
                "plan gate off through the door built to keep it on. Name the "
                "directory the run writes into" % (pattern, head))
    if any(ch in head for ch in PATTERN_CHARS):
        return ("%r begins with a pattern segment (%r) rather than a directory "
                "name, so it reaches every directory in the repository. Anchor "
                "it: the first segment is a literal name, and everything under "
                "it may be a pattern" % (pattern, head))
    return None


def _segments_match(pat_segs, path_segs):
    """Whether the pattern segments match the path segments, with `**` standing
    for any number of segments and every other segment matched WITHIN itself.

    SEGMENT-AWARE ON PURPOSE. `fnmatch` over the whole string lets a single `*`
    cross a separator, so `docs/*` would cover `docs/a/b/c` - and a reader who
    wrote one star and got the whole subtree has been given a wider scope than
    the one they declared. The two spellings mean different things here and both
    are useful: `docs/*` is the directory's own entries, `docs/**` is everything
    under it.
    """
    if not pat_segs:
        return not path_segs
    head = pat_segs[0]
    if head == "**":
        rest = pat_segs[1:]
        if not rest:
            return True
        for i in range(len(path_segs) + 1):
            if _segments_match(rest, path_segs[i:]):
                return True
        return False
    if not path_segs:
        return False
    if not fnmatch.fnmatchcase(path_segs[0], head):
        return False
    return _segments_match(pat_segs[1:], path_segs[1:])


def output_covers(pattern, rel):
    """Whether this `outputs` entry covers the repository-relative path `rel`.

    IT DOES NOT RE-ASK `output_pattern_problem`, and that is the caller's
    obligation rather than an oversight: the graded list is what a caller holds,
    so there is no path on which an ungraded pattern can be matched. Asking here
    too would put the refusal in two places, and the day one of them learned a
    case the other would keep honouring it.

    A TRAILING `/` IS THE DIRECTORY SPELLING that `files` already uses, kept so
    one habit covers both keys; it means the same as `<dir>/**`.
    """
    text = str(pattern or "").replace("\\", "/").strip()
    target = str(rel or "").replace("\\", "/").strip()
    if not text or not target:
        return False
    if text.endswith("/"):
        text += "**"
    return _segments_match([s for s in text.split("/") if s != ""],
                           [s for s in target.split("/") if s != ""])


def output_problems(patterns):
    """`[(entry, reason), ...]` for every `outputs` entry that may not be
    honoured - empty when the list is clean, and empty for a list that is absent
    or is not a list at all.

    THE WRONG TYPE IS SOMEBODY ELSE'S FINDING. A non-array `outputs` is a shape
    error the level that owns the key reports once; reporting it again from here
    would put two sentences about one mistake in front of the reader.
    """
    if not isinstance(patterns, list):
        return []
    graded = [(p, output_pattern_problem(p)) for p in patterns]
    return [(p, why) for p, why in graded if why]


def honoured(patterns):
    """The entries of `patterns` a reader may act on, in document order.

    THE ONE WAY TO A USABLE LIST, so nothing can reach `output_covers` with an
    entry the writer would have refused. The plan gate is the reader this is for:
    a manifest it did not write may carry anything, and a pattern the rule refuses
    has to cover nothing rather than cover everything.
    """
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if output_pattern_problem(p) is None]
