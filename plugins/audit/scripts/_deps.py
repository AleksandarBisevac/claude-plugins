#!/usr/bin/env python3
"""
The module structure written down once, then checked against the truth every run.

`LAYERS` is this module's own data: every `scripts/*.py` basename, grouped into strictly
ordered layers. The rule a layer table is for is simple to say and easy to let rot: a file
may import a sibling in a LOWER layer, never a peer or a higher one, and hooks/ may not
import scripts/ at all (hooks run on every tool call from a launcher that may not even have
scripts/ on its path — the isolation is load-bearing, not stylistic). Saying the rule once
in prose does not enforce it; the table drifts the moment someone adds an import and nobody
re-reads the sentence. This module makes the rule self-checking: `import_graph()` reads the
REAL edges via `ast`, `layer_violations()` compares them against `LAYERS`, and the selftest
this file's own CI runs fails the moment truth and table disagree.

WHICH FILES, AND WHAT A NODE IS CALLED. Every `.py` under scripts/ and hooks/ is scanned
WHEREVER IT SITS - the walk is `_output.py_files`, recursive, the same one both of
`_output`'s own lints and CI's two `find` sweeps use. It used to be a flat `os.listdir`
in all three places, which is the whole reason `CONTRIBUTING.md` had to forbid a `.py` in
a subdirectory: the file did not fail anything, it silently stopped being checked. The
hazard was the SILENCE, not the subdirectory, so the walk was widened rather than the
shape forbidden. A node is named by its BASENAME (`scripts/usage/core.py` is `core`), and
`_module_files` carries the argument for that and the collision check that pays for it.

WHY `ast`, NOT A REGEX. An import can be nested inside a function, a `try`, a selftest -
`_help.py` reaches for `_panel_settings` from inside its own selftest, five lines of comment
explaining why that one is safe. A textual grep sees line noise; `ast.walk` sees a real edge
whether it is module-level or fifty lines deep in a function body, which is the only way a
lint like this is worth trusting.

WHY THE WALK READS `_loader` CALLS TOO, AND WHAT IT COST NOT TO. An `import` statement is a
MINORITY of the real edges here. Every entry point is hyphenated, so `import audit-status` is
not legal Python and nothing can spell that edge - scripts/ reaches those siblings through
`_loader` at runtime instead, and a `_loader.load_script("audit-status.py")` is an `ast.Call`
that an import walk cannot see at all. For as long as this module looked only at `ast.Import`
/ `ast.ImportFrom` it reported ZERO violations on a tree carrying twenty-one peer-to-peer or
upward runtime edges, and printed a clean module map beside them. That is worse than having no
lint: a rule that is configured, green and structurally blind is believed. `_loader` is the
ONE loading mechanism scripts/ has (that is the whole point of its own docstring), so its call
shapes are read here as edges of the same graph - see `_runtime_loaded_sibling_names` for the
shapes covered and the one that is deliberately not.

WHY LAYERS, NOT A STRICT TOPOLOGICAL SORT. The tightest possible layering (every node one
above the highest of its own dependencies) is not what a human wants to read in a guide: it
would put `audit-journal.py` (which imports only `_output`) two layers below `panel-server.py`
(which imports almost everything), even though both are equally "an entry point nobody else
imports." A layer is a GROUP with a meaning a reader can hold in their head - "the entry
points," "the panel's read-side helpers" - and the only hard constraint on membership is that
every real edge still points strictly downward. `validate-config.py` imports only `_policy`
(layer 1) yet sits at layer 7 with its eleven siblings; that is not slack in the checker, it
is the checker correctly treating "nothing imports an entry point" as permission to place it
wherever its group belongs, same idea named in the exercise's own validate-config example.

`tests/` IS NOT IN `LAYERS`, AND THE OMISSION IS THE DESIGN. A layer table answers "may
this module import that one", and it answers it for the shipped product: `scripts/` and
`hooks/` are what a user installs and what a hook loads on every tool call. A test file
imports downward into whatever it tests and is imported by nothing, so it has no position
in that order to be wrong about — giving it one would mean inventing a layer above every
existing layer whose only rule is "nothing may point here". That rule is worth having, and
`tests_import_violations()` states it directly instead: nothing under `scripts/` or
`hooks/` may import from `tests/`. A test is allowed to reach into the product; the
product is never allowed to reach into its tests, because the day it does, the tests stop
being removable and start being a dependency a consumer has to install.

THE ONE EXCEPTION THIS FILE USED TO CARRY IS GONE. Its first run found exactly one violation of
"hooks import nothing from scripts": `hooks/_config.py`'s guarded, static `import _manifest_io`,
reached by inserting scripts/ at the FRONT of `sys.path`. It was named in an allow-list here
(`_KNOWN_HOOKS_EXCEPTIONS`) because that task could only touch this file; it was fixed in its own
session (F11) by routing the load through the `_load_scripts_module` its own sibling two lines
below already used, and the allow-list went with it. The rule is stated without exceptions now,
which is the only form of it a reader can trust — an allow-list that survives its cause is a
second place the rule lives, and the next violation would be argued against the list rather than
against the rule.
"""

import ast
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.join(os.path.dirname(_HERE), "hooks")
_TESTS_DIR = os.path.join(os.path.dirname(_HERE), "tests")

# Run as a command, `sys.path[0]` is already this directory; imported from anywhere else
# it is not. The same two-line preamble `_help.py` and `_panel_state.py` carry, for the
# same reason - and `_output` was already an edge of this module (the `safe_stdio` import
# in `__main__` below), so hoisting it to module level adds no new one.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _output  # noqa: E402  (py_files: the ONE recursive `.py` walk, shared not copied)

# The module structure, position-indexed: LAYERS[0] is layer 0, the floor. Built from the
# REAL import graph (see the module docstring), not aspiration - `import_graph()` and the
# selftest's real-tree cases are what keep this honest as the tree grows.
# --- layer table --------------------------------------------------------------
LAYERS = (
    ("_output",),
    # _deps (this module) imports only _output, the safe_stdio guard - same as every
    # other member of this layer - so it belongs beside them, not in a layer of its own.
    ("_ui_theme", "_loader", "_fmt", "_cli_fmt", "_manifest_io", "_areas", "_policy",
     "_usage_core", "_deps", "_refs"),
    ("_panel_settings", "_panel_ui", "_report_html", "_report_ui", "_usage_analytics"),
    # The usage metering stack is a three-link chain, `_usage_core` -> `_usage_analytics`
    # -> `usage_ledger`, so it needs three layers under its lowest consumer. That consumer
    # is `_report_usage`, which sat here beside `_help` and now sits one layer up: moving
    # ONE module was the whole cost of making room, where inserting a layer would have
    # renumbered every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    # `_report_usage` reaches nothing at layer 4 or above, and only render-report (L7)
    # reaches it, so the move is free.
    ("_help", "usage_ledger"),
    # `_panel_page` (the panel's assembled page: the substitution chain and the
    # ~1,450 lines of cases that read the result) lands here rather than beside
    # `_panel_state`, and that placement is the whole cost of the split. Its
    # deepest reach is `usage_ledger` at L3 - `_panel_ui`/`_panel_settings` are
    # L2, `_ui_theme`/`_loader` L1, `_help` L3 - so L4 is the first layer that
    # holds every one of its edges strictly downward. Sitting beside
    # `_panel_discovery` and `_report_usage` costs nothing: it reaches neither,
    # and neither reaches it. The alternative was a new layer, which renumbers
    # every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    ("_panel_discovery", "_panel_page", "_report_usage"),
    # `_report_md` (render_html's Markdown twin) and `_report_page` (the whole
    # document) are the report's answer to the same question `_panel_page`
    # answered above, and they land the same way: at the FIRST layer that holds
    # every one of their edges strictly downward, beside whatever already lives
    # there. `_report_md` reaches `_report_usage` (L4) and `_report_html` (L2),
    # so L5; `_report_page` reaches `_report_md`, so L6. Neither touches
    # `_panel_state`/`_panel_write` and neither is touched by them, so sharing
    # their layers costs nothing - where a new layer for the pair would renumber
    # every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    #
    # NOT above L6, and that is the design rather than a coincidence: the gate
    # verdict at the top of the report comes from `audit-status` (L7), so
    # `render_html` takes it as an INJECTED callable and render-report.py - which
    # already carries that L7 -> L7 runtime edge, recorded below - supplies it.
    # Reaching the gate from `_report_page` would be a helper calling up, and the
    # runtime-load half of this lint would report it.
    ("_panel_state", "_report_md"),
    ("_panel_write", "_report_page"),
    ("panel-server", "render-report", "audit-status", "audit-doctor", "audit-usage",
     "validate-manifest", "validate-config", "audit-journal", "audit-lock",
     "gen-demo-manifest", "gen-demo-usage", "migrate-manifest", "audit-task"),
)

# No allow-list. There was one, for exactly one import, and it is gone with the import (F11);
# see the module docstring for why it is not kept "in case".


def _all_names(layers=None):
    """Every module name LAYERS assigns, flattened, in table order."""
    names = []
    for members in (layers if layers is not None else LAYERS):
        names.extend(members)
    return names


def _layer_of(name, layers=None):
    """The layer index `name` is assigned to, or None if LAYERS has no entry for it."""
    for i, members in enumerate(layers if layers is not None else LAYERS):
        if name in members:
            return i
    return None


# --- file discovery -----------------------------------------------------------
# ONE module name per file, and it is the BASENAME: `scripts/usage/core.py` is `core`,
# never `usage/core`. That is not a shortening for readability, it is the only name
# anything in this tree can reach the file by. `import core` resolves on `sys.path`,
# which carries scripts/ and not scripts/usage/; a runtime load is read through
# `_py_literal_basenames`, which drops the directory on purpose so that
# `../hooks/x.py` is not mistaken for a scripts/ sibling. A node called `usage/core`
# would therefore match no edge either walk can produce, and `LAYERS` would become a
# table of names nothing in the tree spells.
#
# The price of that choice is that a `.py` BASENAME must be unique across the whole
# recursive tree, and the price is charged here rather than assumed in a comment: two
# files claiming one name do not merely confuse the map, they COLLAPSE INTO ONE NODE -
# every edge of one is attributed to the other, and the layer rule is then judged
# against a graph that does not exist. `layer_violations()` reports a collision as a
# violation in its own words, so the day `usage/core.py` and `panel/core.py` both exist
# the build says so instead of quietly keeping whichever the walk saw last. This is the
# same shape as `r8`, which asserts the hooks/-vs-scripts/ half of the same precondition.
def _module_files(directory):
    """`(modules, collisions)` for every `.py` under `directory`, RECURSIVELY.

    `modules` maps module name -> a LIST of `(relname, path)`, and the list is a list
    rather than a single entry for exactly one reason: a second file claiming the same
    name has to be visible instead of overwriting the first. `collisions` is the sorted
    list of names carrying more than one file - empty on any tree that obeys the rule
    above, and never confused with "no files found", which shows up as an empty
    `modules` instead.

    `relname` is `_output.py_files`' forward-slashed path relative to `directory`, kept
    so a violation can NAME `usage/core.py` rather than a bare `core.py` the reader then
    has to go hunting for. On today's flat tree it is exactly the basename.
    """
    modules = {}
    for rel, path in _output.py_files(directory):
        modules.setdefault(os.path.basename(rel)[:-3], []).append((rel, path))
    return modules, sorted(name for name in modules if len(modules[name]) > 1)


def _named_by(modules):
    """module name -> the relname a violation message should call it by.

    The first entry wins; a name with a second entry is already reported as a collision
    by `layer_violations()`, so this does not ALSO have to invent an answer to "which of
    the two did you mean".
    """
    return dict((name, entries[0][0]) for name, entries in modules.items())


