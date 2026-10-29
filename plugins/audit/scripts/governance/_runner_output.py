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
is what puts it at the bottom of the graph.

WHAT STAYED BEHIND. `failing_suites` and its path filters read `_evidence_io`'s
limits, and that module sits above this one, so they are still the gate's.

AND WHAT `red` READS. `red` asks a narrower question than the gate - did a NAMED
case fail an ASSERTION - so its tally and case readers (`TALLY_READERS`,
`CASE_READERS`, `read_tally`, `failing_cases`) are a section of their own. The
house harness, pytest and unittest have readers of their own in that section,
and pytest's is not the summary row the gate counts by; jest and vitest are
read through this module's own summary and failure readers, each case carrying
the per-case `assertion` flag. Mocha and playwright have no
row there: what each prints under a failure has not been recorded, so which
of their failures is an assertion cannot be read. Playwright's own reporters
and vitest's JSON one are read in the last section, `read_run_tally` and
`run_failing_cases` being the pair `red` calls.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
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
# is the narrower colour-only reading `run-test-gate` strips its own text with.
_CSI_TEXT = "\x1b\\[[0-9;]*[A-Za-z]"
_CSI = re.compile(_CSI_TEXT)


def plain_text(text):
    """`text` with every terminal control sequence removed and every line
    ending `\\n`, None read as "".

    A runner forced into colour through a pipe (FORCE_COLOR) wraps its summary
    words and its failure bullets in escapes, and a child on Windows ends its
    lines `\\r\\n` - kept as they came, since a run's bytes are decoded without
    universal newlines - so a pattern anchored `[ \\t]*$` under re.M stops at the
    `\\r` and matches nothing. Every reader below is written against plain,
    `\\n`-ended text, so every reader taking a run's text - the public tally,
    case, summary and sweep readers, and the per-runner readers of
    `CASE_READERS` and `TALLY_READERS` behind them - reads it through here,
    `\\r\\n` and a lone `\\r` both read as `\\n`. It is idempotent, so a reader
    handing its text on to another reader reads the same answer. `ru17` in
    tests/test__runner_output.py runs every public reader over each fixture's
    CRLF and lone-CR twin, and `rx1` every per-runner reader over those twins
    and a colour-escaped one."""
    return _CSI.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")
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
    the output is ONE runner's asks whether there is more than one. Read
    through `plain_text`, as every reader taking a run's text is."""
    text = plain_text(text)
    out = []
    for name, line_re, words in _SUMMARY_READERS:
        found = line_re.findall(text)
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
    # MULTILINE, so `^`/`$` anchor each line of a whole run's text and not only
    # its first and last; run-test-gate's per-line `.match` is unaffected.
    "playwright": re.compile(
        r"^[ \t]+((?:\[[^\]]+\][ \t]*›[ \t]*)?\S+:\d+:\d+[ \t]*›[ \t]*.+?)"
        r"(?:[ \t]+─+)?[ \t]*$", re.M),
}


# jest's heading for a suite that never ran a test (`jest-message-util`'s
# `EXEC_ERROR_MESSAGE`). The heading alone names neither the suite nor the
# cause, and both sit on lines of their own: the suite on the `FAIL <path>`
# header above it, the cause on the first line under it.
JEST_EXEC_ERROR = "Test suite failed to run"
# The header jest prints per suite. Colour, where a caller forces it through a
# pipe, wraps both the word and the path's two halves in escapes, which is why
# the text is stripped of them (`plain_text`) before this reads it.
_JEST_SUITE_HEADER = re.compile(r"^[ \t]*(?:PASS|FAIL)[ \t]+(\S+)")
_ANSI = re.compile("\x1b\\[[0-9;]*m")


def jest_failures(text):
    """`[(title, suite, reason)]` - each jest failure bullet, in output order.

    `suite` is the path on the nearest `PASS`/`FAIL` header above the bullet,
    or None when none was printed. `reason` is read for a failed-to-run
    heading only - the first non-blank line under it - and is None for an
    ordinary assertion bullet, whose title already names the check.
    """
    return [(title, suite, first if title == JEST_EXEC_ERROR else None)
            for title, suite, first in _jest_blocks(plain_text(text))]


