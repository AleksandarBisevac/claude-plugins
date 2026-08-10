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

A PRESENT-but-malformed config is different from an ABSENT one: silently falling
back to defaults would deactivate the project's custom secret patterns / custom
rules / thresholds with zero signal. `load()` therefore adds a `_configError`
marker (string) to the returned defaults in that case, and detect-plan-skip.py
surfaces it once per session. Keys starting with `_` are internal — never read
them as configuration.

Config keys (all optional; defaults in DEFAULTS below):
  manifestPath            str   — path to the audit manifest, repo-relative
  gitRoot                 str   — path (relative to the project dir) of the git
                                  repo root, where guard-bash-writes runs git.
                                  Default '.' (project dir IS the git root).
                                  Keep in sync with the manifest's meta.gitRoot.
  exemptGlobs             [str] — globs exempt from plan-first enforcement
  enforce                 bool  — force the plan gate to DENY regardless of evidence.
                                  Default false, which grades the gate: observe with
                                  no manifest, warn with a manifest but nothing
                                  running, deny once a phase is in_progress. Set true
                                  to get always-on deny (the pre-0.20 behaviour).
                                  Only the PLAN gate is graded — the secret guards
                                  deny by default either way, because reading .env is
                                  wrong whether or not a plan exists.
  trivialLineThreshold    int   — max added lines for the 1st free code file/session
  stateDir                str   — where per-session state files live
  logsDir                 str   — where the bypass log lives
  bypassKeyword           str   — the single-use plan-first opt-out keyword
  secretPatterns.extra    [str] — additional regexes treated as secret file paths
  guardEdits.tokenVars    [str] — identifier names treated as auth tokens (logging ban)
  guardEdits.customRules  [obj] — project-specific banned-pattern rules, each:
        { "pathPrefix": "libs/x/", "bannedPattern": "<regex>", "message": "<why>" }
        `pathPrefix` is matched as a SUBSTRING of the path the edit tool reported
        (usually absolute), not as a prefix — see guard-edits.py, which owns the
        rule and pins it in its selftest.
  bashWriteCheck.enabled  bool  — PostToolUse git-status diff check for shell
        writes into source files (guard-bash-writes.py); default true
  tddReminder             obj   — non-blocking TDD nudge (remind-tdd.py):
        enabled (bool), sourceGlobs [str], testGlobs [str], throttleMinutes (int),
        inProgressPolicy ("skip-gate-only" | "skip-all" | "warn-always")
  usage                   obj   — token metering (meter-usage.py, /audit:usage):
        enabled (bool), ledgerDir (str), authorMode ("email"|"name"|"hash"|"none"),
        showCost (bool), backfillOnFirstRun (bool), maxScanBytes (int),
        currency (str), pricingAsOf (str), pricing (obj: model -> USD per MTok),
        bands (obj: highUSD / outlierUSD, both null = calibrate from the project)
  journal                 obj   — the tamper-evident audit trail (audit-journal.py,
        journal-writes.py): enabled (bool), dir (str or null = beside the manifest)
  policy                  obj   — which skills, subagents and MCP tools may be used
        here (guard-capabilities.py): enabled (bool), onViolation
        ("deny"|"ask"|"warn"), and one block per kind (skills/agents/mcp) of
        {default: "allow"|"deny", allow: [pattern], deny: [pattern],
        areas: {tag: {allow, deny}}}. The shape, the defaults and the resolution
        all live in scripts/_policy.py — see DEFAULTS below for why they are not
        restated here.

This module also hosts the path/manifest helpers shared by require-plan.py and
remind-tdd.py (rel_path, matches_exempt, strip_line_suffix, in_progress_*).

