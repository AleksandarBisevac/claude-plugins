#!/usr/bin/env python3
"""
The cases for `_areas.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

SEVERAL CASES HERE COMPUTE A PATH, AND A TEST FILE SITS ONE DIRECTORY OVER, so
each was checked rather than carried. The three the migration out of `_areas.py`
had to re-derive:

  * `d1` builds a manifest whose area root is `"scripts"` and asks `missing_roots`
    to resolve it against the PLUGIN directory. Inline that read
    `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` - two levels up
    from `_areas.py`. From here the same expression would still land on the
    plugin directory by coincidence (`tests/` is also one level down), and a case
    that is right by coincidence is a case that breaks the next time the file moves.
    It names `_harness.SCRIPTS_DIR`'s parent instead, which is the plugin directory
    by construction.
  * `p1` calls `M.rule_drift()` with NO argument, and the default is computed
    inside `_areas.py` from ITS own location - so it is unaffected by this file's
    location, and that is why it stays a bare call.
  * `p2` deliberately points `rule_drift` at a directory that holds none of the
    four documents, to prove the lint can report `unreadable`. Inline that was
    `scripts/`; it is spelled `_harness.SCRIPTS_DIR` here so the input is the same
    directory it always was, not "whichever directory this file happens to be in".

`p3`/`p4` write four fixture documents into a `_ruledoc/` directory beside this
file and remove it in `finally`, exactly as the inline suite did beside
`_areas.py`. It holds no `.py`, so it is invisible to every tree scanner here.

THE `oa26`-`oa28` FIXTURES ARE A CODE SIDE, WHICH IS THE OTHER HALF OF THAT, and
they are built from the REAL modules rather than written by hand: `claim_drift`
substitutes only the DOCUMENT through `text=`, so a case about a row's CODE side
has to hand it a tree. Each reads the module the row names off
`_harness.SCRIPTS_DIR`, mutates it in memory, and writes the result at the row's
own relative path under a `tempfile.mkdtemp()` removed in `finally` - never beside
this file, because a code-side fixture DOES hold a `.py` and every tree scanner
here would find it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import re
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _areas as M                                 # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- normalisation -----------------------------------------------------------
    check("a1 a bare string is one tag", M.areas_of("api") == ["api"])
    check("a2 a list keeps written order", M.areas_of(["b", "a"]) == ["b", "a"])
    check("a3 absent/empty/wrong-typed areas are no tags",
          M.areas_of(None) == [] and M.areas_of("") == [] and M.areas_of(7) == []
          and M.areas_of(["", None, 3]) == [])
    check("a4 tags are trimmed, so ' api' and 'api' are one tag on both sides",
          M.areas_of([" api ", "api"]) == ["api"])
    check("a5 a repeated tag is ONE tag - the double-count that made a 1/1 phase "
          "read 2/2 in the rollup's per-area totals",
          M.areas_of(["api", "api", "web"]) == ["api", "web"])

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
          sorted(M.registry(MAN)) == ["api", "sec", "web"])
    check("r2 ...and from a bare meta, which is what the panel holds",
          sorted(M.registry({"areas": MAN["meta"]["areas"]})) == ["api", "sec", "web"])
    check("r3 a missing or malformed registry is {}, never a raise",
          M.registry({}) == {} and M.registry({"meta": {"areas": []}}) == {}
          and M.registry(None) == {} and M.registry({"meta": 5}) == {})
    check("r4 a malformed ENTRY is dropped from resolution and left to the "
          "validator to report",
          M.registry({"meta": {"areas": {"a": "nope", "b": {"root": "x"}}}})
          == {"b": {"root": "x"}})
    check("r5 an unknown tag resolves to {}, so callers can .get without a guard",
          M.entry_of(MAN, "nope") == {} and M.entry_of(MAN, None) == {})
    check("r6 root_of trims and drops the trailing slash",
          M.root_of({"root": " apps/web/ "}) == "apps/web" and M.root_of({}) == ""
          and M.root_of({"root": "  "}) == "" and M.root_of({"root": "/"}) == ".")

    # --- review skill resolution -------------------------------------------------
    sk, basis = M.resolve_review_skill(MAN, MAN["phases"][0])
    check("v1 an area answers when the phase does not, and names itself",
          (sk, basis) == ("backend-review", "area api"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill(MAN, MAN["phases"][1])
    check("v2 a tag that declares nothing is skipped, not treated as an answer: "
          "web is first and silent, so sec answers",
          (sk, basis) == ("sec-review", "area sec"), repr((sk, basis)))
    # v2 alone does NOT test precedence — with only one declaring area, any order
    # gives the same answer, and reversing the loop left it green. Two DECLARING
    # areas is the only shape that can tell written order from any other rule.
    sk, basis = M.resolve_review_skill(MAN, {"id": "PX", "area": ["api", "sec"]})
    check("v2b written order decides between two areas that BOTH declare",
          (sk, basis) == ("backend-review", "area api"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill(MAN, {"id": "PX", "area": ["sec", "api"]})
    check("v2c ...and the same two tags the other way round answer the other way",
          (sk, basis) == ("sec-review", "area sec"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill(MAN, MAN["phases"][2])
    check("v3 an untagged phase falls through to meta",
          (sk, basis) == ("house-review", "meta"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill(MAN, {"id": "P4", "area": "api",
                                             "reviewSkill": "phase-review"})
    check("v4 the phase still wins over its area",
          (sk, basis) == ("phase-review", "phase"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill(MAN, {"id": "P5", "area": "api",
                                             "reviewSkill": None})
    check("v5 an explicit null on the phase is an ANSWER - 'not this one' must not "
          "fall through to the area that would have reviewed it",
          (sk, basis) == (None, "phase"), repr((sk, basis)))
    sk, basis = M.resolve_review_skill({"meta": {"areas": {"api": {"reviewSkill": None}}}},
                                       {"area": "api"})
    check("v6 ...and the same at the area level, over a meta default",
          (sk, basis) == (None, "area api"), repr((sk, basis)))
    check("v7 nothing anywhere is (None, '') - no basis to print",
          M.resolve_review_skill({"meta": {}}, {"id": "P1"}) == (None, ""))
    check("v8 resolution never raises on hostile shapes",
          M.resolve_review_skill(None, None) == (None, "")
          and M.resolve_review_skill({"meta": {"areas": {"a": 3}}}, {"area": "a"})
          == (None, ""))

    # --- skills resolution -------------------------------------------------------
    check("s1 area skills come first, then the task's",
          M.resolve_skills(MAN, MAN["phases"][0], {"skills": ["task-skill"]})
          == ["python-conv", "task-skill"])
    check("s2 several areas union in written order",
          M.resolve_skills(MAN, MAN["phases"][1], {"skills": ["t"]}) == ["ts-conv", "t"])
    check("s3 a skill named in both places is loaded once, area-first",
          M.resolve_skills(MAN, MAN["phases"][0], {"skills": ["python-conv", "x"]})
          == ["python-conv", "x"])
    check("s4 no area and no task skills is an empty list, not None",
          M.resolve_skills(MAN, MAN["phases"][2], None) == [])
    check("s5 junk entries are dropped, not rendered",
          M.resolve_skills({"meta": {"areas": {"a": {"skills": ["ok", 3, "  "]}}}},
                           {"area": "a"}, {"skills": [None, " y "]}) == ["ok", "y"])

    # --- (e) explicit-null opt-out (v0.37 B1) ------------------------------------
    # `task.skills: null` is an ANSWER — "no skills apply to this task" — and
    # STOPS the area fallback, mirroring reviewSkill (v5/v6) and owner (o4).
    # `[]`/absent stays "unconsidered": the area default applies, as before.
    check("e1 task.skills null loads NOTHING - the area default is stopped, "
          "not merged",
          M.resolve_skills(MAN, MAN["phases"][0], {"skills": None}) == [])
    check("e2 skills_opted_out tells null (an answer) from []/absent/junk (not)",
          M.skills_opted_out({"skills": None}) is True
          and M.skills_opted_out({"skills": []}) is False
          and M.skills_opted_out({}) is False
          and M.skills_opted_out(None) is False
          and M.skills_opted_out({"skills": "x"}) is False)
    check("e3 [] and absent still take the area default - the two unconsidered "
          "shapes did not change meaning",
          M.resolve_skills(MAN, MAN["phases"][0], {"skills": []}) == ["python-conv"]
          and M.resolve_skills(MAN, MAN["phases"][0], {}) == ["python-conv"])
    check("e4 an area-level null contributes nothing and stops nothing - the "
          "area IS the fallback; there is no level beneath it to stop",
          M.resolve_skills({"meta": {"areas": {"a": {"skills": None}}}},
                           {"area": "a"}, {"skills": ["t"]}) == ["t"])
    check("e5 a junk skills CONTAINER contributes nothing - a bare string used "
          "to load one 'skill' per character (found during v0.37 B, fixed here)",
          M.resolve_skills({}, {}, {"skills": "my-skill"}) == []
          and M.resolve_skills({"meta": {"areas": {"a": {"skills": "conv"}}}},
                               {"area": "a"}, None) == [])

    # --- conflicts + unregistered tags -------------------------------------------
    check("c1 two areas declaring DIFFERENT reviewers is a conflict worth naming",
          M.review_skill_conflicts(MAN, {"area": ["api", "sec"]})
          == [("api", "backend-review"), ("sec", "sec-review")])
    check("c2 agreement is not a conflict",
          M.review_skill_conflicts({"meta": {"areas": {"a": {"reviewSkill": "r"},
                                                       "b": {"reviewSkill": "r"}}}},
                                   {"area": ["a", "b"]}) == [])
    check("c3 one declaring area is not a conflict",
          M.review_skill_conflicts(MAN, {"area": ["web", "api"]}) == [])
    check("c4 unregistered tags are reported per phase, in order",
          M.unregistered_tags({"meta": {"areas": {"api": {}}},
                               "phases": [{"id": "P1", "area": ["api", "apu"]},
                                          {"id": "P2", "area": "web"}]})
          == [("P1", "apu"), ("P2", "web")])
    check("c5 NO registry means no unregistered tags - free-text tagging is the "
          "v0.16 feature and stays legal",
          M.unregistered_tags({"meta": {}, "phases": [{"id": "P1", "area": "x"}]}) == [])
    check("c6 used_tags lists every tag in first-seen order",
          M.used_tags(MAN) == ["api", "web", "sec"])

    # --- phase_tags: the read-time spend-attribution join ------------------------
    check("t1 phase_tags maps every phase id to its tags in written order",
          M.phase_tags(MAN) == {"P1": ["api"], "P2": ["web", "sec"], "P3": []})
    check("t2 an untagged phase is PRESENT with [] - 'known phase, no tags' must "
          "stay distinguishable from 'phase the plan never heard of'",
          M.phase_tags(MAN).get("P3") == [] and "P9" not in M.phase_tags(MAN))
    check("t3 tags arrive trimmed and deduped, the same normalisation both sides "
          "of every other lookup get",
          M.phase_tags({"phases": [{"id": "P1", "area": [" api ", "api", ""]}]})
          == {"P1": ["api"]})
    check("t4 hostile shapes are an empty map, never a raise - a phase without an "
          "id or that is not a dict is skipped",
          M.phase_tags(None) == {} and M.phase_tags({}) == {}
          and M.phase_tags({"phases": [3, {"area": "x"}, {"id": "P1"}]})
          == {"P1": []})

    # --- owner resolution ----------------------------------------------------------
    OMAN = {"meta": {"areas": {"api": {"root": "services/api", "owner": "jane@x.com"},
                               "web": {"root": "apps/web"},
                               "sec": {"root": ".", "owner": "raj@x.com"},
                               "none": {"root": "lib", "owner": None}}},
            "phases": [{"id": "P1", "area": "api"}]}
    check("o1 the area that declares an owner answers, and names itself",
          M.owner_of(OMAN, OMAN["phases"][0]) == ("jane@x.com", "api"))
    check("o2 a tag with no owner KEY is skipped, not read as 'nobody' - web is "
          "first and silent, so api answers",
          M.owner_of(OMAN, {"area": ["web", "api"]}) == ("jane@x.com", "api"))
    check("o3 written order decides between two areas that BOTH declare",
          M.owner_of(OMAN, {"area": ["api", "sec"]}) == ("jane@x.com", "api")
          and M.owner_of(OMAN, {"area": ["sec", "api"]}) == ("raj@x.com", "sec"))
    check("o4 an explicit null is an ANSWER - 'nobody owns this' stops the lookup "
          "and still names the area that said so",
          M.owner_of(OMAN, {"area": ["none", "api"]}) == (None, "none"))
    check("o5 nothing declared anywhere is (None, '') - distinguishable from o4",
          M.owner_of(OMAN, {"area": "web"}) == (None, "")
          and M.owner_of(OMAN, {"id": "PX"}) == (None, ""))
    check("o6 hostile shapes never raise",
          M.owner_of(None, None) == (None, "")
          and M.owner_of({"meta": {"areas": {"a": 3}}}, {"area": "a"}) == (None, "")
          and M.owner_of({"meta": {"areas": {"a": {"owner": 7}}}}, {"area": "a"})
          == (None, "a"))
    check("o7 an owner arrives trimmed; a whitespace-only owner reads as nobody "
          "but keeps the declaring tag",
          M.owner_of({"meta": {"areas": {"a": {"owner": " jane "}}}}, {"area": "a"})
          == ("jane", "a")
          and M.owner_of({"meta": {"areas": {"a": {"owner": "  "}}}}, {"area": "a"})
          == (None, "a"))
    f, w = M.validate_registry({"api": {"root": "a", "owner": "jane@x.com"}})
    check("o8 'owner' is a KNOWN key - it must not draw the unknown-key warning",
          not f and not w, repr((f, w)))
    f, _ = M.validate_registry({"api": {"root": "a", "owner": 3}})
    check("o9 a non-string non-null owner is a finding",
          len(f) == 1 and "owner" in f[0], repr(f))
    f, _ = M.validate_registry({"api": {"root": "a", "owner": ""}})
    check("o10 an empty-string owner is a finding - null is how you say nobody",
          len(f) == 1 and "owner" in f[0] and "null" in f[0], repr(f))
    f, w = M.validate_registry({"api": {"root": "a", "owner": None}})
    check("o11 an explicit null owner is legal and quiet - and NOTHING here asks "
          "the ledger whether the identity exists; that is the doctor's question",
          not f and not w, repr((f, w)))

    # --- F203: `skills: null` on an AREA -------------------------------------
    # THREE READERS OF ONE RULE, one of them out of step. The schema permits null
    # and documents why -- "allowed for symmetry with task.skills and EQUIVALENT
    # to []: the area is itself the fallback, so there is nothing beneath it for a
    # null to stop" -- and `resolve_skills` already treats the two identically.
    # This validator refused it, and CI runs BOTH the schema (ajv) and this: a
    # manifest carrying it passed one gate and failed the other. Found by a live
    # run that hit the refusal and then mis-cited the convention doc to explain
    # it, which is what a rule with two answers does to a reader.
    #
    # The intended shape was two lines up all along: `owner` and `reviewSkill`
    # both write `is not None and not isinstance(...)`. This branch omitted the
    # first half.
    f, w = M.validate_registry({"api": {"root": "a", "skills": None}})
    check("o12 an explicit null skills list is legal and quiet, exactly as the "
          "schema publishes it - narrowing the SCHEMA instead would have removed "
          "a documented spelling, which COMPATIBILITY.md makes a MAJOR release: "
          "%r" % ((f, w),),
          not f and not w)
    check("o13 ...and null RESOLVES the way the schema says it does, contributing "
          "nothing - the validator accepting it would be worth little if the "
          "resolver disagreed, and this is the pair that says they do not",
          M.resolve_skills(
              {"meta": {"areas": {"a": {"skills": None}}}},
              {"id": "P1", "area": "a"}, {"id": "P1.1", "skills": ["own"]})
          == M.resolve_skills(
              {"meta": {"areas": {"a": {"skills": []}}}},
              {"id": "P1", "area": "a"}, {"id": "P1.1", "skills": ["own"]}))
    # THE REGRESSION MY OWN REPAIR NEARLY SHIPPED. Letting null past the type
    # check sent it into the per-entry loop, which iterated it and raised
    # TypeError - a validator that CRASHES, which is worse than the finding the
    # repair removed. Caught by driving the validator, not by reading the branch.
    f, w = M.validate_registry({"api": {"root": "a", "skills": [1, ""]}})
    check("o14 a malformed skills ENTRY is still a finding, so the null path did "
          "not disable the per-entry check on its way through - the branch is "
          "`elif isinstance(...)` and not a bare `else` for exactly this reason: "
          "%r" % (f,),
          len(f) == 1 and "skills" in f[0] and "non-empty" in f[0])
    f, w = M.validate_registry({"api": {"root": "a", "skills": "conv"}})
    check("o15 ...and a non-list, non-null skills value is STILL refused, naming "
          "both legal spellings - the paired negative, since a check that simply "
          "stopped refusing would pass o12 exactly as the repair does: %r" % (f,),
          len(f) == 1 and "skills" in f[0] and "null" in f[0])

    # --- (n) declared non-string reviewSkill values (v0.36 A5) -------------------
    # The validator flags `reviewSkill: 3` as a finding; resolution must not hand
    # the raw junk to display surfaces meanwhile — it reached the panel as the
    # integer 3. Same hardening owner_of got in group o: invalid -> None, the
    # basis still names the level that declared it.
    sk, basis = M.resolve_review_skill({"meta": {"areas": {"x": {"reviewSkill": 3}}}},
                                       {"area": "x"})
    check("n1 a non-string area reviewSkill resolves to None but keeps its "
          "basis - the o6 hardening, applied to the reviewer lookup",
          (sk, basis) == (None, "area x"), repr((sk, basis)))
    check("n2 ...and at the phase level",
          M.resolve_review_skill({}, {"reviewSkill": 3}) == (None, "phase"))
    check("n3 ...and at the meta level",
          M.resolve_review_skill({"meta": {"reviewSkill": ["x"]}}, {})
          == (None, "meta"))
    check("n4 a padded skill name arrives trimmed, like every other value here",
          M.resolve_review_skill({}, {"reviewSkill": " backend-review "})
          == ("backend-review", "phase"))
    check("n5 an empty string reads as None with the declaring basis - it was "
          "already falsy, pinned now",
          M.resolve_review_skill({}, {"reviewSkill": ""}) == (None, "phase"))

    # --- registry validation -----------------------------------------------------
    f, w = M.validate_registry(MAN["meta"]["areas"])
    check("g1 a good registry has no findings", not f, repr(f))
    check("g2 ...and no warnings either, so a clean manifest stays quiet",
          not w, repr(w))
    check("g3 an absent registry is silent", M.validate_registry(None) == ([], []))
    f, _ = M.validate_registry([])
    check("g4 a non-object registry is a finding",
          len(f) == 1 and "must be an object" in f[0])
    f, _ = M.validate_registry({"api": "services/api"})
    check("g5 the likeliest typo - a bare path where the object goes - is a finding",
          len(f) == 1 and "got str" in f[0], repr(f))
    f, _ = M.validate_registry({"api": {"root": 3}})
    check("g6 a non-string root is a finding", len(f) == 1 and "root" in f[0], repr(f))
    f, w = M.validate_registry({"api": {}})
    check("g7 no root at all is a WARNING - the registry is informational",
          not f and len(w) == 1 and "no 'root'" in w[0], repr((f, w)))
    _, w = M.validate_registry({"api": {"root": "/Users/me/proj/services/api"}})
    check("g8 an absolute root warns: it cannot resolve in a second clone",
          len(w) == 1 and "absolute" in w[0], repr(w))
    _, w = M.validate_registry({"api": {"root": "C:/proj/api"}})
    check("g9 ...including the Windows spelling, which has no leading slash",
          len(w) == 1 and "absolute" in w[0], repr(w))
    _, w = M.validate_registry({"api": {"root": "../sibling"}})
    check("g10 a root outside the project directory warns",
          len(w) == 1 and "outside" in w[0], repr(w))
    _, w = M.validate_registry({"api": {"root": "a", "reviewskill": "x"}})
    check("g11 a miscased key warns rather than being a reviewer that never runs",
          len(w) == 1 and "unknown key" in w[0], repr(w))
    f, _ = M.validate_registry({"api": {"root": "a", "skills": "one-skill"}})
    check("g12 a bare string where the skills ARRAY goes is a finding - it would "
          "otherwise load one skill per character", len(f) == 1 and "skills" in f[0],
          repr(f))
    f, _ = M.validate_registry({"api": {"root": "a", "skills": ["ok", ""]}})
    check("g13 an empty skill name in the array is a finding", len(f) == 1, repr(f))
    f, _ = M.validate_registry({"api": {"root": "a", "description": 3}})
    check("g14 a non-string description is a finding", len(f) == 1, repr(f))
    f, _ = M.validate_registry({"api": {"reviewSkill": None, "root": "a"}})
    check("g15 ...but an explicitly null reviewSkill is legal - it is how an area "
          "says 'tests are the signer here'", not f, repr(f))
    f, _ = M.validate_registry({"  ": {"root": "a"}})
    check("g16 a blank tag name is a finding", len(f) == 1, repr(f))
    _, w = M.validate_registry({" api": {"root": "a"}})
    check("g17 a padded tag warns, since it is MATCHED trimmed and would otherwise "
          "look unregistered", len(w) == 1 and "whitespace" in w[0], repr(w))
    check("g18 validation never raises on hostile shapes",
          M.validate_registry({"a": None})[0] and M.validate_registry("x")[0])

    # --- roots on disk -----------------------------------------------------------
    # The project directory is the PLUGIN directory - `scripts` below has to
    # resolve as a real one. Named off `_harness.SCRIPTS_DIR` rather than off this
    # file, which sits in `tests/`; see the module docstring.
    here = _harness.SCRIPTS_DIR
    man = {"meta": {"areas": {"here": {"root": "scripts"},
                              "gone": {"root": "no/such/dir"},
                              "unstated": {"description": "no root"}}}}
    miss = M.missing_roots(man, os.path.dirname(here))
    check("d1 a root that is not a directory is reported, one that is is not, and "
          "an area with no root is skipped rather than called missing",
          miss == [("gone", "no/such/dir")], repr(miss))

    # --- the prose says what the code does ---------------------------------------
    drift = M.rule_drift()
    check("p1 every document that states the resolution states the SAME one - the "
          "orchestrator reads prose, and prose drift is worse than code drift "
          "because nothing runs it: %r" % (drift,), not drift)
    check("p2 the lint can fail: a doc missing the rule is reported",
          [r for r in M.rule_drift(_harness.SCRIPTS_DIR)
           if "unreadable" in str(r[1])])
    _fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ruledoc")
    os.makedirs(os.path.join(_fake, "reference"), exist_ok=True)
    os.makedirs(os.path.join(_fake, "commands"), exist_ok=True)
    try:
        for rel in M._RULE_DOCS:
            with open(os.path.join(_fake, rel), "w", encoding="utf-8") as fh:
                fh.write("The reviewer is `phase.reviewSkill ?? meta.reviewSkill`, "
                         "then `task.skills`, deduped, **area first**.\n")
        _d = M.rule_drift(_fake)
        check("p3 the pre-v0.28 two-level wording is caught wherever it survives - "
              "one file learning about areas while the others do not is exactly "
              "how this drifts",
              len([x for x in _d if "without the area" in str(x[1])]) == 4
              and all("phase.reviewSkill" in str(x[1])
                      for x in _d if "without the area" in str(x[1])), repr(_d))
        check("p4 ...and the same run reports the rule as missing, so a file can "
              "fail for both reasons at once",
              len([x for x in _d if x[1] == M.REVIEW_RULE]) == 4, repr(_d))
    finally:
        shutil.rmtree(_fake, ignore_errors=True)

    # --- F282: deleting a section of orchestrator.md turns a named case red ------
    # The measurement this block answers: each of the document's `##` sections was
    # deleted in turn and the whole gate set run, and NOT ONE deletion was
    # noticed. `rule_drift` above survived every one of them because its sentence
    # appears twice in the file, which is why these anchors are SECTION-scoped and
    # `rule_drift` is not.
    #
    # `a1` is the live claim; `a2`-`a5` are the four repairs it can report, each
    # driven on a FIXTURE tree so they keep working when the real document
    # changes. `a6`/`a7` are the coverage declaration, checked in both
    # directions - a list of exemptions that only grows is the shape this whole
    # block replaces.
    live = M.claim_drift()
    check("oa1 THE LIVE CLAIM: every anchored claim in reference/orchestrator.md "
          "is stated by the section that owns it, with the value the CODE says - "
          "%r" % (live,), live == [])
    cov = M.anchor_coverage()
    check("oa2 ...and the document really was read: %d '## ' section(s) found "
          "and %d anchored. A splitter that stopped matching would make oa1 an "
          "empty set agreeing with itself, which is exactly what a "
          "whole-document check was already doing here"
          % (len(cov["sections"]), len(cov["anchored"])),
          len(cov["sections"]) > 1 and len(cov["anchored"]) > 1
          and len(cov["anchored"]) <= len(cov["sections"]), repr(cov["sections"]))
    # The document side is a FIXTURE STRING and the code side stays the real
    # tree, which is the whole point of `claim_drift(text=...)`: a fixture tree
    # holding both would report every row as "the code moved" and the document
    # cases would pass for the wrong reason. Measured - the first version of
    # these cases did exactly that.
    real = os.path.join(_harness.SCRIPTS_DIR, os.pardir, M._ORCHESTRATOR)
    with open(real, "r", encoding="utf-8") as fh:
        body = fh.read()
    cut = M.doc_sections(body)
    names = [n for n, _b in cut]
    killed = "Concurrency lock"
    kept = "\n".join(["## %s\n%s" % (n, b) for n, b in cut if n != killed])
    after = M.claim_drift(text=kept)
    check("oa3 DELETING A SECTION IS A FINDING, and it names the section: "
          "cutting '## %s' out reports every claim anchored to it rather than "
          "passing because the rest of the document is intact. This is the "
          "measurement F282 records - each section was deleted in turn and not "
          "one deletion was noticed by anything" % killed,
          killed in names
          and [c for c, p in after if c.startswith("lock-exit")]
          and all("nowhere to live" in p for c, p in after
                  if c.startswith("lock-exit")), repr(after))
    # ...and the SECOND direction: the CODE moves, the document does not. This is
    # the half a presence assertion cannot reach, and the reason every row reads
    # a literal out of the module rather than trusting one written here.
    renum = M.claim_drift(text=body.replace("| **3** | held by a **live** run |",
                                            "| **7** | held by a **live** run |"))
    check("oa4 ...and so is the document stating a value the CODE does not: "
          "renumbering the lock's live-holder exit in the table alone is caught, "
          "because the row reads `_locks.py` and compares. Delete the comparison "
          "and this is the case that goes red",
          any(c == "lock-exit-live" and "does not state" in p
              for c, p in renum), repr(renum))
    # THE FLOOR UNDER EVERY MUTATION CASE ABOVE AND BELOW: the fixture door is
    # the same door. oa3, oa4, oa6, oa7 and oa12 all hand the document in as
    # `text`, and if that parameter took a different path through the function
    # than the file does, every one of them would be testing something the live
    # claim never runs. Handing in the real bytes must produce the real verdict.
    # (The over-fire direction - a row that reports regardless of what it read -
    # is oa1: an unconditional row makes the LIVE claim red, so it needs no case
    # of its own, and one asserting it here would be oa1 spelled twice.)
    check("oa5 the fixture door is the same door: handing the real document in "
          "as `text` gives the same verdict as reading it off disk, which is "
          "what makes every mutation case above a test of the live check",
          M.claim_drift(text=body) == M.claim_drift() == [],
          repr((M.claim_drift(text=body), M.claim_drift())))
    extra = body + "\n## Frobnication\n\nSomething new nobody anchored.\n"
    check("oa6 a NEW section with no anchor and no declared reason is a finding "
          "- a section in neither set is the silent mass F282 measured, and "
          "arriving quietly is how it got that big",
          any(c == "Frobnication" and "neither set" in p
              for c, p in M.claim_drift(text=extra)),
          repr(M.claim_drift(text=extra)))
    trimmed = "\n".join(["## %s\n%s" % (n, b) for n, b in cut
                         if n not in M.UNANCHORED_SECTIONS])
    check("oa7 ...and a DECLARED unanchored section that is gone (or has since "
          "been anchored) is a stale row, so the exemption list shrinks by being "
          "deleted rather than by going quiet",
          any("declared unanchored" in p
              for _c, p in M.claim_drift(text=trimmed)),
          repr(M.claim_drift(text=trimmed)))
    check("oa8 ...and every declared exemption carries a REASON long enough to "
          "be one: a label would let a section be exempted without anyone "
          "saying what would have to be built to anchor it",
          bool(M.UNANCHORED_SECTIONS)
          and all(len(why) >= 120 for why in M.UNANCHORED_SECTIONS.values()),
          repr(sorted((n, len(w)) for n, w in M.UNANCHORED_SECTIONS.items())))
    empty = M.claim_drift(text="no sections at all, just prose\n")
    check("oa9 a document with no '## ' at all is ONE finding about the SCAN, "
          "not a clean run and not a wall of findings about the document - an "
          "empty section list must never read as 'nothing wrong'",
          len(empty) == 1 and "no '## ' sections found" in empty[0][1],
          repr(empty))
    check("oa10 an unreadable document is a finding rather than a clean answer - "
          "the same rule `rule_drift` follows, and the reason `_read` returns "
          "None instead of the empty string that satisfies every `not in`",
          [r for r in M.claim_drift(_harness.SCRIPTS_DIR)
           if "unreadable" in str(r[1])],
          repr(M.claim_drift(_harness.SCRIPTS_DIR)[:2]))
    # A row whose CODE side has moved must be a finding too, not a pass: the
    # basis is gone, and a row with no basis making no claim is the shape
    # `CONTRIBUTING.md`'s cost example forbids.
    _saved = M.CLAIM_ANCHORS
    try:
        M.CLAIM_ANCHORS = (("gone-fact", "Concurrency lock", "value",
                            os.path.join("scripts", "governance", "_locks.py"),
                            r"NO_SUCH_CONSTANT\s*=\s*(\d+)", "", "| %s |"),)
        moved = M.claim_drift(text=body)
        check("oa11 a row whose CODE no longer carries the fact it is anchored "
              "to is a FINDING, not a pass. Without this the way to silence any "
              "row is to delete the constant it reads, which is the direction "
              "F271 and F276 already rotted in",
              any(c == "gone-fact" and "no longer carries the fact" in p
                  for c, p in moved), repr(moved))
    finally:
        M.CLAIM_ANCHORS = _saved
    # --- F282, second pass: the two things a review found this block claiming --
    # 1. A LIST CLAIM. `## Keeping a failed run's record` names the evidence
    #    statuses a run can strand, and that list went stale inside the very
    #    change that added these anchors: the section was anchored, but only by a
    #    row reading a check NAME, so `claim_drift` was blind to the list. F282's
    #    own class in F282's own commit.
    check("oa13 the evidence vocabulary is DERIVED from the enum that owns it, "
          "not restated: every member of `_status_facts.NO_SIGN_OFF_EVIDENCE` is "
          "named by the section, and every word the section names is a member",
          not [p for c, p in M.claim_drift()
               if c == "audit-state-statuses"],
          repr([p for c, p in M.claim_drift() if c == "audit-state-statuses"]))
    # DROPS THE NEWEST MEMBER, and one member rather than three: the previous
    # spelling anchored on the whole head of the list, so adding `gate-mutated` to
    # the section - the very edit this anchor exists to force - stopped the
    # mutation landing and the case reported an empty finding list instead of
    # going red for a reason. A one-member drop is also the real shape: a word
    # joins the enum and the document is updated everywhere except here.
    _gained = body.replace("`gate-mutated`, ", "")
    check("oa14 ...and a member the section STOPS naming is a finding, which is "
          "the direction that was blind - a status the code produces and the "
          "orchestrator has never heard of",
          any(c == "audit-state-statuses" and "does not name it" in p
              for c, p in M.claim_drift(text=_gained)),
          repr(M.claim_drift(text=_gained)))
    # THE INVENTED WORD IS INVENTED ON PURPOSE, and it did not start that way:
    # this case was written against `gate-mutated`, which was in no enum on the
    # branch that wrote it and IS one here, so the case broke on the merge that
    # added the member. A fixture naming a real-but-absent word tests the rule
    # only until somebody implements that word. `never-a-status` cannot become a
    # member, so the case survives every future addition to the enum.
    _invented = body.replace("`could-not-run`\nevidence can sit",
                             "`could-not-run` and `never-a-status`\n"
                             "evidence can sit")
    check("oa15 ...and a word the section names that the enum does NOT have is "
          "also a finding. This is the half that stops a status being written "
          "into the prose before the code produces it, which is what F271 and "
          "F276 already were",
          any(c == "audit-state-statuses" and "no such member" in p
              for c, p in M.claim_drift(text=_invented)),
          repr(M.claim_drift(text=_invented)))
    # --- F303: the clause a five-claim section was not holding -----------------
    # `## Phase sign-off` told the reader `/audit:task scope` refuses a `done`
    # task, and F283 had already reversed that: driven on one fixture with only
    # the status changed, the released v2.2.0 exits 2 and this tree exits 0 having
    # widened `files`. The ADVICE survived - a finding in an undeclared file still
    # wants a new task, because the widening settles the index and records no new
    # work - so a reader checks the reasoning, finds it sound, and never re-checks
    # the clause under it. The section was already anchored several claims deep
    # and not one of them read that sentence, which is what a per-SECTION coverage
    # figure actually buys; `_areas.py --coverage` prints the per-claim answer.
    check("oa20 the statuses `scope` REFUSES are read out of the verb, not "
          "restated beside it: `## Phase sign-off` names every status the guard "
          "in `_locked_scope` turns away, and every status it names is one",
          not [p for c, p in M.claim_drift()
               if c == "scope-refusal-statuses"],
          repr([p for c, p in M.claim_drift()
                if c == "scope-refusal-statuses"]))
    # F303 ITSELF, in the direction the document rotted: it named a status the
    # verb does not refuse. One word swapped inside the anchored sentence, which
    # is the smallest edit that reproduces the fault.
    _refused_wrong = body.replace("refusal to `cancelled` alone,",
                                  "refusal to `done` alone,")
    check("oa21 ...and naming a status the verb does NOT refuse is a finding in "
          "both halves at once - the word the code has no member for, and the "
          "member the section stopped naming. This is F303 exactly: the clause "
          "read `done` for a release and a half while the code refused only "
          "`cancelled`",
          _refused_wrong != body
          and any(c == "scope-refusal-statuses" and "no such member" in p
                  for c, p in M.claim_drift(text=_refused_wrong))
          and any(c == "scope-refusal-statuses" and "does not name it" in p
                  for c, p in M.claim_drift(text=_refused_wrong)),
          repr([p for c, p in M.claim_drift(text=_refused_wrong)
                if c == "scope-refusal-statuses"]))
    # ...and the WHOLE clause put back the way it read before this fix, which is
    # the mutation a reverting edit would actually make. It takes the marker with
    # it, so the finding is about the list no longer being locatable rather than
    # about a member - a reworded mechanism is a mechanism somebody has to
    # re-check.
    _pre_f303 = body.replace(
        "It no longer refuses a finished\n   task. F283 narrowed that refusal to "
        "`cancelled` alone,\n   and a `done` task will take a widening",
        "It refuses a `done` task on purpose, and every task is `done` by the "
        "time you are reading this step")
    check("oa22 ...and reverting the clause to the sentence F283 had already "
          "falsified is a finding too, because it takes the anchored mechanism "
          "with it: the list can no longer be located, which is the repair "
          "rather than a member to add",
          _pre_f303 != body
          and any(c == "scope-refusal-statuses" and "cannot be located" in p
                  for c, p in M.claim_drift(text=_pre_f303)),
          repr([p for c, p in M.claim_drift(text=_pre_f303)
                if c == "scope-refusal-statuses"]))
    # THE OTHER DIRECTION, AND THE ONE A DOCUMENT CASE CANNOT REACH: the VERB
    # changes under a correct document. The row is repointed at a guard in the
    # same file that really does refuse two statuses - `cancel`'s - so the
    # comparison is driven against real bytes rather than a hand-written pair.
    # Widening `scope`'s refusal back over `done` is what this simulates, and it
    # must be reported as the member the section never learned.
    _saved_lists = M.LIST_ANCHORS
    try:
        M.LIST_ANCHORS = tuple(
            row if row[0] != "scope-refusal-statuses"
            else (row[0], row[1], row[2],
                  r'node\.get\("status"\) in \(([^)]*)\):\s*\n'
                  r'\s*# Terminal is terminal',
                  row[4])
            for row in _saved_lists)
        _widened = M.claim_drift(text=body)
        check("oa23 ...and a VERB that starts refusing a status the document "
              "does not name is a finding under a document nobody touched. "
              "Without this half the anchor only ever watches the prose, which "
              "is how F283 reversed the code and left the clause standing",
              any(c == "scope-refusal-statuses" and "'done'" in p
                  and "does not name it" in p for c, p in _widened),
              repr([p for c, p in _widened
                    if c == "scope-refusal-statuses"]))
    finally:
        M.LIST_ANCHORS = _saved_lists
    # --- F334: the window this row searches, and what bounds it ---------------
    # THE PATTERN USED TO BE UNBOUNDED - `.*?` under `re.S` - and the shape it
    # anchors on is not unique to the verb it names: a status test beside an
    # `out(` prefix is ordinary code here, where the row above it anchors on a
    # constant NAME that occurs once. So deleting `_locked_scope`'s refusal did
    # not report a deleted refusal. The scan read past the end of the function,
    # latched onto `retarget`'s guard further down the file, and told the reader
    # `## Phase sign-off` fails to name `done` - a status `scope` no longer
    # refuses at all, sending the repair to the document. `_list_anchor_drift`
    # already carried the branch that is right for a deleted guard and the
    # window made it unreachable.
    #
    # DRIVEN ON THE REAL BYTES with the status test neutralised, which is the
    # smallest edit that takes the shape out of the function and leaves
    # everything below it standing. A hand-written verb here would be a fixture
    # that agrees with whichever pattern wrote it.
    _verb_rel = os.path.join("scripts", "manifest", "audit-task.py")
    with open(os.path.join(_harness.SCRIPTS_DIR, "manifest", "audit-task.py"),
              "r", encoding="utf-8") as fh:
        _verb_src = fh.read()
    _guard_test = '    if node.get("status") == "cancelled":\n'
    _blinded = _verb_src.replace(_guard_test, "    if False:\n")
    _scratch = tempfile.mkdtemp(prefix="areas-code-side-")
    try:
        os.makedirs(os.path.join(_scratch, os.path.dirname(_verb_rel)))
        with open(os.path.join(_scratch, _verb_rel), "w",
                  encoding="utf-8") as fh:
            fh.write(_blinded)
        _gone = [p for c, p in M.claim_drift(plugin_root=_scratch, text=body)
                 if c == "scope-refusal-statuses"]
        check("oa26 a DELETED guard is reported as a deleted guard: with the "
              "status test gone from `_locked_scope`, the row says the file no "
              "longer carries the vocabulary it is anchored to and says nothing "
              "about a member. F334 read the NEXT verb's guard instead and "
              "blamed the document for not naming a status `scope` had stopped "
              "refusing",
              _verb_src.count(_guard_test) == 1 and _blinded != _verb_src
              and any("no longer carries the vocabulary" in p for p in _gone)
              and not any("does not name it" in p or "no such member" in p
                          for p in _gone),
              repr(_gone))
        # ...and the case above is DISCRIMINATING rather than green by luck. The
        # pre-F334 spelling is derived from the row's own pattern instead of
        # copied, so it cannot drift from what it claims to compare, and it must
        # still find a match in these same bytes: the deletion case only proves
        # a bound while there is something below the function for an unbounded
        # scan to slide onto, and the day `retarget`'s guard moves it would go
        # green under either pattern.
        _pat = [r[3] for r in M.LIST_ANCHORS
                if r[0] == "scope-refusal-statuses"][0]
        _loose = _pat.replace(r"(?:(?!\n\S).)*?", ".*?")
        check("oa27 ...and the bound is what makes that true: the UNBOUNDED "
              "spelling of this very row still matches those bytes, further "
              "down the file, where the bounded one does not match at all. A "
              "proof of a bound has to show the two patterns disagreeing on one "
              "input",
              _loose != _pat
              and re.search(_loose, _blinded, re.S) is not None
              and re.search(_pat, _blinded, re.S) is None,
              repr((_loose != _pat,
                    bool(re.search(_loose, _blinded, re.S)),
                    bool(re.search(_pat, _blinded, re.S)))))
    finally:
        shutil.rmtree(_scratch, ignore_errors=True)
    # --- F330a: an empty vocabulary is a finding about the SCAN ---------------
    # A pattern can match and still parse to nothing - the enum is emptied, or a
    # capture is narrowed to a group that no longer holds a member - and an empty
    # set agrees with EVERY document, so the set difference both directions of
    # this row rest on reports a clean answer over nothing at all. That refusal
    # was written before either list row and had no case, which is the shape
    # `no-silent-pass` calls a filter narrowing to nothing and reading as "all
    # clear". It is load-bearing in more places now that a second row leans on
    # it.
    #
    # THE FIXTURE IS THE ENUM EMPTIED, on the real module's bytes, by a
    # substitution rather than a rewritten line - so it survives the declaration
    # being reformatted, and it asserts that it landed. `audit-state-statuses` is
    # the row it is driven through because its capture CAN come back empty;
    # `scope-refusal-statuses` cannot be reached this way at all, since its group
    # requires a quoted member to match in the first place.
    _facts_rel = os.path.join("scripts", "status", "_status_facts.py")
    with open(os.path.join(_harness.SCRIPTS_DIR, "status", "_status_facts.py"),
              "r", encoding="utf-8") as fh:
        _facts_src = fh.read()
    _emptied = re.sub(r"(NO_SIGN_OFF_EVIDENCE = frozenset\(\{)[^}]*(\})",
                      r"\1\2", _facts_src, count=1)
    _scratch = tempfile.mkdtemp(prefix="areas-code-side-")
    try:
        os.makedirs(os.path.join(_scratch, os.path.dirname(_facts_rel)))
        with open(os.path.join(_scratch, _facts_rel), "w",
                  encoding="utf-8") as fh:
            fh.write(_emptied)
        _void = [p for c, p in M.claim_drift(plugin_root=_scratch, text=body)
                 if c == "audit-state-statuses"]
        check("oa28 an enum that parses to an EMPTY vocabulary is a finding "
              "about the scan, not a clean answer: the row says so and reports "
              "no member, where blinding that refusal turns every word the "
              "section names into 'a status the code does not produce' - a wall "
              "of findings against a document nobody touched, pointing at the "
              "wrong side",
              _emptied != _facts_src
              and "NO_SIGN_OFF_EVIDENCE = frozenset({})" in _emptied
              and any("EMPTY vocabulary" in p for p in _void)
              and not any("no such member" in p for p in _void),
              repr(_void))
    finally:
        shutil.rmtree(_scratch, ignore_errors=True)
    # THE SECOND DIRECTION, and it is the case that looks vacuous: it asserts a
    # vocabulary that HAS members produces no empty-set finding, which is true of
    # the code before that refusal existed. It is the only case that fails when
    # the refusal is made unconditional, and an unconditional one would report
    # every list row on every run - so it stays, with this comment saying which
    # mutation it is here for.
    check("oa29 ...and it stays quiet on a vocabulary that has members: the "
          "live rows report no empty-set finding at all. Make that refusal "
          "unconditional and this is the case that goes red - the direction the "
          "case above cannot see",
          not [p for c, p in M.claim_drift() if "EMPTY vocabulary" in p],
          repr([r for r in M.claim_drift() if "EMPTY vocabulary" in r[1]]))
    # --- coverage is derived from EVERY anchor table, not just the first -------
    _claims = M.anchor_coverage()["claims"]
    _sign_off = [n for n in _claims if n.startswith("Phase sign-off")]
    _failed_run = [n for n in _claims if n.startswith("Keeping a failed run")]
    check("oa24 the coverage table counts a LIST row as the anchor it is: both "
          "vocabularies show up under the section that carries them. Reading "
          "only `CLAIM_ANCHORS` showed `## Keeping a failed run's record` with "
          "one claim while it carried two",
          len(_sign_off) == 1 and len(_failed_run) == 1
          and "scope-refusal-statuses" in _claims[_sign_off[0]]
          and "audit-state-statuses" in _claims[_failed_run[0]],
          repr(_claims))
    _saved_lists, _saved_claims = M.LIST_ANCHORS, M.CLAIM_ANCHORS
    try:
        M.LIST_ANCHORS = (("frob-vocab", "Frobnication",
                           os.path.join("scripts", "status",
                                        "_status_facts.py"),
                           r"NO_SIGN_OFF_EVIDENCE\s*=\s*frozenset\(\{([^}]*)\}",
                           "the statuses this section names"),)
        _frob = body + ("\n## Frobnication\n\nAnchored by a list row alone. "
                        "So `blocked`\nthe statuses this section names\n")
        check("oa25 ...and a section anchored ONLY by a list row is anchored: it "
              "shows in the coverage and is NOT reported as being in neither "
              "set. The consequence of the narrower read had not happened yet, "
              "which is the cheap moment to close it - a finding against a "
              "section that IS anchored is the worst kind of false one",
              "Frobnication" in M.anchor_coverage(text=_frob)["anchored"]
              and not [p for c, p in M.claim_drift(text=_frob)
                       if c == "Frobnication" and "neither set" in p],
              repr([r for r in M.claim_drift(text=_frob)
                    if r[0] in ("Frobnication", "frob-vocab")]))
    finally:
        M.LIST_ANCHORS, M.CLAIM_ANCHORS = _saved_lists, _saved_claims
    # 2. THE STRENGTH DECLARATION. The block comment said every row derives a
    #    value from the code; a review measured that seven did not. Declaring the
    #    strength is worth nothing unless the declaration is checked, so it is.
    check("oa16 every row's DECLARED strength is one it can deliver: a 'value' "
          "row captures a group that can match something else and substitutes "
          "it, a 'presence' row asserts a fixed shape, a 'pinned' row names no "
          "module. This is what stops the block comment over-claiming again",
          M._strength_mismatches() == [], repr(M._strength_mismatches()))
    _saved_rows = M.CLAIM_ANCHORS
    try:
        M.CLAIM_ANCHORS = tuple(
            (row[0], row[1], "value", row[3], row[4], row[5], row[6])
            if row[2] == "presence" else row for row in _saved_rows)
        check("oa17 ...and a presence row RELABELLED 'value' is a finding, "
              "because its capture is a literal spelled inside its own pattern "
              "and a group that can only match itself derives nothing. That is "
              "the exact over-claim, caught by name",
              [c for c, p in M._strength_mismatches()
               if "derives nothing" in p],
              repr(M._strength_mismatches()[:2]))
        M.CLAIM_ANCHORS = tuple(
            (row[0], row[1], "presence", row[3], row[4], row[5], row[6])
            if row[2] == "value" else row for row in _saved_rows)
        check("oa18 ...and the other direction: a value row relabelled "
              "'presence' is a finding too, so the strengths cannot be made to "
              "agree by weakening every claim",
              [c for c, p in M._strength_mismatches()
               if "should claim it" in p],
              repr(M._strength_mismatches()[:2]))
    finally:
        M.CLAIM_ANCHORS = _saved_rows
    check("oa19 the capture reader tells a varying group from a literal one - "
          "that distinction is the whole basis of oa16, and reading it wrong in "
          "either direction relabels every row",
          M._capture_source(r'X\s*=\s*"([^"]+)"') == '[^"]+'
          and M._capture_source(r'"(GATE MUTATED THE TREE)') ==
          "GATE MUTATED THE TREE"
          and M._capture_source(r"(?:not a capture)") is None
          and M._capture_source(r"A(B(C))") == "B(C)",
          repr((M._capture_source(r'X\s*=\s*"([^"]+)"'),
                M._capture_source(r"(?:not a capture)"),
                M._capture_source(r"A(B(C))"))))
    # THE CONTEXT WINDOW IS LOAD-BEARING and this is the case that says so.
    # `## Preflight` states two defaults in the same shape - `(default main)` for
    # the development branch and `(default audit)` for the branch prefix - so a
    # row searching the WHOLE section could be satisfied by the neighbour's
    # value. Here the prefix's own default is wrong and the right string is
    # planted elsewhere in the same section: a laundered claim must still be a
    # finding.
    laundered = body.replace(
        "prefix for per-phase branches (default `audit`)",
        "prefix for per-phase branches (default `qa`)").replace(
        "- `meta.developmentBranch` —",
        "- Somewhere else entirely, mentioning (default `audit`) in passing.\n"
        "- `meta.developmentBranch` —")
    check("oa12 a claim satisfied by a NEIGHBOUR's value in the same section is "
          "still a finding - two defaults written in one shape is exactly why "
          "the row carries a context substring and a window rather than "
          "searching the section",
          "(default `qa`)" in laundered
          and any(c == "branch-prefix-default" and "does not state" in p
                  for c, p in M.claim_drift(text=laundered)),
          repr(M.claim_drift(text=laundered)))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__areas.py --selftest\n")
    raise SystemExit(2)
