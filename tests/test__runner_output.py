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
import inspect
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


# One summary per runner, each with a skipped/pending entry the count must
# leave out - a reader that summed every pair would answer one more.
_SUMMARIES = (
    ("jest", "Tests:  1 failed, 2 skipped, 3 passed, 6 total\n", 4),
    ("vitest", "      Tests  1 failed | 4 passed | 1 skipped (6)\n", 5),
    ("mocha", "  5 passing (23ms)\n  1 failing\n  2 pending\n", 6),
    ("pytest", "==== 1 failed, 2 passed, 1 skipped in 0.03s ====\n", 3),
    ("playwright", "  1 failed\n  1 flaky\n  2 skipped\n"
                   "  3 passed (590ms)\n", 5))


def _summary_cases(check):
    seen = [(name, M.summary_reader(text)[0], M.summary_count(text), want)
            for name, text, want in _SUMMARIES]
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


# The entries sit BELOW a header line, so a `^` that anchors only the whole
# string (the pattern with no re.M) finds none of them. Two entries, so a
# reader that stops at the first is told apart from one that reads all.
_PLAYWRIGHT_LINE = ("Running 4 tests using 1 worker\n\n"
                    "  tests/a.spec.ts:4:7 \u203a math \u203a adds numbers\n"
                    "  tests/a.spec.ts:9:7 \u203a math \u203a subtracts\n\n"
                    "  2 failed\n  2 passed (1s)\n")


def _playwright_line_cases(check):
    text = _PLAYWRIGHT_LINE
    found = M._FAILURE_READERS["playwright"].findall(text)
    tally = M.read_run_tally(text)
    cases = M.run_failing_cases(text, "playwright")
    check("ru15 a Playwright list-reporter output whose failing entries start "
          "mid-text (not at offset 0) is read as failed with each failing "
          "test named, through _FAILURE_READERS['playwright']: %r / %r"
          % (found, tally),
          len(found) == 2 and tally is not None
          and tally["runner"] == "playwright" and tally["failed"] == 2
          and tally["assertions"] == 0
          and [c["id"] for c in cases] == ["adds numbers", "subtracts"])
    check("ru16 a Playwright line-reporter failure is not marked an assertion "
          "(it proves a failure, not an assertion: the tally counts none, the "
          "JSON reporter is what names one): %r / %r"
          % ([c["assertion"] for c in cases], tally),
          len(cases) == 2 and not any(c["assertion"] for c in cases)
          and tally["failed"] == 2 and tally["assertions"] == 0)


# What `tools/sweep-selftests.py` printed at the end of two real red runs,
# verbatim from the evidence ledger's `failing` tails: run
# 2026-10-19T05:41:28Z.21bec2 (two files that exited 1) and run
# 2026-10-19T00:00:44Z.ab64e9 (one file stopped at its timeout). The PASS line
# naming a path and a colon, the house tally and the `--- <path>: <why> ---`
# header above a failure's output are all in the real text, and none of them is
# a verdict on a file. The summary lines are BUILT by `_sweep_line`, byte for
# byte what the sweep printed, because the prose scan reads a count of cases
# written out in a literal as a claim about this repository.


def _sweep_line(ok, files, migrated, cases, slash=""):
    """The sweep's summary line, in its own spelling."""
    return ("%d/%d files ok, %d migrated to tests%s, %d cases"
            % (ok, files, migrated, slash, cases))


def _plain_line(ok, files, cases):
    """The sweep's summary line as it spells it now, with no `migrated` clause."""
    return "%d/%d files ok, %d cases" % (ok, files, cases)


_SWEEP_EXITED = "\n".join((
    "PASS sb1m RED TWIN: a block lifted into a stage while its caller still "
    "calls it reads as doubled, a block no [truncated]",
    "PASS tests/test_drive_phase.py: every file the drive and "
    "its fixtures write in text mode names [truncated]",
    "SELFTEST FAILED: 378/379 cases passed",
    "FAIL  tests/test__refs.py: exited 1",
    "FAIL  tests/test_drive_phase.py: exited 1",
    _sweep_line(338, 340, 155, 15755))) + "\n"
_SWEEP_TIMEOUT = "\n".join((
    "  ok      tools/sweep-selftests.py                                   "
    "%d cases  [30.0s]" % (100,),
    "--- tests/test_drive_phase.py: did not finish within 674s ---",
    "did not finish within 674s",
    "FAIL  tests/test_drive_phase.py: did not finish within 674s",
    _sweep_line(339, 340, 155, 16016))) + "\n"


