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
  tddReminder             obj   — non-blocking TDD nudge (remind-tdd.py):
        enabled (bool), sourceGlobs [str], testGlobs [str], throttleMinutes (int),
        inProgressPolicy ("skip-gate-only" | "skip-all" | "warn-always")

This module also hosts the path/manifest helpers shared by require-plan.py and
remind-tdd.py (rel_path, matches_exempt, strip_line_suffix, in_progress_*).
"""
import fnmatch
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
    "tddReminder": {
        "enabled": True,
        "sourceGlobs": [
            "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.py", "**/*.go",
            "**/*.rb", "**/*.java", "**/*.cs", "**/*.kt", "**/*.swift", "**/*.rs",
        ],
        "testGlobs": [
            "**/*.test.*", "**/*.spec.*", "**/test_*.py", "**/*_test.*",
            "**/__tests__/**", "**/tests/**",
        ],
        "throttleMinutes": 10,
        "inProgressPolicy": "skip-gate-only",
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


def tdd_reminder(cfg):
    try:
        tr = (cfg or {}).get("tddReminder")
        merged = dict(DEFAULTS["tddReminder"])
        if isinstance(tr, dict):
            merged.update(tr)
        return merged
    except Exception:
        return dict(DEFAULTS["tddReminder"])


# Shared path/manifest helpers (require-plan.py + remind-tdd.py) ---------------
def rel_path(root, file_path):
    """Path of file_path RELATIVE to repo root, posix-style. Falls back gracefully."""
    fp = str(file_path).replace("\\", "/")
    try:
        p = Path(fp)
        if not p.is_absolute():
            p = (Path(root) / p)
        rel = os.path.relpath(str(p), str(root))
    except Exception:
        rel = fp
    return rel.replace("\\", "/")


def matches_exempt(rel, globs):
    """Generic glob matcher that understands the common `**` forms.

    Handles:  `dir/**` (recursive prefix), `**/*.ext` (basename), and plain fnmatch.
    """
    base = rel.split("/")[-1]
    for g in globs or ():
        g = str(g)
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(base, g):
            return True
        # `some/dir/**` → recursive prefix match
        if g.endswith("/**"):
            prefix = g[:-3]
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
        # `**/*.ext` or `**/name` → match against the basename
        if g.startswith("**/"):
            if fnmatch.fnmatch(base, g[3:]):
                return True
        # `**/dir/**` → match any path segment sequence
        if g.startswith("**/") and g.endswith("/**"):
            seg = g[3:-3]
            if seg and ("/" + rel + "/").find("/" + seg + "/") != -1:
                return True
    return False


def strip_line_suffix(entry):
    """`a/b.tsx:291-294,308` -> `a/b.tsx`."""
    s = str(entry).replace("\\", "/")
    return s.split(":", 1)[0]


def in_progress_task_map(root, manifest_rel):
    """Rel-file -> [{"taskId", "testsMode"}] for tasks whose status == 'in_progress',
    including fileIndex siblings keyed by the same task ids. Empty dict on any error."""
    out = {}
    try:
        with open(Path(root) / manifest_rel, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        return out

    modes = {}  # in_progress task id -> tests.mode (or None)
    try:
        for phase in manifest.get("phases", []) or []:
            for task in phase.get("tasks", []) or []:
                if task.get("status") != "in_progress":
                    continue
                tid = task.get("id")
                tests = task.get("tests")
                mode = tests.get("mode") if isinstance(tests, dict) else None
                if tid:
                    modes[tid] = mode
                entry = {"taskId": tid, "testsMode": mode}
                for f in task.get("files", []) or []:
                    out.setdefault(strip_line_suffix(f), []).append(entry)
    except Exception:
        pass

    try:
        for fpath, task_ids in (manifest.get("fileIndex", {}) or {}).items():
            for tid in task_ids or []:
                if tid in modes:
                    rel = strip_line_suffix(fpath)
                    entry = {"taskId": tid, "testsMode": modes[tid]}
                    if entry not in out.get(rel, []):
                        out.setdefault(rel, []).append(entry)
    except Exception:
        pass

    return out


def in_progress_files(root, manifest_rel):
    """Set of rel files covered by in_progress tasks (wrapper around the map)."""
    try:
        return set(in_progress_task_map(root, manifest_rel).keys())
    except Exception:
        return set()
