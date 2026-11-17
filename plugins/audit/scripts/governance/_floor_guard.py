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
  * a test file deleted - unless its text reappears under another test path of
    the diff (see A FILE MOVED);
  * an existing test definition changed. For Python each test the runner would
    run - a function, or a method under its `Class.method` name, whose name
    starts with `TEST_PREFIX` - is compared between the base and tree copies by
    `ast.dump` - line numbers excluded, decorators included, a leading
    docstring dropped, every skip's reason text blanked - together with what
    decides whether it runs: its class's head and decorators, a module or
    class `pytestmark`, and the `if`/`with`/`try` heads it sits under. So a test
    appended beside it is no change, and a skip put on its class is one. A test
    that disappears is reported unless a new test with the same body appeared,
    in its own file (a rename) or in another file of the diff (a move). A
    Python test file that defines no test but calls checks by label - one
    callable whose first argument is a constant string, the house's row suites
    - is compared by label the same way: a label gone, or its arguments
    changed, is a finding. For any other language the assertion lines removed
    from a test file are reported, read through `ASSERTIONS`;
  * a skip added to a test file (`SKIPS`);
  * a suppression whose CODE is new to the file, read in comments only
    (`SUPPRESSIONS`) and only in the place its own checker reads it
    (`_MARKER_AT`): `noqa` and `type: ignore` after a hash, `eslint-disable`
    and the TypeScript pragmas as the comment's first word, `istanbul ignore`
    only before the words istanbul obeys, and the scanners that read a marker
    anywhere on a code line only there. A comment that mentions the word is
    not a suppression. A code is the marker's kind with one rule code out of
    the comment (`noqa E402`, `type: ignore attr-defined`), and a blanket
    marker is its own code; a code some comment of the base copy already
    carries is the file's existing contract and gives no finding, so in a file
    new to the diff every code is new. A caller's `accepted` codes are never
    reported;
  * a stub added in non-test code: `raise NotImplementedError`,
    `throw new Error('Not implemented')`, an except or catch with an empty body.
What a test file is comes from `_filed_returns.is_test_path`, the scripts-side
definition the red-first helper and the task writer already read.

FOUR ANSWERS, AND ONLY ONE IS CLEAN - the shape `_runner_collects` set.
`FINDINGS` when a move was found; `COULD_NOT_TELL` with its reason when no move
was found and something could not be read (a diff that does not parse, a file
a reader could not produce, a Python copy that does not compile, a tree that no
longer holds the lines the diff says it added); `PARTLY_READ` when nothing was
found but a file that could hold a move was not compared; `CLEAN` only when
everything that could hold a move was compared. A could-not-tell beside a
finding does not hide the finding and is not dropped: `couldNotTell` lists it
whatever the answer is.

A FILE IS COMPARED ONLY WHOLE. Every file the reading did not compare is listed
under `notRead` with its `move` and its reason, and with one of two kinds:
`COULD_HOLD` - a binary file, a Python test file whose code outside the compared
definitions or checks was removed or changed (a helper, a table a case reads, a
fixture), a test file of another language with no assertion line this reading
knows - and `CANNOT_HOLD`, a file with no syntax known here or a data file
(`DATA_EXTENSIONS`), which is listed and recorded but does not make the reading
partly read. In a Python test file, code outside the compared definitions or
checks that was only ADDED counts as compared (`_outside_changed`). The
residual that leaves: an added statement that rebinds a name a later check or
test reads changes what it asserts, and is read as an addition. The one added
statement read as a change is a `return`, `raise`, `break` or `continue` put
into a function the base held, which makes the file could-hold.

A DECLARATION COVERS WHAT IS NEW. `declared` holds the task's own test paths. A
bare path covers definitions new to that file and nothing else; only
`path::case` makes a change to a test the base held the task's own, returned
under `declared` and never as a finding. A non-Python test line is never
declared, since its lines map to no case name. A reading clean apart from
declared changes says so in its basis.

A MOVE IS ONLY A MOVE WHEN IT IS NEW. Marks are read over the whole of both
copies of a changed file - so a catch body emptied by a pure removal, whose
`catch` line the diff never touches, is still seen - and each tree skip or stub
is paired away against a base mark with the same text first, then against a
base mark of the same kind only when the two sit on the two sides of one changed
line or inside the same enclosing definition. A suppression is not paired: it
is new when one of its codes is in no comment of the base copy. Every unchanged
mark cancels against itself; a `# noqa` that moved, or whose line's code
changed, is no finding; an assertion line is paired by its exact text only, so
one rewritten in place still reads as removed. The diff's own lines are what
each copy is checked against, so a reader handing back a different tree is
could-not-tell rather than a reading of the wrong file.

A FILE MOVED. A rename git reports is read old against new. A deleted file and
an added file of the same family whose texts git's own default would call a
rename (`RENAME_SIMILARITY`) are paired the same way, so a file moved with its
new path untracked carries its old marks with it.

WHAT THIS READING CANNOT SEE. The non-Python scanner knows quotes and comments,
not regex literals or heredocs, so a quote inside a JavaScript regex mis-masks
the rest of that line. Suppressions are read per file: one carried with code
moved to another file reads as added there. A code the base already carries is
no finding however many more lines it is added to, and the kind is read without
its scope, so an `eslint-disable-next-line <rule>` the base holds hides the same
rule disabled for the whole file. The marker shapes are written from each
checker's documented behaviour, not measured against the checkers. A non-Python
test file is read by assertion line, so a weakened test whose assertions stay
is not seen. A binary file is never read.