# A red file is printed whole under its header, and a case belongs to the
# header above it - the same label in two files stays two cases.
_SWEEP_BLOCKS = "\n".join((
    "  FAILED  a.py   exited 1", "", "--- a.py: exited 1 ---",
    "PASS x1 first", "FAIL x5 second", "SELFTEST FAILED: 1/2 cases passed",
    "", "--- b.py: exited 1 ---", "FAIL x5 second", "",
    "FAIL  a.py: exited 1", "FAIL  b.py: exited 1", _plain_line(0, 2, 1)))


def _sweep_cases(check):
    failures = getattr(M, "sweep_failures", None)
    summary = getattr(M, "sweep_summary", None)
    exited = failures(_SWEEP_EXITED) if failures else "no reader"
    hung = failures(_SWEEP_TIMEOUT) if failures else "no reader"
    tally = summary(_SWEEP_EXITED) if summary else "no reader"
    check("rs1 the sweep's `FAIL  <path>: exited 1` and `FAIL  <path>: did not "
          "finish within Ns` lines each name the FILE and why, in printed "
          "order, and its summary line is read for the files it graded - the "
          "PASS line, the house tally and the `--- <path>: <why> ---` header "
          "name none: %r / %r / %r" % (exited, hung, tally),
          exited == [("tests/test__refs.py", "exited 1"),
                     ("tests/test_drive_phase.py", "exited 1")]
          and hung == [("tests/test_drive_phase.py",
                        "did not finish within 674s")]
          and tally == {"ok": 338, "files": 340, "migrated": 155,
                        "cases": 15755})
    # THE LINE AS THE SWEEP SPELLS IT NOW: no `migrated` clause, because no file is
    # classed that way any more. Built from parts, as the others are, so the prose scan
    # does not read it as a claim; the old spelling above is what the ledger keeps.
    _now = "%d/%d files ok, %d cases" % (3, 4, 120)
    _no_clause = len(())
    check("rs1b the sweep's summary without the retired `migrated` clause is read "
          "too, with `migrated` 0, and its FAIL line still accounts for the one "
          "red file: %r" % (summary(_now),),
          summary(_now) == {"ok": 3, "files": 4, "migrated": _no_clause, "cases": 120}
          and failures("FAIL  tests/test__refs.py: exited 1\n" + _now)
          == [("tests/test__refs.py", "exited 1")])
    # The summary as the sweep spells it today, with the directory's slash; the
    # ledger's copies above carry none.
    green = "\n".join(("  ok      tools/where.py   %d cases" % (7,),
                       _sweep_line(341, 341, 155, 16040, "/")))
    cut = "\n".join(("FAIL  tests/test__refs.py: exited 1",
                     _sweep_line(338, 340, 155, 15755, "/")))
    house = ("PASS pl1 first case\nFAIL  pl2 second case: why\n"
             "SELFTEST FAILED: 1/2 cases passed\n")
    got = ((failures(green), failures(cut), failures(house),
            failures(_SWEEP_EXITED.replace("FAIL  ", "FAIL "))) if failures
           else "no reader")
    check("rs2 THE ALLOW CASE for rs1: a green sweep names no file and says so "
          "with an empty list, while a tail whose FAIL lines do not account for "
          "every file the summary failed, output with no sweep summary at all, "
          "and a one-space FAIL line are NOT KNOWABLE (None) - never a partial "
          "or an empty answer: %r" % (got,),
          got == ([], None, None, None))
    red = _SWEEP_BLOCKS
    swept = M.sweep_failing_cases(red)
    plain = M.failing_cases(red, "house")
    check("rs3 the sweep's failing cases are read per file, each tagged with the "
          "script of the header above it, and its own two-space FAIL lines are "
          "not cases; output with no sweep summary has none to read: %r / %r"
          % (swept, plain),
          [(c["id"], c["script"]) for c in swept or ()]
          == [("x5", "a.py"), ("x5", "b.py")]
          and [c["id"] for c in plain] == ["x5", "x5"]
          and M.sweep_failing_cases("FAIL x5 second\n") is None)
    clean = M.sweep_tally(_plain_line(2, 2, 9))
    check("rs4 a sweep that graded every file ok has a tally of its summary's "
          "cases; one with a red file, one that ran no file and one that counted "
          "no case have none, and `read_run_tally` reads the clean one last, "
          "behind any runner's own: %r" % (clean,),
          clean == {"runner": M.SWEEP_RUNNER, "collected": 9, "failed": 0,
                    "assertions": 0, "files": 2}
          and M.sweep_tally(_plain_line(1, 2, 9)) is None
          and M.sweep_tally(_plain_line(0, 0, 0)) is None
          and M.sweep_tally(_plain_line(2, 2, 0)) is None
          and M.read_run_tally(_plain_line(2, 2, 9)) == clean
          and M.read_run_tally("=== 1 passed in 0.01s ===\n"
                               + _plain_line(2, 2, 9))["runner"] == "pytest")


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


_HOUSE_PRINTED = ("PASS pl1 first case\nFAIL pl2 second case (why)\nPASS \n"
                  "SELFTEST FAILED: 1/2 cases passed\n")


