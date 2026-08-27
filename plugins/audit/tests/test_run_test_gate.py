#!/usr/bin/env python3
"""Cases for `governance/run-test-gate.py` (F193).

WHAT THIS FILE IS ABOUT, in one line: a gate is a MEASUREMENT, and the two ways
this one stopped being a measurement were both exit 0.

Measured live before any of this existed. A docs task's gate was
`pre-commit run --all-files`; `isort` and `black` are fix-in-place, so they
rewrote five source files the task does not own and reported `Passed` BECAUSE
they had. Then, narrowed to the task's own two markdown files, every hook
SKIPPED -- that repo configures Python hooks only -- and the task went to `done`
on exit 0 with zero checks performed. One design, both failure modes, and the
exit code separated neither from a real verdict.

THE `runner` SEAM IS THE WHOLE REASON THESE CASES EXIST. `run_gate` takes the
command runner as an argument, so a fix-in-place hook can be simulated by a
runner that touches a file, and a skipping hook by one that prints `Skipped`.
Without that seam every case here would need a repository with `pre-commit`
installed, which is to say there would be no cases.

`git` IS REAL, though. The mutation half is a `git status --porcelain` diff, and
faking that would test the arithmetic rather than the question -- so the fixture
is an actual repository and the "mutation" is an actual file appearing in it.
"""
import json
import os
import signal
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve by basename)
import _journal_io                                 # noqa: E402  (the rows a stamp anchors)

M = _loader.load_script("run-test-gate.py", "rtg")


