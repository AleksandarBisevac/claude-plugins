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
import io
import json
import os
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _tree_stamp                                 # noqa: E402

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
_RED_TEST = (
    "import os, sys\n"
    "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),"
    " '..', 'src'))\n"
    "%s\n"
    "ok = %s\n"
    "print('%%s a' %% ('PASS' if ok else 'FAIL'))\n"
    "print(%r %% ('ALL PASS' if ok else 'SELFTEST FAILED', int(ok), 1))\n"
    "sys.exit(0 if ok else 1)\n")


def _red_test(imports, cond):
    return _RED_TEST % (imports, cond, _TALLY)


def _red_repo(prefix, wt_test, extra=None, files=None):
    """A repository whose HEAD holds `v = 1` and a passing test, and whose working
    tree holds the fix (`v = 2`), `wt_test` as the task's new test, an untracked
    sibling file, and a manifest declaring the task."""
    root = _seeded_repo(prefix)
    os.makedirs(os.path.join(root, "tests"))
    _write(os.path.join(root, "tests", "test_mine.py"),
           _red_test("import mine", "mine.v >= 1"))
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
        ("pytest failed", (1, "===== 1 failed, 2 passed in 0.12s =====\n")),
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


def _cases(check):
    _harness.stage(check, "sv-take", _take_cases)
    _harness.stage(check, "sv-compare", _compare_cases)
    _harness.stage(check, "sv-shape", _shape_cases)
    _harness.stage(check, "sr-red", _red_cases)
    _harness.stage(check, "sr-tally", _tally_cases)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_stamp_verification.py --selftest\n")
    raise SystemExit(2)
