#!/usr/bin/env python3
"""Which lines of a module its suite reached at one revision and no longer reaches at another.

    python3 tools/reach-diff.py <module> <suite> --base <rev> --head <rev|WORKTREE>
        [--repo PATH] [--jobs N] [--timeout S] [--tracer monitoring|settrace]
        [--allow-same]

e.g. python3 tools/reach-diff.py plugins/audit/scripts/governance/drive-phase.py \\
         tests/test_drive_phase.py --base 92c399f5 --head WORKTREE

WHY THIS EXISTS. A suite converted from end-to-end drives to unit cases over a
decision function keeps its decisions tested and can stop running the code that ACTS
on a decision - the branch that routes to the answer, the line that appends what the
answer printed. Nothing about the converted suite looks wrong: every case passes and
every case is about the planner. Reviews found that shape by reading, one instance at
a time, and a reader finds the instances they think to look for. This is the
invariant instead: every line of the module the old suite reached, the new suite
still reaches, or the line is named. It is the check a conversion owes.

THIS TEXT IS THE CONTRACT, and the only copy of it: what the run measures, when it
exits 1, and - in the list at the end - every reason it refuses with 2. Each
refusal printed carries its name from that list, and `--selftest` fails when a
name there has no case asserting it, when a case asserts a name not there, or
when a refusal site in the code names one not there.

THE HEAD A GATE NAMES IS THE WORKING TREE. A task's gate runs over the task's
uncommitted work, and a commit is not that work: `--head HEAD` over an uncommitted
conversion compares the base with itself, and over an uncommitted fix still holds
the loss the fix removes. `--head WORKTREE` (that exact spelling, so a ref of that
name cannot be compared) materialises the checkout as git lists it - each tracked
file as it is on disk, each untracked file git does not ignore, a tracked file
deleted on disk absent - by copying, never by writing the checkout or its index.
The base is always a commit.

THE HEAD IS THE BASE WHEN THE TWO SIDES HOLD THE SAME BYTES: both name one commit,
two commits name one tree, or the two exports differ in no file at all. No suite
is run then - there is nothing a run could tell apart - and the run refuses
(`same`): "lost: 0" over such sides is true and measures nothing, the same for
every suite, a converted one or not. That covers `--base HEAD --head WORKTREE` on
a clean checkout, and any run once the task's work is committed. `--allow-same`
is the caller saying identical sides are the answer it expects (a gate re-run
where the work is already in the base): the same lines are printed and the exit
is 0.

SIDES THAT DIFFER IN ANY FILE ARE MEASURED, and the run says which files differ
and which of them `decides()`: the module, the suite, or a file Python can import
(`IMPORTABLE_SUFFIXES` - source, bytecode, an extension, a `.pth`, an importable
archive, a `conftest` or a `sitecustomize` included). A change confined to files
that do not decide is measured all the same, because a data file the module reads
can move what the suite reaches, and a line lost over it exits 1 like any other.
Nothing lost over such sides is no evidence of a conversion, though - a journal
row the drive leaves uncommitted changes nothing any suite runs - so it refuses
(`no-conversion`), unless `--allow-same`. Sides that differ in a file that decides
and lose nothing are an honest 0.

HOW A REVISION IS MEASURED. Each commit is a `git archive` export into a scratch
directory, and the working tree the copy above (the checkout is never written, and
no worktree is registered in its git dir). The suite is run there the way the sweep runs it - the sweep's own `run_one`
and `grade`, loaded rather than copied, so the child's cwd, temp, home, git config and
session filtering are the sweep's - one job per `STAGES` block (`--selftest --stage
LABEL`), or the whole file when the sweep cannot read a table, with the jobs of both
revisions in one pool sized by the sweep's `default_jobs`.

THE HOOK. A line tracer is installed in every Python process the run starts that
imports the hook, a module in a scratch directory put first on `PYTHONPATH`. It is
written as `usercustomize`, which `site` imports after whichever `sitecustomize`
won - so a suite that plants its own sitecustomize ahead of everything (the drive
suite's pinned clock and Windows-shaped stdout both do) still runs it - and only
when this interpreter, asked once under the sweep's filtered environment, has its user
site off (`-s`, `PYTHONNOUSERSITE`, a venv without system site packages) is it
written as `sitecustomize` instead, which the output's `hook:` line says along with
what that costs. Either way it runs the module of its own name that it shadows, and
installs once per process. It records only lines whose code object's file is the
module, by resolved path - `sys.monitoring` where the interpreter has it, each
location disabled after its first event so the cost elsewhere is one call per
location, and `sys.settrace` plus `threading.settrace` on the 3.8 floor, which hands
a line tracer only to the module's frames. Each process writes a start marker when
it installs and its lines when it exits. Everything a process writes about itself -
its parent, its key, its block - is read when the hook installs, so a process that
rewrites or clears its environment before it exits is still filed where it started.

THE ROUTE IS THE SWEEP'S. A suite may decide how to run something by what is on
`PYTHONPATH` - the drive suite runs a verb as a process rather than in its own
interpreter when a `sitecustomize` sits there, since only a fresh interpreter imports
one. The `usercustomize` entry adds none, so such a suite takes the route it takes
under the sweep. The `sitecustomize` fallback does add one, and under it every verb
that suite would run in-process runs as a process, at both revisions alike: the
reach measured is then the process route's, not the sweep's.

UNTRACED MODULE CHILDREN DECIDE THE EXIT. Each traced process records the key of
every child it starts through `subprocess.Popen` with the module's path among
their arguments, and hands each child a token naming itself in the environment;
each traced process records its own key, whether it is running the module, and
the token of its parent. A KEY is a process's arguments - for a module child,
those after the module's path - with every absolute path under the export's root
written relative to it, every one under the temp or home directory the sweep
handed the block's run written as `<temp>` or `<home>` (those two differ between
any two runs; the block's first process reads them and hands them down, so every
process of one block agrees), and every other absolute path kept as it is, since
on one machine it names the same thing at both revisions. So the same child has
one key at both revisions and in both of a base's runs. A
child started on the module that never wrote its lines - one handed an
environment that drops the hook, one started with `-I`, `-E`, `-S` or (under the
`usercustomize` entry) `-s`, one that ended through `os._exit`, a kill or a
timeout - is a key its parent recorded and no child of its answered. Children are
kept per block. A block that ran
at both revisions and left the same untraced children at both - the same keys,
as many times each - measured the same blind spot on both sides (a suite that
kills a child on purpose does that at every revision), and it is printed, with
the keys, as a blind spot while the comparison goes on over everything else;
lines only those children ran are measured at neither revision, so a loss among
them cannot be seen. Any other untraced child refuses (`untraced`), naming each
side's keys: a block whose children differ, in number or in which they are, or
one that ran at one revision only - the shape a conversion takes when it deletes
a block, whose children the base could not see either. WHAT A KEY CANNOT TELL
APART: two children with the same arguments that take different paths through
the module - by what they read on stdin, in the environment or in a file - are
one key, and so are two that differ only in which path under the temp or home
directory they name; a blind spot matched by key can still hide a loss among the
lines one of them ran. An argument that varies between runs in a way the key
does not cover (a generated id, a path inside an option's value) makes the same
child two keys, which refuses rather than hiding anything.

WHAT IT CANNOT SEE, SAID RATHER THAN IMPLIED. A child that runs the module without
naming its path among `subprocess.Popen`'s arguments - started through a shell
string, `os.system`, `os.spawn*`, `os.posix_spawn` or `-m`, or a script that imports
the module rather than running it - is not counted, so if it is untraced nothing says
so. A child of an untraced process is not counted either, and a traced process that
itself ended without writing takes its count with it; the start markers make those
visible as the gap between processes that started the hook and processes that
wrote, printed per revision, without deciding the exit. A `Popen` that fails to
start its child is counted as an untraced one. A suite that reads the repository's
own git (history, `ls-files`) sees an export with none.

HOW A LINE IS MATCHED ACROSS REVISIONS. Never by its number. Each function's code
lines at the base are aligned with the same function's at the head
(`difflib.SequenceMatcher` over their stripped text), so an identical line inserted
or deleted beside another does not re-pair it; what is left in the whole module is
aligned again in line order, which finds a body moved into a renamed or a new
function; what is still left is paired by text alone. A line reached at the base and
paired with a head line the head did not reach is lost, whichever function it is in
now. Only a reached line whose text the head's module no longer holds anywhere is
listed apart as gone, and gone lines do not decide the exit code: a line that was
rewritten and left unreached is not seen.

A LINE THE BASE REACHES ONLY SOMETIMES DECIDES NOTHING. A race branch can be
reached in one run and missed in the next, and as lost it would make a gate flap.
So before a lost line counts, the blocks that reached any lost line at the base
are run once more, in a fresh export of the same commit - fresh, because a cache
or a marker the first run left behind is a different input, not chance, and a
second run over it could miss a line for that reason. A lost line the recheck
reaches again stays lost; one it does not reach, and any line only the recheck
reached that the head does not, is listed apart under `sometimes:` and does not
decide the exit. This rather than a fixed number of base runs, because it costs
nothing when nothing looks lost and is on in every run, and it cannot set aside
a real loss: a line every base run reaches is reached by the recheck too. A
recheck that could have missed a line for another reason than chance is no
evidence of chance, and refuses - the `recheck-` reasons in the list below.
WHAT IT CANNOT SEE: a line the base reaches by chance in both of its runs is
still lost - the flap is made rarer, not impossible - and the head is measured
once, so a line the head reaches only sometimes is lost in the runs where it
misses it.

EXIT CODES. 0 - nothing lost; or the head is the base, or only files that do
not decide differ, under `--allow-same`. 1 - a line lost. 2 - no comparison
made: a reach measured over a suite that did not finish, or over sides that
cannot be told apart, is not the suite's reach. Each refusal prints a line
`reach-diff: no comparison made (NAME) - ...`, the result carries the first
NAME as `refusal`, and these are all of them:

  [usage] the command line is not one this accepts.
  [base-worktree] `--base WORKTREE`: the base is the state a change started
      from, a commit; only `--head` may name the working tree.
  [hook-probe] the interpreter could not be asked whether it imports a
      `usercustomize` module, so where to write the hook is unknown.
  [revision] git cannot resolve a revision.
  [export] a revision could not be exported or copied.
  [missing] a revision holds no module or no suite at the path given.
  [unparsable] the module at a revision does not parse.
  [same] the head is the base, as above; no suite is run.
  [failed] a block did not pass at either revision - a red case, a crash, a
      timeout, no contract line.
  [untraced] a module child never wrote what it reached, and no blind spot
      matches it.
  [unreadable] a trace file of either revision could not be read.
  [no-reach] a revision reached no line of the module: the suite does not run
      it there, or no process it started ran the tracer.
  [no-conversion] only files that do not decide differ, and nothing was lost.
  [recheck-export] the fresh export the recheck runs in could not be made.
  [recheck-failed] a block run again did not pass.
  [recheck-unreadable] a trace file of the recheck could not be read.
  [recheck-processes] a block run again did not run the same processes as its
      first run: the processes that wrote what they reached, the processes that
      never wrote it, and the module children left untraced are each compared
      with the first run's by key, as multisets, and a difference in either
      direction refuses - a child swapped for another included.
  [recheck-cases] a block run again did not run the same cases as its first
      run: compared by case id - the word after `PASS` or `FAIL` on each case
      line - when both runs printed case lines, else by the contract's case
      count; the refusal says which it compared.
"""
import ast
import difflib
import filecmp
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from concurrent import futures

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
# Same shape as `tools/where.py`, and for the same reason.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import _output  # noqa: E402

_output.install_path()

USAGE = ("usage: reach-diff.py <module> <suite> --base <rev> --head <rev|WORKTREE> "
         "[--repo PATH] [--jobs N] [--timeout S] [--tracer monitoring|settrace] "
         "[--allow-same]\n")


TRACERS = ("monitoring", "settrace")
# A block's hang detector: the sweep's per-file default, doubled for the tracer's
# cost on the settrace floor. A heavier suite passes `--timeout`.
TIMEOUT_FACTOR = 2

# The names the hook reads. Neither starts with the session prefix the sweep's
# environment filter drops, so they reach the child it starts.
ENV_MODULE = "REACH_DIFF_MODULE"
ENV_OUT = "REACH_DIFF_OUT"
ENV_TRACER = "REACH_DIFF_TRACER"
ENV_PARENT = "REACH_DIFF_PARENT"
ENV_BLOCK = "REACH_DIFF_BLOCK"
ENV_ROOT = "REACH_DIFF_ROOT"
# Written by the first traced process of a block and read by every process below
# it, so the whole tree of one block normalises the same two directories.
ENV_TEMP = "REACH_DIFF_TEMP"
ENV_HOME = "REACH_DIFF_HOME"
WHOLE_FILE = "(whole file)"
UNKNOWN_BLOCK = "(a start marker that could not be read)"
# The head that names the checkout's working tree rather than a commit. A ref of
# this exact name cannot be compared; nothing else is reserved.
WORKTREE = "WORKTREE"
# The module names the hook is written as. `usercustomize` is imported by `site`
# after whichever `sitecustomize` won, so a suite that plants its own sitecustomize
# first on PYTHONPATH still runs the hook, and the hook adds no sitecustomize for a
# suite to see. Where the interpreter's user site is off it is never imported, and
# the hook falls back to being the `sitecustomize`.
HOOK_USER = "usercustomize"
HOOK_SITE = "sitecustomize"
USER_SITE_PROBE = "import site; print(site.ENABLE_USER_SITE)"


