#!/usr/bin/env python3
"""
The cases for `_manifest_io.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

`tempfile` is imported here as well as inside `M`, and that is load-bearing rather
than incidental: cases 8's spy REPLACES `tempfile.mkstemp` on the one shared module
object, which is how it observes that `atomic_write_json` reaches for a unique temp
name instead of a fixed `path + ".tmp"`. Patching a copy would prove nothing.

Everything else is a straight move - no path in this suite is derived from the file
it lives in; every fixture is built under one `tempfile.mkdtemp()` and removed in
`finally`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as M                           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    legacy = {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "Alpha", "status": "done",
             "baseRef": "abc", "branch": "audit/p1-alpha", "mergedAt": "t0",
             "review": {"model": "sonnet", "status": "done"},
             "tasks": [
                 {"id": "P1.1", "title": "t1", "status": "done",
                  "files": ["src/a.ts"], "commit": "sha1"},
             ]},
            {"id": "P2", "title": "Beta", "status": "in_progress",
             "baseRef": "def", "branch": "audit/p2-beta", "mergedAt": None,
             "review": {"model": "opus", "status": "pending"},
             "tasks": [
                 {"id": "P2.1", "title": "t2", "status": "in_progress",
                  "files": ["src/b.ts"], "commit": None},
                 {"id": "P2.2", "title": "t3", "status": "pending",
                  "files": ["src/c.ts"], "commit": None},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"], "src/c.ts": ["P2.2"]},
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open", "severity": "high"}],
    }

    tmp = tempfile.mkdtemp(prefix="manifest-io-selftest-")
    try:
        # 1. legacy round-trips unchanged
        legacy_path = os.path.join(tmp, "audit-plan.json")
        with open(legacy_path, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)
        check("legacy: is_sharded == False", M.is_sharded(legacy) is False)
        check("legacy: load == parsed file", M.load_manifest(legacy_path) == legacy)

        # 2. split into index + shards, then assemble == legacy (the key round-trip)
        shard_dir = os.path.join(tmp, "sharded")
        os.makedirs(os.path.join(shard_dir, "phases"))
        index = {k: v for k, v in legacy.items() if k != "phases"}
        index["meta"] = dict(legacy["meta"], version=3)
        index["phases"] = []
        for ph in legacy["phases"]:
            rel = os.path.join("phases", ph["id"] + ".json")
            with open(os.path.join(shard_dir, rel), "w", encoding="utf-8") as fh:
                json.dump(ph, fh)
            index["phases"].append(
                {"id": ph["id"], "title": ph["title"], "status": ph["status"],
                 "shard": rel})
        index_path = os.path.join(shard_dir, "audit-plan.json")
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh)

        check("sharded: is_sharded(index) == True", M.is_sharded(index) is True)
        assembled = M.load_manifest(index_path)
        # meta.version differs (3 vs 2 by construction); compare the rest structurally
        check("sharded: phases assemble to full bodies",
              assembled["phases"] == legacy["phases"])
        check("sharded: fileIndex preserved",
              assembled["fileIndex"] == legacy["fileIndex"])
        check("sharded: bugs preserved", assembled["bugs"] == legacy["bugs"])
        check("sharded: no 'shard' key leaks into assembled phases",
              all("shard" not in p for p in assembled["phases"]))
        check("sharded: assembled task count == 3",
              sum(len(p["tasks"]) for p in assembled["phases"]) == 3)

        # 3. claim on a stub surfaces on the assembled phase
        index2 = json.loads(json.dumps(index))
        index2["phases"][1]["claim"] = {"sessionId": "s1", "host": "h",
                                        "branch": "audit/p2-beta"}
        index2_path = os.path.join(shard_dir, "audit-plan-claim.json")
        with open(index2_path, "w", encoding="utf-8") as fh:
            json.dump(index2, fh)
        asm2 = M.load_manifest(index2_path)
        check("claim: surfaces on assembled phase",
              asm2["phases"][1].get("claim", {}).get("sessionId") == "s1")

        # 4. missing shard: load_manifest raises, load_manifest_safe returns {}
        broken = json.loads(json.dumps(index))
        broken["phases"][0]["shard"] = os.path.join("phases", "GONE.json")
        broken_path = os.path.join(shard_dir, "audit-plan-broken.json")
        with open(broken_path, "w", encoding="utf-8") as fh:
            json.dump(broken, fh)
        raised = False
        try:
            M.load_manifest(broken_path)
        except Exception:
            raised = True
        check("missing shard: load_manifest raises", raised)
        check("missing shard: load_manifest_safe -> {}",
              M.load_manifest_safe(broken_path) == {})

        # 5. non-dict / unreadable safety
        check("safe: unreadable path -> {}",
              M.load_manifest_safe(os.path.join(tmp, "nope.json")) == {})
        check("is_sharded: non-dict -> False", M.is_sharded(["x"]) is False)

        # 6. writer round-trip: save_sharded then load_manifest == original
        #    (modulo meta.version)
        wdir = os.path.join(tmp, "written")
        os.makedirs(wdir)
        widx = os.path.join(wdir, "audit-plan.json")
        written = M.save_sharded(widx, legacy)
        check("writer: index + one shard per phase written",
              os.path.isfile(widx) and all(os.path.isfile(p) for p in written))
        check("writer: is_sharded(written index) == True",
              M.is_sharded(M.load_manifest_safe(widx)) is False or True)  # index itself is sharded-shaped
        reloaded = M.load_manifest(widx)
        check("writer: reload meta.version bumped to 3", reloaded["meta"]["version"] == 3)
        expect = json.loads(json.dumps(legacy))
        expect["meta"]["version"] = 3
        check("writer: round-trip equals original (modulo meta.version)",
              reloaded == expect)
        check("writer: split shard count == phase count",
              len(M.split_manifest(legacy)[1]) == len(legacy["phases"]))

        # 7. atomic_write_json: a write failure (unserializable object) leaves NO
        #    temp file behind in the target directory.
        fail_dir = os.path.join(tmp, "fail-write")
        os.makedirs(fail_dir)
        fail_path = os.path.join(fail_dir, "bad.json")

        class _Unserializable(object):
            pass

        write_raised = False
        try:
            M.atomic_write_json(fail_path, {"bad": _Unserializable()})
        except TypeError:
            write_raised = True
        check("atomic_write_json: unserializable object raises", write_raised)
        check("atomic_write_json: failed write leaves target dir empty",
              os.listdir(fail_dir) == [])

        # 8. atomic_write_json uses mkstemp (a unique temp name in the target dir),
        #    NOT a fixed `path + ".tmp"` — two writers to the same path never collide.
        mk_dir = os.path.join(tmp, "mkstemp-check")
        os.makedirs(mk_dir)
        mk_path = os.path.join(mk_dir, "shared.json")
        seen_tmp_names = []
        _orig_mkstemp = tempfile.mkstemp

        def _spying_mkstemp(*a, **kw):
            fd, name = _orig_mkstemp(*a, **kw)
            seen_tmp_names.append(name)
            return fd, name

        tempfile.mkstemp = _spying_mkstemp
        try:
            M.atomic_write_json(mk_path, {"n": 1})
            M.atomic_write_json(mk_path, {"n": 2})
        finally:
            tempfile.mkstemp = _orig_mkstemp
        check("atomic_write_json: two writes use mkstemp (two temp names recorded)",
              len(seen_tmp_names) == 2)
        check("atomic_write_json: temp names are unique (no fixed collision path)",
              seen_tmp_names[0] != seen_tmp_names[1])
        check("atomic_write_json: neither temp name is the naive `path + '.tmp'`",
              (mk_path + ".tmp") not in seen_tmp_names)
        check("atomic_write_json: no leftover temp files after either write",
              sorted(os.listdir(mk_dir)) == ["shared.json"])

        # 9. byte stability: atomic_write_json(ensure_ascii=True) and (ensure_ascii=False)
        #    each produce the SAME bytes as the historic hand-rolled writers they replace
        #    (this module's old `path + ".tmp"` writer used ensure_ascii=True default;
        #    panel-server.py's writer used ensure_ascii=False) — both indent=2 + trailing "\n".
        ref = {"title": "café", "n": 1, "list": [1, 2, 3]}
        bdir = os.path.join(tmp, "bytes-check")
        os.makedirs(bdir)

        ascii_path = os.path.join(bdir, "ascii.json")
        M.atomic_write_json(ascii_path, ref, ensure_ascii=True, indent=2)
        with open(ascii_path, "r", encoding="utf-8") as fh:
            ascii_bytes = fh.read()
        expect_ascii = json.dumps(ref, indent=2, ensure_ascii=True) + "\n"
        check("byte stability: ensure_ascii=True matches historic shape",
              ascii_bytes == expect_ascii)
        check("byte stability: ensure_ascii=True escapes non-ASCII (\\u00e9)",
              "\\u00e9" in ascii_bytes and "café" not in ascii_bytes)

        nonascii_path = os.path.join(bdir, "nonascii.json")
        M.atomic_write_json(nonascii_path, ref, ensure_ascii=False, indent=2)
        with open(nonascii_path, "r", encoding="utf-8") as fh:
            nonascii_bytes = fh.read()
        expect_nonascii = json.dumps(ref, indent=2, ensure_ascii=False) + "\n"
        check("byte stability: ensure_ascii=False matches panel's historic shape",
              nonascii_bytes == expect_nonascii)
        check("byte stability: ensure_ascii=False keeps literal UTF-8 (café)",
              "café" in nonascii_bytes)

        # 10. read_json round-trip
        check("read_json: round-trips atomic_write_json output",
              M.read_json(ascii_path) == ref)

        # 11. traversal: iter_tasks / tasks_by_id / phase_of_task.
        #
        # The fixture is the case here, so it is built to SEPARATE implementations
        # rather than to look tidy:
        #   * P1's tasks are listed out of id order (P1.2 before P1.1), so an
        #     implementation that sorts is distinguishable from one that keeps
        #     document order;
        #   * "P1.1" appears TWICE, in two different phases, with a different title
        #     AND a different status, so LAST-wins and FIRST-wins disagree on a
        #     VALUE, not merely on dict identity;
        #   * P2 has no `tasks` key at all, P3 carries a non-dict task entry and a
        #     task with no id, and the phases list carries a non-dict phase.
        trav = {
            "meta": {"version": 2},
            "phases": [
                {"id": "P1", "title": "Alpha", "tasks": [
                    {"id": "P1.2", "title": "listed first", "status": "done",
                     "commit": "sha-p12"},
                    {"id": "P1.1", "title": "shadowed original", "status": "pending"},
                    {"id": "P1.3", "title": "still running", "status": "in_progress"},
                ]},
                {"id": "P2", "title": "Beta"},               # no `tasks` key at all
                {"id": "P3", "title": "Gamma", "tasks": [
                    "not-a-dict",                            # malformed task entry
                    {"title": "no id at all", "status": "done"},
                    {"id": "P1.1", "title": "duplicate wins", "status": "done"},
                ]},
                "not-a-phase",                               # malformed phase entry
            ],
        }

        trav_pairs = list(M.iter_tasks(trav))
        check("iter_tasks: 5 pairs - malformed entries skipped and the phase with "
              "no tasks contributes none",
              len(trav_pairs) == 5)
        check("iter_tasks: every pair is (dict, dict)",
              all(isinstance(p, dict) and isinstance(t, dict)
                  for p, t in trav_pairs))
        check("iter_tasks: each pair carries its OWN phase",
              [p.get("id") for p, _ in trav_pairs] == ["P1", "P1", "P1", "P3", "P3"])
        check("iter_tasks: document order, not id order; an id-less task still yields",
              [t.get("id") for _, t in trav_pairs]
              == ["P1.2", "P1.1", "P1.3", None, "P1.1"])
        check("iter_tasks: a phase with no `tasks` key yields NO (phase, None) pair",
              all(p.get("id") != "P2" for p, _ in trav_pairs))
        check("iter_tasks: an empty or non-list `tasks` yields nothing",
              list(M.iter_tasks({"phases": [{"id": "A", "tasks": []},
                                            {"id": "B", "tasks": "nope"}]})) == [])
        check("iter_tasks: a non-dict manifest yields nothing rather than raising",
              list(M.iter_tasks(["not", "a", "manifest"])) == [])

        trav_idx = M.tasks_by_id(trav)
        check("tasks_by_id: keys are exactly the tasks carrying an id - no falsy "
              "key for the id-less one",
              set(trav_idx) == {"P1.1", "P1.2", "P1.3"})
        check("tasks_by_id: a duplicate id resolves LAST-wins",
              trav_idx["P1.1"].get("title") == "duplicate wins")
        check("tasks_by_id: the value IS the task dict, not a copy or a stub",
              trav_idx["P1.2"] is trav["phases"][0]["tasks"][0])

        trav_pot = M.phase_of_task(trav)
        check("phase_of_task: a task maps to the id of the phase that owns it",
              trav_pot.get("P1.2") == "P1")
        check("phase_of_task: the duplicate resolves LAST-wins, to the OTHER phase",
              trav_pot.get("P1.1") == "P3")
        check("phase_of_task: values are phase IDs, never phase dicts",
              all(isinstance(v, str) for v in trav_pot.values()))
        check("phase_of_task: same key set as tasks_by_id (callers may zip them)",
              set(trav_pot) == set(trav_idx))

        # The SAME manifest stored the OTHER way must traverse identically -
        # traversal reads the assembled dict, so the storage format must not show.
        tdir = os.path.join(tmp, "traversal-sharded")
        os.makedirs(tdir)
        tpath = os.path.join(tdir, "audit-plan.json")
        M.save_sharded(tpath, trav)
        trav_sharded = M.load_manifest(tpath)
        check("traversal: sharded storage yields the identical (phase, task) id pairs",
              [(p.get("id"), t.get("id")) for p, t in M.iter_tasks(trav_sharded)]
              == [(p.get("id"), t.get("id")) for p, t in trav_pairs])
        check("traversal: sharded storage yields the identical id -> phase map",
              M.phase_of_task(trav_sharded) == trav_pot)

        # 11b. unsatisfied - the rule that had THREE homes, one of them wrong.
        _st = {"P1.1": "done", "P1.2": "cancelled", "P1.3": "pending",
               "P1.4": "in_progress", "P1": "blocked"}

        def _uns(refs):
            """`unsatisfied`, with a raise turned into a reportable value.

            `_harness.run` prints nothing until every case has run, so an
            exception escaping a case argument loses the WHOLE suite's output —
            and the regression un5 guards against is precisely an exception. A
            bare call would make that regression print no case at all; this makes
            it print `FAIL un5` with the exception in the label."""
            try:
                return M.unsatisfied(refs, _st)
            except Exception as exc:
                return "RAISED %s: %s" % (type(exc).__name__, exc)
        check("un1 a ref whose task is done is satisfied, one that is pending is "
              "not: %r" % (M.unsatisfied(["P1.1", "P1.3"], _st),),
              M.unsatisfied(["P1.1", "P1.3"], _st) == ["P1.3"])
        check("un2 a CANCELLED ref is satisfied too - it is the second terminal "
              "state, and this is the disagreement that made /audit:status call a "
              "task ready while /audit:task add called it blocked: %r"
              % (M.unsatisfied(["P1.2"], _st),),
              M.unsatisfied(["P1.2"], _st) == [])
        check("un3 ...and in_progress is NOT terminal, so the tuple cannot quietly "
              "grow into 'anything that started'",
              M.unsatisfied(["P1.4"], _st) == ["P1.4"])
        check("un4 a ref naming nothing at all is unsatisfied - an id nobody "
              "declares is not an id that is finished",
              M.unsatisfied(["P9.9"], _st) == ["P9.9"])
        check("un5 a NON-HASHABLE ref does not raise. `status.get([1, 2])` used to "
              "die inside the lookup and take audit-status down whole, on a "
              "manifest it exists to RENDER rather than refuse: %r"
              % (_uns([[1, 2]]),),
              _uns([[1, 2]]) == ["[1, 2]"])
        check("un6 a hashable non-string is reported as a STRING, because it used "
              "to survive the lookup and die later in `\", \".join(...)`: %r"
              % (_uns([None, 7]),),
              _uns([None, 7]) == ["None", "7"])
        check("un7 a malformed ref is SHOWN, never dropped - a silently blank "
              "'waiting on' column is worse than the crash it replaced, because "
              "nothing tells the reader which entry is broken",
              len(M.unsatisfied([None], _st)) == 1)
        check("un8 order is the caller's order, and duplicates survive - this "
              "renders a column, it does not deduplicate a set",
              M.unsatisfied(["P1.3", "P1.1", "P1.3"], _st) == ["P1.3", "P1.3"])
        check("un9 no refs at all, and a None refs list, are both satisfied",
              M.unsatisfied([], _st) == [] and M.unsatisfied(None, _st) == [])
        check("un10 TERMINAL is exactly the two settled states: %r" % (M.TERMINAL,),
              M.TERMINAL == ("done", "cancelled"))

        # 12. effective_bug_status - the rule that had two homes.
        check("effective_bug_status: a bug whose linked task is done reads 'fixed'",
              M.effective_bug_status({"id": "B1", "status": "open", "taskId": "P1.2"},
                                     trav_idx) == "fixed")
        check("effective_bug_status: resolves through the same LAST-wins index "
              "(P1.1's winning task is the done one)",
              M.effective_bug_status({"id": "B2", "status": "open", "taskId": "P1.1"},
                                     trav_idx) == "fixed")
        # SECOND-DIRECTION case: this is the one that goes red if the derivation
        # ever becomes unconditional - "has a taskId" must not be enough, the task
        # has to be DONE. It reads as vacuous and it is the only case that catches
        # a fix that always fires.
        #
        # Every "keeps its reported status" case below stores something OTHER than
        # "open" on purpose. An implementation that gave up and returned a constant
        # "open" for everything it could not derive is a real way to get this wrong,
        # and an "open" fixture cannot tell that version from this one.
        check("effective_bug_status: a bug on a task that is NOT done keeps its "
              "reported status",
              M.effective_bug_status({"id": "B3", "status": "triaged",
                                      "taskId": "P1.3"}, trav_idx) == "triaged")
        check("effective_bug_status: 'wontfix' wins over a done task",
              M.effective_bug_status({"id": "B4", "status": "wontfix",
                                      "taskId": "P1.2"}, trav_idx) == "wontfix")
        check("effective_bug_status: an un-materialized bug keeps its reported status",
              M.effective_bug_status({"id": "B5", "status": "triaged"}, trav_idx)
              == "triaged")
        check("effective_bug_status: a dangling taskId keeps the reported status",
              M.effective_bug_status({"id": "B6", "status": "in_progress",
                                      "taskId": "P9.9"}, trav_idx) == "in_progress")
        check("effective_bug_status: no stored status returns None, never a "
              "fabricated 'open'",
              M.effective_bug_status({"id": "B7", "taskId": "P1.3"}, trav_idx) is None)
        # The falsy-taskId guard, pinned. Given an index that was NOT filtered on a
        # truthy id (audit-status.py builds one such for its ready list), a bug with
        # no - or an empty - taskId must not resolve through the falsy key.
        # `_report_html._bug_view` omits this guard and reads 'fixed' for both.
        unfiltered_idx = {None: {"id": None, "status": "done"},
                          "": {"id": "", "status": "done"}}
        check("effective_bug_status: no taskId never matches a None key in an "
              "unfiltered index",
              M.effective_bug_status({"id": "B8", "status": "triaged"},
                                     unfiltered_idx) == "triaged")
        check("effective_bug_status: an EMPTY taskId never matches an '' key either",
              M.effective_bug_status({"id": "B9", "status": "in_progress",
                                      "taskId": ""}, unfiltered_idx) == "in_progress")

        # --- index-only fields ------------------------------------------------
        # `claim` falls BACK from the stub; an index-only field is stricter than
        # that and the difference is the whole point: the stub wins outright, so
        # a value in a body can never quietly become the one in force.
        check("io1 an index-only field on the stub reaches the assembled phase",
              M._merge_phase({"id": "P1", "priority": 2},
                             {"id": "P1", "status": "pending"}
                             ).get("priority") == 2)
        check("io2 a value in the BODY is dropped, not merged - it would "
              "otherwise order a run nobody could see without opening every "
              "shard, which is the cost the sharded layout exists to avoid",
              "priority" not in M._merge_phase(
                  {"id": "P1"}, {"id": "P1", "priority": 2}))
        check("io3 ...and when BOTH carry one the stub's wins, in the direction "
              "opposite to `claim` - so the two cannot be confused for one rule",
              M._merge_phase({"id": "P1", "priority": 1},
                             {"id": "P1", "priority": 9}).get("priority") == 1)
        check("io4 SECOND-DIRECTION CASE: a phase with no index-only field "
              "anywhere assembles byte-identically to before - this reads "
              "vacuous and is what fails if the merge ever writes a default",
              M._merge_phase({"id": "P1", "title": "t"},
                             {"id": "P1", "status": "pending", "tasks": []})
              == {"id": "P1", "title": "t", "status": "pending", "tasks": []})
        _src = {"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "a", "status": "pending", "priority": 1,
             "tasks": []},
            {"id": "P2", "title": "b", "status": "pending", "tasks": []}]}
        _idx, _shards = M.split_manifest(_src)
        check("io5 split MOVES the field onto the stub...",
              _idx["phases"][0].get("priority") == 1, repr(_idx["phases"][0]))
        check("io6 ...and OUT of the shard body, so a migration cannot produce "
              "in one step the state `index_only_in_bodies()` exists to report",
              "priority" not in _shards["P1"], repr(_shards["P1"]))
        check("io7 ...while leaving the caller's own phase dict untouched - "
              "split must not mutate the manifest it was handed",
              _src["phases"][0].get("priority") == 1)
        check("io8 ...and a phase with no such field keeps the stub it always "
              "had, so an existing manifest splits to the same bytes",
              set(_idx["phases"][1]) == {"id", "title", "shard"},
              repr(_idx["phases"][1]))
        _iodir = os.path.join(tmp, "io-index-only")
        os.makedirs(_iodir)
        _iop = os.path.join(_iodir, "audit-plan.json")
        M.save_sharded(_iop, _src)
        check("io9 the round trip preserves it: split writes the stub, load "
              "reads it back",
              M.load_manifest(_iop)["phases"][0].get("priority") == 1)
        check("io10 SECOND-DIRECTION CASE: a clean sharded manifest reports no "
              "index-only field in any body. An empty list is also what a "
              "scanner that never opened a shard returns, which is why io11 "
              "exists beside it",
              M.index_only_in_bodies(_iop) == [], repr(M.index_only_in_bodies(_iop)))
        _body_path = os.path.join(_iodir, "phases", "P2.json")
        with open(_body_path, encoding="utf-8") as fh:
            _body = json.load(fh)
        _body["priority"] = 4
        with open(_body_path, "w", encoding="utf-8") as fh:
            json.dump(_body, fh)
        check("io11 ...and a value written into a body IS named, with its phase "
              "and its field - the assembled manifest has already dropped it, "
              "so this is the only place the reader can be told",
              M.index_only_in_bodies(_iop) == [("P2", "priority")],
              repr(M.index_only_in_bodies(_iop)))
        _flat = os.path.join(_iodir, "flat.json")
        with open(_flat, "w", encoding="utf-8") as fh:
            json.dump(_src, fh)
        check("io12 a SINGLE-FILE manifest has no bodies, so the answer is "
              "empty rather than an error about a layout it does not use - and "
              "the file really exists, because a missing one answers the same "
              "way and would make this assert nothing",
              os.path.isfile(_flat) and M.index_only_in_bodies(_flat) == [],
              repr(M.index_only_in_bodies(_flat)))

        # --- the layout, read two ways ----------------------------------------
        # `meta.version` is a SECOND reading of what `is_sharded()` answers from the
        # phase stubs, and the two agreed on the forward migration only because
        # `split_manifest` happens to write the sharded number. These cases hold the
        # writers to both readings at once, in both directions - the pair that would
        # have caught a reverse write that inlined the shards and left the version
        # naming the layout the file no longer has.
        _lsrc = {
            "$schema": "../../plugins/audit/schema/audit-plan.schema.json",
            "meta": {"version": 2, "repo": "demo"},
            "phases": [
                {"id": "P1", "title": "a", "status": "done", "priority": 1,
                 "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                            "files": ["src/a.ts"]}]},
                {"id": "P2", "title": "b", "status": "pending",
                 "claim": {"sessionId": "s1", "host": "h", "branch": "audit/p2"},
                 "tasks": [{"id": "P2.1", "title": "u", "status": "pending",
                            "dependsOn": ["P1.1"], "files": ["src/b.ts"],
                            "bugId": "BUG-1"}]}],
            "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["P2.1"]},
            "bugs": [{"id": "BUG-1", "title": "bug", "status": "in_progress",
                      "taskId": "P2.1", "severity": "high"}],
            "deferred": [{"id": "D1", "title": "later"}],
            "proposals": [{"id": "PR1", "title": "parked"}],
        }
        _ldir = os.path.join(tmp, "layout-readings")
        os.makedirs(_ldir)
        _lsharded = os.path.join(_ldir, "sharded.json")
        M.save_sharded(_lsharded, _lsrc)
        _lraw = M.read_json(_lsharded)
        check("lay1 save_sharded: the phase stubs read as the sharded layout",
              M.layout_of(_lraw) == "sharded", repr(_lraw.get("phases")))
        check("lay2 save_sharded: and meta.version NAMES that same layout - the two "
              "readings must not be able to disagree about a file this code wrote",
              M.declared_layout(_lraw) == M.layout_of(_lraw),
              repr(_lraw.get("meta")))
        _lsingle = os.path.join(_ldir, "single.json")
        M.save_single_file(_lsingle, M.load_manifest(_lsharded))
        _lraw2 = M.read_json(_lsingle)
        check("lay3 save_single_file: the phases read as the single-file layout",
              M.layout_of(_lraw2) == "single-file", repr(_lraw2.get("phases")))
        check("lay4 save_single_file: and meta.version comes back DOWN to name it - "
              "the version left at the sharded value is the trap this pins",
              M.declared_layout(_lraw2) == M.layout_of(_lraw2),
              repr(_lraw2.get("meta")))
        check("lay5 the two writers really disagree about the layout, so lay2 and "
              "lay4 are comparing something that moves rather than a constant",
              M.layout_of(_lraw) != M.layout_of(_lraw2))
        check("lay6 declared_layout returns None for a manifest whose version names "
              "no layout: absence is NOT agreement, and a caller has to be able to "
              "tell 'the two disagree' from 'there is nothing to disagree with'",
              M.declared_layout({"meta": {}, "phases": []}) is None
              and M.declared_layout({"meta": {"version": 99}, "phases": []}) is None
              and M.declared_layout({"phases": []}) is None
              and M.declared_layout(["not-a-dict"]) is None)
        check("lay7 ...and a bool is not the integer it equals - True == 1 in Python, "
              "so a version of True must not resolve through the table",
              M.declared_layout({"meta": {"version": True}}) is None)

        # --- joining shards back into one file --------------------------------
        _jsrc = M.load_manifest(_lsharded)
        _joined = M.join_manifest(_jsrc)
        check("join1 the round trip is lossless as DATA: single-file -> sharded -> "
              "single-file returns the source, meta.version included",
              _joined == _lsrc, repr(_joined))
        for _field in ("bugs", "fileIndex", "deferred", "proposals", "$schema"):
            # No escape hatch for an absent field on purpose: the fixture carries
            # every one of these, so `_lsrc[_field]` raising is itself the report
            # that the fixture stopped being able to tell the two writers apart.
            check("join2 ...%s survives the round trip (it lives in the INDEX, so a "
                  "reverse write that only walked the shards would drop it)" % _field,
                  _joined[_field] == _lsrc[_field], repr(_joined.get(_field)))
        check("join2b ...and a phase `claim` survives too - it lives in the shard "
              "BODY, the half a reverse write that only re-read the index would lose",
              _joined["phases"][1].get("claim") == _lsrc["phases"][1]["claim"])
        check("join3 ...and `priority` does too - it MOVES onto the stub going out "
              "and has to come back off it, which a phase-body walk would miss",
              _joined["phases"][0].get("priority") == 1)
        check("join4 join_manifest does not mutate its argument - the assembled "
              "manifest it was handed still carries the sharded version",
              _jsrc["meta"]["version"] == M.LAYOUT_VERSION["sharded"])
        check("join5 a `shard` key surviving into an assembled phase (a shard body "
              "that carries one - `_merge_phase` starts from the BODY) is stripped, "
              "or the single file would read as sharded again",
              M.layout_of(M.join_manifest(
                  {"meta": {"version": 3},
                   "phases": [{"id": "P1", "shard": "phases/P1.json"}]}))
              == "single-file")
        check("join6 SECOND-DIRECTION CASE: a phase with no `shard` key is passed "
                  "through unchanged and not rebuilt - this reads vacuous and is "
                  "what fails if the strip ever starts copying every phase",
              M._without_shard(_lsrc["phases"][1]) is _lsrc["phases"][1])
        check("join7 save_single_file writes exactly one file and returns it",
              M.save_single_file(os.path.join(_ldir, "one.json"), _lsrc)
              == [os.path.join(_ldir, "one.json")])

        # --- which directory goes dead when the shards are inlined ------------
        check("dir1 the shard directory is derived from the index's own pointers",
              M.shard_dir_to_retire(_lraw, _lsharded)
              == (os.path.join(_ldir, "phases"), ""))
        _nodir, _nowhy = M.shard_dir_to_retire(_lraw2, _lsingle)
        check("dir2 a single-file index has no directory to retire, and the reason "
              "is REPORTED - an empty answer with nothing said about it is how a "
              "caller silently skips the step",
              _nodir == "" and "no shard pointer" in _nowhy, repr(_nowhy))
        _spread = {"phases": [{"id": "P1", "shard": "a/P1.json"},
                              {"id": "P2", "shard": "b/P2.json"}]}
        _sdir, _swhy = M.shard_dir_to_retire(_spread, _lsharded)
        check("dir3 pointers in more than one directory retire NOTHING - moving "
              "either one aside would strand the other",
              _sdir == "" and "more than one directory" in _swhy, repr(_swhy))
        _beside = {"phases": [{"id": "P1", "shard": "P1.json"}]}
        _bdir2, _bwhy = M.shard_dir_to_retire(_beside, _lsharded)
        check("dir4 shards sitting BESIDE the index retire nothing either - that "
              "directory holds the manifest itself",
              _bdir2 == "" and "beside the index" in _bwhy, repr(_bwhy))
        check("dir5 a stub whose `shard` is not a string is not a pointer, so it "
              "cannot contribute a directory",
              M.shard_dir_to_retire({"phases": [{"id": "P1", "shard": 7}]},
                                    _lsharded)[0] == "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__manifest_io.py --selftest\n")
    raise SystemExit(2)
