#!/usr/bin/env python3
"""
UserPromptSubmit hook — plan-first opt-out logger + config-error surfacing.

1. Bypass arming. Watches every submitted prompt for the bypass keyword
   (default `#no-plan`, overridable via `.claude/audit.config.json` →
   bypassKeyword, case-insensitive). When present, it ARMS a single-use
   plan-first bypass for the current session:
     - writes <stateDir>/plan-bypass-<session_id>.json ({ts, reason})
     - appends a line to <logsDir>/plan-bypass.log
     - tells the user (systemMessage) that the bypass is live
   The bypass is later CONSUMED (deleted — single-use) by require-plan.py's
   PostToolUse pass, after a non-trivial edit actually happened.

2. Config-error surfacing. When `.claude/audit.config.json` exists but is
   malformed, _config.load() falls back to defaults and sets a `_configError`
   marker. A silently broken config means the project's custom secret patterns
   / custom rules / thresholds are NOT applied — so this hook warns the user
   ONCE per session (flag file <stateDir>/config-error-notified-<session>.json).

This hook never blocks a prompt. Messages go out as JSON {"systemMessage": ...}
on stdout with exit 0.

Contract: always exit 0. Any unexpected input / exception also exits 0.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


def _prompt_text(data: dict) -> str:
    for key in ("prompt", "user_prompt", "message"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def main() -> None:
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

        # --- 1. surface a malformed config, once per session -----------------
        err = cfg.get("_configError")
        if err:
            flag = state_dir / ("config-error-notified-%s.json" % session_id)
            if not flag.exists():
                try:
                    state_dir.mkdir(parents=True, exist_ok=True)
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
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
            snippet = " ".join(prompt.split())[:120]

            logs_dir = _config.logs_dir(root, cfg)
            state_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            with open(state_dir / ("plan-bypass-%s.json" % session_id), "w",
                      encoding="utf-8") as fh:
                json.dump({"ts": ts, "reason": snippet}, fh)

            with open(logs_dir / "plan-bypass.log", "a", encoding="utf-8") as fh:
                fh.write("%s session=%s bypass armed: %s\n"
                         % (ts, session_id, snippet))

            messages.append(
                "[audit] Plan-first bypass ARMED (%s): the next non-trivial "
                "edit in this session proceeds without a manifest task "
                "(single-use, logged)." % keyword)
    except Exception:
        sys.exit(0)

    if messages:
        try:
            print(json.dumps({"systemMessage": "\n".join(messages)}))
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
