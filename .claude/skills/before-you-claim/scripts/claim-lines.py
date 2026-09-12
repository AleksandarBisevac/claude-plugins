#!/usr/bin/env python3
"""List every added prose block in a diff that claims a behaviour.

The first of the seven questions asks, for every sentence that describes what the code does,
where the line is that does it. An author answers the sentences they remember writing; this
lists the ones they wrote. It reads a unified diff on stdin (or a file named as the argument)
and prints each ADDED block that sits in prose - a `#` comment, a docstring, a Markdown
paragraph, a bare string literal - and carries a verb of behaviour.

    git diff HEAD | python3 .claude/skills/before-you-claim/scripts/claim-lines.py
    python3 .../claim-lines.py my.diff --tree /path/to/checkout

Whether an added line is prose is read off the FILE, not the hunk: for a `.py` the tree's copy
is parsed and every docstring's line range and every comment line is known, so a paragraph
added in the middle of a docstring - the commonest docstring edit, and a hunk that shows no
quote at all - is still prose. The hunk heuristic (a quote seen in the hunk opens a docstring)
is the fallback when the file cannot be read, and it is what the first version had: it
answered "n/a" for a thirty-line paragraph on exactly the question this script exists for.

It is a list to answer, never a verdict: it cannot know whether a claim is true, only that one
was made. A line it misses is still the author's; a line it prints that claims nothing is one
second to dismiss. Exit 0 always; the answer is the list.
"""
import ast
import io
import os
import re
import sys
import tokenize

# Verbs and phrases by which prose asserts that something happens. Kept as a table
# so a reader can see the vocabulary and widen it; an entry here does not make a
# line a defect, it makes it a line to answer.
BEHAVIOUR = re.compile(
    r"\b(refus\w*|den\w*|block\w*|reject\w*|record\w*|append\w*|write\w*|read\w*|"
    r"enforc\w*|check\w*|verif\w*|validat\w*|guarantee\w*|ensure\w*|prevent\w*|"
    r"serialis\w*|serializ\w*|chain\w*|hash\w*|lock\w*|wait\w*|retr\w*|re-run\w*|"
    r"protect\w*|anchor\w*|refuse\w*|never|always|only|cannot|can't|must|"
    r"is (?:chained|refused|recorded|checked|enforced|verified|held|taken|written|denied|"
    r"blocked|the only)|are (?:chained|refused|recorded|checked|enforced))\b",
    re.IGNORECASE,
)

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
FILE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
PROSE_PY = re.compile(r'^\s*(#|"""|\'\'\'|"|\')')
MD_EXT = (".md", ".markdown", ".txt", ".rst")


def prose_lines_of(path):
    """Line numbers that are prose in a Python file on disk - every line of every string
    statement (a docstring anywhere, a bare message) and every line carrying a comment.
    None when the file cannot be read or parsed; the caller then reads the hunk instead."""
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        tree = ast.parse(src)
    except Exception:
        return None
    lines = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            end = getattr(node, "end_lineno", None) or node.lineno
            for n in range(node.lineno, end + 1):
                lines.add(n)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except Exception:
        pass
    return lines


def _added_lines(diff_text):
    """[(path, lineno, text, prose_by_hunk)] for every added line, in diff order, with the
    hunk heuristic's verdict beside each - a docstring tracked by a quote seen in the hunk."""
    out = []
    path, lineno, in_doc = None, 0, False
    for raw in diff_text.splitlines():
        m = FILE.match(raw)
        if m:
            path, in_doc = m.group(1), False
            continue
        m = HUNK.match(raw)
        if m:
            lineno = int(m.group(1)) - 1
            continue
        if path is None or raw.startswith("---"):
            continue
        is_md = path.lower().endswith(MD_EXT)
        if raw.startswith("+"):
            lineno += 1
            text = raw[1:]
            if is_md:
                prose = bool(text.strip())
            elif text.count('"""') % 2 == 1 or text.count("'''") % 2 == 1:
                in_doc = not in_doc
                prose = True
            else:
                prose = in_doc or bool(PROSE_PY.match(text))
            out.append((path, lineno, text, prose))
        elif raw.startswith(" "):
            lineno += 1
            if not is_md:
                t = raw[1:]
                if t.count('"""') % 2 == 1 or t.count("'''") % 2 == 1:
                    in_doc = not in_doc
    return out


def claims(diff_text, tree=None):
    """[(path, lineno, text)] - one entry per added prose BLOCK that claims a behaviour.

    A block is a run of consecutive added prose lines (a docstring, a comment run, a
    Markdown paragraph); the entry carries the first line's number and the block's
    text joined. Grouping is the point: on a real diff, listing every line that
    holds `reads` or `writes` produced well over a hundred entries for one file,
    which is a list nobody answers. A block is one claim to answer.

    With `tree`, a `.py` line's prose-ness comes from the file's own AST and tokens;
    without it, or for a file the tree does not hold, from the hunk."""
    added = _added_lines(diff_text)
    known = {}
    if tree:
        for path in set(p for p, _l, _t, _pr in added if p.lower().endswith(".py")):
            got = prose_lines_of(os.path.join(tree, path))
            if got is not None:
                known[path] = got
    out = []
    block = None                      # [path, first_lineno, last_lineno, [lines]]

    def flush():
        if block and any(BEHAVIOUR.search(ln) for ln in block[3]):
            out.append((block[0], block[1], " ".join(s.strip() for s in block[3])))

    for path, lineno, text, by_hunk in added:
        if path in known:
            prose = lineno in known[path] or bool(PROSE_PY.match(text))
        else:
            prose = by_hunk
        if path.lower().endswith(MD_EXT):
            prose = bool(text.strip())
        if prose and block and block[0] == path and block[2] == lineno - 1:
            block[2] = lineno
            block[3].append(text)
        elif prose:
            flush()
            block = [path, lineno, lineno, [text]]
        else:
            flush()
            block = None
    flush()
    return out


