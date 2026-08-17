#!/usr/bin/env python3
"""
The cases for `scripts/_output.py`, moved out of it - the last of the forty-eight, and
the one that classifies the other forty-seven.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THE ONE EXPRESSION THAT COULD NOT MOVE LITERALLY, and it is the fixture that proves the
guard works. The `guarded.py` child written under `b1`/`c1` carries
`sys.path.insert(0, <dir>)` so that `from _output import safe_stdio` resolves in a fresh
interpreter. Moved literally, `<dir>` would be this file's directory - `tests/`, which
holds no `_output.py` - and the child would die on ImportError instead of surviving the
cp1252 stream. It reads `M._HERE`, the SUBJECT's own directory, which is the only value
that has ever been meant. (Loud rather than silent, as it happens: the child's stderr
would have named the ImportError. It is on this list because the case's whole claim is
about what the child could import.)

`M._HERE`, `M._TESTS_DIR` AND `M._REPO_ROOT` RATHER THAN THE `_harness` CONSTANTS. Same
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
                'print("tick \\u2713 done")\n' % M._HERE)

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
          % (sorted(n for n, _p in M.py_files(M._TESTS_DIR)),),
          M.entries_missing_guard() == sorted(M.entries_missing_guard((M._HERE,))
                                              + M.entries_missing_guard((M._TESTS_DIR,)))
          and M.py_files(M._TESTS_DIR) != [])

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
                                  "scripts/_areas.py",
                                  "scripts/_cli_fmt.py",
                                  "scripts/_deps.py",
                                  "scripts/_fmt.py",
                                  "scripts/_help.py",
                                  "scripts/_loader.py",
                                  "scripts/_manifest_io.py",
                                  "scripts/_output.py",
                                  "scripts/_panel_discovery.py",
                                  "scripts/_panel_page.py",
                                  "scripts/_panel_settings.py",
                                  "scripts/_panel_state.py",
                                  "scripts/_panel_ui.py",
                                  "scripts/_panel_write.py",
                                  "scripts/_policy.py",
                                  "scripts/_refs.py",
                                  "scripts/_report_html.py",
                                  "scripts/_report_md.py",
                                  "scripts/_report_page.py",
                                  "scripts/_report_ui.py",
                                  "scripts/_report_usage.py",
                                  "scripts/_ui_theme.py",
                                  "scripts/_usage_analytics.py",
                                  "scripts/_usage_core.py",
                                  "scripts/audit-doctor.py",
                                  "scripts/audit-journal.py",
                                  "scripts/audit-lock.py",
                                  "scripts/audit-status.py",
                                  "scripts/audit-task.py",
                                  "scripts/audit-usage.py",
                                  "scripts/gen-demo-manifest.py",
                                  "scripts/gen-demo-usage.py",
                                  "scripts/migrate-manifest.py",
                                  "scripts/panel-server.py",
                                  "scripts/render-report.py",
                                  "scripts/usage_ledger.py",
                                  "scripts/validate-config.py",
                                  "scripts/validate-manifest.py"])
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
                                     "plugins/audit/scripts/_areas.py",
                                     "plugins/audit/scripts/_cli_fmt.py",
                                     "plugins/audit/scripts/_deps.py",
                                     "plugins/audit/scripts/_fmt.py",
                                     "plugins/audit/scripts/_help.py",
                                     "plugins/audit/scripts/_loader.py",
                                     "plugins/audit/scripts/_manifest_io.py",
                                     "plugins/audit/scripts/_output.py",
                                     "plugins/audit/scripts/_panel_discovery.py",
                                     "plugins/audit/scripts/_panel_page.py",
                                     "plugins/audit/scripts/_panel_settings.py",
                                     "plugins/audit/scripts/_panel_state.py",
                                     "plugins/audit/scripts/_panel_ui.py",
                                     "plugins/audit/scripts/_panel_write.py",
                                     "plugins/audit/scripts/_policy.py",
                                     "plugins/audit/scripts/_refs.py",
                                     "plugins/audit/scripts/_report_html.py",
                                     "plugins/audit/scripts/_report_md.py",
                                     "plugins/audit/scripts/_report_page.py",
                                     "plugins/audit/scripts/_report_ui.py",
                                     "plugins/audit/scripts/_report_usage.py",
                                     "plugins/audit/scripts/_ui_theme.py",
                                     "plugins/audit/scripts/_usage_analytics.py",
                                     "plugins/audit/scripts/_usage_core.py",
                                     "plugins/audit/scripts/audit-doctor.py",
                                     "plugins/audit/scripts/audit-journal.py",
                                     "plugins/audit/scripts/audit-lock.py",
                                     "plugins/audit/scripts/audit-status.py",
                                     "plugins/audit/scripts/audit-task.py",
                                     "plugins/audit/scripts/audit-usage.py",
                                     "plugins/audit/scripts/gen-demo-manifest.py",
                                     "plugins/audit/scripts/gen-demo-usage.py",
                                     "plugins/audit/scripts/migrate-manifest.py",
                                     "plugins/audit/scripts/panel-server.py",
                                     "plugins/audit/scripts/render-report.py",
                                     "plugins/audit/scripts/usage_ledger.py",
                                     "plugins/audit/scripts/validate-config.py",
                                     "plugins/audit/scripts/validate-manifest.py"]
          and all(os.path.isfile(os.path.join(M._REPO_ROOT, p.replace("/", os.sep)))
                  for p in M.covered_repo_paths()))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__output.py --selftest\n")
    raise SystemExit(2)
