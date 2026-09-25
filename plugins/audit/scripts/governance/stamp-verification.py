#!/usr/bin/env python3
"""
Stamp a verification with the tree it was taken on, and grade that stamp later.

WHAT THIS IS FOR, from failures that all look like carelessness and are all one
structure: somebody acted on a HELD MODEL of state instead of a read of it. Case
counts quoted after the patch they described had landed on a different tree. A
patch taken against a branch that had moved, silently reverting a sibling's work,
caught only because a number dropped. A gate that was green, an edit that landed,
and the green still being cited afterwards. None of those is a lapse of care - a
verification is a claim about a tree, and a claim that does not carry its tree
cannot be told from one that is still true.

THE GATE ALREADY SOLVED THIS FOR ITS OWN ROWS. `run-test-gate.py` records three
identity fields on every run because an exit code cannot say WHICH state it was
about. `_tree_stamp` is that arithmetic, moved so this command and that one share
it rather than agree by coincidence; what this adds is the second question - is
the tree still the one the stamp names - and the third answer, that git may not be
able to say.

WHAT IT DOES NOT DO, so nobody has to discover it. A stamp is not a snapshot: the
dirty digest records WHICH paths were dirty and never their contents, so a rewrite
of an already-dirty file outside the declared scope moves nothing here. Every
field prints that limit beside itself, on the way in and on the way out.

AND IT IS NOT THE DOCTOR. `/audit:doctor` already reports two neighbouring
things - that the hooks running in this session are an OLDER installed copy of the
plugin, and what an abandoned worktree has left behind - and neither is repeated
here. Those are questions about the INSTALLATION; this is a question about the
TREE, and a claim taken while the doctor was warning about a stale copy is a claim
whose stamp is worth having beside that warning rather than instead of it.

Usage:
  stamp-verification.py take    [--project DIR] [--files A [B ...]]
                                [--manifest M --task T] [--json]
  stamp-verification.py compare [--project DIR] [--stamp TEXT | --stamp-file F]
                                [--json]
  stamp-verification.py red     [--project DIR] --manifest M --task T
                                [--case ID ...] [--introduces SYMBOL ...]
                                [--timeout S] [--json] -- <test command>

  `compare` reads the stamp from stdin when neither --stamp nor --stamp-file is
  given, so a report or a commit message can be piped straight in.

Exit codes:
  0  compare: current - every field git could answer still agrees
     take:    the stamp was taken
  1  compare: STALE - the tree has moved, and the output names which field did
  3  compare: unestablished - git could not answer, so nothing was graded
  2  usage error, an unreadable manifest, a task id that is not there, or a stamp
     this code cannot read
  red: 0 proved - 1 not red (the test passed in the throwaway) - 3 could not
     prove (no case of the task's own failed an assertion, the run could not run,
     or it was interrupted) - 4 the throwaway tree could not be removed - 2 as
     above, and for a task with no test file, a symbol that is not an
     identifier, or a command that names the shared tree

RED IS THE THIRD ACTION, AND THE ONE THAT BUILDS SOMETHING. It proves a new test
can fail by running it in a throwaway tree - HEAD, with the task's test files
copied from the working tree over it - so nobody has to put code without the fix
back into a tree siblings are editing. The `red` section below says what it writes
and how the removal is checked.

WHY THREE CODES AND NOT TWO. `unestablished` must not share an exit code with
either neighbour. Sharing 0 makes an unanswerable comparison read as "unchanged",
which is the false clean sheet the whole design refuses; sharing 1 makes it read
as "the tree moved", which sends a reader to re-run work that may be perfectly
current. A caller that only wants a pass/fail gets it by testing for 0.

`take` and `compare` mutate nothing: no lock is taken, no file is written, and
git is only read. `red` never writes the working tree it is pointed at; it writes a
temp directory and the worktree registration for it, and removes both on every
path but SIGKILL, which no process can catch - the `red` section says what is
reported instead.
"""
import argparse
import datetime
import json
import os
import re
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

import _tree_stamp  # noqa: E402  (the ONE tree identity, shared with run-test-gate)
import _manifest_io as _mio  # noqa: E402  (dual-format loader: single file OR shards)
import _proc_group  # noqa: E402  (a child tree stopped whole; a stop signal as an exception)

USAGE = ("usage: stamp-verification.py take|compare|red [--project DIR] ...\n")

E_STALE, E_USAGE, E_UNESTABLISHED = 1, 2, 3

# The verdict -> exit code map, as a table rather than as three `if`s in `main`.
# One place decides what a word is worth, so the docstring above, the cases, and
# the caller cannot come to disagree about which answer exits 0.
EXIT_FOR = {_tree_stamp.CURRENT: 0,
            _tree_stamp.STALE: E_STALE,
            _tree_stamp.UNESTABLISHED: E_UNESTABLISHED}