This module carries no `--selftest` of its own; its cases live in
`tests/test__floor_guard.py`.
"""

import ast
import bisect
import collections
import copy
import difflib
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
PARTLY_READ = "partly-read"

# The two kinds of file not read, borrowed rather than restated: the block's
# readers in `_filed_returns` hold the same words.
CANNOT_HOLD = _filed_returns.FLOOR_CANNOT_HOLD
COULD_HOLD = _filed_returns.FLOOR_COULD_HOLD

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

# Extensions inside a comment family that hold configuration or styling, never a
# test: a file of these is read for suppressions, and its having no assertion
# line is no gap in the reading.
DATA_EXTENSIONS = (".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf", ".css", ".scss",
                   ".less")

# Where each kind's checker reads its marker - read that way, and only that way,
# over a comment, so a comment that only mentions the word is not a marker. Each
# kind has a shape for a line holding code and one for a line holding nothing but
# the comment (None: the same shape). Every shape is searched in the line's
# comment text, the code blanked to spaces.
#   noqa - ruff 0.16.2, as it obeyed two-line probe files: a hash, optional
#     blanks, the word in any letter case, then the end, a blank or a colon; a
#     later hash inside one comment opens another and is obeyed too. The
#     file-level form names its linter in lower case and is obeyed on a line of
#     its own only.
#   type: ignore - mypy and pyright: at a comment's opening, or after a later hash.
#   pragma: no cover - coverage.py's default exclusion: a hash, then the words.
#   eslint-disable, @ts-ignore, @ts-expect-error, istanbul ignore, Stryker
#     disable - a directive is the comment's first word after `//` or `/*`;
#     istanbul's only before `if`, `else`, `next` or `file`.
#   nosemgrep - semgrep reads it after a blank anywhere on the finding's own line,
#     and on the line above only when nothing but comment punctuation precedes it.
#   gitleaks:allow - gitleaks reads it anywhere on the secret's own line, so on a
#     line holding only the comment it can allow nothing but that comment.
# A caller's accepted entry is not a comment: it is read through `SUPPRESSIONS`,
# in its written case.
_C_OPENER = r"(?://+|/\*+)[ \t*]*"
_NEVER = re.compile(r"(?!)")
_MARKER_AT = {
    "noqa": (re.compile(r"#[ \t]*(?i:noqa)(?![^\s:])"), None),
    "type: ignore": (re.compile(r"#[ \t]*type:[ \t]*ignore\b"), None),
    "pragma: no cover": (re.compile(
        r"#\s*(?:pragma|PRAGMA)[:\s]?\s*(?:no|NO)\s*(?:cover|COVER)"), None),
    "eslint-disable": (re.compile(
        _C_OPENER + r"eslint-disable(?=-next-line\b|-line\b|[\s*]|$)"), None),
    "@ts-ignore": (re.compile(_C_OPENER + r"@ts-ignore\b"), None),
    "@ts-expect-error": (re.compile(_C_OPENER + r"@ts-expect-error\b"), None),
    "istanbul ignore": (re.compile(
        _C_OPENER + r"istanbul\s+ignore(?=[ \t]+(?:if|else|next|file)\b)"), None),
    "Stryker disable": (re.compile(_C_OPENER + r"Stryker[ \t]+disable(?=[ \t])"), None),
    "nosemgrep": (re.compile(r"(?i)[ \t]nosem(?:grep)?(?![\w-])"),
                  re.compile(r"(?i)^[^A-Za-z0-9]*[ \t]nosem(?:grep)?(?![\w-])")),
    "gitleaks:allow": (re.compile(r"gitleaks:allow"), _NEVER),
}
_OWN_LINE = {
    "noqa": re.compile(r"[ \t]*#[ \t]*(?:ruff|flake8)[ \t]*:[ \t]*(?i:noqa)(?![^\s:])"),
}

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
    """One file of a diff. `removedAt` and `addedAt` map a changed line to its
    (change, place): a change is one run of removed and added lines between two
    context lines, and the n-th line removed and the n-th added in one change are
    the two sides of one changed line."""
    return {"old": None, "new": None, "status": "modified", "binary": False,
            "hunks": 0, "added": [], "removed": [], "headerPath": None,
            "changes": 0, "removedAt": {}, "addedAt": {}}


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
    places = None
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
        if tag in "-+" and places is None:
            rec["changes"] += 1
            places = {"-": 0, "+": 0}
        if tag == " ":
            if left_old <= 0 or left_new <= 0:
                raise _Unparsed("a hunk of %s holds more lines than its header "
                                "counts" % (rec["new"] or rec["old"]))
            old_ln, new_ln, left_old, left_new = old_ln + 1, new_ln + 1, left_old - 1, left_new - 1
            places = None
        elif tag == "-" and left_old > 0:
            rec["removed"].append((old_ln, body))
            rec["removedAt"][old_ln] = (rec["changes"], places["-"])
            places["-"] += 1
            old_ln, left_old = old_ln + 1, left_old - 1
        elif tag == "+" and left_new > 0:
            rec["added"].append((new_ln, body))
            rec["addedAt"][new_ln] = (rec["changes"], places["+"])
            places["+"] += 1
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


def _in_comment(name, text, alone):
    """The match of kind `name` in one line's comment text, where its checker
    reads it (`_MARKER_AT`) - and, on a line holding nothing but the comment,
    in that kind's `_OWN_LINE` form too."""
    at_code, at_alone = _MARKER_AT[name]
    own = _OWN_LINE[name].match(text) if alone and name in _OWN_LINE else None
    return own or ((at_alone or at_code) if alone else at_code).search(text)


