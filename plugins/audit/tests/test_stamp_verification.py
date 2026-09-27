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

import hashlib
import importlib.util
import io
import json
import os
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
    root = _harness.fixture_root(prefix)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
          and tw["path"] not in _worktrees(root))
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
          [os.path.realpath(x["path"]) for x in got_l.get("leftovers") or []]
          == [os.path.realpath(leftover)]
          and os.path.realpath(leftover) in _worktrees(root)
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
    check("sr94 a test file that is new at HEAD proves - HEAD has nothing of its "
          "own to run - and the payload records the fix run with its exit and "
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
          "the command reaches nothing HEAD has, so no HEAD run is made and the "
          "basis says so; the edited case in it fails on HEAD's code and passes "
          "with the fix, which is the proof: exit=%r %s" % (code_r, basis_r[:300]),
          code_r == M.E_PROVED and "no HEAD run" in basis_r
          and "green on HEAD's code" not in basis_r)
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
    got = dict((k, M.baseline_problem(h, [py, "t.py"], False))
               for k, h in shapes.items())
    got["green"] = M.baseline_problem(green, [py, "t.py"], False)
    got["no HEAD run owed"] = M.baseline_problem(None, [py, "t.py"],
                                                 "no HEAD run: a reason")
    got["no HEAD run made, none owed said"] = M.baseline_problem(None, [py, "t.py"],
                                                                 None)
    check("sr104 the baseline is green only when HEAD's own run could be made, "
          "exited 0 and printed a tally counting no failure; a missing run is "
          "accepted only with baseline_skip's reason: %r" % (got,),
          got["green"] is None and got["no HEAD run owed"] is None
          and all(got[k] and "narrow" in got[k] for k in shapes)
          and got["no HEAD run made, none owed said"])
    where = _harness.fixture_root("stamp-skip-")
    os.makedirs(os.path.join(where, "tests"))
    _write(os.path.join(where, "tests", "test_old.py"), "x = 1\n")
    _write(os.path.join(where, "tests", "test_new.py"), "x = 1\n")
    new = set(["tests/test_new.py"])
    skips = dict((" ".join(cmd[1:]), bool(M.baseline_skip(cmd, where, new)))
                 for cmd in ([py, "tests/test_new.py"],
                             ["pytest", "-q", "tests/test_new.py::test_a"],
                             [py, "tests/test_new.py", "tests/test_old.py"],
                             [py, "-m", "unittest", "discover", "-s", "tests"],
                             [py, "-m", "pytest", "tests"],
                             [py, "-m", "pytest"]))
    check("sr140 HEAD's run is skipped ONLY when the command names nothing but test "
          "files new at HEAD - another file, a directory, a discovery or no path at "
          "all gets the baseline: %r" % (skips,),
          skips == {"tests/test_new.py": True,
                    "-q tests/test_new.py::test_a": True,
                    "tests/test_new.py tests/test_old.py": False,
                    "-m unittest discover -s tests": False,
                    "-m pytest tests": False, "-m pytest": False})
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
                               ["sh", "-c", "%s tests/test_mine.py -v -f" % (py,)])[0]
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
          code_h != M.E_PROVED)
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
          code_t != M.E_PROVED)
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
          "proves with no HEAD run, and the basis says no HEAD run was made and "
          "why - never that HEAD's tests were green: exit=%r %s"
          % (code_o, basis_o[:300]),
          code_o == M.E_PROVED and "no HEAD run" in basis_o
          and "green on HEAD's code" not in basis_o
          and (got_o.get("run") or {}).get("head") is None)
    detail = repr([(i, i + 1) for i in range(20000)])
    long_fail = {"id": None, "label": "the pairs round-trip (saw %s)" % (detail,),
                 "assertion": True, "why": "house FAIL"}
    code = "\n".join([
        "import sys, resource", "sys.path.insert(0, %r)" % (_output.TESTS_DIR,),
        "import _harness, _loader",
        "M = _loader.load_script('stamp-verification.py', modname='sv_forms')",
        "d = repr([(i, i + 1) for i in range(20000)])",
        "f = {'id': None, 'label': 'the pairs round-trip (saw %s)' % (d,),"
        " 'assertion': True, 'why': 'house FAIL'}",
        "own, refused = M.own_failures([f], ['the pairs round-trip'])",
        "print(len(own), len(refused),"
        " resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)"])
    try:
        proc = subprocess.run([py, "-c", code], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True,
                              timeout=60)
        out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    except subprocess.TimeoutExpired:
        out = "timed out"
    parts = out.split()
    rss_mb = (int(parts[2]) // (1 << 20 if sys.platform == "darwin" else 1 << 10)
              if len(parts) == 3 and parts[2].isdigit() else None)
    check("sr139 --case names a label beside a long parenthesised detail in linear "
          "memory - no prefix of the line is built: %r (%r MB) %d chars"
          % (out, rss_mb, len(long_fail["label"])),
          parts[:2] == ["1", "0"] and rss_mb is not None and rss_mb < 80)
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


def _cases(check):
    _harness.stage(check, "sv-take", _take_cases)
    _harness.stage(check, "sv-compare", _compare_cases)
    _harness.stage(check, "sv-shape", _shape_cases)
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
