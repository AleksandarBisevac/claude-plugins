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
import re
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (TESTS_DIR, for the race children)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _locks                                      # noqa: E402  (the wait a held-lock case shortens)
import _manifest_io as _mio                        # noqa: E402  (the layout the stamp writes)
import _proposals                                  # noqa: E402  (the rule sign-off reports)
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
        # Supplied, because `cleanup_plan` fails CLOSED without them: a case that
        # omitted these would refuse every cleanup and pass its assertions for a
        # reason that has nothing to do with what it claims to measure. `standingIn`
        # joined that list in 2.1.1 - it used to be None, which the plan read
        # as "nowhere" and now reads as "never asked".
        "standingIn": W.CWD_OUTSIDE,
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
    import _branch
    _ini_meta = {"developmentBranch": "dev",
                 "branch": {"template": "{type}/{initials}-{phase}-{slug}"}}
    _unrec = {"id": "BUG-3", "title": "Crash"}
    rc = M.resolve({"meta": _ini_meta}, _unrec, initials="Ann Bee")
    _want_c = _branch.phase_answer(_ini_meta, _unrec, "Ann Bee")["branch"]
    check("r3b a phase whose copy of the plan never recorded its branch is found by "
          "the name that CUT it - git user.name's initials and a bug phase's type "
          "included, through the one answer start and worktree add compose: %r vs %r"
          % (rc["branch"], _want_c),
          rc["branch"] == _want_c and "/ab-" in _want_c
          and _want_c.startswith("bugfix/"))
    check("r4 the policy travels with the names, so one read of meta decides both "
          "where this goes and what happens after",
          r["policy"]["auto"] is True, repr(r["policy"]["auto"]))
    _self = M.resolve({"meta": meta}, {"id": "P2", "branch": "dev"})
    _self_arg = M.resolve({"meta": meta}, {"id": "P2", "branch": "feature/p2"},
                          branch_arg="dev")
    check("r5 a branch that IS the resolved parent is refused, recorded or passed - "
          "landing it would plan deleting the parent: %r / %r"
          % (_self.get("refusal"), _self_arg.get("refusal")),
          bool(_self.get("refusal")) and "its own parent" in _self["refusal"]
          and bool(_self_arg.get("refusal")))
    check("r6 SECOND DIRECTION: a branch other than the parent carries no refusal",
          r.get("refusal") is None, repr(r.get("refusal")))

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
    # `auto` used to be read BEFORE the merge plan's own refusal, so a run
    # that could not merge for a real reason - a `parentBranch` this clone does not
    # have, a dirty parent worktree - came back exit 0 saying "the human will do
    # this deliberately". `orchestrator.md` maps that exact shape to "signed off and
    # deliberately unlanded", so a typo'd branch travelled up the chain as a plan.
    run, calls = _fake({})
    _bad = M.plan(_obs(W.NOT_CONTAINED, parent_exists=False),
                  "feature/p2", "develp", NO_AUTO)
    code, ans = M.close("/repo", _bad, "feature/p2", "develp", run=run,
                        settled_now=SETTLED_OK)
    check("a4 a merge the plan REFUSES is a failure even under auto:false - the "
          "switch says 'a human will merge this', and a parent that does not "
          "resolve is not something a human can merge either. Two different "
          "answers must not share exit 0",
          code == M.E_FAIL and ans["pending"] is False,
          "exit=%d pending=%r mode=%r" % (code, ans["pending"], ans["mode"]))
    check("a5 ...and the reason is REPORTED. The pending path used to return "
          "before the refusal block, so the one line a reader got named the "
          "switch and not the branch that does not exist",
          ans["refusal"] and "develp" in str(ans["refusal"].get("why")),
          repr(ans["refusal"]))
    check("a6 ...and it still ran no git command, because a refusal is decided "
          "before anything is attempted",
          calls == [], repr(calls))

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
    # `main()` stamped `mergedAt` on `answer["merged"]`, which is "THIS RUN
    # performed a merge" - and this path performs none, while its cleanup runs on
    # the VERIFIED containment. So the idempotent re-run the design advertises, and
    # the re-run `orchestrator.md` tells a human to make after merging by hand,
    # removed the worktree and deleted the branch and wrote no `mergedAt`. The
    # phase is then unsettled for ever and no later sweep can reap anything.
    check("b3 ...and it reports the containment it VERIFIED, which is the fact the "
          "stamp is written from. 'this run merged' and 'the parent contains it' "
          "are two different claims and only the second is what mergedAt records",
          ans["verified"]["answer"] == W.CONTAINED
          and ans["merged"] is False,
          "verified=%r merged=%r" % (ans["verified"]["answer"], ans["merged"]))
    # --- the preview previews the CLEANUP, not just the merge --------------------
    # The plan is built with `settled` read off disk, where `mergedAt` is null by
    # construction before sign-off — so the preview blocked both cleanup halves and
    # printed a merge and nothing else, while the same command without --dry-run
    # removed the worktree and deleted the branch. `commands/phase.md` promises the
    # opposite. There were no dry-run cases here at all, which is how it survived.
    run, calls = _fake({})
    _dp = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON)
    code, dry = M.close("/repo", _dp, "feature/p2", "dev", run=run, dry_run=True,
                        settled_now=SETTLED_OK)
    check("y1 --dry-run exits 0 and writes nothing at all - COUNTED, because a "
          "preview that ran a command is not a preview",
          code == M.E_OK and calls == [], "exit=%d calls=%r" % (code, calls))
    check("y2 ...and it shows the CLEANUP it will perform, not the merge alone. "
          "The preview is computed against what the merge is about to make true, "
          "which is the only version of it that describes the same run",
          # The merge argv carries `-C <tree>` in front, so the verb is read by
          # membership rather than by position - a positional read would pass or
          # fail on which worktree held the parent, which is not what is asked here.
          [next(a for a in c if not a.startswith("-") and a != "/repo")
           for c in dry["plannedSteps"]] == ["merge", "worktree", "branch"],
          repr(dry["plannedSteps"]))
    check("y3 ...and it SAYS the preview is conditional on the merge landing, "
          "because a cleanup shown as fact about a repository that has not merged "
          "yet is a different claim from the one being made",
          "the merge lands" in str(dry.get("previewAssumes")),
          repr(dry.get("previewAssumes")))

    # --- --no-ff is honoured or refused, never dropped ---------------------------
    # `git fetch . <b>:<p>` cannot make a merge commit, so on the no-checkout path
    # the flag used to be silently ignored: the run fast-forwarded, reported
    # success, and produced a different history than the one asked for. It matters
    # twice over because `orchestrator.md` makes --no-ff the documented remedy for
    # exit 3, and in this topology that remedy could never have worked.
    _nf_trees = [{"path": "/repo", "branch": "main", "isMain": True},
                 {"path": "/wt-p2", "branch": "feature/p2"}]
    _nf = M.plan(_obs(W.NOT_CONTAINED, trees=_nf_trees), "feature/p2", "dev",
                 ALL_ON, no_ff=True)
    check("n1 --no-ff with the parent checked out NOWHERE is refused, not "
          "silently fast-forwarded - a merge commit and a fast-forward are two "
          "histories, and the caller asked for the one a fetch cannot make",
          _nf["merge"]["mode"] == "refuse" and not _nf["merge"]["argv"],
          "mode=%r argv=%r" % (_nf["merge"]["mode"], _nf["merge"]["argv"]))
    check("n2 ...and the refusal names the parent and offers both ways out, "
          "because the operator can either check it out or accept the "
          "fast-forward and both are legitimate",
          "--no-ff" in str(_nf["merge"]["refusal"].get("why"))
          and "dev" in str(_nf["merge"]["refusal"].get("remedy")),
          repr(_nf["merge"]["refusal"]))
    _nf_ok = M.plan(_obs(W.NOT_CONTAINED), "feature/p2", "dev", ALL_ON,
                    no_ff=True)
    check("n3 ...while with the parent checked out somewhere it is HONOURED - "
          "the allow case, without which n1 is a rule that refuses every --no-ff "
          "and proves nothing about the topology",
          "--no-ff" in _nf_ok["merge"]["argv"]
          and "--ff-only" not in _nf_ok["merge"]["argv"],
          repr(_nf_ok["merge"]["argv"]))
    # --- the remedy was reachable and then blocked one step later ---------------
    # The parent is checked out nowhere BECAUSE every worktree holds an audit
    # branch, so a reader does what n2's remedy says and adds one - and a worktree
    # git has just added holds no installed dependencies, so the commit hook that
    # bootstraps from one cannot find its own bootstrap file and aborts the merge
    # commit. `--no-verify` was what finished it. The refusal is where a reader
    # meets this, so the whole path belongs there: START AND FINISH, and the
    # finish needs the BRANCH as well as the parent, because it merges
    # `feature/p2` into `dev` and a remedy naming only one of the two cannot be
    # typed. That is the half the old wording was missing, which is why the
    # fixture's two names differ.
    _rem = str(_nf["merge"]["refusal"].get("remedy"))
    check("n4 ...and the remedy names the path that WORKS rather than only its "
          "first step: the worktree to add, the hooks that will stop the merge "
          "commit inside it, and the --no-ff --no-verify finish naming the "
          "branch. Advice that is reachable and then blocked by something it "
          "does not mention is advice a reader abandons",
          "git worktree add" in _rem and "hook" in _rem
          and "--no-ff --no-verify" in _rem and "feature/p2" in _rem,
          repr(_rem))
    check("n5 ...and the second direction, which looks vacuous and is the only "
          "case that fails if the advice becomes unconditional: a --no-ff this "
          "command HONOURS says nothing about --no-verify anywhere in its plan. "
          "A hook skip has to stay a thing somebody chose once",
          "--no-verify" not in repr(_nf_ok),
          repr(_nf_ok["merge"]))

    check("b4 ...and `stampable` is the field main() gates the write on, set from "
          "the verified containment rather than from whether this run merged. The "
          "cleanup half already read the verified answer; the recording half read "
          "the other one, so the two disagreed about the same phase",
          ans["stampable"] is True,
          "stampable=%r merged=%r" % (ans.get("stampable"), ans["merged"]))

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
    # `--no-ff` IS ONE OF THE DIMENSIONS NOW, but it used to be absent from
    # every combination here, so the merge these assertions
    # swept was always the `--ff-only` one and the branch that composes the
    # `--no-ff` argv was outside all three of them. Measured: putting
    # `--no-verify` into that branch turned n5 red and left h3 green, which is a
    # sweep that cannot see the argv it is a sweep about.
    every = []
    for policy in (ALL_ON, NO_AUTO):
        for state in (W.CONTAINED, W.NOT_CONTAINED, W.UNKNOWN):
            for trees in (TREES, NOWT):
                for no_ff in (False, True):
                    run, calls = _fake({"merge --ff-only": (0, "", ""),
                                        "merge --no-ff": (0, "", ""),
                                        "fetch .": (0, "", ""),
                                        "merge-base --is-ancestor": (0, "", "")})
                    pl = M.plan(_obs(state, trees=trees), "feature/p2", "dev",
                                policy, no_ff=no_ff)
                    M.close("/repo", pl, "feature/p2", "dev", run=run)
                    every.extend(calls)
    # EVERY ASSERTION BELOW IS A NEGATIVE OVER `every`, so all three are
    # true of an empty corpus - a `close()` that stopped issuing calls, a `plan`
    # that started refusing every combination, or a rename inside `_fake` would
    # make them the calmest lines in the file while sweeping nothing. Each one
    # therefore requires the corpus rather than inheriting it from the case above:
    # a case whose precondition is another case's assertion goes vacuous the day
    # that case is reordered or deleted, and this one has already been the case
    # that could not see the argv it was a sweep about.
    check("h0 THE CORPUS THE THREE NEGATIVES BELOW SWEEP: `close()` really "
          "issued calls over every combination, and both merge spellings are "
          "among them. `--no-ff` composes its own argv, and no combination here "
          "used to take that branch - so a sweep that cannot say "
          "which merges it saw is a sweep that proves nothing about the one it "
          "missed",
          every and any("--ff-only" in c for c in every)
          and any("--no-ff" in c for c in every),
          "%d call(s) recorded; ff-only=%r no-ff=%r"
          % (len(every), any("--ff-only" in c for c in every),
             any("--no-ff" in c for c in every)))
    check("h1 NO run, in any policy x containment x worktree x --no-ff "
          "combination, ever issues "
          "`git switch` - it is unavailable from inside the worktree a "
          "phase ran in, and moving an operator's HEAD is a side effect no script "
          "takes on its own. COUNTED over every combination rather than checked on "
          "the happy path",
          every and not any("switch" in c for c in every),
          "%d call(s) recorded, none a switch" % (len(every),))
    check("h2 ...and no run ever forces: no `+` refspec, no `branch -D`, no "
          "`--force` anywhere",
          every and not any(a.startswith("+") or a in ("-D", "--force")
                            for c in every for a in c),
          "%d call(s) recorded, no forcing argument in any of them"
          % (len(every),))
    # This guard protects the FIX rather than the bug. The tempting
    # repair once a linked worktree's missing hook bootstrap has aborted a merge
    # commit is to put `--no-verify` in this command's own argv, which would skip
    # hooks on every merge it ever makes and skip them silently. The flag is
    # named in one refusal's remedy and belongs in the operator's shell, on one
    # commit they typed - so it must appear in no call this command issues.
    check("h3 ...and no run ever skips a hook: `--no-verify` is advice in one "
          "refusal and appears in no argv, over the same combinations. "
          "Putting it here instead would trade one blocked merge for a hook "
          "that stops running and says nothing",
          every and not any("--no-verify" in a for c in every for a in c),
          "%d call(s) recorded, none skipping a hook" % (len(every),))

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
    signed = {"id": "P2", "status": "in_progress", "branch": "audit/p2",
              "review": {"status": "passed"}, "mergedAt": None,
              "tasks": [{"id": "P2.1", "status": "done"}]}
    check("k4s a phase signed off by the signoff verb (stored status untouched) is "
          "settled once THIS run verified its merge - close-phase cleans up after "
          "the sign-off it no longer finds as a hand-written `done`",
          M.settlement(signed, merged=True)["ok"] is True,
          M.settlement(signed, merged=True)["why"])
    check("k4u ...and without a recorded verdict it is not, merged or not",
          M.settlement(dict(signed, review={"status": "pending"}), merged=True)["ok"]
          is False)
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
        path, stamp = M.stamp_merged(shard, "P2", when="2026-01-02T03:04:05Z")[:2]
        with open(shard) as fh:
            body = json.load(fh)
        check("s1 the stamp lands in the phase's own file and is the moment it was "
              "given, not a wall-clock read a case cannot pin",
              path == shard and body["mergedAt"] == "2026-01-02T03:04:05Z",
              repr(body.get("mergedAt")))
        missing = os.path.join(root, "nope.json")
        path2, why = M.stamp_merged(missing, "P2")[:2]
        check("s2 a file that cannot be read returns a REASON rather than raising "
              "- a merge that happened must not be reported as not having happened "
              "because the plan could not be updated",
              path2 == "" and why != "", repr(why))
        with open(shard, "w") as fh:
            json.dump({"id": "P9"}, fh)
        path3, why3 = M.stamp_merged(shard, "P2")[:2]
        check("s3 ...and a file holding a DIFFERENT phase is refused by name "
              "rather than stamped anyway",
              path3 == "" and "P2" in why3, repr(why3))
        with open(shard, "w") as fh:
            json.dump({"id": "P2", "mergedAt": "2026-01-02T03:04:05Z"}, fh)
        path4, stamp4 = M.stamp_merged(shard, "P2", when="2026-09-09T09:09:09Z")[:2]
        with open(shard) as fh:
            body4 = json.load(fh)
        check("s4 a phase that already records its merge KEEPS that moment - an "
              "idempotent re-run records a merge, it does not move one: %r"
              % (body4.get("mergedAt"),),
              path4 == shard and stamp4 == "2026-01-02T03:04:05Z"
              and body4["mergedAt"] == "2026-01-02T03:04:05Z")

        # THE MERGE IS AN INPUT OF THE DERIVED STATUS. A branch phase signed off
        # with every task terminal reads done once `mergedAt` lands, so the stamp
        # stores that status beside it - on the shard, and mirrored on the index
        # stub, which is what a reader of the index alone is answered from.
        signed = {"id": "P2", "title": "Two", "status": "in_progress",
                  "branch": "feature/p2", "mergedAt": None,
                  "review": {"status": "passed"},
                  "tasks": [{"id": "P2.1", "title": "t", "status": "done"}]}
        mpath = os.path.join(root, "audit-plan.json")
        _mio.save_sharded(mpath, {"meta": {"version": 2}, "phases": [signed],
                                  "bugs": [], "fileIndex": {}})
        stub_of = lambda: [s for s in _mio.read_json(mpath)["phases"]  # noqa: E731
                           if s.get("id") == "P2"][0]
        spath = os.path.join(root, stub_of()["shard"])
        path5, _st5 = M.stamp_merged(mpath, "P2", when="2026-01-02T03:04:05Z")[:2]
        body5 = _mio.read_json(spath)
        check("s5 the stamp stores the status the merge now derives - done, for a "
              "signed-off phase with every task terminal - in the same write as "
              "mergedAt: %r" % (body5.get("status"),),
              path5 == spath and body5.get("status") == "done"
              and body5.get("mergedAt") == "2026-01-02T03:04:05Z")
        mirrored, why = M.mirror_stub(mpath, "P2", root)[:2]
        check("s6 ...and the index stub is re-mirrored from that shard, so the index "
              "alone reads done too: stub=%r (%s)" % (stub_of().get("status"), why),
              mirrored == mpath and stub_of().get("status") == "done")
        with open(mpath, "rb") as fh:
            before = fh.read()
        again, why2 = M.mirror_stub(mpath, "P2", root)[:2]
        with open(mpath, "rb") as fh:
            after = fh.read()
        check("s7 ...and a stub that already agrees is not rewritten - the index "
              "is written on a phase's own transitions, not on every run: %r"
              % (why2,), again == "" and before == after)
        unsigned = dict(signed, review={"status": "pending"})
        _mio.save_sharded(mpath, {"meta": {"version": 2}, "phases": [unsigned],
                                  "bugs": [], "fileIndex": {}})
        M.stamp_merged(mpath, "P2", when="2026-01-02T03:04:05Z")
        body8 = _mio.read_json(os.path.join(root, stub_of()["shard"]))
        check("s8 SECOND DIRECTION: a merge of a phase whose sign-off is NOT "
              "recorded stamps mergedAt and stores no done - the derivation does not "
              "answer done there, and the case goes red when the stamp writes done "
              "unconditionally: %r" % (body8.get("status"),),
              body8.get("mergedAt") == "2026-01-02T03:04:05Z"
              and body8.get("status") == "in_progress")

        # THE MIRROR FAILS AS A SENTENCE, NEVER AS A RAISE. It runs after the merge
        # has landed, so a lock held elsewhere, or a lock that cannot even be asked
        # for, must leave the index as it was and say which command catches it up.
        _mio.save_sharded(mpath, {"meta": {"version": 2}, "phases": [signed],
                                  "bugs": [], "fileIndex": {}})
        M.stamp_merged(mpath, "P2", when="2026-01-02T03:04:05Z")
        with open(mpath, "rb") as fh:
            held_before = fh.read()
        claim = mpath + ".lock"                  # another run's claim on the index
        with open(claim, "w") as fh:
            fh.write("held elsewhere")
        try:
            got9, why9 = M.mirror_stub(mpath, "P2", root)[:2]
        finally:
            os.remove(claim)
        with open(mpath, "rb") as fh:
            held_after = fh.read()
        check("s9 with the index lock held elsewhere the mirror writes nothing and "
              "answers with a sentence naming settle: %r" % (why9,),
              got9 == "" and "settle" in why9 and "not taken" in why9
              and held_before == held_after and stub_of().get("status") != "done")
        real_read = M._panel_write.read_config

        def _boom(_project):
            raise RuntimeError("config unreadable")
        M._panel_write.read_config = _boom
        try:
            try:
                got10, why10 = M.mirror_stub(mpath, "P2", root)[:2]
                raised10 = None
            except Exception as exc:
                got10, why10, raised10 = "", "", exc
        finally:
            M._panel_write.read_config = real_read
        check("s10 ...and a lock that cannot even be ASKED for is a sentence too, not "
              "an exception out of a merge that already landed: %r / %r"
              % (why10, raised10),
              raised10 is None and got10 == "" and "config unreadable" in why10
              and "settle" in why10)
        # REVALIDATED, and only the write's own findings refuse it: a write making
        # the plan invalid has its prior bytes restored, while a plan that was
        # already carrying a finding is not this write's to refuse (s1 stamps a
        # file that is no plan at all, and lands).
        broken = _mio.read_json(mpath)
        broken["fileIndex"] = {"src/x.py": ["P9.9"]}   # names no task
        with open(mpath, "rb") as fh:
            rv_before = fh.read()
        new11 = M._revalidated_write(mpath, mpath, broken)
        with open(mpath, "rb") as fh:
            rv_after = fh.read()
        check("s11 a write that introduces a finding is rolled back byte for byte and "
              "the finding is returned: %r" % (new11,),
              new11 != [] and rv_before == rv_after)
        fine = _mio.read_json(mpath)
        fine["meta"]["title"] = "Renamed"
        new12 = M._revalidated_write(mpath, mpath, fine)
        check("s12 SECOND DIRECTION: a write that validates stands - the case that "
              "goes red when every write is rolled back: %r" % (new12,),
              new12 == [] and _mio.read_json(mpath)["meta"]["title"] == "Renamed")
    finally:
        _harness.remove_tree(root)