def task_files(manifest, task_id):
    """`(files, problem)` - the paths one task declares. Exactly one is None.

    THE SCOPE COMES OFF THE PLAN AND NOT OFF A HAND-TYPED LIST wherever a plan
    exists, because the hand-typed list is the held model of state this command
    is about. A task that declares no files is NOT an error - it is a stamp with
    no scope digest, and `take` says so rather than inventing one."""
    for _phase, task in _mio.iter_tasks(manifest):
        if str(task.get("id")) != str(task_id):
            continue
        return [f for f in (task.get("files") or []) if isinstance(f, str)], None
    known = [str(t.get("id")) for _p, t in _mio.iter_tasks(manifest)]
    return None, ("no task %r in this manifest (have: %s)"
                  % (task_id, ", ".join(known) if known else "none"))


def resolve_scope(args):
    """`(files, problem)` - what this invocation declares, from either source.

    BOTH SOURCES AT ONCE IS A REFUSAL. A `--files` list beside a `--task` is two
    answers to "which work is this about", and silently preferring one would put
    the wrong scope under a right-looking digest - the failure in miniature."""
    if args.task and args.files:
        return None, ("--files and --task both name the work under test; pass "
                      "one, because a digest over the wrong file set is a stamp "
                      "about the wrong claim")
    if args.task:
        if not args.manifest:
            return None, "--task needs --manifest to resolve the task's files"
        try:
            manifest = _mio.load_manifest(args.manifest)
        except Exception as exc:
            return None, "cannot read/parse %s: %s" % (args.manifest, exc)
        if not isinstance(manifest, dict):
            return None, "manifest %s is not a JSON object" % (args.manifest,)
        return task_files(manifest, args.task)
    return list(args.files or []), None


def read_stamp_text(args, stdin=None):
    """`(text, problem)` - the document the stamp is somewhere inside.

    STDIN IS THE DEFAULT because that is the shape the caller already has: a
    commit message, a report paragraph, an agent's reply. `parse_stamp` finds the
    token in it, and refuses a document carrying two."""
    if args.stamp is not None and args.stamp_file is not None:
        return None, "pass --stamp or --stamp-file, not both"
    if args.stamp is not None:
        return args.stamp, None
    if args.stamp_file is not None:
        try:
            with open(args.stamp_file, "r", encoding="utf-8") as fh:
                return fh.read(), None
        except (OSError, UnicodeDecodeError) as exc:
            return None, "cannot read %s: %s" % (args.stamp_file, exc)
    stream = stdin if stdin is not None else sys.stdin
    try:
        return stream.read(), None
    except Exception as exc:
        return None, "cannot read the stamp from stdin: %s" % (exc,)


# --- red: a red-first proof in a throwaway tree --------------------------------
# PROVING A TEST CAN FAIL MEANS RUNNING IT AGAINST CODE WITHOUT THE FIX, and the
# only way the briefs used to offer was to put that code back in the shared
# working tree - undo the fix, or write HEAD's copy over the file - for as long
# as the run took. In a tree siblings are editing that is a write over their
# ground, and a host refused it beside a sibling's uncommitted work. So the proof
# is made somewhere else: a `git worktree add --detach` of HEAD in a temp
# directory, with the working tree's copy of the task's TEST files laid over it
# and its implementation files left at HEAD.
#
# WHAT IT WRITES, AND WHAT IT CANNOT PROMISE, so nobody has to discover it.
# `git worktree add` registers the throwaway in the repository's administrative
# directory; the `finally` below removes that registration with the directory and
# then asks git whether either is still there, and a registration it could not
# remove is its own exit code. SIGINT and SIGTERM are turned into an exception so
# that `finally` runs, and the run's whole process group is torn down on a timeout
# or an interrupt, so no grandchild writes into a directory being removed.
# SIGKILL cannot be caught: a run killed that way leaves its throwaway, and the
# next `red` REPORTS it by name, never prunes it - it may be another run's, still
# going. The throwaway also shares the repository's git directory, so a test that
# runs git in its own cwd (a stash, a config write, a branch) writes shared refs;
# the environment is scrubbed of what points at the shared tree, but a test's own
# git commands are its own.
E_PROVED, E_NOT_RED, E_CANNOT_PROVE, E_LEFT_BEHIND = 0, 1, 3, 4

# The words this command writes, each one the schema's `redFirst.status` enum
# declares. A green run has no word here on purpose: a test that passes without
# the fix is work left to do, not an outcome to record.
RED_PROVED = "proved"
RED_CANNOT = "could-not-prove"
RED_WORDS = (RED_PROVED, RED_CANNOT)

V_RED, V_GREEN = "red", "green"
V_COLLECT, V_NO_TALLY, V_NOT_RUN = "collection-error", "no-tally", "could-not-run"