Hooks never statically `import` anything from scripts/, this module included: they
run on every tool call, launched by a process that may not have scripts/ on its
sys.path, so scripts/-owned features (policy, journal, manifest assembly) are
loaded by path via `_load_scripts_module` and treated as optional, not required.
"""
import copy
import fnmatch
import json
import os
import sys
from pathlib import Path

CONFIG_REL = ".claude/audit.config.json"

# --- defaults -----------------------------------------------------------------
DEFAULTS = {
    "manifestPath": "docs/audit/audit-plan.json",
    "gitRoot": ".",
    # The test-file exemption exists so red-first TDD stays frictionless: the first
    # act of a red-first fix is writing a test that FAILS, and a gate that blocks
    # that blocks the discipline this plugin ships.
    #
    # It only ever recognised the JavaScript spelling. `*.test.js` and `*.spec.ts`
    # were exempt while `test_cart.py` — Python's dominant convention, and what both
    # unittest and pytest discover by default — was denied, as was `cart_test.go`,
    # which is not a convention in Go but a REQUIREMENT of the toolchain. A Python
    # or Go consumer got the opposite of the intended behaviour, and this repo never
    # saw it because it dogfoods on its own manifest where every test lives inside a
    # task's `files`. Found by running the pipeline end to end in a sandbox project.
    #
    # The suffix pair covers Go, Python, Ruby and Elixir at once; the prefix form is
    # Python's alone. This widens an already-documented bypass class (SECURITY.md,
    # "Test-file exemption") rather than opening a new one — the same compensations
    # apply: remind-tdd stays visible and the phase review gate still reads the diff.
    "exemptGlobs": [
        "docs/audit/**",
        "**/*.md",
        ".claude/**",
        "**/*.spec.*",
        "**/*.test.*",
        "**/*_test.*",
        "**/*_spec.*",
        "**/test_*.*",
    ],
    # false grades the plan gate by evidence; true restores always-on deny.
    "enforce": False,
    "trivialLineThreshold": 80,
    "stateDir": ".claude/state",
    "logsDir": ".claude/logs",
    "bypassKeyword": "#no-plan",
    "secretPatterns": {"extra": []},
    "guardEdits": {
        "tokenVars": ["accessToken", "refreshToken", "idToken"],
        "customRules": [],
    },
    "bashWriteCheck": {"enabled": True},
    "tddReminder": {
        "enabled": True,
        "sourceGlobs": [
            "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.py", "**/*.go",
            "**/*.rb", "**/*.java", "**/*.cs", "**/*.kt", "**/*.swift", "**/*.rs",
            "**/*.ipynb",
        ],
        "testGlobs": [
            "**/*.test.*", "**/*.spec.*", "**/test_*.py", "**/*_test.*",
            "**/__tests__/**", "**/tests/**",
        ],
        "throttleMinutes": 10,
        "inProgressPolicy": "skip-gate-only",
    },
    # Token metering. `pricing` is USD per MILLION tokens and lives in config on
    # purpose: model rates change, and a stale rate should be a one-line fix in the
    # consuming repo rather than a plugin release. Cache rates follow the published
    # multipliers off base input — write 1.25x at the 5-minute TTL, 2x at the
    # 1-hour TTL, read 0.1x. Keep in sync with scripts/usage_ledger.py
    # DEFAULT_PRICING, which mirrors this so the module works standalone.
    "usage": {
        "enabled": True,
        "ledgerDir": ".claude/usage",
        "authorMode": "email",
        "showCost": True,
        "backfillOnFirstRun": True,
        "maxScanBytes": 33554432,
        "currency": "USD",
        "pricingAsOf": "2026-08-06",
        # Cost bands. Empty by default on purpose: with no thresholds set the
        # analytics calibrate from the project's own completed tasks (median/p90),
        # which means something on day one and needs no guess. Set both to pin
        # absolute dollar thresholds instead — `highUSD` must be <= `outlierUSD`,
        # and a malformed pair falls back to the relative basis rather than
        # classifying anything wrongly. NOT named "risk": tasks already carry a
        # `risk` field meaning risk of the change.
        "bands": {"highUSD": None, "outlierUSD": None},
        # `_default` is Opus-tier on purpose: an unrecognized model is far more
        # likely to be a new frontier release than a cheap one, and over-stating
        # spend is the safer error for a cost display.
        "pricing": {
            "_default":          {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-fable-5":    {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
            "claude-mythos-5":   {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
            "claude-opus-5":     {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-8":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-7":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-6":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-5":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-sonnet-5":   {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
            "claude-sonnet-4-6": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
            "claude-sonnet-4-5": {"in":  3.0, "out": 15.0, "cacheW5m":  3.75, "cacheW1h":  6.0, "cacheR": 0.3},
            "claude-haiku-4-5":  {"in":  1.0, "out":  5.0, "cacheW5m":  1.25, "cacheW1h":  2.0, "cacheR": 0.1},
        },
    },
    # The audit trail. `dir` is null on purpose rather than a literal path: the
    # journal belongs beside the manifest, so it travels with a repo that moved its
    # plan and is committed by the same commit that carries the change it records.
    # scripts/audit-journal.py owns the resolution; journal_dir() below is the one
    # copy of it the hooks read, and its selftest pins the two together.
    "journal": {"enabled": True, "dir": None},
}


# --- config load --------------------------------------------------------------
def _load_scripts_module(name, filename):
    """Load a sibling module out of ../scripts by path. None when it cannot be
    loaded — every caller reads that as "the feature this module owns is not
    installed" rather than raising into a hook."""
    try:
        import importlib.util
        scripts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(scripts_dir, filename))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# The capability policy's defaults are NOT written out here. scripts/_policy.py owns
# the block — its shape, its resolution order and what "inert" means — and a second
# copy of the shipped values in this file is the drift this repository has already
# shipped once (`exemptGlobs` and `tddReminder.testGlobs` disagreeing about what a
# test file is). So DEFAULTS carries that module's own dict, and `policy_cfg` below
# delegates rather than merging by hand. If the module is missing there is no policy
# engine at all, and the key is simply absent — which every reader treats as "allow",
# the same fail-open the rest of this file uses.
_POLICY_MOD = _load_scripts_module("audit_policy", "_policy.py")
if _POLICY_MOD is not None:
    DEFAULTS["policy"] = copy.deepcopy(_POLICY_MOD.DEFAULTS)


