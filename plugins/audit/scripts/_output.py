#!/usr/bin/env python3
"""
Terminal output that cannot be killed by a character it cannot spell — stdlib only.

Python does not degrade an unprintable character; it raises. When stdout is a PIPE on
Windows, its encoding is the machine's legacy code page (cp1252 on a US/EU runner), and
`print("✓")` there is not a missing tick — it is a `UnicodeEncodeError`, a traceback and
a non-zero exit, with everything the command was going to say still unsaid.

The console is not the problem: Python has written UTF-8 to the Windows console since
3.6. Only redirected output falls back to the code page, which is why this is invisible
until someone pipes, tees or captures — and CI captures everything.

`safe_stdio()` is the whole fix: reconfigure both streams to UTF-8, and set the error
handler to `replace` so that even a stream that cannot be reconfigured, or a consumer
that really is cp1252, gets a `?` instead of a crash. UTF-8 first and `replace` second is
deliberate — the common case (a UTF-8 capable consumer) gets the real character, and the
impossible case degrades one glyph instead of losing the whole run.

WHERE IT APPLIES. Every entry point under `scripts/` calls it as its first statement, and
that is enforced rather than remembered: `entries_missing_guard()` reads the directory and
names any `__main__` block that does not, so the selftest CI already runs fails the moment
a new script forgets. Ordering matters as much as adoption — the guard has to run before
the first `print`, so a script that calls it late is a script that still crashes on its
first line of output.

`hooks/` deliberately does NOT import this. A hook's product output is `json.dumps`, which
is `ensure_ascii` by default and therefore pure ASCII by construction; its only other
output is its own selftest. Keeping the hooks importless is worth more than the guard —
they run on every tool call, from a launcher that may not have this directory on its path.
CI runs the whole selftest sweep a second time under `PYTHONIOENCODING=cp1252`, which is
what actually covers them, and would catch a hook that started printing prose with a glyph
in it.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__output.py`, and it was the last of the forty-eight to move —
`selftest_coverage()` below is what classified the other forty-seven on the way. Two
things had to change for it to classify ITSELF correctly, both recorded where they were
made: `_CONTRACT` is assembled rather than spelled, and every docstring (not only the
module's) is dropped before the proxy reads a file's strings. `--covered` is production
and is what CI's sweep skips by, so it keeps working with no suite here at all.
"""

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# `tests/` is a sibling of scripts/ and hooks/, not a subdirectory of either, so no
# existing walk reaches it and every lint that should cover it has to say so. The
# scope decision, recorded once here and again on each function: the DIALECT rules
# apply to tests too (`house_style_violations`, `entries_missing_guard`), because a
# test written with `typing` or a walrus is exactly as unrunnable on 3.8 as a script
# written that way, and a test that crashes on a cp1252 stream hides its own result.
_TESTS_DIR = os.path.join(os.path.dirname(_HERE), "tests")

# scripts -> audit -> plugins -> the repo root. Only `covered_repo_paths()` needs it,
# and it needs it because CI's sweep speaks repo-relative paths.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))


