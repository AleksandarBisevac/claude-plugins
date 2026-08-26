#!/usr/bin/env python3
"""
The cases for `_config_rules.py` - every rule .claude/audit.config.json is held to.

THIS SUITE USED TO BE `test_validate_config.py` AND IT FOLLOWED ITS SUBJECT.
The rules were `validate-config.py`'s body until three modules that are not
commands needed them: `_panel_settings` (L2) reads the enum tuples so the panel's
Settings form offers exactly what the validator accepts, and `_panel_state` (L5)
and `audit-doctor` (L7) each want `validate_config`. All three reached it through
`_loader.load_script("validate-config.py")`, which `_deps.layer_violations()`
counts, so three of the seventeen `KNOWN_LAYER_DEBT` entries were that one file
being used as a library — the `_panel_settings` one from layer 2, the deepest
inversion in the table. The rules moved to `_config_rules.py` at layer 2 (and
`_panel_settings` moved up to layer 3 to make the edge downward), and the cases
about the rules moved with them. What stayed in `test_validate_config.py` is what
is genuinely about the COMMAND: the exit codes.

`M` is a plain `import` now rather than a `_loader.load_script`, which is the
whole point of the move made visible in one line. Nothing else about these cases
changed: same labels, same order.

`_policy` is imported under its own name, the way `_config_rules.py` imports it,
because the last case in the policy group asserts IDENTITY - that this validator's
key sets ARE `_policy`'s objects and not a fourth copy of the same shape. That case
only means anything if both sides name the same module object, which they do:
`load_script` does not touch `sys.modules`, so `M`'s own `import _policy` resolves
to the very object imported here.

ONE PATH WAS RE-POINTED. The "shipped template passes its own validator" case reads
`../templates/audit.config.example.json` relative to the file it was written in.
From `tests/` the same `..` lands on the plugin directory too - by coincidence, not
by construction - so it is spelled off `_harness.SCRIPTS_DIR`'s parent instead. That
file is a shipped JSON TEMPLATE, not another module's source.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (load_hooks_config only)
import _policy                                     # noqa: E402
import _config_rules as M                          # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    f, w = M.validate_config({})
    check("empty config is valid", not f and not w)

    full = {
        "manifestPath": "docs/audit/audit-plan.json", "gitRoot": ".",
        "exemptGlobs": ["**/*.md"], "enforce": False, "trivialLineThreshold": 80,
        "stateDir": ".claude/state", "logsDir": ".claude/logs",
        "bypassKeyword": "#no-plan",
        "secretPatterns": {"extra": [r"\.secretrc$"]},
        "guardEdits": {"tokenVars": ["accessToken"],
                       "customRules": [{"pathPrefix": "src/", "bannedPattern": r"x\(", "message": "no"}]},
        "bashWriteCheck": {"enabled": True},
        "tddReminder": {"enabled": True, "sourceGlobs": ["**/*.ts"],
                        "testGlobs": ["**/*.test.*"], "throttleMinutes": 10,
                        "inProgressPolicy": "skip-all"},
        "usage": {"enabled": True, "ledgerDir": ".claude/usage",
                  "authorMode": "hash", "showCost": True,
                  "backfillOnFirstRun": False, "maxScanBytes": 1024,
                  "currency": "USD", "pricingAsOf": "2026-08-06",
                  "pricing": {"_default": {"in": 5.0, "out": 25.0, "cacheW5m": 6.25,
                                           "cacheW1h": 10.0, "cacheR": 0.5}}},
    }
    f, w = M.validate_config(full)
    check("fully-populated valid config passes", not f and not w)

    f, w = M.validate_config({"enforce": True})
    check("enforce:true is valid", not f and not w)
    f, w = M.validate_config({"enforce": False})
    check("enforce:false is valid", not f and not w)
    f, w = M.validate_config({"enforce": "true"})
    check("enforce as a string is a finding, not a silent truthy",
          any("enforce" in x for x in f))
    f, w = M.validate_config({"enforce": 1})
    check("enforce as a number is a finding", any("enforce" in x for x in f))
    f, w = M.validate_config({"enforce": False})
    check("enforce is a known root key (no unknown-key warning)", not w)

    # --- planGate (v0.34 B1) ---------------------------------------------------
    # The hook fails OPEN on a typo (never to deny), which is exactly why the
    # validator must fail LOUD on one: a value the gate silently reads as unset
    # would otherwise sit in the file looking like a decision.
    for _tier in ("observe", "warn", "ask", "deny"):
        f, w = M.validate_config({"planGate": _tier})
        check("planGate %r is a legal, known value (no finding, no warning)"
              % _tier, not f and not w)
    f, w = M.validate_config({"planGate": "denny"})
    check("a typo'd planGate is a FINDING - the hook would silently read it "
          "as unset", any("planGate" in x for x in f))
    f, w = M.validate_config({"planGate": True})
    check("a non-string planGate is a finding", any("planGate" in x for x in f))
    f, w = M.validate_config({"planGate": "deny", "enforce": True})
    check("planGate + enforce together is a WARNING naming the winner - the "
          "file still works, planGate wins",
          not f and any("planGate" in x and "enforce" in x for x in w))
    f, w = M.validate_config({"planGate": "observe", "enforce": False})
    check("...and it fires whichever way they point (enforce:false is still "
          "a second, losing statement about the same gate)",
          not f and any("planGate" in x and "enforce" in x for x in w))
    _hcfg = _loader.load_hooks_config(modname="audit__config_vc_selftest")
    check("PLAN_GATE_MODES IS the hooks' own tier tuple - the panel's select "
          "reads this validator, so a tier the gate honours can never be "
          "missing from the form",
          tuple(M.PLAN_GATE_MODES) == tuple(_hcfg.PLAN_GATE_TIERS))

    # The `//comment` convention is what this plugin's own template ships; warning
    # about it made the template fail its own validator nine times over.
    f, w = M.validate_config({"//": "a note", "//gitRoot": "why", "gitRoot": "."})
    check("`//` comment keys are not warned about", not f and not w)

    # Every policy the hook implements must validate. `warn-always` was documented
    # in four places, implemented in remind-tdd.py, covered by its selftests — and
    # rejected here, so following the documentation produced an invalid config.
    for _pol in ("skip-gate-only", "skip-all", "warn-always"):
        f, w = M.validate_config({"tddReminder": {"inProgressPolicy": _pol}})
        check("inProgressPolicy %r validates (the hook implements it)" % _pol,
              not f and not w)
    f, w = M.validate_config({"tddReminder": {"inProgressPolicy": "nonsense"}})
    check("an unimplemented inProgressPolicy is still a finding",
          any("inProgressPolicy" in x for x in f))
    _tmpl = os.path.join(os.path.dirname(_harness.SCRIPTS_DIR),
                         "templates", "audit.config.example.json")
    with open(_tmpl, encoding="utf-8") as _fh:
        f, w = M.validate_config(json.load(_fh))
    check("the shipped template passes its own validator cleanly",
          not f and not w)

    # th (F-P-6)
    check("ui: absent is fine", M.validate_config({})[0] == [])
    check("ui: a preset name validates",
          M.validate_config({"ui": {"theme": "slate-teal"}})[0] == [])
    check("ui: a path validates",
          M.validate_config({"ui": {"theme": ".claude/themes/midnight.json"}})[0] == [])
    check("ui: explicit null is an answer",
          M.validate_config({"ui": {"theme": None}})[0] == [])
    check("ui: a non-string theme is a finding",
          M.validate_config({"ui": {"theme": 3}})[0] != [])
    check("ui: a blank theme is a finding",
          M.validate_config({"ui": {"theme": "  "}})[0] != [])
    check("ui: a non-object ui is a finding",
          M.validate_config({"ui": "dark"})[0] != [])
    check("ui: an unknown ui key warns rather than refusing",
          M.validate_config({"ui": {"themee": "x"}})[0] == []
          and M.validate_config({"ui": {"themee": "x"}})[1] != [])
    f, w = M.validate_config({"usage": {"authorMode": "nope"}})
    check("usage.authorMode enum enforced", any("authorMode" in x for x in f))
    f, w = M.validate_config({"usage": {"maxScanBytes": -1}})
    check("negative usage.maxScanBytes -> finding",
          any("maxScanBytes" in x for x in f))
    f, w = M.validate_config({"usage": {"enabled": "yes"}})
    check("non-bool usage.enabled -> finding",
          any("usage.enabled" in x for x in f))
    f, w = M.validate_config({"usage": {"pricing": {"m": {"in": -1}}}})
    check("negative rate -> finding", any("pricing" in x for x in f))
    f, w = M.validate_config({"usage": {"pricing": {"m": "cheap"}}})
    check("non-object rate row -> finding", any("pricing" in x for x in f))
    f, w = M.validate_config({"usage": {"pricing": {"m": {"inn": 1}}}})
    check("unknown rate key -> warning only",
          not f and any("pricing" in x for x in w))
    f, w = M.validate_config({"usage": {"bogusKey": 1}})
    check("unknown usage key -> warning only", not f and len(w) == 1)

    # --- usage.bands ---------------------------------------------------------
    # The key is in DEFAULTS and the README tells you to set it; it was not in
    # KNOWN_USAGE, so doing what the documentation says produced a warning from the
    # plugin's own validator. This is the test for "the documented key is a real key".
    f, w = M.validate_config({"usage": {"bands": {"highUSD": 4, "outlierUSD": 12}}})
    check("the documented usage.bands pair validates clean - no unknown-key warning",
          not f and not w)
    # null is the shipped default and MEANS something: calibrate from the project.
    f, w = M.validate_config({"usage": {"bands": {"highUSD": None,
                                                  "outlierUSD": None}}})
    check("null thresholds are the default, not a missing value", not f and not w)
    f, w = M.validate_config({"usage": {"bands": {}}})
    check("an empty bands object is valid", not f and not w)
    f, w = M.validate_config({"usage": {"bands": {"highUSD": -1}}})
    check("a negative threshold -> finding",
          any("usage.bands.highUSD" in x for x in f))
    f, w = M.validate_config({"usage": {"bands": {"outlierUSD": "12"}}})
    check("a string threshold -> finding",
          any("usage.bands.outlierUSD" in x for x in f))
    f, w = M.validate_config({"usage": {"bands": {"highUSD": True,
                                                  "outlierUSD": 2}}})
    check("a bool threshold is rejected (not a number)",
          any("usage.bands.highUSD" in x for x in f))
    f, w = M.validate_config({"usage": {"bands": []}})
    check("non-object bands -> finding",
          any("usage.bands must be" in x for x in f))
    f, w = M.validate_config({"usage": {"bands": {"highUsd": 4}}})
    check("a misspelled band key -> warning only (the real one is highUSD)",
          not f and any("usage.bands" in x for x in w))
    # Inverted is a WARNING: cost_bands falls back to the relative basis, so the file
    # is not misread — and a finding would make the panel refuse to save a config
    # that works.
    f, w = M.validate_config({"usage": {"bands": {"highUSD": 20, "outlierUSD": 5}}})
    check("an inverted pair warns rather than failing - the runtime falls back "
          "instead of misclassifying", not f and any("fall back" in x for x in w))
    f, w = M.validate_config({"usage": {"bands": {"highUSD": 5, "outlierUSD": 5}}})
    check("high == outlier is legal (the runtime's own predicate is high <= outlier)",
          not f and not w)

    # --- journal --------------------------------------------------------------
    f, w = M.validate_config({"journal": {"enabled": True,
                                          "dir": "docs/audit/journal"}})
    check("the documented journal pair validates clean", not f and not w)
    f, w = M.validate_config({"journal": {"enabled": False}})
    check("turning the journal off is a legal config", not f and not w)
    f, w = M.validate_config({"journal": {"dir": None}})
    check("a null dir is the default, not a missing value - it means beside the "
          "manifest", not f and not w)
    f, w = M.validate_config({"journal": {"enabled": "true"}})
    check("a string `enabled` is a finding, not a silent truthy",
          any("journal.enabled" in x for x in f))
    f, w = M.validate_config({"journal": {"dir": ""}})
    check("an EMPTY dir is a finding - it would put the journal, and the guard "
          "that protects it, at the repository root",
          any("journal.dir" in x for x in f))
    f, w = M.validate_config({"journal": {"dir": 3}})
    check("a non-string dir is a finding", any("journal.dir" in x for x in f))
    f, w = M.validate_config({"journal": []})
    check("non-object journal -> finding", any("journal must be" in x for x in f))

    # --- evidence -------------------------------------------------------------
    # The same shape one record over, and the same trap: `dir` is joined onto the
    # project path, so an empty string puts the file at the repository ROOT - and
    # this record is COMMITTED, so that mistake ships rather than sitting in
    # somebody's scratch directory.
    f, w = M.validate_config({"evidence": {"dir": "docs/audit/evidence"}})
    check("the documented evidence dir validates clean", not f and not w)
    f, w = M.validate_config({"evidence": {"dir": None}})
    check("a null evidence dir is the DEFAULT and not a missing value - it means "
          "beside the manifest, so a repo that moves its plan takes the record of "
          "its runs along", not f and not w)
    f, w = M.validate_config({"evidence": {"dir": ""}})
    check("an EMPTY evidence dir is a finding - it would put a COMMITTED record "
          "at the repository root, which is the version of this mistake that "
          "ships: %r" % (f,), any("evidence.dir" in x for x in f))
    f, w = M.validate_config({"evidence": {"dir": 3}})
    check("a non-string evidence dir is a finding, paired with the empty one "
          "above so neither branch can be the only reason this passes",
          any("evidence.dir" in x for x in f))
    f, w = M.validate_config({"evidence": []})
    check("non-object evidence -> finding", any("evidence must be" in x for x in f))
    f, w = M.validate_config({"evidence": {"enabled": True}})
    check("`enabled` is NOT a key here and a warning says so - recording is "
          "opt-in at the call site, and a second off switch would be two keys "
          "expressing one thing: %r" % (w,),
          not f and any("evidence" in x for x in w))
    f, w = M.validate_config({"journal": {"enabledd": True}})
    check("a misspelled journal key -> warning only",
          not f and any("journal" in x for x in w))
    f, w = M.validate_config({"journal": {"strictManifestState": "ask"}})
    check("journal.strictManifestState 'ask' is a legal, known key",
          not f and not w)
    f, w = M.validate_config({"journal": {"strictManifestState": "off"}})
    check("...and 'off' (the shipped default) is too", not f and not w)
    f, w = M.validate_config({"journal": {"strictManifestState": "deny"}})
    check("a strictManifestState outside off|ask is a finding - 'deny' is "
          "deliberately not in the enum (the orchestrator writes through the "
          "same tools the guard watches)",
          any("strictManifestState" in x for x in f))
    f, w = M.validate_config({"journal": {"strictManifestState": True}})
    check("a non-string strictManifestState is a finding",
          any("strictManifestState" in x for x in f))

    # --- policy ---------------------------------------------------------------
    # The rules themselves are exercised in _policy.py's own selftest; what is
    # checked here is that this validator DELEGATES to it — a copy of the rules in
    # this file could call legal what the guard hook refuses.
    f, w = M.validate_config({"policy": {"enabled": True, "onViolation": "ask",
                                         "agents": {"default": "deny",
                                                    "allow": ["code-*"]}}})
    check("a documented policy block validates clean", not f and not w)
    f, w = M.validate_config({})
    check("no policy block is still a clean config", not f and not w)
    check("policy is a known root key, so writing one produces no unknown-key "
          "warning", "policy" in M.KNOWN_ROOT)
    f, _ = M.validate_config({"policy": {"onViolation": "block"}})
    check("an onViolation outside the enum -> finding",
          any("onViolation" in x for x in f))
    f, _ = M.validate_config({"policy": {"skills": {"default": "denied"}}})
    check("a misspelled default -> finding (it would silently ALLOW)",
          any("policy.skills.default" in x for x in f))
    f, _ = M.validate_config({"policy": {"mcp": {"deny": "mcp__prod__*"}}})
    check("a bare string where a pattern list goes -> finding",
          any("policy.mcp.deny" in x for x in f))
    f, _ = M.validate_config({"policy": {"agents": {"deny": ["audit:*"]}}})
    check("denying audit's own components -> finding, so the panel refuses to save "
          "a policy whose line does not take effect",
          any("not deniable" in x for x in f))
    _, w = M.validate_config({"policy": {"skills": {"typo": []}}})
    check("an unknown policy key -> warning only", any("unknown" in x for x in w))
    check("the key sets ARE _policy's, not a copy - a fourth statement of this "
          "shape is the drift the delegation exists to prevent",
          M.KNOWN_POLICY is _policy.KNOWN_POLICY
          and M.KNOWN_POLICY_KIND is _policy.KNOWN_KIND
          and M.POLICY_KINDS is _policy.KINDS)

    f, w = M.validate_config([])
    check("non-object root -> finding", len(f) == 1 and not w)

    f, w = M.validate_config({"trivialLineThreshold": 0})
    check("zero threshold -> finding",
          any("trivialLineThreshold" in x for x in f))
    f, w = M.validate_config({"trivialLineThreshold": True})
    check("bool threshold rejected (not int)",
          any("trivialLineThreshold" in x for x in f))

    f, w = M.validate_config({"manifestPath": ""})
    check("empty manifestPath -> finding", any("manifestPath" in x for x in f))

    f, w = M.validate_config({"exemptGlobs": "nope"})
    check("string exemptGlobs -> finding", any("exemptGlobs" in x for x in f))

    f, w = M.validate_config({"secretPatterns": {"extra": ["("]}})
    check("bad regex in secretPatterns.extra -> finding",
          any("not a valid regex" in x for x in f))

    f, w = M.validate_config({"guardEdits": {"customRules": [{"pathPrefix": "src/"}]}})
    check("customRule missing bannedPattern -> finding",
          any("bannedPattern" in x for x in f))
    f, w = M.validate_config({"guardEdits": {"customRules": [{"pathPrefix": "s/", "bannedPattern": "["}]}})
    check("customRule bad regex -> finding", any("not a valid regex" in x for x in f))
    f, w = M.validate_config({"guardEdits": {"customRules": "nope"}})
    check("customRules non-array -> finding",
          any("customRules must be an array" in x for x in f))

    f, w = M.validate_config({"bashWriteCheck": {"enabled": "yes"}})
    check("non-bool bashWriteCheck.enabled -> finding",
          any("enabled" in x for x in f))

    f, w = M.validate_config({"tddReminder": {"inProgressPolicy": "bogus"}})
    check("bad inProgressPolicy -> finding",
          any("inProgressPolicy" in x for x in f))
    f, w = M.validate_config({"tddReminder": {"throttleMinutes": -1}})
    check("negative throttleMinutes -> finding",
          any("throttleMinutes" in x for x in f))

    f, w = M.validate_config({"whatIsThis": 1})
    check("unknown top-level key -> warning only", not f and len(w) == 1)
    f, w = M.validate_config({"guardEdits": {"typo": 1}})
    check("unknown nested key -> warning only", not f and len(w) == 1)

    # --- the root vocabulary is one vocabulary (F79, F80) --------------------
    # cv1 is the case that would have caught the gap it was written for: `ui` was
    # read by `_ui_theme`, written by the panel, validated here and defaulted by
    # the hooks, and absent from the schema - where `additionalProperties: true`
    # meant no surface ever said so. It reads the real tree on purpose; the
    # fixture-driven cases below are what make its own failure modes testable,
    # which is the split `_help.vocab_drift()` is on.
    check("cv1 every published statement of the config's root vocabulary agrees "
          "with KNOWN_ROOT - the schema, the README's table and the hooks' "
          "DEFAULTS",
          M.config_vocab_drift() == [],
          "; ".join("%s: %s" % (s, p) for s, p in M.config_vocab_drift()))
    # cv2 states the disagreement between the two candidate authorities instead of
    # letting one of them win quietly. KNOWN_ROOT is the authority because it is
    # the only COMPLETE list: DEFAULTS is a proper subset by design, and the
    # difference is exactly what OFF_ROOT excuses with a reason. Put `policy` back
    # into DEFAULTS, or add a key to one list only, and this goes red.
    _hooks_root = set(_hcfg.DEFAULTS)
    check("cv2 KNOWN_ROOT is a proper superset of the hooks' DEFAULTS and the "
          "difference is exactly what OFF_ROOT excuses - so the narrower list is "
          "never quietly the authority",
          set(M.KNOWN_ROOT) - _hooks_root == set(M.OFF_ROOT["hooks DEFAULTS"])
          and not _hooks_root - set(M.KNOWN_ROOT),
          "extra in KNOWN_ROOT: %s | extra in DEFAULTS: %s"
          % (sorted(set(M.KNOWN_ROOT) - _hooks_root),
             sorted(_hooks_root - set(M.KNOWN_ROOT))))

    _known = {"alpha", "beta"}
    _clean = (("s", set(["alpha", "beta"]), None),)
    # cv3 looks vacuous and is the second-direction case: it is the only one that
    # fails if the comparison ever becomes unconditional. Keep it.
    check("cv3 a surface publishing exactly the vocabulary is silent",
          M.root_vocab_drift(_clean, _known, {}) == [])
    check("cv4 a key the validator accepts and a surface does not publish is "
          "named - the direction nothing held before",
          [p for _s, p in M.root_vocab_drift((("s", set(["alpha"]), None),),
                                             _known, {})
           if "'beta'" in p and "does not publish" in p])
    check("cv5 a key a surface publishes and the validator does not accept is "
          "named - a typo in a published list is otherwise invisible",
          [p for _s, p in M.root_vocab_drift(
              (("s", set(["alpha", "beta", "gama"]), None),), _known, {})
           if "'gama'" in p and "publishes" in p])
    check("cv6 a surface that publishes NOTHING is reported as empty rather than "
          "as agreement - a reader that quietly stopped matching would otherwise "
          "clear the whole vocabulary in one pass",
          [p for _s, p in M.root_vocab_drift((("s", set(), None),), _known, {})
           if "no root key at all" in p])
    check("cv7 a surface that could not be read reports its problem and is "
          "compared against nothing",
          M.root_vocab_drift((("s", None, "cannot be read: boom"),), _known, {})
          == [("s", "cannot be read: boom")])

    _off = {"s": {"beta": "a reason"}}
    check("cv8 OFF_ROOT excuses a key a surface leaves out on purpose",
          M.root_vocab_drift((("s", set(["alpha"]), None),), _known, _off) == [])
    check("cv9 ...and that exemption goes stale LOUDLY the moment the surface "
          "publishes the key - an exemption outliving its reason hides the next gap",
          [p for _s, p in M.root_vocab_drift(
              (("s", set(["alpha", "beta"]), None),), _known, _off)
           if "drop the exemption" in p])
    check("cv10 an exemption for a key the validator does not accept excuses "
          "nothing, and is named rather than believed",
          [p for _s, p in M.root_vocab_drift(
              (("s", set(["alpha", "beta"]), None),), _known,
              {"s": {"zeta": "why"}}) if "'zeta'" in p])
    check("cv11 an exemption with a blank reason is named",
          [p for _s, p in M.root_vocab_drift(
              (("s", set(["alpha"]), None),), _known, {"s": {"beta": "   "}})
           if "no reason" in p])
    check("cv12 OFF_ROOT naming a surface nothing reads is named - it would "
          "otherwise excuse a key on a surface that is no longer compared at all",
          [p for _s, p in M.root_vocab_drift(_clean, _known,
                                             {"gone": {"beta": "r"}})
           if "nothing reads" in p])

    # The README reader, on a fixture rather than on the shipped table: a case
    # that can only be run against the real README is a case whose own failure
    # modes are untested. The fixture carries both compound shapes the real table
    # has, and the values are chosen so the rule and its absence DISAGREE - drop
    # the leaf rule and `two` appears as a root; drop the root-segment rule and
    # `beta.one` does.
    _tbl = ("## Configuration (`.claude/audit.config.json`)\n"
            "\n"
            "| Key | Purpose | Default |\n"
            "|---|---|---|\n"
            "| `alpha` | one | `x` |\n"
            "| `beta.one` / `two` | a leaf spelled short | `y` |\n"
            "| `gamma` / `delta` | two roots in one cell | `z` |\n"
            "\n"
            "prose after the table\n")
    check("cv13 the README reader takes the ROOT of every key path in the first "
          "column, and reads a bare token after a NESTED one as a leaf rather "
          "than as another root",
          M.readme_root_keys(_tbl)
          == (set(["alpha", "beta", "gamma", "delta"]), None))
    check("cv14 a missing Configuration heading is a PROBLEM, never an empty "
          "vocabulary - returning the clean answer for an unreadable table is "
          "how a formatting change turns this gate into decoration",
          M.readme_root_keys("no heading here")[0] is None
          and "cannot be located" in M.readme_root_keys("no heading here")[1])
    check("cv15 a DOUBLED heading is a problem too - silently taking the first "
          "would read whichever table happened to come first",
          M.readme_root_keys(_tbl + _tbl)[0] is None)
    check("cv16 a header row that stopped opening with `Key` is a problem: the "
          "table's shape changed under the reader",
          M.readme_root_keys(_tbl.replace("| Key |", "| Setting |"))[0] is None)
    check("cv17 a header with no separator row under it is a problem",
          M.readme_root_keys(_tbl.replace("|---|---|---|\n", ""))[0] is None)
    check("cv18 a row whose first column names no key is a problem, never a "
          "silently skipped row",
          M.readme_root_keys(_tbl.replace("| `alpha` |", "| alpha |"))[0] is None)
    check("cv19 an escaped pipe inside a Key cell does not truncate it - the "
          "mistake command_flag_drift() had to make on this very file first, "
          "where a lazy match reported six commands as missing a flag that was "
          "written two characters further along",
          M.readme_root_keys(
              _tbl.replace("| `alpha` |", "| `alpha` \\| `zeta` |"))[0]
          == set(["alpha", "zeta", "beta", "gamma", "delta"]))

    # The two exit-code cases used to sit here. They are about
    # `validate-config.py`'s `main()`, not about a rule, and they went to
    # `test_validate_config.py` when the rules moved out from under it.


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__config_rules.py --selftest\n")
    raise SystemExit(2)