def repo_root(data):
    """Locate the CONSUMING repo root: CLAUDE_PROJECT_DIR, else stdin cwd, else getcwd."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        root = (data or {}).get("cwd") or ""
    if not root:
        root = os.getcwd()
    return Path(root)


def _deep_merge(base, over):
    """Shallow-per-key deep merge: nested dicts merged one level, others replaced.

    The result NEVER aliases `base` (everything is deep-copied), so callers may
    mutate the returned dict without corrupting module-global DEFAULTS."""
    out = copy.deepcopy(base)
    if not isinstance(over, dict):
        return out
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(copy.deepcopy(v))
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(root):
    """Return the merged config dict for `root`. Never raises.

    - Config file ABSENT → pure defaults, silently (the normal zero-config case).
    - Config file PRESENT but unreadable / malformed / not a JSON object →
      defaults PLUS a `_configError` marker describing the problem, so hooks can
      surface it instead of silently dropping the project's customizations.
    """
    try:
        cfg_path = Path(root) / CONFIG_REL
    except Exception:
        return copy.deepcopy(DEFAULTS)
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
    except (FileNotFoundError, NotADirectoryError):
        return copy.deepcopy(DEFAULTS)
    except Exception as exc:
        out = copy.deepcopy(DEFAULTS)
        out["_configError"] = "%s: %s" % (type(exc).__name__, exc)
        return out
    if not isinstance(user, dict):
        out = copy.deepcopy(DEFAULTS)
        out["_configError"] = (
            "config root is %s, expected a JSON object" % type(user).__name__
        )
        return out
    return _deep_merge(DEFAULTS, user)


# --- git / paths --------------------------------------------------------------
# Convenience typed getters (defensive; never raise) --------------------------
def git_root_dir(root, cfg):
    """Absolute path of the git repository root: <project dir>/<cfg.gitRoot>.
    Defaults to the project dir itself ('.')."""
    gr = (cfg.get("gitRoot") or ".").strip()
    if gr in ("", "."):
        return Path(root)
    return Path(root) / gr


def git_root_rel(cfg):
    """The gitRoot path prefix ('' when the project dir IS the git root)."""
    gr = (cfg.get("gitRoot") or ".").strip().replace("\\", "/").strip("/")
    return "" if gr in ("", ".") else gr


def state_dir(root, cfg):
    return root / (cfg.get("stateDir") or DEFAULTS["stateDir"])


def logs_dir(root, cfg):
    return root / (cfg.get("logsDir") or DEFAULTS["logsDir"])


# --- usage / ledger -----------------------------------------------------------
def usage_cfg(cfg):
    """The merged `usage` block, defaults filled in. Never raises."""
    try:
        merged = copy.deepcopy(DEFAULTS["usage"])
        block = (cfg or {}).get("usage")
        if isinstance(block, dict):
            for k, v in block.items():
                if k == "pricing" and isinstance(v, dict):
                    merged["pricing"].update(copy.deepcopy(v))
                else:
                    merged[k] = copy.deepcopy(v)
        return merged
    except Exception:
        return copy.deepcopy(DEFAULTS["usage"])


def usage_enabled(cfg):
    try:
        return bool(usage_cfg(cfg).get("enabled", True))
    except Exception:
        return True


def ledger_dir(root, cfg):
    """Absolute path of the usage ledger directory (repo-relative in config).

    Deliberately NOT under `stateDir`: that tree is garbage-collected after 7 days
    by detect-plan-skip.py, and the ledger's scan cursors must outlive it or a lost
    cursor would re-scan from offset 0 and double-count."""
    return Path(root) / (usage_cfg(cfg).get("ledgerDir")
                         or DEFAULTS["usage"]["ledgerDir"])


# --- journal ------------------------------------------------------------------
_JOURNAL_LIB = {"tried": False, "mod": None}


def _load_journal_lib():
    """scripts/audit-journal.py, loaded by path and cached — the same pattern as
    _load_lock_lib, and for the same reason: the journal's own module owns where a
    journal lives and what a row means, and a second copy of that rule in here is
    two implementations that can disagree. None when it cannot be loaded, which
    every caller reads as "there is no journal", because without that module
    nothing can write one."""
    if not _JOURNAL_LIB["tried"]:
        _JOURNAL_LIB["tried"] = True
        _JOURNAL_LIB["mod"] = _load_scripts_module("audit_journal",
                                                   "audit-journal.py")
    return _JOURNAL_LIB["mod"]


def journal_enabled(cfg):
    """`journal.enabled`, default true (a non-bool is ignored, not trusted)."""
    try:
        block = (cfg or {}).get("journal")
        if isinstance(block, dict) and isinstance(block.get("enabled"), bool):
            return block["enabled"]
    except Exception:
        pass
    return bool(DEFAULTS["journal"]["enabled"])


def journal_dir(root, cfg):
    """Absolute path of the journal directory, or None when there can be no
    journal (the module is unavailable). `journal.dir` when set, else
    `<manifest dir>/journal`."""
    mod = _load_journal_lib()
    if mod is None:
        return None
    try:
        return Path(mod.journal_dir(str(root), cfg or {}))
    except Exception:
        return None


def in_journal(root, cfg, path):
    """True when `path` (absolute or project-relative) is inside the journal.

    The journal is append-only: it is written by the plugin, never by hand, and
    this is what the edit guards ask before refusing a write to it."""
    try:
        d = journal_dir(root, cfg)
        if d is None:
            return False
        target = path if os.path.isabs(str(path)) else os.path.join(str(root), str(path))
        target = os.path.realpath(target)
        d = os.path.realpath(str(d))
        return target == d or target.startswith(d + os.sep)
    except Exception:
        return False


# --- policy -------------------------------------------------------------------
def policy_mod():
    """scripts/_policy.py, or None when this install has no policy engine."""
    return _POLICY_MOD


def policy_cfg(cfg):
    """The merged `policy` block, or None when there is no policy engine here.

    Delegates to `_policy.policy_cfg` for the same reason `journal_dir` delegates
    to audit-journal: the module that resolves a policy owns what an absent key
    means, and a second merge in this file would be free to disagree with it.
    """
    if _POLICY_MOD is None:
        return None
    try:
        return _POLICY_MOD.policy_cfg(cfg or {})
    except Exception:
        return None


# --- areas --------------------------------------------------------------------
_AREAS_LIB = {"tried": False, "mod": None}


def _areas_lib():
    """scripts/_areas.py, loaded once — the same caching `_load_journal_lib` uses,
    and for the plainer reason: this sits behind a blocking guard, and executing a
    module per tool call to normalise a list of tags is work nobody asked for."""
    if not _AREAS_LIB["tried"]:
        _AREAS_LIB["tried"] = True
        _AREAS_LIB["mod"] = _load_scripts_module("audit_areas", "_areas.py")
    return _AREAS_LIB["mod"]


def active_area_tags(root, manifest_rel):
    """The `meta.areas` tags of phases with work in progress, in manifest order.

    This is what scopes a per-area policy rule. A hook is handed a tool name and
    nothing else — no directory, no file — so "this rule applies to the API area"
    can only mean "while the API area is being worked on". The evidence is the same
    one the plan gate grades itself on: a phase (or one of its tasks) is
    `in_progress`.

    Reads the ASSEMBLED manifest, which is load-bearing under the sharded layout —
    the index stubs carry no status, so a raw read would report nothing running and
    every area rule would be silently inert. Empty list on any error, which resolves
    to the policy without its area rules: fail-open, like everything else here.
    """
    tags = []
    try:
        manifest = _load_manifest_assembled(Path(root) / manifest_rel)
        if not isinstance(manifest, dict):
            return tags
        areas = _areas_lib()
        for phase in manifest.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            running = phase.get("status") == "in_progress" or any(
                isinstance(t, dict) and t.get("status") == "in_progress"
                for t in (phase.get("tasks") or []))
            if not running:
                continue
            of = areas.areas_of if areas is not None else _areas_of_fallback
            for tag in of(phase.get("area")):
                if tag not in tags:
                    tags.append(tag)
    except Exception:
        return tags
    return tags


def _areas_of_fallback(area):
    """`_areas.areas_of` when scripts/_areas.py cannot be loaded. Deliberately the
    same normalisation (trim, drop empties, dedupe) and nothing more — the module
    is the source of truth and this exists only so a missing file degrades to a
    plain reading of the tag rather than to no tags at all."""
    raw = [area] if isinstance(area, str) else (area if isinstance(area, list) else [])
    out = []
    for tag in raw:
        t = tag.strip() if isinstance(tag, str) else ""
        if t and t not in out:
            out.append(t)
    return out


# --- guard config (edits / secrets / tdd) -------------------------------------
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
        merged = copy.deepcopy(DEFAULTS["tddReminder"])
        if isinstance(tr, dict):
            merged.update(copy.deepcopy(tr))
        return merged
    except Exception:
        return copy.deepcopy(DEFAULTS["tddReminder"])


def bash_write_check_enabled(cfg):
    try:
        bw = (cfg or {}).get("bashWriteCheck")
        if isinstance(bw, dict) and "enabled" in bw:
            return bool(bw["enabled"])
    except Exception:
        pass
    return True


def source_exts(cfg):
    """Source-file extensions derived from tddReminder.sourceGlobs
    (`**/*.ts` → `.ts`) — ONE place defines what 'source' means for the
    shell-write guards and the TDD nudge alike."""
    exts = set()
    try:
        for g in tdd_reminder(cfg).get("sourceGlobs") or []:
            g = str(g)
            if g.startswith("**/*."):
                exts.add(g[4:].lower())
    except Exception:
        pass
    return exts or {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rb",
                    ".java", ".cs", ".kt", ".swift", ".rs"}


# --- path / manifest helpers --------------------------------------------------
# Shared by require-plan.py + remind-tdd.py.
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


# --- manifest state -----------------------------------------------------------
def _load_manifest_assembled(path):
    """Read the manifest as ONE assembled dict, handling BOTH storage layouts —
    the legacy single file and the index+per-phase-shards form. Prefers
    scripts/_manifest_io (the single source of truth for assembly); if that module
    is somehow unavailable it FALLS BACK to a plain single-file read, so this
    blocking-hook read path never regresses. Returns {} on any error (never raises)."""
    try:
        scripts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import _manifest_io  # noqa: E402  (dependency-free; imports only json+os)
        return _manifest_io.load_manifest_safe(str(path))
    except Exception:
        pass
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_lock_lib():
    """Load scripts/audit-lock.py by path — same pattern as _load_manifest_assembled
    and meter-usage's ledger load. None if it cannot be loaded; every caller treats
    that as "no verdict" and allows."""
    return _load_scripts_module("audit_lock", "audit-lock.py")


def governing_lock(manifest_rel, rel):
    """Which lock covers a write to `rel`: 'index', 'phase-<id>', or None.

    Mirrors the orchestrator's two tiers. Only manifest paths have a governing
    lock — everything else in the repo is the plan gate's business, not the
    lock's."""
    if not rel or not manifest_rel:
        return None
    if rel == manifest_rel:
        return "index"
    mdir = os.path.dirname(manifest_rel)
    shards = (mdir + "/" if mdir else "") + "phases/"
    if rel.startswith(shards) and rel.endswith(".json"):
        phase_id = rel[len(shards):-len(".json")]
        if phase_id and "/" not in phase_id:
            return "phase-" + phase_id
    return None


