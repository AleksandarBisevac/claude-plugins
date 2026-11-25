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

A VALUE THAT IS ONE ACCOUNT OF ONE EVENT MERGES WHOLE. A run record and the pointer
beside it, a CI run, a merge stamp with its head, a sign-off's verdict: merged field
by field, a red on the base, a green on one side and a newer red on the other
conflict on the run id, the moment and the duration alone, and keeping one side
there pairs that side's run id with the other side's status - a red read back as
passed. So `MERGE_UNITS` says, for every object value the schema declares on a kind
the merge walks into, whether it is one account (`whole`: changed on both sides is
ONE conflict on the whole value, sibling keys grouped where they are one account
together) or a `container`/`map` merged by field or by key as before. Changed on one
side only is that side's value whole either way. `tests/test__manifest_merge.py`
walks the schema and fails on an object value no row names, so a value added later
is asked the question by name. A group of SIBLING keys is no object, so the schema
cannot ask about it; the suite asks the plan's writers instead - a set of one
record's keys some function under `scripts/` writes together must merge as one unit
(`_units`: one row, or rows joined through a key the writer moved), or carry its
reason in the suite - and the other way, every group the table holds must be
written together somewhere or carry its reason. And every conflict is
rendered as ONE marker block spanning its whole value, so no way of keeping a side
per block yields a value neither side wrote.

WHAT THE MERGE CANNOT SEE: a person typing inside a block, or editing a resolved
record after the merge, writes a value no side wrote. `foreign_values` names one
in a hand-resolved document, for the resolver to refuse; a record the edit left
unreadable is the reader's to report. And a group of sibling keys whose writers the
suite's scan cannot read - keys computed at run time, one record written by two
functions, a record a person writes - is in the table only because somebody read
its writers; the suite's scan says which shapes it reads.

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


