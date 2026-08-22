#!/usr/bin/env python3
"""
UserPromptSubmit hook — plan-first opt-out logger + config-error surfacing.

1. Bypass arming. Watches every submitted prompt for the bypass keyword
   (default `#no-plan`, overridable via `.claude/audit.config.json` →
   bypassKeyword, case-insensitive). When present, it ARMS a single-use
   plan-first bypass for the current session (see `_arm_bypass`):
     - writes <stateDir>/plan-bypass-<session_id>.json
       ({ts, reason, armedAtEpoch})
     - appends a line to <logsDir>/plan-bypass.log and a `bypass.armed` line
       to the gate events feed
     - tells the user (systemMessage) that the bypass is live and expires
       unused after 30 minutes (_config.BYPASS_TTL_SECONDS)
   The bypass is later CONSUMED (deleted — single-use) by require-plan.py's
   PostToolUse pass, after a non-trivial edit actually happened; unused past
   the TTL it is treated as never armed and cleaned up there.

2. Config-error surfacing. When `.claude/audit.config.json` exists but is
   malformed, _config.load() falls back to defaults and sets a `_configError`
   marker. A silently broken config means the project's custom secret patterns
   / custom rules / thresholds are NOT applied — so this hook warns the user
   ONCE per session (flag file <stateDir>/config-error-notified-<session>.json).

3. State GC. Session state files (`plan-gate-*`, `tdd-reminder-*`,
   `bash-writes-*`, `config-error-notified-*`, `plan-bypass-*`,
   `journal-preimage-*`, `owner-note-*`) are otherwise never deleted; this hook
   opportunistically removes ones older than 7 days on every prompt —
   stale-session leftovers (and forgotten armed bypasses) expire instead
   of accumulating.

This hook never blocks a prompt. Messages go out as JSON {"systemMessage": ...}
on stdout with exit 0.

Contract: always exit 0. Any unexpected input / exception also exits 0.

This hook carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test_detect_plan_skip.py` (hyphens become underscores - a
hyphenated name is not importable). A test of a hook may import from `scripts/`
even though the hook itself may not; see `plugins/audit/tests/_harness.py`.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


# --- state gc -----------------------------------------------------------------
_GC_PREFIXES = ("plan-gate-", "tdd-reminder-", "bash-writes-",
                "config-error-notified-", "plan-bypass-",
                # journal-writes.py's Pre-pass slot: it holds pre-image BYTES
                # and its normal lifecycle (Post pass consumes it) never runs
                # when a session dies between the two passes (F-B1).
                "journal-preimage-",
                # require-plan.py's ownership-advisory throttle (v0.34 D2):
                # which area tags this session has already been nudged about.
                "owner-note-")
_GC_MAX_AGE = 7 * 86400  # seconds


def _gc_state(state_dir, now=None):
    """Delete session state files older than 7 days. Returns count removed.
    Best-effort — never raises."""
    removed = 0
    try:
        now = now if now is not None else time.time()
        for f in state_dir.glob("*.json"):
            if not f.name.startswith(_GC_PREFIXES):
                continue
            try:
                if now - f.stat().st_mtime > _GC_MAX_AGE:
                    f.unlink()
                    removed += 1
            except Exception:
                continue
    except Exception:
        pass
    return removed


# --- arming the bypass ----------------------------------------------------------
def _arm_bypass(state_dir, logs_dir, session_id,
                keyword, prompt):
    """Arm the single-use plan-first bypass; returns the systemMessage line.

    Extracted from main() so the TTL contract is testable (v0.34 B4). The slot
    carries `armedAtEpoch` as EPOCH SECONDS -- require-plan compares clock to
    clock, with no %z ISO parsing to get wrong -- and both the log line and the
    message say the bypass expires unused after 30 minutes, because a fact that
    changes what the keyword means belongs where the keyword is used."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    snippet = " ".join(prompt.split())[:120]
    minutes = _config.BYPASS_TTL_SECONDS // 60
    _config.ensure_local_dir(state_dir)
    _config.ensure_local_dir(logs_dir)
    with open(state_dir / ("plan-bypass-%s.json" % session_id), "w",
              encoding="utf-8") as fh:
        json.dump({"ts": ts, "reason": snippet,
                   "armedAtEpoch": int(time.time())}, fh)
    with open(logs_dir / "plan-bypass.log", "a", encoding="utf-8") as fh:
        fh.write("%s session=%s bypass armed (single-use, expires unused "
                 "after %d minutes): %s\n" % (ts, session_id, minutes, snippet))
    _config.append_gate_event(logs_dir, {
        "event": "bypass.armed", "reason": snippet, "sessionId": session_id})
    return ("[audit] Plan-first bypass ARMED (%s): the next non-trivial edit "
            "in this session proceeds without a manifest task (single-use, "
            "logged, expires in %d minutes if unused)." % (keyword, minutes))


