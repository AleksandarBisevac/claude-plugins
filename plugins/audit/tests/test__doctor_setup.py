#!/usr/bin/env python3
"""
The cases for `_doctor_setup.py` — the six checks everything else stands on.

`check_interpreter` is driven through a `shutil.which` seam rather than the
machine's real PATH, and that is not tidiness: the launcher tries three names
in ORDER, this machine carries one of them, and a suite that asked the real
PATH could not tell `found[0]` from `found[-1]` at all. The same reasoning runs
through the rest — every case here picks fixture values the two implementations
would disagree about.

The `git`-dependent cases are SKIPPED rather than failed when git is not on
PATH, the same rule `test_audit_doctor.py` follows: "git root resolves" going
red because git is not installed reports the wrong defect.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _doctor_setup as M                          # noqa: E402
import _doctor_report as base                      # noqa: E402  (the collector)


def _levels(rep, name):
    return [r["level"] for r in rep.rows if r["check"] == name]


def _detail(rep, name):
    return " ".join(r["detail"] for r in rep.rows if r["check"] == name)


def _manifest(**over):
    doc = {
        "meta": {"version": 2, "title": "t"},
        "phases": [{"id": "P1", "title": "one", "status": "done",
                    "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                               "files": ["a.py"], "tests": {"mode": "regression"},
                               "risk": "low"}]}],
        "bugs": [], "fileIndex": {"a.py": ["P1.1"]},
    }
    doc.update(over)
    return doc


# --- cases --------------------------------------------------------------------
def _cases(check):
    import tempfile

    # ------------------------------------------------------- check_interpreter
    def interp_rep(present):
        rep = base.Report()
        saved = shutil.which

        def fake(name, *a, **k):
            return ("/usr/bin/" + name) if name in present else None
        shutil.which = fake
        try:
            M.check_interpreter(rep)
        finally:
            shutil.which = saved
        return rep

    rep = interp_rep(())
    check("ds1 no interpreter on PATH is a FINDING, because every guard hook "
          "then falls back to a manual-approval prompt and enforces nothing: %r"
          % (_detail(rep, "interpreter"),),
          _levels(rep, "interpreter") == ["FINDING"]
          and "enforces nothing" in _detail(rep, "interpreter"))
    check("ds1b ...and it lists the three names it LOOKED FOR, not the empty "
          "list of what it found. Every claim carries its basis, and 'none of "
          "  is on PATH' is a sentence with the basis deleted: %r"
          % (_detail(rep, "interpreter"),),
          "none of python3, python, py is on PATH"
          in _detail(rep, "interpreter"))

    rep = interp_rep(("python", "py"))
    check("ds2 the FIRST name that resolves is the one reported, not the last. "
          "The fixture deliberately omits python3, so `found[0]` and `found[-1]` "
          "give different answers - with all three present they would not: %r"
          % (_detail(rep, "interpreter"),),
          "will use python " in _detail(rep, "interpreter"))
    check("ds3 ...and the row still lists every candidate it saw, so the line "
          "carries the basis and not only the verdict: %r"
          % (_detail(rep, "interpreter"),),
          "python, py" in _detail(rep, "interpreter"))

    rep = interp_rep(("python3", "python", "py"))
    check("ds4 with all three present the answer is python3 - the launcher's own "
          "order, not PATH order", "will use python3 " in _detail(rep, "interpreter"))

    # ---------------------------------------------------------- check_sandbox
    # P0-S. The plugin's secret guards match the TEXT of a tool call and never
    # observe I/O; what actually contains a read is the harness sandbox plus the
    # permission deny rules. Neither is this plugin's, and until now neither was
    # checked - so a repo could run with both off, every guard green, and nothing
    # saying so. A live session did exactly that.
    #
    # THE FIXTURES PIN A THREE-VALUED ANSWER, which is the whole point: "declared
    # false", "declared true" and "nobody declared it" are three different facts,
    # and collapsing the third into the first would make this check assert
    # something it cannot observe. Managed policy and a `--settings` flag outrank
    # every file read here.
    def sandbox_rep(local=None, proj=None, user=None):
        box = tempfile.mkdtemp(prefix="doctor-sandbox-")
        home = os.path.join(box, "home")
        proj_dir = os.path.join(box, "proj")
        for base_dir, obj, name in (
                (proj_dir, local, "settings.local.json"),
                (proj_dir, proj, "settings.json"),
                (home, user, "settings.json")):
            if obj is None:
                continue
            os.makedirs(os.path.join(base_dir, ".claude"), exist_ok=True)
            with open(os.path.join(base_dir, ".claude", name), "w",
                      encoding="utf-8") as fh:
                fh.write(obj if isinstance(obj, str) else json.dumps(obj))
        rep = base.Report()
        M.check_sandbox(rep, proj_dir, home=home)
        shutil.rmtree(box, ignore_errors=True)
        return rep

    unattested = sandbox_rep()
    check("ds0a NO settings file at all: the sandbox is NOT ESTABLISHED, which "
          "is a warning and not a claim that it is off - no env var carries the "
          "state and a read-only doctor may not probe by writing: %r"
          % (_detail(unattested, "sandbox"),),
          _levels(unattested, "sandbox") == ["WARNING"]
          and "cannot be attested" in _detail(unattested, "sandbox"))
    check("ds0b ...and with NEITHER layer established the missing deny rule is a "
          "WARNING too, never a finding. A finding would assert the sandbox is "
          "ABSENT, and absence is the one thing this check cannot establish - "
          "managed policy and a --settings flag outrank every file it reads: %r"
          % (_detail(unattested, "secret rules"),),
          _levels(unattested, "secret rules") == ["WARNING"]
          and "could not be established" in _detail(unattested, "secret rules"))
    check("ds0b2 ...and the two warnings are not one generic line printed twice: "
          "each names ITS OWN layer, and they carry different bases - the "
          "deny-rule row says what it looked for and did not find, the sandbox "
          "row says it could not look at all: %r / %r"
          % (_detail(unattested, "sandbox"), _detail(unattested, "secret rules")),
          _detail(unattested, "sandbox") != _detail(unattested, "secret rules")
          and "no permission deny rule" in _detail(unattested, "secret rules")
          and "no permission deny rule" not in _detail(unattested, "sandbox")
          and "declares `sandbox`" in _detail(unattested, "sandbox"))

    # ds0c/ds0c2/ds0c3 ARE THE SECOND-DIRECTION CASES for ds0b, and they are the
    # reason ds0b could be softened at all: collapse the graded branch into one
    # unconditional warning and ds0b stays green forever while these go red. An
    # explicitly disabled sandbox IS established - by the file that says so - so
    # it keeps the finding and keeps failing the doctor.
    off = sandbox_rep(proj={"sandbox": {"enabled": False}})
    check("ds0c sandbox.enabled FALSE is a FINDING - broken now, not later, and "
          "read from a file rather than inferred from silence: %r"
          % (_detail(off, "sandbox"),),
          _levels(off, "sandbox") == ["FINDING"]
          and "project settings" in _detail(off, "sandbox"))
    check("ds0c2 ...and the missing deny rule BESIDE a disabled sandbox is a "
          "FINDING as well, naming the file that establishes it: both halves "
          "are observed, so neither is a claim without a basis: %r"
          % (_detail(off, "secret rules"),),
          _levels(off, "secret rules") == ["FINDING"]
          and "is false in project settings" in _detail(off, "secret rules"))
    check("ds0c3 ...so the two states diverge at the EXIT CODE, which is the "
          "user-visible half: a setup that cannot be attested does not fail the "
          "doctor, an explicitly disabled sandbox does. Asserted as one pair, "
          "because either half alone is green on a wrong implementation: %r vs %r"
          % (unattested.exit_code(), off.exit_code()),
          unattested.exit_code() == 0 and off.exit_code() == 1)

    # ds0d IS THE SECOND-DIRECTION MUTATION for ds0a/ds0c and it looks vacuous:
    # a check that reported "no sandbox" unconditionally passes ds0a and ds0c
    # forever and fails only here. It is also the case that fails if the
    # three-valued read is collapsed to a truthiness test, since `enabled: true`
    # and "no sandbox key" are both non-False.
    rep = sandbox_rep(proj={"sandbox": {"enabled": True},
                            "permissions": {"deny": ["Read(.env*)"]}})
    check("ds0d a declared, enabled sandbox with a deny rule is two OK rows and "
          "no warning anywhere - the guard must be able to say 'this is fine'",
          _levels(rep, "sandbox") == ["OK"]
          and _levels(rep, "secret rules") == ["OK"]
          and "Read(.env*)" in _detail(rep, "secret rules"))

    rep = sandbox_rep(proj={"sandbox": {"enabled": True}})
    check("ds0e a working sandbox DOWNGRADES the missing rule to a warning - one "
          "layer is established, so this will bite later rather than now: %r"
          % (_detail(rep, "secret rules"),),
          _levels(rep, "secret rules") == ["WARNING"])

    # PRECEDENCE, and it is picked so the two implementations disagree: a scalar
    # does not merge, so the LOCAL file must win over the project one. Reading
    # the lowest-precedence file (or the first found in path order) reports the
    # opposite verdict here.
    rep = sandbox_rep(local={"sandbox": {"enabled": False}},
                      proj={"sandbox": {"enabled": True}})
    check("ds0f settings.local.json outranks settings.json for a scalar - the "
          "highest-precedence file that DEFINES the key decides: %r"
          % (_detail(rep, "sandbox"),),
          _levels(rep, "sandbox") == ["FINDING"]
          and "project local settings" in _detail(rep, "sandbox"))

    # ...and rule LISTS merge instead of overriding, so a rule in the user scope
    # counts even when a project file also defines `permissions`. The fixture
    # gives the project file a deny list that does NOT cover .env, so an
    # implementation that stopped at the first `permissions` block reports a
    # FINDING here.
    rep = sandbox_rep(proj={"permissions": {"deny": ["Bash(rm:*)"]}},
                      user={"permissions": {"deny": ["Read(.env*)"]}})
    check("ds0g deny LISTS merge across scopes - a user-scope rule still counts "
          "when a project file defines its own: %r"
          % (_detail(rep, "secret rules"),),
          _levels(rep, "secret rules") == ["OK"]
          and "Read(.env*)" in _detail(rep, "secret rules"))

    check("ds0h `Edit(.env*)` alone does NOT count - it refuses a write, and "
          "the leak this is about is a read",
          M.env_deny_rules([("project", {"permissions": {
              "deny": ["Edit(.env*)"]}})]) == []
          and M.env_deny_rules([("project", {"permissions": {
              "deny": ["Read(./.env)"]}})]) == ["Read(./.env)"])

    rep = sandbox_rep(proj="{not json")
    check("ds0i an UNPARSEABLE settings file is reported as unreadable, not "
          "silently skipped - the harness is not applying its rules either, and "
          "'no rule found' would name the wrong cause: %r"
          % (_detail(rep, "settings"),),
          _levels(rep, "settings") == ["WARNING"]
          and "not applying" in _detail(rep, "settings"))

    # -------------------------------------------------------------- check_git
    have_git = bool(shutil.which("git"))
    if not have_git:
        print("SKIP git-dependent cases (git is not on PATH)")
    tmp = tempfile.mkdtemp(prefix="doctor-setup-")
    try:
        if have_git:
            rep = base.Report()
            got = M.check_git(rep, tmp, {})
            check("ds5 a directory that is not a repository is a FINDING and the "
                  "fix names meta.gitRoot - every mutating /audit command stops "
                  "there: %r" % (_detail(rep, "git"),),
                  _levels(rep, "git") == ["FINDING"] and got is None)

            subprocess.run(["git", "init", "-q", tmp], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rep = base.Report()
            got = M.check_git(rep, tmp, {})
            check("ds6 ...and a real repository resolves, RETURNING the toplevel "
                  "so the four checks that need a git root take it as an "
                  "argument rather than re-deriving it: %r" % (got,),
                  _levels(rep, "git") == ["OK"] and got
                  and os.path.realpath(got) == os.path.realpath(tmp))

            rep = base.Report()
            got = M.check_git(rep, tmp, {"gitRoot": "nowhere"})
            check("ds7 `gitRoot` is honoured and judged: a config pointing at a "
                  "subdirectory that is not a repo is the finding, not the "
                  "project directory that IS one: %r" % (_detail(rep, "git"),),
                  _levels(rep, "git") == ["FINDING"] and got is None)

        # ----------------------------------------------------- check_config
        cfg_path = os.path.join(tmp, ".claude", "audit.config.json")
        os.makedirs(os.path.dirname(cfg_path))

        rep = base.Report()
        cfg, cfg_mod = M.check_config(rep, tmp)
        check("ds8 an ABSENT config is OK, never a warning: safe defaults are "
              "the normal case and a doctor that nagged every default setup is "
              "a doctor people stop running: %r" % (_detail(rep, "config"),),
              _levels(rep, "config") == ["OK"]
              and "safe defaults" in _detail(rep, "config"))
        check("ds9 ...and it still returns the (cfg, cfg_mod) pair the rest of "
              "the doctor is called with", isinstance(cfg, dict)
              and hasattr(cfg_mod, "DEFAULTS"))

        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        rep = base.Report()
        cfg, cfg_mod = M.check_config(rep, tmp)
        check("ds10 a PRESENT but unreadable config is a FINDING, and the detail "
              "says the project's own patterns are NOT applied - the failure "
              "mode is silent otherwise: %r" % (_detail(rep, "config"),),
              _levels(rep, "config") == ["FINDING"]
              and "NOT applied" in _detail(rep, "config"))

        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"stateDir": ".claude/state"}, fh)
        rep = base.Report()
        cfg, cfg_mod = M.check_config(rep, tmp)
        check("ds11 a valid config is one OK row and nothing else. THE "
              "OTHER-DIRECTION CASE: it goes red if the warning arm ever becomes "
              "unconditional: %r" % (_levels(rep, "config"),),
              _levels(rep, "config") == ["OK"])

        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"wibble": 1, "wobble": 2}, fh)
        rep = base.Report()
        cfg, cfg_mod = M.check_config(rep, tmp)
        check("ds12 ...while unknown keys are WARNINGS beside the OK, one row "
              "each: they are ignored by the orchestrator, not fatal to it: %r"
              % (_levels(rep, "config"),),
              _levels(rep, "config").count("WARNING") == 2
              and "OK" in _levels(rep, "config"))

        # -------------------------------------------------- check_plan_gate
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        cfg, cfg_mod = M.check_config(base.Report(), tmp)
        mrel = "docs/audit/audit-plan.json"
        mpath = os.path.join(tmp, mrel)
        os.makedirs(os.path.dirname(mpath))

        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds13 no manifest means the OBSERVE tier, and the row says how to "
              "get enforcement - the tier is the question people actually ask: "
              "%r" % (_detail(rep, "plan gate"),),
              _levels(rep, "plan gate") == ["OK"]
              and _detail(rep, "plan gate").startswith("observe"))

        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(_manifest(), fh)
        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds14 a manifest with no phase in_progress is WARN, not deny: %r"
              % (_detail(rep, "plan gate"),),
              _detail(rep, "plan gate").startswith("warn"))

        running = _manifest()
        running["phases"][0]["status"] = "in_progress"
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(running, fh)
        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds15 ...and a running phase is DENY: %r"
              % (_detail(rep, "plan gate"),),
              _detail(rep, "plan gate").startswith("deny"))

        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"planGate": "observe"}, fh)
        cfg, cfg_mod = M.check_config(base.Report(), tmp)
        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds16 `planGate: observe` PINNED over a running phase is the one "
              "setting that lowers the gate below what the evidence would "
              "enforce, so it is a WARNING and names itself as the reason: %r"
              % (_detail(rep, "plan gate"),),
              _levels(rep, "plan gate") == ["WARNING"]
              and "BELOW what the" in _detail(rep, "plan gate"))

        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(_manifest(), fh)
        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds17 ...and the SAME pin with no phase running is an ok line. THE "
              "OTHER-DIRECTION CASE: it is what fails if the warning drops its "
              "`phaseRunning` half and starts firing on every pinned observe: %r"
              % (_levels(rep, "plan gate"),),
              _levels(rep, "plan gate") == ["OK"]
              and "is pinned" in _detail(rep, "plan gate"))

        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"enforce": True}, fh)
        cfg, cfg_mod = M.check_config(base.Report(), tmp)
        rep = base.Report()
        M.check_plan_gate(rep, tmp, cfg, cfg_mod, mrel)
        check("ds18 the legacy `enforce: true` still reports deny, and says it "
              "is legacy: %r" % (_detail(rep, "plan gate"),),
              "deny" in _detail(rep, "plan gate")
              and "legacy" in _detail(rep, "plan gate"))

        # --------------------------------------------------- check_manifest
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        cfg, cfg_mod = M.check_config(base.Report(), tmp)

        rep = base.Report()
        rel, manifest = M.check_manifest(rep, tmp, cfg)
        check("ds19 a valid manifest counts phases and tasks THROUGH "
              "`iter_tasks` and returns the assembled document: %r"
              % (_detail(rep, "manifest"),),
              _levels(rep, "manifest") == ["OK"] and manifest is not None
              and "(1 phases, 1 tasks)" in _detail(rep, "manifest"))

        parked = _manifest()
        # TWO proposed against ONE materialized, deliberately: with one of each
        # the count is 1 whichever way the comparison is written, and the case
        # could not tell `== "proposed"` from `!= "proposed"` at all.
        parked["proposals"] = [
            {"id": "PROP-1", "name": "a", "status": "proposed",
             "payload": {"phase": {"id": "P9", "title": "p", "status": "pending",
                                   "tasks": []}}},
            {"id": "PROP-2", "name": "b", "status": "proposed",
             "payload": {"phase": {"id": "P8", "title": "q", "status": "pending",
                                   "tasks": []}}},
            {"id": "PROP-3", "name": "c", "status": "materialized",
             "payload": {"phase": {"id": "P7", "title": "r", "status": "pending",
                                   "tasks": []}}},
        ]
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(parked, fh)
        rep = base.Report()
        rel, manifest = M.check_manifest(rep, tmp, cfg)
        check("ds20 parked proposals are NAMED, because a park-all /audit:init "
              "leaves '0 phases, 0 tasks' and that reads as a dead plan. Two of "
              "the three are proposed and one is not, so the inverted "
              "comparison gives 1 where the right one gives 2: %r"
              % (_detail(rep, "manifest"),),
              "2 parked proposal(s)" in _detail(rep, "manifest"))

        # F14 said this next branch could never execute, on the reading that the
        # validator makes every out-of-vocabulary proposal status a finding — and
        # a finding takes the OTHER arm, so the count could not print. Measured:
        # false. `_check_proposals` skips an entry whose `payload` is not a dict
        # (`continue  # legacy free-form entry — tolerated as-is`) BEFORE it looks
        # at status, and those entries are exactly what reaches `n_legacy`. The
        # branch is live; nothing covered it, which is why it was the single miss
        # in 42 planted mutations. An undetectable mutation was the question, and
        # "the code is dead" was the wrong answer to it.
        legacy = _manifest()
        legacy["proposals"] = [
            {"id": "PROP-1", "status": "parked-old"},   # status outside the vocabulary
            {"id": "PROP-2"},                           # no status at all
            {"id": "PROP-3", "status": "proposed",
             "payload": {"phase": {"id": "P9", "title": "s", "status": "pending",
                                   "tasks": []}}},
        ]
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(legacy, fh)
        rep = base.Report()
        rel, manifest = M.check_manifest(rep, tmp, cfg)
        check("ds20b legacy free-form proposals are counted and NAMED - two of "
              "the three carry no vocabulary status and the payload-bearing one "
              "does, so the line has to say 1 parked and 2 legacy: %r"
              % (_detail(rep, "manifest"),),
              "1 parked proposal(s)" in _detail(rep, "manifest")
              and "2 legacy proposal(s)" in _detail(rep, "manifest"))
        _mrows = [r for r in rep.rows if r["check"] == "manifest"]
        check("ds20c ...and it prints from the VALID arm, which is the half F14 "
              "believed impossible - a legacy entry is tolerated rather than a "
              "finding, so the manifest is valid and the count is reachable: %r"
              % ([r["level"] for r in _mrows],),
              any(r["level"] == "OK" and "valid" in r["detail"]
                  for r in _mrows))

        broken = _manifest()
        broken["meta"].pop("version")
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(broken, fh)
        rep = base.Report()
        rel, manifest = M.check_manifest(rep, tmp, cfg)
        check("ds21 validator findings are a FINDING here, counted and quoted: "
              "%r" % (_detail(rep, "manifest"),),
              _levels(rep, "manifest") == ["FINDING"]
              and "1 validator finding(s)" in _detail(rep, "manifest"))

        os.remove(mpath)
        rep = base.Report()
        rel, manifest = M.check_manifest(rep, tmp, cfg)
        check("ds22 an ABSENT manifest is a WARNING and returns None - the "
              "pipeline has nothing to run, which is not the same as broken: %r"
              % (_detail(rep, "manifest"),),
              _levels(rep, "manifest") == ["WARNING"] and manifest is None
              and rel == "docs/audit/audit-plan.json")

        # ---------------------------------------------------- _check_shards
        def shards(index, files):
            for name in os.listdir(os.path.dirname(mpath)):
                p = os.path.join(os.path.dirname(mpath), name)
                if os.path.isfile(p):
                    os.remove(p)
            with open(mpath, "w", encoding="utf-8") as fh:
                json.dump(index, fh)
            for name, body in files.items():
                with open(os.path.join(os.path.dirname(mpath), name), "w",
                          encoding="utf-8") as fh:
                    json.dump(body, fh)
            r = base.Report()
            M._check_shards(r, mpath, None)
            return r

        rep = shards({"meta": {"version": 2}, "phases": []}, {})
        check("ds23 a single-file layout is an ok line pointing at /audit:migrate "
              "- not a warning about a layout nobody asked for: %r"
              % (_detail(rep, "layout"),),
              _levels(rep, "layout") == ["OK"]
              and "single-file layout" in _detail(rep, "layout"))

        rep = shards({"meta": {"version": 3},
                      "phases": [{"id": "P1", "shard": "p1.json"}]},
                     {"p1.json": {"id": "P1", "tasks": []}})
        check("ds24 an intact sharded layout counts the shards that assemble: %r"
              % (_detail(rep, "layout"),),
              _levels(rep, "layout") == ["OK"]
              and "1 shards assemble" in _detail(rep, "layout"))

        rep = shards({"meta": {"version": 3},
                      "phases": [{"id": "P1", "shard": "p1.json"}]}, {})
        check("ds25 a shard file that is not there is a FINDING naming it under "
              "`missing`, with `mismatched: none` - the two halves are reported "
              "separately because they have different repairs: %r"
              % (_detail(rep, "layout"),),
              _levels(rep, "layout") == ["FINDING"]
              and "missing: p1.json" in _detail(rep, "layout")
              and "mismatched: none" in _detail(rep, "layout"))

        rep = shards({"meta": {"version": 3},
                      "phases": [{"id": "P1", "shard": "p1.json"}]},
                     {"p1.json": {"id": "PX", "tasks": []}})
        check("ds26 ...while a shard whose id disagrees with its stub is "
              "MISMATCHED, not missing: %r" % (_detail(rep, "layout"),),
              "missing: none" in _detail(rep, "layout")
              and "mismatched: p1.json" in _detail(rep, "layout"))

        rep = shards({"meta": {"version": 3}, "phases": [{"id": "P1"}]}, {})
        check("ds27 ...and a stub carrying NO shard ref is reported by phase id, "
              "which is the only name it has: %r" % (_detail(rep, "layout"),),
              "P1 has no shard ref" in _detail(rep, "layout"))

        # -------------------------------------------------- check_submodules
        if have_git:
            rep = base.Report()
            M.check_submodules(rep, tmp, {}, _manifest(), tmp)
            check("ds28 no .gitmodules is SILENCE, not an ok line: a repo with "
                  "no submodules has no submodule question to answer: %r"
                  % (rep.rows,), rep.rows == [])

            with open(os.path.join(tmp, ".gitmodules"), "w",
                      encoding="utf-8") as fh:
                fh.write("[submodule \"vendor\"]\n\tpath = vendor\n"
                         "\turl = https://x/y\n")
            rep = base.Report()
            M.check_submodules(rep, tmp, {}, _manifest(), tmp)
            check("ds29 ...and with one declared, a task file OUTSIDE it is an "
                  "ok line counting the submodules, never a finding: %r"
                  % (_detail(rep, "submodules"),),
                  _levels(rep, "submodules") == ["OK"]
                  and "1 submodule(s)" in _detail(rep, "submodules"))

            inside = _manifest()
            inside["phases"][0]["tasks"][0]["files"] = ["vendor/a.py"]
            inside["fileIndex"] = {"vendor/a.py": ["P1.1"]}
            rep = base.Report()
            M.check_submodules(rep, tmp, {}, inside, tmp)
            check("ds30 ...while a task file INSIDE one is a FINDING that names "
                  "the pair - the parent repo cannot stage it, and the phase "
                  "dies at commit time rather than before: %r"
                  % (_detail(rep, "submodules"),),
                  _levels(rep, "submodules") == ["FINDING"]
                  and "P1.1 -> vendor/a.py" in _detail(rep, "submodules"))

            rep = base.Report()
            M.check_submodules(rep, tmp, {}, inside, None)
            check("ds31 ...and with no git root the check says NOTHING rather "
                  "than clearing the repo: an unanswerable question is not an "
                  "all-clear", rep.rows == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_setup.py --selftest\n")
    raise SystemExit(2)
