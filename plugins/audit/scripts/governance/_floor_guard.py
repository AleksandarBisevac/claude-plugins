#!/usr/bin/env python3
"""
Which moves in a task's diff make a test easier to pass or a checker quieter.

WHY THIS IS A MODULE. The red-first helper proves that a NEW test can fail, and
the `tests-moved` refusal covers a test file changed after its proof; neither
reads an EXISTING test being weakened. A measured session edited a protected
test's assertion until it passed, and nothing in the plugin would have seen it.
This module is the reading that sees it. It decides nothing and refuses nothing:
it returns what it found, and a caller reports it.

GIT IS KEPT OUT. The input is the diff's text and two reader callables - one for
a file at the base, one for it in the tree - so every case runs with no
repository and no process. A reader returns the file's text, None when the file
does not exist on that side, and raises `OSError` (or `ValueError` for text that
will not decode) when it cannot be read. The diff is git's unified form with its
default `a/` and `b/` prefixes; a rename is read base-old against tree-new.

THE MOVES, NAMED IN `MOVES`:
  * a test file deleted;
  * an existing test definition changed. For Python each test the runner would
    run - a function, or a method under its `Class.method` name, whose name
    starts with `TEST_PREFIX` - is compared between the base and tree copies by
    `ast.dump` - line numbers excluded, decorators included, a leading
    docstring dropped - so a test appended beside it is no change and a
    decorator added to it is one. Helpers, fixtures and case-table functions
    are not compared: a suite that adds a case changes its table every time,
    and that is not a weaker bar. A test that disappears is reported unless a
    new test with the same body appeared (a rename). For any other language the
    assertion lines removed from a test file are reported, read through
    `ASSERTIONS`;
  * a skip added to a test file (`SKIPS`);
  * a suppression whose CODE is new to the file, read in comments only
    (`SUPPRESSIONS`), so one inside a fixture string - text a test feeds to
    something else - is not. A code is the marker's kind with one rule code
    out of the comment (`noqa E402`, `type: ignore attr-defined`), and a
    blanket marker is its own code; a code some comment of the base copy
    already carries is the file's existing contract and gives no finding, so
    in a file new to the diff every code is new. A caller's `accepted` codes
    are never reported;
  * a stub added in non-test code: `raise NotImplementedError`,
    `throw new Error('Not implemented')`, an except or catch with an empty body.
What a test file is comes from `_filed_returns.is_test_path`, the scripts-side
definition the red-first helper and the task writer already read.

THREE ANSWERS, AND ONLY ONE IS CLEAN - the shape `_runner_collects` set.
`FINDINGS` when a move was found; `COULD_NOT_TELL` with its reason when no move
was found and something could not be read (a diff that does not parse, a file
a reader could not produce, a Python copy that does not compile, a tree that no
longer holds the lines the diff says it added); `CLEAN` only when every changed
file was read. A could-not-tell beside a finding does not hide the finding and
is not dropped: `couldNotTell` lists it whatever the answer is. A changed test
the caller DECLARED (the task's own `tests.add`) is returned under `declared`,
never as a finding.

A MOVE IS ONLY A MOVE WHEN IT IS NEW. Marks are read over the whole of both
copies of a changed file - so a catch body emptied by a pure removal, whose
`catch` line the diff never touches, is still seen - and each tree skip or stub
is paired away against a base mark with the same text first, then against any
base mark of the same kind in the same file. A suppression is not paired: it is
new when one of its codes is in no comment of the base copy. Every unchanged
mark cancels against itself; a `# noqa` that moved, or whose line's code
changed, is no finding; an assertion line is paired by its exact text only, so
one rewritten in place still reads as removed. The diff's own lines are what
each copy is checked against, so a reader handing back a different tree is
could-not-tell rather than a reading of the wrong file.

WHAT THIS READING CANNOT SEE. The non-Python scanner knows quotes and comments,
not regex literals or heredocs, so a quote inside a JavaScript regex mis-masks
the rest of that line. Suppressions are read per file: one carried with code
moved to another file reads as added there. A code the base already carries is
no finding however many more lines it is added to, and the kind is read without
its scope, so an `eslint-disable-next-line <rule>` the base holds hides the same
rule disabled for the whole file. A Python test file the diff modifies, where
neither copy defines a test - a suite written as case rows - has no definition
this reading can compare: when its code changed it is listed under `notRead` with
`move: definition-changed`, never clean in silence and never a finding. A
declared non-Python test is declared by file, since its lines map to no case
name. A file whose extension has no comment syntax here is not read and is
listed under `notRead` with `move` None.

This module carries no `--selftest` of its own; its cases live in
`tests/test__floor_guard.py`.
"""

import ast
import bisect
import copy
import io
import os
import re
import sys
import tokenize

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

import _filed_returns  # noqa: E402  (is_test_path: what a test file is)

FINDINGS = "findings"
CLEAN = "clean"
COULD_NOT_TELL = "could-not-tell"

