#!/usr/bin/env python3
"""
The cases for `stamp-verification.py` — the door, not the arithmetic.

`test__tree_stamp.py` proves the identity fields and the three-word comparison
against a real repository, one moved thing at a time. What is left for the door is
everything a caller can get wrong, and everything the exit code promises.

- **Three answers need three exit codes.** `unestablished` sharing 0 makes an
  ungradeable comparison read as "unchanged", which is the false clean sheet the
  whole design refuses; sharing 1 makes it read as "the tree moved" and sends a
  reader to re-run work that may be perfectly current. `sv5` reads the map off the
  module's own verdict words, so a fourth verdict cannot be added without a code.
- **A stamp that cannot be READ is not a stamp that matched.** Every refusal here
  exits 2, and `sv13` is the case that asserts the one thing that must never
  happen: an unreadable stamp coming back 0.
- **The scope rides inside the stamp.** `compare` refuses a `--files`/`--task` of
  its own, because a comparison handed a second file set silently answers about a
  different question — which is the held-model-of-state failure this command was
  built for, reappearing inside the tool meant to catch it.
- **`--task` reads the plan.** A hand-typed file list beside a manifest is the
  same failure one step earlier, so the door takes the declared scope off the task
  and `sv8` asserts both routes reach the same digest.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import hashlib
import importlib.util
import io
import json
import ntpath
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _tree_stamp                                 # noqa: E402
import _proc_group                                 # noqa: E402
import _worktrees as _wt                           # noqa: E402

M = _loader.load_script("stamp-verification.py", modname="stamp_verification")
M_PLUGIN = _output.PLUGIN_ROOT


def _git(repo, *args):
    """A git command that must succeed, with the identity a fresh runner lacks."""
    subprocess.run(["git", "-C", repo,
                    "-c", "user.email=fixture@example.invalid",
                    "-c", "user.name=fixture",
                    "-c", "commit.gpgsign=false"] + list(args),
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def _seeded_repo(prefix):
    """A committed fixture repository with its line endings pinned in the
    REPOSITORY's own config. The helper drops every GIT_* variable before it
    calls git, the sweep's GIT_CONFIG_NOSYSTEM with them, so without the pin its
    git reads a system config this suite's git never saw - Git for Windows ships
    one setting core.autocrlf - and the two disagree about the bytes a
    checkout writes."""
    root = _harness.fixture_root(prefix)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _git(root, "config", "core.autocrlf", "false")
    os.makedirs(os.path.join(root, "src"))
    _write(os.path.join(root, "src", "mine.py"), "v = 1\n")
    _git(root, "add", "src/mine.py")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _run(argv, stdin_text=None):
    """`(code, text)` from one invocation, stderr silenced the way `run()` does.

    The door writes its refusals to stderr, so a case that only collected stdout
    would grade a refusal by its exit code alone and could not tell one refusal
    from another."""
    lines = []
    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        code = M.main(argv, out=lines.append,
                      stdin=io.StringIO(stdin_text or ""))
        errs = sys.stderr.getvalue()
    finally:
        sys.stderr = held
    return code, "\n".join(lines) + errs


MANIFEST = {
    "meta": {"version": 3, "repo": "fixture", "title": "fixture",
             "createdISO": "2026-01-01T00:00:00Z", "developmentBranch": "main",
             "branchPrefix": "audit", "gitRoot": ".",
             "buildCommands": {"test": "true"}},
    "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                "tasks": [{"id": "P1.1", "title": "t", "status": "pending",
                           "files": ["src/mine.py"]},
                          {"id": "P1.2", "title": "u", "status": "pending",
                           "files": []}]}]}


# --- take: the stamp, and where its scope comes from --------------------------
def _take_cases(check):
    repo = _seeded_repo("stamp-door-take-")
    code, text = _run(["take", "--project", repo, "--files", "src/mine.py"])
    check("sv1 `take` exits 0 and prints the one line a report or a commit "
          "message carries - the token is the whole product, so a run that "
          "printed the fields and not the line would have produced nothing to "
          "carry: exit=%r" % (code,),
          code == 0 and _tree_stamp.STAMP_TOKEN in text)

    stamp, problem = _tree_stamp.parse_stamp(text)
    check("sv2 ...and what it printed parses back, which is the only property "
          "that makes the line worth printing: %r" % (problem,),
          problem is None and stamp.get("scope") == ["src/mine.py"])

    man_path = os.path.join(repo, "audit-plan.json")
    _write(man_path, json.dumps(MANIFEST))
    code_task, text_task = _run(["take", "--project", repo,
                                 "--manifest", man_path, "--task", "P1.1"])
    by_task, _p = _tree_stamp.parse_stamp(text_task)
    check("sv3 `--task` takes the declared scope OFF THE PLAN, and reaches the "
          "same digest a hand-typed list does. The hand-typed list is the held "
          "model of state this command is about, so the plan has to be a route: "
          "exit=%r" % (code_task,),
          code_task == 0
          and by_task.get("scope") == stamp.get("scope")
          and by_task.get("scopeDigest") == stamp.get("scopeDigest"))

    code_empty, text_empty = _run(["take", "--project", repo,
                                   "--manifest", man_path, "--task", "P1.2"])
    empty, _p2 = _tree_stamp.parse_stamp(text_empty)
    check("sv4 a task that declares NO files is a stamp with no scope digest and "
          "a sentence saying why - not an error, and not a digest over an empty "
          "list, which would compare equal across every such run and read as "
          "agreement: exit=%r" % (code_empty,),
          code_empty == 0 and empty.get("scope") == []
          and empty.get("scopeDigest") is None
          and "declares no files" in text_empty)

    both = _run(["take", "--project", repo, "--files", "src/mine.py",
                 "--manifest", man_path, "--task", "P1.1"])
    no_man = _run(["take", "--project", repo, "--task", "P1.1"])
    missing = _run(["take", "--project", repo, "--manifest", man_path,
                    "--task", "P9.9"])
    unread = _run(["take", "--project", repo, "--manifest",
                   os.path.join(repo, "nope.json"), "--task", "P1.1"])
    check("sv5 every way of naming the wrong work is a refusal with its own "
          "sentence and exit 2 - two scopes at once, a task with no manifest, a "
          "task that is not there (the message lists what is), and a manifest "
          "that will not read: %r"
          % ([c for c, _t in (both, no_man, missing, unread)],),
          [c for c, _t in (both, no_man, missing, unread)] == [2, 2, 2, 2]
          and "P1.1" in missing[1])


# --- compare: three answers, three exit codes ---------------------------------
def _compare_cases(check):
    repo = _seeded_repo("stamp-door-compare-")
    _code, taken = _run(["take", "--project", repo, "--files", "src/mine.py"])

    quiet_code, quiet_text = _run(["compare", "--project", repo], stdin_text=taken)
    check("sv6 THE ALLOW CASE: an untouched tree is `current` and exits 0, read "
          "off STDIN because a commit message or a report is what a caller "
          "already has in hand. A stamp that cried stale here would be ignored "
          "within a day: exit=%r" % (quiet_code,),
          quiet_code == 0 and _tree_stamp.CURRENT in quiet_text)

    _write(os.path.join(repo, "src", "mine.py"), "v = 2\n")
    stale_code, stale_text = _run(["compare", "--project", repo,
                                   "--stamp", taken])
    check("sv7 an edited tree is `stale`, exits 1, and NAMES the field that "
          "moved. 'Stale' with no cause sends the reader back to re-run "
          "everything: exit=%r" % (stale_code,),
          stale_code == M.E_STALE and _tree_stamp.STALE in stale_text
          and "scopeDigest" in stale_text)

    plain = _harness.fixture_root("stamp-door-nogit-")
    _dead_code, dead = _run(["take", "--project", plain])
    dead_code, dead_text = _run(["compare", "--project", plain], stdin_text=dead)
    check("sv8 THE THIRD ANSWER: a directory git cannot describe is "
          "`unestablished` on its OWN exit code, neither 0 nor 1. Sharing 0 "
          "would make an ungradeable comparison read as unchanged; sharing 1 "
          "would send a reader to re-run work that may be current: exit=%r"
          % (dead_code,),
          dead_code == M.E_UNESTABLISHED
          and _tree_stamp.UNESTABLISHED in dead_text
          and _tree_stamp.CURRENT not in dead_text.splitlines()[0])

    check("sv9 the three codes really are three, and every verdict the module "
          "declares has one - read off `_tree_stamp`'s own words, so a fourth "
          "verdict cannot be added and left sharing a neighbour's code: %r"
          % (M.EXIT_FOR,),
          set(M.EXIT_FOR) == set(_tree_stamp.VERDICT_HELP)
          and len(set(M.EXIT_FOR.values())) == len(M.EXIT_FOR)
          and M.EXIT_FOR[_tree_stamp.CURRENT] == 0)

    scoped = _run(["compare", "--project", repo, "--files", "src/mine.py"],
                  stdin_text=taken)
    tasked = _run(["compare", "--project", repo, "--task", "P1.1"],
                  stdin_text=taken)
    check("sv10 `compare` refuses a scope of its own. The scope rides inside the "
          "stamp, and a second one here would let the comparison answer about a "
          "different file set than the stamp was taken over - this command's own "
          "defect, reappearing inside it: %r"
          % ([c for c, _t in (scoped, tasked)],),
          [c for c, _t in (scoped, tasked)] == [2, 2])

    both_sources = _run(["compare", "--project", repo, "--stamp", taken,
                         "--stamp-file", os.path.join(repo, "nope.txt")])
    no_file = _run(["compare", "--project", repo, "--stamp-file",
                    os.path.join(repo, "nope.txt")])
    garbage = _run(["compare", "--project", repo], stdin_text="gates are green\n")
    check("sv13 A STAMP THAT CANNOT BE READ IS NOT A STAMP THAT MATCHED. Two "
          "sources, a file that is not there, and a document carrying no token "
          "all exit 2 - never 0, which is the one answer that would let the "
          "claim go on being cited: %r"
          % ([c for c, _t in (both_sources, no_file, garbage)],),
          [c for c, _t in (both_sources, no_file, garbage)] == [2, 2, 2])


# --- the content field at the door: the recorder's own writes left out --------
def _recorder_cases(check):
    repo = _seeded_repo("stamp-door-recorder-")
    man_path = os.path.join(repo, "audit-plan.json")
    other = os.path.join(repo, "other.txt")
    _write(man_path, json.dumps(MANIFEST))
    _write(other, "a sibling's in-flight edit\n")
    code, text = _run(["take", "--project", repo, "--manifest", man_path,
                       "--task", "P1.1"])
    stamp, problem = _tree_stamp.parse_stamp(text)
    line = _tree_stamp.format_stamp(stamp) if stamp else ""
    # The orchestrator's own bookkeeping, between the stamp and the compare.
    _write(man_path, json.dumps(MANIFEST, indent=1))
    kept_code, kept_text = _run(["compare", "--project", repo],
                                stdin_text=line)
    check("sv16 THE ALLOW CASE FOR THE CONTENT FIELD: a write to the plan the "
          "stamp names, after the stamp, still compares `current`. The stamp "
          "stores the manifest project-relative and `compare` derives the "
          "recorder's paths from it again; left in, every stamp would go stale "
          "on the orchestrator's next manifest write: take=%r problem=%r "
          "manifest=%r compare=%r"
          % (code, problem, (stamp or {}).get("manifest"), kept_code),
          code == 0 and problem is None
          and (stamp or {}).get("manifest") == "audit-plan.json"
          and kept_code == 0 and _tree_stamp.CURRENT in kept_text)

    _write(other, "the sibling rewrote it\n")
    moved_code, moved_text = _run(["compare", "--project", repo],
                                  stdin_text=line)
    check("sv17 ...and a rewrite of the undeclared dirty file beside it is "
          "`stale`, exit 1, with that path named once - the door reaches the "
          "same content field the module grades: exit=%r named=%r"
          % (moved_code, moved_text.count("moved: other.txt")),
          moved_code == M.E_STALE
          and moved_text.count("moved: other.txt") == 1)


# --- the machine-readable half and the command's own shape --------------------
def _shape_cases(check):
    repo = _seeded_repo("stamp-door-json-")
    code, text = _run(["take", "--project", repo, "--files", "src/mine.py",
                       "--json"])
    payload = json.loads(text)
    check("sv11 `take --json` carries the stamp, the full basis for every field, "
          "and the line to paste - a caller that got only the digests would have "
          "to re-derive the sentence that bounds them: exit=%r" % (code,),
          code == 0 and set(payload) == set(("stamp", "state", "line"))
          and payload["line"].startswith(_tree_stamp.STAMP_TOKEN)
          and all(payload["state"].get(key)
                  for _f, key, _l in _tree_stamp.FIELD_LIMIT))

    _cmp_code, cmp_text = _run(["compare", "--project", repo, "--json"],
                               stdin_text=payload["line"])
    verdict = json.loads(cmp_text)
    check("sv12 `compare --json` carries the verdict AND the per-field words it "
          "was assembled from, so a caller can act on which part moved rather "
          "than on the one word: %r" % (verdict["verdict"],),
          verdict["verdict"] == _tree_stamp.CURRENT
          and [e["field"] for e in verdict["fields"]]
          == list(_tree_stamp.IDENTITY_FIELDS))

    bad_verb = _run(["stamp"])
    check("sv14 a verb this command does not have is a usage error and not a "
          "silent default - guessing which of two actions was meant is the "
          "guess this whole command exists to stop: %r" % (bad_verb[0],),
          bad_verb[0] == M.E_USAGE)

    coverage = _output.selftest_coverage()
    mine = ["scripts/governance/stamp-verification.py",
            "scripts/governance/_tree_stamp.py"]
    check("sv15 both new files are classified `covered` - a suite in tests/ and "
          "no inline one. Asked of `selftest_coverage()` rather than of the "
          "source text, because the classifier reads STRING LITERALS and a file "
          "explaining the rule in a comment would fail a grep while being "
          "perfectly compliant: %r"
          % ([name for name in mine if name not in coverage["covered"]],),
          all(name in coverage["covered"] for name in mine)
          and not [d for d in coverage["defects"] if any(n in d for n in mine)])


# --- red: a red-first proof in a throwaway tree, never in the shared one -------
# The test file a fixture task declares. It prints the house tally so the helper
# reads a count of collected cases; the literal is BUILT, because the tally is the
# contract CI greps for and a spelled one in a fixture reads as a suite of its own.
_TALLY = "%s: %d/%d cases " + "passed"
_PATH_LINE = ("sys.path.insert(0, os.path.join(os.path.dirname("
              "os.path.abspath(__file__)), '..', 'src'))")


def _house_test(imports, cases):
    """A house-style suite: one PASS/FAIL line per `(label, cond)` and the tally."""
    body = ["import os, sys", _PATH_LINE, imports, "results = []"]
    for label, cond in cases:
        body += ["ok = bool(%s)" % (cond,), "results.append(ok)",
                 "print('%%s %s' %% ('PASS' if ok else 'FAIL'))" % (label,)]
    body += ["n = sum(results)",
             "print(%r %% ('ALL PASS' if n == len(results) else 'SELFTEST FAILED',"
             " n, len(results)))" % (_TALLY,),
             "sys.exit(0 if n == len(results) else 1)"]
    return "\n".join(body) + "\n"


def _red_test(imports, cond, label="new1"):
    """A suite keeping HEAD's case `old1` beside the task's `label` - a red is
    measured against HEAD's own run, which refuses a comparison in which a
    case HEAD ran is gone."""
    if label == "old1":
        return _house_test(imports, [(label, cond)])
    return _house_test(imports, [("old1", "True"), (label, cond)])


def _red_repo(prefix, wt_test, extra=None, files=None, head_test=None):
    """A repository whose HEAD holds `v = 1` and a passing test (`head_test`, or
    one case `old1`), and whose working tree holds the fix (`v = 2`), `wt_test` as
    the task's new test, an untracked sibling file, and a manifest declaring the
    task."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    _write(os.path.join(root, "tests", "test_mine.py"),
           head_test or _red_test("import mine", "mine.v >= 1", label="old1"))
    _git(root, "add", "tests/test_mine.py")
    _git(root, "commit", "-q", "-m", "test")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    _write(os.path.join(root, "tests", "test_mine.py"), wt_test)
    _write(os.path.join(root, "notes.txt"), "a sibling's uncommitted work\n")
    for rel, text in (extra or {}).items():
        _write(os.path.join(root, *rel.split("/")), text)
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = files or ["src/mine.py", "tests/test_mine.py"]
    task["tests"] = {"mode": "tdd", "add": ["tests/test_mine.py: v is two"]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    return root, man


def _snapshot(root):
    """Every byte of the working tree outside `.git`, plus what git says about it."""
    files = {}
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            path = os.path.join(base, name)
            with open(path, "rb") as fh:
                files[os.path.relpath(path, root)] = hashlib.sha256(
                    fh.read()).hexdigest()
    status = subprocess.run(["git", "-C", root, "status", "--porcelain", "-uall"],
                            stdout=subprocess.PIPE, universal_newlines=True).stdout
    return files, status, _worktrees(root)


def _worktrees(root):
    return subprocess.run(["git", "-C", root, "worktree", "list", "--porcelain"],
                          stdout=subprocess.PIPE, universal_newlines=True).stdout


def _lists(root, path):
    """Whether git's worktree list names `path`, compared as a path. git prints
    its own spelling - forward slashes and long names on Windows - so a
    substring test of a native path against the listing answers "absent" for a
    tree git lists, and an `x not in listing` assertion passes for nothing."""
    return any(_wt.same_tree(rec["path"], path)
               for rec in _wt.parse_list(_worktrees(root)))


def _sh_word(path):
    """`path` as one word of an `sh -c` script: quoted, so a space does not split
    it, and forward-slashed, so the POSIX shell Git for Windows runs does not
    read a backslash as an escape."""
    return shlex.quote(path.replace("\\", "/"))


def _red(root, man, cmd, *extra):
    code, text = _run(["red", "--project", root, "--manifest", man,
                       "--task", "P1.1", "--json"] + list(extra) + ["--"] + cmd)
    try:
        return code, json.loads(text)
    except ValueError:
        return code, {"unparsed": text}


def _red_cases(check):
    py = sys.executable
    root, man = _red_repo("stamp-red-", _red_test("import mine", "mine.v == 2"))
    shared = subprocess.run([py, "tests/test_mine.py"], cwd=root,
                            stdout=subprocess.DEVNULL).returncode
    before = _snapshot(root)
    code, got = _red(root, man, [py, "tests/test_mine.py"])
    after = _snapshot(root)
    block = got.get("redFirst") or {}
    check("sr1 a test that fails on HEAD's implementation is `proved`, in the "
          "shape the executor's return already carries - status, basis, at - "
          "and the basis names the command, its exit and the tally it read. The "
          "same test PASSES in the shared tree (exit %r there), so a helper that "
          "ran it there would come back green: exit=%r %r"
          % (shared, code, block),
          shared == 0 and code == M.E_PROVED and got.get("verdict") == "red"
          and block.get("status") == "proved"
          and set(block) == set(("status", "basis", "at"))
          and "tests/test_mine.py" in block.get("basis", "")
          and "exited 1" in block.get("basis", "")
          and "SELFTEST FAILED" in block.get("basis", ""))
    check("sr2 the SHARED tree is byte-identical after the run - every file "
          "outside `.git`, the untracked sibling included, git's own status, and "
          "the worktree list: %r"
          % (sorted(set(before[0].items()) ^ set(after[0].items())),),
          before == after and "notes.txt" in after[0])
    tw = got.get("throwaway") or {}
    check("sr3 the throwaway tree is REMOVED, and that is proved rather than "
          "assumed: the path it names is gone from disk and from git's worktree "
          "list: %r" % (tw,),
          tw.get("path") and tw.get("removed") is True
          and not os.path.exists(tw["path"])
          and not _lists(root, tw["path"]))
    check("sr4 the throwaway held HEAD's implementation and the working tree's "
          "test, split on what the task declares, and says which was which: %r"
          % ((got.get("atHead"), got.get("copied")),),
          got.get("atHead") == ["src/mine.py"]
          and got.get("copied") == ["tests/test_mine.py"]
          and len(str(tw.get("head") or "")) >= 7)

    root_g, man_g = _red_repo("stamp-red-green-",
                              _red_test("import mine", "mine.v >= 1"))
    code_g, got_g = _red(root_g, man_g, [py, "tests/test_mine.py"])
    check("sr5 a test that PASSES without the fix is not red: exit %r, no "
          "`redFirst` block to paste, and a sentence saying the test proves "
          "nothing yet - never a word the record would take as a proof: %r"
          % (M.E_NOT_RED, (code_g, got_g.get("verdict"), got_g.get("redFirst"))),
          code_g == M.E_NOT_RED and got_g.get("verdict") == "green"
          and got_g.get("redFirst") is None and got_g.get("note")
          and (got_g.get("throwaway") or {}).get("removed") is True)

    new_files = ["src/mine.py", "src/newmod.py", "tests/test_mine.py"]
    root_c, man_c = _red_repo(
        "stamp-red-collect-",
        _red_test("from newmod import helper_fn", "helper_fn() == 2"),
        extra={"src/newmod.py": "def helper_fn():\n    return 2\n"},
        files=new_files)
    code_c, got_c = _red(root_c, man_c, [py, "tests/test_mine.py"])
    block_c = got_c.get("redFirst") or {}
    check("sr6 a compile or collection error - here the module the test imports "
          "does not exist at HEAD, and no case ran - is `could-not-prove`, not "
          "`proved`: exit=%r %r" % (code_c, block_c),
          code_c == M.E_CANNOT_PROVE
          and got_c.get("verdict") == "collection-error"
          and block_c.get("status") == "could-not-prove"
          and "no test" in block_c.get("basis", ""))
    root_x, man_x = _red_repo(
        "stamp-red-introduces-redhead-",
        _red_test("from newmod import helper_fn", "helper_fn() == 2"),
        extra={"src/newmod.py": "def helper_fn():\n    return 2\n"},
        files=new_files,
        head_test=_house_test("import mine", [("old1", "mine.v == 5")]))
    code_x, got_x = _red(root_x, man_x, [py, "tests/test_mine.py"],
                         "--introduces", "newmod")
    check("sr141 --introduces requires the same green baseline: HEAD's own tests "
          "red on HEAD's code leave even an introduced symbol could-not-prove: "
          "exit=%r %r" % (code_x, (got_x.get("redFirst") or {}).get("basis", "")[:240]),
          code_x == M.E_CANNOT_PROVE
          and "narrow" in (got_x.get("redFirst") or {}).get("basis", ""))
    code_i, got_i = _red(root_c, man_c, [py, "tests/test_mine.py"],
                         "--introduces", "newmod")
    block_i = got_i.get("redFirst") or {}
    check("sr7 ...unless the task INTRODUCES the symbol: named by --introduces, "
          "absent from every declared implementation file at HEAD, present in the "
          "working tree's copy, and named by the run's own output. Then the "
          "error is the absence the test asserts, and it is `proved` with those "
          "three observations as its basis: exit=%r %r" % (code_i, block_i),
          code_i == M.E_PROVED and block_i.get("status") == "proved"
          and "introduces" in block_i.get("basis", "")
          and "src/newmod.py" in block_i.get("basis", ""))
    code_h, got_h = _red(root_c, man_c, [py, "tests/test_mine.py"],
                         "--introduces", "mine")
    check("sr8 ...and a symbol HEAD already has is not introduced by this task, "
          "whatever the flag says, so the error stays `could-not-prove` and the "
          "basis says where HEAD carries it: exit=%r %r"
          % (code_h, got_h.get("redFirst")),
          code_h == M.E_CANNOT_PROVE
          and (got_h.get("redFirst") or {}).get("status") == "could-not-prove"
          and "src/mine.py" in (got_h.get("redFirst") or {}).get("basis", ""))

    code_t, got_t = _red(root, man, [py, "-c", "import time; time.sleep(30)"],
                         "--timeout", "1")
    code_n, got_n = _red(root, man, ["no-such-binary-for-a-red-run"])
    check("sr9 a run that times out, and a command that cannot start, are "
          "`could-not-prove` with the reason as basis - and the throwaway is "
          "removed on both paths, because the removal sits in a `finally`: %r"
          % ([(c, (g.get("redFirst") or {}).get("status"),
               (g.get("throwaway") or {}).get("removed"))
              for c, g in ((code_t, got_t), (code_n, got_n))],),
          all(c == M.E_CANNOT_PROVE
              and (g.get("redFirst") or {}).get("status") == "could-not-prove"
              and (g.get("throwaway") or {}).get("removed") is True
              and not os.path.exists((g.get("throwaway") or {}).get("path") or "")
              for c, g in ((code_t, got_t), (code_n, got_n)))
          and "timed out" in got_t["redFirst"]["basis"])

    held = _worktrees(root)
    code_s, _t = _run(["red", "--project", root, "--manifest", man, "--task",
                       "P1.1", "--", py, os.path.join(root, "tests",
                                                      "test_mine.py")])
    check("sr10 a command that names the SHARED tree by path is refused before "
          "anything is built - it would run the shared files and grade the fix, "
          "not HEAD: exit=%r" % (code_s,),
          code_s == M.E_USAGE and _worktrees(root) == held)

    no_cmd = _run(["red", "--project", root, "--manifest", man, "--task", "P1.1"])
    take_cmd = _run(["take", "--project", root, "--", py])
    no_task = _run(["red", "--project", root, "--", py, "tests/test_mine.py"])
    root_x, man_x = _red_repo("stamp-red-notest-",
                              _red_test("import mine", "mine.v == 2"),
                              files=["src/mine.py"])
    no_tests = _run(["red", "--project", root_x, "--manifest", man_x, "--task",
                     "P1.1", "--", py, "tests/test_mine.py"])
    check("sr11 every way of asking for a red that cannot be graded is a usage "
          "error: no command, a command given to `take`, no task, and a task "
          "declaring no test file - a throwaway holding only HEAD would prove "
          "nothing about this task's test: %r"
          % ([c for c, _t2 in (no_cmd, take_cmd, no_task, no_tests)],),
          [c for c, _t2 in (no_cmd, take_cmd, no_task, no_tests)]
          == [M.E_USAGE] * 4
          and "test file" in no_tests[1])

    script = os.path.join(M_PLUGIN, "scripts", "governance",
                          "stamp-verification.py")
    as_cmd = subprocess.run([py, script, "red", "--project", root, "--manifest",
                             man, "--task", "P1.1", "--json", "--", py,
                             "tests/test_mine.py", "--selftest"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
    check("sr15 a test command carrying `--selftest` after `--` is the RED RUN'S "
          "flag, not this command's: run as a command, the helper still builds "
          "the throwaway and proves the red rather than answering its own "
          "migrated-suite notice with exit 0: exit=%r %r"
          % (as_cmd.returncode, as_cmd.stdout[:160]),
          as_cmd.returncode == M.E_PROVED and '"verdict": "red"' in as_cmd.stdout)

    with open(os.path.join(M_PLUGIN, "schema", "audit-plan.schema.json"),
              "r", encoding="utf-8") as fh:
        enum = (json.load(fh)["$defs"]["redFirst"]["properties"]["status"]
                ["enum"])
    check("sr12 every word the helper writes is a word the schema declares - the "
          "enum is the one source, and a helper printing a word the record "
          "refuses would hand the executor an unrecordable block: %r"
          % (sorted(M.RED_WORDS),),
          set(M.RED_WORDS) <= set(enum) and M.RED_WORDS)


def _tally_cases(check):
    def house(body):
        held = sys.stdout
        sys.stdout = io.StringIO()
        held_err = sys.stderr
        sys.stderr = io.StringIO()
        try:
            code = _harness.run(body)
            return code, sys.stdout.getvalue()
        finally:
            sys.stdout = held
            sys.stderr = held_err

    def failing(chk):
        chk("x1 asserts", False)

    def escaping(chk):
        _harness.stage(chk, "x-build", lambda c: {}["missing"])

    shapes = [
        ("house assertion", house(failing)),
        ("house escape", house(escaping)),
        ("pytest failed", (1, "FAILED t.py::test_x - assert 1 == 2\n"
                                  "===== 1 failed, 2 passed in 0.12s =====\n")),
        ("pytest error", (2, "=== 1 error in 0.30s ===\n")),
        ("pytest none", (5, "collected 0 items\n\n=== no tests ran in 0.01s ===\n")),
        ("unittest failure", (1, "Ran 3 tests in 0.001s\n\nFAILED (failures=1)\n")),
        ("unittest error", (1, "Ran 1 test in 0.001s\n\nFAILED (errors=1)\n")),
        ("bare traceback", (1, "Traceback (most recent call last):\n"
                               "ModuleNotFoundError: No module named 'x'\n")),
        ("no tally", (1, "the runner stopped\n")),
    ]
    got = dict((name, M.classify_run(code, text)[0]) for name, (code, text) in shapes)
    want = {"house assertion": "red", "house escape": "collection-error",
            "pytest failed": "red", "pytest error": "collection-error",
            "pytest none": "collection-error", "unittest failure": "red",
            "unittest error": "collection-error",
            "bare traceback": "collection-error", "no tally": "no-tally"}
    check("sr13 the verdict reads a TALLY, and `red` needs at least one test "
          "collected and an assertion failing: a house suite whose only failure "
          "is a block that raised while being built, a pytest error with nothing "
          "failed, zero collected and a bare traceback are none of them red. The "
          "house shapes come from the real harness, so the helper cannot drift "
          "from what a suite actually prints: %r"
          % (dict((k, v) for k, v in got.items() if want[k] != v),),
          got == want)
    check("sr14 THE ALLOW CASE for sr13: a green run is `green` whatever it "
          "prints - exit 0 is never read as a red by a tally that happens to "
          "contain the word failed: %r"
          % (M.classify_run(0, "== 0 failed, 3 passed in 0.1s ==\n")[0],),
          M.classify_run(0, "== 0 failed, 3 passed in 0.1s ==\n")[0] == "green")


# --- the review's findings, each as the case that went red --------------------
# Real pytest output, captured from `pytest -q` and `pytest` over one file holding
# a passing test, an assertion and a body TypeError - a hand-written shape is the
# parser's own assumption, so the shapes come from the runner.
_PYTEST_Q = (
    "..F.F\n"
    "=========================== short test summary info ============================\n"
    "FAILED test_a.py::test_assert - assert 1 == 2\n"
    "FAILED test_a.py::test_type - TypeError: unsupported operand type(s) for +: '...\n"
    "2 failed, 1 passed in 0.01s\n")
_PYTEST_FULL = _PYTEST_Q.replace(
    "2 failed, 1 passed in 0.01s\n",
    "========================= 2 failed, 1 passed in 0.01s ==========================\n")
_PYTEST_TYPE_ONLY = (
    "=========================== short test summary info ============================\n"
    "FAILED test_a.py::test_type - TypeError: unsupported operand type(s) for +: '...\n"
    "1 failed in 0.01s\n")


def _introduces_cases(check):
    py = sys.executable
    files = ["src/mine.py", "src/newmod.py", "tests/test_mine.py"]
    newmod = {"src/newmod.py": "def helper_fn():\n    return 2\n"}
    root, man = _red_repo(
        "stamp-red-syntax-",
        _red_test("from newmod import helper_fn", "helper_fn() == 2 )"),
        extra=newmod, files=files)
    code, got = _red(root, man, [py, "tests/test_mine.py"],
                     "--introduces", "helper_fn")
    block = got.get("redFirst") or {}
    check("sr16 a test broken by a SyntaxError WITH the fix present is not a "
          "proved red under --introduces: the error is the test's, it survives "
          "the fix, and syntax errors never qualify: exit=%r %r" % (code, block),
          code != M.E_PROVED and block.get("status") != "proved")

    root_i, man_i = _red_repo(
        "stamp-red-intro-",
        _red_test("from newmod import helper_fn", "helper_fn() == 2"),
        extra=newmod, files=files)
    empty = _run(["red", "--project", root_i, "--manifest", man_i, "--task",
                  "P1.1", "--introduces", "", "--", py, "tests/test_mine.py"])
    dotted = _run(["red", "--project", root_i, "--manifest", man_i, "--task",
                   "P1.1", "--introduces", "new mod", "--", py,
                   "tests/test_mine.py"])
    check("sr17 a symbol that is not identifier-shaped is refused before anything "
          "runs - the empty string is a substring of every output: %r"
          % ([empty[0], dotted[0]],),
          [empty[0], dotted[0]] == [M.E_USAGE, M.E_USAGE])
    code_s, got_s = _red(root_i, man_i, [py, "tests/test_mine.py"],
                         "--introduces", "newm")
    code_o, got_o = _red(root_i, man_i, [py, "tests/test_mine.py"],
                         "--introduces", "helper_fn")
    check("sr18 the final error must name THE symbol, whole, as the runtime "
          "quotes it: a substring of the missing name is not it, and neither is "
          "another symbol the task adds when the error names its module: "
          "exit=%r/%r %r"
          % (code_s, code_o, (got_o.get("redFirst") or {}).get("basis", "")[-120:]),
          [code_s, code_o] == [M.E_CANNOT_PROVE, M.E_CANNOT_PROVE]
          and (got_s.get("redFirst") or {}).get("status") == "could-not-prove"
          and (got_o.get("redFirst") or {}).get("status") == "could-not-prove")
    code_p, got_p = _red(root_i, man_i, [py, "tests/test_mine.py"],
                         "--introduces", "newmod")
    basis = (got_p.get("redFirst") or {}).get("basis", "")
    check("sr19 ...and the qualifying case is decided by a SECOND run with the "
          "working tree's implementation copied in, in which the error is gone - "
          "the basis says both runs: exit=%r %r" % (code_p, basis),
          code_p == M.E_PROVED and "second run" in basis
          and "ModuleNotFoundError" in basis)

    root_k, man_k = _red_repo(
        "stamp-red-stays-",
        _red_test("from newmod import helper_fn\nimport nothere_mod",
                  "helper_fn() == 2"),
        extra=newmod, files=files)
    code_k, got_k = _red(root_k, man_k, [py, "tests/test_mine.py"],
                         "--introduces", "newmod")
    check("sr20 an import error that the fix does NOT remove is not the task's: "
          "with the working tree's implementation copied in the run still fails "
          "to import, so it stays could-not-prove: exit=%r %r"
          % (code_k, (got_k.get("redFirst") or {}).get("basis", "")[-160:]),
          code_k == M.E_CANNOT_PROVE)


def _process_cases(check):
    py = sys.executable
    root, man = _red_repo("stamp-red-proc-", _red_test("import mine", "mine.v == 2"))
    check("sr21 the default timeout stays under the host's Bash limit, so the "
          "helper's own timeout fires - and its `finally` runs - before the host "
          "kills it: %r < %r" % (M.DEFAULT_TIMEOUT, M.HOST_BASH_LIMIT),
          M.DEFAULT_TIMEOUT < M.HOST_BASH_LIMIT)

    marks = _harness.fixture_root("stamp-red-marks-")
    late = os.path.join(marks, "grandchild-wrote")
    began = os.path.join(marks, "grandchild-began")
    inner = ("import time; open(%r, 'w').close(); time.sleep(5); "
             "open(%r, 'w').close()" % (began, late))
    spawn = ("import subprocess, sys, time\n"
             "subprocess.Popen([sys.executable, '-c', %r])\n"
             "time.sleep(30)\n" % (inner,))
    code_t, got_t = _red(root, man, [py, "-c", spawn], "--timeout", "3")
    time.sleep(6)
    check("sr22 a timeout kills the run's whole process GROUP: a grandchild the "
          "test runner started - seen running - does not outlive the throwaway "
          "and write after it: exit=%r began=%r wrote=%r"
          % (code_t, os.path.exists(began), os.path.exists(late)),
          code_t == M.E_CANNOT_PROVE and os.path.exists(began)
          and not os.path.exists(late)
          and (got_t.get("throwaway") or {}).get("removed") is True)

    script = os.path.join(_output.PLUGIN_ROOT, "scripts", "governance",
                          "stamp-verification.py")
    if not hasattr(signal, "SIGTERM") or os.name == "nt":
        _harness.skip(check, "sr23 SIGTERM removes the throwaway", "posix",
                      "no POSIX SIGTERM delivery on this platform")
    else:
        started = os.path.join(marks, "started")
        wait = ("import time\nopen(%r, 'w').close()\ntime.sleep(60)\n" % (started,))
        proc = subprocess.Popen([py, script, "red", "--project", root, "--manifest",
                                 man, "--task", "P1.1", "--json", "--", py, "-c",
                                 wait], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True)
        for _i in range(200):
            if os.path.exists(started):
                break
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        out, _e = proc.communicate(timeout=60)
        left = [ln for ln in _worktrees(root).splitlines()
                if ln.startswith("worktree ") and M.THROWAWAY_PREFIX in ln]
        check("sr23 SIGTERM mid-run still removes the throwaway: the signal is "
              "turned into an exception, so the `finally` runs, and nothing is "
              "left in git's worktree list: exit=%r left=%r %r"
              % (proc.returncode, left, out[-200:]),
              os.path.exists(started) and left == []
              and proc.returncode == M.E_CANNOT_PROVE)

    leftover = os.path.join(_harness.fixture_root("stamp-red-left-"),
                            M.THROWAWAY_PREFIX + "stale", "tree")
    _git(root, "worktree", "add", "--detach", "--quiet", leftover, "HEAD")
    code_l, got_l = _red(root, man, [py, "tests/test_mine.py"])
    check("sr24 a throwaway an earlier run could not remove (SIGKILL cannot be "
          "caught) is REPORTED by name, and never pruned - it may be another "
          "run's, still going: %r" % (got_l.get("leftovers"),),
          [_wt.same_tree(x["path"], leftover)
           for x in got_l.get("leftovers") or []] == [True]
          and _lists(root, leftover)
          and code_l == M.E_PROVED)
    _git(root, "worktree", "remove", "--force", leftover)

    # A leftover is LEFT BEHIND only when no live process holds it: a sibling's
    # `red` running now registers a throwaway exactly like one SIGKILL stranded.
    states = {}
    for label, pid in (("dead", 2 ** 22 + 12345), ("live", os.getpid())):
        holder = os.path.join(_harness.fixture_root("stamp-red-held-"),
                              M.THROWAWAY_PREFIX + label)
        tree = os.path.join(holder, "tree")
        _git(root, "worktree", "add", "--detach", "--quiet", tree, "HEAD")
        with open(os.path.join(holder, M.OWNER_FILE), "w", encoding="utf-8") as fh:
            json.dump({"pid": pid}, fh)
        states[label] = tree
    _code_h, got_h = _red(root, man, [py, "tests/test_mine.py"])
    by = dict((os.path.realpath(x["path"]), x["state"])
              for x in got_h.get("leftovers") or [])
    check("sr31 a registered throwaway whose owning process is gone is `left "
          "behind`; one whose owner is alive is `running`, never called left "
          "behind: %r" % (by,),
          by.get(os.path.realpath(states["dead"])) == "left-behind"
          and by.get(os.path.realpath(states["live"])) == "running")
    for tree in states.values():
        _git(root, "worktree", "remove", "--force", tree)


def _own_case_cases(check):
    py = sys.executable
    two = _house_test("import mine", [("old1", "mine.v == 2"), ("new1", "True")])
    root, man = _red_repo("stamp-red-own-", two)
    code, got = _red(root, man, [py, "tests/test_mine.py"])
    said = json.dumps(got.get("redFirst") or got.get("note"))
    check("sr25 an EXISTING case edited to fail, while the task's new case "
          "passes, proves: against a green baseline the red comes from the "
          "task's own edit, and the basis names it: exit=%r %s" % (code, said[:240]),
          code == M.E_PROVED and "old1" in said)
    code_c, got_c = _red(root, man, [py, "tests/test_mine.py"], "--case", "zz9")
    check("sr26 --case names the task's own case, and a red whose failing cases "
          "do not include it is not proved: exit=%r" % (code_c,),
          code_c != M.E_PROVED)
    root_n, man_n = _red_repo("stamp-red-named-",
                              _red_test("import mine", "mine.v == 2"))
    code_n, got_n = _red(root_n, man_n, [py, "tests/test_mine.py"])
    check("sr27 a proved red NAMES the failing case it rests on: %r"
          % ((got_n.get("redFirst") or {}).get("basis"),),
          code_n == M.E_PROVED
          and "new1" in (got_n.get("redFirst") or {}).get("basis", ""))

    got = dict((name, M.classify_run(1, text)[0]) for name, text in (
        ("pytest -q", _PYTEST_Q), ("pytest", _PYTEST_FULL),
        ("pytest body TypeError", _PYTEST_TYPE_ONLY)))
    fails = M.failing_cases(_PYTEST_Q)
    check("sr28 pytest -q's unframed summary is a tally (it read as no-tally), a "
          "body TypeError is not an assertion failure, and each failing node is "
          "named with whether it asserted: %r %r" % (got, fails),
          got == {"pytest -q": "red", "pytest": "red",
                  "pytest body TypeError": "collection-error"}
          and [(f["id"], f["assertion"]) for f in fails]
          == [("test_assert", True), ("test_type", False)])


def _env_cases(check):
    py = sys.executable
    root, man = _red_repo("stamp-red-env-", _red_test("import mine", "mine.v >= 1"))
    mark = os.path.join(_harness.fixture_root("stamp-red-envmark-"), "env.json")
    probe = ("import json, os\njson.dump(sorted(os.environ), open(%r, 'w'))\n"
             % (mark,))
    # Values OUTSIDE the shared root for the named variables: they go because of
    # what they are - a redirection of git or of Python's import path - and not
    # because they happen to name the root.
    elsewhere = os.path.join(_harness.fixture_root("stamp-red-elsewhere-"), "x")
    planted = {"PYTHONPATH": elsewhere, "CLAUDE_PROJECT_DIR": root,
               "GIT_DIR": os.path.join(elsewhere, "git"), "GIT_WORK_TREE": elsewhere,
               "GIT_INDEX_FILE": os.path.join(elsewhere, "index")}
    held = dict((k, os.environ.get(k)) for k in planted)
    os.environ.update(planted)
    try:
        code, got = _red(root, man, [py, "-c", probe])
    finally:
        for k, v in held.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    seen = []
    if os.path.exists(mark):
        with open(mark, "r", encoding="utf-8") as fh:
            seen = [k for k in json.load(fh) if k in planted]
    check("sr29 the red run's environment is SCRUBBED of what reaches the shared "
          "tree - PYTHONPATH, CLAUDE_PROJECT_DIR and git's own GIT_DIR/"
          "GIT_WORK_TREE/GIT_INDEX_FILE, which also would have pointed the "
          "helper's own git elsewhere - and the output names what it dropped: "
          "exit=%r child saw %r dropped %r"
          % (code, seen, (got.get("environment") or {}).get("dropped")),
          code == M.E_NOT_RED and os.path.exists(mark) and seen == []
          and set(planted) <= set((got.get("environment") or {}).get("dropped")
                                  or []))
    check("sr30 ...and a green run says it passed IN THE THROWAWAY, which is what "
          "was observed, not that the test passes without the fix everywhere: %r"
          % (got.get("note"),),
          "in the throwaway" in (got.get("note") or ""))


# Captured from `pytest -q` over a test whose module imports a name the module
# under test does not define yet - pytest's collection-error shape.
_PYTEST_COLLECT = (
    "==================================== ERRORS ====================================\n"
    "__________________________ ERROR collecting test_b.py __________________________\n"
    "ImportError while importing test module '/tmp/x/test_b.py'.\n"
    "Hint: make sure your test modules/packages have valid Python names.\n"
    "Traceback:\n"
    "test_b.py:1: in <module>\n"
    "    from newmod import helper_fn\n"
    "E   ImportError: cannot import name 'helper_fn' from 'newmod' (/tmp/x/newmod.py)\n"
    "=========================== short test summary info ============================\n"
    "ERROR test_b.py\n"
    "!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
    "1 error in 0.04s\n")


def _final_pass_cases(check):
    py = sys.executable
    env = {"PATH": os.pathsep.join(["/repo/x/.venv/bin", "/usr/bin", "/bin"]),
           "TMPDIR": "/repo/x/.tmp", "PWD": "/repo/x", "SIBLING": "/repo/x-other/lib",
           "NOTE": "see /repo/x for details", "HOME": "/home/me",
           "PYTHONPATH": "/elsewhere"}
    kept, dropped, _naming = M.child_env("/repo/x", environ=env)
    check("sr32 the scrub is by PATH, not by substring: an in-root PATH entry is "
          "removed while PATH itself survives, a variable whose value IS a path "
          "under the root goes, a sibling directory that merely shares the "
          "prefix stays, and so does text that mentions the root: %r %r"
          % (kept, dropped),
          kept.get("PATH") == os.pathsep.join(["/usr/bin", "/bin"])
          and "TMPDIR" not in kept and "PWD" not in kept
          and kept.get("SIBLING") == "/repo/x-other/lib"
          and kept.get("NOTE") == "see /repo/x for details"
          and kept.get("HOME") == "/home/me" and "PYTHONPATH" not in kept
          and "PATH entry /repo/x/.venv/bin" in dropped)

    root, man = _red_repo("stamp-red-envbasis-", _red_test("import mine", "mine.v == 2"))
    held = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = root
    try:
        _c, got = _red(root, man, [py, "tests/test_mine.py"])
    finally:
        if held is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = held
    check("sr33 every redFirst basis names what the environment lost, so a proof "
          "made without a variable says so: %r"
          % ((got.get("redFirst") or {}).get("basis", "")[-160:],),
          "PYTHONPATH" in (got.get("redFirst") or {}).get("basis", "")
          .split("run without")[-1])

    err = M.final_error(_PYTEST_COLLECT)
    check("sr34 pytest's `E   ` prefix is read: the final error of a collection "
          "failure is the ImportError naming the symbol, so --introduces can "
          "reach its second run under pytest: %r" % (err,),
          err is not None and err[0] == "ImportError"
          and M.qualifying_error(_PYTEST_COLLECT, "helper_fn") is not None)
    attr = "Traceback (most recent call last):\nAttributeError: module 'newmod' has no attribute 'helper_fn'\n"
    check("sr35 ...and a bare AttributeError with no tally is a collection error, "
          "so it reaches the second run too, not no-tally: %r"
          % (M.classify_run(1, attr)[0],),
          M.classify_run(1, attr)[0] == M.V_COLLECT
          and M._wants_second(1, attr, ["helper_fn"]))

    two = _house_test("import mine", [("old1", "mine.v == 2"), ("new1", "True")])
    root_c, man_c = _red_repo("stamp-red-caseold-", two)
    code_c, got_c = _red(root_c, man_c, [py, "tests/test_mine.py"], "--case", "old1")
    code_p, got_p = _red(root_c, man_c, [py, "tests/test_mine.py"], "--case", "new1")
    check("sr36 --case must name a case that FAILED in the task's run: the edited "
          "old1 is one and proves, the passing new1 is not and is refused, "
          "whoever chooses the flag: exit=%r/%r %r"
          % (code_c, code_p, (got_p.get("redFirst") or {}).get("basis", "")[-160:]),
          code_c == M.E_PROVED and code_p == M.E_CANNOT_PROVE
          and "new1" in (got_p.get("redFirst") or {}).get("basis", ""))
    root_d, man_d = _red_repo("stamp-red-casenew-",
                              _red_test("import mine", "mine.v == 2"))
    code_d, got_d = _red(root_d, man_d, [py, "tests/test_mine.py"], "--case", "new1")
    check("sr37 ...and a proved basis says whether the case was NAMED by --case or "
          "derived: exit=%r %r" % (code_d, (got_d.get("redFirst") or {}).get("basis")),
          code_d == M.E_PROVED
          and "named by --case" in (got_d.get("redFirst") or {}).get("basis", ""))

    big = _run(["red", "--project", root_d, "--manifest", man_d, "--task", "P1.1",
                "--timeout", str(M.HOST_BASH_LIMIT), "--", py, "tests/test_mine.py"])
    check("sr38 a --timeout that would outlive the host's Bash limit is refused: "
          "the helper's own deadline has to fire first: exit=%r" % (big[0],),
          big[0] == M.E_USAGE)
    files = ["src/mine.py", "src/newmod.py", "tests/test_mine.py"]
    slow = _house_test("import time\ntime.sleep(3)\nfrom newmod import helper_fn",
                       [("new1", "helper_fn() == 2")])
    root_s, man_s = _red_repo("stamp-red-deadline-", slow,
                              extra={"src/newmod.py": "def helper_fn():\n    return 2\n"},
                              files=files)
    started = time.time()
    code_s, got_s = _red(root_s, man_s, [py, "tests/test_mine.py"],
                         "--introduces", "newmod", "--timeout", "7")
    spent = time.time() - started
    check("sr39 ONE deadline covers both runs: the second run gets what the first "
          "left, so a two-run proof cannot take twice the budget - here the "
          "second run is cut off and the proof is could-not-prove: exit=%r in "
          "%.1f s %r" % (code_s, spent,
                         (got_s.get("redFirst") or {}).get("basis", "")[-140:]),
          code_s == M.E_CANNOT_PROVE and spent < 7 + 3 * _proc_group.GRACE_SECONDS
          and "timed out" in (got_s.get("redFirst") or {}).get("basis", "")
          and (got_s.get("run") or {}).get("exit") == 1
          and (got_s.get("run") or {}).get("second") is not None)

    root_t, man_t = _red_repo("stamp-red-tmpdir-",
                              _red_test("import mine", "mine.v == 2"))
    inside = os.path.join(root_t, "untracked-tmp")
    os.makedirs(inside)
    held_tmp = tempfile.tempdir
    tempfile.tempdir = inside
    try:
        code_t, got_t = _red(root_t, man_t, [py, "tests/test_mine.py"])
    finally:
        tempfile.tempdir = held_tmp
    where = (got_t.get("throwaway") or {}).get("path") or ""
    check("sr40 a temp directory inside the shared tree is never where the "
          "throwaway goes - it would be a worktree siblings see in `git status`: "
          "%r (inside: %r)" % (where, os.listdir(inside)),
          where and not os.path.realpath(where).startswith(
              os.path.realpath(root_t) + os.sep)
          and os.listdir(inside) == [] and code_t == M.E_PROVED)


def _budget_cases(check):
    py = sys.executable
    check("sr41 the margin under the host's limit pays for ONE teardown (two waits "
          "and a drain) and the throwaway's removal (two git calls, each capped), "
          "so the largest accepted --timeout still leaves the host room: %r"
          % ((M.MAX_TIMEOUT, M.TEARDOWN_MARGIN, M.HOST_BASH_LIMIT),),
          M.MAX_TIMEOUT + M.TEARDOWN_MARGIN == M.HOST_BASH_LIMIT
          and M.TEARDOWN_MARGIN >= 3 * _proc_group.GRACE_SECONDS
          + 2 * M.REMOVE_GIT_TIMEOUT)
    root, man = _red_repo("stamp-red-budget-", _red_test("import mine", "mine.v == 2"))
    real = M._build_throwaway

    def slow_build(*args, **kwargs):
        time.sleep(2)
        return real(*args, **kwargs)
    M._build_throwaway = slow_build
    try:
        started = time.time()
        code, got = _red(root, man, [py, "-c", "import time; time.sleep(3)"],
                         "--timeout", "4")
        spent = time.time() - started
    finally:
        M._build_throwaway = real
    check("sr42 the FIRST run gets what the build left of the deadline, not a "
          "fresh full timeout - a slow build and a run that fits the timeout on "
          "its own still end inside it: exit=%r in %.1f s %r"
          % (code, spent, (got.get("redFirst") or {}).get("basis", "")[-120:]),
          code == M.E_CANNOT_PROVE
          and "timed out" in (got.get("redFirst") or {}).get("basis", "")
          and spent < 4 + 3 * _proc_group.GRACE_SECONDS + 2 * M.REMOVE_GIT_TIMEOUT)

    env = {"NODE_OPTIONS": "--require /repo/x/test/setup.js",
           "PYTEST_ADDOPTS": "--basetemp=/repo/x/.t -c /repo/x/pytest.ini",
           "NOTE": "see /repo/x for details", "PLAIN": "--flag value"}
    kept, dropped, naming = M.child_env("/repo/x", environ=env)
    check("sr43 an OPTION STRING carrying a path under the shared root is kept - "
          "it is not a path to rewrite - but NAMED, so a basis resting on a shared "
          "file says so; a value naming nothing under the root is not listed: "
          "%r %r" % (naming, dropped),
          naming == ["NODE_OPTIONS", "NOTE", "PYTEST_ADDOPTS"]
          and all(k in kept for k in env) and dropped == [])
    held = os.environ.get("NODE_OPTIONS")
    os.environ["NODE_OPTIONS"] = "--require %s" % (os.path.join(root, "setup.js"),)
    try:
        _c, got_n = _red(root, man, [py, "tests/test_mine.py"])
    finally:
        if held is None:
            os.environ.pop("NODE_OPTIONS", None)
        else:
            os.environ["NODE_OPTIONS"] = held
    check("sr44 ...and the redFirst basis carries it: %r"
          % ((got_n.get("redFirst") or {}).get("basis", "")[-160:],),
          "kept, naming the shared root: NODE_OPTIONS"
          in (got_n.get("redFirst") or {}).get("basis", ""))

    with open(os.path.join(M_PLUGIN, "reference", "execute-task.md"), "r",
              encoding="utf-8") as fh:
        ref = " ".join(fh.read().split())
    check("sr45 execute-task.md states the rule the helper enforces: a red counts "
          "only against a GREEN baseline of HEAD's own test files, a command "
          "already red at HEAD must be narrowed to the task's cases, and --case "
          "is held to that same test - not an alternative to it",
          "GREEN baseline" in ref and "narrow the command to the task's cases" in ref
          and "`--case` narrows" in ref and "held to that same test" in ref
          and "did not name" not in ref)


# --- a house case is its label; a runner's lines count only in its own output --
# A house label is usually a sentence, so its first word is an ordinary one that
# HEAD's test file carries too; and a passing house case may print an error line
# on purpose, because the case asserts on that message.
_OLD_LABEL = "the old value is at least one"
_NEW_LABEL = "the new value is two, as the fix sets it, read as 1"
_NEW_LABEL_SRC = ('("the new value is two, as the fix sets it, "\n'
                  '       "read as %r" % (mine.v,))')
_EXPECTED_ERRORS = ("print('ERROR: /tmp/nope is not a directory')",
                    "print('ERROR tests/data.json - the path is missing')")


def _label_suite(cases, extra=()):
    """A suite in the house harness's own shape: `check(label, cond, detail)`,
    the detail in parentheses on a FAIL line, and a label written as a literal
    that may wrap across source lines and interpolate a value."""
    body = ["import os, sys", _PATH_LINE, "import mine", "results = []",
            "def check(label, ok, detail=''):",
            "    results.append(bool(ok))",
            "    print('%s %s%s' % ('PASS' if ok else 'FAIL', label,",
            "          (' (%s)' % detail) if detail and not ok else ''))"]
    body += list(extra)
    for src, cond in cases:
        body.append("check(%s, %s, 'saw %%r' %% (mine.v,))" % (src, cond))
    body += ["n = sum(results)",
             "print(%r %% ('ALL PASS' if n == len(results) else 'SELFTEST FAILED',"
             " n, len(results)))" % (_TALLY,),
             "sys.exit(0 if n == len(results) else 1)"]
    return "\n".join(body) + "\n"


def _real_unittest():
    """`(code, text)` from a real `python -m unittest` over one assertion, one
    body exception and a test that prints a house-shaped line - captured from the
    runner, so the reader is not tested against its own assumption."""
    where = _harness.fixture_root("stamp-unittest-")
    _write(os.path.join(where, "test_u.py"), "\n".join([
        "import unittest", "", "", "class T(unittest.TestCase):",
        "    def test_assert(self):",
        "        print('FAIL printed by a test, not a case the house harness ran')",
        "        self.assertEqual(1, 2)", "",
        "    def test_pass(self):", "        pass", "",
        "    def test_raise(self):", "        raise TypeError('a body that raised')",
        ""]))
    proc = subprocess.run([sys.executable, "-m", "unittest", "test_u"], cwd=where,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
    return proc.returncode, proc.stdout


def _shape(cases):
    return [(c.get("id"), c.get("label"), c["assertion"]) for c in cases]


def _label_cases(check):
    py = sys.executable
    reported = ("FAIL the gate-economy row is wired: [1]\n"
                "ERROR: /tmp/nope is not a directory\n"
                + _TALLY % ("SELFTEST FAILED", 155, 156) + "\n")
    check("sr46 a house FAIL whose label is a sentence is named by its FULL "
          "label with no id - its first word is an ordinary one - and an "
          "`ERROR:` line in house output is not a unittest case: %r"
          % (_shape(M.failing_cases(reported)),),
          _shape(M.failing_cases(reported))
          == [(None, "the gate-economy row is wired: [1]", True)])
    led = ("FAIL me1 the value is read (saw 1)\nFAIL ga9b a suffix\n"
           "FAIL pc-sd0 a hyphen\n" + _TALLY % ("SELFTEST FAILED", 0, 3) + "\n")
    check("sr47 a label led by an id-shaped token is still named by that id, and "
          "carries its full label beside it: %r" % (_shape(M.failing_cases(led)),),
          _shape(M.failing_cases(led))
          == [("me1", "me1 the value is read (saw 1)", True),
              ("ga9b", "ga9b a suffix", True), ("pc-sd0", "pc-sd0 a hyphen", True)])
    code_u, text_u = _real_unittest()
    got_u = sorted(((c["id"], c["assertion"]) for c in M.failing_cases(text_u)),
                   key=repr)
    verdict_u, tally_u = M.classify_run(code_u, text_u)
    check("sr48 real unittest output still counts its cases - `FAIL:` as an "
          "assertion, `ERROR:` named but NOT credited as one - and a house-shaped "
          "line a unittest test printed is not a house case: %r %r"
          % (got_u, verdict_u),
          got_u == [("test_assert", True), ("test_raise", False)]
          and verdict_u == "red" and (tally_u or {}).get("assertions") == 1,
          text_u[-400:])
    quiet = ("ERROR: /tmp/nope is not a directory\n"
             "ERROR tests/data.json - the path is missing\n"
             "PASS the path is refused\n"
             + _TALLY % ("ALL PASS", 1, 1) + "\n")
    check("sr49 a passing house run that PRINTS error lines on purpose names no "
          "failing case at all - neither the unittest nor the pytest reader "
          "applies to output neither runner printed: %r"
          % (M.failing_cases(quiet),),
          M.failing_cases(quiet) == [])

    head = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1")])
    wt = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1"),
                       (_NEW_LABEL_SRC, "mine.v == 2")], extra=_EXPECTED_ERRORS)
    root, man = _red_repo("stamp-red-label-", wt, head_test=head)
    code, got = _red(root, man, [py, "tests/test_mine.py"])
    basis = (got.get("redFirst") or {}).get("basis", "")
    check("sr50 a house suite whose new case has a SENTENCE label proves red - "
          "HEAD's test file carries the label's first word in a case of its own, "
          "so a first word read as an id was refused - and an error line a "
          "passing case printed is no phantom case: exit=%r %s"
          % (code, json.dumps(got.get("redFirst") or got.get("note"))[:400]),
          code == M.E_PROVED and _NEW_LABEL in basis and "/tmp/nope" not in basis
          and "data.json" not in basis)
    runs = dict((flag, _red(root, man, [py, "tests/test_mine.py"], "--case", flag))
                for flag in (_NEW_LABEL, "the", _OLD_LABEL))
    check("sr51 --case names a sentence-labelled case by its full label; its "
          "first word alone is not a name, and the label of a case that passes "
          "is refused: %r" % (dict((k, v[0]) for k, v in runs.items()),),
          runs[_NEW_LABEL][0] == M.E_PROVED
          and runs["the"][0] == M.E_CANNOT_PROVE
          and runs[_OLD_LABEL][0] == M.E_CANNOT_PROVE
          and "names no case that failed" in json.dumps(runs[_OLD_LABEL][1]))

    wt_id = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1"),
                          ("'nv2 the new value is two'", "mine.v == 2")])
    root_i, man_i = _red_repo("stamp-red-idlabel-", wt_id, head_test=head)
    by = dict((flag, _red(root_i, man_i, [py, "tests/test_mine.py"], *flag))
              for flag in ((), ("--case", "nv2"),
                           ("--case", "nv2 the new value is two")))
    check("sr52 an id-led label proves red and the basis names it by its id; "
          "--case takes the id or the full label: %r"
          % (dict((k, (v[0], (v[1].get("redFirst") or {}).get("basis", "")[:160]))
                  for k, v in by.items()),),
          all(v[0] == M.E_PROVED for v in by.values())
          and "nv2 (house FAIL)" in by[()][1]["redFirst"]["basis"])


