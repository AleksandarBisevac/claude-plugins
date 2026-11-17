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
import re
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
    check("fa25 THE TWIN: a test file that only gains code - an import, a helper "
          "and a test appended - or whose helper gains a docstring and whose test "
          "gains a comment is compared and clean, listed nowhere: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got]
          == [(M.CLEAN, [], [])] * 2)

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
    check("fa26 a script-style suite that only gains a labelled check and the line "
          "before it is compared and clean: %s %r" % (_show(got), got["notRead"]),
          got["answer"] == M.CLEAN and got["findings"] == [] and got["notRead"] == [])

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
                   ("tests/test_h2.py", other,
                    other + '\n\ndef _more(check):\n'
                            '    check("h2 zero doubled is zero", _double(0) == 0)\n')])
    check("fa32 a test function, and a labelled check, moved unchanged from one "
          "test file to another give no finding: %s / %s" % (_show(got), _show(labels)),
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


# --- compared means every changed line is accounted for --------------------------
# A test file reads as compared only when each changed line of either copy lies in
# a compared unit (a test definition or a labelled check, compared with the chain
# of statements enclosing it) or in an inert addition. Each input below lowers the
# bar while every unit's own text stays the same, so a reading that compares the
# units alone calls it clean.

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
          "try whose except passes, is a definition change of that check alone, and "
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
    check("fm55 (g) a call of sys.exit added above the checks is no inert addition: "
          "the file is not compared at that line, and the answer is not clean: %s %r"
          % (_show(got), got["notRead"]),
          got["answer"] == PARTLY_READ and _names_line(got, path, (12,)))

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
          "trailing print - is compared and clean: %s / %s"
          % (_show(got[0]), _show(got[1])),
          [(g["answer"], g["findings"], g["notRead"]) for g in got]
          == [(M.CLEAN, [], [])] * 2)

    tree = ROWS_MAIN.replace("def main():", "def triple(n):\n    return n * 3\n\n\n"
                             "def main():")
    got = _run([(path, ROWS_MAIN, tree)])
    check("fa34 THE TWIN of fm54: a new helper function under a fresh name is an "
          "inert addition: %s %r" % (_show(got), got["notRead"]),
          (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], []))

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
    check("fa40 THE TWIN of fm62: a new test file with module code of its own, a new "
          "test that catches SkipTest without raising one, and a new group of checks "
          "called after every statement its caller had are inert and read clean: "
          "%s / %s / %s" % (_show(new_file), _show(caught), _show(grouped)),
          [(g["answer"], g["findings"], g["notRead"]) for g in (new_file, caught, grouped)]
          == [(M.CLEAN, [], [])] * 3)


# --- the invariant, computed by the case itself ----------------------------------
# The expected reading of each generated edit is derived here from line spans -
# ast lineno/end_lineno over this file's own fixtures and difflib's changed lines
# - and never from the module's helpers, so the case cannot agree with the guard
# by construction. A fixed table of edit operators is applied at every statement
# position of two small fixtures, so the edits and their count are reproducible.

INV_ROWS = '''import sys

LIMIT = 3


def _cases(check):
    x = 2
    check("alpha two", x == 2)
    for n in (1, 2):
        check("beta row %d" % n, n < 3)
    check("gamma limit", LIMIT == 3)
    print("done", 4)


def main():
    return _cases(print)
'''

INV_UNIT = '''import unittest

BASE = 2


class TestA(unittest.TestCase):
    def setUp(self):
        self.x = 2

    def test_one(self):
        self.assertEqual(self.x, 2)

    def test_two(self):
        self.assertTrue(BASE < 3)


def _helper(v):
    return v * 2
'''

INV_INSERTS = ("_probe = 0", "sys.exit(0)")
INV_HOOK = re.compile(r"^(setUp|tearDown|setUpClass|tearDownClass|setUpModule|"
                      r"tearDownModule|pytest_\w+|load_tests)$")