def _printed_cases(check):
    house = _HOUSE_PRINTED
    pytest = "=== 2 passed in 0.01s ===\n"
    got = (M.printed_labels(house), M.printed_labels(pytest),
           M.printed_labels("PASS pl1 x\n"), M.printed_labels(""))
    check("pl1 a house run's printed labels are its PASS and FAIL lines, and a "
          "runner that prints none for a passing case, or a run with no tally, "
          "answers None - unknown, never an empty list a binding is graded "
          "against: %r" % (got,),
          got == (["pl1 first case", "pl2 second case (why)"], None, None, None))


# A child on Windows writes `\r\n` through its pipe, and the run's bytes are
# decoded as they came - no universal newlines - so every reader is handed the
# CRLF text. Each fixture this suite holds is read twice more: as that twin,
# and with lone `\r` line ends.
_LINE_END_EXTRA = (
    "FAILED tests/test_x.py::test_a - assert 1 == 2\n=== 1 failed in 0.01s ===\n",
    "FAIL: test_a (mod.Cls)\n----\nAssertionError\n\nRan 1 test in 0.001s\n\n"
    "FAILED (failures=1)\n",
)
# The readers the line-end case must find, written out: a derivation that read
# nothing would otherwise compare nothing and pass.
_LINE_END_FLOOR = ("failing_cases", "jest_failures", "playwright_line_cases",
                   "playwright_line_tally", "read_run_tally", "read_tally",
                   "run_failing_cases", "summary_count", "summary_reader",
                   "summary_readers", "sweep_failing_cases", "sweep_failures",
                   "sweep_summary", "sweep_tally")


def _text_readers():
    """`[(name, fn, rest)]` - every public function of the module whose first
    parameter is `text`, `rest` its other parameters. Derived, so a reader added
    later is in the line-end case without anyone remembering to list it."""
    out = []
    for name in sorted(vars(M)):
        fn = getattr(M, name)
        if name.startswith("_") or not inspect.isfunction(fn) \
                or fn.__module__ != M.__name__:
            continue
        params = list(inspect.signature(fn).parameters.values())
        if params and params[0].name == "text":
            out.append((name, fn, params[1:]))
    return out


def _says_something(answer):
    """Whether a reader's answer carries a reading - a comparison of two empty
    answers proves nothing about line ends."""
    return answer is not None and answer != [] and answer != (None, "", ())


def _line_end_cases(check):
    fixtures = ([text for _name, text, _want in _SUMMARIES]
                + [_VITEST_ASSERT, _JEST_NODE_ASSERT, _JEST_COLOUR_RED,
                   _JEST_COLOUR_GREEN, _PLAYWRIGHT_LINE, _SWEEP_EXITED,
                   _SWEEP_TIMEOUT, _SWEEP_BLOCKS, _plain_line(2, 2, 9),
                   _HOUSE_PRINTED] + list(_LINE_END_EXTRA))
    readers = _text_readers()
    differ, unknown, answered = [], [], set()
    for name, fn, rest in readers:
        for i, text in enumerate(fixtures):
            given = {"runner": (M.read_run_tally(text) or {}).get("runner"),
                     "cmd": None}
            missing = [p.name for p in rest
                       if p.default is p.empty and p.name not in given]
            if missing:
                unknown.append((name, missing))
                break
            args = [given[p.name] for p in rest if p.default is p.empty]
            want = fn(text, *args)
            if _says_something(want):
                answered.add(name)
            for twin, ending in (("crlf", "\r\n"), ("cr", "\r")):
                got = fn(text.replace("\n", ending), *args)
                if got != want:
                    differ.append((name, i, twin, repr(want)[:120], repr(got)[:120]))
    names = [name for name, _fn, _rest in readers]
    check("ru17 every public reader whose first parameter is the run's text "
          "answers a fixture's CRLF twin, and its lone-CR twin, exactly as it "
          "answers the LF text, and each has a fixture it reads something from: "
          "readers %r; floor missing %r; differing (%d) %r; never answered %r; "
          "a required parameter the case cannot fill %r"
          % (names, sorted(set(_LINE_END_FLOOR) - set(names)), len(differ),
             differ[:4], sorted(set(names) - answered), unknown),
          set(_LINE_END_FLOOR) <= set(names) and not differ and not unknown
          and answered == set(names))


def _cases(check):
    _line_end_cases(check)
    _printed_cases(check)
    _table_cases(check)
    _summary_cases(check)
    _jest_cases(check)
    _vitest_cases(check)
    _node_assert_cases(check)
    _colour_cases(check)
    _playwright_line_cases(check)
    _sweep_cases(check)
    _layer_cases(check)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__runner_output.py --selftest\n")
    raise SystemExit(2)
