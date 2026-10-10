#!/usr/bin/env python3
"""Carry ONE task tree's work into the phase tree, or refuse by name.

WHY THIS EXISTS. A wave runs tasks in worktrees of their own and the tree that
holds the record is the phase tree, so something has to move bytes from the one to
the other - and the tree is removed afterwards, so whatever is not moved is gone.
That makes every silent choice here a lost edit: a path the task never declared, a
file a sibling already changed, a lockfile two tasks both rewrote. Each is either
integrated on purpose or refused with the names of the tasks and paths involved;
none is dropped.

WHAT IT WRITES, AND WHAT IT NEVER TOUCHES. Bytes into the phase tree's WORKING
TREE and a small state file in the phase tree's git directory (never the working
tree, never tracked). The phase tree's INDEX is left alone, because `commit-task-work`
stages exactly the declared files afterwards and a pre-staged path is something it
refuses; every git call here runs with `GIT_OPTIONAL_LOCKS=0`. That is DEFENSIVE
and UNPROVEN for the calls made here: measured on a stale stat cache, `git status`
rewrote the index without it and left it alone with it, but `git diff HEAD` (the
form used below) rewrote nothing either way, and no test fails if it is removed.

THE ORDER OF THE QUESTIONS is the order of what each one costs to get wrong:
  1. is the phase tree clean apart from record paths (manifest, journal, evidence)
     and paths other integrations of this wave put there?  -> `dirty`
  2. what did the task really change?  Read from the task tree's own index
     (`git add -A` there is private to that tree), never from its declaration.
  3. which of those paths did something else change since the base?  A lockfile
     among them is refused outright (`non-mergeable`) - a clean text merge of two
     machine-written files is not a file any tool wrote; the rest are merged per
     path with `git merge-file`, and a conflict is refused (`conflict`). Both name
     every task involved. This runs BEFORE the declaration check on purpose: a
     path two tasks both wrote is a refusal whether or not either declared it.
  4. which changed paths does the task not declare?  A DECISION (exit 3) - widen,
     discard or block - because the task tree is about to be removed.
  5. write, with the intent recorded first so a crash mid-write is resumable.

RESUME. A second run is a no-op that says "already integrated": the state file
says so, and if that file is lost the bytes say it (the phase tree already holds
exactly the task tree's bytes at every changed path, and no other integration
accounts for them).

Usage:
  integrate-task.py <manifest> <taskId> [--project DIR] [--json]
                    [--undeclared widen|discard|block]

Exit codes:
  0  integrated, or already integrated, or there was nothing to integrate
  1  refused: dirty | conflict | non-mergeable | undeclared (blocked) |
     no-task-tree - the answer names the paths and the tasks
  2  usage error - unknown task, bad option
  3  a DECISION is owed (undeclared paths): rerun with `--undeclared`
  4  it could not be asked - git would not answer. Not 0 and not a refusal
"""
import argparse
import json
import os
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
import _evidence_io  # noqa: E402  (where the evidence ledger lives: a record path)
import _invariants  # noqa: E402  (the git root and the manifest file pair)
import _journal_io  # noqa: E402  (where the journal lives: a record path)
import _manifest_io as _mio  # noqa: E402  (dual-format loader)
import _task_outputs  # noqa: E402  (the ONE rule for what a declared entry covers)
import _wave  # noqa: E402  (which path classes a text merge cannot be trusted with)
import _worktrees as _wt  # noqa: E402  (git's worktree list and the task marker)

E_OK, E_REFUSED, E_USAGE, E_DECIDE, E_NO_BASIS = 0, 1, 2, 3, 4

PREFIX = "integrate-task:"
STATE_NAME = "audit-wave-integration.json"
CHOICES = ("widen", "discard", "block")
NO_SIBLING = "(a change in the phase tree that no integration here accounts for)"


class GitUnavailable(RuntimeError):
    """git could not be asked, which is not the same as git saying no."""