def _jest_blocks(text):
    """`[(title, suite, first)]` - each jest failure bullet, the path on the
    nearest `PASS`/`FAIL` header above it (None when none was printed), and
    the first non-blank line under it, stripped. `text` is already plain."""
    lines = text.splitlines()
    out, suite = [], None
    for i, line in enumerate(lines):
        header = _JEST_SUITE_HEADER.match(line)
        if header:
            suite = header.group(1)
            continue
        bullet = _FAILURE_READERS["jest"].match(line)
        if bullet:
            out.append((bullet.group(1), suite, _first_below(lines, i)))
    return out


# vitest's own `FAIL  <file> > <suite> > <name>` line under `Failed Tests`. The
# cross beside it in the file tree (`× <file> > <name>`) carries no `FAIL` word
# at all and is deliberately NOT read here - the gate's `failing_lines` reads
# both because either spelling names a failing CHECK, but only this one names a
# FILE.
_VITEST_FAIL_LINE = re.compile(r"^[ \t]*FAIL[ \t]+(\S+)", re.M)


# --- which files the selftest sweep failed ------------------------------------
# `tools/sweep-selftests.py` grades FILES, not checks: one `FAIL  <path>: <why>`
# line per red file - two spaces, which is how it is told from a house case's
# one-space `FAIL <id> <title>` - and one summary line,
# `<ok>/<files> files ok, <cases> cases`. The sweep used to count the files whose
# cases had moved to `tests/` in the middle of that line (`<n> migrated to tests/`);
# there is no such class now, but a ledger still holds runs that printed it, so the
# clause is optional on read. It is not in
# `_SUMMARY_READERS`: its `cases` total is the house suites' own claims added
# up, not a count of checks this module watched execute. The directory's slash
# is optional because the ledger's copies of the line carry none.
SWEEP_RUNNER = "the sweep"
_SWEEP_SUMMARY = re.compile(
    r"^(\d+)/(\d+) files ok,(?: (\d+) migrated to tests/?,)? (\d+) cases[ \t]*$",
    re.M)
_SWEEP_FAIL = re.compile(r"^FAIL  (\S(?:.*?\S)?): (\S.*?)[ \t]*$", re.M)


def sweep_summary(text):
    """`{"ok", "files", "migrated", "cases"}` off the sweep's LAST summary line,
    or None when the output carries none - one run prints one, and a log holding
    several is read for the run that ended it. `migrated` is 0 for a line that
    names no such clause, which is every line the sweep prints now."""
    found = _SWEEP_SUMMARY.findall(plain_text(text))
    if not found:
        return None
    ok, files, migrated, cases = found[-1]
    clause = int(migrated) if migrated else 0
    return {"ok": int(ok), "files": int(files), "migrated": clause,
            "cases": int(cases)}


def sweep_failures(text):
    """`[(path, why), ...]` - every file the sweep printed a `FAIL` line for,
    in printed order, or None when that is not knowable from `text`.

    None, NEVER A PARTIAL LIST, for output with no sweep summary (it is not the
    sweep's) and for FAIL lines that do not account for every file the summary
    says failed - a cut tail, or lines this reader cannot see - because a list
    one file short would charge that file to nobody. `[]` is the sweep's own
    word that every file it graded was ok.
    """
    body = plain_text(text)
    summary = sweep_summary(body)
    if summary is None:
        return None
    named = []
    for path, why in _SWEEP_FAIL.findall(body):
        if (path, why) not in named:
            named.append((path, why))
    if len(named) != summary["files"] - summary["ok"]:
        return None
    return named


def sweep_tally(text):
    """The tally of a sweep that graded every file it ran ok, else None.

    A green file is printed by the sweep as one line and its own output is
    dropped, so a passing sweep carries no tally of any runner - only its
    summary. That summary is read here, for a run that swept at least one file
    and counted at least one case: `0/0 files ok` is a sweep that ran nothing,
    which is not a pass. A sweep with a red file has no tally here on purpose -
    the failing file's own output is printed whole and is read as its own
    runner's, which is what names the case that failed."""
    summary = sweep_summary(text)
    if summary is None or not summary["files"] or not summary["cases"] \
            or summary["ok"] != summary["files"]:
        return None
    return {"runner": SWEEP_RUNNER, "collected": summary["cases"], "failed": 0,
            "assertions": 0, "files": summary["files"]}


