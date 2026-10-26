#!/usr/bin/env python3
"""
Which checks a change actually needs — and, when it cannot tell, all of them.

    tools/affected.py                 # what the working tree changed
    tools/affected.py --base HEAD~3   # ...against another commit
    tools/affected.py <path> <path>   # ...or an explicit list
    tools/affected.py --json          # machine-readable, for verify.sh
    tools/affected.py --list-related <path> <path>   # one suite path per
                                       # line, nothing executed -- the shape
                                       # meta.phaseGate.derived.listing.related
                                       # records, {paths} filled in
    tools/affected.py --list-all      # every suite file, one per line,
                                       # nothing executed -- .listing.all

HOW OFTEN THIS SELECTION IS WRONG is not decided here: `tools/measure-affected-miss.py` plants
a fault in the files of recent commits and counts the red suites this file did not select.

WHY THE BROWSER GATES ARE THE POINT. The whole Python selftest sweep now runs in
parallel and the panel browser gate is by far the longest leg, so narrowing the
Python side saves seconds and narrowing the BROWSER side saves minutes. Re-derive
both rather than trusting a figure written here:

    python3 tools/sweep-selftests.py
    node tools/capture-screenshots.mjs --check --only panel

A change that touches only the report's parts does not need the panel driven at
all, and that single decision is most of what this is for.

WHEN IN DOUBT, EVERYTHING. A selector that under-selects is worse than no
selector: it turns "I ran the tests" into a sentence that is no longer true, and
the failure surfaces in CI wearing somebody else's commit. So every rule here is
written to widen rather than narrow, an unrecognised path selects the full set, and
the reason is always printed next to the selection.

THE CROSS-FILE TRAP. Suites here lint OTHER files' source - `_output_lints` reads
every file's AST for house style, `_deps` walks the import graph, `_refs` checks
paths and version pins. Editing one file can turn those red without touching them,
so any `.py` change selects every suite and tool that calls one of the shared tree
walks (`reach_graph()` reads which do). That is not caution, it is a measured fact:
this repo has gone red exactly that way.

WHAT A SUITE REACHES is read the same way, off the code rather than a list: what it
imports, what it loads or resolves through `_loader` or the hooks' resolver, what a
suite or a tool names inside a call (the subprocess it starts, the source it reads),
and onward through each of those, however many files away. What that reading cannot
see: a target computed at runtime in the product's own code, and a file loaded
through `importlib` by a computed path - neither shows up here, and the miss
measurement is what finds them.
"""
import ast
import contextlib
import io
import json
import os
import subprocess
import sys

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
        _anchor_dir = None
        break
    _anchor_dir = _anchor_up
if _anchor_dir is None:
    # tools/ is outside scripts/, so find the anchor by the known layout instead.
    _anchor_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "plugins", "audit", "scripts")
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402

_output.install_path()
# `_deps` and `_refs` live outside the plugin, and `install_path()` never adds them.
if _output.LINTS_DIR not in sys.path:
    sys.path.insert(0, _output.LINTS_DIR)

import _deps  # noqa: E402  (the loader's module and call names the graph reads)
import _output_lints  # noqa: E402  (which development modules have their cases in tests/)
import _refs  # noqa: E402  (the surfaces and sweep documents it reads)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = "tests"
LINTS = "tools/lints/"

PANEL_GATE = "node tools/capture-screenshots.mjs --check --only panel"
REPORT_GATE = "node tools/check-report-interactive.mjs %s"
# The committed reports verify.sh's report slice drives. docs/index.html is not one:
# it is a byte copy of the acme report, which the manifests slice proves by `cmp`.
REPORT_DOCS = ("examples/acme-store/acme-store-audit.html", "docs/demo-large.html")
# `--before-commit` because a narrowed run happens before the commit: the tool's
# other arm asks what HEAD carries, and that is red for every change that re-renders
# a page until the change is committed. verify.sh's release slice asks it.
ARTIFACTS = "python3 tools/check-rendered-artifacts.py --before-commit"

# The JavaScript unit tests under `tools/ui-tests/`. They were selectable by nothing
# and runnable only in CI, so a change to a `scripts/ui/` part reached a push with
# none of the suites covering it having run - the same forgotten-step class
# `verify.sh` exists to close, one directory over. Cheap enough that widening to it
# is never the expensive decision.
VITEST = "npx vitest run"

# The meta-gate. The workflow runs slices of the runner, and `gate-parity.py` holds
# the workflow to the runner's `--list` - so editing either is what makes them
# disagree. The documents that describe the sweep select it too (the sweep-document
# branch), which is a widening this file is allowed.
PARITY = "python3 tools/gate-parity.py"

# The workflow, and the tools whose OWN cases read it: the slice rule (gate-parity),
# the sweep's deadline against the selftests job's bound (tt5), the rendered-artifact
# tool's pin that the workflow carries no call of its own (ra29), and the release
# dispatch's tier input (rt2). Listed because each reads it by path, which no import
# graph shows; a reader added later and missed here under-selects, so a new one
# belongs on this list in the same change.
WORKFLOW = ".github/workflows/ci.yml"
WORKFLOW_READERS = ("tools/gate-parity.py", "tools/sweep-selftests.py",
                    "tools/check-rendered-artifacts.py", "tools/release.py")

# A tool's OWN cases. Every `.py` under `tools/` carries an inline suite, and until
# this existed nothing here selected one: a change to a tool was classified "a tool
# no suite covers" and the narrowed run skipped exactly the cases that change owed.
# The classification was the worse half - it reads as a fact about the file when it
# was a fact about this selector, which is the one thing a reader must never be told
# wrong by a tool whose whole subject is what a narrowed run leaves out.
#
# DERIVED, not a list. `sweep-selftests.py` walks `tools/` and demands the
# `N/M cases passed` contract from every file except the development modules whose
# cases live in `tests/`, so a `.py` outside that set HAS a suite by construction - and
# the set is read off the same function the sweep asks rather than name-transformed
# here. The path is substituted whole: a format string spelling a module basename is
# what `_refs.tool_basename_drift()` reads as a reference to a file that does not exist.
TOOL_SELFTEST = "python3 %s --selftest"
MIGRATED = frozenset(_output_lints.suite_elsewhere_paths(REPO))

# The documents `_refs.sweep_glob_drift()` pins, READ OFF `_refs` rather than listed
# again here. Two of them start with a dot and were unreachable by every rule below;
# a third copy of the list is also how the two would come to disagree.
SWEEP_DOCS = frozenset(d.replace(os.sep, "/") for d in _refs.SWEEP_DOCS)

# ...and `_refs.raw_url_pin_drift()` reads every document of the formats it holds a
# runnable-region rule for, anywhere the repo keeps files, not only the listed ones.
# So the selector owes the refs pins for any of them, which is a WIDENING - the
# direction this file is allowed to be wrong in. Read off the same constant the scan
# derives its own extension set from, so the two cannot disagree about what a
# document is.
FETCH_DOC_EXT = tuple(_refs._FETCH_DOC_EXT)

# ...and the pages `_refs.artifact_version_drift()` reads, derived the same way. A
# committed report carries the plugin version that rendered it, and that rule is the
# only thing comparing the stamp with `plugin.json` - so a narrowed run that edited a
# published page and skipped this suite would be the under-selection this whole file
# exists to prevent. The other direction is already covered: a `plugin.json` change
# selects the full set.
STAMP_EXT = tuple(_refs.STAMP_EXT)