def _label_id_cases(check):
    labels = ["me1 x", "ga9b y", "pc-sd0 z", "bw1-a q", "h2b", "the thing",
              "viewer: x", "x-build", "", "a", "utf8 bytes", "9lives"]
    check("sr53 the id a house label is named by is the id the harness hands "
          "out and prove-gates attributes by - one shape, pinned by agreement "
          "rather than by a comment: %r"
          % ([(lb, M.house_case_id(lb), _harness.case_id(lb)) for lb in labels
              if M.house_case_id(lb) != _harness.case_id(lb)],),
          all(M.house_case_id(lb) == _harness.case_id(lb) for lb in labels))

# --- only the runner that ran; labels that loose literals happen to fit ---
# A passing house case may print a captured unittest transcript, `Ran N tests`
# line and all; a test file may hold a loose literal (`'%dx%d'`) or a generic
# message template (`'%s is %s'`) that fits labels it was never written for;
# and a FAIL line's detail may span lines, leaving ` (` with no closing paren.
_TRANSCRIPT = ("TRANSCRIPT = 'FAIL: test_new_rule (test_u.T)\\n----\\n"
               "Ran 3 tests in 0.001s\\n\\nFAILED (failures=1)'",
               "print(TRANSCRIPT)")


def _label_red(prefix, head_extra, wt_cases, wt_extra=(), flags=()):
    """`(exit, basis)` of a red over a HEAD suite holding the old sentence case
    and `head_extra`, and a working-tree suite adding `wt_cases`."""
    old = [(repr(_OLD_LABEL), "mine.v >= 1")]
    head = _label_suite(old, extra=head_extra)
    wt = _label_suite(old + list(wt_cases),
                      extra=list(head_extra) + list(wt_extra))
    root, man = _red_repo(prefix, wt, head_test=head)
    code, got = _red(root, man, [sys.executable, "tests/test_mine.py"], *flags)
    return code, json.dumps(got.get("redFirst") or got.get("note") or got)


