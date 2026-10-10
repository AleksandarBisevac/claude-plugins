#!/usr/bin/env python3
"""Cases for `governance/run-test-gate.py`.

WHAT THIS FILE IS ABOUT, in one line: a gate is a MEASUREMENT, and the two ways
this one stopped being a measurement were both exit 0.

Measured live before any of this existed. A docs task's gate was
`pre-commit run --all-files`; `isort` and `black` are fix-in-place, so they
rewrote five source files the task does not own and reported `Passed` BECAUSE
they had. Then, narrowed to the task's own two markdown files, every hook
SKIPPED -- that repo configures Python hooks only -- and the task went to `done`
on exit 0 with zero checks performed. One design, both failure modes, and the
exit code separated neither from a real verdict.

THE `runner` SEAM IS THE WHOLE REASON THESE CASES EXIST. `run_gate` takes the
command runner as an argument, so a fix-in-place hook can be simulated by a
runner that touches a file, and a skipping hook by one that prints `Skipped`.
Without that seam every case here would need a repository with `pre-commit`
installed, which is to say there would be no cases.

`git` IS REAL, though. The mutation half is a `git status --porcelain` diff, and
faking that would test the arithmetic rather than the question -- so the fixture
is an actual repository and the "mutation" is an actual file appearing in it.
"""
import datetime
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT, for the schema read)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402  (script_path: resolve by basename)
import _proc_group as _pg                          # noqa: E402  (the teardown `_tear_down` is)
import _journal_io                                 # noqa: E402  (the rows a stamp anchors)
import _evidence_io as _ev_io                      # noqa: E402  (STEP_KEYS: what a row keeps)
import _manifest_vocab                             # noqa: E402  (FULL_STATUS_WHOLE, for --full)
import _fmt as _rtg_fmt                            # noqa: E402  (where human_duration lives now)
import _manifest_phases as _phases                 # noqa: E402  (the identity pin below: an
#                                  alias, not a second body)
import _runner_output as _ro                       # noqa: E402  (the runner readers the
#                                  gate imports: the identity pin beside fl0)
import io as _io
import contextlib as _ctx

M = _loader.load_script("run-test-gate.py", "rtg")
_AT = _loader.load_script("audit-task.py", "rtg_audit_task")  # its parser, for the remedy pins

# --- which half of a platform split a case may assert -------------------------
# READ THE WAY THE PRODUCT READS IT, never off `sys.platform`. `_tear_down`
# branches on `os.killpg`, `shares_our_group` calls `os.getpgid`, and `_shell`
# hands an interrupt to whatever `os.kill` does here - so those names, and not a
# platform's name, are what decides which side of a split exists on this machine.
# A case that guessed by platform name could be right about the name and wrong
# about the mechanism, and the mechanism is the thing it needed.
#
# ONE CONSTANT, NOT THREE. `os.getpgid` gets no constant here on purpose: the
# skips are graded on a fresh `hasattr` rather than on whatever the `if` above
# them read, so a name kept for both jobs would have made the grade circular -
# `console_events()` carries that reasoning in full.
HAS_KILLPG = hasattr(os, "killpg")
# `os.kill(pid, SIGINT)` is an INTERRUPT only where signals are real. Where
# `signal.CTRL_C_EVENT` exists, python documents `os.kill` as generating a
# console-control event for that value and for CTRL_BREAK_EVENT, and as
# terminating the target through TerminateProcess for ANY OTHER value - SIGINT
# among them. A case that must interrupt a child rather than kill it needs this.
SENDS_REAL_SIGNALS = not hasattr(signal, "CTRL_C_EVENT")


def console_events():
    """The values `os.kill` delivers as console-control events here; () on posix.

    THE EVIDENCE BEHIND THE SKIP, COMPUTED A SECOND TIME ON PURPOSE. A skip is
    graded on whether the mechanism it names is really missing, and grading it on
    the very constant the `if` above it read would compare a value with itself:
    the branch could not be taken unless the evidence already said yes, so the
    grade could never be anything but a pass. Two reads is the floor for a check
    that has to be able to fail, and the second one is this - which also asks the
    question one step more sharply than the constant does, by naming SIGINT.
    """
    return tuple(v for v in (getattr(signal, "CTRL_C_EVENT", None),
                             getattr(signal, "CTRL_BREAK_EVENT", None))
                 if v is not None)

# The step a process-tree case runs, as a SCRIPT rather than as shell syntax.
# `sleep 30 & echo $! > f; sleep 30` is three things `cmd.exe` does not have, so
# on the windows leg the step exited immediately, no grandchild was ever started,
# and the case reported a teardown it had never exercised. One command with no
# operators in it is the same command on both platforms, and it builds the same
# shape either way: the shell starts this helper, this helper starts a
# grandchild, and the narrow kill `_tear_down` exists to replace reaches neither.
#
# THE GRANDCHILD IS MEASURED BY WHAT IT WRITES. The harm has always been stated
# as "a survivor keeps writing into the tree the gate is about to describe", so
# the file it is writing is the honest instrument - and a pid probe is not one
# here anyway: `os.kill(pid, 0)` on windows is a console-control event that takes
# a process GROUP id, and a grandchild leads no group.
CHILD_SOURCE = """\
import os
import subprocess
import sys
import time

MODE = sys.argv[1]
BEAT = sys.argv[2]

if MODE == "beat":
    while True:
        fh = open(BEAT, "a")
        fh.write("x")
        fh.close()
        time.sleep(0.05)
elif MODE == "stall":
    sys.stdout.write("marker\\n")
    sys.stdout.flush()
    time.sleep(30)
else:
    kid = subprocess.Popen([sys.executable, sys.argv[0], "beat", BEAT])
    fh = open(sys.argv[3], "w")
    fh.write("%d %d" % (os.getpid(), kid.pid))
    fh.close()
    time.sleep(30)
"""

# Long enough for two interpreters to start on the slowest leg, short enough that
# the case is not the reason the suite takes as long as it does.
TREE_TIMEOUT = 5

# --- what a runner leaves behind, per reporter --------------------------------
# These fixtures are TAKEN FROM THE REPORTERS rather than written to suit the
# reader. The discriminator below is keyed on shapes this file recognises, so a
# fixture invented alongside it would encode the same assumption twice and go
# green against a reader that cannot fire in the field. Every one below is what
# the named tool actually prints, trimmed; the
# tallies are all the SAME RUN - one pass and a hundred and thirty-nine failures
# - because that failure count is the exit status the fault turns on.
#
# THE SHARED SHAPE IS DELIBERATE: each of these runners exits with a number that
# is a COUNT and not a verdict, so exit 139 is ambiguous for all of them in
# exactly the way `128 + SIGSEGV` is.
MOCHA_JSON = """\
{
  "stats": {
    "suites": 12,
    "tests": 140,
    "passes": 1,
    "pending": 0,
    "failures": 139,
    "start": "2026-09-10T09:00:00.000Z",
    "end": "2026-09-10T09:00:12.000Z",
    "duration": 12000
  },
  "tests": [],
  "pending": [],
  "failures": [],
  "passes": []
}
"""
MOCHA_XUNIT = """\
<testsuite name="Mocha Tests" tests="140" failures="139" errors="139" \
skipped="0" timestamp="Thu, 10 Sep 2026 09:00:00 GMT" time="12.0000">
<testcase classname="order" name="totals a basket" time="0.001"/>
</testsuite>
"""
MOCHA_MIN = """\

  1 passing (12s)
  139 failing

  1) order
       rejects an empty basket:
     AssertionError: expected 0 to equal 1
"""
NUNIT_REPORT = """\
NUnit Console Runner 3.15.0
Test Count: 140, Passed: 1, Failed: 139, Warnings: 0, Inconclusive: 0, Skipped: 0
"""
CHECKSTYLE_REPORT = """\
Starting audit...
[ERROR] src/Main.java:12:1: Missing a Javadoc comment. [JavadocMethod]
Audit done.
Checkstyle ends with 139 errors.
"""
# THREE TAP FIXTURES WHERE THERE WAS ONE, AND THE SPLIT IS THE POINT.
# A single fixture carried BOTH the opening plan line and the closing tallies,
# so it matched whichever alternative was left and deleting either one kept
# `sk5e` green - a case that could not see the difference between "the runner
# closed" and "the runner started". A TAP plan is legal at either end of the
# stream and the classic form prints it FIRST, so each shape now has a fixture
# that exercises it alone.
#
# `tape`'s shape: the plan opens and the tallies close. Read for the TALLIES.
TAP_REPORT = """\
TAP version 13
1..140
ok 1 order totals a basket
not ok 2 order rejects an empty basket
# tests 140
# pass 1
# fail 139
"""
# `Test::More` under `done_testing()`: the plan is the LAST line and there are no
# tallies at all, which is the shape that would be lost by deleting the plan
# alternative rather than positioning it.
TAP_PLAN_LAST = """\
ok 1 - order totals a basket
not ok 2 - order rejects an empty basket
#   Failed test 'order rejects an empty basket'
#   at t/order.t line 12.
1..140
"""
# ...and the SAME classic stream killed after its second test: the plan is
# there, at the top, where it was written before any test ran.
TAP_KILLED = """\
TAP version 13
1..140
ok 1 order totals a basket
not ok 2 order rejects an empty basket
"""
VSTEST_REPORT = """\
Starting test execution, please wait...
Total tests: 140
     Passed: 1
     Failed: 139
Test Run Failed.
"""

# ...and the one shape that is NOT a report: `pre-commit` mid-run, with a hook
# already logged and the next one's line unfinished, which is what an
# out-of-memory reaper leaves. The arm meant to catch this configuration
# cannot fire here, because `ran_count` tallies LINES for `_STEP_WORDS` and so
# never answers None.
PRECOMMIT_KILLED = """\
check yaml...............................................................Passed
black...................................................................."""

# ...and the same wrapper with a hook that DOES publish a summary. `pre-commit`
# runs other runners, so pytest's own closing line is an end-of-run report for
# THAT HOOK and mid-flight for the step - `mypy` had not finished when the
# reaper arrived. Here `summary_count` answers a number, so the summary arm of
# `reached_a_verdict` said the step had spoken for its exit code and an
# OOM-killed composite was graded `failed`.
PRECOMMIT_HOOK_SUMMARY = """\
check yaml...............................................................Passed
pytest...................................................................Failed
- hook id: pytest
- exit code: 1

==================== 1 failed, 3 passed, 2 skipped in 0.42s ====================

mypy....................................................................."""


# --- what a runner prints when it reached no verdict ----------------------------
# CAPTURED, NOT COMPOSED. Each of these is what the named tool printed on this
# machine when it was driven into the state the name describes, trimmed only of
# a long relative prefix on a stack frame, and the one cmd.exe line, which is
# labelled as NOT captured where it sits. The shells were run as `sh -c`,
# `dash -c`, `zsh -c` and `bash -c` over a word that names no program (the
# word itself swapped for the entry the cases use); vitest 4.1.10 was
# run as `vitest run src/a.ts` over a tree whose only file is not a test; jest
# 30.0.5 was run with `--maxWorkers=2 --ci` over suites one of which calls
# `process.kill(process.pid, 'SIGSEGV')` inside a worker, and again over a
# suite with a syntax error. A fixture written to suit the reader would agree
# with it by construction.
SH_NOT_FOUND = "/bin/sh: lint,format,typecheck,test: command not found\n"
DASH_NOT_FOUND = "/bin/sh: 1: lint,format,typecheck,test: not found\n"
ZSH_NOT_FOUND = "zsh:1: command not found: lint,format,typecheck,test\n"
BASH_NOT_FOUND = "bash: line 1: lint,format,typecheck,test: command not found\n"
# cmd.exe's wording, which `_NO_VERDICT_SIGNATURES` deliberately does NOT read:
# no capture of it exists here, and an unanchored phrase at exit 1 would turn a
# windows harness's real failure into an infrastructure excuse. No plan command
# is handed to cmd.exe any more, but a command may still start it itself - a
# `cmd /c` step prints exactly this - so `nv7` still pins the refusal to read it.
CMD_NOT_RECOGNIZED = ("'lint' is not recognized as an internal or external "
                      "command,\r\noperable program or batch file.\r\n")
VITEST_NO_FILES = """\

 RUN  v4.1.10 /proj

No test files found, exiting with code 1

filter: src/a.ts
include: **/*.{test,spec}.?(c|m)[jt]s?(x)
exclude:  **/node_modules/**, **/.git/**
"""
JEST_KILLED_SUITE = "src/features/projects/create-project-duplicate-title.e2e.test.js"
JEST_WORKER_KILLED = """\
PASS src/features/projects/list.test.js
PASS src/features/projects/other.test.js
FAIL src/features/projects/create-project-duplicate-title.e2e.test.js
  ● Test suite failed to run

    A jest worker process (pid=4875) was terminated by another process: \
signal=SIGSEGV, exitCode=null. Operating system logs may contain more \
information on why this occurred.

      at ChildProcessWorker._onExit (../node_modules/jest-runner/node_modules/\
jest-worker/build/index.js:968:23)

Test Suites: 1 failed, 2 passed, 3 total
Tests:       2 passed, 2 total
Snapshots:   0 total
Time:        0.274 s
Ran all test suites.
"""
# ...the same run with a second suite that fails an ASSERTION. One real red
# beside the kill, so this is a verdict and it has to stay one.
JEST_KILLED_AND_RED = """\
PASS src/features/projects/other.test.js
PASS src/features/projects/list.test.js
FAIL src/features/projects/broken.test.js
  ● f

    expect(received).toBe(expected) // Object.is equality

    Expected: 2
    Received: 1

    > 1 | test('f', () => { expect(1).toBe(2); });
        |                             ^
      2 |

      at Object.toBe (src/features/projects/broken.test.js:1:29)

FAIL src/features/projects/create-project-duplicate-title.e2e.test.js
  ● Test suite failed to run

    A jest worker process (pid=4523) was terminated by another process: \
signal=SIGSEGV, exitCode=null. Operating system logs may contain more \
information on why this occurred.

      at ChildProcessWorker._onExit (../node_modules/jest-runner/node_modules/\
jest-worker/build/index.js:968:23)

Test Suites: 2 failed, 2 passed, 4 total
Tests:       1 failed, 2 passed, 3 total
Snapshots:   0 total
Time:        0.318 s
Ran all test suites.
"""
# ...and a suite that failed to run with NO signal: jest could not parse it.
# Same heading, a different first reason line, and no worker was killed.
JEST_UNPARSEABLE = """\
FAIL src/features/projects/syntax.test.js
  ● Test suite failed to run

    Jest encountered an unexpected token

    Jest failed to parse a file. This happens e.g. when your code or its \
dependencies use non-standard JavaScript syntax, or when Jest is not \
configured to support such syntax.

Test Suites: 1 failed, 1 total
Tests:       0 total
Snapshots:   0 total
Time:        0.149 s
Ran all test suites matching src/features/projects/syntax.
"""

# --- fixtures: an ordinary assertion failure, one runner at a time ------------
# `failing_lines`/`jest_failures` already answer "which CHECK failed" from these
# - the bullet title alone, per `_jest_failure_name`. What none of them answer is
# which FILE that check lives in, which is the suite path on the `FAIL` header
# above the bullet and is dropped on the floor today.
JEST_CART_FAIL = """\
FAIL src/cart.test.ts
  ● cart > rejects a negative quantity

    expected true to be false

Tests:       1 failed, 3 passed, 4 total
"""
# vitest prints the failing file TWICE - once beside a cross in the file tree,
# once again as `FAIL  <file> > <suite> > <name>` under `Failed Tests`. Only the
# second is read here: the first carries no `FAIL` word at all.
VITEST_CART_FAIL = """\
❯ src/cart.test.ts (5)
   × cart > rejects a negative quantity
FAIL  src/cart.test.ts > cart > rejects a negative quantity
 Tests  1 failed | 4 passed (5)
"""
PYTEST_CART_FAIL = """\
FAILED tests/test_cart.py::test_negative - AssertionError
=== 1 failed, 2 passed in 0.12s ===
"""
# mocha NUMBERS its failures and names only the check - no suite path is ever
# on the line, so this runner is recognised and still answers (None, ...).
MOCHA_CART_FAIL = """\
  4 passing (23ms)
  1 failing

  1) cart rejects a negative quantity:
     AssertionError: expected true to be false
"""
# A `FAIL` header naming only a vendored path - the one case where a real jest
# header exists and still names nothing this gate may attribute to the work.
JEST_VENDOR_ONLY_FAIL = """\
FAIL node_modules/some-pkg/dist/index.test.js
  ● x

Tests:       1 failed, 0 passed, 1 total
"""

# --- fixtures: what Playwright Test really prints ----------------------------
# CAPTURED, NOT WRITTEN. `@playwright/test` 1.56.0 (the version of the
# `playwright` library package.json pins), installed into a scratch directory
# and run as `npx playwright test --retries=1 --reporter=list` and again with
# `--reporter=line`, with `CI` unset and `FORCE_COLOR=0`. The spec holds one
# test that throws while `testInfo.retry === 0` and passes on its retry, one
# plain passing test and - for the RED captures - one test that always fails;
# the PROJECT capture adds a `playwright.config.js` declaring a single project
# named `alpha`. The one edit to the bytes: the absolute scratch directory on
# each `at ...` stack line is replaced by `<scratch>`, because the capture
# machine's home directory is not a thing this repository may carry. Everything
# else, the line reporter's cursor escapes included, is as it was printed.
PW_LIST_FLAKY = (
    '\n'
    'Running 2 tests using 1 worker\n'
    '\n'
    '  ✘  1 tests/flaky.spec.js:2:1 › settles on retry (1ms)\n'
    '  ✓  2 tests/flaky.spec.js:2:1 › settles on retry (retry #1) (3ms)\n'
    '  ✓  3 tests/flaky.spec.js:6:1 › always passes (0ms)\n'
    '\n'
    '\n'
    '  1) tests/flaky.spec.js:2:1 › settles on retry ────────────────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    "      6 | test('always passes', async () => {\n"
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '  1 flaky\n'
    '    tests/flaky.spec.js:2:1 › settles on retry ─────────────────────────────────────────────────────\n'
    '  1 passed (599ms)\n'
)

PW_LINE_FLAKY = (
    '\n'
    'Running 2 tests using 1 worker\n'
    '\n'
    '\x1b[1A\x1b[2K[1/2] tests/flaky.spec.js:2:1 › settles on retry\n'
    '\x1b[1A\x1b[2K[2/2] tests/flaky.spec.js:2:1 › settles on retry (retry #1)\n'
    '\x1b[1A\x1b[2K  1) tests/flaky.spec.js:2:1 › settles on retry ────────────────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    "      6 | test('always passes', async () => {\n"
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '\n'
    '\x1b[1A\x1b[2K[3/2] (retries) tests/flaky.spec.js:6:1 › always passes\n'
    '\x1b[1A\x1b[2K  1 flaky\n'
    '    tests/flaky.spec.js:2:1 › settles on retry ─────────────────────────────────────────────────────\n'
    '  1 passed (560ms)\n'
)

PW_LIST_RED = (
    '\n'
    'Running 3 tests using 2 workers\n'
    '\n'
    '  ✘  2 tests/flaky.spec.js:2:1 › settles on retry (1ms)\n'
    '  ✘  1 tests/hard.spec.js:2:1 › always fails (3ms)\n'
    '  ✓  4 tests/flaky.spec.js:2:1 › settles on retry (retry #1) (2ms)\n'
    '  ✘  3 tests/hard.spec.js:2:1 › always fails (retry #1) (3ms)\n'
    '  ✓  5 tests/flaky.spec.js:6:1 › always passes (1ms)\n'
    '\n'
    '\n'
    '  1) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  2) tests/flaky.spec.js:2:1 › settles on retry ────────────────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    "      6 | test('always passes', async () => {\n"
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 flaky\n'
    '    tests/flaky.spec.js:2:1 › settles on retry ─────────────────────────────────────────────────────\n'
    '  1 passed (578ms)\n'
)

PW_LINE_RED = (
    '\n'
    'Running 3 tests using 2 workers\n'
    '\n'
    '\x1b[1A\x1b[2K[1/3] tests/hard.spec.js:2:1 › always fails\n'
    '\x1b[1A\x1b[2K[2/3] tests/flaky.spec.js:2:1 › settles on retry\n'
    '\x1b[1A\x1b[2K[3/3] tests/hard.spec.js:2:1 › always fails (retry #1)\n'
    '\x1b[1A\x1b[2K[4/3] (retries) tests/flaky.spec.js:2:1 › settles on retry (retry #1)\n'
    '\x1b[1A\x1b[2K  1) tests/flaky.spec.js:2:1 › settles on retry ────────────────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    "      6 | test('always passes', async () => {\n"
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '\n'
    '\x1b[1A\x1b[2K[5/3] (retries) tests/flaky.spec.js:6:1 › always passes\n'
    '\x1b[1A\x1b[2K  2) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '\n'
    '\x1b[1A\x1b[2K  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 flaky\n'
    '    tests/flaky.spec.js:2:1 › settles on retry ─────────────────────────────────────────────────────\n'
    '  1 passed (590ms)\n'
)

PW_LIST_PROJECT_RED = (
    '\n'
    'Running 3 tests using 2 workers\n'
    '\n'
    '  ✘  2 [alpha] › tests/flaky.spec.js:2:1 › settles on retry (1ms)\n'
    '  ✘  1 [alpha] › tests/hard.spec.js:2:1 › always fails (3ms)\n'
    '  ✓  4 [alpha] › tests/flaky.spec.js:2:1 › settles on retry (retry #1) (2ms)\n'
    '  ✘  3 [alpha] › tests/hard.spec.js:2:1 › always fails (retry #1) (3ms)\n'
    '  ✓  5 [alpha] › tests/flaky.spec.js:6:1 › always passes (1ms)\n'
    '\n'
    '\n'
    '  1) [alpha] › tests/hard.spec.js:2:1 › always fails ───────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  2) [alpha] › tests/flaky.spec.js:2:1 › settles on retry ──────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    "      6 | test('always passes', async () => {\n"
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '  1 failed\n'
    '    [alpha] › tests/hard.spec.js:2:1 › always fails ────────────────────────────────────────────────\n'
    '  1 flaky\n'
    '    [alpha] › tests/flaky.spec.js:2:1 › settles on retry ───────────────────────────────────────────\n'
    '  1 passed (612ms)\n'
)

# --- fixtures: a muted failure beside a failure nobody named -----------------
# CAPTURED, NOT WRITTEN, by the routine the Playwright block above states
# (`@playwright/test` 1.56.0 in a scratch directory, `CI` unset,
# `FORCE_COLOR=0`, `--reporter=list`, the scratch path on each stack line
# replaced by `<scratch>`). Each pairs `tests/hard.spec.js` - or, for the first,
# the failing step of a serial group - with something the named failure does
# not account for:
#   DID_NOT_RUN   `test.describe.serial` whose first step fails, so the rest
#                 never run; `npx playwright test --workers=1`, exit 1.
#   INTERRUPTED   a five-second test beside the failing one, the run sent
#                 SIGINT after about two and a half seconds;
#                 `node .../@playwright/test/cli.js test --workers=2`, exit 130.
#   STRAY_ERROR   a passing test that throws from a `setTimeout` after it
#                 returns; `npx playwright test --workers=1`, exit 1.
PW_LIST_DID_NOT_RUN = (
    '\n'
    'Running 4 tests using 1 worker\n'
    '\n'
    '  ✘  1 tests/serial.spec.js:3:3 › checkout flow › step one breaks (3ms)\n'
    '  -  2 tests/serial.spec.js:4:3 › checkout flow › step two\n'
    '  -  3 tests/serial.spec.js:5:3 › checkout flow › step three\n'
    '  -  4 tests/serial.spec.js:6:3 › checkout flow › step four\n'
    '\n'
    '\n'
    '  1) tests/serial.spec.js:3:3 › checkout flow › step one breaks ────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test.describe.serial('checkout flow', () => {\n"
    "    > 3 |   test('step one breaks', async () => { expect(1).toBe(2); });\n"
    '        |                                                   ^\n'
    "      4 |   test('step two', async () => { expect(1).toBe(1); });\n"
    "      5 |   test('step three', async () => { expect(1).toBe(1); });\n"
    "      6 |   test('step four', async () => { expect(1).toBe(1); });\n"
    '        at <scratch>/tests/serial.spec.js:3:51\n'
    '\n'
    '  1 failed\n'
    '    tests/serial.spec.js:3:3 › checkout flow › step one breaks ─────────────────────────────────────\n'
    '  3 did not run\n'
)

PW_LIST_INTERRUPTED = (
    '\n'
    'Running 2 tests using 2 workers\n'
    '\n'
    '  ✘  2 tests/hard.spec.js:2:1 › always fails (3ms)\n'
    '  ✘  1 tests/slow.spec.js:2:1 › slow one (1.9s)\n'
    '\n'
    '\n'
    '  1) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 interrupted\n'
    '    tests/slow.spec.js:2:1 › slow one ──────────────────────────────────────────────────────────────\n'
)

PW_LIST_STRAY_ERROR = (
    '\n'
    'Running 2 tests using 1 worker\n'
    '\n'
    '  ✘  1 tests/hard.spec.js:2:1 › always fails (3ms)\n'
    '  ✓  2 tests/stray.spec.js:2:1 › leaves a stray error behind (3ms)\n'
    'Error: stray error after the test\n'
    '\n'
    '\x1b[31mFailed worker ran 1 test:\x1b[39m\n'
    'tests/stray.spec.js:2:1 › leaves a stray error behind\n'
    '\n'
    '   at tests/stray.spec.js:3\n'
    '\n'
    "  1 | const { test, expect } = require('@playwright/test');\n"
    "  2 | test('leaves a stray error behind', async () => {\n"
    "> 3 |   setTimeout(() => { throw new Error('stray error after the test'); }, 0);\n"
    '    |                            ^\n'
    '  4 |   expect(1).toBe(1);\n'
    '  5 | });\n'
    '  6 |\n'
    '    at Timeout._onTimeout (<scratch>/tests/stray.spec.js:3:28)\n'
    '\n'
    '\n'
    '  1) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 passed (1.1s)\n'
    '  1 error was not a part of any test, see above for details\n'
)

# vitest 4.1.10, the copy this repository installs, run from a scratch
# directory as `node <repo>/node_modules/vitest/vitest.mjs run` with
# `NO_COLOR=1`, exit 1: `src/cart.test.js` fails, and `src/stray.test.js`
# passes while throwing from a `setTimeout` - vitest's `Errors  1 error`.
# The scratch path on the `RUN` line is replaced by `<scratch>`.
VITEST_STRAY_ERROR = (
    '\n'
    ' RUN  v4.1.10 <scratch>\n'
    '\n'
    ' ❯ src/cart.test.js (1 test | 1 failed) 4ms\n'
    '   × rejects a negative quantity 3ms\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯\n'
    '\n'
    ' FAIL  src/cart.test.js > rejects a negative quantity\n'
    'AssertionError: expected true to be false // Object.is equality\n'
    '\n'
    '- Expected\n'
    '+ Received\n'
    '\n'
    '- false\n'
    '+ true\n'
    '\n'
    ' ❯ src/cart.test.js:2:58\n'
    "      1| import { test, expect } from 'vitest';\n"
    "      2| test('rejects a negative quantity', () => { expect(true).toBe(false); …\n"
    '       |                                                          ^\n'
    '      3|\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯ Unhandled Errors ⎯⎯⎯⎯⎯⎯\n'
    '\n'
    'Vitest caught 1 unhandled error during the test run.\n'
    'This might cause false positive tests. Resolve unhandled errors to make sure your tests are not affected.\n'
    '\n'
    '⎯⎯⎯⎯⎯ Uncaught Exception ⎯⎯⎯⎯⎯\n'
    'Error: stray error after the test\n'
    ' ❯ Timeout._onTimeout src/stray.test.js:3:28\n'
    "      1| import { test, expect } from 'vitest';\n"
    "      2| test('leaves a stray error behind', () => {\n"
    "      3|   setTimeout(() => { throw new Error('stray error after the test'); },…\n"
    '       |                            ^\n'
    '      4|   expect(1).toBe(1);\n'
    '      5| });\n'
    ' ❯ listOnTimeout node:internal/timers:585:17\n'
    ' ❯ processTimers node:internal/timers:521:7\n'
    '\n'
    'This error originated in "src/stray.test.js" test file. It doesn\'t mean the error was thrown inside the file itself, but while it was running.\n'
    '⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n'
    '\n'
    '\n'
    ' Test Files  1 failed | 1 passed (2)\n'
    '      Tests  1 failed | 1 passed (2)\n'
    '     Errors  1 error\n'
    '   Start at  17:34:42\n'
    '   Duration  104ms (transform 18ms, setup 0ms, import 31ms, tests 5ms, environment 0ms)\n'
    '\n'
)

# jest 30.5.2 (not pinned by this repository - installed into a scratch
# directory for this capture alone), `npx jest` with `collectCoverage` and a
# global lines threshold of 100, exit 1: the one failing test is named and the
# threshold failure beneath the coverage table is not a test at all.
JEST_THRESHOLD_FAIL = (
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: null\n'
    '\n'
    "      1 | const { price } = require('./price');\n"
    "    > 2 | test('rejects a negative quantity', () => { expect(price(-1)).toBe(0); });\n"
    '        |                                                               ^\n'
    '      3 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:2:63)\n'
    '\n'
    '----------|---------|----------|---------|---------|-------------------\n'
    'File      | % Stmts | % Branch | % Funcs | % Lines | Uncovered Line #s \n'
    '----------|---------|----------|---------|---------|-------------------\n'
    'All files |      75 |       50 |     100 |   66.66 |                   \n'
    ' price.js |      75 |       50 |     100 |   66.66 | 3                 \n'
    '----------|---------|----------|---------|---------|-------------------\n'
    'Jest: Coverage for lines (66.66%) does not meet "global" threshold (100%)\n'
    'Test Suites: 1 failed, 1 total\n'
    'Tests:       1 failed, 1 total\n'
    'Snapshots:   0 total\n'
    'Time:        0.196 s\n'
    'Ran all test suites.\n'
)

# HAND-BUILT, and the only fixture in this block that is: the summary counts
# two failures and the short summary names one. No runner run here could be
# made to print that pair, and it is the shape of every reporter that names
# fewer failures than it counts.
PYTEST_COUNTS_MORE_THAN_NAMED = """\
FAILED tests/test_cart.py::test_negative - AssertionError
=== 2 failed, 3 passed in 0.12s ===
"""

# --- fixtures: what a mute must refuse, and what it may honour ---------------
# CAPTURED, NOT WRITTEN, each with the scratch directory it ran in replaced by
# `<scratch>` and nothing else changed. Every install was made for this capture
# alone and deleted after it.
#   pytest 9.1.1 and pytest-cov 7.1.0, in a fresh venv (`python -m pytest`):
#     PYTEST_REAL_FAIL      `pytest -q`, one failing test beside a passing one;
#                           exit 1.
#     PYTEST_RF_WITH_ERROR  `pytest -q -rf`, a failing test and a fixture that
#                           errors at setup - the short summary names only the
#                           failure; exit 1.
#     PYTEST_STOPPED_EARLY  `pytest -q -x`, two failing tests; exit 1.
#     PYTEST_COV_THRESHOLD  `pytest -q --cov=shop --cov-fail-under=100`; exit 1.
# Two lines are BUILT rather than written, with bytes unchanged: ruff's rule
# code, which reads to this tree's citation lint as a register id, and jest's
# suites ratio, which reads to the prose-number lint as a count claim.
#   pre-commit 4.6.2, two `repo: local` hooks (`python -m pytest -q` and
#   `ruff check`), `pre-commit run --all-files`; exit 1:
#     PRECOMMIT_PYTEST_AND_RUFF
#   the same tree, `sh -c 'pytest -q; ruff check .'`; exit 1:
#     PYTEST_THEN_RUFF
#   jest 30.5.2 and mocha 12.0.2, `CI` unset, `FORCE_COLOR=0`:
#     JEST_REAL_FAIL        `npx jest src/cart.test.js`; exit 1.
#     JEST_BAIL             `npx jest --bail -i`, two failing suites; exit 1.
#     MOCHA_THEN_JEST       `sh -c 'npx mocha ...; npx jest src/cart.test.js'`
#                           with `NO_COLOR=1` - one step's output carrying two
#                           runners' summaries; exit 1 (jest's).
#   vitest 4.1.10 with @vitest/coverage-v8 4.1.10, `NO_COLOR=1`:
#     VITEST_REAL_FAIL      `npx vitest run src/cart.test.js`; exit 1.
#     VITEST_BAIL           `npx vitest run --bail=1 --no-file-parallelism`,
#                           two failing files; exit 1.
#     VITEST_COV_THRESHOLD  `npx vitest run src/cart.test.js --coverage.enabled
#                           --coverage.reportOnFailure --coverage.include=...
#                           --coverage.thresholds.lines=100`; exit 1. Without
#                           `reportOnFailure` this version prints no coverage
#                           at all once a test fails.
PYTEST_REAL_FAIL = (
    'F.                                                                       [100%]\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert -1 > 0\n'
    'E       assert -1 > 0\n'
    '\n'
    'tests/test_cart.py:2: AssertionError\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert -1 > 0\n'
    '1 failed, 1 passed in 0.01s\n'
)

PYTEST_RF_WITH_ERROR = (
    'FE                                                                       [100%]\n'
    '==================================== ERRORS ====================================\n'
    '______________________ ERROR at setup of test_uses_basket ______________________\n'
    '\n'
    '    @pytest.fixture\n'
    '    def basket():\n'
    '>       raise RuntimeError("fixture setup fails")\n'
    'E       RuntimeError: fixture setup fails\n'
    '\n'
    'tests/test_cart.py:6: RuntimeError\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert -1 > 0\n'
    'E       assert -1 > 0\n'
    '\n'
    'tests/test_cart.py:10: AssertionError\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert -1 > 0\n'
    '1 failed, 1 error in 0.01s\n'
)

PYTEST_STOPPED_EARLY = (
    'F\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert -1 > 0\n'
    'E       assert -1 > 0\n'
    '\n'
    'tests/test_cart.py:2: AssertionError\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert -1 > 0\n'
    '!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!\n'
    '1 failed in 0.01s\n'
)

PYTEST_COV_THRESHOLD = (
    'F\n'
    'ERROR: Coverage failure: total of 75 is less than fail-under=100\n'
    '                                                                         [100%]\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert price(-1) == 0\n'
    'E       assert None == 0\n'
    'E        +  where None = price(-1)\n'
    '\n'
    'tests/test_cart.py:5: AssertionError\n'
    '================================ tests coverage ================================\n'
    '_______________ coverage: platform darwin, python 3.14.7-final-0 _______________\n'
    '\n'
    'Name               Stmts   Miss  Cover\n'
    '--------------------------------------\n'
    'shop/__init__.py       0      0   100%\n'
    'shop/price.py          4      1    75%\n'
    '--------------------------------------\n'
    'TOTAL                  4      1    75%\n'
    'FAIL Required test coverage of 100% not reached. Total coverage: 75.00%\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert None == 0\n'
    '1 failed in 0.01s\n'
)

PRECOMMIT_PYTEST_AND_RUFF = (
    'pytest...................................................................Failed\n'
    '- hook id: pytest\n'
    '- exit code: 1\n'
    '\n'
    'F.                                                                       [100%]\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert -1 > 0\n'
    'E       assert -1 > 0\n'
    '\n'
    'tests/test_cart.py:2: AssertionError\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert -1 > 0\n'
    '1 failed, 1 passed in 0.01s\n'
    '\n'
    'ruff.....................................................................Failed\n'
    '- hook id: ruff\n'
    '- exit code: 1\n'
    '\n'
    + ("F%d" % (401,)) + ' [*] `os` imported but unused\n'
    ' --> lint_me.py:1:8\n'
    '  |\n'
    '1 | import os\n'
    '  |        ^^\n'
    'help: Remove unused import: `os`\n'
    '  |\n'
    '  - import os\n'
    '  |\n'
    '\n'
    'PLR0133 Two constants compared in a comparison, consider replacing `1 > 0`\n'
    ' --> tests/test_cart.py:6:12\n'
    '  |\n'
    '5 | def test_positive():\n'
    '6 |     assert 1 > 0\n'
    '  |            ^\n'
    '\n'
    'Found 2 errors.\n'
    '[*] 1 fixable with the `--fix` option.\n'
    '\n'
)

PYTEST_THEN_RUFF = (
    'F.                                                                       [100%]\n'
    '=================================== FAILURES ===================================\n'
    '________________________________ test_negative _________________________________\n'
    '\n'
    '    def test_negative():\n'
    '>       assert -1 > 0\n'
    'E       assert -1 > 0\n'
    '\n'
    'tests/test_cart.py:2: AssertionError\n'
    '=========================== short test summary info ============================\n'
    'FAILED tests/test_cart.py::test_negative - assert -1 > 0\n'
    '1 failed, 1 passed in 0.01s\n'
    + ("F%d" % (401,)) + ' [*] `os` imported but unused\n'
    ' --> lint_me.py:1:8\n'
    '  |\n'
    '1 | import os\n'
    '  |        ^^\n'
    'help: Remove unused import: `os`\n'
    '  |\n'
    '  - import os\n'
    '  |\n'
    '\n'
    'PLR0133 Two constants compared in a comparison, consider replacing `1 > 0`\n'
    ' --> tests/test_cart.py:6:12\n'
    '  |\n'
    '5 | def test_positive():\n'
    '6 |     assert 1 > 0\n'
    '  |            ^\n'
    '\n'
    'Found 2 errors.\n'
    '[*] 1 fixable with the `--fix` option.\n'
)

JEST_REAL_FAIL = (
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: null\n'
    '\n'
    "      1 | const { price } = require('./price');\n"
    "    > 2 | test('rejects a negative quantity', () => { expect(price(-1)).toBe(0); });\n"
    '        |                                                               ^\n'
    '      3 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:2:63)\n'
    '\n'
    'Test Suites: 1 failed, 1 total\n'
    'Tests:       1 failed, 1 total\n'
    'Snapshots:   0 total\n'
    'Time:        0.27 s\n'
    'Ran all test suites matching src/cart.test.js.\n'
)

JEST_BAIL = (
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: null\n'
    '\n'
    "      1 | const { price } = require('./price');\n"
    "    > 2 | test('rejects a negative quantity', () => { expect(price(-1)).toBe(0); });\n"
    '        |                                                               ^\n'
    '      3 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:2:63)\n'
    '\n'
    'Test Suites: 1 failed, ' + ("%d of %d total\n" % (1, 2)) +
    'Tests:       1 failed, 1 total\n'
    'Snapshots:   0 total\n'
    'Time:        0.115 s, estimated 1 s\n'
    'Ran all test suites.\n'
)

MOCHA_THEN_JEST = (
    '\n'
    '\n'
    '  ✔ adds tax\n'
    '\n'
    '  1 passing (1ms)\n'
    '\n'
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: null\n'
    '\n'
    "      1 | const { price } = require('./price');\n"
    "    > 2 | test('rejects a negative quantity', () => { expect(price(-1)).toBe(0); });\n"
    '        |                                                               ^\n'
    '      3 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:2:63)\n'
    '\n'
    'Test Suites: 1 failed, 1 total\n'
    'Tests:       1 failed, 1 total\n'
    'Snapshots:   0 total\n'
    'Time:        0.163 s, estimated 1 s\n'
    'Ran all test suites matching src/cart.test.js.\n'
)

VITEST_REAL_FAIL = (
    '\n'
    ' RUN  v4.1.10 <scratch>\n'
    '\n'
    ' ❯ src/cart.test.js (1 test | 1 failed) 3ms\n'
    '   × rejects a negative quantity 3ms\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯\n'
    '\n'
    ' FAIL  src/cart.test.js > rejects a negative quantity\n'
    'AssertionError: expected null to be +0 // Object.is equality\n'
    '\n'
    '- Expected:\n'
    '0\n'
    '\n'
    '+ Received:\n'
    'null\n'
    '\n'
    ' ❯ src/cart.test.js:3:63\n'
    "      1| import { test, expect } from 'vitest';\n"
    "      2| import { price } from './price.js';\n"
    "      3| test('rejects a negative quantity', () => { expect(price(-1)).toBe(0);…\n"
    '       |                                                               ^\n'
    '      4|\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯\n'
    '\n'
    '\n'
    ' Test Files  1 failed (1)\n'
    '      Tests  1 failed (1)\n'
    '   Start at  18:01:54\n'
    '   Duration  97ms (transform 10ms, setup 0ms, import 17ms, tests 3ms, environment 0ms)\n'
    '\n'
)

VITEST_BAIL = (
    '\n'
    ' RUN  v4.1.10 <scratch>\n'
    '\n'
    ' ❯ src/cart.test.js (1 test | 1 failed) 4ms\n'
    '   × rejects a negative quantity 3ms\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯\n'
    '\n'
    ' FAIL  src/cart.test.js > rejects a negative quantity\n'
    'AssertionError: expected null to be +0 // Object.is equality\n'
    '\n'
    '- Expected:\n'
    '0\n'
    '\n'
    '+ Received:\n'
    'null\n'
    '\n'
    ' ❯ src/cart.test.js:3:63\n'
    "      1| import { test, expect } from 'vitest';\n"
    "      2| import { price } from './price.js';\n"
    "      3| test('rejects a negative quantity', () => { expect(price(-1)).toBe(0);…\n"
    '       |                                                               ^\n'
    '      4|\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯\n'
    '\n'
    '\n'
    ' Test Files  1 failed (2)\n'
    '      Tests  1 failed (1)\n'
    '   Start at  18:01:55\n'
    '   Duration  93ms (transform 10ms, setup 0ms, import 17ms, tests 4ms, environment 0ms)\n'
    '\n'
)

VITEST_COV_THRESHOLD = (
    '\n'
    ' RUN  v4.1.10 <scratch>\n'
    '      Coverage enabled with v8\n'
    '\n'
    ' ❯ src/cart.test.js (1 test | 1 failed) 4ms\n'
    '   × rejects a negative quantity 3ms\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯\n'
    '\n'
    ' FAIL  src/cart.test.js > rejects a negative quantity\n'
    'AssertionError: expected null to be +0 // Object.is equality\n'
    '\n'
    '- Expected:\n'
    '0\n'
    '\n'
    '+ Received:\n'
    'null\n'
    '\n'
    ' ❯ src/cart.test.js:3:63\n'
    "      1| import { test, expect } from 'vitest';\n"
    "      2| import { price } from './price.js';\n"
    "      3| test('rejects a negative quantity', () => { expect(price(-1)).toBe(0);…\n"
    '       |                                                               ^\n'
    '      4|\n'
    '\n'
    '⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯\n'
    '\n'
    '\n'
    ' Test Files  1 failed (1)\n'
    '      Tests  1 failed (1)\n'
    '   Start at  18:02:06\n'
    '   Duration  123ms (transform 11ms, setup 0ms, import 19ms, tests 4ms, environment 0ms)\n'
    '\n'
    ' % Coverage report from v8\n'
    '----------|---------|----------|---------|---------|-------------------\n'
    'File      | % Stmts | % Branch | % Funcs | % Lines | Uncovered Line #s \n'
    '----------|---------|----------|---------|---------|-------------------\n'
    'All files |   66.66 |       50 |     100 |      50 |                   \n'
    ' price.js |   66.66 |       50 |     100 |      50 | 3                 \n'
    '----------|---------|----------|---------|---------|-------------------\n'
    '\n'
    '=============================== Coverage summary ===============================\n'
    'Statements   : 66.66% ( 2/3 )\n'
    'Branches     : 50% ( 1/2 )\n'
    'Functions    : 100% ( 1/1 )\n'
    'Lines        : 50% ( 1/2 )\n'
    '================================================================================\n'
    'ERROR: Coverage for lines (50%) does not meet global threshold (100%)\n'
)

# --- fixtures: what a direct runner call still hides -------------------------
# CAPTURED, NOT WRITTEN; the scratch directory is replaced by `<scratch>` and
# nothing else changed, and every install was deleted after its capture.
#   playwright 1.56.0, `CI` unset, `FORCE_COLOR=0`, `--reporter=list`:
#     PW_LIST_RED_NO_FLAKY   `npx playwright test --retries=1 --workers=1`,
#                            one failing test beside a passing one; exit 1.
#     PW_LIST_FAIL_ON_FLAKY  the same plus a test that passes on retry, with
#                            `--fail-on-flaky-tests`; exit 1.
#   jest 30.5.2, `CI` unset, `FORCE_COLOR=0`, `npx jest`:
#     JEST_OBSOLETE_SNAPSHOT       a failing test beside a snapshot file
#                                  holding an entry no test writes; exit 1.
#     JEST_OVER_SUMMARY_THRESHOLD  one failing suite among more suites than
#                                  jest's `summaryThreshold`, so the failure is
#                                  printed again under `Summary of all failing
#                                  tests`; exit 1.
PW_LIST_RED_NO_FLAKY = (
    '\n'
    'Running 2 tests using 1 worker\n'
    '\n'
    '  ✓  1 tests/fine.spec.js:2:1 › always passes (5ms)\n'
    '  ✘  2 tests/hard.spec.js:2:1 › always fails (1ms)\n'
    '  ✘  3 tests/hard.spec.js:2:1 › always fails (retry #1) (3ms)\n'
    '\n'
    '\n'
    '  1) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 passed (585ms)\n'
)

PW_LIST_FAIL_ON_FLAKY = (
    '\n'
    'Running 3 tests using 1 worker\n'
    '\n'
    '  ✓  1 tests/fine.spec.js:2:1 › always passes (2ms)\n'
    '  ✘  2 tests/flaky.spec.js:2:1 › settles on retry (0ms)\n'
    '  ✓  3 tests/flaky.spec.js:2:1 › settles on retry (retry #1) (6ms)\n'
    '  ✘  4 tests/hard.spec.js:2:1 › always fails (1ms)\n'
    '  ✘  5 tests/hard.spec.js:2:1 › always fails (retry #1) (3ms)\n'
    '\n'
    '\n'
    '  1) tests/hard.spec.js:2:1 › always fails ─────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '    Retry #1 ───────────────────────────────────────────────────────────────────────────────────────\n'
    '\n'
    '    Error: \x1b[2mexpect(\x1b[22m\x1b[31mreceived\x1b[39m\x1b[2m).\x1b[22mtoBe\x1b[2m(\x1b[22m\x1b[32mexpected\x1b[39m\x1b[2m) // Object.is equality\x1b[22m\n'
    '\n'
    '    Expected: \x1b[32m2\x1b[39m\n'
    '    Received: \x1b[31m1\x1b[39m\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('always fails', async () => {\n"
    '    > 3 |   expect(1).toBe(2);\n'
    '        |             ^\n'
    '      4 | });\n'
    '      5 |\n'
    '        at <scratch>/tests/hard.spec.js:3:13\n'
    '\n'
    '  2) tests/flaky.spec.js:2:1 › settles on retry ────────────────────────────────────────────────────\n'
    '\n'
    '    Error: first attempt fails\n'
    '\n'
    "      1 | const { test, expect } = require('@playwright/test');\n"
    "      2 | test('settles on retry', async ({}, testInfo) => {\n"
    "    > 3 |   if (testInfo.retry === 0) throw new Error('first attempt fails');\n"
    '        |                                   ^\n'
    '      4 |   expect(1).toBe(1);\n'
    '      5 | });\n'
    '      6 |\n'
    '        at <scratch>/tests/flaky.spec.js:3:35\n'
    '\n'
    '  1 failed\n'
    '    tests/hard.spec.js:2:1 › always fails ──────────────────────────────────────────────────────────\n'
    '  1 flaky\n'
    '    tests/flaky.spec.js:2:1 › settles on retry ─────────────────────────────────────────────────────\n'
    '  1 passed (888ms)\n'
)

JEST_OBSOLETE_SNAPSHOT = (
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: -1\n'
    '\n'
    "    > 1 | test('rejects a negative quantity', () => { expect(-1).toBe(0); });\n"
    '        |                                                        ^\n'
    "      2 | test('renders a label', () => { expect('label').toMatchSnapshot(); });\n"
    '      3 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:1:56)\n'
    '\n'
    ' › 1 snapshot obsolete.\n'
    '   • a test that no longer exists 1\n'
    'Snapshot Summary\n'
    ' › 1 snapshot obsolete from 1 test suite. To remove it, run `npm run npx -- -u`.\n'
    '   ↳ src/cart.test.js\n'
    '       • a test that no longer exists 1\n'
    '\n'
    'Test Suites: 1 failed, 1 total\n'
    'Tests:       1 failed, 1 passed, 2 total\n'
    'Snapshots:   1 obsolete, 1 passed, 1 total\n'
    'Time:        0.154 s\n'
    'Ran all test suites.\n'
)

JEST_OVER_SUMMARY_THRESHOLD = (
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: -1\n'
    '\n'
    "    > 1 | test('rejects a negative quantity', () => { expect(-1).toBe(0); });\n"
    '        |                                                        ^\n'
    '      2 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:1:56)\n'
    '\n'
    '\n'
    'Summary of all failing tests\n'
    'FAIL src/cart.test.js\n'
    '  ● rejects a negative quantity\n'
    '\n'
    '    expect(received).toBe(expected) // Object.is equality\n'
    '\n'
    '    Expected: 0\n'
    '    Received: -1\n'
    '\n'
    "    > 1 | test('rejects a negative quantity', () => { expect(-1).toBe(0); });\n"
    '        |                                                        ^\n'
    '      2 |\n'
    '\n'
    '      at Object.toBe (src/cart.test.js:1:56)\n'
    '\n'
    '\n'
    'Test Suites: 1 failed, 21 passed, 22 total\n'
    'Tests:       1 failed, 21 passed, 22 total\n'
    'Snapshots:   0 total\n'
    'Time:        0.611 s\n'
    'Ran all test suites.\n'
)


def _step(python, script, *args):
    """One gate step that runs `script` and nothing else - quoted, no operators.

    The shell is the product's, not this file's: `_shell` always goes through
    `sh -c`, so the string still has to survive one. Quoting each path is what
    makes a Windows interpreter path with a space in it survive that shell.
    """
    return " ".join('"%s"' % (part,) for part in (python, script) + args)


def _on_legacy_codec(run):
    """`run()`'s result, with every child it spawns writing through a cp1252
    stdout, and the caller's `PYTHONIOENCODING` restored afterwards.

    A fixture that stands in for a runner must write the bytes a runner writes;
    one printing through a text stream only fails where the codec cannot spell
    its output. Pinning the codec here measures that on every run, not only on
    the sweep's encoding pass, which a fast local sweep skips.
    """
    was = os.environ.get("PYTHONIOENCODING")
    os.environ["PYTHONIOENCODING"] = "cp1252"
    try:
        return run()
    finally:
        if was is None:
            os.environ.pop("PYTHONIOENCODING", None)
        else:
            os.environ["PYTHONIOENCODING"] = was


def _written(path):
    """How many bytes the survivor has written, or -1 when it never started.

    -1 rather than 0, because "the file is not there" and "the file is there and
    empty" are different findings and a case that merged them could not tell a
    grandchild that died from one that was never spawned.
    """
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def _pids_in(path):
    """The pids the helper recorded, or [] when it never got that far."""
    try:
        with open(path) as fh:
            return [int(tok) for tok in fh.read().split()]
    except Exception:                                          # noqa: BLE001
        return []


def _force_kill(pid):
    """Best-effort removal of a survivor. CLEANUP, never an assertion.

    Spelled per platform because there is no spelling that names a PID on both:
    `signal.SIGKILL` does not exist on windows, and `os.kill` there takes a
    process GROUP id for the two values it accepts at all.
    """
    if HAS_KILLPG:
        _harness.attempt(os.kill, pid, signal.SIGKILL)
    else:
        _harness.attempt(subprocess.run,
                         ["taskkill", "/F", "/PID", str(pid)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _recorded_rows(directory):
    """Every row in the evidence directory, in the order they landed.

    Read off the DISK rather than through `_evidence_io.read_rows`, because the
    question these cases put is what a reader of the committed file sees -- and a
    reader that went through the writer's own module could not tell a field that
    was never written from one the reader supplies.
    """
    rows = []
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _cases(check):
    # `_harness.fixture_root`, NOT a bare mkdtemp with a trailing rmtree. It is
    # the only spelling that survives windows: git writes its loose objects
    # READ-ONLY, and on windows the read-only attribute is checked on the FILE,
    # so `shutil.rmtree(..., ignore_errors=True)` leaves `.git/objects/**`
    # behind and leaves it behind SILENTLY. This suite once hand-rolled the pair
    # and CI's windows leg caught it through the sweep's own isolation guard -
    # the removal had simply never worked there.
    tmp = _harness.fixture_root("run-test-gate-selftest-")
    subprocess.run(["git", "init", "-q", tmp], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(tmp, "tracked.txt"), "w") as fh:
        fh.write("x\n")
    subprocess.run(["git", "-C", tmp, "add", "tracked.txt"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- the gate resolves through meta.buildCommands, once ----------------
    man = {"meta": {"version": 2,
                    "buildCommands": {"lint": "pre-commit run --all-files",
                                      "test": "pytest -q"}},
           "phases": [{"id": "P1", "title": "one", "status": "in_progress",
                       "testGate": ["lint", "test"], "tasks": []},
                      {"id": "P2", "title": "two", "status": "pending",
                       "testGate": [], "tasks": []},
                      {"id": "P3", "title": "three", "status": "pending",
                       "testGate": ["echo literal"], "tasks": []}]}
    cmds, _srcA, err = M.gate_of(man, "P1")
    check("rg1 the gate resolves each entry through meta.buildCommands, "
          "because a second resolution here would be a second answer to "
          "'what is this phase's gate': %r" % (cmds,),
          err is None
          and cmds == [("lint", "pre-commit run --all-files"),
                       ("test", "pytest -q")])
    cmds3, _srcB, _errB = M.gate_of(man, "P3")
    check("rg2 ...and an entry naming no build command is carried VERBATIM - "
          "it may be a literal shell command, and refusing it would make this "
          "script decide what a gate is allowed to be: %r" % (cmds3,),
          cmds3 == [("echo literal", "echo literal")])
    # `orchestrator.md` names `meta.nodePreamble` repeatedly, including "it
    # must run task.tests.gate (running meta.nodePreamble first, un-piped, if set)"
    # — and the script had ZERO occurrences of it. On a real run that cost two gate
    # rows recording exit 127, a PATH problem, as EVIDENCE: the committed ledger
    # carries two false failures for ever. A gate that records a false red is worse
    # than one that does not run.
    _pre_man = {"meta": dict(man["meta"],
                             nodePreamble="source ~/.nvm/nvm.sh && nvm use"),
                "phases": man["phases"]}
    _pre_cmds, _srcP, _errP = M.gate_of(_pre_man, "P1")
    check("rg1b every resolved command carries meta.nodePreamble in front, "
          "because the script spawns its own shell and a preamble the caller "
          "exported into a different one reaches nothing: %r" % (_pre_cmds,),
          _pre_cmds == [
              ("lint", "source ~/.nvm/nvm.sh && nvm use && "
                       "pre-commit run --all-files"),
              ("test", "source ~/.nvm/nvm.sh && nvm use && pytest -q")])
    check("rg1c ...joined with && rather than a pipe, which is what 'un-piped' "
          "in orchestrator.md is asking for - a pipe would hand the gate's exit "
          "code to the preamble's tail and lose the verdict entirely",
          all("|" not in c for _n, c in _pre_cmds), repr(_pre_cmds))
    check("rg1d ...and with NO preamble the command is untouched, so the "
          "overwhelming majority of manifests pay nothing for this",
          [c for _n, c in cmds] == ["pre-commit run --all-files", "pytest -q"],
          repr(cmds))
    _blank = {"meta": dict(man["meta"], nodePreamble="   "),
              "phases": man["phases"]}
    _blank_cmds, _sB, _eB = M.gate_of(_blank, "P1")
    check("rg1e ...and a preamble that is only whitespace is not one. Prefixing "
          "`   && ` would make every gate on that manifest exit 2 with a syntax "
          "error, which is the false-red this entry exists to stop",
          _blank_cmds == cmds, repr(_blank_cmds))
    _none, _srcC, err_none = M.gate_of(man, "P9")
    check("rg3 an unknown phase is an error rather than an empty gate - "
          "'this phase has no gate' and 'there is no such phase' are two "
          "different answers: %r" % (err_none,),
          _none is None and "no phase" in (err_none or ""))

    # --- the mutation bracket, against a REAL repository -------------------
    def _quiet(_project, _command, _timeout=None):
        return 0, "all good\n", {}

    res = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("rg4 a gate that changes nothing reports no mutation, and the basis "
          "says git was actually asked: %r"
          % ((res["treeMutated"], res["treeBasis"]),),
          res["treeMutated"] == [] and res["failed"] == []
          and res["treeBasis"].startswith("git described"))

    def _fix_in_place(project, _command, _timeout=None):
        # `isort`/`black`'s shape: it rewrites and then reports success.
        with open(os.path.join(project, "rewritten.py"), "w") as fh:
            fh.write("import os\n")
        return 0, "Passed\n", {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_fix_in_place)
    check("rg5 THE FAULT: a gate that passed BECAUSE it rewrote the tree is "
          "caught, with the file named - exit 0 said nothing was wrong and "
          "five source files had changed: %r" % (res["treeMutated"],),
          res["failed"] == []
          and any("rewritten.py" in line for line in res["treeMutated"]))
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg6 ...and it REFUSES regardless of the gate's own exit code, "
          "naming what to do - a measurement with side effects has answered a "
          "different question, and a commit on it carries work no task owns "
          "and no review saw: %r" % (text[:120],),
          code == M.E_FAIL and "GATE MUTATED THE TREE" in text
          and "Do NOT commit" in text)
    # Leave the fixture as it was: the next case asserts on a clean tree.
    os.remove(os.path.join(tmp, "rewritten.py"))

    # --- the bracket over a WHOLLY UNTRACKED directory ----------------------
    # A SEPARATE FIXTURE, and that is the point rather than tidiness. `tmp` above
    # holds nothing untracked, so every one of rg4-rg6 is green whether the
    # porcelain carries `-uall` or not -- which is how the flag came to be missing
    # here while three sibling readers passed it. What tells the two versions
    # apart is a subject tree with an untracked DIRECTORY in it before the
    # measurement window opens: the day-one shape of a repository nobody has
    # committed yet, and of a new source directory in one that has.
    unt = _harness.fixture_root("run-test-gate-untracked-")
    subprocess.run(["git", "init", "-q", unt], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(unt, "committed.txt"), "w") as fh:
        fh.write("base\n")
    for arg in (["add", "--", "committed.txt"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", unt] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(unt, "newdir"))
    with open(os.path.join(unt, "newdir", "already-here.txt"), "w") as fh:
        fh.write("present before the window\n")

    def _writes_into_untracked_dir(project, _command, _timeout=None):
        # The fix-in-place shape again, aimed where the collapsed porcelain hid
        # it: a file the gate CREATES inside a directory git has never tracked.
        with open(os.path.join(project, "newdir", "made-by-the-gate.txt"),
                  "w") as fh:
            fh.write("the gate wrote this\n")
        return 0, "Passed\n", {}

    res = M.run_gate(unt, [("lint", "pre-commit run --all-files")],
                     runner=_writes_into_untracked_dir)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("ud1 THE FAULT: a gate that CREATES a file inside a wholly untracked "
          "directory is caught and refused. Without `-uall` git collapses that "
          "directory to one `?? newdir/` entry, which is the SAME entry before "
          "and after - so the file appears in no diff, `treeMutated` comes back "
          "the empty list that means KNOWN CLEAN, and the run signs off carrying "
          "work the gate wrote: %r exit=%r" % (res["treeMutated"], code),
          any("newdir/made-by-the-gate.txt" in line
              for line in res["treeMutated"])
          and res["treeMutated"] != [] and res["failed"] == []
          and code == M.E_FAIL and "GATE MUTATED THE TREE" in text)
    os.remove(os.path.join(unt, "newdir", "made-by-the-gate.txt"))

    def _rewrites_untracked_file(project, _command, _timeout=None):
        with open(os.path.join(project, "newdir", "already-here.txt"),
                  "w") as fh:
            fh.write("REWRITTEN by the gate\n")
        return 0, "Passed\n", {}

    res = M.run_gate(unt, [("lint", "pre-commit run --all-files")],
                     runner=_rewrites_untracked_file)
    check("ud2 THE LIMIT `-uall` DOES NOT LIFT, pinned so the flag cannot be "
          "read as a fix for it: porcelain reports STATUS, never bytes, so a "
          "file that was ALREADY untracked keeps its one `?? newdir/"
          "already-here.txt` entry when the gate REWRITES it - identical before "
          "and after, with the flag exactly as without it. This bracket sees "
          "paths appearing and disappearing; `_tree_stamp.DIRTY_LIMIT` states "
          "the matching "
          "limit for an already-dirty TRACKED file. Asserted as the EMPTY LIST "
          "and not merely as falsy, because None here would be git having "
          "refused rather than this limit: %r" % (res["treeMutated"],),
          res["treeMutated"] == [] and res["treeMutated"] is not None)
    with open(os.path.join(unt, "newdir", "already-here.txt"), "w") as fh:
        fh.write("present before the window\n")

    res = M.run_gate(unt, [("lint", "true")], runner=_quiet)
    check("ud3 ...and an untracked directory the gate never touches still "
          "reports NO mutation. THE SECOND-DIRECTION CASE, and it looks vacuous "
          "on purpose: it is the one that goes red when the bracket learns to "
          "over-fire - a `-uall` reaching only the AFTER snapshot, or a delta "
          "widened past `after - before` - either of which accuses a gate of "
          "writing files that were sitting there when it started. rg4 cannot "
          "see that mutation at all, because its fixture has no untracked "
          "directory to expand: %r" % (res["treeMutated"],),
          res["treeMutated"] == [] and res["failed"] == []
          and res["treeBasis"].startswith("git described"))

    # --- whose writes did the bracket catch? --------------------------------
    # `_tree_stamp.porcelain` has no pathspec, so the bracket sees EVERY write in
    # its window and not only the gate's -- and `orchestrator.md` encourages
    # running tasks with disjoint `files` in parallel, which puts a sibling
    # executor's writes in that window as a matter of course. Measured live on a
    # project whose gates are all read-only: one run named a file owned by a
    # DIFFERENT task, another went red across dozens of paths and green on an
    # identical re-run. `GATE MUTATED THE TREE` refuses the commit step whatever
    # the gate's exit code says, so a false positive there halts a correct run.
    #
    # NO CASE ABOVE EXERCISES A CONCURRENT EXTERNAL WRITER, and that gap is
    # exactly why this was reachable: every mutation fixture in this file writes
    # from INSIDE the runner seam, which is the gate's own hand. `ow1` is the one
    # that writes something the work under test does not declare.
    own = _harness.fixture_root("run-test-gate-owned-")
    subprocess.run(["git", "init", "-q", own], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(own, "src"))
    os.makedirs(os.path.join(own, "other"))
    with open(os.path.join(own, "base.txt"), "w") as fh:
        fh.write("base\n")
    for arg in (["add", "--", "base.txt"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", own] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _sibling_writes(project, _command, _timeout=None):
        # A READ-ONLY gate -- `vitest run` names nothing it writes -- while a
        # parallel task's executor writes a file of ITS own. The bracket cannot
        # tell the two apart by timing, only by ownership.
        with open(os.path.join(project, "other", "sibling.ts"), "w") as fh:
            fh.write("written by somebody else\n")
        return 0, " Tests  3 passed (3)\n", {}

    res = M.run_gate(own, [("test", "npx vitest run")], runner=_sibling_writes,
                     owns=["src/mine.ts"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("ow1 THE FAULT: a read-only gate is not accused of a SIBLING's write. "
          "The changed path is not one the work under test declares, so it is "
          "reported as what it is -- something else is writing here -- and the "
          "commit-refusing verdict does NOT fire. Before this, a parallel run "
          "with disjoint files halted on a gate that had written nothing: %r"
          % ((res["treeMutatedOwned"], res["treeMutatedForeign"], code),),
          code == M.E_OK and res["treeMutatedOwned"] == []
          and any("other/sibling.ts" in ln for ln in res["treeMutatedForeign"])
          and "TREE CHANGED OUTSIDE THIS WORK" in text
          and "GATE MUTATED THE TREE" not in text
          and "no declared file changed" in text
          and "tree unchanged" not in text)
    os.remove(os.path.join(own, "other", "sibling.ts"))

    def _rewrites_own_subject(project, _command, _timeout=None):
        with open(os.path.join(project, "src", "mine.ts"), "w") as fh:
            fh.write("rewritten by the gate\n")
        return 0, "Tests:       2 passed, 2 total\n", {}

    res = M.run_gate(own, [("test", "npx jest")], runner=_rewrites_own_subject,
                     owns=["src/mine.ts"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("ow2 THE PAIRED POSITIVE, and it is the half that matters: a gate "
          "that rewrote the very file it was grading still says GATE MUTATED "
          "THE TREE and still refuses. A repair that classified everything as "
          "somebody else's would pass ow1 exactly as this does: %r"
          % ((res["treeMutatedOwned"], code),),
          code == M.E_FAIL and res["treeMutatedForeign"] == []
          and any("src/mine.ts" in ln for ln in res["treeMutatedOwned"])
          and "GATE MUTATED THE TREE" in text
          and "TREE CHANGED OUTSIDE THIS WORK" not in text)
    os.remove(os.path.join(own, "src", "mine.ts"))

    def _rewrites_both(project, _command, _timeout=None):
        for rel in (("src", "mine.ts"), ("other", "sibling.ts")):
            with open(os.path.join(project, *rel), "w") as fh:
                fh.write("x\n")
        return 0, "Tests:       2 passed, 2 total\n", {}

    res = M.run_gate(own, [("test", "npx jest")], runner=_rewrites_both,
                     owns=["src/mine.ts"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("ow3 ...and a window that caught BOTH says both, in two sentences "
          "with two responses -- the rule `render` already follows for a gate "
          "that failed and also rewrote the tree. One line refuses and the "
          "other reports, and folding them into one set would have to pick a "
          "meaning for paths that have two: %r" % (text[:80],),
          code == M.E_FAIL
          and len(res["treeMutatedOwned"]) == 1
          and len(res["treeMutatedForeign"]) == 1
          and "GATE MUTATED THE TREE" in text
          and "TREE CHANGED OUTSIDE THIS WORK" in text)
    for rel in (("src", "mine.ts"), ("other", "sibling.ts")):
        os.remove(os.path.join(own, *rel))

    _r_out, _r_for, _r_b = M.classify_mutations(
        ["R  src/mine.ts -> other/moved.ts"], ["src/mine.ts"])
    _r_out2, _r_for2, _r_b2 = M.classify_mutations(
        ["R  other/was.ts -> src/mine.ts"], ["src/mine.ts"])
    check("ow4 a RENAME is asked about BOTH of its names. `XY <old> -> <new>` "
          "takes a declared file away under one name and brings one back under "
          "another, and either half is the gate rewriting its own subject -- so "
          "a reader that kept only the name that exists now would hand the "
          "first of these to the half that merely reports: %r / %r"
          % (_r_out, _r_out2),
          _r_out == ["R  src/mine.ts -> other/moved.ts"] and _r_for == []
          and _r_out2 == ["R  other/was.ts -> src/mine.ts"] and _r_for2 == [])
    _q_out, _q_for, _q_b = M.classify_mutations(
        ['?? "src/caf\\303\\251.ts"'], ["src/café.ts"])
    check("ow5 ...and a path git QUOTED is unquoted before it is compared. Git "
          "spells a non-ASCII byte as a three-digit octal escape inside quotes, "
          "so a reader that only stripped the quotes would compare "
          "`caf\\303\\251.ts` against `café.ts`, find no match, and hand a "
          "declared file to the reporting half in silence: %r" % (_q_out,),
          _q_out == ['?? "src/caf\\303\\251.ts"'] and _q_for == [])
    _n_out, _n_for, _n_basis = M.classify_mutations([" M a.py"], [])
    check("ow6 THE SECOND DIRECTION: with NO declared files there is no "
          "ownership to sort by, so both halves are None and the basis says "
          "which -- never an empty `foreign`, which would read as 'nothing was "
          "attributed to the gate' and silence rg5 and ud1 outright. `render` "
          "then attributes the whole set to the gate, the direction a guard may "
          "be wrong in: %r" % ((_n_out, _n_for, _n_basis),),
          _n_out is None and _n_for is None
          and "declares no files" in _n_basis)
    res = M.run_gate(own, [("test", "npx jest")], runner=_rewrites_own_subject,
                     owns=["src/mine.ts"])
    check("ow7 the ownership answer rides on `treeBasis`, the string the LEDGER "
          "and the report already render -- not on a fourth key that would "
          "reach the terminal and none of the three surfaces where a committed "
          "row is read: %r" % (res["treeBasis"],),
          "git described the tree" in res["treeBasis"]
          and "declared by the work under test" in res["treeBasis"])
    with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                           "audit-plan.schema.json"), encoding="utf-8") as fh:
        _gm_enum = ((((json.load(fh).get("$defs") or {}).get("testEvidence")
                      or {}).get("properties") or {})
                    .get("status") or {}).get("enum") or []
    check("ow8 THE FAULT: a gate that passed every command AND rewrote "
          "the file it was grading records `gate-mutated` and NEVER `passed`. "
          "`run_status` took no tree argument and had no tree arm, so this "
          "exact run - the one ow2 shows refusing at the terminal - cached "
          "`passed` onto `task.testEvidence`, where `--fail-on failing-tests` "
          "read it and signed the work off. The record outlives the exit code, "
          "which makes it the worse half: %r"
          % ((res["status"], res["treeMutatedOwned"]),),
          res["status"] == M.GATE_MUTATED
          and res["status"] != "passed"
          # ...and the word is one the PLAN SCHEMA declares, asked of the schema
          # rather than retyped: a status the enum does not carry is a pointer
          # `ajv` refuses, so a verdict spelled only here would be written and
          # then rejected by the validator that guards every manifest write.
          and M.GATE_MUTATED in _gm_enum
          and res["failed"] == [])
    os.remove(os.path.join(own, "src", "mine.ts"))
    res_sib = M.run_gate(own, [("test", "npx vitest run")],
                         runner=_sibling_writes, owns=["src/mine.ts"])
    check("ow9 SECOND DIRECTION, and it is the one an always-firing repair "
          "fails: the SIBLING's write leaves the verdict `passed`. The foreign "
          "half is the half nothing can attribute, and refusing on it is "
          "what halted correct runs, so the word reads the same list `render` "
          "refuses on and not `treeMutated`: %r"
          % ((res_sib["status"], res_sib["treeMutatedForeign"]),),
          res_sib["status"] == "passed"
          and res_sib["treeMutatedOwned"] == []
          and res_sib["treeMutatedForeign"] != [])
    os.remove(os.path.join(own, "other", "sibling.ts"))

    def _fails_and_rewrites(project, _command, _timeout=None):
        with open(os.path.join(project, "src", "mine.ts"), "w") as fh:
            fh.write("rewritten by a gate that also went red\n")
        return 1, "Tests:       1 failed, 2 total\n", {}

    res_fm = M.run_gate(own, [("test", "npx jest")], runner=_fails_and_rewrites,
                        owns=["src/mine.ts"])
    lines = []
    M.render(res_fm, out=lines.append)
    check("ow10 THE PRECEDENCE, UPWARDS: a gate that came back RED and also "
          "rewrote its subject stays `failed`. `gate-mutated` claims the "
          "commands answered green, so every word denying that outranks it - "
          "and nothing is lost, because `render` still prints the rewrite as "
          "its own sentence beside the red one: %r"
          % ((res_fm["status"], res_fm["treeMutatedOwned"]),),
          res_fm["status"] == "failed"
          and res_fm["treeMutatedOwned"] != []
          and "GATE RED" in "\n".join(lines)
          and "GATE MUTATED THE TREE" in "\n".join(lines))
    os.remove(os.path.join(own, "src", "mine.ts"))

    def _skips_and_rewrites(project, _command, _timeout=None):
        with open(os.path.join(project, "src", "mine.ts"), "w") as fh:
            fh.write("rewritten by a hook that skipped every check\n")
        return 0, ("check yaml.....................Skipped\n"
                   "black.........................Skipped\n"), {}

    res_zm = M.run_gate(own, [("lint", "pre-commit run --files src/mine.ts")],
                        runner=_skips_and_rewrites, owns=["src/mine.ts"])
    check("ow11 ...and `no-checks` outranks it at the other end, for the same "
          "one reason: a reader told the gate rewrote the tree would believe "
          "checks had run, and positively zero ran. Both facts still reach "
          "them - the count is on the row and the paths are in `treeMutated`: "
          "%r" % ((res_zm["status"], res_zm["ranTotal"],
                   res_zm["treeMutatedOwned"]),),
          res_zm["status"] == "no-checks" and res_zm["ranTotal"] == 0
          and res_zm["treeMutatedOwned"] != [])
    os.remove(os.path.join(own, "src", "mine.ts"))
    _ok4, _why4 = _harness.attempt(M.run_status, [], [], None, None, [])
    check("ow12 `run_status` takes the refused list AND the unattributable one "
          "WITH NO DEFAULT, so a "
          "caller that forgets it is a TypeError rather than a run silently "
          "spelled `passed`. That is not defensiveness: an argument nobody has "
          "to pass is how a mutated-tree run once got recorded `passed`, and "
          "this is the arm that stops it coming back. %r" % (_why4,),
          _ok4 is False and _why4.startswith("TypeError:")
          # ...and the complete call still answers, so the case above is a
          # missing ARGUMENT and not a function that raises whatever it is given.
          and M.run_status([], [], None, None, [], None) == "passed")
    _am_ref, _am_rep = M.attributed_mutations(None, None, None)
    _am_ref2, _am_rep2 = M.attributed_mutations([" M a.py"], None, None)
    _am_ref3, _am_rep3 = M.attributed_mutations(
        [" M src/mine.ts", " M other/x.ts"], [" M src/mine.ts"],
        [" M other/x.ts"])
    check("ow13 `attributed_mutations` is the ONE expression the verdict, the "
          "terminal and `--json` now share. No comparison refuses nothing (a "
          "comparison nobody made cannot refuse); no ownership charges the "
          "WHOLE set to the gate, which is what this verdict did before the "
          "split existed and the direction a guard may be wrong in; and a "
          "sorted window hands each half to the reader that may act on it: "
          "%r" % ((_am_ref, _am_ref2, _am_ref3, _am_rep3),),
          (_am_ref, _am_rep) == ([], [])
          and (_am_ref2, _am_rep2) == ([" M a.py"], [])
          and _am_ref3 == [" M src/mine.ts"] and _am_rep3 == [" M other/x.ts"])

    # --- the other failure mode: nothing ran -------------------------------
    def _all_skipped(_project, _command, _timeout=None):
        return 0, ("check yaml.....................Skipped\n"
                   "black.........................Skipped\n"), {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                     runner=_all_skipped)
    check("rg7 THE OTHER FAULT: a gate where every hook SKIPPED is exit 0 "
          "with zero checks, and the count is read rather than assumed: %r"
          % (res["ranTotal"],),
          res["failed"] == [] and res["treeMutated"] == []
          and res["ranTotal"] == 0)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg8 ...and that is REFUSED too, said as what it is: a gate that "
          "skipped everything and a gate that verified everything are the "
          "same exit code: %r" % (text[:110],),
          code == M.E_FAIL and "NO CHECK RAN" in text)

    def _two_ran(_project, _command, _timeout=None):
        return 0, ("check yaml.....................Passed\n"
                   "black.........................Passed\n"
                   "mypy..........................Skipped\n"), {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_two_ran)
    check("rg9 a run where some hooks executed counts THOSE and not the "
          "skipped one - the paired positive, since a counter that always "
          "answered zero would pass rg7 exactly as the repair does: %r"
          % (res["ranTotal"],),
          res["ranTotal"] == 2)
    lines = []
    check("rg10 ...and it renders GREEN, carrying the count so the reader "
          "sizes the verdict: %r" % (lines,),
          M.render(res, out=lines.append) == M.E_OK
          and "GATE GREEN" in "\n".join(lines)
          and "2 check(s) ran" in "\n".join(lines))

    # --- an unknown runner must not be guessed at -------------------------
    res = M.run_gate(tmp, [("test", "pytest -q")], runner=_quiet)
    check("rg11 a runner that does NOT report its step count yields None, "
          "never zero - guessing zero would refuse a passing gate and "
          "guessing one would bless a skipped one: %r" % (res["ranTotal"],),
          res["ranTotal"] is None)
    lines = []
    check("rg12 ...and that renders as not-knowable rather than as a number, "
          "so the limit is stated instead of filled in: %r" % (lines,),
          M.render(res, out=lines.append) == M.E_OK
          and "not knowable from this runner" in "\n".join(lines))

    # --- the count vocabulary was one entry wide ---------------------------
    # `_STEP_WORDS` held `pre-commit` and nothing else, so jest, vitest, mocha
    # and pytest all answered "not knowable" to "how many ran" -- which made the
    # `NO CHECK RAN` branch, and the whole "gates could NOT run" distinction
    # `orchestrator.md` step 4c prescribes, unreachable for every real test
    # runner. Measured live: `mongodb-memory-server` could not bind a port in a
    # sandbox, the suite died at exit 48 with no test executed, and the ledger
    # recorded GATE RED with the task's name on it.
    check("ct1 jest is counted from its own summary, and from the words that "
          "mean a check EXECUTED rather than from `N total` -- jest's total "
          "includes SKIPPED tests, so reading it would bless the gate that "
          "skipped everything -- the same no-checks failure as pre-commit's, "
          "one runner along: %r"
          % (M.summary_count("Tests:  1 failed, 2 skipped, 3 passed, 6 total\n"),),
          M.summary_count("Tests:  1 failed, 2 skipped, 3 passed, 6 total\n") == 4
          and M.summary_count("Tests:       0 total\n") == 0)
    check("ct2 vitest is read off `Tests`, never off `Test Files` -- files are "
          "not checks -- and its own `no tests` is a POSITIVE zero rather than "
          "a runner this cannot read: %r"
          % ((M.summary_count(" Test Files  2 passed (2)\n"
                              "      Tests  1 failed | 4 passed (5)\n"),
              M.summary_count("      Tests  no tests\n")),),
          M.summary_count(" Test Files  2 passed (2)\n"
                          "      Tests  1 failed | 4 passed (5)\n") == 5
          and M.summary_count(" Test Files  1 passed (1)\n"
                              "      Tests  no tests\n") == 0)
    check("ct3 mocha prints its summary across SEPARATE lines, so every match "
          "is joined before the pairs are read out of it -- and `pending` is "
          "counted by neither, because a pending test did not run: %r"
          % (M.summary_count("\n  5 passing (23ms)\n  1 failing\n  2 pending\n"),),
          M.summary_count("\n  5 passing (23ms)\n  1 failing\n  2 pending\n") == 6
          and M.summary_count("\n  0 passing (1ms)\n") == 0)
    check("ct4 pytest is read decorated AND bare -- `-q` drops the `=` rule "
          "entirely -- and both of its zero shapes are POSITIVE zeros: `no "
          "tests ran` collected nothing, and `1 error` is a test that never "
          "started, which is the exact distinction that separates a positive "
          "zero from `None`: %r"
          % ((M.summary_count("1 failed, 2 passed in 0.03s\n"),
              M.summary_count("==== no tests ran in 0.01s ====\n"),
              M.summary_count("==== 1 error in 0.01s ====\n")),),
          M.summary_count("1 failed, 2 passed in 0.03s\n") == 3
          and M.summary_count("===== 3 passed in 0.12s =====\n") == 3
          and M.summary_count("==== no tests ran in 0.01s ====\n") == 0
          and M.summary_count("==== 1 error in 0.01s ====\n") == 0)
    check("ct5 THE RULE THE WIDENING HAD TO KEEP: a runner this still cannot "
          "read answers None and NEVER zero. Returning 0 for 'I did not "
          "recognise this output' would refuse every passing gate whose runner "
          "is not in the table: %r"
          % (M.summary_count("/repo/src/a.ts\n  1:1  error  x\n"
                             "1 problem (1 error, 0 warnings)\n"),),
          M.summary_count("/repo/src/a.ts\n1 problem (1 error, 0 warnings)\n")
          is None
          and M.summary_count("Done in 1.53s.\n") is None
          and M.summary_count("") is None)
    check("ct6 the summary is matched on the OUTPUT and not on the command, "
          "which is the half `_STEP_WORDS` cannot do: a gate entry is as often "
          "`npm test` or `make check` as it is the runner's name, and the "
          "summary line is the runner's signature either way: %r"
          % (M.ran_count("npm test", "Tests:       4 passed, 4 total\n"),),
          M.ran_count("npm test", "Tests:       4 passed, 4 total\n") == 4
          and M.ran_count("make check", "\n  7 passing (9ms)\n") == 7)
    check("ct7 ...and `_STEP_WORDS` is still asked FIRST, so a `pre-commit` "
          "gate wrapping a test hook keeps counting HOOKS and not the tests "
          "inside one of them. Two counters over one text is a number that "
          "changes meaning with the reader that got there first: %r"
          % (M.ran_count("pre-commit run --all-files",
                         "pytest................Passed\n"
                         "1 failed, 2 passed in 0.03s\n"),),
          M.ran_count("pre-commit run --all-files",
                      "pytest................Passed\n"
                      "1 failed, 2 passed in 0.03s\n") == 1)

    # --- a gate that COULD NOT RUN is not a gate that FAILED ----------------
    def _sandbox_died(_project, _command, _timeout=None):
        # The live shape: the port could not be bound, the suite died, and jest
        # still printed its summary -- reporting zero tests.
        return 48, ("MongoMemoryServer: Instance failed to start\n"
                    "Test Suites: 1 failed, 1 total\n"
                    "Tests:       0 total\n"), {}

    res_nr = M.run_gate(tmp, [("test", "npx jest")], runner=_sandbox_died)
    check("nr1 THE FAULT: a step that exited NON-ZERO having run ZERO checks is "
          "an INFRASTRUCTURE failure, not this work's. It was recorded `failed` "
          "with the task's name on a committed row, because the step carried no "
          "outcome and `failed` sits at the top of the precedence: %r"
          % ((res_nr["status"], res_nr["failed"], res_nr["ranTotal"]),),
          res_nr["status"] == M.CANNOT_RUN and res_nr["failed"] == []
          and res_nr["steps"][0].get("outcome") == M.CANNOT_RUN
          and res_nr["ranTotal"] == 0)

    def _real_red(_project, _command, _timeout=None):
        return 1, "Tests:       1 failed, 3 passed, 4 total\n", {}

    res_red = M.run_gate(tmp, [("test", "npx jest")], runner=_real_red)
    check("nr2 THE PAIRED POSITIVE: a suite that RAN and came back non-zero is "
          "still `failed`, and the task still owns it. A repair that read the "
          "exit code alone would pass nr1 by calling every red gate "
          "infrastructure: %r" % ((res_red["status"], res_red["ranTotal"]),),
          res_red["status"] == "failed" and res_red["failed"] == ["test"]
          and res_red["ranTotal"] == 4)
    res_skip = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                          runner=_all_skipped)
    check("nr3 ...and the other direction: exit ZERO with zero checks is still "
          "`no-checks` and not infrastructure. A rule reading only the count "
          "would swallow a skipped-everything gate into a word that names "
          "a different repair: %r" % (res_skip["status"],),
          res_skip["status"] == "no-checks"
          and res_skip["steps"][0].get("outcome") is None)
    check("nr4 ...and a count that is None does not earn it either. `None == 0` "
          "is False rather than a branch to write, and 'the runner does not "
          "say' is not evidence that nothing ran: %r"
          % ((M.never_started(1, None, None), M.never_started(1, 0, None),
              M.never_started(0, 0, None),
              M.never_started(1, 0, M.TIMED_OUT)),),
          M.never_started(1, 0, None) is True
          and M.never_started(1, None, None) is False
          and M.never_started(0, 0, None) is False
          and M.never_started(1, 0, M.TIMED_OUT) is False)
    lines = []
    code = M.render(res_nr, out=lines.append)
    text = "\n".join(lines)
    check("nr5 AND `render` HAD NO ARM FOR IT AT ALL, which is what made the "
          "widening dangerous rather than merely incomplete: with `failed` "
          "empty, the tree clean and the status already reading `could-not-run`, "
          "this printed GATE GREEN and exited 0. A false red became a false "
          "GREEN, which is strictly the worse of the two: %r" % (text[-90:],),
          code == M.E_FAIL and "GATE COULD NOT RUN" in text
          and "GATE GREEN" not in text and "NO CHECK RAN" not in text)

    def _stalled(_project, _command, timeout=None):
        return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}

    lines = []
    code = M.render(M.run_gate(tmp, [("test", "pytest -q")], runner=_stalled),
                    out=lines.append)
    check("nr6 ...and the same hole was under `timed-out`, so it is closed in "
          "the same place. A run stopped at its bound printed GATE GREEN too, "
          "and no gate in this file could see it because nothing rendered a "
          "timed-out run: %r" % ("\n".join(lines)[-80:],),
          code == M.E_FAIL and "GATE TIMED OUT" in "\n".join(lines)
          and "GATE GREEN" not in "\n".join(lines))

    # --- the count ships with the basis that explains it --------------------
    check("cb1 `countsBasis` is WRITTEN. `_evidence_io.row_for` has copied it "
          "into every row since the ledger existed and nothing ever set it, so "
          "each committed row carried null there and the panel printed a "
          "hard-coded sentence in its place -- a three-valued count shipped "
          "without the basis that explains its unknown arm: %r"
          % (res_red.get("countsBasis"),),
          "summary line" in (res_red.get("countsBasis") or ""))
    def _one_counts(_project, command, _timeout=None):
        if "jest" in command:
            return 0, "Tests:  2 passed, 2 total\n", {}
        return 0, "no findings\n", {}

    res_mixed = M.run_gate(tmp, [("a", "npx jest"), ("b", "eslint .")],
                           runner=_one_counts)
    check("cb2 ...and a MIXED gate says the total is a FLOOR and not a size. "
          "`ranTotal` sums the steps that ANSWERED, so a reader holding the "
          "number alone cannot tell a partial count from a complete one, and "
          "the step that printed no summary is NAMED: %r"
          % ((res_mixed["ranTotal"], res_mixed["countsBasis"]),),
          res_mixed["ranTotal"] == 2
          and "floor and not a size" in (res_mixed["countsBasis"] or "")
          and "b" in (res_mixed["countsBasis"] or ""))
    res_silent = M.run_gate(tmp, [("test", "make check")], runner=_quiet)
    check("cb3 ...and with nothing countable at all the basis says WHICH steps "
          "printed no summary, rather than leaving `ranTotal: null` to be read "
          "as a bug in the gate: %r"
          % ((res_silent["ranTotal"], res_silent["countsBasis"]),),
          res_silent["ranTotal"] is None
          and "not knowable" in (res_silent["countsBasis"] or "")
          and "test" in (res_silent["countsBasis"] or ""))

    # --- P46.5: a total that added a suite to itself ----------------------
    # REPORTED FROM A LIVE AUDIT. `meta.buildCommands` mapped one entry to a
    # plain runner invocation and another to the SAME runner with coverage on.
    # The gate ran both, the identical checks executed twice, and the TOTAL was
    # the suite counted twice - which the operator and the reviewer both read as
    # thoroughness. On a later sign-off the plain step passed and the coverage
    # step came back RED on the identical checks, a flaky index-build race: the
    # duplicate step could only agree with the other or be flaky, so it could
    # only cost. These cases are about the total and about the per-step wall
    # clock that makes a doubled run visible on the first green gate anybody
    # reads.
    def _vitest_plain(_project, _command, _timeout=None):
        return 0, (" src/cart.test.js (12)\n"
                   "Tests  12 passed (12)\n"), {}

    def _vitest_cover(_project, _command, _timeout=None):
        # THE SAME SUITE, AND A DIFFERENT SET OF PRINTED PATHS. `--coverage`
        # adds a table naming the SOURCES under the suite, so a comparison over
        # everything the runner printed would call these two different runs -
        # which is why `suite_paths` narrows before comparing.
        return 0, (" src/cart.test.js (12)\n"
                   "Tests  12 passed (12)\n"
                   " % Coverage report\n"
                   " src/cart.js      |   91.2 |\n"), {}

    def _vitest_other(_project, _command, _timeout=None):
        return 0, (" src/user.test.js (12)\n"
                   "Tests  12 passed (12)\n"), {}

    def _pytest_quiet(_project, _command, _timeout=None):
        # A REAL COUNT FROM A RUNNER THAT NAMED NO SUITE. `-q` prints the
        # arithmetic and no file at all, which is the state where "same suite"
        # can be suspected and not established.
        return 0, "=== 12 passed in 0.30s ===\n", {}

    check("sc1 THE COMPARISON IS OVER THE SUITES A RUNNER SAYS IT RAN, not over "
          "every path it printed. A coverage table names the SOURCES under a "
          "suite, so a set comparison over the whole output would report one "
          "suite run twice as two different runs - and the narrowing is asked "
          "of `_is_suite_path`, which this file already uses for the same "
          "question: %r"
          % ((sorted(M.suite_paths(M.files_named(
              " src/cart.test.js (12)\n src/cart.js | 91.2 |\n"))),
              sorted(M.suite_paths(M.files_named("no paths here\n")) or ())),),
          M.suite_paths(M.files_named(
              " src/cart.test.js (12)\n src/cart.js | 91.2 |\n"))
          == frozenset(["src/cart.test.js"])
          and M.suite_paths(M.files_named("=== 12 passed in 0.30s ===\n"))
          == frozenset())

    def _two_spellings(_project, command, _timeout=None):
        return (_vitest_cover if "coverage" in command
                else _vitest_plain)(_project, command)

    res_dup = M.run_gate(tmp, [("unit", "npx vitest run"),
                               ("unit-cov", "npx vitest run --coverage")],
                         runner=_two_spellings)
    check("sc2 A GATE THAT RUNS ONE SUITE TWICE REPORTS THE SUITE'S SIZE, not "
          "twice it. The reported run printed the sum and both the operator and "
          "the reviewer read it as thoroughness - the number that should have "
          "exposed the duplication is the number that concealed it: %r"
          % ((res_dup["ranTotal"],
              [(g["verdict"], g["names"], g["ran"]) for g in
               res_dup["sharedCounts"]]),),
          res_dup["ranTotal"] == 12
          and [g["verdict"] for g in res_dup["sharedCounts"]] == [M.SAME_SUITE]
          and res_dup["sharedCounts"][0]["names"] == ["unit", "unit-cov"]
          and res_dup["sharedCounts"][0]["files"] == ["src/cart.test.js"])

    lines = []
    code_dup = M.render(res_dup, out=lines.append)
    text_dup = "\n".join(lines)
    check("sc3 ...and the PARTS are printed beside the total, naming both steps "
          "and the suite they share. A total on its own cannot be argued with; "
          "the parts are what let a reader see the second step buys nothing and "
          "costs a re-run every time that suite is flaky: %r"
          % (text_dup,),
          code_dup == M.E_OK and "SAME SUITE COUNTED ONCE" in text_dup
          and "unit, unit-cov" in text_dup and "src/cart.test.js" in text_dup
          and "12 check(s) ran" in text_dup
          and "24 check(s) ran" not in text_dup)

    def _one_quiet(_project, command, _timeout=None):
        return (_pytest_quiet if "pytest" in command
                else _vitest_plain)(_project, command)

    res_maybe = M.run_gate(tmp, [("unit", "npx vitest run"),
                                 ("api", "pytest -q")], runner=_one_quiet)
    lines = []
    code_maybe = M.render(res_maybe, out=lines.append)
    text_maybe = "\n".join(lines)
    check("sc4 WHERE IT CANNOT BE ESTABLISHED IT IS NOT ASSERTED, and the count "
          "is still ADDED. A step that named no suite could be the same run as "
          "the other or a different one of equal size, and silently dropping it "
          "would delete a real measurement to avoid a suspected duplicate - the "
          "same lie in the other direction: %r"
          % ((res_maybe["ranTotal"],
              [(g["verdict"], g["names"], g["silent"]) for g in
               res_maybe["sharedCounts"]]),),
          res_maybe["ranTotal"] == 24
          and [g["verdict"] for g in res_maybe["sharedCounts"]] == [M.MAYBE_SAME]
          and res_maybe["sharedCounts"][0]["silent"] == ["api"]
          and "SAME SUITE NOT ESTABLISHED" in text_maybe
          and "MAY be one suite run twice" in text_maybe
          and "24 check(s) ran" in text_maybe
          # NEITHER NEW LINE IS A REFUSAL, and that is the half
          # `reference/orchestrator.md` had to be able to state: a duplicated
          # or unresolved count costs wall clock and exposure to flakiness,
          # and neither is evidence about the work under test. `sc3` holds the
          # same boundary for the line that DOES change the total.
          and code_maybe == M.E_OK)

    def _two_suites(_project, command, _timeout=None):
        return (_vitest_other if "user" in command
                else _vitest_plain)(_project, command)

    res_diff = M.run_gate(tmp, [("cart", "npx vitest run src/cart.test.js"),
                                ("user", "npx vitest run src/user.test.js")],
                          runner=_two_suites)
    lines = []
    code_diff = M.render(res_diff, out=lines.append)
    text_diff = "\n".join(lines)
    check("sc5 THE ALLOW CASE, AND IT IS THE ONE THIS FUNCTION IS GRADED ON: "
          "two DIFFERENT suites of equal size are added, and nothing is said "
          "about them. Equal counts are ordinary, so a version that collapsed "
          "on the count alone would under-report every such gate - a total that "
          "is too small, which looks like caution and is the harder lie to "
          "notice: %r" % ((res_diff["ranTotal"], res_diff["sharedCounts"]),),
          res_diff["ranTotal"] == 24 and res_diff["sharedCounts"] == []
          and "SAME SUITE" not in text_diff
          and "SAME COUNT" not in text_diff
          and "24 check(s) ran" in text_diff and code_diff == M.E_OK)

    res_zero = M.run_gate(tmp, [("a", "pre-commit run --all-files"),
                                ("b", "pre-commit run --all-files")],
                          runner=_all_skipped)
    check("sc6 A ZERO IS NEVER GROUPED. It is additively identical either way, "
          "so a group over it could only put a second sentence on a run "
          "`NO CHECK RAN` already owns end to end - and that banner, not this, "
          "is what refuses it: %r"
          % ((res_zero["ranTotal"], res_zero["sharedCounts"]),),
          res_zero["ranTotal"] == 0 and res_zero["sharedCounts"] == []
          and res_zero["status"] == "no-checks")

    check("sc7 ...and the finding reaches the COMMITTED row, not only the "
          "terminal. `countsBasis` is what the ledger, the report and the panel "
          "already render, so the clause rides there rather than in a fourth "
          "field that would reach a terminal and none of the three: %r"
          % ((res_dup["countsBasis"], res_maybe["countsBasis"]),),
          "ONCE and is not added" in (res_dup["countsBasis"] or "")
          and "unit-cov" in (res_dup["countsBasis"] or "")
          and "may be one suite twice" in (res_maybe["countsBasis"] or "")
          and "floor and not a size" not in (res_dup["countsBasis"] or ""))

    check("sc8 the duration is spelled in the unit a reader COMPARES two steps "
          "in, and a step carrying no duration says so rather than printing a "
          "zero nobody measured: %r"
          % ([M.human_duration(v) for v in (0, 940, 1500, 125000, None, -1)],),
          M.human_duration(0) == "0 ms" and M.human_duration(940) == "940 ms"
          and M.human_duration(1500) == "1.5 s"
          and M.human_duration(125000) == "2 m 05 s"
          and M.human_duration(None) is None and M.human_duration(-1) is None)
    check("sc8b ...and the name here IS `_fmt`'s function rather than a second "
          "one agreeing with it today: the rendered report prints the same "
          "field now, and an identity is the only assertion a later copy "
          "cannot pass",
          M.human_duration is _rtg_fmt.human_duration)

    check("sc9 EVERY STEP'S LINE CARRIES WHAT THAT STEP COST. `durationMs` was "
          "recorded per step and for the run since this script existed and the "
          "terminal printed neither, so a gate running one suite twice looked "
          "exactly like a gate running two, and 'where does the time go' needed "
          "somebody to decide to go and measure it: %r" % (lines[:2],),
          all(("ms" in ln or " s" in ln) for ln in text_diff.splitlines()[:2])
          and "(not timed)" not in text_diff)
    lines = []
    M.render({"steps": [{"name": "u", "exit": 0, "ran": 3}], "failed": [],
              "treeMutated": [], "treeBasis": "b", "ranTotal": 3,
              "sharedCounts": [], "overlap": None, "coverageBasis": ""},
             out=lines.append)
    check("sc10 ...and a step whose duration was NOT recorded says that, rather "
          "than borrowing the zero a missing key reads as. A fabricated `0 ms` "
          "on a step nobody timed is the shape every other answer in this file "
          "refuses: %r" % (lines[:1],),
          "(not timed)" in lines[0] and "0 ms" not in lines[0])

    check("sc11 ...and the three-way count vocabulary is untouched by the "
          "arithmetic above it. A step whose runner publishes no summary is "
          "still NOT KNOWABLE and never zero, the total over a mixed gate is "
          "still a floor, and a de-duplicated gate is still `passed`: %r"
          % ((res_silent["ranTotal"], res_mixed["ranTotal"],
              res_dup["status"], res_dup["steps"][1]["measured"]),),
          res_silent["ranTotal"] is None
          and "not knowable" in (res_silent["countsBasis"] or "")
          and res_mixed["ranTotal"] == 2
          and "floor and not a size" in (res_mixed["countsBasis"] or "")
          and res_dup["status"] == "passed"
          and res_dup["steps"][1]["measured"] == M.MEASURED_CHECKS)

    # --- render_quiet prints failures and totals, never a plain pass -------
    _res_mixed_render = {
        "steps": [
            {"name": "ok-step", "exit": 0, "ran": 5, "durationMs": 120},
            {"name": "bad-step", "exit": 1, "ran": 5, "durationMs": 80,
             "failing": ["FAIL: something broke"], "failingBasis": "b"}],
        "failed": ["bad-step"], "treeMutated": [], "treeBasis": "b",
        "ranTotal": 10, "sharedCounts": [], "overlap": None,
        "coverageBasis": ""}
    _loud_lines, _quiet_lines = [], []
    _loud_code = M.render(_res_mixed_render, out=_loud_lines.append)
    _quiet_code = M.render_quiet(_res_mixed_render, out=_quiet_lines.append)
    _loud_text, _quiet_text = "\n".join(_loud_lines), "\n".join(_quiet_lines)
    check("rq1 THE LOUD FORM prints a line for a step that simply passed, "
          "unchanged: %r" % (_loud_text,),
          "ok-step" in _loud_text and "exit 0" in _loud_text)
    check("rq2 THE QUIET FORM drops that line - a plain pass has nothing left "
          "to say once the totals below already say the run came back clean: "
          "%r" % (_quiet_text,),
          "ok-step" not in _quiet_text)
    check("rq3 ...and keeps the FAILING step's line and its failing detail IN "
          "FULL, exactly as the loud form does - the shape this task is about "
          "is one line per PASSING file, never a failure: %r" % (_quiet_text,),
          "bad-step" in _quiet_text and "FAIL: something broke" in _quiet_text
          and "bad-step" in _loud_text
          and "FAIL: something broke" in _loud_text)
    check("rq4 THE VERDICT ITSELF DOES NOT MOVE: both forms return the same "
          "exit code and print the identical GATE RED banner - a quiet run is "
          "a second spelling of one run and not a second run: %r"
          % ((_loud_code, _quiet_code),),
          _loud_code == _quiet_code
          and "GATE RED: bad-step" in _loud_text
          and "GATE RED: bad-step" in _quiet_text)

    _res_retried = {
        "steps": [{"name": "flaky", "exit": 0, "ran": 4, "durationMs": 50,
                   "retryBasis": "retried after SIGTERM once"}],
        "failed": [], "treeMutated": [], "treeBasis": "b", "ranTotal": 4,
        "sharedCounts": [], "overlap": None, "coverageBasis": ""}
    _rq_lines = []
    M.render_quiet(_res_retried, out=_rq_lines.append)
    check("rq5 OVER-FIRE GUARD: a step that passed on a RETRY is not a plain "
          "pass, so the quiet form must not drop its own inventory line (the "
          "one carrying ITS exit, ran count and duration, distinct from the "
          "retry banner every form prints) - a quiet form that widened this "
          "far would be hiding a finding rather than an inventory: %r"
          % (_rq_lines,),
          any("flaky" in ln and "exit" in ln for ln in _rq_lines))

    # --- did the step measure anything, said as a word --------------------
    # THE READING, RECORDED WHERE IT WAS TAKEN. Reported from the field: three
    # rows brought as "false reds", two of them withdrawn on the raw evidence
    # because they were real failures. The step that had genuinely produced no
    # verdict about the tests was the one whose count was zero, and the two that
    # were red for cause had counts in the thousands - so the column that
    # separated them was already on every row, as an integer-or-null each reader
    # had to turn into a three-way answer for themselves. These cases are about
    # the word that takes that derivation away from the reader, and about the
    # verdict NOT moving while it is introduced.
    check("ms1 the three answers stay apart, and the one that must never merge "
          "is None against zero: a runner that publishes no count has not told "
          "us that nothing ran, and `not ran` is the spelling that says it did: "
          "%r" % ([M.measured_state(v) for v in (4, 1, 0, None)],),
          M.measured_state(4) == M.MEASURED_CHECKS
          and M.measured_state(1) == M.MEASURED_CHECKS
          and M.measured_state(0) == M.MEASURED_NOTHING
          and M.measured_state(None) == M.MEASURED_UNKNOWN
          and M.MEASURED_NOTHING != M.MEASURED_UNKNOWN)
    check("ms2 THE FIELD'S OWN ROW: a step that exited non-zero having "
          "collected nothing carries `nothing` BESIDE its `ran`, where a reader "
          "of the committed row meets it without doing the arithmetic again - "
          "and the paired positive is the row that was withdrawn, a suite that "
          "came back red having really measured: %r"
          % ([(s["name"], s["exit"], s["ran"], s.get("measured"))
              for s in (res_nr["steps"][0], res_red["steps"][0])],),
          res_nr["steps"][0]["ran"] == 0
          and res_nr["steps"][0].get("measured") == M.MEASURED_NOTHING
          and res_red["steps"][0]["ran"] == 4
          and res_red["steps"][0].get("measured") == M.MEASURED_CHECKS)
    check("ms3 ...and the observation moves NO verdict, which is the boundary "
          "of this change. `failed` is still `failed` and the red gate still "
          "names its step: the word says what was measured, and what a gate is "
          "worth needs a second fact - whether the failure is attributable to "
          "this work - that nothing here has: %r"
          % ((res_red["status"], res_red["failed"], res_nr["status"],
              res_nr["failed"], res_skip["status"]),),
          res_red["status"] == "failed" and res_red["failed"] == ["test"]
          and res_nr["status"] == M.CANNOT_RUN and res_nr["failed"] == []
          # ...and the gate that SKIPPED everything keeps the word that names
          # its own repair. `no-checks` is exit 0 with a positive zero, which is
          # the same observation as the row above and a different verdict, so a
          # status arm reading this word would swallow one into the other.
          and res_skip["status"] == "no-checks")

    def _red_unreadable(_project, _command, _timeout=None):
        # A real red from a runner no reader in the file can count: eslint's
        # shape, which `summary_count` answers None to by design.
        return 1, "/repo/src/a.ts\n1 problem (1 error, 0 warnings)\n", {}

    res_unread = M.run_gate(tmp, [("lint", "eslint .")], runner=_red_unreadable)
    check("ms4 THE OVER-FIRE DIRECTION: a runner that merely does not REPORT a "
          "count is `not-knowable` and never `nothing`. Reading it as nothing "
          "would print 'this step measured nothing' over a suite that may have "
          "measured everything, and it would say it of every runner outside the "
          "summary table rather than of a rare one. The gate is still red, "
          "which is the half a reader acts on: %r"
          % ((res_unread["steps"][0]["ran"],
              res_unread["steps"][0].get("measured"), res_unread["status"],
              res_unread["failed"]),),
          res_unread["steps"][0]["ran"] is None
          and res_unread["steps"][0].get("measured") == M.MEASURED_UNKNOWN
          and res_unread["status"] == "failed"
          and res_unread["failed"] == ["lint"])
    _ident = {"runId": "run-measured", "ts": "2026-09-12T00:00:00Z"}
    _rows = [_ev_io.row_for(tmp, r, "phase", {"phaseId": "P1"}, _ident)
             for r in (res_red, res_nr, res_unread)]
    check("ms5 ...and every one of the answers CROSSES INTO THE ROW, which is "
          "the half `_evidence_io.STEP_KEYS` decides: a key the allow-list does "
          "not name is dropped silently, so the word would exist in memory for "
          "the length of the run and be absent from the only copy anybody reads "
          "afterwards: %r"
          % ([r["steps"][0].get("measured") for r in _rows],),
          "measured" in _ev_io.STEP_KEYS
          and [r["steps"][0].get("measured") for r in _rows]
          == [M.MEASURED_CHECKS, M.MEASURED_NOTHING, M.MEASURED_UNKNOWN]
          # ...beside the number it was read from, never instead of it: the
          # basis for this word IS `ran`, and a row carrying the reading alone
          # would be a claim whose evidence stayed behind.
          and [r["steps"][0].get("ran") for r in _rows] == [4, 0, None])

    # --- fl: a red gate says WHICH checks failed ---------------------------
    # THE COST, reported three times by two projects: a red row carried the
    # status, the failing gate ENTRY names and a check count, and nothing about
    # which TESTS failed. Both operators built their own failing-test reporter
    # around the gate, and one recovered the names twice out of a project
    # artefact the next run overwrites - so the obvious reflex, re-run and read
    # the output, destroys the evidence. The text was in hand the whole time and
    # was thrown away, which is why this is a carrying problem and not a parsing
    # one.
    check("fl0 the two tables are ONE table's worth of runners. A failure "
          "reader for a runner whose summary cannot be counted would name "
          "failures beside `check count not knowable from this runner` - a "
          "claim with no measurement under it - and a counting reader with no "
          "failure reader falls silently through to a tail: %r"
          % (sorted(M._FAILURE_READERS),),
          set(M._FAILURE_READERS)
          == set(name for name, _re, _words in M._SUMMARY_READERS))

    # The readers moved to `_runner_output` so a second entry point can share
    # them; the gate keeps a NAME for each and no table of its own. Identity,
    # not equality: an equal copy is the second table this pins against.
    _shared = [(name, getattr(M, name, None) is getattr(_ro, name))
               for name in ("_SUMMARY_PAIR", "_CSI_TEXT", "_SUMMARY_READERS",
                            "summary_reader", "summary_readers",
                            "summary_count", "_FAILURE_READERS",
                            "JEST_EXEC_ERROR", "_JEST_SUITE_HEADER", "_ANSI",
                            "jest_failures", "_VITEST_FAIL_LINE")]
    check("ro1 the gate's runner readers ARE `_runner_output`'s objects - no "
          "summary or failure table is defined here: %r"
          % ([n for n, ok in _shared if not ok],),
          all(ok for _n, ok in _shared))

    _jest_red = (
        " FAIL  src/checkout/total.test.ts\n"
        "  ● totals > applies the bulk discount\n\n"
        "    expected 90 received 100\n"
        "  ● Console\n\n"
        "    console.log debug noise\n"
        "  ● cart > rejects a negative quantity\n\n"
        "Tests:       2 failed, 7 passed, 9 total\n")
    _named, _basis = M.failing_lines(_jest_red, _ev_io.MAX_FAILING)
    check("fl1 a jest run names the CHECKS that failed, and the basis says the "
          "names were read from jest's own failure lines rather than guessed. "
          "`● Console` is a console dump under the same bullet and is not "
          "one of them: %r" % ((_named, _basis),),
          _named == ["totals > applies the bulk discount",
                     "cart > rejects a negative quantity"]
          and "jest" in _basis and "failure lines" in _basis)

    _others = {
        "vitest": ("❯ src/cart.test.ts (5)\n"
                   "   × cart > rejects a negative quantity\n"
                   "FAIL  src/cart.test.ts > cart > rejects a negative "
                   "quantity\n"
                   " Tests  1 failed | 4 passed (5)\n"),
        "mocha": ("  5 passing (23ms)\n"
                  "  1 failing\n\n"
                  "  1) cart rejects a negative quantity:\n"
                  "     AssertionError\n"),
        "pytest": ("FAILED tests/test_cart.py::test_negative - AssertionError\n"
                   "ERROR tests/test_boot.py\n"
                   "=== 1 failed, 2 passed in 0.12s ===\n"),
    }
    _read = dict((k, M.failing_lines(v, _ev_io.MAX_FAILING))
                 for k, v in _others.items())
    check("fl2 ...and so does every other runner the summary table counts, each "
          "off the mark that runner actually prints - a cross and a `FAIL` line "
          "for vitest, a NUMBERED failure for mocha, the short summary for "
          "pytest. `ERROR` is read for pytest although `error` is deliberately "
          "absent from its COUNTING words: a collection error is not a check "
          "that ran and is still the thing to fix: %r"
          % (dict((k, v[0]) for k, v in _read.items()),),
          _read["vitest"][0] == ["cart > rejects a negative quantity",
                                 "src/cart.test.ts > cart > rejects a negative "
                                 "quantity"]
          and _read["mocha"][0] == ["cart rejects a negative quantity:"]
          and _read["pytest"][0] == ["tests/test_cart.py::test_negative - "
                                     "AssertionError", "tests/test_boot.py"]
          and all("tail" not in v[1] for v in _read.values()))

    _make_red = ("building object files\n"
                 "src/parse.c:44:9: error: implicit declaration\n"
                 "make: *** [build/parse.o] Error 1\n")
    _tail, _tail_basis = M.failing_lines(_make_red, _ev_io.MAX_FAILING)
    check("fl3 a runner NONE of the readers recognises gets a capped tail of its "
          "output instead of silence, and the basis says so IN SO MANY WORDS - a "
          "reader who could not tell a tail from a list of names would read a "
          "stack frame as a test name: %r" % ((_tail[-1:], _tail_basis),),
          _tail == _make_red.strip().split("\n")
          and "NOT a list of failing checks" in _tail_basis
          and "no runner this gate can count" in _tail_basis)

    _quiet_jest = "Tests:       1 failed, 8 passed, 9 total\n"
    _q_lines, _q_basis = M.failing_lines(_quiet_jest, _ev_io.MAX_FAILING)
    check("fl4 A RECOGNISED RUNNER THAT NAMED NOTHING FALLS TO THE TAIL TOO, "
          "which is the arm that keeps this from being the same defect one "
          "branch in: an empty list because jest was recognised and printed no "
          "bullet hands the operator a red verdict and no text, which is exactly "
          "what they already had. The basis names the runner AND says the lines "
          "are not failing checks: %r" % ((_q_lines, _q_basis),),
          _q_lines == [_quiet_jest.strip()]
          and "jest" in _q_basis
          and "NOT a list of failing checks" in _q_basis)

    _many = "".join("  ● suite > case %d\n" % (n,)
                    for n in range(_ev_io.MAX_FAILING + 3))
    _cut, _cut_basis = M.failing_lines(
        _many + "Tests:  13 failed, 13 total\n", _ev_io.MAX_FAILING)
    check("fl5 THE CAP IS REAL AND THE ROW SAYS SO. A row is hash-chained, so a "
          "field with unbounded content is a row with unbounded size; the list "
          "is cut to `_evidence_io.MAX_FAILING` and the basis carries both "
          "counts, because a truncation nobody announced reads as 'that is all "
          "there was': %r" % ((len(_cut), _cut_basis),),
          len(_cut) == _ev_io.MAX_FAILING
          and _cut[0] == "suite > case 0"
          and ("%d of the %d" % (_ev_io.MAX_FAILING,
                                 _ev_io.MAX_FAILING + 3)) in _cut_basis
          and "not carried" in _cut_basis)

    def _mixed_gate(_project, command, _timeout=None):
        # The green step's runner is RECOGNISED too, so the case turns on the
        # exit code and not on whether anything could have been parsed.
        if "vitest" in command:
            return 0, " Tests  3 passed (3)\n", {}
        return 1, _jest_red, {}

    res_fl = M.run_gate(tmp,
                        [("test", "npx jest"), ("green", "npx vitest run")],
                        runner=_mixed_gate)
    _by_name = dict((s["name"], s) for s in res_fl["steps"])
    check("fl6 ALLOW, AND THE DIRECTION AN OVER-FIRING VERSION BREAKS IN: the "
          "step that came back ZERO carries neither key. The claim is 'here is "
          "what went wrong in this step', and a green step has nothing to say "
          "under it - so a version that carried a tail there would put an "
          "arbitrary slice of a passing runner's output into a committed row on "
          "every run this plugin ever records: %r"
          % (sorted(k for k in _by_name["green"] if k.startswith("failing")),),
          "failing" not in _by_name["green"]
          and "failingBasis" not in _by_name["green"]
          and _by_name["test"]["failing"]
          == ["totals > applies the bulk discount",
              "cart > rejects a negative quantity"]
          # ...and it is an OBSERVATION beside the verdict, never a second
          # verdict: the status word and the failing ENTRY list are what they
          # were before the names existed.
          and res_fl["status"] == "failed" and res_fl["failed"] == ["test"])

    lines = []
    code_fl = M.render(res_fl, out=lines.append)
    text_fl = "\n".join(lines)
    check("fl7 ...and `render` prints them UNDER THE STEP, which is the only "
          "place a per-step fact needs no attribution written beside it - and "
          "RAW, where the row's copy is redacted: a terminal belongs to the "
          "operator whose machine the paths name, and a path rewritten to the "
          "outside token is one they cannot open: %r" % (text_fl[:90],),
          code_fl == M.E_FAIL
          and "      totals > applies the bulk discount" in text_fl
          and "      basis: the 2 check(s) jest named as failing" in text_fl
          # ...above the verdict banners rather than among them:
          # `reference/orchestrator.md` keys its arms on those literal lines.
          and text_fl.index("basis: the 2 check(s)")
          < text_fl.index("GATE RED"))

    # --- and when that zero moves the verdict ------------------------------
    # THE ROW THAT SURVIVED. Of the three "false reds" the operator brought, two
    # were withdrawn on the raw evidence - real failures with counts in the
    # thousands. The third was a task gate whose typecheck exited non-zero and
    # whose jest step collected nothing, run in a tree a SIBLING EXECUTOR was
    # editing at the same time: `tsc` compiles the whole program, so a
    # half-written file belonging to another task fails it regardless of whose
    # file it is.
    #
    # AND ITS `treeMutated` WAS EMPTY, which is what made it unreadable. The
    # mutation bracket compares before to after, the sibling's file was ALREADY
    # half-written when the gate started, so nothing moved inside the window and
    # the row said KNOWN CLEAN. The evidence was in the BEFORE snapshot, which no
    # verdict looked at.
    attrib = _harness.fixture_root("run-test-gate-attribution-")
    subprocess.run(["git", "init", "-q", attrib], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(attrib, "src"))
    os.makedirs(os.path.join(attrib, "other"))
    with open(os.path.join(attrib, "base.txt"), "w") as fh:
        fh.write("base\n")
    for arg in (["add", "--", "base.txt"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", attrib] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _sibling_half = os.path.join(attrib, "other", "sibling.ts")

    def _reported_gate(_project, command, _timeout=None):
        # The two steps of the reported row. `tsc --noEmit` prints diagnostics
        # and no summary any reader here can count, so its `ran` is None; jest
        # with nothing to collect prints a positive zero at a non-zero exit.
        if "tsc" in command:
            return 2, ("other/sibling.ts(2,1): error TS1005: '}' expected.\n"
                       "Found 1 error.\n"), {}
        return 1, "Tests:       0 total\nNo tests found, exiting with code 1\n", {}

    _gate_cmds = [("typecheck", "tsc --noEmit"), ("test", "npx jest")]
    with open(_sibling_half, "w") as fh:
        fh.write("export const half = {\n")
    res_ua = M.run_gate(attrib, _gate_cmds, runner=_reported_gate,
                        owns=["src/mine.ts"])
    lines = []
    code_ua = M.render(res_ua, out=lines.append)
    text_ua = "\n".join(lines)
    check("ua1 THE FAULT: a gate that MEASURED NOTHING and came back red, in a "
          "tree that already carried changes outside the declared scope, is "
          "`could-not-run` and not `failed`. The word costs no retry and signs "
          "nothing off, which is the pair of things this run has earned: %r"
          % ((res_ua["status"], res_ua["failed"], res_ua["notAttributable"]),),
          res_ua["status"] == M.CANNOT_RUN
          # ...and the steps keep their own answers, which is what makes the
          # excuse checkable rather than a mute: the red step is still named.
          and res_ua["failed"] == ["typecheck"]
          and res_ua["notAttributable"] == ["?? other/sibling.ts"]
          and res_ua["ranTotal"] == 0)
    check("ua2 ...and the bracket that was SUPPOSED to see this saw nothing. "
          "`treeMutated` is the EMPTY LIST - the value that means known clean - "
          "because the sibling's file was already half-written when the run "
          "started, so it moved no line between the two snapshots. The fact is "
          "in the BEFORE snapshot and nowhere else, and that is the whole "
          "difference between this condition and `classify_mutations`: %r"
          % ((res_ua["treeMutated"], res_ua["notAttributable"]),),
          res_ua["treeMutated"] == [] and res_ua["treeMutatedForeign"] == []
          and res_ua["notAttributable"])
    check("ua3 ...and the terminal says the same word as the record. `GATE RED` "
          "is gone, the banner is the literal `reference/orchestrator.md` keys "
          "its infrastructure arm on - which is how this member costs no retry, "
          "the script touching `attempts` nowhere - and the line under it names "
          "the paths that were already dirty: %r" % (text_ua[:120],),
          code_ua == M.E_FAIL
          and "GATE COULD NOT RUN" in text_ua and "GATE RED" not in text_ua
          and "do not spend a retry" in text_ua
          and "other/sibling.ts" in text_ua
          and "typecheck" in text_ua.split("GATE COULD NOT RUN")[1]
          # ...and the zero does not get the sentence that calls it exit 0.
          and "NO CHECK RAN" not in text_ua
          and "basis:" in text_ua)

    os.remove(_sibling_half)
    res_clean = M.run_gate(attrib, _gate_cmds, runner=_reported_gate,
                           owns=["src/mine.ts"])
    lines = []
    code_clean = M.render(res_clean, out=lines.append)
    text_clean = "\n".join(lines)
    check("ua4 THE CASE THAT MUST NOT MOVE, and it is the whole reason the "
          "condition has two halves: the SAME gate, measuring the same nothing, "
          "on a tree nobody else was writing to, is still `failed` and still "
          "says GATE RED. A task whose own test file does not compile collects "
          "nothing too, and excusing that records no verdict, spends no retry "
          "and hides the defect: %r"
          % ((res_clean["status"], res_clean["notAttributable"],
              res_clean["attributionBasis"]),),
          res_clean["status"] == "failed" and res_clean["failed"] == ["typecheck"]
          and res_clean["notAttributable"] is None
          and res_clean["attributionBasis"] is None
          and "GATE RED" in text_clean and code_clean == M.E_FAIL)

    def _own_file_broken(_project, command, _timeout=None):
        # THE HONEST RED IN ITS PUREST SHAPE: the work's OWN half-written file,
        # named by its OWN typecheck, with the suite collecting nothing after
        # it. Every clause of the condition is satisfied except the ownership
        # split, so this is the case that goes red the moment that split stops
        # being asked.
        if "tsc" in command:
            return 2, "src/mine.ts(2,1): error TS1005: '}' expected.\n", {}
        return 1, "Tests:       0 total\nNo tests found\n", {}

    with open(os.path.join(attrib, "src", "mine.ts"), "w") as fh:
        fh.write("export const mine = {\n")
    res_owndirt = M.run_gate(attrib, _gate_cmds, runner=_own_file_broken,
                             owns=["src/mine.ts"])
    check("ua5 ...and dirt this work DECLARES excuses nothing either, which is "
          "the same rule read off the other half of the split. The tree is "
          "dirty, nothing was measured, and the only uncommitted file is the "
          "work's own - so there is nobody else to attribute the red to and the "
          "word stays `failed`: %r"
          % ((res_owndirt["status"], res_owndirt["notAttributable"],
              M.dirty_outside(M._tree_stamp.porcelain(attrib), ["src/mine.ts"])),),
          res_owndirt["status"] == "failed"
          and res_owndirt["notAttributable"] is None
          and M.dirty_outside(M._tree_stamp.porcelain(attrib), ["src/mine.ts"])[0] == [])
    os.remove(os.path.join(attrib, "src", "mine.ts"))

    with open(_sibling_half, "w") as fh:
        fh.write("export const half = {\n")
    res_noscope = M.run_gate(attrib, _gate_cmds, runner=_reported_gate, owns=[])
    _no_paths, _no_basis = M.dirty_outside(M._tree_stamp.porcelain(attrib), [])
    check("ua6 THE OVER-FIRE DIRECTION: with NO declared files every dirty path "
          "is trivially 'outside the declared scope', so a reader taking the "
          "empty scope for foreign dirt would excuse every failing run on every "
          "dirty tree - real failures turned into infrastructure, in a "
          "hash-chained row. Nothing is attributed where nothing can be: %r"
          % ((res_noscope["status"], _no_paths, _no_basis),),
          res_noscope["status"] == "failed"
          and res_noscope["notAttributable"] is None
          and _no_paths is None and "declares no files" in _no_basis)

    def _red_with_checks(_project, command, _timeout=None):
        # The two rows the operator WITHDREW: red for cause, having really
        # measured. The tree is as dirty as ua1's and this must stay `failed`.
        if "tsc" in command:
            return 2, "src/mine.ts(2,1): error TS1005: '}' expected.\n", {}
        return 1, "Tests:       3 failed, 1200 passed, 1203 total\n", {}

    res_measured = M.run_gate(attrib, _gate_cmds, runner=_red_with_checks,
                              owns=["src/mine.ts"])
    check("ua7 ...and a red that MEASURED is untouched by a dirty tree. The two "
          "rows withdrawn from the report came back red having run checks in "
          "the thousands, and the column that separated them from ua1 was the "
          "count - so a condition reading the tree alone would have excused "
          "them all: %r"
          % ((res_measured["status"], res_measured["ranTotal"],
              res_measured["notAttributable"]),),
          res_measured["status"] == "failed"
          and res_measured["ranTotal"] == 1203
          and res_measured["notAttributable"] is None)

    def _red_uncountable(_project, _command, _timeout=None):
        # eslint's shape: a real red from a runner no reader here can count. It
        # NAMES the dirty foreign file, so the only thing keeping this red is
        # the count - which is the arm this case is about.
        return 1, "other/sibling.ts\n  2:1  error  Parsing error\n", {}

    res_unknown = M.run_gate(attrib, [("lint", "eslint .")],
                             runner=_red_uncountable, owns=["src/mine.ts"])
    check("ua8 ...and NOT-KNOWABLE is not nothing, on this condition as on "
          "every other one in the file. `ranTotal is None` means no runner in "
          "this gate published a count, which is not evidence that nothing ran "
          "- and reading it as one would excuse every red from every runner "
          "outside the summary table whenever anything else was dirty: %r"
          % ((res_unknown["ranTotal"], res_unknown["steps"][0].get("measured"),
              res_unknown["status"]),),
          res_unknown["ranTotal"] is None
          and res_unknown["steps"][0].get("measured") == M.MEASURED_UNKNOWN
          and res_unknown["status"] == "failed"
          and res_unknown["notAttributable"] is None)

    def _skips_everything(_project, _command, _timeout=None):
        return 0, ("check yaml.....................Skipped\n"
                   "black.........................Skipped\n"), {}

    res_zero_green = M.run_gate(attrib, [("lint", "pre-commit run --all-files")],
                                runner=_skips_everything, owns=["src/mine.ts"])
    lines = []
    M.render(res_zero_green, out=lines.append)
    check("ua9 ...and `failed` is the ONLY word this displaces. A gate that "
          "came back green having measured nothing is `no-checks` - it blames "
          "nobody and names its own repair, the gate skipped everything - and a "
          "tree somebody else made dirty explains none of that. The excuse is "
          "asked only where there is a red to attribute: %r"
          % ((res_zero_green["status"], res_zero_green["ranTotal"],
              res_zero_green["notAttributable"]),),
          res_zero_green["status"] == "no-checks"
          and res_zero_green["notAttributable"] is None
          and "NO CHECK RAN" in "\n".join(lines))

    _ua_row = _ev_io.row_for(attrib, res_ua, "task",
                             {"phaseId": "P1", "taskId": "P1.1"},
                             {"runId": "run-attrib", "ts": "2026-09-13T00:00:00Z"})
    _clean_row = _ev_io.row_for(attrib, res_clean, "task",
                                {"phaseId": "P1", "taskId": "P1.1"},
                                {"runId": "run-clean",
                                 "ts": "2026-09-13T00:00:00Z"})
    check("ua10 ...and the BASIS crosses into the committed row, because this "
          "is the one member of the class the row cannot be read back for: "
          "`steps[].outcome` carries the members a step observes and "
          "`testedState.dirtyBasis` counts the dirty paths without saying whose "
          "they were, so a `could-not-run` recorded here would have arrived "
          "with nothing under it. Written only where there is something to "
          "write, like `cancelledBy`: %r"
          % ((_ua_row.get("attributionBasis"),
              "attributionBasis" in _clean_row),),
          "other/sibling.ts" in (_ua_row.get("attributionBasis") or "")
          and _ua_row.get("status") == M.CANNOT_RUN
          # ...and the raw path list does NOT, which is the division `treeBasis`
          # already makes: the bounded sentence is what a reader needs and an
          # unbounded list is what a committed row may not grow.
          and "notAttributable" not in _ua_row
          and "attributionBasis" not in _clean_row
          and _clean_row.get("status") == "failed")

    # THE SHAPE THAT REACHES THE NEW ARMS, and the mutation battery is what
    # found it missing. In every case above, the step that collected nothing
    # also exited non-zero, so `never_started` had already put `could-not-run`
    # on it - and the status arm, the banner and the `NO CHECK RAN` suppression
    # were all satisfied by that EXISTING member before this one was consulted.
    # Deleting each of the three new branches left the suite green. Here the
    # zero comes back at exit 0, so no step carries an outcome at all and the
    # run-level condition is the only thing that can move anything.
    def _red_then_silent_zero(_project, command, _timeout=None):
        if "tsc" in command:
            return 2, "other/sibling.ts(2,1): error TS1005: '}' expected.\n", {}
        return 0, "Tests:       0 total\n", {}

    res_runlevel = M.run_gate(attrib, _gate_cmds, runner=_red_then_silent_zero,
                              owns=["src/mine.ts"])
    lines = []
    code_rl = M.render(res_runlevel, out=lines.append)
    text_rl = "\n".join(lines)
    check("ua11 a run whose steps each carry NO outcome of their own still "
          "moves: the zero came back at exit 0, so nothing inferred "
          "`could-not-run` for a step, and the red belongs to a step that "
          "published no count. The word, the banner and the retry sentence "
          "come from the run-level condition or from nowhere: %r"
          % ((res_runlevel["status"],
              [st.get("outcome") for st in res_runlevel["steps"]],
              res_runlevel["failed"], code_rl),),
          res_runlevel["status"] == M.CANNOT_RUN
          and [st.get("outcome") for st in res_runlevel["steps"]] == [None, None]
          and res_runlevel["failed"] == ["typecheck"] and code_rl == M.E_FAIL
          and "GATE COULD NOT RUN" in text_rl and "GATE RED" not in text_rl
          and "do not spend a retry" in text_rl
          # ...and the zero is not handed the sentence that calls it exit 0.
          # One step here really did exit 0 and the other exited 2, so `NO CHECK
          # RAN: ... That is exit 0` would be false of the run it described.
          and "NO CHECK RAN" not in text_rl)

    os.remove(_sibling_half)
    res_rl_clean = M.run_gate(attrib, _gate_cmds, runner=_red_then_silent_zero,
                              owns=["src/mine.ts"])
    lines = []
    code_rlc = M.render(res_rl_clean, out=lines.append)
    check("ua12 ...and the same run on a tree nobody else was writing to is "
          "`failed` and says GATE RED, which is the half a repair that always "
          "fires would take away. Both of these reach the new arms; only one of "
          "them may come out of them: %r"
          % ((res_rl_clean["status"], res_rl_clean["notAttributable"],
              code_rlc),),
          res_rl_clean["status"] == "failed"
          and res_rl_clean["notAttributable"] is None
          and code_rlc == M.E_FAIL and "GATE RED" in "\n".join(lines)
          and "GATE COULD NOT RUN" not in "\n".join(lines))

    # THE THIRD CONJUNCT, AND IT WAS MEASURED RATHER THAN REASONED. Driven end
    # to end on a scratch project, the SECOND run of this gate was excused by
    # the FIRST run's own bookkeeping: the manifest pointer, the evidence ledger
    # and the journal are dirty, undeclared by any task, and incapable of
    # failing a typecheck. `reference/orchestrator.md` step 2 makes that the
    # normal state rather than an accident - it edits the phase's manifest file
    # before the executor is spawned - so a rule reading tree state alone
    # excuses every red that measured nothing and ua4 becomes unreachable in the
    # real workflow. The dirty path has to be one the RUN ITSELF BLAMED.
    with open(os.path.join(attrib, "other", "bookkeeping.json"), "w") as fh:
        fh.write("{\"attempts\": 2}\n")
    res_ambient = M.run_gate(attrib, _gate_cmds, runner=_red_then_silent_zero,
                             owns=["src/mine.ts"])
    _amb_paths, _amb_basis = M.dirty_outside(M._tree_stamp.porcelain(attrib),
                                             ["src/mine.ts"])
    check("ua13 ...and dirt the run NEVER NAMED excuses nothing, which is what "
          "keeps ua4 reachable outside a fixture. The tree carries an "
          "undeclared file - the shape the orchestrator's own `attempts` edit "
          "has at every gate run - and no step's output mentions it, so there "
          "is no evidence tying the red to it and the red stands: %r"
          % ((res_ambient["status"], _amb_paths,
              res_ambient["notAttributable"]),),
          res_ambient["status"] == "failed"
          and res_ambient["notAttributable"] is None
          # ...and the path really WAS foreign dirt, so the case is about the
          # naming arm and not about a tree that happened to be clean.
          and _amb_paths == ["?? other/bookkeeping.json"])
    with open(_sibling_half, "w") as fh:
        fh.write("export const half = {\n")
    res_blamed = M.run_gate(attrib, _gate_cmds, runner=_red_then_silent_zero,
                            owns=["src/mine.ts"])
    check("ua14 ...and the PAIRED POSITIVE separates the two in one tree: with "
          "both files dirty and undeclared, only the one the typecheck printed "
          "is carried. A repair that handed over the whole foreign set would "
          "pass ua1 exactly as this does and would name a file nothing blamed: "
          "%r" % ((res_blamed["status"], res_blamed["notAttributable"]),),
          res_blamed["status"] == M.CANNOT_RUN
          and res_blamed["notAttributable"] == ["?? other/sibling.ts"]
          # ...and the basis keeps the two apart rather than merging them: the
          # whole foreign set is what was dirty, and the tail is the part the
          # run blamed. A reader gets both and can tell which is which.
          and "bookkeeping" in (res_blamed["attributionBasis"] or "")
          and "bookkeeping" not in
          (res_blamed["attributionBasis"] or "").split("the run named")[-1]
          and "sibling.ts" in
          (res_blamed["attributionBasis"] or "").split("the run named")[-1])
    os.remove(os.path.join(attrib, "other", "bookkeeping.json"))
    os.remove(_sibling_half)

    # --- a failing gate, and both facts at once ---------------------------
    def _fail_and_rewrite(project, _command, _timeout=None):
        with open(os.path.join(project, "also.py"), "w") as fh:
            fh.write("x = 1\n")
        return 1, "Failed\n", {}

    res = M.run_gate(tmp, [("lint", "pre-commit run --all-files")],
                     runner=_fail_and_rewrite)
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("rg13 a gate that failed AND rewrote the tree says both - a reader "
          "who only fixed the failure would meet the rewrite next: %r"
          % (text[:100],),
          code == M.E_FAIL and "GATE RED" in text
          and "GATE MUTATED THE TREE" in text)
    os.remove(os.path.join(tmp, "also.py"))

    # --- git that cannot answer is UNKNOWN, not clean ---------------------
    notrepo = _harness.fixture_root("run-test-gate-norepo-")
    if True:
        res = M.run_gate(notrepo, [("lint", "true")], runner=_quiet)
        check("rg14 where git cannot describe the tree, mutation is UNKNOWN - "
              "and unknown is None, NOT an empty list. The empty list was the "
              "conflation: it reads as 'nothing changed' to every truthy test, "
              "so the third state survived only in the prose beside it: %r"
              % ((res["treeMutated"], res["treeBasis"]),),
              res["treeMutated"] is None
              and res["treeBasis"].startswith("git could not"))
        lines = []
        M.render(res, out=lines.append)
        check("rg15 ...and the basis is printed, so a green verdict over an "
              "unaskable tree carries its own limit",
              "git could not describe the tree" in "\n".join(lines))

    # --- did the run touch anything the work declares? ----------------------
    # The third way a gate says nothing, after doing too much and doing nothing.
    # Measured live: a UI vitest suite, two files, nine tests, all green, against
    # a diff that was a one-value edit to a JSON manifest. Exit 0, a real
    # NON-ZERO count, and no relationship between what ran and what changed --
    # which is why `ranTotal` could not catch it and needed a fact of its own.
    #
    # REPORTED, NEVER REFUSED, and that was the operator's decision taken with
    # both options named. The overlap comes from paths a runner HAPPENS to print,
    # so it is a heuristic; a heuristic that refuses manufactures false refusals,
    # and the exit code deliberately does not read it.
    def _vitest_green(_project, _command, _timeout=None):
        return 0, ("\u2713 tools/ui-tests/panel.test.js (5 tests)\n"
                   "\u2713 tools/ui-tests/report.test.js (4 tests)\n"
                   "Test Files  2 passed (2)\n"), {}

    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=["docs/audit/audit-plan.json"])
    check("cv1 THE FAULT: a gate that RAN, passed, and named nothing the work "
          "owns is reported as exactly that - the count is non-zero, so the "
          "zero-check rule cannot see it: %r"
          % ((res["overlap"], res["coverageBasis"]),),
          res["failed"] == [] and res["overlap"] == []
          and "the runner named" in res["coverageBasis"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("cv2 ...printed with its basis, and NOT refused - exit stays 0, "
          "because refusing on a heuristic would make this script decide what a "
          "gate may be, which its own header declines: %r" % (text[-160:],),
          code == M.E_OK and "NO OVERLAP WITH THIS WORK" in text
          and "the runner named" in text)
    # THE PAIRED POSITIVE, and it is the half that matters: a renderer that
    # printed the warning unconditionally would pass cv1 and cv2 exactly as the
    # repair does.
    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=["tools/ui-tests/panel.test.js", "docs/plan.json"])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("cv3 a run that DOES name a declared file says so instead, and names "
          "which - the warning is conditional, which a warning printed on every "
          "run would not be: %r" % ((res["overlap"], text[-120:]),),
          code == M.E_OK
          and res["overlap"] == ["tools/ui-tests/panel.test.js"]
          and "NO OVERLAP" not in text and "coverage: 1 declared file" in text)

    def _no_paths(_project, _command, _timeout=None):
        return 0, "OK\n9 tests passed\n", {}

    res = M.run_gate(tmp, [("test", "make check")], runner=_no_paths,
                     owns=["docs/audit/audit-plan.json"])
    lines = []
    M.render(res, out=lines.append)
    check("cv4 a runner that prints NO paths yields not-knowable, never 'no "
          "overlap' - `porcelain`'s rule one question over, and the difference "
          "between a measurement and a claim: %r" % (res["coverageBasis"],),
          res["overlap"] is None
          and "not knowable from its output" in "\n".join(lines)
          and "NO OVERLAP" not in "\n".join(lines))
    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=[])
    check("cv5 ...and work declaring no files is the same answer for the other "
          "reason, said as itself: there is nothing to relate a run TO, which is "
          "not the same as a run that covered nothing: %r"
          % (res["coverageBasis"],),
          res["overlap"] is None and "declares no files" in res["coverageBasis"])
    # Two field reports disagreed about `NO OVERLAP` and both were right
    # about their own run: one saw it on 9 of 12 tasks because jest prints SUITE
    # paths while `task.files` lists the sources under them; the other called this
    # line the best thing in the plugin because eslint and tsc named real files and
    # none was the Markdown that task owned. The repair is the MATCH, and these two
    # cases are the pair - quieten the first without preserving the second and the
    # feature is gone.
    _hit, _b = M.coverage(["src/parser.ts", "src/other.ts"],
                          set(["tests/parser.spec.ts", "tests/misc.test.ts"]))
    check("cv5b a runner that printed only SUITE paths still names the work: "
          "`tests/parser.spec.ts` is about `src/parser.ts`, matched on the stem "
          "the test is named after and across directories, because src/ tested "
          "from tests/ is the ordinary layout: %r / %r" % (_hit, _b),
          _hit == ["src/parser.ts"] and "test paths" in _b)
    _miss, _b2 = M.coverage(["docs/handbook.md", "docs/guide.md"],
                            set(["src/a.ts", "src/b.ts"]))
    check("cv5c ...and NO OVERLAP still fires where it was earned: eslint and "
          "tsc named real source files and none of them is the Markdown this "
          "task owns. This is the case the second report says stopped it reading "
          "green as verified: %r" % (_miss,),
          _miss == [])
    _cross, _b3 = M.coverage(["src/parser.ts"], set(["tests/lexer.spec.ts"]))
    check("cv5d ...and a test named after a DIFFERENT file is not a match. The "
          "match only widens onto test-shaped paths and only onto the exact stem "
          "they carry - a false overlap tells the reader their work was "
          "exercised when it was not, which is the comfort NO OVERLAP exists to "
          "refuse. THE MATCH IS ASSERTED SEPARATELY from the verdict, because "
          "this shape must read as NOT KNOWABLE: the suite really is about "
          "`lexer` and not about `parser`, so nothing matched - and a `None` "
          "here that came from a match quietly widening would look identical to "
          "one that came from the population test: %r / %r"
          % (_cross, M._subject_of("tests/lexer.spec.ts")),
          _cross is None
          and M._subject_of("tests/lexer.spec.ts") == "lexer"
          and M.coverage(["src/lexer.ts"],
                         set(["tests/lexer.spec.ts"]))[0] == ["src/lexer.ts"])

    # --- an empty overlap is only evidence from comparable paths -------------
    # `NO OVERLAP WITH THIS WORK` fired on roughly 20 of 30 runs in one jest
    # repository, INCLUDING runs whose coverage was obvious, because jest prints
    # the SUITE it ran while `task.files` lists the sources under it. The stem
    # bridge above is the only relation there is, so a suite named for a
    # FEATURE rather than for a file leaves a real empty set over a real path
    # set - literally true, and useless. At two firings in three a reader learns
    # to skim the block a real finding appears in.
    #
    # THE REPAIR IS ON WHAT COUNTS AS EVIDENCE AND NOT ON THE MATCH, which is
    # why cv14 and cv15 are a PAIR: widening the stem match would satisfy cv14
    # and destroy the two firings cv15 and cv5c/cv11 pin.
    _f307 = ["src/services/order.ts", "src/cart.ts"]
    _f307_named = set(["src/services/__tests__/checkout-flow.test.ts",
                       "src/misc.test.ts"])
    _nk, _nkb = M.coverage(_f307, _f307_named)
    check("cv14 THE FAULT: a jest gate printed two suites named after FEATURES, "
          "the task declares the sources under them, and the answer is NOT "
          "KNOWABLE rather than `no overlap`. A runner that prints what it RAN "
          "has not said which sources it exercised, so the empty set measured "
          "the naming convention: %r" % (_nkb[-190:],),
          _nk is None and "NOT KNOWABLE from its output" in _nkb
          and "not evidence that it did not" in _nkb
          and M.evidence_paths(_f307, _f307_named) == [])
    _j_hit, _ = M.coverage(["docs/audit/audit-plan.json"],
                           set(["tools/ui-tests/panel.test.js",
                                "tools/ui-tests/report.test.js"]))
    _e_hit, _ = M.coverage(["src/mine.ts"], set(["src/a.ts", "src/b.ts"]))
    check("cv15 SECOND DIRECTION, AND IT IS TWO RUNS BECAUSE THE REPAIR HAS TWO "
          "HALVES. The run that motivated this feature - a vitest UI suite, "
          "two `.test.js` files, nine tests green, against a one-value edit "
          "to a `.json` "
          "manifest - printed nothing spelled like that manifest, so those "
          "suites demonstrably are not about it and NO OVERLAP is the finding. "
          "And eslint naming real `.ts` sources against a `.ts`-owning task it "
          "never linted is the half a rule reading EXTENSIONS ALONE would have "
          "silenced - the suite/processed split is what keeps it: %r / %r"
          % (_j_hit, _e_hit),
          _j_hit == [] and _e_hit == [])
    _vend = set(["src/flow.test.ts", "src/checkout.test.ts",
                 "node_modules/jest-runner/build/index.js"])
    _v_hit, _v_b = M.coverage(["src/order.ts"], _vend)
    _cfg = set(["jest.config.js", "package.json"])
    check("cv16 ...and a VENDORED path is not evidence either, which is what "
          "keeps cv14 true on a FAILING jest run: the stack frames under "
          "`node_modules` are the bulk of what `_PATHISH` harvests there, and a "
          "dependency is not a file any task declares. A CONFIG file is the "
          "paired half and stays NO OVERLAP - `jest.config.js` is a repo file "
          "the runner really did read, and cv11's whole set is built from those: "
          "%r / %r" % (_v_hit, M.coverage(["src/mine.ts"], _cfg)[0]),
          _v_hit is None and M.evidence_paths(["src/order.ts"], _vend) == []
          and M.coverage(["src/mine.ts"], _cfg)[0] == []
          and M.evidence_paths(["src/mine.ts"], _cfg) == ["jest.config.js",
                                                          "package.json"])
    check("cv17 `_is_suite_path` reads the DIRECTORY too - `__tests__/order.ts` "
          "is jest's own layout and carries no `.test` mark at all - while "
          "`_subject_of` still does NOT, because that one re-spells a path onto "
          "another file's stem and a directory is far too weak to justify it. "
          "One signal for classifying, a stricter one for matching: %r"
          % ([M._is_suite_path(p) for p in
              ("src/__tests__/order.ts", "src/order.ts", "test/order.ts")],),
          M._is_suite_path("src/__tests__/order.ts") is True
          and M._is_suite_path("src/order.ts") is False
          and M._subject_of("src/__tests__/order.ts") is None)
    check("cv18 `_extension` reads the BASENAME, so a dotted DIRECTORY lends no "
          "suffix to a file that has none and a leading dot is a NAME rather "
          "than a suffix - `.gitignore` has no extension, and getting that "
          "wrong would put every dotfile in its own population: %r"
          % ([M._extension(p) for p in
              ("src/a.TS", "my.dir/Makefile", ".gitignore", "a")],),
          [M._extension(p) for p in
           ("src/a.TS", "my.dir/Makefile", ".gitignore", "a")]
          == ["ts", "", "", ""])
    check("cv5e `_subject_of` answers only for test-shaped paths, so an "
          "ordinary source file is never re-spelled into somebody else's stem",
          M._subject_of("src/foo.ts") is None
          and M._subject_of("src/foo.test.ts") == "foo"
          and M._subject_of("tests/foo_spec.rb") == "foo"
          and M._subject_of("src/.spec.ts") is None,
          repr([M._subject_of(p) for p in
                ("src/foo.ts", "src/foo.test.ts", "tests/foo_spec.rb",
                 "src/.spec.ts")]))
    check("mp1 `_subject_of`, `_is_suite_path`, `_TEST_MARKS`, `_TEST_DIRS` "
          "and `_segments` are ALIASES of `_manifest_phases`'s public "
          "functions, not a second body: `is` rather than a behavioural "
          "match, because a re-pasted copy would pass every case above and "
          "still be the second definition an entry point cannot share with "
          "audit-task.py",
          getattr(M, "_subject_of", None)
          is getattr(_phases, "subject_of", object())
          and getattr(M, "_is_suite_path", None)
          is getattr(_phases, "is_suite_path", object())
          and getattr(M, "_TEST_MARKS", None)
          is getattr(_phases, "TEST_MARKS", object())
          and getattr(M, "_TEST_DIRS", None)
          is getattr(_phases, "TEST_DIRS", object())
          and getattr(M, "_segments", None)
          is getattr(_phases, "path_segments", object()))
    check("cv6 `files_named` reads a path out of runner prose and leaves the "
          "words alone - a grammar that swallowed `Passed` or `2` would make "
          "every run overlap everything: %r"
          % (sorted(M.files_named("Passed\n  src/a.ts:12 ok\n2 files\n") or []),),
          M.files_named("Passed 9 tests ok") is None
          and "src/a.ts" in (M.files_named("  src/a.ts:12 ok") or set()))
    # THE SEPARATOR SURVIVES, and what it costs to lose it is not a lost match.
    # These paths travel into the coverage basis and from there into a COMMITTED
    # row, where every reader downstream decides by asking whether the path is
    # absolute - so a leading `/` this function removed was a home directory
    # that nothing below could see, in the one file whose subject that is. The
    # dotfile is here for the same cut: `.claude/x.json` came back as
    # `claude/x.json`, a path no repository has.
    _cv6_abs = "/Users/someone/proj/node_modules/x.js"
    check("cv6a an absolute path keeps its separator and a dotfile keeps its "
          "dot - only a leading `./` comes off, because the strip that took "
          "more handed the next reader a machine path wearing a "
          "repo-relative spelling: %r"
          % (sorted(M.files_named("%s\n.claude/x.json\n./src/a.ts\n"
                                  % _cv6_abs) or []),),
          M.files_named("%s\n.claude/x.json\n./src/a.ts\n" % _cv6_abs)
          == set([_cv6_abs, ".claude/x.json", "src/a.ts"]))
    # ...and the match the strip was there for is unaffected, which is the case
    # that fails if the repair is taken as licence to stop normalising at all.
    check("cv6b a runner's absolute spelling of a declared file still counts as "
          "coverage - the comparison relates a path to a suffix of itself, so "
          "keeping the separator costs no overlap",
          M.coverage(["src/a.ts"],
                     M.files_named("PASS /Users/someone/proj/src/a.ts\n"))[0]
          == ["src/a.ts"])

    # --- NO OVERLAP has to be diagnosable when it fires ---------------------
    # Reported firing on every gate run of one session, including tasks whose own
    # suite went green -- and at that rate the line becomes noise people skip,
    # which is the opposite of what it is for. THE REPORTED MECHANISM WAS WRONG:
    # `named` is not empty (`files_named` already answers None for that, and
    # `coverage` already renders it as not-knowable -- cv4 above). `named` is
    # NON-EMPTY and simply unrelated, because `_PATHISH` harvests stack frames,
    # config files, the echoed command line and dotted identifiers. So the
    # verdict is literally true over a real path set, and two counts cannot show
    # a reader why.
    _noise = (["jest.config.js", "package.json"]
              + ["node_modules/pkg%02d/dist/index.js" % n for n in range(40)])
    _miss270, _b270 = M.coverage(["src/mine.ts"], set(_noise))
    check("cv11 THE FAULT: the basis NAMES what the runner printed, so a reader "
          "sees in one second that these are config files and stack frames "
          "rather than suites. Two counts -- 42 named, 1 declared -- are both "
          "true and neither is a diagnosis, and `named` escaped `run_gate` "
          "nowhere at all before this: %r" % (_b270,),
          _miss270 == [] and "node_modules/pkg00/dist/index.js" in _b270
          and "jest.config.js" in _b270)
    _shown270 = len([p for p in _noise if p in _b270])
    check("cv12 ...and the sample is BOUNDED and says exactly how many it did "
          "NOT show, never silently short -- `_output.some_of`'s whole "
          "contract, and the reason a count printed in front of a list and the "
          "list itself cannot disagree about how much of the set is on screen. "
          "This string is copied verbatim into a COMMITTED row, so the budget "
          "is a limit on the record and not only on a terminal: shown=%d of %d"
          % (_shown270, len(_noise)),
          0 < _shown270 < len(_noise)
          and "and %d more" % (len(_noise) - _shown270) in _b270)
    _hit270, _bhit = M.coverage(["src/mine.ts"], set(["src/mine.ts", "x/y.ts"]))
    check("cv13 ...and the sample rides on the SAME basis the overlapping case "
          "prints, so the ledger, the report and the panel all get it without a "
          "field of their own. A sample attached only to the empty verdict "
          "would be missing from every row that is worth comparing it with: %r"
          % (_bhit,),
          _hit270 == ["src/mine.ts"] and "among them:" in _bhit
          and "src/mine.ts" in _bhit)

    # --- the complement: what a green gate did NOT touch ---------------------
    # An operator running this on a live engagement singled out the coverage
    # line unprompted: it is the only place connecting a green gate to the
    # files a phase claimed, and the complement - what was declared but never
    # named - is the interesting half of that. `hits` and `owned` are both
    # live inside `coverage()` where the overlap is built, so that is where
    # the subtraction has to happen; a print site downstream only ever sees
    # whichever one it was handed.
    _some, _sb = M.coverage(["src/a.ts", "src/b.ts", "src/c.ts"],
                            set(["src/a.ts"]))
    check("cv19 THE FAULT, FIXED: a partial hit used to report only the file "
          "it named, saying nothing about the two it declared and never "
          "touched - the complement was computed nowhere. It now rides the "
          "same basis the hit count comes from: %r" % (_sb,),
          _some == ["src/a.ts"]
          and "declared but not named by the run" in _sb
          and "src/b.ts" in _sb and "src/c.ts" in _sb)
    _all, _ab = M.coverage(["src/a.ts", "src/b.ts"],
                           set(["src/a.ts", "src/b.ts"]))
    check("cv20 AN EMPTY COMPLEMENT IS ITS OWN SENTENCE, not a basis that "
          "just stops after the count: 'every declared file was touched' is "
          "a claim the run earned, and a reader must be told that rather "
          "than inferring it from a missing clause: %r" % (_ab,),
          _all == ["src/a.ts", "src/b.ts"]
          and "every declared file was named by the run" in _ab
          and "declared but not named by the run" not in _ab)
    _none, _nb = M.coverage([], set(["src/a.ts"]))
    check("cv21 ...and it must not be the SAME sentence as 'nothing was "
          "declared' - the two are different facts and a reader comparing "
          "two rows cannot be made to tell them apart from a blank: %r / %r"
          % (_ab, _nb),
          "declares no files" in _nb
          and "every declared file was named" not in _nb
          and _ab != _nb)
    _wide = ["src/keep%02d.ts" % n for n in range(40)]
    _whit, _wb = M.coverage(_wide, set(["src/keep00.ts"]))
    _wshown = len([p for p in _wide[1:] if p in _wb])
    check("cv22 the untouched list is truncated the way its neighbour two "
          "statements above already is - `_output.some_of`, not a second "
          "mechanism invented for this line - so a row this wide still says "
          "how many it left out rather than growing the ledger unbounded: "
          "shown=%d of %d" % (_wshown, len(_wide) - 1),
          _whit == ["src/keep00.ts"]
          and 0 < _wshown < len(_wide) - 1
          and "and %d more" % (len(_wide) - 1 - _wshown) in _wb)
    res = M.run_gate(tmp, [("test", "npx vitest run")], runner=_vitest_green,
                     owns=["tools/ui-tests/panel.test.js", "docs/plan.json"])
    lines = []
    M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("cv23 END TO END: the printed line and the recorded basis agree - "
          "the run named one of two declared files, and the line a reader "
          "actually sees says which one it missed, not only which one it "
          "hit: %r" % (text[-160:],),
          "coverage: 1 declared file" in text
          and "declared but not named by the run: docs/plan.json" in text)

    # P59.6: a `:line-range` suffix must not defeat the match. The schema
    # allows one on a `files` entry and nothing a runner prints ever carries
    # it, so comparing the raw entry against `named` used to drop a suffixed
    # declaration out of `hits` and into the complement - "declared but not
    # named by the run" about a file the run named exactly.
    _sfx_hit, _sfx_b = M.coverage(["src/a.ts:12-34", "src/missing.ts"],
                                  set(["src/a.ts"]))
    check("cv24 a suffixed entry naming a path the runner DID print is a HIT, "
          "asked of the file it names rather than of its own spelling: %r"
          % (_sfx_hit,),
          _sfx_hit == ["src/a.ts:12-34"])
    check("cv25 SECOND-DIRECTION CASE: the UNSUFFIXED entry in the SAME call "
          "that really was not named still lands in the complement - the "
          "repair reads the suffix away, it does not widen what counts as "
          "named: %r" % (_sfx_b,),
          "declared but not named by the run: src/missing.ts" in _sfx_b)

    # --- what the manifest says the work owns -----------------------------
    check("cv7 the phase's declaration is the UNION of its tasks' files, "
          "de-duplicated - the phase gate is this script's actual call site, so "
          "asking only about a named task would be a flag with no caller: %r"
          % (M.owned_files(man, "P1"),),
          M.owned_files(man, "P1") == ([], None))
    _cvman = {"meta": {"version": 2},
              "phases": [{"id": "PA", "title": "a", "status": "in_progress",
                          "testGate": [], "tasks": [
                              {"id": "PA.1", "files": ["x.ts", "shared.ts"]},
                              {"id": "PA.2", "files": ["y.ts", "shared.ts"]}]}]}
    check("cv8 ...in manifest order and without a repeat, which is what makes "
          "the printed count a basis rather than a number: %r"
          % (M.owned_files(_cvman, "PA"),),
          M.owned_files(_cvman, "PA") == (["x.ts", "shared.ts", "y.ts"], None))
    check("cv9 ...and --task narrows it to that task alone",
          M.owned_files(_cvman, "PA", "PA.2") == (["y.ts", "shared.ts"], None))
    _cvnone, _cverr = M.owned_files(_cvman, "PA", "PA.9")
    check("cv10 ...while an unknown task is an ERROR rather than an empty "
          "declaration - 'this task owns nothing' and 'there is no such task' "
          "are two different answers, exactly as rg3 draws it for a phase: %r"
          % (_cverr,),
          _cvnone is None and "no task" in (_cverr or ""))

    # --- the empty gate is a designed state, not a pass -------------------
    mpath = os.path.join(tmp, "audit-plan.json")
    with open(mpath, "w") as fh:
        json.dump(man, fh)
    lines = []
    code = M.main([mpath, "P2", "--project-dir", tmp], out=lines.append)
    check("rg16 an EMPTY gate exits 0 and is reported AS the empty gate - "
          "`_phase_gate` documents it as a designed state, and printing "
          "'green' would claim a measurement nobody made: %r"
          % ("\n".join(lines)[:100],),
          code == M.E_OK and "EMPTY gate" in "\n".join(lines)
          and "GATE GREEN" not in "\n".join(lines))
    lines = []
    code = M.main([mpath, "P9", "--project-dir", tmp], out=lines.append)
    check("rg17 ...and a phase that does not exist is exit 2, the code for "
          "'could not be asked' rather than 'failed'",
          code == M.E_ASK and "no phase" in "\n".join(lines))

    # --- lifecycle: what did not finish, and what it cost ------------------
    # A timeout and a failure to START were ONE answer before this: `_shell`
    # swallowed both into `except Exception` and reported exit 127 for each, so
    # "the suite hung" and "the binary is missing" were the same row. They are
    # different repairs, so they are different words - and `lc2` is the pair that
    # says so, because either alone passes with the two collapsed.
    def _timed_out(_project, _command, timeout=None):
        return -9, "partial output\n", {"outcome": M.TIMED_OUT,
                                        "timeoutSeconds": timeout}

    def _cannot_run(_project, _command, _timeout=None):
        return 127, "could not run: no such file\n", {"outcome": M.CANNOT_RUN}

    res_t = M.run_gate(tmp, [("test", "pytest -q")], runner=_timed_out,
                       timeout=7)
    check("lc1 a step that did not finish is `timed-out`, not `failed` - a "
          "verdict was never reached, and spelling that as red would claim a "
          "measurement nobody completed: %r"
          % ((res_t.get("status"), res_t["steps"][0].get("outcome")),),
          res_t.get("status") == "timed-out"
          and res_t["steps"][0].get("outcome") == M.TIMED_OUT)

    res_c = M.run_gate(tmp, [("test", "pytest -q")], runner=_cannot_run)
    check("lc2 ...and a step that never STARTED is a third word again. The two "
          "are asserted as DIFFERENT rather than each against a literal, which "
          "is the half that fails while both are exit 127: %r vs %r"
          % (res_t.get("status"), res_c.get("status")),
          res_c.get("status") == "could-not-run"
          and res_c.get("status") != res_t.get("status"))

    check("lc3 the timeout that applied is recorded on the step, so `timed-out` "
          "carries the basis that makes it actionable rather than leaving a "
          "reader to guess which bound was hit: %r"
          % (res_t["steps"][0].get("timeoutSeconds"),),
          res_t["steps"][0].get("timeoutSeconds") == 7)

    def _fail_then_timeout(project, command, timeout=None):
        if "first" in command:
            return 1, "boom\n", {}
        return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}

    res_ft = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_fail_then_timeout)
    check("lc4 a run that FAILED and also timed out reads `failed` - a certain "
          "red must not be downgraded to an uncertain one - and the timeout "
          "survives on its own step, so neither fact is lost: %r"
          % ((res_ft.get("status"), [st.get("outcome") for st in res_ft["steps"]]),),
          res_ft.get("status") == "failed" and res_ft["failed"] == ["a"]
          and res_ft["steps"][1].get("outcome") == M.TIMED_OUT)

    check("lc5 ON A TIMEOUT THE TREE COMPARISON IS NOT MADE: `treeMutated` is "
          "None and the basis names the race, because a survivor of a torn-down "
          "group keeps writing. `porcelain` already refuses to call an "
          "unanswerable tree clean; this is the same refusal one cause over: %r"
          % ((res_t.get("treeMutated"), res_t.get("treeBasis")),),
          res_t.get("treeMutated") is None
          and "interrupted" in (res_t.get("treeBasis") or ""))

    res_ok = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("lc6 ...and the pair that keeps that honest: a run that COMPLETED "
          "reports `treeMutated == []`, a list. Empty and None are the two "
          "readings a truthy test would merge, which is the whole reason the "
          "field is three-valued: %r" % (res_ok.get("treeMutated"),),
          res_ok.get("treeMutated") == []
          and res_ok.get("treeMutated") is not None)

    check("lc7 a completed run with every step at exit 0 is `passed`, and an "
          "unknowable check count does NOT make it `no-checks` - None is 'not "
          "knowable', and only a POSITIVE zero earns that word: %r"
          % ((res_ok.get("status"), res_ok["ranTotal"]),),
          res_ok.get("status") == "passed" and res_ok["ranTotal"] is None)

    res_zero = M.run_gate(tmp, [("lint", "pre-commit run --files a.md")],
                          runner=_all_skipped)
    check("lc8 ...while a count that is POSITIVELY zero is `no-checks`, which "
          "is the one status that is exit 0 and still not a verdict: %r"
          % ((res_zero.get("status"), res_zero["ranTotal"]),),
          res_zero.get("status") == "no-checks" and res_zero["ranTotal"] == 0)

    check("lc9 the run and every step carry a duration, as non-negative "
          "integers - `run_gate` measures around the seam, so a fixture runner "
          "needs to know nothing about time: %r"
          % ((res_ok.get("durationMs"), res_ok["steps"][0].get("durationMs")),),
          isinstance(res_ok.get("durationMs"), int)
          and res_ok.get("durationMs") >= 0
          and all(isinstance(st.get("durationMs"), int)
                  and st["durationMs"] >= 0 for st in res_ok["steps"]))

    # --- the REAL runner, against a real process tree ----------------------
    # The one case that cannot be written with a fixture: `subprocess.run`'s own
    # timeout kills the direct child, and under `sh -c` that child is the
    # shell. A grandchild outlives it, keeps writing, and is exactly what makes
    # the after-snapshot a race. Proven by what the survivor WRITES, not by prose
    # and not by a pid probe - `CHILD_SOURCE` carries why.
    #
    # ITS OWN ROOT, because the survivor is writing a file for as long as the
    # teardown fails to stop it, and `tmp` is the git fixture several later cases
    # take a `git status --porcelain` of.
    treeroot = _harness.fixture_root("run-test-gate-tree-")
    helper = os.path.join(treeroot, "child_helper.py")
    with open(helper, "w") as fh:
        fh.write(CHILD_SOURCE)
    beat = os.path.join(treeroot, "beat.txt")
    pidpath = os.path.join(treeroot, "pids.txt")
    code, text, facts = M._shell(
        treeroot, _step(sys.executable, helper, "spawn", beat, pidpath),
        timeout=TREE_TIMEOUT)
    # Sampled TWICE, after the teardown and half a second apart. One sample can
    # only say the grandchild ran; two say whether it is still running, which is
    # the question. The first also has to be positive: a grandchild that never
    # started writes nothing, and "nothing was written" would otherwise read
    # exactly like "the teardown worked".
    tree_pids = _pids_in(pidpath)
    time.sleep(0.5)
    wrote = _written(beat)
    time.sleep(0.5)
    wrote_later = _written(beat)
    if wrote_later != wrote:
        for _pid in tree_pids:
            _force_kill(_pid)
    # The guard the mutation battery found, covered WITHOUT the suite ever
    # signalling its own group. An earlier case called the real `_tear_down` on a
    # same-group child; with the guard defeated that killpg reaches this runner,
    # so the suite DIED instead of going red - detection of the worst kind, since
    # a dead suite reads as infrastructure trouble. The decision and its use site
    # are covered separately below, and neither can take this process with it.
    #
    # THE PREDICATE IS THE ONE THING HERE THAT IS GENUINELY HALF A SPLIT.
    # `shares_our_group` calls `os.getpgid`, which exists on posix and nowhere
    # else; on a platform without it every call raises, the `except` returns True,
    # and `_tear_down` never asks - it took the `taskkill` arm two lines earlier.
    # So the two halves are asserted separately and each says which platform it
    # is about, rather than one of them being softened until it passes on both.
    # Each skip below is GRADED on a fresh `hasattr`, not on the constant the
    # `if` read - see `console_events()` for why a skip graded on its own branch
    # condition is a check that cannot fail.
    #
    # THE SPLIT IS TAKEN ON `os.killpg`, WHICH IS THE EXPRESSION `_tear_down`
    # ITSELF BRANCHES ON, and that is a safety property and not a tidiness one.
    # The windows arm below calls `_tear_down` with the predicate forced FALSE,
    # which on posix is the spelling that reaches `os.killpg` on a child sharing
    # this runner's group - the call that once killed the suite mid-run. Reading
    # the same name the product reads makes that call unreachable there rather
    # than merely unlikely. Each case still declares the mechanism IT needs, so a
    # platform where the two names came apart is reported and not assumed.
    if HAS_KILLPG:
        plain = subprocess.Popen("sleep 30", shell=True, cwd=tmp,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
        detached = subprocess.Popen("sleep 30", shell=True, cwd=tmp,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True)
        try:
            check("lc11 the predicate tells the two apart: a child of our own "
                  "group WOULD signal us, one given its own session would not. "
                  "Both ends asserted, because a predicate stuck at either "
                  "constant is half right and wholly useless: same=%r detached=%r"
                  % (_pg.shares_our_group(plain.pid),
                     _pg.shares_our_group(detached.pid)),
                  _pg.shares_our_group(plain.pid) is True
                  and _pg.shares_our_group(detached.pid) is False)
            check("lc12 ...and an unanswerable pid is True, the SAFE direction: "
                  "not knowing whether we would hit ourselves must never read as "
                  "permission to aim at the group",
                  _pg.shares_our_group(-1) is True)

            real = _pg.shares_our_group
            try:
                _pg.shares_our_group = lambda _pid: True
                narrow = M._tear_down(detached)
            finally:
                _pg.shares_our_group = real
            check("lc13 ...and `_tear_down` READS it: told the child shares our "
                  "group, it takes the narrow kill and reports UNCONFIRMED, even "
                  "though this child had a session of its own. The use site, "
                  "covered by swapping the name rather than by signalling "
                  "ourselves - `test__journal_io` uses the same seam: %r"
                  % (narrow,),
                  narrow is False and detached.returncode is not None)
        finally:
            for proc in (plain, detached):
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass
        _harness.skip(check, "lc11w",
                      "the constant this asserts is what a platform with no "
                      "`os.getpgid` reports, and this one HAS it - lc11 and "
                      "lc12 assert the answering predicate instead",
                      hasattr(os, "getpgid"))
        _harness.skip(check, "lc13w",
                      "`_tear_down` reads the predicate here, which is lc13; "
                      "the arm that ignores it is the one guarded by "
                      "`hasattr(os, \"killpg\")` being false",
                      hasattr(os, "killpg"))
    else:
        _harness.skip(check, "lc11",
                      "no `os.getpgid`, so `shares_our_group` cannot answer the "
                      "question this case puts to it and returns its safe "
                      "constant for every pid - lc11w asserts that constant",
                      not hasattr(os, "getpgid"))
        _harness.skip(check, "lc12",
                      "no `os.getpgid`, so EVERY pid takes the same `except` and "
                      "an unanswerable one is indistinguishable from the rest - "
                      "the case would pass while separating nothing",
                      not hasattr(os, "getpgid"))
        _harness.skip(check, "lc13",
                      "no `os.killpg`, so `_tear_down` never reaches the branch "
                      "that reads the predicate - lc13w asserts the arm it "
                      "reaches instead",
                      not hasattr(os, "killpg"))
        # Through `_step`, like every other command here: it is the one spelling
        # already known to survive both shells, and `sys.executable` is not
        # guaranteed to be a path without a space in it.
        _stall = _step(sys.executable, helper, "stall", beat)
        detached = subprocess.Popen(_stall, shell=True, cwd=tmp,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
        ignored = subprocess.Popen(_stall, shell=True, cwd=tmp,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        try:
            check("lc11w the predicate is the SAFE CONSTANT here, for every pid "
                  "including our own: with no `os.getpgid` there is no question "
                  "it can answer, and True is 'do not aim at the group'. This is "
                  "the platform half of lc11, and it is only honest beside "
                  "lc13w - a constant nobody reads: same=%r detached=%r own=%r"
                  % (_pg.shares_our_group(detached.pid),
                     _pg.shares_our_group(ignored.pid),
                     _pg.shares_our_group(os.getpid())),
                  _pg.shares_our_group(detached.pid) is True
                  and _pg.shares_our_group(ignored.pid) is True
                  and _pg.shares_our_group(os.getpid()) is True
                  and _pg.shares_our_group(-1) is True)

            real = _pg.shares_our_group
            try:
                _pg.shares_our_group = lambda _pid: True
                forced_true = M._tear_down(detached)
                _pg.shares_our_group = lambda _pid: False
                forced_false = M._tear_down(ignored)
            finally:
                _pg.shares_our_group = real
            _harness.attempt(detached.wait, 10)
            _harness.attempt(ignored.wait, 10)
            check("lc13w ...and `_tear_down` does NOT read it here: swung to "
                  "both constants it gives the same answer, because the arm it "
                  "takes is `taskkill /T /F` and that arm is chosen before the "
                  "predicate is mentioned. Asserted as INVARIANCE plus a dead "
                  "child, so an arm that answered False for a kill that never "
                  "happened could not pass it: told-true=%r told-false=%r "
                  "rc=%r %r" % (forced_true, forced_false,
                                detached.returncode, ignored.returncode),
                  forced_true == forced_false
                  and detached.returncode is not None
                  and ignored.returncode is not None)
        finally:
            for proc in (detached, ignored):
                if proc.poll() is None:
                    proc.kill()
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass

    check("lc10 THE FAULT: the real runner tears down the whole process tree, so "
          "a grandchild the step started does not outlive the timeout. "
          "`subprocess.run(timeout=)` kills the shell alone and leaves it "
          "running - and a survivor keeps writing into the tree the gate is "
          "about to describe. Whichever teardown this platform has is the one "
          "under test, because `_tear_down` picks it the same way this file "
          "does: pids=%r outcome=%r wrote=%r then=%r"
          % (tree_pids, facts.get("outcome"), wrote, wrote_later),
          facts.get("outcome") == M.TIMED_OUT
          and len(tree_pids) == 2 and wrote > 0 and wrote_later == wrote)
    check("lc10b ...and the teardown was CONFIRMED, which is the return value "
          "and not the silence around it. `_tear_down` answers False for a kill "
          "it could not account for and the row then says `unconfirmed`, so a "
          "run whose facts carry no teardown key is the one claiming a clean "
          "stop. This is the half that reaches the platform's own arm - killpg "
          "returning, or taskkill exiting 0: %r" % (facts,),
          facts.get("outcome") == M.TIMED_OUT
          and facts.get("teardown") is None)

    # --- the real runner's other two answers -------------------------------
    code, text, facts = M._shell(os.path.join(tmp, "no-such-dir"), "true")
    check("lc14 a command that could not be STARTED is `could-not-run` from the "
          "real runner, not only from a fixture - this is the Popen failure "
          "itself, and it is the half that never reaches a stub: %r"
          % ((code, facts.get("outcome")),),
          facts.get("outcome") == M.CANNOT_RUN and code == 127
          and "could not run" in text)

    # `echo marker; sleep 30` was two things `cmd.exe` does not read as two
    # commands, so on the windows leg this step printed the whole string and
    # exited - and the case went red about a drain that had nothing to drain.
    # The guarantee is not platform-split, only its spelling was.
    code, text, facts = M._shell(
        treeroot, _step(sys.executable, helper, "stall", beat),
        timeout=TREE_TIMEOUT)
    check("lc15 ...and a timed-out step still returns what the child had "
          "already written. The drain runs AFTER the kill, never instead of it: "
          "a timed-out child is often blocked on a full pipe, so reading first "
          "would wait on a process nothing is going to stop: %r"
          % ((text.strip()[:24], facts.get("timeoutSeconds")),),
          facts.get("outcome") == M.TIMED_OUT and "marker" in text
          and facts.get("timeoutSeconds") == TREE_TIMEOUT)

    res_127 = M.run_gate(tmp, [("x", "definitely-not-a-real-binary-xyz")])
    # ONE EXPECTATION ON EVERY HOST. A plan command runs under the POSIX `sh`
    # `_proc_group` resolves, Windows included, so the missing program is read
    # off that shell's diagnostic everywhere; the arm that once expected
    # cmd.exe's silence on Windows described a spawn that no longer happens.
    check("lc16 a MISSING BINARY under `sh -c` is `could-not-run`, read "
          "off the SHELL'S OWN DIAGNOSTIC and not off the number: the shell "
          "started, could not find the program, and said so before printing "
          "any report a runner prints at its end. 127 alone stays a failure - "
          "`nv2` pins that half - because a real command may return it: %r"
          % ((res_127["status"], res_127["steps"][0].get("outcome"),
              res_127["steps"][0].get("outcomeBasis")),),
          res_127["status"] == M.CANNOT_RUN
          and res_127["steps"][0].get("outcome") == M.CANNOT_RUN
          and res_127["failed"] == []
          and "could not find" in (res_127["steps"][0].get("outcomeBasis")
                                   or ""))

    # --- a signal-killed runner is not a failing test -----------------------
    # DRIVEN, and the two commands are the whole fault: `sh -c 'kill -9 $$'`
    # came back exit -9 and `sh -c 'exit 1'` came back exit 1, and the verdict
    # read them as ONE answer - GATE RED, recorded `failed`, a retry spent. The
    # signal was already on the record as `steps[].exit`, so this runner had
    # observed it and the verdict threw the observation away.
    #
    # `hasattr(signal, "SIGKILL")` IS THE MECHANISM READ, not a platform name:
    # windows' `signal` module has no SIGKILL, so a case that guessed
    # by platform could be right about the name and wrong about the thing it
    # needed. It is read fresh here rather than off a constant a branch above
    # already consulted, for `console_events()`'s reason.
    if not hasattr(signal, "SIGKILL"):
        print("SKIP sk1/sk3 (no SIGKILL on this platform)")
    else:
        res_kill = M.run_gate(tmp, [("test", "kill -9 $$")])
        res_one = M.run_gate(tmp, [("test", "exit 1")])
        # THE SHELL'S OWN SPELLING OF A SEGFAULT, driven rather than stubbed:
        # this is the code `sh` returns when the command it ran died of signal
        # 11, and it is the only channel a grandchild's kill can reach us
        # through under `sh -c`.
        res_139 = M.run_gate(tmp, [("test", "exit 139")])
        kill_lines, one_lines = [], []
        kill_code = M.render(res_kill, out=kill_lines.append)
        one_code = M.render(res_one, out=one_lines.append)
        kill_text, one_text = "\n".join(kill_lines), "\n".join(one_lines)
        check("sk1 THE FAULT, BOTH HALVES IN ONE CASE: a child the OS killed is "
              "`could-not-run` carrying the signal, while an HONEST non-zero "
              "exit beside it is still a failing test. Asserted as DIFFERENT and "
              "not each against a literal, which is the half that fails both "
              "when the kill is graded red AND when nothing is ever graded red "
              "again: %r vs %r"
              % ((res_kill["steps"][0]["exit"], res_kill["status"],
                  res_kill["steps"][0].get("signal"), res_kill["failed"]),
                 (res_one["steps"][0]["exit"], res_one["status"],
                  res_one["failed"])),
              res_kill["steps"][0]["exit"] < 0
              and res_kill["steps"][0].get("outcome") == M.CANNOT_RUN
              and res_kill["steps"][0].get("signal") == "SIGKILL"
              and res_kill["status"] == M.CANNOT_RUN
              and res_kill["failed"] == []
              and res_one["steps"][0]["exit"] == 1
              and res_one["steps"][0].get("outcome") is None
              and res_one["status"] == "failed"
              and res_one["failed"] == ["test"]
              and res_kill["status"] != res_one["status"])
        check("sk2 ...and THE RULE THE DOCUMENT ALREADY STATES BECOMES "
              "REACHABLE, which is the difference between correcting a word and "
              "repairing the defect. `reference/orchestrator.md` keys its "
              "infrastructure arm on the literal `GATE COULD NOT RUN` - 'not the "
              "task's failure ... do NOT spend a retry' - so a kill printed "
              "under a banner of its own would fall through to 'gates RAN and "
              "are red' and burn all three maxAttempts. The banner is the CLASS; "
              "the OS sentence under it is the member, and neither run prints "
              "the other's: %r / %r"
              % (kill_text[:78], one_text[-40:]),
              kill_code == M.E_FAIL and one_code == M.E_FAIL
              and "GATE COULD NOT RUN" in kill_text
              and "THE OS ENDED test (SIGKILL)" in kill_text
              and "do not spend a retry on the task" in kill_text
              and "GATE RED" not in kill_text
              and "GATE RED: test" in one_text
              and "GATE COULD NOT RUN" not in one_text
              and "THE OS ENDED" not in one_text
              # ...and it does NOT claim the step never got as far as a check,
              # which is the sentence `could-not-run`'s OTHER member owns and is
              # false of a suite killed mid-run. That half of the old single
              # sentence was wrong for this member before the split.
              and "never got as far as a check" not in kill_text)
        check("sk3 THE CHANNEL THE FIELD ACTUALLY MEASURED: under `sh -c` "
              "the negative code stops at the shell, so a runner two levels down "
              "that segfaults arrives as exit 139 - and 2 of 10 recorded failures "
              "on one project were exactly that. A reader taking only the OS's "
              "own report would have left every one of them unchanged: %r"
              % ((res_139["steps"][0]["exit"], res_139["status"],
                  res_139["steps"][0].get("signal")),),
              res_139["steps"][0]["exit"] == 139
              and res_139["steps"][0].get("signal") == "SIGSEGV"
              and res_139["status"] == M.CANNOT_RUN
              and res_139["failed"] == [])

    # ...and the rest is a PURE table, so it runs on both platforms. SIGSEGV is
    # 11 everywhere `signal.Signals` exists, which is why every portable case
    # below is written on it rather than on SIGKILL.
    _honest = [(code, M.ended_by_signal(code, "")[0])
               for code in (1, 2, 5, 48, 101, 127, 128, 255)]
    check("sk4 SECOND DIRECTION, SPELLED AS A TABLE: every honest non-zero exit "
          "is still no signal at all. A version answering `could-not-run` for "
          "any non-zero code passes sk1's first half and fails here, and 127 is "
          "on the list on purpose - `lc16` pins that a missing binary under a "
          "shell is a FAILURE, because 127 is a code a real command may return "
          "and reading a category out of a number lets a child claim it: %r"
          % (_honest,),
          [name for _code, name in _honest] == [None] * len(_honest))
    check("sk5 the convention arm YIELDS to a runner that reached the end of its "
          "run, and mocha is why: it exits with the NUMBER OF FAILING TESTS, so "
          "139 failures really is exit 139. A reader that trusted the number "
          "alone would record a suite with 139 real failures as infrastructure, "
          "and one that trusted an EMPTY output would refuse every real kill: "
          "ran=%r" % (M.summary_count(MOCHA_MIN),),
          M.summary_count(MOCHA_MIN) == 140
          and M.ended_by_signal(139, MOCHA_MIN)[0] is None
          and M.ended_by_signal(139, "")[0] == "SIGSEGV")
    # THE FIXTURES BELOW ARE REAL REPORTER OUTPUT rather than a shape written
    # to match the reader: a hand-made fixture and the parser under it would
    # encode one assumption twice. These are what `mocha` emits under each
    # `--reporter`, trimmed.
    _reporters = [(name, M.ran_count("npx mocha", text),
                   M.reached_a_verdict(text),
                   M.ended_by_signal(139, text)[0])
                  for name, text in (("json", MOCHA_JSON),
                                     ("xunit", MOCHA_XUNIT),
                                     ("min", MOCHA_MIN))]
    check("sk5b THE FAULT: the narrowing rested on whether THIS READER had "
          "recognised the output, and every counting reader here answers None to "
          "`mocha --reporter json`. So exit 139 - mocha's spelling of 139 FAILING "
          "TESTS - was recorded `could-not-run`, landed in "
          "`_status_facts.NO_VERDICT_EVIDENCE` and told the orchestrator not to "
          "spend a retry: real failures as an infrastructure excuse, permanently, "
          "in a hash-chained row. Driven across the reporters, with the count "
          "STILL None on two of them - which is what fails a repair that merely "
          "taught the counter another shape: %r" % (_reporters,),
          [(n, verdict) for n, _ran, _end, verdict in _reporters]
          == [("json", None), ("xunit", None), ("min", None)]
          and [(n, ran) for n, ran, _end, _v in _reporters]
          == [("json", None), ("xunit", None), ("min", 140)]
          and all(end for _n, _ran, end, _v in _reporters))
    check("sk5c SECOND DIRECTION, and it is the one that makes this a NARROWING "
          "rather than a mute: a step whose output carries no end-of-run report "
          "at all is still read as a kill. A version that answered "
          "`reached_a_verdict` True unconditionally passes sk5b and fails here, "
          "and the fixtures are the shapes a killed runner really leaves - "
          "nothing, a partial line, and a `pre-commit` log with hooks already "
          "logged: %r"
          % ([M.ended_by_signal(139, t)[0]
              for t in ("", "collecting ...", PRECOMMIT_KILLED)],),
          all(M.ended_by_signal(139, t)[0] == "SIGSEGV"
              for t in ("", "collecting ...", PRECOMMIT_KILLED))
          and not M.reached_a_verdict(PRECOMMIT_KILLED))

    if hasattr(signal, "SIGKILL"):
        def _precommit_killed(_project, _command, _timeout=None):
            return 137, PRECOMMIT_KILLED, {}

        res_pc = M.run_gate(tmp, [("hooks", "pre-commit run --all-files")],
                            runner=_precommit_killed)
        pc_lines = []
        pc_code = M.render(res_pc, out=pc_lines.append)
        pc_text = "\n".join(pc_lines)
        check("sk5d ...AND THE PRE-COMMIT CONFIGURATION THE ARM COULD NEVER REACH. "
              "`pre-commit` is the only entry in `_STEP_WORDS`, so `ran_count` tallies "
              "LINES for it and never answers None - an OOM-killed "
              "`pre-commit run --all-files` that had logged one hook came back "
              "`GATE RED: hooks`, recorded `failed` against the task, and spent a "
              "retry on something no code change fixes. The line tally is still "
              "there and is no longer a verdict: ran=%r %r"
              % (res_pc["steps"][0]["ran"],
                 (res_pc["status"], res_pc["steps"][0].get("signal"))),
              res_pc["steps"][0]["ran"] == 1
              and res_pc["steps"][0].get("outcome") == M.CANNOT_RUN
              and res_pc["steps"][0].get("signal") == "SIGKILL"
              and res_pc["status"] == M.CANNOT_RUN
              and res_pc["failed"] == []
              and pc_code == M.E_FAIL
              and "GATE COULD NOT RUN" in pc_text
              and "GATE RED" not in pc_text)
    else:
        _harness.skip(check, "sk5d",
                      "the case drives an OOM kill as exit 137 and asserts it names SIGKILL; `ended_by_signal` resolves that through `signal.Signals` on THIS machine, which defines no SIGKILL, so the arm cannot fire here by construction",
                      not hasattr(signal, "SIGKILL"))
    _machine = [(name, M.reached_a_verdict(text))
                for name, text in (("nunit3-console", NUNIT_REPORT),
                                   ("checkstyle", CHECKSTYLE_REPORT),
                                   ("tap tallies", TAP_REPORT),
                                   ("tap plan last", TAP_PLAN_LAST),
                                   ("dotnet test", VSTEST_REPORT))]
    check("sk5e ...and the other runners whose EXIT STATUS IS A COUNT are reached "
          "by the same table. `nunit3-console` and `checkstyle` both encode a "
          "tally in their status, so a status in the terminating band is as "
          "ambiguous for them as it is for mocha - and none of them prints a "
          "summary any counting reader in that file knows. Their reports are "
          "recognised without teaching the counter to parse them, which is the "
          "whole point of asking the weaker question. THE TWO TAP SHAPES ARE "
          "SEPARATE FIXTURES: a single one carrying the opening plan AND the "
          "closing tallies would match whichever alternative survived and "
          "deleting either would keep this green: %r" % (_machine,),
          all(seen for _n, seen in _machine)
          # ...and none of them is COUNTED, which is what separates "the runner
          # finished" from "this reader has a number": a repair that widened
          # `summary_count` instead would make these non-None and change what
          # `ranTotal` claims about runs nobody asked it to size.
          and all(M.summary_count(t) is None
                  for t in (NUNIT_REPORT, CHECKSTYLE_REPORT, VSTEST_REPORT,
                            TAP_REPORT, TAP_PLAN_LAST, TAP_KILLED)))

    if hasattr(signal, "SIGKILL"):
        def _tap_killed(_project, _command, _timeout=None):
            return -9, TAP_KILLED, {}

        res_tap = M.run_gate(tmp, [("tap", "npx tape test/*.js")],
                             runner=_tap_killed)
        check("sk5f THE MARKER A RUNNER WRITES BEFORE ITS FIRST TEST. A TAP "
              "plan is legal at either end of the stream and the CLASSIC form "
              "prints `1..N` first, so the row that read it anywhere was matching "
              "a marker emitted at the START of a run - which is the one thing the "
              "table's own header says none of these may be. Driven: the same "
              "classic stream killed after its second test was read as having "
              "spoken for its exit code, so a SIGKILLed suite came back `failed`, "
              "recorded a red row against the task and spent a retry on work never "
              "measured. The tallies are what close a TAP stream and the plan does "
              "so only where it is LAST: %r"
              % ((M.reached_a_verdict(TAP_KILLED),
                  M.ended_by_signal(137, TAP_KILLED)[0], res_tap["status"]),),
              M.reached_a_verdict(TAP_KILLED) is False
              and M.ended_by_signal(137, TAP_KILLED)[0] == "SIGKILL"
              and res_tap["status"] == M.CANNOT_RUN
              and res_tap["failed"] == []
              # ...and the two complete shapes are still verdicts, so this is a
              # NARROWING and not a mute - the same pairing sk5c makes for the
              # convention arm.
              and M.reached_a_verdict(TAP_REPORT) is True
              and M.reached_a_verdict(TAP_PLAN_LAST) is True)
    else:
        _harness.skip(check, "sk5f",
                      "the case asserts -9 and 137 both name SIGKILL, which this platform does not define - the narrowing it proves (a TAP plan printed FIRST is not an end-of-run marker) is asserted platform-free by sk5e's fixtures",
                      not hasattr(signal, "SIGKILL"))

    if hasattr(signal, "SIGKILL"):
        def _precommit_hook_summary(_project, _command, _timeout=None):
            return 137, PRECOMMIT_HOOK_SUMMARY, {}

        res_ph = M.run_gate(tmp, [("hooks", "pre-commit run --all-files")],
                            runner=_precommit_hook_summary)
        check("sk5g ...AND THE SAME CLASS THROUGH THE SUMMARY ARM, which is the "
              "half a fix to the TAP row alone would leave open. `pre-commit` runs "
              "OTHER runners, so a pytest hook's closing line is that HOOK's "
              "end-of-run report and the step's mid-flight - `mypy` had not "
              "finished. `summary_count` reads it, so the arm answered True and an "
              "OOM-killed composite was graded `failed`: the same OOM-killed "
              "configuration again, one arm along from the line tally sk5d "
              "covers. The count is still taken and is still not a verdict: "
              "count=%r ran=%r %r"
              % (M.summary_count(PRECOMMIT_HOOK_SUMMARY),
                 res_ph["steps"][0]["ran"],
                 (res_ph["status"], res_ph["steps"][0].get("signal"))),
              M.summary_count(PRECOMMIT_HOOK_SUMMARY) == 4
              and M.reached_a_verdict(PRECOMMIT_HOOK_SUMMARY,
                                      "pre-commit run --all-files") is False
              # ...off `_STEP_WORDS` and not off a second table, which is the
              # DRY half of the repair: a runner is in there precisely because
              # its output is a list of other runs, so the table that tells
              # `ran_count` to tally lines is the one that answers this.
              and M.wrapper_words("pre-commit run --all-files")
              == M._STEP_WORDS["pre-commit"]
              and M.wrapper_words("npx mocha") is None
              and M.wrapper_words(None) is None
              and res_ph["status"] == M.CANNOT_RUN
              and res_ph["steps"][0].get("signal") == "SIGKILL"
              and res_ph["failed"] == []
              # SECOND DIRECTION, and it is the one that fails a repair that simply
              # deleted the summary arm: a runner that is NOT a wrapper still
              # speaks for its exit code through its own summary line, which is
              # what keeps mocha's 139 failures a red suite rather than a kill.
              and M.reached_a_verdict(MOCHA_MIN, "npx mocha") is True
              and M.ended_by_signal(139, MOCHA_MIN, "npx mocha")[0] is None)
    else:
        _harness.skip(check, "sk5g",
                      "the case drives a composite runner killed at 137 and asserts SIGKILL, which this platform does not define; the summary-arm narrowing it proves is the same `reached_a_verdict(text, command)` rule sk5e drives without a signal",
                      not hasattr(signal, "SIGKILL"))
    # THE ACCEPTED CODES ARE PRINTED, not described. The field report names a
    # band of `128` to `165`; what this reader asks instead is whether
    # `code - 128` names a signal ON THIS MACHINE that terminates by default -
    # narrower at the top, where nothing is a signal, and narrower inside, where
    # SIGCHLD/SIGCONT/SIGURG/SIGWINCH all live. So the band is DERIVED and the
    # case shows what it came to rather than restating a number.
    _band = [(c, M.ended_by_signal(c, "")[0]) for c in range(128, 166)]
    _taken = [c for c, name in _band if name]
    _left = [c for c, name in _band if not name]
    check("sk6 ...and a signal that does not TERMINATE by default is not a kill "
          "either: `128 + SIGWINCH` is an exit code, because nothing was ever "
          "killed by SIGWINCH. The table is spelled as NAMES and resolved on "
          "THIS machine, since `SIGBUS` is 7 on linux and 10 on darwin - a "
          "numeric table would name the wrong signal on one of the two "
          "platforms and there would be no way to see it from the other. "
          "Accepted inside the reported band: %r; declined: %r"
          % (_taken, _left),
          M.ended_by_signal(128 + getattr(signal, "SIGWINCH", 28),
                            "")[0] is None
          and "SIGWINCH" not in M.TERMINATING_SIGNALS
          and "SIGSEGV" in M.TERMINATING_SIGNALS
          and M._signal_name(11) == "SIGSEGV"
          and M._signal_name(9999) is None
          # BOTH ENDS OF THE BAND ARE NON-EMPTY, which is what stops this
          # reading as "the table accepts everything" or "accepts nothing" -
          # either would satisfy a one-sided assertion.
          and 139 in _taken and 128 in _left and _taken and _left)

    def _our_teardown(_project, _command, timeout=None):
        return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}

    res_td = M.run_gate(tmp, [("test", "pytest -q")], runner=_our_teardown,
                        timeout=3)
    check("sk7 OUR OWN TEARDOWN IS NOT THE OS ENDING THE RUN: a timed-out step "
          "arrives at `-9` because `_tear_down` killed the group, and reading "
          "that here would relabel EVERY timeout as infrastructure. The "
          "wrapper's own observation outranks this inference, so the step keeps "
          "`timed-out` and carries no signal at all: %r"
          % ((res_td["status"], res_td["steps"][0].get("outcome"),
              res_td["steps"][0].get("signal")),),
          res_td["status"] == M.TIMED_OUT
          and res_td["steps"][0].get("outcome") == M.TIMED_OUT
          and res_td["steps"][0].get("signal") is None)
    _obs = M.ended_by_signal(-11, "")[1]
    _conv = M.ended_by_signal(139, "")[1]
    check("sk8 THE TWO CHANNELS CARRY DIFFERENT BASES, because they are not "
          "equally strong: a negative code is what the OS REPORTED and no child "
          "can return one, while `128 + N` is the shell's CONVENTION and a real "
          "program may choose that number. A reader deciding whether to believe "
          "the word needs to know which they have, so the sentences are "
          "asserted as MUTUALLY EXCLUSIVE and not merely as different, which is "
          "the clause a single collapsed sentence carrying both words would "
          # SLICED THROUGH `or ""` SO THE LABEL CANNOT RAISE. Both of these are
          # None on a version where the arm does not fire, and a subscript in the
          # label then escapes before `check()` is ever entered - which took 83
          # later cases out of a mutation run and named none of them. The
          # assertion below is what decides; the label only has to survive being
          # written.
          "satisfy: %r / %r" % ((_obs or "")[:60], (_conv or "")[:60]),
          # ...and the `or ""` is the assertion's, not only the label's: both are
          # None on a version where the arm never fires, and `in None` RAISES
          # rather than answering False - a case that cannot go red because it
          # takes the suite down instead is the same silence as one that cannot
          # go red at all.
          "observed and not inferred" in (_obs or "")
          and "convention" not in (_obs or "")
          and "shell's convention" in (_conv or "")
          and "observed" not in (_conv or "")
          and _obs and _conv and _obs != _conv)
    check("sk9 a garbage exit code is `(None, None)` rather than a raise - "
          "`run_gate` hands this whatever the runner seam returned, and a "
          "fixture that answered None must not take the whole run down. The TEXT "
          "side takes the same treatment: `_shell` returns None for a step it "
          "could not decode, and `reached_a_verdict` has to read that as 'no "
          "report' rather than raising inside a verdict: %r"
          % ([M.ended_by_signal(v, None) for v in (None, "x", "")],),
          all(M.ended_by_signal(v, None) == (None, None)
              for v in (None, "x", "", 3.5j))
          and M.reached_a_verdict(None) is False
          and M.ended_by_signal(139, None)[0] == "SIGSEGV")

    def _zero_then_killed(_project, _command, _timeout=None):
        return -11, "Tests  no tests\n", {}

    res_zk = M.run_gate(tmp, [("test", "npx jest")], runner=_zero_then_killed)
    lines_zk = []
    M.render(res_zk, out=lines_zk.append)
    check("sk10 ...and `NO CHECK RAN` does NOT also fire over a killed run that "
          "reached a positive zero. That sentence's claim is 'that is exit 0', "
          "which `-11` makes false - the same zero, a different fact, and the "
          "kill line already said which. The count still travels on the run, so "
          "nothing is lost by the silence: ranTotal=%r"
          % (res_zk["ranTotal"],),
          res_zk["ranTotal"] == 0
          and res_zk["status"] == M.CANNOT_RUN
          and "THE OS ENDED" in "\n".join(lines_zk)
          and "NO CHECK RAN" not in "\n".join(lines_zk))
    check("sk11 THE RECORD KEEPS ENOUGH TO RE-DERIVE THE SIGNAL AND NO COPY OF "
          "IT. `exit` and `outcome` are both already in `_evidence_io.STEP_KEYS`, "
          "so a committed row carries `-9` beside `could-not-run` and a reader a "
          "week later can name the signal - while `signal` and `signalBasis` "
          "stay off the row, because a claim a row can be read for is not cached "
          "twice (`row_for` makes that argument for `treeMutatedOwned`): %r"
          % (sorted(_ev_io.STEP_KEYS),),
          "exit" in _ev_io.STEP_KEYS and "outcome" in _ev_io.STEP_KEYS
          and "signal" not in _ev_io.STEP_KEYS
          and "signalBasis" not in _ev_io.STEP_KEYS)

    # --- rk: a step the OS ended is run once more, and says so -------------
    # THE ORDER OF THIS BLOCK IS THE ARGUMENT IT MAKES. The inverse risk is the
    # one that has actually cost this project - a real failure excused as
    # infrastructure, re-run, and passed on a later roll - so the case that pins
    # a genuine red as neither retried nor reclassified is written FIRST, before
    # any case that asserts a retry happens at all. It asserts the thing a
    # loosened guard breaks: the runner seam is asked once.
    #
    # EVERY CASE HERE IS WRITTEN ON A NEGATIVE EXIT CODE, which is the channel
    # the OS reports rather than the one a shell converts, so none of them needs
    # a platform skip: `SIGSEGV` and `SIGABRT` are defined wherever
    # `signal.Signals` is, while `SIGKILL` is not.
    def _answers(replies):
        """A runner that answers from a list and RECORDS what it was asked.

        The COMMAND each call received is the evidence, not only the number of
        calls: a retry that fired and changed nothing and a retry that never
        fired are different defects, and a tally cannot tell them apart.
        """
        asked = []

        def _run(_project, command, _timeout=None):
            asked.append(command)
            return replies[min(len(asked) - 1, len(replies) - 1)]

        return asked, _run

    rk_gate = "npx mocha --parallel --jobs 4"
    rk_red_asked, rk_red_runner = _answers([(139, MOCHA_JSON, {})])
    res_rk_red = M.run_gate(tmp, [("test", rk_gate)], runner=rk_red_runner)
    check("rk0 A GENUINE RED IS NEITHER RE-ROLLED NOR RECLASSIFIED, and this is "
          "the case that had to exist before the retry did. `mocha --reporter "
          "json` at exit 139 carries an END-OF-RUN REPORT, so the step measured "
          "and spoke for its own status - it is asked ONCE, it stays `failed`, "
          "and it carries no retry field. A retry keyed on the exit code rather "
          "than on the signal passes every case below and fails here: %r"
          % ((rk_red_asked, res_rk_red["status"], res_rk_red["failed"]),),
          rk_red_asked == [rk_gate]
          and res_rk_red["status"] == "failed"
          and res_rk_red["failed"] == ["test"]
          and res_rk_red["steps"][0].get("outcome") is None
          and res_rk_red["steps"][0].get("retriedAfterSignal") is None
          and res_rk_red["steps"][0].get("retryBasis") is None
          # ...and this gate DOES declare a bound the retry could have lowered,
          # so the case cannot pass by the retry having nothing to act on - the
          # only thing stopping it is the report the step printed.
          and M.lowered_parallelism(rk_gate)[0]
          == "npx mocha --parallel --jobs 2")

    rk_ok_asked, rk_ok_runner = _answers([(-11, "", {}),
                                          (0, "Tests  4 passed (4)\n", {})])
    res_rk_ok = M.run_gate(tmp, [("test", "npx vitest run --maxWorkers=4")],
                           runner=rk_ok_runner)
    rk_ok_lines = []
    rk_ok_code = M.render(res_rk_ok, out=rk_ok_lines.append)
    rk_ok_text = "\n".join(rk_ok_lines)
    check("rk1 ...AND A STEP THE OS ENDED IS RUN ONCE MORE, AT A BOUND THE "
          "FIRST ATTEMPT DID NOT HAVE. Before this the run stopped at "
          "`could-not-run` and an operator re-ran it by hand, which is where a "
          "session of them went. The second command is the first with its "
          "worker bound lowered, and the verdict on the row is the SECOND "
          "attempt's - its exit, its count and its duration: %r"
          % ((rk_ok_asked, res_rk_ok["status"],
              res_rk_ok["steps"][0]["exit"], res_rk_ok["steps"][0]["ran"]),),
          rk_ok_asked == ["npx vitest run --maxWorkers=4",
                          "npx vitest run --maxWorkers=2"]
          and res_rk_ok["status"] == "passed"
          and res_rk_ok["steps"][0]["exit"] == 0
          and res_rk_ok["steps"][0]["ran"] == 4
          and res_rk_ok["steps"][0].get("outcome") is None
          and res_rk_ok["steps"][0].get("signal") is None
          # ...while the row still names what ended the first attempt. That is
          # the one fact no other field on the row can be read for, which is why
          # it is the one the retry has to write down.
          and res_rk_ok["steps"][0].get("retriedAfterSignal") == "SIGSEGV"
          and rk_ok_code == M.E_OK
          # A READER WHO SEES ONLY THE GREEN LINE HAS BEEN MISLED, so the note
          # sits ABOVE the banner and names the signal, the flag and both
          # values. The banner literal another document keys its arms on is
          # left unbroken.
          and "RETRIED AFTER A SIGNAL: test" in rk_ok_text
          and "SIGSEGV" in rk_ok_text
          and "`--maxWorkers` was lowered from 4 to 2" in rk_ok_text
          and "different measurement" in rk_ok_text
          # `find`, NEVER `index`. Both are None-free, but `index` RAISES on the
          # version where the note is gone - and an escape here leaves every
          # case after this one out of the run and names none of them, which is
          # the same silence as a case that cannot go red at all.
          and 0 <= rk_ok_text.find("RETRIED AFTER A SIGNAL")
          < rk_ok_text.find("GATE GREEN"))

    _lowered = [(cmd, M.lowered_parallelism(cmd)[0])
                for cmd in ("make -j8 check", "pytest -n 4 -q",
                            "npx jest --maxWorkers=3",
                            "npx playwright test --workers 2",
                            "nvm use 20 && npx jest --maxWorkers=4")]
    check("rk2 THE NEW BOUND IS DERIVED FROM THE COMMAND AND IS NOWHERE "
          "WRITTEN DOWN. A worker count pasted into the script would be a claim "
          "about somebody else's host - the ceiling is memory per worker, so it "
          "moves with the machine and with the suite. Every spelling is read "
          "where it sits and spliced in place, so the rest of the command comes "
          "through byte for byte, preamble and all: %r" % (_lowered,),
          [new for _cmd, new in _lowered]
          == ["make -j4 check", "pytest -n 2 -q", "npx jest --maxWorkers=1",
              "npx playwright test --workers 1",
              "nvm use 20 && npx jest --maxWorkers=2"]
          # SECOND DIRECTION, and it is what makes the short spelling a
          # NARROWING rather than a guess: one letter is the worker count for
          # one runner and the LINE COUNT for a pager, and a gate entry is as
          # often a pipeline as it is one command. So the short flag is read
          # only where the program it sits beside is the runner that spells it
          # that way - asking whether the whole STRING names that runner is the
          # version that lowers a pager's line count and calls the result a
          # smaller measurement.
          and M.lowered_parallelism("npm test | head -n 20")[0] is None
          and M.lowered_parallelism("pytest -q | head -n 20")[0] is None
          # ...and the pager is left alone in the run that really does declare
          # a bound, which is what stops the narrowing above being a mute.
          and M.lowered_parallelism("pytest -n 4 | tail -n 20")[0]
          == "pytest -n 2 | tail -n 20")

    _cannot_cmds = ("npx vitest run", "pytest -n auto", "pytest -n 1",
                    "make -j8 check && pytest -n 4")
    _cannot = [M.lowered_parallelism(cmd)[1] for cmd in _cannot_cmds]
    check("rk3 ...AND WHERE NOTHING CAN BE LOWERED IT SAYS SO RATHER THAN "
          "PRETENDING IT DID. Four states reach that answer and each names "
          "itself: no bound this reader can see, a bound whose value is not a "
          "number, a bound with nothing below it that is still a run, and a "
          "gate entry chaining two runners that each declare one. Asserted as "
          "MUTUALLY DISTINCT, which is what fails a version that collapsed them "
          "into one sentence - and the second attempt then claims only the "
          "moment it ran, never a smaller measurement: %r"
          % ([(b or "")[:44] for b in _cannot],),
          all(M.lowered_parallelism(cmd)[0] is None for cmd in _cannot_cmds)
          and len(set(_cannot)) == len(_cannot)
          and "no worker bound this reader can see" in _cannot[0]
          and "not a number this reader can lower" in _cannot[1]
          and "no bound below it that is still a run" in _cannot[2]
          and "not knowable from the string" in _cannot[3]
          # ...and none of the four claims a reduction. The word the note is
          # built on is what a reader acts on, so a basis that said "lowered"
          # with nothing lowered would be the false half of this whole change.
          and not any("was lowered" in b for b in _cannot))

    rk_run_asked, rk_run_runner = _answers([(-11, "", {}), (0, "", {})])
    res_rk_run = M.run_gate(tmp, [("test", "npx vitest run")],
                            runner=rk_run_runner)
    check("rk3b ...and a gate with no bound to lower is STILL run a second "
          "time, because the first attempt measured nothing at all and a host "
          "that was starving one measurement of CPU may not be starving the "
          "next. What must not happen is the claim: the same command ran twice, "
          "so the note says the moment changed and refuses to say the work "
          # READ THROUGH `.get(..., "")`, for the reason sk8 states: the key is
          # absent on a version where the retry does not happen, and a subscript
          # in the label escapes before `check()` is ever entered.
          "did: %r"
          % ((rk_run_asked,
              res_rk_run["steps"][0].get("retryBasis", "")[-60:]),),
          rk_run_asked == ["npx vitest run", "npx vitest run"]
          and res_rk_run["steps"][0].get("retriedAfterSignal") == "SIGSEGV"
          and "only the moment it ran" in res_rk_run["steps"][0].get(
              "retryBasis", "")
          and "was lowered" not in res_rk_run["steps"][0].get("retryBasis", ""))

    rk_red2_asked, rk_red2_runner = _answers(
        [(-11, "", {}), (1, "Tests  1 failed | 3 passed (4)\n", {})])
    res_rk_red2 = M.run_gate(tmp, [("test", "npx vitest run --maxWorkers=4")],
                             runner=rk_red2_runner)
    rk_red2_lines = []
    M.render(res_rk_red2, out=rk_red2_lines.append)
    rk_red2_text = "\n".join(rk_red2_lines)
    check("rk4 A RETRY MAY NOT TURN A RED INTO A RUN THAT REACHED NO VERDICT, "
          "which is the same fault as rk0 with the attempts the other way "
          "round. The second attempt came back red HAVING MEASURED, so the "
          "verdict is `failed` and the banner is `GATE RED` - the kill that "
          "ended the first attempt is an observation beside it and not a word "
          "that outranks it. A version that carried the first attempt's outcome "
          "forward would print an infrastructure banner over a measured red: %r"
          % ((res_rk_red2["status"], res_rk_red2["failed"],
              res_rk_red2["steps"][0].get("outcome")),),
          res_rk_red2["status"] == "failed"
          and res_rk_red2["failed"] == ["test"]
          and res_rk_red2["steps"][0].get("outcome") is None
          and "GATE RED: test" in rk_red2_text
          and "GATE COULD NOT RUN" not in rk_red2_text
          # ...and the run is STILL legible as a second attempt, which is the
          # half that separates this from simply forgetting the first one.
          and res_rk_red2["steps"][0].get("retriedAfterSignal") == "SIGSEGV"
          and "RETRIED AFTER A SIGNAL: test" in rk_red2_text)

    # THE THIRD REPLY EXISTS SO A THIRD ATTEMPT IS OBSERVABLE RATHER THAN
    # ENDLESS, and it is GREEN on purpose: a version that kept retrying while
    # the step came back killed would reach it, print `GATE GREEN` over a run
    # that was ended by a signal twice, and hang instead of failing if the only
    # reply left were another kill. The correct runner never asks for it.
    #
    # THE SECOND KILL IS `-signal.SIGABRT`, NEVER THE LITERAL `-6`. SIGSEGV is
    # 11 on both POSIX and windows, which is what let every case above get away
    # with pasting the number - but SIGABRT is 6 on POSIX and 22 in the windows
    # CRT's own `<signal.h>`, so a hardcoded `-6` asks `_signal_name` a question
    # windows answers "signal 6", not "SIGABRT" - failing this case for a wrong
    # fixture rather than a wrong reader. Reading the platform's own constant is
    # the fix; `-11` above is left as a literal deliberately, because THAT
    # number is not the bug and does not need the same asking.
    rk_twice_asked, rk_twice_runner = _answers(
        [(-11, "", {}), (-signal.SIGABRT, "", {}),
         (0, "Tests  1 passed (1)\n", {})])
    res_rk_twice = M.run_gate(tmp, [("test", "make -j8 check")],
                              runner=rk_twice_runner)
    rk_twice_lines = []
    rk_twice_code = M.render(res_rk_twice, out=rk_twice_lines.append)
    rk_twice_text = "\n".join(rk_twice_lines)
    check("rk5 A SECOND SIGNAL DEATH IS NOT A THIRD ATTEMPT. The seam is asked "
          "exactly twice and the run is an honest `could-not-run` naming BOTH "
          "attempts and both signals - a step ended by a signal under the bound "
          "it declared and again under a smaller one is a host that cannot run "
          "this gate, which is a thing to repair rather than to keep rolling "
          "for. A loop, a budget or a configurable count fails here: %r"
          % ((len(rk_twice_asked), res_rk_twice["status"],
              res_rk_twice["steps"][0].get("signal"),
              res_rk_twice["steps"][0].get("retriedAfterSignal")),),
          rk_twice_asked == ["make -j8 check", "make -j4 check"]
          and res_rk_twice["status"] == M.CANNOT_RUN
          and res_rk_twice["failed"] == []
          and res_rk_twice["steps"][0].get("signal") == "SIGABRT"
          and res_rk_twice["steps"][0].get("retriedAfterSignal") == "SIGSEGV"
          and rk_twice_code == M.E_FAIL
          # THE BANNER IS THE ONE ANOTHER DOCUMENT ALREADY KEYS ITS
          # INFRASTRUCTURE ARM ON, so a second kill costs no retry of the
          # orchestrator's either - and the two signals are printed apart,
          # because they are two observations and a reader deciding what to fix
          # needs both.
          and "GATE COULD NOT RUN" in rk_twice_text
          and "THE OS ENDED test (SIGABRT)" in rk_twice_text
          and "ended by SIGSEGV" in rk_twice_text
          and "there is no third" in rk_twice_text
          and "GATE RED" not in rk_twice_text)

    _ident_rk = {"runId": "run-retried", "ts": "2026-09-12T00:00:00Z"}
    row_rk = _ev_io.row_for(tmp, res_rk_ok, "phase", {"phaseId": "P1"},
                            _ident_rk)
    check("rk6 AND ALL THREE SURFACES CARRY IT, because the row is the one read "
          "a week later. `_evidence_io.STEP_KEYS` is what decides: a key the "
          "allow-list does not name is dropped in silence, so the fact would "
          "live in memory for the length of the run and be absent from the only "
          "copy anybody keeps - and unlike the signal it can be re-derived from "
          "NOTHING else on the row, since exit, count, duration and outcome all "
          "describe the attempt that answered: %r"
          % ((row_rk["steps"][0].get("retriedAfterSignal"),
              row_rk["steps"][0].get("retryBasis", "")[:40]),),
          "retriedAfterSignal" in _ev_io.STEP_KEYS
          and "retryBasis" in _ev_io.STEP_KEYS
          and row_rk["steps"][0].get("retriedAfterSignal") == "SIGSEGV"
          and "lowered from 4 to 2" in row_rk["steps"][0].get("retryBasis", "")
          # ...and the MACHINE-READABLE half is the same dict `main`'s `--json`
          # arm dumps, so it is asserted through a real round trip rather than
          # by reading the key off the object that produced it.
          and json.loads(json.dumps(res_rk_ok))["steps"][0]["retriedAfterSignal"]
          == "SIGSEGV"
          # ...while a step nothing happened to carries NEITHER key, so an
          # ordinary row does not grow two fields to say so.
          and _ev_io.row_for(tmp, res_rk_red, "phase", {"phaseId": "P1"},
                             _ident_rk)["steps"][0].get("retryBasis") is None
          and _ev_io.row_for(tmp, res_rk_red, "phase", {"phaseId": "P1"},
                             _ident_rk)["steps"][0]
          .get("retriedAfterSignal") is None)

    rk_to_asked, rk_to_runner = _answers(
        [(-9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": 3})])
    res_rk_to = M.run_gate(tmp, [("test", "pytest -n 8")], runner=rk_to_runner,
                           timeout=3)
    rk_ns_asked, rk_ns_runner = _answers(
        [(127, "could not run: no such file", {"outcome": M.CANNOT_RUN})])
    res_rk_ns = M.run_gate(tmp, [("test", "pytest -n 8")], runner=rk_ns_runner)
    check("rk7 THE OTHER TWO NO-VERDICT MEMBERS ARE NOT RETRIED, and each is "
          "declined for its own reason. A timed-out step arrives at a negative "
          "code because OUR teardown killed it, so re-running it buys a second "
          "wait at the same bound; a runner that never started answers the same "
          "way however many workers it is asked for. Both commands declare a "
          "bound this reader CAN lower, so neither passes by having nothing to "
          "act on: %r"
          % ((rk_to_asked, res_rk_to["status"], rk_ns_asked,
              res_rk_ns["status"]),),
          len(rk_to_asked) == 1 and len(rk_ns_asked) == 1
          and res_rk_to["status"] == M.TIMED_OUT
          and res_rk_ns["status"] == M.CANNOT_RUN
          and res_rk_to["steps"][0].get("retriedAfterSignal") is None
          and res_rk_ns["steps"][0].get("retriedAfterSignal") is None
          and M.lowered_parallelism("pytest -n 8")[0] == "pytest -n 4")

    # --- what state was actually tested ------------------------------------
    # `head` alone cannot answer this and never could: a TASK gate runs BEFORE the
    # task commit, so a run executes against HEAD plus staged edits plus unstaged
    # ones plus untracked files. Two failed retries at one HEAD were
    # indistinguishable, which defeats the point of recording retries at all.
    # The fixture had staged `tracked.txt` and never committed, so `rev-parse
    # HEAD` had nothing to answer with - and "the two runs share a head" would
    # then have been None == None, true with the field absent. One commit gives
    # the comparison something real to be about. Identity is passed per command
    # rather than written into the repo config, so the fixture keeps no state a
    # later case could read.
    subprocess.run(["git", "-C", tmp, "-c", "user.email=fixture@example.com",
                    "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "base"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    scope_a = os.path.join(tmp, "scope_a.py")
    owns = ["scope_a.py"]

    def _write(path, text):
        with open(path, "w") as fh:
            fh.write(text)

    _write(scope_a, "v = 1\n")
    r1 = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    _write(scope_a, "v = 2\n")
    r2 = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    st1, st2 = r1.get("testedState") or {}, r2.get("testedState") or {}
    check("ts1 THE REQUIREMENT: two runs at the SAME head against different "
          "declared content are told apart by `scopeDigest`. Asserted as a pair "
          "- the heads equal AND the digests differing - because either half "
          "alone passes with the field absent: head=%r digests differ=%r"
          % (st1.get("head") == st2.get("head"),
             st1.get("scopeDigest") != st2.get("scopeDigest")),
          st1.get("head") is not None
          and st1.get("head") == st2.get("head")
          and st1.get("scopeDigest") is not None
          and st1.get("scopeDigest") != st2.get("scopeDigest"))

    _write(scope_a, "v = 1\n")

    def _rewrites_scope(project, _command, _timeout=None):
        # `isort`/`black`'s shape again, but aimed at a file the work DECLARES.
        with open(os.path.join(project, "scope_a.py"), "w") as fh:
            fh.write("v = 999\n")
        return 0, "Passed\n", {}

    r_mut = M.run_gate(tmp, [("lint", "true")], runner=_rewrites_scope, owns=owns)
    r_post = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    st_mut, st_post = r_mut.get("testedState") or {}, r_post.get("testedState") or {}
    check("ts2 THE PLACEMENT: a gate that REWRITES a declared file leaves "
          "`scopeDigest` at the content it was asked to judge, not the content "
          "it produced. Taken before the first command for exactly this - a "
          "fix-in-place runner rewrites the files it checks, and a digest read "
          "afterwards would answer a different question than the one asked: "
          "pre==mut %r, post!=mut %r"
          % (st_mut.get("scopeDigest") == st1.get("scopeDigest"),
             st_post.get("scopeDigest") != st_mut.get("scopeDigest")),
          st_mut.get("scopeDigest") == st1.get("scopeDigest")
          and st_post.get("scopeDigest") != st_mut.get("scopeDigest"))

    _write(scope_a, "v = 1\n")
    r_before = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    stray = os.path.join(tmp, "stray_outside_scope.txt")
    _write(stray, "x\n")
    r_after = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    sb, sa = r_before.get("testedState") or {}, r_after.get("testedState") or {}
    check("ts3 a file appearing OUTSIDE the declared scope moves `dirtyDigest` "
          "while `scopeDigest` holds still - the two answer different questions "
          "and are asserted apart, since one field doing both would hide "
          "whichever it was not looking at: scope same=%r dirty differs=%r"
          % (sb.get("scopeDigest") == sa.get("scopeDigest"),
             sb.get("dirtyDigest") != sa.get("dirtyDigest")),
          sb.get("scopeDigest") == sa.get("scopeDigest")
          and sb.get("dirtyDigest") is not None
          and sb.get("dirtyDigest") != sa.get("dirtyDigest"))

    _write(stray, "x changed but still untracked\n")
    r_limit = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=owns)
    sl = r_limit.get("testedState") or {}
    check("ts4 THE LIMIT, PINNED RATHER THAN HIDDEN: editing an ALREADY-DIRTY "
          "file outside the declared scope moves NEITHER digest. `dirtyDigest` "
          "records which paths were dirty, not their contents - so this evidence "
          "distinguishes the realistic retry and must never be sold as a "
          "reproducible snapshot of the repository: %r"
          % ((sl.get("scopeDigest") == sa.get("scopeDigest"),
              sl.get("dirtyDigest") == sa.get("dirtyDigest")),),
          sl.get("scopeDigest") is not None
          and sl.get("dirtyDigest") is not None
          and sl.get("scopeDigest") == sa.get("scopeDigest")
          and sl.get("dirtyDigest") == sa.get("dirtyDigest"))
    os.remove(stray)

    r_missing = M.run_gate(tmp, [("lint", "true")], runner=_quiet,
                           owns=["scope_a.py", "no_such_file.py"])
    sm = r_missing.get("testedState") or {}
    check("ts5 a declared file that is NOT THERE is hashed as null and counted "
          "in the basis - absent is itself evidence about the state under test, "
          "and dropping it would let two different scopes share a digest: %r"
          % (sm.get("scopeBasis"),),
          sm.get("scopeDigest") is not None
          and sm.get("scopeDigest") != st1.get("scopeDigest")
          and "1 missing" in (sm.get("scopeBasis") or ""))

    r_noscope = M.run_gate(tmp, [("lint", "true")], runner=_quiet, owns=[])
    sn = r_noscope.get("testedState") or {}
    check("ts6 work that declares no files has no scope digest and SAYS so - "
          "the shape `coverage` already uses for the same question, because a "
          "digest of nothing would compare equal across every such run: %r"
          % ((sn.get("scopeDigest"), sn.get("scopeBasis")),),
          sn.get("scopeDigest") is None
          and "declares no files" in (sn.get("scopeBasis") or ""))

    r_norepo = M.run_gate(notrepo, [("lint", "true")], runner=_quiet, owns=owns)
    sr = r_norepo.get("testedState") or {}
    check("ts7 where git cannot describe the tree, `dirtyDigest` is None - not "
          "a hash of an empty set, which is a real digest that would compare "
          "equal to any other unanswerable run and read as agreement: %r"
          % ((sr.get("dirtyDigest"), sr.get("dirtyBasis")),),
          sr.get("dirtyDigest") is None
          and sr.get("head") is None
          and "git could not" in (sr.get("dirtyBasis") or "")
          and sr.get("scopeDigest") is not None)

    check("ts8 `head` carries the basis that says what it is NOT. It is the "
          "repository HEAD at execution time and it does not identify the "
          "tested state, because a task gate runs before the task commit - a "
          "field that claimed otherwise would be the overclaim this block "
          "exists to retire: %r" % (st1.get("headBasis"),),
          "does not identify the tested state" in (st1.get("headBasis") or ""))

    # --- whose gate is this, anyway ----------------------------------------
    # `--task` narrowed only the COVERAGE question before this: `gate_of` read
    # `phase.testGate` whatever it was handed, so a task declaring its own
    # `tests.gate` had no way to be run through this bracket at all. That is the
    # level every question the evidence has to answer actually lives at.
    gman = {"meta": {"version": 2,
                     "buildCommands": {"unit": "pytest -q tests/unit",
                                       "lint": "ruff check ."}},
            "phases": [{"id": "PG", "title": "g", "status": "in_progress",
                        "testGate": ["lint"], "tasks": [
                            {"id": "PG.1", "files": ["a.py"],
                             "tests": {"mode": "tdd", "gate": ["unit"]}},
                            {"id": "PG.2", "files": ["b.py"],
                             "tests": {"mode": "gate-only", "gate": []}},
                            {"id": "PG.3", "files": ["c.py"],
                             "tests": {"mode": "gate-only",
                                       "gate": ["echo literal-task"]}},
                            {"id": "PG.4", "files": ["d.py"]}]},
                       {"id": "PH", "title": "h", "status": "pending",
                        "testGate": [], "tasks": [
                            {"id": "PH.1", "files": ["e.py"],
                             "tests": {"mode": "tdd", "gate": ["unit"]}}]}]}

    cmds, source, err = M.gate_of(gman, "PG", "PG.1")
    check("gs1 a task that declares `tests.gate` is run through ITS commands, "
          "resolved by the same `meta.buildCommands` pass the phase gate uses - "
          "a second resolution would be a second answer to what a gate is: "
          "%r %r" % (cmds, source),
          err is None and source == "task"
          and cmds == [("unit", "pytest -q tests/unit")])

    cmds, source, err = M.gate_of(gman, "PG", "PG.2")
    check("gs2 ...and a task declaring an EMPTY gate falls back to the phase's, "
          "SAYING which it used. The fallback is the half that must not be "
          "silent: a phase gate measured against one task's files is a "
          "different claim from that task's own gate: %r %r" % (cmds, source),
          err is None and source == "phase"
          and cmds == [("lint", "ruff check .")])

    cmds4, source4, _e4 = M.gate_of(gman, "PG", "PG.4")
    check("gs3 ...and so does a task with no `tests` block at all - absent and "
          "empty are the same answer to 'does this task declare a gate', and "
          "they must not be two code paths: %r %r" % (cmds4, source4),
          source4 == "phase" and cmds4 == cmds)

    cmds3, source3, _e3 = M.gate_of(gman, "PG", "PG.3")
    check("gs4 a task gate entry naming no build command is carried VERBATIM, "
          "exactly as rg2 draws it for a phase - refusing it here would make "
          "this script decide what a task's gate may be: %r" % (cmds3,),
          source3 == "task" and cmds3 == [("echo literal-task",
                                           "echo literal-task")])

    cmdsh, sourceh, _eh = M.gate_of(gman, "PH", "PH.1")
    check("gs5 a task gate wins even where the PHASE declares nothing - the "
          "empty phase gate is a designed state for sign-off, not a veto over "
          "the task that ran under it: %r %r" % (cmdsh, sourceh),
          sourceh == "task" and cmdsh == [("unit", "pytest -q tests/unit")])

    _cn, _sn, errn = M.gate_of(gman, "PG", "PG.9")
    check("gs6 an unknown task is an ERROR, never a silent fall back to the "
          "phase - 'this task declares no gate' and 'there is no such task' are "
          "two different answers, the distinction rg3 already draws one noun "
          "up: %r" % (errn,),
          _cn is None and "no task" in (errn or ""))

    gman_cleared = json.loads(json.dumps(gman))
    gman_cleared["phases"][0]["tasks"][1]["tests"]["gateBasis"] = "cleared"
    cmdsc, sourcec, errc = M.gate_of(gman_cleared, "PG", "PG.2")
    check("gs8 a task whose gate was CLEARED (`gateBasis: cleared`) resolves "
          "EMPTY at task scope, as `commands/task.md` promises for "
          "`--gate-clear`: the operator said nothing here can grade this task, "
          "and borrowing the phase's gate would grade it anyway. gs2 is the "
          "other half - an empty gate with no such basis still falls back: %r"
          % ((cmdsc, sourcec, errc),),
          errc is None and cmdsc == [] and sourcec == "task")

    cmdsp, sourcep, _ep = M.gate_of(gman, "PG")
    check("gs7 ...and with no task named at all the answer is the phase's gate, "
          "unchanged - this is the call site the script has had all along and "
          "it must not move: %r %r" % (cmdsp, sourcep),
          sourcep == "phase" and cmdsp == [("lint", "ruff check .")])

    # --- every declared entry runs, and in declaration order ---------------
    # THE MEASUREMENT CAME FIRST AND IS WHAT MADE THIS A PIN RATHER THAN A
    # CHANGE. Field data on a large phase: the suite dominated every recorded
    # gate, the typecheck entry was a small fraction of it, and the one genuine
    # cross-task breakage of that phase surfaced as a TYPE error rather than as a
    # failing test - a required parameter added to a service method, breaking call
    # sites in a test file the task never opened. The obvious conclusion, put the
    # cheap entry first and stop at the first red, rests on a premise nobody had
    # checked: that `run_gate` stops at all. IT DOES NOT. Every entry runs, in
    # declaration order, whatever an earlier one exited - so there was no ordering
    # to change, and the saving that report wanted could only come from ADDING a
    # short circuit.
    #
    # WHICH IS THE CHANGE THESE CASES REFUSE, and `steps` is the reason. Today
    # `steps` is both what ran and the whole declared list, so `failed` can be
    # read against it and `ranTotal` is a total rather than a floor. Stop at the
    # first red and a one-step `failed` row can no longer be told from a
    # one-entry gate, while `ranTotal`, `countsBasis` and the coverage answer -
    # each summed or scraped over EVERY step - quietly begin describing a prefix.
    # That is a record that can no longer be audited, the same defect already
    # repaired one field over for `gateSource`, and it would be paid on every
    # red run to save time on the runs that are already going to be re-run.
    #
    # AND THE TRAP, WHICH NO ORDERING MAY EVER BE READ AS PERMISSION TO SPRING. A
    # task gate of the cheap entry alone is not a narrowed suite; it is a
    # different question. The suite asks whether behaviour still holds and the
    # typecheck asks whether the program still type-checks, and the same phase
    # carried a task that changed a validation decorator so every schema default
    # began taking effect on every route - types impeccable throughout. So the
    # measurement says the cheap entry caught THAT breakage, never that it catches
    # breakages, and the entry that asks the behaviour question has to run on
    # every run that could pass.
    ordroot = _harness.fixture_root("run-test-gate-order-")
    subprocess.run(["git", "init", "-q", ordroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(ordroot, "src.py"), "w") as fh:
        fh.write("x = 1\n")
    for arg in (["add", "--", "src.py"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", ordroot] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # A DIFFERENT CHECK COUNT PER ENTRY, so a prefix sum and a total sum are
    # different numbers. With equal counts both readings produce the same
    # `ranTotal` and the case survives the mutation it exists for.
    order_checks = {"cheap": 1, "middle": 2, "expensive": 4}
    seen = []

    def _counting(_project, command, _timeout=None):
        seen.append(command)
        return ((1 if command == "cheap" else 0),
                "=== %d passed in 0.01s ===\n" % (order_checks[command],), {})

    ordered = M.run_gate(ordroot, [("typecheck", "cheap"), ("lint", "middle"),
                                   ("suite", "expensive")], runner=_counting)
    check("eo1 a FAILING first entry does not stop the run: the runner is called "
          "for every declared entry, in declaration order. This is the answer the "
          "field report needed and nothing had established - the gate has no "
          "short circuit to reorder, so a cheap entry placed first buys a reader "
          "the earlier line and buys the clock nothing: %r" % (seen,),
          seen == ["cheap", "middle", "expensive"])

    check("eo2 ...and every one of them is on the record, in the same order, "
          "with its own exit. `steps` is what ran AND the whole declared list, "
          "which is what lets `failed` be read against it: %r"
          % ([(s["name"], s["exit"]) for s in ordered["steps"]],),
          [(s["name"], s["exit"]) for s in ordered["steps"]]
          == [("typecheck", 1), ("lint", 0), ("suite", 0)]
          and ordered["failed"] == ["typecheck"]
          and ordered["status"] == "failed")

    check("eo3 ...so `ranTotal` is a TOTAL and not a floor, and its basis says so "
          "over every step. A run that stopped at the first red would answer 1 "
          "here and carry a sentence about a complete count, which is the reading "
          "that turns a prefix into a measurement: %r"
          % ((ordered["ranTotal"], ordered["countsBasis"]),),
          ordered["ranTotal"] == sum(order_checks.values())
          and "floor" not in ordered["countsBasis"])

    green = []

    def _all_green(_project, command, _timeout=None):
        green.append(command)
        return 0, "=== 3 passed in 0.01s ===\n", {}

    passing = M.run_gate(ordroot, [("typecheck", "cheap"),
                                   ("suite", "expensive")], runner=_all_green)
    check("eo4 SECOND DIRECTION, and it is the one that looks vacuous: a run "
          "whose CHEAP entry passes still runs the expensive one. It is green by "
          "construction on a build that stops only at a red, which is exactly why "
          "it is here - it is the only case that fails when a stop becomes "
          "unconditional, and the expensive entry is the one that asks whether "
          "behaviour still holds. A typecheck cannot answer that question for it: "
          "%r" % (green,),
          green == ["cheap", "expensive"] and passing["status"] == "passed")

    # --- which attempt, read off the plan ----------------------------------
    # EVERY TASK HERE RECORDS SOMETHING DIFFERENT, and the values are picked so a
    # wrong reading cannot land on the right answer: the phase's first task
    # records a count, so an implementation that answered the phase scope with
    # "the phase's first task" would return that number instead of nothing.
    aman = {"meta": {"version": 2},
            "phases": [{"id": "PA", "title": "a", "tasks": [
                {"id": "PA.1", "attempts": 3},
                {"id": "PA.2", "attempts": 0},
                {"id": "PA.3"},
                {"id": "PA.4", "attempts": True},
                {"id": "PA.5", "attempts": "2"}]}]}

    check("ao1 the attempt a run is stamped with comes from the task's own "
          "`attempts`, unchanged - this runner does not count the execution it "
          "is part of, because the orchestrator owns that number: %r"
          % (M.attempt_of(aman, "PA.1"),),
          M.attempt_of(aman, "PA.1") == 3)

    check("ao2 a recorded 0 travels as 0. The plan takes this count back down on "
          "a reverted increment and on a reset, so it is a value the plan WROTE "
          "and reading it as one attempt would report a run the plan denies: %r"
          % (M.attempt_of(aman, "PA.2"),),
          M.attempt_of(aman, "PA.2") == 0
          and M.attempt_of(aman, "PA.2") is not None)

    check("ao3 a task that records NO attempts answers None, which the row "
          "spells as an absent field - 'the plan does not say how many times "
          "this ran' has no number, and any number here would be invented: %r"
          % (M.attempt_of(aman, "PA.3"),),
          M.attempt_of(aman, "PA.3") is None)

    check("ao4 a PHASE-scope run answers None even where the phase's tasks each "
          "record a count. `attempts` is a task field, so there is nothing to "
          "read and nothing to borrow from a neighbour: %r"
          % (M.attempt_of(aman, None),),
          M.attempt_of(aman, None) is None)

    check("ao5 `attempts: true` and `attempts: \"2\"` record nothing either - "
          "`True` is an `int` in Python, so a plan carrying it would otherwise "
          "read as one attempt: %r"
          % ((M.attempt_of(aman, "PA.4"), M.attempt_of(aman, "PA.5")),),
          M.attempt_of(aman, "PA.4") is None
          and M.attempt_of(aman, "PA.5") is None)

    check("ao6 a task this manifest does not carry answers None rather than "
          "raising - `gate_of` and `owned_files` have already refused an unknown "
          "id by the time a row is being assembled, and a recorder that raised "
          "here would lose a run that DID happen: %r"
          % (M.attempt_of(aman, "PA.9"),),
          M.attempt_of(aman, "PA.9") is None)

    # --- the measurement boundary, end to end ------------------------------
    # THE HEADLINE OF THE RECORDING CHANGE. The evidence file, the journal and the
    # manifest all live INSIDE the repository this run has just described with
    # `git status --porcelain`. A write above the post-run snapshot would appear
    # in the very comparison it is being judged by, and the gate would report
    # itself as having rewritten the tree.
    recroot = _harness.fixture_root("run-test-gate-record-")
    os.makedirs(os.path.join(recroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(recroot, ".claude"))
    with open(os.path.join(recroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    rmpath = os.path.join(recroot, "docs", "audit", "audit-plan.json")
    with open(rmpath, "w") as fh:
        json.dump({"meta": {"version": 3, "buildCommands": {"ok": "true"}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    rshard = os.path.join(recroot, "docs", "audit", "phases", "P1.json")
    # THE THREE TASKS ARE THE THREE ANSWERS `attempts` HAS, and the values are
    # chosen so a wrong implementation cannot produce them: P1.2 records TWO, so
    # the `or 1` shape reads 1 and disagrees; P1.3 records ZERO, which is a value
    # the plan wrote and not a gap; P1.1 records nothing at all, which no number
    # may stand in for.
    with open(rshard, "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["ok"], "tasks": [
                       {"id": "P1.1", "title": "t", "status": "in_progress",
                        "files": []},
                       {"id": "P1.2", "title": "retried", "status": "in_progress",
                        "attempts": 2, "files": []},
                       {"id": "P1.3", "title": "reset", "status": "pending",
                        "attempts": 0, "files": []},
                       # THE ONLY TASK HERE THAT DECLARES A GATE, and it exists
                       # so the provenance cases below have both answers to
                       # compare inside ONE fixture. Its entry is the phase's
                       # own `ok`, deliberately: two rows whose `steps` are
                       # identical and whose provenance differs is the pair a
                       # reader cannot separate without the field, and a task
                       # gate spelled differently would let a case pass by
                       # reading the step name instead.
                       {"id": "P1.4", "title": "own gate", "status": "pending",
                        "files": [], "tests": {"mode": "gate-only",
                                               "gate": ["ok"]}}]}, fh)
    subprocess.run(["git", "init", "-q", recroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # AND THE FIXTURE IS COMMITTED, which is load-bearing here rather than tidy.
    # `git status --porcelain` collapses an UNTRACKED directory to one
    # `?? docs/` line, so on an uncommitted fixture a write into
    # `docs/audit/audit-plan.json` inside the measurement window changes no
    # porcelain line at all: rc1's `"MUTATED" not in text` clause then has
    # nothing to compare and the case stands on its exit code alone, which is
    # green whatever the placement. Measured both ways with a recording write
    # injected between the two snapshots - uncommitted rc1 stayed GREEN, and on
    # this committed fixture it goes red naming the write.
    for arg in (["add", "--", "docs", ".claude"],
                ["-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", recroot] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    lines = []
    code = M.main([rmpath, "P1", "--project-dir", recroot, "--record"],
                  out=lines.append)
    text = "\n".join(lines)
    shard_after = json.loads(open(rshard).read())
    ev_files = os.listdir(os.path.join(recroot, "docs", "audit", "evidence"))
    check("rc1 THE BOUNDARY: recording writes the row, the journal and the "
          "pointer during this invocation, and the gate still reports the tree "
          "UNCHANGED. Move any of those writes above the post-run snapshot and "
          "the runner accuses itself of the rewrite it exists to catch: exit=%r "
          "green=%r" % (code, "GATE GREEN" in text),
          code == M.E_OK and "GATE GREEN" in text
          and "MUTATED" not in text and len(ev_files) == 1)

    check("rc2 ...and the pointer landed on the phase, naming the run just "
          "recorded - the two halves are asserted together because a recorded "
          "run nothing points at and a pointer at no run are both half-done: %r"
          % (shard_after.get("testEvidence"),),
          shard_after.get("testEvidence", {}).get("status") == "passed"
          and shard_after["testEvidence"]["runId"] in text)

    lines = []
    code = M.main([rmpath, "P1", "--project-dir", recroot, "--reconcile"],
                  out=lines.append)
    check("rc3 reconcile over an already-correct plan moves nothing, says so, "
          "and exits 0 - the repair a refused pointer names has to be safe to "
          "run when nothing is wrong, or nobody will run it: %r"
          % ("\n".join(lines)[:90],),
          code == M.E_OK and "already:" in "\n".join(lines)
          and "moved:" not in "\n".join(lines))

    # --- which attempt the run was, end to end -----------------------------
    # THE FIELD HAD NO WRITER. `_evidence_io.row_for` has always copied `attempt`
    # out of the identity and both renderers have always shown it, while the only
    # thing that ever set it was the demo generator - so every row a user could
    # produce left the column blank and the demo advertised a capability the
    # product did not have. These cases are driven through `main` for that reason:
    # what was missing was the WIRING, and a case against the helper alone would
    # have passed on the broken build.
    evdir = os.path.join(recroot, "docs", "audit", "evidence")
    two = []
    code_two = M.main([rmpath, "P1", "--task", "P1.2", "--project-dir", recroot,
                       "--record"], out=two.append)
    row_two = _recorded_rows(evdir)[-1]
    check("at1 a task whose plan RECORDS attempts stamps that number on the row, "
          "beside the `via` no real run could carry it with before: exit=%r %r"
          % (code_two, (row_two.get("taskId"), row_two.get("attempt"),
                        row_two.get("via"))),
          code_two == M.E_OK and row_two.get("taskId") == "P1.2"
          and row_two.get("attempt") == 2 and row_two.get("via") == "cli")

    zero = []
    M.main([rmpath, "P1", "--task", "P1.3", "--project-dir", recroot,
            "--record"], out=zero.append)
    row_zero = _recorded_rows(evdir)[-1]
    check("at2 a RECORDED zero is a value and is written as one - the plan takes "
          "this count back down on a reverted increment and on a reset, so a row "
          "reading it as 'surely at least one' would report an attempt the plan "
          "says never happened: %r"
          % (("attempt" in row_zero, row_zero.get("attempt")),),
          row_zero.get("taskId") == "P1.3" and "attempt" in row_zero
          and row_zero["attempt"] == 0)

    none = []
    M.main([rmpath, "P1", "--task", "P1.1", "--project-dir", recroot,
            "--record"], out=none.append)
    row_none = _recorded_rows(evdir)[-1]
    check("at3 a task whose plan records NO attempts leaves the field off the "
          "row entirely. Absent means 'the plan does not say how many times this "
          "ran', and a 0 or a 1 invented here would be a claim with no basis - "
          "the failure the whole record exists to prevent: %r" % (sorted(row_none),),
          row_none.get("taskId") == "P1.1" and "attempt" not in row_none)

    check("at4 ...and a PHASE-scope run carries no attempt either, which is the "
          "plan being read correctly rather than a gap: `attempts` is a task "
          "field, so a phase has none to report: %r"
          % (sorted(_recorded_rows(evdir)[0]),),
          _recorded_rows(evdir)[0].get("scope") == "phase"
          and "attempt" not in _recorded_rows(evdir)[0])

    check("ms6 ...and the word reaches a row ON DISK, through `main` and the "
          "writer rather than through a helper called by hand. `true` prints no "
          "summary, so the committed row says `not-knowable` beside a null "
          "count - the state a reader must never meet as 'this gate measured "
          "nothing', and the one a case against the helper alone could not "
          "prove had survived the allow-list: %r"
          % (row_none.get("steps"),),
          [(s.get("ran"), s.get("measured")) for s in row_none.get("steps")]
          == [(None, M.MEASURED_UNKNOWN)])

    # --- which gate ran, end to end -----------------------------------------
    # DRIVEN THROUGH `main` FOR `attempt`'s REASON. `gateSource` is set on the
    # result by `main` and read by `_evidence_io.row_for`, so a case against
    # either half alone passes on a build where the two are not wired together -
    # which is exactly the state `attempt` shipped in for as long as it did.
    #
    # AND THE PAIR IS WHAT MAKES IT A MEASUREMENT. P1.4 declares `gate: ["ok"]`
    # and P1.2 declares nothing, so both runs execute the same entry and record
    # the same `steps`; the rows differ in this field and in nothing else a
    # reader could use. A row that answered "task" for both, or "phase" for
    # both, passes half of this and fails the other.
    own = []
    code_own = M.main([rmpath, "P1", "--task", "P1.4", "--project-dir", recroot,
                       "--record"], out=own.append)
    row_own = _recorded_rows(evdir)[-1]
    row_fell_back = [r for r in _recorded_rows(evdir)
                     if r.get("taskId") == "P1.2"][-1]
    check("gp1 a task measured by its OWN `tests.gate` records that, and a task "
          "measured by the PHASE's records that instead - two rows whose `steps` "
          "are byte-identical, told apart by the one field that says where the "
          "list came from: exit=%r %r"
          % (code_own, ((row_own.get("taskId"), row_own.get("gateSource")),
                        (row_fell_back.get("taskId"),
                         row_fell_back.get("gateSource")))),
          code_own == M.E_OK
          and row_own.get("gateSource") == "task"
          and row_fell_back.get("gateSource") == "phase"
          and ([s.get("name") for s in row_own.get("steps") or []]
               == [s.get("name") for s in row_fell_back.get("steps") or []]))

    check("gp2 ...and `scope` is NOT that answer, which is why the field exists: "
          "the fallback row says `phase` for the pointer subject while carrying "
          "`taskId`, and the task row says `task` - so one field is answering "
          "two questions and a reader taking it for provenance is reading a "
          "contract about where the POINTER went: %r"
          % ((row_fell_back.get("scope"), row_fell_back.get("taskId")),),
          row_fell_back.get("scope") == "phase"
          and row_fell_back.get("taskId") == "P1.2"
          and row_own.get("scope") == "task")

    check("gp3 THE OTHER DIRECTION, and it is the one that looks vacuous: a "
          "PHASE-scope run with no --task at all still records `phase` rather "
          "than leaving the field off. A writer that only stamped the fallback "
          "would pass gp1 and leave every sign-off run with no provenance at "
          "all: %r" % (_recorded_rows(evdir)[0].get("gateSource"),),
          _recorded_rows(evdir)[0].get("gateSource") == "phase"
          and "taskId" not in _recorded_rows(evdir)[0])

    check("gp4 the SUBJECT is not recorded beside it, because the row can be "
          "read for it: it is the `taskId` when the gate was the task's and the "
          "`phaseId` otherwise. A second field carrying that would be a cached "
          "claim of the kind this ledger refuses everywhere else: %r"
          % (sorted(k for k in row_own if k.startswith(("gate", "subj"))),),
          "subject" not in row_own and "subject" not in row_fell_back)

    # --- the evidence boundary, end to end ---------------------------------
    # THE MID-FLIGHT ADOPTER'S SHAPE, built rather than described: a plan with no
    # `meta.evidenceSince` and an empty ledger, which is every repository the day
    # it upgrades. A FRESH fixture, never `recroot`: that one has recorded runs
    # by now, so a boundary case against it would be reading somebody else's
    # first run as its own.
    bdroot = _harness.fixture_root("run-test-gate-boundary-")
    os.makedirs(os.path.join(bdroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(bdroot, ".claude"))
    with open(os.path.join(bdroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    bdpath = os.path.join(bdroot, "docs", "audit", "audit-plan.json")
    with open(bdpath, "w") as fh:
        json.dump({"meta": {"version": 3, "buildCommands": {"ok": "true"}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    with open(os.path.join(bdroot, "docs", "audit", "phases", "P1.json"), "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["ok"], "tasks": [
                       {"id": "P1.1", "title": "t", "status": "in_progress",
                        "files": []}]}, fh)
    subprocess.run(["git", "init", "-q", bdroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # AND THE FIXTURE IS COMMITTED, for the reason spelled out at `recroot`'s
    # own commit above: an uncommitted fixture is one `?? docs/` line, so a write
    # inside the measurement window moves no porcelain line and bd2 could never
    # go red.
    for arg in (["add", "-A"],
                ["-c", "user.email=t@example.invalid", "-c", "user.name=t",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", bdroot] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bd_before = json.loads(open(bdpath).read())["meta"]

    bd1_lines = []
    bd1_code = M.main([bdpath, "P1", "--project-dir", bdroot, "--record"],
                      out=bd1_lines.append)
    bd1_text = "\n".join(bd1_lines)
    bd_meta = json.loads(open(bdpath).read())["meta"]
    bd_row = _recorded_rows(os.path.join(bdroot, "docs", "audit", "evidence"))[0]
    check("bd1 a plan with no boundary and no ledger gets one from its FIRST "
          "recorded run: the key names that run, dates it from that run's own "
          "stamp, and carries the sentence that licenses it. Before this, "
          "`no-test-evidence` had no setting for a plan adopted mid-flight - "
          "every task finished before the recorder existed failed a condition "
          "it could not have passed: %r -> %r" % (bd_before, bd_meta.get("evidenceSince")),
          bd1_code == M.E_OK and "evidenceSince" not in bd_before
          and (bd_meta.get("evidenceSince") or {}).get("at") == bd_row["ts"]
          and (bd_meta.get("evidenceSince") or {}).get("runId") == bd_row["runId"]
          and str((bd_meta.get("evidenceSince") or {}).get("basis") or "").strip() != ""
          and "boundary: recording began" in bd1_text)

    check("bd2 ...and the gate STILL reports the tree unchanged, which is the "
          "same boundary rc1 pins one write over: this one touches the INDEX, "
          "the file the run has just described with `git status --porcelain`. "
          "Move it above the post-run snapshot and the runner accuses itself of "
          "the rewrite it exists to catch: green=%r" % ("GATE GREEN" in bd1_text,),
          "GATE GREEN" in bd1_text and "MUTATED" not in bd1_text)

    bd_j = [r for r in _journal_io.read_all(bdroot)
            if r.get("action") == "meta.evidenceSince"]
    check("bd3 the stamp is anchored in the hash chain by a row of its own, "
          "naming both ends. A DETAIL on the row that anchors the RUN would not "
          "do: that row is written before the plan is touched and stays true "
          "whatever happens to it, so hanging a plan-movement claim on it would "
          "put a transition in the chain that had not happened yet: %r"
          % (bd_j[0]["details"] if bd_j else None,),
          len(bd_j) == 1 and bd_j[0]["details"]["field"] == "evidenceSince"
          and bd_j[0]["details"]["from"] is None
          and bd_j[0]["details"]["to"] == (bd_meta.get("evidenceSince") or {}).get("at")
          and bd_j[0]["details"]["runId"] == bd_row["runId"])

    bd2_lines = []
    M.main([bdpath, "P1", "--project-dir", bdroot, "--record"],
           out=bd2_lines.append)
    bd_meta2 = json.loads(open(bdpath).read())["meta"]
    bd_j2 = [r for r in _journal_io.read_all(bdroot)
             if r.get("action") == "meta.evidenceSince"]
    check("bd4 a SECOND recorded run does not move it, says the plan already "
          "states it, and draws no second row. THE ROW COUNT IS THE SEPARATOR "
          "here and the value is not: a writer that re-derived on every run "
          "would compute the same earliest stamp and leave the block looking "
          "untouched, while quietly asserting a transition in the chain each "
          "time (eb19 is where the VALUE tells them apart): %r"
          % (bd_meta2.get("evidenceSince"),),
          bd_meta2.get("evidenceSince") == bd_meta.get("evidenceSince")
          and bd_meta2.get("evidenceSince") is not None and len(bd_j2) == 1
          and "already stated by the plan" in "\n".join(bd2_lines)
          and len(_recorded_rows(os.path.join(bdroot, "docs", "audit",
                                              "evidence"))) == 2)

    # --- a run that was STOPPED, not answered ------------------------------
    # `cancelled` was a `testEvidence.status` member with NO WRITER: it sat in the
    # schema enum, in both renderers and in two documents listing what gets
    # written, while `run_status` could answer only the four words around it. The
    # cost was not cosmetic - the negative-evidence policy's fourth commit point,
    # the sweep at `/audit:resume`, existed to make an interrupted run durable and
    # had nothing to sweep, because the local write it was meant to sweep was
    # never built.
    def _interrupt_second(_project, command, _timeout=None):
        if "first" in command:
            return 0, "all good\n", {}
        raise KeyboardInterrupt("SIGTERM")

    res_i = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                       runner=_interrupt_second)
    check("ic1 a run a stop signal cut short is `cancelled`, and it carries the "
          "steps that FINISHED and no others - the step that was in flight "
          "reported nothing, so a row for it would be an invented entry in the "
          "one record that exists to be true: %r"
          % ((res_i.get("status"), [st["name"] for st in res_i["steps"]],
              res_i.get("cancelledBy")),),
          res_i.get("status") == M.CANCELLED
          and [st["name"] for st in res_i["steps"]] == ["a"]
          and res_i.get("cancelledBy") == "SIGTERM")

    def _fail_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 1, "boom\n", {}
        raise KeyboardInterrupt("SIGINT")

    res_fi = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_fail_then_interrupt)
    check("ic2 THE PRECEDENCE DECISION: a run whose first step FAILED and whose "
          "second was interrupted reads `failed`. A signal does not retract a "
          "measurement that already completed, and spelling a certain red "
          "`cancelled` would downgrade a finding a reader can act on into one "
          "they have to reproduce - the same rule lc4 pins for a timeout. Both "
          "facts survive, one level down: %r"
          % ((res_fi.get("status"), res_fi.get("failed"),
              res_fi.get("cancelledBy")),),
          res_fi.get("status") == "failed" and res_fi.get("failed") == ["a"]
          and res_fi.get("cancelledBy") == "SIGINT")

    def _timeout_then_interrupt(_project, command, timeout=None):
        if "first" in command:
            return -9, "", {"outcome": M.TIMED_OUT, "timeoutSeconds": timeout}
        raise KeyboardInterrupt("SIGINT")

    res_ti = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_timeout_then_interrupt)
    check("ic3 ...and a step that TIMED OUT outranks the interrupt too, one "
          "step weaker and for the same reason: a timeout is a finding with a "
          "repair attached (raise the bound, or fix the hang), and `cancelled` "
          "names none - it is a fact about the operator, not about the work: %r"
          % ((res_ti.get("status"), res_ti.get("cancelledBy")),),
          res_ti.get("status") == M.TIMED_OUT
          and res_ti.get("cancelledBy") == "SIGINT")

    def _cannot_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 127, "could not run: no such file\n", {"outcome": M.CANNOT_RUN}
        raise KeyboardInterrupt("SIGINT")

    res_ci = M.run_gate(tmp, [("a", "first"), ("b", "second")],
                        runner=_cannot_then_interrupt)
    check("ic4 ...and so does a runner that never STARTED, which points at "
          "`meta.buildCommands` and at not burning a retry. Every word that "
          "names a repair sits above the one that names none: %r"
          % ((res_ci.get("status"), res_ci.get("cancelledBy")),),
          res_ci.get("status") == M.CANNOT_RUN
          and res_ci.get("cancelledBy") == "SIGINT")

    def _skipped_then_interrupt(_project, command, _timeout=None):
        if "first" in command:
            return 0, ("check yaml.....................Skipped\n"
                       "black.........................Skipped\n"), {}
        raise KeyboardInterrupt("SIGINT")

    res_zi = M.run_gate(tmp, [("a", "pre-commit run --files first.md"),
                              ("b", "second")], runner=_skipped_then_interrupt)
    check("ic5 THE OTHER END OF THAT PRECEDENCE: a completed step reporting "
          "positively zero checks does NOT make an interrupted run `no-checks`. "
          "A zero taken over a TRUNCATED run is not the 'the gate ran and "
          "skipped everything' claim that word makes, and reading it as one "
          "would sign off a gate that never finished: %r"
          % ((res_zi.get("status"), res_zi.get("ranTotal")),),
          res_zi.get("status") == M.CANCELLED and res_zi["ranTotal"] == 0)

    res_ni = M.run_gate(tmp, [("lint", "true")], runner=_quiet)
    check("ic6 SECOND DIRECTION, and it is the case that looks vacuous: a run "
          "NOTHING stopped reports `cancelledBy` None and a real tree "
          "comparison. It passes on the build that has no interrupt path at "
          "all, and it is the only case that fails when the interrupt arm "
          "becomes unconditional: %r"
          % ((res_ni.get("cancelledBy"), res_ni.get("status"),
              res_ni.get("treeMutated")),),
          res_ni.get("cancelledBy") is None
          and res_ni.get("status") == "passed"
          and res_ni.get("treeMutated") == [])

    check("ic7 ON AN INTERRUPT THE TREE COMPARISON IS NOT MADE EITHER, and the "
          "value is None and not `[]`. `[]` is the one value that means KNOWN "
          "CLEAN, and a killed child may still have been writing - this "
          "repository has conflated null with empty three times and this is the "
          "fourth place it could have: %r"
          % ((res_i.get("treeMutated"), res_i.get("treeBasis")),),
          res_i.get("treeMutated") is None and res_i.get("treeMutated") != []
          and "interrupted" in (res_i.get("treeBasis") or ""))

    def _interrupt_unnamed(_project, _command, _timeout=None):
        raise KeyboardInterrupt()

    res_un = M.run_gate(tmp, [("a", "first")], runner=_interrupt_unnamed)
    check("ic8 an interrupt carrying no name still says so rather than writing "
          "`cancelled` with nothing beside it. `run_gate` is a library function, "
          "so a caller that never armed the handlers meets Python's own bare "
          "KeyboardInterrupt - and a status whose basis is missing must say THAT "
          "is what is missing: %r" % (res_un.get("cancelledBy"),),
          res_un.get("status") == M.CANCELLED
          and res_un.get("cancelledBy") == M.UNNAMED_SIGNAL)

    check("ic9 ...and that run has NO steps at all, which is where the status "
          "has to come from `cancelledBy` rather than from a step's `outcome`: "
          "an interrupt lands on this process, not on one command, so there is "
          "nothing for it to hang off: %r" % (res_un.get("steps"),),
          res_un.get("steps") == [])

    def _explodes(_project, _command, _timeout=None):
        raise MemoryError("not an interrupt")

    _ok_mem, _mem = _harness.attempt(M.run_gate, tmp, [("a", "first")],
                                     runner=_explodes)
    check("ic10 ...and something that is NOT an interrupt still escapes. The "
          "catch is `KeyboardInterrupt` and not `BaseException` on purpose: "
          "`_shell`'s wide arm is doing TEARDOWN, which every escape owes, while "
          "this one assigns a MEANING, and calling a MemoryError `cancelled` "
          "would be the silent mislabel the rest of this file exists to end: %r"
          % (_mem,),
          _ok_mem is False and "MemoryError" in str(_mem))

    rl = []
    code_i = M.render(res_i, out=rl.append)
    rtext = "\n".join(rl)
    check("ic11 render REFUSES a cancelled run, and the refusal is the point: "
          "with no failed step and no mutation this run is exit 0 everywhere "
          "else, so a missing arm here spells a stopped gate GREEN: exit=%r %r"
          % (code_i, rtext[:60]),
          code_i == M.E_FAIL and "GATE CANCELLED" in rtext
          and "GATE GREEN" not in rtext and "SIGTERM" in rtext)

    check("ic12 ...and it says the row is written locally and committed by "
          "nobody. Git belongs to the orchestrator: a commit made while stopping "
          "is a half-made one nobody reviewed, on the one path where nobody is "
          "going to look - so the sentence names the sweep that makes it durable "
          "instead: %r" % (rtext[-90:],),
          "committed by nobody" in rtext and "commit-audit-state.py" in rtext
          and "/audit:resume" in rtext)

    rl2 = []
    M.render(res_fi, out=rl2.append)
    check("ic13 ...and a run that FAILED and was also stopped prints BOTH "
          "sentences, from the fact rather than from the status word. "
          "Precedence gives `failed` the one word; a reader who saw only that "
          "would believe the remaining steps had their say: %r"
          % ("\n".join(rl2)[:70],),
          "GATE RED" in "\n".join(rl2) and "GATE CANCELLED" in "\n".join(rl2))

    # --- the handlers that make a signal reachable at all ------------------
    # `_spawn_kwargs` detaches every step into a session of its own, so a
    # terminal's Ctrl-C arrives HERE and at nothing else - its docstring has named
    # "the handler in `main`" as the other half of that trade since before one
    # existed. SIGTERM had no default that could stand in: with no handler the
    # interpreter dies, the detached group outlives it, and the run leaves neither
    # a record nor a stopped child.
    def _fires(handler, sig):
        """What the installed handler raises, as a word.

        NOT `_harness.attempt`: that catches `Exception`, and the whole point of
        raising a `KeyboardInterrupt` is that it is a `BaseException` and travels
        past every such arm between the handler and `run_gate`. Caught here by the
        name the production code catches it by.
        """
        try:
            handler(sig, None)
        except KeyboardInterrupt as exc:
            return str(exc)
        return "no interrupt raised"

    before_int = signal.getsignal(signal.SIGINT)
    before_term = signal.getsignal(signal.SIGTERM)
    armed = M._arm_interrupt()
    try:
        during_int = signal.getsignal(signal.SIGINT)
        during_term = signal.getsignal(signal.SIGTERM)
        _raised_i = _fires(during_int, signal.SIGINT)
        _raised_t = _fires(during_term, signal.SIGTERM)
    finally:
        M._disarm_interrupt(armed)
    check("ia1 arming installs a handler for each stop signal and disarming puts "
          "back exactly what it displaced - `main` is a function the suites drive "
          "many times in one process, so a handler left behind outlives its run: "
          "%r" % ((during_int is not before_int,
                   signal.getsignal(signal.SIGINT) is before_int),),
          during_int is not before_int and during_term is not before_term
          and signal.getsignal(signal.SIGINT) is before_int
          and signal.getsignal(signal.SIGTERM) is before_term)

    check("ia2 ...and each handler raises an interrupt NAMING its own signal. "
          "Both ends are asserted because a handler stuck on one word is half "
          "right and wholly useless - the name is the whole of a cancelled row's "
          "basis: %r vs %r" % (_raised_i, _raised_t),
          _raised_i == "SIGINT" and _raised_t == "SIGTERM")

    M._disarm_interrupt([(signal.SIGTERM, None)])
    restored = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, before_term)
    check("ia3 a displaced handler of None is restored as the DEFAULT rather "
          "than handed back: None is what `getsignal` answers for a handler that "
          "was not set from Python, and `signal.signal(sig, None)` is a "
          "TypeError - which would take the whole run down inside a `finally`: %r"
          % (restored,),
          restored == signal.SIG_DFL)

    # --- a REAL signal, through a real process tree -------------------------
    # THE MECHANISM, NOT THE PLATFORM'S NAME, IS WHAT DECIDES. These cases put
    # the one question the `runner` seam cannot: whether a signal SENT TO THIS
    # PROGRAM arrives at `run_gate` as an interrupt. Sending it needs `os.kill`
    # to be signal delivery, and where `signal.CTRL_C_EVENT` exists it is not:
    # python documents `os.kill` there as generating a console-control event for
    # that value and CTRL_BREAK_EVENT, and as terminating the target through
    # TerminateProcess for every other value - so `os.kill(child, SIGINT)` would
    # KILL the run rather than interrupt it, and there would be no interrupted
    # run to record. CTRL_BREAK is not the way round it either: it reaches the
    # child as SIGBREAK, which `main` does not arm and cannot, since the row it
    # writes is the row a SIGINT and a SIGTERM produce.
    #
    # So the cases skip, and say so. Weakening them into something that passes
    # on both would mean asserting a `cancelled` row nothing cancelled.
    _harness.stage(check, "ru0 the verdict-reuse block", _reuse_cases)
    _harness.stage(check, "nv0 the no-verdict block", _no_verdict_cases)
    _harness.stage(check, "ce0 the empty-and-retry block",
                   _empty_and_retry_cases)
    _harness.stage(check, "sf0 the suite-files block", _suite_files_cases)
    _harness.stage(check, "mu0 the muted-suite block", _muted_cases)
    _harness.stage(check, "pw0 the playwright-flaky block", _playwright_cases)
    _harness.stage(check, "rv0 the remedy-line block", _remedy_cases)
    _harness.stage(check, "dg0 the record-before-render block", _record_order_cases)
    _harness.stage(check, "xg0 the excluded/no-suite block", _excluded_cases)
    _harness.stage(check, "ow0 the --own block", _own_cases)
    _harness.stage(check, "dgv0 the derived-gate block", _derived_gate_cases)

    if SENDS_REAL_SIGNALS:
        _harness.stage(check, "is0 the real-interrupt block", _interrupt_cases)
    else:
        for _id, _asserts in (
                ("is1", "a real SIGINT mid-step lands a `cancelled` row"),
                ("is2", "the row carries the step that finished"),
                ("is3", "`treeMutated` is null with the race named"),
                ("is4", "the torn-down group takes the grandchild with it"),
                ("is5", "the process exits saying it was cancelled"),
                ("is6", "nothing was committed while stopping"),
                ("is7", "the plan pointer names the cancelled run")):
            _harness.skip(
                check, _id,
                "%s - and no signal can be DELIVERED to a child here: `os.kill` "
                "terminates the target for every value but the two console "
                "events, so there would be no interrupted run to look at"
                % (_asserts,),
                console_events() and signal.SIGINT not in console_events())


def _no_verdict_cases(check):
    """A step that never answered, a jest suite that never ran, and whose gate
    graded the work.

    THE FIXTURES ARE CAPTURED OUTPUT (see the block above `_step`), because the
    readers under test match shapes and a fixture written beside them would
    share their assumption. The second direction is here for every rule: a
    runner that printed its own end-of-run report keeps its red whatever else
    its output says, and a jest run with one real failure beside a killed
    worker stays a verdict.
    """
    def _obs(code, text, command="gate"):
        return M.observed_step("gate", command, code, text, {}, 1)

    # --- a non-zero exit with no report and a could-not-run signature -------
    shells = [(label, _obs(127, text)) for label, text in (
        ("sh", SH_NOT_FOUND), ("dash", DASH_NOT_FOUND), ("zsh", ZSH_NOT_FOUND),
        ("bash", BASH_NOT_FOUND))]
    check("nv1 each shell's own `not found` diagnostic, at exit 127 with no "
          "report after it, is `could-not-run` with a basis naming what was "
          "read - the spelling differs per shell and every one was captured: %r"
          % ([(label, st.get("outcome")) for label, st in shells],),
          all(st.get("outcome") == M.CANNOT_RUN
              and "127" in (st.get("outcomeBasis") or "")
              for _label, st in shells))

    bare = _obs(127, "")
    chose = _obs(127, "custom tool: refusing, exit 127 is my own answer\n")
    other = _obs(1, SH_NOT_FOUND)
    check("nv2 SECOND DIRECTION: 127 with no diagnostic is a code the command "
          "CHOSE, so it keeps its red - reading the category out of the number "
          "would let any child claim it by exiting 127 - and the diagnostic "
          "beside a DIFFERENT code is a script that carried on and answered: %r"
          % ((bare.get("outcome"), chose.get("outcome"), other.get("outcome")),),
          bare.get("outcome") is None and chose.get("outcome") is None
          and other.get("outcome") is None)

    vit = _obs(1, VITEST_NO_FILES, "vitest run src/a.ts")
    check("nv3 vitest's `No test files found` is `could-not-run`: the filter "
          "selected nothing, so no test was asked anything, and a red would "
          "grade the work on a question nobody put: %r"
          % ((vit.get("outcome"), vit.get("outcomeBasis")),),
          vit.get("outcome") == M.CANNOT_RUN
          and "No test files found" in (vit.get("outcomeBasis") or ""))

    counted = _obs(127, MOCHA_MIN + SH_NOT_FOUND, "mocha")
    passing_vitest = _obs(0, VITEST_NO_FILES)
    check("nv4 `reached_a_verdict` STAYS THE GUARD: a runner whose report is "
          "in the output has spoken for its exit code, so a signature printed "
          "beside that report grades nothing - and an exit of 0 is never "
          "reclassified at all: %r"
          % ((counted.get("outcome"), passing_vitest.get("outcome")),),
          counted.get("outcome") is None
          and passing_vitest.get("outcome") is None)

    # --- overlap is asked only of steps that reached a verdict --------------
    def _canned(outputs):
        queue = list(outputs)

        def _runner(_project, _command, _timeout):
            code, text = queue.pop(0)
            return code, text, {}
        return _runner

    root = _harness.fixture_root("run-test-gate-noverdict-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res_sh = M.run_gate(root, [("lint,format,typecheck,test",
                                "lint,format,typecheck,test")],
                        runner=_canned([(127, SH_NOT_FOUND)]),
                        owns=["src/a.ts"])
    sh_lines = []
    M.render(res_sh, out=sh_lines.append)
    sh_text = "\n".join(sh_lines)
    check("nv5 THE FIELD REPORT'S RUN: a comma-joined entry the shell could "
          "not find is GATE COULD NOT RUN, not GATE RED, and `/bin/sh` from "
          "its diagnostic is not read as a path the run printed - so there is "
          "no NO OVERLAP either, only the sentence that no step answered: %r"
          % ((res_sh["status"], res_sh["overlap"], sh_text[-160:]),),
          res_sh["status"] == M.CANNOT_RUN
          and "GATE COULD NOT RUN" in sh_text
          and "GATE RED" not in sh_text
          and "NO OVERLAP" not in sh_text
          and "/bin/sh" not in (res_sh["coverageBasis"] or "")
          and res_sh["overlap"] is None
          and "no step reached a verdict" in (res_sh["coverageBasis"] or ""))

    res_mix = M.run_gate(root, [("broken", "broken"), ("unit", "jest")],
                         runner=_canned([(127, SH_NOT_FOUND),
                                         (0, " PASS  src/a.test.ts\n"
                                             "Tests:       3 passed, 3 total\n")]),
                         owns=["src/a.ts"])
    check("nv6 ALLOW: a step that DID answer beside one that did not still "
          "carries the coverage question, from its own output only: %r"
          % ((res_mix["overlap"], res_mix["coverageBasis"]),),
          res_mix["overlap"] == ["src/a.ts"]
          and "/bin/sh" not in (res_mix["coverageBasis"] or ""))

    # --- jest: a failed-to-run names its suite, its reason, and its signal --
    named_mix, _basis_mix = M.failing_lines(JEST_KILLED_AND_RED,
                                            _ev_io.MAX_FAILING)
    check("jf1 a `Test suite failed to run` is PAIRED with the `FAIL <path>` "
          "above it and its first reason line, so the failure names WHICH "
          "suite and WHY - the bare heading named neither, and an ordinary "
          "assertion bullet beside it is unchanged: %r" % (named_mix,),
          len(named_mix) == 2 and named_mix[0] == "f"
          and named_mix[1].startswith("(signal=SIGSEGV) " + JEST_KILLED_SUITE
                                      + ": Test suite failed to run - A jest "
                                      "worker process"))

    killed = _obs(1, JEST_WORKER_KILLED, "jest")
    check("jf2 EVERY failure a killed worker: `could-not-run`, the signal "
          "named, and the basis says the channel was jest's own report - exit "
          "1 carries no signal at all, so the code could never have said it: %r"
          % ((killed.get("outcome"), killed.get("signal"),
              killed.get("signalBasis")),),
          killed.get("outcome") == M.CANNOT_RUN
          and killed.get("signal") == "SIGSEGV"
          and "jest" in (killed.get("signalBasis") or "")
          and JEST_KILLED_SUITE in (killed.get("signalBasis") or ""))

    mixed = _obs(1, JEST_KILLED_AND_RED, "jest")
    check("jf3 SECOND DIRECTION: one real assertion failure beside the kill "
          "is a VERDICT, so the step stays failed - and its failing list names "
          "both, the assertion and the killed suite with its signal: %r"
          % ((mixed.get("outcome"), mixed.get("failing")),),
          mixed.get("outcome") is None and mixed.get("signal") is None
          and any(JEST_KILLED_SUITE in f and "SIGSEGV" in f
                  for f in (mixed.get("failing") or []))
          and "f" in (mixed.get("failing") or []))

    unparse = _obs(1, JEST_UNPARSEABLE, "jest")
    check("jf4 a suite that failed to run with NO signal is not read as a "
          "kill: it names its path and reason, and carries no `signal`: %r"
          % ((unparse.get("signal"), unparse.get("failing")),),
          unparse.get("signal") is None
          and unparse.get("failing") == [
              "src/features/projects/syntax.test.js: Test suite failed to run"
              " - Jest encountered an unexpected token"])

    colored = JEST_WORKER_KILLED.replace(
        "FAIL src/features/projects/create",
        "\x1b[0m\x1b[7m\x1b[1m\x1b[31m FAIL \x1b[39m\x1b[22m\x1b[27m\x1b[0m "
        "\x1b[2msrc/features/projects/\x1b[22m\x1b[1mcreate")
    colored_named, _cb = M.failing_lines(colored, _ev_io.MAX_FAILING)
    check("jf5 jest's COLOURED header (FORCE_COLOR through a pipe) pairs the "
          "same way - the escapes are jest's chalk calls around ` FAIL ` and "
          "around the dirname, and they are not part of the path: %r"
          % (colored_named,),
          len(colored_named) == 1
          and colored_named[0].startswith("(signal=SIGSEGV) "
                                          + JEST_KILLED_SUITE + ": "))

    res_jest = M.run_gate(root, [("test", "jest")],
                          runner=_canned([(1, JEST_WORKER_KILLED),
                                          (1, JEST_WORKER_KILLED)]),
                          owns=["src/features/projects/list.ts"])
    jrow = _ev_io.row_for(root, res_jest, "task",
                          {"phaseId": "P1", "taskId": "P1.1"},
                          {"runId": "run-jest", "ts": "2026-09-25T00:00:00Z"})
    row_failing = " ".join(f for st in jrow.get("steps") or []
                           for f in (st.get("failing") or []))
    check("jf6 ...and the EVIDENCE ROW carries both: the suite path and the "
          "signal are in the failing record a reader opens a week later, and "
          "the run is `could-not-run` rather than `failed`: %r"
          % ((jrow.get("status"), row_failing[:120]),),
          jrow.get("status") == M.CANNOT_RUN
          and JEST_KILLED_SUITE in row_failing
          and "SIGSEGV" in row_failing)

    # --- the repeat's first line says how to re-measure ---------------------
    rep_lines = []
    M.render_reuse(M.reused_result({"key": "k", "basis": "b"},
                                   {"runId": "r1", "ts": "t", "status": "failed",
                                    "failed": ["test"]}, 0),
                   out=rep_lines.append)
    check("rb1 a repeated verdict's FIRST line carries `--no-reuse`: a reader "
          "who stops at the banner is the one who needs the way back to a "
          "measurement, and the red it repeats is still printed under it: %r"
          % (rep_lines[0][:90],),
          rep_lines[0].startswith("GATE VERDICT REUSED")
          and "--no-reuse" in rep_lines[0]
          and "GATE RED: test" in rep_lines)

    # --- a task gate much wider than the task -------------------------------
    suites = ["src/features/projects/s%02d.test.ts" % i for i in range(12)]
    declared = ["src/features/projects/s00.ts", suites[0]]
    _o, wide = M.coverage(declared, set(suites), task_scope=True)
    check("br1 under --task, a run naming suites the task does not declare "
          "adds ONE breadth clause with both counts - the suites the run "
          "named and the files the task declares - and refuses nothing: %r"
          % (wide[-200:],),
          wide.count("breadth:") == 1
          and "12 suite path(s)" in wide and "2 file(s)" in wide
          and "11 of them" in wide)
    _o, phase_wide = M.coverage(declared, set(suites))
    _o, narrow = M.coverage(declared, set(suites[:1]), task_scope=True)
    check("br2 ALLOW, both ways: at phase scope the question is not asked, and "
          "a task whose run named only its own suite hears nothing about "
          "breadth: %r" % (("breadth:" in phase_wide, "breadth:" in narrow),),
          "breadth:" not in phase_wide and "breadth:" not in narrow)
    _o, subject = M.coverage(["src/features/projects/s03.ts"],
                             set(suites[3:4]), task_scope=True)
    check("br3 ALLOW: a suite NAMED AFTER a declared file is that file's test "
          "and not breadth - `_subject_of` already relates the two: %r"
          % (subject[-80:],),
          "breadth:" not in subject)

    # --- whose gate graded the work, printed where the verdict is read ------
    # Echoed as BYTES, and the file written as UTF-8: the output carries jest's
    # bullet, which a text stream on a legacy code page cannot encode.
    say = os.path.join(root, "say.py")
    with open(say, "w") as fh:
        fh.write("import sys\n"
                 "if len(sys.argv) > 3:\n"
                 "    open(sys.argv[3], 'w').close()\n"
                 "sys.stdout.buffer.write(open(sys.argv[1], 'rb').read())\n"
                 "raise SystemExit(int(sys.argv[2]))\n")
    red_out = os.path.join(root, "red.txt")
    with open(red_out, "w", encoding="utf-8") as fh:
        fh.write(" FAIL  src/sibling.test.ts\n  ● sibling > regressed\n\n"
                 "Tests:       1 failed, 4 passed, 5 total\n")
    ran_marker = os.path.join(root, "phase-gate-ran")
    mp = os.path.join(root, "audit-plan.json")
    with open(mp, "w") as fh:
        json.dump({"meta": {"version": 2, "buildCommands": {
            "suite": _step(sys.executable, say, red_out, "1", ran_marker),
            "own": _step(sys.executable, say, red_out, "1")}},
            "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                        "testGate": ["suite"], "tasks": [
                            {"id": "P1.1", "title": "docs", "status":
                             "in_progress", "files": ["docs/guide.md"],
                             "tests": {"mode": "gate-only", "add": [],
                                       "gate": [], "gateBasis": "cleared"}},
                            {"id": "P1.2", "title": "src", "status":
                             "in_progress", "files": ["src/a.ts"]},
                            {"id": "P1.3", "title": "own", "status":
                             "in_progress", "files": ["src/b.ts"],
                             "tests": {"mode": "gate-only", "add": [],
                                       "gate": ["own"]}}]}]}, fh)

    def _main(*extra):
        lines = []
        code = M.main([mp, "P1", "--project-dir", root, "--no-reuse"]
                      + list(extra), out=lines.append)
        return code, lines

    c_code, c_lines = _main("--task", "P1.1")
    c_text = "\n".join(c_lines)
    check("gb1 a CLEARED task gate is EMPTY at task scope: the phase's suite "
          "does not run, the line names the TASK rather than the phase, and it "
          "says what does still grade it: %r" % (c_text[:160],),
          c_code == M.E_OK and "EMPTY gate" in c_text
          and "P1.1" in c_text and "GATE" not in c_text
          and "command(s)" not in c_text
          and not os.path.exists(ran_marker))

    f_code, f_lines = _main("--task", "P1.2")
    pre = [ln for ln in f_lines if ln.startswith("[run-test-gate]")]
    banner = [i for i, ln in enumerate(f_lines) if ln.startswith("GATE RED:")]
    check("gb2 a task borrowing the PHASE'S gate says so twice: the preamble "
          "names the task and the phase, and a `graded by:` line sits directly "
          "under the banner - which is left exactly `GATE RED: suite`, the "
          "literal the orchestrator keys on: %r"
          % ((pre, [f_lines[i:i + 2] for i in banner]),),
          f_code == M.E_FAIL and len(pre) == 1
          and "P1.2" in pre[0] and "P1" in pre[0].replace("P1.2", "")
          and len(banner) == 1 and f_lines[banner[0]] == "GATE RED: suite"
          and f_lines[banner[0] + 1].strip().startswith("graded by:")
          and "phase P1" in f_lines[banner[0] + 1])

    o_code, o_lines = _main("--task", "P1.3")
    o_banner = [i for i, ln in enumerate(o_lines) if ln.startswith("GATE RED:")]
    check("gb3 ...and a task graded by its OWN gate says that instead, so the "
          "line is never read as a fallback it was not: %r"
          % ([o_lines[i:i + 2] for i in o_banner],),
          o_code == M.E_FAIL and len(o_banner) == 1
          and o_lines[o_banner[0]] == "GATE RED: own"
          and "P1.3's own" in o_lines[o_banner[0] + 1]
          and "phase" not in o_lines[o_banner[0] + 1])

    p_code, p_lines = _main()
    check("gb4 ALLOW: a phase-scope run has no task to contrast, so it prints "
          "no `graded by:` line - the preamble already names the phase: %r"
          % ([ln for ln in p_lines if "graded by" in ln],),
          p_code == M.E_FAIL
          and not any("graded by" in ln for ln in p_lines))

    e_code, e_lines = _on_legacy_codec(lambda: _main("--task", "P1.2"))
    e_text = "\n".join(e_lines)
    check("gb6 on a child stream that cannot spell jest's bullet, the gate still "
          "reads the runner's own output - the bullet's title reaches the "
          "report and no encode traceback stands in for it: %r"
          % ([ln for ln in e_lines if "regressed" in ln or "Error" in ln],),
          e_code == M.E_FAIL and "sibling > regressed" in e_text
          and "UnicodeEncodeError" not in e_text)

    # --- the breadth clause, end to end ---------------------------------------
    # `coverage()` is pinned directly by br1-br3; these pin that `main` hands it
    # `task_scope` at all, which is a keyword a merge can drop without any of
    # those going red.
    wide_suites = ["src/features/projects/s%02d.test.ts" % i for i in range(12)]
    wide_out = os.path.join(root, "wide.txt")
    with open(wide_out, "w") as fh:
        fh.write("".join(" PASS  %s\n" % s for s in wide_suites)
                 + "Tests:       12 passed, 12 total\n")
    wide_mp = os.path.join(root, "wide-plan.json")
    with open(wide_mp, "w") as fh:
        json.dump({"meta": {"version": 2, "buildCommands": {
            "wide": _step(sys.executable, say, wide_out, "0")}},
            "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                        "testGate": ["wide"], "tasks": [
                            {"id": "P1.1", "title": "one suite's worth",
                             "status": "in_progress",
                             "files": ["src/features/projects/s00.ts",
                                       wide_suites[0]]}]}]}, fh)

    def _wide(*extra):
        lines = []
        M.main([wide_mp, "P1", "--project-dir", root, "--no-reuse"]
               + list(extra), out=lines.append)
        return "\n".join(lines)
    at_task = _wide("--task", "P1.1")
    at_phase = _wide()
    check("br4 `main` under --task asks the breadth question: a run naming "
          "suites the task neither declares nor is named after prints exactly "
          "ONE `breadth:` clause: %r" % (at_task.count("breadth:"),),
          at_task.count("breadth:") == 1)
    check("br5 ...and the same run at phase scope prints none, so the clause is "
          "the task scope's and not the run's: %r"
          % (at_phase.count("breadth:"),),
          at_phase.count("breadth:") == 0 and "wide" in at_phase)


def _empty_and_retry_cases(check):
    """An EMPTY answer is a recorded one, a jest kill is retried on the terms
    the retry was built for, and the signal survives the row's cut.

    A FUNCTION SO THE BLOCK CAN BE NAMED: the fixture is a real repository with
    a real manifest and a real `audit-status` read of it.
    """
    def _obs(code, text, command="gate"):
        return M.observed_step("gate", command, code, text, {}, 1)

    cmd = _obs(9009, CMD_NOT_RECOGNIZED)
    cmd1 = _obs(1, CMD_NOT_RECOGNIZED)
    check("nv7 cmd.exe's wording is NOT read, at either exit code: nothing here "
          "captured it, and an unanchored phrase at exit 1 would excuse a real "
          "windows failure as infrastructure: %r"
          % ((cmd.get("outcome"), cmd1.get("outcome")),),
          cmd.get("outcome") is None and cmd1.get("outcome") is None)

    # --- the signal is the FIRST thing in the entry -------------------------
    long_suite = ("packages/storefront-admin/src/features/projects/"
                  "duplicate-detection/__tests__/"
                  "create-project-duplicate-title.e2e.test.tsx")
    long_text = JEST_WORKER_KILLED.replace(JEST_KILLED_SUITE, long_suite)

    def _canned(outputs, seen=None):
        queue = list(outputs)

        def _runner(_project, command, _timeout):
            if seen is not None:
                seen.append(command)
            code, text = queue.pop(0)
            return code, text, {}
        return _runner

    root = _harness.fixture_root("run-test-gate-empty-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res_long = M.run_gate(root, [("test", "jest")],
                          runner=_canned([(1, long_text), (1, long_text)]),
                          owns=["src/a.ts"])
    lrow = _ev_io.row_for(root, res_long, "task",
                          {"phaseId": "P1", "taskId": "P1.1"},
                          {"runId": "run-long", "ts": "2026-09-25T00:00:00Z"})
    lfail = [f for st in lrow.get("steps") or [] for f in st.get("failing") or []]
    check("jf7 a suite path past a hundred characters still leaves SIGSEGV in "
          "the committed row: the row keeps each line only up to the journal's "
          "value cap, so the signal is the entry's FIRST word, not its middle: %r"
          % (lfail,),
          len(long_suite) > 100 and len(lfail) == 1
          and lfail[0].startswith("(signal=SIGSEGV) ")
          and "SIGSEGV" in lfail[0])

    # --- a jest-reported kill is retried at a lowered bound -----------------
    seen = []
    res_retry = M.run_gate(root, [("test", "jest --maxWorkers=4")],
                           runner=_canned([(1, JEST_WORKER_KILLED),
                                           (0, " PASS  src/a.test.ts\n"
                                               "Tests:       3 passed, 3 total\n")],
                                          seen),
                           owns=["src/a.ts"])
    rstep = res_retry["steps"][0]
    check("jr1 A WORKER jest reports killed is the case the retry was built for "
          "- a parallel suite bounded by memory per worker - so the step is run "
          "once more at half the declared bound, and the row says so: %r"
          % ((seen, rstep.get("retriedAfterSignal"), rstep.get("retryBasis")),),
          seen == ["jest --maxWorkers=4", "jest --maxWorkers=2"]
          and rstep.get("retriedAfterSignal") == "SIGSEGV"
          and "from 4 to 2" in (rstep.get("retryBasis") or "")
          and res_retry["status"] == "passed")

    # --- the EMPTY answer, recorded and read back ----------------------------
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    say = os.path.join(root, "say.py")
    with open(say, "w") as fh:
        fh.write("import sys\nsys.stdout.write(sys.argv[1])\n"
                 "raise SystemExit(int(sys.argv[2]))\n")
    mp = os.path.join(root, "docs", "audit", "audit-plan.json")

    def _plan(phase_gate):
        cleared = {"mode": "gate-only", "add": [], "gate": [],
                   "gateBasis": "cleared"}
        plan = {"meta": {"version": 2, "evidenceSince": {"at": "2026-01-01T00:00:00Z"},
                         "buildCommands": {
                             "suite": _step(sys.executable, say, "ok", "0"),
                             "zero": _step(sys.executable, say,
                                           "Tests:       0 total", "0")}},
                "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                            "desiredOutcome": "p", "testGate": phase_gate,
                            "tasks": [
                                {"id": "P1.1", "title": "docs",
                                 "status": "in_progress", "files": ["d.md"],
                                 "tests": cleared},
                                {"id": "P1.4", "title": "zero",
                                 "status": "in_progress", "files": ["z.py"],
                                 "tests": {"mode": "gate-only", "add": [],
                                           "gate": ["zero"]}}]}],
                "fileIndex": {"d.md": ["P1.1"], "z.py": ["P1.4"]}, "bugs": []}
        with open(mp, "w") as fh:
            json.dump(plan, fh, indent=2)

    def _main(*extra):
        lines = []
        code = M.main([mp, "P1", "--project-dir", root, "--no-reuse"]
                      + list(extra), out=lines.append)
        return code, lines

    _plan(["suite"])
    e_code, e_lines = _main("--task", "P1.1", "--record")
    with open(mp) as fh:
        plan = json.load(fh)
    t11 = plan["phases"][0]["tasks"][0]
    evdir = os.path.join(root, "docs", "audit", "evidence")
    rows = _recorded_rows(evdir) if os.path.isdir(evdir) else []
    check("ce1 a cleared task's EMPTY answer under --record is RECORDED: an "
          "`empty-gate` row and a pointer the plan carries, the one word the "
          "enum has for 'no gate was configured' - so a reader never has to "
          "read a missing answer as missing evidence: %r"
          % ((e_code, [r.get("status") for r in rows],
              (t11.get("testEvidence") or {}).get("status")),),
          e_code == M.E_OK and len(rows) == 1
          and rows[0].get("status") == "empty-gate"
          and rows[0].get("taskId") == "P1.1" and rows[0].get("steps") == []
          and (t11.get("testEvidence") or {}).get("status") == "empty-gate")

    t11["status"] = "done"
    t11["completedAt"] = "2026-09-25T12:00:00Z"
    t11["commit"] = "0" * 40
    with open(mp, "w") as fh:
        json.dump(plan, fh, indent=2)
    status_mod = _loader.load_script("audit-status.py", "ast_ce")
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        s_code = status_mod.main([mp, "--gate", "--fail-on",
                                  "no-test-evidence"])
    check("ce2 THE REPRO: a done task whose gate was cleared no longer fails "
          "`audit-status --gate --fail-on no-test-evidence` - its pointer is "
          "the recorded EMPTY answer, not an absence the repair text could "
          "never fix: exit=%r %r" % (s_code, buf.getvalue()[-160:]),
          s_code == 0 and "GATE PASSED: no-test-evidence" in buf.getvalue()
          and "GATE FAILED" not in buf.getvalue())

    j_code, j_lines = _main("--task", "P1.1", "--json")
    try:
        j_obj = json.loads("\n".join(j_lines))
    except ValueError:
        j_obj = None
    check("ce3 ...and under --json the EMPTY answer is a JSON object, never a "
          "prose line a machine reader cannot parse: %r" % (j_lines[:1],),
          j_code == M.E_OK and isinstance(j_obj, dict)
          and j_obj.get("status") == "empty-gate")

    _plan([])
    n_code, n_lines = _main("--task", "P1.1")
    n_text = "\n".join(n_lines)
    check("ce4 a cleared task in a phase whose gate is EMPTY too is graded by "
          "NOTHING, and the line says review alone rather than pointing at a "
          "phase gate that does not exist: %r" % (n_text[:200],),
          n_code == M.E_OK and "review alone" in n_text
          and "testGate at sign-off is what still does" not in n_text)

    _plan(["suite"])
    z_code, z_lines = _main("--task", "P1.4")
    z_at = [i for i, ln in enumerate(z_lines) if ln.startswith("NO CHECK RAN:")]
    check("gb5 `NO CHECK RAN` is a verdict banner too, so the `graded by:` line "
          "sits directly under it: %r" % ([z_lines[i:i + 2] for i in z_at],),
          z_code == M.E_FAIL and len(z_at) == 1
          and z_lines[z_at[0] + 1].strip().startswith("graded by:"))


def _suite_files_cases(check):
    """`failing_suites` names the FILE a failing check lives in, which `failing`
    (the check's own name) cannot - and `suiteReader` records, on every step,
    whether this gate could even tell a test suite from a hook list.
    """
    def _obs(code, text, command="gate"):
        return M.observed_step("gate", command, code, text, {}, 1)

    named, basis = M.failing_lines(JEST_CART_FAIL, _ev_io.MAX_FAILING)
    suites, s_basis = M.failing_suites(JEST_CART_FAIL)
    check("sf1 THE FAULT, READ DIRECTLY: an ordinary jest assertion failure "
          "records the bullet TITLE in `failing` and the suite it lives in "
          "NOWHERE - `failing_suites` is the reader that answers the second "
          "question: %r" % ((named, suites, s_basis),),
          named == ["cart > rejects a negative quantity"]
          and "cart > rejects a negative quantity" not in " ".join(
              suites or [])
          and suites == ["src/cart.test.ts"]
          and "jest" in s_basis and "named as failing" in s_basis)

    v_suites, v_basis = M.failing_suites(VITEST_CART_FAIL)
    check("sf2 vitest: the FILE PART of `FAIL <file> > <suite> > <name>`, "
          "never the cross line beside it in the file tree (it carries no "
          "`FAIL` word at all): %r" % ((v_suites, v_basis),),
          v_suites == ["src/cart.test.ts"] and "vitest" in v_basis)

    p_suites, p_basis = M.failing_suites(PYTEST_CART_FAIL)
    check("sf3 pytest: the path BEFORE `::` on its FAILED/ERROR line(s): %r"
          % ((p_suites, p_basis),),
          p_suites == ["tests/test_cart.py"] and "pytest" in p_basis)

    m_suites, m_basis = M.failing_suites(MOCHA_CART_FAIL)
    check("sf4 mocha is a RECOGNISED runner whose failure lines name only the "
          "check, never a file - so this is `(None, <a basis saying so>)`, "
          "never an empty list that would read as nothing failed: %r"
          % ((m_suites, m_basis),),
          m_suites is None and "mocha" in m_basis)

    u_suites, u_basis = M.failing_suites(
        "building object files\nmake: *** [build/parse.o] Error 1\n")
    check("sf5 a runner NONE of the readers recognises answers `(None, ...)` "
          "too, and the basis says so rather than naming a runner: %r"
          % ((u_suites, u_basis),),
          u_suites is None and "no runner" in u_basis)

    vend_suites, vend_basis = M.failing_suites(JEST_VENDOR_ONLY_FAIL)
    check("sf6 a `FAIL` header naming ONLY a vendored path is not a suite this "
          "work owns - `_VENDOR_DIRS` filters it out, and the empty result "
          "reads as `(None, ...)` and never as an empty list: %r"
          % ((vend_suites, vend_basis),),
          vend_suites is None and "node_modules" not in (vend_basis or ""))

    mixed = _obs(1, JEST_KILLED_AND_RED, "jest")
    check("sf7 a real assertion failure beside a killed worker is a VERDICT, "
          "so the step's `failingSuites` names BOTH suites - the broken one "
          "and the one jest reports as killed: %r" % (mixed.get("failingSuites"),),
          mixed.get("outcome") is None
          and set(mixed.get("failingSuites") or [])
          == {"src/features/projects/broken.test.js", JEST_KILLED_SUITE})

    killed = _obs(1, JEST_WORKER_KILLED, "jest")
    check("sf8 THE OUTCOME GUARD: a jest run whose ONLY failures are workers "
          "the OS killed is `could-not-run`, and a killed worker's `FAIL` "
          "header is not a failing TEST - so the step carries NEITHER "
          "`failingSuites` nor `failingSuitesBasis` at all: %r"
          % (sorted(k for k in killed if k.startswith("failingSuite")),),
          killed.get("outcome") == M.CANNOT_RUN
          and "failingSuites" not in killed
          and "failingSuitesBasis" not in killed)

    passing = _obs(0, "Tests:       4 passed, 4 total\n", "jest")
    check("sf9 ALLOW: a step that simply passed carries neither key either - "
          "the guard above is `exit != 0`, not `outcome is None`, so a green "
          "step never gains a `failingSuites` of its own: %r"
          % (sorted(k for k in passing if k.startswith("failingSuite")),),
          "failingSuites" not in passing and "failingSuitesBasis" not in passing)

    jest_step = _obs(1, JEST_CART_FAIL, "jest")
    vitest_step = _obs(1, VITEST_CART_FAIL, "vitest run src/cart.test.ts")
    precommit_step = _obs(
        0, "check yaml................................................"
           ".............Passed\n", "pre-commit run --all-files")
    unknown_step = _obs(1, "building object files\nError 1\n", "make check")
    check("sf10 EVERY STEP RECORDS `suiteReader`, passing ones included - the "
          "name the counts reader gave its output, or `none` when it "
          "recognised no test runner's summary at all: %r"
          % ((jest_step.get("suiteReader"), vitest_step.get("suiteReader"),
              precommit_step.get("suiteReader"),
              unknown_step.get("suiteReader")),),
          jest_step.get("suiteReader") == "jest"
          and vitest_step.get("suiteReader") == "vitest"
          and precommit_step.get("suiteReader") == "none"
          and unknown_step.get("suiteReader") == "none")

    check("sf11 A `pre-commit` WRAPPER'S OWN LINE TALLY IS NOT A SUITE: "
          "`suiteReader` is read off `summary_reader`, never off `measured` "
          "or `ran` - a hook list that `_STEP_WORDS` counts perfectly well is "
          "still `none` here: %r" % (precommit_step.get("measured"),),
          precommit_step.get("measured") is not None
          and precommit_step.get("suiteReader") == "none")


def _mini_repo(prefix):
    """A real, empty git repository: `run_gate` asks git for the tree bracket."""
    root = _harness.fixture_root(prefix)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return root


def _scripted(outputs, calls=None):
    """A runner answering each command from `outputs[command]`, counting calls."""
    def run(_project, command, _timeout=None):
        if calls is not None:
            calls.append(command)
        code, text = outputs[command]
        return code, text, {}
    return run


# Two suites fail in ONE jest step, and a mute names only the first of them.
JEST_TWO_SUITES_FAIL = """\
FAIL src/cart.test.ts
  ● cart > rejects a negative quantity
FAIL src/pay.test.ts
  ● pay > declines an expired card

Tests:       2 failed, 3 passed, 5 total
"""


def _mute_plan(mute, fix_status="in_progress", gate_command=None):
    """A plan whose bug B1 is fixed by task P1.2 and muted by `mute`; P1.3 is
    another task of the same phase. `gate_command`, when given, is the one
    `test` build command both tasks' gates run."""
    tasks = [{"id": "P1.2", "title": "fix the cart", "status": fix_status,
              "bugId": "B1", "files": ["src/cart.js"]},
             {"id": "P1.3", "title": "other work", "status": "in_progress",
              "files": ["src/pay.js"]}]
    meta = {"version": 3, "muted": [mute]}
    if gate_command is not None:
        meta["buildCommands"] = {"test": gate_command}
        for task in tasks:
            task["tests"] = {"mode": "gate-only", "add": [], "gate": ["test"]}
    return {"meta": meta,
            "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                        "testGate": ["test"], "tasks": tasks}],
            "bugs": [{"id": "B1", "title": "cart rejects a quantity",
                      "status": "open", "severity": "med", "taskId": "P1.2"}]}


def _withheld_mute_cases(check, repo, mute, today, outputs, commands):
    """A mute never holds inside the gate of its own bug's fix task, nor once
    its bug is closed; every other mute holds exactly as before."""
    plan = _mute_plan(mute)
    own = M.run_gate(repo, commands, runner=_scripted(outputs), muted=[mute],
                     today=today, withheld=M.withheld_mutes(plan, "P1.2"))
    shown = []
    own_code = M.render(own, out=shown.append)
    own_step = [st for st in own["steps"] if st["name"] == "test"][0]
    check("mw1 RED-FIRST: the gate of bug B1's own fix task (P1.2) does NOT "
          "honour B1's mute - the run fails, the step keeps no `muted`, and "
          "the line says why the mute did not hold: %r"
          % ((own["status"], own_code,
              [ln for ln in shown if "muted" in ln]),),
          own["status"] == "failed" and own_code != M.E_OK
          and not own_step.get("muted")
          and "bug B1 is the one task P1.2 fixes" in "\n".join(shown)
          and "so this failure blocks" in "\n".join(shown))
    other = M.run_gate(repo, commands, runner=_scripted(outputs),
                       muted=[mute], today=today,
                       withheld=M.withheld_mutes(plan, "P1.3"))
    check("mw2 ALLOW: another task's gate (P1.3) still honours the mute on "
          "an open bug, and a phase or full run (no task) does too: %r"
          % ((other["status"], M.withheld_mutes(plan, "P1.3"),
              M.withheld_mutes(plan, None)),),
          other["status"] == "passed" and other.get("muted")
          and M.withheld_mutes(plan, "P1.3") == {}
          and M.withheld_mutes(plan, None) == {})
    closed_plan = _mute_plan(mute, fix_status="done")
    closed = M.run_gate(repo, commands, runner=_scripted(outputs),
                        muted=[mute], today=today,
                        withheld=M.withheld_mutes(closed_plan, None))
    closed_step = [st for st in closed["steps"] if st["name"] == "test"][0]
    check("mw3 RED-FIRST: a mute whose bug is effectively closed (its fix "
          "task is done) blocks for every run, naming the effective status: "
          "%r" % ((closed["status"], closed_step.get("muteRefused")),),
          closed["status"] == "failed" and not closed_step.get("muted")
          and any("bug B1 is closed (fixed)" in (r.get("why") or "")
                  for r in closed_step.get("muteRefused") or []))

    # THE WIRING: `main --task P1.2` hands the runner the task under test.
    # The shell is replaced so the gate's one step prints a real jest capture
    # whose only failure is the muted suite.
    command = "npx jest src/cart.test.js"
    task_mute = dict(mute, test="src/cart.test.js", until="9999-12-31")
    mp = os.path.join(repo, "mute-plan.json")
    with open(mp, "w") as fh:
        json.dump(_mute_plan(task_mute, gate_command=command), fh)
    real_shell = M._shell
    M._shell = lambda _project, _command, _timeout=None: (
        1, JEST_REAL_FAIL, {})
    try:
        runs = {}
        for task in ("P1.2", "P1.3"):
            said = []
            runs[task] = (M.main([mp, "P1", "--task", task, "--project-dir",
                                  repo, "--no-reuse"], out=said.append),
                          "\n".join(said))
    finally:
        M._shell = real_shell
    check("mw4 RED-FIRST: `run-test-gate.py <plan> P1 --task P1.2` over a run "
          "whose only failure is B1's muted suite exits red and says the "
          "mute did not hold; the same run for P1.3 is green: %r"
          % ((runs["P1.2"][0], runs["P1.3"][0],
              [ln for ln in runs["P1.2"][1].splitlines() if "muted" in ln]),),
          runs["P1.2"][0] != M.E_OK
          and "bug B1 is the one task P1.2 fixes" in runs["P1.2"][1]
          and runs["P1.3"][0] == M.E_OK)


def _muted_cases(check):
    """A muted suite's failure is recorded and does not fail the run - only
    when every suite the runner NAMED as failing is muted by an entry that
    still holds. Everything else blocks exactly as it did before a mute
    existed: an expired entry, a second failing suite nobody muted, and a
    failure whose names could not be read at all.
    """
    repo = _mini_repo("run-test-gate-muted-")
    today = datetime.date(2026, 9, 27)
    mute = {"test": "src/cart.test.ts", "bugId": "B1", "until": "2026-10-01",
            "reason": "flaky on the shared runner", "owner": "shop team"}
    outputs = {"ruff check .": (0, "All checks passed!\n"),
               "npx jest": (1, JEST_CART_FAIL)}
    commands = [("lint", "ruff check ."), ("test", "npx jest")]

    calls = []
    res = M.run_gate(repo, commands, runner=_scripted(outputs, calls),
                     muted=[mute], today=today)
    test_step = [st for st in res["steps"] if st["name"] == "test"][0]
    check("mu1 THE FAULT: a run whose ONLY failing suite is muted by an "
          "unexpired entry comes back `passed`, and the failing step keeps its "
          "exit, its failing names and its failing suites: %r"
          % ((res["status"], res["failed"], test_step.get("exit"),
              test_step.get("failingSuites")),),
          res["status"] == "passed" and res["failed"] == []
          and test_step["exit"] == 1
          and test_step.get("failing") == ["cart > rejects a negative quantity"]
          and test_step.get("failingSuites") == ["src/cart.test.ts"])
    check("mu2 ...and the run carries the mute it honoured as "
          "`{test, bugId, until}`: %r" % (res.get("muted"),),
          res.get("muted") == [{"test": "src/cart.test.ts", "bugId": "B1",
                                "until": "2026-10-01"}])
    lines = []
    code = M.render(res, out=lines.append)
    text = "\n".join(lines)
    check("mu3 ...the terminal says so in its own line, and the exit code is "
          "the green one: %r" % ((code, [ln for ln in lines if "muted" in ln]),),
          code == M.E_OK
          and "muted: src/cart.test.ts failed (bug B1, until 2026-10-01)"
          in text)
    check("mu4 THE RUNNER NEVER RETRIES A FAILURE, muted or not - a retry "
          "stays reserved for a signal death: %r" % (calls,),
          calls == ["ruff check .", "npx jest"])

    same_day = M.run_gate(repo, commands, runner=_scripted(outputs),
                          muted=[dict(mute, until="2026-09-27")], today=today)
    check("mu5 `until` IS INCLUSIVE: a mute until today still holds today: %r"
          % ((same_day["status"], same_day.get("muted")),),
          same_day["status"] == "passed" and same_day["failed"] == [])

    expired = M.run_gate(repo, commands, runner=_scripted(outputs),
                         muted=[dict(mute, until="2026-09-26")], today=today)
    exp_lines = []
    exp_code = M.render(expired, out=exp_lines.append)
    check("mu6 ALLOW: an EXPIRED entry is not honoured - the failure blocks "
          "and the line says why: %r"
          % ((expired["status"], expired["failed"],
              [ln for ln in exp_lines if "muted" in ln]),),
          expired["status"] == "failed" and expired["failed"] == ["test"]
          and not expired.get("muted") and exp_code != M.E_OK
          and "muted until 2026-09-26 - expired, so this failure blocks"
          in "\n".join(exp_lines))

    two = M.run_gate(repo, [("test", "npx jest")],
                     runner=_scripted({"npx jest": (1, JEST_TWO_SUITES_FAIL)}),
                     muted=[mute], today=today)
    check("mu7 ALLOW: a muted suite BESIDE an unmuted failing suite in the "
          "same step fails as it always did - a mute covers what it names "
          "and nothing next to it: %r" % ((two["status"], two["failed"]),),
          two["status"] == "failed" and two["failed"] == ["test"]
          and not two.get("muted"))

    tail = M.run_gate(repo, [("test", "make check")],
                      runner=_scripted({"make check": (
                          1, "src/cart.test.ts\nmake: *** [check] Error 1\n")}),
                      muted=[mute], today=today)
    check("mu8 ALLOW: a failure whose names could not be READ (a tail, not "
          "a runner's failure lines) fails as today - a mute is never "
          "assumed, even when the muted path appears in the output: %r"
          % ((tail["status"], tail["failed"],
              tail["steps"][0].get("failingBasis")),),
          tail["status"] == "failed" and tail["failed"] == ["test"]
          and not tail.get("muted"))

    unmuted = M.run_gate(repo, commands, runner=_scripted(outputs),
                         muted=[], today=today)
    check("mu9 ALLOW: with no mute at all the same output is `failed`, which "
          "is what makes `mu1` a statement about the mute: %r"
          % ((unmuted["status"], unmuted["failed"]),),
          unmuted["status"] == "failed" and unmuted["failed"] == ["test"]
          and not unmuted.get("muted"))

    old = M.run_gate(repo, commands, runner=_scripted(outputs),
                     muted=[dict(mute, until="2000-01-01")])
    far = M.run_gate(repo, commands, runner=_scripted(outputs),
                     muted=[dict(mute, until="9999-12-31")])
    check("mu10 WITH NO `today` THE RUNNER ASKS THE ONE CLOCK the validator "
          "asks (`_manifest_vocab.mute_today`), never none at all: a mute "
          "long past blocks, one far ahead holds: %r"
          % ((old["status"], far["status"]),),
          old["status"] == "failed" and far["status"] == "passed")

    bad = M.run_gate(repo, commands, runner=_scripted(outputs),
                     muted=[dict(mute, until="soon")], today=today)
    check("mu11 ALLOW: an `until` that is not a day is not honoured - an "
          "unreadable expiry is not read as a live one: %r"
          % ((bad["status"],),),
          bad["status"] == "failed" and not bad.get("muted"))

    _row = _ev_io.row_for(repo, res, "task", {"taskId": "P1.2"},
                          {"runId": "R-mute"}, published=["npx jest"])
    check("mu12 THE COMMITTED ROW carries the mute beside the failing step "
          "it excused: %r" % ((_row.get("status"), _row.get("muted")),),
          _row.get("status") == "passed"
          and _row.get("muted") == res.get("muted")
          and [s["exit"] for s in _row["steps"]] == [0, 1])

    _withheld_mute_cases(check, repo, mute, today, outputs, commands)

    # --- a mute applies only when the NAMED failures are the whole failure ---
    def _one(label, command, code, text, test):
        """One step, one mute naming `test`: `(result, step, rendered)`."""
        got = M.run_gate(repo, [("e2e", command)],
                         runner=_scripted({command: (code, text)}),
                         muted=[dict(mute, test=test)], today=today)
        shown = []
        M.render(got, out=shown.append)
        return got, got["steps"][0], "\n".join(shown)

    pw_red, pw_red_step, _t = _one("pw", "npx playwright test", 1,
                                   PW_LIST_RED, "tests/hard.spec.js")
    check("mu13 A FLAKY TEST BESIDE A MUTED FAILURE REFUSES THE MUTE: "
          "playwright fails a run on flaky tests when `failOnFlakyTests` is "
          "set, and the config form of that is invisible from the command - "
          "so a non-zero flaky count is a failure this cannot rule out: %r"
          % ((pw_red["status"], [r.get("why") for r in
                                  pw_red_step.get("muteRefused") or []]),),
          pw_red["status"] == "failed" and not pw_red_step.get("muted")
          and any("flaky" in (r.get("why") or "")
                  for r in pw_red_step.get("muteRefused") or []))
    for case, command, code, text, test, word in (
            ("mu14 playwright `did not run`", "npx playwright test", 1,
             PW_LIST_DID_NOT_RUN, "tests/serial.spec.js", "did not run"),
            ("mu15 playwright `error was not a part of any test`",
             "npx playwright test", 1, PW_LIST_STRAY_ERROR,
             "tests/hard.spec.js", "not a part of any test"),
            ("mu16 vitest's `Errors` summary", "npx vitest run", 1,
             VITEST_STRAY_ERROR, "src/cart.test.js", "error"),
            ("mu17 jest's failed coverage threshold", "npx jest", 1,
             JEST_THRESHOLD_FAIL, "src/cart.test.js", "threshold"),
            ("mu18 a summary counting more failures than were named",
             "pytest -q", 1, PYTEST_COUNTS_MORE_THAN_NAMED,
             "tests/test_cart.py", "named")):
        got, step, shown = _one(case, command, code, text, test)
        refused = step.get("muteRefused") or []
        check("%s: ALLOW - the named failure is muted and the runner reported "
              "a failure beyond it, so the mute is REFUSED with its own `why` "
              "and the failure blocks: %r"
              % (case, (got["status"], got["failed"],
                        [r.get("why") for r in refused]),),
              got["status"] == "failed" and got["failed"] == ["e2e"]
              and not got.get("muted") and not step.get("muted")
              and any(word in (r.get("why") or "") for r in refused)
              and "so this failure blocks" in shown)

    # The interrupted capture exited 130, the code a shell gives a SIGINT, so
    # the whole run is judged before any mute is asked; the refusal itself is
    # read off the same bytes with the exit a `--max-failures` stop gives.
    intr, intr_step, _t = _one("intr", "npx playwright test", 130,
                               PW_LIST_INTERRUPTED, "tests/hard.spec.js")
    _h, _r, _u = M.mute_decision(
        {"exit": 1, "command": "npx playwright test"}, PW_LIST_INTERRUPTED,
        [dict(mute, test="tests/hard.spec.js")], today)
    check("mu19 playwright `interrupted`: the captured run is not green, and "
          "a muted failure beside an interrupted test is REFUSED: %r"
          % ((intr["status"], _h, [r.get("why") for r in _r]),),
          intr["status"] != "passed" and not intr.get("muted")
          and _h == [] and any("interrupted" in (r.get("why") or "")
                               for r in _r))

    rel, rel_step, rel_text = _one(
        "rel", "npx jest", 1, JEST_CART_FAIL.replace("src/cart", "cart"),
        "src/cart.test.ts")
    check("mu20 A MUTE THAT MATCHES NO PATH THE RUNNER NAMED says so - the "
          "runner printed paths relative to its own directory and the mute "
          "spells them from the repository root: %r"
          % ([ln for ln in rel_text.splitlines() if "mute" in ln],),
          rel["status"] == "failed"
          and "the mute on src/cart.test.ts (bug B1) matches no path the "
          "runner named" in rel_text
          and "cart.test.ts" in rel_text)
    check("mu21 ALLOW: a mute that DID match is never reported as matching "
          "nothing: %r" % ([ln for ln in lines if "mute" in ln],),
          "matches no path" not in text)

    # --- FAIL CLOSED: a mute is honoured only when the step is ONE listed
    # runner, exiting with its failed-tests code, whose named failures are its
    # whole tally, with no early stop and no coverage threshold. Every shape
    # below breaks exactly one of those, and each is a real capture.
    for case, command, code, text, test, word in (
            ("mu22 a pre-commit WRAPPER step", "pre-commit run --all-files", 1,
             PRECOMMIT_PYTEST_AND_RUFF, "tests/test_cart.py", "wraps"),
            ("mu23 a COMPOUND command", "pytest -q; ruff check .", 1,
             PYTEST_THEN_RUFF, "tests/test_cart.py", "shell clause"),
            ("mu24 TWO runners' summaries in one step", "npx jest", 1,
             MOCHA_THEN_JEST, "src/cart.test.js", "more than one runner"),
            ("mu25 a pytest-cov threshold", "pytest -q --cov=shop "
             "--cov-fail-under=100", 1, PYTEST_COV_THRESHOLD,
             "tests/test_cart.py", "coverage threshold"),
            ("mu26 a vitest coverage threshold", "npx vitest run "
             "src/cart.test.js --coverage.enabled", 1, VITEST_COV_THRESHOLD,
             "src/cart.test.js", "coverage threshold"),
            ("mu27 pytest -x", "pytest -q -x", 1, PYTEST_STOPPED_EARLY,
             "tests/test_cart.py", "stopped early"),
            ("mu28 jest --bail", "npx jest --bail -i", 1, JEST_BAIL,
             "src/cart.test.js", "stopped early"),
            ("mu29 vitest --bail", "npx vitest run --bail=1", 1, VITEST_BAIL,
             "src/cart.test.js", "stopped early"),
            ("mu30 pytest -rf with an error the short summary leaves out",
             "pytest -q -rf", 1, PYTEST_RF_WITH_ERROR, "tests/test_cart.py",
             "named"),
            ("mu31 an exit code that is not the runner's failed-tests code",
             "npx jest src/cart.test.js", 3, JEST_REAL_FAIL,
             "src/cart.test.js", "failed-tests code")):
        got, step, shown = _one(case, command, code, text, test)
        refused = step.get("muteRefused") or []
        check("%s: ALLOW - the named failure is muted and the mute is REFUSED "
              "with its own `why`, so the failure blocks: %r"
              % (case, (got["status"], got["failed"],
                        [r.get("why") for r in refused]),),
              got["status"] == "failed" and got["failed"] == ["e2e"]
              and not got.get("muted") and not step.get("muted")
              and any(word in (r.get("why") or "") for r in refused)
              and "so this failure blocks" in shown)

    _hc, _rc, _uc = M.mute_decision(
        {"exit": 1, "command": "npx jest src/cart.test.js"}, JEST_REAL_FAIL,
        [dict(mute, test="src/cart.test.js")], today, runners={})
    check("mu32 ALLOW: a runner NOT on the allow-list never mutes, however "
          "clean its output: %r" % ([r.get("why") for r in _rc],),
          _hc == [] and any("allow-list" in (r.get("why") or "") for r in _rc))
    check("mu33 THE ALLOW-LIST says which runners' failed-tests exit was read "
          "off a real run, and what that code is: %r" % (M.MUTE_RUNNERS,),
          M.MUTE_RUNNERS == {"pytest": 1, "jest": 1, "vitest": 1,
                             "playwright": 1})

    for case, command, text, test in (
            ("mu34 pytest", "pytest -q", PYTEST_REAL_FAIL,
             "tests/test_cart.py"),
            ("mu35 jest", "npx jest src/cart.test.js", JEST_REAL_FAIL,
             "src/cart.test.js"),
            ("mu36 vitest", "npx vitest run src/cart.test.js",
             VITEST_REAL_FAIL, "src/cart.test.js"),
            ("mu37 playwright", "npx playwright test", PW_LIST_RED_NO_FLAKY,
             "tests/hard.spec.js")):
        got, step, _shown = _one(case, command, 1, text, test)
        check("%s: a bare, muted-only failure from an allow-listed runner "
              "STAYS passed - the refusals above are about what surrounds "
              "the failure, never the failure itself: %r"
              % (case, (got["status"], step.get("muteRefused"))),
              got["status"] == "passed" and step.get("muted")
              and not step.get("muteRefused"))

    # --- FAIL CLOSED ON THE COMMAND: only a DIRECT runner call mutes -------
    for case, command, text, test, word in (
            ("mu40 npm test", "npm test", JEST_REAL_FAIL,
             "src/cart.test.js", "package script"),
            ("mu41 npm run", "npm run test:unit", JEST_REAL_FAIL,
             "src/cart.test.js", "package script"),
            ("mu42 yarn test", "yarn test", JEST_REAL_FAIL,
             "src/cart.test.js", "package script"),
            ("mu43 yarn jest (a same-named script runs first)", "yarn jest",
             JEST_REAL_FAIL, "src/cart.test.js", "package script"),
            ("mu44 pnpm test", "pnpm test", JEST_REAL_FAIL,
             "src/cart.test.js", "package script"),
            ("mu45 a script file", "./scripts/test.sh", PYTEST_REAL_FAIL,
             "tests/test_cart.py", "script file"),
            ("mu46 make", "make test", PYTEST_REAL_FAIL, "tests/test_cart.py",
             "task runner"),
            ("mu47 tox", "tox -e py", PYTEST_REAL_FAIL, "tests/test_cart.py",
             "task runner"),
            ("mu48 nox", "nox -s tests", PYTEST_REAL_FAIL,
             "tests/test_cart.py", "task runner"),
            ("mu49 run-s behind npx", "npx run-s -c lint test:unit",
             JEST_REAL_FAIL, "src/cart.test.js", "task runner"),
            ("mu50 npm-run-all", "npx npm-run-all test", JEST_REAL_FAIL,
             "src/cart.test.js", "task runner"),
            ("mu51 turbo", "npx turbo run test", JEST_REAL_FAIL,
             "src/cart.test.js", "task runner"),
            ("mu52 nx", "npx nx test shop", JEST_REAL_FAIL,
             "src/cart.test.js", "task runner"),
            ("mu53 a DIFFERENT runner than the output names",
             "npx vitest run", JEST_REAL_FAIL, "src/cart.test.js",
             "not a direct call of jest"),
            ("mu54 anything unrecognised", "bash run-tests", JEST_REAL_FAIL,
             "src/cart.test.js", "not a direct call of jest")):
        got, step, shown = _one(case, command, 1, text, test)
        refused = step.get("muteRefused") or []
        check("%s: ALLOW - the command is not a direct runner call, so the "
              "mute is REFUSED with its own `why` and the failure blocks: %r"
              % (case, (got["status"], [r.get("why") for r in refused]),),
              got["status"] == "failed" and not step.get("muted")
              and any(word in (r.get("why") or "") for r in refused)
              and "so this failure blocks" in shown)

    for case, command, text, test in (
            ("mu55 a leading VAR=value word", "CI=1 npx jest src/cart.test.js",
             JEST_REAL_FAIL, "src/cart.test.js"),
            ("mu56 python3 -m pytest", "python3 -m pytest -q",
             PYTEST_REAL_FAIL, "tests/test_cart.py"),
            ("mu57 python -m pytest", "python -m pytest -q", PYTEST_REAL_FAIL,
             "tests/test_cart.py"),
            ("mu58 yarn exec", "yarn exec jest src/cart.test.js",
             JEST_REAL_FAIL, "src/cart.test.js"),
            ("mu59 pnpm exec", "pnpm exec vitest run src/cart.test.js",
             VITEST_REAL_FAIL, "src/cart.test.js"),
            ("mu60 a bare runner binary", "jest src/cart.test.js",
             JEST_REAL_FAIL, "src/cart.test.js"),
            ("mu61 jest past its summary threshold", "npx jest",
             JEST_OVER_SUMMARY_THRESHOLD, "src/cart.test.js")):
        got, step, _shown = _one(case, command, 1, text, test)
        check("%s: a DIRECT call of the runner the output names mutes: %r"
              % (case, (got["status"], [r.get("why") for r in
                                        step.get("muteRefused") or []])),
              got["status"] == "passed" and step.get("muted")
              and not step.get("muteRefused"))

    for case, command, text, test, word in (
            ("mu62 playwright --fail-on-flaky-tests",
             "npx playwright test --fail-on-flaky-tests",
             PW_LIST_FAIL_ON_FLAKY, "tests/hard.spec.js", "flaky"),
            ("mu63 an obsolete jest snapshot", "npx jest",
             JEST_OBSOLETE_SNAPSHOT, "src/cart.test.js", "snapshot")):
        got, step, shown = _one(case, command, 1, text, test)
        refused = step.get("muteRefused") or []
        check("%s: ALLOW - the runner fails the run for something its test "
              "tally does not count, so the mute is REFUSED: %r"
              % (case, (got["status"], [r.get("why") for r in refused]),),
              got["status"] == "failed" and not step.get("muted")
              and any(word in (r.get("why") or "") for r in refused))

    pre = "source ~/.nvm/nvm.sh && nvm use"
    with_pre = M.run_gate(
        repo, [("unit", "%s && npx jest src/cart.test.js" % (pre,))],
        runner=_scripted({"%s && npx jest src/cart.test.js" % (pre,):
                          (1, JEST_REAL_FAIL)}),
        muted=[dict(mute, test="src/cart.test.js")], today=today, preamble=pre)
    no_pre = M.run_gate(
        repo, [("unit", "%s && npx jest src/cart.test.js" % (pre,))],
        runner=_scripted({"%s && npx jest src/cart.test.js" % (pre,):
                          (1, JEST_REAL_FAIL)}),
        muted=[dict(mute, test="src/cart.test.js")], today=today)
    check("mu38 `meta.nodePreamble` IS NOT A SECOND CLAUSE: the exact "
          "preamble the manifest prefixes is read off before the one-runner "
          "rule, and the same command with it undeclared is refused: %r"
          % ((with_pre["status"], no_pre["status"]),),
          with_pre["status"] == "passed" and no_pre["status"] == "failed")

    _shadow_man = {"meta": {"phaseGate": {"mode": "shadow"}},
                   "phases": [{"id": "P1", "testGateBasis": "declared",
                               "testGateDerived": {"tests": ["tests/a.py"]}}]}
    _muted_only = [{"name": "unit", "exit": 1,
                    "failingSuites": ["src/cart.test.js"],
                    "failingSuitesBasis": "named as failing",
                    "muted": [{"test": "src/cart.test.js", "bugId": "B1",
                               "until": "2026-10-01"}]}]
    _unmuted = [dict(_muted_only[0], muted=None)]
    check("mu39 A SHADOW RUN WHOSE ONLY FAILURE IS MUTED has nothing the "
          "derived gate 'would have missed' - a quarantined failure is not a "
          "catch: %r" % (M.shadow_gate_claim(_shadow_man, "P1", _muted_only),),
          M.shadow_gate_claim(_shadow_man, "P1", _muted_only) is None
          and M.shadow_gate_claim(_shadow_man, "P1", _unmuted) is not None)


def _playwright_cases(check):
    """Playwright Test is a runner this gate can count, and a test it reports
    as FLAKY - failed, then passed on retry - is named on the step as an
    observation: the step exited 0 and the run passed, with a named doubt.
    Every fixture is a captured run (see the fixture block's header).
    """
    def _obs(code, text):
        return M.observed_step("e2e", "npx playwright test", code, text, {}, 1)

    flaky_name = "tests/flaky.spec.js:2:1 › settles on retry"
    green = _obs(0, PW_LIST_FLAKY)
    check("pw1 THE FAULT: Playwright's list output reporting one flaky test "
          "records a step that NAMES it, on a step that exited 0: %r"
          % ((green.get("flaky"), green.get("flakyBasis")),),
          green.get("flaky") == [flaky_name]
          and "playwright" in (green.get("flakyBasis") or ""))
    check("pw2 ...and FLAKY IS NOT AN OUTCOME: no `outcome`, no `failing`, "
          "and the count reads the summary - the flaky test and the passing "
          "one both ran: %r"
          % ((green.get("outcome"), green.get("failing"), green.get("ran"),
              green.get("suiteReader")),),
          green.get("outcome") is None and green.get("failing") is None
          and green.get("ran") == 2 and green.get("suiteReader") == "playwright")
    line = _obs(0, PW_LINE_FLAKY)
    check("pw3 ...the LINE reporter, cursor escapes and all, answers the same: "
          "%r" % ((line.get("flaky"), line.get("ran")),),
          line.get("flaky") == [flaky_name] and line.get("ran") == 2)

    repo = _mini_repo("run-test-gate-playwright-")
    res = M.run_gate(repo, [("e2e", "npx playwright test")],
                     runner=_scripted({"npx playwright test":
                                       (0, PW_LIST_FLAKY)}))
    row = _ev_io.row_for(repo, res, "task", {"taskId": "P1.2"},
                         {"runId": "R-pw"}, published=["npx playwright test"])
    check("pw4 THE RUN PASSES, and the committed row keeps the flaky name "
          "while every tally still counts the step as a pass - "
          "`gate_tally` reads any `outcome` as not-passed: %r"
          % ((res["status"], row["steps"][0].get("flaky"),
              _ev_io.gate_tally([row], "e2e")),),
          res["status"] == "passed" and res["failed"] == []
          and row["steps"][0].get("flaky") == [flaky_name]
          and _ev_io.gate_tally([row], "e2e") == (1, 0))
    lines = []
    M.render(res, out=lines.append)
    check("pw5 ...and the terminal names the flaky test under its step: %r"
          % ([ln for ln in lines if "flaky" in ln],),
          any(flaky_name in ln for ln in lines))

    for label, text in (("pw6 list", PW_LIST_RED), ("pw7 line", PW_LINE_RED)):
        red = _obs(1, text)
        check("%s reporter, a HARD failure beside a flaky one: the failing "
              "check and its suite are named off the `N failed` block, the "
              "flaky one off the `N flaky` block, and the count reads all "
              "three tests: %r"
              % (label, (red.get("failing"), red.get("failingSuites"),
                         red.get("flaky"), red.get("ran"))),
              red.get("failing") == ["tests/hard.spec.js:2:1 › always fails"]
              and red.get("failingSuites") == ["tests/hard.spec.js"]
              and red.get("flaky") == [flaky_name]
              and red.get("ran") == 3 and red.get("outcome") is None
              and "playwright" in (red.get("failingBasis") or ""))

    proj = _obs(1, PW_LIST_PROJECT_RED)
    check("pw8 a PROJECT-prefixed name keeps its project, and the suite is "
          "still the file: %r"
          % ((proj.get("failing"), proj.get("failingSuites")),),
          proj.get("failing")
          == ["[alpha] › tests/hard.spec.js:2:1 › always fails"]
          and proj.get("failingSuites") == ["tests/hard.spec.js"]
          and proj.get("flaky")
          == ["[alpha] › tests/flaky.spec.js:2:1 › settles on retry"])

    plain = _obs(0, "  3 passed (1.2s)\n")
    check("pw9 ALLOW: a run with nothing flaky carries NO `flaky` key - an "
          "empty list would read as a claim somebody measured: %r"
          % (sorted(k for k in plain if k.startswith("flaky")),),
          "flaky" not in plain and "flakyBasis" not in plain
          and plain.get("ran") == 3)
    jest_green = _obs(0, "Tests:       4 passed, 4 total\n")
    check("pw10 ALLOW: another runner's summary is still read as that runner "
          "and grows no `flaky` key: %r" % (jest_green.get("suiteReader"),),
          jest_green.get("suiteReader") == "jest" and "flaky" not in jest_green)


def _remedy_cases(check):
    """The remedy line under `SAME SUITE COUNTED ONCE`, phase-scope only.

    THE REPRO: a phase gate `[test, coverage]` whose two steps print the same
    suite and the same count prints the duplication with no runnable way out
    of it - `main` has `res['subject']` (the phase id) and the manifest PATH
    in hand, and printed nothing that used either.
    """
    root = _harness.fixture_root("run-test-gate-remedy-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say = os.path.join(root, "say.py")
    with open(say, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write(open(sys.argv[1]).read())\n"
                 "raise SystemExit(int(sys.argv[2]))\n")
    dup_out = os.path.join(root, "dup.txt")
    with open(dup_out, "w") as fh:
        fh.write(" PASS  src/cart.test.js\nTests  5 passed (5)\n")

    def _plan(gate, at=None):
        mp = os.path.join(at or root, "audit-plan.json")
        with open(mp, "w") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "test": _step(sys.executable, say, dup_out, "0"),
                "coverage": _step(sys.executable, say, dup_out, "0")}},
                "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                            "testGate": gate, "tasks": [
                                {"id": "P1.1", "title": "t", "status":
                                 "in_progress", "files": ["src/a.ts"]}]}]},
                      fh)
        return mp

    mp = _plan(["test", "coverage"])
    lines = []
    code = M.main([mp, "P1", "--project-dir", root, "--no-reuse"],
                  out=lines.append)
    text = "\n".join(lines)
    remedy = [ln.strip() for ln in lines if ln.strip().startswith("remedy:")]
    check("rv1 THE REPRO: a phase gate whose two steps report the SAME suite "
          "and the SAME count prints the duplication with a runnable way out "
          "of it - a `retarget --gate-drop` line naming the SECOND entry, "
          "`coverage`, and the manifest path `main` already holds: %r"
          % (remedy,),
          code == M.E_OK and "SAME SUITE COUNTED ONCE" in text
          and len(remedy) == 1 and "retarget P1 --gate-drop coverage" in remedy[0]
          and mp in remedy[0] and "CLAUDE_PLUGIN_ROOT" in remedy[0]
          and "audit-task.py" in remedy[0])

    def _run_printed(line, project):
        """The printed remedy, run the way the plan's own commands run - under
        the POSIX shell `_proc_group` resolves, never `shell=True`, which is
        `cmd.exe` on Windows and would leave `${CLAUDE_PLUGIN_ROOT}` unexpanded.
        Nothing is added but the project directory a real terminal would
        already be standing in, itself quoted."""
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = _output.PLUGIN_ROOT
        argv, env, why = _pg.shell_invocation(
            line[len("remedy:"):].strip()
            + " --project-dir " + shlex.quote(project), env)
        if argv is None:
            return None, why
        proc = subprocess.run(argv, cwd=project, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)
        return proc.returncode, proc.stdout.decode("utf-8", "replace")[-400:]

    rv2_code, rv2_text = _run_printed(remedy[0], root)
    with open(mp, encoding="utf-8") as fh:
        after = json.load(fh)
    check("rv2 RUNNING THE PRINTED COMMAND, argv split and nothing added but "
          "the project directory a real terminal would already be standing "
          "in, drops `coverage` from the phase's own testGate: %r"
          % ((rv2_code, rv2_text, after["phases"][0].get("testGate")),),
          rv2_code == 0 and after["phases"][0]["testGate"] == ["test"])

    # A MANIFEST WHOSE PATH HAS A SPACE IN IT: the remedy printed it unquoted,
    # so the shell split it into two words and the command named a plan that
    # does not exist - on every platform, not only on Windows.
    spaced = os.path.join(root, "with space")
    os.mkdir(spaced)
    subprocess.run(["git", "init", "-q", spaced], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Written fresh and not copied from `mp`: rv2's command saved `mp` through
    # the plan writer, which spells every path inside ITS checkout
    # repo-relative, and a step reading `say.py` from `root` runs nothing from
    # this one.
    sp_mp = _plan(["test", "coverage"], at=spaced)
    sp_lines = []
    M.main([sp_mp, "P1", "--project-dir", spaced, "--no-reuse"],
           out=sp_lines.append)
    sp_remedy = [ln.strip() for ln in sp_lines
                 if ln.strip().startswith("remedy:")]
    sp_code, sp_text = (_run_printed(sp_remedy[0], spaced) if sp_remedy
                        else (None, "no remedy printed"))
    with open(sp_mp, encoding="utf-8") as fh:
        sp_after = json.load(fh)
    check("rv5 RED-FIRST: from a manifest path WITH A SPACE the remedy carries "
          "the path as ONE quoted word, and runs as printed to drop `coverage` "
          "(mutation: print the path unquoted -> the command names a plan that "
          "does not exist -> red): %r"
          % ((sp_remedy, sp_code, sp_text,
              sp_after["phases"][0].get("testGate")),),
          len(sp_remedy) == 1 and shlex.quote(sp_mp) in sp_remedy[0]
          and shlex.split(sp_remedy[0])[-1] == sp_mp
          and sp_code == 0 and sp_after["phases"][0]["testGate"] == ["test"])

    task_lines = []
    M.main([mp, "P1", "--project-dir", root, "--no-reuse", "--task", "P1.1"],
          out=task_lines.append)
    _plan(["test", "coverage"])
    task_lines = []
    M.main([mp, "P1", "--project-dir", root, "--no-reuse", "--task", "P1.1"],
          out=task_lines.append)
    task_text = "\n".join(task_lines)
    check("rv3 ALLOW: a TASK-scope run of the same duplicated gate prints the "
          "duplication line and NO remedy - a phase retarget there would drop "
          "the wrong declaration, since the narrowing rules a task's own "
          "gate is corrected by are `_invariants`'s and not "
          "`meta.phaseGate`'s: %r"
          % ([ln for ln in task_lines if "remedy:" in ln],),
          "SAME SUITE COUNTED ONCE" in task_text
          and not any("remedy:" in ln for ln in task_lines))

    def _vitest_other(_project, command, _timeout=None):
        return 0, (" PASS  src/user.test.js\nTests  5 passed (5)\n"
                   if "user" in command else
                   " PASS  src/cart.test.js\nTests  5 passed (5)\n"), {}

    res_diff = M.run_gate(root, [("cart", "npx vitest run src/cart.test.js"),
                                 ("user", "npx vitest run src/user.test.js")],
                          runner=_vitest_other)
    res_diff["manifestPath"] = mp
    res_diff["subject"] = "P1"
    diff_lines = []
    M.render(res_diff, out=diff_lines.append)
    check("rv4 ALLOW: two steps of equal count over DIFFERENT suites print "
          "neither the duplication line nor a remedy (`sc5` stays green) - "
          "even with `manifestPath` present, there is no `SAME SUITE` group "
          "to hang a remedy off of: %r"
          % ([ln for ln in diff_lines if "remedy:" in ln],),
          not any("SAME SUITE" in ln for ln in diff_lines)
          and not any("remedy:" in ln for ln in diff_lines))


def _record_order_cases(check):
    """A PIN, NO BEHAVIOUR CHANGE: the ledger row is written before the first
    verdict banner, so a run cut off mid-render still leaves its row.
    """
    root = _harness.fixture_root("run-test-gate-order-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say = os.path.join(root, "say.py")
    with open(say, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('Tests: 1 failed, 0 passed, 1 total\\n')\n"
                 "raise SystemExit(1)\n")
    mp = os.path.join(root, "audit-plan.json")
    with open(mp, "w") as fh:
        json.dump({"meta": {"version": 2, "buildCommands": {
            "test": _step(sys.executable, say)}},
            "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                        "testGate": ["test"], "tasks": []}]}, fh)

    class _CutOff(Exception):
        pass

    seen = []

    def _raising_out(line):
        seen.append(line)
        if str(line).startswith(M._VERDICT_BANNERS):
            raise _CutOff("cut off at the first verdict banner")

    try:
        M.main([mp, "P1", "--project-dir", root, "--no-reuse", "--record"],
              out=_raising_out)
        raised = False
    except _CutOff:
        raised = True
    recorded_line = [ln for ln in seen if ln.startswith("  evidence: recorded")]
    rows = _ev_io.read_rows(root)["rows"]
    check("dg22 THE ROW IS WRITTEN BEFORE THE BANNER: `_record_run` already "
          "runs before `render`, so a run cut off AT the first verdict "
          "banner still leaves `evidence: recorded <runId>` printed and the "
          "row sitting in the ledger - never a run that answered and left "
          "no trace of it: %r"
          % ((raised, len(recorded_line), len(rows)),),
          raised and len(recorded_line) == 1 and len(rows) == 1)


def _excluded_cases(check):
    """The declared narrowing, printed rather than silently applied - and the
    statement that nothing here could tell a suite from a hook list.
    """
    root = _harness.fixture_root("run-test-gate-excluded-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lint_out = os.path.join(root, "lint.txt")
    with open(lint_out, "w") as fh:
        fh.write("check yaml.................................."
                 "............................Passed\n")
    # NAMED FOR THE WRAPPER IT STANDS IN FOR, not "say.py" - `wrapper_words`
    # (and so `ran_count`/`measured_state`) matches on the COMMAND STRING, and
    # this is the one case here that needs the lint step to measure real HOOK
    # checks (`MEASURED_CHECKS`) rather than an unknowable count, so the
    # `suiteReader`-vs-`measured` mutation has something to disagree about.
    say = os.path.join(root, "pre-commit-lint.py")
    with open(say, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write(open(sys.argv[1]).read())\n"
                 "raise SystemExit(0)\n")

    def _plan(exclude):
        mp = os.path.join(root, "audit-plan.json")
        meta = {"version": 2, "buildCommands": {
            "lint": _step(sys.executable, say, lint_out),
            "test": _step(sys.executable, say, lint_out)}}
        if exclude:
            meta["phaseGate"] = {"exclude": exclude}
        with open(mp, "w") as fh:
            json.dump({"meta": meta,
                       "phases": [{"id": "P1", "title": "p", "status":
                                   "in_progress", "testGate": ["lint"],
                                   "tasks": []}]}, fh)
        return mp

    mp = _plan(["test"])
    lines = []
    M.main([mp, "P1", "--project-dir", root, "--no-reuse"], out=lines.append)
    check("xg1 RED-FIRST: a phase gate excluding `test` prints, under its "
          "header, which buildCommands key `meta.phaseGate.exclude` "
          "declares out of this gate - naming it rather than leaving a "
          "reader to diff `meta.buildCommands` against `testGate` by hand: %r"
          % ([ln for ln in lines if "excluded:" in ln],),
          any("excluded:" in ln and "test" in ln for ln in lines))
    check("xg2 RED-FIRST: a lint-only gate under that exclude - a "
          "`pre-commit`-shaped step that MEASURED real checks and recognised "
          "no test runner's summary - prints `PHASE GATE RAN NO SUITE` "
          "above the verdict: %r"
          % ([ln for ln in lines if "PHASE GATE RAN NO SUITE" in ln],),
          any(ln.startswith("PHASE GATE RAN NO SUITE") for ln in lines)
          and "test" in [ln for ln in lines
                        if ln.startswith("PHASE GATE RAN NO SUITE")][0])

    mp_none = _plan(None)
    lines_none = []
    M.main([mp_none, "P1", "--project-dir", root, "--no-reuse"],
          out=lines_none.append)
    check("xg3 ALLOW: a plan with no `meta.phaseGate.exclude` at all prints "
          "NEITHER line - there is nothing declared out of this gate to "
          "name, and nothing here refuses a green verdict either way: %r"
          % ([ln for ln in lines_none
              if "excluded:" in ln or "PHASE GATE RAN NO SUITE" in ln],),
          not any("excluded:" in ln or "PHASE GATE RAN NO SUITE" in ln
                 for ln in lines_none))

    # --- xg4: RED-FIRST - `meta.phaseGate.exclude` edited AFTER `testGate` -
    # `phase_gate_default` alone answers "what would a gate built TODAY drop",
    # which is a DIFFERENT claim from "was not run here": a phase's own
    # `testGate` can still carry a key `exclude` now lists, and that key RUNS.
    # The fixture is built so the two readings disagree - `test` is excluded
    # AND still in `testGate` (stale), `coverage` is excluded and genuinely
    # absent from `testGate` (true) - so a version reading `exclude` alone
    # cannot tell them apart and this case can.
    stale_mp = os.path.join(root, "audit-plan-stale.json")
    with open(stale_mp, "w") as fh:
        json.dump({"meta": {"version": 2, "buildCommands": {
            "lint": _step(sys.executable, say, lint_out),
            "test": _step(sys.executable, say, lint_out),
            "coverage": _step(sys.executable, say, lint_out)},
            "phaseGate": {"exclude": ["test", "coverage"]}},
            "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                        "testGate": ["lint", "test"], "tasks": []}]}, fh)
    stale_lines = []
    M.main([stale_mp, "P1", "--project-dir", root, "--no-reuse"],
          out=stale_lines.append)
    excluded_line = [ln for ln in stale_lines if "excluded:" in ln]
    check("xg4 RED-FIRST: `test` is STILL in this phase's `testGate` - it "
          "RAN, whatever `meta.phaseGate.exclude` now says - so the line "
          "must not name it; `coverage` truly is not in `testGate`, so the "
          "line must name that one instead: %r" % (excluded_line,),
          len(excluded_line) == 1
          and excluded_line[0]
          == "  excluded: coverage - meta.phaseGate.exclude declares them "
             "out of this phase's gate; they were not run here")


def _derived_gate_cases(check):
    """The derived sign-off gate, in shadow first: a phase's `testGateDerived`
    either replaces the phase's gate (`meta.phaseGate.mode == "enforce"`) or
    rides beside it (`"shadow"`), and this run has to grade itself against
    whichever one it actually was measured under.
    """
    def _plan(root, say, phase_extra, meta_extra):
        mp = os.path.join(root, "audit-plan.json")
        meta = {"version": 2,
                "buildCommands": {"pytest": _step(sys.executable, say)}}
        meta.update(meta_extra)
        phase = {"id": "P1", "title": "p", "status": "in_progress",
                 "testGate": ["pytest"], "tasks": []}
        phase.update(phase_extra)
        with open(mp, "w") as fh:
            json.dump({"meta": meta, "phases": [phase]}, fh)
        return mp

    # --- dg3: a derived (enforce) run that skipped a listed suite ----------
    root = _harness.fixture_root("run-test-gate-derived-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say = os.path.join(root, "say.py")
    with open(say, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('tests/test_a.py::"
                 "test_one PASSED\\n')\n"
                 "sys.stdout.write('tests/test_b.py::"
                 "test_two PASSED\\n')\n"
                 "sys.stdout.write('2 passed in 0.01s\\n')\n"
                 "raise SystemExit(0)\n")
    derived = {"entry": "pytest",
               "tests": ["tests/test_a.py",
                        "tests/test_b.py",
                        "tests/test_c.py"],
               "narrowed": True}
    mp = _plan(root, say,
              {"testGateBasis": "derived", "testGateDerived": derived},
              {"phaseGate": {"mode": "enforce"}})
    lines = []
    M.main([mp, "P1", "--project-dir", root, "--no-reuse", "--record"],
          out=lines.append)
    check("dg3 RED-FIRST: a derived gate listing three suites whose run "
          "named only two comes back `GATE COULD NOT RUN`, never `GATE "
          "GREEN` - the step's own exit code answered a narrower question "
          "than the phase recorded, and that is not this run's verdict: %r"
          % ([ln for ln in lines
              if "DERIVED RUN NAMED" in ln or ln.startswith(
                  M._VERDICT_BANNERS)],),
          any(ln.startswith("GATE COULD NOT RUN:") for ln in lines)
          and not any(ln.startswith("GATE GREEN:") for ln in lines)
          and any("DERIVED RUN NAMED 2 OF 3 LISTED SUITES" in ln
                  and "test_c.py" in ln for ln in lines))
    check("dg3n RED-FIRST: `testGateDerived.narrowed` is true, but this run "
          "did not name every listed suite - the derived-step gap already "
          "graded it `could-not-run` - so the sign-off line must not claim "
          "this run MEASURED the derived gate; the two sentences cannot "
          "both be true of one run: %r"
          % ([ln for ln in lines if ln.startswith("NARROWED sign-off:")],),
          not any(ln.startswith("NARROWED sign-off:")
                 and "measured the DERIVED gate" in ln for ln in lines)
          and any(ln.startswith("NARROWED sign-off:")
                 and "did not name every listed suite" in ln
                 and "certifies nothing" in ln for ln in lines))

    # --- dg3g: a derived run that DID name every listed suite -- the allow -
    # narrowed sign-off's measured line still prints exactly as before, which
    # is the direction `dg3n` above must not have broken.
    root1b = _harness.fixture_root("run-test-gate-derived-full-")
    subprocess.run(["git", "init", "-q", root1b], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say1b = os.path.join(root1b, "say.py")
    with open(say1b, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('tests/test_a.py::"
                 "test_one PASSED\\n')\n"
                 "sys.stdout.write('tests/test_b.py::"
                 "test_two PASSED\\n')\n"
                 "sys.stdout.write('2 passed in 0.01s\\n')\n"
                 "raise SystemExit(0)\n")
    derived_full = {"entry": "pytest",
                    "tests": ["tests/test_a.py", "tests/test_b.py"],
                    "narrowed": True}
    mp1b = _plan(root1b, say1b,
                {"testGateBasis": "derived", "testGateDerived": derived_full},
                {"phaseGate": {"mode": "enforce"}})
    lines1b = []
    M.main([mp1b, "P1", "--project-dir", root1b, "--no-reuse", "--record"],
          out=lines1b.append)
    check("dg3g ALLOW: a run that named every listed suite still prints the "
          "measured NARROWED line unchanged - suppressing it is only for a "
          "run the derived-step gap actually graded `could-not-run`: %r"
          % ([ln for ln in lines1b if ln.startswith("NARROWED sign-off:")],),
          any(ln.startswith("NARROWED sign-off:")
              and "measured the DERIVED gate" in ln
              and "2 of 2 listed checks" in ln
              and "before P1 is whole" in ln for ln in lines1b))
    rows_derived = _ev_io.read_rows(root)["rows"]
    check("dg3s ALLOW: an ENFORCE-mode run - `phase.testGateBasis` is "
          "already `derived` - prints no `shadow:` line and records no "
          "`shadow` field: asking whether the derived gate `would have` "
          "caught what it just ran is a question with no content",
          not any(ln.startswith("shadow:") for ln in lines)
          and "shadow" not in (rows_derived[0] if rows_derived else {}))

    root2 = _harness.fixture_root("run-test-gate-derived-narrow-off-")
    subprocess.run(["git", "init", "-q", root2], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say2 = os.path.join(root2, "say.py")
    with open(say2, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('tests/test_a.py::"
                 "test_one PASSED\\n')\n"
                 "sys.stdout.write('1 passed in 0.01s\\n')\n"
                 "raise SystemExit(0)\n")
    derived_off = {"entry": "pytest", "tests": ["tests/test_a.py"],
                  "narrowed": False}
    mp2 = _plan(root2, say2,
               {"testGateBasis": "derived", "testGateDerived": derived_off},
               {"phaseGate": {"mode": "enforce"}})
    lines2 = []
    M.main([mp2, "P1", "--project-dir", root2, "--no-reuse", "--record"],
          out=lines2.append)
    check("dg3-allow NARROWED prints NOTHING when `testGateDerived.narrowed` "
          "is false - a derivation that computed nothing to narrow to earns "
          "no claim that a narrower gate ran",
          not any(ln.startswith("NARROWED sign-off:") for ln in lines2))

    # --- dg19: a wide (shadow) run over two failing suites, one listed -----
    root3 = _harness.fixture_root("run-test-gate-shadow-")
    subprocess.run(["git", "init", "-q", root3], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say3 = os.path.join(root3, "say.py")
    with open(say3, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('FAILED tests/test_a.py::"
                 "test_one - AssertionError\\n')\n"
                 "sys.stdout.write('FAILED tests/"
                 "test_other.py::test_two - AssertionError\\n')\n"
                 "sys.stdout.write('2 failed in 0.02s\\n')\n"
                 "raise SystemExit(1)\n")
    derived_shadow = {"entry": "pytest",
                      "tests": ["tests/test_a.py"],
                      "narrowed": False}
    mp3 = _plan(root3, say3, {"testGateDerived": derived_shadow},
               {"phaseGate": {"mode": "shadow"}})
    lines3 = []
    M.main([mp3, "P1", "--project-dir", root3, "--no-reuse", "--record"],
          out=lines3.append)
    rows3 = _ev_io.read_rows(root3)["rows"]
    check("dg19 RED-FIRST: a WIDE run of a shadow-mode phase with two "
          "failing suites, one of them listed in `testGateDerived.tests`, "
          "records `shadow.missed` of one - the suite the derived gate "
          "would NOT have caught: %r"
          % ([ln for ln in lines3 if ln.startswith("shadow:")],),
          any(ln == "shadow: derived would have listed 1 of 2 failing "
                     "suite(s)" for ln in lines3)
          and len(rows3) == 1
          and rows3[0].get("shadow", {}).get("listed") == 1
          and rows3[0].get("shadow", {}).get("full") == 2
          and rows3[0].get("shadow", {}).get("missed")
          == ["tests/test_other.py"])

    # --- dg19-allow: a plan with no meta.phaseGate.mode records no shadow --
    root4 = _harness.fixture_root("run-test-gate-shadow-off-")
    subprocess.run(["git", "init", "-q", root4], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say4 = os.path.join(root4, "say.py")
    with open(say4, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('FAILED tests/test_a.py::"
                 "test_one - AssertionError\\n')\n"
                 "sys.stdout.write('FAILED tests/"
                 "test_other.py::test_two - AssertionError\\n')\n"
                 "sys.stdout.write('2 failed in 0.02s\\n')\n"
                 "raise SystemExit(1)\n")
    mp4 = _plan(root4, say4, {"testGateDerived": derived_shadow}, {})
    lines4 = []
    M.main([mp4, "P1", "--project-dir", root4, "--no-reuse", "--record"],
          out=lines4.append)
    rows4 = _ev_io.read_rows(root4)["rows"]
    check("dg19-allow: a plan with no `meta.phaseGate.mode` at all records "
          "no `shadow` field and prints no shadow line, even with the same "
          "two failing suites and a `testGateDerived` on the phase",
          not any(ln.startswith("shadow:") for ln in lines4)
          and "shadow" not in (rows4[0] if rows4 else {}))

    # --- dg20: SHADOW mode with `testGateBasis` already `derived` -----------
    # An independent case from `dg3s` above: that one is mode `enforce`, so
    # `shadow_gate_claim`'s own first line - `mode != "shadow"` - already
    # returns None before its `testGateBasis` guard is ever reached. This
    # fixture sets mode to `shadow` so the FIRST guard cannot be what is
    # doing the work, and isolates the second one alone.
    root5 = _harness.fixture_root("run-test-gate-shadow-derived-")
    subprocess.run(["git", "init", "-q", root5], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say5 = os.path.join(root5, "say.py")
    with open(say5, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('FAILED tests/test_a.py::"
                 "test_one - AssertionError\\n')\n"
                 "sys.stdout.write('FAILED tests/"
                 "test_other.py::test_two - AssertionError\\n')\n"
                 "sys.stdout.write('2 failed in 0.02s\\n')\n"
                 "raise SystemExit(1)\n")
    mp5 = _plan(root5, say5,
               {"testGateBasis": "derived", "testGateDerived": derived_shadow},
               {"phaseGate": {"mode": "shadow"}})
    lines5 = []
    M.main([mp5, "P1", "--project-dir", root5, "--no-reuse", "--record"],
          out=lines5.append)
    rows5 = _ev_io.read_rows(root5)["rows"]
    check("dg20 RED-FIRST: mode `shadow` AND `phase.testGateBasis == "
          "\"derived\"` together still record no `shadow` field and print "
          "no `shadow:` line, on the SAME two failing suites `dg19` reads a "
          "shadow claim from - the `testGateBasis` guard has to fire on its "
          "own, not only alongside `mode != \"shadow\"`",
          not any(ln.startswith("shadow:") for ln in lines5)
          and "shadow" not in (rows5[0] if rows5 else {}))

    # --- dg21: the derived-step gap must not overwrite an earlier no-verdict
    # outcome/outcomeBasis a step already carries - it appends its own reason
    # instead. The entry here reports one no-verdict signature of its own
    # (a vitest-shaped "no test files" exit) AND names fewer of the listed
    # suites than `testGateDerived.tests` records, so both arms fire on the
    # SAME step. Driven through `run_gate` directly, the same seam `lc16`
    # above uses, because `outcomeBasis` is an in-memory field - it is not
    # among `_evidence_io.STEP_KEYS`, so a committed row is the wrong place
    # to read it back from.
    root6 = _harness.fixture_root("run-test-gate-derived-gap-keeps-")
    subprocess.run(["git", "init", "-q", root6], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say6 = os.path.join(root6, "say6.py")
    with open(say6, "w") as fh:
        fh.write("import sys\n"
                 "sys.stdout.write('tests/test_a.py::test_one\\n')\n"
                 "sys.stdout.write('No test files found, exiting with "
                 "code 1\\n')\n"
                 "raise SystemExit(1)\n")
    res6 = M.run_gate(root6, [("pytest", _step(sys.executable, say6))],
                      derived_check={"entry": "pytest",
                                     "tests": ["tests/test_a.py",
                                              "tests/test_b.py"]})
    step6 = res6["steps"][0]
    check("dg21 RED-FIRST: the step's own no-verdict signature ('vitest "
          "found no test file to run') stays on `outcomeBasis`, and the "
          "derived-gap reason is APPENDED to it rather than replacing it: %r"
          % (step6.get("outcomeBasis"),),
          step6.get("outcome") == M.CANNOT_RUN
          and "vitest found no test file to run" in
              (step6.get("outcomeBasis") or "")
          and "DERIVED RUN NAMED 1 OF 2 LISTED SUITES" in
              (step6.get("outcomeBasis") or ""))


def _own_cases(check):
    """`--own`: an executor's own tests, through the runner rather than bare
    Bash - the bounded render reaches the caller, the whole raw output
    reaches a local log file nobody's context ever sees, and nothing here
    is ever recorded.
    """
    root = _harness.fixture_root("run-test-gate-own-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    big_n = _ev_io.MAX_FAILING + 20
    big_script = os.path.join(root, "big_fail.py")
    with open(big_script, "w") as fh:
        fh.write("import sys\n"
                 "N = %d\n" % (big_n,)
                 + "for i in range(N):\n"
                   "    print('FAILED tests/test_a.py::test_%d - "
                   "AssertionError' % i)\n"
                   "print('=== %d failed in 0.01s ===' % N)\n"
                   "sys.exit(1)\n")
    entry = "%s tests/test_a.py" % (_step(sys.executable, big_script),)

    def _plan(gate, add=None, files=None, gate_basis="declared",
             task_id="P1.1"):
        mp = os.path.join(root, "audit-plan.json")
        tests = {"gateBasis": gate_basis}
        if gate is not None:
            tests["gate"] = gate
        if add is not None:
            tests["add"] = add
        task = {"id": task_id, "title": "t", "status": "in_progress",
               "tests": tests}
        if files is not None:
            task["files"] = files
        with open(mp, "w") as fh:
            json.dump({"meta": {"version": 2, "buildCommands": {
                "lint": "true"}},
                "phases": [{"id": "P1", "title": "p", "status":
                            "in_progress", "testGate": ["lint"],
                            "tasks": [task]}]}, fh)
        return mp

    mp = _plan([entry], add=["tests/test_a.py: covers a"])

    def _run_own(*extra):
        lines = []
        code = M.main([mp, "P1", "--project-dir", root, "--own",
                      "--task", "P1.1"] + list(extra), out=lines.append)
        return code, lines

    code, lines = _run_own("--quiet")
    named = [ln for ln in "\n".join(lines).splitlines()
            if "tests/test_a.py::test_" in ln]
    log_lines = [ln for ln in lines if ln.strip().startswith("raw log:")]
    check("tk1 THE REPRO/RED-FIRST: a fake runner printing far more lines "
          "than the bound, through `--own --quiet`, renders no more than "
          "the bounded failing lines - never the %d this step actually "
          "printed: %r" % (big_n, (len(named), len(log_lines))),
          code == M.E_FAIL and len(named) == _ev_io.MAX_FAILING
          and len(log_lines) == 1)
    log_path = log_lines[0].split("raw log:", 1)[1].strip()
    with open(log_path, encoding="utf-8") as fh:
        log_text = fh.read()
    check("tk1b ...and the LOG holds every line the bounded render dropped: "
          "%r" % (log_text.count("FAILED tests/test_a.py::test_"),),
          log_text.count("FAILED tests/test_a.py::test_") == big_n)

    # A COLON IS NOT A LEGAL CHARACTER IN A WINDOWS FILE NAME, and the run id's
    # time stamp carries two - so a log named by the raw id died on `open` and
    # every `--own` run there crashed. The name is made portable; the id is not.
    log_name = os.path.basename(log_path)
    fresh_id = _ev_io.new_run_id()
    check("own11 RED-FIRST: the raw log's FILE NAME is portable - the run id "
          "with every character outside `[A-Za-z0-9._-]` made `-`, so no colon "
          "(mutation: name the log by the raw run id -> red): %r"
          % ((log_name, M.own_log_name("2026-09-29T10:20:02Z.536528")),),
          ":" not in log_name
          and re.match(r"^\d{4}-\d\d-\d\dT\d\d-\d\d-\d\dZ\.[0-9a-f]{6}\.log$",
                        log_name) is not None
          and M.own_log_name("2026-09-29T10:20:02Z.536528")
          == "2026-09-29T10-20-02Z.536528.log")
    check("own12 ALLOW: ...and the RUN ID ITSELF is untouched - the ledger's "
          "`runId` keeps its colons, because only the file name was the "
          "problem and the id is a recorded value readers already hold: %r"
          % (fresh_id,),
          re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\.[0-9a-f]{6}$",
                    fresh_id) is not None)

    own2_lines = []
    own2_code = M.main([mp, "P1", "--project-dir", root, "--own"],
                       out=own2_lines.append)
    check("own2 ALLOW: `--own` requires `--task` - an executor's own tests "
          "are a task's claim, never a phase's, and the sentence names "
          "THAT reason rather than merely refusing by some other path: %r"
          % (own2_lines,),
          own2_code == M.E_ASK
          and any("--own requires --task" in ln for ln in own2_lines))
    own3_lines = []
    own3_code = M.main([mp, "P1", "--project-dir", root, "--own", "--task",
                       "P1.1", "--record"], out=own3_lines.append)
    check("own3 ALLOW: `--own` refuses `--record` - this run writes no row "
          "and no pointer, ever, and the sentence names `--record` rather "
          "than refusing by some other path: %r" % (own3_lines,),
          own3_code == M.E_ASK
          and any("--own refuses --record" in ln for ln in own3_lines))
    own4_lines = []
    own4_code = M.main([mp, "P1", "--project-dir", root, "--own", "--task",
                       "P1.1", "--reconcile"], out=own4_lines.append)
    check("own4 ALLOW: `--own` refuses `--reconcile` - there is no pointer "
          "from this path for it to repair, and the sentence names "
          "`--reconcile`: %r" % (own4_lines,),
          own4_code == M.E_ASK
          and any("--own refuses --reconcile" in ln for ln in own4_lines))

    gate_only_mp = _plan(None, gate_basis="cleared", task_id="P1.1")
    go_lines = []
    go_code = M.main([gate_only_mp, "P1", "--project-dir", root, "--own",
                      "--task", "P1.1"], out=go_lines.append)
    check("own5 A GATE-ONLY TASK HEARS THE IDENTICAL SENTENCE: nothing of "
          "its own points at its own tests, whether that is because it "
          "declared no entries at all or because every entry it declared "
          "got filtered out - exit 2, naming the task and its gateBasis: %r"
          % (go_lines,),
          go_code == M.E_ASK
          and any("P1.1 declares no gate entry pointed at its own "
                  "tests.add paths (tests.gateBasis=cleared)" in ln
                  and "nothing of its own to run" in ln
                  for ln in go_lines))

    log_dir = os.path.dirname(log_path)
    check("own6 the log directory carries the .gitignore marker "
          "`ensure_local_dir` drops - self-ignoring the moment it exists, "
          "whatever the repository's own `.gitignore` does or does not say: "
          "%r" % (log_dir,),
          os.path.isfile(os.path.join(log_dir, ".gitignore"))
          and open(os.path.join(log_dir, ".gitignore")).read().strip()
          .endswith("*"))
    check("own7 ABSENT `logsDir` MEANS THE CONFIG DEFAULT: no config file "
          "exists in this fixture project at all, and the log still lands "
          "under `.claude/logs/gate-raw` - the same default "
          "`hooks/_config.DEFAULTS['logsDir']` names: %r" % (log_dir,),
          log_dir.replace("\\", "/").endswith(
              ".claude/logs/gate-raw"))

    before_rows = _ev_io.read_rows(root)["rows"]
    _run_own()
    after_rows = _ev_io.read_rows(root)["rows"]
    check("own8 NOTHING IS RECORDED: the ledger carries exactly as many "
          "rows after an `--own` run as before it - no row, and so no "
          "pointer either, whatever the plan's own testEvidence says: %r"
          % ((len(before_rows), len(after_rows)),),
          len(before_rows) == 0 and len(after_rows) == 0)

    # --- own_gate_of, at the unit level: what gets kept and what does not --
    shared_mp_manifest = {
        "meta": {"version": 2, "buildCommands": {"lint": "true",
                                                  "test": "pytest -q"}},
        "phases": [{"id": "P1", "title": "p", "status": "in_progress",
                    "testGate": ["lint", "test"], "tasks": [
                        {"id": "P1.1", "title": "own", "status":
                         "in_progress",
                         "tests": {"gateBasis": "declared",
                                  "gate": ["test", entry,
                                          "%s tests/other.py"
                                          % (_step(sys.executable,
                                                  big_script),)],
                                  "add": ["tests/test_a.py: covers a"]}},
                        {"id": "P1.2", "title": "borrowed", "status":
                         "in_progress"}]}]}
    own_kept, own_source, own_err = M.own_gate_of(
        shared_mp_manifest, "P1", "P1.1")
    check("own9 A `meta.buildCommands` KEY IS NEVER KEPT, whatever it is "
          "spelled - `test` names a build step this task's own claim "
          "cannot narrow, so only the LITERAL command pointed at "
          "`tests/test_a.py` survives, and the entry pointed at "
          "`tests/other.py` (not this task's own path) is dropped too: %r"
          % (own_kept,),
          own_err is None and own_source == "task" and len(own_kept) == 1
          and own_kept[0][0] == entry)
    borrowed_kept, borrowed_source, borrowed_err = M.own_gate_of(
        shared_mp_manifest, "P1", "P1.2")
    check("own10 A TASK MEASURED BY ITS PHASE'S GATE HAS NOTHING OF ITS "
          "OWN, by definition - `own_gate_of` refuses it exactly as it "
          "refuses a task whose every entry got filtered out, never by "
          "falling back to the phase's gate: %r" % (borrowed_err,),
          borrowed_kept is None and borrowed_source is None
          and "P1.2 declares no gate entry" in (borrowed_err or ""))
    # own10's borrowed task names no test, so a rule that let the phase's
    # gate count as the task's own would still keep nothing there. This one
    # declares the very test file the phase's gate names, which is the shape
    # that tells "the phase's entry is never the task's own" from a rule that
    # merely filters it out by path.
    named_manifest = json.loads(json.dumps(shared_mp_manifest))
    named_manifest["phases"][0]["testGate"] = ["lint", entry]
    named_manifest["phases"][0]["tasks"].append(
        {"id": "P1.3", "title": "named by the phase", "status": "in_progress",
         "tests": {"add": ["tests/test_a.py: covers a"]}})
    named_kept, named_source, named_err = M.own_gate_of(
        named_manifest, "P1", "P1.3")
    check("own13 a task with no gate of its own is refused even when the "
          "PHASE's gate names exactly its tests.add file - that entry is the "
          "phase's, not the task's: %r" % ((named_kept, named_err),),
          named_kept is None and named_source is None
          and "P1.3 declares no gate entry" in (named_err or ""))


def _reuse_cases(check):
    """A verdict already measured on these bytes, and everything that must stop it.

    THE CASES COME IN PAIRS ON PURPOSE. Every one that shows a repeat firing has
    one beside it showing it refused, because a repeat is the one feature here
    whose failure mode is SILENCE: a gate that quietly does not run looks exactly
    like a gate that ran and passed, which is the fault this whole file exists
    for wearing a new coat. So the over-fires - two trees that differ, two gates
    that differ - are the cases that matter, and the allow cases are the ones a
    guard tightened until it never fires would break.

    A FUNCTION SO THE BLOCK CAN BE NAMED, for `_interrupt_cases`' reason: the
    fixture is a real repository with a real manifest, and an escape while it is
    being built has to arrive as one named failing case rather than as an escape
    that ends the suite.
    """
    # --- an entry whose SUBJECT is a path the identity leaves out ---------------
    # AHEAD OF THE FIXTURE ON PURPOSE. These three ask a pure function and need no
    # repository, and the rest of this block does - so leaving them at the end put
    # them behind a fixture that any widening of the rule breaks, and the allow
    # case then never ran at all. A case that cannot be reached is not a case, and
    # the whole point of this one is to go red when somebody widens the rule.
    #
    # The identity drops the paths this plugin writes itself, because a recorded
    # run rewrites them and no later run could otherwise match. An entry that
    # GRADES one of those files is what that reasoning does not cover, and it was
    # driven before the rule existed: a gate whose one entry validated the plan
    # reported green over a plan that no longer validated, and wrote `passed`
    # into the phase.
    left_out = ["audit-plan.json", "docs/audit/evidence", "docs/audit/journal"]
    check("ru26 an entry whose command NAMES a path the identity leaves out is "
          "reported, with the entry and the path, so a repeat cannot answer for "
          "bytes the identity never read: %r"
          % (M.grades_left_out([("validate", "python3 v.py audit-plan.json")],
                               left_out),),
          M.grades_left_out([("validate", "python3 v.py audit-plan.json")],
                            left_out) == [("validate", "audit-plan.json")])

    # THE ALLOW CASE, AND IT IS THE ONE THAT MATTERS. Every ordinary gate entry
    # names none of these, so widening this rule to "any entry" would turn the
    # repeat off everywhere - which is the cheap way to make the feature look
    # safe while removing the whole of its value.
    check("ru27 ...and an ordinary entry names none of them, so the repeat stays "
          "available for the gates this feature exists for: %r"
          % (M.grades_left_out([("unit", "pytest -q tests/"),
                                ("lint", "ruff check src")], left_out),),
          M.grades_left_out([("unit", "pytest -q tests/"),
                             ("lint", "ruff check src")], left_out) == [])

    check("ru28 the basename is matched too, because an entry names the plan the "
          "way an operator types it and not the way the manifest resolves it",
          M.grades_left_out([("v", "validate ./audit-plan.json")],
                            ["docs/audit/audit-plan.json"])
          == [("v", "docs/audit/audit-plan.json")])

    root = _harness.fixture_root("run-test-gate-reuse-")
    os.makedirs(os.path.join(root, "docs", "audit", "phases"))
    os.makedirs(os.path.join(root, ".claude"))
    os.makedirs(os.path.join(root, "src"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    for name, body in (("a.py", "declared = 1\n"), ("b.py", "undeclared = 1\n")):
        with open(os.path.join(root, "src", name), "w") as fh:
            fh.write(body)
    mp = os.path.join(root, "docs", "audit", "audit-plan.json")

    def _plan(gate, build):
        """Rewrite the index and the shard. The manifest is OUTSIDE the identity,
        so a case changing the gate is changing exactly one thing."""
        with open(mp, "w") as fh:
            json.dump({"meta": {"version": 3, "buildCommands": build},
                       "phases": [{"id": "P1", "title": "one",
                                   "shard": "phases/P1.json"}]}, fh)
        with open(os.path.join(root, "docs", "audit", "phases", "P1.json"),
                  "w") as fh:
            json.dump({"id": "P1", "title": "one", "status": "in_progress",
                       "testGate": gate, "tasks": [
                           {"id": "P1.1", "title": "t", "status": "in_progress",
                            "files": ["src/a.py"]}]}, fh)

    _plan(["ok"], {"ok": "true", "other": "true", "red": "false"})
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for arg in (["add", "--", "docs", ".claude", "src"],
                ["-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", root] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    evdir = os.path.join(root, "docs", "audit", "evidence")

    def _run(*extra):
        lines = []
        code = M.main([mp, "P1", "--project-dir", root, "--record"]
                      + list(extra), out=lines.append)
        return code, "\n".join(lines)

    # --- what the identity is made of, asked directly -----------------------
    # `reuse_identity` reads `meta.buildCommands` out of whatever manifest it is
    # handed and the ENTRY NAMES out of the commands, so these four cases change
    # one thing each and watch the key. Built inline rather than through files:
    # what is being separated is the declaration from the executed string, and a
    # fixture would put a manifest read between the two.
    declared = {"meta": {"buildCommands": {"ok": "true"}}}
    prefixed = {"meta": {"buildCommands": {"ok": "true"},
                         "nodePreamble": "source ~/.nvm/nvm.sh && nvm use"}}
    plain_key = M.reuse_identity(root, mp, declared, [("ok", "true")],
                                 ["src/a.py"])
    pre_key = M.reuse_identity(
        root, mp, prefixed,
        [("ok", "source ~/.nvm/nvm.sh && nvm use && true")], ["src/a.py"])
    check("ru1 THE COMPARISON IS OVER THE GATE THE MANIFEST DECLARES, NOT OVER "
          "THE EXECUTED STRING. These two runs execute different strings - one "
          "carries `meta.nodePreamble` in front - and they are the same gate, so "
          "they share an identity. Comparing what was executed would make two "
          "operators whose shell preludes differ unable to ever agree: %r"
          % (plain_key["key"] == pre_key["key"],),
          plain_key["key"] is not None
          and plain_key["key"] == pre_key["key"])

    remapped = M.reuse_identity(root, mp, {"meta": {"buildCommands":
                                                    {"ok": "pytest -q"}}},
                                [("ok", "pytest -q")], ["src/a.py"])
    check("ru2 OVER-FIRE, AND IT IS THE ONE COMPARING ENTRY NAMES ALONE FAILS: "
          "the same entry `ok` remapped to a different command is a DIFFERENT "
          "gate. An entry is a label, and a key made of labels would repeat a "
          "verdict measured by a command nobody runs any more: %r"
          % (remapped["key"] != plain_key["key"],),
          remapped["key"] is not None
          and remapped["key"] != plain_key["key"])

    two_entries = M.reuse_identity(
        root, mp, {"meta": {"buildCommands": {"ok": "true", "other": "true"}}},
        [("ok", "true"), ("other", "true")], ["src/a.py"])
    check("ru3 OVER-FIRE: a gate with a SECOND entry in it is not the gate with "
          "one, even where both entries resolve to the same command. Two "
          "commands can fail independently and a verdict over one of them says "
          "nothing about the other: %r"
          % (two_entries["key"] != plain_key["key"],),
          two_entries["key"] != plain_key["key"])

    other_scope = M.reuse_identity(root, mp, declared, [("ok", "true")],
                                   ["src/a.py", "src/b.py"])
    check("ru4 OVER-FIRE: the FILES the work declares are in the identity too. "
          "The ownership split, the coverage answer and the excused red are all "
          "read against that list, so one tree and one gate with two different "
          "declarations reach two different verdicts: %r"
          % (other_scope["key"] != plain_key["key"],),
          other_scope["key"] != plain_key["key"])

    excluded, _no_drops = _ev_io.recorded_paths(root, mp)
    check("ru5 the paths this recorder writes are DERIVED and include the "
          "SHARD, which is the one the assembled manifest cannot name: assembly "
          "replaces every `shard` stub with the phase it points at, so a reader "
          "of the assembled dict leaves the shard inside the identity and no "
          "second run ever matches: %r" % (excluded,),
          "docs/audit/evidence" in excluded
          and "docs/audit/journal" in excluded
          and "docs/audit/audit-plan.json" in excluded
          and "docs/audit/phases/P1.json" in excluded)

    # --- the exclusion, and the identity built on it, must not depend on
    # whether a project's path is spelled through a symlink -----------------
    # A repo is routinely reached through one - /tmp -> /private/tmp on macOS,
    # and every checkout somebody symlinked into place - and `recorded_paths`
    # used to compare a write it built by joining onto `project` against
    # `project` itself with neither side resolved: fine while both spellings
    # agreed, and silently wrong the moment they did not, because a relative
    # path computed from two different spellings of one directory climbs back
    # OUT of it. Guarded the way `test__config.py`'s r7/r8 already are: a
    # platform that will not make a symlink here skips rather than fails.
    _sym_link = root + "-link"
    try:
        os.symlink(root, _sym_link)
        _symlinked = True
    except (OSError, NotImplementedError, AttributeError):
        _symlinked = False
    if not _symlinked:
        print("SKIP ru5a-ru5c (this platform will not create a symlink here)")
    else:
        _link_mp = os.path.join(_sym_link, "docs", "audit", "audit-plan.json")
        _ex_a, _drop_a = _ev_io.recorded_paths(_sym_link, mp)
        _ex_b, _drop_b = _ev_io.recorded_paths(root, _link_mp)
        check("ru5a THE FAULT, FIXED: the project spelled through a symlink "
              "with the manifest spelled plainly, or the other way round, "
              "excludes exactly what ru5 excluded reaching both plainly, with "
              "nothing reported dropped. Before the fix the manifest fell out "
              "of the exclusion on both sides: %r"
              % ((_ex_a, _ex_b, _drop_a, _drop_b),),
              _ex_a == excluded and _ex_b == excluded
              and _drop_a == [] and _drop_b == [])

        _id_link_project = M.reuse_identity(_sym_link, mp, declared,
                                            [("ok", "true")], ["src/a.py"])
        _id_link_manifest = M.reuse_identity(root, _link_mp, declared,
                                             [("ok", "true")], ["src/a.py"])
        check("ru5b ...and the IDENTITY built on that exclusion agrees "
              "whichever side of the pair is spelled through the link, which "
              "is the property a caller actually reads rather than the "
              "exclusion list alone: %r"
              % ((plain_key["key"], _id_link_project["key"],
                  _id_link_manifest["key"]),),
              plain_key["key"] is not None
              and plain_key["key"] == _id_link_project["key"]
              and plain_key["key"] == _id_link_manifest["key"])

        # OVER-FIRE GUARD: resolving both sides must not make two genuinely
        # different repositories - each reached only through its OWN symlink -
        # read as one tree. What must not move (the brief's own words) is that
        # a reused verdict is still refused for a tree that genuinely differs.
        _other_root = _harness.fixture_root("run-test-gate-reuse-other-")
        subprocess.run(["git", "init", "-q", _other_root], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.makedirs(os.path.join(_other_root, "src"))
        with open(os.path.join(_other_root, "src", "a.py"), "w") as fh:
            fh.write("declared = 999\n")
        for arg in (["add", "--", "src"],
                    ["-c", "user.email=fixture@example.com",
                     "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                     "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", _other_root] + arg, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _other_link = _other_root + "-link"
        os.symlink(_other_root, _other_link)
        _other_mp = os.path.join(_other_link, "audit-plan.json")
        _id_other = M.reuse_identity(_other_link, _other_mp, declared,
                                     [("ok", "true")], ["src/a.py"])
        check("ru5c OVER-FIRE GUARD: resolving both sides of the comparison "
              "must not widen what counts as the same tree - a genuinely "
              "DIFFERENT repository, reached only through its own symlink, "
              "still measures a different identity from the fixture's: %r"
              % ((plain_key["key"], _id_other["key"]),),
              _id_other["key"] is not None
              and _id_other["key"] != plain_key["key"])

        # THE SYMLINKS ARE SIBLINGS OF THEIR TARGETS, not children of them, so
        # `_harness.fixture_root`'s own atexit cleanup - registered on `root`
        # and `_other_root` - never reaches them. Removed explicitly, or the
        # sweep's own isolation check (this suite's cwd is a watched
        # directory) names them as debris this suite left behind.
        os.unlink(_other_link)
        os.unlink(_sym_link)

    # --- a write genuinely outside the project (not a symlink of the same
    # file) is REPORTED, not silently dropped from the exclusion -----------
    _outside_mp = os.path.join(os.path.dirname(root), "elsewhere-plan.json")
    _ex_outside, _dropped_outside = _ev_io.recorded_paths(root, _outside_mp)
    check("ru5d a manifest path that is genuinely outside the project still "
          "cannot be excluded, and the miss is NAMED rather than left for a "
          "shrunk count in a basis line to imply: %r" % (_dropped_outside,),
          "docs/audit/audit-plan.json" not in _ex_outside
          and len(_dropped_outside) == 1
          and _dropped_outside[0][0] == os.path.abspath(_outside_mp))

    _sibling_root = _harness.fixture_root("run-test-gate-sibling-")
    subprocess.run(["git", "init", "-q", _sibling_root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _sibling_lines = []
    M.main([mp, "P1", "--project-dir", _sibling_root], out=_sibling_lines.append)
    _sibling_text = "\n".join(_sibling_lines)
    check("ru5e ...and `main` PRINTS that sentence rather than letting the "
          "identity's basis count shrink where nobody is watching: %r"
          % (_sibling_text[:200],),
          "is a path this plugin writes" in _sibling_text
          and "stays inside the content identity" in _sibling_text)

    # --- through `main`, which is where the wiring lives --------------------
    code_one, text_one = _run()
    code_two, text_two = _run()
    rows = _recorded_rows(evdir)
    first, second = rows[0], rows[1]
    check("ru6 THE REQUIREMENT: a second run over an unchanged tree REPEATS the "
          "first run's verdict instead of taking it again, and the summary says "
          "so before it says anything else. The first run measured; this one did "
          "not: exit=%r %r"
          % (code_two, text_two.splitlines()[1:2]),
          code_one == M.E_OK and code_two == M.E_OK
          and "GATE VERDICT REUSED" not in text_one
          and "GATE VERDICT REUSED" in text_two
          # The step table is the discriminator a banner cannot fake: it is
          # printed per command that ran, so a repeat has none of it.
          and "exit 0" in text_one and "exit " not in text_two)

    check("ru7 ...and it NAMES THE RUN IT CAME FROM and the IDENTITY that "
          "matched, both of them, because a repeated verdict with neither is a "
          "claim with no basis - and the way back to a measurement is printed "
          "beside it: %r" % (text_two.splitlines()[2:3],),
          first["runId"] in text_two
          and second[_ev_io.REUSE_KEY] in text_two
          and "--no-reuse" in text_two
          and M.REUSE_LIMIT in text_two)

    check("ru8 ...and the ROW says it too, naming the same run. A summary a "
          "terminal scrolls away is not a record: the ledger is what a later "
          "reader opens, and a repeated verdict that reached it looking like a "
          "measurement is a run this plugin never made: %r"
          % ({"verdictSource": second.get("verdictSource"),
              "reusedFrom": second.get("reusedFrom")},),
          second.get(_ev_io.VERDICT_SOURCE) == _ev_io.REUSED
          and (second.get("reusedFrom") or {}).get("runId") == first["runId"]
          and first.get(_ev_io.VERDICT_SOURCE) is None
          and second.get("status") == first.get("status"))

    check("ru9 ...and it carries NO observation it did not make. Nothing ran, so "
          "there are no steps, no tree comparison and no check count - and each "
          "of those is null with the sentence that says why rather than the "
          "empty list that would mean KNOWN CLEAN: %r"
          % ({"steps": second.get("steps"),
              "treeMutated": second.get("treeMutated")},),
          second.get("steps") == []
          and second.get("treeMutated") is None
          and second["observations"]["ranTotal"] is None
          and "no command ran" in (second["observations"]["treeBasis"] or ""))

    json_lines = []
    code_json = M.main([mp, "P1", "--project-dir", root, "--json"],
                       out=json_lines.append)
    payload = json.loads("\n".join(json_lines))
    check("ru10 ...and the MACHINE half says it as well, which is the third "
          "surface and the one a CI job reads. A consumer switching on `status` "
          "alone would sign this off as a measurement: exit=%r %r"
          % (code_json, payload.get("verdictSource")),
          code_json == M.E_OK and payload.get("status") == "passed"
          and payload.get(_ev_io.VERDICT_SOURCE) == _ev_io.REUSED
          and (payload.get("reusedFrom") or {}).get("runId") == first["runId"]
          and payload.get("steps") == [])

    forced_code, forced_text = _run("--no-reuse")
    forced = _recorded_rows(evdir)[-1]
    check("ru11 THE OPERATOR'S WAY BACK, and it is why a repeat may be the "
          "default at all: `--no-reuse` measures. A cache with no override is a "
          "cache somebody deletes by hand: exit=%r %r"
          % (forced_code, "GATE GREEN" in forced_text),
          forced_code == M.E_OK
          and "GATE VERDICT REUSED" not in forced_text
          and "exit 0" in forced_text
          and forced.get(_ev_io.VERDICT_SOURCE) is None)

    check("ru12 ...and the forced run still RECORDS an identity, which is the "
          "half an override is free to lose: a measurement that recorded none "
          "would leave the next run nothing to match, and one operator's "
          "override would become everybody's: %r"
          % (forced.get(_ev_io.REUSE_KEY) == first.get(_ev_io.REUSE_KEY),),
          forced.get(_ev_io.REUSE_KEY) is not None
          and forced.get(_ev_io.REUSE_KEY) == first.get(_ev_io.REUSE_KEY))

    # THE NEWEST ROW ON THIS IDENTITY HAS TO BE A REPEAT for the next case to be
    # a measurement: with a MEASURED row newest, a version that skipped nothing
    # would land on the right run by accident and the case would assert nothing.
    _run()
    chained = _recorded_rows(evdir)[-1]
    again_code, _again_text = _run()
    again = _recorded_rows(evdir)[-1]
    check("ru13 A REPEAT IS NEVER REPEATED FROM. The newest row carrying this "
          "identity is itself a repeat, and this run reaches PAST it to the run "
          "that MEASURED - a chain of copies would make a reader walk it to find "
          "out whether anything was ever measured at all: newest repeat=%r "
          "named=%r"
          % (chained.get("runId"),
             (again.get("reusedFrom") or {}).get("runId")),
          again_code == M.E_OK
          and chained.get(_ev_io.VERDICT_SOURCE) == _ev_io.REUSED
          and chained.get("runId") != forced["runId"]
          and (again.get("reusedFrom") or {}).get("runId") == forced["runId"])

    # --- OVER-FIRE ONE: two trees that are not the same tree ----------------
    # THE FILE IS UNDECLARED AND ALREADY DIRTY, which is the exact configuration
    # the recorded `testedState` cannot tell apart: its dirty digest records
    # WHICH paths were dirty and never their contents, and `src/b.py` is dirty on
    # both sides. A repeat keyed on that block would skip this run.
    with open(os.path.join(root, "src", "b.py"), "w") as fh:
        fh.write("undeclared = 2\n")
    _run()
    dirty_once = _recorded_rows(evdir)[-1]
    with open(os.path.join(root, "src", "b.py"), "w") as fh:
        fh.write("undeclared = 3\n")
    edited_code, edited_text = _run()
    dirty_twice = _recorded_rows(evdir)[-1]
    check("ru14 OVER-FIRE, AND IT IS THE ONE THE OBVIOUS IDENTITY FAILS: "
          "rewriting an ALREADY-DIRTY file the work does not declare MEASURES "
          "again. Asserted as a pair - the two runs' `testedState` agrees, so "
          "the block a reader would reach for first says these are one run, and "
          "the content identity says they are two: testedState same=%r key "
          "differs=%r"
          % (dirty_once["testedState"] == dirty_twice["testedState"],
             dirty_once.get(_ev_io.REUSE_KEY)
             != dirty_twice.get(_ev_io.REUSE_KEY)),
          edited_code == M.E_OK
          and "GATE VERDICT REUSED" not in edited_text
          and dirty_once["testedState"] == dirty_twice["testedState"]
          and dirty_once.get(_ev_io.REUSE_KEY) is not None
          and dirty_once.get(_ev_io.REUSE_KEY)
          != dirty_twice.get(_ev_io.REUSE_KEY))

    # --- OVER-FIRE TWO: two gates that are not the same gate ----------------
    _plan(["other"], {"ok": "true", "other": "true", "red": "false"})
    gate_code, gate_text = _run()
    check("ru15 OVER-FIRE: the SAME tree with a DIFFERENT gate entry measures. "
          "The manifest is outside the identity's tree half on purpose - this "
          "recorder rewrites it on every run - so the gate half is the only "
          "thing that can catch an edit to it, and a key without it would repeat "
          "a verdict for a gate nobody has run: exit=%r %r"
          % (gate_code, "GATE VERDICT REUSED" in gate_text),
          gate_code == M.E_OK and "GATE VERDICT REUSED" not in gate_text)

    repeat_code, repeat_text = _run()
    check("ru16 ...and the ALLOW case one line later: the new gate's SECOND run "
          "does repeat. A guard tightened until it never fires passes every "
          "case above this one: exit=%r %r"
          % (repeat_code, "GATE VERDICT REUSED" in repeat_text),
          repeat_code == M.E_OK and "GATE VERDICT REUSED" in repeat_text)

    # --- a red verdict is repeated as a red one -----------------------------
    _plan(["red"], {"ok": "true", "other": "true", "red": "false"})
    red_one_code, _red_one = _run()
    red_two_code, red_two_text = _run()
    red_row = _recorded_rows(evdir)[-1]
    check("ru17 A FAILING VERDICT IS REPEATED AS ONE, banner and exit code both. "
          "`reference/orchestrator.md` keys its arms on those literals, so a "
          "repeat printed under a banner of its own would be a line that "
          "document has never heard of - the reader meets `REUSED` first and the "
          "machine still meets the word it switches on: exit=%r/%r %r"
          % (red_one_code, red_two_code, "GATE RED" in red_two_text),
          red_one_code == M.E_FAIL and red_two_code == M.E_FAIL
          and "GATE VERDICT REUSED" in red_two_text
          and "GATE RED: red" in red_two_text
          and red_row.get("status") == "failed"
          and red_row.get("failed") == ["red"])

    # --- which verdicts may be repeated at all ------------------------------
    with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                           "audit-plan.schema.json"), encoding="utf-8") as fh:
        published = set(((((json.load(fh).get("$defs") or {})
                           .get("testEvidence") or {}).get("properties") or {})
                         .get("status") or {}).get("enum") or [])
    sorted_out = M.REUSABLE_STATUS | M.NOT_REUSABLE_STATUS
    check("ru18 EVERY VERDICT THE RUNNER CAN PRODUCE IS SORTED INTO ONE OF THE "
          "TWO SETS, asked of the PUBLISHED enum rather than of a list retyped "
          "here. `empty-gate` is the one word outside it because `main` returns "
          "before a gate runs at all; a word added to the runner and to neither "
          "set lands here rather than in whichever half an arithmetic default "
          "would have handed it: %r"
          % (sorted(published - sorted_out),),
          published - sorted_out == set(("empty-gate",))
          and not (M.REUSABLE_STATUS & M.NOT_REUSABLE_STATUS)
          and M.REUSABLE_STATUS == frozenset(("passed", "failed")))

    identity = M.reuse_identity(root, mp, declared, [("ok", "true")],
                                ["src/a.py"])
    ids = M.subject_ids("P1", None, "phase")

    def _row(status, extra=None):
        row = {"runId": "R-%s" % (status,), "ts": "2026-01-01T00:00:00Z",
               "scope": "phase", "phaseId": "P1", "status": status,
               _ev_io.REUSE_KEY: identity["key"]}
        row.update(extra or {})
        return row

    refused = [w for w in sorted(M.NOT_REUSABLE_STATUS)
               if _ev_io.reusable_run([_row(w)], "phase", ids, identity["key"],
                                      M.REUSABLE_STATUS) is not None]
    check("ru19 ...and not one of the refused words is repeated, each asserted "
          "on its own row. Three of them are facts about the MACHINE or the "
          "operator, which the tree does not hold and a repeat would cache; the "
          "other two are true of the tree and would still be false of THIS run, "
          "which rewrote nothing and counted nothing: %r" % (refused,),
          refused == [])

    check("ru20 THE PAIRED POSITIVE, and it is the one that makes the case above "
          "a measurement rather than a function that always answers None: the "
          "same row with a repeatable word IS found",
          _ev_io.reusable_run([_row("passed")], "phase", ids, identity["key"],
                              M.REUSABLE_STATUS) is not None,
          repr(identity["key"]))

    # THREE ROWS, ONE DIFFERENCE EACH, so the two narrowings are separable: a
    # row that differs in BOTH would be refused by either one on its own and the
    # case would pass with one of them gone.
    other_phase = _row("passed", {"phaseId": "P9"})
    other_scope = _row("passed", {"scope": "task"})
    task_row = _row("passed", {"scope": "task", "taskId": "P1.1"})
    check("ru21 AN IDENTITY IS NOT A SUBJECT. Two tasks can declare the same "
          "files and the same gate, so their runs share a key - and a repeat "
          "has to NAME the run it came from, which makes somebody else's phase, "
          "and the same ids under a different pointer scope, two wrong runs to "
          "name: %r"
          % ([_ev_io.reusable_run([r], "phase", ids, identity["key"],
                                  M.REUSABLE_STATUS)
              for r in (other_phase, other_scope)],),
          _ev_io.reusable_run([other_phase], "phase", ids, identity["key"],
                              M.REUSABLE_STATUS) is None
          and _ev_io.reusable_run([other_scope], "phase", ids, identity["key"],
                                  M.REUSABLE_STATUS) is None
          and _ev_io.reusable_run([task_row], "task",
                                  M.subject_ids("P1", "P1.1", "task"),
                                  identity["key"], M.REUSABLE_STATUS)
          is not None)

    check("ru22 a key that could not be established matches NOTHING, and that is "
          "the same refusal `field_state` makes one module over: `None == None` "
          "is True in Python and false in English, and a tree git would not "
          "describe must never repeat a verdict taken on a tree it could",
          _ev_io.reusable_run([_row("passed", {_ev_io.REUSE_KEY: None})],
                              "phase", ids, None, M.REUSABLE_STATUS) is None)

    # A TREE GIT WILL NOT LIST, DRIVEN THROUGH `main`. A fresh directory with no
    # repository in it: the gate still runs, the verdict is still real, and the
    # one thing that cannot happen is a repeat - in either direction.
    nogit = _harness.fixture_root("run-test-gate-reuse-nogit-")
    os.makedirs(os.path.join(nogit, "docs", "audit"))
    nomp = os.path.join(nogit, "docs", "audit", "audit-plan.json")
    with open(nomp, "w") as fh:
        json.dump({"meta": {"version": 3, "buildCommands": {"ok": "true"}},
                   "phases": [{"id": "P1", "title": "one",
                               "status": "in_progress", "testGate": ["ok"],
                               "tasks": []}]}, fh)
    nogit_lines = []
    nogit_code = M.main([nomp, "P1", "--project-dir", nogit],
                        out=nogit_lines.append)
    nogit_text = "\n".join(nogit_lines)
    check("ru25 WHERE THE IDENTITY CANNOT BE ESTABLISHED, THAT IS WHAT IS SAID. "
          "A missing basis is the thing to report, not a silence a reader has to "
          "diagnose: the gate still ran and still answered, and the one fact "
          "added is that no verdict here can be repeated in either direction: "
          "exit=%r %r" % (nogit_code, nogit_text.splitlines()[1:2]),
          nogit_code == M.E_OK
          and "identity: NOT established" in nogit_text
          and "git would not list this tree" in nogit_text
          and "GATE GREEN" in nogit_text
          and "GATE VERDICT REUSED" not in nogit_text)

    unrenderable = []
    unrenderable_code = M.render_reuse(
        {"status": "no-checks", "failed": [], "reusedFrom": {"runId": "R9"},
         _ev_io.REUSE_KEY: "1:sha256:aa", "reuseBasis": "b"},
        out=unrenderable.append)
    check("ru23 ...and `render_reuse` REFUSES a word it cannot state rather than "
          "falling through to the green line. `main` never hands it one, which "
          "is exactly why this arm has to exist: a word added to one of the two "
          "sets and forgotten here would otherwise print as a pass: exit=%r %r"
          % (unrenderable_code, "\n".join(unrenderable).splitlines()[-1:],),
          unrenderable_code == M.E_FAIL
          and "GATE COULD NOT RUN" in "\n".join(unrenderable)
          and "GATE GREEN" not in "\n".join(unrenderable))

    # THE REFUSAL, END TO END. The pure cases above prove `reusable_run` sorts
    # the words; this proves `main` hands it the set at all. The row is planted
    # rather than produced, because manufacturing a real infrastructure failure
    # would test the OS rather than this decision - and a planted row is exactly
    # what a machine that failed yesterday leaves behind.
    _plan(["ok"], {"ok": "true", "other": "true", "red": "false"})
    seed_code, _seed_text = _run("--no-reuse")
    seeded = _recorded_rows(evdir)[-1]
    # NEWEST BY `ts`, which is what makes this a measurement: an older planted
    # row would be passed over by the newest-wins rule whether the status filter
    # existed or not. A session id is handed in so the writer takes the session
    # path and mints no token file - a write into the tree here would move the
    # very identity the run below has to match.
    _ev_io.append_row(root, {
        "v": _ev_io.ROW_VERSION, "runId": "planted-could-not-run",
        "ts": "2099-01-01T00:00:00Z", "scope": "phase", "phaseId": "P1",
        "status": M.CANNOT_RUN, "failed": [], "steps": [],
        _ev_io.REUSE_KEY: seeded.get(_ev_io.REUSE_KEY)},
        session_id="planted-row")
    after_code, after_text = _run()
    landed = [r for r in _recorded_rows(evdir)
              if r.get("runId") != "planted-could-not-run"][-1]
    check("ru24 AN INFRASTRUCTURE FAILURE IS NEVER REPEATED, through `main` and "
          "not only through the helper. The newest row on this identity says "
          "`could-not-run`, and the repair for that word is to fix the runner "
          "and re-run - a repeat would cache the broken machine and hand it back "
          "to the operator who has just fixed it: exit=%r/%r %r"
          % (seed_code, after_code, "GATE VERDICT REUSED" in after_text),
          seed_code == M.E_OK and after_code == M.E_OK
          and "GATE VERDICT REUSED" in after_text
          and (landed.get("reusedFrom") or {}).get("runId")
          == seeded.get("runId"))


def _interrupt_cases(check):
    """The cases that need a real signal delivered to a real child.

    A FUNCTION SO THE BLOCK CAN BE NAMED. It is run through `_harness.stage`,
    which turns an escape while the fixture is being BUILT into one failing case
    carrying this block's label instead of an escape that ends the suite. That is
    not hypothetical here: on the windows leg the gate step was posix shell, the
    run never reached the point of writing an evidence directory, and reading it
    raised - taking every case after this block out of the run and naming none of
    them.
    """
    # --- a REAL signal, through a real process tree -------------------------
    # THE CASE THAT CANNOT BE WRITTEN WITH A FIXTURE. Every case above drives the
    # `runner` seam, which proves the decision and nothing about delivery: whether
    # a signal sent to this program actually reaches `run_gate` as an interrupt,
    # whether the detached group dies with it, and whether the row lands. So this
    # one spawns the script, waits until a step is genuinely running, and signals
    # it.
    sigroot = _harness.fixture_root("run-test-gate-signal-")
    os.makedirs(os.path.join(sigroot, "docs", "audit", "phases"))
    os.makedirs(os.path.join(sigroot, ".claude"))
    with open(os.path.join(sigroot, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    # The marker carries the GRANDCHILD's pid, so the case can wait for the step
    # to be genuinely under way instead of sleeping and hoping, and can then ask
    # whether the interrupt took the whole group with it.
    marker = os.path.join(sigroot, "grandchild.pid")
    slow = "sleep 45 & echo $! > '%s'; wait" % (marker,)
    smpath = os.path.join(sigroot, "docs", "audit", "audit-plan.json")
    with open(smpath, "w") as fh:
        json.dump({"meta": {"version": 3,
                            "buildCommands": {"quick": "true", "slow": slow}},
                   "phases": [{"id": "P1", "title": "one",
                               "shard": "phases/P1.json"}]}, fh)
    with open(os.path.join(sigroot, "docs", "audit", "phases", "P1.json"),
              "w") as fh:
        json.dump({"id": "P1", "title": "one", "status": "in_progress",
                   "testGate": ["quick", "slow"],
                   "tasks": [{"id": "P1.1", "title": "t",
                              "status": "in_progress", "files": []}]}, fh)
    subprocess.run(["git", "init", "-q", sigroot], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", sigroot, "add", "--", "docs", ".claude"],
                   check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", sigroot, "-c", "user.email=fixture@example.com",
                    "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "base"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    head_before = subprocess.run(["git", "-C", sigroot, "rev-parse", "HEAD"],
                                 stdout=subprocess.PIPE).stdout.decode().strip()

    child = subprocess.Popen(
        [sys.executable, _loader.script_path("run-test-gate.py"),
         smpath, "P1", "--project-dir", sigroot, "--record"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        start_new_session=True)
    grandchild, waited = None, 0.0
    while waited < 40.0:
        try:
            with open(marker) as fh:
                grandchild = int(fh.read().strip())
            break
        except Exception:
            # Bounded, and the failure is REPORTED rather than skipped: a marker
            # that never arrives leaves `grandchild` None and every case below
            # goes red naming it.
            time.sleep(0.05)
            waited += 0.05
    if grandchild is not None:
        os.kill(child.pid, signal.SIGINT)
    else:
        child.kill()
    child_out = (child.communicate(timeout=90)[0] or b"").decode("utf-8",
                                                                 "replace")
    alive = None
    if grandchild is not None:
        time.sleep(0.4)
        try:
            os.kill(grandchild, 0)
            alive = True
        except OSError:
            alive = False
        if alive:
            _harness.attempt(os.kill, grandchild, 9)
    sig_rows = _recorded_rows(os.path.join(sigroot, "docs", "audit", "evidence"))
    sig_row = sig_rows[-1] if sig_rows else {}

    check("is1 A REAL SIGINT, SENT TO A REAL RUN MID-STEP, LANDS A ROW: the "
          "signal reaches `run_gate` as an interrupt, the run is recorded as "
          "`cancelled`, and before this an interrupted run left no record at all "
          "- which made the /audit:resume sweep a sweep with nothing to sweep: "
          "rows=%r %r" % (len(sig_rows), sig_row.get("status")),
          len(sig_rows) == 1 and sig_row.get("status") == M.CANCELLED
          and sig_row.get("cancelledBy") == "SIGINT")

    check("is2 ...and the row carries the step that FINISHED and not the one the "
          "signal cut off. The list is short because the run was short, which is "
          "the difference between a record and a reconstruction: %r"
          % ([st.get("name") for st in (sig_row.get("steps") or [])],),
          [st.get("name") for st in (sig_row.get("steps") or [])] == ["quick"])

    check("is3 ...with `treeMutated` null and the basis naming the race. A "
          "torn-down group may still have been writing, so `[]` - the one value "
          "that means KNOWN CLEAN - would be a claim nobody measured: %r"
          % ((sig_row.get("treeMutated"),
              (sig_row.get("observations") or {}).get("treeBasis")),),
          sig_row.get("treeMutated") is None
          and "interrupted" in str((sig_row.get("observations")
                                    or {}).get("treeBasis")))

    check("is4 ...and the detached group went with it: the grandchild the step "
          "backgrounded is DEAD. A survivor keeps writing into the tree this "
          "record describes, which is the state in which every answer here is a "
          "guess: pid=%r alive_after=%r" % (grandchild, alive),
          grandchild is not None and alive is False)

    check("is5 ...the process exits the code a stopped gate earns and SAYS it "
          "was cancelled, rather than dying with a traceback and no verdict: "
          "exit=%r %r" % (child.returncode, child_out[-70:]),
          child.returncode == M.E_FAIL and "GATE CANCELLED" in child_out
          and "GATE GREEN" not in child_out)

    head_after = subprocess.run(["git", "-C", sigroot, "rev-parse", "HEAD"],
                                stdout=subprocess.PIPE).stdout.decode().strip()
    porcelain = subprocess.run(["git", "-C", sigroot, "status", "--porcelain"],
                               stdout=subprocess.PIPE).stdout.decode()
    check("is6 AND NOTHING WAS COMMITTED. The interrupt path writes and returns; "
          "HEAD has not moved and the row is sitting in the working tree, which "
          "is exactly the state `commit-audit-state.py` sweeps at the next "
          "/audit:resume. A commit made while stopping is the half-made one "
          "nobody reviews: %r" % (head_after == head_before,),
          head_after == head_before and head_before
          and "docs/audit/evidence" in porcelain)

    shard_sig = json.loads(open(os.path.join(sigroot, "docs", "audit",
                                             "phases", "P1.json")).read())
    check("is7 ...while the PLAN did catch up locally: the pointer names the "
          "cancelled run, so `/audit:status` refuses sign-off on it rather than "
          "reading an absent pointer as nothing having happened: %r"
          % (shard_sig.get("testEvidence"),),
          (shard_sig.get("testEvidence") or {}).get("status") == M.CANCELLED
          and (shard_sig.get("testEvidence") or {}).get("runId")
          == sig_row.get("runId"))

    # --- (dc) the coverage answer that needs nothing from the run -------------
    # THE COST WAS ENTIRELY ORDERING. A task declaring no files can be related to
    # no run at all, and that is knowable from the plan - yet the sentence saying
    # so was produced inside `coverage`, which runs after every gate command has
    # finished. So an operator paid for a whole suite to be told this run could
    # tell them nothing.
    _settled = M.declared_coverage_answer([])
    check("dc1 an empty declaration settles the coverage question before "
          "anything runs, and the answer is a PAIR shaped exactly as `coverage` "
          "returns one: %r" % (_settled,),
          _settled is not None and _settled[0] is None
          and "declares no files" in _settled[1])
    for empty in (None, [], ["", "   "], [None, 7]):
        check("dc2 ...and %r is the same empty declaration - a list of blanks "
              "and a list of non-strings name no files either, and the filter "
              "is read ONCE so the answer before the run and the answer after "
              "it are drawn from the same set" % (empty,),
              M.declared_coverage_answer(empty) is not None,
              repr(M.declared_coverage_answer(empty)))
    check("dc3 SECOND-DIRECTION CASE: a task that DOES declare files is not "
          "settled early - None means the run is required, not that coverage is "
          "fine. Every other way the question ends needs the run's own output, "
          "and answering early would be inventing one",
          M.declared_coverage_answer(["src/a.ts"]) is None)
    check("dc4 ...and `coverage` gives the IDENTICAL sentence, because it asks "
          "this first: a second wording for the early answer would be one claim "
          "in two voices, and the day one moved the reader would have two "
          "different reasons for one fact: %r"
          % (M.coverage([], set(["src/a.ts"])),),
          M.coverage([], set(["src/a.ts"])) == _settled)
    check("dc5 ...and the run-required path is untouched: with files declared "
          "and a runner that printed nothing, the answer is still the "
          "not-knowable one the run produces",
          M.coverage(["src/a.ts"], None)[0] is None
          and "not knowable from its output" in M.coverage(["src/a.ts"], None)[1])

    # --- (rc) what the gate set never measures --------------------------------
    # THE BOUNDARY IS REASONABLE AND WAS UNSTATED, which is the whole of this: a
    # reader meeting a green gate with no such sentence beside it reads broader
    # coverage than was taken.
    _claim = M.runtime_claim({"meta": {}})
    check("rt1 a plan with no runtime boot is told, in the gate's own output, "
          "that nothing here opens a browser or starts a server - so a green "
          "verdict is evidence about the commands and about nothing that only "
          "happens at runtime: %r" % (_claim,),
          "opens no browser" in _claim and "starts no server" in _claim
          and "runtimeBoot" in _claim)
    _claim_boot = M.runtime_claim({"meta": {"runtimeBoot": {"appRootPath": "app"}}})
    check("rt2 ...and a plan that DOES declare one is told which step runs it, "
          "rather than being told the same sentence: the two plans are in "
          "different states and a line that could not tell them apart would be "
          "a line nobody reads: %r" % (_claim_boot,),
          "phase sign-off" in _claim_boot and "opens no browser" not in _claim_boot)
    check("rt3 an EMPTY `runtimeBoot` block is the no-boot answer, not the "
          "declared one - a key present and empty is a plan that declared "
          "nothing, and reading it as a declaration would credit the plan with "
          "a check nobody wrote",
          M.runtime_claim({"meta": {"runtimeBoot": {}}}) == _claim
          and M.runtime_claim({"meta": {"runtimeBoot": None}}) == _claim
          and M.runtime_claim({}) == _claim and M.runtime_claim(None) == _claim)
    check("rt4 the claim is DERIVED FROM THE PLAN and never from the command "
          "strings: a gate entry spelled `playwright` does not change it. "
          "Guessing from a command's spelling is the class this plugin keeps "
          "being repaired for, and it would be wrong in both directions on the "
          "first project that wrapped its own runner",
          M.runtime_claim({"meta": {"buildCommands":
                                    {"test": "npx playwright test"}}}) == _claim)


def _group_cases(check):
    """`--also`: one gate run over a GROUP of phases built on one branch owns the
    union of their files, so a rewrite of a file only a non-carrier member declares
    is the gate grading bytes it produced. A real repository and a real command,
    because the ownership answer is read off `git status`."""
    root = _harness.fixture_root("run-test-gate-group-")
    try:
        os.makedirs(os.path.join(root, "src"))
        os.makedirs(os.path.join(root, ".claude"))
        os.makedirs(os.path.join(root, "docs", "audit"))
        with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        for name in ("p1.txt", "p2.txt"):
            with open(os.path.join(root, "src", name), "w") as fh:
                fh.write("0\n")
        mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
        with open(mpath, "w") as fh:
            json.dump({"meta": {"version": 3,
                                "buildCommands": {"rw": "printf 1 > src/p2.txt"}},
                       "phases": [
                           {"id": "P1", "title": "one", "status": "in_progress",
                            "testGate": ["rw"],
                            "tasks": [{"id": "P1.1", "title": "a",
                                       "status": "done", "files": ["src/p1.txt"]}]},
                           {"id": "P2", "title": "two", "status": "in_progress",
                            "testGate": ["rw"],
                            "tasks": [{"id": "P2.1", "title": "b",
                                       "status": "done",
                                       "files": ["src/p2.txt"]}]}]}, fh)

        def reset():
            for arg in (["add", "-A"],
                        ["-c", "user.email=f@e", "-c", "user.name=F",
                         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture",
                         "--allow-empty"]):
                subprocess.run(["git", "-C", root] + arg, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "init", "-q", root], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        reset()

        def run_json(argv):
            lines = []
            code = M.main(argv, out=lines.append)
            try:
                return code, json.loads("\n".join(lines))
            except ValueError:
                return code, {"raw": "\n".join(lines)}
        code, alone = run_json([mpath, "P1", "--project-dir", root, "--json",
                                "--no-reuse"])
        subprocess.run(["git", "-C", root, "checkout", "-q", "--", "src"],
                       check=True)
        code_g, grp = run_json([mpath, "P1", "--also", "P2", "--project-dir", root,
                                "--json", "--no-reuse"])
        check("gg1 a gate run for P1 with --also P2 owns P2's files too, so the "
              "command rewriting src/p2.txt is `gate-mutated`, not a pass: exit %r "
              "status %r" % (code_g, grp.get("status") or grp.get("raw", "")[:200]),
              code_g == M.E_FAIL and grp.get("status") == "gate-mutated")
        check("gg2 SECOND DIRECTION: without --also the same run owns only P1's "
              "files and passes - the union is what widened the refusal: exit %r "
              "status %r" % (code, alone.get("status")),
              code == M.E_OK and alone.get("status") == "passed")
        code_t, _t = run_json([mpath, "P1", "--also", "P2", "--task", "P1.1",
                               "--project-dir", root, "--json"])
        check("gg3 --also is a PHASE-scope group and is refused beside --task, which "
              "narrows to one task: exit %r" % (code_t,), code_t == M.E_ASK)
        code_u, _u = run_json([mpath, "P1", "--also", "P9", "--project-dir", root,
                               "--json"])
        check("gg4 an --also member the plan does not carry is refused, not "
              "skipped: exit %r" % (code_u,), code_u == M.E_ASK)
        subprocess.run(["git", "-C", root, "checkout", "-q", "--", "src"],
                       check=True)
        with open(mpath) as fh:
            _gg = json.load(fh)
        _gg["meta"]["buildCommands"]["rw"] = "true"
        with open(mpath, "w") as fh:
            json.dump(_gg, fh)
        reset()
        M.main([mpath, "P1", "--also", "P2", "--project-dir", root, "--record",
                "--no-reuse"], out=lambda *_a: None)
        M.main([mpath, "P1", "--project-dir", root, "--record", "--no-reuse"],
               out=lambda *_a: None)
        _gg_rows = sorted(_recorded_rows(os.path.join(root, "docs", "audit",
                                                      "evidence")),
                          key=lambda r: str(r.get("ts") or ""))
        _gg_with = [r.get("groupWith") for r in _gg_rows]
        check("gg5 a group run's ledger row names the members it owned, and a run "
              "for the carrier alone names none - the row is where a member's "
              "copied pointer is checked against: %r" % (_gg_with,),
              len(_gg_rows) == 2 and _gg_rows[0].get("groupWith") == ["P2"]
              and "groupWith" not in _gg_rows[1])
        _gg_basis = str((_gg_rows[0].get("observations") or {}).get("coverageBasis"))
        check("gg6 the group run's coverage basis names the files it owned for the "
              "OTHER members by member, so a reader of the carrier's row does not take "
              "them for the carrier's declaration: %r" % (_gg_basis,),
              "src/p2.txt declared by P2 (group member)" in _gg_basis
              and "group member" not in str((_gg_rows[1].get("observations") or {})
                                            .get("coverageBasis")))
        # A group whose other member declares only the carrier's own files has the
        # same owned set as the carrier alone, and still never repeats its solo run.
        with open(mpath) as fh:
            _gg = json.load(fh)
        _gg["phases"][1]["tasks"][0]["files"] = ["src/p1.txt"]
        with open(mpath, "w") as fh:
            json.dump(_gg, fh)
        reset()
        _ev_dir = os.path.join(root, "docs", "audit", "evidence")
        for _name in os.listdir(_ev_dir):
            os.remove(os.path.join(_ev_dir, _name))
        M.main([mpath, "P1", "--project-dir", root, "--record", "--no-reuse"],
               out=lambda *_a: None)
        M.main([mpath, "P1", "--also", "P2", "--project-dir", root, "--record"],
               out=lambda *_a: None)
        _gg7 = sorted(_recorded_rows(_ev_dir), key=lambda r: str(r.get("ts") or ""))
        check("gg7 a group run over the same files as a solo run is MEASURED, not a "
              "repeat of it - the members a run owns are part of what it would have "
              "to match: %r" % ([(r.get("groupWith"), r.get(_ev_io.VERDICT_SOURCE))
                                 for r in _gg7],),
              len(_gg7) == 2 and _gg7[-1].get("groupWith") == ["P2"]
              and _gg7[-1].get(_ev_io.VERDICT_SOURCE) != _ev_io.REUSED)
    finally:
        _harness.remove_tree(root)


def _crowd_cases(check):
    """The machine line reads the ledger's windows: runs recorded one after another
    are not a crowd, a run that genuinely overlapped is, and one whole-second
    stamps cannot place is said to be unknowable rather than shared."""
    root = _harness.fixture_root("run-test-gate-crowd-")
    try:
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
            json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
        evidence = _ev_io.evidence_dir(root)
        os.makedirs(evidence)
        prev = {"runId": "A", _ev_io.STARTED_KEY: "2026-09-26T15:48:37Z",
                "ts": "2026-09-26T15:49:37Z", "scope": "task", "status": "passed"}

        def line_for(row, others, one_writer=True):
            """The machine line for `row`, with `others` written before it by the
            same writer (one chain) or by another writer (another file)."""
            for name in os.listdir(evidence):
                os.remove(os.path.join(evidence, name))
            files = ([("2026-09.t.jsonl", others + [row])] if one_writer
                     else [("2026-09.other.jsonl", others),
                           ("2026-09.t.jsonl", [row])])
            for name, part in files:
                with open(os.path.join(evidence, name), "w") as fh:
                    for r in _ev_io.chain_file(part, name):
                        fh.write(json.dumps(r) + "\n")
            lines = []
            M._say_who_else_was_running(root, {"status": "passed"}, row,
                                        out=lines.append)
            return [ln for ln in lines if "machine:" in ln]
        mine = {"runId": "B", _ev_io.STARTED_KEY: "2026-09-26T15:49:37Z",
                "ts": "2026-09-26T15:50:39Z", "scope": "task", "status": "passed"}
        got = line_for(mine, [prev])
        check("gc1 a run that started in the second the previous run's row was "
              "written had the machine to itself - not a crowd: %r" % (got,),
              len(got) == 1 and "had the machine to itself" in got[0])
        got = line_for(dict(mine, **{_ev_io.STARTED_KEY: "2026-09-26T15:49:30Z"}),
                       [prev])
        check("gc2 SECOND DIRECTION: a run that began seven seconds before the "
              "previous one ended shared the window, and the line names it: %r"
              % (got,),
              len(got) == 1 and "1 other gate run(s) shared this window (A)" in got[0])
        blip = {"runId": "Z", _ev_io.STARTED_KEY: "2026-09-26T15:49:37Z",
                "ts": "2026-09-26T15:49:37Z", "scope": "task", "status": "passed"}
        got = line_for(prev, [blip], one_writer=False)
        check("gc3 a sub-second run stamped in the second this one ended is said to "
              "be unknowable from whole-second stamps, never asserted as sharing "
              "the window: %r" % (got,),
              len(got) == 1 and "whole-second" in got[0] and "Z" in got[0]
              and "shared this window" not in got[0])
        got = line_for(mine, [prev], one_writer=False)
        check("gc4 the same back-to-back pair from TWO writers is said to be "
              "unknowable, never that this run had the machine to itself: %r" % (got,),
              len(got) == 1 and "whole-second" in got[0] and "A" in got[0]
              and "to itself" not in got[0])
        # The gc1 pair again, but the journal records that a ledger merge
        # re-chained the file from the row after R0 through this run.
        first = {"runId": "R0", _ev_io.STARTED_KEY: "2026-09-26T15:40:00Z",
                 "ts": "2026-09-26T15:40:01Z", "scope": "task", "status": "passed"}
        name = "2026-09.t.jsonl"
        for stale in os.listdir(evidence):
            os.remove(os.path.join(evidence, stale))
        chained = _ev_io.chain_file([first, prev, mine], name)
        with open(os.path.join(evidence, name), "w") as fh:
            for r in chained:
                fh.write(json.dumps(r) + "\n")
        _ev_io.record_merge(root, os.path.join(evidence, name),
                            {"relinkedAfter": chained[0]["hash"],
                             "relinkedThrough": chained[-1]["hash"]})
        lines = []
        M._say_who_else_was_running(root, {"status": "passed"}, mine,
                                    out=lines.append)
        got = [ln for ln in lines if "machine:" in ln]
        check("gc5 the gc1 pair inside a stretch a ledger merge re-chained is "
              "said to be unknowable - the re-chain joined two branches in "
              "timestamp order, which is no writer's order: %r" % (got,),
              len(got) == 1 and "whether A ran alongside" in got[0]
              and "to itself" not in got[0])
        real = M._ev.merge_seams
        M._ev.merge_seams = lambda project, config=None: (None, "SEAMS-UNREAD")
        try:
            got = line_for(mine, [prev])
        finally:
            M._ev.merge_seams = real
        check("gc6 ...and when nothing could say whether the ledger was ever "
              "merged, the gc1 pair is unknowable too and the line says why: %r"
              % (got,),
              len(got) == 1 and "SEAMS-UNREAD" in got[0]
              and "to itself" not in got[0])
    finally:
        _harness.remove_tree(root)


def _full_repo(name, fullgate=("ok",), buildcommands=None, mergedhead=None,
              extra_phases=(), preamble=None):
    """A committed git repository whose plan declares `meta.fullGate`.

    Returns `(root, mpath, head)`, `head` being the full sha of the fixture
    commit just made. `fullgate=None` builds a manifest that names no
    third place at all, for the refusal case. `mergedhead`, when given, is
    written onto phase `P1` so a WHOLE claim can be asked of the SAME commit
    this fixture just made - a commit is its own ancestor. `preamble`, when
    given, is written as `meta.nodePreamble` verbatim.
    """
    root = _harness.fixture_root("run-test-gate-full-")
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    meta = {"version": 3,
           "buildCommands": buildcommands or {"ok": "true", "bad": "false"}}
    if fullgate is not None:
        meta["fullGate"] = list(fullgate)
    if preamble is not None:
        meta["nodePreamble"] = preamble
    phases = [{"id": "P1", "title": "one", "status": "in_progress", "tasks": []}]
    if mergedhead is not None:
        phases[0]["mergedHead"] = mergedhead
    phases.extend(extra_phases)
    with open(mpath, "w") as fh:
        json.dump({"meta": meta, "phases": phases}, fh)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for arg in (["add", "--", "docs", ".claude"],
                ["-c", "user.email=fixture@example.com",
                 "-c", "user.name=Fixture", "-c", "commit.gpgsign=false",
                 "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", root] + arg, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return root, mpath, head


def _layout_project_cases(check):
    """A standalone run over a manifest OUTSIDE the default layout records
    into the project `_panel_write.project_of_manifest` names - the first
    ancestor holding `.claude/` - never three directories up from the file.
    The fixture is nested so a count of directories still lands inside it."""
    base = _harness.fixture_root("run-test-gate-layout-")
    try:
        root = os.path.join(base, "outer", "inner", "proj")
        os.makedirs(os.path.join(root, "plans"))
        os.makedirs(os.path.join(root, ".claude"))
        mpath = os.path.join(root, "plans", "plan.json")
        with open(mpath, "w") as fh:
            json.dump({"meta": {"version": 3, "fullGate": ["ok"],
                                "buildCommands": {"ok": "true"}},
                       "phases": []}, fh)
        env_was = os.environ.pop("CLAUDE_PROJECT_DIR", None)
        try:
            lines = []
            code = M.main([mpath, "--full", "--record"], out=lines.append)
        finally:
            if env_was is not None:
                os.environ["CLAUDE_PROJECT_DIR"] = env_was
        here = [r.get("scope") for r in _ev_io.read_rows(root)["rows"]]
        # Three dirnames up from the manifest is <base>/outer/inner.
        stray = [top for top, _dirs, _files in os.walk(base)
                 if os.path.basename(top) == "evidence"
                 and not top.startswith(root + os.sep)]
        check("lp1 RED-FIRST: `run-test-gate.py <root>/plans/plan.json --full "
              "--record`, <root> holding .claude/, records its row in <root>'s "
              "ledger - the helper's answer - and nothing lands three "
              "directories up: %r" % ((code, here, stray,
                                      [ln for ln in lines if "evidence" in ln]),),
              here == ["full"] and stray == [])
    finally:
        _harness.remove_tree(base)


def _full_scope_cases(check):
    # --- the third arm's own refusals: no git, no manifest needed at all ----
    lines = []
    code = M.main(["nowhere.json", "P1", "--full"], out=lines.append)
    check("fg1 RED-FIRST: --full and a phase positional are refused together - "
          "the whole product is never one phase's claim: %r" % (lines,),
          code == M.E_ASK and any("--full" in ln for ln in lines))

    lines = []
    code = M.main(["nowhere.json", "--full", "--task", "P1.1"], out=lines.append)
    check("fg2 RED-FIRST: --full and --task are refused together for the same "
          "reason: %r" % (lines,),
          code == M.E_ASK and any("--task" in ln for ln in lines))

    lines = []
    code = M.main(["nowhere.json", "--project-dir", "/nowhere"], out=lines.append)
    check("fg3 a phase is required unless --full is given - dropping BOTH is "
          "refused rather than reading as one of them: %r" % (lines,),
          code == M.E_ASK)

    # --- no meta.fullGate: exit 2, the sentence this plan names no third place -
    root_none, mpath_none, _head_none = _full_repo("no-fullgate", fullgate=None)
    try:
        lines = []
        code = M.main([mpath_none, "--full", "--project-dir", root_none],
                      out=lines.append)
        check("fg4 RED-FIRST: --full over a plan with no meta.fullGate exits 2 "
              "with the sentence naming what is missing, rather than running "
              "anyway: %r" % (lines,),
              code == M.E_ASK
              and any("no meta.fullGate declared" in ln for ln in lines))
    finally:
        _harness.remove_tree(root_none)

    # --- the ordinary run: scope full, ids {}, no pointer, no boundary ------
    root, mpath, _head = _full_repo("ok")
    try:
        lines = []
        code = M.main([mpath, "--full", "--project-dir", root, "--record"],
                      out=lines.append)
        text = "\n".join(lines)
        rows = _ev_io.read_rows(root)["rows"]
        full_rows = [r for r in rows if r.get("scope") == "full"]
        check("fg5 RED-FIRST: a declared fullGate records a scope-full row "
              "with the head it measured and a clean dirtyOutside, prints "
              "FULL GATE GREEN, and writes no pointer at all: %r"
              % (full_rows and full_rows[0],),
              code == M.E_OK and "FULL GATE GREEN at" in text
              and len(full_rows) == 1)
        row = full_rows[0]
        check("fg5b ...and the row itself carries no taskId/phaseId (ids={}), "
              "an empty dirtyOutside, and the ONE resolution both places use "
              "for its published commands: %r"
              % ({k: row.get(k) for k in ("taskId", "phaseId")},),
              "taskId" not in row and "phaseId" not in row
              and row["observations"]["dirtyOutside"] == []
              and row["steps"][0]["command"] == "true")
        manifest_after = json.loads(open(mpath).read())
        check("fg6 ...NO pointer (write_pointer is never called for scope "
              "full) and NO evidence boundary stamp: %r"
              % (manifest_after["phases"][0].get("testEvidence"),),
              "testEvidence" not in manifest_after["phases"][0]
              and "evidenceSince" not in manifest_after["meta"])

        # --- ordering: the row is written before the summary is printed ----
        recorded_at = next(i for i, ln in enumerate(lines)
                           if ln.startswith("  evidence: recorded"))
        banner_at = next(i for i, ln in enumerate(lines)
                         if ln.startswith("FULL GATE"))
        check("fg7 the evidence line is printed BEFORE the FULL GATE banner - "
              "the row must survive an operator's own tool timeout landing "
              "between the run finishing and this process finishing its "
              "summary: recorded@%d banner@%d" % (recorded_at, banner_at),
              recorded_at < banner_at)
    finally:
        _harness.remove_tree(root)

    # --- a dirty tree certifies nothing, but the run still happens ---------
    root_d, mpath_d, _head_d = _full_repo("dirty")
    try:
        with open(os.path.join(root_d, "untracked.txt"), "w") as fh:
            fh.write("uncommitted\n")
        lines = []
        code = M.main([mpath_d, "--full", "--project-dir", root_d, "--record"],
                      out=lines.append)
        text = "\n".join(lines)
        rows = _ev_io.read_rows(root_d)["rows"]
        row = [r for r in rows if r.get("scope") == "full"][0]
        check("fg8 RED-FIRST: a dirty tree outside the recorder's own paths "
              "prints FULL RUN ON A DIRTY TREE and is carried onto the row - "
              "the run still happens and is still recorded: %r"
              % (row["observations"]["dirtyOutside"],),
              "FULL RUN ON A DIRTY TREE" in text
              and code == M.E_OK
              and any("untracked.txt" in p
                     for p in row["observations"]["dirtyOutside"]))
    finally:
        _harness.remove_tree(root_d)

    # --- --writer names a CI shard's own ledger file ------------------------
    root_w, mpath_w, _head_w = _full_repo("writer")
    try:
        code = M.main([mpath_w, "--full", "--project-dir", root_w, "--record",
                      "--writer", "ci-42"], out=(lambda _l: None))
        ev_dir = _ev_io.evidence_dir(root_w)
        names = os.listdir(ev_dir)
        check("fg9 RED-FIRST: --writer ci-42 lands in a file named for it - a "
              "CI build's identity must not be split by session: %r" % (names,),
              code == M.E_OK and any("ci-42" in n for n in names))
    finally:
        _harness.remove_tree(root_w)

    # --- a full run recorded by --full is judged WHOLE by full_status ------
    # A COUNTABLE COMMAND, unlike the bare `true` the other fixtures use:
    # `_full_disqualification` refuses a row whose `ranTotal` is not knowable
    # ("the full run counted nothing"), so a whole-bearing row needs a summary
    # this gate's own reader can count.
    root_w2, mpath_w2, head_full = _full_repo(
        "whole", buildcommands={"ok": "echo '1 passed in 0.01s'"})
    try:
        code = M.main([mpath_w2, "--full", "--project-dir", root_w2, "--record"],
                      out=(lambda _l: None))
        manifest_now = json.loads(open(mpath_w2).read())
        phase = dict(manifest_now["phases"][0], mergedHead=head_full)
        rows = _ev_io.read_rows(root_w2)["rows"]
        # `full_commands` IS THE BARE COMMAND HALF of `resolved_commands` -
        # see `_evidence_io.full_status`'s own docstring for why that, and
        # not the (name, command) pairs, is the contract.
        full_commands = [c for _n, c in M._ev.resolved_commands(
            manifest_now, manifest_now["meta"]["fullGate"])]
        status = M._ev.full_status(rows, phase, root_w2, full_commands)
        check("fg10 a full run recorded by --full, measured at this repo's own "
              "HEAD, is judged WHOLE by full_status once the phase's own "
              "mergedHead is that same commit - the SAME resolution and the "
              "SAME rows a real /audit:phase would read: %r" % (status,),
              code == M.E_OK
              and status["answer"] == _manifest_vocab.FULL_STATUS_WHOLE)
        # The comparison above reads its expected commands from the function
        # it is judging, so a resolution that went wrong on both sides would
        # still agree with itself. The literal below is written by hand: the
        # `buildCommands` value the fixture's `fullGate` names.
        recorded = [s.get("command") for r in rows if r.get("scope") == "full"
                    for s in r.get("steps") or []]
        check("fg10b ...and the command the run recorded is the fixture's "
              "declared gate spelled out by hand, not re-derived by the "
              "resolver under test: %r" % (recorded,),
              recorded == ["echo '1 passed in 0.01s'"])
    finally:
        _harness.remove_tree(root_w2)

    # --- the same run with meta.nodePreamble set ----------------------------
    # Padded with whitespace on purpose: the preamble is stripped before it is
    # joined with `&&`, so a literal that kept the padding, or one that
    # dropped the preamble, would each tell a mis-resolution apart.
    root_p, mpath_p, _head_p = _full_repo(
        "preamble", buildcommands={"ok": "echo '1 passed in 0.01s'"},
        preamble="  export FIXTURE_PREAMBLE=on  ")
    try:
        code = M.main([mpath_p, "--full", "--project-dir", root_p, "--record"],
                      out=(lambda _l: None))
        rows = _ev_io.read_rows(root_p)["rows"]
        recorded = [s.get("command") for r in rows if r.get("scope") == "full"
                    for s in r.get("steps") or []]
        check("fg10c ...and with meta.nodePreamble set, the recorded command "
              "is the preamble, stripped, joined to the declared gate by `&&` "
              "- written here by hand, so a resolver that dropped or "
              "mis-joined the preamble cannot agree with itself: %r"
              % (recorded,),
              code == M.E_OK
              and recorded == [
                  "export FIXTURE_PREAMBLE=on && echo '1 passed in 0.01s'"])
    finally:
        _harness.remove_tree(root_p)


# --- the --full post-pass: a failing suite no derived gate selected ------------
# The gate script lives OUTSIDE the fixture repository, so a green run before
# the red one measures a clean tree and can bear whole. The mode file beside it
# picks which output the one declared `fullGate` command prints this time: the
# earlier row and the later one must run the SAME command, or the earlier one
# would not be a measured full run against the plan's own declaration. The
# suite the gate names is a TRACKED file of the fixture, as a real runner's is:
# the post-pass pins each named suite to one tracked path before asking whether
# a derived gate listed it.
_SM_SUITE = "e2e/cart.spec.ts"
# Two packages carrying one suite name: a runner started with `--root pkg1`
# prints `tests/x.test.js` for the first, which a suffix reading would also
# find at the end of the second.
_SM_SIBLING_A = "pkg1/tests/x.test.js"
_SM_SIBLING_B = "pkg2/tests/x.test.js"


def _sm_track_suite(root, suite=_SM_SUITE):
    path = os.path.join(root, suite)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("// %s\n" % (suite,))
    return suite.split("/", 1)[0]
# The fake runner writes UTF-8 BYTES, as jest does whatever its parent's stream
# is. A text-stream `print` encodes through the child's own stdout codec, so on a
# legacy code page the bullet raises instead of printing and the runner under
# test reads a traceback where a named suite should be.
_SM_GATE = """\
import sys
def say(line):
    sys.stdout.buffer.write((line + "\\n").encode("utf-8"))
mode = open(sys.argv[1]).read().strip()
if mode == "green":
    say("PASS e2e/cart.spec.ts")
    say("Tests:       4 passed, 4 total")
    sys.exit(0)
if mode == "named":
    say("FAIL e2e/cart.spec.ts")
    say("  \\u25cf cart > adds an item")
    say("")
    say("Tests:       1 failed, 3 passed, 4 total")
    sys.exit(1)
say("boom")
say("at e2e/cart.spec.ts:3")
sys.exit(1)
"""

_SM_GIT = ["-c", "user.email=fixture@example.com", "-c", "user.name=Fixture",
           "-c", "commit.gpgsign=false"]


def _sm_git(root, *args):
    return subprocess.run(["git", "-C", root] + _SM_GIT + list(args),
                          check=True, capture_output=True,
                          text=True).stdout.strip()


def _sm_fixture():
    """`{root, mpath, gate_dir, mode, first}` - a committed repository whose
    plan declares one `fullGate` command, and the file choosing its output.

    `first` is the sha of the fixture's first commit; `_sm_commit` makes the
    later ones, so a merged phase's `mergedHead` is a REAL ancestor of the
    run's head and the ancestry question is really asked of git.
    """
    root = _harness.fixture_root("run-test-gate-miss-")
    gate_dir = _harness.fixture_root("run-test-gate-miss-gate-")
    script = os.path.join(gate_dir, "gate.py")
    mode = os.path.join(gate_dir, "mode")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_SM_GATE)
    os.makedirs(os.path.join(root, "docs", "audit"))
    os.makedirs(os.path.join(root, ".claude"))
    with open(os.path.join(root, ".claude", "audit.config.json"), "w") as fh:
        json.dump({"manifestPath": "docs/audit/audit-plan.json"}, fh)
    mpath = os.path.join(root, "docs", "audit", "audit-plan.json")
    fx = {"root": root, "mpath": mpath, "gate_dir": gate_dir, "mode": mode,
          "command": _step(sys.executable, script, mode)}
    _sm_plan(fx, [])
    top = _sm_track_suite(root)
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _sm_git(root, "add", "--", "docs", ".claude", top)
    _sm_git(root, "commit", "-qm", "fixture")
    fx["first"] = _sm_git(root, "rev-parse", "HEAD")
    return fx


def _sm_plan(fx, phases):
    with open(fx["mpath"], "w") as fh:
        json.dump({"meta": {"version": 3, "fullGate": ["e2e"],
                            "buildCommands": {"e2e": fx["command"]}},
                   "phases": [{"id": "P1", "title": "one",
                               "status": "in_progress", "tasks": []}]
                  + list(phases)}, fh)


def _sm_commit(fx, name):
    path = os.path.join(fx["root"], "src", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("%s\n" % (name,))
    _sm_git(fx["root"], "add", "--", "src")
    _sm_git(fx["root"], "commit", "-qm", name)
    return _sm_git(fx["root"], "rev-parse", "HEAD")


def _sm_phase(pid, merged_head, tests, files):
    return {"id": pid, "title": pid, "status": "done",
            "mergedAt": "2026-09-01T00:00:00Z", "mergedHead": merged_head,
            "testGateDerived": {"tests": list(tests)},
            "tasks": [{"id": "%s.1" % (pid,), "title": "t", "status": "done",
                       "files": list(files)}]}


def _sm_run(fx, mode):
    with open(fx["mode"], "w") as fh:
        fh.write(mode)
    lines = []
    code = M.main([fx["mpath"], "--full", "--project-dir", fx["root"],
                   "--record"], out=lines.append)
    full_rows = [r for r in _ev_io.read_rows(fx["root"])["rows"]
                 if r.get("scope") == "full"]
    return code, lines, full_rows[-1] if full_rows else {}


def _sm_remove(fx):
    _harness.remove_tree(fx["root"])
    _harness.remove_tree(fx["gate_dir"])


def _sm_commands(line):
    """The `audit-task.py` commands a SELECTION MISS line's remedy carries,
    each as the argv its parser would be handed - whatever explanation the
    remedy holds sits before the colon and never among the commands."""
    tail = _sm_remedy_text(line)
    parts = tail.split("; python3 ")
    texts = [parts[0]] + ["python3 " + p for p in parts[1:]]
    return [shlex.split(t) for t in texts]


def _sm_remedy_text(line):
    """Everything after a remedy's colon - the commands alone."""
    tail = line.split("remedy", 1)[1]
    return tail.split("): ", 1)[1] if tail.startswith(" (") else tail[2:]


def _sm_parses(argvs):
    """`[(verb, args-or-None)]` - each argv through audit-task's own parser,
    exactly as its `main` parses (`parse_intermixed_args`). Each argv is
    `python3 <audit-task.py> <verb> ...`, so the verb is its third word and
    the script its second, which must be the one `_loader` resolves."""
    parser = _AT.build_parser()
    script = _loader.script_path("audit-task.py")
    parsed = []
    for argv in argvs:
        if argv[:2] != ["python3", script]:
            parsed.append((None, None))
            continue
        try:
            with _ctx.redirect_stderr(_io.StringIO()):
                parsed.append((argv[2], parser.parse_intermixed_args(argv[2:])))
        except SystemExit:
            parsed.append((argv[2] if len(argv) > 2 else None, None))
    return parsed


def _sm_since_row(run_id, head, commands):
    """A whole-bearing scope-full row at `head`: passed, measured, counted
    with a basis, every step timed, a clean tree, the declared commands."""
    return {"v": _ev_io.ROW_VERSION, "runId": run_id,
            "ts": "2026-09-01T00:00:00Z", "scope": _ev_io.FULL_SCOPE,
            "status": "passed",
            "steps": [{"name": "gate", "command": c, "exit": 0,
                       "durationMs": 10} for c in commands],
            "testedState": {"head": head},
            "observations": {"ranTotal": 4, "countsBasis": "4 checks",
                             "dirtyOutside": []}}


_SM_NAMED = ("the 1 suite file(s) jest named as failing, read from jest's "
             "FAIL <path> header(s)")
_SM_STEP = {"name": "e2e", "exit": 1, "failingSuites": ["e2e/cart.spec.ts"],
            "failingSuitesBasis": _SM_NAMED,
            "failingBasis": "the 1 check(s) jest named as failing"}


def _sm_pair():
    """`(root, first, second)` - a real repository with two commits, `first`
    a real ancestor of `second`, so both ancestry questions go to git."""
    root = _harness.fixture_root("run-test-gate-miss-pair-")
    subprocess.run(["git", "init", "-q", root], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shas = []
    for suite in (_SM_SUITE, _SM_SIBLING_A, _SM_SIBLING_B):
        _sm_git(root, "add", "--", _sm_track_suite(root, suite))
    for name in ("a.txt", "b.txt"):
        with open(os.path.join(root, name), "w") as fh:
            fh.write(name)
        _sm_git(root, "add", "--", name)
        _sm_git(root, "commit", "-qm", name)
        shas.append(_sm_git(root, "rev-parse", "HEAD"))
    return root, shas[0], shas[1]


def _selection_miss_cases(check):
    # --- a named failure no merged phase's derived gate listed -------------
    fx = _sm_fixture()
    try:
        code_green, _lines, green = _sm_run(fx, "green")
        second = _sm_commit(fx, "cart.ts")
        _sm_plan(fx, [_sm_phase("P2", second, ["e2e/other.spec.ts"],
                                ["src/cart.ts", "src/pay.ts"])])
        code, lines, row = _on_legacy_codec(lambda: _sm_run(fx, "named"))
        run_id = row.get("runId")
        # The row records the head abbreviated; it must still be the commit
        # the phase merged at, or ancestry was never asked.
        head = (row.get("testedState") or {}).get("head") or ""
        at = "python3 %s" % (shlex.quote(_loader.script_path("audit-task.py")),)
        want = ("SELECTION MISS: e2e/cart.spec.ts failed at the third place "
                "and no derived sign-off gate in P2 listed it. remedy: "
                "%s couple --test e2e/cart.spec.ts --sources "
                "src/cart.ts,src/pay.ts --basis-run %s --basis-head %s "
                "--phases P2 %s --project-dir %s; %s bug-add "
                % (at, shlex.quote(str(run_id)), shlex.quote(head),
                   shlex.quote(os.path.abspath(fx["mpath"])),
                   shlex.quote(os.path.abspath(fx["root"])), at))
        misses = [ln for ln in lines if ln.startswith("SELECTION MISS:")]
        check("sm1 RED-FIRST: a full run failing on a suite the runner NAMED, "
              "with one phase merged since the earlier green run (%s) whose "
              "derived gate does not list it, prints exactly one SELECTION "
              "MISS whose remedy is the couple and bug-add spelling "
              "audit-task accepts - with the runner's stream pinned to cp1252, "
              "so a fake runner that cannot write jest's bullet as bytes loses "
              "the suite name on every run: %r" % (green.get("runId"), misses),
              code_green == M.E_OK and code == M.E_FAIL and len(misses) == 1
              and len(head) >= 7 and second.startswith(head)
              and misses[0].startswith(want))
        check("sm1b ...and the row records it as `selectionMiss`, naming the "
              "suite, the phase whose derived gate missed it, and that "
              "phase's tasks' files as the sources: %r"
              % (row.get("selectionMiss"),),
              row.get("selectionMiss") == [
                  {"test": "e2e/cart.spec.ts", "phases": ["P2"],
                   "sources": ["src/cart.ts", "src/pay.ts"]}])
        check("sm1c ...and no not-learned or not-asked line beside it - the "
              "runner named the suite and the work since is bounded: %r"
              % (lines,),
              not any(ln.startswith("not learned:")
                      or ln.startswith("SELECTION MISS not asked")
                      for ln in lines))
        parsed = _sm_parses(_sm_commands(misses[0]) if misses else [])
        check("sm1d ...and both remedy commands shlex-split and parse through "
              "audit-task's own parser, carrying the values the miss names: "
              "%r" % ([(v, a and vars(a)) for v, a in parsed],),
              [v for v, _a in parsed] == ["couple", "bug-add"]
              and all(a is not None for _v, a in parsed)
              and parsed[0][1].test == "e2e/cart.spec.ts"
              and ",".join(parsed[0][1].sources).split(",")
              == ["src/cart.ts", "src/pay.ts"]
              and parsed[0][1].basis_run == run_id
              and parsed[0][1].phases == ["P2"]
              and parsed[1][1].files == ["e2e/cart.spec.ts"])

        # --- the same failure, but the runner named nothing --------------
        code, lines, row = _sm_run(fx, "tail")
        basis = [s.get("failingBasis") for s in row.get("steps") or []]
        unlearned = [ln for ln in lines if ln.startswith("not learned:")]
        check("sm2 RED-FIRST: the same failure read only off the output's "
              "TAIL records no selectionMiss and prints the not-learned line "
              "with the basis the step carries - a tail is not a list of "
              "failing suites: %r" % ((row.get("selectionMiss"), unlearned),),
              code == M.E_FAIL and "selectionMiss" not in row
              and not any(ln.startswith("SELECTION MISS") for ln in lines)
              and unlearned == [
                  "not learned: the runner did not name the failing suites "
                  "(basis: %s)" % (basis[0],)])

        # --- --json carries the whole post-pass under one key ------------
        with open(fx["mode"], "w") as fh:
            fh.write("named")
        jlines = []
        # A dump that raises is this case's failure, never the suite's: a
        # step carrying a set once made every `--json` path raise here.
        try:
            M.main([fx["mpath"], "--full", "--project-dir", fx["root"],
                    "--json"], out=jlines.append)
        except TypeError as exc:
            jlines = ["{\"raised\": %s}" % (json.dumps(str(exc)),)]
        blob = json.loads([ln for ln in jlines if ln.startswith("{")][0])
        spass = blob.get("selectionPass") or {}
        check("sm6 --json carries the WHOLE post-pass under `selectionPass` - "
              "misses, unnamed, unasked, reasons and the bounding run - while "
              "the row keeps only the allow-listed misses: %r" % (spass,),
              [m["test"] for m in spass.get("misses") or []]
              == ["e2e/cart.spec.ts"]
              and spass.get("since", {}).get("runId") == green.get("runId")
              and all(k in spass for k in ("unnamed", "unasked", "reasons"))
              and "selectionPass" not in row)

        # --- ALLOW: a suite a derived gate listed is not a miss ----------
        _sm_plan(fx, [_sm_phase("P2", second,
                                ["e2e/other.spec.ts", "e2e/cart.spec.ts"],
                                ["src/cart.ts"])])
        code, lines, row = _sm_run(fx, "named")
        check("sm3 ALLOW: a failing suite a merged phase's derived gate "
              "LISTED is not a miss - the selection was right and the suite "
              "caught something: %r" % ((row.get("selectionMiss"), lines),),
              code == M.E_FAIL and "selectionMiss" not in row
              and not any(ln.startswith("SELECTION MISS") for ln in lines))

        # THE PRINTED REMEDY IS RUN AS A SHELL WOULD RUN IT, from a directory
        # that is not the project: a bare `audit-task.py` is 'command not
        # found' there, and a plan the command does not name is not found.
        # The shell is the one the plan's own commands run under, so this
        # case runs wherever the product does - Windows with Git's `sh`
        # included - and skips only where the product itself refuses.
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        sm_argv, env, sm_why = _pg.shell_invocation(
            _sm_remedy_text(misses[0]) if misses else "false", env)
        if sm_argv is None:
            _harness.skip(check, "sm16", "no POSIX shell here to run the "
                          "printed remedy through: %s" % (sm_why,), True)
        else:
            away = _harness.fixture_root("run-test-gate-miss-away-")
            try:
                proc = subprocess.run(
                    sm_argv, cwd=away, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    universal_newlines=True)
            finally:
                _harness.remove_tree(away)
            with open(fx["mpath"]) as fh:
                ran_plan = json.load(fh)
            coupled = [e.get("test") for e in
                       (ran_plan.get("meta") or {}).get("coupling") or []]
            bugs = [(b.get("title"), b.get("files"))
                    for b in ran_plan.get("bugs") or []]
            check("sm16 RED-FIRST: the SELECTION MISS remedy runs as printed "
                  "under the resolved POSIX sh from another directory, exit 0, and "
                  "leaves the coupling and the bug it spells in the plan: "
                  "%r" % ((proc.returncode, proc.stdout[-400:], coupled,
                           bugs),),
                  proc.returncode == 0 and coupled == [_SM_SUITE]
                  and bugs == [("SELECTION MISS: %s" % (_SM_SUITE,),
                                [_SM_SUITE])])
    finally:
        _sm_remove(fx)

    # --- ALLOW: a phase merged before the newest earlier green full row ----
    fx = _sm_fixture()
    try:
        code_green, _lines, green = _sm_run(fx, "green")
        second = _sm_commit(fx, "pay.ts")
        _sm_plan(fx, [_sm_phase("P2", fx["first"], ["e2e/other.spec.ts"],
                                ["src/old.ts"]),
                      _sm_phase("P3", second, ["e2e/other.spec.ts"],
                                ["src/pay.ts"])])
        code, lines, row = _sm_run(fx, "named")
        check("sm4 ALLOW: a phase whose mergedHead the newest earlier "
              "measured green full run (%s) already contained is not "
              "counted - only P3, merged since, is named, and only its files "
              "are the sources: %r"
              % (green.get("runId"), (row.get("selectionMiss"), lines)),
              code_green == M.E_OK and code == M.E_FAIL
              and row.get("selectionMiss") == [
                  {"test": "e2e/cart.spec.ts", "phases": ["P3"],
                   "sources": ["src/pay.ts"]}])
    finally:
        _sm_remove(fx)

    # --- no earlier measured full run: nothing bounds the work, no learn ---
    fx = _sm_fixture()
    try:
        second = _sm_commit(fx, "cart.ts")
        _sm_plan(fx, [_sm_phase("P2", second, ["e2e/other.spec.ts"],
                                ["src/cart.ts"])])
        code, lines, row = _sm_run(fx, "named")
        check("sm7 with NO earlier measured full run, nothing is learned "
              "- 'the work since' would be the whole history - and the "
              "post-pass says so rather than falling silent: %r"
              % ((row.get("selectionMiss"), lines),),
              code == M.E_FAIL and "selectionMiss" not in row
              and not any(ln.startswith("SELECTION MISS:") for ln in lines)
              and "SELECTION MISS not asked: no earlier measured full "
                  "run bounds the work since" in lines)
    finally:
        _sm_remove(fx)

    # --- a ledger line lost: `--full` asks no miss, and names the file -----
    fx = _sm_fixture()
    try:
        code_green, _lines, green = _sm_run(fx, "green")
        second = _sm_commit(fx, "cart.ts")
        _sm_plan(fx, [_sm_phase("P2", second, ["e2e/other.spec.ts"],
                                ["src/cart.ts"])])
        ledger_file = _ev_io.ledger_files(fx["root"])[-1]
        with open(ledger_file, "a", encoding="utf-8") as fh:
            fh.write("{\"v\": 1, \"runId\": \"LOST\", this line is torn}\n")
        lost_name = _output.posix_rel(ledger_file, fx["root"])
        code, lines, row = _sm_run(fx, "named")
        said = [ln for ln in lines if ln.startswith("SELECTION MISS")]
        check("sm20 RED-FIRST: `--full` over a ledger with an unreadable line "
              "asks no selection miss - the bounding run may be the lost "
              "one - and prints one not-asked line naming the file: %r"
              % ((code_green, code, said, row.get("selectionMiss")),),
              code_green == M.E_OK and code == M.E_FAIL
              and "selectionMiss" not in row and len(said) == 1
              and said[0].startswith("SELECTION MISS not asked: the evidence "
                                     "ledger could not be read in full (")
              and lost_name in said[0])
    finally:
        _sm_remove(fx)

    # --- the pure post-pass over a real two-commit repository --------------
    # The bounding run sits at `first`; a phase merged at `second` is merged
    # since it. Each case changes ONE thing about that phase or that run.
    root, first, second = _sm_pair()
    try:
        since = [_sm_since_row("R-since", first, ["x"])]

        def post(phases, steps=None, rows=None):
            return M._ev.selection_miss(steps or [_SM_STEP], phases, second,
                                        root, since if rows is None else rows,
                                        ["x"])

        derived = _sm_phase("P2", second, ["e2e/other.spec.ts"], ["src/a.ts"])
        plain = post([derived])
        muted = post([derived], steps=[dict(
            _SM_STEP, muted=[{"test": "e2e/cart.spec.ts", "bugId": "B1",
                              "until": "2099-01-01"}])])
        check("sm5 ALLOW: a muted step's suite is never a miss and never a "
              "not-learned line - the quarantine is known, and the same step "
              "unmuted IS a miss, so the fixture can tell the two apart: %r"
              % ((plain, muted),),
              [m["test"] for m in plain["misses"]] == ["e2e/cart.spec.ts"]
              and muted["misses"] == [] and muted["unnamed"] == [])

        underived = dict(derived)
        del underived["testGateDerived"]
        res = post([underived])
        check("sm8 ALLOW: a phase merged since that signed off on a gate that "
              "was NOT derived made no selection, so it is no miss - and one "
              "line names it rather than the post-pass going silent: %r"
              % (res,),
              res["misses"] == [] and res["underived"] == ["P2"]
              and res["phases"] == []
              and any("(P2) signed off on a gate that was not derived" in r
                      for r in res["reasons"]))

        with_cancelled = dict(derived, tasks=derived["tasks"] + [
            {"id": "P2.2", "title": "t", "status": "cancelled",
             "files": ["src/never.ts"]}])
        res = post([with_cancelled])
        check("sm9 ALLOW: a cancelled task's files are not sources - that "
              "work never landed, so a coupling to it would be to nothing: %r"
              % ([m["sources"] for m in res["misses"]],),
              [m["sources"] for m in res["misses"]] == [["src/a.ts"]])

        headless = dict(derived)
        del headless["mergedHead"]
        res = post([headless])
        check("sm10 a merged phase with NO mergedHead is reported unasked with "
              "its basis, never skipped in silence: %r" % (res["unasked"],),
              res["misses"] == []
              and len(res["unasked"]) == 1
              and res["unasked"][0][0] == "phase P2"
              and "records no mergedHead" in res["unasked"][0][1])

        no_head_since = [dict(since[0], testedState={})]
        res = post([derived], rows=no_head_since)
        check("sm11 a bounding run that recorded NO head learns nothing and "
              "is reported unasked, naming the run: %r"
              % ((res["misses"], res["unasked"]),),
              res["misses"] == [] and len(res["unasked"]) == 1
              and res["unasked"][0][0] == "run R-since"
              and "records no testedState.head" in res["unasked"][0][1])

        backfilled = dict(derived, mergedHeadAt="2026-09-02T00:00:00Z")
        res = post([backfilled])
        before = post([dict(backfilled, mergedHead=first)])
        check("sm12 a BACKFILLED mergedHead (mergedHeadAt set) the bounding "
              "run does not contain cannot say whether the merge came before "
              "it, so it is unasked and never counted; the same backfill the "
              "bounding run DOES contain is settled, and stays quiet: %r"
              % ((res["unasked"], before["unasked"]),),
              res["misses"] == [] and len(res["unasked"]) == 1
              and "recorded after the fact" in res["unasked"][0][1]
              and before["unasked"] == [] and before["misses"] == [])

        # --- a runner's spelling is pinned to ONE tracked path first --------
        # The runner ran with `--root pkg1`, so it printed its failing suite
        # as `tests/x.test.js`; the derived gate listed the OTHER package's
        # suite, which a suffix reading also finds that spelling at the end
        # of. Both packages are tracked in `root`, so git's own listing is
        # what the post-pass pins against.
        sib_step = dict(_SM_STEP, failingSuites=["tests/x.test.js"])
        sib_phase = _sm_phase("P2", second, [_SM_SIBLING_B], ["src/a.ts"])
        sib = post([sib_phase], steps=[sib_step])
        sib_lines = M.selection_lines(sib, "R-1", second, "/plan/m.json",
                                      root)
        check("sm17 RED-FIRST: a runner spelling that two tracked sibling "
              "suites end in is NOT counted as listed because one of them "
              "was - it is asked of nothing, and the line says so naming "
              "both candidates: %r" % ((sib["misses"], sib_lines),),
              sib["misses"] == []
              and sib_lines == [
                  "SELECTION MISS not asked of tests/x.test.js: "
                  "tests/x.test.js names each of %s, %s - one name, several "
                  "suites, so it names none of them"
                  % (_SM_SIBLING_A, _SM_SIBLING_B)])

        # The same spelling where only pkg1 is tracked pins to pkg1: a real
        # miss, filed under the tracked path and never under the spelling.
        one_pkg = {"project": root, "listingFailed": None,
                   "tracked": [_SM_SUITE, _SM_SIBLING_A]}
        pinned = M._ev.selection_miss(
            [sib_step], [sib_phase], second, root, since, ["x"],
            listing=one_pkg)
        listed = M._ev.selection_miss(
            [sib_step], [_sm_phase("P2", second, [_SM_SIBLING_A],
                                   ["src/a.ts"])],
            second, root, since, ["x"], listing=one_pkg)
        check("sm18 a spelling that pins to one tracked suite is a miss under "
              "THAT path when the derived gate listed another package's, and "
              "no miss at all when it listed this one: %r"
              % ((pinned["misses"], pinned["unasked"], listed["misses"],
                  listed["unasked"]),),
              [m["test"] for m in pinned["misses"]] == [_SM_SIBLING_A]
              and pinned["unasked"] == []
              and listed["misses"] == [] and listed["unasked"] == [])

        # --- a ledger read with losses bounds nothing -----------------------
        lost = post([derived], rows=since)
        lost_now = M._ev.selection_miss(
            [_SM_STEP], [derived], second, root, since, ["x"],
            unreadable=["docs/audit/evidence/2026-09.ci-1.jsonl"])
        check("sm19 RED-FIRST: when a ledger file could not be read in full, "
              "no miss is asked and the reason names the file - the newest "
              "measured run may be on the lost line; the same ledger read "
              "whole still finds the miss: %r"
              % ((lost_now["misses"], lost_now["reasons"],
                  [m["test"] for m in lost["misses"]]),),
              lost_now["misses"] == [] and lost_now["since"] is None
              and len(lost_now["reasons"]) == 1
              and "docs/audit/evidence/2026-09.ci-1.jsonl"
              in lost_now["reasons"][0]
              and [m["test"] for m in lost["misses"]] == [_SM_SUITE])
    finally:
        _harness.remove_tree(root)

    # --- a phase --json run whose gate output names a path ------------------
    # `files_named` answers with a set; a step that carried it raw made every
    # `--json` dump raise before printing anything.
    fx = _sm_fixture()
    try:
        with open(fx["mpath"]) as fh:
            plan = json.load(fh)
        plan["phases"][0]["testGate"] = ["e2e"]
        with open(fx["mpath"], "w") as fh:
            json.dump(plan, fh)
        with open(fx["mode"], "w") as fh:
            fh.write("green")
        jlines = []
        try:
            code = M.main([fx["mpath"], "P1", "--project-dir", fx["root"],
                           "--json"], out=jlines.append)
            raised = None
        except TypeError as exc:
            code, raised = None, str(exc)
        blobs = [ln for ln in jlines if ln.startswith("{")]
        try:
            payload = json.loads(blobs[0]) if len(blobs) == 1 else {}
        except ValueError:
            payload = {}
        named = [st.get("named") for st in payload.get("steps") or []]
        check("sm15 RED-FIRST: `<manifest> <phase> --json` over a gate whose "
              "output names a path exits normally with valid JSON, the step's "
              "`named` a sorted list rather than a set JSON cannot spell: %r"
              % ((code, raised, named),),
              raised is None and code == M.E_OK
              and named == [["e2e/cart.spec.ts"]])
    finally:
        _sm_remove(fx)

    # --- the printed remedy: bounded, and explanation before the command ---
    many = ["src/f%d.ts" % i for i in range(M._ev.MAX_PATHS + 3)]
    wide = M._miss_remedy({"test": "e2e/cart.spec.ts", "phases": ["P2"],
                           "sources": many}, "R-1", "abc1234",
                          "/plan/docs/audit/audit-plan.json", "/plan")
    check("sm13 --sources past MAX_PATHS is never printed: the remedy points "
          "at the row and the plan instead, and what it does print parses: "
          "%r" % (wide,),
          "--sources" not in wide and "sourcesDropped" in wide
          and [v for v, a in _sm_parses(_sm_commands("x " + wide))
               if a is not None] == ["bug-add"])
    bare = M._miss_remedy({"test": "e2e/cart.spec.ts", "phases": ["P2"],
                           "sources": []}, "R-1", "abc1234",
                          "/plan/docs/audit/audit-plan.json", "/plan")
    check("sm14 a remedy with no couple puts its explanation BEFORE the "
          "colon, so everything after it is a command that parses: %r"
          % (bare,),
          bare.startswith("remedy (no couple: ")
          and [v for v, a in _sm_parses(_sm_commands("x " + bare))
               if a is not None] == ["bug-add"])


def _cli(argv):
    """`(exit, stdout)` of this command run as the main loop runs it: a process,
    with the session's own variables dropped."""
    env = dict((k, v) for k, v in os.environ.items()
               if not k.startswith("CLAUDE") and k != "AUDIT_LOCK_TOKENS")
    done = subprocess.run(
        [sys.executable, _loader.script_path("run-test-gate.py")] + argv,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, encoding="utf-8")
    return done.returncode, done.stdout


def _success_line_cases(check):
    """A green gate, said in one line naming the verdict and the row it
    recorded; a red one, a refusal and `--verbose`, in full."""
    def project(name, command):
        root = _mini_repo("run-test-gate-sl-%s-" % (name,))
        mp = os.path.join(root, "audit-plan.json")
        with open(mp, "w") as fh:
            json.dump({"meta": {"version": 2,
                                "buildCommands": {"test": command}},
                       "phases": [{"id": "P1", "title": "p",
                                   "status": "in_progress",
                                   "testGate": ["test"],
                                   "tasks": [{"id": "P1.1", "title": "t",
                                              "status": "in_progress",
                                              "files": ["a.txt"],
                                              "tests": {"gate": ["test"]}}]}]},
                      fh)
        return root, mp

    def pointer(mp):
        task = json.load(open(mp))["phases"][0]["tasks"][0]
        return (task.get("testEvidence") or {}).get("runId")

    root, mp = project("green", "true")
    code, short = _cli([mp, "P1", "--task", "P1.1", "--project-dir", root,
                        "--record"])
    lines = short.splitlines()
    run_id = pointer(mp)
    check("sl1 a green gate prints ONE line within the byte bound, naming the "
          "verdict and the evidence row it recorded - the id the plan's "
          "pointer now holds: %r" % (short,),
          code == M.E_OK and len(lines) == 1
          and len(lines[0].encode("utf-8")) <= 200
          and lines[0].startswith("[run-test-gate] GATE GREEN")
          and run_id and ("evidence: recorded %s" % (run_id,)) in lines[0])
    vroot, vmp = project("verbose", "true")
    vcode, verbose = _cli([vmp, "P1", "--task", "P1.1", "--project-dir", vroot,
                           "--record", "--verbose"])
    check("sl2 ...and `--verbose` prints the text the gate always printed: the "
          "evidence block, the per-step inventory, the verdict: %r"
          % (verbose[:200],),
          vcode == M.E_OK and len(verbose.splitlines()) > 3
          and "  evidence: recorded %s" % (pointer(vmp),) in verbose.splitlines()
          and any(ln.startswith("GATE GREEN") for ln in verbose.splitlines()))
    rroot, rmp = project("red", "false")
    rcode, red = _cli([rmp, "P1", "--task", "P1.1", "--project-dir", rroot,
                       "--record"])
    check("sl3 a RED gate prints in full - the deny twin of sl1: %r"
          % (red[-200:],),
          rcode != M.E_OK and len(red.splitlines()) > 3
          and any(ln.startswith("GATE RED") for ln in red.splitlines()))
    green = ["  evidence: recorded R-1", "  machine:  this run had the machine "
             "to itself", "  pointer:  P1.1 now names it", "GATE GREEN: test, "
             "tree unchanged"]
    crowded = list(green)
    crowded[1] = ("  machine:  1 other gate run(s) shared this window (R-0). A "
                  "full suite measured beside another is not this run's alone")
    check("sl5 a green that did NOT have the host to itself is told in full - "
          "the `machine:` line is read beside the verdict - while the same "
          "green alone on the host is one line: %r"
          % ((M.success_line(green), M.success_line(crowded)),),
          M.success_line(crowded) is None
          and M.success_line(green).startswith("[run-test-gate] GATE GREEN")
          and "evidence: recorded R-1" in M.success_line(green))
    refused = _cli([mp, "P1", "--task", "P1.1", "--project-dir", root,
                    "--own", "--record"])
    check("sl4 a refusal is what it always was, `--verbose` or not: %r"
          % (refused,),
          refused[0] != M.E_OK and "refuses --record" in refused[1]
          and refused == _cli([mp, "P1", "--task", "P1.1", "--project-dir",
                               root, "--own", "--record", "--verbose"]))


def _selftest():
    def body(check):
        _cases(check)
        _harness.stage(check, "sl-block", _success_line_cases)
        _group_cases(check)
        _crowd_cases(check)
        _full_scope_cases(check)
        _layout_project_cases(check)
        _selection_miss_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_run_test_gate.py --selftest\n")
    raise SystemExit(2)
