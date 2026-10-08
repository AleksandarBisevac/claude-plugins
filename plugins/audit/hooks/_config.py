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
                                  is in_progress. What is graded is the
                                  PLAN-COVERAGE class, wherever it is enforced —
                                  require-plan's Edit/Write path, BOTH Bash-write
                                  branches of guard-secrets-read (the shell forms
                                  and the interpreter ones) and the PostToolUse
                                  report in guard-bash-writes all resolve their
                                  tier through plan_gate_mode below, and the
                                  first two read one free-file slot
                                  (trivial_slot), so one file gets one verdict
                                  whichever way it is written — except a shell
                                  write whose size its command does not state,
                                  which takes the slot unmeasured and is sized
                                  by guard-bash-writes once it lands; see that
                                  function's own docstring.
                                  The secret guards are never graded and
                                  deny at every tier, because reading .env is
                                  wrong whether or not a plan exists.
  planGate                str   — pin the plan gate to one tier by hand:
                                  "observe" | "warn" | "ask" | "deny". Absent (the
                                  default) keeps the graded ladder above. "ask"
                                  surfaces each out-of-plan edit for the human's
                                  approval. Beats enforce; a typo fails open to
                                  the ladder (the validator flags it). Reaches
                                  every plan-coverage surface, not just the Edit
                                  path — see `enforce` above for the list.
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
        writes into source files (guard-bash-writes.py); default true. TWO KEYS
        DECIDE WHETHER ITS PLAN-COVERAGE CLASS SPEAKS, and this is the master off
        switch rather than the only one: with it true, that class still resolves a
        tier through plan_gate_mode, so `planGate: "observe"` — or simply a repo
        with no manifest — silences it. The lock and journal classes bind
        their claim to evidence of their own and report at every tier.
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
  priority                obj   — phase prioritisation (_priority.py, set-priority.py):
        maxTier (int) — the highest tier the panel offers. Advisory; nothing is
        clamped to it, and no hook reads it.
  policy                  obj   — which skills, subagents and MCP tools may be used
        here (guard-capabilities.py): enabled (bool), onViolation
        ("deny"|"ask"|"warn"), and one block per kind (skills/agents/mcp) of
        {default: "allow"|"deny", allow: [pattern], deny: [pattern],
        areas: {tag: {allow, deny}}}. The shape, the defaults and the resolution
        all live in _policy.py — see DEFAULTS below for why they are not
        restated here.
  executor.runsGate       str   — how much of a task's gate the EXECUTOR runs
        ITSELF before handing back to the orchestrator, which always runs the
        gate again with `--record` — only that recorded run is evidence, so
        the executor's own pass is a convenience it can afford to skip or
        narrow. One of RUNS_GATE_MODES: "never" (skip it — the executor
        develops against nothing of its own and trusts the recorded run
        entirely), "own-tests" (run only the test(s) `task.tests.add` names —
        the default), or "full" (every command in `task.tests.gate`, same as
        if this key did not exist). No hook reads this; `executor_gate_policy`
        below is read by the orchestrator at spawn time, the same moment it
        resolves which skills to hand the subagent. An unrecognised value is
        REFUSED (the function returns None) rather than folded into "own-tests"
        — a typo here would otherwise make the cheap default look like a
        deliberate choice.
  executor.maxHours      number — how many hours a single spawned executor may
        be CONTINUED onto further tasks (never re-spawned) before the
        orchestrator stops preferring that and hands it back instead. Default 3
        — the point measured here where a continued agent's per-turn cost
        roughly triples, almost entirely in material it had already read once,
        because every later turn still carries everything earlier and the
        cache is rewritten as it lapses. No hook reads this either;
        `executor_context_bound_hours` below is read by the orchestrator at
        the same moment it decides whether to hand a running agent its next
        task (`reference/execute-task.md`'s continuation rule) rather than
        spawn a fresh one. A value that is not a positive number is REFUSED
        (the function returns None), the same shape `executor_gate_policy`
        uses for its own key and for the same reason — zero, negative or
        garbled is a mistake nobody meant, and folding it into the default
        would make the mistake look like a decision.
  review.perTask          str   — where a task's three review answers are
        given. One of REVIEW_PER_TASK_MODES: "phase" (the default — no
        reviewer per task; `done` records the intent as `deferred` and the
        phase review answers each task at sign-off, which refuses while one
        lacks its answers), "always" (a reviewer per task before its close),
        or "signals" (a reviewer per task only where its red-first proof did
        not come back `proved` or its return disagrees with the recorded gate).
        Recorded on the phase at its first start and on each task at its own,
        so the live value is read only while a phase records none. No hook
        reads this; `_config_rules.review_per_task_mode` does, and refuses a
        value outside the vocabulary rather than reading the default.

This module also hosts the path/manifest helpers the hooks share (rel_path,
within_root, matches_exempt, strip_line_suffix, in_progress_*).

Hooks never statically `import` anything from scripts/, this module included: they
run on every tool call, launched by a process that may not have scripts/ on its
sys.path, so scripts/-owned features (policy, journal, manifest assembly) are
loaded by path via `_load_scripts_module` and treated as optional, not required.

That sentence is machine-checked — `_deps.py` fails the build on any static
hooks->scripts import, with no allow-list. It had one, for one import: this
module's own manifest read, which the checker's first run found and which
was the only thing standing between the rule and being true.

This module carries no `--selftest` of its own any more; its cases live in
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

# The page DEFAULTS["usage"]["pricing"] was read from on its `pricingAsOf`. A
# module constant rather than a config key: it names where the SHIPPED rates came
# from, and a project that overrides them has its own source to answer to.
PRICING_SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"

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
    # consuming repo rather than a plugin release. Every rate is copied from the
    # page PRICING_SOURCE_URL names, as of `pricingAsOf`, never derived: the cache
    # read multiplier is not uniform across models. `_usage_core.py`
    # DEFAULT_PRICING, PRICING_AS_OF and PRICING_SOURCE_URL mirror this table, its
    # date and its source so that module works standalone; the `pp` and `pv` cases
    # in `tests/test__usage_core.py` read both copies and name any field that drifts.
    "usage": {
        "enabled": True,
        "ledgerDir": ".claude/usage",
        "authorMode": "email",
        "showCost": True,
        "backfillOnFirstRun": True,
        "maxScanBytes": 33554432,
        "currency": "USD",
        "pricingAsOf": "2026-10-06",
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
            "claude-fable-5-1":  {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 0.25},
            "claude-mythos-5":   {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 1.0},
            "claude-mythos-5-1": {"in": 10.0, "out": 50.0, "cacheW5m": 12.50, "cacheW1h": 20.0, "cacheR": 0.25},
            "claude-opus-5":     {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-5-5":   {"in":  4.0, "out": 20.0, "cacheW5m":  5.00, "cacheW1h":  8.0, "cacheR": 0.2},
            "claude-opus-4-8":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-7":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-6":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-opus-4-5":   {"in":  5.0, "out": 25.0, "cacheW5m":  6.25, "cacheW1h": 10.0, "cacheR": 0.5},
            "claude-sonnet-5":   {"in":  2.0, "out": 10.0, "cacheW5m":  2.50, "cacheW1h":  4.0, "cacheR": 0.2},
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
    # Where the test-evidence record lives -- an append-only NDJSON row per gate
    # run, one file per writer per month, COMMITTED beside the manifest like the
    # journal rather than kept as local scratch like the usage ledger: it is
    # evidence somebody hands to a client, so it has to survive a clone.
    #
    # NO `enabled` BESIDE IT, unlike the journal, and that is a decision rather
    # than an omission: recording is already opt-in at the call site
    # (`run-test-gate.py --record`), so a second off switch would be two keys
    # expressing one thing -- which COMPATIBILITY.md then owes a written
    # precedence rule for. One key, one purpose, and `_evidence_io.evidence_dir`
    # is what reads it.
    "evidence": {"dir": None},
    # th: the panel's and the report's LOOK. `theme` is a preset name or
    # a path to a theme file; absent means "search" -- .claude/audit.theme.json
    # in the project, then ~/.claude/audit.theme.json, then the built-in. No
    # hook reads this; it lives here because DEFAULTS is the one place the whole
    # config's shape is stated, and a key the validator knows but this file does
    # not is how the two drifted before.
    "ui": {"theme": None},
    # Phase prioritisation (scripts/manifest/_priority.py). ADVISORY, AND NOTHING
    # IS CLAMPED: `maxTier` is the highest tier the panel's control offers and the
    # CLI suggests, not a ceiling anything enforces. A phase pinned above it keeps
    # the tier it was given and sorts after every tier at or under the maximum by
    # ordinary arithmetic. Clamping would make the file say one thing and the run
    # do another. No hook reads this either -- it is here for `ui`'s reason: this
    # dict is the one place the whole config's shape is stated, and a key the
    # validator knows and this file does not is how the two drifted before.
    "priority": {"maxTier": 9},
    # Whether a capability that would NOT survive a clone may be used here:
    # "strict" (shipped) | "warn" | "off". A skill in somebody's home directory
    # never travels, and a plugin travels only if the COMMITTED settings declare
    # it in both `extraKnownMarketplaces` and `enabledPlugins`;
    # `_panel_discovery` grades every discovered capability and this key decides
    # whether the panel refuses to write one, merely reports it, or says nothing.
    #
    # Shipped strict, which is a BEHAVIOUR CHANGE for a repository that sets
    # nothing -- see COMPATIBILITY.md, where it is recorded as one. No hook reads
    # this; it is here for `ui`'s and `priority`'s reason: this dict is the one
    # place the whole config's shape is stated, and a key the validator knows and
    # this file does not is how the two drifted before.
    "portability": "strict",
    # How much of a task's gate the EXECUTOR runs itself before the orchestrator
    # runs the same gate again with `--record` — the only run that becomes
    # evidence. "own-tests" is the cheap default: an executor that ran the full
    # gate on every task was paying for two full-suite runs where one recorded
    # run already stands as proof. See RUNS_GATE_MODES and executor_gate_policy
    # below, and the "executor.runsGate" entry above for the vocabulary.
    #
    # "maxHours" bounds continuing the SAME agent across tasks, never a single
    # task's own runtime — see executor_context_bound_hours below and the
    # "executor.maxHours" entry above for why 3.
    "executor": {"runsGate": "own-tests", "maxHours": 3},
    # Where a task's three review answers - the intent binding, the red-first
    # grade, the inherited-test question - are given: "phase" (shipped) carries
    # them to the phase review at sign-off, "always" spawns a reviewer per task,
    # "signals" spawns one only where a computed signal fires. Shipped "phase",
    # which is a BEHAVIOUR CHANGE for a repository that sets nothing - see
    # COMPATIBILITY.md, where it is recorded as one. No hook reads this; it is
    # here for `ui`'s reason, and `_config_rules.review_per_task_mode` reads it.
    "review": {"perTask": "phase"},
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


def slashed(value):
    """A path as the guards MATCH it: "/" separators, on every platform.

    The secret and write rules are regexes over path text, so a Windows payload is
    respelled before any of them is asked. The respelling is published because the
    refusal message quotes the matched spelling - a case that retypes the payload's
    own separators asserts the wrong string on one of the two platforms, which is a
    case that can only be red where nobody is looking.
    """
    return str(value).replace("\\", "/")


def repo_root(data):
    """Locate the CONSUMING repo root: CLAUDE_PROJECT_DIR, else stdin cwd, else getcwd."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        root = (data or {}).get("cwd") or ""
    if not root:
        root = os.getcwd()
    return Path(root)


# --- which agent of this session made the call ---------------------------------
# THE ORCHESTRATOR IS A NAME HERE, NOT AN ABSENCE. A payload carries `agent_id`
# only when a subagent made the call - probed, not assumed (Claude Code 2.1.250,
# 2026-08-28: a PostToolUse hook dumping stdin under `claude -p`, one main-agent
# Bash call and two parallel Task agents; the subagents' payloads carried
# `agent_id` and `agent_type` at the top level and the main agent's carried
# neither, while `session_id` and `transcript_path` were IDENTICAL across all of
# them). So "no agent_id" means the orchestrator and nothing else - and writing
# that down as a word is what separates "the orchestrator did it" from "nobody
# recorded it". An empty field says both at once and a reader cannot tell which,
# which is why no caller here is handed one.
#
# A short word cannot collide with a real agent id, which is a long hex string,
# and `agent_of` sanitises anyway.
MAIN_AGENT = "main"
# ...AND A SUBAGENT WHOSE ID SURVIVES NO SANITISING IS NOT THE ORCHESTRATOR. The
# payload named an agent and only the spelling was unusable, so the answer says
# that rather than promoting the call to the one writer it certainly was not.
UNNAMED_AGENT = "agent-unnamed"
MAX_AGENT_CHARS = 40
_AGENT_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def is_subagent(data):
    """Whether a SUBAGENT made this tool call, rather than the orchestrator.

    One spelling for a question several guards asked in their own: `require-plan`
    refuses a subagent the manifest on the edit path and again on the scope path,
    `guard-secrets-read` refuses it the same file arriving by shell, and
    `guard-bash-writes` separates the writers inside one session by it. Each read
    the payload key itself, so a change in how the harness spells it would have
    had to be found at every site by whoever noticed first - list them with
    `grep -rn agent_id plugins/audit/hooks/`.

    The PRESENCE of the key decides, not the shape of its value: an id that
    sanitises away is still a subagent, and `agent_of` is where that is named.
    """
    return bool(str((data or {}).get("agent_id") or "").strip())


def agent_of(data):
    """Which writer inside this session made the call.

    -> the sanitised `agent_id`, `MAIN_AGENT` for the orchestrator, or
       `UNNAMED_AGENT` for an id that sanitises away

    Every answer is a word, so a caller that records one records an answer rather
    than a blank. Sanitised and bounded because callers put the value where it is
    read back: a key in a state file, a name quoted into a message injected into
    the model's context, a field of a committed journal row. A payload field is
    not a place to trust.
    """
    if not is_subagent(data):
        return MAIN_AGENT
    ident = _AGENT_SAFE.sub("-", str(data.get("agent_id"))).strip("-.")
    return ident[:MAX_AGENT_CHARS].strip("-.") or UNNAMED_AGENT


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


# --- the tree question, which is not the config question ----------------------
# `repo_root()` above answers WHERE THE CONFIG LIVES, and CLAUDE_PROJECT_DIR wins
# there deliberately: the config belongs to the project, and a worktree should not
# need its own copy of it. It is the wrong answer to a second question this plugin
# also asks - WHICH TREE DID THIS COMMAND TOUCH - and the two came apart the first
# time an agent worked inside a git worktree. The env var stays pinned to the
# primary checkout, so `guard-bash-writes` ran `git status` there and told a
# read-only sweep in the worktree that it had modified files a parallel session was
# editing in the other tree.
#
# Git already tells the two trees apart, and nothing here re-derives it: a
# worktree's `--show-toplevel` is the worktree, its `--git-common-dir` is the shared
# `.git`. Path arithmetic cannot stand in for either - an agent worktree sits UNDER
# the project directory, so every containment test calls it the same tree.
# The basis clause both answers below give a linked worktree of this same
# repository. A constant because `tree_for` reads it back to decide whether to
# re-root, and a re-spelled literal in one of three places would re-root nothing.
LINKED_WORKTREE = "a linked worktree of the same repository"


def _same_dir(a, b):
    """Do two path strings name the same directory on disk?

    `os.path.realpath` on both sides, which is the whole implementation. A raw
    string comparison gets this wrong in two ways the suites produce on their own:
    a trailing separator, and the symlinked temp root every `mkdtemp` fixture sits
    under (`/var` -> `/private/var` on macOS)."""
    try:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))
    except Exception:
        return False


def _git_rev_parse(cwd, fields):
    """`git rev-parse` answers for `cwd`, one string per field, or None.

    A LIST of fields because `rev-parse` answers several questions in one process,
    and the caller pays for processes rather than for questions.

    None means git declined to answer at all - not a repository, no git on PATH, a
    directory that does not exist, a call that did not finish. Nothing is salvaged
    from a non-zero exit, and that is not the discarded-stdout mistake: `rev-parse`
    writes its answer to stdout only when it succeeds, so keeping stdout on failure
    would be keeping an empty string and calling it a path.

    THE RETURNCODE TEST IS DEFENSIVE and no case can currently distinguish it.
    What was observed is a refusal exiting 128 with EMPTY stdout, which the field
    count below already rejects; the test stays for a non-zero exit that prints a
    partial answer, which `rev-parse` was not seen to do. Labelled rather than
    deleted, and labelled rather than left looking load-bearing.

    `subprocess` IS IMPORTED INSIDE. Every hook imports this module at module scope
    on every matching tool call and most of them never ask git anything - the same
    budget that made `guard-bash-writes` import it inside `_git_dirty`."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse"] + list(fields),
                             capture_output=True, timeout=5, text=True)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    lines = [ln.strip() for ln in out.stdout.splitlines()]
    return lines if len(lines) == len(fields) else None


def _shares_repository(cwd, common_dir, watching, ours=None):
    """Is the `.git` behind `cwd` the same one the watched tree uses?

    Separates a linked worktree of THIS repository from an unrelated checkout,
    which is the difference between "the phase worktree walked out of view" and
    "you are in somebody else's repo". That is its whole job: it changes the
    sentence a notice prints and never the verdict.

    `--git-common-dir` COMES BACK RELATIVE TO THE DIRECTORY GIT RAN IN for an
    ordinary checkout, and absolute from a linked worktree. Probed rather than
    assumed (git 2.50.1, 2026-08-23):

        git -C <repo>     rev-parse --git-common-dir  ->  .git
        git -C <repo>/a/b rev-parse --git-common-dir  ->  ../../.git
        git -C <worktree> rev-parse --git-common-dir  ->  /abs/<repo>/.git

    so both answers are joined against the directory they were asked from before
    anything compares them; `os.path.join` returns an absolute right-hand side
    unchanged, which is what lets one expression cover both shapes. Reading it as
    an absolute path is the mistake a hand-written fake would have agreed with.

    THE SAME INSTRUMENT ALREADY EXISTS on the other side of the import boundary:
    `scripts/governance/_locks.lock_dir()` resolves `--git-common-dir` and joins a
    relative answer against the directory it asked from, so that "the locks span
    every worktree of one clone". `hooks/` may import nothing from `scripts/`, so
    this is a duplication the layer rule forces rather than one to tidy away - and
    the agreement is pinned by a case (`w9` in `test__config.py`) instead of
    asserted in a comment.

    It costs the second `git rev-parse` of the pass, and only ever runs once the
    trees have already been established to differ.

    `ours` LETS A CALLER THAT ALREADY ASKED HAND THE ANSWER IN, rather than
    paying for that same question twice: `path_tree` below needs `watching`'s
    own `--git-common-dir` one branch before it can even reach this function
    (to tell "no repository to compare against" apart from everything else), so
    without this it would ask git the identical question a second time on every
    call. None (the default) re-derives it exactly as before, so `command_tree`
    above is unchanged."""
    if ours is None:
        ours = _git_rev_parse(watching, ["--git-common-dir"])
    if not ours or not ours[0]:
        return False
    return _same_dir(os.path.join(str(cwd), common_dir),
                     os.path.join(str(watching), ours[0]))


def command_tree(data, root, cfg):
    """Which WORKING TREE did this tool call run in, against the one we watch.

    -> {"tree", "watching", "watched", "basis"}
       tree      the tree git named for the payload's cwd, or None when it named
                 none
       watching  the tree the caller watches - `git_root_dir(root, cfg)`, so the
                 project's `gitRoot` declaration is what this refines and never
                 what it replaces
       watched   may the caller attribute what it sees in `watching` to this call?
       basis     why - the clause a notice prints, because a claim with no basis
                 is the defect this function exists inside of

    `watched` IS TRUE WHENEVER THE TREE CANNOT BE ESTABLISHED, and that direction
    is chosen rather than inherited. `gitRoot` is the project's own declaration of
    which tree to watch, so with no evidence to the contrary the declaration
    stands; only positive evidence that the command ran somewhere else takes the
    claim away. Failing the other way would hand any command a silence by running
    it somewhere git cannot answer about, and for the guard that reads this a
    stray notice costs a line of text while a miss costs a write nobody was told
    about.

    The equal-path short circuit is not an optimisation looking for a home: the
    ordinary case is a session whose cwd IS the watched tree, and it is answered
    without starting a process at all. Only a cwd that differs pays git.

    WHAT THE PAYLOAD CARRIES, probed against the real harness rather than reasoned
    about (Claude Code 2.1.241, 2026-08-23; a PostToolUse Bash hook dumping stdin,
    driven by `claude -p` over four separate Bash calls):

        1) `pwd`                 -> cwd = <project>
        2) `cd sub/deep && pwd`  -> cwd = <project>/sub/deep
        3) `pwd`                 -> cwd = <project>/sub/deep
        4) `cd <project>/wt`     -> cwd = <project>/wt          (a linked worktree)

    So `cwd` is present on every call, it is the shell's directory AFTER the
    command ran, and it tracks a `cd` both within one call and across calls - while
    `CLAUDE_PROJECT_DIR` stayed `<project>` throughout and the hook PROCESS's own
    `os.getcwd()` was `<project>` too, not the shell's. The payload was already
    carrying the answer; the gap was `repo_root()`'s preference order discarding it. The
    empty-cwd branch above is therefore defensive: no payload without the field was
    observed, and the branch exists because a hook must not raise over one.

    RESIDUAL, AND THE FIRST PROBE READ IT TOO NARROWLY. It said a command is
    placed where the shell ENDED UP, so one that walks INTO a tree and writes
    there is placed right and only one that writes and then walks OUT is
    misplaced. That is true of the MAIN session, where a `cd` moves the session's
    directory and therefore this field. It is NOT true of an agent, whose shell
    starts back in the session's directory on every call: `cd <worktree> && x`
    moves nothing this field can see, the paths compare equal, and the short
    circuit above answers "watched" without asking git at all. Reaching a
    phase worktree that way is the ordinary shape here, not an exotic one.

    `guard-bash-writes.directory_change_basis` is what reads the `cd` in that
    case, and it only ever WITHDRAWS an attribution - inferring a tree from the
    command text in order to MAKE one is the same raw-string guessing a command
    tokenizer exists to replace."""
    watching = git_root_dir(root, cfg)
    cwd = str((data or {}).get("cwd") or "")
    if not cwd:
        return {"tree": None, "watching": str(watching), "watched": True,
                "basis": "the hook payload named no working directory"}
    if _same_dir(cwd, watching):
        return {"tree": str(watching), "watching": str(watching),
                "watched": True, "basis": "the command ran in the watched tree"}
    got = _git_rev_parse(cwd, ["--show-toplevel", "--git-common-dir"])
    if not got or not got[0]:
        return {"tree": None, "watching": str(watching), "watched": True,
                "basis": "git names no working tree for %s" % cwd}
    if _same_dir(got[0], watching):
        return {"tree": got[0], "watching": str(watching), "watched": True,
                "basis": "the command ran in the watched tree"}
    return {"tree": got[0], "watching": str(watching), "watched": False,
            "basis": (LINKED_WORKTREE
                      if _shares_repository(cwd, got[1], watching)
                      else "a separate git repository")}


def _nearest_existing_dir(path):
    """The nearest existing directory containing `path`, climbing from `path`
    itself when it is already one, else from its parent - or None when the
    climb runs out (an unrooted relative fragment, or a parent chain that
    never bottoms out).

    Almost every caller's first step already answers this: an Edit target
    must exist to be edited, and an ordinary Write lands in a directory that
    is already there. This exists for the one shape neither of those is - a
    Write whose whole parent chain is still being created - which is also the
    one case `path_tree` below has nothing to ask `git -C` about at all."""
    try:
        p = Path(str(path))
    except Exception:
        return None
    seen = set()
    while True:
        s = str(p)
        if s in seen:
            return None
        seen.add(s)
        if os.path.isdir(s):
            return s
        parent = p.parent
        if parent == p:
            return None
        p = parent


def _memo_rev_parse(cache, cwd, fields):
    """`_git_rev_parse(cwd, fields)`, asked once per (directory, fields) when
    `cache` is a dict the caller keeps, and every time when it is None."""
    if cache is None:
        return _git_rev_parse(cwd, fields)
    key = ("rev-parse", str(cwd), tuple(fields))
    if key not in cache:
        cache[key] = _git_rev_parse(cwd, fields)
    return cache[key]


def _inside_known_tree(real, top):
    """True when the resolved directory `real` lies in the working tree whose
    resolved toplevel is `top`, with no repository of its own in between: no
    directory from `real` up to, but not including, `top` holds a `.git`
    entry - a nested clone, a submodule or a linked worktree placed inside
    the tree, each of which git would name as a toplevel of its own."""
    if real != top and not real.startswith(top.rstrip(os.sep) + os.sep):
        return False
    at = real
    while at != top:
        if os.path.lexists(os.path.join(at, ".git")):
            return False
        parent = os.path.dirname(at)
        if parent == at:
            return False
        at = parent
    return True


def _tree_of_dir(cache, start):
    """`git rev-parse --show-toplevel --git-common-dir` for the existing
    directory `start`, the common dir made absolute - or None.

    ONE QUESTION PER TOPLEVEL, WHEN THE CALLER KEEPS A `cache`. A directory
    under a toplevel git already named for this cache is answered by
    containment, with no process: a whole copy onto directories that already
    exist lists each file in a directory of its own, and a memo keyed by
    directory still started one git per directory - a wide tree inside a
    linked worktree outran the hook's timeout that way, and a killed hook
    lets the write through. Containment is decided on the RESOLVED path,
    which is also what git answers for, so a symlinked subdirectory pointing
    out of the tree is asked about where it really is; and a `.git` entry on
    the way up hands the question back to git (`_inside_known_tree`).

    The common dir comes back relative to the directory asked from for an
    ordinary checkout (`_shares_repository`'s note), so it is joined there
    before it is reused for any other directory."""
    fields = ["--show-toplevel", "--git-common-dir"]
    if cache is None:
        got = _git_rev_parse(start, fields)
        return got if not got or not got[0] else [
            got[0], os.path.join(str(start), got[1])]
    try:
        real = os.path.realpath(str(start))
    except Exception:
        real = None
    known = cache.setdefault(("toplevels",), [])
    for top, answer in known:
        if real is not None and _inside_known_tree(real, top):
            return answer
    got = _memo_rev_parse(cache, start, fields)
    if not got or not got[0]:
        return got
    answer = [got[0], os.path.join(str(start), got[1])]
    try:
        known.append((os.path.realpath(got[0]), answer))
    except Exception:
        pass
    return answer


def path_tree(file_path, root, cfg, cache=None):
    """Where a FILE lands, for a caller that already knows `file_path` is not
    under `root` (`within_root` answered False) - the plan gate's own "is this
    even mine" question, asked of a PATH rather than of `command_tree`'s `cwd`.

    -> {"root": the tree to judge this edit under - `root` unchanged, or a
                 different tree's own toplevel,
        "placed": whether that answer may be trusted at all,
        "basis": the clause a verdict may quote}

    `root` UNCHANGED is the answer for two different reasons, and both mean
    "not my business" rather than "judged elsewhere":
      * this project names no git repository to compare against in the first
        place, so "is this a worktree of it" has no question to answer - a
        consuming repo need not be a git checkout for the rest of this plugin
        to work, and this one question does not get to require one where
        nothing else does;
      * git DOES answer for `file_path`, and the answer is a repository other
        than this one, or no repository at all - the case `within_root` sends
        here in the first place: a helper script under the system temp
        directory names no git tree, and this project's own manifest can never
        have an opinion about it.

    A LINKED WORKTREE OF THIS SAME REPOSITORY is the one case that is not
    `root`: `file_path`'s own toplevel comes back instead, so every manifest
    read that follows opens the file that TREE actually holds on disk. A
    worktree does not share an uncommitted edit with its sibling - the two can
    disagree about whether a phase is even running - so `root`'s own manifest
    is not a stand-in for it and answering with `root` here would be exactly
    that stand-in.

    `placed` IS FALSE FOR ONE REASON ONLY, and "git said no" is not it: no
    EXISTING directory contains `file_path` at all, so there is nowhere to run
    `git -C` from and therefore no confident "not a repository" to fall back
    on either - both answers above need a place to stand and this gives them
    none. That is narrower than "git could not answer", which also covers git
    missing from PATH or a call that timed out; both of those already read as
    "no repository here" in the paragraph above, a residual `_git_rev_parse`
    already carries and this does not try to resolve a second time.

    PAID FOR ONLY BY A CALLER WHOSE CHEAP CHECK ALREADY FAILED. The ordinary
    edit, inside the tree the session started in, never reaches this function
    and never pays for the git calls inside it - `within_root` answers it with
    no process started at all.

    ONE QUESTION PER TOPLEVEL, WHEN THE CALLER KEEPS A `cache`. Both git
    answers depend on a directory and never on the file in it - the watched
    tree's, and the nearest existing directory's - so a caller placing many
    files hands one dict to every call; a directory is asked once, and one
    under a toplevel already named is answered by containment
    (`_tree_of_dir`). A recursive copy out of the tree placed every file it
    lands with two processes of its own, which outran the hook's timeout on
    an ordinary directory. With no cache every call asks afresh, as it always
    did."""
    watching = git_root_dir(root, cfg)
    ours = _memo_rev_parse(cache, watching, ["--git-common-dir"])
    if not ours or not ours[0]:
        return {"root": str(root), "placed": True,
                "basis": "this project names no git repository to compare "
                         "against"}
    start = _nearest_existing_dir(file_path)
    if start is None:
        return {"root": str(root), "placed": False,
                "basis": "no existing directory contains %s" % file_path}
    got = _tree_of_dir(cache, start)
    if not got or not got[0]:
        return {"root": str(root), "placed": True,
                "basis": "git names no working tree for %s" % start}
    if _shares_repository(start, got[1], watching, ours=ours):
        return {"root": got[0], "placed": True, "basis": LINKED_WORKTREE}
    return {"root": str(root), "placed": True,
            "basis": "a separate git repository"}


def in_project(file_path, root, cfg):
    """Is `file_path` this project's business - `within_root`, widened to a
    linked worktree of the same repository via `path_tree`.

    A YES/NO QUESTION FOR A CANDIDATE FILTER, not the verdict `path_tree`
    itself hands to a caller that has already committed to ONE file. Used
    where several locators share a payload and each is asked in turn "is this
    even a candidate" before anything is decided about any of them
    (`_mcp_plan_target`): a locator this returns False for is skipped so the
    next one gets a turn, exactly as `within_root` already did, and one this
    returns True for is handed to the caller's own `decide()` pass, which asks
    `path_tree` again and re-roots properly - so an unplaceable tree is never
    silently swallowed here, only ever skipped as "not a candidate" the same
    way a truly unrelated one already was.
    """
    if within_root(root, file_path):
        return True
    placement = path_tree(file_path, root, cfg)
    return bool(placement["placed"]) and placement["root"] != str(root)


# `tree_for`'s target when the caller judges nothing yet and wants only the
# homes - the config and the session's state - because it places each target
# itself afterwards. Named rather than implied by some other value, so asking
# for less than a verdict is visible at the call site.
PROJECT_ONLY = object()


def tree_for(data, target=None, cfg=None, project=None, cache=None):
    """Which tree's PLAN governs the work this hook is judging - the one
    question every hook that reads the manifest asks before it reads it.

    -> {"root":    the tree whose manifest, shards and journal are read - the
                   project, or a linked worktree of it,
        "project": where the config and the session's own state live
                   (`repo_root`, or the caller's `project`),
        "cfg":     the config, loaded from `project` unless handed in,
        "moved":   `root` is a different tree from `project`,
        "placed":  False only when `target` cannot be placed at all,
        "inside":  `target` lies inside `root` (always True with no target),
        "rel":     `target` relative to `root`, or None,
        "basis":   the clause a verdict may quote,
        "command": `command_tree`'s own answer when it was asked, else None}

    TWO QUESTIONS, TWO HOMES. `repo_root` answers where the config lives, and
    CLAUDE_PROJECT_DIR wins there on purpose. It is the wrong answer to "whose
    plan is this edit held to": an executor in a linked worktree of the
    project was told "Phase P41 is in_progress" by one hook while the tree it
    was writing in ran P48, and skipped by another hook for the same file. A
    worktree does not share an uncommitted manifest with its sibling, so the
    project's copy is not a stand-in for the worktree's. Session state (bypass
    flags, baselines, throttles) stays with `project`: it is keyed by session,
    and the prompt hook that arms a bypass cannot know which tree the next edit
    will land in.

    WHAT IS JUDGED:
      * a `target` PATH (a file, or the directory a command runs in) - inside
        `project` it is the project, answered with no process at all; outside
        it `path_tree` asks git, and only a linked worktree of this repository
        re-roots. A separate repository, or no repository, is `inside: False`
        - not this plan's business; no existing directory at all is `placed:
        False`, which the caller refuses or skips, never guesses;
      * no target - the SESSION's working directory from the payload, through
        the same containment shortcut and then `command_tree`. A Bash command
        that walks with `cd` is placed by handing `effective_cwd`'s answer in
        as the target; this function does not read command text;
      * `PROJECT_ONLY` - nothing is judged and nothing is asked of git: the
        caller wants the config and the state home, and places its own
        targets through this function afterwards.

    `cache` is `path_tree`'s: a dict a caller placing many targets keeps
    across its calls, so a directory outside the project is asked about once.

    RESIDUAL, stated because the containment shortcut is what makes it: a
    linked worktree placed UNDER the project directory is judged as part of
    the project, since `within_root` answers before git is asked. The default
    exempt globs cover `.claude/**`, where the harness puts its own agent
    worktrees; a worktree elsewhere under the project is judged against the
    project's plan with its path spelled from the project root.
    """
    project = Path(project) if project is not None else repo_root(data)
    cfg = cfg if cfg is not None else load(project)
    out = {"root": project, "project": project, "cfg": cfg, "moved": False,
           "placed": True, "inside": True, "rel": None, "basis": "",
           "command": None}
    if target is PROJECT_ONLY:
        out["basis"] = "no target named yet"
        return out
    if target is None or str(target) == "":
        cwd = str((data or {}).get("cwd") or "")
        if not cwd or within_root(project, cwd):
            out["basis"] = ("the session's directory is the project" if cwd
                            else "the hook payload named no working directory")
            return out
        tree = command_tree(data, project, cfg)
        out["command"] = tree
        out["basis"] = tree["basis"]
        if not tree["watched"] and tree["basis"] == LINKED_WORKTREE \
                and tree["tree"]:
            out["root"] = Path(tree["tree"])
            out["moved"] = True
        return out
    if within_root(project, target):
        out["rel"] = rel_path(project, target)
        out["basis"] = "inside the project"
        return out
    placement = path_tree(target, project, cfg, cache=cache)
    out["basis"] = placement["basis"]
    if not placement["placed"]:
        out["placed"] = False
        out["inside"] = False
        return out
    if placement["root"] == str(project):
        out["inside"] = False
        return out
    # git answers `--show-toplevel` fully resolved, so `target` is resolved
    # too before the subtraction: a symlinked component on one side only would
    # climb back out of the worktree as `../..`, which no `files` entry holds.
    out["root"] = Path(placement["root"])
    out["moved"] = True
    out["rel"] = rel_path(out["root"], os.path.realpath(str(target)))
    return out


def state_dir(root, cfg):
    return root / (cfg.get("stateDir") or DEFAULTS["stateDir"])


def logs_dir(root, cfg):
    return root / (cfg.get("logsDir") or DEFAULTS["logsDir"])


# --- the session's free-file slot ----------------------------------------------
# `trivialLineThreshold`'s allowance is ONE file per session, whichever tool
# writes it. `require-plan.py` grades Edit/Write against it,
# `guard-secrets-read.py` grades a shell write against it and
# `guard-bash-writes.py` measures that shell write once it has landed, and the
# slot has one reader and one writer here so the hooks cannot disagree about
# which file a session has already spent it on - which is what they did while
# the shell half never read the slot at all.
TRIVIAL_SLOT = "plan-gate-%s.json"
_SLOT_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_SLOT_ID_MAX = 96


def _slot_path(state, session_id):
    """The slot's file. The session id is payload text, so it is reduced to a
    file-name-safe class and bounded before it names a file: a separator in
    it would otherwise place the slot outside the state directory."""
    sid = _SLOT_UNSAFE.sub("_", str(session_id or "no-session"))[:_SLOT_ID_MAX]
    return Path(state) / (TRIVIAL_SLOT % sid)


def text_lines(text):
    """Lines in `text`; 0 for the empty string."""
    s = str(text)
    return 0 if s == "" else len(s.splitlines())


def text_char_lines(text):
    """`text`'s length in 200-character lines, rounded up."""
    return (len(str(text)) + 199) // 200


def text_magnitude(text):
    """The size `trivialLineThreshold` is compared against, for a body of
    text: max(lines, chars / 200, rounded up). One formula for both plan-gate
    halves - require-plan measures an edit's new text with it, and
    guard-secrets-read measures the content a shell write states - so a
    one-line blob and a long file count the same through either tool."""
    return max(text_lines(text), text_char_lines(text))


def change_magnitude(new, old):
    """The size of a change that replaces `old` text with `new`: the new
    text's `text_magnitude`, or the removed text's lines when more were taken
    away than put in - so a large deletion is not trivial either. require-plan
    sizes an Edit this way, and guard-bash-writes sizes the diff a shell write
    left behind this way, so the free-file limit means one thing after the
    fact as well as before it."""
    return max(text_magnitude(new), text_lines(old))


# What `trivial_slot` answers for a slot file that exists but names no file it
# can read. Not a path any tree holds, so it never matches a `rel` - the slot
# is spent, on a file nobody can name.
SLOT_UNREADABLE = "(an unreadable free-file slot)"


def trivial_slot(state, session_id):
    """The repo-relative files this session's free-file slot holds; [] while
    it is unspent.

    A SLOT FILE THAT EXISTS IS A SPENT SLOT, readable or not. One that cannot
    be parsed, or names no file, answers [SLOT_UNREADABLE]: spent on a file
    nobody can name, so the next uncovered file is graded. Reading it as
    unspent gave two verdicts by tool - an Edit was allowed as the first free
    file while a shell write, whose exclusive take then failed, was graded -
    and kept the door open for the rest of the session. Only an ABSENT file
    is unspent. `take_trivial_slot` publishes the file whole, so a reader
    never meets one half-written by a live writer; this answer is for a file
    damaged some other way."""
    path = _slot_path(state, session_id)
    try:
        if not path.exists():
            return []
    except Exception:
        return [SLOT_UNREADABLE]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        files = loaded.get("files") if isinstance(loaded, dict) else None
        named = [f for f in files or [] if isinstance(f, str)]
        return named or [SLOT_UNREADABLE]
    except Exception:
        return [SLOT_UNREADABLE]


def take_trivial_slot(state, session_id, files):
    """Take this session's slot for `files`.

    -> True   taken
       False  another write took it first: the slot file already exists, so
              the loser re-reads the slot and is graded against it
       None   the slot could not be written at all

    PUBLISHED WHOLE. The JSON is written to a temp file in the state
    directory and `os.link`ed to the slot's name, which fails if the name
    exists - so two writers racing for an empty slot cannot both win, and no
    reader can ever see a slot file that is present but not yet written. An
    exclusive create followed by a write had the first property and not the
    second: a failed write left an empty slot file behind. A volume that
    refuses hard links falls back to exactly that create
    (`_take_slot_exclusive`), so a writable directory always takes the slot.

    NONE IS AN OPEN DOOR, and it is stated here because it is the cost of
    keeping state writes best-effort. With a state directory nobody can write,
    every slot reads as unspent, so EVERY uncovered file of the session is
    taken as its first free file and allowed - at the deny tier too, through
    either tool. A hook cannot refuse an edit for want of its own scratch
    space without making that scratch space a way to stop all work, so the
    door is accepted and named rather than closed.

    `tempfile` is imported here, not at module scope, for the reason
    `atomic_write_text` gives: every hook imports this module on every call,
    and this is reached only when a slot is taken."""
    import tempfile
    tmp = None
    try:
        ensure_local_dir(Path(state))
        fd, tmp = tempfile.mkstemp(dir=str(state), prefix="plan-gate-tmp-",
                                   suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"files": list(files)}, fh)
        try:
            os.link(tmp, str(_slot_path(state, session_id)))
        except FileExistsError:
            raise
        except OSError:
            return _take_slot_exclusive(state, session_id, files)
        return True
    except FileExistsError:
        return False
    except Exception:
        return None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except Exception:
                pass


