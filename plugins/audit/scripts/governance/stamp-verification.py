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
                                [--case ID|LABEL ...] [--introduces SYMBOL ...]
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
import ast
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

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
import _locks  # noqa: E402  (pid_alive: whether a leftover throwaway's owner still runs)

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
V_MIXED = "mixed-tally"

# The host's Bash tool gives a command at most this many seconds, and a helper it
# kills never reaches its own `finally`. The default stays under it with room for
# the teardown, so the helper's own timeout is the one that fires.
HOST_BASH_LIMIT = 600
DEFAULT_TIMEOUT = 480
# ONE deadline, `--timeout`, starts before anything runs and covers every git
# call that builds or reads the throwaway and both runs: each stage gets what the
# earlier ones left. What happens after the deadline has to fit in the rest of
# the host's limit, so it is bounded and summed here: one teardown of a timed-out
# run (`_proc_group.GRACE_SECONDS` for SIGTERM, again for SIGKILL, again for the
# drain - two runs cannot both time out, the second is only made when the first
# finished), and the removal's two git calls, each capped at `REMOVE_GIT_TIMEOUT`.
# Copying files and deleting the temp directory are local and are not budgeted.
REMOVE_GIT_TIMEOUT = 10
TEARDOWN_MARGIN = 3 * _proc_group.GRACE_SECONDS + 2 * REMOVE_GIT_TIMEOUT
MAX_TIMEOUT = HOST_BASH_LIMIT - TEARDOWN_MARGIN

# Every throwaway's temp directory starts with this, which is how a leftover from
# a run nobody could clean up is recognised in `git worktree list`.
THROWAWAY_PREFIX = "audit-red-"
# ...and the file in that directory naming the process that made it, which is
# what tells a stranded throwaway from one a sibling's run is still using.
OWNER_FILE = "owner.json"

# What the child's environment loses: these variables whole, and - by PATH, not
# by substring - every other value that IS a path under the shared root, or the
# entries of a path list that are. A variable that merely mentions the root in
# text, or names a sibling directory sharing its prefix, is kept.
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
# A house case's id is its label's leading token when that token carries a digit
# (`me1`, `ga9b`, `pc-sd0`) - the key the harness's `case_id()` hands out and
# prove-gates attributes a mutation by. A label led by an ordinary word has no id
# and is named by the whole label: its first word is one HEAD's test file almost
# always carries too, so reading it as an id refuses the task's own case.
_HOUSE_CASE_ID = re.compile(r"^[A-Za-z][A-Za-z_-]*[0-9][A-Za-z0-9_-]*$")
# A template's fixed text names a label only when it holds a run of two letters.
_ANCHORING_WORD = re.compile(r"[^\W\d_]{2}")
# A `.format` field; `{{` and `}}` stand for themselves.
_FORMAT_FIELD = re.compile(r"\{\{|\}\}|\{[^{}]*\}")
# A %-placeholder inside a label literal; `%%` is the one that stands for itself.
_PLACEHOLDER = re.compile(r"%(?:\([^)]*\))?[#0 +-]*(?:\*|\d+)?(?:\.(?:\*|\d+))?"
                          r"[A-Za-z%]")
# With no tally, a traceback ending in one of these is a run that never reached an
# assertion; any other tally-less failure is `no-tally`, a crash nobody classified.
_COMPILE_ERROR = re.compile(r"^\s*(?:E\s+)?(SyntaxError|IndentationError|TabError|"
                            r"ImportError|ModuleNotFoundError|NameError|"
                            r"AttributeError)\b", re.M)
_ERROR_LINE = re.compile(r"^\s*(\w*(?:Error|Exception)\b.*)$", re.M)
# pytest prints a collection error's exception behind an `E   ` gutter.
_FINAL_ERROR = re.compile(r"^\s*(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception)):\s?(.*)$",
                          re.M)

# The error classes a missing symbol produces. A syntax error never qualifies: it
# is the test's own text failing to parse, and it survives any fix.
INTRODUCES_CLASSES = ("ImportError", "ModuleNotFoundError", "AttributeError",
                      "NameError")
_SYMBOL_SHAPE = re.compile(r"^[A-Za-z_][\w.]*$")


def house_case_id(label):
    """The label's leading token when it is id-shaped, else None."""
    head = label.split(None, 1)
    if not head or not _HOUSE_CASE_ID.match(head[0]):
        return None
    return head[0]


