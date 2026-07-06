#!/usr/bin/env python3
"""
PreToolUse guard (matcher: Edit|Write|MultiEdit|NotebookEdit).

Inspects the *incoming* text (new content) and the target path, and blocks:

  1. Token-logging ban (universal) — logging an auth token via
     console.* / Sentry / remoteLog. The token identifier names come from
     `.claude/audit.config.json` → guardEdits.tokenVars
     (default: accessToken, refreshToken, idToken). Prefix-only debug
     (token.slice(0, 6)) is allowed.

  2. Project custom rules (opt-in) — `.claude/audit.config.json` →
     guardEdits.customRules: a list of
        { "pathPrefix": "libs/x/", "bannedPattern": "<regex>", "message": "<why>" }
     Each rule blocks `bannedPattern` when the edited path starts with `pathPrefix`.
     Ships EMPTY by default — the plugin has no hardcoded project rules.

  3. Self-edit protection — edits targeting the INSTALLED plugin's own files
     (a model must not modify the hooks that govern it; upstream issue
     anthropics/claude-code#32376). Dev-mode exception: when the plugin
     directory lives INSIDE the consuming repo (a checkout of the plugin's own
     repository), editing is allowed — that's plugin development, not runtime.

  4. Bypass forgery — writing <stateDir>/plan-bypass-*.json directly would arm
     the plan-first opt-out without a user prompt. Those files may only be
     created by detect-plan-skip.py (i.e. by the USER typing the keyword).

Contract: exit code 2 + stderr blocks the edit and tells Claude why.
Unexpected input exits 0 (never break legitimate work).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HOOKS_DIR)


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
    if tool == "NotebookEdit":
        path = str(ti.get("notebook_path", "") or ti.get("file_path", ""))
        return path.replace("\\", "/"), str(ti.get("new_source", ""))
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


def _self_edit_target(path: str, root) -> bool:
    """True when `path` targets the installed plugin's own files while the plugin
    lives OUTSIDE the consuming repo. A plugin checkout inside the project
    (development) is exempt — there the plugin files ARE the project."""
    try:
        plugin_root = os.path.realpath(_PLUGIN_ROOT)
        proj = os.path.realpath(str(root))
        if plugin_root == proj or plugin_root.startswith(proj + os.sep):
            return False  # dev mode: plugin inside the consuming repo
        target = path if os.path.isabs(path) else os.path.join(proj, path)
        target = os.path.realpath(target)
        return target == plugin_root or target.startswith(plugin_root + os.sep)
    except Exception:
        return False


def block(msg: str) -> None:
    sys.stderr.write("[guard-edits] " + msg + "\n")
    sys.exit(2)


def decide(data: dict, *, cfg=None):
    """Pure decision core. Returns ("allow", reason) or ("block", message)."""
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ("allow", "unknown tool")

    path, text = collect(tool, data.get("tool_input", {}) or {})
    root = _config.repo_root(data)
    cfg = cfg if cfg is not None else _config.load(root)

    # path-based blocks first — they apply even to empty/whitespace content
    if path:
        # 3. self-edit protection
        if _self_edit_target(path, root):
            return ("block",
                    "The audit plugin's own files are read-only at runtime "
                    "(self-edit protection): %s\n"
                    "A model must not modify the hooks that govern it. To change "
                    "the plugin, edit it in its own repository checkout." % path)

        # 4. bypass forgery
        state_rel = str(cfg.get("stateDir")
                        or _config.DEFAULTS["stateDir"]).strip("/")
        rel = _config.rel_path(root, path)
        base = rel.rsplit("/", 1)[-1]
        if rel.startswith(state_rel + "/") and base.startswith("plan-bypass-"):
            return ("block",
                    "Writing the plan-first bypass state directly is not allowed "
                    "(bypass forgery): %s\n"
                    "A bypass may only be armed by the USER including the bypass "
                    "keyword in their prompt." % rel)

    if not text:
        return ("allow", "no text")

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
    import tempfile

    results = []
    tmp = tempfile.mkdtemp(prefix="guard-edits-selftest-")
    # token identifier assembled at runtime so this SOURCE file never contains a
    # literal logger-call-with-token (which the guard itself would flag).
    tok = "access" + "Token"
    cfg = _config._deep_merge(_config.DEFAULTS, {
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
    })

    def check(name, expected, tool, path, text, *, cwd=tmp):
        ti = {"file_path": path, "content": text}
        if tool == "NotebookEdit":
            ti = {"notebook_path": path, "new_source": text}
        data = {"tool_name": tool, "tool_input": ti, "cwd": cwd}
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
    # NotebookEdit is covered too
    check("n1 notebook cell logging token blocked", "block", "NotebookEdit",
          "notebooks/train.ipynb", "console.log('t', %s)" % tok)
    check("n2 innocent notebook cell allowed", "allow", "NotebookEdit",
          "notebooks/train.ipynb", "print('hello')")

    # self-edit protection: plugin dir is OUTSIDE the tmp "project" → block,
    # even with empty content
    check("s1 editing an installed plugin file blocked", "block", "Write",
          os.path.join(_HOOKS_DIR, "guard-edits.py"), "tampered")
    check("s2 empty-content write to plugin file blocked", "block", "Write",
          os.path.join(_HOOKS_DIR, "hooks.json"), "")
    # dev mode: when cwd IS the repo containing the plugin → allow
    plugin_repo = os.path.dirname(os.path.dirname(_PLUGIN_ROOT))
    check("s3 dev-mode edit of plugin file allowed", "allow", "Write",
          os.path.join(_HOOKS_DIR, "guard-edits.py"), "dev change",
          cwd=plugin_repo)

    # bypass forgery
    check("f1 writing plan-bypass state blocked", "block", "Write",
          ".claude/state/plan-bypass-abc.json", "{}")
    check("f2 other state files allowed", "allow", "Write",
          ".claude/state/tdd-reminder-abc.json", "{}")

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