def _inv_places(tree):
    """(node, where, function, class) for every statement, outermost first: `where`
    is module, class, function (a direct child of a def body) or block."""
    out = []

    def visit(body, where, func, cls):
        for node in body:
            out.append((node, where, func, cls))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(node.body, "function", node, cls)
            elif isinstance(node, ast.ClassDef):
                visit(node.body, "class", None, node.name)
            else:
                for name in ("body", "orelse", "finalbody"):
                    visit(getattr(node, name, None) or [], "block", func, cls)
                for handler in getattr(node, "handlers", None) or []:
                    visit(handler.body, "block", func, cls)
    visit(tree.body, "module", None, None)
    return out


def _inv_first(node):
    return min([d.lineno for d in getattr(node, "decorator_list", ())] + [node.lineno])


def _inv_key(node, func, cls):
    """A unit's identity, or None: a test definition outside any function, or a
    `check(...)` statement whose first argument opens with a string."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if func is None and node.name.startswith("test") and (cls or "Test").startswith("Test"):
            return ("def", cls, node.name)
        return None
    call = node.value if isinstance(node, ast.Expr) else None
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "check" and call.args):
        return None
    label = call.args[0]
    label = label.left if isinstance(label, ast.BinOp) else label
    if isinstance(label, ast.Constant) and isinstance(label.value, str):
        return ("check", label.value)
    return None


def _inv_units(places):
    return dict(((_inv_key(n, f, c), (_inv_first(n), n.end_lineno, f))
                 for n, _w, f, c in places if _inv_key(n, f, c) is not None))


def _inv_bound(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
    return names


def _inv_inert(node, where, func, base_tree, base_units, tree_units, base_places):
    """The inert-addition rule read independently: is this added tree statement
    harmless to what exists?"""
    bound = _inv_bound(base_tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (where in ("module", "class") and node.name not in bound
                and not node.decorator_list and not INV_HOOK.match(node.name))
    if where == "module":
        if isinstance(node, ast.Assign):
            return all(isinstance(t, ast.Name) and t.id not in bound for t in node.targets)
        return False
    if where != "function" or INV_HOOK.match(func.name):
        return False
    ends = [end for key, (_s, end, f) in tree_units.items()
            if f is func and key in base_units]
    if ends:
        return node.lineno > max(ends)
    # A body holding no unit: inert only after every statement it already had.
    base_func = [n for n, _w, _f, _c in base_places
                 if isinstance(n, type(func)) and n.name == func.name]
    if len(base_func) != 1:
        return False
    tree_lines = [n.lineno for n in func.body if n is not node]
    return not tree_lines or node.lineno > max(tree_lines)


def _inv_expect(base, tree):
    """(leftover lines, lines in existing units, all accounted by inert additions)."""
    blines, tlines = base.splitlines(), tree.splitlines()
    bchanged, tchanged = set(), set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, blines, tlines).get_opcodes():
        if tag != "equal":
            bchanged.update(i for i in range(i1 + 1, i2 + 1) if blines[i - 1].strip())
            tchanged.update(j for j in range(j1 + 1, j2 + 1) if tlines[j - 1].strip())
    btree, ttree = ast.parse(base), ast.parse(tree)
    bplaces, tplaces = _inv_places(btree), _inv_places(ttree)
    bunits, tunits = _inv_units(bplaces), _inv_units(tplaces)

    def spans(units):
        return set(ln for s, e, _f in units.values() for ln in range(s, e + 1))
    in_units = (set(("base", ln) for ln in bchanged & spans(bunits))
                | set(("tree", ln) for ln in tchanged & spans(
                    dict((k, v) for k, v in tunits.items() if k in bunits))))
    inert = set()
    for node, where, func, cls in tplaces:
        lines = set(range(_inv_first(node), node.end_lineno + 1))
        code = set(ln for ln in lines if tlines[ln - 1].strip())
        if not code or not code <= tchanged:
            continue
        key = _inv_key(node, func, cls)
        if (key is not None and key not in bunits) or (
                key is None and _inv_inert(node, where, func, btree, bunits, tunits, bplaces)):
            inert |= lines
    left = (set(("base", ln) for ln in bchanged - spans(bunits))
            | set(("tree", ln) for ln in tchanged - spans(tunits) - inert))
    return left, in_units


def _inv_edits(text):
    """Every edit the operator table makes at every statement position of `text`,
    each once: insert a statement before or after, delete, change the last number
    on the head line, wrap in an `if`."""
    lines = text.splitlines(True)
    edits = []
    for node, _w, _f, _c in _inv_places(ast.parse(text)):
        first, last = _inv_first(node), node.end_lineno
        pad = " " * node.col_offset
        for stmt in INV_INSERTS:
            edits.append(lines[:first - 1] + [pad + stmt + "\n"] + lines[first - 1:])
            edits.append(lines[:last] + [pad + stmt + "\n"] + lines[last:])
        edits.append(lines[:first - 1] + lines[last:])
        head = lines[node.lineno - 1]
        nums = list(re.finditer(r"\d+", head))
        if nums:
            cut = nums[-1]
            edits.append(lines[:node.lineno - 1]
                         + [head[:cut.start()] + "97" + head[cut.end():]] + lines[node.lineno:])
        edits.append(lines[:first - 1] + [pad + "if True:\n"]
                     + ["    " + ln if ln.strip() else ln for ln in lines[first - 1:last]]
                     + lines[last:])
    out = []
    for edit in edits:
        joined = "".join(edit)
        if joined != text and joined not in out:
            out.append(joined)
    return out


def _invariant(check):
    tally = {"made": 0, "unparsed": 0, "leftover": 0, "units": 0, "inert": 0}
    wrong = []
    for path, base in (("tests/test_inv_rows.py", INV_ROWS),
                       ("tests/test_inv_unit.py", INV_UNIT)):
        for tree in _inv_edits(base):
            tally["made"] += 1
            try:
                left, in_units = _inv_expect(base, tree)
            except SyntaxError:
                tally["unparsed"] += 1
                continue
            got = _run([(path, base, tree)])
            if left:
                tally["leftover"] += 1
                named = any(re.search(r"\b%s line %d\b" % (side, ln), n["reason"])
                            for n in _named_lines(got, path) for side, ln in left)
                ok = got["answer"] != M.CLEAN and named
            elif in_units:
                tally["units"] += 1
                ok = got["answer"] == M.FINDINGS and _named_lines(got, path) == []
            else:
                tally["inert"] += 1
                ok = (got["answer"], got["findings"], got["notRead"]) == (M.CLEAN, [], [])
            if not ok:
                wrong.append((path, sorted(left)[:3], sorted(in_units)[:2],
                              [ln for ln in difflib.unified_diff(
                                  base.splitlines(), tree.splitlines(), n=0, lineterm="")
                               if ln[:1] in "+-" and ln[:3] not in ("+++", "---")],
                              _show(got), [n.get("reason") for n in got["notRead"]]))
    check("fx4 over %(made)d generated edits (%(unparsed)d not parsing, skipped): each "
          "of the %(leftover)d leaving a changed line outside every unit and inert "
          "addition is not clean and names such a line; each of the %(units)d touching "
          "only units is a finding; each of the %(inert)d made only of inert additions "
          "is clean: wrong %(n)d: %(w)s"
          % dict(tally, n=len(wrong), w=some_of(wrong, render=repr)),
          wrong == [] and tally["leftover"] > 0 and tally["units"] > 0
          and tally["inert"] > 0)


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
    seen = [[(f["side"], "r2" in f["what"]) for f in _moves(g, M.DEFINITION_CHANGED)]
            for g in (both, grown)]
    check("fm63 a row suite holding a helper named with the test prefix inside a "
          "function is still read by its labelled checks: a weakened check is a "
          "definition change naming it, with the helper in both copies and with "
          "it new to the tree: %s / %s" % (_show(both), _show(grown)),
          seen == [[("tree", True)], [("tree", True)]])


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
