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
  * a test file deleted - unless its text reappears under another path that
    is a test by every reading that made the old one a test, in the same
    comment family (see A FILE MOVED);
  * an existing test changed. For Python a UNIT is what the runner runs as one
    case: a function, or a method under its `Class.method` name, whose name
    starts with `TEST_PREFIX`, or - in a file that defines none outside a
    function, the house's row suites - a labelled check, a call of the one callable the base copy's
    labelled calls go to most. A unit is found wherever it stands - inside a
    loop, a conditional, a `with`, a `try`, another function - and compared by
    `ast.dump` (line numbers excluded, decorators included, nothing else left
    out but what WHAT IS SET ASIDE names), a check also by the name it is
    called through and the values its label formats, together with its
    POSITION, read by PAIRING:
    in each part (a body, an else, a handler, a finally) the statements that
    are not units are a sequence of tokens - a simple statement's syntax, a
    compound one's head (an `if`'s test, a `for`'s target and iterable, a
    `with`'s items, a `try`'s handler types and its else and finally, a def's
    or class's name, arguments, bases and decorators) - and a unit is IN PLACE
    when some longest common subsequence of the two copies' sequences pairs
    nothing across it. A unit is in the same position when every statement
    enclosing it from the module down is in place as a paired member, the part
    of each holding it is the same part, every `pytestmark` on the way is the
    same, and it is in place in its own part. A unit whose text is the same and
    whose position differs is a finding saying it moved, from where to where.
    A unit that disappears is reported unless one with the same body and
    position appeared, in its own file (a rename) or in another file of the
    diff (a move - read there by the count of statements before it, since no
    pairing spans two files); a check the tree no longer calls through the
    base's callable is gone. For any other language the assertion lines
    removed from a test file are reported, read through `ASSERTIONS`;
  * a skip added to a test file (`SKIPS`), a raised `SkipTest` and an
    `importorskip` call among them;
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
`COULD_HOLD` - a binary file, a Python test file whose code outside its units
is not the same in both copies, a test file of another language with no
assertion line this reading knows - and `CANNOT_HOLD`, a file with no syntax
known here or a data file (`DATA_EXTENSIONS`), which is listed and recorded but
does not make the reading partly read.

COMPARED MEANS THE REST IS THE SAME AND EVERY UNIT HAS ITS TWIN. A Python test
file of the diff is compared only when both of these hold, each a comparison of
syntax trees and never of lines. S, THE REST IS THE SAME: with every unit taken
out of each copy's tree, what is left is identical - the same statements, in
the same order, each in the same part of the same enclosing statement (`_rest`);
a comment, a blank line or a layout change is no syntax, so it is never a
difference, and of what is syntax only WHAT IS SET ASIDE is left out. U, EVERY
EXISTING UNIT IS STILL THERE AND STILL THE SAME: each unit of the base copy has
one twin in the tree copy with the same own syntax, the same position and, for
a check, the same callee. A unit of the tree copy with no twin is NEW: counted
and named in the basis, and not judged - and a test definition is a new unit
only when it is bare (WHAT IS SET ASIDE). A finding for a unit whose own
syntax changed carries `part`, the fixed words of `PARTS` joined by `+`, and
says them in its text: for a check what it is called through, its condition
and arguments, or its label's values; for a test its head or its body.
"position" is the part of a unit that moved, "gone" of one with no twin.
When U fails for a unit it is a finding; when S
fails the file is listed as not compared, and its reason says which of two
things the rest is, computed by fitting the base copy's rest into the tree
copy's in order and in place (`_fit`): ONLY ADDED, naming the first added
statement and its tree line, or CHANGED OR REMOVED, naming the first base
statement with no place in the tree copy and its base line. A file new to the
diff is read against an empty base copy, so any statement in it outside its
units is only added. A reformat, a reworded label, a new unit and two adjacent
units swapped are therefore clean; a new helper, import or set-up line makes
its file not compared and leaves every unit after it in place, a duplicate of
an existing statement included; a unit moved across a statement, under a new
or another block, or into a later block whose head reads the same is a
finding, moved; and where the rest was changed or removed, each unit is still
judged against the best pairing of what is there.

WHAT IS SET ASIDE. The comparison reads all of both copies but what the table
`SET_ASIDE` names, one row per thing with the function that sets it aside and
why it cannot change what runs:
  * A LABEL'S LITERAL TEXT. A check's own syntax is all of it but the constant
    text of its label; every expression the label formats is compared like
    the condition. A check whose literal text alone changed is a rename; one
    whose label values changed is a changed check, `part` "label".
  * THE BODY OF A BARE NEW TEST, OR A NEW LABELLED CHECK. A new test is a unit
    only when it is bare - no decorator, no default, no evaluated annotation -
    nested in no function, and under a name no identifier of the base copy
    spells (a string is no identifier); only then is it set aside, with what it
    runs. Any other new test is no unit: it stays in the rest, so its file is
    not compared, only added, naming it - unless it is the rename of a base
    test gone from the tree with the same head and body, whose head is then
    compared with that test's.
  * A DOCSTRING HOLDING NO EXAMPLE. A docstring is set aside only when neither
    copy's text of it holds a doctest prompt; one that does is syntax of the
    statement holding it, a unit's (`part` "body") or the rest's.
  * A REASON, WHERE THE SKIP'S OWN SIGNATURE CALLS IT ONE. For each skip and
    expected-failure decorator or call `_REASONS` knows, the literal text of
    the argument its signature documents as the reason, by position or by
    keyword; every other argument is compared, and an expected-failure mark's
    first positional argument is its condition. A skip `_REASONS` does not
    know has nothing set aside.

WHAT THE READING DOES NOT CLAIM. It is a comparison of structure that never
evaluates code, so a new test or a new check can do anything when it runs - the
reading says new, not harmless - and an author set on defeating it can, for
one by code that reads a label's or a docstring's text back as a value. Clean
means every existing test stands where it stood, unchanged, and nothing in a
test file but tests was touched. Code outside the test files of the diff - a
changed helper module, a conftest in another directory - is read by the other
rules of this module or not at all.