def _house_cases(text):
    out = []
    for ln in text.splitlines():
        if ln.startswith("FAIL ") and not any(m in ln for m in HOUSE_ESCAPES):
            label = ln[len("FAIL "):].strip()
            out.append({"id": house_case_id(label), "label": label,
                        "assertion": True, "why": "house FAIL"})
    return out


def _pytest_cases(text):
    out = []
    for kind, node, why in _PYTEST_FAILED.findall(text):
        why = (why or "").strip()
        out.append({"id": node.split("::")[-1], "label": node,
                    "assertion": kind == "FAILED"
                    and (why.startswith("assert") or why.startswith("AssertionError")),
                    "why": why or kind})
    return out


def _unittest_cases(text):
    return [{"id": name, "label": name, "assertion": kind == "FAIL", "why": kind}
            for kind, name in _UNITTEST_CASE.findall(text)]


CASE_READERS = {"house": _house_cases, "pytest": _pytest_cases,
                "unittest": _unittest_cases}


def failing_cases(text, runner=None):
    """`[{"id", "label", "assertion", "why"}]` - every failing case the runner
    that ran named; `runner` defaults to the one `read_tally()` selects.

    Only that runner's lines are read, never another's whose tally line merely
    appears in the output: a passing house case may print
    `ERROR: <path> is not a directory` because it asserts on that message, or
    echo a whole captured unittest transcript, `Ran N tests` line included; a
    test under another runner may print a line that opens with `FAIL `. No
    tally, no runner, no cases. `label` is the whole name as printed; `id` is
    the part a case is keyed by, None for a house label with no id-shaped lead.

    `assertion` is True only where the runner says the case failed an assertion:
    a house `FAIL` line that is not an escape, a pytest `FAILED` whose reason is
    an `assert` or an `AssertionError`, a unittest `FAIL:`. A pytest `ERROR`, a
    pytest body exception and a unittest `ERROR:` are named with it False."""
    if runner is None:
        tally = read_tally(text)
        runner = tally["runner"] if tally is not None else None
    reader = CASE_READERS.get(runner)
    return reader(text) if reader is not None else []


def _house_tally(text):
    hits = _HOUSE_TALLY.findall(text)
    if not hits:
        return None
    passed, total = int(hits[-1][0]), int(hits[-1][1])
    asserting = _house_cases(text)
    return {"runner": "house", "collected": total, "failed": total - passed,
            "assertions": len(asserting)}


def _pytest_tally(text):
    hits = _PYTEST_SUMMARY.findall(text)
    if not hits:
        return None
    counts = dict((kind.rstrip("s") if kind.startswith("error") else kind, int(n))
                  for n, kind in _PYTEST_COUNT.findall(hits[-1]))
    ran = sum(counts.get(k, 0) for k in ("failed", "passed", "xfailed", "xpassed"))
    asserting = [c for c in _pytest_cases(text) if c["assertion"]]
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


TALLY_READERS = (("house", _house_tally), ("pytest", _pytest_tally),
                 ("unittest", _unittest_tally))


def command_runner(cmd):
    """The runner a test command names - `pytest`, `python -m unittest`, a house
    `--selftest` - or None when it names none, or more than one."""
    args = [str(a) for a in (cmd or ())]
    named = set()
    for i, arg in enumerate(args):
        base = os.path.basename(arg)
        follows_m = i > 0 and args[i - 1] == "-m"
        if base in ("pytest", "py.test") or (follows_m and arg == "pytest"):
            named.add("pytest")
        elif follows_m and arg == "unittest":
            named.add("unittest")
        elif arg == "--selftest":
            named.add("house")
    return named.pop() if len(named) == 1 else None


def read_tally(text, cmd=None):
    """The tally of the runner that ran, or None when no known runner printed one.

    One runner's tally is that runner's. When more than one appears - a house
    case echoing a captured unittest transcript, a unittest test printing a
    house tally - neither the order they were printed in nor a precedence
    between runners says which ran: a merged pipe puts a test's buffered
    stdout after the runner's own stderr. So the command decides when it names
    a runner (`command_runner`), and otherwise the answer is
    `{"runner": None, "mixed": [...]}`, which no reader reads cases from."""
    tallies = [t for t in (reader(text) for _name, reader in TALLY_READERS)
               if t is not None]
    if not tallies:
        return None
    if len(tallies) == 1:
        return tallies[0]
    named = [t for t in tallies if t["runner"] == command_runner(cmd)]
    if named:
        return named[0]
    return {"runner": None, "mixed": [t["runner"] for t in tallies],
            "collected": 0, "failed": 0, "assertions": 0}


