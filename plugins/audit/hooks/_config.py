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
  enforce                 bool  — LEGACY: force the plan gate to DENY regardless of
                                  evidence (same as planGate: "deny"; planGate wins
                                  when both are set). Default false, which grades
                                  the gate: observe with no manifest, warn with a
                                  manifest but nothing running, deny once a phase
                                  is in_progress. Only the PLAN gate is graded —
                                  the secret guards deny by default either way,
                                  because reading .env is wrong whether or not a
                                  plan exists.
  planGate                str   — pin the plan gate to one tier by hand:
                                  "observe" | "warn" | "ask" | "deny". Absent (the
                                  default) keeps the graded ladder above. "ask"
                                  surfaces each out-of-plan edit for the human's
                                  approval. Beats enforce; a typo fails open to
                                  the ladder (the validator flags it).
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
        all live in _policy.py — see DEFAULTS below for why they are not
        restated here.

This module also hosts the path/manifest helpers shared by require-plan.py and
remind-tdd.py (rel_path, matches_exempt, strip_line_suffix, in_progress_*).

Hooks never statically `import` anything from scripts/, this module included: they
run on every tool call, launched by a process that may not have scripts/ on its
sys.path, so scripts/-owned features (policy, journal, manifest assembly) are
loaded by path via `_load_scripts_module` and treated as optional, not required.

That sentence is machine-checked — `_deps.py` fails the build on any static
hooks->scripts import, with no allow-list. It had one, for one import: this
module's own manifest read, which the checker's first run found (F11) and which
was the only thing standing between the rule and being true.

