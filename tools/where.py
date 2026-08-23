#!/usr/bin/env python3
"""
Which source part emits this — and which assembled surface it actually reaches.

    tools/where.py audit-hm-gran        # an element id
    tools/where.py "worked by"          # a label
    tools/where.py uhmwhy               # a class

WHY. `scripts/ui/` is not a set of files, it is ordered parts of two pages, so
"where does this come from" has two different answers and only one of them is a
grep: which FILE contains the text, and which assembled SURFACE it ends up in. A
string can sit in a part that only the panel joins, or in a shared part that ships
inside both, and the difference decides which browser gate a change owes. The panel
gate is by far the longer of the two, so guessing wrong is expensive in both
directions - re-derive the figures rather than trusting a pair written here:

    node tools/capture-screenshots.mjs --check --only panel
    node tools/check-report-interactive.mjs docs/index.html

It is a lookup, not a check: nothing here can fail a build. It exists because
finding the emitter of a control was the single largest tax on a day of UI work -
grep answers "which file has this text" and then you still do not know whether the
page you are looking at is built from it.
"""
import io
import os
import sys

# The path bootstrap, adapted: this file lives in tools/, outside scripts/, so the
# anchor is found by the known layout rather than by walking up for `_output.py`.
_here = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_here)
_scripts = os.path.join(REPO, "plugins", "audit", "scripts")
for _p in (_scripts, os.path.join(_scripts, "report"), os.path.join(_scripts, "panel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _output  # noqa: E402

_output.install_path()

SOURCE_DIRS = (
    os.path.join("plugins", "audit", "scripts", "ui"),
    os.path.join("plugins", "audit", "scripts", "report"),
    os.path.join("plugins", "audit", "scripts", "panel"),
    os.path.join("plugins", "audit", "hooks"),
)
SOURCE_EXT = (".py", ".js", ".css", ".html", ".md")


def hits_in_source(needle):
    """Every (path, line_no, line) under the UI and surface directories."""
    out = []
    for rel in SOURCE_DIRS:
        base = os.path.join(REPO, rel)
        for root, _dirs, files in os.walk(base):
            if "__pycache__" in root:
                continue
            for name in sorted(files):
                if not name.endswith(SOURCE_EXT):
                    continue
                path = os.path.join(root, name)
                try:
                    text = io.open(path, encoding="utf-8").read()
                except Exception:
                    continue
                if needle not in text:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if needle in line:
                        out.append((os.path.relpath(path, REPO).replace(os.sep, "/"),
                                    i, line.strip()))
    return out


def surfaces(needle):
    """Which ASSEMBLED page carries it. The half a grep cannot answer."""
    found = []
    try:
        import _panel_page
        if needle in _panel_page.UI_HTML:
            found.append("panel (assembled page)")
    except Exception as exc:
        found.append("panel: could not assemble (%s)" % (exc.__class__.__name__,))
    try:
        import _report_page
        for label, attr in (("report script", "_SCRIPT"), ("report stylesheet", "_CSS")):
            blob = getattr(_report_page, attr, None)
            if isinstance(blob, str) and needle in blob:
                found.append("report (%s)" % (label,))
    except Exception as exc:
        found.append("report: could not assemble (%s)" % (exc.__class__.__name__,))
    return found


def gates_for(surface_names, source_paths):
    """The checks a change to this would owe, named rather than guessed."""
    out = []
    panel = any(s.startswith("panel") for s in surface_names) or \
        any("/panel" in p for p in source_paths)
    report = any(s.startswith("report") for s in surface_names) or \
        any("/report" in p for p in source_paths)
    if report:
        out.append("node tools/check-report-interactive.mjs "
                   "examples/acme-store/acme-store-audit.html")
    if panel:
        out.append("node tools/capture-screenshots.mjs --check --only panel")
    if not out:
        out.append("(neither surface carries it - no browser gate applies)")
    return out


# --- selftest -----------------------------------------------------------------
# IT USED TO SAY IT NEEDED NONE: "a read-only lookup that cannot fail a build, and
# its answers are the assembled pages themselves". The first half is true. The second
# is the shape that catches people out - nothing compares this file's answers to the
# pages, so a wrong answer here sends someone to run the wrong browser gate, and the
# gate they skipped is the one that would have told them.
def _cases(check):

    panel = gates_for(["panel (assembled page)"], ["scripts/ui/panel/core.js"])
    report = gates_for(["report (report script)"], ["scripts/ui/report/areas.js"])
    check("g0 a panel-only string owes the PANEL gate and not the report one: %r"
          % (panel,),
          any("capture-screenshots" in g for g in panel)
          and not any("check-report-interactive" in g for g in panel))
    check("g1 THE OTHER HALF, and the reason g0 means anything: a report-only "
          "string owes the REPORT gate and not the panel one. The panel gate "
          "is the long one, so an answer that always named both would cost "
          "minutes per lookup and an answer that always named one would send "
          "half of all changes to the wrong check: %r" % (report,),
          any("check-report-interactive" in g for g in report)
          and not any("capture-screenshots" in g for g in report))

    both = gates_for([], ["scripts/ui/shared/format.js",
                          "scripts/ui/panel/core.js",
                          "scripts/ui/report/areas.js"])
    check("g2 a string in both surfaces owes both gates: %r" % (both,),
          len(both) == 2)

    neither = gates_for([], ["hooks/require-plan.py"])
    check("g3 and a string in NEITHER surface gets a sentence saying so rather "
          "than an empty list - 'no gate applies' and 'I found nothing to "
          "say' must not print the same way: %r" % (neither,),
          len(neither) == 1 and "no browser gate" in neither[0])

    check("g4 the SURFACE alone is enough - a name built at runtime appears in "
          "no source path, and answering only off paths would report no gate "
          "for exactly those",
          gates_for(["panel (assembled page)"], []) == panel[:1]
          or any("capture-screenshots" in g
                 for g in gates_for(["panel (assembled page)"], [])))

    hits = hits_in_source("safe_stdio")
    check("g5 the source scan really reads the tree and returns (path, line, "
          "text) triples a reader can open (%d hits)" % (len(hits),),
          len(hits) > 3
          and all(len(h) == 3 and isinstance(h[1], int) for h in hits))

    check("g6 ...and a needle that is not there comes back empty, so g5 is a "
          "scan rather than a function that returns the whole tree",
          hits_in_source("qzx-no-such-needle-anywhere") == [])


def _selftest():
    from _suite import run          # the house runner; tools/_suite.py says why here
    return run(_cases)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    needle = argv[0]

    hits = hits_in_source(needle)
    where = surfaces(needle)

    print("where: %r" % (needle,))
    print("")
    if hits:
        print("in source:")
        shown = {}
        for path, line_no, line in hits:
            shown.setdefault(path, []).append((line_no, line))
        for path in sorted(shown):
            for line_no, line in shown[path][:3]:
                print("  %s:%d  %s" % (path, line_no, line[:96]))
            if len(shown[path]) > 3:
                print("  %s      ...and more in this file" % (" " * len(path),))
    else:
        print("in source: nothing under scripts/ui, report/, panel/ or hooks/")
    print("")
    print("reaches:")
    if where:
        for s in where:
            print("  " + s)
    else:
        print("  neither assembled surface - it is source that never ships, or a "
              "name built at runtime")
    print("")
    print("a change here owes:")
    for g in gates_for(where, [h[0] for h in hits]):
        print("  " + g)
    return 0


if __name__ == "__main__":
    from _output import safe_stdio
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