def classify_run(code, text, cmd=None):
    """`(verdict, tally)` for one run: `green` / `red` / `collection-error` /
    `mixed-tally` / `no-tally`. Exit 0 is `green` whatever the output says."""
    tally = read_tally(text, cmd)
    if code == 0:
        return V_GREEN, tally
    if tally is None:
        return (V_COLLECT if _COMPILE_ERROR.search(text) else V_NO_TALLY), None
    if tally["runner"] is None:
        return V_MIXED, tally
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


def _under(value, roots):
    """Whether `value` is one of `roots` or a path beneath one - a separator
    boundary, so `/repo-other` is not under `/repo`."""
    if not value or not os.path.isabs(value):
        return False
    spellings = set((value, os.path.realpath(value)))
    return any(v == r or v.startswith(r.rstrip("/\\") + sep)
               for v in spellings for r in roots for sep in ("/", os.sep))


# An option string - NODE_OPTIONS, PYTEST_ADDOPTS - is not a path to rewrite, but
# a runner reads the paths inside it: split on whitespace, `=` and the path-list
# separator to find them.
_TOKEN_SPLIT = re.compile(r"[\s=%s]+" % (re.escape(os.pathsep),))


def child_env(root, environ=None):
    """`(env, dropped, naming)` - the environment without what reaches the shared
    tree, and the kept variables that still NAME a path under it.

    `SCRUBBED_ENV` goes whole; any other variable whose value IS a path under the
    root goes; a path list keeps its other entries and loses the ones under the
    root, so an in-repo `.venv/bin` leaves PATH without taking PATH with it.
    `dropped` names every variable and every list entry removed. A value that is
    not itself a path but carries one under the root - an option string such as
    `--require /repo/test/setup.js` - is kept and listed in `naming`, because a
    runner reads it as a path into the shared tree and the basis must say so."""
    source = os.environ if environ is None else environ
    roots = [r for r in set((root, os.path.realpath(root))) if r]
    env, dropped, naming = {}, [], []
    for key in sorted(source):
        value = source[key]
        if key in SCRUBBED_ENV:
            dropped.append(key)
            continue
        parts = value.split(os.pathsep) if os.pathsep in value else [value]
        gone = [p for p in parts if _under(p, roots)]
        if not gone:
            env[key] = value
            if any(_under(tok, roots) for tok in _TOKEN_SPLIT.split(value)):
                naming.append(key)
        elif len(parts) == 1 or len(gone) == len(parts):
            dropped.append(key)
        else:
            env[key] = os.pathsep.join(p for p in parts if p not in gone)
            dropped.extend("%s entry %s" % (key, p) for p in gone)
    return env, dropped, naming


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


def _split(text, fields, escapes):
    """`text`'s fixed pieces, split at each hit of `fields` - `escapes` maps
    the hits that stand for a fixed character (`%%`, `{{`) to that character."""
    pieces, cur, at = [], [], 0
    for hit in fields.finditer(text):
        cur.append(text[at:hit.start()])
        if hit.group() in escapes:
            cur.append(escapes[hit.group()])
        else:
            pieces.append("".join(cur))
            cur = []
        at = hit.end()
    cur.append(text[at:])
    pieces.append("".join(cur))
    return pieces


def _joined(left, right):
    return left[:-1] + [left[-1] + right[0]] + right[1:]


