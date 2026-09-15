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


def _phase_blocks(manifest):
    """The phase dicts a document holds, whichever of the two shapes it is in.

    An index carries `phases`; a shard is ONE phase written on its own, with no
    wrapper, and a caller reading what git tracks meets both unassembled. Kept
    apart from `recorded()` deliberately: that function answers for the trail as
    the doctor and the repair verb read it, and widening it to shards would
    change what those two grade.
    """
    phases = (manifest or {}).get("phases")
    if isinstance(phases, list):
        return [p for p in phases if isinstance(p, dict)]
    if isinstance((manifest or {}).get("tasks"), list):
        return [manifest]
    return []


def referenced(manifest):
    """`[(where, field, value)]` for every commit a manifest NAMES, in order.

    WIDER THAN `recorded()`, ON PURPOSE. The trail is task commits, and that is
    what the doctor grades and what the repair verb clears. A manifest names a
    commit in two more places and neither belongs to the trail: a phase's
    `baseRef` says which commit its branch forked from, and a bug's `fixedIn` is
    copied off the fixing task. Both are still claims about a repository's
    history, so a reader asking whether COMMITTED data names anything git does
    not have needs all three in one walk rather than in a second one that can
    disagree with this one.

    A `baseRef` may name a branch rather than a SHA, and `resolve()` answers for
    either: the question is whether git has the object, not how the document
    spelled the way to it.
    """
    out = []
    for phase in _phase_blocks(manifest):
        phase_id = str(phase.get("id"))
        if phase.get("baseRef"):
            out.append((phase_id, "baseRef", str(phase.get("baseRef"))))
        for task in (phase.get("tasks") or []):
            if isinstance(task, dict) and task.get("commit"):
                out.append((str(task.get("id")), "commit",
                            str(task.get("commit"))))
    for bug in ((manifest or {}).get("bugs") or []):
        if isinstance(bug, dict) and bug.get("fixedIn"):
            out.append((str(bug.get("id")), "fixedIn", str(bug.get("fixedIn"))))
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


def is_shallow(git_root):
    """Is this a truncated clone? `True`, `False`, or `None` when git would not say.

    IN A SHALLOW CLONE A NEGATIVE ANSWER IS NOT AN ANSWER, which is the whole
    reason this exists. `git clone --depth` and `actions/checkout`'s default both
    leave a repository whose object store and whose history stop at a graft
    boundary, so "rev-parse cannot resolve it" stops meaning "the object is not in
    the world" and starts meaning "the object is past where this clone was cut".
    POSITIVE answers survive: a SHA that resolves is present, and one that is an
    ancestor of HEAD is reachable. Only the accusations become unsupportable.

    `None` rather than `False` when git will not answer: guessing "not shallow"
    here would restore exactly the false accusation this removes, on the machine
    least able to argue with it.
    """
    code, out = _git(git_root, ["rev-parse", "--is-shallow-repository"])
    if code != 0:
        return None
    val = out.strip()
    # Older git answers neither word; a repository it will not describe is one
    # this function must not describe either.
    return True if val == "true" else (False if val == "false" else None)


def can_answer(git_root):
    """`(True, None)` when this checkout can say whether an object exists here.

    `(False, why)` otherwise, and the sentence is the whole point of the
    function. `resolve()` turns a negative into `unchecked` wherever the clone
    cannot support an accusation, which is right for a DIAGNOSTIC: it refuses to
    accuse on evidence it does not have. A GATE reading the same three words has
    the opposite failure available to it -- every row `unchecked` and nothing to
    report reads as a clean set, so the truncation that hides the problem becomes
    the reason the gate is green. A gate therefore asks about the CLONE before it
    asks about any object, and stops when the answer is that it cannot look.

    Lifted here rather than written in the caller because `is_shallow`'s three
    answers are already subtle, and a second reading of them would be a second
    opinion about what a truncated clone may be asked.
    """
    if not (git_root and shutil.which("git")):
        return False, ("git is not on PATH, so whether this checkout holds a "
                       "commit could not be asked at all")
    cut = is_shallow(git_root)
    if cut is None:
        return False, ("git would not say whether %s is a truncated clone, and "
                       "a checkout that will not describe itself cannot be read "
                       "as a complete one" % (git_root,))
    if cut:
        return False, ("%s is a SHALLOW clone: its object store stops at a graft "
                       "boundary, so every commit past that boundary is one git "
                       "answers for the same way it answers for a commit that "
                       "never existed. Deepen it (`git fetch --unshallow`, or "
                       "`fetch-depth: 0` on the checkout step) and ask again"
                       % (git_root,))
    return True, None