# --- git, as bytes ---------------------------------------------------------------
def _git(cwd, args, stdin=None):
    """(code, stdout bytes, stderr text). Raises GitUnavailable when git cannot run.

    `GIT_OPTIONAL_LOCKS=0` is the reason this is not `_worktrees._git`: that one
    decodes text and may let a read refresh the index, and this file's contract is
    that the phase tree's index file is not rewritten."""
    if not shutil.which("git"):
        raise GitUnavailable("git is not on PATH")
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(["git", "-C", cwd] + list(args), input=stdin,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=120)
    except Exception as exc:
        raise GitUnavailable("%s" % (exc,))
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


def _git_ok(cwd, args):
    code, out, err = _git(cwd, args)
    if code != 0:
        raise GitUnavailable("git %s failed in %s: %s"
                             % (" ".join(args), cwd, err.strip()))
    return out


def _nul_list(raw):
    return [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]


# --- the facts (I/O) ---------------------------------------------------------------
def state_file(git_root):
    """The state file's path: in the phase tree's git directory, so no `git status`
    sees it and no commit can carry it."""
    rel = _git_ok(git_root, ["rev-parse", "--git-path", STATE_NAME]).decode().strip()
    return rel if os.path.isabs(rel) else os.path.join(git_root, rel)


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data.get("tasks") if isinstance(data.get("tasks"), dict) else {}


def _save_state(path, tasks):
    _mio.atomic_write_text(path, json.dumps({"version": 1, "tasks": tasks},
                                            indent=2, sort_keys=True) + "\n")


def record_paths(manifest, phase, manifest_path, project, git_root):
    """Git-root-relative paths (files or directories) that are RECORD, not work: the
    manifest pair, the journal directory and the evidence directory - the same
    three `commit-task-work` stages besides the declared files."""
    config = _journal_io.load_config(project)
    index_abs, phase_abs = _invariants.manifest_files(manifest_path, phase)
    found = []
    for absolute in (index_abs, phase_abs, _journal_io.journal_dir(project, config),
                     _evidence_io.evidence_dir(project, config)):
        rel = os.path.relpath(absolute, git_root).replace(os.sep, "/")
        if not rel.startswith("..") and rel not in found:
            found.append(rel)
    return found


def _is_record(path, records):
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in records)


def task_tree(git_root, task_id):
    """(record, path) of the worktree whose marker names THIS task, else (None, why)."""
    listing = _wt.list_worktrees(git_root)
    if listing["error"]:
        raise GitUnavailable(listing["error"])
    for rec in listing["trees"]:
        if rec.get("isMain") or not rec.get("path"):
            continue
        prov = _wt.read_provenance(rec["path"], expect_task=str(task_id))
        if prov["ours"] is True:
            return prov["record"], rec["path"]
    return None, "no worktree is marked for task %r" % (task_id,)


def task_changes(tree, base):
    """{path: "D" | "M"} - what the task really changed against the base, from the
    tree's own index. Ignored files are not here, which is what `add -A` means."""
    _git_ok(tree, ["add", "-A"])
    raw = _git_ok(tree, ["diff", "--cached", "--name-status", "-z",
                         "--no-renames", base])
    items = _nul_list(raw)
    return {items[i + 1]: ("D" if items[i].startswith("D") else "M")
            for i in range(0, len(items) - 1, 2)}


def _untracked(root):
    return _nul_list(_git_ok(root, ["ls-files", "-o", "--exclude-standard", "-z"]))


def changed_since(root, rev):
    """Paths whose working-tree bytes differ from `rev` in `root`."""
    return set(_nul_list(_git_ok(root, ["diff", "--name-only", "-z",
                                        "--no-renames", rev]))) | set(_untracked(root))


def dirty_paths(root):
    """Paths that differ from HEAD (staged or not) plus untracked ones."""
    return set(_nul_list(_git_ok(root, ["diff", "--name-only", "-z",
                                        "--no-renames", "HEAD"]))) | set(_untracked(root))


