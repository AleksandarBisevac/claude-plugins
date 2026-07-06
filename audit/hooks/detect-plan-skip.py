#!/usr/bin/env python3
"""
UserPromptSubmit hook — plan-first opt-out logger.

Watches every submitted prompt for the bypass keyword (default `#bez-plana`,
overridable via `.claude/audit.config.json` → bypassKeyword, case-insensitive).
When present, it ARMS a single-use plan-first bypass for the current session:
  - writes <stateDir>/plan-bypass-<session_id>.json ({ts, reason})
  - appends a line to <logsDir>/plan-bypass.log

The bypass is later CONSUMED (and deleted — single-use) by require-plan.py the
next time a non-trivial edit is attempted. This hook never blocks a prompt.

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

    try:
        root = _config.repo_root(data)
        cfg = _config.load(root)
        keyword = (cfg.get("bypassKeyword") or "#bez-plana").lower()

        prompt = _prompt_text(data)
        if keyword not in prompt.lower():
            sys.exit(0)

        session_id = str(data.get("session_id", "") or "no-session")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
        snippet = " ".join(prompt.split())[:120]

        state_dir = _config.state_dir(root, cfg)
        logs_dir = _config.logs_dir(root, cfg)
        state_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        with open(state_dir / ("plan-bypass-%s.json" % session_id), "w",
                  encoding="utf-8") as fh:
            json.dump({"ts": ts, "reason": snippet}, fh)

        with open(logs_dir / "plan-bypass.log", "a", encoding="utf-8") as fh:
            fh.write("%s session=%s bypass armed: %s\n" % (ts, session_id, snippet))
    except Exception:
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