def _take_slot_exclusive(state, session_id, files):
    """`take_trivial_slot` on a volume that refuses hard links.

    FAT/exFAT, some SMB and FUSE mounts and some container bind mounts raise
    on `os.link` in a directory that is perfectly writable, and reading that
    as "the slot cannot be written" opened the door for every uncovered file
    of the session. So the slot is taken by an exclusive create instead: the
    race is still won once, and the cost is the property `os.link` bought - a
    write that fails after the create leaves a partial file, which
    `trivial_slot` reads as SLOT_UNREADABLE, a spent slot. That errs strict.
    None only when this create fails too."""
    try:
        fd = os.open(str(_slot_path(state, session_id)),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    except Exception:
        return None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"files": list(files)}, fh)
        return True
    except Exception:
        return None


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
# The capability policy's defaults are NOT written out here, and they are no longer
# copied into DEFAULTS either. _policy.py owns the block — its shape, its resolution
# order and what "inert" means — and a second copy of the shipped values in this file
# is the drift this repository has already shipped once (`exemptGlobs` and
# `tddReminder.testGlobs` disagreeing about what a test file is). `policy_cfg` below
# delegates rather than merging by hand, and it re-derives the whole block from the
# project's RAW `policy` key, so a copy in DEFAULTS changed nothing any caller could
# observe. What it did change was the cost of importing this file: loading the module
# eagerly executed the scripts-side `_policy.py`, whose pinned preamble imports
# `_output`, which imports `ast` — a build-time dependency of the house-style lints,
# dragged onto the hot path of every hook. Exactly one hook consults a policy, on a
# matcher (Skill|Task|Agent|mcp__.*) that never coincides with an edit or a shell
# call, so the load is lazy and memoized like the ledger, journal and areas libs.
# If the module is missing there is no policy engine at all — which every reader
# treats as "allow", the same fail-open the rest of this file uses.
_POLICY_LIB = {"tried": False, "mod": None}


