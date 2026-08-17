#!/usr/bin/env python3
"""
The cases for `scripts/_panel_state.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

SIX EXPRESSIONS COULD NOT MOVE LITERALLY.

  * `_src_of_this_file()` - a three-line `open(__file__)` helper this module,
    `panel-server.py` and `_panel_write.py` each carried a copy of, with all six
    call sites inside the three `--selftest` blocks and none in the product. The
    copies are gone; `_harness.module_source(M)` takes the module, so a source
    slice reads its SUBJECT.
  * `globals()["_MAX_FACTS"] = 1` - the roll-up cap, lowered so `usage_state` has
    to fold hourly facts into daily ones. From here that binds a name nothing
    reads: the real cap (large) would stay in force, `rolled` would be False and
    the case would go red pointing at a fold that is not broken. It is `M._MAX_FACTS`
    and restored on `M` in the same `finally`.
  * `globals()["_resolve_viewer"] = _counting_resolve` - the same shape, and the
    dangerous direction: the counting stub exists to prove the viewer cache is a
    cache. Left unpatched, the real resolver would run, the counter would read 0
    and the cache cases would be measuring nothing.
  * `[n for n in _moved if n in globals()]` - INTROSPECTION, not a rebind: "is
    every name this module took actually defined here". This file defines none of
    them, so it fails loudly rather than silently - but it is still asking the
    wrong module. It is `hasattr(M, n)`.
  * the `--name-only` slice - see below; it is the security case.
  * two paths built off the module's own directory: `<dir>/../hooks/
    guard-capabilities.py` and `<dir>/panel-server.py`. `scripts/` and `tests/` sit
    at the same depth, so the first would have resolved correctly by coincidence
    and the second incorrectly (there is no `tests/panel-server.py`). They are
    `_harness.HOOKS_DIR` and `_harness.SCRIPTS_DIR` now. The PRODUCTION copy of the
    guard-capabilities path stays where it is, spelled off `_panel_state.py`'s own
    `_HERE`, which is correct there.

THE `--name-only` CASE IS A SECURITY CLAIM, AND IT IS THE ONE THIS MOVE COULD HAVE
BROKEN SILENTLY. `_git_config_origins` must run `git config --list --name-only`:
a plain `--list` hands back every VALUE, and a git config routinely holds credential
helpers and tokens. The case asserts the flag appears between `def
_git_config_origins` and `def _git_config_candidates`. Spelled `_src.split(a)[1]
.split(b)[0]`, a missing END marker returns the whole rest of the module - measured
at 71,084 characters against the slice's real 3,747 - and `--name-only` is found
somewhere in it, so the case passes while guarding nothing. `_harness.between()`
raises on either marker. Both directions were proven red: renaming the end marker
makes the naive form pass vacuously and `between()` raise by name, and renaming the
flag itself turns the case red in both forms.

`_manifest_io` is imported here the way `_panel_state.py` imports it, because the
fixture writer goes straight through `_mio.atomic_write_json`.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve a sibling by basename)
import _manifest_io as _mio                        # noqa: E402  (as _panel_state imports it)
import _panel_state as M                           # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import pathlib
    import shutil
    import tempfile

    _src = _harness.module_source(M)

    def _atomic_write_json(path, obj):
        """The selftest's own fixture writer. panel-server keeps the real
        `_atomic_write_json`; nothing in THIS module writes JSON, so rather than
        move a writer a read module has no use for, the fixtures go straight
        through `_manifest_io` — the same implementation that one delegates to."""
        _mio.atomic_write_json(path, obj, ensure_ascii=False, indent=2)

    tmp = tempfile.mkdtemp(prefix="panel-state-selftest-")
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude"), exist_ok=True)
    _atomic_write_json(M._config_path(proj), {"trivialLineThreshold": 40})
    mpath = M._manifest_path(proj, M.read_config(proj))
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    _atomic_write_json(mpath, {
        "meta": {"version": 2, "reviewSkill": None},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                    "review": {"model": "sonnet"},
                    "tasks": [{"id": "P1.1", "title": "T", "status": "pending"},
                              {"id": "P1.2", "title": "T2", "status": "pending"}]}]})

    # --- what the config declares, and what merely defaults ---------------------
    check("_declared_as_of separates a project's own value from the default",
          M._declared_as_of({"usage": {"pricingAsOf": "2026-01-02"}}) is True
          and M._declared_as_of({"usage": {"showCost": True}}) is False
          and M._declared_as_of({}) is False
          and M._declared_as_of({"usage": {"pricingAsOf": "   "}}) is False
          and M._declared_as_of({"usage": {"pricingAsOf": 20260102}}) is False)

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
    _rup = M._cores()[2].rollup(bm, [], [])
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


    # --- v0.30: the policy block's rules, and whether anything enforces them ----
    # The verdict cases that need a fixture full of discovered capabilities stay
    # with the HTTP round trip in panel-server; what moved is the part that is a
    # function of the block itself, plus the enforcement marker.
    check("deny is listed before allow within a scope, because that is the "
          "order the verdict is decided in",
          [(r["list"], r["pattern"]) for r in M._policy_rules(
              {"skills": {"allow": ["a"], "deny": ["d"]}}, "skills", [])]
          == [("deny", "d"), ("allow", "a")])
    _many = M._policy_rules({"skills": {"deny": ["a*"]}}, "skills",
                          ["a%d" % i for i in range(9)])
    check("a pattern covering more names than fit is capped for display while "
          "the count stays true - a truncated list read as the total would "
          "understate what one rule decides",
          _many[0]["n"] == 9 and len(_many[0]["matches"]) == 6)
    check("a blank or non-string pattern is skipped rather than rendered as an "
          "empty rule nobody can remove",
          M._policy_rules({"skills": {"deny": ["  ", "", 7, "real"]}},
                        "skills", []) == [
              {"scope": None, "list": "deny", "pattern": "real",
               "matches": [], "n": 0, "dead": True}])
    # v0.38: the dead flag - the server's own "names nothing" verdict, computed
    # by _policy.dead_patterns beside the guard's matcher, so the client renders
    # it and never matches a pattern itself.
    check("a pattern matching nothing discovered and nothing of audit's own is "
          "marked dead; a name the inventory satisfies is not",
          [(r["pattern"], r["dead"]) for r in M._policy_rules(
              {"skills": {"deny": ["ghost-*", "real-skill"]}}, "skills",
              ["real-skill"])]
          == [("ghost-*", True), ("real-skill", False)])
    check("a pattern that names only audit's own components is not dead - the "
          "plugin ships them, so they are always installed",
          M._policy_rules({"skills": {"deny": ["x"], "allow": ["audit:*"]}},
                        "skills", [])[1]["dead"] is False)
    check("mcp rules are judged both ways against the server stand-ins - a rule "
          "for one tool of an installed server is alive, one for an absent "
          "server is dead",
          [r["dead"] for r in M._policy_rules(
              {"mcp": {"deny": ["mcp__srv__one_tool", "mcp__gone__*"]}},
              "mcp", ["mcp__srv__*"])] == [False, True])
    # Called through a wrapper so the failure is a named FAIL and not a
    # traceback: this endpoint feeds a form, a form's job is to survive a file
    # somebody hand-edited, and an assertion that dies while proving that
    # reports the wrong thing twice over — nothing about the defect, and a
    # crash that looks like one.
    def _rules_safe(pol, kind, names):
        try:
            return M._policy_rules(pol, kind, names)
        except Exception as exc:                 # noqa: BLE001 - that is the check
            return "raised %s" % type(exc).__name__
    check("a malformed kind block yields no rules instead of raising",
          _rules_safe({"skills": "nonsense"}, "skills", ["x"]) == []
          and _rules_safe({}, "skills", ["x"]) == []
          and _rules_safe({"skills": {"deny": "nope"}}, "skills", ["x"]) == [])

    # What scopes an area rule, and why this walk is NOT `_mio.iter_tasks`. The
    # first phase is in_progress with NO tasks at all — the state a phase is in
    # between /audit:phase starting it and its first task being minted — and
    # `iter_tasks` yields nothing for it. The second phase is the same shape the
    # other way round (dormant phase, running task), so the case separates the
    # two rules instead of proving only one of them.
    check("an in_progress phase with no tasks still scopes its area, and a "
          "dormant phase holding a running task does too",
          M._active_area_tags({"phases": [
              {"id": "P1", "status": "in_progress", "area": "infra"},
              {"id": "P2", "status": "pending", "area": ["web"], "tasks": [
                  {"id": "P2.1", "status": "in_progress"}]},
              {"id": "P3", "status": "pending", "area": "quiet", "tasks": [
                  {"id": "P3.1", "status": "pending"}]},
          ]}) == ["infra", "web"])

    _pproj = tempfile.mkdtemp(prefix="state-policy-")
    try:
        os.makedirs(os.path.join(_pproj, ".claude"), exist_ok=True)
        _atomic_write_json(M._config_path(_pproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _ps = M.policy_state(_pproj)
        # Whether anything is enforcing any of this. A page full of `deny` verdicts
        # that cannot say whether the hook has ever run would be claiming
        # enforcement nobody has - the doctor's warning, on the surface that shows
        # the denials.
        check("with no marker, enforcement is reported as never seen rather than "
              "assumed",
              _ps["enforcement"] == {"seen": False, "ageDays": None})
        _sd = str(M._cores()[3].state_dir(pathlib.Path(_pproj), M.read_config(_pproj)))
        os.makedirs(_sd, exist_ok=True)
        # Off `_harness.HOOKS_DIR`, not off this file: scripts/ and tests/ are
        # both one level under the plugin directory, so the module's own
        # `<dir>/../hooks` would resolve right here by coincidence.
        _gc = M._load("audit_guard_capabilities_t", "guard-capabilities.py",
                      _harness.HOOKS_DIR)
        with open(os.path.join(_sd, _gc.SEEN_FILE), "w", encoding="utf-8") as _fh:
            _fh.write("{}")
        _pe = M._policy_enforcement(_pproj, M.read_config(_pproj))
        check("with the guard's own marker present it is reported as seen, with an "
              "age and no verdict about whether that age is too old - how stale is "
              "too stale is /audit:doctor's judgement, and a second threshold here "
              "is one that can disagree with it",
              _pe["seen"] is True and _pe["ageDays"] is not None
              and _pe["ageDays"] < 1 and set(_pe) == {"seen", "ageDays"})
        check("...and it is found at the path the hook writes: the config's own "
              "state_dir and the hook's own SEEN_FILE, neither spelled out twice",
              os.path.isfile(os.path.join(_sd, _gc.SEEN_FILE))
              and _gc.SEEN_FILE == "capability-guard.json")
        check("an unreadable project reports never-seen rather than raising",
              M._policy_enforcement(os.path.join(_pproj, "nope"), {})["seen"] is False)
    finally:
        shutil.rmtree(_pproj, ignore_errors=True)


    # --- the audit locks, and whether the run behind one is alive ---------------
    ld = os.path.join(tmp, "audit-locks")
    os.makedirs(ld)
    _atomic_write_json(os.path.join(ld, "index.lock"), {"hostname": "hi", "startedAt": "t"})
    _atomic_write_json(os.path.join(ld, "phase-P1.lock"), {"hostname": "hp", "startedAt": "t2"})
    li = M._lock_info(ld)
    check("_lock_info reads the index lock", (li["index"] or {}).get("hostname") == "hi")
    check("_lock_info reads a phase lock", (li["phases"].get("P1") or {}).get("hostname") == "hp")

    # C1 — the badge says "running", which is a claim about a live process.
    import platform as _pf
    import subprocess as _sp
    import time as _t
    _here = _pf.node()
    _old = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(_t.time() - 95 * 60))
    _atomic_write_json(os.path.join(ld, "phase-P2.lock"),
                       {"hostname": _here, "pid": os.getpid(), "startedAt": _old})
    _d = _sp.Popen([sys.executable, "-c", "pass"]); _d.wait()
    _atomic_write_json(os.path.join(ld, "phase-P3.lock"),
                       {"hostname": _here, "pid": _d.pid,
                        "startedAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())})
    li = M._lock_info(ld)
    check("lock verdict: a 95-min-old run with a live pid is live",
          li["phases"]["P2"].get("live") is True)
    check("lock verdict: a 1-min-old run whose pid is gone is not",
          li["phases"]["P3"].get("live") is False)
    check("lock verdict: each carries the basis behind it",
          bool(li["phases"]["P2"].get("liveBasis"))
          and bool(li["phases"]["P3"].get("liveBasis")))
    check("lock verdict: a pid-less lock gets one too (age fallback)",
          li["phases"]["P1"].get("live") is not None)
    os.remove(os.path.join(ld, "phase-P2.lock"))
    os.remove(os.path.join(ld, "phase-P3.lock"))

    u = M.usage_state(proj)
    check("usage_state on a project with no ledger is empty, not an error",
          u["facts"] == [] and u["totalRows"] == 0 and "ledgerDir" in u)
    led = os.path.join(proj, ".claude", "usage")
    os.makedirs(led, exist_ok=True)
    with open(os.path.join(led, "2026-08.jsonl"), "w", encoding="utf-8") as fh:
        for i, (model, author) in enumerate(
                (("claude-opus-5", "a@x.io"), ("claude-haiku-4-5", "b@x.io"))):
            fh.write(json.dumps({
                "ts": "2026-08-0%dT1%d" % (i + 1, i), "sessionId": "s%d" % i,
                "phaseId": "P1", "taskId": "P1.%d" % (i + 1), "attr": "task",
                "model": model, "author": author, "agentType": "audit-executor",
                "msgs": 2, "in": 5, "out": 100, "cacheW5m": 0, "cacheW1h": 0,
                "cacheR": 50, "costUSD": 0.25}) + "\n")
        fh.write("{ torn line\n")
    u = M.usage_state(proj)
    check("usage_state reads the ledger into positional facts",
          len(u["facts"]) == 2 and u["fields"][0] == "ts"
          and len(u["facts"][0]) == len(u["fields"]))
    check("usage_state tolerates a torn ledger line", u["totalRows"] == 2)
    check("usage_state carries phase titles for labelling",
          isinstance(u["phaseTitles"], dict))
    check("usage_state does not roll up a small ledger", u["rolled"] is False)
    check("usage facts carry no prompt content — only dimensions and counts",
          all(len(f) == 10 for f in u["facts"]))

    # --- one manifest read per /api/usage ---------------------------------------
    # The payload answers five questions about ONE document (titles/taskMeta/
    # budgets, routingAdvice, monthlyPlan, phaseAreas, areaOwners) and each used to
    # re-read it — on a sharded plan that is 1 index + 1 file per phase, per
    # question. COUNTED rather than asserted-present: a source pin cannot tell one
    # call from five, which is exactly the regression this guards.
    _lms_calls = [0]
    _real_lms = _mio.load_manifest_safe

    def _counting_lms(path):
        _lms_calls[0] += 1
        return _real_lms(path)

    _mio.load_manifest_safe = _counting_lms
    try:
        _hoisted = M.usage_state(proj)
    finally:
        _mio.load_manifest_safe = _real_lms
    check("usage_state reads the manifest exactly ONCE for all five of its "
          "manifest-derived fields (each used to re-read it)",
          _lms_calls[0] == 1)
    check("counting the reads did not change the payload",
          _hoisted == u)
    # The other direction, and the one that looks vacuous: "read once" must mean
    # once PER REQUEST, not once per process. A manifest memoized across requests
    # would satisfy the count above and then serve a stale plan forever — the
    # `_VIEWER_CACHE` failure — so edit the plan on disk and require the next
    # response to carry it.
    _m_before = _mio.load_manifest_safe(mpath)
    try:
        _m_edited = json.loads(json.dumps(_m_before))
        _m_edited["phases"][0]["title"] = "Retitled between requests"
        _atomic_write_json(mpath, _m_edited)
        check("the single read is per REQUEST — a plan edited between two calls "
              "shows up in the second",
              M.usage_state(proj)["phaseTitles"].get("P1")
              == "Retitled between requests")
    finally:
        _atomic_write_json(mpath, _m_before)
    check("...and restoring the plan restores the payload",
          M.usage_state(proj)["phaseTitles"].get("P1") == "P")

    _saved = M._MAX_FACTS
    try:
        M._MAX_FACTS = 1
        ru = M.usage_state(proj)
        check("oversized ledger rolls hourly facts up to daily, and says so",
              ru["rolled"] is True and all(len(f[0]) == 10 for f in ru["facts"]))
    finally:
        M._MAX_FACTS = _saved
    _cfg_path = os.path.join(proj, ".claude", "audit.config.json")
    _prev_cfg = (open(_cfg_path, encoding="utf-8").read()
                 if os.path.isfile(_cfg_path) else None)
    try:
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"enabled": False, "showCost": False}}, fh)
        du = M.usage_state(proj)
        check("usage_state reports metering off so the tab can explain itself",
              du["enabled"] is False and du["showCost"] is False)
        # The empty branch's own comment requires it: every key the populated
        # branch returns must appear here too, or a fresh install reads undefined.
        check("the no-ledger shape carries pricingAsOfDeclared as well, so a "
              "fresh install does not read undefined",
              "pricingAsOfDeclared" in du and du["pricingAsOfDeclared"] is False)
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"pricingAsOf": "2026-01-02"}}, fh)
        check("a declared date is reported as declared, and travels with it",
              M.usage_state(proj)["pricingAsOfDeclared"] is True
              and M.usage_state(proj)["pricingAsOf"] == "2026-01-02")
        with open(_cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"usage": {"showCost": True}}, fh)
        _dd = M.usage_state(proj)
        check("an undeclared one still carries the merged default as the VALUE, "
              "flagged as undeclared - the client decides, the server does not lie",
              _dd["pricingAsOfDeclared"] is False and _dd["pricingAsOf"])
    finally:
        if _prev_cfg is None:
            os.remove(_cfg_path)
        else:
            with open(_cfg_path, "w", encoding="utf-8") as fh:
                fh.write(_prev_cfg)

    # --- monthlyPlan (C2): the Monthly card's server-shipped plan half ----------
    # The ledger half of that card is recomputed in the browser under the current
    # filters; the plan half cannot be (the client has no manifest), so it ships
    # here. Key parity first: the empty branch must carry every key the populated
    # branch returns — the pinned rule beside the empty dict — so a fresh install
    # reads {} and never undefined.
    _mp_empty = M.usage_state(os.path.join(tmp, "no-such-proj"))
    check("usage_state ships monthlyPlan in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          _mp_empty["facts"] == [] and "monthlyPlan" in _mp_empty
          and _mp_empty["monthlyPlan"] == {})
    with open(mpath, encoding="utf-8") as _fh:
        _orig_manifest = json.load(_fh)
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [{"id": "P1", "title": "P", "status": "done",
                        "mergedAt": "2026-08-06T10:00:00Z",
                        "tasks": [{"id": "P1.1", "title": "T", "status": "done",
                                   "completedAt": "2026-08-03T10:00:00Z"}]}],
            "bugs": [{"id": "BUG-1", "status": "open",
                      "reportedAt": "2026-07-02T10:00:00Z", "taskId": "P1.1"}]})
        _mp = M.usage_state(proj)
        check("the populated branch derives monthlyPlan from the manifest "
              "through monthly_activity - completedAt/reportedAt/mergedAt "
              "buckets, bugsFixed via the linked done task",
              _mp["monthlyPlan"].get("2026-08", {}).get("tasksCompleted") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("phasesMerged") == 1
              and _mp["monthlyPlan"].get("2026-07", {}).get("bugsReported") == 1
              and _mp["monthlyPlan"].get("2026-08", {}).get("bugsFixed") == 1)
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- phaseAreas (D4): the Usage tab's area filter join map ------------------
    # The client attributes spend to areas in a read-time join (row.phaseId ->
    # phase.area tags), so the map ships with the facts. Key parity again: BOTH
    # branches carry the key, and an untagged phase maps to [] rather than being
    # missing, so the client can tell "known phase, no tags" from "phase the
    # plan never heard of".
    check("usage_state ships phaseAreas in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "phaseAreas" in _mp_empty and _mp_empty["phaseAreas"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2},
            "phases": [
                {"id": "P1", "title": "A", "status": "done",
                 "area": ["backend", "sec"], "tasks": []},
                {"id": "P2", "title": "B", "status": "pending", "tasks": []}]})
        check("the populated branch derives phaseAreas through _areas."
              "phase_tags - a multi-tag phase keeps every tag, an untagged "
              "phase maps to [], not missing",
              M.usage_state(proj).get("phaseAreas")
              == {"P1": ["backend", "sec"], "P2": []})
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- areaOwners (v0.34 D3): the advisory owner per registered area ----------
    # panel.js joins UF.author against these values for the person header's
    # "owns:" line and titles the area select options. Key parity again - the
    # sibling case beside phaseAreas', because a key in one branch only is an
    # `undefined` that ships on every fresh install.
    check("usage_state ships areaOwners in BOTH branches - {} on a repo with "
          "no ledger, never undefined",
          "areaOwners" in _mp_empty and _mp_empty["areaOwners"] == {})
    try:
        _atomic_write_json(mpath, {
            "meta": {"version": 2,
                     "areas": {"backend": {"root": "src",
                                           "owner": " jane@x.com "},
                               "sec": {"root": "sec", "owner": None},
                               "web": {"root": "web"}}},
            "phases": [{"id": "P1", "title": "A", "status": "done",
                        "area": ["backend", "sec"], "tasks": []}]})
        check("the populated branch maps tag -> trimmed owner through _areas."
              "registry - only tags that DECLARE a non-null owner enter the "
              "map, so null ('nobody') and undeclared read the same to the UI",
              M.usage_state(proj).get("areaOwners") == {"backend": "jane@x.com"})
    finally:
        _atomic_write_json(mpath, _orig_manifest)

    # --- report export ------------------------------------------------------------
    # There is deliberately no path parameter on /report: the location is derived
    # from the project's own config, so there is nothing to traverse with.
    _rp = tempfile.mkdtemp(prefix="panel-report-")
    try:
        os.makedirs(os.path.join(_rp, "docs", "audit"), exist_ok=True)
        with open(os.path.join(_rp, "docs", "audit", "audit-plan.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "repo": "x"}, "phases": [
                {"id": "P1", "title": "A", "status": "done", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)
        check("no report exists before it is rendered",
              os.path.isfile(M.report_paths(_rp)[2]) is False)
        _res = M.render_report(_rp)
        check("export writes the html and its markdown twin, and reports both",
              _res["ok"] and len(_res["files"]) == 2
              and any(f.endswith(".html") for f in _res["files"])
              and any(f.endswith(".md") for f in _res["files"]))
        check("everything it writes stays inside the project",
              all(M._within(_rp, f) for f in _res["files"]))
        check("it hands back an in-origin href, not a filesystem path — a browser "
              "will not follow file:// from an http:// page",
              _res["href"] == "/report" and _res["exists"] is True)
    finally:
        shutil.rmtree(_rp, ignore_errors=True)
    _np = tempfile.mkdtemp(prefix="panel-noreport-")
    try:
        check("a project with no manifest refuses instead of raising",
              M.report_paths(_np) is None
              and M.render_report(_np)["ok"] is False)
    finally:
        shutil.rmtree(_np, ignore_errors=True)

    # --- routing advice ---------------------------------------------------------
    # The only server-computed metric in the Usage tab; the tab's own strings are
    # pinned in panel-server, beside UI_HTML.
    check("routing advice is shipped from the server and fails soft",
          '"routingAdvice": advice' in _src
          and "ul.routing(manifest, rows," in _src
          and "advice = []" in _src)

    # --- v0.34 C5 (lv): the data fingerprint -------------------------------------
    # Pure stats per request, folded into /api/runstatus so the existing 5s
    # poll carries it. The browser half (refreshFromDisk) is driven in
    # capture-screenshots.mjs --check.
    _fp1 = M.data_fingerprint(proj, M.read_config(proj))
    _fp2 = M.data_fingerprint(proj, M.read_config(proj))
    check("lv: the fingerprint is a pure stat - stable across two calls with "
          "nothing changed", isinstance(_fp1, str) and _fp1 and _fp1 == _fp2)
    # Change the SIZE, not only the mtime: coarse filesystems round mtime to a
    # second, and a rewrite inside that second would otherwise stamp equal.
    _m_orig = open(mpath, encoding="utf-8").read()
    try:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig + " ")
        check("lv: a manifest rewrite moves it",
              M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    finally:
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(_m_orig)
    _c_orig = open(M._config_path(proj), encoding="utf-8").read()
    try:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig + " ")
        check("lv: a config write moves it (manifestPath/ledgerDir live there, "
              "so the config file is stamped FIRST)",
              M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    finally:
        with open(M._config_path(proj), "w", encoding="utf-8") as fh:
            fh.write(_c_orig)
    with open(os.path.join(led, "2026-08.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-08-03T10", "sessionId": "s9",
                             "model": "m", "msgs": 1, "in": 1, "out": 1,
                             "costUSD": 0.0}) + "\n")
    check("lv: a ledger append moves it (newest *.jsonl stat)",
          M.data_fingerprint(proj, M.read_config(proj)) != _fp1)
    # Sharded: every shard body is stamped, so a phase edit that never touches
    # the index still moves the stamp.
    _lvproj = tempfile.mkdtemp(prefix="state-lv-")
    try:
        _atomic_write_json(M._config_path(_lvproj),
                           {"manifestPath": "docs/audit/audit-plan.json"})
        _lvm = M._manifest_path(_lvproj, M.read_config(_lvproj))
        os.makedirs(os.path.dirname(_lvm), exist_ok=True)
        _mio.save_sharded(_lvm, {
            "meta": {"version": 3},
            "phases": [{"id": "P1", "title": "One", "status": "pending",
                        "tasks": [{"id": "P1.1", "title": "T",
                                   "status": "pending"}]}]})
        _lv1 = M.data_fingerprint(_lvproj, M.read_config(_lvproj))
        with open(os.path.join(os.path.dirname(_lvm), "phases", "P1.json"),
                  "a", encoding="utf-8") as fh:
            fh.write(" ")
        check("lv: a sharded phase body moves it without the index changing",
              M.data_fingerprint(_lvproj, M.read_config(_lvproj)) != _lv1)
    finally:
        shutil.rmtree(_lvproj, ignore_errors=True)
    _lvmiss = os.path.join(tmp, "lv-nothing-here")
    check("lv: missing everything is a stable sentinel, never a raise",
          M.data_fingerprint(_lvmiss, {}) == M.data_fingerprint(_lvmiss, {})
          and isinstance(M.data_fingerprint(_lvmiss, {}), str))
    check("lv: the fingerprint rides /api/runstatus's payload - with and "
          "without a manifest - so the existing poll carries it for free "
          "while it stays OUT of runStatusKey (a moved stamp hands off to "
          "refreshFromDisk instead of repainting)",
          isinstance(M._run_status(proj, M.read_config(proj), {})
                     .get("fingerprint"), str)
          and isinstance(M._run_status(_lvmiss, {}, {}).get("fingerprint"), str))
    check("lv: SSE is weighed and rejected in prose where the stamp is "
          "defined, so the next person does not re-litigate it blind",
          "SSE" in (M.data_fingerprint.__doc__ or ""))

    # --- v0.34 B3 (gt): the Plan gate block on /api/runstatus --------------------
    # Tier + why, bypass-armed, and the tail of the gate events feed - the
    # panel's Overview card is fed from here, so the server computes the tier
    # with the hooks' own functions rather than letting the browser guess.
    _gtcfg = M._cores()[3]
    _gt = M._run_status(proj, M.read_config(proj), {}).get("gate")
    check("gt: runstatus carries a gate block with the tier and its source",
          isinstance(_gt, dict) and _gt.get("mode") in ("observe", "warn",
                                                        "ask", "deny")
          and bool(_gt.get("source")) and isinstance(_gt.get("events"), list)
          and _gt.get("bypassArmed") is False)
    check("gt: a pinned planGate names the knob as the source, tier included",
          (M._run_status(proj, {"planGate": "ask"}, {}).get("gate") or {})
          .get("mode") == "ask"
          and "planGate" in str((M._run_status(proj, {"planGate": "ask"}, {})
                                 .get("gate") or {}).get("source")))
    check("gt: legacy enforce:true is named as legacy, not as evidence",
          "legacy" in str((M._run_status(proj, {"enforce": True}, {})
                           .get("gate") or {}).get("source")))
    for _i in range(25):
        _gtcfg.append_gate_event(os.path.join(proj, ".claude", "logs"),
                                 {"event": "observe", "file": "f%d.ts" % _i,
                                  "sessionId": "gt"})
    _gt = M._run_status(proj, M.read_config(proj), {}).get("gate") or {}
    check("gt: the events table is the feed's tail, newest first, capped at 20",
          len(_gt.get("events") or []) == 20
          and _gt["events"][0].get("file") == "f24.ts"
          and _gt["events"][-1].get("file") == "f5.ts")
    _gtsd = os.path.join(proj, ".claude", "state")
    os.makedirs(_gtsd, exist_ok=True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())}, fh)
    check("gt: a live bypass slot flips the armed indicator",
          (M._run_status(proj, M.read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is True)
    with open(os.path.join(_gtsd, "plan-bypass-gt.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": "t", "reason": "x",
                   "armedAtEpoch": int(time.time())
                   - _gtcfg.BYPASS_TTL_SECONDS - 60}, fh)
    check("gt: an EXPIRED slot does not count as armed - the card must not "
          "claim a bypass require-plan would refuse",
          (M._run_status(proj, M.read_config(proj), {}).get("gate") or {})
          .get("bypassArmed") is False)
    os.unlink(os.path.join(_gtsd, "plan-bypass-gt.json"))
    check("gt: a project with nothing on disk still gets a gate block, never "
          "a raise",
          isinstance(M._run_status(_lvmiss, {}, {}).get("gate"), dict))

    # --- who is looking: the identity cache, in BOTH directions -----------------
    # A stale answer here is worse than a slow one: the Usage tab's "my spend"
    # filter compares this name against the ledger's `author` column, so an
    # identity that went out of date silently selects the wrong rows. Neither
    # direction is taken on trust. Every case COUNTS resolves rather than timing
    # anything — a wall-clock assertion is flaky on a loaded machine and cannot say
    # WHICH work was skipped.
    #
    # The fixture owns its whole git identity: GIT_CONFIG_NOSYSTEM plus a
    # GIT_CONFIG_GLOBAL under the temp dir, and USER/USERNAME both set (Windows
    # reads the second), so nothing about this machine's real config can decide a
    # case here — the `no-silent-pass` ambient-state rule, on the two CI platforms.
    _vtmp = tempfile.mkdtemp(prefix="state-viewer-")
    _venv_keys = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
                  "XDG_CONFIG_HOME", "USER", "USERNAME")
    _venv_saved = {k: os.environ.get(k) for k in _venv_keys}
    _real_resolve_viewer = M._resolve_viewer
    _resolves = [0]

    def _counting_resolve(project, mode):
        _resolves[0] += 1
        return _real_resolve_viewer(project, mode)

    def _vwrite(path, email, settled=True):
        """Write a git config carrying one identity.

        Backdated by default because the settle guard is doing its job: a file
        written this millisecond is deliberately NOT cached, so aging it is the
        honest way to reach the cached path. `settled=False` is how the guard's
        own case reaches the other branch."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[user]\n\temail = %s\n" % email)
        if settled:
            _when = time.time() - 5
            os.utime(path, (_when, _when))

    try:
        M._resolve_viewer = _counting_resolve
        _vproj = os.path.join(_vtmp, "proj")
        os.makedirs(_vproj)
        _vglobal = os.path.join(_vtmp, "gitconfig-global")
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        os.environ["GIT_CONFIG_GLOBAL"] = _vglobal
        os.environ["XDG_CONFIG_HOME"] = os.path.join(_vtmp, "xdg")
        os.environ["USER"] = os.environ["USERNAME"] = "fixture-user"
        os.environ.pop("GIT_CONFIG_SYSTEM", None)

        _vwrite(_vglobal, "alice@example.com")
        _resolves[0] = 0
        _v1 = M._viewer(_vproj, {})
        check("viewer: the first call really does resolve — the baseline the skip "
              "case below is measured against, and the proof the counter works",
              _v1 == {"author": "alice@example.com", "mode": "email"}
              and _resolves[0] == 1)
        _resolves[0] = 0
        _v2 = M._viewer(_vproj, {})
        # THE SECOND-DIRECTION CASE. It looks vacuous and it is the only one that
        # fails if invalidation becomes unconditional (a token that never compares
        # equal, a bare recompute): the answer would still be right, and the cache
        # would have bought nothing.
        check("viewer: with no identity file and no environment moved, the second "
              "call resolves NOTHING and hands back the same answer",
              _resolves[0] == 0 and _v2 == _v1)

        # THE BUG ITSELF (F-P): `git config user.email` edited under a running
        # panel. The old cache was keyed on (project, mode) and populated once, so
        # this returned alice forever.
        _vwrite(_vglobal, "bob@example.com")
        _resolves[0] = 0
        _v3 = M._viewer(_vproj, {})
        check("viewer: user.email changed IN PLACE under a running process is "
              "picked up — the whole bug: no directory listing changed, so only "
              "stamping the config FILE can catch this",
              _v3["author"] == "bob@example.com" and _resolves[0] == 1)

        # The environment half. With no git identity anywhere, resolve_author's
        # answer IS $USER — a value no stat of any file could ever see move.
        _vlater = os.path.join(_vtmp, "gitconfig-later")
        os.environ["GIT_CONFIG_GLOBAL"] = _vlater          # nothing there yet
        M._viewer(_vproj, {})                                # warm on the new env
        _resolves[0] = 0
        _v4 = M._viewer(_vproj, {})
        check("viewer: a project whose git knows no identity falls back to the "
              "environment, and that answer caches too",
              _v4["author"] == "fixture-user" and _resolves[0] == 0)
        os.environ["USER"] = os.environ["USERNAME"] = "someone-else"
        _resolves[0] = 0
        _v5 = M._viewer(_vproj, {})
        check("viewer: the environment is pinned BY VALUE - USER changed moves no "
              "file's mtime, so a stat-only token would have served the old name",
              _v5["author"] == "someone-else" and _resolves[0] == 1)

        # THE TTL-KILLER. The winning config file did not EXIST when the answer was
        # resolved, so a token covering only what was read (or a plain TTL) cannot
        # know it appeared.
        M._viewer(_vproj, {})                                # re-warm, settled
        _resolves[0] = 0
        _vwrite(_vlater, "carol@example.com")
        _v6 = M._viewer(_vproj, {})
        check("viewer: a config file that did not EXIST at resolve time "
              "invalidates when it appears — absent paths are stamped, never "
              "dropped from the token",
              _v6["author"] == "carol@example.com" and _resolves[0] == 1)

        # The settle guard, both ways. A case that only ever saw it accept would be
        # asserting nothing.
        _vfresh = os.path.join(_vtmp, "gitconfig-fresh")
        os.environ["GIT_CONFIG_GLOBAL"] = _vfresh
        _vwrite(_vfresh, "dave@example.com", settled=False)
        M._viewer(_vproj, {})
        _resolves[0] = 0
        _v7 = M._viewer(_vproj, {})
        check("viewer: an identity file written a moment ago is NOT cached — a "
              "1-second-granular mtime cannot prove the resolve saw the final "
              "bytes, and serving the pre-edit name forever is the original bug",
              _v7["author"] == "dave@example.com" and _resolves[0] == 1)
        _vsettle = time.time() - 5
        os.utime(_vfresh, (_vsettle, _vsettle))
        M._viewer(_vproj, {})                                # re-warm, now settled
        _resolves[0] = 0
        _v8 = M._viewer(_vproj, {})
        check("viewer: ...and the same file, once it has settled, IS cached",
              _v8["author"] == "dave@example.com" and _resolves[0] == 0)

        _vmine = M._viewer(_vproj, {})
        _vmine["author"] = "clobbered"
        check("viewer: each caller gets its own copy — writing to a returned "
              "viewer cannot poison the next caller's answer",
              M._viewer(_vproj, {})["author"] == "dave@example.com")

        # The watch list is what the RESOLVE read, plus what it would have read.
        # A file consulted but not stamped is precisely how a cache goes stale in
        # silence, so the two halves are checked against each other rather than
        # trusted from the docstring.
        _vwatch = _real_resolve_viewer(_vproj, "email")[1]
        check("viewer: the winning config file is in the watch list, and so is the "
              "repo config of the project and of its parent — the places a "
              "repo-local user.email can appear when the panel is opened on a "
              "subdirectory",
              _vfresh in _vwatch
              and os.path.join(os.path.realpath(_vproj), ".git", "config")
              in _vwatch
              and os.path.join(os.path.realpath(_vtmp), ".git", "config")
              in _vwatch)
        check("viewer: the origin list carries PATHS only - `--name-only`, because "
              "a plain --list also hands back every value and a git config "
              "routinely holds credential helpers and tokens",
              "--name-only" in _harness.between(
                  _src, "def _git_config_origins", "def _git_config_candidates"))
    finally:
        M._resolve_viewer = _real_resolve_viewer
        for _k, _v in _venv_saved.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        shutil.rmtree(_vtmp, ignore_errors=True)

    # --- isolation cases (P12.3): the moved boundary stays real -----------------
    _imports = [l for l in _src.split("\n")
                if l.startswith("import ") or l.startswith("from ")]
    check("this module never imports panel-server - the read side sits BELOW the "
          "server, so nothing that imports it can form a cycle",
          not any("panel_server" in l or "panel-server" in l for l in _imports))
    # `_loader.script_path`, not `join(_harness.SCRIPTS_DIR, ...)`: this reads
    # another file's SOURCE, so a joined root would keep working for exactly as long
    # as `panel-server.py` sits at the top of `scripts/` and would then fail as a
    # missing file rather than as the resolvable basename it still is.
    _panel_src = open(_loader.script_path("panel-server.py"),
                      encoding="utf-8").read()
    _moved = ["_load", "_cores", "_defaults", "_within", "_config_path",
              "_declared_as_of", "_manifest_path", "_viewer", "_read_json",
              "read_config", "_areas_of", "_bugs_view", "_skills_of",
              "_composition_view", "areas_state", "_JOURNAL", "_journalmod",
              "JOURNAL_PAGE", "journal_state", "help_state", "help_field",
              "_policy_rules", "_policy_enforcement", "_policy_areas_view",
              "policy_state", "_active_area_tags", "_audit_lock_dir",
              "_audit_lock_held", "_lockmod", "_lock_info", "_run_status",
              "usage_state", "report_paths", "render_report", "build_state"]
    _unaliased = [n for n in _moved
                  if "\n%s = _panel_state.%s\n" % (n, n) not in _panel_src]
    check("every name this module took is aliased back in panel-server, so a route "
          "or a selftest that still spells it there resolves to THIS one: %r"
          % (_unaliased,), not _unaliased)
    _defined = [n for n in _moved if hasattr(M, n)]
    check("...and every one of them is actually defined here rather than merely "
          "expected: %r" % ([n for n in _moved if not hasattr(M, n)],),
          len(_defined) == len(_moved))
    # `_journalmod`'s memo is ONE dict, not a copy per module: the write path in
    # panel-server swaps a stub module into it and this module's `journal_state`
    # has to see the same swap, or each side would test a journal the other does
    # not have.
    check("the journal memo is shared with panel-server by identity, not copied",
          "\n_JOURNAL = _panel_state._JOURNAL\n" in _panel_src
          and isinstance(M._JOURNAL, dict))

    shutil.rmtree(tmp, ignore_errors=True)

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_state.py --selftest\n")
    raise SystemExit(2)
