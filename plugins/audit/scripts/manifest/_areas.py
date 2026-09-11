#!/usr/bin/env python3
"""
The `meta.areas` registry and everything that resolves against it — stdlib only.

A phase has carried an `area` tag since v0.16: free text, one string or a list,
purely a grouping label for status/report/panel. That is enough to SEE a monorepo
and not enough to work in one. `meta.areas` is the other half — the place a tag
becomes a thing with properties:

    "areas": {
      "api":    {"root": "services/api", "description": "Django service",
                 "reviewSkill": "backend-review", "skills": ["python-conventions"]},
      "mobile": {"root": "apps/mobile",  "description": "Expo app"}
    }

Registration stays OPTIONAL in both directions, and that is deliberate. A tag with
no entry is still legal (the validator warns, nothing refuses); a registry entry
with no phase using it is legal too. The v0.16 behaviour is what you get by writing
nothing, so no existing manifest changes meaning by upgrading.

What registration buys is resolution — two questions the orchestrator asks per
phase, whose answers used to have exactly one source:

  review skill   phase.reviewSkill ?? areas[tag].reviewSkill ?? meta.reviewSkill
  executor skills   area skills (tag order) + task.skills, deduped, area first

Both are implemented HERE, once, and every surface that shows an answer shows this
one. `resolve_review_skill` returns the basis alongside the value — "area api", not
just "backend-review" — because a phase whose reviewer was chosen three levels away
is otherwise a reviewer nobody can explain.

**Precedence among several tags is written order.** A phase tagged
`["api", "mobile"]` where both areas declare a reviewSkill takes `api`'s, because it
is written first. Any rule here is arbitrary; what matters is that it is stated,
deterministic, and *visible* — `review_skill_conflicts()` finds exactly this case so
the validator can warn instead of letting the tie-break stay silent.

Paths are PROJECT-DIR-RELATIVE, the same as `task.files` and the `fileIndex` keys
(so they carry the `meta.gitRoot` prefix when the workspace sits in a subdirectory).
An absolute root would not survive a second clone; the validator says so.

**AND IT HOLDS THE ORCHESTRATOR'S CLAIMS TO THE CODE** — `rule_drift` at the
bottom, plus the section-scoped `claim_drift`/`anchor_coverage` beside it. That
is a second subject in one module and it is here on purpose rather than in a new
file: `rule_drift` was already here, because the reviewSkill resolution is
implemented here and the rule had to be pinned next to the thing that executes
it, and the anchors are the same mechanism widened — a document makes a claim,
the code says what is true, the two are compared every run. A separate module
would put the mechanism one import away from its one working example and owe the
build guide a section for the privilege. Print what is covered rather than
trusting a sentence about it:

    python3 plugins/audit/scripts/manifest/_areas.py --coverage

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__areas.py`, byte-identical labels and all - see
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

# Keys an area entry may carry. Unknown ones warn — a typo'd `reviewskill` would
# otherwise be a reviewer that silently never runs.
KNOWN_AREA = ("root", "description", "reviewSkill", "skills", "owner")


# --- normalisation ------------------------------------------------------------
def _norm_tag(tag):
    """A tag as it is compared: whitespace-trimmed, or "" if it is not a tag.

    Trimming matters because both sides of every lookup come from hand-written
    JSON: `"area": " api"` on a phase and `"api"` in the registry are the same
    tag to a reader, and a difference nobody can see is the worst kind."""
    return tag.strip() if isinstance(tag, str) else ""


def areas_of(area):
    """A phase's `area` (string, list, or absent) -> its tags, in written order.

    Trimmed, empties dropped, and DEDUPED: `["api","api"]` is one tag, not two.
    Before this was deduped, a repeated tag counted its phase twice in the status
    rollup's per-area totals — a phase that was 1-of-1 done reading 2/2."""
    raw = [area] if isinstance(area, str) else (area if isinstance(area, list) else [])
    out = []
    for tag in raw:
        t = _norm_tag(tag)
        if t and t not in out:
            out.append(t)
    return out


# --- registry access ----------------------------------------------------------
def registry(manifest):
    """`meta.areas` as a tag -> entry dict, with the junk dropped rather than raised on.

    Accepts a whole manifest or a bare `meta` (the panel holds one, the validator
    the other). Tags are normalised on the way out so a lookup cannot miss by a
    space. Malformed entries are skipped here and REPORTED by validate_registry —
    resolution must never raise on a manifest the validator has only warned about.
    """
    if not isinstance(manifest, dict):
        return {}
    meta = manifest.get("meta")
    src = meta if isinstance(meta, dict) else manifest
    areas = src.get("areas")
    if not isinstance(areas, dict):
        return {}
    out = {}
    for tag, entry in areas.items():
        t = _norm_tag(tag)
        if t and isinstance(entry, dict):
            out[t] = entry
    return out


def entry_of(manifest, tag):
    """One registered area, or {} — never None, so callers can `.get` freely."""
    return registry(manifest).get(_norm_tag(tag)) or {}


def root_of(entry):
    """An area's root as a clean relative path, or "" when it declares none."""
    root = (entry or {}).get("root")
    if not isinstance(root, str) or not root.strip():
        return ""
    return root.strip().replace("\\", "/").rstrip("/") or "."


# --- review skill resolution --------------------------------------------------
def _declared_skill(val):
    """A declared reviewSkill as resolution returns it: a non-empty trimmed
    string, or None. An explicit null is an answer ("not this one") and stays
    None; a NON-STRING is the validator's finding (`must be a skill name or
    null`) and must not reach display surfaces raw — `reviewSkill: 3` used to
    come out of the lookup as the integer 3 (v0.36 A5). Same hardening
    `owner_of` got in group o: invalid -> None, the basis still names the level
    that declared it."""
    if isinstance(val, str):
        return val.strip() or None
    return None


def resolve_review_skill(manifest, phase):
    """(skill, basis) for a phase's sign-off reviewer.

    `phase.reviewSkill ?? areas[tag].reviewSkill ?? meta.reviewSkill`, with the tags
    tried in written order. `basis` names the level that answered — "phase",
    "area <tag>", "meta", or "" when nothing did — so every surface can print WHY
    this reviewer, which is the whole reason a three-level lookup is tolerable.

    A level that is present and explicitly null is an answer, not a miss: setting
    `phase.reviewSkill: null` on one phase of a reviewed project is how you say
    "not this one", and falling through to the area would ignore it. A declared
    value that is not a string is treated the same way (see _declared_skill):
    the level answered, the answer is None, and the validator names the typo.
    """
    phase = phase if isinstance(phase, dict) else {}
    if "reviewSkill" in phase:
        return _declared_skill(phase.get("reviewSkill")), "phase"
    for tag in areas_of(phase.get("area")):
        entry = entry_of(manifest, tag)
        if "reviewSkill" in entry:
            return _declared_skill(entry.get("reviewSkill")), "area %s" % tag
    meta = (manifest or {}).get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "reviewSkill" in meta:
        return _declared_skill(meta.get("reviewSkill")), "meta"
    return None, ""


