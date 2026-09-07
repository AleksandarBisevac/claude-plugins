#!/usr/bin/env python3
"""
Which worktrees this repository has, whose phase each one is, and what may be reaped.

WHY THIS IS A MODULE AND NOT A PARAGRAPH. `commands/worktree.md` composes a path --
`../<repo>-<phaseId>` -- and then RECORDS IT NOWHERE. No manifest field, no state
file, no lock names where a phase ran, so the only account of a plan's worktrees is
git's own list and until now nothing read it. Residue accumulates in one direction:
`git worktree prune` clears a hand-deleted worktree's record and LEAVES ITS BRANCH,
so every abandoned parallel run deposits an orphan branch nothing could name.

GIT IS THE REGISTRY, NOT THE MANIFEST. A `phase.worktree` field would be a second
source of truth that goes stale the moment somebody moves a directory. `git worktree
list --porcelain` already gives the authoritative (path, branch) pair; the phase is
joined onto it through `phase.branch`. A worktree made by hand, at a path nobody
predicted, is therefore still seen and still judged.

THE WORD IS `contained`, NOT `merged`. `git merge-base --is-ancestor` answers 1 for a
squash-merged branch: the work IS in the parent and the tip is not an ancestor of it.
A report saying "never merged" about that branch would be false, so nothing here says
it.

EVERY QUESTION HAS THREE ANSWERS. Yes, no, and could-not-ask -- and the third is
loud rather than folded into the second. `_doctor_policy.check_branch_naming` shows
the cost of collapsing them: `merged = (out.returncode == 0)` turns exit 128 (a
`parentBranch` this clone does not have) into a definite "is NOT yet merged"
accusation. `merged_into()` is the shape that cannot do that.

I/O IS AT THE EDGE. `parse_list` and every planner below it are pure functions over
text and dicts, so their cases need no `git init` and can drive branches a fixture
cannot reach. The three functions that must ask git take an injectable `run`.

Reads git, never writes it. The plan it returns names the argv a caller would run;
running it is `close-phase.py`'s and `manage-worktrees.py`'s job, and the lock, the
journal row and the revalidation are theirs too.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__worktrees.py`.
"""
import json
import os
import shutil
import subprocess
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

# The three answers `merged_into` gives. Named constants rather than bare strings
# because two of them are substrings of each other -- `"contained" in
# "not-contained"` is True -- and a caller comparing with `in` would read a refusal
# as an approval. Callers compare with `==` against these.
CONTAINED = "contained"
NOT_CONTAINED = "not-contained"
UNKNOWN = "unknown"

# The answer a caller gives `cleanup_plan` when it HAS asked where it is standing and
# the answer is "outside every worktree". It exists because absence used to mean that
# (F245): `cwd_tree=None` skipped the check, so a caller that never asked and a caller
# that asked and got "nowhere" were one value -- and the panel passed the first one
# literally while the CLI passed the second. `owned` and `settled` already refuse on
# an absent answer; this is the third precondition joining them.
CWD_OUTSIDE = "cwd-outside-every-worktree"

# How a merge can be reached. `refuse` is a mode rather than an absence, so a plan
# always has one and a caller never has to tell "no mode" from "not planned yet".
MERGE_MODES = ("already-contained", "in-parent-worktree", "no-checkout", "refuse")

# What the sweep may do, and it may do nothing by default. A verb the caller did not
# name is not performed, which is why this is a set the caller builds rather than a
# flag the sweep infers from "there was something to do".
SWEEP_VERBS = ("removeWorktrees", "deleteBranches", "prune")

# --- provenance ------------------------------------------------------------------
# THE PLUGIN MAY ONLY REAP WHAT THE PLUGIN STARTED. Being able to SEE a worktree and
# being allowed to DELETE it are different questions, and answering the second from
# git alone is what made the first version of this dangerous: a worktree somebody
# opened by hand, or a colleague's, is indistinguishable from ours by branch name and
# merge state.
#
# The record lives in the worktree's OWN admin directory -- `<common>/worktrees/<n>`,
# what `git rev-parse --git-dir` prints from inside it -- and not in the manifest.
# Three properties come from that placement, and the third is the one that matters:
#
#   * git tolerates unknown files there (measured: `worktree list` is unaffected),
#   * it needs no manifest write, so `/audit:worktree` keeps its "never edits the
#     manifest" contract,
#   * IT DIES WITH ITS SUBJECT. `git worktree remove` and `git worktree prune` delete
#     that directory, so a marker can never outlive the worktree it describes and
#     authorise the removal of a DIFFERENT directory that later reuses the path.
PROVENANCE_FILE = "audit-worktree.json"
PROVENANCE_MARK = "audit"


def admin_dir(tree_path, run=None):
    """The worktree's own git-dir, or "" when git will not say.

    Asked git rather than composed from the path: the admin directory's NAME is not
    always the basename of the worktree (git disambiguates a collision by appending),
    and composing it would silently point at another worktree's record.
    """
    fn = _runner(run)
    code, out, _ = fn(tree_path, ["rev-parse", "--git-dir"])
    if code != 0:
        return ""
    path = (out or "").strip()
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.join(tree_path, path)


