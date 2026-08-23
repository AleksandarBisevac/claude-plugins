#!/usr/bin/env python3
"""
The house selftest runner, as reached from `tools/` - and the rule that keeps it here.

WHY A BRIDGE RATHER THAN A SECOND RUNNER. `plugins/audit/tests/_harness.py` owns
`run()`: the `N/M cases passed` contract, the escape guard that turns a raised fixture
into a named failing case with every case already recorded still printed, and the
case-id uniqueness check. Every suite under `tests/` inherited all of it and every tool
under `tools/` inherited none, because each tool wrote its own printer - most of them
saying `FAILURES` where the house says `SELFTEST FAILED`, and one saying nothing at
all. `_harness`' own docstring records that spelling as a DEFECT rather than a variant:
a suite whose last line reads the same whether it passed or failed leaves the numbers
as its only sentinel. So the fix was documented, adopted, and had never reached these
files (F73).

`run` is re-exported here, not reimplemented. A second copy of mutate-print-tally is
how the hand-rolled printers came to disagree in the first place - and `attempt` comes
with it, because a tool with a probe that must not abort the suite wants the same
answer `tests/` already has rather than a local `try` written a tenth way.

WHY THE IMPORT IS DEFERRED, WHICH IS THE OBJECTION THIS FILE ANSWERS. `tools/` is
outside the plugin, and importing `_harness` puts `scripts/`, `hooks/` and every
subdirectory of `scripts/` on `sys.path` as a side effect of the import. A tool that
renders a report or counts pins should not pay for the test tree to run, and - more to
the point - should not stop working when it is missing. So each tool imports this
module INSIDE `_selftest()`, and a normal run never reaches the test tree at all. The
`sys.path` cost lands only on the one mode that needs a runner.

That is also why `tools/` is not the `tests_import_violations()` rule's business.
That rule forbids `scripts/` and `hooks/` - the PRODUCT, the thing that ships - from
importing its own test tree. `tools/` ships with nothing; it is development machinery
in the same sense `tests/` is, and the marketplace payload is `plugins/audit/`.

AND THE RULE, BECAUSE AN EXEMPTION THAT EXISTS ONLY AS THE ABSENCE OF AN IMPORT IS
WHAT F73 WAS. `hand_rolled_runners()` reads every tool's `_selftest` and reports one
that tallies its own cases instead of delegating here. It is derived from the tree, so
the NEXT tool is covered the day it is written rather than the day somebody remembers.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
TOOLS_DIR = _HERE
TESTS_DIR = os.path.join(REPO, "plugins", "audit", "tests")

if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

# `_harness` puts `scripts/`, `hooks/` and every `.py`-bearing subdirectory of
# `scripts/` on `sys.path` as it is imported - which is why this import is the
# thing tools defer, and why `_output` below is reachable without a second bootstrap.
import _harness  # noqa: E402
import _output   # noqa: E402

# THE re-export, and the whole point of the file. Bound to the function object rather
# than wrapped: a wrapper here would be a second place for the tally to be spelled,
# and `s1` pins this identity for exactly that reason.
run = _harness.run
attempt = _harness.attempt


# --- the rule: no tool tallies its own cases ----------------------------------
def _selftest_body(tree):
    """The statements of a module-level `def _selftest`, or None if there is none."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_selftest":
            return node.body
    return None


def _is_runner_import(stmt):
    """True for an import out of this module - `from _suite import run`, or run and
    `attempt` together.

    The NAMES are not pinned, only where they come from: a rule that spelled the
    import list would refuse a tool importing the other half of the pair, and the
    delegation below is what actually carries the weight here.
    """
    return isinstance(stmt, ast.ImportFrom) and stmt.module == "_suite"


def _is_delegation(stmt):
    """True for `return run(<name>)` - the whole of a delegating `_selftest`."""
    if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    return (isinstance(call.func, ast.Name) and call.func.id == "run"
            and len(call.args) == 1 and isinstance(call.args[0], ast.Name)
            and not call.keywords)


