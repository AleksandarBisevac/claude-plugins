#!/usr/bin/env python3
"""The worktrees this plan owns: what exists, what to add, what may be reaped.

WHY THIS EXISTS. `commands/worktree.md` was prose too, and its gap is different from
the sign-off's: it composes a path -- `../<repo>-<phaseId>` -- and then RECORDS IT
NOWHERE. No manifest field, no state file, no lock names where a phase ran, so the
only account of a plan's worktrees is git's own list and until now nothing read it.
The residue accumulates in one direction: `git worktree prune` clears a hand-deleted
worktree's record and LEAVES ITS BRANCH, so every abandoned parallel run deposits an
orphan branch no command could name, let alone judge.

THE SWEEP IS READ-ONLY BY DEFAULT AND THAT IS NOT TIMIDITY. Measured: `git worktree
remove` destroys IGNORED files without complaint -- a worktree holding
`node_modules/` and a `build.log` reports zero `status --porcelain` lines and is
removed silently. A `.env` in a parallel-run worktree dies with the sweep. That is a
consequence to publish, not a reason to narrow the sweep, and the answer to it is an
explicit verb.

IT REFUSES ON TWO AXES, NOT ONE. A branch being contained in its parent says the
COMMITS are safe; it says nothing about the working tree. The 2026-08-26 hand-prune
in this project's own history is the worked example: every branch was merged and the
worktrees still held unstaged edits, which is why that prune cost six hundred lines
of evidence written by hand before anyone dared run it. So a worktree is swept only
when its branch is contained AND its tree is clean, and everything else is KEPT with
the reason printed beside it.

AND IT MAY ONLY TOUCH WHAT THE PLAN NAMES. The branch names come from `_branch` over
this manifest's phases; every worktree git lists that is not on that list is REPORTED
as a stranger and left alone. That is `commit-audit-state`'s rule -- build the
allow-list, read the state back, refuse rather than widen -- transposed onto a
filesystem.

Usage:
  manage-worktrees.py list   <manifest> [--project DIR] [--json]
  manage-worktrees.py add    <manifest> <phaseId> [--project DIR] [--path DIR]
  manage-worktrees.py remove <manifest> <phaseId> [--project DIR] [--force]
  manage-worktrees.py sweep  <manifest> [--project DIR] [--apply]
                             [--remove-worktrees] [--delete-branches] [--prune]
  manage-worktrees.py task-add    <manifest> <taskId> --base SHA [--project DIR]
                                  [--path DIR]
  manage-worktrees.py task-remove <manifest> <taskId> [--project DIR] [--force]

  A TASK TREE is a worktree for one task of a parallel wave: detached at `--base`
  (the phase HEAD), OUTSIDE the project directory, and marked with the task it
  belongs to. `task-add` refuses a root inside the project, and hands back a tree
  already marked for the task (at the base its marker records) instead of making a
  second one, running its setup again unless the marker says it completed;
  `task-remove` takes down
  only a tree whose marker names THIS task, refuses a dirty one without `--force`,
  and the sweep never removes one.

  The verb is mandatory and `sweep` without `--apply` is the read-only half -- the
  same grammar `/audit:logs prune` already uses. `--apply` needs at least one of the
  three verbs; `--apply` alone is a usage error, because "sweep everything" is not
  something this command infers.

Exit codes:
  0  it ran, and it printed how many worktrees it examined
  1  it could not: git refused, or a precondition failed. The reason names a path
  2  usage error -- unknown verb, no such phase, `--apply` with no verb
  4  it could not be ASKED -- git would not describe the worktrees. NOT 0 with an
     empty list: an unreadable list rendered as "no worktrees" is the clean sheet
     this whole file exists to avoid
  6  `task-add` only: the tree exists and is marked, but the declared
     `executor.worktreeSetup` failed or timed out in it. COULD-NOT-RUN -- not a red,
     and no attempt is spent on it. The answer carries the setup's exit code, its
     duration and the tail of its output
  5  THERE WAS NOTHING TO EXAMINE -- git listed no linked worktree, or none whose
     branch this plan names. Its own sentinel, and the one that matters most: a
     sweep that examined nothing and a sweep that examined every worktree and found
     all of them healthy are otherwise the same exit code and very nearly the same
     sentence, and only one of them describes a repository somebody should feel
     good about
"""
import argparse
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import time

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
import _manifest_io as _mio                                          # noqa: E402
import _worktrees as _wt                                             # noqa: E402

E_OK, E_FAIL, E_USAGE, E_NO_BASIS, E_NOTHING = 0, 1, 2, 4, 5
# `task-add` made the tree and the declared setup did not complete in it. Its own
# code: the task never ran, so it is neither a red nor a spent attempt, and folding
# it into E_FAIL would make "the environment is broken" read as "the code is".
E_SETUP = 6

SETUP_TIMEOUT = 900
# What a task marker records of its setup: `pending` from the moment the marker is
# written until the setup returns, then `run_setup`'s status. A tree is handed
# back as it stands only when that status is a completed one; `kept` is the
# status an adopted tree reports for a setup it did not run again.
SETUP_PENDING, SETUP_KEPT = "pending", "kept"
SETUP_COMPLETE = ("ran", "none")
INCLUDE_FILE = ".worktreeinclude"
# Never COPIED, and never linked in its place: a dependency tree is the setup
# command's to install, and a task that adds a dependency must not change its
# siblings' trees.
NEVER_COPY = ("node_modules",)

VERBS = ("list", "add", "remove", "sweep", "task-add", "task-remove")