def _runner_cases(check):
    echoed = ("PASS the gate reports the unittest failure it ran\n"
              "FAIL: test_new_rule (test_u.T)\n----\nRan 3 tests in 0.001s\n\n"
              "FAILED (failures=1)\nFAIL %s\n" % (_OLD_LABEL,)
              + _TALLY % ("SELFTEST FAILED", 1, 2) + "\n")
    verdict = M.classify_run(1, echoed)
    check("sr55 output carrying the tallies of TWO runners - a house run that "
          "prints a captured unittest transcript - names no runner by itself: "
          "no runner's cases are read, and the verdict says the tallies are "
          "mixed, where a fixed precedence used to pick one: %r %r"
          % (M.failing_cases(echoed), verdict),
          M.failing_cases(echoed) == [] and verdict[0] == M.V_MIXED
          and sorted(verdict[1]["mixed"]) == ["house", "unittest"]
          and _shape(M.failing_cases(echoed, "house"))
          == [(None, _OLD_LABEL, True)])
    head = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1")])
    wt = _label_suite([(repr(_OLD_LABEL), "mine.v == 2"),
                       ("'the gate reports the unittest failure it ran'",
                        "'FAILED' in TRANSCRIPT")], extra=_TRANSCRIPT)
    root, man = _red_repo("stamp-red-echo-", wt, head_test=head)
    code, got = _red(root, man, [sys.executable, "tests/test_mine.py"])
    check("sr56 ...so an EXISTING case edited to go red, beside a new passing "
          "case that echoes a unittest `FAIL:`, is not proved on that phantom: "
          "exit=%r %s" % (code, json.dumps(got.get("redFirst"))[:300]),
          code == M.E_CANNOT_PROVE
          and "test_new_rule" not in (got.get("redFirst") or {}).get("basis", "?"))


def _specific_cases(check):
    new = [("'the fix sets the next value'", "mine.v == 2")]
    code, said = _label_red("stamp-red-loose-", ["VIEW = '%dx%d' % (1280, 720)"],
                            new)
    check("sr57 a genuinely new sentence case PROVES although HEAD's test file "
          "holds a loose literal (`'%%dx%%d'`) the label happens to fit: HEAD's "
          "own run never printed that label: exit=%r %s" % (code, said[:300]),
          code == M.E_PROVED and "the fix sets the next value" in said)
    code_g, said_g = _label_red(
        "stamp-red-generic-", ["check('%s is %s' % ('a', 'b'), True)"],
        [("'the next value is %r once fixed' % (mine.v,)", "mine.v == 2")])
    check("sr58 ...and although HEAD holds a case whose label template "
          "(`'%%s is %%s'`) would fit it: that case printed its own label, not "
          "this one: exit=%r %s" % (code_g, said_g[:300]),
          code_g == M.E_PROVED and "the next value is 1 once fixed" in said_g)
    multi = "'line one\\nline two'"
    head_m = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1")])
    wt_m = head_m.replace("n = sum(results)",
                          "check('the value is two after the fix', mine.v == 2, "
                          "%s)\nn = sum(results)" % (multi,))
    root_m, man_m = _red_repo("stamp-red-multiline-", wt_m, head_test=head_m)
    code_m, got_m = _red(root_m, man_m, [sys.executable, "tests/test_mine.py"])
    check("sr60 a genuinely new sentence case PROVES when its FAIL detail spans "
          "lines - the printed line keeps ` (` and loses the closing paren: "
          "exit=%r %s" % (code_m, json.dumps(got_m.get("redFirst"))[:300]),
          code_m == M.E_PROVED)
def _wording_cases(check):
    with open(os.path.join(M_PLUGIN, "agents", "audit-executor.md"), "r",
              encoding="utf-8") as fh:
        brief = fh.read()
    helps = [a.help for a in M.build_parser()._actions if "--case" in a.option_strings]
    check("sr64 every place that spells --case says it takes an id OR a full "
          "label - the usage line, the flag's help, and the executor brief's "
          "command template: %r" % (helps,),
          "[--case ID|LABEL ...]" in (M.__doc__ or "")
          and helps and "full label" in helps[0]
          and "[--case <id or full label of the case you added>]" in brief)


# --- labels spelled twice or built at run time; two runners' tallies ---
_UNIT_HEAD = "\n".join([
    "import os, sys, unittest", _PATH_LINE, "import mine",
    "class T(unittest.TestCase):",
    "    def test_old(self):", "        self.assertTrue(mine.v >= 1)",
    "if __name__ == '__main__':", "    unittest.main()"]) + "\n"


def _unit_echo(tally):
    """A unittest file whose existing test is edited to fail and whose new
    passing test prints a house FAIL line - and, when `tally`, a house tally."""
    lines = ["import os, sys, unittest", _PATH_LINE, "import mine",
             "class T(unittest.TestCase):",
             "    def test_old(self):", "        self.assertEqual(mine.v, 2)",
             "    def test_echo(self):",
             "        print('FAIL zz9 the harness names a failing case')"]
    if tally:
        lines.append("        print('SELFTEST FAILED: 1/2 cases ' + 'passed')")
    lines += ["if __name__ == '__main__':", "    unittest.main()"]
    return "\n".join(lines) + "\n"


def _suite_red(prefix, head, wt, cmd=None):
    root, man = _red_repo(prefix, wt, head_test=head)
    code, got = _red(root, man, cmd or [sys.executable, "tests/test_mine.py"])
    return code, (got.get("redFirst") or {}).get("basis", json.dumps(got))


def _exact_cases(check):
    head_p = _label_suite([("'the value'", "mine.v >= 1")])
    wt_p = _label_suite([("'the value'", "mine.v >= 1"),
                         ("'the value (as read)'", "mine.v == 2")])
    code_p, basis_p = _suite_red("stamp-red-paren-", head_p, wt_p)
    check("sr67 THE ALLOW CASE for sr65: a genuinely new label holding a "
          "parenthesis still proves beside an older, shorter label HEAD's run "
          "printed, because the task's run prints that older label again: "
          "exit=%r %s" % (code_p, basis_p[:300]),
          code_p == M.E_PROVED and "the value (as read)" in basis_p)
def _command_cases(check):
    echoed = ("FAIL: test_new_rule (test_u.T)\n----\nRan 3 tests in 0.001s\n\n"
              "FAILED (failures=1)\nFAIL %s\n" % (_OLD_LABEL,)
              + _TALLY % ("SELFTEST FAILED", 1, 2) + "\n")
    py = sys.executable
    runners = dict((name, (M.classify_run(1, echoed, cmd)[1] or {}).get("runner"))
                   for name, cmd in (
                       ("a house --selftest", [py, "t.py", "--selftest"]),
                       ("python -m unittest", [py, "-m", "unittest", "t"]),
                       ("pytest", ["pytest", "-q", "t.py"]),
                       ("nothing named", [py, "t.py"])))
    check("sr69 when two runners' tallies appear, the test command decides when "
          "it names the runner - a house --selftest, -m unittest, pytest - and "
          "otherwise no runner is picked: %r" % (runners,),
          runners == {"a house --selftest": "house",
                      "python -m unittest": "unittest",
                      "pytest": None, "nothing named": None})


def _mixed_cases(check):
    code, basis = _suite_red("stamp-red-mixed-", _UNIT_HEAD, _unit_echo(True))
    check("sr70 a unittest run whose new passing test echoes a house FAIL line "
          "and a house tally is not proved on that phantom: the command names no "
          "runner, so the red is could-not-prove and names both tallies: "
          "exit=%r %s" % (code, basis[:400]),
          code == M.E_CANNOT_PROVE and "zz9" not in basis.split(" - ")[0]
          and "SELFTEST FAILED" in basis and "Ran 2 tests" in basis)
    code_c, basis_c = _suite_red("stamp-red-plain-", _UNIT_HEAD, _unit_echo(False))
    check("sr71 THE ALLOW CASE for sr70: the same unittest run with no house "
          "tally echoed is read as unittest, and its edited test_old proves - the "
          "task's own edit against a green baseline: exit=%r %s"
          % (code_c, basis_c[:300]),
          code_c == M.E_PROVED and "test_old" in basis_c)


# --- every red is the task's own against a GREEN baseline ---
# HEAD's own tests run on HEAD's code in an isolated clean throwaway; when they
# pass, every failure of the task's run comes from the task's change to the tests
# - a new case or an edited one - and the fix run must turn each one green. A
# red baseline is could-not-prove, whatever shape the red takes, with the
# instruction to narrow the command to the task's cases.
_L = "the next value is read"
_GENERIC = "check('%s is %s' % ('a', 'b'), True)"
_NEW_RULE = "the new rule is honoured"
_TMP = ["import atexit, shutil, tempfile", "WHERE = tempfile.mkdtemp(prefix='lbl-')",
        "atexit.register(shutil.rmtree, WHERE, True)"]


