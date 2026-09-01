#!/usr/bin/env python3
"""
Every rule .claude/audit.config.json is held to, and the vocabulary its enums come from.

Complements schema/audit-config.schema.json with the checks a schema pass alone
doesn't surface nicely (regex compilability of custom rules, positive thresholds),
and gives the control panel a machine-usable findings list.

WHY THIS IS NOT `validate-config.py` ANY MORE. Three modules needed these rules
and only one of them is a command. `_panel_settings` reads the four enum tuples
straight off the validator so the Settings form offers exactly what the validator
accepts; `_panel_state` and `audit-doctor` each want `validate_config`. All three
reached it with `_loader.load_script("validate-config.py")`, and
`_deps.layer_violations()` counts those calls, so three of the seventeen entries
in `KNOWN_LAYER_DEBT` were this one file being loaded as a library — one of them
from LAYER 2, the deepest inversion in the table.

That deepest one is also why `_panel_settings` moved from layer 2 to layer 3 in
the same change. These rules import `_policy` (layer 1) and therefore cannot sit
below layer 2; a consumer AT layer 2 would still be a same-layer edge, which the
lint counts as not-strictly-downward and is right to. Moving one module up was
the whole cost — `_panel_settings` reaches nothing at L3 and nothing at L3
reaches it — where inserting a layer would have renumbered the table for an edge
that did not change.

Output classes, which the command turns into prefixes and an exit code:
  FINDING  — the config is INVALID / would be misread.
  WARNING  — tolerated but suspicious (unknown/typo'd keys).

`validate_config(obj)` is pure and never raises on arbitrary JSON input. The key
set and shapes mirror hooks/_config.py DEFAULTS — that module stays the source of
truth for the hooks themselves; this only guards the file's shape and is
intentionally permissive (unknown keys are warnings, not findings).

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__config_rules.py` — see `plugins/audit/tests/_harness.py`.
"""
import json
import os
import re
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _policy  # noqa: E402  (the policy block's shape + the resolution it feeds)
import _loader  # noqa: E402  (load_hooks_config: the third statement of the vocabulary)

# --- known keys -----------------------------------------------------------------
# Mirror of hooks/_config.py DEFAULTS key set (source of truth for the hooks).
KNOWN_ROOT = {
    "manifestPath", "gitRoot", "exemptGlobs", "enforce", "planGate",
    "trivialLineThreshold", "stateDir", "logsDir", "bypassKeyword",
    "secretPatterns", "guardEdits", "bashWriteCheck", "tddReminder", "usage",
    "journal", "evidence", "policy", "ui", "priority", "portability",
}
# The tiers `planGate` may pin. Mirror of hooks/_config.py PLAN_GATE_TIERS (that
# module stays the source of truth for the gate itself); the selftest below pins
# the two together, and the panel's select reads THIS tuple via _cfg_enums.
PLAN_GATE_MODES = ("observe", "warn", "ask", "deny")
# How strictly this repository refuses capabilities that would not survive a clone
# — a skill in somebody's home directory, a plugin the committed settings do not
# declare. `strict` is the shipped value and it BLOCKS: the panel offers only what
# travels and refuses to write anything else. `warn` diagnoses and blocks nothing;
# `off` says nothing at all. Read by `_panel_discovery`'s consumers rather than by
# the grading itself, which always states a verdict and lets each surface decide
# what to do about it.
PORTABILITY_MODES = ("strict", "warn", "off")


def portability_mode(config, defaults=None):
    """Which `portability` tier a project is on, falling back to what ships.

    HERE because four surfaces ask it — the doctor's row, the panel's write
    refusal, the policy switchboard and the report — and a tier resolved four
    times is four tiers waiting to disagree. It was written twice before this
    function existed, which is exactly how far that gets before it is a defect.

    A value outside the enum resolves to the shipped tier rather than switching
    the feature off: `validate_config` already refuses to store one, so a typo
    reaching here is a config nobody could have saved through the panel, and
    reading it as "off" would make a misspelling the quiet way to disable this.

    `defaults` is the hooks' `DEFAULTS` dict when a caller already holds it (the
    doctor does); otherwise it is loaded through the one loader.
    """
    if defaults is None:
        defaults = getattr(_loader.load_hooks_config(), "DEFAULTS", None) or {}
    mode = (config or {}).get("portability")
    if mode not in PORTABILITY_MODES:
        mode = defaults.get("portability")
    return mode if mode in PORTABILITY_MODES else PORTABILITY_MODES[0]
