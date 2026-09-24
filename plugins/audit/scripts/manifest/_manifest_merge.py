#!/usr/bin/env python3
"""
Three-way merge of a manifest document by RECORD, for the git merge driver.

Every structural writer appends at the tail of a list - a phase, a task, a bug, a
`fileIndex` row - so two branches that each add a different record write the same
lines, and git's line merge stops on a conflict nothing disagrees about. On a plan
of a few hundred phases a human cannot tell that hunk from a real one. This merges
the parsed documents instead: a record is matched by its `id` rather than by where
it sits, so the only conflicts left are the ones a person has to decide.

WHAT COUNTS AS A CONFLICT, and the line is drawn where a human would draw it:
  - the same field of the same record changed to two different values;
  - a record deleted on one side and changed on the other;
  - the same id ADDED on both sides with different content. That is two branches
    minting one `max+1` id, a real collision, and it is never renumbered here:
    renaming it on either side would make the two branches disagree about what the
    id names the next time they meet.
A list of plain values changed on both sides is a conflict too, with ONE exception
the schema supplies: a `fileIndex` row is a set of task ids, and two branches
naturally add a task each to the same file's row.

THE ORDER IS A FUNCTION OF THE THREE INPUTS, NOT OF WHICH SIDE IS "OURS". Phase
order is execution order for `/audit:next`, so merging `develop` into a branch and
the branch into `develop` must produce the same bytes. Records keep the base's
order; a record added on one side goes after the record it followed on that side,
and one added at a side's tail goes at the tail; when both sides insert at the same
place, their runs are ordered by a natural sort of each run's first id. A reorder of
existing records is taken from the one side that made it, and is a conflict when
both sides made different ones.

The functions take and return values; the driver that reads files and talks to git
is `merge-manifest.py`.
"""
import difflib
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


# A value that is not there. `None` cannot play this part: `null` is a legal JSON
# value, and "set to null on one side" must not read as "deleted on one side".
_ABSENT = object()

# The prefix of a placeholder string standing in for a conflicted value while the
# merged document is serialised. It begins with a NUL, which no manifest string
# carries, so a real value can never be mistaken for one.
_PLACEHOLDER = "\u0000audit-merge-conflict-"

# The anchor of a run added at a side's tail: it goes at the merged tail, not after
# whichever record happened to be last on that side.
_END = object()


# --- ordering -------------------------------------------------------------------
def natural_key(text):
    """`P9` before `P10`, `BUG-2` before `BUG-12`: digits compare as numbers."""
    return [(0, int(tok), "") if tok.isdigit() else (1, 0, tok)
            for tok in re.findall(r"\d+|\D+", "%s" % (text,))]


def _skeleton(base_seq, ours_seq, theirs_seq, keep):
    """The surviving BASE ids in the order the merge keeps them, or None when the
    two sides reordered them in two different ways."""
    base = [k for k in base_seq if k in keep]
    base_set = set(base)
    ours = [k for k in ours_seq if k in base_set]
    theirs = [k for k in theirs_seq if k in base_set]
    # Compare only ids BOTH sides still list, so a deletion never reads as a reorder.
    common = set(ours) & set(theirs)
    b_c = [k for k in base if k in common]
    o_c = [k for k in ours if k in common]
    t_c = [k for k in theirs if k in common]
    if o_c == b_c and t_c == b_c:
        return base
    if t_c == b_c:
        chosen = o_c
    elif o_c == b_c or o_c == t_c:
        chosen = t_c
    else:
        return None
    # Survivors one side no longer lists (a conflicted delete) go back after
    # their nearest base predecessor.
    out = list(chosen)
    for i, k in enumerate(base):
        if k in common:
            continue
        before = [p for p in base[:i] if p in out]
        out.insert(out.index(before[-1]) + 1 if before else 0, k)
    return out


def _runs(side_seq, skeleton_set, keep):
    """{anchor: [added ids, in this side's order]}. `anchor` is the last skeleton
    id seen before the run, None for the head, `_END` for a run at the tail."""
    runs, pending = {}, []
    anchor = None
    for k in side_seq:
        if k in skeleton_set:
            if pending:
                runs.setdefault(anchor, []).extend(pending)
                pending = []
            anchor = k
        elif k in keep:
            pending.append(k)
    if pending:
        runs.setdefault(_END, []).extend(pending)
    return runs


def merge_order(base_seq, ours_seq, theirs_seq, keep):
    """The order of the merged ids (every id in `keep`, once), or None when the two
    sides reordered existing ids in two different ways."""
    skeleton = _skeleton(base_seq, ours_seq, theirs_seq, keep)
    if skeleton is None:
        return None
    sk = set(skeleton)
    o_runs = _runs(ours_seq, sk, keep)
    t_runs = _runs(theirs_seq, sk, keep)
    out, seen = [], set()

    def emit(anchor):
        runs = [r for r in (o_runs.get(anchor), t_runs.get(anchor)) if r]
        for run in sorted(runs, key=lambda r: [natural_key(k) for k in r]):
            for k in run:
                if k not in seen:
                    seen.add(k)
                    out.append(k)

    emit(None)
    for k in skeleton:
        out.append(k)
        seen.add(k)
        emit(k)
    emit(_END)
    return out