def policy_mod():
    """_policy.py, loaded once, or None when this install has no policy engine."""
    if not _POLICY_LIB["tried"]:
        _POLICY_LIB["tried"] = True
        _POLICY_LIB["mod"] = _load_scripts_module("audit_policy", "_policy.py")
    return _POLICY_LIB["mod"]


def policy_cfg(cfg):
    """The merged `policy` block, or None when there is no policy engine here.

    Delegates to `_policy.policy_cfg` for the same reason `journal_dir` delegates
    to audit-journal: the module that resolves a policy owns what an absent key
    means, and a second merge in this file would be free to disagree with it.
    """
    mod = policy_mod()
    if mod is None:
        return None
    try:
        return mod.policy_cfg(cfg or {})
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
    """The `meta.areas` tags of phases whose area is live, in manifest order.

    This is what scopes a per-area policy rule. A hook is handed a tool name and
    nothing else — no directory, no file — so "this rule applies to the API area"
    can only mean "while the API area is being worked on". That is
    `_manifest_io.area_active`, and it is WIDER than the plan gate's evidence on
    purpose: a phase with work in flight, and also one only awaiting sign-off,
    whose review and fix runs still work in that area. The plan gate's denying
    tier is not held by the second kind; the area's rules are.

    Reads the ASSEMBLED manifest, which is load-bearing under the sharded layout —
    the index stubs carry no status, so a raw read would report nothing running and
    every area rule would be silently inert. Empty list on any error, which resolves
    to the policy without its area rules: fail-open, like everything else here.

    A phase carrying `mergedAt` is skipped before "running" is even asked, whatever
    its `status` still says: `close-phase.py` stamps `mergedAt` and never touches
    `status`, so a phase merged hours ago can still read `in_progress` and hold its
    area's policy open for ever. `_panel_policy._active_area_tags` asks the panel's
    preview the same question the same way — the two must move together, or the
    guard and the preview would disagree about which areas are live.
    """
    tags = []
    try:
        manifest = _load_manifest_assembled(Path(root) / manifest_rel)
        if not isinstance(manifest, dict):
            return tags
        areas = _areas_lib()
        mio = _load_scripts_module("_manifest_io", "_manifest_io.py")
        for phase in manifest.get("phases") or []:
            if not isinstance(phase, dict) or mio is None:
                continue
            running = mio.area_active(phase)
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