def _parked_cases(check):
    """What sign-off says about the work a phase branch parked for later."""
    manifest = {"meta": {}, "phases": [], "proposals": [
        {"id": "PROP-1-k7m", "status": "proposed", "branch": "feature/p2",
         "name": "Idea", "payload": {"phase": {"id": "P5", "title": "Idea"}}},
        {"id": "PROP-2", "status": "proposed", "branch": "feature/other",
         "payload": {"phase": {"id": "P6", "title": "Elsewhere"}}},
        {"id": "PROP-3-k7m", "status": "materialized", "branch": "feature/p2",
         "payload": {"phase": {"id": "P7", "title": "Done already"}}}]}
    rows = _proposals.parked_on_branch(manifest, "feature/p2")
    check("pp1 the proposals parked on the merged branch are the still-proposed ones "
          "whose branch it is - not another branch's, not one already materialized",
          [r["id"] for r in rows] == ["PROP-1-k7m"] and rows[0]["reserves"] == "P5", rows)
    lines = []
    M.render({"branch": "feature/p2", "parent": "dev", "mode": "fast-forward",
              "steps": [], "stamped": "x.json", "stampedAt": "t",
              "parkedOnBranch": rows}, out=lines.append)
    text = "\n".join(lines)
    check("pp2 once the branch has landed, sign-off names each parked proposal and the "
          "materialize command to run on the parent branch - the step is printed, "
          "not left to memory: %s" % (text,),
          "PROP-1-k7m" in text and "on dev" in text
          and "/audit:propose materialize PROP-1-k7m" in text)
    lines = []
    M.render({"branch": "feature/p2", "parent": "dev", "mode": "fast-forward",
              "steps": [], "stamped": "x.json", "stampedAt": "t",
              "parkedOnBranch": []}, out=lines.append)
    check("pp3 SECOND DIRECTION: with nothing parked there, sign-off says nothing about "
          "proposals", not any("materialize" in ln for ln in lines), lines)


def _landed_cases(check):
    """The "landed and its branch is gone" answer trusts a RECORDED branch only.

    Against a real repository: a composed name is a prediction, and with another
    identity at the keyboard it names a branch that never existed - while the one
    that did may still hold work."""
    import _branch
    root = _harness.fixture_root("closephase-landed")
    try:
        git = _fixture_git(root)
        _init_fixture_repo(git)
        git("config", "user.name", "Zed Quill")
        meta = {"developmentBranch": "main",
                "branch": {"template": "{type}/{initials}-{phase}-{slug}"}}
        phase = {"id": "P9", "title": "Nine", "status": "done",
                 "review": {"status": "passed"}, "mergedAt": "2026-01-01T00:00:00Z",
                 "tasks": [{"id": "P9.1", "title": "t", "status": "done"}]}
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        os.makedirs(os.path.dirname(mpath))
        with open(mpath, "w") as fh:
            json.dump({"meta": meta, "phases": [phase]}, fh)
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        real = _branch.phase_answer(meta, phase, "Ann Bee")["branch"]
        git("branch", real)
        lines = []
        code = M.main([mpath, "P9", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("lg1 a phase recording a merge but NO branch is not declared landed and "
              "gone on a COMPOSED name - another identity composes a name that never "
              "existed while the real branch (%s) is still there; it says the name was "
              "composed and asks for --branch: exit %r, %r" % (real, code, text[:200]),
              code == M.E_NO_BASIS and "nothing left to do" not in text
              and "composed" in text and "--branch" in text)
        lines = []
        code = M.main([mpath, "P9", "--project", root, "--branch", "gone/branch"],
                      out=lines.append)
        check("lg2 SECOND DIRECTION: with the branch NAMED (an argument, as a recorded "
              "phase.branch would be) and absent, it is landed and gone, exit 0: %r"
              % ("\n".join(lines)[:160],),
              code == M.E_OK and "landed at" in "\n".join(lines)
              and "is gone" in "\n".join(lines))
    finally:
        _harness.remove_tree(root)


def _fixture_git(root):
    """`git -C root ...` with a fixed identity, returning the CompletedProcess."""
    import subprocess
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*a):
        return subprocess.run(["git", "-C", root] + list(a), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return git


def _init_fixture_repo(git):
    """`git init` on `main`, then a REPO-LOCAL identity.

    The environment `_fixture_git` sets reaches only the fixture's own git calls;
    close-phase runs its merge with the process's environment, and a `--no-ff`
    merge needs a committer. Where git cannot guess one from the host (a CI
    runner, a container) that merge fails, so the identity lives in the repo's
    config, where every git process run inside it finds it."""
    git("init", "-q", "-b", "main")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")


def _signed_phase(pid, branch):
    return {"id": pid, "title": "One", "status": "in_progress",
            "branch": branch, "baseRef": None, "mergedAt": None,
            "parentBranch": "main" if branch else None,
            "review": {"status": "passed"},
            "tasks": [{"id": pid + ".1", "title": "t", "status": "done"}]}


def _write_plan(root, meta, phases):
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    if not os.path.isdir(os.path.dirname(mpath)):
        os.makedirs(os.path.dirname(mpath))
    with open(mpath, "w") as fh:
        json.dump({"meta": meta, "phases": phases}, fh)
    return mpath


def _main_tree_cases(check):
    """Signed off from the MAIN worktree while it stands on the phase branch.

    Against a real repository, because the defect was in the order two real
    refusals were asked in: the merge lands, and the cleanup then has to hand the
    operator the switch it will not make itself."""
    root = _harness.fixture_root("closephase-maintree")
    try:
        git = _fixture_git(root)
        _init_fixture_repo(git)
        meta = {"developmentBranch": "main"}
        mpath = _write_plan(root, meta, [_signed_phase("P1", "audit/p1-demo")])
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "audit/p1-demo")
        with open(os.path.join(root, "work.txt"), "w") as fh:
            fh.write("work\n")
        git("add", "-A")
        git("commit", "-q", "-m", "work")
        lines = []
        M.main([mpath, "P1", "--project", root, "--delete-branch", "--dry-run"],
               out=lines.append)
        preview = "\n".join(lines)
        check("mt0 --dry-run words the follow-up as what the cleanup WILL need after "
              "the merge, not as a cleanup that has run and stopped: %r"
              % (preview[-300:],),
              "after the merge, cleanup will need, from" in preview
              and "cleanup is not finished" not in preview
              and "git switch main" in preview)
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--delete-branch"],
                      out=lines.append)
        text = "\n".join(lines)
        head = git("branch", "--show-current").stdout.decode().strip()
        landed = git("merge-base", "--is-ancestor", "audit/p1-demo",
                     "main").returncode == 0
        check("mt1 close-phase from the main worktree ON the phase branch lands it, "
              "moves no HEAD, and prints the two commands that finish the cleanup "
              "- `git switch main`, then `git branch -d audit/p1-demo` - each on a "
              "line of its own: exit %r, head %r, %r" % (code, head, text[-400:]),
              landed and head == "audit/p1-demo"
              and "\n    git switch main\n    git branch -d audit/p1-demo" in text)
        check("mt2 ...and never tells the operator to remove the main tree, nor "
              "that a worktree must go first: %r" % (text[-400:],),
              "git worktree remove" not in text and "must go first" not in text)
    finally:
        _harness.remove_tree(root)


# The trail's action name for a close made over its verdict's refusal, spelled
# out: it is what a reader greps the journal for, so the suite pins the literal.
_OVERRIDE_ACTION = "audit.verdict.close-overridden"


def _red_fixture(name, statuses, gate=("test",), member=False):
    """`(root, mpath, git)` - a signed-off P1 on `audit/p1-demo`, standing in the
    main tree, whose ledger holds one phase row per `statuses` entry, oldest
    first and an hour apart, as `cr-0`, `cr-1`... The rows ride the branch's
    last commit, so the tree is clean and only the verdict differs.

    `member` adds P2 on the same branch, signed off in a group with P1 as the
    carrier: P2's `testEvidence` points at P1's run with `gradedBy`, and the
    ledger holds no row of P2's own - group sign-off's shape."""
    root = _harness.fixture_root(name)
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phase = _signed_phase("P1", "audit/p1-demo")
    phase["testGate"] = list(gate)
    phases = [phase]
    if member:
        other = _signed_phase("P2", "audit/p1-demo")
        other["testGate"] = list(gate)
        other["testEvidence"] = {"runId": "cr-0", "status": "passed",
                                 "gradedBy": "P1"}
        phases.append(other)
    mpath = _write_plan(root, {"developmentBranch": "main"}, phases)
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "audit/p1-demo")
    with open(os.path.join(root, "work.txt"), "w") as fh:
        fh.write("work\n")
    _write_rows(root, statuses, gate)
    git("add", "-A")
    git("commit", "-q", "-m", "work")
    return root, mpath, git


