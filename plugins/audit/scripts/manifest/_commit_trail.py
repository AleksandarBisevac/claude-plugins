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

THE VERDICT A TASK COMMIT CARRIES lives here too, for the same reason: it is a
question about a recorded commit, and git alone answers it. The commit verb writes
`Audit-Task`, `Audit-Gate`, `Audit-Run` and, over a refused verdict,
`Audit-Override` into the commit's trailer block (`verdict_trailers`), and
`verdicts_at` / `task_verdicts` / `plan_verdicts` read them back through git's own
trailer parser - no evidence directory, no journal. The writer and the reader sit
side by side so neither can learn a spelling the other does not.

Reads git, never writes it. The caller owns the lock, the journal row and the
revalidation — this module answers and returns.

This module carries no `--selftest` of its own; its cases live in
`tests/test__commit_trail.py`.
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


def no_change_close(task):
    """`outcome.noChange` when `task` was closed as `done --no-change`, else None.

    THE ONE DONE TASK THAT OWES NO SHA: its answer was that nothing needed to
    change, so nothing was committed and the block records why and the HEAD it
    was examined at. Asked here because the verb that writes it and the doctor
    that would otherwise warn about the missing SHA both need the same answer.
    """
    outcome = task.get("outcome") if isinstance(task, dict) else None
    block = outcome.get("noChange") if isinstance(outcome, dict) else None
    return block if isinstance(block, dict) else None


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


def _git(git_root, args, timeout=15, stdin=None):
    """(returncode, stdout) or (None, "") when git could not be asked."""
    try:
        out = subprocess.run(["git", "-C", git_root] + list(args),
                             input=stdin, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=timeout)
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

    **A SHALLOW CLONE TURNS EVERY ACCUSATION INTO AN UNASKED QUESTION**.
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

    A BUG'S `fixedIn` IS CLEARED WITH IT when it holds the commit its fix task just
    lost. `/audit:task done` stores that copy, and nothing else would ever move it:
    the derivation only fills an empty `fixedIn`, so the bug would go on naming a
    commit the trail no longer has, where before the close stored it the report read
    the task's commit and followed the repair. A `fixedIn` naming a DIFFERENT commit
    was put there by someone else and is left alone. Its row carries `bugId`.
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
    lost_by_task = dict((c["taskId"], c["wasCommit"]) for c in cleared)
    for bug in ((manifest or {}).get("bugs") or []):
        if not isinstance(bug, dict):
            continue
        was = lost_by_task.get(str(bug.get("taskId")))
        if was and str(bug.get("fixedIn") or "") == was:
            cleared.append({"bugId": str(bug.get("id")),
                            "taskId": str(bug.get("taskId")), "wasFixedIn": was})
            bug["fixedIn"] = None
    return manifest, cleared


def changes_of(cleared):
    """`cleared` as journal `changes` rows: `{id, field, from, to}`."""
    return [{"id": c["bugId"], "field": "fixedIn", "from": c["wasFixedIn"], "to": None}
            if "bugId" in c else
            {"id": c["taskId"], "field": "commit", "from": c["wasCommit"], "to": None}
            for c in cleared]


def summary(cleared):
    """One line naming what the trail lost, for a journal row and for a human."""
    if not cleared:
        return "no recorded commit needed clearing"
    tasks = [c for c in cleared if "bugId" not in c]
    bugs = [c for c in cleared if "bugId" in c]
    names = ", ".join("%s (%s)" % (c["taskId"], c["wasCommit"][:12])
                      for c in tasks[:4])
    return ("cleared %d unreachable task commit(s) after a history rewrite: %s%s%s"
            % (len(tasks), names, "" if len(tasks) <= 4 else ", ...",
               ("; and the fixedIn of %s, which held one of them"
                % (", ".join(c["bugId"] for c in bugs),)) if bugs else ""))


