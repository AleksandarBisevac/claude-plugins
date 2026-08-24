#!/usr/bin/env python3
"""
The cases for `_output.py`, moved out of it - the last of the forty-eight, and
the one that classifies the other forty-seven.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THE ONE EXPRESSION THAT COULD NOT MOVE LITERALLY, and it is the fixture that proves the
guard works. The `guarded.py` child written under `b1`/`c1` carries
`sys.path.insert(0, <dir>)` so that `from _output import safe_stdio` resolves in a fresh
interpreter. Moved literally, `<dir>` would be this file's directory - `tests/`, which
holds no `_output.py` - and the child would die on ImportError instead of surviving the
cp1252 stream. It reads `M.SCRIPTS_DIR`, the SUBJECT's own directory, which is the only value
that has ever been meant. (Loud rather than silent, as it happens: the child's stderr
would have named the ImportError. It is on this list because the case's whole claim is
about what the child could import.)

`M.SCRIPTS_DIR`, `M.TESTS_DIR` AND `M.REPO_ROOT` RATHER THAN THE `_harness` CONSTANTS. Same
three directories, different question: `f1`/`f2` ask what `entries_missing_guard()`
scans BY DEFAULT, and `sc13` asks which root `covered_repo_paths()` makes its paths
relative to. Respelling them off the harness would turn a claim about the subject's own
defaults into a claim about paths that happen to agree.

Nothing here patches a module global, reads `globals()`, or slices a source file - an
AST pass over the block before it moved found none of the seven shapes the guide lists.
What it has instead is the property this batch is named for: `f1`, `g10`, `rc7`,
`sc10`-`sc13` are assertions about the REAL tree, and the real tree now contains this
file. `f2` in particular requires `tests/` to be non-empty and every entry point in it
to install the guard - a rule this file is subject to, and satisfies, one line above.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output as M                                # noqa: E402
# `us8` asserts the anchor's doc-suffix set has ONE home: the ui/ walk here and
# `declared_asset_drift()` a layer up must skip the same files, or a README lands
# inside a digest, or an asset lands outside the comparison.
import _ui_theme                                   # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    import subprocess
    import tempfile
    import shutil
    import io

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
                'print("tick \\u2713 done")\n' % M.SCRIPTS_DIR)

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
            M.safe_stdio()  # a StringIO has no reconfigure at all
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
        found = M.entries_missing_guard((fake,))
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
    real = M.entries_missing_guard()
    check("f1 every entry point under scripts/ installs the guard before it prints: %r"
          % (real,), not real)
    check("f2 ...and the default scope now reaches tests/ too, which is the half a "
          "sibling directory added: %r"
          % (sorted(n for n, _p in M.py_files(M.TESTS_DIR)),),
          M.entries_missing_guard() == sorted(M.entries_missing_guard((M.SCRIPTS_DIR,))
                                              + M.entries_missing_guard((M.TESTS_DIR,)))
          and M.py_files(M.TESTS_DIR) != [])

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
        with open(os.path.join(style, "ann_param.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(value: str):\n    return value\n")
        with open(os.path.join(style, "ann_return.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(value) -> str:\n    return value\n")
        with open(os.path.join(style, "ann_assign.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("count: int = 0\n")
        with open(os.path.join(style, "ann_star.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("def f(*rest: str, **kw: int):\n    return rest, kw\n")
        with open(os.path.join(style, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write('def f(n, m=1):\n    return n + m\n')
        with open(os.path.join(style, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def f(:\n")

        hits = M.house_style_violations((style,))
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
        # ---- annotations: the half the rule claimed and nothing enforced -------
        # `CLAUDE.md` named this function as the enforcer of "no annotations" the
        # whole time and it read only walrus and two import shapes. The tree had
        # 113 of them, all in hooks/, and the check stayed green under a mutation
        # that added one. All THREE shapes are asserted separately, because a rule
        # written as "no annotations" that reads one of three is the same defect
        # one step smaller.
        check("ga1 an annotated PARAMETER is caught, and named with the parameter "
              "so a reader can find it: %r" % (by_file.get("ann_param.py"),),
              any("annotated parameter" in w and "value" in w
                  for w in by_file.get("ann_param.py", [])))
        check("ga2 a RETURN annotation is caught, and named with the function: %r"
              % (by_file.get("ann_return.py"),),
              any("return annotation" in w and "f" in w
                  for w in by_file.get("ann_return.py", [])))
        check("ga3 an annotated ASSIGNMENT is caught - the shape with no function "
              "around it at all: %r" % (by_file.get("ann_assign.py"),),
              any("annotated assignment" in w
                  for w in by_file.get("ann_assign.py", [])))
        check("ga4 `*args` and `**kw` annotations are caught TOO, and that is what "
              "one branch over `ast.arg` buys: a version walking each FunctionDef's "
              "arg lists by hand looks complete and misses exactly these two: %r"
              % (by_file.get("ann_star.py"),),
              len([w for w in by_file.get("ann_star.py", [])
                   if "annotated parameter" in w]) == 2)
        check("ga5 ...while a clean signature WITH A DEFAULT is not named - the "
              "rule is the annotation, not the `=`, and stripping 113 of them left "
              "defaults behind everywhere",
              "clean.py" not in by_file)
        check("g9 every violation names a line number, so a failure can point at "
              "its offender rather than just its file",
              all(isinstance(line, int) and line > 0 for _, line, _ in hits
                  if _ != "broken.py"))
    finally:
        shutil.rmtree(style, ignore_errors=True)

    # The gate this half of the module exists for: scripts/, hooks/ and tests/, as
    # they stand, carry none of the bans - INCLUDING annotations, which is new and is
    # why 113 of them came out of hooks/ in the same change that added the rule.
    real_style = M.house_style_violations()
    check("g10 no scanned directory carries any house-style ban, annotations "
          "included: %r" % (real_style,), not real_style)

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

        found = M.py_files(rec)
        names = [n for n, _ in found]
        check("r1 py_files walks into a subdirectory and names the file by its "
              "RELATIVE path, so `usage/banned.py` cannot be mistaken for a "
              "top-level `banned.py` once folders exist: %r" % (names,),
              names == ["flat_ok.py", "usage/banned.py", "usage/clean_entry.py",
                        "usage/unguarded.py"])

        hs = M.house_style_violations([rec])
        check("r2 a banned import one directory down IS reported - the flat scan "
              "this replaced returned [] for exactly this tree: %r" % (hs,),
              any(n == "usage/banned.py" for n, _l, _w in hs))
        check("r3 ...and the clean files beside it are NOT reported. Reads vacuous, "
              "and is the only case that fails if the walk starts flagging "
              "everything it can now see: %r" % (hs,),
              not any(n in ("flat_ok.py", "usage/clean_entry.py")
                      for n, _l, _w in hs))

        missing = M.entries_missing_guard((rec,))
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

        dups = M.redundant_constants([dup_a])
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
              % (M.redundant_constants([dup_a, dup_b]),),
              not any(n == "hooks_copy.py"
                      for n, _l, _w2 in M.redundant_constants([dup_a, dup_b])))
    finally:
        shutil.rmtree(dup_a, ignore_errors=True)
        shutil.rmtree(dup_b, ignore_errors=True)

    check("rc7 ...and the real tree carries none. This is the case that goes red "
          "when somebody adds the next copy: %r" % (M.redundant_constants(),),
          M.redundant_constants() == [])

    # ------------------------------------------------------- selftest coverage
    # Fixture trees first, because NO defect class exists in the real tree any more
    # and a classifier only ever seen returning empty lists is a classifier that
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

        cov = M.selftest_coverage(cov_s, cov_h, cov_t)
        check("sc1 a file with an inline suite and no test file is `inline`: %r"
              % (cov["inline"],),
              cov["inline"] == ["hooks/hook_with_suite.py", "scripts/keeps_its_own.py"])
        check("sc1b ...and `inline` is now a DEFECT, listed in `defects` beside "
              "`both` and `neither` rather than accepted as the other half of an OR "
              "that no longer has anything to permit: %r" % (cov["defects"],),
              "inline scripts/keeps_its_own.py" in cov["defects"]
              and "inline hooks/hook_with_suite.py" in cov["defects"]
              and "both scripts/has-both.py" in cov["defects"]
              and "neither scripts/has_nothing.py" in cov["defects"]
              and not any(d.startswith("covered ") for d in cov["defects"]))
        check("sc2 a file with a test file and no inline suite is `covered` - the "
              "migrated shape: %r" % (cov["covered"],),
              cov["covered"] == ["scripts/moved_out.py", "scripts/talks_about_it.py"])
        check("sc2b a migrated file that DESCRIBES the contract - in its docstring "
              "and again in a comment - is still `covered`, never `both`. Found by "
              "this lint reporting two of its own three pilots: %r"
              % (cov["both"],),
              M._carries_inline_selftest(os.path.join(cov_s, "talks_about_it.py"))
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
              M._test_name_for("has-both.py") == "test_has_both.py"
              and M._test_name_for("migrate-manifest.py") == "test_migrate_manifest.py")
        check("sc8 every production file lands in exactly one class, and `total` "
              "says how many were looked at - so `no defects` and `nothing was "
              "scanned` cannot print the same way: %r" % (cov["total"],),
              cov["total"] == 6
              and len(cov["inline"]) + len(cov["covered"]) + len(cov["both"]) \
              + len(cov["neither"]) + len(cov["unreadable"]) == cov["total"])

        _w2(cov_s, "clash-name.py", "x = 1\n")
        _w2(cov_s, "clash_name.py", "x = 1\n")
        clash = M.selftest_coverage(cov_s, cov_h, cov_t)
        check("sc9 two production files wanting ONE test name is reported - `_deps` "
              "forbids a shared basename, and this is the same hazard one transform "
              "later: %r" % (clash["collisions"],),
              clash["collisions"] == ["tests/test_clash_name.py <- "
                                      "scripts/clash-name.py, scripts/clash_name.py"])
    finally:
        shutil.rmtree(cov_s, ignore_errors=True)
        shutil.rmtree(cov_h, ignore_errors=True)
        shutil.rmtree(cov_t, ignore_errors=True)

    # The real tree. The counts stay visible - they were the migration's progress
    # report and they are now its result - and every defect class is the invariant
    # that has to hold on every commit from here on.
    real_cov = M.selftest_coverage()
    check("sc10 the real tree: %d inline, %d covered, %d both, %d neither, %d "
          "orphans, %d collisions, %d unreadable, %d files. Every class but "
          "`covered` is a defect now, and the assertion is `defects` rather than a "
          "tuple of keys re-spelled here, so a file that ships a new inline suite "
          "is named: %r"
          % (len(real_cov["inline"]), len(real_cov["covered"]), len(real_cov["both"]),
             len(real_cov["neither"]), len(real_cov["orphans"]),
             len(real_cov["collisions"]), len(real_cov["unreadable"]),
             real_cov["total"], real_cov["defects"]),
          not real_cov["defects"])
    check("sc11 ...and the migrated set is now EVERY production file - the three "
          "pilots, batches A through E, and the three lints that own this boundary "
          "and had to migrate themselves last. "
          "Editing this list is what a migration step COSTS, which is the point: "
          "the end state (0 inline, every file covered) is asserted here, never "
          "assumed: %r" % (real_cov["covered"],),
          real_cov["covered"] == ["hooks/_config.py",
                                  "hooks/detect-plan-skip.py",
                                  "hooks/guard-bash-writes.py",
                                  "hooks/guard-capabilities.py",
                                  "hooks/guard-edits.py",
                                  "hooks/guard-history-rewrite.py",
                                  "hooks/guard-secrets-read.py",
                                  "hooks/journal-writes.py",
                                  "hooks/meter-usage.py",
                                  "hooks/remind-tdd.py",
                                  "hooks/require-plan.py",
                                  "scripts/_cli_fmt.py",
                                  "scripts/_deps.py",
                                  "scripts/_fmt.py",
                                  "scripts/_loader.py",
                                  "scripts/_output.py",
                                  "scripts/_refs.py",
                                  "scripts/_ui_theme.py",
                                  "scripts/config/_config_rules.py",
                                  "scripts/config/_help.py",
                                  "scripts/config/validate-config.py",
                                  "scripts/demo/_demo_cast.py",
                                  "scripts/demo/gen-demo-manifest.py",
                                  "scripts/demo/gen-demo-usage.py",
                                  "scripts/governance/_invariants.py",
        "scripts/governance/_journal_io.py",
                                  "scripts/governance/_locks.py",
                                  "scripts/governance/_policy.py",
                                  "scripts/governance/audit-journal.py",
                                  "scripts/governance/audit-lock.py",
        "scripts/governance/verify-invariants.py",
                                  "scripts/manifest/_ado_connect.py",
                                  "scripts/manifest/_ado_conventions.py",
                                  "scripts/manifest/_ado_drift.py",
                                  "scripts/manifest/_ado_fetch.py",
                                  "scripts/manifest/_ado_fields.py",
                                  "scripts/manifest/_ado_parent.py",
                                  "scripts/manifest/_areas.py",
                                  "scripts/manifest/_branch.py",
                                  "scripts/manifest/_commit_trail.py",
                                  "scripts/manifest/_manifest_ado.py",
                                  "scripts/manifest/_manifest_crossrefs.py",
                                  "scripts/manifest/_manifest_io.py",
                                  "scripts/manifest/_manifest_phases.py",
                                  "scripts/manifest/_manifest_rules.py",
                                  "scripts/manifest/_manifest_typos.py",
                                  "scripts/manifest/_manifest_vocab.py",
                                  "scripts/manifest/_priority.py",
                                  "scripts/manifest/_proposals.py",
                                  "scripts/manifest/_warning_groups.py",
                                  "scripts/manifest/ado-connect.py",
                                  "scripts/manifest/audit-task.py",
                                  "scripts/manifest/check-ado-item.py",
                                  "scripts/manifest/explain-ado-drift.py",
                                  "scripts/manifest/fetch-ado-items.py",
                                  "scripts/manifest/materialize-proposal.py",
                                  "scripts/manifest/migrate-manifest.py",
                                  "scripts/manifest/repair-commits.py",
                                  "scripts/manifest/resolve-ado-parent.py",
                                  "scripts/manifest/resolve-branch.py",
                                  "scripts/manifest/set-priority.py",
                                  "scripts/manifest/validate-manifest.py",
                                  "scripts/panel/_panel_composition.py",
                                  "scripts/panel/_panel_discovery.py",
                                  "scripts/panel/_panel_page.py",
                                  "scripts/panel/_panel_paths.py",
                                  "scripts/panel/_panel_policy.py",
                                  "scripts/panel/_panel_runstate.py",
                                  "scripts/panel/_panel_settings.py",
                                  "scripts/panel/_panel_state.py",
                                  "scripts/panel/_panel_ui.py",
                                  "scripts/panel/_panel_usage.py",
                                  "scripts/panel/_panel_viewer.py",
                                  "scripts/panel/_panel_write.py",
                                  "scripts/panel/panel-server.py",
                                  "scripts/report/_report_html.py",
                                  "scripts/report/_report_md.py",
                                  "scripts/report/_report_page.py",
                                  "scripts/report/_report_ui.py",
                                  "scripts/report/_report_usage.py",
                                  "scripts/report/_usage_detail.py",
                                  "scripts/report/_usage_load.py",
                                  "scripts/report/_usage_markdown.py",
                                  "scripts/report/_usage_overview.py",
                                  "scripts/report/_usage_viz.py",
                                  "scripts/report/render-report.py",
                                  "scripts/status/_doctor_ado.py",
                                  "scripts/status/_doctor_completions.py",
                                  "scripts/status/_doctor_hygiene.py",
                                  "scripts/status/_doctor_policy.py",
                                  "scripts/status/_doctor_report.py",
                                  "scripts/status/_doctor_setup.py",
                                  "scripts/status/_doctor_trail.py",
                                  "scripts/status/_status_facts.py",
                                  "scripts/status/audit-doctor.py",
                                  "scripts/status/audit-status.py",
                                  "scripts/usage/_usage_bench.py",
                                  "scripts/usage/_usage_core.py",
                                  "scripts/usage/_usage_coverage.py",
                                  "scripts/usage/_usage_economics.py",
                                  "scripts/usage/_usage_routing.py",
                                  "scripts/usage/_usage_spend.py",
                                  "scripts/usage/audit-usage.py",
                                  "scripts/usage/usage_ledger.py"])
    check("sc12 every production file is accounted for, so a file can neither be "
          "double-counted nor quietly dropped: %d + %d == %d"
          % (len(real_cov["inline"]), len(real_cov["covered"]), real_cov["total"]),
          len(real_cov["inline"]) + len(real_cov["covered"]) == real_cov["total"]
          and real_cov["total"] > 40)
    check("sc13 covered_repo_paths() speaks the repo-relative paths CI's sweep "
          "iterates, so the skip list and the `find` output are the same strings: %r"
          % (M.covered_repo_paths(),),
          M.covered_repo_paths() == ["plugins/audit/hooks/_config.py",
                                     "plugins/audit/hooks/detect-plan-skip.py",
                                     "plugins/audit/hooks/guard-bash-writes.py",
                                     "plugins/audit/hooks/guard-capabilities.py",
                                     "plugins/audit/hooks/guard-edits.py",
                                     "plugins/audit/hooks/guard-history-rewrite.py",
                                     "plugins/audit/hooks/guard-secrets-read.py",
                                     "plugins/audit/hooks/journal-writes.py",
                                     "plugins/audit/hooks/meter-usage.py",
                                     "plugins/audit/hooks/remind-tdd.py",
                                     "plugins/audit/hooks/require-plan.py",
                                     "plugins/audit/scripts/_cli_fmt.py",
                                     "plugins/audit/scripts/_deps.py",
                                     "plugins/audit/scripts/_fmt.py",
                                     "plugins/audit/scripts/_loader.py",
                                     "plugins/audit/scripts/_output.py",
                                     "plugins/audit/scripts/_refs.py",
                                     "plugins/audit/scripts/_ui_theme.py",
                                     "plugins/audit/scripts/config/_config_rules.py",
                                     "plugins/audit/scripts/config/_help.py",
                                     "plugins/audit/scripts/config/validate-config.py",
                                     "plugins/audit/scripts/demo/_demo_cast.py",
                                     "plugins/audit/scripts/demo/gen-demo-manifest.py",
                                     "plugins/audit/scripts/demo/gen-demo-usage.py",
                                     "plugins/audit/scripts/governance/_invariants.py",
        "plugins/audit/scripts/governance/_journal_io.py",
                                     "plugins/audit/scripts/governance/_locks.py",
                                     "plugins/audit/scripts/governance/_policy.py",
                                     "plugins/audit/scripts/governance/audit-journal.py",
                                     "plugins/audit/scripts/governance/audit-lock.py",
        "plugins/audit/scripts/governance/verify-invariants.py",
                                     "plugins/audit/scripts/manifest/_ado_connect.py",
                                     "plugins/audit/scripts/manifest/_ado_conventions.py",
                                     "plugins/audit/scripts/manifest/_ado_drift.py",
                                     "plugins/audit/scripts/manifest/_ado_fetch.py",
                                     "plugins/audit/scripts/manifest/_ado_fields.py",
                                     "plugins/audit/scripts/manifest/_ado_parent.py",
                                     "plugins/audit/scripts/manifest/_areas.py",
                                     "plugins/audit/scripts/manifest/_branch.py",
                                     "plugins/audit/scripts/manifest/_commit_trail.py",
                                     "plugins/audit/scripts/manifest/_manifest_ado.py",
                                     "plugins/audit/scripts/manifest/_manifest_crossrefs.py",
                                     "plugins/audit/scripts/manifest/_manifest_io.py",
                                     "plugins/audit/scripts/manifest/_manifest_phases.py",
                                     "plugins/audit/scripts/manifest/_manifest_rules.py",
                                     "plugins/audit/scripts/manifest/_manifest_typos.py",
                                     "plugins/audit/scripts/manifest/_manifest_vocab.py",
                                     "plugins/audit/scripts/manifest/_priority.py",
                                     "plugins/audit/scripts/manifest/_proposals.py",
                                     "plugins/audit/scripts/manifest/_warning_groups.py",
                                     "plugins/audit/scripts/manifest/ado-connect.py",
                                     "plugins/audit/scripts/manifest/audit-task.py",
                                     "plugins/audit/scripts/manifest/check-ado-item.py",
                                     "plugins/audit/scripts/manifest/explain-ado-drift.py",
                                     "plugins/audit/scripts/manifest/fetch-ado-items.py",
                                     "plugins/audit/scripts/manifest/materialize-proposal.py",
                                     "plugins/audit/scripts/manifest/migrate-manifest.py",
                                     "plugins/audit/scripts/manifest/repair-commits.py",
          "plugins/audit/scripts/manifest/resolve-ado-parent.py",
                                     "plugins/audit/scripts/manifest/resolve-branch.py",
                                     "plugins/audit/scripts/manifest/set-priority.py",
                                     "plugins/audit/scripts/manifest/validate-manifest.py",
                                     "plugins/audit/scripts/panel/_panel_composition.py",
                                     "plugins/audit/scripts/panel/_panel_discovery.py",
                                     "plugins/audit/scripts/panel/_panel_page.py",
                                     "plugins/audit/scripts/panel/_panel_paths.py",
                                     "plugins/audit/scripts/panel/_panel_policy.py",
                                     "plugins/audit/scripts/panel/_panel_runstate.py",
                                     "plugins/audit/scripts/panel/_panel_settings.py",
                                     "plugins/audit/scripts/panel/_panel_state.py",
                                     "plugins/audit/scripts/panel/_panel_ui.py",
                                     "plugins/audit/scripts/panel/_panel_usage.py",
                                     "plugins/audit/scripts/panel/_panel_viewer.py",
                                     "plugins/audit/scripts/panel/_panel_write.py",
                                     "plugins/audit/scripts/panel/panel-server.py",
                                     "plugins/audit/scripts/report/_report_html.py",
                                     "plugins/audit/scripts/report/_report_md.py",
                                     "plugins/audit/scripts/report/_report_page.py",
                                     "plugins/audit/scripts/report/_report_ui.py",
                                     "plugins/audit/scripts/report/_report_usage.py",
                                     "plugins/audit/scripts/report/_usage_detail.py",
                                     "plugins/audit/scripts/report/_usage_load.py",
                                     "plugins/audit/scripts/report/_usage_markdown.py",
                                     "plugins/audit/scripts/report/_usage_overview.py",
                                     "plugins/audit/scripts/report/_usage_viz.py",
                                     "plugins/audit/scripts/report/render-report.py",
                                     "plugins/audit/scripts/status/_doctor_ado.py",
                                     "plugins/audit/scripts/status/_doctor_completions.py",
                                     "plugins/audit/scripts/status/_doctor_hygiene.py",
                                     "plugins/audit/scripts/status/_doctor_policy.py",
                                     "plugins/audit/scripts/status/_doctor_report.py",
                                     "plugins/audit/scripts/status/_doctor_setup.py",
                                     "plugins/audit/scripts/status/_doctor_trail.py",
                                     "plugins/audit/scripts/status/_status_facts.py",
                                     "plugins/audit/scripts/status/audit-doctor.py",
                                     "plugins/audit/scripts/status/audit-status.py",
                                     "plugins/audit/scripts/usage/_usage_bench.py",
                                     "plugins/audit/scripts/usage/_usage_core.py",
                                     "plugins/audit/scripts/usage/_usage_coverage.py",
                                     "plugins/audit/scripts/usage/_usage_economics.py",
                                     "plugins/audit/scripts/usage/_usage_routing.py",
                                     "plugins/audit/scripts/usage/_usage_spend.py",
                                     "plugins/audit/scripts/usage/audit-usage.py",
                                     "plugins/audit/scripts/usage/usage_ledger.py"]
          and all(os.path.isfile(os.path.join(M.REPO_ROOT, p.replace("/", os.sep)))
                  for p in M.covered_repo_paths()))

    # ------------------------------------------------------------------ the anchors
    # BEFORE AND AFTER, MEASURED. Seventeen sites used to derive a parent directory
    # from their OWN `__file__`; they now read one of the five anchors. On a flat
    # tree each must evaluate to the string it evaluated to before, and the way to
    # know that is to recompute the OLD expression here and compare - not to assert
    # that the new one looks right.
    #
    # Every consumer at once rather than a hand-picked few: the old expressions were
    # all functions of the consuming file's `__file__`, so running them over EVERY
    # `.py` under scripts/ proves the claim for all thirty-seven and keeps proving it
    # for the thirty-eighth. `_ab`/`_ab2`/`_ab4` are the three depths that were
    # actually spelled in the tree (`dirname` once, twice and four times).
    #
    # SCOPED TO THE FILES STILL AT DEPTH 0, AND THAT SCOPE IS THE FINDING RATHER THAN
    # A CONVENIENCE. `dirname(abspath(__file__))` is a claim about how deep a file
    # sits; it was true of all thirty-eight while `scripts/` was flat, and the files
    # now filed under a domain (`scripts/report/`, `scripts/usage/`,
    # `scripts/governance/`) are precisely the ones for which it stopped being true.
    # Recomputing it over them would not measure "the anchor equals what the old code
    # produced" — it would measure that the old code is the thing the preamble
    # replaced. `an8` carries the other half: a file AT DEPTH resolves to the same
    # anchor, by walking up to `_output.py` rather than by counting `dirname` calls,
    # which is the claim the preamble makes and the one no `dirname` chain can make.
    _paths = [p for rel, p in M.script_files() if "/" not in rel]
    _nested = [p for rel, p in M.script_files() if "/" in rel]
    _ab = [os.path.dirname(os.path.abspath(p)) for p in _paths]
    _ab2 = [os.path.dirname(d) for d in _ab]
    _ab4 = [os.path.dirname(os.path.dirname(d)) for d in _ab2]
    check("an1 SCRIPTS_DIR is what a TOP-LEVEL file's old `dirname(abspath("
          "__file__))` produced - %d files, one answer: %r"
          % (len(_paths), M.SCRIPTS_DIR),
          _paths and set(_ab) == set([M.SCRIPTS_DIR]))
    check("an2 PLUGIN_ROOT is what `_areas`/`_policy`'s old "
          "`dirname(dirname(abspath(__file__)))` and `_help`'s old `dirname(_HERE)` "
          "both produced: %r" % (M.PLUGIN_ROOT,),
          set(_ab2) == set([M.PLUGIN_ROOT])
          and os.path.basename(M.PLUGIN_ROOT) == "audit")
    check("an3 HOOKS_DIR is what `_deps`/`audit-doctor`/`audit-journal`'s old "
          "`join(dirname(_HERE), 'hooks')` produced: %r" % (M.HOOKS_DIR,),
          set(os.path.join(d, "hooks") for d in _ab2) == set([M.HOOKS_DIR])
          and os.path.isdir(M.HOOKS_DIR))
    check("an4 TESTS_DIR is what the old `join(dirname(_HERE), 'tests')` produced, "
          "and it is the directory this file is in: %r" % (M.TESTS_DIR,),
          set(os.path.join(d, "tests") for d in _ab2) == set([M.TESTS_DIR])
          and os.path.dirname(os.path.abspath(__file__)) == M.TESTS_DIR)
    check("an5 REPO_ROOT is what `_output`'s and `_refs`' old three-deep "
          "`dirname(dirname(dirname(_HERE)))` produced - the duplicate derivation "
          "that is now one: %r" % (M.REPO_ROOT,),
          set(_ab4) == set([M.REPO_ROOT])
          and os.path.isdir(os.path.join(M.REPO_ROOT, "plugins")))
    # The two sites whose OLD value was not normalised: `_panel_state`'s
    # `join(_HERE, "..", "hooks", "guard-capabilities.py")` and `_deps`'
    # `join(_HERE, "..", "..", "..", "PLUGIN-BUILD-GUIDE.md")` each carried `..`
    # segments in the middle of the string. The new values are the normpath of the
    # old ones, which is the honest comparison and is stated rather than glossed.
    _old_gc = os.path.join(M.SCRIPTS_DIR, "..", "hooks", "guard-capabilities.py")
    _old_guide = os.path.join(M.SCRIPTS_DIR, "..", "..", "..",
                              "PLUGIN-BUILD-GUIDE.md")
    check("an6 the two `..`-carrying sites resolve to the SAME FILE, and the new "
          "spelling is the normpath of the old - not the same string, which is why "
          "this case compares normpaths and says so",
          os.path.normpath(_old_gc)
          == os.path.join(M.HOOKS_DIR, "guard-capabilities.py")
          and os.path.normpath(_old_guide)
          == os.path.join(M.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md")
          and os.path.isfile(os.path.normpath(_old_gc))
          and os.path.isfile(os.path.normpath(_old_guide)))
    def _walk_up(path):
        """The preamble's own loop, verbatim: up from the file until `_output.py` is
        beside it. Reproduced here rather than imported because the thing under test
        IS the loop - reading it off the module it bootstraps would be the module
        agreeing with itself."""
        d = os.path.dirname(os.path.abspath(path))
        while not os.path.isfile(os.path.join(d, "_output.py")):
            up = os.path.dirname(d)
            if up == d:
                return None
            d = up
        return d

    check("an8 a file AT DEPTH reaches the SAME anchor - the preamble walks up to "
          "_output.py instead of counting dirnames, so `scripts/report/*.py` lands on "
          "SCRIPTS_DIR where `dirname(abspath(__file__))` would have landed on "
          "scripts/report. %d nested file(s); this is the case that had nothing to "
          "measure while the tree was flat" % (len(_nested),),
          _nested and set(_walk_up(p) for p in _nested) == set([M.SCRIPTS_DIR]))
    check("an9 ...and the OLD expression would have got it wrong, which is the "
          "direction that fails if the preamble is quietly replaced by a dirname "
          "count again",
          all(os.path.dirname(os.path.abspath(p)) != M.SCRIPTS_DIR for p in _nested))
    check("an7 ...and all five anchors are real directories, so a typo in one is a "
          "failure here rather than an empty scan somewhere downstream",
          all(os.path.isdir(d) for d in (M.SCRIPTS_DIR, M.PLUGIN_ROOT, M.HOOKS_DIR,
                                         M.TESTS_DIR, M.REPO_ROOT)))

    # ------------------------------------------------------------- script_files()
    check("sf1 script_files() is py_files(SCRIPTS_DIR) - the same list, not a "
          "second walk with its own rules", M.script_files() == M.py_files(M.SCRIPTS_DIR))
    check("sf2 ...and it is MEMOISED: the identical list object comes back, which "
          "is what keeps ~37 import-time bootstraps from doing ~37 os.walks",
          M.script_files() is M.script_files())
    check("sf3 refresh=True re-walks - the case that fails if the memo becomes "
          "permanent and a selftest that just wrote a fixture file cannot see it",
          M.script_files(refresh=True) is not M.script_files.__globals__[
              "_SCRIPT_FILES_CACHE"].get("nonexistent"))
    _fx = tempfile.mkdtemp(prefix="audit-anchor-")
    try:
        with open(os.path.join(_fx, "only.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        _held = list(M.script_files())
        _fixture_files = M.script_files(root=_fx)
        check("sf4 a fixture root is answered but NOT cached: the caller gets its "
              "own directory and the real tree's memo is untouched, so a case that "
              "passes a temp dir cannot poison what every other caller reads",
              [r for r, _p in _fixture_files] == ["only.py"]
              and M.script_files() == _held
              and M.script_files() is not _fixture_files)

        # ------------------------------------------------------------ install_path()
        _installed = M.install_path()
        check("ip1 install_path() RETURNS the list it installed - never None, never "
              "empty - so a caller can assert what happened instead of trusting "
              "that an import worked for some other reason: %r" % (_installed,),
              isinstance(_installed, list) and _installed)
        check("ip2 SCRIPTS_DIR is first, and every entry is on sys.path",
              _installed[0] == M.SCRIPTS_DIR
              and all(d in sys.path for d in _installed))
        check("ip3 the day a script moved has arrived: the list is SCRIPTS_DIR plus "
              "every domain under it - config/, demo/, governance/, manifest/, panel/ "
              "(the largest, seven files), report/ (the first ever created), status/ "
              "and usage/, in the walk's own sorted order rather than the order they "
              "were created. The list is now COMPLETE - the eighth and last domain "
              "landed with it, and the root holds only the cross-cutting modules. "
              "It said `exactly one directory` for as long as the tree was flat, and "
              "editing it is what each move COSTS - the mechanism is no longer a "
              "no-op and this is where that is stated: %r" % (_installed,),
              # `install_path()` MUST see a probe directory - `test__loader.py`
              # writes one into the real tree and needs it on sys.path - so the
              # filtering is in what this case COMPARES and never in the
              # function. The sweep runs both suites at once, and without it
              # the domain list gained a neighbour's fixture for the width of
              # one `finally`. `ip5` keeps the RAW list, because idempotence is
              # a property of the call and not of the tree.
              [d for d in _installed
               if not os.path.basename(d).startswith(M.LOADER_PROBE_DIR)]
              == [M.SCRIPTS_DIR,
                             os.path.join(M.SCRIPTS_DIR, "config"),
                             os.path.join(M.SCRIPTS_DIR, "demo"),
                             os.path.join(M.SCRIPTS_DIR, "governance"),
                             os.path.join(M.SCRIPTS_DIR, "manifest"),
                             os.path.join(M.SCRIPTS_DIR, "panel"),
                             os.path.join(M.SCRIPTS_DIR, "report"),
                             os.path.join(M.SCRIPTS_DIR, "status"),
                             os.path.join(M.SCRIPTS_DIR, "usage")])
        check("ip3b ...and it is DERIVED from the walk, not a constant: every entry "
              "past the root is a real directory holding at least one `.py`, so a "
              "later domain joins the list by existing rather than by being added "
              "here",
              all(os.path.isdir(d)
                  and any(f.endswith(".py") for f in os.listdir(d))
                  for d in _installed[1:]))
        check("ip4 scripts/ui/ is NOT on it, and not by an exemption: the list is "
              "derived from the `.py` walk, and ui/ holds CSS and JS only",
              os.path.isdir(os.path.join(M.SCRIPTS_DIR, "ui"))
              and os.path.join(M.SCRIPTS_DIR, "ui") not in _installed)
        _before_len = len(sys.path)
        check("ip5 idempotent: a second call returns the same list and grows "
              "sys.path by nothing",
              M.install_path() == _installed and len(sys.path) == _before_len)
        # A fixture tree with a subdirectory, which the real tree deliberately does
        # not have. Without this the whole point of the function - EVERY directory
        # holding a `.py`, not just the root - is asserted by nothing.
        os.makedirs(os.path.join(_fx, "manifest"))
        os.makedirs(os.path.join(_fx, "assets"))          # no .py: must not appear
        with open(os.path.join(_fx, "manifest", "deep.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("y = 2\n")
        with open(os.path.join(_fx, "assets", "style.css"), "w",
                  encoding="utf-8") as fh:
            fh.write("body{}\n")
        _sub = M.install_path(root=_fx)
        check("ip6 a subdirectory holding a `.py` IS installed, root first then the "
              "subdirectories sorted - the ~81 module-level sibling imports need "
              "the directory the IMPORTED file is in, not just the root: %r"
              % (_sub,),
              _sub == [_fx, os.path.join(_fx, "manifest")])
        check("ip7 ...and a subdirectory holding no `.py` is not - an editorial "
              "rule about ui/ turned into a mechanical one. Reads vacuous beside "
              "ip6 and is the only case that fails if the walk starts listing "
              "every directory it sees",
              os.path.join(_fx, "assets") not in _sub)
        for _d in _sub:
            if _d in sys.path:
                sys.path.remove(_d)
    finally:
        shutil.rmtree(_fx, ignore_errors=True)

    # ------------------------------------------------- the pinned path preamble
    check("pp1 the real tree carries the preamble exactly once in every `.py` "
          "under scripts/, above every sibling import: %r"
          % (M.path_preamble_violations(),),
          M.path_preamble_violations() == [])
    check("pp2 ...and `_output.py` is exempt BY NAME rather than by passing. It "
          "holds PATH_PREAMBLE as a string, so a text count over its own source "
          "finds exactly one occurrence and reads as compliant - the case that "
          "says the exemption is deliberate, not a coincidence",
          M._PREAMBLE_EXEMPT == "_output.py"
          and open(M.__file__, encoding="utf-8").read().count(M.PATH_PREAMBLE) == 1)
    check("pp3 the preamble is depth-INDEPENDENT by construction: it walks up "
          "looking for the marker file and spells no `dirname(dirname(`, no `..` "
          "and no count of levels",
          "_output.py" in M.PATH_PREAMBLE
          and "while not os.path.isfile" in M.PATH_PREAMBLE
          and "dirname(os.path.dirname" not in M.PATH_PREAMBLE
          and '".."' not in M.PATH_PREAMBLE)
    check("pp4 it terminates at the filesystem root with a NAMED ImportError "
          "rather than looping - the failure a bootstrap must not have",
          "raise ImportError" in M.PATH_PREAMBLE
          and "_anchor_up == _anchor_dir" in M.PATH_PREAMBLE)
    check("pp5 it carries no `# --- name ---` banner. `_deps._NAV_HEADER_RE` "
          "matches those at column 0, so a banner in every file would let a "
          "2,000-line module satisfy navigability_violations() on boilerplate",
          not any(re.match(r"^# --- (.+?) -+\s*$", ln)
                  for ln in M.PATH_PREAMBLE.split("\n")))
    _entries = [(r, open(p, encoding="utf-8").read()) for r, p in M.script_files()
                if os.path.basename(r) != M._PREAMBLE_EXEMPT]
    _entries = [(r, t) for r, t in _entries if '__name__ == "__main__"' in t]
    check("pp6 the __main__ blocks were NOT rewritten: all %d of them still spell "
          "`from _output import safe_stdio`, and NOTHING in scripts/ calls it as "
          "`_output.safe_stdio()`. That would be an ast.Attribute call, which "
          "`_call_lines` does not recognise, and entries_missing_guard() would "
          "then name every entry point in the tree" % (len(_entries),),
          len(_entries) > 30
          and all("from _output import safe_stdio" in t for _r, t in _entries)
          and not any("_output.safe_stdio" in t for _r, t in _entries))

    # The three ways the lint has to go red, each built as a file rather than
    # reasoned about. A lint only ever seen returning [] is a lint that might be
    # returning [] because it looks at nothing.
    pre = tempfile.mkdtemp(prefix="audit-preamble-")
    try:
        _good = ("import os\nimport sys\n\n" + M.PATH_PREAMBLE
                 + "\nimport _sibling  # noqa: E402\n")
        with open(os.path.join(pre, "_output.py"), "w", encoding="utf-8") as fh:
            fh.write("SCRIPTS_DIR = 1\n")
        # The sibling carries the preamble too: it is a `.py` under the fixture
        # `scripts/` and the rule applies to it, so leaving it bare would put a
        # fourth name in the expected list for a reason unrelated to any case.
        with open(os.path.join(pre, "_sibling.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE + "\nx = 1\n")
        with open(os.path.join(pre, "ok.py"), "w", encoding="utf-8") as fh:
            fh.write(_good)
        with open(os.path.join(pre, "missing.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\nimport _sibling\n")
        with open(os.path.join(pre, "doubled.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE + "\n"
                     + M.PATH_PREAMBLE + "\nimport _sibling  # noqa: E402\n")
        with open(os.path.join(pre, "too_late.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\nimport _sibling  # noqa: E402\n\n"
                     + M.PATH_PREAMBLE)
        hits = {}
        for name, why in M.path_preamble_violations(pre):
            hits.setdefault(name, []).append(why)
        check("pp7 a file with NO preamble is named, and the message says how many "
              "it has rather than only that something is wrong: %r"
              % (hits.get("missing.py"),),
              any("0 times" in w for w in hits.get("missing.py", []))
              and any("never calls _output.install_path()" in w
                      for w in hits.get("missing.py", [])))
        check("pp8 a DOUBLED preamble is named too - counted, not tested for "
              "membership, because `in` cannot tell one occurrence from two and "
              "two is a second walk-up and a second install: %r"
              % (hits.get("doubled.py"),),
              any("2 times" in w for w in hits.get("doubled.py", [])))
        check("pp9 a preamble placed BELOW the sibling import it exists to enable "
              "is named. It is exactly once, so the count says nothing; only the "
              "AST ordering check fires: %r" % (hits.get("too_late.py"),),
              any("above the _output.install_path()" in w
                  for w in hits.get("too_late.py", []))
              and not any("times" in w for w in hits.get("too_late.py", [])))
        check("pp10 ...and the correct file is NOT named. Reads vacuous beside the "
              "three above and is the only case that fails if the lint starts "
              "reporting everything: %r" % (sorted(hits),),
              "ok.py" not in hits and sorted(hits) == ["doubled.py", "missing.py",
                                                       "too_late.py"])
    finally:
        shutil.rmtree(pre, ignore_errors=True)

    # ------------------------------------------------ the self-location lint
    check("ds1 no `.py` under scripts/ reads `__file__` outside the pinned "
          "preamble any more - the seventeen sites are gone and this is what "
          "stops the eighteenth: %r" % (M.depth_sensitive_paths(),),
          M.depth_sensitive_paths() == [])
    dsl = tempfile.mkdtemp(prefix="audit-depth-")
    try:
        with open(os.path.join(dsl, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE + "\nx = 1\n")
        # The TWO-STEP shape, which is how sixteen of the seventeen were actually
        # written. A lint looking for `dirname(dirname(` nested in one expression
        # passes this file, which is why the rule is "no __file__ at all".
        with open(os.path.join(dsl, "two_step.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE
                     + '\n_HERE = os.path.dirname(os.path.abspath(__file__))\n'
                       'HOOKS = os.path.join(os.path.dirname(_HERE), "hooks")\n')
        with open(os.path.join(dsl, "nested.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE
                     + '\nR = os.path.dirname(os.path.dirname(os.path.abspath'
                       '(__file__)))\n')
        with open(os.path.join(dsl, "own_name.py"), "w", encoding="utf-8") as fh:
            fh.write("import os\nimport sys\n\n" + M.PATH_PREAMBLE
                     + '\nUSAGE = "usage: %s" % os.path.basename(__file__)\n')
        found = {}
        for name, line, _why in M.depth_sensitive_paths(dsl):
            found.setdefault(name, []).append(line)
        check("ds2 the TWO-STEP form is caught - `_HERE = dirname(abspath(...))` "
              "on one line and `dirname(_HERE)` on the next was how sixteen of the "
              "seventeen sites were written, and a nesting-only rule passes it: %r"
              % (found.get("two_step.py"),), "two_step.py" in found)
        check("ds3 the nested form is caught too", "nested.py" in found)
        check("ds4 `os.path.basename(__file__)` is NOT caught - it yields a NAME, "
              "not a location, and panel-server.py prints its own filename in a "
              "usage line", "own_name.py" not in found)
        check("ds5 a file carrying only the pinned preamble is NOT caught, though "
              "the preamble itself spells `dirname(abspath(__file__))`. The block "
              "is cut out before the scan; without that every file in the tree "
              "would be a violation and the lint would be uninstallable",
              "clean.py" not in found and sorted(found) == ["nested.py",
                                                            "two_step.py"])
    finally:
        shutil.rmtree(dsl, ignore_errors=True)

    # --------------------------------------------- --covered is LF on every platform
    # THE CASE THAT WOULD HAVE CAUGHT THE WINDOWS FAILURE. "the output contains no
    # \r" is not it: on Linux it cannot contain one, which is exactly why the whole
    # migration went green here and red on the windows leg. The property is asserted
    # where the PLATFORM decides it - a text stream constructed WITH translation on,
    # which any platform can build - so the fixture tells the two implementations
    # apart on the machine running this suite.
    _sink = io.BytesIO()
    _crlf = io.TextIOWrapper(_sink, encoding="utf-8", newline="\r\n")
    M.write_lf_lines(["a/b.py", "c/d.py"], _crlf)
    _crlf.flush()
    check("lf1 a stream that WOULD translate is reconfigured not to: the bytes are "
          "LF, on a fixture any platform can build. Restore the `print()` and this "
          "goes red on ubuntu, which the real bug never did: %r" % (_sink.getvalue(),),
          _sink.getvalue() == b"a/b.py\nc/d.py\n")
    _sink2 = io.BytesIO()
    _crlf2 = io.TextIOWrapper(_sink2, encoding="utf-8", newline="\r\n")
    _crlf2.write("a/b.py\nc/d.py\n")
    _crlf2.flush()
    check("lf2 ...and the fixture really does translate without the fix - measured, "
          "not remembered. This is the case that fails if the fixture stops being "
          "able to tell the buggy version from the fixed one: %r"
          % (_sink2.getvalue(),),
          _sink2.getvalue() == b"a/b.py\r\nc/d.py\r\n")
    _plain = io.StringIO()
    check("lf3 a stream with no reconfigure() (a StringIO, which every capturing "
          "selftest installs) is written to anyway rather than skipped - it does "
          "not translate in the first place",
          M.write_lf_lines(["x"], _plain) is _plain
          and _plain.getvalue() == "x\n")
    check("lf4 an empty list writes nothing at all, which is the correct answer "
          "before the migration starts and after it ends",
          M.write_lf_lines([], io.StringIO()).getvalue() == "")

    # --- pn: numbers written into prose (the rot this repo keeps meeting) -----
    _pn_live = M.prose_number_claims()
    check("pn0 no `.py` this repo keeps writes a present-tense number into its "
          "prose - every one of these has a live source one command away, so a "
          "copy in a docstring has no reader and nothing comparing it: %r"
          % (_pn_live[:6],),
          _pn_live == [])
    # Vacuity FIRST, because "no claims" and "read no files" print identically.
    #
    # TWO TERMS, F69's shape, and the second one is not derived from the thing it
    # measures. `scan_floor()` holds the scanned set against the CANDIDATE count
    # the same walk produced, which catches an exemption row that grew to swallow
    # a directory but cannot catch the walk itself collapsing - both fall
    # together. So the other half of this case is a PLAIN recursive walk of the
    # three directories that have to exist, which needs no `.gitignore` and so
    # cannot fail the way the derivation can: if the pruning ever starts eating
    # the plugin, the derived set drops below a walk that knows nothing about it.
    _pn_scan = M.prose_scan_set((".py",))
    _pn_plain = (len(M.py_files(M.SCRIPTS_DIR)) + len(M.py_files(M.HOOKS_DIR))
                 + len(M.py_files(M.TESTS_DIR)))
    check("pn1 the walk that produced pn0 read the tree, by two measures that "
          "fail differently - %d file(s) scanned of %d candidate(s), floor %d, "
          "against %d found by a plain walk that reads no `.gitignore`"
          % (len(_pn_scan["paths"]), _pn_scan["candidates"],
             M.scan_floor(_pn_scan["candidates"]), _pn_plain),
          _pn_scan["problem"] is None
          and len(_pn_scan["paths"]) >= M.scan_floor(_pn_scan["candidates"])
          and _pn_scan["candidates"] >= _pn_plain)
    check("pn2 CARDINALITY is caught, in each of the four shapes",
          M._prose_number_claim("its 124 cases live in `tests/test_x.py`")
              == "its 124 cases"
          and M._prose_number_claim("11 cases live in the suite")
              == "11 cases live in"
          and M._prose_number_claim("Config `x`. `--selftest` (26 cases).")
              == "--selftest (26 cases)"
          and M._prose_number_claim("the migration finished, all 64 of them")
              == "all 64 of them")
    check("pn3 the REPAIR is not itself a finding - dropping the number is the "
          "fix for all three families, so every fixed line must read clean or "
          "the lint would forbid its own remedy",
          M._prose_number_claim("its cases live in `tests/test_x.py`") is None
          and M._prose_number_claim("`--selftest`.") is None
          and M._prose_number_claim("the migration finished, all of them") is None
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` did not change and the "
                                    "map did not move") is None
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` is unchanged") is None
          and M._prose_number_claim("Every one of them has moved") is None)
    check("pn4 HISTORY stays writable - the past tense is how a decision record "
          "explains itself, and a lint that forbade it would push the rot into "
          "vaguer wording instead of removing it. `was still` and `stood at` "
          "are anchored to a past moment; `stayed at` with no anchor is not, "
          "which is why one is a finding and the other is not",
          M._prose_number_claim("ONE entry, down from the seventeen") is None
          and M._prose_number_claim("it stood at 70 cases that day, and was wrong")
              is None
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` was still 17 that day")
              is None
          and M._prose_number_claim("all 48 files carried their own copy") is None)
    check("pn5 a number that carries its own re-derivation is NOT a finding - "
          "the house rule is that a claim carries the basis that makes it true",
          M._prose_number_claim("its 82 cases live in x - re-derive with "
                                "`python3 tests/test_x.py --selftest`") is None)
    check("pn6 ...and the basis counts when it lands on the FOLLOWING line, "
          "because every document here is hard-wrapped. Judging the claim by "
          "its own line alone would report a line that has already satisfied "
          "the house rule, and the repair for THAT would be to delete the basis",
          M._prose_number_claim("into `tests/`, all 83 of them (`73042a1` - "
                                "print it with", "`python3 -c \"...\"`); a "
                                "migrated file still exits 0") is None
          and M._prose_number_claim("into `tests/`, all 83 of them (`73042a1` - "
                                    "print it with", "and then read it off.")
              == "all 83 of them")
    check("pn7 the word 'cases' without a count is untouched, so ordinary prose "
          "about edge cases does not become a violation",
          M._prose_number_claim("the edge cases this guard cannot see") is None
          and M._prose_number_claim("in most cases the answer is no") is None)
    check("pn8 PERSISTENCE is caught - F43's shape, and F39's. A claim that a "
          "number has not changed is the purest form of the rot, because the "
          "sentence's whole job is to be checked against the present",
          M._prose_number_claim("`KNOWN_LAYER_DEBT` stayed at 17 and the map "
                                "did not move") == "stayed at 17"
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` is still 17 and "
                                    "`--render` is byte-identical")
              == "is still 17"
          and M._prose_number_claim("`LAYERS` remains at 8") == "remains at 8"
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` remains 17")
              == "remains 17")
    check("pn9 ...and it fires ONLY where the line names code in backticks. The "
          "measured line this protects is `hooks/_config.py`'s counterfactual "
          "about a format string's width: it is correct, removing its number "
          "would destroy the sentence, and it names no code. The two fixtures "
          "differ in exactly that, so a gate that stopped working turns this red",
          M._prose_number_claim("the `Z` is a literal so it is still 17 wide")
              == "is still 17"
          and M._prose_number_claim("the result is still 20 characters, and "
                                    "strptime parses it") is None)
    check("pn10 COMPLETENESS is caught when it carries a present-tense "
          "auxiliary within three tokens, and the window is what separates a "
          "claim about now from a count followed by an unrelated relative "
          "clause seven tokens later",
          M._prose_number_claim("All 48 files have moved, so the OR is empty")
              == "all 48 ... have"
          and M._prose_number_claim("**All 48 have moved**, `sc10` asserts it")
              == "all 48 ... have"
          and M._prose_number_claim("pins all 17 alias lines this module's "
                                    "names are re-exported through") is None
          and M._prose_number_claim("against all 8 viz slots on this surface")
              is None)


    check("pn10b the BARE count is caught however it is introduced - the three "
          "narrow shapes above all needed an introducer ('its', 'live in', "
          "'--selftest'), and eight sites said it plainly instead: 'the N cases "
          "in tests/', 'across N cases', 'the ~N cases below'. SEVEN of the "
          "eight were already wrong, and the eighth was one added case from "
          "joining them",
          M._prose_number_claim("and the 285 cases in `tests/` that read the page")
              == "285 cases"
          and M._prose_number_claim("asks for them by hand across 112 cases")
              == "112 cases"
          and M._prose_number_claim("It also keeps the ~230 cases, and that is")
              == "230 cases"
          and M._prose_number_claim("holds the ~283 selftest cases that assert")
              == "283 cases")
    check("pn11 ...and this is the family wide enough to swallow RECOLLECTION, "
          "so it is the one that has to ask whether the line means THEN - "
          "without that, a decision record cannot say what a number used to be",
          M._prose_number_claim("it stood at 70 cases that day, and was wrong")
              is None
          and M._prose_number_claim("the suite was 285 cases before the split")
              is None
          and M._prose_number_claim("down from 48 cases once the migration ran")
              is None)
    check("pn12 the REPAIR of the bare shape reads clean, or the lint forbids "
          "its own remedy and everyone deletes the pointer too",
          M._prose_number_claim("and the cases in `tests/` that read the page")
              is None
          and M._prose_number_claim("asks for them by hand, case by case")
              is None
          and M._prose_number_claim("holds the selftest cases that assert")
              is None)
    check("pn13 a count spelled as a WORD is the same claim in a different "
          "spelling - F59, which sat in a comment block every gate reads because "
          "no lint was looking at that spelling. One numeral reader serves every "
          "shape, so the word form cannot reach one family and miss another",
          M._prose_number_claim("its thirteen cases live in `tests/test_x.py`")
              == "its thirteen cases"
          and M._prose_number_claim("eleven cases live in the suite")
              == "eleven cases live in"
          and M._prose_number_claim("Config `x`. `--selftest` (nineteen cases).")
              == "--selftest (nineteen cases)"
          and M._prose_number_claim("the migration finished, all fifteen of them")
              == "all fifteen of them"
          and M._prose_number_claim("All fifteen files have moved, so the OR is "
                                    "empty") == "all fifteen ... have"
          and M._prose_number_claim("`KNOWN_LAYER_DEBT` stayed at seventeen and "
                                    "the map did not move")
              == "stayed at seventeen"
          and M._prose_number_claim("and the ten cases in `tests/` that read it")
              == "ten cases")
    # SECOND DIRECTION, and the only case in this family that fails if the numeral
    # table GROWS. It looks vacuous - none of these lines is a finding before the
    # word spelling was read either - and it is the whole reason the table stops
    # where it does. Every line is real prose from this tree, and not one of them
    # is a count: a rate, a uniqueness claim whose sentence dies if the word goes,
    # an anaphor pointing at an enumeration the reader can see in the same breath,
    # and an auxiliary that belongs to the NEXT sentence. Admitting the small words
    # - the obvious "make it see more" mutation - turns every one of them into a
    # finding, and the repair reached for next would be loosening a shape, which is
    # how a pattern stops catching the thing it exists for.
    check("pn14 ...and a number-word in ordinary prose is NOT a claim, which is "
          "what the table's omissions buy. These are measured lines from this "
          "tree, not invented ones, and admitting the words below `ten` makes "
          "every one of them a violation",
          M._prose_number_claim("a caller can still report one case per asset")
              is None
          and M._prose_number_claim("It is the ONE case that brings the section")
              is None
          and M._prose_number_claim("and all three are honest about what a "
                                    "violation does") is None
          and M._prose_number_claim("belongs below all four of them, not beside "
                                    "one") is None
          and M._prose_number_claim("read 'fixed'. Pinned below by two cases.")
              is None
          and M._prose_number_claim("because `diagnose()` calls all six. They "
                                    "are modules now, cut where the") is None)
    check("pn15 a tens word and its tail are ONE numeral, because the hyphen is "
          "punctuation the tokenizer has already dropped - without that a "
          "written-out compound reads as a number followed by an unrelated word "
          "and slips every shape. The tail words are not numerals on their own, "
          "which is what keeps pn14 true, and a tens word with no tail keeps its "
          "own shape, which is what fails if the span over-consumes",
          M._prose_number_claim("forty-four cases assert the join") == "forty-four cases"
          and M._prose_number_claim("its twenty-one cases live in `tests/x.py`")
              == "its twenty-one cases"
          and M._prose_number_claim("twenty cases live in the suite")
              == "twenty cases live in"
          and M._prose_number_claim("four cases assert the join") is None
          and M._prose_number_claim("carrying twenty-one upward runtime edges")
              is None)
    check("pn16 the word spelling inherits BOTH escape hatches, or the extension "
          "would make the decision record unwritable and forbid its own remedy - "
          "the two things every family here is pinned against",
          M._prose_number_claim("the suite was eleven cases before the split")
              is None
          and M._prose_number_claim("it stood at seventy cases that day") is None
          and M._prose_number_claim("its thirteen cases live in x - re-derive "
                                    "with `python3 tests/test_x.py --selftest`")
              is None
          and M._prose_number_claim("its cases live in `tests/test_x.py`") is None)
    _pn_isdigit = [ln for ln in open(M.__file__, encoding="utf-8").read().split("\n")
                   if "isdigit" in ln]
    check("pn17 every shape reads its number through the ONE span reader - a "
          "family added later that asked a token whether it is a digit itself "
          "would see digits and miss words, which is F59 wearing a new shape. "
          "COUNTED over the source rather than asserted present, because the "
          "defect is a second reader existing at all. TWO occurrences, not one, "
          "and the pair is spelled out rather than tallied: one asks whether a "
          "TOKEN is a numeral, the other whether a CHARACTER is a digit, which "
          "is the tokenizer's separator rule and runs before any shape sees "
          "anything. A third would be the defect this counts: %r" % (_pn_isdigit,),
          sorted(ln.strip() for ln in _pn_isdigit)
              == ["if tok.isdigit():", "return ch.isdigit()"]
          and M._numeral_span(["ten"], 0) == ("ten", 1)
          and M._numeral_span(["17"], 0) == ("17", 1)
          and M._numeral_span(["four"], 0) is None)

    # --- pn18-pn23: WHERE the scan looks, which is C4's location axis ---------
    # The set used to be a hand-written pair and the claims had moved to what it
    # left out. Each directory below held a real one: a suite size in a `tests/`
    # docstring, a file count in the prover, a part count per assembled surface.
    _pn_reach = dict(
        (_d, len([r for r in _pn_scan["paths"] if r.startswith(_d)]))
        for _d in ("tools/", "plugins/audit/tests/", "plugins/audit/hooks/",
                   "plugins/audit/scripts/"))
    check("pn18 the scanned set is DERIVED from the tree, so it reaches the "
          "directories no hand-written list held - `tools/`, which holds the "
          "sweep runner and the mutation table, and `tests/`, which is where the "
          "suite sizes are written down: %r" % (_pn_reach,),
          _pn_scan["problem"] is None and all(_pn_reach.values()))
    # THE PREMISE OF EACH ROW, CHECKED, not just its presence. A row for a path
    # nothing holds any more is a sentence about a state that has passed, and it
    # stays green forever under a presence check alone - gate-parity's
    # stale-exemption half is the same reading. The generated report is the one
    # row whose file is legitimately absent from a fresh checkout, and it is
    # absent for a reason this can verify: `.gitignore` names it.
    _pn_ign = [_l.strip() for _l in
               io.open(os.path.join(M.REPO_ROOT, ".gitignore"),
                       encoding="utf-8").read().splitlines()]
    _pn_rows = M.PROSE_SCAN_EXEMPT
    _pn_bad = [_p for _p, _w in _pn_rows if not _w.strip()]
    _pn_dead = [_p for _p, _w in _pn_rows
                if not os.path.exists(
                    os.path.join(M.REPO_ROOT, _p.replace("/", os.sep)))
                and _p not in _pn_ign]
    check("pn19 every exemption carries a reason and describes a file that is "
          "really there - or one `.gitignore` names, which is how a generated "
          "document earns a row. The matcher is asked about that row's path "
          "directly, because it is the one row whose effect this tree never "
          "shows: the file is absent until somebody renders a report, and a row "
          "that matched nothing would look identical from here: %r"
          % (_pn_bad + _pn_dead,),
          not _pn_bad and not _pn_dead
          and len(_pn_rows) == len(set(_p for _p, _w in _pn_rows))
          and M.prose_scan_exemption("docs/audit/audit-report.md") is not None
          and M.prose_scan_exemption("docs/design/anything.md") is not None
          and M.prose_scan_exemption("plugins/audit/README.md") is None)
    _pn_tmp = tempfile.mkdtemp(prefix="pn-scan-")
    try:
        def _pn_write(rel, text):
            _full = os.path.join(_pn_tmp, rel.replace("/", os.sep))
            _dir = os.path.dirname(_full)
            if _dir and not os.path.isdir(_dir):
                os.makedirs(_dir)
            with io.open(_full, "w", encoding="utf-8") as _fh:
                _fh.write(text)
        _pn_write(".gitignore", "# fixture\nnotkept/\n")
        # Every line here is honest prose of a kind this tree really writes: a
        # recollection, a claim carrying its own basis, a noun with no count, and
        # a tally. None of them is a finding.
        _pn_write("clean.py",
                  '"""It stood at 70 cases that day, and the cases live in\n'
                  "`tests/`. Re-derive with `python3 x.py --selftest`.\n"
                  'ALL PASS: 7/7 cases passed."""\n')
        _pn_write("notes.md", "# Notes\n\nThe parts are joined in the order the\n"
                              "module lists them.\n")
        # The pruned half: a REAL claim, in a directory `.gitignore` names. If it
        # were reported, the finding count would depend on which agent worktrees
        # happened to be lying around rather than on anything in the commit.
        _pn_write("notkept/rot.py", '"""its 12 cases live in `tests/x.py`."""\n')
        _pn_honest = M.prose_number_claims(_pn_tmp)
        _pn_honest_set = M.prose_scan_set((".py",), _pn_tmp)
        # SECOND DIRECTION, and the only case here that fails if the widened scan
        # fires unconditionally: a tree whose prose is all correct reports
        # nothing WHILE HAVING READ IT. It looks vacuous, which is why the count
        # is in the message - "clean" and "read nothing" print the same otherwise.
        check("pn20 a tree whose claims are all honest reports nothing, over %d "
              "file(s) really read - this is the case that goes red if the scan "
              "ever fires unconditionally, and the one that goes red if the "
              "`.gitignore` pruning stops working: %r"
              % (len(_pn_honest_set["paths"]), _pn_honest),
              _pn_honest == [] and _pn_honest_set["paths"] == ["clean.py"])
        # ...and the same fixture WITH a claim, so pn20 is not a scan that cannot
        # fire. One line changed, one finding, naming the file and the line.
        _pn_write("clean.py", '"""its 12 cases live in `tests/x.py`."""\n')
        _pn_dirty = M.prose_number_claims(_pn_tmp)
        check("pn21 ...and the same tree with ONE claim added reports exactly it, "
              "by path and line - which is what tells pn20 apart from a walk "
              "that reads nothing: %r" % (_pn_dirty,),
              _pn_dirty == [("clean.py", 1, "its 12 cases")])
        os.remove(os.path.join(_pn_tmp, ".gitignore"))
        _pn_blind = M.prose_number_claims(_pn_tmp)
        check("pn22 a tree whose `.gitignore` cannot be read reports THAT and "
              "stops - the derivation is what prunes the agent worktrees, so "
              "falling back to 'nothing is ignored' would be a wrong answer "
              "wearing the shape of a right one, and returning [] would be "
              "'could not look' printed as 'clean': %r" % (_pn_blind,),
              len(_pn_blind) == 1 and _pn_blind[0][0] == ".gitignore"
              and "unreadable" in _pn_blind[0][2])
    finally:
        shutil.rmtree(_pn_tmp, ignore_errors=True)
    check("pn23 a numeral with an interior separator is a TALLY or a "
          "MEASUREMENT, not a count of things - the narrowing the widened scan "
          "needed, because the contract every suite prints appears outside "
          "`scripts/` as a fixture, a regex and an asserted literal. The bare "
          "count on the same noun still fires, which is what fails if the rule "
          "is ever widened from 'inside a number' to 'anywhere on the line'",
          M._prose_number_claim("ALL PASS: 7/7 cases passed") is None
          and M._prose_number_claim("suppresses even the <$0.01 case") is None
          and M._prose_number_claim("so the 4/1000 case goes red") is None
          and M._prose_number_claim("7 cases live in the suite")
              == "7 cases live in"
          and M._prose_number_claim("its 124 cases live in `tests/x.py`")
              == "its 124 cases"
          # THE TWO DIRECTIONS A NARROWING CAN BE WRONG IN, and neither is the
          # one above. Widened to the LINE, a real claim on a line that also
          # carries a tally would stop being read - and lines like that are
          # ordinary here. Widened to the TOKEN, a separator next to a letter
          # would be kept and every path in the tree would become one word.
          and M._prose_number_claim("7 cases live in it, in 1/2 the time")
              == "7 cases live in"
          and M._words("tests/x.py has 7 cases") == ["tests", "x", "py",
                                                     "has", "7", "cases"]
          # A thousands comma is NOT one of the separators: a grouped number is
          # still a count, so it stays dropped and the second numeral keeps its
          # noun. Asserted on the tokens, because the claim above it is reported
          # either way and so cannot tell the two versions apart.
          and M._prose_number_claim("1,254 lines, 148 cases, and 53 of them")
              == "148 cases"
          and M._words("1,254 lines") == ["1", "254", "lines"]
          and M._words("7/7 and 0.01") == ["7/7", "and", "0.01"])

    # --- pn24-pn28: the SENTENCE a number sits in, and two families refused ---
    # F76. The tense escape read the physical line, and a line is neither the unit
    # a tense belongs to nor the unit prose arrives in. The first line below is the
    # real one it was found on: a stale count sat unread behind a past marker two
    # clauses earlier, about something else entirely.
    check("pn24 the tense escape reads the SENTENCE the numeral sits in, not the "
          "physical line - a marker in an earlier sentence on the same line used "
          "to excuse a live count (F76's false negative, on the line it was found "
          "on). The second half is what fails if the scope narrows past a "
          "sentence to a clause: a marker inside the number's OWN sentence still "
          "excuses it, which is what keeps the decision record writable",
          M._prose_number_claim("THIS SUITE ALREADY HAD ITS OWN `check`. 102 of "
                                "the 131 cases go") == "131 cases"
          and M._prose_number_claim("the split was measured. 131 cases go "
                                    "through the wrapper") == "131 cases"
          and M._prose_number_claim("it had 131 cases then") is None)
    check("pn25 ...and the sentence is JOINED across the wrap, one line each way "
          "- the window `_carries_basis()` already reads, for the same reason: "
          "prose wraps, so a marker and its number land on different lines. Both "
          "directions of the join are here, and so is the half that fails if the "
          "join stops asking where a sentence ENDS - a marker in a sentence that "
          "finished before the wrap must not reach across it",
          M._prose_number_claim("146 cases stayed green afterwards", "",
                                "nothing pinned it, so the count was replaced by "
                                "a constant and all") is None
          and M._prose_number_claim("146 cases stayed green afterwards", "",
                                    "nothing pinned it, so the count was "
                                    "replaced by a constant.") == "146 cases"
          and M._prose_number_claim("the suite keeps all 146 cases",
                                    "before the split") is None
          and M._prose_number_claim("the suite keeps all 146 cases.",
                                    "It was different before.") == "146 cases"
          # A markdown sentence ends after its emphasis, not before it. Without
          # that the bolded line below would read as unfinished and hand its past
          # tense down to the next line, which is a document-shaped hole: `.md` is
          # half of what these shapes now read.
          and M._prose_number_claim("146 cases go through the wrapper", "",
                                    "**it was measured then.**") == "146 cases"
          # Called with no neighbours at all - one string, read as one whole
          # sentence. Every case above this section hands over exactly that.
          and M._prose_number_claim("the suite keeps all 146 cases") == "146 cases")
    # SECOND DIRECTION, and it is the only case here that fails when the boundary
    # rule gets GREEDY. It looks vacuous - both lines are ordinary recollection
    # and neither was a finding before F76 either - and it is the whole reason the
    # rule asks what follows a stop. Each half names its own mutation: read every
    # stop as a boundary and a dotted filename cuts the sentence in two, leaving
    # the tense behind in the first half; read a run of stops as boundaries and an
    # elided tag pair cuts one sentence into four, which is how a docstring's own
    # history was reported as a claim while this was being written.
    check("pn26 a stop INSIDE a name, and a run of stops standing for elided "
          "markup, are not sentence ends - a fragmenting boundary rule throws "
          "away the tense the sentence opened with and reports recollection as a "
          "claim. The third line is the same shape with the marker removed, so "
          "this fails if the joining stops firing at all rather than reading as "
          "two silent lines",
          M._prose_number_claim("it was rewritten in `x.py` and has 7 cases")
              is None
          and M._prose_number_claim("used to hold `<style>...</style>` and 7 "
                                    "cases") is None
          and M._prose_number_claim("it holds `x.py` and 7 cases") == "7 cases")
    # F70 AND F65: two families MEASURED AND REFUSED, recorded as cases because a
    # docstring saying "cannot see" is not checkable and the next author will
    # reach for exactly these shapes.
    #
    # A MEASUREMENT - a duration, a byte count, a line count - is invisible here,
    # and the units family that would read it was surveyed over this whole tree
    # before being declined. Every hit was read: on the widest unit vocabulary
    # honest prose outran real claims by better than two to one, and on the
    # narrowest defensible cut (size units, on a line naming code, the gate the
    # persistence family uses) it still outran them. The lines below are the
    # reason and they are real ones from this tree: a THRESHOLD, a configured
    # constant and a hypothetical are numbers that must stay, and they are the
    # shape a units family cannot tell from a claim.
    # F77. The bound matters as much as the rule: an underscore glues a token
    # only where WORD CHARACTERS flank it, so a trailing one still ends the token
    # and the numeral after it keeps whatever noun follows. The second half is the
    # direction that fails if this is ever applied to any underscore at all.
    _f77_line = '    x = y[1] == case_id(z)'
    check("pn29 an identifier is ONE word, so a numeric index in front of a name "
          "whose first piece is a case noun is not a claim - and the rule stops "
          "at a word boundary, so a trailing separator still leaves the numeral "
          "its noun: %r / %r"
          % (M._words(_f77_line), M._words("count_ 5 cases")),
          M._prose_number_claim(_f77_line) is None
          and "case_id" in M._words(_f77_line)
          and M._words("count_ 5 cases") == ["count", "5", "cases"]
          and M._prose_number_claim("count_ 5 cases") is not None
          # ...and a LEADING separator is dropped too, so an underscore-prefixed
          # noun still keeps the numeral in front of it. This is the direction
          # that fails if the rule stops asking for left context.
          and M._words("its 1 _cases") == ["its", "1", "cases"]
          and M._prose_number_claim("its 1 _cases") is not None)
    check("pn27 a MEASUREMENT is not read - the units family was surveyed over "
          "this tree and refused, because a size or a duration here is usually a "
          "threshold, a budget or a hypothetical, and those numbers are the point "
          "of their sentences. This is the case that goes red if one is adopted "
          "without measuring again",
          M._prose_number_claim("Files of 400+ lines need at least two markers")
              is None
          and M._prose_number_claim("Events are the newest ~20 lines of")
              is None
          and M._prose_number_claim("a banner would let a 2,000-line module pass")
              is None
          # WHAT THE REFUSAL GIVES UP, in the same case so it cannot be read as
          # an accident: a real measurement of this tree is not read either.
          and M._prose_number_claim("front-matter reads, 159 ms cold and 31 ms "
                                    "warm - and it runs on a POLL") is None
          and M._prose_number_claim("the 46,220-byte `audit-plan.schema.json`")
              is None)
    check("pn28 ...and a BEFORE/AFTER sentence is not read either, for a "
          "different reason: its first number is history and legal for ever, its "
          "second is a live claim, and the tense that makes the first one legal "
          "sits in the same sentence as the second. The `is N` shape that would "
          "reach it was surveyed too and refused - real claims were a quarter of "
          "its hits, the rest arithmetic, format shapes and external facts. The "
          "repair is the prose, and the repaired form reads clean",
          M._prose_number_claim("It was 1,456 lines and is 242, because the "
                                "checks shared one file") is None
          and M._prose_number_claim("`E_USAGE` is 2 and the reason is arithmetic")
              is None
          and M._prose_number_claim("It was one file and is six, because the "
                                    "checks shared it for one reason") is None)

    # --- us: which files a surface's pictures are OF (F85) --------------------
    # `_refs.screenshot_capture_drift()` and `tools/capture-screenshots.mjs` both
    # need this answer and neither may hold its own copy of it, so every case here
    # is about the ONE walk they share. The rule's own cases live beside sc1-sc10
    # in test__refs.py; these are about the walk underneath it.
    _us_live = M.ui_surface_digests()
    check("us1 the real tree files every `ui/` part under a surface, and both "
          "surfaces come back with a digest - the case that goes red the day a "
          "directory is added under `ui/` whose name answers nobody: %r"
          % ((_us_live["error"], _us_live["unassigned"]),),
          _us_live["error"] is None and _us_live["unassigned"] == []
          and sorted(_us_live["digests"]) == sorted(M.UI_SURFACES)
          and len(set(_us_live["digests"].values())) == len(M.UI_SURFACES))
    _us_src = M.ui_surface_sources()
    check("us2 ...over a real set of parts rather than an empty one, and the two "
          "surfaces are not the same set - a walk that reached nothing would "
          "return the same clean shape us1 accepts: %r"
          % ({"panel": len(_us_src["sources"]["panel"]),
              "report": len(_us_src["sources"]["report"])},),
          min(len(v) for v in _us_src["sources"].values()) > 5
          and set(_us_src["sources"]["panel"]) != set(_us_src["sources"]["report"])
          and "panel.html" in _us_src["sources"]["panel"])
    check("us3 the FILING CONVENTION is what answers, so a part added under an "
          "existing directory is covered without anyone declaring it - and an "
          "unfamiliar directory returns no surface rather than a guess",
          M.ui_surfaces_of("panel/core.js") == ("panel",)
          and M.ui_surfaces_of("panel-css/app-shell.css") == ("panel",)
          and M.ui_surfaces_of("panel.html") == ("panel",)
          and M.ui_surfaces_of("report/filters.js") == ("report",)
          and M.ui_surfaces_of("report-css/shell.css") == ("report",)
          and M.ui_surfaces_of("shared/dates.js") == M.UI_SURFACES
          and M.ui_surfaces_of("widgets/thing.js") == ())

    tmp = tempfile.mkdtemp(prefix="audit-uisrc-")
    try:
        def _us_write(rel, text):
            path = os.path.join(tmp, "scripts", *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)

        def _us_digests():
            return M.ui_surface_digests(os.path.join(tmp, "scripts"))

        _us_scripts = os.path.join(tmp, "scripts")
        _us_write("_ui_theme.py", "TOKEN_CSS = ':root{--bg:#fff}'\n")
        _us_write("ui/panel.html", "<!doctype html>\n")
        _us_write("ui/panel/core.js", "const el = 1;\n")
        _us_write("ui/panel-css/app-shell.css", ".shell{}\n")
        _us_write("ui/report/filters.js", "const chips = 1;\n")
        _us_write("ui/report-css/shell.css", ".rshell{}\n")
        _us_write("ui/shared/dates.js", "const DAY = 1;\n")
        _us_base = _us_digests()
        check("us4 a fixture tree digests both surfaces, so every case below "
              "fails for the reason it names: %r" % (_us_base["error"],),
              _us_base["error"] is None and _us_base["unassigned"] == []
              and sorted(_us_base["digests"]) == sorted(M.UI_SURFACES))

        # THE CASE THAT MAKES THIS A RULE RATHER THAN A NUISANCE. A digest that
        # fires on everything asks for every picture back on every commit and gets
        # switched off; both directions are asserted in one case so neither can be
        # read as an accident of which file was picked.
        _us_write("ui/report/filters.js", "const chips = 2;\n")
        _us_rep = _us_digests()["digests"]
        _us_write("ui/report/filters.js", "const chips = 1;\n")
        _us_write("ui/panel/core.js", "const el = 2;\n")
        _us_pan = _us_digests()["digests"]
        _us_write("ui/panel/core.js", "const el = 1;\n")
        check("us5 a report source moves the REPORT digest and leaves the panel's "
              "alone, and a panel source the other way - the separation the whole "
              "rule rests on: %r"
              % ({"report-edit": [s for s in M.UI_SURFACES
                                  if _us_rep[s] != _us_base["digests"][s]],
                  "panel-edit": [s for s in M.UI_SURFACES
                                 if _us_pan[s] != _us_base["digests"][s]]},),
              _us_rep["report"] != _us_base["digests"]["report"]
              and _us_rep["panel"] == _us_base["digests"]["panel"]
              and _us_pan["panel"] != _us_base["digests"]["panel"]
              and _us_pan["report"] == _us_base["digests"]["report"])

        _us_write("ui/shared/dates.js", "const DAY = 2;\n")
        _us_shared = _us_digests()["digests"]
        _us_write("ui/shared/dates.js", "const DAY = 1;\n")
        check("us6 a `shared/` part moves BOTH, because both assemblies list it - "
              "the one place where firing on everything is the right answer: %r"
              % (_us_shared,),
              _us_shared["panel"] != _us_base["digests"]["panel"]
              and _us_shared["report"] != _us_base["digests"]["report"])

        # The edge that had to be argued rather than assumed: the token layer is a
        # `.py`, it is not under `ui/`, and it is in the digest because `TOKEN_CSS`
        # heads one stylesheet and is substituted into the other. A colour moving
        # there moves every picture, so a rule blind to it would sleep through the
        # change most likely to matter.
        _us_write("_ui_theme.py", "TOKEN_CSS = ':root{--bg:#000}'\n")
        _us_token = _us_digests()["digests"]
        _us_write("_ui_theme.py", "TOKEN_CSS = ':root{--bg:#fff}'\n")
        check("us7 the TOKEN LAYER is in both digests though it lives outside "
              "`ui/` - a palette edit is the change most likely to move every "
              "pixel and the one a walk over `ui/` alone cannot see: %r"
              % (_us_token,),
              _us_token["panel"] != _us_base["digests"]["panel"]
              and _us_token["report"] != _us_base["digests"]["report"])

        # The second direction, and it looks vacuous on purpose: it passes on a
        # digest that never fires. It is the only case that fails if the walk
        # starts reading something that is not a part - a README, a dotfile, the
        # mtime - and it is why us5's negative halves mean anything.
        _us_write("ui/report/README.md", "# what these parts are\n")
        _us_write("ui/panel/README.md", "# and these\n")
        _us_write("ui/.DS_Store_probe", "junk\n")
        _us_doc = _us_digests()
        check("us8 documentation and dotfiles are NOT parts, so adding them moves "
              "no digest and asks for no re-capture - the guard against a walk "
              "that fires on everything, and the suffix set has one home: %r"
              % (_us_doc["digests"] == _us_base["digests"],),
              _us_doc["digests"] == _us_base["digests"]
              and _us_doc["unassigned"] == []
              and _ui_theme._DOC_SUFFIXES is M.UI_DOC_EXT)

        _us_write("ui/widgets/thing.js", "const w = 1;\n")
        _us_odd = _us_digests()
        os.remove(os.path.join(_us_scripts, "ui", "widgets", "thing.js"))
        check("us9 a part under a directory no surface claims is REPORTED, never "
              "dropped - a part covered by no digest is a part whose change could "
              "never turn a picture red, which is the silence this whole rule is "
              "against: %r" % (_us_odd["unassigned"],),
              _us_odd["unassigned"] == ["widgets/thing.js"]
              and _us_odd["digests"] == _us_base["digests"])

        # A missing member must not be answered with a digest over the remainder:
        # that value is stable, comparable, and about a different tree. REMOVED
        # rather than chmod-ed, because `chmod 000` does not stop a read on the
        # windows runner and the case would then be untested on exactly one of the
        # two platforms CI runs.
        os.remove(os.path.join(_us_scripts, "_ui_theme.py"))
        _us_unreadable = _us_digests()
        _us_write("_ui_theme.py", "TOKEN_CSS = ':root{--bg:#fff}'\n")
        check("us10 a member that cannot be read empties the digests and names "
              "the file - a digest over a PARTIAL set is a wrong answer wearing "
              "the shape of a right one: %r" % (_us_unreadable,),
              _us_unreadable["digests"] == {}
              and _us_unreadable["error"] is not None
              and "_ui_theme.py" in _us_unreadable["error"])

        shutil.rmtree(os.path.join(_us_scripts, "ui", "report"))
        shutil.rmtree(os.path.join(_us_scripts, "ui", "report-css"))
        _us_gone = _us_digests()
        check("us11 a surface left with no part of its own is an ERROR, not a "
              "digest over the token layer alone - that value would be stable and "
              "comparable and would clear every picture of a surface that is no "
              "longer there: %r" % (_us_gone,),
              _us_gone["digests"] == {} and _us_gone["error"] is not None
              and "report" in _us_gone["error"])

        _us_empty = M.ui_surface_digests(os.path.join(tmp, "nowhere"))
        # The message is asserted, not merely the presence of one: an ignored
        # `onerror` leaves an empty walk, which the no-parts branch below would
        # then report in different words - a right-looking error about the wrong
        # thing, and the reader sent to look for a deleted part.
        check("us12 an absent `ui/` is reported AS UNWALKABLE, because os.walk "
              "reports a missing tree by yielding nothing and raising nothing - "
              "the exact shape a renamed directory takes: %r" % (_us_empty,),
              _us_empty["digests"] == {} and _us_empty["error"] is not None
              and "cannot be walked" in _us_empty["error"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="audit-uiframe-")
    try:
        def _us2_write(rel, text):
            path = os.path.join(tmp, "scripts", *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)

        # THE FRAMING CASE, and the fixture is the whole of it. Each member enters
        # the hash as `name length` and then its bytes, so a byte moved ACROSS a
        # part boundary is visible even though the concatenation is unchanged -
        # which is what a badly resolved merge between two adjacent parts looks
        # like. The contents are deliberately not real part shapes: two files whose
        # bytes merely SWAP would separate no implementation, because concatenating
        # them the other way round already produces a different stream. This one
        # produces the same stream and is the only shape that fails when the
        # framing is dropped.
        _us2_write("_ui_theme.py", "T = 1\n")
        _us2_write("ui/panel.html", "<!doctype html>\n")
        _us2_write("ui/panel-css/a.css", ".a{}\n")
        _us2_write("ui/panel/one.js", "AB")
        _us2_write("ui/panel/two.js", "C\n")
        _us2_write("ui/report/r.js", "R\n")
        _us2_write("ui/report-css/r.css", ".r{}\n")
        _before = M.ui_surface_digests(os.path.join(tmp, "scripts"))["digests"]
        _us2_write("ui/panel/one.js", "A")
        _us2_write("ui/panel/two.js", "BC\n")
        _after = M.ui_surface_digests(os.path.join(tmp, "scripts"))["digests"]
        check("us13 a byte moved ACROSS a part boundary changes the panel digest "
              "though the concatenated bytes are identical, so the name and the "
              "length of each member are inside the hash: %r"
              % ((_before["panel"][:12], _after["panel"][:12]),),
              _before["panel"] != _after["panel"]
              and _before["report"] == _after["report"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__output.py --selftest\n")
    raise SystemExit(2)