def _file_bytes(root, rel):
    """The file's bytes, ("link", target) for a symlink, or None when absent."""
    path = os.path.join(root, rel)
    if os.path.islink(path):
        return ("link", os.readlink(path))
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _base_bytes(root, base, rel):
    code, out, _err = _git(root, ["show", "%s:%s" % (base, rel)])
    return out if code == 0 else None


# --- the decisions (pure over bytes) ------------------------------------------------
def undeclared_paths(declared, paths):
    """The paths no declared entry covers, sorted."""
    return sorted(p for p in paths
                  if not any(_task_outputs.covers(d, p) for d in declared))


def attribution(entries, task_id, base, path):
    """The other tasks of THIS wave (same base) whose integration wrote `path`."""
    return sorted(t for t, e in entries.items()
                  if t != task_id and e.get("base") == base
                  and path in (e.get("paths") or []))


def merge_bytes(current, base, other):
    """(bytes, None) for a clean three-way result, or (None, why).

    Equal sides and a side equal to the base need no text merge; a deletion against
    an edit is a conflict; anything else is `git merge-file`, whose refusal of
    binary content is a conflict too."""
    if current == other:
        return other, None
    if current == base:
        return other, None
    if other == base:
        return current, None
    if not isinstance(current, bytes) or not isinstance(other, bytes) \
            or not isinstance(base, (bytes, type(None))):
        return None, "one side is deleted, absent at the base or a link"
    scratch = tempfile.mkdtemp(prefix="integrate-")
    try:
        names = []
        for name, body in (("current", current), ("base", base or b""),
                           ("other", other)):
            names.append(os.path.join(scratch, name))
            with open(names[-1], "wb") as fh:
                fh.write(body)
        code, out, err = _git(scratch, ["merge-file", "-p"] + names)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if code == 0:
        return out, None
    return None, ("%d conflicting hunk(s)" % code if 0 < code < 128
                  else "git merge-file refused: %s" % (err.strip() or "binary content"))


# --- the answer --------------------------------------------------------------------
def _answer(task_id, phase_id, **fields):
    base = {"task": task_id, "phaseId": phase_id, "tree": None, "base": None,
            "headBefore": None, "paths": [], "already": False, "regate": False,
            "overlapWith": [], "discarded": [], "widened": [], "refused": None,
            "decision": None, "error": None, "sentence": ""}
    base.update(fields)
    return base


def _refuse(answer, kind, paths, tasks, reason):
    refused = {"kind": kind, "paths": sorted(paths), "tasks": sorted(set(tasks)),
               "reason": reason}
    return E_REFUSED, dict(answer, refused=refused,
                           sentence="integration refused (%s): %s" % (kind, reason))


# --- the operation -------------------------------------------------------------------
def integrate(manifest, phase, task, manifest_path, project, git_root,
              undeclared=None):
    """`(exitCode, answer)` - integrate one task tree, or say why not. Prints nothing.

    Every refusal is reached BEFORE the first byte is written, so a refused task
    leaves the phase tree exactly as it found it."""
    task_id, phase_id = str(task.get("id")), str((phase or {}).get("id"))
    answer = _answer(task_id, phase_id)
    try:
        return _integrate(manifest, phase, task, manifest_path, project, git_root,
                          undeclared, answer)
    except GitUnavailable as exc:
        return E_NO_BASIS, dict(answer, error=str(exc),
                                sentence="could not be asked: %s" % (exc,))