def _suppression_keys(text, anchored=False, alone=False):
    """[(kind, end, ((kind, code), ...))] for each suppression kind `text`
    carries, read through `SUPPRESSIONS`; a blanket one's single key has code
    None. `anchored` reads only a marker at the start of `text` - the form a
    caller's accepted entry is written in; otherwise `text` is a line's comment
    and `alone` says the line holds nothing else."""
    found = []
    for name, _pat, _codes in SUPPRESSIONS:
        m = _COMPILED[name].match(text) if anchored else _in_comment(name, text, alone)
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
        alone = bool(comment.strip()) and raw_lines[idx].strip() == comment.strip()
        for name, _end, keys in _suppression_keys(comment, alone=alone):
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


def _pair(base_marks, tree_marks, near=None):
    """(base marks left unpaired, tree marks left unpaired): paired by exact
    text first, then - when `near` is given - by kind, but only a base mark and
    a tree mark `near(base, tree)` calls one place. Kind alone would cancel a
    skip added to an enclosing block against an unrelated one taken off a
    single test, and the wider skip would read as no change."""
    base_left, tree_left = list(base_marks), []
    for mark in tree_marks:
        twin = next((b for b in base_left if (b[0], b[1], b[4]) == (mark[0], mark[1], mark[4])),
                    None)
        if twin is None:
            tree_left.append(mark)
        else:
            base_left.remove(twin)
    if near is None:
        return base_left, tree_left
    tree_rest = []
    for mark in tree_left:
        twin = next((b for b in base_left if (b[0], b[1]) == (mark[0], mark[1])
                     and near(b, mark)), None)
        if twin is None:
            tree_rest.append(mark)
        else:
            base_left.remove(twin)
    return base_left, tree_rest


def _nearness(rec, base_ast, tree_ast):
    """`near(base mark, tree mark)` for `_pair`: the two lines are the two
    sides of one changed line of the diff, or - in Python - sit inside the same
    enclosing function or class."""
    base_spans, tree_spans = _scopes(base_ast), _scopes(tree_ast)

    def near(b, t):
        side = rec["removedAt"].get(b[2])
        if side is not None and side == rec["addedAt"].get(t[2]):
            return True
        scope = _scope_of(base_spans, b[2])
        return scope is not None and scope == _scope_of(tree_spans, t[2])
    return near


_STATEMENT_LISTS = ("body", "orelse", "finalbody", "handlers", "cases")


def _scopes(tree):
    """[(first line, last line, qualified name)] for every function and class of
    a Python AST, decorators counted in; [] for no AST. Statements only are
    walked, never expressions, so the depth is the code's block nesting."""
    out, todo = [], ([(tree, "")] if tree is not None else [])
    while todo:
        node, prefix = todo.pop()
        for field in _STATEMENT_LISTS:
            for child in getattr(node, field, None) or ():
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = prefix + child.name
                    first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                    out.append((first, child.end_lineno or child.lineno, name))
                    todo.append((child, name + "."))
                elif isinstance(child, ast.AST):
                    todo.append((child, prefix))
    return out


def _scope_of(spans, line):
    """The innermost scope of `spans` holding `line`, or None at module level."""
    inside = [s for s in spans if s[0] <= line <= s[1]]
    return max(inside, key=lambda s: s[0])[2] if inside else None


# --- Python definitions -----------------------------------------------------------
# A test is compared together with everything that decides whether and how it
# runs: the decorators of each class around it, every `pytestmark` of its module
# and classes, and the head of each `if`, `with` or `try` block it is defined in.
# A skip widened on any of those is a change to every test under it. A skip's
# reason text is no part of the comparison, so a reason reworded is no change.

_TRY = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)
_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_FLOW = (ast.Return, ast.Raise, ast.Break, ast.Continue)

# A skip call's reason: its string arguments from this position on, and these
# keywords. `skipif`'s first argument is a condition, so it is kept.
_REASON_FROM = {"skip": 0, "skipTest": 0, "xfail": 0, "skipIf": 1, "skipUnless": 1,
                "skipif": 1}
_REASON_KEYWORDS = ("reason", "msg")


