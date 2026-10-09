#!/usr/bin/env python3
"""
Which copy holds a phase in flight live - read once, the same way, for every surface that shows one.

A phase being worked on in another worktree, or under a lock on a branch this
checkout does not have out, is not what this checkout's files say about it: the
run there marks tasks done before any commit here carries them. `/audit:status`,
the panel and the rendered report all show such a phase, and they must read it
the same way, or two of them would disagree about what is ready. So the reader
lives here and nowhere else, and `_status_facts.live_view` is the pure half
that lays what it read over the plan and names each copy.

WHY THIS LAYER. The reader asks git through `_scoped_commit.run_git`, whose
stderr is the `why` in every sentence it writes, and places a phase's file
through `_invariants`. That puts it one layer above `_scoped_commit`, which is
the highest layer `audit-status`, `render-report` and `panel-server` can all
import from. `_panel_state` sits below it, so `build_state` takes the reader as
an argument (`live=`) that `panel-server` supplies - the injection
`render-report` already uses for the gate verdict - and a payload built without
one says it shows this checkout's copy.

WHAT IT DOES NOT DECIDE. Which facts a surface takes from the overlaid plan is
the surface's call: the gate, the bug counts and the resume advice read this
checkout's own copy, because they certify or advise about it. This module only
reads, and names the copy it read.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__live_copy.py` - see `plugins/audit/tests/_harness.py`.
The cases that drive it through `/audit:status` stay in `test_audit_status.py`.
"""
import json
import os
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

import _manifest_io as _mio  # noqa: E402  (TERMINAL, effective_phase_status)
import _status_facts  # noqa: E402  (readiness_projection and the phase-lock prefix)
import _invariants  # noqa: E402  (phase_of, manifest_files, git_root_for)
import _locks  # noqa: E402  (which phase locks are held, and whether a holder is alive)
import _branch  # noqa: E402  (what a phase's own branch is called - one answer for every surface)
import _worktrees  # noqa: E402  (which worktree has a phase branch out, and the ref probe)
import _scoped_commit  # noqa: E402  (the stderr-keeping git runner a branch copy is read through)


# --- reading one copy -------------------------------------------------------------
def _phase_body(doc, phase_id):
    """The phase dict with this id in a parsed shard or single-file manifest.

    Both shapes are read so the layout a copy keeps does not decide whether it
    can be counted: a shard IS one phase, a single file lists every phase.
    """
    candidates = [doc] if isinstance(doc, dict) and "tasks" in doc else (
        (doc.get("phases") or []) if isinstance(doc, dict) else [])
    for body in candidates:
        if isinstance(body, dict) and str(body.get("id")) == str(phase_id):
            return body
    return None


def _branch_copy(git_root, branch, rel, phase_id):
    """`(phase body, None)` as `branch` commits `rel`, or `(None, why)`.

    `git show <branch>:<rel>` reads the blob out of the object store, so no
    checkout of the branch is needed - which is the copy to read when no
    worktree has the branch out, because then nothing uncommitted can exist.
    """
    return _show_phase(git_root, "refs/heads/%s" % (branch,), rel, phase_id)


