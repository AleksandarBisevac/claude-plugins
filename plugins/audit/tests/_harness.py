#!/usr/bin/env python3
"""
The two things a moved `--selftest` needs and cannot bring with it: a path, and a runner.

45% of this tree was selftest code living inside the modules it tested, and all 48 files
carried their own copy of `check()`. Moving a block out breaks it twice - it can no longer
reach its module by a bare `import`, and it can no longer reach the `check`/tally contract
that was defined ten lines above it. This module owns both answers so a test file owns
neither.

PATH SETUP HAPPENS AT IMPORT, ON PURPOSE. `scripts/` and `hooks/` go onto `sys.path` when
this module is imported, not when a function is called. A setup function you must remember
to call is a fifth obligation beside the four `CLAUDE.md` already lists, and the failure
mode is an ImportError that reads like a missing file. `import _harness` first, then
`import _output` / `import _config` by basename, is the whole contract. Both directories
are added because a TEST may reach both: `hooks/` may not import `scripts/` (that isolation
is load-bearing and `_deps.layer_violations()` enforces it), but a test of a hook is not a
hook - it runs from a shell, once, with no launcher and no tool call behind it. Their order
cannot matter: `_deps`' r8 case fails the build if a `hooks/**.py` basename ever collides
with a `scripts/**.py` one.

AND EVERY SUBDIRECTORY OF `scripts/` HOLDING A `.py`, THROUGH `_output.install_path()`.
The two directories above are not enough the moment a script sits one level down: the
folders under `scripts/` are LABELS, NOT NAMESPACES, so `import _report_html` has to
resolve out of `scripts/report/` from a test exactly as it does from a production
sibling. That answer is not recomputed here - `install_path()` derives it from the one
recursive `.py` walk `_loader.script_index()` also reads, and a second walk in this file
would be a second answer to "what is in the tree". Found by the first real move: four
suites went red with `ModuleNotFoundError` while two stayed green purely because they
happened to `import _ui_theme` (whose own preamble bootstraps the path) BEFORE the module
under test - green by import order, which is not green.

THE VOCABULARY THIS UNIFIES, AND WHY THIS SHAPE WON. Measured across the 48 files, not
guessed:

  * `check` arity - 18 files take `(label, cond)`, 18 take `(label, cond, detail="")`, and
    12 wrap it in something domain-specific (`check(name, expected, payload)`). KEPT: the
    3-arg form, because it is the superset and a 2-arg call is a 3-arg call with an empty
    detail. The 12 domain wrappers stay in their own test files - a wrapper that calls
    `decide()` for you belongs beside the cases that need it, not in a shared runner.
  * the parameter's name - 22 files say `label`, 20 say `name`. KEPT: `label`, by count.
  * detail rendering - 17 of the 18 detail-carrying files print `" (%s)"` on FAILURE only;
    4 print `" :: %s"`. KEPT: `" (%s)"` on failure only. A detail printed on a passing case
    is noise the reader has to skip 3,451 times to find the one that matters, and one of
    the migrated suites proves it: `remind-tdd` printed `(expected record, got record)` on
    every green line.
  * the success tally - 39 files print `ALL PASS: N/M cases passed`; 9 print
    `<modulename>: N/M cases passed`. KEPT: `ALL PASS`. The 9 self-naming ones are not a
    style variant, they are a DEFECT: they print the same last line whether the suite
    passed or failed, so the sentinel that tells the two apart is the numbers being equal.
    Their module name is dropped rather than merged in because CI already echoes the
    filename before running it and every label carries its own suite prefix (`cf1`, `a1`).
  * the failure tally - 25 files say `SELFTEST FAILED`, 14 say `FAILURES`, 9 say nothing.
    KEPT: `SELFTEST FAILED`, by count.

`N/M cases passed` itself is not a choice: CI greps the output for it, and a file that does
not print it fails by name.

WHY `run(body)` AND NOT A BARE `check`. Nothing is printed until every case has run - that
is this repo's shape, and it is what makes the output a report rather than a stream. The
cost is that an exception raised while COMPUTING a case argument escapes before `check()` is
ever entered, and takes the whole suite's unprinted output with it: a traceback, and no idea
which of 90 cases were already green. `run()` puts the body inside a try, so an escape
becomes one more failing case, the cases already recorded still print, and the traceback
still names the line. `attempt()` is the finer-grained half, for a case that must not abort
the rest of the suite - `remind-tdd`'s selftest already hand-rolled exactly that guard
(`except Exception as exc: verdict = "EXC:%s" % exc`) and now borrows it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import json
import os
import re
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.dirname(_HERE)

TESTS_DIR = _HERE
SCRIPTS_DIR = os.path.join(_PLUGIN_DIR, "scripts")
HOOKS_DIR = os.path.join(_PLUGIN_DIR, "hooks")


# --- path setup ---------------------------------------------------------------
def _install_paths(dirs):
    """Put each of `dirs` on `sys.path`, front-most, skipping ones already there.

    Returns the list actually inserted, so the selftest can assert this ran rather
    than assert that an import happened to work - an import can succeed for reasons
    that have nothing to do with this function.
    """
    added = []
    for d in dirs:
        if d not in sys.path:
            sys.path.insert(0, d)
            added.append(d)
    return added


_install_paths((HOOKS_DIR, SCRIPTS_DIR))

import _output  # noqa: E402  (the anchor: reachable now that SCRIPTS_DIR is on the path)

# The subdirectories of `scripts/`, from the anchor rather than from a second walk here.
# Returns the list it installed, which is why the cases can assert this ran instead of
# asserting that some import happened to work.
SCRIPT_DIRS = _output.install_path()


# --- the shared runner --------------------------------------------------------
def attempt(fn, *args, **kwargs):
    """`(True, value)` from `fn(*args, **kwargs)`, or `(False, "TypeError: boom")`.

    For the case that must report its own exception and let the rest of the suite
    continue. `run()` covers the whole body; this covers one case, and the two are
    not the same choice: an escape from a fixture builder should stop the suite,
    while an escape from the eleventh of twenty independent probes should be the
    eleventh result.

    The message carries the exception's TYPE as well as its text, because a bare
    `str(exc)` on a KeyError is a quoted key with no clue what raised it.
    """
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:                                   # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def module_source(mod):
    """The SOURCE TEXT of `mod`, read off `mod.__file__`.

    THE ONE THING A SOURCE-READING CASE CANNOT SPELL FROM HERE. Three files -
    `panel-server.py`, `_panel_state.py` and `_panel_write.py` - each carried an
    identical `_src_of_this_file()` reading `open(__file__)`, and each one's ONLY
    caller was its own `--selftest` (six call sites, all inside the three suites;
    nothing in the product ever asked). Moved literally they would each read the
    TEST file: every "this route is only a GET", "these aliases exist", "this
    command passes --name-only" case would then be asking about a file that
    contains none of those things, and the `... not in ...` halves would pass by
    describing an empty room. Naming the module is the whole fix, and one helper
    is why three copies did not become three more.

    `mod` is a module OBJECT, so this works for a `_loader.load_script()` return
    (a hyphenated entry point has no importable name) exactly as it does for an
    `import x as M`.
    """
    with open(mod.__file__, encoding="utf-8") as fh:
        return fh.read()


def _module_body_offset(text):
    """Where the CODE starts, for text that is a Python module with a docstring.

    A marker quoted in a module's own docstring is prose ABOUT the code, so a
    slice that starts there is a check about the wrong region - F21 was that
    twice in one day. Both firings were loud, and the polarity that is not
    happened to be absent rather than impossible: with the two markers named
    either side of the flag in one plausible sentence, the `--name-only`
    security case in `test__panel_viewer.py` passes on the docstring's prose
    while guarding nothing - measured by injecting such a sentence into that
    module's docstring and taking the slice, not argued from the shape.
    Rewording the docstring - the repair that closed F21 - leaves that one edit
    away, for every marker in every suite. Starting below the docstring does
    not.

    Text that is not a Python module keeps every byte: `ast.parse` refuses it
    and the offset is zero. Text that IS one and has no docstring keeps every
    byte too, because the first statement is then code the caller may point at.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return 0
    if not tree.body:
        return 0
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return 0
    if not isinstance(first.value, ast.Constant):
        return 0
    if not isinstance(first.value.value, str):
        return 0
    end_line = getattr(first, "end_lineno", None)
    if end_line is None:
        return 0
    return len("".join(text.splitlines(True)[:end_line]))


