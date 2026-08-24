#!/usr/bin/env python3
"""
The house helpers `tools/` may not copy, as reached from here - and the rules that
keep them here.

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

`remove_tree` is here for the same reason and it is the second thing this file carries
(F155). Git writes its loose objects READ-ONLY. On POSIX that is invisible, because
unlinking a file needs a writable DIRECTORY and not a writable file; on windows the
attribute is read off the file itself, `os.unlink` raises, and `shutil.rmtree` leaves
`.git/objects/**` behind - SILENTLY, because every caller in this tree spells the call
`ignore_errors=True`. `_harness.remove_tree()` is the answer, `tools/sweep-selftests.py`
keeps the one deliberate copy of it (a runner may not import a file it is one of the
runners OF, and `removal_helper_drift()` compares the two statement for statement), and
a tool that needs the same answer gets it from here rather than becoming a third home.

WHY THE IMPORT IS DEFERRED, WHICH IS THE OBJECTION THIS FILE ANSWERS. `tools/` is
outside the plugin, and importing `_harness` puts `scripts/`, `hooks/` and every
subdirectory of `scripts/` on `sys.path` as a side effect of the import. A tool that
renders a report or counts pins should not pay for the test tree to run, and - more to
the point - should not stop working when it is missing. So a tool imports this module
INSIDE the code path that needs it - `_selftest()` for the runner, the `finally` that
disposes of a fixture for the removal - and the `sys.path` cost lands only on the modes
that ask for it. A tool whose FIXTURE is a git repository does reach the test tree on
its ordinary run, and that is a cost rather than a breakage: such a tool is a gate
driven from a checkout that has `tests/` in it, and `tools/` is development machinery in
the same sense `tests/` is.

That is also why `tools/` is not the `tests_import_violations()` rule's business.
That rule forbids `scripts/` and `hooks/` - the PRODUCT, the thing that ships - from
importing its own test tree. `tools/` ships with nothing; it is development machinery
in the same sense `tests/` is, and the marketplace payload is `plugins/audit/`.

AND THE RULES, BECAUSE AN EXEMPTION THAT EXISTS ONLY AS THE ABSENCE OF AN IMPORT IS
WHAT F73 WAS. `hand_rolled_runners()` reads every tool's `_selftest` and reports one
that tallies its own cases instead of delegating here. `unsafe_removal_violations()`
reads every tool's removals and reports a bare `shutil.rmtree` in a tool that builds a
repository with objects in it. Both are derived from the tree, so the NEXT tool is
covered the day it is written rather than the day somebody remembers - which is the
answer to F155, whose call sites were enumerated by hand and whose next one would
not have been.

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

# THE SAME BINDING FOR THE SAME REASON, and the reason is sharper here: this fact has
# two homes already and a check that compares them, so a third spelling is not a style
# question but a rule broken. Bound, never wrapped - `s11` pins the identity, and
# `unsafe_removal_violations()` below quotes this name out of the object rather than
# out of a literal, so the rule cannot come to name a helper the bridge does not hand
# out.
remove_tree = _harness.remove_tree


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


# --- the rule: no tool removes a repository it built with a bare rmtree --------
# THE TWO SETS ARE THE MEASUREMENT, NOT A GUESS AT ONE. Run a bare repository
# initialisation into an empty directory and nothing under it lacks an owner-write
# bit; stage a single file and a read-only loose object appears immediately. So the
# marker for "this tool builds a tree windows cannot remove" is not the presence of
# a repository, it is the presence of a repository that has been WRITTEN to - and
# spelling it this way is what keeps the demo capture, whose fixture initialises a
# repository and never stages anything into it, out of the findings while convicting
# it on the day its fixture learns to stage or commit. An exemption row would have
# recorded the same premise in prose and gone on firing after it stopped being true.
REPO_MARKERS = ("git", "init")
OBJECT_MARKERS = ("add", "commit")


def _plain_constants(tree):
    """Every string constant in `tree` except the docstrings.

    THE NARROWING IS WHAT LETS THIS RULE LIVE IN A FILE THAT EXPLAINS IT. Several
    guards here read source as TEXT and cannot tell code from a comment about code,
    and the usual way to meet one is to describe it. Dropping docstrings is a
    distinction with a reason behind it rather than a hole cut to fit this file: a
    word a module only ever says about itself is not a word it passes to a
    subprocess. Comments are not constants at all, so they never arrive here.
    """
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            continue
        if not body or not isinstance(body[0], ast.Expr):
            continue
        first = body[0].value
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            docstrings.add(id(first))
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.add(node.value)
    return out


def _bare_removal_lines(tree, helper):
    """The lines of every `<module>.rmtree(...)` call outside `def <helper>`.

    THE HELPER IS NOT ONE OF ITS OWN CALLERS. `remove_tree` is BUILT out of two
    ordinary removals - one that works everywhere and one behind a chmod pass - so
    a rule that counted them would convict the very answer it hands out, and the
    repair a reader reaches for when a rule convicts the arrangement it was written
    to police is to delete the rule. The copy under `tools/sweep-selftests.py` is
    the file this protects today.
    """
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == helper:
            for child in ast.walk(node):
                inside.add(id(child))
    lines = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rmtree" and id(node) not in inside):
            lines.append(node.lineno)
    return sorted(lines)


def removal_problem(source):
    """Why `source` cannot remove the repositories it builds, or None.

    A PURE FUNCTION OVER TEXT, like `runner_problem()` above and for the same two
    reasons: both directions of the rule are driven from strings rather than from
    files written into a temp directory, and a `.py` basename written under
    `tools/` has to name a file that exists (`_refs.tool_basename_drift()`), so a
    fixture spelled as a file would need a declared exemption to say what a string
    says for free.

    THE RULE IS PER MODULE AND NOT PER TREE, which is the whole of what it buys.
    Nothing static can say which of a module's directories will hold the `.git` -
    that is the judgement F155 asked of a reader at every site, and it came back
    wrong more than once. Asking the module instead costs nothing: on a tree with
    no read-only file the careful removal's second half never runs, so uniformity
    inside a repository-building tool is free and the judgement is gone.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "does not parse, so nothing can be said about its removals: %s" % (exc,)
    words = _plain_constants(tree)
    if not all(marker in words for marker in REPO_MARKERS):
        return None
    if not any(marker in words for marker in OBJECT_MARKERS):
        return None
    lines = _bare_removal_lines(tree, remove_tree.__name__)
    if not lines:
        return None
    return ("it builds a git repository and writes to it, then removes a tree with "
            "`shutil.rmtree` at line(s) %s. Git's loose objects are read-only, "
            "windows refuses to unlink a read-only file, and `ignore_errors=True` "
            "turns that refusal into silence - so the removal has never worked "
            "there and nothing said so. `from _suite import %s`, which is "
            "`_harness.%s` and retries behind a chmod pass"
            % (", ".join(str(line) for line in lines), remove_tree.__name__,
               remove_tree.__name__))