def _callee(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _is_text(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_docstring(node):
    return isinstance(node, ast.Expr) and _is_text(node.value)


def _parse_test(text):
    """A Python test file's AST with every skip call's reason text blanked, so
    no comparison of it sees a reason. The blanking is done in place on the
    tree this function has just parsed, never on one a caller holds: a copy of
    each definition would cost a deep recursion per node, which a long
    expression in a test turns into a crash."""
    tree = ast.parse(text)
    for sub in ast.walk(tree):
        first = _REASON_FROM.get(_callee(sub.func)) if isinstance(sub, ast.Call) else None
        if first is None:
            continue
        sub.args = [ast.Constant(value="") if k >= first and _is_text(a) else a
                    for k, a in enumerate(sub.args)]
        for kw in sub.keywords:
            if kw.arg in _REASON_KEYWORDS and _is_text(kw.value):
                kw.value = ast.Constant(value="")
    return tree


def _is_pytestmark(node):
    return isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)


def _marks_of(body):
    return tuple(("pytestmark", ast.dump(n.value)) for n in body if _is_pytestmark(n))


def _class_head(node, decorators=True):
    return ("class", node.name, tuple(ast.dump(b) for b in node.bases),
            tuple(ast.dump(k) for k in node.keywords),
            tuple(ast.dump(d) for d in node.decorator_list) if decorators else ())


def _blocks(node, loops=False):
    """[(head, statements)] for each block of a compound statement a definition
    can sit in - `if`, `with`, `try` with its handlers - and, with `loops`, the
    blocks of a loop; [] for any other statement."""
    if isinstance(node, ast.If):
        test = ast.dump(node.test)
        return [(("if", test), node.body), (("else", test), node.orelse)]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [(("with",) + tuple(ast.dump(i) for i in node.items), node.body)]
    if _TRY and isinstance(node, _TRY):
        return ([(("try",), node.body)]
                + [(("except", ast.dump(h.type) if h.type else ""), h.body)
                   for h in node.handlers]
                + [(("try-else",), node.orelse), (("finally",), node.finalbody)])
    if loops and isinstance(node, _LOOPS):
        head = (ast.dump(node.test),) if isinstance(node, ast.While) else (
            ast.dump(node.target), ast.dump(node.iter))
        return [(("loop",) + head, node.body), (("loop-else",) + head, node.orelse)]
    return []


def _definitions(tree):
    """{qualified name: (node, context)} for the module's functions and every
    class's methods (`Class.method`, `Outer.Inner.method`), those defined inside
    an `if`, `with` or `try` block included; `context` is what decides how the
    definition runs, as the section comment says. A name defined twice keeps the
    LAST, which is the one Python runs - so a weaker test appended under an
    existing name is a change to that name."""
    out = {}

    def walk(body, prefix, context):
        context = context + _marks_of(body)
        for node in body:
            if isinstance(node, _FUNCTIONS):
                out[prefix + node.name] = (node, context)
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".", context + (_class_head(node),))
            else:
                for head, block in _blocks(node):
                    walk(block, prefix, context + (head,))
    walk(tree.body, "", ())
    return out


def _dump(entry, anonymous=False):
    """One definition as the comparison reads it: `ast.dump` without line
    numbers, leading docstring or skip reasons, followed by its context;
    `anonymous` also drops its name, to recognise a rename."""
    node, context = entry
    clone = copy.copy(node)
    if clone.body and _is_docstring(clone.body[0]):
        clone.body = clone.body[1:]
    if anonymous:
        clone.name = ""
    return "%s %r" % (ast.dump(clone), context)


def _is_test_name(qual):
    return qual.rsplit(".", 1)[-1].startswith(TEST_PREFIX)


def _tests_only(defs):
    """The definitions a runner would run: the last name segment starts with
    `TEST_PREFIX`. Helpers, fixtures and case-table functions fall away."""
    return dict((q, e) for q, e in defs.items() if _is_test_name(q))


def _compare_definitions(base_tree, tree_tree, new):
    """(changed, renamed, fresh). `changed` holds (name, what, line, side, sign)
    - `sign` set on a definition that is gone, so one that reappears unchanged
    in another file of the diff is a move; `renamed` holds {path, from, to,
    line}; `fresh` holds (sign, name, line) for each test new to the tree copy."""
    base_defs = _tests_only(_definitions(base_tree))
    tree_defs = _tests_only(_definitions(tree_tree))
    fresh = dict((q, e) for q, e in tree_defs.items() if q not in base_defs)
    changed, renamed = [], []
    for qual, entry in sorted(base_defs.items(), key=lambda kv: kv[1][0].lineno):
        if qual in tree_defs:
            if _dump(entry) != _dump(tree_defs[qual]):
                changed.append((qual, "definition `%s` differs from its base copy" % qual,
                                tree_defs[qual][0].lineno, "tree", None))
            continue
        shape = _dump(entry, anonymous=True)
        twin = next((q for q in sorted(fresh) if _dump(fresh[q], anonymous=True) == shape),
                    None)
        if twin is None:
            changed.append((qual, "definition `%s` is gone from the tree copy" % qual,
                            entry[0].lineno, "base", ("def", shape)))
        else:
            renamed.append({"path": new, "from": qual, "to": twin,
                            "line": fresh.pop(twin)[0].lineno})
    return changed, renamed, [(("def", _dump(e, anonymous=True)), q, e[0].lineno)
                              for q, e in sorted(fresh.items())]


def _fresh_definitions(tree):
    """`fresh`, as `_compare_definitions` gives it, for a test file new to the
    diff: every test it defines."""
    return [(("def", _dump(e, anonymous=True)), q, e[0].lineno)
            for q, e in sorted(_tests_only(_definitions(tree)).items())]


# --- labelled checks: a suite written as script rows ------------------------------
# A Python test file that defines no test is read as a script of checks: the
# calls of ONE callable whose first argument is a constant string (or a `%` or
# f-string format whose text is constant) are its cases, each named by that
# label. The callable is the one most such call statements go to across both
# copies. Checks are compared by label: a label that is gone is a removed case,
# one whose other arguments changed is a changed case; the values a label prints
# are not compared. A check whose label changed and whose arguments did not is a
# rename.