# --- the refusals ------------------------------------------------------------
# The names are read off the docstring's list, the one place the contract is
# stated; `_refuse` takes no other, and `--selftest` holds a case for each.
_DOC_REFUSAL = re.compile(r"^  \[([a-z][a-z-]*)\] ", re.M)
REFUSAL_LINE = re.compile(r"^reach-diff: no comparison made \(([a-z][a-z-]*)\) - ",
                          re.M)
# A case line of the house runner's: `PASS <id> ...` or `FAIL <id> ...`.
CASE_LINE = re.compile(r"^(?:PASS|FAIL) (\S+)", re.M)


def doc_refusals(doc):
    """The refusal names the list at the end of `doc` holds, in its order."""
    tail = (doc or "").split("\nEXIT CODES.", 1)
    return _DOC_REFUSAL.findall(tail[1]) if len(tail) == 2 else []


REFUSALS = tuple(doc_refusals(__doc__))


def refusals_in(text):
    """The refusal names `text` prints, in order, one per refusal line."""
    return REFUSAL_LINE.findall(text or "")


def fresh_result():
    """The result of a comparison before anything has been decided: exit 2,
    no refusal named yet."""
    return {"code": 2, "refusal": None, "gaps": [], "gone": [], "reached": {},
            "tracers": [], "processes": {}, "blocks": {}, "untraced": {},
            "hook": None, "blind": {}, "same": False, "rechecked": [],
            "flaky": []}


def _refuse(result, out, name, why):
    """Print one refusal line naming `name` and record the first one in
    `result`, whose exit stays 2. A name the docstring's list does not hold is
    a ValueError: a refusal the contract does not state is a defect here, not
    a reason to print."""
    if name not in REFUSALS:
        raise ValueError("refusal %r is not one the docstring names" % (name,))
    if result.get("refusal") is None:
        result["refusal"] = name
    result["code"] = 2
    out.write("reach-diff: no comparison made (%s) - %s\n" % (name, why))
    return result


def hook_line(entry):
    """What the output says about the module the hook was written as."""
    if entry == HOOK_USER:
        return ("usercustomize (no sitecustomize is added to PYTHONPATH, so the "
                "suite's processes run as the sweep runs them)")
    return ("sitecustomize, because this interpreter's user site is off - a suite "
            "that plants its own sitecustomize ahead of it hides its children from "
            "the hook, and one that routes on a sitecustomize being present runs "
            "differently than under the sweep")

# The hook, written into a scratch directory as one of the modules above. It runs
# in every Python process that imports it, so it is 3.8 syntax, stdlib only, and
# inert unless both variables are set. Per process it writes a start marker when it
# installs and the lines when the process exits, each renamed into place, so a
# process killed mid-write leaves a `.part` the reader skips. Both name the process
# by a token it also hands its children in the environment and carry its key, and
# the lines file holds the key of each child it started on the module's path - an
# audit hook on `subprocess.Popen` - so the reader can tell which module child was
# traced and which was started and never wrote.
HOOK_SOURCE = '''import json
import os
import sys


def _reach_diff_install():
    if getattr(sys, "_reach_diff_hooked", False):
        return
    sys._reach_diff_hooked = True
    target = os.environ.get("REACH_DIFF_MODULE")
    out_dir = os.environ.get("REACH_DIFF_OUT")
    if not target or not out_dir:
        return

    def norm(path):
        return os.path.normcase(os.path.realpath(path))
    want = norm(target)
    root = os.environ.get("REACH_DIFF_ROOT")
    root = norm(root) if root else None

    def under(full, base):
        return full == base or full.startswith(base.rstrip(os.sep) + os.sep)

    def first_set(names):
        for name in names:
            if os.environ.get(name):
                return os.environ[name]
        return ""
    home = os.path.expanduser("~")
    scratch = []
    for var, mark, here in (
            ("REACH_DIFF_TEMP", "<temp>", first_set(("TMPDIR", "TEMP", "TMP"))),
            ("REACH_DIFF_HOME", "<home>", "" if home == "~" else home)):
        if var not in os.environ:
            os.environ[var] = here
        found = os.environ[var]
        if found and os.path.isabs(found):
            found = norm(found)
            if os.path.dirname(found) != found:
                scratch.append((found, mark))

    def decoded(arg):
        try:
            return os.fsdecode(arg)
        except TypeError:
            return "%r" % (arg,)

    def ident(args):
        key = []
        for arg in args:
            arg = decoded(arg)
            if os.path.isabs(arg):
                full = norm(arg)
                if root and full.startswith(root + os.sep):
                    arg = "<tree>/" + os.path.relpath(full, root).replace(
                        os.sep, "/")
                else:
                    arg = next((mark for base, mark in scratch
                                if under(full, base)), arg)
            key.append(arg)
        return key

    def module_at(args):
        if not isinstance(args, (list, tuple)):
            return -1
        for at, arg in enumerate(args):
            arg = decoded(arg)
            if arg and not arg.startswith("-") and norm(arg) == want:
                return at
        return -1
    verdicts = {}
    lines = set()
    spawned = []
    token = "%d-%s" % (os.getpid(), os.urandom(6).hex())
    parent = os.environ.get("REACH_DIFF_PARENT")
    block = os.environ.get("REACH_DIFF_BLOCK")
    os.environ["REACH_DIFF_PARENT"] = token
    argv = list(getattr(sys, "argv", None) or [])
    is_module = module_at(argv[:1]) == 0
    me = ["<module>"] + ident(argv[1:]) if is_module else ident(argv)

    def write(suffix, record):
        path = os.path.join(out_dir, token + suffix)
        with open(path + ".part", "w") as fh:
            json.dump(record, fh)
        os.replace(path + ".part", path)
    write(".start", {"parent": parent, "module": is_module, "argv": me,
                     "block": block})

    def on_event(event, args):
        if event != "subprocess.Popen":
            return
        at = module_at(args[1])
        if at >= 0:
            spawned.append(["<module>"] + ident(list(args[1])[at + 1:]))
    sys.addaudithook(on_event)

    def ours(filename):
        hit = verdicts.get(filename)
        if hit is None:
            hit = bool(filename) and not filename.startswith("<") \\
                and norm(filename) == want
            verdicts[filename] = hit
        return hit

    used = "settrace"
    mon = getattr(sys, "monitoring", None)
    if os.environ.get("REACH_DIFF_TRACER") == "settrace":
        mon = None
    if mon is not None:
        try:
            mon.use_tool_id(mon.COVERAGE_ID, "reach-diff")
        except ValueError:
            mon = None
            used = "settrace (the monitoring id was taken)"
    if mon is not None:
        disable = mon.DISABLE

        def on_line(code, line):
            if ours(code.co_filename):
                lines.add(line)
            return disable
        mon.register_callback(mon.COVERAGE_ID, mon.events.LINE, on_line)
        mon.set_events(mon.COVERAGE_ID, mon.events.LINE)
        used = "monitoring"
    else:
        import threading

        def local(frame, event, arg):
            if event == "line":
                lines.add(frame.f_lineno)
            return local

        def calls(frame, event, arg):
            if ours(frame.f_code.co_filename):
                return local
            return None
        sys.settrace(calls)
        threading.settrace(calls)

    def dump():
        write(".json", {"tracer": used, "lines": sorted(lines),
                        "parent": parent, "module": is_module, "argv": me,
                        "spawned": spawned, "block": block})
    import atexit
    atexit.register(dump)


def _reach_diff_chain():
    import importlib.machinery
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]
    spec = importlib.machinery.PathFinder.find_spec(__name__, rest)
    if spec is None or spec.loader is None:
        return
    shadowed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shadowed)


_reach_diff_install()
_reach_diff_chain()
'''


# --- matching a line across revisions -----------------------------------------
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _source_lines(source):
    """`source` split the way the compiler numbers lines: at `\\r\\n`, `\\r` or
    `\\n`, and at nothing else - `splitlines` also splits at form feeds and
    separators the compiler reads inside a line."""
    return source.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _scope_spans(tree):
    """`(first line, last line, dotted name)` for every function and class, outer
    before inner. A decorator belongs to the scope that evaluates it, so a span
    starts at the `def` line."""
    spans = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                name = prefix + child.name
                spans.append((child.lineno, getattr(child, "end_lineno", None)
                              or child.lineno, name))
                walk(child, name + ".")
            else:
                walk(child, prefix)
    walk(tree, "")
    return spans


def code_lines(source):
    """`[(line number, function, stripped text)]` for every line of `source` that
    holds code - a blank or comment-only line is never reached and anchors
    nothing. `function` is the innermost enclosing one, dotted, or `<module>`."""
    lines = _source_lines(source)
    owner = ["<module>"] * (len(lines) + 1)
    for first, last, name in _scope_spans(ast.parse(source)):
        for n in range(first, min(last, len(lines)) + 1):
            owner[n] = name
    return [(n, owner[n], text.strip()) for n, text in enumerate(lines, 1)
            if text.strip() and not text.strip().startswith("#")]


def _aligned(base_rows, head_rows):
    """`(base line, head line)` for each row the two sequences share, by an
    order-preserving alignment of their texts."""
    matcher = difflib.SequenceMatcher(None, [r[2] for r in base_rows],
                                      [r[2] for r in head_rows], autojunk=False)
    return [(base_rows[block.a + k][0], head_rows[block.b + k][0])
            for block in matcher.get_matching_blocks() for k in range(block.size)]


def _by_function(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row[1], []).append(row)
    return grouped


def match_lines(base_source, head_source):
    """`{base line: head line}` for every code line of the base the head still
    holds, in three passes, each over what the earlier ones left:

      1. per function present at both, the two functions' lines aligned - so an
         identical line inserted or deleted beside another does not re-pair it;
      2. the rest of the module at both, aligned in line order - a body moved
         into a renamed or a new function;
      3. the rest by text alone, each base line taking the first head line of
         that text no pass has taken - a move that crossed another.

    A base line left unpaired has a text the head no longer holds anywhere."""
    base, head = code_lines(base_source), code_lines(head_source)
    pairs, taken = {}, set()

    def keep(found):
        for b, h in found:
            if b not in pairs and h not in taken:
                pairs[b] = h
                taken.add(h)
    base_fns, head_fns = _by_function(base), _by_function(head)
    for name in base_fns:
        if name in head_fns:
            keep(_aligned(base_fns[name], head_fns[name]))
    keep(_aligned([r for r in base if r[0] not in pairs],
                  [r for r in head if r[0] not in taken]))
    spare = {}
    for n, _fn, text in head:
        if n not in taken:
            spare.setdefault(text, []).append(n)
    keep((n, spare[text].pop(0)) for n, _fn, text in base
         if n not in pairs and spare.get(text))
    return pairs


def reach_gaps(base_source, base_lines, head_source, head_lines):
    """`{"gaps": [...], "gone": [...], "lost_at_base": [...]}`; the first two
    are lists of `(function, line, text)`, the third the base's numbers of the
    lines in `gaps`.

    `gaps` are lines reached at the base that `match_lines` pairs with a head
    line the head's suite did not reach, named and numbered as the head has
    them; `gone` are lines reached at the base whose text the head's module no
    longer holds anywhere, named and numbered as the base had them. Both in line
    order."""
    pairs = match_lines(base_source, head_source)
    base_rows = dict((r[0], r) for r in code_lines(base_source))
    head_rows = dict((r[0], r) for r in code_lines(head_source))
    reached_now = set(head_lines)
    gaps, gone, lost = [], [], []
    for n in sorted(set(base_lines)):
        if n not in base_rows:
            continue
        if n not in pairs:
            gone.append(base_rows[n][1:2] + (n, base_rows[n][2]))
        elif pairs[n] not in reached_now:
            row = head_rows[pairs[n]]
            gaps.append((row[1], row[0], row[2]))
            lost.append(n)
    return {"gaps": sorted(gaps, key=lambda g: g[1]), "gone": gone,
            "lost_at_base": lost}


