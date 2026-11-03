#!/usr/bin/env python3
"""
The cases for `tools/plan-window.py` - which phases of a plan the report leg's
window keeps, and what it narrows the plan's index lists to.

They run against a FIXTURE plan whose shape is fixed here, not against this
repository's live plan: the live plan's shape moves with every merged phase, so a
case over it could stay green with an arm deleted whenever the live plan happened
to hold nothing that arm exists for. Each phase below exists for exactly one arm,
and the comment on it says which, so a case that goes red names the arm that
broke.

`M` is the tool, loaded by path because it lives under `tools/`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import io
import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _output                                     # noqa: E402  (project_of_manifest)

M = _loader.load(os.path.join(_harness.TOOLS_DIR, "plan-window.py"),
                 modname="plan_window_under_test")


# --- the fixture ----------------------------------------------------------------
def _task(tid, status="done", **extra):
    out = {"id": tid, "title": "task %s" % (tid,), "status": status,
           "outcome": "landed", "dependsOn": [], "blockedBy": []}
    out.update(extra)
    return out


def _phase(pid, status, tasks, **extra):
    out = {"id": pid, "title": "phase %s" % (pid,), "status": status,
           "blockedBy": [], "tasks": tasks}
    out.update(extra)
    return out


def _shards():
    """One shard per phase, in plan order. What each is FOR:

      P1  the first done phase: brings the `done` statuses no open phase has
      P2  shaped exactly like P1, kept ONLY because P6.1 dependsOn P2.1 (one hop)
      P3  shaped like P1 plus a phase key no other phase carries
      P4  shaped like P1 except that its task's `outcome` is the object form, so
          only a NESTED key path (`outcome.filesTouched`) is new
      P5  shaped exactly like P1 and referenced by nothing: the phase to drop. A
          bug points at its task, a proposal became it, and the fileIndex names it
      P6  the one open phase
      P7  shaped like P1, kept ONLY because P2.1 dependsOn P7.1 (the second hop)
      P8  shaped like P1 in the manifest; its task's EVIDENCE reads a status and
          a flag no other subject does
    """
    return [
        _phase("P1", "done", [_task("P1.1")]),
        _phase("P2", "done", [_task("P2.1", dependsOn=["P7.1"])]),
        _phase("P3", "done", [_task("P3.1")], mergedHead="abc1234"),
        _phase("P4", "done", [_task("P4.1", outcome={
            "summary": "landed", "filesTouched": ["a.py"]})]),
        _phase("P5", "done", [_task("P5.1")]),
        _phase("P6", "in_progress", [_task("P6.1", "pending", dependsOn=["P2.1"]),
                                     _task("P6.2", "pending")]),
        _phase("P7", "done", [_task("P7.1")]),
        _phase("P8", "done", [_task("P8.1")]),
    ]


def _plan(shards):
    return {
        "meta": {"version": 2, "title": "window fixture", "repo": "r"},
        "phases": [{"id": s["id"], "title": s["title"], "status": s["status"],
                    "shard": "phases/%s.json" % (s["id"],)} for s in shards],
        "fileIndex": {"a.py": ["P5.1"], "b.py": ["P6.1", "P5.1"],
                      "c.py": ["P1.1"]},
        "bugs": [{"id": "BUG-1", "title": "on the dropped task", "taskId": "P5.1"},
                 {"id": "BUG-2", "title": "on a kept task", "taskId": "P6.1"},
                 {"id": "BUG-3", "title": "on no task"}],
        "proposals": [
            {"id": "PROP-1", "status": "materialized", "materializedAs": "P5"},
            {"id": "PROP-2", "status": "materialized", "materializedAs": "P3"},
            {"id": "PROP-3", "status": "parked", "materializedAs": None}],
        "deferred": [],
    }


def _view(key, flags=()):
    return {"key": key, "flags": [(f, f) for f in flags]}


def _reading(shards):
    """An evidence reading of the reader's shape: every task `passed`, the open
    phase's tasks `no-evidence`, and P8.1 alone `failed` with a flag."""
    tasks, phases = {}, {}
    for s in shards:
        phases[s["id"]] = {"own": _view("no-evidence")}
        for t in s["tasks"]:
            tasks[t["id"]] = (_view("no-evidence") if s["status"] != "done"
                              else _view("passed"))
    tasks["P8.1"] = _view("failed", ("stale",))
    return {"tasks": tasks, "phases": phases, "keys": [], "flags": [], "files": 1}


EXPECTED_KEEP = set(["P1", "P2", "P3", "P4", "P6", "P7", "P8"])