def _recorded_rows(directory):
    """Every row in the evidence directory, in the order they landed.

    Read off the DISK rather than through `_evidence_io.read_rows`, because the
    question these cases put is what a reader of the committed file sees -- and a
    reader that went through the writer's own module could not tell a field that
    was never written from one the reader supplies.
    """
    rows = []
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _cases(check):
    # `_harness.fixture_root`, NOT a bare mkdtemp with a trailing rmtree. It exists
    # for F119 and it is the only spelling that survives windows: git writes its
    # loose objects READ-ONLY, and on windows the read-only attribute is checked on
    # the FILE, so `shutil.rmtree(..., ignore_errors=True)` leaves `.git/objects/**`
    # behind and leaves it behind SILENTLY. This suite hand-rolled the pair and CI's
    # windows leg caught it through the sweep's own isolation guard - the removal
    # had simply never worked there.
    tmp = _harness.fixture_root("run-test-gate-selftest-")
    subprocess.run(["git", "init", "-q", tmp], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(tmp, "tracked.txt"), "w") as fh:
        fh.write("x\n")
    subprocess.run(["git", "-C", tmp, "add", "tracked.txt"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- the gate resolves through meta.buildCommands, once ----------------
    man = {"meta": {"version": 2,
                    "buildCommands": {"lint": "pre-commit run --all-files",
                                      "test": "pytest -q"}},
           "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                       "testGate": ["lint", "test"], "tasks": []},
                      {"id": "P2", "title": "two", "status": "pending",
                       "testGate": [], "tasks": []},
                      {"id": "P3", "title": "three", "status": "pending",
                       "testGate": ["echo literal"], "tasks": []}]}
    cmds, _srcA, err = M.gate_of(man, "P1")
    check("rg1 the gate resolves each entry through meta.buildCommands, "
          "because a second resolution here would be a second answer to "
          "'what is this phase's gate': %r" % (cmds,),
          err is None
          and cmds == [("lint", "pre-commit run --all-files"),
                       ("test", "pytest -q")])
    cmds3, _srcB, _errB = M.gate_of(man, "P3")
    check("rg2 ...and an entry naming no build command is carried VERBATIM - "
          "it may be a literal shell command, and refusing it would make this "
          "script decide what a gate is allowed to be: %r" % (cmds3,),
          cmds3 == [("echo literal", "echo literal")])
    _none, _srcC, err_none = M.gate_of(man, "P9")
    check("rg3 an unknown phase is an error rather than an empty gate - "
          "'this phase has no gate' and 'there is no such phase' are two "
          "different answers: %r" % (err_none,),
          _none is None and "no phase" in (err_none or ""))

    # --- the mutation bracket, against a REAL repository -------------------
    def _quiet(_project, _command, _timeout=None):
        return 0, "all good\n", {}

    res = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("rg4 a gate that changes nothing reports no mutation, and the basis "
          "says git was actually asked: %r"
          % ((res["treeMutated"], res["treeBasis"]),),
          res["treeMutated"] == [] and res["failed"] == []
          and res["treeBasis"].startswith("git described"))

    def _fix_in_place(project, _command, _timeout=None):
        # `isort`/`black`'s shape: it rewrites and then reports success.
        with open(os.path.join(project, "rewritten.py"), "w") as fh:
            fh.write("import os\n")
        return 0, "Passed\n", {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_fix_in_place)
    check("rg5 THE FAULT: a gate that passed BECAUSE it rewrote the tree is "
          "caught, with the file named - exit 0 said nothing was wrong and "
          "five source files had changed: %r" % (res["treeMutated"],),
          res["failed"] == []
          and any("rewritten.py" in line for line in res["treeMutated"]))
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg6 ...and it REFUSES regardless of the gate's own exit code, "
          "naming what to do - a measurement with side effects has answered a "
          "different question, and a commit on it carries work no task owns "
          "and no review saw: %r" % (text[:120],),
          code == M.E_FAIL and "GATE MUTATED THE TREE" in text
          and "Do NOT commit" in text)
    # Leave the fixture as it was: the next case asserts on a clean tree.
    os.remove(os.path.join(tmp, "rewritten.py"))

    # --- the other failure mode: nothing ran -------------------------------
    def _all_skipped(_project, _command, _timeout=None):
        return 0, ("check yaml.....................Skipped\n"
                   "black.........................Skipped\n"), {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                     runner=_all_skipped)
    check("rg7 THE OTHER FAULT: a gate where every hook SKIPPED is exit 0 "
          "with zero checks, and the count is read rather than assumed: %r"
          % (res["ranTotal"],),
          res["failed"] == [] and res["treeMutated"] == []
          and res["ranTotal"] == 0)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg8 ...and that is REFUSED too, said as what it is: a gate that "
          "skipped everything and a gate that verified everything are the "
          "same exit code: %r" % (text[:110],),
          code == M.E_FAIL and "NO CHECK RAN" in text)

    def _two_ran(_project, _command, _timeout=None):
        return 0, ("check yaml.....................Passed\n"
                   "black.........................Passed\n"
                   "mypy..........................Skipped\n"), {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_two_ran)
    check("rg9 a run where some hooks executed counts THOSE and not the "
          "skipped one - the paired positive, since a counter that always "
          "answered zero would pass rg7 exactly as the repair does: %r"
          % (res["ranTotal"],),
          res["ranTotal"] == 2)
    lines = []
    check("rg10 ...and it renders GREEN, carrying the count so the reader "
          "sizes the verdict: %r" % (lines,),
          M.render(res, out=lines.append) == M.E_OK
          and "GATE GREEN" in "\n".join(lines)
          and "2 check(s) ran" in "\n".join(lines))

    # --- an unknown runner must not be guessed at -------------------------
    res = M.run_gate(tmp, [("test", "pytest -q")], runner=_quiet)
    check("rg11 a runner that does NOT report its step count yields None, "
          "never zero - guessing zero would refuse a passing gate and "
          "guessing one would bless a skipped one: %r" % (res["ranTotal"],),
          res["ranTotal"] is None)
    lines = []
    check("rg12 ...and that renders as not-knowable rather than as a number, "
          "so the limit is stated instead of filled in: %r" % (lines,),
          M.render(res, out=lines.append) == M.E_OK
          and "not knowable from this runner" in "\n".join(lines))

    # --- a failing gate, and both facts at once ---------------------------
    def _fail_and_rewrite(project, _command, _timeout=None):
        with open(os.path.join(project, "also.py"), "w") as fh:
            fh.write("x = 1\n")
        return 1, "Failed\n", {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_fail_and_rewrite)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg13 a gate that failed AND rewrote the tree says both - a reader "
          "who only fixed the failure would meet the rewrite next: %r"
          % (text[:100],),
          code == M.E_FAIL and "GATE RED" in text
          and "GATE MUTATED THE TREE" in text)
    os.remove(os.path.join(tmp, "also.py"))

    # --- git that cannot answer is UNKNOWN, not clean ---------------------
    notrepo = _harness.fixture_root("run-test-gate-norepo-")
    if True:
        res = M.run_gate(notrepo, [("lint", "true")], runner=_quiet)
        check("rg14 where git cannot describe the tree, mutation is UNKNOWN - "
              "and unknown is None, NOT an empty list. The empty list was the "
              "conflation: it reads as 'nothing changed' to every truthy test, "
              "so the third state survived only in the prose beside it: %r"
              % ((res["treeMutated"], res["treeBasis"]),),
              res["treeMutated"] is None
              and res["treeBasis"].startswith("git could not"))
        lines = []
        M.render(res, out=lines.append)
        check("rg15 ...and the basis is printed, so a green verdict over an "
              "unaskable tree carries its own limit",
              "git could not describe the tree" in "\n".join(lines))

    # --- F204: did the run touch anything the work declares? --------------
    # The third way a gate says nothing, after doing too much and doing nothing.
    # Measured live: a UI vitest suite, two files, nine tests, all green, against
    # a diff that was a one-value edit to a JSON manifest. Exit 0, a real
    # NON-ZERO count, and no relationship between what ran and what changed --
    # which is why `ranTotal` could not catch it and needed a fact of its own.
    #
    # REPORTED, NEVER REFUSED, and that was the operator's decision taken with
    # both options named. The overlap comes from paths a runner HAPPENS to print,
    # so it is a heuristic; a heuristic that refuses manufactures false refusals,
    # and the exit code deliberately does not read it.
    def _vitest_green(_project, _command, _timeout=None):
        return 0, ("\u2713 tools/ui-tests/panel.test.js (5 tests)\n"
                   "\u2713 tools/ui-tests/report.test.js (4 tests)\n"
                   "Test Files  2 passed (2)\n"), {}

    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=["docs/audit/audit-plan.json"])
    check("cv1 THE FAULT: a gate that RAN, passed, and named nothing the work "
          "owns is reported as exactly that - the count is non-zero, so the "
          "zero-check rule cannot see it: %r"
          % ((res["overlap"], res["coverageBasis"]),),
          res["failed"] == [] and res["overlap"] == []
          and "the runner named" in res["coverageBasis"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("cv2 ...printed with its basis, and NOT refused - exit stays 0, "
          "because refusing on a heuristic would make this script decide what a "
          "gate may be, which its own header declines: %r" % (text[-160:],),
          code == M.E_OK and "NO OVERLAP WITH THIS WORK" in text
          and "the runner named" in text)
    # THE PAIRED POSITIVE, and it is the half that matters: a renderer that
    # printed the warning unconditionally would pass cv1 and cv2 exactly as the
    # repair does.
    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=["tools/ui-tests/panel.test.js", "docs/plan.json"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("cv3 a run that DOES name a declared file says so instead, and names "
          "which - the warning is conditional, which a warning printed on every "
          "run would not be: %r" % ((res["overlap"], text[-120:]),),
          code == M.E_OK
          and res["overlap"] == ["tools/ui-tests/panel.test.js"]
          and "NO OVERLAP" not in text and "coverage: 1 declared file" in text)

    def _no_paths(_project, _command, _timeout=None):
        return 0, "OK\n9 tests passed\n", {}

    res = M.run_gate(tmp, [("test", "make check")], runner=_no_paths,
                     owns=["docs/audit/audit-plan.json"])
    lines = []
    M.render(res, out=lines.append)
    check("cv4 a runner that prints NO paths yields not-knowable, never 'no "
          "overlap' - `_porcelain`'s rule one question over, and the difference "
          "between a measurement and a claim: %r" % (res["coverageBasis"],),
          res["overlap"] is None
          and "not knowable from its output" in "\n".join(lines)
          and "NO OVERLAP" not in "\n".join(lines))
    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=[])
    check("cv5 ...and work declaring no files is the same answer for the other "
          "reason, said as itself: there is nothing to relate a run TO, which is "
          "not the same as a run that covered nothing: %r"
          % (res["coverageBasis"],),
          res["overlap"] is None and "declares no files" in res["coverageBasis"])
    check("cv6 `files_named` reads a path out of runner prose and leaves the "
          "words alone - a grammar that swallowed `Passed` or `2` would make "
          "every run overlap everything: %r"
          % (sorted(M.files_named("Passed\n  src/a.ts:12 ok\n2 files\n") or []),),
          M.files_named("Passed 9 tests ok") is None
          and "src/a.ts" in (M.files_named("  src/a.ts:12 ok") or set()))

    # --- what the manifest says the work owns -----------------------------
    check("cv7 the phase's declaration is the UNION of its tasks' files, "
          "de-duplicated - the phase gate is this script's actual call site, so "
          "asking only about a named task would be a flag with no caller: %r"
          % (M.owned_files(man, "P1"),),
          M.owned_files(man, "P1") == ([], None))
    _cvman = {"meta": {"version": 2},
              "phases": [{"id": "PA", "title": "a", "status": "in_progress",
                          "testGate": [], "tasks": [
                              {"id": "PA.1", "files": ["x.ts", "shared.ts"]},
                              {"id": "PA.2", "files": ["y.ts", "shared.ts"]}]}]}
    check("cv8 ...in manifest order and without a repeat, which is what makes "
          "the printed count a basis rather than a number: %r"
          % (M.owned_files(_cvman, "PA"),),
          M.owned_files(_cvman, "PA") == (["x.ts", "shared.ts", "y.ts"], None))
    check("cv9 ...and --task narrows it to that task alone",
          M.owned_files(_cvman, "PA", "PA.2") == (["y.ts", "shared.ts"], None))
    _cvnone, _cverr = M.owned_files(_cvman, "PA", "PA.9")
    check("cv10 ...while an unknown task is an ERROR rather than an empty "
          "declaration - 'this task owns nothing' and 'there is no such task' "
          "are two different answers, exactly as rg3 draws it for a phase: %r"
          % (_cverr,),
          _cvnone is None and "no task" in (_cverr or ""))

    # --- the empty gate is a designed state, not a pass -------------------
    mpath = os.path.join(tmp, "audit-plan.json")
    with open(mpath, "w") as fh:
        json.dump(man, fh)
    lines = []
    code = M.main([mpath, "P2", "--project-dir", tmp], out=lines.append)
    check("rg16 an EMPTY gate exits 0 and is reported AS the empty gate - "
          "`_phase_gate` documents it as a designed state, and printing "
          "'green' would claim a measurement nobody made: %r"
          % ("\n".join(lines)[:100],),
          code == M.E_OK and "EMPTY gate" in "\n".join(lines)
          and "GATE GREEN" not in "\n".join(lines))
    lines = []
    code = M.main([mpath, "P9", "--project-dir", tmp], out=lines.append)
    check("rg17 ...and a phase that does not exist is exit 2, the code for "
          "'could not be asked' rather than 'failed'",
          code == M.E_ASK and "no phase" in "\n".join(lines))

    # --- lifecycle: what did not finish, and what it cost ------------------
    # A timeout and a failure to START were ONE answer before this: `_shell`
    # swallowed both into `except Exception` and reported exit 127 for each, so
    # "the suite hung" and "the binary is missing" were the same row. They are
    # different repairs, so they are different words - and `lc2` is the pair that
    # says so, because either alone passes with the two collapsed.
    def _timed_out(_project, _command, timeout=None):
        return -9, "partial output\n", {"outcome": M.TIMED_OUT,
                                        "timeoutSeconds": timeout}

    def _cannot_run(_project, _command, _timeout=None):
        return 127, "could not run: no such file\n", {"outcome": M.CANNOT_RUN}

    res_t = M.run_gate(tmp, [("test", "pytest -q")], runner=_timed_out,
                       timeout=7)
    check("lc1 a step that did not finish is `timed-out`, not `failed` - a "
          "verdict was never reached, and spelling that as red would claim a "
          "measurement nobody completed: %r"
          % ((res_t.get("status"), res_t["steps"][0].get("outcome")),),
          res_t.get("status") == "timed-out"
          and res_t["steps"][0].get("outcome") == M.TIMED_OUT)

    res_c = M.run_gate(tmp, [("test", "pytest -q")], runner=_cannot_run)
    check("lc2 ...and a step that never STARTED is a third word again. The two "
          "are asserted as DIFFERENT rather than each against a literal, which "
          "is the half that fails while both are exit 127: %r vs %r"
          % (res_t.get("status"), res_c.get("status")),
          res_c.get("status") == "could-not-run"
          and res_c.get("status") != res_t.get("status"))

    check("lc3 the timeout that applied is recorded on the step, so `timed-out` "
          "carries the basis that makes it actionable rather than leaving a "
          "reader to guess which bound was hit: %r"
          % (res_t["steps"][0].get("timeoutSeconds"),),
          res_t["steps"][0].get("timeoutSeconds") == 7)

    def _fail_then_timeout(project, command, timeout=None):
        if "first" in command:
            return 1, "boom\n", {}
        return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}

    res_ft = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_fail_then_timeout)
    check("lc4 a run that FAILED and also timed out reads `failed` - a certain "
          "red must not be downgraded to an uncertain one - and the timeout "
          "survives on its own step, so neither fact is lost: %r"
          % ((res_ft.get("status"), [st.get("outcome") for st in res_ft["steps"]]),),
          res_ft.get("status") == "failed" and res_ft["failed"] == ["a"]
          and res_ft["steps"][1].get("outcome") == M.TIMED_OUT)

    check("lc5 ON A TIMEOUT THE TREE COMPARISON IS NOT MADE: `treeMutated` is "
          "None and the basis names the race, because a survivor of a torn-down "
          "group keeps writing. `_porcelain` already refuses to call an "
          "unanswerable tree clean; this is the same refusal one cause over: %r"
          % ((res_t.get("treeMutated"), res_t.get("treeBasis")),),
          res_t.get("treeMutated") is None
          and "interrupted" in (res_t.get("treeBasis") or ""))

    res_ok = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("lc6 ...and the pair that keeps that honest: a run that COMPLETED "
          "reports `treeMutated == []`, a list. Empty and None are the two "
          "readings a truthy test would merge, which is the whole reason the "
          "field is three-valued: %r" % (res_ok.get("treeMutated"),),
          res_ok.get("treeMutated") == []
          and res_ok.get("treeMutated") is not None)

    check("lc7 a completed run with every step at exit 0 is `passed`, and an "
          "unknowable check count does NOT make it `no-checks` - None is 'not "
          "knowable', and only a POSITIVE zero earns that word: %r"
          % ((res_ok.get("status"), res_ok["ranTotal"]),),
          res_ok.get("status") == "passed" and res_ok["ranTotal"] is None)

    res_zero = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                          runner=_all_skipped)
    check("lc8 ...while a count that is POSITIVELY zero is `no-checks`, which "
          "is the one status that is exit 0 and still not a verdict: %r"
          % ((res_zero.get("status"), res_zero["ranTotal"]),),
          res_zero.get("status") == "no-checks" and res_zero["ranTotal"] == 0)

    check("lc9 the run and every step carry a duration, as non-negative "
          "integers - `run_gate` measures around the seam, so a fixture runner "
          "needs to know nothing about time: %r"
          % ((res_ok.get("durationMs"), res_ok["steps"][0].get("durationMs")),),
          isinstance(res_ok.get("durationMs"), int)
          and res_ok.get("durationMs") >= 0
          and all(isinstance(st.get("durationMs"), int)
                  and st["durationMs"] >= 0 for st in res_ok["steps"]))

    # --- the REAL runner, against a real process tree ----------------------
    # The one case that cannot be written with a fixture: `subprocess.run`'s own
    # timeout kills the direct child, and with `shell=True` that child is the
    # shell. A backgrounded grandchild outlives it, keeps writing, and is exactly
    # what makes the after-snapshot a race. Proven by PID, not by prose.
    pidfile = os.path.join(tmp, "grandchild.pid")
    code, text, facts = M._shell(
        tmp, "sleep 30 & echo $! > %s; sleep 30" % (pidfile,), timeout=2)
    child_pid = None
    try:
        with open(pidfile) as fh:
            child_pid = int(fh.read().strip())
    except Exception:
        child_pid = None
    alive = None
    if child_pid:
        import time as _t
        _t.sleep(0.4)
        try:
            os.kill(child_pid, 0)
            alive = True
        except OSError:
            alive = False
        if alive:
            try:
                os.kill(child_pid, 9)
            except OSError:
                pass
    # The guard the mutation battery found, covered WITHOUT the suite ever
    # signalling its own group. An earlier case called the real `_tear_down` on a
    # same-group child; with the guard defeated that killpg reaches this runner,
    # so the suite DIED instead of going red - detection of the worst kind, since
    # a dead suite reads as infrastructure trouble. The decision and its use site
    # are covered separately below, and neither can take this process with it.
    plain = subprocess.Popen("sleep 30", shell=True, cwd=tmp,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    detached = subprocess.Popen("sleep 30", shell=True, cwd=tmp,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True)
    try:
        check("lc11 the predicate tells the two apart: a child of our own group "
              "WOULD signal us, one given its own session would not. Both ends "
              "asserted, because a predicate stuck at either constant is half "
              "right and wholly useless: same=%r detached=%r"
              % (M.shares_our_group(plain.pid), M.shares_our_group(detached.pid)),
              M.shares_our_group(plain.pid) is True
              and M.shares_our_group(detached.pid) is False)
        check("lc12 ...and an unanswerable pid is True, the SAFE direction: not "
              "knowing whether we would hit ourselves must never read as "
              "permission to aim at the group",
              M.shares_our_group(-1) is True)

        real = M.shares_our_group
        try:
            M.shares_our_group = lambda _pid: True
            narrow = M._tear_down(detached)
        finally:
            M.shares_our_group = real
        check("lc13 ...and `_tear_down` READS it: told the child shares our "
              "group, it takes the narrow kill and reports UNCONFIRMED, even "
              "though this child had a session of its own. The use site, "
              "covered by swapping the name rather than by signalling "
              "ourselves - `test__journal_io` uses the same seam: %r" % (narrow,),
              narrow is False and detached.returncode is not None)
    finally:
        for proc in (plain, detached):
            if proc.poll() is None:
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass

    check("lc10 THE FAULT: the real runner tears down the process GROUP, so a "
          "backgrounded grandchild does not outlive the timeout. "
          "`subprocess.run(timeout=)` kills the shell alone and leaves this pid "
          "running - and a survivor keeps writing into the tree the gate is "
          "about to describe: pid=%r alive_after=%r" % (child_pid, alive),
          facts.get("outcome") == M.TIMED_OUT
          and child_pid is not None and alive is False)
    if os.path.exists(pidfile):
        os.remove(pidfile)

    # --- the real runner's other two answers -------------------------------
    code, text, facts = M._shell(os.path.join(tmp, "no-such-dir"), "true")
    check("lc14 a command that could not be STARTED is `could-not-run` from the "
          "real runner, not only from a fixture - this is the Popen failure "
          "itself, and it is the half that never reaches a stub: %r"
          % ((code, facts.get("outcome")),),
          facts.get("outcome") == M.CANNOT_RUN and code == 127
          and "could not run" in text)

    code, text, facts = M._shell(tmp, "echo marker; sleep 30", timeout=2)
    check("lc15 ...and a timed-out step still returns what the child had "
          "already written. The drain runs AFTER the kill, never instead of it: "
          "a timed-out child is often blocked on a full pipe, so reading first "
          "would wait on a process nothing is going to stop: %r"
          % ((text.strip()[:24], facts.get("timeoutSeconds")),),
          facts.get("outcome") == M.TIMED_OUT and "marker" in text
          and facts.get("timeoutSeconds") == 2)

    res_127 = M.run_gate(tmp, [("x", "definitely-not-a-real-binary-xyz")])
    check("lc16 THE LIMIT, PINNED: a MISSING BINARY under `shell=True` is "
          "reported as a failure, not as `could-not-run`. The shell started "
          "fine and exited 127, and 127 is a code a real command may return - "
          "so reading the category out of the number would let a child claim "
          "one by exiting with it. The wrapper names only what IT observed: %r"
          % ((res_127["status"], res_127["steps"][0].get("outcome")),),
          res_127["status"] == "failed"
          and res_127["steps"][0].get("outcome") is None)


    # --- what state was actually tested ------------------------------------
    # `head` alone cannot answer this and never could: a TASK gate runs BEFORE the
    # task commit, so a run executes against HEAD plus staged edits plus unstaged
    # ones plus untracked files. Two failed retries at one HEAD were
    # indistinguishable, which defeats the point of recording retries at all.
    # The fixture had staged `tracked.txt` and never committed, so `rev-parse
    # HEAD` had nothing to answer with - and "the two runs share a head" would
    # then have been None == None, true with the field absent. One commit gives
    # the comparison something real to be about. Identity is passed per command
    # rather than written into the repo config, so the fixture keeps no state a
    # later case could read.
    subprocess.run(["git", "-C", tmp, "-c", "user.email=fixture@example.com",
                    "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "base"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    scope_a = os.path.join(tmp, "scope_a.py")
    owns = ["scope_a.py"]

    def _write(path, text):
        with open(path, "w") as fh:
            fh.write(text)

    _write(scope_a, "v = 1\n")
    r1 = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    _write(scope_a, "v = 2\n")
    r2 = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    st1, st2 = r1.get("testedState") or {}, r2.get("testedState") or {}
    check("ts1 THE REQUIREMENT: two runs at the SAME head against different "
          "declared content are told apart by `scopeDigest`. Asserted as a pair "
          "- the heads equal AND the digests differing - because either half "
          "alone passes with the field absent: head=%r digests differ=%r"
          % (st1.get("head") == st2.get("head"),
             st1.get("scopeDigest") != st2.get("scopeDigest")),
          st1.get("head") is not None
          and st1.get("head") == st2.get("head")
          and st1.get("scopeDigest") is not None
          and st1.get("scopeDigest") != st2.get("scopeDigest"))

    _write(scope_a, "v = 1\n")

    def _rewrites_scope(project, _command, _timeout=None):
        # `isort`/`black`'s shape again, but aimed at a file the work DECLARES.
        with open(os.path.join(project, "scope_a.py"), "w") as fh:
            fh.write("v = 999\n")
        return 0, "Passed\n", {}

    r_mut = M.run_gate(tmp, [("lint", "true")], runner=_rewrites_scope, owns=owns)
    r_post = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    st_mut, st_post = r_mut.get("testedState") or {}, r_post.get("testedState") or {}
    check("ts2 THE PLACEMENT: a gate that REWRITES a declared file leaves "
          "`scopeDigest` at the content it was asked to judge, not the content "
          "it produced. Taken before the first command for exactly this - a "
          "fix-in-place runner rewrites the files it checks, and a digest read "
          "afterwards would answer a different question than the one asked: "
          "pre==mut %r, post!=mut %r"
          % (st_mut.get("scopeDigest") == st1.get("scopeDigest"),
             st_post.get("scopeDigest") != st_mut.get("scopeDigest")),
          st_mut.get("scopeDigest") == st1.get("scopeDigest")
          and st_post.get("scopeDigest") != st_mut.get("scopeDigest"))

    _write(scope_a, "v = 1\n")
    r_before = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    stray = os.path.join(tmp, "stray_outside_scope.txt")
    _write(stray, "x\n")
    r_after = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    sb, sa = r_before.get("testedState") or {}, r_after.get("testedState") or {}
    check("ts3 a file appearing OUTSIDE the declared scope moves `dirtyDigest` "
          "while `scopeDigest` holds still - the two answer different questions "
          "and are asserted apart, since one field doing both would hide "
          "whichever it was not looking at: scope same=%r dirty differs=%r"
          % (sb.get("scopeDigest") == sa.get("scopeDigest"),
             sb.get("dirtyDigest") != sa.get("dirtyDigest")),
          sb.get("scopeDigest") == sa.get("scopeDigest")
          and sb.get("dirtyDigest") is not None
          and sb.get("dirtyDigest") != sa.get("dirtyDigest"))

    _write(stray, "x changed but still untracked\n")
    r_limit = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    sl = r_limit.get("testedState") or {}
    check("ts4 THE LIMIT, PINNED RATHER THAN HIDDEN: editing an ALREADY-DIRTY "
          "file outside the declared scope moves NEITHER digest. `dirtyDigest` "
          "records which paths were dirty, not their contents - so this evidence "
          "distinguishes the realistic retry and must never be sold as a "
          "reproducible snapshot of the repository: %r"
          % ((sl.get("scopeDigest") == sa.get("scopeDigest"),
              sl.get("dirtyDigest") == sa.get("dirtyDigest")),),
          sl.get("scopeDigest") is not None
          and sl.get("dirtyDigest") is not None
          and sl.get("scopeDigest") == sa.get("scopeDigest")
          and sl.get("dirtyDigest") == sa.get("dirtyDigest"))
    os.remove(stray)

    r_missing = M.run_gate(tmp, [("lint", "true")], runner=_quiet,
                           owns=["scope_a.py", "no_such_file.py"])
    sm = r_missing.get("testedState") or {}
    check("ts5 a declared file that is NOT THERE is hashed as null and counted "
          "in the basis - absent is itself evidence about the state under test, "
          "and dropping it would let two different scopes share a digest: %r"
          % (sm.get("scopeBasis"),),
          sm.get("scopeDigest") is not None
          and sm.get("scopeDigest") != st1.get("scopeDigest")
          and "1 missing" in (sm.get("scopeBasis") or ""))

    r_noscope = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=[])
    sn = r_noscope.get("testedState") or {}
    check("ts6 work that declares no files has no scope digest and SAYS so - "
          "the shape `coverage` already uses for the same question, because a "
          "digest of nothing would compare equal across every such run: %r"
          % ((sn.get("scopeDigest"), sn.get("scopeBasis")),),
          sn.get("scopeDigest") is None
          and "declares no files" in (sn.get("scopeBasis") or ""))

    r_norepo = M.run_gate(notrepo, [("lint", "true")], runner=_quiet, owns=owns)
    sr = r_norepo.get("testedState") or {}
    check("ts7 where git cannot describe the tree, `dirtyDigest` is None - not "
          "a hash of an empty set, which is a real digest that would compare "
          "equal to any other unanswerable run and read as agreement: %r"
          % ((sr.get("dirtyDigest"), sr.get("dirtyBasis")),),
          sr.get("dirtyDigest") is None
          and sr.get("head") is None
          and "git could not" in (sr.get("dirtyBasis") or "")
          and sr.get("scopeDigest") is not None)

    check("ts8 `head` carries the basis that says what it is NOT. It is the "
          "repository HEAD at execution time and it does not identify the "
          "tested state, because a task gate runs before the task commit - a "
          "field that claimed otherwise would be the overclaim this block "
          "exists to retire: %r" % (st1.get("headBasis"),),
          "does not identify the tested state" in (st1.get("headBasis") or ""))

    # --- whose gate is this, anyway ----------------------------------------
    # `--task` narrowed only the COVERAGE question before this: `gate_of` read
    # `phase.testGate` whatever it was handed, so a task declaring its own
    # `tests.gate` had no way to be run through this bracket at all. That is the
    # level every question the evidence has to answer actually lives at.
    gman = {"meta": {"version": 2,
                     "buildCommands": {"unit": "pytest -q tests/unit",
                                       "lint": "ruff check ."}},
            "phases": [{"id": "PG", "title": "g", "status": "in_progress",
                        "testGate": ["lint"], "tasks": [
                            {"id": "PG.1", "files": ["a.py"],
                             "tests": {"mode": "tdd", "gate": ["unit"]}},
                            {"id": "PG.2", "files": ["b.py"],
                             "tests": {"mode": "gate-only", "gate": []}},
                            {"id": "PG.3", "files": ["c.py"],
                             "tests": {"mode": "gate-only",
                                       "gate": ["echo literal-task"]}},
                            {"id": "PG.4", "files": ["d.py"]}]},
                       {"id": "PH", "title": "h", "status": "pending",
                        "testGate": [], "tasks": [
                            {"id": "PH.1", "files": ["e.py"],
                             "tests": {"mode": "tdd", "gate": ["unit"]}}]}]}

    cmds, source, err = M.gate_of(gman, "PG", "PG.1")
    check("gs1 a task that declares `tests.gate` is run through ITS commands, "
          "resolved by the same `meta.buildCommands` pass the phase gate uses - "
          "a second resolution would be a second answer to what a gate is: "
          "%r %r" % (cmds, source),
          err is None and source == "task"
          and cmds == [("unit", "pytest -q tests/unit")])

    cmds, source, err = M.gate_of(gman, "PG", "PG.2")
    check("gs2 ...and a task declaring an EMPTY gate falls back to the phase's, "
          "SAYING which it used. The fallback is the half that must not be "
          "silent: a phase gate measured against one task's files is a "
          "different claim from that task's own gate: %r %r" % (cmds, source),
          err is None and source == "phase"
          and cmds == [("lint", "ruff check .")])

    cmds4, source4, _e4 = M.gate_of(gman, "PG", "PG.4")
    check("gs3 ...and so does a task with no `tests` block at all - absent and "
          "empty are the same answer to 'does this task declare a gate', and "
          "they must not be two code paths: %r %r" % (cmds4, source4),
          source4 == "phase" and cmds4 == cmds)

    cmds3, source3, _e3 = M.gate_of(gman, "PG", "PG.3")
    check("gs4 a task gate entry naming no build command is carried VERBATIM, "
          "exactly as rg2 draws it for a phase - refusing it here would make "
          "this script decide what a task's gate may be: %r" % (cmds3,),
          source3 == "task" and cmds3 == [("echo literal-task",
                                           "echo literal-task")])

    cmdsh, sourceh, _eh = M.gate_of(gman, "PH", "PH.1")
    check("gs5 a task gate wins even where the PHASE declares nothing - the "
          "empty phase gate is a designed state for sign-off, not a veto over "
          "the task that ran under it: %r %r" % (cmdsh, sourceh),
          sourceh == "task" and cmdsh == [("unit", "pytest -q tests/unit")])

    _cn, _sn, errn = M.gate_of(gman, "PG", "PG.9")
    check("gs6 an unknown task is an ERROR, never a silent fall back to the "
          "phase - 'this task declares no gate' and 'there is no such task' are "
          "two different answers, the distinction rg3 already draws one noun "
          "up: %r" % (errn,),
          _cn is None and "no task" in (errn or ""))

    cmdsp, sourcep, _ep = M.gate_of(gman, "PG")
    check("gs7 ...and with no task named at all the answer is the phase's gate, "
          "unchanged - this is the call site the script has had all along and "
          "it must not move: %r %r" % (cmdsp, sourcep),
          sourcep == "phase" and cmdsp == [("lint", "ruff check .")])

    # --- which attempt, read off the plan ----------------------------------
    # EVERY TASK HERE RECORDS SOMETHING DIFFERENT, and the values are picked so a
    # wrong reading cannot land on the right answer: the phase's first task
    # records a count, so an implementation that answered the phase scope with
    # "the phase's first task" would return that number instead of nothing.
    aman = {"meta": {"version": 2},
            "phases": [{"id": "PA", "title": "a", "tasks": [
                {"id": "PA.1", "attempts": 3},
                {"id": "PA.2", "attempts": 0},
                {"id": "PA.3"},
                {"id": "PA.4", "attempts": True},
                {"id": "PA.5", "attempts": "2"}]}]}

    check("ao1 the attempt a run is stamped with comes from the task's own "
          "`attempts`, unchanged - this runner does not count the execution it "
          "is part of, because the orchestrator owns that number: %r"
          % (M.attempt_of(aman, "PA.1"),),
          M.attempt_of(aman, "PA.1") == 3)

    check("ao2 a recorded 0 travels as 0. The plan takes this count back down on "
          "a reverted increment and on a reset, so it is a value the plan WROTE "
          "and reading it as one attempt would report a run the plan denies: %r"
          % (M.attempt_of(aman, "PA.2"),),
          M.attempt_of(aman, "PA.2") == 0
          and M.attempt_of(aman, "PA.2") is not None)

    check("ao3 a task that records NO attempts answers None, which the row "
          "spells as an absent field - 'the plan does not say how many times "
          "this ran' has no number, and any number here would be invented: %r"
          % (M.attempt_of(aman, "PA.3"),),
          M.attempt_of(aman, "PA.3") is None)

    check("ao4 a PHASE-scope run answers None even where the phase's tasks each "
          "record a count. `attempts` is a task field, so there is nothing to "
          "read and nothing to borrow from a neighbour: %r"
          % (M.attempt_of(aman, None),),
          M.attempt_of(aman, None) is None)

    check("ao5 `attempts: true` and `attempts: \"2\"` record nothing either - "
          "`True` is an `int` in Python, so a plan carrying it would otherwise "
          "read as one attempt: %r"
          % ((M.attempt_of(aman, "PA.4"), M.attempt_of(aman, "PA.5")),),
          M.attempt_of(aman, "PA.4") is None
          and M.attempt_of(aman, "PA.5") is None)

    check("ao6 a task this manifest does not carry answers None rather than "
          "raising - `gate_of` and `owned_files` have already refused an unknown "
          "id by the time a row is being assembled, and a recorder that raised "
          "here would lose a run that DID happen: %r"
          % (M.attempt_of(aman, "PA.9"),),
          M.attempt_of(aman, "PA.9") is None)

    # --- the measurement boundary, end to end ------------------------------
    # THE HEADLINE OF THE RECORDING CHANGE. The evidence file, the journal and the
    # manifest all live INSIDE the repository this run has just described with
    # `git status --porcelain`. A write above the post-run snapshot would appear
    # in the very comparison it is being judged by, and the gate would report
    # itself as having rewritten the tree.
    recroot = _harness.fixture_root("run-test-gate-record-")
    os.makedirs(os.path.join(recroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(recroot, ".claude"))
    with open(os.path.join(recroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    rmpath = os.path.join(recroot, "docs", "audit", "audit-plan.json")
    with open(rmpath, "w") as fh:
        json.dump({"meta": {"version": 3, "buildCommands": {"ok": "true"}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    rshard = os.path.join(recroot, "docs", "audit", "phases", "P1.json")
    # THE THREE TASKS ARE THE THREE ANSWERS `attempts` HAS, and the values are
    # chosen so a wrong implementation cannot produce them: P1.2 records TWO, so
    # the `or 1` shape reads 1 and disagrees; P1.3 records ZERO, which is a value
    # the plan wrote and not a gap; P1.1 records nothing at all, which no number
    # may stand in for.
    with open(rshard, "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["ok"], "tasks": [
                       {"id": "P1.1", "title": "t", "status": "in_progress",
                        "files": []},
                       {"id": "P1.2", "title": "retried", "status": "in_progress",
                        "attempts": 2, "files": []},
                       {"id": "P1.3", "title": "reset", "status": "pending",
                        "attempts": 0, "files": []}]}, fh)
    subprocess.run(["git", "init", "-q", recroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # AND THE FIXTURE IS COMMITTED, which is load-bearing here rather than tidy
    # (F223). `git status --porcelain` collapses an UNTRACKED directory to one
    # `?? docs/` line, so on an uncommitted fixture a write into
    # `docs/audit/audit-plan.json` inside the measurement window changes no
    # porcelain line at all: rc1's `"MUTATED" not in text` clause then has
    # nothing to compare and the case stands on its exit code alone, which is
    # green whatever the placement. Measured both ways with a recording write
    # injected between the two snapshots - uncommitted rc1 stayed GREEN, and on
    # this committed fixture it goes red naming the write.
    for arg in (["add", "--", "docs", ".claude"],
                ["-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", recroot] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    lines = []
    code = M.main([rmpath, "P1", "--project-dir", recroot, "--record"],
                  out=lines.append)
    text = "\n".join(lines)
    shard_after = json.loads(open(rshard).read())
    ev_files = os.listdir(os.path.join(recroot, "docs", "audit", "evidence"))
    check("rc1 THE BOUNDARY: recording writes the row, the journal and the "
          "pointer during this invocation, and the gate still reports the tree "
          "UNCHANGED. Move any of those writes above the post-run snapshot and "
          "the runner accuses itself of the rewrite it exists to catch: exit=%r "
          "green=%r" % (code, "GATE GREEN" in text),
          code == M.E_OK and "GATE GREEN" in text
          and "MUTATED" not in text and len(ev_files) == 1)

    check("rc2 ...and the pointer landed on the phase, naming the run just "
          "recorded - the two halves are asserted together because a recorded "
          "run nothing points at and a pointer at no run are both half-done: %r"
          % (shard_after.get("testEvidence"),),
          shard_after.get("testEvidence", {}).get("status") == "passed"
          and shard_after["testEvidence"]["runId"] in text)

    lines = []
    code = M.main([rmpath, "P1", "--project-dir", recroot, "--reconcile"],
                  out=lines.append)
    check("rc3 reconcile over an already-correct plan moves nothing, says so, "
          "and exits 0 - the repair a refused pointer names has to be safe to "
          "run when nothing is wrong, or nobody will run it: %r"
          % ("\n".join(lines)[:90],),
          code == M.E_OK and "already:" in "\n".join(lines)
          and "moved:" not in "\n".join(lines))

    # --- which attempt the run was, end to end -----------------------------
    # THE FIELD HAD NO WRITER. `_evidence_io.row_for` has always copied `attempt`
    # out of the identity and both renderers have always shown it, while the only
    # thing that ever set it was the demo generator - so every row a user could
    # produce left the column blank and the demo advertised a capability the
    # product did not have. These cases are driven through `main` for that reason:
    # what was missing was the WIRING, and a case against the helper alone would
    # have passed on the broken build.
    evdir = os.path.join(recroot, "docs", "audit", "evidence")
    two = []
    code_two = M.main([rmpath, "P1", "--task", "P1.2", "--project-dir", recroot,
                       "--record"], out=two.append)
    row_two = _recorded_rows(evdir)[-1]
    check("at1 a task whose plan RECORDS attempts stamps that number on the row, "
          "beside the `via` no real run could carry it with before: exit=%r %r"
          % (code_two, (row_two.get("taskId"), row_two.get("attempt"),
                        row_two.get("via"))),
          code_two == M.E_OK and row_two.get("taskId") == "P1.2"
          and row_two.get("attempt") == 2 and row_two.get("via") == "cli")

    zero = []
    M.main([rmpath, "P1", "--task", "P1.3", "--project-dir", recroot,
            "--record"], out=zero.append)
    row_zero = _recorded_rows(evdir)[-1]
    check("at2 a RECORDED zero is a value and is written as one - the plan takes "
          "this count back down on a reverted increment and on a reset, so a row "
          "reading it as 'surely at least one' would report an attempt the plan "
          "says never happened: %r"
          % (("attempt" in row_zero, row_zero.get("attempt")),),
          row_zero.get("taskId") == "P1.3" and "attempt" in row_zero
          and row_zero["attempt"] == 0)

    none = []
    M.main([rmpath, "P1", "--task", "P1.1", "--project-dir", recroot,
            "--record"], out=none.append)
    row_none = _recorded_rows(evdir)[-1]
    check("at3 a task whose plan records NO attempts leaves the field off the "
          "row entirely. Absent means 'the plan does not say how many times this "
          "ran', and a 0 or a 1 invented here would be a claim with no basis - "
          "the failure the whole record exists to prevent: %r" % (sorted(row_none),),
          row_none.get("taskId") == "P1.1" and "attempt" not in row_none)

    check("at4 ...and a PHASE-scope run carries no attempt either, which is the "
          "plan being read correctly rather than a gap: `attempts` is a task "
          "field, so a phase has none to report: %r"
          % (sorted(_recorded_rows(evdir)[0]),),
          _recorded_rows(evdir)[0].get("scope") == "phase"
          and "attempt" not in _recorded_rows(evdir)[0])

    # --- the evidence boundary, end to end ---------------------------------
    # THE MID-FLIGHT ADOPTER'S SHAPE, built rather than described: a plan with no
    # `meta.evidenceSince` and an empty ledger, which is every repository the day
    # it upgrades. A FRESH fixture, never `recroot`: that one has recorded runs
    # by now, so a boundary case against it would be reading somebody else's
    # first run as its own.
    bdroot = _harness.fixture_root("run-test-gate-boundary-")
    os.makedirs(os.path.join(bdroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(bdroot, ".claude"))
    with open(os.path.join(bdroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    bdpath = os.path.join(bdroot, "docs", "audit", "audit-plan.json")
    with open(bdpath, "w") as fh:
        json.dump({"meta": {"version": 3, "buildCommands": {"ok": "true"}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    with open(os.path.join(bdroot, "docs", "audit", "phases", "P1.json"), "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["ok"], "tasks": [
                       {"id": "P1.1", "title": "t", "status": "in_progress",
                        "files": []}]}, fh)
    subprocess.run(["git", "init", "-q", bdroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # AND THE FIXTURE IS COMMITTED, for the reason spelled out at `recroot`'s
    # own commit above: an uncommitted fixture is one `?? docs/` line, so a write
    # inside the measurement window moves no porcelain line and bd2 could never
    # go red.
    for arg in (["add", "-A"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", bdroot] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bd_before = json.loads(open(bdpath).read())["meta"]

    bd1_lines = []
    bd1_code = M.main([bdpath, "P1", "--project-dir", bdroot, "--record"],
                      out=bd1_lines.append)
    bd1_text = "\n".join(bd1_lines)
    bd_meta = json.loads(open(bdpath).read())["meta"]
    bd_row = _recorded_rows(os.path.join(bdroot, "docs", "audit", "evidence"))[0]
    check("bd1 a plan with no boundary and no ledger gets one from its FIRST "
          "recorded run: the key names that run, dates it from that run's own "
          "stamp, and carries the sentence that licenses it. Before this, "
          "`no-test-evidence` had no setting for a plan adopted mid-flight - "
          "every task finished before the recorder existed failed a condition "
          "it could not have passed: %r -> %r" % (bd_before, bd_meta.get("evidenceSince")),
          bd1_code == M.E_OK and "evidenceSince" not in bd_before
          and (bd_meta.get("evidenceSince") or {}).get("at") == bd_row["ts"]
          and (bd_meta.get("evidenceSince") or {}).get("runId") == bd_row["runId"]
          and str((bd_meta.get("evidenceSince") or {}).get("basis") or "").strip() != ""
          and "boundary: recording began" in bd1_text)

    check("bd2 ...and the gate STILL reports the tree unchanged, which is the "
          "same boundary rc1 pins one write over: this one touches the INDEX, "
          "the file the run has just described with `git status --porcelain`. "
          "Move it above the post-run snapshot and the runner accuses itself of "
          "the rewrite it exists to catch: green=%r" % ("GATE GREEN" in bd1_text,),
          "GATE GREEN" in bd1_text and "MUTATED" not in bd1_text)

    bd_j = [r for r in _journal_io.read_all(bdroot)
            if r.get("action") == "meta.evidenceSince"]
    check("bd3 the stamp is anchored in the hash chain by a row of its own, "
          "naming both ends. A DETAIL on the row that anchors the RUN would not "
          "do: that row is written before the plan is touched and stays true "
          "whatever happens to it, so hanging a plan-movement claim on it would "
          "put a transition in the chain that had not happened yet: %r"
          % (bd_j[0]["details"] if bd_j else None,),
          len(bd_j) == 1 and bd_j[0]["details"]["field"] == "evidenceSince"
          and bd_j[0]["details"]["from"] is None
          and bd_j[0]["details"]["to"] == (bd_meta.get("evidenceSince") or {}).get("at")
          and bd_j[0]["details"]["runId"] == bd_row["runId"])

    bd2_lines = []
    M.main([bdpath, "P1", "--project-dir", bdroot, "--record"],
           out=bd2_lines.append)
    bd_meta2 = json.loads(open(bdpath).read())["meta"]
    bd_j2 = [r for r in _journal_io.read_all(bdroot)
             if r.get("action") == "meta.evidenceSince"]
    check("bd4 a SECOND recorded run does not move it, says the plan already "
          "states it, and draws no second row. THE ROW COUNT IS THE SEPARATOR "
          "here and the value is not: a writer that re-derived on every run "
          "would compute the same earliest stamp and leave the block looking "
          "untouched, while quietly asserting a transition in the chain each "
          "time (eb19 is where the VALUE tells them apart): %r"
          % (bd_meta2.get("evidenceSince"),),
          bd_meta2.get("evidenceSince") == bd_meta.get("evidenceSince")
          and bd_meta2.get("evidenceSince") is not None and len(bd_j2) == 1
          and "already stated by the plan" in "\n".join(bd2_lines)
          and len(_recorded_rows(os.path.join(bdroot, "docs", "audit",
                                              "evidence"))) == 2)

    # --- a run that was STOPPED, not answered ------------------------------
    # `cancelled` was a `testEvidence.status` member with NO WRITER: it sat in the
    # schema enum, in both renderers and in two documents listing what gets
    # written, while `run_status` could answer only the four words around it. The
    # cost was not cosmetic - the negative-evidence policy's fourth commit point,
    # the sweep at `/audit:resume`, existed to make an interrupted run durable and
    # had nothing to sweep, because the local write it was meant to sweep was
    # never built.
    def _interrupt_second(_project, command, _timeout=None):
        if "first" in command:
            return 0, "all good\n", {}
        raise KeyboardInterrupt("SIGTERM")

    res_i = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                       runner=_interrupt_second)
    check("ic1 a run a stop signal cut short is `cancelled`, and it carries the "
          "steps that FINISHED and no others - the step that was in flight "
          "reported nothing, so a row for it would be an invented entry in the "
          "one record that exists to be true: %r"
          % ((res_i.get("status"), [st["name"] for st in res_i["steps"]],
              res_i.get("cancelledBy")),),
          res_i.get("status") == M.CANCELLED
          and [st["name"] for st in res_i["steps"]] == ["a"]
          and res_i.get("cancelledBy") == "SIGTERM")

    def _fail_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 1, "boom\n", {}
        raise KeyboardInterrupt("SIGINT")

    res_fi = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_fail_then_interrupt)
    check("ic2 THE PRECEDENCE DECISION: a run whose first step FAILED and whose "
          "second was interrupted reads `failed`. A signal does not retract a "
          "measurement that already completed, and spelling a certain red "
          "`cancelled` would downgrade a finding a reader can act on into one "
          "they have to reproduce - the same rule lc4 pins for a timeout. Both "
          "facts survive, one level down: %r"
          % ((res_fi.get("status"), res_fi.get("failed"),
              res_fi.get("cancelledBy")),),
          res_fi.get("status") == "failed" and res_fi.get("failed") == ["a"]
          and res_fi.get("cancelledBy") == "SIGINT")

    def _timeout_then_interrupt(_project, command, timeout=None):
        if "first" in command:
            return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}
        raise KeyboardInterrupt("SIGINT")

    res_ti = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_timeout_then_interrupt)
    check("ic3 ...and a step that TIMED OUT outranks the interrupt too, one "
          "step weaker and for the same reason: a timeout is a finding with a "
          "repair attached (raise the bound, or fix the hang), and `cancelled` "
          "names none - it is a fact about the operator, not about the work: %r"
          % ((res_ti.get("status"), res_ti.get("cancelledBy")),),
          res_ti.get("status") == M.TIMED_OUT
          and res_ti.get("cancelledBy") == "SIGINT")

    def _cannot_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 127, "could not run: no such file\n", {"outcome": M.CANNOT_RUN}
        raise KeyboardInterrupt("SIGINT")

    res_ci = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_cannot_then_interrupt)
    check("ic4 ...and so does a runner that never STARTED, which points at "
          "`meta.buildCommands` and at not burning a retry. Every word that "
          "names a repair sits above the one that names none: %r"
          % ((res_ci.get("status"), res_ci.get("cancelledBy")),),
          res_ci.get("status") == M.CANNOT_RUN
          and res_ci.get("cancelledBy") == "SIGINT")

    def _skipped_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 0, ("check yaml.....................Skipped\n"
                       "black.........................Skipped\n"), {}
        raise KeyboardInterrupt("SIGINT")

    res_zi = M.run_gate(tmp, [("a", "pre-commit run --files first.md"),
                              ("b", "second")], runner=_skipped_then_interrupt)
    check("ic5 THE OTHER END OF THAT PRECEDENCE: a completed step reporting "
          "positively zero checks does NOT make an interrupted run `no-checks`. "
          "A zero taken over a TRUNCATED run is not the 'the gate ran and "
          "skipped everything' claim that word makes, and reading it as one "
          "would sign off a gate that never finished: %r"
          % ((res_zi.get("status"), res_zi.get("ranTotal")),),
          res_zi.get("status") == M.CANCELLED and res_zi["ranTotal"] == 0)

    res_ni = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("ic6 SECOND DIRECTION, and it is the case that looks vacuous: a run "
          "NOTHING stopped reports `cancelledBy` None and a real tree "
          "comparison. It passes on the build that has no interrupt path at "
          "all, and it is the only case that fails when the interrupt arm "
          "becomes unconditional: %r"
          % ((res_ni.get("cancelledBy"), res_ni.get("status"),
              res_ni.get("treeMutated")),),
          res_ni.get("cancelledBy") is None
          and res_ni.get("status") == "passed"
          and res_ni.get("treeMutated") == [])

    check("ic7 ON AN INTERRUPT THE TREE COMPARISON IS NOT MADE EITHER, and the "
          "value is None and not `[]`. `[]` is the one value that means KNOWN "
          "CLEAN, and a killed child may still have been writing - this "
          "repository has conflated null with empty three times and this is the "
          "fourth place it could have: %r"
          % ((res_i.get("treeMutated"), res_i.get("treeBasis")),),
          res_i.get("treeMutated") is None and res_i.get("treeMutated") != []
          and "interrupted" in (res_i.get("treeBasis") or ""))

    def _interrupt_unnamed(_project, _command, _timeout=None):
        raise KeyboardInterrupt()

    res_un = M.run_gate(tmp, [("a", "first")], runner=_interrupt_unnamed)
    check("ic8 an interrupt carrying no name still says so rather than writing "
          "`cancelled` with nothing beside it. `run_gate` is a library function, "
          "so a caller that never armed the handlers meets Python's own bare "
          "KeyboardInterrupt - and a status whose basis is missing must say THAT "
          "is what is missing: %r" % (res_un.get("cancelledBy"),),
          res_un.get("status") == M.CANCELLED
          and res_un.get("cancelledBy") == M.UNNAMED_SIGNAL)

    check("ic9 ...and that run has NO steps at all, which is where the status "
          "has to come from `cancelledBy` rather than from a step's `outcome`: "
          "an interrupt lands on this process, not on one command, so there is "
          "nothing for it to hang off: %r" % (res_un.get("steps"),),
          res_un.get("steps") == [])

    def _explodes(_project, _command, _timeout=None):
        raise MemoryError("not an interrupt")

    _ok_mem, _mem = _harness.attempt(M.run_gate, tmp, [("a", "first")],
                                     runner=_explodes)
    check("ic10 ...and something that is NOT an interrupt still escapes. The "
          "catch is `KeyboardInterrupt` and not `BaseException` on purpose: "
          "`_shell`'s wide arm is doing TEARDOWN, which every escape owes, while "
          "this one assigns a MEANING, and calling a MemoryError `cancelled` "
          "would be the silent mislabel the rest of this file exists to end: %r"
          % (_mem,),
          _ok_mem is False and "MemoryError" in str(_mem))

    rl = []
    code_i = M.render(res_i, out=rl.append)
    rtext = "\n".join(rl)
    check("ic11 render REFUSES a cancelled run, and the refusal is the point: "
          "with no failed step and no mutation this run is exit 0 everywhere "
          "else, so a missing arm here spells a stopped gate GREEN: exit=%r %r"
          % (code_i, rtext[:60]),
          code_i == M.E_FAIL and "GATE CANCELLED" in rtext
          and "GATE GREEN" not in rtext and "SIGTERM" in rtext)

    check("ic12 ...and it says the row is written locally and committed by "
          "nobody. Git belongs to the orchestrator: a commit made while stopping "
          "is a half-made one nobody reviewed, on the one path where nobody is "
          "going to look - so the sentence names the sweep that makes it durable "
          "instead: %r" % (rtext[-90:],),
          "committed by nobody" in rtext and "commit-audit-state.py" in rtext
          and "/audit:resume" in rtext)

    rl2 = []
    M.render(res_fi, out=rl2.append)
    check("ic13 ...and a run that FAILED and was also stopped prints BOTH "
          "sentences, from the fact rather than from the status word. "
          "Precedence gives `failed` the one word; a reader who saw only that "
          "would believe the remaining steps had their say: %r"
          % ("\n".join(rl2)[:70],),
          "GATE RED" in "\n".join(rl2) and "GATE CANCELLED" in "\n".join(rl2))

    # --- the handlers that make a signal reachable at all ------------------
    # `_spawn_kwargs` detaches every step into a session of its own, so a
    # terminal's Ctrl-C arrives HERE and at nothing else - its docstring has named
    # "the handler in `main`" as the other half of that trade since before one
    # existed. SIGTERM had no default that could stand in: with no handler the
    # interpreter dies, the detached group outlives it, and the run leaves neither
    # a record nor a stopped child.
    def _fires(handler, sig):
        """What the installed handler raises, as a word.

        NOT `_harness.attempt`: that catches `Exception`, and the whole point of
        raising a `KeyboardInterrupt` is that it is a `BaseException` and travels
        past every such arm between the handler and `run_gate`. Caught here by the
        name the production code catches it by.
        """
        try:
            handler(sig, None)
        except KeyboardInterrupt as exc:
            return str(exc)
        return "no interrupt raised"

    before_int = signal.getsignal(signal.SIGINT)
    before_term = signal.getsignal(signal.SIGTERM)
    armed = M._arm_interrupt()
    try:
        during_int = signal.getsignal(signal.SIGINT)
        during_term = signal.getsignal(signal.SIGTERM)
        _raised_i = _fires(during_int, signal.SIGINT)
        _raised_t = _fires(during_term, signal.SIGTERM)
    finally:
        M._disarm_interrupt(armed)
    check("ia1 arming installs a handler for each stop signal and disarming puts "
          "back exactly what it displaced - `main` is a function the suites drive "
          "many times in one process, so a handler left behind outlives its run: "
          "%r" % ((during_int is not before_int,
                   signal.getsignal(signal.SIGINT) is before_int),),
          during_int is not before_int and during_term is not before_term
          and signal.getsignal(signal.SIGINT) is before_int
          and signal.getsignal(signal.SIGTERM) is before_term)

    check("ia2 ...and each handler raises an interrupt NAMING its own signal. "
          "Both ends are asserted because a handler stuck on one word is half "
          "right and wholly useless - the name is the whole of a cancelled row's "
          "basis: %r vs %r" % (_raised_i, _raised_t),
          _raised_i == "SIGINT" and _raised_t == "SIGTERM")

    M._disarm_interrupt([(signal.SIGTERM, None)])
    restored = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, before_term)
    check("ia3 a displaced handler of None is restored as the DEFAULT rather "
          "than handed back: None is what `getsignal` answers for a handler that "
          "was not set from Python, and `signal.signal(sig, None)` is a "
          "TypeError - which would take the whole run down inside a `finally`: %r"
          % (restored,),
          restored == signal.SIG_DFL)

    # --- a REAL signal, through a real process tree -------------------------
    # THE CASE THAT CANNOT BE WRITTEN WITH A FIXTURE. Every case above drives the
    # `runner` seam, which proves the decision and nothing about delivery: whether
    # a signal sent to this program actually reaches `run_gate` as an interrupt,
    # whether the detached group dies with it, and whether the row lands. So this
    # one spawns the script, waits until a step is genuinely running, and signals
    # it.
    sigroot = _harness.fixture_root("run-test-gate-signal-")
    os.makedirs(os.path.join(sigroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(sigroot, ".claude"))
    with open(os.path.join(sigroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    # The marker carries the GRANDCHILD's pid, so the case can wait for the step
    # to be genuinely under way instead of sleeping and hoping, and can then ask
    # whether the interrupt took the whole group with it.
    marker = os.path.join(sigroot, "grandchild.pid")
    slow = "sleep 45 & echo $! > '%s'; wait" % (marker,)
    smpath = os.path.join(sigroot, "docs", "audit", "audit-plan.json")
    with open(smpath, "w") as fh:
        json.dump({"meta": {"version": 3,
                            "buildCommands": {"quick": "true", "slow": slow}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    with open(os.path.join(sigroot, "docs", "audit", "phases", "P1.json"),
              "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["quick", "slow"],
                   "tasks": [{"id": "P1.1", "title": "t",
                              "status": "in_progress", "files": []}]}, fh)
    subprocess.run(["git", "init", "-q", sigroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", sigroot, "add", "--", "docs", ".claude"],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", sigroot, "-c", "user.email=fixture@example.com",
                    "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "base"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    head_before = subprocess.run(["git", "-C", sigroot, "rev-parse", "HEAD"],
                                 stdout=subprocess.PIPE).stdout.decode().strip()

    child = subprocess.Popen(
        [sys.executable, _loader.script_path("run-test-gate.py"),
         smpath, "P1", "--project-dir", sigroot, "--record"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True)
    grandchild, waited = None, 0.0
    while waited < 40.0:
        try:
            with open(marker) as fh:
                grandchild = int(fh.read().strip())
            break
        except Exception:
            # Bounded, and the failure is REPORTED rather than skipped: a marker
            # that never arrives leaves `grandchild` None and every case below
            # goes red naming it.
            time.sleep(0.05)
            waited += 0.05
    if grandchild is not None:
        os.kill(child.pid, signal.SIGINT)
    else:
        child.kill()
    child_out = (child.communicate(timeout=90)[0] or b"").decode("utf-8",
                                                                 "replace")
    alive = None
    if grandchild is not None:
        time.sleep(0.4)
        try:
            os.kill(grandchild, 0)
            alive = True
        except OSError:
            alive = False
        if alive:
            _harness.attempt(os.kill, grandchild, 9)
    sig_rows = _recorded_rows(os.path.join(sigroot, "docs", "audit", "evidence"))
    sig_row = sig_rows[-1] if sig_rows else {}

    check("is1 A REAL SIGINT, SENT TO A REAL RUN MID-STEP, LANDS A ROW: the "
          "signal reaches `run_gate` as an interrupt, the run is recorded as "
          "`cancelled`, and before this an interrupted run left no record at all "
          "- which made the /audit:resume sweep a sweep with nothing to sweep: "
          "rows=%r %r" % (len(sig_rows), sig_row.get("status")),
          len(sig_rows) == 1 and sig_row.get("status") == M.CANCELLED
          and sig_row.get("cancelledBy") == "SIGINT")

    check("is2 ...and the row carries the step that FINISHED and not the one the "
          "signal cut off. The list is short because the run was short, which is "
          "the difference between a record and a reconstruction: %r"
          % ([st.get("name") for st in (sig_row.get("steps") or [])],),
          [st.get("name") for st in (sig_row.get("steps") or [])] == ["quick"])

    check("is3 ...with `treeMutated` null and the basis naming the race. A "
          "torn-down group may still have been writing, so `[]` - the one value "
          "that means KNOWN CLEAN - would be a claim nobody measured: %r"
          % ((sig_row.get("treeMutated"),
              (sig_row.get("observations") or {}).get("treeBasis")),),
          sig_row.get("treeMutated") is None
          and "interrupted" in str((sig_row.get("observations")
                                    or {}).get("treeBasis")))

    check("is4 ...and the detached group went with it: the grandchild the step "
          "backgrounded is DEAD. A survivor keeps writing into the tree this "
          "record describes, which is the state in which every answer here is a "
          "guess: pid=%r alive_after=%r" % (grandchild, alive),
          grandchild is not None and alive is False)

    check("is5 ...the process exits the code a stopped gate earns and SAYS it "
          "was cancelled, rather than dying with a traceback and no verdict: "
          "exit=%r %r" % (child.returncode, child_out[-70:]),
          child.returncode == M.E_FAIL and "GATE CANCELLED" in child_out
          and "GATE GREEN" not in child_out)

    head_after = subprocess.run(["git", "-C", sigroot, "rev-parse", "HEAD"],
                                stdout=subprocess.PIPE).stdout.decode().strip()
    porcelain = subprocess.run(["git", "-C", sigroot, "status", "--porcelain"],
                               stdout=subprocess.PIPE).stdout.decode()
    check("is6 AND NOTHING WAS COMMITTED. The interrupt path writes and returns; "
          "HEAD has not moved and the row is sitting in the working tree, which "
          "is exactly the state `commit-audit-state.py` sweeps at the next "
          "/audit:resume. A commit made while stopping is the half-made one "
          "nobody reviews: %r" % (head_after == head_before,),
          head_after == head_before and head_before
          and "docs/audit/evidence" in porcelain)

    shard_sig = json.loads(open(os.path.join(sigroot, "docs", "audit",
                                             "phases", "P1.json")).read())
    check("is7 ...while the PLAN did catch up locally: the pointer names the "
          "cancelled run, so `/audit:status` refuses sign-off on it rather than "
          "reading an absent pointer as nothing having happened: %r"
          % (shard_sig.get("testEvidence"),),
          (shard_sig.get("testEvidence") or {}).get("status") == M.CANCELLED
          and (shard_sig.get("testEvidence") or {}).get("runId")
          == sig_row.get("runId"))

def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_run_test_gate.py --selftest\n")
    raise SystemExit(2)