# --- materialising a revision -------------------------------------------------
def _git(repo, *args):
    """`(exit code, stdout, stderr)` of one git command against `repo`."""
    try:
        done = subprocess.run(("git", "-C", repo) + args, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError as exc:
        return None, "", "git could not be started: %s" % (exc,)
    return (done.returncode, done.stdout.decode("utf-8", "replace").strip(),
            done.stderr.decode("utf-8", "replace").strip())


def resolve_rev(repo, rev):
    """The commit `rev` names in `repo`, or None when git cannot name one."""
    code, sha, _err = _git(repo, "rev-parse", "--verify", "--quiet",
                           "%s^{commit}" % (rev,))
    return sha if code == 0 and sha else None


def export_rev(repo, sha, dest):
    """Write the tree of commit `sha` into `dest` through `git archive`; an
    error message, or None when the export was made."""
    with tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(("git", "-C", repo, "archive", "--format=tar",
                                     sha), stdout=subprocess.PIPE, stderr=err)
        except OSError as exc:
            return "git could not be started: %s" % (exc,)
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                if hasattr(tarfile, "data_filter"):
                    archive.extractall(dest, filter="data")
                else:
                    archive.extractall(dest)
        except (tarfile.TarError, OSError) as exc:
            proc.kill()
            proc.wait()
            return "the export of %s could not be unpacked: %s" % (sha, exc)
        finally:
            proc.stdout.close()
        code = proc.wait()
        err.seek(0)
        text = err.read().decode("utf-8", "replace").strip()
    if code != 0:
        return "git archive %s exited %d: %s" % (sha, code, text)
    return None


def export_worktree(repo, dest):
    """Copy the working tree of `repo` into `dest` as git lists it - every
    tracked file as it is on disk, every untracked file git does not ignore -
    and nothing else: a tracked file deleted on disk is absent, an ignored one
    is not copied, and the git dir is not. An error message, or None.

    THE CHECKOUT IS ONLY READ. A symlink is copied as a link. A path git lists
    that is a directory - a submodule's gitlink - is not copied, as `git
    archive` does not copy one either."""
    code, listed, err = _git_z(repo, "ls-files", "-z", "--cached", "--others",
                               "--exclude-standard")
    if code != 0:
        return "git ls-files exited %s: %s" % (code, err)
    root = os.path.abspath(repo)
    for rel in sorted(set(listed)):
        source = os.path.join(root, *rel.split("/"))
        if not os.path.lexists(source) or (os.path.isdir(source)
                                           and not os.path.islink(source)):
            continue
        target = os.path.join(dest, *rel.split("/"))
        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        try:
            shutil.copy2(source, target, follow_symlinks=False)
        except OSError as exc:
            return "the working tree could not be copied at %s: %s" % (rel, exc)
    return None


def _git_z(repo, *args):
    """`(exit code, NUL-separated paths, stderr)` of one git command."""
    try:
        done = subprocess.run(("git", "-C", repo) + args, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError as exc:
        return None, [], "git could not be started: %s" % (exc,)
    paths = [os.fsdecode(p) for p in done.stdout.split(b"\0") if p]
    return done.returncode, paths, done.stderr.decode("utf-8", "replace").strip()


# --- running a suite with the tracer ------------------------------------------
def _sweep():
    """The sweep runner as a module: its child environment, its grade, its
    reading of a `STAGES` table and its job count, loaded rather than copied."""
    import _loader
    return _loader.load(os.path.join(_here, "sweep-selftests.py"))


def suite_blocks(sweep, source):
    """The labels to run a suite under, one job each, or `[None]` for one run of
    the whole file - and the reason when the file is run whole."""
    if not sweep.is_staged(source):
        return [None], "no staged_main, so the whole file is one run"
    labels = sweep.stage_labels(source)
    if not labels:
        return [None], "its STAGES table is not a literal the sweep reads"
    return labels, None


def hook_entry(environ):
    """`HOOK_USER` when this interpreter, under `environ`, imports a
    usercustomize module; else `HOOK_SITE`, or None with the reason when the
    interpreter cannot be asked."""
    try:
        done = subprocess.run([sys.executable, "-c", USER_SITE_PROBE], env=environ,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "the interpreter could not be asked about its user site: %s" % (
            exc,)
    answer = done.stdout.strip()
    if done.returncode != 0 or answer not in ("True", "False", "None"):
        return None, "the interpreter's user-site probe exited %d saying %r" % (
            done.returncode, (answer or done.stderr.strip())[:200])
    return (HOOK_USER if answer == "True" else HOOK_SITE), None


def write_hook(directory, entry):
    """The hook, written into `directory` as the module `entry`; the path."""
    path = os.path.join(directory, entry + os.extsep + "py")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HOOK_SOURCE)
    return path


def traced_env(hook_dir, module_path, out_dir, tracer, root, environ=None):
    """The caller's environment with the hook first on `PYTHONPATH` and the
    module, the output directory, the tracer and the export's root named."""
    env = dict(os.environ if environ is None else environ)
    prior = env.get("PYTHONPATH")
    env["PYTHONPATH"] = hook_dir + (os.pathsep + prior if prior else "")
    env[ENV_MODULE] = module_path
    env[ENV_ROOT] = root
    env[ENV_OUT] = out_dir
    env.pop(ENV_PARENT, None)
    env.pop(ENV_TEMP, None)
    env.pop(ENV_HOME, None)
    if tracer:
        env[ENV_TRACER] = tracer
    else:
        env.pop(ENV_TRACER, None)
    return env


def _read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def untraced_children(dumps):
    """`{block label: Counter of child keys}` - the module children the traced
    processes of each block started that never wrote their lines: for each
    process that wrote, the keys of the children it started on the module's
    path, less the keys of the module processes that wrote naming it as parent.
    A key is the child's arguments after the module, with the export's root
    stripped (`process_key`). Only blocks with some are listed."""
    written, out = {}, {}
    for data in dumps.values():
        if data.get("module") and data.get("parent"):
            written.setdefault(data["parent"], Counter())[data["argv"]] += 1
    for token, data in dumps.items():
        short = Counter(data["spawned"]) - written.get(token, Counter())
        if short:
            label = "%s" % (data.get("block") or WHOLE_FILE,)
            out.setdefault(label, Counter()).update(short)
    return out


def total(by_block):
    """How many keys a `{label: Counter}` holds, over every label."""
    return sum(sum(keys.values()) for keys in by_block.values())


def render_keys(keys):
    """A Counter of process keys as one line, each key's arguments joined by a
    space and a repeat shown as a multiplier; `none` when empty."""
    if not keys:
        return "none"
    return "; ".join(" ".join(key) + (" (x%d)" % (n,) if n > 1 else "")
                     for key, n in sorted(keys.items()))


def blind_spots(base_untraced, head_untraced, base_blocks, head_blocks):
    """`{"matched": {label: n}, "unmatched": [(label, base keys, head keys,
    why)]}`, the keys as Counters.

    A block that ran at both revisions and left the same children untraced at
    both - the same keys, as many times each - measured the same blind spot on
    both sides: it is matched, and the comparison goes on over everything else.
    Any other untraced child is unmatched - a block whose children differ,
    however many there are of them, or one that ran at one revision only. The
    second is the shape a conversion takes when it deletes a block, and the
    children the base could not see must not leave the comparison with the
    block."""
    matched, unmatched = {}, []
    for label in sorted(set(base_untraced) | set(head_untraced)):
        at_base = base_untraced.get(label, Counter())
        at_head = head_untraced.get(label, Counter())
        if label not in base_blocks or label not in head_blocks:
            unmatched.append((label, at_base, at_head,
                              "the block ran at one revision only"))
        elif at_base != at_head:
            unmatched.append((label, at_base, at_head,
                              "the children differ between the revisions"))
        else:
            matched[label] = sum(at_base.values())
    return {"matched": matched, "unmatched": unmatched}


def process_key(value):
    """A key the hook wrote, as a tuple of strings; ValueError for any other
    shape, so a trace that does not hold one is unreadable rather than read
    as no key."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("a process key is not a list of strings: %r" % (value,))
    return tuple(value)


UNREADABLE_KEY = ("(a start marker that could not be read)",)


def read_traces(out_dir):
    """What the hook wrote into `out_dir`: `{"lines", "tracers", "started",
    "written", "silent", "untraced", "unreadable"}`. `started` counts processes
    that installed the hook, `written` those that also wrote their lines, and
    `silent` the difference - a process that ended without its exit handlers.
    `untraced` is `untraced_children()` over what was written, by block.
    `by_block` is the lines each block's processes wrote; `written_by_block`
    and `silent_by_block` the keys of each block's processes that wrote and
    that did not, a start marker that cannot be read counted under
    `UNKNOWN_BLOCK` with `UNREADABLE_KEY`."""
    starts, dumps, unreadable = {}, {}, []
    for name in sorted(os.listdir(out_dir)):
        token, ext = os.path.splitext(name)
        if ext == ".start":
            try:
                mark = _read_json(os.path.join(out_dir, name))
                label = "%s" % (mark.get("block") or WHOLE_FILE,)
            except (OSError, ValueError, AttributeError):
                starts[token] = (UNKNOWN_BLOCK, UNREADABLE_KEY)
                continue
            try:
                starts[token] = (label, process_key(mark.get("argv")))
            except ValueError:
                starts[token] = (label, UNREADABLE_KEY)
            continue
        if ext != ".json":
            continue
        try:
            data = _read_json(os.path.join(out_dir, name))
            data["lines"] = set(int(n) for n in data["lines"])
            data["tracer"] = "%s" % (data["tracer"],)
            data["argv"] = process_key(data["argv"])
            if not isinstance(data["spawned"], list):
                raise ValueError("spawned is not a list: %r" % (data["spawned"],))
            data["spawned"] = [process_key(key) for key in data["spawned"]]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            unreadable.append("%s: %s" % (name, exc))
            continue
        dumps[token] = data
    lines, by_block, written_by_block, silent_by_block = set(), {}, {}, {}
    for data in dumps.values():
        label = "%s" % (data.get("block") or WHOLE_FILE,)
        lines.update(data["lines"])
        by_block.setdefault(label, set()).update(data["lines"])
        written_by_block.setdefault(label, Counter())[data["argv"]] += 1
    silent = set(starts) - set(dumps)
    for token in silent:
        label, key = starts[token]
        silent_by_block.setdefault(label, Counter())[key] += 1
    return {"lines": lines, "tracers": sorted(set(d["tracer"] for d in dumps.values())),
            "started": len(set(starts) | set(dumps)), "written": len(dumps),
            "silent": len(silent), "silent_by_block": silent_by_block,
            "written_by_block": written_by_block,
            "by_block": by_block,
            "untraced": untraced_children(dumps),
            "unreadable": unreadable}


def _run_block(sweep, side, label, suite, timeout, pycache):
    """One job: one block of `side`'s suite (or the whole file), graded the way
    the sweep grades it."""
    extra = ["--stage", label] if label else []
    env = dict(side["env"])
    env[ENV_BLOCK] = label or WHOLE_FILE
    row = sweep.run_one(suite, repo=side["export"], timeout=timeout,
                        pycache=pycache, environ=env, extra=extra)
    graded = sweep.grade(suite, row["code"], row["output"], row.get("debris", ()))
    return {"side": side["name"], "label": label or WHOLE_FILE,
            "ok": graded["ok"], "why": graded["why"], "cases": graded["cases"],
            "output": row["output"], "seconds": row.get("seconds", 0.0)}


# --- the comparison -----------------------------------------------------------
def _repo_relative(repo, path):
    """`path` as the repository names it, `/`-separated; an absolute path under
    `repo` loses that prefix, anything else is taken as already relative."""
    root = os.path.abspath(repo).rstrip(os.sep) + os.sep
    if os.path.isabs(path) and os.path.abspath(path).startswith(root):
        path = os.path.abspath(path)[len(root):]
    return path.replace(os.sep, "/").lstrip("/")


def _prepare(repo, name, rev, module, suite, scratch, tracer, sweep,
             environ=None):
    """One side of the comparison, exported and ready to run; or `(None,
    (refusal name, why))`."""
    export = os.path.join(scratch, name + "-tree")
    if rev == WORKTREE:
        sha = resolve_rev(repo, "HEAD") or "no commit"
        shown = "the working tree over %s" % (sha[:12],)
        os.makedirs(export)
        why = export_worktree(repo, export)
    else:
        sha = resolve_rev(repo, rev)
        if sha is None:
            return None, ("revision", "%s revision %r: git cannot resolve it in "
                                      "%s" % (name, rev, repo))
        shown = sha[:12]
        os.makedirs(export)
        why = export_rev(repo, sha, export)
    if why:
        return None, ("export", "%s revision %s: %s" % (name, rev, why))
    sources = {}
    for role, rel in (("module", module), ("suite", suite)):
        path = os.path.join(export, *rel.split("/"))
        if not os.path.isfile(path):
            return None, ("missing", "%s revision %s holds no %s at %s" % (
                name, rev, role, rel))
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            sources[role] = fh.read()
    try:
        ast.parse(sources["module"])
    except (SyntaxError, ValueError) as exc:
        return None, ("unparsable", "%s revision %s: the module does not "
                                    "parse: %s" % (name, rev, exc))
    out_dir = os.path.join(scratch, name + "-traces")
    os.makedirs(out_dir)
    labels, whole = suite_blocks(sweep, sources["suite"])
    module_path = os.path.join(export, *module.split("/"))
    return {"name": name, "rev": rev, "sha": sha, "shown": shown,
            "export": export,
            "out": out_dir, "labels": labels, "whole": whole,
            "module_source": sources["module"],
            "env": traced_env(os.path.join(scratch, "hook"), module_path, out_dir,
                              tracer, export, environ)}, None


def _measure(sweep, work, suite, jobs, timeout, pycache):
    """Every `(side, block)` of `work`, run in one pool; the rows in submission
    order."""
    with futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        pending = [pool.submit(_run_block, sweep, side, label, suite, timeout,
                               pycache) for side, label in work]
        return [job.result() for job in pending]


# --- the same side twice ------------------------------------------------------
def _tree_entries(root):
    """`{relative path: ("link", target) or ("file", None)}` for every entry under
    `root` that is not a directory. Directories are left out: git tracks no
    empty one, and a submodule's path is an empty directory in an export and
    absent from a copy of the working tree."""
    found = {}
    for here, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(here, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                found[rel] = ("link", os.readlink(path))
            elif not os.path.isdir(path):
                found[rel] = ("file", None)
    return found


# What a Python process can import or run at start-up from a directory on its
# path: source, bytecode, an extension module, a `.pth`, an importable archive.
# A file of any other kind that differs between the sides does not make them
# differ, unless it is the module or the suite.
IMPORTABLE_SUFFIXES = (".py", ".pyw", ".pyc", ".pyo", ".pyd", ".so", ".pth",
                       ".zip", ".egg")


def differing_files(first, second):
    """The relative paths, sorted, of every file or link that is in one
    directory and not the other, or in both with other bytes or another
    target."""
    left, right = _tree_entries(first), _tree_entries(second)
    found = []
    for rel in sorted(set(left) | set(right)):
        if left.get(rel) != right.get(rel):
            found.append(rel)
        elif left[rel][0] == "file" and not filecmp.cmp(
                os.path.join(first, *rel.split("/")),
                os.path.join(second, *rel.split("/")), shallow=False):
            found.append(rel)
    return found


def decides(rel, module, suite):
    """Whether a differing file can change what the suite reaches: the module,
    the suite, or a file Python can import."""
    return (rel in (module, suite)
            or os.path.splitext(rel)[1].lower() in IMPORTABLE_SUFFIXES)


def _tree_of(repo, sha):
    code, tree, _err = _git(repo, "rev-parse", "--verify", "--quiet",
                            "%s^{tree}" % (sha,))
    return tree if code == 0 and tree else None


def same_side(repo, base, head):
    """`(why, differing)`: why the two prepared sides hold the same bytes, or
    None when they do not, and the files that differ between them. Two
    commits naming one commit or one tree are the same; otherwise the two
    exports are compared byte for byte. Nothing here writes any git state."""
    if head["rev"] != WORKTREE:
        if base["sha"] == head["sha"]:
            return "both name commit %s" % (base["sha"][:12],), []
        trees = [_tree_of(repo, side["sha"]) for side in (base, head)]
        if trees[0] and trees[0] == trees[1]:
            return "commits %s and %s hold the same tree" % (
                base["sha"][:12], head["sha"][:12]), []
    differing = differing_files(base["export"], head["export"])
    if not differing:
        return "%s is byte for byte the export of %s" % (
            head["shown"], base["shown"]), []
    return None, differing


def _same_verdict(result, out, why, allow_same):
    """The verdict when the head is the base: nothing is run, and the exit is 2
    unless the caller said identical sides are an answer."""
    result["same"] = True
    out.write("reach-diff: the head is the base: no change to measure - %s; "
              "no suite was run\n" % (why,))
    if allow_same:
        out.write("  exit 0 under --allow-same: the caller has said identical "
                  "sides are an answer, and this is not a measured conversion\n")
        result["code"] = 0
        return result
    return _refuse(result, out, "same", "a 0 here would read as a conversion "
                   "measured and found whole; pass --allow-same where identical "
                   "sides are the answer expected")


def _tail(text, count):
    lines = (text or "").rstrip("\n").split("\n")
    return lines[-count:]


def _render_lines(rows, indent):
    """`(function, line, text)` rows grouped under their function, in line order
    of each function's first row."""
    out, order, grouped = [], [], {}
    for qual, n, text in rows:
        if qual not in grouped:
            order.append(qual)
            grouped[qual] = []
        grouped[qual].append((n, text))
    for qual in order:
        out.append("%s%s" % (indent, qual))
        for n, text in grouped[qual]:
            out.append("%s  %5d  %s" % (indent, n, text))
    return out


def compare(repo, module, suite, base, head, jobs=None, timeout=None,
            tracer=None, out=None, allow_same=False, environ=None):
    """Run the comparison and print it to `out`; the result dict, whose `code`
    is the exit code the docstring's EXIT CODES state, and whose `refusal` is
    the first refusal's name. `environ` is the environment the runs start
    from, the process's own when None - threaded so a case can hand it an
    interpreter that cannot start without writing to the process's own."""
    out = out if out is not None else sys.stdout
    environ = os.environ if environ is None else environ
    began = time.monotonic()
    module, suite = _repo_relative(repo, module), _repo_relative(repo, suite)
    result = fresh_result()
    sweep = _sweep()
    jobs = jobs if jobs is not None else sweep.default_jobs()
    timeout = timeout if timeout is not None else (
        TIMEOUT_FACTOR * sweep.DEFAULT_TIMEOUT)
    if base == WORKTREE:
        return _refuse(result, out, "base-worktree", "--base %s is refused: the "
                       "base is the state a change started from, a commit; only "
                       "--head may name the working tree" % (WORKTREE,))
    entry, why = hook_entry(sweep.ambient_env(environ))
    if entry is None:
        return _refuse(result, out, "hook-probe", why)
    result["hook"] = entry
    scratch = tempfile.mkdtemp(prefix="reach-")
    try:
        os.makedirs(os.path.join(scratch, "hook"))
        write_hook(os.path.join(scratch, "hook"), entry)
        sides = []
        for name, rev in (("base", base), ("head", head)):
            side, refused = _prepare(repo, name, rev, module, suite, scratch,
                                     tracer, sweep, environ)
            if side is None:
                return _refuse(result, out, refused[0], refused[1])
            sides.append(side)
        why, differing = same_side(repo, sides[0], sides[1])
        if why:
            return _same_verdict(result, out, why, allow_same)
        out.write("reach-diff: %s under %s\n" % (module, suite))
        deciding = [rel for rel in differing if decides(rel, module, suite)]
        out.write("  the sides differ in %d files, %d of them deciding - the "
                  "module, the suite or a file Python can import: %s\n" % (
                      len(differing), len(deciding),
                      ", ".join(deciding) or "none, so the files that differ "
                      "are %s" % (", ".join(differing),)))
        out.write("  hook: %s\n" % (hook_line(entry),))
        pycache = os.path.join(scratch, "pycache")
        os.makedirs(pycache)
        rows = _measure(sweep, [(side, label) for side in sides
                                for label in side["labels"]],
                        suite, jobs, timeout, pycache)

        def recheck(labels):
            again, refused = _prepare(repo, "base-again", base, module, suite,
                                      scratch, tracer, sweep, environ)
            if again is None:
                return None, None, refused[1]
            return (_measure(sweep, [(again, label) for label in labels], suite,
                             jobs, timeout, pycache),
                    read_traces(again["out"]), None)
        _judge(sides, rows, result, out, began, jobs, recheck)
        if result["code"] == 0 and not deciding:
            return _no_conversion(result, out, differing, allow_same)
        return result
    finally:
        from _suite import remove_tree
        remove_tree(scratch)


def _no_conversion(result, out, differing, allow_same):
    """The verdict over sides measured whole that differ only in files that do
    not decide, with nothing lost: exit 2 unless the caller said so is the
    answer."""
    if allow_same:
        out.write("  exit 0 under --allow-same: only files that do not decide "
                  "differ (%s), and nothing was lost\n" % (", ".join(differing),))
        return result
    return _refuse(result, out, "no-conversion", "only files that do not decide "
                   "differ (%s) and nothing was lost: no evidence of a conversion; "
                   "pass --allow-same where that is the answer expected" % (
                       ", ".join(differing),))


def _blocks_reaching(by_block, lines, labels):
    """The labels among `labels` whose processes reached any of `lines`, in
    `labels` order - or every label, when a process no label names reached one,
    so that no line is left out of the recheck."""
    named = dict(((label or WHOLE_FILE), label) for label in labels)
    hit = set(block for block, reached in by_block.items() if reached & lines)
    if hit - set(named):
        return list(labels)
    return [label for label in labels if (label or WHOLE_FILE) in hit]


def case_ids(output):
    """The case ids a run printed - the word after `PASS` or `FAIL` on each
    case line - as a Counter, or None when it printed no case line."""
    found = CASE_LINE.findall(output or "")
    return Counter(found) if found else None


def _render_ids(ids):
    return ", ".join(sorted(ids.elements())) or "none"


# Each per-block multiset of processes a recheck must match its first run's, in
# the order they are checked and with the words a refusal names them by.
RECHECK_PROCESSES = (
    ("silent_by_block", "processes that never wrote what they reached"),
    ("untraced", "module children untraced"),
    ("written_by_block", "processes that wrote what they reached"),
)


def _recheck_refusal(rows, again, first, first_rows):
    """`(refusal name, why)` when the recheck cannot stand beside the base's
    first run, or None. The docstring's `recheck-` refusals are the rules; each
    comparison is an equality, so a difference in either direction refuses."""
    failed = [r for r in rows if not r["ok"]]
    if failed:
        return "recheck-failed", "%d of %d blocks run again did not pass: %s" % (
            len(failed), len(rows), "; ".join(
                "%s: %s" % (r["label"], r["why"]) for r in failed))
    if again["unreadable"]:
        return "recheck-unreadable", "%d trace files could not be read: %s" % (
            len(again["unreadable"]), "; ".join(again["unreadable"]))
    before = dict((r["label"], r) for r in first_rows if r["side"] == "base")
    for row in rows:
        label = row["label"]
        for key, what in RECHECK_PROCESSES:
            was = first[key].get(label, Counter())
            now = again[key].get(label, Counter())
            if was != now:
                return "recheck-processes", (
                    "block %s: its %s differ from its first run's - only in the "
                    "first run: %s; only run again: %s" % (
                        label, what, render_keys(was - now), render_keys(now - was)))
        then = before.get(label) or {}
        was, now = case_ids(then.get("output")), case_ids(row["output"])
        if was is not None and now is not None:
            if was != now:
                return "recheck-cases", (
                    "block %s ran other cases than in its first run, compared "
                    "by case id - only in the first run: %s; only run again: %s"
                    % (label, _render_ids(was - now), _render_ids(now - was)))
        elif row["cases"] != then.get("cases"):
            return "recheck-cases", (
                "block %s ran %s cases and %s in its first run, compared by the "
                "case count, since a run printed no case id" % (
                    label, row["cases"], then.get("cases")))
    return None


def _judge(sides, rows, result, out, began, jobs, recheck):
    """The verdict over the measured `rows`, printed and returned. `recheck`
    runs the given blocks of the base again in a fresh export: `(rows, traces,
    None)`, or `(None, None, why)` when the export could not be made."""
    failed = [r for r in rows if not r["ok"]]
    traces = dict((side["name"], read_traces(side["out"])) for side in sides)
    for side in sides:
        trace = traces[side["name"]]
        mine = [r for r in rows if r["side"] == side["name"]]
        result["reached"][side["name"]] = sorted(trace["lines"])
        result["processes"][side["name"]] = trace["written"]
        result["untraced"][side["name"]] = total(trace["untraced"])
        result["blocks"][side["name"]] = len(mine)
        out.write("  %s %s (%s): %d lines of the module reached; %d blocks run%s; "
                  "%d processes started the hook and %d wrote their lines (%s); "
                  "%d module children untraced\n" % (
                      side["name"], side["rev"], side["shown"],
                      len(trace["lines"]), len(mine),
                      " - %s" % (side["whole"],) if side["whole"] else "",
                      trace["started"], trace["written"],
                      ", ".join(trace["tracers"]) or "none",
                      total(trace["untraced"])))
        for bad in trace["unreadable"]:
            out.write("    a trace file could not be read: %s\n" % (bad,))
    result["tracers"] = sorted(set(t for tr in traces.values()
                                   for t in tr["tracers"]))
    seconds = time.monotonic() - began
    if failed:
        _refuse(result, out, "failed", "%d of %d blocks did not pass, and a reach "
                "measured over a suite that did not finish is not its reach:" % (
                    len(failed), len(rows)))
        for row in failed:
            out.write("  %s block %s: %s\n" % (row["side"], row["label"],
                                               row["why"]))
            for line in _tail(row["output"], 12):
                out.write("      %s\n" % (line,))
        out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
        return result
    ran = dict((side["name"], set(r["label"] for r in rows
                                   if r["side"] == side["name"]))
               for side in sides)
    spots = blind_spots(traces["base"]["untraced"], traces["head"]["untraced"],
                        ran["base"], ran["head"])
    unreadable = [side for side in sides if traces[side["name"]]["unreadable"]]
    if spots["unmatched"] or unreadable:
        for label, at_base, at_head, why in spots["unmatched"]:
            _refuse(result, out, "untraced", "block %s: module children were "
                    "started and never wrote what they reached (%s) - at the "
                    "base: %s; at the head: %s. A child started on the module's "
                    "path with an environment that drops the hook, or one that "
                    "ended without its exit handlers (os._exit, a kill, a "
                    "timeout), ran lines no trace holds" % (
                        label, why, render_keys(at_base), render_keys(at_head)))
        for side in unreadable:
            _refuse(result, out, "unreadable", "at %s (%s) %d trace files could "
                    "not be read" % (side["name"], side["rev"],
                                     len(traces[side["name"]]["unreadable"])))
        out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
        return result
    result["blind"] = spots["matched"]
    for label in sorted(spots["matched"]):
        out.write("  blind spot, the same at both revisions: block %s started the "
                  "same module children at both, none of which wrote what it "
                  "reached: %s; lines only they ran are measured at neither "
                  "revision\n" % (label, render_keys(
                      traces["base"]["untraced"][label])))
    for side in sides:
        if not traces[side["name"]]["lines"]:
            _refuse(result, out, "no-reach", "no line of the module was reached "
                    "at %s (%s): the suite does not run it there, or no process "
                    "it started ran the tracer" % (side["name"], side["rev"]))
            out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
            return result
    base, head = sides
    found = reach_gaps(base["module_source"], traces["base"]["lines"],
                       head["module_source"], traces["head"]["lines"])
    lost, sometimes = set(found["lost_at_base"]), set()
    if lost:
        labels = _blocks_reaching(traces["base"]["by_block"], lost,
                                  base["labels"])
        result["rechecked"] = [label or WHOLE_FILE for label in labels]
        again_rows, again, why = recheck(labels)
        refused = (("recheck-export", why) if why else
                   _recheck_refusal(again_rows, again, traces["base"], rows))
        if refused:
            _refuse(result, out, refused[0], "%d lines reached at %s and not at "
                    "%s could not be confirmed by running the blocks that "
                    "reached them again: %s" % (len(lost), base["rev"],
                                                head["rev"], refused[1]))
            for row in [r for r in again_rows or () if not r["ok"]]:
                for line in _tail(row["output"], 12):
                    out.write("      %s\n" % (line,))
            out.write("took %.1fs with %d jobs\n" % (
                time.monotonic() - began, jobs))
            return result
        sometimes = ((lost - again["lines"])
                     | (again["lines"] - traces["base"]["lines"]))
        out.write("  rechecked at %s: block %s ran again in a fresh export of the "
                  "same commit, to confirm the %d lines that looked lost\n" % (
                      base["rev"], ", ".join(result["rechecked"]), len(lost)))
    if sometimes:
        found = reach_gaps(base["module_source"],
                           traces["base"]["lines"] - sometimes,
                           head["module_source"], traces["head"]["lines"])
        result["flaky"] = reach_gaps(base["module_source"], sometimes,
                                     head["module_source"],
                                     traces["head"]["lines"])["gaps"]
    seconds = time.monotonic() - began
    result["gaps"], result["gone"] = found["gaps"], found["gone"]
    result["code"] = 1 if found["gaps"] else 0
    functions = len(set(g[0] for g in found["gaps"]))
    out.write("lost: %d lines reached at %s and not at %s, in %d functions "
              "(numbered as %s numbers them)\n" % (
                  len(found["gaps"]), base["rev"], head["rev"], functions,
                  head["rev"]))
    for line in _render_lines(found["gaps"], "  "):
        out.write(line + "\n")
    if found["gone"]:
        out.write("gone: %d lines reached at %s whose text the module at %s no "
                  "longer holds anywhere, so they are not judged (numbered as %s "
                  "numbers them)\n" % (len(found["gone"]), base["rev"],
                                       head["rev"], base["rev"]))
        for line in _render_lines(found["gone"], "  "):
            out.write(line + "\n")
    if result["flaky"]:
        out.write("sometimes: %d lines reached at %s in one of its runs and not "
                  "in the other, and not at %s, so they decide nothing "
                  "(numbered as %s numbers them)\n" % (
                      len(result["flaky"]), base["rev"], head["rev"],
                      head["rev"]))
        for line in _render_lines(result["flaky"], "  "):
            out.write(line + "\n")
    out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
    return result


# --- the command line ---------------------------------------------------------
_VALUE_FLAGS = ("--base", "--head", "--repo", "--jobs", "--timeout", "--tracer")


def parse_args(argv):
    """`(options, None)`, or `(None, why)` for a usage error."""
    opts, positional, i = {}, [], 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--allow-same":
            opts["allow_same"] = True
            i += 1
            continue
        if arg in _VALUE_FLAGS:
            if i + 1 >= len(argv):
                return None, "%s takes a value" % (arg,)
            opts[arg[2:]] = argv[i + 1]
            i += 2
            continue
        if arg.startswith("-"):
            return None, "unknown flag %s" % (arg,)
        positional.append(arg)
        i += 1
    if len(positional) != 2:
        return None, "expected <module> <suite>, got %d paths" % (len(positional),)
    if "base" not in opts or "head" not in opts:
        return None, "--base and --head are both required"
    for flag in ("jobs", "timeout"):
        if flag in opts:
            try:
                opts[flag] = int(opts[flag])
            except ValueError:
                opts[flag] = 0
            if opts[flag] < 1:
                return None, "--%s takes a positive whole number" % (flag,)
    if opts.get("tracer") not in (None,) + TRACERS:
        return None, "--tracer is one of %s" % (", ".join(TRACERS),)
    opts["module"], opts["suite"] = positional
    return opts, None


def main(argv, out=None):
    out = out if out is not None else sys.stdout
    if argv and argv[0] in ("-h", "--help"):
        out.write(__doc__.strip() + "\n")
        return 0
    opts, why = parse_args(argv)
    if opts is None:
        _refuse(fresh_result(), out, "usage", why)
        out.write(USAGE)
        return 2
    repo = os.path.abspath(opts.get("repo") or REPO)
    return compare(repo, opts["module"], opts["suite"], opts["base"],
                   opts["head"], jobs=opts.get("jobs"),
                   timeout=opts.get("timeout"), tracer=opts.get("tracer"),
                   out=out, allow_same=opts.get("allow_same", False))["code"]


# --- selftest -----------------------------------------------------------------
# The fixture is a git repository of its own, one tag per shape of the module and
# its suite, and every comparison below runs the real path end to end: an export
# per revision, the suite's blocks run with the tracer, the lines matched. The
# file names are built rather than spelled: a `.py` basename literal anywhere
# under `tools/` must name a file the tree holds.
_PY = ".py"
FIX_MODULE = "fixmod" + _PY
FIX_SUITE = "test_fixmod" + _PY

FIXTURE_GIT = ("git", "-c", "user.email=fixture@example.com",
               "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
               "-c", "init.defaultBranch=main", "-c", "maintenance.auto=false",
               "-c", "gc.auto=0")

MODULE_BASE = '''def pick(x):
    if x > 0:
        return "positive"
    return "other"


def in_child():
    return "seen in a child"


if __name__ == "__main__":
    print(in_child())
'''

# THE PURE REFACTOR: the two functions swap places under a comment that pushes
# every line down, so no reached line keeps its number and every one keeps its
# function and its text. A matcher by number reports gaps here; one by function
# and text reports none.
MODULE_MOVED = '''# Moved: the functions swapped places,
# and this comment pushes every line down.


def in_child():
    return "seen in a child"


def pick(x):
    if x > 0:
        return "positive"
    return "other"


if __name__ == "__main__":
    print(in_child())
'''

_SUITE_HEAD = '''import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.path.join(HERE, "fixmod" + ".py")


def load():
    spec = importlib.util.spec_from_file_location("fixmod", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _positive_cases(check):
    check("p1", load().pick(5) == "positive")


def _other_cases(check):
    check("o1", load().pick(-5) == %(other)s)


def _child_cases(check):
    paths = [os.path.join(HERE, "data"), tempfile.mkdtemp()]
    try:
        out = subprocess.run([sys.executable, MODULE] + %(child_args)s + paths,
                             stdout=subprocess.PIPE,
                             universal_newlines=True).stdout
    finally:
        os.rmdir(paths[1])
    check("c1", out.strip() == "seen in a child")


def _nothing_cases(check):
    check("z1", True)


def _shadowed_child_cases(check):
    planted = tempfile.mkdtemp()
    try:
        with open(os.path.join(planted, "sitecustomize" + ".py"), "w") as fh:
            fh.write("import sys\\n")
        held = os.environ.get("PYTHONPATH")
        env = dict(os.environ, PYTHONPATH=planted + (
            os.pathsep + held if held else ""))
        out = subprocess.run([sys.executable, MODULE], stdout=subprocess.PIPE,
                             universal_newlines=True, env=env).stdout
    finally:
        shutil.rmtree(planted)
    check("s1", out.strip() == "seen in a child")


def _stripped_child_cases(check):
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("REACH_DIFF"))
    out = subprocess.run([sys.executable, MODULE], stdout=subprocess.PIPE,
                         universal_newlines=True, env=env).stdout
    check("t1", out.strip() == "seen in a child")


def _route_cases(check):
    planted = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
               if p and os.path.isfile(os.path.join(p, "sitecustomize" + ".py"))]
    check("r1", not planted)


def _grade_cases(check):
    for value in GRADES:
        check("g%%d" %% (value,), load().grade(value) in (0, 1))


def _race_cases(check):
    check("x1", load().race() in ("first", "later"))


def _race_marked_cases(check):
    check("x2", load().race() == "later")


def _state_cases(check):
    check("x5", load().remember() in ("once", "again"))


def _race_fragile_cases(check):
    check("x3", load().race() == "first")


def _race_hard_cases(check):
    again = os.path.basename(HERE) == "base-again-tree"
    subprocess.run([sys.executable, MODULE] + (["exit-hard"] if again else []),
                   stdout=subprocess.PIPE, universal_newlines=True)
    check("x4", load().race() in ("first", "later"))


def _race_skip_cases(check):
    if os.path.basename(HERE) != "base-again-tree":
        subprocess.run([sys.executable, MODULE], stdout=subprocess.PIPE,
                       universal_newlines=True)
    check("x6", load().race() in ("first", "later"))


def _race_swap_cases(check):
    again = os.path.basename(HERE) == "base-again-tree"
    subprocess.run([sys.executable, MODULE, "swapped" if again else "kept"],
                   stdout=subprocess.PIPE, universal_newlines=True)
    check("x7", load().race() in ("first", "later"))


def _race_count_cases(check):
    check("x8", load().race() in ("first", "later"))
    if os.path.basename(HERE) == "base-again-tree":
        check("x9", True)


def _act_cases(check):
    check("a1", load().act() in ("took a", "took b"))


def _junk_cases(check):
    with open(os.path.join(os.environ["REACH_DIFF_OUT"], "junk.json"), "w") as fh:
        fh.write("{")
    check("j1", True)

'''

_SUITE_STAGED_MAIN = '''

def staged_main(argv):
    only = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--stage"]
    results = []

    def check(label, ok):
        results.append(bool(ok))
        print("%%s %%s" %% ("PASS" if ok else "FAIL", label))
    for label, fn in STAGES:
        if not only or label in only:
            globals()[fn](check)
    passed = sum(1 for r in results if r)
    print("%%d/%%d cases passed" %% (passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    %(prelude)ssys.exit(staged_main(sys.argv[1:]))
'''

_SUITE_PLAIN_MAIN = '''

def main():
    results = []

    def check(label, ok):
        results.append(bool(ok))
        print("%%s %%s" %% ("PASS" if ok else "FAIL", label))
    for fn in %(fns)s:
        globals()[fn](check)
    passed = sum(1 for r in results if r)
    print("%%d/%%d cases passed" %% (passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
'''

ALL_ROWS = (("positive", "_positive_cases"), ("other", "_other_cases"),
            ("child", "_child_cases"))


def _suite_head(other='"other"', child_args=(), grades=()):
    return (_SUITE_HEAD % {"other": other, "child_args": repr(list(child_args))}
            + "GRADES = %r\n" % (tuple(grades),))


def _staged_suite(rows=ALL_ROWS, other='"other"', prelude="", child_args=(),
                  grades=()):
    """A suite text whose `STAGES` table is `rows`, run block by block."""
    return (_suite_head(other, child_args, grades)
            + "STAGES = %r\n" % (tuple(rows),)
            + _SUITE_STAGED_MAIN % {"prelude": prelude})


def _plain_suite(fns):
    """A suite text with no `STAGES` table: one run of the whole file."""
    return _suite_head() + _SUITE_PLAIN_MAIN % {"fns": repr(list(fns))}


# A route line that occurs twice in one function, and a head that inserts a third
# copy ABOVE both: the head reaches the new copy and the first old one, and not the
# second old one. Matching by occurrence index pairs the base's two copies with the
# head's first two, both reached, and hides the loss.
GRADE_V1 = '''

def grade(x):
    if x == 1:
        return 0
    if x == 2:
        return 0
    return 1
'''
GRADE_V2 = GRADE_V1.replace("    if x == 1:\n",
                            "    if x == 0:\n        return 0\n    if x == 1:\n")

# A branch body moved into a new function, whose only case the head then drops:
# its text is still in the module, in another function, and nothing reaches it.
MODULE_EXTRACTED = MODULE_BASE.replace(
    '        return "positive"\n', "        return _positive()\n") + '''

def _positive():
    return "positive"
'''

# A child that reaches the module and ends without running its exit handlers, so
# whatever it reached is never written.
MODULE_HARD = MODULE_BASE.replace("    print(in_child())\n", (
    "    print(in_child())\n    import os\n    import sys\n"
    "    sys.stdout.flush()\n    if sys.argv[1:2] == [\"exit-hard\"]:\n"
    "        os._exit(0)\n"))

# A line the base reaches in one run and not in the next, from the same commit:
# the shape of a real race branch, made deterministic and stateless. `race()`
# takes its first branch only in the base's first export, so the recheck - a fresh
# export of the same commit under another directory name - takes the other, and
# so does every head. It reads no state a run leaves behind, because the recheck
# must see a difference no earlier run caused.
MODULE_RACE = MODULE_BASE + '''

def race():
    import os
    tree = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    if tree != "base-tree":
        return "later"
    first = "first"
    return first
'''

# A line skipped on a second run because the first run left a mark behind: a
# different input, not chance. Rechecked in the export the first run wrote into,
# the skipped lines would be set apart as reached only sometimes and a loss of
# them hidden; rechecked in a fresh export, they are reached again.
MODULE_STATE = MODULE_BASE + '''

def remember():
    import os
    mark = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.mark")
    if os.path.exists(mark):
        return "again"
    open(mark, "w").close()
    return "once"
'''

# A module whose reach turns on a data file it reads: a change to that file alone
# moves what the suite reaches, though no file Python imports differs.
MODULE_DATA = MODULE_BASE + '''

def mode():
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "data" + ".json")) as fh:
        return json.load(fh)["mode"]


def act():
    if mode() == "a":
        return "took a"
    return "took b"
'''

# Two absolute paths outside every export and every scratch directory: one
# machine names the same thing by each at both revisions, so a child given one is
# not the child given the other.
OUTSIDE_A = os.path.abspath(os.sep + "reach-diff-outside-a")
OUTSIDE_B = os.path.abspath(os.sep + "reach-diff-outside-b")

SHADOW_ROWS = ALL_ROWS[:2] + (("shadowed", "_shadowed_child_cases"),)
GRADE_ROWS = ALL_ROWS + (("grade", "_grade_cases"),)

FIXTURE_TAGS = (
    ("base", MODULE_BASE, _staged_suite()),
    ("moved", MODULE_MOVED, _staged_suite()),
    ("reworded", MODULE_BASE.replace('return "other"', 'return ("other")'),
     _staged_suite()),
    ("drop-positive", MODULE_BASE, _staged_suite(ALL_ROWS[1:])),
    ("drop-child", MODULE_BASE, _staged_suite(ALL_ROWS[:2])),
    ("red-case", MODULE_BASE, _staged_suite(other='"not what pick returns"')),
    ("crash", MODULE_BASE, _staged_suite(prelude="raise SystemExit(3)\n    ")),
    ("untouched", MODULE_BASE, _staged_suite((("nothing", "_nothing_cases"),))),
    ("plain-base", MODULE_BASE, _plain_suite(
        ["_positive_cases", "_other_cases", "_child_cases"])),
    ("plain-drop", MODULE_BASE, _plain_suite(["_other_cases", "_child_cases"])),
    ("shadow-base", MODULE_BASE, _staged_suite(SHADOW_ROWS)),
    ("shadow-drop", MODULE_BASE, _staged_suite(ALL_ROWS[:2])),
    ("stripped", MODULE_BASE, _staged_suite(
        ALL_ROWS[:2] + (("child", "_stripped_child_cases"),))),
    ("hard-exit", MODULE_HARD, _staged_suite(child_args=["exit-hard"])),
    ("hard-exit-drop", MODULE_HARD, _staged_suite(ALL_ROWS[1:],
                                                  child_args=["exit-hard"])),
    ("hard-exit-gone", MODULE_HARD, _staged_suite(ALL_ROWS[:2])),
    ("hard-exit-other", MODULE_HARD, _staged_suite(
        ALL_ROWS[1:], child_args=["exit-hard", "other"])),
    ("extracted", MODULE_EXTRACTED, _staged_suite(ALL_ROWS[1:])),
    ("dup-base", MODULE_BASE + GRADE_V1, _staged_suite(GRADE_ROWS,
                                                       grades=(1, 2, 3))),
    ("dup-insert", MODULE_BASE + GRADE_V2, _staged_suite(GRADE_ROWS,
                                                         grades=(0, 1, 3))),
    ("route", MODULE_BASE, _staged_suite(ALL_ROWS + (("route", "_route_cases"),))),
    ("race-base", MODULE_RACE, _staged_suite(ALL_ROWS + (("race", "_race_cases"),))),
    ("race-marked", MODULE_RACE, _staged_suite(
        ALL_ROWS + (("race", "_race_marked_cases"),))),
    ("race-drop", MODULE_RACE, _staged_suite(ALL_ROWS)),
    ("race-fragile", MODULE_RACE, _staged_suite(
        ALL_ROWS + (("race", "_race_fragile_cases"),))),
    ("race-hard", MODULE_HARD + MODULE_RACE[len(MODULE_BASE):], _staged_suite(
        ALL_ROWS + (("race", "_race_hard_cases"),))),
    ("race-hard-drop", MODULE_HARD + MODULE_RACE[len(MODULE_BASE):],
     _staged_suite(ALL_ROWS)),
    ("state-base", MODULE_STATE, _staged_suite(
        ALL_ROWS + (("state", "_state_cases"),))),
    ("state-drop", MODULE_STATE, _staged_suite(ALL_ROWS)),
    ("race-skip", MODULE_RACE, _staged_suite(
        ALL_ROWS + (("race", "_race_skip_cases"),))),
    ("race-swap", MODULE_RACE, _staged_suite(
        ALL_ROWS + (("race", "_race_swap_cases"),))),
    ("race-count", MODULE_RACE, _staged_suite(
        ALL_ROWS + (("race", "_race_count_cases"),))),
    ("outside-a", MODULE_HARD, _staged_suite(child_args=["exit-hard", OUTSIDE_A])),
    ("outside-a-drop", MODULE_HARD, _staged_suite(
        ALL_ROWS[1:], child_args=["exit-hard", OUTSIDE_A])),
    ("outside-b", MODULE_HARD, _staged_suite(child_args=["exit-hard", OUTSIDE_B])),
    ("unparsable", "def broken(:\n", _staged_suite()),
    ("junk-trace", MODULE_BASE, _staged_suite(
        ALL_ROWS + (("junk", "_junk_cases"),))),
)


def _fixture_git(cwd, *args):
    done = subprocess.run(FIXTURE_GIT + args, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip()


def _fixture_repo(root):
    """A repository holding one tagged commit per row of `FIXTURE_TAGS`."""
    _fixture_git(root, "init", "-q")
    for tag, module, suite in FIXTURE_TAGS:
        for name, text in ((FIX_MODULE, module), (FIX_SUITE, suite)):
            with io.open(os.path.join(root, name), "w", encoding="utf-8",
                         newline="\n") as fh:
                fh.write(text)
        _fixture_git(root, "add", "-A")
        _fixture_git(root, "commit", "-q", "--allow-empty", "-m", tag)
        _fixture_git(root, "tag", tag)
    return root


def _run(repo, head, base="base", suite=FIX_SUITE, module=FIX_MODULE,
         tracer=None, allow_same=False, environ=None):
    """`(exit code, the result dict, printed text)` for one comparison."""
    out = io.StringIO()
    result = compare(repo, module, suite, base, head, tracer=tracer, out=out,
                     allow_same=allow_same, environ=environ)
    return result["code"], result, out.getvalue()


def _refused(seen, text, name):
    """Whether `text` refuses for `name` and for no other reason. `name` goes
    into `seen` either way: that list is how the contract case knows which
    refusals the docstring names some case asserts."""
    seen.append(name)
    found = refusals_in(text)
    return bool(found) and set(found) == set([name])


def _gap_texts(result):
    return sorted((qual, text) for qual, _line, text in result.get("gaps", []))


def _key_cases(check):
    v1, v2 = MODULE_BASE + GRADE_V1, MODULE_BASE + GRADE_V2
    pairs = match_lines(v1, v2)
    later = [n for n, text in enumerate(v1.split("\n"), 1) if text == "        return 0"]
    now = [n for n, text in enumerate(v2.split("\n"), 1) if text == "        return 0"]
    check("rd10 two identical lines in one function are matched by alignment, "
          "not by which occurrence they are: a third copy inserted above both "
          "leaves each old copy paired with itself: %r -> %r, %r"
          % (later, now, dict((n, pairs.get(n)) for n in later)),
          len(later) == 2 and len(now) == 3
          and [pairs.get(n) for n in later] == now[1:])
    pairs = match_lines(MODULE_BASE, MODULE_MOVED)
    ret = [n for n, text in enumerate(MODULE_BASE.split("\n"), 1)
           if text.strip() == 'return "positive"']
    now = [n for n, text in enumerate(MODULE_MOVED.split("\n"), 1)
           if text.strip() == 'return "positive"']
    check("rd11 a line that only moved is paired with its new number - the "
          "property the refactor case below rests on: %r -> %r"
          % (ret, [pairs.get(n) for n in ret]),
          len(ret) == 1 and len(now) == 1 and ret != now
          and pairs.get(ret[0]) == now[0])


def _compare_cases(check, repo, seen):
    code, res, text = _run(repo, "drop-positive")
    check("rd1 a suite that stops reaching one branch exits 1 and names that "
          "line and its function - and only it: %r\n%s"
          % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [("pick", 'return "positive"')]
          and 'return "positive"' in text and "pick" in text)

    code, res, text = _run(repo, "moved")
    base_n = res.get("reached", {}).get("base", [])
    head_n = res.get("reached", {}).get("head", [])
    # `gone` is asserted empty as well as `gaps`: a matcher by number files every
    # moved line under gone rather than lost, which exits 0 just the same.
    check("rd2 a change that only MOVES the reached code exits 0 with no gap "
          "and nothing gone, over a comparison that measured lines at both "
          "ends: %r %r\n%s" % (_gap_texts(res), res.get("gone"), text),
          code == 0 and res.get("gaps") == [] and res.get("gone") == []
          and base_n and head_n)
    check("rd3 ...and the fixture can tell the two matchers apart: the line "
          "numbers reached at the two revisions differ, so a matcher by number "
          "would have reported a gap rd2 does not: %r vs %r" % (base_n, head_n),
          base_n and head_n and sorted(base_n) != sorted(head_n))

    code, res, text = _run(repo, "reworded")
    check("rd16 a reached line whose text changed is GONE, listed apart and "
          "numbered as the base numbered it, and decides nothing: the reworded "
          "line is reached at the head and nothing is lost: %r %r\n%s"
          % (_gap_texts(res), res.get("gone"), text),
          code == 0 and res.get("gaps") == []
          and res.get("gone") == [("pick", 4, 'return "other"')]
          and "gone: " in text)

    code, res, text = _run(repo, "drop-child")
    check("rd4 lines reached only in a CHILD interpreter the suite starts are "
          "measured: dropping the block that runs the module as a process "
          "exits 1 naming exactly the lines that process ran: %r\n%s"
          % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [
              ("<module>", "print(in_child())"),
              ("in_child", 'return "seen in a child"')])

    code, res, text = _run(repo, "red-case")
    check("rd5 a suite with a failing case at one revision is no measurement "
          "of its reach: exit 2, naming the block - never 0: %d\n%s"
          % (code, text),
          code == 2 and _refused(seen, text, "failed") and "other" in text
          and "FAIL" in text)

    code, res, text = _run(repo, "crash")
    # The block is named as not passing, not only refused: a crashed suite also
    # reaches no line, and the empty-reach refusal alone would exit 2 here too.
    check("rd6 a suite that fails to run at all exits 2, not 0, and says its "
          "blocks did not pass: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "failed") and "did not pass" in text
          and "exited 3" in text)

    code, res, text = _run(repo, "untouched")
    check("rd7 a revision at which no line of the module was reached is a run "
          "that measured nothing, and refuses with 2 rather than reporting "
          "every line as lost or none: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "no-reach") and "no line" in text)

    code, res, text = _run(repo, "plain-drop", base="plain-base")
    check("rd8 a suite with no `STAGES` table is run whole, and the same loss "
          "is found: %r\n%s" % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [("pick", 'return "positive"')])

    code, res, text = _run(repo, "shadow-drop", base="shadow-base")
    check("rd17 a child started under a suite's own sitecustomize, planted "
          "ahead of the hook on PYTHONPATH, is still traced: dropping that "
          "block exits 1 naming the lines the child ran: %r\n%s"
          % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [
              ("<module>", "print(in_child())"),
              ("in_child", 'return "seen in a child"')])

    code, res, text = _run(repo, "stripped")
    check("rd18 a child started on the module with an environment that does "
          "not carry the hook is an untraced module child: exit 2, counted "
          "for the head and not the base: %r\n%s"
          % (res.get("untraced"), text),
          code == 2 and res.get("untraced") == {"base": 0, "head": 1}
          and _refused(seen, text, "untraced"))

    code, res, text = _run(repo, "hard-exit")
    check("rd22 a module child that ran the hook and ended without its exit "
          "handlers wrote nothing it reached: it is counted as untraced too, "
          "exit 2: %r\n%s" % (res.get("untraced"), text),
          code == 2 and res.get("untraced") == {"base": 0, "head": 1}
          and _refused(seen, text, "untraced"))

    code, res, text = _run(repo, "hard-exit-drop", base="hard-exit")
    check("rd29 a block that ran at both revisions with the same untraced "
          "module children measured the same blind spot on both sides: it is "
          "printed, and the comparison goes on - the dropped branch still "
          "exits 1: %r %r\n%s" % (res.get("blind"), _gap_texts(res), text),
          code == 1 and res.get("blind") == {"child": 1}
          and _gap_texts(res) == [("pick", 'return "positive"')]
          and "blind spot" in text and "child" in text and not refusals_in(text)
          # The child is one key at both revisions although its arguments
          # name two export roots and two temp directories: a path under the
          # root is kept relative to it, one under the run's temp directory is
          # that directory's placeholder.
          and "<module> exit-hard <tree>/data <temp>;" in text)

    code, res, text = _run(repo, "hard-exit-gone", base="hard-exit")
    check("rd30 ...and a block whose module children were untraced at the base "
          "and that the head no longer runs is no matched blind spot: exit 2 "
          "naming it, so a removed block cannot take its children's lines out "
          "of the comparison silently: %d %r\n%s"
          % (code, res.get("blind"), text),
          code == 2 and _refused(seen, text, "untraced") and "child" in text
          and not res.get("blind"))

    code, res, text = _run(repo, "hard-exit-other", base="hard-exit")
    # Equal counts, different children: the base's untraced child ran the module
    # with one argument and the head's with another, so lines only one of them
    # ran are not the same blind spot. rd29 is the other direction: the same
    # child at both revisions, under two export roots, is still matched.
    check("rd41 a block that left the same NUMBER of module children untraced "
          "at both revisions, but not the same children, is no matched blind "
          "spot: exit 2 naming the block and each side's child: %d %r\n%s"
          % (code, res.get("blind"), text),
          code == 2 and not res.get("blind") and _refused(seen, text, "untraced")
          and "block child" in text
          and "<module> exit-hard other" in text
          and "the children differ" in text)

    code, res, text = _run(repo, "outside-b", base="outside-a")
    # A path outside the export and the temp and home directories names one
    # thing at both revisions, so it stays in the key: a placeholder for it would
    # make these two children one key and match them as one blind spot.
    check("rd47 two module children that differ only in an absolute path outside "
          "the export and the run's scratch directories are two children: exit "
          "2, the children differ, each named with its path: %d %r\n%s"
          % (code, res.get("blind"), text),
          code == 2 and not res.get("blind") and _refused(seen, text, "untraced")
          and "the children differ" in text and OUTSIDE_A in text
          and OUTSIDE_B in text)
    code, res, text = _run(repo, "outside-a-drop", base="outside-a")
    # The other direction for rd47: the same outside path at both revisions is
    # one key, so a key that varied by revision goes red here.
    check("rd48 ...and the same child given the same outside path at both "
          "revisions is one key, matched as a blind spot, the dropped branch "
          "still exiting 1: %r %r\n%s" % (res.get("blind"), _gap_texts(res), text),
          code == 1 and res.get("blind") == {"child": 1} and OUTSIDE_A in text
          and _gap_texts(res) == [("pick", 'return "positive"')])

    code, res, text = _run(repo, "moved", environ=dict(
        os.environ, PYTHONHOME=os.path.join(repo, "no-such-home")))
    check("rd52 an interpreter that cannot be asked whether it imports a "
          "usercustomize module is no run to trace: exit 2: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "hook-probe") and not res.get("blocks"))

    code, res, text = _run(repo, "unparsable")
    check("rd54 a module that does not parse at one revision refuses with 2, "
          "naming the revision: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "unparsable") and "unparsable" in text)

    code, res, text = _run(repo, "junk-trace")
    check("rd55 a trace file that cannot be read refuses with 2, naming the "
          "revision it was written at: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "unreadable") and "junk" in text)

    code, res, text = _run(repo, "extracted")
    check("rd19 a line moved into ANOTHER function and left unreached is "
          "lost, not gone: matched again by its text, exit 1, named under "
          "the function it is in now: %r %r\n%s"
          % (_gap_texts(res), res.get("gone"), text),
          code == 1 and _gap_texts(res) == [("_positive", 'return "positive"')]
          and res.get("gone") == [])

    code, res, text = _run(repo, "dup-insert", base="dup-base")
    v2_lines = (MODULE_BASE + GRADE_V2).split("\n")
    second = [n for n, t in enumerate(v2_lines, 1) if t == "        return 0"][2]
    check("rd20 a loss behind an identical line inserted earlier in the same "
          "function is found: exit 1 naming the later copy at line %d: %r\n%s"
          % (second, res.get("gaps"), text),
          code == 1 and res.get("gaps") == [("grade", second, "return 0")])

    # The other direction for rd18 and rd22: a run with every module child
    # traced counts none untraced, so the count does not fire on its own.
    code, res, text = _run(repo, "route")
    check("rd21 the hook changes nothing a suite can see about its path: no "
          "sitecustomize is put on PYTHONPATH, so a suite that routes on one "
          "runs as the sweep runs it; exit 0, nothing untraced: %r %r\n%s"
          % (res.get("untraced"), res.get("hook"), text),
          code == 0 and res.get("untraced") == {"base": 0, "head": 0}
          and res.get("hook") == "usercustomize")

    code, res, text = _run(repo, "drop-positive", tracer="settrace")
    check("rd9 the settrace tracer the 3.8 floor runs on finds what rd1 found: "
          "%r\n%s" % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [("pick", 'return "positive"')]
          and res.get("tracers") == ["settrace"])


def _same_cases(check, repo, seen):
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    check("rd31 --base HEAD --head WORKTREE over a clean checkout copies exactly "
          "the base, so it measures no change: exit 2, saying the head is the "
          "base, and no suite is run: %d %r\n%s"
          % (code, res.get("same"), text),
          code == 2 and res.get("same") is True and _refused(seen, text, "same")
          and "the head is the base: no change to measure" in text
          and "lost:" not in text and not res.get("blocks"))
    shas = [_fixture_git(repo, "rev-parse", tag) for tag in
            ("drop-child", "shadow-drop")]
    code, res, text = _run(repo, "shadow-drop", base="drop-child")
    check("rd32 two DIFFERENT commits holding the same tree are the same side "
          "too - the content decides, not the name: exit 2: %r %d\n%s"
          % (shas, code, text),
          shas[0] != shas[1] and code == 2 and res.get("same") is True
          and _refused(seen, text, "same") and "the head is the base" in text)
    out = io.StringIO()
    code = main([FIX_MODULE, FIX_SUITE, "--base", "base", "--head", "base",
                 "--repo", repo, "--allow-same"], out=out)
    text = out.getvalue()
    check("rd33 --allow-same is the caller saying identical sides are an "
          "answer: exit 0, and the line saying the head is the base is still "
          "printed, with nothing measured: %d\n%s" % (code, text),
          code == 0 and "the head is the base: no change to measure" in text
          and "lost:" not in text)


def _flaky_texts(result):
    return _gap_texts({"gaps": result.get("flaky") or []})


def _flaky_cases(check, repo, seen):
    code, res, text = _run(repo, "race-marked", base="race-base")
    check("rd34 a line the base reaches in one run and not when its block runs "
          "again is reported apart as reached only sometimes, and decides "
          "nothing: the race's first branch, missed by the head, exits 0: "
          "%r %r\n%s" % (_gap_texts(res), _flaky_texts(res), text),
          code == 0 and res.get("gaps") == []
          and _flaky_texts(res) == [
              ("race", 'first = "first"'), ("race", "return first")]
          and res.get("rechecked") == ["race"] and "sometimes" in text)
    code, res, text = _run(repo, "race-drop", base="race-base")
    check("rd35 ...and a line the base reached in BOTH its runs and the head "
          "never reaches is still lost, in the same comparison that set the "
          "race's branches apart: exit 1 naming exactly the always-reached "
          "lines: %r %r\n%s" % (_gap_texts(res), res.get("flaky"), text),
          code == 1 and _gap_texts(res) == [
              ("race", 'if tree != "base-tree":'), ("race", "import os"),
              ("race", "tree = os.path.basename(os.path.dirname("
                       "os.path.abspath(__file__)))")]
          and _flaky_texts(res) == [
              ("race", 'first = "first"'), ("race", 'return "later"'),
              ("race", "return first")])
    # The other direction for rd34: the recheck runs and confirms an ordinary
    # loss, so a mutation that files every rechecked line as sometimes-reached
    # goes red here as well as in rd1.
    code, res, text = _run(repo, "drop-positive")
    check("rd36 a line every base run reaches is confirmed, not set apart: the "
          "block that reached it is run again, nothing is reached only "
          "sometimes, exit 1: %r %r %r"
          % (res.get("rechecked"), res.get("flaky"), _gap_texts(res)),
          code == 1 and res.get("rechecked") == ["positive"]
          and res.get("flaky") == []
          and _gap_texts(res) == [("pick", 'return "positive"')])
    code, res, text = _run(repo, "race-drop", base="race-fragile")
    check("rd37 a recheck whose block does not pass is no evidence that a line "
          "is reached only sometimes: exit 2, saying the lost lines could not "
          "be confirmed - never 0 and never a list set apart: %d %r\n%s"
          % (code, res.get("flaky"), text),
          code == 2 and _refused(seen, text, "recheck-failed")
          and "could not be confirmed" in text and "did not pass" in text
          and res.get("flaky") == [] and res.get("rechecked") == ["race"])
    code, res, text = _run(repo, "race-hard-drop", base="race-hard")
    check("rd38 ...nor is a recheck whose block left a process that never wrote "
          "what it reached, which its first run did not: exit 2: %d %r\n%s"
          % (code, res.get("flaky"), text),
          code == 2 and _refused(seen, text, "recheck-processes")
          and "never wrote" in text and res.get("flaky") == [])
    code, res, text = _run(repo, "state-drop", base="state-base")
    check("rd40 a line the base's first run would skip on a second pass over "
          "the files it wrote is still lost: the recheck runs in a fresh "
          "export, so state left behind is not read as chance - exit 1, "
          "every line of the dropped block named, none set apart: %r %r\n%s"
          % (_gap_texts(res), res.get("flaky"), text),
          code == 1 and res.get("flaky") == [] and res.get("rechecked") == ["state"]
          and _gap_texts(res) == [
              ("remember", "if os.path.exists(mark):"),
              ("remember", "import os"),
              ("remember", "mark = os.path.join(os.path.dirname(os.path.abspath("
                           '__file__)), "seen.mark")'),
              ("remember", 'open(mark, "w").close()'),
              ("remember", 'return "once"')])
    code, res, text = _run(repo, "race-drop", base="race-skip")
    check("rd44 a recheck whose block wrote FEWER processes than its first "
          "run - a child it did not start again - is no evidence of chance: "
          "exit 2, naming the process that did not write again: %d %r\n%s"
          % (code, res.get("flaky"), text),
          code == 2 and _refused(seen, text, "recheck-processes")
          and "only in the first run: <module>" in text and res.get("flaky") == [])
    code, res, text = _run(repo, "race-drop", base="race-swap")
    check("rd45 ...nor is one that wrote as MANY processes but not the same "
          "ones - a child started with other arguments: the processes are "
          "compared as sets, exit 2 naming the first run's: %d %r\n%s"
          % (code, res.get("flaky"), text),
          code == 2 and _refused(seen, text, "recheck-processes")
          and "<module> kept" in text and res.get("flaky") == [])
    code, res, text = _run(repo, "race-drop", base="race-count")
    check("rd46 ...nor one whose block ran other cases than in its first run: "
          "exit 2, naming by id the case only the recheck ran: %d %r\n%s"
          % (code, res.get("flaky"), text),
          code == 2 and _refused(seen, text, "recheck-cases")
          and "by case id" in text and "x9" in text and res.get("flaky") == [])


def _usage_cases(check, repo, seen):
    def quiet(argv):
        out = io.StringIO()
        return main(argv, out=out), out.getvalue()
    code, text = quiet([])
    check("rd12 no arguments is a usage error, 2: %d %r" % (code, text),
          code == 2 and _refused(seen, text, "usage"))
    code, text = quiet([FIX_MODULE, FIX_SUITE, "--base", "base", "--head",
                        "no-such-rev", "--repo", repo])
    check("rd13 a revision git cannot resolve is a usage error naming it: "
          "%d %r" % (code, text),
          code == 2 and _refused(seen, text, "revision") and "no-such-rev" in text)
    code, text = quiet(["missing" + _PY, FIX_SUITE, "--base", "base",
                        "--head", "moved", "--repo", repo])
    check("rd14 a module the revision does not hold refuses with 2: %d %r"
          % (code, text),
          code == 2 and _refused(seen, text, "missing") and "missing" in text)


WT_NOTES = "notes.txt"
WT_IGNORED = "build.log"
WT_UNTRACKED = "new_suite" + _PY


def _worktree_repo(root):
    """A repository whose last commit is the base fixture, and whose working
    tree drops the positive block from the suite uncommitted, adds an
    untracked suite file and an ignored one, and deletes a tracked file."""
    _fixture_git(root, "init", "-q")
    files = ((FIX_MODULE, MODULE_BASE), (FIX_SUITE, _staged_suite()),
             (".gitignore", "*.log\n"), (WT_NOTES, "kept in git\n"))
    for name, text in files:
        with io.open(os.path.join(root, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    _fixture_git(root, "add", "-A")
    _fixture_git(root, "commit", "-q", "-m", "base")
    for name, text in ((FIX_SUITE, _staged_suite(ALL_ROWS[1:])),
                       (WT_UNTRACKED, "UNTRACKED = True\n"),
                       (WT_IGNORED, "ignored\n")):
        with io.open(os.path.join(root, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    os.remove(os.path.join(root, WT_NOTES))
    return root


def _worktree_cases(check, root, seen):
    repo = os.path.join(root, "wt")
    os.makedirs(repo)
    _worktree_repo(repo)
    status = _fixture_git(repo, "status", "--porcelain", "--ignored")
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    check("rd25 --head WORKTREE measures the uncommitted change: the suite on "
          "disk dropped the positive block, so the branch it reached is lost, "
          "exit 1: %r\n%s" % (_gap_texts(res), text),
          code == 1 and _gap_texts(res) == [("pick", 'return "positive"')])
    code, res, text = _run(repo, "HEAD", base="HEAD")
    check("rd26 ...and --head HEAD over the same checkout names the last "
          "commit, which is the base: refused with 2 as no change to measure, "
          "which is what proves rd25's head was the working tree: %d\n%s"
          % (code, text),
          code == 2 and res.get("same") is True and _refused(seen, text, "same")
          and "the head is the base" in text)
    dest = os.path.join(root, "wt-export")
    os.makedirs(dest)
    why = export_worktree(repo, dest)
    on_disk = io.open(os.path.join(repo, FIX_SUITE), encoding="utf-8").read()
    copied = os.path.join(dest, FIX_SUITE)
    got = sorted(os.listdir(dest))
    check("rd27 the working tree is materialised as git would list it: the "
          "modified suite as it is on disk, the untracked suite file present, "
          "the ignored file and the deleted tracked file absent, no git dir; "
          "and the checkout's status is unchanged: %r %r" % (why, got),
          why is None and WT_UNTRACKED in got and WT_IGNORED not in got
          and WT_NOTES not in got and ".git" not in got
          and io.open(copied, encoding="utf-8").read() == on_disk
          and _fixture_git(repo, "status", "--porcelain", "--ignored") == status)
    edited = os.path.join(root, "wt-edit")
    os.makedirs(edited)
    _fixture_git(edited, "init", "-q")
    for name, text in ((FIX_MODULE, MODULE_BASE), (FIX_SUITE, _staged_suite())):
        with io.open(os.path.join(edited, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    _fixture_git(edited, "add", "-A")
    _fixture_git(edited, "commit", "-q", "-m", "base")
    with io.open(os.path.join(edited, FIX_SUITE), "w", encoding="utf-8",
                 newline="\n") as fh:
        fh.write(_staged_suite(ALL_ROWS[1:]))
    code, res, text = _run(edited, "WORKTREE", base="HEAD")
    # The other direction for rd31: the same file names with one file's bytes
    # changed are a change, so a comparison by names alone goes red here.
    check("rd39 a working tree that changes only a file's content, no name, is "
          "not the base: it is measured, and the dropped branch exits 1: "
          "%r %r\n%s" % (res.get("same"), _gap_texts(res), text),
          code == 1 and res.get("same") is False
          and _gap_texts(res) == [("pick", 'return "positive"')])
    _clean_differs_cases(check, root, seen)
    _data_cases(check, root)
    _export_cases(check, root, seen)
    out = io.StringIO()
    code = main([FIX_MODULE, FIX_SUITE, "--base", "WORKTREE", "--head", "HEAD",
                 "--repo", repo], out=out)
    check("rd28 --base WORKTREE is refused with 2: the base is the state the "
          "change started from, which a working tree is not: %d %r"
          % (code, out.getvalue()),
          code == 2 and _refused(seen, out.getvalue(), "base-worktree")
          and "WORKTREE" in out.getvalue())


WT_JOURNAL = "journal.jsonl"
WT_HELPER = "helper" + _PY


def _clean_differs_cases(check, root, seen):
    """A committed base whose working tree adds files the suite cannot import,
    then one it can."""
    repo = os.path.join(root, "wt-clean")
    os.makedirs(repo)
    _fixture_git(repo, "init", "-q")
    for name, text in ((FIX_MODULE, MODULE_BASE), (FIX_SUITE, _staged_suite())):
        with io.open(os.path.join(repo, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    _fixture_git(repo, "add", "-A")
    _fixture_git(repo, "commit", "-q", "-m", "base")
    with io.open(os.path.join(repo, WT_JOURNAL), "w", encoding="utf-8",
                 newline="\n") as fh:
        fh.write('{"row": 1}\n')
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    check("rd42 a working tree that differs from the base only in a file no "
          "Python process imports - an untracked journal row - is measured, "
          "and with nothing lost it is no evidence of a conversion: exit 2, "
          "the differing file named: %d %r\n%s" % (code, res.get("same"), text),
          code == 2 and res.get("same") is False
          and _refused(seen, text, "no-conversion") and WT_JOURNAL in text
          and "lost: 0" in text and res.get("blocks"))
    code, res, text = _run(repo, "WORKTREE", base="HEAD", allow_same=True)
    check("rd51 ...and under --allow-same the same measurement exits 0: %d\n%s"
          % (code, text),
          code == 0 and not refusals_in(text) and "lost: 0" in text
          and "--allow-same" in text)
    with io.open(os.path.join(repo, WT_HELPER), "w", encoding="utf-8",
                 newline="\n") as fh:
        fh.write("HELPER = True\n")
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    # The other direction for rd42: a differing file Python can import is a
    # change, so a rule that ignored every file but the module and the suite
    # goes red here.
    check("rd43 ...and one that also adds a file Python can import is a change: "
          "measured, nothing lost, exit 0: %d %r\n%s"
          % (code, res.get("same"), text),
          code == 0 and res.get("same") is False and "lost: 0" in text)


WT_DATA = "data" + ".json"


def _data_cases(check, root):
    """A committed base whose working tree changes only a data file the module
    reads, moving which branch the suite reaches."""
    repo = os.path.join(root, "wt-data")
    os.makedirs(repo)
    _fixture_git(repo, "init", "-q")
    files = ((FIX_MODULE, MODULE_DATA), (WT_DATA, '{"mode": "a"}\n'),
             (FIX_SUITE, _staged_suite(ALL_ROWS + (("act", "_act_cases"),))))
    for name, text in files:
        with io.open(os.path.join(repo, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    _fixture_git(repo, "add", "-A")
    _fixture_git(repo, "commit", "-q", "-m", "base")
    with io.open(os.path.join(repo, WT_DATA), "w", encoding="utf-8",
                 newline="\n") as fh:
        fh.write('{"mode": "b"}\n')
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    check("rd50 a change confined to a data file the module reads is measured, "
          "not refused as no change: the branch it stops taking is lost, exit "
          "1: %d %r\n%s" % (code, _gap_texts(res), text),
          code == 1 and res.get("same") is False and not refusals_in(text)
          and _gap_texts(res) == [("act", 'return "took a"')])


def _export_cases(check, root, seen):
    """A base commit git cannot export: an object it names is gone."""
    repo = os.path.join(root, "corrupt")
    os.makedirs(repo)
    _fixture_git(repo, "init", "-q")
    for name, text in ((FIX_MODULE, MODULE_BASE), (FIX_SUITE, _staged_suite())):
        with io.open(os.path.join(repo, name), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    _fixture_git(repo, "add", "-A")
    _fixture_git(repo, "commit", "-q", "-m", "base")
    blob = _fixture_git(repo, "rev-parse", "HEAD:" + FIX_SUITE)
    loose = os.path.join(repo, ".git", "objects", blob[:2], blob[2:])
    os.chmod(loose, stat.S_IREAD | stat.S_IWRITE)
    os.remove(loose)
    code, res, text = _run(repo, "WORKTREE", base="HEAD")
    check("rd53 a revision git cannot export refuses with 2, naming it: %d\n%s"
          % (code, text),
          code == 2 and _refused(seen, text, "export") and not res.get("blocks"))


# --- the recheck, judged over traces written by hand ----------------------------
JUDGE_SOURCE = "a = 1\nb = 2\n"
JUDGE_CASES = "PASS a1\nPASS a2\n2/2 cases passed\n"


def _trace_dir(path, records, junk=False):
    """`path`, holding one lines file per record, each a traced process of
    block `blk` in the hook's shape; and an unreadable one under `junk`."""
    os.makedirs(path)
    for n, record in enumerate(records):
        data = {"tracer": "settrace", "parent": None, "module": False,
                "spawned": [], "block": "blk"}
        data.update(record)
        with io.open(os.path.join(path, "p%d.json" % (n,)), "w",
                     encoding="utf-8") as fh:
            fh.write(json.dumps(data))
    if junk:
        with io.open(os.path.join(path, "junk.json"), "w", encoding="utf-8") as fh:
            fh.write("{")
    return path


def _judged(root, again=None, again_output=JUDGE_CASES, again_cases=2,
            first_output=JUDGE_CASES, export_failed=None, junk=False):
    """`(exit code, result, text)` of `_judge` over a base whose one process
    reached both lines of `JUDGE_SOURCE`, a head reaching the first only, and
    a recheck of `again` - the base's own process when None."""
    os.makedirs(root)
    first = [{"lines": [1, 2], "argv": ["suite"]}]
    sides = [{"name": name, "rev": name, "shown": name, "whole": None,
              "labels": ["blk"], "module_source": JUDGE_SOURCE,
              "out": _trace_dir(os.path.join(root, name), records)}
             for name, records in (("base", first),
                                   ("head", [{"lines": [1], "argv": ["suite"]}]))]
    rows = [{"side": name, "label": "blk", "ok": True, "why": None, "cases": 2,
             "output": first_output, "seconds": 0.0} for name in ("base", "head")]

    def recheck(labels):
        if export_failed:
            return None, None, export_failed
        path = _trace_dir(os.path.join(root, "again"),
                          first if again is None else again, junk)
        return ([{"side": "base-again", "label": label, "ok": True, "why": None,
                  "cases": again_cases, "output": again_output, "seconds": 0.0}
                 for label in labels], read_traces(path), None)
    out = io.StringIO()
    result = _judge(sides, rows, fresh_result(), out, time.monotonic(), 1, recheck)
    return result["code"], result, out.getvalue()


def _judge_cases(check, root, seen):
    code, res, text = _judged(os.path.join(root, "j-same"))
    # The other direction for every recheck refusal: a recheck that ran the
    # same processes and the same cases confirms the loss, so a refusal that
    # fired on equal runs goes red here.
    check("rd61 a recheck that ran the same processes and the same cases as "
          "the first run confirms the loss: exit 1, nothing refused: %d\n%s"
          % (code, text),
          code == 1 and not refusals_in(text)
          and res.get("gaps") == [("<module>", 2, "b = 2")])
    code, res, text = _judged(os.path.join(root, "j-export"),
                              export_failed="the fresh export failed")
    check("rd56 a recheck whose fresh export could not be made refuses with 2: "
          "%d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "recheck-export")
          and "the fresh export failed" in text)
    code, res, text = _judged(os.path.join(root, "j-junk"), junk=True)
    check("rd57 a recheck whose trace cannot be read refuses with 2: %d\n%s"
          % (code, text), code == 2 and _refused(seen, text, "recheck-unreadable"))
    code, res, text = _judged(os.path.join(root, "j-more"), again=[
        {"lines": [1, 2], "argv": ["suite"]}, {"lines": [], "argv": ["suite", "extra"]}])
    check("rd58 a recheck that wrote a process its first run did not - MORE "
          "writers, not fewer - is no evidence of chance: exit 2, naming the "
          "process only the recheck wrote: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "recheck-processes")
          and "only run again: suite extra" in text)
    code, res, text = _judged(os.path.join(root, "j-ids"), again_output=(
        "PASS a1\nPASS a3\n2/2 cases passed\n"))
    check("rd59 a recheck that ran as many cases but not the same ones is "
          "refused, the cases compared by id: exit 2 naming each side's: %d\n%s"
          % (code, text),
          code == 2 and _refused(seen, text, "recheck-cases") and "by case id" in text
          and "only in the first run: a2" in text and "only run again: a3" in text)
    code, res, text = _judged(os.path.join(root, "j-count"),
                              first_output="2/2 cases passed\n",
                              again_output="3/3 cases passed\n", again_cases=3)
    check("rd60 ...and where neither run printed a case id, the case count is "
          "what is compared, and the refusal says so: %d\n%s" % (code, text),
          code == 2 and _refused(seen, text, "recheck-cases")
          and "by the case count" in text)


def _hook_cases(check, root):
    """The hook in one process that rewrites the block label before it exits."""
    hook_dir, out_dir = os.path.join(root, "hook"), os.path.join(root, "out")
    os.makedirs(hook_dir)
    os.makedirs(out_dir)
    entry, why = hook_entry(dict(os.environ))
    if entry:
        write_hook(hook_dir, entry)
    env = traced_env(hook_dir, os.path.join(root, FIX_MODULE), out_dir, None, root)
    env[ENV_BLOCK] = "installed"
    done = subprocess.run(
        [sys.executable, "-c", "import os; os.environ[%r] = 'changed'" % (ENV_BLOCK,)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)
    traces = read_traces(out_dir)
    check("rd49 a process that changes its block label before it exits is filed "
          "under the label it was started with, read when the hook installed: "
          "%r %r %r %r" % (why, done.returncode, done.stdout[-300:],
                           sorted(traces["written_by_block"])),
          entry is not None and done.returncode == 0 and traces["written"] == 1
          and sorted(traces["written_by_block"]) == ["installed"])


def _contract_cases(check, seen):
    named = list(REFUSALS)
    asserted = set(seen)
    check("rd62 every refusal --help names has a case asserting it, and every "
          "refusal a case asserts is named there: unasserted %r, unnamed %r"
          % (sorted(set(named) - asserted), sorted(asserted - set(named))),
          named and len(named) == len(set(named)) and set(named) == asserted)
    try:
        _refuse(fresh_result(), io.StringIO(), "no-such-refusal", "a reason")
        raised = None
    except ValueError as exc:
        raised = exc
    check("rd63 a refusal site naming a refusal --help does not name raises "
          "rather than printing an undocumented reason: %r" % (raised,),
          raised is not None and "no-such-refusal" in str(raised))


def _cases(check):
    _key_cases(check)
    seen = []
    root = tempfile.mkdtemp(prefix="rd-")
    try:
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        _fixture_repo(repo)
        status = _fixture_git(repo, "status", "--porcelain", "--ignored")
        _compare_cases(check, repo, seen)
        _same_cases(check, repo, seen)
        _flaky_cases(check, repo, seen)
        _usage_cases(check, repo, seen)
        after = _fixture_git(repo, "status", "--porcelain", "--ignored")
        check("rd15 the repository compared is never written: its status, "
              "ignored files included, is the same after every comparison "
              "above: %r -> %r" % (status, after), status == after == "")
        _worktree_cases(check, root, seen)
        _judge_cases(check, os.path.join(root, "judge"), seen)
        _hook_cases(check, os.path.join(root, "hooked"))
        _contract_cases(check, seen)
    finally:
        from _suite import remove_tree
        remove_tree(root)


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
