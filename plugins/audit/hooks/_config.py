#!/usr/bin/env python3
"""
Shared config loader for the audit plugin's hooks.

Every hook reads an OPTIONAL per-repo config file from the *consuming* repo at
`${CLAUDE_PROJECT_DIR}/.claude/audit.config.json`. When the file is absent or
malformed, safe generic defaults apply — so the plugin works out-of-the-box and
each project scales it up by dropping in that one file (Layer 1 of the plugin's
extensibility model; see the plugin README "Extending" section).

Design contract (matches the hooks): NOTHING here ever raises. On any error we
return defaults. Hooks must never break legitimate work because of config.

Config keys (all optional; defaults in DEFAULTS below):
  manifestPath            str   — path to the audit manifest, repo-relative
  exemptGlobs             [str] — globs exempt from plan-first enforcement
  trivialLineThreshold    int   — max added lines for the 1st free code file/session
  stateDir                str   — where per-session state files live
  logsDir                 str   — where the bypass log lives
  bypassKeyword           str   — the single-use plan-first opt-out keyword
  secretPatterns.extra    [str] — additional regexes treated as secret file paths
  guardEdits.tokenVars    [str] — identifier names treated as auth tokens (logging ban)
  guardEdits.customRules  [obj] — project-specific banned-pattern rules, each:
        { "pathPrefix": "libs/x/", "bannedPattern": "<regex>", "message": "<why>" }
"""
import json
import os
from pathlib import Path

CONFIG_REL = ".claude/audit.config.json"

DEFAULTS = {
    "manifestPath": "docs/audit/audit-plan.json",
    "exemptGlobs": [
        "docs/audit/**",
        "**/*.md",
        ".claude/**",
        "**/*.spec.*",
        "**/*.test.*",
    ],
    "trivialLineThreshold": 80,
    "stateDir": ".claude/state",
    "logsDir": ".claude/logs",
    "bypassKeyword": "#no-plan",
    "secretPatterns": {"extra": []},
    "guardEdits": {
        "tokenVars": ["accessToken", "refreshToken", "idToken"],
        "customRules": [],
    },
}


def repo_root(data):
    """Locate the CONSUMING repo root: CLAUDE_PROJECT_DIR, else stdin cwd, else getcwd."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        root = (data or {}).get("cwd") or ""
    if not root:
        root = os.getcwd()
    return Path(root)


def _deep_merge(base, over):
    """Shallow-per-key deep merge: nested dicts merged one level, others replaced."""
    out = dict(base)
    if not isinstance(over, dict):
        return out
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def load(root):
    """Return the merged config dict for `root`. Never raises; defaults on any error."""
    try:
        cfg_path = root / CONFIG_REL
        with open(cfg_path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        return _deep_merge(DEFAULTS, user)
    except Exception:
        return dict(DEFAULTS)


# Convenience typed getters (defensive; never raise) --------------------------
def state_dir(root, cfg):
    return root / (cfg.get("stateDir") or DEFAULTS["stateDir"])


def logs_dir(root, cfg):
    return root / (cfg.get("logsDir") or DEFAULTS["logsDir"])


def token_vars(cfg):
    try:
        tv = (cfg.get("guardEdits") or {}).get("tokenVars")
        return tv if isinstance(tv, list) and tv else DEFAULTS["guardEdits"]["tokenVars"]
    except Exception:
        return DEFAULTS["guardEdits"]["tokenVars"]


def custom_rules(cfg):
    try:
        cr = (cfg.get("guardEdits") or {}).get("customRules")
        return cr if isinstance(cr, list) else []
    except Exception:
        return []


def extra_secret_patterns(cfg):
    try:
        ex = (cfg.get("secretPatterns") or {}).get("extra")
        return ex if isinstance(ex, list) else []
    except Exception:
        return []
