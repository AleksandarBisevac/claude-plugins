#!/usr/bin/env python3
"""
The cases for `repair-commits.py` — the DOOR, and the two bugs running it found.

`test__commit_trail.py` tests what reachable MEANS; this tests the command:
exit codes, what it writes, and where the record lands.

TWO CASES HERE ARE REGRESSIONS FOR BUGS THIS FILE DID NOT CATCH FIRST — a real
run did, which is why they are written the way they are:

- **`rc6`, the journal's location.** `project` was computed as
  `dirname(manifest)`, i.e. `docs/audit/`, and the journal then resolved
  `manifestPath` against it a SECOND time and landed in
  `docs/audit/docs/audit/journal/`. Every selftest passed; the row existed; it
  was simply in a directory no reader looks at. So the case asserts the absolute
  path, not that "a row was written".
- **`rc7`, the row's contents.** The details block invented `cleared` and
  `reason`, and `normalise_details` drops anything outside `DETAILS_KEYS` by
  design — so the row shipped with an EMPTY details block and `append` still
  returned truthy. The case reads the row back and asserts the SHA is in it.

Both share one shape: the write succeeded, the command said so, and the thing
that was supposed to be recorded was not. Asserting "it returned ok" would have
passed in both.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("repair-commits.py")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _repo_with_orphan(tmp, name="r"):
    """A repo whose manifest names a commit no ref reaches any more."""
    repo = os.path.join(tmp, name)
    os.makedirs(os.path.join(repo, "docs", "audit"))
    subprocess.run(["git", "init", "-q", repo], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test User")
    shas = []
    for n in range(3):
        with open(os.path.join(repo, "f%d.txt" % n), "w", encoding="utf-8") as fh:
            fh.write("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "c%d" % n)
        shas.append(_git(repo, "rev-parse", "HEAD").stdout.decode().strip())
    mpath = os.path.join(repo, "docs", "audit", "audit-plan.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 2},
                   "phases": [{"id": "P0", "title": "t", "status": "done",
                               "tasks": [{"id": "P0.1", "title": "t",
                                          "status": "done",
                                          "commit": shas[2]}]}]}, fh)
    _git(repo, "reset", "--hard", shas[0])
    return repo, mpath, shas


def _journal_rows(repo):
    rows = []
    jdir = os.path.join(repo, "docs", "audit", "journal")
    for name in sorted(os.listdir(jdir)) if os.path.isdir(jdir) else []:
        with open(os.path.join(jdir, name), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _cases(check):
    check("rc0 no arguments is a usage error, not an accidental clean report",
          M.main([]) == 2)
    check("rc1 an unreadable manifest is 2 - never a fall-through to 'all "
          "commits resolve', which is what a clean exit would claim",
          M.main(["/no/such/manifest.json"]) == 2)

    tmp = _harness.fixture_root("qg-repair-")
    try:
        repo, mpath, shas = _repo_with_orphan(tmp)

        check("rc2 report mode exits 1 when a recorded commit is unreachable, "
              "and writes NOTHING - the default has to be safe to run anywhere",
              M.main([mpath]) == 1
              and json.load(open(mpath))["phases"][0]["tasks"][0]["commit"]
              == shas[2])

        clean = os.path.join(tmp, "clean.json")
        with open(clean, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"version": 2}, "phases": []}, fh)
        check("rc3 a manifest with nothing recorded exits 0 - there is no trail "
              "to be broken, and reporting one would be a nag",
              M.main([clean]) == 0)

        check("rc4 --apply exits 0 and nulls the unreachable commit",
              M.main([mpath, "--apply"]) == 0
              and json.load(open(mpath))["phases"][0]["tasks"][0]["commit"]
              is None)
        check("rc5 ...and the repaired manifest reports clean on a re-run, so "
              "the repair is idempotent rather than a permanent finding",
              M.main([mpath]) == 0)

        rows = _journal_rows(repo)
        check("rc6 REGRESSION: the journal row lands in <repo>/docs/audit/"
              "journal, NOT in docs/audit/docs/audit/journal. `project` was "
              "dirname(manifest) once, the journal resolved manifestPath against "
              "it a second time, and the row went somewhere no reader looks - "
              "with every selftest still green, because a row WAS written",
              len(rows) == 1 and rows[0].get("action") == "trail.repair",
              repr([os.path.relpath(p, repo) for p in
                    [os.path.join(repo, "docs", "audit", "journal")]] + [len(rows)]))
        det = (rows[0].get("details") or {}) if rows else {}
        check("rc7 REGRESSION: the row actually CARRIES the lost SHA. The first "
              "version invented `cleared`/`reason`, which normalise_details drops "
              "by design - so the row shipped with an empty details block and "
              "append still returned truthy. Asserting 'it journaled' passed then "
              "and asserts nothing; this reads the row back",
              [c.get("from") for c in (det.get("changes") or [])] == [shas[2]]
              and [c.get("to") for c in (det.get("changes") or [])] == [None],
              repr(det))
        check("rc8 the summary names the task, so the trail is readable without "
              "opening the manifest it describes",
              "P0.1" in (rows[0].get("summary") or ""), repr(rows[0].get("summary")))

        code = M.main([mpath, "--json"])
        check("rc9 --json is available in report mode and does not change the "
              "verdict - a machine reader and a human reader get the same answer",
              code == 0)

        # A DECLINED RELEASE IS THE ONLY NEWS OF A TAKEOVER THIS COMMAND GETS,
        # and it used to go into a printer that discards beside a code nothing
        # read - so a repair that raced another session reported success and
        # said nothing. The lock is made to decline rather than raced into
        # declining: the property is that the code is READ and reaches the
        # message, and a real race would be testing the scheduler.
        import _locks                              # noqa: E402  (layer 1)
        repo2, mpath2, shas2 = _repo_with_orphan(tmp, name="r2")
        ans2 = M.report(json.load(open(mpath2)), repo2)
        real = _locks.release
        _locks.release = lambda *_a, **_k: _locks.E_LIVE
        try:
            ok2, said2 = M.apply_repair(mpath2, json.load(open(mpath2)), ans2)
        finally:
            _locks.release = real
            _locks.release(repo2, M.LOCK_NAME, out=lambda *_a, **_k: None)
        check("rc10 a release the lock DECLINES travels with the answer. The "
              "repair landed - that is what `ok` says - and the sentence adds "
              "the part nothing else would ever tell this run: another session "
              "took its lock over while the manifest was being written: %r"
              % (said2,),
              ok2 is True and "NOT released" in said2
              and "took it over" in said2
              and json.load(open(mpath2))["phases"][0]["tasks"][0]["commit"]
              is None)
    finally:
        _harness.remove_tree(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_repair_commits.py --selftest\n")
    raise SystemExit(2)