# --- runtime loads ------------------------------------------------------------
# hooks/ is deliberately NOT scanned this way. Hooks keep their own copies of the
# loader and DO reach scripts/ modules by path on purpose, degrading gracefully when
# the file is not installed; the rule this module enforces for them - no STATIC
# import of a scripts/ module - is about import-TIME coupling, and reading their
# runtime loads as violations would fail a design decision rather than a defect.
_LOADER_MODULE = "_loader"

# `_loader`'s public API is `load`, `load_script` and `load_hooks_config`. The third
# is left out on purpose rather than forgotten: it takes no path at all and resolves
# `../hooks/_config.py` by construction, so it can never name a scripts/ sibling, and
# listing it would imply an edge it cannot produce.
_LOADER_FUNCS = ("load", "load_script")


def _loader_names(tree):
    """`(module_names, function_names)` - every local name `_loader` is reachable by.

    Both spellings the tree actually uses are covered: plain `import _loader`, and
    `import _loader as _ldr` (validate-config.py's selftest). `from _loader import
    load_script` is read as well even though nothing writes it today - an unhandled
    call shape is not a smaller graph, it is a blind spot that opens silently the
    first time somebody writes it, which is the exact failure this whole section is
    repairing.
    """
    module_names = set()
    function_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _LOADER_MODULE:
                    module_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module != _LOADER_MODULE:
                continue
            for alias in node.names:
                if alias.name in _LOADER_FUNCS:
                    function_names.add(alias.asname or alias.name)
    return module_names, function_names


def _is_loader_call(call, module_names, function_names):
    """True if `call` calls one of `_loader`'s loading functions directly."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in module_names and func.attr in _LOADER_FUNCS
    if isinstance(func, ast.Name):
        return func.id in function_names
    return False


def _loader_wrapper_names(tree, module_names, function_names):
    """Local function names that forward a CALLER-CHOSEN target to `_loader`.

    Three files wrap the loader (`audit-doctor._load`, `audit-usage._load`,
    `_panel_state._load`) and in those the filename is spelled at the CALL SITE, not
    in the wrapper body, so the call site is where the edge is readable.

    The test is that the wrapper passes one of its OWN parameters into the loader
    call - that is what makes the caller the one choosing the target. A function that
    merely hard-codes a load (`_panel_state._cores`, `render-report._load_status_lib`
    and ~20 more accessors of that shape) is NOT a wrapper: its own body already
    carries the literal, so following its zero-argument call sites would add nothing
    and would invent a false edge the day one of them is handed an unrelated `.py`
    string. Both rules were run over the real tree and agree on it exactly; the
    narrower one is kept because only it stays true of a tree nobody has read yet.
    """
    wrappers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = set(a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg))
        if not params:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            if not _is_loader_call(sub, module_names, function_names):
                continue
            used = set(n.id for n in ast.walk(sub) if isinstance(n, ast.Name))
            if used & params:
                wrappers.add(node.name)
                break
    return wrappers


def _py_literal_basenames(node):
    """Module basenames of every `"....py"` string literal anywhere inside `node`.

    The directory is dropped, so `os.path.join(_HERE, "..", "hooks",
    "guard-capabilities.py")` yields `guard-capabilities` - not a scripts/ sibling,
    therefore not an edge, which is how audit-doctor's two hooks/ loads stay out of
    this graph. That is also this rule's one false-positive shape: a `../hooks/x.py`
    load WOULD be recorded against scripts/x.py if both files existed. No such
    basename collision exists, and the selftest asserts that rather than assuming it.
    """
    found = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
            continue
        if sub.value.endswith(".py"):
            found.append(os.path.basename(sub.value)[:-3])
    return found


def _runtime_loaded_sibling_names(tree, sibling_names, self_name):
    """Base module names `tree` loads at RUNTIME through `_loader`.

    An edge is counted when a `_loader` loading call - direct, under an alias, or
    through one of the three local wrappers `_loader_wrapper_names` recognises -
    contains a string literal ending in `.py` whose basename is one of
    `sibling_names`. A `modname="usage_ledger"` argument is not one (no `.py`), and a
    hooks/ filename is not one (no such sibling), so neither invents an edge.

    LIMITATION, deliberate and load-bearing: only a filename SPELLED AS A LITERAL
    INSIDE THE CALL counts. `_loader.load(os.path.join(_HERE, "render-report.py"))`
    is read, because the literal is right there in the call expression;
    `path = os.path.join(_HERE, "audit-journal.py")` on one line followed by
    `_loader.load(path)` on the next is NOT, and neither is any genuinely computed
    name. A target this function cannot READ is not a target it may GUESS - widening
    the scan to "any `.py` literal in the file" would manufacture edges out of error
    messages and doc strings, and the selftest carries the fixture that goes red the
    day someone tries it. One real call site is invisible for this reason today
    (`_panel_state`'s journal loader), and that is a known gap, not a clean scan.
    """
    module_names, function_names = _loader_names(tree)
    if not module_names and not function_names:
        return []
    wrappers = _loader_wrapper_names(tree, module_names, function_names)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        wrapped = isinstance(node.func, ast.Name) and node.func.id in wrappers
        if not (wrapped or _is_loader_call(node, module_names, function_names)):
            continue
        for base in _py_literal_basenames(node):
            if base in sibling_names and base != self_name:
                found.append(base)
    return found


# --- import graph -------------------------------------------------------------
def _imported_sibling_names(tree, sibling_names, self_name):
    """Base module names `tree` statically imports that are also in `sibling_names`.

    Walks the WHOLE tree (nested defs, try/except, selftest bodies included) - the same
    reach `_output.house_style_violations` uses, and for the same reason: an import fifty
    lines inside a function is still an edge the moment that function ever runs. Only
    `import X` / `from X import ...` with `level == 0` count; a dotted `import os.path`
    or a relative `from . import x` is reduced to its first component, and ignored unless
    that component is itself one of the sibling names.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in sibling_names and base != self_name:
                    found.append(base)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import; no sibling in this tree spells one
                continue
            base = (node.module or "").split(".")[0]
            if base in sibling_names and base != self_name:
                found.append(base)
    return found


def _scan_edges(script_dir=None):
    """`(static, runtime, broken)` - the two kinds of edge kept apart, in one pass.

    `static` and `runtime` are SETS of `(importer, imported)` pairs (module names, no
    `.py`); an edge that is both - a file that imports a sibling and also loads it by
    path - is in each. `broken` is a sorted list of RELNAMES (with `.py`) that would not
    parse; a relname rather than a module name because that violation is the one whose
    reader most needs to be handed the file. Recursive `.py` walk via `_module_files`,
    nothing skipped silently: a file that will not parse is reported in `broken` rather
    than dropped from the scan, the same rule `_output.entries_missing_guard` and
    `_output.house_style_violations` both follow.

    Kept apart for one reason worth the tuple: a violation that says "runtime-loads"
    instead of "imports" tells the reader which kind of line to go and find, and there
    is no `import` line to find for most of them.
    """
    script_dir = script_dir or _HERE
    modules, _collisions = _module_files(script_dir)
    sibling_names = set(modules)

    static = set()
    runtime = set()
    broken = []
    for mod in sorted(modules):
        for rel, path in modules[mod]:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
            except (OSError, SyntaxError):
                broken.append(rel)
                continue
            for imported in _imported_sibling_names(tree, sibling_names, mod):
                static.add((mod, imported))
            for loaded in _runtime_loaded_sibling_names(tree, sibling_names, mod):
                runtime.add((mod, loaded))
    return static, runtime, sorted(broken)


def import_graph(script_dir=None):
    """The real dependency graph of scripts/*.py: static imports AND runtime loads.

    Returns `(edges, broken)` - `edges` a sorted list of unique `(importer, imported)`
    pairs of MODULE NAMES, `broken` a sorted list of relnames that would not parse. A
    node is a basename (`scripts/usage/core.py` is `core`; see `_module_files` for why
    it can be nothing else), which is also why two files may not share one: they would
    be a single node here, wearing each other's edges. That collision is not silently
    tolerated - `layer_violations()` names it - but this function does not itself
    return it, so a caller reading the graph alone reads it through that gate.
    The two kinds are
    unioned here on purpose: a dependency is a dependency, and `layer_violations()` /
    `_find_cycle()` must judge the whole graph, not the quarter of it spelled with an
    `import` keyword. `_scan_edges()` is the same scan with the kinds still separated,
    for callers that need to say WHICH kind an edge is.

    A hyphenated name (every entry point) is reachable both ways now: as an IMPORTER,
    because it runs as a command and can `import _loader` like anything else, and as an
    IMPORTED target, because `_loader.load_script("audit-status.py")` names one where
    `import audit-status` cannot. It is exactly those targets the old import-only walk
    could not see.
    """
    static, runtime, broken = _scan_edges(script_dir)
    return sorted(static | runtime), broken


def _find_cycle(edges):
    """One cycle, as a list of names where `path[0] == path[-1]`, or None.

    Not every cycle - one is enough to name and fix, and a table with a real cycle is
    already broken regardless of how many loops it contains. Deterministic: adjacency is
    walked in sorted order, so the same graph always names the same cycle.
    """
    adjacency = {}
    for importer, imported in edges:
        adjacency.setdefault(importer, []).append(imported)

    visited = set()
    on_stack = set()
    stack = []

    def visit(node):
        visited.add(node)
        on_stack.add(node)
        stack.append(node)
        for nxt in sorted(adjacency.get(node, ())):
            if nxt in on_stack:
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if nxt not in visited:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        on_stack.discard(node)
        return None

    for node in sorted(adjacency):
        if node not in visited:
            found = visit(node)
            if found:
                return found
    return None


def _hooks_scripts_imports(hooks_dir, script_names):
    """(hookfile, importedmodule) pairs: every static hooks/**.py import of a scripts name.

    A hook's own sibling (`_config`, etc.) is not in `script_names` and is never flagged -
    only a name that is genuinely one of scripts/'s own modules counts. A hooks file
    that will not parse is reported (as a violation, by the caller) rather than skipped.

    Recursive: `hookfile` is the path relative to `hooks_dir`, so a hook one directory
    down is both SEEN and named by a path the reader can open. A hook that reaches into
    scripts/ is exactly the rule this module refuses to let rot, and a flat listing
    quietly exempted any hook somebody moved into a folder.
    """
    hits = []
    for rel, path in _output.py_files(hooks_dir):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, SyntaxError):
            hits.append((rel, None))  # None: caller renders this as "does not parse"
            continue
        for imported in _imported_sibling_names(tree, script_names, None):
            hits.append((rel, imported))
    return hits


def _edge_verb(edge, static, runtime):
    """How a violation should describe `edge`: the reader has to find the line.

    "imports" sends them looking for an `import` statement, which for most of the
    edges in this tree does not exist - the dependency is a `_loader` call somewhere
    in a function body. Naming the kind is the difference between a message that
    locates the problem and one that sends the reader hunting for the wrong syntax.
    """
    if edge in static and edge in runtime:
        return "imports and runtime-loads"
    return "imports" if edge in static else "runtime-loads"


