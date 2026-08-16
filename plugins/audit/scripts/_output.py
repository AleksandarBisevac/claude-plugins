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


def entries_missing_guard(script_dir=None):
    """Names of scripts/*.py that run as a command but do not call safe_stdio() first.

    Returns a sorted list of basenames. Two ways to be listed, because both ship the same
    crash: never calling it, or calling it after something has already printed — a guard
    installed after the output it guards is decoration.

    "First" is judged on what EXECUTES, via `ast`, not on where text appears. Every one of
    these scripts defines printing functions hundreds of lines above its `__main__` block,
    so a textual "the call must precede the first `print(`" would name all fifteen of them
    for code that cannot possibly run before the guard. The rule is: among the statements
    that actually run — module level, then the entry block — no `print` may precede the
    `safe_stdio()` call. A file that cannot be parsed is reported rather than skipped,
    since a syntax error is a worse thing to pass over in silence.
    """
    script_dir = script_dir or _HERE
    missing = []
    for name, path in py_files(script_dir):
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
    return missing


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
    reads the AST. Scans every `.py` under `scripts/` and `hooks/` RECURSIVELY through
    `py_files`, the same walk `entries_missing_guard` uses — and for the same reason
    a file that will not parse is reported as a violation rather than skipped, since a
    syntax error is a worse thing to pass over in silence than any single banned import.
    """
    dirs = dirs if dirs is not None else (_HERE, _HOOKS_DIR)
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
        found = entries_missing_guard(fake)
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

    # The gate this module exists for. Every command under scripts/ is covered, and a new
    # one that forgets fails HERE - in a suite CI already runs - rather than on a Windows
    # runner, in one leg of a matrix, weeks later.
    real = entries_missing_guard()
    check("f1 every entry point under scripts/ installs the guard before it prints: %r"
          % (real,), not real)

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

        missing = entries_missing_guard(rec)
        check("r4 an entry point one directory down with no safe_stdio() guard is "
              "named: %r" % (missing,),
              "usage/unguarded.py" in missing)
        check("r5 ...and a guarded one a level down is not - the second direction "
              "for the guard check too: %r" % (missing,),
              "usage/clean_entry.py" not in missing)
    finally:
        shutil.rmtree(rec, ignore_errors=True)

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
    sys.stderr.write("usage: _output.py --selftest\n")
    raise SystemExit(2)