# The host's Bash tool gives a command at most this many seconds, and a helper it
# kills never reaches its own `finally`. The default stays under it with room for
# the teardown, so the helper's own timeout is the one that fires.
HOST_BASH_LIMIT = 600
DEFAULT_TIMEOUT = 480

# Every throwaway's temp directory starts with this, which is how a leftover from
# a run nobody could clean up is recognised in `git worktree list`.
THROWAWAY_PREFIX = "audit-red-"

# What the child's environment loses: the variables that point a test, or git,
# back at the shared tree, and any variable whose value names the shared root.
SCRUBBED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY", "PYTHONPATH", "CLAUDE_PROJECT_DIR")

# A task's declared file is a TEST file when `tests.add` names it or its path has
# the conventional test shape; everything else it declares is implementation and
# stays at HEAD. The split is printed with every run, because it decides what the
# red is a red OF.
_TEST_DIRS = ("tests", "test", "__tests__", "spec")
_TEST_NAME = re.compile(r"^(test_.+|.+_test\.[^.]+|.+\.(test|spec)\.[^.]+)$")

# --- the tally a verdict is read from ---
# `red` needs a COUNT and a NAME: at least one test collected, and at least one
# named case failing an ASSERTION. A non-zero exit alone is not that - a compile
# error, an import error and a runner that collected nothing all exit non-zero
# with no assertion ever evaluated - and neither is an exception raised in a test
# body, which pytest counts as `failed` and unittest as an error. A runner whose
# tally this does not read is `no-tally` and never promoted to `red`.
#
# The house harness marks a block that raised while being BUILT with one of
# these labels, and a duplicated case id with the third; none of them is an
# assertion about the code.
HOUSE_ESCAPES = ("RAISED WHILE ITS CASES WERE BEING BUILT",
                 "selftest body raised before reaching the end",
                 "DUPLICATE CASE ID")
_HOUSE_TALLY = re.compile(r"^(?:ALL PASS|SELFTEST FAILED): (\d+)/(\d+) "
                          + "cases " + "passed", re.M)
# pytest frames its summary with `=` by default and prints it bare under -q.
_PYTEST_SUMMARY = re.compile(
    r"^(?:=+ )?((?:\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|"
    r"warnings?|deselected)(?:, )?)+|no tests ran) in [\d.]+s\b.*$", re.M)
_PYTEST_COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed)")
_PYTEST_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.M)
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
_UNITTEST_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
_UNITTEST_CASE = re.compile(r"^(FAIL|ERROR): (\S+)", re.M)
# With no tally, a traceback ending in one of these is a run that never reached an
# assertion; any other tally-less failure is `no-tally`, a crash nobody classified.
_COMPILE_ERROR = re.compile(r"^\s*(SyntaxError|IndentationError|TabError|ImportError|"
                            r"ModuleNotFoundError|NameError)\b", re.M)
_ERROR_LINE = re.compile(r"^\s*(\w*(?:Error|Exception)\b.*)$", re.M)
_FINAL_ERROR = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception)):\s?(.*)$", re.M)

# The error classes a missing symbol produces. A syntax error never qualifies: it
# is the test's own text failing to parse, and it survives any fix.
INTRODUCES_CLASSES = ("ImportError", "ModuleNotFoundError", "AttributeError",
                      "NameError")
_SYMBOL_SHAPE = re.compile(r"^[A-Za-z_][\w.]*$")


def failing_cases(text):
    """`[{"id", "assertion", "why"}]` - every failing case a runner named.

    `assertion` is True only where the runner says the case failed an assertion:
    a house `FAIL` line that is not an escape, a pytest `FAILED` whose reason is
    an `assert` or an `AssertionError`, a unittest `FAIL:`. A pytest `ERROR`, a
    pytest body exception and a unittest `ERROR:` are named with it False."""
    out = []
    for ln in text.splitlines():
        if ln.startswith("FAIL ") and not any(m in ln for m in HOUSE_ESCAPES):
            label = ln[len("FAIL "):].strip()
            out.append({"id": label.split()[0] if label else "", "assertion": True,
                        "why": "house FAIL"})
    for kind, node, why in _PYTEST_FAILED.findall(text):
        why = (why or "").strip()
        out.append({"id": node.split("::")[-1], "assertion": kind == "FAILED"
                    and (why.startswith("assert") or why.startswith("AssertionError")),
                    "why": why or kind})
    for kind, name in _UNITTEST_CASE.findall(text):
        out.append({"id": name, "assertion": kind == "FAIL", "why": kind})
    return out


def _house_tally(text):
    hits = _HOUSE_TALLY.findall(text)
    if not hits:
        return None
    passed, total = int(hits[-1][0]), int(hits[-1][1])
    asserting = [c for c in failing_cases(text) if c["why"] == "house FAIL"]
    return {"runner": "house", "collected": total, "failed": total - passed,
            "assertions": len(asserting)}