def refs_reads(posix):
    """True when `_refs` scans this path, so `test__refs.py` can go red for it.

    Derived from `_refs.SURFACES`, `_refs.SWEEP_DOCS`, `_refs._FETCH_DOC_EXT` and
    `_refs.STAMP_EXT` for the
    same reason `reach_graph()` is derived from the real tree: a hand-kept
    copy of somebody else's list is a copy that stops agreeing. Editing
    `CONTRIBUTING.md` selected `test__deps.py` and not this - and `CONTRIBUTING.md` is a
    `_refs` surface, so a path rotting in it went unchecked by the narrowed run.

    The extension arm needs no ignored-directory test to go with it: the paths this
    file judges come from git, and git never hands over a file the repo ignores. The
    scan's own prune list exists for a WALK, which sees files git does not.
    """
    if posix in SWEEP_DOCS or posix.endswith(FETCH_DOC_EXT + STAMP_EXT):
        return True
    for surface, _mode in _refs.SURFACES:
        rel = surface.replace(os.sep, "/")
        if posix == rel or posix.startswith(rel + "/"):
            return True
    return False


def _repo_relative(path):
    """One repo-relative POSIX spelling of `path`.

    `lstrip("./")` was here, and `lstrip` strips CHARACTERS, not a prefix: it turned
    `.github/workflows/ci.yml` into `github/...` and
    `.claude/skills/.../SKILL.md` into `claude/...`, so every rule below missed and
    both fell through to "UNRECOGNISED, select everything". Safe, because that
    branch widens - and silent, because a widened run looks like a careful one.
    """
    posix = path.replace(os.sep, "/")
    if posix.startswith("./"):
        posix = posix[2:]
    return posix


def changed_files(base, explicit):
    """The paths this run is about, as repo-relative POSIX strings."""
    if explicit:
        return sorted(set(_repo_relative(p) for p in explicit))
    out = set()
    for args in (["diff", "--name-only", base],
                 ["diff", "--name-only", "--cached", base],
                 ["ls-files", "--others", "--exclude-standard"]):
        try:
            proc = subprocess.run(["git"] + args, cwd=REPO, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        for line in proc.stdout.decode("utf-8", "replace").splitlines():
            if line.strip():
                out.add(line.strip())
    return sorted(out)


# --- the reach graph ------------------------------------------------------------
# WHICH SUITE GOES RED WHEN A FILE BREAKS is a question about what each suite RUNS,
# and the import graph `_deps` keeps answers a narrower one: what the SHIPPED tree
# imports, for the layer rule. Read alone it missed every suite that reaches a module
# through something else - a suite loading an entry script, that script running a
# second one by path, a suite importing another suite's fixtures - and the measured
# misses were exactly those. So the graph below is read off every `.py` the sweep can
# run or load - imports read as `_deps` reads them, loads through the loader names
# `_deps` keeps - and widened by the ways this repo runs a file it does not import.
#
# The directories a red-turning `.py` can sit in. `.claude/hooks/` is not one: a path
# there matches no branch of `select()` and widens to the full set.
REACH_DIRS = (_output.SCRIPTS_DIR, _output.HOOKS_DIR, _output.TESTS_DIR,
              os.path.join(REPO, "tools"))

# The calls that run or load a file named in their arguments, by the module that
# holds them - read through that module, never by a bare name, because `json.load`
# is a `load` too. `_deps` reads only the loading pair, and leaves `script_path` out
# ON PURPOSE: for the layer rule a path handed to a subprocess is no dependency. For
# this question it is the whole of one - the subprocess is what turns the suite red -
# so the resolver joins them, and so does the hooks' resolver
# (`hooks/_config.find_script`), which is how a hook reaches a script.
RESOLVERS = {_deps._LOADER_MODULE: tuple(_deps._LOADER_FUNCS) + ("script_path",),
             "_config": ("find_script",)}

# Where the shared tree walks live: `_output.py` holds the walk the sweep and the
# lints share, and the lint modules hold every walk built on it. A function here
# that reaches `os.walk` - directly or through another function here - walks the
# tree, and a suite calling one is a tree scanner.
WALK_HOMES = (os.path.join(_output.SCRIPTS_DIR, "_output.py"),)
OS_WALK = "os.walk"


def _rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def _stem(rel):
    return os.path.basename(rel)[:-3]


def _is_suite(rel):
    """A file the sweep runs as a suite under `tests/` - never a helper beside one."""
    return rel.startswith(TESTS + "/") and os.path.basename(rel).startswith("test")


def _is_dev(rel):
    """Development code: a suite, a suite helper, a tool. Its `.py` literals inside a
    call are what it runs; the product's are mostly text - a brief naming the next
    command, a table of areas - and reading them as runs made every suite reach every
    other one through a sentence."""
    return rel.startswith(TESTS + "/") or rel.startswith("tools/")


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _py_constants(tree):
    """Module-level `NAME = "....py"` bindings - `DRIVER = "drive-phase.py"` and
    `load_script(DRIVER)` are one target spelled in two places."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) \
                and node.value.value.endswith(".py"):
            out[node.targets[0].id] = _stem(node.value.value)
    return out


def _scan(tree, consts):
    """Everything the graph reads from one file, in ONE walk of its tree.

    `imports` holds the first component of every absolute import, read the way
    `_deps._imported_sibling_names()` reads one; `in_call` every module stem a `.py`
    literal or bound constant names inside a call; `calls` one row per call that
    names a target or could resolve one - `(name, qualifier, targets, forwards,
    has_args, function)`, where `forwards` says the call passes on a parameter of the
    function it sits in; `fn_calls` the call names inside each function; `aliases`
    and `from_names` how its imports are bound.

    One walk because the graph parses every `.py` the sweep can reach on every
    selection, and the first version, walking each tree once per question, spent
    more on the walks than on the parse."""
    found = {"imports": set(), "in_call": set(), "calls": [], "fn_calls": {},
             "aliases": {}, "from_names": {}}
    frames, open_calls = [], []
    stack = [(tree, True)]
    while stack:
        node, entering = stack.pop()
        if not entering:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                frames.pop()
            elif isinstance(node, ast.Call):
                row = open_calls.pop()
                if row[0] is not None:
                    found["calls"].append(tuple(row))
            continue
        stack.append((node, False))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = set(a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg))
            frames.append((node.name, params))
            found["fn_calls"].setdefault(node.name, set())
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            func = node.func
            qualifier = (func.value.id if isinstance(func, ast.Attribute)
                         and isinstance(func.value, ast.Name) else None)
            if frames:
                # `os.walk` kept apart from every other `walk`: the lint modules
                # call `ast.walk` everywhere, and it walks a tree of nodes.
                found["fn_calls"][frames[-1][0]].add(
                    OS_WALK if (qualifier, name) == ("os", "walk") else name)
            open_calls.append([name, qualifier, set(), False, bool(node.args),
                               frames[-1][0] if frames else None])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.endswith(".py") and open_calls:
            stem = _stem(node.value)
            found["in_call"].add(stem)
            for row in open_calls:
                row[2].add(stem)
        elif isinstance(node, ast.Name) and open_calls:
            if node.id in consts:
                found["in_call"].add(consts[node.id])
                for row in open_calls:
                    row[2].add(consts[node.id])
            if frames and node.id in frames[-1][1]:
                for row in open_calls:
                    row[3] = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                found["imports"].add(base)
                found["aliases"][alias.asname or base] = base
        elif isinstance(node, ast.ImportFrom) and not node.level:
            base = (node.module or "").split(".")[0]
            found["imports"].add(base)
            for alias in node.names:
                found["from_names"][alias.asname or alias.name] = (base, alias.name)
        stack.extend((child, True) for child in ast.iter_child_nodes(node))
    return found


def _walk_names(scans, homes):
    """Function names in `homes` that reach `os.walk`, grown to a fixpoint - a walk
    built on a walk is a walk."""
    defs = [(fn, calls) for rel in homes for fn, calls in scans[rel]["fn_calls"].items()]
    names = set((OS_WALK,))
    grew = True
    while grew:
        grew = False
        for fn, calls in defs:
            if fn not in names and calls & names:
                names.add(fn)
                grew = True
    names.discard(OS_WALK)
    return names


def _scans_tree(scan, walks, home_stems):
    """True when this file calls a shared walk through the module that holds it -
    `_output.py_files(...)`, `L.kept_files(...)`, or a walk imported by name. Read
    through the module, never by a bare name alone: a suite's own `render` is not
    the lint module's."""
    via = set(local for local, mod in scan["aliases"].items() if mod in home_stems)
    bare = set(local for local, (mod, name) in scan["from_names"].items()
               if mod in home_stems and name in walks)
    for name, qualifier, _t, _f, _a, _fn in scan["calls"]:
        if (qualifier in via and name in walks) or (qualifier is None and name in bare):
            return True
    return False


def _is_resolver(scan, name, qualifier):
    """True for a call that reaches a `RESOLVERS` function through its module - an
    `import _loader [as X]` alias, or the name imported from it."""
    if qualifier is not None:
        return name in RESOLVERS.get(scan["aliases"].get(qualifier), ())
    mod, original = scan["from_names"].get(name, (None, None))
    return original in RESOLVERS.get(mod, ())


def _file_edges(rel, scan, known, wrappers):
    """`(imports, runs, unknown)` for one file.

    `imports` is what it imports by bare name; `runs` what it loads, resolves or -
    for development code - names inside a call; `unknown` is True when a resolver
    call's target is computed at runtime (a name read out of a document, say), which
    this graph cannot follow and so reads as every module under `scripts/`."""
    stem = _stem(rel)
    runs = set(scan["in_call"]) if _is_dev(rel) else set()
    unknown = False
    for name, qualifier, targets, forwards, has_args, _fn in scan["calls"]:
        resolver = _is_resolver(scan, name, qualifier)
        if not resolver and name not in wrappers:
            continue
        runs |= targets
        if resolver and not targets and has_args and not forwards:
            unknown = True
    self_only = set((stem,))
    return (scan["imports"] & known) - self_only, (runs & known) - self_only, unknown


def reach_graph():
    """The graph `select()` reads: who imports and who runs each module, every
    suite and tool that scans the tree, and the files nothing could parse.

    Built once per selection and handed in, never cached in the module: a cache here
    is a second copy of the tree that stops agreeing with it."""
    files = []
    for directory in REACH_DIRS:
        files.extend(_rel(path) for _r, path in _output.lint_py_files(directory))
    scans, broken = {}, []
    for rel in sorted(set(files)):
        try:
            with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, SyntaxError, ValueError):
            broken.append(rel)
            continue
        scans[rel] = _scan(tree, _py_constants(tree))
    known = set(_stem(rel) for rel in files)
    scripts = set(_stem(rel) for rel in files
                  if rel.startswith(_rel(_output.SCRIPTS_DIR) + "/"))
    wrappers = set(fn for scan in scans.values()
                   for name, qualifier, _t, forwards, _a, fn in scan["calls"]
                   if forwards and fn and _is_resolver(scan, name, qualifier))
    imported_by, run_by = {}, {}
    for rel, scan in scans.items():
        imports, runs, unknown = _file_edges(rel, scan, known, wrappers)
        if unknown:
            runs = runs | (scripts - set((_stem(rel),)))
        for stem in imports:
            imported_by.setdefault(stem, set()).add(rel)
        for stem in runs:
            run_by.setdefault(stem, set()).add(rel)
    homes = [rel for rel in scans
             if rel.startswith(LINTS) or rel in set(_rel(p) for p in WALK_HOMES)]
    walks = _walk_names(scans, homes)
    home_stems = set(_stem(rel) for rel in homes)
    scanners = sorted(rel for rel, scan in scans.items()
                      if _is_runner(rel) and _scans_tree(scan, walks, home_stems))
    return {"imported_by": imported_by, "run_by": run_by, "scanners": scanners,
            "broken": sorted(broken)}