# --- merging --------------------------------------------------------------------
def _is_keyed_list(*seqs):
    """True when every element of every present list is an object carrying a
    string `id`, unique within its own list - the shape of `phases`, `tasks`,
    `bugs`, `proposals`, `deferred` and `decisions`."""
    lists = [s for s in seqs if s is not _ABSENT]
    if not lists or not all(isinstance(s, list) for s in lists):
        return False
    for s in lists:
        ids = [e.get("id") if isinstance(e, dict) else None for e in s]
        if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            return False
    return any(lists)


def _is_id_set(path, *seqs):
    """A `fileIndex` row: a list of unique task-id strings, merged as a set."""
    if len(path) != 2 or path[0] != "fileIndex":
        return False
    for s in seqs:
        if s is _ABSENT:
            continue
        if not isinstance(s, list) or not all(isinstance(e, str) for e in s) \
                or len(set(s)) != len(s):
            return False
    return True


def _label(path):
    """`phases[P1].tasks[P1.1].status` - a record named by its id, never its index."""
    parts = []
    for p in path:
        if isinstance(p, tuple):
            parts.append("[%s]" % (p[1],))
        else:
            parts.append(("." if parts else "") + "%s" % (p,))
    return "".join(parts) or "(document)"


def _conflict(state, path, ours, theirs, reason):
    """Record a conflict and return the placeholder standing in for it."""
    n = len(state["conflicts"])
    state["conflicts"].append({"path": _label(path), "ours": ours, "theirs": theirs,
                               "reason": reason})
    return "%s%d" % (_PLACEHOLDER, n)


def _merge(path, b, o, t, state):
    """The merged value, or a placeholder after recording a conflict. `_ABSENT` out
    means the key or record is gone."""
    if o == t:
        return o
    if o == b:
        return t
    if t == b:
        return o
    if b is _ABSENT:
        # A RECORD minted on both sides is an id collision, whatever its shape -
        # merging the two bodies would make one id name two things' fields.
        if path and isinstance(path[-1], tuple):
            return _conflict(state, path, o, t,
                             "the same id was added on both sides with different content")
        # Anything else new on both sides merges as if the base held an empty one
        # of its shape: two branches first touching one file both create its
        # `fileIndex` row, and that must be the union a row that existed gets.
        empty = _empty_like(o, t)
        if empty is None:
            return _conflict(state, path, o, t, "added on both sides with different values")
        b = empty
    if o is _ABSENT or t is _ABSENT:
        return _conflict(state, path, o, t, "deleted on one side and changed on the other")
    if isinstance(b, dict) and isinstance(o, dict) and isinstance(t, dict):
        return _merge_dict(path, b, o, t, state)
    if _is_keyed_list(b, o, t):
        return _merge_keyed(path, b, o, t, state)
    if _is_id_set(path, b, o, t):
        return _merge_id_set(b, o, t)
    return _conflict(state, path, o, t, "changed on both sides")


def _empty_like(o, t):
    """`{}` or `[]` when both sides hold that container, else None."""
    if isinstance(o, dict) and isinstance(t, dict):
        return {}
    if isinstance(o, list) and isinstance(t, list):
        return []
    return None


def _merge_dict(path, b, o, t, state):
    values = {}
    for k in set(b) | set(o) | set(t):
        v = _merge(path + (k,), b.get(k, _ABSENT), o.get(k, _ABSENT),
                   t.get(k, _ABSENT), state)
        if v is not _ABSENT:
            values[k] = v
    order = merge_order(list(b), list(o), list(t), set(values))
    if order is None:
        # Key order means nothing in a manifest object, so two different reorders
        # are not worth a human's time - but the fallback must still be symmetric.
        order = sorted(values, key=natural_key)
    return dict((k, values[k]) for k in order)


def _merge_keyed(path, b, o, t, state):
    by = [dict((e["id"], e) for e in s) if isinstance(s, list) else {}
          for s in (b, o, t)]
    values = {}
    for i in set(by[0]) | set(by[1]) | set(by[2]):
        v = _merge(path + (("id", i),), by[0].get(i, _ABSENT), by[1].get(i, _ABSENT),
                   by[2].get(i, _ABSENT), state)
        if v is not _ABSENT:
            values[i] = v
    order = merge_order(list(by[0]), list(by[1]), list(by[2]), set(values))
    if order is None:
        return _conflict(state, path, o, t, "records reordered differently on both sides")
    return [values[i] for i in order]