def runner_problem(source):
    """Why `source`'s `_selftest` does not delegate to the house runner, or None.

    A PURE FUNCTION OVER TEXT, so both directions of the rule are driven from
    strings rather than from `.py` files written into a temp directory. That is
    not only cheaper: a `.py` basename literal written under `tools/` has to name
    a real file (`_refs.tool_basename_drift()`), so a fixture-file spelling of
    these cases would need a declared exemption to say what a string says for
    free.

    A module with no `_selftest` is NOT this rule's finding - the sweep already
    fails a tool that prints no contract, and reporting it twice under two
    different names is two bug reports for one defect.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "does not parse, so nothing can be said about its runner: %s" % (exc,)
    body = _selftest_body(tree)
    if body is None:
        return None
    for stmt in body:
        if _is_runner_import(stmt) or _is_delegation(stmt):
            continue
        return ("its `_selftest` does its own work at line %d instead of handing "
                "`_cases` to the shared runner - which is how a tool comes to print "
                "its own tally, and every hand-rolled tally so far has printed the "
                "same last line on a pass and on a failure. The whole of a tool's "
                "`_selftest` is `from _suite import run` and `return run(_cases)`, "
                "with `_cases(check)` calling `check(label, cond, detail=\"\")` "
                "once per case" % (stmt.lineno,))
    if not any(_is_delegation(stmt) for stmt in body):
        return ("its `_selftest` never returns `run(_cases)`, so whatever it reports "
                "is not the house contract")
    return None


def hand_rolled_runners(tools_dir=None):
    """[(rel, problem)] for every tool that runs its own suite. Empty when clean.

    Walks with `_output.py_files()`, the same recursive walk the sweep uses to
    decide which files must carry a suite at all - a second walk here is how a
    file in a subdirectory comes to be swept by one rule and missed by another.
    """
    root = tools_dir if tools_dir is not None else TOOLS_DIR
    out = []
    for rel, path in _output.py_files(root):
        try:
            source = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            out.append((rel, "could not be read: %s" % (exc,)))
            continue
        problem = runner_problem(source)
        if problem is not None:
            out.append((rel, problem))
    return out


# --- selftest -----------------------------------------------------------------
def _cases(check):
    check("s1 `run` IS `_harness.run`, the same function object the suites under "
          "tests/ call - not a copy, not a wrapper. This is the case that fails "
          "the day somebody reimplements the tally here, which is the defect this "
          "file exists to stop rather than to relocate",
          run is _harness.run and attempt is _harness.attempt)
    check("s2 ...so the deferred import really did reach the test tree: %r"
          % (TESTS_DIR,),
          os.path.isfile(os.path.join(TESTS_DIR, "_harness.py"))
          and TESTS_DIR in sys.path)

    # F73's actual complaint, asserted rather than described: a suite that ends the
    # same way whether it passed or failed has the numbers as its only sentinel.
    # Both directions are needed - the failing line must be the house spelling AND
    # the passing line must not be it, or a runner that always said SELFTEST FAILED
    # would pass the first half.
    _held = sys.stdout
    sys.stdout = io.StringIO()
    try:
        green_code = run(lambda c: c("x1 a green case", True))
        green = sys.stdout.getvalue()
        sys.stdout = io.StringIO()
        red_code = run(lambda c: c("x2 a red case", False))
        red = sys.stdout.getvalue()
    finally:
        sys.stdout = _held
    check("s3 the last line differs between a pass and a failure, and the failing "
          "one carries the house spelling: %r vs %r"
          % (green.strip().splitlines()[-1:], red.strip().splitlines()[-1:]),
          green.strip().endswith("ALL PASS: 1/1 cases passed")
          and red.strip().endswith("SELFTEST FAILED: 0/1 cases passed"))
    check("s4 ...and the exit codes agree with the two sentinels, so a caller that "
          "reads the code and a reader who reads the line cannot disagree",
          (green_code, red_code) == (0, 1))

    # The rule, over the real tree. This is the case that goes red if a tool goes
    # back to printing its own tally.
    live = hand_rolled_runners()
    check("s5 every tool hands its cases to the shared runner: %r" % (live,),
          live == [])

    _delegating = ("def _cases(check):\n"
                   "    check('d1 a case', True)\n"
                   "\n"
                   "def _selftest():\n"
                   "    from _suite import run\n"
                   "    return run(_cases)\n")
    check("s6 ...and that is not the rule finding nothing findable: the shape it "
          "accepts is the shape the tools are written in, and it accepts the other "
          "half of the pair being imported beside the runner",
          runner_problem(_delegating) is None
          and runner_problem(_delegating.replace("import run",
                                                 "import attempt, run")) is None)
    # THE SECOND DIRECTION, and the fixture is the pre-F73 body verbatim in
    # miniature - the seven-way copy, including the sentinel that read the same
    # on both paths. A rule that accepted this would have accepted the tree as it
    # stood, which is the state that made F73 an entry rather than a preference.
    _hand_rolled = ("def _cases():\n"
                    "    return [('d1 a case', True, 'why')]\n"
                    "\n"
                    "def _selftest():\n"
                    "    rows = _cases()\n"
                    "    bad = [r for r in rows if not r[1]]\n"
                    "    print('%s: %d/%d cases passed' % ('ALL PASS', 1, 1))\n"
                    "    return 1 if bad else 0\n")
    _hand_problem = runner_problem(_hand_rolled)
    check("s7 a tool that runs its own suite is reported, and the report names the "
          "line rather than only the file: %r" % (_hand_problem,),
          _hand_problem is not None and "line 5" in _hand_problem)
    check("s8 a `_selftest` that is only an import and no delegation is reported "
          "too - the shape a half-finished migration leaves behind, which would "
          "otherwise return None from a body every statement of which was legal",
          runner_problem("def _selftest():\n"
                         "    from _suite import run\n") is not None)
    check("s9 a module with NO `_selftest` is not this rule's finding - the sweep "
          "already fails a tool that prints no contract, and one defect wants one "
          "name", runner_problem("x = 1\n") is None)
    check("s10 a file that will not parse is REPORTED, never skipped: a scan that "
          "quietly drops a file it could not read is a clean answer about a file "
          "nobody looked at",
          (runner_problem("def _selftest(:\n") or "").startswith("does not parse"))


def _selftest():
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _suite.py --selftest\n")
    raise SystemExit(2)
