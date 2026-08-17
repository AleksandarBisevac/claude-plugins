#!/usr/bin/env python3
"""
The cases for `scripts/audit-doctor.py`, moved out of it - an entry point.

`audit-doctor.py` is hyphenated, so it comes through `_loader.load_script` and
the test file substitutes underscores; see `test_migrate_manifest.py` for both
halves of that rule. `M` is the module under test.

MOVED WHOLE, AND THAT IS A DECISION. 1,254 lines, 148 cases, and 53 of them call
`diagnose()` on ONE fixture directory that is mutated step by step - a config
written, a manifest broken, a lock aged, a journal row appended, a hook marker
touched - so each case asks what the doctor says about the repo AS IT NOW STANDS.
Only two cases call a check function directly (`check_policy`, `check_ado`). It is
an integration suite, not 148 unit cases wearing one prefix, and splitting it or
re-shaping the cases would change WHAT is tested rather than where it lives. The
sequence, the fixture and the ordering are byte-identical to what
`audit-doctor.py` ran.

ONE `KNOWN_LAYER_DEBT` ENTRY RETIRED WITH THIS MOVE, AND ONLY ONE. `_deps` walks
the whole AST, selftest included, so a `_loader` load that only ever ran inside a
suite is a real edge in the product's graph until the suite moves. Measured by AST
rather than assumed, per call site: of `audit-doctor.py`'s six recorded L7 -> L7
edges, `gen-demo-manifest` had exactly ONE call site and it was inside
`_selftest` (the sharded-layout fixture), so that entry is deleted from
`_deps.KNOWN_LAYER_DEBT` - which drops from 18 entries to 17. The other five
(`audit-journal`, `audit-lock`, `audit-status`, `validate-config`,
`validate-manifest`) all keep at least one PRODUCTION call site and stay:
`audit-journal` is loaded by `check_journal`/`check_completions` at lines 943/959/
1033 as well as twice in the suite, `audit-lock` by `check_locks` at 1206 as well
as once in the suite, and `audit-status`/`validate-config`/`validate-manifest` are
production-only.

`_load(name, filename, directory=None)` STAYS IN THE PRODUCT. It has ~24 call
sites, three of which pass `_HOOKS`, and the checks themselves are its main
caller; only the five inside the suite came here, spelled `M._load` so they still
resolve off `audit-doctor.py`'s own `_HERE` rather than off `tests/`.

`_json_ok()` came with the suite. It sat below `_selftest` in the same file and had
exactly one caller, the `CLI --json emits parseable JSON` case.

NOTHING ELSE HAD TO CHANGE MEANING. No `globals()`, no `vars()`, no `__file__`, no
`dirname(dirname(...))` and no `split(a)[1].split(b)[0]` anywhere in the block. The
fixtures are real directories under `tempfile.mkdtemp(prefix="audit-doctor-
selftest-")`, removed in a `finally`, and the git-dependent cases are skipped
(loudly, with a printed SKIP line) when git is not on PATH.

THE TALLY LINE CHANGES, AND IT IS A FIX. This suite printed `audit-doctor: N/M
cases passed` whether it passed or failed - one of the nine files the harness
docstring calls a DEFECT rather than a style variant, because the only thing
telling a reader which happened was the two numbers being equal. It prints
`ALL PASS` / `SELFTEST FAILED` now.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import json
import os
import shutil                                      # the `ado` group patches
#                                                  `shutil.which` - see below
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _cli_fmt                                    # noqa: E402  (as audit-doctor imports it)

M = _loader.load_script("audit-doctor.py", modname="audit_doctor")


# --- the one helper that came with the suite ----------------------------------
def _json_ok(project):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        M.main(["--project", project, "--json"])
    try:
        obj = json.loads(buf.getvalue())
        return isinstance(obj.get("checks"), list) and "counts" in obj
    except Exception:
        return False



# --- cases --------------------------------------------------------------------
def _cases(check):
    import shutil as sh
    import tempfile

    def levels(rep, name):
        return [r["level"] for r in rep.rows if r["check"] == name]

    def detail(rep, name):
        return " ".join(r["detail"] for r in rep.rows if r["check"] == name)

    # An empty directory: no config, no manifest, no state. Nothing is BROKEN, so
    # this must not report findings - a fresh repo is not a sick one.
    tmp = tempfile.mkdtemp(prefix="audit-doctor-selftest-")
    try:
        # A non-git directory is legitimately a FINDING (every mutating command
        # stops there), so the "fresh setup" case has to be a fresh REPO. If git is
        # not installed the repo cannot be made, and asserting "git root resolves"
        # would then fail for a reason that has nothing to do with this script —
        # so the git-dependent cases are skipped rather than reported as defects.
        have_git = bool(sh.which("git"))
        if have_git:
            try:
                subprocess.run(["git", "init", "-q", tmp],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30, check=True)
            except Exception:
                have_git = False
        if not have_git:
            print("SKIP git-dependent cases (git is not on PATH)")
        rep = M.diagnose(tmp)
        check("fresh repo: interpreter resolves", levels(rep, "interpreter") == ["OK"])
        check("fresh repo: absent config is OK, not a finding",
              levels(rep, "config") == ["OK"], repr(levels(rep, "config")))
        check("fresh repo: absent manifest is a WARNING, not a finding",
              levels(rep, "manifest") == ["WARNING"], repr(levels(rep, "manifest")))
        check("fresh repo: plan gate reports the observe tier",
              "observe" in detail(rep, "plan gate"), detail(rep, "plan gate"))
        hooks_fix = " ".join(r["fix"] or "" for r in rep.rows
                             if r["check"] == "hooks")
        check("fresh repo: no hook state is a WARNING",
              levels(rep, "hooks") == ["WARNING"], repr(levels(rep, "hooks")))
        check("the hooks warning names the likely cause (not enabled)",
              "enabled" in hooks_fix, hooks_fix)
        # F-E2: an absent ledger DIRECTORY used to read "<path> exists but
        # holds no rows yet" - a diagnostic asserting the existence of a
        # directory nothing ever created. Missing and empty are two branches.
        check("ledger: a missing directory reads 'no ledger yet' and names "
              "where it would live",
              "no ledger yet" in detail(rep, "usage ledger")
              and os.path.join(tmp, ".claude", "usage")
                  in detail(rep, "usage ledger"),
              detail(rep, "usage ledger"))
        check("ledger: ...and never claims the directory exists",
              "exists" not in detail(rep, "usage ledger"),
              detail(rep, "usage ledger"))
        os.makedirs(os.path.join(tmp, ".claude", "usage"))
        rep_led = M.diagnose(tmp)
        check("ledger: present but empty keeps the 'exists but holds no rows "
              "yet' wording",
              "exists but holds no rows yet" in detail(rep_led, "usage ledger"),
              detail(rep_led, "usage ledger"))
        sh.rmtree(os.path.join(tmp, ".claude", "usage"))

        # --- connector v2: the ADO card's operational half -------------------
        # check_ado is exercised directly, with shutil.which stubbed so the
        # verdicts do not depend on whether THIS machine has az installed.
        def _ado_rep(manifest, which):
            r = M.Report()
            _saved_which = shutil.which
            shutil.which = which
            try:
                M.check_ado(r, tmp, manifest)
            finally:
                shutil.which = _saved_which
            return r

        def _no_az(_name):
            return None

        r_a1 = _ado_rep({"meta": {}}, _no_az)
        check("ado: absent config is one OK row - not configured is not sick",
              levels(r_a1, "ado") == ["OK"]
              and "not configured" in detail(r_a1, "ado"), repr(r_a1.rows))
        r_a2 = _ado_rep({"meta": {"ado": {"organization": "o", "project": "p",
                                          "enabled": False}}}, _no_az)
        check("ado: enabled:false is a WARNING naming the freeze, never a "
              "finding",
              levels(r_a2, "ado") == ["WARNING"]
              and "DISABLED" in detail(r_a2, "ado"), repr(r_a2.rows))
        r_a3 = _ado_rep({"meta": {"ado": {"organization": "o",
                                          "project": "p"}}}, _no_az)
        check("ado: no stateMap draws the Scrum-vs-Agile advisory and says "
              "real states live in ADO",
              levels(r_a3, "ado state map") == ["WARNING"]
              and "Scrum" in detail(r_a3, "ado state map")
              and "real states live in ADO" in detail(r_a3, "ado state map"),
              repr(r_a3.rows))
        check("ado: a missing az is a WARNING with the install fix, not a "
              "finding - MCP transport may still carry a session",
              levels(r_a3, "ado transport") == ["WARNING"]
              and "az" in detail(r_a3, "ado transport"), repr(r_a3.rows))
        r_a4 = _ado_rep({"meta": {"ado": {"organization": "o", "project": "p",
                                          "stateMap": {"task":
                                                       {"done": "Done"}}}}},
                        _no_az)
        check("ado: a written stateMap silences the advisory",
              not [r for r in r_a4.rows if r["check"] == "ado state map"],
              repr(r_a4.rows))
        r_a5 = _ado_rep(
            {"meta": {"ado": {"organization": "o", "project": "p"}},
             "phases": [{"id": "P1",
                         "ado": {"id": 7,
                                 "lastSyncedAt": "2026-08-03T00:00:00Z"},
                         "tasks": [{"id": "P1.1", "ado": {"id": 8}}]}],
             "bugs": [{"id": "BUG-1", "ado": {"id": "x"}}]}, _no_az)
        check("ado: links count by kind with int ids only (junk skipped), and "
              "the newest sync stamp is named",
              "1 task" in detail(r_a5, "ado links")
              and "0 bug" in detail(r_a5, "ado links")
              and "1 phase" in detail(r_a5, "ado links")
              and "2026-08-03T00:00:00Z" in detail(r_a5, "ado links"),
              repr(r_a5.rows))
        check("ado: an unlinked config reads 'configuration, not evidence'",
              "configuration, not evidence" in detail(r_a3, "ado links"),
              repr(r_a3.rows))
        r_a6 = _ado_rep({"meta": {"ado": "org-as-string"}}, _no_az)
        check("ado: a shape defect adds NO ado rows - the validator already "
              "owns that finding",
              not [r for r in r_a6.rows if r["check"].startswith("ado")],
              repr(r_a6.rows))
        r_a7 = _ado_rep({"meta": {"ado": {"organization": "o", "project": "p",
                                          "onComplete": {"remainingWork": 0}}}},
                        _no_az)
        check("ado: a configured remainingWork draws the force-clear advisory "
              "(stock processes empty the field at done by themselves)",
              any("force-clear" in r["detail"] for r in r_a7.rows
                  if r["check"] == "ado remaining work"), repr(r_a7.rows))
        check("ado: ...and no remainingWork config draws no such row",
              not [r for r in r_a3.rows
                   if r["check"] == "ado remaining work"], repr(r_a3.rows))
        if have_git:
            check("fresh repo: a fresh setup yields no findings",
                  rep.counts()["FINDING"] == 0,
                  repr([r for r in rep.rows if r["level"] == "FINDING"]))
        if have_git:
            check("fresh repo: exit code 0", rep.exit_code() == 0)
        if have_git:
            # Locks. The case that used to be reported wrongly: a phase run that
            # has been going for 95 minutes is healthy, and calling it stale is
            # how the doctor talked a human into the takeover that loses work.
            lockmod = M._load("audit_lock", "audit-lock.py")
            ld = lockmod.lock_dir(tmp)
            os.makedirs(ld, exist_ok=True)
            old = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime(time.time() - 95 * 60))
            here = __import__("platform").node()
            lp = os.path.join(ld, "phase-P1.lock")

            def put(info):
                with open(lp, "w", encoding="utf-8") as fh:
                    json.dump(info, fh)

            put({"hostname": here, "pid": os.getpid(), "startedAt": old,
                 "note": "phase P1"})
            rep = M.diagnose(tmp)
            check("locks: a 95-min-old run with a live pid is OK, not stale",
                  levels(rep, "locks") == ["OK"], detail(rep, "locks"))
            check("locks: and the OK says how it knows",
                  "is running on this host" in detail(rep, "locks"),
                  detail(rep, "locks"))
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            put({"hostname": here, "pid": dead.pid,
                 "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "note": "phase P1"})
            rep = M.diagnose(tmp)
            check("locks: a 1-min-old run whose pid is gone is a WARNING",
                  levels(rep, "locks") == ["WARNING"], detail(rep, "locks"))
            check("locks: a dead holder is never a FINDING (nothing is broken)",
                  rep.counts()["FINDING"] == 0)
            os.unlink(lp)

        if have_git:
            check("fresh repo: git root resolves", levels(rep, "git") == ["OK"],
                  detail(rep, "git"))

        # a non-repo IS a finding, and it names the fix
        nogit = tempfile.mkdtemp(prefix="audit-doctor-nogit-")
        try:
            rep_ng = M.diagnose(nogit)
            check("a non-repo directory is a git FINDING",
                  levels(rep_ng, "git") == ["FINDING"], repr(levels(rep_ng, "git")))
            # Two different git findings with two different fixes: "not a repo"
            # points at meta.gitRoot, "git is not on PATH" points at installing it.
            # Asserting the first unconditionally made this case depend on the
            # machine rather than on the code.
            _gfix = " ".join(r["fix"] or "" for r in rep_ng.rows
                             if r["check"] == "git")
            _gdet = detail(rep_ng, "git")
            check("the git finding is actionable for the actual cause",
                  ("gitRoot" in _gfix) if have_git else ("not on PATH" in _gdet),
                  "%s | %s" % (_gdet, _gfix))
            check("a non-repo exits 1", rep_ng.exit_code() == 1)
        finally:
            sh.rmtree(nogit, ignore_errors=True)

        # malformed config
        os.makedirs(os.path.join(tmp, ".claude"), exist_ok=True)
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("{not json")
        rep = M.diagnose(tmp)
        check("malformed config is a FINDING", levels(rep, "config") == ["FINDING"])
        check("malformed config exits 1", rep.exit_code() == 1)

        # an invalid-but-parsing config value
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"enforce": "yes"}, fh)
        rep = M.diagnose(tmp)
        check("a config that parses but does not validate is a FINDING",
              levels(rep, "config") == ["FINDING"], detail(rep, "config"))

        # enforce:true is reported as deny even with no manifest
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"enforce": True, "manifestPath": "plan.json"}, fh)
        rep = M.diagnose(tmp)
        check("enforce:true is reported as the deny tier",
              "deny" in detail(rep, "plan gate"), detail(rep, "plan gate"))

        # a valid manifest at a custom path, with a running phase
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"test": "definitely-not-a-real-runner x"}},
                       "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                                   "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "pending"}]}]}, fh)
        rep = M.diagnose(tmp)
        check("a valid manifest at a custom path is OK",
              levels(rep, "manifest") == ["OK"], detail(rep, "manifest"))
        check("a running phase is reported as the deny tier",
              "deny" in detail(rep, "plan gate"), detail(rep, "plan gate"))
        check("a missing buildCommands runner is a WARNING, not a FINDING "
              "(the machine lacks a tool; the repo is not broken)",
              levels(rep, "buildCommands") == ["WARNING"],
              repr(levels(rep, "buildCommands")))
        check("a missing runner does not fail the exit code",
              rep.exit_code() == 0, repr(rep.counts()))
        check("the buildCommands warning names the runner",
              "definitely-not-a-real-runner" in detail(rep, "buildCommands"))

        # v0.34 B1: planGate pins a tier by hand; the doctor names the knob as
        # the fixed-mode source, and warns LOUDLY about the one setting that
        # lowers the gate below its evidence. plan.json still carries the
        # running phase here.
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json", "planGate": "ask"}, fh)
        rep = M.diagnose(tmp)
        check("a pinned planGate names the knob as the fixed-mode source",
              levels(rep, "plan gate") == ["OK"]
              and "planGate" in detail(rep, "plan gate")
              and "ask" in detail(rep, "plan gate"), detail(rep, "plan gate"))
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json", "planGate": "observe"}, fh)
        rep = M.diagnose(tmp)
        check("planGate:'observe' while a phase is RUNNING is a WARNING - the "
              "only setting that drops the gate below its evidence",
              levels(rep, "plan gate") == ["WARNING"]
              and "in_progress" in detail(rep, "plan gate"),
              detail(rep, "plan gate"))
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)

        # an invalid manifest
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "p", "status": "pending",
                 "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                            "blockedBy": ["NOPE"]}]}]}, fh)
        rep = M.diagnose(tmp)
        check("an invalid manifest is a FINDING",
              levels(rep, "manifest") == ["FINDING"], detail(rep, "manifest"))

        # buildCommands present and resolvable
        real = "python3" if sh.which("python3") else "python"
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"test": "%s -c pass" % real}},
                       "phases": [{"id": "P1", "title": "p", "status": "done",
                                   "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "done"}]}]}, fh)
        rep = M.diagnose(tmp)
        check("a resolvable buildCommands runner is OK",
              levels(rep, "buildCommands") == ["OK"], detail(rep, "buildCommands"))
        check("a `cd x && runner` form resolves the runner, not cd", True)
        check("no running phase is reported as the warn tier",
              "warn" in detail(rep, "plan gate"), detail(rep, "plan gate"))

        # `cd ... && runner` - the git-in-subdir shape
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "test": "cd app && %s -c pass" % real}},
                "phases": [{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done"}]}]}, fh)
        rep = M.diagnose(tmp)
        check("`cd x && runner` is resolved past the cd",
              levels(rep, "buildCommands") == ["OK"], detail(rep, "buildCommands"))

        # areas (v0.28). The registry describes the tree, and nothing inside the
        # manifest can tell that the tree moved.
        def with_areas(areas, tags):
            with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2, "areas": areas},
                           "phases": [{"id": "P1", "title": "p", "status": "done",
                                       "area": tags,
                                       "tasks": [{"id": "P1.1", "title": "t",
                                                  "status": "done"}]}]}, fh)
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json"}, fh)
            return M.diagnose(tmp)

        os.makedirs(os.path.join(tmp, "services", "api"), exist_ok=True)
        rep = with_areas({"api": {"root": "services/api"}}, "api")
        check("areas: a registry whose roots exist and whose tags all resolve is OK",
              levels(rep, "areas") == ["OK"], detail(rep, "areas"))
        check("areas: the OK states the counts it is claiming",
              "1 area(s) registered, 1 phase tag(s)" in detail(rep, "areas"),
              detail(rep, "areas"))
        rep = with_areas({"api": {"root": "services/gone"}}, "api")
        check("areas: a root that is not a directory is a WARNING - the manifest "
              "cannot see this, and nothing else will ever report it",
              levels(rep, "areas") == ["WARNING"], detail(rep, "areas"))
        check("areas: the warning names the tag and the path",
              "api -> services/gone" in detail(rep, "areas"), detail(rep, "areas"))
        check("areas: a bad root never fails the exit code (areas are informational)",
              rep.exit_code() == 0, repr(rep.counts()))
        rep = with_areas({"api": {"root": "services/api"}}, "apu")
        check("areas: a tag with no entry is a WARNING naming the phase",
              levels(rep, "areas") == ["WARNING"]
              and "P1 uses 'apu'" in detail(rep, "areas"), detail(rep, "areas"))
        rep = with_areas({}, "anything")
        check("areas: NO registry means the check says nothing at all - a "
              "single-app repo is not nagged about a monorepo feature",
              levels(rep, "areas") == [], repr(levels(rep, "areas")))

        # v0.34 D3: the advisory owner against the ledger's author column -
        # the one place the two identities can be compared. Heavily gated:
        # the ledger must HAVE rows, authorMode must be an identity an owner
        # could be written in (email/name), and only then is an unseen owner
        # worth a question. WARNING at most - identity drift is a
        # coordination smell, not a broken repo.
        _ldir = os.path.join(tmp, ".claude", "usage")
        os.makedirs(_ldir, exist_ok=True)
        with open(os.path.join(_ldir, "2026-08.jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": "2026-08-01T00:00:00Z",
                                 "author": "jane@x.com",
                                 "inputTokens": 1}) + "\n")
        rep = with_areas({"api": {"root": "services/api",
                                  "owner": "jane@x.com"}}, "api")
        check("areas owner: an owner the ledger HAS seen is silent - the "
              "identities join and there is nothing to ask",
              levels(rep, "areas") == ["OK"], detail(rep, "areas"))
        rep = with_areas({"api": {"root": "services/api",
                                  "owner": "Jane Doe"}}, "api")
        check("areas owner: an owner the ledger has never seen is a WARNING "
              "that asks the identity question instead of accusing",
              "WARNING" in levels(rep, "areas")
              and "never appear in the ledger's author column"
                  in detail(rep, "areas")
              and "Jane Doe" in detail(rep, "areas"), detail(rep, "areas"))
        _afix = " ".join(r["fix"] or "" for r in rep.rows
                         if r["check"] == "areas")
        check("areas owner: the fix names the actual join - the form "
              "usage.authorMode records",
              "identity git config reports" in _afix
              and "authorMode" in _afix, _afix)
        check("areas owner: ...and it is never a FINDING",
              rep.exit_code() == 0, repr(rep.counts()))
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json",
                       "usage": {"authorMode": "hash"}}, fh)
        rep = M.diagnose(tmp)
        check("areas owner: authorMode 'hash' silences the hint - pseudonyms "
              "cannot honestly join an email-shaped owner",
              "never appear" not in detail(rep, "areas"),
              detail(rep, "areas"))
        sh.rmtree(_ldir)
        rep = with_areas({"api": {"root": "services/api",
                                  "owner": "Jane Doe"}}, "api")
        check("areas owner: no ledger rows means silence - pre-first-run and "
              "new-member repos are not coordination smells",
              "never appear" not in detail(rep, "areas"),
              detail(rep, "areas"))

        # --- the capability policy (v0.30) ------------------------------------
        # The resolution is exercised in _policy.py's selftest; what is checked
        # here is the two things only a doctor standing in the repo can see.
        # v0.38 fixtures: the dead-pattern check scans a live inventory, and
        # discovery reads the PROJECT's .claude as well as the real home - so
        # the names the existing cases deny are installed here as project
        # skills. Those cases are about refusal and enforcement, not deadness,
        # and this keeps them live-patterned on any machine, a bare CI runner
        # (no ~/.claude at all) included.
        for _sk in ("nothing-uses-this", "house-review"):
            _skd = os.path.join(tmp, ".claude", "skills", _sk)
            os.makedirs(_skd, exist_ok=True)
            with open(os.path.join(_skd, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write("---\nname: %s\ndescription: doctor fixture.\n---\n" % _sk)
        with open(os.path.join(tmp, ".mcp.json"), "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": {"fixsrv": {"command": "x"}}}, fh)

        def with_policy(policy, phases=None, seen=None):
            with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
                json.dump({"meta": {"version": 2, "reviewSkill": "house-review"},
                           "phases": phases or [
                               {"id": "P1", "title": "p", "status": "done",
                                "tasks": [{"id": "P1.1", "title": "t",
                                           "status": "done"}]}]}, fh)
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json", "policy": policy}, fh)
            marker = os.path.join(tmp, ".claude", "state", "capability-guard.json")
            if seen is None:
                if os.path.exists(marker):
                    os.unlink(marker)
            else:
                os.makedirs(os.path.dirname(marker), exist_ok=True)
                with open(marker, "w", encoding="utf-8") as fh:
                    json.dump({"lastRun": "x"}, fh)
                os.utime(marker, (time.time() - seen, time.time() - seen))
            return M.diagnose(tmp)

        rep = with_policy({})
        check("policy: an empty block is inert, and the row says so rather than "
              "implying an enforcement nobody has",
              levels(rep, "policy") == ["OK"]
              and "inert" in detail(rep, "policy"), detail(rep, "policy"))
        rep = with_policy({"enabled": False, "skills": {"deny": ["x"]}})
        check("policy: switched off reads as inert and names the switch",
              levels(rep, "policy") == ["OK"]
              and "policy.enabled is false" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy({"skills": {"deny": ["nothing-uses-this"]}}, seen=60)
        check("policy: an active policy with a fresh marker is OK and states the "
              "violation mode it will use",
              levels(rep, "policy") == ["OK"]
              and "onViolation: deny" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy({"skills": {"deny": ["nothing-uses-this"]}})
        check("policy: an active policy the hook has never enforced is a WARNING - "
              "subagent hook inheritance is not guaranteed, and silence there "
              "would claim an enforcement the repo may not be getting",
              levels(rep, "policy") == ["WARNING"]
              and "advisory" in detail(rep, "policy"), detail(rep, "policy"))
        check("policy: ...and it names the upstream issue rather than hand-waving",
              "43772" in detail(rep, "policy"), detail(rep, "policy"))
        check("policy: a never-fired hook is never a FINDING - nothing is broken",
              rep.exit_code() == 0, repr(rep.counts()))
        rep = with_policy({"skills": {"deny": ["house-review"]}}, seen=60)
        check("policy: a review skill the plan depends on and the policy refuses "
              "is a WARNING - it would otherwise surface at phase sign-off, which "
              "is the worst moment to find out",
              "WARNING" in levels(rep, "policy")
              and "review skill 'house-review'" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy(
            {"skills": {"default": "deny", "allow": ["house-review"]}},
            phases=[{"id": "P1", "title": "p", "status": "done",
                     "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                                "skills": ["python-conv"]}]}], seen=60)
        check("policy: a task's own skill is checked too, named by task id",
              "P1.1 skill 'python-conv'" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy(
            {"skills": {"default": "allow",
                        "areas": {"api": {"deny": ["house-review"]}}}},
            phases=[{"id": "P1", "title": "p", "status": "done", "area": "web",
                     "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}],
            seen=60)
        check("policy: an area rule is judged against the phase's OWN tags, so a "
              "rule for another area is not reported against this one",
              levels(rep, "policy") == ["OK"], detail(rep, "policy"))
        rep = with_policy(
            {"skills": {"default": "allow",
                        "areas": {"api": {"deny": ["house-review"]}}}},
            phases=[{"id": "P1", "title": "p", "status": "done", "area": "api",
                     "tasks": [{"id": "P1.1", "title": "t", "status": "done"}]}],
            seen=60)
        check("policy: ...and IS reported against the phase that carries the tag",
              "WARNING" in levels(rep, "policy")
              and "areas.api.deny" in detail(rep, "policy"), detail(rep, "policy"))
        # A policy that denies audit's own components is a config FINDING, reported
        # by check_config. This row must not restate it: two rows for one defect is
        # the second-place-status problem one size down.
        rep = with_policy({"agents": {"deny": ["audit:*"]}}, seen=60)
        check("policy: denying audit's own components is reported ONCE, by the "
              "config check that already validates the file",
              levels(rep, "config") == ["FINDING"]
              and "not deniable" in detail(rep, "config")
              and not any("not deniable" in r["detail"] for r in rep.rows
                          if r["check"] == "policy"), detail(rep, "policy"))
        # --- dead patterns (v0.38): a rule that names nothing installed HERE --
        rep = with_policy({"skills": {"deny": ["zzz-v38-no-such-*",
                                               "nothing-uses-this"]}}, seen=60)
        _d = detail(rep, "policy")
        check("policy: a pattern matching nothing installed here is a WARNING "
              "with the hedge - the inventory is this machine's, so a typo and "
              "a teammate's tool are indistinguishable - and never a FINDING",
              "WARNING" in levels(rep, "policy")
              and "zzz-v38-no-such-*" in _d
              and "match nothing installed here" in _d
              and "teammate" in _d
              and "FINDING" not in levels(rep, "policy")
              and rep.exit_code() == 0, _d)
        check("policy: ...while the installed name beside it in the same list "
              "stays unmentioned - dead is judged per pattern, not per list",
              "nothing-uses-this" not in _d, _d)
        rep = with_policy({"skills": {"deny": ["nothing-uses-this"],
                                      "allow": ["zzz-v38-dead-allow-*"]}},
                          seen=60)
        check("policy: an allow pattern is walked too - the validator already "
              "calls an allow under default:allow inert, but only a surface "
              "with the inventory can say it also names nothing installed",
              "zzz-v38-dead-allow-*" in detail(rep, "policy")
              and "policy.skills.allow" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy({"skills": {"deny": ["nothing-uses-this"],
                                      "allow": ["audit:*", "audit:next"]}},
                          seen=60)
        check("policy: a pattern that names only audit's own components is not "
              "dead - the plugin ships them, so they are always installed",
              levels(rep, "policy") == ["OK"], detail(rep, "policy"))
        rep = with_policy({"skills": {"areas": {"api":
                                                {"deny": ["zzz-v38-a-*"]}}}},
                          seen=60)
        check("policy: an area rule's dead pattern is named with its full path",
              "policy.skills.areas.api.deny" in detail(rep, "policy")
              and "zzz-v38-a-*" in detail(rep, "policy"), detail(rep, "policy"))
        rep = with_policy({"mcp": {"deny": ["mcp__fixsrv__dangerous_tool"]}},
                          seen=60)
        check("policy: a rule for one tool of a configured MCP server is alive "
              "- matched both ways against the server stand-in",
              levels(rep, "policy") == ["OK"], detail(rep, "policy"))
        rep = with_policy({"mcp": {"deny": ["mcp__zzz-v38-nosrv__*"]}}, seen=60)
        check("policy: ...and a rule for a server nobody configured is dead",
              "mcp__zzz-v38-nosrv__*" in detail(rep, "policy"),
              detail(rep, "policy"))
        rep = with_policy({"skills": {"allow": ["zzz-v38-inert-*"]}})
        check("policy: an inert policy is never scanned - the allow-only block "
              "already reads 'inert', dead or not, and the validator's "
              "no-effect warning owns that story",
              levels(rep, "policy") == ["OK"]
              and "inert" in detail(rep, "policy"), detail(rep, "policy"))
        # Fail-open, driven through the seam rather than hoped about: a scan
        # that raises and a scan that found NOTHING AT ALL both say nothing.
        # A working scan always sees audit's own plugin tree, so a truly empty
        # inventory is a broken scanner, not an empty machine - and warning
        # about every pattern there would be noise about the wrong thing.
        _pol_cfg = {"manifestPath": "plan.json",
                    "policy": {"skills": {"deny": ["zzz-v38-no-such-*"]}}}
        _cm = M._load("_config", "_config.py", M._HOOKS)

        def _cp_rows(scan):
            r2 = M.Report()
            try:
                M.check_policy(r2, tmp, _pol_cfg, _cm, {"phases": []},
                             _discover=scan)
            except Exception as exc:               # noqa: BLE001 - the check
                return "raised %s" % type(exc).__name__
            return r2.rows

        def _boom(_project):
            raise RuntimeError("discovery broke")

        _r_raise = _cp_rows(_boom)
        _r_empty = _cp_rows(lambda _p: {"skills": [], "agents": [], "mcp": []})
        check("policy: no inventory - a raising scan and an empty one both say "
              "nothing about dead patterns rather than crying about the scan",
              isinstance(_r_raise, list) and isinstance(_r_empty, list)
              and not any("match nothing installed here" in r["detail"]
                          for r in _r_raise + _r_empty),
              repr((_r_raise, _r_empty)))
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)

        # --- the audit trail (v0.29) ------------------------------------------
        # Graded the way the journal itself grades: a broken chain is the only
        # thing that can fail a doctor run, because it is the only one that cannot
        # happen by accident.
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json",
                       "journal": {"dir": "trail"}}, fh)
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "p", "status": "done", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "done"}]}]}, fh)
        rep = M.diagnose(tmp)
        check("journal: a repo that has recorded nothing yet is OK, not a warning "
              "- that is what every repo looks like before its first write",
              levels(rep, "journal") == ["OK"]
              and "no writes recorded yet" in detail(rep, "journal"),
              detail(rep, "journal"))
        jr = M._load("audit_journal", "audit-journal.py")
        for i in range(2):
            jr.append(tmp, {"action": "manifest.edit", "target": "plan.json",
                            "summary": "row %d" % i,
                            "actor": {"sessionId": "doc", "via": "hook"}})
        rep = M.diagnose(tmp)
        check("journal: an intact chain is OK and counts its rows",
              levels(rep, "journal") == ["OK"] and "2 row(s)" in detail(rep, "journal"),
              detail(rep, "journal"))
        check("journal: an intact chain never affects the exit code",
              rep.exit_code() == 0, repr(rep.counts()))
        # Out-of-band drift: the plan moved with no row to explain it. A warning,
        # because a git checkout does exactly this and is nobody's tampering.
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": []}, fh)
        rep = M.diagnose(tmp)
        check("journal: a document that changed with no row to explain it is a "
              "WARNING, and the exit code stays 0",
              levels(rep, "journal") == ["WARNING"] and rep.exit_code() == 0,
              detail(rep, "journal"))
        # A tampered row: this one IS a finding.
        _jf = jr.journal_files(jr.journal_dir(tmp))[0]
        _rows, _ = jr.read_file(_jf)
        _rows[0]["summary"] = "nothing happened"
        with open(_jf, "w", encoding="utf-8") as fh:
            for _r in _rows:
                fh.write(jr.canonical(_r) + "\n")
        rep = M.diagnose(tmp)
        check("journal: an edited row is a FINDING and fails the run",
              levels(rep, "journal") == ["FINDING"] and rep.exit_code() == 1,
              detail(rep, "journal"))
        check("journal: the finding says what was wrong, not just that something was",
              "edited after it was written" in detail(rep, "journal"),
              detail(rep, "journal"))
        # UPDATED PIN (workstream B, deliberate contract change): a disabled
        # journal with recorded rows used to read as plain OK, which graded
        # "the trail was running and someone turned it off" identically to
        # "this repo never used it". Rows present -> WARNING; the chain itself
        # is still not verified (a broken chain in a disabled journal is not
        # this run's business), and it is NEVER a finding -- nothing overrides
        # the user's own switch.
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json",
                       "journal": {"dir": "trail", "enabled": False}}, fh)
        rep = M.diagnose(tmp)
        check("journal: switched off WITH rows on disk is a WARNING that says "
              "the trail was running and has been turned off",
              levels(rep, "journal") == ["WARNING"]
              and "turned off" in detail(rep, "journal"),
              detail(rep, "journal"))
        check("journal: ...and never a FINDING - the user's switch is theirs",
              rep.exit_code() == 0, repr(rep.counts()))
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json",
                       "journal": {"dir": "trail-never", "enabled": False}}, fh)
        rep = M.diagnose(tmp)
        check("journal: switched off with NO rows anywhere stays a plain OK",
              levels(rep, "journal") == ["OK"]
              and "disabled" in detail(rep, "journal"), detail(rep, "journal"))

        # D4 / F-F1: journal git hygiene. The git anchor only pins committed
        # history, so a journal file that has sat UNTRACKED for more than 7
        # days is work the anchor cannot protect - a WARNING that names it,
        # never a FINDING (absence of a commit is not evidence of forgery).
        # Fresh uncommitted files are the normal write-then-commit rhythm and
        # stay silent.
        if have_git:
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail2"}}, fh)
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "hygiene row",
                            "actor": {"sessionId": "hyg", "via": "hook"}})
            rep = M.diagnose(tmp)
            check("journal hygiene: a FRESH uncommitted file is silent - "
                  "write-then-commit is the normal rhythm",
                  "never been committed" not in detail(rep, "journal"),
                  detail(rep, "journal"))
            _hf = jr.journal_files(jr.journal_dir(tmp))[0]
            _old8 = time.time() - 8 * 86400
            os.utime(_hf, (_old8, _old8))
            rep = M.diagnose(tmp)
            check("journal hygiene: an 8-day-old uncommitted file is a WARNING "
                  "naming the count, the oldest file and what the anchor "
                  "cannot do for it",
                  "WARNING" in levels(rep, "journal")
                  and "1 journal file(s) have never been committed"
                      in detail(rep, "journal")
                  and "the git anchor only pins committed history"
                      in detail(rep, "journal")
                  and os.path.basename(_hf) in detail(rep, "journal"),
                  detail(rep, "journal"))
            check("journal hygiene: ...and never a FINDING, never the exit code",
                  rep.counts()["FINDING"] == 0 and rep.exit_code() == 0,
                  repr(rep.counts()))
            _hfix = " ".join(r["fix"] or "" for r in rep.rows
                             if r["check"] == "journal")
            check("journal hygiene: the fix says commit it, and warns off "
                  ".gitignore", "commit" in _hfix and "gitignore" in _hfix,
                  _hfix)
            subprocess.run(["git", "-C", tmp, "add", "trail2"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-q", "-m", "trail2"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            rep = M.diagnose(tmp)
            check("journal hygiene: once committed, the warning is gone and "
                  "the chain reads plain OK",
                  levels(rep, "journal") == ["OK"]
                  and "never been committed" not in detail(rep, "journal"),
                  detail(rep, "journal"))

        # --- journal archive (v0.37 D) ---------------------------------------
        # `journal/archive/` holds whole month-files moved by `audit-journal.py
        # archive` via git mv: untouched bytes under the same basename, so
        # jr.verify counts them and the doctor's totals must include them. A
        # git mv leaves a STAGED RENAME -- porcelain says "R ", not "??" -- so
        # a moved-but-uncommitted file must never trip never-committed: its
        # history IS committed, at the pre-move path, and the archive
        # subcommand's own output already says to commit the move. An UNTRACKED
        # file in archive/ is the same unanchored work it was live, and the
        # warning follows it there.
        if have_git:
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail3"}}, fh)
            t3 = os.path.join(tmp, "trail3")
            _t = time.gmtime()
            _y, _m = ((_t.tm_year, _t.tm_mon - 2) if _t.tm_mon > 2
                      else (_t.tm_year - 1, _t.tm_mon + 10))
            _oldmo = "%04d-%02d" % (_y, _m)
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "old row",
                            "ts": _oldmo + "-01T00:00:00Z",
                            "actor": {"sessionId": "arch", "via": "hook"}})
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "live row",
                            "actor": {"sessionId": "arch", "via": "hook"}})
            subprocess.run(["git", "-C", tmp, "add", "trail3"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-q", "-m",
                            "trail3"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            rep = M.diagnose(tmp)
            check("journal archive: baseline before the move -- 2 rows in 2 "
                  "files read OK",
                  levels(rep, "journal") == ["OK"]
                  and "2 row(s) in 2 file(s)" in detail(rep, "journal"),
                  detail(rep, "journal"))
            # The sanctioned git mv: inside THIS tmp fixture repo only.
            os.makedirs(os.path.join(t3, "archive"), exist_ok=True)
            subprocess.run(["git", "-C", tmp, "mv",
                            "trail3/%s.arch.jsonl" % _oldmo,
                            "trail3/archive/%s.arch.jsonl" % _oldmo],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            _moved = os.path.join(t3, "archive", "%s.arch.jsonl" % _oldmo)
            _old8 = time.time() - 8 * 86400
            os.utime(_moved, (_old8, _old8))
            rep = M.diagnose(tmp)
            check("journal archive: rows moved into archive/ are still "
                  "counted -- 2 row(s) in 2 file(s), chain intact",
                  levels(rep, "journal") == ["OK"]
                  and "2 row(s) in 2 file(s)" in detail(rep, "journal"),
                  detail(rep, "journal"))
            check("journal archive: a tracked file whose MOVE is staged but "
                  "uncommitted never trips never-committed (porcelain calls "
                  "it R, not ??; its history is committed at the old path)",
                  "never been committed" not in detail(rep, "journal"),
                  detail(rep, "journal"))
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "never committed",
                            "ts": _oldmo + "-02T00:00:00Z",
                            "actor": {"sessionId": "arch2", "via": "hook"}})
            _un_arch = os.path.join(t3, "archive", "%s.arch2.jsonl" % _oldmo)
            os.rename(os.path.join(t3, "%s.arch2.jsonl" % _oldmo), _un_arch)
            os.utime(_un_arch, (_old8, _old8))
            rep = M.diagnose(tmp)
            check("journal archive: an 8-day-old UNTRACKED file inside "
                  "archive/ IS covered by the never-committed warning",
                  "WARNING" in levels(rep, "journal")
                  and "never been committed" in detail(rep, "journal")
                  and os.path.basename(_un_arch) in detail(rep, "journal"),
                  detail(rep, "journal"))
            with open(_un_arch, "r", encoding="utf-8") as fh:
                _row0 = json.loads(fh.readline())
            _row0["summary"] = "nothing happened"
            with open(_un_arch, "w", encoding="utf-8") as fh:
                fh.write(jr.canonical(_row0) + "\n")
            rep = M.diagnose(tmp)
            check("journal archive: a broken chain inside archive/ is a "
                  "FINDING and fails the run",
                  levels(rep, "journal") == ["FINDING"]
                  and rep.exit_code() == 1, detail(rep, "journal"))
            os.unlink(_un_arch)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-q", "-m",
                            "archive move"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            rep = M.diagnose(tmp)
            check("journal archive: with the move committed, the archive "
                  "reads plain OK",
                  levels(rep, "journal") == ["OK"], detail(rep, "journal"))
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail2"}}, fh)

        # --- journal basename collision (F-D-1) ---------------------------
        # The same basename live AND archived: an already-anomalous state
        # that verify() flags as a duplicate WARNING. never-committed must
        # still count ONLY the untracked file -- the status lookup is keyed
        # by journal-relative path, so the tracked+committed archive twin
        # can never answer for the untracked live one (basename keying
        # counted both, and "oldest" could name the wrong file).
        if have_git:
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail4"}}, fh)
            t4 = os.path.join(tmp, "trail4")
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "archived twin",
                            "ts": _oldmo + "-01T00:00:00Z",
                            "actor": {"sessionId": "coll", "via": "hook"}})
            _cname = "%s.coll.jsonl" % _oldmo
            os.makedirs(os.path.join(t4, "archive"), exist_ok=True)
            os.rename(os.path.join(t4, _cname),
                      os.path.join(t4, "archive", _cname))
            subprocess.run(["git", "-C", tmp, "add", "trail4"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-q", "-m",
                            "archived twin"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            jr.append(tmp, {"action": "manifest.edit", "target": "",
                            "summary": "live twin",
                            "ts": _oldmo + "-02T00:00:00Z",
                            "actor": {"sessionId": "coll", "via": "hook"}})
            _old10 = time.time() - 10 * 86400
            os.utime(os.path.join(t4, "archive", _cname), (_old10, _old10))
            _old8c = time.time() - 8 * 86400
            os.utime(os.path.join(t4, _cname), (_old8c, _old8c))
            rep = M.diagnose(tmp)
            check("journal collision: a tracked+committed archive twin of an "
                  "untracked live basename is NOT counted by never-committed "
                  "- exactly 1 file, and oldest names the live one",
                  "1 journal file(s) have never been committed"
                      in detail(rep, "journal")
                  and ("(oldest %s," % _cname) in detail(rep, "journal")
                  and "oldest archive/" not in detail(rep, "journal"),
                  detail(rep, "journal"))
            check("journal collision: ...and still never a FINDING - the "
                  "duplicate itself stays verify's WARNING",
                  rep.counts()["FINDING"] == 0 and rep.exit_code() == 0,
                  repr(rep.counts()))
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail2"}}, fh)
        os.remove(os.path.join(tmp, "plan.json"))

        # proposals: a park-all init leaves 0 phases + parked proposals, and the
        # ok line must SAY so - "valid (0 phases, 0 tasks)" alone reads as dead.
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [], "proposals": [
                {"id": "PROP-1", "name": "Parked work", "status": "proposed",
                 "payload": {"phase": {"id": "P1", "title": "Parked work",
                                       "status": "pending", "tasks": []}}}]}, fh)
        rep = M.diagnose(tmp)
        check("manifest: parked proposals are counted in the ok line",
              "1 parked proposal(s)" in detail(rep, "manifest"),
              detail(rep, "manifest"))
        os.remove(os.path.join(tmp, "plan.json"))

        # F-E3 sibling: a proposal whose status is OUTSIDE the vocabulary
        # (proposed|materialized|dropped) is real tracked work too - the ok
        # line must count it rather than let it vanish into "0 phases, 0 tasks".
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [], "proposals": [
                {"id": "modernize-build", "name": "Modernize build",
                 "status": "open"}]}, fh)
        rep = M.diagnose(tmp)
        check("manifest: legacy free-form proposals are counted in the ok line",
              "1 legacy proposal(s)" in detail(rep, "manifest"),
              detail(rep, "manifest"))
        os.remove(os.path.join(tmp, "plan.json"))

        # The OTHER direction, and it was missing: nothing pinned the NUMBER, so
        # `n_tasks` could have been replaced by a constant 0 and all 146 cases
        # stayed green (measured, by doing exactly that). A count that no case
        # reads is not a checked count. The fixture is 2 phases holding 3 tasks
        # UNEVENLY - one phase with 1, one with 2 - so the assertion separates a
        # real total from a phase count, from a per-phase count, and from 0.
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "one", "status": "pending", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "pending"}]},
                {"id": "P2", "title": "two", "status": "pending", "tasks": [
                    {"id": "P2.1", "title": "t", "status": "pending"},
                    {"id": "P2.2", "title": "t", "status": "pending"}]}]}, fh)
        rep_cnt = M.diagnose(tmp)
        check("manifest: the ok line counts every task across every phase",
              "(2 phases, 3 tasks" in detail(rep_cnt, "manifest"),
              detail(rep_cnt, "manifest"))
        os.remove(os.path.join(tmp, "plan.json"))

        # A doctor must survive the broken input it exists to describe. The task
        # count beside "N phases" was hand-rolled as
        # `sum(len(p.get("tasks") or []) for p in phases)` with no isinstance
        # guard, so a non-dict PHASE raised AttributeError one line after
        # `validate()` had already produced the finding that names it - the whole
        # run died instead of printing it. Counting through
        # `_manifest_io.iter_tasks` is what makes the line survive.
        #
        # `diagnose()` is called inside a try so the REINTRODUCED bug reports as a
        # clean FAIL naming the exception. Without it the mutation kills the whole
        # suite before any case runs, and a suite that never ran is not a red one.
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": [
                {"id": "P1", "title": "real", "status": "pending", "tasks": [
                    {"id": "P1.1", "title": "t", "status": "pending"}]},
                "not-a-phase"]}, fh)
        try:
            rep_bad = M.diagnose(tmp)
            _bad_lv, _bad_dt = levels(rep_bad, "manifest"), detail(rep_bad, "manifest")
        except Exception as _exc:
            _bad_lv, _bad_dt = [], "diagnose() RAISED %r" % (_exc,)
        check("manifest: a non-object phase entry is REPORTED, not crashed on - "
              "the count beside 'N phases' walks the shared traversal",
              _bad_lv == ["FINDING"] and "phases[1]: not an object" in _bad_dt,
              "%r %s" % (_bad_lv, _bad_dt))
        os.remove(os.path.join(tmp, "plan.json"))

        # sharded layout: intact, then broken
        gen = M._load("gen_demo_manifest", "gen-demo-manifest.py")
        shard_dir = os.path.join(tmp, "sharded")
        gen.write_manifest(gen.generate(n_phases=4, n_tasks=2, seed=11), shard_dir)
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "sharded/audit-plan.json"}, fh)
        rep = M.diagnose(tmp)
        check("an intact sharded layout is OK", levels(rep, "layout") == ["OK"],
              detail(rep, "layout"))
        os.remove(os.path.join(shard_dir, "phases", "P1.json"))
        rep = M.diagnose(tmp)
        check("a missing shard is a FINDING", levels(rep, "layout") == ["FINDING"],
              detail(rep, "layout"))

        # the executable resolver, against the shapes real manifests use. Guessing
        # here produced a false FINDING on this repo's own `for f in ...; do` loop.
        for cmd, want in (("yarn test", "yarn"),
                          ("python3 x.py --gate", "python3"),
                          ("cd app && yarn test", "yarn"),
                          ("cd a && cd b && npm run t", "npm"),
                          ("env CI=1 pytest -q", "pytest"),
                          ("CI=1 NODE_ENV=test jest", "jest"),
                          ("claude plugin validate . && claude plugin validate p",
                           "claude"),
                          ("./scripts/run.sh", "./scripts/run.sh"),
                          ("for f in a b; do python3 $f; done", None),
                          ("if [ -f x ]; then make; fi", None),
                          ("$RUNNER test", None),
                          ("", None)):
            got = M._leading_executable(cmd)
            check("resolver: %r -> %r" % (cmd[:34], want), got == want, repr(got))

        # a shell-construct command is reported as unchecked, never as missing
        with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"manifestPath": "plan.json"}, fh)
        with open(os.path.join(tmp, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "selftests": "for f in a b; do %s -c pass $f; done" % real}},
                "phases": [{"id": "P1", "title": "p", "status": "done",
                            "tasks": [{"id": "P1.1", "title": "t",
                                       "status": "done"}]}]}, fh)
        rep_sh = M.diagnose(tmp)
        check("a shell-construct gate is a WARNING, not a missing-runner FINDING",
              "FINDING" not in levels(rep_sh, "buildCommands"),
              repr(levels(rep_sh, "buildCommands")))
        check("and it says the runner was not checked",
              "not checked" in detail(rep_sh, "buildCommands"),
              detail(rep_sh, "buildCommands"))

        # --- completion records (workstream B: check_completions) --------------
        # The journal's task.complete rows are the pipeline's receipt for a done
        # task. check_completions joins them against the manifest, watermarked by
        # the FIRST record, so history an older plugin wrote never goes red.
        if have_git:
            jr2 = M._load("audit_journal", "audit-journal.py")
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json",
                           "journal": {"dir": "trail2"}}, fh)

            def ctask(tid, completed=None, commit=None):
                return {"id": tid, "title": "t", "status": "done",
                        "completedAt": completed, "commit": commit}

            def cplan(tasks):
                with open(os.path.join(tmp, "plan.json"), "w",
                          encoding="utf-8") as fh:
                    json.dump({"meta": {"version": 2}, "phases": [
                        {"id": "P1", "title": "p", "status": "in_progress",
                         "tasks": tasks}]}, fh)

            def crow(tid, completed):
                jr2.append(tmp, {"action": "task.complete", "target": "plan.json",
                                 "summary": "%s done" % tid, "ts": now,
                                 "details": {"taskId": tid, "phaseId": "P1",
                                             "from": "in_progress", "to": "done",
                                             "completedAt": completed},
                                 "actor": {"sessionId": "doc2", "via": "hook"}})

            cplan([ctask("P1.1", completed=now)])
            subprocess.run(["git", "-C", tmp, "add", "-A"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t",
                            "-c", "user.name=t", "commit", "-q", "-m", "fixture"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sha = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"],
                                 stdout=subprocess.PIPE).stdout.decode().strip()

            repc = M.diagnose(tmp)
            check("completions: zero task.complete rows is a single plain OK "
                  "naming the older plugin, never a nag",
                  levels(repc, "completions") == ["OK"]
                  and "not in use" in detail(repc, "completions"),
                  detail(repc, "completions"))

            # compliant: record + real SHA + ledger row -> OK, exit 0
            crow("P1.1", now)
            cplan([ctask("P1.1", completed=now, commit=sha)])
            os.makedirs(os.path.join(tmp, ".claude", "usage"), exist_ok=True)
            lpath = os.path.join(tmp, ".claude", "usage",
                                 "%s.jsonl" % now[:7])
            with open(lpath, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": now, "taskId": "P1.1",
                                     "phaseId": "P1"}) + "\n")
            repc = M.diagnose(tmp)
            check("completions: a compliant done task (record, real SHA, ledger "
                  "rows) is OK",
                  levels(repc, "completions") == ["OK"]
                  and "carry chained records" in detail(repc, "completions"),
                  detail(repc, "completions"))
            check("completions: ...and does not fail the run",
                  repc.exit_code() == 0, repr(repc.counts()))

            # hand-flipped to done with no record -> FINDING
            cplan([ctask("P1.1", completed=now, commit=sha),
                   ctask("P1.2", completed=now, commit=sha)])
            repc = M.diagnose(tmp)
            check("completions: a done task with no completion record is a "
                  "FINDING that says what it means",
                  "FINDING" in levels(repc, "completions")
                  and "no completion record" in detail(repc, "completions")
                  and "edited outside the pipeline" in detail(repc, "completions"),
                  detail(repc, "completions"))
            check("completions: ...and it fails the run", repc.exit_code() == 1)

            # fabricated SHA -> FINDING (the first place a commit is checked
            # against git at all)
            crow("P1.2", now)
            cplan([ctask("P1.1", completed=now, commit=sha),
                   ctask("P1.2", completed=now, commit="deadbeef" * 5)])
            repc = M.diagnose(tmp)
            check("completions: a commit git does not have is a FINDING",
                  "FINDING" in levels(repc, "completions")
                  and "git does not have" in detail(repc, "completions"),
                  detail(repc, "completions"))

            # pre-watermark done tasks -> out of scope, OK
            cplan([ctask("P1.1", completed=now, commit=sha),
                   ctask("P1.3", completed="2020-01-01T00:00:00Z")])
            repc = M.diagnose(tmp)
            check("completions: done tasks that PREDATE the first record are "
                  "out of scope - an aggregate line, no finding",
                  "FINDING" not in levels(repc, "completions")
                  and "predate" in detail(repc, "completions"),
                  detail(repc, "completions"))

            # record ts vs completedAt drift beyond 24h -> WARNING. The drift is
            # derived from `now` (F-A1: a hardcoded date here went red the day the
            # calendar caught up with it) - 48h guarantees the >24h gap forever.
            drifted = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                    time.gmtime(time.time() + 48 * 3600))
            crow("P1.4", drifted)
            cplan([ctask("P1.1", completed=now, commit=sha),
                   ctask("P1.4", completed=drifted, commit=sha)])
            repc = M.diagnose(tmp)
            check("completions: record ts vs completedAt drift beyond 24h is a "
                  "WARNING, not an accusation",
                  "FINDING" not in levels(repc, "completions")
                  and "WARNING" in levels(repc, "completions")
                  and "24h" in detail(repc, "completions"),
                  detail(repc, "completions"))

            # a done task with a record but no commit SHA -> WARNING
            crow("P1.5", now)
            cplan([ctask("P1.1", completed=now, commit=sha),
                   ctask("P1.5", completed=now, commit=None)])
            repc = M.diagnose(tmp)
            check("completions: a null task.commit is a WARNING",
                  "FINDING" not in levels(repc, "completions")
                  and "no commit SHA" in detail(repc, "completions"),
                  detail(repc, "completions"))

            # zero ledger rows for an in-scope task -> WARNING + backfill hint
            os.unlink(lpath)
            cplan([ctask("P1.1", completed=now, commit=sha)])
            repc = M.diagnose(tmp)
            cfix = " ".join(r["fix"] or "" for r in repc.rows
                            if r["check"] == "completions")
            check("completions: zero ledger rows for the task is a WARNING that "
                  "names the --backfill repair",
                  "WARNING" in levels(repc, "completions")
                  and "--backfill" in cfix,
                  detail(repc, "completions") + " | " + cfix)
            with open(lpath, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": now, "taskId": "P1.1",
                                     "phaseId": "P1"}) + "\n")

            # --deep: the task commit should carry the journal file that
            # records it. The fixture commit predates the journal rows, so deep
            # warns -- and the default run says nothing about it.
            repc = M.diagnose(tmp)
            check("completions: the deep check is OFF by default",
                  "does not carry the journal" not in detail(repc, "completions"),
                  detail(repc, "completions"))
            repc = M.diagnose(tmp, deep=True)
            check("completions: --deep warns when the task commit does not "
                  "carry the journal file that records it",
                  "WARNING" in levels(repc, "completions")
                  and "does not carry the journal" in detail(repc, "completions"),
                  detail(repc, "completions"))

            with open(os.path.join(tmp, ".claude", "audit.config.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"manifestPath": "plan.json"}, fh)

        # rendering + json shape
        text = M.render(rep, tmp)
        check("render is pure ASCII", all(ord(c) < 128 for c in text))
        check("render carries no ANSI escapes", "\033" not in text)
        check("render prints the totals line", "finding(s)" in text)
        check("every row renders its level", text.count("[FINDING") >= 1)
        check("CLI exits 2 on a non-directory",
              M.main(["--project", os.path.join(tmp, "nope")]) == 2)
        check("CLI --json emits parseable JSON", _json_ok(tmp))

        # color (--color through _cli_fmt). Plain mode must stay byte-identical
        # to the pre-color render; painting wraps the level tokens and nothing
        # else, and strips back to the exact plain bytes.
        check("color: --color never renders byte-identically to the plain "
              "default",
              M.render(rep, tmp, pt=_cli_fmt.painter("never")) == text)
        painted = M.render(rep, tmp, pt=_cli_fmt.painter("always"))
        check("color: a painted render marks the level tokens - FINDING red, "
              "OK green",
              "\033[31m[FINDING]\033[0m" in painted
              and "\033[32m[OK     ]\033[0m" in painted, painted[:200])
        check("color: painted output strips back to the plain render byte "
              "for byte", _cli_fmt.strip(painted) == text)
        check("color: painted output is still pure ASCII (ANSI escapes are "
              "ASCII)", all(ord(c) < 128 for c in painted))
        import contextlib as _ctx
        import io as _io
        _jbuf = _io.StringIO()
        with _ctx.redirect_stdout(_jbuf):
            M.main(["--project", tmp, "--json", "--color", "always"])
        check("color: --json ignores --color entirely (parseable, no escapes)",
              "\033" not in _jbuf.getvalue()
              and isinstance(json.loads(_jbuf.getvalue()).get("checks"), list))

        # --- local artifacts hygiene (the ignore that was only ever claimed) -
        if have_git:
            hyg = tempfile.mkdtemp(prefix="doctor-hygiene-")
            try:
                subprocess.run(["git", "init", "-q", hyg],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30,
                               check=True)

                def hyg_fix(rep_x):
                    return " ".join(r["fix"] or "" for r in rep_x.rows
                                    if r["check"] == "hygiene")

                rep_h = M.diagnose(hyg)
                check("hygiene: a repo with no local artifacts is OK",
                      levels(rep_h, "hygiene") == ["OK"],
                      detail(rep_h, "hygiene"))
                os.makedirs(os.path.join(hyg, ".claude", "usage"))
                with open(os.path.join(hyg, ".claude", "usage",
                                       "2026-08.jsonl"), "w",
                          encoding="utf-8") as fh:
                    fh.write("{}\n")
                rep_h = M.diagnose(hyg)
                check("hygiene: an unprotected local dir is a WARNING with "
                      "the self-ignore hint",
                      "WARNING" in levels(rep_h, "hygiene")
                      and "self-ignore" in hyg_fix(rep_h),
                      detail(rep_h, "hygiene") + hyg_fix(rep_h))
                with open(os.path.join(hyg, ".claude", "usage", ".gitignore"),
                          "w", encoding="utf-8") as fh:
                    fh.write("*\n")
                rep_h = M.diagnose(hyg)
                check("hygiene: a marker-protected dir goes back to OK",
                      levels(rep_h, "hygiene") == ["OK"],
                      detail(rep_h, "hygiene"))
                pid_h = os.path.join(hyg, ".claude", "audit-panel.json")
                with open(pid_h, "w", encoding="utf-8") as fh:
                    json.dump({"url": "http://127.0.0.1:1?t=secret"}, fh)
                subprocess.run(["git", "add", "-f",
                                os.path.join(".claude", "audit-panel.json")],
                               cwd=hyg, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
                rep_h = M.diagnose(hyg)
                check("hygiene: a TRACKED panel pidfile warns about the live "
                      "token and says how to rotate it",
                      "WARNING" in levels(rep_h, "hygiene")
                      and "token" in detail(rep_h, "hygiene")
                      and "rotate" in hyg_fix(rep_h),
                      detail(rep_h, "hygiene"))
                check("hygiene: never a FINDING - a leak is a privacy defect, "
                      "not evidence of forgery",
                      "FINDING" not in levels(rep_h, "hygiene"),
                      repr(levels(rep_h, "hygiene")))
            finally:
                sh.rmtree(hyg, ignore_errors=True)
    finally:
        sh.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_audit_doctor.py --selftest\n")
    raise SystemExit(2)
