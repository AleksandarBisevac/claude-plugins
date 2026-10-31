#!/usr/bin/env python3
"""Which lines of a module its suite reached at one revision and no longer reaches at another.

    python3 tools/reach-diff.py <module> <suite> --base <rev> --head <rev>
        [--repo PATH] [--jobs N] [--timeout S] [--tracer monitoring|settrace]

e.g. python3 tools/reach-diff.py plugins/audit/scripts/governance/drive-phase.py \\
         tests/test_drive_phase.py --base 92c399f5 --head HEAD

WHY THIS EXISTS. A suite converted from end-to-end drives to unit cases over a
decision function keeps its decisions tested and can stop running the code that ACTS
on a decision - the branch that routes to the answer, the line that appends what the
answer printed. Nothing about the converted suite looks wrong: every case passes and
every case is about the planner. Reviews found that shape by reading, one instance at
a time, and a reader finds the instances they think to look for. This is the
invariant instead: every line of the module the old suite reached, the new suite
still reaches, or the line is named. It is the check a conversion owes.

HOW A REVISION IS MEASURED. Each revision is a `git archive` export into a scratch
directory (the checkout is never written, and no worktree is registered in its git
dir). The suite is run there the way the sweep runs it - the sweep's own `run_one`
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
it installs and its lines when it exits.

THE ROUTE IS THE SWEEP'S. A suite may decide how to run something by what is on
`PYTHONPATH` - the drive suite runs a verb as a process rather than in its own
interpreter when a `sitecustomize` sits there, since only a fresh interpreter imports
one. The `usercustomize` entry adds none, so such a suite takes the route it takes
under the sweep. The `sitecustomize` fallback does add one, and under it every verb
that suite would run in-process runs as a process, at both revisions alike: the
reach measured is then the process route's, not the sweep's.

UNTRACED MODULE CHILDREN DECIDE THE EXIT. Each traced process counts the children it
starts through `subprocess.Popen` with the module's path among their arguments, and
hands each child a token naming itself in the environment; each traced process
records whether it is running the module and the token of its parent. A child
started on the module that never wrote its lines - one handed an environment that
drops the hook, one started with `-I`, `-E`, `-S` or (under the `usercustomize`
entry) `-s`, one that ended through
`os._exit`, a kill or a timeout - is one its parent counted and nothing answered. A
revision with any such child, or with a trace file that cannot be read, refuses with
2: its reach is short by lines nothing measured, and a comparison over it could
hide a loss or invent one.

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

A RUN THAT MEASURED NOTHING IS NOT A PASS. Any block that failed - a red case, a
crash, a timeout, no contract line - an untraced module child, or a revision at
which no line of the module was reached at all, refuses with 2 and says which: a
reach measured over a suite that did not finish is not the suite's reach.

Exit codes: 0 no line lost - 1 a line lost - 2 usage error, or no comparison made.
"""
import ast
import difflib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
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