This module carries no `--selftest` of its own any more; its 124 cases live in
`plugins/audit/tests/test__config.py`. A test of a hook may import from `scripts/`
even though the hook itself may not — the isolation rule is about what a hook costs
at import time under a launcher, and a test has no launcher above it; see
`plugins/audit/tests/_harness.py`. That is also why this file is the one entry point
in the tree with no `safe_stdio()` call: it would have to come from `scripts/`.
"""
import copy
import fnmatch
import json
import os
import re
import sys
import time
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
    # LEGACY: `planGate: "deny"` says the same thing, and planGate wins when
    # both are set.
    "enforce": False,
    # Pin the plan gate to one tier by hand: "observe" | "warn" | "ask" | "deny".
    # None (the default) keeps the graded ladder plan_gate_mode documents. A
    # typo fails OPEN to the ladder -- never to deny.
    "planGate": None,
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
    # 1-hour TTL, read 0.1x. Keep in sync with usage_ledger.py
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
    # audit-journal.py owns the resolution; journal_dir() below is the one
    # copy of it the hooks read, and its selftest pins the two together.
    # `strictManifestState` ("off" | "ask", default off) is guard-edits' opt-in
    # confirmation prompt on manifest STATE edits (status/completedAt/commit/
    # attempts) -- never "deny": the orchestrator writes through the same tools.
    "journal": {"enabled": True, "dir": None, "strictManifestState": "off"},
    # th (F-P-6): the panel's and the report's LOOK. `theme` is a preset name or
    # a path to a theme file; absent means "search" -- .claude/audit.theme.json
    # in the project, then ~/.claude/audit.theme.json, then the built-in. No
    # hook reads this; it lives here because DEFAULTS is the one place the whole
    # config's shape is stated, and a key the validator knows but this file does
    # not is how the two drifted before.
    "ui": {"theme": None},
}


# --- config load --------------------------------------------------------------
def find_script(filename):
    """Full path of `filename` ANYWHERE under `../scripts`, recursively, or None.

    BY BASENAME, because the folders under `scripts/` are labels and not
    namespaces: `_output.install_path()` puts every one of them on `sys.path` and
    `_loader.load_script()` resolves the same way. A flat
    `join(scripts_dir, filename)` is right only while the tree is flat, and when it
    stops being right it fails SILENTLY — see `_load_scripts_module` below for what
    that costs.

    THE THIRD COPY OF "WHERE IS scripts/", AND IT IS IRREDUCIBLE. `hooks/` may not
    import `scripts/` at all (`_deps` r5/r6, and there is no allow-list any more),
    so this cannot read `_output.SCRIPTS_DIR` and has to walk from its own
    `__file__`. It is held true by READING rather than by merging: a case in
    `tests/test__config.py` loads this file by path and asserts this resolver and
    `_output.script_files()` agree on every basename — the same shape as the
    pricing-table pair in `tests/test__usage_core.py`.

    Deterministic: `os.walk` yields the root before its subdirectories and the
    subdirectory names are sorted, so the flat file wins and a tie below it always
    resolves the same way. `_deps.layer_violations()` forbids the tie existing at
    all.
    """
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def _load_scripts_module(name, filename):
    """Load a sibling module out of ../scripts by path. None when it cannot be
    loaded — every caller reads that as "the feature this module owns is not
    installed" rather than raising into a hook.

    THAT FAIL-OPEN IS WHY `find_script` HAS TO BE RIGHT. A wrong path here does not
    raise: it returns None, and the capability policy, the journal, the ledger and
    the sharded-manifest read all switch themselves off with every gate still
    green. There is no louder symptom to notice later, which is why the resolver
    above is tested directly rather than through the features that depend on it.
    """
    try:
        import importlib.util
        path = find_script(filename)
        if path is None:
            return None
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# The capability policy's defaults are NOT written out here. _policy.py owns
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


# --- usage ledger ---------------------------------------------------------------
_LEDGER_LIB = {"tried": False, "mod": None}


def _ledger_lib():
    """usage_ledger.py, loaded once — the `_load_journal_lib` caching.

    Honest accounting: a hook process resolves an author once per run, so in
    production this cache saves almost nothing. What it buys is parity (the
    ledger module now has the same one-load seam the journal and areas modules
    have) and the selftests, which drive `_author` dozens of times and were
    re-executing a ~1800-line module on every call. None when it cannot be
    loaded — callers read that as "author attribution is off"."""
    if not _LEDGER_LIB["tried"]:
        _LEDGER_LIB["tried"] = True
        _LEDGER_LIB["mod"] = _load_scripts_module("usage_ledger",
                                                  "usage_ledger.py")
    return _LEDGER_LIB["mod"]


# --- journal ------------------------------------------------------------------
_JOURNAL_LIB = {"tried": False, "mod": None}


def _load_journal_lib():
    """audit-journal.py, loaded by path and cached — the same pattern as
    _load_lock_lib, and for the same reason: the journal's own module owns where a
    journal lives and what a row means, and a second copy of that rule in here is
    two implementations that can disagree. None when it cannot be loaded, which
    every caller reads as "there is no journal", because without that module
    nothing can write one."""
    if not _JOURNAL_LIB["tried"]:
        _JOURNAL_LIB["tried"] = True
        # `_journal_io.py`, not `audit-journal.py`: the one function this hook
        # asks for (`journal_dir`) moved down to layer 1 when two modules that
        # are not commands needed the trail. This runs on every tool call, so
        # the argument parser and four subcommand bodies were cost with no
        # caller here — the same move `_load_lock_lib` makes above.
        _JOURNAL_LIB["mod"] = _load_scripts_module("audit_journal_io",
                                                   "_journal_io.py")
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
    """_policy.py, or None when this install has no policy engine."""
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
    """_areas.py, loaded once — the same caching `_load_journal_lib` uses,
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
    """`_areas.areas_of` when _areas.py cannot be loaded. Deliberately the
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


# --- the test-file exemption stops at data formats ----------------------------
# `tsconfig.test.json` matched `**/*.test.*` and was exempted as a "test file"
# (live find, v0.36 A1) — but it is BUILD CONFIGURATION named like a test, and
# the same shape covers tsconfig.spec.json, docker-compose.test.yml and
# test_config.yaml. The carve-out is by FILE FORMAT, not by narrowing the globs
# to an allow-list of code extensions: the width of these globs is deliberate
# (multi-language — *.test.js, test_*.py, cart_test.go, cart_spec.rb,
# cart_test.exs) and a per-language allow-list has already been this exemption's
# opposite bug once, when it recognised only the JavaScript spelling. Tests are
# written in CODE; a file whose extension is a pure data/markup format cannot be
# one, whatever its name says — and the data-format list is small and stable
# where a code-extension list grows with every language.
#
# Applied ONLY to test-suffix-shaped globs (`*.test.*`, `*_spec.*`, `test_*.*`,
# ...): an explicit glob a project writes (`**/tsconfig.*`) still exempts
# exactly what it names, and the directory globs (`**/tests/**`,
# `**/__tests__/**`) still cover data fixtures that live with their tests.
# A JSON fixture named `cart.test.json` OUTSIDE such a directory loses its
# exemption — accepted: the gate fails closed and says so, which beats handing
# build configs a silent bypass.
_TEST_SUFFIX_GLOB = re.compile(
    r"(?:[.*_](?:test|spec)[.*_]|(?:^|/)test_)", re.IGNORECASE)
_NON_CODE_TEST_EXTS = (".json", ".jsonc", ".json5", ".yaml", ".yml", ".toml",
                       ".ini", ".cfg", ".conf", ".xml", ".properties")


def matches_exempt(rel, globs):
    """Generic glob matcher that understands the common `**` forms.

    Handles:  `dir/**` (recursive prefix), `**/*.ext` (basename), and plain fnmatch.

    One carve-out: a test-suffix-shaped glob never claims a file in a pure
    data/markup format (see _TEST_SUFFIX_GLOB / _NON_CODE_TEST_EXTS above) —
    `tsconfig.test.json` is a compiler config, not a test.
    """
    base = rel.split("/")[-1]
    non_code = base.lower().endswith(_NON_CODE_TEST_EXTS)
    for g in globs or ():
        g = str(g)
        if non_code and _TEST_SUFFIX_GLOB.search(g):
            continue
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
    blocking-hook read path never regresses. Returns {} on any error (never raises).

    Loaded by path, like every other scripts/-owned feature a hook reaches for. It
    was the one place that did it by putting scripts/ at the FRONT of `sys.path`
    and running a plain `import` — which is a process-wide edit to import
    resolution, made inside a hook that runs on every tool call, to load one
    module: from then on any import anywhere in the process resolves against
    scripts/ first. Nothing in scripts/ shadows a stdlib name today, and that is a
    property of a directory nobody is maintaining for it. It also made this module
    the only static hooks->scripts edge in the tree, which its own docstring says
    does not exist (F11). Costs 0.136 ms per call, measured, because importlib by
    path does not cache in sys.modules — against a 10-second hook budget and at
    most three calls in a run, that is not worth a second mechanism to avoid (D5's
    reasoning, one module down)."""
    mio = _load_scripts_module("_manifest_io", "_manifest_io.py")
    if mio is not None:
        try:
            return mio.load_manifest_safe(str(path))
        except Exception:
            pass
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_lock_lib():
    """Load _locks.py by path — same pattern as _load_manifest_assembled
    and meter-usage's ledger load. None if it cannot be loaded; every caller treats
    that as "no verdict" and allows.

    `_locks.py`, not `audit-lock.py`: the three functions this hook asks for
    (`lock_dir`, `read_lock`, `judge`) moved down to layer 1 when three scripts
    that are not commands needed them, and this hook wants the module that OWNS
    them rather than the command built on top. It runs on every tool call, so the
    argparse-and-subcommands half of `audit-lock.py` was cost with no caller
    here."""
    return _load_scripts_module("audit_locks", "_locks.py")


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
    """How much the plan gate actually knows:
    {"exists": bool, "phaseRunning": bool, "runningPhase": "<id>"|None}.

    `runningPhase` names the phase behind `phaseRunning` (the phase itself when
    it is in_progress, the OWNER phase when only a task is), so a denial can say
    "phase P3 is in_progress" instead of the anonymous claim that shipped F-F4.

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
    state = {"exists": False, "phaseRunning": False, "runningPhase": None}
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
                state["runningPhase"] = phase.get("id")
                return state
            for task in phase.get("tasks", []) or []:
                if isinstance(task, dict) and task.get("status") == "in_progress":
                    state["phaseRunning"] = True
                    state["runningPhase"] = phase.get("id")
                    return state
    except Exception:
        pass
    return state


# --- plan-first bypass ----------------------------------------------------------
# How long an armed #no-plan bypass stays live before require-plan treats it as
# never armed (deleting it on its next Post pass). A CONSTANT, not a config key,
# on purpose: the surface for one knob is large (schema, validator, panel
# control, help, docs) and nobody has asked for tunability -- if someone does,
# the upgrade path is a `bypassTtlMinutes` key beside `bypassKeyword` in
# DEFAULTS, threaded through those same places. Legacy bypass slots without
# `armedAtEpoch` are honoured WITHOUT a TTL (fail-open; the 7-day state GC
# still sweeps them).
BYPASS_TTL_SECONDS = 30 * 60

# --- plan gate ----------------------------------------------------------------
# The tiers `planGate` may pin, in escalation order. validate-config.py mirrors
# this as PLAN_GATE_MODES (its FINDING enum, which the panel's select reads);
# the two are pinned together by that validator's selftest.
PLAN_GATE_TIERS = ("observe", "warn", "ask", "deny")


def plan_gate_knob(cfg):
    """The `planGate` override: one of PLAN_GATE_TIERS, or None when unset.

    Fail-open on a typo, and openly: a value outside the enum reads as UNSET
    (the graded ladder), never as deny -- the validator makes the typo a
    FINDING, so it is caught where it can be read rather than silently obeyed
    as something else."""
    try:
        val = (cfg or {}).get("planGate")
        if isinstance(val, str) and val in PLAN_GATE_TIERS:
            return val
    except Exception:
        pass
    return None


def plan_gate_mode(cfg, state):
    """Resolve evidence into "observe" | "warn" | "ask" | "deny".

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

    `planGate` (v0.34) pins one tier by hand — "observe" | "warn" | "ask" |
    "deny" — and wins over everything below, including `enforce`: it is the
    newer, more explicit spelling, and when the two disagree the one that can
    say all four things beats the one that can only say deny. "ask" surfaces
    each out-of-plan edit for the human's approval; "observe" is the only
    setting that LOWERS the gate below its evidence, which the doctor warns
    about when a phase is running.

    `enforce: true` restores always-on deny for anyone who wants it — as a decision
    someone made, rather than a default that surprises a stranger. It is the
    legacy spelling of `planGate: "deny"`."""
    try:
        knob = plan_gate_knob(cfg)
        if knob:
            return knob
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


# --- utc stamps ---------------------------------------------------------------
def utc_stamp():
    """The wall-clock stamp every record a hook writes carries — one instant in
    UTC, ISO-8601 to the second, e.g. `2026-08-17T09:41:03Z`.

    The `Z` and `time.gmtime()` are a pair, and holding the pair together is the
    entire reason this function exists rather than the expression. `Z` is not
    decoration: it is a claim that the digits in front of it are UTC, and
    `gmtime()` is the only thing that makes the claim true. Build the same format
    from `time.localtime()` and nothing anywhere objects — the `Z` is a literal in
    the format string so it is still emitted, the result is still 20 characters,
    and `time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")` still parses it without a
    murmur. What breaks is downstream and silent: a lock taken at 14:00 CEST is
    recorded as `14:00Z`, so every reader that compares it to real UTC — the
    stale-lock age in audit-lock.py, the doctor's clock-drift check, the
    panel's Overview — sees an event two hours in the future and computes a
    negative age. On a machine that happens to run in UTC the two versions are
    indistinguishable, which is why the mistake survives review and a CI run.

    This existed as five separately-typed copies of the expression across
    hooks/, with no constant and no home; the sixth would eventually have been
    typed with `localtime`.

    Never raises, and adds no import: `time` is already at module scope. Every
    hook imports this module on every tool call and they are blocking gates, so
    a helper that pulled in `datetime` here would be paid for on calls that never
    stamp anything."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- atomic local writes ------------------------------------------------------
