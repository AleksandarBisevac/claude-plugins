#!/usr/bin/env python3
"""
The cases for `_floor_guard.py` - which moves in a task's diff lower the bar.

The reason the module exists is one observed session shape: an agent edited an
existing test's assertion so the test passed, and nothing that reads a task's
work would have seen it. So the cases are grouped by the three answers the
module gives: each of the five moves found on a minimal diff (`fm`), the honest
edits that must give no finding however much they look like one (`fa`), and
the inputs the module cannot read, each of which must say so rather than read
as clean (`fc`).

Every fixture diff but one is built here from a base and a tree text with
`difflib`, in git's header shape. The one that is not (`REAL_GIT`) was printed
by a real `git diff -M --no-color HEAD` over a small repository, so the parser
is not tested only against diffs written by the same hand that wrote it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import ast
import collections
import difflib
import json
import re
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio, some_of           # noqa: E402
import _filed_returns                              # noqa: E402
import _floor_guard as M                           # noqa: E402

# Read through getattr, so a module without them fails each case that needs
# them on its own line rather than ending the run; the stand-in never
# equals a word the module writes.
PARTLY_READ = getattr(M, "PARTLY_READ", "<absent: PARTLY_READ>")
COULD_HOLD = getattr(M, "COULD_HOLD", "<absent: COULD_HOLD>")
CANNOT_HOLD = getattr(M, "CANNOT_HOLD", "<absent: CANNOT_HOLD>")


# --- building a diff ------------------------------------------------------------

def _hunks(base, tree):
    lines = list(difflib.unified_diff((base or "").splitlines(True),
                                      (tree or "").splitlines(True), n=3))
    return lines[2:]


def _file_diff(path, base, tree, old=None):
    """One file's section of a git diff: `base` None is an added file, `tree`
    None a deleted one, `old` a rename source."""
    old = old or path
    head = ["diff --git a/%s b/%s\n" % (old, path)]
    if base is None:
        head += ["new file mode 100644\n", "--- /dev/null\n", "+++ b/%s\n" % path]
    elif tree is None:
        head += ["deleted file mode 100644\n", "--- a/%s\n" % old, "+++ /dev/null\n"]
    else:
        if old != path:
            sim = "100" if base == tree else "90"
            head += ["similarity index %s%%\n" % sim, "rename from %s\n" % old,
                     "rename to %s\n" % path]
            if base == tree:
                return "".join(head)
        head += ["--- a/%s\n" % old, "+++ b/%s\n" % path]
    return "".join(head + _hunks(base, tree))


def _readers(files):
    base = dict(((f[3] or f[0]), f[1]) for f in files if f[1] is not None)
    tree = dict((f[0], f[2]) for f in files if f[2] is not None)
    return base.get, tree.get


def _run(files, declared=(), accepted=None):
    """`files` is a list of (path, base, tree[, old]) rows. `accepted` is passed
    only when given, and a module that refuses the argument answers a result no
    case can read as clean - so a case about it fails on its own line instead of
    ending the run."""
    rows = [tuple(f) + (None,) * (4 - len(f)) for f in files]
    diff = "".join(_file_diff(r[0], r[1], r[2], r[3]) for r in rows)
    read_base, read_tree = _readers(rows)
    if accepted is None:
        return M.find_moves(diff, read_base, read_tree, declared=declared)
    try:
        return M.find_moves(diff, read_base, read_tree, declared=declared,
                            accepted=accepted)
    except TypeError as exc:
        return {"answer": "refused: %s" % exc, "basis": "", "findings": None,
                "couldNotTell": [], "notRead": []}


def _moves(result, move=None):
    return [f for f in result["findings"] or () if move is None or f["move"] == move]


def _show(result):
    return "%s | %s | %r | cnt=%r" % (result.get("answer"), result.get("basis"),
                                     result.get("findings"), result.get("couldNotTell"))


# --- fixtures -------------------------------------------------------------------

CART_TEST = """\
import pytest

from cart import total


def test_total():
    \"\"\"The sum of the cart.\"\"\"
    # three items
    assert total([1, 2]) == 3


def test_empty():
    assert total([]) == 0


class TestCart:
    def test_one(self):
        assert total([1]) == 1
"""

CART_SRC = """\
def total(xs):
    return sum(xs)


def parse(text):
    try:
        return int(text)
    except ValueError:
        return None
"""

JS_TEST = """\
import { add } from "../src/add";

describe("add", () => {
  it("adds", () => {
    expect(add(1, 2)).toBe(3);
  });

  it("adds zero", () => {
    expect(add(0, 2)).toBe(2);
  });
});
"""

GO_TEST = """\
package cart

import "testing"

func TestTotal(t *testing.T) {
\tif Total([]int{1, 2}) != 3 {
\t\tt.Fatal("total is wrong")
\t}
}
"""

JS_SRC = """\
export function load(path) {
  try {
    return read(path);
  } catch (err) {
    return log(err);
  }
}
"""

# Printed by `git diff -M --no-color HEAD` in a scratch repository: a noqa added
# to src/cart.py, a 100% rename of a JS test, an assertion weakened in
# tests/test_cart.py, and tests/test_gone.py deleted.
REAL_GIT = """\
diff --git a/src/cart.py b/src/cart.py
index 8ce3223..ba93eeb 100644
--- a/src/cart.py
+++ b/src/cart.py
@@ -1,2 +1,2 @@
 def total(xs):
-    return sum(xs)
+    return sum(xs)  # noqa: E501
diff --git a/tests/old.test.js b/tests/renamed.test.js
similarity index 100%
rename from tests/old.test.js
rename to tests/renamed.test.js
diff --git a/tests/test_cart.py b/tests/test_cart.py
index 0cbb0ab..ec82b9d 100644
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -1,5 +1,5 @@
 def test_total():
-    assert 1 + 2 == 3
+    assert 1 + 2 >= 0


 def test_empty():
diff --git a/tests/test_gone.py b/tests/test_gone.py
deleted file mode 100644
index 9ac3582..0000000
--- a/tests/test_gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def gone():
-    return 1
"""

REAL_BASE = {
    "src/cart.py": "def total(xs):\n    return sum(xs)\n",
    "tests/old.test.js": 'it("adds", () => {\n  expect(add(1, 2)).toBe(3);\n});\n',
    "tests/test_cart.py": ("def test_total():\n    assert 1 + 2 == 3\n\n\n"
                           "def test_empty():\n    assert [] == []\n"),
    "tests/test_gone.py": "def gone():\n    return 1\n",
}
REAL_TREE = {
    "src/cart.py": "def total(xs):\n    return sum(xs)  # noqa: E501\n",
    "tests/renamed.test.js": REAL_BASE["tests/old.test.js"],
    "tests/test_cart.py": ("def test_total():\n    assert 1 + 2 >= 0\n\n\n"
                           "def test_empty():\n    assert [] == []\n"),
}


# --- the five moves -------------------------------------------------------------

def _found(check):
    got = _run([("tests/test_cart.py", CART_TEST, None)])
    hits = _moves(got, M.TEST_DELETED)
    check("fm1 a deleted test file is a test-deleted finding on its path: %s" % _show(got),
          got["answer"] == M.FINDINGS and len(hits) == 1
          and hits[0]["path"] == "tests/test_cart.py" and hits[0]["side"] == "base")

    tree = CART_TEST.replace("assert total([1, 2]) == 3", "assert total([1, 2]) >= 0")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm2 an existing test's assertion weakened is a definition change on "
          "its def line in the tree: %s" % _show(got),
          len(hits) == 1 and hits[0]["path"] == "tests/test_cart.py"
          and hits[0]["line"] == 6 and hits[0]["side"] == "tree"
          and "test_total" in hits[0]["what"])

    tree = CART_TEST.replace("def test_empty():\n    assert total([]) == 0\n\n\n", "")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm3 a test definition that disappears is reported on its base line: %s"
          % _show(got),
          len(hits) == 1 and hits[0]["line"] == 12 and hits[0]["side"] == "base"
          and "test_empty" in hits[0]["what"])

    tree = CART_TEST.replace("assert total([1]) == 1", "assert total([1])")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm4 a method is compared by its qualified name Class.method: %s" % _show(got),
          len(hits) == 1 and "TestCart.test_one" in hits[0]["what"]
          and hits[0]["line"] == 17)

    tree = CART_TEST.replace("def test_empty():", "@pytest.mark.flaky(reruns=5)\n"
                             "def test_empty():")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm5 a decorator added to a test is a change to its definition: %s" % _show(got),
          len(hits) == 1 and "test_empty" in hits[0]["what"])

    tree = JS_TEST.replace("    expect(add(1, 2)).toBe(3);\n", "")
    got = _run([("tests/add.test.js", JS_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm6 a removed expect( line in a JS test is reported on its base line: %s"
          % _show(got),
          len(hits) == 1 and hits[0]["line"] == 5 and hits[0]["side"] == "base"
          and hits[0]["path"] == "tests/add.test.js")

    tree = JS_TEST.replace("toBe(3)", "toBeDefined()")
    got = _run([("tests/add.test.js", JS_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm7 an assertion line rewritten in place still counts as removed: %s"
          % _show(got), len(hits) == 1 and hits[0]["line"] == 5)

    tree = GO_TEST.replace('\t\tt.Fatal("total is wrong")\n', "")
    got = _run([("cart_test.go", GO_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm8 a removed t.Fatal in a Go test is reported: %s" % _show(got),
          len(hits) == 1 and hits[0]["line"] == 7)

    tree = CART_TEST.replace("def test_empty():",
                             "@pytest.mark.skip(reason='later')\ndef test_empty():")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    hits = _moves(got, M.SKIP_ADDED)
    check("fm9 a pytest skip marker added to a test file is a skip finding on its "
          "line: %s" % _show(got),
          len(hits) == 1 and hits[0]["line"] == 12 and hits[0]["side"] == "tree")

    skips = (("it.skip", JS_TEST.replace('it("adds zero"', 'it.skip("adds zero"'), 8),
             ("xit", JS_TEST.replace('it("adds zero"', 'xit("adds zero"'), 8),
             ("it.todo", JS_TEST.replace('  it("adds zero", () => {\n'
                                         '    expect(add(0, 2)).toBe(2);\n  });\n',
                                         '  it.todo("adds zero");\n'), 8))
    seen = []
    for name, tree, line in skips:
        got = _run([("tests/add.test.js", JS_TEST, tree)])
        seen.append((name, [(f["line"]) for f in _moves(got, M.SKIP_ADDED)]))
    check("fm10 it.skip, xit and it.todo added to a JS test are skip findings: %r" % seen,
          seen == [(n, [l]) for n, _t, l in skips])

    tree = GO_TEST.replace("func TestTotal(t *testing.T) {\n",
                           "func TestTotal(t *testing.T) {\n\tt.Skip()\n")
    got = _run([("cart_test.go", GO_TEST, tree)])
    check("fm11 t.Skip() added to a Go test is a skip finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.SKIP_ADDED)] == [6])

    tree = CART_SRC.replace("return sum(xs)", "return sum(xs)  # noqa: E501")
    got = _run([("src/cart.py", CART_SRC, tree)])
    hits = _moves(got, M.SUPPRESSION_ADDED)
    check("fm12 a noqa added to source code is a suppression finding: %s" % _show(got),
          len(hits) == 1 and hits[0]["line"] == 2 and hits[0]["path"] == "src/cart.py")

    tree = JS_SRC.replace("    return read(path);\n",
                          "    // eslint-disable-next-line no-undef\n"
                          "    return read(path); // @ts-ignore\n")
    got = _run([("src/load.js", JS_SRC, tree)])
    check("fm13 eslint-disable and @ts-ignore added to JS are two suppression "
          "findings: %s" % _show(got),
          sorted(f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)) == [3, 4])

    tree = CART_TEST.replace("    assert total([]) == 0\n",
                             "    assert total([]) == 0  # pragma: no cover\n")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    check("fm14 a suppression added to a test file's own code is found there too: %s"
          % _show(got),
          [f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)] == [13])

    tree = CART_SRC.replace("    return sum(xs)\n", "    raise NotImplementedError\n")
    got = _run([("src/cart.py", CART_SRC, tree)])
    check("fm15 raise NotImplementedError added to source is a stub finding: %s"
          % _show(got),
          [f["line"] for f in _moves(got, M.STUB_ADDED)] == [2])

    tree = CART_SRC.replace("        return None\n", "        pass\n")
    got = _run([("src/cart.py", CART_SRC, tree)])
    check("fm16 an except body emptied to pass is a stub finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.STUB_ADDED)] == [8])

    tree = JS_SRC.replace("    return log(err);\n", "")
    got = _run([("src/load.js", JS_SRC, tree)])
    check("fm17 a JS catch body emptied is a stub finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.STUB_ADDED)] == [4])

    tree = JS_SRC.replace("    return read(path);\n",
                          "    throw new Error('Not implemented');\n")
    got = _run([("src/load.js", JS_SRC, tree)])
    check("fm18 throw new Error('Not implemented') added to JS is a stub finding: %s"
          % _show(got),
          [f["line"] for f in _moves(got, M.STUB_ADDED)] == [3])

    tree = CART_TEST + "\n\ndef test_later():\n    raise NotImplementedError\n"
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    check("fm19 a stub is a finding in non-test code only - the same raise in a "
          "test file is not one: %s" % _show(got),
          _moves(got, M.STUB_ADDED) == [])

    tree = JS_SRC.replace("    return read(path);\n",
                          "    return read(path).skip(4);\n")
    got = _run([("src/load.js", JS_SRC, tree)])
    check("fm23 a skip is read in test files only - a stream's .skip( in source "
          "code is no finding: %s" % _show(got),
          got["answer"] == M.CLEAN and got["findings"] == [])

    got = M.find_moves(REAL_GIT, REAL_BASE.get, REAL_TREE.get)
    kinds = sorted((f["move"], f["path"], f["line"]) for f in got["findings"])
    check("fm20 a diff printed by real git: the noqa, the weakened assertion and the "
          "deleted test, and nothing for the 100%% rename: %r" % (kinds,),
          kinds == sorted([(M.SUPPRESSION_ADDED, "src/cart.py", 2),
                           (M.DEFINITION_CHANGED, "tests/test_cart.py", 1),
                           (M.TEST_DELETED, "tests/test_gone.py", 1)]))

    every = []
    for files in ([("tests/test_cart.py", CART_TEST, None)],
                  [("src/cart.py", CART_SRC, CART_SRC.replace(
                      "return sum(xs)", "return sum(xs)  # type: ignore"))]):
        every.extend(_run(files)["findings"])
    shaped = [f for f in every if f["move"] in M.MOVES and f["path"]
              and isinstance(f["line"], int) and f["line"] >= 1
              and f["side"] in ("base", "tree")]
    check("fm21 every finding carries a move name, a path and a line: %r" % (every,),
          every and shaped == every)

    # `pkg/cart_spec.rb` is the probe that tells the definitions apart: the plan
    # gate's exempt globs count that suffix as a test and `is_test_path` does not.
    deleted = [p for p in ("specs/cart.rb", "src/cart.rb", "pkg/cart.spec.js",
                           "pkg/cart_spec.rb")
               if _moves(_run([(p, "x = 1\n", None)]), M.TEST_DELETED)]
    check("fm22 what a test file is comes from _filed_returns.is_test_path, not a "
          "second definition: %r" % (deleted,),
          M.is_test_path is _filed_returns.is_test_path
          and deleted == ["specs/cart.rb", "pkg/cart.spec.js"])


# --- honest edits that must give no finding -------------------------------------

def _allowed(check):
    tree = CART_TEST + "\n\ndef test_three():\n    assert total([1, 1, 1]) == 3\n"
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    check("fa1 a test appended to an existing file gives no finding: %s" % _show(got),
          got["answer"] == M.CLEAN and got["findings"] == [])

    tree = CART_TEST.replace("def test_empty():", "def test_empty_cart():")
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    check("fa2 a test renamed with its body unchanged gives no finding and is "
          "listed as renamed: %s %r" % (_show(got), got.get("renamed")),
          got["answer"] == M.CLEAN and got["findings"] == []
          and len(got["renamed"]) == 1)

    tree = CART_TEST.replace("assert total([1, 2]) == 3", "assert total([1, 2]) == 4")
    by_case = _run([("tests/test_cart.py", CART_TEST, tree)],
                   declared=("tests/test_cart.py::test_total",))
    by_file = _run([("tests/test_cart.py", CART_TEST, tree)],
                   declared=("tests/test_cart.py",))
    other = _run([("tests/test_cart.py", CART_TEST, tree)],
                 declared=("tests/test_cart.py::test_empty",))
    check("fa3 a changed definition the task declared by its case is returned as "
          "declared, apart from findings; a bare path or another case declares no "
          "definition the base already held: %s / %s / %s"
          % (_show(by_case), _show(by_file), _show(other)),
          by_case["findings"] == [] and len(by_case["declared"]) == 1
          and by_case["declared"][0]["path"] == "tests/test_cart.py"
          and by_case["answer"] == M.CLEAN
          and len(_moves(by_file, M.DEFINITION_CHANGED)) == 1 and by_file["declared"] == []
          and len(_moves(other, M.DEFINITION_CHANGED)) == 1 and other["declared"] == [])

    tree = JS_TEST.replace("toBe(3)", "toBe(4)")
    got = _run([("tests/add.test.js", JS_TEST, tree)], declared=("tests/add.test.js",))
    named = _run([("tests/add.test.js", JS_TEST, tree)],
                 declared=("tests/add.test.js::adds",))
    check("fa4 an assertion line the base held, changed in a JS test the task "
          "declares, is a finding whether the file or a case is declared - a "
          "line of a JS test maps to no case name, and a declaration covers "
          "only what is new: %s / %s" % (_show(got), _show(named)),
          len(_moves(got, M.DEFINITION_CHANGED)) == 1 and got["declared"] == []
          and len(_moves(named, M.DEFINITION_CHANGED)) == 1 and named["declared"] == [])

    base = "import os  # noqa: F401\nimport sys\n"
    moved = "import sys\nimport os  # noqa: F401\n"
    edited = "import os.path  # noqa: F401\nimport sys\n"
    got = [_run([("src/boot.py", base, t)]) for t in (moved, edited)]
    check("fa5 a coded noqa on a line that only moved, or whose code changed, gives "
          "no finding - the base copy already carries that noqa code: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [g["findings"] for g in got] == [[], []]
          and [g["answer"] for g in got] == [M.CLEAN, M.CLEAN])

    tree = CART_TEST.replace("# three items", "# three items, summed").replace(
        '"""The sum of the cart."""', '"""What the cart adds up to."""')
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    check("fa6 a comment or docstring edit inside a test gives no finding: %s"
          % _show(got),
          got["answer"] == M.CLEAN and got["findings"] == [])

    tree = CART_TEST + ('\n\nFIXTURE = """\\\nimport os  # noqa: F401\n'
                        'x = 1  # type: ignore\n"""\n'
                        'SKIPPED = "@pytest.mark.skip(reason=1)"\n\n\n'
                        'def test_lint():\n'
                        '    assert lint(FIXTURE) == ["# pragma: no cover"]\n')
    got = _run([("tests/test_cart.py", CART_TEST, tree)])
    js_tree = JS_TEST.replace('describe("add", () => {\n',
                              'const SRC = "// eslint-disable-next-line";\n'
                              'const SKIP = "it.skip(";\n'
                              'describe("add", () => {\n')
    js = _run([("tests/add.test.js", JS_TEST, js_tree)])
    check("fa7 a suppression or a skip spelled inside a test's fixture string "
          "gives no finding: %s / %s" % (_show(got), _show(js)),
          got["findings"] == [] and js["findings"] == [])

    tree = JS_TEST.replace('    expect(add(1, 2)).toBe(3);\n',
                           '      expect(add(1, 2)).toBe(3);\n')
    got = _run([("tests/add.test.js", JS_TEST, tree)])
    check("fa8 an assertion line only re-indented gives no finding: %s" % _show(got),
          got["findings"] == [])

    got = _run([("tests/test_basket.py", CART_TEST, CART_TEST, "tests/test_cart.py")])
    edited = _run([("tests/test_basket.py", CART_TEST,
                    CART_TEST + "\n\ndef test_x():\n    assert True\n",
                    "tests/test_cart.py")])
    check("fa9 a test file renamed, whole or with a test appended, gives no finding: "
          "%s / %s" % (_show(got), _show(edited)),
          got["findings"] == [] and edited["findings"] == []
          and got["answer"] == M.CLEAN and edited["answer"] == M.CLEAN)

    # The second direction: a guard that always fires passes every case above
    # that expects a finding; this ordinary source edit must come back clean.
    tree = CART_SRC.replace("return sum(xs)", "return sum(x for x in xs)")
    got = _run([("src/cart.py", CART_SRC, tree)])
    check("fa10 an ordinary source edit with none of the moves is clean: %s" % _show(got),
          got["answer"] == M.CLEAN and got["findings"] == [] and got["basis"])

    base = CART_SRC + "\n\ndef later():\n    raise NotImplementedError\n"
    stub = _run([("src/cart.py", base, base.replace(
        "raise NotImplementedError\n", "raise NotImplementedError('later')\n"))])
    js_base = JS_TEST.replace('it("adds zero"', 'it.skip("adds zero"')
    skip = _run([("tests/add.test.js", js_base,
                  js_base.replace('it.skip("adds zero"', 'it.skip("adds nothing"'))])
    check("fa20 a stub or a skip the base already had, whose line was only reworded, "
          "gives no finding - paired by kind once its text no longer matches: %s / %s"
          % (_show(stub), _show(skip)),
          stub["findings"] == [] and stub["answer"] == M.CLEAN
          and skip["findings"] == [] and skip["answer"] == M.CLEAN)

    doc = "# Linting\n\nWrite `# noqa` only with a code.\n"
    got = _run([("docs/lint.md", "# Linting\n", doc)])
    check("fa11 a document naming a suppression gives no finding, and the file is "
          "named as not read rather than passed over in silence: %s %r"
          % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN
          and [n["path"] for n in got["notRead"]] == ["docs/lint.md"])


