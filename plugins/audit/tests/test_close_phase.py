#!/usr/bin/env python3
"""
The cases for `close-phase.py` — sign-off 5c–5e, and the four ways it can end.

WHAT IS PINNED, and why each one is here rather than trusted:

- **`meta.merge.auto: false` exits 0.** It is a switch, not a failure: the phase is
  reviewed, gated and committed, and the merge is somebody else's to make. An exit
  code that called it a failure would make the human-in-the-loop path indistinguishable
  from a refusal, and every wrapper would learn to ignore both.
- **...and that path writes NOTHING.** `mergedAt` on a phase that did not merge is
  worse than silence, because every later reader treats it as landed. The case counts
  the git calls, not just the exit code.
- **Not-a-fast-forward is exit 3 and could-not-be-asked is exit 4.** Two sentinels,
  because a caller acts differently on each and folding either into 1 makes it
  indistinguishable from "the tree was dirty".
- **The verification asks a DIFFERENT question than the write.** A fake runner whose
  merge succeeds but whose ancestry still answers `not-contained` must NOT be reported
  as merged — otherwise the check is the merge command grading its own homework.
- **Cleanup stops at the first refusal**, because the steps are ordered and git
  enforces the order: continuing would attempt the thing that cannot work and report
  a second error for the first one's reason.
- **`git switch` never appears in any recorded argv, in any mode.** The single
  assertion that keeps the whole design honest.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _worktrees as W                             # noqa: E402

M = _loader.load_script("close-phase.py")

MAIN = ("worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n\n"
        "worktree /wt-p2\nHEAD bbb\nbranch refs/heads/feature/p2\n")
TREES = W.parse_list(MAIN)
NOWT = W.parse_list("worktree /repo\nHEAD aaa\nbranch refs/heads/dev\n")
# The parent checked out NOWHERE: the main worktree sits on an unrelated branch and
# the phase has its own tree. This is the shape the no-checkout merge is for, and the
# only shape in which `ref_exists` is even asked.
ORPHAN = W.parse_list("worktree /repo\nHEAD aaa\nbranch refs/heads/other\n\n"
                      "worktree /wt-p2\nHEAD bbb\nbranch refs/heads/feature/p2\n")


def _fake(script):
    """A recording git. `script` maps the first two argv words to (code, out, err);
    `calls` is what the run actually attempted, which is what several cases COUNT
    rather than merely inspect."""
    calls = []

    def key_of(args):
        # A LEADING `-C <path>` IS ADDRESSING, NOT THE VERB. The in-parent-worktree
        # merge runs as `-C <that tree> merge --ff-only <branch>`, so keying on the
        # first two words alone matched nothing and every such call fell through to
        # the catch-all success. Several cases passed for that reason rather than
        # for their own, which is the failure a fixture is least able to announce.
        rest = args[2:] if len(args) > 2 and args[0] == "-C" else args
        return " ".join(rest[:2])

    def run(git_root, args, timeout=None):
        calls.append(list(args))
        return script.get(key_of(args), script.get("*", (0, "", "")))
    return run, calls


OWNED_OK = {"ok": True, "why": "fixture: the plugin created this worktree"}
SETTLED_OK = {"ok": True, "why": "fixture: signed off, no open task, merge verified"}


def _obs(contained, trees=None, parent_dirty=False, phase_dirty=False,
         parent_exists=True, owned=None, settled=None):
    """An observation, assembled by hand so a case can drive a state a fixture
    cannot reach — a parent ref that does not resolve, a tree git will not describe."""
    trees = TREES if trees is None else trees
    return {
        "trees": trees,
        "contained": {"answer": contained, "basis": "fake", "detail": ""},
        "parentExists": {"exists": parent_exists, "sha": "x", "basis": "fake"},
        "parentTree": W.holder_of(trees, "dev")["tree"],
        "phaseTree": W.holder_of(trees, "feature/p2")["tree"],
        "parentDirty": {"dirty": parent_dirty, "lines": [], "basis": "fake"},
        "phaseDirty": {"dirty": phase_dirty, "lines": [], "basis": "fake"},
        "standingIn": None,
        # Supplied, because `cleanup_plan` fails CLOSED without them: a case that
        # omitted these would refuse every cleanup and pass its assertions for a
        # reason that has nothing to do with what it claims to measure.
        "owned": owned if owned is not None else OWNED_OK,
        "settled": settled if settled is not None else SETTLED_OK,
        "why": "",
    }


ALL_ON = {"auto": True, "removeWorktree": True, "deleteBranch": True}
NO_AUTO = {"auto": False, "removeWorktree": True, "deleteBranch": True}


def _cases(check):
    # --- resolve: names, each with the key that produced it -------------------
    meta = {"developmentBranch": "dev"}
    r = M.resolve({"meta": meta}, {"id": "P2", "branch": "feature/p2"})
    check("r1 a recorded phase.branch is used as-is and says so - composing a name "
          "for a phase that already has one is how a run ends up on a second branch",
          r["branch"] == "feature/p2" and r["branchBasis"] == "phase.branch",
          "%s / %s" % (r["branch"], r["branchBasis"]))
    check("r2 the parent comes from the manifest chain and carries ITS key",
          r["parent"] == "dev" and r["parentBasis"] == "meta.developmentBranch",
          "%s / %s" % (r["parent"], r["parentBasis"]))
    ro = M.resolve({"meta": meta}, {"id": "P2", "branch": "feature/p2"},
                   parent_arg="release/1.2")
    check("r3 an override reports basis `argument`, NOT the manifest key it "
          "replaced - a claim the manifest does not support must not wear the "
          "manifest's name",
          ro["parent"] == "release/1.2" and "argument" in ro["parentBasis"],
          ro["parentBasis"])
    check("r4 the policy travels with the names, so one read of meta decides both "
          "where this goes and what happens after",
          r["policy"]["auto"] is True, repr(r["policy"]["auto"]))

    # --- auto: false, the human-in-the-loop exit ------------------------------
    run, calls = _fake({})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", NO_AUTO)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("a1 meta.merge.auto false exits 0 - it is a SWITCH, not a failure. A "
          "phase reviewed, gated and committed but deliberately unmerged is a real "
          "state, and an exit code calling it a failure makes every wrapper learn "
          "to ignore both it and a genuine refusal",
          code == M.E_OK and ans["pending"] is True,
          "exit=%d pending=%r" % (code, ans["pending"]))
    check("a2 ...and it ran NO git command at all - COUNTED, because 'did not "
          "merge' and 'merged and did not say so' produce the same exit code and "
          "only one of them leaves the branch where the operator expects it",
          calls == [], repr(calls))
    check("a3 ...and it hands over the exact command, so the human is not left to "
          "reconstruct it from the mode name",
          ans["command"].startswith("git "), ans["command"])

    # --- already contained: zero writes ---------------------------------------
    run, calls = _fake({})
    p = M.plan(_obs(W.CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("b1 an ALREADY CONTAINED branch makes no merge call - the fetch path "
          "cannot see this state and would report `! [rejected] "
          "(non-fast-forward)` exit 1 for a phase that had already landed",
          not any(c[:1] == ["fetch"] or "merge" in c for c in calls),
          repr(calls))
    check("b2 ...and it still exits 0: the parent contains the branch, which is "
          "the question this command answers",
          code == M.E_OK, "exit=%d" % (code,))

    # --- the merge itself -----------------------------------------------------
    run, calls = _fake({"merge --ff-only": (0, "Fast-forward\n", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("c1 a parent held by another worktree is merged THERE, with -C naming "
          "that path - `git switch dev` from inside the phase worktree fails with "
          "`fatal: 'dev' is already used by worktree at '/repo'`",
          calls[0][:2] == ["-C", "/repo"] and "--ff-only" in calls[0],
          repr(calls[0]))
    check("c2 ...and the run VERIFIES by asking the ancestry again, which is a "
          "different question from the one the merge answered. A check that read "
          "the merge's own output back would be the command grading itself",
          any(c[:1] == ["merge-base"] for c in calls[1:]),
          repr([c[0] for c in calls]))
    check("c3 a successful merge and a verified containment exit 0 and report "
          "merged",
          code == M.E_OK and ans["merged"] is True,
          "exit=%d merged=%r" % (code, ans["merged"]))

    # --- the merge SUCCEEDED and the ancestry still says no -------------------
    run, calls = _fake({"merge --ff-only": (0, "Fast-forward\n", ""),
                        "merge-base --is-ancestor": (1, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("c4 a merge that reported success while the parent still does NOT "
          "contain the branch is a failure - this is the case that proves the "
          "verification is real rather than decorative, and it cannot be reached "
          "by a check that reads the merge's exit code twice",
          code == M.E_FAIL and ans["merged"] is True
          and not ans.get("cleanupDone"),
          "exit=%d cleanup=%r" % (code, ans.get("cleanupDone")))

    # --- not a fast-forward: its own sentinel ---------------------------------
    run, calls = _fake({"merge --ff-only":
                        (128, "", "fatal: Not possible to fast-forward\n"),
                        "merge-base --is-ancestor": (1, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("d1 a refused merge whose branch is still not contained exits 3, not 1 "
          "- the parent moved while the phase ran, which is the normal case on a "
          "team repo and has a human question attached. Folded into 1 it reads as "
          "'the tree was dirty', which is a different conversation",
          code == M.E_NOT_FF, "exit=%d" % (code,))
    check("d2 ...and NOTHING was cleaned up on that path: an unmerged branch keeps "
          "its worktree and its name",
          not ans.get("cleanupDone"), repr(ans.get("cleanupDone")))

    # --- could not be asked ---------------------------------------------------
    run, calls = _fake({"merge --ff-only": (None, "", "git is not on PATH")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("e1 a git that could not be RUN exits 4, not 1 - 'git refused' and 'git "
          "could not be asked' are different states of the world, and a caller "
          "that cannot tell them apart retries the wrong one",
          code == M.E_NO_BASIS, "exit=%d" % (code,))
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (128, "", "fatal: bad ref\n")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("e2 ...and an UNVERIFIABLE result is 4 as well, never 0: a merge nobody "
          "could confirm must not stamp the plan",
          code == M.E_NO_BASIS, "exit=%d" % (code,))

    # --- refusals decided before any write ------------------------------------
    run, calls = _fake({})
    p = M.plan(_obs(W.UNKNOWN), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("f1 an UNKNOWN containment refuses BEFORE writing - a could-not-ask is "
          "never a merge, and the repository is left exactly as it was found",
          code == M.E_FAIL and calls == [], "exit=%d calls=%r" % (code, calls))
    run, calls = _fake({})
    # The parent must be checked out NOWHERE for this case to reach the ref-exists
    # question at all: a worktree holding the branch IS proof the branch exists, so
    # the in-parent-worktree path never asks. Getting that wrong was the first
    # version of this case, and it passed against a correct implementation.
    p = M.plan(_obs(W.NOT_CONTAINED, parent_exists=False, trees=ORPHAN),
               "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("f2 an absent parent ref refuses and runs nothing - measured, `git fetch "
          ". <b>:<p>` would CREATE the branch, print `* [new branch]` and exit 0, "
          "so the phase would report as merged into a branch it had invented",
          code == M.E_FAIL and calls == [], "exit=%d calls=%r" % (code, calls))
    run, calls = _fake({"fetch .": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED, trees=ORPHAN), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("f3 ...and the ALLOW case for f2: a parent that DOES exist and is held "
          "nowhere is fast-forwarded without a checkout, and the refspec carries "
          "no leading '+'",
          code == M.E_OK and calls[0][:2] == ["fetch", "."]
          and not calls[0][2].startswith("+"),
          repr(calls[0]))

    # --- cleanup --------------------------------------------------------------
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("g1 cleanup runs worktree removal BEFORE branch deletion - asserted as "
          "an index comparison over the recorded calls, because 'both happened' "
          "passes on exactly the order git rejects",
          ans["cleanupDone"] == ["worktree-remove", "branch-delete"],
          repr(ans["cleanupDone"]))
    check("g2 ...and prune runs only after something was actually removed, so a "
          "no-op run does not look like it did work",
          any(c[:2] == ["worktree", "prune"] for c in calls), repr(calls[-1]))
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", ""),
                        "worktree remove": (128, "", "fatal: contains modified "
                                            "or untracked files\n")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("g3 a refused worktree removal STOPS the cleanup - continuing would "
          "attempt `git branch -d` on a branch whose worktree still stands, which "
          "git refuses for the first refusal's own reason",
          code == M.E_FAIL and ans["cleanupDone"] == []
          and not any(c[:2] == ["branch", "-d"] for c in calls),
          "exit=%d done=%r" % (code, ans["cleanupDone"]))
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON,
               want_worktree=False, want_branch=False)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                            settled_now=SETTLED_OK)
    check("g4 a merge with cleanup switched off merges and cleans nothing - the "
          "allow case for every refusal above, and the proof that cleanup is never "
          "implied by a successful merge",
          code == M.E_OK and ans["cleanupDone"] == []
          and any("--ff-only" in c for c in calls),
          "exit=%d done=%r" % (code, ans["cleanupDone"]))

    # --- the invariant that keeps the design honest ---------------------------
    every = []
    for policy in (ALL_ON, NO_AUTO):
        for state in (W.CONTAINED, W.NOT_CONTAINED, W.UNKNOWN):
            for trees in (TREES, NOWT):
                run, calls = _fake({"merge --ff-only": (0, "", ""),
                                    "fetch .": (0, "", ""),
                                    "merge-base --is-ancestor": (0, "", "")})
                pl = M.plan(_obs(state, trees=trees), "feature/p2", "dev", policy)
                M.close("/repo", pl, "feature/p2", "dev", run=run)
                every.extend(calls)
    check("h1 NO run, in any policy x containment x worktree combination, ever "
          "issues `git switch` - it is unavailable from inside the worktree a "
          "phase ran in, and moving an operator's HEAD is a side effect no script "
          "takes on its own. COUNTED over every combination rather than checked on "
          "the happy path",
          not any("switch" in c for c in every),
          "%d call(s) recorded, none a switch" % (len(every),))
    check("h2 ...and no run ever forces: no `+` refspec, no `branch -D`, no "
          "`--force` anywhere",
          not any(a.startswith("+") or a in ("-D", "--force")
                  for c in every for a in c),
          "no forcing argument in any recorded call")

    # --- whose worktree, and are we finished ----------------------------------
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED,
                    owned={"ok": False,
                           "why": "no marker in its admin directory"}),
               "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                        settled_now=SETTLED_OK)
    check("k1 sign-off in a worktree the plugin did NOT create still merges, and "
          "removes nothing - the merge is the phase's work landing, the worktree "
          "is somebody's directory, and only the second needs permission",
          code == M.E_OK and ans["merged"] is True
          and not any(c[:2] == ["worktree", "remove"] for c in calls),
          "exit=%d merged=%r cleanup=%r"
          % (code, ans["merged"], ans["cleanupDone"]))
    check("k2 ...and the run SAYS so rather than finishing quietly - a cleanup "
          "that silently did not happen is one nobody goes looking for",
          any("did not create" in b["remedy"]
              or "only removes worktrees it started" in b["remedy"]
              for b in ans["blocked"]),
          ans["blocked"][0]["why"][:70])
    run, calls = _fake({"merge --ff-only": (0, "", ""),
                        "merge-base --is-ancestor": (0, "", "")})
    p = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, ans = M.close("/repo", p, "feature/p2", "dev", run=run,
                        settled_now={"ok": False,
                                     "why": "phase P2 still has unfinished "
                                            "task(s): P2.3"})
    check("k3 a phase with a task still open merges and is not cleaned up - the "
          "commits being safe is not the same as the plugin being finished, and "
          "the refusal names the task",
          code == M.E_OK and ans["cleanupDone"] == []
          and any("P2.3" in b["why"] for b in ans["blocked"]),
          repr(ans["cleanupDone"]))

    # `settlement()` is where `mergedAt` is supplied by the run rather than read
    # from a field this command has not written yet.
    phase = {"id": "P2", "status": "done", "mergedAt": None,
             "tasks": [{"id": "P2.1", "status": "done"}]}
    check("k4 a phase whose merge THIS RUN just verified is settled even though "
          "mergedAt is still null - the orchestrator writes that field after this "
          "command returns, so reading the stale null would refuse every cleanup "
          "the command exists to perform. A deadlock, not a safeguard",
          M.settlement(phase, merged=True)["ok"] is True
          and M.settlement(phase, merged=False)["ok"] is False,
          "merged=%r unmerged=%r" % (M.settlement(phase, merged=True)["ok"],
                                     M.settlement(phase, merged=False)["ok"]))
    check("k5 ...and `merged=True` is NOT a shortcut past the other two marks: a "
          "phase that has not signed off stays unsettled however verified its "
          "merge is",
          M.settlement(dict(phase, status="in_progress"),
                       merged=True)["ok"] is False,
          M.settlement(dict(phase, status="in_progress"), merged=True)["why"][:60])

    # --- which copy of the plan survives --------------------------------------
    root = _harness.fixture_root("closephase")
    try:
        here = os.path.join(root, "wt-p2")
        there = os.path.join(root, "repo")
        for d in (here, there):
            os.makedirs(os.path.join(d, "docs", "audit"))
            with open(os.path.join(d, "docs", "audit", "plan.json"), "w") as fh:
                json.dump({"phases": [{"id": "P2", "mergedAt": None}]}, fh)
        obs = {"parentTree": {"path": there}}
        pl = {"merge": {"mode": "in-parent-worktree"}}
        mine = os.path.join(here, "docs", "audit", "plan.json")
        target, proj, _why = M.surviving_copy(mine, here, here, obs, pl)
        check("v1 a merge that landed in ANOTHER worktree stamps the plan THERE, "
              "not in the tree this process is standing in - measured live, the "
              "phase worktree is removed moments later, so a stamp written here "
              "records the moment a phase landed in a directory that ceases to "
              "exist while the surviving copy still reads null",
              target == os.path.join(there, "docs", "audit", "plan.json")
              and proj == there,
              repr(target))
        # The PROJECT and the GIT ROOT are different directories whenever
        # `meta.gitRoot` names a subdirectory, and this case is built that way on
        # purpose: with them equal, dropping the same-tree short-circuit computes
        # the identical path and the mutation is invisible. The journal is written
        # under the PROJECT, so an unconditional redirect files the row against the
        # git root instead - a real misplacement that only this shape can see.
        proj_dir = os.path.join(root, "proj")
        sub = os.path.join(proj_dir, "sub")
        os.makedirs(os.path.join(sub, "docs", "audit"))
        # INSIDE the git root, so the relative path resolves and the later
        # `..`-escape branch cannot answer for this one. With the manifest outside,
        # that branch returns the same tuple and the mutation is invisible again -
        # which is how the first version of this case passed against the break.
        inside = os.path.join(sub, "docs", "audit", "plan.json")
        with open(inside, "w") as fh:
            json.dump({"phases": [{"id": "P2", "mergedAt": None}]}, fh)
        target2, proj2, _w2 = M.surviving_copy(
            inside, proj_dir, sub, {"parentTree": {"path": sub}}, pl)
        mine = inside
        check("v2 ...and when the merge landed in the tree we are ALREADY in, the "
              "caller's own path AND its project directory are used unchanged - "
              "the allow case, which goes red if the redirect becomes "
              "unconditional and files the journal row against the git root "
              "instead of the project",
              target2 == mine and proj2 == proj_dir,
              "%r / %r" % (target2, proj2))
        target3, _p3, _w3 = M.surviving_copy(
            mine, here, here, obs, {"merge": {"mode": "no-checkout"}})
        check("v3 a no-checkout merge redirects nothing: no other worktree was "
              "written to, so there is no other copy to prefer",
              target3 == mine, repr(target3))
        target4, _p4, _w4 = M.surviving_copy(
            os.path.join(root, "outside.json"), here, here, obs, pl)
        check("v4 a manifest OUTSIDE the repository is left where the caller put "
              "it rather than having a path invented for it inside another tree",
              target4 == os.path.join(root, "outside.json"), repr(target4))
    finally:
        _harness.remove_tree(root)

    # --- the stamp, against a real file ---------------------------------------
    root = _harness.fixture_root("closephase")
    try:
        shard = os.path.join(root, "P2.json")
        with open(shard, "w") as fh:
            json.dump({"id": "P2", "mergedAt": None}, fh)
        path, stamp = M.stamp_merged(shard, "P2", when="2026-01-02T03:04:05Z")
        with open(shard) as fh:
            body = json.load(fh)
        check("s1 the stamp lands in the phase's own file and is the moment it was "
              "given, not a wall-clock read a case cannot pin",
              path == shard and body["mergedAt"] == "2026-01-02T03:04:05Z",
              repr(body.get("mergedAt")))
        missing = os.path.join(root, "nope.json")
        path2, why = M.stamp_merged(missing, "P2")
        check("s2 a file that cannot be read returns a REASON rather than raising "
              "- a merge that happened must not be reported as not having happened "
              "because the plan could not be updated",
              path2 == "" and why != "", repr(why))
        with open(shard, "w") as fh:
            json.dump({"id": "P9"}, fh)
        path3, why3 = M.stamp_merged(shard, "P2")
        check("s3 ...and a file holding a DIFFERENT phase is refused by name "
              "rather than stamped anyway",
              path3 == "" and "P2" in why3, repr(why3))
    finally:
        _harness.remove_tree(root)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_close_phase.py --selftest\n")
    raise SystemExit(2)