# --- what merges whole ------------------------------------------------------------
# (kind, keys, verdict, why). A KIND is where a value sits, named the way the merge
# walks to it: `plan` is the document, `phase`/`task`/`bug`/... a record of a keyed
# list (`ELEMENT_KINDS`), and `<kind>.<key>` an object inside a container - `.*`
# for every entry of a map. `whole`: one account of one event; both sides changed
# it is one conflict on the whole value, and several keys in one row are one value
# together. `container`: merged key by key. `map`: a container whose keys are names
# a writer chooses, its entries of the kind `<kind>.*`. A key no row names merges
# as a container, which is what the merge did for every value before this table -
# and what the schema case refuses for any object value the schema declares.
MERGE_UNITS = (
    ("plan", ("meta",), "container",
     "the plan's settings, each key set by its own verb or by hand"),
    ("plan", ("fileIndex",), "map", "file path -> the task ids touching it, each row a set"),
    ("plan", ("deferred",), "container", "a note and a target beside a list of items"),
    ("plan.meta", ("branch",), "container", "branch naming settings, set apart"),
    ("plan.meta", ("merge",), "container", "landing settings, set apart"),
    ("plan.meta", ("areas",), "map", "area name -> its declaration"),
    ("plan.meta.areas", ("*",), "container", "one area's declaration, its keys set apart"),
    ("plan.meta", ("runtimeBoot",), "container", "boot settings, set apart"),
    ("plan.meta", ("commit",), "container", "commit message settings, set apart"),
    ("plan.meta", ("buildCommands",), "map", "command name -> its command"),
    ("plan.meta", ("phaseGate",), "container", "sign-off gate settings, set apart"),
    ("plan.meta.phaseGate", ("derived",), "container", "derivation settings, set apart"),
    ("plan.meta.phaseGate.derived", ("listing",), "container", "listing commands, set apart"),
    ("plan.meta.phaseGate.derived", ("verifiedOn",), "whole",
     "one verification: the command run and the answer it gave"),
    ("plan.meta", ("ado",), "container", "Azure DevOps settings, set apart"),
    ("plan.meta.ado", ("types",), "container", "work item type per kind, set apart"),
    ("plan.meta.ado", ("identityMap",), "map", "identity -> work item identity"),
    ("plan.meta.ado", ("fields",), "map", "work item type -> its field template"),
    ("plan.meta.ado.fields", ("*",), "container", "one type's field template, field by field"),
    ("plan.meta.ado", ("conventions",), "container", "work item conventions, set apart"),
    ("plan.meta.ado.conventions", ("requiredFields",), "map", "type -> its required fields"),
    ("plan.meta.ado.conventions", ("descriptionMustContain",), "map",
     "type -> what its description must hold"),
    ("plan.meta.ado.conventions", ("tagVocabulary",), "map", "type -> its tags"),
    ("plan.meta.ado", ("stateMap",), "container", "state maps per kind, set apart"),
    ("plan.meta.ado.stateMap", ("phase",), "container", "phase status -> state, per status"),
    ("plan.meta.ado.stateMap", ("task",), "container", "task status -> state, per status"),
    ("plan.meta.ado.stateMap", ("bug",), "container", "bug status -> state, per status"),
    ("plan.meta.ado", ("onComplete",), "container", "completion settings, set apart"),
    ("plan.meta.ado", ("comments",), "container", "comment settings, set apart"),
    ("plan.meta.ado", ("sprint",), "container", "sprint settings, set apart"),
    ("plan.meta.ado", ("pull",), "container", "pull settings, set apart"),
    ("plan.meta.ado", ("hierarchy",), "whole",
     "one fetch of the process hierarchy, with when and on what basis"),
    ("plan.meta.ado", ("parentCandidates",), "whole",
     "one fetch of parent candidates, with when and on what basis"),
    ("plan.meta.ado", ("connection",), "whole",
     "one reading of the connection, with when and on what basis"),
    ("plan.meta", ("evidenceSince",), "whole",
     "one moment the ledger is read from, with the run and the basis that set it"),
    ("plan.meta", ("lastFullRun", "lastMeasuredFullRun"), "whole",
     "the newest full run and the newest measured one, written in one save"),
    ("plan.meta", ("usage",), "container", "usage settings, set apart"),
    ("phase", ("claim",), "whole", "one session's claim: its session, branch and moment"),
    ("phase", ("lastRun", "testEvidence"), "whole",
     "the newest run of the phase's gate and the pointer derived from it: one run"),
    ("phase", ("ci",), "whole", "one CI run: its id, the head it graded, its conclusion"),
    ("phase", ("mergedAt", "mergedHead", "mergedHeadAt"), "whole",
     "one landing: its moment, the commit asked about, when that was recorded"),
    ("phase", ("baseRef", "branch"), "whole",
     "one start: the commit the phase started from and the branch it runs on"),
    ("phase", ("testGateDerived", "testGateBasis"), "whole",
     "one derivation: its answer and the word naming which derivation gave it"),
    ("phase", ("ado",), "whole", "one sync's link to the phase's work item"),
    ("phase", ("adoParent",), "whole", "one declaration of the parent work item"),
    ("phase", ("review",), "container",
     "reviewer settings, findings and the sign-off's verdict, written by different verbs"),
    ("phase.review", ("status", "outcome", "noEvidenceReason", "readReturns",
                      "acceptedCommits"), "whole",
     "one sign-off's verdict: what it decided, the outcome, the reason it gave, the "
     "returns it read and the commits it accepted, written together"),
    ("phase", ("reviewFindings",), "whole", "one legacy tally of found and resolved"),
    ("finding", ("status", "commit", "resolution", "acceptedReason", "carriedTo"),
     "whole", "one finding's disposition: fixed in a commit with what the resolution "
              "says, or accepted with its reason, or carried with where to"),
    ("finding", ("fixTask", "commit"), "whole",
     "the task fixing the finding and the commit it landed in - `add --fixes` writes "
     "the task alone, a landing writes both beside the disposition"),
    ("task", ("tests",), "container", "an authored spec whose fields different verbs set"),
    ("task.tests", ("gate", "gateBasis"), "whole",
     "one gate answer: the commands and the word naming who chose them"),
    ("task.tests", ("falsifiers",), "map", "name -> one falsifier"),
    ("task.tests.falsifiers", ("*",), "whole",
     "one mutation: the file, the text found and what replaces it"),
    ("task", ("lastRun", "testEvidence"), "whole",
     "the newest run of the task and the pointer derived from it: one run"),
    ("task", ("status", "startedAt", "attempts", "blockedReason"), "whole",
     "a move into or out of running: the status with a start's moment and attempt, or "
     "a block's reason"),
    ("task", ("status", "commit", "completedAt", "outcome", "verifiedBy", "redFirst"),
     "whole", "a close or a cancel: the status with the commit it landed in, its moment, "
              "what was done, what verified it and the red-first proof"),
    ("task", ("intentCheck",), "whole",
     "one review verdict on the task's intent, re-recorded alone by its own verb"),
    ("task", ("movedFrom",), "whole", "one move: the id and phase it held, and when"),
    ("task", ("ado",), "whole", "one sync's link to the task's work item"),
    ("task", ("adoParent",), "whole", "one declaration of the parent work item"),
    ("task", ("timing",), "container", "a first start set once beside stages appended"),
    ("bug", ("ado",), "whole", "one sync's link to the bug's work item"),
    ("bug", ("status", "taskId", "fixedIn"), "whole",
     "where the bug stands and what each move wrote with it: the task linked to fix "
     "it, the commit that fixed it"),
    ("decision", ("status", "answer", "decidedBy", "decidedAt"), "whole",
     "one decision: its answer, who gave it and when - written by a person"),
    ("proposal", ("status", "materializedAs", "materializedAt", "droppedAt", "notes"),
     "whole", "one disposition: materialized as a phase at a moment, or dropped with a "
              "note at a moment"),
    ("proposal", ("payload",), "container",
     "the parked phase, merged as a live phase is: an id rename rewrites it in place"),
    ("proposal.payload", ("phase",), "container", "a phase, of the kind `phase`"),
)

