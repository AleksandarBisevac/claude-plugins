#!/usr/bin/env python3
"""
The cases for `_manifest_merge.py` - the record-level three-way merge.

Every fixture is the smallest document that tells a record merge from a line merge:
two branches that each append a DIFFERENT record at the same tail. A line merge
conflicts on every one of them; the cases below say which of them a record merge may
resolve and which it must still hand to a human.

`M` is the module under test. Fixtures are built fresh per case, because `merge3`
must never mutate its inputs and a shared fixture would hide it if it did.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _manifest_merge as M                        # noqa: E402


# --- fixtures -----------------------------------------------------------------
def _task(tid, status="pending", files=None):
    return {"id": tid, "title": "t " + tid, "status": status, "files": files or []}


def _base():
    """A plan whose phases end at BF10 - the reporter's shape, shrunk."""
    return {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "one", "status": "in_progress",
             "tasks": [_task("P1.1", files=["src/a.ts"])]},
            {"id": "BF10", "title": "ten", "status": "pending",
             "tasks": [_task("BF10.1", files=["src/b.ts"])]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["BF10.1"]},
        "bugs": [{"id": "BUG-1", "title": "b1", "status": "open"}],
    }


def _with_phase(doc, pid, files):
    d = copy.deepcopy(doc)
    d["phases"].append({"id": pid, "title": "phase " + pid, "status": "pending",
                        "tasks": [_task(pid + ".1", files=files)]})
    for f in files:
        d["fileIndex"].setdefault(f, []).append(pid + ".1")
    return d


def _phase(doc, pid):
    return [p for p in doc["phases"] if p["id"] == pid][0]


def _dump(obj):
    return _mio.json_document(obj)


def _pick(text, side):
    """Resolve every marker block in `text` by keeping one side, as a human would."""
    out, mode = [], None
    for line in text.split("\n"):
        if line.startswith("<<<<<<< "):
            mode = "ours"
            continue
        if line == "=======" and mode:
            mode = "theirs"
            continue
        if line.startswith(">>>>>>> ") and mode:
            mode = None
            continue
        if mode is None or mode == side:
            out.append(line)
    return "\n".join(out)