# A red file's output is printed whole under `--- <path>: <why> ---`; which file a
# `FAIL <label>` line belongs to is the header above it, and nothing else in the
# output says.
_SWEEP_BLOCK = re.compile(r"^--- (\S(?:.*?\S)?): (\S.*?) ---[ \t]*$", re.M)


def sweep_failing_cases(text):
    """`[{"id", "label", "assertion", "why", "script"}]` - the house cases the
    sweep's red files printed, each carrying the `script` (the path the sweep
    printed) whose block it was read from; None for output with no sweep summary.

    A house run located its cases in the one script its command ran, and a
    sweep-shaped command runs the sweep, not the suite: the file a case belongs
    to has to be read off the block that printed it."""
    body = plain_text(text)
    if sweep_summary(body) is None:
        return None
    heads = list(_SWEEP_BLOCK.finditer(body))
    out = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out.extend(dict(case, script=head.group(1))
                   for case in _house_cases(body[head.end():end]))
    return out


# --- which case failed an assertion: the tally and cases `red` reads -------
# `red` needs a COUNT and a NAME: at least one test collected, and at least one
# named case failing an ASSERTION. A non-zero exit alone is not that - a compile
# error, an import error and a runner that collected nothing all exit non-zero
# with no assertion ever evaluated - and neither is an exception raised in a test
# body, which pytest counts as `failed` and unittest as an error. A runner whose
# tally this does not read is `no-tally` and never promoted to `red`.
#
# The house harness marks a block that raised while being BUILT with one of
# these labels, and a duplicated case id with the third; none of them is an
# assertion about the code.
HOUSE_ESCAPES = ("RAISED WHILE ITS CASES WERE BEING BUILT",
                 "selftest body raised before reaching the end",
                 "DUPLICATE CASE ID")
_HOUSE_TALLY = re.compile(r"^(?:ALL PASS|SELFTEST FAILED): (\d+)/(\d+) "
                          + "cases " + "passed", re.M)
# pytest frames its summary with `=` by default and prints it bare under -q.
_PYTEST_SUMMARY = re.compile(
    r"^(?:=+ )?((?:\d+ (?:failed|passed|errors?|skipped|xfailed|xpassed|"
    r"warnings?|deselected)(?:, )?)+|no tests ran) in [\d.]+s\b.*$", re.M)
_PYTEST_COUNT = re.compile(r"(\d+) (failed|passed|errors?|skipped|xfailed|xpassed)")
_PYTEST_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.M)
_UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
_UNITTEST_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
# The location is read off the SAME line as the case: two cases of one name in
# two modules - HEAD's imported class and a subclass inheriting from it - each
# keep their own.
_UNITTEST_CASE = re.compile(r"^(FAIL|ERROR): (\S+)(?: \(([\w.]+)\))?", re.M)
# A house case's id is its label's leading token when that token carries a digit
# (`me1`, `ga9b`, `pc-sd0`) - the key the harness's `case_id()` hands out and
# prove-gates attributes a mutation by. A label led by an ordinary word has no id
# and is named by the whole label: its first word is one some case HEAD's run
# prints almost always opens with too, so reading it as an id refuses the task's
# own case.
_HOUSE_CASE_ID = re.compile(r"^[A-Za-z][A-Za-z_-]*[0-9][A-Za-z0-9_-]*$")


def house_case_id(label):
    """The label's leading token when it is id-shaped, else None."""
    head = label.split(None, 1)
    if not head or not _HOUSE_CASE_ID.match(head[0]):
        return None
    return head[0]


def printed_labels(text, cmd=None):
    """The labels a house run printed, one per `PASS <label>` or `FAIL <label>`
    line, or None when the run is not a house one - jest, pytest and unittest
    print no label for a passing case, so for them the answer is "unknown",
    never an empty list a binding would be graded against."""
    text = plain_text(text)
    tally = read_tally(text, cmd)
    if tally is None or tally["runner"] != "house":
        return None
    return [ln.split(" ", 1)[1].strip() for ln in text.splitlines()
            if (ln.startswith("PASS ") or ln.startswith("FAIL "))
            and ln.split(" ", 1)[1].strip()]


