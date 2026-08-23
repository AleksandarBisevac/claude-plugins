#!/usr/bin/env python3
"""
The cases for `_commit_trail.py` — is a recorded commit still REACHABLE?

The suite exists because of one distinction, and every case here is a way of
holding it: **an object being in the store is not the same as a ref reaching it.**
`/audit:doctor` asked `git rev-parse --verify` alone, which answers the first
question, so a `git reset --hard` that orphaned three task commits left all three
verifying green — until a `gc` ran, at which point they turned from recoverable
into gone with no event in between for anyone to notice.

`t3` is that case, built on a real repo with a real reset, and it is the one that
would go red if the check ever slid back to existence.

The other load-bearing shape is that `clear()` NEVER re-anchors. There is no
search for a commit with the same message or tree, because a plausible substitute
makes the trail read as intact when it is not — so the cases assert the SHA
becomes null and that what was lost comes back to the caller to record.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _commit_trail as M                          # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def _repo(tmp, name="r"):
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
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
    return repo, shas


def _manifest(*commits):
    return {"meta": {"version": 2},
            "phases": [{"id": "P0", "title": "t", "status": "done",
                        "tasks": [{"id": "P0.%d" % (i + 1), "title": "t",
                                   "status": "done", "commit": c}
                                  for i, c in enumerate(commits)]}]}


def _cases(check):
    check("t0 a manifest with no recorded commit answers all three classes "
          "empty rather than raising - nothing to reach is a state, not an error",
          M.dangling(_manifest(), None) == {"missing": [], "unreachable": [],
                                            "unchecked": []})
    tmp = tempfile.mkdtemp(prefix="qg-trail-")
    try:
        repo, shas = _repo(tmp)

        check("t1 a reachable commit is in NO class - the clean case, and the one "
              "that goes red if the check ever starts refusing everything",
              M.dangling(_manifest(shas[1]), repo)
              == {"missing": [], "unreachable": [], "unchecked": []})
        check("t2 a SHA git has never seen is MISSING - a fabricated id, or one "
              "orphaned long enough ago for gc to collect it",
              [t for _p, t, _s in M.dangling(
                  _manifest("0" * 40), repo)["missing"]] == ["P0.1"],
              repr(M.dangling(_manifest("0" * 40), repo)))

        # THE CASE THE MODULE EXISTS FOR.
        _git(repo, "reset", "--hard", shas[0])
        d = M.dangling(_manifest(shas[2]), repo)
        check("t3 EXISTENCE IS NOT REACHABILITY. After `git reset --hard`, the "
              "orphaned commit is still IN THE OBJECT STORE - `rev-parse "
              "--verify` finds it and reports green - but no ref reaches it. It "
              "must land in `unreachable`, and it must not be silently clean: "
              "this is the bug the doctor's old rev-parse loop could not see, "
              "and the window in which the damage is still recoverable",
              [t for _p, t, _s in d["unreachable"]] == ["P0.1"]
              and d["missing"] == [], repr(d))
        check("t3b ...and the proof the two questions really differ: git still "
              "resolves that same SHA as an object, so a check built on "
              "rev-parse alone would call this trail healthy",
              _git(repo, "rev-parse", "-q", "--verify",
                   "%s^{commit}" % shas[2]).returncode == 0)

        check("t4 no git means UNCHECKED, never clean. 'could not ask' and "
              "'everything is present' are different answers, and folding the "
              "first into the second reports a machine with no git as healthy",
              [t for _p, t, _s in
               M.dangling(_manifest(shas[1]), None)["unchecked"]] == ["P0.1"],
              repr(M.dangling(_manifest(shas[1]), None)))

        # --- clear: null, never a substitute -------------------------------
        man = _manifest(shas[2], shas[0])
        out, cleared = M.clear(man, [("P0", "P0.1", shas[2])])
        tasks = out["phases"][0]["tasks"]
        check("t5 clear() nulls the named task's commit and leaves the others "
              "alone - a repair that touched a healthy row would be worse than "
              "the damage",
              tasks[0]["commit"] is None and tasks[1]["commit"] == shas[0],
              repr([t["commit"] for t in tasks]))
        check("t6 ...and hands back WHAT WAS LOST, because the caller's job is to "
              "record it. A repair that erased the evidence of its own necessity "
              "would be the same silence one step later",
              cleared == [{"phaseId": "P0", "taskId": "P0.1",
                           "wasCommit": shas[2]}], repr(cleared))
        check("t7 NO RE-ANCHOR: the cleared task's commit is null and not some "
              "other SHA. A substitute found by matching messages or trees makes "
              "the trail read as intact when the commit it was verified against "
              "is gone - the gap IS the fact",
              tasks[0]["commit"] is None
              and shas[0] not in [str(t["commit"]) for t in tasks[:1]],
              repr(tasks[0]))
        check("t8 summary() names the task and the SHA it used to hold, so the "
              "journal row is readable without opening the manifest",
              "P0.1" in M.summary(cleared) and shas[2][:12] in M.summary(cleared),
              M.summary(cleared))
        check("t9 ...and an empty repair says so rather than producing an "
              "authoritative-looking empty sentence",
              "no recorded commit" in M.summary([]), M.summary([]))

        # --- F88: a shallow clone cannot accuse ---------------------------------
        # Driven against a REAL truncated clone rather than a stubbed predicate.
        # `--depth 1` is what `actions/checkout` does by default, and the SHA the
        # manifest records is deliberately one the graft cut away - so the fixture
        # reproduces the CI failure rather than describing it.
        # ITS OWN REPO, not the shared one. By this point an earlier case has
        # `reset --hard`ed the shared fixture onto its first commit, so a
        # `--depth 1` clone of it fetches exactly the SHA this case needs to be
        # missing - `--depth` is per REF, and that ref now points there. Reusing
        # it made t10 report `cut_resolves=True` and t11 pass for the wrong
        # reason. A fresh repo also leaves nothing behind for the cases after.
        f88_repo, f88_shas = _repo(tmp, "f88")
        shallow = os.path.join(tmp, "shallow")
        # `file://` is required: git says "--depth is ignored in local clones"
        # and silently hands back a FULL clone, which would make every case
        # below assert the opposite of what it says.
        _git(tmp, "clone", "-q", "--depth", "1", "file://" + f88_repo, shallow)
        cut = f88_shas[0]
        deep_ok = _git(shallow, "rev-parse", "-q", "--verify",
                       cut + "^{commit}").returncode == 0
        check("t10 the fixture really is truncated - a clone git calls shallow, "
              "whose HEAD is present and whose oldest recorded commit is past the "
              "cut. A fixture where every SHA resolves would pass under any "
              "grading, which is how this case would assert nothing",
              M.is_shallow(shallow) is True and M.is_shallow(f88_repo) is False
              and not deep_ok,
              "shallow=%r full=%r cut_resolves=%r"
              % (M.is_shallow(shallow), M.is_shallow(f88_repo), deep_ok))
        _cut_shallow = M.dangling(_manifest(cut), shallow)
        check("t11 a commit past the graft is UNCHECKED, never missing - in a "
              "shallow clone `rev-parse` failing says the object is past where "
              "the clone was cut, and `missing` is graded as fabricated-or-"
              "collected, whose own remedy (`repair-commits.py --apply`) NULLS "
              "the SHA. The old grading made the doctor advise destroying an "
              "intact trail",
              _cut_shallow["missing"] == [] and _cut_shallow["unreachable"] == []
              and len(_cut_shallow["unchecked"]) == 1, _cut_shallow)
        _cut_full = M.dangling(_manifest(cut), f88_repo)
        check("t12 ...and the SECOND DIRECTION, which is the one that fails if "
              "the fix becomes unconditional: the same manifest against the FULL "
              "clone still resolves clean, so a version that routed every "
              "negative to unchecked would report a healthy trail as unasked",
              _cut_full == {"missing": [], "unreachable": [], "unchecked": []},
              _cut_full)
        _bogus_full = M.dangling(_manifest("0" * 40), f88_repo)
        check("t13 ...and a genuinely fabricated SHA in a full clone is STILL "
              "missing. This is the accusation the fix must not soften, and it "
              "is what separates 'shallow' from 'silent'",
              len(_bogus_full["missing"]) == 1
              and _bogus_full["unchecked"] == [], _bogus_full)
        _bogus_shallow = M.dangling(_manifest("0" * 40), shallow)
        check("t14 a fabricated SHA in a SHALLOW clone is unchecked, and that is "
              "the cost stated rather than hidden: the fix cannot tell a lie from "
              "a truncation, so it declines to tell either. Named here so nobody "
              "later reads t13 as covering both clones",
              _bogus_shallow["missing"] == []
              and len(_bogus_shallow["unchecked"]) == 1, _bogus_shallow)
        _notrepo = os.path.join(tmp, "plain-dir")
        os.makedirs(_notrepo)
        _nr = M.dangling(_manifest("0" * 40), _notrepo)
        check("t16 the fail-safe direction, pinned where it has a CONSEQUENCE: a "
              "git_root that is a directory but not a repository makes "
              "is_shallow() answer None, and every recorded SHA is then "
              "unchecked. Without that, a place with no repository at all would "
              "report a fabricated commit - an accusation from a question that "
              "was never answerable: %r" % (_nr,),
              _nr["missing"] == [] and _nr["unreachable"] == []
              and len(_nr["unchecked"]) == 1)
        check("t15 git refusing to say is treated as shallow, not as full - "
              "guessing 'not truncated' would restore the false accusation on "
              "the machine least able to argue with it",
              M.is_shallow(os.path.join(tmp, "nope-not-a-repo")) is None)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__commit_trail.py --selftest\n")
    raise SystemExit(2)