# --- detection ----------------------------------------------------------------
def _prompt_text(data):
    for key in ("prompt", "user_prompt", "message"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _observed_message(state_dir, session_id, cfg=None):
    """One line naming what the plan gate would have blocked, then never again.

    The tally is written by require-plan.py's observe tier. It is reported once and
    marked notified rather than deleted, so the count keeps accumulating while the
    message does not repeat — a warning that reappears on every turn is a warning
    nobody reads, which is the same reasoning meter-usage applies to its per-task
    advisory. Returns [] on anything unexpected; this is an advisory path.

    WHY observe is in force decides what the line claims (v0.34 B1): with
    planGate: "observe" pinned, "this repo has no audit manifest" may be flatly
    false — the honest sentence names the knob and how to unpin it."""
    try:
        path = state_dir / ("plan-gate-observed-%s.json" % session_id)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fh:
            tally = json.load(fh) or {}
        if not isinstance(tally, dict) or tally.get("notified"):
            return []
        files = [f for f in (tally.get("files") or []) if f]
        if not files:
            return []
        tally["notified"] = True
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(tally, fh)
        except Exception:
            pass
        shown = ", ".join(files[:3])
        more = "" if len(files) <= 3 else " (+%d more)" % (len(files) - 3)
        if _config.plan_gate_knob(cfg) == "observe":
            why = ("It is observing because planGate is set to \"observe\" in "
                   ".claude/audit.config.json - remove the key (or set it to "
                   "\"deny\") to enforce.")
        else:
            why = ("It is observing, not enforcing, because this repo has no "
                   "audit manifest - run /audit:init to turn enforcement on, or "
                   "set \"planGate\": \"deny\" in .claude/audit.config.json to "
                   "enforce without one.")
        return ["[audit] The plan gate would have held %d edit(s) this session: "
                "%s%s. %s" % (len(files), shown, more, why)]
    except Exception:
        return []


# --- cli ----------------------------------------------------------------------
def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    messages = []
    try:
        root = _config.repo_root(data)
        cfg = _config.load(root)
        session_id = str(data.get("session_id", "") or "no-session")
        state_dir = _config.state_dir(root, cfg)

        # --- 0. opportunistic GC of stale session state -----------------------
        _gc_state(state_dir)

        # --- 1. surface a malformed config, once per session -----------------
        err = cfg.get("_configError")
        if err:
            flag = state_dir / ("config-error-notified-%s.json" % session_id)
            if not flag.exists():
                try:
                    _config.ensure_local_dir(state_dir)
                    flag.write_text(json.dumps({"error": str(err)}),
                                    encoding="utf-8")
                except Exception:
                    pass
                messages.append(
                    "[audit] .claude/audit.config.json is malformed (%s). "
                    "Safe defaults are active — the project's custom secret "
                    "patterns, custom rules and thresholds are NOT applied. "
                    "Fix the file to restore them." % err)

        # --- 2. arm the single-use bypass when the keyword is present --------
        keyword = (cfg.get("bypassKeyword")
                   or _config.DEFAULTS["bypassKeyword"]).lower()
        prompt = _prompt_text(data)
        if keyword in prompt.lower():
            messages.append(_arm_bypass(state_dir, _config.logs_dir(root, cfg),
                                        session_id, keyword, prompt))

        # --- 3. report what the plan gate observed, once per session ----------
        # In a repo with no manifest the gate records rather than denies. Saying so
        # once is what makes that tier useful: it demonstrates the guard working on
        # the user's own edits instead of asserting authority over them. Silence
        # here would make observe indistinguishable from the plugin being off.
        messages.extend(_observed_message(state_dir, session_id, cfg=cfg))
    except Exception:
        sys.exit(0)

    if messages:
        try:
            print(json.dumps({"systemMessage": "\n".join(messages)}))
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than fallen through to main(), which would block on stdin
        # waiting for a hook payload that is never coming. It deliberately does NOT
        # print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("detect-plan-skip.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_detect_plan_skip.py - run that file instead.")
        sys.exit(0)
    main()