TEST_DELETED = "test-deleted"
DEFINITION_CHANGED = "definition-changed"
SKIP_ADDED = "skip-added"
SUPPRESSION_ADDED = "suppression-added"
STUB_ADDED = "stub-added"
MOVES = (TEST_DELETED, DEFINITION_CHANGED, SKIP_ADDED, SUPPRESSION_ADDED, STUB_ADDED)

# The one definition of a test path, borrowed rather than restated.
is_test_path = _filed_returns.is_test_path

# --- tables ---------------------------------------------------------------------
# Families of comment and string syntax. `py` is read by `tokenize` and `ast`;
# `c` and `hash` by the scanner below.
PY = "py"
C_LIKE = "c"
HASH = "hash"
FAMILIES = (
    (PY, (".py", ".pyi")),
    (C_LIKE, (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx", ".go",
              ".java", ".kt", ".kts", ".scala", ".c", ".h", ".cc", ".cpp", ".hpp",
              ".cs", ".rs", ".swift", ".dart", ".php", ".css", ".scss", ".less")),
    (HASH, (".sh", ".bash", ".zsh", ".rb", ".yml", ".yaml", ".toml", ".cfg", ".ini",
            ".conf", ".pl", ".r")),
)

# (name, pattern over a line's CODE, families it applies to)
SKIPS = (
    ("pytest.mark.skip", r"\bpytest\.mark\.(?:skip|skipif|xfail)\b", (PY,)),
    ("pytest.skip", r"\bpytest\.(?:skip|xfail)\s*\(", (PY,)),
    ("unittest.skip", r"\bunittest\.(?:skip\w*|expectedFailure)\b", (PY,)),
    ("skipTest", r"\.skipTest\s*\(", (PY,)),
    ("@skip", r"^\s*@(?:skip|skipIf|skipUnless|expectedFailure)\b", (PY,)),
    (".skip(", r"\.skip\s*\(", (C_LIKE, HASH)),
    ("xit(", r"\b(?:xit|xdescribe|xtest)\s*\(", (C_LIKE, HASH)),
    (".todo(", r"\.todo\s*\(", (C_LIKE,)),
    ("t.Skip", r"\bt\.Skip(?:f|Now)?\s*\(", (C_LIKE,)),
)

# (name, pattern over a line's COMMENT text, pattern for its codes or None) -
# every family. The codes pattern is matched right where the marker ends and its
# group 1 is split on commas and blanks; a marker with no codes there is a
# blanket one, whose code is None - its own code, never a wildcard.
SUPPRESSIONS = (
    ("noqa", r"\bnoqa\b",
     r":[ \t]*([A-Za-z]+[0-9]+(?:[ \t,]+[A-Za-z]+[0-9]+)*)"),
    ("type: ignore", r"\btype:\s*ignore\b", r"\[([^\]]*)\]"),
    ("eslint-disable", r"\beslint-disable",
     r"(?:-next-line|-line)?[ \t]+([@A-Za-z][\w@/.-]*(?:[ \t]*,[ \t]*[@A-Za-z][\w@/.-]*)*)"),
    ("@ts-ignore", r"@ts-ignore\b", None),
    ("@ts-expect-error", r"@ts-expect-error\b", None),
    ("istanbul ignore", r"\bistanbul\s+ignore\b", r"[ \t]+(\w+)"),
    ("nosemgrep", r"\bnosemgrep\b", r":[ \t]*([\w.-]+(?:[ \t]*,[ \t]*[\w.-]+)*)"),
    ("gitleaks:allow", r"\bgitleaks:allow\b", None),
    ("Stryker disable", r"\bStryker\s+disable\b",
     r"[ \t]+(?:next-line[ \t]+)?(\w+(?:,\w+)*)"),
    ("pragma: no cover", r"\bpragma:\s*no\s*cover\b", None),
)

# What a test is to the runner: a function or method whose name starts with this.
# One fixed prefix rather than a table, because unittest's default loader and
# pytest's default collection agree on it and both compare it case-sensitively.
TEST_PREFIX = "test"

# (name, pattern over a line's CODE) - test files outside Python.
ASSERTIONS = (
    ("expect(", r"\bexpect\s*\("),
    ("assert", r"\bassert\w*"),
    ("should", r"\bshould\b"),
    ("t.Error/t.Fatal", r"\bt\.(?:Errorf?|Fatalf?|FailNow|Fail)\s*\("),
)

# Stubs outside Python, over the whole CODE text (a catch body may span lines).
_EMPTY_CATCH = re.compile(r"\bcatch\b\s*(?:\([^)]*\))?\s*\{\s*\}")
# Over the RAW text, because the message is a string; the `throw` must be code.
_NOT_IMPLEMENTED = re.compile(r"\bthrow\s+new\s+Error\s*\(\s*['\"`]\s*not\s+implemented",
                              re.IGNORECASE)

