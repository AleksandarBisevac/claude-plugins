#!/usr/bin/env python3
"""
Which checks a change actually needs — and, when it cannot tell, all of them.

    tools/affected.py                 # what the working tree changed
    tools/affected.py --base HEAD~3   # ...against another commit
    tools/affected.py <path> <path>   # ...or an explicit list
    tools/affected.py --json          # machine-readable, for verify.sh

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

THE CROSS-FILE TRAP. Suites here lint OTHER files' source - `_output` reads every
file's AST for house style, `_deps` walks the import graph, `_refs` checks paths and
version pins. Editing one file can turn those red without touching them, so any
`.py` change selects them too. That is not caution, it is a measured fact: this
repo has gone red exactly that way.
"""
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

import _deps  # noqa: E402  (the import graph this selection is derived from)
import _refs  # noqa: E402  (the surfaces and sweep documents it reads)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join("plugins", "audit", "tests")

# Suites that read the WHOLE tree rather than one module, so any `.py` edit can
# turn them red. Derived by grep once and listed here because the list is the
# claim: a suite that starts scanning the tree must be added, and the comment
# above `PANEL_GATE` says how a missing entry shows up.
TREE_SCANNERS = (
    "test__output.py", "test__deps.py", "test__refs.py", "test__manifest_vocab.py",
    "test__config_rules.py", "test__manifest_rules.py", "test__panel_paths.py",
    "test__panel_state.py", "test__report_page.py", "test__ui_theme.py",
    "test_remind_tdd.py", "test_validate_manifest.py",
)

PANEL_GATE = "node tools/capture-screenshots.mjs --check --only panel"
REPORT_GATE = "node tools/check-report-interactive.mjs %s"
REPORT_DOCS = ("examples/acme-store/acme-store-audit.html",
               "docs/index.html", "docs/demo-large.html")
ARTIFACTS = "python3 tools/check-rendered-artifacts.py"

# The JavaScript unit tests under `tools/ui-tests/`. They were selectable by nothing
# and runnable only in CI, so a change to a `scripts/ui/` part reached a push with
# none of the suites covering it having run - the same forgotten-step class
# `verify.sh` exists to close, one directory over. Cheap enough that widening to it
# is never the expensive decision.
VITEST = "npx vitest run"

# The meta-gate. Several files describe one gate set - the runner, the workflow and
# the two root documents - and editing any of them is what makes them disagree. Which
# files those are is `gate-parity.py`'s own table and is deliberately not copied here;
# see the sweep-document branch for what this selects on instead.
PARITY = "python3 tools/gate-parity.py"

# A tool's OWN cases. Every `.py` under `tools/` carries an inline suite, and until
# this existed nothing here selected one: a change to a tool was classified "a tool
# no suite covers" and the narrowed run skipped exactly the cases that change owed.
# The classification was the worse half - it reads as a fact about the file when it
# was a fact about this selector, which is the one thing a reader must never be told
# wrong by a tool whose whole subject is what a narrowed run leaves out.
#
# DERIVED, not a list. `sweep-selftests.py` walks `tools/` and demands the
# `N/M cases passed` contract from every file it is not told is migrated, so a `.py`
# outside the migrated set HAS a suite by construction - and the migrated set is read
# off the same classifier the sweep asks rather than name-transformed here. The path
# is substituted whole: a format string spelling a module basename is what
# `_refs.tool_basename_drift()` reads as a reference to a file that does not exist.
TOOL_SELFTEST = "python3 %s --selftest"
MIGRATED = frozenset(_output.covered_repo_paths(REPO))

# The documents `_refs.sweep_glob_drift()` pins, READ OFF `_refs` rather than listed
# again here. Two of them start with a dot and were unreachable by every rule below;
# a third copy of the list is also how the two would come to disagree.
SWEEP_DOCS = frozenset(d.replace(os.sep, "/") for d in _refs.SWEEP_DOCS)

# ...and since `sweep_doc_drift()` asks whether that LIST is complete, `_refs` no
# longer reads only the listed documents: it reads every document of a format
# `_runnable_text` has a rule for, anywhere the repo keeps files. So the selector owes
# the refs pins for any of them, which is a WIDENING - the direction this file is
# allowed to be wrong in. Read off the same constant the scan derives its own
# extension set from, so the two cannot disagree about what a document is.
SWEEP_DOC_EXT = tuple(_refs.SWEEP_DOC_EXT)

# ...and the pages `_refs.artifact_version_drift()` reads, derived the same way. A
# committed report carries the plugin version that rendered it, and that rule is the
# only thing comparing the stamp with `plugin.json` - so a narrowed run that edited a
# published page and skipped this suite would be the under-selection this whole file
# exists to prevent. The other direction is already covered: a `plugin.json` change
# selects the full set.
STAMP_EXT = tuple(_refs.STAMP_EXT)