def _label_of(call):
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.BinOp) and isinstance(first.op, ast.Mod):
        first = first.left
    if _is_text(first):
        return first.value
    if isinstance(first, ast.JoinedStr):
        return "".join(v.value if _is_text(v) else "{}" for v in first.values)
    return None


def _labelled(node):
    """The call `node` is, when it is a statement calling something with a label."""
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _label_of(node.value) is not None:
            return node.value
    return None


def _check_callables(trees):
    """The `ast.dump` of the callable the labelled call statements of `trees`
    go to most - every one tied for most - as a frozenset; empty for none."""
    counts = collections.Counter(ast.dump(call.func) for tree in trees
                                 for call in map(_labelled, ast.walk(tree)) if call)
    top = max(counts.values()) if counts else 0
    return frozenset(k for k, v in counts.items() if v == top)


def _check_of(node, callables):
    call = _labelled(node)
    return call if call is not None and ast.dump(call.func) in callables else None


def _checks(tree, callables):
    """[(label, signature, line)] for each labelled check of `tree`, in line order."""
    out = []
    for node in ast.walk(tree):
        call = _check_of(node, callables)
        if call is not None:
            sign = "|".join([ast.dump(a) for a in call.args[1:]]
                            + [ast.dump(k) for k in call.keywords])
            out.append((_label_of(call), sign, node.lineno))
    return sorted(out, key=lambda c: c[2])


def _case_id(label):
    words = label.split()
    return words[0].rstrip(":") if words else label


def _compare_checks(base_tree, tree_tree, callables, new):
    """(changed, renamed, fresh), in `_compare_definitions`' shapes, over the
    labelled checks of the two copies."""
    base_left, tree_left = _checks(base_tree, callables), []
    for check in _checks(tree_tree, callables):
        twin = next((b for b in base_left if b[:2] == check[:2]), None)
        if twin is None:
            tree_left.append(check)
        else:
            base_left.remove(twin)
    changed, renamed, gone = [], [], []
    for b in base_left:
        same = next((t for t in tree_left if t[0] == b[0]), None)
        if same is None:
            gone.append(b)
            continue
        tree_left.remove(same)
        changed.append((_case_id(b[0]), "labelled check `%s` differs from its base copy"
                        % (_short(b[0]),), same[2], "tree", None))
    for b in gone:
        twin = next((t for t in tree_left if t[1] == b[1]), None)
        if twin is not None:
            tree_left.remove(twin)
            renamed.append({"path": new, "from": b[0], "to": twin[0], "line": twin[2]})
            continue
        changed.append((_case_id(b[0]), "labelled check `%s` is gone from the tree copy"
                        % (_short(b[0]),), b[2], "base", ("check", b[0], b[1])))
    return (sorted(changed, key=lambda c: (c[3], c[2])), renamed,
            [(("check", t[0], t[1]), t[0], t[2]) for t in tree_left])


def _short(text, width=70):
    return text if len(text) <= width else text[:width - 3] + "..."


# --- the code outside the tests ----------------------------------------------------
# What a Python test file holds besides its tests - helpers, module tables a
# parametrize reads, fixtures, the lines a labelled check reads - is read as
# statements, each keyed by the heads of the blocks around it. The file counts as
# compared when every statement of the base copy is still there: lines only added
# cannot remove or weaken an existing case by themselves, and the moves an added
# line can be (a skip, a suppression) are read line by line elsewhere. The one
# added line that is read as a change is a `return`, `raise`, `break` or
# `continue` put into a function the base already had, since it can end a case
# before the case checks anything.

def _units(tree, callables):
    """([(key, line, statement)], every block head seen) for the code of `tree`
    outside its tests, its `pytestmark`s and its labelled checks."""
    found, heads = [], {()}

    def walk(body, context, in_function):
        heads.add(context)
        for k, node in enumerate(body):
            if (k == 0 and _is_docstring(node)) or _is_pytestmark(node):
                continue
            if callables and _check_of(node, callables) is not None:
                continue
            if isinstance(node, _FUNCTIONS):
                if not in_function and node.name.startswith(TEST_PREFIX):
                    continue
                walk(node.body, context + (
                    ("def", node.name, ast.dump(node.args),
                     tuple(ast.dump(d) for d in node.decorator_list),
                     ast.dump(node.returns) if node.returns else ""),), True)
            elif isinstance(node, ast.ClassDef):
                holds = any(isinstance(n, _FUNCTIONS) and n.name.startswith(TEST_PREFIX)
                            for n in node.body)
                walk(node.body, context + (_class_head(node, not holds),), in_function)
            elif _blocks(node, loops=True):
                for head, block in _blocks(node, loops=True):
                    walk(block, context + (head,), in_function)
            else:
                found.append(((context, ast.dump(node)), node.lineno, node))
    walk(tree.body, (), False)
    return found, heads


def _function_part(context):
    """`context` up to its innermost function head; () outside every function."""
    last = max([k for k, head in enumerate(context) if head[0] == "def"] or [-1])
    return context[:last + 1]


def _outside_changed(base_tree, tree_tree, callables):
    """None when the code outside the tests was only added to, else (side, line)
    of the first statement that says otherwise: a base statement gone or
    changed, or a flow statement added inside a function the base had."""
    base_units, base_heads = _units(base_tree, callables)
    tree_units, _heads = _units(tree_tree, callables)
    left = collections.Counter(u[0] for u in tree_units)
    for key, line, _node in base_units:
        if left[key] > 0:
            left[key] -= 1
        else:
            return "base", line
    for key, line, node in tree_units:
        if left[key] > 0 and isinstance(node, _FLOW) and _function_part(key[0]) in base_heads:
            return "tree", line
    return None


