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

        _baseline_cases(check, tmp)
        _harness.stage(check, "sl-block",
                       lambda c: _success_line_cases(c, tmp))
        _harness.stage(check, "lc-block",
                       lambda c: _landing_committed_cases(c, tmp))
    finally:
        _harness.remove_tree(tmp)


def _landed_repo(tmp, name):
    """`(manifest path, root)` - the phase branch landed on `main` by a
    fast-forward, with `main` checked out and the plan as committed there."""
    root = os.path.join(tmp, name)
    os.makedirs(root)
    path = repo(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore(audit-state): phase P1 - close")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--ff-only", BRANCH)
    return path, root


def _stamp(path, when="2026-01-02T00:00:00Z"):
    """What a landing writes into the parent's copy: `mergedAt`, and the
    derived `done` stored beside it."""
    body = _load(path)
    body["phases"][0]["mergedAt"] = when
    body["phases"][0]["status"] = "done"
    _write_json(path, body)


def _landing_check(argv):
    """`(exit code, the landing-committed check's answer or None, stdout)`."""
    code, out, _err = _run(argv + ["--json"])
    try:
        checks = json.loads(out)["checks"]
    except (ValueError, KeyError):
        return code, None, out
    named = [c for c in checks if c.get("name") == "landing-committed"]
    return code, (named[0] if named else None), out


def _landing_committed_cases(check, tmp):
    """A landed phase whose stamp - `status` done and `mergedAt` - sits in the
    parent's working tree and not in its HEAD is a landing nobody committed."""
    path, root = _landed_repo(tmp, "lc-dirty")
    _stamp(path)
    code, answer, out = _landing_check([path, "P1", "--project", root])
    said = " ".join((answer or {}).get("breaches") or [])
    check("lc1 a landed phase whose status and mergedAt are uncommitted in the "
          "parent's tree is a landing-committed BREACH naming the file and the "
          "stamp, and exits 1: %r" % ((code, answer),),
          code == 1 and (answer or {}).get("verdict") == "breach"
          and "docs/audit/audit-plan.json" in said and "mergedAt" in said
          and "2026-01-02T00:00:00Z" in said)
    _git(root, "add", "docs/audit/audit-plan.json")
    _git(root, "commit", "-q", "-m", "chore(audit-state): phase P1 - landed")
    code, answer, out = _landing_check([path, "P1", "--project", root])
    check("lc2 THE ALLOW TWIN: the same stamp committed is clean, with its basis "
          "naming what was compared: %r" % ((answer,),),
          (answer or {}).get("verdict") == "clean"
          and not (answer or {}).get("breaches")
          and "HEAD" in str((answer or {}).get("basis")))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n")
    code, answer, out = _landing_check([path, "P1", "--project", root])
    check("lc3 a file that is dirty for some other reason, its stamp committed, "
          "is not this breach - the check compares the stamp, never the file's "
          "dirtiness: %r" % ((answer,),),
          (answer or {}).get("verdict") == "clean")
    path, root = _landed_repo(tmp, "lc-open")
    code, answer, out = _landing_check([path, "P1", "--project", root])
    check("lc4 a phase that has not landed (mergedAt null) gives the check no "
          "subject: %r" % ((answer,),),
          (answer or {}).get("verdict") == "not-applicable")
    path, root = _landed_repo(tmp, "lc-all")
    _stamp(path)
    code, out, _err = _run([path, "--all", "--project", root])
    check("lc5 --all carries the check too, and its breach reaches the verdict "
          "list: %r" % (out[-300:],),
          code == 1 and "P1 landing-committed: " in out)


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _finish(path):
    """Mark the fixture's phase done, so a baseline may be written over it."""
    manifest = _load(path)
    manifest["phases"][0]["status"] = "done"
    _write_json(path, manifest)


def _entries_of(path):
    return _load(path)["entries"] if os.path.isfile(path) else []


