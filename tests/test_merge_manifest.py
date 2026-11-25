#!/usr/bin/env python3
"""
The cases for `merge-manifest.py` - the driver git calls, and the install behind it.

Most of these drive REAL git in throwaway repositories, because the property worth
having is a fact about git: what the file holds after `git merge` returns. A driver
unit-tested against its own idea of git would pass while git kept %A as ours with
no markers - the one outcome this file exists to make impossible. The record merge
itself is `test__manifest_merge.py`'s; here it is only exercised end to end.

Git is invoked with identity and config on the command line and HOME pointed at the
scratch directory, so nothing reads or writes the operator's git configuration.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402
import _loader                                     # noqa: E402
import _manifest_io as _mio                        # noqa: E402

M = _loader.load_script("merge-manifest.py", modname="merge_manifest")


# --- fixtures -----------------------------------------------------------------
def _plan():
    """A minimal plan the validator passes clean."""
    return {
        "meta": {"version": 2, "repo": "demo"},
        "phases": [
            {"id": "P1", "title": "One", "status": "pending",
             "tasks": [{"id": "P1.1", "title": "a", "status": "pending",
                        "files": ["src/a.ts"]}]},
            {"id": "BF10", "title": "Ten", "status": "pending",
             "tasks": [{"id": "BF10.1", "title": "b", "status": "pending",
                        "files": ["src/b.ts"]}]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"], "src/b.ts": ["BF10.1"]},
        "bugs": [],
    }


def _add_phase(doc, pid, path):
    d = copy.deepcopy(doc)
    d["phases"].append({"id": pid, "title": "phase " + pid, "status": "pending",
                        "tasks": [{"id": pid + ".1", "title": "t", "status": "pending",
                                   "files": [path]}]})
    d["fileIndex"][path] = [pid + ".1"]
    return d


def _add_bug(doc, bid):
    d = copy.deepcopy(doc)
    d["bugs"].append({"id": bid, "title": "bug " + bid, "severity": "low",
                      "status": "open"})
    return d


def _env(home):
    env = dict(os.environ)
    env.update({"HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return env


def _git(repo, env, *args):
    r = subprocess.run(["git", "-C", repo] + list(args), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


def _write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_mio.json_document(doc))


def _repo(root, name, env, base_doc):
    repo = os.path.join(root, name)
    os.makedirs(repo)
    _git(repo, env, "init", "-q", "-b", "main")
    _write_json(os.path.join(repo, "docs", "audit", "plan.json"), base_doc)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-qm", "base")
    return repo, os.path.join(repo, "docs", "audit", "plan.json")


def _branches(repo, env, plan_path, ours_doc, theirs_doc):
    _git(repo, env, "checkout", "-qb", "side")
    _write_json(plan_path, theirs_doc)
    _git(repo, env, "commit", "-qam", "theirs")
    _git(repo, env, "checkout", "-q", "main")
    _write_json(plan_path, ours_doc)
    _git(repo, env, "commit", "-qam", "ours")


def _install(plan_path, root=None):
    held = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = io.StringIO()
    try:
        return M.install(plan_path, root or _output.PLUGIN_ROOT)
    finally:
        sys.stdout, sys.stderr = held


def _driver_files(tmp, name, base, ours, theirs):
    d = os.path.join(tmp, name)
    os.makedirs(d)
    paths = []
    for tag, doc in (("O", base), ("A", ours), ("B", theirs)):
        p = os.path.join(d, tag)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(doc if isinstance(doc, str) else _mio.json_document(doc))
        paths.append(p)
    return paths


def _run_driver(paths, label="docs/audit/plan.json"):
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.driver_main(paths + [label])
        return code, sys.stderr.getvalue()
    finally:
        sys.stderr = held


# --- cases --------------------------------------------------------------------
def _cases(check):
    tmp = tempfile.mkdtemp(prefix="merge-manifest-selftest-")
    try:
        _driver_cases(check, tmp)
        ran, why = _harness.attempt(_driver_twice_cases, check, tmp)
        if not ran:
            check("mk0 the driver's key-written-twice block ran to its end "
                  "(%s)" % (why,), False)
        _merge_parse_cases(check)
        _install_cases(check, tmp)
        _git_cases(check, tmp)
    finally:
        _harness.remove_tree(tmp)


def _driver_cases(check, tmp):
    base = _plan()
    o, t = _add_phase(base, "BF12", "src/c.ts"), _add_phase(base, "BF11", "src/d.ts")
    paths = _driver_files(tmp, "d1", base, o, t)
    code, err = _run_driver(paths)
    merged = json.loads(open(paths[1], encoding="utf-8").read())
    check("mm1 the driver merges two appended phases into %A and exits 0",
          code == 0 and [p["id"] for p in merged["phases"]] == ["P1", "BF10", "BF11", "BF12"],
          "%s %s" % (code, err))
    check("mm2 ...and says what it merged and that it validated, with the counts",
          "ours 1, theirs 1 record(s) changed" in err and "no new findings" in err, err)

    # A real conflict: exit 1, and %A carries ONE marker block.
    o2 = copy.deepcopy(o)
    o2["phases"][0]["title"] = "ours"
    t2 = copy.deepcopy(t)
    t2["phases"][0]["title"] = "theirs"
    paths = _driver_files(tmp, "d2", base, o2, t2)
    code, err = _run_driver(paths)
    text = open(paths[1], encoding="utf-8").read()
    check("mm3 a real conflict exits 1 with one marker block naming the record by id",
          code == 1 and text.count("<<<<<<< ") == 1 and "phases[P1].title" in text
          and "phases[P1].title" in err, "%s\n%s" % (err, text))

    # Unreadable JSON on one side: git's line merge, with markers - never ours alone.
    paths = _driver_files(tmp, "d3", "{\n}\n", '{\n  "a": 1\n}\n', '{\n  "a": 2,\n')
    code, err = _run_driver(paths)
    text = open(paths[1], encoding="utf-8").read()
    check("mm4 a side that is not JSON falls back to a line merge WITH markers, exit 1",
          code == 1 and "<<<<<<< ours" in text and "not valid JSON" in err,
          "%s\n%s" % (err, text))

    # A crash inside the record merge still writes markers.
    paths = _driver_files(tmp, "d4", base, o2, t2)
    real = M._manifest_merge.merge3

    def boom(*a):
        raise RuntimeError("planted")
    M._manifest_merge.merge3 = boom
    try:
        code, err = _run_driver(paths)
    finally:
        M._manifest_merge.merge3 = real
    text = open(paths[1], encoding="utf-8").read()
    check("mm5 an exception inside the merge still leaves conflict markers in %A, exit 1",
          code == 1 and "<<<<<<< ours" in text and "planted" in err, "%s\n%s" % (err, text))

    # A NEW finding from a clean record merge: exit 1 and name it. Each side mints
    # task `P1.2` - ours inside P1, theirs inside BF10. Two different lists, so
    # the record merge keeps both, and the duplicate exists only in the result.
    o3 = copy.deepcopy(base)
    o3["phases"][0]["tasks"].append({"id": "P1.2", "title": "o", "status": "pending",
                                     "files": []})
    t3 = copy.deepcopy(base)
    t3["phases"][1]["tasks"].append({"id": "P1.2", "title": "t", "status": "pending",
                                     "files": []})
    paths = _driver_files(tmp, "d5", base, o3, t3)
    code, err = _run_driver(paths)
    check("mm6 a clean record merge whose result carries a finding NEITHER side had "
          "exits 1 and names it",
          code == 1 and "neither side had" in err and "P1.2" in err, err)

    # An add/add: git hands the driver an EMPTY %O. For a plan file that is a merge
    # against nothing; for a shard it is one phase id minted on two branches.
    paths = _driver_files(tmp, "d7", "", o, t)
    code, err = _run_driver(paths)
    merged = open(paths[1], encoding="utf-8").read()
    check("mm21 an EMPTY base (git's add/add) is not reported as invalid JSON - the plan "
          "merges by record against an empty one",
          "not valid JSON" not in err and "<<<<<<<" not in merged
          and "BF11" in merged and "BF12" in merged, "%s\n%s" % (err, merged))
    shard_o = {"id": "P7", "title": "ours", "tasks": [{"id": "P7.1", "title": "a"}]}
    shard_t = {"id": "P7", "title": "theirs", "tasks": [{"id": "P7.1", "title": "b"}]}
    paths = _driver_files(tmp, "d8", "", shard_o, shard_t)
    code, err = _run_driver(paths, "docs/audit/phases/P7.json")
    merged = open(paths[1], encoding="utf-8").read()
    check("mm22 ...but a SHARD created on both sides is one phase id minted twice: a "
          "conflict that says so, never two phases' bodies merged into one",
          code == 1 and "created on both sides" in err and "<<<<<<<" in merged,
          "%s\n%s" % (err, merged))

    # SECOND DIRECTION: a finding every side already had does not block the merge.
    bad = copy.deepcopy(base)
    bad["phases"][1]["tasks"][0]["id"] = "P1.1"
    ours_bad2 = _add_bug(bad, "BUG-1")
    theirs_ok = _add_phase(bad, "P5", "src/q.ts")
    paths = _driver_files(tmp, "d6", bad, ours_bad2, theirs_ok)
    code, err = _run_driver(paths)
    check("mm7 SECOND DIRECTION: a finding already present on a side does not make the "
          "merge fail", code == 0 and "no new findings" in err, err)


def _install_cases(check, tmp):
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    env = _env(home)
    repo, plan = _repo(tmp, "inst", env, _plan())
    attrs = os.path.join(repo, ".gitattributes")
    with open(attrs, "w", encoding="utf-8") as fh:
        fh.write("*.png binary\n")
    held = os.environ.copy()
    os.environ.update(env)
    try:
        code, msg = _install(plan)
        first = open(attrs, encoding="utf-8").read()
        check("mm8 install appends the driver lines for the plan AND its shard directory "
              "below the lines already there",
              code == 0 and first.startswith("*.png binary\n")
              and "docs/audit/plan.json merge=audit-manifest" in first
              and "docs/audit/phases/*.json merge=audit-manifest" in first, first)
        _c, drv = _git(repo, env, "config", "--get", "merge.audit-manifest.driver")
        common = os.path.realpath(os.path.join(repo, ".git"))
        shim = os.path.join(common, "audit", "merge-manifest.sh")
        check("mm9 ...configures this clone's driver to the shim under the git common dir, "
              "never to a path inside the versioned plugin cache",
              shim in drv and _output.PLUGIN_ROOT not in drv and os.path.isfile(shim), drv)
        check("mm10 ...and the shim records the plugin root it came from",
              "AUDIT_PLUGIN_ROOT='%s'" % (_output.PLUGIN_ROOT,) in open(shim).read())
        _install(plan)
        check("mm11 a second install changes nothing (idempotent)",
              open(attrs, encoding="utf-8").read() == first)
        code, text = M.status(plan)
        check("mm12 status reads every piece back and reports installed, exit 0",
              code == 0 and "installed for docs/audit/plan.json" in text, text)
        M.uninstall(plan)
        code, text = M.status(plan)
        check("mm13 uninstall removes the lines, the config and the shim, keeping the "
              "lines it did not write",
              open(attrs, encoding="utf-8").read() == "*.png binary\n"
              and not os.path.isfile(shim) and code == 1
              and _git(repo, env, "config", "--get", "merge.audit-manifest.driver")[0] != 0,
              text)
        _install(plan, root=os.path.join(tmp, "gone"))
        code, text = M.status(plan)
        check("mm14 status says a shim whose plugin root is gone is stale, exit 1",
              code == 1 and "re-run install" in text, text)
        M.uninstall(plan)

        # A CRLF .gitattributes (a Windows checkout) keeps its line endings: the
        # install owns three lines, not the file's spelling.
        crlf = b"*.png binary\r\n*.jpg binary\r\n"
        with open(attrs, "wb") as fh:
            fh.write(crlf)
        _install(plan)
        raw = open(attrs, "rb").read()
        check("mm23 install into a CRLF .gitattributes writes CRLF on every line, its "
              "own included",
              raw.startswith(crlf) and b"merge=audit-manifest\r\n" in raw
              and raw.count(b"\n") == raw.count(b"\r\n"), raw)
        M.uninstall(plan)
        check("mm24 ...and uninstall gives back the exact bytes it found",
              open(attrs, "rb").read() == crlf, open(attrs, "rb").read())
    finally:
        os.environ.clear()
        os.environ.update(held)


def _merge(repo, env, plan):
    code, out = _git(repo, env, "merge", "-q", "side", "-m", "merge")
    return code, out, open(plan, encoding="utf-8").read()


def _git_cases(check, tmp):
    home = os.path.join(tmp, "home-git")
    os.makedirs(home)
    env = _env(home)
    held = os.environ.copy()
    os.environ.update(env)
    try:
        base = _plan()
        ours = _add_bug(_add_phase(base, "BF12", "src/c.ts"), "BUG-2")
        theirs = _add_bug(_add_phase(base, "BF11", "src/d.ts"), "BUG-3")

        # Control: without the driver this is the reporter's conflict.
        repo, plan = _repo(tmp, "g0", env, base)
        _branches(repo, env, plan, ours, theirs)
        code, out, _t = _merge(repo, env, plan)
        check("mm15 CONTROL: without the driver, two appended phases and bugs conflict "
              "(the field report, reproduced)", code != 0 and "CONFLICT" in out, out)

        repo, plan = _repo(tmp, "g1", env, base)
        _install(plan)
        _git(repo, env, "add", ".gitattributes")
        _git(repo, env, "commit", "-qm", "attrs")
        _branches(repo, env, plan, ours, theirs)
        code, out, text = _merge(repo, env, plan)
        doc = _load_or_empty(plan)
        check("mm16 with the driver installed the same merge is clean, and both phases "
              "and both bugs are in the plan",
              code == 0 and [p["id"] for p in doc.get("phases") or []][-2:] == ["BF11", "BF12"]
              and [b["id"] for b in doc.get("bugs") or []] == ["BUG-2", "BUG-3"], out)
        forward = text

        repo2, plan2 = _repo(tmp, "g2", env, base)
        _install(plan2)
        _git(repo2, env, "add", ".gitattributes")
        _git(repo2, env, "commit", "-qm", "attrs")
        _branches(repo2, env, plan2, theirs, ours)       # the sides swapped
        code, out, text = _merge(repo2, env, plan2)
        check("mm17 merging in the other direction produces byte-identical plan text",
              code == 0 and text == forward, out)

        # Sharded: the index gets two stubs and two bugs, each branch a new shard.
        repo3, idx = _repo(tmp, "g3", env, base)
        _write_json(idx, base)
        _mio.save_sharded(idx, base)
        _git(repo3, env, "add", "-A")
        _git(repo3, env, "commit", "-qm", "shard")
        _install(idx)
        _git(repo3, env, "add", ".gitattributes")
        _git(repo3, env, "commit", "-qm", "attrs")
        _git(repo3, env, "checkout", "-qb", "side")
        _mio.save_sharded(idx, _add_bug(_add_phase(_mio.load_manifest(idx), "BF11",
                                                    "src/d.ts"), "BUG-3"))
        _git(repo3, env, "add", "-A")
        _git(repo3, env, "commit", "-qm", "theirs")
        _git(repo3, env, "checkout", "-q", "main")
        _mio.save_sharded(idx, _add_bug(_add_phase(_mio.load_manifest(idx), "BF12",
                                                    "src/c.ts"), "BUG-2"))
        _git(repo3, env, "add", "-A")
        _git(repo3, env, "commit", "-qm", "ours")
        code, out, _t = _merge(repo3, env, idx)
        merged = _mio.load_manifest(idx)
        check("mm18 SHARDED: two branches that each add a phase and a bug merge the index "
              "cleanly, and the assembled plan holds both",
              code == 0 and {"BF11", "BF12"} <= set(p["id"] for p in merged["phases"])
              and [b["id"] for b in merged["bugs"]] == ["BUG-2", "BUG-3"], out)

        # A shim whose plugin root is gone: markers, not a silent "ours".
        repo4, plan4 = _repo(tmp, "g4", env, base)
        _install(plan4, root=os.path.join(tmp, "moved-away"))
        _git(repo4, env, "add", ".gitattributes")
        _git(repo4, env, "commit", "-qm", "attrs")
        _branches(repo4, env, plan4, ours, theirs)
        code, out, text = _merge(repo4, env, plan4)
        check("mm19 a STALE shim leaves git's line merge WITH markers and says to re-run "
              "install - never %A as ours with no markers",
              code != 0 and "<<<<<<< ours" in text and "re-run the merge-driver install" in out,
              "%s\n%s" % (out, text))

        # A driver that dies before writing (the ImportError shape, exit 1).
        fake = os.path.join(tmp, "fake-root")
        os.makedirs(os.path.join(fake, "scripts", "manifest"))
        with open(os.path.join(fake, "scripts", "manifest", "merge-manifest.py"), "w") as fh:
            fh.write("import sys\nsys.exit(1)\n")
        repo5, plan5 = _repo(tmp, "g5", env, base)
        _install(plan5, root=fake)
        _git(repo5, env, "add", ".gitattributes")
        _git(repo5, env, "commit", "-qm", "attrs")
        _branches(repo5, env, plan5, ours, theirs)
        code, out, text = _merge(repo5, env, plan5)
        check("mm20 a driver that exits 1 WITHOUT writing is caught by the shim, which "
              "writes the line merge's markers itself",
              code != 0 and "<<<<<<< ours" in text and "without writing" in out,
              "%s\n%s" % (out, text))
        _resolve_cases(check, tmp, env)
        _resolve_twice_cases(check, tmp, env)
        _base_twice_resolve_case(check, tmp, env)
        _base_container_twice_cases(check, tmp, env)
        _run_record_cases(check, tmp, env)
        _window_cases(check, tmp, env)
    finally:
        os.environ.clear()
        os.environ.update(held)


# --- a run record is merged whole, through git ----------------------------------
# Two branches that each recorded a run on one task: the record and its pointer are
# one account of one run, so `git merge` through the installed driver must leave a
# block that, kept either way, is one side's run - never one side's run id beside the
# other side's status. The records are written by the evidence layer's own writer,
# so the fixture is the shape a gate leaves, not a hand-written guess at it.
_RR_UNIT = ("lastRun", "testEvidence")


def _record_run(repo, idx, run_id, status, ts, ms, task_id="P1.1"):
    import _evidence_io
    row = {"v": 1, "runId": run_id, "ts": ts, "scope": "task", "taskId": task_id,
           "phaseId": "P1", "status": status, "durationMs": ms,
           "steps": [], "failed": ["tests/test_x.py"] if status == "failed" else []}
    return _evidence_io.write_record(repo, idx, "task",
                                     {"taskId": task_id, "phaseId": "P1"},
                                     _evidence_io.run_record(row),
                                     session_id="run-record-case")


def _verbs_merge(tmp, name, env, ours, theirs):
    """A sharded plan holding a bug and a review finding, `theirs(plan)` committed
    on a branch and `ours(plan)` on main, merged through the installed driver ->
    (merge exit, output, the plan as the work tree then reads)."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _harness.git(repo, "init", "-q", "-b", "main")
    idx = os.path.join(repo, "docs", "audit", "plan.json")
    plan = _window_plan()
    plan["bugs"] = [{"id": "BUG-1", "title": "b", "status": "open", "severity": "low",
                     "notes": "seen once"}]
    plan["phases"][0]["review"] = {"status": "failed", "findings": [
        {"id": "x1", "issue": "i", "severity": "med", "status": "open"}]}
    _write_json(idx, plan)
    _mio.save_sharded(idx, plan)
    _install(idx)
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "base")
    for branch, edit in (("side", theirs), ("main", ours)):
        _harness.git(repo, "checkout", "-q" + ("b" if branch == "side" else ""), branch)
        doc = _mio.load_manifest(idx)
        edit(doc)
        _mio.save_sharded(idx, doc)
        _harness.git(repo, "commit", "-qam", branch)
    code, out = _git(repo, env, "merge", "-q", "side", "-m", "merge")
    try:
        merged = _mio.load_manifest(idx)
    except Exception:
        merged = None
    return code, out, merged