# --- safe stdio ---------------------------------------------------------------
def safe_stdio():
    """Make stdout/stderr unable to crash on a character they cannot spell.

    Idempotent, and never raises: a stream that has been replaced by a StringIO (which
    every selftest that captures output does) has no `reconfigure`, and a stream that has
    been detached has one that refuses. Neither is a reason to take the process down —
    the point of this function is that output problems stop being fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # No reconfigure (StringIO), already detached, or a platform that refuses.
            # `replace` alone is still worth having if the encoding move is what failed.
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


# --- finding the files to check ------------------------------------------------
def py_files(directory):
    """Sorted `(relname, path)` for every `.py` under `directory`, RECURSIVELY.

    The recursion is the point. Both lints below used a flat `os.listdir`, and so
    did CI's selftest glob and `_deps`' scanners — which is why `CONTRIBUTING.md`
    had to carry a rule saying `.py` must stay one directory deep: a file dropped
    into a subdirectory silently stopped being checked. The hazard was never the
    subdirectory, it was the SILENCE. A recursive walk removes the hazard instead
    of forbidding the shape, and it costs nothing today because there is no `.py`
    in a subdirectory yet — this change is a no-op on the current tree and only
    ever matters for a file somebody adds later.

    `relname` is relative to `directory` and uses forward slashes, so a violation
    in `usage/core.py` reports as `usage/core.py` rather than as a bare `core.py`
    that could be any of several files once folders exist. Today, with everything
    flat, it is exactly the basename it always was.

    Sorted so the output is stable across filesystems; `os.walk` order is not.
    """
    found = []
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, directory).replace(os.sep, "/")
            found.append((rel, path))
    found.sort()
    return found


# --- entry-point guard check --------------------------------------------------
def _is_entry(node):
    """True for `if __name__ == "__main__":`, however the comparison is spelled."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left] + list(node.test.comparators)
    return (any(isinstance(n, ast.Name) and n.id == "__name__" for n in names)
            and any(isinstance(n, ast.Constant) and n.value == "__main__" for n in names))