def _integrate(manifest, phase, task, manifest_path, project, git_root, undeclared,
               answer):
    task_id = answer["task"]
    marker, tree = task_tree(git_root, task_id)
    if marker is None:
        return _refuse(answer, "no-task-tree", [], [task_id], tree)
    base = marker.get("base")
    if not base:
        return _refuse(answer, "no-task-tree", [], [task_id],
                       "the marker of %s records no base commit" % (tree,))
    head = _git_ok(git_root, ["rev-parse", "HEAD"]).decode().strip()
    answer = dict(answer, tree=tree, base=base, headBefore=head)
    sfile = state_file(git_root)
    entries = _load_state(sfile)
    own = entries.get(task_id) or {}
    if own.get("base") != base:
        own = {}
    if own.get("status") == "done":
        return E_OK, dict(answer, already=True, paths=own.get("paths") or [],
                          regate=own.get("regate"),
                          overlapWith=own.get("overlapWith") or [],
                          sentence="task %s is already integrated (recorded for "
                                   "base %s)" % (task_id, base[:12]))
    records = record_paths(manifest, phase, manifest_path, project, git_root)

    changes = {p: s for p, s in task_changes(tree, base).items()
               if not _is_record(p, records)}
    paths = sorted(changes)
    answer["paths"] = paths
    if not paths:
        entries[task_id] = {"base": base, "paths": [], "status": "done",
                            "regate": False, "overlapWith": []}
        _save_state(sfile, entries)
        return E_OK, dict(answer, sentence="task %s changed nothing outside the "
                                           "record paths; nothing to integrate"
                          % (task_id,))

    others = {t: e for t, e in entries.items()
              if t != task_id and e.get("base") == base}
    accounted = set(own.get("paths") or [])
    for entry in others.values():
        accounted.update(entry.get("paths") or [])

    # The bytes may already be there with the state file lost.
    if not own and not any(attribution(entries, task_id, base, p) for p in paths) \
            and all(_file_bytes(git_root, p) == _file_bytes(tree, p)
                    for p in paths) and set(paths) <= changed_since(git_root, base):
        entries[task_id] = {"base": base, "paths": paths, "status": "done",
                            "regate": None, "overlapWith": []}
        _save_state(sfile, entries)
        return E_OK, dict(answer, already=True, regate=None,
                          sentence="task %s is already integrated: the phase tree "
                                   "holds exactly its bytes at every changed path "
                                   "(the state file was lost, so whether it needs "
                                   "a re-gate is unknown - re-gate)" % (task_id,))

    stray = sorted(p for p in dirty_paths(git_root)
                   if not _is_record(p, records) and p not in accounted)
    if stray:
        return _refuse(answer, "dirty", stray, [task_id],
                       "the phase tree holds changes that are neither record paths "
                       "nor another integration's: %s" % (", ".join(stray),))

    moved = changed_since(git_root, base)
    clash = sorted(p for p in paths if p in moved and not _is_record(p, records)
                   and (p not in set(own.get("paths") or [])
                        or attribution(entries, task_id, base, p)))
    siblings = {}
    for path in clash:
        siblings[path] = attribution(entries, task_id, base, path) or [NO_SIBLING]
    involved = [t for names in siblings.values() for t in names] + [task_id]
    locked = [p for p in clash if _wave.is_non_mergeable(p)]
    if locked:
        return _refuse(answer, "non-mergeable", locked, involved,
                       "%s changed by more than one task; a lockfile is machine-"
                       "written and a text merge of two is not a file any tool "
                       "wrote" % (", ".join(locked),))

    results, conflicts = {}, {}
    for path in paths:
        mine = _file_bytes(tree, path)
        if path not in clash:
            results[path] = mine
            continue
        merged, why = merge_bytes(_file_bytes(git_root, path),
                                  _base_bytes(git_root, base, path), mine)
        if why:
            conflicts[path] = why
        else:
            results[path] = merged
    if conflicts:
        return _refuse(answer, "conflict", conflicts, involved,
                       "; ".join("%s: %s" % (p, w) for p, w in sorted(conflicts.items())))

    extra = undeclared_paths(task.get("files") or [], paths)
    if extra and undeclared is None:
        return E_DECIDE, dict(answer, decision={
            "kind": "undeclared-change", "options": list(CHOICES), "paths": extra},
            sentence="task %s changed %d path(s) it does not declare: %s - choose "
                     "widen, discard or block (the task tree is removed after "
                     "integration)" % (task_id, len(extra), ", ".join(extra)))
    if extra and undeclared == "block":
        return _refuse(answer, "undeclared", extra, [task_id],
                       "undeclared paths, blocked on request: %s" % (", ".join(extra),))
    discarded = extra if undeclared == "discard" else []
    widened = extra if undeclared == "widen" else []
    for path in discarded:
        results.pop(path, None)

    written = sorted(results)
    overlap_with = sorted(set(t for p in written for t in siblings.get(p, [])))
    regate = any(p in siblings for p in written)
    entries[task_id] = {"base": base, "paths": written, "status": "writing",
                        "regate": regate, "overlapWith": overlap_with}
    _save_state(sfile, entries)
    for path in written:
        _place(git_root, tree, path, results[path])
    entries[task_id]["status"] = "done"
    _save_state(sfile, entries)
    return E_OK, dict(answer, paths=written, regate=regate,
                      overlapWith=overlap_with, discarded=discarded, widened=widened,
                      sentence="integrated %d path(s) of task %s%s"
                               % (len(written), task_id,
                                  "; overlaps %s, so it needs a re-gate on the "
                                  "integrated tree" % (", ".join(overlap_with),)
                                  if regate else ""))