# --- a test is what the runner would run ----------------------------------------
# Each narrowing is held from both sides: an allow case that goes red when the
# narrowing is removed (the guard compares every definition again and over-fires)
# and a deny case that goes red when it is widened into silence.

ROW_SUITE = """\
import sys


def _cases(check):
    check("c1 one", 1 == 1)


def _selftest():
    return _run(_cases)
"""

HELPER_TEST = CART_TEST + """

def _basket():
    return [1, 2]
"""


def _definitions(check):
    tree = ROW_SUITE.replace('    check("c1 one", 1 == 1)\n',
                             '    check("c1 one", 1 == 1)\n    check("c2 two", 2 == 2)\n')
    got = _run([("tests/test_rows.py", ROW_SUITE, tree)])
    check("fa12 a labelled check added inside a case-table function gives no "
          "finding, and the file - its labelled checks compared by label, its "
          "other code only added to - is compared, not listed: %s %r"
          % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN and got["notRead"] == [])

    tree = ROW_SUITE.replace("import sys\n", "import sys  # the runner's argv\n")
    got = _run([("tests/test_rows.py", ROW_SUITE, tree)])
    check("fa13 a comment edit in a file with no test definition touches no code: "
          "clean, and not listed as not read: %s %r" % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN and got["notRead"] == [])

    tree = HELPER_TEST.replace("return [1, 2]", "return [1, 2, 3]")
    got = _run([("tests/test_cart.py", HELPER_TEST, tree)])
    listed = [n for n in got["notRead"] if n["path"] == "tests/test_cart.py"]
    check("fa14 a helper changed beside untouched test_ functions gives no finding, "
          "and the file is listed as not compared for the definition move - the "
          "helper is code outside its tests: %s %r" % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == PARTLY_READ and len(listed) == 1
          and listed[0].get("move") == M.DEFINITION_CHANGED
          and listed[0].get("kind") == COULD_HOLD and listed[0].get("reason"))

    tree = HELPER_TEST.replace("return [1, 2]", "return [1, 2, 3]").replace(
        "assert total([1, 2]) == 3", "assert total([1, 2]) >= 0")
    got = _run([("tests/test_cart.py", HELPER_TEST, tree)])
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm24 a test_ function changed beside a changed helper is the one "
          "finding, and the helper is not: %s" % _show(got),
          len(hits) == 1 and "test_total" in hits[0]["what"]
          and "_basket" not in hits[0]["what"] and got["findings"] == hits)

    tree = ROW_SUITE + "\n\ndef test_rows():\n    assert _cases\n"
    edited = tree.replace("    assert _cases\n", "    assert True\n")
    got = _run([("tests/test_rows.py", tree, edited)])
    check("fm25 a file that has a test_ definition is compared even when it also "
          "keeps a case table - its changed test is a finding, not a not-read: %s"
          % _show(got),
          [f["what"] for f in _moves(got, M.DEFINITION_CHANGED)
           if "test_rows" in f["what"]] != [] and got["notRead"] == [])

    base = CART_TEST.replace("class TestCart:\n", "class TestCart:\n    def setUp(self):\n"
                             "        self.xs = [1]\n\n") + "\n\ndef Test_upper():\n    pass\n"
    tree = base.replace("self.xs = [1]", "self.xs = []").replace(
        "def Test_upper():\n    pass", "def Test_upper():\n    return 1")
    got = _run([("tests/test_cart.py", base, tree)])
    check("fa19 the convention is one fixed prefix, compared case-sensitively as "
          "unittest and pytest compare it: a changed setUp and a changed "
          "Test_upper are not tests, so no finding - they are code outside the "
          "tests, and the file is listed as not compared: %s" % _show(got),
          M.TEST_PREFIX == "test" and got["findings"] == []
          and got["answer"] == PARTLY_READ
          and [n["path"] for n in got["notRead"]] == ["tests/test_cart.py"])


# --- a suppression is a finding only when its code is new to the file -----------

PREAMBLE = """\
import sys

import _output  # noqa: E402
"""