# --- cases --------------------------------------------------------------------
def _cases(check):
    # mg1 - the report's own example: ours adds BF12, theirs adds BF11.
    b = _base()
    o = _with_phase(b, "BF12", ["src/c.ts"])
    t = _with_phase(b, "BF11", ["src/d.ts"])
    before = (_dump(b), _dump(o), _dump(t))
    r = M.merge3(b, o, t)
    check("mg1 two branches that each append a different phase merge with no conflict",
          r["conflicts"] == [], r["conflicts"])
    ids = [p["id"] for p in r["doc"]["phases"]]
    check("mg2 ...both phases survive, after the base's own, in natural id order "
          "(BF11 before BF12, whichever side added which)",
          ids == ["P1", "BF10", "BF11", "BF12"], ids)
    check("mg3 ...both new fileIndex rows survive",
          r["doc"]["fileIndex"].get("src/c.ts") == ["BF12.1"]
          and r["doc"]["fileIndex"].get("src/d.ts") == ["BF11.1"], r["doc"]["fileIndex"])
    check("mg4 ...and merge3 mutates none of its three inputs",
          (_dump(b), _dump(o), _dump(t)) == before)
    r_rev = M.merge3(b, t, o)
    check("mg5 SYMMETRY: merging in the other direction yields byte-identical output, "
          "because phase order is execution order",
          _dump(r_rev["doc"]) == _dump(r["doc"]), _dump(r_rev["doc"]))
    check("mg6 ...and the report counts one record contributed by each side",
          r["counts"] == {"ours": 1, "theirs": 1}, r["counts"])

    # mg7 - two bugs appended at one tail.
    b = _base()
    o = copy.deepcopy(b)
    o["bugs"].append({"id": "BUG-2", "title": "b2", "status": "open"})
    t = copy.deepcopy(b)
    t["bugs"].append({"id": "BUG-3", "title": "b3", "status": "open"})
    r = M.merge3(b, o, t)
    check("mg7 two different bugs appended on two branches both survive, no conflict",
          r["conflicts"] == [] and [x["id"] for x in r["doc"]["bugs"]]
          == ["BUG-1", "BUG-2", "BUG-3"], r)

    # mg8 - one file's fileIndex row grows a task on each side.
    b = _base()
    o = copy.deepcopy(b)
    o["fileIndex"]["src/a.ts"].append("P1.2")
    t = copy.deepcopy(b)
    t["fileIndex"]["src/a.ts"].append("BF10.2")
    r = M.merge3(b, o, t)
    check("mg8 a fileIndex row extended on both sides is a set union, not a conflict",
          r["conflicts"] == [] and sorted(r["doc"]["fileIndex"]["src/a.ts"])
          == ["BF10.2", "P1.1", "P1.2"], r)
    check("mg9 ...in the same order from either direction",
          M.merge3(b, t, o)["doc"]["fileIndex"]["src/a.ts"]
          == r["doc"]["fileIndex"]["src/a.ts"])

    # mg10 - a fileIndex removal on one side is honoured while the other adds.
    o = copy.deepcopy(b)
    o["fileIndex"]["src/a.ts"] = []
    r = M.merge3(b, o, t)
    check("mg10 a task id removed from a row on one side stays removed while the other "
          "side adds a different one",
          r["conflicts"] == [] and r["doc"]["fileIndex"]["src/a.ts"] == ["BF10.2"], r)

    # mg11 - SECOND DIRECTION of the fileIndex exception: any other list of plain
    #        values changed on both sides is still a conflict.
    b = _base()
    o = copy.deepcopy(b)
    _phase(o, "P1")["tasks"][0]["files"].append("src/x.ts")
    t = copy.deepcopy(b)
    _phase(t, "P1")["tasks"][0]["files"].append("src/y.ts")
    r = M.merge3(b, o, t)
    check("mg11 a task's own `files` changed on both sides is a CONFLICT - the set "
          "rule is fileIndex's alone",
          len(r["conflicts"]) == 1
          and r["conflicts"][0]["path"] == "phases[P1].tasks[P1.1].files", r["conflicts"])

    # mg12 - the same field of one record changed two ways.
    b = _base()
    o = copy.deepcopy(b)
    _phase(o, "P1")["tasks"][0]["status"] = "done"
    t = copy.deepcopy(b)
    _phase(t, "P1")["tasks"][0]["status"] = "blocked"
    r = M.merge3(b, o, t)
    check("mg12 one field of one task changed to two values is a conflict naming the "
          "record by id, not by position",
          [c["path"] for c in r["conflicts"]] == ["phases[P1].tasks[P1.1].status"],
          r["conflicts"])

    # mg13 - different fields of one record: both kept.
    t = copy.deepcopy(b)
    _phase(t, "P1")["tasks"][0]["title"] = "renamed"
    r = M.merge3(b, o, t)
    check("mg13 two different fields of the same task changed on the two sides both land",
          r["conflicts"] == [] and _phase(r["doc"], "P1")["tasks"][0]["status"] == "done"
          and _phase(r["doc"], "P1")["tasks"][0]["title"] == "renamed", r)

    # mg14 - one id minted twice.
    b = _base()
    o = copy.deepcopy(b)
    o["bugs"].append({"id": "BUG-2", "title": "ours", "status": "open"})
    t = copy.deepcopy(b)
    t["bugs"].append({"id": "BUG-2", "title": "theirs", "status": "open"})
    r = M.merge3(b, o, t)
    check("mg14 the same id ADDED on both sides with different content is a conflict "
          "that says so, never a silent pick or a renumber",
          len(r["conflicts"]) == 1 and r["conflicts"][0]["path"] == "bugs[BUG-2]"
          and "added on both sides" in r["conflicts"][0]["reason"], r["conflicts"])

    # mg15 - the same id added identically on both sides is one record.
    t = copy.deepcopy(o)
    r = M.merge3(b, o, t)
    check("mg15 the same record added identically on both sides appears once",
          r["conflicts"] == [] and [x["id"] for x in r["doc"]["bugs"]]
          == ["BUG-1", "BUG-2"], r)

    # mg16 - delete vs modify.
    b = _base()
    o = copy.deepcopy(b)
    o["bugs"] = []
    t = copy.deepcopy(b)
    t["bugs"][0]["status"] = "fixed"
    r = M.merge3(b, o, t)
    check("mg16 a record deleted on one side and changed on the other is a conflict",
          [c["path"] for c in r["conflicts"]] == ["bugs[BUG-1]"]
          and "deleted" in r["conflicts"][0]["reason"], r["conflicts"])

    # mg17 - a delete against an untouched other side lands.
    t = copy.deepcopy(b)
    t["phases"].append({"id": "P9", "title": "nine", "tasks": []})
    r = M.merge3(b, o, t)
    check("mg17 a record deleted on one side and untouched on the other is deleted",
          r["conflicts"] == [] and r["doc"]["bugs"] == []
          and [p["id"] for p in r["doc"]["phases"]][-1] == "P9", r)

    # mg18 - null is a value, not an absence. Theirs changes ANOTHER field of the
    #        same object, so the merge has to descend into it: had only ours
    #        touched `meta`, ours' whole object would be taken and a merge that
    #        dropped nulls would still pass.
    b = _base()
    b["meta"]["owner"] = "x"
    o = copy.deepcopy(b)
    o["meta"]["owner"] = None
    t = copy.deepcopy(b)
    t["meta"]["repo"] = "renamed"
    r = M.merge3(b, o, t)
    check("mg18 a field set to null on one side stays present as null while the other "
          "side changes a sibling field",
          r["conflicts"] == [] and "owner" in r["doc"]["meta"]
          and r["doc"]["meta"]["owner"] is None
          and r["doc"]["meta"]["repo"] == "renamed", r["doc"]["meta"])

    # mg19 - a reorder by one side is kept; by both, differently, is a conflict.
    b = _base()
    b["phases"].append({"id": "P3", "title": "three", "tasks": []})
    o = copy.deepcopy(b)
    o["phases"] = [o["phases"][2], o["phases"][0], o["phases"][1]]
    t = _with_phase(b, "P4", [])
    r = M.merge3(b, o, t)
    check("mg19 a reorder made on one side is kept while the other side appends",
          r["conflicts"] == [] and [p["id"] for p in r["doc"]["phases"]]
          == ["P3", "P1", "BF10", "P4"], [p["id"] for p in r["doc"]["phases"]])
    t = copy.deepcopy(b)
    t["phases"] = [t["phases"][1], t["phases"][0], t["phases"][2]]
    r = M.merge3(b, o, t)
    check("mg20 two different reorders of the same records are a conflict",
          [c["path"] for c in r["conflicts"]] == ["phases"], r["conflicts"])

    # mg21 - rendering: a clean merge is exactly the serialiser's text.
    b = _base()
    o = _with_phase(b, "BF12", ["src/c.ts"])
    t = _with_phase(b, "BF11", ["src/d.ts"])
    r = M.merge3(b, o, t)
    check("mg21 a clean merge renders to exactly the plugin's one serialisation",
          M.render(r, _dump) == _dump(r["doc"]))

    # mg22 - rendering a conflict: markers only around the disagreeing value, and
    #        choosing either side leaves valid JSON holding that side's value.
    b = _with_phase(_base(), "BF11", ["src/d.ts"])
    o = copy.deepcopy(b)
    _phase(o, "P1")["tasks"][0]["status"] = "done"
    o = _with_phase(o, "BF12", ["src/c.ts"])
    t = copy.deepcopy(b)
    _phase(t, "P1")["tasks"][0]["status"] = "blocked"
    t["bugs"].append({"id": "BUG-9", "title": "b9"})
    r = M.merge3(b, o, t)
    text = M.render(r, _dump)
    check("mg22 a conflicted merge carries exactly ONE marker block, for the one record "
          "that disagrees, while both sides' appends are already merged",
          text.count("<<<<<<< ") == 1 and text.count(">>>>>>> ") == 1
          and '"id": "BF12"' in text and '"id": "BUG-9"' in text, text)
    try:
        po = json.loads(_pick(text, "ours"))
        pt = json.loads(_pick(text, "theirs"))
        ok = (_phase(po, "P1")["tasks"][0]["status"] == "done"
              and _phase(pt, "P1")["tasks"][0]["status"] == "blocked")
    except ValueError as exc:
        ok = exc
    check("mg23 ...and keeping either side of the block parses and holds that side's "
          "value", ok is True, ok)

    # mg24 - rendering a delete-vs-modify: the deleted side's block is empty, and
    #        keeping it removes the record while leaving valid JSON.
    b = _base()
    b["bugs"].append({"id": "BUG-2", "title": "b2"})
    o = copy.deepcopy(b)
    o["bugs"] = o["bugs"][1:]
    t = copy.deepcopy(b)
    t["bugs"][0]["status"] = "fixed"
    text = M.render(M.merge3(b, o, t), _dump)
    try:
        ok = [x["id"] for x in json.loads(_pick(text, "ours"))["bugs"]] == ["BUG-2"] \
            and json.loads(_pick(text, "theirs"))["bugs"][0]["status"] == "fixed"
    except (ValueError, TypeError, KeyError) as exc:
        ok = exc
    check("mg24 a delete-vs-modify block keeps valid JSON whichever side is kept",
          ok is True, "%s\n%s" % (ok, text))

    # mg25 - a sharded shard is a phase object: its tasks list merges by id too.
    b = {"id": "P7", "title": "seven", "tasks": [_task("P7.1")]}
    o = copy.deepcopy(b)
    o["tasks"].append(_task("P7.2"))
    t = copy.deepcopy(b)
    t["tasks"][0]["status"] = "done"
    r = M.merge3(b, o, t)
    check("mg25 a shard (one phase) merges a task added on one side with a status "
          "change on the other",
          r["conflicts"] == [] and [x["id"] for x in r["doc"]["tasks"]] == ["P7.1", "P7.2"]
          and r["doc"]["tasks"][0]["status"] == "done", r)

    # mg27 - a delete-vs-modify on the LAST record: the sibling before it carries
    #        the comma, so keeping the delete must not leave it dangling.
    b = {"bugs": [{"id": "BUG-1", "status": "open"}, {"id": "BUG-2", "status": "open"}]}
    o = {"bugs": [{"id": "BUG-1", "status": "open"}]}
    t = {"bugs": [{"id": "BUG-1", "status": "open"}, {"id": "BUG-2", "status": "fixed"}]}
    text = M.render(M.merge3(b, o, t), _dump)
    try:
        ok = (json.loads(_pick(text, "ours")) == o
              and json.loads(_pick(text, "theirs")) == t)
    except ValueError as exc:
        ok = exc
    check("mg27 a delete-vs-modify on the LAST record of a list still leaves valid JSON "
          "whichever side is kept", ok is True, "%s\n%s" % (ok, text))

    # mg28 - the same too for two consecutive conflicts at the tail, one of them a
    #        delete: the comma before them belongs to neither block alone.
    b = {"bugs": [{"id": "BUG-1", "t": "a"}, {"id": "BUG-2", "t": "b"},
                  {"id": "BUG-3", "t": "c"}]}
    o = {"bugs": [{"id": "BUG-1", "t": "a"}, {"id": "BUG-2", "t": "ours"}]}
    t = {"bugs": [{"id": "BUG-1", "t": "a"}, {"id": "BUG-2", "t": "theirs"},
                  {"id": "BUG-3", "t": "changed"}]}
    text = M.render(M.merge3(b, o, t), _dump)
    try:
        ok = (json.loads(_pick(text, "ours")) == o
              and json.loads(_pick(text, "theirs")) == t)
    except ValueError as exc:
        ok = exc
    check("mg28 two adjacent conflicts at a list's tail, one a delete, still resolve to "
          "valid JSON either way", ok is True, "%s\n%s" % (ok, text))

    # mg29 - a fileIndex row that did not exist in the base, created on both sides.
    b = _base()
    o = copy.deepcopy(b)
    o["fileIndex"]["src/new.ts"] = ["P1.2"]
    t = copy.deepcopy(b)
    t["fileIndex"]["src/new.ts"] = ["BF10.2"]
    r = M.merge3(b, o, t)
    check("mg29 a NEW fileIndex row created on both sides is a union, like a row that "
          "already existed - two branches first touching one file is the common case",
          r["conflicts"] == [] and sorted(r["doc"]["fileIndex"]["src/new.ts"])
          == ["BF10.2", "P1.2"], r["conflicts"])

    # mg30 - a new object field added on both sides merges field by field; a real
    #        disagreement inside it is still a conflict on that field alone.
    b = _base()
    o = copy.deepcopy(b)
    _phase(o, "P1")["review"] = {"verdict": "pass", "by": "ours"}
    t = copy.deepcopy(b)
    _phase(t, "P1")["review"] = {"verdict": "pass", "notes": "theirs"}
    r = M.merge3(b, o, t)
    check("mg30 an object added on both sides merges by field, with no base to compare",
          r["conflicts"] == [] and _phase(r["doc"], "P1")["review"]
          == {"verdict": "pass", "by": "ours", "notes": "theirs"}, r)
    t = copy.deepcopy(b)
    _phase(t, "P1")["review"] = {"verdict": "fail"}
    r = M.merge3(b, o, t)
    check("mg31 ...and a field inside it set two ways is a conflict on that field alone",
          [c["path"] for c in r["conflicts"]] == ["phases[P1].review.verdict"],
          r["conflicts"])

    # mg32 - a delete-vs-modify on an object KEY rather than a list record: keeping
    #        the delete must drop the key, not leave it holding null.
    b = {"meta": {"version": 2, "owner": "x", "zeta": 1}}
    o = {"meta": {"version": 2, "zeta": 1}}
    t = {"meta": {"version": 2, "owner": "y", "zeta": 1}}
    text = M.render(M.merge3(b, o, t), _dump)
    try:
        ok = (json.loads(_pick(text, "ours")) == o
              and json.loads(_pick(text, "theirs")) == t)
    except ValueError as exc:
        ok = exc
    check("mg32 a key deleted on one side and changed on the other resolves to exactly "
          "either side's object - the kept delete leaves no key behind",
          ok is True, "%s\n%s" % (ok, text))

    # mg26 - natural order is numeric.
    check("mg26 natural order puts P9 before P10 and BUG-2 before BUG-12",
          sorted(["P10", "P9", "BUG-12", "BUG-2"], key=M.natural_key)
          == ["BUG-2", "BUG-12", "P9", "P10"])
    _whole_value_cases(check)
    _newest_cases(check)
    _schema_table_cases(check)
    _co_write_cases(check)


