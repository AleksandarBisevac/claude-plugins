#!/usr/bin/env python3
"""
The cases for `hooks/guard-capabilities.py`, moved out of it - a hook, hyphenated.

The module comes through `_loader.load` by path out of `_harness.HOOKS_DIR`, and
`_config` is imported directly because the fixtures build configs with the hook's
own `_config._deep_merge(_config.DEFAULTS, ...)` rather than through a second copy.
`_policy` is NOT imported here: the suite asks for it the way the hook does, through
`M._policy_mod()`, so `m0` still answers "is the engine reachable from the hook".

THE ONE REBIND IN THIS FILE IS NOT THE `globals()` HAZARD. The `j` group swaps
`os.replace` for a spy to read which temp NAME the writer hands over. That is an
attribute on the `os` MODULE - the same object `_config.atomic_write_text` looks the
name up on at call time - so it works identically from `tests/`, unlike a
`globals()["x"] = stub`, which from here would rebind a name in the test module that
nothing calls. It is restored in a `finally`.

Otherwise the AST scan for the six shapes the guide forbids carrying literally came
back empty: no `globals()`, no `vars()`, no `__file__`, no path built off the suite's
own directory, no `split(a)[1].split(b)[0]`.

THE EARLY EXIT BECAME A RETURN. The inline suite printed its own
`SELFTEST FAILED: the policy engine did not load` line and returned 1 when `m0`
failed, because there was no engine to run the remaining 29 cases against. Here the
body just returns: `m0` is already recorded as a failing case, and `_harness.run`
renders `SELFTEST FAILED: 0/1 cases passed` and exits 1 - the same verdict through
the shared sentinel instead of a hand-written one.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path as _P

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _config                                     # noqa: E402

M = _loader.load(os.path.join(_harness.HOOKS_DIR, "guard-capabilities.py"),
                 modname="guard_capabilities")


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = tempfile.mkdtemp(prefix="guard-capabilities-selftest-")
    pol_mod = M._policy_mod()
    check("m0 the policy engine is reachable from this hook", pol_mod is not None)
    if pol_mod is None:
        return

    def cfg_with(policy, **rest):
        base = {"policy": policy}
        base.update(rest)
        return _config._deep_merge(_config.DEFAULTS, base)

    def call(tool, ti, policy=None, active=None, cwd=tmp):
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
        return M.decide(data, cfg=cfg_with(policy) if policy is not None
                        else _config._deep_merge(_config.DEFAULTS, {}), active=active)

    # (a) inert by default — the case every repo that never opts in is in.
    for _tool, _ti in (("Skill", {"skill": "anything"}),
                       ("Agent", {"subagent_type": "general-purpose"}),
                       ("mcp__whatever__do", {})):
        action, _ = call(_tool, _ti)
        check("a1 %s is allowed under the shipped config" % _tool, action == "allow")
    action, why = call("Edit", {"file_path": "x.py"},
                       {"skills": {"default": "deny"}})
    check("a2 a tool this hook does not govern is never touched, even under a "
          "deny-everything policy", action == "allow" and "not a governed" in why)

    # (b) the three violation modes.
    deny_all = {"skills": {"default": "deny"}}
    action, msg = call("Skill", {"skill": "dataviz"}, deny_all)
    check("b1 default onViolation denies", action == "deny")
    check("b2 the message names the capability AND the rule that refused it, "
          "because a refusal nobody can explain gets switched off",
          "'dataviz'" in msg and "policy.skills.default is deny" in msg, msg)
    check("b3 ...and says how to change it", "audit.config.json" in msg)
    action, msg = call("Skill", {"skill": "dataviz"},
                       dict(deny_all, onViolation="ask"))
    check("b4 onViolation ask asks", action == "ask")
    action, msg = call("Skill", {"skill": "dataviz"},
                       dict(deny_all, onViolation="warn"))
    check("b5 onViolation warn allows the call and says so", action == "warn"
          and "Allowed anyway" in msg)
    action, _ = call("Skill", {"skill": "dataviz"},
                     dict(deny_all, onViolation="nonsense"))
    check("b6 a nonsense onViolation falls back to deny rather than to silence - "
          "the validator calls it a finding, and until it is fixed the written "
          "intent was to refuse. Decided ONCE, in _policy.policy_cfg; this case "
          "is what proves the hook reads the sanitised value and not the raw one",
          action == "deny")

    # (c) the payloads. `warn` must not be a permissionDecision.
    blob = json.loads(json.dumps(M._decision_payload("deny", "why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("c1 the deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[guard-capabilities]"))
    check("c2 the ask payload is the same shape with the other decision",
          json.loads(json.dumps(M._decision_payload("ask", "w")))
          ["hookSpecificOutput"]["permissionDecision"] == "ask")
    warn = json.loads(json.dumps(M._warn_payload("w")))
    check("c3 a warning is a systemMessage and carries NO permissionDecision - "
          "`allow` would skip the permission system, so an advisory written that "
          "way would silently grant more than it found",
          "hookSpecificOutput" not in warn
          and str(warn.get("systemMessage", "")).startswith("[guard-capabilities]"))

    # (d) audit's own components survive a deny-everything policy — the honest
    # half of "not unremovable, but not removable QUIETLY either".
    hard = {"skills": {"default": "deny", "deny": ["audit:*"]},
            "agents": {"default": "deny", "deny": ["*"]}}
    check("d1 audit's own skill is allowed through a policy that denies it twice",
          call("Skill", {"skill": "audit:next"}, hard)[0] == "allow")
    check("d2 ...and its executor agent",
          call("Agent", {"subagent_type": "audit:audit-executor"}, hard)[0]
          == "allow")
    check("d3 while somebody else's agent under the same policy is refused",
          call("Agent", {"subagent_type": "code-reviewer"}, hard)[0] == "deny")

    # (e) areas: the manifest read happens only when it could change the answer.
    area_pol = {"skills": {"default": "allow",
                           "areas": {"api": {"deny": ["deploy-*"]}}}}
    check("e1 an area rule is silent while that area has no work in progress",
          call("Skill", {"skill": "deploy-prod"}, area_pol, active=[])[0] == "allow")
    action, msg = call("Skill", {"skill": "deploy-prod"}, area_pol, active=["api"])
    check("e2 ...and refuses once it has, naming the area",
          action == "deny" and "areas.api.deny" in msg, msg)
    check("e3 _has_area_rules is what decides whether the manifest is read at all",
          M._has_area_rules(pol_mod.policy_cfg({"policy": area_pol}), "skills") is True
          and M._has_area_rules(pol_mod.policy_cfg({"policy": deny_all}), "skills")
          is False
          and M._has_area_rules(pol_mod.policy_cfg(
              {"policy": {"skills": {"areas": {"api": {}}}}}), "skills") is False)

    # (f) fail-open, every way in. A capability guard that fails closed over a bug
    # in itself would brick a session.
    check("f1 garbage payloads allow", M.decide({})[0] == "allow"
          and M.decide({"tool_name": None, "tool_input": None})[0] == "allow")
    check("f2 a malformed policy allows rather than denying by accident",
          call("Skill", {"skill": "x"}, "deny-everything")[0] == "allow"
          and call("Skill", {"skill": "x"}, {"skills": "nope"})[0] == "allow")
    check("f3 enabled:false turns it off entirely",
          call("Skill", {"skill": "x"},
               {"enabled": False, "skills": {"default": "deny"}})[0] == "allow")

    # (g) the doctor's evidence file: written once the policy is live, throttled,
    # and never on the inert path (its absence is what tells the doctor the
    # matchers are not reaching this hook).
    seen_root = tempfile.mkdtemp(prefix="guard-capabilities-seen-")
    try:
        cfg = cfg_with({"skills": {"default": "deny"}})
        path = os.path.join(str(_config.state_dir(_config.Path(seen_root), cfg)),
                            M.SEEN_FILE)
        M.decide({"tool_name": "Skill", "tool_input": {"skill": "x"},
                  "cwd": seen_root}, cfg=cfg, active=[])
        check("g1 a live policy leaves the marker the doctor reads",
              os.path.isfile(path))
        first = os.path.getmtime(path)
        os.utime(path, (first - 10, first - 10))
        M.decide({"tool_name": "Skill", "tool_input": {"skill": "y"},
                  "cwd": seen_root}, cfg=cfg, active=[])
        check("g2 ...refreshed at most once an hour, not once per tool call",
              os.path.getmtime(path) == first - 10)
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        inert = _config._deep_merge(_config.DEFAULTS, {})
        M.decide({"tool_name": "Skill", "tool_input": {"skill": "x"},
                  "cwd": seen_root}, cfg=inert, active=[])
        check("g3 an inert policy writes nothing - the marker means 'the guard ran "
              "with a policy to enforce', which is the only reading that makes its "
              "absence evidence", not os.path.exists(path))
    finally:
        shutil.rmtree(seen_root, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)
    # (i) the seen-file's state dir is self-ignoring
    tmp_i = tempfile.mkdtemp(prefix="gcap-ignore-")
    try:
        _cfg_i = dict(_config.DEFAULTS)
        M._mark_seen(_P(tmp_i), _cfg_i)
        check("i1 _mark_seen lands the seen-file in a self-ignoring dir",
              os.path.exists(os.path.join(
                  str(_config.state_dir(_P(tmp_i), _cfg_i)), ".gitignore")))
    finally:
        shutil.rmtree(tmp_i, ignore_errors=True)

    # (j) the seen-file is written through a UNIQUE temp name, never the naive
    # `path + ".tmp"`. Hooks run concurrently (one Edit fans out to seven hook
    # processes), so a fixed temp path is two processes truncating and replacing
    # the same file. "The marker exists" cannot see that - BOTH implementations
    # write it when nothing else is running - so these cases judge the temp NAME
    # and what happens when that one name is taken.
    tmp_j = tempfile.mkdtemp(prefix="gcap-atomic-")
    try:
        cfg_j = dict(_config.DEFAULTS)
        sdir_j = str(_config.state_dir(_P(tmp_j), cfg_j))
        path_j = os.path.join(sdir_j, M.SEEN_FILE)
        handed_over = []
        _real_replace = os.replace

        def _spy_replace(src, dst):
            handed_over.append(str(src))
            return _real_replace(src, dst)

        # An attribute on the `os` module, NOT `globals()`: the writer under test
        # resolves `os.replace` at call time on this same module object, so the spy
        # is seen from `tests/` exactly as it was from beside the hook.
        os.replace = _spy_replace
        try:
            M._mark_seen(_P(tmp_j), cfg_j)
            # Backdate rather than delete, so a broken first write leaves the
            # second call reachable and the cases below run instead of dying.
            try:
                stale = os.path.getmtime(path_j) - 2 * M.SEEN_REFRESH_SECONDS
                os.utime(path_j, (stale, stale))
            except OSError:
                pass
            M._mark_seen(_P(tmp_j), cfg_j)
        finally:
            os.replace = _real_replace
        check("j1 two writes hand os.replace two DIFFERENT temp names, neither of "
              "them the colliding `path + \".tmp\"` - the naive form hands over "
              "that one fixed name both times, which is the collision",
              len(handed_over) == 2 and len(set(handed_over)) == 2
              and (path_j + ".tmp") not in handed_over, repr(handed_over))
        check("j2 and no temp file is left behind either way",
              sorted(f for f in os.listdir(sdir_j) if ".tmp" in f) == [])
    finally:
        shutil.rmtree(tmp_j, ignore_errors=True)

    tmp_k = tempfile.mkdtemp(prefix="gcap-collide-")
    try:
        cfg_k = dict(_config.DEFAULTS)
        sdir_k = str(_config.ensure_local_dir(_config.state_dir(_P(tmp_k), cfg_k)))
        path_k = os.path.join(sdir_k, M.SEEN_FILE)
        os.mkdir(path_k + ".tmp")   # that exact name is already someone else's
        M._mark_seen(_P(tmp_k), cfg_k)
        ok_k = os.path.isfile(path_k)
        if ok_k:
            with open(path_k, "r", encoding="utf-8") as fh:
                ok_k = "lastRun" in (json.load(fh) or {})
        check("j3 the marker still lands when `path + \".tmp\"` is occupied - the "
              "naive writer opens that fixed name, raises, and the fail-open "
              "except swallows it, leaving the doctor to read the missing marker "
              "as 'the matchers never reach this hook'", ok_k)
    finally:
        shutil.rmtree(tmp_k, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_guard_capabilities.py --selftest\n")
    raise SystemExit(2)