def read_provenance(tree_path, run=None, expect_branch=None):
    """{"ours", "record", "basis"} -- did THIS plugin create THIS worktree?

    `ours` is True, False, or None when the question could not be put. None is
    treated as NOT ours by every caller, because the whole point is that an
    unanswered question never authorises a deletion -- but it is a distinct value so
    the report can say "could not tell" rather than "somebody else's", which are
    different things to a reader deciding what to do next.

    `expect_branch` IS WHAT MAKES THE ANSWER ABOUT THIS WORKTREE (F246). The marker
    records the phase and the branch it was written for, and only `createdBy` used to
    be read -- so the join from worktree to phase was made purely from whatever branch
    git reports NOW. An operator who runs `git switch` inside a phase worktree to look
    at something hands P1's still-open working directory to P2's settlement verdict,
    and it is removed with the ignored files `dirtiness()` deliberately cannot see.
    Reproduced against a real worktree. Passing None keeps the weaker question, which
    is right for a report that only asks "did we make this at all".
    """
    admin = admin_dir(tree_path, run=run)
    if not admin:
        return {"ours": None, "record": None,
                "basis": "git would not name the admin directory of %s"
                         % (tree_path,)}
    path = os.path.join(admin, PROVENANCE_FILE)
    if not os.path.isfile(path):
        return {"ours": False, "record": None,
                "basis": "no %s in %s - this worktree was not created by the plugin"
                         % (PROVENANCE_FILE, admin)}
    try:
        with open(path, "r") as fh:
            rec = json.load(fh)
    except Exception as exc:
        return {"ours": None, "record": None,
                "basis": "%s could not be read: %s" % (path, exc)}
    if not isinstance(rec, dict) or rec.get("createdBy") != PROVENANCE_MARK:
        return {"ours": False, "record": rec if isinstance(rec, dict) else None,
                "basis": "%s does not carry createdBy=%r" % (path,
                                                             PROVENANCE_MARK)}
    if expect_branch is not None and rec.get("branch") != expect_branch:
        # The marker is ours and describes a DIFFERENT job. Not "somebody else's" and
        # not "could not tell" - a third thing, and the wording has to say which,
        # because the repair is neither "leave it alone" nor "investigate git".
        return {"ours": False, "record": rec,
                "basis": "%s was created by this plugin for phase %r on branch %r, "
                         "and this worktree now holds %r - the marker does not "
                         "describe the work in it"
                         % (path, rec.get("phaseId"), rec.get("branch"),
                            expect_branch)}
    return {"ours": True, "record": rec, "basis": path}


def phase_settled(phase, terminal):
    """{"settled", "why"} -- has the plugin FINISHED with this phase?

    A branch being contained in its parent says the COMMITS are safe. It says nothing
    about whether the plugin is done: a phase can be merged early, or merged and then
    re-opened, or have a task still running while an earlier commit already landed.
    Sign-off is the event that means finished, and it leaves three marks -- so all
    three are asked, and the FIRST failing one is the reason reported.

    `terminal` is the set of statuses that end a task, passed in rather than imported:
    `_manifest_io.TERMINAL` is a layer-mate's, and a second copy of it here would be a
    second opinion about whether a phase is over.
    """
    phase = phase or {}
    status = phase.get("status")
    if status != "done":
        return {"settled": False,
                "why": "phase %s is %r, not 'done' - sign-off has not passed"
                       % (phase.get("id"), status)}
    # AN ENTRY THIS CANNOT READ IS A REFUSAL, NOT A FINISHED TASK (F247). The
    # `isinstance` test used to sit inside the comprehension, where it dropped the
    # item from the OPEN list -- so `"tasks": ["P2.1", "P2.2"]`, or a `tasks` object
    # rather than an array, produced `settled: True` with a `why` that stated "every
    # task is terminal" about a list it had never looked at. `settled` is one of the
    # two permission gates for deleting a working directory, and the sweep does not
    # revalidate the manifest first, so a half-written one reaches this directly.
    tasks = phase.get("tasks") or []
    unreadable = [t for t in tasks if not isinstance(t, dict)]
    if unreadable:
        return {"settled": False,
                "why": "phase %s has %d task entr%s that could not be read as a "
                       "task object (first: %r) - a phase is never called finished "
                       "on a list this cannot see into"
                       % (phase.get("id"), len(unreadable),
                          "y" if len(unreadable) == 1 else "ies", unreadable[0])}
    open_tasks = [str(t.get("id")) for t in tasks
                  if t.get("status") not in terminal]
    if open_tasks:
        return {"settled": False,
                "why": "phase %s still has unfinished task(s): %s"
                       % (phase.get("id"), ", ".join(open_tasks))}
    if not phase.get("mergedAt"):
        return {"settled": False,
                "why": "phase %s records no mergedAt, so nothing says the merge "
                       "happened" % (phase.get("id"),)}
    return {"settled": True,
            "why": "phase %s is done, every task is terminal, and mergedAt is %s"
                   % (phase.get("id"), phase.get("mergedAt"))}


# --- the runner -----------------------------------------------------------------

def _git(git_root, args, timeout=60):
    """(code, stdout, stderr), or (None, "", why) when git could not be run.

    KEEPS BOTH STREAMS ON BOTH PATHS, which is not the shape `_commit_trail._git`
    has. That one sends stderr to DEVNULL because its answers are READS whose
    absence is itself an answer. These answers are consumed by a WRITER, and the two
    commands a writer needs split their output the opposite way from each other:
    `git fetch` writes everything to stderr and nothing to stdout, while `git merge
    --ff-only` on a refusal writes `Aborting` to stderr and `Updating <a>..<b>` to
    stdout. Discarding either stream loses a refusal a human has to act on.

    It cannot borrow `_commit_trail._git` for a second reason: that module is a
    LAYER-MATE at L1, and a sideways edge is the one `_deps.layer_violations()`
    refuses.
    """
    if not shutil.which("git"):
        return (None, "", "git is not on PATH")
    argv = ["git"]
    if git_root:
        argv.extend(["-C", git_root])
    argv.extend(list(args))
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=timeout)
    except Exception as exc:
        return (None, "", "%s" % (exc,))
    return (out.returncode,
            out.stdout.decode("utf-8", "replace"),
            out.stderr.decode("utf-8", "replace"))


def _runner(run):
    """The injected runner, or the real one. One line, named, because every public
    function below takes `run=None` and repeating the conditional is where one of
    them would eventually get it backwards."""
    return run if run is not None else _git


# --- parsing (pure) --------------------------------------------------------------

def _records(text, nul):
    """The raw attribute lines, grouped per worktree, in git's order.

    Both spellings end a record with an EMPTY item -- a blank line in the plain
    form, an extra NUL in the `-z` form -- so one loop reads both and there is no
    second parser to keep agreeing with the first.
    """
    sep = "\0" if nul else "\n"
    out, cur = [], []
    for item in text.split(sep):
        if not nul:
            item = item.rstrip("\r")
        if item == "":
            if cur:
                out.append(cur)
                cur = []
            continue
        cur.append(item)
    if cur:
        out.append(cur)
    return out


def _is_zero_sha(sha):
    """An all-zero HEAD is git's spelling of an UNBORN branch, not a commit.

    A fresh repository's worktree prints forty zeros. Handing that to `rev-parse`
    or to `merge-base` produces `fatal: Not a valid object name`, so it is named
    here and refused there rather than travelling as though it were a SHA. Written
    as "every character is zero" so a sha256 repository's sixty-four zeros are the
    same answer.
    """
    return bool(sha) and set(sha) == set("0")