def _place(git_root, tree, path, content):
    """Write one result into the phase tree's working tree (never its index)."""
    target = os.path.join(git_root, path)
    if content is None:
        if os.path.lexists(target):
            os.remove(target)
        return
    if not os.path.isdir(os.path.dirname(target)):
        os.makedirs(os.path.dirname(target))
    if os.path.lexists(target):
        os.remove(target)
    if isinstance(content, tuple):
        os.symlink(content[1], target)
        return
    with open(target, "wb") as fh:
        fh.write(content)
    source = os.path.join(tree, path)
    if os.path.isfile(source) and not os.path.islink(source):
        shutil.copymode(source, target)


# --- the command -----------------------------------------------------------------------
def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="integrate-task.py", add_help=True, allow_abbrev=False,
        description="Carry one task tree's work into the phase tree, or refuse by "
                    "name.")
    parser.add_argument("manifest")
    parser.add_argument("task")
    parser.add_argument("--project", default=".",
                        help="the directory holding .claude/ and the records "
                             "(default: the current directory)")
    parser.add_argument("--undeclared", choices=CHOICES, default=None,
                        help="what to do with changed paths the task does not "
                             "declare; without it they are a decision (exit 3)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return _claude_home.attach_usage_hint(parser)


def render(answer, out=print):
    out("%s %s" % (PREFIX, answer.get("sentence")))
    refused = answer.get("refused") or {}
    if refused:
        out("  tasks: %s" % (", ".join(refused.get("tasks") or []),))
        out("  paths: %s" % (", ".join(refused.get("paths") or []),))
    decision = answer.get("decision") or {}
    if decision:
        out("  decide: %s -> rerun with --undeclared <%s>"
            % (", ".join(decision.get("paths") or []), "|".join(CHOICES)))
    for key in ("discarded", "widened"):
        if answer.get(key):
            out("  %s: %s" % (key, ", ".join(answer[key])))
    if answer.get("regate"):
        out("  regate: true")


def main(argv, out=print):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else E_OK
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args.manifest, exc))
        return E_USAGE
    phase, task = None, None
    for candidate_phase, candidate_task in _mio.iter_tasks(manifest):
        if str(candidate_task.get("id")) == str(args.task):
            phase, task = candidate_phase, candidate_task
            break
    if task is None:
        sys.stderr.write("ERROR: no task %r in %s\n" % (args.task, args.manifest))
        return E_USAGE
    project = os.path.abspath(args.project)
    git_root = _invariants.git_root_for(manifest, project)
    code, answer = integrate(manifest, phase, task, args.manifest, project, git_root,
                             undeclared=args.undeclared)
    if args.as_json:
        out(json.dumps(answer, indent=2, sort_keys=True))
    else:
        render(answer, out=out)
    return code


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        print("integrate-task.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_integrate_task.py - run that file "
              "instead.")
        sys.exit(0)
    raise SystemExit(main(sys.argv[1:]))