def _pytest_tally(text):
    hits = _PYTEST_SUMMARY.findall(text)
    if not hits:
        return None
    counts = dict((kind.rstrip("s") if kind.startswith("error") else kind, int(n))
                  for n, kind in _PYTEST_COUNT.findall(hits[-1]))
    ran = sum(counts.get(k, 0) for k in ("failed", "passed", "xfailed", "xpassed"))
    asserting = [c for c in failing_cases(text) if c["assertion"]]
    return {"runner": "pytest", "collected": ran,
            "failed": counts.get("failed", 0) + counts.get("error", 0),
            "assertions": len(asserting)}


def _unittest_tally(text):
    ran = _UNITTEST_RAN.findall(text)
    if not ran:
        return None
    counts = {}
    for hit in _UNITTEST_FAILED.findall(text):
        for part in hit.split(","):
            key, _sep, val = part.strip().partition("=")
            if val.isdigit():
                counts[key] = counts.get(key, 0) + int(val)
    failures = counts.get("failures", 0)
    return {"runner": "unittest", "collected": int(ran[-1]),
            "failed": failures + counts.get("errors", 0), "assertions": failures}


def read_tally(text):
    """The first tally a known runner printed, or None when none did."""
    for reader in (_house_tally, _pytest_tally, _unittest_tally):
        tally = reader(text)
        if tally is not None:
            return tally
    return None


def classify_run(code, text):
    """`(verdict, tally)` for one run: `green` / `red` / `collection-error` /
    `no-tally`. Exit 0 is `green` whatever the output says."""
    if code == 0:
        return V_GREEN, read_tally(text)
    tally = read_tally(text)
    if tally is None:
        return (V_COLLECT if _COMPILE_ERROR.search(text) else V_NO_TALLY), None
    if tally["collected"] > 0 and tally["assertions"] > 0:
        return V_RED, tally
    return V_COLLECT, tally


def final_error(text):
    """`(class, message, line)` of the last exception line a run printed, or None."""
    hits = _FINAL_ERROR.findall(text)
    if not hits:
        return None
    cls, message = hits[-1]
    return cls.split(".")[-1], message.strip(), "%s: %s" % (cls, message.strip())


def qualifying_error(text, symbol):
    """The final error line when it is a missing-symbol error NAMING `symbol` whole
    - the runtime quotes the name it could not find - else None."""
    err = final_error(text)
    if err is None or err[0] not in INTRODUCES_CLASSES:
        return None
    quoted = ("'%s'" % (symbol,), '"%s"' % (symbol,))
    return err[2] if any(q in err[1] for q in quoted) else None


# --- which files the throwaway takes from where ---
def find_task(manifest, task_id):
    """`(task, problem)` - one task by id. Exactly one is None."""
    for _phase, task in _mio.iter_tasks(manifest):
        if str(task.get("id")) == str(task_id):
            return task, None
    return None, "no task %r in this manifest" % (task_id,)


def _is_test_path(rel, named):
    parts = rel.replace("\\", "/").split("/")
    return (rel in named or any(p in _TEST_DIRS for p in parts[:-1])
            or bool(_TEST_NAME.match(parts[-1])))


def split_scope(task):
    """`(implementation, tests)` - the task's declared files, in declared order."""
    files = [f for f in (task.get("files") or []) if isinstance(f, str)]
    adds = (task.get("tests") or {}).get("add") or []
    named = set(str(a).split(":", 1)[0].strip() for a in adds if isinstance(a, str))
    tests = [f for f in files if _is_test_path(f, named)]
    return [f for f in files if f not in tests], tests


def child_env(root):
    """`(env, dropped)` - this process's environment without what reaches the
    shared tree: `SCRUBBED_ENV`, and any variable whose value names its root."""
    spellings = set(p for p in (root, os.path.realpath(root)) if p)
    dropped = sorted(k for k, v in os.environ.items()
                     if k in SCRUBBED_ENV or any(s in v for s in spellings))
    return dict((k, v) for k, v in os.environ.items() if k not in dropped), dropped


def _git_env():
    """This process's environment without git's own redirections, so the helper's
    git reads the repository `-C` names and nothing an environment points at."""
    return dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))


def _git(root, args, timeout=120):
    """`(code, text)` for one git call; the hooks path points nowhere, so no hook
    the repository carries runs on the throwaway's behalf."""
    try:
        out = subprocess.run(["git", "-C", root, "-c",
                              "core.hooksPath=%s" % os.devnull] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=timeout, env=_git_env())
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s" % (exc,)
    return out.returncode, out.stdout.decode("utf-8", "replace").strip()


def _head_text(root, rel):
    """HEAD's bytes of `rel` as text, or None when HEAD has no such file."""
    code, text = _git(root, ["show", "HEAD:%s" % (rel,)])
    return text if code == 0 else None