def _suppressions(check):
    tree = PREAMBLE + "import _manifest_io  # noqa: E402\n"
    got = _run([("src/boot.py", PREAMBLE, tree)])
    blanket = "import os\nx = 1  # noqa\n"
    twice = _run([("src/flat.py", blanket, blanket + "y = 2  # noqa\n")])
    check("fa15 a second noqa E402 where the base already has one gives no finding, "
          "and a second blanket noqa beside a blanket one neither: %s / %s"
          % (_show(got), _show(twice)),
          got["findings"] == [] and got["answer"] == M.CLEAN
          and twice["findings"] == [] and twice["answer"] == M.CLEAN)

    tree = PREAMBLE + "x = _output.thing  # type: ignore[attr-defined]\n"
    got = _run([("src/boot.py", PREAMBLE, tree)])
    check("fm26 the first type-ignore in a file whose base has only noqa E402 is a "
          "finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)] == [4])

    tree = PREAMBLE + "x = 1  # noqa: E501\n"
    got = _run([("src/boot.py", PREAMBLE, tree)])
    check("fm27 a noqa with a code the base does not carry is a finding though the "
          "base has another noqa - the code is compared, not the marker: %s"
          % _show(got),
          [f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)] == [4])

    tree = PREAMBLE + "x = 1  # noqa\n"
    got = _run([("src/boot.py", PREAMBLE, tree)])
    check("fm28 a blanket noqa added where the base has only coded ones is a "
          "finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)] == [4])

    fresh = [("src/new_mod.py", None, PREAMBLE)]
    accepted = _run(fresh, accepted=("noqa: E402",))
    plain = _run(fresh)
    check("fa16 a new file whose noqa E402 is an accepted code gives no finding: %s"
          % _show(accepted),
          accepted["findings"] == [] and accepted["answer"] == M.CLEAN)
    check("fm29 a new file's noqa E402 with nothing accepted is a finding - a file "
          "arriving already suppressed is the move: %s" % _show(plain),
          [f["line"] for f in _moves(plain, M.SUPPRESSION_ADDED)] == [3])

    old = _run([("src/flat.py", "import os\n", "import os\nimport x  # noqa: E402\n")],
               accepted=("noqa: E402",))
    spelled = [_run(fresh, accepted=(a,)) for a in ("noqa:E402", "  noqa:   E402 ",
                                                    "noqa: F401, E402")]
    check("fa17 an accepted code is never reported in an old file either, and is "
          "matched on kind and code whatever the blanks around it or beside "
          "another code: %s / %s" % (_show(old), [_show(s) for s in spelled]),
          old["findings"] == [] and old["answer"] == M.CLEAN
          and [s["findings"] for s in spelled] == [[], [], []])

    bad = [_run(fresh, accepted=a) for a in (("NOQA: E402",), ("E402",),
                                             ("noqa: E402 extra",), "noqa: E402")]
    check("fc13 an accepted entry the tables do not read whole - another case, a "
          "bare code, trailing words, or one string in place of a sequence - is "
          "could-not-tell naming it, never an entry that silently matches "
          "nothing: %s" % [_show(b) for b in bad],
          [b["answer"] for b in bad] == [M.COULD_NOT_TELL] * 4
          and all(b["basis"] and b["findings"] == [] for b in bad))

    near = [_run(fresh, accepted=(a,)) for a in ("noqa: E40", "noqa: e402",
                                                 "type: ignore[E402]")]
    check("fm30 a near miss is not an accepted code - a prefix of it, its code in "
          "another case, or the code under another kind: %s"
          % [_show(n) for n in near],
          [[f["line"] for f in _moves(n, M.SUPPRESSION_ADDED)] for n in near]
          == [[3], [3], [3]])

    mixed = [("src/new_mod.py", None, PREAMBLE + "y = 1  # type: ignore\n")]
    got = _run(mixed, accepted=("noqa: E402",))
    check("fm31 accepting one code silences that code only - a type-ignore beside "
          "it in the same new file is still a finding: %s" % _show(got),
          [f["line"] for f in _moves(got, M.SUPPRESSION_ADDED)] == [4])

    base = "// eslint-disable-next-line no-undef\nread(path);\n"
    same = _run([("src/load.js", base, base + "// eslint-disable-next-line no-undef\n"
                  "write(path);\n")])
    other = _run([("src/load.js", base, base + "// eslint-disable-next-line no-console\n"
                   "console.log(path);\n")])
    check("fa18 an eslint-disable for a rule the base already disables gives no "
          "finding: %s" % _show(same),
          same["findings"] == [] and same["answer"] == M.CLEAN)
    check("fm32 an eslint-disable for a rule new to the file is a finding: %s"
          % _show(other),
          [f["line"] for f in _moves(other, M.SUPPRESSION_ADDED)] == [3])


# --- the marker is read where the linter reads it --------------------------------
# Each spelling below was run through ruff on a two-line file before it was
# written here: the deny rows are the ones ruff obeyed (the import was no longer
# reported), the allow rows the ones it did not. A guard that matched the word
# anywhere passes every deny row and fails the allow rows; a guard that read
# only the lower-case word at the comment's start fails the deny rows.

def _marker(check):
    read = ("x = 1  # NOQA\n", "x = 1  # NoQa: F401\n", "x = 1  #noqa:F401\n",
            "x = 1  #   noqa\n", "x = 1  # noqa trailing words\n",
            "x = 1  # todo  # noqa\n")
    seen = [(t, [f["line"] for f in _moves(_run([("src/cart.py", CART_SRC,
                                                    CART_SRC + t)]),
                                          M.SUPPRESSION_ADDED)]) for t in read]
    check("fm33 a marker the linter obeys is a finding in any letter case, with "
          "codes or text after it, or opening a second comment: %r" % (seen,),
          [s[1] for s in seen] == [[10]] * len(read))

    whole = ("# ruff: noqa\n", "# flake8: NOQA\n", "#ruff:noqa: F401\n")
    seen = [(h, [f["line"] for f in _moves(_run([("src/cart.py", CART_SRC,
                                                   h + CART_SRC)]),
                                          M.SUPPRESSION_ADDED)]) for h in whole]
    check("fm34 a file-level marker on its own line is a finding: %r" % (seen,),
          [s[1] for s in seen] == [[1]] * len(whole))

    prose = ("x = 1  # the word noqa here\n", "# a noqa added to source code is read\n",
             "x = 1  # see: noqa\n", "x = 1  # noqa-like\n", "x = 1  # xnoqa\n",
             "x = 1  # ruff: noqa\n")
    got = [(t, _run([("src/cart.py", CART_SRC, CART_SRC + t)])) for t in prose]
    test = _run([("tests/test_cart.py", CART_TEST,
                  CART_TEST.replace("# three items", "# three items, a noqa is not"))])
    check("fa21 a comment that only mentions the word - in prose, glued to other "
          "letters, or a file-level directive written after code - gives no "
          "finding, in source or in a test: %r / %s"
          % ([(t, _show(g)) for t, g in got if g["findings"]], _show(test)),
          [g["findings"] for _t, g in got] == [[]] * len(prose)
          and [g["answer"] for _t, g in got] == [M.CLEAN] * len(prose)
          and test["findings"] == [] and test["answer"] == M.CLEAN)

    strings = ('MSG = "add # noqa to silence it"\n',
               'def note():\n    """Write # noqa only with a code."""\n')
    got = [_run([("src/cart.py", CART_SRC, CART_SRC + s)]) for s in strings]
    base = "import os  # noqa: F401\n"
    upper = _run([("src/boot.py", base, base + "import sys  # NOQA: F401\n")])
    fresh = _run([("src/new_mod.py", None, "import sys\n\nimport x  # NOQA: E402\n")],
                 accepted=("noqa: E402",))
    check("fa22 a string or docstring holding the marker gives no finding, and "
          "the marker in another letter case is the same code - beside the base's "
          "copy and against an accepted entry: %s / %s / %s"
          % ([_show(g) for g in got], _show(upper), _show(fresh)),
          [g["findings"] for g in got] == [[], []]
          and [g["answer"] for g in got] == [M.CLEAN, M.CLEAN]
          and upper["findings"] == [] and upper["answer"] == M.CLEAN
          and fresh["findings"] == [] and fresh["answer"] == M.CLEAN)


# --- a file counts as compared only when everything that could hold a move was --
# Each rule below is held from both sides: the deny case goes red when the rule is
# dropped, and its allow twin goes red when the rule widens into reporting honest
# work - a test appended, a reason reworded, a fixture added, a file moved.

def _binary_diff(path, added=False):
    """A file section as git prints a binary change: no hunk at all."""
    head = "diff --git a/%s b/%s\n" % (path, path)
    if added:
        return head + ("new file mode 100644\nindex 0000000..ba93eeb\n"
                       "Binary files /dev/null and b/%s differ\n" % (path,))
    return head + ("index 8ce3223..ba93eeb 100644\n"
                   "Binary files a/%s and b/%s differ\n" % (path, path))


def _binary(check):
    got = M.find_moves(_binary_diff("tests/Cart.Tests.cs"), lambda p: "x", lambda p: "y")
    listed = [n for n in got["notRead"] if n["path"] == "tests/Cart.Tests.cs"]
    check("fm35 a binary test file is listed as not read with the reason binary, as "
          "a file that could hold a move, and the answer is not clean: %s %r"
          % (_show(got), got.get("notRead")),
          got["answer"] == PARTLY_READ and len(listed) == 1
          and "binary" in listed[0]["reason"] and listed[0].get("kind") == COULD_HOLD
          and "1 of the diff" not in got["basis"])

    diff = (_binary_diff("tests/fixtures/logo.png", added=True)
            + _binary_diff("docs/shot.png"))
    got = M.find_moves(diff, lambda p: "x", lambda p: "y")
    check("fa23 THE TWIN: a binary fixture added and a binary image changed cannot "
          "hold a move: listed as not read of the first kind, and the answer stays "
          "clean: %s %r" % (_show(got), got.get("notRead")),
          got["answer"] == M.CLEAN and got["findings"] == []
          and sorted(n["path"] for n in got["notRead"]) == ["docs/shot.png",
                                                            "tests/fixtures/logo.png"]
          and all(n.get("kind") == CANNOT_HOLD for n in got["notRead"]))


SKIPPED_CLASS = """\
import sys
import unittest


@unittest.skipIf(sys.platform == 'win32', 'posix only')
class TestCart(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1, 1)

    def test_two(self):
        self.assertEqual(2, 2)
"""

MARKED_MODULE = """\
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='posix')


def test_one():
    assert 1 == 1


@pytest.mark.skip(reason='later')
def test_later():
    assert 2 == 2


def test_inline():
    if sys.platform == 'win32':
        pytest.skip('not on windows')
    assert 3 == 3
"""

JS_SKIPPED = """\
describe("cart", () => {
  it.skip("flaky one", () => {
    expect(1).toBe(1);
  });
  it("b", () => {
    expect(2).toBe(2);
  });
});
"""


def _skips(check):
    tree = SKIPPED_CLASS.replace("sys.platform == 'win32'", "True")
    got = _run([("tests/test_cart.py", SKIPPED_CLASS, tree)])
    whats = sorted(f["what"] for f in _moves(got, M.DEFINITION_CHANGED))
    check("fm36 a class's skip decorator widened is a change to each of its test "
          "methods: %s" % _show(got),
          len(whats) == 2 and "TestCart.test_one" in whats[0]
          and "TestCart.test_two" in whats[1] and got["answer"] == M.FINDINGS)

    tree = MARKED_MODULE.replace(
        "pytest.mark.skipif(sys.platform == 'win32', reason='posix')", "pytest.mark.skip")
    got = _run([("tests/test_cart.py", MARKED_MODULE, tree)])
    whats = [f["what"] for f in _moves(got, M.DEFINITION_CHANGED)]
    check("fm37 a module's pytestmark widened from skipif to skip is a change to "
          "every test it marks: %s" % _show(got),
          len(whats) == 3 and any("test_one" in w for w in whats))

    tree = JS_SKIPPED.replace('describe("cart"', 'describe.skip("cart"').replace(
        'it.skip("flaky one"', 'it("flaky one"')
    got = _run([("tests/cart.test.js", JS_SKIPPED, tree)])
    check("fm38 a JS skip moved from one call to its enclosing block is a new "
          "skip on the block's line, not paired away by kind: %s" % _show(got),
          [(f["line"], f["side"]) for f in _moves(got, M.SKIP_ADDED)] == [(1, "tree")])

    reworded = (
        ("tests/test_cart.py", SKIPPED_CLASS,
         SKIPPED_CLASS.replace("'posix only'", "'posix only, see the runner'")),
        ("tests/test_mark.py", MARKED_MODULE,
         MARKED_MODULE.replace("reason='posix')", "reason='posix hosts')")
         .replace("reason='later'", "reason='much later'")
         .replace("'not on windows'", "'never on windows'")),
        ("tests/cart.test.js", JS_SKIPPED,
         JS_SKIPPED.replace('it.skip("flaky one"', 'it.skip("flaky, see the issue"')))
    got = [_run([row]) for row in reworded]
    check("fa24 THE TWIN: a skip whose reason is reworded on its own line - on a "
          "class decorator, a module pytestmark, a test's marker, a call in its "
          "body, a JS it.skip - gives no finding and leaves the file compared: %s"
          % [_show(g) for g in got],
          [g["findings"] for g in got] == [[], [], []]
          and [g["answer"] for g in got] == [M.CLEAN] * 3
          and [g["notRead"] for g in got] == [[], [], []])


POSIX_GUARDED = """\
import sys

if sys.platform != 'win32':
    def test_posix():
        assert 1 == 1


def test_any():
    assert True
"""

API_TEST = """\
import pytest

CASES = [(1, 2), (2, 4), (0, 0), (-1, -2)]


def _assert_ok(resp):
    assert resp.status == 200
    assert resp.body == 'ok'


def test_get(client):
    _assert_ok(client.get('/'))


@pytest.mark.parametrize('a,b', CASES)
def test_double(a, b):
    assert a * 2 == b
"""


def _outside(check):
    got = _run([("tests/test_p.py", POSIX_GUARDED,
                 POSIX_GUARDED.replace("assert 1 == 1", "pass"))])
    check("fm39 a test defined under an if-block whose assertion is replaced is a "
          "definition change: %s" % _show(got),
          [f["what"] for f in _moves(got, M.DEFINITION_CHANGED)
           if "test_posix" in f["what"]] != [])

    gutted = API_TEST.replace("    assert resp.status == 200\n    assert resp.body == 'ok'\n",
                              "    return\n")
    cut = API_TEST.replace("[(1, 2), (2, 4), (0, 0), (-1, -2)]", "[(0, 0)]")
    seen = []
    for label, tree in (("helper gutted", gutted), ("table cut", cut)):
        got = _run([("tests/test_api.py", API_TEST, tree)])
        seen.append((label, got["answer"], [(n["path"], n["move"], n.get("kind"))
                                            for n in got["notRead"]], got["findings"]))
    check("fm40 a Python test file whose code outside its test definitions changed "
          "- a helper holding the assertions gutted, a parametrize table cut - is "
          "listed as not compared for the definition move, and the answer is not "
          "clean: %r" % (seen,),
          [s[1:] for s in seen] == [(PARTLY_READ, [("tests/test_api.py",
                                                      M.DEFINITION_CHANGED, COULD_HOLD)],
                                     [])] * 2)

    grown = ("import json\n" + API_TEST
             + "\n\ndef _assert_json(resp):\n    assert json.loads(resp.body)\n"
             + "\n\ndef test_json(client):\n    _assert_json(client.get('/j'))\n")
    reworded = API_TEST.replace("def _assert_ok(resp):\n",
                                "def _assert_ok(resp):\n    \"\"\"The answer is ok.\"\"\"\n"
                                ).replace("def test_get(client):\n",
                                          "def test_get(client):\n    # the root\n")
    got = [_run([("tests/test_api.py", API_TEST, t)]) for t in (grown, reworded)]
    check("fa25 THE TWIN: a test file whose helper gains a docstring and whose test "
          "gains a comment is compared and clean, listed nowhere; one that gains an "
          "import, a helper and a test is not compared - its code outside the tests "
          "was only added, named at the import: %s / %s"
          % (_show(got[0]), _show(got[1])),
          (got[1]["answer"], got[1]["findings"], got[1]["notRead"]) == (M.CLEAN, [], [])
          and got[0]["answer"] != M.CLEAN
          and _reason_says(got[0], "tests/test_api.py", "only added", "tree", 1,
                           "import json"))

    # Every base line of the helper stays; the one line added ends it before it
    # asserts anything, so an addition alone is not always harmless.
    early = API_TEST.replace("def _assert_ok(resp):\n",
                             "def _assert_ok(resp):\n    return\n")
    got = _run([("tests/test_api.py", API_TEST, early)])
    check("fm50 a `return` added at the top of a helper the base held is no mere "
          "addition: the file is listed as not compared and the answer is not "
          "clean: %s" % _show(got),
          got["answer"] == PARTLY_READ and got["findings"] == []
          and [(n["path"], n.get("kind")) for n in got["notRead"]]
          == [("tests/test_api.py", COULD_HOLD)])


HOUSE_SUITE = """\
import sys

import _harness


def _double(n):
    return n * 2


def _cases(check):
    got = _double(2)
    check("h1 two doubled is four: %r" % (got,), got == 4)
    check("h2 zero doubled is zero", _double(0) == 0)


def _selftest():
    return _harness.run(_cases)
"""


def _labelled(check):
    grown = HOUSE_SUITE.replace(
        '    check("h2 zero doubled is zero", _double(0) == 0)\n',
        '    check("h2 zero doubled is zero", _double(0) == 0)\n'
        '    one = _double(1)\n    check("h3 one doubled is two", one == 2)\n')
    got = _run([("tests/test_house.py", HOUSE_SUITE, grown)])
    check("fa26 a script-style suite that gains a labelled check and the set-up line "
          "before it gives no finding, and is not compared - the set-up line is code "
          "outside its checks, only added, named: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and got["findings"] == []
          and _reason_says(got, "tests/test_house.py", "only added", "tree", 14,
                           "one = _double(1)"))

    lost = HOUSE_SUITE.replace('    check("h2 zero doubled is zero", _double(0) == 0)\n', "")
    weak = HOUSE_SUITE.replace("_double(0) == 0)", "True)")
    got = [_run([("tests/test_house.py", HOUSE_SUITE, t)]) for t in (lost, weak)]
    hits = [[(f["side"], "h2" in f["what"]) for f in _moves(g, M.DEFINITION_CHANGED)]
            for g in got]
    check("fm41 a labelled check that is gone, and one whose condition changed, are "
          "each a definition change naming the label - on the base line and the "
          "tree line: %s / %s" % (_show(got[0]), _show(got[1])),
          hits == [[("base", True)], [("tree", True)]])

    helper = HOUSE_SUITE.replace("return n * 2", "return {2: 4, 0: 0}.get(n)")
    fixture = HOUSE_SUITE.replace("got = _double(2)", "got = 4")
    got = [_run([("tests/test_house.py", HOUSE_SUITE, t)]) for t in (helper, fixture)]
    check("fm42 a script-style suite whose code outside its labelled checks was "
          "changed - a helper, a line a check reads - is listed as not compared "
          "for the definition move: %s / %s" % (_show(got[0]), _show(got[1])),
          [[(n["path"], n["move"], n.get("kind")) for n in g["notRead"]] for g in got]
          == [[("tests/test_house.py", M.DEFINITION_CHANGED, COULD_HOLD)]] * 2
          and [g["answer"] for g in got] == [PARTLY_READ] * 2)

    renamed = HOUSE_SUITE.replace('"h2 zero doubled is zero"', '"h2 zero doubled stays zero"')
    said = HOUSE_SUITE.replace('% (got,), got == 4)', '% (got, 4), got == 4)')
    got = [_run([("tests/test_house.py", HOUSE_SUITE, t)]) for t in (renamed, said)]
    check("fa27 THE TWIN: a label reworded with its check unchanged, and the "
          "values a label prints changed, give no finding: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got]
          == [(M.CLEAN, [], [])] * 2)

    bare = _run([("tests/test_house.py", HOUSE_SUITE, weak)],
                declared=("tests/test_house.py",))
    named = _run([("tests/test_house.py", HOUSE_SUITE, weak)],
                 declared=("tests/test_house.py::h2",))
    check("fm43 a bare-path declaration does not cover a labelled check the base "
          "held; the case named by its id does: %s / %s" % (_show(bare), _show(named)),
          len(_moves(bare, M.DEFINITION_CHANGED)) == 1 and bare["declared"] == []
          and named["findings"] == [] and len(named["declared"]) == 1)


def _declarations(check):
    weak = CART_TEST.replace("assert total([1, 2]) == 3", "assert total([1, 2]) >= 0")
    grown = weak + "\n\ndef test_three():\n    assert total([1, 1, 1]) == 3\n"
    bare = _run([("tests/test_cart.py", CART_TEST, grown)],
                declared=("tests/test_cart.py",))
    check("fm44 a bare-path declaration covers the definition the task added and "
          "not the base test it weakened beside it: %s" % _show(bare),
          [("test_total" in f["what"]) for f in _moves(bare, M.DEFINITION_CHANGED)]
          == [True] and bare["declared"] == [] and bare["answer"] == M.FINDINGS)
    named = _run([("tests/test_cart.py", CART_TEST, grown)],
                 declared=("tests/test_cart.py::test_total",))
    check("fa28 THE TWIN: the same change declared by `path::test_total` is the "
          "task's own, and the reading says clean apart from declared changes: %s"
          % _show(named),
          named["findings"] == [] and len(named["declared"]) == 1
          and named["answer"] == M.CLEAN and "declared" in named["basis"])


SRC_PY = "import os\n\n\ndef f(x):\n    return os.path.join(x)\n"
SRC_JS = "function f(x) {\n  return x;\n}\n"


def _marker_kinds(check):
    prose = (("src/m.py", SRC_PY, "# the type: ignore that stood here is gone\n"),
             ("src/m.py", SRC_PY, "x = 1  # the type: ignore that stood here\n"),
             ("src/m.py", SRC_PY, "# never write pragma: no cover in this module\n"),
             ("src/m.py", SRC_PY, "x = 1  # never write pragma: no cover here\n"),
             ("src/m.py", SRC_PY, "# gitleaks:allow is not accepted here\n"),
             ("src/m.py", SRC_PY, "# see nosemgrep in the docs\n"),
             ("src/m.js", SRC_JS, "// the eslint-disable comment was removed on purpose\n"),
             ("src/m.js", SRC_JS, "x = 1; // the eslint-disable went\n"),
             ("src/m.js", SRC_JS, "// do not add @ts-ignore here\n"),
             ("src/m.js", SRC_JS, "// nor an @ts-expect-error\n"),
             ("src/m.js", SRC_JS, "// istanbul ignore comments are banned\n"),
             ("src/m.js", SRC_JS, "/* the istanbul ignore next comment went */\n"),
             ("src/m.js", SRC_JS, "// the Stryker disable comment went\n"))
    got = [(t, _run([(p, b, b + t)])) for p, b, t in prose]
    loud = [(t, _show(g)) for t, g in got if g["findings"] or g["answer"] != M.CLEAN]
    check("fa29 a prose comment that mentions a suppression - every kind, on a line "
          "of its own or after code - is no finding: %r" % (loud,), loud == [])

    marked = (("src/m.py", SRC_PY, "x = 1  # type: ignore\n"),
              ("src/m.py", SRC_PY, "x = 1  # pragma: no cover\n"),
              ("src/m.py", SRC_PY, "TOKEN = 'abc'  # gitleaks:allow\n"),
              ("src/m.py", SRC_PY, "x = run()  # nosemgrep: python.lang.x\n"),
              ("src/m.py", SRC_PY, "# nosemgrep\nx = run()\n"),
              ("src/m.js", SRC_JS, "// eslint-disable-next-line no-undef\nx = 1;\n"),
              ("src/m.js", SRC_JS, "/* eslint-disable */\n"),
              ("src/m.js", SRC_JS, "x = y; // @ts-ignore\n"),
              ("src/m.js", SRC_JS, "// @ts-expect-error\nx = y;\n"),
              ("src/m.js", SRC_JS, "/* istanbul ignore next */\n"),
              ("src/m.js", SRC_JS, "// Stryker disable next-line all\nx = 1;\n"))
    got = [(t, len(_moves(_run([(p, b, b + t)]), M.SUPPRESSION_ADDED))) for p, b, t in marked]
    check("fm45 each kind's marker where its checker reads it is still a "
          "suppression finding: %r" % (got,),
          [n for _t, n in got] == [1] * len(marked))


CS_TEST = """\
public class CartTests {
    [Fact]
    public void Totals() {
        Assert.Equal(3, Total(new[] {1, 2}));
    }
}
"""


def _other_languages(check):
    got = _run([("tests/CartTests.cs", CS_TEST, CS_TEST.replace(
        "        Assert.Equal(3, Total(new[] {1, 2}));\n", ""))])
    listed = [n for n in got["notRead"] if n["path"] == "tests/CartTests.cs"]
    check("fm46 a non-Python test file whose language has no assertion row that "
          "matched either copy is listed as not compared, never counted as "
          "compared: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and len(listed) == 1
          and listed[0].get("kind") == COULD_HOLD and "assert" in listed[0]["reason"])

    yml = "jobs:\n  test:\n    runs: pytest\n"
    data = _run([("tests/fixtures/ci.yml", yml, yml.replace("pytest", "pytest -q"))])
    js = _run([("tests/add.test.js", JS_TEST, JS_TEST.replace('it("adds"', 'it("sums"'))])
    check("fa30 THE TWIN: a data file under a test directory, and a JS test whose "
          "assertions matched a row, are compared and clean: %s / %s"
          % (_show(data), _show(js)),
          [(g["answer"], g["notRead"]) for g in (data, js)] == [(M.CLEAN, [])] * 2)


def _moved(check):
    got = _run([("tests/test_take.py", SKIPPED_CLASS, None),
                ("tests/unit/test_take.py", None, SKIPPED_CLASS)])
    check("fa31 a test file moved unchanged, printed as a deletion and an "
          "addition, is no deletion, and the skip it already carried is not "
          "read as added: %s" % _show(got),
          got["findings"] == [] and got["answer"] == M.CLEAN)

    tree = SKIPPED_CLASS + ("\n\n@unittest.skip('later')\nclass TestMore(unittest.TestCase):\n"
                            "    def test_three(self):\n        self.assertEqual(3, 3)\n")
    got = _run([("tests/test_take.py", SKIPPED_CLASS, None),
                ("tests/unit/test_take.py", None, tree)])
    check("fm47 a test file moved that also gained a skip reports the new skip "
          "alone, against the old copy: %s" % _show(got),
          [(f["move"], f["path"], f["line"]) for f in got["findings"]]
          == [(M.SKIP_ADDED, "tests/unit/test_take.py", 14)])

    got = _run([("tests/test_take.py", SKIPPED_CLASS, None),
                ("tests/test_other.py", None, "def test_x():\n    assert 1\n")])
    check("fm48 a test file deleted beside an unrelated new file is still a "
          "deletion: %s" % _show(got),
          [(f["move"], f["path"]) for f in _moves(got, M.TEST_DELETED)]
          == [(M.TEST_DELETED, "tests/test_take.py")])

    one = "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2 == 2\n"
    two = "def test_c():\n    assert 3 == 3\n"
    got = _run([("tests/test_one.py", one, one.replace(
        "\n\ndef test_b():\n    assert 2 == 2\n", "")),
        ("tests/test_two.py", two, two + "\n\ndef test_b():\n    assert 2 == 2\n")])
    house = HOUSE_SUITE.replace('    check("h2 zero doubled is zero", _double(0) == 0)\n', "")
    other = HOUSE_SUITE.replace("h1 two doubled", "h9 two doubled").replace(
        '"h2 zero doubled is zero", _double(0) == 0', '"h8 zero", _double(0) == 0')
    labels = _run([("tests/test_h1.py", HOUSE_SUITE, house),
                   ("tests/test_h2.py", other, other.replace(
                       '"h8 zero", _double(0) == 0)\n',
                       '"h8 zero", _double(0) == 0)\n'
                       '    check("h2 zero doubled is zero", _double(0) == 0)\n'))])
    check("fa32 a test function, and a labelled check, moved unchanged from one "
          "test file to the same position in another give no finding: %s / %s"
          % (_show(got), _show(labels)),
          got["findings"] == [] and labels["findings"] == [])

    # THE TWIN for fa32: the test that appears in the other file is a DIFFERENT
    # one, so the test gone from the first file was not moved anywhere.
    elsewhere = _run([("tests/test_one.py", one, one.replace(
        "\n\ndef test_b():\n    assert 2 == 2\n", "")),
        ("tests/test_two.py", two, two + "\n\ndef test_d():\n    assert 4 == 4\n")])
    check("fm49 THE TWIN: a test gone from one file while a different test is added "
          "to another is still a finding on the first file: %s" % _show(elsewhere),
          [(f["move"], f["path"]) for f in elsewhere["findings"]]
          == [(M.DEFINITION_CHANGED, "tests/test_one.py")]
          and elsewhere["renamed"] == [])


def _kinds(check):
    got = _run([("docs/notes.md", "a\n", "b\n"), ("tests/cart_test.lua", "a = 1\n", "a = 2\n"),
                ("src/app.lua", "a = 1\n", "a = 2\n"), ("tests/fixtures/rows.json", "[]\n", "[1]\n")])
    kinds = sorted((n["path"], n.get("kind")) for n in got["notRead"])
    check("fx2 every file not read says which kind it is: prose, data and a source "
          "file outside a test directory in a language read nowhere here cannot "
          "hold a move as read here; a test in such a language could: %r" % (kinds,),
          kinds == [("docs/notes.md", CANNOT_HOLD), ("src/app.lua", CANNOT_HOLD),
                    ("tests/cart_test.lua", COULD_HOLD),
                    ("tests/fixtures/rows.json", CANNOT_HOLD)]
          and got["answer"] == PARTLY_READ
          and M.MOVES == (M.TEST_DELETED, M.DEFINITION_CHANGED, M.SKIP_ADDED,
                          M.SUPPRESSION_ADDED, M.STUB_ADDED))
    docs = _run([("docs/notes.md", "a\n", "b\n"), ("src/cart.py", CART_SRC, CART_SRC + "\n")])
    check("fx3 THE TWIN: a diff of compared files and prose answers clean, the "
          "prose still listed: %s %r" % (_show(docs), docs["notRead"]),
          docs["answer"] == M.CLEAN
          and [n["path"] for n in docs["notRead"]] == ["docs/notes.md"])


# --- a unit is compared with its position ----------------------------------------
# A unit (a test definition or a labelled check) is compared with its position -
# the statements enclosing it, the part of each that holds it, and where it stands
# among the other statements there, read by pairing (see the section on pairing
# below) - and the file with everything outside its units
# (see the section on the rest below). Each input below lowers the bar while every
# unit's own text stays the same, so a reading that compares the units alone calls
# it clean.

ROWS_MAIN = '''import sys


def check(label, ok):
    if not ok:
        print("FAIL", label)
        sys.exit(1)


def main():
    x = 1 + 1
    check("r1 two is two", x == 2)
    check("r2 three is not two", x != 3)
    check("r3 list empty", [] == [])
    print("3/3 cases passed")


if __name__ == "__main__":
    main()
'''

ROWS_ARG = '''def main(check):
    x = 2
    check("c1 two", x == 2)
    check("c2 not three", x != 3)
    for n in (1, 2):
        check("c4 row %d" % n, n > 0)
'''

ROWS_CALLED = '''import sys

FAILED = []


def check(label, ok):
    if not ok:
        FAILED.append(label)


def main():
    check("c1 two", 1 + 1 == 2)
    check("c2 three", 1 + 2 == 3)
    check("c3 four", 2 + 2 == 4)
    sys.exit(1 if FAILED else 0)


main()
'''

MOVED_TEST = '''def test_one():
    assert 1 + 1 == 2


def test_two():
    assert [1, 2] == sorted([2, 1])
'''

SHARED_WORD = '''def main(check):
    check("empty list gives zero", len([]) == 0)
    check("empty string gives zero", len("") == 0)
'''

SHARED_METHOD = '''class TestA:
    def test_empty(self):
        assert len([]) == 0


class TestB:
    def test_empty(self):
        assert len("") == 0
'''


def _named_lines(result, path):
    """The could-hold not-compared entries for `path` whose reason names a line."""
    return [n for n in result["notRead"] if n["path"] == path
            and n.get("kind") == COULD_HOLD and re.search(r"\bline \d+", n.get("reason") or "")]


def _names_line(result, path, lines):
    return any(re.search(r"\bline %d\b" % ln, n["reason"])
               for n in _named_lines(result, path) for ln in lines)


def _labels_found(result, words, side=None):
    """For each word, how many definition-changed findings name it."""
    hits = _moves(result, M.DEFINITION_CHANGED)
    return [len([f for f in hits if w in f["what"] and (side is None or f["side"] == side)])
            for w in words]


def _wrapped(check):
    path = "tests/test_rows.py"
    checks = ('    check("r1 two is two", x == 2)\n'
              '    check("r2 three is not two", x != 3)\n'
              '    check("r3 list empty", [] == [])\n')
    nested = "".join("    " + ln + "\n" for ln in checks.splitlines())
    seen = []
    for head in ("    if False:\n", "    def _later():\n"):
        got = _run([(path, ROWS_MAIN, ROWS_MAIN.replace(checks, head + nested))])
        seen.append((head.strip(), _labels_found(got, ("r1", "r2", "r3")),
                     all("enclos" in f["what"] for f in got["findings"]),
                     _names_line(got, path, (12,)), _show(got)))
    check("fm51 (a) a row suite's labelled checks wrapped in `if False:`, and (b) "
          "moved into a function nothing calls, are each a definition change saying "
          "the enclosing statement changed, and the file is not compared at the "
          "added head line: %r" % (seen,),
          [s[1:4] for s in seen] == [([1, 1, 1], True, True)] * 2)

    one = '    check("r2 three is not two", x != 3)\n'
    seen = []
    for label, wrap, lines in (
            ("for over ()", "    for _row in ():\n    " + one, (13,)),
            ("try/except pass", "    try:\n    " + one + "    except Exception:\n"
             "        pass\n", (13, 15, 16))):
        got = _run([(path, ROWS_MAIN, ROWS_MAIN.replace(one, wrap))])
        seen.append((label, _labels_found(got, ("r1", "r2", "r3")),
                     _names_line(got, path, lines), _show(got)))
    check("fm52 (c) a check put under a for over an empty tuple, and (d) wrapped in a "
          "try whose except passes, is a definition change of that check alone - the "
          "check after it stays in place, the new statement only added before it - and "
          "the file is not compared at the added line: %r" % (seen,),
          [s[1:3] for s in seen] == [([0, 1, 0], True)] * 2)

    got = _run([(path, ROWS_ARG, ROWS_ARG.replace("(1, 2)", "(1,)"))])
    check("fm53 (e) the literal table a loop of checks iterates, cut from two entries "
          "to one, is a definition change of the check under it, and the file is not "
          "compared at the loop's line: %s %r" % (_show(got), got["notRead"]),
          _labels_found(got, ("c1", "c2", "c4")) == [0, 0, 1]
          and _names_line(got, path, (5,)))

    tree = ROWS_CALLED.replace("def main():", "def note(label, ok):\n    pass\n\n\n"
                               "def main():").replace('    check("', '    note("')
    got = _run([(path, ROWS_CALLED, tree)])
    check("fm54 (f) every call of the check function pointed at a new function "
          "that does nothing: each base check is gone, a finding on its base line: %s"
          % _show(got),
          _labels_found(got, ("c1", "c2", "c3"), side="base") == [1, 1, 1]
          and got["answer"] == M.FINDINGS)

    tree = ROWS_MAIN.replace("    x = 1 + 1\n", "    x = 1 + 1\n    sys.exit(0)\n")
    got = _run([(path, ROWS_MAIN, tree)])
    check("fm55 (g) a call of sys.exit added above the checks: the file is not "
          "compared, only added at that line - a statement added before a check "
          "leaves the check in place, so it is no finding: %s %r"
          % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and got["findings"] == []
          and _reason_says(got, path, "only added", "tree", 12, "sys.exit(0)"))

    base = ("import pytest\n\n\ndef test_plain():\n    assert 1 + 1 == 2\n\n\n"
            "for _n in (1, 2):\n    def test_looped(n=_n):\n"
            "        assert n * 2 == n + n and n < 5\n")
    got = _run([("tests/test_d.py", base,
                 base.replace("assert n * 2 == n + n and n < 5", "assert True"))])
    check("fm56 (h) a test defined inside a module-level for loop, its assertion "
          "removed, is a definition change: %s" % _show(got),
          _labels_found(got, ("test_looped",)) == [1] and got["answer"] == M.FINDINGS)


def _skip_spellings(check):
    base = ("import unittest\n\n\nclass TestA(unittest.TestCase):\n"
            "    def test_one(self):\n        self.assertEqual(1 + 1, 2)\n")
    tree = base.replace("class TestA(unittest.TestCase):\n",
                        "class TestA(unittest.TestCase):\n    @classmethod\n"
                        "    def setUpClass(cls):\n        raise unittest.SkipTest('later')\n\n")
    raised = _run([("tests/test_u.py", base, tree)])
    plain = "import pytest\n\n\ndef test_one():\n    assert 1 + 1 == 2\n"
    imported = _run([("tests/test_p.py", plain, plain.replace(
        "import pytest\n", "import pytest\n\npytest.importorskip('no_such_module')\n"))])
    check("fm57 (i) a raised unittest.SkipTest in a new setUpClass, and a module-level "
          "pytest.importorskip, are skip findings on their lines: %s / %s"
          % (_show(raised), _show(imported)),
          [f["line"] for f in _moves(raised, M.SKIP_ADDED)] == [7]
          and [f["line"] for f in _moves(imported, M.SKIP_ADDED)] == [3])


def _moved_out(check):
    weak = MOVED_TEST.replace("assert [1, 2] == sorted([2, 1])", "assert True")
    shapes = (
        ("renamed out of the test tree", [("tools/a_checks.py", MOVED_TEST, MOVED_TEST,
                                           "tests/test_a.py")]),
        ("deleted, its text added untracked outside it",
         [("tests/test_a.py", MOVED_TEST, None), ("tools/a_checks.py", None, MOVED_TEST)]),
        ("renamed out and weakened", [("tools/a_checks.py", MOVED_TEST, weak,
                                       "tests/test_a.py")]),
        ("renamed to a dot-disabled suffix", [("tests/test_a.py.disabled", MOVED_TEST,
                                               MOVED_TEST, "tests/test_a.py")]))
    seen = [(label, [(f["move"], f["path"]) for f in _moves(_run(rows), M.TEST_DELETED)])
            for label, rows in shapes]
    check("fm58 (j) a test file moved to a path that is not a test path - renamed, "
          "deleted and re-added untracked, renamed and weakened, renamed to a "
          "disabled suffix - is a test-deleted finding on the old path: %r" % (seen,),
          [s[1] for s in seen] == [[(M.TEST_DELETED, "tests/test_a.py")]] * 4)


def _ambiguous(check):
    path = "tests/test_r.py"
    weak = SHARED_WORD.replace('len("") == 0', "True")
    got = _run([(path, SHARED_WORD, weak)], declared=(path + "::empty",))
    hits = _moves(got, M.DEFINITION_CHANGED)
    check("fm59 (k) a declaration naming the first word two base checks share covers "
          "neither: the weakened check is a finding saying the declaration is "
          "ambiguous, never filed as declared: %s" % _show(got),
          len(hits) == 1 and "empty string" in hits[0]["what"]
          and "ambiguous" in hits[0]["what"] and got["declared"] == []
          and got["answer"] == M.FINDINGS)

    upath = "tests/test_c.py"
    weak = SHARED_METHOD.replace('assert len("") == 0', "assert True")
    bare = _run([(upath, SHARED_METHOD, weak)], declared=(upath + "::test_empty",))
    hits = _moves(bare, M.DEFINITION_CHANGED)
    check("fm60 a declaration naming a method two classes share covers neither, and "
          "the finding says it is ambiguous and that class and method would make it "
          "single: %s" % _show(bare),
          len(hits) == 1 and "TestB.test_empty" in hits[0]["what"]
          and "ambiguous" in hits[0]["what"] and bare["declared"] == [])

    gone = _run([("tests/test_a.py", MOVED_TEST, None),
                 ("docs/a_checks.py", None, MOVED_TEST)])
    kept = _run([("tests/test_a.py", MOVED_TEST, None),
                 ("tests/unit/test_a.py", None, MOVED_TEST)])
    check("fm61 a deleted test path is paired only with an added test path: beside a "
          "non-test path holding its text it is a deletion, beside a test path it is "
          "a move: %s / %s" % (_show(gone), _show(kept)),
          [(f["move"], f["path"]) for f in gone["findings"]]
          == [(M.TEST_DELETED, "tests/test_a.py")]
          and kept["findings"] == [] and kept["answer"] == M.CLEAN)


def _honest(check):
    path = "tests/test_rows.py"
    house = HOUSE_SUITE.replace(
        '    check("h2 zero doubled is zero", _double(0) == 0)\n',
        '    check("h2 zero doubled is zero", _double(0) == 0)\n'
        '    a = _double(3)\n    b = a + 1\n    c = b - 1\n'
        '    check("h3 three doubled is six", c == 6)\n')
    tail = ROWS_MAIN.replace(
        '    check("r3 list empty", [] == [])\n',
        '    check("r3 list empty", [] == [])\n    y = x * 2\n    z = y + 1\n'
        '    w = z - 1\n    check("r4 four", w == 4)\n')
    got = [_run([(path, b, t)]) for b, t in ((HOUSE_SUITE, house), (ROWS_MAIN, tail))]
    check("fa33 THE TWIN of fm55: a check appended after the last existing one with "
          "three set-up lines of its own - at the end of the body, and before a "
          "trailing print - gives no finding, and is not compared at the first set-up "
          "line, only added: %s / %s" % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"]) for g in got] == [(PARTLY_READ, [])] * 2
          and _reason_says(got[0], path, "only added", "tree", 14, "a = _double(3)")
          and _reason_says(got[1], path, "only added", "tree", 15, "y = x * 2"))

    tree = ROWS_MAIN.replace("def main():", "def triple(n):\n    return n * 3\n\n\n"
                             "def main():")
    got = _run([(path, ROWS_MAIN, tree)])
    check("fa34 THE TWIN of fm54: a new helper function under a fresh name gives no "
          "finding, and is not compared - only added, named: %s %r"
          % (_show(got), got["notRead"]),
          (got["answer"], got["findings"]) == (PARTLY_READ, [])
          and _reason_says(got, path, "only added", "tree", 10, "def triple(n):"))

    tree = SKIPPED_CLASS.replace("    def test_two(self):",
                                 "    def test_one_half(self):\n"
                                 "        self.assertEqual(3, 3)\n\n"
                                 "    def test_two(self):")
    got = _run([("tests/test_cart.py", SKIPPED_CLASS, tree)])
    check("fa35 THE TWIN of fm57: a new test method between two existing ones is a "
          "new unit and reads clean: %s %r" % (_show(got), got["notRead"]),
          (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], []))

    reflowed = ROWS_ARG.replace('    check("c2 not three", x != 3)\n',
                                '    check(\n        "c2 not three",\n'
                                '        x != 3,\n    )\n')
    test = CART_TEST.replace("    assert total([1, 2]) == 3\n",
                             "    assert (\n        total([1, 2])\n        == 3\n    )\n")
    got = [_run([(path, ROWS_ARG, reflowed)]), _run([("tests/test_cart.py", CART_TEST, test)])]
    check("fa36 THE TWIN of fm51: a pure reformat - a check's arguments split over "
          "lines, a test's assertion reflowed - reads clean: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got]
          == [(M.CLEAN, [], [])] * 2)

    tree = ROWS_ARG.replace('"c4 row %d"', '"c4 table row %d"')
    got = _run([(path, ROWS_ARG, tree)])
    check("fa37 THE TWIN of fm53: a label reworded under its loop, the condition and "
          "the loop untouched, reads clean: %s %r" % (_show(got), got["notRead"]),
          (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], []))

    got = [_run([("tests/unit/test_rows.py", ROWS_MAIN, ROWS_MAIN, path)]),
           _run([(path, ROWS_MAIN, None), ("tests/unit/test_rows.py", None, ROWS_MAIN)])]
    check("fa38 THE TWIN of fm58: a test file moved to another test path unchanged - "
          "renamed, or deleted and re-added - reads clean: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"]) for g in got] == [(M.CLEAN, [])] * 2)

    weak = SHARED_WORD.replace('len("") == 0', "True")
    whole = _run([("tests/test_r.py", SHARED_WORD, weak)],
                 declared=("tests/test_r.py::empty string gives zero",))
    uweak = SHARED_METHOD.replace('assert len("") == 0', "assert True")
    qualified = _run([("tests/test_c.py", SHARED_METHOD, uweak)],
                     declared=("tests/test_c.py::TestB::test_empty",))
    check("fa39 THE TWIN of fm59 and fm60: a declaration answering to one base unit - "
          "the whole label, or class and method - covers it: %s / %s"
          % (_show(whole), _show(qualified)),
          [(g["answer"], g["findings"], len(g["declared"])) for g in (whole, qualified)]
          == [(M.CLEAN, [], 1)] * 2)