def _only_in_docstring(text, offset, marker):
    """The half of a missing-marker message that says where the marker actually is.

    "You moved it" and "you are pointing at your own prose" are different
    diagnoses and the caller cannot tell them apart from the marker alone.
    """
    if offset and marker in text[:offset]:
        return (" below its module docstring - it appears only INSIDE that "
                "docstring, which is prose ABOUT the code and not the code")
    return ""


def between(text, start, end):
    """The slice of `text` after the first `start` and before the next `end`.

    RAISES on a marker that is not there, and that is the entire point. The
    hand-rolled form this replaces was `text.split(start)[1].split(end)[0]`, whose
    two halves fail in OPPOSITE ways: a missing `start` raises IndexError (loud),
    while a missing `end` quietly returns the whole remainder of the file. The
    slices that matter here are exactly the ones where the second half is the
    dangerous one - `_write_src` ran from `def do_PUT` to `def _free_port` and
    ended there only because `_free_port` happened to be the next top-level def,
    so moving that one function would have silently widened the slice to the rest
    of the file and turned four `"... not in _write_src"` cases vacuously true.

    An escape from here is not a crash: `run()` records it as a failing case with
    the traceback, so a marker that has moved is reported by name.

    THE SLICE STARTS BELOW A MODULE DOCSTRING, which is where every marker this
    is ever pointed at lives. `_module_body_offset` carries the reason and the
    measurement; F21 is the entry.
    """
    offset = _module_body_offset(text)
    body = text[offset:]
    i = body.find(start)
    if i < 0:
        raise ValueError("between(): start marker %r is not in the text%s - the "
                         "slice cannot be taken, and a whole-text fallback would "
                         "be a check about the wrong region"
                         % (start, _only_in_docstring(text, offset, start)))
    j = body.find(end, i + len(start))
    if j < 0:
        raise ValueError("between(): end marker %r is not in the text after %r%s - "
                         "the slice would silently run to the end of the file and "
                         "every `not in` case over it would pass vacuously"
                         % (end, start, _only_in_docstring(text, offset, end)))
    return body[i + len(start):j]