def _is_runner(rel):
    """A file whose own cases the sweep runs: a suite, or a tool carrying them."""
    return _is_suite(rel) or (rel.startswith("tools/") and rel not in MIGRATED)


def reached_by(graph, rel):
    """Every file that imports or runs `rel`, transitively.

    A suite is where a red STOPS: a file naming a suite's path does not run its cases.
    The one way past one is an import - a suite borrowing another suite's fixture
    goes red with it - so from a suite only the importers are followed."""
    seen = set()
    stack = [rel]
    while stack:
        cur = stack.pop()
        stem = _stem(cur)
        up = set(graph["imported_by"].get(stem, ()))
        if not _is_suite(cur):
            up |= graph["run_by"].get(stem, set())
        for nxt in up - seen:
            seen.add(nxt)
            stack.append(nxt)
    seen.discard(rel)
    return seen


def _suite_for(module_basename):
    """The test file that holds this module's cases, if it exists."""
    # Assembled from a prefix and the basename rather than written as one format
    # string. `_refs` scans tools/ for anything shaped like a module filename and
    # checks it exists, and a percent-substitution reads to it as a real file that
    # is missing. Writing the trap into the comment tripped it a second time, so
    # the explanation avoids the shape too.
    for prefix in ("test_", "test"):
        candidate = prefix + module_basename + ".py"
        if os.path.isfile(os.path.join(REPO, TESTS, candidate)):
            return candidate
    return None


def _reached_selection(graph, rel):
    """`(suites, tool gates)` that `rel` can turn red: its own suite, and every suite
    and tool whose cases import or run it, however many files away."""
    suites, gates = set(), []
    reached = reached_by(graph, rel) | set((rel,))
    own = _suite_for(_stem(rel))
    if own:
        suites.add(own)
    for other in sorted(reached):
        if _is_suite(other):
            suites.add(other[len(TESTS) + 1:])
        elif _is_runner(other):
            gates.append(TOOL_SELFTEST % (other,))
    return suites, gates


# --- the selection rules ------------------------------------------------------
def _suite_path(name):
    """A suite's repo-relative POSIX path -- what a listing mode prints,
    rather than the bare basename `select()` works in internally."""
    return TESTS.replace(os.sep, "/") + "/" + name


def _all_suite_paths():
    """Every suite file the runner would collect under `tests`,
    one per line and never executed -- the FULL listing
    `meta.phaseGate.derived.listing.all` records. Read off `_output.py_files`
    (the same recursive walk `sweep-selftests.py` trusts) rather than a
    second, hand-kept glob, and narrowed to `test*` so a helper module
    (`_harness.py`, `_suite.py`) is never printed as a suite."""
    names = sorted(relname for relname, _path in
                   _output.py_files(os.path.join(REPO, TESTS))
                   if os.path.basename(relname).startswith("test"))
    return [_suite_path(name) for name in names]


