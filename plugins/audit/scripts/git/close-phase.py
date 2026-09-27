#!/usr/bin/env python3
"""Land a signed-off phase on its parent branch, or say exactly why it did not.

WHY THIS EXISTS. `reference/orchestrator.md` steps 5c-5e were prose the model
executed: `git switch <parent>`, `git merge --ff-only <branch>`, and "optionally
clean up: `git branch -d <branch>`". Three measured facts make that prose wrong
rather than merely informal.

  * `git switch <parent>` CANNOT RUN in the worktree the phase ran in. Measured:
    `fatal: 'main' is already used by worktree at '<the main tree>'`, exit 128.
    `/audit:worktree` exists to put phases in linked worktrees, so the documented
    sign-off was unavailable on exactly the runs the plugin recommends.
  * `git branch -d` GRADES AGAINST HEAD, NOT AGAINST THE PARENT. Measured: a branch
    whose `parentBranch` is `develop`, merged only into `main`, deleted with exit 0.
    "Safe after a completed merge" was leaning on a check that answers a different
    question -- and `_doctor_policy.check_branch_naming` already warned in prose
    about the case it lets through.
  * THE TWO MERGE PATHS DISAGREE ABOUT AN ALREADY-LANDED PHASE. `git merge --ff-only`
    says `Already up to date.` exit 0; `git fetch . <b>:<p>` says `! [rejected]
    (non-fast-forward)` exit 1 -- byte-identical to a real divergence. A rule with a
    case like that is a rule that needs cases, which is what `_worktrees.merge_plan`
    is.

WHAT IT NEVER DOES. It never moves an operator's HEAD -- no `git switch`, in any
mode. It never forces: no `+` refspec, no `branch -D`, no `merge --no-ff` unless the
human passed the flag. It never skips a hook either: `--no-verify` is named in one
refusal's remedy and appears in no argv this command runs, so a hook is only
ever skipped by a person typing it. It never deletes a branch that did not reach ITS
parent. And it never runs the second half of a cleanup when the first half was
refused.

DECIDE, THEN WRITE, THEN READ BACK -- `commit-audit-state.py`'s shape. Every
precondition is resolved into a plan before the first mutation, so a refusal leaves
the repository exactly as it was found. After the merge the parent SHA is re-read AND
the ancestry re-asked: two computations rather than one, because comparing the
merge's own output against itself would be a check that cannot go red.

Usage:
  close-phase.py <manifest> <phaseId> [--project DIR] [--parent BRANCH]
                 [--branch NAME] [--remove-worktree] [--delete-branch]
                 [--no-ff] [--dry-run] [--json]

  --parent / --branch override what `_branch` resolves, for a phase whose branch was
  renamed by hand. Both are reported with basis "argument" rather than
  "phase.parentBranch": a name nobody can explain is the thing this plugin refuses to
  print.
  --remove-worktree / --delete-branch are OPT-IN and independent, and default to
  what `meta.merge` says. Cleanup is never implied by a successful merge.
  --no-ff is honoured ONLY when passed. Exit 3 is how the orchestrator learns it
  needs to ask.
  --dry-run prints the plan, every refusal it already knows about, and the exact argv
  it would run. It reaches no writing command at all.

Exit codes:
  0  the parent contains the branch -- it was merged now, or it already did -- and
     every cleanup asked for was done and read back. Also the answer when
     `meta.merge.auto` is false and the run deliberately stopped before the merge
  1  it could not: git refused a write, a precondition failed, or a cleanup was
     blocked. The refusal names the path or ref that has to change - a branch that
     is its own parent, or a phase that records no branch whose composed name is
     not one, included: git answered, and it is the command that has to change
  2  usage error -- the manifest will not load, or there is no such phase, or the
     parent is checked out in no worktree while the manifest given is the phase
     worktree's own copy: the landing would have no surviving copy to stamp
  3  NOT A FAST-FORWARD -- the parent moved while the phase ran. Nothing was written.
     Its own sentinel because it is the normal case on a team repo and the
     orchestrator has a human question for it; folded into 1 it would be
     indistinguishable from "the tree was dirty", which is a different conversation
  4  it could not be ASKED -- git is not on PATH, or would not describe the worktrees
     or the ancestry. NOT 1, for `verify-invariants.py`'s reason: "git refused" and
     "git could not be asked" are different states of the world, and a caller that
     cannot tell them apart will retry the wrong one
"""
import argparse
import datetime
import json
import os
import shutil
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _branch                                                       # noqa: E402
import _journal_io                                                   # noqa: E402
import _manifest_io as _mio                                          # noqa: E402
import _manifest_rules as _rules  # noqa: E402  (revalidate what the stamp writes)
import _panel_write  # noqa: E402  (the index lock the stub mirror is written under)
import _proposals  # noqa: E402  (parked_on_branch: the work this branch deferred)
import _worktrees as _wt                                             # noqa: E402

E_OK, E_FAIL, E_USAGE, E_NOT_FF, E_NO_BASIS = 0, 1, 2, 3, 4

# The journal action for a phase that reached its parent. A new name beside
# `_invariants.ACTION_STATE_COMMITTED` rather than a reuse: the trail is read by
# people asking "when did this land", and a row that says "state committed" for a
# merge answers a different question.
ACTION_PHASE_MERGED = "phase.merged"

# The one thing this command does that is not a merge and not a cleanup: the moment
# the phase reached its parent, written into the plan. Worded as a constant because
# the dry-run prints it and the writer writes it, and two spellings of one sentence
# is where they start to disagree.
MERGED_FIELD = "mergedAt"

# The oldest commit on the parent's first-parent chain that contains the tip: the
# commit on that chain that brought the tip in - the tip itself for a
# fast-forward, the merge commit for a direct merge, the parent's merge of an
# intermediate branch for a nested one - and never a second write away from
# `mergedAt`. A sentinel (not None) is `stamp_merged`'s
# default for this one, so a caller that never mentions it leaves the key untouched
# rather than pinning it to null; `main()` always passes one or the other on purpose.
MERGED_HEAD_FIELD = "mergedHead"
_HEAD_NOT_ASKED = object()

# Present ONLY when `mergedHead` was recorded after the fact with the branch gone,
# so it is the parent's head at that moment rather than the merge's own commit -
# the moment a reader measures "ran after" against. Absent means `mergedHead` is
# what `merge_commit` recovers.
MERGED_HEAD_AT_FIELD = "mergedHeadAt"

# The journal action for a head written AFTER its merge was recorded - a plan whose
# merge predates the field. Its own name rather than a second `phase.merged` row:
# nothing merged on the run that writes it, and a reader counting merges by that
# action must not count this one.
ACTION_MERGED_HEAD_RECORDED = "phase.mergedHead.recorded"


# --- resolving what this phase is ------------------------------------------------

def resolve(manifest, phase, parent_arg=None, branch_arg=None, initials=None):
    """{"branch", "parent", "branchBasis", "parentBasis", "policy"} -- the names this
    run will hand git, each with the key that produced it.

    An override is reported as `argument` rather than silently taking the shape of a
    manifest key. A branch nobody can explain is the thing `_branch` exists to
    prevent, and an override that borrowed `phase.parentBranch`'s basis would put a
    claim in the report that the manifest does not support.
    """
    meta = (manifest or {}).get("meta") or {}
    if branch_arg:
        branch, bbasis = str(branch_arg), "argument (--branch)"
    else:
        recorded = (phase or {}).get("branch")
        if recorded:
            branch, bbasis = str(recorded), "phase.branch"
        else:
            # `_branch.phase_answer`, the name `start`, `resolve-branch.py` and
            # `/audit:worktree add` compose - a phase landed from a parent whose
            # copy of the plan never recorded the branch is found by the SAME name
            # that cut it, git user.name and a bug phase's type included.
            composed = _branch.phase_answer(meta, phase, initials)
            branch = composed["branch"]
            bbasis = "composed (%s)" % composed["branchBasis"]
    if parent_arg:
        parent, pbasis = str(parent_arg), "argument (--parent)"
    else:
        resolved = _branch.parent_branch(meta, phase)
        parent, pbasis = resolved["branch"], resolved["basis"]
    # A BRANCH THAT IS ITS OWN PARENT HAS NOTHING TO LAND, and the cleanup would
    # then plan deleting the parent itself: already contained, settled, and held by
    # no worktree reads as a branch to reap. Refused here, where both names meet.
    refusal = None
    if branch and branch == parent:
        refusal = ("%r is its own parent (%s; parent from %s) - there is nothing to "
                   "land, and the cleanup would delete %r. Name the branch the "
                   "phase's work is on with --branch" % (branch, bbasis, pbasis,
                                                          parent))
    return {"branch": branch, "parent": parent, "branchBasis": bbasis,
            "parentBasis": pbasis, "policy": _branch.merge_policy(meta),
            "refusal": refusal}


# --- observing the repository ----------------------------------------------------

