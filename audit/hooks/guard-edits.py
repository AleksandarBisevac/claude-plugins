#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Edit|Write|MultiEdit).

Inspects only the *incoming* text (new content) and blocks two classes of change:

  1. Token-logging ban (universal) — logging an auth token via
     console.* / Sentry / remoteLog. The token identifier names come from
     `.claude/audit.config.json` → guardEdits.tokenVars
     (default: accessToken, refreshToken, idToken). Prefix-only debug
     (token.slice(0, 6)) is allowed.

  2. Project custom rules (opt-in) — `.claude/audit.config.json` →
     guardEdits.customRules: a list of
        { "pathPrefix": "libs/x/", "bannedPattern": "<regex>", "message": "<why>" }
     Each rule blocks `bannedPattern` when the edited path starts with `pathPrefix`.
     Example: ban `.removeAllListeners(` under a realtime/subscription dir.
     Ships EMPTY by default — the plugin has no hardcoded project rules.

Contract: exit code 2 + stderr blocks the edit and tells Claude why.
Unexpected input exits 0 (never break legitimate work).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402


def _token_log_re(token_vars):
    """A logger call whose args use a token as a *value* (interpolation / arg / concat
    / object value), not merely a string mentioning the word. `.slice` prefix is allowed."""
    alt = "|".join(re.escape(t) for t in token_vars) or "accessToken"
    return re.compile(
        r"(?:console\.\w+"
        r"|Sentry\.(?:captureMessage|captureException|addBreadcrumb|setExtra|setContext)"
        r"|remoteLog)\s*\("
        r"[^)]*?"
        r"(?:\$\{|,\s*|\+\s*|:\s*)"
        r"(?:" + alt + r")\b"
        r"(?!\s*\.slice)",
        re.IGNORECASE | re.DOTALL,
    )


def _bearer_re(token_vars):
    alt = "|".join(re.escape(t) for t in token_vars + ["token"])
    return re.compile(r"[Bb]earer\s+\$\{?\s*(?:" + alt + r")\b", re.IGNORECASE)


def collect(tool: str, ti: dict):
    path = str(ti.get("file_path", ""))
    chunks = []
    if tool == "Write":
        chunks.append(str(ti.get("content", "")))
    elif tool == "Edit":
        chunks.append(str(ti.get("new_string", "")))
    elif tool == "MultiEdit":
        for e in ti.get("edits", []) or []:
            chunks.append(str(e.get("new_string", "")))
    return path.replace("\\", "/"), "\n".join(chunks)


def block(msg: str) -> None:
    sys.stderr.write("[guard-edits] " + msg + "\n")
    sys.exit(2)


def decide(data: dict, *, cfg=None):
    """Pure decision core. Returns ("allow", reason) or ("block", message)."""
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit"):
        return ("allow", "unknown tool")

    path, text = collect(tool, data.get("tool_input", {}) or {})
    if not text:
        return ("allow", "no text")

    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)

    # 1. project custom rules (opt-in)
    for rule in _config.custom_rules(cfg):
        try:
            prefix = str(rule.get("pathPrefix", ""))
            pattern = str(rule.get("bannedPattern", ""))
            if not prefix or not pattern:
                continue
            if prefix in path and re.search(pattern, text):
                msg = rule.get("message") or (
                    "Blocked by a project custom rule: pattern %r is banned under %s."
                    % (pattern, prefix)
                )
                return ("block", str(msg))
        except Exception:
            continue

    # 2. token-logging ban (universal)
    token_vars = _config.token_vars(cfg)
    if _token_log_re(token_vars).search(text) or _bearer_re(token_vars).search(text):
        return ("block",
                "Blocked: this logs a full auth token.\n"
                "Never log %s / Authorization. For debug, log a prefix only: "
                "token.slice(0, 6) + ' len=' + token.length." % " / ".join(token_vars))

    return ("allow", "clean")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        verdict, msg = decide(data)
    except Exception:
        sys.exit(0)

    if verdict == "block":
        block(msg)
    sys.exit(0)


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    results = []
    # token identifier assembled at runtime so this SOURCE file never contains a
    # literal logger-call-with-token (which the guard itself would flag).
    tok = "access" + "Token"
    cfg = {
        "guardEdits": {
            "tokenVars": ["accessToken", "refreshToken", "idToken"],
            "customRules": [
                {
                    "pathPrefix": "src/realtime/",
                    "bannedPattern": r"\.removeAllListeners\s*\(",
                    "message": "removeAllListeners() nukes sibling listeners — use a ref.",
                }
            ],
        }
    }

    def check(name, expected, tool, path, text):
        data = {"tool_name": tool, "tool_input": {"file_path": path, "content": text}}
        try:
            verdict, _ = decide(data, cfg=cfg)
        except Exception as exc:  # pragma: no cover
            verdict = "EXC:%s" % exc
        ok = verdict == expected
        results.append(ok)
        print("%s %s (expected %s, got %s)"
              % ("PASS" if ok else "FAIL", name, expected, verdict))

    # custom rule fires only under its pathPrefix
    check("c1 removeAllListeners under prefix blocked", "block", "Write",
          "src/realtime/useX.tsx", "qObject.removeAllListeners()")
    check("c2 removeAllListeners elsewhere allowed", "allow", "Write",
          "src/other/useX.tsx", "qObject.removeAllListeners()")
    # token logging
    check("t1 logger with token value blocked", "block", "Write",
          "src/api.ts", "console.log('tok', %s)" % tok)
    check("t2 token prefix debug allowed", "allow", "Write",
          "src/api.ts", "console.log(%s.slice(0,6))" % tok)
    check("t3 innocent code allowed", "allow", "Write",
          "src/api.ts", "const x = 1 + 2;")

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