def atomic_write_text(path, text):
    """Replace `path`'s whole contents with `text`, atomically: a UNIQUE temp
    file created in the SAME directory (mkstemp), written, then os.replace'd
    into place. The temp file is never left behind, and failures RAISE — the
    caller owns the fail-open decision, because a writer that silently swallows
    is how a hook reports success over a file it never wrote.

    Both halves are load-bearing and both have been wrong in this tree:

    - **Unique name.** Hooks run concurrently — one Edit tool call fans out to
      seven hook processes — so a fixed `path + ".tmp"` is two processes
      opening, truncating and replacing the SAME file: the loser's write is
      lost, and a reader sees a torn one. Measured at 12-way concurrency
      against this module's own gate-events feed: 1773 corrupt reads out of
      4800 with the fixed name, 0 with mkstemp. Note that "the file was
      written" cannot see this — both shapes write it when nothing else is
      running; the temp NAME is the thing that differs.
    - **Same directory.** os.replace is only atomic within one filesystem, so
      the temp cannot go to the system temp dir.

    `tempfile` is imported here rather than at module scope on purpose: it costs
    ~8ms to import, EVERY hook imports this module on EVERY tool call, and this
    function is reached only on the rare rewrite. Keeping the import local is
    what lets guard-capabilities.py share this code without paying that cost on
    the calls that never write anything.

    The plugin's other atomic writer is scripts/_manifest_io.atomic_write_json,
    which hooks/ may not import at all (the layer rule) — hence a second, smaller
    statement of the same pattern here rather than one shared home."""
    import tempfile
    target = str(path)
    d = os.path.dirname(target) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --- gate events feed -----------------------------------------------------------