_COMPILED = dict((name, re.compile(pat)) for name, pat, _f in SKIPS)
_COMPILED.update((name, re.compile(pat)) for name, pat, _c in SUPPRESSIONS)
_COMPILED.update((name, re.compile(pat)) for name, pat in ASSERTIONS)
_CODES = dict((name, re.compile(codes)) for name, _p, codes in SUPPRESSIONS if codes)


def family(path):
    """The comment family of `path` by its extension, or None when this reading
    knows none for it."""
    low = str(path or "").lower()
    return next((fam for fam, exts in FAMILIES if low.endswith(exts)), None)


# --- the diff -------------------------------------------------------------------

class _Unparsed(Exception):
    pass


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_IGNORED_HEADERS = ("index ", "similarity index ", "dissimilarity index ",
                    "old mode ", "new mode ", "copy from ", "copy to ")


def _unquote(text):
    """A path as git prints it: C-quoted when it holds unusual bytes."""
    if not text.startswith('"'):
        return text
    try:
        raw = ast.literal_eval("b" + text)
    except (ValueError, SyntaxError) as exc:
        raise _Unparsed("a quoted path does not read (%s): %s" % (exc, text))
    return raw.decode("utf-8", "replace")


def _header_path(text, prefix):
    text = text.rstrip("\t")
    if text == "/dev/null":
        return None
    text = _unquote(text)
    return text[len(prefix):] if text.startswith(prefix) else text


def _git_header_paths(rest):
    """The two paths of `diff --git a/P b/P` when they are the same file; None
    otherwise - a rename's paths come from its own `rename` lines."""
    half = (len(rest) - 1) // 2
    left, right = rest[:half], rest[half + 1:]
    if left.startswith("a/") and right.startswith("b/") and left[2:] == right[2:]:
        return left[2:]
    return None


def _new_record():
    return {"old": None, "new": None, "status": "modified", "binary": False,
            "hunks": 0, "added": [], "removed": [], "headerPath": None}


def _read_hunk(lines, i, rec):
    """Consume the hunk whose header is `lines[i]`; returns the index after it."""
    m = _HUNK.match(lines[i])
    if not m:
        raise _Unparsed("a hunk header does not read: %r" % lines[i])
    o_start, o_count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
    n_start, n_count = int(m.group(3)), int(m.group(4) if m.group(4) is not None else 1)
    old_ln = o_start if o_count else o_start + 1
    new_ln = n_start if n_count else n_start + 1
    left_old, left_new = o_count, n_count
    i += 1
    while left_old > 0 or left_new > 0:
        if i >= len(lines):
            raise _Unparsed("a hunk of %s ends %d base and %d tree line(s) short"
                            % (rec["new"] or rec["old"], left_old, left_new))
        line = lines[i].rstrip("\r")
        tag, body = (line[:1], line[1:]) if line else (" ", "")
        if tag == "\\":
            i += 1
            continue
        if tag == " ":
            if left_old <= 0 or left_new <= 0:
                raise _Unparsed("a hunk of %s holds more lines than its header "
                                "counts" % (rec["new"] or rec["old"]))
            old_ln, new_ln, left_old, left_new = old_ln + 1, new_ln + 1, left_old - 1, left_new - 1
        elif tag == "-" and left_old > 0:
            rec["removed"].append((old_ln, body))
            old_ln, left_old = old_ln + 1, left_old - 1
        elif tag == "+" and left_new > 0:
            rec["added"].append((new_ln, body))
            new_ln, left_new = new_ln + 1, left_new - 1
        else:
            raise _Unparsed("a hunk of %s holds a line that is not context, a "
                            "removal or an addition: %r" % (rec["new"] or rec["old"], line))
        i += 1
    while i < len(lines) and lines[i].startswith("\\"):
        i += 1
    rec["hunks"] += 1
    return i