def _straight_line(body):
    """Statements that run when `body` runs, in order — not the ones merely DEFINED.

    A `print` inside a `def` is not output; it is a plan to produce output later, after
    the entry block has already installed the guard. Descending into function and class
    bodies would flag every script in the directory for code that cannot run first, so
    this walks the executable spine (module level, `if`/`try`/`with`/loop bodies) and
    stops at every definition boundary.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list):
                for sub in _straight_line(inner):
                    yield sub
        for handler in getattr(stmt, "handlers", []) or []:
            for sub in _straight_line(handler.body):
                yield sub


def _call_lines(stmts, func):
    return [s.lineno for s in stmts
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Name) and s.value.func.id == func]


def entries_missing_guard(dirs=None):
    """Names of .py files that run as a command but do not call safe_stdio() first.

    SCOPE: `scripts/` AND `tests/`, and deliberately not `hooks/` — hooks stay
    importless on purpose (see the module docstring) and are covered by CI's cp1252
    pass instead. `tests/` is in because a test file is run exactly the way a script
    is, prints far more prose than a script does, and would take its own result down
    with it on a Windows pipe; there is no reason it is exempt except that nothing
    used to look there.

    Returns a sorted list of names, each relative to the directory it was found in.
    Two ways to be listed, because both ship the same crash: never calling it, or
    calling it after something has already printed — a guard installed after the
    output it guards is decoration.

    "First" is judged on what EXECUTES, via `ast`, not on where text appears. Every one of
    these scripts defines printing functions hundreds of lines above its `__main__` block,
    so a textual "the call must precede the first `print(`" would name all fifteen of them
    for code that cannot possibly run before the guard. The rule is: among the statements
    that actually run — module level, then the entry block — no `print` may precede the
    `safe_stdio()` call. A file that cannot be parsed is reported rather than skipped,
    since a syntax error is a worse thing to pass over in silence.
    """
    dirs = dirs if dirs is not None else (_HERE, _TESTS_DIR)
    missing = []
    for d in dirs:
        for name, path in py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                missing.append(name)
                continue
            entries = [n for n in tree.body if _is_entry(n)]
            if not entries:
                continue  # imported module: its importer holds the guard
            runs = list(_straight_line(tree.body))
            guards = _call_lines(runs, "safe_stdio")
            prints = _call_lines(runs, "print")
            if not guards or (prints and min(prints) < min(guards)):
                missing.append(name)
    return sorted(missing)


# --- house-style AST checks ---------------------------------------------------
_HOOKS_DIR = os.path.join(os.path.dirname(_HERE), "hooks")

# The four bans: legal Python 3.8, illegal in this repo, and none of them caught by a
# version gate (vermin flags syntax the interpreter cannot run at all — every one of
# these runs fine on 3.8, it is just not this repo's style). Named here once so the
# checker and its selftest cases both read the same list rather than two lists drifting.
_BANNED_MODULES = ("typing", "dataclasses")


def _house_style_violations_in_tree(tree, name):
    """(line, what) tuples for one already-parsed module — the part `ast.walk` can see.

    Walks the WHOLE tree, not the straight-line spine `entries_missing_guard` walks:
    a walrus or a banned import is just as much a style violation buried inside a
    function body as it is at module level, so nothing here stops at a def boundary.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr):
            found.append((node.lineno, "walrus operator (:=)"))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                found.append((node.lineno, "from __future__ import"))
            elif node.module in _BANNED_MODULES:
                found.append((node.lineno, "from %s import" % node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _BANNED_MODULES:
                    found.append((node.lineno, "import %s" % alias.name))
    return [(name, line, what) for line, what in found]


def house_style_violations(dirs=None):
    """(filename, line, what) tuples for every banned construct under `dirs`.

    House style, not the 3.8 floor: walrus, `from __future__ import ...`, `typing` and
    `dataclasses` are all legal on Python 3.8, so vermin's version gate cannot see any
    of them — they are banned by convention, and conventions drift unless something
    reads the AST. Scans every `.py` under `scripts/`, `hooks/` AND `tests/`
    RECURSIVELY through `py_files`, the same walk `entries_missing_guard` uses — and
    for the same reason a file that will not parse is reported as a violation rather
    than skipped, since a syntax error is a worse thing to pass over in silence than
    any single banned import.

    `tests/` is in scope from the first day it existed. A test file is the most
    tempting place in the tree to reach for `typing` or a walrus — nothing ships it,
    so the usual argument feels weaker — and it is also the place where a 3.8
    violation costs most: the suite that would have caught the regression is itself
    the thing that will not start.
    """
    dirs = dirs if dirs is not None else (_HERE, _HOOKS_DIR, _TESTS_DIR)
    violations = []
    for d in dirs:
        for name, path in py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError) as exc:
                violations.append((name, getattr(exc, "lineno", 0) or 0,
                                    "file does not parse: %s" % exc))
                continue
            violations.extend(_house_style_violations_in_tree(tree, name))
    return violations


def _module_string_constants(tree):
    """`{NAME: (value, line)}` for MODULE-LEVEL `NAME = "literal"` assignments.

    Module level only — `tree.body`, not `ast.walk`. A same-named local inside a
    function is a different name with a different lifetime, and folding the two
    together would report a constant as duplicated by a variable that shadows it
    for three lines.
    """
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) \
                and isinstance(value.value, str):
            found[target.id] = (value.value, node.lineno)
    return found


def _names_read(tree):
    """Every name this module reads, as a bare name OR through an attribute.

    The attribute half matters: a constant nothing in its own file reads may still
    be another module's `panel_server.CONFIG_REL`, and deleting it would break a
    reader this file cannot see. Collecting `node.attr` across the tree is coarse —
    an unrelated `x.CONFIG_REL` counts — but it errs toward silence, which is the
    right direction for a lint whose remedy is DELETION.
    """
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            read.add(node.id)
        elif isinstance(node, ast.Attribute):
            read.add(node.attr)
    return read


