#!/usr/bin/env python3
"""
The cases for `_panel_policy.py` - the capability policy's rules, what they
resolve to for what is installed, and whether anything is enforcing them.

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
import _panel_policy as M           # noqa: E402


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

    tmp = tempfile.mkdtemp(prefix="panel-policy-selftest-")
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
        _sd = str(_paths.hooks_config().state_dir(
            pathlib.Path(_pproj), _paths.read_config(_pproj)))
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

    shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__panel_policy.py --selftest\n")
    raise SystemExit(2)