KNOWN_SECRET = {"extra"}
KNOWN_GUARD = {"tokenVars", "customRules"}
KNOWN_RULE = {"pathPrefix", "bannedPattern", "message"}
KNOWN_BASHW = {"enabled"}
KNOWN_TDD = {"enabled", "sourceGlobs", "testGlobs", "throttleMinutes",
             "inProgressPolicy"}
# `bands` is shipped in hooks/_config.py DEFAULTS and the plugin README tells you to
# set it. It was missing from this set, so following the documentation produced
# "unknown usage key 'bands'" from the plugin's own validator — the same shape of
# bug as `warn-always` below, one layer down.
KNOWN_USAGE = {"enabled", "ledgerDir", "authorMode", "showCost",
               "backfillOnFirstRun", "maxScanBytes", "currency", "pricingAsOf",
               "bands", "pricing"}
KNOWN_RATE = {"in", "out", "cacheW5m", "cacheW1h", "cacheR"}
KNOWN_BANDS = {"highUSD", "outlierUSD"}
# `dir` is null by default and that is MEANINGFUL — it means "beside the manifest",
# so a repo that moves its plan takes the record of it along. Same shape as
# usage.bands: a null here is an answer, not a missing value.
KNOWN_JOURNAL = {"enabled", "dir", "strictManifestState"}
# The test-evidence record. ONE KEY, and the absence of an `enabled` beside it is
# the decision rather than an oversight: recording is opt-in at the call site
# (`run-test-gate.py --record`), so a second off switch would be two keys saying
# one thing -- and COMPATIBILITY.md then owes a written precedence rule for the
# pair. `dir` is null by default and that null is MEANINGFUL, exactly as
# `journal.dir`'s is: it means "beside the manifest", so a repo that moves its
# plan takes the record of its runs along with it.
KNOWN_EVIDENCE = {"dir"}
# Phase prioritisation. One key, and it is advisory: see `_check_root`'s note on
# why nothing clamps to it.
KNOWN_PRIORITY = {"maxTier"}
# "deny" is deliberately absent: the orchestrator completes tasks through the
# same edit tools the guard watches, so strict mode can only ever ASK.
STRICT_MANIFEST_STATE = ("off", "ask")
# Not a fourth statement of the policy block's shape: `_policy` owns it, and every
# surface that needs the key set (this validator, the panel's Settings coverage
# check) reads THIS name, which is that module's.
KNOWN_POLICY = _policy.KNOWN_POLICY
KNOWN_POLICY_KIND = _policy.KNOWN_KIND
POLICY_KINDS = _policy.KINDS
ON_VIOLATION = _policy.ON_VIOLATION
# All three are implemented by remind-tdd.py and covered by its selftests;
# "warn-always" was documented in four places and rejected here, so setting the
# documented value made the config invalid and the panel refuse to save it.
IN_PROGRESS_POLICY = ("skip-gate-only", "skip-all", "warn-always")
AUTHOR_MODES = ("email", "name", "hash", "none")

_STR_PATHS = ("manifestPath", "gitRoot", "stateDir", "logsDir", "bypassKeyword")


# --- helpers --------------------------------------------------------------------
def _real_keys(obj):
    """Keys that are actual configuration, skipping `//` annotations.

    JSON has no comments, so this plugin's own template documents every field with a
    sibling `"//<key>"` string — at the top level and inside the nested objects.
    Treating those as unknown keys meant the shipped template produced nine warnings
    from this very validator, and so did every config copied from it: the documented
    pattern was punished by the tool that documents it. One predicate rather than a
    check per nesting level, so the rule cannot drift between them."""
    try:
        return [k for k in obj if not str(k).startswith("//")]
    except Exception:
        return []


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