def _fold(node):
    """The fixed pieces of the text an expression renders, open between them
    wherever a value goes - or None when no literal text is in it.

    A literal's `%` placeholders are open, and `template % values` is its
    template. `+` joins literals, and a non-literal operand joined to one is
    open where its value goes; an f-string field and a `.format` field are
    open too. So a label built at run time is a template of its own rather
    than no literal at all, and outranks a generic template that fits it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _split(node.value, _PLACEHOLDER, {"%%": "%"})
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _fold(node.left)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        if left is None and right is None:
            return None
        return _joined(left or ["", ""], right or ["", ""])
    if isinstance(node, ast.JoinedStr):
        pieces = [""]
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces[-1] += part.value
            else:
                pieces.append("")
        return pieces
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format" and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)):
        return _split(node.func.value.value, _FORMAT_FIELD, {"{{": "{", "}}": "}"})
    return None


def _names_a_label(pieces):
    """Whether a template is anchored enough to name a label: one with no open
    part, or one whose fixed text holds a run of two letters - `'%dx%d'`,
    `' (%s)'` and `'%s: %s'` render labels they were never written for."""
    return any(pieces) and (len(pieces) == 1
                            or bool(_ANCHORING_WORD.search("".join(pieces))))


def _renders(pieces, form):
    """Whether a template's pieces render `form` whole, each gap any text.

    Linear and without a regex engine: the first piece anchors the start, the
    last the end, the middle ones are found left to right. A pattern of lazy
    wildcards backtracks combinatorially on a many-placeholder literal, and this
    runs after the red run, outside what --timeout bounds."""
    if len(pieces) == 1:
        return form == pieces[0]
    first, last = pieces[0], pieces[-1]
    if (len(form) < len(first) + len(last) or not form.startswith(first)
            or not form.endswith(last)):
        return False
    at, end = len(first), len(form) - len(last)
    for middle in pieces[1:-1]:
        hit = form.find(middle, at, end)
        if hit < 0:
            return False
        at = hit + len(middle)
    return True


def _label_forms(label):
    """The label as printed and the label before each ` (` it holds - a house
    FAIL line appends its detail that way, and a detail spanning lines leaves
    the line with no closing paren."""
    return [label] + [label[:i] for i in range(len(label)) if label.startswith(" (", i)]


def _callee(call):
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _case_callees(tree):
    """`{name: position}` - the calls in a suite whose argument at `position`
    names a case.

    Derived from the file rather than listed: `check` and every body's own name
    for it (the first parameter of a function handed to the harness's `stage`
    or `run`) take the label first, the harness's `skip` takes it second, and a
    suite's wrapper that passes one of its parameters on to such a call at a
    label position (`_expect(name, ...)` calling `check(name, ...)`) names a
    case at that parameter's position - followed until nothing new appears."""
    callees = {"check": 0, "skip": 1}
    defs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    by_name = dict((d.name, d) for d in defs)
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        if _callee(call) not in ("stage", "run"):
            continue
        for arg in call.args:
            body = by_name.get(arg.id) if isinstance(arg, ast.Name) else None
            if body is not None and body.args.args:
                callees.setdefault(body.args.args[0].arg, 0)
    grew = True
    while grew:
        grew = False
        for fn in defs:
            params = [a.arg for a in fn.args.args]
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
                at = callees.get(_callee(call))
                arg = call.args[at] if at is not None and len(call.args) > at else None
                if (isinstance(arg, ast.Name) and arg.id in params
                        and fn.name not in callees):
                    callees[fn.name] = params.index(arg.id)
                    grew = True
    return callees


def _case_label_nodes(tree):
    """The argument nodes that name a case, by identity."""
    callees = _case_callees(tree)
    out = set()
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        at = callees.get(_callee(call))
        if at is not None and len(call.args) > at:
            out.add(id(call.args[at]))
    return out


def _source_view(text):
    """`{"text", "labels", "others"}` for one copy of a test file: the fixed
    pieces of every literal it spells, split by ROLE - the ones that are a case
    call's label argument, and every other one - or both None when it is not
    Python."""
    text = text or ""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {"text": text, "labels": None, "others": None}
    naming = _case_label_nodes(tree)
    labels, others = set(), set()
    for node in ast.walk(tree):
        pieces = _fold(node)
        if pieces and _names_a_label(pieces):
            (labels if id(node) in naming else others).add(tuple(pieces))
    return {"text": text, "labels": sorted(labels), "others": sorted(others - labels)}


def _closest_in(templates, forms):
    """Within one role: a literal with no open part that EQUALS a form, the
    longest such form winning; else the templates with the most fixed text."""
    exact = set(p[0] for p in templates if len(p) == 1)
    matched = [form for form in forms if form in exact]
    if matched:
        return [(max(matched, key=len),)]
    scored = [(len("".join(p)), p) for p in templates
              if any(_renders(list(p), form) for form in forms)]
    if not scored:
        return []
    best = max(score for score, _p in scored)
    return [p for score, p in scored if score == best]


