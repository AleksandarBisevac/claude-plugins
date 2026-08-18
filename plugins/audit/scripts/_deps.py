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

AND A WRAPPER AND ITS CALL SITES DO NOT HAVE TO SHARE A FILE. `_doctor_report._load` is
imported by six modules; the `_loader` import is in the module that DEFINES it and the `.py`
literal is in the module that CALLS it, so a scan reading one tree at a time sees neither half
as an edge and twelve real dependencies report as none. `_wrapper_map` therefore runs over the
WHOLE tree before any edge is judged, and `_borrowed_wrapper_names` reads the two spellings a
borrower can use. Nothing in the tree borrowed one when this was written, which is exactly why
it had to be written before the first module did rather than after.

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

This module carries no `--selftest` of its own any more; its 73 cases live in
`plugins/audit/tests/test__deps.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. The move retired NO edge, and that was measured per
call site rather than assumed: this file makes no `_loader` call at all, and its only
static sibling import (`_output`, twice) is production both times. `KNOWN_LAYER_DEBT`
therefore stayed at 17 and `--render`'s output is byte-identical across the move —
which is what a fence pinned in `PLUGIN-BUILD-GUIDE.md` requires.
"""

import ast
import os
import re
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
     "_usage_core", "_deps", "_refs",
     # `_locks` is `audit-lock.py`'s read side: where a lock lives, what it may be
     # called, and whether its holder is alive. It reaches nothing but `_output`,
     # and it had to land at L1 rather than beside its command because
     # `hooks/_config.py` loads it too - a hook may not import scripts/, so the
     # SMALLER the module it resolves by path on every tool call, the better.
     "_locks",
     # `_journal_io` is `audit-journal.py`'s trail: the row shape, the chain, where
     # a journal lives, and what `verify` checks. Same reasoning as `_locks`, and
     # the same hook argument - `hooks/_config.py` asks it for `journal_dir` on
     # every tool call. It reaches nothing but `_output`, and it had to be at L1
     # because `_help` (L3) needs it too.
     "_journal_io",
     # `_demo_cast` is three fictional identities the two demo generators must
     # agree on - the smallest module here, and the right size for the fact: the
     # alternative was not a bigger module but a second copy nothing would compare.
     "_demo_cast",
     # `_manifest_vocab` is the manifest's words - the status/risk/tests enums, the
     # known-key sets per level, and the four shape checks every level shares. It
     # holds no rule and reaches nothing but `_output`, which is exactly why it can
     # sit at the floor: FOUR modules at L2 read it, and a vocabulary copied into
     # four files is four vocabularies that disagree the first time one learns a
     # word. `TERMINAL` is deliberately NOT here - it is `_manifest_io`'s, and
     # holding it would put this module at L2 and its consumers at L3.
     "_manifest_vocab"),
    ("_panel_ui", "_report_html", "_report_ui", "_usage_analytics",
     # `_config_rules` is `validate-config.py` without its `main()`. It imports
     # `_policy` (L1), so L2 is the lowest layer it can occupy - and its deepest
     # consumer, `_panel_settings`, therefore had to move UP one, from here to L3.
     # Moving ONE module was the whole cost of making that edge downward; inserting
     # a layer would have renumbered every entry in KNOWN_LAYER_DEBT below without
     # a single edge changing.
     "_config_rules",
     # The four pieces `_manifest_rules` was cut into. Each answers ONE of the
     # subjects that file held, each reads `_manifest_vocab` at L1, and none reads
     # another - which is what lets all four share a layer. `_manifest_phases` also
     # reads `_manifest_io` (TERMINAL) and `_areas`, both L1.
     #   `_manifest_phases`     the one walk over phases and tasks, and what a
     #                          phase carries (claim, area tag, budget, sign-off)
     #   `_manifest_ado`        `meta.ado`, the connector config - ONE front door,
     #                          shared with the panel's PUT /api/ado
     #   `_manifest_typos`      the did-you-mean detectors (model ids, skill names)
     #   `_manifest_crossrefs`  ids, references, cycles, fileIndex, bugs, proposals
     "_manifest_phases", "_manifest_ado", "_manifest_typos", "_manifest_crossrefs",
     # `_status_facts` is `audit-status.py`'s machine-readable half: the rollup,
     # readiness, the submodule preflight and the gate. Same reasoning and the same
     # floor - `_manifest_io`/`_areas` at L1 below it, `_panel_state` at L5 above it.
     "_status_facts",
     # `_doctor_report` is the piece all six of `audit-doctor`'s check modules sit
     # on: the `Report` collector, the `_load` wrapper and the two constants. It
     # holds no check, which is exactly why it can sit here while its consumers
     # reach as high as L5 - it imports `_loader` (L1) and nothing else. The
     # wrapper being SHARED is what `_borrowed_wrapper_names` was written for:
     # without it the twelve runtime loads spelled in those six files would be a
     # dozen edges nothing could see.
     "_doctor_report"),
    # The usage metering stack is a three-link chain, `_usage_core` -> `_usage_analytics`
    # -> `usage_ledger`, so it needs three layers under its lowest consumer. That consumer
    # is `_report_usage`, which sat here beside `_help` and now sits one layer up: moving
    # ONE module was the whole cost of making room, where inserting a layer would have
    # renumbered every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    # `_report_usage` reaches nothing at layer 4 or above, and only render-report (L7)
    # reaches it, so the move is free.
    # `_panel_settings` sits here rather than at L2, and the move was forced by
    # `_config_rules`: it reads the four enum tuples off the module that ENFORCES
    # them, and a consumer at the same layer is still not strictly downward. It
    # reaches nothing at L3 and nothing at L3 reaches it, so the move was free -
    # `_panel_page` (L4), `_panel_write` (L6) and `panel-server` (L7) are all
    # still strictly above it.
    # `_manifest_rules` sat at L2 and moved up one, which is the whole structural
    # cost of cutting it into five: the four pieces it now orchestrates each sit at
    # L2 above `_manifest_vocab`, and a consumer AT L2 is still not strictly
    # downward. It reaches nothing at L3 and nothing at L3 reaches it, so the move
    # is free - `_panel_state` (L5) and the four L7 commands that import it are all
    # still strictly above it, and the alternative (inserting a layer) would have
    # renumbered every entry in KNOWN_LAYER_DEBT below without one edge changing.
    # `_usage_viz` - how the Usage section formats a number and draws a bar -
    # lands here because it reaches `_report_html` at L2 and nothing deeper, and
    # it has to be BELOW the three renderers that all read it. Its sibling
    # `_usage_load` did NOT land beside it: it runtime-loads `usage_ledger`,
    # which is at this layer, and a load at the same layer is not strictly
    # downward. The lint said so the first time this table was written, and the
    # answer was to put the reader above what it reads rather than to widen the
    # rule.
    # The two doctor checks that reach no further than L2 land here, at the first
    # layer that holds their edges strictly downward, rather than beside the other
    # four: `_doctor_ado` runtime-loads `_manifest_io` (L1) for the task walk, and
    # `_doctor_hygiene` imports `_locks` (L1) and loads nothing at all. Putting the
    # seven doctor modules in one layer would have been a nicer picture and a false
    # one - four of them genuinely sit higher, so the layer would have had to be L5
    # and three modules would carry a position nothing about them requires.
    ("_help", "usage_ledger", "_panel_settings", "_manifest_rules",
     "_usage_viz", "_doctor_ado", "_doctor_hygiene"),
    # `_panel_page` (the panel's assembled page: the substitution chain and the
    # ~1,450 lines of cases that read the result) lands here rather than beside
    # `_panel_state`, and that placement is the whole cost of the split. Its
    # deepest reach is `usage_ledger` at L3 - `_panel_ui`/`_panel_settings` are
    # L2, `_ui_theme`/`_loader` L1, `_help` L3 - so L4 is the first layer that
    # holds every one of its edges strictly downward. Sitting beside
    # `_panel_discovery` and the Usage renderers costs nothing: it reaches none of
    # them, and none of them reaches it. The alternative was a new layer, which
    # renumbers every entry in KNOWN_LAYER_DEBT below without a single edge
    # changing.
    # The three renderers the Usage section was cut into land here for one reason:
    # each reads `_usage_viz` at L3, so L4 is the first layer strictly above it.
    # None of the three reaches another, which is what lets `_report_usage` fold
    # all three into one order at L5.
    #   `_usage_overview`  what shows on FIRST PAINT (strip, trend, ranked lists)
    #   `_usage_detail`    everything folded behind the `Detail` disclosure
    #   `_usage_markdown`  the Markdown twin - and `_report_md` (L5) reads it
    #                      DIRECTLY rather than through `_report_usage`, which is
    #                      now its own layer-mate and so not strictly below it
    # `_usage_load` (the section's only I/O) is here for a different reason: it
    # runtime-loads `usage_ledger` at L3, so this is the first layer that holds
    # that edge strictly downward. It reaches none of the three renderers.
    # Three of `audit-doctor`'s check modules land here, each at the first layer
    # above what it actually reaches: `_doctor_setup` imports `_manifest_rules`
    # (L3), and `_doctor_trail` / `_doctor_completions` each runtime-load
    # `usage_ledger` (L3) - the same reason `_usage_load` is here and not beside
    # the ledger it reads. None of the three reaches another, which is what lets
    # `audit-doctor` fold all of them into one order.
    ("_panel_discovery", "_panel_page", "_usage_load",
     "_usage_overview", "_usage_detail", "_usage_markdown",
     "_doctor_setup", "_doctor_trail", "_doctor_completions"),
    # `_report_md` (render_html's Markdown twin) and `_report_page` (the whole
    # document) are the report's answer to the same question `_panel_page`
    # answered above, and they land the same way: at the FIRST layer that holds
    # every one of their edges strictly downward, beside whatever already lives
    # there. `_report_md` reaches `_usage_markdown` (L4) and `_report_html` (L2),
    # so L5; `_report_page` reaches `_report_md`, so L6. Neither touches
    # `_panel_state`/`_panel_write` and neither is touched by them, so sharing
    # their layers costs nothing - where a new layer for the pair would renumber
    # every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    #
    # `_report_usage` moved L4 -> L5 and joins them, and that is the whole
    # structural cost of cutting the Usage section into five: the three renderers
    # it folds into one order sit at L4, so their only consumer has to sit above
    # them. It reaches nothing at L5 and nothing at L5 reaches it - `_report_md`
    # goes to `_usage_markdown` directly for exactly that reason - so the move is
    # free, and `_report_page` (L6) is still strictly above.
    #
    # NOT above L6, and that is the design rather than a coincidence: the gate
    # verdict at the top of the report comes from `audit-status` (L7), so
    # `render_html` takes it as an INJECTED callable and render-report.py - which
    # already carries that L7 -> L7 runtime edge, recorded below - supplies it.
    # Reaching the gate from `_report_page` would be a helper calling up, and the
    # runtime-load half of this lint would report it.
    #
    # `_doctor_policy` is here and not at L4 because `check_policy` runtime-loads
    # `_panel_discovery` (L4) for this machine's skills/agents/MCP inventory - the
    # same walk the panel's rules view marks `dead` with, so the two surfaces
    # cannot disagree about which pattern is inert. That single edge is the whole
    # reason the doctor's checks occupy four layers instead of one, and it is the
    # edge `_borrowed_wrapper_names` had to be able to see: it is spelled
    # `_load("_panel_discovery", "_panel_discovery.py")` through a wrapper defined
    # two modules away.
    ("_panel_state", "_report_md", "_report_usage", "_doctor_policy"),
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
#
# AND `_loader.script_path()` REFUSES THE SAME TREE AT RUN TIME. That is one rule with
# two enforcement points, not two rules: this one fails the BUILD, in a checkout, where
# a CI job runs it; that one fails a RUN, in a consumer's installed plugin, where this
# lint has never executed and never will. The failure it prevents is the only silent one
# either of them can produce - the wrong module loaded under the right name - so the
# duplication is deliberate and the two messages name each other rather than drifting
# into two accounts of what the rule is.
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

# `_loader`'s public API is `load`, `load_script`, `load_hooks_config`,
# `script_index` and `script_path`. THREE ARE LEFT OUT ON PURPOSE rather than
# forgotten, and each for the same test: does the call, by itself, make this module
# depend on that one?
#
#   * `load_hooks_config` takes no path at all and resolves `../hooks/_config.py` by
#     construction, so it can never name a scripts/ sibling.
#   * `script_index` takes no name at all - it returns the whole map.
#   * `script_path` RESOLVES, it does not LOAD. It returns a string; nothing is
#     imported, nothing is executed, and a caller that only wants the path has no
#     dependency on the module at that path. `render-report._bench_fixture` is the
#     worked example: it spells `script_path("gen-demo-manifest.py")` and then runs
#     that file as a SUBPROCESS, precisely so the fixture build stays out of this
#     process - listing `script_path` here would invent a `render-report ->
#     gen-demo-manifest` edge out of a `sys.executable` argument. The edges that ARE
#     real remain visible either way: a `script_path(...)` sitting inside a
#     `_load(...)` wrapper call is still a `.py` literal inside that call, which is
#     what `_py_literal_basenames` reads.
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

    Three files wrap the loader (`_doctor_report._load`, `audit-usage._load`,
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


def _sibling_module_aliases(tree, sibling_names):
    """Local name -> sibling module name, for every `import X` / `import X as Y`.

    Only what a CALL can be spelled through: `from X import thing` binds the thing,
    not the module, and is read by `_borrowed_wrapper_names` instead.
    """
    aliases = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in sibling_names:
                aliases[alias.asname or base] = base
    return aliases


def _borrowed_wrapper_names(tree, sibling_names, wrapper_map):
    """Local names that ARE a sibling's loader wrapper, however they were bound.

    A WRAPPER AND ITS CALL SITES DO NOT HAVE TO SHARE A FILE, and until this
    existed the moment they stopped sharing one the edges vanished. `_loader`
    is imported in the module that DEFINES the wrapper; the `.py` literal is
    spelled in the module that CALLS it; and `_loader_wrapper_names` reads one
    tree, so neither file alone carries anything the scan could see. Six
    modules sharing `_doctor_report._load` would have contributed twelve real
    runtime edges and reported none - the exact "configured, green and
    structurally blind" state this module's docstring is about.

    Two spellings, both of which the tree uses: `from X import _load`, and the
    house alias `_load = X._load` sitting with the imports. `wrapper_map` is
    module name -> that module's wrapper names, so a name only counts when the
    thing it points at really is a wrapper.
    """
    aliases = _sibling_module_aliases(tree, sibling_names)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            base = (node.module or "").split(".")[0]
            for alias in node.names:
                if alias.name in wrapper_map.get(base, ()):
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
            if not isinstance(target, ast.Name) or not isinstance(value, ast.Attribute):
                continue
            if not isinstance(value.value, ast.Name):
                continue
            owner = aliases.get(value.value.id)
            if owner and value.attr in wrapper_map.get(owner, ()):
                names.add(target.id)
    return names


def _wrapper_map(trees):
    """module name -> the loader-wrapper names it can be called through.

    Grown to a FIXPOINT rather than in a fixed number of passes: a module that
    borrows a wrapper is itself somewhere the next module can borrow it from
    (`_load = _base._load` is a wrapper under this rule exactly as the original
    `def` is), so a two-pass version would see one hop of a chain and stop.
    """
    sibling_names = set(trees)
    wrapper_map = {}
    for mod, tree in trees.items():
        module_names, function_names = _loader_names(tree)
        wrapper_map[mod] = _loader_wrapper_names(tree, module_names, function_names)
    while True:
        grew = False
        for mod, tree in trees.items():
            borrowed = _borrowed_wrapper_names(tree, sibling_names, wrapper_map)
            if borrowed - wrapper_map[mod]:
                wrapper_map[mod] = wrapper_map[mod] | borrowed
                grew = True
        if not grew:
            return wrapper_map


def _py_literal_basenames(node):
    """Module basenames of every `"....py"` string literal anywhere inside `node`.

    The directory is dropped, so `os.path.join(_output.HOOKS_DIR,
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


def _runtime_loaded_sibling_names(tree, sibling_names, self_name, wrapper_map=None):
    """Base module names `tree` loads at RUNTIME through `_loader`.

    An edge is counted when a `_loader` loading call - direct, under an alias,
    through one of the local wrappers `_loader_wrapper_names` recognises, or
    through a wrapper this module BORROWED from a sibling (`wrapper_map`; see
    `_borrowed_wrapper_names`) - contains a string literal ending in `.py` whose
    basename is one of `sibling_names`. A `modname="usage_ledger"` argument is not
    one (no `.py`), and a hooks/ filename is not one (no such sibling), so neither
    invents an edge.

    `wrapper_map` is None for the `tests/` boundary scan, which asks a narrower
    question (does the PRODUCT reach into tests/) and has no wrapper to follow.

    LIMITATION, deliberate and load-bearing: only a filename SPELLED AS A LITERAL
    INSIDE THE CALL counts. `_loader.load_script("render-report.py")` is read,
    because the literal is right there in the call expression;
    `path = _loader.script_path("audit-journal.py")` on one line followed by
    `_loader.load(path)` on the next is NOT, and neither is any genuinely computed
    name. A target this function cannot READ is not a target it may GUESS - widening
    the scan to "any `.py` literal in the file" would manufacture edges out of error
    messages and doc strings, and the selftest carries the fixture that goes red the
    day someone tries it. One real call site is invisible for this reason today
    (`_panel_state`'s journal loader), and that is a known gap, not a clean scan.
    """
    module_names, function_names = _loader_names(tree)
    wrappers = _loader_wrapper_names(tree, module_names, function_names)
    aliases = {}
    if wrapper_map:
        wrappers = wrappers | _borrowed_wrapper_names(tree, sibling_names,
                                                      wrapper_map)
        aliases = _sibling_module_aliases(tree, sibling_names)
    if not module_names and not function_names and not wrappers and not aliases:
        return []

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        wrapped = isinstance(node.func, ast.Name) and node.func.id in wrappers
        if not wrapped and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name):
            # `_base._load("x.py")` - the wrapper reached through the module it
            # lives in, rather than through a local alias of it.
            owner = aliases.get(node.func.value.id)
            wrapped = bool(owner) and node.func.attr in (wrapper_map or
                                                         {}).get(owner, ())
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
    script_dir = script_dir or _output.SCRIPTS_DIR
    modules, _collisions = _module_files(script_dir)
    sibling_names = set(modules)

    # PARSED ONCE, READ TWICE. The wrapper map is a whole-tree fact - which
    # module a borrowed `_load` came from is not answerable from the borrowing
    # file alone - so every file has to be parsed before any edge is judged.
    parsed = []
    trees = {}
    broken = []
    for mod in sorted(modules):
        for rel, path in modules[mod]:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
            except (OSError, SyntaxError):
                broken.append(rel)
                continue
            parsed.append((mod, tree))
            trees.setdefault(mod, tree)
    wrapper_map = _wrapper_map(trees)

    static = set()
    runtime = set()
    for mod, tree in parsed:
        for imported in _imported_sibling_names(tree, sibling_names, mod):
            static.add((mod, imported))
        for loaded in _runtime_loaded_sibling_names(tree, sibling_names, mod,
                                                     wrapper_map):
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
    script_dir = script_dir or _output.SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else _output.HOOKS_DIR
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
    message naming `tests/test_x.py` is not an edge. EVERY migrated file in `scripts/`
    and `hooks/` names its test file in prose — twice, in its docstring and in the
    pointer `--selftest` prints — so a looser scan would now report the whole tree
    rather than the three pilots it would have reported when this was written.

    A file that will not parse is reported here as well as by the lints that already
    say so; a scan that silently skips it is a scan claiming a clean answer about a
    file it never read.
    """
    script_dir = script_dir or _output.SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else _output.HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else _output.TESTS_DIR

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
# The guide lives at the repo root. Counted off `_output.REPO_ROOT` rather than by
# three `..` segments from this file's own directory: the count WAS this module's
# depth written down, and it was wrong the moment the file moved.
_GUIDE_REL_PATH = "PLUGIN-BUILD-GUIDE.md"


def _guide_path(guide_path=None):
    if guide_path is not None:
        return guide_path
    return os.path.join(_output.REPO_ROOT, _GUIDE_REL_PATH)


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
    script_dir = script_dir or _output.SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else _output.HOOKS_DIR
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
    script_dir = script_dir or _output.SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else _output.HOOKS_DIR
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
_UI_DIR = os.path.join(_output.SCRIPTS_DIR, "ui")

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
# ONE entry, down from the seventeen that became visible the moment this module
# learned to read `_loader` calls. None of those seventeen was ever new: each had
# been in the tree for months, certified clean by a lint that walked only
# `ast.Import` while most of this codebase reaches its siblings at runtime.
#
# HOW THE OTHER SIXTEEN WENT, because the shape generalises. Every one of them was
# a module being used as a LIBRARY that happened to be shaped as a COMMAND, and in
# every case the answer was the same: move the logic, never the call. Five files
# came out from under five entry points -
#
#   `_manifest_rules` (L2)  <- validate-manifest.py   retired 4
#   `_status_facts`  (L2)  <- audit-status.py        retired 3
#   `_config_rules`  (L2)  <- validate-config.py     retired 3
#   `_locks`         (L1)  <- audit-lock.py          retired 3
#   `_journal_io`    (L1)  <- audit-journal.py       retired 2
#   `_demo_cast`     (L1)  <- gen-demo-usage.py      retired 1
#
# - and each entry point kept its `main()`, which is the half that was genuinely a
# command. `_panel_settings` moved from L2 to L3 in the same change, because
# `_config_rules` imports `_policy` (L1) and so cannot sit below L2, and a consumer
# AT L2 is still not strictly downward. Moving one module was the whole cost.
#
# A SEVENTEENTH EDGE WENT THAT WAS NEVER IN THIS TABLE, AND THAT MATTERS MORE THAN
# THE COUNT. `_panel_state -> audit-journal` was real and deliberately invisible:
# it spelled `script_path()` on one line and `load()` on the next, because
# `_runtime_loaded_sibling_names` reads only a literal inside the call, and the
# comment there said so out loud. `rt4` still pins that blindness as a decision -
# the scan is narrow on purpose - but the edge itself is gone, not hidden: the
# journal is `_journal_io` at L1 now and `_panel_state` imports it like anything
# else. A count that a blind spot flatters is not a smaller debt, so the fix had
# to be the dependency becoming legal rather than the spelling staying unreadable.
#
# THE LIST MAY ONLY SHRINK. `r2` asserts EXACT equality, so a new violation fails
# the build, and retiring one also fails it until the entry is deleted on purpose.
# An allowlist that silently absorbs both directions is how debt becomes
# permanent; this one cannot, because fixing something breaks it too.
KNOWN_LAYER_DEBT = (
    # THE ONE THAT DID NOT GO, AND WHY IT IS NOT A SPELLING PROBLEM.
    # `_panel_state.render_report()` is the panel's Export button, and it calls
    # `render-report.py`'s own `main()` in-process - deliberately, so the panel
    # takes the same code path the CLI takes, with no interpreter discovery and
    # the same behaviour on Windows.
    #
    # There is no logic here to extract downward. What the panel wants is not a
    # rule it could share but the WHOLE report pipeline ending in two files on
    # disk, and that pipeline reaches `_report_page` at L6 - above this module's
    # own L5. A helper holding it could therefore not sit anywhere `_panel_state`
    # may import from. The two real fixes are both larger decisions than this
    # entry: move `_panel_state` above the report stack (which renumbers the
    # table), or split a writer out of `render-report.main()` and rehome the
    # report modules under it.
    #
    # WHAT WAS DELIBERATELY NOT DONE: swapping the in-process call for a
    # `script_path()` + subprocess. `_deps` does not count that as an edge, by
    # design and for a good reason (nothing is imported, nothing is executed
    # here) - which is exactly why reaching for it would be laundering. It would
    # also change behaviour: a second interpreter, a different failure surface,
    # and an exit code where there is now an exception. A fix that makes an edge
    # invisible rather than absent is a regression wearing a green suite.
    ("panel/_panel_state.py",
     "runtime-loads render-report (layer 7) from layer 5 - not strictly downward"),
)


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to `--render`'s usage line, which
        # would exit 2 with no word about the flag. It deliberately does NOT print
        # the `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_deps.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__deps.py - run that file instead.")
        raise SystemExit(0)
    if "--render" in sys.argv[1:]:
        sys.stdout.write(render())
        raise SystemExit(0)
    sys.stderr.write("usage: _deps.py --selftest | --render\n")
    raise SystemExit(2)
