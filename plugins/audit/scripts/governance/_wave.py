"""Which ready tasks may run together, and what an overlap between two is.

A wave is a set of ready tasks whose declared `files` are provably disjoint, so
each can be edited in a tree of its own and integrated afterwards. The proof is
the declaration and nothing else: a task that declares no files cannot be shown
disjoint from anything, so it runs alone. These are pure functions over task
dicts (`id`, `files`) so the driver's wave step, the integration step and their
tests all ask ONE rule; the question "do these two paths touch" is
`_task_outputs.covers`, never re-spelled here.

An overlap is graded, not just found. A file two tasks both edit can usually be
merged per path; a lockfile cannot - two machine-written files merged by text
produce a file no tool wrote - so an overlap that reaches one is refused
whatever else it reaches.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__wave.py` - see `plugins/audit/tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
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

import _task_outputs  # noqa: E402


# --- what is not mergeable -------------------------------------------------------
# Machine-written files whose text cannot be merged by line. A name ending in
# `.lock` covers Cargo.lock, uv.lock, poetry.lock, yarn.lock, Gemfile.lock,
# composer.lock and Pipfile.lock; the rest do not end that way.
NON_MERGEABLE_NAMES = frozenset((
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "bun.lockb", "go.sum",
))


def _bare(entry):
    """The entry as a path: backslashes read as separators, a `:line-range`
    suffix and a trailing slash dropped - the spelling `covers` itself reads."""
    text = re.sub(r":[0-9][0-9,-]*\Z", "", str(entry).replace("\\", "/"))
    return text.rstrip("/")


def is_non_mergeable(path):
    """Whether this path's class cannot be merged by text."""
    name = _bare(path).rsplit("/", 1)[-1]
    return name in NON_MERGEABLE_NAMES or name.endswith(".lock")


def _declared(task):
    """The task's non-blank declared entries, bare, in a stable order."""
    return sorted(set(b for b in (_bare(f) for f in (task.get("files") or [])
                                  if isinstance(f, str)) if b))


def _shared(a_entries, b_entries):
    """The paths both lists reach: for each overlapping pair the MORE SPECIFIC
    entry (the longer one - the directory covers it, so the file is what both
    can touch)."""
    found = set()
    for x in a_entries:
        for y in b_entries:
            if _task_outputs.covers(x, y) or _task_outputs.covers(y, x):
                found.add(x if len(x) >= len(y) else y)
    return sorted(found)


def overlap(a, b):
    """None when the two tasks share no declared path, else
    `{"tasks": [id, id], "paths": [...], "mergeable": bool, "nonMergeable":
    [...]}` with the ids in sorted order, so the argument order changes
    nothing. A task declaring no files shares nothing it can name: None."""
    paths = _shared(_declared(a), _declared(b))
    if not paths:
        return None
    bad = [p for p in paths if is_non_mergeable(p)]
    return {"tasks": sorted([a.get("id"), b.get("id")]), "paths": paths,
            "mergeable": not bad, "nonMergeable": bad}


# --- choosing a wave -------------------------------------------------------------
def _valid_width(width):
    return isinstance(width, int) and not isinstance(width, bool) and width >= 1


def select(tasks, width):
    """`{"wave": [ids], "deferred": [{"id", "reason", "with"}]}`.

    `tasks` are the READY tasks in the order the caller wants them run (id
    order); this takes each in turn and adds it when the wave has room and its
    files are disjoint from every task already chosen. A task with no declared
    files is chosen only into an EMPTY wave and then closes it. A deferred task
    says why - `width`, `overlap` (with whom) or `undeclared` - so nothing is
    left out silently. `width` must be an integer of at least 1: 'auto' is
    resolved by the caller, and a 0 would otherwise read as 'run nothing,
    successfully'."""
    if not _valid_width(width):
        raise ValueError("wave width must be an integer of at least 1, got %r"
                         % (width,))
    wave, deferred = [], []
    chosen = []
    closed = False
    for task in tasks:
        tid = task.get("id")
        files = _declared(task)
        if closed:
            deferred.append({"id": tid, "reason": "undeclared",
                             "with": wave[0]})
            continue
        if len(wave) >= width:
            deferred.append({"id": tid, "reason": "width", "with": None})
            continue
        if not files:
            if wave:
                deferred.append({"id": tid, "reason": "undeclared",
                                 "with": None})
                continue
            wave.append(tid)
            chosen.append(task)
            closed = True
            continue
        clash = next((c.get("id") for c in chosen if overlap(c, task)), None)
        if clash is not None:
            deferred.append({"id": tid, "reason": "overlap", "with": clash})
            continue
        wave.append(tid)
        chosen.append(task)
    return {"wave": wave, "deferred": deferred}