# --- a needle spelled the way the haystack spells it ---------------------------
def in_json(text):
    """`text` as a JSON string spells it - the needle for counting a path in JSON.

    Cases in more than one suite counted a temp-directory path in a feed file with
    `feed_text.count(str(tmpdir))`. On POSIX that is one string looked for in a
    copy of itself. On Windows `str(tmpdir)` is `C:\\Users\\RUNNER~1\\...`, the
    encoder doubles every separator on the way in, and the needle is nowhere in
    the haystack - so the `== 1` halves went red on the windows runner and the
    `== 0` halves went GREEN by describing an empty room. The vacuous half is the
    worse one: a check that cannot fail is not a check, and it had been on that
    runner for as long as the red one.

    `json.dumps(text)[1:-1]` is the encoder itself with its quotes taken off, so
    the needle is BY CONSTRUCTION what the writer put in the file rather than a
    second opinion about escaping. For text holding none of the characters JSON
    escapes - every POSIX path these suites build - it returns `text` unchanged,
    so an assertion it feeds is the assertion it always was.

    Only for haystacks that are JSON. A path quoted in PROSE - a hook's reason, a
    rendered report - is spelled natively there, and `str(path)` is already the
    right needle for it.
    """
    return json.dumps(text)[1:-1]


# --- two cases wearing one name -----------------------------------------------
# A leading token is an IDENTIFIER when it carries a digit: `pn10`, `sc9`, `h2b`,
# `bw1-a`. A leading `the`, `every` or `viewer:` is an English word or a group
# tag, and a suite spelled that way cannot be named from a `prove-gates.py` row
# at all - so it is not held to a convention it never adopted.
_CASE_ID = re.compile(r"^[A-Za-z][A-Za-z_-]*[0-9][A-Za-z0-9_-]*$")


def case_id(label):
    """The label's leading token when it is an identifier, else None.

    NOT A FORMATTING DETAIL. `tools/prove-gates.py` credits a mutation to the
    case that went red by taking exactly this token off a `FAIL <label>` line -
    it is the key the whole proof harness attributes by. F63 is what happens
    when two cases claim one key: the "RED, WRONG CASE" verdict that stops an
    unrelated breakage being called a proof is defeated for that key, silently,
    and a rule proven through the other case reads as proven.
    """
    head = label.split(None, 1)
    if not head or not _CASE_ID.match(head[0]):
        return None
    return head[0]