def _key_paths(obj, prefix=""):
    """Every key path under `obj`, a list's items read through `[]` - written here
    on its own rather than borrowed from the tool, so the shape-set comparison is
    two computations and not one compared with itself."""
    out = set()
    if isinstance(obj, dict):
        for k in obj:
            path = "%s.%s" % (prefix, k) if prefix else k
            out.add(path)
            out |= _key_paths(obj[k], path)
    elif isinstance(obj, list):
        for item in obj:
            out |= _key_paths(item, prefix + "[]")
    return out


def _manifest_shape(shards):
    out = set()
    for s in shards:
        out |= set(("phase", p) for p in _key_paths(
            dict((k, v) for k, v in s.items() if k != "tasks")))
        out.add(("phase-status", s["status"]))
        for t in s["tasks"]:
            out |= set(("task", p) for p in _key_paths(t))
            out.add(("task-status", t["status"]))
    return out


# --- the project on disk ----------------------------------------------------------
def _row(run_id, task_id, phase_id, status):
    return {"v": 1, "runId": run_id, "ts": "2026-08-01T09:00:00Z", "scope": "task",
            "taskId": task_id, "phaseId": phase_id, "status": status,
            "durationMs": 10, "failed": [] if status == "passed" else ["unit"],
            "steps": [{"name": "unit", "exit": 0 if status == "passed" else 1,
                       "ran": 3, "durationMs": 9, "command": "pytest"}],
            "observations": {"ranTotal": 3, "treeMutated": [], "treeBasis": "b",
                             "coverage": ["a.py"], "coverageBasis": "c"},
            "treeMutated": []}


def _write_json(path, data):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2))


def _write_project(root):
    """The fixture as a project: a record-shaped plan, its shards, a ledger whose
    runs three tasks point at - P8.1's the one failed run, the evidence word that
    is P8's reason to be kept - and the project config. Returns the plan's path."""
    shards = _shards()
    runs = {"P1": "passed", "P7": "passed", "P8": "failed"}
    for s in shards:
        if s["id"] in runs:
            s["tasks"][0]["testEvidence"] = {"runId": "R-%s" % (s["id"],),
                                             "status": runs[s["id"]],
                                             "at": "2026-08-01T09:00:00Z"}
    audit = os.path.join(root, "docs", "audit")
    for s in shards:
        _write_json(os.path.join(audit, "phases", "%s.json" % (s["id"],)), s)
    plan_path = os.path.join(audit, "audit-plan.json")
    _write_json(plan_path, _plan(shards))
    _write_json(os.path.join(root, ".claude", "audit.config.json"),
                {"manifestPath": "docs/audit/audit-plan.json"})
    ledger = os.path.join(audit, "evidence", "2026-08.t.jsonl")
    os.makedirs(os.path.dirname(ledger))
    with io.open(ledger, "w", encoding="utf-8") as fh:
        for pid in sorted(runs):
            row = _row("R-%s" % (pid,), "%s.1" % (pid,), pid, runs[pid])
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return plan_path


def _snapshot_dirs():
    return set(d for d in os.listdir(tempfile.gettempdir())
               if d.startswith(M.SNAPSHOT_PREFIX))


def _quiet(fn, *args):
    """(return value, stdout+stderr text) of `fn(*args)`."""
    buf = io.StringIO()
    out, err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        got = fn(*args)
    finally:
        sys.stdout, sys.stderr = out, err
    return got, buf.getvalue()


