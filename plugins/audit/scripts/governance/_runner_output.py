#!/usr/bin/env python3
"""
Every reading of what a test runner printed: its summary line, and the lines
that name a failing check.

WHY A MODULE. `run-test-gate.py` wrote these readers to answer how many checks
ran and which of them failed. `stamp-verification.py red` asks the same output
the same questions about a run in a throwaway tree, and an entry point may not
import another, so the readers moved here, where both can reach them, rather than
being written a second time - two spellings of one runner's summary drift the
first time either learns a new reporter. It reaches nothing but `_output`, which
is what puts it at layer 1.

WHAT STAYED BEHIND. `failing_suites` and its path filters read `_evidence_io`'s
limits, and that module sits above layer 1, so they are still the gate's.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import os
import re
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

# --- how much did it do -------------------------------------------------------
# MATCHED ON THE OUTPUT, NOT ON THE COMMAND, which is the half
# `run-test-gate`'s `_STEP_WORDS` cannot do: a gate entry is as often
# `npm test`, `yarn test` or `make check` as it is the runner's own name, and
# the summary line is the runner's signature either way.
#
# THE WORDS ARE THE ONES THAT MEAN A CHECK EXECUTED, and `skipped`, `pending`,
# `todo`, `deselected` and `total` are deliberately absent from every row. A
# skipped check is the exact thing `NO CHECK RAN` exists to catch, so counting
# jest's own `N total` -- which includes them -- would re-open the "gate that did
# nothing" failure mode one runner along. `error` is out for the same reason from the
# other end: a pytest collection error is a test that never started.
_SUMMARY_PAIR = re.compile(r"(\d+) ([a-z]+)")
# One terminal control sequence of any kind - a colour, and also the cursor
# moves a live reporter prints before it rewrites a line. `_ANSI` further down
# is the narrower colour-only reading jest's header needs.
_CSI_TEXT = "\x1b\\[[0-9;]*[A-Za-z]"
# The phrasing both vitest and pytest use for "there were none", which carries no
# `N word` pair at all and would otherwise read as a runner this cannot count.
_NO_TESTS = re.compile(r"\bno tests\b")
_SUMMARY_READERS = (
    # jest:   `Tests:       1 failed, 2 skipped, 3 passed, 6 total`
    ("jest", re.compile(r"^[ \t]*Tests:[ \t]+(.*)$", re.M), ("passed", "failed")),
    # vitest: `Tests  1 failed | 4 passed (5)`, `Tests  no tests`. No colon, which
    # is what keeps this off jest's line, and `Test Files` is a different word.
    ("vitest", re.compile(r"^[ \t]*Tests[ \t]+(.*)$", re.M), ("passed", "failed")),
    # mocha:  `  5 passing (23ms)` and `  1 failing` on SEPARATE lines, which is
    # why every match is joined before the pairs are read out of it.
    ("mocha", re.compile(r"^[ \t]*(\d+ (?:passing|failing|pending).*)$", re.M),
     ("passing", "failing")),
    # pytest: `=== 3 passed in 0.12s ===`, and bare under `-q`. `no tests ran` and
    # `1 error` are both real summaries reporting zero, so both must MATCH here
    # and count nothing, rather than falling through as "not knowable".
    ("pytest",
     re.compile(r"^[=\s]*((?:no tests ran|\d+ \w+(?:, \d+ \w+)*)"
                r" in [\d.]+m?s.*)$", re.M),
     ("passed", "failed", "xpassed", "xfailed")),
    # playwright: `  1 failed`, `  1 flaky` and `  1 passed (590ms)`, each ALONE
    # on its line and the last with its duration. The line reporter prints
    # cursor escapes in front of the block, which is why any may lead. `flaky`
    # counts as ran: the test executed, failed once and passed on its retry.
    # LAST, because a bare count line is the loosest shape in this table and
    # every runner above has a signature of its own to be recognised by first.
    ("playwright",
     re.compile("^(?:" + _CSI_TEXT + ")*[ \t]*(\\d+ (?:passed|failed|"
                "flaky|skipped|interrupted|did not run))(?: \\([^)]*\\))?"
                "[ \t]*$", re.M),
     ("passed", "failed", "flaky")),
)



def summary_reader(text):
    """`(name, joined, words)` of the reader whose summary this output carries.

    `(None, "", ())` FOR A RUNNER NONE OF THEM RECOGNISES, which is the same
    answer `summary_count` has always returned as `None` - this is that decision
    lifted out of it, unchanged, so that "which runner is this" is asked once and
    answered in one place. It was already asked twice the moment a second reader
    wanted the names of the checks that failed, and two spellings of one
    recognition rule drift the first time either table grows a row.
    """
    matched = summary_readers(text)
    return matched[0] if matched else (None, "", ())


def summary_readers(text):
    """Every `(name, joined, words)` whose summary this output carries, in
    table order. `summary_reader` takes the first; a caller that must know
    the output is ONE runner's asks whether there is more than one."""
    out = []
    for name, line_re, words in _SUMMARY_READERS:
        found = line_re.findall(text or "")
        if not found:
            continue
        joined = " ".join(found)
        if _SUMMARY_PAIR.findall(joined) or _NO_TESTS.search(joined):
            out.append((name, joined, words))
    return out


