#!/usr/bin/env python3
"""
The cases for `status/_impact.py` - who, among a repository's tracked files,
reads a file a task is about to change.

- **Every kind of reference is asked for by the file that carries it.** The
  fixture's dependants are a Python import, a shell heredoc importing the module,
  a CI step naming its path and a fenced Markdown command naming its basename;
  `im1` asserts the whole `{file: kind}` map, so a scan that found three of the
  four, or read a path reference as a bare basename, is red.
- **The over-fire twin sits beside it.** `im2` keeps a tracked file whose text
  is ONE CHARACTER off each reference - a longer basename, a longer module name,
  a name with a suffix - and the module itself, an untracked file and a
  gitignored file that all do import it. None may be listed: a scan that matched
  substrings, or searched the work tree rather than the index, goes red there.
- **A defined name is reported with the files that name it, and only those.**
  `im3` asserts the exact file list for the one top-level function a second file
  calls without importing the module, and that a name nothing else uses is not
  listed at all.
- **A cap is printed with its total.** `im4` caps the list below its length and
  asserts the rendering carries both numbers; a silent cut is the failure.
- **A non-Python file gets the same path and basename reading** (`im5`) and no
  name scan, and **a repository that cannot be read says so** (`im6`) in words
  the empty answer never uses - the two sentinels are told apart, both ways.
- **The git calls are bounded** (`im7`): at most two per declared file, counted
  through the injected runner rather than assumed; `im8` refuses the PCRE form
  the way a git built without it does and asserts the same answer, with the
  fixed-string retry made once and never offered again.
- **The readers a dispatch demands stand beside their near misses** (`ow1`-`ow4`):
  a passage quoted beside the path is a pin and each shape one step off it is
  not, a heading naming the full path is a section and a longer path is not.
- **What is owed is bounded by what the task edits** (`eb1`-`eb4`, `rd1`-`rd2`):
  a pin outside the declared lines or outside the sections a declared path
  heads is not owed, a file declared to answer a reading is not asked for its
  own readers - each beside the twin that keeps the demand when the edit can
  reach it.
- **A delete or a rename owes its import readers** (`rm1`-`rm2`): a Python
  import, a basename loader call, a JS import - and not a CI step running the
  path or a document quoting the import.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import sys
import time
import warnings

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _impact as M                                # noqa: E402

_REFUND = '''"""The refund module; refund.py names itself and is no dependant."""


def split_refund(total, lines):
    return [total // lines] * lines


class Ledger(object):
    pass


def _never_called_elsewhere():
    return None


def _round_down(total):
    return total
'''

_TRACKED = {
    "pkg/refund.py": _REFUND,
    "pkg/user.py": "from refund import split_refund\n\nprint(split_refund(9, 3))\n",
    "tools/run.sh": "#!/bin/sh\npython3 - <<'EOF'\nimport refund\nprint(refund._round_down(3))\nEOF\n",
    # A private name of its own, sharing the module's spelling: a homonym.
    "notes/own.py": "def _round_down(x):\n    return x\n",
    # A CI step naming the path and a private name with it: code that reaches
    # the module, so the private name is that step's use of it.
    ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n"
                                "      - run: python3 pkg/refund.py --selftest\n"
                                "      - run: python3 pkg/refund.py --only _round_down\n",
    # A document that names the module AND one of its private names: prose
    # describing the module, not a caller of the name.
    "docs/guide.md": "Run it:\n\n```sh\npython3 refund.py --check\n```\n\n"
                     "`_round_down` truncates.\n",
    "pkg/caller.py": "def go(order):\n    return split_refund(order, 2)\n",
    # One character off every reference above: a longer basename, a longer
    # module name in an import, a defined name with a suffix.
    "notes/near.txt": "prefund.py and refund.pyc; import refunds; "
                      "split_refunds(1); Ledgers\n",
    ".gitignore": "build/\n",
    # A non-Python declared file and the three ways other files name it.
    "web/app.js": "export function boot() { return 1; }\n",
    "web/index.html": '<script type="module" src="app.js"></script>\n',
    "package.json": '{"main": "web/app.js"}\n',
    "docs/web.md": "The page script is `web/app.js`.\n",
    "config.json": '{"a": 1}\n',
    "web/load.js": "fetch('config.json');\n",
    "docs/alone.md": "Nobody names this file.\n",
    # JS/TS: importers that write the specifier without its extension, one that
    # writes the `.js` a TypeScript ESM build resolves, and a directory import
    # reaching an index file - plus the twins that must NOT count: a same-named
    # module in another directory, an alias, and a file nothing imports.
    "web/api.ts": "export function fmt(x) { return x; }\n",
    "web/app.ts": "import {fmt} from './api'\nfmt(1);\n",
    "lib/u.js": "const u = require('../web/api');\n",
    "web/esm.ts": "import z from './api.js';\n",
    "web/lib/index.ts": "export const x = 1;\n",
    "web/main.ts": "import x from './lib'\n",
    "other/api.ts": "export const a = 1;\n",
    "other/use.ts": "import a from './api'\n",
    "web/alias.ts": "import y from '@/web/api'\n",
    "web/lonely.ts": "export const z = 3;\n",
}
_UNTRACKED = {
    "scratch.py": "import refund\n",
    "build/out.py": "import refund\nsplit_refund(1, 1)\n",
}


def _write(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


def _repo():
    root = os.path.join(_harness.fixture_root("impact-"), "repo")
    os.makedirs(root)
    _harness.git(root, "init", "-q")
    _write(root, _TRACKED)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "fixture")
    _write(root, _UNTRACKED)
    return root


def _kinds(result):
    return dict((f["file"], f["via"]) for f in result["files"])


def _cases(check):
    root = _repo()
    try:
        _run_cases(check, root)
    finally:
        _harness.remove_tree(os.path.dirname(root))


def _run_cases(check, root):
    refund = M.dependants(root, ["pkg/refund.py"])[0]
    kinds = _kinds(refund)
    expected = {"pkg/user.py": "import", "tools/run.sh": "import",
                ".github/workflows/ci.yml": "path", "docs/guide.md": "basename"}
    check("im1 a Python module's dependants are the tracked files that import "
          "it (a .py import AND a .sh heredoc), name its path (a .yml step) or "
          "its basename (a fenced .md command), each read as its own kind: %r"
          % (kinds,),
          kinds == expected and refund["total"] == 4
          and refund.get("error") is None)

    listed = set(kinds)
    strays = sorted(listed & {"notes/near.txt", "pkg/refund.py", "scratch.py",
                              "build/out.py", "pkg/caller.py"})
    check("im2 THE OVER-FIRE TWIN: a file one character off every reference, "
          "the module itself, an untracked file and a gitignored file that DO "
          "import it, and a file that only calls a name, are none of them a "
          "path/import/basename dependant: strays=%r" % (strays,),
          not strays)

    names = dict((s["name"], s["files"]) for s in refund["symbols"])
    check("im3 a top-level function the module defines is reported with exactly "
          "the tracked files that name it as a word - not its own file, not the "
          "suffixed near miss, not the gitignored caller - and a defined name "
          "nothing else uses is not listed: %r" % (names,),
          names.get("split_refund") == ["pkg/caller.py", "pkg/user.py"]
          and "Ledger" not in names and "_never_called_elsewhere" not in names
          and refund["defined"] == 4)
    check("im3b a private name (leading underscore) counts only in files that "
          "also reference the module: the heredoc importing it and the CI step "
          "naming its path are listed, the file defining a _round_down of its "
          "own is not: %r" % (names.get("_round_down"),),
          names.get("_round_down") == [".github/workflows/ci.yml", "tools/run.sh"])
    check("im3c a prose file that references the module is still its dependant "
          "but is no user of a private name it mentions - a document describing "
          "the module names its internals without calling them: %r / %r"
          % (names.get("_round_down"), kinds.get("docs/guide.md")),
          "docs/guide.md" not in (names.get("_round_down") or [])
          and kinds.get("docs/guide.md") == "basename")

    capped = M.dependants(root, ["pkg/refund.py"], cap=2)[0]
    text = "\n".join(M.render([capped]))
    check("im4 a list longer than the cap keeps the cap and the total, and the "
          "rendering prints both - never a silent cut: shown=%d total=%r %r"
          % (len(capped["files"]), capped["total"], text),
          len(capped["files"]) == 2 and capped["total"] == 4
          and "2 of 4 files shown" in text.split("\n")[0]
          and sum(1 for f in expected if f in text.split("\n")[0]) == 2)

    other = M.dependants(root, ["web/app.js", "docs/guide.md", "config.json",
                                "docs/alone.md"])
    by = dict((r["path"], r) for r in other)
    got = dict((p, _kinds(r)) for p, r in by.items())
    check("im5 a declared non-Python file (.js, .md, .json) gets its path and "
          "basename references the same way and no name scan, and a file "
          "nothing names has an empty list, not an error: %r" % (got,),
          got == {"web/app.js": {"web/index.html": "basename",
                                 "package.json": "path", "docs/web.md": "path"},
                  "docs/guide.md": {},
                  "config.json": {"web/load.js": "basename"},
                  "docs/alone.md": {}}
          and all(r["symbols"] == [] and r["defined"] == 0
                  and r.get("error") is None for r in other))

    lonely = M.render([by["docs/alone.md"]])
    bare = os.path.join(os.path.dirname(root), "not-a-repo")
    os.makedirs(bare)
    # A TMPDIR inside some checkout would let git find that one instead.
    ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = os.path.dirname(root)
    try:
        broken = M.dependants(bare, ["pkg/refund.py"])[0]
    finally:
        if ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = ceiling
    broken_text = M.render([broken])
    check("im6 the two sentinels apart: a file nothing names says so in ONE "
          "line, and a directory git cannot read carries the error and renders "
          "as could-not-read, never as the empty answer: %r / %r"
          % (lonely, broken_text),
          len(lonely) == 1 and "could not" not in lonely[0]
          and broken["error"] and broken["files"] == []
          and len(broken_text) == 1 and "could not read" in broken_text[0]
          and broken_text[0] != lonely[0])

    calls = []

    def counting(argv, cwd):
        calls.append(argv)
        return M.run_git(argv, cwd)

    M.dependants(root, ["pkg/refund.py", "web/app.js", "docs/alone.md"],
                 git=counting)
    check("im7 the scan is bounded: at most two git calls per declared file "
          "(one for references, one for a Python file's names), plus one for "
          "the prose passages of the whole scan: %d calls" % (len(calls),),
          0 < len(calls) <= 2 * 3 + 1 and all(a[0] == "grep" for a in calls))

    refused = []

    def no_pcre(argv, cwd):
        refused.append("-P" in argv)
        if "-P" in argv:
            return 128, "", ("fatal: cannot use Perl-compatible regexes when "
                             "not compiled with USE_LIBPCRE\n")
        return M.run_git(argv, cwd)

    # Two declared files that each define a name, so both reach a names call.
    two = ["pkg/refund.py", "pkg/caller.py"]
    plain = M.dependants(root, two, git=no_pcre)
    check("im8 a git without PCRE gets the same answer through the "
          "fixed-string form, offered PCRE once per scan and not again (the "
          "last call is the prose scan, fixed-string by design): "
          "calls=%r same=%r" % (refused, plain == M.dependants(root, two)),
          plain == M.dependants(root, two)
          and refused == [False, True, False, False, False, False])


def _js_cases(check):
    root = _repo()
    try:
        got = dict((r["path"], _kinds(r)) for r in M.dependants(
            root, ["web/api.ts", "web/lib/index.ts", "web/lonely.ts"]))
        check("im9 a .ts module's importers that write the specifier without "
              "its extension (import ... from './api', require('../web/api')), "
              "with the .js an ESM build resolves, and a directory import of an "
              "index file are each an `import` dependant: %r" % (got,),
              got.get("web/api.ts") == {"web/app.ts": "import",
                                        "lib/u.js": "import",
                                        "web/esm.ts": "import"}
              and got.get("web/lib/index.ts") == {"web/main.ts": "import"})
        strays = sorted(set(got.get("web/api.ts") or {})
                        & {"other/use.ts", "web/alias.ts", "other/api.ts"})
        check("im10 THE OVER-FIRE TWIN: './api' written next to a different "
              "api.ts, and an aliased '@/web/api', are not importers of "
              "web/api.ts: strays=%r" % (strays,),
              not strays and got.get("web/lonely.ts") == {})
        lonely = M.render(M.dependants(root, ["web/lonely.ts"]))
        md = M.render(M.dependants(root, ["docs/alone.md"]))
        both = M.render(M.dependants(root, ["web/api.ts", "web/lonely.ts"]))
        quiet = [ln for ln in both if ln.startswith("- web/lonely.ts")]
        check("im11 a file nothing names says what was searched: a JS/TS file "
              "by path, basename and import stem, with the aliased and dynamic "
              "imports that are not seen; a .md file by path and basename only, "
              "with no import claim: %r / %r / %r" % (lonely, md, quiet),
              len(lonely) == 1 and "import stem" in lonely[0]
              and "aliased or dynamic imports are not seen" in lonely[0]
              and len(md) == 1 and "path" in md[0] and "basename" in md[0]
              and "import" not in md[0]
              and len(quiet) == 1 and "import stem" in quiet[0]
              and "aliased or dynamic imports are not seen" in quiet[0])
    finally:
        _harness.remove_tree(os.path.dirname(root))


def _ranking_cases(check):
    root = _repo()
    try:
        refund = M.dependants(root, ["pkg/refund.py"])[0]
        vias = [f["via"] for f in refund["files"]]
        one = M.dependants(root, ["pkg/refund.py"], cap=1)[0]["files"]
        check("im12 importers are ranked ahead of a file naming the path, and "
              "that ahead of a bare basename mention, so a cap keeps the real "
              "callers: %r / cap 1 keeps %r" % (vias, one),
              vias == ["import", "import", "path", "basename"]
              and [f["via"] for f in one] == ["import"])
    finally:
        _harness.remove_tree(os.path.dirname(root))


def _budget_repo(count):
    root = os.path.join(_harness.fixture_root("impact-budget-"), "repo")
    os.makedirs(root)
    _harness.git(root, "init", "-q")
    files = {}
    for n in range(count):
        files["docs/n%02d.md" % n] = "page %d\n" % n
        files["refs/r%02d.txt" % n] = "see n%02d.md\n" % n
    _write(root, files)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "fixture")
    return root


def _budget_cases(check):
    order = M.scan_order(["docs/a.md", "src/x.py", "README.md", "src/y.js",
                          "docs/named.md", "src/z.py"],
                         "Fix the thing; named.md says how.")
    check("im13 the scan order is a stated rule: files the description names "
          "first, then source files before documents, each group in declared "
          "order: %r" % (order,),
          order == ["docs/named.md", "src/x.py", "src/y.js", "src/z.py",
                    "docs/a.md", "README.md"])

    count = 40
    root = _budget_repo(count)
    try:
        paths = ["docs/n%02d.md" % n for n in range(count)]
        calls = []

        def counting(argv, cwd):
            calls.append(argv)
            return M.run_git(argv, cwd)

        started = time.time()
        got = M.section(root, paths, "the last page, n39.md, is the one",
                        "LIST-ALL", git=counting)
        took = time.time() - started
        lines = got["lines"]
        shown = [ln for ln in lines if ln.startswith("- docs/n")]
        cut = "dependants of %d of %d declared files shown; the rest: LIST-ALL" % (
            len(shown), count)
        check("im14 a task declaring more files than the budget scans at most "
              "FILE_BUDGET of them, the one its description names among them, "
              "and prints how many of how many were shown and the command that "
              "lists the rest - never a silent cut: %d shown, %d git calls, "
              "%.2fs, last line %r" % (len(shown), len(calls), took, lines[-1:]),
              len(shown) == M.FILE_BUDGET and len(calls) <= 2 * M.FILE_BUDGET
              and lines[-1] == cut and got["shown"] == M.FILE_BUDGET
              and got["declared"] == count
              and any(ln.startswith("- docs/n39.md") for ln in shown)
              and len(lines) <= M.LINE_BUDGET + 1)
        tight = M.section(root, paths, "", "LIST-ALL", line_budget=5)
        tshown = [ln for ln in tight["lines"] if ln.startswith("- docs/n")]
        check("im15 the line budget binds too: at most that many lines are "
              "rendered, and the cut line counts what was shown: %r"
              % (tight["lines"],),
              len(tshown) == 5 and len(tight["lines"]) == 6
              and tight["lines"][-1] == ("dependants of 5 of %d declared files "
                                         "shown; the rest: LIST-ALL" % (count,)))
        small = M.section(root, paths[:3], "", "LIST-ALL")
        check("im16 THE ALLOW TWIN: a task under both budgets gets every file "
              "and no cut line: %r" % (small["lines"],),
              len(small["lines"]) == 3 and small["shown"] == 3
              and not any("declared files shown" in ln for ln in small["lines"]))
    finally:
        _harness.remove_tree(os.path.dirname(root))


_PINNED = "the refund is split evenly here"
_SOURCE = "def split():\n    return \"%s\"\n\nsplit_refund_total = 1\n" % (_PINNED,)


def _owed_cases(check):
    """The readers an edit can reach, each beside its near miss; the
    readers are found among tracked files, so `owed` itself is driven by the
    `dd` group of `test_audit_task.py` over a real repository."""
    path = "pkg/refund.py"
    pin = 'ROWS = (\n    ("%s",\n     "%s"),\n)\n' % (path, _PINNED)
    far = ('ROWS = ("%s",)\n' % (path,)) + "\n" * (M.ANCHOR_WINDOW + 2) \
        + ('X = "%s"\n' % (_PINNED,))
    check("ow1 a passage of the file quoted within the window of its path is a "
          "pin, and the passage is what is returned: %r"
          % (M.pinned_passage(pin, path, _SOURCE),),
          M.pinned_passage(pin, path, _SOURCE) == _PINNED)
    misses = {
        "outside the window": far,
        "an identifier, no whitespace":
            'PAIR = ("%s", "split_refund_total")\n' % (path,),
        "a path": 'PAIR = ("%s", "pkg/other refund.py here")\n' % (path,),
        "text the file does not hold":
            'PAIR = ("%s", "a sentence nobody wrote there")\n' % (path,),
        "the basename only": 'PAIR = ("refund.py", "%s")\n' % (_PINNED,),
    }
    got = dict((k, M.pinned_passage(v, path, _SOURCE)) for k, v in misses.items())
    check("ow2 THE OVER-FIRE TWINS: none of these is a pin - a passage past the "
          "window, an identifier, a path, text the file does not hold, a reader "
          "naming the basename alone: %r" % (got,),
          all(v is None for v in got.values()))
    check("ow3 a Markdown heading naming the full path is a section; the "
          "basename in a heading, the path in a sentence, and a longer path in "
          "a heading are not: %r"
          % ([M.heads_section(t, path) for t in (
              "## `pkg/refund.py`\n", "## refund.py\n",
              "It lives in pkg/refund.py.\n", "## pkg/refund.py.bak\n")],),
          M.heads_section("## `pkg/refund.py`\n", path)
          and not M.heads_section("## refund.py\n", path)
          and not M.heads_section("It lives in pkg/refund.py.\n", path)
          and not M.heads_section("## pkg/refund.py.bak\n", path))
    regex_reader = 'ROWS = ("%s",\n    r"x", "\\d+ refunds split here")\n' % (path,)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        M.pinned_passage(regex_reader, path, _SOURCE)
    check("ow5 a reader quoting a regex (an invalid escape to the parser) is "
          "read without a warning reaching stderr - the parser's complaint is "
          "about the reader's source, not this scan: %r"
          % ([str(w.message) for w in seen],),
          not [w for w in seen
               if issubclass(w.category, (SyntaxWarning, DeprecationWarning))])
    stems = M.suite_stems("scripts/run-gate.py")
    check("ow4 a suite is named after the file in each convention, a hyphen "
          "read as Python's underscore: %r" % (sorted(stems),),
          "test_run_gate" in stems and "run_gate_test" in stems
          and "run-gate.test" in stems and "run-gate.spec" in stems
          and "test_run" not in stems)


# The bounded fixture: one module with a passage in each half, a reader pinning
# each, a guide with a section per module (a fenced comment inside the first),
# a reader of a reader, and the four ways code reaches a file it would lose.
_HEAD = "the head passage stands here"
_TAIL = "the tail passage stands here"
_CORE_SECTION = "The core section text lives here"
_FENCED = "the fenced line under core"
_OTHER_SECTION = "The other section text lives here"
_PIN_NOTE = "a note only the pin file carries"
_BOUNDED = {
    "src/core.py": ('"""Core."""\n\n\ndef head():\n    return "%s"\n\n\n'
                    'def tail():\n    return "%s"\n' % (_HEAD, _TAIL)),
    "tests/test_core.py": "import core\n",
    "tools/pin_head.py": ('ROWS = (("src/core.py", "%s"),)\n'
                          'NOTE = "%s"\n' % (_HEAD, _PIN_NOTE)),
    "tools/pin_tail.py": 'ROWS = (("src/core.py", "%s"),)\n' % (_TAIL,),
    # A reader of the reader: its suite, and a file pinning its own text.
    "tests/test_pin_head.py": "import pin_head\n",
    "tools/pin_pin.py": 'PIN = ("tools/pin_head.py", "%s")\n' % (_PIN_NOTE,),
    "docs/guide.md": ("# Guide\n\n## `src/core.py`\n\n%s.\n\n```python\n"
                      "# a comment in a fence is no heading\nx = \"%s\"\n```\n\n"
                      "## `src/other.py`\n\n%s.\n"
                      % (_CORE_SECTION, _FENCED, _OTHER_SECTION)),
    "tools/doc_core.py": 'PIN = ("docs/guide.md", "%s")\n' % (_CORE_SECTION,),
    "tools/doc_fence.py": 'PIN = ("docs/guide.md", "%s")\n' % (_FENCED,),
    "tools/doc_other.py": 'PIN = ("docs/guide.md", "%s")\n' % (_OTHER_SECTION,),
    # What a delete or a rename breaks, and what it does not.
    "pkg/gone.py": "def g():\n    return 1\n",
    "pkg/uses.py": "import gone\n\nprint(gone.g())\n",
    "hooks/h.py": "import _config\n\nPATH = _config.find_script(\"gone.py\")\n",
    "scripts/run-it.py": "print(1)\n",
    "scripts/load.py": "import _loader\n\nM = _loader.load_script(\"run-it.py\")\n",
    "web/gone.js": "export const g = 1;\n",
    "web/use.js": "import {g} from './gone'\nconsole.log(g);\n",
    "ci.yml": "steps:\n  - run: python3 pkg/gone.py\n",
    "docs/d.md": "Write `import gone` to call it; scripts/run-it.py runs alone.\n",
}


def _bounded_repo():
    root = os.path.join(_harness.fixture_root("impact-bounded-"), "repo")
    os.makedirs(root)
    _harness.git(root, "init", "-q")
    _write(root, _BOUNDED)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "fixture")
    return root


def _owed_files(result):
    return sorted(set(r["file"] for r in result["owed"]))


def _owed(root, paths, **bounds):
    """`M.owed` with the bounding arguments. A signature that takes none of them
    answers with no rows and the TypeError as its error, so each case reads it
    as a failed assertion naming the missing argument rather than a block that
    never ran; every case passing a bound asserts a row present or no error."""
    try:
        return M.owed(root, paths, **bounds)
    except TypeError as exc:
        return {"owed": [], "errors": [{"path": None, "error": str(exc)}]}


def _bounded_cases(check):
    root = _bounded_repo()
    try:
        _region_cases(check, root)
        _reader_cases(check, root)
        _removal_cases(check, root)
    finally:
        _harness.remove_tree(os.path.dirname(root))


def _region_cases(check, root):
    # Lines 1-5 hold head(); tail()'s passage sits on line 9.
    head_only = _owed(root, ["src/core.py"], regions={"src/core.py": [(1, 5)]})
    whole = _owed(root, ["src/core.py"])
    check("eb1 a reader quoting a passage OUTSIDE the lines a task declares "
          "(`src/core.py:1-5`) is not owed - the edit cannot reach the text it "
          "pins: %r" % (_owed_files(head_only),),
          "tools/pin_tail.py" not in _owed_files(head_only)
          and not head_only["errors"])
    check("eb2 THE OVER-FIRE TWIN: the reader pinning a passage INSIDE the "
          "region is still owed, and with no region declared both pins are: "
          "%r / %r" % (_owed_files(head_only), _owed_files(whole)),
          "tools/pin_head.py" in _owed_files(head_only)
          and "tests/test_core.py" in _owed_files(head_only)
          and {"tools/pin_head.py", "tools/pin_tail.py"} <= set(_owed_files(whole)))

    sectioned = _owed(root, ["docs/guide.md", "src/core.py"])
    got = _owed_files(sectioned)
    check("eb3 a declared document is edited in the sections a declared path "
          "heads: a reader pinning text under `src/core.py`'s heading is owed "
          "(a fenced `#` comment does not end that section), one pinning the "
          "section headed by an undeclared path is not: %r" % (got,),
          "tools/doc_core.py" in got and "tools/doc_fence.py" in got
          and "tools/doc_other.py" not in got)
    alone = _owed_files(_owed(root, ["docs/guide.md"]))
    named = _owed_files(_owed(root, ["docs/guide.md", "src/core.py"],
                               regions={"docs/guide.md": None}))
    check("eb4 THE OVER-FIRE TWIN: a document no declared path heads a "
          "section of, or one the task names whole, is edited anywhere, so "
          "every pin of it is owed: %r / %r" % (alone, named),
          all(p in alone and p in named for p in (
              "tools/doc_core.py", "tools/doc_fence.py", "tools/doc_other.py")))


def _reader_cases(check, root):
    declared = ["src/core.py", "tools/pin_head.py"]
    as_reader = _owed_files(_owed(root, declared, readers=["tools/pin_head.py"]))
    as_edit = _owed_files(_owed(root, declared))
    check("rd1 a file declared to ANSWER a reading (`--files +reader`) is not "
          "asked for its own readers - its suite and the file pinning its text "
          "are not owed - while the edited file's readers still are: %r"
          % (as_reader,),
          "tests/test_pin_head.py" not in as_reader
          and "tools/pin_pin.py" not in as_reader
          and "tests/test_core.py" in as_reader)
    check("rd2 THE OVER-FIRE TWIN: the same file declared as an EDIT is asked "
          "for its readers - its suite and its pinner are owed: %r" % (as_edit,),
          "tests/test_pin_head.py" in as_edit and "tools/pin_pin.py" in as_edit)


def _removal_cases(check, root):
    gone = ["pkg/gone.py", "scripts/run-it.py", "web/gone.js"]
    removed = _owed(root, gone, removed=gone)
    rows = dict((r["file"], r) for r in removed["owed"])
    importers = ("pkg/uses.py", "hooks/h.py", "scripts/load.py", "web/use.js")
    check("rm1 a declared delete or rename owes every import reader of the "
          "file - a Python import, a hook's find_script basename, a "
          "load_script of a hyphenated entry point, a JS import - each under "
          "the kind `import`: %r"
          % (sorted((f, r["kind"], r["reads"]) for f, r in rows.items()),),
          all(rows.get(f, {}).get("kind") == "import" for f in importers)
          and rows["pkg/uses.py"]["reads"] == "pkg/gone.py"
          and rows["hooks/h.py"]["reads"] == "pkg/gone.py"
          and rows["scripts/load.py"]["reads"] == "scripts/run-it.py"
          and rows["web/use.js"]["reads"] == "web/gone.js")
    kept = _owed_files(_owed(root, gone))
    check("rm2 THE OVER-FIRE TWIN: the same files edited in place owe none of "
          "those importers, and a delete still does not owe a CI step running "
          "the path or a document quoting the import in prose: %r / %r"
          % (kept, sorted(rows)),
          not any(f in kept for f in importers)
          and "ci.yml" not in rows and "docs/d.md" not in rows)


# The prose fixture: three passages shaped like the ones a change left stale -
# a reference document naming a decision a driver's table defines, a README row
# naming a config key a lookup module reads, a suite's comment describing a
# runner by its basename - each beside the near misses that must not be listed.
_DRIVE = ('"""Driver."""\n\nDECISIONS = {\n    "gate-red-writer": "resume",\n'
          '    "gate-red-base": "block",\n}\nWORDS = ("gate-red-other",)\n'
          '# `gate-red-writer` is named here, in its own file.\n')
_LOOKUP = ('"""Lookup.\n\nLeaves a step to the phase gate when '
           '`executor.phaseGateOnly` names it; `meta.buildCommands` is a plan\n'
           'field, not a config key.\n"""\n\n\ndef brief():\n    return 1\n')
