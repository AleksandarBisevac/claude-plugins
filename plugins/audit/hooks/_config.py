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
  bashWriteCheck.enabled  bool  — PostToolUse git-status diff check for shell
        writes into source files (guard-bash-writes.py); default true
  tddReminder             obj   — non-blocking TDD nudge (remind-tdd.py):
        enabled (bool), sourceGlobs [str], testGlobs [str], throttleMinutes (int),
        inProgressPolicy ("skip-gate-only" | "skip-all" | "warn-always")
  usage                   obj   — token metering (meter-usage.py, /audit:usage):
        enabled (bool), ledgerDir (str), authorMode ("email"|"name"|"hash"|"none"),
        showCost (bool), backfillOnFirstRun (bool), maxScanBytes (int),
        currency (str), pricingAsOf (str), pricing (obj: model -> USD per MTok)

This module also hosts the path/manifest helpers shared by require-plan.py and
remind-tdd.py (rel_path, matches_exempt, strip_line_suffix, in_progress_*).
"""
import copy
import fnmatch
import json
import os
import sys
from pathlib import Path

CONFIG_REL = ".claude/audit.config.json"

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

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print("This is a library module; run with --selftest to exercise it.")