LOCAL_IGNORE_MARKER = "# audit plugin: local state - do not commit\n*\n"


def ensure_local_dir(path):
    """mkdir -p a plugin-managed LOCAL directory and make it self-ignoring:
    a `.gitignore` holding `*` is dropped inside on creation (and re-created
    if missing). state/, logs/ and the usage ledger hold a live panel token,
    person identities and session scratch - none of it belongs in git, and
    the help-text advice to "gitignore them" demonstrably went unread on a
    real repo while `git add .claude` sat one keystroke away.

    An existing marker is never overwritten (the file is the user's once it
    exists), and a tracked file is immune to ignore rules anyway, so a team
    that deliberately `git add -f`s the ledger loses nothing. NEVER call this
    for docs/audit - the journal is the opposite kind of artifact: its git
    history is one of the trail's three anchors and it must stay tracked.
    Never raises: hook context. Returns the Path either way."""
    d = Path(path)
    try:
        d.mkdir(parents=True, exist_ok=True)
        marker = d / ".gitignore"
        if not marker.exists():
            marker.write_text(LOCAL_IGNORE_MARKER, encoding="utf-8")
    except Exception:
        pass
    return d


GATE_EVENTS_FILE = "plan-gate-events.jsonl"
_GATE_EVENTS_MAX_BYTES = 512 * 1024
_GATE_EVENTS_KEEP_LINES = 400
_GATE_EVENT_KEYS = ("event", "file", "mode", "reason", "sessionId")