def _extra_red(prefix, head_extra, wt_extra, siblings=None):
    """`(exit, basis)` of a red over suites built from `extra` lines alone;
    `siblings` are further test modules committed at HEAD beside the suite."""
    root, man = _red_repo(prefix, _label_suite([], extra=wt_extra),
                          head_test=_label_suite([], extra=head_extra))
    for rel, text in (siblings or {}).items():
        _write(os.path.join(root, *rel.split("/")), text)
        _git(root, "add", rel)
    if siblings:
        _git(root, "commit", "-q", "-m", "siblings")
    code, got = _red(root, man, [sys.executable, "tests/test_mine.py"])
    return code, (got.get("redFirst") or {}).get("basis", json.dumps(got))


def _green_baseline_cases(check):
    head_t = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1")])
    wt_t = _label_suite([(repr(_OLD_LABEL), "mine.v >= 1")], extra=[
        "ROWS = [('the table row is read', 2)]",
        "for lb, want in ROWS:",
        "    check(lb, mine.v == want)"])
    code_t, basis_t = _suite_red("stamp-red-table-", head_t, wt_t)
    check("sr74 a new case whose label comes from a table proves: HEAD's own tests "
          "are green and the fix turns the new case green: exit=%r %s"
          % (code_t, basis_t[:300]),
          code_t == M.E_PROVED and "the table row is read" in basis_t)
    code_n, basis_n = _extra_red(
        "stamp-red-others-", ["check('the old one holds', True)"],
        ["check('the old one holds', True)",
         "ROWS = {'k': 'the dict row is read'}", "check(ROWS['k'], mine.v == 2)"])
    check("sr88 a new case whose label is a dict value proves: exit=%r %s"
          % (code_n, basis_n[:260]),
          code_n == M.E_PROVED and "the dict row is read" in basis_n)
    edits = [
        ("a dict value", ["ROWS = {'k': %r}" % (_L,), "check(ROWS['k'], mine.v >= 1)"],
         ["ROWS = {'k': %r}" % (_L,), "check(ROWS['k'], mine.v == 2)"]),
        ("a table row", ["ROWS = [(%r, 1)]" % (_L,), "for lb, want in ROWS:",
                         "    check(lb, mine.v >= want)"],
         ["ROWS = [(%r, 2)]" % (_L,), "for lb, want in ROWS:",
          "    check(lb, mine.v == want)"]),
        ("a label carrying a per-run value", _TMP + [
            "check('the file under %s is read' % (WHERE,), mine.v >= 1)"],
         _TMP + ["check('the file under %s is read' % (WHERE,), mine.v == 2)"]),
    ]
    got = dict((how, _extra_red("stamp-red-edit-", head, wt)[0])
               for how, head, wt in edits)
    check("sr127 THE ALLOW CASE: an EXISTING case edited to go red, however its "
          "label is named, proves against a green baseline - the red is the "
          "task's own edit, and the fix turns it green: %r" % (got,),
          all(c == M.E_PROVED for c in got.values()))
    code_s, basis_s = _extra_red(
        "stamp-red-stillred-", ["check('the old one holds', True)"],
        ["check('the old one holds', True)",
         "check('the new case the fix does not fix', mine.v == 3)"])
    check("sr128 a new failing case that still fails with the working tree's "
          "implementation is not proved - the fix run must turn every failure "
          "green: exit=%r %s" % (code_s, basis_s[:300]),
          code_s == M.E_CANNOT_PROVE and "do not all pass" in basis_s)


def _wrapper_cases(check):
    lam = ["expect = lambda n, c: check(n, c, 'saw %r' % (mine.v,))"]
    method = ["class Suite:", "    def expect(self, name, ok):",
              "        check(name, ok, 'saw %r' % (mine.v,))", "s = Suite()"]
    helper = ("def expect(check, name, ok):\n"
              "    check(name, ok, 'saw %r' % (ok,))\n")
    shapes = [
        ("sr81", "a lambda wrapper", lam,
         "expect(%r, mine.v == 2)" % (_NEW_RULE,), None),
        ("sr82", "a method wrapper", method,
         "s.expect(%r, mine.v == 2)" % (_NEW_RULE,), None),
        ("sr83", "a keyword label", [],
         "check(label=%r, ok=mine.v == 2)" % (_NEW_RULE,), None),
        ("sr84", "a wrapper imported from a sibling test module",
         ["from _helpers import expect"],
         "expect(check, %r, mine.v == 2)" % (_NEW_RULE,),
         {"tests/_helpers.py": helper}),
    ]
    for cid, how, base, new, siblings in shapes:
        code, basis = _extra_red("stamp-red-%s-" % (cid,), base + [_GENERIC],
                                 base + [_GENERIC, new], siblings)
        check("%s a new case named through %s proves, however its label is "
              "written: exit=%r %s" % (cid, how, code, basis[:260]),
              code == M.E_PROVED and _NEW_RULE in basis)


def _pytest_command_cases(check):
    text = ("FAILED t.py::test_x - assert 1 == 2\n"
            "===== 1 failed, 2 passed in 0.12s =====\n"
            + _TALLY % ("SELFTEST FAILED", 0, 1) + "\n")
    py = sys.executable
    got = dict((name, (M.classify_run(1, text, cmd)[1] or {}).get("runner"))
               for name, cmd in (("pytest", ["pytest", "-q", "t.py"]),
                                 ("python -m pytest", [py, "-m", "pytest", "t.py"]),
                                 ("bare", [py, "t.py"])))
    check("sr86 with a pytest summary beside a house tally, the command decides "
          "for pytest too - under `pytest` and `python -m pytest` - and a bare "
          "command reads mixed: %r" % (got,),
          got == {"pytest": "pytest", "python -m pytest": "pytest", "bare": None})


def _unittest_cases(check):
    unit_head = _unit_suite(["    def test_old(self):",
                             "        self.assertTrue(mine.v >= 1)"])
    unit_new = _unit_suite(["    def test_old(self):",
                            "        self.assertTrue(mine.v >= 1)",
                            "    def test_new(self):",
                            "        self.assertEqual(mine.v, 2)"])
    unit_edit = _unit_suite(["    def test_old(self):",
                             "        self.assertEqual(mine.v, 2)"])
    verbose = [sys.executable, "tests/test_mine.py", "-v"]
    runs = dict((k, _suite_red("stamp-red-unit-%s-" % (k,), unit_head, wt, cmd))
                for k, wt, cmd in (("new", unit_new, verbose),
                                   ("edited", unit_edit, verbose),
                                   ("quiet", unit_new,
                                    [sys.executable, "tests/test_mine.py"])))
    check("sr93 THE ALLOW CASE under unittest: with HEAD's own tests green, a new "
          "failing test proves, an existing one edited to fail proves, and so "
          "does a run that names only its failures: %r"
          % (dict((k, (c, b[-160:])) for k, (c, b) in runs.items()),),
          all(c == M.E_PROVED for c, _b in runs.values())
          and "test_new" in runs["new"][1] and "test_old" in runs["edited"][1])
    two = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                     "class A(unittest.TestCase):", "    def test_x(self):",
                     "        self.assertTrue(True)",
                     "class B(unittest.TestCase):", "    def test_x(self):",
                     "        self.assertTrue(True)",
                     "if __name__ == '__main__':", "    unittest.main()"]) + "\n"
    two_new = two.replace("class B(unittest.TestCase):",
                          "class C(unittest.TestCase):\n    def test_new(self):\n"
                          "        self.assertEqual(mine.v, 2)\n"
                          "class B(unittest.TestCase):")
    code_q, basis_q = _suite_red("stamp-red-classes-", two, two_new,
                                 [sys.executable, "tests/test_mine.py", "-v"])
    check("sr103 a new unittest test beside two classes sharing a method name "
          "proves: exit=%r %s" % (code_q, basis_q[:300]),
          code_q == M.E_PROVED and "test_new" in basis_q)
    new_rel = "tests/test_new.py"
    root, man = _red_repo("stamp-red-newfile-", _red_test("import mine", "True"),
                          extra={new_rel: _red_test("import mine", "mine.v == 2",
                                                    label="the new file holds a case")},
                          files=["src/mine.py", new_rel])
    code_f, got_f = _red(root, man, [sys.executable, new_rel])
    fix_run = (got_f.get("run") or {}).get("fix") or {}
    check("sr94 a test file that is new at HEAD proves - HEAD's run, made with "
          "it as an empty stub, is green - and the payload records the fix run "
          "with its exit and "
          "how long it took: exit=%r %r" % (code_f, fix_run),
          code_f == M.E_PROVED and isinstance(fix_run.get("seconds"), float)
          and fix_run.get("exit") == 0)
    with open(os.path.join(M_PLUGIN, "agents", "audit-executor.md"), "r",
              encoding="utf-8") as fh:
        brief = " ".join(fh.read().split())
    with open(os.path.join(M_PLUGIN, "reference", "execute-task.md"), "r",
              encoding="utf-8") as fh:
        ref = " ".join(fh.read().split())
    check("sr97 the executor brief and execute-task.md both state the rule: HEAD's "
          "own test files must be green on HEAD's code, else narrow the command "
          "to the task's cases, and the fix must turn every failure green",
          all("HEAD's own test files" in t and "GREEN baseline" in t
              and "narrow the command to the task's cases" in t
              and "fix run" in t for t in (brief, ref)))


def _red_baseline_cases(check):
    py = sys.executable
    shapes = [
        ("sr99", "HEAD already red on a per-run label, the task adding only a "
         "passing case",
         _label_suite([("'the object %r is kept' % (object(),)", "mine.v == 2")]),
         _label_suite([("'the object %r is kept' % (object(),)", "mine.v == 2"),
                       ("'the new pass'", "True")]), None),
        ("sr102", "HEAD red under unittest -f, the task fixing only the first "
         "broken test", _unit_suite(_FAILFAST_HEAD), _unit_suite(_FAILFAST_WT),
         [py, "tests/test_mine.py", "-v", "-f"]),
        ("sr117", "a case already red at HEAD, relabelled while its old label goes "
         "to a new passing case",
         _label_suite([("'the old broken case'", "mine.v == 2")]),
         _label_suite([("'the old broken case'", "True"),
                       ("'the renamed broken case'", "mine.v == 2")]), None),
        ("sr118", "a new failing case beside a case already red at HEAD",
         _label_suite([("'the old broken case'", "mine.v == 2")]),
         _label_suite([("'the old broken case'", "mine.v == 2"),
                       ("'the new failing case'", "mine.v == 2")]), None),
        ("sr119", "two reds at HEAD sharing a label, one relabelled",
         _label_suite([("'the old broken case'", "mine.v == 2"),
                       ("'the old broken case'", "mine.v == 2")]),
         _label_suite([("'the renamed case'", "mine.v == 2"),
                       ("'the old broken case'", "mine.v == 2"),
                       ("'the old broken case'", "True")]), None),
        ("sr120", "two reds at HEAD whose labels share a reading, one relabelled",
         _label_suite([("'the value'", "mine.v == 2"),
                       ("'the value (as read)'", "mine.v == 2")]),
         _label_suite([("'the renamed case'", "mine.v == 2"), ("'the value'", "True"),
                       ("'the value (as read)'", "mine.v == 2")]), None),
        ("sr121", "a failfast set in HEAD's test file itself",
         _unit_main(True), _unit_main(False), [py, "tests/test_mine.py", "-v"]),
        ("sr126", "a house suite that stops quietly after its first red at HEAD",
         _label_suite([], extra=_quiet_stop(True)),
         _label_suite([], extra=_quiet_stop(False)), None),
    ]
    for cid, how, head, wt, cmd in shapes:
        code, basis = _suite_red("stamp-red-%s-" % (cid,), head, wt, cmd)
        check("%s %s is not proved: HEAD's own tests are red on HEAD's code, so "
              "the command is already red at HEAD and must be narrowed to the "
              "task's cases: exit=%r %s" % (cid, how, code, basis[:300]),
              code == M.E_CANNOT_PROVE and "already red" in basis
              and "narrow" in basis)
    head = _label_suite([("'the next value is read'", "mine.v >= 1")])
    wt = _label_suite([("'the next value is read'", "mine.v == 2")])
    root, man = _red_repo("stamp-red-rename-", wt, head_test=head,
                          extra={"tests/test_ren.py": wt},
                          files=["src/mine.py", "tests/test_mine.py",
                                 "tests/test_ren.py"])
    os.remove(os.path.join(root, "tests", "test_mine.py"))
    code_r, got_r = _red(root, man, [py, "tests/test_ren.py"])
    basis_r = json.dumps(got_r.get("redFirst"))
    check("sr101 a declared test file renamed, the command naming only the new path: "
          "HEAD's run is made with that path as an empty stub and is green; the "
          "edited case in it fails on HEAD's code and passes with the fix, which "
          "is the proof: exit=%r %s" % (code_r, basis_r[:300]),
          code_r == M.E_PROVED and "laid over as empty files" in basis_r)
    probe = ["import os", "HERE = os.path.dirname(os.path.abspath(__file__))",
             "MARK = os.path.join(HERE, 'skip-the-legacy-case')"]
    head_i = _label_suite([], extra=probe + [
        "if not os.path.exists(MARK):",
        "    check('the legacy field is kept', mine.v == 99)"])
    wt_i = _label_suite([], extra=probe + [
        "open(MARK, 'w').close()",
        "check('the new case', mine.v == 2)"])
    code_i, basis_i = _suite_red("stamp-red-isolated-", head_i, wt_i)
    check("sr129 HEAD's own run is made in a throwaway reset to HEAD: a file the "
          "task's run left behind, which HEAD's test would read and skip its red "
          "case on, is gone - so HEAD's red baseline is seen and the red is not "
          "proved: exit=%r %s" % (code_i, basis_i[:300]),
          code_i == M.E_CANNOT_PROVE and "already red" in basis_i)
    tmp_probe = ["import os, tempfile",
                 "MARK = os.path.join(tempfile.gettempdir(), 'skip-legacy-%d' "
                 "% (os.getppid(),))"]
    head_t = _label_suite([], extra=tmp_probe + [
        "if not os.path.exists(MARK):",
        "    check('the legacy field is kept', mine.v == 99)"])
    wt_t = _label_suite([], extra=tmp_probe + [
        "open(MARK, 'w').close()",
        "check('the new case', mine.v == 2)"])
    code_t, basis_t = _suite_red("stamp-red-tmpdir-", head_t, wt_t)
    mark = os.path.join(tempfile.gettempdir(), "skip-legacy-%d" % (os.getpid(),))
    if os.path.exists(mark):
        os.remove(mark)
    home_probe = ["import os",
                  "MARK = os.path.join(os.path.expanduser('~'), '.skip-legacy-%d' "
                  "% (os.getppid(),))"]
    head_h = _label_suite([], extra=home_probe + [
        "if not os.path.exists(MARK):",
        "    check('the legacy field is kept', mine.v == 99)"])
    wt_h = _label_suite([], extra=home_probe + [
        "open(MARK, 'w').close()",
        "check('the new case', mine.v == 2)"])
    code_h, basis_h = _suite_red("stamp-red-home-", head_h, wt_h)
    home_mark = os.path.join(os.path.expanduser("~"),
                             ".skip-legacy-%d" % (os.getpid(),))
    if os.path.exists(home_mark):
        os.remove(home_mark)
    check("sr132 HEAD's own run gets a home of its own: a file the task's run left "
          "in $HOME, which HEAD's test would read and skip its red case on, is not "
          "there - so the red baseline is seen: exit=%r %s" % (code_h, basis_h[:300]),
          code_h == M.E_CANNOT_PROVE and "already red" in basis_h)
    spec = importlib.util.spec_from_file_location(
        "sweep_selftests_homes",
        os.path.join(_output.REPO_ROOT, "tools", "sweep-selftests.py"))
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    theirs = getattr(sweep, "HOME_VARS", None)
    check("sr133 the home names the baseline and the fix run are given are the "
          "table tools/sweep-selftests.py isolates its children with - one list, "
          "pinned by agreement: %r vs %r" % (M.HOME_VARS, theirs),
          theirs is not None and tuple(M.HOME_VARS) == tuple(theirs))
    check("sr130 HEAD's own run gets a TMPDIR of its own and no user site: a file "
          "the task's run left in its temp directory, which HEAD's test would read "
          "and skip its red case on, is not there - so the red baseline is seen: "
          "exit=%r %s" % (code_t, basis_t[:300]),
          code_t == M.E_CANNOT_PROVE and "already red" in basis_t)


