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

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import sys
import time

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
    ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n"
                                "      - run: python3 pkg/refund.py --selftest\n",
    "docs/guide.md": "Run it:\n\n```sh\npython3 refund.py --check\n```\n",
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
          "also reference the module: the heredoc importing it is listed, the "
          "file defining a _round_down of its own is not: %r"
          % (names.get("_round_down"),),
          names.get("_round_down") == ["tools/run.sh"])

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
          "(one for references, one for a Python file's names): %d calls"
          % (len(calls),),
          0 < len(calls) <= 2 * 3 and all(a[0] == "grep" for a in calls))

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
          "fixed-string form, offered PCRE once per scan and not again: "
          "calls=%r same=%r" % (refused, plain == M.dependants(root, two)),
          plain == M.dependants(root, two)
          and refused == [False, True, False, False, False])


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


def _selftest():
    def body(check):
        _harness.stage(check, "im-block", _cases)
        _harness.stage(check, "js-block", _js_cases)
        _harness.stage(check, "rk-block", _ranking_cases)
        _harness.stage(check, "bd-block", _budget_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__impact.py --selftest\n")
    raise SystemExit(2)