def _json(argv):
    code, out, err = _run(argv + ["--json"])
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, {}, err


def _baseline_cases(check, tmp):
    """The committed baseline: only what is new is printed, nothing is dropped."""
    root = os.path.join(tmp, "base")
    os.makedirs(root)
    rogue = repo(root, rogue=True)
    base_path = os.path.join(os.path.dirname(rogue), "invariants-baseline.json")
    sha = _load(rogue)["phases"][0]["tasks"][0]["commit"]

    # --- the allow case: no baseline file, no change ------------------------
    code, out, _err = _run([rogue, "P1", "--project", root])
    check("vb1 with no baseline file the answer is what it always was - every "
          "breach printed, exit 1, and no baseline line invented",
          code == 1 and "BREACHES (1)" in out and "baseline" not in out.lower())

    # --- no self-baselining -------------------------------------------------
    code, out, err = _run([rogue, "P1", "--project", root, "--write-baseline"])
    check("vb2 --write-baseline is REFUSED while the phase it covers is in "
          "flight, and says whose file the baseline is instead: %r"
          % (err.strip()[:160],),
          code == 2 and not os.path.exists(base_path) and "in flight" in err
          and "outside any phase commit" in err)

    _finish(rogue)
    code, out, _err = _run([rogue, "P1", "--project", root, "--write-baseline"])
    entries = _entries_of(base_path)
    check("vb3 once the phase is done the write lands BESIDE the manifest, one "
          "entry per breach keyed on phase, check, subject and the FULL commit "
          "SHA from the check's own key: %r" % (entries,),
          len(entries) == 1
          and entries[0].get("phase") == "P1"
          and entries[0].get("check") == "commit-scope"
          and entries[0].get("subject") == "P1.1 src/rogue.py"
          and entries[0].get("sha") == sha
          and "src/rogue.py" in entries[0].get("breach", ""))
    check("vb3b ...and a write that succeeded exits 0 and prints how many it "
          "wrote - what it found is exactly what it just baselined, so exit 1 "
          "would say something untrue: %r" % (out.strip()[-120:],),
          code == 0 and "BASELINE WRITTEN: 1 fingerprint(s)" in out)
    with open(base_path, "rb") as fh:
        first_bytes = fh.read()
    _run([rogue, "P1", "--project", root, "--write-baseline"])
    with open(base_path, "rb") as fh:
        second_bytes = fh.read()
    check("vb4 ...and writing it twice over the same history is byte-identical, "
          "so a committed baseline only changes when the breaches do",
          first_bytes == second_bytes)

    # --- reading ------------------------------------------------------------
    code, out, _err = _run([rogue, "P1", "--project", root])
    check("vb5 once the baseline exists a baselined breach is not printed as "
          "one, the run exits 0, and the baseline count IS printed: %r"
          % (out.strip()[-160:],),
          code == 0 and "NEW BREACHES (0)" in out
          and "      BREACH:" not in out
          and "1 baselined breach(es)" in out)

    reworded = dict(entries[0])
    reworded["breach"] = "a sentence this module has never printed"
    _write_json(base_path, {"version": 2, "entries": [reworded]})
    code, out, _err = _run([rogue, "P1", "--project", root])
    check("vb6 the printed sentence is never matched: an entry whose wording "
          "differs but whose subject and SHA are the same still matches, so a "
          "reworded template does not bring the flood back",
          code == 0 and "NEW BREACHES (0)" in out
          and "NO LONGER MATCH" not in out)

    def _deferred(count):
        return {"found": True, "phaseId": "P7", "branch": None,
                "checks": [_invariants.result(
                    "manifest-revalidated", "b",
                    [_invariants.found("%d task commit(s) deferred this pairing"
                                       % (count,), "pairing deferred")], [], 1)],
                "breaches": [], "gaps": []}
    first = _invariants.fingerprints(_deferred(3))
    second = _invariants.compare_baseline(first, _deferred(4))
    check("vb7 a frozen breach whose sentence carries a count that moved "
          "between two runs is NOT new on the second: %r" % (second["new"],),
          second["new"] == [] and second["matched"] == 1)

    hexy = _invariants.fingerprints({
        "found": True, "phaseId": "P7", "branch": None, "breaches": [],
        "gaps": [], "checks": [_invariants.result(
            "evidence-committed", "b",
            [_invariants.found("task P7.1 points at run 24c1c300-aa", "run")],
            [], 1)]})
    check("vb8 a hex token in the sentence is not read as a commit - the SHA "
          "comes from the check's key, and this one has none: %r" % (hexy,),
          len(hexy) == 1 and hexy[0]["sha"] is None)

    stale = {"phase": "P1", "check": "commit-scope",
             "subject": "P1.1 src/gone.py", "sha": "0123456789ab" * 3 + "0123",
             "breach": "P1.1: commit 0123456789ab staged src/gone.py"}
    _write_json(base_path, {"version": 2, "entries": [stale]})
    code, out, _err = _run([rogue, "P1", "--project", root])
    check("vb9 a breach the baseline does not hold is NEW - printed, and exit "
          "1: %r" % (out.strip()[-200:],),
          code == 1 and "NEW BREACHES (1)" in out and "src/rogue.py" in out)
    check("vb10 ...and a baseline entry that matches no breach is REPORTED, with "
          "its commit named as one this clone does not have, never dropped",
          "NO LONGER MATCH (1)" in out and "src/gone.py" in out
          and "not in this clone" in out)
    check("vb11 ...and the matching and rewrite rule is stated in the output "
          "rather than left for a reader to discover",
          "rebase" in out and "squash" in out and "reworded" in out
          and "--write-baseline" in out)
    check("vb12 ...and the stale entry is still in the file - reading never "
          "rewrites it", _entries_of(base_path) == [stale])

    present = dict(stale, sha=sha, subject="P1.1 src/fixed.py")
    _write_json(base_path, {"version": 2, "entries": [present]})
    code, out, _err = _run([rogue, "P1", "--project", root])
    check("vb13 an unmatched entry whose commit IS still reachable, on a check "
          "that read everything, is told apart from a rewritten one",
          "NO LONGER MATCH (1)" in out and "still-reachable" in out
          and "not in this clone" not in out)

    # --- set aside rather than compared --------------------------------------
    code, payload, _err = _json([rogue, "P1", "--project", root])
    gapped = [c["name"] for c in payload.get("checks") or []
              if c["gaps"] and not c["breaches"]]
    blind = {"phase": "P1", "check": gapped[0] if gapped else "?",
             "subject": "something it could not look at", "sha": None,
             "breach": "x"}
    local = {"phase": "P1", "check": "branch-history",
             "subject": "stash On audit/p1-demo: x", "sha": None, "breach": "y",
             "clone": "0123456789abcdef"}
    other = {"phase": "P9", "check": "base-ref", "subject": "parent main",
             "sha": None, "breach": "elsewhere"}
    _write_json(base_path, {"version": 2,
                            "entries": [stale, blind, local, other]})
    code, payload, _err = _json([rogue, "P1", "--project", root])
    block = payload.get("baseline") or {}
    why = block.get("notComparedWhy") or {}
    check("vb14 an entry whose check had no full basis this run, one read from "
          "ANOTHER clone's own evidence, and one for a phase "
          "not examined are each set aside WITH their reason - never called "
          "repaired: %r" % (why,),
          bool(gapped) and len(block.get("unmatched") or []) == 1
          and why.get(_invariants.NOT_COMPARED_BASIS) == 1
          and why.get(_invariants.NOT_COMPARED_LOCAL) == 1
          and why.get(_invariants.NOT_COMPARED_PHASE) == 1)
    code, out, _err = _run([rogue, "P1", "--project", root, "--write-baseline"])
    kept = _entries_of(base_path)
    check("vb15 ...and a rewrite keeps every set-aside entry and removes only the "
          "compared stale one, naming it: %r" % (out.strip()[-200:],),
          all(any(k["subject"] == e["subject"] for k in kept)
              for e in (blind, local, other))
          and not any(k["subject"] == stale["subject"] for k in kept)
          and "removed 1" in out and "src/gone.py" in out)

    code, payload, _err = _json([rogue, "P1", "--project", root])
    block = payload.get("baseline") or {}
    check("vb16 --json carries the baseline answer as one block - path, "
          "counts, new, unmatched and the reasons for what was set aside - "
          "beside the full breach list: %r" % (sorted(block.keys()),),
          code == 0 and block.get("path") == base_path
          and block.get("matched") == 1 and block.get("new") == []
          and block.get("unmatched") == [] and block.get("notCompared") == 3
          and len(payload.get("breaches") or []) == 1)

    # --- one verdict: the gate reads the same baseline ----------------------
    status = _loader.load_script("audit-status.py", modname="audit_status_vb")
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = root
    try:
        gate_with = status.invariants_block(_load(rogue), rogue)
        os.rename(base_path, base_path + ".off")
        gate_without = status.invariants_block(_load(rogue), rogue)
        os.rename(base_path + ".off", base_path)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
    check("vb17 the gate counts what the CLI counts: with the baseline it has "
          "no breach to trip on, without it the same history trips - and the "
          "full list travels beside the counted one: %r / %r"
          % (gate_with.get("breaches"), len(gate_without.get("breaches") or [])),
          gate_with.get("breaches") == []
          and len(gate_with.get("allBreaches") or []) == 1
          and len(gate_without.get("breaches") or []) == 1)

    status_py = os.path.join(os.path.dirname(os.path.abspath(status.__file__)),
                             "audit-status.py")

    def _gate():
        done = subprocess.run(
            [sys.executable, status_py, rogue, "--gate", "--fail-on",
             "invariant-breach"], cwd=root,
            env=dict(os.environ, CLAUDE_PROJECT_DIR=root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return done.returncode, done.stdout.decode("utf-8", "replace")

    gate_code, gate_out = _gate()
    check("vb26 a fully baselined history PASSES the gate and the gate SAYS the "
          "baseline was applied - path and counts - before the verdict: %r"
          % (gate_out.strip()[-240:],),
          gate_code == 0 and "GATE PASSED" in gate_out
          and "held by the baseline %s" % (base_path,) in gate_out
          and gate_out.index("held by the baseline") < gate_out.index("GATE"))
    with open(base_path, "rb") as fh:
        keep_bytes = fh.read()
    _write_json(base_path, {"version": 3, "entries": []})
    gate_code, gate_out = _gate()
    check("vb27 ...and a FAILED gate over a baseline says what it counted: the "
          "breaches the baseline does not hold, with the baseline note beside "
          "it: %r" % (gate_out.strip()[-240:],),
          gate_code != 0 and "the baseline does not hold" in gate_out
          and "held by the baseline" in gate_out)
    with open(base_path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    gate_code, gate_out = _gate()
    check("vb28 ...and an unreadable baseline's GATE FAILED line carries the "
          "baseline's own reason, not the sentence for checks that never ran: %r"
          % (gate_out.strip()[-200:],),
          gate_code != 0 and "baseline could not be applied" in gate_out
          and "did not run" not in gate_out)
    with open(base_path, "wb") as fh:
        fh.write(keep_bytes)

    manifest = _load(rogue)
    manifest["phases"][0]["tasks"][0]["commit"] = sha[:8]
    _write_json(rogue, manifest)
    code, payload, _err = _json([rogue, "P1", "--project", root])
    keys = [k for c in payload.get("checks") or [] if c["name"] == "commit-scope"
            for k in c["keys"]]
    check("vb29 a commit the manifest recorded ABBREVIATED is keyed on the full "
          "id git resolves, so re-recording it at another length is not a new "
          "breach: %r" % (keys,),
          keys and all(k["sha"] == sha and len(k["sha"]) == 40 for k in keys)
          and (payload.get("baseline") or {}).get("new") == [])
    manifest["phases"][0]["tasks"][0]["commit"] = sha
    _write_json(rogue, manifest)

    real_check = _invariants.check_phase

    def _boom(*_a, **_k):
        raise TypeError("a breach built without found()")
    _invariants.check_phase = _boom
    try:
        code, out, err = _run([rogue, "P1", "--project", root])
    finally:
        _invariants.check_phase = real_check
    check("vb30 a check that raises is exit 2 with its message - never the 1 "
          "that means a breach, which sign-off would read as a finding: %r"
          % (err.strip()[:120],),
          code == 2 and "could not run" in err and "found()" in err)

    # --- the write is serialized --------------------------------------------
    import _locks
    held_path = os.path.join(_locks.lock_dir(root), "index.lock")
    os.makedirs(os.path.dirname(held_path), exist_ok=True)
    _locks._write_lock(held_path, {"sessionId": "another-writer",
                                   "pid": os.getppid(),
                                   "hostname": __import__("socket").gethostname(),
                                   "startedAt": "2099-01-01T00:00:00Z"})
    with open(base_path, "rb") as fh:
        before = fh.read()
    saved_wait = _locks.WAIT_SECONDS
    _locks.WAIT_SECONDS = 0
    try:
        code, out, err = _run([rogue, "P1", "--project", root,
                               "--write-baseline"])
    finally:
        _locks.WAIT_SECONDS = saved_wait
        os.unlink(held_path)
    with open(base_path, "rb") as fh:
        after = fh.read()
    check("vb18 a second writer is refused while another holds the index lock, "
          "and the file is untouched - two writers that each read the old file "
          "would have the second erase the first: %r" % (err.strip()[:120],),
          code == 2 and "index lock" in err and before == after)

    # HELD IS NOT TAKEN: this session's own hold is what a parallel subagent of
    # the same session also sees, so the write must not ride it.
    saved_env = dict((k, os.environ.get(k))
                     for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_PID"))
    os.environ["CLAUDE_CODE_SESSION_ID"] = "this-session"
    os.environ["CLAUDE_PID"] = str(os.getpid())
    _locks._write_lock(held_path, {"sessionId": "this-session",
                                   "pid": os.getpid(),
                                   "hostname": __import__("socket").gethostname(),
                                   "startedAt": "2099-01-01T00:00:00Z"})
    try:
        code, out, err = _run([rogue, "P1", "--project", root,
                               "--write-baseline"])
    finally:
        os.unlink(held_path)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    with open(base_path, "rb") as fh:
        after_ours = fh.read()
    check("vb31 ...and so is a writer whose OWN session already holds the index "
          "lock - a hold it did not take serializes nothing against a sibling "
          "of the same session: %r" % (err.strip()[:120],),
          code == 2 and "already holds the index lock" in err
          and after_ours == before)

    # --- a rewrite: the SHA changes under the same breach --------------------
    _git(root, "commit", "-q", "--amend", "-m", "chore(P1.1): audit - a (rewritten)")
    manifest = _load(rogue)
    manifest["phases"][0]["tasks"][0]["commit"] = _git(
        root, "rev-parse", "HEAD").strip()
    _write_json(rogue, manifest)
    new_sha = manifest["phases"][0]["tasks"][0]["commit"]
    code, payload, _err = _json([rogue, "P1", "--project", root])
    block = payload.get("baseline") or {}
    rewritten = [e for e in block.get("new") or []
                 if e["check"] == "commit-scope" and e["sha"] == new_sha]
    stale_old = [e for e in block.get("unmatched") or [] if e["sha"] == sha]
    check("vb19 after an amend gives the task commit a new SHA the breach is "
          "NEW under that SHA and the old entry is unmatched with its commit "
          "named as reachable from no ref - the rewrite is said, not silent: %r"
          % ([e.get("reason") for e in stale_old],),
          code == 1 and len(rewritten) == 1 and len(stale_old) == 1
          and "no branch or tag" in stale_old[0]["reason"])

    # --- refusals -----------------------------------------------------------
    with open(base_path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    code, out, err = _run([rogue, "P1", "--project", root])
    check("vb20 a baseline that cannot be read is exit 2 and says so - never a "
          "run that quietly ignores it and prints every frozen breach as new",
          code == 2 and out == "" and "baseline" in err)
    _write_json(base_path, {"version": 1, "entries": [
        {"phase": "P1", "check": "commit-scope", "breach": "old shape",
         "commits": []}]})
    code, out, err = _run([rogue, "P1", "--project", root])
    check("vb21 ...and so is a baseline that matched on the printed sentence: it "
          "is refused with the instruction to write it again, never read as "
          "matching nothing", code == 2 and "write it again" in err)
    missing = os.path.join(tmp, "nowhere.json")
    code, out, err = _run([rogue, "P1", "--project", root,
                           "--baseline", missing])
    check("vb22 an explicit --baseline that is not there is exit 2 - the caller "
          "asked for a comparison that cannot be made",
          code == 2 and out == "" and missing in err)
    code, out, err = _run([rogue, "P1", "--project", root, "--write-baseline",
                           "--baseline", missing])
    check("vb23 ...while --write-baseline to an explicit path creates it",
          os.path.isfile(missing))
    help_text = M.build_parser().format_help()
    check("vb24 --help names both flags and the in-flight refusal, so the mode "
          "can be found without reading the source",
          "--write-baseline" in help_text and "--baseline" in help_text
          and "in flight" in help_text)
    shared = ("BASELINE_NAME", "REWRITE_RULE", "baseline_key")
    forked = sorted(n for n in shared
                    if getattr(M, n, None) is not getattr(_invariants, n, 0))
    check("vb25 the baseline's names here are the library's own objects, so "
          "the command and the gate cannot come to spell them apart: %r"
          % (forked,), forked == [])


def _cli(argv):
    """`(exit, stdout)` of this command run as the main loop runs it: a process,
    with the session's own variables dropped."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("verify-invariants.py")] + argv,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _success_line_cases(check, tmp):
    """A phase with no breach, said in one line; a breach and `--verbose`, in
    full."""
    root = os.path.join(tmp, "sl-clean")
    os.makedirs(root)
    clean = repo(root)
    code, short = _cli([clean, "P1", "--project", root])
    lines = short.splitlines()
    check("sl1 a phase with no breach prints ONE line within the byte bound, "
          "naming the phase and that nothing was found in what could be "
          "examined: %r" % (short,),
          code == 0 and len(lines) == 1
          and len(lines[0].encode("utf-8")) <= 200
          and lines[0].startswith("[verify-invariants] PHASE P1")
          and "no breach found" in lines[0])
    vcode, verbose = _cli([clean, "P1", "--project", root, "--verbose"])
    check("sl2 ...and `--verbose` prints the report `main` prints - a verdict "
          "and a basis per check - byte for byte: %r" % (verbose[:120],),
          vcode == 0
          and verbose == _run([clean, "P1", "--project", root])[1]
          and len(verbose.splitlines()) > len(_invariants.CHECK_NAMES))
    rroot = os.path.join(tmp, "sl-rogue")
    os.makedirs(rroot)
    rogue = repo(rroot, rogue=True)
    breach = _cli([rogue, "P1", "--project", rroot])
    check("sl3 a BREACH prints the whole report, `--verbose` or not - the deny "
          "twin of sl1: %r" % (breach[1][-160:],),
          breach[0] != 0 and "BREACH: " in breach[1]
          and breach == _cli([rogue, "P1", "--project", rroot, "--verbose"]))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_verify_invariants.py --selftest\n")
    raise SystemExit(2)