USAGE = ("usage: reach-diff.py <module> <suite> --base <rev> --head <rev> "
         "[--repo PATH] [--jobs N] [--timeout S] [--tracer monitoring|settrace]\n")


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
# The module names the hook is written as. `usercustomize` is imported by `site`
# after whichever `sitecustomize` won, so a suite that plants its own sitecustomize
# first on PYTHONPATH still runs the hook, and the hook adds no sitecustomize for a
# suite to see. Where the interpreter's user site is off it is never imported, and
# the hook falls back to being the `sitecustomize`.
HOOK_USER = "usercustomize"
HOOK_SITE = "sitecustomize"
USER_SITE_PROBE = "import site; print(site.ENABLE_USER_SITE)"


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
# by a token it also hands its children in the environment, and the lines file
# counts the children it started on the module's path - an audit hook on
# `subprocess.Popen` - so the reader can tell a module child that was traced from
# one that was started and never wrote.
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
    verdicts = {}
    lines = set()
    spawned = []
    token = "%d-%s" % (os.getpid(), os.urandom(6).hex())
    parent = os.environ.get("REACH_DIFF_PARENT")
    os.environ["REACH_DIFF_PARENT"] = token
    script = sys.argv[0] if getattr(sys, "argv", None) else ""
    is_module = bool(script) and not script.startswith("-") and norm(script) == want

    def write(suffix, record):
        path = os.path.join(out_dir, token + suffix)
        with open(path + ".part", "w") as fh:
            json.dump(record, fh)
        os.replace(path + ".part", path)
    write(".start", {"parent": parent, "module": is_module})

    def names_module(args):
        if isinstance(args, (str, bytes)):
            return False
        for arg in args or ():
            try:
                arg = os.fsdecode(arg)
            except TypeError:
                continue
            if arg and not arg.startswith("-") and norm(arg) == want:
                return True
        return False

    def on_event(event, args):
        if event == "subprocess.Popen" and names_module(args[1]):
            spawned.append(1)
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
                        "parent": parent, "module": is_module,
                        "spawned": len(spawned)})
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
    """`{"gaps": [...], "gone": [...]}`, each a list of `(function, line, text)`.

    `gaps` are lines reached at the base that `match_lines` pairs with a head
    line the head's suite did not reach, named and numbered as the head has
    them; `gone` are lines reached at the base whose text the head's module no
    longer holds anywhere, named and numbered as the base had them. Both in line
    order."""
    pairs = match_lines(base_source, head_source)
    base_rows = dict((r[0], r) for r in code_lines(base_source))
    head_rows = dict((r[0], r) for r in code_lines(head_source))
    reached_now = set(head_lines)
    gaps, gone = [], []
    for n in sorted(set(base_lines)):
        if n not in base_rows:
            continue
        if n not in pairs:
            gone.append(base_rows[n][1:2] + (n, base_rows[n][2]))
        elif pairs[n] not in reached_now:
            row = head_rows[pairs[n]]
            gaps.append((row[1], row[0], row[2]))
    return {"gaps": sorted(gaps, key=lambda g: g[1]), "gone": gone}


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


def traced_env(hook_dir, module_path, out_dir, tracer, environ=None):
    """The caller's environment with the hook first on `PYTHONPATH` and the
    module, the output directory and the tracer named."""
    env = dict(os.environ if environ is None else environ)
    prior = env.get("PYTHONPATH")
    env["PYTHONPATH"] = hook_dir + (os.pathsep + prior if prior else "")
    env[ENV_MODULE] = module_path
    env[ENV_OUT] = out_dir
    env.pop(ENV_PARENT, None)
    if tracer:
        env[ENV_TRACER] = tracer
    else:
        env.pop(ENV_TRACER, None)
    return env


def _read_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def untraced_children(dumps):
    """How many module children the traced processes started that never wrote
    their lines: for each process that wrote, the children it started on the
    module's path, less the module processes that wrote naming it as parent."""
    written = {}
    for token, data in dumps.items():
        if data.get("module") and data.get("parent"):
            written[data["parent"]] = written.get(data["parent"], 0) + 1
    return sum(max(0, int(data.get("spawned") or 0) - written.get(token, 0))
               for token, data in dumps.items())


def read_traces(out_dir):
    """What the hook wrote into `out_dir`: `{"lines", "tracers", "started",
    "written", "silent", "untraced", "unreadable"}`. `started` counts processes
    that installed the hook, `written` those that also wrote their lines, and
    `silent` the difference - a process that ended without its exit handlers.
    `untraced` is `untraced_children()` over what was written."""
    starts, dumps, unreadable = set(), {}, []
    for name in sorted(os.listdir(out_dir)):
        token, ext = os.path.splitext(name)
        if ext == ".start":
            starts.add(token)
            continue
        if ext != ".json":
            continue
        try:
            data = _read_json(os.path.join(out_dir, name))
            data["lines"] = set(int(n) for n in data["lines"])
            data["tracer"] = "%s" % (data["tracer"],)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            unreadable.append("%s: %s" % (name, exc))
            continue
        dumps[token] = data
    lines = set()
    for data in dumps.values():
        lines.update(data["lines"])
    return {"lines": lines, "tracers": sorted(set(d["tracer"] for d in dumps.values())),
            "started": len(starts | set(dumps)), "written": len(dumps),
            "silent": len(starts - set(dumps)), "untraced": untraced_children(dumps),
            "unreadable": unreadable}