def _write_rows(root, statuses, gate=("test",), name="2026-09.cr.jsonl",
                first=0):
    """P1's ledger rows, `cr-<first>` onward, an hour apart from `first`."""
    import _evidence_io as E
    ev = E.evidence_dir(root)
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, name), "a") as fh:
        for i, status in enumerate(statuses, first):
            fh.write(json.dumps({
                "runId": "cr-%d" % i, "ts": "2026-09-01T0%d:00:00Z" % i,
                "scope": "phase", "phaseId": "P1", "status": status,
                "gateSource": "phase", "steps": [{"name": n} for n in gate],
                "testedState": {}}) + "\n")


def _landing_fixture(name, rows, files=(), reason=None, verdict_hour=None,
                     change_after=False):
    """`(root, mpath, git)` - P1 on `audit/p1-demo` declaring `files`, with
    everything committed on the branch: the work, P1's ledger rows - `rows` is
    `[(hour, status)]`, each `passed` row carrying the declared files' digest as
    the branch first held them - and, with `verdict_hour`, the sign-off's
    `phase.verdict` journal row. `reason` records the sign-off with
    `--no-evidence-reason`; `change_after` rewrites the declared files in a
    later commit, so a green measured before it no longer binds."""
    import _evidence_io as E
    import _journal_io as J
    import _tree_stamp as T
    root = _harness.fixture_root(name)
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phase = _signed_phase("P1", "audit/p1-demo")
    phase["testGate"] = ["test"]
    phase["tasks"][0]["files"] = list(files)
    if reason:
        phase["review"]["noEvidenceReason"] = reason
    mpath = _write_plan(root, {"developmentBranch": "main"}, [phase])
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "audit/p1-demo")
    for rel in ("work.txt",) + tuple(files):
        with open(os.path.join(root, rel), "w") as fh:
            fh.write("work\n")
    digest = T.scope_digest(root, list(files))[0] if files else None
    ev = E.evidence_dir(root)
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, "2026-09.cr.jsonl"), "w") as fh:
        for hour, status in rows:
            fh.write(json.dumps({
                "runId": "cr-%d" % hour, "ts": "2026-09-01T0%d:00:00Z" % hour,
                "scope": "phase", "phaseId": "P1", "status": status,
                "gateSource": "phase", "steps": [{"name": "test"}],
                "testedState": {"scopeDigest": digest}}) + "\n")
    if verdict_hour is not None:
        jd = J.journal_dir(root)
        os.makedirs(jd, exist_ok=True)
        with open(os.path.join(jd, "2026-09.cr.jsonl"), "w") as fh:
            fh.write(json.dumps({
                "action": "phase.verdict", "target": "P1",
                "ts": "2026-09-01T0%d:00:00Z" % verdict_hour,
                "summary": "P1 signed off (passed)",
                "details": {"phaseId": "P1"}}) + "\n")
    git("add", "-A")
    git("commit", "-q", "-m", "work")
    if change_after:
        for rel in files:
            with open(os.path.join(root, rel), "w") as fh:
                fh.write("changed after the gate measured it\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more work")
    return root, mpath, git


def _landing_cases(check):
    """THE HEAD IT WOULD MERGE, not the tree `--project` names; and a sign-off
    that chose to stand on no run, honoured for the green it set aside and not
    for a red recorded after it."""
    def run_case(name, build, act):
        root = None
        try:
            root, mpath, git = build()
            act(root, mpath, git)
        finally:
            if root:
                _harness.remove_tree(root)

    def from_parent(rows, files, label, expect_refused):
        def build():
            return _landing_fixture(label, rows, files=files)

        def act(root, mpath, git):
            # The main tree goes back to the parent: --project is now a tree
            # holding none of the branch's rows and none of its files.
            git("checkout", "-q", "main")
            # --keep-branch: with no worktree holding the branch the default
            # deletes it once landed, and the ancestry asked below needs it.
            code, text = _close(mpath, root, "--keep-branch")
            if expect_refused:
                check("cr11 RED-FIRST: run from the PARENT's tree, a phase whose "
                      "branch carries a red after its green refuses, naming the "
                      "red read at the branch tip, and lands nothing: exit %r, "
                      "landed %r, %r" % (code, _landed(git), text[:300]),
                      code == 1 and not _landed(git) and "cr-1" in text)
            else:
                check("cr12 ALLOW: run from the parent's tree, a green newest "
                      "verdict at the branch tip lands, BOUND - the digest taken "
                      "over the tip's declared files, not the parent's: exit %r, "
                      "landed %r, %r" % (code, _landed(git), text[:400]),
                      code == 0 and _landed(git)
                      and "gate: bound to run cr-1" in text)
        run_case(label, build, act)

    from_parent([(0, "passed"), (1, "failed")], (), "closephase-tip-red", True)
    from_parent([(0, "failed"), (1, "passed")], ("src.txt",),
                "closephase-tip-green", False)

    def uncommitted(root, mpath, git):
        _write_rows(root, ["failed"], first=1)
        code, text = _close(mpath, root)
        check("cr13 RED-FIRST: a red recorded in the tree holding the branch and "
              "NOT committed still counts - the union of the tip and that tree: "
              "exit %r, landed %r, %r" % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-1" in text)
    run_case("closephase-uncommitted-red",
             lambda: _landing_fixture("closephase-uncommitted-red",
                                      [(0, "passed")]), uncommitted)

    def honoured(root, mpath, git):
        code, text = _close(mpath, root)
        check("cr14 RED-FIRST: a sign-off recorded with --no-evidence-reason over "
              "an older green whose files changed since lands - the stale green "
              "is not the verdict it stood on - and says so: exit %r, landed %r, "
              "%r" % (code, _landed(git), text[:400]),
              code == 0 and _landed(git) and "--no-evidence-reason" in text
              and "have changed since it was measured" in text)
    run_case("closephase-noevidence-stale",
             lambda: _landing_fixture("closephase-noevidence-stale",
                                      [(0, "passed")], files=("src.txt",),
                                      reason="graded by hand", verdict_hour=5,
                                      change_after=True), honoured)

    def red_after(root, mpath, git):
        code, text = _close(mpath, root)
        check("cr15 SECOND DIRECTION: a red recorded AFTER that sign-off still "
              "refuses - newer evidence it never saw: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-6" in text)
    run_case("closephase-noevidence-red-after",
             lambda: _landing_fixture("closephase-noevidence-red-after",
                                      [(0, "passed"), (6, "failed")],
                                      files=("src.txt",), reason="graded by hand",
                                      verdict_hour=5), red_after)

    def red_before(root, mpath, git):
        code, text = _close(mpath, root)
        check("cr16 ...and a red the sign-off came AFTER, it chose to stand over: "
              "it lands: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 0 and _landed(git))
    run_case("closephase-noevidence-red-before",
             lambda: _landing_fixture("closephase-noevidence-red-before",
                                      [(0, "passed"), (1, "failed")],
                                      files=("src.txt",), reason="graded by hand",
                                      verdict_hour=5), red_before)

    def no_moment(root, mpath, git):
        code, text = _close(mpath, root)
        check("cr17 a no-evidence sign-off whose journal row cannot be found "
              "refuses on any red - with no moment, the side that cannot land "
              "over an unanswered red: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-1" in text)
    run_case("closephase-noevidence-no-moment",
             lambda: _landing_fixture("closephase-noevidence-no-moment",
                                      [(0, "passed"), (1, "failed")],
                                      files=("src.txt",), reason="graded by hand"),
             no_moment)

    import _evidence_io as EV
    import _tree_stamp as TS

    def _row(root, run_id, hour, status, phase_id="P1", files=()):
        """One ledger row appended in the tree holding the branch, uncommitted,
        carrying the declared files' digest as they stand on disk."""
        with open(os.path.join(EV.evidence_dir(root), "2026-09.cr.jsonl"),
                  "a") as fh:
            fh.write(json.dumps({
                "runId": run_id, "ts": "2026-09-01T0%d:00:00Z" % hour,
                "scope": "phase", "phaseId": phase_id, "status": status,
                "gateSource": "phase", "steps": [{"name": "test"}],
                "testedState": {"scopeDigest": TS.scope_digest(
                    root, list(files))[0] if files else None}}) + "\n")

    def green_over_dirty(root, mpath, git):
        with open(os.path.join(root, "src.txt"), "w") as fh:
            fh.write("uncommitted - never at the tip\n")
        _row(root, "cr-1", 1, "passed", files=("src.txt",))
        code, text = _close(mpath, root)
        check("cr19 RED-FIRST: a green recorded over an UNCOMMITTED declared "
              "change refuses - the tip that would land is not what it measured: "
              "exit %r, landed %r, %r" % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-1" in text
              and "have changed since it was measured" in text)
    run_case("closephase-green-over-dirty",
             lambda: _landing_fixture("closephase-green-over-dirty",
                                      [(0, "passed")], files=("src.txt",)),
             green_over_dirty)

    def dirty_after_green(root, mpath, git):
        with open(os.path.join(root, "src.txt"), "w") as fh:
            fh.write("an edit after the green, not committed\n")
        code, text = _close(mpath, root)
        check("cr20 SECOND DIRECTION: a green at the tip with a dirty declared "
              "edit after it lands - the dirt does not land, so it does not "
              "decide: exit %r, landed %r, %r" % (code, _landed(git), text[:300]),
              code == 0 and _landed(git) and "gate: bound to run cr-0" in text)
    run_case("closephase-dirty-after-green",
             lambda: _landing_fixture("closephase-dirty-after-green",
                                      [(0, "passed")], files=("src.txt",)),
             dirty_after_green)

    def member_own_red(root, mpath, git):
        _row(root, "cr-m", 3, "failed", phase_id="P2")
        lines = []
        code = M.main([mpath, "P2", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cr7b RED-FIRST: a red recorded on a group MEMBER alone, after the "
              "carrier's green that grades the group, refuses that member's "
              "landing and merges nothing: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-m" in text)
    run_case("closephase-member-own-red",
             lambda: _red_fixture("closephase-member-own-red", ["passed"],
                                  member=True), member_own_red)

    def member_old_red(root, mpath, git):
        _row(root, "cr-m", 0, "failed", phase_id="P2")
        _write_rows(root, ["passed"], first=1)
        lines = []
        code = M.main([mpath, "P2", "--project", root], out=lines.append)
        check("cr7c SECOND DIRECTION: a member's red OLDER than the carrier's "
              "green that grades the group does not refuse: exit %r, landed %r"
              % (code, _landed(git)), code == 0 and _landed(git))
    run_case("closephase-member-old-red",
             lambda: _red_fixture("closephase-member-old-red", [],
                                  member=True), member_old_red)

    # LAST: it calls helpers that exist only with the fix, so on code without
    # it this is where the run stops, after every case above has been graded.
    import _verdict_binding as VB
    nowhere = _harness.fixture_root("closephase-nowhere")
    try:
        texts, _notes = M.branch_texts(nowhere, nowhere, "audit/p1-demo", None,
                                       os.path.join(nowhere, "docs", "audit",
                                                    "evidence"))
        bound = VB.binding(nowhere, {"phaseId": "P1"}, ["test"], "phase", [],
                           os.path.join(nowhere, "docs", "audit",
                                        "audit-plan.json"),
                           "run the gate", "no gate", texts=texts)
        check("cr18 RED-FIRST: a branch tip git cannot read and no worktree "
              "holding the branch is UNREADABLE, never no run - it refuses a "
              "close: texts %r, arm %r" % (texts, bound.get("arm")),
              texts and all(t is None for _l, t in texts)
              and bound.get("arm") == VB.ARM_UNREADABLE
              and VB.close_refusal(bound) == bound.get("sentence"))
        # The worktree holding the branch exists, but its evidence directory
        # does not: it lists nothing, which is no reading at all.
        texts, _notes = M.branch_texts(nowhere, nowhere, "audit/p1-demo",
                                       {"path": nowhere},
                                       os.path.join(nowhere, "docs", "audit",
                                                    "evidence"))
        check("cr21 RED-FIRST: a tip git cannot read and a holding worktree "
              "whose evidence directory lists nothing is UNREADABLE too, never "
              "no run: %r" % (texts,),
              texts and all(t is None for _l, t in texts))
    finally:
        _harness.remove_tree(nowhere)
    _scratch_cases(check)


def _tip_temps():
    import tempfile
    return set(n for n in os.listdir(tempfile.gettempdir())
               if n.startswith("close-phase-tip-"))


def _scratch_cases(check):
    """`tip_scope`'s scratch repository: it never outlives a failure, and the
    operator's git config never decides what it holds."""
    root = None
    try:
        root, mpath, git = _landing_fixture("closephase-tip-scratch",
                                            [(0, "passed")], files=("src.txt",))
        before = _tip_temps()

        def refuse_to_write(*_a, **_k):
            raise IOError("a write the disk refused")
        M.open = refuse_to_write
        try:
            raised, got = None, None
            try:
                got = M.tip_scope(root, root, "audit/p1-demo", ["src.txt"])
            except Exception as exc:
                raised = exc
        finally:
            del M.open
        check("cr22 RED-FIRST: a write that raises inside tip_scope answers None, "
              "raises nothing and leaves no scratch directory behind: got %r, "
              "raised %r, left %r" % (got, raised, sorted(_tip_temps() - before)),
              got is None and raised is None and not (_tip_temps() - before))

        # A declared DIRECTORY whose file matches the operator's global
        # excludes: without isolation the scratch `add` skips it, and the digest
        # reads the directory as holding nothing.
        os.makedirs(os.path.join(root, "lib"))
        with open(os.path.join(root, "lib", "x.txt"), "w") as fh:
            fh.write("tracked, and matched by a global exclude\n")
        git("add", "-A")
        git("commit", "-q", "-m", "lib")
        home = os.path.join(root, ".fake-global")
        os.makedirs(home)
        with open(os.path.join(home, "ignore"), "w") as fh:
            fh.write("*.txt\n")
        with open(os.path.join(home, "config"), "w") as fh:
            fh.write("[core]\n\texcludesFile = %s\n"
                     % (os.path.join(home, "ignore").replace(os.sep, "/"),))
        saved = os.environ.get("GIT_CONFIG_GLOBAL")
        os.environ["GIT_CONFIG_GLOBAL"] = os.path.join(home, "config")
        try:
            scratch = M.tip_scope(root, root, "audit/p1-demo", ["lib"])
        finally:
            if saved is None:
                os.environ.pop("GIT_CONFIG_GLOBAL", None)
            else:
                os.environ["GIT_CONFIG_GLOBAL"] = saved
        try:
            listed = (_fixture_git(scratch)("ls-files").stdout.decode()
                      if scratch else "")
        finally:
            if scratch:
                _harness.remove_tree(scratch)
        check("cr23 RED-FIRST: a tracked file matching the operator's global "
              "excludes is still in the scratch repository the digest reads: "
              "%r" % (listed,), "lib/x.txt" in listed)
    finally:
        if root:
            _harness.remove_tree(root)


def _checked_out_fixture(name, attributes, declared, change_after=False):
    """`(root, mpath, git, working)` - P1 on `audit/p1-demo` declaring `declared`,
    whose green was recorded over `src.txt` AS CHECKED OUT: the file is removed
    and checked out again under the branch's `.gitattributes` (`attributes`, or
    none) before the digest is taken, so the bytes the recorder hashed are the
    checkout's, not the blob's. `working` is those bytes. `change_after` commits
    a different `src.txt` after the green, so it no longer binds."""
    import _evidence_io as E
    import _tree_stamp as T
    root = _harness.fixture_root(name)
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phase = _signed_phase("P1", "audit/p1-demo")
    phase["testGate"] = ["test"]
    phase["tasks"][0]["files"] = list(declared)
    mpath = _write_plan(root, {"developmentBranch": "main"}, [phase])
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "audit/p1-demo")
    if attributes:
        with open(os.path.join(root, ".gitattributes"), "w") as fh:
            fh.write(attributes)
    src = os.path.join(root, "src.txt")
    with open(src, "wb") as fh:
        fh.write(b"line one\nline two\n")
    git("add", "-A")
    git("commit", "-q", "-m", "work")
    os.remove(src)
    git("checkout", "--", "src.txt")
    with open(src, "rb") as fh:
        working = fh.read()
    digest = T.scope_digest(root, list(declared))[0]
    ev = E.evidence_dir(root)
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, "2026-09.cr.jsonl"), "w") as fh:
        fh.write(json.dumps({
            "runId": "cr-0", "ts": "2026-09-01T00:00:00Z", "scope": "phase",
            "phaseId": "P1", "status": "passed", "gateSource": "phase",
            "steps": [{"name": "test"}],
            "testedState": {"scopeDigest": digest}}) + "\n")
    git("add", "-A")
    git("commit", "-q", "-m", "gate")
    if change_after:
        with open(src, "wb") as fh:
            fh.write(b"line one\nchanged after the gate measured it\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more work")
    return root, mpath, git, working