def parse_list(text, nul=False):
    """The records in `git worktree list --porcelain` output, in git's order.

    EVERY KEY IS ALWAYS PRESENT, so a caller never has to tell "absent" from
    "false":

        path            str, exactly as git printed it (unresolved -- see same_tree)
        head            str SHA, or "" for a bare record
        unborn          True when head is the all-zero SHA
        branch          the short name ("feature/p1"), or None when detached or bare.
                        None and never "" -- a falsy check would otherwise let a
                        detached tree match a lookup for a branch named ""
        ref             the full "refs/heads/..." spelling, or None
        detached        bool
        bare            bool
        locked          bool
        lockReason      str, "" when locked with no reason
        prunable        bool
        prunableReason  str
        isMain          True for the FIRST record only, which is what git's own
                        ordering guarantees

    `locked` IS THE ANSWER AND THE REASON IS DECORATION. git prints a bare `locked`
    line as readily as `locked <why>`, so an implementation that reads the reason as
    the flag misses half the locked worktrees -- and a locked worktree that reads as
    unlocked is one a sweep would try to remove.

    `nul=True` parses the `-z` form. Prefer it wherever the caller can: without it a
    worktree path containing a newline splits into two records and the second is
    garbage.
    """
    out = []
    for index, lines in enumerate(_records(text or "", nul)):
        rec = {"path": "", "head": "", "unborn": False, "branch": None,
               "ref": None, "detached": False, "bare": False,
               "locked": False, "lockReason": "", "prunable": False,
               "prunableReason": "", "isMain": index == 0}
        for line in lines:
            # Split once only: a worktree path may contain spaces, and git does not
            # quote or escape it.
            key, _, rest = line.partition(" ")
            if key == "worktree":
                rec["path"] = rest
            elif key == "HEAD":
                rec["head"] = rest
                rec["unborn"] = _is_zero_sha(rest)
            elif key == "branch":
                rec["ref"] = rest
                rec["branch"] = rest[len("refs/heads/"):] \
                    if rest.startswith("refs/heads/") else rest
            elif key == "detached":
                rec["detached"] = True
            elif key == "bare":
                rec["bare"] = True
            elif key == "locked":
                rec["locked"] = True
                rec["lockReason"] = rest
            elif key == "prunable":
                rec["prunable"] = True
                rec["prunableReason"] = rest
        out.append(rec)
    return out


def parse_error(code, stderr, records=None):
    """Why the list could not be read, or "" when it could.

    A SEPARATE FUNCTION FROM `parse_list` so "git said nothing" and "git said no"
    are two answers rather than one empty list. And an empty parse from a git that
    exited 0 IS an error: the main worktree is always a record, so a healthy
    repository cannot list none. Reporting that as "no worktrees" is the clean sheet
    this whole module exists to avoid, which is why `records` is read here rather
    than left to each caller to remember.
    """
    if code is None:
        return "git could not be run: %s" % ((stderr or "unknown reason").strip(),)
    if code != 0:
        first = (stderr or "").strip().split("\n")[0]
        return first or "git exited %d and said nothing" % (code,)
    if records is not None and not records:
        return ("git listed no worktree at all, which cannot happen in a "
                "repository - the main worktree is always a record")
    return ""


# --- identity (pure, given a resolver) -------------------------------------------

def same_tree(a, b, resolve=None):
    """Do two paths name one directory? `resolve` defaults to os.path.realpath.

    REALPATH AND NOT ABSPATH, and this is not a preference. git prints the RESOLVED
    path even when it was reached through a symlink -- and on macOS `/tmp` and every
    `tempfile.mkdtemp()` are symlinks into `/private`, so an abspath comparison
    answers "different directories" for one directory. It is right on ubuntu and
    wrong on macOS, which is the worst kind of wrong: CI would stay green.

    `resolve` is an ARGUMENT so a case can inject a fake resolver and separate the
    two implementations on every platform, rather than only on the one whose
    filesystem happens to expose the bug.
    """
    fn = resolve if resolve is not None else os.path.realpath
    if not a or not b:
        return False
    try:
        return fn(a) == fn(b)
    except Exception:
        return False


def holder_of(trees, branch, resolve=None):
    """{"tree", "basis"} -- the worktree holding `branch`, and how that is known.

    A PRUNABLE RECORD STILL COUNTS AS A HOLDER. git refuses both `branch -d` and
    `fetch . <b>:<p>` for a branch held by a worktree whose directory was deleted by
    hand -- the errors name a path that no longer exists -- so reporting it as free
    produces a plan git rejects and a message nobody can act on.
    """
    if not branch:
        return {"tree": None, "basis": "no branch to look for"}
    for rec in trees or []:
        if rec.get("branch") == branch:
            return {"tree": rec, "basis": "worktree list names %s at %s"
                    % (branch, rec.get("path"))}
    return {"tree": None,
            "basis": "worktree list names no worktree holding %s" % (branch,)}


def within_tree(root, path, resolve=None):
    """True when `path` IS `root` or sits under it, on resolved paths.

    THE SEPARATOR BOUNDARY IS THE WHOLE POINT, not tidiness: a bare `startswith`
    makes `/x/repo-P1-old` a child of `/x/repo-P1`, and those are two worktrees whose
    only relationship is a shared prefix. Removing one because the caller is in the
    other is the same class of mistake this function exists to prevent.

    AND BOTH SPELLINGS ARE ONE SEPARATOR, which is not a tidy-up either. The two
    sides of this comparison come from different places: git's porcelain prints
    POSIX separators on EVERY platform, while `os.getcwd()` on Windows gives
    backslashes. A boundary built from `os.sep` then compares a slash-spelled root
    against a backslash-spelled cwd and answers False - so on Windows the "do not
    delete the directory you are standing in" guard would go quietly back to never
    firing,
    which is the whole of F245 returning on one platform. Caught by windows-latest
    on the 2.1.1 candidate, which is the second time that leg has found a real
    defect a green macOS run had.
    """
    fn = resolve if resolve is not None else os.path.realpath
    if not root or not path:
        return False
    try:
        a, b = fn(root).replace("\\", "/"), fn(path).replace("\\", "/")
    except Exception:
        return False
    return a == b or b.startswith(a.rstrip("/") + "/")