# --- validate_config ------------------------------------------------------------
def validate_config(obj):
    """Return (findings, warnings). Pure; never raises on arbitrary JSON."""
    findings, warnings = [], []
    if not isinstance(obj, dict):
        return (["config root must be a JSON object, got %s"
                 % type(obj).__name__], warnings)

    for k in _real_keys(obj):
        if k not in KNOWN_ROOT:
            warnings.append("unknown top-level key %r (ignored by the hooks)" % k)

    for key in _STR_PATHS:
        if key in obj and not (isinstance(obj[key], str) and obj[key].strip()):
            findings.append("%s must be a non-empty string" % key)

    if "trivialLineThreshold" in obj:
        v = obj["trivialLineThreshold"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            findings.append("trivialLineThreshold must be a positive integer")

    if "exemptGlobs" in obj and not _is_str_list(obj["exemptGlobs"]):
        findings.append("exemptGlobs must be an array of strings")

    # A truthy string here is the dangerous typo: "false" is truthy in most
    # languages a reader might be coming from, and the hook ignores a non-bool
    # rather than trusting it — so silently taking the graded default while the
    # file says otherwise is exactly the surprise this finding prevents.
    if "enforce" in obj and not isinstance(obj["enforce"], bool):
        findings.append("enforce must be true or false (a bool, not a string)")

    # Same reasoning, stronger stakes: the hook fails OPEN on a planGate typo
    # (the graded ladder, never deny), so a value outside the enum is a setting
    # that silently does nothing while reading like a decision.
    if "planGate" in obj and obj["planGate"] not in PLAN_GATE_MODES:
        findings.append("planGate must be one of %s - the gate reads anything "
                        "else as unset (the graded ladder)"
                        % (PLAN_GATE_MODES,))
    # A FINDING rather than a warning, and for the reason above one key over: only
    # a finding refuses the panel's save, so a typo here would otherwise be stored
    # and then read as `strict` by every surface — the strictest tier, arrived at
    # by accident.
    if "portability" in obj and obj["portability"] not in PORTABILITY_MODES:
        findings.append("portability must be one of %s - it decides whether a "
                        "capability that would not survive a clone is refused, "
                        "merely reported, or ignored" % (PORTABILITY_MODES,))

    if "planGate" in obj and "enforce" in obj:
        warnings.append("both planGate and enforce are set - planGate wins; "
                        "enforce is legacy (true means the same as planGate: "
                        "\"deny\"), so drop it to keep one statement of the "
                        "gate's tier")

    sp = obj.get("secretPatterns")
    if sp is not None:
        if not isinstance(sp, dict):
            findings.append("secretPatterns must be an object")
        else:
            for k in _real_keys(sp):
                if k not in KNOWN_SECRET:
                    warnings.append("unknown secretPatterns key %r" % k)
            if "extra" in sp:
                if not _is_str_list(sp["extra"]):
                    findings.append("secretPatterns.extra must be an array of strings")
                else:
                    for i, pat in enumerate(sp["extra"]):
                        try:
                            re.compile(pat)
                        except re.error as exc:
                            findings.append("secretPatterns.extra[%d] is not a valid "
                                            "regex: %s" % (i, exc))

    ge = obj.get("guardEdits")
    if ge is not None:
        if not isinstance(ge, dict):
            findings.append("guardEdits must be an object")
        else:
            for k in _real_keys(ge):
                if k not in KNOWN_GUARD:
                    warnings.append("unknown guardEdits key %r" % k)
            if "tokenVars" in ge and not _is_str_list(ge["tokenVars"]):
                findings.append("guardEdits.tokenVars must be an array of strings")
            cr = ge.get("customRules")
            if cr is not None:
                if not isinstance(cr, list):
                    findings.append("guardEdits.customRules must be an array")
                else:
                    for i, rule in enumerate(cr):
                        _check_rule(i, rule, findings, warnings)

    bw = obj.get("bashWriteCheck")
    if bw is not None:
        if not isinstance(bw, dict):
            findings.append("bashWriteCheck must be an object")
        else:
            for k in _real_keys(bw):
                if k not in KNOWN_BASHW:
                    warnings.append("unknown bashWriteCheck key %r" % k)
            if "enabled" in bw and not isinstance(bw["enabled"], bool):
                findings.append("bashWriteCheck.enabled must be a boolean")

    tr = obj.get("tddReminder")
    if tr is not None:
        if not isinstance(tr, dict):
            findings.append("tddReminder must be an object")
        else:
            for k in _real_keys(tr):
                if k not in KNOWN_TDD:
                    warnings.append("unknown tddReminder key %r" % k)
            if "enabled" in tr and not isinstance(tr["enabled"], bool):
                findings.append("tddReminder.enabled must be a boolean")
            for g in ("sourceGlobs", "testGlobs"):
                if g in tr and not _is_str_list(tr[g]):
                    findings.append("tddReminder.%s must be an array of strings" % g)
            if "throttleMinutes" in tr:
                v = tr["throttleMinutes"]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    findings.append("tddReminder.throttleMinutes must be a "
                                    "non-negative number")
            if "inProgressPolicy" in tr and tr["inProgressPolicy"] not in IN_PROGRESS_POLICY:
                findings.append("tddReminder.inProgressPolicy must be one of %s"
                                % (IN_PROGRESS_POLICY,))

    # th (F-P-6): `ui.theme` is a preset NAME or a path to a theme file. The
    # shape is all this can judge: whether a named preset exists, or a path
    # resolves, is a question about a live tree and belongs to the doctor and
    # the panel (the same split the skills inventory already uses).
    ui = obj.get("ui")
    if ui is not None:
        if not isinstance(ui, dict):
            findings.append("ui must be an object, got %s" % type(ui).__name__)
        else:
            for k in ui:
                if k != "theme":
                    warnings.append("unknown key ui.%s (ignored)" % k)
            th = ui.get("theme")
            if th is not None and not (isinstance(th, str) and th.strip()):
                findings.append("ui.theme must be a non-empty string (a preset "
                                "name or a path) or null")

    # Phase prioritisation. `maxTier` is ADVISORY and nothing clamps to it, so
    # the only thing worth a finding is a value that could not be a tier at all:
    # a phase pinned above the maximum still runs, in tier order, and the write
    # path says so — but `maxTier: 0` or `"9"` would make the panel's control
    # offer an empty range while reading like a setting.
    pri = obj.get("priority")
    if pri is not None:
        if not isinstance(pri, dict):
            findings.append("priority must be an object, got %s"
                            % type(pri).__name__)
        else:
            for k in _real_keys(pri):
                if k not in KNOWN_PRIORITY:
                    warnings.append("unknown priority key %r" % k)
            if "maxTier" in pri:
                mt = pri["maxTier"]
                if isinstance(mt, bool) or not isinstance(mt, int) or mt < 1:
                    findings.append("priority.maxTier must be a positive "
                                    "integer - it is the highest tier the panel "
                                    "offers, and nothing is clamped to it")

    us = obj.get("usage")
    if us is not None:
        if not isinstance(us, dict):
            findings.append("usage must be an object")
        else:
            for k in _real_keys(us):
                if k not in KNOWN_USAGE:
                    warnings.append("unknown usage key %r" % k)
            for b in ("enabled", "showCost", "backfillOnFirstRun"):
                if b in us and not isinstance(us[b], bool):
                    findings.append("usage.%s must be a boolean" % b)
            for s in ("ledgerDir", "currency", "pricingAsOf"):
                if s in us and (not isinstance(us[s], str) or not us[s].strip()):
                    findings.append("usage.%s must be a non-empty string" % s)
            if "authorMode" in us and us["authorMode"] not in AUTHOR_MODES:
                findings.append("usage.authorMode must be one of %s" % (AUTHOR_MODES,))
            if "maxScanBytes" in us:
                v = us["maxScanBytes"]
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    findings.append("usage.maxScanBytes must be a non-negative integer")
            _check_bands(us.get("bands"), findings, warnings)
            _check_pricing(us.get("pricing"), findings, warnings)

    _check_journal(obj.get("journal"), findings, warnings)
    _check_evidence(obj.get("evidence"), findings, warnings)

    # Delegated whole: the module that resolves a policy decides what a malformed
    # one is. A copy of those rules here would be free to call legal what the guard
    # hook refuses, which is the one disagreement a config validator must not have.
    pf, pw = _policy.validate_policy(obj.get("policy"))
    findings.extend(pf)
    warnings.extend(pw)

    return findings, warnings


# --- sub-checkers ---------------------------------------------------------------
def _check_evidence(evidence, findings, warnings):
    """The test-evidence record's one setting.

    An empty `dir` is a FINDING and not a shrug, for `_check_journal`'s reason one
    record over: the string is joined onto the project path, so `""` would put the
    evidence file at the repository ROOT — and this one is committed, so the
    mistake ships. `null` is different and is the default: beside the manifest,
    derived from `manifestPath`, which is what lets one commit carry both a run
    and the record of it."""
    if evidence is None:
        return
    if not isinstance(evidence, dict):
        findings.append("evidence must be an object")
        return
    for k in _real_keys(evidence):
        if k not in KNOWN_EVIDENCE:
            warnings.append("unknown evidence key %r" % k)
    if evidence.get("dir") is not None:
        d = evidence["dir"]
        if not isinstance(d, str) or not d.strip():
            findings.append("evidence.dir must be a non-empty string, or null to "
                            "keep the record beside the manifest")


def _check_journal(journal, findings, warnings):
    """The audit trail's two settings.

    An empty `dir` is a FINDING rather than a shrug: the string is joined onto the
    project path, so `""` would put the journal — and the guard that refuses hand
    edits to it — at the repository root, which is not what anyone typing an empty
    box meant. `null` is different and is the default: beside the manifest."""
    if journal is None:
        return
    if not isinstance(journal, dict):
        findings.append("journal must be an object")
        return
    for k in _real_keys(journal):
        if k not in KNOWN_JOURNAL:
            warnings.append("unknown journal key %r" % k)
    if "enabled" in journal and not isinstance(journal["enabled"], bool):
        findings.append("journal.enabled must be true or false (a bool, not a "
                        "string)")
    if journal.get("dir") is not None:
        d = journal["dir"]
        if not isinstance(d, str) or not d.strip():
            findings.append("journal.dir must be a non-empty string, or null to "
                            "keep the journal beside the manifest")
    if ("strictManifestState" in journal
            and journal["strictManifestState"] not in STRICT_MANIFEST_STATE):
        findings.append("journal.strictManifestState must be one of %s -- "
                        "'ask' surfaces a confirmation prompt on manifest "
                        "state edits; there is deliberately no 'deny'"
                        % (STRICT_MANIFEST_STATE,))


def _check_bands(bands, findings, warnings):
    """Absolute cost-band thresholds.

    `null` is meaningful here and is the shipped default — it means "calibrate from
    this project's own completed tasks" — so a null is not a missing value to
    complain about.

    An inverted pair (`highUSD` > `outlierUSD`) is a WARNING, not a finding. The
    runtime already handles it: `usage_ledger.cost_bands` requires
    `0 < high <= outlier` and otherwise falls back to the relative basis rather than
    classifying anything wrongly. Calling it invalid would make the panel refuse to
    save a file that works, which is a harsher verdict than the behaviour justifies —
    and this validator's own contract reserves FINDING for a config that would be
    MISREAD."""
    if bands is None:
        return
    if not isinstance(bands, dict):
        findings.append("usage.bands must be an object")
        return
    for k in _real_keys(bands):
        if k not in KNOWN_BANDS:
            warnings.append("unknown usage.bands key %r" % k)
    vals = {}
    for k in ("highUSD", "outlierUSD"):
        if k not in bands or bands[k] is None:
            continue
        v = bands[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            findings.append("usage.bands.%s must be a non-negative number or null" % k)
        else:
            vals[k] = float(v)
    if len(vals) == 2 and vals["highUSD"] > vals["outlierUSD"]:
        warnings.append(
            "usage.bands.highUSD (%g) is above outlierUSD (%g), so the pair is "
            "ignored and the bands fall back to this project's own completed tasks"
            % (vals["highUSD"], vals["outlierUSD"]))


def _check_pricing(pricing, findings, warnings):
    """Rates are USD per MILLION tokens. A malformed row would silently price spend
    at zero, so the shape is a finding rather than a warning."""
    if pricing is None:
        return
    if not isinstance(pricing, dict):
        findings.append("usage.pricing must be an object")
        return
    for model, row in pricing.items():
        if not isinstance(row, dict):
            findings.append("usage.pricing[%r] must be an object" % model)
            continue
        for k in _real_keys(row):
            if k not in KNOWN_RATE:
                warnings.append("unknown usage.pricing[%r] key %r" % (model, k))
        for k in KNOWN_RATE:
            if k not in row:
                continue
            v = row[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                findings.append("usage.pricing[%r].%s must be a non-negative number"
                                % (model, k))


def _check_rule(i, rule, findings, warnings):
    if not isinstance(rule, dict):
        findings.append("guardEdits.customRules[%d] must be an object" % i)
        return
    for k in _real_keys(rule):
        if k not in KNOWN_RULE:
            warnings.append("unknown guardEdits.customRules[%d] key %r" % (i, k))
    for req in ("pathPrefix", "bannedPattern"):
        if not (isinstance(rule.get(req), str) and rule[req].strip()):
            findings.append("guardEdits.customRules[%d].%s must be a non-empty "
                            "string" % (i, req))
    if isinstance(rule.get("bannedPattern"), str):
        try:
            re.compile(rule["bannedPattern"])
        except re.error as exc:
            findings.append("guardEdits.customRules[%d].bannedPattern is not a "
                            "valid regex: %s" % (i, exc))
    if "message" in rule and not isinstance(rule["message"], str):
        findings.append("guardEdits.customRules[%d].message must be a string" % i)


# --- is the root vocabulary one vocabulary? -------------------------------------
# KNOWN_ROOT IS THE AUTHORITY FOR BOTH DIRECTIONS AND `DEFAULTS` IS NOT. Settling
# that came first, because the two do not agree: `policy` is in KNOWN_ROOT and
# deliberately absent from hooks/_config.py DEFAULTS (that module's `--- policy ---`
# note says why - `_policy.py` owns the block, and copying it back would put the
# scripts-side module on the hot path of every tool call). DEFAULTS is therefore a
# proper subset by design, and picking it as the authority would under-report by
# exactly the block with the most consequence.
#
# WHY HERE, WHEN `_help.schema_vocab_drift()` ALREADY DOES THIS FOR THE MANIFEST.
# That comparison had to leave `_manifest_vocab` because the vocabulary sits at
# layer 1 while the tree's only `$ref`-resolving schema walk sits at layer 2, so the
# alternative was a second walk. Neither half applies here: this module IS the
# config vocabulary, `_help` is its PEER at layer 2 (so neither may import the
# other), and the config's root level is `schema["properties"]` - a dict access, not
# a walk. Mirroring the manifest's shape would mean moving this vocabulary down into
# a layer-1 module - renaming what the panel's Settings form, the doctor and several
# suites read - to save that dict access.
_SCHEMA_REL = os.path.join("schema", "audit-config.schema.json")
_README_REL = "README.md"
# The table this reads, located by its own heading rather than by position.
README_TABLE_HEADING = "## Configuration (`.claude/audit.config.json`)"
# The first column, up to an UNESCAPED pipe - the discipline `command_flag_drift()`
# had to learn on this same file, where a lazy match to the first `|` truncated
# half the cells and reported keys that were written two characters further along.
_CFG_CELL = re.compile(r"^\|((?:\\\||[^|])*)\|")
_CFG_KEY = re.compile(r"`([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9{},]+)*)`")
_CFG_SEP = re.compile(r"^[\s:|-]+$")

# Keys a surface may leave unpublished, with the reason it may. Read BOTH ways by
# `root_vocab_drift`: an exemption for a key the validator does not accept, or for
# one the surface has since published, is itself a finding. An exemption list with
# no live reasons is where a lint goes to die.
OFF_ROOT = {
    "hooks DEFAULTS": {
        "policy": "_policy.py owns the block's shape and its defaults; "
                  "hooks/_config.py stopped copying them so that consulting a "
                  "policy would not import the scripts-side module on every "
                  "tool call",
    },
}


def _cell_roots(cell):
    """The ROOT keys one Key cell of the Configuration table names.

    The table's compound cells are why this is a stated rule rather than a split on
    whitespace: a cell may name several roots (`stateDir` beside `logsDir`), and a
    cell whose first key is nested may name further LEAVES of that same key
    (`usage.currency` beside `pricingAsOf`). So a bare token following a nested one
    is a leaf, and one following a bare token is another root.
    """
    tokens = _CFG_KEY.findall(cell)
    if not tokens:
        return []
    nested_head = "." in tokens[0]
    roots = [tokens[0].split(".")[0]]
    for tok in tokens[1:]:
        if nested_head and "." not in tok:
            continue
        roots.append(tok.split(".")[0])
    return roots


def readme_root_keys(text):
    """(keys, problem) - the root keys the README's Configuration table documents.

    A MARKDOWN TABLE IS PROSE, so this reads the least of it that answers the
    question: the root segment of every backticked key path in the first column.
    Leaves are deliberately not compared - the map from a top-level key to the keys
    inside it is hand-kept wherever it exists at all (the panel's Settings form
    keeps one, and its own case says so), and a lint comparing against a hand-kept
    map agrees with a second copy rather than with the code.

    IT FAILS LOUDLY OR NOT AT ALL. A heading that is missing or doubled, a header
    row whose first column stopped saying `Key`, a missing separator, or a row that
    names no key each come back as a PROBLEM - because "I could not read this
    table" and "this table is complete" are different answers, and returning the
    empty finding list for both is how a formatting change turns a gate into
    decoration.
    """
    seen = text.count(README_TABLE_HEADING)
    if seen != 1:
        return None, ("carries the Configuration heading %d time(s), so the table "
                      "cannot be located" % (seen,))
    tail = text[text.find(README_TABLE_HEADING):].splitlines()[1:]
    rows, started = [], False
    for line in tail:
        if line.startswith("|"):
            rows.append(line)
            started = True
        elif started:
            break
    if len(rows) < 3:
        return None, ("the Configuration heading is followed by %d table row(s), "
                      "so the key table is not there to read" % (len(rows),))
    head = _CFG_CELL.match(rows[0])
    if head is None or head.group(1).strip() != "Key":
        return None, ("the Configuration table's header row does not open with a "
                      "`Key` column, so its shape has changed under this")
    if not _CFG_SEP.match(rows[1]):
        return None, ("the Configuration table's header is not followed by a "
                      "separator row, so its shape has changed under this")
    keys = set()
    for row in rows[2:]:
        cell = _CFG_CELL.match(row)
        if cell is None:
            return None, ("a Configuration table row has no first column: %r"
                          % (row[:60],))
        roots = _cell_roots(cell.group(1))
        if not roots:
            return None, ("a Configuration table row names no key in its first "
                          "column: %r" % (cell.group(1).strip(),))
        keys |= set(roots)
    return keys, None


def root_vocab_drift(surfaces, known, off_root):
    """[(surface, problem), ...] - every surface that has stopped agreeing with
    `known` about the config's root keys.

    Separate from `config_vocab_drift()` because that one reads every surface off a
    file on disk, and a lint you can only run against the real tree is a lint whose
    own failure modes are untested - the split `_help.vocab_drift()` is on, for the
    same reason. Every case that proves this goes red hands it a fixture here
    instead of mutating the shipped vocabulary.

    `surfaces` is `((name, keys or None, problem or None), ...)`, `known` the
    authority, and `off_root` the `{surface: {key: reason}}` table.
    """
    out = []
    named = set(name for name, _keys, _problem in surfaces)
    for name in sorted(set(off_root) - named):
        out.append((name, "OFF_ROOT excuses keys for a surface nothing reads"))
    for name, keys, problem in surfaces:
        if problem is not None:
            out.append((name, problem))
            continue
        published = set(keys or ())
        if not published:
            out.append((name, "publishes no root key at all - a comparison against "
                              "nothing passes for any vocabulary"))
            continue
        exempt = off_root.get(name) or {}
        for key in sorted(set(known) - published - set(exempt)):
            out.append((name, "does not publish %r, which the validator accepts - "
                              "publish it, or add it to OFF_ROOT with the reason "
                              "this surface leaves it out" % (key,)))
        for key in sorted(published - set(known)):
            out.append((name, "publishes %r, which the validator does not accept - "
                              "a config that sets it is warned about by the "
                              "plugin's own validator" % (key,)))
        for key in sorted(exempt):
            if key in published:
                out.append((name, "OFF_ROOT excuses %r, but this surface now "
                                  "publishes it - drop the exemption" % (key,)))
            elif key not in known:
                out.append((name, "OFF_ROOT excuses %r, which the validator does "
                                  "not accept - an exemption for a key nothing "
                                  "reads excuses nothing and hides the next one"
                            % (key,)))
            if not str(exempt[key]).strip():
                out.append((name, "OFF_ROOT excuses %r with no reason" % (key,)))
    return out


def _read_schema_roots(root):
    """(keys, problem) - the root property names the config schema publishes."""
    try:
        with open(os.path.join(root, _SCHEMA_REL), "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, "cannot be read: %s" % (exc,)
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return None, "declares no root `properties` object to compare against"
    return set(schema["properties"]), None


def _read_readme_roots(root):
    """(keys, problem) - the root keys the plugin README's config table documents."""
    try:
        with open(os.path.join(root, _README_REL), "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return None, "cannot be read: %s" % (exc,)
    return readme_root_keys(text)


def _read_defaults_roots():
    """(keys, problem) - the root keys the hooks ship a default for.

    Through `_loader.load_hooks_config()` rather than by parsing the file: DEFAULTS
    is a dict literal of nested dicts, and a text scan of it would be a second and
    worse reader of something the loader already hands back. That call names no
    sibling and is why `_deps` leaves it out of the layer graph.

    Broad on purpose: a hooks module that cannot be loaded at all is exactly the
    case that must be SAID rather than passed over, and the value returned is a
    problem, not an empty key set that would read as agreement.
    """
    try:
        mod = _loader.load_hooks_config(modname="audit_config_vocab_defaults")
    except Exception as exc:                                    # noqa: BLE001
        return None, "cannot be loaded: %s" % (exc,)
    if not isinstance(getattr(mod, "DEFAULTS", None), dict):
        return None, "has no DEFAULTS dict to compare against"
    return set(mod.DEFAULTS), None


def config_vocab_drift(plugin_root=None):
    """[(surface, problem), ...] - every published statement of the config's root
    vocabulary that has stopped agreeing with `KNOWN_ROOT`.

    THE DIRECTION NOTHING HELD. The panel's Settings coverage case derives the
    form's controls FROM this validator, so "documented, therefore reachable" was
    already checked; "runs, therefore published" was not. `ui` spent its whole life
    read by `_ui_theme`, written by the panel, validated here, defaulted by the
    hooks - and absent from the schema, where `additionalProperties: true` meant no
    surface ever said so (F79). The README table is the same rule one surface
    further (F80): `priority.maxTier` had a panel control and no published row, so
    the only description of the lever was the row for the command that writes it.

    ROOT KEYS ONLY, which is the level at which three statements written for three
    different readers are comparable without inventing a fourth, hand-kept map
    between them.
    """
    root = plugin_root if plugin_root is not None else _output.PLUGIN_ROOT
    schema_keys, schema_bad = _read_schema_roots(root)
    readme_keys, readme_bad = _read_readme_roots(root)
    hooks_keys, hooks_bad = _read_defaults_roots()
    return root_vocab_drift((("schema", schema_keys, schema_bad),
                             ("README", readme_keys, readme_bad),
                             ("hooks DEFAULTS", hooks_keys, hooks_bad)),
                            KNOWN_ROOT, OFF_ROOT)


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_config_rules.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__config_rules.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())


