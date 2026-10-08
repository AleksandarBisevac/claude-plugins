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

A PHASE DOES NOT LAND OVER A VERDICT THAT NO LONGER HOLDS. Once the plan is made,
the phase's newest recorded gate verdict is asked at the head it would merge
(`gate_answer`: `_verdict_binding.phase_binding` over the gate and the tasks'
files of the phase - or, for a phase signed off in a group, of the carrier whose
run grades it, over every member's files). The ledger is read as committed at the
branch tip and, unioned with it, as it stands in the worktree holding the branch
(`branch_texts`); the digest is always taken over the tip's committed declared
files, checked out as a checkout of the branch writes them (`tip_scope`) - never
over a worktree, whatever tree `--project` names. Neither readable is
unreadable, never no run. A sign-off recorded with `--no-evidence-reason` is honoured: a
green it chose not to stand on does not refuse, a red recorded after it does. A red recorded after the
run the sign-off was bound to is newer evidence about the work about to land, and
`_verdict_binding.close_refusal` refuses on it and on every other arm in
`CLOSE_REFUSING_ARMS`, naming the run. It refuses only while the landing is
still to happen: a branch the parent already contains has landed, so a re-run
that stamps or cleans up prints the gate line and is never refused.
`--override-verdict` lands it anyway and journals the exception
(`_verdict_binding.ACTION_CLOSE_OVERRIDDEN`) before the merge - once, by the run
that merges; with the journal off, or a row that will not write, it refuses
instead. No run at all, or an `empty-gate` answer, does not refuse - there is
no measurement to vouch for, and the sign-off recorded why.

ACCEPTED: A PENDING HAND-OVER JOURNALS EACH TIME. With `meta.merge.auto` false
and the branch not yet landed, a run given `--override-verdict` writes its row
and hands the merge command over; run again before anyone merges, it writes
another. Each run is a separate hand-over of a merge over the same refusal, and
the alternative - writing none until something lands - would leave a hand merge
over a refused verdict with no row at all, because the run after it finds the
branch landed and asks nothing.

Usage:
  close-phase.py <manifest> <phaseId> [--project DIR] [--parent BRANCH]
                 [--branch NAME] [--remove-worktree] [--delete-branch]
                 [--no-ff] [--dry-run] [--json] [--override-verdict TEXT]

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
     not one, included: git answered, and it is the command that has to change.
     Or the phase's newest gate verdict no longer holds: the refusal names the
     run, and the two ways out are a green run recorded on the work
     (`run-test-gate.py --record`) or `--override-verdict "<why>"`, journaled
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
import posixpath
import shutil
import subprocess
import sys
import tempfile

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

import _claude_home  # noqa: E402  (a usage error names this copy and a newer installed one)
import _branch                                                       # noqa: E402
import _evidence_io  # noqa: E402  (where the ledger lives, and its one strict decode)
import _config_rules  # noqa: E402  (review_per_task_mode: the live key, refused not defaulted)
import _filed_returns as _fr  # noqa: E402  (landing_refusals: sign-off's own property)
import _journal_io                                                 # noqa: E402
import _loader  # noqa: E402  (script_path: the commit verbs run as subprocesses, never imported)
import _manifest_io as _mio                                          # noqa: E402
import _manifest_rules as _rules  # noqa: E402  (revalidate what the stamp writes)
import _panel_write  # noqa: E402  (the index lock the stub mirror is written under)
import _proposals  # noqa: E402  (parked_on_branch: the work this branch deferred)
import _tree_stamp  # noqa: E402  (declared_scope: the one reading of a declared entry)
import _verdict_binding as _vb  # noqa: E402  (the one rule for whether a verdict refuses a close)
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
        if written.get("planUnrestored"):
            # A REFUSED WRITE STILL ON DISK is neither a stamp nor its absence: the
            # plan holds bytes its own validation refused, so nothing past this
            # point - the cleanup least of all - may act on it.
            answer["blocked"] = list(answer["blocked"]) + [{
                "why": "the merge landed and %s" % (written["planUnrestored"],),
                "remedy": "put that file back from git or by hand, then run this "
                          "again - the cleanup is held back on purpose, because "
                          "the plan now holds a write its validation refused"}]
            return E_FAIL, answer
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
    # The path is relative to the tree that HOLDS the manifest: a worktree's
    # manifest handed from the main checkout sits outside `git_root`, and a path
    # taken against `git_root` would name a file no commit holds.
    holder = _wt.tree_root(os.path.dirname(os.path.abspath(manifest_path)))["root"]
    rel = os.path.relpath(os.path.realpath(os.path.abspath(manifest_path)),
                          os.path.realpath(holder or git_root))
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


def under_index_lock(manifest_path, project, note, write):
    """(True, `write()`'s answer, released) once `write` has run with the index
    lock held, or (False, why, "") when the lock was not taken and `write` never
    ran. `released` is the lock's sentence when it DECLINED the release, else "".

    THE LOCK EVERY OTHER PLAN WRITER TAKES, so a stamp and a panel save, or two
    closes of one single-file plan, serialise instead of each writing the copy it
    read and dropping the other's write while both answer ok. `write` does its own
    reading: what it decides on is read with the lock held.

    EVERY STEP UNDER A `try`, the lock's own included: the writers here run inside
    `close()` after the merge has landed, so a raise from reading the config or
    asking for the lock would report a merge that happened as one that failed.
    `project` is where the lock is taken; None reads it off the manifest's own tree.

    A DECLINED RELEASE IS RETURNED, NOT PRINTED INTO A LIST NOBODY READS. The lock
    declines to take back a claim another session has taken over, and that is the
    one sign this write ran beside another writer - so the caller carries it into
    the close answer, and a stamp under a lock taken over never reads as clean.
    """
    lines = []
    project = project or _panel_write.project_of_manifest(manifest_path)
    try:
        lock = _panel_write.acquire_index_lock(
            project, _panel_write.read_config(project), manifest_path, False,
            lines.append, "[close-phase]", note)
    except Exception as exc:
        return False, "the index lock could not be asked for: %s" % (exc,), ""
    if isinstance(lock, int):
        return False, ("the index lock was not taken (%s)"
                       % ("; ".join(line.strip() for line in lines)
                          or "exit %d" % (lock,))), ""
    try:
        got = write()
    finally:
        released = _panel_write.release_index_lock(lock, out=lines.append)
    return True, got, released or ""


def _notes(released="", unrestored=False):
    """What a locked write owes its caller beyond its own answer: the sentence of a
    release the lock declined, and whether a refused write was left in place
    because restoring its prior bytes failed."""
    return {"released": released, "unrestored": unrestored}


def _not_locked(why, phase_id, field):
    """The sentence a stamp the lock refused owes: nothing written, and the re-run
    that writes it."""
    return ("%s, so phase %s's %s was not written and the plan is as it was: the "
            "merge has landed, so run close-phase again for %s once the lock is free "
            "and the re-run writes it" % (why, phase_id, field, phase_id))


def mirror_stub(manifest_path, phase_id, project):
    """(index path written, or "", why, notes) -- re-mirror a phase's index stub from its
    shard, under the index lock.

    The stub is where the index alone answers a phase's status, and `stamp_merged`
    writes only the shard, so a stamp that stored `done` leaves the stub behind until
    this runs. A stub that already agrees is not rewritten: the index is written on a
    phase's own transitions and nothing else. A lock this cannot take is a sentence,
    not a failure - the merge happened and the shard records it, and `audit-task.py
    settle` re-mirrors the stub later. `notes` is `_notes()`'s shape.
    """
    if not _stale_stub(manifest_path, phase_id):
        return "", "", _notes()
    taken, got, released = under_index_lock(
        manifest_path, project, "close-phase stub mirror",
        lambda: _mirror_locked(manifest_path, phase_id))
    if not taken:
        return "", _unmirrored(got), _notes()
    path, why, unrestored = got
    return path, why, _notes(released, unrestored)


def _mirror_locked(manifest_path, phase_id):
    """`mirror_stub`'s write, run with the index lock held -> (path, why,
    unrestored)."""
    try:
        # RE-READ UNDER THE LOCK: what was stale a moment ago is decided again once
        # the lock is held, so a writer that got there first is not overwritten.
        moved = _stale_stub(manifest_path, phase_id)
        if not moved:
            return "", "", False
        raw = _mio.read_json(manifest_path)
        for stub in (raw.get("phases") or []):
            if isinstance(stub, dict) and str(stub.get("id")) == str(phase_id):
                stub.update(moved)
        new = _revalidated_write(manifest_path, manifest_path, raw)
        if new:
            return "", _unmirrored("the re-mirrored index would not validate (%s), "
                                   "so its prior bytes were restored"
                                   % ("; ".join(new[:3]),)), False
        return manifest_path, "", False
    except RefusedWriteStands as exc:
        return "", str(exc), True
    except Exception as exc:
        return "", _unmirrored("the index stub could not be written: %s"
                               % (exc,)), False


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
    this write's to refuse on, which is why the two sets are compared.

    THE RESTORE IS AS ATOMIC AS THE WRITE: `_panel_write.restore` puts the bytes
    back through a temp file and a replace, so a reader never meets a half-written
    plan. The bytes, not `obj`'s predecessor re-serialised - `atomic_write_json`
    would rewrite the content in this writer's formatting rather than restore it.

    A RESTORE THAT FAILS RAISES `RefusedWriteStands`, never the error itself: the
    refused bytes are on disk by then, and a caller reading an ordinary exception
    as "could not be written" would report the opposite of what the plan holds."""
    snap = _panel_write.snapshot([path])
    if snap[path] is None:
        # A snapshot of nothing restores by DELETING, so a file this cannot read
        # first is not written at all.
        raise OSError("%s could not be read before the write" % (path,))
    pre = _findings_of(manifest_path)
    _mio.atomic_write_json(path, obj, indent=2)
    new = sorted(_findings_of(manifest_path) - pre)
    if new:
        try:
            _panel_write.restore(snap)
        except Exception as exc:
            raise RefusedWriteStands(
                "%s was written and introduced %s; restoring its prior bytes "
                "failed: %s - the plan holds the refused write"
                % (path, "; ".join(new[:3]), exc))
    return new


class RefusedWriteStands(Exception):
    """A write `_revalidated_write` refused is still on disk because putting the
    prior bytes back failed. Its own type because every caller already catches
    `Exception` as "could not be written", which is the one thing this is not."""


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


def stamp_merged(manifest_path, phase_id, when=None, merged_head=_HEAD_NOT_ASKED,
                 project=None):
    """Write `phase.mergedAt` (and, in the SAME write, `phase.mergedHead`). Returns
    (the path written, the stamp) or ("", a reason), with `_notes()` third.

    UNDER THE INDEX LOCK (`under_index_lock`), the plan read with it held. A lock
    that is not taken writes nothing - never an unlocked write - and the reason
    names the re-run that stamps it, because the merge it records has landed.

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
    taken, got, released = under_index_lock(
        manifest_path, project, "close-phase stamp %s" % (phase_id,),
        lambda: _stamp_locked(manifest_path, phase_id, when, merged_head))
    if not taken:
        return "", _not_locked(got, phase_id, MERGED_FIELD), _notes()
    path, value, unrestored = got
    return path, value, _notes(released, unrestored)


def _stamp_locked(manifest_path, phase_id, when, merged_head):
    """`stamp_merged`'s read and write, run with the index lock held -> (path,
    stamp or why, unrestored)."""
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return "", ("no file holds phase %s - the index names no shard for it"
                    % (phase_id,)), False
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return "", "%s could not be read: %s" % (path, exc), False
    stamp = when or _utc_now()
    # A RECORDED MERGE IS KEPT: the field names the moment the parent came to hold
    # the branch, and a re-run finding it already there records nothing new.
    found = _phases_in(body, phase_id)
    for ph in found:
        if ph.get(MERGED_FIELD):
            return path, ph[MERGED_FIELD], False
    if not found:
        return "", "phase %s is not in %s" % (phase_id, path), False
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
    except RefusedWriteStands as exc:
        return "", str(exc), True
    except Exception as exc:
        return "", "%s could not be written: %s" % (path, exc), False
    if new:
        return "", ("%s would leave the plan invalid (%s), so its prior bytes were "
                    "restored" % (path, "; ".join(new[:3]))), False
    return path, stamp, False


def record_merged_head(manifest_path, phase_id, merged_head, merged_head_at=None,
                       project=None):
    """(path, head written or "", why, notes) - add `phase.mergedHead` (and, for a head
    recorded after the fact, `phase.mergedHeadAt`) to a phase whose merge is
    ALREADY recorded without one, and touch nothing else.

    The counterpart of `stamp_merged` for a plan written before the field existed,
    under the same index lock and through the same `_revalidated_write`: one read
    with the lock held, one write, restored on a new finding; a lock not taken
    writes nothing and names the re-run. It refuses rather than writes when the
    phase records no merge (that
    is `stamp_merged`'s job, and a head with no merge is a claim with no event) and
    when a head is already recorded - A RECORDED HEAD IS NEVER REPLACED: it is the
    one every reader has been measuring against, and replacing it would move a
    verdict nothing about the merge changed. `mergedAt` is not
    written at all, so it cannot move. `merged_head_at`, when given, is written in
    the same write as `mergedHeadAt`: the head is then not the merge's own commit.
    `notes` is `_notes()`'s shape.
    """
    if not merged_head:
        return "", "", "no head was supplied", _notes()
    taken, got, released = under_index_lock(
        manifest_path, project, "close-phase head %s" % (phase_id,),
        lambda: _head_locked(manifest_path, phase_id, merged_head, merged_head_at))
    if not taken:
        return "", "", _not_locked(got, phase_id, MERGED_HEAD_FIELD), _notes()
    path, head, why, unrestored = got
    return path, head, why, _notes(released, unrestored)


def _head_locked(manifest_path, phase_id, merged_head, merged_head_at):
    """`record_merged_head`'s read and write, run with the index lock held ->
    (path, head, why, unrestored)."""
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return "", "", ("no file holds phase %s - the index names no shard for it"
                        % (phase_id,)), False
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return "", "", "%s could not be read: %s" % (path, exc), False
    found = _phases_in(body, phase_id)
    if not found:
        return "", "", "phase %s is not in %s" % (phase_id, path), False
    if not all(ph.get(MERGED_FIELD) for ph in found):
        return "", "", "phase %s records no merge in %s" % (phase_id, path), False
    if any(ph.get(MERGED_HEAD_FIELD) for ph in found):
        return path, "", "a head is already recorded in %s" % (path,), False
    for ph in found:
        ph[MERGED_HEAD_FIELD] = merged_head
        if merged_head_at:
            ph[MERGED_HEAD_AT_FIELD] = merged_head_at
    try:
        new = _revalidated_write(manifest_path, path, body)
    except RefusedWriteStands as exc:
        return "", "", str(exc), True
    except Exception as exc:
        return "", "", "%s could not be written: %s" % (path, exc), False
    if new:
        return "", "", ("%s would leave the plan invalid (%s), so its prior bytes "
                        "were restored" % (path, "; ".join(new[:3]))), False
    return path, merged_head, "", False


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
    path, written, why, notes = record_merged_head(
        manifest_path, phase_id, head["sha"], merged_head_at=at, project=project)
    told = _told(notes, why)
    if not written:
        return dict(told, **({} if notes["unrestored"] else {"mergedHeadWhy": why}))
    # ONLY ALLOW-LISTED DETAIL KEYS: `_journal_io` drops any other key in silence,
    # so the head travels as `to`, its basis as `reason` and the branch whose chain
    # it came from as `parent`; what has no key of its own - which head this is,
    # `mergedHeadAt` - is in the summary.
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
                    "mergedAt": recorded[MERGED_FIELD], "parent": parent,
                    "reason": ("recovered: " if not at else "") + head["basis"]},
    })
    return dict(told, mergedHead=written, mergedHeadBackfilled=path,
                mergedHeadAt=at)