def observe(git_root, branch, parent, cwd=None, run=None):
    """Everything the planners need, asked once. `why` is non-empty when git would
    not answer at all, and the caller exits 4 rather than planning on a guess."""
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return {"trees": [], "why": listing["error"]}
    trees = listing["trees"]
    parent_tree = _wt.holder_of(trees, parent)["tree"]
    phase_tree = _wt.holder_of(trees, branch)["tree"]
    contained = _wt.merged_into(git_root, branch, parent, run=run)
    parent_dirt = ({"dirty": None, "lines": []} if parent_tree is None
                   or parent_tree.get("prunable")
                   else _wt.dirtiness(parent_tree.get("path"), run=run))
    phase_dirt = ({"dirty": None, "lines": []} if phase_tree is None
                  or phase_tree.get("prunable")
                  else _wt.dirtiness(phase_tree.get("path"), run=run))
    return {
        "trees": trees,
        "contained": contained,
        "parentExists": _wt.ref_exists(git_root, parent, run=run),
        # Where the phase branch points, for the guarded deletion.
        "branchExists": _wt.ref_exists(git_root, branch, run=run),
        "parentTree": parent_tree,
        "phaseTree": phase_tree,
        "parentDirty": parent_dirt,
        "phaseDirty": phase_dirt,
        # Named rather than left as None: this IS an answer, and `cleanup_plan`
        # now refuses on the absent one.
        "standingIn": (_wt.standing_in(trees, cwd or os.getcwd())
                       or _wt.CWD_OUTSIDE),
        # WHOSE WORKTREE IS IT. Asked here so the dry-run can say so before anything
        # runs: a phase that ran in a worktree the operator made by hand will merge
        # and will NOT be cleaned up, and being told that up front is the difference
        # between a considered refusal and a surprise.
        "owned": ({"ok": False,
                   "why": "no worktree holds %r, so there is none to own"
                          % (branch,)}
                  if phase_tree is None else _owned_of(phase_tree, run)),
        "why": "",
    }


def _owned_of(tree, run=None):
    """`{"ok", "why"}` for one worktree's provenance, in `cleanup_plan`'s shape.

    The tree's CURRENT branch is handed over, so the marker has to describe the work
    that is in it rather than merely to exist.
    """
    prov = _wt.read_provenance(tree.get("path"), run=run,
                               expect_branch=tree.get("branch"))
    return {"ok": prov["ours"] is True, "why": prov["basis"],
            "record": prov["record"]}


def settlement(phase, merged=False):
    """`{"ok", "why"}` -- is the plugin finished with this phase, for cleanup?

    `merged=True` is what THIS RUN has just established, and it is not a shortcut
    past `phase_settled`: the other two marks - sign-off done, every task terminal -
    are still required. What it replaces is the `mergedAt` mark alone, because the
    orchestrator writes that AFTER this command returns and the field is null while
    the command is deciding. Reading the stale null would refuse every cleanup this
    command exists to perform, which is a deadlock rather than a safeguard.
    """
    stamped = dict(phase or {})
    if merged and not stamped.get("mergedAt"):
        stamped["mergedAt"] = "verified by this run"
    verdict = _wt.phase_settled(stamped, _mio.TERMINAL,
                                status_of=_mio.effective_phase_status)
    return {"ok": verdict["settled"], "why": verdict["why"]}


# --- planning --------------------------------------------------------------------

def plan(observation, branch, parent, policy, want_worktree=None,
         want_branch=None, no_ff=False):
    """{"merge", "cleanup", "auto", "wantWorktree", "wantBranch"} -- the whole run,
    decided before anything is written.

    `want_*` default to the policy and are overridden by an explicit flag. `None`
    means "the policy decides", which is why they are not plain booleans: `False` has
    to mean the caller said no, and a flag defaulting to False cannot say that.
    """
    want_worktree = (policy["removeWorktree"] if want_worktree is None
                     else bool(want_worktree))
    want_branch = (policy["deleteBranch"] if want_branch is None
                   else bool(want_branch))
    contained = observation["contained"]["answer"]
    merge = _wt.merge_plan(
        observation["trees"], branch, parent, contained,
        observation["parentExists"]["exists"],
        observation["parentDirty"]["dirty"],
        observation["parentDirty"]["lines"])
    if no_ff and merge["mode"] == "in-parent-worktree":
        # The ONLY place `--no-ff` reaches, and only when the human passed it.
        merge = dict(merge, argv=[a for a in merge["argv"] if a != "--ff-only"])
        merge["argv"] = merge["argv"][:-1] + ["--no-ff", merge["argv"][-1]]
        merge["mode"] = "in-parent-worktree"
    elif no_ff and merge["mode"] == "no-checkout":
        # ...AND THE REFUSAL THIS COMMENT USED TO ONLY CLAIM. A no-checkout
        # `git fetch . <b>:<p>` cannot express a merge commit at all, so the flag was
        # silently dropped and the run fast-forwarded and reported success — a
        # different history than the one that was asked for, with nothing saying so.
        # It matters twice over, because `orchestrator.md` makes `--no-ff` the
        # documented remedy for exit 3, and in this topology that remedy could never
        # succeed: the caller loops on 3 forever.
        #
        # THE REFUSAL IS RIGHT AND ITS REMEDY WAS BLOCKED ONE STEP LATER, by
        # something the remedy did not mention. The parent is checked out in no
        # worktree precisely because every worktree holds an audit branch, so the
        # reader does what this text says and adds one -- and `core.hooksPath` is
        # repository config, shared by every linked worktree, while what it points
        # at is generated by an install and gitignored. Reported from a repository
        # whose hook path was husky's: the bootstrap file was absent in the tree
        # `git worktree add` had just made, the hook aborted the merge commit, and
        # `--no-verify` was what finished it. This repository has no such hook, so
        # no gate here can reach that -- which is why the answer is in the text a
        # reader meets rather than in a check nothing could run.
        #
        # THE ROUTE STAYS AND THE PATH IS NAMED INSTEAD, because the alternatives
        # are both worse than a longer sentence. A checkout of the parent is the only
        # way to make a merge commit without moving somebody's HEAD, which is this
        # command's central promise; making one by plumbing instead would skip those
        # same hooks BY CONSTRUCTION, which is the quiet version of the thing this
        # branch refuses to do. So the operator is told where the hooks will stop
        # them and why skipping them there forfeits nothing -- a merge commit carries
        # no source of its own, and the content it lands was graded by the phase's
        # task commits and its test gate before sign-off ever got here. This command
        # still passes `--no-verify` nowhere itself (`h3`): the choice is the
        # operator's, in their own shell, on one commit.
        merge = dict(merge, mode="refuse", argv=[], refusal=_wt._refusal(
            "--no-ff was asked for, and %r is checked out in no worktree - the "
            "merge would have to be a fetch, which cannot make a merge commit"
            % (parent,),
            "`git worktree add <dir> %s` and run this again, or drop --no-ff and "
            "accept the fast-forward. EXPECT THE COMMIT HOOKS TO STOP THAT MERGE: "
            "a worktree git has just added holds none of this repository's "
            "installed dependencies, so a hook that bootstraps from one cannot "
            "find its own bootstrap file and aborts the merge commit. Finish it by "
            "hand with `git -C <dir> merge --no-ff --no-verify %s`, then run this "
            "once more so the containment is verified and the phase is stamped. "
            "--no-verify is honest THERE and nowhere else here: a merge commit "
            "introduces no source of its own, and what it lands was already graded "
            "by the phase's task commits and its test gate. This refuses rather "
            "than quietly making the other history" % (parent, branch)))
    # THE CLEANUP INPUTS TRAVEL, AND THE CLEANUP ITSELF IS COMPUTED TWICE. Both
    # halves of `cleanup_plan` are gated on containment, and containment is exactly
    # the fact the merge is about to change -- so a cleanup decided here, before the
    # merge, refuses everything on the grounds that the merge has not happened yet.
    # The copy below is the PREVIEW (`--dry-run` prints it, and it is honest about
    # the state the repository is in right now); `close()` recomputes it against the
    # VERIFIED answer once the branch has actually landed. Every other precondition
    # -- dirty, locked, standing-in, main -- is knowable up front and is decided
    # once, which is the part of "decide, then write" that still holds.
    inputs = {"trees": observation["trees"],
              "treeDirty": observation["phaseDirty"]["dirty"],
              "dirtyLines": observation["phaseDirty"]["lines"],
              "cwdTree": observation.get("standingIn"),
              "owned": observation.get("owned"),
              "settled": observation.get("settled"),
              "phaseTree": observation.get("phaseTree"),
              "branchSha": (observation.get("branchExists") or {}).get("sha"),
              "wantWorktree": want_worktree, "wantBranch": want_branch}
    cleanup = cleanup_for(inputs, branch, parent, contained)
    return {"merge": merge, "cleanup": cleanup, "cleanupInputs": inputs,
            "auto": policy["auto"],
            "wantWorktree": want_worktree, "wantBranch": want_branch}