_PROSE_TREE = {
    "gov/drive.py": _DRIVE,
    "status/lookup.py": _LOOKUP,
    "gov/run-session.py": "def run():\n    return 1\n",
    "ref/execute.md": ("# Execute\n\n"
                       "3. **The recorded gate.** Red goes back to the session "
                       "(`gate-red-writer`).\n"),
    "README.md": ("| key | default |\n|---|---|\n"
                  "| `executor.phaseGateOnly` | every gate command is listed |\n"
                  "| `meta.buildCommands` | none |\n"),
    "tests/test_policy.py": ("import _loader\n"
                             "# `run-session.py` loads the skills a task names.\n"
                             "L = _loader.load_script(\"run-session.py\")\n"),
    # One step off each passage: a suffixed name, a bare (unquoted) name, a
    # string the driver holds that is no table key, a code line that is not a
    # comment, and a document naming the runner's basename - already a
    # `basename` dependant, not a prose row.
    "docs/near.md": ("`gate-red-writers` and gate-red-writer and `gate-red-other`.\n"
                     "Run `run-session.py` by hand.\n"),
    "tools/msg.py": 'MSG = "see `gate-red-writer`"\n',
    "docs/quiet.md": "Nothing here names a term.\n",
    # A changelog naming the decision records what it meant that day; a suite
    # keying the same decision in a fixture defines nothing, and a comment
    # naming the suite is no prose dependant of it.
    "CHANGELOG.md": "- `gate-red-writer` was added.\n",
    "tests/test_drive.py": ('import drive\nCASES = {"gate-red-writer": 1}\n'),
    "tools/see.py": "# cases in `test_drive.py`\n",
    # Two documents describing the driver: the one naming more of its terms
    # ranks first.
    "ref/guide.md": "`gate-red-base` then `gate-red-writer`.\n",
    # A rules module whose config root is also the stem of a workflow file it
    # names: the file name is no key, the key beside it is.
    "config/rules.py": ('"""Rules.\n\nThe workflow `ci.yml` and the key '
                        '`ci.pushCarry`.\n"""\n\nWORKFLOW = "ci.yml"\n'
                        'KEY = "ci.pushCarry"\n'),
    "docs/ci.md": "Edit `ci.yml` by hand.\n\nSet `ci.pushCarry` to carry.\n",
}


