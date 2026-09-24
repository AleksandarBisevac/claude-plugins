#!/usr/bin/env python3
"""
The cases for `_merge_install.py` - what a merge-driver install is, read back.

The end-to-end install (write, re-install, uninstall, a real `git merge`) is
`test_merge_manifest.py`'s; the doctor's reading of it is `test__doctor_setup.py`'s.
What is left here is the part both of those trust without looking: where the pieces
are located, and that the shim's recorded root reads back as the root that was
written - including a root the shell had to quote.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _merge_install as M                         # noqa: E402


def _cases(check):
    loc = {"toplevel": "/r", "common_dir": "/r/.git", "manifest_rel": "docs/audit/plan.json",
           "shard_glob_rel": "docs/audit/phases/*.json"}
    lines = M.attribute_lines(loc)
    check("mi1 install owns a header and one line each for the plan and its shard glob",
          lines == [M.ATTR_HEADER, "docs/audit/plan.json merge=audit-manifest",
                    "docs/audit/phases/*.json merge=audit-manifest"], lines)
    check("mi2 git config names the shim under the common dir, run through sh",
          M.driver_value(loc) == "sh '/r/.git/%s' %%O %%A %%B %%P" % (M.SHIM_REL,),
          M.driver_value(loc))

    shim = M.shim_text("/opt/plugin root")
    check("mi3 the shim records the root on one line the reader looks for",
          "\n%s'/opt/plugin root'\n" % (M.SHIM_ROOT_KEY,) in shim, shim)
    check("mi4 ...and every exit it takes is 0 or 1 - git aborts the WHOLE merge on an "
          "exit above 128",
          all(tok in ("0", "1") for tok in
              [ln.strip().split("exit ")[1].split(";")[0].split()[0]
               for ln in shim.splitlines() if "exit " in ln]), shim)
    check("mi5 ...and its fallback is git's line merge into %A with labels",
          'git merge-file -L ours -L base -L theirs "$2" "$1" "$3"' in shim)

    if not shutil.which("git"):
        _harness.skip(check, "mi6-mi9 locate and status_facts against real git",
                      "git", "git is not on PATH")
        return
    tmp = tempfile.mkdtemp(prefix="merge-install-selftest-")
    held = os.environ.copy()
    os.environ.update({"HOME": tmp, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": os.devnull})
    try:
        loose = os.path.join(tmp, "loose", "plan.json")
        os.makedirs(os.path.dirname(loose))
        got, err = M.locate(loose)
        check("mi6 a manifest outside any work tree is an error naming it, not a location",
              got is None and "not inside a git work tree" in err, err)

        repo = os.path.join(tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        spaced = os.path.join(repo, "my plans", "plan.json")
        os.makedirs(os.path.dirname(spaced))
        got, err = M.locate(spaced)
        check("mi7 a path .gitattributes would have to quote is refused with the reason",
              got is None and "quote" in err, err)

        plan = os.path.join(repo, "docs", "audit", "plan.json")
        os.makedirs(os.path.dirname(plan))
        got, _e = M.locate(plan)
        check("mi8 a plan inside the tree locates relative to the top level, shards beside it",
              got is not None and got["manifest_rel"] == "docs/audit/plan.json"
              and got["shard_glob_rel"] == "docs/audit/phases/*.json", got)

        root = os.path.join(tmp, "it's here")
        os.makedirs(os.path.join(root, "scripts", "manifest"))
        open(os.path.join(root, "scripts", "manifest", "merge-manifest.py"), "w").close()
        os.makedirs(os.path.dirname(M.shim_path(got)))
        with open(M.shim_path(got), "w", encoding="utf-8") as fh:
            fh.write(M.shim_text(root))
        facts = M.status_facts(plan)
        check("mi9 a root the shell had to quote reads back as the root that was written",
              facts["shim_root"] == root and facts["shim_root_exists"] is True, facts)
        _replay_cases(check, tmp)
    finally:
        os.environ.clear()
        os.environ.update(held)
        shutil.rmtree(tmp, ignore_errors=True)


def _history(root):
    """A repository whose history holds the three merges the measurement must tell
    apart: one where both sides appended to the plan (a line merge conflicts), one
    where both sides changed the plan in far-apart places (it does not), and one
    where only one side touched the plan (no conflict was possible)."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        return subprocess.run(["git", "-C", root] + list(a), check=True, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE
                              ).stdout.decode().strip()

    def write(path, lines):
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    plan = "docs/audit/plan.json"
    body = ["{", '  "a": 1,'] + ['  "k%d": %d,' % (i, i) for i in range(12)] + ['  "z": 0', "}"]
    subprocess.run(["git", "init", "-q", "-b", "main", root], check=True)
    write(plan, body)
    git("add", "-A")
    git("commit", "-qm", "base")
    shas = {}
    # 1. both append at the tail -> a line merge conflicts
    git("checkout", "-qb", "b1")
    write(plan, body[:-2] + ['  "z": 0,', '  "b1": 1', "}"])
    git("commit", "-qam", "b1")
    git("checkout", "-q", "main")
    write(plan, body[:-2] + ['  "z": 0,', '  "m1": 1', "}"])
    git("commit", "-qam", "m1")
    subprocess.run(["git", "-C", root, "merge", "-q", "b1", "-m", "merge b1"], env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    write(plan, body[:-2] + ['  "z": 0,', '  "m1": 1,', '  "b1": 1', "}"])
    git("add", "-A")
    git("commit", "-qm", "merge b1 (resolved by hand)")
    shas["conflicted"] = git("rev-parse", "HEAD")
    cur = open(os.path.join(root, plan)).read().split("\n")[:-1]
    # 2. both change the plan, far apart -> clean IN THE PLAN; and both change another
    #    file on one line, so the merge itself conflicts - but not in the plan, and a
    #    measurement of the plan's cost must not count it.
    git("checkout", "-qb", "b2")
    write(plan, [cur[0], '  "a": 2,'] + cur[2:])
    write("src/y.txt", ["from b2"])
    git("add", "-A")
    git("commit", "-qm", "b2")
    git("checkout", "-q", "main")
    write(plan, cur[:-2] + ['  "b1": 2', "}"])
    write("src/y.txt", ["from main"])
    git("add", "-A")
    git("commit", "-qm", "m2")
    subprocess.run(["git", "-C", root, "merge", "-q", "b2", "-m", "merge b2"], env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    write("src/y.txt", ["from both"])
    git("add", "-A")
    git("commit", "-qm", "merge b2 (src/y.txt resolved by hand)")
    shas["clean"] = git("rev-parse", "HEAD")
    # 3. only one side touches the plan
    git("checkout", "-qb", "b3")
    write("src/x.txt", ["x"])
    git("add", "-A")
    git("commit", "-qm", "b3")
    git("checkout", "-q", "main")
    write(plan, open(os.path.join(root, plan)).read().replace('"k3": 3', '"k3": 33').split("\n")[:-1])
    git("commit", "-qam", "m3")
    git("merge", "-q", "b3", "-m", "merge b3")
    return plan, shas


def _replay_cases(check, tmp):
    root = os.path.join(tmp, "history")
    plan, shas = _history(root)
    got = M.replay_merges(root, plan)
    check("mi10 the measurement scans the repository's merges and counts, as its "
          "denominator, only those where BOTH sides changed the plan - the only ones "
          "where a conflict was possible: %r" % (got,),
          got.get("basis") is None and got["scanned"] == 3 and got["bothSides"] == 2, got)
    check("mi11 ...and of those it names exactly the one git's line merge conflicts on "
          "(both appended at the tail), not the far-apart edit",
          got.get("conflicted") == [shas["conflicted"]], got)
    fresh = os.path.join(tmp, "fresh")
    subprocess.run(["git", "init", "-q", fresh], check=True)
    got_fresh = M.replay_merges(fresh, "docs/audit/plan.json")
    check("mi13 a repository with no commit yet has nothing to measure - and is not "
          "reported as a git too old to measure with: %r" % (got_fresh,),
          got_fresh.get("basis") is None and got_fresh.get("scanned") == 0, got_fresh)
    check("mi14 git's version is read from `git --version`, and 2.38 is the floor "
          "`merge-tree --write-tree` needs",
          M.git_version_ok("git version 2.50.1 (Apple Git-155)")
          and M.git_version_ok("git version 2.38.0")
          and not M.git_version_ok("git version 2.37.9")
          and not M.git_version_ok("garbage"))
    got_none = M.replay_merges(root, "docs/audit/other.json")
    check("mi12 a plan no merge changed on both sides has a zero denominator, which the "
          "caller must read as 'nothing to measure', not as 'no conflicts'",
          got_none.get("bothSides") == 0 and got_none.get("conflicted") == [], got_none)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__merge_install.py --selftest\n")
    raise SystemExit(2)