def _wt_text(root, rel):
    try:
        with open(os.path.join(root, *rel.split("/")), "r", encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _names(text, word):
    """Whether `text` carries `word` as a whole name, not inside a longer one."""
    return bool(re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), text or ""))


def introduced(root, implementation, symbol):
    """`(holds, basis)` - the STATIC half of whether this task introduces `symbol`:
    absent, as a whole name, from HEAD's copy of every declared implementation
    file (content and path, so a new module counts), and present in the working
    tree's copy of at least one. The half that decides is the second run, in
    `run_red`: with the working tree's implementation copied in, the error the
    first run ended on must be gone."""
    heads = dict((rel, _head_text(root, rel)) for rel in implementation)
    at_head = [rel for rel, text in heads.items()
               if text is not None and (_names(rel, symbol) or _names(text, symbol))]
    if at_head:
        return False, ("%r is not introduced by this task: HEAD already carries it "
                       "in %s" % (symbol, ", ".join(at_head)))
    in_wt = [rel for rel in implementation
             if (_names(rel, symbol) and _wt_text(root, rel) is not None)
             or _names(_wt_text(root, rel), symbol)]
    if not in_wt:
        return False, ("%r is not introduced by this task: no declared "
                       "implementation file in the working tree carries it" % (symbol,))
    return True, ("absent from HEAD's %s and present in the working tree's %s"
                  % (", ".join(implementation), ", ".join(in_wt)))


def own_failures(root, tests, failing, cases):
    """The failing cases that are the TASK'S OWN and failed an assertion.

    Own means named by `--case` when any is given; otherwise a case whose id is a
    whole name in the working tree's copy of a declared test file and absent from
    HEAD's copy of that file - a case the task added. An existing case going red
    because the working tree's test file was edited to match other work is not a
    proof about this task's test."""
    asserting = [f for f in failing if f["assertion"] and f["id"]]
    if cases:
        return [f for f in asserting if f["id"] in cases]
    added = []
    for f in asserting:
        for rel in tests:
            if (_names(_wt_text(root, rel), f["id"])
                    and not _names(_head_text(root, rel) or "", f["id"])):
                added.append(f)
                break
    return added


def _names_shared_tree(cmd, root, project):
    """The arguments that reach into the shared tree - by any spelling of its
    root, or as a path that resolves under it."""
    spellings = set(p for p in (root, os.path.realpath(root), project,
                                os.path.realpath(project)) if p)
    real = os.path.realpath(root) + os.sep
    return [a for a in cmd
            if any(s in a for s in spellings)
            or (os.path.isabs(a) and os.path.realpath(a).startswith(real))]


# --- the throwaway tree itself ---
def leftover_throwaways(root):
    """Registered worktrees whose path carries `THROWAWAY_PREFIX`: throwaways an
    earlier run could not remove. Reported, never pruned."""
    code, listing = _git(root, ["worktree", "list", "--porcelain"])
    if code != 0:
        return []
    paths = [ln[len("worktree "):] for ln in listing.splitlines()
             if ln.startswith("worktree ")]
    return [p for p in paths
            if any(part.startswith(THROWAWAY_PREFIX) for part in
                   p.replace("\\", "/").split("/"))]


def _build_throwaway(root, path, tests):
    """`(copied, problem)`: HEAD checked out at `path`, the tests laid over it."""
    code, text = _git(root, ["worktree", "add", "--detach", "--quiet", path, "HEAD"])
    if code != 0:
        return [], "git could not build the throwaway tree: %s" % (text,)
    return _lay_over(root, path, tests), None


def _lay_over(root, path, rels):
    """Copy each of `rels` from the working tree into the throwaway; one the
    working tree no longer has is removed there. Returns what was copied."""
    copied = []
    for rel in rels:
        src = os.path.join(root, *rel.split("/"))
        dst = os.path.join(path, *rel.split("/"))
        if not os.path.isfile(src):
            if os.path.isfile(dst):
                os.remove(dst)
            continue
        if not os.path.isdir(os.path.dirname(dst)):
            os.makedirs(os.path.dirname(dst))
        shutil.copyfile(src, dst)
        copied.append(rel)
    return copied


def _remove_throwaway(root, holder, path):
    """True only when the directory is gone AND git no longer lists it.

    The removal is asked of git whether or not the build got as far as
    registering the tree, because a build that died half way is exactly the
    case in which nobody knows."""
    _git(root, ["worktree", "remove", "--force", path])
    shutil.rmtree(holder, ignore_errors=True)
    code, listing = _git(root, ["worktree", "list", "--porcelain"])
    listed = code != 0 or path in listing or os.path.realpath(path) in listing
    return not os.path.exists(holder) and not listed