def _own_identities(session_id):
    """Every id that means "this same Claude Code process took that lock".

    There is more than one, and assuming otherwise nearly shipped a gate that
    denied the orchestrator its own writes. The lock is taken from **Bash**, which
    reads `$CLAUDE_CODE_SESSION_ID`; the decision is made in a **hook**, which is
    handed `session_id` in its payload. Measured in a live session, those two are
    NOT the same value:

        $CLAUDE_CODE_SESSION_ID  ad510b54-c8d8-400c-9d3c-f227e85b50f9
        hook payload session_id  f6cea720-f3ff-4de5-aef8-8ac328782d7a

    So a run would have locked as one identity and then been refused as another.
    Selftests could never catch it — they pass explicit ids to both sides.

    What saves it is that a hook subprocess inherits the parent's environment, so
    the hook can read the SAME env vars Bash read. Any of the three matching means
    one process, and the tie goes to "ours": matching too eagerly costs a missed
    denial (fail-open, the direction this whole file leans), while failing to match
    denies a run its own bookkeeping — which is the worse mistake by far.
    """
    ids = {str(session_id)} if session_id else set()
    env_sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if env_sid:
        ids.add(str(env_sid))
    return ids


def _own_pid(info):
    """True when the lock's pid IS this Claude Code process.

    The strongest of the three, and the one that survives any session-id shape:
    `$CLAUDE_PID` is the same number in Bash and in a hook, and it is already in
    the lock because liveness needs it."""
    try:
        env_pid = os.environ.get("CLAUDE_PID")
        return bool(env_pid) and int(env_pid) == int(info.get("pid"))
    except (TypeError, ValueError):
        return False


def manifest_lock_conflict(root, cfg, manifest_rel, rel, session_id):
    """Is another session's lock in the way of this manifest write?

    Returns None when the write is clear, else
    {"lock", "holder", "live", "basis", "note"}.

    This is the enforcement half of the concurrency lock. audit-lock.py made the
    lock correct — it can now tell a live holder from an abandoned one — but a
    correct lock that nothing consults is still advice. The orchestrator takes the
    lock in prose, so a session that ignores an exit 3 was stopped by nothing, and
    the loser's writes landed on top of the winner's with no error anywhere. This
    is the check that makes the exit code binding, at the only moment that
    matters: the write itself.

    FAIL OPEN at every uncertainty, in keeping with the rest of this file:
      * no lock file          -> None. Taking a lock is not enforced, only honoured.
      * lock has no sessionId -> None. Written by hand or by an older orchestrator;
                                 unattributable, and an unattributable lock must
                                 never be able to deny.
      * the lock is ours      -> None.
      * no git / unreadable / audit-lock.py missing -> None.

    A conflict with a NOT-live holder is returned too, with live=False. That is not
    a denial case — nobody is writing against you, so blocking would only add
    friction after a crash — but it is worth saying out loud, because the lock is
    still there and the takeover was never performed.
    """
    try:
        name = governing_lock(manifest_rel, rel)
        if not name:
            return None
        lock = _load_lock_lib()
        if lock is None:
            return None
        ld = lock.lock_dir(str(git_root_dir(root, cfg)))
        if not ld:
            return None
        path = os.path.join(ld, name + ".lock")
        if not os.path.exists(path):
            return None
        info = lock.read_lock(path)
        holder = info.get("sessionId")
        if not holder or not session_id:
            return None
        if holder in _own_identities(session_id) or _own_pid(info):
            return None
        live, basis = lock.judge(info, path)
        return {"lock": name, "holder": holder, "live": bool(live),
                "basis": basis, "note": info.get("note") or name}
    except Exception:
        return None


