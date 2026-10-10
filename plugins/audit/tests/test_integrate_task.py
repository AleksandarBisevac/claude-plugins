#!/usr/bin/env python3
"""
The cases for `integrate-task.py` - one task tree's bytes carried into the phase
tree, and every way that is refused.

Each case drives REAL git: a phase repository, real task worktrees made by
`manage-worktrees.py task-add` (so the marker the product reads is the marker the
product writes), and the integration run against them. A fixture that faked git
would assert the fake.

Fixtures are chosen so the wrong implementation disagrees with the right one:

- `i1` has both tasks edit the SAME line of an undeclared `package.json`, so the
  only honest outcome is a refusal that names the pair; the integration that
  silently let the later task win would write a file and exit 0.
- `i2` has the two tasks edit lines far apart, so a text merge is clean and an
  implementation that refused every overlap goes red - the allow case.
- `i6` puts a lockfile in a DECLARED DIRECTORY and has the two tasks edit lines far
  apart, so a text merge would be clean: only reading the real changed path, not the
  declared entry `deps`, can refuse it. `_wave.overlap` on the declarations is
  asserted to call that overlap mergeable, which is the premise.
- `i5` compares the phase tree's index FILE byte for byte, not a staged-path list:
  a refresh of its stat cache is a write the list cannot see.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import hashlib
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("integrate-task.py")
MW = _loader.load_script("manage-worktrees.py")

GIT = ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
       "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

TEN = "".join("line %d\n" % n for n in range(1, 11))


def _run(cwd, *argv):
    done = subprocess.run(GIT + list(argv), cwd=cwd, capture_output=True, timeout=30)
    if done.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(argv), done.stderr))
    return done.stdout.decode("utf-8")


def _write(root, rel, text):
    path = os.path.join(root, rel)
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8", newline="") as fh:
        return fh.read()


def _world(prefix, tasks, files, trees=True):
    """A committed phase repository holding `files` (rel -> text) and its manifest,
    whose phase P1 carries `tasks` (id -> declared files). -> dict."""
    root = os.path.realpath(_harness.fixture_root(prefix))
    proj = os.path.join(root, "proj")
    os.makedirs(proj)
    for rel, text in files.items():
        _write(proj, rel, text)
    manifest = {"meta": {"version": 3, "developmentBranch": "main"},
                "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                            "tasks": [{"id": tid, "title": tid,
                                       "status": "in_progress", "files": decl}
                                      for tid, decl in sorted(tasks.items())]}]}
    manifest_path = os.path.join(proj, "audit-plan.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    _run(proj, "init", "-q")
    _run(proj, "add", "-A")
    _run(proj, "commit", "-qm", "base")
    base = _run(proj, "rev-parse", "HEAD").strip()
    world = {"root": root, "proj": proj, "manifest": manifest,
             "manifest_path": manifest_path, "base": base, "trees": {}}
    for tid in sorted(tasks) if trees else ():
        code, answer = MW.do_task_add(proj, manifest, tid, base, project=proj,
                                      path=os.path.join(root, "wt-" + tid))
        if code != 0:
            raise RuntimeError("task-add %s: %r" % (tid, answer))
        world["trees"][tid] = answer["path"]
    return world


def _integrate(world, tid, undeclared=None):
    phase = world["manifest"]["phases"][0]
    task = [t for t in phase["tasks"] if t["id"] == tid][0]
    return M.integrate(world["manifest"], phase, task, world["manifest_path"],
                       world["proj"], world["proj"], undeclared=undeclared)


def _index_digest(proj):
    with open(os.path.join(proj, ".git", "index"), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _edit_line(text, number, new):
    lines = text.splitlines(True)
    lines[number - 1] = new + "\n"
    return "".join(lines)


def _conflict_cases(check):
    world = _world("itc", {"P1.1": ["src/a.txt"], "P1.2": ["src/b.txt"]},
                   {"package.json": "{\n  \"name\": \"x\"\n}\n",
                    "src/a.txt": "a\n", "src/b.txt": "b\n"})
    t1, t2 = world["trees"]["P1.1"], world["trees"]["P1.2"]
    _write(t1, "src/a.txt", "a1\n")
    _write(t1, "package.json", "{\n  \"name\": \"one\"\n}\n")
    _write(t2, "src/b.txt", "b2\n")
    _write(t2, "package.json", "{\n  \"name\": \"two\"\n}\n")
    code1, ans1 = _integrate(world, "P1.1", undeclared="widen")
    check("i1a the first task widens the undeclared package.json and integrates: "
          "%r %r" % (code1, ans1.get("refused")),
          code1 == 0 and _read(world["proj"], "package.json").count("one") == 1)
    code2, ans2 = _integrate(world, "P1.2")
    check("i1 two tasks writing package.json undeclared on the same line are "
          "REFUSED (exit 1, kind conflict) and BOTH are named: %r %r"
          % (code2, ans2.get("refused")),
          code2 == 1 and (ans2.get("refused") or {}).get("kind") == "conflict"
          and ans2["refused"]["tasks"] == ["P1.1", "P1.2"]
          and ans2["refused"]["paths"] == ["package.json"])
    check("i1b ...and the refusal wrote nothing: the second task's own file is "
          "absent from the phase tree and package.json is still the first task's",
          _read(world["proj"], "src/b.txt") == "b\n"
          and "one" in _read(world["proj"], "package.json"))


def _clean_overlap_cases(check):
    world = _world("ito", {"P1.1": ["shared.txt"], "P1.2": ["shared.txt"]},
                   {"shared.txt": TEN})
    _write(world["trees"]["P1.1"], "shared.txt", _edit_line(TEN, 1, "first"))
    _write(world["trees"]["P1.2"], "shared.txt", _edit_line(TEN, 9, "ninth"))
    code1, ans1 = _integrate(world, "P1.1")
    check("i2a the FIRST task of an overlapping pair has nothing to re-gate "
          "against (regate false): %r" % (ans1.get("regate"),),
          code1 == 0 and ans1.get("regate") is False)
    code2, ans2 = _integrate(world, "P1.2")
    merged = _read(world["proj"], "shared.txt")
    check("i2 a CLEAN overlap of a declared file is integrated, both edits "
          "survive, and it is marked `regate: true`: %r %r"
          % (code2, ans2.get("regate")),
          code2 == 0 and ans2.get("regate") is True
          and "first\n" in merged and "ninth\n" in merged
          and ans2.get("overlapWith") == ["P1.1"])


def _dirty_cases(check):
    world = _world("itd", {"P1.1": ["a.txt"]}, {"a.txt": "a\n"})
    _write(world["trees"]["P1.1"], "a.txt", "a1\n")
    journal = os.path.join(M._journal_io.journal_dir(world["proj"]), "x.jsonl")
    os.makedirs(os.path.dirname(journal))
    with open(journal, "w", encoding="utf-8") as fh:
        fh.write("{}\n")
    _write(world["proj"], "stray.txt", "not mine\n")
    code, ans = _integrate(world, "P1.1")
    check("i3 a non-record dirty path in the phase tree is REFUSED and named - and "
          "the journal file beside it is a record, so it is NOT named: %r %r"
          % (code, ans.get("refused")),
          code == 1 and (ans.get("refused") or {}).get("kind") == "dirty"
          and ans["refused"]["paths"] == ["stray.txt"])
    check("i3b ...and nothing was written before the refusal",
          _read(world["proj"], "a.txt") == "a\n")
    os.remove(os.path.join(world["proj"], "stray.txt"))
    code, ans = _integrate(world, "P1.1")
    check("i3c the same tree with only record paths dirty integrates - the "
          "refusal reads the stray file, not the journal: %r %r"
          % (code, ans.get("refused")),
          code == 0 and _read(world["proj"], "a.txt") == "a1\n")


def _resume_cases(check):
    world = _world("itr", {"P1.1": ["a.txt"]}, {"a.txt": "a\n"})
    _write(world["trees"]["P1.1"], "a.txt", "a1\n")
    first = _integrate(world, "P1.1")
    check("i4a a first run is NOT 'already integrated' (the quiet-tree direction "
          "of i4): %r" % (first[1].get("already"),),
          first[0] == 0 and first[1].get("already") is False)
    again = _integrate(world, "P1.1")
    check("i4 a second run after a crash between write and commit is a no-op that "
          "says 'already integrated': %r" % (again[1].get("sentence"),),
          again[0] == 0 and again[1].get("already") is True
          and "already integrated" in again[1].get("sentence", "")
          and _read(world["proj"], "a.txt") == "a1\n")
    os.remove(M.state_file(world["proj"]))
    lost = _integrate(world, "P1.1")
    check("i4b ...and with the state file LOST the bytes themselves say the same: "
          "%r" % (lost[1].get("sentence"),),
          lost[0] == 0 and lost[1].get("already") is True)


def _index_cases(check):
    world = _world("iti", {"P1.1": ["a.txt", "new/"]},
                   {"a.txt": "a\n"})
    _write(world["trees"]["P1.1"], "a.txt", "a1\n")
    _write(world["trees"]["P1.1"], "new/b.txt", "b\n")
    before = _index_digest(world["proj"])
    code, ans = _integrate(world, "P1.1")
    check("i5 the phase tree's git index FILE is byte-identical after an "
          "integration, and nothing is staged: %r" % (ans.get("refused"),),
          code == 0 and _index_digest(world["proj"]) == before
          and _run(world["proj"], "diff", "--cached", "--name-only") == "")
    check("i5b ...while the working tree did change (otherwise i5 passes on a "
          "no-op): modified %r"
          % (_run(world["proj"], "diff", "--name-only").split(),),
          _run(world["proj"], "diff", "--name-only").split() == ["a.txt"]
          and _read(world["proj"], "new/b.txt") == "b\n")


def _lockfile_cases(check):
    lock = "".join("dep %d\n" % n for n in range(1, 11))
    world = _world("itl", {"P1.1": ["deps"], "P1.2": ["deps"]},
                   {"deps/pkg.lock": lock, "deps/notes.txt": TEN})
    premise = M._wave.overlap({"id": "P1.1", "files": ["deps"]},
                              {"id": "P1.2", "files": ["deps"]})
    check("i6a premise: the DECLARATIONS alone call this overlap mergeable - the "
          "directory entry hides the lockfile: %r" % (premise,),
          premise is not None and premise["mergeable"] is True)
    _write(world["trees"]["P1.1"], "deps/pkg.lock", _edit_line(lock, 1, "x"))
    _write(world["trees"]["P1.2"], "deps/pkg.lock", _edit_line(lock, 9, "y"))
    _write(world["trees"]["P1.1"], "deps/notes.txt", _edit_line(TEN, 1, "x"))
    _write(world["trees"]["P1.2"], "deps/notes.txt", _edit_line(TEN, 9, "y"))
    check("i6b the first task integrates", _integrate(world, "P1.1")[0] == 0)
    code, ans = _integrate(world, "P1.2")
    refused = ans.get("refused") or {}
    check("i6 a lockfile inside a declared directory changed by two tasks is "
          "REFUSED as non-mergeable, naming the lockfile and both tasks - though "
          "its text merges clean: %r %r" % (code, refused),
          code == 1 and refused.get("kind") == "non-mergeable"
          and refused.get("paths") == ["deps/pkg.lock"]
          and refused.get("tasks") == ["P1.1", "P1.2"])
    check("i6c ...and the mergeable file beside it was NOT written by the refused "
          "task (no half-applied integration)",
          "y\n" not in _read(world["proj"], "deps/notes.txt"))


def _undeclared_cases(check):
    def fresh():
        world = _world("itu", {"P1.1": ["a.txt"]}, {"a.txt": "a\n"})
        _write(world["trees"]["P1.1"], "a.txt", "a1\n")
        _write(world["trees"]["P1.1"], "extra.txt", "x\n")
        return world
    world = fresh()
    code, ans = _integrate(world, "P1.1")
    decision = ans.get("decision") or {}
    check("i7 an undeclared path is a DECISION (exit 3) offering widen / discard / "
          "block, naming the path, and nothing is written: %r %r" % (code, decision),
          code == 3 and decision.get("kind") == "undeclared-change"
          and decision.get("options") == ["widen", "discard", "block"]
          and decision.get("paths") == ["extra.txt"]
          and _read(world["proj"], "a.txt") == "a\n"
          and not os.path.exists(os.path.join(world["proj"], "extra.txt")))
    world = fresh()
    code, ans = _integrate(world, "P1.1", undeclared="discard")
    check("i7b discard integrates the declared work, LISTS what it left behind, "
          "and does not write it: %r %r" % (code, ans.get("discarded")),
          code == 0 and ans.get("discarded") == ["extra.txt"]
          and not os.path.exists(os.path.join(world["proj"], "extra.txt"))
          and _read(world["proj"], "a.txt") == "a1\n")
    world = fresh()
    code, ans = _integrate(world, "P1.1", undeclared="widen")
    check("i7c widen integrates both and reports the paths the manifest must now "
          "declare: %r %r" % (code, ans.get("widened")),
          code == 0 and ans.get("widened") == ["extra.txt"]
          and _read(world["proj"], "extra.txt") == "x\n")
    world = fresh()
    code, ans = _integrate(world, "P1.1", undeclared="block")
    check("i7d block refuses and writes nothing: %r %r" % (code, ans.get("refused")),
          code == 1 and (ans.get("refused") or {}).get("kind") == "undeclared"
          and _read(world["proj"], "a.txt") == "a\n")


def _cli_cases(check):
    world = _world("itm", {"P1.1": ["a.txt"]}, {"a.txt": "a\n"})
    _write(world["trees"]["P1.1"], "a.txt", "a1\n")
    lines = []
    code = M.main([world["manifest_path"], "P1.1", "--project", world["proj"],
                   "--json"], out=lines.append)
    body = json.loads("\n".join(lines)) if lines else {}
    check("i8 the command integrates and prints the answer as JSON (exit 0): "
          "%r %r" % (code, body.get("paths")),
          code == 0 and body.get("paths") == ["a.txt"])
    code = M.main([world["manifest_path"], "P9.9", "--project", world["proj"]],
                  out=lambda _line: None)
    check("i8b a task the plan does not hold is a usage error (exit 2): %r" % (code,),
          code == 2)
    bare = _world("itn", {"P1.1": ["a.txt"]}, {"a.txt": "a\n"}, trees=False)
    code, ans = _integrate(bare, "P1.1")
    check("i8c a task with no marked tree is refused and says so, rather than "
          "integrating nothing and exiting 0: %r %r" % (code, ans.get("refused")),
          code == 1 and (ans.get("refused") or {}).get("kind") == "no-task-tree")


def _cases(check):
    _harness.stage(check, "itc", _conflict_cases)
    _harness.stage(check, "ito", _clean_overlap_cases)
    _harness.stage(check, "itd", _dirty_cases)
    _harness.stage(check, "itr", _resume_cases)
    _harness.stage(check, "iti", _index_cases)
    _harness.stage(check, "itl", _lockfile_cases)
    _harness.stage(check, "itu", _undeclared_cases)
    _harness.stage(check, "itm", _cli_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_integrate_task.py --selftest\n")
    raise SystemExit(2)