def unsafe_removal_violations(tools_dir=None):
    """[(rel, problem)] for every tool that cannot remove what it built. Empty when
    clean.

    Walks with `_output.py_files()`, the same recursive walk `hand_rolled_runners()`
    and the sweep use - a second walk here is how a file in a subdirectory comes to
    be covered by one rule and missed by another.
    """
    root = tools_dir if tools_dir is not None else TOOLS_DIR
    out = []
    for rel, path in _output.py_files(root):
        try:
            source = io.open(path, encoding="utf-8").read()
        except OSError as exc:
            out.append((rel, "could not be read: %s" % (exc,)))
            continue
        problem = removal_problem(source)
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

    # --- F155: the removal, and the rule that keeps it reachable from here -----
    check("s11 `remove_tree` IS `_harness.remove_tree`, the same function object "
          "the suites under tests/ call - not a copy. This fact is allowed exactly "
          "two homes, `tests/_harness.py` and the deliberate copy in the sweep "
          "runner, and `removal_helper_drift()` compares those two. A binding here "
          "is how a tool gets the answer without becoming a third",
          remove_tree is _harness.remove_tree)

    # The fixture is BOTH directions of the helper exclusion in one body: a removal
    # inside `def remove_tree` (which is what the helper is BUILT of) and a removal
    # outside it (which is the defect). A version that skipped the exclusion reports
    # both lines, so the fixture tells the two implementations apart instead of
    # merely exercising one.
    _removing = ("import shutil\n"
                 "\n"
                 "def build(root):\n"
                 "    run(['git', '-C', root, 'init', '-q'])\n"
                 "    run(['git', '-C', root, 'commit', '-m', 'seed'])\n"
                 "\n"
                 "def remove_tree(path):\n"
                 "    shutil.rmtree(path, ignore_errors=True)\n"
                 "\n"
                 "def drop(root):\n"
                 "    shutil.rmtree(root, ignore_errors=True)\n")
    _removing_lines = _bare_removal_lines(ast.parse(_removing),
                                          remove_tree.__name__)
    check("s12 the helper's OWN body is not one of its callers - the careful "
          "removal is built out of ordinary ones, and a rule that counted them "
          "would convict the answer it hands out. Both removals are in this "
          "fixture and only the one outside the helper is reported: %r"
          % (_removing_lines,),
          _removing_lines == [11])
    _removing_problem = removal_problem(_removing)
    check("s13 a tool that stages or commits into a repository and then removes a "
          "tree with a bare `shutil.rmtree` is REPORTED, and the report names the "
          "line and the way out rather than only the file: %r"
          % (_removing_problem,),
          _removing_problem is not None
          and "line(s) 11" in _removing_problem
          and remove_tree.__name__ in _removing_problem)

    # THE PAIR, AND THE MUTATION IT EXISTS FOR: a rule that fired on any repository
    # at all rather than on a WRITTEN one. It reads as vacuous - it asserts that
    # something is not reported - and it is the only case that goes red when the
    # object-verb half of the marker test is removed. Measured rather than assumed:
    # a bare initialisation leaves nothing without an owner-write bit, and a single
    # staged file leaves a read-only loose object.
    _init_only = _removing.replace(
        "    run(['git', '-C', root, 'commit', '-m', 'seed'])\n", "")
    check("s14 ...while a tool that only INITIALISES a repository and never writes "
          "an object into it is not reported: there is no read-only object under a "
          "repository nothing was staged into, so a plain removal is the right one "
          "and a finding here would be a demand with no failure behind it",
          "commit" not in _init_only and removal_problem(_init_only) is None)
    check("s15 a file that will not parse is REPORTED by this rule too, never "
          "skipped",
          (removal_problem("def drop(:\n") or "").startswith("does not parse"))

    # The rule over the real tree. This is the case that goes red the day a tool
    # that builds a repository goes back to removing it with a bare call.
    _live_removals = unsafe_removal_violations()
    check("s16 every tool that builds a repository removes it the one way that "
          "works on both platforms: %r" % (_live_removals,),
          _live_removals == [])


def _selftest():
    return run(_cases)


if __name__ == "__main__":
    _output.safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: _suite.py --selftest\n")
    raise SystemExit(2)