def in_progress_task_map(root, manifest_rel):
    """Rel-file -> [{"taskId", "testsMode"}] for tasks whose status == 'in_progress',
    including fileIndex siblings keyed by the same task ids. Empty dict on any error.

    Reads via the dual-format loader so the guard hooks see in-progress coverage on
    both the single-file and the sharded manifest layout."""
    out = {}
    manifest = _load_manifest_assembled(Path(root) / manifest_rel)
    if not isinstance(manifest, dict):
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


def manifest_state(root, manifest_rel):
    """How much the plan gate actually knows: {"exists": bool, "phaseRunning": bool}.

    The gate's verdict is graded on this, so the two questions have to be answered
    separately. "No manifest" and "a manifest with nothing running" look identical to
    `in_progress_files` — both yield an empty set — yet they mean very different
    things: the first is a repo that never opted in, the second is a repo mid-plan.

    `phaseRunning` reads the ASSEMBLED manifest, which is load-bearing. Under the
    sharded layout the index carries `{id, title, shard}` stubs with no `status` at
    all (`_manifest_io._STUB_KEYS`), so a raw index read reports every phase as
    None and a live phase would be missed.

    A task `in_progress` under a phase that is not counts too. The runtime writes
    `phase.status` on entry, but a manifest hand-edited to start one task is still a
    repo executing its plan, and refusing to notice would deny the gate exactly when
    it is most warranted.

    Never raises. On any error it reports the LEAST aggressive state, so a crash in
    here can only relax the gate, never invent a denial."""
    state = {"exists": False, "phaseRunning": False}
    try:
        path = Path(root) / manifest_rel
        if not path.exists():
            return state
        state["exists"] = True
        manifest = _load_manifest_assembled(path)
        if not isinstance(manifest, dict):
            return state
        for phase in manifest.get("phases", []) or []:
            if not isinstance(phase, dict):
                continue
            if phase.get("status") == "in_progress":
                state["phaseRunning"] = True
                return state
            for task in phase.get("tasks", []) or []:
                if isinstance(task, dict) and task.get("status") == "in_progress":
                    state["phaseRunning"] = True
                    return state
    except Exception:
        pass
    return state


# --- plan gate ----------------------------------------------------------------
def plan_gate_mode(cfg, state):
    """Resolve evidence into "observe" | "warn" | "deny".

    The product is plan-first development, mechanically enforced. In a repo with no
    manifest there is no plan, so there is nothing to enforce — what a deny does
    there is rate-limit edits, which is a different and worse product sharing a code
    path. It is also the strongest claim this plugin makes on the weakest evidence it
    has, which is the one thing every other surface here refuses to do: the routing
    advisory stays silent until it has three comparable tasks, and the cost report
    prints the thresholds behind every number.

    So the gate is graded the same way:

        no manifest                  -> observe   (record, never block)
        manifest, nothing running    -> warn      (advisory)
        manifest + a phase running   -> deny      (full enforcement)

    `enforce: true` restores always-on deny for anyone who wants it — as a decision
    someone made, rather than a default that surprises a stranger."""
    try:
        if enforce_always(cfg):
            return "deny"
        if not (state or {}).get("exists"):
            return "observe"
        return "deny" if (state or {}).get("phaseRunning") else "warn"
    except Exception:
        return "observe"


def enforce_always(cfg):
    """`enforce: true` -> the plan gate denies regardless of evidence."""
    try:
        val = (cfg or {}).get("enforce")
        if isinstance(val, bool):
            return val
    except Exception:
        pass
    return bool(DEFAULTS.get("enforce", False))