# --- a value that means "the newest one" ----------------------------------------
# The plan's full-run record and its newest measured run: a pre-push full gate and
# a full review record on every branch, so both sides changing them is ordinary
# work. Each is the later side's value whole, by its own `at`, and a conflict only
# when the moments do not order the two.
def _full_runs(full, measured):
    doc = _base()
    if full is not None:
        doc["meta"]["lastFullRun"] = full
    if measured is not None:
        doc["meta"]["lastMeasuredFullRun"] = measured
    return doc


def _held(rid, at):
    return {"runId": rid, "at": at, "head": "a" * 40, "status": "passed",
            "entries": ["sweep"], "digest": "sha256:" + "0" * 64}


def _newest_cases(check):
    g0 = _run("G0", "passed", "2026-11-20T09:00:00Z", 100)
    h0 = _held("G0", g0["at"])
    red_early = _run("R1", "failed", "2026-11-20T10:00:00Z", 200)
    red_late = _run("R3", "failed", "2026-11-20T12:00:00Z", 300)
    green = _run("G2", "passed", "2026-11-20T11:00:00Z", 400)
    h2 = _held("G2", green["at"])
    b = _full_runs(g0, h0)

    def meta(r):
        return (r["doc"]["meta"].get("lastFullRun"),
                r["doc"]["meta"].get("lastMeasuredFullRun"))

    def both_ways(o, t):
        r, rev = M.merge3(b, o, t), M.merge3(b, t, o)
        return r, _dump(r["doc"]) == _dump(rev["doc"]) and rev["conflicts"] == []

    # A green base; a red on one branch, a later green (measured) on the other.
    r, sym = both_ways(_full_runs(red_early, h0), _full_runs(green, h2))
    check("nw1 a green full run on the base, a red on one branch and a later measured "
          "green on the other merge with no conflict: the newest full run is the green, "
          "and so is the newest measured run - each the later side's value whole, the "
          "same in either direction",
          r["conflicts"] == [] and meta(r) == (green, h2) and sym, (r["conflicts"], meta(r)))
    # ...and the red the later one: each key is its own newest, from its own side.
    r, sym = both_ways(_full_runs(red_late, h0), _full_runs(green, h2))
    check("nw2 ...and when the red is the later run, the newest full run is that red "
          "while the newest measured run is still the other branch's green - each key "
          "the newest of its own meaning, never one side's pair imposed on the other",
          r["conflicts"] == [] and meta(r) == (red_late, h2) and sym,
          (r["conflicts"], meta(r)))
    # Two reds on a green base: the later red, and the base's measured run kept.
    r, sym = both_ways(_full_runs(red_early, h0), _full_runs(red_late, h0))
    check("nw3 a red on each branch over a green base is the later red, with the "
          "base's measured run, which neither red replaced",
          r["conflicts"] == [] and meta(r) == (red_late, h0) and sym,
          (r["conflicts"], meta(r)))
    # Two measured greens: the later of each.
    g4 = _run("G4", "passed", "2026-11-20T13:00:00Z", 500)
    h4 = _held("G4", g4["at"])
    r, sym = both_ways(_full_runs(green, h2), _full_runs(g4, h4))
    check("nw4 a measured green on each branch is the later green in both keys",
          r["conflicts"] == [] and meta(r) == (g4, h4) and sym, (r["conflicts"], meta(r)))
    # One side unchanged: the other side's run, whatever its moment.
    r = M.merge3(b, _full_runs(g0, h0), _full_runs(red_early, h0))
    check("nw5 ALLOW: a full run recorded on one branch only is that branch's record",
          r["conflicts"] == [] and meta(r) == (red_early, h0), (r["conflicts"], meta(r)))
    # A tie: two different runs stamped the same second.
    twin = _run("R9", "failed", red_early["at"], 900)
    r = M.merge3(b, _full_runs(red_early, h0), _full_runs(twin, h0))
    paths = [c["path"] for c in r["conflicts"]]
    check("nw6 two different full runs of the same moment are one conflict on the "
          "record, whose reason names the moment, since neither is the newer",
          paths == ["meta.lastFullRun"]
          and red_early["at"] in r["conflicts"][0]["reason"], r["conflicts"])
    # A moment that is not the recorder's form orders nothing.
    blank = dict(red_late, at="yesterday")
    r = M.merge3(b, _full_runs(red_early, h0), _full_runs(blank, h0))
    check("nw7 a run whose moment is not the recorder's stamp is a conflict naming the "
          "side that carries none, never a guess at which is newer",
          [c["path"] for c in r["conflicts"]] == ["meta.lastFullRun"]
          and "theirs' run carries no moment" in r["conflicts"][0]["reason"],
          r["conflicts"])
    # Deleted on one side, recorded on the other: still the delete-vs-change conflict.
    r = M.merge3(b, _full_runs(None, h0), _full_runs(red_late, h0))
    check("nw8 a record deleted on one branch and replaced on the other is still a "
          "delete-vs-change conflict, not the replacement taken as the newer",
          [c["path"] for c in r["conflicts"]] == ["meta.lastFullRun"]
          and "deleted" in r["conflicts"][0]["reason"], r["conflicts"])


# --- a value that is one account merges whole ------------------------------------
# A run record and the pointer beside it are one account of one run. Merged field by
# field, a red on the base, a green on one side and a newer red on the other conflict
# on the run id, the moment and the duration alone, and keeping one side there pairs
# that side's run id with the other side's status. The fixtures below are the shapes
# that tell a whole-value merge from a field merge: each side's run differs from the
# other's in every field, and one side carries a key the other does not.
_RUN_KEYS = ("lastRun", "testEvidence")


def _run(rid, status, at, ms, **extra):
    run = {"runId": rid, "at": at, "durationMs": ms, "status": status,
           "failed": ["tests/test_x.py"] if status == "failed" else []}
    run.update(extra)
    return run


def _recorded(holder, run):
    """`holder` with `run` as its record and the pointer derived from it."""
    out = dict(holder)
    if run is None:
        out.pop("lastRun", None)
        out.pop("testEvidence", None)
        return out
    # A copy per holder: the phase's and the task's runs must not be one object, or
    # an edit to one in a case edits the other with it.
    out["lastRun"] = copy.deepcopy(run)
    out["testEvidence"] = {"runId": run["runId"], "status": run["status"],
                           "at": run["at"]}
    return out


def _shard(phase_run, task_run, title="t P7.1"):
    """A phase shard whose phase and whose one task each hold a run."""
    task = _recorded(dict(_task("P7.1"), title=title), task_run)
    return _recorded({"id": "P7", "title": "seven", "status": "in_progress",
                      "tasks": [task]}, phase_run)


def _units(doc):
    """{subject: its run record and pointer, as one value} of a shard - the key
    absent from a unit where the document holds none."""
    def unit(holder):
        return dict((k, holder[k]) for k in _RUN_KEYS if k in holder)
    task = [t for t in doc.get("tasks") or [] if t.get("id") == "P7.1"]
    return {"phase": unit(doc), "task": unit(task[0]) if task else None}


def _blocks(text):
    return text.count("<<<<<<< ")


def _every_resolution(text):
    """Every document a person gets by keeping one side of each marker block, block
    by block - 2**blocks of them - each parsed, or the exception parsing raised."""
    lines = text.split("\n")
    n = _blocks(text)
    out = []
    for mask in range(2 ** n):
        kept, mode, block = [], None, -1
        for line in lines:
            if line.startswith("<<<<<<< "):
                block += 1
                mode = "ours"
                continue
            if line == "=======" and mode:
                mode = "theirs"
                continue
            if line.startswith(">>>>>>> ") and mode:
                mode = None
                continue
            if mode is None or mode == ("theirs" if mask >> block & 1 else "ours"):
                kept.append(line)
        try:
            out.append(json.loads("\n".join(kept)))
        except ValueError as exc:
            out.append(exc)
    return out


def _mixes(text, b, o, t):
    """[(resolution index, subject, the unit it holds)] for every resolution of `text`
    holding a run unit that is not base's, ours' or theirs' - [] when none does."""
    allowed = dict((s, [_units(d)[s] for d in (b, o, t)]) for s in ("phase", "task"))
    bad = []
    for i, doc in enumerate(_every_resolution(text)):
        if not isinstance(doc, dict):
            bad.append((i, "parse", "%s" % (doc,)))
            continue
        for subject, unit in sorted(_units(doc).items()):
            if unit not in allowed[subject]:
                bad.append((i, subject, unit))
    return bad


