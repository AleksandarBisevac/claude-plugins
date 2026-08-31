#!/usr/bin/env python3
"""
The cases for `_doctor_policy.py` — the three checks that compare a declaration
against the world it claims to describe.

Every row this module can emit is a WARNING or an OK, and several cases below
exist only to hold that line: an area root that is not there, a policy pattern
naming nothing installed, a runner missing from PATH — none of them is proof
the repo is broken, and CI's manifest job (which deliberately does not install
the Claude CLI) is the worked example of a FINDING here failing a build over a
correct observation.

`check_policy` is driven through its `_discover` seam rather than a real
discovery scan: what this machine has installed is not a fact a suite may
depend on, and the seam is in the product precisely so the cases do not.

`_leading_executable`'s grid is the one place a table is the right shape — the
function's whole contract is "what would a shell run, or None if that cannot be
decided", and the cases that matter are the ones where guessing produced a false
FINDING on this repo's own `for f in ...; do` loop.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_policy as M                         # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)
import _loader                                     # noqa: E402


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _fix(rep, name):
    """The `fix` half of the rows for `name` — where a row says what to DO, which
    is a different claim from what it observed and is asserted separately."""
    return " ".join(r.get("fix") or "" for r in rep.rows if r["check"] == name)


def _manifest():
    return {
        "meta": {"version": 2, "title": "t"},
        "phases": [{"id": "P1", "title": "one", "status": "pending",
                    "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                               "files": ["a.py"], "tests": {"mode": "tdd"},
                               "risk": "low"}]}],
        "bugs": [], "fileIndex": {"a.py": ["P1.1"]},
    }


# --- cases --------------------------------------------------------------------
def _cases(check):
    import tempfile

    # ------------------------------------------------- _leading_executable
    GRID = (
        ("pytest", "pytest"),
        ("npm test", "npm"),
        ("cd app && yarn test", "yarn"),
        ("cd app && cd deep && make check", "make"),
        ("env FOO=1 pytest", "pytest"),
        ("FOO=1 BAR=2 pytest", "pytest"),
        ("./scripts/run.sh", "./scripts/run.sh"),
        # `env` is stripped only when spelled bare: a PATH-qualified /usr/bin/env
        # is the executable, and pretending otherwise would report the wrong
        # binary as missing.
        ("/usr/bin/env python3 -m pytest", "/usr/bin/env"),
        ("a/b=c pytest", "a/b=c"),
        ("", None), ("   ", None),
        ("for f in *; do x; done", None),
        ("while true; do x; done", None),
        ("if [ -f x ]; then y; fi", None),
        ("eval pytest", None), ("source ./env", None), (". ./env", None),
        ("$RUNNER test", None), ("`which pytest`", None), ("(subshell)", None),
        ("{brace}", None), ("a|b", None), ("a;b", None), ("a>b", None),
        ("a&b", None), ("a*b", None), ("a?b", None),
        ("cd app", "cd"), ("cd", "cd"), ("env", None), ("env FOO=1", None),
    )
    wrong = [(cmd, want, M._leading_executable(cmd))
             for cmd, want in GRID if M._leading_executable(cmd) != want]
    check("dp1 the whole `_leading_executable` grid, %d commands, compared as a "
          "LIST rather than one assertion per shape - a version that resolves "
          "one prefix and drops another cannot pass this: %r"
          % (len(GRID), wrong), wrong == [])
    check("dp2 `cd app` with no `&&` resolves to `cd` and NOT to None. The "
          "other-direction case for the `cd`-stripping loop: a version that "
          "stripped unconditionally would return None here and quietly stop "
          "checking every runner behind a bare cd: %r"
          % (M._leading_executable("cd app"),),
          M._leading_executable("cd app") == "cd")
    check("dp3 an env-assignment prefix with a SLASH in the name is not an "
          "assignment - `a/b=c pytest` runs `a/b=c`, and the exclusion is what "
          "keeps a path from being eaten as a variable: %r"
          % (M._leading_executable("a/b=c pytest"),),
          M._leading_executable("a/b=c pytest") == "a/b=c")

    # ------------------------------------------------- check_build_commands
    def build(cmds, which=None):
        mf = _manifest()
        if cmds is not None:
            mf["meta"]["buildCommands"] = cmds
        rep = base.Report()
        saved = shutil.which
        if which is not None:
            shutil.which = which
        try:
            M.check_build_commands(rep, "/nowhere", mf)
        finally:
            shutil.which = saved
        return rep

    present = lambda name, *a, **k: "/usr/bin/" + name          # noqa: E731
    absent = lambda name, *a, **k: None                         # noqa: E731

    rep = build(None)
    check("dp4 no buildCommands at all is a WARNING that names the consequence: "
          "testGateGreen would pass vacuously: %r"
          % (_detail(rep, "buildCommands"),),
          _levels(rep, "buildCommands") == ["WARNING"]
          and "vacuously" in _detail(rep, "buildCommands"))
    check("dp5 ...and an EMPTY object says the same thing, rather than reading "
          "as 'all 0 runners found'. A filter that narrows to nothing must not "
          "report an all-clear",
          "vacuously" in _detail(build({}), "buildCommands"))

    rep = build({"test": "pytest", "lint": "ruff"}, which=present)
    check("dp6 every runner resolving is an ok line COUNTING them: %r"
          % (_detail(rep, "buildCommands"),),
          _levels(rep, "buildCommands") == ["OK"]
          and "all 2 resolvable runner(s)" in _detail(rep, "buildCommands"))

    rep = build({"test": "pytest"}, which=absent)
    check("dp7 a runner not installed here is a WARNING, never a FINDING: it is "
          "a gap in THIS MACHINE, and calling it repo-broken failed CI's "
          "manifest job over a correct observation: %r"
          % (_detail(rep, "buildCommands"),),
          _levels(rep, "buildCommands") == ["WARNING"]
          and "test (pytest)" in _detail(rep, "buildCommands"))

    rep = build({"test": "for f in *; do x; done"}, which=present)
    check("dp8 a shell construct is reported as NOT CHECKED - saying so is the "
          "honest answer, and guessing produced a false FINDING on this repo's "
          "own for-loop: %r" % (_detail(rep, "buildCommands"),),
          "not checked" in _detail(rep, "buildCommands"))
    check("dp9 ...and the unresolvable one is excluded from the count of what "
          "WAS checked, so `all N found` never claims a command it skipped: %r"
          % (_detail(build({"test": "pytest", "lint": "if x; then y; fi"},
                           which=present), "buildCommands"),),
          "all 1 resolvable runner(s)" in _detail(
              build({"test": "pytest", "lint": "if x; then y; fi"},
                    which=present), "buildCommands"))

    # dp10 REVERSED on purpose (F-P-28). It used to pin SILENCE here, on the
    # argument that an ok line would be "a claim about a document that is not
    # there". That conflated two different things: not claiming the manifest is
    # fine, and saying nothing at all. Every neighbour in this report names an
    # absent basis - `ado` reports an unconfigured connector, `journal` reports no
    # writes, `config` reports defaults active - and the row that vanished was read
    # as "checked, nothing to say" by a reader whose repo carried three plausible
    # runners. The house rule decides it: when the basis is missing, that is the
    # thing to say.
    rep = base.Report()
    M.check_build_commands(rep, "/nowhere", None)
    check("dp10 no manifest NAMES the absent basis instead of vanishing - a row "
          "that disappears reads as a row that passed",
          len(rep.rows) == 1 and "no manifest yet" in _detail(rep, "buildCommands"))
    check("dp10b ...and says what will supply it, so the reader knows where to "
          "look rather than that something is missing",
          "meta.buildCommands" in _detail(rep, "buildCommands"))

    # ------------------------------------------------------------ check_areas
    tmp = tempfile.mkdtemp(prefix="doctor-policy-")
    try:
        os.makedirs(os.path.join(tmp, "server"))
        os.makedirs(os.path.join(tmp, "web"))
        mrel = "docs/audit/audit-plan.json"

        def areas(reg, tags, cfg=None):
            mf = _manifest()
            mf["meta"]["areas"] = reg
            for i, tag in enumerate(tags):
                if tag is not None:
                    mf["phases"][i]["area"] = tag
            rep = base.Report()
            M.check_areas(rep, tmp, cfg or {}, mf, mrel)
            return rep

        rep = base.Report()
        M.check_areas(rep, tmp, {}, _manifest(), mrel)
        check("dp11 a manifest that registers NO areas is silent. Free-text "
              "tagging is still the normal case, and a doctor that nagged every "
              "single-app repo about a monorepo registry would be one people "
              "stop running", rep.rows == [])

        rep = areas({"be": {"root": "server"}}, ["be"])
        check("dp12 a registry whose roots all resolve is one ok line counting "
              "areas AND tags: %r" % (_detail(rep, "areas"),),
              _levels(rep, "areas") == ["OK"]
              and "1 area(s) registered, 1 phase tag(s)" in _detail(rep, "areas"))

        rep = areas({"be": {"root": "nowhere"}}, ["be"])
        check("dp13 a root that is not there is a WARNING naming the pair, and "
              "the fix says roots are project-relative like task.files: %r"
              % (_detail(rep, "areas"),),
              _levels(rep, "areas") == ["WARNING"]
              and "be -> nowhere" in _detail(rep, "areas"))

        rep = areas({"be": {"root": "server"}}, ["ghost"])
        check("dp14 a phase tag with no registry entry is its OWN warning, and "
              "the all-clear line does not print beside it. The fixture has no "
              "missing root at all, so a version testing only `not missing` "
              "would emit both: %r" % (_levels(rep, "areas"),),
              _levels(rep, "areas") == ["WARNING"]
              and "P1 uses 'ghost'" in _detail(rep, "areas"))

        # The owner-vs-ledger join: heavily gated, and every gate is a case.
        ul = _loader.load_script("usage_ledger.py", modname="dp_ledger")
        ledger = os.path.join(tmp, ".claude", "usage")
        os.makedirs(os.path.join(tmp, "docs", "audit"))

        reg = {"be": {"root": "server", "owner": "seen@example.com"},
               "fe": {"root": "web", "owner": "never@example.com"}}
        rep = areas(reg, ["be"])
        check("dp15 with NO ledger on disk the owner question is not asked. A "
              "validator that warned here would false-alarm on every "
              "pre-first-run repo and every new team member: %r"
              % (_detail(rep, "areas"),),
              "never appear in the ledger" not in _detail(rep, "areas"))

        ul.ensure_ledger_dir(ledger)
        ul.append_rows(ledger, [{"ts": "2026-01-01T00:00:00Z",
                                 "author": "seen@example.com",
                                 "taskId": "P1.1", "model": "m",
                                 "inputTokens": 1, "outputTokens": 1}])
        rep = areas(reg, ["be"])
        check("dp16 ...and with rows in it, the owner nobody has ever matched is "
              "a WARNING while the one that matched is not. The fixture carries "
              "one of each, so a version comparing the sets the other way round "
              "names the wrong person: %r" % (_detail(rep, "areas"),),
              "never@example.com" in _detail(rep, "areas")
              and "seen@example.com" not in _detail(rep, "areas"))

        rep = areas(reg, ["be"], cfg={"usage": {"authorMode": "hash"}})
        check("dp17 ...and under `authorMode: hash` it is not asked at all - an "
              "owner cannot be written as a hash, so the join could only ever "
              "produce a false accusation: %r" % (_detail(rep, "areas"),),
              "never appear in the ledger" not in _detail(rep, "areas"))

        # ----------------------------------------------------- check_policy
        cfgmod = _loader.load_hooks_config()

        INV = {"skills": [{"name": "writing-python"}, {"name": "code-review"}],
               "agents": [{"name": "reviewer"}], "mcp": ["github"]}

        def policy(block, inventory=INV, mf=None):
            cfg = {"policy": block} if block is not None else {}
            rep = base.Report()
            M.check_policy(rep, tmp, cfg, cfgmod, mf,
                           _discover=(lambda _p: inventory))
            return rep

        rep = policy(None)
        check("dp18 no policy is INERT, and the row says what that means rather "
              "than staying silent: %r" % (_detail(rep, "policy"),),
              _levels(rep, "policy") == ["OK"]
              and "inert" in _detail(rep, "policy"))
        rep = policy({"enabled": False})
        check("dp19 ...and `enabled: false` says so IN the row, so 'inert' and "
              "'switched off' are not the same sentence: %r"
              % (_detail(rep, "policy"),),
              "policy.enabled is false" in _detail(rep, "policy"))
        rep = policy({"enabled": True, "skills": {"allow": ["writing-python"]}})
        check("dp20 an allow-only policy is inert too - allow lists cannot deny, "
              "so there is no verdict to make: %r" % (_detail(rep, "policy"),),
              "inert" in _detail(rep, "policy"))

        active = {"enabled": True, "onViolation": "deny",
                  "skills": {"default": "deny", "allow": ["writing-python",
                                                          "code-review"]}}
        rep = policy(active)
        check("dp21 an active policy with no guard marker WARNS that it is "
              "advisory, and cites the Claude Code issue rather than implying "
              "enforcement nobody has: %r" % (_detail(rep, "policy"),),
              _levels(rep, "policy") == ["WARNING"]
              and "43772" in _detail(rep, "policy"))

        dead = {"enabled": True, "onViolation": "warn",
                "skills": {"default": "deny",
                           "allow": ["nope-a", "nope-b", "nope-c", "nope-d"]}}
        rep = policy(dead)
        # F205, ON THE SURFACE THAT PINNED THE DEFECT. This asserted that four
        # dead patterns were counted and THREE were named, so the truncation had
        # a case defending it - which is how a count that was always right kept
        # a basis that did not support it. Counted rather than found, because a
        # renderer naming one pattern twice would satisfy a presence assertion,
        # and the LAST name is asserted by itself: it is the one the old slice
        # dropped, and a version that shows a bounded prefix passes every
        # assertion above this line.
        check("dp22 patterns matching nothing installed here are counted AND "
              "named in full - the number and the list are the same set, so the "
              "reader can act on the last of them: %r"
              % (_detail(rep, "policy"),),
              "4 pattern(s) match nothing installed here" in _detail(rep, "policy")
              and _detail(rep, "policy").count("policy.skills.allow") == 4
              and "nope-d" in _detail(rep, "policy"))

        rep = policy(dead, inventory={"skills": [], "agents": [], "mcp": []})
        check("dp23 ...and an inventory that found NOTHING AT ALL says nothing. "
              "A working scan always sees audit's own plugin tree, so an empty "
              "one means the scanner is broken, and warning about every pattern "
              "would be noise about the scan rather than about the policy: %r"
              % (_detail(rep, "policy"),),
              "match nothing installed" not in _detail(rep, "policy"))

        rep = base.Report()
        M.check_policy(rep, tmp, {"policy": dead}, cfgmod, None,
                       _discover=lambda _p: (_ for _ in ()).throw(OSError("x")))
        check("dp24 ...and a scan that RAISES says nothing either - fail-open "
              "twice over, because a broken scan is not evidence about the "
              "policy: %r" % (_detail(rep, "policy"),),
              "match nothing installed" not in _detail(rep, "policy"))

        refuse = {"enabled": True, "onViolation": "deny",
                  "skills": {"deny": ["code-review"]}}
        mf = _manifest()
        mf["meta"]["reviewSkill"] = "code-review"
        rep = policy(refuse, mf=mf)
        check("dp25 a review skill the policy would refuse is named with the "
              "BASIS that refuses it - it fails at phase sign-off otherwise, "
              "which is the worst possible moment: %r" % (_detail(rep, "policy"),),
              "P1 review skill 'code-review'" in _detail(rep, "policy")
              and "policy.skills.deny" in _detail(rep, "policy"))

        mf2 = _manifest()
        mf2["meta"]["reviewSkill"] = "writing-python"
        rep = policy(refuse, mf=mf2)
        check("dp26 ...and a plan asking for nothing denied draws no such row. "
              "THE OTHER-DIRECTION CASE: the same policy, a different plan, so "
              "only an unconditional version passes both: %r"
              % (_detail(rep, "policy"),),
              "would be refused" not in _detail(rep, "policy"))

        # --- F195: the skills the plan NAMES, against this machine -------------
        # `check_build_commands` already grades this class one dependency over -
        # "runner not on PATH here ... that gate cannot run on this machine". A
        # gate whose runner is absent and a reviewer whose skill is absent are the
        # same shape, and one of them got silence. Measured live on a manifest
        # naming a hand-placed SKILL.md that exists in no marketplace.
        # Entries carry a portability verdict now, and a fixture that omits it is
        # the honest shape for "this machine could not say" - so the F195 cases
        # below stay about resolution alone, and the ones after them supply a
        # verdict on purpose.
        def _skills(mf, inv, cfg=None):
            r = base.Report()
            M.check_plan_skills(r, tmp, cfg or {}, cfgmod, mf,
                                _discover=lambda _p, home=None: inv)
            return r

        def _travels(name, travels, basis="because"):
            return {"name": name, "travels": travels, "travelsBasis": basis}
        mfs = _manifest()
        mfs["meta"]["reviewSkill"] = "code-review-and-quality"
        rep = _skills(mfs, {"skills": [{"name": "writing-python"}]})
        check("dp27 a skill the plan names and this machine cannot find is "
              "WARNED about, naming the skill AND where the plan names it - a "
              "review skill that does not resolve means sign-off runs with no "
              "reviewer: %r" % (_detail(rep, "skills"),),
              "'code-review-and-quality'" in _detail(rep, "skills")
              and "P1 review skill" in _detail(rep, "skills")
              # F233: this read `!= "finding"` and could not fail. `Report.finding`
              # writes "FINDING", so the comparison was true of every row it would
              # ever see, and the half of dp27 that names the TIER was asserting
              # nothing for as long as the case had existed.
              and "FINDING" not in _levels(rep, "skills"))
        rep = _skills(mfs, {"skills": [{"name": "writing-python"},
                                       {"name": "code-review-and-quality"}]})
        check("dp28 ...and a plan whose every name resolves says so instead. THE "
              "OTHER DIRECTION: the same plan, a different machine, so an "
              "unconditional row fails one of the two: %r"
              % (_detail(rep, "skills"),),
              "not resolvable here" not in _detail(rep, "skills")
              and "resolve on this machine" in _detail(rep, "skills"))
        # A SCAN THAT CANNOT ANSWER MUST NOT READ AS AGREEMENT. Two ways it fails
        # and both are said, because "every skill resolves" over a broken scan is
        # exactly the claim-without-a-basis this repo's rule forbids.
        rep = _skills(mfs, {"skills": []})
        check("dp29 an EMPTY inventory is reported as unknown, never as clean - a "
              "working scan always sees audit's own skills, so empty means the "
              "scanner is broken: %r" % (_detail(rep, "skills"),),
              "UNKNOWN" in _detail(rep, "skills")
              and "resolve on this machine" not in _detail(rep, "skills"))
        rep = base.Report()
        M.check_plan_skills(
            rep, tmp, {}, cfgmod, mfs,
            _discover=lambda _p, home=None: (_ for _ in ()).throw(OSError("x")))
        check("dp30 ...and a scan that RAISES says the same thing rather than "
              "nothing: silence here would be indistinguishable from a plan that "
              "names no skills: %r" % (_detail(rep, "skills"),),
              "UNKNOWN" in _detail(rep, "skills"))
        # One row per NAME, not per reference: a review skill inherited by every
        # phase is one thing to install.
        mfd = _manifest()
        mfd["meta"]["reviewSkill"] = "ghost"
        mfd["phases"].append({"id": "P2", "title": "two", "status": "pending",
                              "tasks": [], "blockedBy": [], "testGate": []})
        rep = _skills(mfd, {"skills": [{"name": "writing-python"}]})
        check("dp31 a name the whole plan inherits is reported ONCE, not once per "
              "phase - nineteen identical lines is the wall `_warning_groups` "
              "exists to stop: %r" % (_detail(rep, "skills"),),
              _detail(rep, "skills").count("'ghost'") == 1)

        # --- would it survive a CLONE? the half "resolves here" cannot see ------
        # The row above is answered on the authoring machine, where every name
        # resolves - which is why it went green over a plan a teammate could not
        # run. `_panel_discovery` decides; this only words it, so every fixture
        # here states a verdict rather than a tree.
        _PORT = "plan portability"
        mfp = _manifest()
        mfp["meta"]["reviewSkill"] = "personal-skill"
        rep = _skills(mfp, {"skills": [
            _travels("personal-skill", False,
                     "lives in a home directory, which no clone carries")]})
        check("dp32 a name that resolves HERE and would not survive a clone is "
              "warned about, naming the skill, where the plan names it, and the "
              "basis - and never as a finding, because a solo plan nobody will "
              "clone is entitled to it: %r" % (_detail(rep, _PORT),),
              "'personal-skill'" in _detail(rep, _PORT)
              and "P1 review skill" in _detail(rep, _PORT)
              and "home directory" in _detail(rep, _PORT)
              and "FINDING" not in _levels(rep, _PORT))
        rep = _skills(mfp, {"skills": [
            _travels("personal-skill", True, "committed under .claude/")]})
        # THE SECOND-DIRECTION CASE, and the one that looks vacuous: a plan whose
        # every name travels must draw NO such warning. An unconditional row -
        # the natural way to get dp32 green - fails exactly here.
        check("dp33 ...and a plan whose every name would survive a clone says so "
              "instead, drawing no warning at all: %r" % (_detail(rep, _PORT),),
              "will NOT survive" not in _detail(rep, _PORT)
              and "would survive a clone" in _detail(rep, _PORT)
              and _levels(rep, _PORT) == ["OK"])
        rep = _skills(mfp, {"skills": [
            _travels("personal-skill", False,
                     "enabledPlugins names p@m but extraKnownMarketplaces does "
                     "not carry 'm'")]})
        check("dp34 the BASIS is carried through rather than restated - here the "
              "half-declared plugin, whose repair is one named key: %r"
              % (_detail(rep, _PORT),),
              "extraKnownMarketplaces" in _detail(rep, _PORT))
        rep = _skills(mfp, {"skills": [
            _travels("personal-skill", False,
                     "extraKnownMarketplaces carries 'm' but enabledPlugins "
                     "names no plugin of it")]})
        # THE TWIN OF dp34. A doctor that wrote its own message instead of
        # rendering the basis passes one of this pair and fails the other,
        # whichever key it happened to hard-code.
        check("dp35 ...and the OTHER half-declaration reaches the reader naming "
              "the other key: %r" % (_detail(rep, _PORT),),
              "enabledPlugins" in _detail(rep, _PORT)
              and "extraKnownMarketplaces" in _detail(rep, _PORT))
        rep = _skills(mfp, {"skills": [
            _travels("personal-skill", None,
                     "the committed .claude/settings.json could not be read")]})
        check("dp36 an UNANSWERED verdict is said as unknown and never folded "
              "into 'will not travel' - an unreadable settings file is not "
              "evidence about a plugin: %r" % (_detail(rep, _PORT),),
              "UNKNOWN" in _detail(rep, _PORT)
              and "OK" not in _levels(rep, _PORT))
        mfg = _manifest()
        mfg["meta"]["reviewSkill"] = "nowhere-at-all"
        rep = _skills(mfg, {"skills": [_travels("something-else", True)]})
        # NARROWED TO NOTHING IS NOT CLEAN. Every name failed to resolve, so the
        # graded set is empty - and `if not stranded: ok(...)` would report a
        # perfect result over a set it never looked at.
        check("dp37 when NOTHING resolved there is nothing to grade, and that is "
              "reported as unknown rather than as an all-clear: %r"
              % (_detail(rep, _PORT),),
              "UNKNOWN" in _detail(rep, _PORT)
              and "OK" not in _levels(rep, _PORT))
        _stranded = {"skills": [_travels("personal-skill", False, "home dir")]}
        rep_off = _skills(mfp, _stranded, {"portability": "off"})
        check("dp38 'off' does not go quiet - it SAYS it did not grade, because "
              "silence and 'checked, all fine' are indistinguishable to a reader: "
              "%r" % (_detail(rep_off, _PORT),),
              "not graded" in _detail(rep_off, _PORT)
              and "will NOT survive" not in _detail(rep_off, _PORT))
        rep_warn = _skills(mfp, _stranded, {"portability": "warn"})
        rep_strict = _skills(mfp, _stranded, {"portability": "strict"})
        # The doctor DIAGNOSES at every tier that is not off; only the panel and
        # the gate act on the difference. Binding this row to strict would make
        # 'warn' mean nothing at all, which is the mutation this kills.
        check("dp39 'warn' and 'strict' draw the SAME warning - the tier decides "
              "what is refused elsewhere, not what is observed here",
              "will NOT survive" in _detail(rep_warn, _PORT)
              and "will NOT survive" in _detail(rep_strict, _PORT))
        check("dp40 ...and 'warn' says plainly that nothing is being refused, "
              "which 'strict' does not: %r"
              % (_detail(rep_warn, _PORT),),
              "nothing is being refused" in _fix(rep_warn, _PORT)
              and "nothing is being refused" not in _fix(rep_strict, _PORT))
        rep = _skills(mfp, _stranded, {"portability": "bogus"})
        check("dp41 a tier outside the enum is treated as unset and falls back to "
              "what the plugin ships, rather than switching the check off - the "
              "validator already refuses the value, and a typo must not be the "
              "quiet way to disable this",
              "will NOT survive" in _detail(rep, _PORT))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_policy.py --selftest\n")
    raise SystemExit(2)