def _house_cases(text):
    text = plain_text(text)
    out = []
    for ln in text.splitlines():
        # Two spaces after FAIL is the sweep's own per-file line, not a case.
        if ln.startswith("FAIL ") and not ln.startswith("FAIL  ") \
                and not any(m in ln for m in HOUSE_ESCAPES):
            label = ln[len("FAIL "):].strip()
            out.append({"id": house_case_id(label), "label": label,
                        "assertion": True, "why": "house FAIL"})
    return out


def _pytest_cases(text):
    text = plain_text(text)
    out = []
    for kind, node, why in _PYTEST_FAILED.findall(text):
        why = (why or "").strip()
        out.append({"id": node.split("::")[-1], "label": node,
                    "assertion": kind == "FAILED"
                    and (why.startswith("assert") or why.startswith("AssertionError")),
                    "why": why or kind})
    return out


def _unittest_site(name, where):
    """`(module, class, qual)` a unittest line locates a case in: `where` is
    `mod.Class` or, from 3.11, `mod.Class.test`, the class part a qualified
    name when classes nest (`mod.Outer.Inner`). `qual` is that dotted path
    whole, split, since only the declared files can say where the module ends
    and the class chain begins; `module` and `class` read it as one class
    deep. Nones when the line gives no location."""
    parts = where.split(".") if where else []
    if parts and parts[-1] == name:
        parts = parts[:-1]
    if len(parts) < 2:
        return None, None, []
    return ".".join(parts[:-1]), parts[-1], parts


def _unittest_cases(text):
    text = plain_text(text)
    out = []
    for kind, name, where in _UNITTEST_CASE.findall(text):
        module, cls, qual = _unittest_site(name, where)
        out.append({"id": name, "label": name, "assertion": kind == "FAIL",
                    "why": kind, "module": module, "cls": cls, "qual": qual})
    return out


# jest and vitest name a case by the suite path their `FAIL` header or line
# prints and its title chain - the `describe` titles and the test's own. Each
# case carries both, as `suite` and `chain`, and `id` is the test's own title.
# A suite that never ran a test is named with an EMPTY chain and no id: the tally
# counts it as a failure no case ran, and it never sets the assertion flag.
#
# The first line under a jest bullet says what failed: a matcher hint
# (`expect(received).toBe(expected)`) for an `expect`, a hint naming the call
# (`assert(received)`, `assert.equal(received, expected)`,
# `assert.throws(function)`) for `node:assert`, and the exception itself
# (`TypeError: boom`) for a body that threw - which is the one of the three
# that is not an assertion. jest prints no `AssertionError` line for a
# `node:assert` failure; it formats one as it formats a matcher.
_JEST_ASSERTION = re.compile(r"^(?:expect[.(]|assert(?:\.\w+)?\()")
_JEST_CHAIN = " › "
# vitest prints chai's `AssertionError` for an `expect` failure and for
# `node:assert` alike, on the line under the case's `FAIL`, and the exception
# for a throw. Its `FAIL  <file> > <suite> > <name>` lines sit under `Failed
# Tests`; a `FAIL  <file> [ <file> ]` line under `Failed Suites` carries no
# chain and is a file whose suite never ran a test.
_VITEST_ASSERTION = re.compile(r"^AssertionError\b")
_VITEST_CHAIN = " > "
_VITEST_CASE_LINE = re.compile(r"^[ \t]*FAIL[ \t]+(\S+)(.*?)[ \t]*$")


def _first_below(lines, i):
    """The first non-blank line after `lines[i]`, stripped, or None."""
    return next((ln.strip() for ln in lines[i + 1:] if ln.strip()), None)


def _suite_failure(suite, why):
    return {"id": None, "label": suite, "assertion": False, "why": why,
            "suite": suite, "chain": []}


def _jest_cases(text):
    text = plain_text(text)
    # Exact repeats collapse: with more than one suite, jest prints every
    # failure again under `Summary of all failing tests`, and the same bullet
    # read twice is one case, not two.
    out = []
    for title, suite, first in _jest_blocks(text):
        if title == JEST_EXEC_ERROR:
            case = _suite_failure(suite, first or title)
            case["label"] = title
        else:
            chain = title.split(_JEST_CHAIN)
            case = {"id": chain[-1], "label": title,
                    "assertion": bool(_JEST_ASSERTION.match(first or "")),
                    "why": first or "jest bullet", "suite": suite, "chain": chain}
        if case not in out:
            out.append(case)
    return out