def standing_in(trees, cwd, resolve=None):
    """The worktree this process is inside, or None.

    `git worktree remove` will delete the tree the caller's cwd is inside --
    measured: silently, exit 0, empty stdout AND empty stderr, and the ignored files
    a `git status` never mentioned go with it. Nothing in git asks the question, so
    this is the only place it can be asked.

    INSIDE, NOT AT (F245). This was realpath EQUALITY, which answered a different
    question than its own docstring asked: from `<worktree>/src` it returned None and
    the guard never fired, so one `cd` into a subdirectory turned the refusal into
    the deletion. Reproduced on a real repository -- clean per `status --porcelain`,
    exit 0, directory and `.env` both gone.

    THE INNERMOST MATCH WINS, because a worktree nested under the main one (`<repo>/
    worktrees/P1`) is inside two records and git resolves such a path to the deeper
    of them. Returning the first would name the main worktree, which is never removed
    anyway -- so the guard would silently stop protecting the linked one.
    """
    best = None
    for rec in trees or []:
        if within_tree(rec.get("path"), cwd, resolve=resolve):
            if best is None or len(str(rec.get("path") or "")) > \
                    len(str(best.get("path") or "")):
                best = rec
    return best


def phase_trees(trees, wanted_branches, resolve=None):
    """{"named", "strangers", "basis"} -- the allow-list, split rather than filtered.

    `wanted_branches` is a branch-name -> phaseId mapping the CALLER built from the
    manifest. `_branch` is a layer-mate and cannot be imported here, so composed
    names arrive as ARGUMENTS -- which is `_ado_tracked`'s constraint and the same
    benefit: this whole classifier is exercised with a dict and no repository.

    `strangers` is the safety property and it is RETURNED rather than dropped. A
    worktree this plan does not name is reported and never touched, the way
    `commit-audit-state` reports foreign staged paths rather than sweeping them in.
    A filter would make the same decision and say nothing about it, and a silent
    skip over somebody's unrelated worktree is indistinguishable from not having
    looked.
    """
    named, strangers = [], []
    wanted = wanted_branches or {}
    for rec in trees or []:
        if rec.get("isMain"):
            continue
        branch = rec.get("branch")
        if branch and branch in wanted:
            row = dict(rec)
            row["phaseId"] = wanted[branch]
            named.append(row)
        else:
            strangers.append(rec)
    return {"named": named, "strangers": strangers,
            "basis": "the plan names %d branch(es); git lists %d linked worktree(s)"
                     % (len(wanted), len(named) + len(strangers))}


# --- questions that need git -----------------------------------------------------

def merged_into(git_root, branch, parent, run=None):
    """{"answer", "basis", "detail"} -- CONTAINED, NOT_CONTAINED or UNKNOWN.

    THREE ANSWERS, NEVER A BOOLEAN, AND UNKNOWN IS THE LOUD ONE. `git merge-base
    --is-ancestor` exits 0 for contained, 1 for not, and 128 when either ref does not
    resolve -- a `parentBranch` absent from this clone, or an unborn HEAD. `code == 0`
    collapses 1 and 128 into one answer, which is the defect live in
    `_doctor_policy.check_branch_naming` today: a missing parent is printed there as
    a definite "is NOT yet merged".

    `detail` carries the squash sentence for NOT_CONTAINED. A squash-merged branch
    is IN the parent and is not an ancestor of it, so a report that turned this
    answer into "the work never landed" would be false about a real and common
    workflow. What was measured is that the tip is not reachable, and that is what
    the line says.
    """
    fn = _runner(run)
    if not branch or not parent:
        return {"answer": UNKNOWN, "detail": "",
                "basis": "no %s to ask about" % ("branch" if not branch
                                                 else "parent branch",)}
    code, _, err = fn(git_root, ["merge-base", "--is-ancestor", branch, parent])
    asked = "git merge-base --is-ancestor %s %s" % (branch, parent)
    if code == 0:
        return {"answer": CONTAINED, "detail": "", "basis": asked}
    if code == 1:
        return {"answer": NOT_CONTAINED,
                "detail": ("the tip of %s is not reachable from %s; a squash merge "
                           "gives this same answer for work that DID land"
                           % (branch, parent)),
                "basis": asked}
    return {"answer": UNKNOWN,
            "detail": (err or "").strip().split("\n")[0],
            "basis": "%s could not be asked" % (asked,)}


def ref_exists(git_root, ref, run=None):
    """{"exists", "sha", "basis"} -- `exists` is True, False, or None for unknown.

    THE PRECONDITION THE NO-CHECKOUT MERGE CANNOT DO WITHOUT. Measured: `git fetch .
    <branch>:<parent>` CREATES `<parent>` when it does not exist, prints
    `* [new branch]` and exits 0. A phase whose `parentBranch` is a typo would
    therefore be reported as successfully merged into a branch that command had just
    invented. `git rev-parse --verify --quiet refs/heads/<name>` exits 0 with the
    SHA or 1 with nothing; anything else is None and the caller refuses.
    """
    fn = _runner(run)
    if not ref:
        return {"exists": False, "sha": "", "basis": "no ref named"}
    full = ref if ref.startswith("refs/") else "refs/heads/%s" % (ref,)
    code, out, _ = fn(git_root, ["rev-parse", "--verify", "--quiet", full])
    asked = "git rev-parse --verify --quiet %s" % (full,)
    if code == 0:
        return {"exists": True, "sha": (out or "").strip(), "basis": asked}
    if code == 1:
        return {"exists": False, "sha": "", "basis": asked}
    return {"exists": None, "sha": "", "basis": "%s could not be asked" % (asked,)}


def dirtiness(tree_path, run=None):
    """{"dirty", "lines", "basis"} -- `dirty` is True, False, or None for unknown.

    None rather than False when git would not describe the tree, because "clean" and
    "unreadable" are the two answers a boolean renders identically -- and the one
    that leads to a `worktree remove` nobody sanctioned.

    IGNORED FILES ARE NOT DIRT HERE, AND THAT MATCHES `git worktree remove`.
    Measured: a worktree holding an ignored `node_modules/` and `build.log` reports
    zero status lines and is removed without complaint. The two agree, and the price
    of that agreement is that removal destroys ignored content -- a `.env` in a
    parallel-run worktree dies with the sweep. That is stated in the refusal text
    rather than left to be discovered.

    `-uall` and not the default: a directory of untracked files collapses to one
    line without it, so the count under-reports exactly where the operator needs the
    names. That is the same correction F224 already made elsewhere in this tree.
    """
    fn = _runner(run)
    code, out, err = fn(tree_path, ["status", "--porcelain", "-uall"])
    asked = "git -C %s status --porcelain -uall" % (tree_path,)
    if code != 0:
        return {"dirty": None, "lines": [],
                "basis": "%s could not be asked: %s"
                         % (asked, (err or "").strip().split("\n")[0])}
    lines = [ln for ln in (out or "").split("\n") if ln.strip()]
    return {"dirty": bool(lines), "lines": lines, "basis": asked}


