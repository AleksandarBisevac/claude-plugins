#!/usr/bin/env python3
"""
The cases for `_live_copy.py` - the one reader of a phase in flight - and the
scratch repository the panel's and the report's suites read it against.

WHY THE FIXTURE LIVES HERE. `test__panel_state.py` and `test_render_report.py`
each ask the same question this module answers - what does a surface show for a
phase finished in a linked worktree - and a repository built three ways would be
three ideas of what such a worktree looks like. `worktree_fixture` is the one,
and those suites import it from this file.

`_live_copy` itself is imported INSIDE the cases rather than at the top, so a
suite that only wants the fixture can import this file on a tree where the
module does not exist yet, and its own cases fail by name instead of the
import taking the whole file down.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import importlib
import json
import os
import shutil
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402
import _status_facts                               # noqa: E402

# The names the reader is made of. `audit-status.py` used to define every one of
# them; the move is only a move if it now defines none of them, and binds each
# name it still calls by to this module's own object.
CALLED_NAMES = ("in_flight", "flight_for")
READER_NAMES = ("in_flight", "live_reads", "flight_for", "worktree_view",
                "_live_read", "_worked_elsewhere", "_tree_copy", "_branch_copy",
                "_show_phase", "_readiness_moved", "_held_locks",
                "_branch_names", "_phase_body", "_own_read", "_fallback",
                "_shard_rel", "_here_words")


def _git_cmd():
    return ["git", "-c", "user.email=t@t.t", "-c", "user.name=t",
            "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def _write_shard(base, pid, title, status, tasks):
    path = os.path.join(base, "docs", "audit", "phases", "%s.json" % (pid,))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"id": pid, "title": title, "status": status,
                   "tasks": tasks}, fh)


def _p1_tasks(first):
    return [{"id": "P1.1", "title": "first", "status": first,
             "bugId": "BUG-1"},
            {"id": "P1.2", "title": "second", "status": "pending",
             "dependsOn": ["P1.1"]}]


def worktree_fixture(root, linked, cross=False):
    """`{"repo", "manifest", "tree"}` - a git repository on `main` whose own
    copy of the plan says nothing has started.

    P1 holds P1.1 and P1.2, which waits on P1.1; P2 holds P2.1; a high bug is
    fixed by P1.1. With `linked`, P1's branch is out in a linked worktree that
    committed P1.1 done, so the copy holding P1 live has P1.2 ready and P1.1
    finished while this checkout's copy still lists P1.1 as ready and the bug
    as open. Without it there is no branch and no worktree: the twin.

    With `cross`, P2.1 depends on P1.1, so a task of another phase is made
    ready by the work the worktree did - the dependency a ready list has to
    name the copy of even though no task of P1 is the one listed.

    The values are chosen so the two copies disagree on every list a surface
    prints - the ready list, P1's done count and the copy note - and a surface
    reading the wrong copy cannot pass by accident.
    """
    repo = os.path.join(root, "proj")
    os.makedirs(os.path.join(repo, "docs", "audit", "phases"))
    git = _git_cmd()

    def sh(*args, **kw):
        subprocess.run(git + list(args), cwd=kw.get("cwd", repo), check=True,
                       capture_output=True, timeout=60)

    manifest = os.path.join(repo, "docs", "audit", "audit-plan.json")
    with open(os.path.join(repo, "README"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"version": 3, "title": "live copy"},
                   "phases": [{"id": "P1", "title": "fixer",
                               "status": "pending",
                               "shard": "phases/P1.json"},
                              {"id": "P2", "title": "other",
                               "status": "pending",
                               "shard": "phases/P2.json"}],
                   "bugs": [{"id": "BUG-1", "title": "high one",
                             "severity": "high", "status": "open",
                             "taskId": "P1.1"}]}, fh)
    _write_shard(repo, "P1", "fixer", "pending", _p1_tasks("pending"))
    p21 = {"id": "P2.1", "title": "t", "status": "pending"}
    if cross:
        p21["dependsOn"] = ["P1.1"]
    _write_shard(repo, "P2", "other", "pending", [p21])
    sh("init", "-q")
    sh("add", "-A")
    sh("commit", "-qm", "the plan")
    tree = None
    if linked:
        sh("branch", "audit/p1-fixer")
        tree = os.path.join(root, "p1-tree")
        sh("worktree", "add", "-q", tree, "audit/p1-fixer")
        _write_shard(tree, "P1", "fixer", "in_progress", _p1_tasks("done"))
        sh("commit", "-qam", "P1.1 done", cwd=tree)
    return {"repo": repo, "manifest": manifest, "tree": tree}


def _reader():
    """`(module, None)` or `(None, why)` - the reader, imported where the case
    can say it is missing."""
    try:
        return importlib.import_module("_live_copy"), None
    except Exception as exc:                                   # noqa: BLE001
        return None, "%s: %s" % (type(exc).__name__, exc)


def _moved_cases(check):
    lc, why = _reader()
    status = _loader.load_script("audit-status.py", modname="audit_status_lc")
    same = [n for n in CALLED_NAMES
            if lc is not None and getattr(status, n, None) is getattr(lc, n, 1)]
    check("lc1 every name of the reader `audit-status.py` calls it by is "
          "`_live_copy`'s own object - one reader, reached from the entry point",
          lc is not None and len(same) == len(CALLED_NAMES),
          "missing=%r why=%r" % (sorted(set(CALLED_NAMES) - set(same)), why))
    tree = ast.parse(_harness.module_source(status))
    defined = sorted(n.name for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name in READER_NAMES)
    check("lc2 ...and `audit-status.py` defines none of them: the reader was "
          "moved, not copied", defined == [], "still defined: %r" % (defined,))


def _overlay_cases(check):
    own = {"meta": {"version": 2},
           "phases": [{"id": "P1", "status": "pending",
                       "tasks": [{"id": "P1.1", "status": "pending"}]},
                      {"id": "P2", "status": "pending",
                       "tasks": [{"id": "P2.1", "status": "pending"}]}]}
    body = {"id": "P1", "status": "in_progress",
            "tasks": [{"id": "P1.1", "status": "done"}]}
    flight = {"reads": {"P1": {"body": body, "live": True, "own": False,
                               "counted": True, "basis": "the worktree file X"}},
              "unread": {"P2": {"live": False, "basis": "shows this checkout's "
                                                        "copy - not read"}},
              "note": "the worktree list could not be asked",
              "error": ""}
    view = getattr(_status_facts, "live_view", None)
    got = view(own, flight) if view else {}
    plan = got.get("plan") or {}
    copies = got.get("copies") or {}
    check("lv1 `live_view` lays a read body over the plan, names each copy a "
          "row was read from or fell back to, keeps this checkout's plan as "
          "`own` and carries what could not be asked",
          view is not None
          and plan.get("phases", [{}])[0].get("status") == "in_progress"
          and copies.get("P1", {}).get("basis") == "read from the worktree file X"
          and copies.get("P1", {}).get("live") is True
          and copies.get("P2", {}).get("live") is False
          and got.get("own") is own
          and got.get("note") == "the worktree list could not be asked"
          and own["phases"][0]["status"] == "pending",
          "got=%r" % (got,))
    empty = view(own, {"reads": {}, "unread": {}, "note": ""}) if view else {}
    check("lv2 ...and its twin: nothing in flight is this checkout's plan, no "
          "copy named, no `own` and no note",
          view is not None and empty.get("plan") == own
          and empty.get("copies") == {} and empty.get("own") is None
          and empty.get("note") == "",
          "got=%r" % (empty,))
    failed = view(own, {"held": None, "reads": {}, "unread": {}, "note": "",
                        "error": "could not be asked (boom)"}) if view else {}
    check("lv3 a reader that failed is said, not swallowed: its error is the "
          "note", view is not None
          and failed.get("note") == "could not be asked (boom)",
          "got=%r" % (failed,))


def _reader_cases(check):
    labels = ("lr1", "lr2")
    if not shutil.which("git"):
        for lbl in labels:
            _harness.skip(check, lbl, "git is not on PATH, and the worktree "
                          "and the branch live in git", True)
        return
    lc, why = _reader()
    root = _harness.fixture_root("live-copy-reader-")
    try:
        fx = worktree_fixture(os.path.join(root, "linked"), True)
        manifest = _mio.load_manifest(fx["manifest"])
        flight = (lc.flight_for(manifest, fx["manifest"], fx["repo"])
                  if lc else {})
        read = (flight.get("reads") or {}).get("P1") or {}
        tasks = (read.get("body") or {}).get("tasks") or []
        check("lr1 a phase whose branch a linked worktree has out is read from "
              "that worktree's file, and the read names it",
              lc is not None and "p1-tree" in str(read.get("basis"))
              and [t.get("status") for t in tasks] == ["done", "pending"],
              "why=%r flight=%r" % (why, flight))
        fx2 = worktree_fixture(os.path.join(root, "alone"), False)
        alone = (lc.flight_for(_mio.load_manifest(fx2["manifest"]),
                               fx2["manifest"], fx2["repo"]) if lc else {})
        check("lr2 ...and its twin: with no branch and no worktree nothing is "
              "read and nothing is said",
              lc is not None and alone.get("reads") == {}
              and not alone.get("unread") and not alone.get("note")
              and not alone.get("error"),
              "flight=%r" % (alone,))
    finally:
        _harness.remove_tree(root)


def _lookup_cases(check):
    """A lock directory that could not be looked up is not the absence of a
    repository. Both make `_locks.lock_dir` answer None; only the second means
    nothing can be in flight, so only the first may reach a surface as a
    sentence - and the second must stay silent, or every project outside git
    would print a failure it does not have."""
    labels = ("lk1", "lk2")
    if not shutil.which("git"):
        for lbl in labels:
            _harness.skip(check, lbl, "git is not on PATH, and the lookup is "
                          "a git call", True)
        return
    lc, why = _reader()
    root = _harness.fixture_root("live-copy-lookup-")
    plan = {"meta": {"version": 3}, "phases": []}
    try:
        broken = os.path.join(root, "broken")
        os.makedirs(broken)
        # A checkout whose `.git` names a git directory that is gone - a
        # worktree whose main clone was moved is the ordinary way to get one.
        with open(os.path.join(broken, ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: %s\n" % os.path.join(root, "gone", "worktrees",
                                                   "x"))
        got = lc.in_flight(plan, None, broken) if lc else {}
        note = (_status_facts.live_view(plan, got).get("note")
                if lc else "")
        check("lk1 a lock directory whose lookup failed is said in the note, "
              "with git's own answer, and is not read as no repository",
              lc is not None and got.get("scheme") is not False
              and "lock directory" in str(got.get("error"))
              and "rev-parse" in str(got.get("error"))
              and "lock directory" in str(note),
              "why=%r got=%r" % (why, got))
        plain = os.path.join(root, "plain")
        os.makedirs(plain)
        none = lc.in_flight(plan, None, plain) if lc else {}
        check("lk2 ...and its twin: a directory in no repository has no lock "
              "scheme and nothing to say",
              lc is not None and none.get("scheme") is False
              and not none.get("error") and not none.get("note")
              and _status_facts.live_view(plan, none).get("note") == "",
              "got=%r" % (none,))
    finally:
        _harness.remove_tree(root)


def _selftest():
    def body(check):
        _harness.stage(check, "lc", _moved_cases)
        _harness.stage(check, "lv", _overlay_cases)
        _harness.stage(check, "lr", _reader_cases)
        _harness.stage(check, "lk", _lookup_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__live_copy.py --selftest\n")
    raise SystemExit(2)