def _checked_out_cases(check):
    """THE TIP IS DIGESTED AS A CHECKOUT WRITES IT, and a declared entry as the
    recorder's digest reads it. Each allow case has a twin whose declared file
    changed after the green, so a reading that made every digest agree - both
    sides missing, say - goes red there instead of passing here."""
    def run(name, attributes, declared, change_after):
        root = None
        try:
            root, mpath, git, working = _checked_out_fixture(
                name, attributes, declared, change_after)
            git("checkout", "-q", "main")
            code, text = _close(mpath, root, "--keep-branch")
            return code, text, _landed(git), working
        finally:
            if root:
                _harness.remove_tree(root)

    crlf = "* text eol=crlf\n"
    code, text, landed, working = run("closephase-crlf", crlf, ["src.txt"], False)
    check("cr24 RED-FIRST: a branch whose .gitattributes says eol=crlf over LF "
          "blobs, with its green recorded over the checked-out (CRLF) file, "
          "lands BOUND - the tip is digested as a checkout writes it, not as "
          "the blob holds it: working %r, exit %r, landed %r, %r"
          % (working, code, landed, text[:400]),
          working == b"line one\r\nline two\r\n" and code == 0 and landed
          and "gate: bound to run cr-0" in text)
    code, text, landed, _w = run("closephase-crlf-moved", crlf, ["src.txt"], True)
    check("cr25 SECOND DIRECTION: the same eol=crlf branch whose declared file "
          "changed after the green still refuses as moved: exit %r, landed %r, "
          "%r" % (code, landed, text[:300]),
          code == 1 and not landed
          and "have changed since it was measured" in text)

    code, text, landed, _w = run("closephase-suffix", None, ["src.txt:1-2"],
                                 False)
    check("cr26 RED-FIRST: a phase declaring 'src.txt:1-2' whose file did not "
          "change lands BOUND - the line-range suffix is stripped before the "
          "tip is listed, as the recorder's digest strips it: exit %r, landed "
          "%r, %r" % (code, landed, text[:400]),
          code == 0 and landed and "gate: bound to run cr-0" in text)
    code, text, landed, _w = run("closephase-suffix-moved", None,
                                 ["src.txt:1-2"], True)
    check("cr27 SECOND DIRECTION: the same suffixed declaration whose file "
          "changed after the green refuses as moved - the suffix is not read "
          "as a file missing on both sides: exit %r, landed %r, %r"
          % (code, landed, text[:300]),
          code == 1 and not landed
          and "have changed since it was measured" in text)


def _symlink_refusal():
    """Why `os.symlink` cannot make a link here, or None when it can."""
    import tempfile
    probe = tempfile.mkdtemp(prefix="closephase-symlink-probe-")
    try:
        os.symlink("target", os.path.join(probe, "link"))
        return None
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "%s: %s" % (type(exc).__name__, exc)
    finally:
        _harness.remove_tree(probe)


def _symlink_fixture(name, change_after):
    """`(root, mpath, git)` - P1 declaring `link`, a committed symbolic link to
    `t.txt`, with its green recorded over the working tree: the recorder's
    digest follows the link and hashes `t.txt`'s bytes. `change_after` commits
    a different `t.txt` after the green."""
    import _evidence_io as E
    import _tree_stamp as T
    root = _harness.fixture_root(name)
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phase = _signed_phase("P1", "audit/p1-demo")
    phase["testGate"] = ["test"]
    phase["tasks"][0]["files"] = ["link"]
    mpath = _write_plan(root, {"developmentBranch": "main"}, [phase])
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "audit/p1-demo")
    with open(os.path.join(root, "t.txt"), "wb") as fh:
        fh.write(b"the bytes the link leads to\n")
    os.symlink("t.txt", os.path.join(root, "link"))
    git("add", "-A")
    git("commit", "-q", "-m", "work")
    digest = T.scope_digest(root, ["link"])[0]
    ev = E.evidence_dir(root)
    os.makedirs(ev, exist_ok=True)
    with open(os.path.join(ev, "2026-09.cr.jsonl"), "w") as fh:
        fh.write(json.dumps({
            "runId": "cr-0", "ts": "2026-09-01T00:00:00Z", "scope": "phase",
            "phaseId": "P1", "status": "passed", "gateSource": "phase",
            "steps": [{"name": "test"}],
            "testedState": {"scopeDigest": digest}}) + "\n")
    git("add", "-A")
    git("commit", "-q", "-m", "gate")
    if change_after:
        with open(os.path.join(root, "t.txt"), "wb") as fh:
            fh.write(b"changed after the gate measured it\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more work")
    return root, mpath, git


def _symlink_cases(check):
    """A DECLARED LINK IS DIGESTED THROUGH IT, as the recorder's file hash
    follows it: the tip must hand the digest the target's bytes, not the
    link's target text."""
    refused = _symlink_refusal()
    if refused is not None:
        for label in ("cr28", "cr29"):
            _harness.skip(check, label, "os.symlink is refused here (%s)"
                          % (refused,), True)
        return

    def run(name, change_after):
        root = None
        try:
            root, mpath, git = _symlink_fixture(name, change_after)
            git("checkout", "-q", "main")
            code, text = _close(mpath, root, "--keep-branch")
            return code, text, _landed(git)
        finally:
            if root:
                _harness.remove_tree(root)

    code, text, landed = run("closephase-symlink", False)
    check("cr28 RED-FIRST: a declared symbolic link to a file that did not "
          "change lands BOUND - the tip hands the digest the bytes following "
          "the link reads: exit %r, landed %r, %r" % (code, landed, text[:400]),
          code == 0 and landed and "gate: bound to run cr-0" in text)
    code, text, landed = run("closephase-symlink-moved", True)
    check("cr29 SECOND DIRECTION: the same link whose TARGET changed after the "
          "green refuses as moved: exit %r, landed %r, %r"
          % (code, landed, text[:300]),
          code == 1 and not landed
          and "have changed since it was measured" in text)


def _override_rows(project):
    """The rows a close over its verdict left, whole - their details are the
    claim."""
    import _journal_io
    return [r for r in _journal_io.read_all(project)
            if r.get("action") == _OVERRIDE_ACTION]


def _close(mpath, root, *extra):
    """`(exit, text)` of one close-phase run."""
    lines = []
    code = M.main([mpath, "P1", "--project", root] + list(extra),
                  out=lines.append)
    return code, "\n".join(lines)


def _landed(git):
    return git("merge-base", "--is-ancestor", "audit/p1-demo",
               "main").returncode == 0


def _override_cases(check):
    """THE PROBE SEQUENCE: a green the sign-off was bound to, a red recorded after
    it, then the close. The newer red is newer evidence about the work being
    landed, and the merge used to go ahead over it."""
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-over-red",
                                        ["passed", "failed"])
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cr1 RED-FIRST: a red phase-gate run recorded after the green the "
              "sign-off was bound to makes close-phase refuse, name the row, and "
              "land nothing: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-1" in text
              and "`failed`" in text and "--override-verdict" in text
              and not _merged_at(mpath))
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--override-verdict",
                       "the red was a runner outage"], out=lines.append)
        rows = _override_rows(root)
        check("cr2 RED-FIRST: an explicit --override-verdict lands it and journals "
              "the exception - ONE row naming the phase, the red run and the "
              "reason: exit %r, landed %r, rows %r"
              % (code, _landed(git), rows),
              code == 0 and _landed(git) and len(rows) == 1
              and (rows[0].get("details") or {}).get("runId") == "cr-1"
              and (rows[0].get("details") or {}).get("phaseId") == "P1"
              and (rows[0].get("details") or {}).get("reason")
              == "the red was a runner outage")
        # ALREADY LANDED: the branch is kept and the parent holds it, a later
        # red is recorded, and the re-runs that stamp or clean up must finish.
        _write_rows(root, ["failed"], first=2)
        code, text = _close(mpath, root, "--override-verdict", "again")
        check("cr5 a re-run over a landed branch with the override writes NO "
              "second row - one row per actual merge: exit %r, rows %d, %r"
              % (code, len(_override_rows(root)), text[:300]),
              code == 0 and len(_override_rows(root)) == 1)
        code, text = _close(mpath, root)
        check("cr6 RED-FIRST: a re-run over a landed branch with a red recorded "
              "after is not refused - the landing happened, and the cleanup it "
              "prints could otherwise never finish; the verdict is said: exit "
              "%r, %r" % (code, text[:300]),
              code == 0 and "REFUSED" not in text and "already landed" in text
              and "cr-2" in text and len(_override_rows(root)) == 1)
    finally:
        if root:
            _harness.remove_tree(root)
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-group-member",
                                        ["passed", "failed"], member=True)
        lines = []
        code = M.main([mpath, "P2", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cr7 RED-FIRST: a group member whose carrier holds a red after its "
              "green refuses, naming the carrier's run, and lands nothing - its "
              "own ledger holds no row, and reading that as no verdict merged "
              "the whole branch: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "cr-1" in text)
    finally:
        if root:
            _harness.remove_tree(root)
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-dry-override",
                                        ["passed", "failed"])
        code, text = _close(mpath, root, "--dry-run", "--override-verdict", "x")
        check("cr8 --dry-run with the override merges nothing and writes no "
              "row, saying so: exit %r, landed %r, rows %d, %r"
              % (code, _landed(git), len(_override_rows(root)), text[:300]),
              code == 0 and not _landed(git) and not _override_rows(root)
              and "a dry run writes nothing" in text)
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json",
                       "journal": {"enabled": False}}, fh)
        code, text = _close(mpath, root, "--override-verdict", "x")
        check("cr9 RED-FIRST: journal.enabled false with the override exits 1 "
              "and lands nothing - an override recorded nowhere is a gate "
              "quietly removed: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 1 and not _landed(git) and "journal.enabled" in text
              and not _merged_at(mpath))
    finally:
        if root:
            _harness.remove_tree(root)
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-journal-unwritable",
                                        ["passed", "failed"])
        import _journal_io
        jdir = _journal_io.journal_dir(root)
        if os.path.isdir(jdir):
            _harness.remove_tree(jdir)
        with open(jdir, "w") as fh:
            fh.write("a file where the journal directory goes\n")
        code, text = _close(mpath, root, "--override-verdict", "x")
        check("cr10 RED-FIRST: a journal the row cannot be written to, with the "
              "override, exits 1, lands nothing and stamps nothing: exit %r, "
              "landed %r, mergedAt %r, %r"
              % (code, _landed(git), _merged_at(mpath), text[:300]),
              code == 1 and not _landed(git) and not _merged_at(mpath)
              and "could NOT be written" in text)
    finally:
        if root:
            _harness.remove_tree(root)
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-green-newest",
                                        ["failed", "passed"])
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cr3 ALLOW: a green newest verdict closes with no flag, says the "
              "run it is bound to, and journals no exception: exit %r, landed "
              "%r, %r" % (code, _landed(git), text[:300]),
              code == 0 and _landed(git) and "gate: bound to run cr-1" in text
              and not _override_rows(root))
    finally:
        if root:
            _harness.remove_tree(root)
    root = None
    try:
        root, mpath, git = _red_fixture("closephase-no-gate", [], gate=())
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cr4 ALLOW: a phase no gate measures closes, in the no-gate arm's "
              "own sentence: exit %r, landed %r, %r"
              % (code, _landed(git), text[:300]),
              code == 0 and _landed(git)
              and "gate: phase P1 declares no gate" in text)
    finally:
        if root:
            _harness.remove_tree(root)


def _composed_cases(check):
    """A phase with no recorded branch: the name close-phase asks git about was
    composed, and a composed name that is not a branch is a question for the
    operator, not an unanswerable ancestry."""
    import _branch
    root = _harness.fixture_root("closephase-composed")
    try:
        git = _fixture_git(root)
        _init_fixture_repo(git)
        git("config", "user.name", "Zed Quill")
        meta = {"developmentBranch": "main"}
        phase = _signed_phase("P1", None)
        mpath = _write_plan(root, meta, [phase])
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        composed = _branch.phase_answer(meta, phase, "Zed Quill")["branch"]
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("cn1 a phase recording NO branch, whose composed name %r is not a "
              "branch here, is refused with the reason - the name was composed "
              "because none is recorded - and asked for --branch, instead of an "
              "ancestry that 'could not be established': exit %r, %r"
              % (composed, code, text[:300]),
              code == M.E_FAIL and "no branch is recorded" in text
              and composed in text and "--branch" in text
              and "could not be established" not in text)
        git("checkout", "-q", "-b", composed)
        with open(os.path.join(root, "work.txt"), "w") as fh:
            fh.write("work\n")
        git("add", "-A")
        git("commit", "-q", "-m", "work")
        git("checkout", "-q", "main")
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--keep-branch",
                       "--keep-worktree"], out=lines.append)
        text = "\n".join(lines)
        check("cn2 SECOND DIRECTION: when the composed name IS a branch, the phase "
              "lands on it as before - the refusal is for a name nothing holds, not "
              "for every composed one: exit %r, %r" % (code, text[:300]),
              code == M.E_OK and "no branch is recorded" not in text
              and git("merge-base", "--is-ancestor", composed,
                      "main").returncode == 0)
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--branch", "main"],
                      out=lines.append)
        text = "\n".join(lines)
        check("cn3 --branch naming the parent itself is refused with exit 1 and "
              "leaves the parent branch where it was: exit %r, %r"
              % (code, text[:300]),
              code == M.E_FAIL and "its own parent" in text
              and git("rev-parse", "--verify", "--quiet",
                      "refs/heads/main").returncode == 0)
    finally:
        _harness.remove_tree(root)