def label_faults(labels, sites):
    """Extra FAILING cases for two cases wearing one name; empty when clean.

    Two spellings of one defect, reported apart because they fail apart: an
    identifier claimed from more than one `check()` CALL SITE, and a whole label
    printed more than once.

    WHY THE CALL SITE AND NOT THE OCCURRENCE COUNT. A suite may legitimately
    print one identifier many times - `t3 0 is not a tier`, `t3 -3 is not a
    tier`, seven fixtures driven from one loop over one rule - and crediting a
    mutation to that family is exactly right, because the family IS one authored
    assertion. Measured over the tree rather than argued from the shape, and
    written in the past tense because the count is evidence for a decision and
    not a fact to keep true: 31 identifiers across 19 suites repeated that way
    the day this shipped, so a rule that counted occurrences would have called
    every one of them a duplicate and renumbered the family idiom wherever it
    appears. One call site is one authored assertion; two hand-written cases
    claiming `pn10` are two.

    `sites` maps an identifier to the set of caller line numbers that produced
    it. `run()` collects it because a line number is the one thing a rendered
    report has already thrown away, and it is what turns "this id is ambiguous"
    into two places to go and look.
    """
    faults = []
    for cid in sorted(sites):
        lines = sorted(sites[cid])
        if len(lines) > 1:
            faults.append(
                ("DUPLICATE CASE ID `%s` - claimed by %d separate check() call "
                 "sites, at lines %s. prove-gates.py credits a mutation to the "
                 "case whose id went red, so an id naming two cases defeats that "
                 "verdict silently (F63)"
                 % (cid, len(lines), ", ".join(str(n) for n in lines)),
                 False, ""))
    seen = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    for label in sorted(seen):
        if seen[label] > 1:
            faults.append(
                ("DUPLICATE CASE LABEL printed %d times, so no reader and no "
                 "tool can tell the two apart: %r" % (seen[label], label),
                 False, ""))
    return faults


def _render(cases):
    """`(text, passed, total)` - the report, not printed yet.

    Split from `run()` so the selftest can read what would be printed without
    capturing a stream, and so the exit code and the text are computed from one
    list rather than from two walks that could disagree.

    AN EMPTY SUITE IS `SELFTEST FAILED`, not `ALL PASS: 0/0`. `passed == total` is
    true of nothing at all, and a body whose cases were skipped, filtered away or
    never reached would otherwise print the calmest line in the file. Found by the
    case that asserts it rather than reasoned about afterwards.
    """
    lines = []
    passed = 0
    for label, ok, detail in cases:
        if ok:
            passed += 1
        lines.append("%s %s%s" % ("PASS" if ok else "FAIL", label,
                                  (" (%s)" % detail) if detail and not ok else ""))
    lines.append("")
    lines.append("%s: %d/%d cases passed"
                 % ("ALL PASS" if cases and passed == len(cases) else "SELFTEST FAILED",
                    passed, len(cases)))
    return "\n".join(lines), passed, len(cases)


def run(body):
    """Run `body(check)`, print every case and the tally, return an exit code.

    `body` is called with one argument, `check(label, cond, detail="")`, and is
    expected to call it once per case. `cond` is coerced with `bool()` so a case
    can assert on a list or a count without spelling the comparison twice.

    An exception escaping `body` is recorded as a final failing case and the
    traceback is written to stderr - see the module docstring for why that is the
    whole reason this wrapper exists. It is a FAILING case rather than a silent
    truncation, so a suite that dies half way cannot exit 0 with a plausible-looking
    `ALL PASS` over the cases that did run.

    EVERY SUITE ALSO GETS THE UNIQUENESS CHECK FOR FREE, because this is the one
    place that has already seen every label the suite produced - `label_faults()`
    carries what it rules and why. The caller's line number comes from
    `sys._getframe`, not from `inspect` or `traceback`: both of those read the
    source file to build a frame record, and this runs once per case across
    thousands of cases in one sweep.
    """
    cases = []
    sites = {}

    def check(label, cond, detail=""):
        cases.append((label, bool(cond), str(detail)))
        cid = case_id("%s" % (label,))
        if cid is not None:
            sites.setdefault(cid, set()).add(sys._getframe(1).f_lineno)

    try:
        body(check)
    except Exception as exc:                                   # noqa: BLE001
        traceback.print_exc()
        cases.append(("selftest body raised before reaching the end - "
                      "every case after this point did NOT run", False,
                      "%s: %s" % (type(exc).__name__, exc)))

    cases.extend(label_faults([c[0] for c in cases], sites))
    text, passed, total = _render(cases)
    print(text)
    return 0 if passed == total and total else 1


# --- selftest -----------------------------------------------------------------
def _capture(fn, *args, **kwargs):
    """`(stdout_text, returned)` for a call that prints. Restores the stream in
    `finally` - a case that swallows stdout forever takes every later case's output
    with it, which is the exact failure this module exists to prevent."""
    import io

    held = sys.stdout
    sys.stdout = io.StringIO()
    try:
        returned = fn(*args, **kwargs)
        return sys.stdout.getvalue(), returned
    finally:
        sys.stdout = held