def _whole_value_cases(check):
    red = _run("R1", "failed", "2026-11-20T10:00:00Z", 100)
    green = _run("R2", "passed", "2026-11-20T11:00:00Z", 200,
                 attribution={"taskId": "P7.1", "basis": "ours alone wrote this"})
    newer = _run("R3", "failed", "2026-11-20T12:00:00Z", 300)
    group = "{lastRun,testEvidence}"

    # wv1 - the finding's own shape: red on the base, green on ours, a newer red on
    #       theirs, at both phase and task scope. Ours' run carries a key theirs'
    #       does not, so a field merge would carry it onto theirs' run.
    b, o, t = _shard(red, red), _shard(green, green), _shard(newer, newer)
    r = M.merge3(b, o, t)
    paths = sorted(c["path"] for c in r["conflicts"])
    check("wv1 a run recorded on both sides is ONE conflict per subject, on the record "
          "and its pointer together - not one per differing field",
          paths == sorted([group, "tasks[P7.1].%s" % (group,)]), paths)
    text = M.render(r, _dump)
    bad = _mixes(text, b, o, t)
    check("wv2 ...and every way of keeping a side of each marker block leaves each "
          "subject holding ours' run or theirs' run, byte for byte - no run id of one "
          "side beside the other's status, no key of one side on the other's run",
          _blocks(text) >= 1 and bad == [], "%r\n%s" % (bad, text))
    picked = [_units(d) for d in _every_resolution(text) if isinstance(d, dict)]
    check("wv3 ...and the two pure resolutions are ours' and theirs' runs exactly, so "
          "the block is not one that dropped a side",
          _units(o) in picked and _units(t) in picked, picked)

    # wv4 - one side only ADDS a key to the base's run; the other records a new one.
    graded = dict(red, gradedBy="P6")
    b, o, t = _shard(red, red), _shard(graded, graded), _shard(newer, newer)
    r = M.merge3(b, o, t)
    text = M.render(r, _dump)
    check("wv4 a key added to the base's run on one side while the other records a new "
          "run is a conflict on the whole record, never theirs' run wearing ours' key",
          sorted(c["path"] for c in r["conflicts"])
          == sorted([group, "tasks[P7.1].%s" % (group,)])
          and _mixes(text, b, o, t) == [], "%r\n%s" % (r["conflicts"], text))

    # wv5 - one side deletes the record and its pointer; the other records a run.
    b, o, t = _shard(red, red), _shard(None, None), _shard(newer, newer)
    r = M.merge3(b, o, t)
    text = M.render(r, _dump)
    check("wv5 a record deleted on one side and replaced on the other is one "
          "delete-vs-change conflict per subject: kept, the delete leaves neither the "
          "record nor its pointer; kept, the change leaves both",
          sorted(c["path"] for c in r["conflicts"])
          == sorted([group, "tasks[P7.1].%s" % (group,)])
          and all("deleted" in c["reason"] for c in r["conflicts"])
          and _mixes(text, b, o, t) == [], "%r\n%s" % (r["conflicts"], text))

    # wv6 - ALLOW: both sides wrote the same run (a reconcile on each branch).
    b, o, t = _shard(red, red), _shard(newer, newer), _shard(newer, newer, title="x")
    r = M.merge3(b, o, t)
    check("wv6 ALLOW: the same run written on both sides is no conflict, and the record "
          "is that run while a sibling field changed on one side still lands",
          r["conflicts"] == [] and _units(r["doc"]) == _units(t)
          and r["doc"]["tasks"][0]["title"] == "x", r)

    # wv7 - ALLOW: a run recorded on one side only is that side's run whole, while
    #       the other side changes a sibling field of the same task.
    b, o, t = _shard(red, red), _shard(green, green), _shard(red, red, title="y")
    r = M.merge3(b, o, t)
    check("wv7 ALLOW: a run recorded on one side only is that side's record and pointer "
          "whole, beside the other side's change to the same task",
          r["conflicts"] == [] and _units(r["doc"]) == _units(o)
          and r["doc"]["tasks"][0]["title"] == "y", r)

    # wv8 - a run recorded on both sides where the base held none: the case a field
    #       merge resolves with NO conflict at all for every field one side alone
    #       wrote.
    b, o, t = _shard(None, None), _shard(green, green), _shard(newer, newer)
    r = M.merge3(b, o, t)
    text = M.render(r, _dump)
    check("wv8 a first run recorded on both sides is one conflict on the whole record, "
          "never a run assembled from the two",
          sorted(c["path"] for c in r["conflicts"])
          == sorted([group, "tasks[P7.1].%s" % (group,)])
          and _mixes(text, b, o, t) == [], "%r\n%s" % (r["conflicts"], text))

    # wv9 - SECOND DIRECTION: a CONTAINER still merges by field. A task's `tests` is
    #       an authored spec whose fields are set by different verbs; if the whole
    #       rule leaked onto it, this would conflict.
    b = _shard(None, None)
    b["tasks"][0]["tests"] = {"mode": "tdd", "add": ["a"]}
    o = copy.deepcopy(b)
    o["tasks"][0]["tests"]["mode"] = "regression"
    t = copy.deepcopy(b)
    t["tasks"][0]["tests"]["gate"] = ["python3 x.py"]
    r = M.merge3(b, o, t)
    check("wv9 SECOND DIRECTION: a container (a task's `tests`) changed in two different "
          "fields still merges field by field, with no conflict",
          r["conflicts"] == [] and r["doc"]["tasks"][0]["tests"]
          == {"mode": "regression", "add": ["a"], "gate": ["python3 x.py"]}, r)

    # wv10 - the other accounts the plan holds: a phase's merge stamp (three sibling
    #        scalars, one landing) and its CI record.
    b = {"id": "P7", "title": "seven", "tasks": []}
    o = dict(b, mergedAt="2026-11-20T10:00:00Z", mergedHead="a" * 40,
             ci={"runId": "1", "sha": "a" * 40, "conclusion": "success",
                 "at": "2026-11-20T10:05:00Z"})
    t = dict(b, mergedAt="2026-11-20T11:00:00Z", mergedHead="b" * 40,
             mergedHeadAt="2026-11-20T11:30:00Z",
             ci={"runId": "2", "sha": "b" * 40, "conclusion": "failure",
                 "at": "2026-11-20T11:05:00Z"})
    r = M.merge3(b, o, t)
    paths = sorted(c["path"] for c in r["conflicts"])
    stamp = ("mergedAt", "mergedHead", "mergedHeadAt", "ci")

    def accounts(doc):
        return dict((k, doc.get(k)) for k in stamp)
    resolutions = [d for d in _every_resolution(M.render(r, _dump)) if isinstance(d, dict)]
    mixed = [accounts(d) for d in resolutions
             if dict((k, accounts(d)[k]) for k in stamp[:3])
             not in [dict((k, accounts(x)[k]) for k in stamp[:3]) for x in (o, t)]
             or accounts(d)["ci"] not in (o["ci"], t["ci"])]
    check("wv10 a merge stamp with its head, and a CI record, each set on both sides "
          "are one conflict apiece, every resolution one side's landing and one "
          "side's CI run whole",
          paths == ["ci", "{mergedAt,mergedHead,mergedHeadAt}"]
          and resolutions and mixed == [], (paths, mixed))

    # wv11 - every conflict, not only a whole value, is one block: a plain list
    #        changed on both sides kept half from each side is a list neither wrote.
    b = {"id": "P7", "title": "seven", "tasks": [_task("P7.1", files=["a", "b", "c"])]}
    o = copy.deepcopy(b)
    o["tasks"][0]["files"] = ["a", "x", "c", "d"]
    t = copy.deepcopy(b)
    t["tasks"][0]["files"] = ["a", "y", "c", "e"]
    text = M.render(M.merge3(b, o, t), _dump)
    lists = [d["tasks"][0]["files"] for d in _every_resolution(text) if isinstance(d, dict)]
    check("wv11 a list changed on both sides is one marker block, so no resolution "
          "holds a list neither side wrote",
          lists and all(x in (o["tasks"][0]["files"], t["tasks"][0]["files"])
                        for x in lists), "%r\n%s" % (lists, text))

    # wv18 - a task's close is one account written in one write: its commit, the
    #        moment, the outcome and who verified it. Sibling scalars, so the object
    #        walk cannot find them; the row is held here by behaviour.
    close = ("commit", "completedAt", "outcome", "verifiedBy")
    b = {"id": "P7", "title": "seven", "tasks": [_task("P7.1", status="done")]}
    o = copy.deepcopy(b)
    o["tasks"][0].update(commit="a" * 40, completedAt="2026-11-20T10:00:00Z",
                         outcome={"technical": "ours", "descriptive": "ours"},
                         verifiedBy=["gate"])
    t = copy.deepcopy(b)
    t["tasks"][0].update(commit="b" * 40, completedAt="2026-11-20T11:00:00Z",
                         outcome={"technical": "theirs", "descriptive": "theirs"},
                         verifiedBy=["gate"])
    r = M.merge3(b, o, t)

    def closed(doc):
        return dict((k, doc["tasks"][0].get(k)) for k in close)
    seen = [closed(d) for d in _every_resolution(M.render(r, _dump)) if isinstance(d, dict)]
    check("wv18 a task closed on both sides is one conflict on its close - commit, moment, "
          "outcome and verification together - and no resolution pairs one side's commit "
          "with the other's moment",
          [c["path"] for c in r["conflicts"]]
          == ["tasks[P7.1].{status,commit,completedAt,outcome,verifiedBy}"]
          and seen and all(s in (closed(o), closed(t)) for s in seen), (r["conflicts"], seen))

    # wv19 - THE KEYS OF ONE VALUE ARE NOT ADJACENT in a real plan: a task's pointer
    #        is written early and its record after other accounts, and a sign-off's
    #        verdict sits on both sides of the findings list. The block must still
    #        span the value from its first key to its last.
    def run_task(run):
        return {"id": "P7.1", "title": "t", "status": "pending",
                "testEvidence": {"runId": run["runId"], "status": run["status"],
                                 "at": run["at"]},
                "description": "a task", "intentCheck": {"answer": "matches", "commit": "c"},
                "lastRun": copy.deepcopy(run)}

    def review(status, outcome):
        return {"status": status, "findings": [{"id": "first", "issue": "x"},
                                               {"id": "second", "issue": "y"}],
                "outcome": outcome}
    b = {"id": "P7", "title": "seven", "review": review("pending", None),
         "tasks": [run_task(red)]}
    o = dict(copy.deepcopy(b), review=review("passed", "ours ok"), tasks=[run_task(green)])
    t = dict(copy.deepcopy(b), review=review("failed", "theirs no"), tasks=[run_task(newer)])

    def apart(doc):
        task = doc["tasks"][0]
        return (dict((k, task.get(k)) for k in _RUN_KEYS),
                dict((k, doc["review"].get(k)) for k in ("status", "outcome")))
    text = M.render(M.merge3(b, o, t), _dump)
    held = [apart(d) for d in _every_resolution(text) if isinstance(d, dict)]
    check("wv19 a whole value whose keys sit apart in the record - a pointer before other "
          "accounts and its record after them, a verdict on both sides of the findings - "
          "is still one block per value: every resolution holds one side's run and one "
          "side's verdict",
          held and all(h[0] in (apart(o)[0], apart(t)[0]) and h[1] in (apart(o)[1],
                                                                       apart(t)[1])
                       for h in held), "%r\n%s" % (held, text))

    # wv20 - a block names the conflicts it holds and no other.
    def runs_on(doc_runs):
        tasks = [_recorded(_task("P7.%d" % i), r) for i, r in enumerate(doc_runs, 1)]
        tasks[1].update(description="\n".join(["an unchanged task between them"] * 3),
                        files=["a", "b", "c", "d"])
        return {"id": "P7", "title": "seven", "tasks": tasks}
    b = runs_on([red, red, red])
    o = runs_on([green, red, green])
    t = runs_on([newer, red, newer])
    text = M.render(M.merge3(b, o, t), _dump)
    labels = [ln for ln in text.split("\n") if ln.startswith("<<<<<<< ")]
    check("wv20 two conflicts in two blocks: each block's marker names its own record "
          "and not the other's: %r" % (labels,),
          len(labels) == 2 and "tasks[P7.1]" in labels[0] and "tasks[P7.3]" not in labels[0]
          and "tasks[P7.3]" in labels[1] and "tasks[P7.1]" not in labels[1])

    # wv21 - one account per group the writers write together, each set two ways.
    def mixes(b, o, t, pick):
        r = M.merge3(b, o, t)
        seen = [pick(d) for d in _every_resolution(M.render(r, _dump)) if isinstance(d, dict)]
        allowed = [pick(x) for x in (b, o, t)]
        return len(r["conflicts"]), seen, [s for s in seen if s not in allowed]
    shapes = []
    p = {"id": "P7", "title": "seven", "testGateBasis": "listing",
         "testGateDerived": {"tests": ["a0"], "at": "T0"}, "tasks": []}
    shapes.append(("a gate derivation and its basis", p,
                   dict(p, testGateDerived={"tests": ["a"], "at": "T1"}, testGateBasis="derived"),
                   dict(p, testGateDerived={"tests": ["b"], "at": "T2"},
                        testGateBasis="derived-empty"),
                   lambda d: (d.get("testGateDerived"), d.get("testGateBasis"))))
    plan = {"decisions": [{"id": "DEC-1", "title": "q", "status": "pending", "answer": None,
                           "decidedBy": None, "decidedAt": None}]}
    yes, no = copy.deepcopy(plan), copy.deepcopy(plan)
    yes["decisions"][0].update(status="done", answer="ship", decidedBy="a", decidedAt="T1")
    no["decisions"][0].update(status="done", answer="hold", decidedBy="b", decidedAt="T2")
    shapes.append(("a decision", plan, yes, no, lambda d: d["decisions"][0]))
    p = {"id": "P7", "title": "s", "tasks": [_task("P7.1")]}
    p["tasks"][0]["tests"] = {"mode": "tdd", "gate": ["g0"], "gateBasis": "derived"}
    g1, g2 = copy.deepcopy(p), copy.deepcopy(p)
    g1["tasks"][0]["tests"].update(gate=["g1"], gateBasis="declared")
    g2["tasks"][0]["tests"].update(gate=[], gateBasis="cleared")
    shapes.append(("a task's gate and its basis", p, g1, g2,
                   lambda d: d["tasks"][0]["tests"]))
    plan = {"proposals": [{"id": "PROP-1", "name": "n", "status": "proposed"}]}
    made, dropped = copy.deepcopy(plan), copy.deepcopy(plan)
    made["proposals"][0].update(status="materialized", materializedAs="P5", materializedAt="T1")
    dropped["proposals"][0].update(status="dropped", notes="no", droppedAt="T2")
    shapes.append(("a proposal materialized on one side, dropped on the other", plan,
                   made, dropped, lambda d: d["proposals"][0]))
    p = {"id": "P7", "title": "s", "tasks": [_task("P7.1", status="in_progress")]}
    blocked, done = copy.deepcopy(p), copy.deepcopy(p)
    blocked["tasks"][0].update(status="blocked", blockedReason="waiting")
    done["tasks"][0].update(status="done", commit="c", completedAt="T",
                            outcome={"technical": "x"}, verifiedBy=[])
    shapes.append(("a task blocked on one side, closed on the other", p, blocked, done,
                   lambda d: d["tasks"][0]))
    got = [(name,) + mixes(b, o, t, pick) for name, b, o, t, pick in shapes]
    check("wv21 every group a writer writes together - a gate derivation with its basis, "
          "a decision, a task's gate with its basis, a proposal's disposition, a task's "
          "status with the move that set it - set two ways is one conflict and no "
          "resolution mixes the two: %r" % ([(g[0], g[1], g[3]) for g in got],),
          all(n == 1 and seen and not bad for _name, n, seen, bad in got))

    # wv22 - a parked phase is a phase: edits to two of its fields both land, and a run
    #        recorded inside it on both sides is one conflict on the record.
    parked = {"id": "P9", "title": "nine", "description": "d",
              "tasks": [_recorded(_task("P9.1"), red)]}
    plan = {"proposals": [{"id": "PROP-1", "name": "n", "status": "proposed",
                           "payload": {"phase": parked}}]}
    o, t = copy.deepcopy(plan), copy.deepcopy(plan)
    o["proposals"][0]["payload"]["phase"]["title"] = "ours"
    t["proposals"][0]["payload"]["phase"]["description"] = "theirs"
    clean = M.merge3(plan, o, t)
    o["proposals"][0]["payload"]["phase"]["tasks"][0] = _recorded(_task("P9.1"), green)
    t["proposals"][0]["payload"]["phase"]["tasks"][0] = _recorded(_task("P9.1"), newer)
    ran = M.merge3(plan, o, t)
    check("wv22 a parked phase merges as a phase: two fields edited apart both land, and "
          "a run recorded in it on both sides is one conflict on the record",
          clean["conflicts"] == []
          and clean["doc"]["proposals"][0]["payload"]["phase"]["title"] == "ours"
          and clean["doc"]["proposals"][0]["payload"]["phase"]["description"] == "theirs"
          and [c["path"] for c in ran["conflicts"]]
          == ["proposals[PROP-1].payload.phase.tasks[P9.1].%s" % (group,)],
          (clean["conflicts"], ran["conflicts"]))

    # wv27 - two verbs writing apart in one record both land; two accounts meeting on
    #        a key are one conflict. A retry moves no status, so its row and the
    #        close's meet on no key either side moved and both land; a START moves
    #        the status, which the close's row holds too, so the close's row changed
    #        on both sides and the start's and the proof's accounts are one conflict:
    #        landed apart, the merged close would pair ours' status with theirs'
    #        proof, a close neither side wrote.
    def bug_plan(**kw):
        return {"bugs": [dict({"id": "BUG-1", "title": "b", "status": "open",
                               "notes": "seen"}, **kw)]}

    def finding_phase(**kw):
        return {"id": "P7", "title": "s", "tasks": [], "review": {
            "status": "failed", "findings": [dict({"id": "x1", "issue": "i",
                                                   "status": "open"}, **kw)]}}

    def task_phase(**kw):
        return {"id": "P7", "title": "s", "tasks": [dict(_task("P7.1", status="in_progress"),
                                                         **kw)]}
    shapes = [
        ("apart", "a bug fixed on one side, its notes edited on the other",
         bug_plan(), bug_plan(status="fixed", fixedIn="c"), bug_plan(notes="seen twice")),
        ("apart", "a finding's resolution edited on one side, a fixing task linked on "
                  "the other", finding_phase(), finding_phase(resolution="typed"),
         finding_phase(fixTask="P7.9")),
        ("apart", "a retry moving no status - a task's attempts and start moved on one "
                  "side - its red-first proof re-recorded on the other", task_phase(),
         task_phase(attempts=2, startedAt="T2"), task_phase(redFirst={"status": "proved"})),
        ("one", "a start moving the status from pending on one side, its red-first proof "
                "re-recorded on the other", task_phase(status="pending"),
         task_phase(attempts=1, startedAt="T1"),
         task_phase(status="pending", redFirst={"status": "proved"})),
        ("one", "a finding accepted on one side, carried on the other", finding_phase(),
         finding_phase(status="accepted-open", acceptedReason="ok"),
         finding_phase(status="carried", carriedTo="BUG-1")),
        ("one", "a finding landed on one side, linked to another fixing task on the other",
         finding_phase(), finding_phase(status="fixed", commit="c", fixTask="P7.2",
                                        resolution="fixed in P7.2"),
         finding_phase(fixTask="P7.3")),
        ("one", "a bug closed on one side, linked to a fixing task on the other",
         bug_plan(), bug_plan(status="wontfix"), bug_plan(taskId="P7.1")),
        ("one", "a task blocked on one side, closed on the other", task_phase(),
         task_phase(status="blocked", blockedReason="w"),
         task_phase(status="done", commit="c", completedAt="T")),
    ]
    got = [(want, name, [c["path"] for c in M.merge3(b, o, t)["conflicts"]])
           for want, name, b, o, t in shapes]
    wrong = [(name, paths) for want, name, paths in got
             if (want == "apart" and paths) or (want == "one" and len(paths) != 1)]
    # The start beside the proof is one conflict over BOTH accounts - the start's
    # status, moment and attempt with the close's proof - never two blocks, one per
    # account, whose sides a person could keep apart.
    started = [paths for _want, name, paths in got if name.startswith("a start moving")]
    check("wv27 two verbs writing apart in one record both land - a fix beside a note, a "
          "resolution beside a fixing task, a retry moving no status beside a red-first "
          "proof - and two accounts meeting on a key are one conflict, a start moving the "
          "status beside a re-recorded proof among them, over both accounts whole: "
          "wrong %r, the start's %r" % (wrong, started),
          wrong == [] and len(got) == 8
          and started == [["tasks[P7.1].{status,startedAt,attempts,redFirst}"]])

    # wv12 - the read the resolver makes: a hand-resolved document whose run unit is
    #        neither side's nor the base's is named by its path; one side's unit,
    #        the base's, or a container field edited are not.
    b, o, t = _shard(red, red), _shard(green, green), _shard(newer, newer)
    mixed_doc = copy.deepcopy(o)
    mixed_doc["tasks"][0]["lastRun"]["status"] = "failed"
    named = [f["path"] for f in M.foreign_values(b, o, t, mixed_doc)]
    # A key DELETED by hand is judged too: ours' record kept, its pointer dropped.
    halved = copy.deepcopy(o)
    del halved["tasks"][0]["testEvidence"]
    dropped = [f["path"] for f in M.foreign_values(b, o, t, halved)]
    # A side as resolve renumbered it is a side too: its record is not foreign.
    renamed = M.foreign_values(b, o, t, mixed_doc, also=[copy.deepcopy(mixed_doc)])
    check("wv12 a hand-resolved record that is neither side's nor the base's is named "
          "by its path - one assembled from both sides, and one side's record with its "
          "pointer deleted - and one a renumbered side holds is not",
          named == ["tasks[P7.1].%s" % (group,)]
          and dropped == ["tasks[P7.1].%s" % (group,)] and renamed == [],
          (named, dropped, renamed))
    clean = [M.foreign_values(b, o, t, d) for d in (b, o, t)]
    edited = copy.deepcopy(t)
    edited["tasks"][0]["title"] = "typed by hand"
    check("wv13 ALLOW: one side's document, the base's, or one whose only hand edit is "
          "a container field names no record",
          clean == [[], [], []] and M.foreign_values(b, o, t, edited) == [],
          (clean, M.foreign_values(b, o, t, edited)))