def _worktree_fixture(root, meta_extra=None, nested=False):
    """(main manifest, worktree dir, worktree manifest, git) - main on `main`, the
    phase on `audit/p1-demo` in a linked worktree the plugin created (its marker
    written), signed off, one commit ahead. `nested` puts the worktree under
    `<root>/.claude/worktrees/p1`, the layout Claude Code makes."""
    git = _fixture_git(root)
    _init_fixture_repo(git)
    meta = dict({"developmentBranch": "main"}, **(meta_extra or {}))
    mpath = _write_plan(root, meta, [_signed_phase("P1", "audit/p1-demo")])
    if nested:
        with open(os.path.join(root, ".gitignore"), "w") as fh:
            fh.write(".claude/worktrees/\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    wt = (os.path.join(root, ".claude", "worktrees", "p1") if nested
          else root + "-wt")
    git("worktree", "add", "-q", "-b", "audit/p1-demo", wt)
    wgit = _fixture_git(wt)
    with open(os.path.join(wt, "work.txt"), "w") as fh:
        fh.write("work\n")
    wgit("add", "-A")
    wgit("commit", "-q", "-m", "work")
    admin = wgit("rev-parse", "--git-dir").stdout.decode().strip()
    admin = admin if os.path.isabs(admin) else os.path.join(wt, admin)
    with open(os.path.join(admin, W.PROVENANCE_FILE), "w") as fh:
        json.dump({"createdBy": W.PROVENANCE_MARK, "phaseId": "P1",
                   "branch": "audit/p1-demo"}, fh)
    return mpath, wt, os.path.join(wt, "docs", "audit", "audit-plan.json"), git


def _merged_at(path):
    with open(path) as fh:
        return [p.get("mergedAt") for p in json.load(fh)["phases"]
                if p.get("id") == "P1"][0]


def _from_dirs(text):
    """Every directory a `From <dir>, run:` line in close-phase's output names."""
    return re.findall(r"\bFrom (.+?), run:", text)


def _same_dir(printed, want):
    """True when `printed` and `want` name one directory, however each is spelled.

    The printed directory is GIT'S spelling - on windows `C:/Users/...`, forward
    slashes, long names - while a fixture path is Python's, backslashes and
    possibly the 8.3 short form a runner's temp directory carries. Comparing the
    text asked whether the two programs spell alike, which is not the question;
    `realpath` resolves both to the one real spelling and `normcase` folds the
    case a windows path does not distinguish.
    """
    return (os.path.normcase(os.path.realpath(printed))
            == os.path.normcase(os.path.realpath(want)))


def _same_dir_cases(check):
    """The comparison sv3 relies on, pinned without a fixture.

    POSIX has neither 8.3 names nor a second separator, so the windows spelling
    that made a text comparison fail cannot be produced here. What can be is the
    same CLASS: one directory written two ways. Reverting `_same_dir` to a string
    comparison turns sv3b red on any platform.
    """
    base = os.path.abspath("closephase-same-dir")
    text = "  cleanup is not finished. From %s, run:" % (base + os.sep + ".",)
    froms = _from_dirs(text)
    check("sv3b a `From <dir>, run:` line naming the fixture in another spelling "
          "is read as that directory, while a sibling directory is not: %r"
          % (froms,),
          froms == [base + os.sep + "."] and _same_dir(froms[0], base)
          and not _same_dir(froms[0], base + "-other"))


def _surviving_copy_cases(check):
    """The landing stamp goes to the manifest of the tree the merge lands in, never
    to the copy inside the phase's own worktree - whichever path was passed."""
    for label, use_wt in (("worktree", True), ("main", False)):
        root = _harness.fixture_root("closephase-survivor-%s" % (label,))
        wt = None
        try:
            mpath, wt, wt_mpath, git = _worktree_fixture(root)
            lines = []
            code = M.main([wt_mpath if use_wt else mpath, "P1", "--project", root],
                          out=lines.append)
            text = "\n".join(lines)
            removed = not os.path.isdir(wt)
            if label == "worktree":
                check("sv1 given the WORKTREE's manifest from the main checkout, the "
                      "stamp lands in main's copy and nothing is written under the "
                      "worktree, so its removal succeeds: exit %r, main mergedAt %r, "
                      "worktree removed %r, %s"
                      % (code, _merged_at(mpath), removed, text[-400:]),
                      code == M.E_OK and bool(_merged_at(mpath)) and removed)
            else:
                check("sv2 SECOND DIRECTION: given main's own manifest the landing is "
                      "unchanged - main's copy stamped, the worktree removed: exit %r, "
                      "main mergedAt %r, worktree removed %r"
                      % (code, _merged_at(mpath), removed),
                      code == M.E_OK and bool(_merged_at(mpath)) and removed)
        finally:
            _harness.remove_tree(root)
            if wt and os.path.isdir(wt):
                _harness.remove_tree(wt)
    root = _harness.fixture_root("closephase-survivor-followup")
    wt = None
    here = os.getcwd()
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        lines = []
        os.chdir(wt)
        try:
            M.main([wt_mpath, "P1", "--project", wt, "--dry-run"], out=lines.append)
        finally:
            os.chdir(here)
        text = "\n".join(lines)
        follow = [ln.strip() for ln in lines if "close-phase.py" in ln]
        froms = _from_dirs(text)
        check("sv3 a dry-run standing inside the worktree prints a follow-up naming the "
              "SURVIVING manifest - main's - never the worktree's copy, from the main "
              "checkout: %r from %r" % (follow, froms),
              len(follow) == 1 and "docs/audit/audit-plan.json" in follow[0]
              and os.path.realpath(wt) not in follow[0] and wt not in follow[0]
              and len(froms) == 1 and _same_dir(froms[0], root))
        check("sv4 ...and the preview wrote nothing anywhere: %r"
              % (_merged_at(mpath),), _merged_at(mpath) is None
              and _merged_at(wt_mpath) is None)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


def _no_survivor_cases(check):
    """The parent checked out in NO worktree, and the manifest inside the phase's own
    worktree: the landing has no surviving copy to stamp, so close-phase stops
    before the ref-only fast-forward - the ref and the stamp cannot disagree."""
    root = _harness.fixture_root("closephase-no-survivor")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        git("checkout", "-q", "-b", "other")
        before = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        after = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        check("ns1 with `main` checked out nowhere and the manifest inside the phase's "
              "worktree, close-phase refuses BEFORE merging - exit 2, `main` unmoved, "
              "no stamp in the worktree copy, the worktree kept - naming the branch "
              "and the step that fixes it: exit %r, main moved %r, %s"
              % (code, before != after, text[:400]),
              code == M.E_USAGE and before == after
              and _merged_at(wt_mpath) is None and os.path.isdir(wt)
              and "no surviving copy" in text
              and "check out main in a worktree" in text)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


def _landed_survivor_cases(check):
    """The ALREADY-LANDED mode stamps the surviving copy too - a branch a human
    merged by hand, or a re-run - and the remaining arms of the no-survivor rule."""
    here = os.getcwd()

    def fresh(name, **kw):
        root = _harness.fixture_root("closephase-%s" % (name,))
        mpath, wt, wt_mpath, git = _worktree_fixture(root, **kw)
        return root, mpath, wt, wt_mpath, git

    def done(root, wt):
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)
    root, mpath, wt, wt_mpath, git = fresh("landed-main")
    try:
        git("merge", "-q", "--ff-only", "audit/p1-demo")
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        check("sv5 a branch merged BY HAND, closed from main with the worktree's "
              "manifest: main's copy is stamped, the worktree copy is not, and the "
              "worktree is removed: exit %r, main %r, removed %r, %s"
              % (code, _merged_at(mpath), not os.path.isdir(wt),
                 "\n".join(lines)[-300:]),
              code == M.E_OK and bool(_merged_at(mpath))
              and not os.path.isdir(wt))
    finally:
        done(root, wt)
    root, mpath, wt, wt_mpath, git = fresh("landed-inside")
    try:
        git("merge", "-q", "--ff-only", "audit/p1-demo")
        lines = []
        os.chdir(wt)
        try:
            M.main([wt_mpath, "P1", "--project", wt], out=lines.append)
        finally:
            os.chdir(here)
        follow = [ln.strip() for ln in lines if "close-phase.py" in ln]
        check("sv6 ...and closed from INSIDE the worktree, the stamp is in main's copy "
              "and not the worktree's, and the follow-up names main's manifest: main "
              "%r, worktree %r, follow-up %r"
              % (_merged_at(mpath), _merged_at(wt_mpath), follow),
              bool(_merged_at(mpath)) and _merged_at(wt_mpath) is None
              and len(follow) == 1 and wt not in follow[0]
              and os.path.realpath(wt) not in follow[0])
    finally:
        done(root, wt)
    root, mpath, wt, wt_mpath, git = fresh("pending",
                                           meta_extra={"merge": {"auto": False}})
    try:
        git("checkout", "-q", "-b", "other")
        before = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        after = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        check("ns2 with merge.auto false the run writes nothing, so it is not refused "
              "for having no survivor: exit 0, NOT MERGED and the command to run, the "
              "ref unmoved: exit %r, %s" % (code, text[:300]),
              code == M.E_OK and "NOT MERGED" in text and before == after
              and "no surviving copy" not in text)
    finally:
        done(root, wt)
    root, mpath, wt, wt_mpath, git = fresh("pr-landed",
                                           meta_extra={"merge": {"auto": False}})
    try:
        # A pull request landed the branch: main holds it and is checked out
        # nowhere, and the only manifest in reach is the worktree's.
        git("checkout", "-q", "-b", "other")
        git("branch", "-f", "main", "audit/p1-demo")
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        check("ns4 with merge.auto false and the branch ALREADY in main by a pull "
              "request, main checked out nowhere, the worktree's manifest is the "
              "copy removal would delete - refused, and neither copy stamped: "
              "exit %r, main %r, worktree %r, %s"
              % (code, _merged_at(mpath), _merged_at(wt_mpath), text[:300]),
              code == M.E_USAGE and "no surviving copy" in text
              and _merged_at(mpath) is None and _merged_at(wt_mpath) is None)
    finally:
        done(root, wt)
    root, mpath, wt, wt_mpath, git = fresh("nocheckout-main")
    try:
        git("checkout", "-q", "-b", "other")
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--keep-branch",
                       "--keep-worktree"], out=lines.append)
        text = "\n".join(lines)
        landed = git("merge-base", "--is-ancestor", "audit/p1-demo",
                     "main").returncode == 0
        check("ns3 SECOND DIRECTION: the ordinary no-checkout landing, given main's "
              "own manifest, lands and is not refused: exit %r, landed %r, %s"
              % (code, landed, text[:300]),
              code == M.E_OK and landed and "no surviving copy" not in text)
    finally:
        done(root, wt)
    root, mpath, wt, wt_mpath, git = fresh("nested", nested=True)
    try:
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        check("sv7 a worktree NESTED in the main tree (.claude/worktrees/p1), closed "
              "from main with its manifest: the deepest holder is the worktree, so "
              "main's copy is stamped and the worktree removed: exit %r, main %r, "
              "removed %r, %s" % (code, _merged_at(mpath), not os.path.isdir(wt),
                                  "\n".join(lines)[-300:]),
              code == M.E_OK and bool(_merged_at(mpath)) and not os.path.isdir(wt))
    finally:
        done(root, wt)


def _merged_head(path):
    with open(path) as fh:
        return [p.get("mergedHead") for p in json.load(fh)["phases"]
                if p.get("id") == "P1"][0]


def _merged_head_cases(check):
    """`phase.mergedHead` is the PARENT's commit right after the merge, stamped in
    the same write as `mergedAt` - never a second write, the branch tip only for a
    fast-forward, and a recorded `mergedHead` is never replaced. A merge recorded WITHOUT one is
    `_backfill_cases`' subject."""
    # --- THE REPRO: a fast-forward landing carries mergedAt and no mergedHead ----
    root = _harness.fixture_root("closephase-mergedhead-ff")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        head = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        merged_head = _merged_head(mpath)
        check("mh1 a phase closed into its parent carries mergedAt and its derived "
              "status but ALSO mergedHead, equal to the parent's HEAD right after "
              "the merge - a full 40-hex SHA, never a guess: exit %r, mergedAt %r, "
              "mergedHead %r, parent head %r"
              % (code, _merged_at(mpath), merged_head, head),
              code == M.E_OK and bool(_merged_at(mpath))
              and merged_head == head and len(merged_head or "") == 40
              and "mergedHeadAt" not in open(mpath).read())
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- THE PARENT'S HEAD, NOT THE BRANCH TIP: a --no-ff merge makes them differ -
    root = _harness.fixture_root("closephase-mergedhead-noff")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        tip = git("rev-parse", "refs/heads/audit/p1-demo").stdout.decode().strip()
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root, "--no-ff",
                       "--keep-branch"], out=lines.append)
        head = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        merged_head = _merged_head(mpath)
        check("mh2 --no-ff: mergedHead is the parent's post-merge commit, not the "
              "branch's own tip - a merge commit has a parent the branch tip is not: "
              "exit %r, tip %r, parent head %r, mergedHead %r"
              % (code, tip, head, merged_head),
              code == M.E_OK and merged_head == head and merged_head != tip
              and len(merged_head or "") == 40)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- A RECORDED MERGE IS KEPT: a re-run does not move mergedHead -------------
    # `--keep-branch` so the branch survives the first run: with it gone, `main()`'s
    # own "landed and gone" short-circuit answers before `close-phase` ever reaches
    # `_stamp`, which would make this case pass for a reason that has nothing to do
    # with the one it is pinning - the RE-RUN going through `close()` and its
    # `recorded_merge` guard, on an already-contained branch that still resolves.
    root = _harness.fixture_root("closephase-mergedhead-rerun")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root, meta_extra={
            "merge": {"deleteBranch": False}})
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        first_head = _merged_head(mpath)
        with open(os.path.join(root, "extra.txt"), "w") as fh:
            fh.write("more\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more")
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        text = "\n".join(lines)
        second_head = _merged_head(mpath)
        check("mh3 a phase whose merge is already recorded is not re-stamped with a "
              "different head, even though the parent has since moved on: exit %r, "
              "first %r, second %r, mode %r"
              % (code, first_head, second_head,
                 [ln for ln in lines if ln.startswith("[close-phase]")][:1]),
              code == M.E_OK and second_head == first_head and bool(first_head)
              and "is gone" not in text)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


# The journal action a backfilled head is recorded under. Spelled here rather than
# read off the module: it is what a reader of the trail filters on, so a rename is
# a change to the trail's vocabulary and should turn this suite red.
BACKFILL_ACTION = "phase.mergedHead.recorded"


def _drop_merged_head(path):
    """Rewrite the plan at `path` as a merge recorded before `mergedHead` existed:
    `mergedAt` kept, the head key absent."""
    with open(path) as fh:
        body = json.load(fh)
    for ph in body["phases"]:
        if ph.get("id") == "P1":
            ph.pop("mergedHead", None)
    with open(path, "w") as fh:
        json.dump(body, fh, indent=2)


