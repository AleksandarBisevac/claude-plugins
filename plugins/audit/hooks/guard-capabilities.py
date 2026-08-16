#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Skill|Task|Agent|mcp__.*).

Enforces the project's `policy` block from `.claude/audit.config.json`: which
skills, subagents and MCP tools may be used in this repository, optionally scoped
to the monorepo areas currently being worked on.

    "policy": {
      "onViolation": "deny",
      "agents": {"default": "deny", "allow": ["audit:*", "code-reviewer"]},
      "mcp":    {"deny": ["mcp__prod-db__*"]}
    }

**The rule itself is not here.** `scripts/_policy.py` owns the resolution order
(required -> deny -> allow -> default), what "inert" means, and every pattern
match; this file is the enforcement half — read the payload, ask that module, emit
the verdict. The panel previews the same answers and the doctor checks them
against the same function, so a policy cannot mean three things on three surfaces.

Costs nothing until a project writes a policy. The shipped block is inert
(everything allowed, no deny anywhere), and `_policy.is_active` is false for it,
so this hook returns BEFORE it reads a manifest.

`onViolation` decides what a violation does, and all three are honest about what
they are:
  deny (default) — the canonical PreToolUse deny; the tool call does not happen.
  ask            — a manual approval prompt: the human decides, per call.
  warn           — the call proceeds and a `systemMessage` says it broke the
                   policy. Deliberately NOT a `permissionDecision: "allow"`, which
                   would BYPASS the permission system and quietly widen what the
                   agent may do — a warning must not grant anything.