def _closest_literals(view, label):
    """The literals of `view` a label was most plausibly written from, as
    tuples of fixed pieces. Empty when none renders it; None when the file is
    not Python.

    ROLE FIRST: a literal that is a case call's label argument outranks every
    other literal, so a constant or an expected-output string the task adds -
    even one spelling the printed FAIL line verbatim, detail included - never
    outranks the label argument that names the case. Other literals are read
    only when no label argument renders the label (a label taken from a
    table). Within a role, a literal equal to the label or to the label with
    its detail set aside outranks any template, the longest such form wins -
    so a new label holding a parenthesis still beats an older, shorter one -
    and only then does the template with the most fixed text decide."""
    if view["labels"] is None:
        return None
    forms = _label_forms(label)
    return _closest_in(view["labels"], forms) or _closest_in(view["others"], forms)


def _carries_label(text, label):
    """Whether a test file's source spells `label`: some literal in it renders
    the whole label, or - for a file that is not Python - it holds the text."""
    if not text or not label:
        return False
    view = _source_view(text)
    closest = _closest_literals(view, label)
    if closest is None:
        return any(form in text for form in _label_forms(label))
    return bool(closest)


def _standing(wt, head, name):
    """`added` / `at-head` / `absent` - case `name` in one test file's two copies.

    A single token is a whole name. A label is judged by the working tree's
    closest literal (`_closest_literals`): the task added it when HEAD's copy
    holds none of those literals. HEAD is never asked whether some looser
    literal of its own renders the label too - a generic message template
    there would refuse every new case whose label it happens to fit.

    WHAT THIS CANNOT SEE. A label that no literal in HEAD spells even in part -
    read from a file, computed, assembled from values alone - has no literal
    at HEAD, so a literal the task adds that renders it reads as the task's
    own. And a label that no case call's argument spells (a table row fed to
    `check` by a loop) is judged among the other literals, where a longer one
    the task adds - a verbatim FAIL line, detail included - outranks it."""
    if len(name.split()) <= 1:
        in_wt, at_head = _names(wt["text"], name), _names(head["text"], name)
    elif wt["labels"] is None or head["labels"] is None:
        forms = _label_forms(name)
        in_wt = any(form in wt["text"] for form in forms)
        at_head = any(form in head["text"] for form in forms)
    else:
        closest = _closest_literals(wt, name)
        held = set(head["labels"]) | set(head["others"])
        in_wt = bool(closest)
        at_head = (any(lit in held for lit in closest) if closest
                   else bool(_closest_literals(head, name)))
    if at_head:
        return "at-head"
    return "added" if in_wt else "absent"


def _test_views(root, tests):
    """`[(wt_view, head_view)]` - each declared test file, parsed once."""
    return [(_source_view(_wt_text(root, rel)), _source_view(_head_text(root, rel)))
            for rel in tests]


def _added_standing(views, name):
    """The best standing any declared test file gives case `name`."""
    got = [_standing(wt, head, name) for wt, head in views]
    for word in ("added", "at-head"):
        if word in got:
            return word
    return "absent"


def _added_by_task(root, tests, name):
    """Whether case `name` - an id, or a house label with no id - is one the
    task added to a declared test file."""
    return _added_standing(_test_views(root, tests), name) == "added"


def _is_named(failure, name):
    """Whether `--case NAME` names this failing case: its id, or its label as
    printed, with or without the detail a house FAIL line appends."""
    label = failure.get("label") or ""
    return name == failure.get("id") or name in _label_forms(label)


def _case_key(failure):
    return failure["id"] or failure["label"]


