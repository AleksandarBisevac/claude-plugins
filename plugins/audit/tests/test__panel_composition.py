#!/usr/bin/env python3
"""
The cases for `_panel_composition.py` - the plan as the panel shows it:
phase/task rows, bug rows, the ADO honesty banner and the areas registry.

Moved out of `test__panel_state.py` at U3.1, with the code it covers. `M` is the
module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402  (as the module imports it)
import _panel_paths as _paths                     # noqa: E402  (the shared base)
import _panel_composition as M      # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import pathlib                                 # noqa: F401  (used by moved cases)
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer -- straight through `_manifest_io`,
        the implementation panel-server's `_atomic_write_json` delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-composition-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(_paths._config_path(proj), {"trivialLineThreshold": 40})
    mpath = _paths._manifest_path(proj, _paths.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    check("_areas_of normalizes string/list/absent",
          M._areas_of("x") == ["x"] and M._areas_of(["a", "b"]) == ["a", "b"]
          and M._areas_of(None) == [])
    # --- v0.37 B1: the three skill states, as the panel payload carries them ----
    # Explicit null is an ANSWER ("none applies" — it stops the area fallback)
    # and the view must ship it AS null; flattening it to [] made the opt-out
    # indistinguishable from "unconsidered" on every panel surface.
    check("_skills_of keeps the three states apart: null stays None, absent "
          "and junk read as []",
          M._skills_of({"skills": None}) is None
          and M._skills_of({}) == []
          and M._skills_of({"skills": "x"}) == []
          and M._skills_of({"skills": ["a"]}) == ["a"])
    _cv3 = M._composition_view({
        "meta": {"areas": {"api": {"root": "src", "skills": ["conv", "sec"]},
                           "web": {"root": "w", "skills": ["conv"]}}},
        "phases": [{"id": "PX", "title": "p", "status": "pending",
                    "tasks": [{"id": "PX.1", "title": "t", "status": "pending",
                               "skills": None}]}]})
    check("the composition view ships the opt-out as null, not as []",
          _cv3["tasks"][0]["skills"] is None)
    check("...and carries the area-declared skill names, deduped, so the "
          "client's inventory hint sees every name the manifest spells",
          _cv3.get("areaSkills") == ["conv", "sec"])

    # --- connector v2: the ADO card's read side ---------------------------------
    # adoStatus is MANIFEST EVIDENCE only (links /audit:sync wrote) — the panel
    # reports what the file proves, never what the connector claims; the policy
    # tab's rule, applied to a second feature. No network in the panel, ever.
    check("the composition view ships meta.ado verbatim - the card's form source",
          M._composition_view({"meta": {"ado": {"organization": "o"}},
                             "phases": []})["meta"]["ado"]
          == {"organization": "o"})
    _as1 = M._ado_status({"meta": {}, "phases": []})
    check("adoStatus: an unconfigured manifest reads configured=false, "
          "nothing linked, no effective switches",
          _as1 == {"configured": False, "enabled": False, "echo": False,
                   "linked": {"tasks": 0, "bugs": 0, "phases": 0},
                   "lastSyncedAt": None})
    _as2 = M._ado_status({"meta": {"ado": {"organization": "o",
                                         "enabled": False}}, "phases": []})
    check("adoStatus: enabled:false reads off (echo effectively off too) "
          "while staying configured",
          _as2["configured"] is True and _as2["enabled"] is False
          and _as2["echo"] is False)
    _as3 = M._ado_status({"meta": {"ado": {"organization": "o"}}, "phases": []})
    check("adoStatus: absent switches read as their defaults - enabled on, "
          "echo on",
          _as3["configured"] is True and _as3["enabled"] is True
          and _as3["echo"] is True
          and _as3["linked"] == {"tasks": 0, "bugs": 0, "phases": 0})
    _as4 = M._ado_status({
        "meta": {"ado": {"organization": "o", "echo": False}},
        "phases": [{"id": "P1", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-02T00:00:00Z"},
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "ado": {"id": 7,
                                       "lastSyncedAt": "2026-08-03T00:00:00Z"}},
                              {"id": "P1.2", "title": "t", "status": "pending",
                               "ado": "junk"}]}],
        "bugs": [{"id": "BUG-1", "title": "b", "status": "open",
                  "ado": {"id": 8, "lastSyncedAt": "2026-08-01T00:00:00Z"}},
                 {"id": "BUG-2", "title": "b", "status": "open",
                  "ado": {"id": "x"}}]})
    check("adoStatus: linked counts by kind with junk shapes skipped "
          "(int ids only), the newest lastSyncedAt wins, echo:false honoured",
          _as4["linked"] == {"tasks": 1, "bugs": 1, "phases": 1}
          and _as4["lastSyncedAt"] == "2026-08-03T00:00:00Z"
          and _as4["echo"] is False and _as4["enabled"] is True)
    check("the composition view carries adoStatus (and a manifest with no "
          "meta.ado still gets the full shape)",
          M._composition_view({"meta": {}, "phases": []})
          .get("adoStatus", {}).get("configured") is False)
    # _as5 pins why the phase half of this walk is NOT `_mio.iter_tasks`: a phase
    # /audit:sync has pushed but nobody has broken into tasks yet still carries a
    # link and a timestamp, and `iter_tasks` yields nothing at all for it. The
    # fixture puts the NEWEST timestamp on that phase so a version that dropped it
    # gets both the count AND lastSyncedAt wrong — a same-or-older stamp there
    # would let the two versions agree on the second half by accident.
    _as5 = M._ado_status({
        "meta": {"ado": {"organization": "o"}},
        "phases": [{"id": "P1", "title": "linked, no tasks yet",
                    "status": "pending",
                    "ado": {"id": 4, "lastSyncedAt": "2026-08-09T00:00:00Z"}},
                   {"id": "P2", "title": "p", "status": "pending",
                    "ado": {"id": 9, "lastSyncedAt": "2026-08-01T00:00:00Z"},
                    "tasks": [
                       {"id": "P2.1", "title": "t", "status": "pending",
                        "ado": {"id": 5,
                                "lastSyncedAt": "2026-08-04T00:00:00Z"}}]}]})
    check("adoStatus: a phase with a link and NO tasks is still counted, and "
          "still wins lastSyncedAt",
          _as5["linked"] == {"tasks": 1, "bugs": 0, "phases": 2}
          and _as5["lastSyncedAt"] == "2026-08-09T00:00:00Z")

    # _bugs_view: the bug rows behind the strip. Every derived field is decided in
    # Python by the SAME functions the rollup counts with.
    bm = {"phases": [{"id": "P1", "title": "One", "status": "in_progress", "tasks": [
              {"id": "P1.1", "title": "fix it", "status": "done", "bugId": "BUG-1"},
              {"id": "P1.2", "title": "later", "status": "pending", "bugId": "BUG-2"}]}],
          "bugs": [
              {"id": "BUG-1", "title": "a", "status": "open", "severity": "high",
               "taskId": "P1.1"},
              {"id": "BUG-2", "title": "b", "status": "open", "severity": "critical",
               "taskId": "P1.2"},
              {"id": "BUG-3", "title": "c", "status": "wontfix", "severity": "high"}]}
    bv = M._bugs_view(bm)
    by_id = {b["id"]: b for b in bv}
    check("_bugs_view resolves a bug through its task: fixed when the task is done, "
          "with the stored value kept so it does not read as hand-edited",
          by_id["BUG-1"]["status"] == "fixed" and by_id["BUG-1"]["reported"] == "open"
          and by_id["BUG-2"]["status"] == "open")
    check("_bugs_view names the phase behind the linked task",
          by_id["BUG-1"]["phaseId"] == "P1")
    # A regex in the browser would be a third opinion on 'is this high?' — and the
    # first spelling it would miss is `critical`, which is the one that matters.
    _rup = _paths.status_facts().rollup(bm, [], [])
    check("_bugs_view's open/high agree with the rollup's counts, by construction",
          sum(1 for b in bv if b["open"]) == _rup["bugs"]["open"]
          and sum(1 for b in bv if b["open"] and b["high"])
          == _rup["bugs"]["openHighSeverity"] == 1
          and by_id["BUG-2"]["high"] is True)
    check("_bugs_view on a manifest with no bugs is an empty list, not an error",
          M._bugs_view({"phases": []}) == [])

    # --- v0.28: the areas registry, as GET reports it ---------------------------
    # A sharded fixture on purpose: `meta` lives on the INDEX there, and this
    # endpoint has to read the ASSEMBLED document to see the phases at all.
    _aproj = tempfile.mkdtemp(prefix="state-areas-")
    try:
        _atomic_write_json(M._config_path(_aproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _am = M._manifest_path(_aproj, M.read_config(_aproj))
        os.makedirs(os.path.dirname(_am), exist_ok=True)
        os.makedirs(os.path.join(_aproj, "services", "api"), exist_ok=True)
        _mio.save_sharded(_am, {
            "meta": {"version": 3,
                     "areas": {"api": {"root": "services/api", "description": "d",
                                       "reviewSkill": "backend-review"},
                               "unused": {"root": "services/api"}}},
            "phases": [
                {"id": "P1", "title": "One", "status": "pending", "area": "api",
                 "tasks": [{"id": "P1.1", "title": "T1", "status": "pending"}]},
                {"id": "P2", "title": "Two", "status": "pending", "area": "apu",
                 "tasks": [{"id": "P2.1", "title": "T2", "status": "pending"}]}]})
        _st = M.areas_state(_aproj)
        # `.get` and not `[...]`: a missing tag is exactly what a broken version of
        # this endpoint returns, and a KeyError exits 1 without naming which check
        # noticed — indistinguishable from a suite that crashed for another reason.
        _bytag = {t["tag"]: t for t in _st["tags"]}
        _tag = lambda name: _bytag.get(name) or {}          # noqa: E731
        check("areas GET returns the registry as stored",
              set(_st["areas"]) == {"api", "unused"})
        check("areas GET lists a registered tag with the phases using it",
              _tag("api").get("registered") and _tag("api").get("phases") == ["P1"])
        check("areas GET says a root that exists exists",
              _tag("api").get("rootExists") is True)
        check("areas GET lists a tag no entry covers - the typo case, which "
              "resolves to no reviewer and no skills",
              _tag("apu").get("registered") is False
              and _tag("apu").get("phases") == ["P2"])
        check("areas GET also lists a registered area no phase uses - a rename "
              "done on one side only looks exactly like this",
              _tag("unused").get("registered")
              and _tag("unused").get("phases") == [])
        check("areas GET carries the resolved reviewer of a registered area",
              _tag("api").get("reviewSkill") == "backend-review")
        check("areas GET refuses a manifest path that escapes the project rather "
              "than reading it",
              M.areas_state(os.path.join(_aproj, "nope"))["areas"] == {})
    finally:
        shutil.rmtree(_aproj, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_composition.py --selftest\n")
    raise SystemExit(2)