def _vitest_cases(text):
    text = plain_text(text)
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        hit = _VITEST_CASE_LINE.match(line)
        if not hit:
            continue
        suite, rest, first = hit.group(1), hit.group(2), _first_below(lines, i)
        if not rest.startswith(_VITEST_CHAIN):
            case = _suite_failure(suite, first or "vitest FAIL")
        else:
            chain = rest[len(_VITEST_CHAIN):].split(_VITEST_CHAIN)
            case = {"id": chain[-1], "label": _VITEST_CHAIN.join(chain),
                    "assertion": bool(_VITEST_ASSERTION.match(first or "")),
                    "why": first or "vitest FAIL", "suite": suite, "chain": chain}
        if case not in out:
            out.append(case)
    return out


CASE_READERS = {"house": _house_cases, "pytest": _pytest_cases,
                "unittest": _unittest_cases, "jest": _jest_cases,
                "vitest": _vitest_cases}


def failing_cases(text, runner=None):
    """`[{"id", "label", "assertion", "why"}]` - every failing case the runner
    that ran named; `runner` defaults to the one `read_tally()` selects.

    Only that runner's lines are read, never another's whose tally line merely
    appears in the output: a passing house case may print
    `ERROR: <path> is not a directory` because it asserts on that message, or
    echo a whole captured unittest transcript, `Ran N tests` line included; a
    test under another runner may print a line that opens with `FAIL `. No
    tally, no runner, no cases. `label` is the whole name as printed; `id` is
    the part a case is keyed by, None for a house label with no id-shaped lead.

    `assertion` is True only where the runner says the case failed an assertion:
    a house `FAIL` line that is not an escape, a pytest `FAILED` whose reason is
    an `assert` or an `AssertionError`, a unittest `FAIL:`, a jest bullet whose
    first line is a matcher hint or a `node:assert` hint, a vitest `FAIL` line
    whose next line is an `AssertionError`. A pytest `ERROR`, a pytest body
    exception, a unittest `ERROR:`, a jest or vitest body that threw and a jest
    or vitest suite that failed to run are named with it False."""
    text = plain_text(text)
    if runner is None:
        tally = read_tally(text)
        runner = tally["runner"] if tally is not None else None
    reader = CASE_READERS.get(runner)
    return reader(text) if reader is not None else []


def _house_tally(text):
    text = plain_text(text)
    hits = _HOUSE_TALLY.findall(text)
    if not hits:
        return None
    passed, total = int(hits[-1][0]), int(hits[-1][1])
    asserting = _house_cases(text)
    return {"runner": "house", "collected": total, "failed": total - passed,
            "assertions": len(asserting)}


def _pytest_tally(text):
    text = plain_text(text)
    hits = _PYTEST_SUMMARY.findall(text)
    if not hits:
        return None
    # Every summary line is counted, as unittest's `Ran N` lines are: a command
    # running two invocations prints two, and reading only the last would judge
    # the whole run by its second half.
    counts = {}
    for hit in hits:
        for n, kind in _PYTEST_COUNT.findall(hit):
            key = kind.rstrip("s") if kind.startswith("error") else kind
            counts[key] = counts.get(key, 0) + int(n)
    ran = sum(counts.get(k, 0) for k in ("failed", "passed", "xfailed", "xpassed"))
    asserting = [c for c in _pytest_cases(text) if c["assertion"]]
    return {"runner": "pytest", "collected": ran,
            "failed": counts.get("failed", 0) + counts.get("error", 0),
            "assertions": len(asserting)}


def _unittest_tally(text):
    text = plain_text(text)
    ran = _UNITTEST_RAN.findall(text)
    if not ran:
        return None
    counts = {}
    for hit in _UNITTEST_FAILED.findall(text):
        for part in hit.split(","):
            key, _sep, val = part.strip().partition("=")
            if val.isdigit():
                counts[key] = counts.get(key, 0) + int(val)
    failures = counts.get("failures", 0)
    # Every `Ran N` line is counted, as every FAILED line is: a command running
    # two suites prints two, and reading only the last would pair one run's
    # count with both runs' failures.
    return {"runner": "unittest", "collected": sum(int(n) for n in ran),
            "failed": failures + counts.get("errors", 0), "assertions": failures}


