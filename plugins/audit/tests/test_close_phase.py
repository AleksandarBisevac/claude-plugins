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
        with open(shard, "w") as fh:
            json.dump({"id": "P2", "mergedAt": "2026-01-02T03:04:05Z"}, fh)
        path4, stamp4 = M.stamp_merged(shard, "P2", when="2026-09-09T09:09:09Z")
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
        path5, _st5 = M.stamp_merged(mpath, "P2", when="2026-01-02T03:04:05Z")
        body5 = _mio.read_json(spath)
        check("s5 the stamp stores the status the merge now derives - done, for a "
              "signed-off phase with every task terminal - in the same write as "
              "mergedAt: %r" % (body5.get("status"),),
              path5 == spath and body5.get("status") == "done"
              and body5.get("mergedAt") == "2026-01-02T03:04:05Z")
        mirrored, why = M.mirror_stub(mpath, "P2", root)
        check("s6 ...and the index stub is re-mirrored from that shard, so the index "
              "alone reads done too: stub=%r (%s)" % (stub_of().get("status"), why),
              mirrored == mpath and stub_of().get("status") == "done")
        with open(mpath, "rb") as fh:
            before = fh.read()
        again, why2 = M.mirror_stub(mpath, "P2", root)
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
            got9, why9 = M.mirror_stub(mpath, "P2", root)
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
                got10, why10 = M.mirror_stub(mpath, "P2", root)
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
    import subprocess
    import _branch
    root = _harness.fixture_root("closephase-landed")
    try:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def git(*a):
            return subprocess.run(["git", "-C", root] + list(a), env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git("init", "-q", "-b", "main")
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
              code == M.E_OK and "nothing left to do" in "\n".join(lines))
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
        git("init", "-q", "-b", "main")
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


def _composed_cases(check):
    """A phase with no recorded branch: the name close-phase asks git about was
    composed, and a composed name that is not a branch is a question for the
    operator, not an unanswerable ancestry."""
    import _branch
    root = _harness.fixture_root("closephase-composed")
    try:
        git = _fixture_git(root)
        git("init", "-q", "-b", "main")
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
    git("init", "-q", "-b", "main")
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
        check("sv3 a dry-run standing inside the worktree prints a follow-up naming the "
              "SURVIVING manifest - main's - never the worktree's copy: %r" % (follow,),
              len(follow) == 1 and "docs/audit/audit-plan.json" in follow[0]
              and os.path.realpath(wt) not in follow[0] and wt not in follow[0]
              and ("From %s," % (os.path.realpath(root),) in text
                   or "From %s," % (root,) in text))
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
    the same write as `mergedAt` - never a second write, never the branch tip, and
    never re-derived once a merge is already recorded."""
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
              and merged_head == head and len(merged_head or "") == 40)
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
              and "nothing left to do" not in text)
    finally:
        _harness.remove_tree(root)
        if wt and os.path.isdir(wt):
            _harness.remove_tree(wt)


def _selftest():
    def body(check):
        _no_survivor_cases(check)
        _landed_survivor_cases(check)
        _cases(check)
        _parked_cases(check)
        _landed_cases(check)
        _main_tree_cases(check)
        _composed_cases(check)
        _surviving_copy_cases(check)
        _merged_head_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_close_phase.py --selftest\n")
    raise SystemExit(2)
