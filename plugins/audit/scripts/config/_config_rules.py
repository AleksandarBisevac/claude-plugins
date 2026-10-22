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
from the lowest layer any of them sat in, the deepest inversion in the table.

That deepest one is also why `_panel_settings` moved up one layer in the same
change. These rules import `_policy` and therefore sit one layer above it; a
consumer in that same layer would still be a same-layer edge, which the lint
counts as not-strictly-downward and is right to. Moving one module up was the
whole cost — `_panel_settings` reaches nothing in its new layer and nothing there
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
`tests/test__config_rules.py` — see `tests/_harness.py`.
"""
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
    "journal", "evidence", "policy", "ui", "priority", "portability", "executor",
    "review", "ci",
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
# Mirror of hooks/_config.py RUNS_GATE_MODES (that module stays the source of
# truth for `executor_gate_policy`); the selftest below pins the two together,
# the same shape PLAN_GATE_MODES above mirrors PLAN_GATE_TIERS.
KNOWN_EXECUTOR = {"runsGate", "maxHours", "waveWidth", "worktreeSetup",
                  "worktreeRoot", "writerModel", "writerBudgetUsd",
                  "phaseGateOnly"}
# A full model id is `claude-<family...>` with a version digit in it; an alias
# (`opus`, `sonnet`) names whatever is newest on the day, so two writers under
# one config could run two models. `run-agent-session.py` refuses the same
# shapes at run time with its own copy of this pattern - it imports none of
# this layer - and `wm6` in `tests/test__config_rules.py` holds the two equal
# on every probe.
FULL_MODEL_ID = re.compile(r"^claude-[a-z][a-z0-9-]*[0-9][a-z0-9-]*$")
# The one word `executor.waveWidth` takes besides a whole number: as many tasks
# at once as the machine has cores less two, resolved by the driver.
WAVE_WIDTH_AUTO = "auto"
RUNS_GATE_MODES = ("never", "own-tests", "full")
# Mirror of hooks/_config.py REVIEW_PER_TASK_MODES, pinned the same way: where a
# task's three review answers are given - by a reviewer per task, by the phase
# review at sign-off, or per task only where a computed signal fires.
KNOWN_REVIEW = {"perTask", "maxRounds"}
REVIEW_PER_TASK_MODES = ("always", "phase", "signals")
# When a long phase asks CI about itself before it lands. `cadence` holds the
# triggers (`closes`: every N task closes, `hours`: every H hours of phase time,
# either or both); `workflow` is the workflow file dispatched, `ci.yml` unless it
# names another. Nothing in `ci` set means landing only, as before the key existed.
# `pushCarry` is the one key here that is not about CI: it is where the step
# driver's other act on the remote is switched on, and it lives beside the
# cadence because both are the project saying "the driver may push" - absent,
# the driver pushes nothing of its own accord.
KNOWN_CI = {"cadence", "workflow", "pushCarry"}
KNOWN_CI_CADENCE = {"closes", "hours"}
CI_WORKFLOW_DEFAULT = "ci.yml"


def review_per_task_mode(config, defaults=None):
    """`(mode, problem)` - `review.perTask` as `config` sets it, else the shipped
    default; `(None, problem)` for a value outside REVIEW_PER_TASK_MODES.

    REFUSED, NOT FOLDED INTO THE DEFAULT, unlike `portability_mode`: this key
    decides which close and which landing a task's review answers hold, and a
    typo read as the default would make a guarantee nobody chose look chosen.
    Asked by every verb that records the key where a phase has none yet, each of
    which refuses on the problem. `defaults` is the hooks' DEFAULTS when a caller
    already holds it."""
    if defaults is None:
        defaults = getattr(_loader.load_hooks_config(), "DEFAULTS", None) or {}
    block = (config or {}).get("review")
    if not isinstance(block, dict) or "perTask" not in block:
        shipped = (defaults.get("review") or {}).get("perTask")
        if shipped in REVIEW_PER_TASK_MODES:
            return shipped, None
        return None, ("the hooks' DEFAULTS ship no review.perTask in %s, so "
                      "there is no default to read" % (REVIEW_PER_TASK_MODES,))
    mode = block["perTask"]
    if mode in REVIEW_PER_TASK_MODES:
        return mode, None
    return None, ("review.perTask is %r, not one of %s - fix the config "
                  "(/audit:doctor names it); it is not read as the default"
                  % (mode, ", ".join(REVIEW_PER_TASK_MODES)))


def _positive_int(value):
    """A whole number of at least 1, never a bool - which Python counts as one."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def review_max_rounds(config, defaults=None):
    """`(rounds, problem)` - `review.maxRounds` as `config` sets it, else the
    shipped default: how many phase reviews a sign-off dispatches before the
    step driver stops and asks once. `(None, problem)` for anything but a
    positive integer.

    REFUSED, NOT FOLDED INTO THE DEFAULT: a cap of 0 would read as "no review
    round, successfully", and a typo read as the default would make a cap
    nobody chose look chosen. `defaults` is the hooks' DEFAULTS when a caller
    already holds it."""
    if defaults is None:
        defaults = getattr(_loader.load_hooks_config(), "DEFAULTS", None) or {}
    block = (config or {}).get("review")
    if not isinstance(block, dict) or "maxRounds" not in block:
        shipped = (defaults.get("review") or {}).get("maxRounds")
        if _positive_int(shipped):
            return shipped, None
        return None, ("the hooks' DEFAULTS ship no positive review.maxRounds, "
                      "so there is no default to read")
    rounds = block["maxRounds"]
    if _positive_int(rounds):
        return rounds, None
    return None, ("review.maxRounds is %r, not a positive integer - fix the "
                  "config (/audit:doctor names it); it is not read as the "
                  "default" % (rounds,))