# --- where a Bash command stands -------------------------------------------------
def command_clauses(cmd):
    """Split a shell command into clauses on `;`, `|`, `&`, NEWLINE, outside quotes.

    The newline was added as a separator, matching how a multi-line Bash block is
    actually written -- and its absence was this function's own documented
    defect surviving in the one spelling nobody had tried. Measured: the two
    lines below deny together and neither denies alone, while the same two joined
    with `;` are allowed. The evidence was being taken from two different
    commands and applied to the block as a whole.

    The inline-eval heuristics must judge each clause on its own facts:
    `x.py --selftest >/tmp/out; python3 -c "json.load(open('a.json'))"` is a
    redirect in one clause and an eval in another, and reading them as one
    command manufactured a deny neither clause earns (reproduced live).

    Deliberately simple, and FAIL-SAFE about its own limits: quote tracking
    covers '...', "..." and backslash escapes; when the quoting cannot be
    tracked (unbalanced at end of string) the WHOLE command is returned as one
    clause, so an unparseable command is judged exactly as strictly as before
    the split existed. A single-clause command comes back unchanged either way
    — the split can only narrow multi-clause false positives, never widen what
    one clause may do. Separators inside `$( )` are an accepted imprecision:
    full shell parsing is out of scope here (see the header's trade-off note),
    and each fragment is still judged by the same regexes.

    A LINE CONTINUATION IS NOT A SEPARATOR and needs no special case: the
    backslash branch above already consumes the character after it, so one
    ending a line eats its own newline and the two lines stay one clause.
    (Spelled without the character itself: in a non-raw docstring it would
    open an invalid escape sequence, which is a SyntaxWarning -- and the
    warning machinery pulls `warnings`, `linecache` and `tokenize` into a
    hook that must import fast, which is how `bench-hooks --gate` found it.)
    A newline inside quotes is likewise held together by the quote tracking, which
    is why the transport shape -- an interpreter invocation and a repo path both
    inside ONE quoted argument handed to another program -- is still refused.
    That one cannot be fixed by splitting: it needs knowing the text is an
    argument rather than a program, which is real shell parsing. Stated here
    rather than left to be rediscovered."""
    parts, buf, quote = [], [], None
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch in (";", "|", "&", "\n", "\r"):
            if "".join(buf).strip():
                parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if quote is not None:
        return [cmd]  # unbalanced quoting: unsure, so judge it as ONE clause
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts or [cmd]


_DIR_CHANGE_CLAUSE = re.compile(
    r"^\s*(cd|pushd|popd)(?:\s+(.*))?$", re.IGNORECASE)


_DQUOTE_ESCAPABLE = "$`\"\\"


def shell_words(text):
    """`text` split into the words the shell would hand a program, quotes
    removed, or None when a quote never closes.

    A backslash before whitespace or a quote keeps that character in its word,
    and inside double quotes one before `$`, a backtick, `"` or a backslash
    does the same - which is how a command handed to `bash -c "..."` spells a
    quote of its own. Other backslashes stay literal so a Windows path remains
    one word. No expansion is performed: a word carrying `$` keeps it, for
    `resolvable_destination` to read."""
    words, current, quote, has_word = [], [], None, False
    index = 0
    while index < len(text):
        ch = text[index]
        if quote == '"' and ch == "\\" and index + 1 < len(text) \
                and text[index + 1] in _DQUOTE_ESCAPABLE:
            current.append(text[index + 1])
            index += 2
            continue
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
        elif ch == "\\" and index + 1 < len(text) and (
                text[index + 1].isspace() or text[index + 1] in "'\""):
            current.append(text[index + 1])
            has_word = True
            index += 1
        elif ch in ("'", '"'):
            quote, has_word = ch, True
        elif ch.isspace():
            if has_word:
                words.append("".join(current))
            current, has_word = [], False
        else:
            current.append(ch)
            has_word = True
        index += 1
    if quote:
        return None
    if has_word:
        words.append("".join(current))
    return words


def effective_cwd(cmd, payload_cwd):
    """Where this command's shell is standing when its writes actually run.

    -> an absolute directory, or None when this cannot be said at all

    A RELATIVE WRITE TARGET IS A WORD ABOUT SOMEWHERE, AND "SOMEWHERE" WAS
    ALWAYS THE REPOSITORY ROOT in `guard-secrets-read` - never read from the
    payload and never read from the command. `sed -i 's/a/b/' notes.py` run from a directory
    outside the repository, or reached through `cd <elsewhere> &&`, named a
    repository-relative path that does not exist and was refused for plan
    coverage under that name, while the identical write spelled from inside
    the tree was refused correctly - one file, one command shape, two
    verdicts decided by where the shell happened to be standing. The payload
    already carries the shell's own starting point: `cwd`, the SESSION's
    directory and the same field `guard-bash-writes.directory_change_basis`
    reads for the same reason (a hook may not import a hook, so this is a
    second reading of the same field rather than a second field). A leading
    `cd`/`pushd` in the command text is the one thing that moves it before a
    write runs. The journal recorder and the history guard ask the same
    question to place a command in a working tree, which is why the answer
    lives here rather than in the guard that first needed it.

    NO PAYLOAD `cwd` AT ALL IS UNRESOLVABLE - not a silent fallback to this
    process's own directory or to the repository root. Either guess answers a
    question about the SHELL with an answer about something else, which is
    the same invented-target class `_resolve_write_expr` already refuses to
    commit for a bound name it cannot read.

    A DIRECTORY CHANGE THIS CANNOT READ ENDS THE WALK, for every write that
    follows it in the command. `cd`/`pushd` with anything but exactly one
    literal argument - balanced quotes or a backslash directly before
    whitespace may spell literal whitespace, but no expansion, substitution,
    glob or home shorthand is read - and `popd` (which needs a push stack this
    process never saw a matching `pushd` build) both leave the rest of the
    command standing somewhere this cannot name. That is not a second
    mechanism: it is the withdrawal `resolvable_destination` already makes
    for a mark in the target's OWN text, extended to the one case it was one
    short of - a plain word with nothing to resolve it against.

    ONE PASS, ACCUMULATING, over every non-heredoc clause in the command in the
    order it is written - not the directory change nearest a particular write's
    own clause. Data and interpreter bodies cannot move the parent shell, so
    they leave that walk. A shell body is unreadable: it may belong to a child
    process, or reach the current shell through an indirection such as `eval`.
    That uncertainty ends the walk rather than guessing either destination.
    This is coarser than a real shell, and coarser on purpose:
    `guard-secrets-read` reasons about the whole command for the shell-write
    grammars and clause-by-clause only for the eval heuristics, and a write's
    position relative to a `cd` is evidence read nowhere else in it. What this may not
    be is finer than it can prove, which is why one unreadable change stops
    the walk rather than being skipped past.

    NEVER REALPATH HERE. `guard-secrets-read._placed_target` joins this
    answer onto a relative write target and hands the join straight to
    `rel_path`, which
    compares it against `root` WITHOUT resolving either side - on purpose, so
    a relative target stays comparable to a relative task-file entry. A
    working directory quietly resolved through a symlink (`/tmp` ->
    `/private/tmp` on macOS, which is where a test fixture and a real
    session scratchpad both commonly live) would then compare a resolved
    path against an unresolved `root` and manufacture a `../../..` mismatch
    for a file that never left the tree. `within_root` is the one place
    symlinks get resolved, on both sides at once, and it is asked separately -
    this only normalises the arithmetic of `..` and `.`."""
    if not payload_cwd:
        return None
    current = str(payload_cwd)
    text, _code, shell = split_heredocs(cmd)
    if shell:
        return None
    for clause in command_clauses(text):
        # `eval` runs its argument in THIS shell, so a directory change inside
        # it moves every write after it, and is read exactly as a bare one is.
        # A shell's `-c` runs in a child, which moves nothing here.
        handed = _handed_command(shell_words(clause.strip()) or [])
        if handed is not None and handed[0] == "eval":
            current = effective_cwd(handed[1], current)
            if current is None:
                return None
            continue
        m = _DIR_CHANGE_CLAUSE.match(clause)
        if not m:
            continue
        verb = m.group(1).lower()
        if verb == "popd":
            return None
        words = shell_words(m.group(2) or "")
        if words is None:
            return None
        args = [w for w in words if not w.startswith("-")]
        if len(args) != 1 or not resolvable_destination(args[0]):
            return None
        try:
            current = os.path.normpath(os.path.join(current, args[0]))
        except Exception:
            return None
    return current


# --- a Bash command's heredoc bodies: data, or text a machine will run --------
# WHY THIS IS HERE AND NOT IN A GUARD. Two guards in this directory have to
# answer the same question before they grade anything - `guard-secrets-read`
# (a commit message quoting `cat <key>` is prose, a `python3 - <<PY`
# body is a program) and `guard-history-rewrite` (which refused a command whose
# only act was to WRITE A FILE, because the file's content named a force push).
# A hook may not import another hook; `_config` is the only module all of them
# already load. So the answer lives once, here, and both guards call it. The
# alternative was a second copy in the second guard, which is how the two would
# drift into disagreeing about what a heredoc is.
#
# `.claude/hooks/require-claim-block.py` asks a narrower version of this question
# and keeps its OWN copy DELIBERATELY: it is this repository's configuration, the
# plugin is a product that ships without `.claude/` at all, and a config hook
# importing product internals inverts that dependency. Two homes on either side
# of a release boundary is a boundary; two homes inside this directory would just
# be a duplicate.
# `(?<!<)<<(?!<)`: a here-string (`sh <<<'EOF'`) is not a heredoc, and reading
# one as a heredoc dropped the lines after it - commands the shell runs - as a
# body nothing executes.
_HEREDOC_START = re.compile(
    r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# The head of a heredoc line, when what it invokes reads its PROGRAM from stdin.
# `python3 - <<PY`, `python3 <<PY`, `node <<JS`, `bash -s <<EOF` are all the same
# capability as `python -c`, spelled differently; `git commit -F - <<MSG` and
# `cat <<EOF` are not, because the body is data those commands never execute.
#
# `/dev/stdin` IS THAT DASH WRITTEN OUT, and leaving it off made the classification
# depend on which of two identical spellings the operator typed: `python3 - <<PY`
# was graded as a program and `python3 /dev/stdin <<PY` fell through to the data
# bucket, where it left the scanned text entirely and no rule saw it at all. A body
# the guards cannot place is the one they must keep, so the spelling is named here
# rather than left to be discovered by whoever types it.
_STDIN_INTERP = re.compile(
    r"\b(?:python3?|python3\.\d+|node|nodejs|deno|bun|ruby|perl|php|bash|sh|zsh)\b"
    r"(?:\s+-[A-Za-z-]+)*\s*(?:-|/dev/stdin)?\s*$",
    re.IGNORECASE,
)
# The SHELL subset of the line above, tested first because `_STDIN_INTERP` holds
# for both and the two answers are not interchangeable. A body fed to
# `bash -s` is shell text and the shell-grammar rules must read it; a body fed to
# `python3 -` is a program in another language, where a shell READ VERB is a word
# inside a string and the interpreter arms are what grade it.
#
# THE NAMED PROGRAMS STAY `\b`-BOUNDED ONLY, ON PURPOSE - matched anywhere a
# word boundary allows, including a REDIRECT TARGET's own extension
# (`cat > probe.sh`). That is gh35's pinned case: narrowing it to the head's
# command-verb position would also narrow `guard-secrets-read`, which shares
# this classification, and the conservative direction for a secret-reading
# guard is to over-match, never under-match. The bare `.` added below carries
# no such history - nothing before it relied on a trailing, unanchored dot -
# so IT ALONE requires start-of-head or a real separator (the same class
# `_last_command` already splits a head's simple commands on) immediately
# before it: `git add .` ends in an argument, not the dot-source builtin, and
# reads as one without this anchor, grading an unrelated heredoc body as live
# shell it was never going to be.
_STDIN_SHELL = re.compile(
    r"(?:\b(?:bash|sh|zsh|source)\b|(?:^|[;&|(\n])\s*\.)"
    r"(?:\s+-[A-Za-z-]+)*\s*(?:-|/dev/stdin)?\s*$",
    re.IGNORECASE)


# A heredoc HEAD that runs a script FILE - `python3 x.py --technical - <<'EOF'`
# - hands the body to that script as its stdin, and that is data: the shape
# the base always allowed and the one the field report needed. It is the ONLY
# interpreter invocation `_head_runs_body` reads as not running the body, and
# only with no option before the script: every other spelling (`-`,
# `/dev/stdin`, an option value, a subcommand) may read its program from stdin.
_DATA_SCRIPT_EXTS = (
    (re.compile(r"^python(?:3(?:\.\d+)?)?$"), (".py",)),
    (re.compile(r"^(?:node|nodejs)$"), (".js", ".mjs", ".cjs")),
)
# Programs that run their argument as a command, for reading a heredoc HEAD:
# `env python3 -`, `sudo bash`, `xargs sh -c ...`, `timeout 5 python3 -`.
_HEAD_WRAPPERS = ("env", "sudo", "doas", "xargs", "timeout", "nice", "ionice",
                  "nohup", "command", "builtin", "exec", "time", "stdbuf", "chrt",
                  "setsid")
_SHELL_PROGRAMS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "mksh", "ash",
                   "source", ".")
