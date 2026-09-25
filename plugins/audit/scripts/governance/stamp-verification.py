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
                                [--introduces SYMBOL ...] [--timeout S] [--json]
                                -- <test command>

  `compare` reads the stamp from stdin when neither --stamp nor --stamp-file is
  given, so a report or a commit message can be piped straight in.

Exit codes:
  0  compare: current - every field git could answer still agrees
     take:    the stamp was taken
  1  compare: STALE - the tree has moved, and the output names which field did
  3  compare: unestablished - git could not answer, so nothing was graded
  2  usage error, an unreadable manifest, a task id that is not there, or a stamp
     this code cannot read
  red: 0 proved - 1 not red (the test passes without the fix) - 3 could not
     prove (the run reached no assertion, or could not run) - 4 the throwaway
     tree could not be removed - 2 as above, and for a task with no test file or
     a command that names the shared tree

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
temp directory and the worktree registration for it, and removes both.
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
# and its implementation files left at HEAD. The shared working tree is only read.
#
# WHAT IT DOES WRITE, so nobody has to discover it: `git worktree add` registers
# the throwaway in the repository's administrative directory, and the `finally`
# below removes that registration with the directory and then asks git whether
# either is still there. A registration it could not remove is its own exit code,
# never folded into the verdict.
E_PROVED, E_NOT_RED, E_CANNOT_PROVE, E_LEFT_BEHIND = 0, 1, 3, 4

# The words this command writes, each one the schema's `redFirst.status` enum
# declares. A green run has no word here on purpose: a test that passes without
# the fix is work left to do, not an outcome to record.
RED_PROVED = "proved"
RED_CANNOT = "could-not-prove"
RED_WORDS = (RED_PROVED, RED_CANNOT)

V_RED, V_GREEN = "red", "green"
V_COLLECT, V_NO_TALLY, V_NOT_RUN = "collection-error", "no-tally", "could-not-run"

DEFAULT_TIMEOUT = 900

# A task's declared file is a TEST file when `tests.add` names it or its path has
# the conventional test shape; everything else it declares is implementation and
# stays at HEAD. The split is printed with every run, because it decides what the
# red is a red OF.
_TEST_DIRS = ("tests", "test", "__tests__", "spec")
_TEST_NAME = re.compile(r"^(test_.+|.+_test\.[^.]+|.+\.(test|spec)\.[^.]+)$")

# --- the tally a verdict is read from ---
# `red` needs a COUNT: at least one test collected and at least one assertion
# failing. A non-zero exit alone is not that - a compile error, an import error
# and a runner that collected nothing all exit non-zero with no assertion ever
# evaluated, and reading them as red is how a test that asserts nothing gets
# credited with a proof. A runner whose tally this does not read is `no-tally`
# and never promoted to `red`.
#
# The house harness marks a block that raised while being BUILT with one of
# these labels, so a house suite whose every failure is one of them collected
# nothing that asserted.
HOUSE_ESCAPES = ("RAISED WHILE ITS CASES WERE BEING BUILT",
                 "selftest body raised before reaching the end")
_HOUSE_TALLY = re.compile(r"^(?:ALL PASS|SELFTEST FAILED): (\d+)/(\d+) "
                          + "cases " + "passed", re.M)
_PYTEST_SUMMARY = re.compile(r"^=+ (.*?) in [\d.]+s.*=+\s*$", re.M)
_PYTEST_COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed)")
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
_UNITTEST_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
# With no tally, a traceback ending in one of these is a run that never reached an
# assertion; any other tally-less failure is `no-tally`, a crash nobody classified.
_COMPILE_ERROR = re.compile(r"^\s*(SyntaxError|IndentationError|TabError|ImportError|"
                            r"ModuleNotFoundError|NameError)\b", re.M)
_ERROR_LINE = re.compile(r"^\s*(\w*(?:Error|Exception)\b.*)$", re.M)


def _house_tally(text):
    hits = _HOUSE_TALLY.findall(text)
    if not hits:
        return None
    passed, total = int(hits[-1][0]), int(hits[-1][1])
    fails = [ln for ln in text.splitlines() if ln.startswith("FAIL ")]
    asserting = [ln for ln in fails if not any(m in ln for m in HOUSE_ESCAPES)]
    return {"runner": "house", "collected": total, "failed": total - passed,
            "assertions": len(asserting)}