def resolve(git_root, sha, cut=None):
    """`"present"`, `"absent"` or `"unchecked"` for ONE sha in this clone.

    THE EXISTENCE HALF OF `dangling`, LIFTED SO A SECOND CALLER CANNOT REACH A
    DIFFERENT ANSWER. `/audit:task done` grades a SHA it is being handed BEFORE it
    writes it, which is the same question this module exists to hold once: does
    git have this object. Asking it again in the writer would be the second walk
    the docstring above says not to take.

    THE THREE-WAY ANSWER IS THE POINT, and `is_shallow` is why. A `rev-parse` that
    fails means the object is not here only in a clone that can answer for the
    world; in a truncated one, or with no git to ask, the same failure means the
    question was never put. So a negative becomes `unchecked` wherever the clone
    cannot support the accusation, and a POSITIVE survives everywhere -- an object
    that resolves really is present.

    `cut` is the shallow verdict when the caller already holds one: `dangling`
    pays for it once per call rather than once per row. Passed None it is asked
    here, which is what a single-SHA caller wants.

    THE NO-GIT BRANCH IS REACHABLE ONLY FROM THAT SECOND CALLER -- `dangling`
    returns every row as `unchecked` before it reaches this function. It is
    spelled anyway, because a caller handed an empty root would otherwise get an
    answer out of a `_git` that never ran.
    """
    if not (git_root and shutil.which("git")):
        return "unchecked"
    code, _ = _git(git_root, ["rev-parse", "-q", "--verify",
                              "%s^{commit}" % sha])
    if code is None:
        return "unchecked"
    if code == 0:
        return "present"
    if cut is None:
        cut = is_shallow(git_root) is not False
    return "unchecked" if cut else "absent"


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
    * **unchecked** — git could not be asked, OR it was asked in a clone that
      cannot answer. Not a clean trail; an unasked question, and a caller that
      folds it into "fine" reports a machine with no git as a healthy one.

    **A SHALLOW CLONE TURNS EVERY ACCUSATION INTO AN UNASKED QUESTION** (F88).
    `git clone --depth` and `actions/checkout`'s default cut the object store and
    the history at a graft boundary, so a `rev-parse` that fails there says the
    object is past the cut and not that it never existed — and a ref walk that
    finds no container says the same about reachability. Both negatives move to
    `unchecked`; both POSITIVES are kept, because a SHA that resolves really is
    present and one that is an ancestor of HEAD really is reached.

    That distinction is not cosmetic here: the doctor's remedy for `missing` is
    `repair-commits.py --apply`, which NULLS the recorded SHAs. Graded the old
    way, a shallow checkout produced a finding whose own advice destroyed a trail
    that was intact.

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
    # Asked ONCE per call rather than per row: it is a property of the clone, and
    # a per-row question would pay a git call for every recorded commit to learn
    # the same thing. `None` (git would not say) is treated as shallow, which is
    # the direction that refuses to accuse on evidence it does not have.
    cut = is_shallow(git_root) is not False
    for phase_id, task_id, sha in rows:
        row = (phase_id, task_id, sha)
        verdict = resolve(git_root, sha, cut)
        if verdict == "unchecked":
            unchecked.append(row)
            continue
        if verdict == "absent":
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
            (unchecked if cut else unreachable).append(row)
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