def _baseline_unit_cases(check):
    py = sys.executable
    green = {"code": 0, "problem": None,
             "text": "PASS a\n" + _TALLY % ("ALL PASS", 1, 1) + "\n"}
    shapes = {
        "a red house run": {"code": 1, "problem": None,
                            "text": "FAIL a (x)\n" + _TALLY % ("SELFTEST FAILED", 0, 1)},
        "a run with no tally": {"code": 1, "problem": None, "text": "boom\n"},
        "a run that could not be made": {"code": None, "text": "",
                                         "problem": "timed out"},
        "exit 0 with a failure counted": {
            "code": 0, "problem": None,
            "text": "FAIL a (x)\n" + _TALLY % ("SELFTEST FAILED", 0, 1)},
        "a pytest run that stopped": {
            "code": 1, "problem": None,
            "text": "!!! stopping after 1 failures !!!\n=== 1 failed in 0.1s ===\n"},
    }
    got = dict((k, M.baseline_problem(h, [py, "t.py"])) for k, h in shapes.items())
    got["green"] = M.baseline_problem(green, [py, "t.py"])
    got["an empty stub run by its script"] = M.baseline_problem(
        {"code": 0, "problem": None, "text": ""}, [py, "tests/test_new.py"])
    got["unittest ran no test"] = M.baseline_problem(
        {"code": 5, "problem": None,
         "text": "\n----\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n"},
        [py, "-m", "unittest", "-v", "tests/test_new.py"])
    got["pytest collected nothing"] = M.baseline_problem(
        {"code": 5, "problem": None, "text": "=== no tests ran in 0.01s ===\n"},
        ["pytest", "tests/test_new.py"])
    got["pytest deselected every case"] = M.baseline_problem(
        {"code": 5, "problem": None, "text": "=== 2 deselected in 0.01s ===\n"},
        ["pytest", "tests/test_old.py", "-k", "test_new_case"])
    got["not made"] = M.baseline_problem(None, [py, "t.py"])
    reds = {
        "a red run, then the stub's empty one, behind exit 5": (
            {"code": 5, "problem": None,
             "text": "FAIL: test_value_is_two (tests.test_old.Old.test_value_is_two)\n"
                     "Ran 1 test in 0.0s\n\nFAILED (failures=1)\n"
                     "Ran 0 tests in 0.0s\n\nNO TESTS RAN\n"},
            ["sh", "-c", "two runs", "--", "-m", "unittest"]),
        "a mixed tally behind exit 5 and NO TESTS RAN": (
            {"code": 5, "problem": None,
             "text": "FAIL a (x)\n" + _TALLY % ("SELFTEST FAILED", 0, 1)
                     + "\nRan 0 tests in 0.0s\n\nNO TESTS RAN\n"},
            [py, "t.py"]),
        "a pytest exit 5 counting an error and no case run": (
            {"code": 5, "problem": None, "text": "=== 1 error in 0.01s ===\n"},
            ["pytest", "tests/test_new.py"]),
        "pytest's red run, then the stub's `no tests ran`, behind exit 5": (
            {"code": 5, "problem": None,
             "text": "FAILED tests/test_old.py::test_value_is_two - assert 1 == 2\n"
                     "==== 1 failed in 0.01s ====\n==== no tests ran in 0.00s ====\n"},
            ["sh", "-c", "pytest tests/test_old.py; pytest tests/test_new.py"]),
        "exit 5 with no tally at all, saying no tests ran": (
            {"code": 5, "problem": None, "text": "no tests ran\n"}, [py, "t.py"]),
    }
    for k, (h, cmd) in reds.items():
        got[k] = M.baseline_problem(h, cmd)
    greens = ("green", "an empty stub run by its script", "unittest ran no test",
              "pytest collected nothing", "pytest deselected every case")
    check("sr104 the baseline is green on exit 0 with no failure counted, or on an "
          "exit 5 whose ONE runner's tally counts no case run and no failure - what a "
          "command naming only new files gives when they are empty stubs, and pytest "
          "gives when -k deselects everything; never on the words alone, a red run "
          "before an empty one, or a mixed tally; and a run not made is never "
          "green: %r"
          % (got,),
          all(got[k] is None for k in greens)
          and all(got[k] and "narrow" in got[k]
                  for k in list(shapes) + ["not made"] + list(reds)))
    summed = M._unittest_tally("Ran 1 test in 0.0s\n\nFAILED (failures=1)\n"
                               "Ran 2 tests in 0.0s\n\nOK\n")
    two_fix = ("FAILED tests/test_new.py::test_always - assert False\n"
               "==== 1 failed in 0.01s ====\n==== 1 passed in 0.01s ====\n")
    p2 = M.fix_problem({"code": 0, "problem": None, "text": two_fix},
                       ["sh", "-c", "pytest tests/test_new.py; pytest tests/test_b.py"],
                       {"runner": "pytest", "collected": 1, "failed": 1})
    p2_tally = M.read_tally(two_fix, None)
    check("sr171 pytest's tally sums every summary line, so a fix run whose first "
          "invocation still fails is not passing because its last one passed: %r %r"
          % (p2, p2_tally),
          p2 is not None and "do not all pass" in p2
          and p2_tally["failed"] == 1 and p2_tally["collected"] == 2)
    check("sr163 unittest's tally counts every `Ran N` line it counts the FAILED "
          "lines of, so two runs read as one tally and not as the last: %r"
          % (summed,), summed["collected"] == 3 and summed["failed"] == 1)
    one = {"code": 0, "problem": None,
           "text": "PASS a\n" + _TALLY % ("ALL PASS", 1, 1) + "\n"}
    fewer = M.fix_problem(one, [py, "t.py"], {"collected": 2})
    same = M.fix_problem(one, [py, "t.py"], {"collected": 1})
    red_fix = M.fix_problem(shapes["a red house run"], [py, "t.py"], {"collected": 1})
    check("sr131 the fix run must be green and run no fewer cases than the task's "
          "run - a failing case may not go missing instead of passing: %r"
          % ((fewer, same, red_fix),),
          fewer and "missing" in fewer and same is None
          and red_fix and "do not all pass" in red_fix)
    rel = "tests/t.py"
    failing = [{"id": None, "label": rel + "::test_a", "assertion": True,
                "why": "assert False"},
               {"id": None, "label": rel + "::test_b", "assertion": False,
                "why": "TypeError"}]
    own = M.own_failures(failing, [rel + "::test_a", "tests/t.py::test_b"])
    check("sr63 --case must name a case that failed an assertion in the task's "
          "run: a pytest node id does, a body error does not: %r" % (own,),
          [f["label"] for f in own[0]] == [rel + "::test_a"]
          and own[1] == ["tests/t.py::test_b"])
    root = _seeded_repo("stamp-isolate-")
    os.makedirs(os.path.join(root, "tests"))
    committed = b"x = 1\n\n\n"
    with open(os.path.join(root, "tests", "t.py"), "wb") as fh:
        fh.write(committed)
    _write(os.path.join(root, ".gitignore"), "*.log\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "t")
    _write(os.path.join(root, "tests", "t.py"), "x = 2\n")
    _write(os.path.join(root, "tests", "stray.py"), "left behind\n")
    _write(os.path.join(root, "run.log"), "ignored, left behind\n")
    calls = []
    real = M._git

    def recording(where, args, timeout=120, **kwargs):
        calls.append(timeout)
        return real(where, args, timeout=timeout, **kwargs)
    M._git = recording
    try:
        problem = M._isolate(root, time.time() + 5)
    finally:
        M._git = real
    with open(os.path.join(root, "tests", "t.py"), "rb") as fh:
        back = fh.read()
    left = [p for p in ("tests/stray.py", "run.log")
            if os.path.exists(os.path.join(root, *p.split("/")))]
    check("sr105 the throwaway is reset to HEAD exactly before HEAD's own run: a "
          "rewritten tracked file comes back byte for byte, an untracked and an "
          "ignored file are removed, and every git call runs under the one "
          "deadline: %r" % ((problem, back, left, calls),),
          problem is None and back == committed and not left and calls
          and all(t <= 6 for t in calls))


def _round5_cases(check):
    py = sys.executable
    broken = _label_suite([("'the old broken case'", "mine.v == 2")])
    plus_new = _label_suite([("'the old broken case'", "mine.v == 2"),
                             ("'the new pass'", "True")])
    got = dict((rel, _path_red("stamp-red-path-", rel, broken, plus_new))
               for rel in ("tests/test_café.py", "tests/test_cafe.py"))
    check("sr107 a declared test file whose path git quotes (not plain ASCII) is "
          "found at HEAD like an ASCII one, so HEAD's red baseline is seen: %r"
          % (dict((k, v[0]) for k, v in got.items()),),
          all(v[0] == M.E_CANNOT_PROVE and "already red" in v[1]
              for v in got.values()))
    head_u, wt_u = _unit_suite(_FAILFAST_HEAD), _unit_suite(_FAILFAST_WT)
    runs = dict((" ".join(flags), _suite_red("stamp-red-ff-", head_u, wt_u,
                                             [py, "tests/test_mine.py"] + flags)[0])
                for flags in (["-vf"], ["-fv"], ["-v", "-cf"], ["-v", "--failf"]))
    runs["sh -c"] = _suite_red("stamp-red-sh-", head_u, wt_u,
                               ["sh", "-c", "%s tests/test_mine.py -v -f"
                                % (_sh_word(py),)])[0]
    check("sr109 HEAD red under failfast in any spelling, or under a wrapper, is "
          "not proved - the baseline is red whatever stopped it: %r" % (runs,),
          all(c == M.E_CANNOT_PROVE for c in runs.values()))
    old_u = _unit_suite(["    def test_old(self):",
                         "        self.assertEqual(mine.v, 3)"])
    new_u = _unit_suite(["    def test_old(self):", "        self.assertEqual(mine.v, 3)",
                         "    def test_new(self):", "        self.assertEqual(mine.v, 2)"])
    code_v, basis_v = _suite_red("stamp-red-vv-", old_u, new_u,
                                 [py, "tests/test_mine.py", "-vv"])
    check("sr110 a new test beside an existing one already red at HEAD is not "
          "proved under any runner - narrow the command to the task's cases: "
          "exit=%r %s" % (code_v, basis_v[:300]),
          code_v == M.E_CANNOT_PROVE and "narrow" in basis_v)


def _round5_unit_cases(check):
    root = _seeded_repo("stamp-quoted-")
    rels = ["tests/test_café.py", "tests/t.py"]
    os.makedirs(os.path.join(root, "tests"))
    for rel in rels:
        _write(os.path.join(root, *rel.split("/")), "x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "t")
    calls = []
    real = M._git

    def recording(where, args, timeout=120, **kwargs):
        calls.append(timeout)
        return real(where, args, timeout=timeout, **kwargs)
    M._git = recording
    try:
        present, problem = M._at_head(root, rels + ["tests/absent.py"],
                                      time.time() + 30)
    finally:
        M._git = real
    check("sr111 HEAD's file list is read NUL-separated, so a path git quotes is "
          "found exactly like an ASCII one, an absent path is absent, and the git "
          "call runs under the one deadline: %r" % ((present, problem, calls),),
          problem is None and present == set(rels) and calls
          and all(c <= 31 for c in calls))
    root = _seeded_repo("stamp-introduced-")
    calls = []
    real = M._git

    def recording(where, args, timeout=120, **kwargs):
        calls.append(timeout)
        return real(where, args, timeout=timeout, **kwargs)
    M._git = recording
    try:
        M.introduced(root, ["src/mine.py"], "helper_fn", time.time() + 5)
    finally:
        M._git = real
    check("sr115 --introduces reads HEAD's implementation files under the one "
          "deadline too: %r" % (calls,), calls and all(t <= 6 for t in calls))
    wt = _house_test("import mine", [("old1", "True"), ("new1", "mine.v == 2"),
                                     ("the child writes no bytecode",
                                      "sys.dont_write_bytecode")])
    head = _house_test("import mine", [("old1", "True"),
                                       ("the child writes no bytecode",
                                        "sys.dont_write_bytecode")])
    root_b, man_b = _red_repo("stamp-red-pyc-", wt, head_test=head)
    code_b, got_b = _red(root_b, man_b, [sys.executable, "tests/test_mine.py"])
    basis_b = (got_b.get("redFirst") or {}).get("basis", "")
    check("sr116 every run in the throwaway is made with bytecode writing off - a "
          "file swapped for one of the same size in the same second is otherwise "
          "shadowed by a stale cached copy - and the payload says so: exit=%r %s"
          % (code_b, basis_b[:200]),
          code_b == M.E_PROVED
          and "PASS the child writes no bytecode"
          in ((got_b.get("run") or {}).get("outputTail") or [])
          and "PYTHONDONTWRITEBYTECODE=1"
          in (got_b.get("environment") or {}).get("set", []))


# --- every run isolated; HEAD's baseline first, skipped only on proof ---
def _with_env(name, value, fn):
    """`fn()` with `os.environ[name]` set to `value`, restored after."""
    held = os.environ.get(name)
    os.environ[name] = value
    try:
        return fn()
    finally:
        if held is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = held


def _new_only_repo(prefix):
    """HEAD holds tests/test_old.py, red at HEAD and fixed by the implementation;
    the task declares src/mine.py and a NEW tests/test_new.py asserting nothing."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    _write(os.path.join(root, "tests", "test_old.py"), "\n".join([
        "import os, sys, unittest", _PATH_LINE, "import mine",
        "class Old(unittest.TestCase):", "    def test_value_is_two(self):",
        "        self.assertEqual(mine.v, 2)"]) + "\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "red at HEAD")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    _write(os.path.join(root, "tests", "test_new.py"), "\n".join([
        "import unittest", "class New(unittest.TestCase):",
        "    def test_new(self):", "        self.assertTrue(True)"]) + "\n")
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", "tests/test_new.py"]
    task["tests"] = {"mode": "tdd", "add": ["tests/test_new.py: v is two"]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    return root, man


def _every_run_cases(check):
    py = sys.executable
    home_case = ("'the home holds no stray config'",
                 "not os.path.exists(os.path.join(os.path.expanduser('~'), "
                 "'.mine-stray'))")
    head = _label_suite([home_case])
    wt = _label_suite([home_case, ("'the new case'", "True")])
    home = _harness.fixture_root("stamp-caller-home-")
    _write(os.path.join(home, ".mine-stray"), "x\n")
    root, man = _red_repo("stamp-red-callerhome-", wt, head_test=head)
    code_h, got_h = _with_env("HOME", home, lambda: _red(
        root, man, [py, "tests/test_mine.py"]))
    check("sr134 a HEAD case red only under the CALLER's home is not credited: the "
          "task's run gets a fresh home as every run does, so that case passes "
          "there and nothing of the task's is red: exit=%r %s"
          % (code_h, json.dumps(got_h.get("redFirst") or got_h.get("note"))[:300]),
          code_h == M.E_NOT_RED and "PASSED in the throwaway" in (got_h.get("note") or ""))
    tmp_case = ("'no stale lock is left in the temp dir'",
                "not os.path.exists(os.path.join(__import__('tempfile')"
                ".gettempdir(), 'mine.lock'))")
    head_t = _label_suite([tmp_case])
    wt_t = _label_suite([tmp_case, ("'the new case'", "True")])
    tmpd = _harness.fixture_root("stamp-caller-tmp-")
    _write(os.path.join(tmpd, "mine.lock"), "x")
    root_t, man_t = _red_repo("stamp-red-callertmp-", wt_t, head_test=head_t)
    code_t, got_t = _with_env("TMPDIR", tmpd, lambda: _red(
        root_t, man_t, [py, "tests/test_mine.py"]))
    check("sr135 ...and the same through the caller's TMPDIR: exit=%r %s"
          % (code_t, json.dumps(got_t.get("redFirst") or got_t.get("note"))[:300]),
          code_t == M.E_NOT_RED and "PASSED in the throwaway" in (got_t.get("note") or ""))
    discover = [py, "-m", "unittest", "discover", "-s", "tests", "-v"]
    root_n, man_n = _new_only_repo("stamp-red-newonly-")
    code_n, got_n = _red(root_n, man_n, discover)
    basis_n = json.dumps(got_n.get("redFirst") or got_n.get("note"))
    check("sr136 every declared test file new at HEAD does not skip HEAD's run when "
          "the command reaches HEAD's old tests too (a discovery): HEAD's run is "
          "made, is red, and the red is not credited: exit=%r %s"
          % (code_n, basis_n[:300]),
          code_n == M.E_CANNOT_PROVE and "narrow" in basis_n)
    root_1, man_1 = _new_only_repo("stamp-red-newonly1-")
    code_1, _got_1 = _red(root_1, man_1, discover, "--case", "test_new")
    check("sr137 ...and with --case naming the new test, still not proved: "
          "exit=%r" % (code_1,), code_1 == M.E_CANNOT_PROVE)
    root_o, man_o = _new_only_repo("stamp-red-newonly2-")
    _write(os.path.join(root_o, "tests", "test_new.py"), "\n".join([
        "import os, sys, unittest", _PATH_LINE, "import mine",
        "class New(unittest.TestCase):", "    def test_new(self):",
        "        self.assertEqual(mine.v, 2)",
        "if __name__ == '__main__':", "    unittest.main()"]) + "\n")
    code_o, got_o = _red(root_o, man_o, [py, "tests/test_new.py", "-v"])
    basis_o = (got_o.get("redFirst") or {}).get("basis", "")
    check("sr138 THE ALLOW CASE: a command naming ONLY a test file new at HEAD "
          "proves - HEAD's run is made with that file as an empty stub, is green, "
          "and the basis says so: exit=%r %s" % (code_o, basis_o[:300]),
          code_o == M.E_PROVED and "laid over as empty files" in basis_o
          and ((got_o.get("run") or {}).get("head") or {}).get("exit") == 0)
    detail = repr([(i, i + 1) for i in range(20000)])
    long_fail = {"id": None, "label": "the pairs round-trip (saw %s)" % (detail,),
                 "assertion": True, "why": "house FAIL"}
    code = "\n".join([
        "import sys, tracemalloc", "sys.path.insert(0, %r)" % (_output.TESTS_DIR,),
        "import _harness, _loader",
        "M = _loader.load_script('stamp-verification.py', modname='sv_forms')",
        "d = repr([(i, i + 1) for i in range(20000)])",
        "f = {'id': None, 'label': 'the pairs round-trip (saw %s)' % (d,),"
        " 'assertion': True, 'why': 'house FAIL'}",
        "tracemalloc.start()",
        "own, refused = M.own_failures([f], ['the pairs round-trip'])",
        "print(len(own), len(refused), tracemalloc.get_traced_memory()[1])"])
    try:
        proc = subprocess.run([py, "-c", code], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True,
                              timeout=60)
        out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    except subprocess.TimeoutExpired:
        out = "timed out"
    parts = out.split()
    rss_mb = (int(parts[2]) // (1 << 20)
              if len(parts) == 3 and parts[2].isdigit() else None)
    check("sr139 --case names a label beside a long parenthesised detail in linear "
          "memory - no prefix of the line is built; measured with tracemalloc, "
          "which every platform has: %r (%r MB peak) %d chars"
          % (out, rss_mb, len(long_fail["label"])),
          parts[:2] == ["1", "0"] and rss_mb is not None and rss_mb < 8)
    # The task's run leaves a marker where the fix run would read it, and its new
    # case passes on that marker alone - the fix (v = 2) never satisfies it. Only
    # a fix run with a home, a temp directory and a tree of its own sees the case
    # stay red.
    channels = [
        ("sr142", "its home", "os.path.join(os.path.expanduser('~'), "
                              "'.fix-mark-%d' % (os.getppid(),))"),
        ("sr143", "its temp directory", "os.path.join(__import__('tempfile')"
                                        ".gettempdir(), 'fix-mark-%d' % (os.getppid(),))"),
        ("sr144", "the throwaway tree", "os.path.join(os.path.dirname("
                                        "os.path.abspath(__file__)), 'fix-mark')"),
    ]
    head_f = _label_suite([("'the old one holds'", "True")])
    for cid, where_ch, mark in channels:
        wt_f = _label_suite([("'the old one holds'", "True")], extra=[
            "import atexit", "MARK = %s" % (mark,),
            "check('the new case', os.path.exists(MARK) or mine.v == 3)",
            "atexit.register(lambda: open(MARK, 'w').close())"])
        code_f, basis_f = _suite_red("stamp-red-%s-" % (cid,), head_f, wt_f)
        for leftover in (os.path.join(os.path.expanduser("~"),
                                      ".fix-mark-%d" % (os.getpid(),)),
                         os.path.join(tempfile.gettempdir(),
                                      "fix-mark-%d" % (os.getpid(),))):
            if os.path.exists(leftover):
                os.remove(leftover)
        check("%s the fix run gets %s of its own: a marker the task's run left "
              "there, on which alone its new case passes, is not there, so the "
              "case stays red with the fix and is not proved: exit=%r %s"
              % (cid, where_ch, code_f, basis_f[:240]),
              code_f == M.E_CANNOT_PROVE and "do not all pass" in basis_f)


# --- the baseline reaches what the task's run reaches; only located reds count --
_NEW_TRIVIAL = "\n".join(["import unittest", "class New(unittest.TestCase):",
                          "    def test_new(self):", "        self.assertTrue(True)"]) + "\n"
_OLD_RED = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                      "class Old(unittest.TestCase):",
                      "    def test_value_is_two(self):",
                      "        self.assertEqual(mine.v, 2)"]) + "\n"


def _reach_repo(prefix, new_text=_NEW_TRIVIAL, old_text=_OLD_RED, declare_old=False,
                wt_old=None):
    """HEAD holds a unittest package `tests/` with test_old.py (red at HEAD by
    default, fixed by the implementation); the task declares src/mine.py and a
    NEW tests/test_new.py - and test_old.py too when `declare_old`."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    _write(os.path.join(root, "tests", "__init__.py"), "")
    _write(os.path.join(root, "tests", "test_old.py"), old_text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "at HEAD")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    _write(os.path.join(root, "tests", "test_new.py"), new_text)
    if wt_old is not None:
        _write(os.path.join(root, "tests", "test_old.py"), wt_old)
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = (["src/mine.py", "tests/test_new.py"]
                     + (["tests/test_old.py"] if declare_old else []))
    task["tests"] = {"mode": "tdd", "add": ["tests/test_new.py: v is two"]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    return root, man


def _tree_repo(prefix, head, wt, declared, moves=()):
    """HEAD holds `head` (`{rel: text}`) beside the seeded src/mine.py; the
    working tree fixes mine.py, `git mv`s each `(old, new)` of `moves` and then
    writes `wt`; the task declares src/mine.py and `declared`."""
    root = _seeded_repo(prefix)

    def put(rel, text):
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        _write(path, text)
    for rel, text in head.items():
        put(rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "at HEAD")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    for old, new in moves:
        _git(root, "mv", old, new)
    for rel, text in wt.items():
        put(rel, text)
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py"] + list(declared)
    task["tests"] = {"mode": "tdd", "add": ["%s: v is two" % (declared[0],)]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    return root, man


def _moved_cases(check):
    py = sys.executable
    unit = [py, "-m", "unittest", "-v"]
    head = {"tests/__init__.py": "", "tests/test_old.py": _OLD_RED}
    move = [("tests/test_old.py", "tests/test_moved.py")]
    red_shapes = [
        ("sr164", "HEAD's red file `git mv`d, unchanged, the new path declared",
         head, {}, ["tests/test_moved.py"], move, "tests/test_moved.py"),
        ("sr165", "the same rename with both paths declared", head, {},
         ["tests/test_moved.py", "tests/test_old.py"], move, "tests/test_moved.py"),
        ("sr166", "a verbatim copy of HEAD's red class in a new declared file", head,
         {"tests/test_new.py": _OLD_RED}, ["tests/test_new.py"], (),
         "tests/test_new.py"),
    ]
    for cid, how, head_files, wt, declared, moves, target in red_shapes:
        root, man = _tree_repo("stamp-red-%s-" % (cid,), head_files, wt, declared,
                               moves)
        code, got = _red(root, man, unit + [target])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s %s does not get HEAD's red credited - an ast-identical def under "
              "the same class and name anywhere in HEAD's test files is HEAD's "
              "case: exit=%r %s" % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and "HEAD's tests/test_old.py" in basis)
    edited = _OLD_RED.replace("assertEqual(mine.v, 2)", "assertEqual(2, mine.v)")
    root, man = _tree_repo("stamp-red-sr167-", head, {"tests/test_moved.py": edited},
                           ["tests/test_moved.py"], move)
    code, got = _red(root, man, unit + ["tests/test_moved.py"])
    basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
    check("sr167 THE ALLOW CASE: a case EDITED in a renamed file is the task's and "
          "proves: exit=%r %s" % (code, basis[:400]),
          code == M.E_PROVED and "test_value_is_two" in basis)
    legacy = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                        "class Old(unittest.TestCase):",
                        "    def test_value_is_two(self):",
                        "        self.assertEqual(mine.v, 2)"]) + "\n"
    reach = "\n".join(["import os, sys, unittest",
                       "sys.path.insert(0, os.path.join(os.path.dirname("
                       "os.path.abspath(__file__)), '..', 'legacy'))",
                       "from test_old import Old", "class New(unittest.TestCase):",
                       "    def test_new(self):", "        self.assertTrue(True)"]) + "\n"
    decoy = "\n".join(["import unittest", "class Old(unittest.TestCase):",
                       "    def test_value_is_two(self):",
                       "        self.assertTrue(True)"]) + "\n"
    root, man = _tree_repo("stamp-red-sr168-",
                           {"tests/__init__.py": "", "legacy/test_old.py": legacy},
                           {"tests/test_new.py": reach, "tests/test_old.py": decoy},
                           ["tests/test_new.py", "tests/test_old.py"])
    code, got = _red(root, man, unit + ["tests/test_new.py"])
    basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
    check("sr168 a module name whose trailing components also name an undeclared "
          "file HEAD has (legacy/test_old.py) is not mapped to the declared one that "
          "shares them: exit=%r %s" % (code, basis[:400]),
          code == M.E_CANNOT_PROVE and "no declared test file" in basis)
    rebinds = [
        ("sr169", "a class-body assignment after the def rebinds the case to HEAD's "
         "function", "\n".join([
             "import unittest", "from tests import test_old",
             "class New(unittest.TestCase):", "    def test_value_is_two(self):",
             "        self.assertTrue(True)",
             "    test_value_is_two = test_old.Old.test_value_is_two"]) + "\n"),
        ("sr170", "a module-level `New = type(...)` after class New rebinds the class",
         "\n".join([
             "import unittest", "from tests import test_old",
             "class New(unittest.TestCase):", "    def test_value_is_two(self):",
             "        self.assertTrue(True)",
             "New = type('New', (test_old.Old,), {})"]) + "\n"),
    ]
    for cid, how, text in rebinds:
        root, man = _tree_repo("stamp-red-%s-" % (cid,), head,
                               {"tests/test_new.py": text}, ["tests/test_new.py"])
        code, got = _red(root, man, unit + ["tests/test_new.py"])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s %s - the def is not what runs, so it is not credited: exit=%r %s"
              % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and "does not define it" in basis)



def _binding_cases(check):
    py = sys.executable
    unit = [py, "-m", "unittest", "-v"]
    head = {"tests/__init__.py": "", "tests/test_old.py": _OLD_RED}
    own_red = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                         "class New(unittest.TestCase):",
                         "    def test_new_two(self):",
                         "        self.assertEqual(mine.v, 2)",
                         "New.maxDiff = None"]) + "\n"
    root, man = _tree_repo("stamp-red-sr175-", head, {"tests/test_new.py": own_red},
                           ["tests/test_new.py"])
    code, got = _red(root, man, unit + ["tests/test_new.py"])
    basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
    check("sr175 THE ALLOW CASE: a new red case whose class gets `New.maxDiff = None` "
          "after it proves - an attribute assignment rebinds no name: exit=%r %s"
          % (code, basis[:400]),
          code == M.E_PROVED and "test_new_two" in basis)
    rebinds = [
        ("sr176", "a class-body `with ... as test_value_is_two` after the def", "\n".join([
            "import contextlib, unittest", "from tests import test_old",
            "class New(unittest.TestCase):", "    def test_value_is_two(self):",
            "        self.assertTrue(True)",
            "    with contextlib.nullcontext(test_old.Old.test_value_is_two)"
            " as test_value_is_two:", "        pass"]) + "\n"),
        ("sr177", "a class-body walrus after the def", "\n".join([
            "import unittest", "from tests import test_old",
            "class New(unittest.TestCase):", "    def test_value_is_two(self):",
            "        self.assertTrue(True)",
            "    (test_value_is_two := test_old.Old.test_value_is_two)"]) + "\n"),
    ]
    for cid, how, text in rebinds:
        root, man = _tree_repo("stamp-red-%s-" % (cid,), head,
                               {"tests/test_new.py": text}, ["tests/test_new.py"])
        code, got = _red(root, man, unit + ["tests/test_new.py"])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s %s rebinds the case to HEAD's function, so the def is not what "
              "runs and HEAD's red is not credited: exit=%r %s"
              % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and "does not define it" in basis)
    passing = ["import unittest", "from tests import test_old",
               "class New(unittest.TestCase):", "    def test_value_is_two(self):",
               "        self.assertTrue(True)"]
    replaced = [
        ("sr184", "a module-level `New.test_value_is_two = ...` after the class",
         "New.test_value_is_two = test_old.Old.test_value_is_two"),
        ("sr185", "a module-level `setattr(New, 'test_value_is_two', ...)`",
         "setattr(New, 'test_value_is_two', test_old.Old.test_value_is_two)"),
    ]
    for cid, how, line in replaced:
        root, man = _tree_repo("stamp-red-%s-" % (cid,), head,
                               {"tests/test_new.py": "\n".join(passing + [line]) + "\n"},
                               ["tests/test_new.py"])
        code, got = _red(root, man, unit + ["tests/test_new.py"])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s %s replaces the passing def with HEAD's function, so the def is not "
              "what runs and HEAD's red is not credited: exit=%r %s"
              % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and "does not define it" in basis)
    legacy = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                        "class Old(unittest.TestCase):",
                        "    def test_value_is_two(self):",
                        "        self.assertEqual(mine.v, 2)"]) + "\n"
    reach = "\n".join(["import os, sys, unittest",
                       "sys.path.insert(0, os.path.join(os.path.dirname("
                       "os.path.abspath(__file__)), '..', 'legacy'))",
                       "from test_old import Old", "class New(unittest.TestCase):",
                       "    def test_new(self):", "        self.assertTrue(True)"]) + "\n"
    decoy = "\n".join(["import unittest", "class Old(unittest.TestCase):",
                       "    def test_value_is_two(self):",
                       "        self.assertTrue(True)"]) + "\n"
    root, man = _tree_repo("stamp-red-sr178-",
                           {"tests/__init__.py": "", "legacy/test_old.py": legacy},
                           {"tests/test_new.py": reach, "test_old.py": decoy},
                           ["tests/test_new.py", "test_old.py"])
    code, got = _red(root, man, unit + ["tests/test_new.py"])
    basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
    check("sr178 a unittest module that EXACTLY names a declared file is still not "
          "mapped to it when an undeclared file HEAD has (legacy/test_old.py) ends "
          "with the same path - unittest found it through sys.path: exit=%r %s"
          % (code, basis[:400]),
          code == M.E_CANNOT_PROVE and "no declared test file" in basis)
    suite = _house_test("import mine", [("old1", "mine.v == 2")])
    house = [
        ("sr179", "HEAD's red house suite `git mv`d, unchanged", {
            "tests/test_hold.py": suite}, {}, ["tests/test_hmoved.py"],
         [("tests/test_hold.py", "tests/test_hmoved.py")], "tests/test_hmoved.py"),
        ("sr180", "a verbatim copy of HEAD's red house suite", {
            "tests/test_hold.py": suite}, {"tests/test_hcopy.py": suite},
         ["tests/test_hcopy.py"], (), "tests/test_hcopy.py"),
    ]
    for cid, how, head_files, wt, declared, moves, script in house:
        root, man = _tree_repo("stamp-red-%s-" % (cid,), head_files, wt, declared,
                               moves)
        code, got = _red(root, man, [py, script])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s %s is not credited under a house run - the script is identical to "
              "HEAD's tests/test_hold.py: exit=%r %s" % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and "HEAD's tests/test_hold.py" in basis)
    fresh = _house_test("import mine", [("new1", "mine.v == 2")])
    root, man = _tree_repo("stamp-red-sr181-", {"tests/test_hold.py": suite},
                           {"tests/test_hnew.py": fresh}, ["tests/test_hnew.py"])
    code, got = _red(root, man, [py, "tests/test_hnew.py"])
    basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
    check("sr181 THE ALLOW CASE: a NEW house suite with its own red case still proves: "
          "exit=%r %s" % (code, basis[:400]),
          code == M.E_PROVED and "new1" in basis)