def _run_block(sweep, side, label, suite, timeout, pycache):
    """One job: one block of `side`'s suite (or the whole file), graded the way
    the sweep grades it."""
    extra = ["--stage", label] if label else []
    row = sweep.run_one(suite, repo=side["export"], timeout=timeout,
                        pycache=pycache, environ=side["env"], extra=extra)
    graded = sweep.grade(suite, row["code"], row["output"], row.get("debris", ()))
    return {"side": side["name"], "label": label or "(whole file)",
            "ok": graded["ok"], "why": graded["why"],
            "output": row["output"], "seconds": row.get("seconds", 0.0)}


# --- the comparison -----------------------------------------------------------
def _repo_relative(repo, path):
    """`path` as the repository names it, `/`-separated; an absolute path under
    `repo` loses that prefix, anything else is taken as already relative."""
    root = os.path.abspath(repo).rstrip(os.sep) + os.sep
    if os.path.isabs(path) and os.path.abspath(path).startswith(root):
        path = os.path.abspath(path)[len(root):]
    return path.replace(os.sep, "/").lstrip("/")


def _prepare(repo, name, rev, module, suite, scratch, tracer, sweep):
    """One side of the comparison, exported and ready to run; or a refusal."""
    sha = resolve_rev(repo, rev)
    if sha is None:
        return None, "%s revision %r: git cannot resolve it in %s" % (
            name, rev, repo)
    export = os.path.join(scratch, name + "-tree")
    os.makedirs(export)
    why = export_rev(repo, sha, export)
    if why:
        return None, "%s revision %s: %s" % (name, rev, why)
    sources = {}
    for role, rel in (("module", module), ("suite", suite)):
        path = os.path.join(export, *rel.split("/"))
        if not os.path.isfile(path):
            return None, "%s revision %s holds no %s at %s" % (name, rev, role, rel)
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            sources[role] = fh.read()
    try:
        ast.parse(sources["module"])
    except (SyntaxError, ValueError) as exc:
        return None, "%s revision %s: the module does not parse: %s" % (
            name, rev, exc)
    out_dir = os.path.join(scratch, name + "-traces")
    os.makedirs(out_dir)
    labels, whole = suite_blocks(sweep, sources["suite"])
    module_path = os.path.join(export, *module.split("/"))
    return {"name": name, "rev": rev, "sha": sha, "export": export,
            "out": out_dir, "labels": labels, "whole": whole,
            "module_source": sources["module"],
            "env": traced_env(os.path.join(scratch, "hook"), module_path, out_dir,
                              tracer)}, None


def _measure(sweep, sides, suite, jobs, timeout, scratch):
    """Every block of every side, run in one pool; the rows in submission order."""
    pycache = os.path.join(scratch, "pycache")
    os.makedirs(pycache)
    work = [(side, label) for side in sides for label in side["labels"]]
    with futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        pending = [pool.submit(_run_block, sweep, side, label, suite, timeout,
                               pycache) for side, label in work]
        return [job.result() for job in pending]


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
            tracer=None, out=None):
    """Run the comparison and print it to `out`; the result dict, whose `code`
    is the exit code: 0 no line lost, 1 a line lost, 2 no comparison made."""
    out = out if out is not None else sys.stdout
    began = time.monotonic()
    module, suite = _repo_relative(repo, module), _repo_relative(repo, suite)
    result = {"code": 2, "gaps": [], "gone": [], "reached": {}, "tracers": [],
              "processes": {}, "blocks": {}, "untraced": {}, "hook": None}
    sweep = _sweep()
    jobs = jobs if jobs is not None else sweep.default_jobs()
    timeout = timeout if timeout is not None else (
        TIMEOUT_FACTOR * sweep.DEFAULT_TIMEOUT)
    entry, why = hook_entry(sweep.ambient_env(os.environ))
    if entry is None:
        out.write("reach-diff: no comparison made - %s\n" % (why,))
        return result
    result["hook"] = entry
    scratch = tempfile.mkdtemp(prefix="reach-")
    try:
        os.makedirs(os.path.join(scratch, "hook"))
        write_hook(os.path.join(scratch, "hook"), entry)
        sides = []
        for name, rev in (("base", base), ("head", head)):
            side, why = _prepare(repo, name, rev, module, suite, scratch, tracer,
                                 sweep)
            if side is None:
                out.write("reach-diff: no comparison made - %s\n" % (why,))
                return result
            sides.append(side)
        out.write("reach-diff: %s under %s\n" % (module, suite))
        out.write("  hook: %s\n" % (hook_line(entry),))
        rows = _measure(sweep, sides, suite, jobs, timeout, scratch)
        return _judge(sides, rows, result, out, began, jobs)
    finally:
        from _suite import remove_tree
        remove_tree(scratch)