def cleanup_for(inputs, branch, parent, contained, settled=None):
    """`cleanup_plan` over the travelling inputs. One call site for both the preview
    and the real thing, so the two cannot drift into different opinions about what
    a dirty worktree means.

    `settled` overrides the observation's copy, because it is the ONE precondition
    this command changes as it runs: `mergedAt` is null when the run starts and is
    written by this run, so the preview's answer is honest about the repository as
    found and stale by the time the cleanup happens.
    """
    return _wt.cleanup_plan(
        inputs["trees"], branch, parent, contained,
        inputs["treeDirty"], inputs["dirtyLines"],
        cwd_tree=inputs["cwdTree"],
        want_worktree=inputs["wantWorktree"],
        want_branch=inputs["wantBranch"],
        owned=inputs.get("owned"),
        tree=inputs.get("phaseTree"),
        # Where the branch points, so the deletion is guarded on that rather than
        # re-asked of `git branch -d`, which grades from HEAD. On the
        # no-checkout path the parent is by construction checked out nowhere, so
        # HEAD is never the parent and `-d` refuses a branch that landed.
        branch_sha=inputs.get("branchSha"),
        settled=settled if settled is not None else inputs.get("settled"))


# --- the writer ------------------------------------------------------------------

def _step(argv, code, out, err):
    return {"argv": list(argv), "code": code, "stdout": out, "stderr": err}


def close(git_root, the_plan, branch, parent, run=None, dry_run=False,
          settled_now=None, stamp=None):
    """(exitCode, answer) -- the only function here that writes.

    Returns the pair rather than just a verdict for `commit_state`'s reason: a
    function that only exits cannot be exercised without a terminal around it, and
    every branch below has a case.

    `stamp` IS CALLED BEFORE THE CLEANUP, and the order is the point. It used
    to run in `main()` after this function returned, so a cleanup that failed - and
    `git branch -d` failing was routine, see the guarded deletion in `_worktrees` -
    took the exit code to E_FAIL and the record of a merge that HAD LANDED was never
    written. The phase was then unsettled for ever with its worktree already gone.
    A deletion is a consequence of the merge; the record of the merge must not
    depend on the consequence succeeding. It returns `{"stamped"…}` fields that are
    merged into the answer, and a stamp that FAILS stops the cleanup, because a
    removal nothing recorded is the state this whole module exists to prevent.
    """
    fn = _wt._runner(run)
    merge, cleanup = the_plan["merge"], the_plan["cleanup"]
    answer = {"branch": branch, "parent": parent, "mode": merge["mode"],
              "steps": [], "blocked": list(cleanup["blocked"]),
              "refusal": merge["refusal"], "dryRun": bool(dry_run),
              "merged": False, "pending": False, "cleanupDone": [],
              # Set only once the parent DEMONSTRABLY contains the branch, which is
              # the fact `mergedAt` records. False on every path that returns before
              # that verification, so an absent key can never be read as permission.
              "stampable": False}

    # A REFUSAL OUTRANKS THE SWITCH, and the order used to be the other way round.
    # `auto: false` says "a human will merge this"; a parent branch that
    # does not resolve, or a parent worktree holding uncommitted work, is not
    # something a human can merge either - and `orchestrator.md` reads exit 0 plus
    # `pending` as "signed off and deliberately unlanded". A typo'd `parentBranch`
    # travelled up the chain as a plan.
    if merge["mode"] == "refuse":
        return E_FAIL, answer

    if not the_plan["auto"] and merge["mode"] not in ("already-contained",):
        # THE HUMAN-IN-THE-LOOP EXIT, and it is a SUCCESS. `meta.merge.auto: false`
        # does not make sign-off fail; it makes it stop and hand over the command it
        # would have run. A team landing work through a pull request has a phase that
        # is reviewed, gated, committed and deliberately unmerged, and the plugin had
        # no way to say that.
        answer["pending"] = True
        answer["command"] = ("git " + " ".join(merge["argv"])) if merge["argv"] \
            else "(nothing to run: %s)" % (merge["mode"],)
        return E_OK, answer

    if dry_run:
        # THE PREVIEW HAS TO PREVIEW THE CLEANUP, and it did not. The plan
        # this returns was built with `settled` read off DISK, where `mergedAt` is
        # null by construction before sign-off — so `cleanup_plan` blocked both
        # halves and the preview showed a merge and nothing else, while the same
        # command without `--dry-run` removed the worktree and deleted the branch.
        # `commands/phase.md` promises the opposite: "the preview owes it too —
        # whether the worktree and the branch go afterwards".
        #
        # Recomputed here against what the merge is ABOUT to make true: contained,
        # and settled as this run would settle it. That is a conditional preview and
        # it says so, which is honest — the alternative is a preview of the state
        # the repository is leaving rather than the one it is entering.
        preview = cleanup
        if the_plan.get("cleanupInputs"):
            preview = cleanup_for(the_plan["cleanupInputs"], branch, parent,
                                  _wt.CONTAINED, settled=settled_now)
        answer["plannedSteps"] = ([merge["argv"]] if merge["argv"] else []) \
            + [s["argv"] for s in preview["steps"]]
        answer["blocked"] = list(preview["blocked"])
        answer["followUp"] = preview.get("followUp")
        answer["previewAssumes"] = (
            "the merge lands - the cleanup below is what follows it, not what "
            "this repository would allow right now")
        return E_OK, answer

    if merge["mode"] != "already-contained":
        code, out, err = fn(git_root if merge["mode"] == "no-checkout" else None,
                            merge["argv"])
        answer["steps"].append(_step(merge["argv"], code, out, err))
        if code is None:
            return E_NO_BASIS, answer
        if code != 0:
            # NOT-A-FAST-FORWARD IS ITS OWN EXIT, and it is read off the ancestry
            # rather than off the message: `git fetch` says `(non-fast-forward)` for
            # a divergence AND for a state `merge --ff-only` calls `Already up to
            # date.`, so the text cannot be the discriminator. Everything else git
            # refuses is a plain failure.
            after = _wt.merged_into(git_root, branch, parent, run=run)
            if after["answer"] == _wt.CONTAINED:
                answer["merged"] = True          # it landed after all; fall through
            else:
                return E_NOT_FF, answer
        else:
            answer["merged"] = True

    # READ THE RESULT BACK, and ask a DIFFERENT question than the one the write
    # answered. A merge that reported success and a parent that contains the branch
    # are two facts, and only the second is the one the plan will record.
    verified = _wt.merged_into(git_root, branch, parent, run=run)
    answer["verified"] = verified
    if verified["answer"] != _wt.CONTAINED:
        return (E_NO_BASIS if verified["answer"] == _wt.UNKNOWN else E_FAIL), answer

    # THE FACT `mergedAt` RECORDS IS THIS ONE, not "this run performed a merge".
    # `merged` is true only on the paths that ran a git write, so an
    # ALREADY-CONTAINED phase - the idempotent re-run this command advertises, and
    # the re-run `orchestrator.md` tells a human to make after merging by hand - had
    # its worktree removed and its branch deleted while `mergedAt` stayed null. The
    # phase is then unsettled for ever, so no later sweep can reap anything, and the
    # report reads it as unmerged. The cleanup half already gates on `verified`; this
    # makes the recording half read the same answer.
    answer["stampable"] = True
    if stamp is not None and not dry_run:
        written = stamp() or {}
        answer.update(written)
        if not written.get("stamped"):
            # The merge landed and nothing recorded it. Removing the worktree now
            # would leave a phase that can never be shown finished, holding no
            # working copy — so the cleanup does not run, and the operator is left
            # with both halves intact and a reason.
            answer["blocked"] = list(answer["blocked"]) + [{
                "why": "the merge landed but `phase.mergedAt` could not be written"
                       "%s" % (": %s" % (written.get("stampWhy"),)
                               if written.get("stampWhy") else "",),
                "remedy": "fix the manifest write and run this again - the cleanup "
                          "is held back on purpose, because a worktree removed "
                          "against an unrecorded merge cannot be reasoned about "
                          "afterwards"}]
            return E_FAIL, answer

    # Recomputed against the VERIFIED answer, not the one observed before the merge.
    # See `plan()`: the containment gate on both cleanup halves is exactly the fact
    # the merge just changed, and a plan made before it refuses everything for a
    # reason that is no longer true.
    # ...and `settled` is recomputed for the same reason, one field over: `mergedAt`
    # is written by this command AFTER it returns, so the observation's copy is null
    # while the cleanup is being decided. `settled_now` carries what this run has
    # just VERIFIED in place of that one mark, and leaves the other two - sign-off
    # done, every task terminal - to answer for themselves.
    if the_plan.get("cleanupInputs"):
        cleanup = cleanup_for(the_plan["cleanupInputs"], branch, parent,
                              verified["answer"], settled=settled_now)
        answer["blocked"] = list(cleanup["blocked"])
    # The operator's half of a cleanup this command will not do: freeing a branch
    # the main worktree stands on takes a switch, and no HEAD is moved here.
    answer["followUp"] = cleanup.get("followUp")

    for step in cleanup["steps"]:
        code, out, err = fn(git_root, step["argv"])
        answer["steps"].append(_step(step["argv"], code, out, err))
        if code is None:
            return E_NO_BASIS, answer
        if code != 0:
            # STOP AT THE FIRST REFUSAL. The steps are ordered because git enforces
            # the order -- a branch cannot be deleted while its worktree stands -- so
            # carrying on after a failed removal would attempt exactly the thing that
            # cannot work and report a second error for the first one's reason.
            return E_FAIL, answer
        answer["cleanupDone"].append(step["action"])

    if answer["cleanupDone"]:
        # Only after a removal: `prune` clears records whose directory is gone, and
        # running it unconditionally would make a no-op run look like it did work.
        fn(git_root, ["worktree", "prune"])
    return E_OK, answer