def _related_suite_paths(paths):
    """The suite paths `--list-related` prints for `paths` -- the SAME
    selection `select()` already derives (importers' suites, every
    tree-scanning suite once any `.py` changed), widened to the full listing
    the moment `select()` cannot narrow (an unrecognised path, or any other
    `full` trigger). One path per line, never executed -- the contract
    `meta.phaseGate.derived.listing.related` holds."""
    suites, _gates, _reasons, full = select(paths)
    if full:
        return _all_suite_paths()
    return sorted(_suite_path(s) for s in suites)


def _once(gates):
    """`gates` with repeats removed, first occurrence kept.

    ORDER-PRESERVING AND APPLIED ONCE AT THE END, rather than a membership test at
    each append. The parity check is reachable from several branches - a sweep
    document, the runner, the comparison itself - so a change touching two of them
    named it twice and `verify.sh` ran it twice, which is a narrowed run paying more
    than it saved. Order is kept because the runner reads this list as its steps and
    a reordered list is a diff nobody asked for.
    """
    seen = set()
    out = []
    for gate in gates:
        if gate not in seen:
            seen.add(gate)
            out.append(gate)
    return out


def select(paths, graph=None):
    """What to run, and why. Returns (suites, gates, reasons, full).

    `graph` is `reach_graph()`'s answer, for a caller asking many questions of one
    tree; absent, it is built here when a `.py` is among the paths."""
    suites = set()
    gates = []
    reasons = []
    full = False
    touched_py = False
    panel = report = artifacts = vitest = False
    if graph is None and any(_repo_relative(p).endswith(".py") for p in paths):
        graph = reach_graph()

    def reach(posix):
        found, tool_gates = _reached_selection(graph, posix)
        suites.update(found)
        gates.extend(tool_gates)

    for path in paths:
        posix = _repo_relative(path)
        if refs_reads(posix):
            # Applied to EVERY path rather than added inside four branches by hand,
            # which is how three of them came to disagree about it.
            suites.add("test__refs.py")
        # THE PROSE SCANS, and they are applied to every path for the same reason.
        # Their sets are derived now - every `.py` this repo keeps for
        # `prose_number_claims()`, every `.md` for `doc_prose_numbers()` - so the
        # extension decides which suite reads the file, and NOTHING about which
        # directory it sits in does. Written as a branch on the directory (the
        # root-prose rule below used to be the whole of it), this file would
        # under-select for exactly the files the widening was for: a count added to
        # a `commands/*.md` or to a `tests/` docstring selected neither suite.
        #
        # THE `.py` HALF IS THE TREE SCANNERS, added once after the loop. It named one
        # suite here by hand, and the scan had moved to another module with its own
        # suite, so a style fault in any `.py` turned a suite red that no narrowed run
        # selected. The scanners are now read off the shared walks (`reach_graph()`).
        if posix.endswith(".py"):
            touched_py = True
        if posix.endswith(".md"):
            suites.add("test__deps.py")
        if posix == WORKFLOW:
            # THE WORKFLOW IS NO SWEEP DOCUMENT any more - every job is one verify.sh
            # call - but it is what the slice rule holds against `verify.sh --list`,
            # and the tools whose own cases read it go red when it moves.
            gates.append(PARITY)
            gates.extend(TOOL_SELFTEST % (rel,) for rel in WORKFLOW_READERS)
            reasons.append("%s - the workflow, so the slice rule and the cases "
                           "that read it are re-checked" % (posix,))
            continue
        if posix in SWEEP_DOCS:
            suites.add("test__deps.py")
            # EVERY sweep document, not only the workflow. Some of them are parity
            # SIDES and the workflow was the only one selecting the check, so editing
            # `CONTRIBUTING.md` - a side long before this - narrowed to a run that
            # skipped the comparison while the reason line below said the gate set had
            # been re-checked. The parity sides are a subset of these documents plus
            # `verify.sh`, which the tools/ branch already covers, so selecting on the
            # whole set is a WIDENING - the direction this file is allowed to be wrong
            # in - and it buys not keeping a copy of which documents are sides.
            gates.append(PARITY)
            reasons.append("%s - a sweep document, so the sweep-shape rule and the "
                           "gate set are re-checked" % (posix,))
            continue
        if posix.startswith("docs/screenshots/"):
            reasons.append("%s - a committed PNG, checked by eye and never by a "
                           "gate" % (posix,))
            continue
        if posix.endswith((".md", ".txt")) and "/" not in posix:
            # Root prose. The `.md` half is already selected above, along with
            # every other `.md` in the tree; what this branch still owns is `.txt`
            # and the `continue` that says a root document needs nothing else.
            suites.add("test__deps.py")
            reasons.append("%s - root prose, linted by _deps" % (posix,))
            continue
        if posix.startswith(TESTS.replace(os.sep, "/") + "/"):
            if posix.endswith(".py"):
                # A suite is its own selection; a helper beside the suites (the
                # harness, a shared fixture) is no suite at all, and was named as
                # one here. Either way what imports or runs it goes red with it.
                if _is_suite(posix):
                    suites.add(posix[len(TESTS) + 1:])
                reach(posix)
                reasons.append("%s - its own cases, plus every suite and tool that "
                               "imports or runs it" % (posix,))
            continue
        if posix.startswith("plugins/audit/scripts/ui/"):
            # Assembled surfaces: the part belongs to a page, not to a module.
            # EVERY ui part selects vitest, whichever surface it belongs to: those
            # suites test the shared helpers and the per-surface logic alike, they
            # cost about as much as starting node, and under-selecting here is the
            # failure this whole file is written to avoid.
            vitest = True
            if "/panel" in posix:
                panel = True
                suites.update(("test__panel_page.py", "test__panel_ui.py",
                               "test_panel_server.py"))
                reasons.append("%s - a panel part, so the panel is reassembled"
                               % (posix,))
            if "/report" in posix:
                report = artifacts = True
                suites.update(("test_render_report.py", "test__report_page.py"))
                reasons.append("%s - a report part, so the report is reassembled"
                               % (posix,))
            if "/shared" in posix:
                panel = report = artifacts = True
                suites.update(("test__panel_page.py", "test_render_report.py"))
                reasons.append("%s - shared by BOTH surfaces" % (posix,))
            continue
        if posix.endswith(".py") and posix.startswith("plugins/audit/"):
            touched_py = True
            base = os.path.basename(posix)[:-3]
            reach(posix)
            reasons.append("%s - its suite plus every suite and tool that imports "
                           "or runs it, however many files away" % (posix,))
            if base in ("_ui_theme", "_output"):
                panel = report = artifacts = True
                reasons.append("%s - both surfaces read it" % (posix,))
            if base.startswith("_report") or base.startswith("_usage"):
                report = artifacts = True
            if base.startswith("_panel"):
                panel = True
            continue
        if posix == "plugins/audit/.claude-plugin/plugin.json":
            full = True
            reasons.append("%s - the version is embedded in every rendered "
                           "artifact, so nothing here is unaffected" % (posix,))
            continue
        if posix.startswith("plugins/audit/commands/") or \
                posix.startswith("plugins/audit/skills/") or \
                posix.startswith("plugins/audit/agents/"):
            # The plugin's PRODUCT prose. No browser gate renders it, but `_refs`
            # checks every path it names still exists and `plugin validate` checks
            # its frontmatter, so those two are the whole answer. Left unrecognised
            # this selected the full set - correct but expensive, and these are
            # among the most frequently edited files in the tree.
            suites.update(("test__refs.py", "test__deps.py"))
            gates.append("claude plugin validate plugins/audit")
            reasons.append("%s - plugin prose: path references and frontmatter, "
                           "no rendered surface" % (posix,))
            continue
        if posix.startswith("plugins/audit/README.md"):
            suites.update(("test__refs.py", "test__deps.py"))
            reasons.append("%s - the plugin README, read by _refs and _deps"
                           % (posix,))
            continue
        if posix.startswith(LINTS) and posix.endswith(".py"):
            # A LINT MODULE IS NO TOOL, though it sits under `tools/`: its cases are
            # a suite beside the rest and it is `MIGRATED`, so the tool arm below
            # answered "no rule matches" for the two files that used to take the
            # plugin `.py` arm. Same selection as that arm: its own suite, every
            # suite and tool that imports or runs it, and the tree scanners.
            reach(posix)
            reasons.append("%s - a lint module: its suite plus every suite and tool "
                           "that imports or runs it" % (posix,))
            continue
        if posix.startswith("tools/"):
            # THE TOOL'S OWN CASES FIRST, and outside the chain below rather than as
            # another arm of it: what a tool is a gate FOR and whether it has a suite
            # are two questions, and answering them in one chain is what left the
            # sweep runner - the one file every other suite is run BY - selectable
            # only through an arm written for it by name.
            own = posix.endswith(".py") and posix not in MIGRATED
            if posix in MIGRATED:
                # A DEVELOPMENT MODULE UNDER `tools/` THAT ISN'T A LINT (a demo
                # generator, a benchmark): its cases are a suite in `tests/`, named
                # for it with the hyphens read as underscores, and the sweep never
                # runs the file itself.
                suite = _suite_for(os.path.basename(posix)[:-3].replace("-", "_"))
                if suite:
                    suites.add(suite)
                    reasons.append("%s - a development module: its suite %s"
                                   % (posix, suite))
            if own:
                gates.append(TOOL_SELFTEST % (posix,))
                reasons.append("%s - a tool, so its own cases run" % (posix,))
            if posix.endswith(".py"):
                # ...and every suite and tool that imports or runs it: a tool is a
                # module to whatever loads it, and a suite driving the runner or the
                # selector goes red with them.
                reach(posix)
            if "capture-screenshots" in posix or posix.startswith("tools/ui-checks/"):
                # `ui-checks/` holds the concerns that moved OUT of the panel gate
                # and are imported back into it, so editing one edits the gate. They
                # matched nothing here and fell to the line below, which said no
                # suite covered them while the panel gate ran them on every full run.
                panel = True
                reasons.append("%s - the panel gate, or a part it imports"
                               % (posix,))
            elif "check-report-interactive" in posix:
                report = True
                reasons.append("%s - the report gate itself" % (posix,))
            elif posix.startswith("tools/ui-tests/"):
                vitest = True
                reasons.append("%s - a vitest suite, so vitest runs" % (posix,))
            elif posix.endswith(("verify.sh", "gate-parity.py")):
                # Editing either side of the gate set is exactly the change that
                # breaks parity between them, so the check that compares them runs.
                gates.append(PARITY)
                reasons.append("%s - part of the gate set, so gate parity is "
                               "re-checked" % (posix,))
            elif not own:
                # SAID AS A PROPERTY OF THIS FILE, not of the tool. It read "a tool
                # no suite covers", which is a claim about the tool - and it was
                # false for every `.py` here and for `ui-checks/` besides. What is
                # true is that nothing above matched, and a reader deciding whether
                # to trust a narrowed run needs to be told which of the two they got.
                reasons.append("%s - NO RULE HERE MATCHES IT, so nothing was "
                               "selected for it. That is this selector's gap and "
                               "not a statement that the file is uncovered"
                               % (posix,))
            continue
        if posix.startswith("examples/") or posix.startswith("docs/"):
            artifacts = True
            reasons.append("%s - a rendered artifact" % (posix,))
            continue
        full = True
        reasons.append("%s - UNRECOGNISED, so the full set is selected rather "
                       "than a guess" % (posix,))

    if touched_py:
        for rel in graph["scanners"]:
            if _is_suite(rel):
                suites.add(rel[len(TESTS) + 1:])
            else:
                gates.append(TOOL_SELFTEST % (rel,))
        reasons.append("a .py changed, so every suite and tool that walks the tree "
                       "through a shared walk is included - editing one file turns "
                       "those red without touching them")
        if graph["broken"]:
            # A file the graph could not parse is a file whose edges it does not
            # know, so what reaches through it is unknown too.
            full = True
            reasons.append("%s - would not parse, so what it reaches is unknown "
                           "and the full set is selected" % (", ".join(graph["broken"]),))
    if vitest:
        gates.append(VITEST)
    if artifacts:
        gates.append(ARTIFACTS)
    if report:
        for doc in REPORT_DOCS:
            gates.append(REPORT_GATE % (doc,))
    if panel:
        gates.append(PANEL_GATE)
    return sorted(suites), _once(gates), reasons, full