def _judge(sides, rows, result, out, began, jobs):
    """The verdict over the measured `rows`, printed and returned."""
    failed = [r for r in rows if not r["ok"]]
    traces = dict((side["name"], read_traces(side["out"])) for side in sides)
    for side in sides:
        trace = traces[side["name"]]
        mine = [r for r in rows if r["side"] == side["name"]]
        result["reached"][side["name"]] = sorted(trace["lines"])
        result["processes"][side["name"]] = trace["written"]
        result["untraced"][side["name"]] = trace["untraced"]
        result["blocks"][side["name"]] = len(mine)
        out.write("  %s %s (%s): %d lines of the module reached; %d blocks run%s; "
                  "%d processes started the hook and %d wrote their lines (%s); "
                  "%d module children untraced\n" % (
                      side["name"], side["rev"], side["sha"][:12],
                      len(trace["lines"]), len(mine),
                      " - %s" % (side["whole"],) if side["whole"] else "",
                      trace["started"], trace["written"],
                      ", ".join(trace["tracers"]) or "none", trace["untraced"]))
        for bad in trace["unreadable"]:
            out.write("    a trace file could not be read: %s\n" % (bad,))
    result["tracers"] = sorted(set(t for tr in traces.values()
                                   for t in tr["tracers"]))
    seconds = time.monotonic() - began
    if failed:
        out.write("reach-diff: no comparison made - %d of %d blocks did not pass, "
                  "and a reach measured over a suite that did not finish is not "
                  "its reach:\n" % (len(failed), len(rows)))
        for row in failed:
            out.write("  %s block %s: %s\n" % (row["side"], row["label"],
                                               row["why"]))
            for line in _tail(row["output"], 12):
                out.write("      %s\n" % (line,))
        out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
        return result
    blind = [side for side in sides if traces[side["name"]]["untraced"]
             or traces[side["name"]]["unreadable"]]
    if blind:
        for side in blind:
            trace = traces[side["name"]]
            out.write("reach-diff: no comparison made - at %s (%s) %d module "
                      "children were started and never wrote what they reached, "
                      "and %d trace files could not be read: a child started on "
                      "the module's path with an environment that drops the hook, "
                      "or one that ended without its exit handlers (os._exit, a "
                      "kill, a timeout), ran lines no count holds\n" % (
                          side["name"], side["rev"], trace["untraced"],
                          len(trace["unreadable"])))
        out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
        return result
    for side in sides:
        if not traces[side["name"]]["lines"]:
            out.write("reach-diff: no comparison made - no line of the module was "
                      "reached at %s (%s): the suite does not run it there, or no "
                      "process it started ran the tracer\n" % (
                          side["name"], side["rev"]))
            out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
            return result
    base, head = sides
    found = reach_gaps(base["module_source"], traces["base"]["lines"],
                       head["module_source"], traces["head"]["lines"])
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
    out.write("took %.1fs with %d jobs\n" % (seconds, jobs))
    return result


# --- the command line ---------------------------------------------------------
_VALUE_FLAGS = ("--base", "--head", "--repo", "--jobs", "--timeout", "--tracer")