UNIT_SUITE = '''import unittest


class TestA(unittest.TestCase):
    def test_two(self):
        self.assertEqual(sorted([2, 1]), [1, 2])


if __name__ == "__main__":
    unittest.main()
'''


def _not_inert(check):
    path = "tests/test_unit.py"
    hook = UNIT_SUITE.replace('\n\nif __name__', '\n\ndef load_tests(loader, tests, pattern):\n'
                              '    return unittest.TestSuite()\n\n\nif __name__')
    decorated = UNIT_SUITE.replace('\n\nif __name__', '\n\n@unittest.skip("x")\ndef helper():\n'
                                   '    return 1\n\n\nif __name__')
    shadow = UNIT_SUITE.replace('\n\nif __name__', '\n\ndef sorted(xs):\n    return [1, 2]\n'
                                '\n\nif __name__')
    attribute = UNIT_SUITE.replace("class TestA(unittest.TestCase):\n",
                                   "class TestA(unittest.TestCase):\n"
                                   "    __unittest_skip__ = True\n")
    seen = []
    for label, tree, line in (("a load_tests hook", hook, 9), ("a decorated helper", decorated, 9),
                              ("a def shadowing a name the base reads", shadow, 9),
                              ("a class-level assignment", attribute, 5)):
        got = _run([(path, UNIT_SUITE, tree)])
        seen.append((label, got["answer"] != M.CLEAN, _names_line(got, path, (line,)), _show(got)))
    conftest = _run([(path, UNIT_SUITE, UNIT_SUITE),
                     ("tests/conftest.py", None, "def pytest_collection_modifyitems(config, items):"
                                                 "\n    items[:] = []\n")])
    seen.append(("a new conftest.py defining a pytest hook", conftest["answer"] != M.CLEAN,
                 _names_line(conftest, "tests/conftest.py", (1,)), _show(conftest)))
    plain = "import os\n\n\ndef test_one():\n    assert os.sep\n"
    hidden = _run([("tests/test_plain.py", plain, plain.replace(
        "def test_one():\n    assert os.sep\n",
        "def _hidden():\n    def test_one():\n        assert os.sep\n"))])
    seen.append(("a new fresh function holding an existing test", hidden["answer"] != M.CLEAN,
                 _names_line(hidden, "tests/test_plain.py", (4,)), _show(hidden)))
    check("fm62 an addition is not inert when it is a hook-named definition, a decorated "
          "one, one under a name the base copy reads, a class-level assignment, or one "
          "holding a test the base had - in an existing test file - or a hook in a test "
          "file new to the diff: the file is not compared at its line: %r" % (seen,),
          [s[1:3] for s in seen] == [(True, True)] * 6)


