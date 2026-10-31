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


def _git_spawns(fn, *args):
    """`(fn's answer, the argv of every git process started while it ran)`.

    Counted at `subprocess.Popen`, which `run`, `check_output` and a direct
    `Popen` all reach through the module attribute, so a read that moves from
    one spelling to another is still counted."""
    import subprocess
    real = subprocess.Popen
    seen = []

    def counting(argv, *a, **k):
        words = [argv] if isinstance(argv, str) else list(argv)
        if words and os.path.basename(str(words[0])).startswith("git"):
            seen.append(tuple(str(w) for w in words))
        return real(argv, *a, **k)
    subprocess.Popen = counting
    try:
        return fn(*args), seen
    finally:
        subprocess.Popen = real


def _branch_memo_cases(check, root):
    """The branch a verb mints under is read from git once per HEAD file: kept
    while the bytes of the HEAD file git itself reads are unchanged, asked again
    the moment they change - in a main checkout, from a subdirectory of one, and
    in a linked worktree, whose HEAD lives behind its `.git` file's `gitdir:`."""
    repo = os.path.join(root, "memo-repo")
    _harness.git(None, "init", "-q", "-b", "feature/m", repo)
    _harness.git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    sub = os.path.join(repo, "a", "b")
    os.makedirs(sub)
    M.current_branch(repo)                         # the first ask may spawn
    again, spawned = _git_spawns(M.current_branch, repo)
    check("is18 a second current_branch with the HEAD file unchanged starts no git "
          "process at all - the kept answer is reused: %r" % (spawned,),
          again == "feature/m" and spawned == [], repr((again, spawned)))
    _harness.git(repo, "branch", "feature/n")
    _harness.git(repo, "symbolic-ref", "HEAD", "refs/heads/feature/n")
    moved, spawned = _git_spawns(M.current_branch, repo)
    check("is19 SECOND DIRECTION: once HEAD names another branch the next ask "
          "answers it, and asked git to - a kept answer never outlives its HEAD file",
          moved == "feature/n" and len(spawned) >= 1, repr((moved, spawned)))
    _harness.git(repo, "checkout", "-q", "--detach", "HEAD")
    detached, _s = _git_spawns(M.current_branch, repo)
    check("is20 ...and a HEAD detached since the last ask answers None, not the "
          "branch it used to name", detached is None, repr(detached))
    _harness.git(repo, "checkout", "-q", "-b", "feature/p")
    M.current_branch(sub)
    held, spawned = _git_spawns(M.current_branch, sub)
    check("is21 from a subdirectory too: the second ask is answered from the "
          "repository's HEAD file with no git process: %r" % (spawned,),
          held == "feature/p" and spawned == [], repr((held, spawned)))
    _harness.git(repo, "checkout", "-q", "-b", "feature/q")
    turned, _s = _git_spawns(M.current_branch, sub)
    check("is22 ...and a branch switched from the top is seen from the "
          "subdirectory at once", turned == "feature/q", repr(turned))
    wt = os.path.join(root, "memo-wt")
    _harness.git(repo, "worktree", "add", "-q", "-b", "feature/w", wt)
    M.current_branch(wt)
    M.current_branch(repo)
    pair, spawned = _git_spawns(
        lambda: (M.current_branch(wt), M.current_branch(repo)))
    check("is23 a linked worktree and its main checkout each keep their own "
          "answer, and neither re-asks git while its HEAD file holds: %r"
          % (spawned,), pair == ("feature/w", "feature/q") and spawned == [],
          repr((pair, spawned)))
    _harness.git(wt, "checkout", "-q", "-b", "feature/w2")
    pair, _s = _git_spawns(
        lambda: (M.current_branch(wt), M.current_branch(repo)))
    check("is24 SECOND DIRECTION: a branch switched inside the worktree - its "
          "HEAD file behind `gitdir:`, not the main checkout's - changes the "
          "worktree's answer and leaves the main checkout's alone",
          pair == ("feature/w2", "feature/q"), repr(pair))
    _harness.git(repo, "tag", "feature/t")
    _harness.git(repo, "checkout", "-q", "-b", "feature/t")
    shortened, _s = _git_spawns(M.current_branch, repo)
    _harness.git(repo, "tag", "-d", "feature/t")
    plain, _s = _git_spawns(M.current_branch, repo)
    check("is27 an answer git shortened differently - a tag sharing the branch's "
          "name makes it print heads/<name> - is not the name the HEAD bytes spell, "
          "so it is not kept: once the tag is gone the plain name is back",
          shortened == "heads/feature/t" and plain == "feature/t",
          repr((shortened, plain)))
    other = os.path.join(root, "memo-other")
    _harness.git(None, "init", "-q", "-b", "elsewhere", other)
    os.environ["GIT_DIR"] = os.path.join(other, ".git")
    try:
        steered, spawned = _git_spawns(M.current_branch, repo)
    finally:
        os.environ.pop("GIT_DIR", None)
    check("is26 an environment steering discovery (GIT_DIR) is answered by git, "
          "never from the answer kept for the directory - the walk is not the one "
          "git makes then", steered == "elsewhere" and len(spawned) >= 1,
          repr((steered, spawned)))


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

    check("is14d a placeholder phase id is exactly P<n>-<suffix>: not a plain phase, "
          "not a task under one, not another prefix",
          M.is_placeholder_phase("P5-abc") and not any(M.is_placeholder_phase(x) for x in
                                                        ("P5", "P5-abc.1", "BF5-abc",
                                                         "P5-ABC", "P5-abcd")))

    if not shutil.which("git"):
        _harness.skip(check, "is15-is16 current_branch against real git", "git",
                      "git is not on PATH")
        return
    tmp = tempfile.mkdtemp(prefix="id-shape-selftest-")
    held = os.environ.copy()
    os.environ.update({"HOME": tmp, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull})
    try:
        _harness.git(None, "init", "-q", "-b", "feature/x", tmp, prefix=("git",))
        check("is15 current_branch names the checked-out branch, even before a commit",
              M.current_branch(tmp) == "feature/x", M.current_branch(tmp))
        check("is15b suffix_here on a repository whose only branch is unborn and not a "
              "trunk mints no suffix (no trunk exists to fork from)",
              M.suffix_here(tmp, plan) is None)
        # The author and committer identity as config rather than environment:
        # the same name and address for both, which is all the commit reads.
        _harness.git(None, "-C", tmp, "commit", "-q", "--allow-empty", "-m", "b",
                     prefix=("git", "-c", "user.name=t", "-c", "user.email=t@t"))
        _harness.git(None, "-C", tmp, "branch", "main", prefix=("git",))
        check("is15c ...and once `main` exists beside it, the side branch is suffixed",
              M.suffix_here(tmp, plan) == a, M.suffix_here(tmp, plan))
        _harness.git(None, "-C", tmp, "update-ref", "refs/remotes/upstream/main",
                     "HEAD", prefix=("git",))
        _harness.git(None, "-C", tmp, "branch", "-D", "-q", "main", prefix=("git",))
        check("is15d ...and a trunk known only as a remote-tracking branch of ANY remote "
              "counts - upstream/main, not only origin/main",
              M.suffix_here(tmp, plan) == a, M.suffix_here(tmp, plan))
        # A MOVED TASK'S OLD IDS ARE TAKEN. `move` takes the id out of its phase,
        # and an allocator counting live ids alone would hand it out again - to an
        # unrelated task that the ledger, evidence and journal rows written under
        # the old id would then attach to. The whole `movedFrom` chain counts.
        moved = {"phases": [
            {"id": "P2", "tasks": [{"id": "P2.1"}]},
            {"id": "P3", "tasks": [{"id": "P3.1"},
                                   {"id": "P3.2", "movedFrom": {
                                       "id": "P4.1", "phase": "P4",
                                       "previous": {"id": "P2.2", "phase": "P2"}}}]},
            {"id": "P4", "tasks": []}]}
        check("is17 a moved task's old ids stay taken, every link of the chain: the "
              "next P2 id is past P2.2 and the next P4 id is past P4.1: %r"
              % ((M.next_task_id(moved, "P2", None), M.next_task_id(moved, "P4", None)),),
              M.next_task_id(moved, "P2", None) == "P2.3"
              and M.next_task_id(moved, "P4", None) == "P4.2")
        loose = tempfile.mkdtemp(prefix="id-shape-nogit-")
        try:
            check("is16 ...and None outside a repository", M.current_branch(loose) is None)
            outside, spawned = _git_spawns(M.current_branch, loose)
            check("is16b ...and asked again there, with still no repository on the "
                  "way up, it starts no git process: %r" % (spawned,),
                  outside is None and spawned == [], repr((outside, spawned)))
            _harness.git(None, "init", "-q", "-b", "feature/late", loose)
            check("is25 SECOND DIRECTION: a repository created where None was the "
                  "answer is seen on the next ask - a kept refusal holds only while "
                  "no repository stands above the directory",
                  M.current_branch(loose) == "feature/late", M.current_branch(loose))
        finally:
            _harness.remove_tree(loose)
        _branch_memo_cases(check, tmp)
    finally:
        os.environ.clear()
        os.environ.update(held)
        _harness.remove_tree(tmp)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__id_shape.py --selftest\n")
    raise SystemExit(2)
