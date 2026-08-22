#!/usr/bin/env python3
"""Print every figure the docs quote about the assembled-UI test surface.

Exists because those figures kept rotting. `CLAUDE.md` said 737 substring pins
while the tree held 822; its per-target table said 578/100/48/11 against
676/96/51/11; it claimed 118 index-slices and broke them down as 47 + 39, which
is 86, against a real 50; `CONTRIBUTING.md` said 26 files over 500 against 21.
Every one of them was true when written.

**A number in prose rots. A command that prints it cannot.** So the docs cite
this and carry the figure only as of a stated commit, which is the same rule the
rest of the repo follows: every claim carries the basis that makes it true.

WHY AN AST WALK AND NOT A GREP. The documented `grep -rhoE` under-reports by 36
at the commit this was written, and the reason is not one thing:

  * a pin whose literal is split across lines ends with `in M.UI_HTML)` alone on
    the closing line, and a line-based regex sees no literal there;
  * a comparison whose left side is not a literal at all
    (`json.dumps(M._cfg_enums(), sort_keys=True) in M.UI_HTML`) is a substring
    assertion the regex cannot express.

Neither is fixable by a better regex: one needs the parser's idea of a line, the
other needs its idea of an expression. The previous replacement command in
CLAUDE.md was itself off by 73 for the first reason, which is how this file came
to exist rather than a third regex.

Usage:  python3 tools/count-ui-pins.py [--json]
Exit codes: 0 always (a report, not a gate).
"""
import argparse
import ast
import json
import os
import sys

TESTS = os.path.join("plugins", "audit", "tests")
TARGETS = ("UI_HTML", "_SCRIPT", "_CSS", "TOKEN_CSS")
CODE_DIRS = (os.path.join("plugins", "audit", "scripts"),
             os.path.join("plugins", "audit", "hooks"))
LONG_FILE_LINES = 500


def _py_files(root):
    for base, _dirs, names in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in sorted(names):
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _is_target(node):
    """`M.UI_HTML` and friends — the assembled artifacts the pins assert against."""
    return (isinstance(node, ast.Attribute) and node.attr in TARGETS
            and isinstance(node.value, ast.Name) and node.value.id == "M")


def _uses_index(node):
    return any(isinstance(n, ast.Attribute) and n.attr == "index"
               for n in ast.walk(node))