# --- writing the moment into the plan --------------------------------------------

def _phase_file(manifest_path, phase_id):
    """Where this phase's body lives: its shard, or the manifest itself.

    Read off the INDEX STUB rather than composed from the id, for `audit-task`'s
    reason: a manifest whose shards were named under an older convention still
    resolves, and composing the name would write a second file beside the real one.
    """
    try:
        raw = _mio.read_json(manifest_path)
    except Exception:
        return None
    if not isinstance(raw, dict) or not _mio.is_sharded(raw):
        return manifest_path
    for stub in (raw.get("phases") or []):
        if isinstance(stub, dict) and str(stub.get("id")) == str(phase_id):
            rel = stub.get("shard")
            if rel:
                return os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                                    rel)
    return None


def _recorded_phase(manifest_path, phase_id):
    """The phase as the plan at `manifest_path` records it now, or {} when the plan
    cannot be read or does not hold it."""
    try:
        plan_now = _mio.load_manifest(manifest_path)
    except Exception:
        return {}
    for ph in ((plan_now or {}).get("phases") or []):
        if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id):
            return ph
    return {}


def recorded_merge(manifest_path, phase_id):
    """The `mergedAt` the plan at `manifest_path` already records for the phase, or
    "" - read before a stamp so a re-run neither moves it nor journals it twice."""
    return _recorded_phase(manifest_path, phase_id).get(MERGED_FIELD) or ""


def phase_as_landed(git_root, manifest_path, branch, phase_id):
    """(phase, basis) - the phase as the merge brings it in: the branch tip's copy.

    Sign-off is committed ON the phase branch, so the copy of the plan a parent's
    tree holds before its merge still says the phase has not signed off. A
    landing judged by that copy refused the cleanup of a phase that had signed off,
    and the second run it forced moved `mergedAt`. Once the branch is gone - the
    re-run after a cleanup - the tree's own copy is the landed one, and says so.
    """
    rel = os.path.relpath(os.path.abspath(manifest_path), git_root)
    landed = _mio.load_manifest_at(git_root, "refs/heads/" + branch, rel.replace(os.sep, "/"))
    for ph in ((landed or {}).get("phases") or []):
        if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id):
            return ph, "the phase as %s holds it" % (branch,)
    return None, "the plan on disk (%s is not there to read)" % (branch,)


def _store_derived(phase):
    """Set `phase.status` to what the derivation answers, where it differs."""
    derived = _mio.effective_phase_status(phase)
    if derived != phase.get("status"):
        phase["status"] = derived


def _stale_stub(manifest_path, phase_id):
    """{key: shard value} for the mirrored keys this phase's stub no longer agrees
    with its shard about, or None when they agree (or the layout has no stub)."""
    moved = dict((key, now) for pid, key, _was, now in _mio.stale_stubs(manifest_path)
                 if str(pid) == str(phase_id))
    return moved or None


def mirror_stub(manifest_path, phase_id, project):
    """(index path written, or "", why) -- re-mirror a phase's index stub from its
    shard, under the index lock.

    The stub is where the index alone answers a phase's status, and `stamp_merged`
    writes only the shard, so a stamp that stored `done` leaves the stub behind until
    this runs. A stub that already agrees is not rewritten: the index is written on a
    phase's own transitions and nothing else. A lock this cannot take is a sentence,
    not a failure - the merge happened and the shard records it, and `audit-task.py
    settle` re-mirrors the stub later.
    """
    if not _stale_stub(manifest_path, phase_id):
        return "", ""
    lines = []
    # EVERY STEP UNDER A `try`, the lock's own included: this runs inside `close()`
    # after the merge has landed, so a raise from reading the config or asking for
    # the lock would report a merge that happened as one that failed.
    try:
        lock = _panel_write.acquire_index_lock(
            project, _panel_write.read_config(project), manifest_path, False,
            lines.append, "[close-phase]", "close-phase stub mirror")
    except Exception as exc:
        return "", _unmirrored("the index lock could not be asked for: %s" % (exc,))
    if isinstance(lock, int):
        return "", _unmirrored("the index lock was not taken (%s)"
                               % ("; ".join(lines) or "exit %d" % (lock,)))
    try:
        # RE-READ UNDER THE LOCK: what was stale a moment ago is decided again once
        # the lock is held, so a writer that got there first is not overwritten.
        moved = _stale_stub(manifest_path, phase_id)
        if not moved:
            return "", ""
        raw = _mio.read_json(manifest_path)
        for stub in (raw.get("phases") or []):
            if isinstance(stub, dict) and str(stub.get("id")) == str(phase_id):
                stub.update(moved)
        new = _revalidated_write(manifest_path, manifest_path, raw)
        if new:
            return "", _unmirrored("the re-mirrored index would not validate (%s), "
                                   "so its prior bytes were restored"
                                   % ("; ".join(new[:3]),))
        return manifest_path, ""
    except Exception as exc:
        return "", _unmirrored("the index stub could not be written: %s" % (exc,))
    finally:
        _panel_write.release_index_lock(lock, out=lines.append)


def _unmirrored(why):
    """The sentence a stub left behind owes: why, and the command that fixes it."""
    return ("%s, so the stub still differs from its shard; `audit-task.py settle` "
            "re-mirrors it" % (why,))


def _findings_of(manifest_path):
    """The validator's findings over the plan at `manifest_path`, as a set - one
    naming the read itself when the plan cannot be assembled."""
    try:
        return set(_rules.validate(_mio.load_manifest(manifest_path))[0])
    except Exception as exc:
        return set(["the plan could not be assembled: %s" % (exc,)])


def _revalidated_write(manifest_path, path, obj):
    """Write `obj` to `path`, then revalidate the plan at `manifest_path`: a finding
    the write introduced restores `path`'s prior bytes. Returns those new findings,
    sorted - [] when the write stands. A finding the plan already carried is not
    this write's to refuse on, which is why the two sets are compared."""
    with open(path, "rb") as fh:
        before = fh.read()
    pre = _findings_of(manifest_path)
    _mio.atomic_write_json(path, obj, indent=2)
    new = sorted(_findings_of(manifest_path) - pre)
    if new:
        with open(path, "wb") as fh:
            fh.write(before)
    return new


