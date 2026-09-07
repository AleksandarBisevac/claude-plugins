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
import _manifest_io as _mio                                          # noqa: E402
import _worktrees as _wt                                             # noqa: E402

E_OK, E_FAIL, E_USAGE, E_NO_BASIS, E_NOTHING = 0, 1, 2, 4, 5

VERBS = ("list", "add", "remove", "sweep")

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

def wanted_branches(manifest, initials=None):
    """{branchName: phaseId} -- the allow-list, built from the plan and nothing else.

    A phase's RECORDED branch wins over a composed one: a phase that ran has the name
    git actually got, and re-composing could produce a different string for a
    manifest whose convention changed mid-flight. Composing is the fallback for a
    phase that has not started, so `add` can be told about a worktree before there is
    a branch to record.
    """
    meta = (manifest or {}).get("meta") or {}
    out = {}
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        pid = str(phase.get("id"))
        recorded = phase.get("branch")
        name = str(recorded) if recorded else _branch.compose(
            meta, phase, initials=initials)["name"]
        if name:
            out[name] = pid
    return out


def parents_of(manifest):
    """{branchName: parentBranch} -- where each of those branches is supposed to land.

    Per PHASE and not one global answer, because `phase.parentBranch` exists exactly
    so a phase can integrate somewhere else. A sweep that asked "is it in the
    development branch" would keep a phase that had correctly landed on its story
    branch, for ever.
    """
    meta = (manifest or {}).get("meta") or {}
    out = {}
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        recorded = phase.get("branch")
        name = str(recorded) if recorded else _branch.compose(meta, phase)["name"]
        if name:
            out[name] = _branch.parent_branch(meta, phase)["branch"]
    return out


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
    wanted = wanted_branches(manifest)
    parents = parents_of(manifest)
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
    recorded = phase.get("branch")
    branch = str(recorded) if recorded else _branch.compose(meta, phase)["name"]
    parent = _branch.parent_branch(meta, phase)["branch"]
    target = path or default_path(git_root, phase_id)

    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    held = _wt.holder_of(listing["trees"], branch)["tree"]
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
        wanted = wanted_branches(manifest)
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


def write_provenance(tree_path, phase_id, branch, run=None):
    """Record that this plugin created this worktree. Returns the file, or "" + why.

    FAIL-SOFT ON THE WRITE, FAIL-CLOSED ON THE READ. A worktree that was created and
    whose marker could not be written is one the sweep will decline to remove later -
    which is the safe direction, and the caller says so rather than pretending the
    worktree is unusable.
    """
    admin = _wt.admin_dir(tree_path, run=run)
    if not admin:
        return "", "git would not name the admin directory of %s" % (tree_path,)
    path = os.path.join(admin, _wt.PROVENANCE_FILE)
    record = {"createdBy": _wt.PROVENANCE_MARK, "phaseId": str(phase_id),
              "branch": str(branch),
              "at": datetime.datetime.now(datetime.timezone.utc)
              .strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record, indent=1, sort_keys=True))
            fh.write("\n")
    except Exception as exc:
        return "", "%s could not be written: %s" % (path, exc)
    return path, ""


def do_sweep(git_root, manifest, verbs, apply_it=False, run=None):
    """(exit, answer) -- what may go, what stays and why, and (with --apply) the doing."""
    listing = _wt.list_worktrees(git_root, run=run)
    if listing["error"]:
        return E_NO_BASIS, {"error": listing["error"]}
    trees = listing["trees"]
    wanted = wanted_branches(manifest)
    parents = parents_of(manifest)
    development = (((manifest or {}).get("meta") or {})
                   .get("developmentBranch") or _branch.DEFAULT_PARENT)
    obs = _wt.observe_for_sweep(git_root, trees, wanted, parents,
                                phase_by_branch=phases_by_branch(manifest),
                                terminal=_mio.TERMINAL, run=run)
    the_plan = _wt.sweep_plan(trees, wanted, parents, obs["contained"],
                             obs["dirty"],
                             # `standing_in` answering None means "outside every
                             # worktree", which is a MEASUREMENT; passing it through
                             # as None would now read as "never asked" and refuse
                             # (F245), so it is named.
                             cwd_tree=(_wt.standing_in(trees, os.getcwd())
                                       or _wt.CWD_OUTSIDE),
                             verbs=verbs, owned_by_path=obs["owned"],
                             settled_by_branch=obs["settled"],
                             sha_by_branch=obs["shas"])
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
            out("  keeping %s (%s)" % (row["path"], row["branch"]))
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
    for key in ("path", "branch", "parent", "removed", "note"):
        if answer.get(key):
            out("  %-8s %s" % (key + ":", answer[key]))


# --- cli -------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="manage-worktrees.py",
                                description="The worktrees this plan owns.")
    p.add_argument("verb", choices=VERBS)
    p.add_argument("manifest")
    p.add_argument("phase", nargs="?", default=None)
    p.add_argument("--project", default=".")
    p.add_argument("--path", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--apply", dest="apply_it", action="store_true")
    p.add_argument("--remove-worktrees", dest="rm_wt", action="store_true")
    p.add_argument("--delete-branches", dest="rm_br", action="store_true")
    p.add_argument("--prune", action="store_true")
    # `--include-strangers` was here and is deliberately gone; see the section above
    # `write_provenance`. Removing a worktree the plugin did not create is `remove
    # --path <dir>`: one directory, named by the person who wants it gone.
    p.add_argument("--json", dest="as_json", action="store_true")
    return p


def verbs_from(args):
    """The sweep verbs the caller named, as a tuple. Empty is a real answer and the
    caller refuses on it -- `--apply` with nothing named is a usage error, not an
    invitation to guess."""
    out = []
    if args.rm_wt:
        out.append("removeWorktrees")
    if args.rm_br:
        out.append("deleteBranches")
    if args.prune:
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
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("manage-worktrees.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_manage_worktrees.py - run that file "
              "instead.")
        sys.exit(0)
    raise SystemExit(main(sys.argv[1:]))