def _journal_actions(project, action):
    """How many journal rows under `project` carry `action` - counted, so a second
    row for one backfill is as visible as a missing one."""
    import _journal_io
    return len([r for r in _journal_io.read_all(project)
                if r.get("action") == action])


def _commit_on_main(root, git, name):
    """Move the parent past the merge, so its current head is a different commit
    than the one the first stamp recorded - the value that tells an overwrite from
    a keep."""
    with open(os.path.join(root, name), "w") as fh:
        fh.write("more\n")
    git("add", "-A")
    git("commit", "-q", "-m", name)
    return git("rev-parse", "refs/heads/main").stdout.decode().strip()


def _set_task_commit(path, sha):
    """Record `sha` as P1.1's commit in the plan at `path` - the evidence a
    branch-gone backfill asks git about."""
    with open(path) as fh:
        body = json.load(fh)
    for ph in body["phases"]:
        if ph.get("id") == "P1":
            for t in ph.get("tasks") or []:
                if t.get("id") == "P1.1":
                    t["commit"] = sha
    with open(path, "w") as fh:
        json.dump(body, fh, indent=2)


def _merged_head_at(path):
    with open(path) as fh:
        phase = [p for p in json.load(fh)["phases"] if p.get("id") == "P1"][0]
    return phase.get("mergedHeadAt", "<absent>")


def _backfill_rows(project):
    import _journal_io
    return [r for r in _journal_io.read_all(project)
            if r.get("action") == BACKFILL_ACTION]


def _recovery_cases(check):
    """`merge_commit` recovers the commit a merge produced from the parent's
    first-parent history - both spellings, against real git: the tip itself for a
    fast-forward, the oldest first-parent descendant of the tip for a true merge
    commit, and either one unchanged once the parent has moved on."""
    root = _harness.fixture_root("closephase-recovery")
    try:
        git = _fixture_git(root)

        def commit(name):
            with open(os.path.join(root, name), "w") as fh:
                fh.write(name + "\n")
            git("add", "-A")
            git("commit", "-q", "-m", name)
            return git("rev-parse", "HEAD").stdout.decode().strip()

        def head(ref):
            return git("rev-parse", "refs/heads/" + ref).stdout.decode().strip()
        _init_fixture_repo(git)
        commit("base")
        git("checkout", "-q", "-b", "ff")
        tip = commit("f1")
        git("checkout", "-q", "main")
        git("merge", "-q", "--ff-only", "ff")
        got = M.merge_commit(root, "ff", "main")
        check("rc1 a FAST-FORWARD the parent has not moved past: the merge commit is "
              "the tip, which is also the parent's head: %r (tip %r)" % (got, tip),
              got["sha"] == tip == head("main"))
        moved = commit("m1")
        got = M.merge_commit(root, "ff", "main")
        check("rc2 ...and after the parent MOVED ON it is still the tip, never the "
              "parent's current head: %r (tip %r, parent now %r)"
              % (got, tip, moved),
              got["sha"] == tip and got["sha"] != moved)
        git("checkout", "-q", "-b", "true")
        branch_tip = commit("t1")
        git("checkout", "-q", "main")
        commit("m2")
        git("merge", "-q", "--no-ff", "-m", "merge true", "true")
        merge = head("main")
        got = M.merge_commit(root, "true", "main")
        check("rc3 a TRUE MERGE COMMIT over a parent that had diverged: the merge "
              "commit, not the branch tip: %r (merge %r, tip %r)"
              % (got, merge, branch_tip),
              got["sha"] == merge and merge != branch_tip)
        moved = commit("m3")
        got = M.merge_commit(root, "true", "main")
        check("rc4 ...and after the parent moved on, still the merge commit and not "
              "the parent's current head: %r (merge %r, parent now %r)"
              % (got, merge, moved),
              got["sha"] == merge and got["sha"] != moved)
        git("checkout", "-q", "-b", "open")
        commit("o1")
        git("checkout", "-q", "main")
        got = M.merge_commit(root, "open", "main")
        check("rc5 a branch the parent does NOT hold recovers nothing, and says "
              "why - never a guess: %r" % (got,),
              got["sha"] == "" and bool(got["basis"]))

        # --- NESTED: merged --no-ff into an intermediate branch, that one into main
        git("checkout", "-q", "-b", "nested")
        commit("n1")
        git("checkout", "-q", "main")
        git("checkout", "-q", "-b", "integration")
        commit("i0")
        git("merge", "-q", "--no-ff", "-m", "nested into integration", "nested")
        git("checkout", "-q", "main")
        commit("m4")
        git("merge", "-q", "--no-ff", "-m", "integration into main", "integration")
        outer = head("main")
        moved = commit("m5")
        held = git("merge-base", "--is-ancestor", "refs/heads/nested",
                   "refs/heads/main").returncode == 0
        got = M.merge_commit(root, "nested", "main")
        check("rc6 a tip the parent holds through a NESTED merge (into an "
              "intermediate branch, that one into the parent), the parent moved on: "
              "the parent's own merge of the intermediate branch - the first-parent "
              "walk alone never meets the inner merge, so it must not come back "
              "empty: %r (held %r, outer merge %r, parent now %r)"
              % (got, held, outer, moved),
              held and got["sha"] == outer and got["sha"] != moved)

        # --- THE PARENT MERGED INTO THE BRANCH, then fast-forwarded and moved on --
        git("checkout", "-q", "-b", "synced")
        commit("s1")
        git("checkout", "-q", "main")
        commit("m6")
        git("checkout", "-q", "synced")
        git("merge", "-q", "--no-ff", "-m", "main into synced", "main")
        tip = head("synced")
        git("checkout", "-q", "main")
        git("merge", "-q", "--ff-only", "synced")
        moved = commit("m7")
        got = M.merge_commit(root, "synced", "main")
        check("rc7 the parent merged INTO the branch, then fast-forwarded to it and "
              "moved on: the tip, which that fast-forward put on the parent's "
              "first-parent chain: %r (tip %r, parent now %r)" % (got, tip, moved),
              got["sha"] == tip and got["sha"] != moved)

        # --- MERGED TWICE: the second merge is the one that brought the tip in ----
        git("checkout", "-q", "-b", "twice")
        commit("w1")
        git("checkout", "-q", "main")
        git("merge", "-q", "--no-ff", "-m", "twice, first", "twice")
        first = head("main")
        git("checkout", "-q", "twice")
        commit("w2")
        git("checkout", "-q", "main")
        git("merge", "-q", "--no-ff", "-m", "twice, second", "twice")
        second = head("main")
        moved = commit("m8")
        got = M.merge_commit(root, "twice", "main")
        check("rc8 a branch merged TWICE: the second merge, which brought the tip "
              "in - not the first, which holds only an older commit of it: %r "
              "(first %r, second %r, parent now %r)" % (got, first, second, moved),
              got["sha"] == second and second != first and got["sha"] != moved)
    finally:
        _harness.remove_tree(root)


def _backfill_cases(check):
    """A merge recorded before `mergedHead` existed gets one on a re-run, once, and
    `mergedAt` never moves; a recorded head is never replaced. With the branch
    still there the head is recovered from the parent's first-parent chain - in
    these fixtures, fast-forwards, the tip itself; with
    it gone it is
    the parent's head, written only over evidence the plan holds - every recorded
    task commit contained - and marked `mergedHeadAt`."""
    # --- BACKFILL THROUGH close(): the branch survives, the merge is recorded -----
    root = _harness.fixture_root("closephase-backfill-kept")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root, meta_extra={
            "merge": {"deleteBranch": False}})
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        stamped = _merged_head(mpath)
        _drop_merged_head(mpath)
        merged_at = _merged_at(mpath)
        now = _commit_on_main(root, git, "later.txt")
        rows_before = len(_backfill_rows(root))
        with open(mpath, "rb") as fh:
            before = fh.read()
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--dry-run"],
                      out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        check("bf0 --dry-run with the branch KEPT (the re-run goes through close()) "
              "names the merge commit it would record and writes nothing: exit %r, "
              "bytes unchanged %r, rows %r, %r"
              % (code, before == after, len(_backfill_rows(root)), lines[-4:]),
              code == M.E_OK and before == after
              and "  would write mergedHead = %s (the merge is recorded without "
                  "one)" % (stamped,) in lines
              and len(_backfill_rows(root)) == rows_before)
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        check("bf1 a recorded merge with NO mergedHead, re-run with its branch kept, "
              "gets the merge's OWN commit - not the parent's current head - with "
              "mergedAt unchanged, no mergedHeadAt, and one journal row: exit %r, "
              "mergedAt %r -> %r, mergedHead %r (merge %r, parent now %r), "
              "mergedHeadAt %r, rows %r -> %r"
              % (code, merged_at, _merged_at(mpath), _merged_head(mpath), stamped,
                 now, _merged_head_at(mpath), rows_before,
                 len(_backfill_rows(root))),
              code == M.E_OK and bool(merged_at) and stamped != now
              and _merged_at(mpath) == merged_at
              and _merged_head(mpath) == stamped
              and _merged_head_at(mpath) == "<absent>"
              and len(_backfill_rows(root)) == rows_before + 1)
        # READ BACK OUT OF THE TRAIL, not off the dict the writer built: the journal
        # keeps only allow-listed detail keys and drops the rest in silence.
        rows = _backfill_rows(root)
        det = (rows[-1].get("details") or {}) if rows else {}
        check("bf1b the backfill row, as the trail holds it, names the field, the "
              "head written, the untouched mergedAt, the parent whose chain it came "
              "from and that it was recovered: %r" % (det,),
              det.get("field") == "mergedHead" and det.get("to") == stamped
              and det.get("mergedAt") == merged_at and det.get("phaseId") == "P1"
              and det.get("parent") == "main"
              and "recovered" in (det.get("reason") or ""))
        again = _commit_on_main(root, git, "later2.txt")
        code = M.main([mpath, "P1", "--project", root], out=(lambda line: None))
        check("bf2 ALLOW: once backfilled, a further re-run keeps the head it has "
              "and writes no second row: exit %r, mergedHead %r (parent now %r), "
              "rows %r" % (code, _merged_head(mpath), again,
                           len(_backfill_rows(root))),
              code == M.E_OK and _merged_head(mpath) == stamped
              and _merged_at(mpath) == merged_at
              and len(_backfill_rows(root)) == rows_before + 1)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- BRANCH KEPT BUT ITS REF MOVED BACK: the recovery must not trust it -------
    # `git branch -f` onto an older commit the parent's chain holds makes the moved
    # tip look like a fast-forward, and recovering from it records a commit that
    # predates the phase's own work - a head a run could contain without that work.
    root = _harness.fixture_root("closephase-backfill-moved")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root, meta_extra={
            "merge": {"deleteBranch": False, "removeWorktree": False}})
        base = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        tip = git("rev-parse", "refs/heads/audit/p1-demo").stdout.decode().strip()
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        _drop_merged_head(mpath)
        _set_task_commit(mpath, tip)
        _commit_on_main(root, git, "later.txt")
        if os.path.isdir(wt):
            git("worktree", "remove", "--force", wt)
        git("branch", "-f", "audit/p1-demo", base)
        with open(mpath, "rb") as fh:
            before = fh.read()
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        text = "\n".join(lines)
        check("bk1 the branch ref MOVED BACK onto an older commit of the parent "
              "(`git branch -f`): the recovered commit does not hold the recorded "
              "task commit, so no head is written and the reason says which: exit "
              "%r, mergedHead %r (moved-to %r, task commit %r), bytes unchanged %r, "
              "rows %r, %r"
              % (code, _merged_head(mpath), base, tip, before == after,
                 len(_backfill_rows(root)), text[-300:]),
              _merged_head(mpath) is None and before == after
              and not _backfill_rows(root)
              and "mergedHead NOT recorded: " in text and tip in text)
        git("branch", "-f", "audit/p1-demo", tip)
        code = M.main([mpath, "P1", "--project", root], out=(lambda line: None))
        check("bk2 ALLOW: with the ref back on the phase's tip, the recorded task "
              "commit is held and the recovered commit is written: exit %r, "
              "mergedHead %r, tip %r" % (code, _merged_head(mpath), tip),
              code == M.E_OK and _merged_head(mpath) == tip
              and len(_backfill_rows(root)) == 1)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- THE DEFAULT RE-RUN, BRANCH GONE, NO EVIDENCE: refused -------------------
    root = _harness.fixture_root("closephase-backfill-noevidence")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        _drop_merged_head(mpath)
        _commit_on_main(root, git, "later.txt")
        with open(mpath, "rb") as fh:
            before = fh.read()
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        text = "\n".join(lines)
        check("bg1 branch gone and NO task commit recorded: the backfill is refused "
              "with the reason printed, nothing written, no row - the phase stays "
              "unknown: exit %r, bytes unchanged %r, rows %r, %r"
              % (code, before == after, len(_backfill_rows(root)), text[-300:]),
              code == M.E_OK and before == after and not _backfill_rows(root)
              and "mergedHead NOT recorded: " in text
              and "no task commit" in text)
        _set_task_commit(mpath, _fixture_git(root)(
            "commit-tree", "HEAD^{tree}", "-m", "elsewhere").stdout.decode().strip())
        with open(mpath, "rb") as fh:
            before = fh.read()
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        text = "\n".join(lines)
        check("bg2 branch gone and a recorded task commit the parent does NOT "
              "contain (a wrong parent, a rewound one, a squash): refused, nothing "
              "written: exit %r, bytes unchanged %r, rows %r, %r"
              % (code, before == after, len(_backfill_rows(root)), text[-300:]),
              code == M.E_OK and before == after and not _backfill_rows(root)
              and "mergedHead NOT recorded: " in text
              and "not-contained" in text)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- THE DEFAULT RE-RUN, BRANCH GONE, EVERY TASK COMMIT CONTAINED ------------
    root = _harness.fixture_root("closephase-backfill-gone")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        tip = git("rev-parse", "refs/heads/audit/p1-demo").stdout.decode().strip()
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        gone = git("rev-parse", "--verify", "--quiet",
                   "refs/heads/audit/p1-demo").returncode != 0
        _drop_merged_head(mpath)
        _set_task_commit(mpath, tip)
        merged_at = _merged_at(mpath)
        now = _commit_on_main(root, git, "later.txt")
        with open(mpath, "rb") as fh:
            before = fh.read()
        lines = []
        code = M.main([mpath, "P1", "--project", root, "--dry-run"],
                      out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        check("bf3 --dry-run on the default re-run says it would record the head "
              "and writes nothing: exit %r, bytes unchanged %r, %r"
              % (code, before == after, "\n".join(lines)[-300:]),
              code == M.E_OK and before == after
              and "  would write mergedHead = %s (the merge is recorded without "
                  "one)" % (now,) in lines
              and "nothing left to do" not in "\n".join(lines))
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        check("bf4 ALLOW: the DEFAULT re-run (branch deleted), every recorded task "
              "commit contained, backfills the parent's current head AND stamps "
              "mergedHeadAt, mergedAt unchanged: branch gone %r, exit %r, mergedAt "
              "%r -> %r, mergedHead %r, parent %r, mergedHeadAt %r, %r"
              % (gone, code, merged_at, _merged_at(mpath), _merged_head(mpath), now,
                 _merged_head_at(mpath), "\n".join(lines)[-300:]),
              gone and code == M.E_OK and _merged_at(mpath) == merged_at
              and _merged_head(mpath) == now
              and _merged_head_at(mpath) not in ("<absent>", None)
              and _merged_head_at(mpath) >= merged_at
              and "nothing left to do" not in "\n".join(lines)
              and "nothing left to merge or clean up" in "\n".join(lines)
              and any(ln.startswith("  mergedHead = %s written to" % (now,))
                      for ln in lines)
              and len(_backfill_rows(root)) == 1)
        det = _backfill_rows(root)[-1].get("details") or {}
        check("bf4b ...and its row carries the head and the evidence it rests on - "
              "the task commits, not a re-verified merge: %r" % (det,),
              det.get("to") == now and "task commit" in (det.get("reason") or ""))
        _commit_on_main(root, git, "later2.txt")
        with open(mpath, "rb") as fh:
            before = fh.read()
        rows = len(_backfill_rows(root))
        lines = []
        code = M.main([mpath, "P1", "--project", root], out=lines.append)
        with open(mpath, "rb") as fh:
            after = fh.read()
        check("bf5 ALLOW: the default re-run with BOTH fields present, the parent "
              "moved on, writes nothing - the plan's bytes and the row count are "
              "unchanged: exit %r, bytes unchanged %r, rows %r -> %r"
              % (code, before == after, rows, len(_backfill_rows(root))),
              code == M.E_OK and before == after
              and len(_backfill_rows(root)) == rows
              and "nothing left to do" in "\n".join(lines)
              and M.MERGED_HEAD_FIELD not in "\n".join(lines))
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)

    # --- A FIRST STAMP AFTER A HAND MERGE: the already-contained mode ------------
    root = _harness.fixture_root("closephase-backfill-hand")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        git("merge", "-q", "--ff-only", "audit/p1-demo")
        merge = git("rev-parse", "refs/heads/main").stdout.decode().strip()
        now = _commit_on_main(root, git, "after-hand-merge.txt")
        lines = []
        code = M.main([wt_mpath, "P1", "--project", root], out=lines.append)
        check("bf6 a branch merged BY HAND, the parent moved on, then closed "
              "(already-contained): the first write stamps mergedAt AND the merge's "
              "OWN commit, not the parent's current head, and no mergedHeadAt: exit "
              "%r, mergedAt %r, mergedHead %r (merge %r, parent now %r), "
              "mergedHeadAt %r, backfill rows %r"
              % (code, _merged_at(mpath), _merged_head(mpath), merge, now,
                 _merged_head_at(mpath), len(_backfill_rows(root))),
              code == M.E_OK and bool(_merged_at(mpath)) and merge != now
              and _merged_head(mpath) == merge
              and _merged_head_at(mpath) == "<absent>"
              and not _backfill_rows(root))
        # The merge row as the trail HOLDS it - read back through the journal, never
        # the dict the writer handed over. The allow-list drops a key it does not
        # hold in silence, so the handover and the trail can disagree and only a
        # read-back sees it: the parent was handed over and dropped for as long as
        # this case pinned the two-key shape.
        import _journal_io
        merged = [r for r in _journal_io.read_all(root)
                  if r.get("action") == M.ACTION_PHASE_MERGED]
        check("bf6b ...and exactly one merge row, whose details are the phase, the "
              "branch AND the parent it reached, read back from the trail: %r"
              % ([(r.get("details"), r.get("summary")) for r in merged],),
              len(merged) == 1
              and merged[0].get("details") == {"phaseId": "P1",
                                               "branch": "audit/p1-demo",
                                               "parent": "main"}
              and merged[0].get("summary") == "audit/p1-demo reached main")
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


