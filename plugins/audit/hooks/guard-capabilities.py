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

This hook carries no `--selftest` of its own any more; its 30 cases live in
`plugins/audit/tests/test_guard_capabilities.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
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


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("guard-capabilities.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_guard_capabilities.py - run that file instead.")
        sys.exit(0)
    main()
