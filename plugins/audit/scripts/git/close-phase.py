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
human passed the flag. It never deletes a branch that did not reach ITS parent. And
it never runs the second half of a cleanup when the first half was refused.

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
     blocked. The refusal names the path or ref that has to change
  2  usage error -- the manifest will not load, or there is no such phase
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
            composed = _branch.compose(meta, phase, initials=initials)
            branch, bbasis = composed["name"], "composed (%s)" % composed["basis"]
    if parent_arg:
        parent, pbasis = str(parent_arg), "argument (--parent)"
    else:
        resolved = _branch.parent_branch(meta, phase)
        parent, pbasis = resolved["branch"], resolved["basis"]
    return {"branch": branch, "parent": parent, "branchBasis": bbasis,
            "parentBasis": pbasis, "policy": _branch.merge_policy(meta)}


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
        # Where the phase branch points, for the guarded deletion (F249).
        "branchExists": _wt.ref_exists(git_root, branch, run=run),
        "parentTree": parent_tree,
        "phaseTree": phase_tree,
        "parentDirty": parent_dirt,
        "phaseDirty": phase_dirt,
        # Named rather than left as None: this IS an answer, and `cleanup_plan`
        # now refuses on the absent one (F245).
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
    that is in it rather than merely to exist (F246).
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
    verdict = _wt.phase_settled(stamped, _mio.TERMINAL)
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
        # ...AND THE REFUSAL THIS COMMENT USED TO ONLY CLAIM (F249). A no-checkout
        # `git fetch . <b>:<p>` cannot express a merge commit at all, so the flag was
        # silently dropped and the run fast-forwarded and reported success — a
        # different history than the one that was asked for, with nothing saying so.
        # It matters twice over, because `orchestrator.md` makes `--no-ff` the
        # documented remedy for exit 3, and in this topology that remedy could never
        # succeed: the caller loops on 3 forever.
        merge = dict(merge, mode="refuse", argv=[], refusal=_wt._refusal(
            "--no-ff was asked for, and %r is checked out in no worktree - the "
            "merge would have to be a fetch, which cannot make a merge commit"
            % (parent,),
            "check %r out in a worktree and run this again, or drop --no-ff and "
            "accept the fast-forward. This refuses rather than quietly making the "
            "other history" % (parent,)))
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
        # re-asked of `git branch -d`, which grades from HEAD (F249). On the
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

    `stamp` IS CALLED BEFORE THE CLEANUP, and the order is the point (F249). It used
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

    # A REFUSAL OUTRANKS THE SWITCH, and the order used to be the other way round
    # (F249). `auto: false` says "a human will merge this"; a parent branch that
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
        # THE PREVIEW HAS TO PREVIEW THE CLEANUP, and it did not (F249). The plan
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

    # THE FACT `mergedAt` RECORDS IS THIS ONE, not "this run performed a merge"
    # (F249). `merged` is true only on the paths that ran a git write, so an
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


def stamp_merged(manifest_path, phase_id, when=None):
    """Write `phase.mergedAt`. Returns the path written, or "" with a reason.

    THE FIELD IS WRITTEN ONLY AFTER THE PARENT DEMONSTRABLY CONTAINS THE BRANCH, and
    never on the `auto: false` path -- a plan that says a phase merged at a moment it
    did not is worse than a plan that says nothing, because every later reader treats
    it as landed.
    """
    path = _phase_file(manifest_path, phase_id)
    if not path:
        return "", ("no file holds phase %s - the index names no shard for it"
                    % (phase_id,))
    try:
        body = _mio.read_json(path)
    except Exception as exc:
        return "", "%s could not be read: %s" % (path, exc)
    # `datetime.utcnow()` is deprecated from 3.12 and emits a warning onto stderr of
    # every run; the aware spelling below works unchanged on the 3.8 floor, which
    # `datetime.UTC` (3.11+) would not.
    stamp = when or (datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"))
    if isinstance(body, dict) and str(body.get("id")) == str(phase_id):
        body[MERGED_FIELD] = stamp                      # a shard IS the phase
    else:
        found = False
        for ph in ((body or {}).get("phases") or []):
            if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id):
                ph[MERGED_FIELD] = stamp
                found = True
        if not found:
            return "", "phase %s is not in %s" % (phase_id, path)
    try:
        _mio.atomic_write_json(path, body, ensure_ascii=False, indent=2)
    except Exception as exc:
        return "", "%s could not be written: %s" % (path, exc)
    return path, stamp


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
    tree = (observation or {}).get("parentTree")
    if (the_plan or {}).get("merge", {}).get("mode") != "in-parent-worktree" \
            or not tree or not tree.get("path"):
        return manifest_path, project, ""
    if _wt.same_tree(tree.get("path"), git_root):
        return manifest_path, project, ""
    try:
        rel = os.path.relpath(os.path.abspath(manifest_path), git_root)
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
    # is F234 coming back through the other door, so the redirect is now conditional
    # on the destination being able to receive it.
    if phase_id is not None and not _phase_present(moved, phase_id):
        return manifest_path, project, (
            "%s does not carry phase %s, so the stamp stays in the copy this run "
            "was pointed at" % (moved, phase_id))
    return moved, tree.get("path"), ""


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