def list_worktrees(git_root, run=None, nul=True):
    """{"trees", "error", "basis"} -- the composed reader every caller wants.

    Front door rather than a fourth place that remembers to pair `parse_list` with
    `parse_error`. `nul=True` by default, because the newline-safe spelling is the
    right default and the plain one exists for a case that pins the other parser.

    AND IT FALLS BACK, because `-z` is not as old as the command. `git worktree list
    --porcelain` predates it by years; `-z` arrives in 2.36, and Ubuntu 22.04 LTS
    ships 2.34 while Debian 11 ships 2.30. Without a fallback the whole feature -
    every `/audit:worktree` verb, sign-off's cleanup, the panel's table and the
    doctor's residue row - fails on a default LTS install with `unknown switch 'z'`,
    which reads like a broken plugin rather than an old git. The module already
    carries a parser for the newline form and `p10` pins the two equal, so the plain
    spelling is a real answer here rather than a default invented to fill a gap. What
    is lost is newline-safety in a path, and the basis says which spelling answered.
    """
    fn = _runner(run)
    args = ["worktree", "list", "--porcelain"]
    if nul:
        args.append("-z")
    code, out, err = fn(git_root, args)
    if nul and code not in (0, None) and _rejected_z(err, out):
        code, out, err = fn(git_root, ["worktree", "list", "--porcelain"])
        nul = False
    trees = parse_list(out or "", nul=nul) if code == 0 else []
    return {"trees": trees, "error": parse_error(code, err, trees),
            "basis": "git worktree list --porcelain%s" % (" -z" if nul else "",)}


def _rejected_z(err, out):
    """Did git refuse the `-z` FLAG, as opposed to failing at the job?

    Read off the message rather than off the exit code, because git spends 128 and
    129 on several things and "this repository is broken" must not be retried as if
    it were "this git is old". Both spellings git has used are matched, and the test
    is narrowed to a message that also names the option, so a repository error that
    happens to contain the word `usage` is not swallowed.
    """
    text = ("%s %s" % (err or "", out or "")).lower()
    return ("unknown switch" in text or "unknown option" in text
            or "usage: git worktree" in text) and "z" in text


# --- planning the merge (pure, given the answers above) --------------------------

def _refusal(why, remedy):
    """One refusal, in two halves. The remedy is separate from the reason because a
    refusal a reader cannot act on gets routed around, and the thing that has to
    change is usually not the thing that is wrong."""
    return {"why": why, "remedy": remedy}


def merge_plan(trees, branch, parent, contained, parent_exists, parent_dirty,
               dirty_lines=None, cwd_tree=None):
    """{"mode", "where", "argv", "refusal", "basis"} -- HOW this merge must be done,
    decided in full before a single git write.

    Every precondition is validated here, which is `commit-audit-state.py`'s rule
    applied to a merge: a plan that refuses has written nothing, so there is no
    half-made state to unpick.

    THE ORDER OF THE QUESTIONS IS THE DESIGN, not a style:

      1. `contained is UNKNOWN`   -> refuse. A could-not-ask is never a merge, and it
                                     is never a "not merged" either.
      2. `contained is CONTAINED` -> already-contained, zero git writes. ASKED SECOND
                                     AND NOT LAST BECAUSE THE NO-CHECKOUT PATH CANNOT
                                     SEE IT: measured, `git fetch . <b>:<p>` reports
                                     an already-landed phase as
                                     `! [rejected] (non-fast-forward)` exit 1 --
                                     byte-identical to a genuine divergence -- while
                                     `git merge --ff-only` calls the same state
                                     `Already up to date.` exit 0. Two write paths
                                     must not give one repository two verdicts.
      3. parent held by a worktree -> in-parent-worktree. Refuses when that record is
                                     prunable (the directory is gone, so `git -C`
                                     cannot run there) or when the tree is dirty or
                                     unreadable.
      4. parent ref absent         -> refuse. Named apart from every other refusal
                                     because the failure it prevents is silent branch
                                     CREATION, not an error: `git fetch` invents the
                                     target and exits 0.
      5. otherwise                 -> no-checkout. NO leading "+" in the refspec,
                                     ever: the plus is the force spelling, and git's
                                     own fast-forward check is the whole safety of
                                     this path.

    THE DIRTY REFUSAL IS OURS AND SAYS SO. Measured: git fast-forwards over unrelated
    dirt and exits 0, leaving the dirt alone; it refuses only when the merge would
    overwrite the dirty path. Wording this as though git refused would be a claim the
    operator disproves in one command, and a guard disproved once is a guard routed
    around.

    THIS FUNCTION NEVER PLANS A `git switch`. Not only because the worktree case
    forbids it -- it does -- but because moving an operator's HEAD is a side effect no
    script should take on its own, and one path that works from inside a worktree,
    from the main tree and from a bare checkout is worth more than two that differ by
    where they were invoked.
    """
    plan = {"mode": "refuse", "where": None, "argv": [], "refusal": None,
            "basis": ""}

    if contained == UNKNOWN:
        plan["refusal"] = _refusal(
            "whether %r is already contained in %r could not be established"
            % (branch, parent),
            "run `git merge-base --is-ancestor %s %s` and read the error; a merge "
            "is not attempted on an unanswered question" % (branch, parent))
        plan["basis"] = "merged_into answered %s" % (UNKNOWN,)
        return plan

    if contained == CONTAINED:
        plan["mode"] = "already-contained"
        plan["basis"] = ("%r is already contained in %r - nothing to merge, and no "
                         "git write is made" % (branch, parent))
        return plan

    held = holder_of(trees, parent)
    tree = held["tree"]
    if tree is not None:
        if tree.get("prunable"):
            plan["refusal"] = _refusal(
                "%r is checked out at %s, which git reports as prunable - the "
                "directory is gone but the record still holds the branch"
                % (parent, tree.get("path")),
                "clear the record first: `git worktree remove %s` (or `git worktree "
                "prune`), then run this again" % (tree.get("path"),))
            plan["basis"] = held["basis"]
            return plan
        if parent_dirty is None:
            plan["refusal"] = _refusal(
                "the worktree holding %r (%s) could not be described by git, so "
                "whether it is safe to merge into is unknown"
                % (parent, tree.get("path")),
                "run `git -C %s status` and fix what stops it answering"
                % (tree.get("path"),))
            plan["basis"] = held["basis"]
            return plan
        if parent_dirty:
            plan["refusal"] = _refusal(
                "the worktree holding %r (%s) has uncommitted changes: %s"
                % (parent, tree.get("path"),
                   ", ".join(dirty_lines or []) or "reported by git status"),
                "this is the plugin's rule and not git's - git would fast-forward "
                "over unrelated changes and leave them. Commit or stash them so the "
                "sign-off lands in a tree somebody can read")
            plan["basis"] = held["basis"]
            return plan
        plan["mode"] = "in-parent-worktree"
        plan["where"] = tree.get("path")
        plan["argv"] = ["-C", tree.get("path"), "merge", "--ff-only", branch]
        plan["basis"] = held["basis"]
        return plan

    if parent_exists is not True:
        plan["refusal"] = _refusal(
            "%r does not resolve to a branch in this repository" % (parent,)
            if parent_exists is False
            else "whether %r exists could not be established" % (parent,),
            "fix `phase.parentBranch` or `meta.developmentBranch`; the no-checkout "
            "merge would CREATE %r and report success" % (parent,))
        plan["basis"] = "ref_exists answered %r" % (parent_exists,)
        return plan

    plan["mode"] = "no-checkout"
    plan["where"] = None
    plan["argv"] = ["fetch", ".", "%s:refs/heads/%s" % (branch, parent)]
    plan["basis"] = ("%r is checked out nowhere, so it is fast-forwarded without a "
                     "checkout" % (parent,))
    return plan


