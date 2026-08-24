#!/usr/bin/env python3
"""
The cases for `verify-invariants.py` — the door, not the checks.

`test__invariants.py` proves the five checks against a real repository, one broken
thing at a time. What is left for the door is everything a caller can get wrong and
everything the printed answer promises:

- **The exit code says what was FOUND, not whether the question could be asked.**
  A breach is exit 1, a usage or read error is exit 2, and a missing basis is exit
  0 with the words `no-basis` in the output. That last one is the contract worth
  writing down: failing a build on absent evidence would fail it on every finished
  phase, because sign-off deletes the branch whose reflog the check reads — and a
  gate that fires on healthy work is a gate somebody turns off within a day.
- **Silence never reads as a pass.** A manifest where nothing has started prints
  that nothing was examined; a `--all` run that skipped phases names them. An empty
  report and a clean report are different documents here.
- **The basis is printed on every check, including the clean ones.** A reader who
  can see why a clean verdict is clean can tell it from a check that was never
  wired up. `vi9` counts the basis lines rather than looking for one.
- **A verdict the renderer has no sentence for would print bare**, so `vi13`
  compares the two vocabularies instead of trusting them to stay in step.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import io
import json
import os
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _invariants                                 # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("verify-invariants.py", modname="verify_invariants")

BRANCH = "audit/p1-demo"

MANIFEST = {
    "meta": {"version": 3, "repo": "fixture", "title": "fixture",
             "createdISO": "2026-01-01T00:00:00Z", "developmentBranch": "main",
             "branchPrefix": "audit", "gitRoot": ".", "reviewSkill": None,
             "runtimeBoot": None, "nodePreamble": None,
             "commit": {"type": "chore", "coauthor": None},
             "buildCommands": {"test": "true"}},
    "phases": [{
        "id": "P1", "title": "one", "status": "pending", "model": "sonnet",
        "blockedBy": [], "desiredOutcome": "d", "testGate": ["test"],
        "baseRef": None, "branch": None, "mergedAt": None,
        "review": {"tool": None, "model": "sonnet", "status": "pending",
                   "findings": []},
        "summary": None,
        "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                   "model": "sonnet", "skills": [], "blockedBy": [],
                   "dependsOn": [], "files": ["src/a.py"], "docs": [],
                   "description": "d",
                   "tests": {"mode": "gate-only", "add": [],
                             "expectRedFirst": False, "gate": ["test"]},
                   "outcome": {"technical": None, "descriptive": None},
                   "commit": None, "attempts": 0, "maxAttempts": 3,
                   "startedAt": None, "completedAt": None, "risk": "low",
                   "verifiedBy": []}]}],
    "fileIndex": {"src/a.py": ["P1.1"]},
    "deferred": {"note": "none", "target": None, "items": []},
    "proposals": [],
    "bugs": [],
}


def _git(cwd, *args):
    done = subprocess.run(["git"] + list(args), cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode != 0:
        raise RuntimeError("git %s failed: %s"
                           % (" ".join(args),
                              done.stdout.decode("utf-8", "replace")[:200]))
    return done.stdout.decode("utf-8", "replace")


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def repo(root, started=True, rogue=False):
    """A single-file-manifest repository, optionally with one finished task.

    SINGLE-FILE ON PURPOSE, and not because it is smaller: `test__invariants.py`
    runs the sharded layout end to end, so the two suites between them cover both
    storage shapes rather than both covering one. The single-file case is also the
    one where "the index was staged" must NOT be a breach — there is only one
    manifest to stage.
    """
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, ".claude"))
    _write_json(os.path.join(root, ".claude", "audit.config.json"),
                {"manifestPath": "docs/audit/audit-plan.json"})
    manifest = copy.deepcopy(MANIFEST)
    path = os.path.join(root, "docs", "audit", "audit-plan.json")
    _write_json(path, manifest)
    _git(root, "init", "-q")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.email", "fixture@example.com")
    _git(root, "config", "user.name", "Fixture")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD").strip()
    if not started:
        return path
    _git(root, "checkout", "-q", "-b", BRANCH)
    with open(os.path.join(root, "src", "a.py"), "w", encoding="utf-8") as fh:
        fh.write("a = 1\n")
    manifest["phases"][0]["branch"] = BRANCH
    manifest["phases"][0]["baseRef"] = base
    manifest["phases"][0]["tasks"][0]["status"] = "done"
    _write_json(path, manifest)
    staged = ["src/a.py", "docs/audit/audit-plan.json"]
    if rogue:
        with open(os.path.join(root, "src", "rogue.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("rogue = 1\n")
        staged.append("src/rogue.py")
    _git(root, "add", *staged)
    _git(root, "commit", "-q", "-m", "chore(P1.1): audit - a")
    manifest["phases"][0]["tasks"][0]["commit"] = _git(
        root, "rev-parse", "HEAD").strip()
    _write_json(path, manifest)
    return path


def _run(argv):
    """(exit code, stdout, stderr) — the printed answer is half the contract."""
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = M.main(argv, out=lambda line: out.write(line + "\n"))
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    return code, out.getvalue(), err.getvalue()


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = _harness.fixture_root("vi-")
    try:
        clean_root = os.path.join(tmp, "clean")
        os.makedirs(clean_root)
        clean = repo(clean_root)

        rogue_root = os.path.join(tmp, "rogue")
        os.makedirs(rogue_root)
        rogue = repo(rogue_root, rogue=True)

        idle_root = os.path.join(tmp, "idle")
        os.makedirs(idle_root)
        idle = repo(idle_root, started=False)

        # --- usage ------------------------------------------------------------
        for label, argv in (("no arguments at all", []),
                            ("a manifest and no subject", [clean]),
                            ("both a phase id AND --all", [clean, "P1", "--all"])):
            code, out, _err = _run(argv)
            check("vi1 usage error is exit 2 and prints NO report (%s): %r"
                  % (label, code), code == 2 and out == "")

        code, _out, err = _run([os.path.join(tmp, "nope.json"), "P1"])
        check("vi2 a manifest that cannot be read is exit 2 and says so - never "
              "exit 0 over a file nobody could open: %r" % (err.strip()[:60],),
              code == 2 and "cannot read/parse" in err)

        notadict = os.path.join(tmp, "notadict.json")
        with open(notadict, "w", encoding="utf-8") as fh:
            json.dump(["nope"], fh)
        code, out, err = _run([notadict, "P1"])
        check("vi3 a manifest that is not an object is exit 2 with an empty "
              "stdout - answering 'no breach' about something we could not read "
              "is the confident-wrong-answer this command exists to avoid",
              code == 2 and out == "" and "not a JSON object" in err)

        code, out, err = _run([clean, "P404"])
        check("vi4 an unknown phase id is exit 2 and the message LISTS the ids "
              "that exist, so the caller is not left guessing: %r"
              % (err.strip()[:70],),
              code == 2 and out == "" and "P1" in err)

        # --- nothing started --------------------------------------------------
        code, out, _err = _run([idle, "P1", "--project", idle_root])
        check("vi5 a phase that never started is exit 0 and every check says "
              "not-applicable - which is printed, not omitted",
              code == 0
              and out.count(_invariants.NA) == len(_invariants.CHECK_NAMES))

        code, out, _err = _run([idle, "--all", "--project", idle_root])
        check("vi6 --all over a manifest where nothing started SAYS that nothing "
              "was examined. This is the case that fails the moment silence is "
              "allowed to read as a pass: %r" % (out.strip()[-60:],),
              code == 0 and "NO PHASE HAS STARTED" in out)

        # --- the clean phase ---------------------------------------------------
        code, out, _err = _run([clean, "P1", "--project", clean_root])
        check("vi7 a clean phase is exit 0 and reports no breach",
              code == 0 and "BREACHES" not in out)
        check("vi8 ...and the basis is printed for EVERY check, clean ones "
              "included - counted, because one basis line looks the same as five "
              "when you only look for the word: %d"
              % (out.count("      basis: "),),
              out.count("      basis: ") == len(_invariants.CHECK_NAMES))
        check("vi9 ...and a `no basis` line is NOT an error: the branch's reflog "
              "survives here, but the stash caveat does not, and the command "
              "still exits 0 with the words in the output",
              code == 0 and "no basis:" in out)

        # --- the breach --------------------------------------------------------
        code, out, _err = _run([rogue, "P1", "--project", rogue_root])
        check("vi10 a breach is exit 1 and the offending path is named in the "
              "BREACHES block: %r" % (out.strip()[-80:],),
              code == 1 and "BREACHES (1)" in out and "src/rogue.py" in out)

        # --- json --------------------------------------------------------------
        code, out, _err = _run([rogue, "P1", "--project", rogue_root, "--json"])
        try:
            payload = json.loads(out)
        except ValueError:
            payload = None
        check("vi11 --json is exactly one parseable document - the human "
              "rendering is not appended to it",
              isinstance(payload, dict))
        check("vi12 ...and it carries the same verdict the exit code does, with "
              "every check and its basis, so a stored answer can be re-read "
              "without re-running git: %r"
              % (sorted((payload or {}).keys()),),
              code == 1 and len(payload["checks"]) == len(_invariants.CHECK_NAMES)
              and len(payload["breaches"]) == 1
              and all(c["basis"] for c in payload["checks"]))

        code_all, out_all, _err = _run([rogue, "--all", "--project", rogue_root])
        check("vi13 --all reaches the same verdict as naming the phase - two "
              "renderings of one answer, not two answers",
              code_all == 1 and "src/rogue.py" in out_all)

        # --- the two vocabularies ---------------------------------------------
        missing = [v for v in (_invariants.CLEAN, _invariants.BREACH,
                               _invariants.PARTIAL, _invariants.NO_BASIS,
                               _invariants.NA) if v not in M.VERDICT_HELP]
        check("vi16 every verdict the module can produce has a sentence here. A "
              "word added next door and not here would print bare, and a bare "
              "`no-basis` reads like a shrug rather than a warning: %r"
              % (missing,), missing == [])

        # --- the boundary ------------------------------------------------------
        # Both resolvers must BE `_invariants`' objects. A copy pasted back here
        # passes every behavioural case below and fails only this one, and the two
        # would then drift for months while `/audit:status --gate` and this command
        # quietly looked in different places for the same ledger.
        shared = ("ledger_dir_for", "git_root_for")
        forked = sorted(n for n in shared
                        if getattr(M, n, None) is not getattr(_invariants, n))
        check("vi14 the path resolvers are the library's own objects, not a "
              "second spelling this command keeps: %r" % (forked,),
              forked == [])
        check("vi15 ...and both are actually present here, so vi14 cannot pass "
              "over a name that quietly went missing",
              all(hasattr(M, n) for n in shared))

        # --- path resolution ---------------------------------------------------
        nested = {"meta": {"gitRoot": "app"}}
        check("vi17 meta.gitRoot is where git runs, resolved against --project - "
              "a workspace whose repo is a subdirectory is the layout this gets "
              "wrong silently",
              M.git_root_for(nested, "/tmp/x") == os.path.abspath("/tmp/x/app")
              and M.git_root_for({}, "/tmp/x") == os.path.abspath("/tmp/x"))
        check("vi18 a manifest with no ledger anywhere resolves to None rather "
              "than to a guess - a guessed ledger is a report full of confident "
              "numbers about another project",
              M.ledger_dir_for(MANIFEST, os.path.join(idle_root, "docs",
                                                      "audit",
                                                      "audit-plan.json")) is None)
        os.makedirs(os.path.join(idle_root, ".claude", "usage"))
        check("vi19 ...and it DOES find one that exists. Reads vacuous beside "
              "vi18 and is the only case that fails if the lookup becomes a "
              "constant None",
              M.ledger_dir_for(MANIFEST,
                               os.path.join(idle_root, "docs", "audit",
                                            "audit-plan.json"))
              == os.path.join(idle_root, ".claude", "usage"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_verify_invariants.py --selftest\n")
    raise SystemExit(2)