def collect(root=TESTS):
    """Every figure, measured. Returns a dict; nothing here reads a document."""
    literal, computed = 0, 0
    per_target = dict((t, 0) for t in TARGETS)
    per_file = {}
    slices, slices_per_file = 0, {}

    for path in _py_files(root):
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        name = os.path.basename(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for i, (op, cmp_) in enumerate(zip(node.ops, node.comparators)):
                    if not (isinstance(op, (ast.In, ast.NotIn)) and _is_target(cmp_)):
                        continue
                    left = node.left if i == 0 else node.comparators[i - 1]
                    per_target[cmp_.attr] += 1
                    per_file[name] = per_file.get(name, 0) + 1
                    if isinstance(left, ast.Constant) and isinstance(left.value, str):
                        literal += 1
                    else:
                        computed += 1
            # An order assertion is one SLICE, not the two `.index()` calls that
            # bound it — counting the calls is what turned 50 into 118.
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                bounds = [b for b in (node.slice.lower, node.slice.upper) if b is not None]
                if any(_uses_index(b) for b in bounds):
                    slices += 1
                    slices_per_file[name] = slices_per_file.get(name, 0) + 1

    css_shaped = per_target["_CSS"] + per_target["TOKEN_CSS"]
    return {
        "pins": {"literal": literal, "computed": computed,
                 "total": literal + computed, "cssShaped": css_shaped},
        "perTarget": per_target,
        "perFile": per_file,
        "indexSlices": {"total": slices, "perFile": slices_per_file},
        "longFiles": long_files(),
    }


def long_files(dirs=CODE_DIRS, limit=LONG_FILE_LINES):
    """`.py` over `limit` lines, per directory — CONTRIBUTING's split list.

    Scoped to `scripts/` and `hooks/` because that is what the sentence in
    CONTRIBUTING is about; counting `tests/` too gives a different, larger number
    and the doc never said which it meant.
    """
    out = {}
    for d in dirs:
        n = 0
        for path in _py_files(d):
            with open(path, "r", encoding="utf-8") as fh:
                if sum(1 for _ in fh) > limit:
                    n += 1
        out[d] = n
    out["total"] = sum(v for k, v in out.items() if k != "total")
    return out


def render(data):
    p = data["pins"]
    lines = ["substring assertions against M.{%s}" % ", ".join(TARGETS),
             "  literal left-hand side (a text pin) : %d" % p["literal"],
             "  computed left-hand side            : %d" % p["computed"],
             "  total                              : %d" % p["total"],
             "  of which CSS-shaped (_CSS+TOKEN_CSS): %d" % p["cssShaped"],
             "per target"]
    for t in TARGETS:
        lines.append("  M.%-10s %5d" % (t, data["perTarget"][t]))
    lines.append("per file")
    for name in sorted(data["perFile"], key=lambda k: -data["perFile"][k]):
        lines.append("  %-32s %5d" % (name, data["perFile"][name]))
    s = data["indexSlices"]
    lines.append("index-bounded slices (statement ORDER): %d" % s["total"])
    for name in sorted(s["perFile"], key=lambda k: -s["perFile"][k]):
        lines.append("  %-32s %5d" % (name, s["perFile"][name]))
    lines.append("`.py` over %d lines" % LONG_FILE_LINES)
    for k in sorted(data["longFiles"]):
        lines.append("  %-32s %5d" % (k, data["longFiles"][k]))
    return "\n".join(lines)


# --- selftest -----------------------------------------------------------------
# IT USED TO SAY IT NEEDED NONE, because `tools/` carried no contract. That was true
# of the directory and never true of this file: CLAUDE.md tells a reader to run it
# BEFORE touching the assembled UI and to budget a change against what it prints, so
# a count that quietly drifts low reads as "few pins to worry about" - which is the
# same rotting-number defect the numbers were deleted from that document to avoid.
def _fixture(tmp, name, src):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(src)
    return path


def _cases():
    import shutil
    import tempfile
    out = []

    real = collect()
    out.append(("p0", real["pins"]["total"] > 20
                and all(real["perTarget"][t] > 0 for t in TARGETS),
                "every one of the four targets carries pins in the real tree "
                "(%r). A zero here would print as a small change budget rather "
                "than as a broken scanner, which is the whole reason the figures "
                "were deleted from CLAUDE.md and replaced by this command"
                % (real["perTarget"],)))

    tmp = tempfile.mkdtemp(prefix="count-ui-pins-")
    try:
        _fixture(tmp, "test_fx.py",
                 'def f():\n'
                 '    assert "literal" in M.UI_HTML\n'
                 '    assert json.dumps(cfg()) in M.UI_HTML\n')
        got = collect(tmp)
        out.append(("p1", got["pins"] == {"literal": 1, "computed": 1, "total": 2,
                                          "cssShaped": 0},
                    "a LITERAL left-hand side and a COMPUTED one are counted apart. "
                    "A change budget needs the split: a computed pin cannot be read "
                    "by eye, and a regex could not express one at all: %r"
                    % (got["pins"],)))
        out.append(("p2", got["perTarget"]["UI_HTML"] == 2
                    and got["perFile"] == {"test_fx.py": 2},
                    "...and both are attributed to their target and their file, "
                    "because that is what the command is asked for"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="count-ui-pins-slice-")
    try:
        _fixture(tmp, "test_slice.py",
                 'def f():\n'
                 '    win = M.UI_HTML[src.index("a"):src.index("b")]\n')
        got = collect(tmp)
        out.append(("p3", got["indexSlices"]["total"] == 1,
                    "THE HISTORICAL DEFECT: an order assertion is ONE slice, not "
                    "the two `.index()` calls that bound it. Counting the calls is "
                    "what put a wrong figure into CLAUDE.md twice, and 2 is exactly "
                    "what the wrong version prints here (got %d)"
                    % (got["indexSlices"]["total"],)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="count-ui-pins-split-")
    try:
        _fixture(tmp, "test_split.py",
                 'def f():\n'
                 '    assert ("a long needle "\n'
                 '            "continued on the next line") in M.UI_HTML\n')
        got = collect(tmp)
        out.append(("p4", got["pins"]["literal"] == 1,
                    "a pin whose literal is SPLIT ACROSS LINES is still one pin - "
                    "the closing line reads `in M.UI_HTML)` with no literal on it, "
                    "and that blind spot is why a documented grep under-reported by "
                    "dozens: %r" % (got["pins"],)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="count-ui-pins-long-")
    try:
        _fixture(tmp, "big.py", "x = 1\n" * (LONG_FILE_LINES + 1))
        _fixture(tmp, "small.py", "x = 1\n" * (LONG_FILE_LINES - 1))
        got = long_files(dirs=(tmp,), limit=LONG_FILE_LINES)
        out.append(("p5", got[tmp] == 1 and got["total"] == 1,
                    "THE PAIR: one file over the limit and one under it, in the "
                    "same directory, and only one is counted - a version that "
                    "counted files would answer 2 and a version that counted none "
                    "would answer 0 (%r)" % (got,)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out.append(("p6", real["pins"]["cssShaped"]
                == real["perTarget"]["_CSS"] + real["perTarget"]["TOKEN_CSS"],
                "the CSS subtotal is DERIVED from the two targets it covers rather "
                "than counted a second time - a subtotal presented as if it covered "
                "everything is one of the six figures that rotted in CLAUDE.md"))
    return out


def _selftest():
    rows = _cases()
    bad = [r for r in rows if not r[1]]
    for name, ok, why in rows:
        print("%s %s %s" % ("PASS" if ok else "FAIL", name, why))
    print("%s: %d/%d cases passed" % ("ALL PASS" if not bad else "FAILURES",
                                      len(rows) - len(bad), len(rows)))
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    data = collect()
    print(json.dumps(data, indent=2, sort_keys=True) if args.as_json else render(data))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