def _inert_twins(check):
    fresh = ("import sys\n\nimport unittest\n\n\ndef _setup_paths():\n    sys.path.insert(0, '.')\n"
             "\n\nclass TestNew(unittest.TestCase):\n    def test_new(self):\n"
             "        self.assertEqual(1 + 1, 2)\n\n\nif __name__ == '__main__':\n"
             "    unittest.main()\n")
    new_file = _run([("tests/test_new.py", None, fresh)])
    catches = UNIT_SUITE.replace('\n\nif __name__', '\n    def test_three(self):\n        try:\n'
                                 '            self.assertTrue(True)\n'
                                 '        except unittest.SkipTest:\n            raise\n'
                                 '\n\nif __name__')
    caught = _run([("tests/test_unit.py", UNIT_SUITE, catches)])
    caller = ROWS_ARG + "\n\ndef _all(check):\n    main(check)\n"
    table = caller.replace("def _all(check):", "def more(check):\n    check(\"m1 eight\", "
                           "2 * 4 == 8)\n\n\ndef _all(check):") + "    more(check)\n"
    grouped = _run([("tests/test_rows.py", caller, table)])
    check("fa40 THE TWIN of fm62: a new test that catches SkipTest without raising one "
          "reads clean; a new test file with module code of its own, and a new group "
          "of checks called after every statement its caller had, give no finding and "
          "are not compared - their code outside the units only added, named: "
          "%s / %s / %s" % (_show(new_file), _show(caught), _show(grouped)),
          (caught["answer"], caught["findings"], caught["notRead"]) == (M.CLEAN, [], [])
          and [(g["answer"], g["findings"]) for g in (new_file, grouped)]
          == [(PARTLY_READ, [])] * 2
          and _reason_says(new_file, "tests/test_new.py", "only added", "tree", 1,
                           "import sys")
          and _reason_says(grouped, "tests/test_rows.py", "only added", "tree", 9,
                           "def more(check):"))


