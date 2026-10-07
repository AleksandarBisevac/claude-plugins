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


# What jest 30.5.2 printed (node v22, `jest --ci`, 2026-10-07) for one failing
# `node:assert` call of each shape, an `expect` and a body that threw - each
# bullet's first line verbatim, the code frames dropped. jest formats a
# `node:assert` failure the way it formats a matcher: a hint naming the call,
# never an `AssertionError` line.
_JEST_NODE_ASSERT = (
    "FAIL ./a.test.js\n"
    "  ● m › eq\n\n    assert.equal(received, expected)\n\n"
    "    Expected value to be equal to:\n      2\n    Received:\n      1\n\n"
    "  ● m › ok\n\n    assert(received)\n\n"
    "  ● m › deep\n\n    assert.deepStrictEqual(received, expected)\n\n"
    "  ● m › strict\n\n    assert.strictEqual(received, expected)\n\n"
    "  ● m › fail\n\n    assert.fail(received, expected)\n\n"
    "  ● m › throws\n\n    assert.throws(function)\n\n"
    "  ● m › exp\n\n    expect(received).toBe(expected) // Object.is equality\n\n"
    "  ● m › boom\n\n    TypeError: boom\n\n"
    "Test Suites: 1 failed, 1 total\n"
    "Tests:       8 failed, 8 total\n"
    "Snapshots:   0 total\n")


def _node_assert_cases(check):
    flags = dict((c.get("id"), c.get("assertion"))
                 for c in M.failing_cases(_JEST_NODE_ASSERT))
    calls = ("eq", "ok", "deep", "strict", "fail", "throws")
    check("ru11 every `node:assert` hint jest prints - `assert(received)` and "
          "`assert.<call>(...)` - sets the assertion flag, as the matcher hint "
          "does, and the tally counts each: %r %r"
          % (flags, M.read_tally(_JEST_NODE_ASSERT)),
          all(flags.get(c) is True for c in calls) and flags.get("exp") is True
          and (M.read_tally(_JEST_NODE_ASSERT) or {}).get("assertions") == 7)
    # The over-fire direction: a reader that took any bullet as an assertion
    # passes ru11 and fails here.
    check("ru12 THE ALLOW CASE for ru11: the body that threw (`TypeError: "
          "boom`) is still not an assertion, and neither is a line that merely "
          "opens with the word: %r %r"
          % (flags.get("boom"), M._JEST_ASSERTION.match("assertion failed")),
          flags.get("boom") is False
          and M._JEST_ASSERTION.match("assertion failed") is None
          and M._JEST_ASSERTION.match("asserted(x)") is None)


# What jest 30.5.2 printed under FORCE_COLOR=1 (2026-10-07) for one failing
# `expect`, and for a file whose one test passed, blank lines and code frames
# dropped - every escape verbatim.
_JEST_COLOUR_RED = (
    "\x1b[0m\x1b[7m\x1b[1m\x1b[31m FAIL \x1b[39m\x1b[22m\x1b[27m\x1b[0m "
    "\x1b[2m./\x1b[22m\x1b[1md.test.js\x1b[22m\n"
    "\x1b[1m\x1b[31m  \x1b[1m● \x1b[22m\x1b[1mm › adds\x1b[39m\x1b[22m\n\n"
    "    \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe"
    "\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality"
    "\x1b[22m\n\n"
    "\x1b[1mTest Suites: \x1b[22m\x1b[1m\x1b[31m1 failed\x1b[39m\x1b[22m, 1 total\n"
    "\x1b[1mTests:       \x1b[22m\x1b[1m\x1b[31m1 failed\x1b[39m\x1b[22m, 1 total\n"
    "\x1b[1mSnapshots:   \x1b[22m0 total\n")
_JEST_COLOUR_GREEN = (
    "\x1b[1mTest Suites: \x1b[22m\x1b[1m\x1b[32m1 passed\x1b[39m\x1b[22m, 1 total\n"
    "\x1b[1mTests:       \x1b[22m\x1b[1m\x1b[32m1 passed\x1b[39m\x1b[22m, 1 total\n"
    "\x1b[1mSnapshots:   \x1b[22m0 total\n")


def _colour_cases(check):
    red, green = M.read_tally(_JEST_COLOUR_RED), M.read_tally(_JEST_COLOUR_GREEN)
    cases = [(c.get("suite"), c.get("label"), c.get("assertion"))
             for c in M.failing_cases(_JEST_COLOUR_RED)]
    check("ru13 jest's coloured summary line is read: a failing `expect` is a "
          "jest tally counting one case and one assertion, its case named under "
          "its suite, and a passing file's coloured line counts its case - "
          "neither reads as no tally: %r %r %r" % (red, green, cases),
          (red or {}).get("runner") == "jest" and red.get("collected") == 1
          and red.get("assertions") == 1
          and (green or {}).get("runner") == "jest"
          and green.get("collected") == 1 and green.get("failed") == 0
          and cases == [("./d.test.js", "m › adds", True)])
    plain = M.plain_text(_JEST_COLOUR_RED) if hasattr(M, "plain_text") else None
    check("ru14 THE ALLOW CASE for ru13: the same output without its escapes "
          "reads identically, and stripping leaves no escape and no other "
          "character behind: %r" % (plain,),
          plain is not None and "\x1b" not in plain
          and M.read_tally(plain) == red
          and M.failing_cases(plain) == M.failing_cases(_JEST_COLOUR_RED)
          and "Tests:       1 failed, 1 total" in plain
          and " FAIL  ./d.test.js" in plain)


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
    _node_assert_cases(check)
    _colour_cases(check)
    _layer_cases(check)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__runner_output.py --selftest\n")
    raise SystemExit(2)