# The two do-nothing outcomes, worded APART because they are different states of the
# world and a reader acts on them differently. Folded into one line they would both
# read as "all clear", and only one of them is a repository somebody should feel good
# about.
NOTHING_TO_EXAMINE = ("no linked worktree belongs to this plan, so nothing was "
                      "examined. This is not the same as 'everything is clean' - "
                      "there was nothing to be clean.")
ALL_HEALTHY = ("every worktree this plan names was examined and none needed "
               "anything.")
# ...and the THIRD do-nothing state, which the first two do not cover: worktrees
# exist, they were all examined, and not one of them belongs to this plan. Saying
# ALL_HEALTHY there would be a clean sheet about directories nothing is entitled to
# judge - which is precisely the reading that made an adopt-everything flag look
# reasonable.
NONE_ARE_OURS = ("linked worktrees exist and NONE of them belongs to this plan, so "
                 "nothing here may be swept. Take one down by hand when you want it "
                 "gone: `remove --path <dir>`.")


# --- the plan's own branches -----------------------------------------------------

# ONE ANSWER FOR EVERY VERB, AND FOR THE PANEL'S SWEEP TOO: `_branch.branch_of`
# is below both, so neither can name a phase's branch differently. Each verb reads
# `user_name` once, off `_wt.git_user_name`.
branch_of = _branch.branch_of
_branches = _branch.plan_branches


def wanted_branches(manifest, user_name):
    """{branchName: phaseId} -- the allow-list, built from the plan and nothing else."""
    return dict((made["name"], str(phase.get("id")))
                for phase, made in _branches(manifest, user_name) if made["name"])


def parents_of(manifest, user_name):
    """{branchName: parentBranch} -- where each of those branches is supposed to land.

    Per PHASE and not one global answer, because `phase.parentBranch` exists exactly
    so a phase can integrate somewhere else. A sweep that asked "is it in the
    development branch" would keep a phase that had correctly landed on its story
    branch, for ever.
    """
    return dict((made["name"], made["parent"])
                for _phase, made in _branches(manifest, user_name) if made["name"])


def phases_by_branch(manifest):
    """{branchName: phase} -- the phase behind each branch, for the settled question.

    The PHASE and not a flag: `phase_settled` reports WHICH of the three marks is
    missing, and a boolean computed here would leave that sentence to be reinvented
    by every caller.
    """
    out = {}
    for phase in ((manifest or {}).get("phases") or []):
        if isinstance(phase, dict) and phase.get("branch"):
            out[str(phase["branch"])] = phase
    return out


def default_path(git_root, phase_id):
    """`../<repo>-<phaseId>` -- the convention `commands/worktree.md` states in prose.

    The phase id is used for the directory name and is SANITISED here, which the
    prose never did: an id carrying a path separator would compose a path outside the
    intended parent, and `migrate-manifest.py` already does the same check for shard
    filenames. Anything that is not a plain identifier character becomes a hyphen.
    """
    safe = "".join(c if (c.isalnum() or c in "._-") else "-"
                   for c in str(phase_id))
    # A component made only of dots is the one shape that still travels: `..` as a
    # WHOLE component walks up, and every other appearance of a dot is an ordinary
    # character in an ordinary name. The prefix below already prevents it, and this
    # says so rather than leaving a reader to work out why.
    safe = safe.strip(".-") or "phase"
    base = os.path.basename(os.path.abspath(git_root))
    return os.path.join(os.path.dirname(os.path.abspath(git_root)),
                        "%s-%s" % (base, safe))


# --- the verbs -------------------------------------------------------------------

def do_list(git_root, manifest, run=None):
    """(exit, answer) -- every worktree, and which phase it belongs to."""
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    user_name = _wt.git_user_name(git_root, run=run)
    wanted = wanted_branches(manifest, user_name)
    parents = parents_of(manifest, user_name)
    split = _wt.phase_trees(listing["trees"], wanted)
    rows = []
    for rec in split["named"]:
        parent = parents.get(rec.get("branch")) or ""
        contained = _wt.merged_into(git_root, rec.get("branch"), parent, run=run)
        dirt = _wt.dirtiness(rec.get("path"), run=run)
        rows.append({"path": rec.get("path"), "branch": rec.get("branch"),
                     "phaseId": rec.get("phaseId"), "parent": parent,
                     "contained": contained["answer"],
                     "dirty": dirt["dirty"], "dirtyLines": dirt["lines"],
                     "locked": rec.get("locked"),
                     "prunable": rec.get("prunable")})
    missing = [b for b in wanted
               if not any(r["branch"] == b for r in rows)]
    return E_OK, {"rows": rows, "strangers": split["strangers"],
                  "missing": sorted(missing), "examined": len(rows)}


