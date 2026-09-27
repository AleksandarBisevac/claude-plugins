#!/usr/bin/env python3
"""
One id renamed everywhere the plan points at it.

Three writers rename ids and each used to know a different subset of the fields
that hold one: `materialize` rewrote the references inside its own payload and no
other, `renumber_duplicate_bugs` rewrote `bug.id` and `task.bugId`, and the resolve
verb for a collision on the development branch needs all of them. A rename that
misses one field leaves a reference to an id that no longer exists - a `blockedBy`
that can never clear, a `fileIndex` row that grants an edit to no task. So the
fields are listed ONCE, here, from the schema's own list of what holds another
record's id.

WHAT IS NEVER REWRITTEN: `movedFrom`. It records the id a task was moved FROM, and
rewriting history to match the present would make the record say the move never
happened. Free text (titles, descriptions, notes) is not touched either - an id
mentioned in a sentence is prose, and a rename that edits prose edits intent.

The functions take a manifest and return a new one; nothing here reads or writes a
file.
"""
import copy
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


# The fields that hold ONE other record's id, and the ones that hold a LIST of them.
# `fixTask` sits on a review finding: the task whose commit settled it.
SCALAR_REFS = ("bugId", "taskId", "materializedAs", "fixTask")
LIST_REFS = ("blockedBy", "dependsOn")
# The lists a phase's review holds findings in. The validator's
# `_manifest_phases.REVIEW_FINDING_LISTS` is the same tuple one layer up, which
# this module may not import; `test__id_refs.py` pins the two equal.
FINDING_LISTS = ("findings", "preExistingNotCharged")


def phase_mapping(phase, new_pid):
    """{old: new} for a phase and each of its tasks: `P2-abc` -> `P7` carries
    `P2-abc.1` -> `P7.1`. A task whose id does not start with the phase's prefix
    keeps it - its id was never derived from the phase's, so there is nothing to
    swap."""
    old = str(phase.get("id"))
    out = {old: new_pid}
    for task in phase.get("tasks") or []:
        tid = str((task or {}).get("id") or "")
        if tid.startswith(old + "."):
            out[tid] = new_pid + tid[len(old):]
    return out


def all_ids(manifest):
    """Every id the plan's namespace holds: phases, tasks, bugs, decisions, and the
    ids parked proposals reserve."""
    ids = set()
    for phase in _phases_and_payloads(manifest):
        ids.add(phase.get("id"))
        ids.update((t or {}).get("id") for t in phase.get("tasks") or [])
    for key in ("bugs", "decisions"):
        ids.update((r or {}).get("id") for r in (manifest or {}).get(key) or [])
    ids.discard(None)
    return ids


def collisions(manifest, mapping):
    """The NEW ids in `mapping` the plan already holds under another record - a
    rename onto one of them would merge two records, so it is refused before any
    write. An id mapped to itself is not a collision."""
    held = all_ids(manifest)
    return sorted(new for old, new in mapping.items() if new != old and new in held)


def _phases_and_payloads(manifest):
    out = [p for p in (manifest or {}).get("phases") or [] if isinstance(p, dict)]
    for prop in (manifest or {}).get("proposals") or []:
        phase = ((prop or {}).get("payload") or {}).get("phase")
        if isinstance(phase, dict):
            out.append(phase)
    return out


def rename(manifest, mapping):
    """(new manifest, count of rewritten occurrences). The input is not mutated."""
    doc = copy.deepcopy(manifest)
    if not mapping:
        return doc, 0
    state = {"n": 0}

    def swap(value):
        if isinstance(value, str) and value in mapping:
            state["n"] += 1
            return mapping[value]
        return value

    def refs(node):
        for key in SCALAR_REFS:
            if key in node:
                node[key] = swap(node[key])
        for key in LIST_REFS:
            if isinstance(node.get(key), list):
                node[key] = [swap(v) for v in node[key]]

    for phase in _phases_and_payloads(doc):
        phase["id"] = swap(phase.get("id"))
        refs(phase)
        review = phase.get("review")
        for key in (FINDING_LISTS if isinstance(review, dict) else ()):
            for finding in review.get(key) or []:
                if isinstance(finding, dict):
                    refs(finding)
        for task in phase.get("tasks") or []:
            if isinstance(task, dict):
                task["id"] = swap(task.get("id"))
                refs(task)
    for bug in doc.get("bugs") or []:
        if isinstance(bug, dict):
            bug["id"] = swap(bug.get("id"))
            refs(bug)
    for prop in doc.get("proposals") or []:
        if isinstance(prop, dict):
            refs(prop)
    index = doc.get("fileIndex")
    if isinstance(index, dict):
        for path in list(index):
            if isinstance(index[path], list):
                index[path] = [swap(v) for v in index[path]]
    return doc, state["n"]
