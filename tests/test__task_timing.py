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
import _json_schema                                # noqa: E402  (the repo's reader of the published schema)
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
          and list(T.KINDS) == ["writer", "proof", "gate", "selection", "base",
                                "reviewer", "commit", "wait"])
    # A proof stage (the red-first run) is a stage like any other: it passes
    # the validator, it lands in the per-kind totals, and the schema's enum
    # names it. Each half is asserted apart so a list that gained the word in
    # one place only cannot pass on the other's strength.
    pstage = _stage("proof", "2026-01-01T00:04:00Z", 90000,
                    basis="stamp-verification red")
    ptask = _timed_task()
    ptask["timing"]["stages"].append(pstage)
    psum = T.summarize(ptask)
    check("tt10c a stage of kind proof validates, KINDS and the schema's enum "
          "both hold it exactly once, and summarize totals it as its own kind "
          "beside the gate's (the gate total stays 150000): %r"
          % (psum["byKind"],),
          T.stage_problems(pstage) == []
          and list(T.KINDS).count("proof") == 1
          and _schema_kinds().count("proof") == 1
          and psum["missing"] == []
          and psum["byKind"]["proof"]["ms"] == 90000
          and psum["byKind"]["proof"]["stages"] == 1
          and psum["byKind"]["gate"]["ms"] == 150000)
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


def _unreadable_cases(check):
    """A record the summary cannot read is NAMED, and gives no figure.

    Every fixture keeps a valid first start and completion, so a summary that
    read past the unreadable part would still have a window to report - which
    is exactly the figure these cases say must not appear."""
    shapes = {"object": {"writer": {"ms": 1000}}, "string": "writer 1000"}
    for name, value in sorted(shapes.items()):
        task = _timed_task()
        task["timing"] = {"firstStartedAt": "2026-01-01T00:00:00Z",
                          "stages": value}
        s = T.summarize(task)
        check("tt14 a `stages` value that is not a list (%s) is named under "
              "missing as `timing.stages`, and the summary gives no window, no "
              "attributed and no unattributed figure - it is not read as a "
              "record of no stages, whose whole window would print as "
              "unattributed time: %r" % (name, s),
              s.get("missing") == ["timing.stages"]
              and s.get("windowMs") is None and s.get("attributedMs") is None
              and s.get("unattributedMs") is None
              and s.get("overrunMs") is None and s.get("byKind") == {}
              and T.is_unreadable(s))
    bad = _timed_task()
    bad["timing"]["stages"][1] = dict(bad["timing"]["stages"][1], ms=-5)
    sb = T.summarize(bad)
    check("tt15 a stage that fails its own check is named by its index under "
          "missing, and the summary gives no attributed or unattributed figure "
          "rather than summing the other stages: %r" % (sb,),
          sb.get("missing") == ["timing.stages[1]"]
          and sb.get("windowMs") is None and sb.get("attributedMs") is None
          and sb.get("unattributedMs") is None and T.is_unreadable(sb))
    back = _timed_task(completedAt="2025-12-31T23:59:00Z")
    sk = T.summarize(back)
    check("tt16 a completion BEFORE the first start is named as no window - a "
          "negative window is not a length - and it is not an unreadable "
          "record, which a reader prints differently: %r" % (sk,),
          sk.get("missing") == ["a window: completedAt precedes "
                                "timing.firstStartedAt"]
          and sk.get("windowMs") is None and sk.get("unattributedMs") is None
          and not T.is_unreadable(sk))
    check("tt17 SECOND DIRECTION: a readable record, and one lacking only its "
          "completion, are not unreadable - the case that fails if every "
          "summary naming something missing were read as unreadable",
          not T.is_unreadable(T.summarize(_timed_task()))
          and not T.is_unreadable(T.summarize(_timed_task(completedAt=None))))
    whole = _timed_task()
    whole["timing"]["stages"][0] = dict(whole["timing"]["stages"][0], ms=200000.0)
    sw = T.summarize(whole)
    check("tt18 an integral float length (`200000.0`) is the integer it equals, "
          "as the schema's `integer` and draft 2020-12 read it - no problem, "
          "and summed as an int - so a plan the schema passes is one the "
          "plugin passes: %r" % (sw,),
          T.stage_problems(whole["timing"]["stages"][0]) == []
          and sw.get("attributedMs") == 410000
          and type(sw.get("attributedMs")) is int
          and type((sw.get("byKind") or {}).get("writer", {}).get("ms")) is int
          and T.stage_problems(dict(whole["timing"]["stages"][0], ms=1.5))
          != [])