def _summary_tally(text, runner, cases):
    """A jest or vitest tally: the runner's own summary line read through
    `summary_readers` - only that runner's row, so another runner's summary in
    the same output is not summed into it - with each suite that never ran a
    test counted as a failure no case ran."""
    rows = [(joined, words) for name, joined, words in summary_readers(text)
            if name == runner]
    if not rows:
        return None
    joined, words = rows[0]
    counts = {}
    for n, word in _SUMMARY_PAIR.findall(joined):
        counts[word] = counts.get(word, 0) + int(n)
    crashed = len([c for c in cases if not c["chain"]])
    return {"runner": runner, "collected": sum(counts.get(w, 0) for w in words),
            "failed": counts.get("failed", 0) + crashed,
            "assertions": len([c for c in cases if c["assertion"]])}


def _jest_tally(text):
    text = plain_text(text)
    return _summary_tally(text, "jest", _jest_cases(text))


def _vitest_tally(text):
    text = plain_text(text)
    return _summary_tally(text, "vitest", _vitest_cases(text))


TALLY_READERS = (("house", _house_tally), ("pytest", _pytest_tally),
                 ("unittest", _unittest_tally), ("jest", _jest_tally),
                 ("vitest", _vitest_tally))


def command_runner(cmd):
    """The runner a test command names - `pytest`, `python -m unittest`, a house
    `--selftest`, `jest` or `vitest` as the program it runs - or None when it
    names none, or more than one. A wrapper (`npm test`, `npx vitest`) names
    none, and the output decides."""
    args = [str(a) for a in (cmd or ())]
    named = set()
    for i, arg in enumerate(args):
        base = os.path.basename(arg)
        follows_m = i > 0 and args[i - 1] == "-m"
        if base in ("pytest", "py.test"):
            named.add("pytest")
        elif i == 0 and base in ("jest", "vitest"):
            named.add(base)
        elif follows_m and arg == "unittest":
            named.add("unittest")
        elif arg == "--selftest":
            named.add("house")
    return named.pop() if len(named) == 1 else None


def read_tally(text, cmd=None):
    """The tally of the runner that ran, or None when no known runner printed one.

    One runner's tally is that runner's. When more than one appears - a house
    case echoing a captured unittest transcript, a unittest test printing a
    house tally - neither the order they were printed in nor a precedence
    between runners says which ran: a merged pipe puts a test's buffered
    stdout after the runner's own stderr. So the command decides when it names
    a runner (`command_runner`), and otherwise the answer is
    `{"runner": None, "mixed": [...]}`, which no reader reads cases from.
    The text is read without its terminal escapes (`plain_text`)."""
    text = plain_text(text)
    tallies = [t for t in (reader(text) for _name, reader in TALLY_READERS)
               if t is not None]
    if not tallies:
        return None
    if len(tallies) == 1:
        return tallies[0]
    named = [t for t in tallies if t["runner"] == command_runner(cmd)]
    if named:
        return named[0]
    return {"runner": None, "mixed": [t["runner"] for t in tallies],
            "collected": 0, "failed": 0, "assertions": 0}


# --- playwright's JSON and line reporters, vitest's JSON reporter -----------
# A Playwright run's own output carries no `Tests` line `read_tally` knows, and
# a vitest run under `--reporter=json` prints none of the one its vitest reader
# looks for: two reporters, not one runner, read here beside the line readers.
def _json_blob(text):
    """The LARGEST `{...}` document `text` parses whole as JSON, or None.

    A wrapper (`npm test`, a package script) prints banner lines before and
    after the reporter's own document, so every `{` is tried as a start and
    the biggest span that parses whole is kept - a small unrelated object (a
    lockfile notice, a config echo) printed beside the real one is not read
    as it."""
    text = text or ""
    decoder, idx, found = json.JSONDecoder(), 0, None
    while True:
        start = text.find("{", idx)
        if start == -1:
            return found[2] if found else None
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            idx = start + 1
            continue
        if found is None or (end - start) > (found[1] - found[0]):
            found = (start, end, obj)
        idx = end