def parse_diff(text):
    """The files a unified git diff changes, each with the lines it added and
    removed. Raises `_Unparsed` naming what did not read."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    records, rec, i = [], None, 0
    while i < len(lines):
        line = lines[i].rstrip("\r")
        if line.startswith("diff --git "):
            rec = _new_record()
            records.append(rec)
            rec["headerPath"] = _git_header_paths(line[len("diff --git "):])
        elif line.startswith("--- ") and (rec is None or rec["hunks"]):
            rec = _new_record()
            records.append(rec)
            rec["old"] = _header_path(line[4:], "a/")
        elif rec is None:
            if line.strip():
                raise _Unparsed("text before the first file header: %r" % line)
        elif line.startswith("@@"):
            _fill_paths(rec)
            i = _read_hunk(lines, i, rec)
            continue
        elif rec["hunks"] and line.strip():
            raise _Unparsed("text after a hunk of %s that is no header: %r"
                            % (rec["new"] or rec["old"], line))
        else:
            _header_line(line, rec)
        i += 1
    for rec in records:
        _fill_paths(rec)
    if text.strip() and not records:
        raise _Unparsed("the text names no file")
    return records


def _header_line(line, rec):
    if line.startswith("--- "):
        rec["old"] = _header_path(line[4:], "a/")
        if rec["old"] is None:
            rec["status"] = "added"
    elif line.startswith("+++ "):
        rec["new"] = _header_path(line[4:], "b/")
        if rec["new"] is None:
            rec["status"] = "deleted"
    elif line.startswith("new file mode"):
        rec["status"] = "added"
    elif line.startswith("deleted file mode"):
        rec["status"] = "deleted"
    elif line.startswith("rename from "):
        rec["old"], rec["status"] = _unquote(line[len("rename from "):]), "renamed"
    elif line.startswith("rename to "):
        rec["new"] = _unquote(line[len("rename to "):])
    elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
        rec["binary"] = True
    elif line.startswith(_IGNORED_HEADERS) or not line.strip():
        pass
    else:
        raise _Unparsed("a header line does not read: %r" % line)


def _fill_paths(rec):
    """Complete a record's two paths from its status and the `diff --git` line."""
    if rec["status"] == "added":
        rec["old"] = None
        rec["new"] = rec["new"] or rec["headerPath"]
    elif rec["status"] == "deleted":
        rec["new"] = None
        rec["old"] = rec["old"] or rec["headerPath"]
    else:
        rec["old"] = rec["old"] or rec["headerPath"] or rec["new"]
        rec["new"] = rec["new"] or rec["headerPath"] or rec["old"]
    if not (rec["old"] or rec["new"]):
        raise _Unparsed("a file section names no path this reading can take")


# --- masking: which characters are code, which are comment ----------------------
# Both readers return two texts the length of the source with the same newlines:
# the code with every string's and comment's characters blanked, and the comments
# alone. Offsets therefore line up with the raw text, line for line.

def _blank(chars, start, end):
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = " "


def _empty_like(text):
    return ["\n" if ch == "\n" else " " for ch in text]


def _scan_python(text):
    """(code, comments) of Python source, through `tokenize`. Raises
    `tokenize.TokenError` or `SyntaxError` for source that does not tokenize."""
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    size = len(text)

    def offset(pos):
        return min(starts[pos[0] - 1] + pos[1], size) if pos[0] - 1 < len(starts) else size

    code, comments = list(text), _empty_like(text)
    stringish = ("STRING", "FSTRING_MIDDLE", "TSTRING_MIDDLE")
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        name = tokenize.tok_name.get(tok.type, "")
        if name == "COMMENT":
            a, b = offset(tok.start), offset(tok.end)
            comments[a:b] = list(text[a:b])
            _blank(code, a, b)
        elif name in stringish:
            _blank(code, offset(tok.start), offset(tok.end))
    return "".join(code), "".join(comments)


def _scan_other(text, fam):
    """(code, comments) for the `c` and `hash` families: quotes and comments,
    nothing more - see the module docstring for what that misses."""
    code, comments = list(text), _empty_like(text)
    quotes = "'\"`" if fam == C_LIKE else "'\""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if (fam == HASH and c == "#") or (fam == C_LIKE and text.startswith("//", i)):
            end = text.find("\n", i)
            end = n if end < 0 else end
        elif fam == C_LIKE and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
        elif c in quotes:
            end = _string_end(text, i, c)
            _blank(code, i + 1, max(i + 1, end - 1))
            i = end
            continue
        else:
            i += 1
            continue
        comments[i:end] = list(text[i:end])
        _blank(code, i, end)
        i = end
    return "".join(code), "".join(comments)


def _string_end(text, i, quote):
    """Index just past the string opened at `i`. A `'` or `"` string stops at
    the line's end when unclosed; a backtick one may span lines."""
    n, j = len(text), i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch == "\n" and quote != "`":
            return j
        j += 1
    return n


# --- marks ----------------------------------------------------------------------
# A mark is one place a move could be: (move, kind, first line, last line, the
# stripped text of its first line). Marks are computed for a whole copy of a
# file and paired base against tree.

def _mark(move, kind, start, end, raw_lines):
    key = raw_lines[start - 1].strip() if 0 < start <= len(raw_lines) else ""
    return (move, kind, start, end, key)


def _line_of(starts, offset):
    return bisect.bisect_right(starts, offset)


def _line_starts(text):
    starts, at = [], 0
    for line in text.split("\n"):
        starts.append(at)
        at += len(line) + 1
    return starts


def _suppression_keys(text, anchored=False):
    """[(kind, end, ((kind, code), ...))] for each suppression kind `text`
    carries, read through `SUPPRESSIONS`; a blanket one's single key has code
    None. `anchored` reads only a marker at the start of `text` - the form a
    caller's accepted entry is written in."""
    found = []
    for name, _pat, _codes in SUPPRESSIONS:
        m = _COMPILED[name].match(text) if anchored else _COMPILED[name].search(text)
        if not m:
            continue
        codes_at = _CODES[name].match(text, m.end()) if name in _CODES else None
        codes = [c for c in re.split(r"[\s,]+", codes_at.group(1)) if c] if codes_at else []
        keys = tuple((name, c) for c in codes) or ((name, None),)
        found.append((name, codes_at.end() if codes_at else m.end(), keys))
    return found


