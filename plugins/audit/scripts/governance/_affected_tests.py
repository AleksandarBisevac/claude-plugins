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
test files to the changed modules; the e2e runner's changed listing
(`listing.e2eChanged`) when one is recorded; and, when the project has e2e specs
that no recorded listing can see, every one of them.

PURE. Every observation -- a listing's exit and output, the version answer,
the Python sources, the tree's suite files -- arrives in `facts`, gathered once
by the caller (`run-test-gate.py`). Nothing here shells out or reads a file.

WIDEN, NEVER EMPTY. A listing that cannot answer, a version that does not
match, a `.py` change with no sources to graph, a changed path no arm reads,
a changed file under a test directory no arm selected (test support), and
suites with no command spelling to run them under all answer `widen` with
the reason: the caller adds the PHASE gate. An empty selection is only ever an
answer every arm gave.

NOT TWICE. A step whose suites a declared entry already runs whole - the
step's own command with its paths taken out (`left_to_run`) - is left out and
said, so a full-sweep key does not run the same suites again beside it.
"""

import ast
import os
import shlex
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
#                                       row's measured-not-declared steps carry)

ARMS = ("related", "python", "e2e-changed", "e2e-widening")
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


def _refs(path, source):
    """`(names, scripts)` -- the dotted names `source` imports (each with its
    parent packages, which importing it runs) and the `*.py` file names it hands
    to a loader call (a script loaded by its file name). None when it does not
    parse."""
    try:
        tree = ast.parse(source, path)
    except (SyntaxError, ValueError):
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


def _python_arm(changed, sources):
    """`{test: basis}` for every Python test whose import closure reaches a
    changed `.py` path. A changed path whose source is gone (a deletion, a
    rename's old side) is still a node, so its importers are found."""
    targets = set(p for p in changed if p.endswith(".py"))
    known = sorted(set(sources) | targets)
    by_name, by_file = {}, {}
    for path in known:
        for name in _module_names(path):
            by_name.setdefault(name, set()).add(path)
        by_file.setdefault(path.rsplit("/", 1)[-1], set()).add(path)
    refs = dict((p, _refs(p, sources[p])) for p in sources)
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

    if any(p.endswith(".py") for p in changed):
        sources = facts.get("pySources")
        if not isinstance(sources, dict):
            return _widened("python: a .py path changed and no sources were "
                            "read to graph its importers", lines)
        for path, basis in sorted(_python_arm(changed, sources).items()):
            add(path, "python", basis)

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
        return _widened("test support: %s changed and no arm selected it - a "
                        "file under a test directory may be what every suite "
                        "leans on" % (", ".join(support),), lines)
    return {"suites": suites, "widen": None, "lines": lines}


# --- what the task's gate already is, and the commands the rest run under --------
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
    meta = meta if isinstance(meta, dict) else {}
    build = meta.get("buildCommands")
    build = build if isinstance(build, dict) else None
    shape, source, _lines = _gate_derive.resolve_shape(phase or {}, build,
                                                       _derived(meta))
    if shape is None:
        return [], ("no path-scoped spelling: no task in this phase declares a "
                    "gate entry naming a path and meta.phaseGate.derived.spelling "
                    "is not set, so the affected suites have no command to run "
                    "under - the task's gate widens to the phase gate")
    scoped = [e for e in shape if not _gate_derive.is_shared_key(e, build)
              and (source == _gate_derive.SPELLING_SOURCE
                   or _phases.gate_entry_paths(e))]
    steps = []
    for arm in ARMS:
        paths = [s["path"] for s in suites if s.get("arm") == arm]
        if not paths:
            continue
        if source == _gate_derive.SPELLING_SOURCE:
            entries = [scoped[0].replace(
                "{paths}", " ".join(shlex.quote(p) for p in paths))]
        else:
            entries, _notes = _gate_derive.repointed_by_runner(
                scoped, build, paths, project, lister=lister)
        for entry in entries:
            named = [p for p in paths if shlex.quote(p) in entry] or paths
            steps.append(("%s%s: %s" % (_evidence_io.DERIVED_STEP_PREFIX, arm,
                                        ", ".join(named)), entry))
    return steps, None


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
    declared = {}
    for entry in task_entries or []:
        words = _words(build.get(entry, entry))
        if words:
            declared.setdefault(tuple(words), entry)
    kept, lines, gone, still = [], [], set(), set()
    for name, command in steps:
        words = _words(command)
        inside = set(w for w in (words or []) if w in paths)
        bare = tuple(w for w in words if w not in paths) if words else None
        entry = declared.get(bare) if inside and bare else None
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


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