def _run_in(path, cmd, timeout, env):
    """`(code, text, problem)` for the command, run in the throwaway as a process
    group, so a timeout or an interrupt stops everything it started."""
    try:
        proc = subprocess.Popen(cmd, cwd=path, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env,
                                **_proc_group.group_kwargs())
    except OSError as exc:
        return None, "", "the command could not start: %s" % (exc,)
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        confirmed = _proc_group.tear_down(proc)
        text = _proc_group.drain(proc)
        return None, text, ("the run timed out after %s s and its process group "
                            "was torn down%s" % (timeout, "" if confirmed else
                                                 " (not confirmed)"))
    except BaseException:
        _proc_group.tear_down(proc)
        _proc_group.drain(proc)
        raise
    return proc.returncode, (out or b"").decode("utf-8", "replace"), None


def _decisive_line(text, tally):
    """The line a reader checks the verdict against: the tally, else the error."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if tally is not None:
        keys = {"house": "cases ", "pytest": " in ", "unittest": "Ran "}
        hits = [ln for ln in lines if keys[tally["runner"]] in ln]
        if hits:
            return hits[-1]
    errors = _ERROR_LINE.findall(text)
    if errors:
        return errors[-1].strip()
    return lines[-1] if lines else "(no output)"


def _ids(cases):
    return _output.some_of(["%s (%s)" % (c["id"] or "?", c["why"]) for c in cases])


def red_verdict(run, ctx):
    """`(exit, verdict, block, note)` - what the run in the throwaway proved.

    `run` is `{"cmd", "code", "text", "problem", "second"}`; `second` is the
    re-run with the working tree's implementation copied in, when one was made.
    `ctx` is `{"root", "implementation", "tests", "cases", "symbols",
    "dropped"}`."""
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    shown = " ".join(run["cmd"])
    if run["problem"] is not None:
        return E_CANNOT_PROVE, V_NOT_RUN, {
            "status": RED_CANNOT, "at": at,
            "basis": "`%s` in a throwaway tree at HEAD: %s"
                     % (shown, run["problem"])}, None
    code, text = run["code"], run["text"]
    verdict, tally = classify_run(code, text)
    line = _decisive_line(text, tally)
    where = "`%s` in a throwaway tree at HEAD exited %d" % (shown, code)
    if verdict == V_GREEN:
        return E_NOT_RED, verdict, None, (
            "%s (%s): the test PASSED in the throwaway - HEAD's implementation with "
            "this task's test files, run with %s removed from its environment - so "
            "it proves nothing yet; fix the test, there is no redFirst word to "
            "record for this" % (where, line, ", ".join(ctx["dropped"]) or "nothing"))
    failing = failing_cases(text)
    if verdict == V_RED:
        own = own_failures(ctx["root"], ctx["tests"], failing, ctx["cases"])
        if own:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s with %d of %d collected tests failing an assertion, "
                         "the task's own among them - %s: %s"
                         % (where, tally["assertions"], tally["collected"],
                            _ids(own), line)}, None
        return E_CANNOT_PROVE, verdict, {
            "status": RED_CANNOT, "at": at,
            "basis": "%s, but none of the failing cases is the task's own (%s): %s "
                     "- %s" % (where, "named by --case" if ctx["cases"] else
                               "added by the task, absent from HEAD's test files",
                               _ids(failing), line)}, None
    why_not = []
    for symbol in (ctx["symbols"] if verdict == V_COLLECT else ()):
        holds, why = introduced(ctx["root"], ctx["implementation"], symbol)
        error = qualifying_error(text, symbol)
        second = run.get("second")
        if not holds:
            why_not.append(why)
        elif error is None:
            why_not.append("the run's final error is not an %s naming %r: %s"
                           % ("/".join(INTRODUCES_CLASSES), symbol,
                              (final_error(text) or ("", "", "none"))[2]))
        elif second is None or second.get("problem"):
            why_not.append("the second run could not be made: %s"
                           % ((second or {}).get("problem") or "not attempted",))
        elif error in second["text"]:
            why_not.append("with the working tree's implementation copied in, a "
                           "second run still ends on %r, so the error is not the "
                           "absence this task fills" % (error,))
        elif classify_run(second["code"], second["text"])[0] not in (V_GREEN, V_RED):
            why_not.append("with the working tree's implementation copied in, a "
                           "second run lost %r but still reached no assertion "
                           "(%s), so the test is broken with the fix too"
                           % (error, _decisive_line(second["text"], None)))
        else:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s on %r, and the task introduces %r: %s; a second run "
                         "with the working tree's implementation copied in exited "
                         "%s without that error, its tests reaching their "
                         "assertions" % (where, error, symbol, why,
                                         second["code"])}, None
    reason = ("no test was collected or none reached an assertion"
              if verdict == V_COLLECT else
              "its output carries no test tally this command reads, so an "
              "assertion failure cannot be told from a crash - no test is known "
              "to have been collected")
    if failing:
        reason += "; failing without an assertion: %s" % (_ids(failing),)
    return E_CANNOT_PROVE, verdict, {
        "status": RED_CANNOT, "at": at,
        "basis": "%s, but %s: %s%s" % (where, reason, line,
                                       ("; " + "; ".join(why_not)) if why_not
                                       else "")}, None


def _wants_second(code, text, symbols):
    """Whether a second run is owed: a collection error some named symbol's
    missing-symbol error could explain."""
    verdict, _t = classify_run(code, text) if code is not None else (None, None)
    return verdict == V_COLLECT and any(qualifying_error(text, s) for s in symbols)


def _red_scope(args, cmd):
    """`(scope, problem)` - everything `red` needs before it builds anything."""
    if not cmd:
        return None, "red needs the test command after `--`"
    if not (args.task and args.manifest) or args.files:
        return None, ("red takes its scope off the plan: pass --manifest and "
                      "--task, and no --files")
    bad = [s for s in args.introduces if not _SYMBOL_SHAPE.match(s)]
    if bad:
        return None, ("--introduces takes an identifier (letters, digits, `_`, "
                      "`.`), and %r is not one - a fragment is a substring of "
                      "outputs it has nothing to do with" % (bad[0],))
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        return None, "cannot read/parse %s: %s" % (args.manifest, exc)
    task, problem = find_task(manifest if isinstance(manifest, dict) else {},
                              args.task)
    if problem is not None:
        return None, problem
    implementation, tests = split_scope(task)
    if not tests:
        return None, ("task %s declares no test file, so a throwaway at HEAD "
                      "would prove nothing about this task's test" % (args.task,))
    code, root = _git(os.path.abspath(args.project), ["rev-parse", "--show-toplevel"])
    if code != 0:
        return None, "%s is not inside a git repository: %s" % (args.project, root)
    named = _names_shared_tree(cmd, root, os.path.abspath(args.project))
    if named:
        return None, ("the command names the shared tree (%s); give its paths "
                      "relative to the tree root so they resolve inside the "
                      "throwaway - an interpreter inside the tree (.venv) is "
                      "untracked and absent there too" % (", ".join(named),))
    present = [t for t in tests if os.path.isfile(os.path.join(root, *t.split("/")))]
    if not present:
        return None, ("none of task %s's test files (%s) is in the working tree, "
                      "so a throwaway would hold HEAD alone"
                      % (args.task, ", ".join(tests)))
    return {"root": root, "implementation": implementation, "tests": present}, None


def _arm():
    """Arm the interrupt handlers where Python allows it (the main thread)."""
    try:
        return _proc_group.arm_interrupt()
    except ValueError:
        return None


def run_red(args, cmd, out):
    """`red`: prove a red in a throwaway tree and print the `redFirst` block."""
    scope, problem = _red_scope(args, cmd)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    root = scope["root"]
    leftovers = leftover_throwaways(root)
    env, dropped = child_env(root)
    _c, head = _git(root, ["rev-parse", "HEAD"])
    holder = tempfile.mkdtemp(prefix=THROWAWAY_PREFIX)
    path = os.path.join(holder, "tree")
    run = {"cmd": cmd, "code": None, "text": "", "problem": None, "second": None}
    copied = []
    previous = _arm()
    try:
        try:
            copied, run["problem"] = _build_throwaway(root, path, scope["tests"])
            if run["problem"] is None:
                run["code"], run["text"], run["problem"] = _run_in(
                    path, cmd, args.timeout, env)
            if run["problem"] is None and _wants_second(run["code"], run["text"],
                                                        args.introduces):
                _lay_over(root, path, scope["implementation"])
                code2, text2, problem2 = _run_in(path, cmd, args.timeout, env)
                run["second"] = {"code": code2, "text": text2, "problem": problem2}
        except KeyboardInterrupt as exc:
            run["problem"] = ("interrupted by %s before the run finished; the "
                              "run's process group was torn down"
                              % (exc or "an interrupt",))
        exit_code, verdict, block, note = red_verdict(run, {
            "root": root, "implementation": scope["implementation"],
            "tests": scope["tests"], "cases": args.case,
            "symbols": args.introduces, "dropped": dropped})
    finally:
        removed = _remove_throwaway(root, holder, path)
        if previous is not None:
            _proc_group.disarm_interrupt(previous)
    payload = {"verdict": verdict, "redFirst": block, "note": note,
               "atHead": scope["implementation"], "copied": copied,
               "leftovers": leftovers,
               "environment": {"dropped": dropped},
               "throwaway": {"path": path, "head": head, "removed": removed},
               "run": {"argv": cmd, "exit": run["code"],
                       "outputTail": run["text"].splitlines()[-20:],
                       "second": None if run["second"] is None else
                       {"exit": run["second"]["code"],
                        "outputTail": run["second"]["text"].splitlines()[-20:]}}}
    if args.as_json:
        out(json.dumps(payload, indent=2, sort_keys=True))
    else:
        out("red-first: %s (throwaway at HEAD %s, removed: %s)"
            % (verdict, (head or "?")[:12], "yes" if removed else "NO"))
        out("  at HEAD: %s" % (", ".join(scope["implementation"]) or "(none declared)"))
        out("  from the working tree: %s" % (", ".join(copied) or "(none)"))
        out("  environment: inherited, without %s" % (", ".join(dropped) or "nothing"))
        for left in leftovers:
            out("  LEFT BEHIND by an earlier run (not pruned): %s" % (left,))
        out(note if block is None else "redFirst: %s" % (json.dumps(block),))
    if not removed:
        sys.stderr.write("ERROR: the throwaway tree at %s could not be removed; "
                         "`git worktree list` names what is left\n" % (path,))
        return E_LEFT_BEHIND
    return exit_code


def build_parser():
    """The argument parser, separated so a case can read the option table."""
    parser = argparse.ArgumentParser(
        prog="stamp-verification.py", add_help=True, allow_abbrev=False,
        description="Stamp a verification with the tree it was taken on, and "
                    "grade that stamp against the tree now.")
    parser.add_argument("action", choices=("take", "compare", "red"))
    parser.add_argument("--project", default=".",
                        help="the tree to stamp or to grade against "
                             "(default: the current directory)")
    parser.add_argument("--files", nargs="*", default=[],
                        help="the paths the work under test declares; `take` only")
    parser.add_argument("--manifest", default=None,
                        help="a manifest to read --task's files out of")
    parser.add_argument("--task", default=None,
                        help="a task id whose `files` become the declared scope")
    parser.add_argument("--stamp", default=None,
                        help="the text carrying the stamp; `compare` only")
    parser.add_argument("--stamp-file", dest="stamp_file", default=None,
                        help="a file carrying the stamp; `compare` only")
    parser.add_argument("--introduces", action="append", default=[],
                        help="a symbol the task creates; `red` only - a compile "
                             "or collection error counts as red only when the "
                             "task introduces a symbol the run names")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="seconds the red run may take; `red` only")
    parser.add_argument("--case", action="append", default=[],
                        help="a case id the task added; `red` only - a red "
                             "counts only when one of the task's own cases "
                             "fails an assertion")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def run_take(args, out):
    """`take`: read the tree once, print the fields with their bases and the token."""
    files, problem = resolve_scope(args)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    stamp, state = _tree_stamp.take(os.path.abspath(args.project), files)
    if args.as_json:
        out(json.dumps({"stamp": stamp, "state": state,
                        "line": _tree_stamp.format_stamp(stamp)},
                       indent=2, sort_keys=True))
    else:
        out("\n".join(_tree_stamp.render_stamp(stamp, state)))
    return 0


def run_compare(args, out, stdin=None):
    """`compare`: grade a stamp against the tree now, in one of three words."""
    if args.files or args.task:
        # The scope rides INSIDE the stamp. Accepting a second one here would let
        # a comparison quietly answer about a different file set than the stamp
        # was taken over, which is the whole defect this command exists to catch.
        sys.stderr.write("ERROR: compare takes its scope from the stamp, so "
                         "--files/--task would be a second answer to which work "
                         "this is about\n")
        return E_USAGE
    text, problem = read_stamp_text(args, stdin=stdin)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    stamp, problem = _tree_stamp.parse_stamp(text)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    result = _tree_stamp.compare(stamp, os.path.abspath(args.project))
    if args.as_json:
        out(json.dumps(result, indent=2, sort_keys=True))
    else:
        out("\n".join(_tree_stamp.render_comparison(result)))
    return EXIT_FOR[result["verdict"]]


def main(argv, out=print, stdin=None):
    argv = list(argv)
    # Everything after the first `--` is the red run's command, kept away from the
    # parser so a test command's own flags are never read as this command's.
    cmd = argv[argv.index("--") + 1:] if "--" in argv else None
    argv = argv[:argv.index("--")] if "--" in argv else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return E_USAGE if exc.code else 0
    if args.action == "red":
        return run_red(args, cmd, out)
    if cmd is not None:
        sys.stderr.write("ERROR: only `red` takes a command after `--`\n")
        return E_USAGE
    if args.action == "take":
        return run_take(args, out)
    return run_compare(args, out, stdin=stdin)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    # Only this command's own flags: after `--` a `--selftest` belongs to the red
    # run's test command.
    _own = sys.argv[1:sys.argv.index("--")] if "--" in sys.argv else sys.argv[1:]
    if "--selftest" in _own:
        # Answers rather than falling through to a usage error, which would read
        # as a broken flag rather than as a moved suite. It deliberately does NOT
        # print the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("stamp-verification.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test_stamp_verification.py - run that file "
              "instead.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