def _line_marks(raw_lines, code_lines, comment_lines, fam, test):
    """The skip, suppression and assertion marks read one line at a time. A
    suppression mark carries a sixth field: its (kind, code) keys."""
    marks = []
    for idx, (code, comment) in enumerate(zip(code_lines, comment_lines)):
        ln = idx + 1
        for name, _end, keys in _suppression_keys(comment):
            marks.append(_mark(SUPPRESSION_ADDED, name, ln, ln, raw_lines) + (keys,))
        if not test:
            continue
        for name, _pat, fams in SKIPS:
            if fam in fams and _COMPILED[name].search(code):
                marks.append(_mark(SKIP_ADDED, name, ln, ln, raw_lines))
        if fam != PY:
            hit = next((name for name, _p in ASSERTIONS if _COMPILED[name].search(code)), None)
            if hit:
                marks.append(_mark("assertion", hit, ln, ln, raw_lines))
    return marks


def _python_stubs(tree, raw_lines):
    marks = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and _is_not_implemented(node.exc):
            marks.append(_mark(STUB_ADDED, "raise NotImplementedError", node.lineno,
                               node.end_lineno or node.lineno, raw_lines))
        elif isinstance(node, ast.ExceptHandler) and all(_is_empty(s) for s in node.body):
            marks.append(_mark(STUB_ADDED, "empty except", node.lineno,
                               node.end_lineno or node.lineno, raw_lines))
    return marks


def _is_not_implemented(exc):
    target = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(target, ast.Name) and target.id == "NotImplementedError"


def _is_empty(stmt):
    return isinstance(stmt, ast.Pass) or (
        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is Ellipsis)


def _other_stubs(text, code, raw_lines):
    starts = _line_starts(text)
    marks = [_mark(STUB_ADDED, "empty catch", _line_of(starts, m.start()),
                   _line_of(starts, m.end() - 1), raw_lines)
             for m in _EMPTY_CATCH.finditer(code)]
    marks.extend(_mark(STUB_ADDED, "throw Not implemented", _line_of(starts, m.start()),
                       _line_of(starts, m.start()), raw_lines)
                 for m in _NOT_IMPLEMENTED.finditer(text)
                 if code[m.start():m.start() + 5] == "throw")
    return marks


def _side_marks(text, tree, fam, test):
    """Every mark of one copy of a file."""
    raw_lines = [l.rstrip("\r") for l in text.split("\n")]
    if fam == PY:
        code, comments = _scan_python(text)
    else:
        code, comments = _scan_other(text, fam)
    marks = _line_marks(raw_lines, code.split("\n"), comments.split("\n"), fam, test)
    if not test:
        marks.extend(_python_stubs(tree, raw_lines) if fam == PY
                     else _other_stubs(text, code, raw_lines))
    return marks


def _new_suppressions(base_marks, tree_marks, accepted):
    """[(tree mark, its keys new to the file)]: a suppression whose (kind, code)
    no comment of the base copy carries and the caller did not accept. A key
    the base already holds is the file's existing contract, so repeating it is
    not a move, wherever it sits."""
    held = set(k for m in base_marks for k in m[5])
    out = []
    for mark in tree_marks:
        new = [k for k in mark[5] if k not in held and k not in accepted]
        if new:
            out.append((mark, new))
    return out


def _key_text(keys):
    return ", ".join(k[0] if k[1] is None else "%s %s" % k for k in keys)


def _pair(base_marks, tree_marks, by_kind):
    """(base marks left unpaired, tree marks left unpaired): paired by exact
    text first, then - when `by_kind` - by kind alone, in order."""
    base_left, tree_left = list(base_marks), []
    for mark in tree_marks:
        twin = next((b for b in base_left if (b[0], b[1], b[4]) == (mark[0], mark[1], mark[4])),
                    None)
        if twin is None:
            tree_left.append(mark)
        else:
            base_left.remove(twin)
    if not by_kind:
        return base_left, tree_left
    tree_rest = []
    for mark in tree_left:
        twin = next((b for b in base_left if (b[0], b[1]) == (mark[0], mark[1])), None)
        if twin is None:
            tree_rest.append(mark)
        else:
            base_left.remove(twin)
    return base_left, tree_rest


# --- Python definitions -----------------------------------------------------------

def _definitions(tree):
    """{qualified name: node} for the module's functions and every class's
    methods (`Class.method`, `Outer.Inner.method`). A name defined twice keeps
    the LAST, which is the one Python runs - so a weaker test appended under an
    existing name is a change to that name."""
    out = {}

    def walk(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".")
    walk(tree.body, "")
    return out