# --- selftest -----------------------------------------------------------------
def _selftest() -> int:
    import platform
    import subprocess
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    tmp = Path(tempfile.mkdtemp(prefix="config-selftest-"))

    # (a) absent config → pure defaults, no error marker
    cfg = load(tmp)
    check("a1 absent config -> defaults, no _configError",
          cfg.get("trivialLineThreshold") == 80 and "_configError" not in cfg,
          repr(cfg.get("_configError")))

    # (b) valid override merges one level deep, keeps un-overridden siblings
    cdir = tmp / ".claude"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "audit.config.json").write_text(
        json.dumps({"trivialLineThreshold": 40,
                    "guardEdits": {"tokenVars": ["jwt"]}}),
        encoding="utf-8")
    cfg = load(tmp)
    check("b1 override merges",
          cfg["trivialLineThreshold"] == 40
          and cfg["guardEdits"]["tokenVars"] == ["jwt"]
          and cfg["guardEdits"]["customRules"] == []
          and "_configError" not in cfg)

    # (b2) the usage block merges per-key, and a partial `pricing` override keeps
    # the shipped rows for every model it doesn't mention
    (cdir / "audit.config.json").write_text(
        json.dumps({"usage": {"showCost": False,
                              "pricing": {"claude-opus-5": {"in": 9.0, "out": 9.0}}}}),
        encoding="utf-8")
    cfg = load(tmp)
    u = usage_cfg(cfg)
    check("b2 usage merges without dropping siblings",
          u["showCost"] is False and u["enabled"] is True
          and u["pricing"]["claude-opus-5"]["in"] == 9.0
          and u["pricing"]["claude-haiku-4-5"]["in"] == 1.0)
    check("b3 ledger_dir is repo-relative and outside stateDir",
          str(ledger_dir(tmp, cfg)).endswith(".claude/usage".replace("/", os.sep)))
    check("b4 usage_enabled defaults true", usage_enabled({}) is True)
    check("b5 usage_enabled honours an explicit false",
          usage_enabled({"usage": {"enabled": False}}) is False)

    # (c) malformed JSON → defaults + _configError (NOT silent)
    (cdir / "audit.config.json").write_text("{not json", encoding="utf-8")
    cfg = load(tmp)
    check("c1 malformed -> defaults + _configError",
          cfg["trivialLineThreshold"] == 80 and bool(cfg.get("_configError")))

    # (d) non-object root → defaults + _configError
    (cdir / "audit.config.json").write_text('["array"]', encoding="utf-8")
    cfg = load(tmp)
    check("d1 non-object root -> _configError", bool(cfg.get("_configError")))

    # (e) no aliasing: mutating a loaded cfg never corrupts DEFAULTS
    (cdir / "audit.config.json").unlink()
    cfg = load(tmp)
    cfg["exemptGlobs"].append("MUTATED")
    cfg["guardEdits"]["tokenVars"].append("MUTATED")
    cfg["tddReminder"]["sourceGlobs"].append("MUTATED")
    cfg["usage"]["pricing"]["_default"]["in"] = 999.0
    check("e0 usage_cfg() does not alias DEFAULTS",
          DEFAULTS["usage"]["pricing"]["_default"]["in"] == 5.0
          and usage_cfg({})["pricing"]["_default"]["in"] == 5.0)
    check("e1 loaded cfg does not alias DEFAULTS",
          "MUTATED" not in DEFAULTS["exemptGlobs"]
          and "MUTATED" not in DEFAULTS["guardEdits"]["tokenVars"]
          and "MUTATED" not in DEFAULTS["tddReminder"]["sourceGlobs"])
    tr = tdd_reminder({})
    tr["testGlobs"].append("MUTATED")
    check("e2 tdd_reminder() does not alias DEFAULTS",
          "MUTATED" not in DEFAULTS["tddReminder"]["testGlobs"])

    # (f) manifest_state + plan_gate_mode — the evidence the plan gate grades on.
    import shutil
    import tempfile
    tmp_f = Path(tempfile.mkdtemp(prefix="config-selftest-state-"))
    try:
        rel = "docs/audit/audit-plan.json"

        def write_manifest(obj, sharded=False):
            d = tmp_f / "docs" / "audit"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            if not sharded:
                (d / "audit-plan.json").write_text(json.dumps(obj), encoding="utf-8")
                return
            # index carries stubs with NO status; the shard bodies hold the truth
            idx = {"meta": {"version": 3}, "phases": []}
            (d / "phases").mkdir(exist_ok=True)
            for ph in obj["phases"]:
                idx["phases"].append({"id": ph["id"], "title": ph.get("title", ""),
                                      "shard": "phases/%s.json" % ph["id"]})
                (d / "phases" / ("%s.json" % ph["id"])).write_text(
                    json.dumps(ph), encoding="utf-8")
            (d / "audit-plan.json").write_text(json.dumps(idx), encoding="utf-8")

        st = manifest_state(tmp_f, rel)
        check("f1 no manifest -> exists False, phaseRunning False",
              st == {"exists": False, "phaseRunning": False}, repr(st))
        check("f2 no manifest -> observe", plan_gate_mode({}, st) == "observe")

        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "done", "tasks": [
                {"id": "P1.1", "title": "t", "status": "done"}]}]})
        st = manifest_state(tmp_f, rel)
        check("f3 manifest with nothing running -> exists, not running",
              st == {"exists": True, "phaseRunning": False}, repr(st))
        check("f4 manifest, nothing running -> warn", plan_gate_mode({}, st) == "warn")

        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "pending"}]}]})
        st = manifest_state(tmp_f, rel)
        check("f5 in_progress phase -> phaseRunning", st["phaseRunning"] is True)
        check("f6 manifest + running phase -> deny", plan_gate_mode({}, st) == "deny")

        # A task running under a phase that is not still counts as executing a plan.
        write_manifest({"meta": {"version": 2}, "phases": [
            {"id": "P1", "title": "p", "status": "pending", "tasks": [
                {"id": "P1.1", "title": "t", "status": "in_progress"}]}]})
        check("f7 in_progress TASK under a pending phase counts as running",
              manifest_state(tmp_f, rel)["phaseRunning"] is True)

        # The sharded trap: the index stub has no status, so a raw read sees None.
        write_manifest({"phases": [
            {"id": "P1", "title": "p", "status": "in_progress", "tasks": [
                {"id": "P1.1", "title": "t", "status": "in_progress"}]}]}, sharded=True)
        idx_raw = json.loads((tmp_f / "docs" / "audit" / "audit-plan.json")
                             .read_text(encoding="utf-8"))
        check("f8 the sharded index really does hide status (guards the next case)",
              idx_raw["phases"][0].get("status") is None)
        check("f9 sharded layout: a running phase is still detected "
              "(assembled read, not the index)",
              manifest_state(tmp_f, rel)["phaseRunning"] is True)

        # enforce overrides every tier, including the one with no evidence at all.
        shutil.rmtree(tmp_f / "docs")
        st = manifest_state(tmp_f, rel)
        check("f10 enforce:true denies even with no manifest",
              plan_gate_mode({"enforce": True}, st) == "deny")
        check("f11 enforce:false is the graded default",
              plan_gate_mode({"enforce": False}, st) == "observe")
        check("f12 a non-bool enforce is ignored rather than trusted",
              plan_gate_mode({"enforce": "yes"}, st) == "observe")
        check("f13 enforce defaults to false", DEFAULTS["enforce"] is False)

        # --- the test-file exemption knows more than one language ------------
        # Found by running the pipeline end to end in a sandbox Python project:
        # the exemption exists so red-first TDD stays frictionless, and it only
        # recognised the JavaScript spelling — so the first act of a red-first
        # fix, writing the failing test, was DENIED for Python and Go.
        _eg = DEFAULTS["exemptGlobs"]
        for _rel, _why in (("tests/test_cart.py", "python, unittest/pytest default"),
                           ("tests/cart_test.py", "python suffix form"),
                           ("pkg/cart_test.go", "go - required by the toolchain"),
                           ("spec/cart_spec.rb", "ruby rspec"),
                           ("test/cart_test.exs", "elixir"),
                           ("src/cart.test.js", "js"),
                           ("src/cart.spec.ts", "ts")):
            check("g1 %s is exempt (%s)" % (_rel, _why), matches_exempt(_rel, _eg))
        # The exemption is for TEST FILES, not for anything with "test" in the name.
        # A wider glob here would quietly hand every file a bypass.
        for _rel in ("src/cart.py", "src/testimonials.py", "src/contest.py",
                     "src/protest_handler.go", "src/latest.py"):
            check("g2 %s is NOT exempt - 'test' inside a word is not a test file"
                  % _rel, not matches_exempt(_rel, _eg))

        # Never raises, and degrades to the least aggressive verdict.
        check("f14 manifest_state on garbage input still returns the safe shape",
              manifest_state(None, None) == {"exists": False, "phaseRunning": False})
        check("f15 plan_gate_mode on garbage input degrades to observe",
              plan_gate_mode(None, None) == "observe")
    finally:
        shutil.rmtree(tmp_f, ignore_errors=True)

    # (j) the journal — where it lives, and what counts as being inside it.
    # Resolved by delegating to scripts/audit-journal.py rather than re-deriving:
    # the module that owns the format owns its location, and the guards below refuse
    # hand edits to whatever it answers.
    tmp_j = Path(tempfile.mkdtemp(prefix="config-journal-"))
    try:
        cfg_j = _deep_merge(DEFAULTS, {})
        check("j1 journal.enabled defaults true", journal_enabled({}) is True
              and DEFAULTS["journal"]["enabled"] is True)
        check("j2 an explicit false is honoured",
              journal_enabled({"journal": {"enabled": False}}) is False)
        check("j3 a non-bool is ignored rather than trusted (the `enforce` rule)",
              journal_enabled({"journal": {"enabled": "no"}}) is True)
        jd = journal_dir(tmp_j, cfg_j)
        check("j4 the journal sits beside the manifest by default",
              jd is not None and str(jd) == str(
                  tmp_j / "docs" / "audit" / "journal"), repr(jd))
        check("j5 journal.dir moves it",
              str(journal_dir(tmp_j, _deep_merge(
                  DEFAULTS, {"journal": {"dir": "trail"}}))) == str(tmp_j / "trail"))
        check("j6 a moved manifest takes the journal with it",
              str(journal_dir(tmp_j, _deep_merge(
                  DEFAULTS, {"manifestPath": "plan/audit.json"})))
              == str(tmp_j / "plan" / "journal"))
        check("j7 a path inside the journal is recognised, absolute or relative",
              in_journal(tmp_j, cfg_j, "docs/audit/journal/2026-08.a.jsonl")
              and in_journal(tmp_j, cfg_j,
                             str(tmp_j / "docs" / "audit" / "journal" / "x.jsonl")))
        check("j8 the manifest beside it is NOT inside it",
              not in_journal(tmp_j, cfg_j, "docs/audit/audit-plan.json")
              and not in_journal(tmp_j, cfg_j, "src/app.py"))
        check("j9 a sibling directory whose name merely starts the same is outside",
              not in_journal(tmp_j, cfg_j, "docs/audit/journal-notes/x.md"))
        # The guards ask THIS question, not `journal_dir`, so it has to read the
        # project's own setting rather than the default: a repo that moved its
        # journal would otherwise have the old location protected and the real one
        # wide open.
        _moved = _deep_merge(DEFAULTS, {"journal": {"dir": "trail"}})
        check("j10 a moved journal is protected where it actually is",
              in_journal(tmp_j, _moved, "trail/2026-08.a.jsonl")
              and not in_journal(tmp_j, _moved,
                                 "docs/audit/journal/2026-08.a.jsonl"))
        check("j11 garbage in, False out", not in_journal(tmp_j, cfg_j, "")
              and not in_journal(None, None, None))
        # The delegation itself: this must be the journal module's answer, not a
        # second copy of the rule that can drift from it.
        _jmod = _load_journal_lib()
        check("j12 the answer comes from audit-journal.py itself",
              _jmod is not None
              and str(jd) == _jmod.journal_dir(str(tmp_j), cfg_j))
    finally:
        shutil.rmtree(tmp_j, ignore_errors=True)

    # (p) the capability policy — the block itself lives in scripts/_policy.py and
    # is exercised there; what this file owns is the delegation and the one piece of
    # evidence a hook cannot get from the config alone: which areas are active.
    tmp_p = Path(tempfile.mkdtemp(prefix="config-policy-"))
    try:
        _pol = policy_mod()
        check("p1 the policy engine ships and is reachable from the hooks",
              _pol is not None)
        check("p2 DEFAULTS carries the engine's own block rather than a copy of it "
              "- one statement of what ships inert",
              _pol is not None and DEFAULTS.get("policy") == _pol.DEFAULTS)
        check("p3 the shipped default is inert, so the guard hook returns before "
              "it reads anything",
              _pol is not None and not _pol.is_active(policy_cfg({})))
        check("p4 a project's block merges through the engine, not by hand",
              policy_cfg({"policy": {"skills": {"default": "deny"}}})["skills"]
              == {"default": "deny", "allow": [], "deny": [], "areas": {}})
        _p = load(tmp_p)
        _p["policy"]["skills"]["deny"].append("MUTATED")
        check("p5 a loaded policy does not alias DEFAULTS",
              "MUTATED" not in DEFAULTS["policy"]["skills"]["deny"]
              and "MUTATED" not in (_pol.DEFAULTS["skills"]["deny"] if _pol else []))

        rel = "docs/audit/audit-plan.json"

        def write_plan(phases, sharded=False):
            d = tmp_p / "docs" / "audit"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
            if not sharded:
                (d / "audit-plan.json").write_text(
                    json.dumps({"meta": {"version": 2}, "phases": phases}),
                    encoding="utf-8")
                return
            idx = {"meta": {"version": 3}, "phases": []}
            (d / "phases").mkdir(exist_ok=True)
            for ph in phases:
                idx["phases"].append({"id": ph["id"], "title": ph.get("title", ""),
                                      "shard": "phases/%s.json" % ph["id"]})
                (d / "phases" / ("%s.json" % ph["id"])).write_text(
                    json.dumps(ph), encoding="utf-8")
            (d / "audit-plan.json").write_text(json.dumps(idx), encoding="utf-8")

        check("p6 no manifest -> no active areas, and no raise",
              active_area_tags(tmp_p, rel) == []
              and active_area_tags(None, None) == [])
        write_plan([{"id": "P1", "title": "a", "status": "done", "area": "api",
                     "tasks": [{"id": "P1.1", "status": "done"}]},
                    {"id": "P2", "title": "b", "status": "in_progress",
                     "area": ["web", "web"],
                     "tasks": [{"id": "P2.1", "status": "pending"}]}])
        check("p7 only the phases with work in progress count, deduped by the same "
              "normaliser the rest of the plugin uses",
              active_area_tags(tmp_p, rel) == ["web"],
              repr(active_area_tags(tmp_p, rel)))
        write_plan([{"id": "P1", "title": "a", "status": "pending", "area": "api",
                     "tasks": [{"id": "P1.1", "status": "in_progress"}]}])
        check("p8 a running TASK under a pending phase makes its area active - the "
              "same evidence the plan gate grades on",
              active_area_tags(tmp_p, rel) == ["api"])
        write_plan([{"id": "P1", "title": "a", "status": "in_progress",
                     "area": "api", "tasks": [{"id": "P1.1", "status": "pending"}]}],
                   sharded=True)
        check("p9 sharded layout: the areas are read from the ASSEMBLED manifest, "
              "or the index stubs' missing status would make every area rule "
              "silently inert", active_area_tags(tmp_p, rel) == ["api"])
        write_plan([{"id": "P1", "title": "a", "status": "in_progress",
                     "tasks": [{"id": "P1.1", "status": "pending"}]}])
        check("p10 an untagged running phase activates nothing",
              active_area_tags(tmp_p, rel) == [])
    finally:
        shutil.rmtree(tmp_p, ignore_errors=True)

    # (g) governing_lock — which of the two tiers covers a given write. This is the
    # map the enforcement rests on, so a path that should be governed and isn't
    # would silently un-enforce, and one that shouldn't be and is would deny work
    # that has nothing to do with the manifest.
    M = "audit/plan.json"
    check("g1 the index is the index tier", governing_lock(M, M) == "index")
    check("g2 a shard is its own phase's tier",
          governing_lock(M, "audit/phases/P1.json") == "phase-P1")
    check("g3 bugfix shards too",
          governing_lock(M, "audit/phases/BF12.json") == "phase-BF12")
    check("g4 a non-JSON file in phases/ is not a shard",
          governing_lock(M, "audit/phases/notes.txt") is None)
    check("g5 a nested path under phases/ is not a shard (no id with a slash)",
          governing_lock(M, "audit/phases/sub/P1.json") is None)
    check("g6 a sibling of the manifest is not governed",
          governing_lock(M, "audit/other.json") is None)
    check("g7 ordinary source is not governed",
          governing_lock(M, "src/app.py") is None)
    check("g8 the lockfile itself is not a governed WRITE",
          governing_lock(M, M + ".lock") is None)
    # A manifest at the repo root makes dirname('') — `phases/` must still work and
    # must not swallow the repo.
    check("g9 root manifest: its shards still resolve",
          governing_lock("plan.json", "phases/P1.json") == "phase-P1")
    check("g10 root manifest: nothing else does",
          governing_lock("plan.json", "src/app.py") is None
          and governing_lock("plan.json", "anything.json") is None)
    check("g11 garbage in, None out", governing_lock(None, None) is None
          and governing_lock("", "") is None)

    # (h) manifest_lock_conflict fail-open. Every one of these must return None:
    # an unattributable lock that could deny would brick legitimate work in a
    # plugin whose whole posture is to fail open.
    tmp_h = Path(tempfile.mkdtemp(prefix="config-lock-"))
    try:
        cfg_h = dict(DEFAULTS)
        check("h1 a path with no governing lock is never a conflict",
              manifest_lock_conflict(tmp_h, cfg_h, M, "src/app.py", "s") is None)
        check("h2 not a git repo -> no verdict",
              manifest_lock_conflict(tmp_h, cfg_h, M, M, "s") is None)
        if not shutil.which("git"):
            print("SKIP h3-h7 (git is not on PATH)")
        else:
            subprocess.run(["git", "init", "-q", str(tmp_h)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            check("h3 a git repo with no lock -> no verdict",
                  manifest_lock_conflict(tmp_h, cfg_h, M, M, "s") is None)
            lockmod = _load_lock_lib()
            ld_h = Path(lockmod.lock_dir(str(tmp_h)))
            ld_h.mkdir(parents=True, exist_ok=True)

            def write_lock(**fields):
                with open(ld_h / "index.lock", "w", encoding="utf-8") as fh:
                    json.dump(fields, fh)

            write_lock(hostname=platform.node(), pid=os.getpid())
            check("h4 a lock with no sessionId -> no verdict",
                  manifest_lock_conflict(tmp_h, cfg_h, M, M, "s") is None)
            write_lock(hostname=platform.node(), pid=os.getpid(), sessionId="s")
            check("h5 our own lock -> no verdict",
                  manifest_lock_conflict(tmp_h, cfg_h, M, M, "s") is None)
            check("h6 a caller with no session id of its own -> no verdict",
                  manifest_lock_conflict(tmp_h, cfg_h, M, M, "") is None)
            got = manifest_lock_conflict(tmp_h, cfg_h, M, M, "other")
            check("h7 another live session -> a conflict, with its basis",
                  isinstance(got, dict) and got["live"] is True
                  and got["holder"] == "s" and bool(got["basis"]))

            # h8-h10: the identity split that nearly shipped a gate denying the
            # orchestrator its own writes. The lock is taken from Bash under
            # $CLAUDE_CODE_SESSION_ID; the hook is handed a DIFFERENT session_id in
            # its payload. Measured in a live session, they do not match. Every
            # identity that means "the same Claude Code process" must count as ours.
            _sid, _pid_env = (os.environ.get("CLAUDE_CODE_SESSION_ID"),
                              os.environ.get("CLAUDE_PID"))
            try:
                os.environ["CLAUDE_CODE_SESSION_ID"] = "from-bash"
                os.environ.pop("CLAUDE_PID", None)
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="from-bash")
                check("h8 a lock taken under the env session id is ours, even "
                      "though the hook is handed a different one",
                      manifest_lock_conflict(tmp_h, cfg_h, M, M,
                                             "from-hook-payload") is None)
                # And the pid path, which survives any session-id shape at all.
                os.environ["CLAUDE_CODE_SESSION_ID"] = "something-else"
                os.environ["CLAUDE_PID"] = str(os.getpid())
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="from-bash")
                check("h9 or matched by $CLAUDE_PID when neither id lines up",
                      manifest_lock_conflict(tmp_h, cfg_h, M, M, "from-hook") is None)
                # A genuinely different process must still conflict.
                write_lock(hostname=platform.node(), pid=os.getpid(),
                           sessionId="a-real-other-session")
                os.environ["CLAUDE_PID"] = str(os.getpid() + 1)
                got = manifest_lock_conflict(tmp_h, cfg_h, M, M, "from-hook")
                check("h10 but a genuinely different session still conflicts",
                      isinstance(got, dict) and got["holder"] == "a-real-other-session")
            finally:
                for k, v in (("CLAUDE_CODE_SESSION_ID", _sid),
                             ("CLAUDE_PID", _pid_env)):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
    finally:
        shutil.rmtree(tmp_h, ignore_errors=True)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print("This is a library module; run with --selftest to exercise it.")
