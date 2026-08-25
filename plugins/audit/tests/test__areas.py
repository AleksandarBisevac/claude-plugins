#!/usr/bin/env python3
"""
The cases for `_areas.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THREE OF THESE CASES COMPUTE A PATH, AND A TEST FILE SITS ONE DIRECTORY OVER, so
each was checked rather than carried:

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

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import sys

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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__areas.py --selftest\n")
    raise SystemExit(2)