def _dump(node, anonymous=False):
    """`ast.dump` of a definition without its line numbers and leading
    docstring; `anonymous` also drops its name, to recognise a rename."""
    clone = copy.copy(node)
    body = list(node.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    clone.body = body
    if anonymous:
        clone.name = ""
    return ast.dump(clone)


def _tests_only(defs):
    """The definitions a runner would run: the last name segment starts with
    `TEST_PREFIX`. Helpers, fixtures and case-table functions fall away."""
    return dict((q, n) for q, n in defs.items()
                if q.rsplit(".", 1)[-1].startswith(TEST_PREFIX))


def _compare_definitions(base_tree, tree_tree, new):
    """(changed, renamed): changed is a list of (what, line, side) and renamed
    a list of {from, to, line}. Only test definitions are compared."""
    base_defs = _tests_only(_definitions(base_tree))
    tree_defs = _tests_only(_definitions(tree_tree))
    fresh = dict((q, n) for q, n in tree_defs.items() if q not in base_defs)
    changed, renamed = [], []
    for qual, node in sorted(base_defs.items(), key=lambda kv: kv[1].lineno):
        if qual in tree_defs:
            if _dump(node) != _dump(tree_defs[qual]):
                changed.append((qual, "definition `%s` differs from its base copy" % qual,
                                tree_defs[qual].lineno, "tree"))
            continue
        shape = _dump(node, anonymous=True)
        twin = next((q for q in sorted(fresh) if _dump(fresh[q], anonymous=True) == shape),
                    None)
        if twin is None:
            changed.append((qual, "definition `%s` is gone from the tree copy" % qual,
                            node.lineno, "base"))
        else:
            renamed.append({"path": new, "from": qual, "to": twin,
                            "line": fresh.pop(twin).lineno})
    return changed, renamed


# --- declared -------------------------------------------------------------------

def _declared_index(declared):
    """(whole files, {path: set of case names}) from `path` and `path::case`
    entries; a pytest-style `Class::method` case is read as `Class.method`."""
    files, cases = set(), {}
    for entry in declared or ():
        path, sep, case = str(entry).replace("\\", "/").partition("::")
        if not sep or not case:
            files.add(path)
        else:
            cases.setdefault(path, set()).add(case.replace("::", "."))
    return files, cases


def _is_declared(index, paths, qual=None):
    files, cases = index
    for path in [p for p in paths if p]:
        if path in files:
            return True
        names = cases.get(path, set())
        if qual is None and names:
            return True
        if qual is not None and (qual in names or qual.rsplit(".", 1)[-1] in names):
            return True
    return False


# --- one file ---------------------------------------------------------------------

def _finding(move, path, line, side, what):
    return {"move": move, "path": path, "line": line, "side": side, "what": what}


def _read(reader, path, side):
    """(text, problem) of one copy; text None and problem None when the reader
    says the file is not there."""
    try:
        text = reader(path)
    except (OSError, ValueError) as exc:
        return None, "the %s copy of %s cannot be read (%s)" % (side, path, exc)
    if text is not None and not isinstance(text, str):
        return None, "the %s reader gave %s for %s, not text" % (side, type(text).__name__, path)
    return text, None


def _lines_hold(text, pairs, side, path):
    """A problem when the copy does not hold the lines the diff says it does."""
    lines = [l.rstrip("\r") for l in text.split("\n")]
    for ln, body in pairs:
        if ln < 1 or ln > len(lines) or lines[ln - 1] != body:
            return ("the %s copy of %s does not hold line %d as the diff gives it, so "
                    "the diff and the copy describe different trees" % (side, path, ln))
    return None


def _copies(rec, read_base, read_tree):
    """(base text, tree text, problem) for a file the diff changes."""
    out = {}
    for side, reader, path, present in (("base", read_base, rec["old"], rec["status"] != "added"),
                                        ("tree", read_tree, rec["new"], True)):
        if not present:
            out[side] = None
            continue
        text, problem = _read(reader, path, side)
        if problem:
            return None, None, problem
        if text is None:
            return None, None, ("the diff changes %s, but the %s reader has no such file"
                                % (path, side))
        out[side] = text
    problem = (_lines_hold(out["tree"], rec["added"], "tree", rec["new"])
               or (out["base"] is not None
                   and _lines_hold(out["base"], rec["removed"], "base", rec["old"])))
    return out["base"], out["tree"], problem or None


def _parse_python(text, side, path):
    if text is None:
        return None, None
    try:
        return ast.parse(text), None
    except (SyntaxError, ValueError) as exc:
        return None, "the %s copy of %s does not compile (%s)" % (side, path, exc)


def _one_file(rec, read_base, read_tree, index, accepted):
    """{findings, declared, renamed, problem, notRead} for one file of the diff.
    `notRead` is one entry or None; its `move` is None when no move was read,
    and names the one move left unread otherwise."""
    out = {"findings": [], "declared": [], "renamed": [], "problem": None, "notRead": None}
    path = rec["new"] or rec["old"]
    if rec["status"] == "deleted":
        if is_test_path(rec["old"]):
            out["findings"].append(_finding(TEST_DELETED, rec["old"], 1, "base",
                                            "test file deleted"))
        return out
    if not rec["hunks"]:
        return out
    fam = family(path)
    if rec["binary"] or fam is None:
        out["notRead"] = {"path": path, "move": None, "reason": "binary" if rec["binary"]
                          else "no comment or string syntax this reading knows for its name"}
        return out
    test = is_test_path(path)
    base, tree, problem = _copies(rec, read_base, read_tree)
    base_ast = tree_ast = None
    if problem is None and fam == PY:
        base_ast, problem = _parse_python(base, "base", rec["old"])
    if problem is None and fam == PY:
        tree_ast, problem = _parse_python(tree, "tree", rec["new"])
    if problem is None:
        try:
            findings, owned, renamed, unread = _collect(
                rec, (base, base_ast), (tree, tree_ast), fam, test, (index, accepted))
        except (tokenize.TokenError, SyntaxError) as exc:
            problem = "%s does not tokenize (%s)" % (path, exc)
    if problem:
        out["problem"] = problem
        return out
    out.update(findings=findings, declared=owned, renamed=renamed, notRead=unread)
    return out


def _collect(rec, base, tree, fam, test, ask):
    """(findings, declared, renamed, notRead entry or None) for one file whose
    copies were read; `base` and `tree` are each (text, Python AST or None) and
    `ask` is (declared index, accepted suppression keys)."""
    index, accepted = ask
    path, paths = rec["new"], (rec["new"], rec["old"])
    base_marks = _side_marks(base[0], base[1], fam, test) if base[0] is not None else []
    tree_marks = _side_marks(tree[0], tree[1], fam, test)
    findings, owned, renamed, unread = [], [], [], None
    gone, _unused = _pair([m for m in base_marks if m[0] == "assertion"],
                          [m for m in tree_marks if m[0] == "assertion"], by_kind=False)
    for mark in gone:
        found = _finding(DEFINITION_CHANGED, rec["old"], mark[2], "base",
                         "assertion line removed (%s): %s" % (mark[1], mark[4]))
        (owned if _is_declared(index, paths) else findings).append(found)
    _old, added = _pair([m for m in base_marks if m[0] in (SKIP_ADDED, STUB_ADDED)],
                        [m for m in tree_marks if m[0] in (SKIP_ADDED, STUB_ADDED)],
                        by_kind=True)
    findings.extend(_finding(mark[0], path, mark[2], "tree", "%s (%s): %s"
                             % (_ADDED_WORD[mark[0]], mark[1], mark[4])) for mark in added)
    fresh = _new_suppressions([m for m in base_marks if m[0] == SUPPRESSION_ADDED],
                              [m for m in tree_marks if m[0] == SUPPRESSION_ADDED], accepted)
    findings.extend(_finding(SUPPRESSION_ADDED, path, mark[2], "tree",
                             "suppression added (%s, new to the file): %s"
                             % (_key_text(new), mark[4])) for mark, new in fresh)
    if fam == PY and test and base[1] is not None:
        changed, renamed = _compare_definitions(base[1], tree[1], path)
        for qual, what, line, side in changed:
            found = _finding(DEFINITION_CHANGED, path if side == "tree" else rec["old"],
                             line, side, what)
            (owned if _is_declared(index, paths, qual) else findings).append(found)
        unread = _uncompared(base[1], tree[1], path)
    return findings, owned, renamed, unread


def _uncompared(base_ast, tree_ast, path):
    """The notRead entry for a Python test file whose code changed while neither
    copy defines a test the runner would run - a suite kept as case rows, whose
    cases are not definitions this reading can compare. None otherwise: a file
    with a test definition was compared, and one whose code did not change (a
    comment edit) has nothing to compare."""
    if _tests_only(_definitions(base_ast)) or _tests_only(_definitions(tree_ast)):
        return None
    if ast.dump(base_ast) == ast.dump(tree_ast):
        return None
    return {"path": path, "move": DEFINITION_CHANGED,
            "reason": "its code changed, but neither copy defines a function or method "
                      "named %s*, so its cases are not definitions this reading can "
                      "compare" % TEST_PREFIX}


_ADDED_WORD = {SKIP_ADDED: "skip added", SUPPRESSION_ADDED: "suppression added",
               STUB_ADDED: "stub added"}


# --- the question -----------------------------------------------------------------

def _order(found):
    return (found["path"], found["line"], found["move"])


def _result(answer, basis, findings=(), declared=(), renamed=(), cannot=(), not_read=()):
    return {"answer": answer, "basis": basis,
            "findings": sorted(findings, key=_order), "declared": sorted(declared, key=_order),
            "renamed": list(renamed), "couldNotTell": list(cannot), "notRead": list(not_read)}


def _accepted_keys(accepted):
    """(set of (kind, code), problem). Each entry is written as the comment would
    be - `noqa: E402`, `type: ignore[attr-defined]`, `eslint-disable no-console`,
    `noqa` for the blanket one - and read by the same tables, so it matches by
    kind and exact code: blanks around it and between codes are free, the
    marker and the code are case-sensitive as `SUPPRESSIONS` reads them, and a
    prefix of a code is another code. An entry those tables do not read whole
    is a problem rather than an entry silently matching nothing."""
    if isinstance(accepted, str) or not isinstance(accepted, (list, tuple, set, frozenset)):
        return set(), ("accepted must be a sequence of suppression texts, not %s"
                       % type(accepted).__name__)
    keys = set()
    for entry in accepted:
        text = entry.strip() if isinstance(entry, str) else None
        read = _suppression_keys(text, anchored=True) if text else []
        whole = [r for r in read if r[1] == len(text)]
        if not whole:
            return set(), ("the accepted entry %r is not a suppression this reading "
                           "knows, written as its comment would be" % (entry,))
        keys.update(whole[0][2])
    return keys, None


def find_moves(diff, read_base, read_tree, declared=(), accepted=()):
    """The moves in `diff` that lower the bar.

    `diff` is the task's unified diff against its base (git's form); `read_base`
    and `read_tree` each take a repository-relative path and return its text,
    None when it does not exist on that side, or raise `OSError`/`ValueError`
    when it cannot be read. `declared` holds the task's own test paths, each
    `path` or `path::case`: a change to one of those is the task's to make.
    `accepted` holds suppression codes never reported, each written as its
    comment would be (`noqa: E402`); `_accepted_keys` says how one matches, and
    an entry it cannot read makes the answer could-not-tell before any file is.

    Returns {"answer": FINDINGS | CLEAN | COULD_NOT_TELL,
             "basis": the sentence that makes the answer true,
             "findings": [{move, path, line, side, what}], sorted,
             "declared": the same shape, for changes the task declared,
             "renamed": [{path, from, to, line}] - definitions renamed unchanged,
             "couldNotTell": [{path, reason}] - kept whatever the answer,
             "notRead": [{path, move, reason}] - `move` None for a file with no
                        syntax known here, read for no move; a move's name for a
                        file read for every move but that one}.
    `side` says which copy `line` counts in: "base" for something that is gone.
    """
    if not isinstance(diff, str):
        return _result(COULD_NOT_TELL, "no diff was given (%s), so nothing was read"
                       % type(diff).__name__)
    keys, problem = _accepted_keys(accepted)
    if problem:
        return _result(COULD_NOT_TELL, "%s, so nothing was read" % problem)
    try:
        records = parse_diff(diff)
    except _Unparsed as exc:
        return _result(COULD_NOT_TELL, "the diff does not parse: %s" % (exc,))
    if not records:
        return _result(CLEAN, "the diff changes no file, so there was nothing to read")
    index = _declared_index(declared)
    findings, owned, renamed, cannot, not_read = [], [], [], [], []
    for rec in records:
        got = _one_file(rec, read_base, read_tree, index, keys)
        findings.extend(got["findings"])
        owned.extend(got["declared"])
        renamed.extend(got["renamed"])
        if got["problem"]:
            cannot.append({"path": rec["new"] or rec["old"], "reason": got["problem"]})
        if got["notRead"]:
            not_read.append(got["notRead"])
    tail = _tail(owned, cannot, not_read)
    if findings:
        answer, basis = FINDINGS, ("%d move(s) that lower the bar across %d file(s) of "
                                   "the diff%s" % (len(findings), len(records), tail))
    elif cannot:
        answer, basis = COULD_NOT_TELL, ("; ".join(c["reason"] for c in cannot)
                                         + _tail(owned, (), not_read))
    else:
        unread = [n for n in not_read if n["move"] is None]
        answer, basis = CLEAN, ("read %d of the diff's %d file(s) and found none of the "
                                "moves (%s)%s" % (len(records) - len(unread), len(records),
                                                  ", ".join(MOVES), tail))
    return _result(answer, basis, findings, owned, renamed, cannot, not_read)


def _tail(owned, cannot, not_read):
    parts = []
    if owned:
        parts.append("%d change(s) to tests the task declared" % len(owned))
    if cannot:
        parts.append("%d file(s) could not be read: %s"
                     % (len(cannot), ", ".join(c["path"] for c in cannot)))
    whole = [n["path"] for n in not_read if n["move"] is None]
    if whole:
        parts.append("%d file(s) not read, having no syntax known here: %s"
                     % (len(whole), ", ".join(whole)))
    part = [n["path"] for n in not_read if n["move"] is not None]
    if part:
        parts.append("%d test file(s) not compared for %s, defining no %s* function: %s"
                     % (len(part), DEFINITION_CHANGED, TEST_PREFIX, ", ".join(part)))
    return "" if not parts else "; " + "; ".join(parts)