def own_failures(root, tests, failing, cases):
    """`(own, refused)` - the failing cases that are the TASK'S OWN and failed an
    assertion, and `[(name, "at-head"|"absent")]` for each `--case` name that
    is not one of the task's own cases.

    Own means a case the task ADDED: its id - or, for a house label with no
    id-shaped lead, its whole label - is carried by the working tree's copy of a
    declared test file and not by HEAD's copy of it. `--case` narrows to the
    cases it names, by id or by full label, and is held to the same test,
    because the flag is chosen by the party whose proof is being checked - an
    existing case going red because its test file was edited to match other work
    is not a proof about this task's test, whoever names it. A name is refused
    by the same match that decides the proof: resolved to the failing cases it
    names, and judged by their key, so a pytest nodeid is judged as its test."""
    views = _test_views(root, tests)
    refused = []
    for name in cases:
        keys = [_case_key(f) for f in failing if _is_named(f, name)] or [name]
        got = [_added_standing(views, key) for key in keys]
        if "added" not in got:
            refused.append((name, "at-head" if "at-head" in got else "absent"))
    asserting = [f for f in failing if f["assertion"] and _case_key(f)]
    if cases:
        asserting = [f for f in asserting if any(_is_named(f, c) for c in cases)]
    return ([f for f in asserting if _added_standing(views, _case_key(f)) == "added"],
            refused)


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
def leftover_throwaways(root, timeout=120):
    """`[{"path", "state", "pid"}]` - registered worktrees whose path carries
    `THROWAWAY_PREFIX`, each graded by the process its `OWNER_FILE` names:
    `running` while that process is alive (a sibling's `red`, still going),
    `left-behind` once it is gone, `unknown` with no owner record. Reported,
    never pruned. A reused pid reads as `running`, the safe direction."""
    code, listing = _git(root, ["worktree", "list", "--porcelain"], timeout=timeout)
    if code != 0:
        return []
    out = []
    for ln in listing.splitlines():
        if not ln.startswith("worktree "):
            continue
        path = ln[len("worktree "):]
        if not any(part.startswith(THROWAWAY_PREFIX)
                   for part in path.replace("\\", "/").split("/")):
            continue
        pid = None
        try:
            with open(os.path.join(os.path.dirname(path), OWNER_FILE), "r",
                      encoding="utf-8") as fh:
                pid = json.load(fh).get("pid")
        except (OSError, ValueError, AttributeError):
            pid = None
        alive = _locks.pid_alive(pid) if pid is not None else None
        out.append({"path": path, "pid": pid,
                    "state": {True: "running", False: "left-behind"}.get(alive,
                                                                         "unknown")})
    return out


def leftover_line(left):
    """One leftover throwaway as the human output says it: what its owner record
    establishes, and never more."""
    if left["state"] == "running":
        return "registered by a run still going (pid %s) - not pruned" % (left["pid"],)
    if left["state"] == "left-behind":
        return ("LEFT BEHIND by an earlier run (pid %s is gone) - not pruned"
                % (left["pid"],))
    return ("registered by another run - left behind, or still running (no owner "
            "record) - not pruned")


def holder_base(root):
    """A temp directory OUTSIDE the shared tree, or None. A TMPDIR pointing inside
    the repository would put the throwaway worktree where siblings' `git status`
    sees it, so the platform's own temp directories are tried next."""
    roots = [r for r in set((root, os.path.realpath(root))) if r]
    candidates = [tempfile.gettempdir()]
    if os.name != "nt":
        candidates += ["/tmp", "/var/tmp"]
    for cand in candidates:
        if os.path.isdir(cand) and not _under(os.path.abspath(cand), roots):
            return cand
    return None


def _build_throwaway(root, path, tests, timeout=120):
    """`(copied, problem)`: HEAD checked out at `path`, the tests laid over it."""
    code, text = _git(root, ["worktree", "add", "--detach", "--quiet", path, "HEAD"],
                      timeout=timeout)
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
    _git(root, ["worktree", "remove", "--force", path], timeout=REMOVE_GIT_TIMEOUT)
    shutil.rmtree(holder, ignore_errors=True)
    code, listing = _git(root, ["worktree", "list", "--porcelain"],
                         timeout=REMOVE_GIT_TIMEOUT)
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


_TALLY_KEYS = {"house": "cases ", "pytest": " in ", "unittest": "Ran "}