def append_gate_event(logs_dir, event):
    """One compact JSON line into `<logsDir>/plan-gate-events.jsonl` (v0.34 B3).

    The gate's verdicts used to leave NO trace at all — only the bypass
    arm/consume had a log — so "what has the gate been doing" had no answer a
    human could read. This is that answer's raw feed: telemetry, not evidence.
    It lives in logsDir on purpose (stateDir is per-session GC territory; the
    journal is the tamper-evidence surface, and telemetry does not belong in a
    hash chain). The panel's Overview reads the tail of it.

    The row is {ts} + the allow-listed keys of `event`, stringified and
    bounded; unknown keys are dropped, None values omitted. Never raises —
    this runs inside blocking hooks, and a feed that cannot be written is
    silence, not an error.

    Self-trim: past ~512KB the newest ~400 lines are rewritten through
    `atomic_write_text` — a unique temp file in the feed's own directory, then
    os.replace — fail-open. This paragraph used to claim atomicity while the
    code below used a fixed `path + ".tmp"`, which under concurrent hooks is
    exactly the thing it promised not to be; see the helper for the numbers."""
    try:
        logs = ensure_local_dir(logs_dir)
        path = logs / GATE_EVENTS_FILE
        row = {"ts": utc_stamp()}
        for key in _GATE_EVENT_KEYS:
            val = (event or {}).get(key) if isinstance(event, dict) else None
            if val is not None:
                row[key] = str(val)[:200]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=True) + "\n")
        try:
            if path.stat().st_size > _GATE_EVENTS_MAX_BYTES:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
                keep = lines[-_GATE_EVENTS_KEEP_LINES:]
                atomic_write_text(path, "\n".join(keep) + "\n")
        except Exception:
            pass
    except Exception:
        pass
    return None


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        # Answered rather than falling through to the library notice below: CI
        # runs `--selftest` over every file in this directory. It deliberately
        # does NOT print the `N/M cases passed` contract - that string is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_config.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__config.py - run that file instead.")
        sys.exit(0)
    print("This is a library module; run with --selftest to exercise it.")