# --- the invariant, computed by the case itself ----------------------------------
# The expected reading of each generated edit is derived here by a route that
# shares nothing with the module: each copy's units are found by this file's own
# walk, their line spans are overwritten in the SOURCE TEXT by a placeholder
# name, and the two texts' `ast.dump`s, placeholders deleted, are compared. Which
# of the two kinds a difference is comes from deleting the tree statements whose
# every line difflib calls inserted and comparing again; a unit's position is the
# same dump with only that unit marked - and, where the rest was only added, with
# those inserted statements taken out of the tree copy first, so a statement added
# above a unit does not move it. A fixed table of edit operators is applied
# at every statement position of two small fixtures, so the edits and their count
# are reproducible.

INV_ROWS = '''import sys

LIMIT = 3


def _helper(v):
    if v > 1:
        out = v * 2
        out = out + 1
    else:
        out = v
        out = out - 2
    try:
        out = int(out)
        out = out - 1
    except ValueError:
        out = 0
        out = out + 5
    return out


def _cases(check):
    x = 2
    check("alpha two", x == 2)
    check("delta three", x + 1 == 3)
    for n in (1, 2):
        check("beta row %d" % n, n < 3)
        check("theta row %d" % n, n > 0)
    if x > 1:
        y = x
        check("eps big", y > 1)
    else:
        check("eta small", x <= 1)
    check("gamma limit", LIMIT == 3)
    for n in (1, 2):
        check("iota row %d" % n, n != 0)
    print("done", 4)


def main():
    return _cases(print)
'''

INV_UNIT = '''import unittest

BASE = 2


def _helper(tc, v):
    if v > 1:
        tc.assertEqual(v, 2)
        v = v + 1
    else:
        v = 0
        v = v - 3
    try:
        tc.assertTrue(v)
        v = v - 1
    except KeyError:
        v = 0
        v = v + 7
    return v


class TestA(unittest.TestCase):
    def setUp(self):
        self.x = 2

    def test_one(self):
        self.assertEqual(self.x, 2)

    def test_two(self):
        self.assertTrue(BASE < 3)

    def test_three(self):
        _helper(self, self.x)


if BASE > 1:
    def test_four():
        assert BASE == 2

    def test_five():
        assert BASE > 0


SECOND = BASE + 1

if BASE > 1:
    def test_six():
        assert SECOND == 3
'''

INV_HOLE = "__inv_hole__"
INV_ME = "__inv_me__"
INV_HOLE_DUMP = ast.dump(ast.parse(INV_HOLE).body[0])


def _inv_walk(tree, rows):
    """(node, name or None, parent body) for every statement outside a unit,
    outermost first, and for every unit - whose inside is not walked. A unit is
    a call of `check` with a string label in a row suite, or a def named with
    the test prefix in a unittest file, qualified by its classes."""
    out = []

    def visit(body, cls):
        for node in body:
            name = None
            if rows and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == "check" \
                    and node.value.args:
                label = node.value.args[0]
                label = label.left if isinstance(label, ast.BinOp) else label
                if isinstance(label, ast.Constant) and isinstance(label.value, str):
                    name = label.value
            if not rows and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test"):
                name = cls + node.name
            out.append((node, name, body))
            if name is not None:
                continue
            inner = cls + node.name + "." if isinstance(node, ast.ClassDef) else cls
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(node, field, None) or [], inner)
            for handler in getattr(node, "handlers", None) or []:
                visit(handler.body, inner)
    visit(tree.body, "")
    return out


def _inv_span(node):
    first = min([d.lineno for d in getattr(node, "decorator_list", ())] + [node.lineno])
    return first, node.end_lineno


def _inv_fill(lines, spans, word):
    """`lines` with each (first, last) span overwritten: `word` on the first line
    at that line's indentation, the rest blank - so line numbers stay."""
    out = list(lines)
    for first, last in spans:
        pad = out[first - 1][:len(out[first - 1]) - len(out[first - 1].lstrip())]
        out[first - 1] = pad + word + "\n"
        for ln in range(first + 1, last + 1):
            out[ln - 1] = "\n"
    return out


def _inv_dump(lines):
    dump = ast.dump(ast.parse("".join(lines)))
    return dump.replace(INV_HOLE_DUMP + ", ", "").replace(", " + INV_HOLE_DUMP, "").replace(
        INV_HOLE_DUMP, "")


def _inv_copy(text, rows):
    """{lines, units: {name: (own dump, position dump, first line)}, holed, rest}."""
    lines = text.splitlines(True)
    walked = _inv_walk(ast.parse(text), rows)
    units = [(node, name) for node, name, _b in walked if name is not None]
    holed = _inv_fill(lines, [_inv_span(n) for n, _nm in units], INV_HOLE)
    found = {}
    for node, name in units:
        marked = _inv_fill(holed, [_inv_span(node)], INV_ME)
        found[name] = (ast.dump(node), _inv_dump(marked), node.lineno)
    return {"lines": lines, "units": found, "holed": holed, "rest": _inv_dump(holed),
            "rows": rows, "spans": dict((name, _inv_span(node)) for node, name in units)}


def _inv_lost(base, tree, gone):
    """The base units with no twin of the same name, own syntax and position in
    the tree copy once the statements spanning `gone` are taken out of it; a twin
    inside one of them went with it."""
    lines = _inv_fill(tree["holed"], gone, INV_HOLE) if gone else tree["holed"]
    lost = []
    for name, unit in base["units"].items():
        span = tree["spans"].get(name)
        if span is None or tree["units"][name][0] != unit[0] \
                or any(g[0] <= span[0] and span[1] <= g[1] for g in gone) \
                or _inv_dump(_inv_fill(lines, [span], INV_ME)) != unit[1]:
            lost.append(name)
    return sorted(lost)


def _inv_added(base, tree):
    """The spans of the outermost tree statements outside the units whose every
    line difflib calls inserted, and whether deleting them leaves the base copy's
    rest - ONLY ADDED - or not."""
    inserted = set()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, base["holed"], tree["holed"], autojunk=False).get_opcodes():
        if tag != "equal":
            inserted.update(range(j1 + 1, j2 + 1))
    gone = []

    def visit(body):
        for node in body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Name) \
                    and node.value.id == INV_HOLE:
                continue
            first, last = _inv_span(node)
            code = [ln for ln in range(first, last + 1) if tree["holed"][ln - 1].strip()
                    and tree["holed"][ln - 1].strip() != INV_HOLE]
            if code and set(code) <= inserted:
                gone.append((first, last))
                continue
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(node, field, None) or [])
            for handler in getattr(node, "handlers", None) or []:
                visit(handler.body)
    visit(ast.parse("".join(tree["holed"])).body)
    left = _inv_dump(_inv_fill(tree["holed"], gone, INV_HOLE)) if gone else None
    return gone, left == base["rest"]


def _inv_expect(base, tree):
    """("only added", (lines, names lost)) / ("changed or removed", None) when the
    rest differs; ("findings", names) when it is the same and a base unit has no
    twin of the same name, own syntax and position; ("clean", None) otherwise."""
    if base["rest"] != tree["rest"]:
        gone, only = _inv_added(base, tree)
        if not only:
            return ("changed or removed", None)
        return ("only added", ([g[0] for g in gone], _inv_lost(base, tree, gone)))
    lost = _inv_lost(base, tree, [])
    return ("findings", lost) if lost else ("clean", None)


def _inv_move(lines, node, body, parts):
    """Each statement at the edge of an if's or a try's part moved across into
    the neighbouring part: the last of the body to the head of the else or the
    first handler, and back. None when it is not at such an edge, or would leave
    a part empty."""
    first, last = _inv_span(node)
    seg = lines[first - 1:last]
    for kind, here, there, there_head in parts:
        if body is here and node is here[-1] and len(here) > 1:
            head = there_head
            return lines[:first - 1] + lines[last:head] + seg + lines[head:]
        if body is there and node is there[0] and len(there) > 1:
            end = here[-1].end_lineno
            return lines[:end] + seg + lines[end:first - 1] + lines[last:]
    return None


def _inv_parts(tree):
    """(kind, body, other part, the other part's head line) for each if with an
    else and each try with a handler."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.orelse:
            out.append(("if", node.body, node.orelse, node.orelse[0].lineno - 1))
        elif isinstance(node, ast.Try) and node.handlers:
            out.append(("try", node.body, node.handlers[0].body, node.handlers[0].lineno))
    return out


def _inv_same_heads(tree, lines):
    """(block, other block) for every two compound statements of one body whose
    head lines read the same, definitions apart."""
    out = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if not isinstance(body, list):
                continue
            heads = [s for s in body if isinstance(s, (ast.If, ast.For, ast.While, ast.With))]
            out.extend((a, b) for a in heads for b in heads
                       if a is not b and lines[a.lineno - 1] == lines[b.lineno - 1])
    return out


def _inv_rehome(lines, node, a, b):
    """`node`, a statement of block `a`'s body, moved to the end of block `b`'s
    body when `b` comes later, to its start when earlier. None when it would leave
    `a`'s body empty."""
    if not any(n is node for n in a.body) or len(a.body) < 2:
        return None
    first, last = _inv_span(node)
    seg, rest = lines[first - 1:last], lines[:first - 1] + lines[last:]
    at = (b.body[-1].end_lineno - len(seg)) if b.lineno > a.lineno \
        else _inv_span(b.body[0])[0] - 1
    return rest[:at] + seg + rest[at:]


def _inv_edits(text, rows):
    """(operator, edited text) for every operator of the table at every
    statement position of `text`, units included, each edit once."""
    lines = text.splitlines(True)
    tree = ast.parse(text)
    parts = _inv_parts(tree)
    twins = _inv_same_heads(tree, lines)
    unit = ('check("zeta new", 1 == 1)\n',) if rows else (
        "def test_zeta(self=None):\n", "    self = 1\n")
    edits = []
    for node, _name, body in _inv_walk(tree, rows):
        first, last = _inv_span(node)
        pad = " " * node.col_offset

        def put(at, stmt):
            return lines[:at] + [pad + s for s in stmt] + lines[at:]
        edits.append(("an inserted call", put(first - 1, ("sys.exit(0)\n",))))
        edits.append(("an inserted assignment of a call",
                      put(first - 1, ("_q = setattr(sys, 'flags', None)\n",))))
        edits.append(("a new def whose default is a call",
                      put(first - 1, ("def _fresh(x=sys.exit(0)):\n", "    return x\n"))))
        edits.append(("a set-up line inserted before it", put(first - 1, ("_k = 0\n",))))
        for a, b in twins:
            rehomed = _inv_rehome(lines, node, a, b)
            if rehomed is not None:
                edits.append(("moved into another block whose head reads the same", rehomed))
        edits.append(("a new unit after it", put(last, unit)))
        edits.append(("wrapped under a new condition",
                      lines[:first - 1] + [pad + "if LIMIT > 9:\n"]
                      + ["    " + ln if ln.strip() else ln for ln in lines[first - 1:last]]
                      + lines[last:]))
        k = next(i for i, n in enumerate(body) if n is node)
        if k > 0:
            p_first, p_last = _inv_span(body[k - 1])
            edits.append(("moved above the statement before it",
                          lines[:p_first - 1] + lines[first - 1:last] + lines[p_last:first - 1]
                          + lines[p_first - 1:p_last] + lines[last:]))
        moved = _inv_move(lines, node, body, parts)
        if moved is not None:
            edits.append(("moved between the parts of an if or a try", moved))
        edits.append(("a pure reformat", lines[:first - 1] + [pad + "# reformatted\n", "\n"]
                      + [lines[first - 1].rstrip("\n") + "  # same\n"] + lines[first:]))
    out, seen = [], set()
    for op, edit in edits:
        joined = "".join(edit)
        if joined != text and joined not in seen:
            seen.add(joined)
            out.append((op, joined))
    return out


def _inv_agrees(expect, got, path):
    """Whether the guard's reading `got` is the one `expect` computed."""
    kind, detail = expect
    listed = [n for n in got["notRead"] if n["path"] == path and n.get("kind") == COULD_HOLD]
    named = sorted(f["what"].split("`")[1] for f in got["findings"])
    if kind in ("only added", "changed or removed"):
        other = "changed or removed" if kind == "only added" else "only added"
        said = [n["reason"] for n in listed if kind in n["reason"] and other not in n["reason"]]
        at = [int(m) for r in said for m in re.findall(
            r"\b%s line (\d+)" % ("tree" if kind == "only added" else "base"), r)]
        lines, lost = detail if detail is not None else (None, None)
        return (got["answer"] in (M.FINDINGS, PARTLY_READ) and len(said) == 1
                and len(at) == 1 and (lines is None or at[0] in lines)
                and (lost is None or named == lost))
    if kind == "findings":
        return got["answer"] == M.FINDINGS and listed == [] and named == detail
    return (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], [])


