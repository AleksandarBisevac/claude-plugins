#!/usr/bin/env python3
"""
The cases for `_task_timing.py` - the one home of a task's timing record.

Every writer that records a stage and every reader that prints one goes
through this module, so the suite asks it the questions a reader of the
figures would ask: do the parts add up to the window, and when a source is
missing, is that said rather than read as zero.

THE FIXTURE WINDOW IS NOT COVERED BY ITS STAGES ON PURPOSE. A summary that
dropped the remainder, or reported the window as the stage total, agrees with
the right answer only when the stages cover the whole window - so the fixture
leaves a gap of a size no stage has, and the remainder is asserted exactly.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT, to read the schema)
from _output import safe_stdio                     # noqa: E402
import _task_timing as T                           # noqa: E402


def _stage(kind, start, ms, basis="journal:fixture", **kw):
    return T.make_stage(kind, start, ms, basis, **kw)


def _timed_task(**kw):
    # The window is 600000 ms; the stages below cover 410000 of it, so the
    # remainder (190000) is a figure no single stage or partial sum equals.
    t = {"id": "P0.1", "title": "t", "status": "done",
         "startedAt": "2026-01-01T00:07:00Z",
         "completedAt": "2026-01-01T00:10:00Z",
         "timing": {"firstStartedAt": "2026-01-01T00:00:00Z", "stages": [
             _stage("writer", "2026-01-01T00:00:00Z", 200000, round=1),
             _stage("gate", "2026-01-01T00:03:20Z", 100000, run_id="r1"),
             _stage("gate", "2026-01-01T00:05:00Z", 50000, run_id="r2"),
             _stage("reviewer", "2026-01-01T00:08:00Z", 60000,
                    basis="result:reviewer")]}}
    t.update(kw)
    return t


def _schema_defs():
    path = os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["$defs"]


def _schema_kinds():
    return _schema_defs()["timingStage"]["properties"]["kind"]["enum"]


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the summary: parts add up to the window ---
    task = _timed_task()
    s = T.summarize(task)
    by = s.get("byKind") or {}
    parts = sum(v["ms"] for v in by.values()) + (s.get("unattributedMs") or 0)
    check("tt1 a summary of a task whose stages cover PART of its window gives "
          "per-kind totals, the window from timing.firstStartedAt to completedAt, "
          "and the remainder as unattributed - and the parts add up to the "
          "window: %r" % (s,),
          s.get("windowMs") == 600000
          and by.get("writer", {}).get("ms") == 200000
          and by.get("gate", {}).get("ms") == 150000
          and by.get("reviewer", {}).get("ms") == 60000
          and s.get("unattributedMs") == 190000
          and parts == s.get("windowMs")
          and s.get("missing") == [])
    check("tt2 ...and the window is read from firstStartedAt, not the restarted "
          "startedAt (which would give 180000), and each figure carries the "
          "record it was read from: %r" % (s,),
          s.get("windowMs") != 180000
          and "firstStartedAt" in (s.get("windowBasis") or "")
          and "completedAt" in (s.get("windowBasis") or "")
          and by.get("gate", {}).get("basis") == ["journal:fixture"]
          and by.get("reviewer", {}).get("basis") == ["result:reviewer"]
          and by.get("gate", {}).get("stages") == 2)
    check("tt3 SECOND-DIRECTION CASE: a kind no stage recorded is ABSENT from "
          "the per-kind totals rather than present at zero - a zero there would "
          "read as a stage that was measured and took no time: %r"
          % (sorted(by),), sorted(by) == ["gate", "reviewer", "writer"])

    # --- the summary: a missing source is named, and there is no total ---
    open_task = _timed_task(completedAt=None)
    so = T.summarize(open_task)
    check("tt4 a task with no completedAt: the summary names `completedAt` as "
          "missing and gives no window, no attributed total and no remainder: "
          "%r" % (so,),
          so.get("missing") == ["completedAt"] and so.get("windowMs") is None
          and so.get("unattributedMs") is None
          and so.get("attributedMs") is None)
    bare = {"id": "P0.2", "title": "t", "status": "done",
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T00:10:00Z"}
    sb = T.summarize(bare)
    check("tt5 a task with no timing at all: the summary names `timing` as "
          "missing and gives no total - startedAt is NOT taken in its place, "
          "since a restart re-stamps it: %r" % (sb,),
          "timing" in (sb.get("missing") or []) and sb.get("windowMs") is None
          and sb.get("unattributedMs") is None and sb.get("attributedMs") is None
          and not sb.get("byKind"))
    nofirst = _timed_task()
    nofirst["timing"] = {"stages": list(nofirst["timing"]["stages"])}
    sn = T.summarize(nofirst)
    check("tt6 ...and a timing record with no firstStartedAt names THAT field "
          "rather than reading the window from startedAt: %r" % (sn,),
          sn.get("missing") == ["timing.firstStartedAt"]
          and sn.get("windowMs") is None)
    check("tt7 SECOND-DIRECTION CASE: a complete record names nothing missing - "
          "the case that fails if `missing` is filled unconditionally: %r"
          % (s.get("missing"),), s.get("missing") == [])

    # --- a stage, and the validator's reading of one ---
    good = _stage("commit", "2026-01-01T00:09:00Z", 1200, round=2, run_id="x")
    check("tt8 make_stage builds the stage the schema describes, carrying round "
          "and runId only when given: %r" % (good,),
          good == {"kind": "commit", "startedAt": "2026-01-01T00:09:00Z",
                   "ms": 1200, "basis": "journal:fixture", "round": 2,
                   "runId": "x"}
          and sorted(_stage("wait", "2026-01-01T00:00:00Z", 0))
          == ["basis", "kind", "ms", "startedAt"])
    probs = {
        "kind": T.stage_problems(dict(good, kind="lunch")),
        "ms": T.stage_problems(dict(good, ms=-1)),
        "basis": T.stage_problems(dict((k, v) for k, v in good.items()
                                       if k != "basis")),
        "good": T.stage_problems(good),
    }
    check("tt9 stage_problems: an unknown kind, a negative ms and a missing "
          "basis are each ONE problem naming its field, and a well-formed stage "
          "has none: %r" % (probs,),
          len(probs["kind"]) == 1 and "kind" in probs["kind"][0]
          and len(probs["ms"]) == 1 and "ms" in probs["ms"][0]
          and len(probs["basis"]) == 1 and "basis" in probs["basis"][0]
          and probs["good"] == [])
    check("tt10 the closed list of kinds is the schema's enum, item for item - "
          "the validator and the schema read one list: module=%r schema=%r"
          % (list(T.KINDS), _schema_kinds()),
          list(T.KINDS) == _schema_kinds()
          and list(T.KINDS) == ["writer", "gate", "selection", "base",
                                "reviewer", "commit", "wait"])
    defs = _schema_defs()
    keys = {"timing": (sorted(T.TIMING_KEYS), sorted(defs["timing"]["properties"])),
            "stage": (sorted(T.STAGE_KEYS),
                      sorted(defs["timingStage"]["properties"]))}
    check("tt10b ...and so are the keys of the record and of a stage, the "
          "vocabulary the validator's unknown-key warning reads: %r" % (keys,),
          all(mine == theirs for mine, theirs in keys.values())
          and keys["stage"][0] == ["basis", "kind", "ms", "round", "runId",
                                   "startedAt"]
          and keys["timing"][0] == ["firstStartedAt", "stages"])

    # --- the writers: append, and the first start ---
    before = copy.deepcopy(task)
    extra = _stage("wait", "2026-01-01T00:09:30Z", 500)
    timing = T.append_stage(task, extra)
    check("tt11 append_stage returns the task's timing with the stage last and "
          "the first start kept, and leaves the task it was handed untouched: "
          "%r" % (timing,),
          timing["stages"][-1] == extra
          and len(timing["stages"]) == len(before["timing"]["stages"]) + 1
          and timing["firstStartedAt"] == "2026-01-01T00:00:00Z"
          and task == before)
    fresh = T.append_stage({"id": "P0.3"}, extra)
    check("tt12 ...and on a task with no record it starts one holding that "
          "stage alone, with no first start invented: %r" % (fresh,),
          fresh == {"stages": [extra]})
    kept = T.first_start(task, "2026-02-02T00:00:00Z")
    born = T.first_start({"id": "P0.3"}, "2026-02-02T00:00:00Z")
    check("tt13 first_start sets firstStartedAt once and never moves it: a "
          "record that has one keeps it, one that has none takes the start "
          "given: kept=%r born=%r" % (kept.get("firstStartedAt"), born),
          kept.get("firstStartedAt") == "2026-01-01T00:00:00Z"
          and kept.get("stages") == task["timing"]["stages"]
          and born == {"firstStartedAt": "2026-02-02T00:00:00Z", "stages": []})


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__task_timing.py --selftest\n")
    raise SystemExit(2)