# --- planning the cleanup (pure) -------------------------------------------------

def cleanup_plan(trees, branch, parent, contained, tree_dirty, dirty_lines=None,
                 cwd_tree=None, want_worktree=True, want_branch=True,
                 resolve=None, owned=None, settled=None, tree=None,
                 branch_sha=None):
    """{"steps", "blocked", "basis"} -- the ordered cleanup, or why each half cannot.

    `steps` IS ORDERED AND THE ORDER IS THE CONTRACT. Worktree removal comes strictly
    before branch deletion, because `git branch -d` refuses with `error: cannot delete
    branch '<b>' used by worktree at '<path>'` for a branch checked out in ANY
    worktree, the current one included. The reverse order is not slower, it is an
    error.

    BRANCH DELETION IS GATED ON `contained`, NEVER ON `git branch -d`. Measured: a
    branch whose declared parent is `develop`, merged only into `main`, is deleted by
    `git branch -d` with exit 0 -- because that safety net grades reachability from
    HEAD, which is a different question from the one the manifest asks. The inverse
    bites too: a branch contained in its parent but not in HEAD is refused for the
    wrong reason. Only `merge-base --is-ancestor <branch> <parent>` asks the
    manifest's question, so only its answer opens this gate.

    Four refusals are worded apart because they are four different repairs, and one of
    them git does not make at all.

    `tree` IS THE RECORD THAT WAS MEASURED, and passing it is how a caller keeps this
    plan about the same directory its answers were about (F244). `git worktree add
    --force <path> <branch>` legally puts two records on one branch; `sweep_plan`
    measures provenance and dirtiness per RECORD, and re-resolving here by branch took
    the FIRST holder instead -- so a plan could keep `/a` as "somebody else's" and
    remove `/a` in the next line, with both safety answers having been about `/b`.
    Omitting it falls back to the lookup, which is right for a caller that only has a
    branch name and only one worktree can hold it.
    """
    steps, blocked = [], []
    held = holder_of(trees, branch)
    tree = held["tree"] if tree is None else tree
    # Every record still on this branch, which is what `git branch -d` actually
    # objects to. Removing one of two holders does not free the branch.
    holders = [r for r in (trees or []) if r.get("branch") == branch]
    removed_here = False

    # FAIL CLOSED. `owned` and `settled` default to None, which means the caller did
    # not establish them, and an unestablished precondition refuses. The alternative
    # -- defaulting to permission -- would make every existing call site reap by
    # omission, which is exactly the accident this pair exists to prevent.
    if want_worktree:
        if not (owned or {}).get("ok"):
            # THE FIRST QUESTION, ahead of containment, because it is about whose
            # directory this is rather than about whether the work is safe. A
            # worktree somebody opened by hand is indistinguishable from ours by
            # branch name and merge state, and deleting it destroys their working
            # copy however cleanly the branch had landed.
            blocked.append(_refusal(
                (owned or {}).get("why")
                or "nothing establishes that this plugin created this worktree",
                "the plugin only removes worktrees it started, which it records "
                "when `/audit:worktree add` creates one. Remove this one by hand "
                "if you meant to: `git worktree remove <path>`"))
        elif not (settled or {}).get("ok"):
            # THE SECOND. Contained says the commits are safe; settled says the
            # plugin is FINISHED - sign-off passed, no task still open, the merge
            # recorded. A phase can be merged early and still be running.
            blocked.append(_refusal(
                (settled or {}).get("why")
                or "nothing establishes that this phase is finished",
                "a worktree is cleanup only once its phase has signed off; until "
                "then it is where the work is"))
        elif contained != CONTAINED:
            # CONTAINMENT GATES THE WORKTREE TOO, and not only the branch. Deleting
            # the directory of a branch that never reached its parent loses no
            # COMMIT -- the branch survives -- but it loses the working tree, and
            # "clean up after the merge" is the whole premise: there was no merge.
            # Asked first among the removal blockers because it is the premise
            # rather than a hazard; the dirty and locked rows below are reasons a
            # justified removal still cannot happen.
            blocked.append(_refusal(
                "%r is not established to be contained in %r (%s), so its worktree "
                "is not cleanup - it is work in progress"
                % (branch, parent, contained),
                "merge it into %r first, or remove the worktree by hand if you "
                "meant to abandon the phase" % (parent,)))
        elif tree is None:
            blocked.append(_refusal(
                "no worktree holds %r, so there is none to remove" % (branch,),
                "nothing to do - this is a report, not a failure"))
        elif tree.get("isMain"):
            blocked.append(_refusal(
                "%r is checked out in the MAIN worktree (%s), which is not a linked "
                "worktree and is never removed" % (branch, tree.get("path")),
                "switch the main worktree to another branch if you want this one "
                "reaped"))
        elif cwd_tree is None:
            # FAIL CLOSED, like `owned` and `settled` one gate up (F245). This used
            # to skip on None, so "the caller never asked where it is standing" and
            # "the caller asked and is outside every worktree" were the same value -
            # and the panel passed the first one literally, which made the panel
            # able to delete the worktree it was being served from.
            blocked.append(_refusal(
                "nothing establishes where this process is standing, and git "
                "removes the directory its caller is sitting in - measured: "
                "silently, exit 0, empty stdout and stderr",
                "pass the answer: `standing_in(trees, os.getcwd())`, or the "
                "CWD_OUTSIDE sentinel when it is outside every worktree"))
        elif cwd_tree is not CWD_OUTSIDE and cwd_tree != CWD_OUTSIDE \
                and within_tree(tree.get("path"),
                                cwd_tree.get("path")
                                if isinstance(cwd_tree, dict) else cwd_tree,
                                resolve=resolve):
            blocked.append(_refusal(
                "this process is standing inside %s, the worktree it was asked to "
                "remove" % (tree.get("path"),),
                "git does NOT ask this - measured, it removes the directory the "
                "caller is sitting in, silently, exit 0. Run this from the main "
                "worktree instead"))
        elif tree.get("locked"):
            blocked.append(_refusal(
                "%s is locked%s" % (tree.get("path"),
                                    ": %s" % (tree.get("lockReason"),)
                                    if tree.get("lockReason") else ""),
                "`git worktree unlock %s` if the lock has outlived its reason"
                % (tree.get("path"),)))
        elif tree_dirty is None:
            blocked.append(_refusal(
                "%s could not be described by git, so whether it holds unsaved work "
                "is unknown" % (tree.get("path"),),
                "run `git -C %s status` and fix what stops it answering; a worktree "
                "is never removed on an unanswered question" % (tree.get("path"),)))
        elif tree_dirty:
            blocked.append(_refusal(
                "%s holds uncommitted work: %s"
                % (tree.get("path"), ", ".join(dirty_lines or [])
                   or "reported by git status"),
                "commit it, or remove the worktree by hand with --force once you "
                "have read it. Note that removal also destroys IGNORED files - a "
                ".env or a node_modules under this path goes with it, and git "
                "status never mentioned them"))
        else:
            steps.append({"action": "worktree-remove",
                          "argv": ["worktree", "remove", tree.get("path")],
                          "why": "%r is contained in %r and %s is clean"
                                 % (branch, parent, tree.get("path"))})
            removed_here = True

    if want_branch:
        if not (settled or {}).get("ok"):
            # A BRANCH IS NOT DELETED BEFORE ITS PHASE IS FINISHED EITHER, and the
            # asymmetry with the worktree above is deliberate: this half does NOT
            # ask about provenance. The plan naming the branch IS the provenance -
            # `phase.branch` is written by the orchestrator at phase entry - and a
            # merged branch is recoverable from the reflog, which a deleted working
            # copy is not.
            blocked.append(_refusal(
                (settled or {}).get("why")
                or "nothing establishes that this phase is finished",
                "a branch is deleted once its phase has signed off and the merge "
                "is recorded, not merely once the commits are reachable"))
        elif contained != CONTAINED:
            blocked.append(_refusal(
                "%r is not established to be contained in %r (%s)"
                % (branch, parent, contained),
                "`git branch -d` would not stop this - measured, it grades against "
                "HEAD and deletes a branch that never reached its declared parent. "
                "Merge it into %r first" % (parent,)))
        elif [r for r in holders
              if not (removed_here and same_tree(r.get("path"),
                                                 tree.get("path")
                                                 if tree else None,
                                                 resolve=resolve))]:
            # EVERY holder, not the one this plan happened to look at. Two records
            # can share a branch, and removing one of them leaves git refusing the
            # deletion for the other - which is the right refusal, said here rather
            # than discovered as a raw `error:` at the shell.
            _rest = [r for r in holders
                     if not (removed_here and same_tree(r.get("path"),
                                                        tree.get("path")
                                                        if tree else None,
                                                        resolve=resolve))]
            blocked.append(_refusal(
                "%r is still checked out at %s"
                % (branch, ", ".join(str(r.get("path")) for r in _rest)),
                "the worktree must go first; git refuses with `cannot delete branch "
                "%r used by worktree at %r`" % (branch, _rest[0].get("path"))))
        else:
            # NOT `git branch -d` WHEN WE CAN DO BETTER, and this is measured rather
            # than preferred (F249). After a `no-checkout` merge the parent is by
            # construction checked out nowhere, so HEAD is not the parent - and
            # `branch -d` grades from HEAD. Driven on a real repository: a branch
            # proven contained in `develop` by `merge-base --is-ancestor` is refused
            # with `error: the branch 'feature/p1' is not fully merged`, exit 1,
            # AFTER its worktree has already been removed. That leaves the orphan
            # branch this module's opening docstring exists to eliminate, and it
            # accuses a branch that landed.
            #
            # `update-ref -d <ref> <oldvalue>` is not `-D`. It deletes only if the
            # ref still points where we looked, so it refuses exactly what a force
            # delete would not: a branch that moved under us. The schema's rule is
            # about never discarding unmerged work, and containment is already
            # established by the question the manifest asks. Without a sha there is
            # nothing to guard on, so the old command stays as the fallback.
            if branch_sha:
                steps.append({"action": "branch-delete",
                              "argv": ["update-ref", "-d",
                                       "refs/heads/%s" % (branch,), branch_sha],
                              "why": "%r is contained in %r, nothing holds it any "
                                     "more, and it still points at %s"
                                     % (branch, parent, branch_sha[:12])})
            else:
                steps.append({"action": "branch-delete",
                              "argv": ["branch", "-d", branch],
                              "why": "%r is contained in %r, and nothing holds it "
                                     "any more (no sha to guard on, so git's own "
                                     "HEAD-graded check is the fallback)"
                                     % (branch, parent)})

    return {"steps": steps, "blocked": blocked,
            "basis": "%s; contained=%s" % (held["basis"], contained)}


