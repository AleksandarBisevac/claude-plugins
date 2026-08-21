#!/usr/bin/env python3
"""
Which `task.commit` SHAs git still has — and what to write when it does not.

The manifest records a SHA per finished task and derives `bug.fixedIn` from it.
That is the audit trail, and it is only a trail while git still holds every commit
it names. `reference/orchestrator.md` protects it by forbidding rebase and
force-push, `hooks/guard-history-rewrite.py` refuses the commands that would
break it, and `/audit:doctor` reports a SHA that resolves nowhere as a FINDING.

This module is the question those three share: **is each recorded SHA still
reachable?** It lives here rather than in the doctor because the doctor is not
the only reader — the repair command needs the same answer, and a second walk
over the same tasks asking git the same question is a second answer waiting to
disagree with the first.

WHAT REPAIR MAY AND MAY NOT DO. When history has been rewritten, the manifest
names ghosts. It is tempting to re-anchor: find the commit with the same message,
or the same tree, and point the task at that instead. **Do not.** That is
inventing a fact to fill a gap, and the gap is the fact — the commit the task was
verified against no longer exists, and a plausible substitute makes the trail
read as intact when it is not. `clear()` therefore sets the SHA to `null` and
hands the caller what was lost, so the caller can record it; the manifest then
says *this commit is no longer reachable*, which is true.

Reads git, never writes it. The caller owns the lock, the journal row and the
revalidation — this module answers and returns.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__commit_trail.py`.
"""
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


def recorded(manifest):
    """`[(phaseId, taskId, sha)]` for every task that names a commit."""
    out = []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        for task in (phase.get("tasks") or []):
            if isinstance(task, dict) and task.get("commit"):
                out.append((str(phase.get("id")), str(task.get("id")),
                            str(task.get("commit"))))
    return out


def _git(git_root, args, timeout=15):
    """(returncode, stdout) or (None, "") when git could not be asked."""
    try:
        out = subprocess.run(["git", "-C", git_root] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=timeout)
        return out.returncode, out.stdout.decode("utf-8", "replace")
    except Exception:
        return None, ""


def dangling(manifest, git_root):
    """`{"missing": [...], "unreachable": [...], "unchecked": [...]}`.

    THREE ANSWERS, NOT ONE, and the split is the point.

    * **missing** — `git rev-parse --verify` cannot resolve it at all. The object
      is not in this clone: a fabricated SHA, or one that was orphaned long enough
      ago for `git gc` to collect it. Nothing can bring it back here.
    * **unreachable** — the object EXISTS but no ref contains it. This is what a
      rewritten history looks like the moment after it happens, and it is
      recoverable: the commit is still in the object store until gc runs, so
      restoring a branch onto it puts the trail back.
    * **unchecked** — git could not be asked. Not a clean trail; an unasked
      question, and a caller that folds it into "fine" reports a machine with no
      git as a healthy one.

    **Existence is not reachability, and the difference is the whole bug this
    function was written to fix.** `/audit:doctor` asked `rev-parse --verify`
    alone, which answers "is this object in the store" — so a `git reset --hard`
    that orphaned three task commits left every one of them verifying green until
    a `gc` ran, possibly weeks later, at which point they turned from
    recoverable into gone with no event in between to notice.

    The reachability question costs one git call per commit, so the ancestor check
    against HEAD runs first: it is cheap and true for the overwhelming majority of
    recorded commits, which sit on the development branch.
    """
    missing, unreachable, unchecked = [], [], []
    rows = recorded(manifest)
    if not rows:
        return {"missing": [], "unreachable": [], "unchecked": []}
    if not (git_root and shutil.which("git")):
        return {"missing": [], "unreachable": [], "unchecked": list(rows)}
    for phase_id, task_id, sha in rows:
        row = (phase_id, task_id, sha)
        code, _ = _git(git_root, ["rev-parse", "-q", "--verify",
                                  "%s^{commit}" % sha])
        if code is None:
            unchecked.append(row)
            continue
        if code != 0:
            missing.append(row)
            continue
        # Fast path: almost every recorded commit is an ancestor of HEAD.
        code, _ = _git(git_root, ["merge-base", "--is-ancestor", sha, "HEAD"])
        if code == 0:
            continue
        code, out = _git(git_root, ["for-each-ref", "--contains", sha])
        if code is None or code != 0:
            unchecked.append(row)
        elif not out.strip():
            unreachable.append(row)
    return {"missing": missing, "unreachable": unreachable,
            "unchecked": unchecked}


def clear(manifest, lost):
    """Null the SHA of every task in `lost`; return `(manifest, cleared)`.

    NOT a re-anchor. The commit the task was verified against is gone, and the
    manifest saying so is the honest state — a substitute found by matching commit
    messages would make the trail read as intact when it is not.

    `cleared` carries what was there, because the caller's job is to record it:
    a repair that erased the evidence of its own necessity would be the same
    silence, one step later.
    """
    wanted = set((str(p), str(t)) for p, t, _sha in lost)
    cleared = []
    for phase in ((manifest or {}).get("phases") or []):
        if not isinstance(phase, dict):
            continue
        for task in (phase.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            key = (str(phase.get("id")), str(task.get("id")))
            if key in wanted and task.get("commit"):
                cleared.append({"phaseId": key[0], "taskId": key[1],
                                "wasCommit": str(task.get("commit"))})
                task["commit"] = None
    return manifest, cleared


def summary(cleared):
    """One line naming what the trail lost, for a journal row and for a human."""
    if not cleared:
        return "no recorded commit needed clearing"
    names = ", ".join("%s (%s)" % (c["taskId"], c["wasCommit"][:12])
                      for c in cleared[:4])
    return ("cleared %d unreachable task commit(s) after a history rewrite: %s%s"
            % (len(cleared), names, "" if len(cleared) <= 4 else ", ..."))


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_commit_trail.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__commit_trail.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