# --- the verdict a task commit carries ------------------------------------------
# THE RULE, property by property; `tests/test__commit_trail.py` holds a case for
# each.
#
#   * A TRAILER COMMIT is one whose trailer block, AS GIT PARSES IT, carries an
#     `Audit-Task` key. Git is the parser (`%(trailers:only,unfold)`, which is
#     `git interpret-trailers --parse`): a line git does not read as a trailer -
#     one in a paragraph a later paragraph follows - is not one here either. Any
#     other commit is not a trailer commit, and its verdict is read as it was
#     before trailers existed: this module answers nothing for it.
#   * `Audit-Task` with no `Audit-Gate` is NO VERDICT RECORDED (`recorded`
#     False, `status` None) - never passed.
#   * A key given more than once with one value reads as that value; with two
#     values, or empty, it reads as nothing for that key, and `problems` names
#     it. An `Audit-Gate` value is `<status>` or `<status> <digest>`; anything
#     else is nothing recorded, named the same way.
#   * A status word outside `GATE_WORDS` is returned as itself with `known`
#     False. It is still a recorded word; folding it into passed or failed is a
#     reader's guess this module does not make.
#   * Keys compare case-insensitively, as git's own trailer matching does.
#   * Of two commits naming one task, `task_verdicts` takes the first that
#     `git log --topo-order` shows - no other carrier descends from it - and
#     names the rest under `superseded`. A plan reader does not walk at all: it
#     reads each done task at the commit the plan records (`plan_verdicts`).
TASK_TRAILER = "Audit-Task"
GATE_TRAILER = "Audit-Gate"
RUN_TRAILER = "Audit-Run"
OVERRIDE_TRAILER = "Audit-Override"
VERDICT_TRAILERS = (TASK_TRAILER, GATE_TRAILER, RUN_TRAILER, OVERRIDE_TRAILER)

# The status words this build knows: the schema's `testEvidence.status` enum,
# which a case reads back out of the schema rather than trusting this copy.
GATE_WORDS = ("passed", "failed", "gate-mutated", "no-checks", "timed-out",
              "cancelled", "could-not-run", "empty-gate")

# git's own reading of a commit's trailer block, one commit per record.
_TRAILER_FORMAT = "--format=%H%x00%(trailers:only,unfold)"


def trailer_pairs(text):
    """`[(key, value)]` from git's parsed trailer output, in order, values
    stripped as git strips them. A line holding no separator is not a trailer
    and is skipped: git's `only` output never prints one."""
    out = []
    for line in (text or "").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            out.append((key.strip(), value.strip()))
    return out


def _one_value(pairs, name):
    """`(value, problem)` for one trailer key: the value when every occurrence
    agrees and it is not empty, else None and the sentence saying why."""
    values = [v for k, v in pairs if k.lower() == name.lower()]
    distinct = sorted(set(values))
    if not values:
        return None, None
    if len(distinct) > 1:
        return None, ("%s is given %d different values (%s), so none of them "
                      "is read" % (name, len(distinct), ", ".join(
                          repr(v) for v in distinct)))
    if not distinct[0]:
        return None, "%s is empty" % (name,)
    return distinct[0], None


def verdict_of(pairs):
    """The verdict `pairs` (one commit's trailers) record, or None when they
    name no task - not a trailer commit.

    `{"task", "status", "digest", "run", "override", "recorded", "known",
    "problems"}`: `recorded` is True only when a task and a status were both
    read; `known` says whether the status is one of `GATE_WORDS` (None with no
    status); `problems` names every key that was present and could not be read.
    """
    if not any(k.lower() == TASK_TRAILER.lower() for k, _v in pairs):
        return None
    problems = []
    read = {}
    for name in VERDICT_TRAILERS:
        value, problem = _one_value(pairs, name)
        read[name] = value
        if problem:
            problems.append(problem)
    status = digest = None
    gate = read[GATE_TRAILER]
    if gate is not None:
        words = gate.split()
        if len(words) in (1, 2):
            status = words[0]
            digest = words[1] if len(words) == 2 else None
        else:
            problems.append("%s %r is not `<status>` or `<status> <digest>`"
                            % (GATE_TRAILER, gate))
    recorded = read[TASK_TRAILER] is not None and status is not None
    return {"task": read[TASK_TRAILER], "status": status if recorded else None,
            "digest": digest if recorded else None, "run": read[RUN_TRAILER],
            "override": read[OVERRIDE_TRAILER], "recorded": recorded,
            "known": (status in GATE_WORDS) if recorded else None,
            "problems": problems}