def _positive_number(value):
    """A number above 0, never a bool - which Python counts as one."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value > 0)


def ci_cadence_setting(config):
    """`(cadence, problem)` - `ci.cadence` as `config` sets it: `None` when the
    key is absent (CI is asked about at landing only, as every config ran before
    the key existed), else `{"closes": int or None, "hours": number or None,
    "workflow": str}`; `(None, problem)` for a value that cannot be read.

    REFUSED, NOT FOLDED INTO ABSENT: a cadence of 0 or `"often"` read as "no
    cadence" would be a setting that silently does nothing while reading like a
    decision, and an empty cadence names no trigger at all."""
    block = (config or {}).get("ci")
    if not isinstance(block, dict) or "cadence" not in block:
        return None, None
    raw = block["cadence"]
    if not isinstance(raw, dict):
        return None, "ci.cadence is %r, not an object of closes and/or hours" % (raw,)
    closes, hours = raw.get("closes"), raw.get("hours")
    if "closes" in raw and not _positive_int(closes):
        return None, ("ci.cadence.closes is %r, not a whole number of at least 1 "
                      "- fix the config (/audit:doctor names it); it is not read "
                      "as no cadence" % (closes,))
    if "hours" in raw and not _positive_number(hours):
        return None, ("ci.cadence.hours is %r, not a number above 0 - fix the "
                      "config (/audit:doctor names it); it is not read as no "
                      "cadence" % (hours,))
    if "closes" not in raw and "hours" not in raw:
        return None, ("ci.cadence names neither closes nor hours, so it asks CI "
                      "about nothing - set one, or remove ci.cadence for landing "
                      "only")
    workflow = block.get("workflow", CI_WORKFLOW_DEFAULT)
    if not (isinstance(workflow, str) and workflow.strip()):
        return None, ("ci.workflow is %r, not a non-empty workflow file name"
                      % (workflow,))
    return {"closes": closes if "closes" in raw else None,
            "hours": hours if "hours" in raw else None,
            "workflow": workflow.strip()}, None


def carry_push_setting(config):
    """`(push, problem)` - `ci.pushCarry` as `config` sets it: `False` when the
    key is absent (a filed wave member's carry ref stays in this repository),
    `True` only when it is the JSON `true`; `(None, problem)` for any other
    value.

    REFUSED, NOT FOLDED INTO ABSENT: `"yes"` or `1` read as `false` would be an
    operator who asked for the carry on the remote and silently did not get it,
    and read as `true` would publish unfinished work on a spelling nobody
    checked."""
    block = (config or {}).get("ci")
    if not isinstance(block, dict) or "pushCarry" not in block:
        return False, None
    value = block["pushCarry"]
    if isinstance(value, bool):
        return value, None
    return None, ("ci.pushCarry is %r, not true or false - fix the config "
                  "(/audit:doctor names it); it is not read as either" % (value,))


def _valid_wave_width(value):
    """A whole number of at least 1 - never a bool, which Python counts as one
    - or the word `auto`."""
    if value == WAVE_WIDTH_AUTO and isinstance(value, str):
        return True
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def wave_width_setting(config):
    """`(value, problem)` - `executor.waveWidth` as `config` sets it: an int of
    at least 1, `"auto"`, or 1 when the key is absent, which is the one task at
    a time every config ran before the key existed. `(None, problem)` for any
    other value: a width of 0 would read as "run nothing, successfully", so it
    is refused rather than read as the default."""
    block = (config or {}).get("executor")
    if not isinstance(block, dict) or "waveWidth" not in block:
        return 1, None
    value = block["waveWidth"]
    if _valid_wave_width(value):
        return value, None
    return None, ("executor.waveWidth is %r, not a whole number of at least 1 "
                  "or %r - fix the config (/audit:doctor names it); it is not "
                  "read as the default" % (value, WAVE_WIDTH_AUTO))


def is_full_model_id(model):
    return isinstance(model, str) and bool(FULL_MODEL_ID.match(model))


def _positive_amount(value):
    """A finite number above zero: `True` is no amount, and neither is an
    infinite ceiling or `nan`."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and value == value and value != float("inf") and value > 0)


def writer_session_setting(config):
    """`(setting, problem)` for a writer run as a headless session:
    `{"model", "budget"}` from `executor.writerModel` and
    `executor.writerBudgetUsd`, the budget as the runner's argv spells it;
    `(None, None)` when no writer model is set, which keeps the executor Agent;
    `(None, problem)` naming the key that is not a full model id or not a
    positive finite amount - never a default standing in for either."""
    block = (config or {}).get("executor")
    block = block if isinstance(block, dict) else {}
    if "writerModel" not in block:
        return None, None
    model = block["writerModel"]
    if not is_full_model_id(model):
        return None, ("executor.writerModel is %r, not a full model id "
                      "(claude-<family>-<version>); an alias names whatever is "
                      "newest on the day" % (model,))
    budget = block.get("writerBudgetUsd")
    if not _positive_amount(budget):
        return None, ("executor.writerBudgetUsd is %s: a writer session runs under "
                      "a per-session budget, so it needs a positive number of USD "
                      "beside executor.writerModel" % (
                          "absent" if budget is None else "%r" % (budget,)))
    return {"model": model, "budget": "%s" % (budget,)}, None


def phase_gate_only_setting(config):
    """`(names, problem)`: the gate commands `executor.phaseGateOnly` names as
    left to the phase gate, each trimmed, as a tuple.

    Absent is `((), None)` - the empty default is the contract, because a name
    this repository happens to use (`verify.sh`) is also a project's own gate and
    the writer must run that one. A value that is not a list of non-empty strings
    is `((), problem)`, never an empty tuple standing in for it: the empty tuple
    would read as the key not being set and turn the sentence off unannounced."""
    block = (config or {}).get("executor")
    if not isinstance(block, dict) or "phaseGateOnly" not in block:
        return (), None
    names = block["phaseGateOnly"]
    if not (isinstance(names, list)
            and all(isinstance(n, str) and n.strip() for n in names)):
        return (), ("executor.phaseGateOnly is %r, not a list of non-empty "
                    "command names (a script name such as verify.sh, or words "
                    "such as 'playwright test')" % (names,))
    return tuple(n.strip() for n in names), None


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

    # th: `ui.theme` is a preset NAME or a path to a theme file. The
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
    _check_executor(obj.get("executor"), findings, warnings)
    _check_review(obj.get("review"), findings, warnings)
    _check_ci(obj.get("ci"), findings, warnings)

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


def _check_executor(executor, findings, warnings):
    """The executor's own gate-running policy, and how long it may be
    CONTINUED across tasks before the orchestrator hands it back.

    A FINDING rather than a warning, for `portability`'s reason: only a finding
    refuses the panel's save, and a value outside RUNS_GATE_MODES (or outside
    `maxHours`'s own vocabulary, a positive number) is exactly the typo
    `hooks/_config.executor_gate_policy`/`executor_context_bound_hours` refuse
    to fold into their defaults - stored anyway, it would be read back as
    neither the word/number written nor the default, which is the
    silent-misread this validator's own contract exists to catch."""
    if executor is None:
        return
    if not isinstance(executor, dict):
        findings.append("executor must be an object")
        return
    for k in _real_keys(executor):
        if k not in KNOWN_EXECUTOR:
            warnings.append("unknown executor key %r" % k)
    if ("runsGate" in executor
            and executor["runsGate"] not in RUNS_GATE_MODES):
        findings.append("executor.runsGate must be one of %s - a value outside "
                        "this vocabulary is refused rather than read as the "
                        "default" % (RUNS_GATE_MODES,))
    if "maxHours" in executor:
        _hrs = executor["maxHours"]
        if (isinstance(_hrs, bool) or not isinstance(_hrs, (int, float))
                or _hrs <= 0):
            findings.append("executor.maxHours must be a positive number - a "
                            "value outside this vocabulary is refused rather "
                            "than read as the default, the same shape "
                            "executor.runsGate uses above")
    if "waveWidth" in executor and not _valid_wave_width(executor["waveWidth"]):
        findings.append("executor.waveWidth must be a whole number of at least 1 "
                        "or %r - a width of 0 would read as a drive that runs "
                        "nothing, successfully" % (WAVE_WIDTH_AUTO,))
    if "writerModel" in executor or "writerBudgetUsd" in executor:
        _setting, problem = writer_session_setting({"executor": executor})
        if problem:
            findings.append(problem)
        elif "writerBudgetUsd" in executor \
                and not _positive_amount(executor["writerBudgetUsd"]):
            findings.append("executor.writerBudgetUsd must be a positive number "
                            "of USD")
    if "phaseGateOnly" in executor:
        _names, problem = phase_gate_only_setting({"executor": executor})
        if problem:
            findings.append(problem)
    for key in ("worktreeSetup", "worktreeRoot"):
        if key in executor and not (isinstance(executor[key], str)
                                    and executor[key].strip()):
            findings.append("executor.%s must be a non-empty string - leave the "
                            "key out for %s" % (key, "no setup command"
                                                 if key == "worktreeSetup" else
                                                 "the directory above the git root"))


def _check_review(review, findings, warnings):
    """Where a task's three review answers are given. A FINDING for a value
    outside the vocabulary, `_check_executor`'s reason: only a finding refuses
    the panel's save, and `review_per_task_mode` refuses to read one."""
    if review is None:
        return
    if not isinstance(review, dict):
        findings.append("review must be an object")
        return
    for k in _real_keys(review):
        if k not in KNOWN_REVIEW:
            warnings.append("unknown review key %r" % k)
    if "perTask" in review and review["perTask"] not in REVIEW_PER_TASK_MODES:
        findings.append("review.perTask must be one of %s - a value outside "
                        "this vocabulary is refused rather than read as the "
                        "default" % (REVIEW_PER_TASK_MODES,))
    if "maxRounds" in review and not _positive_int(review["maxRounds"]):
        findings.append("review.maxRounds must be a positive integer - a cap "
                        "of %r is refused rather than read as the default"
                        % (review["maxRounds"],))


def _check_ci(ci, findings, warnings):
    """When a long phase asks CI about itself, and whether the driver pushes a
    carry. A FINDING for a value the drive refuses to read (`ci_cadence_setting`,
    `carry_push_setting`), `_check_executor`'s reason: only a finding refuses the
    panel's save."""
    if ci is None:
        return
    if not isinstance(ci, dict):
        findings.append("ci must be an object")
        return
    for k in _real_keys(ci):
        if k not in KNOWN_CI:
            warnings.append("unknown ci key %r" % k)
    cadence = ci.get("cadence")
    if isinstance(cadence, dict):
        for k in _real_keys(cadence):
            if k not in KNOWN_CI_CADENCE:
                warnings.append("unknown ci.cadence key %r" % k)
    if "pushCarry" in ci:
        _push, problem = carry_push_setting({"ci": ci})
        if problem:
            findings.append(problem)
    if "cadence" in ci:
        _setting, problem = ci_cadence_setting({"ci": ci})
        if problem:
            findings.append(problem)
    elif "workflow" in ci and not (isinstance(ci["workflow"], str)
                                   and ci["workflow"].strip()):
        findings.append("ci.workflow is %r, not a non-empty workflow file name"
                        % (ci["workflow"],))


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


_EFFECTIVE_FROM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_rate_row(model, row, findings, warnings, where):
    """One flat rate row's keys and values - `where` names it in a finding/warning
    (the model alone for a flat entry, `model[i]` for a dated one)."""
    if not isinstance(row, dict):
        findings.append("usage.pricing[%r] must be an object" % where)
        return
    for k in _real_keys(row):
        if k not in KNOWN_RATE:
            warnings.append("unknown usage.pricing[%r] key %r" % (where, k))
    for k in KNOWN_RATE:
        if k not in row:
            continue
        v = row[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            findings.append("usage.pricing[%r].%s must be a non-negative number"
                            % (where, k))


def _check_dated_rows(model, rows, findings, warnings):
    """A model's entry given as a list of `{"effectiveFrom", "rates"}` rows - the
    shape `_usage_core.rates_for(model, table, at)` reads beside the flat legacy
    row (COMPATIBILITY.md: a config key the plugin reads keeps being read, and
    this is the new shape it also reads). Each row is named by index so a
    malformed one is findable without counting commas."""
    if not rows:
        findings.append("usage.pricing[%r] must not be an empty list" % model)
        return
    for i, entry in enumerate(rows):
        where = "%s[%d]" % (model, i)
        if not isinstance(entry, dict):
            findings.append("usage.pricing[%r] must be an object" % where)
            continue
        ef = entry.get("effectiveFrom")
        if not isinstance(ef, str) or not _EFFECTIVE_FROM_RE.match(ef):
            findings.append(
                "usage.pricing[%r].effectiveFrom must be a YYYY-MM-DD date"
                % where)
        extra = set(_real_keys(entry)) - {"effectiveFrom", "rates"}
        for k in sorted(extra):
            warnings.append("unknown usage.pricing[%r] key %r" % (where, k))
        _check_rate_row(model, entry.get("rates"), findings, warnings,
                        "%s.rates" % where)


def _check_pricing(pricing, findings, warnings):
    """Rates are USD per MILLION tokens. A malformed row would silently price spend
    at zero, so the shape is a finding rather than a warning.

    An entry is either a flat rate row (legacy: in effect always) or a list of
    dated rows - see `_check_dated_rows`."""
    if pricing is None:
        return
    if not isinstance(pricing, dict):
        findings.append("usage.pricing must be an object")
        return
    for model, row in pricing.items():
        if isinstance(row, list):
            _check_dated_rows(model, row, findings, warnings)
        else:
            _check_rate_row(model, row, findings, warnings, model)


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
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())