def summary_count(text):
    """How many checks a runner's own SUMMARY line says executed, or None.

    Derived from the runner's arithmetic and never from this reader's: counting
    output lines would go wrong the first time a suite name wrapped or a reporter
    was configured, and re-adding jest's categories to check its `total` would
    disagree with jest the first time it grew one.

    None IS STILL THE ANSWER FOR A RUNNER WITH NO SUMMARY HERE, and that is the
    rule this widening had to keep rather than the rule it replaces. A reader
    that returned 0 for "I did not recognise this output" would refuse every
    passing gate whose runner is not in the table above.
    """
    name, joined, words = summary_reader(text)
    if name is None:
        return None
    return sum(int(n) for n, word in _SUMMARY_PAIR.findall(joined)
               if word in words)


# --- which checks failed ------------------------------------------------------
# ONE ROW PER RUNNER `_SUMMARY_READERS` ALREADY COUNTS, AND NO OTHER. A parser
# for a runner whose summary this module cannot read would be naming failures
# beside a check count that says "not knowable from this runner" - a claim with
# no measurement under it, which is the shape the gate exists to refuse. The
# case that reads the two tables against each other is in this module's suite
# and in the gate's, so a reader added to one and not the other fails rather
# than silently falling through to a tail.
#
# MATCHED ON THE OUTPUT, NOT ON THE COMMAND, for the reason `_SUMMARY_READERS`
# states: a gate entry is as often `npm test` or `make check` as it is the
# runner's own name, and the failure lines are the runner's signature either way.
_FAILURE_READERS = {
    # jest heads each failure block with a bullet. `Console` is a console dump
    # under the same bullet and not a failing check; `Test suite failed to run`
    # is one and is deliberately kept.
    "jest": re.compile("^[ \t]*●[ \t]+(?!Console[ \t]*$)(.+?)[ \t]*$",
                       re.M),
    # vitest marks a failure beside a cross in the file tree and again as
    # `FAIL  <file> > <suite> > <name>` under `Failed Tests`. Both are read
    # because which of them a reporter prints depends on how it was configured;
    # the two spell the test differently, so this collapses only EXACT repeats
    # and a run printing both carries both spellings of the same failure.
    "vitest": re.compile("^[ \t]*(?:×|FAIL)[ \t]+(.+?)[ \t]*$", re.M),
    # mocha NUMBERS its failures, and the number is the only mark on the line.
    "mocha": re.compile(r"^[ \t]*\d+\)[ \t]*(.+?)[ \t]*$", re.M),
    # pytest's short summary. `ERROR` is here and is NOT the same claim as
    # `error` being absent from the counting words above: a collection error is
    # not a check that ran, and it is still the thing the operator has to fix.
    "pytest": re.compile(r"^(?:FAILED|ERROR)[ \t]+(.+?)[ \t]*$", re.M),
    # playwright lists each test under the count that names its fate - `N
    # failed`, `N flaky` - as `<file>:<line>:<col> › <title>` (behind
    # `[<project>] › ` when projects are configured) and a rule of box-drawing
    # dashes. This is the ENTRY line; which block it sits under is
    # `playwright_listed`'s question, because a flaky test and a failed one are
    # spelled identically and only the heading above tells them apart.
    "playwright": re.compile(
        "^[ \t]+((?:\\[[^\\]]+\\] › )?\\S+:\\d+:\\d+ › .+?)(?:[ \t]+─+)?[ \t]*$"),
}


# jest's heading for a suite that never ran a test (`jest-message-util`'s
# `EXEC_ERROR_MESSAGE`). The heading alone names neither the suite nor the
# cause, and both sit on lines of their own: the suite on the `FAIL <path>`
# header above it, the cause on the first line under it.
JEST_EXEC_ERROR = "Test suite failed to run"
# The header jest prints per suite. Colour, where a caller forces it through a
# pipe, wraps both the word and the path's two halves in escapes, which is why
# the text is stripped of them before this reads it.
_JEST_SUITE_HEADER = re.compile(r"^[ \t]*(?:PASS|FAIL)[ \t]+(\S+)")
_ANSI = re.compile("\x1b\\[[0-9;]*m")


def jest_failures(text):
    """`[(title, suite, reason)]` - each jest failure bullet, in output order.

    `suite` is the path on the nearest `PASS`/`FAIL` header above the bullet,
    or None when none was printed. `reason` is read for a failed-to-run
    heading only - the first non-blank line under it - and is None for an
    ordinary assertion bullet, whose title already names the check.
    """
    lines = _ANSI.sub("", text or "").splitlines()
    out, suite = [], None
    for i, line in enumerate(lines):
        header = _JEST_SUITE_HEADER.match(line)
        if header:
            suite = header.group(1)
            continue
        bullet = _FAILURE_READERS["jest"].match(line)
        if not bullet:
            continue
        title = bullet.group(1)
        reason = None
        if title == JEST_EXEC_ERROR:
            reason = next((ln.strip() for ln in lines[i + 1:] if ln.strip()),
                          None)
        out.append((title, suite, reason))
    return out


# vitest's own `FAIL  <file> > <suite> > <name>` line under `Failed Tests`. The
# cross beside it in the file tree (`× <file> > <name>`) carries no `FAIL` word
# at all and is deliberately NOT read here - the gate's `failing_lines` reads
# both because either spelling names a failing CHECK, but only this one names a
# FILE.
_VITEST_FAIL_LINE = re.compile(r"^[ \t]*FAIL[ \t]+(\S+)", re.M)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        print("_runner_output.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__runner_output.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