# --- declared -------------------------------------------------------------------

# A DECLARATION COVERS WHAT IS NEW. A bare `path` entry - what the drive files
# when the task's return binds no case to a `tests.add` file, and always on the
# writer route - covers the definitions new to the tree copy, which are no move
# in the first place, and nothing the base already held: an existing test
# changed in the file a task adds to is still a finding. Only a `path::case`
# entry declares a change to a test that exists at the base, matched against a
# definition's name or a labelled check's case id. A line of a non-Python test
# maps to no case name, so a change to one the base held is never declared.

def _declared_index(declared):
    """{path: set of case names} from the `path::case` entries of `declared`;
    a pytest-style `Class::method` case is read as `Class.method`. A bare path
    adds nothing, as the comment above says."""
    cases = {}
    for entry in declared or ():
        path, sep, case = str(entry).replace("\\", "/").partition("::")
        if sep and case:
            cases.setdefault(path, set()).add(case.replace("::", "."))
    return cases


def _is_declared(index, paths, qual=None):
    if qual is None:
        return False
    for path in [p for p in paths if p]:
        names = index.get(path, set())
        if qual in names or qual.rsplit(".", 1)[-1] in names:
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


def _parse_python(text, side, path, test):
    """(AST or None, problem). A test file's tree comes with its skip reasons
    blanked (`_parse_test`); no other reading of a test file needs a reason."""
    if text is None:
        return None, None
    try:
        return (_parse_test(text) if test else ast.parse(text)), None
    except (SyntaxError, ValueError) as exc:
        return None, "the %s copy of %s does not compile (%s)" % (side, path, exc)


# Extensions of prose, data and media: a file of these holds no move as this
# reading reads one, wherever it sits.
INERT_EXTENSIONS = (".md", ".markdown", ".rst", ".txt", ".adoc", ".json", ".jsonl",
                    ".jsonc", ".csv", ".tsv", ".xml", ".html", ".htm", ".svg", ".png",
                    ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".lock", ".snap",
                    ".log", ".tape")


def _could_hold(path):
    """Whether a file this reading did not read could still hold a move: one in
    a comment family other than configuration and styling, or one whose own
    name is a test's in a language read nowhere here. Prose, data, media, a
    fixture with no test name and a source file in an unknown language outside
    the tests cannot hold one as this reading reads them."""
    low = str(path or "").lower()
    if low.endswith(INERT_EXTENSIONS):
        return False
    if family(path) is not None:
        return not low.endswith(DATA_EXTENSIONS)
    return is_test_path(low.rsplit("/", 1)[-1])


def _unread(path, move, reason, could=None):
    """One `notRead` entry; its kind is `_could_hold(path)` unless `could` says."""
    could = _could_hold(path) if could is None else could
    return {"path": path, "move": move, "reason": reason,
            "kind": COULD_HOLD if could else CANNOT_HOLD}


def _one_file(rec, read_base, read_tree, index, accepted):
    """{findings, declared, renamed, gone, fresh, problem, notRead} for one file
    of the diff. `notRead` is one entry or None; its `move` is None when no move
    was read, and names the move left uncompared otherwise. `gone` pairs each
    finding for a test that disappeared with its signature, and `fresh` lists
    the signatures of tests new to this file, so a test moved between two files
    of the diff is read as moved."""
    out = {"findings": [], "declared": [], "renamed": [], "gone": [], "fresh": [],
           "problem": None, "notRead": None}
    path = rec["new"] or rec["old"]
    if rec["status"] == "deleted":
        if is_test_path(rec["old"]):
            out["findings"].append(_finding(TEST_DELETED, rec["old"], 1, "base",
                                            "test file deleted"))
        return out
    if rec["binary"]:
        out["notRead"] = _unread(path, None, "binary: git printed no line of it, so "
                                             "nothing in it was read")
        return out
    if not rec["hunks"]:
        return out
    fam = family(path)
    if fam is None:
        out["notRead"] = _unread(path, None, "no comment or string syntax this reading "
                                             "knows for its name")
        return out
    test = is_test_path(path)
    base, tree, problem = _copies(rec, read_base, read_tree)
    base_ast = tree_ast = None
    if problem is None and fam == PY:
        base_ast, problem = _parse_python(base, "base", rec["old"], test)
    if problem is None and fam == PY:
        tree_ast, problem = _parse_python(tree, "tree", rec["new"], test)
    if problem is None:
        try:
            out.update(_collect(rec, (base, base_ast), (tree, tree_ast), fam, test,
                                (index, accepted)))
        except (tokenize.TokenError, SyntaxError) as exc:
            problem = "%s does not tokenize (%s)" % (path, exc)
    out["problem"] = problem
    return out