# The record kind of a keyed list's elements, by the list's own kind. The schema case
# holds each to the definition the schema's `items` name.
ELEMENT_KINDS = {"plan.phases": "phase", "phase.tasks": "task", "plan.bugs": "bug",
                 "plan.decisions": "decision", "plan.proposals": "proposal",
                 "phase.review.findings": "finding",
                 "phase.review.preExistingNotCharged": "finding"}

# {kind: [keys of each whole value]} and the kinds that are maps, read off the table.
_WHOLE = dict((kind, tuple(row[1] for row in MERGE_UNITS
                           if row[0] == kind and row[2] == "whole"))
              for kind in set(row[0] for row in MERGE_UNITS if row[2] == "whole"))
_MAPS = frozenset("%s.%s" % (row[0], row[1][0]) for row in MERGE_UNITS if row[2] == "map")


# A value inside a container that IS a record of a kind the table already names - a
# parked phase is a phase - merges as that kind. The schema case holds each to the
# definition the schema's `$ref` names.
REF_KINDS = {"proposal.payload.phase": "phase"}


def _child_kind(kind, key):
    """The kind of the value under `key` of a value of `kind`."""
    if kind in _MAPS:
        return "%s.*" % (kind,)
    child = "%s.%s" % (kind, key)
    return REF_KINDS.get(child, child)


def _root_kind(*docs):
    """`phase` for a shard - one phase's body, holding tasks and no phases - else `plan`."""
    for d in docs:
        if isinstance(d, dict) and isinstance(d.get("tasks"), list) and "phases" not in d:
            return "phase"
    return "plan"


def _unit_label(path, keys):
    """`tasks[P1.1].{lastRun,testEvidence}` - a whole value named by its keys."""
    inner = keys[0] if len(keys) == 1 else "{%s}" % (",".join(keys),)
    return "%s.%s" % (_label(path), inner) if path else inner


def _group(doc, keys):
    """{key: value or `_ABSENT`} of `keys` in `doc` - one whole value as a dict."""
    doc = doc if isinstance(doc, dict) else {}
    return dict((k, doc.get(k, _ABSENT)) for k in keys)


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