_ANY_INTERPRETER = re.compile(
    r"^(?:python(?:3(?:\.\d+)?)?|node|nodejs|deno|bun|ruby|perl|php|awk|gawk"
    r"|lua|tclsh|Rscript|osascript)$")
# A body the SHELL still expands: an unquoted delimiter leaves command
# substitution live, so the shell runs it before any consumer reads a byte.
_LIVE_SUBSTITUTION = re.compile(r"\$\(|`")
# Shell syntax in a heredoc head that can hand the body to something that runs
# it by a route no word of the head names: process substitution, command
# substitution.
_HEAD_INDIRECTION = re.compile(r"[<>]\(|\$\(|`")


def _program_of(word):
    """A word's program name: basename, quotes and `.exe` dropped."""
    name = str(word).strip("'\"").replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def _plain_script_run(words):
    """Is `words` exactly `<python|node> <script file> [args...]`?

    No leading assignment, no option before the script, a script operand that
    is a real file name with that interpreter's extension - never `-`, a
    `/dev/` or `/proc/` path - and no word carrying a quote, an expansion or a
    redirection. That is the only invocation `_DATA_SCRIPT_EXTS` vouches for."""
    if len(words) < 2:
        return False
    if any(ch in w for w in words for ch in "'\"$`()<>"):
        return False
    program, script = _program_of(words[0]), words[1]
    if script.startswith("-") or script.startswith(("/dev/", "/proc/")):
        return False
    for pattern, exts in _DATA_SCRIPT_EXTS:
        if pattern.match(program):
            return script.lower().endswith(exts)
    return False


def _last_command(text):
    """The words of the last simple command in `text` (after `;` `&` `|` `(`)."""
    return re.split(r"[;&|(\n]", text)[-1].split()


def is_interpreter(word):
    """Whether `word` names an interpreter that runs a program it is handed."""
    return bool(_ANY_INTERPRETER.match(_program_of(word)))


def is_shell(word):
    """Whether `word` names a shell program."""
    return _program_of(word) in _SHELL_PROGRAMS


def program_name(word):
    """The program a command word runs, as the readers here compare it:
    basename, quotes and `.exe` dropped."""
    return _program_of(word)


# Per interpreter family: the flags that hand it its program inline (or name
# a module to run), and the options that take a separate value, so the value
# is not read as the script. Unknown options do not name a program, and `--`
# makes the following word the script.
_OWN_PROGRAM = (
    (re.compile(r"^python(?:3(?:\.\d+)?)?$"), ("-c", "-m"), ("-W", "-X", "-Q"),
     ("-B", "-E", "-I", "-O", "-OO", "-q", "-s", "-S", "-u", "-v", "-x")),
    (re.compile(r"^(?:node|nodejs)$"), ("-e", "-p", "--eval", "--print"),
     ("-r", "--require", "--import", "--loader", "--experimental-loader"),
     ("--no-warnings", "--trace-warnings")),
    (re.compile(r"^ruby$"), ("-e",), ("-r", "-I", "-C", "-E"),
     ("-a", "-c", "-d", "-l", "-n", "-p", "-v", "-w")),
    (re.compile(r"^perl$"), ("-e", "-E"), ("-I", "-M", "-m"),
     ("-c", "-d", "-n", "-p", "-s", "-v", "-w")),
    (re.compile(r"^php$"), ("-r",), ("-c", "-d"), ("-n", "-v")),
)
_SCRIPT_EXTS = (".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".pm",
                ".php")


def runs_own_program(words):
    """Whether an interpreter's words already name the program it runs - a
    script file, or code handed to it by its own inline flag - so what arrives
    on its stdin is input. Decided per interpreter: `perl -c` compiles stdin
    and `python -E` is not a program flag, so neither counts."""
    program = _program_of(words[0]) if words else ""
    for pattern, inline, takes_value, no_value in _OWN_PROGRAM:
        if not pattern.match(program):
            continue
        skip = False
        for index, word in enumerate(words[1:], 1):
            if skip:
                skip = False
                continue
            if word == "--":
                if index + 1 >= len(words):
                    return False
                script = words[index + 1]
                return (not any(ch in script for ch in "'\"$`()<>*?[")
                        and script.lower().endswith(_SCRIPT_EXTS))
            if word == "-" or any(ch in word for ch in "'\"$`()<>*?["):
                return False
            if word in inline:
                return True
            if word in takes_value:
                skip = True
                continue
            if word in no_value:
                continue
            if word.startswith("-"):
                return False
            return word.lower().endswith(_SCRIPT_EXTS)
        return False
    return False


# A shell variable assignment, `NAME=value`, as one of a command's words.
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

_WRAPPER_VALUE_OPTIONS = {
    "sudo": ("-u", "-g", "-h", "-p", "-r", "-t", "-C", "--user", "--group",
             "--host", "--prompt", "--role", "--type", "--close-from", "-a"),
    "doas": ("-u", "-C", "--user", "--config", "-a"),
    "env": ("-C", "-u", "--chdir", "--unset"),
    "xargs": ("-E", "-I", "-i", "-L", "-n", "-P", "-s", "-S", "-a",
              "--max-args",
              "--max-procs", "--max-chars", "--arg-file"),
    "timeout": ("-k", "-s", "--kill-after", "--signal"),
    "time": ("-f",),
    "nice": ("-n", "--adjustment"),
    "ionice": ("-c", "-n", "--class", "--classdata"),
    "stdbuf": ("-i", "-o", "-e", "--input", "--output", "--error"),
    "chrt": ("-T", "-P", "-D", "--runtime", "--period", "--deadline"),
    "exec": ("-a",),
}


def _wrapper_rest(name, words):
    """The command past one known wrapper, or None when parsing is uncertain."""
    index, operand = 0, name in ("timeout", "chrt")
    value_options = _WRAPPER_VALUE_OPTIONS.get(name, ())
    while index < len(words):
        word = words[index]
        if word == "--":
            return words[index + 1:]
        if name in ("env", "sudo", "time") and _ASSIGNMENT.match(word):
            index += 1
            continue
        if name == "xargs" and word == "-i":
            return None
        if word in value_options:
            if index + 1 >= len(words):
                return None
            index += 2
            continue
        if any(word.startswith(option + "=") for option in value_options
               if option.startswith("--")):
            index += 1
            continue
        if word.startswith("-"):
            if word in ("-0", "-a", "-b", "-f", "-i", "-l", "-n", "-p", "-s",
                        "-v", "-w", "-x", "--preserve-status", "--foreground",
                        "--verbose", "--help", "--version"):
                index += 1
                continue
            return None
        if operand:
            operand = False
            index += 1
            continue
        return words[index:]
    return []


def _wrapper_fallback(words):
    """Conservative wrapper reading through options, assignments and wrappers."""
    words = list(words)
    while words:
        while words and (words[0].startswith("-") or words[0].isdigit()):
            words = words[1:]
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        if words and _program_of(words[0]) in _HEAD_WRAPPERS:
            words = words[1:]
            continue
        return words
    return []


def program_candidates(words):
    """(words past the prefix, the words that may be the program run).

    One command's words with leading assignments and wrappers that run their
    argument (`env`, `sudo`, `timeout 5`, ...) stepped over. An exact parse
    narrows the command position, while the conservative reading keeps every
    word that can remain after wrapper prefixes as a candidate."""
    words = list(words)
    fallback_candidates = []
    while words and _ASSIGNMENT.match(words[0]):
        words = words[1:]
    while words and _program_of(words[0]) in _HEAD_WRAPPERS:
        fallback = _wrapper_fallback(words[1:])
        rest = _wrapper_rest(_program_of(words[0]), words[1:])
        if rest is None:
            return (fallback, fallback)
        fallback_candidates.extend(fallback)
        words = rest
    candidates = words[:1] if words else []
    return (words, candidates + fallback_candidates)


def leading_assignments(words):
    """The `NAME=value` words one command's `words` set for its program: the
    ones ahead of it, bare (`A=1 git diff`) or through a wrapper that takes
    them (`env A=1 git diff`, `sudo A=1 ...`), in the order written.

    An assignment there is environment the program reads, and a program can
    run what it reads - git runs `GIT_EDITOR`, `GIT_EXTERNAL_DIFF` and a
    `core.editor` carried in `GIT_CONFIG_PARAMETERS` - so a reader deciding a
    quoted word is mere text asks this first. The words are those
    `program_candidates` steps over, so the two never disagree about where the
    program starts."""
    rest, _candidates = program_candidates(words)
    prefix = list(words)[:len(words) - len(rest)]
    return [w for w in prefix if _ASSIGNMENT.match(w)]


# A shell's options that take a separate value, so the value is not read as
# the script operand that ends the option list.
_SHELL_VALUE_OPTIONS = ("-o", "+o", "-O", "+O", "--rcfile", "--init-file")


def _handed_command(words):
    """("eval" | "shell", the command it runs) when one command's `words` hand
    a command to `eval` or to a shell's `-c`, else None.

    The program is found past assignments and wrappers by `program_candidates`,
    so `sudo bash -c` and `env A=1 sh -c` are read as `bash -c` is. A shell
    takes its command from the first operand after its options once `c` is in
    any short-option cluster (`-c`, `-lc`, `-ec`); an operand before that is a
    script run, whose own `-c` is the script's business. `eval` joins its
    arguments with a blank and runs the result, as the shell does."""
    rest, _candidates = program_candidates(words)
    if not rest:
        return None
    program = _program_of(rest[0])
    if program == "eval":
        args = rest[1:]
        if args and args[0] == "--":
            args = args[1:]
        return ("eval", " ".join(args)) if args else None
    if program not in _SHELL_PROGRAMS or program in ("source", "."):
        return None
    flagged, index = False, 1
    while index < len(rest):
        word = rest[index]
        if word == "--":
            index += 1
            break
        if word in _SHELL_VALUE_OPTIONS:
            index += 2
            continue
        if word.startswith("--"):
            index += 1
            continue
        if len(word) > 1 and word[0] in "-+":
            if word[0] == "-" and "c" in word[1:]:
                flagged = True
            index += 1
            continue
        break
    if not flagged or index >= len(rest):
        return None
    return ("shell", rest[index])


def handed_commands(text):
    """Every command `text` hands to `eval` or to a shell's `-c` as an
    ARGUMENT, one per clause that does, in command order.

    Such a command is text to every reader of the outer command - a quoted
    word - and a command to the shell that runs it, so a guard that grades
    what a command DOES reads it again as a command of its own. One level:
    a handed command that hands another is the caller's to read again, with
    whatever bound it keeps. A clause whose quoting never closes hands
    nothing this can read."""
    out = []
    for clause in command_clauses(join_continuations(text or "")):
        handed = _handed_command(shell_words(clause.strip()) or [])
        if handed is not None and handed[1].strip():
            out.append(handed[1])
    return out


def _head_runs_body(head):
    """"shell", "code" or None: what the heredoc HEAD itself does with the body.

    The two patterns below the marker regex answer the spellings they know; this
    answers by the program in command position of the head's last command, past
    any wrapper that runs its argument, so `env python3 -W ignore -`,
    `sudo -u x bash` and `bash <(cat)` are graded rather than dropped. A shell
    is shell whatever its operands - a script reading its stdin is one `read`
    and `eval` from running it. An interpreter is code unless it is a plain
    script run. Process or command substitution anywhere in the head is shell.
    None means no word of the head is a program that could run the body."""
    if _HEAD_INDIRECTION.search(head):
        return "shell"
    words, candidates = program_candidates(_last_command(head))
    for word in candidates:
        program = _program_of(word)
        if program in _SHELL_PROGRAMS:
            return "shell"
        if _ANY_INTERPRETER.match(program):
            at = words.index(word) if word in words else None
            return (None if at is not None and _plain_script_run(words[at:])
                    else "code")
    return None