def _tree_copy(path, phase_id):
    """`(phase body, None)` as the file at `path` holds it right now, or
    `(None, why)`.

    THE FILE IN THE WORKTREE THAT HAS THE PHASE BRANCH OUT, uncommitted edits
    included. A run marks a task done in that file before any commit carries
    it, so the branch tip lags the run by up to a whole wave - and a count off
    the tip reports work as ready that the run has already finished. Opening
    another checkout's file is a read; nothing here writes to it.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "%s could not be read (%s)" % (path, exc)
    body = _phase_body(doc, phase_id)
    if body is None:
        return None, "%s holds no phase %s" % (path, phase_id)
    return body, None


def _show_phase(git_root, rev, rel, phase_id):
    """`(phase body, None)` as commit `rev` holds `rel`, or `(None, why)`."""
    spec = "%s:%s" % (rev, rel)
    code, out, err = _scoped_commit.run_git(git_root, ["show", spec])
    if code != 0:
        return None, "git show %s answered %s: %s" % (
            spec, code, " ".join((err or "").split())[:160] or "no output")
    try:
        body = _phase_body(json.loads(out), phase_id)
    except ValueError as exc:
        return None, "git show %s is not readable JSON (%s)" % (spec, exc)
    if body is None:
        return None, "git show %s holds no phase %s" % (spec, phase_id)
    return body, None


def _readiness_moved(git_root, branch, rel, phase_id):
    """`(note, known)` - whether this checkout's copy of `rel` changed after
    `branch` forked, in a way that moves the phase's readiness.

    CALL THIS ONLY WHEN THE COUNT CAME FROM THE BRANCH'S COMMITTED COPY - no
    worktree holds `branch` out, so `git show` is the only copy there was to
    read. That copy is the branch tip, but the development branch may have
    moved the same file on since the fork - a task added, a dependency
    rewritten - and a count off the tip alone would then miss that. So the
    count stays the branch's, and the sentence says what it may be missing.

    A worktree that holds `branch` out is read for its own file instead
    (`_tree_copy`), uncommitted edits included - that copy already IS
    whatever is live there, so it has nothing this question could be about,
    and the caller must not run this check over it.

    THE QUESTION IS ABOUT CONTENT, NOT COMMITS. A count of commits to the file
    reads a `--no-ff` landing of a branch that predates the file as a commit to
    it, although the merge brought the file nothing, and a landed reword of a
    description as a change although no task moved. So the common path is one
    `git diff --quiet <branch>...HEAD` - the file at the fork point against
    HEAD's - which costs what the count did. Only when that says the file
    changed are both copies read and their `readiness_projection`s compared.

    `known` is False whenever the note is not empty: a count that may be
    missing a readiness change, or whose divergence git could not report, is
    not one a zero may be silent on.
    """
    spec = "refs/heads/%s...HEAD" % (branch,)
    code, _out, err = _scoped_commit.run_git(
        git_root, ["diff", "--quiet", spec, "--", rel])
    if code == 0:
        return "", True
    why = "git diff --quiet %s answered %s: %s" % (
        spec, code, " ".join((err or "").split())[:160] or "no output")
    if code == 1:
        why = None
        mcode, mout, merr = _scoped_commit.run_git(
            git_root, ["merge-base", "refs/heads/%s" % (branch,), "HEAD"])
        fork = (mout or "").strip()
        if mcode != 0 or not fork:
            why = "git merge-base answered %s: %s" % (
                mcode, " ".join((merr or "").split())[:160] or "no output")
        if why is None:
            was, why = _show_phase(git_root, fork, rel, phase_id)
        if why is None:
            now, why = _show_phase(git_root, "HEAD", rel, phase_id)
        if why is None:
            if (_status_facts.readiness_projection(was)
                    == _status_facts.readiness_projection(now)):
                return "", True
            return ("; this checkout's copy of %s changed after branch `%s` "
                    "forked, in a way that moves readiness, so the branch's "
                    "copy may be missing that change" % (rel, branch), False)
    return ("; whether this checkout's copy of %s changed after branch `%s` "
            "forked could not be asked (%s), so this may not be current"
            % (rel, branch, why), False)


def _own_read(live, basis):
    """A read that shows this checkout's own copy of the phase - no body to lay
    over the plan - and whether that copy is the live one."""
    return {"body": None, "live": live, "own": True, "counted": True,
            "basis": basis}


def _fallback(on, branch, why):
    """This checkout's copy, marked as NOT the live one.

    The branch exists, and that is all this sentence asserts about it: its copy
    could not be read, so which copy holds the phase live is exactly what is
    unknown. A zero counted here is a stale reading, and it prints.
    """
    return _own_read(False, "this checkout's copy %s - branch `%s` exists but "
                            "its copy could not be read (%s), so this may not "
                            "be current" % (on, branch, why))


def _shard_rel(manifest_path, git_root, phase):
    """The phase's file as a path under the git root, or None.

    Every worktree of a clone lays its files out at the same paths relative to
    its own root, so this one path names the file in the branch's commits and
    in any worktree that has the branch out.
    """
    if not manifest_path:
        return None
    _index, phase_file = _invariants.manifest_files(manifest_path, phase)
    try:
        rel = _output.posix_rel(os.path.abspath(phase_file),
                                os.path.abspath(git_root))
    except ValueError:
        return None
    return None if rel.startswith("..") else rel


def _here_words(view):
    """How the sentence names the branch this checkout has out."""
    here = view.get("here")
    if here and here.get("branch"):
        return "on `%s`" % (here["branch"],)
    if here and here.get("detached"):
        return "on a detached HEAD"
    return "on a branch the worktree list could not name (%s)" % (
        view.get("error") or "this checkout is in none of the trees it lists")


# --- which copy holds a phase live ----------------------------------------------
def _live_read(manifest, manifest_path, git_root, phase_id, view, user):
    """`{"body", "live", "own", "counted", "basis"}` for one phase in flight -
    the copy judged to hold the phase live, and the sentence naming it.

    `body` is that copy's phase when it is not this checkout's own, else None
    (this checkout's phase is the one to show). `live` is True only when the
    copy read IS the one holding the phase live. `own` says the copy shown is
    this checkout's. `counted` is False when nothing about the phase could be
    read at all. `basis` names the copy, with no verb, so each surface puts
    its own in front of it: the lock line counts from it, a row is read from
    it or shows it.

    WHICH COPY, in order:

    - this checkout, when it has the phase branch out;
    - the file in another worktree that has the branch out, uncommitted state
      included (`_tree_copy` says why the tip is not enough);
    - the branch's committed copy, when no worktree has it out;
    - this checkout's copy, when no branch of that name exists - then it is the
      only copy there is.

    The branch name comes from `_branch.branch_of`, the one answer every
    surface gives, because the development branch's copy of a shard need not
    record the branch its phase later ran on.

    A PHASE THIS CHECKOUT'S PLAN DOES NOT HOLD GETS NO COUNT. A lock names it,
    so a run of it exists somewhere - on a branch whose phase this checkout's
    index never learned of - and zero would be the silent row. `counted`
    False is what makes the lock line's `readyCount` None, which
    `unfinished_runs` refuses.
    """
    phase = _invariants.phase_of(manifest, phase_id)
    if phase is None:
        return {"body": None, "live": False, "own": False, "counted": False,
                "basis": "this checkout's plan holds no phase %s, so the copy "
                         "that holds it live cannot be named from here"
                         % (phase_id,)}
    on = _here_words(view)
    branch = _branch.branch_of((manifest or {}).get("meta") or {}, phase,
                               user)["name"]
    here = view.get("here") or {}
    if here.get("branch") == branch:
        return _own_read(True, "this checkout, which has `%s` checked out"
                         % (branch,))
    probe = _worktrees.ref_exists(git_root, branch)
    if probe["exists"] is False:
        return _own_read(True, "this checkout's copy %s - no branch `%s` exists "
                               "in this repository (%s)"
                         % (on, branch, probe["basis"]))
    if probe["exists"] is None:
        return _fallback(on, branch, probe["basis"])
    rel = _shard_rel(manifest_path, git_root, phase)
    if rel is None:
        return _fallback(on, branch,
                         "the phase's file could not be placed under the git "
                         "root, so the file to read is unknown")
    caveat = ""
    live = True
    holder = (None if view.get("error")
              else _worktrees.holder_of(view.get("trees"), branch)["tree"])
    body = None
    if view.get("error"):
        live = False
        caveat = ("; which worktree has the branch out could not be asked (%s), "
                  "so uncommitted work there is not in this reading, which may "
                  "not be current" % (view["error"],))
    elif holder is not None:
        path = os.path.join(holder.get("path") or "", *rel.split("/"))
        body, why = _tree_copy(path, phase_id)
        source = "the worktree file %s, which has `%s` checked out" % (
            path, branch)
        if body is None:
            live = False
            caveat = ("; the worktree that has the branch out could not be "
                      "read (%s), so its uncommitted work is not in this "
                      "reading, which may not be current" % (why,))
    note, current = "", True
    if body is None:
        body, why = _branch_copy(git_root, branch, rel, phase_id)
        source = "branch `%s`'s copy of %s" % (branch, rel)
        if body is None:
            return _fallback(on, branch, why)
        # Only the branch's COMMITTED copy is what the fork-point diff is
        # about. A worktree's file already carries whatever is live there,
        # uncommitted edits included, so a readiness-moving edit this
        # checkout lands on its own history afterwards is not a gap in that
        # copy - there is nothing for this question to ask.
        note, current = _readiness_moved(git_root, branch, rel, phase_id)
    return {"body": body, "live": live and current, "own": False,
            "counted": True, "basis": "%s%s%s" % (source, caveat, note)}


def worktree_view(git_root):
    """`{"trees", "error", "here"}` - one `git worktree list`, and which of the
    trees it names is this checkout (so no separate HEAD read)."""
    listed = _worktrees.list_worktrees(git_root)
    trees = listed.get("trees") or []
    return {"trees": trees, "error": listed.get("error") or "",
            "here": _worktrees.standing_in(trees, git_root)}


def live_reads(manifest, manifest_path, git_root, phase_ids, view=None,
               user=None):
    """`{phase id: _live_read(...)}` for each phase id handed in.

    `view` and `user` are `in_flight`'s, which has already asked for both;
    without them the worktree list and the identity lookup are asked here,
    once, and only when there is a phase to read - an empty list costs
    nothing.

    One phase's read failing is that phase's sentence, never the whole
    answer's error: the other phases were read, and refusing them all for one
    unreadable branch would hide every answer that was available. The failed
    phase shows this checkout's copy and says it may not be current, and its
    lock line carries no count.
    """
    if not phase_ids:
        return {}
    if view is None:
        view = worktree_view(git_root)
    if user is None:
        user = _worktrees.git_user_name(git_root)
    out = {}
    for pid in phase_ids:
        try:
            out[pid] = _live_read(manifest, manifest_path, git_root, pid, view,
                                  user)
        except Exception as exc:                   # defensive; see the docstring
            read = _own_read(False, "this checkout's copy - the copy that "
                                    "holds phase %s live could not be read "
                                    "(%s), so this may not be current"
                             % (pid, exc))
            out[pid] = dict(read, counted=False)
    return out


# --- what is in flight ----------------------------------------------------------
def _in_a_repository(path):
    """Whether `path` or a directory above it holds a `.git` entry.

    The fact `_lock_dir` separates its two Nones by: a `.git` file or
    directory is what makes a directory part of a repository at all, so its
    absence all the way up is the one None that means no repository.
    """
    here = os.path.realpath(path or ".")
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return True
        up = os.path.dirname(here)
        if up == here:
            return False
        here = up


def _lock_dir(git_root):
    """`(lock directory, None)`, `(None, None)` for no repository, or
    `(None, why)` when the lookup failed.

    `_locks.lock_dir` answers None for both a directory in no repository and a
    repository git could not describe, and only the first means nothing can be
    in flight. A failed lookup read as no repository would show every phase
    run under a lock elsewhere from this checkout's copy and say nothing, so
    the failure is told apart by whether a `.git` exists at or above the git
    root, and then asked again through the runner that keeps git's stderr,
    which becomes the `why`.
    """
    ld = _locks.lock_dir(git_root)
    if ld:
        return ld, None
    if not _in_a_repository(git_root):
        return None, None
    code, out, err = _scoped_commit.run_git(
        git_root, ["rev-parse", "--git-common-dir"])
    if code == 0 and (out or "").strip():
        return None, ("git rev-parse --git-common-dir answered %s only on a "
                      "second ask, so the first lookup's failure is not known"
                      % ((out or "").strip(),))
    return None, "git rev-parse --git-common-dir answered %s: %s" % (
        code, " ".join((err or "").split())[:160] or "no output")


def _held_locks(ld):
    """`_locks.collect`'s rows for a lock directory already found.

    `collect` takes a project and looks the directory up itself, and
    `in_flight` needs that lookup's answer on its own too - whether this
    project has a lock scheme at all - so the one lookup is made there and
    the listing and judging are done here with `_locks`' own `read_lock` and
    `judge`, in `collect`'s order.
    """
    if not ld or not os.path.isdir(ld):
        return []
    try:
        names = sorted(n for n in os.listdir(ld) if n.endswith(".lock"))
    except OSError:
        return []
    rows = []
    for n in names:
        path = os.path.join(ld, n)
        info = _locks.read_lock(path)
        live, basis = _locks.judge(info, path)
        rows.append({"name": n[:-len(".lock")], "live": live,
                     "basis": basis, "info": info})
    return rows


def _branch_names(git_root):
    """`(set of local branch names, None)`, or `(None, why)` - one
    `git for-each-ref` for every branch, so asking whether a phase's branch
    exists costs nothing per phase."""
    code, out, err = _scoped_commit.run_git(
        git_root, ["for-each-ref", "--format=%(refname)", "refs/heads/"])
    if code != 0:
        return None, "git for-each-ref refs/heads/ answered %s: %s" % (
            code, " ".join((err or "").split())[:160] or "no output")
    prefix = "refs/heads/"
    return set(ln.strip()[len(prefix):] for ln in (out or "").splitlines()
               if ln.strip().startswith(prefix)), None


def _worked_elsewhere(manifest, git_root, view, user, locked):
    """`{"worked", "unread", "note"}` - the phases no lock names whose branch
    is being worked on somewhere this checkout cannot see.

    `worked` lists each phase whose branch another worktree has out and whose
    tip is not an ancestor of this checkout's HEAD: that worktree's file is
    read like a locked phase's. `unread` is `{phase id: {"live", "basis"}}`
    for each unfinished phase whose unmerged branch exists while no worktree
    has it out - the branch is not read, and its row says so. A phase with no
    branch is not named at all; this checkout's copy is the only one there
    is. `note` says what could not be asked, or is empty.

    A FINISHED PHASE'S IDLE BRANCH IS NOT NAMED. A `done` or `cancelled` phase
    has no ready work this checkout's copy could be wrong about, and a branch
    squash-merged or abandoned after such a phase is ordinary residue.

    A BRANCH WHOSE TIP HAS NOT MOVED PAST HEAD READS AS MERGED. A linked
    worktree whose branch has no commit of its own yet has its work only in
    uncommitted files, and the ancestor question cannot tell that branch from
    one that landed; such a phase is shown from this checkout's copy until its
    first commit, or until its run takes a lock.
    """
    notes = []
    names, why = _branch_names(git_root)
    if names is None:
        notes.append("which phase branches exist could not be asked (%s)"
                     % (why,))
    if view.get("error"):
        notes.append("which worktrees have a phase branch out could not be "
                     "asked (%s)" % (view["error"],))
    here = (view.get("here") or {}).get("branch")
    worked, unread = [], {}
    for phase, answer in _branch.plan_branches(manifest, user):
        pid = str(phase.get("id"))
        branch = answer["name"]
        if pid in locked or not branch or branch == here:
            continue
        holder = (None if view.get("error")
                  else _worktrees.holder_of(view.get("trees"), branch)["tree"])
        if holder is None and (names is None or branch not in names):
            continue
        if holder is None and (phase.get("mergedAt") or (
                _mio.effective_phase_status(phase) in _mio.TERMINAL)):
            continue
        merged = _worktrees.merged_into(git_root, "refs/heads/%s" % (branch,),
                                        "HEAD")
        if merged["answer"] == _worktrees.CONTAINED:
            continue
        if merged["answer"] == _worktrees.UNKNOWN:
            unread[pid] = {"live": False, "basis": (
                "shows this checkout's copy - whether branch `%s` is merged "
                "into this checkout's HEAD could not be asked (%s: %s), so it "
                "was not read and this may not be current"
                % (branch, merged["basis"], merged["detail"] or "no output"))}
        elif holder is not None:
            worked.append(pid)
        else:
            unread[pid] = {"live": False, "basis": (
                "shows this checkout's copy - branch `%s` exists and is not "
                "merged into this checkout's HEAD (%s), but no lock is held "
                "for the phase and no worktree has it out, so the branch was "
                "not read and this may not be current"
                % (branch, merged["basis"]))}
    note = ""
    if notes:
        note = ("%s, so a phase worked on there without a lock shows this "
                "checkout's copy, which may not be current" % "; ".join(notes))
    return {"worked": worked, "unread": unread, "note": note}


def in_flight(manifest, manifest_path, git_root):
    """`{"held", "reads", "scheme", "unread", "note"}` - every lock this clone
    holds, a read of each phase in flight from the copy that holds it live,
    whether this project has a lock scheme at all, the rows `_worked_elsewhere`
    names as not read, and what could not be asked.

    THE ONE READER. The READY NOW list, the phase table, the progress counts,
    `--short`, `--json` and the UNFINISHED block all take an in-flight phase
    from this answer: `audit-status.py`'s `main` lays `reads` over the plan
    once (`_status_facts.live_view`) and every surface renders that plan, and
    `locks_block` counts from the same reads. The panel's payload and the
    rendered report lay the same answer over their plan through the same call.
    The copy order lives in `_live_read` and nowhere else.

    IN FLIGHT MEANS ONE OF TWO THINGS. A `phase-<id>` lock is on disk for the
    phase, live holder or gone - the plugin's own record that a run started
    and has not given it back; a gone holder counts for `unfinished_runs`'
    reason, since an abandoned run's work still sits in its worktree. Or, with
    no lock, the worktree list shows the phase's branch out in another
    worktree and that branch is not merged into this checkout's HEAD - a run
    paused between sessions, or work done by hand, is still work this
    checkout's copy does not have (`_worked_elsewhere`). Both kinds are read
    the same way, through `live_reads`.

    THE LOCK DIRECTORY IS LOOKED UP HERE, ONCE, and `scheme` carries the
    answer to `locks_block`, which used to ask again. No repository means no
    lock directory, and then nothing can be in flight anywhere. A lookup that
    FAILED in a repository is not that answer (`_lock_dir`): it comes back as
    `error`, which `live_view` puts in the note and `locks_block` refuses to
    read as a clean bill, and nothing is read - which phases a lock names is
    exactly what is unknown.

    WHAT IT COSTS, in a git repository: the lock directory lookup (one
    `git rev-parse --git-common-dir`, and a second only when the first failed
    there) and its listing, one worktree list, one
    identity lookup and one `git for-each-ref` over the local branches, on
    every invocation. Then one `git merge-base --is-ancestor` per phase no
    lock names whose branch another worktree has out, or whose unfinished
    phase has a branch at all; and per phase read, a ref probe, a read of its
    copy and, for a branch's committed copy, one content diff of its file
    since the fork - and, only when that diff says the file changed, its fork
    point and a read of each copy, to ask whether the change moved readiness.
    Each call goes through a runner with a timeout, and the per-phase calls
    scale with the phase branches that exist rather than with the plan.
    """
    ld, why = _lock_dir(git_root)
    if why:
        return {"held": None, "reads": {}, "scheme": None, "unread": {},
                "note": "",
                "error": "which phase locks are held could not be asked - the "
                         "lock directory could not be looked up (%s), so every "
                         "row shows this checkout's copy, which may not be "
                         "current" % (why,)}
    if not ld:
        return {"held": [], "reads": {}, "scheme": False, "unread": {},
                "note": ""}
    held = _held_locks(ld)
    prefix = _status_facts.PHASE_LOCK_PREFIX
    locked = []
    for r in held:
        name = r.get("name")
        if isinstance(name, str) and name.startswith(prefix):
            pid = name[len(prefix):]
            if pid not in locked:
                locked.append(pid)
    view = worktree_view(git_root)
    user = _worktrees.git_user_name(git_root)
    found = _worked_elsewhere(manifest, git_root, view, user, locked)
    return {"held": held,
            "reads": live_reads(manifest, manifest_path, git_root,
                                locked + found["worked"], view=view,
                                user=user),
            "scheme": True, "unread": found["unread"], "note": found["note"]}


def flight_for(manifest, manifest_path, project):
    """`in_flight` for the project's git root, or `{"held": None, "reads": {},
    "error"}` when it could not be asked - which every surface then says,
    rather than presenting this checkout's copies as if nothing were in flight.
    """
    try:
        return in_flight(manifest, manifest_path,
                         _invariants.git_root_for(manifest, project))
    except Exception as exc:                       # defensive; see the docstring
        return {"held": None, "reads": {}, "unread": {}, "note": "",
                "error": "which phases are in flight elsewhere could not be "
                         "asked (%s), so every row shows this checkout's copy, "
                         "which may not be current" % (exc,)}


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through to the docstring dump. It does NOT
        # print the cases-passed contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_live_copy.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__live_copy.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