Limits, stated because a guard whose reach is overstated is worse than none:
this governs the TOOL, not the knowledge; it holds only while the plugin is
enabled; subagents do not inherit parent hooks on every Claude Code version
(anthropics/claude-code#43772), so inside one a policy may be advisory — the
doctor warns when this hook has never fired; and hooks cannot gate hooks, so
other plugins' hooks are inventoried by the panel, never enforced. See SECURITY.md.

Contract: a block emits {"hookSpecificOutput": {"permissionDecision": "deny",
"permissionDecisionReason": ...}} on stdout and exits 0 — the canonical PreToolUse
protocol. Anything unexpected exits 0 (never break legitimate work).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

# How often the "this hook is dispatching" marker is refreshed. A PreToolUse hook
# on Skill/Agent/MCP runs often; the doctor's question is only ever "has it run
# here recently", so one write an hour answers it for the cost of one stat.
# --- seen marker + payload helpers --------------------------------------------
SEEN_REFRESH_SECONDS = 3600
SEEN_FILE = "capability-guard.json"


def _policy_mod():
    return _config.policy_mod()


def _decision_payload(decision, msg):
    """Canonical PreToolUse payload for a decision ("deny" or "ask")."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": "[guard-capabilities] " + msg,
        }
    }


def _warn_payload(msg):
    """A warning is a `systemMessage`, never a permissionDecision.

    There is no non-blocking `permissionDecision` — `allow` does not mean "carry
    on", it means "skip the permission system" — so a warn tier written that way
    would be an advisory that silently granted more than it found.
    """
    return {"systemMessage": "[guard-capabilities] " + msg}


def _mark_seen(root, cfg):
    """Record that this hook ran with a live policy, for /audit:doctor.

    Only reached once the policy is ACTIVE, which is what makes the file mean
    something: its absence in a repo with a real policy says the matchers are not
    being dispatched to us — the documented subagent case — rather than that
    nobody has used a skill lately. Never raises, and never blocks a decision.
    """
    try:
        state = _config.state_dir(root, cfg)
        path = os.path.join(str(state), SEEN_FILE)
        try:
            if time.time() - os.path.getmtime(path) < SEEN_REFRESH_SECONDS:
                return
        except OSError:
            pass
        _config.ensure_local_dir(state)
        # A UNIQUE temp name in the target dir, never `path + ".tmp"`. Hooks run
        # concurrently - one Edit fans out to seven hook processes - and a fixed
        # temp path means two of them open, truncate and os.replace the SAME
        # file, so the marker lands empty or half-written. Measured at 12-way
        # concurrency: 1167 corrupt reads out of 4800 with the fixed name, 0 with
        # this. The doctor reads this file as evidence, and a corrupt marker is a
        # worse answer than none.
        # The write itself is _config's, not a second copy here: the same defect
        # was live in its gate-events trim, and one statement of the pattern is
        # what stops the next fix from landing in only one of them. It costs this
        # hook nothing - the ~8ms `tempfile` import stays INSIDE that helper, so
        # it is paid only on the rare call that reaches here (at most once an
        # hour), never on the every-tool-call import of _config.
        _config.atomic_write_text(path, json.dumps(
            {"lastRun": _config.utc_stamp()}))
    except Exception:
        pass


def _message(verdict, mode):
    """What the human and the model are told, with the basis that produced it."""
    kind = {"skills": "skill", "agents": "subagent", "mcp": "MCP tool"}.get(
        verdict.get("kind"), verdict.get("kind"))
    head = "%s %r is not allowed in this project: %s." % (
        kind, verdict.get("name"), verdict.get("basis"))
    if mode == "warn":
        return head + " Allowed anyway (policy.onViolation is 'warn')."
    return (head + "\nEdit `policy` in .claude/audit.config.json (or open "
            "/audit:panel) to allow it, or use another tool. Set "
            "policy.onViolation to 'warn' to make this advisory.")


# --- decision -----------------------------------------------------------------
def decide(data, *, cfg=None, active=None):
    """Pure decision core. Returns (action, message) where action is one of
    "allow" (say nothing), "deny", "ask" or "warn".

    Every uncertainty resolves to "allow": no policy engine, an inert policy, an
    unreadable config, a tool this does not govern. A capability guard that fails
    closed would brick a session over a bug in itself.
    """
    pol_mod = _policy_mod()
    if pol_mod is None:
        return ("allow", "no policy engine installed")
    kind, name = pol_mod.capability_of(data.get("tool_name"),
                                       data.get("tool_input") or {})
    if not kind:
        return ("allow", "not a governed tool")
    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)
    policy = pol_mod.policy_cfg(cfg)
    if not pol_mod.is_active(policy):
        return ("allow", "policy is inert")
    _mark_seen(root, cfg)
    if active is None:
        # Only when an area rule could possibly change the answer. Reading the
        # manifest is the expensive half of this hook, and most policies are
        # project-wide.
        active = (_config.active_area_tags(
            root, cfg.get("manifestPath") or _config.DEFAULTS["manifestPath"])
            if _has_area_rules(policy, kind) else [])
    verdict = pol_mod.resolve(policy, kind, name, active_tags=active)
    if verdict.get("verdict") != "violation":
        return ("allow", verdict.get("basis") or "allowed")
    # `policy_cfg` is the sanitiser — an unreadable `onViolation` is already back
    # to the default by the time it gets here. A second fallback in this file
    # would be a second place the answer is decided, and the day one of them
    # learned a fourth mode the other would still be silently choosing deny.
    mode = policy.get("onViolation")
    return (mode, _message(verdict, mode))


def _has_area_rules(policy, kind):
    """Does this kind carry any per-area rule at all? (If not, the manifest read
    that resolves the active areas cannot change the verdict, so it is skipped.)"""
    try:
        areas = ((policy.get(kind) or {}).get("areas") or {})
        return any(isinstance(r, dict) and (r.get("allow") or r.get("deny"))
                   for r in areas.values())
    except Exception:
        return False


# --- cli ----------------------------------------------------------------------
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        action, msg = decide(data)
    except Exception:
        sys.exit(0)
    if action in ("deny", "ask"):
        print(json.dumps(_decision_payload(action, msg)))
    elif action == "warn":
        print(json.dumps(_warn_payload(msg)))
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(bool(ok))
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    tmp = tempfile.mkdtemp(prefix="guard-capabilities-selftest-")
    pol_mod = _policy_mod()
    check("m0 the policy engine is reachable from this hook", pol_mod is not None)
    if pol_mod is None:
        print("\nSELFTEST FAILED: the policy engine did not load")
        return 1

    def cfg_with(policy, **rest):
        base = {"policy": policy}
        base.update(rest)
        return _config._deep_merge(_config.DEFAULTS, base)

    def call(tool, ti, policy=None, active=None, cwd=tmp):
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
        return decide(data, cfg=cfg_with(policy) if policy is not None
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
    blob = json.loads(json.dumps(_decision_payload("deny", "why")))
    hso = blob.get("hookSpecificOutput") or {}
    check("c1 the deny payload is canonical PreToolUse JSON",
          hso.get("hookEventName") == "PreToolUse"
          and hso.get("permissionDecision") == "deny"
          and str(hso.get("permissionDecisionReason", "")).startswith(
              "[guard-capabilities]"))
    check("c2 the ask payload is the same shape with the other decision",
          json.loads(json.dumps(_decision_payload("ask", "w")))
          ["hookSpecificOutput"]["permissionDecision"] == "ask")
    warn = json.loads(json.dumps(_warn_payload("w")))
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
          _has_area_rules(pol_mod.policy_cfg({"policy": area_pol}), "skills") is True
          and _has_area_rules(pol_mod.policy_cfg({"policy": deny_all}), "skills")
          is False
          and _has_area_rules(pol_mod.policy_cfg(
              {"policy": {"skills": {"areas": {"api": {}}}}}), "skills") is False)

    # (f) fail-open, every way in. A capability guard that fails closed over a bug
    # in itself would brick a session.
    check("f1 garbage payloads allow", decide({})[0] == "allow"
          and decide({"tool_name": None, "tool_input": None})[0] == "allow")
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
                            SEEN_FILE)
        decide({"tool_name": "Skill", "tool_input": {"skill": "x"},
                "cwd": seen_root}, cfg=cfg, active=[])
        check("g1 a live policy leaves the marker the doctor reads",
              os.path.isfile(path))
        first = os.path.getmtime(path)
        os.utime(path, (first - 10, first - 10))
        decide({"tool_name": "Skill", "tool_input": {"skill": "y"},
                "cwd": seen_root}, cfg=cfg, active=[])
        check("g2 ...refreshed at most once an hour, not once per tool call",
              os.path.getmtime(path) == first - 10)
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        inert = _config._deep_merge(_config.DEFAULTS, {})
        decide({"tool_name": "Skill", "tool_input": {"skill": "x"},
                "cwd": seen_root}, cfg=inert, active=[])
        check("g3 an inert policy writes nothing - the marker means 'the guard ran "
              "with a policy to enforce', which is the only reading that makes its "
              "absence evidence", not os.path.exists(path))
    finally:
        shutil.rmtree(seen_root, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)
    # (i) the seen-file's state dir is self-ignoring
    from pathlib import Path as _P
    tmp_i = tempfile.mkdtemp(prefix="gcap-ignore-")
    try:
        _cfg_i = dict(_config.DEFAULTS)
        _mark_seen(_P(tmp_i), _cfg_i)
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
        path_j = os.path.join(sdir_j, SEEN_FILE)
        handed_over = []
        _real_replace = os.replace

        def _spy_replace(src, dst):
            handed_over.append(str(src))
            return _real_replace(src, dst)

        os.replace = _spy_replace
        try:
            _mark_seen(_P(tmp_j), cfg_j)
            # Backdate rather than delete, so a broken first write leaves the
            # second call reachable and the cases below run instead of dying.
            try:
                stale = os.path.getmtime(path_j) - 2 * SEEN_REFRESH_SECONDS
                os.utime(path_j, (stale, stale))
            except OSError:
                pass
            _mark_seen(_P(tmp_j), cfg_j)
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
        path_k = os.path.join(sdir_k, SEEN_FILE)
        os.mkdir(path_k + ".tmp")   # that exact name is already someone else's
        _mark_seen(_P(tmp_k), cfg_k)
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

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
