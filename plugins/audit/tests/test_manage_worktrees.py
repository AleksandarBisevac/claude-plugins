#!/usr/bin/env python3
"""
The cases for `manage-worktrees.py` — the account of what `/audit:worktree` created.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The two do-nothing outcomes, in BOTH directions.** "There was no worktree to
  look at" (exit 5) and "every worktree was examined and none needed anything"
  (exit 0) are two states of the world that an empty action list renders identically.
  One case asserts each, and the second is the one that looks vacuous and is the only
  one that fails when the empty branch becomes unconditional.
- **A stranger survives AND is named.** Surviving without being named is a silent
  skip, and a silent skip over somebody's unrelated worktree is indistinguishable
  from not having looked.
- **Provenance, in BOTH directions.** The same repository is swept or spared by the
  presence of one marker file. A single case either way would prove nothing: "the
  sweep refused" and "the sweep checks whose worktree it is" look identical from one
  side. `--include-strangers` was tested here once and is gone with the flag — it
  adopted foreign worktrees on a guessed parent, which is the property these cases
  now forbid.
- **Settlement, one mark at a time.** Sign-off not passed, a task still open, no
  `mergedAt` — each spares the worktree and each names ITS own reason, because
  "not cleaned up" without saying which mark is missing is a report nobody can act
  on.
- **`--apply` with no verb is a usage error.** "Sweep everything" is never inferred
  from having found something to do.
- **The phase id is sanitised into the directory name**, which the prose never did:
  an id carrying a path separator composed a path outside the intended parent.
- **`remove` refuses a dirty tree, an unreadable tree, and the tree it is standing
  in** — the last of which git does not ask about at all.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("manage-worktrees.py")

# The phases are SETTLED by construction — signed off, no task left open, mergedAt
# recorded — because `cleanup_plan` fails closed and a fixture that left any of the
# three out would refuse every sweep and pass its assertions for the wrong reason.
# The cases that WITHHOLD settlement say so in their own phase dict.
PLAN = {"meta": {"developmentBranch": "dev", "branchPrefix": "audit"},
        "phases": [{"id": "P2", "title": "Two", "branch": "audit/p2-two",
                    "status": "done", "mergedAt": "2026-01-01T00:00:00Z",
                    "tasks": [{"id": "P2.1", "status": "done"}]},
                   {"id": "P3", "title": "Three", "branch": "audit/p3-three",
                    "parentBranch": "release/1.2",
                    "status": "done", "mergedAt": "2026-01-01T00:00:00Z",
                    "tasks": []}]}

LIST = ("worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n\n"
        "worktree /wt-p2\nHEAD bbb\nbranch refs/heads/audit/p2-two\n\n"
        "worktree /wt-x\nHEAD ccc\nbranch refs/heads/somebody/else\n")
ONLY_MAIN = "worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n"


def _fake(script, listing=LIST, admin_root=None, ours=()):
    """A recording git. `admin_root` + `ours` make provenance REAL rather than
    stubbed: `rev-parse --git-dir` answers a directory under `admin_root`, and a
    marker file is written into the ones named in `ours`. The product reads the
    filesystem, so a fixture that faked the read would be asserting the fake."""
    calls = []
    if admin_root:
        # CLEARS FIRST, then writes. The fixture root is shared across cases, so a
        # version that only added would leave an earlier case's marker in place and
        # the "no provenance" case would pass or fail depending on what ran before
        # it. Setting the state is the only form of this that means anything.
        for name in (os.listdir(admin_root) if os.path.isdir(admin_root) else []):
            marker = os.path.join(admin_root, name, M._wt.PROVENANCE_FILE)
            if os.path.isfile(marker):
                os.remove(marker)
        # THE MARKER CARRIES THE BRANCH THE LISTING SAYS THAT PATH HOLDS, read out
        # of `listing` rather than written twice: the provenance gate compares the
        # two (F246), so a fixture that invented a branch here would be asserting
        # its own invention. `ours` may name a path with an explicit branch as a
        # pair, which is how the mismatch case is driven.
        held = {}
        for block in listing.split("\n\n"):
            path_line = [ln for ln in block.split("\n")
                         if ln.startswith("worktree ")]
            br_line = [ln for ln in block.split("\n") if ln.startswith("branch ")]
            if path_line and br_line:
                held[path_line[0].split(" ", 1)[1]] = \
                    br_line[0].split(" ", 1)[1].replace("refs/heads/", "")
        for entry in ours:
            path, branch = entry if isinstance(entry, tuple) else \
                (entry, held.get(entry, ""))
            adm = os.path.join(admin_root, os.path.basename(path))
            if not os.path.isdir(adm):
                os.makedirs(adm)
            with open(os.path.join(adm, M._wt.PROVENANCE_FILE), "w") as fh:
                fh.write(json.dumps({"createdBy": "audit", "phaseId": "P2",
                                     "branch": branch}))

    def key_of(args):
        rest = args[2:] if len(args) > 2 and args[0] == "-C" else args
        return " ".join(rest[:2])

    def run(git_root, args, timeout=None):
        calls.append(list(args))
        if args[:2] == ["worktree", "list"]:
            return (0, listing.replace("\n", "\0") if "-z" in args else listing, "")
        if args[:2] == ["rev-parse", "--git-dir"] and admin_root:
            return (0, os.path.join(admin_root,
                                    os.path.basename(git_root or "")) + "\n", "")
        return script.get(key_of(args), script.get("*", (0, "", "")))
    return run, calls


def _cases(check):
    root = _harness.fixture_root("mwt")
    try:
        _run_cases(check, root)
    finally:
        _harness.remove_tree(root)


def _run_cases(check, root):
    # Provenance lives on disk, so the fixture puts it there. `_f` is `_fake` with
    # the admin root wired in and `/wt-p2` marked as ours, which is the state every
    # case below assumes unless it says otherwise.
    def _f(script, listing=LIST, ours=("/wt-p2",)):
        return _fake(script, listing=listing, admin_root=root, ours=ours)

    # --- the plan's own branches ----------------------------------------------
    wanted = M.wanted_branches(PLAN)
    check("w1 a phase's RECORDED branch wins over a composed one - a phase that ran "
          "has the name git actually got, and re-composing can differ for a plan "
          "whose convention changed mid-flight",
          wanted == {"audit/p2-two": "P2", "audit/p3-three": "P3"},
          repr(wanted))
    parents = M.parents_of(PLAN)
    check("w2 the parent is resolved PER PHASE, so a phase integrating into a story "
          "branch is judged against THAT - asking 'is it in the development "
          "branch' would keep a correctly landed phase for ever",
          parents["audit/p3-three"] == "release/1.2"
          and parents["audit/p2-two"] == "dev",
          repr(parents))

    # --- the path convention, with the sanitising the prose never did ---------
    check("p1 the default path is the documented `../<repo>-<phaseId>` shape",
          os.path.basename(M.default_path("/x/myrepo", "P2")) == "myrepo-P2",
          M.default_path("/x/myrepo", "P2"))
    # The property is CONTAINMENT, not the absence of a dot: `myrepo-..-etc` is an
    # ordinary directory name, and asserting `".." not in path` fails a correct
    # implementation while saying nothing about the thing that matters.
    #
    # THE EXPECTED PARENT IS DERIVED, NOT WRITTEN. `default_path` runs its argument
    # through `os.path.abspath`, so on Windows `/x/myrepo` comes back as
    # `C:\x\myrepo` and a literal `"/x"` compares a resolved path against an
    # unresolved one. That is what turned this case red on windows-latest while
    # ubuntu and macOS stayed green, and the code under test was correct the whole
    # time - the assertion was the platform-bound half.
    #
    # BOTH SEPARATORS, for the same reason one level down: `os.sep` is `/` here and
    # `\` there, so a check against it proves the neutralising of whichever
    # separator the RUNNER has and says nothing about the other one. A manifest
    # travels between machines and a phase id carrying `a\b` is a traversal on
    # Windows and an ordinary name here, so both spellings belong in the ids below
    # and in the assertion.
    _wt_root = "/x/myrepo"
    _wt_parent = os.path.dirname(os.path.abspath(_wt_root))
    check("p2 a hostile phase id still composes a path in the SAME parent "
          "directory and a basename with neither separator in it - "
          "`migrate-manifest.py` already checks this for shard filenames and the "
          "worktree path never did",
          all(os.path.dirname(M.default_path(_wt_root, pid)) == _wt_parent
              and "/" not in os.path.basename(M.default_path(_wt_root, pid))
              and "\\" not in os.path.basename(M.default_path(_wt_root, pid))
              for pid in ("../../etc", "a/b", "a\\b", "..\\..\\etc",
                          "..", ".", "", "  ")),
          repr([M.default_path(_wt_root, p)
                for p in ("../../etc", "a\\b", "..", "")]))
    check("p3 ...and an id that sanitises away to nothing still yields a NAME "
          "rather than a bare `myrepo-`, which would be the parent's sibling with "
          "a trailing separator and reads as a mistake in every listing",
          os.path.basename(M.default_path("/x/myrepo", "///")) == "myrepo-phase",
          M.default_path("/x/myrepo", "///"))

    # --- sweep: the two do-nothing states -------------------------------------
    run, _c = _f({}, listing=ONLY_MAIN)
    code, ans = M.do_sweep("/repo", PLAN, ("removeWorktrees",), run=run)
    check("s1 a repository with no linked worktree exits 5 and says examined=0 - "
          "NOT 0 with an empty list, which reads as 'everything is clean' about a "
          "repository where nothing was looked at",
          code == M.E_NOTHING and ans["examined"] == 0 and ans["empty"] is True,
          "exit=%d examined=%d" % (code, ans["examined"]))
    run, _c = _f({"merge-base --is-ancestor": (1, "", ""),
                     "status --porcelain": (0, "", "")})
    code, ans = M.do_sweep("/repo", PLAN, ("removeWorktrees", "deleteBranches"),
                           run=run)
    check("s2 ...and the OTHER direction: worktrees WERE examined and none needed "
          "anything, so exit 0 and empty is False. This is the case that looks "
          "vacuous and is the only one that fails when the empty branch becomes "
          "unconditional",
          code == M.E_OK and ans["empty"] is False and ans["actions"] == []
          and ans["examined"] > 0,
          "exit=%d examined=%d empty=%r" % (code, ans["examined"], ans["empty"]))
    check("s3 ...and each kept worktree carries a reason, so a sweep that did "
          "nothing does not leave the reader to infer health from a number",
          ans["kept"] and ans["kept"][0]["reasons"],
          ans["kept"][0]["reasons"][0]["why"][:60])
    check("s4 the stranger is reported and NOT swept - surviving without being "
          "named is a silent skip over somebody's unrelated worktree",
          len(ans["strangers"]) == 1
          and ans["strangers"][0]["branch"] == "somebody/else",
          repr([r["branch"] for r in ans["strangers"]]))

    # --- sweep: the contained-and-clean case ----------------------------------
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                     "status --porcelain": (0, "", "")})
    code, ans = M.do_sweep("/repo", PLAN, ("removeWorktrees", "deleteBranches"),
                           run=run)
    check("s5 a contained, clean worktree is planned for removal THEN branch "
          "deletion - the allow case, without which every refusal above could be "
          "a sweep that refuses everything",
          len(ans["actions"]) == 1
          and [x["action"] for x in ans["actions"][0]["steps"]]
          == ["worktree-remove", "branch-delete"],
          repr([x["action"] for x in ans["actions"][0]["steps"]]))
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                     "status --porcelain": (0, "?? .env\n", "")})
    code, ans = M.do_sweep("/repo", PLAN, ("removeWorktrees", "deleteBranches"),
                           run=run)
    check("s6 a CONTAINED branch whose worktree is DIRTY is spared and its files "
          "named - the one-axis sweep ('merged, therefore go') destroys this, and "
          "it is the case the 2026-08-26 hand-prune had to prove by hand over six "
          "hundred lines",
          ans["actions"] == [] and ans["kept"][0]["dirtyLines"] == ["?? .env"],
          repr(ans["kept"][0]["dirtyLines"]))
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                     "status --porcelain": (128, "", "fatal: no\n")})
    code, ans = M.do_sweep("/repo", PLAN, ("removeWorktrees",), run=run)
    check("s7 a worktree whose dirtiness could not be READ is kept, never removed "
          "- 'clean' and 'unreadable' are the two answers a boolean renders "
          "identically, and one of them is irreversible",
          ans["actions"] == [], repr([a["path"] for a in ans["actions"]]))

    # --- provenance: the sweep may only reap what the plugin started ----------
    # `--include-strangers` used to be tested here. The flag is gone and so are its
    # cases; what replaced them asserts the property the flag violated.
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")}, ours=())
    code, unowned = M.do_sweep("/repo", PLAN, ("removeWorktrees",), run=run)
    check("x1 a worktree with NO provenance marker is never reaped, however "
          "cleanly its branch landed and however settled its phase - the plugin "
          "only removes what it started, and a worktree somebody opened by hand "
          "is indistinguishable from ours by branch name and merge state",
          unowned["actions"] == [], repr([a["path"] for a in unowned["actions"]]))
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")})
    code, owned = M.do_sweep("/repo", PLAN, ("removeWorktrees",), run=run)
    check("x2 ...and the SAME repository with the marker present does reap it. The "
          "pair is what separates 'the plugin refuses to sweep' from 'the plugin "
          "checks whose worktree it is' - one case alone proves neither",
          len(owned["actions"]) == 1
          and owned["actions"][0]["path"] == "/wt-p2",
          "unowned=%d owned=%d" % (len(unowned["actions"]),
                                   len(owned["actions"])))
    # F246. The marker names the phase and the branch it was written for, and only
    # `createdBy` used to be read - so the worktree-to-phase join was made from
    # whatever branch git reports NOW. An operator who runs `git switch` inside a
    # phase worktree to look at something hands that still-open directory to another
    # phase's settlement verdict, and it goes with its ignored files.
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")},
                 ours=(("/wt-p2", "audit/p9-elsewhere"),))
    code, moved = M.do_sweep("/repo", PLAN, ("removeWorktrees",), run=run)
    check("x2b ...and a marker written for a DIFFERENT branch does not authorise "
          "this one. Same repository, same clean tree, same settled phase as x2 - "
          "the only difference is which job the marker describes",
          moved["actions"] == [],
          repr([a["path"] for a in moved["actions"]]))
    check("x2c ...and the reason names the phase and branch the marker was "
          "written for AND the branch found in the tree. 'not ours' would send the "
          "reader looking for a colleague who does not exist",
          moved["kept"] and any("audit/p9-elsewhere" in r["why"]
                                and "audit/p2-two" in r["why"]
                                for r in moved["kept"][0]["reasons"]),
          repr([r["why"][:120] for r in (moved["kept"][0]["reasons"]
                                         if moved["kept"] else [])]))
    unsettled = {"meta": PLAN["meta"],
                 "phases": [dict(PLAN["phases"][0], status="in_progress")]}
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")})
    code, running = M.do_sweep("/repo", unsettled, ("removeWorktrees",), run=run)
    check("x3 OUR worktree whose phase has not signed off is kept, and the reason "
          "names sign-off rather than the branch - a phase can be merged early and "
          "still be running, and that worktree is where the work is",
          running["actions"] == []
          and any("sign-off" in r["why"] for r in running["kept"][0]["reasons"]),
          running["kept"][0]["reasons"][0]["why"][:70])
    open_task = {"meta": PLAN["meta"],
                 "phases": [dict(PLAN["phases"][0],
                                 tasks=[{"id": "P2.1", "status": "done"},
                                        {"id": "P2.9", "status": "in_progress"}])]}
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")})
    code, busy = M.do_sweep("/repo", open_task, ("removeWorktrees",), run=run)
    check("x4 ...nor one whose phase is marked done while a task is still open, "
          "and the unfinished task is NAMED so the reader knows where to look",
          busy["actions"] == []
          and any("P2.9" in r["why"] for r in busy["kept"][0]["reasons"]),
          busy["kept"][0]["reasons"][0]["why"][:70])
    no_stamp = {"meta": PLAN["meta"],
                "phases": [dict(PLAN["phases"][0], mergedAt=None)]}
    run, _c = _f({"merge-base --is-ancestor": (0, "", ""),
                  "status --porcelain": (0, "", "")})
    code, unstamped = M.do_sweep("/repo", no_stamp, ("removeWorktrees",), run=run)
    check("x5 ...nor one whose phase records no mergedAt. 'The branch is "
          "contained' is a different claim, and a cherry-pick or an early merge "
          "makes it true about work the plugin never signed off",
          unstamped["actions"] == [], repr(unstamped["actions"]))

    # --- remove: our questions before git's ------------------------------------
    run, calls = _f({"status --porcelain": (0, " M a.py\n", "")})
    code, ans = M.do_remove("/repo", PLAN, "P2", run=run)
    check("r1 a dirty worktree is refused BY NAME and no removal is attempted, and "
          "the remedy warns that removal destroys IGNORED files git status never "
          "mentioned",
          code == M.E_FAIL and "a.py" in ans["error"]
          and "IGNORED" in ans["remedy"]
          and not any(c[:2] == ["worktree", "remove"] for c in calls),
          ans["error"][:60])
    run, calls = _f({"status --porcelain": (128, "", "fatal: no\n")})
    code, ans = M.do_remove("/repo", PLAN, "P2", run=run)
    check("r2 a tree git will not describe is refused too - an unanswered question "
          "is not a clean tree",
          code == M.E_FAIL
          and not any(c[:2] == ["worktree", "remove"] for c in calls),
          ans["error"][:60])
    run, calls = _f({"status --porcelain": (0, "", "")})
    code, ans = M.do_remove("/repo", PLAN, "P2", run=run)
    check("r3 ...and a CLEAN tree IS removed, without --force. The allow case",
          code == M.E_OK
          and any(c[:2] == ["worktree", "remove"] and "--force" not in c
                  for c in calls),
          repr(ans.get("removed")))
    check("r4 ...and the answer states that the BRANCH is untouched - `worktree "
          "remove` never deletes one and `prune` does not either, which is how "
          "every abandoned run leaves an orphan branch behind",
          "BRANCH is untouched" in ans["note"], ans["note"][:50])
    code, ans = M.do_remove("/repo", PLAN, "P9",
                            run=_fake({})[0])
    check("r5 a phase the plan does not have is a USAGE error, not a failure - "
          "there is nothing wrong with the repository",
          code == M.E_USAGE, "exit=%d" % (code,))

    # --- add: preflight before git's three different exit codes ---------------
    run, calls = _f({})
    code, ans = M.do_add("/repo", PLAN, "P2", run=run)
    check("a1 adding a worktree for a branch already checked out elsewhere is "
          "refused by us, naming the path - git says the same thing with exit "
          "128, and three of its refusals here carry three different codes",
          code == M.E_FAIL and "/wt-p2" in ans["error"],
          ans["error"][:60])
    run, calls = _f({"rev-parse --verify": (1, "", "")})
    code, ans = M.do_add("/repo", PLAN, "P3", path="/tmp/does-not-exist-p3",
                         run=run)
    check("a2 a branch that does not exist yet is CREATED from the phase's "
          "resolved parent, and one that exists is checked out without -b",
          code == M.E_OK and "-b" in ans["argv"]
          and ans["parent"] == "release/1.2",
          repr(ans["argv"]))
    run, calls = _f({"rev-parse --verify": (0, "sha\n", "")})
    code, ans = M.do_add("/repo", PLAN, "P3", path="/tmp/does-not-exist-p3",
                         run=run)
    check("a3 ...and an EXISTING branch drops -b, which is what the prose told a "
          "human to do by hand",
          code == M.E_OK and "-b" not in ans["argv"], repr(ans["argv"]))

    # --- the CLI grammar ------------------------------------------------------
    class _P(object):
        rm_wt = rm_br = prune = False
    check("v1 no verb named yields an EMPTY tuple, which the caller refuses on - "
          "'sweep everything' is not inferred from having found something to do",
          M.verbs_from(_P()) == (), repr(M.verbs_from(_P())))
    _P.rm_wt = True
    check("v2 ...and a named verb comes back by name",
          M.verbs_from(_P()) == ("removeWorktrees",), repr(M.verbs_from(_P())))

    lines = []
    code = M.main(["sweep", "docs/audit/audit-plan.json", "--apply"],
                  out=lines.append)
    check("v3 `--apply` with no verb is a USAGE error and writes nothing - the "
          "irreversible half needs an explicit ask, because `git worktree remove` "
          "destroys ignored files a status never mentioned",
          code == M.E_USAGE and lines == [], "exit=%d" % (code,))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_manage_worktrees.py --selftest\n")
    raise SystemExit(2)
