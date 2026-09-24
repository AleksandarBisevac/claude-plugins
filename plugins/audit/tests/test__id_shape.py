#!/usr/bin/env python3
"""
The cases for `_id_shape.py` - what an id looks like, and which one to mint next.

The property that matters is between branches, so the fixtures are pairs: the same
manifest, the same next number, two branch names - and the two ids must differ,
while the development branch keeps minting exactly what it minted before.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _id_shape as M                              # noqa: E402
import _manifest_vocab                             # noqa: E402


def _plan(**meta):
    return {"meta": dict({"version": 2}, **meta),
            "phases": [{"id": "P1", "title": "a", "tasks": [{"id": "P1.1"}, {"id": "P1.2"}]},
                       {"id": "P2", "title": "b", "parentBranch": "release/2",
                        "tasks": [{"id": "P2.1-k7m"}]},
                       {"id": "P3-q2a", "title": "c", "tasks": [{"id": "P3-q2a.1"}]}],
            "bugs": [{"id": "BUG-1"}, {"id": "BUG-4-zzz"}, {"id": "BUG-2"}]}


def _cases(check):
    plan = _plan()
    check("is1 the development branch mints no suffix - today's ids, unchanged",
          M.branch_suffix("main", plan) is None)
    check("is2 ...nor does a branch a phase names as its parent",
          M.branch_suffix("release/2", plan) is None)
    check("is3 ...and meta.developmentBranch replaces main as the trunk",
          M.branch_suffix("develop", _plan(developmentBranch="develop")) is None
          and M.branch_suffix("main", _plan(developmentBranch="develop")) is not None)
    a, b = M.branch_suffix("feature/x", plan), M.branch_suffix("feature/y", plan)
    check("is4 two feature branches get two different three-character suffixes",
          a and b and a != b and len(a) == 3 and len(b) == 3, (a, b))
    check("is5 ...drawn from [0-9a-z] only, so a lock, a shard name and a branch "
          "name all take them unchanged",
          all(c in "0123456789abcdefghijklmnopqrstuvwxyz" for c in a + b))
    check("is6 ...and the same branch always gets the same suffix",
          M.branch_suffix("feature/x", plan) == a)
    check("is7 no branch at all (no git, detached HEAD) mints no suffix",
          M.branch_suffix(None, plan) is None)
    check("is7b the branch origin/HEAD names is a trunk too - a clone of a `master` "
          "repository with no developmentBranch configured must not suffix master",
          M.branch_suffix("master", plan, origin_head="master") is None
          and M.branch_suffix("feature/x", plan, origin_head="master") == a)
    check("is7c when NO trunk branch exists in the repository at all, nothing is "
          "suffixed - there is no trunk to tell a side branch from",
          M.branch_suffix("master", plan, branches=set(["master"])) is None
          and M.branch_suffix("feature/x", plan, branches=set(["main", "feature/x"])) == a)

    check("is8 the numeric part reads through a suffix",
          M.number("BUG-4-zzz", "BUG-") == 4 and M.number("BUG-2", "BUG-") == 2
          and M.number("P3-q2a.1", "P3-q2a.") == 1 and M.number("BUG-x", "BUG-") is None)
    check("is9 the next bug is max+1 over every numeric part, suffixed or not",
          M.next_bug_id(plan, None) == "BUG-5" and M.next_bug_id(plan, a) == "BUG-5-" + a,
          (M.next_bug_id(plan, None), M.next_bug_id(plan, a)))
    check("is10 two branches minting the next bug from one base mint two different ids",
          M.next_bug_id(plan, a) != M.next_bug_id(plan, b))
    check("is11 the next task of a phase reads suffixed siblings too",
          M.next_task_id(plan, "P2", None) == "P2.2" and M.next_task_id(plan, "P2", a)
          == "P2.2-" + a, M.next_task_id(plan, "P2", a))
    check("is12 a task in a phase that already carries this branch's suffix is not "
          "suffixed twice",
          M.next_task_id(plan, "P3-q2a", "q2a") == "P3-q2a.2"
          and M.next_task_id(plan, "P3-q2a", a) == "P3-q2a.2-" + a)
    check("is13 the next phase is max+1 over every P<n>, suffixed or not",
          M.next_phase_id(set(["P1", "P2", "P3-q2a", "BF9"]), None) == "P4"
          and M.next_phase_id(set(["P1", "P3-q2a"]), a) == "P4-" + a)

    check("is14 the bug pattern accepts today's ids AND suffixed ones, and nothing else",
          all(_manifest_vocab.BUG_ID_RE.match(x) for x in ("BUG-1", "BUG-12-k7m"))
          and not any(_manifest_vocab.BUG_ID_RE.match(x) for x in
                      ("BUG-12-K7M", "BUG-12-k7", "BUG-k7m", "BUG-12-k7m-x")))

    props = {"proposals": [{"id": "PROP-2"}, {"id": "PROP-5-q2a"}, {"id": "free-form"}]}
    check("is14b the next proposal is max+1 over every PROP-<n>, suffixed or not, and "
          "a legacy free-form id is ignored rather than crashed on",
          M.next_prop_id(props, None) == "PROP-6" and M.next_prop_id(props, a)
          == "PROP-6-" + a and M.next_prop_id({}, None) == "PROP-1")
    check("is14c the proposal pattern accepts today's ids AND suffixed ones",
          _manifest_vocab.PROP_ID_RE.match("PROP-3")
          and _manifest_vocab.PROP_ID_RE.match("PROP-3-k7m")
          and not _manifest_vocab.PROP_ID_RE.match("PROP-3-K7M"))

    if not shutil.which("git"):
        _harness.skip(check, "is15-is16 current_branch against real git", "git",
                      "git is not on PATH")
        return
    tmp = tempfile.mkdtemp(prefix="id-shape-selftest-")
    held = os.environ.copy()
    os.environ.update({"HOME": tmp, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull})
    try:
        subprocess.run(["git", "init", "-q", "-b", "feature/x", tmp], check=True)
        check("is15 current_branch names the checked-out branch, even before a commit",
              M.current_branch(tmp) == "feature/x", M.current_branch(tmp))
        check("is15b suffix_here on a repository whose only branch is unborn and not a "
              "trunk mints no suffix (no trunk exists to fork from)",
              M.suffix_here(tmp, plan) is None)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "b"],
                       check=True, env=env)
        subprocess.run(["git", "-C", tmp, "branch", "main"], check=True)
        check("is15c ...and once `main` exists beside it, the side branch is suffixed",
              M.suffix_here(tmp, plan) == a, M.suffix_here(tmp, plan))
        subprocess.run(["git", "-C", tmp, "update-ref", "refs/remotes/upstream/main",
                        "HEAD"], check=True)
        subprocess.run(["git", "-C", tmp, "branch", "-D", "-q", "main"], check=True)
        check("is15d ...and a trunk known only as a remote-tracking branch of ANY remote "
              "counts - upstream/main, not only origin/main",
              M.suffix_here(tmp, plan) == a, M.suffix_here(tmp, plan))
        loose = tempfile.mkdtemp(prefix="id-shape-nogit-")
        try:
            check("is16 ...and None outside a repository", M.current_branch(loose) is None)
        finally:
            shutil.rmtree(loose, ignore_errors=True)
    finally:
        os.environ.clear()
        os.environ.update(held)
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__id_shape.py --selftest\n")
    raise SystemExit(2)
