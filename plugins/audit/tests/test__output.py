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
        with open(os.path.join(style, "clean.py"), "w", encoding="utf-8") as fh:
            fh.write('def f(n):\n    return n + 1\n')
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
        check("g9 every violation names a line number, so a failure can point at "
              "its offender rather than just its file",
              all(isinstance(line, int) and line > 0 for _, line, _ in hits
                  if _ != "broken.py"))
    finally:
        shutil.rmtree(style, ignore_errors=True)

    # The gate this half of the module exists for: scripts/ and hooks/, as they stand,
    # carry none of the four bans.
    real_style = M.house_style_violations()
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
                                  "scripts/governance/_journal_io.py",
                                  "scripts/governance/_locks.py",
                                  "scripts/governance/_policy.py",
                                  "scripts/governance/audit-journal.py",
                                  "scripts/governance/audit-lock.py",
                                  "scripts/manifest/_areas.py",
                                  "scripts/manifest/_manifest_ado.py",
                                  "scripts/manifest/_manifest_crossrefs.py",
                                  "scripts/manifest/_manifest_io.py",
                                  "scripts/manifest/_manifest_phases.py",
                                  "scripts/manifest/_manifest_rules.py",
                                  "scripts/manifest/_manifest_typos.py",
                                  "scripts/manifest/_manifest_vocab.py",
                                  "scripts/manifest/audit-task.py",
                                  "scripts/manifest/migrate-manifest.py",
                                  "scripts/manifest/validate-manifest.py",
                                  "scripts/panel/_panel_discovery.py",
                                  "scripts/panel/_panel_page.py",
                                  "scripts/panel/_panel_settings.py",
                                  "scripts/panel/_panel_state.py",
                                  "scripts/panel/_panel_ui.py",
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
                                  "scripts/usage/_usage_analytics.py",
                                  "scripts/usage/_usage_core.py",
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
                                     "plugins/audit/scripts/governance/_journal_io.py",
                                     "plugins/audit/scripts/governance/_locks.py",
                                     "plugins/audit/scripts/governance/_policy.py",
                                     "plugins/audit/scripts/governance/audit-journal.py",
                                     "plugins/audit/scripts/governance/audit-lock.py",
                                     "plugins/audit/scripts/manifest/_areas.py",
                                     "plugins/audit/scripts/manifest/_manifest_ado.py",
                                     "plugins/audit/scripts/manifest/_manifest_crossrefs.py",
                                     "plugins/audit/scripts/manifest/_manifest_io.py",
                                     "plugins/audit/scripts/manifest/_manifest_phases.py",
                                     "plugins/audit/scripts/manifest/_manifest_rules.py",
                                     "plugins/audit/scripts/manifest/_manifest_typos.py",
                                     "plugins/audit/scripts/manifest/_manifest_vocab.py",
                                     "plugins/audit/scripts/manifest/audit-task.py",
                                     "plugins/audit/scripts/manifest/migrate-manifest.py",
                                     "plugins/audit/scripts/manifest/validate-manifest.py",
                                     "plugins/audit/scripts/panel/_panel_discovery.py",
                                     "plugins/audit/scripts/panel/_panel_page.py",
                                     "plugins/audit/scripts/panel/_panel_settings.py",
                                     "plugins/audit/scripts/panel/_panel_state.py",
                                     "plugins/audit/scripts/panel/_panel_ui.py",
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
                                     "plugins/audit/scripts/usage/_usage_analytics.py",
                                     "plugins/audit/scripts/usage/_usage_core.py",
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
              _installed == [M.SCRIPTS_DIR,
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__output.py --selftest\n")
    raise SystemExit(2)