def _records(out):
    """`[(sha, trailer text)]` from a `-z` log in `_TRAILER_FORMAT`."""
    parts = out.split("\x00")
    return [(parts[i].strip(), parts[i + 1])
            for i in range(0, len(parts) - 1, 2) if parts[i].strip()]


def verdicts_at(git_root, shas):
    """`(found, why)` - `{sha: verdict}` for each SHA in `shas` that names a
    trailer commit, keyed by the SHA as it was ASKED (an abbreviation is
    matched by prefix). A SHA git does not hold, and a commit carrying no
    `Audit-Task`, are absent. `found` is None when git could not be asked, and
    `why` says so - an empty map would read as "no commit carries a verdict".

    ONE `git log` for every SHA, fed on stdin so a long plan cannot outgrow a
    command line. No SHA asks nothing: `git log` handed no revision reads HEAD.
    """
    wanted = [str(s).strip() for s in (shas or ()) if s and str(s).strip()]
    if not wanted:
        return {}, ""
    if not (git_root and shutil.which("git")):
        return None, ("git is not on PATH or there is no git root, so the "
                      "verdicts task commits carry could not be read")
    code, out = _git(git_root, ["log", "--no-walk=unsorted", "--ignore-missing",
                                "--stdin", "-z", _TRAILER_FORMAT],
                     stdin=("\n".join(wanted) + "\n").encode("utf-8"))
    if code != 0:
        return None, ("git would not read the commits' trailers in %s, so the "
                      "verdicts task commits carry are not known" % (git_root,))
    by_sha = dict((sha, verdict_of(trailer_pairs(text)))
                  for sha, text in _records(out))
    found = {}
    for asked in wanted:
        for sha, verdict in by_sha.items():
            if verdict is not None and sha.startswith(asked.lower()):
                found[asked] = verdict
                break
    return found, ""


def task_verdicts(git_root, rev="HEAD"):
    """`(found, why)` - `{task id: verdict}` over the history `rev` reaches,
    each verdict carrying `sha` and `superseded` (the other commits naming the
    task, in log order). The winner is the first `git log --topo-order` shows,
    which no other carrier descends from. `found` is None when git could not be
    asked.

    `--grep` narrows the walk to messages mentioning the key at all; which of
    them are trailer commits is still git's trailer parse, never the grep.

    THE TRAILING `--` CLOSES THE REVISION LIST WITH AN EMPTY PATHSPEC. It
    carries no path, plan-relative or git-relative, and the output holds SHAs
    and trailer text only, so a project in a subdirectory of its repository
    walks the same whole history. What it buys is that `rev` is only ever a
    revision: without it, a `rev` naming a directory is read as a pathspec and
    git answers, exit 0, with the history of that directory alone."""
    if not (git_root and shutil.which("git")):
        return None, ("git is not on PATH or there is no git root, so no "
                      "history could be read for task verdicts")
    code, out = _git(git_root, ["log", "--topo-order", "-z", "-i",
                                "--fixed-strings", "--grep=" + TASK_TRAILER,
                                _TRAILER_FORMAT, rev, "--"])
    if code != 0:
        return None, ("git would not walk %s in %s for task verdicts"
                      % (rev, git_root))
    found = {}
    for sha, text in _records(out):
        verdict = verdict_of(trailer_pairs(text))
        if verdict is None or verdict["task"] is None:
            continue
        held = found.get(verdict["task"])
        if held is not None:
            held["superseded"].append(sha)
            continue
        found[verdict["task"]] = dict(verdict, sha=sha, superseded=[])
    return found, ""