# --- the CLI entry point -------------------------------------------------------
def main(argv):
    # THE TWO LISTING MODES FIRST, and returned from before anything below
    # touches git or the `--json`/`--base` flags: both are the contract
    # `derive-phase-gate.py`'s `meta.phaseGate.derived.listing` reads --
    # one suite path per line, nothing executed -- and neither asks what
    # changed, so neither needs `changed_files()` or a git repo at all.
    if "--list-all" in argv:
        for path in _all_suite_paths():
            print(path)
        return 0
    if "--list-related" in argv:
        i = argv.index("--list-related")
        for path in _related_suite_paths(argv[i + 1:]):
            print(path)
        return 0

    base = "HEAD"
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1] if len(argv) > i + 1 else "HEAD"
        argv = argv[:i] + argv[i + 2:]
    explicit = [a for a in argv if not a.startswith("-")]

    paths = changed_files(base, explicit)
    if paths is None:
        print("affected: cannot read git, so the full set is the only honest answer")
        return 2
    if not paths:
        print("affected: nothing changed against %s" % (base,))
        return 0

    suites, gates, reasons, full = select(paths)
    if full:
        if as_json:
            print(json.dumps({"full": True, "reasons": reasons}, indent=1))
        else:
            print("affected: FULL SET required")
            for r in reasons:
                print("  " + r)
        return 2

    if as_json:
        print(json.dumps({"full": False, "suites": suites, "gates": gates,
                          "reasons": reasons, "changed": paths}, indent=1))
        return 0
    print("affected: %d changed path(s) against %s" % (len(paths), base))
    for r in reasons:
        print("  " + r)
    print("")
    print("run:")
    for s in suites:
        print("  python3 %s/%s --selftest" % (TESTS.replace(os.sep, "/"), s))
    for g in gates:
        print("  " + g)
    if not suites and not gates:
        print("  (nothing - no check covers what changed)")
    return 0


