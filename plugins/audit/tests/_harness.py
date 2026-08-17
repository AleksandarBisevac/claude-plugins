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

import os
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
    """
    i = text.find(start)
    if i < 0:
        raise ValueError("between(): start marker %r is not in the text - the "
                         "slice cannot be taken, and a whole-text fallback would "
                         "be a check about the wrong region" % (start,))
    j = text.find(end, i + len(start))
    if j < 0:
        raise ValueError("between(): end marker %r is not in the text after %r - "
                         "the slice would silently run to the end of the file and "
                         "every `not in` case over it would pass vacuously"
                         % (end, start))
    return text[i + len(start):j]


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
    """
    cases = []

    def check(label, cond, detail=""):
        cases.append((label, bool(cond), str(detail)))

    try:
        body(check)
    except Exception as exc:                                   # noqa: BLE001
        traceback.print_exc()
        cases.append(("selftest body raised before reaching the end - "
                      "every case after this point did NOT run", False,
                      "%s: %s" % (type(exc).__name__, exc)))

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


def _selftest():
    return run(_cases)


if __name__ == "__main__":
    from _output import safe_stdio  # scripts/ is on sys.path by import of this module
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _harness.py --selftest\n")
    raise SystemExit(2)