def _invariant(check):
    tally = collections.Counter()
    wrong = []
    for path, base_text, rows in (("tests/test_inv_rows.py", INV_ROWS, True),
                                  ("tests/test_inv_unit.py", INV_UNIT, False)):
        base = _inv_copy(base_text, rows)
        for op, tree_text in _inv_edits(base_text, rows):
            tally["made"] += 1
            try:
                expect = _inv_expect(base, _inv_copy(tree_text, rows))
            except SyntaxError:
                tally["unparsed"] += 1
                continue
            tally[expect[0]] += 1
            tally[(op, expect[0])] += 1
            got = _run([(path, base_text, tree_text)])
            if not _inv_agrees(expect, got, path):
                wrong.append((path, op, expect, [ln for ln in difflib.unified_diff(
                    base_text.splitlines(), tree_text.splitlines(), n=0, lineterm="")
                    if ln[:1] in "+-" and ln[:3] not in ("+++", "---")],
                    _show(got), [n.get("reason") for n in got["notRead"]]))
    setup = tally[("a set-up line inserted before it", "only added")]
    rehomed = tally[("moved into another block whose head reads the same", "findings")]
    check("fx4 over %d generated edits (%d not parsing, skipped) the guard agrees with "
          "the case's own tree comparison - %d only added, %d changed or removed, %d "
          "with a base unit lost or moved, %d clean; %d set-up lines inserted before a "
          "statement read as only added, %d units moved into a block whose head reads "
          "the same read as moved: wrong %d: %s"
          % (tally["made"], tally["unparsed"], tally["only added"],
             tally["changed or removed"], tally["findings"], tally["clean"], setup, rehomed,
             len(wrong), some_of(wrong, render=repr)),
          wrong == [] and setup > 0 and rehomed > 0
          and all(tally[k] > 0 for k in ("only added", "changed or removed",
                                         "findings", "clean")))


def _nested_helper(check):
    # A function nested in another body is not one the runner collects, whatever
    # its name, so a helper named with the test prefix inside a row suite's
    # cases function must not turn the file into a file of test definitions -
    # which would leave every labelled check of it uncompared.
    helper = ROWS_MAIN.replace("def main():\n    x = 1 + 1\n",
                               "def main():\n    def tests_of(n):\n        return [n]\n\n"
                               "    x = 1 + 1\n")
    weak = helper.replace("x != 3)", "True)")
    both = _run([("tests/test_rows.py", helper, weak)])
    grown = _run([("tests/test_rows.py", ROWS_MAIN, weak)])
    seen = [[f["side"] for f in _moves(g, M.DEFINITION_CHANGED)
             if "r2" in f["what"] and "differs" in f["what"]] for g in (both, grown)]
    check("fm63 a row suite holding a helper named with the test prefix inside a "
          "function is still read by its labelled checks: a weakened check is a "
          "definition change naming it as changed, with the helper in both copies "
          "and with it new to the tree: %s / %s" % (_show(both), _show(grown)),
          seen == [["tree"], ["tree"]] and len(both["findings"]) == 1)


# --- the rest is the same, and every unit has its twin ---------------------------
# A Python test file is compared only when its tree with the units taken out is
# the same in both copies and every base unit has a twin in the tree copy. Each
# deny input below was measured clean on a real repository through the drive's
# diff before the rule changed; the reading must now name the statement.

UNIT_TWO = '''import unittest


class TestA(unittest.TestCase):
    def setUp(self):
        self.x = 2

    def test_two(self):
        self.assertEqual(self.x, 2)

    def test_three(self):
        self.assertNotEqual(self.x, 3)


if __name__ == "__main__":
    unittest.main()
'''

HELPER_BRANCH = '''import unittest


def _verify(tc, value, fast):
    if fast:
        out = value * 2
        tc.assertEqual(out, 4)
    else:
        out = value * 3
    return out


class TestA(unittest.TestCase):
    def test_fast(self):
        _verify(self, 2, True)

    def test_slow(self):
        _verify(self, 2, False)
'''

HELPER_TRY = HELPER_BRANCH.replace(
    "    if fast:\n        out = value * 2\n        tc.assertEqual(out, 4)\n"
    "    else:\n        out = value * 3\n",
    "    try:\n        out = value * 2\n        tc.assertEqual(out, 4)\n"
    "    except KeyError:\n        out = None\n")


def _not_compared(result, path):
    """The could-hold not-compared entries listed for `path`."""
    return [n for n in result["notRead"] if n["path"] == path and n.get("kind") == COULD_HOLD]


def _reason_says(result, path, word, side, line, text):
    """True when `path` is listed as not compared with a reason holding `word`,
    `<side> line <line>` and the statement's own text - and never the other word."""
    other = "changed or removed" if word == "only added" else "only added"
    return any(word in n["reason"] and other not in n["reason"] and text in n["reason"]
               and re.search(r"\b%s line %d\b" % (side, line), n["reason"])
               for n in _not_compared(result, path))


def _rest_deny(check):
    path, upath, hpath = "tests/test_rows.py", "tests/test_unit.py", "tests/test_help.py"
    verdict = "    sys.exit(1 if FAILED else 0)\n"
    got = _run([(path, ROWS_CALLED, ROWS_CALLED.replace(verdict, "    FAILED.clear()\n"
                                                         + verdict))])
    check("fm64 (a) a statement clearing the failures, added after the last check and "
          "before the existing verdict line, is not compared: only added, named at its "
          "line: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and got["findings"] == []
          and _reason_says(got, path, "only added", "tree", 15, "FAILED.clear()"))

    got = _run([(path, ROWS_CALLED, ROWS_CALLED.replace(
        "        FAILED.append(label)\n", "        FAILED.append(label)\n    FAILED.clear()\n"))])
    check("fm65 (b) the same statement appended to the body of the check function every "
          "check calls is not compared, named at its line: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ
          and _reason_says(got, path, "only added", "tree", 9, "FAILED.clear()"))

    seen = []
    for label, added, text in (
            ("a fresh name bound to a call ending the run", "_stop = sys.exit(0)\n", "_stop"),
            ("a new class whose body ends the run", "class _Quiet:\n    sys.exit(0)\n\n\n",
             "_Quiet"),
            ("a new def whose default ends the run",
             "def _later(x=sys.exit(0)):\n    return x\n\n\n", "_later")):
        got = _run([(path, ROWS_CALLED, ROWS_CALLED.replace("\n\nmain()\n",
                                                            "\n\n" + added + "main()\n"))])
        seen.append((label, got["answer"] == PARTLY_READ,
                     _reason_says(got, path, "only added", "tree", 18, text), _show(got)))
    check("fm66 (c) a call ending the run in a new binding - a fresh name, a class body, "
          "an argument's default - is not compared, named at its line: %r" % (seen,),
          [s[1:3] for s in seen] == [(True, True)] * 3)

    rows = _run([(path, ROWS_CALLED, ROWS_CALLED.replace(
        "\n\nmain()\n", "\n\n_q = setattr(sys.modules[__name__], 'check', "
                        "lambda label, ok: None)\nmain()\n"))])
    unit = _run([(upath, UNIT_TWO, UNIT_TWO.replace(
        "\n\nclass TestA", "\n\n_x = setattr(unittest.TestCase, 'assertEqual', "
                           "lambda *a, **k: None)\n\n\nclass TestA"))])
    check("fm67 (d) a fresh name bound to a call replacing the check function, or an "
          "assertion method of the framework, by one that does nothing is not compared, "
          "named at its line: %s %r / %s %r" % (_show(rows), rows["notRead"], _show(unit),
                                                 unit["notRead"]),
          rows["answer"] == PARTLY_READ and unit["answer"] == PARTLY_READ
          and _reason_says(rows, path, "only added", "tree", 18, "_q = setattr")
          and _reason_says(unit, upath, "only added", "tree", 4, "_x = setattr"))

    got = _run([(upath, UNIT_TWO, UNIT_TWO.replace(
        "    def setUp(self):", "    def _callTestMethod(self, method):\n        pass\n\n"
                               "    def setUp(self):"))])
    check("fm68 (e) a new method under a name the framework calls on every test, the "
          "suite naming it nowhere, is not compared, named at its line - and the tests "
          "after it stay in place, no finding: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and got["findings"] == []
          and _reason_says(got, upath, "only added", "tree", 5, "_callTestMethod"))

    suite = ('def main(check):\n    check("c1 two", 1 + 1 == 2)\n'
             '    check("c2 three", 1 + 2 == 3)\n    check("c3 four", 2 + 2 == 4)\n')
    cut = suite.replace('    check("c3 four", 2 + 2 == 4)\n', "")
    seen = []
    for label, new in (
            ("under a condition never true",
             'def main(check):\n    if False:\n        check("c3 four", 2 + 2 == 4)\n'),
            ("inside a function nothing calls",
             'def _never(check):\n    check("c3 four", 2 + 2 == 4)\n\n\n'
             'def main(check):\n    pass\n')):
        got = _run([("tests/test_a.py", suite, cut), ("tests/test_b.py", None, new)])
        seen.append((label, got["answer"],
                     [(f["path"], f["side"], "c3" in f["what"]) for f in got["findings"]],
                     [r for r in got.get("renamed") or () if "c3" in r.get("from", "")],
                     _show(got)))
    check("fm69 (f) a labelled check cut from one suite and placed in a new file of the "
          "diff under a dead condition, or in a function nothing calls, is gone from the "
          "first file - a finding on its base line, never paired as a move: %r" % (seen,),
          [s[1:4] for s in seen] == [(M.FINDINGS, [("tests/test_a.py", "base", True)], [])] * 2)

    seen = []
    for label, base, tree in (
            ("from an if body into its else", HELPER_BRANCH, HELPER_BRANCH.replace(
                "        tc.assertEqual(out, 4)\n    else:\n",
                "    else:\n        tc.assertEqual(out, 4)\n")),
            ("from a try body into its except handler", HELPER_TRY, HELPER_TRY.replace(
                "        tc.assertEqual(out, 4)\n    except KeyError:\n",
                "    except KeyError:\n        tc.assertEqual(out, 4)\n"))):
        got = _run([(hpath, base, tree)])
        seen.append((label, got["answer"] == PARTLY_READ,
                     _reason_says(got, hpath, "changed or removed", "base", 7,
                                  "tc.assertEqual(out, 4)"), _show(got), got["notRead"]))
    check("fm70 (g) an assertion in a helper moved between the parts of an if, or of a "
          "try, is not compared - changed or removed, named at its base line: %r" % (seen,),
          [s[1:3] for s in seen] == [(True, True)] * 2)

    # Two callables tied for most labelled calls are both read as checks, so a
    # check moved from one to the other is still a unit; only its callee says it
    # is no longer the same.
    tied = ('def main(check, expect):\n    check("k1 two", 1 + 1 == 2)\n'
            '    expect("k2 three", 1 + 2 == 3)\n')
    got = _run([(path, tied, tied.replace('    expect("k2', '    check("k2'))])
    check("fm71 a check called through another of the callables the base calls checks "
          "through is a changed check, not the same one: %s" % _show(got),
          [f["what"] for f in _moves(got, M.DEFINITION_CHANGED) if "k2" in f["what"]] != []
          and got["answer"] == M.FINDINGS)


def _rest_reason(check):
    path = "tests/test_house.py"
    added = _run([(path, HOUSE_SUITE, HOUSE_SUITE.replace(
        "def _double(n):\n", "def _double(n):\n    n = n + 0\n"))])
    edited = _run([(path, HOUSE_SUITE, HOUSE_SUITE.replace("return n * 2", "return n * 3"))])
    removed = _run([(path, HOUSE_SUITE, HOUSE_SUITE.replace("import _harness\n", ""))])
    check("fx5 a file not compared says which of two things its code outside the units "
          "is, computed: a statement only added names the first added one at its tree "
          "line; one edited, or one removed, names the first base statement with no "
          "place in the tree copy at its base line: %r / %r / %r"
          % (added["notRead"], edited["notRead"], removed["notRead"]),
          [g["answer"] for g in (added, edited, removed)] == [PARTLY_READ] * 3
          and [len(_not_compared(g, path)) for g in (added, edited, removed)] == [1] * 3
          and _reason_says(added, path, "only added", "tree", 7, "n = n + 0")
          and _reason_says(edited, path, "changed or removed", "base", 7, "return n * 2")
          and _reason_says(removed, path, "changed or removed", "base", 3, "import _harness"))


def _rest_allow(check):
    path = "tests/test_rows.py"
    c1, c2 = '    check("c1 two", 1 + 1 == 2)\n', '    check("c2 three", 1 + 2 == 3)\n'
    new = '    check("c9 five", 2 + 3 == 5)\n'
    shapes = (("appended after the last", ROWS_CALLED.replace(
        '2 + 2 == 4)\n', '2 + 2 == 4)\n' + new)),
              ("inserted between two", ROWS_CALLED.replace(c1, c1 + new)),
              ("two adjacent swapped", ROWS_CALLED.replace(c1 + c2, c2 + c1)))
    got = [(label, _run([(path, ROWS_CALLED, tree)])) for label, tree in shapes]
    check("fa41 THE TWIN of fm64: a new check appended after the last, one inserted "
          "between two, and two adjacent checks swapped are compared and clean, and the "
          "basis counts the existing units compared and the new ones: %r"
          % ([(label, _show(g), g["notRead"]) for label, g in got],),
          [(g["answer"], g["findings"], g["notRead"]) for _l, g in got]
          == [(M.CLEAN, [], [])] * 3
          and re.search(r"\b3 existing unit", got[0][1]["basis"]) is not None
          and re.search(r"\b1 new unit", got[0][1]["basis"]) is not None)

    upath = "tests/test_unit.py"
    method = "    def test_new(self):\n        self.assertTrue(True)\n\n"
    got = [_run([(upath, UNIT_TWO, UNIT_TWO.replace("    def setUp(self):",
                                                    method + "    def setUp(self):"))]),
           _run([(upath, UNIT_TWO, UNIT_TWO.replace("    def test_two(self):",
                                                    method + "    def test_two(self):"))])]
    check("fa42 THE TWIN of fm68: a new test method, before the set-up or between it and "
          "a test, is a new unit and reads clean: %s / %s" % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got] == [(M.CLEAN, [], [])] * 2)

    unit = ROWS_CALLED.replace(c2, '    check(\n        "c2 three",\n        1 + 2 == 3,\n'
                                   '    )\n')
    helper = ROWS_CALLED.replace("        FAILED.append(label)\n",
                                 "        # keep the label\n        FAILED.append(\n"
                                 "            label)\n")
    got = [_run([(path, ROWS_CALLED, t)]) for t in (unit, helper)]
    check("fa43 THE TWIN of fm65: a pure reformat of a unit and of a helper reads clean: "
          "%s / %s" % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got] == [(M.CLEAN, [], [])] * 2)

    got = _run([(path, ROWS_CALLED, ROWS_CALLED.replace('"c2 three"',
                                                        '"c2 one and two make three"'))])
    check("fa44 THE TWIN of fm69: a label reworded with its condition untouched reads "
          "clean and is listed as renamed: %s %r" % (_show(got), got.get("renamed")),
          (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], [])
          and len(got["renamed"]) == 1)

    got = [_run([("tests/unit/test_unit.py", UNIT_TWO, UNIT_TWO, upath)]),
           _run([(path, ROWS_CALLED, None), ("tests/unit/test_rows.py", None, ROWS_CALLED)])]
    check("fa45 THE TWIN of fm69: a test file moved to another test path unchanged - "
          "renamed, or deleted and added again - reads clean: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"]) for g in got] == [(M.CLEAN, [])] * 2)