def record_row(project, phase_id, branch, parent, config=None):
    """Anchor the merge in the trail. FAIL-SOFT, `_journal_io.append`'s contract: a
    merge that HAPPENED must not be reported as not having happened because the trail
    could not be written. `journal-writes.py` cannot see this one -- it is a
    PostToolUse hook over Edit/Write, and this is a script."""
    config = _journal_io.load_config(project) if config is None else config
    return _journal_io.append(project, {
        "action": ACTION_PHASE_MERGED,
        "actor": {"via": "close-phase"},
        "target": str(phase_id),
        "summary": "%s reached %s" % (branch, parent),
        "details": {"phaseId": str(phase_id), "branch": branch,
                    "parent": parent},
    }, config=config)


# --- rendering -------------------------------------------------------------------

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
    for step in answer.get("steps") or []:
        tail = (step["stderr"] or step["stdout"] or "").strip().split("\n")[0]
        out("  git %s -> %s%s" % (" ".join(step["argv"]), step["code"],
                                  ("  %s" % tail) if tail else ""))
    for row in answer.get("blocked") or []:
        out("  not done: %s" % (row["why"],))
        out("            %s" % (row["remedy"],))
    if answer.get("stamped"):
        out("  %s = %s written to %s"
            % (MERGED_FIELD, answer["stampedAt"], answer["stamped"]))
        if answer.get("stampedElsewhere"):
            out("    (that is the copy in the worktree the merge landed in - the "
                "one in this tree is about to be removed)")
    elif answer.get("stampWhy"):
        out("  %s NOT written: %s" % (MERGED_FIELD, answer["stampWhy"]))
    if answer.get("finishFrom"):
        out("  cleanup is not finished. From %s, run:" % (answer["finishFrom"],))
        out("    %s" % (answer["finishCommand"],))


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
    # Through the shared resolver (F257), so `2`, `p2` and `P2` are one phase here
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

    names = resolve(manifest, phase, args.parent, args.branch)
    observation = observe(git_root, names["branch"], names["parent"])
    if observation["why"]:
        out("[close-phase] %s" % (observation["why"],))
        return E_NO_BASIS

    # The observation carries the phase as it stands on disk; the settlement the
    # CLEANUP is judged by is the same question with `mergedAt` supplied by this run.
    observation["settled"] = settlement(phase, merged=False)
    the_plan = plan(observation, names["branch"], names["parent"],
                    names["policy"], want_worktree=args.remove_worktree,
                    want_branch=args.delete_branch, no_ff=args.no_ff)
    def _stamp():
        """Persist `phase.mergedAt`, and report what happened in answer fields.

        Handed to `close()` so it runs between the verified containment and the
        cleanup: the record of a merge must not be contingent on a deletion that
        happens after it (F249).
        """
        target, project_for_row, why = surviving_copy(
            args.manifest, project, git_root, observation, the_plan,
            phase_id=args.phase)
        if not target:
            return {"stamped": "", "stampWhy": why}
        path, stamp_at = stamp_merged(target, args.phase)
        if not path:
            return {"stamped": "", "stampWhy": stamp_at}
        record_row(project_for_row, args.phase, names["branch"], names["parent"])
        return {"stamped": path, "stampedAt": stamp_at,
                "stampedElsewhere": (os.path.abspath(target)
                                     != os.path.abspath(args.manifest))}

    code, answer = close(git_root, the_plan, names["branch"], names["parent"],
                         dry_run=args.dry_run,
                         settled_now=settlement(phase, merged=True),
                         stamp=_stamp)
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
        answer["finishCommand"] = (
            'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/close-phase.py" %s %s '
            '--project .' % (args.manifest, args.phase))

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
