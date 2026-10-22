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
import _loader                                     # noqa: E402  (load_hooks_config, load_script)
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

    # ui: the theme key accepts absent, a preset name, or a path
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

    # --- executor.runsGate ------------------------------------------------------
    # `portability`'s shape: a FINDING, not a warning, because only a finding
    # refuses the panel's save - and a value outside the vocabulary is exactly
    # the typo hooks/_config.executor_gate_policy refuses to fold into the
    # default rather than store and read back as neither word.
    for _runs in M.RUNS_GATE_MODES:
        f, w = M.validate_config({"executor": {"runsGate": _runs}})
        check("%r validates clean" % (_runs,), not f and not w)
    f, w = M.validate_config({"executor": {"runsGate": "sometimes"}})
    check("a value outside the vocabulary is a FINDING, not a silent read of "
          "the default: %r" % (f,),
          any("executor.runsGate" in x for x in f))
    f, w = M.validate_config({"executor": []})
    check("non-object executor -> finding", any("executor must be" in x for x in f))
    f, w = M.validate_config({"executor": {"runGate": "full"}})
    check("a misspelled executor key -> warning only, and no finding hides "
          "behind it: %r" % ((f, w),),
          not f and any("executor" in x for x in w))

    # --- review.perTask ---------------------------------------------------------
    # Where a task's three review answers are given. `executor.runsGate`'s shape
    # for the same reason: a FINDING refuses the panel's save, and a typo stored
    # anyway would be read back as neither word.
    for _per in M.REVIEW_PER_TASK_MODES:
        f, w = M.validate_config({"review": {"perTask": _per}})
        check("rv1 %r validates clean" % (_per,), not f and not w)
    f, w = M.validate_config({"review": {"perTask": "sometimes"}})
    check("rv2 a review.perTask outside the vocabulary is a FINDING: %r" % (f,),
          any("review.perTask" in x for x in f))
    f, w = M.validate_config({"review": "phase"})
    check("rv3 a non-object review -> finding",
          any("review must be" in x for x in f))
    f, w = M.validate_config({"review": {"perTsk": "phase"}})
    check("rv4 a misspelled review key -> warning only: %r" % ((f, w),),
          not f and any("review" in x for x in w))
    check("rv5 the modes mirror hooks/_config.py's, and the default the hooks "
          "ship is `phase`: %r" % ((M.REVIEW_PER_TASK_MODES,
                                    _hcfg.REVIEW_PER_TASK_MODES,
                                    _hcfg.DEFAULTS.get("review")),),
          tuple(M.REVIEW_PER_TASK_MODES) == tuple(_hcfg.REVIEW_PER_TASK_MODES)
          and (_hcfg.DEFAULTS.get("review") or {}).get("perTask") == "phase")
    _defs = {"review": {"perTask": "phase"}}
    check("rv6 the reading: the key when set, the shipped default when absent, "
          "and a value outside the vocabulary refused with a problem rather "
          "than read as the default",
          M.review_per_task_mode({"review": {"perTask": "always"}}, _defs)
          == ("always", None)
          and M.review_per_task_mode({}, _defs) == ("phase", None)
          and M.review_per_task_mode(None, _defs) == ("phase", None)
          and M.review_per_task_mode({"review": {"perTask": "x"}}, _defs)[0]
          is None
          and "review.perTask" in (M.review_per_task_mode(
              {"review": {"perTask": "x"}}, _defs)[1] or ""))
    with open(os.path.join(os.path.dirname(_harness.SCRIPTS_DIR), "schema",
                           "audit-plan.schema.json"), "r", encoding="utf-8") as fh:
        _pdefs = json.load(fh)["$defs"]
    check("rv7 the value a phase and a task record is the config's vocabulary, "
          "in the plan schema's own enums",
          [(_pdefs[k]["properties"].get("reviewPerTask") or {}).get("enum")
           for k in ("phase", "task")]
          == [list(M.REVIEW_PER_TASK_MODES)] * 2)

    # --- review.maxRounds --------------------------------------------------------
    # How many phase reviews a sign-off runs before it stops and asks once. A
    # cap of 0 would read as "no review at all, successfully", so it is refused
    # by name rather than folded into the default - the waveWidth shape.
    for _cap in (1, 2, 7):
        f, w = M.validate_config({"review": {"maxRounds": _cap}})
        check("rx1 review.maxRounds %r validates clean: %r" % (_cap, (f, w)),
              not f and not w)
    for _bad in (0, -1, True, "2", 1.5, None):
        f, w = M.validate_config({"review": {"maxRounds": _bad}})
        check("rx2 review.maxRounds %r is a FINDING naming the key: %r"
              % (_bad, f), any("review.maxRounds" in x for x in f))
    _rdefs = {"review": {"perTask": "phase", "maxRounds": 2}}
    check("rx3 the reading: the key when set, the shipped default when absent, "
          "and 0 refused by name with no value rather than read as the default",
          M.review_max_rounds({"review": {"maxRounds": 5}}, _rdefs) == (5, None)
          and M.review_max_rounds({}, _rdefs) == (2, None)
          and M.review_max_rounds(None, _rdefs) == (2, None)
          and M.review_max_rounds({"review": {"maxRounds": 0}}, _rdefs)[0] is None
          and "review.maxRounds" in (M.review_max_rounds(
              {"review": {"maxRounds": 0}}, _rdefs)[1] or ""))
    check("rx4 the hooks ship review.maxRounds 2, and the reading with no "
          "defaults handed in is that shipped value: %r"
          % ((_hcfg.DEFAULTS.get("review"), M.review_max_rounds({})),),
          (_hcfg.DEFAULTS.get("review") or {}).get("maxRounds") == 2
          and M.review_max_rounds({}) == (2, None))
    with open(os.path.join(os.path.dirname(_harness.SCRIPTS_DIR), "schema",
                           "audit-config.schema.json"), "r", encoding="utf-8") as fh:
        _rx_schema = json.load(fh)
    _rx_prop = ((((_rx_schema.get("properties") or {}).get("review") or {})
                 .get("properties") or {}).get("maxRounds") or {})
    check("rx5 the config schema types review.maxRounds an integer of at least "
          "1: %r" % (_rx_prop,),
          _rx_prop.get("type") == "integer" and _rx_prop.get("minimum") == 1)

    # --- executor.maxHours -------------------------------------------------------
    # The same shape as runsGate above, for the bound on CONTINUING an agent
    # across tasks: a positive number validates clean, and anything outside
    # that vocabulary is a FINDING rather than a silent read of the default.
    for _hrs in (1, 3, 0.5, 100):
        f, w = M.validate_config({"executor": {"maxHours": _hrs}})
        check("%r validates clean" % (_hrs,), not f and not w)
    for _bad in (0, -1, "3", True, [3]):
        f, w = M.validate_config({"executor": {"maxHours": _bad}})
        check("a value outside the vocabulary is a FINDING, not a silent "
              "read of the default: %r -> %r" % (_bad, f),
              any("executor.maxHours" in x for x in f))
    f, w = M.validate_config({"executor": {"maxHours": 3}})
    check("a recognised maxHours key never warns as unknown, the same "
          "regression runsGate's KNOWN_EXECUTOR entry already guards: %r"
          % (w,),
          not w)
    # --- executor.waveWidth, worktreeSetup, worktreeRoot ------------------------
    # How many ready disjoint tasks the driver runs at once, and where their trees
    # live and how they are set up. An absent width is 1, today's drive; a width
    # of 0 would read as "run nothing, successfully", so it is refused by name.
    for _w in (1, 2, 16, "auto"):
        f, w = M.validate_config({"executor": {"waveWidth": _w}})
        check("ww1 executor.waveWidth %r validates clean and is a known key: %r"
              % (_w, (f, w)), not f and not w)
    for _bad in (0, -1, 1.5, "2", "AUTO", True, None, [2]):
        f, w = M.validate_config({"executor": {"waveWidth": _bad}})
        check("ww2 executor.waveWidth %r is a FINDING, not a silent width: %r"
              % (_bad, f), any("executor.waveWidth" in x for x in f))
    f, w = M.validate_config({"executor": {"worktreeSetup": "npm ci",
                                           "worktreeRoot": "../trees"}})
    check("ww3 executor.worktreeSetup and worktreeRoot as non-empty strings "
          "validate clean and are known keys: %r" % ((f, w),), not f and not w)
    for _key in ("worktreeSetup", "worktreeRoot"):
        for _bad in ("", "  ", 3, ["npm ci"]):
            f, w = M.validate_config({"executor": {_key: _bad}})
            check("ww4 executor.%s %r is a FINDING: %r" % (_key, _bad, f),
                  any("executor.%s" % (_key,) in x for x in f))
    # --- executor.writerModel, writerBudgetUsd ---------------------------------
    # The writer session's model and per-session budget. The session runner
    # refuses an alias at run time, so validation refuses it first, by name; a
    # model with no positive finite budget beside it is a finding too, since the
    # drive cannot start a session without one.
    f, w = M.validate_config({"executor": {"writerModel": "claude-sonnet-4-5",
                                           "writerBudgetUsd": 2.5}})
    check("wm1 executor.writerModel as a full model id with a positive budget "
          "validates clean and both are known keys: %r" % ((f, w),), not f and not w)
    for _bad in ("opus", "sonnet", "claude", "claude-sonnet", "", " claude-opus-5 ",
                 5, None):
        f, w = M.validate_config({"executor": {"writerModel": _bad,
                                               "writerBudgetUsd": 2}})
        check("wm2 executor.writerModel %r is a FINDING - an alias or no id at all "
              "names no fixed model: %r" % (_bad, f),
              any("executor.writerModel" in x for x in f))
    for _bad in (0, -1, "5", True, float("inf"), float("nan"), None, [2]):
        f, w = M.validate_config({"executor": {"writerModel": "claude-opus-5-5",
                                               "writerBudgetUsd": _bad}})
        check("wm3 executor.writerBudgetUsd %r beside a writer model is a FINDING: "
              "%r" % (_bad, f), any("executor.writerBudgetUsd" in x for x in f))
    f, w = M.validate_config({"executor": {"writerModel": "claude-opus-5-5"}})
    check("wm4 a writer model with no budget at all is a FINDING naming the "
          "missing key: %r" % (f,), any("executor.writerBudgetUsd" in x for x in f))
    setting = M.writer_session_setting(
        {"executor": {"writerModel": "claude-opus-5-5", "writerBudgetUsd": 3}})
    absent = M.writer_session_setting({"executor": {"waveWidth": 2}})
    alias = M.writer_session_setting(
        {"executor": {"writerModel": "opus", "writerBudgetUsd": 3}})
    check("wm5 writer_session_setting reads the pair as the drive passes it, is "
          "(None, None) with no writer model, and refuses an alias: %r"
          % ((setting, absent, alias),),
          setting == ({"model": "claude-opus-5-5", "budget": "3"}, None)
          and absent == (None, None) and alias[0] is None
          and "executor.writerModel" in (alias[1] or ""))
    runner = _loader.load_script("run-agent-session.py", modname="ras_for_wm6")
    ids = ("claude-opus-5-5", "claude-sonnet-4-5-20250929", "opus", "claude-x",
           "claude-3", "Claude-opus-5")
    check("wm6 the config's full-model-id rule and the session runner's agree on "
          "every probe, so a config that validates is one the runner runs: %r"
          % ([(i, M.is_full_model_id(i), runner.is_full_model_id(i)) for i in ids],),
          all(M.is_full_model_id(i) == runner.is_full_model_id(i) for i in ids)
          and M.is_full_model_id("claude-opus-5-5")
          and not M.is_full_model_id("opus"))
    # --- executor.phaseGateOnly -------------------------------------------------
    # The gate commands a writer session is told to leave to the phase gate. The
    # empty default is the point: a project that names none is told nothing, so a
    # gate it owns is run by the writer. A value the reader cannot use is refused
    # by name rather than read as the empty list, which would quietly turn the
    # sentence off.
    f, w = M.validate_config({"executor": {"phaseGateOnly": [
        "verify.sh", "playwright test"]}})
    check("pg1 executor.phaseGateOnly as a list of non-empty strings validates "
          "clean and is a known key: %r" % ((f, w),), not f and not w)
    f, w = M.validate_config({"executor": {"phaseGateOnly": []}})
    check("pg1b an empty list is the default spelled out, so it validates "
          "clean too: %r" % ((f, w),), not f and not w)
    for _bad in ("verify.sh", ["verify.sh", ""], ["  "], [3], [["verify.sh"]],
                 {"verify.sh": 1}, 3, None, True):
        f, w = M.validate_config({"executor": {"phaseGateOnly": _bad}})
        check("pg2 executor.phaseGateOnly %r is a FINDING naming the key: %r"
              % (_bad, f), any("executor.phaseGateOnly" in x for x in f))
    _pg_set = M.phase_gate_only_setting(
        {"executor": {"phaseGateOnly": ["verify.sh", " playwright test "]}})
    _pg_none = M.phase_gate_only_setting({"executor": {"waveWidth": 2}})
    _pg_bad = M.phase_gate_only_setting({"executor": {"phaseGateOnly": "verify.sh"}})
    check("pg3 phase_gate_only_setting reads the list as written (trimmed), is "
          "((), None) when the key is absent - never a name the project did not "
          "give - and refuses a non-list with a problem naming the key: %r"
          % ((_pg_set, _pg_none, _pg_bad),),
          _pg_set == (("verify.sh", "playwright test"), None)
          and _pg_none == ((), None) and _pg_bad[0] == ()
          and "executor.phaseGateOnly" in (_pg_bad[1] or ""))

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
