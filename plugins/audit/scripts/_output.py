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


# --- selftest coverage, during the migration ----------------------------------
# The rule while the move from inline `--selftest` blocks to `tests/` is half done:
# every `.py` under scripts/ and hooks/ has EITHER an inline suite OR a file in
# tests/. A rule with an OR in it is exactly the shape that lets a file with NEITHER
# through, because the natural way to write it is `inline or covered` and that reads
# green for a file nobody has looked at. So nothing here returns a boolean: every
# production file is placed in exactly one of four classes, two of which are defects,
# and the caller asserts the COUNTS.
#
# `both` is a defect and not a belt-and-braces bonus: two suites for one module drift,
# and the day they disagree there is no answer to "which one is the test".
_CONTRACT = "cases passed"

_TEST_PREFIX = "test_"


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

    The MODULE DOCSTRING is dropped for the same reason one step up: it is the one
    place a file legitimately DESCRIBES its suite ("its 11 cases live in ..."), and a
    description is not an implementation. Every other string still counts. Both ways
    of being wrong here are loud - a suite misread as migrated is reported as
    `neither` or `both`, and a migrated file misread as inline is failed by CI's
    sweep for not printing the contract - so the proxy never fails silently.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=os.path.basename(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
    body = tree.body
    if body and isinstance(body[0], ast.Expr) \
            and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    texts = [node.value for stmt in body for node in ast.walk(stmt)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    return (any(_CONTRACT in t for t in texts)
            and any("--selftest" in t for t in texts))


def selftest_coverage(script_dir=None, hooks_dir=None, tests_dir=None):
    """Where every production suite lives right now — a classification, not a verdict.

    Returns a dict of sorted lists, keyed by what is true of a file rather than by
    whether it is allowed:

      inline      carries its own `--selftest` printing the contract, no test file
      covered     no inline suite, and `tests/test_<name>.py` exists  (the migrated ones)
      both        DEFECT: an inline suite AND a test file. Which one is the test?
      neither     DEFECT: no suite anywhere. The file the OR-shaped rule would hide
      orphans     DEFECT: a `tests/test_*.py` naming no production file that exists
      collisions  DEFECT: two production files mapping to one test name (`a-b.py`
                  and `a_b.py` both want `test_a_b.py`). `_deps` forbids two files
                  sharing a BASENAME; this is the same hazard one transform later
      unreadable  a production file that could not be read or parsed
      total       how many production files were classified — `checked`, so that
                  "no defects" and "nothing was looked at" cannot print the same way

    Production names are kind-prefixed (`scripts/_cli_fmt.py`, `hooks/remind-tdd.py`)
    so a violation names a path the reader can open; orphans are named `tests/x.py`.
    `tests/_harness.py` is not a test file and is not an orphan candidate: the rule is
    about `test_*.py`, and the harness is the thing they all import.

    The end state is assertable, not hoped for: when the migration finishes this
    returns 0 inline and every production file under `covered`, and the case that
    pins the `covered` list is the one that has to be edited to say so.
    """
    script_dir = script_dir or _HERE
    hooks_dir = hooks_dir if hooks_dir is not None else _HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else _TESTS_DIR

    test_files = set(rel for rel, _path in py_files(tests_dir)
                     if os.path.basename(rel).startswith(_TEST_PREFIX))

    out = {"inline": [], "covered": [], "both": [], "neither": [],
           "orphans": [], "collisions": [], "unreadable": [], "total": 0}
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


# --- selftest -----------------------------------------------------------------
def _selftest():
    import subprocess
    import tempfile
    import shutil
    import io

    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # ------------------------------------------------------------------ the crash
    # Proven by reproduction, not by reasoning: the same one-line program, run twice,
    # differing only in whether the guard is installed. If the unguarded child ever
    # stops dying, this whole module is answering a question nobody is asking any more
    # and these cases are the ones that should say so.
    tmp = tempfile.mkdtemp(prefix="audit-output-")
    try:
        naked = os.path.join(tmp, "naked.py")
        with open(naked, "w", encoding="utf-8") as fh:
            fh.write('print("tick \\u2713 done")\n')

        guarded = os.path.join(tmp, "guarded.py")
        with open(guarded, "w", encoding="utf-8") as fh:
            fh.write(
                "import sys\n"
                "sys.path.insert(0, %r)\n"
                "from _output import safe_stdio\n"
                "safe_stdio()\n"
                'print("tick \\u2713 done")\n' % _HERE)

        def run(path, io_encoding):
            env = dict(os.environ, PYTHONIOENCODING=io_encoding)
            return subprocess.run([sys.executable, path], env=env,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")

        bare = run(naked, "cp1252")
        check("a1 an unguarded print of a non-cp1252 glyph DIES on a cp1252 stream - "
              "this is the Windows CI failure, reproduced on any platform",
              bare.returncode != 0)
        check("a2 ...and it dies with UnicodeEncodeError, not some other error that "
              "would mean this module is fixing the wrong thing",
              "UnicodeEncodeError" in bare.stderr)
        check("a3 ...losing the whole line, not just the glyph: nothing is printed",
              "done" not in bare.stdout)

        safe = run(guarded, "cp1252")
        check("b1 the guarded child survives the same stream", safe.returncode == 0)
        check("b2 ...and still says everything it had to say", "done" in safe.stdout)

        utf8 = run(guarded, "utf-8")
        check("c1 a UTF-8 consumer gets the REAL character, not the degraded one - "
              "'replace' is the floor, not the behaviour", "✓" in utf8.stdout)

        # ------------------------------------------------------- the guard's own edges
        held = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            safe_stdio()  # a StringIO has no reconfigure at all
            failed = False
        except Exception:
            failed = True
        finally:
            sys.stdout, sys.stderr = held
        check("d1 a captured stream (StringIO, which every capturing selftest installs) "
              "is not a reason to take the process down", not failed)

        # -------------------------------------------------------------- adoption lint
        fake = os.path.join(tmp, "fake")
        os.makedirs(fake)
        with open(os.path.join(fake, "importable.py"), "w", encoding="utf-8") as fh:
            fh.write('def f():\n    print("hi")\n')  # no __main__: not an entry point
        with open(os.path.join(fake, "forgot.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__":\n    print("hi")\n')
        with open(os.path.join(fake, "late.py"), "w", encoding="utf-8") as fh:
            fh.write('print("early")\n'
                     'if __name__ == "__main__":\n'
                     '    safe_stdio()\n')
        with open(os.path.join(fake, "ok.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__":\n'
                     '    safe_stdio()\n'
                     '    print("hi")\n')
        # The shape every real script in this directory has, and the one a textual lint
        # gets wrong: printing functions defined FIRST, the guard installed in the entry
        # block. Nothing here prints before the guard, because none of it runs before it.
        with open(os.path.join(fake, "defs.py"), "w", encoding="utf-8") as fh:
            fh.write('def render():\n'
                     '    print("output")\n'
                     'if __name__ == "__main__":\n'
                     '    safe_stdio()\n'
                     '    render()\n')
        with open(os.path.join(fake, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write('if __name__ == "__main__"\n    safe_stdio(\n')
        found = entries_missing_guard((fake,))
        check("e1 the lint names an entry point that never installs the guard",
              "forgot.py" in found)
        check("e2 ...and one that installs it AFTER printing, which crashes on the "
              "line the guard was added to protect", "late.py" in found)
        check("e3 an imported module with no __main__ is not an entry point and is "
              "not named", "importable.py" not in found)
        check("e4 a print inside a def is a plan to print, not printing - the shape "
              "every script here has, and the one a textual check misreads",
              "defs.py" not in found)
        check("e5 a file that will not parse is reported, not silently skipped - "
              "the lint must not be the thing that hides a syntax error",
              "broken.py" in found)
        check("e6 nothing else is named: %r" % (found,),
              found == ["broken.py", "forgot.py", "late.py"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The gate this module exists for. Every command under scripts/ AND tests/ is
    # covered, and a new one that forgets fails HERE - in a suite CI already runs -
    # rather than on a Windows runner, in one leg of a matrix, weeks later.
    real = entries_missing_guard()
    check("f1 every entry point under scripts/ installs the guard before it prints: %r"
          % (real,), not real)
    check("f2 ...and the default scope now reaches tests/ too, which is the half a "
          "sibling directory added: %r" % (sorted(n for n, _p in py_files(_TESTS_DIR)),),
          entries_missing_guard() == sorted(entries_missing_guard((_HERE,))
                                            + entries_missing_guard((_TESTS_DIR,)))
          and py_files(_TESTS_DIR) != [])

    # --------------------------------------------------------- house-style AST bans
    # Same shape as the adoption-lint block above: a fixture directory per case, each
    # proving the checker actually reads the construct rather than merely never having
    # seen one. A ban whose case never turns red before the implementation exists is a
    # decoration, not a check.
    style = tempfile.mkdtemp(prefix="audit-style-")
    try:
        with open(os.path.join(style, "walrus.py"), "w", encoding="utf-8") as fh:
            fh.write("if (n := 3) > 0:\n    print(n)\n")
        with open(os.path.join(style, "future.py"), "w", encoding="utf-8") as fh:
            fh.write("from __future__ import annotations\n")
        with open(os.path.join(style, "typing_import.py"), "w", encoding="utf-8") as fh:
            fh.write("import typing\n")
        with open(os.path.join(style, "typing_from.py"), "w", encoding="utf-8") as fh:
            fh.write("from typing import Optional\n")
        with open(os.path.join(style, "dataclasses_import.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("import dataclasses\n")
        with open(os.path.join(style, "dataclasses_from.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("from dataclasses import dataclass\n")
        with open(os.path.join(style, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write('def f(n):\n    return n + 1\n')
        with open(os.path.join(style, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def f(:\n")

        hits = house_style_violations((style,))
        by_file = {}
        for fname, line, what in hits:
            by_file.setdefault(fname, []).append(what)

        check("g1 the walrus operator is named as its own construct, not lumped in "
              "with everything else", any("walrus" in w for w in
              by_file.get("walrus.py", [])))
        check("g2 `from __future__ import ...` is caught even though it is legal "
              "3.8 syntax a version gate would wave through", any(
              "__future__" in w for w in by_file.get("future.py", [])))
        check("g3 `import typing` is caught", any(
              w == "import typing" for w in by_file.get("typing_import.py", [])))
        check("g4 `from typing import ...` is caught", any(
              "typing" in w for w in by_file.get("typing_from.py", [])))
        check("g5 `import dataclasses` is caught", any(
              w == "import dataclasses" for w in
              by_file.get("dataclasses_import.py", [])))
        check("g6 `from dataclasses import ...` is caught", any(
              "dataclasses" in w for w in by_file.get("dataclasses_from.py", [])))
        check("g7 a clean file with none of the four constructs is not named",
              "clean.py" not in by_file)
        check("g8 a file that will not parse is reported, not silently skipped - "
              "same rule entries_missing_guard already follows",
              "broken.py" in by_file)
        check("g9 every violation names a line number, so a failure can point at "
              "its offender rather than just its file",
              all(isinstance(line, int) and line > 0 for _, line, _ in hits
                  if _ != "broken.py"))
    finally:
        shutil.rmtree(style, ignore_errors=True)

    # The gate this half of the module exists for: scripts/ and hooks/, as they stand,
    # carry none of the four bans.
    real_style = house_style_violations()
    check("g10 neither scripts/ nor hooks/ carries any of the four house-style bans: %r"
          % (real_style,), not real_style)

    # ------------------------------------------------- the lints reach a subdirectory
    # The rule these replace said `.py` must stay one directory deep BECAUSE the
    # scanners were flat - a file in a subdirectory silently stopped being checked.
    # A fixture tree proves the recursion rather than the docstring claiming it: one
    # clean file at the top, one banned import a level down, one entry point a level
    # down with no guard.
    rec = tempfile.mkdtemp(prefix="audit-output-rec-")
    try:
        with open(os.path.join(rec, "flat_ok.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        os.makedirs(os.path.join(rec, "usage"))
        with open(os.path.join(rec, "usage", "banned.py"), "w", encoding="utf-8") as fh:
            fh.write("import typing\nx = 1\n")
        with open(os.path.join(rec, "usage", "unguarded.py"), "w", encoding="utf-8") as fh:
            fh.write('import sys\nif __name__ == "__main__":\n    print("hi")\n')
        with open(os.path.join(rec, "usage", "clean_entry.py"), "w", encoding="utf-8") as fh:
            fh.write('import sys\nif __name__ == "__main__":\n    safe_stdio()\n'
                     '    print("hi")\n')

        found = py_files(rec)
        names = [n for n, _ in found]
        check("r1 py_files walks into a subdirectory and names the file by its "
              "RELATIVE path, so `usage/banned.py` cannot be mistaken for a "
              "top-level `banned.py` once folders exist: %r" % (names,),
              names == ["flat_ok.py", "usage/banned.py", "usage/clean_entry.py",
                        "usage/unguarded.py"])

        hs = house_style_violations([rec])
        check("r2 a banned import one directory down IS reported - the flat scan "
              "this replaced returned [] for exactly this tree: %r" % (hs,),
              any(n == "usage/banned.py" for n, _l, _w in hs))
        check("r3 ...and the clean files beside it are NOT reported. Reads vacuous, "
              "and is the only case that fails if the walk starts flagging "
              "everything it can now see: %r" % (hs,),
              not any(n in ("flat_ok.py", "usage/clean_entry.py")
                      for n, _l, _w in hs))

        missing = entries_missing_guard((rec,))
        check("r4 an entry point one directory down with no safe_stdio() guard is "
              "named: %r" % (missing,),
              "usage/unguarded.py" in missing)
        check("r5 ...and a guarded one a level down is not - the second direction "
              "for the guard check too: %r" % (missing,),
              "usage/clean_entry.py" not in missing)
    finally:
        shutil.rmtree(rec, ignore_errors=True)

    # ------------------------------------------------- duplicated AND dead constants
    # Built as files rather than asserted against the real tree, because the real
    # tree is (now) clean and a lint only ever seen returning [] is a lint that
    # might be returning [] for the wrong reason.
    dup_a = tempfile.mkdtemp(prefix="audit-output-dup-a-")
    dup_b = tempfile.mkdtemp(prefix="audit-output-dup-b-")
    try:
        def _w(root, rel, text):
            path = os.path.join(root, rel)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

        # owner: declares the constant and uses it.
        _w(dup_a, "owner.py", 'REL = ".claude/x.json"\n\n\ndef p(root):\n'
                              '    return root + REL\n')
        # dead_dup: same name, same value, never read here. THE defect.
        _w(dup_a, "dead_dup.py", 'import os\nREL = ".claude/x.json"\n\n\n'
                                 'def p(root):\n    return os.sep\n')
        # live_dup: same name and value, but READ here - a real dependency, so
        # deleting it is a refactor and this lint must stay quiet.
        _w(dup_a, "live_dup.py", 'REL = ".claude/x.json"\n\n\ndef p(root):\n'
                                 '    return root + REL\n')
        # lonely: never read, but nothing else declares it - a constant, not a copy.
        _w(dup_a, "lonely.py", 'import os\nONLY = "solo"\n\n\ndef p():\n'
                               '    return os.sep\n')
        # attr_read: never read as a bare name, but read through an attribute, which
        # is what a cross-module `mod.NAME` looks like from inside this file.
        _w(dup_a, "attr_read.py", 'import os\nSHARED = "s"\n\n\ndef p(m):\n'
                                  '    return m.SHARED + os.sep\n')
        _w(dup_a, "attr_other.py", 'SHARED = "s"\n\n\ndef q():\n    return SHARED\n')
        # the cross-directory pair: identical, dead on one side, and IRREDUCIBLE.
        _w(dup_b, "hooks_copy.py", 'import os\nREL = ".claude/x.json"\n\n\n'
                                   'def p():\n    return os.sep\n')

        dups = redundant_constants([dup_a])
        named = ["%s:%d" % (n, l) for n, l, _w2 in dups]
        check("rc1 a constant that is declared elsewhere AND never read in its own "
              "module is reported, by file and line: %r" % (named,),
              named == ["dead_dup.py:2"])
        check("rc2 ...and the message names the OTHER declaration, so the fix does "
              "not start with a grep: %r" % ([w for _n, _l, w in dups],),
              dups and "live_dup.py" in dups[0][2] and "owner.py" in dups[0][2])
        check("rc3 a duplicate that IS read stays silent - removing it is a "
              "refactor with call sites, not a deletion, and a lint whose remedy "
              "changes shape gets ignored",
              not any(n == "live_dup.py" for n, _l, _w2 in dups))
        check("rc4 an unread constant nobody else declares stays silent - being "
              "unused is not this lint's business",
              not any(n == "lonely.py" for n, _l, _w2 in dups))
        check("rc5 a constant read only through an ATTRIBUTE counts as read, so a "
              "lint whose remedy is DELETION cannot delete another module's reader",
              not any(n == "attr_read.py" for n, _l, _w2 in dups))
        check("rc6 the same name and value in a DIFFERENT directory is not "
              "reported - hooks/ may not import scripts/, so that pair is "
              "irreducible and demanding a fix the layer rule forbids trains "
              "people to skip the lint: %r"
              % (redundant_constants([dup_a, dup_b]),),
              not any(n == "hooks_copy.py"
                      for n, _l, _w2 in redundant_constants([dup_a, dup_b])))
    finally:
        shutil.rmtree(dup_a, ignore_errors=True)
        shutil.rmtree(dup_b, ignore_errors=True)

    check("rc7 ...and the real tree carries none. This is the case that goes red "
          "when somebody adds the next copy: %r" % (redundant_constants(),),
          redundant_constants() == [])

    # ------------------------------------------- selftest coverage (transitional)
    # Fixture trees first, because the two DEFECT classes do not exist in the real
    # tree and a classifier only ever seen returning empty lists is a classifier that
    # might be returning empty lists for the wrong reason. Each fixture is one file
    # with a known answer, and the `neither`/`both` pair is written on purpose -
    # those are the two the OR-shaped version of this rule cannot see.
    cov_s = tempfile.mkdtemp(prefix="audit-cov-s-")
    cov_h = tempfile.mkdtemp(prefix="audit-cov-h-")
    cov_t = tempfile.mkdtemp(prefix="audit-cov-t-")
    try:
        def _w2(root, rel, text):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(text)

        suite = ('if __name__ == "__main__":\n'
                 '    if "--selftest" in sys.argv:\n'
                 '        print("ALL PASS: 1/1 cases passed")\n')
        _w2(cov_s, "keeps_its_own.py", suite)
        _w2(cov_s, "moved_out.py", "x = 1\n")           # no suite; covered below
        # A migrated file that DESCRIBES the contract in its docstring and mentions it
        # again in a comment. Both were read as "carries a suite" by the text-matching
        # first version, and two of the three real pilots came back as `both`.
        _w2(cov_s, "talks_about_it.py",
            '"""Its cases moved out; it no longer prints N/M cases passed."""\n'
            'import sys\n'
            'if __name__ == "__main__":\n'
            '    # deliberately does NOT print the `N/M cases passed` contract\n'
            '    if "--selftest" in sys.argv:\n'
            '        print("moved to tests/")\n')
        _w2(cov_s, "has-both.py", suite)                # suite AND a test file
        _w2(cov_s, "has_nothing.py", "x = 1\n")         # THE defect the OR hides
        _w2(cov_h, "hook_with_suite.py", suite)
        _w2(cov_t, "test_moved_out.py", suite)
        _w2(cov_t, "test_talks_about_it.py", suite)
        _w2(cov_t, "test_has_both.py", suite)           # hyphen -> underscore
        _w2(cov_t, "test_ghost.py", suite)              # names no production file
        _w2(cov_t, "_harness.py", suite)                # not a test file, not an orphan

        cov = selftest_coverage(cov_s, cov_h, cov_t)
        check("sc1 a file with an inline suite and no test file is `inline`: %r"
              % (cov["inline"],),
              cov["inline"] == ["hooks/hook_with_suite.py", "scripts/keeps_its_own.py"])
        check("sc2 a file with a test file and no inline suite is `covered` - the "
              "migrated shape: %r" % (cov["covered"],),
              cov["covered"] == ["scripts/moved_out.py", "scripts/talks_about_it.py"])
        check("sc2b a migrated file that DESCRIBES the contract - in its docstring "
              "and again in a comment - is still `covered`, never `both`. Found by "
              "this lint reporting two of its own three pilots: %r"
              % (cov["both"],),
              _carries_inline_selftest(os.path.join(cov_s, "talks_about_it.py"))
              is False)
        check("sc3 BOTH is reported as a defect, by name. Two suites for one module "
              "drift, and there is no answer to which one is the test: %r"
              % (cov["both"],), cov["both"] == ["scripts/has-both.py"])
        check("sc4 NEITHER is reported as a defect, by name. This is the file an "
              "`inline or covered` boolean waves through: %r" % (cov["neither"],),
              cov["neither"] == ["scripts/has_nothing.py"])
        check("sc5 a test file naming no production file is an orphan - dead weight "
              "that survives a deletion and looks like coverage: %r" % (cov["orphans"],),
              cov["orphans"] == ["tests/test_ghost.py"])
        check("sc6 ...and `_harness.py` is not an orphan. Reads vacuous, and is the "
              "only case that fails if the orphan rule stops looking at `test_` and "
              "starts flagging every file in the directory",
              not any("_harness" in o for o in cov["orphans"]))
        check("sc7 the hyphen->underscore transform is what connects has-both.py to "
              "test_has_both.py, so an ENTRY POINT can be covered at all",
              _test_name_for("has-both.py") == "test_has_both.py"
              and _test_name_for("migrate-manifest.py") == "test_migrate_manifest.py")
        check("sc8 every production file lands in exactly one class, and `total` "
              "says how many were looked at - so `no defects` and `nothing was "
              "scanned` cannot print the same way: %r" % (cov["total"],),
              cov["total"] == 6
              and len(cov["inline"]) + len(cov["covered"]) + len(cov["both"]) \
              + len(cov["neither"]) + len(cov["unreadable"]) == cov["total"])

        _w2(cov_s, "clash-name.py", "x = 1\n")
        _w2(cov_s, "clash_name.py", "x = 1\n")
        clash = selftest_coverage(cov_s, cov_h, cov_t)
        check("sc9 two production files wanting ONE test name is reported - `_deps` "
              "forbids a shared basename, and this is the same hazard one transform "
              "later: %r" % (clash["collisions"],),
              clash["collisions"] == ["tests/test_clash_name.py <- "
                                      "scripts/clash-name.py, scripts/clash_name.py"])
    finally:
        shutil.rmtree(cov_s, ignore_errors=True)
        shutil.rmtree(cov_h, ignore_errors=True)
        shutil.rmtree(cov_t, ignore_errors=True)

    # The real tree. The counts are the migration's progress report, and the two
    # defect classes are the invariant that has to hold on every commit in between.
    real_cov = selftest_coverage()
    check("sc10 the real tree: %d inline, %d covered, %d both, %d neither, %d "
          "orphans, %d collisions, %d unreadable, %d files"
          % (len(real_cov["inline"]), len(real_cov["covered"]), len(real_cov["both"]),
             len(real_cov["neither"]), len(real_cov["orphans"]),
             len(real_cov["collisions"]), len(real_cov["unreadable"]),
             real_cov["total"]),
          not (real_cov["both"] or real_cov["neither"] or real_cov["orphans"]
               or real_cov["collisions"] or real_cov["unreadable"]))
    check("sc11 ...and the migrated set is exactly the three pilots plus batch A. "
          "Editing this list is what a migration step COSTS, which is the point: "
          "the end state (0 inline, every file covered) is asserted here, never "
          "assumed: %r" % (real_cov["covered"],),
          real_cov["covered"] == ["hooks/remind-tdd.py",
                                  "scripts/_areas.py",
                                  "scripts/_cli_fmt.py",
                                  "scripts/_fmt.py",
                                  "scripts/_loader.py",
                                  "scripts/_manifest_io.py",
                                  "scripts/_panel_ui.py",
                                  "scripts/_policy.py",
                                  "scripts/_report_md.py",
                                  "scripts/_report_ui.py",
                                  "scripts/_usage_core.py",
                                  "scripts/audit-lock.py",
                                  "scripts/gen-demo-manifest.py",
                                  "scripts/gen-demo-usage.py",
                                  "scripts/migrate-manifest.py",
                                  "scripts/validate-config.py"])
    check("sc12 every production file is accounted for, so a file can neither be "
          "double-counted nor quietly dropped: %d + %d == %d"
          % (len(real_cov["inline"]), len(real_cov["covered"]), real_cov["total"]),
          len(real_cov["inline"]) + len(real_cov["covered"]) == real_cov["total"]
          and real_cov["total"] > 40)
    check("sc13 covered_repo_paths() speaks the repo-relative paths CI's sweep "
          "iterates, so the skip list and the `find` output are the same strings: %r"
          % (covered_repo_paths(),),
          covered_repo_paths() == ["plugins/audit/hooks/remind-tdd.py",
                                   "plugins/audit/scripts/_areas.py",
                                   "plugins/audit/scripts/_cli_fmt.py",
                                   "plugins/audit/scripts/_fmt.py",
                                   "plugins/audit/scripts/_loader.py",
                                   "plugins/audit/scripts/_manifest_io.py",
                                   "plugins/audit/scripts/_panel_ui.py",
                                   "plugins/audit/scripts/_policy.py",
                                   "plugins/audit/scripts/_report_md.py",
                                   "plugins/audit/scripts/_report_ui.py",
                                   "plugins/audit/scripts/_usage_core.py",
                                   "plugins/audit/scripts/audit-lock.py",
                                   "plugins/audit/scripts/gen-demo-manifest.py",
                                   "plugins/audit/scripts/gen-demo-usage.py",
                                   "plugins/audit/scripts/migrate-manifest.py",
                                   "plugins/audit/scripts/validate-config.py"]
          and all(os.path.isfile(os.path.join(_REPO_ROOT, p.replace("/", os.sep)))
                  for p in covered_repo_paths()))

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
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
