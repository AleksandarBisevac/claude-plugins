#!/usr/bin/env python3
"""
_affected_tests.py -- which suites a task's change can break, and the arm that
says so for each.

A task's own gate runs the tests the task wrote. A change that moves or edits a
file ANOTHER task's test imports breaks that test while the task's own gate
stays green, and the break surfaces at sign-off, after the task has closed.
The phase gate would catch it, but running the phase gate inside every task's
retry loop is the cost a task gate exists to avoid. So a task's measured run is
its own gate plus the suites this module selects, and the wide gate runs once,
at sign-off.

THE ARMS, IN ORDER: the project's recorded related listing
(`meta.phaseGate.derived.listing.related`, the same version-verified listing
`derive-phase-gate.py` already trusts); a stdlib `ast` import graph from Python
test files to the changed modules; the runners whose cases walk a directory
holding a changed suite (`walk`: a lint reads every file under the directory it
walks, so a suite edited there can turn it red through no import at all); the
e2e runner's changed listing (`listing.e2eChanged`) when one is recorded; and,
when the project has e2e specs that no recorded listing can see, every one of
them.

THE SELECTION IS PURE. Every observation -- a listing's exit and output, the
version answer, the Python sources, the tree's suite files -- arrives in
`facts`, and nothing the selection calls shells out or reads a file. The
gathering that fills `facts` is the last section of this file (`gather_facts`),
held apart from the selection and asked by both callers - `run-test-gate.py`'s
affected steps and `audit-task.py`'s gate-reach check - so the two measure one
set of facts the one way.

WIDEN, NEVER EMPTY. A listing that cannot answer, a version that does not
match, a `.py` change with no sources to graph, a changed path no arm reads,
a changed file under a test directory no arm selected (test support), and
suites with no command spelling to run them under all answer `widen` with
the reason: the caller adds the PHASE gate. An empty selection is only ever an
answer every arm gave. The test-support widening alone is settled by the
task's own gate when that gate holds the unscoped call of the spelling
(`steps_for`): that call runs every suite the support file can reach.

NOT TWICE. A step whose suites a declared entry already runs whole - the
step's own command with its paths taken out (`left_to_run`) - is left out and
said, so a full-sweep key does not run the same suites again beside it.
"""

import ast
import concurrent.futures
import os
import posixpath
import shlex
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
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _manifest_phases as _phases   # noqa: E402  (is_suite_path, gate_entry_paths)
import _gate_derive                  # noqa: E402  (the e2e reading of a path, the
#                                       path-scoped shape and its re-pointing:
#                                       asked, not copied)
import _evidence_io                  # noqa: E402  (DERIVED_STEP_PREFIX: the name a
#                                       row's measured-not-declared steps carry,
#                                       and a plan command's node preamble)
import _loader                       # noqa: E402  (git's paths read as plan paths)
import _proc_group                   # noqa: E402  (a listing's shell, its process
#                                       group, and the teardown of the group)

ARMS = ("related", "python", "walk", "e2e-changed", "e2e-widening")
# Prose is not app source: a change to these alone reaches no spec.
_DOC_EXTENSIONS = (".md", ".rst", ".txt")


# --- which paths a change touched -----------------------------------------------
def changed_paths(name_status_z):
    """Every path `git diff --name-status -z -M` names, in order, once each.

    A RENAME COUNTS AS BOTH ITS PATHS and a deletion as its old one: the old
    path is what another task's test still imports, and the break is there. A
    copy counts only its new path - the old one did not change.
    """
    tokens = (name_status_z or "").split("\0")
    out, i = [], 0
    while i < len(tokens):
        status = tokens[i].strip()
        if not status:
            i += 1
            continue
        width = 2 if status[0] in ("R", "C") else 1
        paths = tokens[i + 1:i + 1 + width]
        if status[0] == "C":
            paths = paths[1:]
        for path in paths:
            if path and path not in out:
                out.append(path)
        i += 1 + width
    return out


# --- the Python import graph ------------------------------------------------------
def _is_python_test(path):
    base = path.rsplit("/", 1)[-1]
    return base.endswith(".py") and (base.startswith("test_")
                                     or base.endswith("_test.py"))


def _module_names(path):
    """Every dotted name `path` can be imported under: the whole path's and each
    shorter suffix's. A project that puts several directories on `sys.path` and
    imports by bare basename is read as correctly as one with packages, at the
    price of selecting MORE when two files share a basename - the safe side."""
    if not path.endswith(".py"):
        return []
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts))]


def _prefixes(dotted):
    parts = dotted.split(".")
    return [".".join(parts[:i + 1]) for i in range(len(parts))]


# Callee names that load a module from a file. ONLY these: a `.py` name handed
# to any call at all (a path joined for a message, a fixture's file name) made
# one shared helper reach half a tree, and every test reached everything.
_LOADER_WORDS = ("load", "import", "run_path", "spec_from_file_location")


def _is_loader(func):
    name = getattr(func, "attr", None) or getattr(func, "id", None) or ""
    return any(word in name for word in _LOADER_WORDS)


def _parse(path, source):
    """`source`'s syntax tree, or None when it does not parse."""
    try:
        return ast.parse(source, path)
    except (SyntaxError, ValueError):
        return None


def _parsed(sources):
    """`{path: tree or None}` - every source parsed ONCE, for both arms that
    read Python: parsing a large tree is most of what either one costs."""
    return dict((p, _parse(p, s)) for p, s in sources.items()
                if isinstance(s, str))