# --- the table of whole values, held to the schema ---------------------------------
def _schema():
    import os
    import _output
    with open(os.path.join(_output.PLUGIN_ROOT, "schema", "audit-plan.schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _schema_kinds(schema):
    """{kind: {key: the property's resolved schema}} for every kind the merge walks
    INTO - the plan, every record kind its keyed lists hold, and every value the
    table calls a container or a map - plus [(list kind, element def)] for each
    keyed list met, read off the schema alone. A whole value is not walked into."""
    defs = schema.get("$defs") or {}

    def res(node):
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 20:
            node = defs.get(node["$ref"].rsplit("/", 1)[-1], {})
            seen += 1
        return node if isinstance(node, dict) else {}

    def types(node):
        t = res(node).get("type")
        return set(t if isinstance(t, list) else [t])

    def object_form(node):
        """The object a value is, or one of its `oneOf` arms is - else None."""
        node = res(node)
        if "object" in types(node):
            return node
        for arm in node.get("oneOf") or []:
            if "object" in types(arm):
                return res(arm)
        return None

    def element_def(node):
        items = res(node).get("items")
        if not isinstance(items, dict):
            return None, None
        obj = object_form(items)
        if obj is None or "id" not in (obj.get("properties") or {}):
            return None, None
        name = items.get("$ref", "").rsplit("/", 1)[-1] or None
        return name, obj

    verdicts = dict(((row[0], key), row[2]) for row in M.MERGE_UNITS for key in row[1])
    kinds, elements, objects, todo, seen = {}, [], set(), [("plan", schema)], set()
    refs = []
    while todo:
        kind, node = todo.pop()
        if kind in seen:
            continue
        seen.add(kind)
        props = dict((res(node).get("properties") or {}).items())
        extra = res(node).get("additionalProperties")
        if not props and isinstance(extra, dict):
            props = {"*": extra}
        kinds[kind] = props
        for key, sub in props.items():
            if "array" in types(sub):
                name, obj = element_def(sub)
                if obj is not None:
                    elements.append(("%s.%s" % (kind, key), name))
                    todo.append((name, obj))
                continue
            if object_form(sub) is None:
                continue
            objects.add((kind, key))
            if verdicts.get((kind, key)) in ("container", "map"):
                child = "%s.%s" % (kind, key)
                name = sub.get("$ref", "").rsplit("/", 1)[-1] if isinstance(sub, dict) else ""
                if name in set(n for _l, n in elements) | set(M.ELEMENT_KINDS.values()):
                    refs.append((child, name))
                    child = name
                todo.append((child, object_form(sub)))
    return kinds, elements, objects, refs


# --- groups found by their writers --------------------------------------------------
# A value made of SIBLING keys - a merge stamp, a task's close - is no object, so the
# schema walk cannot ask about it. Its writers can: a verb that sets several keys of
# one record in one function wrote one account, or several. The scan reads every
# `.py` under `scripts/` and collects, per function, the constant keys written to one
# target (`x["k"] = ...`, `x.pop("k")`, `x.update(k=...)` and `x.update({...})`), and
# the constant keys of each `dict(x, k=...)` call and each dict literal carrying no
# `id` (a literal with an id is a record being created, all its keys new at once). A
# key named by a module constant - `MERGED_HEAD_FIELD`, `_fr.READ_RETURNS_FIELD` - is
# read as the string it holds. A key set that is all keys of one kind the schema walk
# reaches is a CO-WRITE of that kind.
#
# WHAT IT CANNOT SEE: a key computed at run time (a loop over names, a key read from
# an argument), keys written to one record by two functions (a helper writing one,
# its caller another), a write through any other method (`setdefault`, `__setitem__`,
# a copy assigned whole), and a record no code writes - a decision, written by a
# person. Those are answered by reading, in `_GROUPS_UNSCANNED`, each with its reason.
# And a key set naming the keys of two kinds is reported under both.
# Why a phase's status is in no row while a task's is in two. A task's status is the
# record of what happened to it, written by the verb that moved it, and nothing
# re-derives it. A phase's is read through `_manifest_io.effective_phase_status`,
# which derives `done` from the tasks, the sign-off and the merge, and close-phase
# stores that derivation - so the common mix, a phase one side finished, is answered
# from the merged tasks. What that does NOT cover, and is the cost: a stored terminal
# word is never re-derived, so a cancel on one side against a claim taken on the
# other conflicts on the status and on the claim apart, and keeping one block of each
# pairs a cancelled phase with a live claim. Folding the status into the claim's row
# would close that and open a worse one: a sign-off releasing the claim on the phase
# branch would conflict with every status the panel heals on the other.
_PHASE_STATUS = ("a phase's stored status merges alone beside the claim (whole on its "
                 "own) and the summary (prose); the comment above says what the "
                 "derivation covers and what it costs")
_CO_WRITES_APART = {
    ("bug", ("fixedIn", "status")):
        "a lookup's report row (audit-lookup.py), built to print, never written",
    ("bug", ("fixedIn", "notes", "status")):
        "a close appends its reason to the notes, a log a person also writes to by hand, "
        "so the notes merge apart from the close: a fix on one side and a note on the "
        "other both land. The cost: a close against a notes edit conflicts on the notes "
        "alone, and keeping the edit's block keeps the close without its reason line",
    ("phase", ("ado", "adoParent")):
        "a bug's work item link and parent copied off another record, two accounts",
    ("task", ("ado", "adoParent")):
        "a bug's work item link and parent copied off another record, two accounts",
    ("phase", ("area", "description", "desiredOutcome", "parentBranch", "testGate",
               "title")):
        "retarget sets the fields it is passed; each is an authored value of its own",
    ("phase", ("area", "parentBranch", "reviewSkill")):
        "a phase being built, every key new",
    ("phase", ("area", "review")):
        "a panel edit applying the fields it is given, each its own value",
    ("phase", ("baseRef", "branch", "claim")):
        "a start writes the start and takes the claim: two accounts, each whole",
    ("phase", ("claim", "lastRun", "review", "summary", "testEvidence")):
        "a group sign-off: the claim released, the verdict (inside review, whole there), "
        "a run copied with its pointer (whole), and the summary - prose the next "
        "sign-off rewrites, merged alone",
    ("phase", ("claim", "review", "summary")):
        "a sign-off: the claim released, the verdict (whole inside review), the summary",
    ("phase", ("claim", "status")):
        "a phase assembled from its index stub and its shard (`_merge_phase`) - a read "
        "filling keys the shard omits, nothing written",
    ("phase", ("claim", "status", "summary")): _PHASE_STATUS,
    ("phase", ("openChoices", "request")): "authored fields of a phase being added",
    ("phase", ("review", "summary")):
        "a correction rewriting the verdict (whole inside review) and the summary",
    ("phase", ("startedAt", "status")): _PHASE_STATUS,
    ("phase.review", ("findings", "model", "status", "tool")):
        "the empty review of a phase being created, every key new",
    ("phase.review", ("findings", "outcome")):
        "a finding added or unresolved rewrites the outcome's tally; findings are records "
        "of their own, so a change to both on two sides conflicts on the verdict",
    ("plan.meta", ("ado", "branch", "buildCommands", "reviewSkill")):
        "the panel's settings view, built to show",
    ("plan.meta", ("ado", "buildCommands", "reviewSkill")): "the panel's settings view",
    ("plan.meta", ("areas", "reviewSkill")): "help text naming settings",
    ("plan.meta", ("branchPrefix", "buildCommands", "createdISO", "developmentBranch",
                   "gitRoot", "repo", "version")): "a plan being created, every key new",
    ("plan.meta", ("buildCommands", "nodePreamble")):
        "a gate run reading two settings, never writing them",
    ("task", ("attempts", "risk", "status", "title")):
        "the usage panel's row for a task, built to show",
    ("task", ("bugId", "fixes")): "authored links from a task to the bug it fixes",
    ("task", ("attempts", "blockedReason", "startedAt", "status", "timing")):
        "a start writes the start's account (whole) and appends a stage to its timing, "
        "a container of stages",
    ("task.timing", ("firstStartedAt", "stages")):
        "the first start, set once, beside stages every later start appends",
    ("finding", ("file", "issue", "resolution", "severity")):
        "a finding's text as the reviewer returned it, before its id is given",
    ("task", ("commit", "completedAt", "intentCheck", "outcome", "redFirst", "status",
              "verifiedBy")):
        "a close writes the close's account (whole) and the intent check, which its own "
        "verb re-records alone",
    ("task", ("description", "files", "notes", "risk", "tests")):
        "scope sets the authored fields it is passed",
    ("task", ("description", "fixes", "title")): "authored fields of a task being drafted",
    ("task", ("files", "tests")): "authored fields copied into a brief",
    ("task", ("model", "skills")): "a panel edit applying the fields it is given",
    ("task.tests", ("add", "expectRedFirst", "gate", "gateBasis", "mode")):
        "scope writes the whole spec; the gate with its basis is the one account in it",
    ("task.tests", ("add", "mode")): "a drafted spec's fields, each its own",
}
# Kinds whose keys are each a value of their own, so a co-write there is never asked:
# a kind named here covers the kinds below it.
_KINDS_APART = {
    "plan": "the document's sections - meta, phases, bugs, the file index - each merged "
            "by its own structure; a writer building or reading the document names them "
            "together",
    "plan.meta": "the plan's settings, each read on its own by the code that uses it; a "
                 "default or a settings view names several at once",
}


def _apart_kind(kind):
    return any(kind == k or kind.startswith(k + ".") for k in _KINDS_APART)


_GROUPS_UNSCANNED = {
    ("decision", ("status", "answer", "decidedBy", "decidedAt")):
        "no code writes a decision: manifest-conventions.md has a person write it, and "
        "the validator requires the answer and who gave it once it is done",
}


def _own_nodes(scope):
    """Every node of `scope` but those of the functions and classes defined inside it,
    which are scopes of their own: a module's writes are its top-level statements'."""
    import ast
    todo, out = list(ast.iter_child_nodes(scope)), []
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Lambda)):
            continue
        out.append(node)
        todo.extend(ast.iter_child_nodes(node))
    return out