A DECLARATION COVERS WHAT IS NEW. `declared` holds the task's own test paths. A
bare path covers definitions new to that file and nothing else; only
`path::case` makes a change to a test the base held the task's own, returned
under `declared` and never as a finding, and only when exactly one unit of the
base copy answers to the case. A declaration several base units answer to - a
first word several labels share, a method name several classes share - covers
none of them, and the finding says it is ambiguous and what would name the
unit alone. A non-Python test line is never declared, since its lines map to
no case name. A reading clean apart from declared changes says so in its
basis.

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
an added file whose texts git's own default would call a rename
(`RENAME_SIMILARITY`) are paired the same way, so a file moved with its new path
untracked carries its old marks with it. Either way a test file counts as moved
only to a path of the same comment family that every reading making the old
path a test - its name, its directory - also makes a test (`_still_a_test`);
moved anywhere else, it is a test deleted, whatever its text.

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
    ("raise SkipTest", r"\braise\s+(?:[A-Za-z_]\w*\.)*SkipTest\b", (PY,)),
    ("importorskip", r"\bimportorskip\s*\(", (PY,)),
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


# --- Python units -----------------------------------------------------------------
# A UNIT is what a runner runs as one case: a test definition, or - in a file
# that defines none a runner collects, none outside a function
# (`_collected_tests`) - a labelled check (below), wherever it stands in the file.
# A unit is compared together with its POSITION, read by pairing (the section
# after `_collected_tests`): each statement enclosing it, from the module down,
# read by its head (`_head`), paired in place, and the part of it that holds the
# unit, the `pytestmark` of each body on the way, and the unit in place among
# the statements of its own part. So a unit whose own text is the same is still a
# change when a statement around it changed or it moved across one - a check
# wrapped in `if False:`, moved into a function nothing calls, put under a loop
# over a table that was cut, inside a `try` whose handler swallows it, or moved
# past a statement; a skip widened on a class is a change to every test under
# it. What the comparison sets aside is `SET_ASIDE` below, and nothing else.

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _callee(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _dotted(func):
    """`pytest.mark.skip` for the callable a call names, or None for one that is
    not a chain of names."""
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    return ".".join([func.id] + parts[::-1]) if isinstance(func, ast.Name) else None


def _is_text(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_docstring(node):
    return isinstance(node, ast.Expr) and _is_text(node.value)


# --- what the comparison sets aside -----------------------------------------------
# The comparison reads both copies whole, by S for the rest and by U for a unit,
# except for what `SET_ASIDE` names - one row each, its function, and why it
# cannot change what runs. Layout, comments and blank lines are no syntax, so no
# row; anything else that is syntax is compared.

# A doctest prompt: three characters at the start of a docstring line, after
# optional indentation.
_PROMPT = re.compile(r"^[ \t]*>>>", re.M)

# Each skip and expected-failure decorator or call this reading knows, by the
# dotted name it is called through (`*.` any receiver): the position its own
# signature gives the reason, or None for a keyword-only one, and the reason's
# keywords. An expected-failure MARK takes its condition first.
_REASONS = (
    ("unittest.skip", 0, ("reason",)), ("skip", 0, ("reason",)),
    ("unittest.skipIf", 1, ("reason",)), ("skipIf", 1, ("reason",)),
    ("unittest.skipUnless", 1, ("reason",)), ("skipUnless", 1, ("reason",)),
    ("*.skipTest", 0, ("reason",)),
    ("pytest.mark.skip", 0, ("reason",)), ("mark.skip", 0, ("reason",)),
    ("pytest.mark.skipif", None, ("reason",)), ("mark.skipif", None, ("reason",)),
    ("pytest.mark.xfail", None, ("reason",)), ("mark.xfail", None, ("reason",)),
    ("pytest.skip", 0, ("reason", "msg")), ("pytest.xfail", 0, ("reason",)),
)


def _reason_of(call):
    """(position, keywords) of `call`'s reason by `_REASONS`, or None."""
    spelled = _dotted(call.func)
    if spelled is None:
        return None
    for name, at, words in _REASONS:
        if spelled == name or name.startswith("*.") and spelled.endswith(name[1:]):
            return at, words
    return None


def _literal_text_aside(node):
    """`node` - a label, or a reason - as a new node with its literal text
    blanked: a constant string, a `%` format's constant text, an f-string's
    constant pieces. Every expression it formats is kept, so it is compared."""
    if _is_text(node):
        return ast.Constant(value="")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _is_text(node.left):
        return ast.BinOp(left=ast.Constant(value=""), op=node.op, right=node.right)
    if isinstance(node, ast.JoinedStr):
        return ast.JoinedStr(values=[ast.Constant(value="") if _is_text(v) else v
                                     for v in node.values])
    return node


def _reason_aside(tree):
    """Blanks, in place, the literal text of every reason `_REASONS` names in
    `tree` - done on the tree `_parse_test` has just parsed, never on one a
    caller holds: a copy of each definition would cost a deep recursion per
    node, which a long expression in a test turns into a crash."""
    for sub in ast.walk(tree):
        spec = _reason_of(sub) if isinstance(sub, ast.Call) else None
        if spec is None:
            continue
        at, words = spec
        if at is not None and len(sub.args) > at:
            sub.args[at] = _literal_text_aside(sub.args[at])
        for kw in sub.keywords:
            if kw.arg in words:
                kw.value = _literal_text_aside(kw.value)
    return tree


def _docstring_aside(node):
    """Whether `node`, the first statement of a module, class or function body,
    is a docstring set aside: one holding no doctest prompt in this copy. A
    docstring holding one in either copy is then compared - the copy with the
    prompt keeps it, so the two differ unless both hold the same text."""
    return _is_docstring(node) and not _PROMPT.search(node.value.value)


def _bare(node, lazy):
    """Whether a definition evaluates nothing when it is defined: no decorator,
    no default, no type parameter, and no annotation unless the copy's
    annotations are never evaluated (`lazy`)."""
    a = node.args
    notes = [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs
             + [v for v in (a.vararg, a.kwarg) if v is not None]] + [node.returns]
    return not (node.decorator_list or a.defaults or any(d is not None for d in a.kw_defaults)
                or getattr(node, "type_params", None)
                or not lazy and any(n is not None for n in notes))


def _new_test_aside(base_ast, tree_ast, base_records):
    """The tree copy's records of a file read by its definitions, with each
    test new to the tree a unit - its body set aside, nothing of it judged -
    only when it is bare, nested in no function, and under a name no identifier
    of the base copy spells. A test is new when the base copy has no unit of
    its name and count (`_test_units`), so a second definition under an
    existing name is new too. One that is not bare stays a unit only as the
    rename of a base test gone from the tree with the same head and body, so
    `_compare_definitions` judges its head against that test's. Any other new
    test is no unit: it stays in the rest, so its file is not compared, only
    added, naming it - and the copy is walked again, since a definition put
    back may hold another."""
    base_defs, names = _test_units(base_records), _identifiers(base_ast)
    lazy, held = _lazy_annotations(tree_ast), set()

    def key(node, prefix):
        return None if id(node) in held else _test_key(node, prefix)
    while True:
        records = _statements(tree_ast, key)
        tree_defs = _test_units(records)
        nested = dict((id(r["node"]), r["nested"]) for r in records)
        renames = set(_own_dump(e[0], anonymous=True) for k, e in base_defs.items()
                      if k not in tree_defs)
        more = set(id(e[0]) for k, e in tree_defs.items() if k not in base_defs and (
            nested[id(e[0])] or e[0].name in names
            or not _bare(e[0], lazy) and _own_dump(e[0], anonymous=True) not in renames))
        if not more:
            return records
        held |= more


# (what is set aside, the function that sets it aside, why it cannot change what
# runs). Each reason holds for code that only runs these things; code that reads
# a label's or a docstring's text back as a value is not followed, which is the
# reading's stated limit, not a row.
SET_ASIDE = (
    ("a label's literal text", "_literal_text_aside",
     "the text a check prints when it fails; every value the label formats is "
     "evaluated, so it is compared"),
    ("the body of a bare new test, or a new labelled check", "_new_test_aside",
     "nothing of it runs before it runs as the new case it is: a bare new test "
     "evaluates nothing when it is defined and binds a name the base copy spells "
     "nowhere; what a new case does when it runs is not judged (see WHAT THE "
     "READING DOES NOT CLAIM)"),
    ("a docstring holding no example", "_docstring_aside",
     "a string no runner executes; a docstring holding a doctest prompt in either "
     "copy is executed by doctest, so it is compared"),
    ("a reason, where the skip's own signature calls it one", "_reason_aside",
     "the text a skip reports; whether and when the skip applies is in its other "
     "arguments, which are compared"),
)


def _lazy_annotations(tree):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)


def _identifiers(tree):
    """Every identifier `tree` spells - a name bound or read, an attribute, an
    argument, an import - and no string."""
    out = set()
    for node in ast.walk(tree):
        for field in ("id", "name", "attr", "arg", "asname"):
            value = getattr(node, field, None)
            if isinstance(value, str):
                out.update(value.split("."))
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            out.update(node.module.split("."))
    return out


def _parse_test(text):
    """A Python test file's AST with every skip's reason text blanked
    (`_reason_aside`), so no comparison of it sees a reason."""
    return _reason_aside(ast.parse(text))


def _is_pytestmark(node):
    return isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)