def _utc_now():
    """This moment in the plan's one UTC spelling. `datetime.utcnow()` is
    deprecated from 3.12 and warns onto stderr of every run; the aware spelling
    works unchanged on the 3.8 floor, which `datetime.UTC` (3.11+) would not."""
    return (datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def merge_commit(git_root, branch, parent, run=None):
    """{"sha", "basis"} - the oldest commit on `parent`'s first-parent chain that
    contains `branch`'s tip: the commit on that chain that brought the tip in -
    the tip itself for a fast-forward, the merge commit for a direct merge, the
    parent's merge of an intermediate branch for a nested one. `sha` is "" with
    the reason when there is none.

    ONE MEANING FOR `mergedHead` WHEREVER THE BRANCH RESOLVES. Read at the moment
    of a merge this command just made, the parent's head IS that commit; read
    later - a hand merge closed afterwards, or a re-run over a merge recorded
    without a head - the parent may have moved on, and its head is then a
    different, later commit. So the commit is recovered rather than read:

    - the tip itself when the branch was fast-forwarded in, which is when the tip
      sits on the parent's first-parent chain;
    - otherwise the commit on that chain that brought the tip in - the merge
      commit, or, for a tip that arrived through an intermediate branch, the
      parent's own merge of that branch.

    TWO WALKS, BECAUSE ONE IS NOT ENOUGH. `rev-list --first-parent <tip>..<parent>`
    is the parent's own chain back to the tip's history, and `rev-list
    --ancestry-path <tip>..<parent>` is every commit that descends from the tip,
    through any parent. The answer is the oldest commit in both. Limiting the
    ancestry path to first parents in one walk loses a tip merged into an
    intermediate branch first: that inner merge is not on the parent's chain, so
    the combined walk comes back empty for a tip the parent does hold. The
    answer's own first parent being the tip is what marks a fast-forward.

    The parent's head always descends from a tip it holds and is on its own
    chain, so an empty intersection means the parent does not hold the tip, and
    nothing is guessed.
    """
    fn = _wt._runner(run)
    tip = _wt.ref_exists(git_root, branch, run=run)
    head = _wt.ref_exists(git_root, parent, run=run)
    if not tip["sha"]:
        return {"sha": "", "basis": "%r %s" % (branch, tip["basis"])}
    if not head["sha"]:
        return {"sha": "", "basis": "%r %s" % (parent, head["basis"])}
    if tip["sha"] == head["sha"]:
        return {"sha": tip["sha"],
                "basis": "%s's tip is %s's head: a fast-forward the parent has "
                         "not moved past" % (branch, parent)}
    span = "%s..%s" % (tip["sha"], head["sha"])
    walks = []
    for walk in (["rev-list", "--first-parent", span],
                 ["rev-list", "--ancestry-path", span]):
        code, out, _err = fn(git_root, walk)
        if code != 0:
            return {"sha": "", "basis": "git %s could not be asked"
                                        % (" ".join(walk),)}
        walks.append((out or "").split())
    descends = set(walks[1])
    chain = [c for c in walks[0] if c in descends]
    if not chain:
        return {"sha": "", "basis": "no commit on %s's first-parent chain contains "
                                    "%s's tip, so %s does not hold it"
                                    % (parent, branch, parent)}
    oldest = chain[-1]
    code, out, _err = fn(git_root, ["rev-parse", "--verify", "--quiet",
                                    oldest + "^1"])
    if code != 0:
        return {"sha": "", "basis": "the first parent of %s could not be read"
                                    % (oldest,)}
    if (out or "").strip() == tip["sha"]:
        return {"sha": tip["sha"],
                "basis": "%s's tip is on %s's first-parent chain: a fast-forward"
                         % (branch, parent)}
    return {"sha": oldest,
            "basis": "%s is the oldest commit on %s's first-parent chain that "
                     "contains %s's tip" % (oldest, parent, branch)}


def contained_task_commits(git_root, phase, parent, run=None):
    """{"sha", "basis"} - the parent's head, when EVERY task commit the phase
    records is an ancestor of it; `sha` is "" with the reason otherwise.

    THE EVIDENCE A BRANCH-GONE BACKFILL STANDS ON. With the branch deleted there is
    no tip to recover the merge commit from, and the recorded `mergedAt` alone says
    only that SOME parent once held SOME branch: the parent asked about now can
    come from `--parent` or from a `meta.developmentBranch` changed since, and a
    parent can be rewound past its merge. A parent that does not hold every
    recorded task commit - a rewound one, a squash merge, a wrong one lacking the
    work - fails; a wrong parent that happens to hold all of them passes, and the
    head written is then still a commit holding the phase's recorded work. The plan's own record of the work - the
    commit each task landed as - is what can be asked of git instead, and each one
    is asked against the one head that would be written, so the evidence and the
    value are about the same commit.

    WHAT IT CAN AND CANNOT PROVE. Every recorded task commit contained means the
    parent's head holds the phase's recorded work. It does not prove the head
    holds work no task recorded. A phase recording no task commit has no evidence
    at all, and a squash merge leaves the task commits outside the parent's
    history - both are refused, which leaves the phase unknown: the safe answer.
    """
    commits = _task_commits(phase)
    if not commits:
        return {"sha": "", "basis": "phase %s records no task commit, so nothing in "
                                    "the plan shows %s holds its work"
                                    % (phase.get("id"), parent)}
    head = _wt.ref_exists(git_root, parent, run=run)
    if not head["sha"]:
        return {"sha": "", "basis": "%r %s" % (parent, head["basis"])}
    missing = _task_commit_missing(git_root, commits, head["sha"],
                                   "%s's head" % (parent,), run=run)
    if missing:
        return {"sha": "", "basis": missing}
    return {"sha": head["sha"],
            "basis": "every recorded task commit (%d) is in %s's head"
                     % (len(commits), parent)}


def _task_commits(phase):
    """The distinct task commits `phase` records, sorted - [] when it records none."""
    return sorted(set(str(t.get("commit")) for t in ((phase or {}).get("tasks") or [])
                      if isinstance(t, dict) and t.get("commit")))


def _task_commit_missing(git_root, commits, sha, where, run=None):
    """The sentence naming the first of `commits` that `sha` does not contain, or ""
    when it contains every one. Anything but CONTAINED - git saying no, or git
    unable to say - is a miss, because each caller writes a head on "" alone."""
    for commit in commits:
        answer = _wt.merged_into(git_root, commit, sha, run=run)
        if answer["answer"] != _wt.CONTAINED:
            return ("task commit %s is %s in %s %s (%s)"
                    % (commit, answer["answer"], where, sha, answer["basis"]))
    return ""


def recovered_head(git_root, branch, parent, phase, run=None):
    """{"sha", "basis"} - `merge_commit`, held to the plan's own record of the work.

    THE BRANCH REF IS READ AS IT STANDS NOW, and a ref can be moved: `git branch
    -f` onto an older commit the parent's chain holds turns that commit into what
    looks like a fast-forward, and recovering from it would record a head that
    predates the phase's work - a run containing it but not that work would read
    whole. So when the phase records task commits, the recovered commit must
    contain every one of them, or nothing is written and the reason says which.

    A PHASE RECORDING NO TASK COMMIT has nothing to hold the ref to, and the
    recovered commit stands on the ref alone - the same trust the merge itself
    placed in it, which is why a normal close of such a phase is unchanged.
    """
    head = merge_commit(git_root, branch, parent, run=run)
    commits = _task_commits(phase)
    if not head["sha"] or not commits:
        return head
    missing = _task_commit_missing(git_root, commits, head["sha"],
                                   "the commit recovered from %s," % (branch,),
                                   run=run)
    if missing:
        return {"sha": "", "basis": "%s - so %s does not hold this phase's recorded "
                                    "work and no head is written" % (missing, branch)}
    return {"sha": head["sha"],
            "basis": "%s; every recorded task commit (%d) is in it"
                     % (head["basis"], len(commits))}


def _phases_in(body, phase_id):
    """The phase dicts in a read plan file that are `phase_id`: the body itself when
    the file is a shard, else the matching entries of its `phases`."""
    if not isinstance(body, dict):
        return []
    if str(body.get("id")) == str(phase_id):
        return [body]                                   # a shard IS the phase
    return [ph for ph in (body.get("phases") or [])
            if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id)]


def stamp_merged(manifest_path, phase_id, when=None, merged_head=_HEAD_NOT_ASKED):
    """Write `phase.mergedAt` (and, in the SAME write, `phase.mergedHead`). Returns
    the path written, or "" with a reason.

    THE FIELD IS WRITTEN ONLY AFTER THE PARENT DEMONSTRABLY CONTAINS THE BRANCH, and
    never on the `auto: false` path -- a plan that says a phase merged at a moment it
    did not is worse than a plan that says nothing, because every later reader treats
    it as landed.

    `merged_head` IS THE COMMIT `recovered_head` FOUND, asked by the caller (never
    composed here): the commit on the parent's first-parent chain that brought the
    branch's tip in, held to the recorded task commits - `None` when none could be
    recovered, and the not-asked
    sentinel when the caller never mentions it at all, which leaves the key out of
    the write entirely rather than pinning it to null. There is no second write:
    both fields land in the one `_revalidated_write` call below, because a stamp
    split across two writes is exactly the bug this exists to close.
    """
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return "", ("no file holds phase %s - the index names no shard for it"
                    % (phase_id,))
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return "", "%s could not be read: %s" % (path, exc)
    stamp = when or _utc_now()
    # A RECORDED MERGE IS KEPT: the field names the moment the parent came to hold
    # the branch, and a re-run finding it already there records nothing new.
    found = _phases_in(body, phase_id)
    for ph in found:
        if ph.get(MERGED_FIELD):
            return path, ph[MERGED_FIELD]
    if not found:
        return "", "phase %s is not in %s" % (phase_id, path)
    # THE MERGE IS AN INPUT OF THE DERIVED STATUS, so the status it now derives is
    # stored in the same write: `done` for a signed-off phase with every task
    # terminal, and nothing new for one whose sign-off is not recorded.
    for ph in found:
        ph[MERGED_FIELD] = stamp
        if merged_head is not _HEAD_NOT_ASKED:
            ph[MERGED_HEAD_FIELD] = merged_head
        _store_derived(ph)
    try:
        new = _revalidated_write(manifest_path, path, body)
    except Exception as exc:
        return "", "%s could not be written: %s" % (path, exc)
    if new:
        return "", ("%s would leave the plan invalid (%s), so its prior bytes were "
                    "restored" % (path, "; ".join(new[:3])))
    return path, stamp