# --- owner resolution -----------------------------------------------------------
def owner_of(manifest, phase):
    """(owner, tag) for the phase's advisory area owner.

    The tags are tried in written order and the FIRST entry that declares an
    `owner` key answers — the same lookup shape as `resolve_review_skill`, for the
    same reason: any tie-break is arbitrary, so it must be the stated one. A tag
    whose entry has no `owner` key is skipped, not treated as "nobody". An entry
    with an explicit `owner: null` IS an answer — "nobody owns this" — and stops
    the lookup: the returned tag names the area that said so, which is how callers
    tell (None, "api") apart from (None, "") — nothing declared anywhere.

    Advisory by construction: the only consumers are a heads-up note, status
    lines and panel labels. Nothing gates on the return value."""
    phase = phase if isinstance(phase, dict) else {}
    for tag in areas_of(phase.get("area")):
        entry = entry_of(manifest, tag)
        if "owner" in entry:
            owner = entry.get("owner")
            if isinstance(owner, str):
                owner = owner.strip() or None
            else:
                owner = None  # null, or a shape the validator reports
            return owner, tag
    return None, ""


# --- skills resolution --------------------------------------------------------
def skills_opted_out(task):
    """True iff the task carries an explicit `skills: null` — the opt-out.

    Null is an ANSWER ("no skills apply to this task") and STOPS the area
    fallback, mirroring reviewSkill and owner. It is distinguishable from `[]`
    and from an absent key, which both mean "unconsidered" and leave the area
    default in force. A junk-typed value is neither: not an answer (the
    validator names it), not an opt-out. This predicate is how display surfaces
    name the state ("none — opted out") instead of rendering it as empty."""
    t = task if isinstance(task, dict) else {}
    return "skills" in t and t.get("skills") is None


def resolve_skills(manifest, phase, task):
    """The skills an executor subagent loads: area defaults first, then the task's.

    Area first because an area skill is the house style ("this service is Django,
    read these conventions") and the task's are the specifics — a subagent that
    reads the specifics before the conventions has already made the decisions the
    conventions were meant to inform. Deduped, first occurrence wins, so naming a
    skill in both places is a no-op rather than a double load.

    `task.skills: null` is a conscious opt-out and resolves to [] REGARDLESS of
    what the areas declare — stopping the fallback is the point, the same
    answer-not-a-miss rule reviewSkill and owner follow; `skills_opted_out` is
    the basis a display can name. `[]`/absent stays "unconsidered": the area
    default applies. An area-level null contributes nothing and stops nothing —
    the area IS the fallback, so at that level null and [] are equivalent (the
    schema says so too). A non-list container (a bare string, say) contributes
    nothing rather than iterating per character, which is what `or []` used to
    let it do.
    """
    if skills_opted_out(task):
        return []
    out = []
    for tag in areas_of((phase or {}).get("area")):
        skills = entry_of(manifest, tag).get("skills")
        for skill in (skills if isinstance(skills, list) else []):
            if isinstance(skill, str) and skill.strip() and skill.strip() not in out:
                out.append(skill.strip())
    tskills = (task or {}).get("skills")
    for skill in (tskills if isinstance(tskills, list) else []):
        if isinstance(skill, str) and skill.strip() and skill.strip() not in out:
            out.append(skill.strip())
    return out