def _told(notes, why):
    """The answer fields a locked write's `_notes()` owe the close answer: the
    declined release as a warning, and the stranded refused write - whose
    sentence is `why` - as `planUnrestored`. {} for a write that owes neither."""
    told = {}
    if notes["released"]:
        told["lockWarnings"] = [notes["released"]]
    if notes["unrestored"]:
        told["planUnrestored"] = why
    return told


def _merged_told(*answers):
    """Several `_told` answers as one: every warning and every stranded write,
    in order."""
    warnings = [w for a in answers for w in (a.get("lockWarnings") or [])]
    lost = [a["planUnrestored"] for a in answers if a.get("planUnrestored")]
    told = {}
    if warnings:
        told["lockWarnings"] = warnings
    if lost:
        told["planUnrestored"] = "; ".join(lost)
    return told


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


# --- committing the stamp ----------------------------------------------------------
# A landing that writes `mergedAt` and the stored `done` into the parent's copy
# and leaves them there is half a landing: a clone of the parent reads the phase
# as running, and the next commit made in that tree sweeps the stamp into work
# that has nothing to do with it. So the stamp is committed where it was
# written - by the audit-state commit verb, and in a sharded plan the index
# verb after it, run as subprocesses because an entry point may not import
# another, and because their staging discipline (the allow-list, the index read
# back, the row inside the commit) is theirs to hold, not a second copy here.
LANDING_SUBJECT = "landed on %s"


