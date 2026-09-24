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
import shutil
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
        _install_cases(check, tmp)
        _git_cases(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
        doc = json.loads(text)
        check("mm16 with the driver installed the same merge is clean, and both phases "
              "and both bugs are in the plan",
              code == 0 and [p["id"] for p in doc["phases"]][-2:] == ["BF11", "BF12"]
              and [b["id"] for b in doc["bugs"]] == ["BUG-2", "BUG-3"], out)
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
    finally:
        os.environ.clear()
        os.environ.update(held)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_merge_manifest.py --selftest\n")
    raise SystemExit(2)