def _schema_findings(name, value):
    """`(findings, unread)` of `value` against `$defs/<name>`, by the repo's own
    reader of the published schema."""
    path = os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json")
    doc = _json_schema.load_document(path)
    return _json_schema.check_findings(doc["$defs"][name], value, doc, name)


def _schema_cases(check):
    """The schema refuses what the Python check refuses, so a plan an external
    validator passes is one the plugin passes.

    Each looseness is written as a value the Python check refuses, and the case
    asks both readers: the schema's answer alone could pass for a schema that
    refuses everything."""
    good = _stage("gate", "2026-01-01T00:03:20Z", 100000, run_id="r1")
    loose = {
        "runId empty": dict(good, runId=""),
        "runId blank": dict(good, runId="   "),
        "basis blank": dict(good, basis="   "),
        "startedAt not a stamp": dict(good, startedAt="yesterday"),
        "startedAt month 13": dict(good, startedAt="2026-13-01T00:00:00Z"),
    }
    verdicts = {}
    for name, stage in sorted(loose.items()):
        found, unread = _schema_findings("timingStage", stage)
        verdicts[name] = (bool(found), bool(T.stage_problems(stage)),
                          sorted(unread))
    check("tt19 each looseness the schema had is refused by it AND by the "
          "Python check, with nothing the schema reader left unread: %r"
          % (verdicts,),
          verdicts == dict((n, (True, True, [])) for n in loose))
    first, unread_first = _schema_findings(
        "timing", {"firstStartedAt": "not a stamp", "stages": []})
    check("tt20 ...and `firstStartedAt` carries the same stamp pattern: %r"
          % (first,),
          bool(first) and not unread_first
          and bool(T.timing_problems({"firstStartedAt": "not a stamp",
                                      "stages": []})))
    # The shapes the writers produce: the drive's own stamp format, a session
    # record's fractional stamp with an offset, the demo's, and a zero wait.
    written = [
        _stage("writer", "2026-11-18T04:17:24Z", 1200, round=1),
        _stage("gate", "2026-11-18T04:17:24.123456+00:00", 5000, run_id="R-1"),
        _stage("wait", "2026-11-18T04:17:24Z", 0,
               basis="hand-out stamped by the drive; under a second: 0"),
        _stage("selection", "2026-11-18 04:17:24+0100", 30, run_id="R-2"),
    ]
    taken = [_schema_findings("timingStage", s) for s in written]
    record = T.first_start({"timing": {"stages": written}}, "2026-11-18T04:17:24Z")
    rec_found, rec_unread = _schema_findings("timing", record)
    check("tt21 SECOND DIRECTION: every stage shape the writers produce passes "
          "the tightened schema and the Python check alike - the case that "
          "fails if a pattern refuses a stamp the drive writes: %r"
          % (([f for f, _u in taken], rec_found),),
          all(not f and not u for f, u in taken)
          and all(T.stage_problems(s) == [] for s in written)
          and not rec_found and not rec_unread
          and T.timing_problems(record) == [])
    ms_float, ms_unread = _schema_findings("timingStage", dict(good, ms=1.0))
    check("tt22 a length of `1.0` is one both readers ACCEPT, as the integer it "
          "equals - no schema can tell it from `1`, since JSON gives the two "
          "one value - and both refuse `1.5`: %r" % (ms_float,),
          not ms_float and not ms_unread
          and T.stage_problems(dict(good, ms=1.0)) == []
          and bool(_schema_findings("timingStage", dict(good, ms=1.5))[0])
          and bool(T.stage_problems(dict(good, ms=1.5))))


