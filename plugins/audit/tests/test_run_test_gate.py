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
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve by basename)

M = _loader.load_script("run-test-gate.py", "rtg")


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
    cmds, err = M.gate_of(man, "P1")
    check("rg1 the gate resolves each entry through meta.buildCommands, "
          "because a second resolution here would be a second answer to "
          "'what is this phase's gate': %r" % (cmds,),
          err is None
          and cmds == [("lint", "pre-commit run --all-files"),
                       ("test", "pytest -q")])
    cmds3, _e3 = M.gate_of(man, "P3")
    check("rg2 ...and an entry naming no build command is carried VERBATIM - "
          "it may be a literal shell command, and refusing it would make this "
          "script decide what a gate is allowed to be: %r" % (cmds3,),
          cmds3 == [("echo literal", "echo literal")])
    _none, err_none = M.gate_of(man, "P9")
    check("rg3 an unknown phase is an error rather than an empty gate - "
          "'this phase has no gate' and 'there is no such phase' are two "
          "different answers: %r" % (err_none,),
          _none is None and "no phase" in (err_none or ""))

    # --- the mutation bracket, against a REAL repository -------------------
    def _quiet(_project, _command):
        return 0, "all good\n"

    res = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("rg4 a gate that changes nothing reports no mutation, and the basis "
          "says git was actually asked: %r"
          % ((res["mutated"], res["treeBasis"]),),
          res["mutated"] == [] and res["failed"] == []
          and res["treeBasis"].startswith("git described"))

    def _fix_in_place(project, _command):
        # `isort`/`black`'s shape: it rewrites and then reports success.
        with open(os.path.join(project, "rewritten.py"), "w") as fh:
            fh.write("import os\n")
        return 0, "Passed\n"

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_fix_in_place)
    check("rg5 THE FAULT: a gate that passed BECAUSE it rewrote the tree is "
          "caught, with the file named - exit 0 said nothing was wrong and "
          "five source files had changed: %r" % (res["mutated"],),
          res["failed"] == []
          and any("rewritten.py" in line for line in res["mutated"]))
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
    def _all_skipped(_project, _command):
        return 0, ("check yaml.....................Skipped\n"
                   "black.........................Skipped\n")

    res = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                     runner=_all_skipped)
    check("rg7 THE OTHER FAULT: a gate where every hook SKIPPED is exit 0 "
          "with zero checks, and the count is read rather than assumed: %r"
          % (res["ranTotal"],),
          res["failed"] == [] and res["mutated"] == []
          and res["ranTotal"] == 0)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg8 ...and that is REFUSED too, said as what it is: a gate that "
          "skipped everything and a gate that verified everything are the "
          "same exit code: %r" % (text[:110],),
          code == M.E_FAIL and "NO CHECK RAN" in text)

    def _two_ran(_project, _command):
        return 0, ("check yaml.....................Passed\n"
                   "black.........................Passed\n"
                   "mypy..........................Skipped\n")

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
    def _fail_and_rewrite(project, _command):
        with open(os.path.join(project, "also.py"), "w") as fh:
            fh.write("x = 1\n")
        return 1, "Failed\n"

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
        check("rg14 where git cannot describe the tree, mutation is UNKNOWN "
              "and said so - reporting it as 'nothing changed' would be the "
              "false clean sheet this file exists to prevent: %r"
              % (res["treeBasis"],),
              res["mutated"] == []
              and res["treeBasis"].startswith("git could not"))
        lines = []
        M.render(res, out=lines.append)
        check("rg15 ...and the basis is printed, so a green verdict over an "
              "unaskable tree carries its own limit",
              "git could not describe the tree" in "\n".join(lines))

    # --- the empty gate is a designed state, not a pass -------------------
    mpath = os.path.join(tmp, "audit-plan.json")
    import json
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_run_test_gate.py --selftest\n")
    raise SystemExit(2)