def record_merged_head(manifest_path, phase_id, merged_head, merged_head_at=None):
    """(path, head written or "", why) - add `phase.mergedHead` (and, for a head
    recorded after the fact, `phase.mergedHeadAt`) to a phase whose merge is
    ALREADY recorded without one, and touch nothing else.

    The counterpart of `stamp_merged` for a plan written before the field existed,
    through the same `_revalidated_write`: one read, one write, restored on a new
    finding. It refuses rather than writes when the phase records no merge (that
    is `stamp_merged`'s job, and a head with no merge is a claim with no event) and
    when a head is already recorded - A RECORDED HEAD IS NEVER REPLACED: it is the
    one every reader has been measuring against, and replacing it would move a
    verdict nothing about the merge changed. `mergedAt` is not
    written at all, so it cannot move. `merged_head_at`, when given, is written in
    the same write as `mergedHeadAt`: the head is then not the merge's own commit.
    """
    if not merged_head:
        return "", "", "no head was supplied"
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return "", "", ("no file holds phase %s - the index names no shard for it"
                        % (phase_id,))
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return "", "", "%s could not be read: %s" % (path, exc)
    found = _phases_in(body, phase_id)
    if not found:
        return "", "", "phase %s is not in %s" % (phase_id, path)
    if not all(ph.get(MERGED_FIELD) for ph in found):
        return "", "", "phase %s records no merge in %s" % (phase_id, path)
    if any(ph.get(MERGED_HEAD_FIELD) for ph in found):
        return path, "", "a head is already recorded in %s" % (path,)
    for ph in found:
        ph[MERGED_HEAD_FIELD] = merged_head
        if merged_head_at:
            ph[MERGED_HEAD_AT_FIELD] = merged_head_at
    try:
        new = _revalidated_write(manifest_path, path, body)
    except Exception as exc:
        return "", "", "%s could not be written: %s" % (path, exc)
    if new:
        return "", "", ("%s would leave the plan invalid (%s), so its prior bytes "
                        "were restored" % (path, "; ".join(new[:3])))
    return path, merged_head, ""


def backfill_merged_head(manifest_path, phase_id, parent, project, ask_head,
                         after_the_fact, dry_run=False):
    """Answer fields for a re-run over a merge recorded WITHOUT `mergedHead`: {} when
    there is nothing to backfill (no merge recorded, or a head already is), else
    the head written - once - or the reason it was not.

    `ask_head` IS CALLED ONLY WHEN A HEAD IS OWED, so a re-run over a phase that
    already has one asks git nothing. It returns `{"sha", "basis"}`:

    - WITH THE BRANCH STILL THERE it is `recovered_head`, and the head written is
      the oldest commit on the parent's first-parent chain that contains the tip:
      the commit on that chain that brought the tip in - the tip itself for a
      fast-forward, the merge commit for a direct merge, the parent's merge of an
      intermediate branch for a nested one - held to the recorded task commits,
      the same value a stamp at the merge would have written, so `mergedHead` keeps one meaning and no `mergedHeadAt` is written.
    - WITH THE BRANCH GONE (`after_the_fact`) the merge commit cannot be recovered,
      and it is `contained_task_commits`: the parent's head, and only when every
      task commit the plan records is in it. That head sits at or after the merge,
      and every reader asks whether `mergedHead` is an ancestor of a run's head, so
      it is STRICTER than the merge's own commit: a green run that contains the
      merge but predates this head reads provisional, never whole by accident.
      `mergedHeadAt` records the moment, which is what "a run after this" is then
      measured against. A parent that does not hold every recorded task commit (a
      rewound one, a squash merge, a wrong one lacking the work) fails the
      evidence and is refused, so the phase stays unknown.

    The basis goes into the journal row's `reason`, and the summary says which of
    the two heads this is.
    """
    recorded = _recorded_phase(manifest_path, phase_id)
    if not recorded.get(MERGED_FIELD) or recorded.get(MERGED_HEAD_FIELD):
        return {}
    head = ask_head(recorded)
    if not head["sha"]:
        return {"mergedHeadWhy": head["basis"]}
    if dry_run:
        return {"mergedHeadWould": head["sha"]}
    at = _utc_now() if after_the_fact else None
    path, written, why = record_merged_head(manifest_path, phase_id, head["sha"],
                                            merged_head_at=at)
    if not written:
        return {"mergedHeadWhy": why}
    # ONLY ALLOW-LISTED DETAIL KEYS: `_journal_io` drops any other key in silence,
    # so the head travels as `to` and its basis as `reason`, and what has no key of
    # its own - the parent, which head this is, `mergedHeadAt` - is in the summary.
    what = ("recorded at %s after the fact: the parent's head then, not the "
            "merge's own commit, so stricter than it" % (at,) if at
            else "recovered from the parent's first-parent chain")
    _journal_io.append_from_cli(project, {
        "action": ACTION_MERGED_HEAD_RECORDED,
        "actor": {"via": "close-phase"},
        "target": str(phase_id),
        "summary": "%s head %s for a merge at %s - %s"
                   % (parent, written, recorded[MERGED_FIELD], what),
        "details": {"phaseId": str(phase_id), "field": MERGED_HEAD_FIELD,
                    "from": None, "to": written,
                    "mergedAt": recorded[MERGED_FIELD],
                    "reason": ("recovered: " if not at else "") + head["basis"]},
    })
    return {"mergedHead": written, "mergedHeadBackfilled": path,
            "mergedHeadAt": at}


def surviving_copy(manifest_path, project, git_root, observation, the_plan,
                   phase_id=None):
    """(manifestPath, projectDir, why) -- the copy of the plan that will still exist
    when this run is over.

    THE BUG THIS EXISTS FOR, MEASURED. A phase that ran in a linked worktree merges
    into the parent's worktree and then stamps `mergedAt`. Stamped through the path
    the caller passed, that write lands in the PHASE's worktree -- the one the very
    next step is about to delete -- so the moment the phase landed is recorded in a
    directory that ceases to exist, and the surviving copy still reads
    `mergedAt: null`. The old prose never met this because it reached the parent with
    `git switch`, which put the edit in the only tree there was.

    So the stamp follows the MERGE: when the branch landed in another worktree, the
    plan is written there, at the same repository-relative path. The journal row goes
    with it for the same reason.

    A path outside the git root is DEGRADED PAST, not failed on -- the same sentence
    `commit-audit-state` writes for a journal directory it cannot commit: say which
    copy was written and carry on, because a merge that happened must not be reported
    as not having happened.
    """
    observation = observation or {}
    # THE TREE THE PASSED PATH SITS IN, read off the worktree list rather than
    # assumed to be the git root: run from the main checkout with the WORKTREE's
    # manifest, the git root is main while the path is the worktree's copy - and a
    # stamp written there dirtied the tree the cleanup was about to remove.
    source = _tree_holding(observation.get("trees") or [], manifest_path)
    base = (source or {}).get("path") or git_root
    tree = observation.get("parentTree")
    # BOTH MODES THAT LAND IN A CHECKOUT: the merge made now, and the branch that
    # already landed - a re-run, or a merge a human made by hand - whose stamp
    # belongs in the same surviving copy.
    if (the_plan or {}).get("merge", {}).get("mode") not in (
            "in-parent-worktree", "already-contained") \
            or not tree or not tree.get("path"):
        return manifest_path, project, ""
    if _wt.same_tree(tree.get("path"), base):
        return manifest_path, project, ""
    try:
        # Both sides RESOLVED: git prints a worktree's real path, and a caller's
        # path through a symlinked prefix (`/var` for `/private/var`) would
        # otherwise read as outside the tree it is in.
        rel = os.path.relpath(os.path.realpath(manifest_path), os.path.realpath(base))
    except Exception as exc:
        return manifest_path, project, "%s" % (exc,)
    if rel.startswith(".."):
        # Outside the repository: there is no corresponding copy in the other tree,
        # so the caller's path is the only one there is. Named rather than silently
        # written, because the reader has to know the stamp may be about to vanish.
        return manifest_path, project, ""
    moved = os.path.join(tree.get("path"), rel)
    if not os.path.isfile(moved):
        return manifest_path, project, ""
    # ...AND IT HAS TO CARRY THE PHASE. The two trees hold two checkouts, and the
    # parent's copy is only guaranteed to know this phase once the commit that
    # introduced it has landed there. Redirecting the stamp to a plan that has never
    # heard of P9 used to fail silently — `stampWhy` was set and the run still exited
    # 0, so `mergedAt` was written NOWHERE and the merge was reported as done. That
    # is the same silent-no-write failure coming back through the other door, so the
    # redirect is now conditional
    # on the destination being able to receive it.
    if phase_id is not None and not _phase_present(moved, phase_id):
        return manifest_path, project, (
            "%s does not carry phase %s, so the stamp stays in the copy this run "
            "was pointed at" % (moved, phase_id))
    return moved, tree.get("path"), ""


def no_survivor_refusal(observation, manifest_path, parent):
    """The refusal owed when the landing has no surviving copy to stamp, or None.

    With `parent` checked out in NO worktree the merge is a ref-only fast-forward,
    and a manifest inside the phase's own worktree is the copy the cleanup removes.
    No other checkout is the landing's either - another branch's plan is not this
    one's. So the run stops before the merge: a moved ref with no record of the
    landing is the disagreement this refuses to create."""
    if (observation or {}).get("parentTree") is not None:
        return None
    phase_tree = (observation or {}).get("phaseTree")
    if not phase_tree or phase_tree.get("isMain") \
            or not _wt.within_tree(phase_tree.get("path"), manifest_path):
        return None
    return ("the landing has no surviving copy to stamp - %r is checked out in no "
            "worktree, and %s is the phase worktree's own copy, which the cleanup "
            "removes: check out %s in a worktree, or run close-phase from its "
            "checkout" % (parent, manifest_path, parent))


def _tree_holding(trees, path):
    """The worktree record `path` sits in - the deepest when records nest - or None."""
    holding = [t for t in trees if t.get("path") and not t.get("prunable")
               and _wt.within_tree(t.get("path"), path)]
    holding.sort(key=lambda t: len(os.path.realpath(t.get("path"))))
    return holding[-1] if holding else None