def _collect(rec, base, tree, fam, test, ask):
    """{findings, declared, renamed, gone, fresh, notRead} for one file whose
    copies were read; `base` and `tree` are each (text, Python AST or None) and
    `ask` is (declared index, accepted suppression keys)."""
    index, accepted = ask
    path = rec["new"]
    base_marks = _side_marks(base[0], base[1], fam, test) if base[0] is not None else []
    tree_marks = _side_marks(tree[0], tree[1], fam, test)
    out = {"findings": [], "declared": [], "renamed": [], "gone": [], "fresh": [],
           "notRead": None}
    gone, _unused = _pair([m for m in base_marks if m[0] == "assertion"],
                          [m for m in tree_marks if m[0] == "assertion"])
    out["findings"].extend(_finding(DEFINITION_CHANGED, rec["old"], mark[2], "base",
                                    "assertion line removed (%s): %s" % (mark[1], mark[4]))
                           for mark in gone)
    _old, added = _pair([m for m in base_marks if m[0] in (SKIP_ADDED, STUB_ADDED)],
                        [m for m in tree_marks if m[0] in (SKIP_ADDED, STUB_ADDED)],
                        near=_nearness(rec, base[1], tree[1]))
    out["findings"].extend(_finding(mark[0], path, mark[2], "tree", "%s (%s): %s"
                                    % (_ADDED_WORD[mark[0]], mark[1], mark[4]))
                           for mark in added)
    fresh = _new_suppressions([m for m in base_marks if m[0] == SUPPRESSION_ADDED],
                              [m for m in tree_marks if m[0] == SUPPRESSION_ADDED], accepted)
    out["findings"].extend(_finding(SUPPRESSION_ADDED, path, mark[2], "tree",
                                    "suppression added (%s, new to the file): %s"
                                    % (_key_text(new), mark[4])) for mark, new in fresh)
    if fam == PY and test:
        _python_test(out, rec, base[1], tree[1], index)
    elif test and base[0] is not None and not path.lower().endswith(DATA_EXTENSIONS) \
            and not any(m[0] == "assertion" for m in base_marks + tree_marks):
        out["notRead"] = _unread(path, DEFINITION_CHANGED, (
            "no assertion pattern this reading knows matched a line of either copy, "
            "so whether an existing case was weakened was not compared"), True)
    return out


def _python_test(out, rec, base_ast, tree_ast, index):
    """Fill `out` with what comparing a Python test file's two copies found:
    its test definitions, or - a file that defines none - its labelled checks,
    then whether its code outside them was only added to."""
    path, paths = rec["new"], (rec["new"], rec["old"])
    if base_ast is None:
        callables = _check_callables([tree_ast])
        out["fresh"] = (_fresh_definitions(tree_ast) if _tests_only(_definitions(tree_ast))
                        else [(("check", c[0], c[1]), c[0], c[2])
                              for c in _checks(tree_ast, callables)])
        return
    has_tests = bool(_tests_only(_definitions(base_ast)) or _tests_only(_definitions(tree_ast)))
    callables = None if has_tests else _check_callables([base_ast, tree_ast])
    changed, out["renamed"], out["fresh"] = (
        _compare_definitions(base_ast, tree_ast, path) if has_tests
        else _compare_checks(base_ast, tree_ast, callables, path))
    for qual, what, line, side, sign in changed:
        found = _finding(DEFINITION_CHANGED, path if side == "tree" else rec["old"],
                         line, side, what)
        if _is_declared(index, paths, qual):
            out["declared"].append(found)
            continue
        out["findings"].append(found)
        if sign is not None:
            out["gone"].append((found, sign))
    where = _outside_changed(base_ast, tree_ast, callables)
    if where is not None:
        held = ("its test definitions" if has_tests else "its labelled checks"
                if callables else "any test - it defines none and calls no labelled check")
        out["notRead"] = _unread(path, DEFINITION_CHANGED, (
            "code outside %s changed (line %d of the %s copy), and that code - a "
            "helper, a table a case reads, a fixture - is not compared"
            % (held, where[1], where[0])), True)


_ADDED_WORD = {SKIP_ADDED: "skip added", SUPPRESSION_ADDED: "suppression added",
               STUB_ADDED: "stub added"}


# --- a file moved ---------------------------------------------------------------
# A file moved in the working tree reaches this module as a deletion and an
# addition whenever git could not pair them - the new path untracked, or the
# diff taken without rename detection. Read that way, a moved test file is a
# deletion and every mark it carried is new. So a deleted file and an added one
# of the same family whose texts git's own default would call a rename (half
# their lines or more in common) are read as one renamed file, base-old against
# tree-new; with the text unchanged there is nothing left to read.

RENAME_SIMILARITY = 0.5


def _text_lines(text):
    return [l.rstrip("\r") for l in text.split("\n")]