def _commit_verb(script, manifest_path, phase_id, project, subject):
    """`(answer, None)` - the verb's `--json` answer - or `(None, why)`."""
    argv = [sys.executable, _loader.script_path(script), manifest_path, phase_id,
            "--project", project, "--subject", subject, "--json"]
    try:
        done = subprocess.run(argv, cwd=project, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s could not be run (%s)" % (script, exc)
    text = done.stdout.decode("utf-8", "replace")
    try:
        answer = json.loads(text)
    except ValueError:
        return None, "%s exited %d with no answer it could read: %s" % (
            script, done.returncode,
            (done.stderr.decode("utf-8", "replace") or text).strip()[:200])
    if done.returncode != 0 or answer.get("refused"):
        return None, "%s refused: %s" % (script, answer.get("refused")
                                         or "exit %d" % (done.returncode,))
    return answer, None


def commit_landing(target, phase_id, project, git_root, parent, branch=None,
                   run=None):
    """`{"landingCommits", "landingCommitWhy" | "landingCommitSkipped"}` -
    the stamp in `target` committed where it reaches `parent`; or why a commit
    verb or the follow-on fast-forward refused (`landingCommitWhy`, a failure
    of the landing); or why no commit was owed in that tree
    (`landingCommitSkipped`, said and not a failure).

    TWO TREES CAN HOLD THE STAMP. The parent's checkout, where the commit is
    the parent's next commit. Or - the parent checked out nowhere, so the merge
    was a ref-only fast-forward - the tree holding the phase branch itself:
    the commit goes on the branch, and the parent is fast-forwarded to it once
    more, so the record of the landing is on the parent and the branch is
    still contained in it. A stamp in a tree holding any other branch is left
    for that tree: a commit there would put the landing on a branch that is
    neither of the two."""
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return {"landingCommits": [], "landingCommitWhy": (
            "git would not list the worktrees (%s), so the tree the stamp sits "
            "in cannot be named" % (listing["error"],))}
    holder = _wt.holder_of(listing["trees"], parent)["tree"]
    here = _tree_holding(listing["trees"], target) or {}
    on_branch = (holder is None and branch and here.get("branch") == branch)
    if not on_branch and (not holder
                          or not _wt.within_tree(holder.get("path"), target)):
        return {"landingCommits": [], "landingCommitSkipped": (
            "%s sits in a tree holding %s, which is neither %s nor the branch "
            "that landed in it, so a commit there would not reach %s - commit "
            "it with that tree's own work" % (
                target, here.get("branch") or "no branch", parent, parent))}
    others = pending_beyond_stamp(
        target, phase_id, project, (here if on_branch else holder).get("path"))
    if others:
        return {"landingCommits": [], "landingCommitSkipped": (
            "%s holds uncommitted changes this landing did not write (%s), and the "
            "audit-state commit stages the whole of each file and directory they "
            "sit in - so committing the stamp there would carry them under a "
            "subject saying the phase landed. Commit it with that tree's own work"
            % ((here if on_branch else holder).get("path"), "; ".join(others)))}
    made = _commit_stamp(target, phase_id, project, parent)
    if made.get("landingCommitWhy") or not on_branch:
        made["landingCommitIn"] = (holder or here).get("path")
        return made
    made["landingCommitIn"] = here.get("path")
    if not made["landingCommits"]:
        return made
    # The parent follows the stamp commit by the same ref-only fast-forward
    # the merge was, and the ancestry is read back rather than trusted.
    fn = _wt._runner(run)
    argv = ["fetch", ".", "%s:refs/heads/%s" % (branch, parent)]
    code, _out, err = fn(git_root, argv)
    if code != 0 or _wt.merged_into(git_root, branch, parent,
                                    run=run)["answer"] != _wt.CONTAINED:
        made["landingCommitWhy"] = (
            "the stamp is committed on %s, and `git %s` did not carry %s to it "
            "(exit %s: %s) - run it once %s can fast-forward"
            % (branch, " ".join(argv), parent, code,
               (err or "").strip()[:160], parent))
    return made


# The fields a landing writes on its own phase. Anything else differing from the
# tree's HEAD in what the audit-state commit stages is somebody else's.
_STAMP_FIELDS = (MERGED_FIELD, MERGED_HEAD_FIELD, MERGED_HEAD_AT_FIELD, "status")


def _git_text(tree, args):
    """`(code, text)` of one git call in `tree`, or (None, "") when git cannot run."""
    code, raw = _git_bytes(tree, args)
    return code, raw.decode("utf-8", "replace")


def _tree_rel(tree, path):
    """`path` relative to `tree`, `/`-separated, or None when it is outside it."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(tree))
    return None if rel == ".." or rel.startswith(".." + os.sep) else \
        rel.replace(os.sep, "/")


def _unstamped(text, phase_id):
    """The plan file's JSON with this phase's stamp fields taken out, or None
    when it does not parse."""
    try:
        body = json.loads(text)
    except ValueError:
        return None
    for ph in _phases_in(body, phase_id):
        for key in _STAMP_FIELDS:
            ph.pop(key, None)
    return body


def _foreign_rows(head_text, text, phase_id):
    """Why the rows `text` holds past `head_text` are not all this phase's, or
    None when they are. The trail is append-only, so anything but an extension
    of what HEAD holds is somebody else's change too."""
    if not text.startswith(head_text):
        return "it no longer begins with what HEAD holds"
    for line in text[len(head_text):].splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            return "a row that does not parse"
        if str(((row if isinstance(row, dict) else {}).get("details") or {})
               .get("phaseId")) != str(phase_id):
            return "a row about something other than phase %s" % (phase_id,)
    return None


def pending_beyond_stamp(target, phase_id, project, tree):
    """`[sentence, ...]` - each change pending in `tree` that the audit-state
    commit would stage and that this landing did not write: the plan file(s)
    differing from HEAD beyond this phase's stamp fields, a journal file holding
    a row about anything else, and any evidence change. Empty is the one answer
    that commits.

    THE COMMIT STAGES WHOLE FILES AND DIRECTORIES. In a parent checkout another
    session shares, its uncommitted plan edit or trail row would otherwise ride
    into a commit titled as this phase's landing."""
    if not tree:
        return ["no tree is named to compare against"]
    config = _journal_io.load_config(project)
    found = []
    for path in sorted(set(p for p in (target, _phase_file(target, phase_id)) if p)):
        rel = _tree_rel(tree, path)
        if rel is None:
            continue
        code, head = _git_text(tree, ["show", "HEAD:%s" % (rel,)])
        if code != 0:
            found.append("%s is not in HEAD, so all of it would be added" % (rel,))
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                now = fh.read()
        except OSError as exc:
            found.append("%s could not be read (%s)" % (rel, exc))
            continue
        was, is_now = _unstamped(head, phase_id), _unstamped(now, phase_id)
        if was is None or is_now is None or was != is_now:
            found.append("%s differs from HEAD beyond phase %s's stamp"
                         % (rel, phase_id))
    for label, directory in (("journal", _journal_io.journal_dir(project, config)),
                             ("evidence",
                              _evidence_io.evidence_dir(project, config))):
        rel = _tree_rel(tree, directory) if directory else None
        if rel is None or not os.path.isdir(directory):
            continue
        code, listing = _git_text(tree, ["status", "--porcelain", "-z",
                                         "--untracked-files=all", "--", rel])
        if code != 0:
            found.append("git would not list the %s directory %s" % (label, rel))
            continue
        for entry in [e for e in listing.split("\0") if len(e) > 3]:
            changed = entry[3:]
            if label == "evidence":
                found.append("%s is an evidence change" % (changed,))
                continue
            hcode, head = _git_text(tree, ["show", "HEAD:%s" % (changed,)])
            try:
                with open(os.path.join(tree, *changed.split("/")), "r",
                          encoding="utf-8") as fh:
                    now = fh.read()
            except OSError:
                found.append("%s is changed and cannot be read" % (changed,))
                continue
            why = _foreign_rows(head if hcode == 0 else "", now, phase_id)
            if why:
                found.append("%s holds %s" % (changed, why))
    return found


def _commit_stamp(target, phase_id, project, parent):
    """The stamp committed by the audit-state verb, and the index verb after it
    in a sharded plan, run in `project`."""
    subject = LANDING_SUBJECT % (parent,)
    scripts = ["commit-audit-state.py"]
    try:
        if _mio.is_sharded(_mio.read_json(target)):
            scripts.append("commit-manifest-index.py")
    except Exception as exc:
        return {"landingCommits": [], "landingCommitWhy": (
            "%s cannot be read to tell its layout (%s)" % (target, exc))}
    made = []
    for script in scripts:
        answer, why = _commit_verb(script, target, phase_id, project, subject)
        if why:
            return {"landingCommits": made, "landingCommitWhy": why}
        if answer.get("commit"):
            made.append(answer["commit"])
    return {"landingCommits": made, "landingCommitWhy": ""}


# --- the verdict at the head it would merge ---------------------------------------
# WHICH TREE `--project` NAMES IS NOT THE QUESTION. A landing is often run from the
# parent's tree, which holds none of the phase's ledger rows and none of its
# declared files as the branch has them, so a verdict read there would read as no
# run at all and land the branch unasked. The rows are read as committed at the
# branch tip (git objects, never a checkout) and, when a worktree holds the branch,
# as they stand in that tree too - the union by row identity, so a red recorded
# there after the sign-off and not yet committed still counts. The digest is
# always taken over the tip's own committed declared files, checked out into a
# scratch repository - never over that worktree, whose uncommitted bytes do not
# land.

def _git_bytes(git_root, args, env=None):
    """`(code, stdout bytes)` of one git call - bytes, because a ledger is decoded
    by its own strict rule, never by git's replacement of a bad byte."""
    try:
        done = subprocess.run(["git", "-C", git_root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=env)
    except Exception:
        return None, b""
    return done.returncode, done.stdout


def _tip_paths(git_root, branch, rel):
    """The files git lists under `rel` (root-relative) at `branch`'s tip, or
    None when git would not answer."""
    code, out = _git_bytes(git_root, ["ls-tree", "-r", "--name-only", "-z",
                                      "refs/heads/%s" % (branch,), "--", rel])
    if code != 0:
        return None
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def tip_texts(git_root, branch, directory):
    """`(texts, why)` - the `.jsonl` files directly in `directory` as committed at
    `branch`'s tip, in `_verdict_binding.ledger_texts`' shape, or `(None, why)`
    when git could not be asked."""
    rel = os.path.relpath(directory, git_root).replace(os.sep, "/")
    if rel.startswith(".."):
        return None, "%s is outside the repository" % (directory,)
    paths = _tip_paths(git_root, branch, rel)
    if paths is None:
        return None, "git would not list %s at %s" % (rel, branch)
    texts = []
    for path in sorted(p for p in paths if p.endswith(".jsonl")
                       and os.path.dirname(p) == rel.rstrip("/")):
        code, raw = _git_bytes(git_root, ["cat-file", "blob",
                                          "refs/heads/%s:%s" % (branch, path)])
        try:
            text = _evidence_io.ledger_decode(raw) if code == 0 else None
        except Exception:
            text = None
        texts.append(("%s:%s" % (branch, path), text))
    return texts, ""


def branch_texts(git_root, project, branch, phase_tree, directory):
    """`(texts, notes)` - one record directory as the landing judges it: at the
    branch tip, unioned with the worktree holding the branch when there is one.

    NEITHER READABLE IS ITS OWN ANSWER: a single entry that could not be read,
    which `_verdict_binding` refuses as unreadable rather than reading no rows
    as no run.
    """
    tip, why = tip_texts(git_root, branch, directory)
    tree = _phase_project(git_root, project, phase_tree)
    rel = os.path.relpath(directory, project)
    local = (_vb.ledger_texts(tree, directory=os.path.join(tree, rel))
             if tree else None)
    # AN EMPTY LOCAL READING IS NOT A READING when the tip is lost too: a
    # directory missing or unlistable in the worktree lists nothing, and nothing
    # read is not the same answer as no run recorded.
    if tip is None and not local:
        return [("%s:%s" % (branch, rel.replace(os.sep, "/")), None)], []
    notes = ["the branch tip could not be read (%s), so only %s was" % (why, tree)
             ] if tip is None else []
    return (tip or []) + (local or []), notes


def _phase_project(git_root, project, phase_tree):
    """The project directory inside the worktree that holds the branch, or None."""
    if not phase_tree or phase_tree.get("prunable") or not phase_tree.get("path"):
        return None
    tree = os.path.join(phase_tree["path"], os.path.relpath(project, git_root))
    return os.path.normpath(tree) if os.path.isdir(tree) else None


# The scratch repository's git reads none of the operator's config: a global
# `core.excludesFile` would leave a declared file matching it out of `add`, and
# the digest would then read a file the tip carries as absent.
_SCRATCH_GIT = ["-c", "core.excludesFile=", "-c", "core.hooksPath="]


def _scratch_env():
    """The environment the scratch repository's git runs under: no global and no
    system config."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def tip_scope(git_root, project, branch, files):
    """A scratch git repository holding `files` (project-relative, a directory
    expanded) as a checkout of `branch`'s tip would write them, or None when
    the tip's declared work could not be written out. The caller removes it. A
    repository rather than a plain directory, because the digest expands a
    declared directory by asking git what it holds.

    THE ENTRIES ARE READ AS THE DIGEST READS THEM, through
    `_tree_stamp.declared_scope`: a `:line-range` suffix or a backslash left on
    would list nothing at the tip, and the digest would read a file the branch
    carries as missing.

    EVERY FAILURE REMOVES THE SCRATCH AND ANSWERS None, a write that raised
    included: a half-written copy is not the tip, and a directory left behind is
    a leak into the operator's temp."""
    prefix = os.path.relpath(project, git_root).replace(os.sep, "/")
    prefix = "" if prefix == "." else prefix + "/"
    scratch = tempfile.mkdtemp(prefix="close-phase-tip-")
    try:
        if _write_tip(git_root, branch, prefix, _tree_stamp.declared_scope(files),
                      scratch):
            return scratch
    except Exception:
        pass
    _output.remove_tree(scratch)
    return None


def _write_tip(git_root, branch, prefix, declared, scratch):
    """True once the `declared` files at `branch`'s tip are written into
    `scratch` as a checkout writes them and added to a repository there; False
    when any of it could not be.

    CHECKED OUT, NOT CAT-FILED. The recorder hashed the working tree, whose
    bytes are the blob after the repository's eol, text and smudge rules - a
    branch under `core.autocrlf`, an `eol=crlf` attribute or a clean/smudge
    filter holds different bytes in its blobs than in its checkout, and a
    digest over the blobs would refuse every green it ever recorded. So the
    tip is checked out for real, into a work tree of its own (`_check_out`),
    and the scratch repository is written from that."""
    paths = []
    for rel in declared:
        listed = _tip_paths(git_root, branch, prefix + rel.rstrip("/"))
        if listed is None:
            return False
        paths.extend(listed)
    paths = sorted(set(paths))
    staging = tempfile.mkdtemp(prefix="close-phase-tip-")
    try:
        work_tree = _check_out(git_root, branch, paths, staging)
        if work_tree is None:
            return False
        for path in paths:
            raw = _checked_out_bytes(os.path.join(work_tree, path))
            if raw is None:
                # Listed and then not written out: the declared work at the
                # tip is not established, which the digest must not read as
                # absent.
                return False
            target = os.path.join(scratch, path[len(prefix):])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(raw)
    finally:
        _output.remove_tree(staging)
    env = _scratch_env()
    for args in (["init", "-q"], ["add", "-A", "--force"]):
        if _git_bytes(scratch, _SCRATCH_GIT + args, env=env)[0] != 0:
            return False
    return True


def _check_out(git_root, branch, paths, staging):
    """The work tree under `staging` holding `paths` (root-relative) checked
    out from `branch`'s tip, every in-repository target of a symbolic link
    among them checked out too, or None when git would not write them or a
    link leads outside the tip.

    THE REPOSITORY'S OWN GIT, with the operator's config, under an index of its
    own: `read-tree` loads the tip into that index, so the attributes a checkout
    consults are the tip's `.gitattributes`, and `checkout-index` applies the
    same conversion and filters a checkout of the branch would. The
    repository's real index and work tree are never touched.

    A LINK IS FOLLOWED THE WAY THE RECORDER'S FILE HASH FOLLOWS IT: the digest
    hashes the bytes reading the link yields, so the file it leads to has to be
    at the tip and in this work tree as well. A target outside the tip - an
    absolute path, or one climbing out of the repository - is not something the
    tip can vouch for, and answers None rather than bytes the digest would read
    as moved."""
    code, out = _git_bytes(git_root, ["rev-parse", "--absolute-git-dir"])
    git_dir = out.decode("utf-8", "replace").strip() if code == 0 else ""
    if not git_dir:
        return None
    work_tree = os.path.join(staging, "tree")
    os.makedirs(work_tree)
    env = dict(os.environ, GIT_INDEX_FILE=os.path.join(staging, "index"))
    base = ["git", "--git-dir=%s" % (git_dir,), "--work-tree=%s" % (work_tree,)]
    if not _git_ok(base + ["read-tree", "refs/heads/%s" % (branch,)], work_tree,
                   env, b""):
        return None
    wanted, written = set(paths), set()
    # Each round checks out what the last round's links lead to; a target
    # already written ends a chain, so a cycle of links ends too.
    while wanted - written:
        batch = sorted(wanted - written)
        if not _git_ok(base + ["checkout-index", "-f", "-z", "--stdin"],
                       work_tree, env,
                       b"".join(p.encode("utf-8") + b"\0" for p in batch)):
            return None
        written.update(batch)
        for path in batch:
            target = _link_target(work_tree, path)
            if target is False:
                return None
            if target:
                wanted.add(target)
    return work_tree


def _git_ok(argv, cwd, env, given):
    """True when one git call fed `given` on stdin exits 0."""
    try:
        return subprocess.run(argv, cwd=cwd, env=env, input=given,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def _link_target(work_tree, path):
    """The root-relative path the link checked out at `path` leads to; None
    when `path` is not a link, False when it leads outside the tip."""
    full = os.path.join(work_tree, path)
    if not os.path.islink(full):
        return None
    text = os.readlink(full).replace("\\", "/")
    if os.path.isabs(text) or text.startswith("/"):
        return False
    target = posixpath.normpath(posixpath.join(posixpath.dirname(path), text))
    if target in (".", "..") or target.startswith("../"):
        return False
    return target


def _checked_out_bytes(path):
    """The bytes reading `path` in the checked-out tree yields - through a
    link, its target's, which is what the recorder's file hash reads - or None
    when there is no file to read there."""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def gate_answer(project, manifest_path, manifest, phase, git_root=None,
                branch=None, phase_tree=None):
    """`(answer, signed_without_run, notes)` - `_verdict_binding.phase_binding`
    for the phase about to land, in this command's words, and what its sign-off
    recorded about standing on no run.

    THE RUN THAT GRADES THE PHASE: its own, or for a member of a group signed off
    together, the carrier's over every member's files (`_verdict_binding.group_of`,
    the question group sign-off asked). A member's own ledger holds no row, so
    asking it alone would read as no verdict and land the whole branch over the
    carrier's red.

    ...AND THE MEMBER'S OWN ROWS TOO. A red recorded on a member alone after the
    group's run is newer evidence about the branch every member lands, so it
    refuses (`_verdict_binding.member_red`).

    READ AT THE HEAD IT WOULD MERGE when `branch` is given: the ledger and the
    journal through `branch_texts`, and the digest over the tip's own declared
    files (`tip_scope`) - never a worktree's working files, whose uncommitted
    bytes are not what lands. A tip that cannot be written out answers
    unanswerable. Without a branch, the ledger and the files under `project`.

    A SIGN-OFF RECORDED WITH `--no-evidence-reason` is handed on as
    `{"at": <its phase.verdict journal row's ts, or None>}` for
    `_verdict_binding.close_refusal` to honour.
    """
    carrier, members = _vb.group_of(manifest, phase or {})
    cid = str(carrier.get("id"))
    others = [str(m.get("id")) for m in members[1:]]
    record = ("run `run-test-gate.py %s %s%s --record` on the work, then land it"
              % (_output.posix_rel(manifest_path, project), cid,
                 "".join(" --also %s" % (o,) for o in others)))
    files = _vb.phase_files(members)
    config = _journal_io.load_config(project)
    texts, digest_root, scratch, notes = None, None, None, []
    journal = None
    tip_lost = False
    if branch and git_root:
        texts, notes = branch_texts(git_root, project, branch, phase_tree,
                                    _evidence_io.evidence_dir(project, config))
        journal, journal_notes = branch_texts(
            git_root, project, branch, phase_tree,
            _journal_io.journal_dir(project, config))
        notes = notes + ["journal: %s" % (n,) for n in journal_notes]
        if files:
            scratch = tip_scope(git_root, project, branch, files)
            tip_lost = scratch is None
            # NO SCRATCH IS NOT THE PARENT'S FILES: a digest over `project`
            # would grade bytes that do not land, so a root holding nothing
            # is handed on and the answer is rewritten below as unanswerable.
            digest_root = scratch or os.path.join(project, ".close-phase-no-tip")
    review = (phase or {}).get("review") or {}
    signed = None
    if isinstance(review, dict) and str(review.get("noEvidenceReason") or "").strip():
        if journal is None:
            journal = _vb.ledger_texts(project, config,
                                       directory=_journal_io.journal_dir(project,
                                                                         config))
        signed = {"at": _vb.signoff_moment(journal, (phase or {}).get("id"))}
    try:
        answer = _vb.phase_binding(
            project, manifest_path, manifest, carrier, files, record,
            "phase %s declares no gate, so its landing rests on its sign-off alone"
            % (cid,), config=config, texts=texts, digest_root=digest_root)
    finally:
        if scratch:
            _output.remove_tree(scratch)
    if tip_lost and (answer.get("state") == "bound"
                     or answer.get("arm") in (_vb.ARM_DIGEST_MOVED,
                                              _vb.ARM_DIGEST_UNANSWERABLE)):
        answer = dict(answer, state="refused", arm=_vb.ARM_DIGEST_UNANSWERABLE,
                      sentence=(
                          "%s's declared files could not be read as committed at "
                          "%s's tip, so whether its newest verdict measured the "
                          "work that would land is not established - %s"
                          % (cid, branch, record)))
    if answer.get("arm") == _vb.ARM_DIGEST_MOVED and branch and git_root:
        answer = _uncommitted_remedy(answer, record, uncommitted_declared(
            git_root, project, phase_tree, files))
    if str((phase or {}).get("id")) != cid and _vb.close_refusal(answer) is None:
        own = _vb.member_red(
            texts if texts is not None else _vb.ledger_texts(project, config),
            (phase or {}).get("id"), answer, record)
        if own is not None:
            answer = own
    return answer, signed, notes


def uncommitted_declared(git_root, project, phase_tree, files):
    """The declared files (project-relative, sorted) holding changes no commit
    carries, in the worktree that holds the branch; [] when none do, when no
    worktree holds it, or when git could not say - the clause this feeds is a
    remedy, and the refusal it rides on stands either way."""
    tree = _phase_project(git_root, project, phase_tree)
    declared = _tree_stamp.declared_scope(files)
    if not tree or not declared:
        return []
    code, out = _git_bytes(tree, ["status", "--porcelain", "-z",
                                  "--untracked-files=all", "--"] + declared)
    if code != 0:
        return []
    prefix = os.path.relpath(project, git_root).replace(os.sep, "/")
    prefix = "" if prefix == "." else prefix + "/"
    found, skip = [], False
    for entry in out.decode("utf-8", "replace").split("\0"):
        if skip or len(entry) < 4:
            skip = False
            continue
        # A rename's entry is followed by its source path, which is not one.
        skip = any(c in "RC" for c in entry[:2])
        path = entry[3:]
        found.append(path[len(prefix):] if path.startswith(prefix) else path)
    return sorted(set(found))


def _uncommitted_remedy(answer, record, dirty):
    """`answer` with its remedy naming the `dirty` declared files, or unchanged
    when there are none.

    RECORDING AGAIN OVER THE SAME DIRT LOOPS: the recorder hashes the working
    files and the landing digests the tip's committed ones, so a run recorded
    while a declared file holds an uncommitted change is refused here however
    often it is recorded. The change has to reach a commit, or leave the tree,
    first."""
    if not dirty:
        return answer
    fixed = ("declared file(s) %s hold uncommitted changes in the worktree "
             "holding the branch, which the recorded run measured and the tip "
             "does not carry - commit or revert them before recording, then %s"
             % (", ".join(dirty), record))
    sentence = answer.get("sentence") or ""
    return dict(answer, sentence=(sentence.replace(record, fixed)
                                  if record in sentence
                                  else "%s; %s" % (sentence, fixed)))


def review_answers_refusal(project, manifest_path, phase):
    """The sentence refusing a landing under `review.perTask: phase`, or None.

    THE SAME PROPERTY SIGN-OFF ASKS, through the same function
    (`_filed_returns.landing_refusals`), of the plan's RECORD as it stands now -
    so a commit or an answer changed by hand after sign-off, or by a writer
    nobody listed, is refused here too. Without it this command would be a way
    past the sign-off verb. A task with no recorded key reads the config's
    value now, and a config value outside the vocabulary is refused, never read
    as `always`."""
    tasks = [t for t in (phase or {}).get("tasks") or [] if isinstance(t, dict)]
    live = None
    if any(t.get("commit") and _fr.review_key(t, phase, None)[1] == "config"
           for t in tasks):
        _proj, config = _evidence_io.project_config_for(manifest_path, project)
        live, problem = _config_rules.review_per_task_mode(config)
        if problem:
            return "%s." % (problem,)
    held = _fr.landing_refusals(phase or {}, live)
    if not held:
        return None
    return ("review.perTask reads `phase` and phase %s has task(s) whose review "
            "answers are not on the record bound to their commits: %s. Sign-off "
            "writes them from the phase review's filed return - file it and sign "
            "off again." % ((phase or {}).get("id"),
                            "; ".join("%s: %s" % (tid, why) for tid, why in held)))


def landed_answers_refusal(project, manifest_path, phase, landed, branch,
                           git_root=None, phase_tree=None, refs=()):
    """The sentence refusing a landing under `review.perTask: phase`, asked of
    EVERY copy of the phase the landing can see, or None.

    The copy handed in is the parent's when the merge is run from the parent's
    checkout, and there it still shows the phase as it stood at the fork: no
    task records a commit, so the property finds nothing to ask. The copy the
    merge brings in is the branch tip's (`landed`), and the copy on disk in the
    worktree holding the branch is the newest record of all, so both are asked
    too.

    A TIP COPY WITH NO SIGN-OFF VERDICT IS REFUSED wherever the property could
    apply. A task closed `deferred` reaches the tip only with the sign-off
    commit - the task's own commit staged the plan before its close was
    written - so a tip recording no verdict can hold a closed task its copy does
    not show, and the question is asked of the tip rather than of whichever
    worktree still stands.

    A tip whose copy cannot be read is refused under the same condition only
    when the plan is VERSIONED (`plan_versioned`): a plan git never commits is
    in no tip, and its copy on disk is then the record, asked the property and
    the verdict in the tip's place.

    UNDER EVERY KEY, A FILED PHASE RETURN HOLDING AN ANSWER ONLY A HUMAN
    SETTLES (`_fr.needs_human`) asks for the same verdict: only the sign-off
    verb writes one, and it refuses while such an answer is unsettled, and
    `audit-task.py file-return` refuses a phase return once a verdict is
    recorded - so a recorded verdict is the evidence that every return filed
    through that verb was put to a human. A return written into the evidence
    directory by any other hand after the verdict is not told apart from one
    the verdict read. A return that will not parse could hold one, and asks for
    the verdict too."""
    phase_id = (phase or {}).get("id")
    on_disk = worktree_phase(git_root, project, phase_tree, manifest_path,
                             phase_id)
    copies = [("", phase)]
    if on_disk:
        copies.append(("in the worktree holding %s: " % (branch,), on_disk))
    if landed is not None:
        copies.append(("on %s: " % (branch,), landed))
    for where, copy in copies:
        held = review_answers_refusal(project, manifest_path, copy)
        if held:
            return where + held
    applies, problem = _phase_key_applies(project, manifest_path,
                                          [copy for _w, copy in copies])
    if problem:
        return problem
    filed = filed_phase_returns(project, manifest_path, git_root, branch,
                                phase_tree, phase_id)
    human = unsettled_sentence(phase_id, filed)
    if not applies and human is None:
        return None
    if applies:
        subject = "review.perTask reads `phase` for phase %s" % (phase_id,)
        unknown = "whether its tasks carry their review answers"
        because = ("a task's close reaches the branch only with the sign-off "
                   "commit")
    else:
        subject, unknown = human, "whether a human settled them"
        because = ("only the sign-off verb writes the verdict, and it refuses "
                   "while such an answer is unsettled")
    if landed is not None:
        if _mio.signoff_recorded(landed):
            return None
        return ("%s, and the copy of the plan %s would bring in records no "
                "sign-off verdict, so %s is not established: %s. Sign the phase "
                "off on %s and run this again."
                % (subject, branch, unknown, because, branch))
    versioned, basis = plan_versioned(git_root, manifest_path, refs)
    if versioned is not False:
        return ("%s, and the copy of the plan %s would bring in could not be "
                "read (%s), so %s is not established. The parent's copy does not "
                "stand in for it: it records the phase as it stood at the fork. "
                "Commit the plan on %s and run this again."
                % (subject, branch, basis, unknown, branch))
    record = on_disk or phase
    if _mio.signoff_recorded(record):
        return None
    return ("%s, the plan is not versioned (%s), so its copy on disk is the "
            "record - and it records no sign-off verdict. Sign the phase off and "
            "run this again." % (subject, basis))


def unsettled_sentence(phase_id, filed):
    """The clause naming what in `filed` (`filed_phase_returns`' list) waits on
    a human - an answer `_fr.needs_human` reports, or a return that will not
    parse and so could hold one - or None when nothing does."""
    asked = _fr.needs_human(filed)
    unread = [why for _rel, _body, why in filed if why]
    if not asked and not unread:
        return None
    said = []
    if asked:
        said.append("answer(s) only a human settles (%s)" % ("; ".join(
            "%s %s" % (a["who"], a["what"]) for a in asked),))
    if unread:
        said.append("a return that cannot be read, so could hold one only a "
                    "human settles (%s)" % ("; ".join(unread),))
    return "phase %s's filed review holds %s" % (phase_id, " and ".join(said))


def filed_phase_returns(project, manifest_path, git_root, branch, phase_tree,
                        phase_id):
    """`[(rel, body, problem)]` in `_fr.phase_returns`' shape - every phase
    return filed for `phase_id` that the landing can see: under the project's
    evidence directory, in the worktree holding the branch, and committed at the
    branch tip. The first copy of a name is kept; a return is keyed on the head
    its brief named, and the filing verb refuses a second for one head.

    A TIP GIT WOULD NOT LIST is a problem entry, never no return filed: the
    landing cannot tell an unread directory from an empty one."""
    proj, config = _evidence_io.project_config_for(manifest_path, project)
    evidence = _evidence_io.evidence_dir(proj, config)
    found = list(_fr.phase_returns(evidence, phase_id))
    tree = _phase_project(git_root, project, phase_tree) if git_root else None
    if tree:
        found += _fr.phase_returns(
            os.path.join(tree, os.path.relpath(evidence, project)), phase_id)
    folder = os.path.join(evidence, _fr.RETURNS_DIRNAME, str(phase_id))
    rel = (os.path.relpath(folder, git_root).replace(os.sep, "/")
           if git_root else "..")
    if branch and not rel.startswith(".."):
        paths = _tip_paths(git_root, branch, rel)
        if paths is None:
            found.append(("%s:%s" % (branch, rel), None,
                          "git would not list %s at %s" % (rel, branch)))
        for path in sorted(p for p in paths or []
                           if p.endswith(".reviewer.json")
                           and posixpath.dirname(p) == rel):
            code, raw = _git_bytes(git_root, ["cat-file", "blob", "refs/heads/%s:%s"
                                              % (branch, path)])
            text = raw.decode("utf-8", "replace") if code == 0 else None
            body, problem = _fr.return_body(text, "%s:%s" % (branch, path))
            found.append(("%s/%s/%s" % (_fr.RETURNS_DIRNAME, phase_id,
                                        posixpath.basename(path)), body, problem))
    kept, seen = [], set()
    for entry in found:
        if entry[0] not in seen:
            seen.add(entry[0])
            kept.append(entry)
    return kept


def _phase_key_applies(project, manifest_path, copies):
    """`(applies, problem)` - whether any task of any copy reads the key
    `phase`, its unrecorded key read off the config; `problem` is a config
    value outside the vocabulary, refused rather than read as `always`."""
    pairs = [(t, copy) for copy in copies
             for t in (copy or {}).get("tasks") or [] if isinstance(t, dict)]
    live = None
    if any(_fr.review_key(t, copy, None)[1] == "config" for t, copy in pairs):
        _proj, config = _evidence_io.project_config_for(manifest_path, project)
        live, problem = _config_rules.review_per_task_mode(config)
        if problem:
            return False, "%s." % (problem,)
    return any(_fr.review_key(t, copy, live)[0] == _fr.KEY_PHASE
               for t, copy in pairs), ""


def worktree_phase(git_root, project, phase_tree, manifest_path, phase_id):
    """The phase as the plan on disk in the worktree holding the branch records
    it, or None - none when no worktree holds it, the plan sits outside the
    project, or the copy there is the one handed in."""
    if not git_root:
        return None
    tree = _phase_project(git_root, project, phase_tree)
    if not tree:
        return None
    rel = os.path.relpath(os.path.abspath(manifest_path), os.path.abspath(project))
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    there = os.path.join(tree, rel)
    if os.path.realpath(there) == os.path.realpath(manifest_path) \
            or not os.path.isfile(there):
        return None
    return _recorded_phase(there, phase_id) or None


def plan_versioned(git_root, manifest_path, refs):
    """`(answer, basis)` - True when git versions the plan: inside the tree
    that holds it, not ignored there, and present at one of `refs` (the
    parent, the phase's `baseRef`). False when one of those fails; None when
    git could not say, which the caller refuses as it would True."""
    if not git_root:
        return None, "no git root to ask"
    holder = _wt.tree_root(os.path.dirname(os.path.abspath(manifest_path)))["root"]
    rel = _tree_rel(holder or git_root, manifest_path)
    if rel is None:
        return False, "%s lies outside the git root" % (manifest_path,)
    code, _out = _git_bytes(holder or git_root, ["check-ignore", "-q", "--", rel])
    if code == 0:
        return False, "git ignores %s" % (rel,)
    if code != 1:
        return None, "git check-ignore could not answer for %s" % (rel,)
    asked = [r for r in refs if r]
    for ref in asked:
        code, _out = _git_bytes(git_root, ["cat-file", "-e", "%s:%s" % (ref, rel)])
        if code == 0:
            return True, "%s holds %s" % (ref, rel)
    if not asked:
        return None, "no parent or base to ask whether %s is committed" % (rel,)
    return False, "%s is committed at none of %s" % (rel, ", ".join(asked))


def override_row(project, phase_id, answer, reason, config=None):
    """The row a landing over its verdict's refusal writes BEFORE the merge, or
    None when the trail did not take it. Worded as what was asked, because the
    merge after it can still refuse."""
    config = _journal_io.load_config(project) if config is None else config
    ids = {"phaseId": str(phase_id)}
    return _journal_io.append_from_cli(project, {
        "action": _vb.ACTION_CLOSE_OVERRIDDEN,
        "actor": {"via": "close-phase"},
        "target": str(phase_id),
        "summary": _vb.override_summary(ids, answer, reason),
        "details": _vb.override_details(ids, answer, reason),
    }, config=config)


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

def _render_told(answer, out=print):
    """The lines `_told` fields owe: each declined lock release as a warning, and a
    refused write left on disk - nothing for an answer carrying neither."""
    for said in answer.get("lockWarnings") or []:
        out("  WARNING: another session took the index lock while this run was "
            "writing under it - %s" % (said,))
    if answer.get("planUnrestored"):
        out("  REFUSED WRITE NOT ROLLED BACK: %s" % (answer["planUnrestored"],))


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


def gate_lines(gate):
    """The lines the verdict a landing stood on owes - none when it was not asked.

    FOUR ANSWERS, worded apart: landed over a refusal with the override (and
    whether the trail took it), already landed so a refusal is said but not
    applied, the verdict as it bound or did not, and an override given with
    nothing to go over."""
    gate = gate or {}
    if not gate:
        return []
    if gate.get("overridden"):
        how = (("journaled as %s" % (_vb.ACTION_CLOSE_OVERRIDDEN,))
               if gate.get("journaled")
               else "NOT journaled: %s" % (gate.get("journalWhy"),))
        return ["  gate: OVER ITS VERDICT'S REFUSAL - %s" % (gate.get("refusal"),),
                "  %s: %s (%s)" % (_vb.OVERRIDE_FLAG, gate.get("overrideReason"),
                                   how)]
    if gate.get("refusal") and not gate.get("landingDue"):
        return ["  gate: the branch has already landed, so its verdict refuses "
                "nothing here - %s" % (gate.get("refusal"),)]
    notes = ["  gate note: %s" % (n,) for n in (gate.get("notes") or [])]
    if gate.get("honoured"):
        return notes + [
            "  gate: the sign-off recorded --no-evidence-reason (at %s), so a "
            "verdict it chose not to stand on refuses nothing here - %s"
            % (gate.get("signedAt") or "a moment its journal does not name",
               gate.get("sentence"))]
    lines = notes + ["  gate: %s" % (_vb.close_line(gate),)]
    if gate.get("overrideUnneeded"):
        lines.append("  %s was given and not needed: the verdict refuses nothing "
                     "here, so no exception was journaled" % (_vb.OVERRIDE_FLAG,))
    return lines


def render(answer, out=print):
    """One block a human reads top to bottom: what was decided, what ran, what did
    not, and why. Refusals carry their remedy on the next line, because a refusal
    nobody can act on is one they route around."""
    out("[close-phase] %s -> %s (%s)"
        % (answer["branch"], answer["parent"], answer["mode"]))
    for line in gate_lines(answer.get("gate")):
        out(line)
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
    _render_told(answer, out=out)
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
        if answer.get("landingCommitWhy"):
            out("  the stamp is NOT committed: %s" % (answer["landingCommitWhy"],))
        elif answer.get("landingCommitSkipped"):
            out("  the stamp is not committed here: %s"
                % (answer["landingCommitSkipped"],))
        elif answer.get("landingCommits"):
            out("  the stamp committed in %s as %s"
                % (answer.get("landingCommitIn"),
                   ", ".join(c[:12] for c in answer["landingCommits"])))
        elif "landingCommits" in answer:
            out("  the stamp was already committed in %s"
                % (answer.get("landingCommitIn"),))
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

# What a landing's long form says when it still owes the reader something: a
# refusal, a preview, a cleanup to finish, a field it could not write, an
# override of the verdict, a lock taken while it ran, work parked to materialize.
_OWED = ("REFUSED", "NOT MERGED", "WARNING", "would run", "would write",
         "cleanup is not finished", "after the merge", "parked on", " NOT ",
         "OVER ITS VERDICT", "not committed here")


def _short_record(line):
    """A written field's line, shortened for the one-line form: the merged head
    abbreviated, and a path written under the working directory spelled
    relative to it."""
    head = "%s = " % (MERGED_HEAD_FIELD,)
    if line.startswith(head):
        return head + line[len(head):].strip()[:12]
    lead, sep, path = line.rpartition(" written to ")
    here = os.getcwd()
    if sep and _wt.within_tree(here, path):
        return "%s%s%s" % (lead, sep, _output.posix_rel(
            os.path.realpath(path), os.path.realpath(here)))
    return line


def success_line(lines):
    """A landing's one line: branch, parent and mode, the merge field it wrote
    and where, the merged head, and how many steps were not done.

    None - the long form - when a git step failed or any line carries one of
    `_OWED`. A `not done:` row is counted rather than printed, with the flag
    that prints why: the ordinary one says there was no worktree to own.
    """
    said = [ln.strip() for ln in lines if ln.strip()]
    if not said or not said[0].startswith("[close-phase] "):
        return None
    failed = [ln for ln in said if ln.startswith("git ")
              and (ln.split(" -> ", 1)[1:] or ["?"])[0].split()[:1] != ["0"]]
    if failed or any(mark in ln for ln in said for mark in _OWED):
        return None
    record = [_short_record(ln) for ln in said
              if ln.startswith(("%s = " % (MERGED_FIELD,),
                                "%s = " % (MERGED_HEAD_FIELD,)))]
    skipped = len([ln for ln in said if ln.startswith("not done: ")])
    if not record:
        return None
    return _output.success_line(
        said[0], "; %s%s" % ("; ".join(record),
                             "; %d step(s) not done (`--verbose` says why)"
                             % (skipped,) if skipped else ""))


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
    p.add_argument("--override-verdict", dest="override_verdict", default=None,
                   metavar="TEXT")
    return _claude_home.attach_usage_hint(p)


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
        # A STAMP LEFT UNCOMMITTED by an earlier landing is committed by the
        # re-run, so the repair of that state is the command that made it.
        kept = ({} if args.dry_run or filled.get("planUnrestored")
                else commit_landing(args.manifest, args.phase, project, git_root,
                                    names["parent"], branch=names["branch"]))
        out("[close-phase] phase %s landed at %s and %s is gone - %s"
            % (args.phase, phase[MERGED_FIELD], names["branch"],
               "nothing left to merge or clean up" if filled or kept.get(
                   "landingCommits") else "nothing left to do"))
        _render_told(filled, out=out)
        _render_backfill(filled, out=out)
        if kept.get("landingCommitWhy"):
            out("  the stamp is NOT committed: %s" % (kept["landingCommitWhy"],))
        elif kept.get("landingCommitSkipped"):
            out("  the stamp is not committed here: %s"
                % (kept["landingCommitSkipped"],))
        elif kept.get("landingCommits"):
            out("  the stamp committed in %s as %s"
                % (kept.get("landingCommitIn"),
                   ", ".join(c[:12] for c in kept["landingCommits"])))
        return E_FAIL if (filled.get("planUnrestored")
                          or kept.get("landingCommitWhy")) else E_OK
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
    if args.override_verdict is not None and not args.override_verdict.strip():
        sys.stderr.write("ERROR: %s needs the reason - it is what the journal "
                         "records for a landing over a gate verdict that "
                         "refuses it\n" % (_vb.OVERRIDE_FLAG,))
        return E_USAGE
    override = (args.override_verdict or "").strip() or None
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
    # THE VERDICT IS ASKED ONLY OF A LANDING STILL TO HAPPEN. A branch the parent
    # already contains has landed - by an earlier run kept with --keep-branch, a
    # group member before this one, or a hand merge - and a re-run that stamps or
    # cleans up must finish; it says the verdict and refuses nothing.
    gate, signed_without_run, gate_notes = gate_answer(
        project, args.manifest, manifest, phase, git_root=git_root,
        branch=names["branch"], phase_tree=observation.get("phaseTree"))
    refused = _vb.close_refusal(gate, signed_without_run=signed_without_run)
    landing_due = observation["contained"]["answer"] != _wt.CONTAINED
    gate_view = {"state": gate.get("state"), "arm": gate.get("arm"),
                 "sentence": gate.get("sentence"),
                 "runId": (gate.get("row") or {}).get("runId"),
                 "refusal": refused, "landingDue": landing_due,
                 "overridden": bool(refused and landing_due),
                 "overrideReason": override if refused and landing_due else None,
                 "journaled": False, "journalWhy": "",
                 "overrideUnneeded": override is not None and not refused,
                 # A refusal the sign-off's `--no-evidence-reason` answered, said
                 # rather than passed in silence.
                 "honoured": bool(signed_without_run is not None and not refused
                                  and gate.get("arm") in _vb.CLOSE_REFUSING_ARMS
                                  and gate.get("state") == "refused"),
                 "signedAt": (signed_without_run or {}).get("at"),
                 "notes": gate_notes}
    if refused and landing_due and override is None:
        out("[close-phase] REFUSED: phase %s does not land over its newest gate "
            "verdict - %s. Nothing was merged or written." % (args.phase, refused))
        out("           or pass %s \"<why this lands over it>\", which is "
            "journaled as %s" % (_vb.OVERRIDE_FLAG, _vb.ACTION_CLOSE_OVERRIDDEN))
        return E_FAIL
    held = landed_answers_refusal(
        project, args.manifest, phase, landed, names["branch"],
        git_root=git_root, phase_tree=observation.get("phaseTree"),
        refs=(names["parent"], phase.get("baseRef"))) if landing_due else None
    if held:
        out("[close-phase] REFUSED: %s Nothing was merged or written." % (held,))
        return E_FAIL
    if refused and landing_due \
            and not _journal_io.enabled(_journal_io.load_config(project)):
        out("[close-phase] REFUSED: %s was given and journal.enabled is false, so "
            "the landing over its verdict would be recorded nowhere. The verdict: "
            "%s. Nothing was merged or written." % (_vb.OVERRIDE_FLAG, refused))
        return E_FAIL
    # THE EXCEPTION IS JOURNALED BEFORE THE WRITE IT EXCUSES, by the run that
    # lands the branch or hands its merge over, and by no other: a merge that has
    # happened cannot be taken back when the row then fails, so the row comes
    # first and its failure refuses the merge. A preview writes none.
    if gate_view["overridden"]:
        if args.dry_run:
            gate_view["journalWhy"] = ("a dry run writes nothing; the run that "
                                       "lands it journals it as %s first"
                                       % (_vb.ACTION_CLOSE_OVERRIDDEN,))
        elif the_plan["merge"]["mode"] == "refuse":
            gate_view["journalWhy"] = "the merge itself is refused below"
        elif not override_row(project, args.phase, gate, override):
            out("[close-phase] REFUSED: the journal row recording the landing "
                "over its verdict could NOT be written, so nothing was merged or "
                "written. The verdict: %s" % (refused,))
            return E_FAIL
        else:
            gate_view["journaled"] = True
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
            kept = {"stamped": target, "stampManifest": target,
                    "stampedAt": earlier, "stampKept": True,
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
        path, stamp_at, notes = stamp_merged(target, args.phase,
                                             merged_head=merged_head,
                                             project=project_for_row)
        stamp_told = _told(notes, stamp_at)
        if not path:
            return dict(stamp_told, stamped="",
                        stampWhy="" if notes["unrestored"] else stamp_at)
        record_row(project_for_row, args.phase, names["branch"], names["parent"])
        mirrored, mirror_why, mirror_notes = mirror_stub(target, args.phase,
                                                         project_for_row)
        stamped = {"stamped": path, "stampManifest": target,
                   "stampedAt": stamp_at,
                   "mergedHead": merged_head, "mergedHeadWhy": merged_head_why,
                   "stubMirrored": mirrored,
                   "stubWhy": "" if mirror_notes["unrestored"] else mirror_why,
                   "stampedElsewhere": (os.path.abspath(target)
                                        != os.path.abspath(args.manifest)),
                   "parkedOnBranch": _parked_after_merge(target, names["branch"])}
        stamped.update(_merged_told(stamp_told, _told(mirror_notes, mirror_why)))
        return stamped

    code, answer = close(git_root, the_plan, names["branch"], names["parent"],
                         dry_run=args.dry_run,
                         settled_now=settlement(landed or phase, merged=True),
                         stamp=_stamp)
    answer["settledBasis"] = landed_basis
    if answer.get("stamped") and not answer.get("dryRun"):
        answer.update(commit_landing(
            answer.get("stampManifest") or answer["stamped"], args.phase,
            surviving_copy(args.manifest, project, git_root, observation,
                           the_plan, phase_id=args.phase)[1],
            git_root, names["parent"], branch=names["branch"]))
        if answer.get("landingCommitWhy") and code == E_OK:
            code = E_FAIL
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
    answer["gate"] = gate_view

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
    raise SystemExit(_output.terse_cli(main, sys.argv[1:], success_line))