def _reach_cases(check):
    py = sys.executable
    unit = [py, "-m", "unittest", "-v"]
    importing = "\n".join(["import os, sys, unittest",
                           "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))",
                           "from test_old import Old", "class New(unittest.TestCase):",
                           "    def test_new(self):", "        self.assertTrue(True)"]) + "\n"
    shapes = [
        ("sr145", "a second argument naming HEAD's red module by its dotted name",
         _NEW_TRIVIAL, unit + ["tests/test_new.py", "tests.test_old"], None),
        ("sr146", "a new test file that imports HEAD's red TestCase", importing,
         unit + ["tests/test_new.py"], None),
        ("sr147", "a shell wrapper whose script is a discovery",
         _NEW_TRIVIAL, ["sh", "-c", _sh_word(py) + " -m unittest discover -s tests -v",
                        "tests/test_new.py"], None),
        ("sr148", "HEAD's red file deleted in the working tree, undeclared, named "
         "beside the new file", _NEW_TRIVIAL,
         unit + ["tests/test_new.py", "tests/test_old.py"], "delete"),
        ("sr153", "a new TestCase that subclasses HEAD's red one and so inherits its "
         "case", importing.replace("class New(unittest.TestCase):", "class New(Old):"),
         unit + ["tests/test_new.py"], None),
    ]
    for cid, how, new_text, cmd, edit in shapes:
        root, man = _reach_repo("stamp-red-%s-" % (cid,), new_text=new_text)
        if edit == "delete":
            os.remove(os.path.join(root, "tests", "test_old.py"))
        code, got = _red(root, man, cmd)
        basis = json.dumps(got.get("redFirst") or got.get("note"))
        check("%s a new test file that asserts nothing, with %s, does not get HEAD's "
              "red credited: exit=%r %s" % (cid, how, code, basis[:300]),
              code == M.E_CANNOT_PROVE)
    fixing = "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                        "class New(unittest.TestCase):", "    def test_new(self):",
                        "        self.assertEqual(mine.v, 2)"]) + "\n"
    root, man = _reach_repo("stamp-red-reach-new-", new_text=fixing,
                            old_text=_OLD_RED.replace("assertEqual(mine.v, 2)",
                                                      "assertTrue(mine.v >= 1)"))
    code_n, got_n = _red(root, man, unit + ["tests/test_new.py"])
    basis_n = (got_n.get("redFirst") or {}).get("basis", "")
    check("sr149 THE ALLOW CASE: a new test file whose own case fails on HEAD's code "
          "and passes with the fix proves - its stub baseline is green, and the "
          "failure is located in it: exit=%r %s" % (code_n, basis_n[:300]),
          code_n == M.E_PROVED and "test_new" in basis_n)
    by_package = "\n".join(["import unittest", "from tests.test_old import Old",
                            "class New(unittest.TestCase):", "    def test_new(self):",
                            "        self.assertTrue(True)"]) + "\n"
    loading = "\n".join(["import unittest", "class New(unittest.TestCase):",
                         "    def test_new(self):", "        self.assertTrue(True)",
                         "def load_tests(loader, tests, pattern):",
                         "    import tests.test_old as o",
                         "    tests.addTests(loader.loadTestsFromModule(o))",
                         "    return tests"]) + "\n"
    same_name = "\n".join(["import unittest", "from tests import test_old",
                           "class New(test_old.Old):", "    def test_new(self):",
                           "        self.assertTrue(True)",
                           "class Other(unittest.TestCase):",
                           "    def test_value_is_two(self):",
                           "        self.assertTrue(True)"]) + "\n"
    declared_old = [
        ("sr157", "imports HEAD's red class from a DECLARED, unchanged test file",
         by_package, True, "unchanged"),
        ("sr158", "adds a DECLARED, unchanged test module through load_tests",
         loading, True, "unchanged"),
        ("sr159", "inherits HEAD's red case while an unrelated class defines one of "
         "the same name", same_name, False, "class New"),
    ]
    for cid, how, new_text, declare, why in declared_old:
        root, man = _reach_repo("stamp-red-%s-" % (cid,), new_text=new_text,
                                declare_old=declare)
        code, got = _red(root, man, unit + ["tests/test_new.py"])
        basis = (got.get("redFirst") or {}).get("basis", "") or json.dumps(got)
        check("%s a new test file that %s does not get HEAD's red credited, and the "
              "basis says why: exit=%r %s" % (cid, how, code, basis[:400]),
              code == M.E_CANNOT_PROVE and why in basis)
    two = "%s -m unittest -v tests/test_old.py; %s -m unittest -v tests/test_new.py" % (
        _sh_word(py), _sh_word(py))
    root_z, man_z = _reach_repo("stamp-red-sr160-", new_text=fixing, declare_old=True)
    code_z, got_z = _red(root_z, man_z, ["sh", "-c", two, "--", "-m", "unittest"],
                         "--case", "test_value_is_two")
    basis_z = (got_z.get("redFirst") or {}).get("basis", "") or json.dumps(got_z)
    check("sr160 HEAD's red run followed by the stub's empty one is not a green "
          "baseline behind exit 5 - HEAD's red case is not credited: exit=%r %s"
          % (code_z, basis_z[:400]),
          code_z == M.E_CANNOT_PROVE and "narrow" in basis_z)
    root_d, man_d = _reach_repo("stamp-red-sr161-", new_text=fixing,
                                old_text=_OLD_RED.replace("assertEqual(mine.v, 2)",
                                                          "assertTrue(mine.v >= 1)"))
    code_d, got_d = _red(root_d, man_d, [py, "-m", "unittest", "discover", "-s",
                                         "tests", "-v"])
    basis_d = (got_d.get("redFirst") or {}).get("basis", "") or json.dumps(got_d)
    check("sr161 THE ALLOW CASE: `unittest discover -s tests` prints the new module "
          "as `test_new`, which names the one declared tests/test_new.py by its "
          "dotted suffix - the new red case proves: exit=%r %s"
          % (code_d, basis_d[:400]),
          code_d == M.E_PROVED and "test_new" in basis_d)
    green_old = _OLD_RED.replace("assertEqual(mine.v, 2)", "assertTrue(mine.v >= 1)")
    root_e, man_e = _reach_repo("stamp-red-reach-edit-", new_text=_NEW_TRIVIAL,
                                old_text=green_old, declare_old=True,
                                wt_old=_OLD_RED)
    code_e, got_e = _red(root_e, man_e, unit + ["tests/test_new.py",
                                               "tests/test_old.py"])
    basis_e = (got_e.get("redFirst") or {}).get("basis", "")
    check("sr150 THE ALLOW CASE: a command naming a new test file AND an edited old "
          "one still gets a green baseline - the new file a stub, the old one "
          "HEAD's - and the edited case proves: exit=%r %s" % (code_e, basis_e[:300]),
          code_e == M.E_PROVED and "test_value_is_two" in basis_e)