def _phase_present(manifest_path, phase_id):
    """Does this plan know `phase_id`? Read through the same resolver the stamp uses,
    so a shard layout and a single file answer alike."""
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return False
    try:
        body = _mio.read_json(path)
    except Exception:
        return False
    if isinstance(body, dict) and str(body.get("id")) == str(phase_id):
        return True
    return any(isinstance(p, dict) and str(p.get("id")) == str(phase_id)
               for p in ((body or {}).get("phases") or []))


def _parked_after_merge(manifest_path, branch):
    """The proposals parked on `branch`, read from the copy the merge landed in -
    the parent's, where `/audit:propose materialize` is to run. An unreadable copy
    is an empty answer: the merge and its stamp stand whether or not this can be
    listed, and the stamp line already says where the file is."""
    try:
        return _proposals.parked_on_branch(_mio.load_manifest(manifest_path), branch)
    except Exception:
        return []


def record_row(project, phase_id, branch, parent, config=None):
    """Anchor the merge in the trail. FAIL-SOFT, `_journal_io.append`'s contract: a
    merge that HAPPENED must not be reported as not having happened because the trail
    could not be written. `journal-writes.py` cannot see this one -- it is a
    PostToolUse hook over Edit/Write, and this is a script.

    Which is also why it is `append_from_cli`: the hook cannot see the
    write, so the hook's per-session claim cannot name it either, and an append no
    writer claims is what `guard-bash-writes` reports as a shell write into the
    append-only trail."""
    config = _journal_io.load_config(project) if config is None else config
    return _journal_io.append_from_cli(project, {
        "action": ACTION_PHASE_MERGED,
        "actor": {"via": "close-phase"},
        "target": str(phase_id),
        "summary": "%s reached %s" % (branch, parent),
        "details": {"phaseId": str(phase_id), "branch": branch,
                    "parent": parent},
    }, config=config)


# --- rendering -------------------------------------------------------------------

def _render_backfill(answer, out=print):
    """The lines a `backfill_merged_head` answer owes - nothing for an empty one."""
    if answer.get("mergedHeadBackfilled") and answer.get("mergedHeadAt"):
        out("  %s = %s written to %s, with %s = %s (the branch is gone: the "
            "parent's head now, not the merge's own commit, so stricter than it)"
            % (MERGED_HEAD_FIELD, answer["mergedHead"],
               answer["mergedHeadBackfilled"], MERGED_HEAD_AT_FIELD,
               answer["mergedHeadAt"]))
    elif answer.get("mergedHeadBackfilled"):
        out("  %s = %s written to %s (the merge was recorded without one; this is "
            "the commit recovered from the parent's first-parent chain)"
            % (MERGED_HEAD_FIELD, answer["mergedHead"],
               answer["mergedHeadBackfilled"]))
    elif answer.get("mergedHeadWould"):
        out("  would write %s = %s (the merge is recorded without one)"
            % (MERGED_HEAD_FIELD, answer["mergedHeadWould"]))
    elif answer.get("mergedHeadWhy"):
        out("  %s NOT recorded: %s" % (MERGED_HEAD_FIELD, answer["mergedHeadWhy"]))


def render(answer, out=print):
    """One block a human reads top to bottom: what was decided, what ran, what did
    not, and why. Refusals carry their remedy on the next line, because a refusal
    nobody can act on is one they route around."""
    out("[close-phase] %s -> %s (%s)"
        % (answer["branch"], answer["parent"], answer["mode"]))
    if answer.get("pending"):
        out("  NOT MERGED: meta.merge.auto is false, so this stopped before the "
            "merge. Nothing was written.")
        out("  run this when you are ready:  %s" % (answer.get("command"),))
        return
    if answer.get("refusal"):
        out("  REFUSED: %s" % (answer["refusal"]["why"],))
        out("           %s" % (answer["refusal"]["remedy"],))
    if answer.get("dryRun"):
        for argv in answer.get("plannedSteps") or []:
            out("  would run: git %s" % (" ".join(argv),))
        if not answer.get("plannedSteps"):
            out("  would run: nothing - %s" % (answer["mode"],))
        _render_backfill(answer, out=out)
    for step in answer.get("steps") or []:
        tail = (step["stderr"] or step["stdout"] or "").strip().split("\n")[0]
        out("  git %s -> %s%s" % (" ".join(step["argv"]), step["code"],
                                  ("  %s" % tail) if tail else ""))
    for row in answer.get("blocked") or []:
        out("  not done: %s" % (row["why"],))
        out("            %s" % (row["remedy"],))
    if answer.get("stamped"):
        out("  %s = %s %s %s"
            % (MERGED_FIELD, answer["stampedAt"],
               "already recorded in" if answer.get("stampKept") else "written to",
               answer["stamped"]))
        if answer.get("stampedElsewhere"):
            out("    (that is the copy in the worktree the merge landed in - the "
                "one in this tree is about to be removed)")
        if answer.get("mergedHeadBackfilled"):
            _render_backfill(answer, out=out)
        elif answer.get("mergedHead"):
            out("  %s = %s" % (MERGED_HEAD_FIELD, answer["mergedHead"]))
        elif answer.get("mergedHeadWhy"):
            out("  %s NOT recorded: %s" % (MERGED_HEAD_FIELD, answer["mergedHeadWhy"]))
        if answer.get("stubMirrored"):
            out("  index stub re-mirrored from the shard in %s"
                % (answer["stubMirrored"],))
        elif answer.get("stubWhy"):
            out("  index stub NOT re-mirrored: %s" % (answer["stubWhy"],))
    elif answer.get("stampWhy"):
        out("  %s NOT written: %s" % (MERGED_FIELD, answer["stampWhy"]))
    if answer.get("finishFrom"):
        out("  cleanup is not finished. From %s, run:" % (answer["finishFrom"],))
        out("    %s" % (answer["finishCommand"],))
    follow = answer.get("followUp")
    if follow:
        # A PREVIEW HAS RUN NOTHING, so it says what the cleanup will need rather
        # than that a cleanup stopped.
        out(("  after the merge, cleanup will need, from %s:" if answer.get("dryRun")
             else "  cleanup is not finished, and this never moves a HEAD. From %s, "
                  "run:") % (follow["from"],))
        for command in follow["commands"]:
            out("    %s" % (command,))
        if follow.get("note"):
            out("  (that %s)" % (follow["note"],))
    parked = answer.get("parkedOnBranch") or []
    if parked:
        out("  parked on %s, materializable now that it has landed - on %s, run:"
            % (answer["branch"], answer["parent"]))
        for row in parked:
            out("    /audit:propose materialize %s   (reserves %s: %s)"
                % (row["id"], row["reserves"], row["name"]))
        out("  then commit %s before starting them." % (answer["parent"],))