def _pw_specs(suites, path=()):
    """`[(chain, file, test)]` - every test playwright's JSON reporter nests
    under `suites`, the chain its own title and every enclosing suite's,
    walked depth first the way the reporter nests them."""
    out = []
    for suite in suites or []:
        title = suite.get("title") or ""
        sub = path + ((title,) if title else ())
        for spec in suite.get("specs") or []:
            chain = sub + (spec.get("title") or "",)
            for test in spec.get("tests") or []:
                out.append((chain, spec.get("file"), test))
        out.extend(_pw_specs(suite.get("suites") or [], sub))
    return out


# An `expect()` or a `node:assert` failure prints `AssertionError`, or the
# matcher's own line, in its error's message; anything else - a timeout, a
# thrown value with no assertion in it - is read `assertion: False`.
_PW_ASSERTION = re.compile(r"\bexpect[.(]|AssertionError\b")


def _pw_error_text(test):
    results = test.get("results") or []
    if not results:
        return ""
    last = results[-1]
    errors = last.get("errors") or ([last["error"]] if last.get("error") else [])
    return "\n".join((e or {}).get("message") or "" for e in errors).strip()


def playwright_json_cases(obj):
    """`[{"id", "label", "assertion", "why", "suite", "chain"}]` from a
    playwright JSON reporter document (`--reporter=json`), or None when `obj`
    carries neither `suites` nor `stats` - the two keys the reporter always
    writes, a passing run included, so their absence means this is not one."""
    if not isinstance(obj, dict) or "stats" not in obj or "suites" not in obj:
        return None
    out = []
    for chain, file_rel, test in _pw_specs(obj.get("suites") or []):
        if test.get("status") != "unexpected":
            continue
        error = _pw_error_text(test)
        case = {"id": chain[-1] if chain else None, "label": " > ".join(chain),
                "assertion": bool(_PW_ASSERTION.search(error)),
                "why": error or "playwright: unexpected", "suite": file_rel,
                "chain": list(chain)}
        if case not in out:
            out.append(case)
    return out


def playwright_json_tally(obj):
    """The tally of a playwright JSON reporter document, or None (see
    `playwright_json_cases`). `collected` is every test that ran at least
    once - `expected`, `unexpected` and `flaky` are playwright's own words for
    that - `skipped` left out exactly as the summary table leaves it out for
    every other runner."""
    cases = playwright_json_cases(obj)
    if cases is None:
        return None
    stats = obj.get("stats") or {}
    collected = sum(int(stats.get(k) or 0) for k in ("expected", "unexpected", "flaky"))
    failed = int(stats.get("unexpected") or 0)
    return {"runner": "playwright", "collected": collected, "failed": failed,
            "assertions": len([c for c in cases if c["assertion"]])}


def playwright_line_cases(text):
    """`playwright_json_cases`'s shape, read off playwright's line/list
    reporter instead of its JSON one: each entry `_FAILURE_READERS["playwright"]`
    locates (`<file>:<line>:<col> › <chain>`, a project prefix allowed), its
    chain split on playwright's own `' › '`. That reporter prints no
    per-failure detail an assertion can be told from a timeout, a refused
    connection or a crash by, so every entry here is `assertion: None`:
    playwright decided the test failed, which proves a failure and no more.
    Only the JSON reporter names an assertion, so a proof that rests on one
    needs `--reporter=json`."""
    out = []
    for hit in _FAILURE_READERS["playwright"].finditer(plain_text(text)):
        entry = re.sub(r"^\[[^\]]+\][ \t]*›[ \t]*", "", hit.group(1))
        loc, sep, rest = entry.partition(" › ")
        if not sep:
            continue
        chain = [c.strip() for c in rest.split(" › ")]
        case = {"id": chain[-1] if chain else None, "label": entry,
                "assertion": None,
                "why": "playwright: failed (line reporter; --reporter=json "
                       "is needed to tell an assertion)",
                "suite": loc.split(":")[0], "chain": chain}
        if case not in out:
            out.append(case)
    return out