# --- planning a sweep (pure) -----------------------------------------------------

def observe_for_sweep(git_root, trees, wanted_branches, parent_of,
                      phase_by_branch=None, terminal=(), run=None,
                      resolve=None):
    """{"contained", "dirty", "owned", "settled"} -- the four questions a sweep needs.

    FOUR AND NOT TWO, and the two that were added are the ones that decide whether a
    deletion is ALLOWED rather than whether it is safe. `contained` and `dirty` say
    the work would survive; `owned` says whose directory it is, and `settled` says
    whether the plugin has finished with it. A sweep that asked only the first pair
    would reap a colleague's worktree whose branch happened to be merged.

    ONE PLACE, because there are two callers: `manage-worktrees.py sweep` and the
    panel's sweep endpoint. A panel that asked git its own way would be a second
    opinion about which worktrees may go, and the panel is the surface where the
    button is -- so the disagreement would be discovered by whoever pressed it.

    The panel cannot reach `manage-worktrees.py` to borrow the loop: that is an
    entry point at layer 7 and the panel sits below it, which is the edge
    `_deps.layer_violations()` refuses. The shared answer therefore lives HERE, at
    the floor, where both can reach down to it.
    """
    contained, dirty, owned, settled, shas = {}, {}, {}, {}, {}
    for rec in phase_trees(trees, wanted_branches, resolve=resolve)["named"]:
        branch = rec.get("branch")
        parent = (parent_of or {}).get(branch) or ""
        # Where the branch points RIGHT NOW, so the deletion can be guarded on it
        # rather than re-asked of git's HEAD-graded `branch -d` (F249).
        shas[branch] = ref_exists(git_root, branch, run=run).get("sha") or ""
        contained[branch] = merged_into(git_root, branch, parent,
                                        run=run)["answer"]
        dirty[rec.get("path")] = dirtiness(rec.get("path"), run=run)
        # The branch is what binds the marker to the work now in the tree (F246).
        # This is the observation the sweep's permission gate reads, so it asks the
        # narrow question; the report in `_panel_composition` asks the wide one.
        prov = read_provenance(rec.get("path"), run=run, expect_branch=branch)
        owned[rec.get("path")] = {"ok": prov["ours"] is True,
                                  "why": prov["basis"], "record": prov["record"]}
        phase = (phase_by_branch or {}).get(branch)
        if phase is None:
            # NO PHASE, NO SETTLEMENT. A branch the plan does not describe cannot be
            # shown to be finished, and "we could not tell" is refused rather than
            # waved through - which is the whole difference between this and the
            # `--include-strangers` flag it replaces.
            settled[branch] = {"ok": False,
                               "why": "no phase in this plan carries branch %r, so "
                                      "nothing says the work on it is finished"
                                      % (branch,)}
        else:
            verdict = phase_settled(phase, terminal or ())
            settled[branch] = {"ok": verdict["settled"], "why": verdict["why"]}
    return {"contained": contained, "dirty": dirty, "owned": owned,
            "settled": settled, "shas": shas}