def _decisive_line(text, tally):
    """The line a reader checks the verdict against: the tally, else the error."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if tally is not None and tally["runner"] in _TALLY_KEYS:
        hits = [ln for ln in lines if _TALLY_KEYS[tally["runner"]] in ln]
        if hits:
            return hits[-1]
    errors = _ERROR_LINE.findall(text)
    if errors:
        return errors[-1].strip()
    return lines[-1] if lines else "(no output)"


def _ids(cases):
    return _output.some_of(["%s (%s)" % (c["id"] or c["label"] or "?", c["why"])
                            for c in cases])


def _refused_clause(refused):
    """The basis clause for the `--case` names that are not the task's own."""
    at_head = [name for name, why in refused if why == "at-head"]
    absent = [name for name, why in refused if why != "at-head"]
    clause = ""
    if at_head:
        clause += ("; --case %s names a case HEAD's test file already carries, "
                   "so it is not the task's" % (", ".join(at_head),))
    if absent:
        clause += ("; --case %s names no case a declared test file in the "
                   "working tree carries" % (", ".join(absent),))
    return clause


def red_verdict(run, ctx):
    """`(exit, verdict, block, note)` - what the run in the throwaway proved.

    `run` is `{"cmd", "code", "text", "problem", "second"}`; `second` is the
    re-run with the working tree's implementation copied in, when one was made.
    `ctx` is `{"root", "implementation", "tests", "cases", "symbols",
    "dropped"}`."""
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    shown = " ".join(run["cmd"])
    env_clause = "; run without %s" % (", ".join(ctx["dropped"]) or "nothing",)
    if ctx.get("naming"):
        env_clause += ("; kept, naming the shared root: %s - the run may have read "
                       "shared-tree files through it" % (", ".join(ctx["naming"]),))
    if run["problem"] is not None:
        return E_CANNOT_PROVE, V_NOT_RUN, {
            "status": RED_CANNOT, "at": at,
            "basis": "`%s` in a throwaway tree at HEAD: %s%s"
                     % (shown, run["problem"], env_clause)}, None
    code, text = run["code"], run["text"]
    verdict, tally = classify_run(code, text, run["cmd"])
    line = _decisive_line(text, tally)
    where = "`%s` in a throwaway tree at HEAD exited %d" % (shown, code)
    if verdict == V_GREEN:
        return E_NOT_RED, verdict, None, (
            "%s (%s): the test PASSED in the throwaway - HEAD's implementation with "
            "this task's test files, run with %s removed from its environment - so "
            "it proves nothing yet; fix the test, there is no redFirst word to "
            "record for this" % (where, line, ", ".join(ctx["dropped"]) or "nothing"))
    failing = (failing_cases(text, tally["runner"])
               if tally is not None and tally["runner"] is not None else [])
    how = ("named by --case and absent from HEAD's test files" if ctx["cases"]
           else "added by the task, absent from HEAD's test files")
    if verdict == V_RED:
        own, refused = own_failures(ctx["root"], ctx["tests"], failing, ctx["cases"])
        refused_clause = _refused_clause(refused)
        if own:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s with %d of %d collected tests failing an assertion, "
                         "the task's own among them (%s) - %s: %s%s%s"
                         % (where, tally["assertions"], tally["collected"], how,
                            _ids(own), line, refused_clause, env_clause)}, None
        return E_CANNOT_PROVE, verdict, {
            "status": RED_CANNOT, "at": at,
            "basis": "%s, but none of the failing cases is the task's own (%s): %s "
                     "- %s%s%s" % (where, how, _ids(failing), line, refused_clause,
                                   env_clause)}, None
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
        elif classify_run(second["code"], second["text"],
                          run["cmd"])[0] not in (V_GREEN, V_RED):
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
                         "assertions%s" % (where, error, symbol, why,
                                           second["code"], env_clause)}, None
    if verdict == V_MIXED:
        reason = ("its output carries the tallies of more than one runner (%s) and "
                  "the command names none of them, so which runner ran - and "
                  "whose failing cases are its own - cannot be told"
                  % ("; ".join("%s: %s" % (r, _decisive_line(text, {"runner": r}))
                               for r in tally["mixed"]),))
    elif verdict == V_COLLECT:
        reason = "no test was collected or none reached an assertion"
    else:
        reason = ("its output carries no test tally this command reads, so an "
                  "assertion failure cannot be told from a crash - no test is "
                  "known to have been collected")
    if failing:
        reason += "; failing without an assertion: %s" % (_ids(failing),)
    return E_CANNOT_PROVE, verdict, {
        "status": RED_CANNOT, "at": at,
        "basis": "%s, but %s: %s%s%s" % (where, reason, line,
                                         ("; " + "; ".join(why_not)) if why_not
                                         else "", env_clause)}, None