def done_commits(manifest):
    """`{task id: sha}` for every DONE task that records a commit, the shape a
    plan's verdict read asks for."""
    out = {}
    for phase in _phase_blocks(manifest):
        for task in (phase.get("tasks") or []):
            if isinstance(task, dict) and task.get("status") == "done" \
                    and task.get("commit") and task.get("id") is not None:
                out[str(task["id"])] = str(task["commit"])
    return out


def plan_verdicts(manifest, git_root):
    """`(found, why)` - `{task id: verdict}` for the plan's done tasks, each
    read at the commit the plan records (`done_commits`); a task whose commit
    carries no `Audit-Task` is absent. A commit naming ANOTHER task is not this
    task's verdict: it comes back `recorded` False with the mismatch in
    `problems`, so one task's green is never lent to another. `found` is None
    when git could not be asked."""
    commits = done_commits(manifest)
    by_sha, why = verdicts_at(git_root, sorted(set(commits.values())))
    if by_sha is None:
        return None, why
    found = {}
    for task_id, sha in sorted(commits.items()):
        verdict = by_sha.get(sha)
        if verdict is None:
            continue
        if verdict["task"] != task_id:
            verdict = dict(verdict, status=None, digest=None, recorded=False,
                           known=None, problems=list(verdict["problems"]) + [
                               "commit %s names task %s, not %s"
                               % (sha[:12], verdict["task"], task_id)])
        found[task_id] = dict(verdict, sha=sha)
    return found, ""


def _line_break_refusal(name, value):
    """The sentence refusing `value` for trailer `name` when it holds a line
    break, naming the line after the first one, else None."""
    lines = str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) == 1:
        return None
    return ("the %s value holds a line break before line 2 (%r) - git reads a "
            "trailer as one line and would join the lines with a space, so it "
            "would not be carried verbatim; give it on one line"
            % (name, lines[1][:60]))


def verdict_trailers(task_id, row=None, override=None):
    """`(lines, refusal)` - the trailer lines a task commit carries for the
    verdict it was bound to: `Audit-Task`, then, when `row` (the evidence row
    the binding bound, or went over) is given, `Audit-Gate: <status>[ <digest>]`
    and `Audit-Run`, then `Audit-Override` with `override` when the commit is
    made over its verdict. With no row the task alone is written, which reads
    as no verdict recorded.

    A VALUE THE READER WOULD NOT READ BACK IS REFUSED, never written altered:
    `refusal` is the sentence and `lines` is empty. A line break is refused
    rather than folded because git unfolds a folded trailer into one line with a
    space, which is not the reason that was given; an empty value, and a status
    or digest holding whitespace, would read as nothing recorded.
    """
    values = [(TASK_TRAILER, task_id)]
    if isinstance(row, dict):
        status, digest = row.get("status"), row.get("gateDigest")
        gate = ("%s %s" % (status, digest) if digest else "%s" % (status,))
        for name, part in (("gate status", status), ("gate digest", digest)):
            if part is not None and len(str(part).split()) != 1:
                return [], ("the %s %r is not one word, so `%s` would not read "
                            "back as `<status> <digest>`"
                            % (name, part, GATE_TRAILER))
        values.append((GATE_TRAILER, gate))
        if row.get("runId"):
            values.append((RUN_TRAILER, row.get("runId")))
    if override is not None:
        values.append((OVERRIDE_TRAILER, override))
    for name, value in values:
        refusal = _line_break_refusal(name, value)
        if refusal:
            return [], refusal
        if not str(value).strip():
            return [], "the %s value is empty, which reads as nothing" % (name,)
    return ["%s: %s" % (name, str(value).strip()) for name, value in values], None


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