def _prose_repo():
    root = os.path.join(_harness.fixture_root("impact-prose-"), "repo")
    os.makedirs(root)
    _harness.git(root, "init", "-q")
    _write(root, _PROSE_TREE)
    _harness.git(root, "add", "-A")
    _harness.git(root, "commit", "-q", "-m", "fixture")
    return root


def _prose_scan(root, paths, **kw):
    """`M.dependants` with the config roots. A signature without them answers
    with no rows, so each case reads that as a failed assertion naming the
    missing argument rather than a block that never ran."""
    try:
        return M.dependants(root, paths, **kw), None
    except TypeError as exc:
        return [{"path": p, "prose": [], "files": [], "symbols": []}
                for p in paths], str(exc)


def _prose_rows(result):
    return sorted((r["name"], r["file"], r["line"])
                  for r in result.get("prose") or [])


def _prose_cases(check):
    root = _prose_repo()
    try:
        _prose_replays(check, root)
        _prose_bounds(check, root)
    finally:
        _harness.remove_tree(os.path.dirname(root))


def _prose_replays(check, root):
    paths = ["gov/drive.py", "status/lookup.py", "gov/run-session.py"]
    got, err = _prose_scan(root, paths, config_roots=("executor", "review"))
    by = dict((r["path"], _prose_rows(r)) for r in got)
    text = "\n".join(M.render(got)) if err is None else ""
    check("pr1 a decision a declared file's table defines (a dict key) and a "
          "reference document names in backticks is listed under that file "
          "with the name and the line - the recorded-gate passage: %r %r"
          % (by.get("gov/drive.py"), err),
          ("gate-red-writer", "ref/execute.md", 3) in (by.get("gov/drive.py") or [])
          and "ref/execute.md (`gate-red-writer`:3)" in text)
    check("pr2 a config key a declared file reads (named in backticks in its own "
          "text, under a config root) and a README row names is listed under that "
          "file - the phaseGateOnly default cell: %r %r"
          % (by.get("status/lookup.py"), err),
          by.get("status/lookup.py")
          == [("executor.phaseGateOnly", "README.md", 3)]
          and "README.md (`executor.phaseGateOnly`:3)" in text)
    check("pr3 a code comment naming a declared file's basename in backticks is "
          "listed under that file as prose, though the same file's import is "
          "already its `import` dependant - the skills-loaded comment: %r %r"
          % (by.get("gov/run-session.py"), err),
          by.get("gov/run-session.py")
          == [("run-session.py", "tests/test_policy.py", 2)]
          and "tests/test_policy.py (`run-session.py`:2)" in text)
    strays = sorted(set(f for rows in by.values() for _, f, _ in rows)
                    & {"docs/near.md", "tools/msg.py", "gov/drive.py",
                       "status/lookup.py", "docs/quiet.md", "CHANGELOG.md"})
    check("pr4 THE OVER-FIRE TWINS: a suffixed name, an unquoted name, a string "
          "the driver holds that keys no table, `meta.buildCommands` (no config "
          "root), a backticked name in a code string, a document's basename "
          "mention, a changelog line and the declared file's own comment are "
          "none of them a prose row: strays=%r rows=%r" % (strays, by),
          err is None and not strays
          and all(n != "meta.buildCommands" for rows in by.values()
                  for n, _, _ in rows))
    rootless, err2 = _prose_scan(root, ["status/lookup.py"])
    check("pr5 with no config roots given, a dotted name is no config key, so "
          "the lookup module has no prose row - the roots are the caller's "
          "statement, never guessed: %r %r" % (_prose_rows(rootless[0]), err2),
          err2 is None and _prose_rows(rootless[0]) == [])
    rules, err3 = _prose_scan(root, ["config/rules.py"],
                              config_roots=("ci", "executor"))
    named = sorted(set(n for n, _f, _l in _prose_rows(rules[0])))
    check("pr12 a file-name string whose stem is a config root (`ci.yml`) is no "
          "config key, so a document naming the workflow is no prose dependant "
          "of the file that names it: %r %r" % (_prose_rows(rules[0]), err3),
          err3 is None and "ci.yml" not in named
          and not [r for r in _prose_rows(rules[0]) if r[2] == 1])
    check("pr13 THE ALLOW TWIN: the dotted key beside it, under the same root, "
          "is still a config key and its passage still listed: %r"
          % (_prose_rows(rules[0]),),
          err3 is None and _prose_rows(rules[0]) == [("ci.pushCarry", "docs/ci.md", 3)])