def _conflict(state, path, ours, theirs, reason, label=None):
    """Record a conflict and return the placeholder standing in for it."""
    n = len(state["conflicts"])
    state["conflicts"].append({"path": label or _label(path), "ours": ours,
                               "theirs": theirs, "reason": reason})
    return "%s%d" % (_PLACEHOLDER, n)


def _merge(path, b, o, t, state, kind):
    """The merged value, or a placeholder after recording a conflict. `_ABSENT` out
    means the key or record is gone. `kind` is where the value sits (`MERGE_UNITS`)."""
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
        return _merge_dict(path, b, o, t, state, kind)
    if _is_keyed_list(b, o, t):
        return _merge_keyed(path, b, o, t, state, kind)
    if _is_id_set(path, b, o, t):
        return _merge_id_set(b, o, t)
    return _conflict(state, path, o, t, "changed on both sides")


def _merge_whole(path, keys, b, o, t, state):
    """{key: merged value or `_ABSENT`} of one whole value - `b`, `o`, `t` each its
    `_group` - taken from one side, or one conflict over all of `keys`."""
    if o == t or t == b:
        return o
    if o == b:
        return t
    absent = [all(v is _ABSENT for v in g.values()) for g in (b, o, t)]
    reason = ("added on both sides with different values" if absent[0] else
              "deleted on one side and changed on the other" if absent[1] or absent[2]
              else "changed on both sides")
    label = _unit_label(path, keys)
    if len(keys) == 1:
        return {keys[0]: _conflict(state, path + (keys[0],), o[keys[0]], t[keys[0]],
                                   reason, label)}
    # Several keys, one conflict: each key holds a placeholder naming the conflict
    # and itself, so a side's resolution restores every key of that side's value.
    n = _conflict(state, path, o, t, reason, label)
    return dict((k, "%s:%s" % (n, k)) for k in keys
                if o[k] is not _ABSENT or t[k] is not _ABSENT)


def _empty_like(o, t):
    """`{}` or `[]` when both sides hold that container, else None."""
    if isinstance(o, dict) and isinstance(t, dict):
        return {}
    if isinstance(o, list) and isinstance(t, list):
        return []
    return None


# ONE ROW IS ONE VERB'S ACCOUNT, AND ROWS MAY SHARE A KEY. A task's status is
# written by a start with its moment and attempt, and by a close with its commit and
# outcome; a finding's commit by a landing beside the fixing task, and beside its
# disposition. A row two sides both changed is one conflict - and so is every row
# it shares a key with that some side moved, since that key is one value and the
# accounts around it come with it: a start against a close is one conflict on both.
# A row only one side changed is that side's, so a retry that moves no status on one
# side and a red-first proof re-recorded on the other both land. A start that moves
# the status changes the close's row too, which holds the status: beside a proof
# re-recorded on the other side that row changed on both, and the two accounts are
# one conflict - landed apart, the close would pair one side's status with the
# other's proof.
def _units(kind, b, o, t, extra=()):
    """The key sets merged as one value each in a record of `kind`: whole rows,
    those both sides changed joined through every key some side moved. A key
    present in no document of (b, o, t) + `extra` is left out."""
    docs = (b, o, t) + tuple(extra)
    rows = [tuple(k for k in keys if any(isinstance(d, dict) and k in d for d in docs))
            for keys in _WHOLE.get(kind, ())]
    rows = [r for r in rows if r]
    base = b if isinstance(b, dict) else {}

    def moved_on(side):
        side = side if isinstance(side, dict) else {}
        return set(k for r in rows for k in r if side.get(k, _ABSENT) != base.get(k, _ABSENT))
    on_o, on_t = moved_on(o), moved_on(t)
    both = [bool(set(r) & on_o) and bool(set(r) & on_t) for r in rows]
    owner = list(range(len(rows)))

    def root(i):
        while owner[i] != i:
            i = owner[i]
        return i
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if (both[i] or both[j]) and set(rows[i]) & set(rows[j]) & (on_o | on_t):
                owner[root(j)] = root(i)
    # A key no side moved that two rows share goes to the unit both sides changed,
    # so a conflict shows the whole account it is about.
    units, claimed = [], set()
    for r in sorted(set(root(i) for i in range(len(rows))),
                    key=lambda r: (not any(both[i] for i in range(len(rows)) if root(i) == r),
                                   r)):
        keys = []
        for i in range(len(rows)):
            if root(i) == r:
                keys.extend(k for k in rows[i] if k not in keys and k not in claimed)
        claimed.update(keys)
        if keys:
            units.append(tuple(keys))
    return units