def _minted_and_run_merge(tmp, name, env):
    """Both sides mint P1.2 (a collision resolve renumbers) AND record a run on P1.1
    and on their own P1.2, through the evidence writer -> (repo, index, exit)."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _harness.git(repo, "init", "-q", "-b", "main")
    idx = os.path.join(repo, "docs", "audit", "plan.json")
    _write_json(idx, _window_plan())
    _mio.save_sharded(idx, _window_plan())
    _install(idx)
    _record_run(repo, idx, "R1", "failed", "2026-11-20T10:00:00Z", 100)
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "base")
    for branch, title, runs in (
            ("side", "theirs", (("R3", "failed", "P1.1"), ("R5", "failed", "P1.2"))),
            ("main", "ours", (("R2", "passed", "P1.1"), ("R4", "passed", "P1.2")))):
        _harness.git(repo, "checkout", "-q" + ("b" if branch == "side" else ""), branch)
        plan = _mio.load_manifest(idx)
        plan["phases"][0]["tasks"].append({"id": "P1.2", "title": title, "status": "pending",
                                           "files": ["src/%s.ts" % (title,)]})
        plan["fileIndex"]["src/%s.ts" % (title,)] = ["P1.2"]
        _mio.save_sharded(idx, plan)
        for i, (rid, status, tid) in enumerate(runs):
            _record_run(repo, idx, rid, status, "2026-11-20T1%d:00:00Z" % (i + 1,), 10, tid)
        _harness.git(repo, "add", "-A")
        _harness.git(repo, "commit", "-qm", title)
    code, _out = _git(repo, env, "merge", "-q", "side", "-m", "merge")
    return repo, idx, code


def _rr_unit(shard_doc):
    task = [t for t in (shard_doc or {}).get("tasks") or [] if t.get("id") == "P1.1"]
    return dict((k, task[0][k]) for k in _RR_UNIT if task and k in task[0])


def _rr_resolutions(text):
    """Every document keeping one side per marker block, block by block."""
    lines = text.split("\n")
    n = sum(1 for ln in lines if ln.startswith("<<<<<<< "))
    out = []
    for mask in range(2 ** n):
        kept, mode, block = [], None, -1
        for line in lines:
            if line.startswith("<<<<<<< "):
                block, mode = block + 1, "ours"
                continue
            if line == "=======" and mode:
                mode = "theirs"
                continue
            if line.startswith(">>>>>>> ") and mode:
                mode = None
                continue
            if mode is None or mode == ("theirs" if mask >> block & 1 else "ours"):
                kept.append(line)
        out.append(_json_or_none("\n".join(kept).encode("utf-8")))
    return n, out


def _run_record_merge(tmp, name, env):
    """A sharded plan with the driver installed, a red recorded on the base, a green
    on ours and a newer red on theirs, `git merge` stopped -> (repo, index, exit,
    output, {side: P1's shard as that commit holds it})."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _harness.git(repo, "init", "-q", "-b", "main")
    idx = os.path.join(repo, "docs", "audit", "plan.json")
    _write_json(idx, _window_plan())
    _mio.save_sharded(idx, _window_plan())
    _install(idx)
    wrote = [_record_run(repo, idx, "R1", "failed", "2026-11-20T10:00:00Z", 100)]
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "base")
    _harness.git(repo, "checkout", "-qb", "side")
    wrote.append(_record_run(repo, idx, "R3", "failed", "2026-11-20T12:00:00Z", 300))
    _harness.git(repo, "commit", "-qam", "theirs: a newer red")
    _harness.git(repo, "checkout", "-q", "main")
    wrote.append(_record_run(repo, idx, "R2", "passed", "2026-11-20T11:00:00Z", 200))
    _harness.git(repo, "commit", "-qam", "ours: a green")
    code, out = _git(repo, env, "merge", "-q", "side", "-m", "merge")
    sides = dict((rev, _json_or_none(_harness.git(repo, "show", "%s:%s" % (
        rev, _W_SHARD % "P1")).encode("utf-8"))) for rev in ("HEAD~1", "HEAD", "side"))
    return repo, idx, code, out, sides, wrote


def _run_record_cases(check, tmp, env):
    repo, idx, code, out, sides, wrote = _run_record_merge(tmp, "rr-git", env)
    units = dict((rev, _rr_unit(doc)) for rev, doc in sides.items())
    recorded = [w.get("written") for w in wrote]
    with open(os.path.join(repo, _W_SHARD % "P1"), encoding="utf-8") as fh:
        text = fh.read()
    blocks, docs = _rr_resolutions(text)
    held = [_rr_unit(d) if isinstance(d, dict) else "unparsed" for d in docs]
    mixed = [u for u in held if u not in (units["HEAD"], units["side"])]
    check("rr1 a real `git merge` through the installed driver over two branches that "
          "each recorded a run on P1.1 stops on ONE conflict naming the record and its "
          "pointer together, and every way of keeping a side of each block leaves ours' "
          "run or theirs' run whole; mixed: %r" % (mixed,),
          recorded == [True, True, True] and code != 0
          and "tasks[P1.1].{lastRun,testEvidence} - " in out
          and "lastRun.runId" not in out
          and units["HEAD"].get("lastRun", {}).get("runId") == "R2"
          and units["side"].get("lastRun", {}).get("runId") == "R3"
          and blocks >= 1 and len(docs) == 2 ** blocks and mixed == []
          and units["HEAD"] in held and units["side"] in held,
          "%s %s\n%s\n%s" % (recorded, code, out, text))

    # A hand resolution typed with ours' run id and theirs' status: neither side's.
    hand = copy.deepcopy(sides["HEAD"])
    task = [t for t in hand["tasks"] if t["id"] == "P1.1"][0]
    task["lastRun"]["status"] = task["testEvidence"]["status"] = "failed"
    _write_json(os.path.join(repo, _W_SHARD % "P1"), hand)
    before = _plan_bytes(repo)
    code, msg = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rr2 the resolver reading a hand-resolved shard refuses a run record neither "
          "side nor the base wrote, naming its path, with nothing written: %s" % (msg,),
          code == 1 and "%s: tasks[P1.1].{lastRun,testEvidence}" % (_W_SHARD % "P1",) in msg
          and "nothing was written" in msg and _plan_bytes(repo) == before)

    # ALLOW: the same hand resolution keeping theirs' run whole names no record.
    _write_json(os.path.join(repo, _W_SHARD % "P1"), sides["side"])
    code, msg = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rr3 ALLOW: a hand resolution keeping one side's run whole is not called a "
          "record neither side wrote - the resolver answers as before: %s" % (msg,),
          code == 1 and "{lastRun,testEvidence}" not in msg
          and "no id in" in msg)

    # rr7 - a run recorded, while the merge is stopped, in a shard both sides hold
    #       alike is neither side's too, and the refusal with no id to renumber -
    #       which returns before any stray check - names it.
    repo, idx, _c, _o, _s, _w = _run_record_merge(tmp, "rr-alike", env)
    alike = os.path.join(repo, _W_SHARD % "BF10")
    with open(alike, encoding="utf-8") as fh:
        shard = json.load(fh)
    shard["tasks"][0].update(lastRun={"runId": "R9", "status": "passed", "at": "T9"},
                             testEvidence={"runId": "R9", "status": "passed", "at": "T9"})
    _write_json(alike, shard)
    code7, msg7 = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rr7 a run recorded while the merge is stopped, in a shard both sides hold "
          "alike, is named by the refusal of a merge with no id to renumber: %s" % (msg7,),
          code7 == 1 and "no id in" in msg7
          and "%s: tasks[BF10.1].{lastRun,testEvidence}" % (_W_SHARD % "BF10",) in msg7)

    # rr8/rr9 - two verbs writing apart in one record, through the real driver.
    def bug(doc):
        return doc["bugs"][0]

    def finding(doc):
        return doc["phases"][0]["review"]["findings"][0]
    code8, out8, merged8 = _verbs_merge(
        tmp, "rr-bug-note", env,
        lambda d: bug(d).update(status="fixed", fixedIn="a" * 40),
        lambda d: bug(d).update(notes="seen once\nseen again on windows"))
    check("rr8 ALLOW: a bug fixed on one branch and its notes edited on the other merge "
          "clean through the driver, keeping both: exit %d %s" % (code8, out8),
          code8 == 0 and merged8 is not None
          and bug(merged8).get("status") == "fixed" and bug(merged8).get("fixedIn") == "a" * 40
          and bug(merged8).get("notes") == "seen once\nseen again on windows")
    code9, out9, merged9 = _verbs_merge(
        tmp, "rr-finding-link", env,
        lambda d: finding(d).update(resolution="typed by the reviewer"),
        lambda d: finding(d).update(fixTask="P1.1"))
    check("rr9 ALLOW: a finding's resolution edited on one branch and a fixing task "
          "linked on the other merge clean through the driver, keeping both: exit %d %s"
          % (code9, out9),
          code9 == 0 and merged9 is not None
          and finding(merged9).get("resolution") == "typed by the reviewer"
          and finding(merged9).get("fixTask") == "P1.1")
    code10, out10, _m = _verbs_merge(
        tmp, "rr-finding-mix", env,
        lambda d: finding(d).update(status="accepted-open", acceptedReason="ok"),
        lambda d: finding(d).update(status="carried", carriedTo="BUG-1"))
    check("rr10 ...while a finding accepted on one branch and carried on the other stops "
          "on ONE conflict over its disposition: exit %d %s" % (code10, out10),
          code10 != 0 and out10.count(" - changed on both sides") == 1
          and "findings[x1].{status,acceptedReason,carriedTo}" in out10)

    # rr4 - a diff3 block's base section is neither side's reading.
    diff3 = "\n".join(['{', '<<<<<<< ours', '  "a": 1', '||||||| base', '  "a": 0',
                       '=======', '  "a": 2', '>>>>>>> theirs', '}'])
    check("rr4 each marker block is read once per side, a diff3 base section in neither "
          "reading, and a file with no marker is read as it stands",
          M._readings(diff3, 7) == ['{\n  "a": 1\n}', '{\n  "a": 2\n}']
          and M._readings('{"a": 1}', 7) == ['{"a": 1}'], M._readings(diff3, 7))

    # rr5 - with an id to renumber, the refusal is the stray one, and it names the
    #       mixed record too - saying once that nothing was written.
    repo, idx, code = _minted_and_run_merge(tmp, "rr-minted", env)
    shard = os.path.join(repo, _W_SHARD % "P1")
    ours = _json_or_none(_harness.git(repo, "show", "HEAD:%s" % (_W_SHARD % "P1",))
                         .encode("utf-8"))
    mixed = copy.deepcopy(ours)
    run = [t for t in mixed["tasks"] if t["id"] == "P1.1"][0]
    run["lastRun"]["status"] = run["testEvidence"]["status"] = "failed"
    _write_json(shard, mixed)
    before = _plan_bytes(repo)
    code2, msg = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rr5 with an id minted on both sides the refusal is the stray one, and it "
          "names the record neither side wrote, saying once that nothing was written: "
          "%s" % (msg,),
          code != 0 and code2 == 1 and "changed since git's merge" in msg
          and "%s: tasks[P1.1].{lastRun,testEvidence}" % (_W_SHARD % "P1",) in msg
          and msg.count("nothing was written") == 1 and _plan_bytes(repo) == before)

    # rr6 - ALLOW, the sequence a person runs: resolve renumbers theirs' P1.2 to P1.3
    #       and leaves the run conflict on P1.1; ours' block kept whole, resolve runs
    #       again. Theirs' P1.2 now held as P1.3 is theirs' record under its new id.
    repo, idx, _c = _minted_and_run_merge(tmp, "rr-renumbered", env)
    code1, out1 = _resolve(["resolve", idx, "--renumber", "theirs"])
    with open(shard.replace("rr-minted", "rr-renumbered"), encoding="utf-8") as fh:
        left = fh.read()
    _blocks, docs = _rr_resolutions(left)
    kept = docs[0] if docs and isinstance(docs[0], dict) else None
    if kept is not None:
        _write_json(shard.replace("rr-minted", "rr-renumbered"), kept)
    code2, out2 = _resolve(["resolve", idx, "--renumber", "theirs"])
    ids = [t["id"] for t in (kept or {}).get("tasks") or []]
    check("rr6 ALLOW: after resolve renumbered theirs' P1.2 to P1.3 and a person kept "
          "ours' block of the run left in conflict, resolve run again names no record "
          "- theirs' record under its new id is theirs': %s | %s" % (out1, out2),
          code1 == 1 and "P1.2 -> P1.3" in out1 and ids == ["P1.1", "P1.2", "P1.3"]
          and code2 == 1 and "neither side's" not in out2)