def _refs(path, source, tree=None):
    """`(names, scripts)` -- the dotted names `source` imports (each with its
    parent packages, which importing it runs) and the `*.py` file names it hands
    to a loader call (a script loaded by its file name). None when it does not
    parse. `tree`, when given, is `source` already parsed."""
    tree = tree if tree is not None else _parse(path, source)
    if tree is None:
        return None
    package = path.split("/")[:-1]
    names, scripts = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(_prefixes(alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = package[:max(len(package) - node.level + 1, 0)] if node.level else []
            stem = ".".join(base + ([node.module] if node.module else []))
            if stem:
                names.update(_prefixes(stem))
            names.update("%s.%s" % (stem, a.name) if stem else a.name
                         for a in node.names if a.name != "*")
        elif isinstance(node, ast.Call) and _is_loader(node.func):
            for arg in node.args:
                value = getattr(arg, "value", None)
                if isinstance(arg, ast.Constant) and isinstance(value, str) \
                        and value.endswith(".py"):
                    scripts.add(value.replace("\\", "/").rsplit("/", 1)[-1])
    return names, scripts


def _python_arm(changed, sources, trees=None):
    """`{test: basis}` for every Python test whose import closure reaches a
    changed `.py` path. A changed path whose source is gone (a deletion, a
    rename's old side) is still a node, so its importers are found. `trees`,
    when given, is `_parsed(sources)`."""
    targets = set(p for p in changed if p.endswith(".py"))
    known = sorted(set(sources) | targets)
    by_name, by_file = {}, {}
    for path in known:
        for name in _module_names(path):
            by_name.setdefault(name, set()).add(path)
        by_file.setdefault(path.rsplit("/", 1)[-1], set()).add(path)
    trees = trees if trees is not None else {}
    refs = dict((p, _refs(p, sources[p], trees.get(p))) for p in sources)
    importers = {}
    for path, got in refs.items():
        if got is None:
            continue
        names, scripts = got
        reached = set()
        for name in names:
            reached |= by_name.get(name, set())
        for script in scripts:
            reached |= by_file.get(script, set())
        for imported in reached:
            importers.setdefault(imported, set()).add(path)
    # ONE WALK UP THE REVERSED GRAPH from the changed modules, in sorted order so
    # each file's basis names the first changed path that reaches it - a walk
    # per test re-crosses the shared core of the graph once per test.
    reached_from = {}
    for target in sorted(targets):
        stack = [target]
        reached_from.setdefault(target, target)
        while stack:
            for up in importers.get(stack.pop(), ()):
                if up not in reached_from:
                    reached_from[up] = target
                    stack.append(up)
    out = {}
    for test in sorted(p for p in known if _is_python_test(p)):
        if test in sources and refs.get(test) is None:
            out[test] = ("python: %s does not parse, so its imports cannot be "
                         "read - selected rather than left out" % (test,))
        elif test in reached_from:
            out[test] = ("python: its import closure reaches %s"
                         % (reached_from[test],))
    return out


# --- the tree walks ---------------------------------------------------------------
# WHICH DIRECTORY A RUNNER'S CASES READ WHOLE, read off the code. A lint walks a
# directory and reads every file under it, so a suite edited there turns the lint
# red through no import - the import graph cannot see that edge, and a gate
# naming only the edited suite went green over it. The walk is found the way a
# reader would: a call that lists a directory, or a project function that makes
# one, followed through modules and parameters; and the directory handed to it is
# evaluated from the literals, `__file__` and the path calls that build it.
#
# WHAT THIS CANNOT SEE: a directory computed at runtime from anything but those
# (an environment variable, a value read from a file, a closure's variable), a
# walk reached through a method on an object, and a recursion's second turn.
# Each is left out rather than guessed: a guessed directory selects runners that
# do not read the suite, and the phase gate still runs every runner the task's
# gate leaves out.
#
# THE PROJECT ROOT COUNTS ONLY WHEN IT IS ANCHORED on a file's own location. A
# bare relative name evaluates to the root too - the directory of `plan.json` is
# `""` - and reads nothing about where a runner walks.
_WALK_CALLS = {"os": ("walk", "listdir", "scandir"), "glob": ("glob", "iglob")}
_WALK_METHODS = ("rglob", "iterdir")
# Calls that hand back the path they were given, or the paths they were given
# joined: a `Path(...)`, an `abspath(...)`, a `str(...)`.
_SAME_PATH = ("abspath", "realpath", "normpath", "expanduser", "fspath", "str",
              "Path", "PurePath", "PurePosixPath")
_SAME_PATH_METHODS = ("resolve", "absolute", "expanduser")
_PATH_MODULES = ("path", "posixpath", "ntpath")
_GLOB_MAGIC = ("*", "?", "[")
# A path expression nested deeper than this is not followed: the answer is
# "unknown", never a guess.
_EVAL_DEPTH = 40
# Joining every value of every piece multiplies; past this many candidates the
# expression is read as unknown rather than enumerated.
_MAX_VALUES = 32


def _function_scope(fdef, parent):
    """A function's own bindings, before its body is read: its parameters,
    each also bound to its default."""
    args = fdef.args
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    assigns = {}
    defaults = list(args.defaults)
    for arg, default in zip(positional[len(positional) - len(defaults):],
                            defaults):
        assigns.setdefault(arg.arg, []).append(default)
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None:
            assigns.setdefault(arg.arg, []).append(default)
    return {"params": [a.arg for a in positional + list(args.kwonlyargs)],
            "positional": [a.arg for a in positional], "assigns": assigns,
            "calls": [], "parent": parent, "busy": set()}


def _bind(assigns, node):
    """Record what `node` binds by name in `assigns`: an assignment's value,
    or what a `for` hands its name - the loop's iterable and the position the
    name takes in each element (`for surface, mode in SURFACES`), read when
    the name is."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                assigns.setdefault(target.id, []).append(node.value)
    elif isinstance(node, ast.For):
        if isinstance(node.target, ast.Name):
            assigns.setdefault(node.target.id, []).append(
                ("unpack", node.iter, None))
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for at, target in enumerate(node.target.elts):
                if isinstance(target, ast.Name):
                    assigns.setdefault(target.id, []).append(
                        ("unpack", node.iter, at))


def _module_facts(path, tree):
    """What a module binds - import aliases, names imported from a module,
    assignments outside any function, top-level functions - and every function
    with the calls and bindings that are its OWN, not a nested function's.

    ONE PASS OVER THE TREE: reading each function's body separately re-reads
    every nested function once per enclosing one, which on a large suite whose
    cases are one function holding many is most of what the reading costs."""
    aliases, names, assigns, defs = {}, {}, {}, {}
    scopes, calls = [], []
    top = set(id(n) for n in tree.body)
    stack = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        here = owner
        if isinstance(node, ast.FunctionDef):
            scopes.append(_function_scope(node, owner))
            here = len(scopes) - 1
            if id(node) in top:
                defs[node.name] = here
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]
                else:
                    head = alias.name.split(".")[0]
                    aliases[head] = head
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = (
                    node.module.rsplit(".", 1)[-1], alias.name)
        elif isinstance(node, (ast.Assign, ast.For)):
            _bind(assigns if owner is None else scopes[owner]["assigns"], node)
        elif isinstance(node, ast.Call):
            (calls if owner is None else scopes[owner]["calls"]).append(node)
        for child in ast.iter_child_nodes(node):
            stack.append((child, here))
    return {"path": path, "aliases": aliases, "names": names,
            "assigns": assigns, "defs": defs, "scopes": scopes,
            "calls": calls}


def _walk_index(trees):
    """The modules the walk reading resolves names through, by path and by the
    bare stem `import` reaches them under. A stem two files share resolves to
    neither: which one a runner meant is not something to guess."""
    modules = dict((p, _module_facts(p, t)) for p, t in sorted(trees.items())
                   if t is not None and p.endswith(".py"))
    stems = {}
    for path in modules:
        stems.setdefault(path.rsplit("/", 1)[-1][:-3], []).append(path)
    return {"modules": modules,
            "stems": dict((s, ps[0]) for s, ps in stems.items() if len(ps) == 1),
            "names": {}, "summaries": {}}


def _module_of(index, stem):
    path = index["stems"].get(stem)
    return index["modules"].get(path) if path else None


def _is_path_call(func, mod, word):
    """True for `os.path.<word>`, `posixpath.<word>`, or `<word>` imported from
    one of them - never a string's own `.join`."""
    if isinstance(func, ast.Attribute):
        owner = func.value
        owner_name = getattr(owner, "attr", None) or getattr(owner, "id", None)
        return func.attr == word and owner_name in _PATH_MODULES
    if isinstance(func, ast.Name):
        source = mod["names"].get(func.id)
        return bool(source) and source[1] == word and source[0] in _PATH_MODULES
    return False


# A VALUE is one of three shapes: `("path", text, anchored)` - a path relative to
# the project, anchored when it was built from a file's own location;
# `("param", name)` - a parameter of the function being read, whose value is
# known only at a call; and `("tpl", pieces)` - a join of paths and parameters,
# filled in at a call (`os.path.join(root, surface)` with both handed in).
def _join_one(combo):
    """One join of `combo`'s values, adjacent known paths folded together and
    a template's pieces spliced in; anchored when its first piece is."""
    pieces = []
    for value in combo:
        pieces.extend(value[1] if value[0] == "tpl" else (value,))
    merged = []
    for piece in pieces:
        if piece[0] == "path" and merged and merged[-1][0] == "path":
            head = merged[-1]
            merged[-1] = ("path", _posix_join(head[1], piece[1]), head[2])
        else:
            merged.append(piece)
    return merged[0] if len(merged) == 1 else ("tpl", tuple(merged))


def _joined(pieces):
    """Every join of one value per piece. A piece with no value makes the whole
    join unknown, and so do more candidates than `_MAX_VALUES`."""
    combos = [[]]
    for values in pieces:
        if not values:
            return set()
        combos = [c + [v] for c in combos for v in values]
        if len(combos) > _MAX_VALUES:
            return set()
    return set(_join_one(c) for c in combos)


def _filled(value, handed):
    """`value` with each parameter replaced by every value `handed` holds for
    it; nothing when a parameter it names was not handed."""
    if value[0] == "path":
        return set((value,))
    pieces = (value,) if value[0] == "param" else value[1]
    return _joined([set((p,)) if p[0] == "path" else handed.get(p[1], set())
                    for p in pieces])


def _params_of(value):
    pieces = (value,) if value[0] == "param" else value[1] \
        if value[0] == "tpl" else ()
    return set(p[1] for p in pieces if p[0] == "param")


def _posix_join(head, tail):
    """`head/tail` in the spelling a plan path uses."""
    if not head:
        return tail
    return tail if tail.startswith("/") else head.rstrip("/") + "/" + tail


def _values(node, mod, scope, index, depth=0):
    """Every value `node` can evaluate to, in the shapes the comment above
    `_join_one` names; `scope` is the function whose parameters a `("param",
    name)` is one of. An expression this cannot follow has no value."""
    if depth > _EVAL_DEPTH:
        return set()
    deeper = depth + 1

    def again(child):
        return _values(child, mod, scope, index, deeper)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return set((("path", node.value, False),))
    if isinstance(node, ast.Name):
        return _name_values(node.id, mod, scope, index, deeper)
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            return set(("path", posixpath.dirname(v[1]), v[2])
                       for v in again(node.value) if v[0] == "path")
        if isinstance(node.value, ast.Name) \
                and node.value.id in mod["aliases"]:
            other = _module_of(index, mod["aliases"][node.value.id])
            if other is not None:
                return _name_values(node.attr, other, None, index, deeper)
        return set()
    if isinstance(node, (ast.IfExp, ast.BoolOp)):
        parts = [node.body, node.orelse] if isinstance(node, ast.IfExp) \
            else node.values
        out = set()
        for part in parts:
            out |= again(part)
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left, right = again(node.left), again(node.right)
        if isinstance(node.op, ast.Div):
            return _joined([left, right])
        return set(("path", a[1] + b[1], a[2]) for a in left for b in right
                   if a[0] == "path" and b[0] == "path")
    if isinstance(node, ast.Call):
        return _call_values(node, mod, again)
    return set()


def _is_separator_swap(node):
    """True for `<path>.replace("/", os.sep)` and its reverse: the same path
    in another spelling of the separator."""
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == "replace"
            and len(node.args) == 2
            and any(isinstance(a, ast.Constant) and a.value in ("/", "\\")
                    for a in node.args))


def _call_values(node, mod, again):
    func = node.func
    word = getattr(func, "attr", None) or getattr(func, "id", None)
    if _is_path_call(func, mod, "join") and node.args:
        return _joined([again(a) for a in node.args])
    if _is_path_call(func, mod, "dirname") and node.args:
        return set(("path", posixpath.dirname(v[1]), v[2])
                   for v in again(node.args[0]) if v[0] == "path")
    if _is_separator_swap(node):
        return again(func.value)
    if isinstance(func, ast.Attribute) and word in _SAME_PATH_METHODS \
            and not node.args:
        return again(func.value)
    if word in _SAME_PATH and node.args:
        if len(node.args) == 1:
            return again(node.args[0])
        return _joined([again(a) for a in node.args])
    return set()


def _name_values(name, mod, scope, index, depth):
    """A name's values: the function's own binding of it when `scope` has
    one, else the module's, else the module it was imported from."""
    if name == "__file__":
        return set((("path", mod["path"], True),))
    if scope is not None and (name in scope["assigns"] or name in scope["params"]):
        if name in scope["busy"]:
            return set()
        scope["busy"].add(name)
        try:
            out = set((("param", name),)) if name in scope["params"] else set()
            for bound in scope["assigns"].get(name, ()):
                out |= _bound_values(bound, mod, scope, index, depth)
            return out
        finally:
            scope["busy"].discard(name)
    key = (mod["path"], name)
    memo = index["names"]
    if key in memo:
        return memo[key]
    memo[key] = set()     # read while being computed: a cycle has no value
    out = set()
    if name in mod["assigns"]:
        for bound in mod["assigns"][name]:
            out |= _bound_values(bound, mod, None, index, depth)
    elif name in mod["names"]:
        stem, original = mod["names"][name]
        other = _module_of(index, stem)
        if other is not None:
            out = _name_values(original, other, None, index, depth)
    memo[key] = out
    return out


def _bound_values(bound, mod, scope, index, depth):
    """The values one binding gives its name: an expression's, or - for a loop
    variable - those of the element (or the element's part) at its position."""
    if not isinstance(bound, tuple):
        return _values(bound, mod, scope, index, depth)
    _kind, iterable, at = bound
    out = set()
    for element in _elements(iterable, mod, scope, index, depth):
        if at is None:
            out |= _values(element, mod, scope, index, depth)
        elif isinstance(element, (ast.Tuple, ast.List)) \
                and at < len(element.elts):
            out |= _values(element.elts[at], mod, scope, index, depth)
    return out


def _elements(node, mod, scope, index, depth):
    """The element expressions of a literal tuple or list `node` names - the
    literal itself, or a name bound to one here or in the module it is
    imported from. Anything else has no elements this can read."""
    if depth > _EVAL_DEPTH:
        return []
    if isinstance(node, (ast.Tuple, ast.List)):
        return list(node.elts)
    owner, name = mod, None
    if isinstance(node, ast.Name):
        name = node.id
        if scope is not None and name in scope["assigns"]:
            return [e for b in scope["assigns"][name]
                    if not isinstance(b, tuple)
                    for e in _elements(b, mod, scope, index, depth + 1)]
        if name not in mod["assigns"] and name in mod["names"]:
            stem, name = mod["names"][name]
            owner = _module_of(index, stem)
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id in mod["aliases"]:
        owner, name = _module_of(index, mod["aliases"][node.value.id]), node.attr
    if owner is None or name not in owner["assigns"]:
        return []
    return [e for b in owner["assigns"][name] if not isinstance(b, tuple)
            for e in _elements(b, owner, None, index, depth + 1)]


def _callee(call, mod, index):
    """`("walk", word)` for a call that lists a directory, `("method", word)`
    for a path method that does, `("def", path, name)` for a project function,
    or None."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id in mod["aliases"]:
            stem = mod["aliases"][func.value.id]
            if func.attr in _WALK_CALLS.get(stem, ()):
                return ("walk", func.attr)
            other = _module_of(index, stem)
            if other is not None and func.attr in other["defs"]:
                return ("def", other["path"], func.attr)
        if func.attr in _WALK_METHODS:
            return ("method", func.attr)
        return None
    if not isinstance(func, ast.Name):
        return None
    if func.id in mod["names"]:
        stem, original = mod["names"][func.id]
        if original in _WALK_CALLS.get(stem, ()):
            return ("walk", original)
        other = _module_of(index, stem)
        if other is not None and original in other["defs"]:
            return ("def", other["path"], original)
        return None
    if func.id in mod["defs"]:
        return ("def", mod["path"], func.id)
    return None


def _root(value, glob=False):
    """The project-relative directory a walked value names, or None."""
    text = value[1]
    if glob:
        kept = []
        for part in text.split("/"):
            if any(m in part for m in _GLOB_MAGIC):
                break
            kept.append(part)
        text = "/".join(kept)
    text = posixpath.normpath(text) if text else "."
    if text == "." and not value[2]:
        return None
    if text.startswith("/") or text == ".." or text.startswith("../"):
        return None
    return "" if text == "." else text


def _walked_by(call, kind, mod, scope, index):
    """`(roots, templates)` this one call walks: the directories it lists, and
    `(value, glob)` for each walked value still waiting on a parameter of
    `scope`."""
    if kind[0] == "walk":
        handed = [(v, kind[1] in ("glob", "iglob"))
                  for v in _values(call.args[0], mod, scope, index)] \
            if call.args else []
        return _settled(handed)
    if kind[0] == "method":
        return _settled([(v, False)
                         for v in _values(call.func.value, mod, scope, index)])
    roots, templates, positional = _summary(kind[1:], index)
    wanted = set(name for value, _g in templates for name in _params_of(value))
    exprs = dict((positional[i], arg) for i, arg in enumerate(call.args)
                 if i < len(positional) and positional[i] in wanted)
    exprs.update((kw.arg, kw.value) for kw in call.keywords if kw.arg in wanted)
    given = dict((name, _values(expr, mod, scope, index))
                 for name, expr in exprs.items())
    found, waiting = _settled([(filled, glob) for value, glob in templates
                               for filled in _filled(value, given)])
    return found | set(roots), waiting


def _settled(handed):
    """`(roots, templates)` for walked values: a known path is a root, a
    value waiting on a parameter is a template."""
    found, waiting = set(), set()
    for value, glob in handed:
        if value[0] != "path":
            waiting.add((value, glob))
            continue
        root = _root(value, glob)
        if root is not None:
            found.add(root)
    return found, waiting


def _scope_walks(calls, mod, scope, index):
    """`(roots, templates)` - what `calls`, made in `scope`, walk: directories,
    and the walked values waiting on a parameter of `scope` (none at a module's
    top, which has no parameters)."""
    roots, templates = set(), set()
    for node in calls:
        kind = _callee(node, mod, index)
        if kind is None:
            continue
        found, waiting = _walked_by(node, kind, mod, scope, index)
        roots |= found
        templates |= waiting
    own = set(scope["params"]) if scope is not None else set()
    return roots, set(t for t in templates if _params_of(t[0]) <= own)


def _summary(key, index):
    """`(roots, templates, positional params)` for a project function,
    computed once: what it walks whatever it is handed - its own calls and
    those of every function nested in it - and the walked values a call fills
    in from what it hands the function's parameters."""
    memo = index["summaries"]
    if key in memo:
        return memo[key]
    memo[key] = (frozenset(), frozenset(), [])   # a recursion reads nothing
    mod = index["modules"][key[0]]
    own = mod["defs"][key[1]]
    scope = mod["scopes"][own]
    roots, templates = _scope_walks(scope["calls"], mod, scope, index)
    for nested in _nested(mod, own):
        inner = mod["scopes"][nested]
        roots |= _scope_walks(inner["calls"], mod, inner, index)[0]
    memo[key] = (frozenset(roots), frozenset(templates), scope["positional"])
    return memo[key]


def _nested(mod, owner):
    """The indexes of every function defined inside function `owner`."""
    inside = set((owner,))
    out = []
    for i, scope in enumerate(mod["scopes"]):
        if scope["parent"] in inside:
            inside.add(i)
            out.append(i)
    return out


def runner_walks(path, index):
    """Every directory `path`'s own code walks, at its top level or in any
    function it defines - a runner's cases may call any of them."""
    mod = index["modules"].get(path)
    if mod is None:
        return set()
    roots = _scope_walks(mod["calls"], mod, None, index)[0]
    for scope in mod["scopes"]:
        roots |= _scope_walks(scope["calls"], mod, scope, index)[0]
    return roots


def _covers(root, path):
    return root == "" or path == root or path.startswith(root + "/")


def _walk_arm(suites, runners, trees):
    """`{runner: basis}` for every runner whose walk holds a changed suite."""
    index = _walk_index(trees)
    out = {}
    for runner in sorted(set(runners)):
        if runner not in index["modules"]:
            continue
        roots = sorted(runner_walks(runner, index))
        for suite in suites:
            hit = [r for r in roots if _covers(r, suite)]
            if hit and runner not in out:
                out[runner] = ("walk: its cases walk %s, which holds %s"
                               % (hit[-1] or "the project root", suite))
    return out


# --- a recorded listing, and whether it may be trusted -------------------------
def _derived(meta):
    gate = (meta or {}).get("phaseGate") if isinstance(meta, dict) else None
    derived = gate.get("derived") if isinstance(gate, dict) else None
    return derived if isinstance(derived, dict) else {}


def listing_templates(meta):
    """`{"related": tpl, "e2eChanged": tpl}` for each recorded listing whose
    template carries `{paths}` - the ones a caller runs."""
    listing = _derived(meta).get("listing")
    listing = listing if isinstance(listing, dict) else {}
    return dict((k, listing[k]) for k in ("related", "e2eChanged")
                if isinstance(listing.get(k), str) and "{paths}" in listing[k])


def all_template(meta):
    """The recorded all-runners listing (`listing.all`): every file whose cases
    the project's runner collects, named by nothing it is handed. None when no
    such listing is recorded."""
    listing = _derived(meta).get("listing")
    listing = listing if isinstance(listing, dict) else {}
    found = listing.get("all")
    return found if isinstance(found, str) and found.strip() else None


def changed_suites(changed):
    """The changed paths a runner collects or that sit under a test
    directory - the ones a lint over the tests can read."""
    return [p for p in changed or [] if _phases.is_suite_path(p)]


def _untrusted(meta, facts):
    """Why the related listing's answer may not be read, or None. The verdict
    is `_gate_derive.version_distrust`'s; only the wording is this arm's."""
    distrust = _gate_derive.version_distrust(_derived(meta), facts)
    if distrust is None:
        return None
    if distrust[0] == "failed":
        return "the version command failed"
    return ("the listing was verified on %s and this machine answers %s"
            % (distrust[1], distrust[2]))


def _ran(facts, key):
    """`(paths, why)` for a listing observation: its paths, or why it gave none."""
    seen = facts.get(key)
    if not isinstance(seen, dict):
        return None, "it was recorded but not run"
    if seen.get("exit") != 0:
        return None, "`%s` exited %r" % (seen.get("command"), seen.get("exit"))
    return [p[2:] if p.startswith("./") else p
            for p in (seen.get("paths") or []) if isinstance(p, str)], None


# --- the selection ----------------------------------------------------------------
def _widened(reason, lines):
    said = "%s - the task's gate widens to the phase gate" % (reason,)
    return {"suites": [], "widen": said, "lines": lines + [said]}


def select(changed, meta, facts, exclude=None):
    """`{suites, widen, lines}` -- the suites `changed` can break, each
    `{path, arm, basis}` in arm order, or `widen` naming why the phase gate
    runs instead. `exclude` is what the task's own gate already names.
    """
    meta = meta if isinstance(meta, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    changed = [p for p in (changed or []) if isinstance(p, str) and p]
    skip = set(exclude or ())
    suites, lines = [], []

    def add(path, arm, basis):
        if path not in skip and path not in [s["path"] for s in suites]:
            suites.append({"path": path, "arm": arm, "basis": basis})

    if not changed:
        return {"suites": [], "widen": None,
                "lines": ["affected: the task changed no path, so nothing joins "
                          "its gate"]}
    templates = listing_templates(meta)
    related_paths = []
    read = set()
    if "related" in templates:
        why = _untrusted(meta, facts)
        related_paths, ran_why = _ran(facts, "related")
        if why or ran_why:
            return _widened("related: %s" % (why or ran_why,), lines)
        command = facts["related"].get("command") or templates["related"]
        # The listing was handed every changed path, so its answer covers all.
        read.update(changed)
        for path in related_paths:
            add(path, "related", "related: named by the recorded listing `%s`"
                % (command,))
    else:
        lines.append("related: no meta.phaseGate.derived.listing.related is "
                     "recorded")

    sources = facts.get("pySources")
    python = any(p.endswith(".py") for p in changed)
    edited = changed_suites(changed)
    trees = _parsed(sources) if isinstance(sources, dict) \
        and (python or edited) else None
    if python:
        if trees is None:
            return _widened("python: a .py path changed and no sources were "
                            "read to graph its importers", lines)
        for path, basis in sorted(_python_arm(changed, sources, trees).items()):
            add(path, "python", basis)

    if edited:
        runners, why = _walk_runners(meta, facts, trees)
        if why:
            return _widened("walk: %s" % (why,), lines)
        if trees is None:
            lines.append("walk: no Python sources were read, so no runner's "
                         "walk over %s was looked for" % (", ".join(edited),))
        else:
            for path, basis in sorted(_walk_arm(edited, runners, trees).items()):
                add(path, "walk", basis)

    e2e_paths = []
    if "e2eChanged" in templates:
        e2e_paths, ran_why = _ran(facts, "e2eChanged")
        if ran_why:
            return _widened("e2e-changed: %s" % (ran_why,), lines)
        for path in e2e_paths:
            add(path, "e2e-changed", "e2e-changed: named by the recorded "
                "listing `%s`" % (facts["e2eChanged"].get("command"),))

    specs = [p for p in (facts.get("suites") or [])
             if isinstance(p, str) and _phases.is_suite_path(p)
             and _gate_derive._e2e_like(p)]
    source = [p for p in changed if not _phases.is_suite_path(p)
              and not p.lower().endswith(_DOC_EXTENSIONS)]
    sees_e2e = "e2eChanged" in templates or any(
        _gate_derive._e2e_like(p) for p in related_paths)
    if specs and source and not sees_e2e:
        for path in specs:
            add(path, "e2e-widening", "e2e-widening: %s is app source and no "
                "recorded listing sees the e2e specs, so every spec runs"
                % (source[0],))
    if "e2eChanged" in templates or (specs and not sees_e2e):
        read.update(source)
    read.update(p for p in changed if p.endswith(".py")
                or p.lower().endswith(_DOC_EXTENSIONS) or p in skip)
    unread = [p for p in changed if p not in read]
    if unread:
        return _widened("unrecognised: no arm reads %s - no related listing "
                        "answered for it, and it is not Python, prose, a suite "
                        "the task's gate runs, or app source an e2e arm took"
                        % (", ".join(unread),), lines)
    # A changed file under a test directory that no arm selected is test
    # support - a harness, a conftest, a fixture - or a suite nothing listed.
    # Every suite may lean on it, and a listing that answered with its
    # importers still left out its own run, so the whole set runs.
    picked = set(s["path"] for s in suites)
    support = [p for p in changed if _phases.is_suite_path(p)
               and p not in skip and p not in picked]
    if support:
        # What the arms chose is kept beside the widening: a task gate that
        # already runs every suite settles it (`steps_for`), and those suites
        # are then measured like any other selection.
        return dict(_widened("test support: %s changed and no arm selected "
                             "it - a file under a test directory may be what "
                             "every suite leans on" % (", ".join(support),),
                             lines),
                    support=support, selected=suites)
    return {"suites": suites, "widen": None, "lines": lines}


def _walk_runners(meta, facts, trees):
    """`(runners, why)` - the files whose cases a runner collects: every Python
    test named as one, and every `.py` the recorded all-runners listing names
    (a lint carrying its own cases need not be named like a test). `why` names
    a recorded listing that could not answer."""
    named = sorted(p for p in (trees or {}) if _is_python_test(p))
    if all_template(meta) is None:
        return named, None
    why = _untrusted(meta, facts)
    listed, ran_why = _ran(facts, "all")
    if why or ran_why:
        return [], "the all-runners listing `%s` cannot be read: %s" % (
            all_template(meta), why or ran_why)
    return sorted(set(named) | set(p for p in listed if p.endswith(".py"))), None


# --- what the task's gate already is, and the commands the rest run under --------
def gate_runs(task_entries):
    """The paths a task's gate entries run the cases of, in order, once each -
    what `select`'s `exclude` is.

    NOT EVERY PATH AN ENTRY NAMES. `python3 tools/sweep.py tests/test_a.py`
    runs `tools/sweep.py` as a program and hands it the suite: the sweep's own
    cases do not run, and a runner whose cases walk the edited suite must still
    be selected when the gate names it only as that program. A path an entry
    names alone (`python3 tests/test_a.py --selftest`) is what runs, so it
    stays."""
    out = []
    for entry in task_entries or []:
        for words in _phases.gate_entry_commands(entry):
            found = [(i, _phases.shell_word_path(w)) for i, w in enumerate(words)]
            found = [(i, p) for i, p in found if p]
            if len(found) > 1 \
                    and _phases._runs_first_path_as_program(words[:found[0][0]]):
                found = found[1:]
            out.extend(p for _i, p in found if p not in out)
    return out


def already_wide(task_entries, phase_entries):
    """True when the task's gate already carries every entry of a non-empty phase
    gate - the wide gate runs anyway, so nothing selected here adds coverage."""
    phase_entries = [e for e in (phase_entries or []) if e]
    return bool(phase_entries) and set(phase_entries) <= set(task_entries or [])


def entries_for(suites, phase, meta, project, lister=None):
    """`(steps, widen)` -- `[(name, command)]`, one or more per arm, each in the
    project's own path-scoped spelling (`_gate_derive.resolve_shape`:
    `meta.phaseGate.derived.spelling` when it carries a `{paths}` placeholder,
    else a sibling task's path-scoped entry). The name is
    `_evidence_io.DERIVED_STEP_PREFIX` followed by `<arm>: <suites>`, which is
    how a recorded row attributes each suite to its arm - and how
    `_evidence_io.declared_steps` tells it from a declared step. No spelling
    means no command can run them: `widen`."""
    spelling, why = _spelling(phase, meta)
    if why:
        return [], why
    steps = []
    for arm in ARMS:
        paths = [s["path"] for s in suites if s.get("arm") == arm]
        if not paths:
            continue
        for entry in _spell(spelling, paths, project, lister):
            named = [p for p in paths if shlex.quote(p) in entry] or paths
            steps.append(("%s%s: %s" % (_evidence_io.DERIVED_STEP_PREFIX, arm,
                                        ", ".join(named)), entry))
    return steps, None


def _spelling(phase, meta):
    """`((scoped, source, build), why)` - the path-scoped shape the selection's
    commands are spelled in, or why there is none."""
    meta = meta if isinstance(meta, dict) else {}
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    shape, source, _lines = _gate_derive.resolve_shape(phase or {}, build,
                                                       _derived(meta))
    if shape is None:
        return None, ("no path-scoped spelling: no task in this phase declares "
                      "a gate entry naming a path and "
                      "meta.phaseGate.derived.spelling is not set, so the "
                      "affected suites have no command to run under - the "
                      "task's gate widens to the phase gate")
    scoped = [e for e in shape if not _gate_derive.is_shared_key(e, build)
              and (source == _gate_derive.SPELLING_SOURCE
                   or _phases.gate_entry_paths(e))]
    return (scoped, source, build), None


def _spell(spelling, paths, project, lister=None):
    """The commands that run `paths` in `spelling`."""
    scoped, source, build = spelling
    if source == _gate_derive.SPELLING_SOURCE:
        return [scoped[0].replace(
            "{paths}", " ".join(shlex.quote(p) for p in paths))]
    entries, _notes = _gate_derive.repointed_by_runner(
        scoped, build, paths, project, lister=lister)
    return entries


def _words(command):
    """`command`'s shell words, or None when it does not split."""
    try:
        return shlex.split(command) if isinstance(command, str) else None
    except ValueError:
        return None


def left_to_run(steps, suites, task_entries, build):
    """`(steps, suites, lines)` - the affected steps the task's own gate does
    not already run, the suites they still carry, and one line per step left
    out.

    A DECLARED ENTRY WHOSE COMMAND IS A STEP'S OWN COMMAND WITH ITS SUITE PATHS
    TAKEN OUT is that runner called unscoped, which runs every suite the step
    would: a spelling of `<runner> {paths}` beside a key whose command is
    `<runner>` alone. Adding the step would run those suites a second time.
    Compared word for word, so the same runner with an option, or scoped to a
    path, is not that entry and the step stays. A command that does not split
    is never read as covered.

    THE PREMISE IS THE RUNNER'S: called with no path it runs every suite it
    would run when one is named. A runner configured to skip a path it still
    runs when that path is handed to it (a `testpaths` that leaves the suite
    out) breaks it, and nothing here can see that configuration."""
    build = build if isinstance(build, dict) else {}
    paths = set(s.get("path") for s in suites or [] if isinstance(s, dict))
    declared = _declared_calls(task_entries, build)
    kept, lines, gone, still = [], [], set(), set()
    for name, command in steps:
        entry, inside = _unscoped_entry(command, paths, declared)
        if entry is None:
            kept.append((name, command))
            still |= inside
            continue
        gone |= inside
        lines.append("affected: %s is not added - the task's gate entry `%s` "
                     "runs `%s`, the same call with no path, which runs every "
                     "suite this step would" % (name, entry,
                                                build.get(entry, entry)))
    dropped = gone - still
    left = [s for s in suites or [] if s.get("path") not in dropped]
    return kept, left, lines


def _declared_calls(task_entries, build):
    """`{words: entry}` - each declared entry's command as shell words."""
    declared = {}
    for entry in task_entries or []:
        words = _words(build.get(entry, entry))
        if words:
            declared.setdefault(tuple(words), entry)
    return declared


def _unscoped_entry(command, paths, declared):
    """`(entry, inside)` - the declared entry whose command is `command` with
    `paths` taken out, word for word, and the paths `command` carried. The
    entry is None when no declared entry is that call."""
    words = _words(command)
    inside = set(w for w in (words or []) if w in paths)
    bare = tuple(w for w in words if w not in paths) if words else None
    return (declared.get(bare) if inside and bare else None), inside


def steps_for(info, phase, meta, project, task_entries, lister=None):
    """`(steps, info)` - the affected steps that join a task's run for
    `select`'s answer `info`, and that answer with what joined, what was left
    out and why said in its lines.

    A TEST-SUPPORT WIDENING IS SETTLED BY THE TASK'S OWN GATE when one of its
    entries is the selection's spelling called with no path: spelled for the
    support paths, the command with those paths taken out is a declared entry's
    command, word for word - the comparison `left_to_run` makes for a step. That
    call runs every suite the runner collects, which is every suite the support
    file can reach, so the phase gate would add nothing for it. A path-scoped
    entry, the same runner with an option, or another key is not that call, and
    the widening stands. Every other widening stands whatever the gate holds:
    its reason is not a suite the unscoped call is known to run."""
    meta = meta if isinstance(meta, dict) else {}
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else {}
    support = info.get("support") or []
    if info.get("widen") is not None and support:
        said = _support_settled(support, phase, meta, project, task_entries,
                                build, lister)
        if said is None:
            return [], info
        info = {"suites": list(info.get("selected") or []), "widen": None,
                "support": support,
                "lines": [ln for ln in info.get("lines") or []
                          if ln != info["widen"]] + [said]}
    if info.get("widen") is not None or not info.get("suites"):
        return [], info
    steps, why = entries_for(info["suites"], phase, meta, project, lister=lister)
    if why:
        return [], dict(info, widen=why)
    steps, left, said = left_to_run(steps, info["suites"], task_entries, build)
    return steps, dict(info, suites=left, lines=list(info["lines"]) + said)


def _support_settled(support, phase, meta, project, task_entries, build,
                     lister=None):
    """The line saying which declared entry runs every suite the changed
    support files can reach, or None when no entry does."""
    spelling, why = _spelling(phase, meta)
    if why:
        return None
    wanted = set(support)
    declared = _declared_calls(task_entries, build)
    covering, carried = [], set()
    for command in _spell(spelling, support, project, lister):
        entry, inside = _unscoped_entry(command, wanted, declared)
        if entry is None:
            return None
        covering.append(entry)
        carried |= inside
    if not covering or carried != wanted:
        return None
    entry = covering[0]
    return ("affected: test support %s changed and no arm selected it - it "
            "does not widen to the phase gate: the task's gate entry `%s` runs "
            "`%s`, the same call with no path, which runs every suite that "
            "leans on it" % (", ".join(support), entry, build.get(entry, entry)))


# --- gathering the facts the selection reads --------------------------------------
# THE ONE PLACE THAT MEASURES. Everything above reads `facts` and nothing else;
# this is what fills it, for both of the callers that ask the selection a
# question: `run-test-gate.py`'s affected steps, over a task's whole change, and
# `audit-task.py`'s gate-reach check, over one declared file at a time. They
# were two hand copies once and had drifted - one ran a listing with no process
# group, so a timed-out listing's children outlived the verb, and the two ran
# under different bounds - so a change to the facts one gathered changed only
# one of the two answers. A listing runs the way a plan command runs: the
# plan's node preamble in front, the plan's shell, stderr folded into the
# output, and on timeout its whole tree stopped by `_proc_group.stop_and_drain`.
LISTING_TIMEOUT_SECONDS = 120
GIT_TIMEOUT_SECONDS = 30
# How many listing commands `prefetch_listings` runs at once; each is a process.
PREFETCH_WORKERS = 8
# The exits a listing that gave no verdict carries, kept apart from any exit a
# listing answers with: the shell's own words for "not run" and "timed out".
_COULD_NOT_RUN_EXIT = 127
_TIMED_OUT_EXIT = 124


def run_listing(project, meta, command, timeout):
    """`{exit, output}` for one listing (or version) command run in `project`
    under `timeout` seconds. A command that could not start answers exit 127
    and one that outlived its bound exit 124 (or the exit its stopped root
    gave), each with the output saying so, so no reader takes either for an
    answer: `_ran` and `_gate_derive.version_facts` read anything but 0 as no
    answer."""
    meta = meta if isinstance(meta, dict) else {}
    wrapped = _evidence_io.resolved_commands(
        {"meta": {"nodePreamble": meta.get("nodePreamble")}}, [command])[0][1]
    argv, env, refusal = _proc_group.shell_invocation(wrapped)
    if argv is None:
        return {"exit": _COULD_NOT_RUN_EXIT,
                "output": "could not run: %s" % (refusal,)}
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    kwargs.update(_proc_group.group_kwargs())
    try:
        proc = subprocess.Popen(argv, cwd=project, env=env, **kwargs)
    except Exception as exc:
        return {"exit": _COULD_NOT_RUN_EXIT, "output": "could not run: %s" % (exc,)}
    try:
        out, _err = proc.communicate(timeout=timeout)
        return {"exit": proc.returncode,
                "output": (out or b"").decode("utf-8", "replace")}
    except subprocess.TimeoutExpired:
        text, _confirmed = _proc_group.stop_and_drain(proc)
        code = proc.returncode if proc.returncode not in (None, 0) \
            else _TIMED_OUT_EXIT
        return {"exit": code,
                "output": "%s\ndid not finish within %ss" % (text, timeout)}
    except BaseException:
        # An interrupt lands here too, and the group goes before it leaves: a
        # listing's children must not outlive the verb that started them.
        _proc_group.stop_and_drain(proc)
        raise


def tree_files(project):
    """The project's files, tracked and untracked-but-not-ignored, as plan
    paths; None when git cannot list them."""
    try:
        done = subprocess.run(["git", "-C", project, "ls-files", "-z", "--cached",
                               "--others", "--exclude-standard"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    # `ls-files` prints from its cwd, the project, which is where the plan's
    # paths are spelled from: said so to the pair.
    hc = _loader.load_hooks_config(modname="audit__config")
    found = [hc.git_to_plan(p, project, project, cwd=project)
             for p in done.stdout.decode("utf-8", "replace").split("\0") if p]
    return [p for p in found if p]


def _python_sources(project, files):
    """`{path: text}` for every `.py` of `files` that can be read."""
    sources = {}
    for path in files:
        if not path.endswith(".py"):
            continue
        try:
            with open(os.path.join(project, *path.split("/")), encoding="utf-8",
                      errors="replace") as fh:
                sources[path] = fh.read()
        except OSError:
            continue
    return sources


def _listing_into(ran, project, meta, command):
    if command not in ran:
        ran[command] = dict(_gate_derive.listing_fact(
            run_listing(project, meta, command, LISTING_TIMEOUT_SECONDS)),
            command=command)
    return ran[command]


def prefetch_listings(project, meta, paths, seen, workers=PREFETCH_WORKERS):
    """Run each recorded listing for each of `paths` ALONE, side by side, into
    `seen` - the answers a later `gather_facts([path], seen=seen)` reads
    instead of running. A project's listing can take seconds a path, and the
    paths do not wait on one another."""
    ran = seen.setdefault("listings", {})
    commands = sorted(set(
        _gate_derive.listing_command(template, [path])
        for template in listing_templates(meta).values()
        for path in paths) - set(ran))
    if not commands:
        return
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(workers, len(commands)))) as pool:
        answers = dict(zip(commands, pool.map(
            lambda cmd: run_listing(project, meta, cmd, LISTING_TIMEOUT_SECONDS),
            commands)))
    for command, res in answers.items():
        ran[command] = dict(_gate_derive.listing_fact(res), command=command)


def gather_facts(project, meta, changed, seen=None, sources=True):
    """Every observation `select` reads about `changed`, measured in `project`.

    `seen` carries what several gatherings over one tree ask once: the version
    answer, each listing command's answer, the tree's files and its Python
    sources. A caller with its own reading of the tree's files - a project that
    is no checkout - hands it in as `seen["files"]`; otherwise git's answer is
    read, and a tree git cannot list has no suites and no sources. `sources`
    False leaves the Python sources out, for a caller asking first whether the
    listing alone settles the question."""
    meta = meta if isinstance(meta, dict) else {}
    seen = {} if seen is None else seen
    derived = _derived(meta)
    templates = listing_templates(meta)
    # The all-runners listing is asked only when a suite changed: it is what
    # the walk arm reads its runners from, and nothing else here reads it.
    edited = changed_suites(changed)
    every = all_template(meta) if edited else None
    facts = {}
    if "related" in templates or every:
        if "version" not in seen:
            seen["version"] = _gate_derive.version_facts(
                derived, lambda cmd: run_listing(project, meta, cmd,
                                                 GIT_TIMEOUT_SECONDS))
        facts.update(seen["version"])
    ran = seen.setdefault("listings", {})
    for key, template in sorted(templates.items()):
        facts[key] = _listing_into(ran, project, meta,
                                   _gate_derive.listing_command(template, changed))
    if every:
        facts["all"] = _listing_into(ran, project, meta, every)
    if "files" not in seen:
        seen["files"] = tree_files(project)
    files = seen["files"]
    facts["suites"] = [p for p in files or [] if _phases.is_suite_path(p)]
    # A changed suite is read for the walk arm whatever its language: the
    # lints that walk it are Python whether or not it is.
    if sources and files is not None \
            and (edited or any(p.endswith(".py") for p in changed or [])):
        if "sources" not in seen:
            seen["sources"] = _python_sources(project, files)
        facts["pySources"] = seen["sources"]
    return facts


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
