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
`completedAt`, no record, no first start, a `stages` value that is not a list
or a stage it cannot read gives no window and no total, and says which of
those it lacked: a zero there would be a measurement nobody made. A kind no
stage recorded is absent from the totals for the same reason.

THE WINDOW RUNS FROM THE FIRST START, WHATEVER HAPPENED BETWEEN. The first
start never moves, so a task reopened after it was done has a window from that
first start to its NEW completion, and the time it sat closed is inside it as
unattributed time. A median of windows is therefore time on the plan, not
time worked, for any task that was reopened.

This module carries no `--selftest` of its own; its cases live in
`tests/test__task_timing.py` - see `tests/_harness.py`.

Stdlib only, Python 3.8 compatible.
"""
import os
import sys
import time

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
# How `summarize` names the stages under `missing`: alone for a value that is
# not a list, with `[i]` for a stage that fails `stage_problems`.
STAGES_FIELD = "timing.stages"


def _is_count(value):
    """An int that is not a bool - `True` is an int to Python and a length to
    nobody."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_whole(value):
    """A count, or a float with no fractional part (`7.0`): the schema's
    `integer` admits one, as draft 2020-12 does, and no schema can refuse it -
    JSON gives `7.0` and `7` one value, and `ajv` reads both as `7`. So the
    Python check admits it too, and the summary sums it as the int it is."""
    return _is_count(value) or (isinstance(value, float) and value.is_integer())


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


# The spelling a stage's derived start is written in: whole seconds, UTC.
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def whole_ms(value):
    """A recorded length in whole milliseconds, or None for anything that is
    not a finite number of zero or more - a bool included."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value != value or value < 0 or value == float("inf"):
        return None
    return int(round(value))


def stamp_less(stamp, ms):
    """The whole second `ms` before `stamp`, or None when `stamp` will not read.
    Floored, so a start derived this way never reads as later than it was."""
    epoch = _usage_core.parse_ts(stamp)
    if epoch is None:
        return None
    return time.strftime(STAMP_FORMAT, time.gmtime(int(epoch - ms / 1000.0)))


def run_stages(run_id, started_at, duration_ms, selection_ms, where, kind="gate"):
    """`(stages, gaps)` for one recorded run: for a `gate` run the time it spent
    choosing what to run, ENDING where the run starts, then the run's own length
    under `kind`, starting there. Each stage carries `run_id` and a basis naming
    `where` the figure was read.

    A MISSING FIGURE IS A GAP, NEVER A STAGE: no readable start gives no stage at
    all (both are placed by it), no length gives no `kind` stage. A selection
    that was never timed is no gap - it is a run from before that figure, or one
    that measured none - and gives no selection stage."""
    if _usage_core.parse_ts(started_at) is None:
        return [], ["%s records no readable startedAt (%r)" % (where, started_at)]
    stages, gaps = [], []
    selection = whole_ms(selection_ms)
    if kind == "gate" and selection is not None:
        stages.append(make_stage(
            "selection", stamp_less(started_at, selection), selection,
            "selectionMs in %s, ending at its startedAt" % (where,),
            run_id=run_id))
    ms = whole_ms(duration_ms)
    if ms is not None:
        stages.append(make_stage(kind, started_at, ms,
                                 "durationMs in %s" % (where,), run_id=run_id))
    else:
        gaps.append("%s records no readable durationMs (%r)" % (where, duration_ms))
    return stages, gaps


def _stage_key(stage):
    return (stage.get("kind"), stage.get("runId")) if isinstance(stage, dict) \
        else None


def append_run_stages(task, stages):
    """The task's timing record with a run's `stages` appended, as a NEW dict,
    each ONCE: a stage whose kind and run id the record already holds is not
    added again, so a run recorded twice into one task is timed once. The
    stages already recorded are kept - the record of a run is replaced by the
    next run's, its stages are not. No first start is invented."""
    timing = dict(_timing_of(task) or {})
    kept = timing.get("stages")
    kept = list(kept) if isinstance(kept, list) else []
    seen = set(k for k in (_stage_key(s) for s in kept)
               if k is not None and k[1] is not None)
    for stage in stages or []:
        if _stage_key(stage) in seen:
            continue
        seen.add(_stage_key(stage))
        kept.append(stage)
    timing["stages"] = kept
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
    if not _is_whole(ms) or ms < 0:
        out.append("ms %r is not a non-negative integer" % (ms,))
    basis = stage.get("basis")
    if not (isinstance(basis, str) and basis.strip()):
        out.append("basis is missing - a length with no record it was read "
                   "from cannot be checked")
    if "round" in stage and not (_is_whole(stage["round"]) and stage["round"] >= 1):
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
            rows[kind] = {"ms": sum(int(s["ms"]) for s in mine), "stages": len(mine),
                          "basis": sorted(set(s["basis"] for s in mine))}
    return rows


def summarize(task):
    """Where a task's wall time went: per-kind totals, the window from
    `timing.firstStartedAt` to `completedAt`, and the part of the window no
    stage accounts for.

    `missing` names every source the figures needed and did not find - `timing`,
    `timing.firstStartedAt`, a `timing.stages` that is not a list, a
    `timing.stages[i]` that fails `stage_problems`, or `completedAt` - and while
    it names any, `windowMs`, `attributedMs` and `unattributedMs` are None
    rather than a number nobody measured. A completion before the first start
    is named the same way, as no window. When stages overlap and sum past the
    window, `unattributedMs` is 0 and `overrunMs` says by how much, so
    `attributedMs - overrunMs + unattributedMs` is the window either way.

    The window is first start to completion even across a reopen: the time the
    task sat closed is inside it, unattributed (the module docstring says
    why)."""
    timing = _timing_of(task)
    missing = []
    stages = []
    if timing is None:
        missing.append("timing")
    else:
        if _usage_core.parse_ts(timing.get("firstStartedAt")) is None:
            missing.append("timing.firstStartedAt")
        raw = timing.get("stages", [])
        if not isinstance(raw, list):
            missing.append(STAGES_FIELD)
            raw = []
        for i, stage in enumerate(raw):
            if stage_problems(stage):
                missing.append("%s[%d]" % (STAGES_FIELD, i))
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


def is_unreadable(summary):
    """Whether `summarize` withheld its figures because the record's stages
    could not be read - the list itself, or a stage in it - as against a
    record that is readable and simply has no window (no first start, no
    completion, a completion before the start). A reader prints the two
    differently: one is a record to repair, the other a window not yet
    there."""
    return any(m == STAGES_FIELD or m.startswith(STAGES_FIELD + "[")
               for m in (summary or {}).get("missing") or [])