def parse_args(argv):
    """`(options, None)`, or `(None, why)` for a usage error."""
    opts, positional, i = {}, [], 0
    while i < len(argv):
        arg = argv[i]
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
        out.write("reach-diff: %s\n%s" % (why, USAGE))
        return 2
    repo = os.path.abspath(opts.get("repo") or REPO)
    return compare(repo, opts["module"], opts["suite"], opts["base"],
                   opts["head"], jobs=opts.get("jobs"),
                   timeout=opts.get("timeout"), tracer=opts.get("tracer"),
                   out=out)["code"]


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
    out = subprocess.run([sys.executable, MODULE] + %(child_args)s,
                         stdout=subprocess.PIPE, universal_newlines=True).stdout
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
    "    sys.stdout.flush()\n    if sys.argv[1:] == [\"exit-hard\"]:\n"
    "        os._exit(0)\n"))

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
    ("extracted", MODULE_EXTRACTED, _staged_suite(ALL_ROWS[1:])),
    ("dup-base", MODULE_BASE + GRADE_V1, _staged_suite(GRADE_ROWS,
                                                       grades=(1, 2, 3))),
    ("dup-insert", MODULE_BASE + GRADE_V2, _staged_suite(GRADE_ROWS,
                                                         grades=(0, 1, 3))),
    ("route", MODULE_BASE, _staged_suite(ALL_ROWS + (("route", "_route_cases"),))),
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
         tracer=None):
    """`(exit code, the result dict, printed text)` for one comparison."""
    out = io.StringIO()
    result = compare(repo, module, suite, base, head, tracer=tracer, out=out)
    return result["code"], result, out.getvalue()


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


def _compare_cases(check, repo):
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
          code == 2 and "other" in text and "FAIL" in text)

    code, res, text = _run(repo, "crash")
    # The block is named as not passing, not only refused: a crashed suite also
    # reaches no line, and the empty-reach refusal alone would exit 2 here too.
    check("rd6 a suite that fails to run at all exits 2, not 0, and says its "
          "blocks did not pass: %d\n%s" % (code, text),
          code == 2 and "did not pass" in text and "exited 3" in text)

    code, res, text = _run(repo, "untouched")
    check("rd7 a revision at which no line of the module was reached is a run "
          "that measured nothing, and refuses with 2 rather than reporting "
          "every line as lost or none: %d\n%s" % (code, text),
          code == 2 and "no line" in text)

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
          and "untraced" in text)

    code, res, text = _run(repo, "hard-exit")
    check("rd22 a module child that ran the hook and ended without its exit "
          "handlers wrote nothing it reached: it is counted as untraced too, "
          "exit 2: %r\n%s" % (res.get("untraced"), text),
          code == 2 and res.get("untraced") == {"base": 0, "head": 1})

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


def _usage_cases(check, repo):
    def quiet(argv):
        out = io.StringIO()
        return main(argv, out=out), out.getvalue()
    code, text = quiet([])
    check("rd12 no arguments is a usage error, 2: %d" % (code,), code == 2)
    code, text = quiet([FIX_MODULE, FIX_SUITE, "--base", "base", "--head",
                        "no-such-rev", "--repo", repo])
    check("rd13 a revision git cannot resolve is a usage error naming it: "
          "%d %r" % (code, text), code == 2 and "no-such-rev" in text)
    code, text = quiet(["missing" + _PY, FIX_SUITE, "--base", "base",
                        "--head", "moved", "--repo", repo])
    check("rd14 a module the revision does not hold refuses with 2: %d %r"
          % (code, text), code == 2 and "missing" in text)


def _cases(check):
    _key_cases(check)
    root = tempfile.mkdtemp(prefix="rd-")
    try:
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        _fixture_repo(repo)
        status = _fixture_git(repo, "status", "--porcelain", "--ignored")
        _compare_cases(check, repo)
        _usage_cases(check, repo)
        after = _fixture_git(repo, "status", "--porcelain", "--ignored")
        check("rd15 the repository compared is never written: its status, "
              "ignored files included, is the same after every comparison "
              "above: %r -> %r" % (status, after), status == after == "")
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
