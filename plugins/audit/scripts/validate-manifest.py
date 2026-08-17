#!/usr/bin/env python3
"""
Structural validator for the audit manifest — dependency-free (stdlib only).

Complements the JSON Schema (schema/audit-plan.schema.json) with the referential
checks a schema cannot express: unique ids, resolvable blockedBy/dependsOn,
dependency CYCLES, fileIndex integrity in BOTH directions, and reciprocal
bugs[] <-> task.bugId cross-links. Commands run it after EVERY manifest
mutation (the Edit-and-revalidate rule in reference/manifest-conventions.md).

Output classes:
  FINDING  — structural defect; the manifest is INVALID (exit 1).
  WARNING  — suspicious but tolerated (unknown/typo'd keys, pre-0.3 status
             combinations); exit stays 0 when there are only warnings.

Usage:
  python3 validate-manifest.py <manifest-path>
  python3 validate-manifest.py --selftest

Exit codes: 0 = valid (warnings allowed) · 1 = findings · 2 = usage error or
unreadable/unparseable file.

The core `validate(manifest)` is pure and never raises on arbitrary JSON input —
shape surprises become findings, not tracebacks.

This module carries no `--selftest` of its own any more; its 131 cases live in
`plugins/audit/tests/test_validate_manifest.py`, byte-identical labels and all —
see `plugins/audit/tests/_harness.py`. The `_valid_manifest()` fixture every
mutating case starts from went with them: it had no caller outside that suite.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _areas  # noqa: E402  (meta.areas registry + the resolution every surface shares)

# --- vocabulary + known keys ----------------------------------------------------
# Two of these are terminal: `done` (it landed) and `cancelled` (it will not be
# done, and that is an answer — see the schema's $defs/status for why the word is
# `cancelled` and not `deprecated`). TERMINAL is what "finished" means everywhere
# below: a phase signs off when every task is finished, and a claim on a finished
# phase is stale whichever way it finished.
STATUS = ("pending", "in_progress", "blocked", "done", "cancelled")
TERMINAL = _mio.TERMINAL
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
             "tag"}
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


# --- per-object checkers --------------------------------------------------------
def _check_claim(phase, pwhere, findings, warnings):
    """Validate an optional parallel-run `claim` on a phase (v0.15 sharded layout).

    A claim records which session/host/branch is running a phase so concurrent work
    across machines is coordinated (and a same-phase double-claim shows up as a shard
    merge conflict). Shape errors are findings; a claim missing recommended keys, or one
    left on a finished phase (stale — should be released), is a warning."""
    if "claim" not in phase:
        return
    claim = phase.get("claim")
    if claim is None:
        return
    if not isinstance(claim, dict):
        findings.append("%s: claim must be an object {sessionId, host, branch, at}, got %s"
                        % (pwhere, type(claim).__name__))
        return
    missing = [k for k in CLAIM_KEYS if not claim.get(k)]
    if missing:
        warnings.append("%s: claim is missing %s — a claim should identify the "
                        "session/host/branch holding the phase" % (pwhere, ", ".join(missing)))
    if phase.get("status") in ("done", "cancelled", "blocked"):
        warnings.append("%s: has a claim but status is %r — a finished/blocked phase should "
                        "release its claim (stale claim)" % (pwhere, phase.get("status")))


def _check_area_tag(phase, pwhere, findings):
    """A phase's `area` must be a tag or a list of them (v0.16 shape, v0.28 meaning).

    Shape only — WHICH tags are legal is not this function's business and is not
    anybody's: free text stays legal forever. But `area: 3` and `area: {...}`
    normalise to NO tags at all, so the phase silently leaves every grouping and
    resolves against no area. Silence is the reason this is worth a finding."""
    if "area" not in phase:
        return
    area = phase.get("area")
    if area is None or isinstance(area, str):
        return
    if not isinstance(area, list):
        findings.append("%s: area must be a tag or a list of tags, got %s"
                        % (pwhere, type(area).__name__))
        return
    bad = [a for a in area if not isinstance(a, str) or not a.strip()]
    if bad:
        findings.append("%s: every area tag must be a non-empty string (%d bad: %r)"
                        % (pwhere, len(bad), bad[:3]))


def _check_areas(manifest, findings, warnings):
    """The `meta.areas` registry, and the phases that name it (v0.28).

    Three questions, and only the first can invalidate a manifest:

      * is the registry SHAPED like a registry — findings, same as any other
        wrong type in this file;
      * does every tag a phase carries have an entry — warnings, and ONLY when
        the manifest registers areas at all. A project that tags freely and
        registers nothing is using the v0.16 feature exactly as designed, and
        warning it would be this validator nagging about a feature not in use.
        A project that DOES register is one where an unregistered tag is nearly
        always a typo of a registered one — and a typo'd tag quietly resolves to
        no area, so the reviewer and the skills the author expected never happen;
      * do a phase's areas AGREE about its reviewer — a warning naming the
        winner, because written order decides and a silent tie-break is a
        reviewer nobody can explain.
    """
    meta = manifest.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "areas" in meta:
        f, w = _areas.validate_registry(meta.get("areas"))
        findings.extend(f)
        warnings.extend(w)
    for pid, tag in _areas.unregistered_tags(manifest):
        warnings.append("phase %s: area tag %r has no entry in meta.areas — it "
                        "groups and filters, but resolves to no root, no default "
                        "reviewer and no default skills (typo? free-text tags are "
                        "legal)" % (pid, tag))
    for phase in manifest.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        clash = _areas.review_skill_conflicts(manifest, phase)
        if clash:
            # json.dumps, not %r: the values came out of a JSON file and go back to
            # someone editing one, and `None` is not something they can type there.
            # A null IS one of the disagreeing answers here — an area saying "tests
            # sign this off" disagrees with an area naming a reviewer.
            warnings.append(
                "phase %s: areas %s each set a different reviewSkill — written "
                "order decides, so %s (from area %s) is the one that runs"
                % (phase.get("id") or "?",
                   ", ".join("%s=%s" % (t, json.dumps(s)) for t, s in clash),
                   json.dumps(clash[0][1]), clash[0][0]))


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
    if "id" in ado and not isinstance(ado.get("id"), int):
        findings.append("%s: ado.id must be an integer work-item id, got %r"
                        % (where, ado.get("id")))


def _check_identity_map(meta, findings, warnings):
    """`meta.ado.identityMap` (v0.38) -- the advisory ledger -> ADO identity map.

    Shape only: an object whose KEYS are ledger identities (the form
    usage.authorMode records authors and area.owner is written in) and whose
    VALUES are ADO identities (email/UPN). The USE is advisory -- /audit:sync
    proposes assignments on push and reverse-maps reportedBy on pull, and
    nothing gates, refuses or assigns on the map by itself -- but a malformed
    map is a structural defect like any other wrong type in this file (the
    ar2 rule: shape is not informational). Deliberately NO email-shape
    policing: an ADO identity is whatever the org's directory says it is,
    and this validator is an offline shape-checker.

    A DUPLICATE VALUE is a WARNING, never a finding: two ledger identities
    mapping to one ADO account is usually a paste error, but one person can
    legitimately hold two ledger identities (usage.authorMode changed
    mid-project, or commits under two git emails). Values are compared
    case-insensitively because ADO identities are."""
    ado = meta.get("ado")
    if not isinstance(ado, dict) or "identityMap" not in ado:
        return
    imap = ado.get("identityMap")
    if imap is None:
        return
    if not isinstance(imap, dict):
        findings.append("meta.ado.identityMap: must be an object mapping "
                        "ledger identity -> ADO identity (email/UPN), got %s"
                        % type(imap).__name__)
        return
    targets = {}   # lowercased ADO identity -> [ledger key, ...] in map order
    shown = {}     # lowercased ADO identity -> first spelling seen
    for k, v in imap.items():
        if not isinstance(k, str) or not str(k).strip():
            findings.append("meta.ado.identityMap: keys must be non-empty "
                            "ledger identity strings (the form usage."
                            "authorMode records), got %r" % (k,))
        if not isinstance(v, str) or not v.strip():
            findings.append("meta.ado.identityMap[%r]: value must be a "
                            "non-empty ADO identity string (email/UPN), "
                            "got %r" % (k, v))
            continue
        low = v.strip().lower()
        targets.setdefault(low, []).append(k)
        shown.setdefault(low, v.strip())
    for low, keys in targets.items():
        if len(keys) > 1:
            warnings.append(
                "meta.ado.identityMap: %r is the target of %d ledger "
                "identities (%s) -- usually a paste error, though one person "
                "CAN legitimately hold two ledger identities (e.g. "
                "usage.authorMode changed mid-project); /audit:sync pull "
                "maps this ADO identity back to the FIRST key in map order"
                % (shown[low], len(keys),
                   ", ".join(repr(k) for k in keys)))


def check_ado_meta(ado):
    """The full meta.ado connector-config check. Returns (findings, warnings).

    ONE front door on purpose: validate() calls this for the manifest, and the
    panel's write_ado (PUT /api/ado) calls it for a candidate save -- so the
    CLI and the panel cannot disagree about what a valid config is.

    null/absent = connector off, an answer -- silent. The v2 keys follow the
    file's standing philosophy: wrong TYPES are findings (a config that would
    be misread), unknown KEYS are did-you-mean warnings (the typo catcher --
    `statemap` configuring nothing is exactly the silence worth naming). The
    stateMap's status keys get the same warning treatment: a typo'd status
    silently never fires, which is the area-tag argument all over again."""
    f, w = [], []
    if ado is None:
        return f, w
    if not isinstance(ado, dict):
        f.append("meta: ado must be an object or null, got %s"
                 % type(ado).__name__)
        return f, w
    _unknown_keys(ado, KNOWN_ADO, "meta.ado", w)
    _check_identity_map({"ado": ado}, f, w)

    for key in ("organization", "project"):
        val = ado.get(key)
        if key in ado and (not isinstance(val, str) or not val.strip()):
            f.append("meta.ado.%s: must be a non-empty string, got %r"
                     % (key, val))
    for key in ("areaPath", "iterationPath"):
        val = ado.get(key)
        if key in ado and val is not None and not isinstance(val, str):
            f.append("meta.ado.%s: must be a string or null, got %s"
                     % (key, type(val).__name__))
    for key in ("enabled", "echo", "phaseWorkItems"):
        val = ado.get(key)
        if key in ado and not isinstance(val, bool):
            f.append("meta.ado.%s: must be true or false, got %r" % (key, val))
    tag = ado.get("tag")
    if "tag" in ado and tag is not None and (
            not isinstance(tag, str) or not tag.strip()):
        f.append("meta.ado.tag: must be a non-empty string or null (null = "
                 "no provenance tag; absent = 'audit-plugin'), got %r" % (tag,))

    types = ado.get("types")
    if "types" in ado and types is not None:
        if not isinstance(types, dict):
            f.append("meta.ado.types: must be an object, got %s"
                     % type(types).__name__)
        else:
            for k, v in types.items():
                if k == "pbi" and v is None:
                    continue  # null pbi = auto-detect at first phase push
                if not isinstance(v, str) or not v.strip():
                    f.append("meta.ado.types: every value must be a work-item "
                             "type name (non-empty string%s), got %s=%r"
                             % ("; pbi may be null = auto-detect", k, v))

    sm = ado.get("stateMap")
    if "stateMap" in ado and sm is not None:
        if not isinstance(sm, dict):
            f.append("meta.ado.stateMap: must be an object {task, bug, phase} "
                     "or null, got %s" % type(sm).__name__)
        else:
            # F1 (live gate): phase work items have their OWN state vocabulary
            # in ADO (a Scrum PBI knows no "In Progress"), so the map carries a
            # third block, keyed by the same status names phases use.
            vocab = {"task": STATUS, "bug": BUG_STATUS, "phase": STATUS}
            _unknown_keys(sm, set(vocab), "meta.ado.stateMap", w)
            for kind, statuses in vocab.items():
                block = sm.get(kind)
                if kind not in sm or block is None:
                    continue
                if not isinstance(block, dict):
                    f.append("meta.ado.stateMap.%s: must be an object of "
                             "status -> ADO state, got %s"
                             % (kind, type(block).__name__))
                    continue
                _unknown_keys(block, set(statuses),
                              "meta.ado.stateMap.%s" % kind, w)
                for st, val in block.items():
                    if st not in statuses or val is None:
                        continue  # unknown key already warned; null = never move
                    if not isinstance(val, str) or not val.strip():
                        f.append("meta.ado.stateMap.%s.%s: must be an ADO "
                                 "state name or null (null = never move this "
                                 "transition), got %r" % (kind, st, val))

    oc = ado.get("onComplete")
    if "onComplete" in ado and oc is not None:
        if not isinstance(oc, dict):
            f.append("meta.ado.onComplete: must be an object or null, got %s"
                     % type(oc).__name__)
        else:
            _unknown_keys(oc, {"remainingWork"}, "meta.ado.onComplete", w)
            rw = oc.get("remainingWork")
            if "remainingWork" in oc and rw is not None:
                if (isinstance(rw, bool) or not isinstance(rw, (int, float))
                        or rw < 0):
                    f.append("meta.ado.onComplete.remainingWork: must be a "
                             "number >= 0 or null (null = never touch the "
                             "field), got %r" % (rw,))

    cm = ado.get("comments")
    if "comments" in ado and cm is not None:
        if not isinstance(cm, dict):
            f.append("meta.ado.comments: must be an object or null, got %s"
                     % type(cm).__name__)
        else:
            _unknown_keys(cm, {"onBlocked", "onComplete"},
                          "meta.ado.comments", w)
            for key in ("onBlocked", "onComplete"):
                val = cm.get(key)
                if key in cm and not isinstance(val, bool):
                    f.append("meta.ado.comments.%s: must be true or false, "
                             "got %r" % (key, val))

    sp = ado.get("sprint")
    if "sprint" in ado and sp is not None:
        if not isinstance(sp, dict):
            f.append("meta.ado.sprint: must be an object {team, mode} or "
                     "null, got %s" % type(sp).__name__)
        else:
            _unknown_keys(sp, {"team", "mode"}, "meta.ado.sprint", w)
            team = sp.get("team")
            if not isinstance(team, str) or not team.strip():
                f.append("meta.ado.sprint: requires a non-empty 'team' -- "
                         "the team whose iteration calendar defines "
                         "'current', got %r" % (team,))
            mode = sp.get("mode")
            if "mode" in sp and mode != "current":
                f.append("meta.ado.sprint.mode: must be 'current' (the only "
                         "mode today; static paths belong in "
                         "meta.ado.iterationPath), got %r" % (mode,))

    pl = ado.get("pull")
    if "pull" in ado and pl is not None:
        if not isinstance(pl, dict):
            f.append("meta.ado.pull: must be an object {areaPath, tags} or "
                     "null, got %s" % type(pl).__name__)
        else:
            _unknown_keys(pl, {"areaPath", "tags"}, "meta.ado.pull", w)
            ap = pl.get("areaPath")
            if "areaPath" in pl and ap is not None and not isinstance(ap, str):
                f.append("meta.ado.pull.areaPath: must be a string or null, "
                         "got %s" % type(ap).__name__)
            tags = pl.get("tags")
            if "tags" in pl:
                if not isinstance(tags, list):
                    f.append("meta.ado.pull.tags: must be an array of tags, "
                             "got %s" % type(tags).__name__)
                else:
                    bad = [t for t in tags
                           if not isinstance(t, str) or not t.strip()]
                    if bad:
                        f.append("meta.ado.pull.tags: every tag must be a "
                                 "non-empty string (%d bad: %r)"
                                 % (len(bad), bad[:3]))
    return f, w


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


def _model_near_miss(a, b):
    """True iff two model ids are one slip apart: case-insensitively equal but
    spelled differently, or one substitution, insertion, deletion or ADJACENT
    TRANSPOSITION away (case-insensitive) -- the four classic typo shapes."""
    if a == b:
        return False
    x, y = a.lower(), b.lower()
    if x == y:
        return True
    if abs(len(x) - len(y)) > 1:
        return False
    if len(x) == len(y):
        diffs = [i for i, (cx, cy) in enumerate(zip(x, y)) if cx != cy]
        if len(diffs) == 1:
            return True
        return (len(diffs) == 2 and diffs[1] == diffs[0] + 1
                and x[diffs[0]] == y[diffs[1]] and x[diffs[1]] == y[diffs[0]])
    short, long_ = (x, y) if len(x) < len(y) else (y, x)
    i = j = 0
    skipped = False
    while i < len(short):
        if short[i] == long_[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def _check_model_typos(manifest, warnings):
    """Intra-manifest model-id near-miss detector (WARNING only).

    Flags a model value that is used EXACTLY ONCE while a case-insensitive or
    edit-distance-1 neighbour is used elsewhere in the manifest, or appears
    among meta.usage.pricing keys when that table exists. A spelling used
    twice or more is an established choice, never flagged; a clean
    single-model manifest has no neighbour to near-miss and stays silent.

    Deliberately intra-manifest: this validator is an offline shape-checker
    (no config, no ledger — see validate()), so the three-source model hint
    (manifest vs rate table vs ledger) lives in the panel, which has all three
    in hand.
    """
    sites = {}   # model value -> [where, ...] in document order

    def note_use(val, where):
        if isinstance(val, str) and val.strip():
            sites.setdefault(val, []).append(where)

    phases = manifest.get("phases") if isinstance(manifest, dict) else None
    for pi, phase in enumerate(_safe_list(phases)):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))
        note_use(phase.get("model"), pwhere)
        review = phase.get("review")
        if isinstance(review, dict):
            note_use(review.get("model"), pwhere + " review")
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if isinstance(task, dict):
                note_use(task.get("model"), "task %s"
                         % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti))))

    pricing = []
    meta = manifest.get("meta") if isinstance(manifest, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("usage"), dict) \
            and isinstance(meta["usage"].get("pricing"), dict):
        pricing = [k for k in meta["usage"]["pricing"]
                   if isinstance(k, str) and not k.startswith("_")]

    for val in sorted(sites):
        if len(sites[val]) != 1:
            continue
        near = None
        # Prefer the most-used neighbour (the established spelling), then the
        # pricing table, so the warning names the likeliest intended id.
        for other in sorted(sites, key=lambda v: (-len(sites[v]), v)):
            if other != val and len(sites[other]) > 1 \
                    and _model_near_miss(val, other):
                near = (other, "used %d times elsewhere in this manifest"
                        % len(sites[other]))
                break
        if near is None:
            for key in sorted(pricing):
                if key != val and _model_near_miss(val, key):
                    near = (key, "a meta.usage.pricing key")
                    break
        if near is None:
            for other in sorted(sites):
                if other != val and len(sites[other]) == 1 \
                        and _model_near_miss(val, other):
                    near = (other, "used once at %s" % sites[other][0])
                    break
        if near is not None:
            warnings.append(
                "%s: model '%s' is used once and is a near-miss of '%s' (%s) "
                "-- a one-slip model id routes work to a model nobody priced "
                "or intended" % (sites[val][0], val, near[0], near[1]))


def _skills_in_use(manifest):
    """True iff the manifest uses executor skills DELIBERATELY, anywhere.

    Evidence: a task whose `skills` key holds a non-empty list, an explicit
    null (the opt-out is use), or a wrong-typed value (someone tried); or a
    registered area declaring a non-empty default list. `skills: []` alone is
    NOT evidence -- generators initialize empty lists on every task, and a
    project that ignores the feature must get zero new warnings from it."""
    if not isinstance(manifest, dict):
        return False
    for phase in _safe_list(manifest.get("phases")):
        if not isinstance(phase, dict):
            continue
        for task in _safe_list(phase.get("tasks")):
            if isinstance(task, dict) and "skills" in task:
                v = task.get("skills")
                if v is None or (isinstance(v, list) and v) \
                        or not isinstance(v, list):
                    return True
    for entry in _areas.registry(manifest).values():
        v = entry.get("skills")
        if isinstance(v, list) and v:
            return True
    return False


def _check_skills(manifest, warnings):
    """Unresolved-skills advisory (v0.37 B2). WARNING only, never a finding.

    A task whose RESOLVED skills are empty while the manifest uses skills
    elsewhere is usually an oversight -- the executor for that one task loads
    no conventions while its siblings do. The warning names what was consulted
    (the task's own value, the phase's areas) and the three exits: set
    task.skills, register defaults on an area, or write `"skills": null` to
    say 'none applies' -- the explicit opt-out that stops the area fallback
    and this warning with it (_areas.skills_opted_out).

    GATED on _skills_in_use: a manifest that never touches the feature gets
    zero new lines, which is the whole back-compat contract here."""
    if not _skills_in_use(manifest):
        return
    for phase in _safe_list(manifest.get("phases")):
        if not isinstance(phase, dict):
            continue
        tags = _areas.areas_of(phase.get("area"))
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or "?")
            if _areas.skills_opted_out(task):
                continue
            tv = task.get("skills")
            if "skills" in task and not isinstance(tv, list):
                # tv is not None here: null is the opt-out, handled above.
                warnings.append("%s: skills must be an array of skill names or "
                                "null, got %s -- resolution loads nothing "
                                "from it" % (twhere, type(tv).__name__))
            if _areas.resolve_skills(manifest, phase, task):
                continue
            if "skills" not in task:
                tpart = "task has no skills key"
            elif isinstance(tv, list):
                tpart = ("task skills []" if not tv
                         else "task skills list no usable name")
            else:
                tpart = "task skills is not a list"
            apart = ("phase has no area tag" if not tags
                     else "area(s) %s declare none" % ", ".join(tags))
            warnings.append(
                "%s: no skills resolve (%s; %s) -- set task.skills, register "
                "default skills on an area in meta.areas, or write "
                "\"skills\": null to say 'none applies'"
                % (twhere, tpart, apart))


def _skill_near_miss(a, b):
    """True iff two skill names are one slip apart, or two on names long
    enough to carry them.

    One slip is _model_near_miss verbatim (case-only difference, one
    substitution/insertion/deletion, adjacent transposition). Two slips are
    allowed only when BOTH names are 6+ characters: on short names two edits
    can turn one real word into another ('web' -> 'wasm' is distance 2) and
    every hit would be noise -- the same false-positive discipline the md
    detector keeps by capping itself at one slip."""
    if _model_near_miss(a, b):
        return True
    x, y = a.lower(), b.lower()
    if min(len(x), len(y)) < 6 or abs(len(x) - len(y)) > 2:
        return False
    # Banded Levenshtein, capped at 2 -- rows whose minimum exceeds the cap
    # cannot recover, so the walk stops early.
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (cx != cy)))
        if min(cur) > 2:
            return False
        prev = cur
    return prev[-1] <= 2


def _check_skill_typos(manifest, warnings):
    """Intra-manifest skill-name near-miss detector (WARNING only) -- the md
    model detector applied to skill names.

    Flags a name used EXACTLY ONCE beside a near-miss neighbour used two or
    more times anywhere in the manifest (task.skills or meta.areas defaults).
    A spelling used twice is an established choice, never flagged. And it is
    deliberately intra-manifest: whether a name exists in the DISCOVERY
    inventory is the panel's hint (the modelHints precedent) -- this validator
    stays an offline shape-checker with no inventory in hand."""
    sites = {}   # skill name -> [where, ...] in document order

    def note_use(val, where):
        if isinstance(val, str) and val.strip():
            sites.setdefault(val.strip(), []).append(where)

    for phase in _safe_list(manifest.get("phases")
                            if isinstance(manifest, dict) else None):
        if not isinstance(phase, dict):
            continue
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or "?")
            sk = task.get("skills")
            for s in (sk if isinstance(sk, list) else []):
                note_use(s, twhere)
    for tag, entry in _areas.registry(manifest).items():
        sk = entry.get("skills")
        for s in (sk if isinstance(sk, list) else []):
            note_use(s, "meta.areas.%s" % tag)

    for val in sorted(sites):
        if len(sites[val]) != 1:
            continue
        # The most-used neighbour is the established spelling -- the warning
        # names the likeliest intended name, exactly as md does.
        for other in sorted(sites, key=lambda v: (-len(sites[v]), v)):
            if other != val and len(sites[other]) > 1 \
                    and _skill_near_miss(val, other):
                warnings.append(
                    "%s: skill '%s' is used once and is a near-miss of '%s' "
                    "(used %d times elsewhere in this manifest) -- a one-slip "
                    "skill name names a skill that never loads"
                    % (sites[val][0], val, other, len(sites[other])))
                break


def _cycle_findings(phases, findings):
    """Detect dependency cycles over the waits-on graph.

    Edges: task -> its blockedBy/dependsOn targets; phase -> its blockedBy
    targets; phase -> each of its tasks (a phase is done only after its tasks),
    which catches the task-blockedBy-its-own-phase deadlock.
    """
    edges = {}

    def add_edge(a, b):
        if a and b:
            edges.setdefault(a, []).append(b)

    for phase in phases:
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id")
        for ref in _safe_list(phase.get("blockedBy")):
            if isinstance(ref, str):
                add_edge(pid, ref)
        for task in _safe_list(phase.get("tasks")):
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            add_edge(pid, tid)
            for ref in _safe_list(task.get("blockedBy")):
                if isinstance(ref, str):
                    add_edge(tid, ref)
            for ref in _safe_list(task.get("dependsOn")):
                if isinstance(ref, str):
                    add_edge(tid, ref)

    WHITE, GRAY, BLACK = 0, 1, 2
    color, reported = {}, set()
    for start in list(edges):
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(edges.get(start, ())))]
        color[start] = GRAY
        path = [start]
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                path.pop()
                color[node] = BLACK
                continue
            c = color.get(nxt, WHITE)
            if c == GRAY:
                i = path.index(nxt) if nxt in path else len(path) - 1
                cyc = path[i:] + [nxt]
                key = frozenset(cyc)
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        "dependency cycle (blockedBy/dependsOn can never be "
                        "satisfied): %s" % " -> ".join(str(x) for x in cyc))
            elif c == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(edges.get(nxt, ()))))
                path.append(nxt)


# --- validate -------------------------------------------------------------------
def validate(manifest):
    """Return (findings, warnings) — two lists of strings; empty findings = valid."""
    f, w = [], []
    if not isinstance(manifest, dict):
        return (["manifest root must be a JSON object"], w)

    _unknown_keys(manifest, KNOWN_ROOT, "manifest root", w)

    meta = manifest.get("meta")
    if not isinstance(meta, dict):
        f.append("meta: missing or not an object")
    else:
        _unknown_keys(meta, KNOWN_META, "meta", w)
        version = meta.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            # bool is an int subclass in Python — `true` must NOT pass as a version.
            f.append("meta.version: missing or not an integer")
        # meta.ado: the whole connector config goes through check_ado_meta --
        # the ONE front door shared with the panel's write_ado, so the CLI
        # and the panel cannot disagree. (It keeps F-C-1's object-or-null rule
        # and folds in _check_identity_map.)
        if "ado" in meta:
            af, aw = check_ado_meta(meta.get("ado"))
            f.extend(af)
            w.extend(aw)

    _check_areas(manifest, f, w)

    phases = manifest.get("phases")
    if not isinstance(phases, list):
        f.append("phases: missing or not an array")
        phases = []

    phase_ids, task_ids = [], []
    task_bug_links = []       # (twhere, task_id, bugId)
    task_by_id = {}
    task_files = {}           # task_id -> files list

    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            f.append("phases[%d]: not an object" % pi)
            continue
        pid = phase.get("id")
        pwhere = "phase %s" % (pid or ("phases[%d]" % pi))
        _require_fields(phase, pwhere, f)
        _unknown_keys(phase, KNOWN_PHASE, pwhere, w)
        # connector v2: phaseWorkItems writes a phase-level adoLink
        _check_ado(phase, pwhere, f)
        if pid:
            phase_ids.append(pid)
        if phase.get("status") not in STATUS:
            f.append("%s: status %r not in %s" % (pwhere, phase.get("status"), list(STATUS)))
        _check_claim(phase, pwhere, f, w)
        _check_area_tag(phase, pwhere, f)
        # A budget of 0 or a negative one is not a budget, and a string is a typo
        # that would silently render as "no budget". Both are worth saying out loud.
        if "budgetUSD" in phase:
            budget = phase.get("budgetUSD")
            if isinstance(budget, bool) or not isinstance(budget, (int, float)):
                f.append("%s: budgetUSD must be a number, got %s"
                         % (pwhere, type(budget).__name__))
            elif budget <= 0:
                f.append("%s: budgetUSD must be greater than 0 (got %s) — omit the "
                         "key entirely for 'no budget'" % (pwhere, budget))

        tasks_val = phase.get("tasks")
        if "tasks" not in phase:
            w.append("%s: no 'tasks' key — the schema requires one (an empty "
                     "phase should carry an empty list)" % pwhere)
        elif not isinstance(tasks_val, list):
            f.append("%s: tasks must be an array, got %s"
                     % (pwhere, type(tasks_val).__name__))
        # A phase is 'done' only after sign-off, which requires every task done.
        # A done phase with a non-done task is a stale-status slip the schema
        # can't express (e.g. a hand-regenerated roadmap that flipped the phase
        # but not its tasks).
        if phase.get("status") == "done":
            # FINISHED, not done: a task the team cancelled is settled, and a
            # phase that signed off around it is not a slip. Only genuinely
            # unfinished work (pending / in_progress / blocked) contradicts it.
            not_done = [t.get("id") or "?" for t in _safe_list(tasks_val)
                        if isinstance(t, dict) and t.get("status") not in TERMINAL]
            if not_done:
                f.append("%s: status 'done' but %d task(s) are not finished (%s) "
                         "\u2014 a phase is done only after ALL its tasks are done "
                         "or cancelled (sign-off)"
                         % (pwhere, len(not_done), ", ".join(not_done[:6])))
        for ti, task in enumerate(_safe_list(tasks_val)):
            if not isinstance(task, dict):
                f.append("%s tasks[%d]: not an object" % (pwhere, ti))
                continue
            tid = task.get("id")
            twhere = "task %s" % (tid or ("%s.tasks[%d]" % (pwhere, ti)))
            _require_fields(task, twhere, f)
            _unknown_keys(task, KNOWN_TASK, twhere, w)
            if tid:
                task_ids.append(tid)
                task_by_id[tid] = task
                files = task.get("files")
                if isinstance(files, list) and files:
                    task_files[tid] = files
            if task.get("status") not in STATUS:
                f.append("%s: status %r not in %s" % (twhere, task.get("status"), list(STATUS)))
            if (phase.get("status") == "pending"
                    and task.get("status") == "in_progress"):
                w.append("%s is in_progress but its %s is still 'pending' — "
                         "pre-0.3 manifest? /audit:resume expects the phase to "
                         "be 'in_progress' too" % (twhere, pwhere))
            tests = task.get("tests")
            if "tests" in task and tests is not None and not isinstance(tests, dict):
                f.append("%s: tests must be an object with a 'mode', got %s"
                         % (twhere, type(tests).__name__))
            if isinstance(tests, dict) and tests.get("mode") not in TESTS_MODE:
                f.append("%s: tests.mode %r not in %s" % (twhere, tests.get("mode"), list(TESTS_MODE)))
            if "risk" in task and task.get("risk") not in RISK:
                f.append("%s: risk %r not in %s" % (twhere, task.get("risk"), ["low", "med", "high", None]))
            _check_ado(task, twhere, f)
            # The id-prefix rule (workstream B) -- the hand-move detector.
            # /audit:task move renumbers a task into its target phase, so an id
            # that does not match `<phaseId>.<int>` means the object was dragged
            # by hand. A WARNING only: legacy manifests with free-form ids must
            # never go red over bookkeeping.
            if tid and pid and not re.match(
                    r"^%s\.\d+$" % re.escape(str(pid)), str(tid)):
                w.append("%s: id does not follow its phase's prefix (%s.<n>) "
                         "-- moved by hand? /audit:task move renumbers, "
                         "rewrites references and records a task.move row. "
                         "Informational; legacy ids stay legal" % (twhere, pid))
            if "movedFrom" in task:
                mf = task.get("movedFrom")
                if mf is not None and not isinstance(mf, dict):
                    w.append("%s: movedFrom should be an object "
                             "{id, phase, at}, got %s"
                             % (twhere, type(mf).__name__))
                elif isinstance(mf, dict):
                    lacking = [k for k in ("id", "phase", "at")
                               if not mf.get(k)]
                    if lacking:
                        w.append("%s: movedFrom is missing %s -- /audit:task "
                                 "move writes all three"
                                 % (twhere, ", ".join(lacking)))
            if task.get("bugId"):
                task_bug_links.append((twhere, tid, task["bugId"]))

    # -- unique ids across phases + tasks + bugs -------------------------------
    bugs = manifest.get("bugs")
    bug_list = bugs if isinstance(bugs, list) else []
    bug_ids = [b.get("id") for b in bug_list if isinstance(b, dict) and b.get("id")]
    bug_by_id = {b["id"]: b for b in bug_list
                 if isinstance(b, dict) and b.get("id")}

    all_ids = phase_ids + task_ids + bug_ids
    seen = set()
    for i in all_ids:
        if i in seen:
            f.append("duplicate id: %s" % i)
        seen.add(i)

    known = set(phase_ids) | set(task_ids)

    # -- blockedBy / dependsOn resolve + cycles ---------------------------------
    for pi, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        pwhere = "phase %s" % (phase.get("id") or ("phases[%d]" % pi))

        def _check_refs(refs_val, where, field, universe, kind):
            """Report a non-array value, a non-string entry (which would crash
            the set-membership test), or an unresolved id — never raise."""
            if refs_val is not None and not isinstance(refs_val, list):
                f.append("%s: %s must be an array, got %s"
                         % (where, field, type(refs_val).__name__))
            for ref in _safe_list(refs_val):
                if not isinstance(ref, str):
                    f.append("%s: %s entry must be a string id, got %r"
                             % (where, field, ref))
                elif ref not in universe:
                    f.append("%s: %s '%s' does not resolve to %s"
                             % (where, field, ref, kind))

        _check_refs(phase.get("blockedBy"), pwhere, "blockedBy", known,
                    "any task/phase")
        for ti, task in enumerate(_safe_list(phase.get("tasks"))):
            if not isinstance(task, dict):
                continue
            twhere = "task %s" % (task.get("id") or ("%s.tasks[%d]" % (pwhere, ti)))
            _check_refs(task.get("blockedBy"), twhere, "blockedBy", known,
                        "any task/phase")
            _check_refs(task.get("dependsOn"), twhere, "dependsOn", task_ids,
                        "a task")

    _cycle_findings(phases, f)
    _check_model_typos(manifest, w)
    _check_skills(manifest, w)
    _check_skill_typos(manifest, w)

    # -- fileIndex integrity (both directions) -----------------------------------
    file_index = manifest.get("fileIndex")
    if isinstance(file_index, dict):
        stripped_index = {}
        for fpath, refs in file_index.items():
            key = _strip_line_suffix(fpath)
            bucket = stripped_index.setdefault(key, set())
            if not isinstance(refs, list):
                f.append("fileIndex['%s']: value must be an array of task ids, "
                         "got %s" % (fpath, type(refs).__name__))
                continue
            for ref in refs:
                if isinstance(ref, str):
                    bucket.add(ref)  # only hashable str ids enter the set
                if ref not in task_ids:
                    f.append("fileIndex['%s']: task '%s' does not exist" % (fpath, ref))
        for tid, files in task_files.items():
            for fentry in files:
                key = _strip_line_suffix(fentry)
                if tid not in stripped_index.get(key, set()):
                    f.append("task %s: file '%s' missing from fileIndex "
                             "(fileIndex['%s'] must include '%s')"
                             % (tid, fentry, key, tid))

    # -- bugs[] ------------------------------------------------------------------
    if bugs is not None and not isinstance(bugs, list):
        f.append("bugs: not an array")
    for bi, bug in enumerate(bug_list):
        if not isinstance(bug, dict):
            f.append("bugs[%d]: not an object" % bi)
            continue
        bid = bug.get("id")
        bwhere = "bug %s" % (bid or ("bugs[%d]" % bi))
        _require_fields(bug, bwhere, f)
        _unknown_keys(bug, KNOWN_BUG, bwhere, w)
        if bid and not BUG_ID_RE.match(str(bid)):
            f.append("%s: id must match BUG-<number>" % bwhere)
        if bug.get("status") not in BUG_STATUS:
            f.append("%s: status %r not in %s" % (bwhere, bug.get("status"), list(BUG_STATUS)))
        _check_ado(bug, bwhere, f)
        if bug.get("taskId"):
            if bug["taskId"] not in task_ids:
                f.append("%s: taskId '%s' does not resolve to a task" % (bwhere, bug["taskId"]))
            else:
                linked = task_by_id.get(bug["taskId"]) or {}
                if linked.get("bugId") != bid:
                    f.append("%s: taskId '%s' but that task's bugId is %r — "
                             "link must be reciprocal"
                             % (bwhere, bug["taskId"], linked.get("bugId")))

    for twhere, tid, bug_ref in task_bug_links:
        if bug_ref not in bug_ids:
            f.append("%s: bugId '%s' does not resolve to a bug" % (twhere, bug_ref))
        else:
            linked = bug_by_id.get(bug_ref) or {}
            if linked.get("taskId") != tid:
                f.append("%s: bugId '%s' but that bug's taskId is %r — "
                         "link must be reciprocal"
                         % (twhere, bug_ref, linked.get("taskId")))

    # -- proposals[] (parked phases; /audit:init park + /audit:propose) ----------
    # Two classes of entry share this array. Payload-bearing proposals are
    # structured records the /audit:propose lifecycle depends on — their
    # vocabulary IS enforced (findings). Legacy free-form entries (pre-0.33)
    # are tolerated: unknown-key warnings at most, so no old manifest goes red.
    proposals = manifest.get("proposals")
    if proposals is not None and not isinstance(proposals, list):
        f.append("proposals: not an array")
    prop_list = proposals if isinstance(proposals, list) else []
    live_ids = set(all_ids)
    prop_ids_seen = set()
    reserved_ids = set()   # payload phase+task ids across still-parked proposals
    staged_refs = []       # (where, ref) — blockedBy/dependsOn inside payloads
    for xi, prop in enumerate(prop_list):
        if not isinstance(prop, dict):
            f.append("proposals[%d]: not an object" % xi)
            continue
        prid = prop.get("id")
        xwhere = "proposal %s" % (prid or ("proposals[%d]" % xi))
        _unknown_keys(prop, KNOWN_PROPOSAL, xwhere, w)
        if prid:
            if prid in prop_ids_seen:
                f.append("duplicate proposal id: %s" % prid)
            prop_ids_seen.add(prid)
        payload = prop.get("payload")
        if "payload" in prop and payload is not None and not isinstance(payload, dict):
            f.append("%s: payload must be an object or null, got %s"
                     % (xwhere, type(payload).__name__))
            payload = None
        if not isinstance(payload, dict):
            continue  # legacy free-form entry — tolerated as-is
        if not PROP_ID_RE.match(str(prid or "")):
            f.append("%s: id must match PROP-<number>" % xwhere)
        status = prop.get("status")
        if status not in PROPOSAL_STATUS:
            f.append("%s: status %r not in %s"
                     % (xwhere, status, list(PROPOSAL_STATUS)))
        mat = prop.get("materializedAs")
        if mat is not None:
            if mat not in phase_ids:
                f.append("%s: materializedAs '%s' does not resolve to a phase"
                         % (xwhere, mat))
            if status != "materialized":
                f.append("%s: materializedAs is set but status is %r — must be "
                         "'materialized' (/audit:propose writes both together)"
                         % (xwhere, status))
        pphase = payload.get("phase")
        if not isinstance(pphase, dict):
            f.append("%s: payload.phase must be an object (the parked phase), "
                     "got %s" % (xwhere, type(pphase).__name__))
            continue
        for key in ("id", "title"):
            if not pphase.get(key):
                f.append("%s: payload.phase missing required '%s'" % (xwhere, key))
        if not isinstance(pphase.get("tasks"), list):
            f.append("%s: payload.phase.tasks must be an array — park the full "
                     "synthesized phase so materialization is a move, not a "
                     "rebuild" % xwhere)
        # Reserved-id bookkeeping applies only while the proposal is parked: a
        # materialized payload id now living as a real phase is the SUCCESS
        # state, not a collision, and a dropped proposal releases its ids.
        if status == "proposed":
            staged = [pphase.get("id")] + [
                t.get("id") for t in _safe_list(pphase.get("tasks"))
                if isinstance(t, dict)]
            for sid in staged:
                if not sid:
                    continue
                if sid in live_ids:
                    f.append("%s: reserved id '%s' collides with a live id — "
                             "/audit:propose materialize re-allocates on "
                             "collision, but a parked payload should never "
                             "share an id with the live plan" % (xwhere, sid))
                elif sid in reserved_ids:
                    f.append("%s: reserved id '%s' is already reserved by "
                             "another proposal" % (xwhere, sid))
                reserved_ids.add(sid)
            for ref in _safe_list(pphase.get("blockedBy")):
                if isinstance(ref, str):
                    staged_refs.append((xwhere, ref))
            for t in _safe_list(pphase.get("tasks")):
                if not isinstance(t, dict):
                    continue
                for field in ("blockedBy", "dependsOn"):
                    for ref in _safe_list(t.get(field)):
                        if isinstance(ref, str):
                            staged_refs.append((xwhere, ref))
    # Staged refs resolve against the live plan OR any reserved id — a payload
    # may lean on a sibling proposal. Naming nothing anywhere is only a warning:
    # the payload is staged, not live, and materialize re-checks refs anyway.
    staged_universe = live_ids | reserved_ids
    for xwhere, ref in staged_refs:
        if ref not in staged_universe:
            w.append("%s: staged blockedBy/dependsOn '%s' names nothing in the "
                     "live plan or any parked proposal — materialize will ask "
                     "about it" % (xwhere, ref))

    return (f, w)


# --- cli ------------------------------------------------------------------------
def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: validate-manifest.py <manifest-path>\n")
        return 2
    try:
        manifest = _mio.load_manifest(argv[0])
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (argv[0], exc))
        return 2

    try:
        findings, warnings = validate(manifest)
    except Exception as exc:  # defensive; validate() should never raise
        print("FINDING: internal validator error: %s" % exc)
        return 1

    for line in warnings:
        print("WARNING: " + line)

    if findings:
        for line in findings:
            print("FINDING: " + line)
        print("\nINVALID: %d finding(s) in %s" % (len(findings), argv[0]))
        return 1

    n_tasks = sum(len(p.get("tasks") or []) for p in manifest.get("phases", []) if isinstance(p, dict))
    print("OK: %s valid (%d phases, %d tasks, %d bugs%s)"
          % (argv[0], len(manifest.get("phases", [])), n_tasks,
             len(manifest.get("bugs") or []),
             ", %d warning(s)" % len(warnings) if warnings else ""))
    return 0


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("validate-manifest.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test_validate_manifest.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