# --- cases --------------------------------------------------------------------
def _cases(check):
    shards = _shards()
    by_id = dict((s["id"], s) for s in shards)
    order = [s["id"] for s in shards]
    reading = _reading(shards)
    keep = M.select(order, by_id, reading)

    # --- pw: which phases the window keeps ------------------------------------
    check("pw1 the reference closure: a phase an open task's dependsOn points "
          "into is kept (P2, one hop), and so is the phase a KEPT task's "
          "dependsOn points into in turn (P7, the second hop): kept %r"
          % (sorted(keep),),
          "P2" in keep and "P7" in keep)
    check("pw2 the shape arm: a done phase carrying a phase key no other kept "
          "phase carries is kept (P3), and so is one whose task reads an "
          "evidence status and flag nothing else reads (P8): kept %r"
          % (sorted(keep),),
          "P3" in keep and "P8" in keep)
    check("pw3 the nested-key arm: a done phase whose only new shape is a key "
          "path BELOW a task key (outcome.filesTouched, the object form of "
          "outcome) is kept (P4): kept %r" % (sorted(keep),),
          "P4" in keep)
    # THE OVER-FIRE TWIN of the three above: an arm that keeps too much - every
    # done phase, or a fixed count of recent ones - passes them all. P5 is a
    # recent done phase with nothing new and nothing pointing at it.
    check("pw4 ...and nothing else: the done phase with no new shape and no "
          "reference into it is dropped, the kept set being exactly %r: kept %r"
          % (sorted(EXPECTED_KEEP), sorted(keep)),
          keep == EXPECTED_KEEP)
    check("pw5 the references a shard makes are its own blockedBy and its tasks' "
          "dependsOn and blockedBy, read as the phases owning them; an id no "
          "phase owns stays as written: %r"
          % (sorted(M.references(
              _phase("PX", "pending", [_task("PX.1", "pending", dependsOn=["P1.1"],
                                             blockedBy=["P3.1", "GONE.1"])],
                     blockedBy=["P4"]),
              {"P1.1": "P1", "P3.1": "P3"})),),
          M.references(
              _phase("PX", "pending", [_task("PX.1", "pending", dependsOn=["P1.1"],
                                             blockedBy=["P3.1", "GONE.1"])],
                     blockedBy=["P4"]),
              {"P1.1": "P1", "P3.1": "P3"}) == set(["P1", "P3", "P4", "GONE.1"]))

    # --- pw: the shape the window keeps is the plan's ---------------------------
    kept_shape = _manifest_shape([by_id[p] for p in order if p in keep])
    all_shape = _manifest_shape(shards)
    check("pw6 shape-set equality, nested keys included: every key path and "
          "status the whole plan's shards use is used by a kept shard, read by a "
          "walk written in this suite; missing %r"
          % (sorted(all_shape - kept_shape),),
          kept_shape == all_shape
          and ("task", "outcome.filesTouched") in all_shape
          and ("phase", "mergedHead") in all_shape)
    falsified = _task("PF.1", tests={"falsifiers": {
        "a sentence naming one test": {"command": "x"},
        "another sentence naming another": {"command": "y"}}})
    got = M.shape(_phase("PF", "done", [falsified]), None)
    check("pw7 a dict keyed by DATA (any key that is not a name) is read as one "
          "map, so two texts give one path and not two - otherwise every phase "
          "carrying one would read as new: %r"
          % (sorted(p for p in got if "falsifiers" in str(p)),),
          ("task", "tests.falsifiers.{}") in got
          and ("task", "tests.falsifiers.{}.command") in got
          and not [p for p in got if "sentence" in str(p)])

    # --- pw: the index lists narrowed to what was kept --------------------------
    plan = _plan(shards)
    before = copy.deepcopy(plan)
    narrowed = M.narrow(plan, by_id, keep)
    check("pw8 the proposal filter: a proposal that became a DROPPED phase goes, "
          "one that became a kept phase and one that became none stay: %r"
          % ([x["id"] for x in narrowed["proposals"]],),
          [x["id"] for x in narrowed["proposals"]] == ["PROP-2", "PROP-3"])
    check("pw9 the bug filter: a bug on a dropped task goes, a bug on a kept task "
          "and a bug on no task stay: %r" % ([b["id"] for b in narrowed["bugs"]],),
          [b["id"] for b in narrowed["bugs"]] == ["BUG-2", "BUG-3"])
    check("pw10 the fileIndex keeps only kept tasks, and a file naming none "
          "goes; the phase list is the kept phases in plan order: %r %r"
          % (narrowed["fileIndex"], [p["id"] for p in narrowed["phases"]]),
          narrowed["fileIndex"] == {"b.py": ["P6.1"], "c.py": ["P1.1"]}
          and [p["id"] for p in narrowed["phases"]]
          == [p for p in order if p in keep])
    check("pw11 narrowing returns a new plan and leaves the one it was handed "
          "as it was", plan == before and narrowed is not plan)

    # --- pw: the comparison of the two readings ---------------------------------
    same = M.disagreements(reading, copy.deepcopy(reading))
    moved = copy.deepcopy(reading)
    moved["tasks"]["P1.1"] = _view("dangling")
    lost = M.disagreements(reading, moved)
    chips = copy.deepcopy(reading)
    chips["keys"] = ["passed"]
    extra = copy.deepcopy(reading)
    extra["tasks"]["PZ.1"] = _view("passed")
    check("pw12 two readings that agree give no disagreement (the over-fire "
          "twin of the cases after it): %r" % (same,), same == [])
    check("pw13 a subject reading another status in the window is named, with "
          "both readings: %r" % (lost,),
          len(lost) == 1 and "P1.1" in lost[0] and "dangling" in lost[0])
    check("pw14 a reading present on one side only, different chip sets, and a "
          "subject the full plan does not have are each a disagreement: "
          "%r %r %r" % (M.disagreements(reading, None),
                        M.disagreements(reading, chips),
                        M.disagreements(reading, extra)),
          len(M.disagreements(reading, None)) == 1
          and len(M.disagreements(None, reading)) == 1
          and M.disagreements(None, None) == []
          and len(M.disagreements(reading, chips)) == 1
          and len(M.disagreements(reading, extra)) == 1)

    # --- pw: the window on disk ---------------------------------------------------
    tmp = _harness.fixture_root("plan-window-selftest-")
    try:
        src_plan = _write_project(os.path.join(tmp, "proj"))
        dst = os.path.join(tmp, "window")
        snaps_before = _snapshot_dirs()
        code, text = _quiet(M.main, [src_plan, dst])
        snaps_left = _snapshot_dirs() - snaps_before
        window_plan = os.path.join(dst, "docs", "audit", "audit-plan.json")
        written = os.path.isfile(window_plan)
        shards_there = sorted(f[:-5] for f in os.listdir(
            os.path.join(dst, "docs", "audit", "phases"))) if written else []
        check("pw15 the tool writes the window at the plan's own record-shaped "
              "path, whose project is the window itself, with the kept shards "
              "and not the dropped one, and exits 0: code=%r project=%r "
              "shards=%r out=%r"
              % (code, written and _output.project_of_manifest(window_plan),
                 shards_there, text[-800:]),
              code == 0 and written
              and os.path.realpath(_output.project_of_manifest(window_plan))
              == os.path.realpath(dst)
              and shards_there == sorted(EXPECTED_KEEP))
        full = M.evidence(src_plan)
        window = M.evidence(window_plan) if written else None
        resolved = sorted(set(v["key"] for v in ((window or {}).get("tasks")
                                                  or {}).values()))
        # THE FIXTURE-VALUE CASE: two readings that both found no ledger agree
        # perfectly, so the window's reading must have resolved a recorded run.
        check("pw16 the window's evidence reads as the plan's, and it resolved "
              "the runs the tasks point at: keys %r, disagreements %r"
              % (resolved, M.disagreements(full, window)),
              window is not None and "passed" in resolved
              and "dangling" not in resolved
              and M.disagreements(full, window) == [])
        if written:
            shutil.rmtree(os.path.join(dst, "docs", "audit", "evidence"))
        cut = M.evidence(window_plan) if written else None
        refused = M.disagreements(full, cut)
        check("pw17 a window whose ledger is missing reads its pointers as "
              "dangling, and the comparison names them: %r" % (refused[:4],),
              written and refused != []
              and any("dangling" in line for line in refused))

        # BOTH READINGS FROM ONE SNAPSHOT. Built from the snapshot after the
        # source tree is gone, the window can only have read the snapshot - a
        # reading taken from the live plan at a second moment would find nothing.
        snap_root = os.path.join(tmp, "snap")
        snap_plan = M.snapshot(src_plan, snap_root)
        shutil.rmtree(os.path.join(tmp, "proj"))
        dst2 = os.path.join(tmp, "window-2")
        (built, btext) = _quiet(M.build, snap_plan, dst2)
        check("pw18 both readings come from one snapshot: with the source tree "
              "removed after it was taken, the window still builds, keeps what "
              "the plan's window keeps, and its reading agrees with the "
              "snapshot's: kept %r, disagreements %r, out %r"
              % (built and sorted(built["keep"]),
                 built and built["drift"], btext[-600:]),
              built is not None and built["keep"] == EXPECTED_KEEP
              and built["drift"] == [] and built["window"] is not None)
        # Measured as the snapshot directories that appeared ACROSS the run, so
        # a stale one some other process left cannot fail this and a real leak
        # cannot hide behind one.
        check("pw19 the snapshot the tool takes for itself is removed when it "
              "ends: %r" % (sorted(snaps_left),), snaps_left == set())
        # ...and the command takes that path itself: every reading `main` asks for
        # is of a plan outside the source tree, one of them the window's.
        src3 = _write_project(os.path.join(tmp, "proj-3"))
        dst3 = os.path.join(tmp, "window-3")
        asked = []
        real = M.evidence
        M.evidence = lambda path: asked.append(os.path.abspath(path)) or real(path)
        try:
            code3, text3 = _quiet(M.main, [src3, dst3])
        finally:
            M.evidence = real
        source = os.path.abspath(os.path.join(tmp, "proj-3")) + os.sep
        window3 = os.path.abspath(os.path.join(dst3, "docs", "audit",
                                               "audit-plan.json"))
        check("pw21 the command reads both evidence readings from its snapshot "
              "and its window, never from the source tree: code=%r asked=%r"
              % (code3, asked),
              code3 == 0 and len(asked) == 2 and window3 in asked
              and not [a for a in asked if a.startswith(source)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    code, text = _quiet(M.main, [])
    check("pw20 no arguments is a usage error, said on stderr: code=%r" % (code,),
          code == 2 and "usage" in text)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_plan_window.py --selftest\n")
    raise SystemExit(2)