def _marks_of(body):
    return tuple(("pytestmark", ast.dump(n.value)) for n in body if _is_pytestmark(n))


def _shape(value):
    """One field of a statement as its head reads it: a node by its dump - a
    handler or a match case by its own head - a statement list by whether it
    holds anything, anything else by its value."""
    if isinstance(value, ast.AST):
        return _head(value) if isinstance(getattr(value, "body", None), list) else ast.dump(value)
    if isinstance(value, list):
        if value and isinstance(value[0], ast.stmt):
            return "<statements>"
        return tuple(_shape(v) for v in value)
    return repr(value)


def _head(node):
    """A statement with every statement inside it taken out: for a compound one,
    what decides whether, how often and under what its inside runs - an `if`'s
    or `while`'s test, a `for`'s target and iterable, a `with`'s items, a
    `try`'s handler types and whether it has an else or a finally, a def's or
    class's name, arguments, bases and decorators. Read off the node's own
    fields, so no kind of statement is listed here and none can be missed."""
    return (type(node).__name__,) + tuple((name, _shape(value))
                                          for name, value in ast.iter_fields(node))


def _bodies(node):
    """[(position, statements)] for each statement list directly inside `node`:
    its own fields, and the body of each handler or match case by its index."""
    out = []
    for name, value in ast.iter_fields(node):
        if not isinstance(value, list) or not value:
            continue
        if isinstance(value[0], ast.stmt):
            out.append((name, value))
        else:
            out.extend(("%s[%d]" % (name, k), sub.body) for k, sub in enumerate(value)
                       if isinstance(getattr(sub, "body", None), list))
    return out


def _first_line(node):
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", ())])


def _statements(tree, unit_key):
    """Every statement of `tree`, outermost first, as a dict: `node`; `chain`,
    the heads of the statements enclosing it with the part of each that holds
    it and every `pytestmark` on the way; `place`, the chain closed by how many
    statements that are not units stand before it in its own part - the words a
    finding gives a unit's place, and its signature for a move to another file,
    while its POSITION in its own file is read by pairing (`_judge`); `parent`,
    the index of the record whose part holds it (None at
    module level), and `part`, which part; `unit`, its key when
    `unit_key(node, prefix)` names one, whose inside is not walked; `nested`,
    whether a function encloses it; `first` and `last`, its lines, decorators
    counted in; `end`, the index just past its last descendant. A leading
    docstring set aside (`_docstring_aside`) is no statement here, as a comment
    is none - the same reading `_own_dump` gives a unit."""
    out = []

    def walk(body, chain, where, prefix, parent, part, nested):
        chain = chain + _marks_of(body)
        before = 0
        for k, node in enumerate(body):
            if k == 0 and where != "block" and _docstring_aside(node):
                continue
            rec = {"node": node, "chain": chain, "place": chain + (("before", before),),
                   "parent": parent, "part": part, "unit": unit_key(node, prefix),
                   "nested": nested, "first": _first_line(node),
                   "last": node.end_lineno or node.lineno}
            here = len(out)
            out.append(rec)
            if rec["unit"] is None:
                before += 1
                for pos, stmts in _bodies(node):
                    inner = chain + ((_head(node), pos),)
                    if isinstance(node, _FUNCTIONS):
                        walk(stmts, inner, "function", prefix, here, pos, True)
                    elif isinstance(node, ast.ClassDef):
                        walk(stmts, inner, "class", prefix + node.name + ".", here, pos, nested)
                    else:
                        walk(stmts, inner, "block", prefix, here, pos, nested)
            rec["end"] = len(out)
    walk(tree.body, (), "module", "", None, None, False)
    return out


def _test_key(node, prefix):
    """A test definition's key - `Class.method` under its classes - or None."""
    if isinstance(node, _FUNCTIONS) and node.name.startswith(TEST_PREFIX):
        return prefix + node.name
    return None


def _collected_tests(records):
    """Whether `records` hold a test definition the runner collects - one no
    function encloses. Which reading a file gets is decided by these alone: a
    helper named with the test prefix inside a row suite's cases function is
    collected by no runner, and counting it would leave every labelled check of
    the file uncompared. Once a file is read by its definitions, a nested one is
    a unit like any other, so a test moved into a function is still seen."""
    inside = set()
    for k, rec in enumerate(records):
        if isinstance(rec["node"], _FUNCTIONS) and rec["unit"] is None:
            inside.update(range(k + 1, rec["end"]))
    return any(rec["unit"] for k, rec in enumerate(records) if k not in inside)