def _merge_dict(path, b, o, t, state, kind):
    values, grouped = {}, set()
    for present in _units(kind, b, o, t):
        grouped.update(present)
        merged = _merge_whole(path, present, _group(b, present), _group(o, present),
                              _group(t, present), state)
        values.update((k, v) for k, v in merged.items() if v is not _ABSENT)
    for k in (set(b) | set(o) | set(t)) - grouped:
        v = _merge(path + (k,), b.get(k, _ABSENT), o.get(k, _ABSENT),
                   t.get(k, _ABSENT), state, _child_kind(kind, k))
        if v is not _ABSENT:
            values[k] = v
    order = merge_order(list(b), list(o), list(t), set(values))
    if order is None:
        # Key order means nothing in a manifest object, so two different reorders
        # are not worth a human's time - but the fallback must still be symmetric.
        order = sorted(values, key=natural_key)
    return dict((k, values[k]) for k in order)


def _merge_keyed(path, b, o, t, state, kind):
    by = [dict((e["id"], e) for e in s) if isinstance(s, list) else {}
          for s in (b, o, t)]
    values = {}
    element = ELEMENT_KINDS.get(kind, "%s[]" % (kind,))
    for i in set(by[0]) | set(by[1]) | set(by[2]):
        v = _merge(path + (("id", i),), by[0].get(i, _ABSENT), by[1].get(i, _ABSENT),
                   by[2].get(i, _ABSENT), state, element)
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
    doc = _merge((), base, ours, theirs, state, _root_kind(base, ours, theirs))
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


# --- reading a hand resolution ------------------------------------------------------
def foreign_values(base, ours, theirs, held, also=()):
    """[{"path"}] of every whole value (`MERGE_UNITS`) `held` - a document a person
    resolved - holds that is neither base's, ours' nor theirs' (nor one in `also`, a
    side as resolve renumbered it) at the same place: one account assembled from
    two, or written after the merge. A key of the value `held` lacks while a side
    holds it counts as a difference, so a pointer deleted by hand is named. A record
    only `held` holds has no side to match, so a whole value in it is named too.
    Containers are not judged: a field of one edited by hand is an ordinary edit."""
    out = []
    sides = (base, ours, theirs) + tuple(also)
    _foreign((), _root_kind(held, base, ours, theirs), held, sides, out)
    return out


def _foreign(path, kind, held, sides, out):
    if isinstance(held, dict):
        grouped = set()
        for present in _units(kind, sides[0], sides[1], sides[2], (held,) + tuple(sides[3:])):
            grouped.update(present)
            if _group(held, present) not in [_group(s, present) for s in sides]:
                out.append({"path": _unit_label(path, present)})
        for k, v in held.items():
            if k not in grouped:
                _foreign(path + (k,), _child_kind(kind, k), v,
                         [s.get(k, _ABSENT) if isinstance(s, dict) else _ABSENT
                          for s in sides], out)
    elif _is_keyed_list(held):
        element = ELEMENT_KINDS.get(kind, "%s[]" % (kind,))
        by = [dict((e.get("id"), e) for e in s if isinstance(e, dict))
              if isinstance(s, list) else {} for s in sides]
        for e in held:
            _foreign(path + (("id", e["id"]),), element, e,
                     [b.get(e["id"], _ABSENT) for b in by], out)


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
        n, _sep, key = value[len(_PLACEHOLDER):].partition(":")
        chosen = conflicts[int(n)][side]
        if not key:
            return chosen
        return chosen.get(key, _ABSENT) if isinstance(chosen, dict) else _ABSENT
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