def do_add(git_root, manifest, phase_id, path=None, run=None):
    """(exit, answer) -- create the worktree, after asking OUR questions first.

    Git's own refusals arrive with three different exit codes -- a non-empty target
    is 128, `-b` on an existing branch is 255, a branch checked out elsewhere is 128
    -- so the preflight is here rather than left to the reader of a raw git error.
    An EMPTY directory is accepted by git and is not an error here either.
    """
    fn = _wt._runner(run)
    meta = (manifest or {}).get("meta") or {}
    phase = None
    for ph in ((manifest or {}).get("phases") or []):
        if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id):
            phase = ph
    if phase is None:
        return E_USAGE, {"error": "no phase %r in this plan" % (phase_id,)}
    # THE NAME `start` WILL EXPECT, through the one answer it is composed by. This
    # composed without initials while `resolve-branch.py` read git user.name, so a
    # template carrying `{initials}` checked out one name here and resolved another
    # there - and a phase started in this worktree would not recognise its branch.
    made = branch_of(meta, phase, _wt.git_user_name(git_root, run=run))
    branch, parent = made["name"], made["parent"]
    target = path or default_path(git_root, phase_id)

    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    held = _wt.holder_of(listing["trees"], branch)["tree"]
    if held is not None and held.get("isMain"):
        # The main tree is never a worktree to remove, so the remedy is the switch
        # that frees the branch there - `main_tree_release`'s answer, not a second.
        release = _wt.main_tree_release(listing["trees"], branch, parent, held)
        return E_FAIL, {"error": "%r is checked out in the MAIN worktree (%s)"
                                 % (branch, held.get("path")),
                        "remedy": "run the phase there, or free the branch: from %s "
                                  "run `%s`%s" % (release["from"],
                                                  release["commands"][0],
                                                  " - which %s" % (release["note"],)
                                                  if release["note"] else "")}
    if held is not None:
        return E_FAIL, {"error": "%r is already checked out at %s"
                                 % (branch, held.get("path")),
                        "remedy": "run the phase there, or remove that worktree "
                                  "first"}
    if os.path.isdir(target) and os.listdir(target):
        return E_FAIL, {"error": "%s already exists and is not empty" % (target,),
                        "remedy": "pass --path to name somewhere else, or clear it "
                                  "by hand once you have read it"}
    exists = _wt.ref_exists(git_root, branch, run=run)["exists"]
    argv = ["worktree", "add", target] + ([] if exists else ["-b", branch]) \
        + ([branch] if exists else [parent])
    code, out, err = fn(git_root, argv)
    if code is None:
        return E_NO_BASIS, {"error": err, "argv": argv}
    if code != 0:
        return E_FAIL, {"error": (err or out or "").strip(), "argv": argv}
    # THE MARKER IS WRITTEN HERE AND NOWHERE ELSE, which is what makes it mean
    # something: the only worktrees the sweep will ever reap are the ones that came
    # through this line. It goes in the worktree's own admin directory, so it dies
    # with the worktree and cannot outlive it to authorise removing whatever next
    # occupies the path.
    marker, why = write_provenance(target, phase_id, branch, run=run)
    return E_OK, {"path": target, "branch": branch, "parent": parent,
                  "created": not exists, "argv": argv,
                  "provenance": marker,
                  "provenanceWhy": why,
                  "note": ("this worktree is recorded as the plugin's, so sign-off "
                           "may clean it up"
                           if marker else
                           "the plugin could NOT record that it created this "
                           "worktree (%s), so nothing will reap it automatically - "
                           "which is the safe direction, and you remove it by hand"
                           % (why,))}


def do_remove(git_root, manifest, phase_id, force=False, run=None, path=None):
    """(exit, answer) -- remove ONE worktree, our questions before git's.

    `--path` names a directory directly, and it is the ONLY way to remove a worktree
    the plugin did not create. That is not a loophole in the provenance rule, it is
    the shape of consent: a human named this exact directory, once, in an argument.
    What the sweep may never do is DECIDE that for a worktree it did not start.

    Every other refusal still applies on that path - dirty, locked, standing in it -
    because those are about losing work rather than about whose work it is.
    """
    fn = _wt._runner(run)
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    branch = None
    if path:
        tree = None
        for rec in listing["trees"]:
            if _wt.same_tree(rec.get("path"), path) and not rec.get("isMain"):
                tree = rec
        if tree is None:
            return E_USAGE, {"error": "no linked worktree at %r" % (path,),
                             "remedy": "`/audit:worktree list` prints the paths git "
                                       "knows about"}
        branch = tree.get("branch")
    else:
        wanted = wanted_branches(manifest, _wt.git_user_name(git_root, run=run))
        for name, pid in wanted.items():
            if str(pid) == str(phase_id):
                branch = name
        if branch is None:
            return E_USAGE, {"error": "no phase %r in this plan" % (phase_id,),
                             "remedy": "name a phase this plan carries, or use "
                                       "--path to remove a worktree by directory"}
        tree = _wt.holder_of(listing["trees"], branch)["tree"]
    if tree is None:
        return E_FAIL, {"error": "no worktree holds %r" % (branch,),
                        "remedy": "nothing to remove - this is a report, not a "
                                  "failure"}
    if tree.get("isMain"):
        # ASKED BEFORE EVERY OTHER REFUSAL, `--path`'s rule on this arm too: the
        # main tree is never removed, and a later refusal answering for it - the
        # one about where this process stands - reads as how to try again.
        phase = ([ph for ph in (manifest.get("phases") or [])
                  if isinstance(ph, dict) and str(ph.get("id")) == str(phase_id)]
                 or [{}])[0]
        parent = _branch.parent_branch(manifest.get("meta") or {}, phase)["branch"]
        release = _wt.main_tree_release(listing["trees"], branch, parent, tree)
        return E_FAIL, {
            "error": "%r is checked out in the MAIN worktree (%s), which is not a "
                     "linked worktree and is never removed" % (branch,
                                                               tree.get("path")),
            "remedy": "nothing to remove. To free the branch, from %s run %s%s"
                      % (release["from"],
                         ", then ".join("`%s`" % c for c in release["commands"]),
                         " - which %s" % (release["note"],)
                         if release["note"] else "")}
    standing = _wt.standing_in(listing["trees"], os.getcwd())
    if standing is not None and _wt.same_tree(standing.get("path"),
                                              tree.get("path")):
        return E_FAIL, {"error": "this process is standing inside %s"
                                 % (tree.get("path"),),
                        "remedy": "git does NOT ask this - it removes the caller's "
                                  "own directory, silently, exit 0. Run it from "
                                  "somewhere else"}
    dirt = _wt.dirtiness(tree.get("path"), run=run)
    if dirt["dirty"] is None and not force:
        return E_FAIL, {"error": "%s could not be described by git"
                                 % (tree.get("path"),),
                        "remedy": "an unanswered question is not a clean tree"}
    if dirt["dirty"] and not force:
        return E_FAIL, {"error": "%s holds uncommitted work: %s"
                                 % (tree.get("path"), ", ".join(dirt["lines"])),
                        "remedy": "commit it, or pass --force once you have read "
                                  "it. Removal also destroys IGNORED files - a "
                                  ".env or a node_modules under this path goes "
                                  "with it, and git status never mentioned them"}
    argv = ["worktree", "remove"] + (["--force"] if force else []) \
        + [tree.get("path")]
    code, out, err = fn(git_root, argv)
    if code is None:
        return E_NO_BASIS, {"error": err, "argv": argv}
    if code != 0:
        return E_FAIL, {"error": (err or out or "").strip(), "argv": argv}
    return E_OK, {"removed": tree.get("path"), "branch": branch,
                  "argv": argv,
                  "note": "the BRANCH is untouched - `git worktree remove` never "
                          "deletes one, and `prune` does not either"}