def _resolve(argv):
    held = sys.stdout, sys.stderr
    buf = io.StringIO()
    sys.stdout = sys.stderr = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = held
    return code, buf.getvalue()


def _twice_found(path):
    """The keys the file at `path` writes twice, as the door names them, or
    None when it is not JSON (a file holding conflict markers)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        return _mio.parse_json_text(text)[1]
    except ValueError:
        return None


def _driver_twice_cases(check, tmp):
    """(mk) The driver never leaves %A writing a key twice: a side that writes
    one is not merged by record over its last copy, and a line merge that
    would come out clean holding one is written as one conflict block."""
    base = _plan()
    theirs = _add_phase(base, "BF11", "src/d.ts")
    ours_text = _mio.json_document(_add_phase(base, "BF12", "src/c.ts"))
    ours_twice = ours_text.replace('"title": "One",',
                                   '"title": "One",\n      "title": "Uno",', 1)
    assert ours_twice != ours_text
    paths = _driver_files(tmp, "dk1", base, ours_twice, theirs)
    code, err = _run_driver(paths)
    left = _twice_found(paths[1])
    check("mk1 RED-FIRST: a side that writes a key twice is not merged by "
          "record over its last copy: %%A is left conflicted (markers, exit 1) "
          "and the driver names the key written twice: exit %r, %%A writes "
          "twice %r, said %r" % (code, left, err[-240:]),
          code == 1 and left is None and "written twice" in err
          and "/phases/0/title" in err)
    # A line merge that comes out CLEAN holding a key twice: each side adds
    # the same key in a different hunk. The record merge is made to crash so
    # the driver's fallback - git's line merge - is what is written.
    base_text = '{\n  "x": 1,\n  "y": 2,\n  "z": 3\n}\n'
    ours_k = '{\n  "k": 1,\n  "x": 1,\n  "y": 2,\n  "z": 3\n}\n'
    theirs_k = '{\n  "x": 1,\n  "y": 2,\n  "k": 2,\n  "z": 3\n}\n'
    paths = _driver_files(tmp, "dk2", base_text, ours_k, theirs_k)
    # THE FIXTURE BITES: git's own line merge of these sides is clean and
    # writes `k` twice, so the case below can fail.
    plain = subprocess.run(["git", "merge-file", "-p", paths[1], paths[0],
                            paths[2]], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    try:
        bites = (plain.returncode, _mio.parse_json_text(
            plain.stdout.decode("utf-8"))[1])
    except ValueError as exc:
        bites = (plain.returncode, "%s" % (exc,))
    real = M._manifest_merge.merge3

    def boom(*a):
        raise RuntimeError("planted")
    M._manifest_merge.merge3 = boom
    try:
        code, err = _run_driver(paths)
    finally:
        M._manifest_merge.merge3 = real
    left = _twice_found(paths[1])
    with open(paths[1], encoding="utf-8") as fh:
        held = fh.read()
    check("mk2 RED-FIRST: a line merge that would come out clean writing a "
          "key twice (git's own: %r) is written as one conflict block instead "
          "- %%A never parses to a key written twice: exit %r, writes twice "
          "%r, %%A %r" % (bites, code, left, held[:120]),
          bites == (0, ["/k"]) and code == 1 and left is None
          and held.count("<<<<<<< ") == 1)
    _base_twice_driver_cases(check, tmp)


def _base_twice(doc):
    """`doc`'s plugin spelling with phase 0's title written twice, the first
    copy "One" and the last "Uno"."""
    d = copy.deepcopy(doc)
    d["phases"][0]["title"] = "One"
    text = _mio.json_document(d)
    twice = text.replace('"title": "One",', '"title": "One",\n      "title": "Uno",', 1)
    assert twice != text
    return twice


def _base_twice_driver_cases(check, tmp):
    """(mk) A key written twice on the merge BASE alone - committed, then
    repaired on both sides - blocks nothing: the base is read only to tell
    which side changed what, and is never written back, so its key written
    twice reads as absent there. Equal sides merge; sides that differ at it
    conflict, never settled by either copy."""
    base = _plan()
    base["phases"][0]["title"] = "One"
    ours = _add_phase(base, "BF12", "src/c.ts")
    theirs = _add_phase(base, "BF11", "src/d.ts")
    paths = _driver_files(tmp, "bt1", _base_twice(base), ours, theirs)
    code, err = _run_driver(paths)
    doc = _load_or_empty(paths[1])
    ids = sorted(p.get("id") for p in doc.get("phases") or [])
    check("mk6 RED-FIRST: a merge whose BASE alone writes a key twice, the two "
          "sides clean, merges by record as it did before the door - exit 0, "
          "both sides' phases, %%A writing each key once, no advice to delete a "
          "copy no file in the tree holds: exit %r, ids %r, twice %r, said %r"
          % (code, ids, _twice_found(paths[1]), err[-240:]),
          code == 0 and "BF11" in ids and "BF12" in ids
          and _twice_found(paths[1]) == [] and "written twice" not in err)
    # The two sides settle the base's key differently, and one of them keeps
    # the base's LAST copy: read as that copy, the base would make that side
    # "unchanged" and hand the record to the other silently.
    ours = copy.deepcopy(base)
    theirs = copy.deepcopy(base)
    theirs["phases"][0]["title"] = "Uno"
    paths = _driver_files(tmp, "bt2", _base_twice(base), ours, theirs)
    code, err = _run_driver(paths)
    with open(paths[1], encoding="utf-8") as fh:
        held = fh.read()
    check("mk7 RED-FIRST: ...and where the sides settle that key differently - "
          "one keeping the base's first copy, one its last - it is a conflict "
          "left to the person, never decided by whichever copy the base's "
          "reader kept: exit %r, markers %r, said %r"
          % (code, held.count("<<<<<<< "), err[-240:]),
          code == 1 and "<<<<<<< " in held and "One" in held and "Uno" in held)


def _tasks_twice_sides():
    """`(base text, ours, theirs)`: the base writes phase P1's `tasks` twice
    (first copy P1.1 pending, last copy P1.1 done, P1.2 pending in both);
    ours and theirs are clean and differ only on P1.2's status."""
    base = _plan()
    base["phases"][0]["tasks"] = [
        {"id": "P1.1", "title": "a", "status": "done", "files": ["src/a.ts"]},
        {"id": "P1.2", "title": "b", "status": "pending", "files": ["src/a.ts"]}]
    first = copy.deepcopy(base["phases"][0]["tasks"])
    first[0]["status"] = "pending"
    text = _mio.json_document(base)
    twice = text.replace('"title": "One",', '"title": "One",\n      "tasks": %s,'
                         % (json.dumps(first),), 1)
    assert twice != text and _mio.parse_json_text(twice)[1] == ["/phases/0/tasks"]
    ours = copy.deepcopy(base)
    theirs = copy.deepcopy(base)
    theirs["phases"][0]["tasks"][1]["status"] = "done"
    return twice, ours, theirs