# --- a unit's position, read by pairing -------------------------------------------
# A part is a statement list: the module's body, a function's, a class's, each
# part of a compound statement. Its statements that are not units form a sequence
# of TOKENS - a simple statement's dump, a compound one's head (`_own`), so a
# function whose body gained a line still pairs with itself. A BEST PAIRING of two
# such sequences is a longest common subsequence, and there can be several. A unit
# standing after i statements of the base part and after j of the tree part is IN
# PLACE when some best pairing pairs nothing across it: LCS(first i, first j) +
# LCS(rest, rest) == LCS(whole, whole). A statement enclosing a unit is in place by
# the same test with itself as a paired member, and the two are then read part by
# part - body with body, else with else, each handler with the handler of the same
# place, finally with finally. A unit is IN THE SAME POSITION when every statement
# enclosing it from the module down is in place, the `pytestmark` of each body on
# the way is the same, and it is in place in its own part.
#
# So a statement added before a unit leaves it in place, a duplicate of an
# existing statement inserted beside it included - one best pairing crosses it and
# another does not, and one is enough. A unit moved across a statement, under a new
# or another block, or into a later block whose head reads the same is not in
# place. Two adjacent units swapped are both in place: no statement that is not a
# unit stands between them.
#
# A count of the statements before a unit is a position only when the statements
# counted are the same in both copies; it survives here only where nothing pairs
# two copies - the signature that recognises a unit moved to another file, and the
# words of a finding.
#
# The tables are built once per pair of parts, forwards and backwards, for exactly
# the cells the judgements ask (`_judge`), so each unit's test is a lookup. A cell
# inside the common prefix or suffix of two sequences is read off its length
# without a table, which is where the cells of an ordinary edit fall.

def _layout(records):
    """One copy's parts: `parts` maps (parent record index, part) to the indices
    of its statements that are not units, in order; `slot` gives each record its
    index among them, or for a unit how many of them stand before it."""
    parts, slot = {}, {}
    for k, rec in enumerate(records):
        here = parts.setdefault((rec["parent"], rec["part"]), [])
        slot[k] = len(here)
        if rec["unit"] is None:
            here.append(k)
    return {"records": records, "parts": parts, "slot": slot}


def _tokens(layout, part):
    records = layout["records"]
    return [_own(records[k]["node"]) for k in layout["parts"].get(part, ())]


def _chain(layout, k):
    """[(part, slot, record index)] from the module's part down to record k's."""
    records, out = layout["records"], []
    while k is not None:
        rec = records[k]
        out.append(((rec["parent"], rec["part"]), layout["slot"][k], k))
        k = rec["parent"]
    return out[::-1]


def _marks_on_the_way(rec):
    """The `pytestmark`s of each body enclosing a record, level by level."""
    return tuple(("|",) if isinstance(c[0], tuple) else c for c in rec["chain"])


def _plan(base, tree, b, t):
    """The in-place tests deciding whether tree record `t` stands where base record
    `b` does: [(base part, tree part, kind, i, j)], kind "member" for an enclosing
    statement and "unit" for the record itself; None when no pairing can make it
    so - another depth, another part of an enclosing statement, another head or
    another `pytestmark` on the way."""
    cb, ct = _chain(base, b), _chain(tree, t)
    if len(cb) != len(ct) or _marks_on_the_way(base["records"][b]) != \
            _marks_on_the_way(tree["records"][t]):
        return None
    out = []
    for d, ((pb, ib, kb), (pt, it, kt)) in enumerate(zip(cb, ct)):
        last = d == len(cb) - 1
        if pb[1] != pt[1] or not last and _own(base["records"][kb]["node"]) != \
                _own(tree["records"][kt]["node"]):
            return None
        out.append((pb, pt, "unit" if last else "member", ib, it))
    return out