def refs_reads(posix):
    """True when `_refs` scans this path, so `test__refs.py` can go red for it.

    Derived from `_refs.SURFACES`, `_refs.SWEEP_DOCS`, `_refs.SWEEP_DOC_EXT` and
    `_refs.STAMP_EXT` for the
    same reason `_reverse_imports()` is derived from the real import graph: a hand-kept
    copy of somebody else's list is a copy that stops agreeing. Editing
    `CONTRIBUTING.md` selected `test__deps.py` and not this - and `CONTRIBUTING.md` is a
    `_refs` surface, so a path rotting in it went unchecked by the narrowed run.

    The extension arm needs no ignored-directory test to go with it: the paths this
    file judges come from git, and git never hands over a file the repo ignores. The
    scan's own prune list exists for a WALK, which sees files git does not.
    """
    if posix in SWEEP_DOCS or posix.endswith(SWEEP_DOC_EXT + STAMP_EXT):
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


def _reverse_imports():
    """basename -> everything that imports it, transitively."""
    edges, _ = _deps.import_graph()
    direct = {}
    for importer, imported in edges:
        direct.setdefault(imported, set()).add(importer)
    closure = {}
    for name in direct:
        seen, stack = set(), [name]
        while stack:
            cur = stack.pop()
            for up in direct.get(cur, ()):
                if up not in seen:
                    seen.add(up)
                    stack.append(up)
        closure[name] = seen
    return closure


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


# --- the selection rules ------------------------------------------------------
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


def select(paths):
    """What to run, and why. Returns (plan, reasons, full)."""
    suites = set()
    gates = []
    reasons = []
    full = False
    closure = _reverse_imports()
    touched_py = False
    panel = report = artifacts = vitest = False

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
        if posix.endswith(".py"):
            suites.add("test__output.py")
        if posix.endswith(".md"):
            suites.add("test__deps.py")
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
        if posix.startswith(TESTS.replace(os.sep, "/")):
            name = os.path.basename(posix)
            if name.endswith(".py"):
                suites.add(name)
                touched_py = True
                reasons.append("%s - its own suite" % (posix,))
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
            own = _suite_for(base)
            if own:
                suites.add(own)
            for up in closure.get(base, ()):
                dep = _suite_for(up)
                if dep:
                    suites.add(dep)
            reasons.append("%s - its suite plus every suite of a module that "
                           "imports it" % (posix,))
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
        if posix.startswith("tools/"):
            # THE TOOL'S OWN CASES FIRST, and outside the chain below rather than as
            # another arm of it: what a tool is a gate FOR and whether it has a suite
            # are two questions, and answering them in one chain is what left the
            # sweep runner - the one file every other suite is run BY - selectable
            # only through an arm written for it by name.
            own = posix.endswith(".py") and posix not in MIGRATED
            if own:
                gates.append(TOOL_SELFTEST % (posix,))
                reasons.append("%s - a tool, so its own cases run" % (posix,))
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
        suites.update(TREE_SCANNERS)
        reasons.append("a .py changed, so every suite that lints the whole tree "
                       "is included - editing one file turns those red without "
                       "touching them")
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


def main(argv):
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
# reading, which is how F61's first attempt collided with `a5`. `_harness.run()`
# now catches a collision by name, so this is about a reader's next label rather
# than about a proof - and it is a convention on purpose, not a lint: a suite
# that groups its cases by topic is right to, and a rule demanding one global
# ascending sequence would forbid exactly that.
def _cases(check):

    def sel(*paths):
        suites, gates, _why, full = select(list(paths))
        return {"suites": suites, "gates": gates, "full": full}

    def why(*paths):
        """The reason lines alone, joined - what a reader of a narrowed run gets."""
        _suites, _gates, reasons, _full = select(list(paths))
        return " | ".join(reasons)

    yml = ".github/workflows/ci.yml"
    dotted = sel(yml)
    undotted = sel("github/workflows/ci.yml")
    check("a0 the workflow is a sweep document and half the gate set, so it "
          "narrows to the refs pins and the parity check instead of demanding "
          "everything: %r" % (dotted,),
          (not dotted["full"])
          and "test__refs.py" in dotted["suites"]
          and PARITY in dotted["gates"])

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

    # Both paths are under `docs/`, which is NOT a `_refs` surface - so before the
    # completeness rule they answered False alike, and the extension is the whole
    # difference between them. A pair inside a surface would prove nothing: everything
    # there already answered True. The False half was `docs/index.html` until the
    # version-stamp rule started reading that page, which is exactly the way a pair
    # like this is supposed to go stale: loudly, in the case, and not in the selector.
    check("a5b a document nowhere near the pinned list selects the refs pins now, "
          "because the completeness rule reads every document the repo keeps - "
          "and a non-document beside it still does not, so this is an extension "
          "rule and not a widening to everything",
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

    page = sel("docs/demo-large.html")
    check("a10b a published report selects the version-stamp rule as well as the "
          "byte comparison. The stamp is the claim the page makes about which "
          "release it came from, and until it was read by a suite the only "
          "thing that could notice a stale one was a re-render: %r" % (page,),
          "test__refs.py" in page["suites"]
          and ARTIFACTS in page["gates"] and not page["full"])

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
    # Measured, not guessed: these are the two files F64 and F71 were found in, and
    # they were also the two that selected the wrong side of this. Anything under
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


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
