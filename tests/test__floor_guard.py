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
import difflib
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _filed_returns                              # noqa: E402
import _floor_guard as M                           # noqa: E402


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
    check("fa3 a changed definition the task declared is returned as declared, "
          "apart from findings, and only for what was declared: %s / %s / %s"
          % (_show(by_case), _show(by_file), _show(other)),
          by_case["findings"] == [] and len(by_case["declared"]) == 1
          and by_case["declared"][0]["path"] == "tests/test_cart.py"
          and by_case["answer"] == M.CLEAN
          and by_file["findings"] == [] and len(by_file["declared"]) == 1
          and len(_moves(other, M.DEFINITION_CHANGED)) == 1 and other["declared"] == [])

    tree = JS_TEST.replace("toBe(3)", "toBe(4)")
    got = _run([("tests/add.test.js", JS_TEST, tree)], declared=("tests/add.test.js",))
    check("fa4 an assertion line changed in a declared JS test is declared, not a "
          "finding: %s" % _show(got),
          got["findings"] == [] and len(got["declared"]) == 1)

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
    listed = [n for n in got["notRead"] if n["path"] == "tests/test_rows.py"]
    check("fa12 a case row added inside a case-table function gives no finding, "
          "and the file is listed as not read for the definition move with a "
          "reason: %s %r" % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN and len(listed) == 1
          and listed[0].get("move") == M.DEFINITION_CHANGED and listed[0].get("reason"))

    tree = ROW_SUITE.replace("import sys\n", "import sys  # the runner's argv\n")
    got = _run([("tests/test_rows.py", ROW_SUITE, tree)])
    check("fa13 a comment edit in a file with no test definition touches no code: "
          "clean, and not listed as not read: %s %r" % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN and got["notRead"] == [])

    tree = HELPER_TEST.replace("return [1, 2]", "return [1, 2, 3]")
    got = _run([("tests/test_cart.py", HELPER_TEST, tree)])
    check("fa14 a helper changed beside untouched test_ functions gives no finding, "
          "and the file was read: %s %r" % (_show(got), got.get("notRead")),
          got["findings"] == [] and got["answer"] == M.CLEAN and got["notRead"] == [])

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
          "Test_upper are not tests, so no finding: %s" % _show(got),
          M.TEST_PREFIX == "test" and got["findings"] == [] and got["answer"] == M.CLEAN)


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