def sweep_plan(trees, wanted_branches, parent_of, contained_by_branch,
               dirty_by_path, cwd_tree=None, verbs=None, resolve=None,
               owned_by_path=None, settled_by_branch=None, sha_by_branch=None):
    """{"examined", "actions", "kept", "strangers", "empty", "basis"}.

    `examined` IS A COUNT AND IT IS ALWAYS REPORTED, and `empty` is a separate field
    rather than an empty `actions` list. "There was no linked worktree to look at" and
    "every worktree was examined and none needed anything" are two states of the
    world that a falsy list renders identically, and only one of them describes a
    repository somebody should feel good about. `commit-audit-state` words the same
    pair apart; this is that rule on a filesystem.

    `kept` CARRIES A REASON PER WORKTREE LEFT ALONE -- dirty, locked, not contained,
    could-not-ask -- so a sweep that did nothing says why for each, rather than
    printing a number and letting the reader infer health.

    `verbs` is a set the CALLER builds. A verb it does not name is not performed:
    "sweep everything" is not something this function infers from having found
    something to do.
    """
    verbs = set(verbs or ())
    split = phase_trees(trees, wanted_branches, resolve=resolve)
    actions, kept = [], []

    for rec in split["named"]:
        branch = rec.get("branch")
        parent = (parent_of or {}).get(branch) or ""
        contained = (contained_by_branch or {}).get(branch, UNKNOWN)
        dirt = (dirty_by_path or {}).get(rec.get("path")) or {}
        owned = (owned_by_path or {}).get(rec.get("path"))
        settled = (settled_by_branch or {}).get(branch)
        plan = cleanup_plan(
            trees, branch, parent, contained,
            dirt.get("dirty"), dirt.get("lines"),
            cwd_tree=cwd_tree,
            want_worktree="removeWorktrees" in verbs,
            want_branch="deleteBranches" in verbs,
            # THE RECORD, not the branch (F244). `owned` and `dirt` above were both
            # read at `rec`'s path; handing the branch over instead let the plan act
            # on a different record carrying the same branch, judged by this one's
            # answers.
            resolve=resolve, owned=owned, settled=settled, tree=rec,
            branch_sha=(sha_by_branch or {}).get(branch))
        row = {"path": rec.get("path"), "branch": branch,
               "ours": (owned or {}).get("ok"),
               "settled": (settled or {}).get("ok"),
               "phaseId": rec.get("phaseId"), "parent": parent,
               "contained": contained, "dirty": dirt.get("dirty"),
               "dirtyLines": dirt.get("lines") or []}
        if plan["steps"]:
            actions.append(dict(row, steps=plan["steps"], blocked=plan["blocked"]))
        else:
            kept.append(dict(row, reasons=plan["blocked"]))

    if "prune" in verbs and any(r.get("prunable") for r in trees or []):
        actions.append({"path": None, "branch": None, "phaseId": None,
                        "parent": None, "contained": None, "dirty": None,
                        "dirtyLines": [],
                        "steps": [{"action": "worktree-prune",
                                   "argv": ["worktree", "prune"],
                                   "why": "git reports at least one prunable record; "
                                          "note that prune clears the RECORD and "
                                          "leaves the branch"}],
                        "blocked": []})

    examined = len(split["named"]) + len(split["strangers"])
    return {"examined": examined,
            "actions": actions,
            "kept": kept,
            "strangers": split["strangers"],
            "empty": examined == 0,
            "basis": split["basis"]}


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_worktrees.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__worktrees.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
