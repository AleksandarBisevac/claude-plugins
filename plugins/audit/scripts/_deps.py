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

ONE FINDING THIS MODULE DOES NOT PAPER OVER: `hooks/_config.py` has a real, guarded, static
`import _manifest_io` (with a plain-JSON fallback if it fails) — a genuine violation of "hooks
import nothing from scripts," predating this checker. Fixing it is out of this file's scope
(this task may only touch `_deps.py`), so the selftest names that ONE known exception instead
of asserting a false "hooks are clean," and still fails on any OTHER or NEW hooks->scripts
import, which is the drift this checker exists to catch.
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.join(os.path.dirname(_HERE), "hooks")

# The module structure, position-indexed: LAYERS[0] is layer 0, the floor. Built from the
# REAL import graph (see the module docstring), not aspiration - `import_graph()` and the
# selftest's real-tree cases are what keep this honest as the tree grows.
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

# hooks/_config.py's one pre-existing, guarded exception (see module docstring). Named here
# once so the checker and its selftest read the same fact rather than two facts drifting.
_KNOWN_HOOKS_EXCEPTIONS = frozenset((("_config.py", "_manifest_io"),))


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
      - a hooks/*.py static import of a scripts/ module name, except the one documented,
        guarded, pre-existing case this file's docstring names (`_KNOWN_HOOKS_EXCEPTIONS`).
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
            if (hookfile, imported) in _KNOWN_HOOKS_EXCEPTIONS:
                continue
            violations.append((hookfile,
                                "imports scripts module %s - hooks must not depend "
                                "on scripts" % imported))

    return violations


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

    # Read the RAW hooks scan directly, not through layer_violations() - that function
    # deliberately suppresses the one documented exception from its own output, so this
    # is the only way to prove the exception list still matches the real tree exactly
    # (neither grown a new import nor gone stale by the known one disappearing).
    real_on_disk = set()
    for _fname in sorted(os.listdir(_HERE)):
        if _fname.endswith(".py"):
            real_on_disk.add(_fname[:-3])
    real_hooks_raw = [(f, m) for f, m in _hooks_scripts_imports(_HOOKS_DIR, real_on_disk)
                       if m is not None]
    check("r5 hooks/ imports nothing from scripts/ except the one documented, guarded, "
          "pre-existing exception named in this module's docstring "
          "(hooks/_config.py -> _manifest_io, a JSON-fallback-guarded read) - any OTHER "
          "or NEW hooks->scripts import is drift and must fail here: %r"
          % (real_hooks_raw,),
          sorted(real_hooks_raw) == sorted(_KNOWN_HOOKS_EXCEPTIONS))
    check("r5b ...and that one exception is correctly SUPPRESSED from layer_violations()'s "
          "own output, so a clean run does not cry wolf about a fault already on record",
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

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


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
