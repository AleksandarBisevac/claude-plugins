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


# --- selftest -------------------------------------------------------------------
def _valid_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
                {"id": "P0.1", "title": "Task", "status": "pending",
                 "tests": {"mode": "regression"}, "risk": "low",
                 "files": ["src/a.ts"],
                 "blockedBy": [], "dependsOn": []},
                {"id": "P0.2", "title": "Task 2", "status": "pending",
                 "dependsOn": ["P0.1"], "bugId": "BUG-1"},
            ]},
        ],
        "fileIndex": {"src/a.ts": ["P0.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "A bug", "status": "in_progress",
             "taskId": "P0.2"},
        ],
    }


def _selftest():
    import copy

    results = []

    def check(name, expect_finding, mutate=None, *, expect_warning=None):
        m = copy.deepcopy(_valid_manifest())
        if mutate:
            mutate(m)
        findings, warnings = validate(m)
        if expect_finding is None:
            ok = findings == []
            detail = "expected clean, got %s" % (findings or "clean")
        else:
            ok = any(expect_finding in x for x in findings)
            detail = "expected finding ~%r in %s" % (expect_finding, findings)
        if ok and expect_warning is not None:
            ok = any(expect_warning in x for x in warnings)
            detail = "expected warning ~%r in %s" % (expect_warning, warnings)
        results.append(ok)
        print("%s %s (%s)" % ("PASS" if ok else "FAIL", name, detail))

    check("v1 valid manifest passes", None)
    # ca (F-P-4): a phase can finish WITHOUT being done — the feature it was for
    # is dropped, part of the work landed, the phase closes. Industry calls that
    # cancelled (Linear "Canceled", Jira "Won't Do", GitHub "closed as not
    # planned", ADO "Removed"); the manifest's bugs already had `wontfix` and
    # phases/tasks had no way to say it, so plans carried dead phases as
    # `pending` forever or lied with `done`.
    check("ca1 cancelled is a legal task status", None,
          lambda m: m["phases"][0]["tasks"][0].update(status="cancelled"))
    check("ca2 cancelled is a legal phase status", None,
          lambda m: m["phases"][0].update(status="cancelled"))
    check("ca3 a done phase may hold cancelled tasks - dropping one task is not "
          "a reason a finished phase cannot sign off", None,
          lambda m: (m["phases"][0].update(status="done"),
                     [t.update(status="done") for t in m["phases"][0]["tasks"]],
                     m["phases"][0]["tasks"][0].update(status="cancelled")))
    check("ca4 ...but a done phase with UNFINISHED tasks is still a slip",
          "status 'done' but 1 task(s) are not finished",
          lambda m: (m["phases"][0].update(status="done"),
                     [t.update(status="done") for t in m["phases"][0]["tasks"]],
                     m["phases"][0]["tasks"][0].update(status="in_progress")))
    check("ca5 a claim on a cancelled phase is stale, exactly as on a done one",
          None,
          lambda m: m["phases"][0].update(
              status="cancelled",
              claim={"sessionId": "s", "host": "h", "branch": "b"}),
          expect_warning="stale claim")
    check("v2 bad task status", "status 'doing' not in",
          lambda m: m["phases"][0]["tasks"][0].update(status="doing"))
    check("v3 bad tests.mode", "tests.mode 'yolo' not in",
          lambda m: m["phases"][0]["tasks"][0]["tests"].update(mode="yolo"))
    check("v4 duplicate id", "duplicate id: P0.1",
          lambda m: m["phases"][0]["tasks"].append(
              {"id": "P0.1", "title": "dup", "status": "pending"}))
    check("v5 dangling dependsOn", "dependsOn 'P9.9' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=["P9.9"]))
    check("v6 dangling bugs[].taskId", "taskId 'P9.9' does not resolve",
          lambda m: m["bugs"][0].update(taskId="P9.9"))
    check("v7 dangling task.bugId", "bugId 'BUG-99' does not resolve",
          lambda m: m["phases"][0]["tasks"][1].update(bugId="BUG-99"))
    check("v8 malformed bug id", "id must match BUG-<number>",
          lambda m: (m["bugs"][0].update(id="bug_one"),
                     m["phases"][0]["tasks"][1].update(bugId="bug_one")))
    check("v9 bad bug status", "status 'zombie' not in",
          lambda m: m["bugs"][0].update(status="zombie"))
    check("v10 missing meta.version", "meta.version",
          lambda m: m["meta"].pop("version"))
    check("v11 dangling fileIndex ref", "fileIndex['src/a.ts']: task 'GONE'",
          lambda m: m.update(fileIndex={"src/a.ts": ["GONE", "P0.1"]}))
    check("v12 dangling phase blockedBy", "blockedBy 'PX' does not resolve",
          lambda m: m["phases"][0].update(blockedBy=["PX"]))

    # --- new in 0.3.0: cycles ---
    check("c1 two-task dependsOn cycle", "dependency cycle",
          lambda m: (m["phases"][0]["tasks"][0].update(dependsOn=["P0.2"]),
                     m["phases"][0]["tasks"][1].update(dependsOn=["P0.1"])))
    check("c2 self-loop", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(dependsOn=["P0.1"]))
    check("c3 task blockedBy its own phase", "dependency cycle",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=["P0"]))
    check("c4 acyclic chain stays clean", None,
          lambda m: m["phases"][0]["tasks"][1].update(blockedBy=["P0.1"]))

    # --- new in 0.3.0: reciprocity ---
    check("r1 bug->task without task->bug", "link must be reciprocal",
          lambda m: m["phases"][0]["tasks"][1].pop("bugId"))
    check("r2 task->bug without bug->task", "link must be reciprocal",
          lambda m: m["bugs"][0].update(taskId=None))

    # --- new in 0.3.0: fileIndex bidirectional ---
    check("f1 task file missing from fileIndex", "missing from fileIndex",
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/other.ts"]))
    check("f2 line-suffix entries match stripped", None,
          lambda m: m["phases"][0]["tasks"][0].update(files=["src/a.ts:10-20"]))

    # --- new in 0.3.0: tests must be an object ---
    check("t1 tests as string is a finding", "tests must be an object",
          lambda m: m["phases"][0]["tasks"][0].update(tests="tdd"))

    # --- new in 0.5.0: ado link shape ---
    check("a1 valid ado link stays clean", None,
          lambda m: m["phases"][0]["tasks"][0].update(
              ado={"id": 1234, "url": "https://dev.azure.com/o/p/_workitems/edit/1234",
                   "lastSyncedAt": "2026-07-07T00:00:00Z"}))
    check("a2 ado as string is a finding", "ado must be an object",
          lambda m: m["bugs"][0].update(ado="WI-1234"))
    check("a3 non-integer ado.id is a finding", "ado.id must be an integer",
          lambda m: m["phases"][0]["tasks"][0].update(ado={"id": "1234"}))
    check("a4 null ado stays clean", None,
          lambda m: m["bugs"][0].update(ado=None))

    # --- new in 0.3.0: warnings ---
    check("w1 unknown key warns with did-you-mean", None,
          lambda m: m["phases"][0]["tasks"][0].update(dependson=["P0.2"]),
          expect_warning="did you mean 'dependsOn'")
    check("w2 unknown key warns", None,
          lambda m: m["meta"].update(frobnicate=True),
          expect_warning="unknown key 'frobnicate'")
    check("w3 legacy meta keys stay silent", None,
          lambda m: m["meta"].update(signOffChecklist=["x"], statusLegend=["y"]))

    # w5: the 0.5.1/0.6.1-known keys must produce NEITHER findings NOR warnings
    m5 = copy.deepcopy(_valid_manifest())
    m5["meta"].update(gitRoot="test", notes="n")
    m5["phases"][0].update(description="d")
    m5["phases"][0]["tasks"][0].update(details="dt")
    f5, w5warn = validate(m5)
    noise = [x for x in w5warn if any(k in x for k in
             ("gitRoot", "description", "details", "notes"))]
    ok = f5 == [] and noise == []
    results.append(ok)
    print("%s w5 gitRoot/description/details/notes -> no findings, no warnings (%s)"
          % ("PASS" if ok else "FAIL", "clean" if ok else (f5 or noise)))
    check("w4 in_progress task in pending phase warns", None,
          lambda m: m["phases"][0]["tasks"][0].update(status="in_progress"),
          expect_warning="still 'pending'")

    # claim (v0.15 sharded parallel-run coordination)
    check("cl1 valid claim on an active phase stays clean", None,
          lambda m: m["phases"][0].update(
              claim={"sessionId": "s1", "host": "h1", "branch": "audit/p0", "at": "t"}))
    check("cl2 claim not an object is a finding", "claim must be an object",
          lambda m: m["phases"][0].update(claim="whoever"))
    check("cl3 claim missing keys warns", None,
          lambda m: m["phases"][0].update(claim={"at": "t"}),
          expect_warning="claim is missing")
    check("cl4 claim on a done phase warns (stale)", None,
          lambda m: (m["phases"][0].update(
              status="done", claim={"sessionId": "s", "host": "h", "branch": "b"}),
              [t.update(status="done") for t in m["phases"][0]["tasks"]]),
          expect_warning="stale claim")

    # v0.16 — per-phase reviewSkill override + area tag are known keys (no noise)
    m6 = copy.deepcopy(_valid_manifest())
    m6["phases"][0].update(reviewSkill="backend-review", area="backend")
    f6, w6 = validate(m6)
    noise6 = [x for x in w6 if "reviewSkill" in x or "area" in x]
    ok6 = f6 == [] and noise6 == []
    results.append(ok6)
    print("%s pp1 per-phase reviewSkill+area: no finding, no unknown-key warning (%s)"
          % ("PASS" if ok6 else "FAIL", "clean" if ok6 else (f6 or noise6)))

    # v0.28 — the meta.areas registry. The shape rules live in _areas.py and are
    # tested there; what is tested HERE is the wiring, and the one rule that only
    # exists at this level: a warning must never become a finding, because a
    # manifest that stops validating over an informational registry would take the
    # whole pipeline down with it.
    def with_areas(m, areas, area_tag=None):
        m["meta"]["areas"] = areas
        if area_tag is not None:
            m["phases"][0]["area"] = area_tag

    m_reg = copy.deepcopy(_valid_manifest())
    with_areas(m_reg, {"api": {"root": "src", "description": "the api",
                               "reviewSkill": "backend-review",
                               "skills": ["conv"]}}, "api")
    f_reg, w_reg = validate(m_reg)
    # The warning half has to be ASSERTED, not merely mentioned in the label: with
    # only `findings == []` checked, dropping `areas` from KNOWN_META left this
    # green while every registry in the world warned as a typo.
    ok_reg = f_reg == [] and not [x for x in w_reg if "areas" in x]
    results.append(ok_reg)
    print("%s ar1 a registered area is clean - no finding, and no unknown-key "
          "warning for meta.areas itself (%s)"
          % ("PASS" if ok_reg else "FAIL", "clean" if ok_reg else (f_reg or w_reg)))
    check("ar2 a malformed registry IS a finding (shape is not informational)",
          "must be an object",
          lambda m: with_areas(m, {"api": "src"}, "api"))
    check("ar3 a tag with no entry warns, and only warns", None,
          lambda m: with_areas(m, {"api": {"root": "src"}}, "apu"),
          expect_warning="has no entry in meta.areas")
    m_free = copy.deepcopy(_valid_manifest())
    m_free["phases"][0]["area"] = ["anything", "at all"]
    f_free, w_free = validate(m_free)
    ok_free = f_free == [] and not any("meta.areas" in x for x in w_free)
    results.append(ok_free)
    print("%s ar4 free-text tags with NO registry are silent - the v0.16 feature "
          "is not deprecated by this one (%s)"
          % ("PASS" if ok_free else "FAIL", "clean" if ok_free else (f_free or w_free)))
    check("ar5 two areas disagreeing about the reviewer warns, naming the winner "
          "written order picked", None,
          lambda m: with_areas(m, {"a": {"root": "src", "reviewSkill": "ra"},
                                   "b": {"root": "src", "reviewSkill": "rb"}},
                               ["a", "b"]),
          expect_warning='"ra" (from area a) is the one that runs')
    check("ar5b an area that says 'tests are the signer' DISAGREES with one that "
          "names a reviewer, and the message is JSON-spelled - a reader who acts "
          "on it is editing a JSON file, where `None` is not a thing they can type",
          None,
          lambda m: with_areas(m, {"a": {"root": "src", "reviewSkill": None},
                                   "b": {"root": "src", "reviewSkill": "rb"}},
                               ["a", "b"]),
          expect_warning='a=null, b="rb"')
    check("ar6 an area with no root warns rather than failing", None,
          lambda m: with_areas(m, {"api": {"description": "d"}}, "api"),
          expect_warning="no 'root'")
    check("ar7 area as a number is a finding - it would silently belong to no "
          "group and resolve against no area", "area must be a tag or a list",
          lambda m: m["phases"][0].update(area=3))
    check("ar8 an empty tag inside the list is a finding",
          "every area tag must be a non-empty string",
          lambda m: m["phases"][0].update(area=["api", ""]))

    # --- robustness: validate() must NEVER raise on hostile shapes, and the
    #     wrong-type diagnostics must be actionable (regression guard for the
    #     "never raises on arbitrary JSON" contract + schema drift) ---
    check("z1 blockedBy as a bare string is a finding (no per-char iteration)",
          "blockedBy must be an array",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy="P0"))
    check("z2 unhashable blockedBy entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][0].update(blockedBy=[["x"]]))
    check("z3 unhashable dependsOn entry reported, does not crash",
          "must be a string id",
          lambda m: m["phases"][0]["tasks"][1].update(dependsOn=[{"k": "v"}]))
    check("z4 non-array fileIndex value is a finding",
          "must be an array of task ids",
          lambda m: m.update(fileIndex={"src/a.ts": "P0.1"}))
    check("z5 non-array tasks is a finding",
          "tasks must be an array",
          lambda m: m["phases"][0].update(tasks="P0.1"))
    check("z6 boolean version rejected (bool is not a valid int version)",
          "meta.version",
          lambda m: m["meta"].update(version=True))
    # removing tasks orphans fileIndex/bug links, so clear those too and assert
    # the bare "no tasks" case is a WARNING, not a hard finding
    check("z7 absent tasks warns but is not a hard finding", None,
          lambda m: (m.pop("fileIndex", None), m.pop("bugs", None),
                     m["phases"][0].pop("tasks", None)),
          expect_warning="no 'tasks' key")
    check("z8 done phase with a non-done task is a finding",
          "status 'done' but",
          lambda m: m["phases"][0].update(status="done"))

    # --- v0.33: proposals[] lifecycle (parked phases) ---
    def parked(pid="PROP-1", phase_id="P1"):
        return {
            "id": pid, "name": "Security hardening", "status": "proposed",
            "origin": "audit:init", "createdISO": "2026-08-11T00:00:00Z",
            "scope": "src/", "benefit": "fewer injection paths",
            "openQuestions": [],
            "payload": {"phase": {
                "id": phase_id, "title": "Security hardening",
                "status": "pending",
                "tasks": [{"id": phase_id + ".1", "title": "Parameterize SQL",
                           "status": "pending", "tests": {"mode": "tdd"},
                           "files": ["src/db.ts"]}]}},
            "materializedAs": None, "materializedAt": None,
        }

    # pr1: a parked proposal is clean AND none of its keys warn as unknown —
    # asserted like ar1, or dropping a key from KNOWN_PROPOSAL goes unnoticed.
    m_pr = copy.deepcopy(_valid_manifest())
    m_pr["proposals"] = [parked()]
    f_pr, w_pr = validate(m_pr)
    noise_pr = [x for x in w_pr if "proposal" in x.lower()]
    ok_pr = f_pr == [] and noise_pr == []
    results.append(ok_pr)
    print("%s pr1 parked proposal: no finding, no unknown-key warning (%s)"
          % ("PASS" if ok_pr else "FAIL", "clean" if ok_pr else (f_pr or noise_pr)))
    check("pr2 payload phase id colliding with a live phase is a finding",
          "reserved id 'P0' collides",
          lambda m: m.update(proposals=[parked(phase_id="P0")]))
    check("pr3 payload task id colliding with a live task is a finding",
          "reserved id 'P0.1' collides",
          lambda m: m.update(proposals=[
              dict(parked(), payload={"phase": {
                  "id": "P1", "title": "T", "status": "pending",
                  "tasks": [{"id": "P0.1", "title": "dup", "status": "pending"}]}})]))
    check("pr4 dangling materializedAs is a finding",
          "materializedAs 'P9' does not resolve",
          lambda m: m.update(proposals=[
              dict(parked(), status="materialized", materializedAs="P9")]))
    check("pr5 payload-bearing proposal with a bad status is a finding",
          "status 'parked' not in",
          lambda m: m.update(proposals=[dict(parked(), status="parked")]))
    # pr6: legacy free-form proposal (no payload) — warnings at most, NEVER a
    # finding. The back-compat pin: pre-0.33 wrote whatever it liked here.
    m_leg = copy.deepcopy(_valid_manifest())
    m_leg["proposals"] = [{"id": "modernize-build", "name": "Modernize build",
                           "status": "someday", "origin": "audit:init"}]
    f_leg, _w_leg = validate(m_leg)
    ok_leg = f_leg == []
    results.append(ok_leg)
    print("%s pr6 legacy free-form proposal: warnings at most, no finding (%s)"
          % ("PASS" if ok_leg else "FAIL", "clean" if ok_leg else f_leg))
    check("pr7a proposals as a string is a finding", "proposals: not an array",
          lambda m: m.update(proposals="later"))
    check("pr7b a non-object entry is a finding", "proposals[0]: not an object",
          lambda m: m.update(proposals=["later"]))
    check("pr8 duplicate PROP id is a finding", "duplicate proposal id: PROP-1",
          lambda m: m.update(proposals=[parked(), parked(phase_id="P2")]))
    # pr9: THE declined-init pin — meta + empty phases + parked proposals is a
    # fully valid manifest (the park-all write path of /audit:init).
    m_empty = {"meta": {"version": 2}, "phases": [], "fileIndex": {},
               "bugs": [], "proposals": [parked()]}
    f_empty, _w_empty = validate(m_empty)
    ok_empty = f_empty == []
    results.append(ok_empty)
    print("%s pr9 meta + empty phases + parked proposals validates clean (%s)"
          % ("PASS" if ok_empty else "FAIL", "clean" if ok_empty else f_empty))
    check("pr10 materializedAs set while status is still 'proposed' is a finding",
          "must be 'materialized'",
          lambda m: m.update(proposals=[dict(parked(), materializedAs="P0")]))
    check("pr11 two proposals reserving the same phase id is a finding",
          "already reserved by another proposal",
          lambda m: m.update(proposals=[parked(), parked(pid="PROP-2")]))
    # pr12: staged blockedBy — a ref to another proposal's reserved id is clean;
    # a ref naming nothing anywhere warns (staged, not live) but never fails.
    m_ref = copy.deepcopy(_valid_manifest())
    p_a, p_b = parked(), parked(pid="PROP-2", phase_id="P2")
    p_b["payload"]["phase"]["blockedBy"] = ["P1"]
    m_ref["proposals"] = [p_a, p_b]
    f_ref, w_ref = validate(m_ref)
    ok_ref = f_ref == [] and not any("blockedBy" in x for x in w_ref)
    results.append(ok_ref)
    print("%s pr12a staged blockedBy to another reserved id is clean (%s)"
          % ("PASS" if ok_ref else "FAIL", "clean" if ok_ref else (f_ref or w_ref)))
    m_ref2 = copy.deepcopy(_valid_manifest())
    p_c = parked()
    p_c["payload"]["phase"]["blockedBy"] = ["P77"]
    m_ref2["proposals"] = [p_c]
    f_ref2, w_ref2 = validate(m_ref2)
    ok_ref2 = f_ref2 == [] and any("P77" in x for x in w_ref2)
    results.append(ok_ref2)
    print("%s pr12b staged blockedBy naming nothing warns, never fails (%s)"
          % ("PASS" if ok_ref2 else "FAIL",
             "clean+warned" if ok_ref2 else (f_ref2 or w_ref2)))
    # pr13: a materialized proposal whose payload id now lives as a real phase
    # must NOT be reported as a collision (that collision is the SUCCESS state).
    m_mat = copy.deepcopy(_valid_manifest())
    mat = parked(phase_id="P0")
    mat.update(status="materialized", materializedAs="P0",
               materializedAt="2026-08-11T00:00:00Z")
    m_mat["proposals"] = [mat]
    f_mat, _w_mat = validate(m_mat)
    ok_mat = f_mat == []
    results.append(ok_mat)
    print("%s pr13 materialized proposal: live payload id is not a collision (%s)"
          % ("PASS" if ok_mat else "FAIL", "clean" if ok_mat else f_mat))

    # --- workstream B: task moves (id-prefix rule + movedFrom) ---
    # The id rule is the hand-move detector: /audit:task move renumbers a task
    # into its new phase, so an id that does not match its phase means someone
    # dragged the object by hand. A WARNING, never a finding -- legacy
    # manifests with free-form ids must not go red over bookkeeping.
    check("mv1 a task id that does not follow its phase's prefix warns only",
          None,
          lambda m: m["phases"][0]["tasks"].append(
              {"id": "ODD-7", "title": "stray", "status": "pending"}),
          expect_warning="does not follow its phase")
    m_mv = copy.deepcopy(_valid_manifest())
    m_mv["phases"][0]["tasks"][0]["movedFrom"] = {
        "id": "P3.4", "phase": "P3", "at": "2026-08-11T00:00:00Z"}
    f_mv, w_mv = validate(m_mv)
    noise_mv = [x for x in w_mv if "movedFrom" in x]
    ok_mv = f_mv == [] and noise_mv == []
    results.append(ok_mv)
    print("%s mv2 a well-formed movedFrom is clean - no finding, no "
          "unknown-key warning (%s)"
          % ("PASS" if ok_mv else "FAIL",
             "clean" if ok_mv else (f_mv or noise_mv)))
    check("mv3 movedFrom that is not an object warns, and only warns", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom="P3.4"),
          expect_warning="movedFrom")
    check("mv3b movedFrom missing its keys warns, naming them", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom={"id": "P3.4"}),
          expect_warning="movedFrom is missing")
    check("mv4 movedFrom null is clean (the schema says object|null)", None,
          lambda m: m["phases"][0]["tasks"][0].update(movedFrom=None))
    # The base fixture itself must not warn: P0.1/P0.2 follow P0.
    _f_base, _w_base = validate(copy.deepcopy(_valid_manifest()))
    ok_base = _f_base == [] and not any("does not follow" in x
                                       for x in _w_base)
    results.append(ok_base)
    print("%s mv5 existing well-formed ids produce no id-prefix warning (%s)"
          % ("PASS" if ok_base else "FAIL",
             "clean" if ok_base else (_f_base or _w_base)))

    # --- md: intra-manifest model-id near-miss (typo detector) ---
    # WARNING only, and only for a value used EXACTLY once beside a
    # case-insensitive / edit-distance-1 neighbour used elsewhere in the
    # manifest or among meta.usage.pricing keys. Deliberately intra-manifest:
    # this validator is an offline shape-checker and never reads the config or
    # the ledger, so the three-source model hint lives in the panel instead.
    def _mk_md1(m):
        t = m["phases"][0]["tasks"]
        t[0]["model"] = "claude-opus-5"
        t[1]["model"] = "claude-opus-5"
        t.append({"id": "P0.3", "title": "typo", "status": "pending",
                  "model": "claude-opsu-5"})
    check("md1 a once-used model one edit from an established one warns",
          None, _mk_md1, expect_warning="'claude-opsu-5'")
    def _mk_md2(m):
        t = m["phases"][0]["tasks"]
        t[0]["model"] = "sonnet"
        t[1]["model"] = "Sonnet"
    check("md2 a case-only near-miss used once warns", None, _mk_md2,
          expect_warning="'Sonnet'")
    # md3: a clean single-model manifest never draws this (the mv5 pattern) --
    # there is no second spelling to near-miss against.
    m_md = copy.deepcopy(_valid_manifest())
    for _t in m_md["phases"][0]["tasks"]:
        _t["model"] = "claude-opus-5"
    f_md, w_md = validate(m_md)
    noise_md = [x for x in w_md if "model" in x]
    ok_md = f_md == [] and noise_md == []
    results.append(ok_md)
    print("%s md3 a clean single-model manifest draws no model warning (%s)"
          % ("PASS" if ok_md else "FAIL",
             "clean" if ok_md else (f_md or noise_md)))
    def _mk_md4(m):
        m["meta"]["usage"] = {"pricing": {"claude-haiku-4-5": {"in": 1.0}}}
        m["phases"][0]["tasks"][0]["model"] = "claude-haiku-45"
    check("md4 a once-used near-miss of a meta.usage.pricing key warns",
          None, _mk_md4, expect_warning="'claude-haiku-45'")
    # md5: a value used twice is an established spelling, not a slip -- even
    # one edit away from another established one.
    m_md5 = copy.deepcopy(_valid_manifest())
    _ts = m_md5["phases"][0]["tasks"]
    _ts[0]["model"] = "claude-opus-5"
    _ts[1]["model"] = "claude-opus-5"
    _ts.append({"id": "P0.3", "title": "x", "status": "pending",
                "model": "claude-opsu-5"})
    _ts.append({"id": "P0.4", "title": "y", "status": "pending",
                "model": "claude-opsu-5"})
    f_md5, w_md5 = validate(m_md5)
    noise_md5 = [x for x in w_md5 if "is used once" in x]
    ok_md5 = f_md5 == [] and noise_md5 == []
    results.append(ok_md5)
    print("%s md5 a spelling used twice is established, never flagged (%s)"
          % ("PASS" if ok_md5 else "FAIL",
             "clean" if ok_md5 else (f_md5 or noise_md5)))
    def _mk_md6(m):
        m["phases"][0]["review"] = {"model": "claude-opus5"}
        for t in m["phases"][0]["tasks"]:
            t["model"] = "claude-opus-5"
    check("md6 a phase review model near-missing the task model warns, "
          "naming the phase", None, _mk_md6, expect_warning="phase P0 review")

    # --- sk: unresolved-skills advisory (v0.37 B2) ---
    # WARNING only, and GATED: it exists only in a manifest that uses skills
    # somewhere (a non-empty task.skills, an explicit null, or an area that
    # declares defaults). A project ignoring the feature gets zero new lines --
    # and `skills: []` alone does NOT switch it on, because generators
    # initialize empty lists on every task.
    m_sk0 = copy.deepcopy(_valid_manifest())
    f_sk0, w_sk0 = validate(m_sk0)
    ok_sk0 = f_sk0 == [] and not any("skills" in x for x in w_sk0)
    results.append(ok_sk0)
    print("%s sk1 a manifest that uses no skills anywhere draws no skills "
          "warning - the gate, and the back-compat pin (%s)"
          % ("PASS" if ok_sk0 else "FAIL",
             "clean" if ok_sk0 else (f_sk0 or w_sk0)))
    check("sk2 with skills in use, a task resolving to nothing warns, naming "
          "what was consulted and the three exits", None,
          lambda m: m["phases"][0]["tasks"][0].update(skills=["conv"]),
          expect_warning="task P0.2: no skills resolve")
    m_sk3 = copy.deepcopy(_valid_manifest())
    m_sk3["phases"][0]["tasks"][0]["skills"] = ["conv"]
    m_sk3["phases"][0]["tasks"][1]["skills"] = None
    f_sk3, w_sk3 = validate(m_sk3)
    ok_sk3 = f_sk3 == [] and not any("no skills resolve" in x for x in w_sk3)
    results.append(ok_sk3)
    print("%s sk3 an explicit null is an ANSWER - the opted-out task is not "
          "'unresolved' and draws nothing (%s)"
          % ("PASS" if ok_sk3 else "FAIL",
             "clean" if ok_sk3 else (f_sk3 or w_sk3)))
    m_sk4 = copy.deepcopy(_valid_manifest())
    m_sk4["meta"]["areas"] = {"api": {"root": "src", "skills": ["conv"]}}
    m_sk4["phases"][0]["area"] = "api"
    f_sk4, w_sk4 = validate(m_sk4)
    ok_sk4 = f_sk4 == [] and not any("no skills resolve" in x for x in w_sk4)
    results.append(ok_sk4)
    print("%s sk4 an area default RESOLVES - tasks under a skills-declaring "
          "area are covered, not warned about (%s)"
          % ("PASS" if ok_sk4 else "FAIL",
             "clean" if ok_sk4 else (f_sk4 or w_sk4)))
    check("sk5 the registry alone arms the gate: areas declare skills but the "
          "phase is untagged, so nothing reaches its tasks", None,
          lambda m: m["meta"].update(
              areas={"api": {"root": "src", "skills": ["conv"]}}),
          expect_warning="phase has no area tag")
    check("sk6 a wrong-typed task.skills warns (and only warns) - it is use "
          "evidence, and resolution loads nothing from it", None,
          lambda m: m["phases"][0]["tasks"][0].update(skills="conv"),
          expect_warning="skills must be an array")

    # --- sn: intra-manifest skill-name near-miss (the md detector, applied
    #     to skill names; inventory-based hints stay the panel's) ---
    def _sn_base(m, once, where="task"):
        t = m["phases"][0]["tasks"]
        t[0]["skills"] = ["python-conventions"]
        t[1]["skills"] = ["python-conventions"]
        if where == "task":
            t.append({"id": "P0.3", "title": "typo", "status": "pending",
                      "skills": [once]})
        else:
            m["meta"]["areas"] = {"api": {"root": "src", "skills": [once]}}
    check("sn1 a once-used skill one slip from an established one warns",
          None, lambda m: _sn_base(m, "pyton-conventions"),
          expect_warning="'pyton-conventions'")
    check("sn2 two slips warn too, on names long enough to carry them",
          None, lambda m: _sn_base(m, "pyton-conventons"),
          expect_warning="'pyton-conventons'")
    m_sn3 = copy.deepcopy(_valid_manifest())
    t_sn3 = m_sn3["phases"][0]["tasks"]
    t_sn3[0]["skills"] = ["web"]
    t_sn3[1]["skills"] = ["web"]
    t_sn3.append({"id": "P0.3", "title": "x", "status": "pending",
                  "skills": ["wasm"]})
    f_sn3, w_sn3 = validate(m_sn3)
    ok_sn3 = f_sn3 == [] and not any("near-miss" in x for x in w_sn3)
    results.append(ok_sn3)
    print("%s sn3 two slips on SHORT names stay silent - 'web' vs 'wasm' is "
          "distance 2 and pure noise (%s)"
          % ("PASS" if ok_sn3 else "FAIL",
             "clean" if ok_sn3 else (f_sn3 or w_sn3)))
    m_sn4 = copy.deepcopy(_valid_manifest())
    t_sn4 = m_sn4["phases"][0]["tasks"]
    t_sn4[0]["skills"] = ["python-conventions"]
    t_sn4[1]["skills"] = ["python-conventions"]
    t_sn4.append({"id": "P0.3", "title": "x", "status": "pending",
                  "skills": ["pyton-conventions"]})
    t_sn4.append({"id": "P0.4", "title": "y", "status": "pending",
                  "skills": ["pyton-conventions"]})
    f_sn4, w_sn4 = validate(m_sn4)
    ok_sn4 = f_sn4 == [] and not any("near-miss" in x for x in w_sn4)
    results.append(ok_sn4)
    print("%s sn4 a spelling used twice is established, never flagged - the "
          "md5 rule (%s)"
          % ("PASS" if ok_sn4 else "FAIL",
             "clean" if ok_sn4 else (f_sn4 or w_sn4)))
    check("sn5 an area-declared skill is a site too, and the warning names it",
          None, lambda m: _sn_base(m, "pyton-conventions", where="area"),
          expect_warning="meta.areas.api")

    # --- im: meta.ado.identityMap shape (v0.38 C) ---
    # Shape only: the map's USE is advisory (/audit:sync proposes, never
    # assigns), but a malformed map is a structural defect like any other
    # wrong type in this file. No email-shape policing -- an ADO identity is
    # whatever the org's directory says it is.
    def _with_imap(m, imap):
        m["meta"]["ado"] = {"organization": "o", "project": "p",
                            "identityMap": imap}

    # (ma) meta.ado itself has a shape - "ado": "org" used to draw neither
    # finding nor warning ("ado" sits in KNOWN_META; _check_ado covered only
    # item-level links), so _check_identity_map inherited the blind spot by
    # silently returning on a non-dict. F-C-1 of the v0.38 round.
    m_ma1 = copy.deepcopy(_valid_manifest())
    m_ma1["meta"]["ado"] = "my-org"
    f_ma1, _ = validate(m_ma1)
    ok_ma1 = any("meta: ado must be an object or null" in x for x in f_ma1)
    results.append(ok_ma1)
    print("%s ma1 meta.ado as a bare string is a FINDING - a config that "
          "would be misread" % ("PASS" if ok_ma1 else "FAIL"))
    m_ma2 = copy.deepcopy(_valid_manifest())
    m_ma2["meta"]["ado"] = None
    f_ma2, w_ma2 = validate(m_ma2)
    ok_ma2 = not any("ado" in x for x in f_ma2 + w_ma2)
    results.append(ok_ma2)
    print("%s ma2 meta.ado null (and absent) stays silent - an answer, not "
          "a miss" % ("PASS" if ok_ma2 else "FAIL"))

    m_im1 = copy.deepcopy(_valid_manifest())
    _with_imap(m_im1, {"alice@corp.dev": "alice@corp.example.com",
                       "bob@corp.dev": "bob@corp.example.com"})
    f_im1, w_im1 = validate(m_im1)
    noise_im1 = [x for x in w_im1 if "identityMap" in x]
    ok_im1 = f_im1 == [] and noise_im1 == []
    results.append(ok_im1)
    print("%s im1 a well-formed identityMap is clean - no finding, no warning (%s)"
          % ("PASS" if ok_im1 else "FAIL",
             "clean" if ok_im1 else (f_im1 or noise_im1)))
    check("im2 identityMap as a string is a finding",
          "identityMap: must be an object",
          lambda m: _with_imap(m, "alice=alice@corp.example.com"))
    check("im3 a non-string value is a finding",
          "value must be a non-empty ADO identity string",
          lambda m: _with_imap(m, {"alice@corp.dev": 42}))
    check("im4 an empty value is a finding",
          "value must be a non-empty ADO identity string",
          lambda m: _with_imap(m, {"alice@corp.dev": "  "}))
    check("im5 an empty key is a finding",
          "keys must be non-empty ledger identity strings",
          lambda m: _with_imap(m, {"": "alice@corp.example.com"}))
    check("im6 two keys sharing one ADO identity warn, and only warn", None,
          lambda m: _with_imap(m, {"alice@corp.dev": "shared@corp.example.com",
                                   "bob@corp.dev": "shared@corp.example.com"}),
          expect_warning="is the target of 2 ledger identities")
    check("im7 null identityMap is clean (an answer, like ado: null)", None,
          lambda m: _with_imap(m, None))
    m_im8 = copy.deepcopy(_valid_manifest())
    m_im8["meta"]["ado"] = {"organization": "o", "project": "p"}
    f_im8, w_im8 = validate(m_im8)
    noise_im8 = [x for x in w_im8 if "identityMap" in x]
    ok_im8 = f_im8 == [] and noise_im8 == []
    results.append(ok_im8)
    print("%s im8 meta.ado without an identityMap draws nothing - the "
          "back-compat pin (%s)"
          % ("PASS" if ok_im8 else "FAIL",
             "clean" if ok_im8 else (f_im8 or noise_im8)))

    # --- av: meta.ado connector v2 config shape ---
    # The v2 keys (enabled/echo/phaseWorkItems/stateMap/onComplete/comments/
    # sprint/pull) are checked by check_ado_meta -- ONE front door shared with
    # the panel's write_ado, so the CLI and the panel cannot disagree about
    # what a valid connector config is.
    def _with_ado(m, **kw):
        ado = {"organization": "o", "project": "p"}
        ado.update(kw)
        m["meta"]["ado"] = ado

    m_av1 = copy.deepcopy(_valid_manifest())
    _with_ado(m_av1, enabled=True, echo=False, phaseWorkItems=True,
              types={"bug": "Bug", "task": "Task", "pbi": None},
              stateMap={"task": {"done": "Review", "blocked": None},
                        "bug": {"fixed": "Resolved"}},
              onComplete={"remainingWork": 0},
              comments={"onBlocked": True, "onComplete": False},
              sprint={"team": "Web", "mode": "current"},
              pull={"areaPath": "Proj\\Team", "tags": ["repo-x"]})
    f_av1, w_av1 = validate(m_av1)
    noise_av1 = [x for x in w_av1 if "ado" in x]
    ok_av1 = f_av1 == [] and noise_av1 == []
    results.append(ok_av1)
    print("%s av1 a full well-formed v2 connector config is clean - no "
          "finding, no warning (%s)"
          % ("PASS" if ok_av1 else "FAIL",
             "clean" if ok_av1 else (f_av1 or noise_av1)))
    m_av2 = copy.deepcopy(_valid_manifest())
    m_av2["meta"]["ado"] = {"organization": "o", "project": "p",
                            "stateMap": None, "onComplete": None,
                            "comments": None, "sprint": None, "pull": None}
    f_av2, w_av2 = validate(m_av2)
    noise_av2 = [x for x in w_av2 if "ado" in x]
    ok_av2 = f_av2 == [] and noise_av2 == []
    results.append(ok_av2)
    print("%s av2 every nullable v2 key accepts null - an answer, not a "
          "miss (%s)"
          % ("PASS" if ok_av2 else "FAIL",
             "clean" if ok_av2 else (f_av2 or noise_av2)))
    check("av3 typo 'statemap' warns with did-you-mean", None,
          lambda m: _with_ado(m, statemap={"task": {"done": "Review"}}),
          expect_warning="did you mean 'stateMap'")
    check("av4 typo 'identitymap' warns with did-you-mean", None,
          lambda m: _with_ado(m, identitymap={"a": "b"}),
          expect_warning="did you mean 'identityMap'")
    check("av5 enabled as a string is a finding",
          "enabled: must be true or false",
          lambda m: _with_ado(m, enabled="yes"))
    check("av6 stateMap as a string is a finding",
          "stateMap: must be an object",
          lambda m: _with_ado(m, stateMap="done=Closed"))
    check("av7 a status key outside the vocabulary warns with did-you-mean",
          None,
          lambda m: _with_ado(m, stateMap={"task": {"Done": "Closed"}}),
          expect_warning="did you mean 'done'")
    check("av8 an empty stateMap value is a finding",
          "must be an ADO state name or null",
          lambda m: _with_ado(m, stateMap={"task": {"done": "  "}}))
    check("av9 negative remainingWork is a finding",
          "remainingWork: must be a number >= 0 or null",
          lambda m: _with_ado(m, onComplete={"remainingWork": -1}))
    check("av10 boolean remainingWork is a finding (bool is not a number "
          "here)",
          "remainingWork: must be a number >= 0 or null",
          lambda m: _with_ado(m, onComplete={"remainingWork": True}))
    check("av11 sprint without a team is a finding",
          "sprint: requires a non-empty 'team'",
          lambda m: _with_ado(m, sprint={"mode": "current"}))
    check("av12 sprint mode outside the enum is a finding",
          "sprint.mode: must be 'current'",
          lambda m: _with_ado(m, sprint={"team": "Web", "mode": "path"}))
    check("av13 an empty pull tag is a finding",
          "pull.tags: every tag must be a non-empty string",
          lambda m: _with_ado(m, pull={"tags": ["repo-x", ""]}))
    check("av14 comments.onBlocked as a string is a finding",
          "comments.onBlocked: must be true or false",
          lambda m: _with_ado(m, comments={"onBlocked": "yes"}))
    check("av15 a non-string types value is a finding",
          "types: every value must be a work-item type name",
          lambda m: _with_ado(m, types={"bug": 42}))
    # phase-level ado link (phaseWorkItems writes phase.ado)
    check("av16 a valid phase ado link stays clean", None,
          lambda m: m["phases"][0].update(
              ado={"id": 7, "url": None, "lastSyncedAt": None,
                   "iterationPath": "Proj\\Sprint 9"}))
    check("av17 phase ado as a string is a finding",
          "phase P0: ado must be an object",
          lambda m: m["phases"][0].update(ado="WI-7"))
    # F1 (live gate): phase PBIs have their OWN state vocabulary - a third
    # stateMap block, keyed by the same status names tasks use.
    check("av18 a stateMap.phase block is clean and known", None,
          lambda m: _with_ado(m, stateMap={"phase": {"done": "Done",
                                                     "in_progress": None}}))
    check("av19 an unknown status inside stateMap.phase warns did-you-mean",
          None,
          lambda m: _with_ado(m, stateMap={"phase": {"Done": "Done"}}),
          expect_warning="did you mean 'done'")
    # ENH-1: the personalizable provenance tag.
    check("av20 a custom tag is clean and null (no tag) is an answer", None,
          lambda m: _with_ado(m, tag="repo-storefront"))
    check("av21 tag null stays clean", None,
          lambda m: _with_ado(m, tag=None))
    check("av22 an empty tag string is a finding",
          "tag: must be a non-empty string or null",
          lambda m: _with_ado(m, tag="  "))

    # --- CLI exit codes: 0 valid · 1 findings · 2 usage/unreadable ---
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_valid_manifest(), fh)
    ok = main([path]) == 0
    results.append(ok)
    print("%s c5 CLI accepts valid file (exit 0)" % ("PASS" if ok else "FAIL"))
    bad = copy.deepcopy(_valid_manifest())
    bad["phases"][0]["tasks"][0]["status"] = "doing"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    ok = main([path]) == 1
    results.append(ok)
    print("%s c6 CLI reports findings (exit 1)" % ("PASS" if ok else "FAIL"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    ok = main([path]) == 2
    results.append(ok)
    print("%s c7 CLI rejects unparseable file (exit 2)" % ("PASS" if ok else "FAIL"))
    ok = main([]) == 2
    results.append(ok)
    print("%s c8 CLI usage error (exit 2)" % ("PASS" if ok else "FAIL"))
    os.unlink(path)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