def _prose_bounds(check, root):
    quiet, err = _prose_scan(root, ["docs/quiet.md", "gov/drive.py"],
                             config_roots=("executor",))
    lines = M.render(quiet) if err is None else []
    quiet_lines = [ln for ln in lines if "named in prose" in ln]
    check("pr6 THE ALLOW TWIN: a file defining no term renders no prose line, "
          "so the section spends no line on it; the file that has one renders "
          "exactly one: %r" % (lines,),
          err is None and len(quiet_lines) == 1
          and "gate-red-writer" in quiet_lines[0])
    calls = []

    def counting(argv, cwd):
        calls.append(argv)
        return M.run_git(argv, cwd)

    paths = ["gov/drive.py", "status/lookup.py", "gov/run-session.py"]
    plain, perr = _prose_scan(root, paths, config_roots=("executor",))
    _prose_scan(root, paths, config_roots=("executor",), git=counting)
    suite, serr = _prose_scan(root, ["tests/test_drive.py", "gov/drive.py"],
                              config_roots=("executor",))
    rows = dict((r["path"], _prose_rows(r)) for r in suite)
    check("pr8 a declared suite defines no term - its dict keys are fixtures and "
          "a comment naming it points at cases - while the module keying the "
          "same decision keeps its passages: %r %r" % (rows, serr),
          serr is None and rows.get("tests/test_drive.py") == []
          and ("gate-red-writer", "ref/execute.md", 3)
          in (rows.get("gov/drive.py") or []))
    drive = [r for r in suite if r["path"] == "gov/drive.py"]
    ranked = M.prose_files(drive[0]["prose"]) if drive else []
    line = [ln for ln in M.render(drive) if "named in prose" in ln] if drive else []
    check("pr9 the prose files are ranked by how many of the file's terms each "
          "names - the guide naming two before the reference naming one - and "
          "the line counts the files: %r %r" % ([r["file"] for r in ranked], line),
          [r["file"] for r in ranked] == ["ref/guide.md", "ref/execute.md"]
          and [n for n, _ in ranked[0]["names"]]
          == ["gate-red-base", "gate-red-writer"]
          and len(line) == 1 and "(2 files)" in line[0]
          and line[0].index("ref/guide.md") < line[0].index("ref/execute.md"))
    capped = dict(drive[0]) if drive else {"prose": [], "proseError": None}
    capped["prose"] = [{"name": "gate-red-writer", "file": "d%02d.md" % n, "line": 1}
                       for n in range(M.PROSE_CAP + 2)]
    cut = [ln for ln in M.render([capped]) if "named in prose" in ln] if drive else []
    check("pr10 more prose files than the cap keep the cap and print how many of "
          "how many - never a silent cut: %r" % (cut,),
          len(cut) == 1 and ("%d of %d files shown" % (M.PROSE_CAP, M.PROSE_CAP + 2))
          in cut[0] and cut[0].count(".md (") == M.PROSE_CAP)
    def prose_refused(argv, cwd):
        if "-n" in argv:
            return 128, "", "fatal: the prose scan was refused\n"
        return M.run_git(argv, cwd)

    broken, berr = _prose_scan(root, ["gov/drive.py"], config_roots=("executor",),
                               git=prose_refused)
    btext = [ln for ln in M.render(broken) if "named in prose" in ln] if berr is None else []
    check("pr11 a prose scan git refuses says so on the file - `proseError` set and "
          "the line reading `passages not read` - never the empty answer a file "
          "with no passage gets: %r %r" % (btext, berr),
          berr is None and broken[0].get("proseError")
          and broken[0].get("prose") == [] and len(btext) == 1
          and "passages not read: fatal: the prose scan was refused" in btext[0])
    check("pr7 the prose scan costs ONE git call for the whole scan, on top of "
          "the two per declared file: %d calls for %d files"
          % (len(calls), len(paths)),
          perr is None and 0 < len(calls) <= 2 * len(paths) + 1
          and any(r.get("prose") for r in plain))


def _selftest():
    def body(check):
        _harness.stage(check, "im-block", _cases)
        _harness.stage(check, "js-block", _js_cases)
        _harness.stage(check, "rk-block", _ranking_cases)
        _harness.stage(check, "bd-block", _budget_cases)
        _harness.stage(check, "ow-block", _owed_cases)
        _harness.stage(check, "eb-block", _bounded_cases)
        _harness.stage(check, "pr-block", _prose_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__impact.py --selftest\n")
    raise SystemExit(2)