# What `measure-affected-miss.py` recorded over a run of recent task commits: per
# commit, the label of the case that holds it, the commit, the files it changed, and
# every suite a planted fault in those files turned red while this selection left it
# out. Copied from the measurement's JSON, so the case reads no file outside the tree.
MEASURED_MISSES = (
    ("a18a", "4805f994",
     ("plugins/audit/scripts/governance/_runner_output.py",
      "plugins/audit/scripts/governance/stamp-verification.py",
      "tests/test__runner_output.py",
      "tests/test_stamp_verification.py",),
     ("tests/test__claude_home.py",
      "tests/test__filed_returns.py",
      "tests/test__output_lints.py",
      "tests/test__panel_composition.py",
      "tests/test__proc_group.py",
      "tests/test_audit_lookup.py",
      "tests/test_audit_task.py",
      "tests/test_commit_task_work.py",
      "tests/test_derive_phase_gate.py",
      "tests/test_drive_phase.py",
      "tests/test_full_gate.py",
      "tests/test_gen_demo_manifest.py",
      "tests/test_run_test_gate.py",)),
    ("a18b", "d33730d6",
     ("tests/test_drive_phase.py",),
     ("tests/test__output_lints.py",)),
    ("a18c", "5536cf07",
     ("plugins/audit/scripts/governance/drive-phase.py",
      "tests/test_drive_phase.py",),
     ("tests/test__filed_returns.py",
      "tests/test__invariants.py",
      "tests/test__output_lints.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_stamp_verification.py",
      "tools/stream-cost.py",)),
    ("a18d", "e4bd0447",
     ("plugins/audit/scripts/governance/drive-phase.py",
      "tests/test_drive_phase.py",),
     ("tests/test__filed_returns.py",
      "tests/test__invariants.py",
      "tests/test__output_lints.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_stamp_verification.py",
      "tools/stream-cost.py",)),
    ("a18e", "67d0e3dc",
     ("plugins/audit/scripts/governance/drive-phase.py",
      "tests/test_drive_phase.py",
      "tools/check-committed-pii.py",),
     ("tests/test__filed_returns.py",
      "tests/test__invariants.py",
      "tests/test__journal_io.py",
      "tests/test__output_lints.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_stamp_verification.py",
      "tools/stream-cost.py",)),
    ("a18f", "d1e8d994",
     ("plugins/audit/scripts/status/_doctor_policy.py",
      "plugins/audit/scripts/status/_skill_places.py",
      "tests/test__doctor_policy.py",
      "tests/test__skill_places.py",),
     ("tests/test__doctor_report.py",
      "tests/test__help_lints.py",
      "tests/test__output_lints.py",
      "tests/test_audit_doctor.py",
      "tests/test_drive_phase.py",
      "tests/test_run_agent_session.py",)),
    ("a18g", "c3ebab8a",
     ("plugins/audit/scripts/governance/run-agent-session.py",
      "plugins/audit/scripts/status/_doctor_policy.py",
      "plugins/audit/scripts/status/_skill_places.py",
      "tests/test__doctor_policy.py",
      "tests/test__skill_places.py",
      "tests/test_run_agent_session.py",
      "tools/lints/_deps.py",),
     ("tests/test__doctor_report.py",
      "tests/test__help_lints.py",
      "tests/test__output_lints.py",
      "tests/test_audit_doctor.py",
      "tests/test_commit_task_work.py",
      "tests/test_derive_phase_gate.py",
      "tools/affected.py",
      "tools/gate-parity.py",
      "tools/prove-gates.py",)),
    ("a18h", "587e2871",
     ("plugins/audit/scripts/governance/drive-phase.py",
      "plugins/audit/scripts/governance/run-agent-session.py",
      "tests/test_drive_phase.py",
      "tests/test_run_agent_session.py",),
     ("tests/test__filed_returns.py",
      "tests/test__invariants.py",
      "tests/test__output_lints.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_stamp_verification.py",
      "tools/stream-cost.py",)),
    ("a18i", "88892397",
     ("plugins/audit/scripts/governance/_scoped_commit.py",
      "plugins/audit/scripts/governance/drive-phase.py",
      "tests/test__scoped_commit.py",
      "tests/test_drive_phase.py",),
     ("tests/test__doctor_hygiene.py",
      "tests/test__doctor_trail.py",
      "tests/test__evidence_io.py",
      "tests/test__evidence_view.py",
      "tests/test__filed_returns.py",
      "tests/test__help_lints.py",
      "tests/test__invariants.py",
      "tests/test__output_lints.py",
      "tests/test__status_facts.py",
      "tests/test_audit_doctor.py",
      "tests/test_audit_status.py",
      "tests/test_audit_task.py",
      "tests/test_bench_report.py",
      "tests/test_close_phase.py",
      "tests/test_commit_task_work.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_full_gate.py",
      "tests/test_gen_demo_manifest.py",
      "tests/test_gen_demo_usage.py",
      "tests/test_guard_bash_writes.py",
      "tests/test_panel_server.py",
      "tests/test_render_report.py",
      "tests/test_run_test_gate.py",
      "tests/test_stamp_verification.py",
      "tests/test_verify_invariants.py",
      "tools/check-git-pipeline.py",
      "tools/check-rendered-artifacts.py",
      "tools/stream-cost.py",)),
    ("a18j", "794aa0d8",
     ("plugins/audit/scripts/governance/_scoped_commit.py",
      "plugins/audit/scripts/manifest/_manifest_io.py",
      "tests/test__scoped_commit.py",
      "tests/test_audit_task.py",
      "tests/test_commit_task_work.py",
      "tests/test_drive_phase.py",),
     ("tests/test__output_lints.py",)),
    ("a18k", "990bfa8c",
     ("tests/_harness.py",
      "tools/gate-parity.py",
      "tools/sweep-selftests.py",),
     ("tests/test__output_lints.py",)),
    ("a18l", "5101bd4d",
     ("plugins/audit/scripts/governance/drive-phase.py",
      "tests/test_drive_phase.py",),
     ("tests/test__filed_returns.py",
      "tests/test__invariants.py",
      "tests/test__output_lints.py",
      "tests/test_detect_plan_skip.py",
      "tests/test_stamp_verification.py",
      "tools/stream-cost.py",)),
    ("a18m", "17563b1b",
     ("plugins/audit/scripts/governance/run-agent-session.py",
      "tests/test_run_agent_session.py",),
     ("tests/test__output_lints.py",
      "tests/test_drive_phase.py",)),
)
# Suites that measurement named which the tree has since retired. Built rather than
# written, because a `.py` path under `tools/` that names no file is what
# `_refs.tool_basename_drift()` reports.
RETIRED_MISSES = tuple("tests/%s.%s" % (stem, "py") for stem in (
    "test_commit_audit_state", "test_commit_manifest_index"))