# `adopt_strangers` USED TO BE HERE, and removing it is the point of this section.
#
# It widened the sweep past the branches the plan names and judged the adopted
# worktrees against `meta.developmentBranch` - a guess at a parent they never
# declared. It was added because the strict sweep found nothing on the repository
# that dogfoods this plugin: every linked worktree there was a stranger, because
# parallel agent sessions and hand `git worktree add` calls do not go through the
# plan. That was a real observation and the wrong conclusion drawn from it.
#
# A worktree somebody opened by hand, or a colleague's, is indistinguishable from
# ours by branch name and merge state - so a flag that adopts on those two signals
# alone deletes other people's working copies on the strength of a guess. The backlog
# it was reaching for is a HUMAN's to clear, and `remove --path` is how: one
# directory, named by the person who wants it gone.
#
# What replaced it is provenance: `add` records that this plugin created a worktree,
# and only a worktree carrying that record is ever reaped automatically.


def _write_record(tree_path, record, run=None):
    """The marker file for `record`, in the worktree's own admin directory. Returns
    the file, or "" + why -- the one writer, so a phase marker and a task marker
    cannot disagree about where the record lives."""
    admin = _wt.admin_dir(tree_path, run=run)
    if not admin:
        return "", "git would not name the admin directory of %s" % (tree_path,)
    path = os.path.join(admin, _wt.PROVENANCE_FILE)
    try:
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record, indent=1, sort_keys=True))
            fh.write("\n")
    except Exception as exc:
        return "", "%s could not be written: %s" % (path, exc)
    return path, ""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_provenance(tree_path, phase_id, branch, run=None):
    """Record that this plugin created this worktree. Returns the file, or "" + why.

    FAIL-SOFT ON THE WRITE, FAIL-CLOSED ON THE READ. A worktree that was created and
    whose marker could not be written is one the sweep will decline to remove later -
    which is the safe direction, and the caller says so rather than pretending the
    worktree is unusable.
    """
    return _write_record(tree_path, {"createdBy": _wt.PROVENANCE_MARK,
                                     "phaseId": str(phase_id),
                                     "branch": str(branch), "at": _now()}, run=run)


# --- task trees ------------------------------------------------------------------