def _run_stage_cases(check):
    """The stages a recorded run appends to its task: built from that run's own
    figures, appended once, and kept when the next run replaces the record.

    THE FIGURES ARE CHOSEN SO NO TWO AGREE - a selection of 2300 ms ending at a
    start whose whole second is :04:10, and a length of 8125 ms - so a stage
    holding the other figure, or a selection read from the start rather than
    ending at it, reads as a different value rather than the same one."""
    where = "run R-1's record"
    stages, gaps = T.run_stages("R-1", "2026-11-18T04:04:10Z", 8125, 2300, where)
    by = dict((s.get("kind"), s) for s in stages)
    check("tt23 a run's stages are its selection, ENDING where the run starts, "
          "and its gate, starting there - each carrying the run's id, its own "
          "figure and a basis naming where the figure came from: %r"
          % ((stages, gaps),),
          gaps == [] and [s.get("kind") for s in stages] == ["selection", "gate"]
          and by["selection"]["ms"] == 2300
          and by["selection"]["startedAt"] == "2026-11-18T04:04:07Z"
          and by["gate"]["ms"] == 8125
          and by["gate"]["startedAt"] == "2026-11-18T04:04:10Z"
          and all(s.get("runId") == "R-1" and where in s.get("basis", "")
                  for s in stages)
          and all(T.stage_problems(s) == [] for s in stages))
    no_pick, _g = T.run_stages("R-2", "2026-11-18T04:04:10Z", 8125, None, where)
    no_len, len_gaps = T.run_stages("R-3", "2026-11-18T04:04:10Z", None, 2300,
                                    where)
    no_start, start_gaps = T.run_stages("R-4", None, 8125, 2300, where)
    check("tt24 a run that timed no selection gives the gate stage alone, a run "
          "with no length gives no gate stage and NAMES the gap, and one with no "
          "readable start gives no stage at all and names that - never a stage "
          "with a zero or a guessed start: %r"
          % ((no_pick, no_len, len_gaps, no_start, start_gaps),),
          [s["kind"] for s in no_pick] == ["gate"]
          and [s["kind"] for s in no_len] == ["selection"]
          and len(len_gaps) == 1 and "durationMs" in len_gaps[0]
          and no_start == [] and len(start_gaps) == 1
          and "startedAt" in start_gaps[0])

    task = {"id": "P0.4", "timing": {"firstStartedAt": "2026-11-18T04:00:00Z",
                                     "stages": [_stage("writer",
                                                       "2026-11-18T04:00:00Z",
                                                       1000, round=1)]}}
    before = copy.deepcopy(task)
    once = T.append_run_stages(task, stages)
    twice = T.append_run_stages(dict(task, timing=once), stages)
    check("tt25 append_run_stages adds a run's stages after the ones already "
          "there and adds them ONCE - a second call with the same run's stages "
          "leaves the record as the first call left it - and leaves the task "
          "it was handed untouched: %r" % ((once, twice),),
          once["stages"][0] == before["timing"]["stages"][0]
          and once["stages"][1:] == stages
          and twice == once and task == before
          and once["firstStartedAt"] == "2026-11-18T04:00:00Z")
    later, _g2 = T.run_stages("R-5", "2026-11-18T04:09:00Z", 4400, 120, where)
    kept = T.append_run_stages(dict(task, timing=once), later)
    ids = [(s.get("kind"), s.get("runId")) for s in kept["stages"]]
    check("tt26 THE STAGE SURVIVES THE RECORD'S REPLACEMENT: the next run's "
          "stages land beside the first run's, which keep their figures - the "
          "record names only the newest run, the timing keeps every one: %r"
          % (ids,),
          ids == [("writer", None), ("selection", "R-1"), ("gate", "R-1"),
                  ("selection", "R-5"), ("gate", "R-5")]
          and kept["stages"][2]["ms"] == 8125 and kept["stages"][4]["ms"] == 4400)
    fresh = T.append_run_stages({"id": "P0.5"}, later)
    check("tt27 ...and a task with no timing record starts one holding the run's "
          "stages, with no first start invented: %r" % (fresh,),
          fresh == {"stages": later})


def _selftest():
    def body(check):
        _cases(check)
        _unreadable_cases(check)
        _schema_cases(check)
        _run_stage_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__task_timing.py --selftest\n")
    raise SystemExit(2)