def _renamed_record(old, new, base, tree):
    """A record for `old` renamed to `new`, its changed lines and their places
    derived from the two texts as the diff parser would have read them."""
    rec = _new_record()
    rec.update(old=old, new=new, status="renamed")
    base_lines, tree_lines = _text_lines(base), _text_lines(tree)
    matcher = difflib.SequenceMatcher(None, base_lines, tree_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        rec["changes"] += 1
        rec["hunks"] += 1
        for k in range(i1, i2):
            rec["removed"].append((k + 1, base_lines[k]))
            rec["removedAt"][k + 1] = (rec["changes"], k - i1)
        for k in range(j1, j2):
            rec["added"].append((k + 1, tree_lines[k]))
            rec["addedAt"][k + 1] = (rec["changes"], k - j1)
    return rec


def _similarity(base, tree):
    matcher = difflib.SequenceMatcher(None, _text_lines(base), _text_lines(tree),
                                      autojunk=False)
    if matcher.real_quick_ratio() < RENAME_SIMILARITY:
        return 0.0
    if matcher.quick_ratio() < RENAME_SIMILARITY:
        return 0.0
    return matcher.ratio()


def _paired_moves(records, read_base, read_tree):
    """`records` with each deleted file and the added file it was moved to read
    as one rename, as the section comment says. A copy that cannot be read is
    left as git gave it, and is read - or fails to be - in its own record."""
    def texts(status, side, reader):
        out = {}
        for k, rec in enumerate(records):
            if rec["status"] != status or rec["binary"]:
                continue
            text, problem = _read(reader, rec["old"] if side == "base" else rec["new"], side)
            if problem is None and text is not None:
                out[k] = text
        return out
    gone = texts("deleted", "base", read_base)
    came = texts("added", "tree", read_tree) if gone else {}
    scored = sorted(((_similarity(gone[g], came[a]), g, a) for g in gone for a in came
                     if family(records[g]["old"]) == family(records[a]["new"])),
                    key=lambda s: (-s[0], s[1], s[2]))
    used, pairs = set(), {}
    for score, g, a in scored:
        if score >= RENAME_SIMILARITY and g not in used and a not in used:
            used.update((g, a))
            pairs[g] = _renamed_record(records[g]["old"], records[a]["new"], gone[g],
                                       came[a])
    return [pairs.get(k, rec) for k, rec in enumerate(records)
            if k not in used or k in pairs]


def _moved_tests(findings, renamed, gone, fresh):
    """(findings, renamed) with each test that disappeared from one file and
    reappeared unchanged in another file of the diff read as moved there."""
    waiting = dict()
    for sign, name, line, path in fresh:
        waiting.setdefault(sign, []).append((name, line, path))
    dropped = []
    for found, sign in gone:
        there = [w for w in waiting.get(sign, []) if w[2] != found["path"]]
        if there:
            waiting[sign].remove(there[0])
            dropped.append(found)
            renamed = renamed + [{"path": there[0][2], "from": "%s in %s"
                                  % (found["what"].split("`")[1], found["path"]),
                                  "to": there[0][0], "line": there[0][1]}]
    return [f for f in findings if not any(f is d for d in dropped)], renamed


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
    `path` or `path::case`: a change to a test the base held is the task's to
    make only under `path::case` (see the comment above `_declared_index`).
    `accepted` holds suppression codes never reported, each written as its
    comment would be (`noqa: E402`); `_accepted_keys` says how one matches, and
    an entry it cannot read makes the answer could-not-tell before any file is.

    Returns {"answer": FINDINGS | COULD_NOT_TELL | PARTLY_READ | CLEAN,
             "basis": the sentence that makes the answer true,
             "findings": [{move, path, line, side, what}], sorted,
             "declared": the same shape, for changes the task declared,
             "renamed": [{path, from, to, line}] - tests renamed or moved unchanged,
             "couldNotTell": [{path, reason}] - kept whatever the answer,
             "notRead": [{path, move, reason, kind}] - `move` None for a file read
                        for no move, a move's name for one read for every move
                        but that one; `kind` COULD_HOLD or CANNOT_HOLD}.
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
    records = _paired_moves(records, read_base, read_tree)
    index = _declared_index(declared)
    findings, owned, renamed, cannot, not_read, gone, fresh = [], [], [], [], [], [], []
    for rec in records:
        got = _one_file(rec, read_base, read_tree, index, keys)
        findings.extend(got["findings"])
        owned.extend(got["declared"])
        renamed.extend(got["renamed"])
        gone.extend(got["gone"])
        fresh.extend(f + (rec["new"],) for f in got["fresh"])
        if got["problem"]:
            cannot.append({"path": rec["new"] or rec["old"], "reason": got["problem"]})
        if got["notRead"]:
            not_read.append(got["notRead"])
    findings, renamed = _moved_tests(findings, renamed, gone, fresh)
    tail = _tail(owned, cannot, not_read)
    open_ = [n for n in not_read if n["kind"] == COULD_HOLD]
    if findings:
        answer, basis = FINDINGS, ("%d move(s) that lower the bar across %d file(s) of "
                                   "the diff%s" % (len(findings), len(records), tail))
    elif cannot:
        answer, basis = COULD_NOT_TELL, ("; ".join(c["reason"] for c in cannot)
                                         + _tail(owned, (), not_read))
    else:
        answer = PARTLY_READ if open_ else CLEAN
        basis = ("compared %d of the diff's %d file(s) and found none of the moves "
                 "(%s)%s" % (len(records) - len(not_read), len(records),
                             ", ".join(MOVES), tail))
    return _result(answer, basis, findings, owned, renamed, cannot, not_read)


def _tail(owned, cannot, not_read):
    parts = []
    if owned:
        parts.append("%d change(s) to tests the task declared by case" % len(owned))
    if cannot:
        parts.append("%d file(s) could not be read: %s"
                     % (len(cannot), ", ".join(c["path"] for c in cannot)))
    inert = [n["path"] for n in not_read if n["kind"] == CANNOT_HOLD]
    if inert:
        parts.append("%d file(s) not read that cannot hold a move as read here: %s"
                     % (len(inert), ", ".join(inert)))
    open_ = [n["path"] for n in not_read if n["kind"] == COULD_HOLD]
    if open_:
        parts.append("%d file(s) that could hold a move not compared: %s"
                     % (len(open_), ", ".join(open_)))
    return "" if not parts else "; " + "; ".join(parts)
