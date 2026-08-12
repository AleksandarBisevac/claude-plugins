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
"""
import os
import re

# Keys an area entry may carry. Unknown ones warn — a typo'd `reviewskill` would
# otherwise be a reviewer that silently never runs.
KNOWN_AREA = ("root", "description", "reviewSkill", "skills")


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
def resolve_review_skill(manifest, phase):
    """(skill, basis) for a phase's sign-off reviewer.

    `phase.reviewSkill ?? areas[tag].reviewSkill ?? meta.reviewSkill`, with the tags
    tried in written order. `basis` names the level that answered — "phase",
    "area <tag>", "meta", or "" when nothing did — so every surface can print WHY
    this reviewer, which is the whole reason a three-level lookup is tolerable.

    A level that is present and explicitly null is an answer, not a miss: setting
    `phase.reviewSkill: null` on one phase of a reviewed project is how you say
    "not this one", and falling through to the area would ignore it.
    """
    phase = phase if isinstance(phase, dict) else {}
    if "reviewSkill" in phase:
        return (phase.get("reviewSkill") or None), "phase"
    for tag in areas_of(phase.get("area")):
        entry = entry_of(manifest, tag)
        if "reviewSkill" in entry:
            return (entry.get("reviewSkill") or None), "area %s" % tag
    meta = (manifest or {}).get("meta")
    meta = meta if isinstance(meta, dict) else {}
    if "reviewSkill" in meta:
        return (meta.get("reviewSkill") or None), "meta"
    return None, ""


# --- skills resolution --------------------------------------------------------
def resolve_skills(manifest, phase, task):
    """The skills an executor subagent loads: area defaults first, then the task's.

    Area first because an area skill is the house style ("this service is Django,
    read these conventions") and the task's are the specifics — a subagent that
    reads the specifics before the conventions has already made the decisions the
    conventions were meant to inform. Deduped, first occurrence wins, so naming a
    skill in both places is a no-op rather than a double load.
    """
    out = []
    for tag in areas_of((phase or {}).get("area")):
        for skill in entry_of(manifest, tag).get("skills") or []:
            if isinstance(skill, str) and skill.strip() and skill.strip() not in out:
                out.append(skill.strip())
    for skill in (task or {}).get("skills") or []:
        if isinstance(skill, str) and skill.strip() and skill.strip() not in out:
            out.append(skill.strip())
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
                        "reviewSkill?, skills?}}, got %s"
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
                            "skills?}, got %s" % (awhere, type(entry).__name__))
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
            if not isinstance(skills, list):
                findings.append("%s.skills: must be an array of skill names, got %s"
                                % (awhere, type(skills).__name__))
            else:
                bad = [s for s in skills if not isinstance(s, str) or not s.strip()]
                if bad:
                    findings.append("%s.skills: every entry must be a non-empty skill "
                                    "name (%d bad: %r)" % (awhere, len(bad), bad[:3]))
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
# must state THIS, and the selftest reads them to check.
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
    root = plugin_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


# --- selftest -----------------------------------------------------------------
def _selftest():
    """Four surfaces resolve against this module, so it carries its own gate."""
    ok = bad = 0

    def check(name, cond, detail=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s%s" % (name, (" :: %s" % detail) if detail else ""))

    # --- normalisation -----------------------------------------------------------
    check("a1 a bare string is one tag", areas_of("api") == ["api"])
    check("a2 a list keeps written order", areas_of(["b", "a"]) == ["b", "a"])
    check("a3 absent/empty/wrong-typed areas are no tags",
          areas_of(None) == [] and areas_of("") == [] and areas_of(7) == []
          and areas_of(["", None, 3]) == [])
    check("a4 tags are trimmed, so ' api' and 'api' are one tag on both sides",
          areas_of([" api ", "api"]) == ["api"])
    check("a5 a repeated tag is ONE tag - the double-count that made a 1/1 phase "
          "read 2/2 in the rollup's per-area totals",
          areas_of(["api", "api", "web"]) == ["api", "web"])

    MAN = {"meta": {"reviewSkill": "house-review",
                    "areas": {"api": {"root": "services/api",
                                      "reviewSkill": "backend-review",
                                      "skills": ["python-conv"]},
                              "web": {"root": "apps/web", "skills": ["ts-conv"]},
                              "sec": {"root": ".", "reviewSkill": "sec-review"}}},
           "phases": [{"id": "P1", "area": "api"},
                      {"id": "P2", "area": ["web", "sec"]},
                      {"id": "P3"}]}

    # --- registry access ---------------------------------------------------------
    check("r1 the registry reads from a manifest",
          sorted(registry(MAN)) == ["api", "sec", "web"])
    check("r2 ...and from a bare meta, which is what the panel holds",
          sorted(registry({"areas": MAN["meta"]["areas"]})) == ["api", "sec", "web"])
    check("r3 a missing or malformed registry is {}, never a raise",
          registry({}) == {} and registry({"meta": {"areas": []}}) == {}
          and registry(None) == {} and registry({"meta": 5}) == {})
    check("r4 a malformed ENTRY is dropped from resolution and left to the "
          "validator to report",
          registry({"meta": {"areas": {"a": "nope", "b": {"root": "x"}}}}) == {"b": {"root": "x"}})
    check("r5 an unknown tag resolves to {}, so callers can .get without a guard",
          entry_of(MAN, "nope") == {} and entry_of(MAN, None) == {})
    check("r6 root_of trims and drops the trailing slash",
          root_of({"root": " apps/web/ "}) == "apps/web" and root_of({}) == ""
          and root_of({"root": "  "}) == "" and root_of({"root": "/"}) == ".")

    # --- review skill resolution -------------------------------------------------
    sk, basis = resolve_review_skill(MAN, MAN["phases"][0])
    check("v1 an area answers when the phase does not, and names itself",
          (sk, basis) == ("backend-review", "area api"), repr((sk, basis)))
    sk, basis = resolve_review_skill(MAN, MAN["phases"][1])
    check("v2 a tag that declares nothing is skipped, not treated as an answer: "
          "web is first and silent, so sec answers",
          (sk, basis) == ("sec-review", "area sec"), repr((sk, basis)))
    # v2 alone does NOT test precedence — with only one declaring area, any order
    # gives the same answer, and reversing the loop left it green. Two DECLARING
    # areas is the only shape that can tell written order from any other rule.
    sk, basis = resolve_review_skill(MAN, {"id": "PX", "area": ["api", "sec"]})
    check("v2b written order decides between two areas that BOTH declare",
          (sk, basis) == ("backend-review", "area api"), repr((sk, basis)))
    sk, basis = resolve_review_skill(MAN, {"id": "PX", "area": ["sec", "api"]})
    check("v2c ...and the same two tags the other way round answer the other way",
          (sk, basis) == ("sec-review", "area sec"), repr((sk, basis)))
    sk, basis = resolve_review_skill(MAN, MAN["phases"][2])
    check("v3 an untagged phase falls through to meta",
          (sk, basis) == ("house-review", "meta"), repr((sk, basis)))
    sk, basis = resolve_review_skill(MAN, {"id": "P4", "area": "api",
                                           "reviewSkill": "phase-review"})
    check("v4 the phase still wins over its area",
          (sk, basis) == ("phase-review", "phase"), repr((sk, basis)))
    sk, basis = resolve_review_skill(MAN, {"id": "P5", "area": "api",
                                           "reviewSkill": None})
    check("v5 an explicit null on the phase is an ANSWER - 'not this one' must not "
          "fall through to the area that would have reviewed it",
          (sk, basis) == (None, "phase"), repr((sk, basis)))
    sk, basis = resolve_review_skill({"meta": {"areas": {"api": {"reviewSkill": None}}}},
                                     {"area": "api"})
    check("v6 ...and the same at the area level, over a meta default",
          (sk, basis) == (None, "area api"), repr((sk, basis)))
    check("v7 nothing anywhere is (None, '') - no basis to print",
          resolve_review_skill({"meta": {}}, {"id": "P1"}) == (None, ""))
    check("v8 resolution never raises on hostile shapes",
          resolve_review_skill(None, None) == (None, "")
          and resolve_review_skill({"meta": {"areas": {"a": 3}}}, {"area": "a"})
          == (None, ""))

    # --- skills resolution -------------------------------------------------------
    check("s1 area skills come first, then the task's",
          resolve_skills(MAN, MAN["phases"][0], {"skills": ["task-skill"]})
          == ["python-conv", "task-skill"])
    check("s2 several areas union in written order",
          resolve_skills(MAN, MAN["phases"][1], {"skills": ["t"]}) == ["ts-conv", "t"])
    check("s3 a skill named in both places is loaded once, area-first",
          resolve_skills(MAN, MAN["phases"][0], {"skills": ["python-conv", "x"]})
          == ["python-conv", "x"])
    check("s4 no area and no task skills is an empty list, not None",
          resolve_skills(MAN, MAN["phases"][2], None) == [])
    check("s5 junk entries are dropped, not rendered",
          resolve_skills({"meta": {"areas": {"a": {"skills": ["ok", 3, "  "]}}}},
                         {"area": "a"}, {"skills": [None, " y "]}) == ["ok", "y"])

    # --- conflicts + unregistered tags -------------------------------------------
    check("c1 two areas declaring DIFFERENT reviewers is a conflict worth naming",
          review_skill_conflicts(MAN, {"area": ["api", "sec"]})
          == [("api", "backend-review"), ("sec", "sec-review")])
    check("c2 agreement is not a conflict",
          review_skill_conflicts({"meta": {"areas": {"a": {"reviewSkill": "r"},
                                                     "b": {"reviewSkill": "r"}}}},
                                 {"area": ["a", "b"]}) == [])
    check("c3 one declaring area is not a conflict",
          review_skill_conflicts(MAN, {"area": ["web", "api"]}) == [])
    check("c4 unregistered tags are reported per phase, in order",
          unregistered_tags({"meta": {"areas": {"api": {}}},
                             "phases": [{"id": "P1", "area": ["api", "apu"]},
                                        {"id": "P2", "area": "web"}]})
          == [("P1", "apu"), ("P2", "web")])
    check("c5 NO registry means no unregistered tags - free-text tagging is the "
          "v0.16 feature and stays legal",
          unregistered_tags({"meta": {}, "phases": [{"id": "P1", "area": "x"}]}) == [])
    check("c6 used_tags lists every tag in first-seen order",
          used_tags(MAN) == ["api", "web", "sec"])

    # --- phase_tags: the read-time spend-attribution join ------------------------
    check("t1 phase_tags maps every phase id to its tags in written order",
          phase_tags(MAN) == {"P1": ["api"], "P2": ["web", "sec"], "P3": []})
    check("t2 an untagged phase is PRESENT with [] - 'known phase, no tags' must "
          "stay distinguishable from 'phase the plan never heard of'",
          phase_tags(MAN).get("P3") == [] and "P9" not in phase_tags(MAN))
    check("t3 tags arrive trimmed and deduped, the same normalisation both sides "
          "of every other lookup get",
          phase_tags({"phases": [{"id": "P1", "area": [" api ", "api", ""]}]})
          == {"P1": ["api"]})
    check("t4 hostile shapes are an empty map, never a raise - a phase without an "
          "id or that is not a dict is skipped",
          phase_tags(None) == {} and phase_tags({}) == {}
          and phase_tags({"phases": [3, {"area": "x"}, {"id": "P1"}]})
          == {"P1": []})

    # --- registry validation -----------------------------------------------------
    f, w = validate_registry(MAN["meta"]["areas"])
    check("g1 a good registry has no findings", not f, repr(f))
    check("g2 ...and no warnings either, so a clean manifest stays quiet",
          not w, repr(w))
    check("g3 an absent registry is silent", validate_registry(None) == ([], []))
    f, _ = validate_registry([])
    check("g4 a non-object registry is a finding", len(f) == 1 and "must be an object" in f[0])
    f, _ = validate_registry({"api": "services/api"})
    check("g5 the likeliest typo - a bare path where the object goes - is a finding",
          len(f) == 1 and "got str" in f[0], repr(f))
    f, _ = validate_registry({"api": {"root": 3}})
    check("g6 a non-string root is a finding", len(f) == 1 and "root" in f[0], repr(f))
    f, w = validate_registry({"api": {}})
    check("g7 no root at all is a WARNING - the registry is informational",
          not f and len(w) == 1 and "no 'root'" in w[0], repr((f, w)))
    _, w = validate_registry({"api": {"root": "/Users/me/proj/services/api"}})
    check("g8 an absolute root warns: it cannot resolve in a second clone",
          len(w) == 1 and "absolute" in w[0], repr(w))
    _, w = validate_registry({"api": {"root": "C:/proj/api"}})
    check("g9 ...including the Windows spelling, which has no leading slash",
          len(w) == 1 and "absolute" in w[0], repr(w))
    _, w = validate_registry({"api": {"root": "../sibling"}})
    check("g10 a root outside the project directory warns",
          len(w) == 1 and "outside" in w[0], repr(w))
    _, w = validate_registry({"api": {"root": "a", "reviewskill": "x"}})
    check("g11 a miscased key warns rather than being a reviewer that never runs",
          len(w) == 1 and "unknown key" in w[0], repr(w))
    f, _ = validate_registry({"api": {"root": "a", "skills": "one-skill"}})
    check("g12 a bare string where the skills ARRAY goes is a finding - it would "
          "otherwise load one skill per character", len(f) == 1 and "skills" in f[0],
          repr(f))
    f, _ = validate_registry({"api": {"root": "a", "skills": ["ok", ""]}})
    check("g13 an empty skill name in the array is a finding", len(f) == 1, repr(f))
    f, _ = validate_registry({"api": {"root": "a", "description": 3}})
    check("g14 a non-string description is a finding", len(f) == 1, repr(f))
    f, _ = validate_registry({"api": {"reviewSkill": None, "root": "a"}})
    check("g15 ...but an explicitly null reviewSkill is legal - it is how an area "
          "says 'tests are the signer here'", not f, repr(f))
    f, _ = validate_registry({"  ": {"root": "a"}})
    check("g16 a blank tag name is a finding", len(f) == 1, repr(f))
    _, w = validate_registry({" api": {"root": "a"}})
    check("g17 a padded tag warns, since it is MATCHED trimmed and would otherwise "
          "look unregistered", len(w) == 1 and "whitespace" in w[0], repr(w))
    check("g18 validation never raises on hostile shapes",
          validate_registry({"a": None})[0] and validate_registry("x")[0])

    # --- roots on disk -----------------------------------------------------------
    here = os.path.dirname(os.path.abspath(__file__))
    man = {"meta": {"areas": {"here": {"root": "scripts"},
                              "gone": {"root": "no/such/dir"},
                              "unstated": {"description": "no root"}}}}
    miss = missing_roots(man, os.path.dirname(here))
    check("d1 a root that is not a directory is reported, one that is is not, and "
          "an area with no root is skipped rather than called missing",
          miss == [("gone", "no/such/dir")], repr(miss))

    # --- the prose says what the code does ---------------------------------------
    drift = rule_drift()
    check("p1 every document that states the resolution states the SAME one - the "
          "orchestrator reads prose, and prose drift is worse than code drift "
          "because nothing runs it: %r" % (drift,), not drift)
    check("p2 the lint can fail: a doc missing the rule is reported",
          [r for r in rule_drift(os.path.dirname(os.path.abspath(__file__)))
           if "unreadable" in str(r[1])])
    _fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ruledoc")
    os.makedirs(os.path.join(_fake, "reference"), exist_ok=True)
    os.makedirs(os.path.join(_fake, "commands"), exist_ok=True)
    try:
        for rel in _RULE_DOCS:
            with open(os.path.join(_fake, rel), "w", encoding="utf-8") as fh:
                fh.write("The reviewer is `phase.reviewSkill ?? meta.reviewSkill`, "
                         "then `task.skills`, deduped, **area first**.\n")
        _d = rule_drift(_fake)
        check("p3 the pre-v0.28 two-level wording is caught wherever it survives - "
              "one file learning about areas while the others do not is exactly "
              "how this drifts",
              len([x for x in _d if "without the area" in str(x[1])]) == 4
              and all("phase.reviewSkill" in str(x[1])
                      for x in _d if "without the area" in str(x[1])), repr(_d))
        check("p4 ...and the same run reports the rule as missing, so a file can "
              "fail for both reasons at once",
              len([x for x in _d if x[1] == REVIEW_RULE]) == 4, repr(_d))
    finally:
        import shutil
        shutil.rmtree(_fake, ignore_errors=True)

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