def join_continuations(text):
    """`text` with every backslash-newline outside single quotes removed - what
    the shell does before it reads a word.

    A line continuation is not a separator: `git`, a backslash ending the
    line, then `stash` on the next is ONE command, and a reader that kept the
    escaped newline as a boundary read two. Inside double quotes the pair is
    removed too (POSIX); inside single quotes it is literal. Any other
    backslash is kept with the character it escapes.

    A COMMENT RUNS TO THE END OF ITS LINE and is copied through untouched: an
    unquoted `#` that starts a word opens it, and a backslash at its end does
    NOT continue the line - bash runs the next line as a command of its own, so
    joining it would make that command an argument of the one before.

    WHETHER `#` STARTS A WORD is read from the word being assembled, not from
    the raw character before it: a removed continuation leaves the word it
    interrupted open (`x`, backslash-newline, `#y` is the one word `x#y`), and
    an escaped blank belongs to its word. `at_start` carries that fact."""
    out, quote, i, n = [], None, 0, len(text or "")
    text = text or ""
    at_start = True
    while i < n:
        ch = text[i]
        if quote is None and ch == "#" and at_start:
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(text[i:end])
            i = end
            continue
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if text[i + 1] == "\n":
                i += 2
                continue
            out.append(text[i:i + 2])
            at_start = False
            i += 2
            continue
        if ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "'" and quote is None:
            quote = "'"
        at_start = quote is None and ch in " \t\n;&|()<>"
        out.append(ch)
        i += 1
    return "".join(out)


def split_heredocs(cmd):
    """(text without heredoc bodies, bodies that are CODE, bodies that are SHELL).

    Found while committing a fix to `guard-secrets-read`: the guard refused
    its own commit, because the message DESCRIBED the write forms it had just
    learned and every branch there scans the whole command text. Probing that
    turned up the mirror defect -- `python3 - <<'PY'` performs exactly what
    `python3 -c` does and walked straight through, because the pattern knew the
    `-c` SPELLING rather than the capability. One root, two directions.

    So the body is separated from the text and handed back only when something
    RUNS it. Prose on its way into a file stops being read as code; a heredoc fed
    to python or node starts being read as the code it is.

    THIS SPLIT THAT ONE BUCKET IN TWO, because "is this code" was never the whole
    question: the LANGUAGE the body is code IN decides which rules may read it. A
    body fed to `bash -s` is shell text; a body fed to `python3 -` is a program in
    a language where a shell read verb is an ordinary word. Both used to arrive in
    one list, so the shell-grammar rules read Python source and refused a write
    whose payload was an English sentence quoting a command.

    A THIRD CLASSIFICATION, and it is the one that keeps this a narrowing. A body
    the consumer does not execute is DATA and leaves -- unless the head line pipes
    it onward, in which case what the far side does with it is not read here and
    it is kept as shell. (A data reading of the far side was tried and removed:
    each allow-list of it missed a spelling that runs the body.) The head is read
    by program too (`_head_runs_body`), so a wrapper or an option in front of an
    interpreter does not turn its program into data.
    `cat <<EOF | bash` really is a way to run a command; `cat <<'EOF' | python3
    x.py -` is an outcome handed to a script, and refusing its prose for naming
    a rule was the guard firing on a sentence.

    AN UNQUOTED DELIMITER KEEPS THE SHELL IN THE BODY. With `<<EOF` rather than
    `<<'EOF'` the shell performs command substitution inside the body before
    any consumer reads it, so `$(...)` or a backquote there is a command that
    runs whatever the body's destination - a file, a script's stdin. Such a
    body is kept as shell rather than dropped as data; quoting the delimiter is
    what makes the same bytes inert text.

    Fail-safe about its own limits: a heredoc whose terminator never arrives is
    left in the text, so an unparseable command is judged exactly as strictly as
    before this existed. The pipe is read on the heredoc's own line only; a
    heredoc line that ends in a backslash continues somewhere this does not
    read, so its body is kept as shell.
    """
    if "<<" not in (cmd or ""):
        return (cmd or ""), [], []
    lines = (cmd or "").split("\n")
    kept, code, shell, i = [], [], [], 0
    while i < len(lines):
        line = lines[i]
        m = _HEREDOC_START.search(line)
        if not m:
            kept.append(line)
            i += 1
            continue
        delim = m.group(2)
        # Look for the terminator before consuming anything: without one there is
        # no body to separate, only a line that happens to contain `<<`.
        end = None
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == delim:
                end = j
                break
        if end is None:
            kept.append(line)
            i += 1
            continue
        head = line[:m.start()].strip()
        tail = line[m.end():]
        # THE REST OF THE HEAD LINE IS COMMAND TEXT, and it was dropped with
        # the body: `cat <<'EOF' && git stash` kept only `cat`, so whatever
        # followed the marker on its own line was invisible to every rule.
        kept.append(line[:m.start()] + " " + tail)
        body = "\n".join(lines[i + 1:end])
        live = not m.group(1) and _LIVE_SUBSTITUTION.search(body)
        runs = _head_runs_body(head)
        if _STDIN_SHELL.search(head) or runs == "shell":
            shell.append(body)
        elif _STDIN_INTERP.search(head) or runs == "code":
            code.append(body)
        elif tail.rstrip().endswith("\\"):
            shell.append(body)     # the line continues; its far side is unread
        elif "|" in tail:
            shell.append(body)     # piped onward: what the far side runs is unread
        elif live:
            shell.append(body)
        i = end + 1
    return "\n".join(kept), code, shell


def runnable_text(cmd):
    """The command with only the spans nothing executes removed.

    Everything a machine will run in SOME language: the text, shell bodies and
    interpreter bodies. For a rule that is about a CAPABILITY rather than about
    shell grammar -- writing a file, reaching the environment, rewriting history
    -- where the interpreter body is still evidence and dropping it would open a
    hole. Only the data body leaves.

    This is the view a guard wants when it asks "what does this command DO": the
    body of `cat > probe.py <<'PY'` is on its way into a file and the guard that
    read it as a command refused a write, while `python3 - <<'PY'` and
    `cat <<'EOF' | bash` keep every byte they are graded on.
    """
    text, code, shell = split_heredocs(cmd)
    return "\n".join([text] + shell + code)


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


# --- MCP tool calls: the payload, never the server it was installed under ------
# An MCP tool is `mcp__<server>__<operation>`, and the server segment is a name the
# OPERATOR typed into their own config: one npm filesystem server is
# `mcp__filesystem__write_file` in one setup and `mcp__fs__write_file` in the next.
# So no verdict in this plugin is taken from it - and none is taken from an argument
# KEY either, which is the same problem one level down (`path`, `paths`, `file_path`,
# `uri`, `content`, `edits`). Both halves are the rule guard-secrets-read states in
# its own header; this is where the walk that keeps them lives.
#
# THREE HOOKS ASK IT NOW - guard-secrets-read on the read side, require-plan and
# guard-edits on the write side - and a hook may not import another hook. So the
# classification has one home here, for the reason `split_heredocs` does.


def mcp_operation(tool):
    """The last `__`-separated segment of an MCP tool name, or "".

    FOR THE REFUSAL SENTENCE ALONE: it names the call back to the person who made
    it. No verdict is taken from its spelling, which is the point - a list of write
    verbs here would only ever be as complete as the servers whose spellings
    somebody happened to think of.
    """
    parts = [p for p in str(tool or "").split("__") if p]
    return parts[-1] if len(parts) > 1 else ""


# The two shapes `writeBasis` reports. Both are SUFFICIENT evidence of a write and
# neither is necessary evidence - see `mcp_payload`.
MCP_BASIS_BODY = "the payload carries body text (a string with a newline in it)"
MCP_BASIS_RECORD = "the payload carries a record (an object inside a list)"


def mcp_payload(node, limit=2000):
    """{"locators", "writeBasis", "body"} - one walk of a tool payload, three answers.

    `locators` is every path-shaped VALUE the payload names, at any depth, in
    payload order and deduplicated. Two narrowings, both structural rather than a
    list of names: a `file:` URI is reduced to the path inside it, so a locator
    reaches a path rule spelled the way that rule matches; and a string carrying a
    NEWLINE is a body, not a filename, which is what keeps the content of a write
    from being graded as a path without this function knowing that a key called
    `content` exists.

    `writeBasis` is the thing in this payload that a READ could not have asked for,
    or None. Two shapes qualify: BODY TEXT (a string with a newline in it - a file
    the call is carrying) and a RECORD (an object inside a list - `edits`, `files`,
    `changes`; a read's parameters select a view, and a view is selected with
    scalars and lists of scalars). Read off the RAW string, before the strip
    `locators` does, so a one-line body ending in a newline still counts.

    THE TEST IS SUFFICIENT, NEVER NECESSARY, AND THAT DIRECTION IS THE DESIGN. A
    PreToolUse payload cannot be made to say whether a call reads or writes -
    guard-secrets-read refuses to guess for exactly that reason, and refuses a
    secret file whatever the operation, because on its side a wrong guess costs the
    file. On this side a wrong guess costs ordinary traffic: a read graded as a
    write is a refused read, and a guard that refuses reads is a guard the operator
    turns off. So the failure direction is chosen to be UNDER-coverage. A write
    whose whole payload is short single-line scalars - a rename, a delete, a
    one-line `edit_file` - produces no basis and reaches the same nothing it
    reached before this existed. What it cannot do is fire on a read, because a
    read payload has nowhere to put a body or a record.

    THE RESIDUAL, stated rather than left to be met: a server whose READ took an
    object inside a list would be graded a write, and would then get the plan
    gate's verdict for whatever repo path it also named. That is friction on one
    call, not a leak, and it is the direction this function is allowed to be wrong
    in.

    `body` is the LONGEST string the payload carries - what the plan gate measures a
    change magnitude from, the same quantity it takes off an Edit's `new_string`.
    The longest string rather than a named field, because a field name is the server
    author's vocabulary again.
    """
    locators = []
    basis = None
    body = ""
    queue = [node]
    i = 0
    while i < len(queue) and i < limit:
        item = queue[i]
        i += 1
        if isinstance(item, dict):
            queue.extend([item[key] for key in item])
        elif isinstance(item, (list, tuple)):
            if basis is None and any(isinstance(el, dict) for el in item):
                basis = MCP_BASIS_RECORD
            queue.extend(list(item))
        elif isinstance(item, str):
            if len(item) > len(body):
                body = item
            if basis is None and "\n" in item:
                basis = MCP_BASIS_BODY
            text = item.strip()
            if not text or "\n" in text:
                continue
            low = text.lower()
            if low.startswith("file://"):
                text = text[len("file://"):]
            elif low.startswith("file:"):
                text = text[len("file:"):]
            text = slashed(text)
            if text and text not in locators:
                locators.append(text)
    return {"locators": locators, "writeBasis": basis, "body": body}


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
# Shared across hooks/ - which ones, without a list here to rot:
#   grep -rn '_config.rel_path\|_config.within_root' plugins/audit/hooks
#
# Marks that stop a word in a command line being read as a path. Every one of
# them is something the SHELL resolves and a hook payload does not carry:
# parameter and command substitution, a glob, a home reference, brace expansion.
# A word wearing one names a place only the shell knows, so any answer this
# process gives about WHERE it lands is an answer about the spelling instead.
#
# `~` IS NOT IN THIS TUPLE, on purpose, even though `resolvable_destination`
# still refuses to guess through one. Every other mark here expands wherever
# it sits in the word - `out*.log`, `a${X}b` - so "anywhere" is the right
# question for them. A tilde does not: POSIX home-shorthand expands only when
# `~` opens the word, and a tilde anywhere else is an ordinary character with
# no shell meaning at all. Windows' own 8.3 short names route through exactly
# that anywhere-else case - `C:\Users\RUNNER~1\...\P1.json` carries one in its
# THIRD component - and a blanket "any position" check read a real absolute
# path as shell-shorthand nobody could resolve, so `_manifest_write_hit`
# withdrew from a shard write that was never ambiguous and let it pass
# unblocked. `resolvable_destination` still checks the leading case below;
# this tuple only stopped answering a question a shell never asks either.
UNRESOLVED_MARKS = ("$", "`", "*", "?", "{", "}")


def resolvable_destination(text):
    """Can this process establish where `text` points? Default: NO.

    ONE ANSWER FOR TWO GUARDS. `guard-bash-writes` asks it of a `cd` target
    before deciding which working tree a command ran in; `guard-secrets-read`
    asks it of a write target before deciding whether the plan covers the file.
    Both used to resolve the word against the repository root as though it were
    a literal path, which places `$HOME/notes.py` inside the tree and then
    reports a finding about a file of that name - a claim whose whole content
    came from the resolution that produced it. Two copies of the question would
    be two opinions about `${OUT}` waiting to disagree.

    The caller decides what to DO with an unestablished destination, and the two
    differ: one withdraws an authorship claim, the other declines to grade a
    coverage question it cannot ask. What neither may do is guess.

    An empty word is unresolvable for the same reason a marked one is: there is
    nothing to place.

    A LEADING `~` IS THE ONLY POSITION THAT MEANS ANYTHING TO A SHELL - home
    shorthand expands at the front of a word and nowhere else, so only that
    position is checked here; `UNRESOLVED_MARKS` carries the marks that expand
    at any position instead. Checked separately rather than added to the tuple
    with a leading-anchor of its own, because every other caller of that tuple
    (the destination text ALONE) would have to grow the same anchor to agree.
    """
    word = str(text or "")
    if not word or word.startswith("~"):
        return False
    return not any(mark in word for mark in UNRESOLVED_MARKS)


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