# --- a unit's position is read by pairing, not by counting ------------------------
# A unit is in place when some longest common subsequence of the statements around
# it - in its part, and in the part of every statement enclosing it - pairs nothing
# across it. A count of the statements before a unit is a position only when the
# statements counted are the same ones in both copies: one set-up line added above
# a check moved every check after it under a count, and a check moved into a later
# block whose head reads the same was never seen moving at all.

BLOCKS = '''import sys

FAILED = []


def check(label, ok):
    if not ok:
        FAILED.append(label)


def main():
    x = 2
    for n in (1, 2):
        check("b1 positive", n > 0)
        check("b2 small", n < 3)
    if x > 1:
        check("i1 big", x > 1)
        check("i2 two", x == 2)
    FAILED.clear()
    for n in (1, 2):
        check("b3 nonzero", n != 0)
    if x > 1:
        check("i3 positive", x > 0)
    sys.exit(1 if FAILED else 0)


main()
'''


def _only_added_at(result, path, lines, text):
    """True when `path` is listed as not compared, only added, at one of `lines`
    of the tree copy, the reason holding `text` - a duplicate's pairing may name
    either copy of the statement."""
    return any(_reason_says(result, path, "only added", "tree", ln, text) for ln in lines)


def _pairing_deny(check):
    path = "tests/test_blocks.py"
    b2 = '        check("b2 small", n < 3)\n'
    i2 = '        check("i2 two", x == 2)\n'
    across_for = BLOCKS.replace(b2, "").replace(
        '        check("b3 nonzero", n != 0)\n', b2 + '        check("b3 nonzero", n != 0)\n')
    across_if = BLOCKS.replace(i2, "").replace(
        '        check("i3 positive", x > 0)\n', '        check("i3 positive", x > 0)\n' + i2)
    seen = []
    for label, tree, words in (("for", across_for, ("b1", "b2", "b3")),
                               ("if", across_if, ("i1", "i2", "i3"))):
        got = _run([(path, BLOCKS, tree)])
        seen.append((label, got["answer"], _labels_found(got, words),
                     _not_compared(got, path), _show(got)))
    check("fm72 a check moved out of a block into a later block whose head reads the "
          "same, across a statement clearing the failures - under a for, and under an "
          "if - is a finding, moved, and the file is compared, its rest the same: %r"
          % (seen,),
          [s[1:4] for s in seen] == [(M.FINDINGS, [0, 1, 0], [])] * 2)


def _pairing_allow(check):
    path, upath = "tests/test_house.py", "tests/test_unit.py"
    rows = HOUSE_SUITE.replace('    check("h1 two', '    seed = 2\n    check("h1 two')
    unit = UNIT_TWO.replace("    def test_two(self):",
                            "    maxDiff = None\n\n    def test_two(self):")
    got = [_run([(path, HOUSE_SUITE, rows)]), _run([(upath, UNIT_TWO, unit)])]
    check("fa46 a set-up line added before an existing check, in a row suite and in a "
          "unittest test's class, gives no finding: the file is not compared, only "
          "added, naming the line: %s %r / %s %r"
          % (_show(got[0]), got[0]["notRead"], _show(got[1]), got[1]["notRead"]),
          [(g["answer"], g["findings"]) for g in got] == [(PARTLY_READ, [])] * 2
          and _reason_says(got[0], path, "only added", "tree", 12, "seed = 2")
          and _reason_says(got[1], upath, "only added", "tree", 8, "maxDiff = None"))

    rpath = "tests/test_rows.py"
    # The duplicate pairs with either copy; one pairing crosses the check beside
    # it and the other does not, and the rule reads it in the check's favour.
    before = ROWS_MAIN.replace('    check("r2 three', '    x = 1 + 1\n    check("r2 three')
    after = ROWS_MAIN.replace('    check("r3 list', '    print("3/3 cases passed")\n'
                              '    check("r3 list')
    got = [_run([(rpath, ROWS_MAIN, t)]) for t in (before, after)]
    check("fa47 a duplicate of an existing statement inserted beside a check - a copy "
          "of the set-up line before it, and of the print after it - gives no finding, "
          "though one best pairing crosses the check: only added: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"]) for g in got] == [(PARTLY_READ, [])] * 2
          and _only_added_at(got[0], rpath, (11, 13), "x = 1 + 1")
          and _only_added_at(got[1], rpath, (14, 16), "print("))

    cpath = "tests/test_cart.py"
    tree = CART_TEST.replace("def test_total():", "def _basket():\n    return [1, 2]\n\n\n"
                             "def test_total():")
    got = _run([(cpath, CART_TEST, tree)])
    check("fa48 a new helper above the first test of a file gives no finding: only "
          "added, named at its line: %s %r" % (_show(got), got["notRead"]),
          (got["answer"], got["findings"]) == (PARTLY_READ, [])
          and _reason_says(got, cpath, "only added", "tree", 6, "def _basket():"))

    tree = ROWS_MAIN.replace('    check("r2 three', '    y = x\n    check("r9 y", y == 2)\n'
                             '    check("r2 three')
    got = _run([(rpath, ROWS_MAIN, tree)])
    check("fa49 a set-up line and a new check added together after one check and "
          "before the next give no finding: only added at the set-up line: %s %r"
          % (_show(got), got["notRead"]),
          (got["answer"], got["findings"]) == (PARTLY_READ, [])
          and _reason_says(got, rpath, "only added", "tree", 13, "y = x"))

    two = "    def test_two(self):\n        self.assertEqual(self.x, 2)\n\n"
    three = "    def test_three(self):\n        self.assertNotEqual(self.x, 3)\n\n"
    got = _run([(upath, UNIT_TWO, UNIT_TWO.replace(two + three, three + two))])
    check("fa50 two adjacent test methods swapped read clean - no statement that is "
          "not a unit stands between them: %s %r" % (_show(got), got["notRead"]),
          (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], []))


# The child is killed at DEADLINE; CEILING is what the reading may take inside it.
# A per-unit recomputation of the pairing turns the reading cubic in a part's
# length, which is the difference these two numbers are there to show.
BIG_PARTS, BIG_SIZE = 4, 750
BIG_CEILING, BIG_DEADLINE = 10.0, 60

BIG_CHILD = r'''
import json, sys, time
sys.path[:0] = json.loads(sys.argv[1])
import _floor_guard as M
job = json.load(sys.stdin)
start = time.perf_counter()
got = M.find_moves(job["diff"], {job["path"]: job["base"]}.get, {job["path"]: job["tree"]}.get)
print(json.dumps({"seconds": time.perf_counter() - start, "answer": got["answer"],
                  "findings": len(got["findings"] or ())}))
'''


def _big_suite(parts, size, edited):
    """A row suite of `parts` functions of `size` set-up lines and checks each;
    `edited` adds a set-up line at the top of every function and a set-up line
    and a check at its end, so no part shares a prefix or a suffix with its base
    and the pairing of every part needs its tables."""
    out = ["import sys\n"]
    for p in range(parts):
        out.append("\n\ndef _cases_%d(check):\n" % p)
        if edited:
            out.append("    seed = %d\n" % p)
        for k in range(size):
            out.append("    v%d = %d\n" % (k, k))
            out.append('    check("p%d case %d", v%d == %d)\n' % (p, k, k, k))
        if edited:
            out.append('    tail = %d\n    check("p%d tail", tail == %d)\n' % (p, p, p))
    return "".join(out)


def _time(check):
    path = "tests/test_big.py"
    base, tree = _big_suite(BIG_PARTS, BIG_SIZE, False), _big_suite(BIG_PARTS, BIG_SIZE, True)
    job = json.dumps({"diff": _file_diff(path, base, tree), "path": path, "base": base,
                      "tree": tree})
    try:
        proc = subprocess.run([sys.executable, "-c", BIG_CHILD, json.dumps(sys.path)],
                              input=job, capture_output=True, text=True,
                              timeout=BIG_DEADLINE)
        lines = proc.stdout.strip().splitlines()
        said = json.loads(lines[-1]) if proc.returncode == 0 and lines else None
        why = "exit %d, stderr %r" % (proc.returncode, proc.stderr[-300:])
    except subprocess.TimeoutExpired:
        said, why = None, "killed at the %ds deadline" % BIG_DEADLINE
    check("fx6 a generated row suite of %d parts, each %d set-up lines and %d checks, "
          "a set-up line added at the top of every part and a check with its set-up "
          "line at its end, is read in under %.0fs with no finding and the file only "
          "added: %r %s"
          % (BIG_PARTS, BIG_SIZE, BIG_SIZE, BIG_CEILING, said, "" if said else why),
          said is not None and said["seconds"] < BIG_CEILING
          and (said["answer"], said["findings"]) == (PARTLY_READ, 0))


# --- what cannot be read ---------------------------------------------------------

def _unreadable(path):
    def read(p):
        if p == path:
            raise OSError("permission denied: %s" % p)
        return CART_SRC
    return read


def _untold(check):
    for cid, label, diff in (
            ("fc1", "text that is not a diff", "this is not a diff\nat all\n"),
            ("fc2", "a hunk whose counts do not add up",
             "diff --git a/src/cart.py b/src/cart.py\n--- a/src/cart.py\n"
             "+++ b/src/cart.py\n@@ -1,5 +1,5 @@\n def total(xs):\n"),
            ("fc3", "a hunk before any file header", "@@ -1 +1 @@\n-a\n+b\n")):
        got = M.find_moves(diff, lambda p: CART_SRC, lambda p: CART_SRC)
        check("%s %s is could-not-tell with a reason, never clean: %s"
              % (cid, label, _show(got)),
              got["answer"] == M.COULD_NOT_TELL and got["findings"] == []
              and got["basis"])

    tree = CART_SRC.replace("return sum(xs)", "return sum(xs)  # noqa")
    diff = _file_diff("src/cart.py", CART_SRC, tree)
    got = M.find_moves(diff, _unreadable("src/cart.py"), lambda p: tree)
    check("fc4 a base file that cannot be read is could-not-tell naming it: %s"
          % _show(got),
          got["answer"] == M.COULD_NOT_TELL and got["findings"] == []
          and [c["path"] for c in got["couldNotTell"]] == ["src/cart.py"]
          and "permission denied" in got["couldNotTell"][0]["reason"])

    got = M.find_moves(diff, lambda p: None, lambda p: tree)
    check("fc5 a base the diff modifies but the reader says is absent is "
          "could-not-tell: %s" % _show(got),
          got["answer"] == M.COULD_NOT_TELL and got["findings"] == [])

    broken = CART_TEST.replace("def test_empty():", "def test_empty(:")
    for cid, side, base, tree in (("fc6", "tree", CART_TEST, broken),
                                  ("fc7", "base", broken, CART_TEST)):
        got = _run([("tests/test_cart.py", base, tree)])
        check("%s a test file that does not compile in the %s is could-not-tell, "
              "never clean and never a finding: %s" % (cid, side, _show(got)),
              got["answer"] == M.COULD_NOT_TELL and got["findings"] == []
              and side in got["couldNotTell"][0]["reason"])

    got = _run([("src/cart.py", CART_SRC, CART_SRC + "def broken(:\n    pass\n")])
    check("fc8 a source .py that does not compile is could-not-tell: %s" % _show(got),
          got["answer"] == M.COULD_NOT_TELL and got["findings"] == [])

    got = M.find_moves(None, lambda p: "", lambda p: "")
    check("fc9 no diff at all is could-not-tell, not an empty clean diff: %s"
          % _show(got), got["answer"] == M.COULD_NOT_TELL)

    tree = CART_SRC.replace("return sum(xs)", "return sum(xs)  # noqa")
    diff = _file_diff("src/cart.py", CART_SRC, tree)
    got = M.find_moves(diff, lambda p: CART_SRC, lambda p: CART_SRC)
    check("fc10 a tree that no longer holds the lines the diff added is "
          "could-not-tell: %s" % _show(got),
          got["answer"] == M.COULD_NOT_TELL and got["findings"] == [])

    gone = _file_diff("tests/test_cart.py", CART_TEST, None)
    noqa = _file_diff("src/cart.py", CART_SRC, tree)
    got = M.find_moves(gone + noqa, _unreadable("src/cart.py"), lambda p: tree)
    check("fc11 a could-not-tell beside a real finding keeps both: the finding "
          "stands and the unreadable file is still named: %s" % _show(got),
          got["answer"] == M.FINDINGS
          and [f["move"] for f in got["findings"]] == [M.TEST_DELETED]
          and [c["path"] for c in got["couldNotTell"]] == ["src/cart.py"])

    got = M.find_moves("", lambda p: None, lambda p: None)
    check("fc12 an empty diff is clean and its basis says nothing was changed: %s"
          % _show(got),
          got["answer"] == M.CLEAN and "no file" in got["basis"])


def _shape(check):
    with open(M.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    check("fx1 the module keeps git out: it imports no subprocess and reads no "
          "repository itself: %r" % (sorted(names),),
          "subprocess" not in names and "_filed_returns" in names)


def _cases(check):
    _found(check)
    _allowed(check)
    _definitions(check)
    _suppressions(check)
    _marker(check)
    _binary(check)
    _skips(check)
    _outside(check)
    _labelled(check)
    _declarations(check)
    _marker_kinds(check)
    _other_languages(check)
    _moved(check)
    _kinds(check)
    _wrapped(check)
    _skip_spellings(check)
    _moved_out(check)
    _ambiguous(check)
    _honest(check)
    _not_inert(check)
    _inert_twins(check)
    _invariant(check)
    _nested_helper(check)
    _rest_deny(check)
    _rest_reason(check)
    _rest_allow(check)
    _pairing_deny(check)
    _pairing_allow(check)
    _time(check)
    _untold(check)
    _shape(check)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__floor_guard.py --selftest\n")
    raise SystemExit(2)