def _find_task(manifest, task_id):
    """(phaseId, task) for `task_id`, or (None, None)."""
    for ph in ((manifest or {}).get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for task in (ph.get("tasks") or []):
            if isinstance(task, dict) and str(task.get("id")) == str(task_id):
                return str(ph.get("id")), task
    return None, None


def read_worktree_setup(project):
    """(command, why) -- `executor.worktreeSetup` from the project's config.

    (None, "") when there is no config or no such key: nothing was declared, and
    that is an answer. (None, reason) when the file exists and cannot be read --
    "unreadable" must not collapse into "no setup", because the tree would then be
    handed out without the environment the operator asked for and nothing would say
    so. A value that is not a non-empty string is refused the same way.
    """
    path = os.path.join(project or ".", ".claude", "audit.config.json")
    if not os.path.isfile(path):
        return None, ""
    try:
        with io.open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as exc:
        return None, "%s is unreadable (%s), so executor.worktreeSetup is unknown" % (
            path, exc)
    block = cfg.get("executor") if isinstance(cfg, dict) else None
    if not isinstance(block, dict) or "worktreeSetup" not in block:
        return None, ""
    cmd = block["worktreeSetup"]
    if not isinstance(cmd, str) or not cmd.strip():
        return None, "executor.worktreeSetup in %s must be a non-empty string" % (path,)
    return cmd, ""


def _included_files(git_root):
    """(paths, why) -- untracked files that `.worktreeinclude` lists AND git ignores.

    The format is Claude Code's (docs: code.claude.com/docs/en/worktrees, "Copy
    gitignored files into worktrees"): `.gitignore` syntax, and only a file that
    matches a pattern and is also gitignored is copied. Matching is git's own
    (`ls-files --others --ignored --exclude-from`), not a second implementation of
    gitignore; the ignored half is `check-ignore`, because a listed pattern also
    matches untracked files that nothing ignores.
    """
    spec = os.path.join(git_root, INCLUDE_FILE)
    if not os.path.isfile(spec):
        return [], ""
    try:
        listed = subprocess.run(
            ["git", "-C", git_root, "ls-files", "-z", "--others", "--ignored",
             "--exclude-from=%s" % (spec,)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if listed.returncode != 0:
            return [], "git ls-files failed: %s" % (
                listed.stderr.decode("utf-8", "replace").strip(),)
        if not listed.stdout:
            return [], ""
        ign = subprocess.run(["git", "-C", git_root, "check-ignore", "-z", "--stdin"],
                             input=listed.stdout, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=120)
    except Exception as exc:
        return [], "%s" % (exc,)
    # check-ignore exits 1 when NOTHING matched, which is an answer, not a failure.
    if ign.returncode not in (0, 1):
        return [], "git check-ignore failed: %s" % (
            ign.stderr.decode("utf-8", "replace").strip(),)
    return sorted(p for p in ign.stdout.decode("utf-8", "replace").split("\0") if p), ""


def copy_worktree_include(git_root, target):
    """{copied, skipped, error} -- the listed ignored files, copied into `target`.

    A skip is NAMED, never dropped: a symlink is not followed out of the project and
    a path under a never-copy directory is the setup command's to provide.
    """
    paths, why = _included_files(git_root)
    out = {"copied": [], "skipped": [], "error": why}
    for rel in paths:
        parts = rel.replace("\\", "/").split("/")
        src = os.path.join(git_root, *parts)
        if any(part in NEVER_COPY for part in parts):
            out["skipped"].append("%s (a dependency tree is the setup command's)" % rel)
            continue
        if os.path.islink(src) or not os.path.isfile(src):
            out["skipped"].append("%s (not a regular file)" % rel)
            continue
        dest = os.path.join(target, *parts)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
        except Exception as exc:
            out["skipped"].append("%s (%s)" % (rel, exc))
            continue
        out["copied"].append("/".join(parts))
    return out


def run_setup(command, cwd, timeout=SETUP_TIMEOUT):
    """{command, status, exitCode, seconds, output} -- `command` run in `cwd`.

    `status` is one of none | ran | failed | timeout. `cwd` is the TREE, always: the
    caller passes the task tree, so an install lands there and the project is never
    the working directory. The duration is a monotonic clock around the child, and
    it is measured for a failure too -- a setup that burns its timeout and dies is
    the figure the cost ceiling most needs.
    """
    if not command:
        return {"command": None, "status": "none", "exitCode": None,
                "seconds": 0.0, "output": ""}
    began = time.monotonic()
    try:
        done = subprocess.run(command, shell=True, cwd=cwd, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        status, code, out = ("ran" if done.returncode == 0 else "failed",
                             done.returncode, done.stdout)
    except subprocess.TimeoutExpired as exc:
        status, code, out = "timeout", None, exc.stdout or b""
    except Exception as exc:
        status, code, out = "failed", None, ("%s" % (exc,)).encode("utf-8")
    text = out.decode("utf-8", "replace").strip()
    return {"command": command, "status": status, "exitCode": code,
            "seconds": round(time.monotonic() - began, 3),
            "output": text[-2000:]}


def do_task_add(git_root, manifest, task_id, base, project=None, path=None, run=None,
                setup=None, setup_timeout=SETUP_TIMEOUT):
    """(exit, answer) -- a detached worktree at `base` for one task, outside the project.

    Every refusal is asked BEFORE git is called, and `base` is resolved to a full
    commit first: a ref name would move under a tree that is meant to stay at the
    phase HEAD it was cut from. The root is judged against the project directory AND
    the git root -- a tree inside either is judged as the project by the plan gate,
    which is what a task tree exists to avoid.
    """
    fn = _wt._runner(run)
    phase_id, task = _find_task(manifest, task_id)
    if task is None:
        return E_USAGE, {"error": "no task %r in this plan" % (task_id,)}
    if not base:
        return E_USAGE, {"error": "task-add needs --base <sha>: a task tree is cut "
                                  "from a named commit, never from a default"}
    target = os.path.abspath(path or default_path(git_root, task_id))
    for root in (project, git_root):
        if root and _wt.within_tree(os.path.abspath(root), target):
            return E_FAIL, {"error": "%s is inside the project (%s)"
                                     % (target, os.path.abspath(root)),
                            "remedy": "a task tree lives OUTSIDE the project "
                                      "directory; pass --path to a sibling of it"}
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    # A tree already marked for this task is ADOPTED, never refused and never
    # doubled: the marker is written before the environment goes in, so a run
    # that died in between, a setup that failed, and a tree a closed wave kept
    # for a blocked task are all found here, by the marker, and resumed.
    for rec in listing["trees"]:
        if rec.get("isMain") or not rec.get("path"):
            continue
        held = _wt.read_provenance(rec.get("path"), run=run, expect_task=str(task_id))
        if held["ours"] is True:
            return adopt_task_tree(git_root, rec.get("path"), held, setup,
                                   setup_timeout, run=run)
    if os.path.isdir(target) and os.listdir(target):
        return E_FAIL, {"error": "%s already exists and is not empty" % (target,),
                        "remedy": "pass --path to name somewhere else, or clear it "
                                  "by hand once you have read it"}
    code, out, err = fn(git_root, ["rev-parse", "--verify", "--quiet",
                                   "%s^{commit}" % (base,)])
    if code is None:
        return E_NO_BASIS, {"error": err}
    sha = (out or "").strip()
    if code != 0 or not sha:
        return E_FAIL, {"error": "--base %r does not name a commit in %s"
                                 % (base, git_root)}
    argv = ["worktree", "add", "--detach", target, sha]
    code, out, err = fn(git_root, argv)
    if code is None:
        return E_NO_BASIS, {"error": err, "argv": argv}
    if code != 0:
        return E_FAIL, {"error": (err or out or "").strip(), "argv": argv}
    record = {"createdBy": _wt.PROVENANCE_MARK, "phaseId": phase_id,
              "taskId": str(task_id), "base": sha,
              "phaseTree": os.path.abspath(git_root), "at": _now(),
              "setup": SETUP_PENDING}
    marker, why = _write_record(target, record, run=run)
    answer = {"path": target, "task": str(task_id), "phaseId": phase_id,
              "base": sha, "argv": argv, "provenance": marker,
              "provenanceWhy": why,
              "note": ("marked for task %s, so `task-remove` may take it down"
                       % (task_id,) if marker else
                       "the plugin could NOT record the task marker (%s), so "
                       "`task-remove` will not take this tree down; remove it "
                       "by hand" % (why,))}
    return provision(git_root, target, record, answer, setup, setup_timeout, run=run)


def provision(git_root, target, record, answer, setup, setup_timeout, run=None):
    """(exit, answer) -- the include and the setup put into a marked tree, and
    the setup's outcome written back into its marker.

    The environment goes in AFTER the marker (a failed setup leaves a tree that
    `task-remove` can still take down) and the include BEFORE the setup (a setup
    may need the `.env` the include brings). The marker says `pending` until the
    setup returns, so a run that dies in between leaves a tree the next
    `task-add` provisions again rather than one it hands out half-made.
    """
    included = copy_worktree_include(git_root, target)
    ran = run_setup(setup, target, timeout=setup_timeout)
    if answer.get("provenance"):
        _write_record(target, dict(record, setup=ran["status"]), run=run)
    answer = dict(answer, include=included, setup=ran)
    if ran["status"] in ("failed", "timeout"):
        # COULD-NOT-RUN, not red: the task's code never executed in this tree, so
        # nothing about the task is known and no attempt is spent on it.
        answer["couldNotRun"] = True
        answer["spendsAttempt"] = False
        answer["error"] = ("the setup command %s in %s after %.1fs%s; the tree is "
                           "kept and marked" % (
                               "timed out" if ran["status"] == "timeout"
                               else "exited %s" % (ran["exitCode"],),
                               target, ran["seconds"],
                               ": " + ran["output"][-300:] if ran["output"] else ""))
        return E_SETUP, answer
    return E_OK, answer


def adopt_task_tree(git_root, path, held, setup, setup_timeout, run=None):
    """(exit, answer) -- the tree already marked for this task, handed back at
    the base its marker records, with its setup run again unless the marker
    says the setup completed. A marker from before the setup was recorded says
    nothing about it, so it is provisioned again too."""
    record = held["record"]
    answer = {"path": os.path.abspath(path), "task": record.get("taskId"),
              "phaseId": record.get("phaseId"), "base": record.get("base"),
              "adopted": True, "provenance": held["basis"], "provenanceWhy": "",
              "note": "adopted: the tree marked for task %s already exists"
                      % (record.get("taskId"),)}
    if record.get("setup") in SETUP_COMPLETE:
        return E_OK, dict(answer, include=None, setup={
            "command": setup, "status": SETUP_KEPT, "exitCode": None,
            "seconds": 0.0, "output": "", "recorded": record.get("setup")})
    return provision(git_root, path, record, answer, setup, setup_timeout, run=run)


def do_task_remove(git_root, manifest, task_id, force=False, run=None):
    """(exit, answer) -- remove the tree whose marker names THIS task.

    Found by marker, not by path: the path is a default a caller may have overridden,
    and a marker for another task is not ours to remove. The refusals are `remove`'s:
    dirty, unreadable, and the tree the process stands in.
    """
    fn = _wt._runner(run)
    if _find_task(manifest, task_id)[1] is None:
        return E_USAGE, {"error": "no task %r in this plan" % (task_id,)}
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    tree, others = None, []
    for rec in listing["trees"]:
        if rec.get("isMain") or not rec.get("path"):
            continue
        prov = _wt.read_provenance(rec.get("path"), run=run, expect_task=str(task_id))
        if prov["ours"] is True:
            tree = rec
        elif (prov["record"] or {}).get("taskId"):
            others.append("%s (task %s)" % (rec.get("path"), prov["record"]["taskId"]))
    if tree is None:
        return E_FAIL, {"error": "no worktree is marked for task %r" % (task_id,),
                        "remedy": "nothing to remove%s"
                                  % ("; task trees that exist belong to other tasks: "
                                     + ", ".join(others) if others else "")}
    standing = _wt.standing_in(listing["trees"], os.getcwd())
    if standing is not None and _wt.same_tree(standing.get("path"), tree.get("path")):
        return E_FAIL, {"error": "this process is standing inside %s"
                                 % (tree.get("path"),),
                        "remedy": "git does NOT ask this - it removes the caller's "
                                  "own directory, silently, exit 0. Run it from "
                                  "somewhere else"}
    dirt = _wt.dirtiness(tree.get("path"), run=run)
    if dirt["dirty"] is None and not force:
        return E_FAIL, {"error": "%s could not be described by git" % (tree.get("path"),),
                        "remedy": "an unanswered question is not a clean tree"}
    if dirt["dirty"] and not force:
        return E_FAIL, {"error": "%s holds uncommitted work: %s"
                                 % (tree.get("path"), ", ".join(dirt["lines"])),
                        "remedy": "integrate or commit it, or pass --force once you "
                                  "have read it. Removal also destroys IGNORED files"}
    argv = ["worktree", "remove"] + (["--force"] if force else []) + [tree.get("path")]
    code, out, err = fn(git_root, argv)
    if code is None:
        return E_NO_BASIS, {"error": err, "argv": argv}
    if code != 0:
        return E_FAIL, {"error": (err or out or "").strip(), "argv": argv}
    return E_OK, {"removed": tree.get("path"), "task": str(task_id), "argv": argv}


def do_sweep(git_root, manifest, verbs, apply_it=False, run=None):
    """(exit, answer) -- what may go, what stays and why, and (with --apply) the doing."""
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    trees = listing["trees"]
    user_name = _wt.git_user_name(git_root, run=run)
    wanted = wanted_branches(manifest, user_name)
    parents = parents_of(manifest, user_name)
    development = (((manifest or {}).get("meta") or {})
                   .get("developmentBranch") or _branch.DEFAULT_PARENT)
    obs = _wt.observe_for_sweep(git_root, trees, wanted, parents,
                                phase_by_branch=phases_by_branch(manifest),
                                terminal=_mio.TERMINAL, run=run,
                                status_of=_mio.effective_phase_status)
    the_plan = _wt.sweep_plan(trees, wanted, parents, obs["contained"],
                             obs["dirty"],
                             # `standing_in` answering None means "outside every
                             # worktree", which is a MEASUREMENT; passing it through
                             # as None would now read as "never asked" and refuse,
                             # so it is named.
                             cwd_tree=(_wt.standing_in(trees, os.getcwd())
                                       or _wt.CWD_OUTSIDE),
                             verbs=verbs, owned_by_path=obs["owned"],
                             settled_by_branch=obs["settled"],
                             sha_by_branch=obs["shas"],
                             task_by_path=obs["tasks"])
    the_plan["applied"] = []
    the_plan["development"] = development
    if the_plan["empty"]:
        return E_NOTHING, the_plan
    if not apply_it:
        return E_OK, the_plan
    fn = _wt._runner(run)
    for action in the_plan["actions"]:
        for step in action["steps"]:
            code, out, err = fn(git_root, step["argv"])
            if code is None:
                the_plan["error"] = err
                return E_NO_BASIS, the_plan
            if code != 0:
                the_plan["error"] = (err or out or "").strip()
                return E_FAIL, the_plan
            the_plan["applied"].append({"action": step["action"],
                                        "path": action.get("path"),
                                        "branch": action.get("branch")})
    return E_OK, the_plan


# --- rendering -------------------------------------------------------------------

def render(verb, answer, out=print):
    if answer.get("error"):
        out("[worktrees] %s" % (answer["error"],))
        if answer.get("remedy"):
            out("            %s" % (answer["remedy"],))
        return
    if verb == "list":
        for row in answer["rows"]:
            out("  %-14s %-28s %s" % (row["phaseId"], row["branch"], row["path"]))
            out("      into %s: %s%s%s"
                % (row["parent"] or "(none)", row["contained"],
                   "  DIRTY(%d)" % (len(row["dirtyLines"]),) if row["dirty"]
                   else ("  dirtiness unknown" if row["dirty"] is None else ""),
                   "  LOCKED" if row["locked"] else ""))
        for rec in answer["strangers"]:
            out("  (stranger)     %-28s %s"
                % (rec.get("branch") or "(detached)", rec.get("path")))
        for name in answer["missing"]:
            out("  (no worktree)  %s" % (name,))
        out("  examined %d worktree(s) this plan names" % (answer["examined"],))
        return
    if verb == "sweep":
        if answer.get("empty"):
            out("[worktrees] %s" % (NOTHING_TO_EXAMINE,))
            return
        for action in answer["actions"]:
            for step in action["steps"]:
                out("  %s git %s" % ("ran:  " if answer.get("applied")
                                     else "would run:", " ".join(step["argv"])))
        for row in answer["kept"]:
            out("  keeping %s (%s)" % (row["path"], row["branch"]
                                       or "task %s" % (row.get("taskId"),)))
            for why in row["reasons"]:
                out("      %s" % (why["why"],))
        for rec in answer["strangers"]:
            out("  not this plan's: %s" % (rec.get("path"),))
        if not answer["actions"]:
            # ALL_HEALTHY is about the worktrees this plan NAMES, and saying it over
            # a repository whose linked worktrees are all strangers reads as a clean
            # sheet about directories nothing looked at. So the two are worded apart
            # here as well as in the empty case.
            named = answer["examined"] - len(answer["strangers"])
            out("  %s" % (ALL_HEALTHY if named else NONE_ARE_OURS,))
        out("  examined %d worktree(s), %d of them this plan's"
            % (answer["examined"],
               answer["examined"] - len(answer["strangers"])))
        return
    for key in ("path", "task", "base", "branch", "parent", "removed", "note"):
        if answer.get(key):
            out("  %-8s %s" % (key + ":", answer[key]))
    inc = answer.get("include")
    if inc is not None:
        out("  include: %d file(s) copied%s" % (
            len(inc["copied"]), "; " + inc["error"] if inc["error"] else ""))
        for item in inc["skipped"]:
            out("           skipped %s" % (item,))
    ran = answer.get("setup")
    if ran is not None:
        out("  setup:   %s" % ("none configured (executor.worktreeSetup is absent)"
                              if ran["status"] == "none" else
                              "completed when the tree was made (%s); not run "
                              "again" % (ran.get("recorded"),)
                              if ran["status"] == SETUP_KEPT else
                              "%s in %.1fs: %s" % (ran["status"], ran["seconds"],
                                                   ran["command"])))


# --- cli -------------------------------------------------------------------------

def build_parser():
    """One subparser per verb, so a flag parses only under the verb that acts on it.

    A single flat parser accepted `add --apply` and `list --force` in silence: the
    usage scoped them to one verb and the parser to none, and a flag the verb never
    reads is an ask that is dropped without a word.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("manifest")
    common.add_argument("--project", default=".")
    common.add_argument("--json", dest="as_json", action="store_true")
    p = argparse.ArgumentParser(prog="manage-worktrees.py",
                                description="The worktrees this plan owns.")
    sub = p.add_subparsers(dest="verb", metavar="{%s}" % ",".join(VERBS))
    sub.required = True
    sub.add_parser("list", parents=[common],
                   help="every worktree, and which phase it belongs to")
    add = sub.add_parser("add", parents=[common],
                         help="create the worktree for one phase")
    add.add_argument("phase")
    add.add_argument("--path", default=None)
    rm = sub.add_parser("remove", parents=[common],
                        help="remove one worktree, by phase or by --path")
    rm.add_argument("phase", nargs="?", default=None)
    rm.add_argument("--path", default=None)
    rm.add_argument("--force", action="store_true")
    ta = sub.add_parser("task-add", parents=[common],
                        help="a detached worktree at --base for one task, outside "
                             "the project")
    ta.add_argument("task")
    ta.add_argument("--base", default=None)
    ta.add_argument("--path", default=None)
    tr = sub.add_parser("task-remove", parents=[common],
                        help="remove the worktree marked for one task")
    tr.add_argument("task")
    tr.add_argument("--force", action="store_true")
    sw = sub.add_parser("sweep", parents=[common],
                        help="what may be reaped, read-only unless --apply, "
                             "which only sweep takes")
    sw.add_argument("--apply", dest="apply_it", action="store_true")
    sw.add_argument("--remove-worktrees", dest="rm_wt", action="store_true")
    sw.add_argument("--delete-branches", dest="rm_br", action="store_true")
    sw.add_argument("--prune", action="store_true")
    # `--include-strangers` was here and is deliberately gone; see the section above
    # `write_provenance`. Removing a worktree the plugin did not create is `remove
    # --path <dir>`: one directory, named by the person who wants it gone.
    return _claude_home.attach_usage_hint(p)


def verbs_from(args):
    """The sweep verbs the caller named, as a tuple. Empty is a real answer and the
    caller refuses on it -- `--apply` with nothing named is a usage error, not an
    invitation to guess."""
    out = []
    if getattr(args, "rm_wt", False):
        out.append("removeWorktrees")
    if getattr(args, "rm_br", False):
        out.append("deleteBranches")
    if getattr(args, "prune", False):
        out.append("prune")
    return tuple(out)


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
    if args.verb == "task-add" and not args.base:
        sys.stderr.write("ERROR: task-add needs --base <sha>\n")
        return E_USAGE
    if args.verb == "add" and not args.phase:
        sys.stderr.write("ERROR: add needs a phase id\n")
        return E_USAGE
    if args.verb == "remove" and not args.phase and not args.path:
        sys.stderr.write("ERROR: remove needs a phase id, or --path <dir> for a "
                         "worktree this plan does not name\n")
        return E_USAGE

    verbs = verbs_from(args)
    if args.verb == "sweep" and args.apply_it and not verbs:
        sys.stderr.write(
            "ERROR: --apply needs at least one of --remove-worktrees, "
            "--delete-branches, --prune. 'sweep everything' is not inferred.\n")
        return E_USAGE

    project = os.path.abspath(args.project)
    meta_root = ((manifest.get("meta") or {}).get("gitRoot") or ".")
    git_root = os.path.abspath(os.path.join(project, meta_root))
    if not shutil.which("git"):
        out("[worktrees] git is not on PATH, so nothing about this repository's "
            "worktrees can be established. Nothing was changed.")
        return E_NO_BASIS

    if args.verb == "list":
        code, answer = do_list(git_root, manifest)
    elif args.verb == "add":
        code, answer = do_add(git_root, manifest, args.phase, path=args.path)
    elif args.verb == "task-add":
        setup, setup_why = read_worktree_setup(project)
        if setup_why:
            out("[worktrees] %s" % (setup_why,))
            return E_FAIL
        code, answer = do_task_add(git_root, manifest, args.task, args.base,
                                   project=project, path=args.path, setup=setup)
    elif args.verb == "task-remove":
        code, answer = do_task_remove(git_root, manifest, args.task,
                                      force=args.force)
    elif args.verb == "remove":
        code, answer = do_remove(git_root, manifest, args.phase,
                                 force=args.force, path=args.path)
    else:
        code, answer = do_sweep(git_root, manifest,
                                verbs or ("removeWorktrees", "deleteBranches"),
                                apply_it=args.apply_it)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True, default=str))
    else:
        render(args.verb, answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        print("manage-worktrees.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_manage_worktrees.py - run that file "
              "instead.")
        sys.exit(0)
    raise SystemExit(main(sys.argv[1:]))
