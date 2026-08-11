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

WHY `ast`, NOT A REGEX. An import can be nested inside a function, a `try`, a selftest -
`_help.py` reaches for `_panel_settings` from inside its own selftest, five lines of comment
explaining why that one is safe. A textual grep sees line noise; `ast.walk` sees a real edge
whether it is module-level or fifty lines deep in a function body, which is the only way a
lint like this is worth trusting.

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

# The module structure, position-indexed: LAYERS[0] is layer 0, the floor. Built from the
# REAL import graph (see the module docstring), not aspiration - `import_graph()` and the
# selftest's real-tree cases are what keep this honest as the tree grows.
# --- layer table --------------------------------------------------------------
LAYERS = (
    ("_output",),
    # _deps (this module) imports only _output, the safe_stdio guard - same as every
    # other member of this layer - so it belongs beside them, not in a layer of its own.
    ("_ui_theme", "_loader", "_fmt", "_manifest_io", "_areas", "_policy", "usage_ledger",
     "_deps"),
    ("_panel_settings", "_panel_ui", "_report_html", "_report_ui"),
    ("_help", "_report_usage"),
    ("_panel_discovery",),
    ("_panel_state",),
    ("_panel_write",),
    ("panel-server", "render-report", "audit-status", "audit-doctor", "audit-usage",
     "validate-manifest", "validate-config", "audit-journal", "audit-lock",
     "gen-demo-manifest", "gen-demo-usage", "migrate-manifest"),
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


def import_graph(script_dir=None):
    """The real static import graph of scripts/*.py.

    Returns `(edges, broken)`: `edges` is a sorted list of unique `(importer, imported)`
    pairs (basenames, no `.py`), `broken` is a sorted list of basenames that would not
    parse. Flat `os.listdir`, `.py` only, nothing skipped silently - a file that will not
    parse is reported in `broken` rather than dropped from the scan, the same rule
    `_output.entries_missing_guard` and `_output.house_style_violations` both follow.

    A hyphenated name (every entry point) can appear as an IMPORTER - it runs as a command
    and can `import _loader` like anything else - but never as an IMPORTED target, since
    `import panel-server` is not legal Python and nothing can spell that edge.
    """
    script_dir = script_dir or _HERE
    files = {}
    for fname in sorted(os.listdir(script_dir)):
        if fname.endswith(".py"):
            files[fname[:-3]] = fname
    sibling_names = set(files)

    edges = set()
    broken = []
    for mod, fname in sorted(files.items()):
        path = os.path.join(script_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=fname)
        except (OSError, SyntaxError):
            broken.append(mod)
            continue
        for imported in _imported_sibling_names(tree, sibling_names, mod):
            edges.add((mod, imported))
    return sorted(edges), sorted(broken)


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
    """(hookfile, importedmodule) pairs: every static hooks/*.py import of a scripts name.

    A hook's own sibling (`_config`, etc.) is not in `script_names` and is never flagged -
    only a name that is genuinely one of scripts/*.py's own modules counts. A hooks file
    that will not parse is reported (as a violation, by the caller) rather than skipped.
    """
    hits = []
    for fname in sorted(os.listdir(hooks_dir)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(hooks_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=fname)
        except (OSError, SyntaxError):
            hits.append((fname, None))  # None: caller renders this as "does not parse"
            continue
        for imported in _imported_sibling_names(tree, script_names, None):
            hits.append((fname, imported))
    return hits


def layer_violations(script_dir=None, hooks_dir=None, layers=None):
    """(file, what) tuples: everything wrong with the real tree against LAYERS.

    Four kinds, each its own wording so a failure names what actually broke:
      - a file on disk with no LAYERS entry, or a LAYERS entry with no file (stale table
        entry is drift too - a name that used to exist and was deleted without updating
        the table is exactly as wrong as a new file nobody added to it);
      - an import cycle;
      - an edge where the importer's layer is not STRICTLY above the imported's (same
        layer included - a same-layer import is still not downward);
      - a hooks/*.py static import of a scripts/ module name, with no exceptions - there was
        one, for one import, and both are gone (F11; see the module docstring).
    A file that will not parse is its own violation in every one of the four passes it
    would otherwise take part in, rather than being dropped from the scan.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    layers = layers if layers is not None else LAYERS
    violations = []

    on_disk = set()
    for fname in sorted(os.listdir(script_dir)):
        if fname.endswith(".py"):
            on_disk.add(fname[:-3])
    assigned = set(_all_names(layers))

    for mod in sorted(on_disk - assigned):
        violations.append((mod + ".py", "on disk but not assigned a layer in LAYERS"))
    for mod in sorted(assigned - on_disk):
        violations.append((mod + ".py",
                            "assigned a layer in LAYERS but no such file exists "
                            "(stale table entry)"))

    edges, broken = import_graph(script_dir)
    for mod in broken:
        violations.append((mod + ".py",
                            "file does not parse; cannot be scanned for import edges"))

    for importer, imported in edges:
        li = _layer_of(importer, layers)
        lj = _layer_of(imported, layers)
        if li is None or lj is None:
            continue  # already named above as unassigned
        if not (li > lj):
            violations.append((importer + ".py",
                                "imports %s (layer %d) from layer %d - not strictly "
                                "downward" % (imported, lj, li)))

    cycle = _find_cycle(edges)
    if cycle:
        violations.append((cycle[0] + ".py", "import cycle: " + " -> ".join(cycle)))

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


# --- rendering ----------------------------------------------------------------
def render(script_dir=None, layers=None):
    """A deterministic module map: every layer, its members, each member's out-edges.

    The format is committed to from this task on - a later phase generates the guide's
    module map from this exact text, under a drift lint, so two calls on an unchanged tree
    must be byte-identical. Stable inputs only: `LAYERS`' own tuple order for layers, a
    sorted() member list within a layer, sorted() edges per member.
    """
    layers = layers if layers is not None else LAYERS
    edges, broken = import_graph(script_dir)
    out_edges = {}
    for importer, imported in edges:
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
    """Sorted `(basename_with_ext, kind)` for every hooks/*.py and scripts/*.py file.

    `kind` is `"scripts"` or `"hooks"` - callers need it only for readable
    violation messages, not for the matching rule itself (a filename is a
    filename regardless of which directory it lives in).
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    out = []
    for fname in sorted(os.listdir(script_dir)):
        if fname.endswith(".py"):
            out.append((fname, "scripts"))
    if os.path.isdir(hooks_dir):
        for fname in sorted(os.listdir(hooks_dir)):
            if fname.endswith(".py"):
                out.append((fname, "hooks"))
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
    for fname, _kind in _real_source_files(script_dir, hooks_dir):
        if tree_block is None or fname not in tree_block:
            violations.append((fname, "missing from the '%s' tree" % _TREE_HEADING))
        if not any(fname in h for h in headings):
            violations.append((fname, "no '### ' heading in '%s' mentions it"
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
    for fname, kind in _real_source_files(script_dir, hooks_dir):
        path = os.path.join(script_dir if kind == "scripts" else hooks_dir, fname)
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
            violations.append((fname,
                                "%d lines but only %d non-selftest section header(s) "
                                "(# --- name ---); needs >= 2 to be navigable"
                                % (len(lines), headers)))
    return violations


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
    check("r2 every real edge points strictly downward: %r" % (real_violations,),
          not by_what("not strictly downward"))
    check("r3 every real scripts/*.py file is assigned a layer, and LAYERS carries no "
          "stale entry: %r" % (real_violations,),
          not by_what("not assigned a layer") and not by_what("stale table entry"))
    check("r4 every real scripts/*.py file parses: %r" % (real_broken,), not real_broken)

    # Read the RAW hooks scan directly as well as through layer_violations(). The raw list
    # is what NAMES an offender; the filtered one is what a build reads. They were two
    # different facts while an allow-list sat between them, and the point of removing it is
    # that they are now one - so both are asserted, and a suppression reintroduced anywhere
    # in between makes exactly one of them fail.
    real_on_disk = set()
    for _fname in sorted(os.listdir(_HERE)):
        if _fname.endswith(".py"):
            real_on_disk.add(_fname[:-3])
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
            for fname, _kind in _real_source_files(src_b, hk_dir):
                if not any(fname in h for h in headings):  # tree check dropped entirely
                    found.append((fname, "no section heading"))
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