def _pytest_tally(text):
    hits = _PYTEST_SUMMARY.findall(text)
    if not hits:
        return None
    counts = dict((kind.rstrip("s") if kind.startswith("error") else kind, int(n))
                  for n, kind in _PYTEST_COUNT.findall(hits[-1]))
    failed = counts.get("failed", 0)
    ran = sum(counts.get(k, 0) for k in ("failed", "passed", "xfailed", "xpassed"))
    return {"runner": "pytest", "collected": ran, "failed": failed + counts.get("error", 0),
            "assertions": failed}


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


def _git(root, args, timeout=120):
    """`(code, text)` for one git call; the hooks path points nowhere, so no hook
    the repository carries runs on the throwaway's behalf."""
    try:
        out = subprocess.run(["git", "-C", root, "-c",
                              "core.hooksPath=%s" % os.devnull] + list(args),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             timeout=timeout)
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


def introduced(root, implementation, symbol, output):
    """`(holds, basis)` - whether this task INTRODUCES `symbol`.

    THE DEFINITION, because "the task introduces the symbol" is otherwise a
    judgement the executor makes about its own proof. It holds when all three
    observations do: the symbol is absent from HEAD's copy of every declared
    implementation file (content and path both, so a new module counts), it is
    present in the working tree's copy of at least one, and the failed run's own
    output names it. Then the compile or collection error is the absence the
    test asserts, not a test that never got to assert."""
    heads = dict((rel, _head_text(root, rel)) for rel in implementation)
    at_head = [rel for rel, text in heads.items()
               if text is not None and (symbol in rel or symbol in text)]
    if at_head:
        return False, ("%r is not introduced by this task: HEAD already carries it "
                       "in %s" % (symbol, ", ".join(at_head)))
    in_wt = [rel for rel in implementation
             if (symbol in rel and _wt_text(root, rel) is not None)
             or symbol in (_wt_text(root, rel) or "")]
    if not in_wt:
        return False, ("%r is not introduced by this task: no declared "
                       "implementation file in the working tree carries it" % (symbol,))
    if symbol not in output:
        return False, ("%r is absent at HEAD and present in %s, but the run's "
                       "output never names it, so the error is about something "
                       "else" % (symbol, ", ".join(in_wt)))
    return True, ("the task introduces %r: absent from HEAD's %s, present in the "
                  "working tree's %s, and named by the run's output"
                  % (symbol, ", ".join(implementation), ", ".join(in_wt)))


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
def _build_throwaway(root, path, tests):
    """`(copied, problem)`: HEAD checked out at `path`, the tests laid over it."""
    code, text = _git(root, ["worktree", "add", "--detach", "--quiet", path, "HEAD"])
    if code != 0:
        return [], "git could not build the throwaway tree: %s" % (text,)
    copied = []
    for rel in tests:
        src = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(src):
            continue
        dst = os.path.join(path, *rel.split("/"))
        if not os.path.isdir(os.path.dirname(dst)):
            os.makedirs(os.path.dirname(dst))
        shutil.copyfile(src, dst)
        copied.append(rel)
    return copied, None


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