def _base_container_twice_cases(check, tmp, env):
    """(mk) A CONTAINER the base writes twice leaves the base unknown there:
    no id under it is minted on both sides, the conflict says the base's
    copy could not be read and offers no renumbering, and `resolve` renumbers
    nothing - a renumbering would put one task under two ids."""
    base_text, ours, theirs = _tasks_twice_sides()
    paths = _driver_files(tmp, "bct", base_text, ours, theirs)
    code, err = _run_driver(paths)
    check("mk9 RED-FIRST: the driver over a base writing `tasks` twice, the "
          "sides differing on one task, conflicts saying the base writes "
          "/phases/0/tasks twice - never 'added on both sides', never "
          "offering --renumber: exit %r, said %r" % (code, err[-500:]),
          code == 1 and "/phases/0/tasks twice" in err
          and "added on both sides" not in err and "--renumber" not in err)
    # A record holding the unknown value, deleted on one side and kept as is
    # on the other: against a base that is not known, "changed on the other
    # side" is a claim nothing established.
    ours_del = copy.deepcopy(ours)
    ours_del["phases"] = [p for p in ours_del["phases"] if p["id"] != "P1"]
    paths = _driver_files(tmp, "bct-del", base_text, ours_del,
                          copy.deepcopy(ours))
    code, err = _run_driver(paths)
    check("mk11 RED-FIRST: a record the base holds an unknown value in, deleted "
          "on one side and kept on the other, conflicts saying the base writes "
          "/phases/0/tasks twice - never 'deleted on one side and changed on "
          "the other', which the kept side did not do: exit %r, said %r"
          % (code, err[-400:]),
          code == 1 and "phases[P1] - the merge base writes /phases/0/tasks "
          "twice" in err and "changed on the other" not in err)
    repo, plan = _repo(tmp, "rct", env, _plan())
    with open(plan, "w", encoding="utf-8") as fh:
        fh.write(base_text)
    _install(plan)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-qm", "tasks written twice, committed")
    _branches(repo, env, plan, ours, theirs)
    _merge(repo, env, plan)
    with open(plan, encoding="utf-8") as fh:
        held = fh.read()
    code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    with open(plan, encoding="utf-8") as fh:
        after = fh.read()
    check("mk10 RED-FIRST: resolve over that merge - through the real git "
          "merge - renumbers nothing and writes nothing, saying the base "
          "writes /phases/0/tasks twice: never 'P1.2 -> P1.3', one task "
          "under two ids: exit %r, same %r, said %r"
          % (code, after == held, out[-400:]),
          code == 1 and after == held and "P1.3" not in after
          and "/phases/0/tasks" in out and "none is renumbered" in out
          and "->" not in out)


def _base_twice_resolve_case(check, tmp, env):
    """(mk) `resolve` reads the merge base the same way: a base writing a key
    twice does not refuse a renumbering the two clean sides call for."""
    base = _plan()
    base["phases"][0]["title"] = "One"
    ours = _add_bug(base, "BUG-1")
    ours["bugs"][0]["title"] = "ours bug"
    theirs = _add_bug(base, "BUG-1")
    theirs["bugs"][0]["title"] = "theirs bug"
    repo, plan = _repo(tmp, "rbt", env, base)
    with open(plan, "w", encoding="utf-8") as fh:
        fh.write(_base_twice(base))
    _install(plan)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-qm", "a key written twice, committed")
    _branches(repo, env, plan, ours, theirs)
    _merge(repo, env, plan)
    code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    doc = _load_or_empty(plan)
    bugs = dict((b["id"], b.get("title")) for b in doc.get("bugs") or [])
    check("mk8 RED-FIRST: resolve over a merge whose BASE alone writes a key "
          "twice renumbers as it would over a clean base - exit 0, both bugs "
          "kept, the plan writing each key once: exit %r, bugs %r, said %r"
          % (code, bugs, out[-300:]),
          code == 0 and bugs.get("BUG-1") == "ours bug"
          and bugs.get("BUG-2") == "theirs bug" and _twice_found(plan) == [])


def _resolve_twice_cases(check, tmp, env):
    """(mk) `resolve` asks the door of every text it is about to write, before
    the first write: one that writes a key twice refuses the whole write."""
    base = _plan()
    ours = _add_bug(base, "BUG-1")
    ours["bugs"][0]["title"] = "ours bug"
    theirs = _add_bug(base, "BUG-1")
    theirs["bugs"][0]["title"] = "theirs bug"
    repo, plan = _repo(tmp, "rk1", env, base)
    _install(plan)
    _git(repo, env, "add", ".gitattributes")
    _git(repo, env, "commit", "-qm", "attrs")
    _branches(repo, env, plan, ours, theirs)
    _merge(repo, env, plan)
    with open(plan, encoding="utf-8") as fh:
        held = fh.read()
    real = M._render_plan

    def twice(path, result, sharded):
        out = real(path, result, sharded)
        target, text = out[0]
        planted = text.replace('"version": 2', '"version": 2,\n    "version": 2', 1)
        assert planted != text
        return [(target, planted)] + out[1:]
    M._render_plan = twice
    try:
        code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    finally:
        M._render_plan = real
    with open(plan, encoding="utf-8") as fh:
        after = fh.read()
    check("mk3 RED-FIRST: a text resolve is about to write that writes a key "
          "twice refuses the whole write - nothing written, the file as git's "
          "merge left it, the key and the hand step named: exit %r, same %r, "
          "said %r" % (code, after == held, out[-240:]),
          code == 1 and after == held and "nothing was written" in out
          and "written twice" in out and "/meta/version" in out)
    # THE OVER-FIRE: the same resolve, its texts as rendered, writes.
    code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    check("mk4 ...and with its texts as rendered the same resolve writes, the "
          "plan holding each key once: exit %r, writes twice %r"
          % (code, _twice_found(plan)),
          code == 0 and _twice_found(plan) == [])


