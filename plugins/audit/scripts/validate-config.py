#!/usr/bin/env python3
"""
Structural validator for the per-repo config .claude/audit.config.json —
dependency-free (stdlib only). Complements schema/audit-config.schema.json with
the checks a schema pass alone doesn't surface nicely (regex compilability of
custom rules, positive thresholds), and gives the control panel a machine-usable
findings list.

Output classes:
  FINDING  — the config is INVALID / would be misread (exit 1).
  WARNING  — tolerated but suspicious (unknown/typo'd keys); exit stays 0.

Usage:
  python3 validate-config.py <config-path>

This module carries no inline `--selftest` any more; its 84 cases live in
`plugins/audit/tests/test_validate_config.py`, byte-identical labels and all -
see `plugins/audit/tests/_harness.py`. The flag is still accepted and still
exits 0, pointing there.

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

The core `validate_config(obj)` is pure and never raises on arbitrary JSON input.
The key set and shapes mirror hooks/_config.py DEFAULTS — that module stays the
source of truth for the hooks themselves; this validator only guards the file's
shape and is intentionally permissive (unknown keys are warnings, not findings).
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

# --- known keys -----------------------------------------------------------------
# Mirror of hooks/_config.py DEFAULTS key set (source of truth for the hooks).
KNOWN_ROOT = {
    "manifestPath", "gitRoot", "exemptGlobs", "enforce", "planGate",
    "trivialLineThreshold", "stateDir", "logsDir", "bypassKeyword",
    "secretPatterns", "guardEdits", "bashWriteCheck", "tddReminder", "usage",
    "journal", "policy", "ui",
}
# The tiers `planGate` may pin. Mirror of hooks/_config.py PLAN_GATE_TIERS (that
# module stays the source of truth for the gate itself); the selftest below pins
# the two together, and the panel's select reads THIS tuple via _cfg_enums.
PLAN_GATE_MODES = ("observe", "warn", "ask", "deny")
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

    # Delegated whole: the module that resolves a policy decides what a malformed
    # one is. A copy of those rules here would be free to call legal what the guard
    # hook refuses, which is the one disagreement a config validator must not have.
    pf, pw = _policy.validate_policy(obj.get("policy"))
    findings.extend(pf)
    warnings.extend(pw)

    return findings, warnings


# --- sub-checkers ---------------------------------------------------------------
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


# --- cli ------------------------------------------------------------------------
def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: validate-config.py <config-path>\n")
        return 2
    try:
        with open(argv[0], "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (argv[0], exc))
        return 2

    try:
        findings, warnings = validate_config(obj)
    except Exception as exc:  # defensive; validate_config should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    for line in warnings:
        print("WARNING: " + line)
    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1
    print("OK: %s valid%s"
          % (argv[0], " (%d warning(s))" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        # Answers rather than falling through to main(), which would read the
        # flag as a config path. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("validate-config.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_validate_config.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
