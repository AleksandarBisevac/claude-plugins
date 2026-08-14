#!/usr/bin/env python3
"""
The Settings form's schema, and the write-path key allow-lists it shares with
panel-server.py — stdlib only.

Moved out of panel-server.py (P12.1). Three things live here because they are all
SETTINGS-SHAPE KNOWLEDGE, not server plumbing:

  * FIELD_HELP / COMPOSITION_HELP / SETTINGS_GROUPS — the Settings form described
    once, in Python, rather than hand-written field by field (see SETTINGS_GROUPS'
    own comment for why: the `usage.*` block and four of five `tddReminder.*` keys
    had drifted out of a form that existed to make the whole config legible).
  * `_META_KEYS` / `_META_API_ONLY` / `_META_FORM_KEYS` / `_PHASE_KEYS` /
    `_TASK_KEYS` — the write path's security allow-list: which composition fields
    a patch is permitted to touch at all.
  * `_settings_paths()` and `_cfg_enums()` — the two lookups the form and its
    selftest both read: every config path the form binds a control to, and the
    enum choices read off validate-config.py rather than copied by hand.

panel-server.py keeps thin module-level aliases (`FIELD_HELP =
_panel_settings.FIELD_HELP`, etc.) so every downstream reference — its
substitution chain (UI_HTML's __SETTINGS__/__FIELD_HELP__/__COMP_HELP__/
__CFG_ENUMS__), its write path (_composition_changes, _reject_unknown), and
_help.py's own selftest — keeps working unchanged.

This module sits at the BOTTOM of the panel's own import graph: it must never
import _help or panel-server, so nothing that imports THIS module (both of them
do) can ever form a cycle through it.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _loader  # noqa: E402  (the one path-importlib loader for scripts/)

# --- key allow-lists (composition write path) -------------------------------
# Fields the composition patch is allowed to touch — the security allow-list.
# `areas` is here so the registry can be written through the ONE write path that
# takes the lock, validates, journals and patches only the index (meta lives on the
# index; a registry save must never rewrite a phase shard). /api/areas is a thin
# front door onto it rather than a second writer.
_META_KEYS = ("reviewSkill", "buildCommands", "areas")
# ...of which these have no control on the Composition form: they are written by
# their own endpoint, so the confirm dialog's client-side change list must NOT
# enumerate them or it would compute a row for a field nobody can edit there. The
# selftest derives the client's list from this pair rather than trusting the two
# to be kept in step by hand.
_META_API_ONLY = ("areas",)
_META_FORM_KEYS = tuple(k for k in _META_KEYS if k not in _META_API_ONLY)
_PHASE_KEYS = ("reviewModel",)
_TASK_KEYS = ("model", "skills")


# --- the Settings form, described once, in Python --------------------------------
# WHY IN PYTHON. This used to be a `DESC = {...}` literal inside the UI string, and
# the form itself was hand-written field by field — so the set of settings the panel
# could edit was whatever someone had remembered to type. It had drifted: the whole
# `usage.*` block and four of the five `tddReminder.*` keys had no control at all,
# on the one surface whose entire job is making the config legible.
#
# Described here instead, the coverage question becomes mechanical. validate-config
# already knows every legal key (KNOWN_ROOT / KNOWN_SECRET / KNOWN_GUARD /
# KNOWN_BASHW / KNOWN_TDD / KNOWN_USAGE), so the selftest DERIVES the expected paths
# from the validator and compares — no hand-kept list on either side. A new config
# key without a control here fails the build rather than quietly not existing in the
# UI.
#
# `kind` drives a generic renderer for the ordinary shapes; `custom` hands the path
# to a bespoke renderer in the UI (lists of regexes, the rules table, the band pair,
# the pricing rows). Either way the path appears here, so it counts as covered.
FIELD_HELP = {
    "manifestPath":
        "Path to the audit manifest JSON, relative to this project. "
        "Default docs/audit/audit-plan.json.",
    "gitRoot":
        "Path of the git repo root, where git and the build/gate commands run. "
        "Default '.' — this directory IS the git root.",
    "stateDir":
        "Where the hooks keep their per-session state files. They are local scratch, "
        "garbage-collected after 7 days; the dir ignores itself (a `*` .gitignore "
        "is written inside).",
    "logsDir": "Where the hooks write the bypass log. Local scratch; self-ignoring "
               "like stateDir.",
    "bypassKeyword":
        "Type this in a prompt to arm a ONE-OFF plan-first bypass for the next edit. "
        "It is consumed by that edit and logged.",
    "trivialLineThreshold":
        "The first file you touch in a session is free if the edit adds at most this "
        "many lines. Anything larger needs a plan.",
    "planGate":
        "Pin the plan-first gate to one tier: observe records, warn advises, ask "
        "holds each out-of-plan edit for your approval, deny refuses. On the "
        "default it grades itself on evidence: observe (no manifest) -> warn (a "
        "manifest, nothing running) -> deny (a phase is in_progress). Replaces "
        "the legacy enforce flag - saving from here rewrites enforce as planGate. "
        "The secret guards are never graded; they deny either way.",
    "exemptGlobs":
        "Globs whose edits skip the plan-first, TDD and shell-write guards — docs, "
        "tests, .claude/** and the manifest. Globs, not regexes: each one is matched "
        "against the whole relative path AND against the bare file name, so "
        "**/*.test.* and *.test.* both work.",
    "secretPatterns.extra":
        "Extra file paths to treat as secrets, so reading one is refused. These are "
        "REGEXES, not globs, and they are matched case-insensitively anywhere in the "
        "path: '.env' means 'any character, then env' and matches secrets.envelope. "
        "Write \\.env$ if you mean the file. A pattern that does not compile is "
        "dropped in silence at runtime — this form refuses to save one instead.",
    "guardEdits.tokenVars":
        "Identifier names that must never be logged: a console.log or print of any "
        "of these is blocked. Your list REPLACES the three defaults rather than "
        "adding to them.",
    "guardEdits.customRules":
        "Your own banned patterns: block a regex in new content when a piece of text "
        "appears in the path being edited. The path test is a SUBSTRING match against "
        "the path the edit tool reported (usually absolute), so 'realtime/' covers "
        "every realtime/ directory in the repo. A rule missing either field, or whose "
        "pattern does not compile, is skipped in silence at runtime — this form "
        "refuses to save one instead.",
    "bashWriteCheck.enabled":
        "After a Bash command, diff git status and warn when it created source files "
        "that were not planned. A warning, never a block.",
    "tddReminder.enabled":
        "Nudge when you edit source without touching a test. Non-blocking: it prints "
        "a reminder and gets out of the way.",
    "tddReminder.sourceGlobs":
        "Globs that count as source, so editing one is a candidate for the nudge. "
        "This list also defines what 'source' means to the shell-write guard — the "
        "two read the same setting so they cannot disagree.",
    "tddReminder.testGlobs":
        "Globs that count as tests. Touching one in the same session silences the "
        "nudge.",
    "tddReminder.throttleMinutes":
        "Least time between two nudges in one session. 0 means nudge every time.",
    "tddReminder.inProgressPolicy":
        "What the nudge does while an audit task is in_progress. skip-gate-only "
        "(default) stays quiet for files the task already covers; skip-all goes quiet "
        "for the whole run; warn-always ignores the manifest entirely.",
    "usage.enabled":
        "Meter token usage on the Stop and SubagentStop hooks. The ledger records "
        "counts, model ids, timestamps, branch and author — never prompt content.",
    "usage.ledgerDir":
        "Where the monthly NDJSON ledger and its scan cursors are written. "
        "Deliberately outside stateDir, which is garbage-collected: a lost cursor "
        "would re-scan a transcript from the start and double-count.",
    "usage.authorMode":
        "How the spender is recorded: their git email, their git name, a short "
        "salt-free sha256 (pseudonymous but still groupable), or nobody at all.",
    "usage.showCost":
        "Show an equivalent API cost beside the tokens. Labelled 'equiv' because a "
        "subscription plan carries no per-token bill.",
    "usage.backfillOnFirstRun":
        "The first time a transcript is seen, read it from the start instead of "
        "metering only from now on. Bounded by the scan ceiling below.",
    "usage.maxScanBytes":
        "Ceiling in bytes for that first-sight backfill; above it the scan seeks to "
        "the end, so the 10-second hook timeout stays safe. "
        "'/audit:usage --backfill' has no ceiling.",
    "usage.currency": "Currency label printed beside the rates. Default USD.",
    "usage.pricingAsOf":
        "The date the rate table below was accurate. Surfaced in the report and the "
        "Usage tab so a stale rate is visible rather than assumed — until you set it, "
        "both say the rates are undated rather than showing you a date you never "
        "chose.",
    "usage.bands":
        "Absolute thresholds that sort each task's spend into typical / high / "
        "outlier. Leave both empty and the bands calibrate from this project's own "
        "completed tasks (median and p90), which needs no guess to mean something. "
        "Set both to band by a real budget instead.",
    "journal.enabled":
        "Record every write to the plan and to this config in an append-only, "
        "hash-chained journal: who, when, what changed, and the state it left "
        "behind. Panel saves and edit-tool writes are recorded; shell writes cannot "
        "be, and show up instead as a document that changed with no row to explain "
        "it. Tamper-EVIDENT, not tamper-proof - `audit-journal.py verify` names an "
        "edited, deleted or reordered row, but nothing here can stop someone "
        "rewriting the whole file.",
    "journal.dir":
        "Where the monthly per-writer .jsonl files live. Empty keeps them beside "
        "the manifest, which is what lets one commit carry both the change and the "
        "record of it. One file per writer, so two sessions in two worktrees never "
        "conflict.",
    "journal.strictManifestState":
        "ask surfaces a confirmation prompt whenever an edit changes a task's or "
        "phase's status, completedAt, commit or attempts in the manifest. off "
        "(the default) leaves detection to the journal and the doctor. There is "
        "deliberately no deny: the pipeline completes tasks through the same "
        "edit tools this guard watches.",
    "usage.pricing":
        "Rates in this project's currency per MILLION tokens. Lookup is exact match, "
        "then longest matching prefix — so a dated model id resolves to its family — "
        "then the _default row. Leave a cell empty to keep the shipped rate shown in "
        "it.",
}

# The manifest levers the Composition tab edits. A separate dict on purpose: these
# are not config paths, and the coverage selftest above would have to special-case
# them if they lived in the same namespace.
COMPOSITION_HELP = {
    "reviewSkill": "Skill the reviewer agent invokes at phase sign-off. Empty = tests"
                   " are the only signer.",
    "buildCommands": "Named shell commands (typecheck / test / lint …) the pipeline "
                     "runs as gates.",
    "phaseReviewModel": "Model used for this phase's sign-off review.",
    "taskModel": "Model the executor uses to implement this task.",
    "taskSkills": "Skills the executor loads (via the Skill tool) before writing code "
                  "for this task.",
}

SETTINGS_GROUPS = (
    {
        "id": "paths",
        "title": "Paths & gate",
        # The concept page this card's decisions belong to, opened from the ⓘ on
        # its heading. Only two of the five have one: a group without a page gets
        # no hint rather than one that goes nowhere.
        "topic": "gate-tiers",
        "blurb": "Where the plugin looks for things, and how hard the plan-first gate "
                 "pushes. Paths are relative to this project directory. Leave a field "
                 "empty to use the default shown inside it — nothing is written for a "
                 "setting you have not changed.",
        "fields": (
            {"path": "manifestPath", "label": "The plan", "kind": "text"},
            {"path": "gitRoot", "label": "Git root", "kind": "text"},
            {"path": "stateDir", "label": "Hook state", "kind": "text"},
            {"path": "logsDir", "label": "Hook logs", "kind": "text"},
            {"path": "bypassKeyword", "label": "Bypass keyword", "kind": "text"},
            {"path": "trivialLineThreshold", "label": "Free first touch, in lines",
             "kind": "int", "min": 1},
            # `custom` (planGateField in panel.js): a select whose preset also
            # reads the LEGACY `enforce` flag, and whose change writes planGate
            # while deleting enforce — one statement of the gate's tier. The
            # enforce key itself keeps no control here; see _settings_exempt.
            {"path": "planGate", "label": "How hard the gate pushes",
             "kind": "custom"},
            {"path": "exemptGlobs", "label": "Paths the guards skip", "kind": "list",
             "placeholder": "glob…"},
        ),
    },
    {
        "id": "guards",
        "title": "Write guards",
        "blurb": "The rules that can REFUSE an edit rather than warn about it. Unlike "
                 "the plan gate these are never graded on evidence: logging an auth "
                 "token is wrong whether or not a plan exists.",
        "fields": (
            {"path": "bashWriteCheck.enabled",
             "label": "Warn on unplanned shell writes", "kind": "bool"},
            {"path": "guardEdits.tokenVars",
             "label": "Secrets never written to logs", "kind": "custom"},
            {"path": "secretPatterns.extra",
             "label": "Extra files treated as secrets", "kind": "custom"},
            {"path": "guardEdits.customRules", "label": "Your own banned patterns",
             "kind": "custom"},
        ),
    },
    {
        "id": "tdd",
        "title": "TDD reminder",
        "blurb": "A nudge, never a block. It prints one line when you change source "
                 "without touching a test, and then leaves you alone for the throttle "
                 "window.",
        "fields": (
            {"path": "tddReminder.enabled", "label": "Nudge when tests are untouched",
             "kind": "bool"},
            {"path": "tddReminder.throttleMinutes", "label": "Minutes between nudges",
             "kind": "number", "min": 0},
            {"path": "tddReminder.inProgressPolicy",
             "label": "While an audit task is running", "kind": "enum",
             "enum": "inProgressPolicy"},
            {"path": "tddReminder.sourceGlobs", "label": "What counts as source",
             "kind": "list", "placeholder": "glob…"},
            {"path": "tddReminder.testGlobs", "label": "What counts as a test",
             "kind": "list", "placeholder": "glob…"},
        ),
    },
    {
        "id": "usage",
        "title": "Usage & pricing",
        "blurb": "Token metering and the rate table every dollar in the Usage tab is "
                 "computed from. The ledger holds counts, model ids, timestamps, "
                 "branch and author — never prompt content.",
        "fields": (
            {"path": "usage.enabled", "label": "Meter token usage", "kind": "bool"},
            {"path": "usage.showCost", "label": "Show equivalent cost", "kind": "bool"},
            {"path": "usage.backfillOnFirstRun",
             "label": "Read transcripts already on disk", "kind": "bool"},
            {"path": "usage.ledgerDir", "label": "Ledger directory", "kind": "text"},
            {"path": "usage.authorMode", "label": "How the spender is recorded",
             "kind": "enum", "enum": "authorMode"},
            {"path": "usage.currency", "label": "Currency label", "kind": "text"},
            {"path": "usage.pricingAsOf", "label": "Rates accurate as of",
             "kind": "date"},
            {"path": "usage.maxScanBytes", "label": "Backfill ceiling, bytes",
             "kind": "int", "min": 0},
            {"path": "usage.bands", "label": "Cost bands", "kind": "custom"},
            {"path": "usage.pricing", "label": "Rates per million tokens",
             "kind": "custom"},
        ),
    },
    {
        "id": "journal",
        "title": "Audit trail",
        "topic": "journal",
        # No backticks in a blurb: it is rendered as text, not as markdown, and the
        # other four say their command names plainly for the same reason.
        "blurb": "An append-only, hash-chained record of every change to the plan "
                 "and to these settings. Tamper-EVIDENT, not tamper-proof: editing, "
                 "deleting or reordering a row breaks the chain and audit-journal.py "
                 "verify names it - but with no secret key to keep on your own "
                 "machine, nothing here can stop someone rewriting the whole file. "
                 "It is a smoke detector, not a vault.",
        "fields": (
            {"path": "journal.enabled", "label": "Record plan and config writes",
             "kind": "bool"},
            {"path": "journal.dir", "label": "Where the record is kept",
             "kind": "text", "placeholder": "beside the manifest"},
            {"path": "journal.strictManifestState",
             "label": "Confirm manifest state edits",
             "kind": "enum", "enum": "strictManifestState"},
        ),
    },
)


# --- settings paths + enums -------------------------------------------------
def _settings_paths():
    """Every config path the Settings form binds a control to."""
    return [f["path"] for g in SETTINGS_GROUPS for f in g["fields"]]


_VC = None


def _validate_config():
    """Load validate-config.py (once) via the shared loader.

    Own cache, not panel-server's `_cores()` — the loader's cache is keyed by
    realpath, so this and panel-server's `_cores()` share the SAME underlying
    module object the first time either loads it; this just avoids re-deriving
    it through panel-server, which this module must not import."""
    global _VC
    if _VC is None:
        _VC = _loader.load_script("validate-config.py",
                                   modname="audit_validate_config")
    return _VC


def _cfg_enums():
    """The enum choices, read off the validator that enforces them.

    Not a copy. `warn-always` was documented in four places, implemented in
    remind-tdd.py and rejected by validate-config, so following the documentation
    produced a config the panel refused to save; a hand-kept list of options in the
    UI is the same failure with one more place to forget."""
    vc = _validate_config()
    return {"inProgressPolicy": list(vc.IN_PROGRESS_POLICY),
            "authorMode": list(vc.AUTHOR_MODES),
            "strictManifestState": list(vc.STRICT_MANIFEST_STATE),
            "planGate": list(vc.PLAN_GATE_MODES)}


# --- selftest ---------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # --- Settings: the whole config, named by what it does ---------------------
    # The claim this tab makes is "here is the configuration". It was not true: the
    # form covered part of the config and nothing anywhere said which part, so the
    # `usage.*` block and four of five `tddReminder.*` keys were invisible on the one
    # surface built to make them legible.
    #
    # The expected set is DERIVED from validate-config's own key sets rather than
    # listed here. A hand-kept list would be a third place to forget a key — the
    # exact failure this chunk exists to fix, one level up.
    _vc = _validate_config()
    _containers = {"secretPatterns": _vc.KNOWN_SECRET, "guardEdits": _vc.KNOWN_GUARD,
                   "bashWriteCheck": _vc.KNOWN_BASHW, "tddReminder": _vc.KNOWN_TDD,
                   "usage": _vc.KNOWN_USAGE, "journal": _vc.KNOWN_JOURNAL}
    # `policy` is a root key with no control on this form, on purpose — the one
    # kind of exemption, and it is stated rather than silently subtracted. It is
    # not a setting with a value; it is a rule set whose meaning is the verdict it
    # produces for each installed capability, which is what /api/policy serves and
    # what the **Policy tab** renders, switch by switch. The exemption is pinned
    # below: it must name a key the validator actually knows, or it would silently
    # excuse nothing. (panel-server.py's own selftest confirms it is served by its
    # own endpoint — that needs the server's source, so it stays there.)
    #
    # `enforce` (v0.34 B1) is exempt for the opposite reason: it IS editable from
    # this form, through the planGate control — the select's preset reads the
    # legacy flag, and saving rewrites it as planGate while deleting enforce. A
    # second, dedicated checkbox would be two controls writing one gate, free to
    # disagree about it. The check below pins that the planGate control exists,
    # so this exemption cannot outlive the control that justifies it.
    _settings_exempt = {"policy", "enforce"}
    _expected = {k for k in _vc.KNOWN_ROOT
                 if k not in _containers and k not in _settings_exempt}
    for _parent, _keys in _containers.items():
        _expected |= {"%s.%s" % (_parent, k) for k in _keys}
    check("the Settings exemption names a real config key - an exemption for a key "
          "the validator has never heard of excuses nothing and hides the next one",
          _settings_exempt <= _vc.KNOWN_ROOT)
    # The container map above IS hand-kept — there is no machine link from a
    # top-level key to the set of keys inside it — so the one thing it can get
    # wrong is naming a container the validator has never heard of. Then the
    # derived set would keep expecting `journal.*` after `journal` was dropped from
    # KNOWN_ROOT, and this whole check would agree with itself about a key the
    # hooks ignore.
    check("every container the form groups is a real top-level key",
          set(_containers) <= _vc.KNOWN_ROOT)
    _bound = set(_settings_paths())
    check("Settings binds a control to EVERY key the validator accepts - the "
          "missing ones were the whole usage block and most of tddReminder",
          _bound == _expected)
    if _bound != _expected:
        print("     missing: %s" % sorted(_expected - _bound))
        print("     unknown: %s" % sorted(_bound - _expected))
    check("every bound setting has help text, and no help text names a key the "
          "validator does not know",
          set(FIELD_HELP) == _bound)
    check("no path is bound twice (a duplicate would render two controls writing "
          "the same key)", len(_settings_paths()) == len(_bound))
    # Named by what they DO, with the key beside them. Every heading used to BE a
    # JSON path, uppercased by the h2 rule: "GUARDEDITS.TOKENVARS". That reads as a
    # config dump and assumes the schema the reader came here to learn.
    for _g in SETTINGS_GROUPS:
        for _f in _g["fields"]:
            check("%r is labelled %r rather than shown as a bare key"
                  % (_f["path"], _f["label"]),
                  bool(_f["label"]) and _f["label"] != _f["path"]
                  and not _f["label"][0].islower())
    check("the groups are the decisions the config makes, not one list",
          tuple(g["id"] for g in SETTINGS_GROUPS)
          == ("paths", "guards", "tdd", "usage", "journal")
          and all(g["blurb"] for g in SETTINGS_GROUPS))
    check("the audit trail's card states the limit of the claim, where someone "
          "deciding whether to rely on it will read it",
          "not tamper-proof" in dict(
              (g["id"], g["blurb"]) for g in SETTINGS_GROUPS)["journal"])
    check("no blurb writes markdown - they are rendered as text, so a backtick "
          "reaches the screen as a backtick",
          not any("`" in g["blurb"] or "**" in g["blurb"]
                  for g in SETTINGS_GROUPS))

    # --- the write allow-lists ---------------------------------------------------
    check("the meta form keys exclude the api-only ones",
          set(_META_FORM_KEYS) == set(_META_KEYS) - set(_META_API_ONLY))
    check("areas is meta-only and api-only, not a phase or task key",
          "areas" in _META_KEYS and "areas" in _META_API_ONLY
          and "areas" not in _PHASE_KEYS and "areas" not in _TASK_KEYS)

    # The enforce exemption's justification, pinned: the planGate control is on
    # the form, custom-rendered (planGateField owns the legacy-flag rewrite).
    _pg = [f for g in SETTINGS_GROUPS for f in g["fields"]
           if f["path"] == "planGate"]
    check("enforce is exempt BECAUSE planGate's control edits it - that control "
          "must exist, custom, or the exemption excuses a hole",
          len(_pg) == 1 and _pg[0]["kind"] == "custom")

    # --- _cfg_enums --------------------------------------------------------------
    check("the enum choices ARE the validator's tuples, not a copy of them",
          set(_cfg_enums()["inProgressPolicy"]) == set(_vc.IN_PROGRESS_POLICY)
          and set(_cfg_enums()["authorMode"]) == set(_vc.AUTHOR_MODES))
    check("the planGate tiers reach the form from the validator's own tuple, "
          "in escalation order",
          _cfg_enums()["planGate"] == list(_vc.PLAN_GATE_MODES))
    check("_cfg_enums() is JSON-serializable (panel-server bakes it into UI_HTML "
          "with json.dumps)", json.dumps(_cfg_enums(), sort_keys=True))

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


# --- cli --------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    print(__doc__.strip())