def _spans(held, side):
    """{conflict number: (first line, end line)} of each conflict's value in `side`,
    one side's rendering, read off its line diff against `held`, the rendering with
    every conflict a placeholder: what differs there is what a conflict put there.
    A value written as several keys runs from its first key's lines to its last."""
    spans = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, held, side).get_opcodes():
        if tag == "equal":
            continue
        for n in set(int(m) for line in held[i1:i2] for m in _PLACEHOLDER_RE.findall(line)):
            lo, hi = spans.get(n, (j1, j2))
            spans[n] = (min(lo, j1), max(hi, j2))
    return spans


def _masked(lines, spans, tag):
    """`lines` with every line inside a conflict's span made unique to this side."""
    inside = set(i for lo, hi in spans.values() for i in range(lo, hi))
    return [(tag, i) if i in inside else line for i, line in enumerate(lines)]


def _meets(span, lo, hi):
    """True when a conflict's `span` lies in or touches the hunk `lo`..`hi`."""
    if span is None:
        return False
    return span[0] < hi and span[1] > lo if span[0] < span[1] else lo <= span[0] <= hi


def render(result, dump, labels=("ours", "theirs")):
    """The merged document as text, with a conflict-marker block wherever the two
    resolutions differ - so a human resolving it sees ONLY the records that really
    disagree, instead of every append point in the file.

    `dump(obj)` is the serialiser the plugin writes manifests with. Each block's
    first marker names the conflicts it holds, by record id; when adjacent
    conflicts share one block, it names all of them."""
    conflicts = result["conflicts"]
    text = dump(result["doc"])
    # One plan's conflict list is rendered against each of its files; a file holding
    # none of them is both sides' alike, and reading three line diffs of it to learn
    # so cost the sharded resolver most of its run.
    if not conflicts or not _PLACEHOLDER_RE.search(text):
        return text
    held = text.split("\n")
    sides, spans = [], []
    for side in ("ours", "theirs"):
        doc = _resolve(result["doc"], conflicts, side)
        sides.append(("" if doc is _ABSENT else dump(doc)).split("\n"))
        spans.append(_spans(held, sides[-1]))
    o_lines, t_lines = sides
    # A CONFLICT'S LINES NEVER MATCH THE OTHER SIDE'S, so each conflict is one block
    # spanning its whole value. Lines two runs share - a status, an empty list -
    # would otherwise split a run record into blocks a person keeps one by one, and
    # one side's run id kept beside the other side's status is a run neither wrote.
    # `autojunk` stays on: it is what keeps a plan of tens of thousands of lines
    # fast, and any alignment the matcher picks keeps both pure resolutions exact.
    o_tok, t_tok = (_masked(lines, sp, tag) for lines, sp, tag
                    in ((o_lines, spans[0], "o"), (t_lines, spans[1], "t")))
    hunks = [op for op in difflib.SequenceMatcher(None, o_tok, t_tok).get_opcodes()
             if op[0] != "equal"]
    order = []
    for n in (int(m) for m in _PLACEHOLDER_RE.findall("\n".join(held))):
        if n not in order:
            order.append(n)
    names = dict((n, "%s: %s" % (conflicts[n]["path"], conflicts[n]["reason"]))
                 for n in order)
    out, at = [], 0
    for _tag, i1, i2, j1, j2 in hunks:
        out.extend(o_lines[at:i1])
        inside = [n for n in order if _meets(spans[0].get(n), i1, i2)
                  or _meets(spans[1].get(n), j1, j2)]
        label = "; ".join(names[n] for n in (inside or order))
        out.append("<<<<<<< %s  (%s)" % (labels[0], label))
        out.extend(o_lines[i1:i2])
        out.append("=======")
        out.extend(t_lines[j1:j2])
        out.append(">>>>>>> %s" % (labels[1],))
        at = i2
    out.extend(o_lines[at:])
    return "\n".join(out)
