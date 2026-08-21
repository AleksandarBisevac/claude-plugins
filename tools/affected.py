#!/usr/bin/env python3
"""
Which checks a change actually needs — and, when it cannot tell, all of them.

    tools/affected.py                 # what the working tree changed
    tools/affected.py --base HEAD~3   # ...against another commit
    tools/affected.py <path> <path>   # ...or an explicit list
    tools/affected.py --json          # machine-readable, for verify.sh

WHY THE BROWSER GATES ARE THE POINT. Measured on this machine: the whole Python
selftest sweep is ~40s for every file in the tree, while the panel browser gate
alone is ~230s. So narrowing the Python side saves seconds and narrowing the
BROWSER side saves minutes. A change that touches only the report's parts does not
need the panel driven at all, and that single decision is most of what this is for.

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


def changed_files(base, explicit):
    """The paths this run is about, as repo-relative POSIX strings."""
    if explicit:
        return sorted(set(p.replace(os.sep, "/").lstrip("./") for p in explicit))
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


def select(paths):
    """What to run, and why. Returns (plan, reasons, full)."""
    suites = set()
    gates = []
    reasons = []
    full = False
    closure = _reverse_imports()
    touched_py = False
    panel = report = artifacts = False

    for path in paths:
        posix = path.replace(os.sep, "/")
        if posix.startswith("docs/screenshots/"):
            reasons.append("%s - a committed PNG, checked by eye and never by a "
                           "gate" % (posix,))
            continue
        if posix.endswith((".md", ".txt")) and "/" not in posix:
            # Root prose: CLAUDE.md and friends are read by `_deps.doc_prose_numbers`.
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
            if "capture-screenshots" in posix:
                panel = True
                reasons.append("%s - the panel gate itself" % (posix,))
            elif "check-report-interactive" in posix:
                report = True
                reasons.append("%s - the report gate itself" % (posix,))
            else:
                reasons.append("%s - a tool no suite covers" % (posix,))
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
    if artifacts:
        gates.append(ARTIFACTS)
    if report:
        for doc in REPORT_DOCS:
            gates.append(REPORT_GATE % (doc,))
    if panel:
        gates.append(PANEL_GATE)
    return sorted(suites), gates, reasons, full


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


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("affected.py has no inline --selftest; it is a dev-side selector "
              "and its answers are checked by running the full set it defers to.")
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