def _merge_parse_cases(check):
    """(mk) The merge resolver parses a plan's text only through the door."""
    import ast
    with open(M.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    raw = sorted("%s:%d" % (n.func.attr, n.lineno) for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("load", "loads")
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "json")
    check("mk5 RED-FIRST: merge-manifest.py parses no JSON itself - every side, "
          "reading and output is parsed by `_manifest_io`'s door, which names "
          "a key written twice: json.load/loads calls %r" % (raw,),
          raw == [])


def _resolve_cases(check, tmp, env):
    """The collision the branch suffix cannot prevent: two clones minting the same
    id on the development branch itself. `resolve` renumbers the side named."""
    base = _plan()
    ours = _add_bug(base, "BUG-1")
    ours["phases"][0]["tasks"][0]["bugId"] = "BUG-1"
    ours["bugs"][0]["taskId"] = "P1.1"
    ours["bugs"][0]["title"] = "ours bug"
    theirs = _add_bug(base, "BUG-1")
    theirs["phases"][1]["tasks"][0]["bugId"] = "BUG-1"
    theirs["bugs"][0]["taskId"] = "BF10.1"
    theirs["bugs"][0]["title"] = "theirs bug"

    repo, plan = _repo(tmp, "r1", env, base)
    _install(plan)
    _git(repo, env, "add", ".gitattributes")
    _git(repo, env, "commit", "-qm", "attrs")
    code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    check("rs1 resolve with no merge in progress refuses and says there is nothing to "
          "resolve - it never invents a side", code == 1 and "no conflict" in out, out)
    _branches(repo, env, plan, ours, theirs)
    code, out, text = _merge(repo, env, plan)
    check("rs2 CONTROL: the same BUG-1 minted on both sides is a conflict the driver "
          "names - and it names the verb that resolves it, so the operator is not left "
          "to hand-edit a collision", code != 0 and "bugs[BUG-1]" in out
          and "resolve" in out and "--renumber ours|theirs" in out, out)
    code, out = _resolve(["resolve", plan])
    check("rs3 resolve without --renumber refuses: which side keeps the id is the "
          "operator's call, never the tool's", code == 2 and "--renumber" in out, out)
    code, out = _resolve(["resolve", plan, "--renumber", "theirs"])
    doc = _load_or_empty(plan)
    bugs = dict((b["id"], b) for b in doc.get("bugs") or [])
    tasks = dict((t["id"], t) for ph in doc.get("phases") or [] for t in ph["tasks"])
    check("rs4 --renumber theirs keeps ours' BUG-1 and gives theirs the next free id, "
          "and says so: %s" % (out,),
          code == 0 and bugs.get("BUG-1", {}).get("title") == "ours bug"
          and bugs.get("BUG-2", {}).get("title") == "theirs bug"
          and "BUG-1 -> BUG-2" in out)
    check("rs5 ...and every reference on theirs follows: the task that linked it now "
          "names BUG-2, the one that linked ours still names BUG-1",
          tasks.get("BF10.1", {}).get("bugId") == "BUG-2"
          and tasks.get("P1.1", {}).get("bugId") == "BUG-1",
          tasks)
    check("rs6 ...the file is valid, has no markers, and the plan validates",
          "<<<<<<<" not in open(plan, encoding="utf-8").read()
          and not _rules_findings(doc), _rules_findings(doc))

    repo2, plan2 = _repo(tmp, "r2", env, base)
    _install(plan2)
    _git(repo2, env, "add", ".gitattributes")
    _git(repo2, env, "commit", "-qm", "attrs")
    _branches(repo2, env, plan2, ours, theirs)
    _merge(repo2, env, plan2)
    code, out = _resolve(["resolve", plan2, "--renumber", "ours"])
    doc2 = _load_or_empty(plan2)
    bugs2 = dict((b["id"], b) for b in doc2.get("bugs") or [])
    check("rs7 --renumber ours is the mirror: theirs keeps BUG-1, ours becomes BUG-2",
          code == 0 and bugs2.get("BUG-1", {}).get("title") == "theirs bug"
          and bugs2.get("BUG-2", {}).get("title") == "ours bug", out)

    # The new id is free over BOTH sides: ours also added BUG-2, so theirs' BUG-1
    # must not become a second BUG-2.
    ours4 = _add_bug(_add_bug(base, "BUG-1"), "BUG-2")
    ours4["bugs"][0]["title"] = "ours one"
    theirs4 = _add_bug(base, "BUG-1")
    theirs4["bugs"][0]["title"] = "theirs one"
    repo4, plan4 = _repo(tmp, "r4", env, base)
    _install(plan4)
    _git(repo4, env, "add", ".gitattributes")
    _git(repo4, env, "commit", "-qm", "attrs")
    _branches(repo4, env, plan4, ours4, theirs4)
    _merge(repo4, env, plan4)
    code, out = _resolve(["resolve", plan4, "--renumber", "theirs"])
    doc4 = _load_or_empty(plan4)
    check("rs10 the renumbered id is free over BOTH sides - theirs' BUG-1 becomes BUG-3 "
          "when ours already added BUG-2: %s" % (out,),
          code == 0 and sorted(b["id"] for b in doc4.get("bugs") or [])
          == ["BUG-1", "BUG-2", "BUG-3"]
          and [b["title"] for b in doc4["bugs"] if b["id"] == "BUG-3"] == ["theirs one"])

    # Sharded: both sides mint phase P11, each in its own new shard file of one name.
    repo3, idx = _repo(tmp, "r3", env, base)
    _mio.save_sharded(idx, base)
    _git(repo3, env, "add", "-A")
    _git(repo3, env, "commit", "-qm", "shard")
    _install(idx)
    _git(repo3, env, "add", ".gitattributes")
    _git(repo3, env, "commit", "-qm", "attrs")
    _git(repo3, env, "checkout", "-qb", "side")
    _mio.save_sharded(idx, _add_phase(_mio.load_manifest(idx), "P11", "src/theirs.ts"))
    _git(repo3, env, "add", "-A")
    _git(repo3, env, "commit", "-qm", "theirs P11")
    _git(repo3, env, "checkout", "-q", "main")
    _mio.save_sharded(idx, _add_phase(_mio.load_manifest(idx), "P11", "src/ours.ts"))
    _git(repo3, env, "add", "-A")
    _git(repo3, env, "commit", "-qm", "ours P11")
    code, out, _t = _merge(repo3, env, idx)
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    try:
        merged = _mio.load_manifest(idx)
    except Exception:
        merged = {"phases": [], "fileIndex": {}}
    by = dict((p["id"], p) for p in merged["phases"])
    check("rs8 SHARDED: a phase minted on both sides is resolved across the index AND "
          "the shard file both sides created - theirs lands as P12 in its own shard, "
          "ours keeps P11: %s" % (out,),
          code == 0 and "P11" in by and "P12" in by
          and by["P11"]["tasks"][0]["files"] == ["src/ours.ts"]
          and by["P12"]["tasks"][0]["id"] == "P12.1"
          and by["P12"]["tasks"][0]["files"] == ["src/theirs.ts"]
          and merged["fileIndex"].get("src/theirs.ts") == ["P12.1"])
    check("rs9 ...with no conflict markers left in the index or either shard",
          not any("<<<<<<<" in open(os.path.join(dp, f), encoding="utf-8").read()
                  for dp, _d, fs in os.walk(os.path.dirname(idx)) for f in fs
                  if f.endswith(".json")))


# --- resolve never writes over bytes it did not account for ----------------------
# `resolve` builds every file of the merged plan from git's commits, never from the
# work tree, so a plan write made while `git merge` is stopped - a gate's run record
# landing in a shard the merge left clean - would be overwritten by it. Each target is
# decided under the index lock, before the first write: equal to what git's merge
# left (a conflicted one included, a marker's label aside where git would have
# written that label) or to what resolve is
# about to write, or a stray - and one stray refuses the whole write.
_W_SHARD = "docs/audit/phases/%s.json"


def _window_plan(extra=None):
    """A two-phase plan; `extra` is the task each side adds to P1 as P1.2."""
    tasks = [{"id": "P1.1", "title": "a", "status": "pending", "files": ["src/a.ts"]}]
    index = {"src/a.ts": ["P1.1"], "src/b.ts": ["BF10.1"]}
    if extra:
        tasks.append(dict(extra, id="P1.2", status="pending"))
        index[extra["files"][0]] = ["P1.2"]
    return {"meta": {"version": 2, "repo": "demo"},
            "phases": [{"id": "P1", "title": "One", "status": "pending", "tasks": tasks},
                       {"id": "BF10", "title": "Ten", "status": "pending",
                        "tasks": [{"id": "BF10.1", "title": "b", "status": "pending",
                                   "files": ["src/b.ts"]}]}],
            "fileIndex": index, "bugs": []}


def _stopped_merge(tmp, name, env, autocrlf=False, driver=True, theirs_bf=None,
                   before_base=None, merge_args=()):
    """A sharded plan with the driver installed, both sides minting P1.2, and `git
    merge` stopped on P1's shard -> (repo, index path, merge exit, merge output).
    `autocrlf` sets `core.autocrlf=true` in the repository before anything is
    committed, so every file git checks out is CRLF in the work tree. `driver`
    False takes the driver out of this clone's config before the merge, as a clone
    that never installed it is - `.gitattributes` still names it. `theirs_bf` is
    merged into BF10.1 on theirs alone, so BF10's shard is one side's blob;
    `before_base(repo)` runs before the base commit; `merge_args` are added to
    `git merge`."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _harness.git(repo, "init", "-q", "-b", "main")
    if autocrlf:
        _harness.git(repo, "config", "core.autocrlf", "true")
    idx = os.path.join(repo, "docs", "audit", "plan.json")
    _write_json(idx, _window_plan())
    _mio.save_sharded(idx, _window_plan())
    _install(idx)
    if before_base:
        before_base(repo)
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "base")
    _harness.git(repo, "checkout", "-qb", "side")
    theirs = _window_plan({"title": "theirs", "files": ["src/t.ts"]})
    if theirs_bf:
        theirs["phases"][1]["tasks"][0].update(theirs_bf)
    _mio.save_sharded(idx, theirs)
    _harness.git(repo, "commit", "-qam", "theirs")
    _harness.git(repo, "checkout", "-q", "main")
    _mio.save_sharded(idx, _window_plan({"title": "ours", "files": ["src/o.ts"]}))
    _harness.git(repo, "commit", "-qam", "ours")
    if not driver:
        _harness.git(repo, "config", "--remove-section", "merge.%s" % (M.DRIVER_NAME,))
    code, out = _git(repo, env, *(("merge", "-q", "side", "-m", "merge")
                                  + tuple(merge_args)))
    return repo, idx, code, out


def _json_or_none(raw):
    """`raw` parsed, or None when it is not JSON - so a marker block fails the
    spelling conjunct it is compared in rather than raising out of the case."""
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None


def _eol_settings(repo):
    """Every `core.autocrlf`/`core.eol` setting git reads in `repo`, with where it
    came from, or what git answered - printed beside a byte comparison, never
    asserted."""
    done = subprocess.run(["git", "-C", repo, "config", "--show-origin",
                           "--get-regexp", r"^core\.(autocrlf|eol|safecrlf)$"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text = (done.stdout + done.stderr).decode("utf-8", "replace").strip()
    return text or "none set (git exit %d)" % (done.returncode,)


def _plan_bytes(repo):
    """{repo-relative path: bytes} of every plan file under docs/audit."""
    top = os.path.join(repo, "docs", "audit")
    found = {}
    for dp, _d, fs in os.walk(top):
        for f in fs:
            if f.endswith(".json"):
                p = os.path.join(dp, f)
                with open(p, "rb") as fh:
                    found[os.path.relpath(p, repo).replace(os.sep, "/")] = fh.read()
    return found


def _record_into(repo, idx, task_id, phase_id, run_id):
    """A run record written through the evidence layer's own writer, as a gate's
    would be -> its `{"written", "reason"}`."""
    import _evidence_io
    row = {"v": 1, "runId": run_id, "ts": "2026-11-19T10:00:00Z", "scope": "task",
           "taskId": task_id, "phaseId": phase_id, "status": "passed",
           "durationMs": 10, "steps": []}
    return _evidence_io.write_record(repo, idx, "task",
                                     {"taskId": task_id, "phaseId": phase_id},
                                     _evidence_io.run_record(row),
                                     session_id="stray-writer")


def _last_run(repo, phase_id):
    try:
        with open(os.path.join(repo, _W_SHARD % (phase_id,)), encoding="utf-8") as fh:
            return (json.load(fh)["tasks"][0].get("lastRun") or {}).get("runId")
    except (OSError, ValueError, KeyError, IndexError):
        return None


def _land_at_acquire(land):
    """Patch the lock `resolve` takes so `land()` runs once, as resolve asks for
    the lock and before the real acquire - the moment a check made before the lock
    would already have passed. -> (restore, [True once it ran])."""
    real = M._locks.acquire
    ran = []

    def first(*a, **k):
        M._locks.acquire = real
        land()
        ran.append(True)
        return real(*a, **k)
    M._locks.acquire = first

    def restore():
        M._locks.acquire = real
    return restore, ran


class _Interrupted(Exception):
    pass


def _window_cases(check, tmp, env):
    # An undisturbed resolve first: the bytes every other case compares against.
    repo_b, idx_b, _c, _o = _stopped_merge(tmp, "w-plain", env)
    code, out = _resolve(["resolve", idx_b, "--renumber", "theirs"])
    clean = _plan_bytes(repo_b)
    try:
        merged = _mio.load_manifest(idx_b)
    except Exception:                                      # noqa: BLE001
        merged = {"phases": []}
    p1 = [(t["id"], t["title"]) for ph in merged["phases"] if ph["id"] == "P1"
          for t in ph["tasks"]]
    # Each conjunct named, so a red on one platform says which one and with what
    # bytes. The spelling conjunct compares BYTES with the plugin's own document,
    # which is LF on every platform: on Windows a text-mode write turns each LF
    # into CRLF, and on any other platform this conjunct cannot tell the two
    # apart - there it proves only that the bytes are the plugin's spelling.
    spelled = dict((rel, b"<<<<<<<" not in raw and raw.decode("utf-8", "replace")
                    == _mio.json_document(_json_or_none(raw)))
                   for rel, raw in clean.items())
    conjuncts = {"exit 0": code == 0,
                 "renumbered": p1 == [("P1.1", "a"), ("P1.2", "ours"),
                                      ("P1.3", "theirs")],
                 "files": sorted(clean) == ["docs/audit/phases/BF10.json",
                                            "docs/audit/phases/P1.json",
                                            "docs/audit/plan.json"],
                 "spelling": bool(spelled) and all(spelled.values())}
    check("rw4 ALLOW: with no stray write resolve writes as before - exit 0, theirs' "
          "P1.2 renumbered to P1.3, the index and both shards in the plugin's spelling "
          "(LF, on every platform) with no marker: %s" % (out,),
          all(conjuncts.values()),
          "%r on %s, git's line-ending settings as the fixture's git reads them: "
          "%r; bytes %r" % (conjuncts, sys.platform, _eol_settings(repo_b),
                            dict((rel, raw[:90]) for rel, raw in clean.items()
                                 if not spelled.get(rel))))
    # The same plan reached through a symlinked directory - a temp dir under
    # /var on macOS is one - names what it wrote relative to the work tree, and a
    # second run over its own output is accepted.
    link = os.path.join(tmp, "w-plain-link")
    try:
        os.symlink(repo_b, link)
        via = os.path.join(link, "docs", "audit", "plan.json")
    except (OSError, NotImplementedError):
        via = idx_b
    code, out = _resolve(["resolve", via, "--renumber", "theirs"])
    check("rw4b ...and says what it wrote relative to the work tree even when the plan "
          "is reached through a symlink, its own earlier output accepted: %s" % (out,),
          code == 0 and "written: docs/audit/plan.json, %s, %s"
          % (_W_SHARD % "P1", _W_SHARD % "BF10") in out and _plan_bytes(repo_b) == clean)

    repo, idx, code, out = _stopped_merge(tmp, "w-stray", env)
    conflicted = _harness.git(repo, "ls-files", "-u", "--", _W_SHARD % "P1")
    check("rw0 CONTROL: the merge stops on P1's shard, naming the id minted on both "
          "sides, and the index and BF10's shard merge clean",
          code != 0 and "tasks[P1.2]" in out and conflicted.strip()
          and not _harness.git(repo, "ls-files", "-u", "--", "docs/audit/plan.json",
                               _W_SHARD % "BF10").strip(), out)

    # State (a): what a conflicted target holds, and whether a writer reaches it.
    before_p1 = _plan_bytes(repo)[_W_SHARD % "P1"]
    try:
        _mio.load_manifest(idx)
        loads = True
    except Exception:                                      # noqa: BLE001
        loads = False
    into_conflicted = _record_into(repo, idx, "P1.1", "P1", "RX")
    check("rw3 a conflicted target holds the driver's marker block, the plan does not "
          "load, and the evidence writer refuses a record for a task in it, leaving "
          "the bytes git's merge left: %s" % (into_conflicted.get("reason"),),
          b"<<<<<<<" in before_p1 and not loads
          and not into_conflicted.get("written")
          and _plan_bytes(repo)[_W_SHARD % "P1"] == before_p1)

    # The window: a gate's record lands in BF10's clean shard as resolve asks for
    # the lock.
    landed = []
    restore, ran = _land_at_acquire(
        lambda: landed.append(_record_into(repo, idx, "BF10.1", "BF10", "RW")))
    try:
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    finally:
        restore()
    after = _plan_bytes(repo)
    check("rw1 a run record written into a shard git's merge left clean, landed as "
          "resolve asks for its lock, survives: resolve exits non-zero and BF10.1's "
          "record is still RW",
          ran and landed and landed[0].get("written") and code != 0
          and _last_run(repo, "BF10") == "RW", "%s %s\n%s" % (code, landed, out))
    check("rw1b ...and NOTHING is written, the files before the stray one included: "
          "the index and P1's shard (still the driver's markers) are byte for byte "
          "what they held before resolve ran",
          after[_W_SHARD % "P1"] == before_p1
          and b"<<<<<<<" in after[_W_SHARD % "P1"]
          and after["docs/audit/plan.json"]
          == _harness.git(repo, "show", ":docs/audit/plan.json").encode("utf-8"), out)
    check("rw1c ...the refusal names the stray file and no other, says nothing was "
          "written, and names the command that puts it back as the merge left it: %s"
          % (out,),
          (_W_SHARD % "BF10") in out and (_W_SHARD % "P1") not in out
          and "nothing was written" in out
          and "git checkout -- %s" % (_W_SHARD % "BF10",) in out
          and "--reconcile" in out)
    _harness.git(repo, "checkout", "--", _W_SHARD % "BF10")
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rw2 the way on is true: after `git checkout --` on the stray file resolve "
          "completes, writing what the undisturbed resolve wrote: %s" % (out,),
          code == 0 and _plan_bytes(repo) == clean)
    # ...and what the refusal says comes back does: the discarded record's run,
    # held as a ledger row (the gate writes the row before the record), is put
    # back by reconcile once the merge is committed.
    import _evidence_io
    discarded = _last_run(repo, "BF10")
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "merged")
    _evidence_io.append_row(repo, {"v": 1, "runId": "RW", "ts": "2026-11-19T10:00:00Z",
                                   "scope": "task", "taskId": "BF10.1", "phaseId": "BF10",
                                   "status": "passed", "durationMs": 10, "steps": []},
                            session_id="stray-writer")
    caught = _evidence_io.reconcile(repo, idx, session_id="after-merge")
    check("rw2b ...and the discarded run record comes back as the refusal says: with "
          "the merge committed, reconcile points BF10.1 at RW from its ledger row: %s"
          % (caught.get("moved"),),
          discarded != "RW" and _last_run(repo, "BF10") == "RW", (discarded, caught))

    # Interrupted after its first target: the second call completes.
    repo_c, idx_c, _c, _o = _stopped_merge(tmp, "w-interrupted", env)
    real_write = M._write
    wrote = []

    def stop_after_first(path, text, newline="\n"):
        real_write(path, text, newline)
        # Only a write into the work tree is resolve's own: the scratch files the
        # reference reruns a content merge in sit outside it.
        if os.path.relpath(os.path.realpath(path),
                           os.path.realpath(repo_c)).startswith(".."):
            return
        wrote.append(os.path.relpath(path, repo_c).replace(os.sep, "/"))
        raise _Interrupted()
    M._write = stop_after_first
    try:
        try:
            M.resolve(idx_c, "theirs")
        except _Interrupted:
            pass
    finally:
        M._write = real_write
    partial = _plan_bytes(repo_c)
    code, out = _resolve(["resolve", idx_c, "--renumber", "theirs"])
    check("rw5 a resolve stopped after writing its first target is completed by the "
          "next call rather than refused for ever by its own write: the stop wrote the "
          "index alone and changed it, and the rerun exits 0 with the undisturbed "
          "bytes: %s" % (out,),
          wrote == ["docs/audit/plan.json"]
          and partial["docs/audit/plan.json"] != _harness.git(
              repo_c, "show", ":docs/audit/plan.json").encode("utf-8")
          and code == 0 and _plan_bytes(repo_c) == clean, wrote)

    # A conflicted target holding JSON (a hand resolution, or a write into it) is
    # a stray too: only markers, or resolve's own bytes, are accounted for there.
    repo_d, idx_d, _c, _o = _stopped_merge(tmp, "w-hand", env)
    _split, shards = _mio.split_manifest(
        _window_plan({"title": "ours", "files": ["src/o.ts"]}))
    with open(os.path.join(repo_d, _W_SHARD % "P1"), "w", encoding="utf-8") as fh:
        fh.write(_mio.json_document(shards["P1"]))
    hand = _plan_bytes(repo_d)
    code, out = _resolve(["resolve", idx_d, "--renumber", "theirs"])
    refused = code != 0 and _plan_bytes(repo_d) == hand \
        and "git checkout -m -- %s" % (_W_SHARD % "P1",) in out
    _harness.git(repo_d, "checkout", "-m", "--", _W_SHARD % "P1")
    code2, out2 = _resolve(["resolve", idx_d, "--renumber", "theirs"])
    check("rw6 a conflicted target holding JSON instead of the driver's markers is "
          "refused with nothing written, naming `git checkout -m --`, and after that "
          "command brings the conflict back resolve completes: %s | %s" % (out, out2),
          refused and code2 == 0 and _plan_bytes(repo_d) == clean)
    _moved_index_cases(check, tmp, env, clean)


def _hand_resolved(repo):
    """P1's shard rewritten by hand as one side's JSON - a resolution the person
    typed, which no marker block marks."""
    _split, shards = _mio.split_manifest(
        _window_plan({"title": "ours", "files": ["src/o.ts"]}))
    with open(os.path.join(repo, _W_SHARD % "P1"), "w", encoding="utf-8") as fh:
        fh.write(_mio.json_document(shards["P1"]))


def _fix_lines(out):
    """The commands a stray refusal names to put each file back, one argv each."""
    import shlex
    lines = out.splitlines()
    at = [i for i, ln in enumerate(lines) if ln.rstrip().endswith("then run resolve again:")]
    if not at:
        return []
    found = []
    for ln in lines[at[0] + 1:]:
        if not ln.startswith("      "):
            break
        found.append(shlex.split(ln.strip()))
    return found


def _moved_index_cases(check, tmp, env, clean):
    # THE REFERENCE IS NOT THE INDEX. Every command here moves the index during a
    # stopped merge, and each is routine while a conflict is open: a stray write
    # it stages must still be refused, with nothing written and the write kept.
    # Before the reference was the merge's own result, each staged row below
    # passed the refusal and was overwritten.
    rows = (
        ("the stray record's shard staged by name",
         lambda r: _harness.git(r, "add", "--", _W_SHARD % "BF10"), "BF10"),
        ("every tracked change staged (`git add -u`)",
         lambda r: _harness.git(r, "add", "-u"), "BF10"),
        ("staged, then written again",
         lambda r: (_harness.git(r, "add", "--", _W_SHARD % "BF10"),
                    _record_into(r, os.path.join(r, "docs", "audit", "plan.json"),
                                 "BF10.1", "BF10", "RT")), "BF10"),
        ("the conflicted shard resolved by hand and staged",
         lambda r: (_hand_resolved(r), _harness.git(r, "add", "--", _W_SHARD % "P1")),
         "P1"))
    held, refused = [], []
    for i, (label, stage, stray) in enumerate(rows):
        repo, idx, _c, _o = _stopped_merge(tmp, "w-moved-%d" % (i,), env)
        landed = {}
        if stray == "BF10":
            landed = _record_into(repo, idx, "BF10.1", "BF10", "RS")
        stage(repo)
        before = _plan_bytes(repo)
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        ok = (code != 0 and _plan_bytes(repo) == before
              and "nothing was written" in out and (_W_SHARD % stray) in out
              and (stray != "BF10" or (landed.get("written")
                                       and _last_run(repo, "BF10") in ("RS", "RT"))))
        if not ok:
            held.append((label, code, out[-400:]))
        refused.append((label, repo, idx, out))
    check("rw7 A STRAY WRITE THE INDEX WAS MOVED OVER IS STILL REFUSED - staged by "
          "name, by `git add -u`, staged then written again, a hand resolution "
          "staged: each exits non-zero, writes nothing, keeps the write and names "
          "its file; not refused as said: %r" % (held,), held == [])
    # Each row's printed commands, run as printed: the clean shard's blob staged
    # from its side, and the conflicted shard's marker text - a content merge no
    # commit holds - staged from git's object store.
    untrue = []
    for label, repo, idx, out in refused:
        fixes = _fix_lines(out)
        for argv in fixes:
            if argv[:1] == ["git"]:
                _harness.git(repo, *argv[1:])
        code, out2 = _resolve(["resolve", idx, "--renumber", "theirs"])
        if not (fixes and all(a[:1] == ["git"] for a in fixes)
                and ["git", "update-index", "--cacheinfo"] in [a[:3] for a in fixes]
                and code == 0 and _plan_bytes(repo) == clean):
            untrue.append((label, fixes, code, out2[-300:]))
    check("rw7b ...and the commands it names for a STAGED stray are true: run as "
          "printed they put the file back as git's merge left it, index and work "
          "tree, and resolve then completes with the undisturbed bytes - for a "
          "clean shard and for the conflicted one; untrue: %r" % (untrue,),
          len(refused) == len(rows) and untrue == [])

    # SECOND DIRECTION: the index moved with NOTHING stray in the tree - every
    # file staged as the merge left it, markers included - is no refusal. The
    # case that goes red when the reference over-fires on a moved index.
    repo, idx, _c, _o = _stopped_merge(tmp, "w-all-staged", env)
    _harness.git(repo, "add", "-A")
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rw8 ALLOW: every plan file staged as the merge left it (the marker block "
          "included) is no stray - resolve exits 0 with the undisturbed bytes: %s"
          % (out,), code == 0 and _plan_bytes(repo) == clean)

    # A CRLF WORK TREE: git checks text out with CRLF where `core.autocrlf` asks
    # for it, so a file the merge left clean differs byte for byte from the LF
    # blob. The comparison is of text read with universal newlines against the
    # blob as checkout would write it, so neither the allow nor the refusal
    # depends on the line endings.
    repo, idx, _c, _o = _stopped_merge(tmp, "w-crlf", env, autocrlf=True)
    with open(os.path.join(repo, "docs", "audit", "plan.json"), "rb") as fh:
        crlf = b"\r\n" in fh.read()
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    allowed = code == 0
    repo2, idx2, _c, _o = _stopped_merge(tmp, "w-crlf-stray", env, autocrlf=True)
    landed = _record_into(repo2, idx2, "BF10.1", "BF10", "RC")
    _harness.git(repo2, "add", "--", _W_SHARD % "BF10")
    code2, out2 = _resolve(["resolve", idx2, "--renumber", "theirs"])
    check("rw9 IN A CRLF WORK TREE (`core.autocrlf=true`, the index file checked "
          "out with CRLF: %r) no stray is resolved and a staged stray is refused "
          "with the record kept: %s | %s" % (crlf, out, out2),
          crlf and allowed and code2 != 0 and landed.get("written")
          and _last_run(repo2, "BF10") == "RC")

    # A CLONE THAT NEVER CONFIGURED THE DRIVER gets git's line merge for every plan
    # file both sides changed, and the reference reruns that line merge rather
    # than the driver - so the files git's markers left are accounted for, and a
    # staged stray in the shard both sides left alone is still refused.
    found = []
    for name in ("w-no-driver", "w-no-driver-stray"):
        repo, idx, mcode, _o = _stopped_merge(tmp, name, env, driver=False)
        landed = {}
        if name.endswith("stray"):
            # Written into the shard by hand: the evidence writer reads the index
            # first, and here the index holds git's markers.
            shard = os.path.join(repo, _W_SHARD % "BF10")
            with open(shard, encoding="utf-8") as fh:
                body = json.load(fh)
            body["tasks"][0]["lastRun"] = {"runId": "RD"}
            with open(shard, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(_mio.json_document(body))
            landed = {"written": True}
            _harness.git(repo, "add", "--", _W_SHARD % "BF10")
        with open(idx, "rb") as fh:
            markers = b"<<<<<<<" in fh.read()
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        found.append((mcode, markers, code, landed.get("written"),
                      _last_run(repo, "BF10"), out[-300:]))
    check("rw10 WITHOUT THE DRIVER (git's line merge left markers in the index: "
          "%r) resolve writes over the markers git left, and refuses a staged stray "
          "with the record kept: %r" % ([f[1] for f in found], found),
          found[0][0] != 0 and found[0][1] and found[0][2] == 0
          and found[1][2] != 0 and found[1][3] and found[1][4] == "RD")
    _kept_edit_cases(check, tmp, env, clean)
    _odd_file_cases(check, tmp, env, clean)
    _reference_cases(check, tmp, env, clean)


def _edit_inside_block(repo):
    """An edit typed INSIDE the driver's marker block of P1's shard, every marker
    line kept -> True when it landed between `<<<<<<<` and `=======`."""
    path = os.path.join(repo, _W_SHARD % "P1")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.find("<<<<<<<")
    mid = text.find("\n=======", start)
    old = '"title": "ours"'
    if start < 0 or mid < 0 or text.count(old, start, mid) != 1:
        return False
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text[:start] + text[start:mid].replace(old, '"title": "ours, typed"')
                 + text[mid:])
    return True


def _drop_marker_line(repo):
    """P1's shard with the first `=======` marker line deleted and nothing else ->
    True when there was one to delete (the driver writes a block per differing
    hunk, so there may be more)."""
    path = os.path.join(repo, _W_SHARD % "P1")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if "=======" not in lines:
        return False
    lines.remove("=======")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines))
    return True


def _put_back_and_resolve(repo, idx, out):
    """Run the commands a refusal printed, as printed, then resolve again ->
    (the commands, exit, output)."""
    fixes = _fix_lines(out)
    for argv in fixes:
        if argv[:1] == ["git"]:
            _harness.git(repo, *argv[1:])
    code, out2 = _resolve(["resolve", idx, "--renumber", "theirs"])
    return fixes, code, out2


def _kept_edit_cases(check, tmp, env, clean):
    # A CONFLICTED FILE IS WRITTEN OVER ONLY AS GIT'S MERGE LEFT IT. Markers still
    # in the file say nothing about whether a person typed inside them, so the
    # only bytes resolve may replace are git's merge result or its own output.
    rows = (("an edit inside the driver's marker block, every marker kept",
             _edit_inside_block, False),
            ("the same edit staged with `git add`", _edit_inside_block, True),
            ("a `=======` marker line deleted", _drop_marker_line, False))
    lost, refused = [], []
    for i, (label, edit, stage) in enumerate(rows):
        repo, idx, _c, _o = _stopped_merge(tmp, "w-kept-%d" % (i,), env)
        landed = edit(repo)
        if stage:
            _harness.git(repo, "add", "--", _W_SHARD % "P1")
        before = _plan_bytes(repo)
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        if not (landed and code != 0 and _plan_bytes(repo) == before
                and "nothing was written" in out and (_W_SHARD % "P1") in out):
            lost.append((label, landed, code, out[-300:]))
        refused.append((label, repo, idx, out))
    check("rw11 A CONFLICTED FILE CHANGED SINCE THE MERGE LEFT IT IS NEVER WRITTEN "
          "OVER, markers or not - an edit inside the marker block, the same edit "
          "staged, a `=======` marker line deleted: each exits non-zero, writes "
          "nothing and names P1's shard; written over, or not refused as said: %r"
          % (lost,), lost == [])
    untrue = []
    for label, repo, idx, out in refused:
        fixes, code, out2 = _put_back_and_resolve(repo, idx, out)
        if not (fixes and all(a[:1] == ["git"] for a in fixes)
                and code == 0 and _plan_bytes(repo) == clean):
            untrue.append((label, fixes, code, out2[-300:]))
    check("rw11b ...and the commands it names put the shard back as git's merge left "
          "it, after which resolve completes with the undisturbed bytes; untrue: %r"
          % (untrue,), len(refused) == len(rows) and untrue == [])

    # git's own line merge labels its markers with the names `git merge` was
    # given; the answer resolve asks git for is labelled by HEAD and MERGE_HEAD.
    repo, idx, mcode, _o = _stopped_merge(tmp, "w-kept-labels", env, driver=False)
    with open(os.path.join(repo, _W_SHARD % "P1"), encoding="utf-8") as fh:
        labelled = ">>>>>>> side\n" in fh.read()
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rw11c ALLOW: a conflicted file exactly as git's own line merge left it is "
          "written over although its marker lines name the branch merged "
          "(`>>>>>>> side`: %r) - the labels carry nothing of the plan: %s"
          % (labelled, out), mcode != 0 and labelled and code == 0)


def _with_bom(repo):
    path = os.path.join(repo, _W_SHARD % "BF10")
    with open(path, "rb") as fh:
        raw = fh.read()
    with open(path, "wb") as fh:
        fh.write(b"\xef\xbb\xbf" + raw)


def _odd_file_cases(check, tmp, env, clean):
    # A CRLF checkout of a file the merge took from one side whole, which resolve
    # rewrites: the reference is that side's blob, and git's own "unchanged" test
    # (`hash-object --path`, through the same filters) finds the CRLF copy equal
    # to it - so this case holds with newlines read either way (measured: it
    # stayed green with the newline reading removed). rw12b is the one that
    # needs the newline reading.
    repo, idx, _c, _o = _stopped_merge(tmp, "w-crlf-blob", env, autocrlf=True,
                                       theirs_bf={"blockedBy": ["P1.2"]})
    shard = os.path.join(repo, _W_SHARD % "BF10")
    with open(shard, "rb") as fh:
        before = fh.read()
    one_side = not _harness.git(repo, "ls-files", "-u", "--", _W_SHARD % "BF10").strip()
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    with open(shard, "rb") as fh:
        after = _json_or_none(fh.read()) or {}
    blocked = ((after.get("tasks") or [{}])[0]).get("blockedBy")
    check("rw12 A CRLF CHECKOUT OF A FILE THE MERGE TOOK FROM ONE SIDE is what the "
          "merge left there: BF10's shard (theirs' blob, CRLF in the work tree: %r, "
          "merged clean: %r), which the renumbering rewrites, is written over - exit "
          "0, now blocked by P1.3: %r %s" % (b"\r\n" in before, one_side, blocked, out),
          b"\r\n" in before and one_side and code == 0 and blocked == ["P1.3"])

    # A CRLF checkout of a file git's own line merge left conflicted (no driver):
    # its markers name the branch, so no oid of it is git's answer's, and only
    # the text read with universal newlines and labels dropped is the same.
    repo, idx, mcode, _o = _stopped_merge(tmp, "w-crlf-markers", env, autocrlf=True,
                                          driver=False)
    with open(os.path.join(repo, _W_SHARD % "P1"), "rb") as fh:
        held = fh.read()
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rw12b ALLOW: A CRLF CHECKOUT OF A FILE GIT LEFT CONFLICTED, exactly as "
          "left, is written over - CRLF: %r, markers: %r, exit %r: %s"
          % (b"\r\n" in held, b"<<<<<<<" in held, code, out),
          mcode != 0 and b"\r\n" in held and b"<<<<<<<" in held and code == 0)

    repo, idx, mcode, _o = _stopped_merge(tmp, "w-bom", env, before_base=_with_bom)
    before = _plan_bytes(repo)
    try:
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    except Exception as exc:                                # noqa: BLE001
        code, out = None, "raised %r" % (exc,)
    check("rw13 A PLAN FILE COMMITTED WITH A BYTE ORDER MARK is refused with a "
          "sentence, not a traceback: exit 1, nothing written, the commit whose plan "
          "could not be read named with what the reader said: %s" % (out,),
          mcode != 0 and code == 1 and _plan_bytes(repo) == before
          and "nothing was written" in out and "cannot be read" in out
          and "BOM" in out)

    # A plan file replaced by a symbolic link: writing the merged plan would put a
    # regular file where the link was and leave what it points to as it is.
    held, untrue, cannot = [], [], None
    for i, edited in enumerate((True, False)):
        repo, idx, _c, _o = _stopped_merge(tmp, "w-link-%d" % (i,), env)
        shard = os.path.join(repo, _W_SHARD % "BF10")
        outside = os.path.join(tmp, "w-link-outside-%d.json" % (i,))
        with open(shard, encoding="utf-8") as fh:
            body = json.load(fh)
        if edited:
            body["tasks"][0]["title"] = "typed through the link"
        with open(outside, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_mio.json_document(body))
        os.remove(shard)
        try:
            os.symlink(outside, shard)
        except (OSError, NotImplementedError) as exc:
            cannot = exc
            break
        with open(outside, "rb") as fh:
            kept = fh.read()
        before = _plan_bytes(repo)
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        with open(outside, "rb") as fh:
            same = fh.read() == kept
        if not (code != 0 and os.path.islink(shard) and same
                and _plan_bytes(repo) == before and "nothing was written" in out
                and (_W_SHARD % "BF10") in out):
            held.append((edited, code, os.path.islink(shard), same, out[-300:]))
            continue
        fixes, code, out2 = _put_back_and_resolve(repo, idx, out)
        if not (fixes and code == 0 and not os.path.islink(shard)
                and _plan_bytes(repo) == clean):
            untrue.append((edited, fixes, code, out2[-300:]))
    if cannot is not None:
        _harness.skip(check, "rw14 a plan file replaced by a symbolic link",
                      "a symbolic link could not be made here: %r" % (cannot,), True)
        return
    check("rw14 A PLAN FILE REPLACED BY A SYMBOLIC LINK is refused, whether what it "
          "points to was edited or not: exit non-zero, nothing written, the link "
          "still a link and its target's bytes kept, the shard named; not as said: %r"
          % (held,), held == [])
    check("rw14b ...and the commands it names put a regular file back as the merge "
          "left it, after which resolve completes with the undisturbed bytes; "
          "untrue: %r" % (untrue,), held == [] and untrue == [])


# --- the reference: git's own answer, and the rebuilt one where git cannot give it --
_SMUDGE = ("import sys\n"
           "raw = sys.stdin.buffer.read()\n"
           "if sys.argv[1] == 'smudge':\n"
           "    sys.stdout.buffer.write(b' ' + raw)\n"
           "else:\n"
           "    sys.stdout.buffer.write(raw[1:] if raw[:1] == b' ' else raw)\n")


def _smudged(repo):
    """A clean/smudge filter over every .json: checkout puts one space before the
    first byte and `git add` takes it off, so the work tree never holds the
    blob's bytes."""
    script = os.path.join(repo, "..", os.path.basename(repo) + "-filter.py")
    with open(script, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_SMUDGE)
    run = '"%s" "%s"' % (sys.executable.replace("\\", "/"),
                         os.path.abspath(script).replace("\\", "/"))
    _harness.git(repo, "config", "filter.lead.smudge", run + " smudge")
    _harness.git(repo, "config", "filter.lead.clean", run + " clean")
    with open(os.path.join(repo, ".gitattributes"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write("*.json filter=lead\n")


def _shard_doc(tasks):
    return {"id": "P1", "title": "One", "status": "pending",
            "tasks": [{"id": i, "title": t, "status": "pending", "files": [f]}
                      for i, t, f in tasks]}


def _line_repo(tmp, name):
    """A repository holding P1's shard alone, with no driver -> (repo, commit fn)."""
    repo = os.path.join(tmp, name)
    os.makedirs(os.path.join(repo, "docs", "audit", "phases"))
    _harness.git(repo, "init", "-q", "-b", "main")
    shard = os.path.join(repo, _W_SHARD % "P1")

    def commit(tasks, message):
        with open(shard, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_mio.json_document(_shard_doc(tasks)))
        _harness.git(repo, "add", "-A")
        _harness.git(repo, "commit", "-qm", message)
    return repo, commit


def _algorithm_merge(tmp, env):
    """A merge whose line merge differs by diff algorithm: git's merge (histogram,
    as `merge-ort` runs it) and `git merge-file` (myers) end the conflict hunk on
    different lines. Found by search over random shard edits, then checked: the
    work tree equals `merge-file --diff-algorithm=histogram`, not the default."""
    repo, commit = _line_repo(tmp, "fam-algorithm")
    commit([("P1.1", "t0", "src/0.ts"), ("P1.2", "t1", "src/1.ts"),
            ("P1.3", "t2", "src/2.ts")], "base")
    _harness.git(repo, "checkout", "-qb", "side")
    commit([("P1.1", "t0", "src/0.ts"), ("P1.6", "t1", "src/a.ts"),
            ("P1.2", "t1", "src/1.ts"), ("P1.3", "t2", "src/2.ts"),
            ("P1.6", "t1", "src/1.ts")], "theirs")
    _harness.git(repo, "checkout", "-q", "main")
    commit([("P1.2", "t1", "src/1.ts"), ("P1.7", "t1", "src/0.ts"),
            ("P1.3", "t2", "src/2.ts")], "ours")
    _git(repo, env, "merge", "-q", "side", "-m", "merge")
    return repo


def _criss_cross_merge(tmp, env):
    """A merge with two merge bases that disagree: each side merged the other's
    first commit and kept its own title by hand. git merges the bases into one
    first (a base that itself conflicts), so both sides changed the title; from
    either base alone, one side did not, and the title merges clean."""
    repo, commit = _line_repo(tmp, "fam-criss-cross")
    task = lambda title: [("P1.1", "a", "src/a.ts"), ("P1.2", title, "src/b.ts")]  # noqa: E731
    commit(task("b"), "base")
    _harness.git(repo, "checkout", "-qb", "A")
    commit(task("bA"), "A1")
    _harness.git(repo, "checkout", "-qb", "B", "main")
    commit(task("bB"), "B1")
    _harness.git(repo, "checkout", "-q", "A")
    _git(repo, env, "merge", "-q", "B", "-m", "AxB")
    commit(task("bA"), "AxB")
    _harness.git(repo, "checkout", "-q", "B")
    _git(repo, env, "merge", "-q", "A~1", "-m", "BxA")
    commit(task("bB"), "BxA")
    _harness.git(repo, "checkout", "-q", "A")
    _git(repo, env, "merge", "-q", "B", "-m", "final")
    return repo


# Where git's answer and the rebuilt one may differ, and why - every other
# difference is a defect of the rebuild. Each is shown by the fixture named.
_ALLOWED = {
    "labels": ("no-driver", "the marker lines' labels: git's line merge names the "
               "commits it was given, the rebuild names its scratch files, and a "
               "label carries nothing of the plan"),
    "diff algorithm": ("diff-algorithm", "merge-ort runs its line merge with the "
                       "histogram diff, `git merge-file` with myers"),
    "merge base": ("criss-cross", "git merges several merge bases into one first; "
                   "the rebuild takes the one `git merge-base` names")}


def _family(tmp, env):
    """[(name, repo)] - every merge the reference is asked about, each stopped."""
    found = []
    for name, kw in (("driver", {}), ("no-driver", {"driver": False}),
                     ("crlf", {"autocrlf": True}),
                     ("crlf-no-driver", {"autocrlf": True, "driver": False}),
                     ("one-side-blob", {"theirs_bf": {"blockedBy": ["P1.2"]}}),
                     ("filtered", {"before_base": _smudged}),
                     ("filtered-no-driver", {"before_base": _smudged,
                                             "driver": False})):
        found.append((name, _stopped_merge(tmp, "fam-" + name, env, **kw)[0]))
    found.append(("diff-algorithm", _algorithm_merge(tmp, env)))
    found.append(("criss-cross", _criss_cross_merge(tmp, env)))
    return found


def _reference_cases(check, tmp, env, clean):
    withheld = {"tree": None, "conflicted": frozenset(), "why": "withheld by the case"}
    unlike, rebuilt_diffs, asked = [], [], []
    for name, repo in _family(tmp, env):
        top = os.path.realpath(repo)
        base = _harness.git(repo, "merge-base", "HEAD", "MERGE_HEAD").strip()
        answer = M._merge_answer(top)
        asked.append((name, bool(answer["tree"]), answer["why"]))
        for rel in sorted(_plan_bytes(repo)):
            held = M._held_text(os.path.join(repo, rel))
            gits, p1 = M._reference(top, base, rel, answer)
            rebuilt, p2 = M._reference(top, base, rel, withheld)
            if p1 or p2 or gits is None or rebuilt is None:
                unlike.append((name, rel, "no reference", p1, p2))
                continue
            if not M._as_merge_left(top, os.path.join(repo, rel), rel, held, gits):
                unlike.append((name, rel, "git's answer is not the work tree",
                               held[:200], gits["text"][:200]))
            if gits["text"] == rebuilt["text"]:
                continue
            kind = ("labels" if M._same_as_left(gits["text"], rebuilt["text"], 7,
                                                lambda _k, _l: True) else None)
            rebuilt_diffs.append((name, rel, kind))
    check("rw15 GIT'S OWN ANSWER IS WHAT `git merge` LEFT, git's labels aside, in every "
          "merge of the family (driver, no driver, CRLF, one side's blob, a smudge "
          "filter, diff algorithm, criss-cross), asked of every git here: %r; "
          "unlike: %r" % (asked, unlike),
          unlike == [] and all(a[1] for a in asked) and len(asked) >= 9)
    seen, stray = set(), []
    for name, rel, kind in rebuilt_diffs:
        allowed = kind or next((k for k, (fx, _w) in _ALLOWED.items()
                                if fx == name and k != "labels"), None)
        if allowed is None:
            stray.append((name, rel))
        else:
            seen.add((allowed, name))
    unshown = [k for k, (fx, _w) in _ALLOWED.items() if (k, fx) not in seen]
    check("rw16 THE REBUILT REFERENCE DIFFERS FROM GIT'S ONLY WHERE A DIFFERENCE IS "
          "NAMED, and each named one is shown by its fixture - %s; differences "
          "seen: %r; unnamed: %r; named but not shown: %r"
          % ("; ".join("%s (%s): %s" % (k, fx, why) for k, (fx, why) in _ALLOWED.items()),
             sorted(seen), stray, unshown), stray == [] and unshown == [])

    # The same property on the rebuilt path: what git left resolves, an edit
    # inside the markers is refused, and the refusal says the reference was rebuilt.
    real = M._merge_answer
    M._merge_answer = lambda top: dict(withheld, why="`git merge-tree` answered 129")
    try:
        repo, idx, _c, _o = _stopped_merge(tmp, "w-rebuilt-allow", env)
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        repo2, idx2, _c, _o = _stopped_merge(tmp, "w-rebuilt-edit", env)
        landed = _edit_inside_block(repo2)
        before = _plan_bytes(repo2)
        code2, out2 = _resolve(["resolve", idx2, "--renumber", "theirs"])
    finally:
        M._merge_answer = real
    check("rw17 WHERE GIT CANNOT ANSWER, THE REBUILT REFERENCE HOLDS THE SAME LINE: "
          "the shard as the merge left it resolves with the undisturbed bytes, an "
          "edit inside its markers is refused with nothing written, and the refusal "
          "says what git answered and what the rebuild cannot know: %s | %s"
          % (out, out2),
          code == 0 and _plan_bytes(repo) == clean and landed and code2 != 0
          and _plan_bytes(repo2) == before and "answered 129" in out2
          and "merge base" in out2 and "-X" in out2)

    _marker_line_cases(check, tmp, env, clean)

    # Measured, and what the documents say: with the driver an `-X` option does
    # not reach the record merge, so the stop is the same and resolve resolves;
    # without it, `-X ours` decides every hunk and the merge does not stop.
    repo, idx, mcode, _o = _stopped_merge(tmp, "w-x-ours", env, merge_args=("-X", "ours"))
    code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
    repo2, _i, mcode2, _o2 = _stopped_merge(tmp, "w-x-ours-no-driver", env, driver=False,
                                           merge_args=("-X", "ours"))
    check("rw18 `git merge -X ours` with the driver stops as without the option and "
          "resolve completes with the undisturbed bytes; without the driver the "
          "merge does not stop (exit %r), so there is nothing to resolve: %s"
          % (mcode2, out),
          mcode != 0 and code == 0 and _plan_bytes(repo) == clean and mcode2 == 0)


def _style(value):
    """A `before_base` setting the clone's `merge.conflictStyle`."""
    return lambda repo: _harness.git(repo, "config", "merge.conflictStyle", value)


def _marker_size_9(repo):
    """A `before_base` giving the plan's JSON files conflict markers of nine."""
    with open(os.path.join(repo, ".gitattributes"), "a", encoding="utf-8") as fh:
        fh.write("*.json conflict-marker-size=9\n")


def _on_marker(repo, kind, change):
    """Rewrite P1's first marker line of `kind` (a regex of its run) with
    `change(line)` -> whether such a line was there to rewrite."""
    import re
    shard = os.path.join(repo, _W_SHARD % "P1")
    with open(shard, encoding="utf-8", newline="") as fh:
        text = fh.read()
    match = re.search(r"^%s.*$" % (kind,), text, re.M)
    if not match:
        return False
    with open(shard, "w", encoding="utf-8", newline="") as fh:
        fh.write(text[:match.start()] + change(match.group(0)) + text[match.end():])
    return True


def _marker_line_cases(check, tmp, env, clean):
    """(rw19-rw21) A marker line differs from git's answer only by a label git
    would write there; the marker run is the file's own; the rebuild writes the
    conflict in the repository's style."""
    rows = (("a note after the driver's `<<<<<<< ours`", {}, "<{7} ",
             lambda line: line + "  NOTE: keep ours, ask"),
            ("a note after git's `<<<<<<< HEAD`", {"driver": False}, "<{7} ",
             lambda line: line + " NOTE"),
            ("trailing spaces on git's `>>>>>>> side`", {"driver": False}, ">{7} ",
             lambda line: line + "   "),
            ("the diff3 base label rewritten", {"driver": False,
                                                "before_base": _style("diff3")},
             r"\|{7}", lambda line: "||||||| base MINE"))
    said = []
    for n, (label, kw, kind, change) in enumerate(rows):
        repo, idx, _c, _o = _stopped_merge(tmp, "w-marker-note-%d" % (n,), env, **kw)
        landed = _on_marker(repo, kind, change)
        before = _plan_bytes(repo)
        code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
        said.append((label, landed, code, _plan_bytes(repo) == before,
                     "conflict markers" in out))
    check("rw19 TEXT TYPED ON A MARKER LINE IS A DIFFERENCE, refused with nothing "
          "written: only a label git (or this driver) would write there is set "
          "aside - %r" % (said,),
          all(landed and code != 0 and kept and named
              for _l, landed, code, kept, named in said))

    allowed = []
    for name, kw in (("diff3", {"before_base": _style("diff3")}),
                     ("zdiff3", {"before_base": _style("zdiff3")}),
                     ("conflict-marker-size=9", {"before_base": _marker_size_9})):
        for path_name, withheld in (("git's answer", False), ("the rebuild", True)):
            repo, idx, mcode, _o = _stopped_merge(
                tmp, "w-style-%s-%s" % (name.split("=")[0], int(withheld)), env,
                driver=False, **kw)
            real = M._merge_answer
            if withheld:
                M._merge_answer = lambda top: {"tree": None, "conflicted": frozenset(),
                                               "why": "withheld by the case"}
            try:
                code, out = _resolve(["resolve", idx, "--renumber", "theirs"])
            finally:
                M._merge_answer = real
            allowed.append((name, path_name, mcode != 0, code,
                            _plan_bytes(repo) == clean))
    check("rw20 ALLOW: A CONFLICT LEFT AS GIT WRITES IT - diff3, zdiff3, markers of "
          "nine - is written over on git's answer AND on the rebuild, which writes "
          "the conflict in the repository's style and the file's marker size: %r"
          % (allowed,),
          len(allowed) == 6 and all(stopped and code == 0 and same
                                    for _n, _p, stopped, code, same in allowed))


def _load_or_empty(path):
    """The file as JSON, or {} when it does not parse - so a case that finds markers
    fails as ITSELF rather than taking every later case down with it."""
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except ValueError:
        return {}


def _rules_findings(doc):
    import _manifest_rules
    return _manifest_rules.validate(doc)[0]


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_merge_manifest.py --selftest\n")
    raise SystemExit(2)