def _full_row(run_id, head):
    """One scope-full ledger row that bears whole on every rule but ancestry: green,
    measured, timed, counted with a basis, clean, and running the one declared
    command - so the only question `full_status` has left to ask is git's."""
    import _evidence_io as E
    return {"v": E.ROW_VERSION, "runId": run_id, "ts": "2026-01-02T00:00:00Z",
            "scope": E.FULL_SCOPE, "status": "passed",
            "steps": [{"name": "gate", "command": "echo x", "exit": 0,
                       "durationMs": 1000}],
            "testedState": {"head": head},
            "observations": {"ranTotal": 3, "countsBasis": "three checks",
                             "dirtyOutside": []}}


def _backfill_direction_cases(check):
    """A backfilled head sits AT OR AFTER the merge, and every reader asks whether
    `mergedHead` is an ancestor of a run's head - so it is STRICTER than the merge's
    own commit, never more generous. A full run on the merge commit reads WHOLE
    against the stamped head and PROVISIONAL against a later backfilled one: a
    false provisional, the fail-safe direction."""
    import _evidence_io as E
    import _manifest_vocab as V
    root = _harness.fixture_root("closephase-backfill-direction")
    wt = None
    try:
        mpath, wt, wt_mpath, git = _worktree_fixture(root)
        tip = git("rev-parse", "refs/heads/audit/p1-demo").stdout.decode().strip()
        M.main([wt_mpath, "P1", "--project", root], out=(lambda line: None))
        stamped = _merged_head(mpath)
        _drop_merged_head(mpath)
        _set_task_commit(mpath, tip)
        later = _commit_on_main(root, git, "later.txt")
        M.main([mpath, "P1", "--project", root], out=(lambda line: None))
        backfilled = _merged_head(mpath)
        row = _full_row("run-at-merge", stamped)
        against_stamp = E.full_status([row], {"id": "P1", "mergedHead": stamped},
                                      root, ["echo x"])
        against_backfill = E.full_status(
            [row], {"id": "P1", "mergedHead": backfilled}, root, ["echo x"])
        check("bd1 SECOND DIRECTION: a full run on the merge commit reads WHOLE "
              "against the head the merge stamped: %r" % (against_stamp,),
              bool(stamped) and against_stamp["answer"] == V.FULL_STATUS_WHOLE)
        check("bd2 ...and PROVISIONAL against the later head a backfill records - "
              "stricter than the merge commit, never more generous: stamped %r, "
              "backfilled %r (parent then %r), %r"
              % (stamped, backfilled, later, against_backfill),
              backfilled == later and backfilled != stamped
              and against_backfill["answer"] == V.FULL_STATUS_PROVISIONAL)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


# --- the stamp under the index lock ------------------------------------------------
# Every other plan writer takes the index lock around its read-modify-write, so a
# stamp that did not was one side of a race the other side believed it had closed:
# two closes, or a close and a panel save, each read the plan, each wrote it whole,
# and the one written second carried the other's copy - both answering ok.

# How many times each race is run. Two closes released together lose on the
# unlocked code often, not on every trial, so the deterministic held-lock and inode
# cases are the ones that prove the fix; the races say the lock holds when real
# processes collide.
_RACE_TRIALS = 4

# One racing writer: imports first, then says it is ready, then waits for the shared
# release so both writers start their read-modify-write in the same instant.
#
# A `-hold` writer is HELD BETWEEN ITS READ AND ITS WRITE: it signals, then pauses
# before writing. An `-after` writer starts once that signal is up, so it runs inside
# the other's window on every trial. Released together and nothing more, a stamp -
# whose own window is a millisecond - almost never met a panel save in the middle
# of one, and the unlocked code passed that race by luck.
_RACER = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import _harness, _loader, _panel_write
M = _loader.load_script("close-phase.py")
role, root, mpath, pid, value, ready, go, signal = sys.argv[2:10]


def held_open(real):
    def wrapped(*a, **k):
        open(signal, "w").close()
        time.sleep(0.3)
        return real(*a, **k)
    return wrapped


if role == "stamp-hold":
    M._revalidated_write = held_open(M._revalidated_write)
elif role == "panel-hold":
    _panel_write._write_back = held_open(_panel_write._write_back)
open(ready, "w").close()
deadline = time.time() + 60
while not os.path.exists(go) and time.time() < deadline:
    time.sleep(0.001)
while role.endswith("-after") and not os.path.exists(signal) \
        and time.time() < deadline:
    time.sleep(0.001)
role = role.split("-")[0]
if role == "stamp":
    path, why = M.stamp_merged(mpath, pid, when=value)[:2]
    print(json.dumps({"ok": bool(path), "why": why}))
else:
    res = _panel_write.apply_composition(
        root, {"phases": {pid: {"reviewModel": value}}})
    print(json.dumps({"ok": bool(res.get("ok")), "why": res.get("findings")}))
'''

# Another run holding the index lock: it takes the lock, says so, and gives it back
# once its stdin closes.
_HOLDER = r'''
import sys
sys.path.insert(0, sys.argv[1])
import _harness, _locks
code = _locks.acquire(sys.argv[2], "index", note="fixture holder",
                      out=lambda *a, **k: None)
