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
  python3 validate-config.py --selftest

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

The core `validate_config(obj)` is pure and never raises on arbitrary JSON input.
The key set and shapes mirror hooks/_config.py DEFAULTS — that module stays the
source of truth for the hooks themselves; this validator only guards the file's
shape and is intentionally permissive (unknown keys are warnings, not findings).
"""
import json
import re
import sys

# Mirror of hooks/_config.py DEFAULTS key set (source of truth for the hooks).
KNOWN_ROOT = {
    "manifestPath", "gitRoot", "exemptGlobs", "trivialLineThreshold",
    "stateDir", "logsDir", "bypassKeyword", "secretPatterns", "guardEdits",
    "bashWriteCheck", "tddReminder",
}
KNOWN_SECRET = {"extra"}
KNOWN_GUARD = {"tokenVars", "customRules"}
KNOWN_RULE = {"pathPrefix", "bannedPattern", "message"}
KNOWN_BASHW = {"enabled"}
KNOWN_TDD = {"enabled", "sourceGlobs", "testGlobs", "throttleMinutes",
             "inProgressPolicy"}
IN_PROGRESS_POLICY = ("skip-gate-only", "skip-all")

_STR_PATHS = ("manifestPath", "gitRoot", "stateDir", "logsDir", "bypassKeyword")


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate_config(obj):
    """Return (findings, warnings). Pure; never raises on arbitrary JSON."""
    findings, warnings = [], []
    if not isinstance(obj, dict):
        return (["config root must be a JSON object, got %s"
                 % type(obj).__name__], warnings)

    for k in obj:
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

    sp = obj.get("secretPatterns")
    if sp is not None:
        if not isinstance(sp, dict):
            findings.append("secretPatterns must be an object")
        else:
            for k in sp:
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
            for k in ge:
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
            for k in bw:
                if k not in KNOWN_BASHW:
                    warnings.append("unknown bashWriteCheck key %r" % k)
            if "enabled" in bw and not isinstance(bw["enabled"], bool):
                findings.append("bashWriteCheck.enabled must be a boolean")

    tr = obj.get("tddReminder")
    if tr is not None:
        if not isinstance(tr, dict):
            findings.append("tddReminder must be an object")
        else:
            for k in tr:
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

    return findings, warnings


def _check_rule(i, rule, findings, warnings):
    if not isinstance(rule, dict):
        findings.append("guardEdits.customRules[%d] must be an object" % i)
        return
    for k in rule:
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


# --- selftest -------------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    f, w = validate_config({})
    check("empty config is valid", not f and not w)

    full = {
        "manifestPath": "docs/audit/audit-plan.json", "gitRoot": ".",
        "exemptGlobs": ["**/*.md"], "trivialLineThreshold": 80,
        "stateDir": ".claude/state", "logsDir": ".claude/logs",
        "bypassKeyword": "#no-plan",
        "secretPatterns": {"extra": [r"\.secretrc$"]},
        "guardEdits": {"tokenVars": ["accessToken"],
                       "customRules": [{"pathPrefix": "src/", "bannedPattern": r"x\(", "message": "no"}]},
        "bashWriteCheck": {"enabled": True},
        "tddReminder": {"enabled": True, "sourceGlobs": ["**/*.ts"],
                        "testGlobs": ["**/*.test.*"], "throttleMinutes": 10,
                        "inProgressPolicy": "skip-all"},
    }
    f, w = validate_config(full)
    check("fully-populated valid config passes", not f and not w)

    f, w = validate_config([])
    check("non-object root -> finding", len(f) == 1 and not w)

    f, w = validate_config({"trivialLineThreshold": 0})
    check("zero threshold -> finding", any("trivialLineThreshold" in x for x in f))
    f, w = validate_config({"trivialLineThreshold": True})
    check("bool threshold rejected (not int)", any("trivialLineThreshold" in x for x in f))

    f, w = validate_config({"manifestPath": ""})
    check("empty manifestPath -> finding", any("manifestPath" in x for x in f))

    f, w = validate_config({"exemptGlobs": "nope"})
    check("string exemptGlobs -> finding", any("exemptGlobs" in x for x in f))

    f, w = validate_config({"secretPatterns": {"extra": ["("]}})
    check("bad regex in secretPatterns.extra -> finding",
          any("not a valid regex" in x for x in f))

    f, w = validate_config({"guardEdits": {"customRules": [{"pathPrefix": "src/"}]}})
    check("customRule missing bannedPattern -> finding",
          any("bannedPattern" in x for x in f))
    f, w = validate_config({"guardEdits": {"customRules": [{"pathPrefix": "s/", "bannedPattern": "["}]}})
    check("customRule bad regex -> finding", any("not a valid regex" in x for x in f))
    f, w = validate_config({"guardEdits": {"customRules": "nope"}})
    check("customRules non-array -> finding", any("customRules must be an array" in x for x in f))

    f, w = validate_config({"bashWriteCheck": {"enabled": "yes"}})
    check("non-bool bashWriteCheck.enabled -> finding", any("enabled" in x for x in f))

    f, w = validate_config({"tddReminder": {"inProgressPolicy": "bogus"}})
    check("bad inProgressPolicy -> finding", any("inProgressPolicy" in x for x in f))
    f, w = validate_config({"tddReminder": {"throttleMinutes": -1}})
    check("negative throttleMinutes -> finding", any("throttleMinutes" in x for x in f))

    f, w = validate_config({"whatIsThis": 1})
    check("unknown top-level key -> warning only", not f and len(w) == 1)
    f, w = validate_config({"guardEdits": {"typo": 1}})
    check("unknown nested key -> warning only", not f and len(w) == 1)

    # exit-code contract
    check("main usage error -> 2", main([]) == 2)
    check("main missing file -> 2", main(["/no/such/file.json"]) == 2)

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
