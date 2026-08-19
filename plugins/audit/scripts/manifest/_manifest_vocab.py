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

# Known keys per level. Unknown keys are WARNINGS (typo catcher), never findings
# — additionalProperties stays permissive for forward/backward compatibility.
# The "legacy" names below were removed from the schema in v0.3.0 but remain
# silently accepted in pre-0.3 manifests.
KNOWN_ROOT = {"$schema", "meta", "phases", "fileIndex", "bugs", "deferred",
              "proposals"}
KNOWN_META = {"version", "repo", "title", "createdISO", "node",
              "developmentBranch", "branchPrefix", "gitRoot", "reviewSkill",
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
              # tolerated (older /audit:init wrote these; informational):
              "notes", "baseCommit",
              # workspaceRoot: 0.2.0-era name for gitRoot; audit.md reads it as
              # a fallback when meta.gitRoot is absent.
              "workspaceRoot",
              # legacy (pre-0.3, ignored by the orchestrator):
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
KNOWN_PHASE = {"id", "title", "status", "model", "blockedBy", "docs",
               "description", "desiredOutcome", "testGate", "baseRef", "branch",
               "mergedAt", "review", "reviewFindings", "summary", "tasks",
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
               # legacy (pre-0.3):
               "signOff"}
# Recommended keys on a parallel-run claim (soft — missing ones are warnings).
CLAIM_KEYS = ("sessionId", "host", "branch")
KNOWN_TASK = {"id", "title", "status", "model", "skills", "blockedBy",
              "dependsOn", "files", "docs", "description", "tests", "outcome",
              "commit", "attempts", "maxAttempts", "startedAt", "completedAt",
              "risk", "verifiedBy", "bugId", "ado",
              # workstream B: written by /audit:task move -- {id, phase, at},
              # the durable half of the mapping (the other half is the
              # journal's task.move row):
              "movedFrom",
              # tolerated (older /audit:init wrote this; informational):
              "details"}
KNOWN_BUG = {"id", "title", "status", "severity", "reportedAt", "reportedBy",
             "description", "repro", "expected", "actual", "files", "taskId",
             "fixedIn", "notes", "ado"}
KNOWN_PROPOSAL = {"id", "name", "status", "origin", "scope", "benefit",
                  "technicalNote", "openQuestions", "createdISO", "payload",
                  "materializedAs", "materializedAt",
                  # tolerated on dropped proposals (/audit:propose drop note):
                  "notes"}


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