def _lcs_rows(a, b, points):
    """{(i, j): LCS(a[:i], b[:j])} for each of `points`: one table, its rows kept
    one at a time and cut at the last row and column a point asks for."""
    out, rows = {}, {}
    for i, j in points:
        if i == 0 or j == 0:
            out[(i, j)] = 0
        else:
            rows.setdefault(i, []).append(j)
    if not rows:
        return out
    width = max(j for js in rows.values() for j in js)
    cols, prev = b[:width], [0] * (width + 1)
    for i in range(1, max(rows) + 1):
        x, cur = a[i - 1], [0] * (width + 1)
        for j, y in enumerate(cols, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
            else:
                up, left = prev[j], cur[j - 1]
                cur[j] = up if up > left else left
        for j in rows.get(i, ()):
            out[(i, j)] = cur[j]
        prev = cur
    return out


def _pairing(a, b, fwd, bwd):
    """The pairing of two token sequences as the in-place tests read it: `L` the
    length of a best pairing, `F` LCS(a[:i], b[:j]) for each of `fwd`, `B`
    LCS(a[i:], b[j:]) for each of `bwd`; None when the sequences are equal, where a
    unit is in place exactly at its own slot. Inside the common prefix of length
    p, F is min(i, j) and B at i == j is L - i; inside the common suffix of length
    s, B is min(n - i, m - j) and F at aligned ends is L less the shared tail - so
    only a cell between the two needs a table."""
    if a == b:
        return None
    ids = {}
    a = [ids.setdefault(x, len(ids)) for x in a]
    b = [ids.setdefault(x, len(ids)) for x in b]
    n, m = len(a), len(b)
    p = 0
    while p < min(n, m) and a[p] == b[p]:
        p += 1
    s = 0
    while s < min(n, m) - p and a[n - 1 - s] == b[m - 1 - s]:
        s += 1
    core = (n - s - p, m - s - p)
    big = p + s + _lcs_rows(a[p:n - s], b[p:m - s], [core])[core]
    forward, todo = {}, []
    for i, j in fwd:
        if min(i, j) <= p:
            forward[(i, j)] = min(i, j)
        elif n - i == m - j <= s:
            forward[(i, j)] = big - (n - i)
        else:
            todo.append((i, j))
    got = _lcs_rows(a[p:], b[p:], [(i - p, j - p) for i, j in todo])
    forward.update(((i, j), p + got[(i - p, j - p)]) for i, j in todo)
    backward, todo = {}, []
    for i, j in bwd:
        if min(n - i, m - j) <= s:
            backward[(i, j)] = min(n - i, m - j)
        elif i == j <= p:
            backward[(i, j)] = big - i
        else:
            todo.append((i, j))
    got = _lcs_rows(a[:n - s][::-1], b[:m - s][::-1], [(n - s - i, m - s - j) for i, j in todo])
    backward.update(((i, j), s + got[(n - s - i, m - s - j)]) for i, j in todo)
    return {"a": a, "b": b, "L": big, "F": forward, "B": backward}


def _in_place(pairing, kind, i, j):
    if pairing is None:
        return i == j
    if kind == "member":
        return pairing["a"][i] == pairing["b"][j] and \
            pairing["F"][(i, j)] + 1 + pairing["B"][(i + 1, j + 1)] == pairing["L"]
    return pairing["F"][(i, j)] + pairing["B"][(i, j)] == pairing["L"]


def _judge(base, tree, pairs):
    """{(base record, tree record): whether the tree one stands in the base one's
    position} for each of `pairs`; `base` and `tree` are `_layout`s. Every cell
    the tests ask is gathered first, so each pair of parts gets one table each way."""
    plans = dict((pair, _plan(base, tree, pair[0], pair[1])) for pair in set(pairs))
    need = {}
    for plan in plans.values():
        for pb, pt, kind, i, j in plan or ():
            fwd, bwd = need.setdefault((pb, pt), (set(), set()))
            fwd.add((i, j))
            bwd.add((i + 1, j + 1) if kind == "member" else (i, j))
    tables = dict((key, _pairing(_tokens(base, key[0]), _tokens(tree, key[1]), fwd, bwd))
                  for key, (fwd, bwd) in need.items())
    return dict((pair, plan is not None and all(_in_place(tables[(pb, pt)], kind, i, j)
                                                for pb, pt, kind, i, j in plan))
                for pair, plan in plans.items())


def _dump(entry, anonymous=False):
    """One definition as the comparison reads it: `ast.dump` without line
    numbers or what `SET_ASIDE` names, followed by its position;
    `anonymous` also drops its name, to recognise a rename."""
    node, place = entry[:2]
    return "%s %r" % (_own_dump(node, anonymous), place)


def _place_text(place):
    """A position in words: the innermost statement enclosing it and which part
    of it, and how many statements that are not units stand before it there."""
    heads = [c for c in place if isinstance(c[0], tuple)]
    if heads:
        head, pos = heads[-1]
        name = dict(head[1:]).get("name")
        where = "in the %s of the %s%s" % (pos, head[0], " %s" % name if name else "")
    else:
        where = "at module level"
    return "%s, after %d statement(s) that are not units" % (where, place[-1][1])


def _moved_what(kind, name, base, tree):
    """The finding for a unit whose own text is the same and whose position is
    not; `base` and `tree` are each (line, place)."""
    return ("%s `%s` is unchanged, but it moved - a statement enclosing it, or the "
            "statements before it there, differ: from base line %d (%s) to tree line "
            "%d (%s)" % (kind, name, base[0], _place_text(base[1]), tree[0],
                         _place_text(tree[1])))


def _own_dump(node, anonymous=False):
    if not isinstance(node, _FUNCTIONS):
        return ast.dump(node)
    clone = copy.copy(node)
    if clone.body and _docstring_aside(clone.body[0]):
        clone.body = clone.body[1:]
    if anonymous:
        clone.name = ""
    return ast.dump(clone)


# The part of a changed unit that differs, as the finding's `part` names it, and
# the words its text says it with.
PARTS = (("callee", "what it is called through"), ("arguments", "its condition and arguments"),
         ("label", "its label's values"), ("head", "its head"), ("body", "its body"))


def _def_parts(node):
    """(head, body) of a test definition as the comparison reads them: its
    decorators, name, arguments and annotations; its statements."""
    clone = copy.copy(node)
    body = clone.body[1:] if clone.body and _docstring_aside(clone.body[0]) else clone.body
    clone.body = []
    return ast.dump(clone), "".join(ast.dump(s) for s in body)


def _differs(words, base, tree):
    """(part, text) for a changed unit: each of `words` whose reading differs
    between the base's `base` and the tree's `tree`, joined by `+`, and the
    phrase saying so."""
    said = dict(PARTS)
    hit = [w for w, b, t in zip(words, base, tree) if b != t]
    return "+".join(hit), " and ".join(said[w] for w in hit)


def _test_units(records):
    """{(name, n): (node, place, record index)} for the test definitions of
    `records`. `n` counts back from the last definition of a name, so 0 is the
    one Python keeps - and a weaker test appended under an existing name is a
    change to that name - while an earlier one is still compared as itself."""
    by_name = collections.OrderedDict()
    for k, rec in enumerate(records):
        if rec["unit"] is not None:
            by_name.setdefault(rec["unit"], []).append((rec["node"], rec["place"], k))
    return dict(((q, n), entry) for q, entries in by_name.items()
                for n, entry in enumerate(reversed(entries)))


def _compare_definitions(base_records, tree_records, new):
    """(changed, renamed, fresh). `changed` holds (unit, what, line, side, sign,
    part) - `unit` is ("def", name), `sign` is set on a definition that is gone,
    so one that reappears unchanged in another file of the diff is a move, and
    `part` says what differs (`PARTS`, or "position" or "gone");
    `renamed` holds {path, from, to, line}; `fresh` holds (sign, name, line)
    for each test new to the tree copy. A rename keeps the body AND the
    position, and so does a move to another file - read there by the count of
    statements before it, since no pairing spans two files."""
    base_defs, tree_defs = _test_units(base_records), _test_units(tree_records)
    fresh = dict((k, e) for k, e in tree_defs.items() if k not in base_defs)
    base, tree = _layout(base_records), _layout(tree_records)
    kept = _judge(base, tree, [(e[2], tree_defs[k][2]) for k, e in base_defs.items()
                               if k in tree_defs])
    shapes = dict((k, _own_dump(e[0], anonymous=True)) for k, e in fresh.items())
    named = _judge(base, tree, [(e[2], f[2]) for k, e in base_defs.items() if k not in tree_defs
                                for fk, f in fresh.items()
                                if shapes[fk] == _own_dump(e[0], anonymous=True)])
    changed, renamed = [], []
    for key, entry in sorted(base_defs.items(), key=lambda kv: kv[1][0].lineno):
        qual = key[0]
        if key in tree_defs:
            twin = tree_defs[key]
            if _own_dump(entry[0]) != _own_dump(twin[0]):
                part, said = _differs(("head", "body"), _def_parts(entry[0]),
                                      _def_parts(twin[0]))
                changed.append((("def", qual), "definition `%s` differs from its base copy "
                                "in %s" % (qual, said), twin[0].lineno, "tree", None, part))
            elif not kept[(entry[2], twin[2])]:
                changed.append((("def", qual), _moved_what(
                    "definition", qual, (entry[0].lineno, entry[1]),
                    (twin[0].lineno, twin[1])), twin[0].lineno, "tree", None, "position"))
            continue
        twin = next((k for k in sorted(fresh) if named.get((entry[2], fresh[k][2]))), None)
        if twin is None:
            changed.append((("def", qual), "definition `%s` is gone from the tree copy" % qual,
                            entry[0].lineno, "base", ("def", _dump(entry, anonymous=True)),
                            "gone"))
        else:
            renamed.append({"path": new, "from": qual, "to": twin[0],
                            "line": fresh.pop(twin)[0].lineno})
    return changed, renamed, [(("def", _dump(e, anonymous=True)), k[0], e[0].lineno)
                              for k, e in sorted(fresh.items())]


# --- labelled checks: a suite written as script rows ------------------------------
# A Python test file that defines no collected test is read as a script of checks: the
# calls of ONE callable whose first argument is a constant string (or a `%` or
# f-string format whose text is constant) are its cases, each named by that
# label. The callable is the one most such call statements of the BASE copy go
# to, so a check the tree calls through another name is a check gone. Checks
# are compared by label, callee, arguments, the values the label formats and
# position: a label that is gone is a removed case, one whose callee, other
# arguments or label values changed is a changed case, one whose position
# changed has moved. Only the label's literal text is set aside
# (`_literal_text_aside`): a check whose literal text alone changed is a rename.

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


def _check_key(callables):
    """`unit_key` for `_statements`: a labelled check's label, or None."""
    def key(node, _prefix):
        call = _check_of(node, callables) if callables else None
        return _label_of(call) if call is not None else None
    return key


def _checks(records):
    """[(label, signature, place, line, record index)] for each labelled check of
    `records`; the signature is (the name it is called through, its other
    arguments, its label with the literal text set aside) - the order of
    `_CHECK_PARTS`."""
    out = []
    for k, rec in enumerate(records):
        if rec["unit"] is not None:
            call = rec["node"].value
            sign = (ast.dump(call.func),
                    "|".join([ast.dump(a) for a in call.args[1:]]
                             + [ast.dump(kw) for kw in call.keywords]),
                    ast.dump(_literal_text_aside(call.args[0])))
            out.append((rec["unit"], sign, rec["place"], rec["node"].lineno, k))
    return out


_CHECK_PARTS = ("callee", "arguments", "label")


def _alike(base_checks, tree_checks, key):
    """(base record, tree record) for each two checks `key` reads the same -
    grouped, so a suite of many checks is not paired all against all."""
    by = {}
    for t in tree_checks:
        by.setdefault(key(t), []).append(t[4])
    return [(b[4], k) for b in base_checks for k in by.get(key(b), ())]


def _case_id(label):
    words = label.split()
    return words[0].rstrip(":") if words else label


def _take(found, left, same):
    """Pair each of `found` with the first of `left` that `same` accepts; the
    pairs, and what of `found` stayed alone. `left` loses what was paired."""
    pairs, alone = [], []
    for item in found:
        twin = next((x for x in left if same(item, x)), None)
        if twin is None:
            alone.append(item)
        else:
            left.remove(twin)
            pairs.append((item, twin))
    return pairs, alone


def _compare_checks(base_records, tree_records, new):
    """(changed, renamed, fresh), in `_compare_definitions`' shapes, over the
    labelled checks of the two copies: paired first on label, signature and
    position, then on label and signature - a check that moved - then on label
    alone - a check whose arguments changed - then on signature and position,
    a rename. A check gone, or new, carries its position in its move signature,
    so one placed elsewhere in another file of the diff is no move."""
    base_checks, tree_left = _checks(base_records), _checks(tree_records)
    base, tree = _layout(base_records), _layout(tree_records)
    kept = _judge(base, tree, _alike(base_checks, tree_left, lambda c: c[:2]))
    _same, base_left = _take(base_checks, tree_left,
                             lambda b, t: b[:2] == t[:2] and kept[(b[4], t[4])])
    moved, base_left = _take(base_left, tree_left, lambda b, t: b[:2] == t[:2])
    edited, base_left = _take(base_left, tree_left, lambda b, t: b[0] == t[0])
    still = _judge(base, tree, _alike(base_left, tree_left, lambda c: c[1]))
    named, gone = _take(base_left, tree_left, lambda b, t: still.get((b[4], t[4]), False))
    changed = [(("check", b[0]), _moved_what("labelled check", _short(b[0]), (b[3], b[2]),
                                             (t[3], t[2])), t[3], "tree", None, "position")
               for b, t in moved]
    for b, t in edited:
        part, said = _differs(_CHECK_PARTS, b[1], t[1])
        changed.append((("check", b[0]), "labelled check `%s` differs from its base copy in %s"
                        % (_short(b[0]), said), t[3], "tree", None, part))
    changed += [(("check", b[0]), "labelled check `%s` is gone from the tree copy"
                 % (_short(b[0]),), b[3], "base", ("check",) + b[:3], "gone") for b in gone]
    renamed = [{"path": new, "from": b[0], "to": t[0], "line": t[3]} for b, t in named]
    return (sorted(changed, key=lambda c: (c[3], c[2])), renamed,
            [(("check",) + t[:3], t[0], t[3]) for t in tree_left])


def _short(text, width=70):
    return text if len(text) <= width else text[:width - 3] + "..."


# --- the rest is the same ---------------------------------------------------------
# A Python test file reads as compared only when two things hold, each a
# comparison of syntax trees and never of lines:
#   S. THE REST IS THE SAME. With every unit taken out of each copy, what is left
#      is identical: the same statements, in the same order, each in the same
#      part of the same enclosing statement. A compound statement is read by its
#      head (`_head`) and then its parts, any other by its dump, so a comment, a
#      blank line or a layout change is no difference, and of what is syntax
#      only what `SET_ASIDE` names is left out.
#   U. EVERY BASE UNIT HAS ITS TWIN in the tree copy, with the same own syntax
#      and the same position - compared in the two sections above.
# When S fails the file is listed as not compared, and the reason says which of
# two things its rest is, computed by fitting the base copy's rest into the tree
# copy's, in order and in place (`_fit`): ONLY ADDED when it fits and the tree
# copy holds more - the first added statement is named - or CHANGED OR REMOVED
# otherwise - the first base statement with no place is named. Nothing here asks
# what a statement does: the reading compares structure and never evaluates
# code, so no added statement is judged by what it would run.

def _own(node):
    """A statement outside the units as S reads it: a compound one by its head,
    any other by its dump."""
    return repr(_head(node)) if _bodies(node) else ast.dump(node)


def _rest(records):
    """The statements of `records` that are not units, as a tree of
    (reading, record index, {part: [...]}) items; a part left holding units
    only is no part here."""
    items, top = {}, []
    for k, rec in enumerate(records):
        if rec["unit"] is not None:
            continue
        item = (_own(rec["node"]), k, collections.OrderedDict())
        items[k] = item
        if rec["parent"] is None:
            top.append(item)
        else:
            items[rec["parent"]][2].setdefault(rec["part"], []).append(item)
    return top


def _same_rest(base_items, tree_items):
    """S: the two rests are identical, part by part."""
    return len(base_items) == len(tree_items) and all(
        b[0] == t[0] and list(b[2]) == list(t[2])
        and all(_same_rest(b[2][part], t[2][part]) for part in b[2])
        for b, t in zip(base_items, tree_items))


def _fits(base_item, tree_item):
    """Whether one base statement has its place in one tree statement: the same
    reading, and each of its parts fitting into the same part of the tree's."""
    return base_item[0] == tree_item[0] and all(
        _fit(sub, tree_item[2].get(part, [])) is None for part, sub in base_item[2].items())


def _fit(base_items, tree_items):
    """None when `base_items` fit into `tree_items` in order; otherwise the
    record index of the first base statement with no place - read inside a tree
    statement of the same reading when one stands for it. Pairing each base
    statement with the earliest tree statement it fits is enough: a later
    pairing never leaves more room for the statements after it."""
    j = 0
    for b in base_items:
        k = next((i for i in range(j, len(tree_items)) if _fits(b, tree_items[i])), None)
        if k is not None:
            j = k + 1
            continue
        same = next((t for t in tree_items[j:] if t[0] == b[0]), None)
        for part, sub in (b[2].items() if same is not None else ()):
            inner = _fit(sub, same[2].get(part, []))
            if inner is not None:
                return inner
        return b[1]
    return None


def _added(base_items, tree_items):
    """The record indices of the outermost tree statements no base statement was
    paired with; only asked when `base_items` fit into `tree_items`."""
    out, j = [], 0
    for b in base_items:
        while not _fits(b, tree_items[j]):
            out.append(tree_items[j][1])
            j += 1
        twin = tree_items[j]
        j += 1
        for part, sub in twin[2].items():
            out.extend(_added(b[2].get(part, []), sub))
    return out + [t[1] for t in tree_items[j:]]


def _statement_text(lines, rec):
    """The first source line of a statement, stripped and shortened - and for a
    decorated definition, whose first line is a decorator, the name it defines."""
    first, node = rec["first"], rec["node"]
    text = _short(lines[first - 1].strip()) if 0 < first <= len(lines) else ""
    if _is_docstring(node) and not text.strip("\"'rRuUbB"):
        said = [ln.strip() for ln in node.value.value.splitlines() if ln.strip()]
        text = _short("%s %s" % (text, said[0] if said else ""))
    if getattr(node, "decorator_list", None) and isinstance(node, _FUNCTIONS + (ast.ClassDef,)):
        text = "%s ... %s %s" % (text, "class" if isinstance(node, ast.ClassDef) else "def",
                                 node.name)
    return text


def _rest_reason(base, tree, held):
    """None when S holds; otherwise the reason the file is not compared, saying
    which of the two things its rest is and naming the statement. `base` and
    `tree` are each (records, the copy's lines)."""
    base_rest, tree_rest = _rest(base[0]), _rest(tree[0])
    if _same_rest(base_rest, tree_rest):
        return None
    miss = _fit(base_rest, tree_rest)
    added = _added(base_rest, tree_rest) if miss is None else []
    if added:
        rec = min((tree[0][k] for k in added), key=lambda r: r["first"])
        return ("code outside %s was only added: every statement of the base copy "
                "outside them stands in the tree copy, in order and in place, and the "
                "first added one is at tree line %d (`%s`); what it runs is not compared"
                % (held, rec["first"], _statement_text(tree[1], rec)))
    if miss is None:
        return ("code outside %s differs between the copies, and no statement of either "
                "could be named as the first difference; it is not compared" % (held,))
    rec = base[0][miss]
    return ("code outside %s was changed or removed: the first statement of the base "
            "copy outside them with no place in the tree copy is at base line %d (`%s`), "
            "and what the code there does for a case is not compared"
            % (held, rec["first"], _statement_text(base[1], rec)))


# --- declared -------------------------------------------------------------------

# A DECLARATION COVERS WHAT IS NEW. A bare `path` entry - what the drive files
# when the task's return binds no case to a `tests.add` file, and always on the
# writer route - covers the definitions new to the tree copy, which are no move
# in the first place, and nothing the base already held: an existing test
# changed in the file a task adds to is still a finding. Only a `path::case`
# entry declares a change to a test that exists at the base, and only when
# exactly one unit of the base copy of that file answers to it - a definition by
# its `Class.method` name or its method name, a labelled check by its whole
# label or its case id. A declaration several base units answer to covers none
# of them, and the finding says so. A line of a non-Python test maps to no case
# name, so a change to one the base held is never declared.

def _declared_index(declared):
    """{path: {case name: the case as written}} from the `path::case` entries of
    `declared`; a pytest-style `Class::method` case is read as `Class.method`. A
    bare path adds nothing, as the comment above says."""
    cases = {}
    for entry in declared or ():
        path, sep, case = str(entry).replace("\\", "/").partition("::")
        if sep and case:
            cases.setdefault(path, {})[case.replace("::", ".")] = case
    return cases


def _answers(case, unit):
    kind, name = unit
    if kind == "def":
        return case == name or case == name.rsplit(".", 1)[-1]
    return case == name or case == _case_id(name)


def _declaration(index, paths, unit, base_units):
    """(covered, note): whether a `path::case` entry covers the changed base
    `unit`, and - when one answers to it and to other base units too - the
    sentence saying it is ambiguous and what would name this unit alone."""
    note = None
    for path in [p for p in paths if p]:
        for case, written in sorted(index.get(path, {}).items()):
            if not _answers(case, unit):
                continue
            count = sum(1 for u in base_units if _answers(case, u))
            if count == 1:
                return True, None
            whole = unit[1] if unit[0] == "check" else unit[1].replace(".", "::")
            alone = sum(1 for u in base_units if u == unit) == 1
            note = ("the declaration `%s::%s` answers to %d units of the base copy, so "
                    "it is ambiguous and covers none of them; %s" % (
                        path, written, count,
                        ("`%s::%s` would name this one alone" % (path, whole)) if alone
                        else "no `path::case` names this one alone"))
    return False, note


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
    """{findings, declared, renamed, gone, fresh, units, problem, notRead} for one
    file of the diff. `notRead` is one entry or None; its `move` is None when no
    move was read, and names the move left uncompared otherwise. `gone` pairs
    each finding for a test that disappeared with its signature, and `fresh`
    lists the signatures of tests new to this file, so a test moved between two
    files of the diff is read as moved. `units` is (the base units compared,
    [(name, line)] of the new ones) for a Python test file read as compared."""
    out = {"findings": [], "declared": [], "renamed": [], "gone": [], "fresh": [],
           "units": None, "problem": None, "notRead": None}
    path = rec["new"] or rec["old"]
    if rec["status"] == "deleted":
        if is_test_path(rec["old"]):
            out["findings"].append(_finding(TEST_DELETED, rec["old"], 1, "base",
                                            "test file deleted"))
        return out
    if rec["status"] == "renamed" and not _still_a_test(rec["old"], rec["new"]):
        out["findings"].append(_finding(TEST_DELETED, rec["old"], 1, "base", (
            "test file moved to %s, which is not a test path by the reading that made "
            "the old one a test" % rec["new"])))
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
            got = _collect(rec, (base, base_ast), (tree, tree_ast), fam, test,
                           (index, accepted))
            got["findings"] = out["findings"] + got["findings"]
            out.update(got)
        except (tokenize.TokenError, SyntaxError) as exc:
            problem = "%s does not tokenize (%s)" % (path, exc)
    out["problem"] = problem
    return out


def _collect(rec, base, tree, fam, test, ask):
    """{findings, declared, renamed, gone, fresh, units, notRead} for one file
    whose copies were read; `base` and `tree` are each (text, Python AST or None)
    and `ask` is (declared index, accepted suppression keys)."""
    index, accepted = ask
    path = rec["new"]
    base_marks = _side_marks(base[0], base[1], fam, test) if base[0] is not None else []
    tree_marks = _side_marks(tree[0], tree[1], fam, test)
    out = {"findings": [], "declared": [], "renamed": [], "gone": [], "fresh": [],
           "units": None, "notRead": None}
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
        _python_test(out, rec, base, tree, index)
    elif test and base[0] is not None and not path.lower().endswith(DATA_EXTENSIONS) \
            and not any(m[0] == "assertion" for m in base_marks + tree_marks):
        out["notRead"] = _unread(path, DEFINITION_CHANGED, (
            "no assertion pattern this reading knows matched a line of either copy, "
            "so whether an existing case was weakened was not compared"), True)
    return out


def _python_test(out, rec, base, tree, index):
    """Fill `out` with what comparing a Python test file's two copies found:
    its test definitions, or - a file that defines none - its labelled checks
    (U), then whether the rest is the same (S); `units` is set only when it is.
    `base` and `tree` are each (text, AST). A file new to the diff is read
    against an empty base copy."""
    path, paths = rec["new"], (rec["new"], rec["old"])
    base_text, base_ast = ("", ast.parse("")) if base[1] is None else base
    tree_text, tree_ast = tree
    has_tests = any(_collected_tests(_statements(t, _test_key)) for t in (base_ast, tree_ast))
    callables = (None if has_tests else
                 _check_callables([base_ast]) or _check_callables([tree_ast]))
    unit_key = _test_key if has_tests else _check_key(callables)
    base_records = _statements(base_ast, unit_key)
    tree_records = (_new_test_aside(base_ast, tree_ast, base_records) if has_tests
                    else _statements(tree_ast, unit_key))
    changed, out["renamed"], out["fresh"] = (
        _compare_definitions(base_records, tree_records, path) if has_tests
        else _compare_checks(base_records, tree_records, path))
    base_units = [("def" if has_tests else "check", r["unit"]) for r in base_records
                  if r["unit"] is not None]
    for unit, what, line, side, sign, part in changed:
        covered, note = _declaration(index, paths, unit, base_units)
        found = _finding(DEFINITION_CHANGED, path if side == "tree" else rec["old"],
                         line, side, what if note is None else "%s - %s" % (what, note))
        found["part"] = part
        if covered:
            out["declared"].append(found)
            continue
        out["findings"].append(found)
        if sign is not None:
            out["gone"].append((found, sign))
    held = ("its test definitions" if has_tests else "its labelled checks"
            if callables else "any test - it defines none and calls no labelled check")
    reason = _rest_reason((base_records, _text_lines(base_text)),
                          (tree_records, _text_lines(tree_text)), held)
    if reason is not None:
        out["notRead"] = _unread(path, DEFINITION_CHANGED, reason, True)
    else:
        out["units"] = (len(base_units), [(name, line) for _s, name, line in out["fresh"]])


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


def _test_readings(path):
    """Which readings of `is_test_path` make `path` a test: its own name, and
    the directory it sits in - each asked of `is_test_path` alone."""
    head, _sep, name = str(path or "").replace("\\", "/").rpartition("/")
    found = set()
    if is_test_path(name):
        found.add("name")
    if head and is_test_path(head + "/-"):
        found.add("directory")
    return found


def _still_a_test(old, new):
    """Whether a file moved from `old` to `new` is the same kind of file - a
    test only when every reading that made `old` a test also makes `new` one -
    in the same comment family. A test moved anywhere else is a test deleted."""
    return (family(old) == family(new)
            and _test_readings(old) <= _test_readings(new))


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
                     if _still_a_test(records[g]["old"], records[a]["new"])),
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
    units = []
    for rec in records:
        got = _one_file(rec, read_base, read_tree, index, keys)
        if got["units"] is not None:
            units.append((rec["new"],) + got["units"])
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
                 "(%s)%s%s" % (len(records) - len(not_read), len(records),
                               ", ".join(MOVES), _units_text(units, renamed), tail))
    return _result(answer, basis, findings, owned, renamed, cannot, not_read)


def _units_text(units, renamed):
    """How many existing units the compared Python test files held and how many
    new ones they gained - a unit moved in from another file of the diff is not
    new - with the new ones named; "" when no such file was compared."""
    if not units:
        return ""
    moved = set((r["path"], r["to"], r["line"]) for r in renamed)
    new = ["`%s` in %s" % (name, path) for path, _n, fresh in units
           for name, line in fresh if (path, name, line) not in moved]
    return ("; %d existing unit(s) compared, %d new unit(s) counted and not judged%s"
            % (sum(u[1] for u in units), len(new),
               (": " + _output.some_of(new)) if new else ""))


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
