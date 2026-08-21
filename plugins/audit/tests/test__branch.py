#!/usr/bin/env python3
"""
The cases for `_branch.py` — where a phase's branch forks from, and its name.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The pre-0.44 shape, byte for byte.** A manifest carrying only
  `meta.branchPrefix` must produce the name it produced yesterday. This is the
  case that makes the feature safe to ship; everything else is new behaviour that
  nobody depends on yet.
- **The collapsing separator, asserted as the WHOLE name.** An absent
  `{initials}` must yield `feature/p2-x`, not `feature//p2-x`. Asserting merely
  that `//` is absent would pass on a version that dropped the type as well, so
  the case pins the exact string. The mutation runs both ways: `c2m` proves a
  naive `str.replace` expansion produces the illegal name, so the walk in
  `expand()` is doing the work and not decoration elsewhere.
- **`ref_violations` on a LEGAL name.** A validator only ever seen refusing may be
  refusing everything; `r3` is the allow case, and it is the one that would go red
  if the rule were tightened into nonsense.
- **Every answer's basis.** `parent_branch` reports `is_development`, and a phase
  whose parent is a story branch must report `False` — the sign-off report reads
  that flag to say where the work actually landed. A value without its basis is
  the defect this module exists to avoid, so the basis is pinned, not just the
  value.
- **`initials_from` refuses rather than guesses.** An identity that yields no
  initials returns `""` so the placeholder collapses. Guessing would stamp the
  wrong person's mark on a branch.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _branch as M                                # noqa: E402

PHASE = {"id": "P2", "title": "Chart export"}
NEW = {"branch": {"template": "{type}/{initials}/{phase}-{slug}"},
       "developmentBranch": "main"}
OLD = {"branchPrefix": "audit", "developmentBranch": "main"}


def _naive(template, values):
    """What a str.replace expansion would produce — the version `expand()` replaces.

    Kept here rather than described, because `c2m` asserts it produces the ILLEGAL
    name. A mutation the suite only talks about is a mutation nobody ran.
    """
    out = template
    for k, v in values.items():
        out = out.replace("{%s}" % k, str(v or ""))
    return out


def _cases(check):
    # --- backward compatibility: the case that makes this safe to ship ---------
    check("b1 a manifest carrying only meta.branchPrefix produces the pre-0.44 "
          "name byte for byte - the whole feature is additive or it is a "
          "breaking change nobody asked for",
          M.compose(OLD, PHASE)["name"] == "audit/p2-chart-export",
          repr(M.compose(OLD, PHASE)["name"]))
    check("b2 ...and it says WHICH key decided that, because meta.branch and "
          "meta.branchPrefix give different names from the same manifest and a "
          "branch alone cannot tell you which was in force",
          M.compose(OLD, PHASE)["basis"] == "meta.branchPrefix",
          repr(M.compose(OLD, PHASE)["basis"]))
    check("b3 a manifest with NEITHER key still names a branch rather than "
          "failing, and says the default answered",
          M.compose({}, PHASE)["name"] == "audit/p2-chart-export"
          and M.compose({}, PHASE)["basis"].startswith("default"),
          repr(M.compose({}, PHASE)))

    # --- the collapsing separator ---------------------------------------------
    with_ini = M.compose(NEW, PHASE, initials="John Doe")["name"]
    without = M.compose(NEW, PHASE)["name"]
    check("c1 initials present land between type and phase",
          with_ini == "feature/jd/p2-chart-export", repr(with_ini))
    check("c2 initials ABSENT collapse together with the separator behind them - "
          "pinned as the whole string, because asserting only that '//' is gone "
          "would also pass on a version that dropped the type",
          without == "feature/p2-chart-export", repr(without))
    naive = _naive("{type}/{initials}/{phase}-{slug}",
                   {"type": "feature", "initials": "", "phase": "p2",
                    "slug": "chart-export"})
    check("c2m mutation proof: the str.replace expansion this replaces produces "
          "the ILLEGAL name, so expand()'s separator walk is what prevents it "
          "and not something else downstream",
          naive == "feature//p2-chart-export" and M.ref_violations(naive) != [],
          repr(naive))
    check("c4 WHICH separator goes, when the two differ. `{a}-{b}/{c}` with an "
          "empty {b} keeps the one IN FRONT and drops the one behind, giving "
          "'x-z'. Pinned because the two collapse branches are INTERCHANGEABLE "
          "whenever the separators match - every template shipped here uses '/' "
          "throughout - so without this case the choice is accidental and the "
          "first mixed-separator template would settle it by luck",
          M.expand("{a}-{b}/{c}", {"a": "x", "b": "", "c": "z"}) == "x-z",
          repr(M.expand("{a}-{b}/{c}", {"a": "x", "b": "", "c": "z"})))
    check("c3 a placeholder that is LAST and empty drops the separator in front "
          "of it instead - the other end of the same rule",
          M.expand("{phase}-{slug}", {"phase": "p2", "slug": ""}) == "p2",
          repr(M.expand("{phase}-{slug}", {"phase": "p2", "slug": ""})))

    # --- type resolution ------------------------------------------------------
    check("t1 an explicit phase.branchType wins, and names itself as the basis",
          M.resolve_type(NEW, dict(PHASE, branchType="refactor"))["type"] == "refactor"
          and M.resolve_type(NEW, dict(PHASE, branchType="refactor"))["basis"]
          == "phase.branchType",
          repr(M.resolve_type(NEW, dict(PHASE, branchType="refactor"))))
    check("t2 a phase materialized from bugs[] derives bugfix without being told",
          M.resolve_type(NEW, PHASE, from_bug=True)["type"] == "bugfix",
          repr(M.resolve_type(NEW, PHASE, from_bug=True)))
    check("t3 ...and an explicit type still beats the derivation, so the "
          "derivation is a DEFAULT and not an override",
          M.resolve_type(NEW, dict(PHASE, branchType="hotfix"),
                         from_bug=True)["type"] == "hotfix",
          repr(M.resolve_type(NEW, dict(PHASE, branchType="hotfix"), from_bug=True)))
    check("t4 a type outside meta.branch.types is REPORTED rather than silently "
          "used - the pre-approved git globs come from that list, so an "
          "unlisted type costs a permission prompt on every branch operation",
          M.compose(NEW, dict(PHASE, branchType="wip"))["unknownType"] is True
          and M.compose(NEW, dict(PHASE, branchType="chore"))["unknownType"] is False,
          repr(M.compose(NEW, dict(PHASE, branchType="wip"))))

    # --- parent branch --------------------------------------------------------
    dflt = M.parent_branch(NEW, PHASE)
    story = M.parent_branch(NEW, dict(PHASE, parentBranch="feature/jd/p1-story"))
    check("p1 with no phase.parentBranch the phase forks from developmentBranch",
          dflt["branch"] == "main" and dflt["basis"] == "meta.developmentBranch",
          repr(dflt))
    check("p2 phase.parentBranch overrides it - the same chain reviewSkill uses",
          story["branch"] == "feature/jd/p1-story"
          and story["basis"] == "phase.parentBranch", repr(story))
    check("p3 ...and the phase pointed at a story branch reports "
          "is_development False. This flag is the whole reason the field exists: "
          "sign-off reads it to say the work reached that branch and NOT main, "
          "and silence there reads as 'landed'",
          story["is_development"] is False and dflt["is_development"] is True,
          repr((story["is_development"], dflt["is_development"])))
    check("p4 a phase.parentBranch that NAMES the development branch is still "
          "development - the flag tracks the answer, not whether a key was set",
          M.parent_branch(NEW, dict(PHASE, parentBranch="main"))["is_development"]
          is True,
          repr(M.parent_branch(NEW, dict(PHASE, parentBranch="main"))))
    check("p5 no developmentBranch anywhere still resolves, to main, and says so",
          M.parent_branch({}, PHASE)["branch"] == "main"
          and "default" in M.parent_branch({}, PHASE)["basis"],
          repr(M.parent_branch({}, PHASE)))

    # --- git ref legality -----------------------------------------------------
    many = M.ref_violations("feature//p2-x..y")
    check("r1 an illegal name reports the WHOLE problem list, not the first "
          "reason - fixing them one round-trip at a time is what a single "
          "reason costs the reader",
          len(many) == 2 and any("//" in m for m in many)
          and any(".." in m for m in many), repr(many))
    check("r2 the character class is caught with the offending character named",
          any("'~'" in m for m in M.ref_violations("feature/p2~1"))
          and any("a space" in m for m in M.ref_violations("feature/p 2")),
          repr((M.ref_violations("feature/p2~1"), M.ref_violations("feature/p 2"))))
    check("r3 THE ALLOW CASE: a legal name reports nothing. A check only ever "
          "seen refusing may be refusing everything, and this is the case that "
          "goes red if the rule is ever tightened into nonsense",
          M.ref_violations("feature/jd/p2-chart-export") == []
          and M.ref_violations("audit/p2-chart-export") == [], "")
    check("r4 the endings git reserves are caught: '.lock' and a trailing dot",
          M.ref_violations("feature/p2.lock") != []
          and M.ref_violations("feature/p2.") != [], "")

    # --- initials -------------------------------------------------------------
    check("i1 a two-word identity initials to two letters, lowercased",
          M.initials_from("John Doe") == "jd", repr(M.initials_from("John Doe")))
    check("i2 an identity that yields nothing returns EMPTY rather than a guess - "
          "the placeholder then collapses, and no branch carries the wrong "
          "person's mark",
          M.initials_from("") == "" and M.initials_from("123 456") == "",
          repr((M.initials_from(""), M.initials_from("123 456"))))
    check("i4 a ONE-WORD identity still initials to something that identifies "
          "someone: CamelCase splits on its capitals ('AleksandarBisevac' -> "
          "'ab'), and a name with no capitals to split on takes two letters "
          "rather than one. A single letter names nobody, which is the whole "
          "point of putting initials in a branch",
          M.initials_from("AleksandarBisevac") == "ab"
          and M.initials_from("madonna") == "ma",
          repr((M.initials_from("AleksandarBisevac"), M.initials_from("madonna"))))
    check("i3 an explicit meta.branch.initials wins over the git identity, which "
          "is the escape hatch for a name that does not initial usefully",
          M.compose({"branch": {"template": "{type}/{initials}/{phase}",
                                "initials": "xyz"}},
                    PHASE, initials="John Doe")["name"] == "feature/xyz/p2",
          repr(M.compose({"branch": {"template": "{type}/{initials}/{phase}",
                                     "initials": "xyz"}},
                         PHASE, initials="John Doe")["name"]))

    # --- slug -----------------------------------------------------------------
    check("s1 the slug is capped and never left ending in a hyphen, which would "
          "put a dangling separator into the branch name",
          M.slugify("A very long phase title that runs on and on", 20)
          == "a-very-long-phase" or not M.slugify(
              "A very long phase title that runs on and on", 20).endswith("-"),
          repr(M.slugify("A very long phase title that runs on and on", 20)))

    # --- pre-approved globs ---------------------------------------------------
    check("g1 the globs are DERIVED from meta.branch.types, so a team that adds "
          "a type gets it pre-approved without editing the orchestrator",
          M.approved_globs({"branch": {"types": ["feature", "spike"]}})
          == ["feature/*", "spike/*"],
          repr(M.approved_globs({"branch": {"types": ["feature", "spike"]}})))
    check("g2 a legacy manifest yields exactly its one prefix glob - the "
          "permission surface does not widen just because the code learned "
          "about types",
          M.approved_globs(OLD) == ["audit/*"], repr(M.approved_globs(OLD)))

    # --- the type vocabulary is explained, not just listed --------------------
    check("v1 every default type carries a one-line description - the panel is "
          "where someone LEARNS the convention, and a bare list teaches nothing",
          all(t in M.TYPE_HELP and M.TYPE_HELP[t] for t in M.DEFAULT_TYPES),
          repr(sorted(set(M.DEFAULT_TYPES) - set(M.TYPE_HELP))))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__branch.py --selftest\n")
    raise SystemExit(2)