def redundant_constants(dirs=None):
    """(filename, line, what) for a constant that is BOTH duplicated and dead.

    `panel-server.py` declared `CONFIG_REL = ".claude/audit.config.json"` and never
    read it, while importing `_panel_state`, which declares the same name with the
    same value and actually uses it. Nothing was broken and nothing would ever have
    gone red — the copy simply sat there being a second place the fact could drift
    from, and a reader grepping for the name found two answers.

    Both halves of the test are load-bearing, and the rule is narrow ON PURPOSE:

    - **duplicated** — a lone constant is a constant, not a defect.
    - **never read in its own module** — a duplicate that IS read is a real
      dependency, and removing it is a refactor with call sites to move. That is a
      different job, and a lint whose fix is sometimes "delete" and sometimes
      "restructure" gets ignored. When this fires, deletion is always correct.
    - **same directory only** — `hooks/` may not import `scripts/`, so
      `hooks/_config.CONFIG_REL` and `_panel_state.CONFIG_REL` are an IRREDUCIBLE
      pair. Reporting them would be demanding a fix the layer rule forbids, and a
      lint that cries about something nobody may fix teaches people to skip it.
      That pair is held true by `_usage_core`'s pricing cases instead — read, not
      merged.

    Scanned per directory through `py_files`, so a file one level down counts.

    `tests/` is NOT scanned, unlike the two dialect lints above, and the asymmetry is
    the point: this lint's whole remedy is DELETION, and two test files legitimately
    declaring the same fixture string are two independent fixtures, not one fact with
    two homes. Widening it here would produce a stream of reports whose correct answer
    is "no", which is how a lint stops being read.
    """
    dirs = dirs if dirs is not None else (_HERE, _HOOKS_DIR)
    violations = []
    for d in dirs:
        declared = {}
        unread = {}
        for name, path in py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                # house_style_violations already reports an unparseable file by
                # name; saying it twice adds noise, not information.
                continue
            consts = _module_string_constants(tree)
            read = _names_read(tree)
            unread[name] = set(n for n in consts if n not in read)
            for const_name, (value, line) in consts.items():
                declared.setdefault((const_name, value), []).append((name, line))
        for (const_name, value), sites in sorted(declared.items()):
            if len(sites) < 2:
                continue
            others = [n for n, _ in sites]
            for name, line in sites:
                if const_name not in unread.get(name, ()):
                    continue
                elsewhere = ", ".join(n for n in others if n != name)
                violations.append((name, line,
                                   "%s = %r is never read here and is already "
                                   "declared in %s" % (const_name, value, elsewhere)))
    return violations


# --- selftest coverage --------------------------------------------------------
# THE RULE WAS TRANSITIONAL AND IS NOT ANY MORE. While the move from inline
# `--selftest` blocks to `tests/` was under way it read "every `.py` under scripts/
# and hooks/ has EITHER an inline suite OR a file in tests/" - and a rule with an OR
# in it is exactly the shape that lets a file with NEITHER through, because the
# natural way to write it is `inline or covered` and that reads green for a file
# nobody has looked at. So nothing here has ever returned a boolean: every production
# file is placed in exactly one of four classes, and the caller asserts the COUNTS.
#
# All 48 files have moved, so the OR has nothing left to permit. `inline` is now a
# DEFECT class beside `both` and `neither`: a file that ships a new inline suite is
# named here rather than quietly accepted as the other half of a choice that no
# longer exists. That is a real tightening and not bookkeeping - a suite added inline
# would be run by CI's sweep, would pass, and would leave `tests/` looking complete
# while one module's cases lived somewhere else entirely.
#
# `both` is a defect and not a belt-and-braces bonus: two suites for one module drift,
# and the day they disagree there is no answer to "which one is the test". `neither`
# is the file the OR-shaped rule hid.
#
# ASSEMBLED, NOT WRITTEN OUT, and the reason is this module's own classification. The
# proxy below asks whether a file's STRING CONSTANTS carry both `--selftest` and the
# contract; spelled as one literal here, `_CONTRACT` IS such a constant, `__main__`
# supplies the other, and this file classified ITSELF as carrying a suite - measured,
# `both: ['scripts/_output.py']`, on the first run after its cases moved out. Same
# self-matching class as `_harness`' m1 needle and `_refs`' fixture constants: a
# scanner that lives in the tree it scans must not plant its own needle there.
_CONTRACT = "cases " + "passed"

_TEST_PREFIX = "test_"

