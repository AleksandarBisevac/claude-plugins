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

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__panel_settings.py`, byte-identical labels and all -
see `plugins/audit/tests/_harness.py`.
"""
import os
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

import _config_rules  # noqa: E402  (the rules that decide what this form may offer)

# --- key allow-lists (composition write path) -------------------------------
# Fields the composition patch is allowed to touch — the security allow-list.
# `areas` is here so the registry can be written through the ONE write path that
# takes the lock, validates, journals and patches only the index (meta lives on the
# index; a registry save must never rewrite a phase shard). /api/areas is a thin
# front door onto it rather than a second writer.
_META_KEYS = ("reviewSkill", "buildCommands", "branch", "areas", "ado")
# ...of which these have no control on the Composition form: they are written by
# their own endpoint, so the confirm dialog's client-side change list must NOT
# enumerate them or it would compute a row for a field nobody can edit there. The
# selftest derives the client's list from this pair rather than trusting the two
# to be kept in step by hand. (`ado` — the connector card — computes its own
# dotted rows and saves via PUT /api/ado, mirroring `areas`.)
_META_API_ONLY = ("areas", "ado")
_META_FORM_KEYS = tuple(k for k in _META_KEYS if k not in _META_API_ONLY)
# `priority` joins `reviewModel` because it is COMPOSITION, not structural CRUD:
# the same class as the per-task `model`/`skills` the panel already writes, so the
# panel's boundary does not move. What legality means is NOT decided here - the
# write path asks `_priority.tier_one_holder()`, the same function
# `set-priority.py` asks, so the UI cannot promise a write the CLI refuses.
# `adoParent` joins them for the same reason and with ONE difference that the
# write path spells out: it is the only key here whose `null` is a VALUE rather
# than a clear, so it is stored and never pruned. What a legal declaration is
# comes from `_ado_parent.declaration_findings`, the function the manifest
# validator asks - the panel cannot promise a parent the CLI would refuse.
_PHASE_KEYS = ("reviewModel", "priority", "adoParent")
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
    "priority.maxTier":
        "The highest tier the phase-priority control offers, and the highest one "
        "set-priority.py suggests. ADVISORY - nothing is clamped to it: a phase "
        "pinned above it keeps the tier it was given and simply sorts after every "
        "tier at or under the maximum. Priority re-sorts work that is ALREADY "
        "ready; it never makes an unready task ready and never skips a dependency.",
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
    # The branch-naming card (meta.branch, saved on the Composition form):
    "branchConvention": "How a phase's branch is named. Empty = the meta.branchPrefix "
                        "shape, `audit/<phase>-<slug>`, which is what every existing "
                        "plan already produces.",
    "branchTemplate": "Placeholders: {type} {initials} {phase} {slug}. One that "
                      "resolves to nothing disappears together with the separator "
                      "behind it, so an absent {initials} gives feature/p2-x, never "
                      "feature//p2-x.",
    "branchDefaultType": "The {type} for a phase that neither sets branchType nor "
                         "derives one. A phase from bugs[] derives 'bugfix' regardless.",
    "branchTypes": "The types a phase may name. This list is ALSO where the "
                   "pre-approved git globs come from, so a type missing here costs a "
                   "confirmation prompt on every branch operation that uses it.",
    "branchInitials": "Overrides the initials taken from your git user.name. Set it "
                      "when that name does not initial usefully; leave it empty to use "
                      "git's.",
    "branchSlugMax": "Cap on the slug taken from the phase title.",
    "phaseReviewModel": "Model used for this phase's sign-off review.",
    "phasePriority": "Which phase the pipeline reaches for first among the tasks "
                     "that are ALREADY ready. It never makes an unready task "
                     "ready and never skips a dependency: a pinned phase still "
                     "waiting on something is skipped, and /audit:status says so. "
                     "Tier 1 is unique; higher tiers are shared. No priority means "
                     "unprioritised - the phase sorts after every pinned one and "
                     "keeps its written position. Display order never changes.",
    "phaseAdoParent": "The board work item THIS phase hangs under, overriding "
                      "meta.ado.parentWorkItem for it. Three answers, and they "
                      "differ: leave it on the fallback, name a parent (the "
                      "menu offers whatever /audit:sync parents last cached, "
                      "and any id can be typed), or say 'none' - which hangs "
                      "the phase under nothing even when the fallback is set, "
                      "and is a declaration rather than an oversight. A parent "
                      "is applied at CREATE only: changing it here does not "
                      "re-parent an item that is already on the board.",
    "taskModel": "Model the executor uses to implement this task.",
    "taskSkills": "Skills the executor loads (via the Skill tool) before writing code "
                  "for this task.",
    # The ADO connector card (meta.ado, saved via PUT /api/ado):
    "adoConnector": "Azure DevOps connector config for /audit:sync and the "
                    "orchestration echo. Empty = nothing syncs.",
    "adoEnabled": "Master switch. Off stops sync push/pull and the echo; links are "
                  "kept and status still reports them.",
    "adoEcho": "On (the default): the orchestrator updates already-linked work items "
               "on task done/blocked/reopen and phase sign-off. Never creates items.",
    "adoPhaseWorkItems": "On (the default): push creates one PBI per phase and "
                         "parent-links its task/bug items under it.",
    "adoTypes": "Work-item type names: bug, task, and pbi (empty pbi = auto-detect "
                "at the first phase push).",
    "adoTag": "Provenance tag stamped on every pushed/echoed item. Empty = "
              "'audit-plugin'; a per-repo value pairs with pull tags on shared "
              "sprints; 'no tag' writes null. Always merged into the item's "
              "existing tags, never replacing them.",
    "adoStateMap": "Manifest status → ADO state per transition. Empty cell = the "
                   "built-in default; 'never move' = the team moves that card by hand.",
    "adoRemainingWork": "Remaining Work written on a task's done move (default 0). "
                        "'Don't touch' = the field is never written.",
    "adoComments": "Generated work-item comments on blocked / completed transitions. "
                   "Both off by default.",
    "adoSprint": "Resolve the team's CURRENT iteration at push time and stamp items "
                 "into it. Empty = the static iteration path (if any).",
    "adoPull": "Which of a shared sprint's items belong to THIS repo: area path and/or "
               "tags. With neither, sprint pull refuses to import blind.",
    "adoIdentityMap": "Ledger identity (git email/name) → ADO identity (email/UPN). "
                      "Advisory: push proposes assignees, pull labels reporters.",
    # The template editor edits the draft object DIRECTLY, never through
    # setPath/delPath: an ADO reference name carries dots, and a dotted-path
    # writer would shred `Microsoft.VSTS.Common.Activity` into four levels.
    # `meta.ado` is still saved wholesale from a deep copy of the file, so a
    # template written by hand survives every save this card makes.
    "adoFields": "Extra fields this project supplies per work item type, merged into "
                 "the create payload before the conformance gate grades it - what "
                 "gets an item past a board that requires an Activity or an estimate. "
                 "Values are literals; a field the connector already maps, or one ADO "
                 "reports as read-only, is refused when the manifest is validated.",
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
    {
        "id": "priority",
        "title": "Execution order",
        "blurb": "Which phase the pipeline reaches for first among the work that is "
                 "already ready. A priority never makes an unready task ready and "
                 "never skips a dependency - a pinned phase that is still waiting is "
                 "skipped, and the status output says so rather than going quiet.",
        "fields": (
            {"path": "priority.maxTier", "label": "Highest tier offered",
             "kind": "int", "min": 1},
        ),
    },
)


# --- settings paths + enums -------------------------------------------------
def _settings_paths():
    """Every config path the Settings form binds a control to."""
    return [f["path"] for g in SETTINGS_GROUPS for f in g["fields"]]


def _validate_config():
    """`_config_rules` — the module that decides what this form may offer.

    A plain import now, and the memo it used to need is gone with it. This was
    `_loader.load_script("validate-config.py")`, which made a LAYER 2 module
    depend on a layer 7 entry point: the deepest of the seventeen inversions
    `_deps.KNOWN_LAYER_DEBT` recorded. The rules moved to layer 2 and this module
    moved up to layer 3, so the edge points down and the lint can see that it
    does. Still a function, because `_cfg_enums` reads it as "the module that
    enforces these" and the indirection is where that sentence lives."""
    return _config_rules


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


# --- cli --------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_panel_settings.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__panel_settings.py - run that file "
              "instead.")
        raise SystemExit(0)
    print(__doc__.strip())