def _merge_id_set(b, o, t):
    b, o, t = [s if isinstance(s, list) else [] for s in (b, o, t)]
    removed = (set(b) - set(o)) | (set(b) - set(t))
    keep = (set(b) | set(o) | set(t)) - removed
    order = merge_order(b, o, t, keep)
    return order if order is not None else sorted(keep, key=natural_key)


def merge3(base, ours, theirs):
    """Merge three parsed documents.

    Returns {"doc": merged (a placeholder wherever conflicted), "conflicts": [...],
    "counts": {"ours": n, "theirs": n}}. The counts are the top-level records each
    side added or changed, so the driver can say WHAT it merged."""
    state = {"conflicts": []}
    doc = _merge((), base, ours, theirs, state)
    return {"doc": doc, "conflicts": state["conflicts"],
            "counts": {"ours": _changed_records(base, ours),
                       "theirs": _changed_records(base, theirs)}}


def collision(ours, theirs, reason):
    """A merge3-shaped result in which the WHOLE document is one conflict - for a
    file that is itself a record, created on both sides (a shard: one phase id
    minted on two branches), whose two bodies must never be merged into one."""
    return {"doc": _PLACEHOLDER + "0",
            "conflicts": [{"path": "(document)", "ours": ours, "theirs": theirs,
                           "reason": reason}],
            "counts": {"ours": 1, "theirs": 1}}


def _records(doc):
    if not isinstance(doc, dict):
        return {}
    return dict(((key, e["id"]), e) for key, val in doc.items()
                if _is_keyed_list(val) for e in val)


def _changed_records(base, side):
    """Top-level records (a phase, a bug, a task of a shard) `side` added or changed."""
    rb = _records(base)
    return sum(1 for k, v in _records(side).items() if rb.get(k, _ABSENT) != v)


# --- rendering ------------------------------------------------------------------
# THE BLOCKS COME FROM TWO COMPLETE DOCUMENTS, NOT FROM PATCHING ONE. A value's
# marker block cannot own the commas around it: when the conflicted record is the
# last in its list and one side deleted it, the comma that has to go sits on the
# sibling BEFORE the block, and with two adjacent conflicts it belongs to neither
# block alone. So each side is rendered whole - every conflict resolved its way,
# which is valid JSON by construction - and the blocks are the line diff between
# the two. Keeping one side throughout reproduces that side's document exactly.
_PLACEHOLDER_RE = re.compile(re.escape(json.dumps(_PLACEHOLDER)[1:-1]) + r"(\d+)")


def _resolve(value, conflicts, side):
    """`value` with every placeholder replaced by that conflict's `side` value, and
    dropped where that side deleted it."""
    if isinstance(value, str) and value.startswith(_PLACEHOLDER):
        return conflicts[int(value[len(_PLACEHOLDER):])][side]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            r = _resolve(v, conflicts, side)
            if r is not _ABSENT:
                out[k] = r
        return out
    if isinstance(value, list):
        return [r for r in (_resolve(v, conflicts, side) for v in value) if r is not _ABSENT]
    return value


def render(result, dump, labels=("ours", "theirs")):
    """The merged document as text, with a conflict-marker block wherever the two
    resolutions differ - so a human resolving it sees ONLY the records that really
    disagree, instead of every append point in the file.

    `dump(obj)` is the serialiser the plugin writes manifests with. Each block's
    first marker names the conflicts it holds, by record id; when adjacent
    conflicts share one block, it names all of them."""
    conflicts = result["conflicts"]
    if not conflicts:
        return dump(result["doc"])
    sides = []
    for side in ("ours", "theirs"):
        doc = _resolve(result["doc"], conflicts, side)
        sides.append("" if doc is _ABSENT else dump(doc))
    o_lines, t_lines = sides[0].split("\n"), sides[1].split("\n")
    # `autojunk` stays on: it is what keeps a plan of tens of thousands of lines
    # fast, and any alignment the matcher picks keeps both pure resolutions exact.
    hunks = [op for op in difflib.SequenceMatcher(None, o_lines, t_lines).get_opcodes()
             if op[0] != "equal"]
    order = [int(n) for n in _PLACEHOLDER_RE.findall(dump(result["doc"]))]
    names = ["%s: %s" % (conflicts[n]["path"], conflicts[n]["reason"]) for n in order]
    out, at = [], 0
    for i, (_tag, i1, i2, j1, j2) in enumerate(hunks):
        out.extend(o_lines[at:i1])
        label = names[i] if len(hunks) == len(names) else "; ".join(names)
        out.append("<<<<<<< %s  (%s)" % (labels[0], label))
        out.extend(o_lines[i1:i2])
        out.append("=======")
        out.extend(t_lines[j1:j2])
        out.append(">>>>>>> %s" % (labels[1],))
        at = i2
    out.extend(o_lines[at:])
    return "\n".join(out)
