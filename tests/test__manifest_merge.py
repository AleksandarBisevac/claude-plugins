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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_merge.py --selftest\n")
    raise SystemExit(2)