def layer_violations(script_dir=None, hooks_dir=None, layers=None):
    """(file, what) tuples: everything wrong with the real tree against LAYERS.

    Five kinds, each its own wording so a failure names what actually broke:
      - two files claiming one module name. The walk is recursive, so `usage/core.py`
        and `panel/core.py` can both exist; they would be ONE node in the graph, each
        wearing the other's edges, and every judgement below would be made about a tree
        that is not there. Reported first because everything below it assumes otherwise;
      - a file on disk with no LAYERS entry, or a LAYERS entry with no file (stale table
        entry is drift too - a name that used to exist and was deleted without updating
        the table is exactly as wrong as a new file nobody added to it);
      - an import cycle;
      - an edge where the importer's layer is not STRICTLY above the imported's (same
        layer included - a same-layer import is still not downward). Both kinds of
        edge are judged: the message opens with `imports`, `runtime-loads` or
        `imports and runtime-loads` so the wording names what is actually on the line;
      - a hooks/*.py static import of a scripts/ module name, with no exceptions - there was
        one, for one import, and both are gone (F11; see the module docstring).
    A file that will not parse is its own violation in every one of the four passes it
    would otherwise take part in, rather than being dropped from the scan.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    layers = layers if layers is not None else LAYERS
    violations = []

    modules, collisions = _module_files(script_dir)
    named = _named_by(modules)
    on_disk = set(modules)
    assigned = set(_all_names(layers))

    for name in collisions:
        violations.append((named[name],
                            "module name %r is claimed by %d files (%s) - a `.py` "
                            "basename must be unique across the whole of scripts/, "
                            "because `import` and `_loader` both resolve by basename "
                            "and two files sharing one are a single node in this graph"
                            % (name, len(modules[name]),
                               ", ".join(rel for rel, _path in modules[name]))))

    for mod in sorted(on_disk - assigned):
        violations.append((named[mod], "on disk but not assigned a layer in LAYERS"))
    for mod in sorted(assigned - on_disk):
        violations.append((mod + ".py",
                            "assigned a layer in LAYERS but no such file exists "
                            "(stale table entry)"))

    static, runtime, broken = _scan_edges(script_dir)
    edges = sorted(static | runtime)
    for rel in broken:
        violations.append((rel,
                            "file does not parse; cannot be scanned for import edges"))

    for edge in edges:
        importer, imported = edge
        li = _layer_of(importer, layers)
        lj = _layer_of(imported, layers)
        if li is None or lj is None:
            continue  # already named above as unassigned
        if not (li > lj):
            violations.append((named[importer],
                                "%s %s (layer %d) from layer %d - not strictly "
                                "downward" % (_edge_verb(edge, static, runtime),
                                              imported, lj, li)))

    cycle = _find_cycle(edges)
    if cycle:
        violations.append((named[cycle[0]], "import cycle: " + " -> ".join(cycle)))

    if os.path.isdir(hooks_dir):
        for hookfile, imported in _hooks_scripts_imports(hooks_dir, on_disk):
            if imported is None:
                violations.append((hookfile,
                                    "file does not parse; cannot be scanned for "
                                    "scripts imports"))
                continue
            violations.append((hookfile,
                                "imports scripts module %s - hooks must not depend "
                                "on scripts" % imported))

    return violations


# --- the tests/ boundary ------------------------------------------------------
def tests_import_violations(script_dir=None, hooks_dir=None, tests_dir=None):
    """(file, what) for every scripts/ or hooks/ file that reaches into `tests/`.

    The rule `LAYERS` cannot express (see the module docstring): the product may not
    depend on its tests. It is not a style preference — `tests/` is where the suites
    that used to live inside each module went, and the whole value of moving them is
    that they can be deleted, skipped or shipped separately. One `from _harness import
    run` in a script takes that back, quietly, and the first person to notice is a
    consumer whose install is missing a directory.

    Both edge kinds are read, the same two `layer_violations()` reads: a static
    `import`, and a `_loader` call carrying a `tests/` filename as a literal. The
    second inherits `_runtime_loaded_sibling_names`' limitation exactly — only a
    literal spelled INSIDE the call counts — and it is why a docstring or an error
    message naming `tests/test_x.py` is not an edge. Three files in `scripts/` and
    `hooks/` name a test file in prose today (the migrated pilots, pointing readers at
    where their cases went), and a looser scan would report all three.

    A file that will not parse is reported here as well as by the lints that already
    say so; a scan that silently skips it is a scan claiming a clean answer about a
    file it never read.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else _TESTS_DIR

    if not os.path.isdir(tests_dir):
        return []
    test_names = set(os.path.basename(rel)[:-3]
                     for rel, _path in _output.py_files(tests_dir))
    if not test_names:
        return []

    violations = []
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)):
        if not os.path.isdir(directory):
            continue
        for rel, path in _output.py_files(directory):
            named = "%s/%s" % (kind, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
            except (OSError, SyntaxError):
                violations.append((named, "file does not parse; cannot be scanned "
                                          "for tests/ imports"))
                continue
            for name in sorted(set(_imported_sibling_names(tree, test_names, None))):
                violations.append((named, "imports %s from tests/ - the product may "
                                          "not depend on its own test tree" % name))
            for name in sorted(set(_runtime_loaded_sibling_names(tree, test_names,
                                                                 None))):
                violations.append((named, "runtime-loads %s from tests/ - the product "
                                          "may not depend on its own test tree" % name))
    return violations


# --- rendering ----------------------------------------------------------------
def render(script_dir=None, layers=None):
    """A deterministic module map: every layer, its members, each member's STATIC
    out-edges.

    The format is committed to from this task on - a later phase generates the guide's
    module map from this exact text, under a drift lint, so two calls on an unchanged tree
    must be byte-identical. Stable inputs only: `LAYERS`' own tuple order for layers, a
    sorted() member list within a layer, sorted() edges per member.

    STATIC ONLY, AND THAT IS A KNOWN GAP, NOT A JUDGEMENT. `layer_violations()` reads
    the whole graph (see `import_graph`); this map still draws only the `import` edges,
    because its text is byte-pinned to a fence in PLUGIN-BUILD-GUIDE.md that
    `map_drift()` compares against and that a change here cannot update. Adding the
    runtime edges to the picture is a one-line change plus a regenerated fence, and it
    belongs in the session that owns the guide - not in one that would leave the two
    disagreeing.
    """
    layers = layers if layers is not None else LAYERS
    static, _runtime, broken = _scan_edges(script_dir)
    out_edges = {}
    for importer, imported in sorted(static):
        out_edges.setdefault(importer, []).append(imported)

    lines = ["module map (%d layers, generated by _deps.py --render)" % len(layers)]
    for i, members in enumerate(layers):
        lines.append("")
        lines.append("L%d:" % i)
        for name in sorted(members):
            outs = sorted(out_edges.get(name, ()))
            if outs:
                lines.append("  %s -> %s" % (name, ", ".join(outs)))
            else:
                lines.append("  %s" % name)
    if broken:
        lines.append("")
        lines.append("UNPARSEABLE:")
        for name in sorted(broken):
            lines.append("  %s" % name)
    return "\n".join(lines) + "\n"


# --- guide drift --------------------------------------------------------------
_GUIDE_HEADING = "## 1a. Module map (generated)"
# _HERE is plugins/audit/scripts; the guide lives at the repo root, three levels up
# (scripts -> audit -> plugins -> repo root) - same anchor `_help._AGENT_DOCS` uses
# from `plugins/audit` (two levels up from there).
_GUIDE_REL_PATH = os.path.join("..", "..", "..", "PLUGIN-BUILD-GUIDE.md")


def _guide_path(guide_path=None):
    if guide_path is not None:
        return guide_path
    return os.path.join(_HERE, _GUIDE_REL_PATH)


def _fenced_block_after(text, heading):
    """The content of the first fenced code block after `heading`, or None.

    `None` distinguishes "no such heading" from "heading present, no fence" -
    `map_drift` needs to tell those two apart and name each one differently.
    Returns `(block_text, "missing fence")` is NOT the shape; callers get either
    a string (the block content, without the fence lines) or `None`.
    """
    idx = text.find(heading)
    if idx == -1:
        return None
    rest = text[idx + len(heading):]
    fence_start = rest.find("```")
    if fence_start == -1:
        return None
    after_open = rest[fence_start + 3:]
    nl = after_open.find("\n")
    if nl == -1:
        return None
    after_open = after_open[nl + 1:]
    fence_end = after_open.find("```")
    if fence_end == -1:
        return None
    return after_open[:fence_end]


def map_drift(guide_path=None):
    """[(guide-relative-path, problem), ...] - the guide's module map against
    the REAL `render()` output, the same "a doc block must match the code's own
    statement" pattern `_areas.rule_drift()` uses for the reviewSkill rule.

    Three named ways this drifts: the heading itself has gone missing (the
    section was renamed or deleted), the heading survives but nothing under it
    is a fenced block any more, or a fence is there but its content is stale -
    one byte different from what `render()` says right now is still drift.
    """
    path = _guide_path(guide_path)
    rel = "PLUGIN-BUILD-GUIDE.md" if guide_path is None else path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [(rel, "unreadable: %s" % exc)]

    if _GUIDE_HEADING not in text:
        return [(rel, "heading %r not found in the guide" % _GUIDE_HEADING)]

    block = _fenced_block_after(text, _GUIDE_HEADING)
    if block is None:
        return [(rel, "heading %r found but no fenced code block follows it"
                  % _GUIDE_HEADING)]

    expected = render()
    if block != expected:
        return [(rel, "the guide's module map fence does not match "
                  "`_deps.py --render` output byte-for-byte (stale - "
                  "regenerate with `python3 plugins/audit/scripts/"
                  "_deps.py --render`)")]
    return []


# The hooks rule, as the guide has to state it. Two halves, and the second is the
# one F11 was about: the required sentence ALONE sat happily beside a paragraph
# that then carved an allowance out of it ("One known pre-existing exception
# (`hooks/_config.py`'s guarded `import _manifest_io`) is named rather than papered
# over"), so the guide went on describing an exception for as long as it took
# somebody to notice. A rule and its exception in prose are two statements, and
# only one of them was ever checked.
# Scoped to one SENTENCE (`[^.]*` spans no full stop), so the paragraph may still
# recount what the exception was and why it went - which the guide does. A rewrite
# that puts "exception" back in the same sentence as the file goes red, and that is
# the right answer: it is the shape the stale claim had.
_GUIDE_HOOKS_RULE = "hooks/ may import nothing from scripts/ at all"
_GUIDE_HOOKS_EXCUSE = re.compile(
    r"exception[^.]*hooks/_config\.py|hooks/_config\.py[^.]*exception", re.I)


def hooks_rule_drift(guide_path=None):
    """[(guide-relative-path, problem), ...] - the guide against the rule this
    module actually enforces for hooks/.

    The same "a doc must match the code's own statement" pattern as `map_drift`
    and `_areas.rule_drift`, aimed at the one claim neither of them covers: there
    is no allow-list here any more, so no document may describe one."""
    path = _guide_path(guide_path)
    rel = "PLUGIN-BUILD-GUIDE.md" if guide_path is None else path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [(rel, "unreadable: %s" % exc)]
    out = []
    if _GUIDE_HOOKS_RULE not in text:
        out.append((rel, "does not state the hooks rule as %r"
                    % _GUIDE_HOOKS_RULE))
    hit = _GUIDE_HOOKS_EXCUSE.search(text)
    if hit:
        out.append((rel, "still describes an exception to it, and there is none: "
                    "%r" % hit.group(0)[:90]))
    return out


_TREE_HEADING = "## 1. Directory tree"
_SECTION2_HEADING = "## 2. File-by-file logic"


def _section_text(text, heading):
    """The text between `heading` and the next top-or-second-level `##` heading
    (or end of file), NOT including `heading` itself.

    Returns None if `heading` is not found - the same "distinguish missing from
    empty" shape `_fenced_block_after` uses, for the same reason: a caller needs
    to tell "no such section" from "section present but empty" apart.
    """
    idx = text.find(heading)
    if idx == -1:
        return None
    rest = text[idx + len(heading):]
    nxt = rest.find("\n## ")
    return rest if nxt == -1 else rest[:nxt]


def _real_source_files(script_dir=None, hooks_dir=None):
    """Sorted `(relname, kind, path)` for every hooks/**.py and scripts/**.py file.

    `relname` is relative to its OWN directory and forward-slashed
    (`usage/core.py`), which is what a violation should print; `kind` is
    `"scripts"` or `"hooks"`, which callers need only for readable messages, not
    for the matching rule itself (a filename is a filename regardless of which
    directory it lives in); `path` is carried because the walk already knows it
    and a caller rebuilding it from a relname is a second place to get it wrong.

    Recursive, via `_output.py_files`. A missing hooks/ directory is skipped
    explicitly rather than left to `os.walk`, which yields nothing for a path
    that does not exist and would make "no hooks at all" indistinguishable from
    "hooks, all clean".
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    out = [(rel, "scripts", path) for rel, path in _output.py_files(script_dir)]
    if os.path.isdir(hooks_dir):
        out.extend((rel, "hooks", path) for rel, path in _output.py_files(hooks_dir))
    return out


def guide_enumeration(guide_path=None, script_dir=None, hooks_dir=None):
    """[(filename, problem), ...] - every scripts/hooks .py file the guide's
    enumeration sections have gone out of step with.

    Two things are checked, and each names its own violation:

      * TREE COVERAGE. Every real `hooks/*.py` and `scripts/*.py` basename must
        appear as a literal substring somewhere in the fenced code block under
        "## 1. Directory tree" - the tree is meant to be a full inventory (one
        line per file, at the neighbors' granularity), so a file absent from it
        is a file the tree no longer lists at all.

      * SECTION-2 COVERAGE. Every real file must have its basename appear in at
        least one `### ` heading line under "## 2. File-by-file logic" (up to
        the next `## ` heading). The match rule is deliberately pragmatic, not
        "one heading per file": several files legitimately share a single
        heading today (`_manifest_io.py` + `migrate-manifest.py` +
        `commands/migrate.md` share one heading, `render-report.py` +
        `_report_ui.py`'s split is folded into render-report's own heading) -
        "the filename appears in SOME ### heading" is the rule this function
        enforces, stated here because that is the only place it needs to be.

    A missing heading OR missing tree entry is reported once per file, in
    `_real_source_files()` order (scripts before hooks, each alphabetical).

    SCOPED TO `scripts/` + `hooks/`, AND `tests/` IS DELIBERATELY OUT. Section 2 is
    "File-by-file logic" because each of those files answers a question a reader of the
    PRODUCT has - what does `_areas.py` decide, what does `require-plan.py` refuse. A
    test file answers no such question: it is the cases of the file beside it, and its
    entry would say so 47 times. What the guide owes instead is ONE section describing
    `tests/` - the harness, the naming rule, the transformation - which is a thing a
    reader genuinely needs and which no per-file enumeration would ever produce.
    Widening this function would make that one section 48, and would put the guide's
    length in the way of finishing the migration.

    MATCHED BY BASENAME, REPORTED BY RELNAME. A directory tree draws a nested
    file as an indented `core.py` under a `usage/` line, not as the string
    `usage/core.py`, so demanding the relname would fail a correctly drawn tree;
    and a basename is unambiguous here because `layer_violations()` fails a tree
    in which two files share one (see `_module_files`). The violation still names
    the relname, because that is the thing the reader has to go and open.
    """
    path = _guide_path(guide_path)
    rel = "PLUGIN-BUILD-GUIDE.md" if guide_path is None else path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        return [(rel, "unreadable: %s" % exc)]

    tree_block = _fenced_block_after(text, _TREE_HEADING)
    section2 = _section_text(text, _SECTION2_HEADING)
    headings = re.findall(r"^### .*$", section2, re.M) if section2 is not None else []

    violations = []
    for rel, _kind, _path in _real_source_files(script_dir, hooks_dir):
        base = os.path.basename(rel)
        if tree_block is None or base not in tree_block:
            violations.append((rel, "missing from the '%s' tree" % _TREE_HEADING))
        if not any(base in h for h in headings):
            violations.append((rel, "no '### ' heading in '%s' mentions it"
                                % _SECTION2_HEADING))
    return violations


# --- navigability -------------------------------------------------------------
# 400 lines is where a flat scroll stops being a map a reader can hold in their
# head - past this a file needs real `# --- name ---` section headers to stay
# navigable, the same house style `usage_ledger.py` / `audit-status.py` /
# `hooks/_config.py` already carry.
_NAV_MIN_LINES = 400

_NAV_HEADER_RE = re.compile(r"^# --- (.+?) -+\s*$")


def navigability_violations(script_dir=None, hooks_dir=None):
    """(filename, problem) for every long .py file that is not carrying enough
    real section headers to be navigable.

    "Long" is `_NAV_MIN_LINES` or more; "enough" is at least 2 top-level (column
    0, unindented) `# --- name ---` headers OTHER than `# --- selftest ---` -
    the same house-style marker `usage_ledger.py` and this module's own new
    headers use. A header buried inside a function (the indented sub-comments a
    selftest sometimes carries to label its own case groups) does not count:
    it is not a landmark a reader scanning the LEFT MARGIN can find. Only
    `# --- selftest ---` itself is exempt from the count - a file's own test
    block does not make its PRODUCTION code any easier to navigate.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    violations = []
    for rel, _kind, path in _real_source_files(script_dir, hooks_dir):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) < _NAV_MIN_LINES:
            continue
        headers = 0
        for line in lines:
            m = _NAV_HEADER_RE.match(line)
            if m and m.group(1).strip() != "selftest":
                headers += 1
        if headers < 2:
            violations.append((rel,
                                "%d lines but only %d non-selftest section header(s) "
                                "(# --- name ---); needs >= 2 to be navigable"
                                % (len(lines), headers)))
    return violations


# --- ui navigability ----------------------------------------------------------
# The same rule as above for the assets under scripts/ui/, which the .py lint
# cannot see: its file list is `scripts/*.py` + `hooks/*.py`, so the four files
# that carry the entire report and panel UI have never been checked by anything.
#
# The threshold is a DENSITY here rather than a flat 2. Two headers is a real
# floor in a 600-line module and means nothing in a 4,500-line script, and these
# assets run 2-11x longer than the longest .py in the tree - the .py rule was
# written for files that top out around 2,600 lines. One landmark per
# `_NAV_MIN_LINES`, with 2 still the minimum, keeps one rule and one constant.
#
# Markers are the comment syntax each language already uses here:
#   report.css   /* ---- base ---------- */
#   panel.js     // ---------- Settings ----------
# Up to two leading spaces count, because report.js wraps its whole body in an
# IIFE and column 0 is therefore unavailable to it. A marker indented deeper
# than that sits inside a function and is not a landmark the left margin gives
# you - the same reason the .py rule insists on column 0.
_UI_DIR = os.path.join(_HERE, "ui")

_UI_MARKER_RES = (
    (".css", re.compile(r"^/\*\s+-{2,}\s+(.+?)\s+-{2,}")),
    (".js", re.compile(r"^ {0,2}//\s+-{2,}\s+(.+?)\s+-{2,}")),
)


def ui_navigability_violations(ui_dir=None):
    """(filename, problem) for every long scripts/ui/ asset carrying too few
    section markers to be navigable.

    "Long" is `_NAV_MIN_LINES` or more, the same constant the .py rule uses;
    "enough" is one marker per `_NAV_MIN_LINES` lines, never fewer than 2.
    Files below the line threshold are not checked at all, and any extension
    without a marker syntax in `_UI_MARKER_RES` (`.html`, and whatever else
    lands there) is skipped rather than guessed at.
    """
    ui_dir = ui_dir if ui_dir is not None else _UI_DIR
    violations = []
    try:
        names = sorted(os.listdir(ui_dir))
    except OSError:
        return violations
    for name in names:
        rex = None
        for ext, candidate in _UI_MARKER_RES:
            if name.endswith(ext):
                rex = candidate
                break
        if rex is None:
            continue
        try:
            with open(os.path.join(ui_dir, name), "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) < _NAV_MIN_LINES:
            continue
        markers = sum(1 for line in lines if rex.match(line))
        want = max(2, -(-len(lines) // _NAV_MIN_LINES))
        if markers < want:
            violations.append((name,
                                "%d lines but only %d section marker(s); needs "
                                ">= %d (one per %d lines) to stay navigable"
                                % (len(lines), markers, want, _NAV_MIN_LINES)))
    return violations


# --- known layer debt ---------------------------------------------------------
# The 21 edges that became visible the moment this module learned to read
# `_loader` calls. NONE of them is new: every one has been in the tree for
# months, certified clean by a lint that walked only `ast.Import` while most of
# this codebase reaches its siblings at runtime. The lint was not wrong, it was
# blind, and `layer_violations()` reported zero over a tree with 34 runtime edges.
#
# They are two different problems and want two different answers:
#
#   * SEVEN are real inversions - a helper reaching UP to an entry point.
#     `_panel_state` (L5) reaching audit-lock / audit-status / render-report /
#     validate-*, `_help` (L3) reaching audit-journal, `_panel_settings` (L2)
#     reaching validate-config. These are debt, and the refactor retires them by
#     giving the shared thing a home low enough to import - e.g. the lock-name
#     grammar into an L1 `_locks.py` rather than `_panel_state` reimplementing
#     `audit-lock`.
#
#   * THIRTEEN are entry point -> entry point. All thirteen commands sit at L7,
#     so one command reusing another is a "peer" edge BY CONSTRUCTION. Whether
#     that is a defect or a gap in the model is an open architecture question
#     this list does not pretend to have answered.
#
# THE LIST MAY ONLY SHRINK. `r2` asserts EXACT equality, so a new violation fails
# the build, and retiring one also fails it until the entry is deleted on purpose.
# An allowlist that silently absorbs both directions is how debt becomes
# permanent; this one cannot, because fixing something breaks it too.
KNOWN_LAYER_DEBT = (
    # -- upward inversions: a helper reaching an entry point (7) --
    ("_help.py",
     "runtime-loads audit-journal (layer 7) from layer 3 - not strictly downward"),
    ("_panel_settings.py",
     "runtime-loads validate-config (layer 7) from layer 2 - not strictly downward"),
    ("_panel_state.py",
     "runtime-loads audit-lock (layer 7) from layer 5 - not strictly downward"),
    ("_panel_state.py",
     "runtime-loads audit-status (layer 7) from layer 5 - not strictly downward"),
    ("_panel_state.py",
     "runtime-loads render-report (layer 7) from layer 5 - not strictly downward"),
    ("_panel_state.py",
     "runtime-loads validate-config (layer 7) from layer 5 - not strictly downward"),
    ("_panel_state.py",
     "runtime-loads validate-manifest (layer 7) from layer 5 - not strictly downward"),
    # -- entry point reusing an entry point, all at L7 (13) --
    ("audit-doctor.py",
     "runtime-loads audit-journal (layer 7) from layer 7 - not strictly downward"),
    ("audit-doctor.py",
     "runtime-loads audit-lock (layer 7) from layer 7 - not strictly downward"),
    ("audit-doctor.py",
     "runtime-loads audit-status (layer 7) from layer 7 - not strictly downward"),
    # audit-doctor -> gen-demo-manifest was RETIRED when that file's `--selftest`
    # moved to `tests/test_audit_doctor.py`: the ONE `_load(...)` call naming it
    # built the sharded-layout fixture and lived inside the suite. Measured per
    # call site by AST rather than assumed - the other five audit-doctor edges
    # below and above each keep at least one PRODUCTION site, which is why only
    # this one went. A test file has no position in the product's import order
    # (`tests/` is deliberately absent from LAYERS), so the edge is gone from the
    # tree and the entry had to go with it - r2 fails on a RETIRED entry exactly
    # as it fails on a new one, and the list may only shrink, deliberately.
    ("audit-doctor.py",
     "runtime-loads validate-config (layer 7) from layer 7 - not strictly downward"),
    ("audit-doctor.py",
     "runtime-loads validate-manifest (layer 7) from layer 7 - not strictly downward"),
    ("audit-status.py",
     "runtime-loads validate-manifest (layer 7) from layer 7 - not strictly downward"),
    ("audit-usage.py",
     "runtime-loads audit-lock (layer 7) from layer 7 - not strictly downward"),
    ("gen-demo-manifest.py",
     "runtime-loads gen-demo-usage (layer 7) from layer 7 - not strictly downward"),
    # gen-demo-manifest -> validate-config and -> validate-manifest were RETIRED
    # when that file's `--selftest` moved to `tests/test_gen_demo_manifest.py`:
    # the only `_loader.load_script` calls naming those two lived in the suite,
    # and a test file has no position in the product's import order (`tests/` is
    # deliberately absent from LAYERS). The edges are gone from the tree, so the
    # entries had to go with them - r2 fails on a RETIRED entry exactly as it
    # fails on a new one, and the list may only shrink, deliberately.
    ("migrate-manifest.py",
     "runtime-loads validate-manifest (layer 7) from layer 7 - not strictly downward"),
    ("render-report.py",
     "runtime-loads audit-status (layer 7) from layer 7 - not strictly downward"),
)


# --- selftest -----------------------------------------------------------------
def _selftest():
    import shutil
    import tempfile

    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # ------------------------------------------------------------- real tree, green cases
    real_edges, real_broken = import_graph()
    real_violations = layer_violations()
    by_what = lambda needle: [v for v in real_violations if needle in v[1]]  # noqa: E731

    check("r1 the real scripts/ tree is acyclic: %r" % (real_violations,),
          not by_what("import cycle"))
    _downward = tuple(sorted(by_what("not strictly downward")))
    _new = [v for v in _downward if v not in KNOWN_LAYER_DEBT]
    _gone = [v for v in KNOWN_LAYER_DEBT if v not in _downward]
    check("r2 the not-strictly-downward edges are EXACTLY the %d recorded in "
          "KNOWN_LAYER_DEBT. A new one fails here; RETIRING one fails here too, "
          "until its entry is deleted on purpose - the list may only shrink, and "
          "only deliberately. new=%r retired=%r"
          % (len(KNOWN_LAYER_DEBT), _new, _gone),
          not _new and not _gone)
    check("r3 every real scripts/*.py file is assigned a layer, and LAYERS carries no "
          "stale entry: %r" % (real_violations,),
          not by_what("not assigned a layer") and not by_what("stale table entry"))
    check("r4 every real scripts/*.py file parses: %r" % (real_broken,), not real_broken)

    # Read the RAW hooks scan directly as well as through layer_violations(). The raw list
    # is what NAMES an offender; the filtered one is what a build reads. They were two
    # different facts while an allow-list sat between them, and the point of removing it is
    # that they are now one - so both are asserted, and a suppression reintroduced anywhere
    # in between makes exactly one of them fail.
    real_modules, real_collisions = _module_files(_HERE)
    real_on_disk = set(real_modules)
    real_hooks_raw = [(f, m) for f, m in _hooks_scripts_imports(_HOOKS_DIR, real_on_disk)
                       if m is not None]
    check("r5 hooks/ statically imports nothing from scripts/ AT ALL - no allow-list, no "
          "documented exception, because the one there was is fixed (F11): a hook runs on "
          "every tool call from a process that may not have scripts/ on its path, so every "
          "scripts/-owned feature is loaded by path and treated as optional: %r"
          % (real_hooks_raw,),
          real_hooks_raw == [])
    check("r5b ...and layer_violations() says the same thing rather than filtering it - the "
          "raw scan and the reported one are one fact now, not two",
          not by_what("imports scripts module"))

    check("r6 real edge count is positive - a checker that finds zero edges on a tree "
          "this size is reading the wrong directory, not a clean graph: %d"
          % len(real_edges), len(real_edges) > 0)

    real_static, real_runtime, _rb = _scan_edges()
    check("r7 the `_loader` runtime edges are actually being READ, and they are edges "
          "the import walk does not already have (%d runtime, %d static, %d runtime-only): "
          "every entry point in this tree is hyphenated and therefore cannot be reached "
          "by an `import` statement at all, so a scan that finds none of them here is "
          "reading static imports only - the state in which r2 certified this tree while "
          "seeing a fraction of it"
          % (len(real_runtime), len(real_static), len(real_runtime - real_static)),
          real_runtime and (real_runtime - real_static))

    real_hook_modules = {}
    real_hook_collisions = []
    if os.path.isdir(_HOOKS_DIR):
        real_hook_modules, real_hook_collisions = _module_files(_HOOKS_DIR)
    real_hook_names = set(real_hook_modules)
    check("r8 no hooks/**.py basename collides with a scripts/**.py one. The runtime-load "
          "rule reads a literal's BASENAME and ignores its directory (audit-doctor loads "
          "`../hooks/_config.py` and `../hooks/guard-capabilities.py` by path), so the "
          "day both directories carry the same filename a hooks load would be recorded "
          "as a scripts edge. That precondition is asserted here rather than assumed in "
          "a comment: %r" % (sorted(real_hook_names & real_on_disk),),
          not (real_hook_names & real_on_disk))
    check("r8b ...and no basename collides WITHIN either directory either. Both scans "
          "are recursive now, so `usage/core.py` beside `panel/core.py` is a shape the "
          "tree can take - and it would be one node in the graph wearing two files' "
          "edges, and one ambiguous name for `guide_enumeration` to match on. scripts=%r "
          "hooks=%r" % (real_collisions, real_hook_collisions),
          not real_collisions and not real_hook_collisions)

    # -------------------------------------------------------- render: format + determinism
    render_a = render()
    render_b = render()
    check("d1 --render is deterministic: two calls on the same tree are byte-identical",
          render_a == render_b)
    check("d2 the rendered map names every layer this module defines",
          all(("L%d:" % i) in render_a for i in range(len(LAYERS))))
    check("d3 the rendered map ends with a trailing newline (clean CLI output)",
          render_a.endswith("\n") and not render_a.endswith("\n\n"))

    # ----------------------------------------------------- fixtures: each violation named
    tmp = tempfile.mkdtemp(prefix="audit-deps-")
    try:
        # a cycle: two files that import each other.
        cyc = os.path.join(tmp, "cycle")
        os.makedirs(cyc)
        with open(os.path.join(cyc, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("import b\n")
        with open(os.path.join(cyc, "b.py"), "w", encoding="utf-8") as fh:
            fh.write("import a\n")
        cyc_layers = (("a",), ("b",))  # a table that would (wrongly) call this acyclic
        hits = layer_violations(cyc, hooks_dir=tmp, layers=cyc_layers)
        cyc_hits = [v for v in hits if v[1].startswith("import cycle")]
        check("f1 a real import cycle is named as a cycle, with the path in the message",
              len(cyc_hits) == 1 and "a" in cyc_hits[0][1] and "b" in cyc_hits[0][1])

        # an upward import: the lower layer imports the higher one.
        up = os.path.join(tmp, "upward")
        os.makedirs(up)
        with open(os.path.join(up, "low.py"), "w", encoding="utf-8") as fh:
            fh.write("import high\n")
        with open(os.path.join(up, "high.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        up_layers = (("low",), ("high",))  # low is BELOW high; low importing high is up
        up_hits = layer_violations(up, hooks_dir=tmp, layers=up_layers)
        up_named = [v for v in up_hits if v[0] == "low.py"
                    and "not strictly downward" in v[1]]
        check("f2 an upward import (a lower layer importing a higher one) is named, "
              "with both layer numbers in the message: %r" % (up_hits,),
              len(up_named) == 1 and "layer 0" in up_named[0][1]
              and "layer 1" in up_named[0][1])

        # an unassigned file: on disk, absent from LAYERS.
        unassigned = os.path.join(tmp, "unassigned")
        os.makedirs(unassigned)
        with open(os.path.join(unassigned, "known.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(unassigned, "orphan.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        orphan_layers = (("known",),)
        orphan_hits = layer_violations(unassigned, hooks_dir=tmp, layers=orphan_layers)
        check("f3 a file on disk with no LAYERS entry is named as unassigned: %r"
              % (orphan_hits,),
              any(v == ("orphan.py", "on disk but not assigned a layer in LAYERS")
                  for v in orphan_hits))
        stale_layers = (("known",), ("ghost",))
        stale_hits = layer_violations(unassigned, hooks_dir=tmp, layers=stale_layers)
        check("f3b a LAYERS entry with no file on disk is named as stale, the other "
              "direction of the same drift: %r" % (stale_hits,),
              any(v[0] == "ghost.py" and "stale table entry" in v[1]
                  for v in stale_hits))

        # hooks importing a scripts module: the banned direction.
        hooksfix = os.path.join(tmp, "hooksfix")
        os.makedirs(hooksfix)
        with open(os.path.join(hooksfix, "sneaky.py"), "w", encoding="utf-8") as fh:
            fh.write("import _fmt\n")  # _fmt is a real scripts/ module name
        with open(os.path.join(hooksfix, "_config.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")  # a hook's own sibling, never flagged
        hook_hits = layer_violations(script_dir=_HERE, hooks_dir=hooksfix)
        check("f4 hooks/*.py importing a real scripts/ module name is named, with the "
              "hook file and the module both in the message: %r" % (hook_hits,),
              any(v == ("sneaky.py", "imports scripts module _fmt - hooks must not "
                        "depend on scripts") for v in hook_hits))
        check("f5 a hook importing its OWN sibling (_config) is not flagged - only a "
              "real scripts/ module name is banned",
              not any(v[0] == "_config.py" and "imports scripts module" in v[1]
                      for v in hook_hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------- runtime loads: the `_loader` call shapes
    # The edges the graph could not see AT ALL until now. Every shape below was read off
    # the real tree first (`_loader.load_script("x.py")`, the `_ldr` alias in
    # validate-config.py's selftest, the three `_load(...)` wrappers, and the one call
    # whose target is bound to a name before the call) - a fixture invented from the same
    # head that wrote the parser proves only that the head is self-consistent.
    rt = tempfile.mkdtemp(prefix="audit-deps-runtime-")
    try:
        rt_hooks = os.path.join(rt, "hooks")  # empty; the hooks pass is not under test
        os.makedirs(rt_hooks)
        rt_src = os.path.join(rt, "scripts")
        os.makedirs(rt_src)

        def _rt_write(name, body):
            with open(os.path.join(rt_src, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        # No _loader.py in the fixture, on purpose: if `_loader` were a sibling here,
        # `import _loader` would ALSO be a static edge and these cases could pass on the
        # import walk alone, proving nothing about the call walk.
        _rt_write("high.py", "pass\n")
        _rt_write("bottom.py", "pass\n")
        _rt_write("low.py",
                  "import _loader\n"
                  "def go():\n"
                  "    return _loader.load_script('high.py', modname='high')\n")
        _rt_write("aliased.py",
                  "import _loader as _ldr\n"
                  "def go():\n"
                  "    return _ldr.load(os.path.join(_HERE, 'high.py'), modname='high')\n")
        _rt_write("wrapped.py",
                  "import _loader\n"
                  "def _load(name, filename):\n"
                  "    return _loader.load_script(filename, modname=name)\n"
                  "def go():\n"
                  "    return _load('high', 'high.py')\n")
        _rt_write("computed.py",
                  "import _loader\n"
                  "TARGET = 'high.py'\n"
                  "def go():\n"
                  "    return _loader.load_script(TARGET)\n")
        _rt_write("top.py",
                  "import _loader\n"
                  "def go():\n"
                  "    return _loader.load_script('bottom.py', modname='bottom')\n")
        # low/aliased/wrapped/computed sit BELOW high; top sits ABOVE bottom. One table
        # carries both directions so a single call has to get both of them right.
        rt_layers = (("aliased", "bottom", "computed", "low", "wrapped"),
                      ("high", "top"))
        rt_hits = layer_violations(rt_src, hooks_dir=rt_hooks, layers=rt_layers)
        rt_by_file = lambda name: [v for v in rt_hits if v[0] == name]  # noqa: E731

        check("rt1 a runtime `_loader.load_script('high.py')` from a LOWER layer is named "
              "as an upward edge - the whole class of edge the import-only walk could not "
              "see - and the message says runtime-loads, not imports, because there is no "
              "import line for the reader to go and find: %r" % (rt_hits,),
              len([v for v in rt_by_file("low.py")
                   if "runtime-loads high (layer 1) from layer 0" in v[1]]) == 1)

        check("rt2 the alias form (`import _loader as _ldr`, which validate-config.py's "
              "selftest really uses) is seen, and so is a literal nested inside an "
              "`os.path.join(...)` argument - the shape `_panel_state` and `audit-doctor` "
              "spell most of their loads with: %r" % (rt_hits,),
              len([v for v in rt_by_file("aliased.py")
                   if "runtime-loads high" in v[1]]) == 1)

        check("rt3 a local wrapper that forwards a caller-chosen filename is followed to "
              "its CALL SITE, where the filename is actually spelled - without this the "
              "~20 `_load(...)` sites in audit-doctor alone are invisible: %r" % (rt_hits,),
              len([v for v in rt_by_file("wrapped.py")
                   if "runtime-loads high" in v[1]]) == 1)

        check("rt4 a target that is not a literal IN the call (bound to a name first) is "
              "NOT guessed at. The documented limitation, asserted so it stays a decision "
              "on record; it is also the OTHER-direction case, going red the day detection "
              "is widened to 'any .py literal anywhere in the file', which would invent "
              "edges out of error messages and docstrings: %r" % (rt_hits,),
              rt_by_file("computed.py") == [])

        check("rt5 control: a LEGAL downward runtime load (top -> bottom) is left alone. "
              "The rule fires on DIRECTION, not on the presence of a load, and this is "
              "the only case that goes red if it ever becomes unconditional - which would "
              "flag every one of the ~13 correct downward loads in the real tree: %r"
              % (rt_hits,), rt_by_file("top.py") == [])

        # ---- mutation proof: the pre-change graph must MISS these same fixtures ----
        # The graph as it stood before the runtime pass existed: edges from `ast.Import` /
        # `ast.ImportFrom` only. Everything else is today's code - including the recursive
        # `_module_files` walk - so exactly ONE variable is removed and a red rt6 can only
        # be about that one. It reports nothing at all here, which is precisely how it
        # reported nothing on a real tree carrying twenty-one bad edges.
        def _static_only_layer_violations(script_dir, layers):
            names, _dupes = _module_files(script_dir)
            found = []
            for mod in sorted(names):
                rel, path = names[mod][0]
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
                for imported in _imported_sibling_names(tree, set(names), mod):
                    li = _layer_of(mod, layers)
                    lj = _layer_of(imported, layers)
                    if li is not None and lj is not None and not (li > lj):
                        found.append((mod + ".py", "imports %s - not strictly downward"
                                      % imported))
            return found

        weak_rt_hits = _static_only_layer_violations(rt_src, rt_layers)
        check("rt6 mutation proof: with the runtime pass removed (the static-import walk "
              "this change replaced, and nothing else changed with it), the SAME three "
              "fixtures rt1-rt3 catch are "
              "missed ENTIRELY - red here proves those three cases test something real "
              "rather than passing however the check were written: %r" % (weak_rt_hits,),
              weak_rt_hits == [])

        rt_again = layer_violations(rt_src, hooks_dir=rt_hooks, layers=rt_layers)
        check("rt7 mutation proof: the real, unweakened check still catches all THREE - "
              "counted, not merely found, so a version that spots one upward load and "
              "drops the other two cannot pass this; nothing was left mutated behind: %r"
              % (rt_again,),
              len([v for v in rt_again if "runtime-loads" in v[1]]) == 3)
    finally:
        shutil.rmtree(rt, ignore_errors=True)

    # --------------------------------------------------- map_drift: guide vs --render output
    check("g1 the shipped guide's module map fence matches `_deps.py --render` "
          "byte-for-byte right now - the house 'a doc block must match the code's own "
          "statement' pattern `_areas.rule_drift()` uses, applied to this generated "
          "block: %r" % (map_drift(),), not map_drift())

    # ---------------------------------------------- hooks_rule_drift: guide vs the rule
    # The generated map has a byte lint; the SENTENCE beside it had nothing, and that is
    # how the guide went on naming an exception (`hooks/_config.py`'s guarded
    # `import _manifest_io`) that no longer exists. Both halves are asserted against
    # fixtures below, because a lint that only requires the sentence is green for a
    # document that states the rule and then takes it back in the next clause.
    check("g0 the shipped guide states the hooks rule and claims no exception to it: %r"
          % (hooks_rule_drift(),), not hooks_rule_drift())

    rule_tmp = tempfile.mkdtemp(prefix="audit-deps-rule-")
    try:
        silent_path = os.path.join(rule_tmp, "no-rule.md")
        with open(silent_path, "w", encoding="utf-8") as fh:
            fh.write("# guide\n\nhooks are lovely and nothing is said about imports.\n")
        silent_hits = hooks_rule_drift(silent_path)
        check("g0a a guide that never states the rule is drift: %r" % (silent_hits,),
              len(silent_hits) == 1 and "does not state" in silent_hits[0][1])

        excuse_path = os.path.join(rule_tmp, "excused.md")
        with open(excuse_path, "w", encoding="utf-8") as fh:
            fh.write("# guide\n\n...and " + _GUIDE_HOOKS_RULE + ". One known "
                     "pre-existing exception (`hooks/_config.py`'s guarded "
                     "`import _manifest_io`) is named rather than papered over.\n")
        excuse_hits = hooks_rule_drift(excuse_path)
        check("g0b ...and so is a guide that states it and then carves an allowance out "
              "of it - which is exactly what shipped until F11, with the sentence above "
              "it correct the whole time: %r" % (excuse_hits,),
              len(excuse_hits) == 1 and "still describes an exception" in excuse_hits[0][1])

        missing_rule_path = os.path.join(rule_tmp, "gone.md")
        check("g0c an unreadable guide is reported, not treated as a clean one",
              [p for _, p in hooks_rule_drift(missing_rule_path) if "unreadable" in p])
    finally:
        shutil.rmtree(rule_tmp, ignore_errors=True)

    guide_tmp = tempfile.mkdtemp(prefix="audit-deps-guide-")
    try:
        real_render = render()

        stale_path = os.path.join(guide_tmp, "stale.md")
        with open(stale_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n" + _GUIDE_HEADING + "\n\nsome text\n\n```\n"
                      + real_render[:-2] + "X\n```\n\nmore text\n")  # one byte changed
        stale_hits = map_drift(stale_path)
        check("g2 a fenced block one byte off from the real `render()` output is named "
              "as stale, not silently accepted: %r" % (stale_hits,),
              len(stale_hits) == 1 and stale_hits[0][0] == stale_path
              and "does not match" in stale_hits[0][1])

        no_heading_path = os.path.join(guide_tmp, "no_heading.md")
        with open(no_heading_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n## something else entirely\n\n```\n" + real_render + "```\n")
        no_heading_hits = map_drift(no_heading_path)
        check("g3 a guide missing the module-map heading entirely is named, not "
              "mistaken for a match: %r" % (no_heading_hits,),
              len(no_heading_hits) == 1
              and "heading" in no_heading_hits[0][1]
              and "not found" in no_heading_hits[0][1])

        no_fence_path = os.path.join(guide_tmp, "no_fence.md")
        with open(no_fence_path, "w", encoding="utf-8") as fh:
            fh.write("intro\n\n" + _GUIDE_HEADING + "\n\nno fence follows this heading "
                      "at all, just prose.\n")
        no_fence_hits = map_drift(no_fence_path)
        check("g4 a guide with the heading but no fenced block after it is named as "
              "missing the fence, distinctly from a stale-content mismatch: %r"
              % (no_fence_hits,),
              len(no_fence_hits) == 1
              and "no fenced code block" in no_fence_hits[0][1])

        missing_path = os.path.join(guide_tmp, "does_not_exist.md")
        missing_hits = map_drift(missing_path)
        check("g5 an unreadable guide path is named as unreadable, not crashed on: %r"
              % (missing_hits,),
              len(missing_hits) == 1 and "unreadable" in missing_hits[0][1])

        # ---- mutation proof: a weakened comparison must MISS the g2 stale fixture ----
        # Same idea as m1/m2 below: a version of the comparison that only checks the
        # block is non-empty (instead of comparing it to `render()`) would let g2's
        # one-byte-off fixture through clean - proving g2 is testing something real.
        def _weakened_map_drift(guide_path):
            path = _guide_path(guide_path)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            if _GUIDE_HEADING not in text:
                return [(path, "heading not found")]
            block = _fenced_block_after(text, _GUIDE_HEADING)
            if block is None:
                return [(path, "no fenced code block")]
            return [] if block else [(path, "empty block")]  # never compares to render()

        weak_stale_hits = _weakened_map_drift(stale_path)
        check("g6 mutation proof: with the byte-for-byte comparison to `render()` "
              "removed, the SAME one-byte-stale fixture g2 catches is missed entirely "
              "(red proves g2 is testing something real): %r" % (weak_stale_hits,),
              not weak_stale_hits)
        real_stale_hits = map_drift(stale_path)
        check("g7 mutation proof: the real, unweakened map_drift() still catches it - "
              "nothing was left mutated behind",
              real_stale_hits and "does not match" in real_stale_hits[0][1])
    finally:
        shutil.rmtree(guide_tmp, ignore_errors=True)

    # ------------------------------------------------------- mutation proof: upward edge
    # Same idea _fmt.py's own selftest proves with a hand-mutated formatter: a weakened
    # version of the check (here, one that simply never looks at layer numbers) must MISS
    # the fixture the real function catches - proving f2 above is testing something real,
    # not a case that would pass however the check were (mis)written.
    mut_dir = tempfile.mkdtemp(prefix="audit-deps-mutant-")
    try:
        with open(os.path.join(mut_dir, "low.py"), "w", encoding="utf-8") as fh:
            fh.write("import high\n")
        with open(os.path.join(mut_dir, "high.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        mut_layers = (("low",), ("high",))

        def _weakened_layer_violations(script_dir, layers):
            # The upward-edge pass, deliberately dropped - everything else kept, so the
            # only thing this proves red is the check f2 depends on.
            edges, _broken = import_graph(script_dir)
            found = []
            cycle = _find_cycle(edges)
            if cycle:
                found.append((cycle[0] + ".py", "import cycle: " + " -> ".join(cycle)))
            return found

        weak_hits = _weakened_layer_violations(mut_dir, mut_layers)
        check("m1 mutation proof: with the upward-edge check removed, the SAME fixture "
              "that f2 catches is missed entirely (red proves the case can fail): %r"
              % (weak_hits,), not weak_hits)
        real_hits = layer_violations(mut_dir, hooks_dir=tmp, layers=mut_layers)
        check("m2 mutation proof: the real, unweakened check still catches it - nothing "
              "was left mutated behind",
              any("not strictly downward" in v[1] for v in real_hits))
    finally:
        shutil.rmtree(mut_dir, ignore_errors=True)

    # ------------------------------------------ guide_enumeration: real guide + fixtures
    check("e1 the real, shipped guide names no scripts/hooks .py file missing from "
          "either the directory tree or a section-2 heading right now: %r"
          % (guide_enumeration(),), not guide_enumeration())

    enum_tmp = tempfile.mkdtemp(prefix="audit-deps-enum-")
    try:
        hk_dir = os.path.join(enum_tmp, "hooks")  # empty; no hooks fixtures needed here
        os.makedirs(hk_dir)

        src_a = os.path.join(enum_tmp, "scripts_a")
        os.makedirs(src_a)
        with open(os.path.join(src_a, "present.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(src_a, "no_section.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")

        complete_guide = os.path.join(enum_tmp, "complete.md")
        with open(complete_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + _TREE_HEADING + "\n\n```\n"
                "  present.py    # a file\n"
                "  no_section.py # another file\n"
                "```\n\n" + _SECTION2_HEADING + "\n\n"
                "### `present.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        complete_hits = guide_enumeration(complete_guide, script_dir=src_a,
                                           hooks_dir=hk_dir)
        check("e2 a file present in the tree but absent from every section-2 heading "
              "is named as missing its section, and ONLY that: %r" % (complete_hits,),
              complete_hits == [("no_section.py",
                                  "no '### ' heading in '%s' mentions it"
                                  % _SECTION2_HEADING)])

        src_b = os.path.join(enum_tmp, "scripts_b")
        os.makedirs(src_b)
        with open(os.path.join(src_b, "present.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")
        with open(os.path.join(src_b, "no_tree.py"), "w", encoding="utf-8") as fh:
            fh.write("pass\n")

        no_tree_guide = os.path.join(enum_tmp, "no_tree.md")
        with open(no_tree_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + _TREE_HEADING + "\n\n```\n"
                "  present.py    # a file\n"
                "```\n\n" + _SECTION2_HEADING + "\n\n"
                "### `present.py`\nprose.\n\n"
                "### `no_tree.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        no_tree_hits = guide_enumeration(no_tree_guide, script_dir=src_b,
                                          hooks_dir=hk_dir)
        check("e3 a file present in every section-2 heading but absent from the tree "
              "is named as missing from the tree, and ONLY that: %r" % (no_tree_hits,),
              no_tree_hits == [("no_tree.py",
                                 "missing from the '%s' tree" % _TREE_HEADING)])

        # ---- mutation proof: a weakened check must MISS the e3 tree-only fixture ----
        def _weakened_guide_enumeration(guide_path):
            with open(guide_path, "r", encoding="utf-8") as fh:
                text = fh.read()
            section2 = _section_text(text, _SECTION2_HEADING)
            headings = (re.findall(r"^### .*$", section2, re.M)
                        if section2 is not None else [])
            found = []
            for rel, _kind, _path in _real_source_files(src_b, hk_dir):
                base = os.path.basename(rel)
                if not any(base in h for h in headings):  # tree check dropped entirely
                    found.append((rel, "no section heading"))
            return found

        weak_hits = _weakened_guide_enumeration(no_tree_guide)
        check("e4 mutation proof: with the tree-coverage check removed, the SAME "
              "tree-missing fixture e3 catches is missed entirely (red proves e3 is "
              "testing something real): %r" % (weak_hits,),
              not any(f == "no_tree.py" for f, _ in weak_hits))
        real_hits_again = guide_enumeration(no_tree_guide, script_dir=src_b,
                                             hooks_dir=hk_dir)
        check("e5 mutation proof: the real, unweakened guide_enumeration() still "
              "catches it - nothing was left mutated behind",
              any(f == "no_tree.py" for f, _ in real_hits_again))
    finally:
        shutil.rmtree(enum_tmp, ignore_errors=True)

    # --------------------------------------------------- navigability_violations
    check("n1 the real tree's long files (>= %d lines) all carry at least 2 "
          "non-selftest section headers - navigability is enforced, not just "
          "declared, with no exceptions left on record: %r"
          % (_NAV_MIN_LINES, navigability_violations()),
          not navigability_violations())

    nav_tmp = tempfile.mkdtemp(prefix="audit-deps-nav-")
    try:
        nav_hooks = os.path.join(nav_tmp, "hooks")  # empty; no hooks fixture needed
        os.makedirs(nav_hooks)
        long_path = os.path.join(nav_tmp, "long_file.py")
        with open(long_path, "w", encoding="utf-8") as fh:
            fh.write("pass\n" * (_NAV_MIN_LINES + 10))
        nav_hits = navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n2 a long file with no section headers at all is named as a "
              "navigability violation: %r" % (nav_hits,),
              any(f == "long_file.py" for f, _ in nav_hits))

        # ---- mutation proof: a weakened check must MISS the n2 fixture ----
        def _weakened_navigability_violations(script_dir, hooks_dir):
            return []  # the header-count check removed entirely

        weak_nav_hits = _weakened_navigability_violations(nav_tmp, nav_hooks)
        check("n3 mutation proof: with the header-count check removed, the SAME "
              "headerless-file fixture n2 catches is missed entirely (red proves "
              "n2 is testing something real): %r" % (weak_nav_hits,),
              not any(f == "long_file.py" for f, _ in weak_nav_hits))
        real_nav_hits_again = navigability_violations(nav_tmp, hooks_dir=nav_hooks)
        check("n4 mutation proof: the real, unweakened navigability_violations() "
              "still catches it - nothing was left mutated behind",
              any(f == "long_file.py" for f, _ in real_nav_hits_again))
    finally:
        shutil.rmtree(nav_tmp, ignore_errors=True)

    # ------------------------------------------------ ui_navigability_violations
    check("u1 the real scripts/ui/ assets (>= %d lines) all carry one section "
          "marker per %d lines - the four files that hold the entire report and "
          "panel UI were unchecked by anything until now: %r"
          % (_NAV_MIN_LINES, _NAV_MIN_LINES, ui_navigability_violations()),
          not ui_navigability_violations())

    ui_tmp = tempfile.mkdtemp(prefix="audit-deps-uinav-")
    try:
        def _write(name, body):
            with open(os.path.join(ui_tmp, name), "w", encoding="utf-8") as fh:
                fh.write(body)

        _JS_MARK = "// --- one -------------------------------------------------\n"
        _CSS_MARK = "/* ---- one ---------------------------------------------- */\n"

        _write("bare.js", "x();\n" * (_NAV_MIN_LINES + 10))
        ui_hits = ui_navigability_violations(ui_tmp)
        check("u2 a long .js with no section markers at all is named as a ui "
              "navigability violation: %r" % (ui_hits,),
              any(f == "bare.js" for f, _ in ui_hits))

        # ---- mutation proof: a weakened check must MISS the u2 fixture ----
        def _weakened_ui_navigability_violations(ui_dir):
            return []  # the marker-count check removed entirely

        weak_ui_hits = _weakened_ui_navigability_violations(ui_tmp)
        check("u3 mutation proof: with the marker-count check removed, the SAME "
              "markerless-file fixture u2 catches is missed entirely (red proves "
              "u2 is testing something real): %r" % (weak_ui_hits,),
              not any(f == "bare.js" for f, _ in weak_ui_hits))
        check("u4 mutation proof: the real, unweakened ui_navigability_violations() "
              "still catches it - nothing was left mutated behind",
              any(f == "bare.js" for f, _ in ui_navigability_violations(ui_tmp)))

        # ---- the density is what does the work, not the floor of 2 ----
        _write("thin.css", _CSS_MARK * 2 + ("a{b:c}\n" * (_NAV_MIN_LINES * 2 + 50)))
        thin_hits = ui_navigability_violations(ui_tmp)
        check("u5 a 900-line asset carrying exactly 2 markers is still named - a "
              "flat 'at least 2' rule (what the .py lint asks) would pass it, so "
              "this is the case that proves the DENSITY is doing the work: %r"
              % (thin_hits,),
              any(f == "thin.css" for f, _ in thin_hits))

        # ---- the other direction: the rule must not fire on a well-marked file.
        # Looks vacuous and is the only case that goes red if the density is ever
        # tightened into something no real asset can satisfy.
        _write("ok.css", _CSS_MARK * 2 + ("a{b:c}\n" * (_NAV_MIN_LINES - 100)))
        _write("short.js", "x();\n" * 100)
        ok_hits = ui_navigability_violations(ui_tmp)
        check("u6 control: a long asset with enough markers, and a short one with "
              "none, are both left alone - the rule fires on too few markers for "
              "the length, not on length or on markers alone: %r" % (ok_hits,),
              not any(f in ("ok.css", "short.js") for f, _ in ok_hits))

        _write("panel.html", "<div>\n" * (_NAV_MIN_LINES + 10))
        check("u7 an extension with no marker syntax on record (.html) is skipped "
              "rather than guessed at",
              not any(f == "panel.html" for f, _ in ui_navigability_violations(ui_tmp)))
    finally:
        shutil.rmtree(ui_tmp, ignore_errors=True)

    # ------------------------------------------- the scanners reach a subdirectory
    # A recursive walk that is never handed a subdirectory proves nothing, so this
    # builds one. Every scanner in this module used a flat `os.listdir`, which is
    # why `CONTRIBUTING.md` had to forbid a `.py` below scripts/ or hooks/: the file
    # did not fail anything, it stopped being scanned and said so nowhere. The
    # fixture puts the offence one level down in each direction - an upward edge in
    # `scripts/usage/`, a banned hooks->scripts import in `hooks/nested/` - and the
    # clean second direction beside each of them.
    rec = tempfile.mkdtemp(prefix="audit-deps-rec-")
    try:
        rec_scripts = os.path.join(rec, "scripts")
        rec_hooks = os.path.join(rec, "hooks")
        for _d in (rec_scripts, rec_hooks,
                   os.path.join(rec_scripts, "usage"),
                   os.path.join(rec_scripts, "panel"),
                   os.path.join(rec_hooks, "nested")):
            os.makedirs(_d)

        def _rec_write(*parts):
            body = parts[-1]
            with open(os.path.join(rec, *parts[:-1]), "w", encoding="utf-8") as fh:
                fh.write(body)

        _rec_write("scripts", "flat_low.py", "pass\n")
        _rec_write("scripts", "high.py", "pass\n")
        # One directory down and UPWARD: L0 reaching L1. The offence.
        _rec_write("scripts", "usage", "core.py", "import high\n")
        # One directory down and DOWNWARD: L1 reaching L0. Legal, and must stay legal.
        _rec_write("scripts", "panel", "clean.py", "import flat_low\n")
        # A hook one directory down importing a scripts module that is ITSELF only
        # findable one directory down - both walks have to work for this to be named.
        _rec_write("hooks", "nested", "sneaky.py", "import core\n")
        _rec_write("hooks", "nested", "fine.py", "import os\n")
        rec_layers = (("core", "flat_low"), ("clean", "high"))

        rec_modules, rec_collisions = _module_files(rec_scripts)
        rec_map = dict((name, [rel for rel, _p in entries])
                       for name, entries in rec_modules.items())
        check("w1 the scripts walk descends into subdirectories, keys each file by its "
              "BASENAME (the only name `import` or `_loader` can spell) and remembers the "
              "relative path to report it by: %r" % (rec_map,),
              rec_map == {"clean": ["panel/clean.py"], "core": ["usage/core.py"],
                          "flat_low": ["flat_low.py"], "high": ["high.py"]})

        rec_hits = sorted(layer_violations(rec_scripts, hooks_dir=rec_hooks,
                                            layers=rec_layers))
        check("w2 the whole violation list is EXACTLY the two offences, one from a "
              "scripts file one directory down and one from a hooks file one directory "
              "down, each NAMED BY ITS RELATIVE PATH rather than by a bare basename the "
              "reader would have to go hunting for. Counted as a whole list, not found "
              "one at a time, so a walk that sees one of the two cannot pass: %r"
              % (rec_hits,),
              rec_hits == [
                  ("nested/sneaky.py",
                   "imports scripts module core - hooks must not depend on scripts"),
                  ("usage/core.py",
                   "imports high (layer 1) from layer 0 - not strictly downward")])
        check("w3 ...and the second direction, which w2's exact list already carries and "
              "this states out loud: a LEGAL downward import from `panel/clean.py`, and a "
              "hook one level down importing only stdlib, are both left alone. Living in "
              "a folder is not the offence - it never was: %r" % (rec_hits,),
              not any(f in ("panel/clean.py", "nested/fine.py") for f, _w in rec_hits))

        rec_edges, rec_broken = import_graph(rec_scripts)
        check("w4 a file one directory down is the node `core`, not `usage/core` - the "
              "name every real edge in this tree is spelled with. Pinned because the "
              "alternative silently matches nothing: %r %r" % (rec_edges, rec_broken),
              rec_edges == [("clean", "flat_low"), ("core", "high")] and not rec_broken)

        # ---- mutation proof: the flat scan this replaced misses both offences ----
        def _flat_relnames(directory):
            """The `os.listdir` these scanners used to call: one level, no walk."""
            return sorted(f for f in os.listdir(directory) if f.endswith(".py"))

        def _flat_layer_violations(script_dir, hooks_dir, layers):
            # `layer_violations()` with ONE thing swapped back - the recursive walk
            # returns to the flat listing. The edge walk, the layer comparison and the
            # hooks rule are all the real ones, so an empty result here is about file
            # discovery and nothing else.
            names = dict((f[:-3], os.path.join(script_dir, f))
                         for f in _flat_relnames(script_dir))
            found = []
            for mod in sorted(names):
                with open(names[mod], "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=mod)
                for imported in _imported_sibling_names(tree, set(names), mod):
                    li = _layer_of(mod, layers)
                    lj = _layer_of(imported, layers)
                    if li is not None and lj is not None and not (li > lj):
                        found.append((mod + ".py",
                                      "imports %s (layer %d) from layer %d - not "
                                      "strictly downward" % (imported, lj, li)))
            for fname in _flat_relnames(hooks_dir):
                with open(os.path.join(hooks_dir, fname), "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=fname)
                for imported in _imported_sibling_names(tree, set(names), None):
                    found.append((fname, "imports scripts module %s - hooks must not "
                                  "depend on scripts" % imported))
            return found

        weak_rec_hits = _flat_layer_violations(rec_scripts, rec_hooks, rec_layers)
        check("w5 mutation proof: with the walk swapped back for the flat `os.listdir` "
              "it replaced, BOTH offences w2 catches are missed entirely - the scan "
              "returns %r and %r and reports a clean tree. That is the exact failure "
              "`CONTRIBUTING.md`'s old flat-files rule existed to avoid: %r"
              % (_flat_relnames(rec_scripts), _flat_relnames(rec_hooks), weak_rec_hits),
              weak_rec_hits == [])
        rec_again = layer_violations(rec_scripts, hooks_dir=rec_hooks, layers=rec_layers)
        check("w6 mutation proof: the real, unweakened check still names both - each "
              "KIND counted separately, so a version that finds the scripts one and "
              "drops the hooks one cannot pass here. Counting the list length alone "
              "would not do it: a flat scan turns those same two files into two "
              "'stale table entry' violations and lands on 2 as well, which is the "
              "shape of a fixture that cannot tell the two implementations apart: %r"
              % (rec_again,),
              len([v for v in rec_again if "not strictly downward" in v[1]]) == 1
              and len([v for v in rec_again if "imports scripts module" in v[1]]) == 1
              and len(rec_again) == 2)

        # ---- guide_enumeration: matched by basename, reported by relative path ----
        rec_guide = os.path.join(rec, "guide.md")
        with open(rec_guide, "w", encoding="utf-8") as fh:
            fh.write(
                "intro\n\n" + _TREE_HEADING + "\n\n```\n"
                "  flat_low.py\n  high.py\n  usage/\n    core.py\n```\n\n"
                + _SECTION2_HEADING + "\n\n"
                "### `flat_low.py`\nprose.\n\n"
                "### `high.py`\nprose.\n\n"
                "### `core.py`\nprose.\n\n"
                "## 3. Next section\nnot part of section 2.\n"
            )
        rec_enum_hooks = os.path.join(rec, "empty_hooks")
        os.makedirs(rec_enum_hooks)
        rec_enum = guide_enumeration(rec_guide, script_dir=rec_scripts,
                                      hooks_dir=rec_enum_hooks)
        check("w7 a file one directory down that the guide never mentions is named, by "
              "its relative path - and `usage/core.py`, which the tree draws as an "
              "indented `core.py` under a `usage/` line, is NOT, because the match is on "
              "the BASENAME. Both directions in one exact list, which is also what fails "
              "if the rule is ever tightened to demand the literal `usage/core.py` a "
              "correctly drawn tree does not contain: %r" % (rec_enum,),
              rec_enum == [
                  ("panel/clean.py", "missing from the '%s' tree" % _TREE_HEADING),
                  ("panel/clean.py", "no '### ' heading in '%s' mentions it"
                   % _SECTION2_HEADING)])

        # ---- navigability: a long file one directory down is still judged ----
        nav_scripts = os.path.join(rec, "nav", "scripts", "deep")
        os.makedirs(nav_scripts)
        nav_hooks_dir = os.path.join(rec, "nav", "hooks")
        os.makedirs(nav_hooks_dir)
        with open(os.path.join(nav_scripts, "long_file.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("pass\n" * (_NAV_MIN_LINES + 10))
        nav_deep = navigability_violations(os.path.join(rec, "nav", "scripts"),
                                            hooks_dir=nav_hooks_dir)
        check("w8 a long, headerless file one directory down is a navigability "
              "violation like any other, named `deep/long_file.py`: %r" % (nav_deep,),
              [f for f, _w in nav_deep] == ["deep/long_file.py"])

        # ---- the price of naming nodes by basename, charged rather than assumed ----
        coll = os.path.join(rec, "collide")
        os.makedirs(os.path.join(coll, "usage"))
        os.makedirs(os.path.join(coll, "panel"))
        for _sub in ("usage", "panel"):
            with open(os.path.join(coll, _sub, "core.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("pass\n")
        coll_hits = layer_violations(coll, hooks_dir=rec_enum_hooks,
                                      layers=(("core",),))
        check("w9 two files claiming one module name is a violation IN ITS OWN WORDS, "
              "naming both paths - not a silently kept last-one-wins. They would be a "
              "single node in the graph, each wearing the other's edges, and every "
              "later judgement would be about a tree that is not there: %r" % (coll_hits,),
              len(coll_hits) == 1 and coll_hits[0][0] == "panel/core.py"
              and "claimed by 2 files" in coll_hits[0][1]
              and "usage/core.py" in coll_hits[0][1])
        check("w10 ...and the second direction: two DIFFERENT basenames in two different "
              "subdirectories are not a collision. Reads vacuous, and is the only case "
              "that fails if uniqueness is ever implemented as 'more than one directory' "
              "rather than 'more than one file per name' - which would make the whole "
              "recursion unusable: %r" % (rec_collisions,),
              rec_collisions == [])
    finally:
        shutil.rmtree(rec, ignore_errors=True)

    # ---- the tests/ boundary: the product may not depend on its own test tree ----
    # Fixtures, because the real tree is (and must stay) clean, and a rule only ever
    # seen returning [] is a rule that might be returning [] for the wrong reason.
    tb_s = tempfile.mkdtemp(prefix="deps-testboundary-s-")
    tb_h = tempfile.mkdtemp(prefix="deps-testboundary-h-")
    tb_t = tempfile.mkdtemp(prefix="deps-testboundary-t-")
    try:
        def _wtb(root, name, text):
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(text)

        _wtb(tb_t, "_harness.py", "def run(body):\n    return 0\n")
        _wtb(tb_t, "test_thing.py", "x = 1\n")
        _wtb(tb_s, "reaches_in.py", "import _harness\nx = 1\n")
        _wtb(tb_s, "reaches_in_from.py", "from _harness import run\nx = 1\n")
        _wtb(tb_s, "loads_it.py",
             'import _loader\n\n\ndef f():\n'
             '    return _loader.load_script("test_thing.py")\n')
        # The shape the three migrated files actually have: a test file named in
        # PROSE, so a reader knows where the cases went. Not an edge, and the only
        # case that fails if this lint is ever widened to "any .py literal".
        #
        # The anchor is BUILT, never spelled beside the filename: this file is one of
        # `_refs`' anchored surfaces, so an anchor written immediately in front of a
        # tests/ filename here would be a real reference to a fixture that exists for
        # four milliseconds, and `_refs.missing_references()` reports it. Learned by
        # doing it twice - the second time inside the comment saying not to.
        _anchor = "plugins/audit/"
        _wtb(tb_s, "only_points_at_it.py",
             '"""Its cases live in %stests/test_thing.py."""\n'
             'import _loader\n\n\ndef f():\n'
             '    print("moved to %stests/test_thing.py")\n'
             '    return _loader\n' % (_anchor, _anchor))
        _wtb(tb_h, "hook_reaches_in.py", "import _harness\nx = 1\n")
        _wtb(tb_h, "hook_clean.py", "import json\nx = 1\n")

        tb = tests_import_violations(tb_s, tb_h, tb_t)
        named_tb = sorted(n for n, _w in tb)
        check("tb1 a scripts/ file that imports the harness is reported, and so is "
              "the `from ... import` form - one rule, both spellings: %r" % (named_tb,),
              "scripts/reaches_in.py" in named_tb
              and "scripts/reaches_in_from.py" in named_tb)
        check("tb2 a HOOK that reaches into tests/ is reported too. hooks/ may not "
              "import scripts/ either, and both rules exist so the thing that runs on "
              "every tool call stays loadable from a launcher: %r" % (named_tb,),
              "hooks/hook_reaches_in.py" in named_tb)
        check("tb3 a `_loader` call naming a tests/ file is an edge as much as an "
              "import is - most of this tree's real edges are loader calls: %r"
              % (named_tb,), "scripts/loads_it.py" in named_tb)
        check("tb4 a file that merely NAMES a test file in a docstring and a print is "
              "NOT reported. Reads vacuous, and is the only case that fails if this "
              "widens to any `.py` literal - which would report all three migrated "
              "files, whose pointer messages say exactly that: %r" % (named_tb,),
              "scripts/only_points_at_it.py" not in named_tb
              and "hooks/hook_clean.py" not in named_tb)
        check("tb5 the message names the kind of edge, so the reader knows whether to "
              "look for an `import` or a loader call: %r" % ([w for _n, w in tb],),
              any("imports _harness from tests/" in w for _n, w in tb)
              and any("runtime-loads test_thing from tests/" in w for _n, w in tb))
        check("tb6 an empty (or absent) tests/ yields no violations, and is not "
              "confused with a clean scan of a populated one",
              tests_import_violations(tb_s, tb_h,
                                      os.path.join(tb_t, "no-such-dir")) == [])
    finally:
        shutil.rmtree(tb_s, ignore_errors=True)
        shutil.rmtree(tb_h, ignore_errors=True)
        shutil.rmtree(tb_t, ignore_errors=True)

    check("tb7 ...and the REAL tree carries none. This is the case that goes red the "
          "day a script imports the harness: %r" % (tests_import_violations(),),
          tests_import_violations() == [])
    check("tb8 tests/ is deliberately absent from LAYERS - a test file has no position "
          "in the product's import order, and tb7 is the rule that replaces one: %r"
          % (sorted(set(_all_names()) & set(os.path.basename(r)[:-3]
                                            for r, _p in _output.py_files(_TESTS_DIR))),),
          not (set(_all_names()) & set(os.path.basename(r)[:-3]
                                       for r, _p in _output.py_files(_TESTS_DIR))))

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    if "--render" in sys.argv[1:]:
        sys.stdout.write(render())
        raise SystemExit(0)
    sys.stderr.write("usage: _deps.py --selftest | --render\n")
    raise SystemExit(2)