# --- selftest -----------------------------------------------------------------
# THIS FILE USED TO SAY IT NEEDED NONE: "its answers are checked by running the full
# set it defers to". That is false in the one direction that matters. A selector that
# UNDER-selects is invisible to the full set, because nobody runs the full set to
# check the selector - they run the narrowed set and believe it. The docstring above
# says under-selection is worse than no selector at all; these are what hold it.
#
# LABELS READ DOWN IN ORDER, and a case added beside its topic takes a LETTER
# suffix rather than the next free number - `a3b` next to `a3`, not `a14` at the
# bottom of the file's numbering. The label set was `a0 a1 a2 a3 a14 a4 a5 a12 a6
# ... a10 a13 a11` and the next free label was therefore not discoverable by
# reading, which is how the first attempt at fixing this collided with `a5`. `_harness.run()`
# now catches a collision by name, so this is about a reader's next label rather
# than about a proof - and it is a convention on purpose, not a lint: a suite
# that groups its cases by topic is right to, and a rule demanding one global
# ascending sequence would forbid exactly that.
def _cases(check):
    # ONE GRAPH FOR EVERY QUESTION BELOW: building it parses every `.py` the sweep
    # can reach, and each case asks about the same tree.
    graph = reach_graph()

    def sel(*paths):
        suites, gates, _why, full = select(list(paths), graph)
        return {"suites": suites, "gates": gates, "full": full}

    def why(*paths):
        """The reason lines alone, joined - what a reader of a narrowed run gets."""
        _suites, _gates, reasons, _full = select(list(paths), graph)
        return " | ".join(reasons)

    yml = ".github/workflows/ci.yml"
    dotted = sel(yml)
    undotted = sel("github/workflows/ci.yml")
    check("a0 the workflow is what the slice rule holds against the runner, so it "
          "narrows to the refs pins, the parity check and the cases of every tool "
          "that reads it by path, instead of demanding everything: %r" % (dotted,),
          (not dotted["full"])
          and "test__refs.py" in dotted["suites"]
          and PARITY in dotted["gates"]
          and all(TOOL_SELFTEST % (rel,) in dotted["gates"]
                  for rel in WORKFLOW_READERS))

    check("a1 THE PAIR: the same path with and without its leading dot give "
          "OPPOSITE answers. `lstrip(\"./\")` strips CHARACTERS, so it ate the "
          "dot and BOTH were the full set - asserting the dotted one alone "
          "would pass on the broken version too (%r vs %r)"
          % (dotted["full"], undotted["full"]),
          dotted["full"] is False and undotted["full"] is True)

    check("a2 ...while a leading `./` IS a prefix and is stripped, so the two "
          "spellings of one path select the same thing",
          sel("./tools/verify.sh") == sel("tools/verify.sh"))

    contributing = sel("CONTRIBUTING.md")
    check("a3 a root document that is a `_refs` SURFACE selects the refs pins. "
          "It selected only test__deps.py before, so a path rotting inside it "
          "went unchecked by every narrowed run: %r" % (contributing,),
          "test__refs.py" in contributing["suites"])

    claude = sel("CLAUDE.md")
    png = sel("docs/screenshots/panel.png")
    check("a3b THE PAIR: a root document that describes the gate set selects the "
          "parity check, and a path that does not describe it does not. Only "
          "the workflow selected it, so editing either document narrowed to a "
          "run that skipped the comparison - while the reason line claimed the "
          "gate set had been re-checked: %r / %r / %r"
          % (claude["gates"], contributing["gates"], png["gates"]),
          PARITY in claude["gates"]
          and PARITY in contributing["gates"]
          and PARITY not in png["gates"])

    both = sel("CLAUDE.md", "CONTRIBUTING.md", "tools/gate-parity.py")
    check("a3c ...and a gate three of those branches all reach is named ONCE. "
          "COUNTED rather than found: every sweep document appends the parity "
          "check and so does the comparison itself, so a change touching two of "
          "them made the narrowed run pay for it twice and `in` could not see "
          "it: %r" % (both["gates"],),
          both["gates"].count(PARITY) == 1)

    report_part = sel("plugins/audit/scripts/ui/report/areas.js")
    check("a3d THE SECOND DIRECTION, and it looks vacuous on purpose: a dedup "
          "that collapsed DIFFERENT gates is the other way to be wrong, and the "
          "report documents are separate runs. One gate per document, and the "
          "count comes from the list rather than from a number typed here: %r"
          % (report_part["gates"],),
          len([g for g in report_part["gates"]
               if g.startswith("node tools/check-report")]) == len(REPORT_DOCS))

    surfaces = [sfc for sfc, _m in _refs.SURFACES]
    reached = [sfc for sfc in surfaces if refs_reads(sfc.replace(os.sep, "/"))]
    check("a4 the surface rule is DERIVED from _refs, not copied: every one of "
          "its %d entries answers True. A hand-kept copy is what let three "
          "branches disagree about this" % (len(surfaces),),
          len(reached) == len(surfaces) and len(surfaces) > 8)

    check("a5 ...and it says False for a path _refs does not read, so a4 is a "
          "rule rather than a function that returns True",
          refs_reads("node_modules/vitest/index.js") is False)

    # Both paths are under `docs/`, which is NOT a `_refs` surface, so the extension
    # is the whole difference between them. A pair inside a surface would prove
    # nothing: everything there already answered True. The False half was
    # `docs/index.html` until the version-stamp rule started reading that page, which
    # is exactly the way a pair like this is supposed to go stale: loudly, in the
    # case, and not in the selector.
    check("a5b a document nowhere near the pinned list selects the refs pins now, "
          "because the published-fetch rule reads every document of its formats "
          "the repo keeps - and a non-document beside it still does not, so this is "
          "an extension rule and not a widening to everything",
          refs_reads("docs/design/audit-concurrency-report.md") is True
          and refs_reads("docs/screenshots/panel-blocks.png") is False)

    check("a6 AN UNRECOGNISED PATH SELECTS EVERYTHING. This is the safety the "
          "whole file rests on; if it ever narrowed, every other case here "
          "would still pass and the selector would quietly be wrong",
          sel("some/unknown/place.xyz")["full"] is True)

    ui = sel("plugins/audit/scripts/ui/panel/core.js")
    check("a7 a panel part selects the JavaScript unit tests AND the panel "
          "browser gate - vitest ran only in CI before, so a ui change could "
          "reach a push with none of its suites having run: %r" % (ui["gates"],),
          VITEST in ui["gates"] and PANEL_GATE in ui["gates"]
          and not ui["full"])

    tests = sel("tools/ui-tests/parse.test.mjs")
    check("a8 a vitest suite selects vitest and nothing else: %r" % (tests,),
          tests["gates"] == [VITEST])

    runner = sel("tools/sweep-selftests.py")
    check("a9 the runner every other suite is run BY selects its own cases - "
          "nothing else can vouch for it: %r" % (runner["gates"],),
          any("sweep-selftests.py --selftest" in g
              for g in runner["gates"]))

    # THE FIXTURE IS A TOOL THE OLD BRANCH HAD NO ARM FOR, which is what tells the
    # two versions apart: the runner above was selectable by a rule written for it
    # BY NAME, so a case pointed at it passes on the version that covers one file
    # and on the version that covers the directory alike.
    bench = sel("tools/bench-hooks.py")
    check("a9b THE PAIR: every other tool selects its own cases too. A change to "
          "one was classified 'a tool no suite covers' and the narrowed run "
          "skipped exactly the cases that change owed - so `verify.sh --affected` "
          "on any tool change ran none of them: %r" % (bench["gates"],),
          TOOL_SELFTEST % ("tools/bench-hooks.py",) in bench["gates"]
          and not bench["full"])

    check("a9c ...and the line a reader gets when nothing matches is a statement "
          "about THIS FILE, not about the file it was handed. The pair is what "
          "makes it a rule rather than a rewording: a shell script no arm matches "
          "still says so, and a tool that IS covered never reaches that line - "
          "which is the case that fails if it becomes unconditional: %r"
          % (why("tools/redfirst.sh"),),
          "selector's gap" in why("tools/redfirst.sh")
          and "selector's gap" not in why("tools/bench-hooks.py"))

    imported = sel("tools/ui-checks/responsive.mjs")
    check("a9d a part the panel gate IMPORTS selects the panel gate. These moved "
          "out of `capture-screenshots.mjs` and are imported back into it, so the "
          "full run drives them on every panel screenshot while the narrowed run "
          "reported them as covered by nothing: %r" % (imported["gates"],),
          PANEL_GATE in imported["gates"] and not imported["full"])

    py = sel("plugins/audit/scripts/_output.py")
    check("a10 a .py selects its own suite plus every suite that lints the whole "
          "tree, because editing one file turns those red without touching "
          "them (%d suites)" % (len(py["suites"]),),
          "test__output.py" in py["suites"]
          and "test__deps.py" in py["suites"] and not py["full"])

    lint = sel("tools/lints/_deps.py")
    lint_why = why("tools/lints/_deps.py")
    check("a10a a lint module under tools/lints is selected like the plugin `.py` "
          "it used to be - its own suite, the suites that import it by name, and "
          "the suites that lint the whole tree - and is NOT left in the tool arm's "
          "'no rule here matches it' gap, which is where a migrated file under "
          "tools/ fell: %r" % (lint["suites"],),
          "test__deps.py" in lint["suites"]
          and "test__panel_paths.py" in lint["suites"]
          and "test__output.py" in lint["suites"]
          and "NO RULE HERE MATCHES" not in lint_why and not lint["full"]
          and "test__refs.py" in sel("tools/lints/_refs.py")["suites"])

    page = sel("docs/demo-large.html")
    check("a10b a published report selects the version-stamp rule as well as the "
          "byte comparison. The stamp is the claim the page makes about which "
          "release it came from, and until it was read by a suite the only "
          "thing that could notice a stale one was a re-render: %r" % (page,),
          "test__refs.py" in page["suites"]
          and ARTIFACTS in page["gates"] and not page["full"])

    # A NARROWED RUN IS A BEFORE-COMMIT RUN, so the byte comparison it selects must
    # not ask what HEAD carries: before the commit exists that arm is red for every
    # change that re-renders a page, the correct one included. The no-flag spelling
    # asks both arms, which is the shape this case exists to refuse.
    _art = [g.split() for g in page["gates"]
            if "tools/check-rendered-artifacts.py" in g]
    check("a10c ...and the byte comparison it selects asks the fresh render ONLY "
          "(`--before-commit`), never what HEAD carries - a narrowed run happens "
          "before the commit it would be comparing against: %r" % (_art,),
          len(_art) == 1
          and _art[0][:2] == ["python3", "tools/check-rendered-artifacts.py"]
          and _art[0][2:] == ["--before-commit"])

    shot = sel("docs/screenshots/panel-blocks.png")
    check("a11 a committed PNG selects no gate and does NOT widen - 'nothing "
          "covers this' is a real answer here, and it is not spelled the same "
          "way as 'I could not tell': %r" % (shot,),
          shot["gates"] == [] and not shot["full"])

    # THE PROSE SCANS ARE DERIVED, so what selects them is the EXTENSION and never
    # the directory. Both paths below are ones whose OWN branch answered
    # completely and correctly for everything except this, which is why the rule
    # had to be applied to every path rather than added inside those branches -
    # the same reasoning the `refs_reads()` line at the top of `select()` carries.
    #
    # Measured, not guessed: these are the two files where each half of this bug
    # was found, and they were also the two that selected the wrong side of this. Anything under
    # `plugins/audit/commands/` or `tests/` was already covered by another branch.
    doc = sel("plugins/audit/scripts/ui/report-css/README.md")
    check("a14 a `.md` whose branch answers about a RENDERED surface still "
          "selects the document scan - this one carries a part count per "
          "assembled surface, and reassembling the report says nothing about "
          "whether the count is still true: %r" % (doc,),
          "test__deps.py" in doc["suites"] and not doc["full"])

    tool = sel("tools/prove-gates.py")
    check("a15 ...and a `.py` under tools/ selects the `.py` scan, whatever its "
          "own branch decided. `tools/` holds the sweep runner, the parity check "
          "and the mutation table, every one of which talks about counts, and "
          "its branch used to end in 'a tool no suite covers': %r" % (tool,),
          "test__output.py" in tool["suites"] and not tool["full"])

    def _run_lines(argv):
        """stdout from `main(argv)`, split into non-blank lines -- what a
        caller of `--list-related`/`--list-all` actually reads, captured
        rather than read off an internal return value."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = main(argv)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        return lines, exit_code

    # A module nothing else imports or runs, so the listing is narrower than the
    # full one and a17's comparison means something: `_output.py` is reached by
    # every suite through the harness, and its listing IS the full one.
    narrow = "plugins/audit/scripts/governance/record-outside-run.py"
    related_lines, related_exit = _run_lines(["--list-related", narrow])
    expected_related = sorted(_suite_path(s) for s in select([narrow], graph)[0])
    scanner_suites = [rel for rel in graph["scanners"] if _is_suite(rel)]
    check("a16 `--list-related` with a scripts/ module prints the suites that "
          "import or run it plus every suite that walks the tree, one path per "
          "line, and runs no suite -- the EXIT CODE is 0 and nothing but paths "
          "came out: %r" % (related_lines,),
          related_exit == 0
          and sorted(related_lines) == expected_related
          and scanner_suites
          and all(s in related_lines for s in scanner_suites)
          and _suite_path("test_record_outside_run.py") in related_lines)

    unknown_lines, unknown_exit = _run_lines(
        ["--list-related", "some/unknown/place.xyz"])
    check("a17 `--list-related` with a path it does not recognise prints the "
          "FULL suite list -- the same widening `select()` already carries "
          "for an unrecognised path, never an empty or a narrowed one: %r"
          % (unknown_lines,),
          unknown_exit == 0
          and sorted(unknown_lines) == _all_suite_paths()
          and len(unknown_lines) > len(related_lines))

    # THE HISTORY, NOT A RULE. Each row is a commit `measure-affected-miss.py` planted
    # a fault in, the files it changed, and the suites that went red under the fault
    # while this file's selection for those files left them out. The rows are the
    # measurement's own data, carried inline so the case needs no file outside the
    # tree; a rule written to pass them would be a list of instances, so the fix is
    # judged by the rows rather than shaped by them.
    def covers(paths, suite):
        """Read the selection the way the measurement does: the full set covers
        everything, a suite under `tests/` is named by basename, any other suite only
        by the gate that asks for its own cases."""
        suites, gates, _why, full = select(list(paths), graph)
        if full:
            return True
        if suite.startswith(TESTS + "/"):
            return os.path.basename(suite) in suites
        return TOOL_SELFTEST % (suite,) in gates

    for label, sha, changed, missed in MEASURED_MISSES:
        left = [s for s in missed if not covers(changed, s)]
        check("%s the selection for commit %s's changed files names every suite the "
              "measurement saw go red without being selected; left out: %r"
              % (label, sha, left),
              not left)

    retired = [s for s in RETIRED_MISSES if os.path.exists(os.path.join(REPO, s))]
    check("a18z a missed suite left out of the rows above is one the tree no longer "
          "holds - and if it comes back it belongs in a row, so its return is red "
          "here rather than silently unchecked: %r" % (retired,),
          not retired and len(RETIRED_MISSES) > 0)

    leaf = "plugins/audit/scripts/governance/record-outside-run.py"
    leaf_sel = sel(leaf)
    every = _all_suite_paths()
    check("a19 THE OTHER DIRECTION: a module nothing imports, runs or reads by name "
          "outside its own suite still narrows - widening every row above to the "
          "full set would pass them all and select nothing. Selected %d suites of "
          "the %d the full set runs" % (len(leaf_sel["suites"]), len(every)),
          not leaf_sel["full"]
          and "test_record_outside_run.py" in leaf_sel["suites"]
          and len(leaf_sel["suites"]) < len(every))


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