def playwright_line_tally(text):
    """The tally of playwright's line/list reporter, or None - `collected` and
    `failed` off its own summary line (`summary_readers`, already carrying a
    `playwright` row), `assertions` the entries `playwright_line_cases` marks
    as one - none, since that reporter cannot tell."""
    rows = [(joined, words) for name, joined, words in
            summary_readers(plain_text(text)) if name == "playwright"]
    if not rows:
        return None
    joined, words = rows[0]
    counts = {}
    for n, word in _SUMMARY_PAIR.findall(joined):
        counts[word] = counts.get(word, 0) + int(n)
    cases = playwright_line_cases(text)
    return {"runner": "playwright",
            "collected": sum(counts.get(w, 0) for w in words),
            "failed": counts.get("failed", 0) + counts.get("flaky", 0),
            "assertions": len([c for c in cases if c["assertion"]])}


def playwright_cases(text):
    """Every failing case a playwright run named: its JSON reporter first,
    its line/list reporter otherwise - the pair `playwright_json_tally` and
    `playwright_line_tally` read from the same text."""
    obj = _json_blob(text)
    cases = playwright_json_cases(obj) if obj is not None else None
    return cases if cases is not None else playwright_line_cases(text)


# vitest's `--reporter=json` writes jest's own schema (`testResults`, each
# holding `assertionResults`), so only that shape is walked.
_VITEST_JSON_ASSERTION = re.compile(r"^AssertionError\b", re.M)


def vitest_json_cases(obj):
    """`playwright_json_cases`'s shape, read off a vitest (or jest) JSON
    reporter document - `None` when `obj` carries no `testResults`, the key
    this schema always writes."""
    if not isinstance(obj, dict) or "testResults" not in obj:
        return None
    out = []
    for file_result in obj.get("testResults") or []:
        file_rel = file_result.get("name")
        for assertion in file_result.get("assertionResults") or []:
            if assertion.get("status") != "failed":
                continue
            chain = list(assertion.get("ancestorTitles") or []) + [
                assertion.get("title") or ""]
            why = "\n".join(assertion.get("failureMessages") or [])
            case = {"id": chain[-1], "label": " > ".join(chain),
                    "assertion": bool(_VITEST_JSON_ASSERTION.search(why)),
                    "why": why.strip() or "vitest: failed", "suite": file_rel,
                    "chain": chain}
            if case not in out:
                out.append(case)
    return out


def vitest_json_tally(obj):
    """The tally of a vitest (or jest) JSON reporter document, or None.

    A suite that never ran a test - a crashed import, a syntax error - is a
    `testResults` entry with no `assertionResults` at all; it is counted as
    one failure with no case, the same convention `_summary_tally` uses for a
    jest or vitest suite the line reporter names with no chain."""
    cases = vitest_json_cases(obj)
    if cases is None:
        return None
    crashed = len([r for r in obj.get("testResults") or []
                  if r.get("status") == "failed" and not r.get("assertionResults")])
    return {"runner": "vitest",
            "collected": int(obj.get("numTotalTests") or 0) + crashed,
            "failed": int(obj.get("numFailedTests") or 0) + crashed,
            "assertions": len([c for c in cases if c["assertion"]])}


def read_run_tally(text, cmd=None):
    """The tally `red` reads for one run: `read_tally` first - house, pytest,
    unittest, jest, vitest's line reporter - then the two reporters it carries
    no row for, playwright (its JSON reporter, else its line one) and vitest's
    JSON reporter; last, a clean sweep's own summary (`sweep_tally`), which is
    all a passing sweep prints."""
    tally = read_tally(text, cmd)
    if tally is not None:
        return tally
    obj = _json_blob(text)
    if obj is not None:
        for reader in (playwright_json_tally, vitest_json_tally):
            got = reader(obj)
            if got is not None:
                return got
    return playwright_line_tally(text) or sweep_tally(text)


def run_failing_cases(text, runner):
    """`failing_cases`'s shape for a run `red` graded, widened to the two
    reporters `read_run_tally` reads and `failing_cases` cannot: playwright
    (either reporter) and vitest's JSON one."""
    if runner == "playwright":
        return playwright_cases(text)
    if runner == "vitest":
        obj = _json_blob(text)
        got = vitest_json_cases(obj) if obj is not None else None
        if got is not None:
            return got
    return failing_cases(text, runner)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    print(__doc__.strip())