# THE SHAPES THE SCAN READS, named once: every branch of `_co_writes` that reads one
# is guarded by its name here, and `_SCAN_SHAPES` below holds one fixture per name.
# wv25 holds the two to each other both ways - a fixture with no name, a name with
# no fixture - and proves each guard real: its fixture is found with every shape
# read, and NOT found with its own shape left out, so a branch that stopped reading
# turns its own name red.
SCAN_READS = ("subscript", "pop", "update(k=...)", "update({...})", "dict(x, k=...)",
              "dict literal", "module constant", "imported constant")


def _co_writes(root=None, reads=SCAN_READS):
    """{(kind, sorted keys): [file:line]} of every co-write the scan finds in the
    `.py` files under `root` (`scripts/` when None), reading the shapes `reads`
    names."""
    import ast
    import os
    import _output
    root = root or _output.SCRIPTS_DIR
    kinds = _schema_kinds(_schema())[0]
    trees = {}
    for dp, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(dp, f)
                with open(p, encoding="utf-8") as fh:
                    trees[p] = ast.parse(fh.read())
    consts = dict((os.path.basename(p)[:-3], dict(
        (n.targets[0].id, n.value.value) for n in t.body
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str))) for p, t in trees.items())
    found = {}

    def note(keys, where):
        keys = frozenset(k for k in keys if k)
        if len(keys) < 2:
            return
        for kind, props in kinds.items():
            if keys <= set(props):
                found.setdefault((kind, tuple(sorted(keys))), []).append(where)

    for path, tree in sorted(trees.items()):
        mod = os.path.basename(path)[:-3]
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        alias = dict((a.asname or a.name, a.name) for n in ast.walk(tree)
                     if isinstance(n, ast.Import) for a in n.names)

        def key(n, mod=mod, alias=alias):
            if isinstance(n, getattr(ast, "Index", ())):
                n = n.value
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                return n.value
            if isinstance(n, ast.Name) and "module constant" in reads:
                return consts[mod].get(n.id)
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and "imported constant" in reads):
                return consts.get(alias.get(n.value.id, ""), {}).get(n.attr)
            return None
        scopes = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for scope in scopes:
            per = {}
            for node in _own_nodes(scope):
                at = "%s:%d" % (rel, getattr(node, "lineno", 0))
                if isinstance(node, ast.Dict) and "dict literal" in reads:
                    keys = [key(k) for k in node.keys if k is not None]
                    if "id" not in keys:
                        note(keys, at)

                def write(target, keys, node=node):
                    entry = per.setdefault(ast.dump(target), [set(), []])
                    entry[0].update(k for k in keys if k)
                    entry[1].append(node.lineno)
                if isinstance(node, ast.Assign) and "subscript" in reads:
                    for tg in node.targets:
                        if isinstance(tg, ast.Subscript) and key(tg.slice):
                            write(tg.value, [key(tg.slice)])
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                kws = [k.arg for k in node.keywords if k.arg]
                if (isinstance(fn, ast.Name) and fn.id == "dict" and node.args
                        and "dict(x, k=...)" in reads):
                    note(kws, at)
                if not isinstance(fn, ast.Attribute):
                    continue
                if fn.attr == "pop" and node.args and key(node.args[0]) and "pop" in reads:
                    write(fn.value, [key(node.args[0])])
                if fn.attr == "update":
                    keys = kws if "update(k=...)" in reads else []
                    if (node.args and isinstance(node.args[0], ast.Dict)
                            and "update({...})" in reads):
                        keys += [key(k) for k in node.args[0].keys if k is not None]
                    if keys:
                        write(fn.value, keys)
            # Named by the first write of the set, in the function that makes them.
            for keys, lines in per.values():
                note(keys, "%s:%d" % (rel, min(lines)))
    return found