def plan_skill_refs(manifest):
    """`[(where, name), ...]` — every skill this plan NAMES, once per name.

    The EFFECTIVE names, resolved through the two functions above, so an area
    default is listed exactly as it will apply rather than as it is written.

    ONE ROW PER NAME, not per reference, and the first mention keeps the label: a
    review skill inherited by every phase is one thing to install, and a surface
    printing it once per phase is a wall of identical lines.

    It lives here because two surfaces ask it — `/audit:doctor` and the status
    gate's portability block — and they must not be able to disagree about which
    names a plan uses. It was written out inside the doctor first; the second
    caller is what made it a shared fact rather than a local loop.
    """
    out, seen = [], set()
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        pid = phase.get("id") or "?"
        skill, _basis = resolve_review_skill(manifest, phase)
        refs = []
        if skill:
            refs.append(("%s review skill" % pid, skill))
        for task in (phase.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            for name in resolve_skills(manifest, phase, task):
                refs.append(("%s skill" % (task.get("id") or pid), name))
        for where, name in refs:
            if name not in seen:
                seen.add(name)
                out.append((where, name))
    return out


# --- conflicts + unregistered tags --------------------------------------------
def review_skill_conflicts(manifest, phase):
    """[(tag, skill), ...] when a phase's areas disagree about its reviewer.

    Returned only when there is a real disagreement — two or more registered areas
    on one phase declaring DIFFERENT reviewSkills. Written order decides it, and
    this is what lets the validator say so out loud instead of the loser being
    dropped in silence.
    """
    seen = []
    for tag in areas_of((phase or {}).get("area")):
        entry = entry_of(manifest, tag)
        if "reviewSkill" in entry:
            seen.append((tag, entry.get("reviewSkill")))
    if len({s for _, s in seen}) > 1:
        return seen
    return []


def unregistered_tags(manifest):
    """[(phaseId, tag), ...] for tags no registry entry covers — in phase order.

    Empty when the manifest registers no areas at all: free-text tagging is the
    v0.16 feature and stays legal. The warning is for the project that HAS a
    registry, where an unregistered tag is nearly always a typo of a registered
    one — and a typo'd tag resolves to no area, which means the reviewer and the
    skills the author expected silently do not happen.
    """
    reg = registry(manifest)
    if not reg:
        return []
    out = []
    for phase in (manifest or {}).get("phases") or []:
        if not isinstance(phase, dict):
            continue
        for tag in areas_of(phase.get("area")):
            if tag not in reg:
                out.append((phase.get("id") or "?", tag))
    return out


def used_tags(manifest):
    """Every tag any phase carries, in first-seen order (registered or not)."""
    out = []
    for phase in (manifest or {}).get("phases") or []:
        if isinstance(phase, dict):
            for tag in areas_of(phase.get("area")):
                if tag not in out:
                    out.append(tag)
    return out


def phase_tags(manifest):
    """{phaseId: [tags]} for every phase — the read-time join key that attributes
    ledger spend to areas (`row.phaseId -> phase.area`).

    Area is a property of the PLAN, not of the moment of spend: this map is built
    fresh from the manifest at every read, so re-tagging a phase re-attributes its
    whole ledger history with no backfill and no row rewriting. An untagged phase
    maps to [] (present, not missing), so callers can tell "known phase, no tags"
    from "phase the plan has never heard of". `usage_ledger.aggregate_area`
    receives this map ready-made — that module stays stdlib-only and must not
    import this one."""
    out = {}
    for phase in (manifest or {}).get("phases") or []:
        if isinstance(phase, dict) and phase.get("id"):
            out[phase["id"]] = areas_of(phase.get("area"))
    return out


# --- registry validation ------------------------------------------------------
def validate_registry(areas, where="meta.areas"):
    """(findings, warnings) for a `meta.areas` value. Never raises.

    Findings are SHAPE — a registry that is not an object, an entry that is not an
    object, a field of the wrong type. Those are typos with silent consequences and
    the validator treats them the way it treats every other wrong type.

    Warnings are CONTENT — an area with no root (nothing for the doctor to check
    and nothing for `/audit:init` to have written), a root that could not survive a
    second clone, an unknown key. Content stays warn-only because the registry is
    informational: nothing in the pipeline refuses to run over a bad description.
    """
    findings, warnings = [], []
    if areas is None:
        return findings, warnings
    if not isinstance(areas, dict):
        findings.append("%s: must be an object {tag: {root, description, "
                        "reviewSkill?, skills?, owner?}}, got %s"
                        % (where, type(areas).__name__))
        return findings, warnings
    for tag, entry in areas.items():
        t = _norm_tag(tag)
        awhere = "%s.%s" % (where, tag if isinstance(tag, str) and tag else "?")
        if not t:
            findings.append("%s: an area tag must be a non-empty name" % where)
            continue
        if t != tag:
            warnings.append("%s: tag %r has surrounding whitespace - it is matched "
                            "trimmed, so write it as %r" % (where, tag, t))
        if not isinstance(entry, dict):
            findings.append("%s: must be an object {root, description, reviewSkill?, "
                            "skills?, owner?}, got %s" % (awhere, type(entry).__name__))
            continue
        for key in entry:
            ks = str(key)
            if ks not in KNOWN_AREA and not ks.startswith(("_", "//")):
                warnings.append("%s: unknown key '%s' (known: %s)"
                                % (awhere, ks, ", ".join(KNOWN_AREA)))
        root = entry.get("root")
        if "root" not in entry:
            warnings.append("%s: no 'root' - an area with no directory cannot be "
                            "checked against the tree (/audit:doctor skips it)" % awhere)
        elif not isinstance(root, str) or not root.strip():
            findings.append("%s.root: must be a non-empty repo-relative directory "
                            "path, got %r" % (awhere, root))
        else:
            clean = root.strip().replace("\\", "/")
            if clean.startswith("/") or (len(clean) > 1 and clean[1] == ":"):
                warnings.append("%s.root: %r is absolute - it will not resolve in "
                                "another clone; use a path relative to the project "
                                "directory" % (awhere, root))
            elif clean.split("/")[0] == "..":
                warnings.append("%s.root: %r points outside the project directory"
                                % (awhere, root))
        desc = entry.get("description")
        if "description" in entry and not isinstance(desc, str):
            findings.append("%s.description: must be a string, got %s"
                            % (awhere, type(desc).__name__))
        rs = entry.get("reviewSkill")
        if "reviewSkill" in entry and rs is not None and not isinstance(rs, str):
            findings.append("%s.reviewSkill: must be a skill name or null, got %s"
                            % (awhere, type(rs).__name__))
        skills = entry.get("skills")
        if "skills" in entry:
            # F203. `null` IS LEGAL HERE and this branch was the only reader that
            # said otherwise. The schema permits it and documents WHY -- "allowed
            # for symmetry with task.skills and EQUIVALENT to []: the area is
            # itself the fallback, so there is nothing beneath it for a null to
            # stop" -- and `resolve_skills` already treats the two identically,
            # measured. So the schema, the resolver and this validator were three
            # readers of one rule with one of them out of step, and CI runs both
            # the schema (ajv) and this: a manifest carrying it passed one gate and
            # failed the other.
            #
            # The intended shape is two lines up, on `reviewSkill`: `is not None
            # and not isinstance(...)`. This branch simply omitted the first half.
            # Narrowing the SCHEMA instead would have removed a published spelling,
            # which COMPATIBILITY.md makes a major release - for a value nothing
            # ships and no reader needed changed.
            if skills is not None and not isinstance(skills, list):
                findings.append("%s.skills: must be an array of skill names or "
                                "null, got %s"
                                % (awhere, type(skills).__name__))
            elif isinstance(skills, list):
                # `elif isinstance`, not `else`: with `None` now legal above, a
                # bare `else` iterates it and the VALIDATOR crashes - which is
                # worse than the finding this repair removed. Caught by driving
                # the validator rather than by reading the branch.
                bad = [s for s in skills if not isinstance(s, str) or not s.strip()]
                if bad:
                    findings.append("%s.skills: every entry must be a non-empty skill "
                                    "name (%d bad: %s)"
                                    % (awhere, len(bad),
                                       _output.some_of(bad, render=repr)))
        owner = entry.get("owner")
        if "owner" in entry:
            # Type only. Whether this identity has ever appeared in the ledger is
            # the doctor's question (it has the ledger in hand); an offline shape
            # check that guessed would false-alarm on every pre-first-run project.
            if owner is not None and not isinstance(owner, str):
                findings.append("%s.owner: must be an author string (the form "
                                "usage.authorMode records) or null, got %s"
                                % (awhere, type(owner).__name__))
            elif isinstance(owner, str) and not owner.strip():
                findings.append("%s.owner: must not be empty - write null to say "
                                "'nobody owns this'" % awhere)
    return findings, warnings


# --- roots on disk ------------------------------------------------------------
def missing_roots(manifest, project):
    """[(tag, root), ...] for registered areas whose root is not a directory.

    Resolved against the PROJECT directory, which is where `task.files` and the
    `fileIndex` keys are resolved from too — one origin for every path a manifest
    states. An area with no root at all is not missing, it is unstated: skipped
    here and warned about by validate_registry.
    """
    out = []
    for tag, entry in registry(manifest).items():
        root = root_of(entry)
        if root and not os.path.isdir(os.path.join(project, root)):
            out.append((tag, root))
    return out


# --- the prose says what the code does ----------------------------------------
# The resolution is executed by this module and OBEYED by a language model reading
# the prose in reference/ and commands/. Two statements of one rule is the drift this
# repository has already shipped once (`exemptGlobs` and `tddReminder.testGlobs`
# disagreeing about what a test file is), and prose drift is worse than code drift
# because nothing runs it. So the sentence is pinned: every file that states the rule
# must state THIS, and `tests/test__areas.py` reads them to check.
REVIEW_RULE = ("phase.reviewSkill ?? meta.areas[tag].reviewSkill "
               "?? meta.reviewSkill")
SKILLS_RULE = "then task.skills, deduped, area first"
# where the rule is stated -> which halves of it that file must carry
# F301. A phase run stopped after wave 1 of eight and nothing could tell: the
# obligation to continue was prose nothing read. `_status_facts.unfinished_runs`
# now answers the same question from the lock and the ready list, so this row is
# what keeps the sentence and the fact from drifting apart - the document may not
# stop stating a rule the code has started grading.
CONTINUATION_RULE = ("A phase run is not finished while its lock is held and a "
                     "task is ready")

_RULE_DOCS = {
    os.path.join("reference", "orchestrator.md"): (REVIEW_RULE, SKILLS_RULE,
                                                   CONTINUATION_RULE),
    os.path.join("reference", "manifest-conventions.md"): (REVIEW_RULE, SKILLS_RULE),
    os.path.join("commands", "review.md"): (REVIEW_RULE,),
    "README.md": (REVIEW_RULE, SKILLS_RULE),
}


def _plain(text):
    """Prose with markdown emphasis and line wrapping removed, so a rule that got
    bolded or re-wrapped still reads as the same sentence."""
    return " ".join(re.sub(r"[*`]", "", text).split())


def rule_drift(plugin_root=None):
    """[(file, missing-rule), ...] for every doc that states the rule differently.

    Also catches the PREVIOUS wording — `phase.reviewSkill ?? meta.reviewSkill`,
    true until v0.28 — surviving somewhere as a two-level rule that quietly omits
    the area. That is the specific way this drifts: an area is added to one file
    and the other three keep describing the old lookup.
    """
    root = plugin_root or _output.PLUGIN_ROOT
    out = []
    for rel, rules in sorted(_RULE_DOCS.items()):
        path = os.path.join(root, rel)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = _plain(fh.read())
        except Exception as exc:
            out.append((rel, "unreadable: %s" % exc))
            continue
        for rule in rules:
            if rule not in text:
                out.append((rel, rule))
        # What sits immediately LEFT of the final `?? meta.reviewSkill`. In the
        # three-level rule that is the area; in the pre-v0.28 two-level one it is
        # the phase, and that is the whole difference between them.
        for left in re.findall(r"([A-Za-z.\[\]]*)\s*\?\? meta\.reviewSkill", text):
            if left != "meta.areas[tag].reviewSkill":
                out.append((rel, "states a lookup without the area: %r ?? "
                                 "meta.reviewSkill" % left))
    return out


# --- the orchestrator's claims, anchored per SECTION --------------------------
# F282. `rule_drift` above was, measured, the ONLY thing in this repository holding
# any sentence of `reference/orchestrator.md` — a document that governs every
# `/audit:*` run. Each of its `##` sections was deleted in turn and the whole gate
# set run: not one deletion was noticed, not by the selftest sweep and not by
# `tools/gate-parity.py`. The one anchored sentence survived every deletion only
# because it appears twice, which is the tell — a whole-document check cannot
# notice a section going missing while a duplicate of its claim lives elsewhere.
#
# So these anchors are SECTION-SCOPED, and that is the difference rather than a
# detail. Each row names the `##` section that must carry the claim, so deleting
# that section is a finding no matter what the rest of the file still says.
#
# AND THE FACT COMES FROM THE CODE — but NOT EQUALLY IN EVERY ROW, and this
# paragraph used to claim it did. A review measured the gap: seven rows carried a
# file and a pattern while deriving nothing a code CHANGE could move, and the
# comment presented all of them as the strong kind. An honest weaker claim is
# worth more than a strong one that is wrong, so each row now DECLARES its
# strength and `_strength_mismatches()` checks the declaration against what the
# row can actually do. A row that loses its capture group fails by name instead of
# quietly demoting itself, which is the drift that happened here:
#
#   "value"    the pattern CAPTURES a literal and the needle carries `%s`, so the
#              section must state that value. Renumber `close-phase.py`'s
#              not-a-fast-forward exit and this row is red. The strong kind.
#   "presence" the code must carry a SHAPE and the sentence is not derived from
#              it, so a rename or deletion fires and a value change cannot. Where
#              a row is this, the reason is on the row.
#   "pinned"   the needle is this module's own constant, because the code that
#              implements the rule is in THIS file and there is no second module
#              to read. Catches deletion and rewording only.
#
# The rot this document has actually suffered runs both ways (F271, F276 and F269
# are prescriptions the code refuses; F281 was a prohibition nothing enforced), so
# the "value" rows are the ones that answer both directions and the others say so.
#
# Coverage is DERIVED, not claimed. `anchor_coverage()` prints which sections have
# an anchor and which do not, `UNANCHORED_SECTIONS` declares the ones that do not
# WITH a reason, and `claim_drift` reports a section that is in neither set — so a
# new section arrives unanchored and says so, rather than joining the silent mass
# this whole block exists to reduce:
#
#     python3 plugins/audit/scripts/manifest/_areas.py --coverage
_ORCHESTRATOR = os.path.join("reference", "orchestrator.md")

# How far after a row's `context` substring the claim may sit. A window rather
# than the whole section because `(default main)` and `(default audit)` are the
# same shape twice in one section, and a whole-section search would let either
# key's default satisfy the other's row.
_CLAIM_WINDOW = 300

# (claim, the `##` section that must carry it, the file under PLUGIN_ROOT that
#  decides the fact, a regex whose group(1) IS the fact, a substring that must
#  appear in the section before the claim, what the section must then state)
#
# An empty code file with a None regex means the needle is this module's own
# pinned constant. Those rows are the WEAKER kind — they catch deletion and
# rewording but not code drift — and they are here because `resolve_review_skill`
# and `resolve_skills` are in this file, so there is no second module to read.
CLAIM_ANCHORS = (
    ("layout-version-sharded", "At a glance", "value",
     os.path.join("scripts", "manifest", "_manifest_io.py"),
     r'LAYOUT_VERSION\s*=\s*\{[^}]*"sharded":\s*(\d+)',
     "", "meta.version: %s is a stamp"),
    ("layout-version-single", "At a glance", "value",
     os.path.join("scripts", "manifest", "_manifest_io.py"),
     r'LAYOUT_VERSION\s*=\s*\{[^}]*"single-file":\s*(\d+)',
     "", "meta.version: %s or absent"),
    # PRESENCE, and the reason is that the claim is a PROHIBITION. The invariants
    # line forbids `stash`; there is no value in the hook for it to state, so the
    # code side is that the guard enforcing it still exists. It is also prose the
    # `_BOLD_NEVER` census in `tools/check-prohibitions.py` cannot see (the line
    # writes `never`, not `NEVER`), which is why this row exists at all.
    ("stash-invariant", "At a glance", "presence",
     os.path.join("hooks", "guard-history-rewrite.py"),
     r"STASH_READS\s*=\s*\(", "", "never git push/force-push/stash"),
    ("branch-prefix-default", "Preflight", "value",
     os.path.join("scripts", "manifest", "_branch.py"),
     r'DEFAULT_PREFIX\s*=\s*"([^"]+)"', "meta.branchPrefix", "(default %s)"),
    ("development-branch-default", "Preflight", "value",
     os.path.join("scripts", "manifest", "_branch.py"),
     r'DEFAULT_PARENT\s*=\s*"([^"]+)"', "meta.developmentBranch",
     "(default %s)"),
    ("max-attempts-default", "Non-negotiable guardrails", "value",
     os.path.join("scripts", "manifest", "audit-task.py"),
     r'"maxAttempts":\s*(\d+)', "", "maxAttempts (int, default %s)"),
    ("index-only-field", "Readiness rule", "value",
     os.path.join("scripts", "manifest", "_manifest_io.py"),
     r'INDEX_ONLY_FIELDS\s*=\s*\(\s*"([^"]+)"', "",
     "phase.%s re-sorts that order"),
    ("unique-tier", "Readiness rule", "value",
     os.path.join("scripts", "manifest", "_priority.py"),
     r"UNIQUE_TIER\s*=\s*(\d+)", "", "tier %s (unique) leads"),
    ("lock-exit-live", "Concurrency lock", "value",
     os.path.join("scripts", "governance", "_locks.py"),
     r"E_LIVE,\s*E_STALE,\s*E_USAGE,\s*E_ERR\s*=\s*(\d+)", "",
     "| %s | held by a live run |"),
    ("lock-exit-stale", "Concurrency lock", "value",
     os.path.join("scripts", "governance", "_locks.py"),
     r"E_LIVE,\s*E_STALE,\s*E_USAGE,\s*E_ERR\s*=\s*\d+,\s*(\d+)", "",
     "| %s | holder is not alive |"),
    ("parent-branch-rule", "Branch-per-phase", "value",
     os.path.join("scripts", "manifest", "_branch.py"),
     r'DEFAULT_PARENT\s*=\s*"([^"]+)"', "",
     "phase.parentBranch ?? meta.developmentBranch (default %s)"),
    ("skills-rule", "Execute the task", "pinned", "", None, "", SKILLS_RULE),
    # POSITIONAL capture, so this is a "value" row rather than a name spelled
    # inside its own pattern: it reads whatever `CHECK_NAMES` holds SECOND, so
    # renaming that check changes the value the section must state. Written out
    # after a review found the row deriving nothing.
    ("audit-state-invariant", "Keeping a failed run's record", "value",
     os.path.join("scripts", "governance", "_invariants.py"),
     r'CHECK_NAMES\s*=\s*\(\s*"[^"]+",\s*"([^"]+)"', "",
     "verify-invariants.py's %s grades those commits"),
    ("review-skill-rule", "Phase sign-off", "pinned", "", None, "",
     REVIEW_RULE),
    ("close-phase-not-ff", "Phase sign-off", "value",
     os.path.join("scripts", "git", "close-phase.py"),
     r"E_OK,\s*E_FAIL,\s*E_USAGE,\s*E_NOT_FF,\s*E_NO_BASIS\s*="
     r"\s*\d+,\s*\d+,\s*\d+,\s*(\d+)", "", "| %s | not a fast-forward"),
    ("close-phase-no-basis", "Phase sign-off", "value",
     os.path.join("scripts", "git", "close-phase.py"),
     r"E_OK,\s*E_FAIL,\s*E_USAGE,\s*E_NOT_FF,\s*E_NO_BASIS\s*="
     r"\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*(\d+)", "",
     "| %s | git could not be asked |"),
    # PRESENCE, both of them, and the reason is measured rather than assumed:
    # `run-test-gate.py` holds its verdict banners as INLINE literals inside
    # `render()` with no module-level table, so there is no position to capture
    # from. Renaming a banner is caught; changing one to a different wording in
    # place is caught too, since the literal is what the pattern looks for. What
    # is NOT caught is the banner keeping its text and changing its meaning.
    ("gate-mutated-verdict", "Phase sign-off", "presence",
     os.path.join("scripts", "governance", "run-test-gate.py"),
     r'"(GATE MUTATED THE TREE)', "", "%s refuses the commit step"),
    ("no-check-ran-verdict", "Phase sign-off", "presence",
     os.path.join("scripts", "governance", "run-test-gate.py"),
     r'"(NO CHECK RAN)', "", "%s is not green"),
    ("ado-tag-default", "ADO echo", "value",
     os.path.join("scripts", "manifest", "_manifest_ado.py"),
     r'DEFAULT_ADO_TAG\s*=\s*"([^"]+)"', "", "absent = %s"),
    # POSITIONAL again: the SECOND member of the status vocabulary, so renaming
    # `in_progress` moves the value this section must state.
    ("resume-status", "Resume after interruption", "value",
     os.path.join("scripts", "manifest", "_manifest_vocab.py"),
     r'^STATUS\s*=\s*\(\s*"[^"]+",\s*"([^"]+)"', "",
     'Find the phase with status == "%s"'),
    # PRESENCE: an argparse flag is spelled once at its definition and there is no
    # neighbouring value to capture positionally. A renamed flag is caught; there
    # is nothing else here for a value to be.
    ("status-phase-flag", "Progress output", "presence",
     os.path.join("scripts", "status", "audit-status.py"),
     r'"(--phase)"', "", 'audit-status.py" <manifestPath> [%s <id>]'),
    # POSITIONAL: the argv pair the code actually runs, so changing the git
    # subcommand it asks moves the value.
    ("dry-run-ancestry", "Dry-run / preview", "value",
     os.path.join("scripts", "governance", "_invariants.py"),
     r'\["merge-base",\s*"([^"]+)"', "", "merge-base %s"),
)

# --- claims that are a LIST rather than a value -------------------------------
# A row above states ONE needle, and a vocabulary is every member of an enum the
# code owns. `## Keeping a failed run's record` names the evidence statuses a run
# can strand, and that list went stale inside the very change that added these
# anchors: the section was anchored, but only by `audit-state-invariant`, which
# reads a check NAME - so `claim_drift` was blind to the list itself. F282's own
# class, in F282's own commit.
#
# The repair is to derive the list rather than restate it. Both directions:
# a member the enum gained and the section never learned is a finding, and so is
# a word the section names that the enum does not have - which is what stops a
# future status being written into the prose before the code produces it.
#
# (`gate-mutated` is the member a reviewer expected to find here. It is in no
# enum in this tree - `run-test-gate.py` prints `GATE MUTATED THE TREE` as a
# banner and records no such STATUS - so writing it into the document would be a
# prescription the code refuses, and this anchor would report it as one. It
# belongs to whichever change adds the status, and this check is what will make
# the document follow it.)
#
# F303. The second row is the same defect one section over, and it is the one that
# measures what section-scoped coverage buys. `## Phase sign-off` told the reader
# that `/audit:task scope` refuses a `done` task; F283 had already reversed that.
# Driven on both trees against one fixture with only the status changed, the
# released v2.2.0 exits 2 saying scope only rewrites a pending task and this tree
# exits 0 having widened `files`. The section was ALREADY anchored, several claims
# deep, and not one of them read that sentence -- so what the coverage line buys is
# SOME claims in most sections, never every sentence in one. Which claims each
# section carries is printed rather than written down here:
#
#     python3 plugins/audit/scripts/manifest/_areas.py --coverage
#
# THE ADVICE SURVIVED THE MECHANISM, which is what makes this the durable kind of
# stale. A finding in a file no task declares still wants a new task, because a
# widening settles the INDEX and deliberately records no new work; a reader checks
# that reasoning, finds it sound, and never re-checks the clause it rests on.
#
# A VOCABULARY rather than a value, and for F303's own reason: the failure was the
# document naming a status the verb does not refuse, which is exactly this shape's
# second direction. The pattern reads the guard inside `_locked_scope` -- the verb
# itself rather than a restatement of it -- and accepts either spelling of a status
# test, so widening that refusal back to `done` and `cancelled` is reported as a
# member the section never learned instead of as a row that lost its basis.
#
# F334. THE FUNCTION BODY IS THE BOUND, AND IT USED TO BE AN UNBOUNDED `.*?`. The
# claim here read "tied to the refusal's own `out(` line so it cannot slide onto
# the acceptance branch below it" - true INSIDE the function and false for the
# file, which is the defect rather than the wording: a claim the code did not
# support. The row above anchors on a unique constant NAME; this one anchors on a
# repeated code SHAPE, a status test beside an `out(` prefix, and that shape occurs
# in more than one verb here. Under `re.S` a lazy `.*?` reads straight past the end
# of `_locked_scope` to find the next one. Measured: delete `_locked_scope`'s
# refusal outright and the anchor latched onto `retarget`'s guard, far below it in
# another function, and reported `## Phase sign-off` for not naming `done` - a
# status `scope` no longer refuses at all. `_list_anchor_drift` already had the
# right branch for a deleted guard ("no longer carries the vocabulary this claim is
# anchored to"), and the unbounded window made it unreachable.
#
# WHAT ACTUALLY HOLDS is a property of the language, not of this file's habits:
# inside a top-level function body every line is blank or indented, so a line
# beginning in column 0 has ENDED that body. `(?:(?!\n\S).)*?` is exactly that
# bound, and it is why the formulation is not the narrower "no `def ` may
# intervene": the window closes at the first column-0 line whatever it is, so a
# top-level constant, a decorator or an `if __name__` stop it too, and the pattern
# does not have to anticipate which shape follows the function. It is conservative
# in one place on purpose - a column-0 comment inside a body is legal Python and
# would close the window early - and that direction fails LOUD, as the missing
# vocabulary the row prints its pattern with, rather than sliding somewhere else.
LIST_ANCHORS = (
    ("audit-state-statuses", "Keeping a failed run's record",
     os.path.join("scripts", "status", "_status_facts.py"),
     r"NO_SIGN_OFF_EVIDENCE\s*=\s*frozenset\(\{([^}]*)\}",
     "evidence can sit in a working tree forever"),
    ("scope-refusal-statuses", "Phase sign-off",
     os.path.join("scripts", "manifest", "audit-task.py"),
     r'def _locked_scope\((?:(?!\n\S).)*?node\.get\("status"\)\s*(?:==|in)\s*'
     r'\(?((?:"[^"]+"(?:\s*,\s*)?)+)\)?\s*:\s*out\("\[audit-task\] ',
     "and a `done` task will take a widening"),
)

# section -> why nothing anchors it. Checked in BOTH directions by `claim_drift`:
# a section here that HAS an anchor is a stale row, and a section in neither set
# is a finding. A reason, not a label - it has to say what a reader would have to
# build for the section to become anchorable.
UNANCHORED_SECTIONS = {
    "Reporting": (
        "NOTHING IN CODE DECIDES THIS SECTION. It is entirely about when a "
        "command's contract is DISCHARGED - that a wave completing is not a "
        "stopping point, that printing the next ready task is what a finished "
        "run does. There is no literal, exit code or table behind any of it, so "
        "an anchor here could only assert that a sentence is present, which is "
        "the half this block deliberately does not build. Anchoring it needs the "
        "orchestrator to emit a machine-readable discharge signal first."),
}


def doc_sections(text):
    """[(heading, body)] for every `##` in a markdown document, in written order.

    The H1 preamble is deliberately dropped: every claim these anchors hold lives
    under a `##`, and a preamble that answered to no heading would be a section
    nothing could name."""
    out = []
    heading, body = None, []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            if heading is not None:
                out.append((heading, "\n".join(body)))
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        out.append((heading, "\n".join(body)))
    return out


def _section_named(sections, prefix):
    """The one section whose heading STARTS with `prefix`, or None.

    A prefix rather than the whole heading because several headings carry a
    parenthetical that is prose (`Phase sign-off (Definition of Done ...)`), and
    a row pinned to the parenthetical would go red on a wording tweak. Exactly
    one match is required: two would make the row ambiguous about which section
    it anchors, which is worse than no anchor at all."""
    hits = [(name, body) for name, body in sections if name.startswith(prefix)]
    return hits[0] if len(hits) == 1 else None


def _read(path):
    """(text, error) - never raises, and never returns "" for a file it could not
    read. An unreadable side of a two-sided comparison must be an ANSWER, because
    "" would satisfy every `not in` test and report the document clean."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read(), None
    except Exception as exc:
        return None, str(exc)


CLAIM_STRENGTHS = ("value", "presence", "pinned")

# A capture group whose source is only these characters can match nothing but
# itself, so substituting it into the needle is a no-op and the row asserts
# PRESENCE however it is spelled. That distinction is the one the over-claim
# turned on: `r'"(GATE MUTATED THE TREE)'` looks like a derivation and is a
# literal wearing a capture group.
_PLAIN_LITERAL = re.compile(r"^[A-Za-z0-9 _./:@-]+$")


def _capture_source(pattern):
    """The regex source inside the first CAPTURING group, or None.

    Hand-scanned rather than parsed because `re` does not expose it. `(?...)`
    is not a capture, and nesting is tracked so a group containing one is read
    whole."""
    depth, start = 0, None
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            capturing = not pattern[index + 1:index + 2] == "?"
            if capturing and start is None:
                start, depth = index + 1, 1
            elif start is not None:
                depth += 1
        elif char == ")" and start is not None:
            depth -= 1
            if depth == 0:
                return pattern[start:index]
        index += 1
    return None


def _strength_mismatches():
    """[(claim, problem)] for every row whose DECLARED strength it cannot deliver.

    This is the check that stops the block comment above over-claiming again. A
    review found seven rows carrying a file and a pattern while deriving nothing
    a code CHANGE could move, described by a comment that presented all of them
    as the strong kind. Declaring the strength is only worth something if the
    declaration is measured, so:

      value     the pattern captures a group that can match SOMETHING ELSE, and
                the needle substitutes it - so a code change moves the value;
      presence  the code must carry a fixed shape. A capture spelled as a plain
                literal counts here however the needle uses it, because a group
                that can only match itself derives nothing - which is the exact
                over-claim this check was written after;
      pinned    no file and no pattern; the needle is this module's constant.

    A row that loses its capture group, or narrows one to a literal, now fails by
    name rather than quietly demoting itself to the weaker kind.
    """
    out = []
    for row in CLAIM_ANCHORS:
        claim, _prefix, strength, rel, pattern, _context, needle = row
        if strength not in CLAIM_STRENGTHS:
            out.append((claim, "declares strength %r, which is not one of %s"
                        % (strength, ", ".join(CLAIM_STRENGTHS))))
            continue
        group = _capture_source(pattern) if pattern else None
        derives = group is not None and not _PLAIN_LITERAL.match(group)
        substitutes = "%s" in needle
        if strength == "value" and not (derives and substitutes):
            out.append((claim, "declares 'value' but its capture is %r and the "
                               "needle substitutes=%s - a group that can only "
                               "match itself derives nothing, so this is a "
                               "presence row and must say so"
                        % (group, substitutes)))
        elif strength == "presence" and (not pattern or derives):
            out.append((claim, "declares 'presence' but pattern=%r captures %r, "
                               "which can match something else - that is a "
                               "value row and should claim it"
                        % (pattern, group)))
        elif strength == "pinned" and (rel or pattern):
            out.append((claim, "declares 'pinned' but names %r/%r - pinned means "
                               "the needle is this module's own constant"
                        % (rel, pattern)))
    return out


def _list_anchor_drift(root, sections):
    """[(claim, problem)] for every vocabulary the document and the code disagree on.

    The section's list is read from the RAW markdown, not the plained text, so
    the backticks that mark each member survive and the sentence's own words do
    not get mistaken for members. The window is the sentence ending at the row's
    marker phrase, which is why rewording that sentence is itself a finding: a
    reworded list is a list somebody has to re-check.
    """
    out = []
    for claim, prefix, rel, pattern, marker in LIST_ANCHORS:
        found = _section_named(sections, prefix)
        if found is None:
            out.append((claim, "no single '## %s...' section in %s"
                        % (prefix, _ORCHESTRATOR)))
            continue
        src, err = _read(os.path.join(root, rel))
        if err is not None:
            out.append((claim, "%s unreadable: %s" % (rel, err)))
            continue
        match = re.search(pattern, src, re.S)
        if match is None:
            out.append((claim, "%s no longer carries the vocabulary this claim "
                               "is anchored to (%s)" % (rel, pattern)))
            continue
        members = set(re.findall(r'"([^"]+)"', match.group(1)))
        at = found[1].find(marker)
        if at < 0:
            out.append((claim, "'## %s' no longer says %r, so the list it "
                               "introduces cannot be located"
                        % (found[0], marker)))
            continue
        sentence = found[1][:at]
        cut = sentence.rfind(". ")
        stated = set(re.findall(r"`([^`]+)`", sentence[cut + 1:]))
        if not members:
            out.append((claim, "%s parsed to an EMPTY vocabulary - an empty set "
                               "agrees with any document, so this is a finding "
                               "about the scan rather than a clean answer"
                        % (rel,)))
            continue
        for name in sorted(members - stated):
            out.append((claim, "%s has %r and '## %s' does not name it"
                        % (rel, name, found[0])))
        for name in sorted(stated - members):
            out.append((claim, "'## %s' names %r and %s has no such member - a "
                               "status the code does not produce"
                        % (found[0], name, rel)))
    return out


def claim_drift(plugin_root=None, text=None):
    """[(subject, problem)] for every anchored claim the two sides disagree about.

    Four kinds of finding, and they are worded apart because they are four
    different repairs: the section is gone or ambiguous; the CODE no longer
    carries the fact the row reads (so the row has no basis and must not pass);
    the section does not state what the code says; and the coverage declaration
    has drifted from what the rows actually cover.

    `text` substitutes for the DOCUMENT only; the code side is always read off
    `plugin_root`. That split is what lets the cases mutate the document on a
    fixture while still comparing against the real modules - a fixture tree
    holding both sides would report every row as "the code moved", which is a
    different finding and would make the document cases pass for the wrong
    reason.
    """
    root = plugin_root or _output.PLUGIN_ROOT
    out = []
    if text is not None:
        doc, err = text, None
    else:
        doc, err = _read(os.path.join(root, _ORCHESTRATOR))
    if err is not None:
        return [(_ORCHESTRATOR, "unreadable: %s" % err)]
    sections = doc_sections(doc)
    if not sections:
        # An empty section list would make every row below report "section
        # missing" for one reason, which reads as many findings about the
        # document rather than one about this scan.
        return [(_ORCHESTRATOR, "no '## ' sections found - either the document "
                                "was restructured or this scan stopped reading "
                                "it; every claim below is unanchored until this "
                                "is answered")]
    out.extend(_strength_mismatches())
    for row in CLAIM_ANCHORS:
        claim, prefix, _strength, rel, pattern, context, needle = row
        found = _section_named(sections, prefix)
        if found is None:
            out.append((claim, "no single '## %s...' section in %s - the claim "
                               "this row anchors has nowhere to live"
                        % (prefix, _ORCHESTRATOR)))
            continue
        # `stated`, not `text`: `text` is this function's own parameter, and
        # rebinding it here left the parameter unreachable by name after the
        # first row. Harmless today, a trap for the next edit.
        stated = _plain(found[1])
        fact = ""
        if pattern:
            src, src_err = _read(os.path.join(root, rel))
            if src_err is not None:
                out.append((claim, "%s unreadable: %s" % (rel, src_err)))
                continue
            match = re.search(pattern, src, re.M)
            if match is None:
                out.append((claim, "%s no longer carries the fact this claim is "
                                   "anchored to (%s) - the code moved and the "
                                   "document's version of it is now unchecked"
                            % (rel, pattern)))
                continue
            fact = match.group(1) if match.groups() else ""
        want = needle % (fact,) if "%s" in needle else needle
        where = stated
        if context:
            at = stated.find(context)
            if at < 0:
                out.append((claim, "'## %s' no longer mentions %r, so the claim "
                                   "cannot be located in it" % (found[0], context)))
                continue
            where = stated[at:at + _CLAIM_WINDOW]
        if want not in where:
            out.append((claim, "'## %s' does not state %r%s" %
                        (found[0], want,
                         "" if not rel else " (%s says so)" % rel)))
    out.extend(_list_anchor_drift(root, sections))
    coverage = anchor_coverage(root, sections)
    for name in coverage["undeclared"]:
        out.append((name, "a '## ' section with no anchor and no row in "
                          "UNANCHORED_SECTIONS - decide which it is; a section "
                          "in neither set is the silent mass F282 measured"))
    for name in coverage["stale_declarations"]:
        out.append((name, "declared unanchored, but it is either anchored now or "
                          "no longer a section - delete the declaration rather "
                          "than leaving a reason nobody can check"))
    return out


def anchor_coverage(plugin_root=None, sections=None, text=None):
    """Which `##` sections of the orchestrator carry an anchor, and which do not.

    Derived rather than written down, because a coverage figure in prose is the
    defect this repository has recorded most often. `undeclared` and
    `stale_declarations` are what make `UNANCHORED_SECTIONS` a checked claim in
    both directions instead of a list that only grows.

    BOTH TABLES, and reading only `CLAIM_ANCHORS` was a real gap rather than an
    omission with no consequence: `audit-state-statuses` held a whole vocabulary
    of `## Keeping a failed run's record` and this function could not see it, so
    the section showed one claim while carrying two. Worse in the direction that
    had not happened yet -- a section anchored ONLY by a list row would have been
    reported by `claim_drift` as being in neither set, which is a finding against
    a section that is anchored. The two tables differ in what a row derives, not
    in whether a row is an anchor.
    """
    root = plugin_root or _output.PLUGIN_ROOT
    if sections is None and text is not None:
        sections = doc_sections(text)
    if sections is None:
        doc, err = _read(os.path.join(root, _ORCHESTRATOR))
        sections = [] if err is not None else doc_sections(doc)
    names = [name for name, _body in sections]
    anchored, claims = [], {}
    for row in CLAIM_ANCHORS + LIST_ANCHORS:
        claim, prefix = row[0], row[1]
        for name in names:
            if name.startswith(prefix):
                if name not in anchored:
                    anchored.append(name)
                claims.setdefault(name, []).append(claim)
    unanchored = [name for name in names if name not in anchored]
    return {
        "sections": names,
        "anchored": anchored,
        "unanchored": unanchored,
        "claims": claims,
        "undeclared": [n for n in unanchored if n not in UNANCHORED_SECTIONS],
        "stale_declarations": sorted(n for n in UNANCHORED_SECTIONS
                                     if n not in unanchored),
    }


def render_coverage(plugin_root=None):
    """The coverage table as lines, for `--coverage` and for a report to paste."""
    cov = anchor_coverage(plugin_root)
    lines = ["orchestrator.md sections and the claims anchored in each:"]
    for name in cov["sections"]:
        claims = cov["claims"].get(name) or []
        if claims:
            lines.append("  [anchored] %s: %s" % (name, ", ".join(claims)))
        elif name in UNANCHORED_SECTIONS:
            lines.append("  [declared unanchored] %s" % name)
        else:
            lines.append("  [UNDECLARED, no anchor] %s" % name)
    lines.append("anchored %d of %d section(s); %d declared unanchored"
                 % (len(cov["anchored"]), len(cov["sections"]),
                    len(cov["unanchored"])))
    return lines


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--coverage" in sys.argv[1:]:
        # DERIVED, so it cannot be the kind of coverage claim that rots. The
        # findings go with it: a table saying which sections are anchored, from a
        # command that also refuses when an anchor is broken, is the only form of
        # that answer worth printing.
        for line in render_coverage():
            print(line)
        drift = claim_drift()
        for subject, problem in drift:
            print("  %s\n      %s" % (subject, problem))
        sys.exit(1 if drift else 0)
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_areas.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__areas.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