def within_root(root, file_path):
    """True when `file_path` lands INSIDE `root` - the question rel_path cannot answer.

    `rel_path` is os.path.relpath, and for a path outside the tree it hands back
    `../../../private/tmp/probe.py`: an ordinary-looking string nothing
    downstream rejects. So the plan gate read a helper script written to the
    system temp directory as repo source and refused it for plan coverage no
    plan could ever have given it. Out of scope is not the same as unplanned,
    and only a caller that asks can tell the two apart - which is why this is a
    separate question rather than a new return value on rel_path, whose other
    callers compare the result against repo-relative literals and are already
    correctly negative for anything outside.

    NEVER relpath, deliberately. Across Windows drives it RAISES ValueError -
    the bug tools/check-rendered-artifacts.py was fixed for - and a containment
    test that raises fails its caller instead of answering it. A prefix
    comparison over resolved absolute paths has no such edge: two drives simply
    do not share one.

    Symlinks are resolved on BOTH sides, because a repo is routinely reached
    through one (/tmp -> /private/tmp on macOS, a checkout symlinked into
    place), and the two spellings name one tree. Case is compared both ways and
    either match counts as inside: on a case-insensitive volume `SRC/app.ts`
    really is inside `src/`. NOT handled, and the omission is chosen: sibling
    directories differing only in case on a case-SENSITIVE volume, where that
    second comparison calls an outside path inside. The tie goes to inside
    everywhere - inside is what every caller assumed before this function
    existed, so a wrong guess can only leave a gate where it already was, and
    unresolvable input answers True for the same reason.
    """
    def contains(parent, child):
        return (child == parent
                or child.startswith(parent.rstrip(os.sep) + os.sep))

    try:
        r = os.path.realpath(str(root))
        p = Path(str(file_path).replace("\\", "/"))
        if not p.is_absolute():
            p = Path(r) / p
        f = os.path.realpath(str(p))
    except Exception:
        return True
    return contains(r, f) or contains(r.lower(), f.lower())


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
    """`a/b.tsx:291-294,308` -> `a/b.tsx` - only a TRAILING `:<digit range>`,
    so a drive letter (`C:/repo/a.py`) or a colon inside a name survives. The
    scripts' copy (`_manifest_vocab._strip_line_suffix`) is pinned equal to this
    one by `test__manifest_vocab.py` `mv6b`."""
    return re.sub(r":[0-9][0-9,-]*\Z", "", str(entry).replace("\\", "/"))


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
    does not exist. Costs 0.136 ms per call, measured, because importlib by
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


def covering_key(file_map, rel):
    """The key of a rel-file -> [...] map that covers `rel`, or None.

    The three forms a manifest `files` list is written in: the path itself,
    the path as a directory, or a directory entry `rel` sits under. It lives
    here rather than beside the one decision that asks it because the REFUSAL
    TEXT asks it too, over a different map — and a message that named a
    declaring task the gate would not in fact have been opened by is the same
    false claim in a new place. One matcher, so the two cannot disagree."""
    if rel in file_map:
        return rel
    if (rel + "/") in file_map:
        return rel + "/"
    for f in file_map:
        if f.endswith("/") and rel.startswith(f):
            return f
    return None


def in_progress_outputs(root, manifest_rel):
    """`[(pattern, taskId), ...]` — the output patterns of `in_progress` tasks
    that the plan gate may honour, in document order. Empty list on any error.

    THE SECOND HALF OF COVERAGE, AND THE ONE THAT NEEDED A BOUND. `files` names
    what a task edits and is enumerated; `outputs` names what a run PRODUCES —
    the documents, the evidence rows — which cannot be enumerated before the run
    makes them, so it is patterns. Uncovered documentation writes were the
    commonest warning this gate produced and the plan had nowhere to put the
    thing it was warning about; a gate whose warnings are noise is a gate that is
    off, and the repair is a place in the plan rather than a hole in the gate.

    EVERY PATTERN IS GRADED BEFORE IT IS HONOURED, by the rule the writer and the
    validator use — `_task_outputs.honoured`, loaded by path because a hook may
    not import `scripts/`. A pattern the rule refuses is dropped here, so a plan
    that somehow carries one covers nothing extra.

    IT IS THAT MODULE AND NOT `_manifest_vocab`, which is a cost decision rather
    than a filing one. This runs on the per-tool-call path, so the SMALLER the
    module resolved by path here the better — the same argument that puts
    `_locks` and `_journal_io` at the floor layer — and the vocabulary module
    carries a premise that nothing on this path loads it.

    AND WHEN THE RULE CANNOT BE LOADED, NOTHING IS HONOURED. That is the only
    safe direction: an unreadable rule makes this gate louder (writes go on being
    reported as uncovered), never wider. Every other fail-open in this file
    switches a FEATURE off; switching this one off the other way would switch the
    GATE off, which is the door this whole key had to be built not to open.
    """
    rule = _load_scripts_module("_task_outputs", "_task_outputs.py")
    if rule is None:
        return []
    out = []
    manifest = _load_manifest_assembled(Path(root) / manifest_rel)
    if not isinstance(manifest, dict):
        return out
    try:
        for phase in manifest.get("phases", []) or []:
            for task in phase.get("tasks", []) or []:
                if task.get("status") != "in_progress":
                    continue
                tid = task.get("id")
                for pattern in rule.honoured(task.get("outputs")):
                    out.append((pattern, tid))
    except Exception:
        return []
    return out


def covering_output(outputs, rel):
    """`(pattern, taskId)` for the first honoured output pattern covering `rel`,
    or None.

    The matcher is `_task_outputs.output_covers`, for the reason
    `in_progress_outputs` gives: the half that says which patterns are legal and
    the half that says what they reach have to be one module, or a pattern ends
    up refused by the writer and matched by the reader.

    TAKES THE GRADED LIST rather than the manifest, which is what keeps the
    decision honest: the only way to reach this function is to have gone through
    `in_progress_outputs`, so there is no path on which an ungraded pattern can
    cover anything. `covering_key` is shaped the same way and for the same
    reason.
    """
    rule = _load_scripts_module("_task_outputs", "_task_outputs.py")
    if rule is None:
        return None
    try:
        for pattern, tid in (outputs or []):
            if rule.output_covers(pattern, rel):
                return (pattern, tid)
    except Exception:
        return None
    return None


def declaring_tasks(root, manifest_rel, rel):
    """[{"taskId", "status"}] for every task declaring `rel` WHATEVER its status
    — its own `files` or a `fileIndex` row keyed to it. Empty list when none
    does, and on any error.

    FOR A MESSAGE, NEVER FOR A VERDICT. `in_progress_task_map` above drops
    every task that is not `in_progress`, and that filter is the gate: an
    unstarted task is a plan, not permission, so reading this map in the
    decision would hand an agent the files of every task nobody has started.
    The decision therefore still reads that map alone and this one answers the
    question it threw the evidence away to answer — WHICH of the two causes a
    refusal found: no task declares this file, or one does and is not started.

    Never raises. An error here costs the refusal its second sentence, not its
    verdict."""
    out = []
    manifest = _load_manifest_assembled(Path(root) / manifest_rel)
    if not isinstance(manifest, dict):
        return out

    statuses = {}   # task id -> status, for every task in the plan
    fmap = {}       # rel file -> [task id], in declaration order
    try:
        for phase in manifest.get("phases", []) or []:
            for task in phase.get("tasks", []) or []:
                tid = task.get("id")
                if not tid:
                    continue
                statuses[tid] = task.get("status")
                for f in task.get("files", []) or []:
                    fmap.setdefault(strip_line_suffix(f), []).append(tid)
    except Exception:
        pass

    # The index arm is what makes this worth having: a file can reach a task
    # through `fileIndex` alone, and the id has to be a task the plan actually
    # holds or the status beside it would be invented.
    try:
        for fpath, task_ids in (manifest.get("fileIndex", {}) or {}).items():
            for tid in task_ids or []:
                if tid in statuses:
                    key = strip_line_suffix(fpath)
                    if tid not in fmap.get(key, []):
                        fmap.setdefault(key, []).append(tid)
    except Exception:
        pass

    key = covering_key(fmap, rel)
    if key is None:
        return out
    for tid in fmap.get(key, []):
        out.append({"taskId": tid, "status": statuses.get(tid)})
    return out