# The classes a build must be empty of. Named once, here, rather than re-spelled as a
# tuple of keys at each call site - the question "is `inline` a defect this week" has
# exactly one answer and it belongs beside the classifier that produces the classes.
_DEFECT_CLASSES = ("inline", "both", "neither", "orphans", "collisions", "unreadable")


def _test_name_for(rel):
    """The `tests/` filename that covers the production file `rel`.

    Hyphens become underscores because a hyphenated name is not importable and never
    will be: `import test_migrate-manifest` is a syntax error, so the entry points -
    which are hyphenated BY CONVENTION here, to mark a thing something invokes - could
    not otherwise have a test module at all. Stated in code, in one place, because CI
    and the guide both need the same answer and a rule spelled twice is a rule with a
    disagreement waiting in it.
    """
    return "%s%s.py" % (_TEST_PREFIX, os.path.basename(rel)[:-3].replace("-", "_"))


def _carries_inline_selftest(path):
    """True / False / None (unreadable or unparseable) for "this file has its own suite".

    Judged on the file's STRING LITERALS carrying both `--selftest` and the
    `N/M cases passed` contract - the same literal CI greps for in a suite's OUTPUT.
    A file with a `_selftest()` that never prints the contract is not counted as
    inline here, and is also a file CI already fails by name; the two agree about
    what a suite is, which is the only property this proxy has to have.

    READ OFF THE AST, AND NOT OFF THE TEXT, for a reason found the hard way: the
    first version matched the raw source, and the COMMENT this module's own migration
    added to each migrated file - "it deliberately does NOT print the `N/M cases
    passed` contract" - contains the literal, so two of the three pilots came back
    classified as `both`. A comment is not in the AST at all, which removes that
    whole class rather than asking the next person to phrase a comment carefully.

    EVERY DOCSTRING IS DROPPED, not only the module's, and the widening was forced by
    THIS module. The first version dropped `tree.body[0]` alone, on the argument that
    a module docstring is the one place a file legitimately DESCRIBES its suite ("its
    11 cases live in ...") and a description is not an implementation. That argument
    was right and under-applied: when `_output.py`'s own cases moved out it came back
    classified `both`, because two of ITS function docstrings - this one and
    `covered_repo_paths`' - spell the contract while explaining what the contract is.
    A string that is a STATEMENT is prose wherever it sits; a suite prints the
    contract, and a `print(...)` argument is not a statement. So the filter is "an
    `ast.Expr` whose value is a string", at any nesting depth, which removes the class
    instead of asking each future docstring to phrase itself around a lint.

    Both ways of being wrong here are loud - a suite misread as migrated is reported
    as `neither` or `both`, and a migrated file misread as inline is failed by CI's
    sweep for not printing the contract - so the proxy never fails silently.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=os.path.basename(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
    prose = set(id(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))
    texts = [node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and id(node) not in prose]
    return (any(_CONTRACT in t for t in texts)
            and any("--selftest" in t for t in texts))


def selftest_coverage(script_dir=None, hooks_dir=None, tests_dir=None):
    """Where every production suite lives right now — a classification, not a verdict.

    Returns a dict of sorted lists, keyed by what is true of a file rather than by
    whether it is allowed:

      covered     no inline suite, and `tests/test_<name>.py` exists — the ONLY
                  clean class, and since the migration finished, all 48 of them
      inline      DEFECT: carries its own `--selftest` printing the contract and has
                  no test file. Clean while the migration ran and a regression now:
                  CI's sweep would run it, it would pass, and `tests/` would look
                  complete with one module's cases living somewhere else
      both        DEFECT: an inline suite AND a test file. Which one is the test?
      neither     DEFECT: no suite anywhere. The file the OR-shaped rule would hide
      orphans     DEFECT: a `tests/test_*.py` naming no production file that exists
      collisions  DEFECT: two production files mapping to one test name (`a-b.py`
                  and `a_b.py` both want `test_a_b.py`). `_deps` forbids two files
                  sharing a BASENAME; this is the same hazard one transform later
      unreadable  DEFECT: a production file that could not be read or parsed
      defects     every name in every defect class above, each tagged with the class
                  it fell into — so a caller asserts ONE thing and a failure names
                  the file rather than only a count
      total       how many production files were classified — `checked`, so that
                  "no defects" and "nothing was looked at" cannot print the same way

    Production names are kind-prefixed (`scripts/_cli_fmt.py`, `hooks/remind-tdd.py`)
    so a violation names a path the reader can open; orphans are named `tests/x.py`.
    `tests/_harness.py` is not a test file and is not an orphan candidate: the rule is
    about `test_*.py`, and the harness is the thing they all import.

    The end state is asserted, not hoped for: this returns 0 inline and every
    production file under `covered`, and the case that pins the `covered` list is the
    one that had to be edited to say so.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else _TESTS_DIR

    test_files = set(rel for rel, _path in py_files(tests_dir)
                     if os.path.basename(rel).startswith(_TEST_PREFIX))

    out = {"inline": [], "covered": [], "both": [], "neither": [],
           "orphans": [], "collisions": [], "unreadable": [], "defects": [],
           "total": 0}
    claimed = {}
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)):
        if not os.path.isdir(directory):
            continue
        for rel, path in py_files(directory):
            named = "%s/%s" % (kind, rel)
            out["total"] += 1
            expected = _test_name_for(rel)
            claimed.setdefault(expected, []).append(named)
            inline = _carries_inline_selftest(path)
            if inline is None:
                out["unreadable"].append(named)
                continue
            covered = expected in test_files
            if inline and covered:
                out["both"].append(named)
            elif inline:
                out["inline"].append(named)
            elif covered:
                out["covered"].append(named)
            else:
                out["neither"].append(named)

    for name in sorted(test_files - set(claimed)):
        out["orphans"].append("tests/%s" % name)
    for expected in sorted(claimed):
        if len(claimed[expected]) > 1:
            out["collisions"].append("tests/%s <- %s"
                                     % (expected, ", ".join(sorted(claimed[expected]))))
    for key in ("inline", "covered", "both", "neither", "unreadable"):
        out[key].sort()
    out["defects"] = ["%s %s" % (cls, name)
                      for cls in _DEFECT_CLASSES for name in out[cls]]
    return out


