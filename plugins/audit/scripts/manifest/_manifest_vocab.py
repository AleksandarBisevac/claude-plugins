#!/usr/bin/env python3
"""
The manifest's vocabulary, and the four shape checks every level of it shares.

Split out of `_manifest_rules.py`, which was 1,406 lines, and cut here because
this is the one piece with no rule in it: an enumeration of the words the
orchestrator understands, plus the small checks that are asked of a phase, a
task and a bug alike. Four modules need them (`_manifest_phases`,
`_manifest_ado`, `_manifest_crossrefs` and `_manifest_rules` itself), and a
vocabulary copied into four files is four vocabularies that will disagree the
first time one of them learns a word.

LAYER 1, AND THAT IS WHY `TERMINAL` IS NOT HERE. Every other name below is a
literal or a `re` pattern, so this module reaches nothing but `_output` and can
sit at the floor where all four consumers can import it. `TERMINAL` is
`_manifest_io`'s (layer 1 as well), so holding it here would put this module at
layer 2 and push `_manifest_rules` past the layer its own consumers leave free.
It stays re-exported from `_manifest_rules`, where the phase walk reads it.

Unknown keys are WARNINGS, never findings: `additionalProperties` stays
permissive for forward and backward compatibility, so the only honest thing to
do with a key nobody recognises is to name it and carry on.

THE `KNOWN_*` SETS ARE CHECKED AGAINST THE SCHEMA, NOT TRUSTED. Every one of
them restates vocabulary `schema/audit-plan.schema.json` already owns, so
`SCHEMA_ANCHORS` records where each set lives in that document and `OFF_SCHEMA`
records, with a reason each, the thirteen keys that deliberately have no schema
counterpart. `_help.schema_vocab_drift()` compares the two and names what
disagrees. IF YOU ADD A KEY HERE, the schema is where it has to exist first; if
it must not, it belongs in `OFF_SCHEMA` with the reason written down. The
comparison lives in `_help` rather than here because the tree's one schema walk
does - see the SCHEMA_ANCHORS comment for why that is a layer fact and not a
preference. `SUBSET_ANCHORS` and `INLINE_ANCHORS` say the same thing about the
other two shapes a vocabulary takes here: a RECOMMENDED subset, checked for
containment, and a nested level whose vocabulary is a set literal at its
`_unknown_keys()` call rather than a set on this module at all.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__manifest_vocab.py` - see
`plugins/audit/tests/_harness.py`.
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


# --- vocabulary ------------------------------------------------------------------
# Two of these are terminal: `done` (it landed) and `cancelled` (it will not be
# done, and that is an answer - see the schema's $defs/status for why the word is
# `cancelled` and not `deprecated`). The tuple naming that pair is `_manifest_io`'s
# `TERMINAL`, re-exported from `_manifest_rules`: a phase signs off when every task
# is finished, and a claim on a finished phase is stale whichever way it finished.
STATUS = ("pending", "in_progress", "blocked", "done", "cancelled")
TESTS_MODE = ("tdd", "regression", "gate-only")
RISK = ("low", "med", "high", None)
BUG_STATUS = ("open", "triaged", "in_progress", "fixed", "wontfix")
BUG_ID_RE = re.compile(r"^BUG-\d+$")
# v0.33 proposals lifecycle (/audit:init park + /audit:propose). The vocabulary
# is enforced only on payload-bearing proposals — legacy free-form entries
# (pre-0.33 wrote whatever it liked here) stay warnings-at-most.
PROPOSAL_STATUS = ("proposed", "materialized", "dropped")
PROP_ID_RE = re.compile(r"^PROP-\d+$")
# v0.44 `ado.origin`: where a linked work item came from. TWO values, because only
# two code paths write one — a push CREATE and a pull import — and a value nothing
# writes is a value nothing tests. ABSENT is the third state and is deliberately
# not spelled here: it means unrecorded, every surface says so, and defaulting it
# to "created" would put this plugin's name on a card somebody else made. The
# vocabulary lives at this layer because `_ado_drift` (L2) and this validator both
# need it, and a second tuple over there would be a second answer.
ADO_ORIGIN_CREATED = "created"
ADO_ORIGIN_IMPORTED = "imported"
ADO_ORIGIN = (ADO_ORIGIN_CREATED, ADO_ORIGIN_IMPORTED)

# Known keys per level. Unknown keys are WARNINGS (typo catcher), never findings
# — additionalProperties stays permissive for forward/backward compatibility.
# The "legacy" names below were removed from the schema in v0.3.0 but remain
# silently accepted in pre-0.3 manifests.
KNOWN_ROOT = {"$schema", "meta", "phases", "fileIndex", "bugs", "deferred",
              "proposals"}
KNOWN_META = {"version", "repo", "title", "createdISO", "node",
              "developmentBranch", "branchPrefix", "gitRoot", "reviewSkill",
              # v0.44: branch-naming convention. Supersedes branchPrefix, which
              # stays valid — an existing manifest must keep producing the same
              # names. _check_branch_naming reads meta.branch first.
              "branch",
              "runtimeBoot", "nodePreamble", "commit", "buildCommands", "ado",
              # report rendering (render-report.py): narrative summary box +
              # custom output-file basename. Neither affects orchestration.
              "reportSummary", "reportBasename",
              # v0.28: the registry a phase's `area` tag can name (_areas.py).
              # Registration is optional in both directions — see _check_areas.
              "areas",
              # token metering, read by the COMMANDS (the hooks read their own
              # copy from .claude/audit.config.json — the plugin's standing split):
              # ledgerDir, showCost, pricingAsOf, pricing.
              "usage",
              # The rest are NOT in the schema, and the reason for each is in
              # `OFF_SCHEMA` below rather than here - one copy, and a lint that
              # goes red when it stops being true. (The comment that stood here
              # said `audit.md` reads workspaceRoot as a fallback; the file has
              # been `reference/orchestrator.md` for some time, which is what an
              # unchecked reason costs.)
              "notes", "baseCommit", "workspaceRoot",
              "signOffChecklist", "autoMode", "modelPolicy", "testPolicy",
              "reviewPolicy", "skillsPolicy", "statusLegend"}
# Keys inside meta.ado (the connector config). Enumerated since the v2 connector
# so a typo like `identitymap` or `statemap` draws a did-you-mean warning instead
# of silently disabling the feature it was meant to configure.
KNOWN_ADO = {"organization", "project", "areaPath", "iterationPath", "types",
             "identityMap",
             # connector v2:
             "enabled", "echo", "phaseWorkItems", "stateMap", "onComplete",
             "comments", "sprint", "pull",
             # ENH-1: personalizable provenance tag (default "audit-plugin";
             # null = no tag):
             "tag",
             # U4: what a work item must look like to BELONG on this board -
             # required fields, description skeleton, tag vocabulary, parent.
             # A property of the board, so absent means "no standard to meet".
             "conventions",
             # U4: the EXISTING work item audit phases hang under, so the work
             # lands inside a team's backlog rather than beside it.
             "parentWorkItem"}
# Keys inside meta.branch (the naming convention). Enumerated for the same reason
# meta.ado is: a typo like `slugMaxLen` or `defaulttype` would otherwise be a
# convention that silently never applies.
KNOWN_BRANCH = {"template", "defaultType", "types", "initials", "slugMaxLength"}

KNOWN_PHASE = {"id", "title", "status", "model", "blockedBy", "docs",
               "description", "desiredOutcome", "testGate", "baseRef", "branch",
               "mergedAt", "review", "reviewFindings", "summary", "tasks",
               # v0.44: this phase's own fork/merge target and branch type.
               # parentBranch resolves phase -> meta.developmentBranch, the same
               # chain reviewSkill uses; branchType names the {type} segment.
               "parentBranch", "branchType",
               # v0.16: per-phase review skill override + app/team area tag
               "reviewSkill", "area",
               # connector v2: phase-level work item link, written by /audit:sync
               # when meta.ado.phaseWorkItems is true:
               "ado",
               # v0.19: optional spend budget for this phase, in USD. Optional on
               # purpose — most phases will not carry one, and the surfaces render
               # an absent budget as "—" rather than as 0% or 100%.
               "budgetUSD",
               # v0.15 sharded layout: an index stub points at its shard file and
               # may carry an optimistic parallel-run claim (both surface on the
               # assembled phase via _manifest_io):
               "shard", "claim",
               # not in the schema; reason in `OFF_SCHEMA` below:
               "signOff"}
# Recommended keys on a parallel-run claim — soft: a claim that omits one draws a
# warning from `_manifest_phases._check_claim`, never a finding. NARROWER than the
# schema's `claim` properties on purpose (`at` is written BY a claim, not asked OF
# one), so it answers to `SUBSET_ANCHORS` below — containment, not coverage.
CLAIM_KEYS = ("sessionId", "host", "branch")
KNOWN_TASK = {"id", "title", "status", "model", "skills", "blockedBy",
              "dependsOn", "files", "docs", "description", "tests", "outcome",
              "commit", "attempts", "maxAttempts", "startedAt", "completedAt",
              "risk", "verifiedBy", "bugId", "ado",
              # workstream B: written by /audit:task move -- {id, phase, at},
              # the durable half of the mapping (the other half is the
              # journal's task.move row):
              "movedFrom",
              # not in the schema; reason in `OFF_SCHEMA` below:
              "details"}
KNOWN_BUG = {"id", "title", "status", "severity", "reportedAt", "reportedBy",
             "description", "repro", "expected", "actual", "files", "taskId",
             "fixedIn", "notes", "ado"}
KNOWN_PROPOSAL = {"id", "name", "status", "origin", "scope", "benefit",
                  "technicalNote", "openQuestions", "createdISO", "payload",
                  "materializedAs", "materializedAt",
                  # The drop pair, mirroring the materialize pair. `notes` was
                  # tolerated OFF-SCHEMA for as long as `/audit:propose drop` was
                  # its only writer; it is declared in the schema now that the
                  # panel can drop too, and the validator requires it once a
                  # proposal is dropped rather than trusting prose to ask.
                  "notes", "droppedAt"}


# --- the schema these sets answer to ---------------------------------------------
# Every `KNOWN_*` set above restates vocabulary that `schema/audit-plan.schema.json`
# already defines, and until this section existed NOTHING compared the two: the
# schema could gain a property and the set beside it stayed behind in silence, which
# is a warning-on-a-real-key for as long as nobody noticed.
#
# LINTED, NOT DERIVED. Three reasons, in order of weight:
#
# 1. THE SETS ARE DELIBERATELY WIDER THAN THE SCHEMA. Thirteen keys above have no
#    schema counterpart at all — `OFF_SCHEMA` names each one and says why. They are
#    legacy or tolerated spellings the schema dropped in v0.3.0 and the orchestrator
#    still accepts in a pre-0.3 manifest. Derivation can express "equal to the
#    schema"; it cannot express "wider". A derived set would either start warning
#    about `signOffChecklist` on every 0.2.0 manifest that still validates, or need
#    this same hand-written table unioned back on — at which point the literal is
#    back and only harder to read.
# 2. THE ONE SCHEMA WALK IN THE TREE SITS A LAYER ABOVE THIS MODULE. `_help.fields()`
#    already chases `$ref`, `$defs`, `items` and `additionalProperties`, and `_help`
#    is at layer 2. This module is at layer 1 because four layer-2 modules import it,
#    so importing `_help` here is an upward edge `_deps.layer_violations()` fails —
#    and the alternative, a second walk written here, is the duplication being
#    removed rather than deleted. So the COMPARISON lives with the walk, in
#    `_help.schema_vocab_drift()`, and this module states the two things it is the
#    right place to state: WHERE in the schema each set lives, and WHICH of its keys
#    the schema does not have.
# 3. Deriving costs about 0.43 ms per process — read 0.023 + `json.loads` 0.122 +
#    `_help.fields()` 0.285, the mean of 200 in-process runs over the 46,220-byte
#    `schema/audit-plan.schema.json` — which measured end to end is 1.2-3.2 ms of a
#    24-33 ms `import _manifest_vocab` process. This is the WEAKEST of the three and
#    is recorded so nobody re-argues it from the usual premise: nothing on the
#    per-tool-call hook path imports this module (hooks resolve `_manifest_io.py` by
#    basename through `_config.find_script()` and never reach here), so the cost
#    would land on `validate-manifest.py` and the panel, not on every edit.
#
# `SCHEMA_ANCHORS` says where each set is defined, spelled as the dotted path
# `_help.fields()` produces and `_help.COMPOSITION_PATHS` already uses; `""` is the
# document root. A property the schema gains at one of these anchors, and this module
# does not have, is a NAMED failure out of `_help.schema_vocab_drift()`.
#
# `CLAIM_KEYS` IS NOT ANCHORED HERE, AND THAT IS NOT AN EXEMPTION. It is not a
# known-key set at all: it is the RECOMMENDED subset `_manifest_phases._check_claim`
# warns about when a claim omits one, so being NARROWER than the schema is the rule
# working rather than drift. Holding it to "covers the anchor" would fail a correct
# set, and a lint that fails its own remedy is a lint people route around. It answers
# to `SUBSET_ANCHORS` below instead, which asks the other question.
SCHEMA_ANCHORS = (
    ("KNOWN_ROOT", ""),
    ("KNOWN_META", "meta"),
    ("KNOWN_ADO", "meta.ado"),
    ("KNOWN_BRANCH", "meta.branch"),
    ("KNOWN_PHASE", "phases[]"),
    ("KNOWN_TASK", "phases[].tasks[]"),
    ("KNOWN_BUG", "bugs[]"),
    ("KNOWN_PROPOSAL", "proposals[]"),
)

# The keys the schema does NOT define, one reason each — because an exemption list
# without reasons is where a lint goes to die, and because these were prose comments
# above until now, which is to say they were unchecked. `_help.schema_vocab_drift()`
# reports an entry whose key the schema has since grown, an entry naming a key the
# set no longer holds, and an empty reason: a stale exemption is a hole in the lint,
# not a tidy detail.
OFF_SCHEMA = {
    "KNOWN_META": {
        # CHANGELOG v0.3.0, "never-read meta fields removed ... legacy manifests
        # still validate". The orchestrator has never read any of these seven.
        "signOffChecklist": "legacy: removed from the schema in v0.3.0 (never read); "
                            "a pre-0.3 manifest still carries it and still validates",
        "autoMode": "legacy: removed from the schema in v0.3.0 with the undefined "
                    "'auto mode' gate; high-risk confirmation is unconditional now",
        "modelPolicy": "legacy: removed from the schema in v0.3.0 (never read); "
                       "model choice is per-task `model` and per-phase `review.model`",
        "testPolicy": "legacy: removed from the schema in v0.3.0 (never read); "
                      "the test contract is per-task `tests` and per-phase `testGate`",
        "reviewPolicy": "legacy: removed from the schema in v0.3.0 (never read); "
                        "review is `meta.reviewSkill` and the phase `review` object",
        "skillsPolicy": "legacy: removed from the schema in v0.3.0 (never read); "
                        "skills are per-task `skills` and per-area `areas[].skills`",
        "statusLegend": "legacy: removed from the schema in v0.3.0 (never read); "
                        "the statuses are this module's STATUS tuple",
        # docs/audit/phases/P5.json: a 0.2.0-generated manifest threw 21 warnings
        # under 0.6.0 on these three plus task.details, and they were tolerated
        # rather than schema'd because nothing reads them.
        "notes": "tolerated: pre-0.3 /audit:init wrote a free-form note here; "
                 "informational, never read, and not worth a schema field",
        "baseCommit": "tolerated: pre-0.3 /audit:init wrote the starting commit "
                      "here; the orchestrator reads meta.commit and phase.baseRef",
        "workspaceRoot": "supported fallback, not a defect: the 0.2.0 name for "
                         "gitRoot, and reference/orchestrator.md still says to fall "
                         "back to it when meta.gitRoot is absent — warning on it "
                         "would fire on a manifest the product deliberately supports",
    },
    "KNOWN_PHASE": {
        "signOff": "legacy: removed from the schema in v0.3.0 alongside the meta "
                   "policy fields; the phase `review` object replaced it",
    },
    "KNOWN_TASK": {
        "details": "tolerated: pre-0.3 /audit:init wrote a free-form note here "
                   "(docs/audit/phases/P5.json); informational, never read",
    },
}

# --- the recommended subsets, which answer a DIFFERENT question -------------------
# `SCHEMA_ANCHORS` asks for COVERAGE: the set holds every property the schema
# declares at the anchor, and every key it holds beyond them is in `OFF_SCHEMA` with
# a reason. `SUBSET_ANCHORS` asks only for CONTAINMENT, in one direction: every key
# in the set is a property the schema declares at the anchor, and the schema is free
# to declare more. That is not a weaker version of the same lint, it is the only
# shape a RECOMMENDED subset can be checked with — a set whose whole job is to name
# some of a level's keys would fail a coverage check while behaving perfectly.
#
# The one member today is `CLAIM_KEYS`, and the thing it protects is at
# `_manifest_phases._check_claim`: `missing = [k for k in CLAIM_KEYS if not
# claim.get(k)]`. A key misspelled in this tuple is asked of no claim and reported
# by nothing — the warning does not become wrong, it stops existing for that key —
# which is exactly the failure a set of literals restating schema vocabulary invites.
# `_help.schema_subset_drift()` is the comparison; it lives with the schema walk for
# the reason `SCHEMA_ANCHORS` gives above, and reports a key the schema does not
# declare, an anchor that declares nothing, an empty set, and a subset nothing
# anchors. What it CANNOT see is written on that function.
#
# THERE IS NO `KNOWN_CLAIM`, AND THE REASON IS NOT THAT `claim` IS SPECIAL — it is
# not. It is an object with four declared properties and `additionalProperties:
# true`, exactly like `meta.ado`, so an unrecognised key inside a claim really does
# go unwarned today while every anchored level catches its typos. That gap is real;
# it is stated here rather than left to be rediscovered.
#
# What differs is WHERE closing it lands. A `KNOWN_*` set here has exactly one kind
# of consumer — an `_unknown_keys()` call — and all seven have one
# (`_manifest_rules._check_meta` for the root and `meta`, `_manifest_ado.check_ado_meta`
# for `meta.ado`, `_manifest_phases` for the phase and the task, `_manifest_crossrefs`
# for the bug and the proposal). A claim's would sit in `_check_claim`, beside the
# loop above. Every other NESTED object in the tree keeps its vocabulary inline at
# that call rather than here, and `INLINE_ANCHORS` below is the list of which levels
# those are — the only list, because the one this comment used to carry spelled three
# of those literals out and was already missing a fourth on the day it was written.
# This module exists for the vocabularies MULTIPLE modules share, which is this
# file's own stated criterion, and a claim has one reader.
#
# So the missing warning is a missing CALL, not a missing set, and adding the set on
# its own would be worse than leaving it out: `_help.vocab_sets()` reads every
# `KNOWN_*` attribute off this module, so a `KNOWN_CLAIM` would be anchored,
# drift-checked and green from the moment it appeared while an unknown key in a claim
# stayed exactly as silent. Coverage in appearance only is the failure `OFF_SCHEMA`'s
# written reasons exist to prevent.
#
# NOTHING PINS ITS ABSENCE, deliberately. Adding `KNOWN_CLAIM`, anchoring it at
# `phases[].claim` in `SCHEMA_ANCHORS`, and giving `_check_claim` the
# `_unknown_keys()` call to read it is the remedy — and the machinery already forces
# it to be done whole, because `mv20` fails a `KNOWN_*` set `SCHEMA_ANCHORS` does not
# anchor. A case asserting `KNOWN_CLAIM` does not exist would forbid its own fix.
SUBSET_ANCHORS = (
    ("CLAIM_KEYS", "phases[].claim"),
)

# --- the nested vocabularies, which are LITERALS AT THEIR CALL SITE ---------------
# The two tables above both assume a NAMED set on this module: `_help.vocab_sets()`
# and `vocab_subsets()` read them off it by attribute name, so a vocabulary that is
# not an attribute anywhere is invisible to both. The `meta.ado` sub-objects are
# exactly that shape. Each is checked against a set literal written straight into the
# `_unknown_keys()` call in `_manifest_ado.py`, each restates properties
# `schema/audit-plan.schema.json` declares, and until this table existed nothing
# compared any of them — the same class `SCHEMA_ANCHORS` closed for the seven
# top-level sets, one nesting level down and therefore untouched by it.
#
# COVERAGE, NOT CONTAINMENT, AND THE CONSUMER SETTLES IT PER LEVEL. Every literal
# here is the `known` argument of `_unknown_keys(obj, known, where, warnings)`, which
# warns about any key NOT in it — the same consumer the seven `KNOWN_*` sets have,
# and the reason they are coverage-shaped. A property the schema declares and the
# literal omits makes the validator warn about a real key; a key in the literal the
# schema does not declare is a typo that both widens the vocabulary and silently
# takes the warning for the key it was meant to be. Both directions cost something,
# so both are checked. `CLAIM_KEYS` is containment-shaped because its consumer asks a
# different question (`missing = [k for k in CLAIM_KEYS if not claim.get(k)]`, a
# subset by design), and no literal here has any consumer other than the one call it
# is written into — an argument cannot acquire a second reader.
#
# WHY THE LITERALS DID NOT SIMPLY MOVE UP HERE, which is the obvious alternative.
# `SCHEMA_ANCHORS` would not have needed a single change to take them:
# `_help._direct_children()` is path-agnostic, so `("KNOWN_ADO_SPRINT",
# "meta.ado.sprint")` resolves against the existing walk today. The cost is not
# machinery, it is what the vocabulary would then be:
#
#   * A named set here does not REPLACE a literal, it joins it. `_manifest_ado` would
#     have to be edited to read the name, and until that lands the tree carries two
#     spellings of each vocabulary with nothing reconciling them — while
#     `_help.vocab_sets()` anchors and green-lights the copy on this module and the
#     literal the validator actually passes drifts freely. Coverage in appearance
#     only is the failure `OFF_SCHEMA`'s written reasons exist to prevent.
#   * This module's criterion is the vocabularies MULTIPLE modules share; it is why
#     `TERMINAL` is not here. Each of these has one reader.
#   * A hand-written set is only as complete as somebody's memory. The report that
#     opened this named `onComplete`, `sprint` and `pull`; the scan that reads the
#     calls found `comments` as well.
#
# So the DATA is the list of levels whose vocabulary is a literal, and the COMPARISON
# reads that literal where the validator reads it — `_help.schema_inline_drift()`
# parses `scripts/`, takes every `_unknown_keys(obj, {…}, "dotted.path", w)` whose
# set and whose path are both literals, and holds each to the schema at that path.
#
# THIS TABLE IS NOT REDUNDANT WITH THE SCAN, and that is its whole job: a scan alone
# cannot tell "clean" from "there is nothing left to look at". A path declared here
# with no call site found is a NAMED failure, and a literal found at a path not
# declared here is the other one, so neither the check nor the code it guards can
# shrink in silence. There is no exemption table because no level needs one today,
# and none can be needed quietly: dropping an entry to escape the check reports the
# call site as undeclared instead.
INLINE_ANCHORS = (
    "meta.ado.onComplete",
    "meta.ado.comments",
    "meta.ado.sprint",
    "meta.ado.pull",
)


# --- the shape checks every level shares -----------------------------------------
def _strip_line_suffix(entry):
    """`a/b.tsx:291-294,308` -> `a/b.tsx` (same rule as hooks/_config.py)."""
    return str(entry).replace("\\", "/").split(":", 1)[0]


def _safe_list(val):
    """A blockedBy/dependsOn/tasks value coerced to a list for safe iteration.
    A non-list (notably a bare string, which must NEVER be iterated
    per-character) becomes []. The wrong-type diagnostic is emitted by the
    caller — this only keeps `validate()` from raising on hostile shapes."""
    return val if isinstance(val, list) else []


def _require_fields(obj, where, findings):
    ok = True
    for key in ("id", "title", "status"):
        if not obj.get(key):
            findings.append("%s: missing required '%s'" % (where, key))
            ok = False
    return ok


def _check_ado(obj, where, findings):
    """`ado` (written by /audit:sync) must be null or {id: int, url, lastSyncedAt}."""
    if "ado" not in obj:
        return
    ado = obj.get("ado")
    if ado is None:
        return
    if not isinstance(ado, dict):
        findings.append("%s: ado must be an object or null, got %s"
                        % (where, type(ado).__name__))
        return
    # `isinstance(x, bool)` first, because `bool` subclasses `int` and `true`
    # would otherwise be accepted as a work-item id (F15). `meta.version` already
    # excluded it by name, so the tree disagreed with itself about one question.
    if "id" in ado and (isinstance(ado.get("id"), bool)
                        or not isinstance(ado.get("id"), int)):
        findings.append("%s: ado.id must be an integer work-item id, got %r"
                        % (where, ado.get("id")))
    # A FINDING rather than a warning, and not for symmetry: a misspelled origin
    # reads as "unrecorded" everywhere downstream, which is the same silence a
    # pre-0.44 link produces. So the one wrong value here is indistinguishable
    # from the honest absence unless the validator refuses it. `null` and absent
    # both mean unrecorded and are left alone.
    if ado.get("origin") is not None and ado.get("origin") not in ADO_ORIGIN:
        findings.append("%s: ado.origin must be one of %s (or absent/null for "
                        "unrecorded), got %r"
                        % (where, ", ".join(repr(v) for v in ADO_ORIGIN),
                           ado.get("origin")))


def _unknown_keys(obj, known, where, warnings):
    """Warn on keys we do not recognize; case-insensitive 'did you mean'."""
    if not isinstance(obj, dict):
        return
    lower = {k.lower(): k for k in known}
    for k in obj:
        ks = str(k)
        # "_" = internal, "$" = JSON-Schema keywords, "//" = comment convention
        if ks in known or ks.startswith(("_", "$", "//")):
            continue
        hint = lower.get(ks.lower())
        if hint:
            warnings.append("%s: unknown key '%s' — did you mean '%s'?"
                            % (where, ks, hint))
        else:
            warnings.append("%s: unknown key '%s' (typo? unknown keys are "
                            "ignored by the orchestrator)" % (where, ks))

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
        print("_manifest_vocab.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__manifest_vocab.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