def manifest_state(root, manifest_rel):
    """How much the plan gate actually knows:
    {"exists": bool, "phaseRunning": bool, "runningPhase": "<id>"|None,
     "staleClosedPhase": "<id>"|None, "signoffDuePhase": "<id>"|None,
     "signoffDueStatus": "<stored status>"|None}.

    `runningPhase` names the phase behind `phaseRunning` (the phase itself when
    it is in_progress, the OWNER phase when only a task is), so a denial can say
    "phase P3 is in_progress" instead of an anonymous claim.

    The gate's verdict is graded on this, so the two questions have to be answered
    separately. "No manifest" and "a manifest with nothing running" look identical to
    `in_progress_files` — both yield an empty set — yet they mean very different
    things: the first is a repo that never opted in, the second is a repo mid-plan.

    `phaseRunning` reads the ASSEMBLED manifest, which is load-bearing. Under the
    sharded layout the index carries STUBS, and while a stub mirrors the phase's
    own status (`_manifest_io._STUB_KEYS`) it is a copy refreshed when that value
    moves rather than the source of truth, and it says nothing at all about the
    tasks inside the phase -- which the paragraph below makes load-bearing here.
    A raw index read would therefore answer from a mirror that may lag and would
    miss a running task outright.

    A task `in_progress` under a phase that is not counts too. The runtime writes
    `phase.status` on entry, but a manifest hand-edited to start one task is still a
    repo executing its plan, and refusing to notice would deny the gate exactly when
    it is most warranted.

    A PHASE ONLY AWAITING SIGN-OFF IS NOT RUNNING either: `phaseRunning` is
    `_manifest_io.phase_running`, the one answer, and a phase whose every task is
    terminal has nothing left to edit - it held this repository's own gate in its
    denying tier across releases while every task was done. It is named in
    `signoffDuePhase`, so a caller can say why the tier is not deny.

    A MERGED phase is never counted as running, whatever `status` still says.
    `close-phase.py` stamps `mergedAt` the moment `git merge` verifies the branch
    landed, and stores `status` only where the derivation now answers `done` - a
    plan it stamped before it did that, or one stamped by hand, keeps whatever
    `status` it had. A phase that
    reaches here with `mergedAt` set and no sign-off recorded (its DERIVED status,
    which reads a recorded verdict as done once the merge lands, is not terminal)
    was merged by hand or signed off on a copy that did not survive; either way
    its branch is gone, so it holds the gate open on nothing. `staleClosedPhase`
    names the first one found, so a caller can say why the tier looks emptier
    than the raw `status` column would suggest, rather than leaving a reader to
    notice the contradiction alone.

    Never raises. On any error it reports the LEAST aggressive state, so a crash in
    here can only relax the gate, never invent a denial."""
    state = {"exists": False, "phaseRunning": False, "runningPhase": None,
             "staleClosedPhase": None, "signoffDuePhase": None,
             "signoffDueStatus": None}
    try:
        path = Path(root) / manifest_rel
        if not path.exists():
            return state
        state["exists"] = True
        manifest = _load_manifest_assembled(path)
        mio = _load_scripts_module("_manifest_io", "_manifest_io.py")
        if not isinstance(manifest, dict) or mio is None:
            return state
        for phase in manifest.get("phases", []) or []:
            if not isinstance(phase, dict):
                continue
            if phase.get("mergedAt"):
                if (state["staleClosedPhase"] is None
                        and mio.effective_phase_status(phase) not in mio.TERMINAL):
                    state["staleClosedPhase"] = phase.get("id")
                continue
            if mio.phase_running(phase):
                state["phaseRunning"] = True
                state["runningPhase"] = phase.get("id")
                return state
            # The one a reader sees IN PROGRESS is the one that needs explaining,
            # so a stored in_progress phase is named over an earlier pending one,
            # and the stored status travels with the id: a caller that assumed
            # in_progress once called a pending phase in progress.
            if mio.signoff_due(phase) and (
                    state["signoffDuePhase"] is None
                    or (state["signoffDueStatus"] != "in_progress"
                        and phase.get("status") == "in_progress")):
                state["signoffDuePhase"] = phase.get("id")
                state["signoffDueStatus"] = phase.get("status")
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
    legacy spelling of `planGate: "deny"`.

    WHAT ELSE READS THIS, because the reach is the promise and it used to be
    understated in every place it was written down. `require-plan.py` grades the
    Edit/Write path here; `guard-secrets-read.py` grades its shell-write branch
    here, so `sed -i src/x.ts` and `Edit src/x.ts` cannot disagree; and
    `guard-bash-writes.py` grades its plan-coverage class here — it did not,
    and an advisory that cried wolf in a repo which never opted in was how a
    stranger met this plugin. Only the plan-coverage claim is graded. A guard whose
    claim binds to evidence of its own — a secret path, a held lock, a journal file
    — needs no tier to be right and reports at all of them.

    THE TIER IS HALF OF THE VERDICT; THE FREE-FILE SLOT IS THE OTHER HALF.
    `trivialLineThreshold` allows a session's first uncovered code file before
    any tier is asked, and that slot is `trivial_slot` — one reader, one
    writer, asked by `require-plan.py` for an edit and by
    `guard-secrets-read.py` for a shell write — so a file spent through either
    tool is spent for both, and a change's size is `text_magnitude` through
    either: an edit's new text, or the text a shell command carries. So the
    same change gets one verdict - WITH ONE EXCEPTION, decided rather than
    open: a shell write whose command does not state its content (it
    computes or fetches it) cannot be measured before it runs, and takes the
    slot exactly as an Edit within the threshold would (decided 2026-10-06).
    It is measured afterwards, by the PostToolUse arm: `guard-bash-writes.py`
    reads the slot, sizes the diff the write left with `change_magnitude`,
    and reports a slot file over `trivialLineThreshold` with its magnitude and
    the threshold. That is a report and not a refusal - the write has
    already landed - so at the deny tier an oversized unstated shell write
    still lands where an Edit of the same size would have been refused."""
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


# --- executor gate policy ------------------------------------------------------
# Before this key existed the executor ran a task's whole gate itself and the
# orchestrator ran the SAME gate again with `--record`, because only the recorded
# run is evidence — two full-suite runs per task, always, with no lever anywhere
# in this tree to say otherwise. An operator who suppressed the executor's own
# run in every spawn prompt measured that as the largest single saving of a whole
# wave and wrote the suppression into a handoff note — which the next session,
# not having read that file, paid for twice over. `_config_rules.py` mirrors this
# tuple as its own RUNS_GATE_MODES (the FINDING enum the panel's Settings select
# reads); the two are pinned together by that validator's own selftest, the same
# shape PLAN_GATE_TIERS/PLAN_GATE_MODES already use one section up.
RUNS_GATE_MODES = ("never", "own-tests", "full")

# `review.perTask`'s words. `_config_rules.py` mirrors this tuple as its own
# REVIEW_PER_TASK_MODES and pins the two together, RUNS_GATE_MODES's shape.
REVIEW_PER_TASK_MODES = ("always", "phase", "signals")


def executor_gate_policy(cfg):
    """`executor.runsGate`: one of RUNS_GATE_MODES, the default when the key is
    ABSENT, or None when it is SET to something outside the vocabulary.

    Absent is not the same finding as invalid, on purpose — most repositories
    write nothing here and should get the cheap reading without having to ask
    for it, while a value outside RUNS_GATE_MODES is a typo nobody meant, and
    folding it into the default would make a mistake look like a decision.
    `validate_config` (scripts/config/_config_rules.py) reports that typo as a
    FINDING at the file level; this is what a caller sees for it at the value
    level, and neither one silently guesses which reading the operator meant.

    Resolved by the ORCHESTRATOR at spawn time — the same moment it resolves
    which skills to hand the executor — and folded into the spawn prompt as an
    explicit word, never left for the subagent to look up on its own. No hook
    reads this key; it lives in DEFAULTS for the reason `ui`, `priority` and
    `portability` do — this dict is the one place the whole config's shape is
    stated, whether or not a hook consults a given key."""
    try:
        block = (cfg or {}).get("executor")
        if not isinstance(block, dict) or "runsGate" not in block:
            return DEFAULTS["executor"]["runsGate"]
        reading = block["runsGate"]
    except Exception:
        return DEFAULTS["executor"]["runsGate"]
    return reading if reading in RUNS_GATE_MODES else None


def executor_context_bound_hours(cfg):
    """`executor.maxHours`: how many hours a single spawned executor may be
    CONTINUED onto further tasks (never re-spawned) before the orchestrator
    stops preferring that, the DOCUMENTED DEFAULT when the key is ABSENT, or
    None when it is set to something outside its vocabulary — a positive
    number, and nothing else.

    Absent-vs-invalid is the same distinction `executor_gate_policy` draws
    for its own key, for the same reason: most projects write nothing here
    and should get a sane bound without asking for one, while zero, a
    negative number or a non-numeric value is a mistake nobody meant, and
    folding it into the default would make the mistake read as a decision.
    `validate_config` (`scripts/config/_config_rules.py`) reports that
    mistake as a FINDING at the file level; this is what a caller sees for
    it at the value level.

    Resolved by the ORCHESTRATOR — not by any hook — at the moment
    `reference/execute-task.md`'s continuation rule asks whether a running
    agent should be handed its next task or handed back instead; the
    resolved number is not itself enforced by anything mechanical, the same
    way `executor.runsGate`'s resolution is a fact folded into a prompt
    rather than a value any code path checks. The default this returns
    (`DEFAULTS["executor"]["maxHours"]`) is the same figure
    `reference/execute-task.md` states for the reader who never sets the
    key — `tests/test__config.py` reads both and fails if they part ways."""
    try:
        block = (cfg or {}).get("executor")
        if not isinstance(block, dict) or "maxHours" not in block:
            return DEFAULTS["executor"]["maxHours"]
        reading = block["maxHours"]
    except Exception:
        return DEFAULTS["executor"]["maxHours"]
    if isinstance(reading, bool) or not isinstance(reading, (int, float)):
        return None
    return reading if reading > 0 else None


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
# The keys stored AS GIVEN, and `file` means A PATH — the thing a gate's verdict
# was about, spelled the way the consuming repo spells it. `command` is
# deliberately NOT in this tuple and must stay out of it: the only route a
# command has into a row is `_command_facts` below, which converts it. That is
# what makes "no raw command text is written here" a property of the writer
# rather than a habit every caller has to remember.
_GATE_EVENT_KEYS = ("event", "file", "mode", "reason", "sessionId")


def _command_facts(event):
    """`event["command"]` as the JOURNAL spells a command it may not store — a
    digest, a UTF-8 byte length and a program name. `{}` when there is no
    command, and `{}` when the module owning that spelling cannot be loaded.

    THE WRITER IS THE ONLY PLACE THIS CAN BE FIXED, which is why the conversion
    is here and not at each call site. `guard-secrets-read` put the raw
    `tool_input.command` into `file`, and a command naming a key file under a
    home directory is not an ABSOLUTE path — so every reader's redactor resolved
    it against the repo root, found it inside, and passed it through verbatim.
    Each reader was correct and the leak survived all of them; a reader cannot
    undo a field, it can only decline to paint one.

    NOT A SECOND REDACTION RULE. `_journal_io.command_facts` is the one this
    repo already has — 1.3.0 took this exact route for the journal's
    `bash.unsandboxed` row, for this exact reason (CWE-532) — reached through
    the door `journal_dir` already uses. The module is loaded ONLY when a
    command is present, so an ordinary observe/warn row naming a file pays
    nothing for it.

    DROPPING THE FACTS IS THE FAIL DIRECTION, not falling back to the text. This
    is a redactor, and `_journal_io`'s own note says why the two directions
    differ: a gate that cannot resolve something must leave the gate where it
    was, while a writer that cannot must not write. A row that says less costs a
    reader a detail; a row that guesses costs them a published home directory.
    """
    cmd = (event or {}).get("command") if isinstance(event, dict) else None
    if cmd is None or not str(cmd):
        return {}
    mod = _load_journal_lib()
    if mod is None:
        return {}
    try:
        return mod.command_facts(str(cmd))
    except Exception:
        return {}


def redact_paths(root, text, values):
    """`text` with each of `values` respelled by the journal's ONE path redactor,
    or None when that cannot be done and `text` really does contain one.

    THE FIELD BESIDE `file` HAD THE OPPOSITE TREATMENT. `file` is put
    through `_journal_io.repo_relative_or_token` by every reader that paints it;
    `reason` — the same row, one cell over — was painted verbatim, and
    `guard-secrets-read` interpolates the payload's path into the message whose
    FIRST LINE becomes that cell. So a denial over a dotenv file under a home
    directory published the absolute path in one cell while the cell next to it
    correctly read the token.

    ONE STRING, NOT TWO. The alternative repairs were to strip the path from the
    terminal message (which is the one place a human wants it: it is their own
    machine and their own tool call) or to author a separate recorded sentence,
    which is "one fact, two homes" — the defect class this whole round is about.
    Neither is taken here: the recorded reason is still the message's first line,
    derived from it every time, with the exact substrings the caller says it
    interpolated respelled. There is nothing to compare because nothing was
    split.

    NOT A SECOND REDACTION RULE, and not a pattern either. `_panel_write.
    _redacted_feed_answer` already repairs its findings this way — `.replace(raw,
    safe)` over the value it was GIVEN — and says why: "the leak is the path, not
    the field it happens to sit under", and "a redactor that guessed at a
    substring it was not given would be a second rule". Same technique, same
    rule, applied one step earlier.

    Both spellings of each value are respelled, because a caller may normalise
    separators on the way into its message (`guard-secrets-read` does) while
    handing the raw payload value here. Longest first, so a value that is a
    prefix of another cannot eat it.

    FAIL-CLOSED, which is why the miss is None rather than `text`. The direction
    is `_command_facts`'s: a writer that cannot redact must not write. A caller
    reads None as "omit the field" — an empty cell claims nothing, where the
    unredacted sentence would claim a home directory. `text` comes back
    unchanged when no value occurs in it, which is also what keeps an ordinary
    fixed-sentence verdict from loading the journal module at all.
    """
    try:
        raw = str(text or "")
        wanted = []
        for val in values or ():
            if not isinstance(val, str) or not val.strip():
                continue
            for spelling in (val, val.replace("\\", "/")):
                if spelling and spelling in raw and spelling not in wanted:
                    wanted.append(spelling)
        if not wanted:
            return raw
        mod = _load_journal_lib()
        if mod is None:
            return None
        for spelling in sorted(wanted, key=len, reverse=True):
            raw = raw.replace(spelling,
                              mod.repo_relative_or_token(str(root), spelling))
        return raw
    except Exception:
        return None


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

    ONE MORE INPUT KEY THAN THE ROW HAS OUTPUT KEYS, and the asymmetry is the
    point: a caller may hand this a `command`, and what lands is
    `_command_facts` — a digest, a byte length, a program name — never the text.
    A verdict about a shell call and a verdict about a file are two different
    claims, so they are two different fields; `file` stays a path, and a caller
    with no path to name omits it rather than filling the cell with what it had.

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
        row.update(_command_facts(event))
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


# --- which plugin copy is running ------------------------------------------------
# `CLAUDE_PLUGIN_ROOT` is fixed when a session STARTS: the harness interpolates it
# into hooks.json's command strings once, so a session that began before an upgrade
# goes on executing the copy it started with however many times the plugin is
# replaced underneath it. That is the harness's behaviour and not something a hook
# may change. What a hook CAN do is say WHICH copy it was -- and it is the only
# process in a position to, because the harness SUBSTITUTES that variable into a
# command string rather than exporting it, so `/audit:doctor` runs with no
# `CLAUDE_PLUGIN_ROOT` in its environment at all and cannot read the hooks' root
# from anywhere. Disk is the only channel from the copy that is running to the
# command a user asks what is running, which is why the writer and the reader
# below are one pair in one file.
RUNNING_STAMP = "running-plugin-%s.json"
RUNNING_STAMP_PREFIX = "running-plugin-"


def hook_plugin_root():
    """The plugin root THIS copy of the hooks was loaded from.

    A walk from `__file__` for `find_script`'s reason and not a second spelling
    of it: `hooks/` may not import `scripts/`, so `_output.PLUGIN_ROOT` -- the
    anchor every script resolves against -- is out of reach here."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hook_plugin_version(root=None):
    """`.claude-plugin/plugin.json`'s version for the copy running this hook, or
    "" when it cannot be read.

    "" is the ABSENCE of a version rather than a version: the stamp carries it
    through unchanged and the doctor grades a stamp that names no version as a
    copy it could not name, never as one that matches.
    `_output.plugin_version()` is this same read one directory over, for
    `scripts/`; the layer rule is what makes that two functions instead of one,
    and `tests/test__config.py` holds them against each other rather than a
    comment claiming they agree."""
    try:
        path = os.path.join(root if root else hook_plugin_root(),
                            ".claude-plugin", "plugin.json")
        with open(path, "r", encoding="utf-8") as fh:
            version = json.load(fh).get("version")
        return version if isinstance(version, str) and version.strip() else ""
    except Exception:
        return ""


def stamp_running_plugin(state_dir, session_id):
    """Record which plugin copy is executing the hooks in this project.

    Returns the dict it wrote, or None when it could not write -- a caller that
    could not tell those apart would report a stamp that is not on disk.

    Written by detect-plan-skip.py on UserPromptSubmit and by nothing else, and
    that placement is the cost decision rather than an accident: once per prompt
    is off the per-tool-call path the guards run on, and no session can reach a
    guarded tool call without submitting a prompt first. The file's mtime is its
    own timestamp -- the choice guard-bash-writes already made for its state, for
    the same reason: a field would only restate what the filesystem says."""
    try:
        root = hook_plugin_root()
        payload = {"root": root, "version": hook_plugin_version(root)}
        ensure_local_dir(state_dir)
        with open(Path(state_dir) / (RUNNING_STAMP % session_id), "w",
                  encoding="utf-8") as fh:
            json.dump(payload, fh)
        return payload
    except Exception:
        return None


# How far apart two refreshes of one session's stamp may be. A tool call inside
# this window pays one `stat` and writes nothing.
RUNNING_STAMP_REFRESH_SECONDS = 60


def refresh_running_stamp(state_dir, session_id, now=None):
    """Move this session's stamp's mtime to now, so it records the last guarded
    TOOL CALL and not only the last prompt. True when it moved.

    One prompt can drive hours of tool calls, subagents included, so a stamp
    written only on a prompt made every session mid-turn look idle beside the
    one asking `/audit:doctor`. Called from a guard on the per-tool-call path,
    which is why it is throttled to one write per `RUNNING_STAMP_REFRESH_SECONDS`
    and creates nothing: a session with no stamp has not prompted under this
    copy, and the payload is the prompt hook's to write. Never raises."""
    if not session_id:
        return False
    path = os.path.join(str(state_dir), RUNNING_STAMP % session_id)
    try:
        clock = time.time() if now is None else now
        if clock - os.stat(path).st_mtime < RUNNING_STAMP_REFRESH_SECONDS:
            return False
        os.utime(path, None)
        return True
    except Exception:
        return False


def refresh_session_stamp(root, cfg, session_id):
    """`refresh_running_stamp` for a guard: EVERYTHING it computes - the state
    directory from a config that may be malformed, the session id from a payload
    that may carry anything - happens inside one never-raise, because a guard's
    `main` exits 0 on an exception and 0 is allow. True when the stamp moved."""
    try:
        return refresh_running_stamp(state_dir(root, cfg),
                                     str(session_id or ""))
    except Exception:
        return False


def running_plugin_stamps(state_dir):
    """Every copy that has stamped itself in `state_dir`.

    `{"stamps": [{"root", "version", "session", "mtime"}], "unreadable": [name]}`,
    newest stamp first. A torn or unparseable stamp is COUNTED and named rather
    than skipped: a file that exists and cannot be read is evidence that a copy
    ran here, and dropping it would let the doctor report the same emptiness it
    reports when nothing ever ran.

    Read by `/audit:doctor` and by no hook. It lives here anyway because the name
    of the file and the names of its keys are one fact with one home, and a
    reader that restated them under `scripts/` would drift from the writer above
    the first time a key was added -- the same reason `DEFAULTS` carries a block
    no hook reads."""
    stamps, unreadable = [], []
    try:
        entries = sorted(os.listdir(str(state_dir)))
    except Exception:
        return {"stamps": stamps, "unreadable": unreadable}
    for name in entries:
        if not name.startswith(RUNNING_STAMP_PREFIX) or not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(str(state_dir), name), "r",
                      encoding="utf-8") as fh:
                obj = json.load(fh)
            mtime = os.path.getmtime(os.path.join(str(state_dir), name))
        except Exception:
            unreadable.append(name)
            continue
        if not isinstance(obj, dict):
            unreadable.append(name)
            continue
        stamps.append({"root": str(obj.get("root") or ""),
                       "version": str(obj.get("version") or ""),
                       "session": name[len(RUNNING_STAMP_PREFIX):-len(".json")],
                       "mtime": mtime})
    stamps.sort(key=lambda s: (-s["mtime"], s["session"]))
    return {"stamps": stamps, "unreadable": unreadable}

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