# --- cli -------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="close-phase.py",
        description="Land a signed-off phase on its parent branch.")
    p.add_argument("manifest")
    p.add_argument("phase")
    p.add_argument("--project", default=".")
    p.add_argument("--parent", default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--remove-worktree", dest="remove_worktree",
                   action="store_true", default=None)
    p.add_argument("--keep-worktree", dest="remove_worktree",
                   action="store_false")
    p.add_argument("--delete-branch", dest="delete_branch",
                   action="store_true", default=None)
    p.add_argument("--keep-branch", dest="delete_branch", action="store_false")
    p.add_argument("--no-ff", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--json", dest="as_json", action="store_true")
    return p


def main(argv, out=print):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK

    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n"
                         % (args.manifest, exc))
        return E_USAGE
    # Through the shared resolver, so `2`, `p2` and `P2` are one phase here
    # and everywhere else rather than three answers per script. The `(have: …)`
    # wording this file already printed is what the resolver carries.
    resolved_id, why = _mio.resolve_phase_id(manifest, args.phase)
    if resolved_id is None:
        sys.stderr.write("ERROR: %s in %s\n" % (why, args.manifest))
        return E_USAGE
    args.phase = resolved_id
    phase = None
    for ph in ((manifest or {}).get("phases") or []):
        if isinstance(ph, dict) and str(ph.get("id")) == resolved_id:
            phase = ph

    project = os.path.abspath(args.project)
    meta_root = ((manifest.get("meta") or {}).get("gitRoot") or ".")
    git_root = os.path.abspath(os.path.join(project, meta_root))
    if not shutil.which("git"):
        out("[close-phase] git is not on PATH, so nothing about this phase's "
            "branch can be established. Nothing was written.")
        return E_NO_BASIS

    names = resolve(manifest, phase, args.parent, args.branch,
                    initials=_wt.git_user_name(git_root))
    if names["refusal"]:
        out("[close-phase] REFUSED: %s. Nothing was written." % (names["refusal"],))
        return E_FAIL
    # ALREADY LANDED AND CLEANED UP: the plan records the merge and the branch is
    # gone. Containment cannot be asked of a branch that no longer exists, and the
    # planner then said "merge it into the parent first" about a phase that had
    # merged - so the idempotent re-run this command promises is answered here.
    #
    # ONLY FOR A NAME SOMEBODY RECORDED OR PASSED. A composed name is a prediction:
    # with another identity at the keyboard it names a branch that never existed,
    # while the one that did may still hold unmerged work - so its absence proves
    # nothing, and the answer is that it cannot be said.
    if (phase or {}).get(MERGED_FIELD) and _wt.ref_exists(
            git_root, names["branch"])["exists"] is False:
        if names["branchBasis"].startswith("composed"):
            out("[close-phase] phase %s records a merge at %s, but no branch is "
                "recorded for it here, and %s - %s - is not a branch. Whether the "
                "branch that carried the phase is gone cannot be said from a "
                "composed name: pass --branch <name> to ask about the real one"
                % (args.phase, phase[MERGED_FIELD], names["branch"],
                   names["branchBasis"]))
            return E_NO_BASIS
        # ...EXCEPT a head a plan older than the field never got. Without this the
        # default re-run - the branch deleted by the first one - answered here for
        # ever, and the phase's merged head stayed unknown with nothing to fill it.
        # ASKED BEFORE ANYTHING IS PRINTED, so "nothing left to do" is said only
        # when that is what happened.
        filled = backfill_merged_head(
            args.manifest, args.phase, names["parent"], project,
            lambda recorded: contained_task_commits(git_root, recorded,
                                                    names["parent"]),
            after_the_fact=True, dry_run=args.dry_run)
        out("[close-phase] phase %s landed at %s and %s is gone - %s"
            % (args.phase, phase[MERGED_FIELD], names["branch"],
               "nothing left to merge or clean up" if filled
               else "nothing left to do"))
        _render_backfill(filled, out=out)
        return E_OK
    # ...AND A COMPOSED NAME NOTHING HOLDS IS NOT AN ANCESTRY QUESTION. Asked of git,
    # it came back as "could not be established", which names the wrong gap: the
    # plan recorded no branch, and the one predicted from the template is not in
    # this repository. Phases built on one combined branch are exactly this shape.
    if names["branchBasis"].startswith("composed") and _wt.ref_exists(
            git_root, names["branch"])["exists"] is False:
        out("[close-phase] no branch is recorded for phase %s, so the name asked "
            "about, %s, was %s - and it is not a branch in this repository. Nothing was "
            "written. Pass --branch <name>: the branch that carries this phase's "
            "work" % (args.phase, names["branch"], names["branchBasis"]))
        return E_FAIL
    observation = observe(git_root, names["branch"], names["parent"])
    if observation["why"]:
        out("[close-phase] %s" % (observation["why"],))
        return E_NO_BASIS

    # The observation carries the phase as it stands on disk; the settlement the
    # CLEANUP is judged by is the same question with `mergedAt` supplied by this run.
    observation["settled"] = settlement(phase, merged=False)
    landed, landed_basis = phase_as_landed(git_root, args.manifest, names["branch"],
                                           args.phase)
    the_plan = plan(observation, names["branch"], names["parent"],
                    names["policy"], want_worktree=args.remove_worktree,
                    want_branch=args.delete_branch, no_ff=args.no_ff)
    # ASKED ONLY WHERE A WRITE WOULD FOLLOW. With `meta.merge.auto` false the run
    # hands over the merge command and writes nothing, so there is no stamp to
    # lack a survivor - unless the branch already landed and the stamp is due.
    writes = the_plan["auto"] or the_plan["merge"]["mode"] == "already-contained"
    refusal = (no_survivor_refusal(observation, args.manifest, names["parent"])
               if writes else None)
    if refusal:
        out("[close-phase] REFUSED: %s. Nothing was merged or written." % (refusal,))
        return E_USAGE
    def _stamp():
        """Persist `phase.mergedAt`, and report what happened in answer fields.

        Handed to `close()` so it runs between the verified containment and the
        cleanup: the record of a merge must not be contingent on a deletion that
        happens after it.
        """
        target, project_for_row, why = surviving_copy(
            args.manifest, project, git_root, observation, the_plan,
            phase_id=args.phase)
        if not target:
            return {"stamped": "", "stampWhy": why}
        earlier = recorded_merge(target, args.phase)
        if earlier:
            # A re-run records the merge that happened; it does not move it. A
            # recorded mergedHead is kept too; only a merge recorded WITHOUT one -
            # a plan older than the field - has the recovered commit added, once.
            kept = {"stamped": target, "stampedAt": earlier, "stampKept": True,
                    "stampedElsewhere": (os.path.abspath(target)
                                         != os.path.abspath(args.manifest)),
                    "parkedOnBranch": _parked_after_merge(target, names["branch"])}
            kept.update(backfill_merged_head(
                target, args.phase, names["parent"], project_for_row,
                lambda recorded: recovered_head(git_root, names["branch"],
                                                names["parent"], recorded),
                after_the_fact=False))
            return kept
        # ASKED HERE, AFTER `close()` HAS VERIFIED CONTAINMENT AND BEFORE THE
        # CLEANUP, while the branch still resolves: the oldest commit on the
        # parent's first-parent chain that contains the tip, recovered by
        # `merge_commit` - the merge's own commit unless that chain was rewritten
        # past it. On a
        # merge this run just made that is the parent's head; on a hand merge
        # closed later the parent may have moved on, and its head would then be a
        # later commit than the merge. A commit that cannot be recovered writes no
        # guess: `None` travels through as an explicit null.
        head = recovered_head(git_root, names["branch"], names["parent"],
                              _recorded_phase(target, args.phase))
        merged_head = head["sha"] or None
        merged_head_why = "" if merged_head else head["basis"]
        path, stamp_at = stamp_merged(target, args.phase, merged_head=merged_head)
        if not path:
            return {"stamped": "", "stampWhy": stamp_at}
        record_row(project_for_row, args.phase, names["branch"], names["parent"])
        mirrored, mirror_why = mirror_stub(target, args.phase, project_for_row)
        return {"stamped": path, "stampedAt": stamp_at,
                "mergedHead": merged_head, "mergedHeadWhy": merged_head_why,
                "stubMirrored": mirrored, "stubWhy": mirror_why,
                "stampedElsewhere": (os.path.abspath(target)
                                     != os.path.abspath(args.manifest)),
                "parkedOnBranch": _parked_after_merge(target, names["branch"])}

    code, answer = close(git_root, the_plan, names["branch"], names["parent"],
                         dry_run=args.dry_run,
                         settled_now=settlement(landed or phase, merged=True),
                         stamp=_stamp)
    answer["settledBasis"] = landed_basis
    # A PREVIEW OWES THE BACKFILL TOO. `close()` never calls the stamp on a dry run,
    # so a re-run over a merge recorded without a head would preview in silence
    # what the real run then writes. Asked of the copy the real run would write.
    if answer.get("dryRun") and code == E_OK and not answer.get("pending"):
        survivor = surviving_copy(args.manifest, project, git_root, observation,
                                  the_plan, phase_id=args.phase)[0]
        if survivor:
            answer.update(backfill_merged_head(
                survivor, args.phase, names["parent"], project,
                lambda recorded: recovered_head(git_root, names["branch"],
                                                names["parent"], recorded),
                after_the_fact=False, dry_run=True))
    answer["branchBasis"] = names["branchBasis"]
    answer["parentBasis"] = names["parentBasis"]

    # The stamp used to be written HERE, after `close()` had already done the
    # cleanup. It now runs inside it, before the deletions — see `close()`'s
    # `stamp` argument for why the order is the fix rather than a tidy-up.

    # A run STANDING IN the worktree it was asked to remove can never finish its own
    # cleanup, and that is not a defect to fix -- it is the refusal working. What was
    # missing is the way out: the operator is left holding a correct refusal and no
    # next step, which is how a guard earns a reputation for being in the way.
    if any("standing inside" in row.get("why", "")
           for row in (answer.get("blocked") or [])):
        tree = (observation.get("parentTree") or {}).get("path") or git_root
        answer["finishFrom"] = tree
        # Spelled the way the orchestrator and the command docs spell every script
        # call, and NOT as `os.path.abspath(__file__)`: no `.py` under `scripts/`
        # reads `__file__` outside the pinned preamble (`depth_sensitive_paths()`
        # fails the file that does), and a hard path would be wrong for the reader
        # anyway - they are running an installed plugin, not this checkout.
        # ...NAMING THE SURVIVING MANIFEST, not the path this run was handed: that
        # path is the worktree's copy, and a stamp through it lands in the tree the
        # follow-up exists to remove.
        survivor = surviving_copy(args.manifest, project, git_root, observation,
                                  the_plan, phase_id=args.phase)[0]
        shown = (os.path.relpath(os.path.realpath(survivor), os.path.realpath(tree))
                 if _wt.within_tree(tree, survivor) else survivor)
        answer["finishCommand"] = (
            'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/close-phase.py" %s %s '
            '--project .' % (shown.replace(os.sep, "/"), args.phase))

    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("close-phase.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_close_phase.py - run that file instead.")
        sys.exit(0)
    raise SystemExit(main(sys.argv[1:]))