def _wants_second(code, text, symbols, cmd=None):
    """Whether a second run is owed: a collection error some named symbol's
    missing-symbol error could explain."""
    verdict, _t = classify_run(code, text, cmd) if code is not None else (None, None)
    return verdict == V_COLLECT and any(qualifying_error(text, s) for s in symbols)


def _left(deadline):
    """Whole seconds left before `deadline`; 0 or less when it has passed."""
    return int(deadline - time.time())


def _red_scope(args, cmd, deadline):
    """`(scope, problem)` - everything `red` needs before it builds anything."""
    if not cmd:
        return None, "red needs the test command after `--`"
    if not (args.task and args.manifest) or args.files:
        return None, ("red takes its scope off the plan: pass --manifest and "
                      "--task, and no --files")
    if not 1 <= args.timeout <= MAX_TIMEOUT:
        return None, ("--timeout %s is outside 1..%d: one deadline covers both runs, "
                      "and it must leave the host's %d-second Bash limit room for "
                      "the teardown, or the host kills the helper before its own "
                      "cleanup runs" % (args.timeout, MAX_TIMEOUT, HOST_BASH_LIMIT))
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
    code, root = _git(os.path.abspath(args.project), ["rev-parse", "--show-toplevel"],
                      timeout=max(1, _left(deadline)))
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
    deadline = time.time() + args.timeout
    scope, problem = _red_scope(args, cmd, deadline)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    root = scope["root"]
    leftovers = leftover_throwaways(root, timeout=max(1, _left(deadline)))
    env, dropped, naming = child_env(root)
    _c, head = _git(root, ["rev-parse", "HEAD"], timeout=max(1, _left(deadline)))
    base = holder_base(root)
    if base is None:
        sys.stderr.write("ERROR: every temp directory this machine offers is inside "
                         "the shared tree %s, and a throwaway there would be a "
                         "worktree siblings see; set TMPDIR outside it\n" % (root,))
        return E_USAGE
    holder = tempfile.mkdtemp(prefix=THROWAWAY_PREFIX, dir=base)
    path = os.path.join(holder, "tree")
    try:
        with open(os.path.join(holder, OWNER_FILE), "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid()}, fh)
    except OSError:
        pass
    run = {"cmd": cmd, "code": None, "text": "", "problem": None, "second": None}
    copied = []
    previous = _arm()
    try:
        try:
            copied, run["problem"] = _build_throwaway(
                root, path, scope["tests"], timeout=max(1, _left(deadline)))
            if run["problem"] is None and _left(deadline) < 1:
                run["problem"] = ("the run timed out: building the throwaway spent "
                                  "the %s-second deadline" % (args.timeout,))
            if run["problem"] is None:
                run["code"], run["text"], run["problem"] = _run_in(
                    path, cmd, _left(deadline), env)
            if run["problem"] is None and _wants_second(run["code"], run["text"],
                                                        args.introduces, cmd):
                _lay_over(root, path, scope["implementation"])
                left = _left(deadline)
                if left < 1:
                    code2, text2, problem2 = None, "", (
                        "the run timed out: no time was left of the %s-second "
                        "deadline" % (args.timeout,))
                else:
                    code2, text2, problem2 = _run_in(path, cmd, left, env)
                run["second"] = {"code": code2, "text": text2, "problem": problem2}
        except KeyboardInterrupt as exc:
            run["problem"] = ("interrupted by %s before the run finished; the "
                              "run's process group was torn down"
                              % (exc or "an interrupt",))
        exit_code, verdict, block, note = red_verdict(run, {
            "root": root, "implementation": scope["implementation"],
            "tests": scope["tests"], "cases": args.case,
            "symbols": args.introduces, "dropped": dropped, "naming": naming})
    finally:
        removed = _remove_throwaway(root, holder, path)
        if previous is not None:
            _proc_group.disarm_interrupt(previous)
    payload = {"verdict": verdict, "redFirst": block, "note": note,
               "atHead": scope["implementation"], "copied": copied,
               "leftovers": leftovers,
               "environment": {"dropped": dropped, "naming": naming},
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
        if naming:
            out("  kept, naming the shared root: %s" % (", ".join(naming),))
        for left in leftovers:
            out("  %s: %s" % (leftover_line(left), left["path"]))
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
                        help="the id or full label of a case the task added; "
                             "`red` only - a red "
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
