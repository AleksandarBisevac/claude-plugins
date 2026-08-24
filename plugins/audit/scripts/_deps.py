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

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__deps.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. The move retired NO edge, and that was measured per
call site rather than assumed: this file makes no `_loader` call at all, and its only
static sibling import (`_output`, twice) is production both times. `KNOWN_LAYER_DEBT`
therefore did not change across that move, and `--render`'s output is byte-identical —
which is what a fence pinned in `PLUGIN-BUILD-GUIDE.md` requires.
"""

import ast
import io
import os
import re
import sys
import tokenize

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
     # `_branch` answers where a phase's branch forks from and what it is called.
     # It reaches nothing but `_output` - it is arithmetic over the manifest dict
     # plus a git-ref regex - and it sits at L1 because the validator (L2), the
     # doctor (L5) and the naming guard all need the SAME answer. A second
     # expansion of the template would be a second set of branch names.
     "_branch",
     # `_priority` answers which READY task the orchestrator reaches for first.
     # Same shape and same reason as `_branch`: it is arithmetic over the manifest
     # dict, it reaches nothing but `_output`, and it sits at L1 because four
     # surfaces need the SAME answer - `_status_facts` (L2) for the ready list,
     # `_manifest_crossrefs` (L2) for the findings, `_panel_composition` (L4) for
     # the control and `set-priority` for the write. A second expression of the
     # order would BE a second order. `TERMINAL` and the unmet-refs map are
     # `_manifest_io`'s and arrive as ARGUMENTS for exactly this reason: that
     # module is a layer-mate, and readiness must never have a second opinion.
     "_priority",
     # `_commit_trail` answers "is this recorded task.commit still reachable?".
     # L1 because BOTH the doctor (L5) and `repair-commits` (an entry point) ask
     # it, and a second walk over the same tasks putting the same question to git
     # is a second answer waiting to disagree with the first. It reaches nothing
     # but `_output` and git.
     "_commit_trail",
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
     "_manifest_vocab",
     # `_ado_conventions` is what a work item must look like to BELONG on a
     # board - required fields, description skeleton, tag vocabulary, parent. It
     # reaches nothing but `_output`, and it is at the floor for the same reason
     # `_manifest_vocab` is: `_manifest_ado` at L2 grades the config through it,
     # and the writing side will grade the ITEM through it, so a copy in either
     # place would be a second answer to "does this belong here".
     "_ado_conventions",
     # `_ado_fields` is the OTHER half of that: what this project supplies to
     # those fields, per work item type. Same floor and the same argument -
     # `_manifest_ado` at L2 grades the block and `check-ado-item` (an entry
     # point) merges the template into the payload it then grades, so the two
     # sides must share one opinion about which field names are legal. It sits
     # beside `_ado_conventions` rather than inside it because the two answer
     # different questions: one is a property of the BOARD, the other of this
     # project, and a file holding both would be where they start borrowing
     # each other's tables.
     "_ado_fields",
     # `_ado_parent` is WHERE one audit item hangs on the board and whether that
     # place can be true. At the floor for `_priority`'s reason exactly, and it
     # is a layer fact rather than a preference: `_manifest_crossrefs` and
     # `_manifest_ado` are both L2, so neither can import the other while both
     # need the SAME answer - as do `resolve-ado-parent` at L7 and the panel
     # after it. A second expression of "which parent" would BE a second parent.
     # `meta.ado`, the phase list and ADO's backlog payload all arrive as
     # ARGUMENTS, which is also why it owns its own unknown-key loop:
     # `_manifest_vocab` is a layer-MATE, so borrowing that one is the sideways
     # edge this lint refuses, and a case pins the two answers equal.
     "_ado_parent"),
    ("_panel_ui", "_report_html", "_report_ui",
     # The four passes `_usage_analytics` was cut into. Each answers ONE of the
     # questions that file held, each reads `_usage_core` at L1, and none reads
     # another - which is what lets all four share a layer, and what they had to
     # be cut to do: `usage_ledger` at L3 imports all four for its re-export, so
     # L2 is the only layer available to them and a peer edge between two of
     # them would have had nowhere to go. The three readers they all start from
     # (`task_index`, `_tokens`, `_cost`) went DOWN into `_usage_core` for
     # exactly that reason rather than into a shared L2 base.
     #   `_usage_spend`      spend through time: series, window compare, cache
     #   `_usage_economics`  what the work cost: unit economics, bands, budgets,
     #                       retried vs blocked spend
     #   `_usage_routing`    cost per task per model WITHIN a risk band, + advice
     #   `_usage_coverage`   the ledger seen whole: attribution coverage, months
     "_usage_spend", "_usage_economics", "_usage_routing", "_usage_coverage",
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
     # `_ado_drift` answers who wrote a linked work item last, and whether pushing
     # would overwrite them. It is L2 rather than L1 for one concrete reason: it
     # reuses `_usage_core.parse_ts` (L1) instead of writing the tree's FOURTH ISO
     # parser, and a same-layer edge is not a downward edge. Its consumers are the
     # `explain-ado-drift` door and `_doctor_ado` (L3), both above it.
     "_ado_drift",
     # `_status_facts` is `audit-status.py`'s machine-readable half: the rollup,
     # readiness, the submodule preflight and the gate. Same reasoning and the same
     # floor - `_manifest_io`/`_areas` at L1 below it, `_panel_state` at L5 above it.
     "_status_facts",
     # `_help` sat at L3 for its whole life and its edges never asked for it: it
     # reaches `_areas`, `_policy`, `_loader` and `_journal_io`, all L1, and
     # `load_hooks_config` is not a sibling load. It came down to L2 at U3.1
     # because a module parked ABOVE its own edges is not free - it lifts
     # `_panel_discovery` with it, and that was what put `discover` out of reach
     # of the layer-4 module that needs it. `_panel_settings` deliberately does
     # NOT import it, so nothing at L2 reaches it and the move cost nothing.
     "_help",
     # `_doctor_report` is the piece all six of `audit-doctor`'s check modules sit
     # on: the `Report` collector, the `_load` wrapper and the two constants. It
     # holds no check, which is exactly why it can sit here while its consumers
     # reach as high as L5 - it imports `_loader` (L1) and nothing else. The
     # wrapper being SHARED is what `_borrowed_wrapper_names` was written for:
     # without it the twelve runtime loads spelled in those six files would be a
     # dozen edges nothing could see.
     "_doctor_report"),
    # The usage metering stack is a three-link chain, `_usage_core` -> the four
    # analytics passes -> `usage_ledger`, so it needs three layers under its lowest
    # consumer. That consumer
    # is `_report_usage`, which sat here beside `_help` and now sits one layer up: moving
    # ONE module was the whole cost of making room, where inserting a layer would have
    # renumbered every entry in KNOWN_LAYER_DEBT below without a single edge changing.
    # `_report_usage` reaches nothing at layer 4 or above, and only render-report (L7)
    # reaches it, so the move is free.
    # `_usage_bench` sits HERE rather than at L2 with the passes it times, and that is
    # the whole structural cost of cutting `_usage_analytics` into five: it calls all
    # four of them, so it has to be above them. It reaches nothing at L3 and nothing at
    # L3 reaches it - `render-report` (L7) loads it for `_time_best` and is the only
    # thing that names it - so sharing this layer with `usage_ledger` costs nothing,
    # where a new layer would have renumbered every entry in KNOWN_LAYER_DEBT below
    # without a single edge changing.
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
    ("usage_ledger", "_panel_settings", "_manifest_rules",
     # `_usage_bench` drives all four analytics passes (each L2), so L3 is the
     # lowest layer that can reach them; `render-report` loads it for `_time_best`.
     "_usage_bench",
     "_usage_viz", "_doctor_ado", "_doctor_hygiene",
     # `_panel_discovery` came down from L4 with `_help`, for the same reason and
     # by the same measurement: `_help` (now L2) and `_manifest_io` (L1) are its
     # only edges, so L3 is where the graph always put it. The move is what makes
     # `discover` reachable from `_panel_policy` at L4 - at L4 itself it was a
     # layer-mate, and a layer-mate is not strictly downward.
     "_panel_discovery",
     # `_panel_paths` is the floor the panel's read side stands on: the config and
     # manifest paths, and the three modules the panel reads through. It lands here
     # and not at L4 because of what it deliberately does NOT hold - see the note
     # on `_panel_state`'s own layer below, which is where `_manifest_rules` had to
     # stay for the split to fit under L5 at all.
     "_panel_paths"),
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
    # The five pieces `_panel_state` was cut into at U3.1. Each reads
    # `_panel_paths` at L3 and none reads another, which is what lets all five
    # share a layer and lets `_panel_state` fold them into one order at L5 -
    # exactly the shape the `_manifest_rules` split took at L2.
    #   `_panel_viewer`       who is driving the panel, and its identity cache
    #   `_panel_composition`  the plan as shown: phases, tasks, bugs, ADO, areas
    #   `_panel_policy`       the capability policy and what it decides today
    #                         (the one that also reaches `_panel_discovery`, L3)
    #   `_panel_runstate`     locks, the on-disk change stamp, the Plan gate card
    #   `_panel_usage`        the Usage tab's facts (runtime-loads usage_ledger, L3)
    # `_invariants` is the post-hoc reader of `reference/orchestrator.md`'s rules:
    # what a task commit staged, what the phase branch's reflog records, whether
    # each committed manifest state still validates, which model answered a
    # high-risk task, and where the phase forked from. It lands here because of
    # what it reads rather than what reads it - `_manifest_rules` and
    # `usage_ledger` are both L3, so L4 is the first layer that holds every one of
    # its edges strictly downward. That is also why it is not beside
    # `verify-invariants.py`: `audit-status.py` needs the answer for `--gate`, and
    # an entry point asking another entry point is the KNOWN_LAYER_DEBT shape this
    # table exists to keep rare.
    ("_panel_page", "_usage_load", "_invariants",
     "_usage_overview", "_usage_detail", "_usage_markdown",
     "_doctor_setup", "_doctor_trail", "_doctor_completions", "_doctor_policy",
     "_panel_viewer", "_proposals", "_panel_composition", "_panel_policy", "_panel_runstate",
     "_panel_usage"),
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
    # `_doctor_policy` runtime-loads `_panel_discovery` for this machine's
    # skills/agents/MCP inventory - the same walk the panel's rules view marks
    # `dead` with, so the two surfaces cannot disagree about which pattern is
    # inert. It is the edge `_borrowed_wrapper_names` had to be able to see: it is
    # spelled `_load("_panel_discovery", "_panel_discovery.py")` through a wrapper
    # defined two modules away.
    #
    # It sat HERE, at L5, while that reasoning ended "and this is the whole reason
    # the doctor's checks occupy four layers instead of one". At U3.1
    # `_panel_discovery` came down to L3, and the sentence stopped being true - the
    # edge is now strictly downward from L4, so `_doctor_policy` joins the other
    # three check modules there and the doctor's checks occupy three layers. The
    # comment is rewritten rather than left standing over a table that no longer
    # matches it: a stale ARGUMENT is worse than no argument, because the next
    # reader spends their time working out why it is wrong.
    ("_panel_state", "_report_md", "_report_usage"),
    ("_panel_write", "_report_page"),
    ("panel-server", "render-report", "audit-status", "audit-doctor", "audit-usage",
     "validate-manifest", "validate-config", "audit-journal", "audit-lock",
     # `check-ado-item` is the gate `/audit:sync push` runs an item through
     # before creating it. A command rather than a helper because the caller is
     # ORCHESTRATOR PROSE, which reaches Python only through Bash - and a
     # `python3 -c` one-liner naming a source path is the shape
     # `guard-secrets-read` refuses (F20/F22), so the check would be blocked
     # exactly where it matters. It reads `_ado_conventions` at L1 and nothing else.
     "check-ado-item",
     # `explain-ado-drift` is the same shape one question over: it carries
     # `_ado_drift` (L2) to `/audit:sync`'s status table and push plan. NOT a gate
     # though - it exits 0 whatever the answer, because "somebody else moved this
     # card" is the normal state of a board with several teams, and a non-zero exit
     # would label it an error and be switched off within a day.
     "explain-ado-drift",
     # `resolve-ado-parent` is the door onto `_ado_parent`: where each item
     # would hang, and whether that place can be true. A command for the reason
     # `check-ado-item` is one - the caller is orchestrator PROSE reaching
     # Python through Bash, and a `python3 -c` naming a source path is the shape
     # `guard-secrets-read` refuses. A GATE (exit 1 refuses a link) unlike
     # `explain-ado-drift`, because a loop is not a difference of opinion
     # between two teams - it is a link nothing can build.
     "resolve-ado-parent",
     # `resolve-branch` is the door onto `_branch`: which branch a phase forks
     # from, and what it is called. A command rather than a prose instruction
     # because a TEMPLATE has cases prose cannot carry, and rather than a
     # `python3 -c` one-liner for check-ado-item's reason - a one-liner naming a
     # source path is the shape `guard-secrets-read` refuses.
     "resolve-branch",
     # `repair-commits` is the third case around a rewritten history: the guard
     # refuses it, the doctor reports it, and this puts the manifest back to the
     # truth afterwards - by nulling what is unreachable and journaling what was
     # lost, never by guessing a substitute.
     "repair-commits",
     # `verify-invariants` is the door onto `_invariants` (L4): one phase, or
     # every phase that has started. A command for the reason `check-ado-item` is
     # one - the caller is orchestrator PROSE, which reaches Python only through
     # Bash, and a `python3 -c` naming a source path is the shape
     # `guard-secrets-read` refuses (F20/F22).
     "verify-invariants",
     # `set-priority` is the writer behind `/audit:phase priority`: one integer on
     # the index stub, under the index lock, revalidated. A command rather than a
     # prose instruction because the rule it enforces (tier 1 is unique, and a
     # refusal must NAME the current holder) is the same rule the panel's write
     # path asks `_priority.tier_one_holder()` for - two places deciding what is
     # legal are two rules that will disagree.
     "set-priority",
     "gen-demo-manifest", "gen-demo-usage", "migrate-manifest", "audit-task", "materialize-proposal"),
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


_EDGES = {}

_EDGES_KEY = "default tree"


def _scan_edges(script_dir=None):
    """`_scan_edges_once`, memoised for the DEFAULT tree only.

    WHY THERE IS A MEMO HERE AT ALL. A scan parses every `.py` under `scripts/` and
    grows the wrapper map to a fixpoint, and the lints above call it independently:
    `import_graph`, `layer_violations`, `tests_import_violations` and `render` each
    ask for the whole graph because each judges the whole graph. Profiled, one run of
    `tests/test__deps.py --selftest` entered this function 25 times and spent 47.5s
    of its 54s inside - the same answer, computed 25 times, over a tree that cannot
    change while the process runs.

    ONLY THE DEFAULT TREE IS CACHED, which is the `_loader._INDEX` precedent and the
    whole safety of it: a caller that hands over its own `script_dir` - every
    selftest with a fixture tree does - is neither served from the cache nor written
    into it, so nothing a caller passes can poison what the real tree sees.

    AND EACH CALLER GETS ITS OWN COPY. The cached value is the ANSWER, not the
    objects: `static` and `runtime` are sets and `broken` is a list, and handing the
    same three mutable objects to every caller is exactly the module state the house
    style bans - one caller's `.add()` would silently become another's input. Copying
    three small containers costs nothing next to a parse of the tree, and it keeps
    this function's contract byte-identical to the uncached one.
    """
    if script_dir is not None and script_dir != _output.SCRIPTS_DIR:
        return _scan_edges_once(script_dir)
    if _EDGES_KEY not in _EDGES:
        _EDGES[_EDGES_KEY] = _scan_edges_once(_output.SCRIPTS_DIR)
    static, runtime, broken = _EDGES[_EDGES_KEY]
    return set(static), set(runtime), list(broken)


def _scan_edges_once(script_dir=None):
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


# WHICH DOCUMENTS ARE SCANNED IS DERIVED, and this constant is the record of what
# it replaced: three named files, of which this one was the last added. The list
# was wrong the way every hand list here has been wrong - not in what it held but
# in what it left out. `plugins/audit/README.md`, `commands/*.md`, `reference/*.md`
# and the skills are the PRODUCT, `scripts/ui/*/README.md` carries a part count per
# assembled surface, and none of them was read by anything.
#
# Kept as the SEED of a case rather than as the scan's input: these three claim to
# be definitions of how this repo works, so a derivation that stopped reaching one
# of them has gone blind rather than clean, and that is a different failure from
# finding nothing. `_refs.sweep_doc_drift()` holds its list for the same reason and
# says so in the same words.
_PROSE_DOCS = (_GUIDE_REL_PATH, "CLAUDE.md", "CONTRIBUTING.md")

# Every document here is hard-wrapped markdown, which is why the scan hands
# `_prose_number_claim` BOTH neighbouring lines: "print it with" ends a line and the
# command that is the claim's basis begins the next one, and a sentence's past tense
# wraps the same way, so judging a claim by its own line alone would report a line
# that has already satisfied the house rule and a recollection that never claimed
# anything.


def doc_prose_numbers(doc_paths=None):
    """[(docname, lineno, text), ...] -- present-tense numbers in the prose docs.

    The same rule `_output.prose_number_claims()` enforces over the tree's `.py`,
    applied to its `.md`. Both halves read one DERIVED set - every file of their
    extension the repo keeps, minus a row in `_output.PROSE_SCAN_EXEMPT` - so a
    document added to this repo is scanned without anybody remembering to add it.

    It REUSES `_output._prose_number_claim` rather than restating the shapes: a
    second copy of the pattern would be precisely the defect both functions exist
    to catch, and a case asserts there is no second `def` in this file.

    `doc_paths` stays for the callers that hand it ONE fixture document by
    absolute path. Those are labelled by basename, because a temp directory is not
    a thing to print; the derived set is labelled by repo-relative path, because
    half a dozen of its documents are called `README.md`.

    Measured when the case-count family was written: of the five
    `--selftest (N cases)` claims in the guide, TWO were already wrong --
    `_policy.py` at 60 against a real 71 and `_refs.py` at 32 against a real 80.
    Measured when the persistence and completeness families were added: THREE
    more, all in the guide, all wrong -- `KNOWN_LAYER_DEBT` written as 17 twice
    where the table held one entry (F43, which is F39 one document over, copied
    to a place nothing compared it), and a migration total written as 48 where
    the tree held eighty-three files. The qualitative half of every one of those
    notes is worth keeping and is untouched; only the number goes, because only
    the number rots.

    An unreadable document is NAMED, never skipped -- F21's rule. A skip would
    return the same empty list a clean document returns, and "nothing to report"
    would then mean either "clean" or "could not look", which is the quiet
    direction.
    """
    if doc_paths is None:
        scan = _output.prose_scan_set((".md",))
        if scan["problem"] is not None:
            return [(".gitignore", 0, scan["problem"])]
        names = tuple(scan["paths"])
    else:
        names = tuple(doc_paths)
    out = []
    for name in names:
        path = name if os.path.isabs(name) else os.path.join(_output.REPO_ROOT, name)
        label = os.path.basename(path) if os.path.isabs(name) else name
        try:
            with io.open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            out.append((label, 0, "<unreadable: %s>" % label))
            continue
        lines = text.split("\n")
        for lineno, line in enumerate(lines, 1):
            nxt = lines[lineno] if lineno < len(lines) else ""
            prv = lines[lineno - 2] if lineno >= 2 else ""
            claim = _output._prose_number_claim(line, nxt, prv)
            if claim is not None:
                out.append((label, lineno, claim))
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


def _section_header_names(text):
    """The names of every top-level section header in `text`, or None if it
    will not tokenize.

    READ AS TOKENS, NOT AS LINES, AND NOT AS AN AST. A section header IS a
    comment, and `ast.parse` throws comments away entirely - the parser this
    module reaches for everywhere else cannot see one at all, which is why the
    tool here is the tokenizer rather than the AST. What the line regex could
    not see is the difference between a header and a DOCSTRING QUOTING ONE:
    identical characters at the identical column, and only the tokenizer knows
    the second is inside a STRING. A 509-line file whose docstring explained the
    house style by showing two markers passed this lint carrying zero real ones,
    which is the quiet direction of that failure - a prose mention that makes a
    check pass.

    Column 0 only, the same rule the line form had: a header indented inside a
    function is not a landmark a reader scanning the LEFT MARGIN can find.

    None rather than an empty list for a file that will not tokenize: an empty
    list is a real answer ("this file has no headers") and would make a file
    nothing could read indistinguishable from one that was read and found
    wanting. The caller reports the two differently.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    names = []
    for token in tokens:
        if token.type != tokenize.COMMENT or token.start[1] != 0:
            continue
        match = _NAV_HEADER_RE.match(token.line)
        if match:
            names.append(match.group(1).strip())
    return names


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

    A file that will not tokenize is a violation rather than a skip - the same
    rule `tests_import_violations()` follows for a file that will not parse, and
    for the same reason: a scan that silently passes over a file it could not
    read is claiming a clean answer about it.

    A file that will not OPEN is now named on the same argument (F44). It was
    a bare `continue` for as long as the tokenize branch has been a violation,
    which made this function inconsistent with its own docstring: the rule was
    applied to the parser's failure and not to the filesystem's, and an
    unreadable file came back indistinguishable from a well-marked one. That is
    the quiet direction, so it is the one that had to move.
    """
    script_dir = script_dir or _output.SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else _output.HOOKS_DIR
    violations = []
    for rel, _kind, path in _real_source_files(script_dir, hooks_dir):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError) as exc:
            violations.append((rel, "unreadable: %s; its section headers cannot "
                                    "be counted" % (exc,)))
            continue
        if len(lines) < _NAV_MIN_LINES:
            continue
        names = _section_header_names("".join(lines))
        if names is None:
            violations.append((rel,
                                "%d lines and does not tokenize; its section headers "
                                "cannot be counted" % (len(lines),)))
            continue
        headers = len([name for name in names if name != "selftest"])
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
#   panel/settings.js   // ---------- Settings ----------
# Up to two leading spaces count, because report.js wraps its whole body in an
# IIFE and column 0 is therefore unavailable to it. A marker indented deeper
# than that sits inside a function and is not a landmark the left margin gives
# you - the same reason the .py rule insists on column 0.
#
# WHAT THIS CANNOT SEE, NAMED RATHER THAN FIXED (F37). These are LINES matched by a
# regex, and a regex cannot tell a comment from the same characters inside a
# string. A `// ---- x ----` alone on its line inside a template literal or inside
# a `/* ... */` block counts as a section marker here, and so would a CSS
# declaration whose string value is continued across a line break with a
# backslash. The .py rule two functions up does NOT have this hole, because
# `tokenize` tells a COMMENT token from a STRING token (F21) - and there is no
# stdlib tokenizer for CSS or JavaScript. Hand-rolling one is not the missing
# work: it would be a second, unverified parser for two languages, maintained
# forever to serve one line-counting lint.
#
# THE CHEAP TIGHTENING WAS MEASURED AND IS WRONG, WHICH IS WHY THE HOLE STAYS.
# "A marker must sit at column 0 and be alone on its line" was the alternative,
# and both halves of it fail against the assets in this directory:
#
#   * COLUMN 0 counts ZERO markers in report.js, where every marker the shipped
#     rule finds is indented two spaces inside the IIFE - the allowance the
#     paragraph above already explains. A file that long carrying no marker is a
#     violation, so the tightening's first act would be to fail the file whose
#     markers are the most consistent in the directory. Case `u9` measures it and
#     prints both counts rather than asserting them from here.
#   * ALONE ON ITS LINE removes nothing and closes nothing. Both regexes are
#     already anchored, so a marker already has to BEGIN its line; and a fake
#     marker inside a template literal is alone on its line too.
#
# AND A PARTIAL LEXER MOVES THE HOLE RATHER THAN NARROWING IT, which was measured
# too. A scan that tracked backtick parity - the cheapest way to guess whether a
# line sits inside a template literal - reported one false marker in panel.js. The
# line it named is a real section marker; the scan had been flipped into "inside a
# string" by the backtick inside the single-quoted string in `hcode()` further up.
# The half-measure produced exactly the class of error it was written to detect.
#
# THE DIRECTION IS RECORDED, NOT OFFERED AS AN EXCUSE. Over-counting can only make
# an under-marked file PASS, never make a well-marked one fail - which is the same
# quiet direction F21 named as the one that hurts. No instance of it is known in
# the shipped assets, and nothing checks that, and nothing here can. `u8` pins the
# blindness the way `rt4` pins the narrowness of `_runtime_loaded_sibling_names` -
# as a decision: if a later change closes the hole, that case goes red and is
# deleted on purpose rather than a lint quietly becoming a different lint.
_UI_DIR = os.path.join(_output.SCRIPTS_DIR, "ui")

_UI_MARKER_RES = (
    (".css", re.compile(r"^/\*\s+-{2,}\s+(.+?)\s+-{2,}")),
    (".js", re.compile(r"^ {0,2}//\s+-{2,}\s+(.+?)\s+-{2,}")),
    # `.mjs` shares the `.js` syntax and reaches this table for `tools/`, which the
    # rule below now covers. A no-op for `scripts/ui/`, which holds none - and the
    # reason it is a THIRD ENTRY rather than a widened `.js` pattern is that the
    # extension is what selects a marker syntax, so a file type with no entry is
    # skipped rather than guessed at, and that property is worth keeping visible.
    (".mjs", re.compile(r"^ {0,2}//\s+-{2,}\s+(.+?)\s+-{2,}")),
    # `.py`, for `tools/` only in practice: `scripts/ui/` holds none by rule. This
    # is the LINE-BASED reading of a marker, so it is weaker than the sibling
    # `navigability_violations()`, which tokenizes and therefore cannot be fooled by
    # a marker-shaped line inside a string. Weaker and present beats absent: without
    # an entry here the walk SKIPS the extension, and the docstring below claimed
    # coverage the table did not give - which is the shape this whole pass is about.
    (".py", re.compile(r"^# -{2,}\s+(.+?)\s+-{2,}")),
)

# `tools/` is checked by the same rule, and until now by nothing. The largest file
# in this repository lived there - a browser gate of 8451 lines - and the marker
# rule reached `scripts/ui/`, `scripts/` and `hooks/` but never the directory that
# holds the machinery proving all three.
_TOOLS_DIR = os.path.join(_output.REPO_ROOT, "tools")


def ui_asset_names(ui_dir):
    """Every file under `ui_dir`, recursively, as forward-slashed relative names.

    Recursive because an asset that moves into a feature directory must not stop
    being checked; a flat listing does not report the file it no longer sees, it
    reports the directory as clean.

    Raises OSError if any directory in the tree cannot be listed. `os.walk`
    swallows that by default -- it yields nothing and raises nothing -- so an
    unreadable tree would otherwise come back as "no assets" and read exactly
    like a tree in which everything is fine. The `onerror` hook is what makes
    that failure loud, and it covers the root and every subdirectory alike.

    Names use "/" on every platform so a caller can compare them against a
    declared list without knowing the separator it is running on.
    """
    errors = []
    names = []
    for base, _dirs, files in os.walk(ui_dir, onerror=errors.append):
        rel = os.path.relpath(base, ui_dir)
        for f in files:
            names.append(f if rel == os.curdir
                         else (rel.replace(os.sep, "/") + "/" + f))
    if errors:
        raise errors[0]
    return sorted(names)


# --- one concern, one home ------------------------------------------------------
# A REGISTRY, NOT A SIMILARITY SCORE, and that choice was measured rather than
# preferred. A normalising token scanner over these same files reported 3,732
# cross-file repeat groups; tuned to preserve the shared vocabulary it still
# reported 725, and the top hits were this codebase's own `el()` DOM idiom - which
# is house style, not duplication. A gate at that noise level is a gate people
# learn to ignore. So the thing that GATES is a named list, and a similarity
# scanner is at most a scout for finding rows to add to it.
#
# Each row is a decision with its reason attached, the way `EXCLUDED` and
# `KNOWN_LAYER_DEBT` already are here. `allowed` is a RATCHET: a concern that has
# been extracted allows zero copies outside its home, and one that has not yet
# been extracted records how many sites exist today so the number can only go
# down. It is `<=`, never `==`, and that distinction is the whole lesson of the
# three save/discard counts this repo just retired: those required the duplication
# to STAY, so removing a copy turned them red and a helper could never be written.
# A cap punishes growth and stays silent when the code improves.
#
# The live count is printed on every run, so the number in this table is never
# what a reader trusts - the same reason `count-ui-pins.py` exists.
#
# WHAT THIS REGISTRY CANNOT REACH, said rather than implied: it scans `ui/*.js`
# only, so a concern whose second copy lives in PYTHON is invisible to it. Those
# are held by differential tests instead - the JavaScript is run in a VM and
# compared against the live Python through `tools/ui-tests/python-fmt.mjs`, which
# is how `uTok`'s truncation and the Appearance tab's contrast pairs were both
# caught. The two mechanisms answer different questions and neither substitutes
# for the other: this one asks "is there a second implementation", a differential
# test asks "do the two agree". A concern can pass one and fail the other, and
# the contrast pairs did exactly that for as long as they existed.
SHARED_CONCERNS = (
    ("blob download", "shared/download.js", "URL.createObjectURL", 0,
     "one revoke policy. Four sites had drifted to three, one of them revoking "
     "synchronously after click() while a sibling part argued that must never "
     "happen - a download that fails with no error anywhere."),
    ("web storage", "shared/storage.js", "localStorage.", 0,
     "fourteen sites each wrapped their own try/catch for one rule: a document "
     "opened over file:// may refuse storage, and neither surface may break."),
    ("pluralisation", "shared/plural.js", "===1?'':'s'", 0,
     "EXTRACTED, and the decision it was blocked on went the only way it could: "
     "the panel carried two conventions for one job - this suffix and a literal "
     "'(s)' - so adopting a helper in one of them would have made the split "
     "permanent. Both are gone. The literal cannot be a needle of its own "
     "(`test(s)`, `label(s)` and `dParse(s)` all match it), so it is not counted "
     "here; what stops it returning is that `plural` expresses what it never "
     "could - a clause whose VERB agrees too, which is why several of those "
     "sites read '1 task(s) are blocked'."),
    ("literal (s) pluralisation", "shared/plural.js", r"re:\(s\)\s+[a-z]", 0,
     "The second convention, and the row that made the registry learn regexes. "
     "A substring cannot express it: `(s) ` matches the sentences AND "
     "`dParse(s) + 6 * DAY`, since a space follows the paren in both, and what "
     "separates them is whether a WORD or an operator comes next. Kept as its "
     "own row rather than folded into the suffix one, because one needle cannot "
     "see both and a row that silently covers half its concern is worse than "
     "two rows that each say what they check."),
    ("clipboard copy", "shared/clipboard.js", "navigator.clipboard", 0,
     "EXTRACTED as copyText once the RULE was separated from the remedy. The "
     "earlier note was right that the part is thin and the fallback has to be "
     "injected, and wrong to read that as a reason to leave it: what is shared is "
     "not the line, it is that BOTH failure paths must fall back - over file:// "
     "some browsers throw and others reject, and an implementation handling one "
     "is broken exactly where a report is opened from disk. The fallbacks stay "
     "the callers': the panel copies through a hidden textarea and toasts, the "
     "report selects the text in place, and both are right for their surface."),
    ("table header construction", "panel/core.js", "el('thead'", 1,
     "EXTRACTED into headRow/tableHead, and the row this registry gained from "
     "the SCOUT rather than from reading - five agents read the whole panel and "
     "none reported it. Fourteen of the fifteen sites are converted, including "
     "every decorated one: a column may be a string, `null` for an action "
     "column, or {attrs,label,extra}, which is three shapes rather than an "
     "optional field per caller. The ONE left is browse-dialog's, which builds "
     "an empty <thead> and fills it on every redraw - a different job, and "
     "forcing it through a helper for the count's sake would be the tail "
     "wagging the lint. Panel-only: `el()` is the panel's builder and the "
     "report assembles its tables with createElement."),
    # The three the SCOUT found after the save/discard footers were factored -
    # reshaping the tree moved the next-largest duplications into view, which is
    # the argument for running it again after every extraction rather than once.
    ("save confirmation", "panel/write-confirmation.js", "'nothing to save", 0,
     "EXTRACTED as confirmSave. Four surfaces opened their Save with the same "
     "three steps in the same order - ask the form, refuse an empty save, get "
     "consent - and then diverged completely: a different endpoint, payload and "
     "re-render each. Only the opening was ever shared, and the needle is its "
     "one user-visible string, which is what a fifth surface would copy first."),
    ("caret restore", "panel/write-confirmation.js", "setSelectionRange(caret,caret)", 0,
     "EXTRACTED as restoreCaret. The panel had carried a comment calling this "
     "'ONE rule, and two places that need it' while four views spelled it - the "
     "comment was written when it was true and nothing counted it afterwards, "
     "which is the whole case for a row here rather than a note there."),
    ("theme token walk", "panel/theme-state.js",
     "const now=tVal(name,mode),was=", 0,
     "EXTRACTED as tDiff. The needle is the COMPARISON, not `TMODES.forEach` - "
     "that first spelling matched two walks in the Appearance editor which are "
     "not this concern at all (one builds a cell per mode, the other walks "
     "contrast pairs), and a row that fires on innocent code is a row someone "
     "switches off. Two functions asked what differs and walked groups, "
     "then tokens, then modes identically - skipping the dark column of a "
     "single-valued token, comparing as strings - and disagreed on nothing but "
     "WHICH baseline. Both copies were mine, hours apart: the second arrived the "
     "same afternoon the first was documented as the meaning of 'differs', which "
     "is how quickly a walk gets retyped when the difference is one argument."),
    ("select option loop", "panel/core.js", "o.selected=true;", 3,
     "EXTRACTED as fillOptions, which now serves five sites: build the option, "
     "mark it when its value is the chosen one, append. The residual THREE are "
     "deliberate and named - two decorate individual options (a title naming an "
     "area's owner, a disabled state over the chart's point cap) and one decides "
     "`selected` through a path normalisation. A per-option callback would have "
     "carried every caller's private business into the helper, which is the "
     "duplication back with extra steps."),
    ("heatmap calendar", "shared/calendar.js", r"re:function (startOf|endOf)\(", 0,
     "EXTRACTED, and the oldest duplication in this tree: five functions - a "
     "Monday-first weekday, startOf, endOf, shift and seek - written twice under "
     "the same names, once inside the report's IIFE and once inside the panel's "
     "uHeatmap. The sandbox harness carried a note the whole time saying neither "
     "copy could be tested because both closed over locals, and that reaching "
     "them was a source change. This is that change; the calendar closes over "
     "nothing, so hoisting cost no state. Only the DATA half stayed behind, as a "
     "predicate, because one surface holds its days as a sorted array and the "
     "other as an object and each has a reason."),
    ("heatmap row shapes", "shared/calendar.js",
     r"re:function (dayRows|weekRows|weekdayRows|dateRows|monthRows|heatRows)\(", 0,
     "EXTRACTED, and its own row rather than folded into the calendar above "
     "because the two failed differently and one of them failed in PRODUCTION. "
     "The calendar's copies agreed; these did not have to, and the branch that "
     "chose between them was wrong in both surfaces at once - month, year and "
     "all shared one builder, so Month drew Week's seven weekday rows with each "
     "cell summed over the four-or-so occurrences of that weekday. A reader "
     "reported it as a copy of the weekly view. The needle names the old "
     "spellings AND the new ones, because what would bring the defect back is "
     "someone retyping a row builder into a surface under either."),
    ("day <-> milliseconds", "shared/dates.js", r"re:864e5|86400000", 0,
     "EXTRACTED as DAY_MS. The needle is the CONSTANT rather than one spelling "
     "of the arithmetic - a narrower pattern found five of the nine and a shell "
     "regex found three, because the divisions and the multiplications look "
     "nothing alike - and it now matches BOTH spellings, which is how the "
     "report's own `86400000` came to light. That second reader is why this went "
     "to shared/ and not to panel/core.js as the earlier note predicted: the "
     "note said the report carries milliseconds throughout, and it does, in a "
     "constant of its own under a different name. The panel's day-number helpers "
     "(dnum, dayIso) stayed in panel/core.js, where they have one reader - "
     "dayIso replacing three identical local copies."),
    ("phase execution order", None,
     r"re:priority\s*(==\s*null\s*\?\s*[^'\"\s]|\|\|\s*0|\?\?)", 0,
     "THE HOME IS PYTHON: `_priority.sort_key` is documented as the only "
     "expression of phase order in this tree, because a second one is how two "
     "orders come to disagree. Both surfaces are handed a NUMBER instead - the "
     "report as `data-porder`, the panel as the rollup's `porder` - and neither "
     "may hold the rule. This is not the blind spot named above: that one is a "
     "home in ui/ with a copy in Python, which this scan cannot see. This is the "
     "MIRROR, and a copy in ui/ is exactly what it does see. The needle is the "
     "one decision a comparator here cannot avoid making - where an ABSENT tier "
     "sorts - in its three spellings: a class test whose branches are numbers, "
     "absent-means-zero arithmetic (which `_priority` names as the wrong "
     "answer), and a nullish default. A bare null test could not be the needle: "
     "the Composition tab writes an empty form value for an absent tier, which "
     "is a different job, and a row that fires on innocent code is a row someone "
     "switches off. The panel carried the comparator for a while with a comment "
     "saying it mirrored sort_key - correct the whole time, held correct by "
     "nothing, and a comment claiming two implementations agree is not a check."),
)


# A `/` starts a regex literal rather than a division when the previous
# significant character is an operator, an opening bracket or nothing at all.
# This is the standard heuristic and it is enough here: the three regex literals
# in `ui/` that contain a quote character are each preceded by `=` or `(`.
_REGEX_PREV = frozenset("(,=:[!&|?{};+-*%~^<>")


def _code_only(text):
    """`text` with JavaScript comments removed and everything else kept verbatim.

    STRINGS ARE PRESERVED, because the needles include string content -
    `el('thead'` and `===1?''` are both partly a literal. Only comments go.

    WHY THIS IS A SCANNER AND NOT TWO REGEXES, measured on this tree rather than
    argued. The first version stripped block comments first with a DOTALL regex,
    and `appearance-view.js` line 69 is a `//` comment containing
    `.claude/themes/*.json`. That `/*` opened a false block comment which closed
    150 lines later, swallowing real code - including a genuine occurrence the
    registry then failed to count. UNDER-counting is the silent direction: the
    lint would have reported no violation while a second implementation sat
    inside the swallowed region.
    Reversing the order does not fix it either: `usage-charts.js` carries
    `'http://www.w3.org/2000/svg'` and `ado-connector.js` an Azure URL, so
    stripping line comments first truncates real code at a `//` inside a string.
    Neither order is safe, so the states are tracked properly.

    Newlines are preserved through comments so a caller can still report a line
    number - a scout that reports real duplication at the wrong coordinates sends
    a reader somewhere irrelevant, and the natural conclusion is that the tool is
    noise.

    KNOWN LIMIT: a regex literal is detected by the previous significant
    character, so a division written where a regex could appear would be read as
    a regex and the rest of the line kept as literal text. That direction is
    safe - it keeps too much rather than too little, so it cannot hide a needle.
    """
    out = []
    i = 0
    end = len(text)
    state = None            # None | line | block | ' | " | ` | regex
    prev_sig = ""
    while i < end:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < end else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if ch in ("'", '"', "`"):
                state = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and (prev_sig == "" or prev_sig in _REGEX_PREV):
                state = "regex"
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            if not ch.isspace():
                prev_sig = ch
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = None
                out.append("\n")
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state = None
                i += 2
                continue
            if ch == "\n":
                out.append("\n")
            i += 1
            continue
        # Inside a string, a template or a regex: copied through verbatim.
        out.append(ch)
        if ch == "\\" and i + 1 < end:
            out.append(text[i + 1])
            i += 2
            continue
        if state == "regex":
            if ch == "/":
                state = None
                prev_sig = "/"
            elif ch == "\n":
                # An unterminated regex is a mis-detected division; recover rather
                # than swallowing the rest of the file.
                state = None
            i += 1
            continue
        if ch == state:
            state = None
            prev_sig = ch
        i += 1
    return "".join(out)


def _needle_counter(needle):
    """A `count(body)` for one needle, substring or regex.

    A needle wrapped in `re:` is compiled; anything else is a plain substring, as
    every row was until the literal `(s)` convention needed a row of its own.
    That one cannot be a substring: `(s) ` matches the sentences AND
    `dParse(s) + 6 * DAY`, because a space follows the paren in both. What
    separates them is what comes NEXT -- a word in the sentence, an operator in
    the call -- and that is a distinction no substring can draw.

    The alternative was to leave the concern unguarded and say so in its `why`.
    Widening the registry once is cheaper than a row that admits it cannot see
    half of what it names, and this is the second row that would have wanted it
    (the day/millisecond needle settled on the CONSTANT for the same reason).
    """
    if needle.startswith("re:"):
        rx = re.compile(needle[3:])
        return lambda body: len(rx.findall(body))
    return lambda body: body.count(needle)


def _concern_hits(root, home, needle):
    """[(asset, count)] for `needle` outside `home`, comments stripped.

    One walk, used by both callers. They had a copy each until this was written,
    which in a module whose subject is duplication is not an irony worth keeping.
    """
    count_in = _needle_counter(needle)
    hits = []
    for name in sorted(n for n in ui_asset_names(root) if n.endswith(".js")):
        if home is not None and name == home:
            continue
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8") as fh:
                body = _code_only(fh.read())
        except (OSError, UnicodeDecodeError) as exc:
            # Named, never skipped: an asset nothing can read is not an asset
            # with no duplication in it.
            hits.append((name + " <unreadable: %s>" % (exc,), 1))
            continue
        count = count_in(body)
        if count:
            hits.append((name, count))
    return hits


def shared_concern_violations(ui_dir=None):
    """[(concern, home, total, allowed, where)] for concerns that have SPREAD.

    A violation is `total > allowed` outside the concern's home. Below the
    allowance is not a violation - see `shared_concern_slack`.
    """
    root = ui_dir if ui_dir is not None else _UI_DIR
    try:
        ui_asset_names(root)
    except OSError as exc:
        # NOT an empty list: a directory nothing could read is not a directory
        # with no duplication in it.
        return [("<unlistable>", "", -1, 0, "%s" % (exc,))]
    out = []
    for concern, home, needle, allowed, _why in SHARED_CONCERNS:
        hits = _concern_hits(root, home, needle)
        total = sum(c for _n, c in hits)
        if total > allowed:
            # A `None` home used to render as "(not extracted)", which was dead
            # text while every row had a home and became WRONG the moment one did
            # not: "phase execution order" is extracted, into Python, and nothing
            # in `ui/` may hold it. This wording is true of both readings - a
            # concern still awaiting extraction has no home here yet either.
            out.append((concern, home or "(no home in ui/)", total, allowed,
                        ", ".join("%s x%d" % (n, c) for n, c in hits)))
    return out


def shared_concern_slack(ui_dir=None):
    """[(concern, total, allowed)] where the allowance is looser than reality.

    Reported rather than failed, because failing here would punish exactly the
    change this registry exists to encourage - and that is the difference between
    a cap and the three `== N` counts this repo retired, which required the
    duplication to stay. Printing it is what stops the table becoming a column of
    numbers nobody has re-derived.
    """
    root = ui_dir if ui_dir is not None else _UI_DIR
    try:
        ui_asset_names(root)
    except OSError:
        return []
    out = []
    for concern, home, needle, allowed, _why in SHARED_CONCERNS:
        total = sum(c for _n, c in _concern_hits(root, home, needle))
        if total < allowed:
            out.append((concern, total, allowed))
    return out


def ui_navigability_violations(ui_dir=None):
    """(filename, problem) for every long scripts/ui/ asset carrying too few
    section markers to be navigable.

    "Long" is `_NAV_MIN_LINES` or more, the same constant the .py rule uses;
    "enough" is one marker per `_NAV_MIN_LINES` lines, never fewer than 2.
    Files below the line threshold are not checked at all, and any extension
    without a marker syntax in `_UI_MARKER_RES` (`.html`, and whatever else
    lands there) is skipped rather than guessed at.

    A marker is found by matching a LINE and not by lexing the file, so a
    marker-shaped line inside a string or a block comment is counted as one. The
    sibling .py rule closed that hole with `tokenize`; CSS and JavaScript have no
    stdlib tokenizer, and the tightening that needs none was measured and
    rejected. Both are argued above `_UI_MARKER_RES`, and `u8` pins the resulting
    blindness so that closing it later is a deliberate act rather than a drift.

    WHAT IS NOT A BLINDNESS ANY MORE, AND WHY IT WAS THE WORSE ONE (F44). This
    function used to swallow an asset it could not read and return an empty list
    for a directory it could not list. Both are the quiet direction that F21
    named: a file nothing could open came back as a file with nothing wrong, and
    a missing `scripts/ui/` - the whole report and panel UI gone - printed
    exactly what a clean tree prints. The sibling .py rule already reported a
    file it could not tokenize, so the pair disagreed about the same question,
    and the disagreement was invisible because both halves were green. The
    marker hole above is pinned as a decision because closing it would cost a
    hand-rolled lexer for two languages; these two cost four lines, which is why
    naming them is not a decision at all.
    """
    ui_dir = ui_dir if ui_dir is not None else _UI_DIR
    violations = []
    try:
        # Recursive, and that is the whole point: a flat listing stops seeing an
        # asset the moment it moves into a feature directory, and reports the
        # silence as "nothing wrong". The report's script lives in `report/`, so
        # a flat walk here would check the panel and quietly grade the entire
        # report as clean.
        names = ui_asset_names(ui_dir)
    except OSError as exc:
        # NOT `return []`. An empty list is a real answer ("every asset here is
        # navigable") and would make a directory nothing could read
        # indistinguishable from one that was read and found clean.
        return [(os.path.basename(ui_dir.rstrip(os.sep)) or ui_dir,
                 "unlistable: %s; no asset here could be checked" % (exc,))]
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
        except (OSError, UnicodeDecodeError) as exc:
            violations.append((name, "unreadable: %s; its section markers cannot "
                                     "be counted" % (exc,)))
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


def tool_navigability_violations(tools_dir=None):
    """(filename, problem) for every long `tools/` file with too few markers.

    DELEGATES rather than re-derives. `ui_navigability_violations` is already
    generic over a directory - it walks recursively, picks a marker syntax by
    extension, and applies one-marker-per-`_NAV_MIN_LINES`-never-fewer-than-two -
    so the only thing `tools/` needed was `.mjs` in the extension table and a name
    saying the directory is in scope. A second copy of that arithmetic is how the
    two would come to disagree about what "navigable" means.

    IT COVERS BOTH FAMILIES, and the `.py` half is the part worth being explicit
    about: `navigability_violations()` scans `scripts/` and `hooks/` and has never
    reached `tools/`, so a 490-line tool with one marker was nobody's finding. The
    `.py` files here are handed to the same asset walk, which selects the `#`
    syntax the sibling rule uses.
    """
    root = tools_dir if tools_dir is not None else _TOOLS_DIR
    return ui_navigability_violations(root)


# --- known layer debt ---------------------------------------------------------
# HOW MANY ARE LEFT IS DELIBERATELY NOT WRITTEN HERE. The tuple below IS the count,
# and a figure in this comment would be a second copy of it with nothing comparing
# the two. That is not hypothetical: the module docstring said this table "stayed
# at 17" for as long as it held ONE, and this comment opened with "ONE entry" -
# both true the day they were typed, and one of them a lie by the next commit
# (F39, the same disease as F29). Print it rather than reading it:
#
#   python3 -c "import sys; sys.path.insert(0, 'plugins/audit/scripts'); \
# import _deps; print(len(_deps.KNOWN_LAYER_DEBT))"
#
# The numbers that DO survive below are HISTORY - what was retired, by which
# extraction, in a change that has already happened - and history does not rot.
# That difference is also why no lint sits behind this rule: "seventeen" is correct
# in a sentence about the past and wrong in a sentence about now, and nothing
# reading the source text can tell those two sentences apart. What a reader gets
# instead is the command, one line up.
#
# Down from the seventeen that became visible the moment this module learned to
# read `_loader` calls. None of those seventeen was ever new: each had been in the
# tree for months, certified clean by a lint that walked only `ast.Import` while
# most of this codebase reaches its siblings at runtime.
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
    # THIS ENTRY USED TO SAY "there is no logic here to extract downward", AND
    # THAT WAS FALSE FOR HALF OF IT. The edge had TWO call sites, and they were
    # not the same kind of thing. `_panel_state.report_paths()` reached the same
    # L7 module for `_report_basename` - a pure naming rule that `_report_html`
    # owns at L2 and `render-report.py` merely aliases. That is the exact shape
    # every retired entry above had, a module used as a LIBRARY through a
    # COMMAND, and the downward home for it was already built; the panel simply
    # was not asking there. It asks `_report_html` directly now. The entry did
    # not move, because an edge is a pair and the other call site keeps it - but
    # a reason that is true of only one call site is a reason that stops the next
    # reader looking, which is how debt becomes permanent without anyone deciding
    # it should be.
    #
    # WHAT IS LEFT REALLY HAS NO DOWNWARD HOME, and the arithmetic is checkable
    # rather than asserted (`ld1` in tests/test__deps.py recomputes it from
    # LAYERS and fails if it stops holding). What `render_report` wants is not a
    # rule it could share but the WHOLE report pipeline ending in two files on
    # disk. That pipeline is a genuine chain - `_report_html` -> `_usage_viz` ->
    # `_usage_markdown` -> `_report_md` -> `_report_page` - and it bottoms out at
    # `_report_page`, ABOVE this module. A helper holding it could therefore not
    # sit anywhere `_panel_state` may import from.
    #
    # THE TWO REAL FIXES, AND WHAT EACH COSTS. Both are larger decisions than
    # this entry.
    #
    #   * MOVE `_panel_state` ABOVE THE REPORT STACK. It cannot land on the entry
    #     point layer - a peer load is not strictly downward either - so it needs
    #     a layer above that, and `_panel_write` and `panel-server` both import it
    #     and must follow. The table gains layers and `panel-server` ends up alone
    #     at the top while every other entry point stays put, which dissolves the
    #     one property this table is FOR: a layer being a group a reader can hold
    #     in their head. No edge changes behaviour; the map is renumbered
    #     throughout. That is the same trade every "inserting a layer would have
    #     renumbered every entry below" note above declines, and it declines
    #     bigger here.
    #
    #   * SPLIT A WRITER OUT OF `render-report.main()`. Real, and it does not
    #     reach this module: the extracted writer still has to call
    #     `_report_page`, so it lands at L6, and `_panel_state` at L5 is still
    #     below it. It shrinks the edge from "an entry point" to "a writer" and
    #     leaves it pointing the same way, so it has to be paired with the move
    #     above to retire anything.
    #
    # AND INVERTING THE CALL IS NOT A THIRD FIX, WHICH IS WORTH SAYING BECAUSE
    # THIS FILE ALREADY HOLDS THE PRECEDENT THAT MAKES IT LOOK LIKE ONE.
    # `render-report` takes the gate verdict as an INJECTED callable instead of
    # reaching up to `audit-status`. That worked because the injected thing's
    # implementation moved DOWN - `_status_facts` at L2 - so the supplier's own
    # edge became downward. Here the implementation cannot go below `_report_page`,
    # so injection only asks who supplies the callable, and every candidate is
    # `_panel_write` or `panel-server`, at or above the entry point layer.
    # The edge would be recorded against a different file, unchanged.
    #
    # WHAT WAS DELIBERATELY NOT DONE: swapping the in-process call for a
    # `script_path()` + subprocess. `_deps` does not count that as an edge, by
    # design and for a good reason (nothing is imported, nothing is executed
    # here) - which is exactly why reaching for it would be laundering. It would
    # also change behaviour: a second interpreter, a different failure surface,
    # and an exit code where there is now an exception. A fix that makes an edge
    # invisible rather than absent is a regression wearing a green suite.
    #
    # NOR IS "TEACH THE LINT THAT A RUNTIME LOAD IS NOT A STATIC EDGE" A FIX,
    # which has to be said because it is the one that looks free. `load_script`
    # creates the module and runs it IN THIS PROCESS; the only reason it is not
    # an `import` statement is that every entry point in this tree is hyphenated
    # and no `import` can spell one. Narrowing the scan to `ast.Import` is the
    # exact state the module docstring records - a clean report over a tree
    # carrying twenty-one upward runtime edges - and `rt6`/`bw4` keep that
    # version red on purpose. The edge is real; the spelling is what is unusual.
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