# One fixture per name in `SCAN_READS`, each a co-write that shape alone completes,
# so leaving the shape out loses it. `actual` and `expected` are keys of a bug and of
# no other kind. The `update({...})` fixture writes one key through it and the other
# by subscript: a dict literal of one key is no co-write, so the dict literal branch
# cannot stand in for it.
_SCAN_SHAPES = (
    ("subscript", {"w.py": "def w(b):\n    b['actual'] = 1\n    b['expected'] = 2\n"}, 2),
    ("pop", {"w.py": "def w(b):\n    b.pop('actual')\n    b.pop('expected')\n"}, 2),
    ("update(k=...)", {"w.py": "def w(b):\n    b.update(actual=1, expected=2)\n"}, 2),
    ("update({...})", {"w.py": "def w(b):\n    b.update({'actual': 1})\n"
                               "    b['expected'] = 2\n"}, 2),
    ("dict(x, k=...)", {"w.py": "def w(b):\n    return dict(b, actual=1, expected=2)\n"}, 2),
    ("dict literal", {"w.py": "def w():\n    return {'actual': 1, 'expected': 2}\n"}, 2),
    ("module constant", {"w.py": "A = 'actual'\nE = 'expected'\n\n\ndef w(b):\n"
                                 "    b[A] = 1\n    b[E] = 2\n"}, 6),
    ("imported constant", {"names.py": "A = 'actual'\nE = 'expected'\n",
                           "w.py": "import names as n\n\n\ndef w(b):\n    b[n.A] = 1\n"
                                   "    b[n.E] = 2\n"}, 5),
)
_SCAN_QUIET = (
    ("a record created with its id", {"w.py": "def w():\n    return {'id': 'B', "
                                              "'actual': 1, 'expected': 2}\n"}),
    ("two functions, one key each", {"w.py": "def w(b):\n    b['actual'] = 1\n\n\n"
                                             "def v(b):\n    b['expected'] = 2\n"}),
)