def _quiet_stderr(fn, *args, **kwargs):
    """Call `fn` with stderr redirected, and throw the text away.

    `run()` prints a traceback on an escape; the cases below deliberately cause
    escapes, and an unsuppressed traceback in the middle of a green suite reads
    like a real failure to whoever is scrolling the CI log."""
    import io

    held = sys.stderr
    sys.stderr = io.StringIO()
    try:
        return fn(*args, **kwargs)
    finally:
        sys.stderr = held


def _labels(text):
    """Every case label in a rendered report, in order - what the migration proof
    compares. The tally line and the blank line before it are not cases."""
    return [line[5:] for line in text.splitlines()
            if line.startswith("PASS ") or line.startswith("FAIL ")]


def _cases(check):
    # -- path setup ------------------------------------------------------------
    check("h1 scripts/ and hooks/ are both on sys.path after import - a test may "
          "reach either, because a test of a hook is not a hook",
          SCRIPTS_DIR in sys.path and HOOKS_DIR in sys.path)
    check("h2 the directories are derived from this file's own location, not from "
          "the caller's cwd: %r" % (SCRIPTS_DIR,),
          os.path.isdir(SCRIPTS_DIR) and os.path.isdir(HOOKS_DIR)
          and os.path.basename(SCRIPTS_DIR) == "scripts"
          and os.path.basename(HOOKS_DIR) == "hooks")
    _subdirs = [d for d in SCRIPT_DIRS if d != SCRIPTS_DIR]
    check("h2b every SUBDIRECTORY of scripts/ holding a `.py` is on sys.path too, so "
          "`import _report_html` resolves out of scripts/report/ from a test exactly "
          "as it does from a sibling - the folders there are labels, not namespaces: "
          "%r" % (_subdirs,),
          SCRIPT_DIRS[0] == SCRIPTS_DIR
          and all(d in sys.path for d in SCRIPT_DIRS))
    check("h2c ...and there IS at least one, which is the direction that fails if "
          "this becomes the no-op it was while the tree was flat. Four suites went "
          "red on the first real move and two stayed green only by import order",
          _subdirs and all(os.path.isdir(d) for d in _subdirs))
    check("h3 _install_paths is idempotent - importing twice must not grow "
          "sys.path, and 'already there' is the answer, not 'insert again'",
          _install_paths((SCRIPTS_DIR, HOOKS_DIR)) == [])
    check("h4 ...and it DOES insert one that is absent. Reads vacuous beside h3 and "
          "is the only case that fails if the function becomes a no-op",
          _install_paths((os.path.join(TESTS_DIR, "no-such-dir"),))
          == [os.path.join(TESTS_DIR, "no-such-dir")])
    sys.path.remove(os.path.join(TESTS_DIR, "no-such-dir"))
    check("h5 a basename import through those paths actually resolves - the paths "
          "are the product, so one real import is the proof",
          __import__("_output").py_files is not None
          and __import__("_config").DEFAULTS is not None)

    # -- the report's shape ----------------------------------------------------
    text, passed, total = _render([("one", True, ""), ("two", False, "why")])
    check("r1 a passing case renders as `PASS <label>` with no detail",
          text.splitlines()[0] == "PASS one")
    check("r2 a failing case renders its detail, which is the only time a detail "
          "is worth printing", text.splitlines()[1] == "FAIL two (why)")
    check("r3 a detail on a PASSING case is not printed - the second direction, and "
          "the one that fails if detail rendering becomes unconditional",
          _render([("one", True, "noise")])[0].splitlines()[0] == "PASS one")
    check("r4 the tally is the last line and carries the contract CI greps for",
          text.splitlines()[-1] == "SELFTEST FAILED: 1/2 cases passed")
    check("r5 an all-green suite says ALL PASS, so the sentinel and not the "
          "arithmetic is what tells a reader which happened",
          _render([("one", True, "")])[0].splitlines()[-1]
          == "ALL PASS: 1/1 cases passed")
    check("r6 counts come from one walk: %d/%d" % (passed, total),
          (passed, total) == (1, 2))

    # -- run(): exit codes -----------------------------------------------------
    out_ok, code_ok = _capture(run, lambda c: c("x", True))
    check("n1 run() exits 0 on an all-green body", code_ok == 0)
    out_bad, code_bad = _capture(run, lambda c: c("x", False))
    check("n2 run() exits 1 on a failing case", code_bad == 1)
    check("n3 both printed their report rather than returning it silently",
          "ALL PASS: 1/1 cases passed" in out_ok
          and "SELFTEST FAILED: 0/1 cases passed" in out_bad)
    out_none, code_none = _capture(run, lambda c: None)
    check("n4 a body that records NO case exits 1, not 0 - an empty suite is the "
          "shape a filter that narrowed to nothing produces, and `0/0 passed` must "
          "never read as all clear", code_none == 1
          and "SELFTEST FAILED: 0/0 cases passed" in out_none)

    # -- run(): the guarded call, which is the reason it exists ----------------
    def _dies_midway(c):
        c("k1 first case, recorded before the explosion", True)
        c("k2 second case", True)
        raise ValueError("boom from a case argument")

    out_exc, code_exc = _quiet_stderr(_capture, run, _dies_midway)
    check("g1 an exception escaping the body does NOT take the suite's output with "
          "it: the cases already recorded still print",
          "PASS k1 first case, recorded before the explosion" in out_exc
          and "PASS k2 second case" in out_exc)
    check("g2 ...and the escape is itself a FAILING case, named, carrying the "
          "exception type and text",
          "FAIL selftest body raised before reaching the end" in out_exc
          and "ValueError: boom from a case argument" in out_exc)
    check("g3 ...so the suite exits 1. This is the case that fails if the guard "
          "ever swallows the exception and reports the green cases as a pass",
          code_exc == 1)
    check("g4 ...and the tally counts the escape, so 2 green cases read as 2/3 "
          "rather than as a complete 2/2 run",
          "SELFTEST FAILED: 2/3 cases passed" in out_exc)

    # -- attempt(): the per-case half ------------------------------------------
    ok_val, val = attempt(int, "12")
    check("t1 attempt() returns (True, value) when the call succeeds",
          ok_val is True and val == 12)
    ok_raise, msg = attempt(int, "not a number")
    check("t2 attempt() turns a raise into (False, message) instead of unwinding",
          ok_raise is False)
    check("t3 ...and the message names the exception TYPE, not just its text: %r"
          % (msg,), msg.startswith("ValueError: "))
    ok_kw, kw = attempt(dict, a=1)
    check("t4 attempt() forwards keyword arguments, not only positional ones",
          ok_kw is True and kw == {"a": 1})

    # -- the label extractor the migration proof leans on ----------------------
    check("l1 _labels() recovers the labels a report printed, and nothing else - "
          "the tally line is not a case",
          _labels(text) == ["one", "two (why)"])

    # -- two cases wearing one name (F63) --------------------------------------
    # THE TWO CALLS BELOW MUST SIT ON DIFFERENT LINES. Written as a one-line
    # lambda they would share one call site, the rule would correctly stay
    # silent, and the case would pass against a `run()` that never learned any
    # of this - the fixture, not the assertion, is what tells the two versions
    # apart.
    def _claims_one_id_twice(c):
        c("dup7 first case claiming the id", True)
        c("dup7 second case claiming the SAME id", True)

    out_dup, code_dup = _capture(run, _claims_one_id_twice)
    check("u1 an id claimed from two check() call sites is reported by NAME, "
          "with the count and both line numbers. F63: prove-gates.py credits a "
          "mutation to the case whose id went red, so an ambiguous id defeats "
          "its 'RED, WRONG CASE' verdict silently",
          "FAIL DUPLICATE CASE ID `dup7`" in out_dup
          and "2 separate check() call sites" in out_dup, out_dup)
    check("u2 ...and the report says so as a FAILING case, so a suite nothing "
          "can attribute cannot exit 0. The mutation this catches is reporting "
          "the duplicate as a detail hung off a passing line",
          code_dup == 1
          and "SELFTEST FAILED: 2/3 cases passed" in out_dup, out_dup)
    # u3 AND u4 LOOK VACUOUS AND ARE THE SECOND-DIRECTION CASES. Both pass on
    # the pre-F63 code by construction, and they are the only ones here that
    # fail if the rule starts firing where it should not: u3 if it fires
    # unconditionally, u4 if it counts OCCURRENCES instead of call sites.
    check("u3 a suite whose ids are all distinct is told nothing at all",
          label_faults(["a1 one", "a2 two"],
                       {"a1": set([10]), "a2": set([11])}) == [])
    # THROUGH `run()`, NOT THROUGH `label_faults()` DIRECTLY. A hand-built
    # `sites` dict would assert nothing about the half that keys on the call
    # site, so the mutation this case exists for - collecting one key per case
    # instead of one per call site - would leave it green.
    def _one_site_many_fixtures(c):
        for _bad in (0, -3, None, 1.5):
            c("t3 %r is not a tier, so the phase sorts as unprioritised"
              % (_bad,), True)

    out_fam, code_fam = _capture(run, _one_site_many_fixtures)
    check("u4 ...and one id printed many times from ONE call site is not a "
          "duplicate: `t3 0 is not a tier`, `t3 -3 is not a tier`, fixtures "
          "driven from one loop over one rule, which is one authored assertion. "
          "Counting occurrences instead would have called 31 ids across 19 "
          "suites duplicates the day this was written - measured, which is why "
          "the rule reads the call site and not the count",
          code_fam == 0 and "DUPLICATE" not in out_fam, out_fam)
    _same = label_faults(["...and a refused PUT wrote nothing"] * 2, {})
    check("u5 a whole label printed twice is the other spelling of the defect "
          "and fails apart from the first: there is no id to name, and no "
          "reader and no tool can tell the two lines apart",
          len(_same) == 1 and _same[0][1] is False
          and "printed 2 times" in _same[0][0], repr(_same))
    check("u6 an id has to carry a digit, so a suite whose labels open with "
          "`the`, `every` or `viewer:` is not held to a convention it never "
          "adopted - while `bw1-a`, `h2b` and `pn10` are ids",
          [case_id(_lbl) for _lbl in
           ("the page renders", "viewer: a GET and nothing else",
            "bw1-a a borrowed wrapper", "h2b every SUBDIRECTORY",
            "pn10 COMPLETENESS is caught")]
          == [None, None, "bw1-a", "h2b", "pn10"])
    # A NAMED LOCAL BELOW rather than the same call twice, which is the whole
    # reason now. It arrived for a different one: the prose scanner used to split
    # an identifier on the underscore, so a numeric index in front of `case_id(`
    # read as a cardinality claim, and naming the local was the rewording. The
    # scanner keeps an identifier whole since F77, so the workaround is no longer
    # load-bearing - kept because computing one id twice in one assertion is
    # worse, not because anything forces it.
    _pn10b_id = case_id("pn10b the BARE count")
    check("u7 the id is read here the way prove-gates.py reads it back off a "
          "rendered line - two spellings of one key, pinned rather than "
          "commented, because that tool is the only consumer and a comment "
          "claiming they agree is not a test that they do",
          _render([("pn10b the BARE count", False, "")])[0]
          .splitlines()[0].split(None, 2)[1] == _pn10b_id)

    # -- module_source(): the subject's file, never the test's -----------------
    import _output as _ms_probe

    # Assembled at runtime, not written out: a literal here would plant itself in
    # THIS file and the second half of the case would fail on its own text - which
    # is the same self-matching bug (F-P-8) that made a panel route check find its
    # own assertion line.
    _ms_needle = "def " + "covered_repo_paths("
    check("m1 module_source() reads the module it is HANDED, and this is the "
          "whole reason it exists: a source-slice case moved to tests/ that kept "
          "reading `__file__` would be asking about this file instead",
          _ms_needle in module_source(_ms_probe)
          and _ms_needle not in open(__file__, encoding="utf-8").read())
    check("m2 ...and it is the file on disk, byte for byte - not a re-render, so "
          "an assertion about whitespace or comment text still means something",
          module_source(_ms_probe)
          == open(_ms_probe.__file__, encoding="utf-8").read())

    # -- between(): both markers are load-bearing ------------------------------
    _bt = "aaa START middle END zzz"
    check("s1 between() returns what sits between the two markers",
          between(_bt, "START", "END") == " middle ")
    _s_ok, _s_msg = attempt(between, _bt, "NOPE", "END")
    check("s2 a missing START raises rather than returning something - the half "
          "the hand-rolled `.split(x)[1]` already got right",
          _s_ok is False and "start marker" in _s_msg, _s_msg)
    _e_ok, _e_msg = attempt(between, _bt, "START", "NOPE")
    check("s3 ...and a missing END raises TOO, which is the half `.split(y)[0]` "
          "got wrong: it returns the whole remainder, and every `not in` case "
          "over that slice then passes by describing a region it never meant",
          _e_ok is False and "end marker" in _e_msg, _e_msg)
    check("s4 the naive form really does fail silently - measured, not asserted "
          "from memory: splitting on an absent END hands back everything after "
          "START, including the `zzz` the slice was supposed to exclude",
          _bt.split("START")[1].split("NOPE")[0] == " middle END zzz")
    check("s5 END is looked for AFTER start, so a marker that also appears "
          "before it cannot produce an empty slice",
          between("END aaa START middle END zzz", "START", "END") == " middle ")

    # -- between(): a marker in the module docstring is prose, not code --------
    # F21's remainder. Each fixture below is chosen so the pre-fix and post-fix
    # implementations DISAGREE - a fixture both versions answer the same way
    # would leave these green against a `between()` that never learned this.
    _prose = ('"""`def target` runs with PAYLOAD before `def stop` ranks it.\n'
              '"""\n'
              'def target():\n'
              '    return 1\n'
              '\n'
              'def stop():\n'
              '    return 2\n')
    # Through `attempt`, not bare: a mutation that makes this marker unfindable
    # would otherwise escape and stop the suite AT this line, so the cases below
    # would not run and a red-first proof would learn nothing about them.
    _p_ok, _p_sl = attempt(between, _prose, "def target", "def stop")
    check("s6 the QUIET polarity of F21: with both markers named either side of "
          "a payload in the docstring, the pre-fix slice was that sentence and "
          "the payload was IN it, so the case passed guarding nothing. The slice "
          "is now the code, and the payload is absent from it",
          _p_ok is True and "PAYLOAD" not in _p_sl and "return 1" in _p_sl,
          repr(_p_sl))
    _only_doc = ('"""The slice runs from `def gone` to `def alsogone`.\n'
                 '"""\n'
                 'def real():\n'
                 '    return 1\n')
    _d_ok, _d_msg = attempt(between, _only_doc, "def gone", "def alsogone")
    check("s7 ...and F21's LOUD polarity now says which of the two diagnoses it "
          "is: a marker that exists only in the docstring raises, and the "
          "message names the docstring rather than only the marker",
          _d_ok is False and "module docstring" in _d_msg, _d_msg)
    # s8 LOOKS VACUOUS AND IS THE SECOND-DIRECTION CASE. It passes on the
    # pre-fix code by construction; it is the only one here that fails if
    # `_module_body_offset` starts returning an offset for anything - a broad
    # `except`, or dropping the `isinstance` guards - because this text opens
    # with a quoted string and is NOT a Python module.
    _notpy = '"START only-in-the-leading-string END" {not python at all\n'
    _n_ok, _n_sl = attempt(between, _notpy, "START", "END")
    check("s8 text that is not a Python module keeps every byte: a leading "
          "quoted string is not a docstring just because it looks like one",
          _n_ok is True and _n_sl == " only-in-the-leading-string ", repr(_n_sl))
    _nodoc = 'import os\n\n\ndef target():\n    return 1\n\n\ndef stop():\n    return 2\n'
    check("s9 a module whose first statement is CODE keeps every byte too - the "
          "caller may legitimately point at it, so only a docstring is skipped",
          _module_body_offset(_nodoc) == 0, repr(_nodoc[:12]))
    check("s10 the offset lands exactly where the docstring ends, not a line "
          "either side of it - an off-by-one here would either re-admit the "
          "prose or eat the first line of code",
          _prose[_module_body_offset(_prose):].startswith("def target"),
          repr(_prose[_module_body_offset(_prose):][:20]))

    # -- in_json(): the needle for a path counted inside JSON -------------------
    # THE WINDOWS SPELLING IS BUILT HERE RATHER THAN TAKEN FROM tempfile, so this
    # runs on every platform: what broke was the ENCODING of a separator, and a
    # literal reproduces that on macOS exactly as the runner does on Windows.
    _posix_p = "/var/folders/d1/T/gate-feed-outside-abc/probe.py"
    check("j1 a path with nothing for JSON to escape comes back unchanged, so "
          "every assertion this feeds on POSIX is the assertion it already was",
          in_json(_posix_p) == _posix_p)
    _win_p = "C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\gate-feed-outside-abc"
    _row = json.dumps({"event": "deny", "file": _win_p + "\\probe.py"},
                      sort_keys=True, separators=(",", ":"))
    check("j2 ...and the windows spelling is found in what the ENCODER actually "
          "wrote, exactly once - driven through json.dumps rather than compared "
          "to a hand-written expectation, which would agree with a wrong needle "
          "forever: %r" % (_row,),
          _row.count(in_json(_win_p)) == 1)
    check("j3 ...where the RAW spelling occurs 0 times, which is the half the "
          "broken cases were leaning on: `feed.count(str(tmpdir)) == 0` passed "
          "on the windows runner by looking for something no encoder can emit",
          _row.count(_win_p) == 0 and in_json(_win_p) != _win_p)


def _selftest():
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio  # scripts/ is on sys.path by import of this module
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _harness.py --selftest\n")
    raise SystemExit(2)