sys.stdout.write("held %d\n" % code)
sys.stdout.flush()
sys.stdin.read()
_locks.release(sys.argv[2], "index", out=lambda *a, **k: None)
'''


def _child_env():
    """The environment a fixture child runs under: no lock token this process
    carries, so the child is another run rather than a re-entry of this one."""
    env = dict(os.environ)
    env.pop(_locks.TOKEN_ENV, None)
    return env


def _race_plan(root, merged=()):
    """A git repository holding a single-file plan of two signed-off phases -
    git, so the lock taken is the shared one that waits for its holder."""
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phases = []
    for pid in ("P1", "P2"):
        ph = _signed_phase(pid, "audit/%s" % (pid.lower(),))
        ph["review"]["model"] = "sonnet"
        if pid in merged:
            ph["mergedAt"] = "2026-01-01T00:00:00Z"
        phases.append(ph)
    return _write_plan(root, {"version": 2, "developmentBranch": "main"}, phases)


def _race(root, mpath, racers):
    """Run `racers` - (role, phaseId, value) - released together. Returns each
    racer's parsed answer, or {"ok": False, "why": <what it printed>}."""
    procs = []
    go = os.path.join(root, ".go")
    signal = os.path.join(root, ".held")
    for n, (role, pid, value) in enumerate(racers):
        ready = os.path.join(root, ".ready%d" % (n,))
        procs.append((ready, subprocess.Popen(
            [sys.executable, "-c", _RACER, _output.TESTS_DIR, role, root, mpath,
             pid, value, ready, go, signal], cwd=root, env=_child_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)))
    deadline = time.time() + 60
    while not all(os.path.exists(r) for r, _p in procs) and time.time() < deadline:
        time.sleep(0.005)
    open(go, "w").close()
    answers = []
    for _ready, proc in procs:
        try:
            out = proc.communicate(timeout=90)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0].decode("utf-8", "replace")
        try:
            answers.append(json.loads(out.strip().splitlines()[-1]))
        except Exception:
            answers.append({"ok": False, "why": out[-400:]})
    return answers


def _plan_phase(mpath, pid):
    return [p for p in _mio.read_json(mpath)["phases"] if p.get("id") == pid][0]


def _lock_cases(check):
    """The stamp and the head backfill write under the index lock, and a rollback
    restores the prior bytes atomically."""
    root = _harness.fixture_root("closephase-held")
    holder = None
    real_wait = _locks.WAIT_SECONDS
    try:
        mpath = _race_plan(root, merged=("P1",))
        with open(mpath, "rb") as fh:
            before = fh.read()
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, _output.TESTS_DIR, root], cwd=root,
            env=_child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        said = holder.stdout.readline().decode("utf-8", "replace").strip()
        # The holder is live for the whole window, so the default wait would only
        # make the case slower: it is shortened, never removed.
        _locks.WAIT_SECONDS = 0.2
        path1, why1 = M.stamp_merged(mpath, "P2", when="2026-02-02T02:02:02Z")[:2]
        path2, head2, why2 = M.record_merged_head(mpath, "P1", "a" * 40)[:3]
        with open(mpath, "rb") as fh:
            after = fh.read()
        check("lk1 with another run holding the index lock the stamp writes nothing, "
              "says the lock was not taken and names the re-run that stamps it "
              "(holder %r): %r" % (said, why1),
              said == "held 0" and path1 == "" and "not taken" in why1
              and "run close-phase again for P2" in why1 and after == before)
        check("lk2 ...and so does the head backfill, leaving the plan's bytes as "
              "they were: %r" % (why2,),
              path2 == "" and head2 == "" and "not taken" in why2
              and "run close-phase again for P1" in why2 and after == before)
        holder.stdin.close()
        holder.wait(timeout=30)
        holder = None
        path3, stamp3 = M.stamp_merged(mpath, "P2", when="2026-02-02T02:02:02Z")[:2]
        path4, head4, why4 = M.record_merged_head(mpath, "P1", "a" * 40)[:3]
        check("lk3 SECOND DIRECTION: with the lock free both write - the case that "
              "goes red when the lock is refused unconditionally: %r / %r"
              % (stamp3, why4),
              path3 == mpath and stamp3 == "2026-02-02T02:02:02Z"
              and _plan_phase(mpath, "P2").get("mergedAt") == stamp3
              and head4 == "a" * 40
              and _plan_phase(mpath, "P1").get("mergedHead") == "a" * 40)
    finally:
        _locks.WAIT_SECONDS = real_wait
        if holder is not None:
            holder.stdin.close()
            holder.wait(timeout=30)
        _harness.remove_tree(root)

    # THE ROLLBACK IS AN ATOMIC REPLACE. The write itself replaced the file, so the
    # file's inode right after it is the one an in-place rollback would keep; a
    # restore through temp-plus-replace leaves a different one, with the bytes back.
    root = _harness.fixture_root("closephase-inode")
    real_write, real_findings = M._mio.atomic_write_json, M._findings_of
    try:
        mpath = _write_plan(root, {"version": 2, "developmentBranch": "main"},
                            [_signed_phase("P1", "audit/p1")])
        with open(mpath, "rb") as fh:
            before = fh.read()
        written = []

        def recording_write(path, obj, **kw):
            real_write(path, obj, **kw)
            written.append(os.stat(path).st_ino)

        def stamped_is_a_finding(manifest_path):
            body = _mio.read_json(manifest_path)
            if any(p.get("mergedAt") for p in body.get("phases") or []):
                return set(["fixture: a stamped phase is a finding here"])
            return set()
        M._mio.atomic_write_json = recording_write
        M._findings_of = stamped_is_a_finding
        path5, why5 = M.stamp_merged(mpath, "P1", when="2026-03-03T03:03:03Z")[:2]
        with open(mpath, "rb") as fh:
            after = fh.read()
        final = os.stat(mpath).st_ino
        check("lk4 a stamp whose write introduces a finding restores the prior bytes "
              "through an atomic replace: the bytes match and the inode is not the "
              "one the write left, which an in-place rewrite keeps (written %r, "
              "now %r): %r" % (written, final, why5),
              path5 == "" and "restored" in why5 and after == before
              and len(written) == 1 and final != written[0])
        M._findings_of = lambda _m: set()
        path6, stamp6 = M.stamp_merged(mpath, "P1", when="2026-03-03T03:03:03Z")[:2]
        check("lk5 SECOND DIRECTION: a stamp introducing no finding stands - the case "
              "that goes red when every stamp is rolled back: %r" % (stamp6,),
              path6 == mpath
              and _plan_phase(mpath, "P1").get("mergedAt") == stamp6)
    finally:
        M._mio.atomic_write_json, M._findings_of = real_write, real_findings
        _harness.remove_tree(root)

    # THE RACES, between real processes released together.
    lost, unanswered = [], []
    for trial in range(_RACE_TRIALS):
        root = _harness.fixture_root("closephase-race")
        try:
            mpath = _race_plan(root)
            answers = _race(root, mpath, [("stamp", "P1", "2026-04-04T04:04:0%dZ" % trial),
                                          ("stamp", "P2", "2026-04-04T04:04:1%dZ" % trial)])
            unanswered += [a["why"] for a in answers if not a.get("ok")]
            lost += ["trial %d %s" % (trial, pid) for pid in ("P1", "P2")
                     if not _plan_phase(mpath, pid).get("mergedAt")]
        finally:
            _harness.remove_tree(root)
    check("lk6 two processes stamping different phases of one single-file plan, "
          "released together over %d trials, both answer ok and lose no mergedAt: "
          "lost %r, unanswered %r" % (_RACE_TRIALS, lost, unanswered),
          lost == [] and unanswered == [])

    # Alternating which writer is caught mid-write: an even trial holds the panel
    # save open while a stamp runs, an odd one holds the stamp open while a save runs.
    lost, unanswered = [], []
    for trial in range(_RACE_TRIALS):
        root = _harness.fixture_root("closephase-panel")
        try:
            mpath = _race_plan(root)
            when = "2026-05-05T05:05:0%dZ" % (trial,)
            roles = ("stamp-after", "panel-hold") if trial % 2 == 0 \
                else ("stamp-hold", "panel-after")
            answers = _race(root, mpath, [(roles[0], "P1", when),
                                          (roles[1], "P2", "opus")])
            unanswered += [a["why"] for a in answers if not a.get("ok")]
            if answers[0].get("ok") and _plan_phase(mpath, "P1").get("mergedAt") != when:
                lost.append("trial %d stamp" % (trial,))
            if answers[1].get("ok") and (_plan_phase(mpath, "P2").get("review")
                                         or {}).get("model") != "opus":
                lost.append("trial %d save" % (trial,))
        finally:
            _harness.remove_tree(root)
    check("lk7 stamps racing panel composition saves over %d trials, each writer "
          "in turn caught between its read and its write while the other runs, "
          "lose neither a stamp nor a save that answered ok: lost %r, "
          "unanswered %r" % (_RACE_TRIALS, lost, unanswered),
          lost == [] and unanswered == [])


# What the lock module says when it refuses to hand back a claim another session
# has taken over: built from parts, so it is one value the cases can count.
_TAKEN_OVER = "the index lock is held by %s now; this run's release was declined" \
    % ("another session",)


def _declining(real, said):
    """`release_index_lock` that gives the lock back as the real one does and then
    answers as a release the lock DECLINED - the claim having been taken over."""
    def release(lock, out=None):
        real(lock, out=out)
        if out is not None:
            out(said)
        return said
    return release


def _close_run(root, wt_mpath, *extra):
    """`(exit, text, answer)` of one close-phase run over `_worktree_fixture`, the
    answer read from the same run's `--json`."""
    lines = []
    code = M.main([wt_mpath, "P1", "--project", root, "--json"] + list(extra),
                  out=lines.append)
    text = "\n".join(lines)
    try:
        answer = json.loads(text)
    except ValueError:
        answer = {}
    return code, text, answer


def _stamped_is_a_finding(manifest_path):
    """A validator under which a stamped phase is the write's own finding, so every
    stamp is refused and its rollback is what runs."""
    body = _mio.read_json(manifest_path)
    if any(p.get("mergedAt") for p in body.get("phases") or []):
        return set(["fixture: a stamped phase is a finding here"])
    return set()


def _takeover_cases(check):
    """A stamp written under a lock another session took over, and a refused write
    whose rollback itself failed: neither may read as the ordinary outcome."""
    real_release = M._panel_write.release_index_lock
    real_restore, real_findings = M._panel_write.restore, M._findings_of

    # --- the release, at the function a close calls ---------------------------
    root = _harness.fixture_root("closephase-takeover-unit")
    try:
        mpath = _write_plan(root, {"version": 2, "developmentBranch": "main"},
                            [_signed_phase("P1", "audit/p1")])
        M._panel_write.release_index_lock = _declining(real_release, _TAKEN_OVER)
        try:
            got = M.stamp_merged(mpath, "P1", when="2026-06-06T06:06:06Z")
        finally:
            M._panel_write.release_index_lock = real_release
        notes = got[2] if len(got) > 2 else {}
        check("to1 a stamp whose index-lock release is DECLINED hands the release's "
              "sentence back beside the path it wrote, rather than dropping it: %r"
              % (got,),
              got[0] == mpath and notes.get("released") == _TAKEN_OVER)
        mpath2 = _write_plan(root, {"version": 2, "developmentBranch": "main"},
                             [_signed_phase("P1", "audit/p1")])
        got2 = M.stamp_merged(mpath2, "P1", when="2026-06-06T06:06:06Z")
        notes2 = got2[2] if len(got2) > 2 else None
        check("to2 SECOND DIRECTION: an ordinary release hands back no sentence - the "
              "case that goes red when every release is reported as taken over: %r"
              % (got2,),
              got2[0] == mpath2 and notes2 == {"released": "", "unrestored": False})
    finally:
        M._panel_write.release_index_lock = real_release
        _harness.remove_tree(root)

    # --- the release, in the close answer -------------------------------------
    for declined in (True, False):
        root = _harness.fixture_root("closephase-takeover")
        wt = None
        try:
            mpath, wt, wt_mpath, _git = _worktree_fixture(root)
            if declined:
                M._panel_write.release_index_lock = _declining(real_release,
                                                               _TAKEN_OVER)
            try:
                code, text, answer = _close_run(root, wt_mpath, "--keep-worktree",
                                                "--keep-branch")
            finally:
                M._panel_write.release_index_lock = real_release
            lines = []
            if answer:
                M.render(answer, out=lines.append)
            rendered = "\n".join(lines)
            if declined:
                check("to3 a close whose stamp was written under a lock taken over "
                      "carries the release sentence in its answer, and its rendered "
                      "text says it once, on a warning line: exit %r, warnings %r, "
                      "%r" % (code, answer.get("lockWarnings"), rendered[-400:]),
                      bool(_merged_at(mpath))
                      and answer.get("lockWarnings") == [_TAKEN_OVER]
                      and rendered.count(_TAKEN_OVER) == 1
                      and "WARNING" in [ln for ln in lines
                                        if _TAKEN_OVER in ln][0])
            else:
                check("to4 SECOND DIRECTION: a close whose release is ordinary adds "
                      "no warning to its answer or its text - the case that goes "
                      "red when a warning is written unconditionally: exit %r, "
                      "%r / %r" % (code, answer.get("lockWarnings"),
                                   rendered[-300:]),
                      code == M.E_OK and bool(_merged_at(mpath)) and bool(answer)
                      and not answer.get("lockWarnings")
                      and "WARNING" not in rendered)
        finally:
            M._panel_write.release_index_lock = real_release
            _harness.remove_tree(root)
            if wt and os.path.isdir(wt):
                _harness.remove_tree(wt)

    # --- a rollback that itself fails -----------------------------------------
    def _no_restore(_snap):
        raise OSError("No space left on device")
    root = _harness.fixture_root("closephase-unrestored-unit")
    try:
        for broken in (True, False):
            mpath = _write_plan(root, {"version": 2, "developmentBranch": "main"},
                                [_signed_phase("P1", "audit/p1")])
            M._findings_of = _stamped_is_a_finding
            if broken:
                M._panel_write.restore = _no_restore
            try:
                got = M.stamp_merged(mpath, "P1", when="2026-07-07T07:07:07Z")
            finally:
                M._panel_write.restore = real_restore
                M._findings_of = real_findings
            why = got[1]
            notes = got[2] if len(got) > 2 else {}
            if broken:
                check("to5 a refused stamp whose restore RAISES says the write landed "
                      "and was not rolled back, names the finding and the error, and "
                      "never says the file could not be written: %r" % (why,),
                      got[0] == "" and "was written and introduced" in why
                      and "fixture: a stamped phase is a finding here" in why
                      and "restoring its prior bytes failed" in why
                      and "No space left on device" in why
                      and "the plan holds the refused write" in why
                      and "could not be written" not in why
                      and notes.get("unrestored") is True
                      and bool(_merged_at(mpath)))
            else:
                check("to6 SECOND DIRECTION: a refused stamp whose restore works says "
                      "the prior bytes were restored and claims no stranded write - "
                      "the case that goes red when every rollback is reported as "
                      "failed: %r / %r" % (why, notes),
                      got[0] == "" and "restored" in why
                      and "holds the refused write" not in why
                      and notes.get("unrestored") is False
                      and not _merged_at(mpath))
    finally:
        M._panel_write.restore = real_restore
        M._findings_of = real_findings
        _harness.remove_tree(root)

    for broken in (True, False):
        root = _harness.fixture_root("closephase-unrestored")
        wt = None
        try:
            mpath, wt, wt_mpath, _git = _worktree_fixture(root)
            M._findings_of = _stamped_is_a_finding
            if broken:
                M._panel_write.restore = _no_restore
            try:
                code, text, answer = _close_run(root, wt_mpath)
            finally:
                M._panel_write.restore = real_restore
                M._findings_of = real_findings
            lines = []
            if answer:
                M.render(answer, out=lines.append)
            rendered = "\n".join(lines)
            if broken:
                check("to7 a close whose refused stamp could not be rolled back exits "
                      "as a failure, says the plan holds the refused write, keeps "
                      "the worktree, and never says mergedAt could not be written: "
                      "exit %r, %r" % (code, rendered[-500:]),
                      code not in (M.E_OK,) and bool(answer)
                      and "the plan holds the refused write" in rendered
                      and "could not be written" not in rendered
                      and "NOT written" not in rendered
                      and os.path.isdir(wt))
            else:
                check("to8 SECOND DIRECTION: a refused stamp that WAS rolled back is "
                      "a failing exit that says so and claims no stranded write - "
                      "the case that goes red when the stranded-write sentence is "
                      "printed for every refusal: exit %r, %r"
                      % (code, rendered[-400:]),
                      code not in (M.E_OK,) and bool(answer)
                      and "restored" in rendered
                      and "holds the refused write" not in rendered
                      and not _merged_at(mpath))
        finally:
            M._panel_write.restore = real_restore
            M._findings_of = real_findings
            _harness.remove_tree(root)
            if wt and os.path.isdir(wt):
                _harness.remove_tree(wt)


def _cli(mpath, root, *extra):
    """`(exit, stdout)` of this command run as the main loop runs it: a process,
    with the session's own variables dropped."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("close-phase.py"), mpath, "P1",
         "--project", root] + list(extra),
        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _sl_repo(root, dirty=False):
    """A signed-off phase branch one commit ahead of `main`, standing on main -
    with, when `dirty`, an uncommitted edit there that refuses the landing."""
    git = _fixture_git(root)
    _init_fixture_repo(git)
    phase = _signed_phase("P1", "audit/p1-demo")
    mpath = _write_plan(root, {"developmentBranch": "main"}, [phase])
    with open(os.path.join(root, "tracked.txt"), "w") as fh:
        fh.write("base\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "audit/p1-demo")
    with open(os.path.join(root, "work.txt"), "w") as fh:
        fh.write("work\n")
    git("add", "-A")
    git("commit", "-q", "-m", "work")
    git("checkout", "-q", "main")
    if dirty:
        with open(os.path.join(root, "tracked.txt"), "a") as fh:
            fh.write("uncommitted\n")
    return git, mpath


def _sl_on_main(git):
    """Whether the phase's work reached `main` - asked of `main` itself, since a
    landing deletes the branch it merged."""
    return git("cat-file", "-e", "main:work.txt").returncode == 0


def _success_line_cases(check):
    """A landing, said in one line naming the merge and the record it wrote; a
    preview, a refusal and `--verbose`, in full."""
    root = _harness.fixture_root("closephase-sl-")
    git, mpath = _sl_repo(root)
    code, short = _cli(mpath, root)
    lines = short.splitlines()
    check("sl1 a landing prints ONE line within the byte bound, naming the "
          "branch, its parent, the merged head and the file the merge was "
          "recorded in: %r" % (short,),
          code == 0 and len(lines) == 1 and _sl_on_main(git)
          and len(lines[0].encode("utf-8")) <= 200
          and lines[0].startswith("[close-phase] audit/p1-demo -> main")
          and "written to docs/audit/audit-plan.json" in lines[0]
          and "mergedHead = " in lines[0])
    vroot = _harness.fixture_root("closephase-sl-verbose-")
    vgit, vmpath = _sl_repo(vroot)
    vcode, verbose = _cli(vmpath, vroot, "--verbose")
    check("sl2 ...and `--verbose` prints what a landing always printed: every "
          "git step with its exit, and the fields written: %r"
          % (verbose[-200:],),
          vcode == 0 and _sl_on_main(vgit) and len(verbose.splitlines()) > 3
          and any(ln.startswith("  git ") for ln in verbose.splitlines())
          and any(ln.startswith("  mergedAt = ")
                  for ln in verbose.splitlines()))
    proot = _harness.fixture_root("closephase-sl-preview-")
    _pgit, pmpath = _sl_repo(proot)
    preview = _cli(pmpath, proot, "--dry-run")
    check("sl3 a preview is a success that still owes the reader its plan, so "
          "it prints in full: %r" % (preview[1][-200:],),
          preview[0] == 0 and "would run: git " in preview[1]
          and len(preview[1].splitlines()) > 1)
    rroot = _harness.fixture_root("closephase-sl-refused-")
    _rgit, rmpath = _sl_repo(rroot, dirty=True)
    refused = _cli(rmpath, rroot)
    check("sl4 a refusal prints in full, `--verbose` or not - the deny twin of "
          "sl1: %r" % (refused[1][-200:],),
          refused[0] != 0 and "REFUSED: " in refused[1]
          and len(refused[1].splitlines()) > 1
          and refused == _cli(rmpath, rroot, "--verbose"))


def _selftest():
    def body(check):
        _takeover_cases(check)
        _lock_cases(check)
        _no_survivor_cases(check)
        _landed_survivor_cases(check)
        _cases(check)
        _parked_cases(check)
        _landed_cases(check)
        _main_tree_cases(check)
        _override_cases(check)
        _landing_cases(check)
        _checked_out_cases(check)
        _symlink_cases(check)
        _composed_cases(check)
        _same_dir_cases(check)
        _surviving_copy_cases(check)
        _merged_head_cases(check)
        _backfill_cases(check)
        _backfill_direction_cases(check)
        _recovery_cases(check)
        _harness.stage(check, "sl-block", _success_line_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_close_phase.py --selftest\n")
    raise SystemExit(2)