def covered_repo_paths(repo_root=None):
    """Repo-relative paths of the production files whose cases have moved to `tests/`.

    CI's selftest sweep reads this. A migrated file no longer prints the `N/M cases
    passed` contract, so the sweep has to skip it — and the skip list is derived from
    the same function that reports `neither`, rather than re-derived in shell, so the
    sweep cannot skip a file this lint has not accounted for.
    """
    root = repo_root if repo_root is not None else _REPO_ROOT
    plugin_dir = os.path.dirname(_HERE)
    return [os.path.relpath(os.path.join(plugin_dir, rel), root).replace(os.sep, "/")
            for rel in selftest_coverage()["covered"]]


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the usage line, which would exit 2
        # with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how `selftest_coverage()`
        # above tells an inline suite from a migrated one, and this module is the
        # one file in the tree where getting that wrong would misclassify every
        # other file as well.
        print("_output.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__output.py - run that file instead.")
        raise SystemExit(0)
    if "--covered" in sys.argv[1:]:
        # CI's sweep asks this, one line per path, so its skip list comes from the
        # classifier that also reports `neither` rather than from a name transform
        # re-implemented in shell. Empty output is the correct answer before the
        # migration starts and after it ends for opposite reasons; `--selftest`'s
        # sc10/sc11 are what tell those two apart, not this flag.
        for _rel in covered_repo_paths():
            print(_rel)
        raise SystemExit(0)
    sys.stderr.write("usage: _output.py --selftest | --covered\n")
    raise SystemExit(2)
