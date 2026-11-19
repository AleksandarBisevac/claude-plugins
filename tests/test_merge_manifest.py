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
        _window_cases(check, tmp, env)
    finally:
        os.environ.clear()
        os.environ.update(held)


def _resolve(argv):
    held = sys.stdout, sys.stderr
    buf = io.StringIO()
    sys.stdout = sys.stderr = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout, sys.stderr = held
    return code, buf.getvalue()


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
# decided under the index lock, before the first write: a conflicted path holding
# the driver's markers (which no plan writer can read, so none can have written),
# a path equal to what git's merge left or to what resolve is about to write, or a
# stray - and one stray refuses the whole write.
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


def _stopped_merge(tmp, name, env, autocrlf=False):
    """A sharded plan with the driver installed, both sides minting P1.2, and `git
    merge` stopped on P1's shard -> (repo, index path, merge exit, merge output).
    `autocrlf` sets `core.autocrlf=true` in the repository before anything is
    committed, so every file git checks out is CRLF in the work tree."""
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    _harness.git(repo, "init", "-q", "-b", "main")
    if autocrlf:
        _harness.git(repo, "config", "core.autocrlf", "true")
    idx = os.path.join(repo, "docs", "audit", "plan.json")
    _write_json(idx, _window_plan())
    _mio.save_sharded(idx, _window_plan())
    _install(idx)
    _harness.git(repo, "add", "-A")
    _harness.git(repo, "commit", "-qm", "base")
    _harness.git(repo, "checkout", "-qb", "side")
    _mio.save_sharded(idx, _window_plan({"title": "theirs", "files": ["src/t.ts"]}))
    _harness.git(repo, "commit", "-qam", "theirs")
    _harness.git(repo, "checkout", "-q", "main")
    _mio.save_sharded(idx, _window_plan({"title": "ours", "files": ["src/o.ts"]}))
    _harness.git(repo, "commit", "-qam", "ours")
    code, out = _git(repo, env, "merge", "-q", "side", "-m", "merge")
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

    def stop_after_first(path, text, newline=None):
        real_write(path, text, newline)
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
    held, first = [], None
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
        if i == 0:
            first = (repo, idx, out)
    check("rw7 A STRAY WRITE THE INDEX WAS MOVED OVER IS STILL REFUSED - staged by "
          "name, by `git add -u`, staged then written again, a hand resolution "
          "staged: each exits non-zero, writes nothing, keeps the write and names "
          "its file; not refused as said: %r" % (held,), held == [])
    repo, idx, out = first
    fixes = _fix_lines(out)
    for argv in fixes:
        if argv[:1] == ["git"]:
            _harness.git(repo, *argv[1:])
    code, out2 = _resolve(["resolve", idx, "--renumber", "theirs"])
    check("rw7b ...and the command it names for a STAGED stray is true: it puts the "
          "file back as git's merge left it, index and work tree, and resolve then "
          "completes with the undisturbed bytes: %r | %s" % (fixes, out2),
          len(fixes) == 1 and fixes[0][:2] == ["git", "restore"]
          and code == 0 and _plan_bytes(repo) == clean)

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
