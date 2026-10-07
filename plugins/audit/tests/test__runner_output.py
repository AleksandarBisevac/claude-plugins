#!/usr/bin/env python3
"""
The cases for `_runner_output.py` - every reading of what a test runner printed.

`test_run_test_gate.py` drives these readers through the gate, which is where
they were first written and where most of their cases still live; what is
pinned here is what the move must not lose: both tables still hold every runner
the gate read, a runner in one table is in the other, and the module reaches
nothing above layer 1.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import ast
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _runner_output as M                         # noqa: E402

# The runners `run-test-gate.py`'s two tables held on the day they moved here,
# written out rather than read off either table: a reading of the table would
# pass whatever the table lost on the way.
GATE_RUNNERS_AT_MOVE = ("jest", "vitest", "mocha", "pytest", "playwright")


def _table_cases(check):
    summary = [name for name, _re, _words in M._SUMMARY_READERS]
    failure = sorted(M._FAILURE_READERS)
    check("ru1 the summary table holds every runner the gate read before the "
          "move, each once: %r" % (summary,),
          set(GATE_RUNNERS_AT_MOVE) <= set(summary)
          and len(summary) == len(set(summary)))
    check("ru2 ...and so does the failure table: %r" % (failure,),
          set(GATE_RUNNERS_AT_MOVE) <= set(failure))
    check("ru3 a runner in one table is in the other - a failure reader with no "
          "count names failures beside an unknowable count, and a count with no "
          "failure reader falls through to a tail: summary-only %r, "
          "failure-only %r"
          % (sorted(set(summary) - set(failure)),
             sorted(set(failure) - set(summary))),
          set(summary) == set(failure))


def _summary_cases(check):
    # One summary per runner, each with a skipped/pending entry the count must
    # leave out - a reader that summed every pair would answer one more.
    seen = [(name, M.summary_reader(text)[0], M.summary_count(text), want)
            for name, text, want in (
                ("jest", "Tests:  1 failed, 2 skipped, 3 passed, 6 total\n", 4),
                ("vitest", "      Tests  1 failed | 4 passed | 1 skipped (6)\n", 5),
                ("mocha", "  5 passing (23ms)\n  1 failing\n  2 pending\n", 6),
                ("pytest", "==== 1 failed, 2 passed, 1 skipped in 0.03s ====\n", 3),
                ("playwright", "  1 failed\n  1 flaky\n  2 skipped\n"
                               "  3 passed (590ms)\n", 5))]
    check("ru4 each runner's summary is recognised as that runner and counts "
          "only what executed: %r" % (seen,),
          all(got == name and count == want
              for name, got, count, want in seen))
    check("ru5 output no reader recognises is NOT KNOWABLE (None), never zero, "
          "while a runner's own `no tests` is zero: %r / %r"
          % (M.summary_reader("Done in 1.53s.\n"),
             M.summary_count("      Tests  no tests\n")),
          M.summary_reader("Done in 1.53s.\n") == (None, "", ())
          and M.summary_count("Done in 1.53s.\n") is None
          and M.summary_count("      Tests  no tests\n") == 0)


def _jest_cases(check):
    red = ("\x1b[1m\x1b[31m FAIL \x1b[39m\x1b[22m src/a.test.ts\n"
           "  ● totals › applies the discount\n\n"
           "    expect(received).toBe(expected)\n"
           "  ● Console\n\n"
           "    console.log noise\n"
           " FAIL  src/b.test.ts\n"
           "  ● Test suite failed to run\n\n"
           "    Cannot find module './gone' from 'b.test.ts'\n")
    found = M.jest_failures(red)
    check("ru6 jest_failures names each bullet under the suite its header "
          "names, colour stripped, a console dump left out, and a failed-to-run "
          "suite's reason read off the line under it: %r" % (found,),
          found == [("totals › applies the discount", "src/a.test.ts", None),
                    (M.JEST_EXEC_ERROR, "src/b.test.ts",
                     "Cannot find module './gone' from 'b.test.ts'")])
    vitest = (" × src/c.test.ts > adds 1ms\n"
              " FAIL  src/c.test.ts > adds\n"
              " FAIL  src/d.test.ts [ src/d.test.ts ]\n")
    check("ru7 vitest's FAIL line yields a FILE, and the cross in the file tree "
          "is not read as one: %r" % (M._VITEST_FAIL_LINE.findall(vitest),),
          M._VITEST_FAIL_LINE.findall(vitest) == ["src/c.test.ts",
                                                  "src/d.test.ts"])


# What vitest 4 prints for one `expect` failure: the file tree's cross, then
# under `Failed Tests` the `FAIL <file> > <suite> > <name>` line with chai's
# `AssertionError` on the line after it, then the summary.
_VITEST_ASSERT = (
    " ❯ tests/add.test.js (1 test | 1 failed) 4ms\n"
    "   × math > adds two numbers 3ms\n\n"
    "⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯\n\n"
    " FAIL  tests/add.test.js > math > adds two numbers\n"
    "AssertionError: expected -1 to be 3 // Object.is equality\n\n"
    "- Expected\n+ Received\n\n- 3\n+ -1\n\n"
    " ❯ tests/add.test.js:5:23\n\n"
    " Test Files  1 failed (1)\n"
    "      Tests  1 failed (1)\n"
    "   Start at  10:00:00\n"
    "   Duration  210ms\n")


def _vitest_cases(check):
    failing = getattr(M, "failing_cases", None)
    read = getattr(M, "read_tally", None)
    cases = ([(c.get("suite"), c.get("label"), c.get("assertion"))
              for c in failing(_VITEST_ASSERT)] if failing else None)
    check("ru9 a vitest `FAIL <file> > <suite> > <name>` line carrying an "
          "AssertionError reads as ONE failing case, its file and title chain "
          "kept and its assertion flag true - the file tree's cross is not a "
          "second one: %r" % (cases,),
          cases == [("tests/add.test.js", "math > adds two numbers", True)])
    none = read("      Tests  no tests\n") if read else None
    check("ru10 vitest's `Tests  no tests` reads as vitest having collected "
          "nothing and failed nothing, never as an unreadable run: %r" % (none,),
          (none or {}).get("runner") == "vitest"
          and (none or {}).get("collected") == 0
          and (none or {}).get("failed") == 0)


def _layer_cases(check):
    with open(M.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    siblings = sorted(set(
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name.startswith("_"))
        | set(node.module for node in ast.walk(tree)
              if isinstance(node, ast.ImportFrom) and node.module
              and node.module.startswith("_")))
    check("ru8 the module imports no sibling but `_output`, which is what keeps "
          "it at layer 1 where both entry points can reach it: %r" % (siblings,),
          siblings == ["_output"])


def _cases(check):
    _table_cases(check)
    _summary_cases(check)
    _jest_cases(check)
    _vitest_cases(check)
    _layer_cases(check)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__runner_output.py --selftest\n")
    raise SystemExit(2)