def _run_in(path, cmd, timeout):
    """`(code, text, problem)` for the command, run in the throwaway."""
    try:
        out = subprocess.run(cmd, cwd=path, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", "the run timed out after %s s" % (timeout,)
    except OSError as exc:
        return None, "", "the command could not start: %s" % (exc,)
    return out.returncode, out.stdout.decode("utf-8", "replace"), None


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


def red_verdict(cmd, code, text, problem, symbols, root, implementation):
    """`(exit, verdict, block, note)` - what one run in the throwaway proved."""
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    shown = " ".join(cmd)
    if problem is not None:
        return E_CANNOT_PROVE, V_NOT_RUN, {
            "status": RED_CANNOT, "at": at,
            "basis": "`%s` in a throwaway tree at HEAD: %s" % (shown, problem)}, None
    verdict, tally = classify_run(code, text)
    line = _decisive_line(text, tally)
    where = "`%s` in a throwaway tree at HEAD exited %d" % (shown, code)
    if verdict == V_GREEN:
        return E_NOT_RED, verdict, None, (
            "%s (%s): the test passes WITHOUT the fix, so it proves nothing yet - "
            "fix the test; there is no redFirst word to record for this" % (where, line))
    if verdict == V_RED:
        return E_PROVED, verdict, {
            "status": RED_PROVED, "at": at,
            "basis": "%s with %d of %d collected tests failing an assertion: %s"
                     % (where, tally["assertions"], tally["collected"], line)}, None
    for symbol in (symbols if verdict == V_COLLECT else ()):
        holds, why = introduced(root, implementation, symbol, text)
        if holds:
            return E_PROVED, verdict, {
                "status": RED_PROVED, "at": at,
                "basis": "%s on a compile or collection error, and %s: %s"
                         % (where, why, line)}, None
    reason = ("no test was collected or none reached an assertion"
              if verdict == V_COLLECT else
              "its output carries no test tally this command reads, so an "
              "assertion failure cannot be told from a crash - no test is known "
              "to have been collected")
    why_not = "; ".join(introduced(root, implementation, s, text)[1]
                        for s in (symbols if verdict == V_COLLECT else ()))
    return E_CANNOT_PROVE, verdict, {
        "status": RED_CANNOT, "at": at,
        "basis": "%s, but %s: %s%s" % (where, reason, line,
                                       ("; " + why_not) if why_not else "")}, None


def run_red(args, cmd, out):
    """`red`: prove a red in a throwaway tree and print the `redFirst` block."""
    if not cmd:
        sys.stderr.write("ERROR: red needs the test command after `--`\n")
        return E_USAGE
    if not (args.task and args.manifest) or args.files:
        sys.stderr.write("ERROR: red takes its scope off the plan: pass --manifest "
                         "and --task, and no --files\n")
        return E_USAGE
    try:
        manifest = _mio.load_manifest(args.manifest)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (args.manifest, exc))
        return E_USAGE
    task, problem = find_task(manifest if isinstance(manifest, dict) else {},
                              args.task)
    if problem is not None:
        sys.stderr.write("ERROR: %s\n" % (problem,))
        return E_USAGE
    implementation, tests = split_scope(task)
    if not tests:
        sys.stderr.write("ERROR: task %s declares no test file, so a throwaway at "
                         "HEAD would prove nothing about this task's test\n"
                         % (args.task,))
        return E_USAGE
    code, root = _git(os.path.abspath(args.project), ["rev-parse", "--show-toplevel"])
    if code != 0:
        sys.stderr.write("ERROR: %s is not inside a git repository: %s\n"
                         % (args.project, root))
        return E_USAGE
    named = _names_shared_tree(cmd, root, os.path.abspath(args.project))
    if named:
        sys.stderr.write("ERROR: the command names the shared tree (%s); give its "
                         "paths relative to the tree root so they resolve inside "
                         "the throwaway\n" % (", ".join(named),))
        return E_USAGE
    present = [t for t in tests if os.path.isfile(os.path.join(root, *t.split("/")))]
    if not present:
        sys.stderr.write("ERROR: none of task %s's test files (%s) is in the working "
                         "tree, so a throwaway would hold HEAD alone\n"
                         % (args.task, ", ".join(tests)))
        return E_USAGE
    _c, head = _git(root, ["rev-parse", "HEAD"])
    holder = tempfile.mkdtemp(prefix="audit-red-")
    path = os.path.join(holder, "tree")
    rcode, text, copied = None, "", []
    try:
        copied, problem = _build_throwaway(root, path, present)
        if problem is None:
            rcode, text, problem = _run_in(path, cmd, args.timeout)
        exit_code, verdict, block, note = red_verdict(
            cmd, rcode, text, problem, args.introduces, root, implementation)
    finally:
        removed = _remove_throwaway(root, holder, path)
    payload = {"verdict": verdict, "redFirst": block, "note": note,
               "atHead": implementation, "copied": copied,
               "throwaway": {"path": path, "head": head,
                             "removed": removed},
               "run": {"argv": cmd, "exit": rcode,
                       "outputTail": text.splitlines()[-20:]}}
    if args.as_json:
        out(json.dumps(payload, indent=2, sort_keys=True))
    else:
        out("red-first: %s (throwaway at HEAD %s, removed: %s)"
            % (verdict, (head or "?")[:12], "yes" if removed else "NO"))
        out("  at HEAD: %s" % (", ".join(implementation) or "(none declared)"))
        out("  from the working tree: %s" % (", ".join(copied) or "(none)"))
        out(note if block is None else "redFirst: %s" % (json.dumps(block),))
    if not removed:
        sys.stderr.write("ERROR: the throwaway tree at %s could not be removed; "
                         "`git worktree list` names what is left\n"
                         % (path,))
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
