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
_RULE_DOCS = {
    os.path.join("reference", "orchestrator.md"): (REVIEW_RULE, SKILLS_RULE),
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


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
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
