"""A task's timing record: the stages of its wall time, and the reading of them.

`task.startedAt` is re-stamped on every restart, so it cannot say when work on a
task began, and nothing on a task said where its wall time went. `timing` is the
record that does both: `firstStartedAt`, set by the first start and never moved,
and `stages`, one entry per measured stretch - a writer round, a gate run, the
time spent choosing what to run, a base measurement, the review, the record
commit, a handed-out step's wait - each with its start, its length and the
record the length was read from.

ONE MODULE, EVERY WRITER AND EVERY READER. The verbs that record a stage, the
validator that grades a record, and the status surfaces that print one all ask
these functions, so a stage is built, checked and summed one way. The kinds and
the keys are this module's tables; the published schema states the same lists,
and `tests/test__task_timing.py` holds the two to agreeing item for item.

A MISSING SOURCE IS NAMED, NEVER READ AS ZERO. A summary of a task with no
`completedAt`, no record, no first start or a stage it cannot read gives no
window and no total, and says which of those it lacked: a zero there would be a
measurement nobody made. A kind no stage recorded is absent from the totals for
the same reason.

This module carries no `--selftest` of its own; its cases live in
`tests/test__task_timing.py` - see `tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
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

import _usage_core  # noqa: E402  (parse_ts: the one reading of an ISO stamp)


# --- the vocabulary -----------------------------------------------------------
# A CLOSED LIST, in the order a task's work runs: the writer, the gate and the
# choosing of what it ran, the base measurement, the review, the record commit,
# and the wait before a handed-out step started. The schema's
# `timingStage` definition gives `kind` the same list as its enum.
KINDS = ("writer", "gate", "selection", "base", "reviewer", "commit", "wait")
TIMING_KEYS = frozenset(["firstStartedAt", "stages"])
STAGE_KEYS = frozenset(["kind", "startedAt", "ms", "basis", "round", "runId"])
WINDOW_BASIS = "timing.firstStartedAt -> completedAt"


def _is_count(value):
    """An int that is not a bool - `True` is an int to Python and a length to
    nobody."""
    return isinstance(value, int) and not isinstance(value, bool)


# --- building a stage, and the record it joins --------------------------------
def make_stage(kind, started_at, ms, basis, round=None, run_id=None):
    """One stage, shaped as the schema describes it; `round` and `runId` are
    written only when given, so a stage never carries a null it was not asked
    for. It does not grade its arguments - `stage_problems` does, and the
    validator asks it of every stage a plan carries."""
    stage = {"kind": kind, "startedAt": started_at, "ms": ms, "basis": basis}
    if round is not None:
        stage["round"] = round
    if run_id is not None:
        stage["runId"] = run_id
    return stage


def _timing_of(task):
    timing = task.get("timing") if isinstance(task, dict) else None
    return timing if isinstance(timing, dict) else None


def append_stage(task, stage):
    """The task's timing record with `stage` appended last, as a NEW dict: the
    task handed in is not touched. A task with no record gets one holding that
    stage alone, and no first start is invented for it - only a start writes
    that."""
    timing = dict(_timing_of(task) or {})
    stages = timing.get("stages")
    timing["stages"] = (list(stages) if isinstance(stages, list) else []) + [stage]
    return timing


def first_start(task, at):
    """The task's timing record with `firstStartedAt` set to `at` when it has
    none, and unchanged when it has one: a restart moves `startedAt` and never
    this. A new dict; the stages already recorded are kept."""
    timing = dict(_timing_of(task) or {})
    if not isinstance(timing.get("stages"), list):
        timing["stages"] = []
    if not (isinstance(timing.get("firstStartedAt"), str)
            and timing.get("firstStartedAt")):
        timing["firstStartedAt"] = at
    return timing


# --- grading a record ---------------------------------------------------------
def stage_problems(stage):
    """What is wrong with one stage, one sentence per fault, each opening with
    the field it is about; [] for a well-formed stage."""
    if not isinstance(stage, dict):
        return ["not an object, got %s" % (type(stage).__name__,)]
    out = []
    if stage.get("kind") not in KINDS:
        out.append("kind %r is not one of %s" % (stage.get("kind"), list(KINDS)))
    if _usage_core.parse_ts(stage.get("startedAt")) is None:
        out.append("startedAt %r is not an ISO timestamp"
                   % (stage.get("startedAt"),))
    ms = stage.get("ms")
    if not _is_count(ms) or ms < 0:
        out.append("ms %r is not a non-negative integer" % (ms,))
    basis = stage.get("basis")
    if not (isinstance(basis, str) and basis.strip()):
        out.append("basis is missing - a length with no record it was read "
                   "from cannot be checked")
    if "round" in stage and not (_is_count(stage["round"]) and stage["round"] >= 1):
        out.append("round %r is not a positive integer" % (stage["round"],))
    if "runId" in stage and not (isinstance(stage["runId"], str)
                                 and stage["runId"].strip()):
        out.append("runId %r is not a non-empty string" % (stage["runId"],))
    return out


def timing_problems(timing):
    """What is wrong with a task's `timing` value, each sentence opening with
    the path under `timing` it is about (`stages[1]: kind ...`); [] when it is
    well formed. Unknown keys are not graded here - the validator warns about
    them against `TIMING_KEYS` and `STAGE_KEYS`, the way it warns at every
    level."""
    if not isinstance(timing, dict):
        return ["must be an object, got %s" % (type(timing).__name__,)]
    out = []
    if "firstStartedAt" in timing \
            and _usage_core.parse_ts(timing["firstStartedAt"]) is None:
        out.append("firstStartedAt %r is not an ISO timestamp"
                   % (timing["firstStartedAt"],))
    stages = timing.get("stages", [])
    if not isinstance(stages, list):
        return out + ["stages must be an array, got %s" % (type(stages).__name__,)]
    for i, stage in enumerate(stages):
        out.extend("stages[%d]: %s" % (i, why) for why in stage_problems(stage))
    return out


# --- the summary --------------------------------------------------------------
def _by_kind(stages):
    """Per-kind totals in `KINDS` order, holding only the kinds a stage
    recorded."""
    rows = {}
    for kind in KINDS:
        mine = [s for s in stages if s.get("kind") == kind]
        if mine:
            rows[kind] = {"ms": sum(s["ms"] for s in mine), "stages": len(mine),
                          "basis": sorted(set(s["basis"] for s in mine))}
    return rows


def summarize(task):
    """Where a task's wall time went: per-kind totals, the window from
    `timing.firstStartedAt` to `completedAt`, and the part of the window no
    stage accounts for.

    `missing` names every source the figures needed and did not find - `timing`,
    `timing.firstStartedAt`, a `timing.stages[i]` that cannot be read, or
    `completedAt` - and while it names any, `windowMs`, `attributedMs` and
    `unattributedMs` are None rather than a number nobody measured. When stages
    overlap and sum past the window, `unattributedMs` is 0 and `overrunMs` says
    by how much, so `attributedMs - overrunMs + unattributedMs` is the window
    either way."""
    timing = _timing_of(task)
    missing = []
    stages = []
    if timing is None:
        missing.append("timing")
    else:
        if _usage_core.parse_ts(timing.get("firstStartedAt")) is None:
            missing.append("timing.firstStartedAt")
        raw = timing.get("stages")
        raw = raw if isinstance(raw, list) else []
        for i, stage in enumerate(raw):
            if stage_problems(stage):
                missing.append("timing.stages[%d]" % (i,))
            else:
                stages.append(stage)
    completed = _usage_core.parse_ts(task.get("completedAt")) \
        if isinstance(task, dict) else None
    if completed is None:
        missing.append("completedAt")
    summary = {"byKind": _by_kind(stages), "windowBasis": WINDOW_BASIS,
               "windowMs": None, "attributedMs": None, "unattributedMs": None,
               "overrunMs": None, "missing": missing}
    if missing:
        return summary
    window = int(round((completed - _usage_core.parse_ts(
        timing["firstStartedAt"])) * 1000))
    if window < 0:
        summary["missing"] = ["a window: completedAt precedes "
                              "timing.firstStartedAt"]
        return summary
    attributed = sum(row["ms"] for row in summary["byKind"].values())
    summary.update(windowMs=window, attributedMs=attributed,
                   unattributedMs=max(0, window - attributed),
                   overrunMs=max(0, attributed - window))
    return summary