def _scan_fixture(files, reads=SCAN_READS):
    import os
    import shutil
    import tempfile
    root = tempfile.mkdtemp()
    try:
        for name, text in files.items():
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        return _co_writes(root, reads).get(("bug", ("actual", "expected")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _scan_shape_cases(check):
    names = [name for name, _files, _line in _SCAN_SHAPES]
    unproved = sorted(set(SCAN_READS) - set(names))
    unnamed = sorted(set(names) - set(SCAN_READS))
    twice = sorted(set(n for n in names if names.count(n) > 1))
    missed, standing = [], []
    for name, files, line in _SCAN_SHAPES:
        got = _scan_fixture(files)
        if got != ["w.py:%d" % (line,)]:
            missed.append((name, got))
        without = _scan_fixture(files, tuple(r for r in SCAN_READS if r != name))
        if without is not None:
            standing.append((name, without))
    check("wv25 every shape the scan reads (`SCAN_READS`) has its own fixture and no "
          "fixture names a shape the scan does not read; each fixture is found, at the "
          "line of its first write, and is NOT found with its own shape left out - "
          "no fixture %r, no shape %r, twice %r, not found %r, found without its "
          "shape %r" % (unproved, unnamed, twice, missed, standing),
          not (unproved or unnamed or twice or missed or standing) and names)
    loud = [(name, got) for name, got in ((n, _scan_fixture(f)) for n, f in _SCAN_QUIET)
            if got is not None]
    check("wv26 ALLOW: a record created with its id, and two keys written by two "
          "functions, are no co-write: %r" % (loud,), loud == [])


def _co_write_cases(check):
    _scan_shape_cases(check)
    found = _co_writes()
    rows = [(row[0], row[1]) for row in M.MERGE_UNITS if row[2] == "whole"]

    # Held means what the merge does with it: the co-write performed two ways on two
    # sides is ONE unit - one whole row, or rows the merge joins through a key the
    # writer moved.
    def held(kind, keys):
        b, o, t = ({k: v for k in keys} for v in ("b", "o", "t"))
        return any(set(keys) <= set(u) for u in M._units(kind, b, o, t))
    unanswered = sorted("%s %s at %s" % (kind, "+".join(keys), found[(kind, keys)][0])
                        for kind, keys in found
                        if not held(kind, keys) and (kind, keys) not in _CO_WRITES_APART
                        and not _apart_kind(kind))
    check("wv23 every group of one record's keys a writer writes together is one whole "
          "value of the table, or written together on purpose with the reason here - "
          "found and unanswered: %r" % (unanswered,),
          unanswered == [] and len(found) > 10)
    stale = sorted("%s %s" % (k, "+".join(keys)) for k, keys in _CO_WRITES_APART
                   if (k, keys) not in found)
    groups = [(k, r) for k, r in rows if len(r) > 1]
    unwritten = sorted("%s {%s}" % (k, ",".join(r)) for k, r in groups
                       if (k, r) not in _GROUPS_UNSCANNED
                       and not any(fk == k and len(set(fk_keys) & set(r)) > 1
                                   for fk, fk_keys in found))
    loose = sorted("%s %s" % (k, r) for k, r in _GROUPS_UNSCANNED
                   if (k, r) not in groups
                   or any(fk == k and len(set(fk_keys) & set(r)) > 1
                          for fk, fk_keys in found))
    check("wv24 ...and the other way: every group of sibling keys the table holds whole "
          "is written together by some writer the scan reads, or is answered by reading "
          "with its reason, and no reason names a co-write the scan no longer finds; "
          "stale %r, unwritten %r, loose %r" % (stale, unwritten, loose),
          not (stale or unwritten or loose) and groups)


def _schema_table_cases(check):
    kinds, elements, objects, refs = _schema_kinds(_schema())
    named = {}
    for kind, keys, verdict, _why in M.MERGE_UNITS:
        for key in keys:
            named.setdefault((kind, key), []).append(verdict)
    unasked = sorted("%s.%s" % k for k in objects if k not in named)
    check("wv14 every object value the schema declares on a kind the merge walks into "
          "is asked the question by name - one row says whether it is ONE ACCOUNT "
          "(merged whole) or a CONTAINER (merged field by field); unasked: %r"
          % (unasked,), unasked == [] and len(kinds) > 5)
    stale = sorted("%s.%s" % k for k in named
                   if k[0] not in kinds or k[1] not in kinds[k[0]])
    # Two verbs' accounts may share a key (a task's status), so a key may sit in two
    # whole rows - never in two verdicts, never twice in one row, and never in two
    # rows that are the same set.
    twice = sorted("%s.%s" % k for k, v in named.items()
                   if len(v) > 1 and set(v) != set(["whole"]))
    rows = [(row[0], tuple(sorted(row[1]))) for row in M.MERGE_UNITS]
    twice += sorted("%s %s" % r for r in set(rows) if rows.count(r) > 1)
    twice += sorted("%s %s" % (row[0], row[1]) for row in M.MERGE_UNITS
                    if len(set(row[1])) != len(row[1]))
    vocab = sorted(set(row[2] for row in M.MERGE_UNITS)
                   - set(["whole", "newest", "container", "map"]))
    # A `newest` row is ONE key: its sides are ordered by that value's own moment,
    # and two keys in one row would make one key's moment decide the other's.
    groups = [row for row in M.MERGE_UNITS if len(row[1]) > 1 and row[2] != "whole"]
    reasons = [row for row in M.MERGE_UNITS if not (row[3] or "").strip()]
    check("wv15 ...and no row names a key the schema does not declare for that kind, "
          "none is named twice but by two whole rows, every verdict is one of the four "
          "words, only a whole value groups sibling keys, and every row carries its "
          "reason; stale %r, twice %r, vocabulary %r, groups %r, no reason %r"
          % (stale, twice, vocab, groups, reasons),
          not (stale or twice or vocab or groups or reasons))
    mapped = [(lst, name, M.ELEMENT_KINDS.get(lst)) for lst, name in elements
              if M.ELEMENT_KINDS.get(lst) != name]
    aliased = sorted(set((c, n, M.REF_KINDS.get(c)) for c, n in refs
                         if M.REF_KINDS.get(c) != n)
                     | set((c, None, n) for c, n in M.REF_KINDS.items()
                           if (c, n) not in refs))
    check("wv16 ...and the record kind the merge gives each keyed list's elements, and "
          "each record a container holds (a parked phase), is the definition the "
          "schema names; disagreeing: %r %r" % (mapped, aliased),
          mapped == [] and elements and aliased == [] and refs)
    accounts = dict(((row[0], row[1]), row[2]) for row in M.MERGE_UNITS)
    owed = [("task", ("lastRun", "testEvidence")), ("phase", ("lastRun", "testEvidence")),
            ("phase", ("ci",)), ("phase", ("mergedAt", "mergedHead", "mergedHeadAt")),
            ("phase.review", ("status", "outcome", "noEvidenceReason", "readReturns",
                              "acceptedCommits")),
            ("task", ("intentCheck",)),
            ("task", ("status", "startedAt", "attempts", "blockedReason")),
            ("task", ("status", "commit", "completedAt", "outcome", "verifiedBy",
                      "redFirst"))]
    # A base-red record and the base runs kept with it sit INSIDE a run record, so
    # they are whole with it: the walk must never reach into a run.
    walked_runs = sorted(k for k in kinds if k.endswith(".lastRun")
                         or k.endswith(".testEvidence"))
    check("wv17 ...and the accounts the task names are whole: a run record with its "
          "pointer at both scopes (its base-red record and base runs inside it), a CI "
          "record, a merge stamp with its head, a sign-off's verdict, a review verdict, "
          "a red-first proof and a task's close with the status it moved; not whole: "
          "%r, walked into: %r"
          % ([o for o in owed if accounts.get(o) != "whole"], walked_runs),
          all(accounts.get(o) == "whole" for o in owed) and walked_runs == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_merge.py --selftest\n")
    raise SystemExit(2)