def main(argv):
    args = [a for a in argv[1:] if a != "--selftest"]
    tree = os.getcwd()
    if "--tree" in args:
        i = args.index("--tree")
        tree = args[i + 1] if i + 1 < len(args) else tree
        del args[i:i + 2]
    if args and args[0] != "-":
        with io.open(args[0], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    found = claims(text, tree=tree)
    if not found:
        print("no added prose line claims a behaviour - question 1 is n/a for this diff")
        return 0
    print("%d added prose block(s) claim a behaviour; answer each with the line that does it:"
          % len(found))
    for path, lineno, text in found:
        print("  %s:%d  %s" % (path, lineno, text[:110]))
    return 0


def _selftest():
    """The list must find a claim, must not find a code line that merely uses a verb, and
    must see a docstring extended where the hunk shows no quote."""
    import shutil
    import tempfile
    diff = "\n".join([
        "--- a/x.py", "+++ b/x.py", "@@ -1,2 +1,8 @@",
        "+def f():",
        '+    """Refuses a read of a dotenv file.',
        "+",
        '+    Two lines of one docstring are ONE claim to answer, not two."""',
        "+    # the row is chained to its predecessor",
        "+    return check(x)",
        "+    y = 'never'",
        '+    "a bare message the user reads: always denied"',
        "--- a/d.md", "+++ b/d.md", "@@ -1 +1,3 @@",
        "+The guard always denies it.",
        "+",
        "+A heading with no verb of behaviour at all",
    ])
    got = claims(diff)
    texts = [t for _p, _l, t in got]
    cases = [
        ("c1 a docstring claim is listed, and its lines are ONE entry",
         sum(1 for t in texts if "Refuses a read" in t) == 1
         and any("Refuses a read" in t and "ONE claim" in t for t in texts)),
        ("c2 a comment claim is listed",
         any("chained" in t for t in texts)),
        ("c3 a markdown claim is listed with its file",
         any(p == "d.md" and "always denies" in t for p, _l, t in got)),
        ("c4 a CODE line using a verb is NOT listed - `return check(x)` is not prose",
         not any("return check" in t for t in texts)),
        # c5 used to assert that `y = 'never'` is prose. It is an ASSIGNMENT, and the
        # code deliberately reads only a line that BEGINS with a quote - a bare
        # string, which is a message somebody reads. The case claimed a behaviour
        # the code did not have; the code was right. (Question 2, applied here.)
        ("c5 a BARE string line is prose; an assignment holding a string is code",
         any("bare message" in t for t in texts)
         and not any("y = 'never'" in t for t in texts)),
        ("c6 a prose line with no behaviour verb is not listed",
         not any("heading with no verb" in t for t in texts)),
        ("c7 line numbers follow the hunk header",
         any(p == "x.py" and l == 2 for p, l, _t in got)),
        ("c8 a blank line ends a Markdown paragraph, so two paragraphs are two entries",
         sum(1 for p, _l, _t in got if p == "d.md") == 1),
    ]
    # c9: the shape the first version missed - a paragraph added INSIDE an existing
    # docstring, with no quote anywhere in the hunk. Read off the file it is prose;
    # read off the hunk it is code. An eval run of the skill hit this on a thirty-line
    # paragraph and was told question 1 did not apply.
    tmp = tempfile.mkdtemp()
    try:
        src = "\n".join([
            "def g():",
            '    """One line of prose.',
            "",
            "    line three of prose.",
            "    line four of prose.",
            "    line five of prose.",
            "    The guard refuses any read of the file, and records it.",
            "    line seven of prose.",
            '    """',
            "    return 1",
            "",
        ])
        with io.open(os.path.join(tmp, "g.py"), "w", encoding="utf-8") as fh:
            fh.write(src)
        mid = "\n".join([
            "--- a/g.py", "+++ b/g.py", "@@ -5,3 +5,4 @@",
            "     line four of prose.",
            "     line five of prose.",
            "+    The guard refuses any read of the file, and records it.",
            "     line seven of prose.",
        ])
        with_tree = claims(mid, tree=tmp)
        without_tree = claims(mid)
        cases += [
            ("c9 a paragraph added inside a docstring, no quote in the hunk, IS listed when "
             "the tree is readable - the file's own AST says it is prose",
             any(p == "g.py" and l == 7 and "refuses any read" in t for p, l, t in with_tree)),
            ("c9b ...and without the tree the same hunk reads as code - the fallback, pinned "
             "so nobody widens the heuristic instead of passing the tree",
             without_tree == []),
        ]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = 0
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
        failed += 0 if ok else 1
    print("\n%s: %d/%d cases passed" % ("ALL PASS" if not failed else "SELFTEST FAILED",
                                       len(cases) - failed, len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    raise SystemExit(main(sys.argv))