def _located_cases(check):
    py = sys.executable
    tests = ["tests/test_new.py"]
    unit = [py, "-m", "unittest", "-v", "tests/test_new.py"]
    root = os.path.join(os.sep, "abs", "repo")
    rows = {
        "a pytest node id in the new file": (
            {"label": "tests/test_new.py::New::test_x"}, "pytest", ["pytest"],
            tests, "tests/test_new.py"),
        "a pytest node id into HEAD's old file": (
            {"label": "tests/test_old.py::Old::test_value_is_two"}, "pytest",
            ["pytest"], tests, None),
        "a pytest node id relative to a rootdir under tests/": (
            {"label": "test_new.py::test_x"}, "pytest", ["pytest"], tests,
            "tests/test_new.py"),
        "unittest -v locating the new module": (
            {"module": "tests.test_new"}, "unittest", unit, tests, "tests/test_new.py"),
        "unittest discover -s tests, the module relative to tests/": (
            {"module": "test_new"}, "unittest", unit, tests, "tests/test_new.py"),
        "a bare module two declared files end with": (
            {"module": "test_new"}, "unittest", unit,
            ["a/test_new.py", "b/test_new.py"], None),
        "unittest -v locating HEAD's module (imported)": (
            {"module": "test_old"}, "unittest", unit, tests, None),
        "unittest with no location": ({"module": None}, "unittest", unit, tests, None),
        "unittest __main__ of the one declared script": (
            {"module": "__main__"}, "unittest", [py, "tests/test_new.py", "-v"], tests,
            "tests/test_new.py"),
        "__main__ of the script spelled ./": (
            {"module": "__main__"}, "unittest", [py, "./tests/test_new.py"], tests,
            "tests/test_new.py"),
        "__main__ of the script spelled absolute under the repository": (
            {"module": "__main__"}, "unittest",
            [py, os.path.join(root, "tests", "test_new.py")], tests,
            "tests/test_new.py"),
        "__main__ of `python -m tests.test_new`": (
            {"module": "__main__"}, "unittest", [py, "-m", "tests.test_new"], tests,
            "tests/test_new.py"),
        "a house run of the one declared script": (
            {}, "house", [py, "tests/test_new.py"], tests, "tests/test_new.py"),
        "a house run through a runner": (
            {}, "house", [py, "-m", "runner"], tests, None),
        "a house run under `-m unittest`": (
            {}, "house", [py, "-m", "unittest", "tests/test_new.py"], tests, None),
    }
    got = dict((k, (M.case_site(f, runner, declared, cmd, (root,)) or (None,))[0])
               for k, (f, runner, cmd, declared, _w) in rows.items())
    shared = ["legacy/test_new.py", "tests/test_old.py"]
    tails = {
        "a tail an undeclared HEAD file shares": M.case_site(
            {"module": "test_new", "qual": ["test_new", "New"]}, "unittest", tests,
            unit, (root,), shared),
        "the full module, when another HEAD file ends with it": M.case_site(
            {"module": "tests.test_new", "qual": ["tests", "test_new", "New"]},
            "unittest", tests, unit, (root,), ["legacy/tests/test_new.py"]),
        "the full module, no other file ending with it": M.case_site(
            {"module": "tests.test_new", "qual": ["tests", "test_new", "New"]},
            "unittest", tests, unit, (root,), shared),
        "a pytest node id's real path, whatever else ends with it": M.case_site(
            {"label": "tests/test_new.py::New::test_x", "id": "test_x"}, "pytest",
            tests, ["pytest"], (root,), ["legacy/tests/test_new.py"]),
        "a tail no other HEAD file shares": M.case_site(
            {"module": "test_new", "qual": ["test_new", "New"]}, "unittest", tests,
            unit, (root,), ["tests/test_old.py"]),
        "a nested class, the module the longest declared prefix": M.case_site(
            {"module": "tests.test_new.Outer",
             "qual": ["tests", "test_new", "Outer", "Inner"], "id": "test_x"},
            "unittest", tests, unit, (root,), ()),
    }
    tails = dict((k, v and (v[0], v[1])) for k, v in tails.items())
    walk_root = _harness.fixture_root("stamp-walk-")
    for rel in (".git/objects/x", "legacy/test_new.py", "top.py"):
        path = os.path.join(walk_root, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        _write(path, "")
    walked = sorted(M._throwaway_files(walk_root))
    binds = [
        ("New.maxDiff = None", "New", False),
        ("REG[New] = 1", "New", False),
        ("test_x.__doc__ = 'x'", "test_x", False),
        ("del New.x", "New", False),
        ("x: int", "x", False),
        ("x: int = 1", "x", True),
        ("a, *test_x = (1, 2)", "test_x", True),
        ("[a, (b, test_x)] = [1, (2, 3)]", "test_x", True),
        ("(test_x := 1)", "test_x", True),
        ("print([(test_x := i) for i in range(2)])", "test_x", True),
        ("f = lambda: (test_x := 1)", "test_x", False),
        ("with open('f') as test_x:\n    pass", "test_x", True),
        ("with open('f') as (a, test_x):\n    pass", "test_x", True),
        ("for test_x in range(2):\n    pass", "test_x", True),
        ("for i in range(2):\n    test_x = i", "test_x", False),
        ("print([test_x for test_x in range(2)])", "test_x", False),
        ("import os.path as test_x", "test_x", True),
        ("import test_x.sub", "test_x", True),
        ("from m import *", "test_x", True),
        ("del test_x", "test_x", True),
        ("@(test_x := deco)\ndef f():\n    pass", "test_x", True),
        ("if True:\n    (test_x := 1)", "test_x", False),
        ("try:\n    (test_x := 1)\nexcept Exception:\n    pass", "test_x", False),
    ]
    if sys.version_info >= (3, 10):
        binds += [
            ("match v:\n    case [test_x, *_]:\n        pass", "test_x", True),
            ("match v:\n    case {'k': 1, **test_x}:\n        pass", "test_x", True),
            ("match v:\n    case int() as test_x:\n        pass", "test_x", True),
            ("match v:\n    case Point(x=test_x.y):\n        pass", "test_x", False),
        ]
    wrong = [(src, name, want) for src, name, want in binds
             if M._binds(ast.parse(src).body[0], name) != want]
    check("sr182 only a real binding of the name counts - a Name target through "
          "tuples, lists and starred, never under an attribute or subscript; a walrus "
          "outside a nested scope; `with ... as`, a `for` target, a match capture, "
          "an import, a def, a class, a `del` - so `New.maxDiff = None` rebinds "
          "nothing: %d rows, wrong %r" % (len(binds), wrong), not wrong)
    suite_text = "import sys\nprint('ALL PASS: 1/1 cases passed')\n"
    head_modules = {M.module_key(suite_text): "tests/test_hold.py"}

    def house(text, modules):
        scope = {"tests": ["tests/test_h.py"], "cmd": [py, "tests/test_h.py"],
                 "roots": (root,), "wt": {"tests/test_h.py": text},
                 "head_defs": {}, "head_modules": modules, "others": ()}
        return M.credit_problem({"id": None, "label": "x"}, "house", scope)
    housed = {
        "identical to a HEAD suite": house(suite_text, head_modules),
        "the same module, a comment and blank lines added": house(
            "# moved\n\n" + suite_text, head_modules),
        "a suite of its own": house(suite_text + "print('new1')\n", head_modules),
        "HEAD's tree unread": house(suite_text + "print('new1')\n", None),
    }
    check("sr183 a house run's script is compared whole with HEAD's test files by "
          "module ast - identical or differing only in layout is HEAD's suite, an "
          "edited one is its own, and an unread HEAD refuses: %r" % (housed,),
          bool(housed["identical to a HEAD suite"])
          and "HEAD's tests/test_hold.py" in housed["identical to a HEAD suite"]
          and bool(housed["the same module, a comment and blank lines added"])
          and housed["a suite of its own"] is None
          and bool(housed["HEAD's tree unread"]))
    base = "class New:\n    def test_x(self):\n        pass\n"
    nested = ("class Outer:\n    class Inner:\n        def test_x(self):\n"
              "            pass\n")
    replacing = [
        ("the case's own attribute replaced", base + "New.test_x = f\n", ["New"], False),
        ("replaced through a tuple target", base + "(New.test_x, a) = (f, 1)\n",
         ["New"], False),
        ("replaced by an augmented assignment", base + "New.test_x += f\n", ["New"],
         False),
        ("replaced by an annotated assignment", base + "New.test_x: object = f\n",
         ["New"], False),
        ("setattr with the literal name", base + "setattr(New, 'test_x', f)\n",
         ["New"], False),
        ("setattr inside an assignment", base + "_ = setattr(New, 'test_x', f)\n",
         ["New"], False),
        ("a nested chain replaced at module level",
         nested + "Outer.Inner.test_x = f\n", ["Outer", "Inner"], False),
        ("a nested chain replaced in the outer class body",
         nested.replace("            pass\n", "            pass\n    Inner.test_x = f\n"),
         ["Outer", "Inner"], False),
        ("another attribute of the class", base + "New.maxDiff = None\n", ["New"],
         True),
        ("the same name on another class", base + "Other.test_x = f\n", ["New"], True),
        ("a longer path through the case", base + "New.test_x.__doc__ = 'x'\n",
         ["New"], True),
        ("setattr with a computed name", base + "setattr(New, 'test_' + 'x', f)\n",
         ["New"], True),
        ("setattr on another object", base + "setattr(Other, 'test_x', f)\n", ["New"],
         True),
    ]
    wrong = [(k, want) for k, text, chain, want in replacing
             if (M._definition(text, chain, "test_x") is not None) != want]
    check("sr186 once the chain resolves, a later assignment to the attribute "
          "<chain>.<case> - plain, through a tuple, augmented or annotated - or a "
          "`setattr(<chain>, '<case>', ...)` with that literal name replaces the def, "
          "at module level or in an enclosing class; any other attribute, another "
          "object, a longer path and a computed name do not: %d rows, wrong %r"
          % (len(replacing), wrong), not wrong)
    check("sr174 the throwaway's own files are listed for that refusal - relative, "
          "`/`-separated, `.git` left out: %r" % (walked,),
          walked == ["legacy/test_new.py", "top.py"])
    check("sr173 a unittest module - read through sys.path, so exact or trailing "
          "alike - is refused when an undeclared file in HEAD's tree shares its "
          "tail; a pytest node id is a real path and is not; and a nested class "
          "keeps its chain: %r" % (tails,),
          tails == {"a tail an undeclared HEAD file shares": None,
                    "the full module, when another HEAD file ends with it": None,
                    "the full module, no other file ending with it": (
                        "tests/test_new.py", ["New"]),
                    "a pytest node id's real path, whatever else ends with it": (
                        "tests/test_new.py", ["New"]),
                    "a tail no other HEAD file shares": ("tests/test_new.py", ["New"]),
                    "a nested class, the module the longest declared prefix": (
                        "tests/test_new.py", ["Outer", "Inner"])})
    check("sr151 a failure is located in the ONE declared test file the runner's "
          "location names - a pytest node id's path or unittest -v's module, matched "
          "by trailing components, or the one declared script a house or `__main__` "
          "run executes, spelled any way: %r" % (got,),
          got == dict((k, w) for k, (_f, _r, _c, _d, w) in rows.items()))
    new_text = "\n".join([
        "import unittest", "from tests import test_old", 'DOC = """',
        "def test_value_is_two(self):", '"""', "class New(test_old.Old):",
        "    def test_new(self):", "        pass", "class Other(unittest.TestCase):",
        "    def test_value_is_two(self):", "        pass", "def test_mine(x):",
        "    assert x"]) + "\n"
    old_head = "\n".join(["import unittest", "class Old(unittest.TestCase):",
                          "    def test_value_is_two(self):",
                          "        self.assertEqual(1, 2)"]) + "\n"
    both = ["tests/test_new.py", "tests/test_old.py"]

    def credit(failure, runner, wt_old=old_head, head_old=old_head, wt_new=new_text):
        defs = (None if head_old is None
                else M.test_definitions({"tests/test_old.py": head_old}))
        scope = {"tests": both, "cmd": unit, "roots": (root,),
                 "wt": {"tests/test_new.py": wt_new, "tests/test_old.py": wt_old},
                 "head_defs": defs, "others": ()}
        return M.credit_problem(failure, runner, scope)

    def ut(module, cls, name="test_value_is_two"):
        return {"id": name, "label": name, "module": module, "cls": cls}

    def pt(node):
        return {"id": node.split("::")[-1], "label": node}

    credits = {
        "an inherited unittest case, another class defining the name": credit(
            ut("tests.test_new", "New"), "unittest"),
        "the same through a pytest node id": credit(
            pt("tests/test_new.py::New::test_value_is_two"), "pytest"),
        "a module-level def that is only inside a string": credit(
            pt("tests/test_new.py::test_value_is_two"), "pytest"),
        "the unrelated class's own case": credit(
            pt("tests/test_new.py::Other::test_value_is_two"), "pytest"),
        "a parametrized module-level case of the new file": credit(
            pt("tests/test_new.py::test_mine[1]"), "pytest"),
        "HEAD's case, unchanged, in a declared existing file": credit(
            ut("tests.test_old", "Old"), "unittest"),
        "HEAD's case edited in a declared existing file": credit(
            ut("tests.test_old", "Old"), "unittest",
            wt_old=old_head.replace("(1, 2)", "(1, 3)")),
        "a case added to a declared existing file": credit(
            ut("tests.test_old", "Old", "test_added"), "unittest",
            wt_old=old_head + "    def test_added(self):\n        self.fail()\n"),
        "a declared existing file whose HEAD copy could not be read": credit(
            ut("tests.test_old", "Old"), "unittest", head_old=None),
        "HEAD's case copied verbatim into the new file": credit(
            ut("tests.test_new", "Old"), "unittest", wt_new=old_head),
        "a def rebound by an import alias after it": credit(
            pt("tests/test_new.py::test_mine"), "pytest",
            wt_new=new_text + "from os import sep as test_mine\n"),
        "a def rebound by an annotated assignment after it": credit(
            pt("tests/test_new.py::test_mine"), "pytest",
            wt_new=new_text + "test_mine: object = None\n"),
        "a def deleted after it": credit(
            pt("tests/test_new.py::test_mine"), "pytest",
            wt_new=new_text + "del test_mine\n"),
        "a class rebound by an assignment after it": credit(
            pt("tests/test_new.py::Other::test_value_is_two"), "pytest",
            wt_new=new_text + "Other = test_old.Old\n"),
        "a def rebound BEFORE it, the def the last binding": credit(
            pt("tests/test_new.py::test_mine"), "pytest",
            wt_new="test_mine = None\n" + new_text),
    }
    credited = ("the unrelated class's own case",
                "a parametrized module-level case of the new file",
                "HEAD's case edited in a declared existing file",
                "a case added to a declared existing file",
                "a def rebound BEFORE it, the def the last binding")
    check("sr154 a located case is the task's only when the class the runner names "
          "holds its def as its last binding (read by ast - a def in a string, in "
          "another class, or rebound after it is not it) and no HEAD test file holds "
          "an identical def under that class and name: %r" % (credits,),
          all(credits[k] is None for k in credited)
          and all(credits[k] for k in credits if k not in credited)
          and "HEAD's" in credits["HEAD's case, unchanged, in a declared existing "
                                   "file"]
          and "HEAD's tests/test_old.py" in credits[
              "HEAD's case copied verbatim into the new file"])
    gone = _harness.fixture_root("stamp-deadline-")
    late, copied = M._isolated_run(gone, os.path.join(gone, "no-tree"), [], [py, "-c", ""],
                                   time.time() + 0.5, 30, {}, gone, "late")
    check("sr155 with less than a second of the deadline left no run is made - not "
          "even the reset's git calls - and the problem is the run's own, naming the "
          "--timeout it spent, not the reset's: %r %r" % (late, copied),
          late["code"] is None
          and "no time was left of the 30-second deadline" in (late["problem"] or "")
          and copied == [])
    real = subprocess.run([py, "-m", "unittest", "-v", "test_u"], cwd=_where_unittest(),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True).stdout
    mods = sorted(set(c.get("module") for c in M.failing_cases(real, "unittest")))
    check("sr152 a real unittest -v run gives each failing case its module: %r"
          % (mods,), mods == ["test_u"])
    twin = ("FAIL: test_value_is_two (test_old.Old.test_value_is_two)\n"
            "FAIL: test_value_is_two (tests.test_new.New.test_value_is_two)\n"
            "\n----\nRan 2 tests in 0.001s\n\nFAILED (failures=2)\n")
    both = [(c.get("module"), c.get("cls")) for c in M.failing_cases(twin, "unittest")]
    old_style = [(c.get("module"), c.get("cls")) for c in M.failing_cases(
        "FAIL: test_value_is_two (tests.test_new.New)\n\n----\nRan 1 test in 0.0s"
        "\n\nFAILED (failures=1)\n", "unittest")]
    check("sr156 two failing cases of one name in two modules keep a module and a "
          "class each - the imported one HEAD's, the inherited one the subclass's - "
          "and a pre-3.11 line gives the same: %r %r" % (both, old_style),
          both == [("test_old", "Old"), ("tests.test_new", "New")]
          and old_style == [("tests.test_new", "New")])
    calls = []
    lefts = [5, 0]
    real_git, real_left = M._git, M._left
    M._git = lambda path, args, timeout=120, strip=True: calls.append(args) or (0, "")
    M._left = lambda deadline: lefts.pop(0) if lefts else 0
    try:
        floor = M._isolate("/nowhere", 0)
    finally:
        M._git, M._left = real_git, real_left
    check("sr162 the one-second floor is checked before EACH of the reset's git "
          "calls: with a second left for the first and none for the second, only the "
          "first is started: %r %r" % (calls, floor),
          len(calls) == 1 and "no time was left" in (floor or ""))


def _where_unittest():
    where = _harness.fixture_root("stamp-unittest-where-")
    _write(os.path.join(where, "test_u.py"), "\n".join([
        "import unittest", "", "", "class T(unittest.TestCase):",
        "    def test_assert(self):", "        self.assertEqual(1, 2)", "",
        "    def test_raise(self):", "        raise TypeError('a body that raised')",
        ""]))
    return where


def _path_red(prefix, rel, head, wt, cmd=None):
    """`(exit, basis)` of a red whose declared test file is `rel`."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    _write(os.path.join(root, *rel.split("/")), head)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "test")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    _write(os.path.join(root, *rel.split("/")), wt)
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", rel]
    task["tests"] = {"mode": "tdd", "add": [rel + ": v is two"]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    code, got = _red(root, man, cmd or [sys.executable, rel])
    return code, json.dumps(got.get("redFirst") or got.get("note") or got)


_FAILFAST_HEAD = ["    def test_a_p(self):", "        self.assertEqual(mine.v, 5)",
                  "    def test_b_f(self):", "        self.assertEqual(mine.v, 7)"]
_FAILFAST_WT = ["    def test_a_p(self):", "        self.assertEqual(mine.v, 1)",
                "    def test_b_f(self):", "        self.assertEqual(mine.v, 7)"]


def _unit_main(failfast):
    return "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                      "class T(unittest.TestCase):",
                      "    def test_a_p(self):", "        self.assertEqual(mine.v, 5)",
                      "    def test_b_f(self):", "        self.assertEqual(mine.v, 7)",
                      "if __name__ == '__main__':",
                      "    unittest.main(%s)" % ("failfast=True" if failfast else "")]
                     ) + "\n"


def _quiet_stop(stop):
    return ["STOP = %s" % (stop,), "ok = mine.v == 2",
            "check('the value is two', ok, 'saw %r' % (mine.v,))",
            "if not (STOP and not ok):",
            "    check('the legacy field is kept', mine.v == 99, 'saw %r' % (mine.v,))"]


def _unit_suite(methods):
    return "\n".join(["import os, sys, unittest", _PATH_LINE, "import mine",
                      "class T(unittest.TestCase):"] + list(methods)
                     + ["if __name__ == '__main__':", "    unittest.main()"]) + "\n"


def _crlf_cases(check):
    """The throwaway holds HEAD's bytes whatever the configs around it say."""
    root = _seeded_repo("stamp-crlf-")
    committed = b"x = 1\n\n\n"
    with open(os.path.join(root, "src", "lf.py"), "wb") as fh:
        fh.write(committed)
    _git(root, "add", "src/lf.py")
    _git(root, "commit", "-q", "-m", "lf")
    # The repository's own config, which no environment scrub can drop: the
    # shape a Windows machine's system config takes once git reads it.
    _git(root, "config", "core.autocrlf", "true")
    path = os.path.join(_harness.fixture_root("stamp-crlf-tree-"), "tree")
    built, problem = M._build_throwaway(root, path, [])
    target = os.path.join(path, "src", "lf.py")
    try:
        with open(target, "rb") as fh:
            after_add = fh.read()
        with open(target, "wb") as fh:
            fh.write(b"x = 2\r\n")
        reset = M._isolate(path, time.time() + 30)
        with open(target, "rb") as fh:
            after_reset = fh.read()
    finally:
        _git(root, "worktree", "remove", "--force", path)
    check("sr187 a repository whose config sets core.autocrlf still gets HEAD's "
          "bytes in the throwaway, both when it is built and when it is reset - a "
          "checkout rewriting line endings would grade bytes HEAD does not hold: "
          "%r" % ((problem, after_add, reset, after_reset),),
          problem is None and reset is None and built == []
          and after_add == committed and after_reset == committed)


def _listing_cases(check):
    """Whether git still lists a throwaway is a comparison of PATHS."""
    real = os.path.realpath(_harness.fixture_root("stamp-listed-"))
    holder = os.path.join(real, M.THROWAWAY_PREFIX + "x")
    path = os.path.join(holder, "tree")
    link = os.path.join(_harness.fixture_root("stamp-listed-link-"), "link")
    try:
        os.symlink(real, link)
        linked = None
    except (OSError, NotImplementedError) as exc:
        linked = exc
    real_git = M._git

    def removed_given(listed_as):
        os.makedirs(path)
        listing = "worktree %s\nHEAD %s\ndetached\n" % (listed_as, "a" * 40)

        def fake(where, args, timeout=120, strip=True):
            if args[:2] == ["worktree", "list"]:
                return 0, listing
            return 1, "fatal: refused"
        M._git = fake
        try:
            return M._remove_throwaway(real, holder, path)
        finally:
            M._git = real_git
    if linked is not None:
        _harness.skip(check, "sr188 a throwaway git lists by another spelling is "
                      "not reported removed", "symlink", True)
    else:
        spelled = os.path.join(link, M.THROWAWAY_PREFIX + "x", "tree")
        check("sr188 a throwaway git still lists, under ANOTHER spelling of the "
              "same directory (here a symlink; on Windows forward slashes and a "
              "long name against a short one), is not reported removed: %r"
              % (spelled,), removed_given(spelled) is False)
    # The second direction, for a comparison widened until everything matches:
    # a sibling whose path merely BEGINS with this one is not this throwaway.
    check("sr189 THE ALLOW CASE: a listing naming only a sibling whose path "
          "begins with this throwaway's does not keep it listed - it was "
          "removed: %r" % (path + "-other",),
          removed_given(path + "-other") is True)
    win_listing = ("worktree C:/Users/runneradmin/work/repo\nHEAD %s\nbranch "
                   "refs/heads/main\n\nworktree C:/Users/runneradmin/AppData/Local/"
                   "Temp/audit-red-x/tree\nHEAD %s\ndetached\n" % ("b" * 40, "b" * 40))
    native = "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\audit-red-x\\tree"

    def as_windows(p):
        return ntpath.normcase(ntpath.normpath(p)).replace("runner~1", "runneradmin")
    check("sr190 git's porcelain spelling and a native Windows spelling of one "
          "tree compare equal under Windows' resolution, and a different tree "
          "does not: %r" % (native,),
          M.still_listed(win_listing, native, as_windows) is True
          and M.still_listed(win_listing, native + "2", as_windows) is False)


def _holder_cases(check):
    """The throwaway's temp directory, when the configured one is inside the repo."""
    root = _seeded_repo("stamp-holder-")
    inside = os.path.join(root, "untracked-tmp")
    os.makedirs(inside)
    outside = _harness.fixture_root("stamp-holder-out-")
    # Two outside homes, each with the Temp the Windows branch names, so which
    # of them answers says which the branch put first.
    local = _harness.fixture_root("stamp-holder-local-")
    system = _harness.fixture_root("stamp-holder-system-")
    for base in (local, system):
        os.makedirs(os.path.join(base, "Temp"))
    all_inside = {"TMPDIR": inside, "TEMP": inside, "TMP": inside}
    windows = dict(all_inside, LOCALAPPDATA=local, SystemRoot=system)
    held = tempfile.tempdir
    try:
        tempfile.tempdir = outside
        preferred = M.holder_base(root, "nt", {"TEMP": outside})
        tempfile.tempdir = inside
        fallback = M.holder_base(root, "nt", {"TEMP": outside})
        platform_only = M.holder_base(root, "nt", windows)
        env_first = M.holder_base(root, "nt", dict(windows, TEMP=outside))
        posix = M.holder_base(root, "posix", dict(all_inside, LOCALAPPDATA=local))
    finally:
        tempfile.tempdir = held
    real_root = os.path.realpath(root) + os.sep
    check("sr191 on Windows too, a temp directory inside the repository is passed "
          "over for one outside it, while an outside one is still used first: "
          "%r" % ((preferred, fallback),),
          preferred == outside and fallback is not None
          and not (os.path.realpath(fallback) + os.sep).startswith(real_root))
    check("sr192 on Windows with the temp directory and every temp variable "
          "inside the repository, the per-user Temp under LOCALAPPDATA answers, "
          "ahead of the system one: %r" % (platform_only,),
          platform_only == os.path.join(local, "Temp"))
    check("sr193 THE ALLOW CASE: on Windows an outside TEMP still answers before "
          "the platform's own directories: %r" % (env_first,),
          env_first == outside)
    posix_dirs = M._platform_temp_dirs("posix", {"LOCALAPPDATA": local,
                                                 "SystemRoot": system})
    check("sr194 THE ALLOW CASE: off Windows the Windows entries are never "
          "consulted, even with LOCALAPPDATA set: %r" % ((posix_dirs, posix),),
          posix_dirs == ["/tmp", "/var/tmp"]
          and posix != os.path.join(local, "Temp"))


# What `npm test` prints when its script reached no test runner at all, with
# npm's update notice after it. No tally reader and no error reader matches
# any of it, and none of it is a jest or vitest summary either, so the case
# keeps holding when those runners get readers of their own.
_UNREAD_NPM = (
    "\n> app@1.0.0 test\n> ./scripts/run-suite.sh\n\n"
    "the suite script stopped before it started a runner\n"
    "npm notice\n"
    "npm notice New major version of npm available! 10.8.2 -> 11.6.1\n"
    "npm notice Changelog: https://github.com/npm/cli/releases/tag/v11.6.1\n"
    "npm notice To update run: npm install -g npm@11.6.1\n"
    "npm notice\n")


def _unread_basis(code, text, cmd):
    """The basis `red_verdict` writes for a run made with no HEAD baseline."""
    run = {"cmd": cmd, "code": code, "text": text, "problem": None,
           "second": None, "head": None, "fix": None}
    ctx = {"root": None, "implementation": [], "tests": ["tests/test_mine.py"],
           "cases": [], "symbols": [], "dropped": [], "new": [],
           "head_files": None, "head_defs": None, "head_modules": None,
           "path": None}
    return (M.red_verdict(run, ctx)[2] or {}).get("basis", "")


def _decisive_cases(check):
    verdict = M.classify_run(1, _UNREAD_NPM, ["npm", "test"])[0]
    basis = _unread_basis(1, _UNREAD_NPM, ["npm", "test"])
    quoted = [ln for ln in _UNREAD_NPM.splitlines() if ln.strip() and ln in basis]
    check("sr195 a run no tally or error reader matches, ending in npm's update "
          "notice, gets a basis that says no reader matched and quotes none of "
          "its lines as the decisive one - position is not a cause: verdict %r, "
          "quoted %r, basis %r" % (verdict, quoted, basis),
          verdict == M.V_NO_TALLY and not quoted
          and "no tally or error reader matched" in basis)
    pytest_basis = _unread_basis(1, _PYTEST_FULL, [sys.executable, "-m", "pytest"])
    tally_line = "========================= 2 failed, 1 passed in 0.01s " \
                 "=========================="
    check("sr196 THE ALLOW CASE for sr195: a run whose pytest tally is read still "
          "quotes that tally line as decisive, and says nothing of an unread run: "
          "%r" % (pytest_basis,),
          pytest_basis.endswith(" - %s; run without nothing" % (tally_line,))
          and "reader matched" not in pytest_basis)
    traceback = ("Traceback (most recent call last):\n"
                 "  File \"tests/test_mine.py\", line 1, in <module>\n"
                 "ModuleNotFoundError: No module named 'mine'\n"
                 "npm notice New major version of npm available! 10.8.2 -> 11.6.1\n")
    error_basis = _unread_basis(1, traceback, ["npm", "test"])
    check("sr197 THE ALLOW CASE for sr195: a run whose final Error line is read "
          "still quotes that line as decisive, not the banner printed after it: "
          "%r" % (error_basis,),
          ": ModuleNotFoundError: No module named 'mine'; " in error_basis
          and "npm notice" not in error_basis
          and "reader matched" not in error_basis)


# What jest 30 prints, under `npx jest`, for one test whose `expect` failed: a
# `FAIL <path>` header, the case's bullet, the matcher hint under it, and the
# `Tests:` summary. The command is a wrapper and names no runner, so only the
# output can say this was jest.
_JEST_ASSERT = (
    " FAIL  tests/add.test.js\n"
    "  ● adds two numbers\n\n"
    "    expect(received).toBe(expected) // Object.is equality\n\n"
    "    Expected: 3\n"
    "    Received: -1\n\n"
    "      3 | test('adds two numbers', () => {\n"
    "    > 4 |   expect(add(1, 2)).toBe(3);\n"
    "        |                     ^\n\n"
    "      at Object.toBe (tests/add.test.js:4:21)\n\n"
    "Test Suites: 1 failed, 1 total\n"
    "Tests:       1 failed, 1 total\n"
    "Snapshots:   0 total\n"
    "Time:        0.31 s\n"
    "Ran all test suites.\n")
# ...and for a suite that never loaded: no case ran, so the only bullet is the
# failed-to-run heading, with its cause on the line under it.
_JEST_NO_SUITE = (
    " FAIL  tests/add.test.js\n"
    "  ● Test suite failed to run\n\n"
    "    Cannot find module '../src/add' from 'tests/add.test.js'\n\n"
    "Test Suites: 1 failed, 1 total\n"
    "Tests:       0 total\n"
    "Snapshots:   0 total\n"
    "Time:        0.2 s\n"
    "Ran all test suites.\n")


def _jest_cases(check):
    cmd = ["npx", "jest"]
    verdict, tally = M.classify_run(1, _JEST_ASSERT, cmd)
    cases = [(c.get("label"), c.get("assertion"))
             for c in M.failing_cases(_JEST_ASSERT)]
    check("sr198 a jest `expect` failure under `npx jest` reads as red, its tally "
          "jest's own `Tests:` line, with the bullet's case named and its "
          "assertion flag true - it read as no-tally: %r %r %r"
          % (verdict, tally, cases),
          verdict == M.V_RED and (tally or {}).get("runner") == "jest"
          and (tally or {}).get("collected") == 1
          and (tally or {}).get("assertions") == 1
          and cases == [("adds two numbers", True)])
    verdict_s, tally_s = M.classify_run(1, _JEST_NO_SUITE, cmd)
    cases_s = [(c.get("label"), c.get("assertion"))
               for c in M.failing_cases(_JEST_NO_SUITE)]
    code_s, _v, block_s, _n = M.red_verdict(
        {"cmd": cmd, "code": 1, "text": _JEST_NO_SUITE, "problem": None,
         "second": None, "head": None, "fix": None},
        {"root": None, "implementation": [], "tests": ["tests/add.test.js"],
         "cases": [], "symbols": [], "dropped": [], "new": [],
         "head_files": None, "head_defs": None, "head_modules": None,
         "path": None})
    basis_s = (block_s or {}).get("basis", "")
    check("sr199 THE ALLOW CASE for sr198: a jest suite that failed to run is "
          "named, with its assertion flag false and counted as a failure no case "
          "ran, so the run is a collection error and red stays could-not-prove, "
          "quoting jest's own summary line: %r %r %r exit=%r %r"
          % (verdict_s, tally_s, cases_s, code_s, basis_s),
          verdict_s == M.V_COLLECT and (tally_s or {}).get("runner") == "jest"
          and (tally_s or {}).get("failed") == 1
          and cases_s == [("Test suite failed to run", False)]
          and code_s == M.E_CANNOT_PROVE
          and ": Tests:       0 total;" in basis_s)


# A jest test file as a task adds it: a comment and strings holding brackets and
# quotes that a text-level reading would misnest, a regex literal holding a
# paren, a template literal with a substitution, a `.each` whose title is a
# format jest fills in at run time, and a loop building titles from a template
# beside the literal test in the same describe.
_JS_NEW = "\n".join([
    "import { add } from '../src/add';",
    "// a comment with an apostrophe isn't a string ( {",
    "describe('math', () => {",
    "  const shape = /^\\(x\\)$/;",
    "  test('adds two numbers', () => {",
    "    expect(add(1, 2)).toBe(3); /* ) */",
    "    expect(`${add(1, {a: 1}.a)}`).toMatch(shape);",
    "  });",
    "  it.each([[1, 2]])('doubles %i', (a, b) => {",
    "    expect(add(a, a)).toBe(b);",
    "  });",
    "  for (const n of [1]) test(`loop ${n} done`, () => expect(n).toBe(n));",
    "});",
    "test(\"top ( level\", () => { expect('}').toBe('}'); });",
    ""])
# The same test file at HEAD, laid out differently and commented, which is no
# change to any test body.
_JS_HEAD_SAME = _JS_NEW.replace("expect(add(1, 2)).toBe(3); /* ) */",
                                "expect(add(1, 2))\n      .toBe(3); // layout")
_JS_EDITED = _JS_NEW.replace("toBe(3);", "toBe(4);")
_JS_OTHER = "test('something else', () => { expect(1).toBe(1); });\n"


def _jest_fail(path, chain, hint="expect(received).toBe(expected) // Object.is equality"):
    """What jest prints for one failing `expect` in `path`, its bullet the title
    chain joined the way jest joins it."""
    return (" FAIL  %s\n  ● %s\n\n    %s\n\n    Expected: 3\n    Received: -1\n\n"
            "Test Suites: 1 failed, 1 total\nTests:       1 failed, 1 passed, "
            "2 total\nSnapshots:   0 total\nTime:        0.31 s\n"
            % (path, " › ".join(chain), hint))


def _jest_credit(text, tests, wt, head, cmd=("npx", "jest")):
    """`credit_problem` of every assertion failure jest named in `text`, against
    `head` (`{rel: text}` of HEAD's test files; None when they could not be read)."""
    scope = {"tests": tests, "cmd": list(cmd), "roots": ("/repo",), "wt": wt,
             "head_defs": {}, "head_modules": {}, "others": (),
             "head_js": None if head is None else M.js_test_definitions(head)}
    return [M.credit_problem(f, "jest", scope)
            for f in M.failing_cases(text, "jest") if f["assertion"]]


def _jest_credit_cases(check):
    new = "tests/add.test.js"
    adds = _jest_fail(new, ["math", "adds two numbers"])
    head_green = {"code": 0, "problem": None,
                  "text": " PASS  tests/other.test.js\nTests:       1 passed, 1 total\n"}
    fix_green = {"code": 0, "problem": None,
                 "text": " PASS  tests/add.test.js\nTests:       2 passed, 2 total\n"}
    run = {"cmd": ["npx", "jest"], "code": 1, "text": adds, "problem": None,
           "second": None, "head": head_green, "fix": fix_green}
    root = _harness.fixture_root("stamp-jest-credit-")
    try:
        os.makedirs(os.path.join(root, "tests"))
        _write(os.path.join(root, new), _JS_NEW)
        ctx = {"root": root, "implementation": ["src/add.js"], "tests": [new],
               "cases": [], "symbols": [], "dropped": [], "new": [new],
               "head_files": ["src/add.js", "tests/other.test.js"],
               "head_defs": {}, "head_modules": {}, "path": None,
               "head_js": M.js_test_definitions({"tests/other.test.js": _JS_OTHER})}
        code, _v, block, _n = M.red_verdict(run, ctx)
        undefined = dict(run, text=_jest_fail(new, ["math", "subtracts"]))
        code_u, _v, block_u, _n = M.red_verdict(undefined, ctx)
        bare = dict(run, text=_jest_fail(new, ["adds two numbers"]))
        code_b, _v, block_b, _n = M.red_verdict(bare, ctx)
    finally:
        _harness.remove_tree(root)
    basis, basis_u, basis_b = [(b or {}).get("basis", "")
                               for b in (block, block_u, block_b)]
    check("sj1 a failing jest case whose title chain is new in a declared test file "
          "is credited to the task, and red proves it end to end: %r %r"
          % (code, basis),
          code == M.E_PROVED and "adds two numbers" in basis)
    check("sj2 THE DENY TWIN for sj1: the same file, a title chain it does not "
          "define - a describe-free bullet naming only the test's title, or a "
          "title under the describe that the file never writes - is not credited, "
          "so red stays could-not-prove: %r %r %r %r"
          % (code_u, basis_u, code_b, basis_b),
          code_u == M.E_CANNOT_PROVE and code_b == M.E_CANNOT_PROVE
          and "defines no test" in basis_u and "defines no test" in basis_b)
    wt = {new: _JS_NEW}
    same = _jest_credit(adds, [new], wt, {new: _JS_HEAD_SAME})
    edited = _jest_credit(adds, [new], {new: _JS_EDITED}, {new: _JS_HEAD_SAME})
    copied = _jest_credit(adds, [new], wt, {"tests/old.test.js": _JS_HEAD_SAME})
    unread = _jest_credit(adds, [new], wt, None)
    check("sj3 a failing jest case whose title chain and body are identical in "
          "HEAD's copy of a test file - layout and comments aside - is not "
          "credited, nor is one copied from another HEAD test file, nor any when "
          "HEAD's files could not be read; the same chain with a body the task "
          "edited is credited: same %r edited %r copied %r unread %r"
          % (same, edited, copied, unread),
          len(same) == 1 and same[0] and "HEAD's tests/add.test.js" in same[0]
          and edited == [None]
          and len(copied) == 1 and copied[0]
          and "HEAD's tests/old.test.js" in copied[0]
          and len(unread) == 1 and unread[0] and "could not be read" in unread[0])
    other = _jest_credit(_jest_fail("tests/other.test.js",
                                    ["math", "adds two numbers"]),
                         [new], {new: _JS_NEW}, {})
    nested = "packages/app/tests/add.test.js"
    suffix = _jest_credit(adds, [nested], {nested: _JS_NEW}, {})
    twice = _jest_credit(adds, [nested, "packages/lib/tests/add.test.js"],
                         {nested: _JS_NEW,
                          "packages/lib/tests/add.test.js": _JS_NEW}, {})
    check("sj4 a failure jest locates in a test file the task does not declare is "
          "not credited, nor one whose path is the tail of two declared files; "
          "THE ALLOW TWIN: the same failure in a declared file, printed relative "
          "to a package root, is located by its suffix and credited: other %r "
          "suffix %r twice %r" % (other, suffix, twice),
          len(other) == 1 and other[0] and "no declared test file" in other[0]
          and suffix == [None]
          and len(twice) == 1 and twice[0] and "no declared test file" in twice[0])
    each = _jest_credit(_jest_fail(new, ["math", "doubles 1"]), [new], wt, {})
    loop = _jest_credit(_jest_fail(new, ["math", "loop 1 done"]), [new], wt, {})
    top = _jest_credit(_jest_fail(new, ["top ( level"]), [new], wt, {})
    broken = "test('adds two numbers', () => { expect(1).toBe(1);\n"
    closed = _jest_credit(adds, [new], wt, {"tests/broken.test.js": broken})
    elsewhere = _jest_credit(adds, [new], wt, {"tests/broken.test.js":
                                               broken.replace("adds two", "x")})
    unbalanced = _jest_credit(adds, [new], {new: _JS_NEW + "})"}, {})
    check("sj5 a jest title built at run time (`.each`) is refused credit by name, "
          "a HEAD test file the reader cannot balance refuses a case whose title "
          "it holds, and an unbalanced declared file credits nothing; THE ALLOW "
          "TWINS: a literal title holding a bracket is credited, and an "
          "unreadable HEAD file NOT holding the title refuses nothing - and a "
          "template title built in a loop is refused while the literal test "
          "beside it stays credited (sj1): each %r loop %r top %r closed %r "
          "elsewhere %r unbalanced %r"
          % (each, loop, top, closed, elsewhere, unbalanced),
          len(each) == 1 and each[0] and "run time" in each[0]
          and len(loop) == 1 and loop[0] and "run time" in loop[0]
          and top == [None]
          and len(closed) == 1 and closed[0]
          and "tests/broken.test.js" in closed[0]
          and elsewhere == [None]
          and len(unbalanced) == 1 and unbalanced[0]
          and "could not be read as" in unbalanced[0])


# A jest-shaped runner, so a `red` over a jest project runs with no npm. Where
# its cwd has a `node_modules` it writes into `node_modules/.cache`, the way a
# real runner keeps its cache. It answers as jest 30 was observed to (the
# design note in stamp-verification.py):
# a named file that is empty fails to run, exit 1; no named file on disk is
# `No tests found, exiting with code 1`, exit 0 only under --passWithNoTests.
# A test is `test('<title>', () => { expect(<v() | int>).toBe(<int>); });`
# inside one `describe`, and `v()` is the value `src/mine.py` assigns. Its
# source is ASCII and its output is written as UTF-8 bytes, so the sweep's
# cp1252 pass reads the same bullets.
_FAKE_JEST = r'''import os, re, sys
TEST = re.compile(r"test\('([^']+)', \(\) => \{ expect\((v\(\)|\d+)\)\.toBe\((\d+)\); \}\);")
DESCRIBE = re.compile(r"describe\('([^']+)'")
def value(word):
    if word != "v()":
        return int(word)
    with open(os.path.join("src", "mine.py")) as fh:
        return int(fh.read().split("=")[1])
out = []
if os.path.isdir("node_modules"):
    os.makedirs(os.path.join("node_modules", ".cache", "fakejest"), exist_ok=True)
    open(os.path.join("node_modules", ".cache", "fakejest", "ran"), "w").close()
targets = [a for a in sys.argv[1:] if not a.startswith("-") and os.path.isfile(a)]
if not targets:
    code = 0 if "--passWithNoTests" in sys.argv else 1
    out.append("No tests found, exiting with code %d" % (code,))
    out.append("Run with `--passWithNoTests` to exit with code 0")
    sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
    sys.exit(code)
passed = failed = suites_bad = 0
for rel in targets:
    with open(rel) as fh:
        text = fh.read()
    if not text.strip():
        suites_bad += 1
        out += [" FAIL  %s" % (rel,), "  ● Test suite failed to run", "",
                "    Your test suite must contain at least one test.", ""]
        continue
    outer = DESCRIBE.search(text).group(1)
    block = []
    for title, got, want in TEST.findall(text):
        if value(got) == int(want):
            passed += 1
            continue
        failed += 1
        block += ["  ● %s › %s" % (outer, title), "",
                  "    expect(received).toBe(expected) // Object.is equality", "",
                  "    Expected: %s" % (want,), "    Received: %s" % (value(got),), ""]
    if block:
        suites_bad += 1
    out += [" %s  %s" % ("FAIL" if block else "PASS", rel)] + block
counts = ", ".join("%d %s" % (n, w) for n, w in ((failed, "failed"), (passed, "passed")) if n)
out.append("Test Suites: %d failed, %d total" % (suites_bad, len(targets)))
out.append("Tests:       %s%d total" % (counts + ", " if counts else "", failed + passed))
sys.stdout.buffer.write(("\n".join(out) + "\n").encode("utf-8"))
sys.exit(1 if suites_bad else 0)
'''
# ...and a pytest-shaped one, which is what the sweep has where pytest is not
# installed: an empty file collects nothing and exits 5 with `no tests ran`.
# A test is `def test_<name>():` over `    assert v() == <int>`. Its file is
# named `pytest`, so the command names the runner the way a real one does.
_FAKE_PYTEST = r'''import os, re, sys
TEST = re.compile(r"^def (test_\w+)\(\):\n    assert v\(\) == (\d+)$", re.M)
with open(os.path.join("src", "mine.py")) as fh:
    have = int(fh.read().split("=")[1])
out, passed, failed = [], 0, 0
for rel in [a for a in sys.argv[1:] if not a.startswith("-")]:
    with open(rel) as fh:
        for name, want in TEST.findall(fh.read()):
            if have == int(want):
                passed += 1
                continue
            failed += 1
            out.append("FAILED %s::%s - assert %d == %s" % (rel, name, have, want))
counts = ", ".join("%d %s" % (n, w) for n, w in ((failed, "failed"), (passed, "passed")) if n)
out.append("=== %s in 0.01s ===" % (counts or "no tests ran",))
sys.stdout.write("\n".join(out) + "\n")
sys.exit(1 if failed else (0 if passed else 5))
'''


def _js_test(outer, cases):
    """A test file `_FAKE_JEST` reads: one `describe(outer)` over `(title,
    got, want)` cases."""
    return "\n".join(["describe('%s', () => {" % (outer,)] + [
        "  test('%s', () => { expect(%s).toBe(%s); });" % case for case in cases]
        + ["});", ""])


def _fake_runner(prefix, name, source):
    """The absolute path of a fake runner script, outside every fixture tree."""
    path = os.path.join(_harness.fixture_root(prefix), name)
    _write(path, source)
    return path


def _new_file_repo(prefix, head_files, wt_files, new):
    """A repository whose HEAD holds `v = 1` and `head_files`, and whose working
    tree holds the fix (`v = 2`) and `wt_files`, the task declaring `src/mine.py`
    and the test file `new` - which HEAD does not have."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    for rel, text in head_files.items():
        _write(os.path.join(root, *rel.split("/")), text)
        _git(root, "add", rel)
    if head_files:
        _git(root, "commit", "-q", "-m", "tests")
    _write(os.path.join(root, "src", "mine.py"), "v = 2\n")
    for rel, text in wt_files.items():
        _write(os.path.join(root, *rel.split("/")), text)
    manifest = json.loads(json.dumps(MANIFEST))
    task = manifest["phases"][0]["tasks"][0]
    task["files"] = ["src/mine.py", new]
    task["tests"] = {"mode": "tdd", "add": ["%s: v is two" % (new,)]}
    man = os.path.join(_harness.fixture_root(prefix + "man-"), "audit-plan.json")
    _write(man, json.dumps(manifest))
    return root, man


def _new_file_cases(check):
    py = sys.executable
    jest = _fake_runner("stamp-fake-jest-", "jest.py", _FAKE_JEST)
    new_js = "tests/new.test.js"
    old_green = {"tests/old.test.js": _js_test("old", [("old holds", "1", "1")])}
    adds = {new_js: _js_test("mine", [("v is two", "v()", "2")])}
    got = {}
    for how, cmd in (("naming only the new file", [py, jest, new_js]),
                     ("naming HEAD's green file and the new one",
                      [py, jest, "tests/old.test.js", new_js])):
        root, man = _new_file_repo("stamp-red-newjs-", old_green, adds, new_js)
        code, payload = _red(root, man, cmd)
        got[how] = (code, (payload.get("redFirst") or {}).get("basis")
                    or payload.get("note") or payload,
                    (payload.get("baseline") or {}).get("absent"))
    check("sb1 a jest-shaped runner that fails an empty suite: a task adding a new "
          "failing test file gets a green baseline - HEAD's run made with the new "
          "file ABSENT, never an empty stub - and the red is proved, the basis "
          "saying the file was left absent: %r" % (got,),
          all(code == M.E_PROVED and "left absent" in str(basis)
              and "Test suite failed to run" not in str(basis)
              and absent == [new_js]
              for code, basis, absent in got.values()) and len(got) == 2)

    pytest = _fake_runner("stamp-fake-pytest-", "pytest", _FAKE_PYTEST)
    new_py = "tests/test_new.py"
    root_p, man_p = _new_file_repo(
        "stamp-red-newpy-", {}, {new_py: "def test_two():\n    assert v() == 2\n"},
        new_py)
    code_p, payload_p = _red(root_p, man_p, [py, pytest, new_py])
    basis_p = (payload_p.get("redFirst") or {}).get("basis", json.dumps(payload_p))
    base_p = payload_p.get("baseline") or {}
    head_p = (payload_p.get("run") or {}).get("head") or {}
    check("sb2 THE ALLOW CASE for sb1: a pytest task adding a new test file keeps "
          "today's baseline - the file laid over as an empty stub, HEAD's run "
          "exiting 5 with no tests ran and accepted as green - and is proved: "
          "exit=%r baseline=%r head exit=%r %s"
          % (code_p, base_p, head_p.get("exit"), basis_p[:300]),
          code_p == M.E_PROVED and "laid over as empty files" in basis_p
          and "left absent" not in basis_p
          and base_p.get("stubbed") == [new_py] and base_p.get("absent") == []
          and head_p.get("exit") == 5)

    old_red = {"tests/old.test.js": _js_test("old", [("v is already two", "v()", "2")])}
    root_r, man_r = _new_file_repo("stamp-red-newjs-red-", old_red, adds, new_js)
    code_r, payload_r = _red(root_r, man_r, [py, jest, "tests/old.test.js", new_js])
    basis_r = (payload_r.get("redFirst") or {}).get("basis", json.dumps(payload_r))
    head_r = "\n".join(((payload_r.get("run") or {}).get("head") or {})
                       .get("outputTail") or [])
    check("sb3 THE ALLOW CASE for sb1, the over-fire direction: with the new file "
          "absent, a baseline whose remaining target is red at HEAD still answers "
          "could-not-prove - the red read off HEAD's own failing case, not off an "
          "empty suite: exit=%r absent=%r head=%r %s"
          % (code_r, (payload_r.get("baseline") or {}).get("absent"), head_r,
             basis_r[:300]),
          code_r == M.E_CANNOT_PROVE and "already red" in basis_r
          and (payload_r.get("baseline") or {}).get("absent") == [new_js]
          and "old › v is already two" in head_r
          and "Test suite failed to run" not in head_r)


def _none_found_cases(check):
    new_js = ["tests/new.test.js"]
    sentence = "No tests found, exiting with code 1\n"
    failing = (sentence + " FAIL  tests/old.test.js\n  ● old › holds\n\n"
               "    expect(received).toBe(expected) // Object.is equality\n\n"
               "Test Suites: 1 failed, 1 total\nTests:       1 failed, 1 total\n")
    refused = M.baseline_problem({"code": 1, "text": failing, "problem": None,
                                  "absent": new_js}, ["npx", "jest"])
    check("sb4 jest's no-test-file sentence beside a tally counting a failure is "
          "NOT a green baseline, a file left absent or not - the sentence alone "
          "never vouches for a run that failed: %r" % (refused,),
          refused is not None and "not green" in refused)
    got = dict((how, M.baseline_problem(dict(head, problem=None), ["npx", "jest"]))
               for how, head in (
                   ("the sentence alone", {"code": 1, "text": sentence,
                                           "absent": new_js}),
                   ("the sentence and a tally counting nothing",
                    {"code": 1, "text": sentence + "Tests:       0 total\n",
                     "absent": new_js}),
                   ("vitest's sentence", {"code": 1, "absent": new_js,
                                          "text": "No test files found, exiting "
                                                  "with code 1\n"})))
    no_absent = M.baseline_problem({"code": 1, "text": sentence, "problem": None,
                                    "absent": []}, ["npx", "jest"])
    check("sb5 THE ALLOW CASE for sb4: with a file left absent, the sentence alone, "
          "or beside a tally counting nothing, IS a green baseline under jest and "
          "vitest alike - and with no file left absent it is not, a path that "
          "matched nothing being a misnamed one: %r absent-none %r"
          % (got, no_absent),
          all(v is None for v in got.values()) and len(got) == 3
          and no_absent is not None)


# --- dependencies: the project's ignored node_modules linked into the throwaway ---
# The throwaway holds tracked files only. These fixtures keep the jest-shaped
# runner INSIDE an ignored `node_modules`, reached through a `.bin` link the way
# npm lays one out, so a run can start only when the helper links that directory
# in - and a sentinel beside it shows the removal unlinked rather than descended.
def _deps_repo(prefix, wt_cases, head_extra=None, deps=True):
    """A repository ignoring `node_modules/`, HEAD at `v = 1` and the working tree
    at `v = 2` with a new `tests/new.test.js` holding `wt_cases`; with `deps`, an
    ignored `node_modules` holding the runner, a `.bin/jest` link to it and a
    sentinel file. Returns `(root, man, cmd)`."""
    new_js = "tests/new.test.js"
    head = {".gitignore": "node_modules/\n"}
    head.update(head_extra or {})
    root, man = _new_file_repo(prefix, head,
                               {new_js: _js_test("mine", wt_cases)}, new_js)
    if deps:
        _deps_dir(root)
    return root, man, [sys.executable, "node_modules/.bin/jest", new_js]


def _deps_dir(base):
    """`base/node_modules` with the fake runner, its `.bin` link and a sentinel."""
    nm = os.path.join(base, "node_modules")
    os.makedirs(os.path.join(nm, "fakejest"))
    os.makedirs(os.path.join(nm, ".bin"))
    _write(os.path.join(nm, "fakejest", "jest.py"), _FAKE_JEST)
    _write(os.path.join(nm, "sentinel.txt"), "the shared tree's dependency\n")
    os.makedirs(os.path.join(nm, ".cache"))
    os.symlink(os.path.join("..", "fakejest", "jest.py"),
               os.path.join(nm, ".bin", "jest"))
    return nm


def _deps_basis(payload):
    return ((payload.get("redFirst") or {}).get("basis") or payload.get("note")
            or json.dumps(payload))


def _deps_cases(check):
    root, man, cmd = _deps_repo("stamp-red-deps-", [("v is two", "v()", "2")],
                                head_extra={".npmrc": "fund=false\n"})
    code, payload = _red(root, man, cmd)
    basis = _deps_basis(payload)
    nm = os.path.join(root, "node_modules")
    kept = [rel for rel in ("sentinel.txt", "fakejest/jest.py", ".bin/jest")
            if os.path.lexists(os.path.join(nm, *rel.split("/")))]
    cache = os.listdir(os.path.join(nm, ".cache"))
    check("sd1 with --deps-from defaulting to --project, an ignored node_modules "
          "holding a jest-shaped runner is linked into the throwaway and a new "
          "failing test answers proved - without the link the runner is absent "
          "there and the answer was could-not-prove; the basis names the linked "
          "directory and the TRACKED .npmrc as carried with HEAD, and the removal "
          "left every file behind the links in place, the runner's write into "
          "node_modules/.cache staying in the throwaway: exit=%r kept=%r "
          "source cache=%r %s" % (code, kept, cache, basis[:600]),
          code == M.E_PROVED and "linked" in basis and "node_modules" in basis
          and ".npmrc" in basis and "carried" in basis
          and kept == ["sentinel.txt", "fakejest/jest.py", ".bin/jest"]
          and cache == []
          and (payload.get("dependencies") or {}).get("linked") == ["node_modules"]
          and (payload.get("throwaway") or {}).get("removed") is True)

    outside = _harness.fixture_root("stamp-red-deps-store-")
    _write(os.path.join(outside, "index.js"), "module.exports = 1;\n")
    root_w, man_w, cmd_w = _deps_repo("stamp-red-deps-ws-", [("v is two", "v()", "2")])
    os.makedirs(os.path.join(root_w, "packages", "ws"))
    _write(os.path.join(root_w, "packages", "ws", "index.js"), "x\n")
    _git(root_w, "add", "packages/ws/index.js")
    _git(root_w, "commit", "-q", "-m", "a workspace package")
    os.symlink(os.path.join(root_w, "packages", "ws"),
               os.path.join(root_w, "node_modules", "ws"))
    code_w, payload_w = _red(root_w, man_w, cmd_w)
    basis_w = _deps_basis(payload_w)
    run_w = payload_w.get("run") or {}
    check("sd2 a node_modules entry linking into the shared working tree (a "
          "workspace package) is refused BY NAME and no run is made - HEAD's run "
          "would read the fix through it: exit=%r head=%r exit-of-run=%r %s"
          % (code_w, run_w.get("head"), run_w.get("exit"), basis_w[:600]),
          code_w == M.E_CANNOT_PROVE and "node_modules/ws" in basis_w
          and "workspace" in basis_w and run_w.get("head") is None
          and run_w.get("exit") is None and run_w.get("fix") is None)

    root_s, man_s, cmd_s = _deps_repo("stamp-red-deps-st-", [("v is two", "v()", "2")])
    os.symlink(outside, os.path.join(root_s, "node_modules", "stored"))
    code_s, payload_s = _red(root_s, man_s, cmd_s)
    basis_s = _deps_basis(payload_s)
    check("sd3 THE ALLOW CASE for sd2: an entry linking OUTSIDE the project (a "
          "package store), and the `.bin` link resolving inside node_modules "
          "itself, are linked and the red is proved - the refusal reads where a "
          "link lands, not that it is a link: exit=%r %s" % (code_s, basis_s[:600]),
          code_s == M.E_PROVED and "workspace" not in basis_s)

    root_g, man_g, cmd_g = _deps_repo("stamp-red-deps-green-", [("one is one", "1", "1")])
    _write(os.path.join(root_g, ".npmrc"), "fund=false\n")
    os.makedirs(os.path.join(root_g, "scratch", "node_modules", "x"))
    # Outside the tree on purpose: a value under the root is already dropped as
    # a path into the shared tree, and would pass this case without the new rule.
    userrc = os.path.join(_harness.fixture_root("stamp-red-deps-rc-"), "npmrc")
    code_g, payload_g = _with_env("NPM_CONFIG_USERCONFIG", userrc,
                                  lambda: _red(root_g, man_g, cmd_g))
    note = _deps_basis(payload_g)
    dropped = (payload_g.get("environment") or {}).get("dropped") or []
    check("sd4 THE ALLOW CASE: a test that passes without the fix stays not red "
          "(exit 1) with dependencies linked, and the note names the linked "
          "directory, the source path a runner may write back through, the cache "
          "directories kept in the throwaway, a node_modules whose parent HEAD "
          "lacks as not linked, and the untracked project .npmrc as "
          "dropped, with NPM_CONFIG_USERCONFIG dropped from the environment: "
          "exit=%r dropped=%r %s" % (code_g, dropped, note[:800]),
          code_g == M.E_NOT_RED and "linked" in note
          and any(os.path.join(r, "node_modules") in note
                  for r in (root_g, os.path.realpath(root_g)))
          and ".cache" in note and ".npmrc" in note and "dropped" in note
          and "not linked: scratch/node_modules (its parent directory is not at "
              "HEAD)" in note
          and "NPM_CONFIG_USERCONFIG" in dropped)

    root_p, man_p, cmd_p = _deps_repo("stamp-red-deps-from-",
                                      [("v is two", "v()", "2")], deps=False)
    source = _harness.fixture_root("stamp-red-deps-source-")
    subprocess.run(["git", "init", "-q", source], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _write(os.path.join(source, ".gitignore"), "node_modules/\n")
    _deps_dir(source)
    code_n, payload_n = _red(root_p, man_p, cmd_p)
    code_f, payload_f = _red(root_p, man_p, cmd_p, "--deps-from", source)
    check("sd5 --deps-from names another checkout holding node_modules: a project "
          "with none of its own proves the red from it, and without the flag the "
          "same run is could-not-prove: without=%r with=%r %s"
          % (code_n, code_f, _deps_basis(payload_f)[:600]),
          code_n == M.E_CANNOT_PROVE and code_f == M.E_PROVED
          and any(s in _deps_basis(payload_f)
                  for s in (source, os.path.realpath(source))))


def _cases(check):
    _harness.stage(check, "sd-deps", _deps_cases)
    _harness.stage(check, "sb-new-file", _new_file_cases)
    _harness.stage(check, "sb-none-found", _none_found_cases)
    _harness.stage(check, "sr-decisive", _decisive_cases)
    _harness.stage(check, "sr-jest", _jest_cases)
    _harness.stage(check, "sj-credit", _jest_credit_cases)
    _harness.stage(check, "sr-crlf", _crlf_cases)
    _harness.stage(check, "sr-listing", _listing_cases)
    _harness.stage(check, "sr-holder", _holder_cases)
    _harness.stage(check, "sv-take", _take_cases)
    _harness.stage(check, "sv-compare", _compare_cases)
    _harness.stage(check, "sv-shape", _shape_cases)
    _harness.stage(check, "sv-recorder", _recorder_cases)
    _harness.stage(check, "sr-red", _red_cases)
    _harness.stage(check, "sr-tally", _tally_cases)
    _harness.stage(check, "sr-introduces", _introduces_cases)
    _harness.stage(check, "sr-process", _process_cases)
    _harness.stage(check, "sr-own", _own_case_cases)
    _harness.stage(check, "sr-label", _label_cases)
    _harness.stage(check, "sr-label-id", _label_id_cases)
    _harness.stage(check, "sr-runner", _runner_cases)
    _harness.stage(check, "sr-specific", _specific_cases)
    _harness.stage(check, "sr-wording", _wording_cases)
    _harness.stage(check, "sr-exact", _exact_cases)
    _harness.stage(check, "sr-command", _command_cases)
    _harness.stage(check, "sr-mixed", _mixed_cases)
    _harness.stage(check, "sr-green", _green_baseline_cases)
    _harness.stage(check, "sr-wrapper", _wrapper_cases)
    _harness.stage(check, "sr-pytest-command", _pytest_command_cases)
    _harness.stage(check, "sr-unittest", _unittest_cases)
    _harness.stage(check, "sr-red-baseline", _red_baseline_cases)
    _harness.stage(check, "sr-baseline-units", _baseline_unit_cases)
    _harness.stage(check, "sr-round5", _round5_cases)
    _harness.stage(check, "sr-round5-units", _round5_unit_cases)
    _harness.stage(check, "sr-every-run-isolated", _every_run_cases)
    _harness.stage(check, "sr-reach", _reach_cases)
    _harness.stage(check, "sr-located", _located_cases)
    _harness.stage(check, "sr-moved", _moved_cases)
    _harness.stage(check, "sr-binding", _binding_cases)
    _harness.stage(check, "sr-env", _env_cases)
    _harness.stage(check, "sr-final", _final_pass_cases)
    _harness.stage(check, "sr-budget", _budget_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_stamp_verification.py --selftest\n")
    raise SystemExit(2)
