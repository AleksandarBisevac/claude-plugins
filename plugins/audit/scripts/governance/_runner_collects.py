#!/usr/bin/env python3
"""
Does the test runner collect this path - ONE answer, three possible.

WHY THIS IS A MODULE. A task that adds `lib/store.test.ts` to a project whose
`vitest.config.ts` includes only `tests/unit/**` produces a test the gate will
never run, and the run learns it only after the work is done. Whether the runner
would collect a path is a question about the runner's configuration, and several
callers (the task-start preflight, the scope companions) must get the same answer,
so it lives in one place.

THE ANSWER HAS THREE VALUES AND ONLY ONE MAY STOP A RUN. `NOT_COLLECTED` is
definite; `COLLECTED` is a reading; `COULD_NOT_TELL` carries no verdict at all and
is the answer for anything the module does not understand - an unknown runner, an
include that is a variable or a spread, a config that merges another, a glob form
it does not translate. There is no fall-through to `COLLECTED`: a guess in that
direction is invisible, a guess in the other stops work that was fine.

THE ORDER IS THE RUNNER'S OWN LIST FIRST, THEN THE CONFIG TEXT. A listing is what the
runner will actually do, so it outranks a reading of its config; it is used only
for the three runners below, only from a binary already on disk in the project
(`node_modules/.bin` for vitest and jest, a virtualenv's `bin` for pytest -
nothing is downloaded), and only when it prints at least one file. An empty or
failed listing is not an answer: it falls through to the config. A listing answers
for a path that exists; for one that does not exist yet it answers through the
files beside it that share its suffix, and says nothing when there are none.
Only the vitest listing (`vitest list --filesOnly`) was captured from a real run
when this was written; the jest (`--listTests`) and pytest (`--collect-only -q`)
readers follow those flags' documented output and have been exercised only
through an injected lister, because neither binary was installed here.
pytest's listing names only files that hold at least one test, so it can prove a
file IS collected and can never prove one is not: its absence is no answer.

A MISMATCH IS SOUNDER THAN A MATCH. An `exclude` can only remove files an
`include` admitted, so a path that fits no literal include is definitely not
collected, while one that fits is only collected if nothing excludes it. A config
that declares an `exclude` therefore turns a match into `COULD_NOT_TELL` and leaves
a mismatch definite.

THE CONFIG IS READ AS TEXT, NEVER EXECUTED. Node is not imported and no config
runs. The text is tokenised (strings, comments and regex literals are skipped, so
an `include` in a comment or under `coverage` is not the test's), the object that
holds the key is found by bracket depth, and the value must be an array of plain
string literals.

Semantics relied on, and where each came from:
  * vitest `test.include` / default include `**/*.{test,spec}.?(c|m)[jt]s?(x)` and
    default exclude `**/node_modules/**`, `**/.git/**`: read from
    `vitest@5.0.3`'s own `dist/chunks/defaults.*.js`, and every glob form in
    the cases was also given to a real `vitest list` as an include.
  * glob syntax (`**`, `*`, `?`, `[..]`, `{a,b}`, `?(a|b)`, `+()`, `*()`, `@()`):
    picomatch for vitest; jest's configuration page names micromatch for
    `testMatch`, which speaks the same forms. Negation (`!(..)`, a leading
    `!`), numeric brace ranges, escapes and dot-files are not translated; they
    answer `None`.
  * jest `testMatch` default `**/__tests__/**/*.[jt]s?(x)` and
    `**/?(*.)+(spec|test).[jt]s?(x)`, `roots` default `["<rootDir>"]`: jest's
    configuration documentation. The current page spells the default extension as
    `?([mc])[jt]s?(x)`, so whether `.mjs`, `.cjs`, `.mts` and `.cts` are collected
    depends on the jest version, and a default-config answer for one of those is
    `COULD_NOT_TELL`. Jest matches `testMatch` against the absolute
    path, so a pattern that starts with neither `**/` nor `<rootDir>/` is not read.
  * pytest `python_files` default `["test_*.py", "*_test.py"]`, searched under
    `testpaths` when no file argument is given: pytest's reference page, whose
    `python_files` entry says these are glob patterns for "python files ...
    considered as test modules" and whose `testpaths` entry says it applies only
    "when no specific directories, files or test ids are given". These describe a run with no file arguments; pytest also
    collects a file given by name on the command line whatever its name.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__runner_collects.py`.
"""

import os
import re
import subprocess
import sys

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

COLLECTED = "collected"
NOT_COLLECTED = "not-collected"
COULD_NOT_TELL = "could-not-tell"

LIST_TIMEOUT = 30
JEST_VERSIONED_EXTENSIONS = (".mjs", ".cjs", ".mts", ".cts")
PYTEST_BINARIES = (".venv/bin/pytest", "venv/bin/pytest", ".venv/Scripts/pytest.exe",
                   "venv/Scripts/pytest.exe")
VITEST_CONFIGS = tuple("vitest.config." + e for e in ("ts", "mts", "cts", "js", "mjs", "cjs"))
VITE_CONFIGS = tuple("vite.config." + e for e in ("ts", "mts", "cts", "js", "mjs", "cjs"))
JEST_CONFIGS = tuple("jest.config." + e for e in ("ts", "mts", "cts", "js", "mjs", "cjs", "json"))
VITEST_DEFAULT_INCLUDE = ["**/*.{test,spec}.?(c|m)[jt]s?(x)"]
JEST_DEFAULT_MATCH = ["**/__tests__/**/*.[jt]s?(x)", "**/?(*.)+(spec|test).[jt]s?(x)"]
# Directories some vitest versions exclude by default and 5.0.3 does not; a path
# under one is never reported as collected on the strength of a default.
VITEST_EXCLUDE_SEGMENTS = ("node_modules", "dist", "cypress")
PYTEST_DEFAULT_FILES = ("test_*.py", "*_test.py")
PYTEST_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
PYTEST_OVERRIDE_KEYS = ("python_files", "testpaths", "norecursedirs")


def _answer(answer, via, basis):
    return {"answer": answer, "via": via, "basis": basis}


def _cannot(basis):
    return _answer(COULD_NOT_TELL, None, basis)


# --- glob ---------------------------------------------------------------------
# picomatch's forms, translated to a regex over a `/`-separated relative path.
# Every `_glob_*` helper returns None for a form it does not translate, and that
# None travels up unchanged: a pattern that is not understood must not be read as
# one that did not match.

class _Unsupported(Exception):
    pass


def _glob_regex(pattern):
    body, rest = _glob_seq(pattern, 0, False)
    if rest != len(pattern):
        raise _Unsupported("unbalanced")
    return re.compile("^" + body + "$")


def _glob_seq(p, i, in_group):
    """Translate `p` from `i` to the end, or to the `|` / `)` closing an extglob
    group when `in_group`; returns (regex, index it stopped at)."""
    out = []
    n = len(p)
    while i < n:
        c = p[i]
        if in_group and c in "|)":
            return "".join(out), i
        if c == "\\":
            raise _Unsupported("escape")
        if c == "*" and p.startswith("**", i):
            at_start = i == 0 or p[i - 1] == "/"
            if at_start and p.startswith("**/", i):
                out.append("(?:[^/]+/)*")
                i += 3
            elif at_start and i + 2 == n:
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 2
            continue
        if c in "?*+@!" and i + 1 < n and p[i + 1] == "(":
            if c == "!":
                raise _Unsupported("negated group")
            alts = []
            i += 2
            while True:
                alt, i = _glob_seq(p, i, True)
                alts.append(alt)
                if i >= n:
                    raise _Unsupported("unclosed group")
                closing = p[i]
                i += 1
                if closing == ")":
                    break
            suffix = {"?": "?", "*": "*", "+": "+", "@": ""}[c]
            out.append("(?:%s)%s" % ("|".join(alts), suffix))
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = p.find("]", i + 2)
            if end < 0:
                raise _Unsupported("unclosed class")
            cls = p[i + 1:end]
            if cls.startswith("!"):
                cls = "^" + cls[1:]
            out.append("[" + cls.replace("\\", "\\\\") + "]")
            i = end
        elif c == "{":
            depth, j, parts, start = 0, i, [], i + 1
            while j < n:
                if p[j] == "{":
                    depth += 1
                elif p[j] == "}":
                    depth -= 1
                    if depth == 0:
                        parts.append(p[start:j])
                        break
                elif p[j] == "," and depth == 1:
                    parts.append(p[start:j])
                    start = j + 1
                j += 1
            else:
                raise _Unsupported("unclosed brace")
            if len(parts) < 2 or any(".." in x and re.match(r"^-?\d+\.\.-?\d+", x)
                                     for x in parts):
                raise _Unsupported("brace form")
            out.append("(?:%s)" % "|".join(_glob_seq(x, 0, False)[0] for x in parts))
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    if in_group:
        raise _Unsupported("unclosed group")
    return "".join(out), i


def match_glob(pattern, path):
    """True / False when `pattern` matches the relative `path`; None when the
    pattern or the path has a form this module does not translate."""
    if pattern.startswith("./"):
        pattern = pattern[2:]
    if (not pattern or pattern.startswith(("!", "/", "../")) or ".." in pattern.split("/")
            or any(seg.startswith(".") and seg not in ("",) for seg in path.split("/"))):
        return None
    try:
        return _glob_regex(pattern).match(path) is not None
    except (_Unsupported, re.error):
        return None


# --- config text --------------------------------------------------------------
# A tokenizer, not a parser: enough to find a key by bracket depth and to say that
# its value is a list of plain strings, without running or importing the file.

_REGEX_PREV = (None, ":", ",", "(", "[", "=", "{", "!", "&", "|", "?", ";")


def _skip_quoted(text, i, quote):
    """Index just past the string opened at `i`; -1 when it never closes."""
    n = len(text)
    i += 1
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return -1


def _tokens(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        prev = toks[-1][1] if toks and toks[-1][0] == "p" else (None if not toks else "x")
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "'\"`":
            end = _skip_quoted(text, i, c)
            if end < 0:
                return None
            raw = text[i + 1:end - 1]
            toks.append(("tpl", None) if c == "`" and "${" in raw else ("str", raw))
            i = end
        elif c == "/" and prev in _REGEX_PREV:
            j, in_class = i + 1, False
            while j < n and (text[j] != "/" or in_class) and text[j] != "\n":
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                j += 1
            toks.append(("re", None))
            i = j + 1
        elif c.isalpha() or c in "_$":
            m = re.compile(r"[A-Za-z_$][\w$]*").match(text, i)
            toks.append(("id", m.group(0)))
            i = m.end()
        elif c.isdigit():
            m = re.compile(r"[\w.]+").match(text, i)
            toks.append(("num", m.group(0)))
            i = m.end()
        elif text.startswith("...", i):
            toks.append(("p", "..."))
            i += 3
        else:
            toks.append(("p", c))
            i += 1
    return toks


def _is_key(tok):
    return tok[0] in ("id", "str")


def _direct_pairs(toks, open_idx):
    """For the `{` at `open_idx`: ({key: index of its value's first token},
    spread seen, a key repeated). Only the object's own level is read."""
    pairs, spread, dup, depth, j = {}, False, False, 0, open_idx
    while j < len(toks):
        kind, val = toks[j]
        if kind == "p" and val in "{[(":
            depth += 1
        elif kind == "p" and val in "}])":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1 and toks[j - 1][1] in ("{", ","):
            if kind == "p" and val == "...":
                spread = True
            elif _is_key(toks[j]) and j + 1 < len(toks) and toks[j + 1] == ("p", ":"):
                dup = dup or val in pairs
                pairs[val] = j + 2
            elif _is_key(toks[j]):
                pairs[val] = -1                      # shorthand / method: not literal
        j += 1
    return pairs, spread, dup


def _string_array(toks, start):
    """The strings of the array literal at `start`, or None when the value is
    anything but `[ 'a', "b", ... ]` - a name, a spread, a call, a template."""
    if start < 0 or start >= len(toks) or toks[start] != ("p", "["):
        return None
    out, j = [], start + 1
    while j < len(toks):
        if toks[j] == ("p", "]"):
            return out
        if toks[j][0] != "str":
            return None
        out.append(toks[j][1])
        j += 1
        if toks[j:j + 1] == [("p", ",")]:
            j += 1
        elif toks[j:j + 1] != [("p", "]")]:
            return None
    return None


def _read_text(project, names):
    """(name, text) of the first of `names` present under `project`; ('', None)
    when none is; (name, False) when one is present and cannot be read."""
    for name in names:
        full = os.path.join(project, name)
        if os.path.isfile(full):
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    return name, fh.read()
            except OSError:
                return name, False
    return "", None


def _names_in(toks):
    return set(v for k, v in toks if k in ("id", "str") and v)


# --- deciding from patterns -----------------------------------------------------

def _decide(path, patterns, source, may_exclude):
    """Read `patterns` (globs from `source`) against `path`. `may_exclude` is a
    reason an exclusion could remove a match, or empty."""
    verdicts = [match_glob(p, path) for p in patterns]
    where = "%s %s" % (source, ", ".join(patterns))
    if any(v is True for v in verdicts):
        if may_exclude:
            return _cannot("%s admits %s, but %s" % (where, path, may_exclude))
        return _answer(COLLECTED, "config", "%s admits %s" % (where, path))
    if any(v is None for v in verdicts):
        return _cannot("%s: a pattern in it is a glob form this reading does not "
                       "translate" % where)
    return _answer(NOT_COLLECTED, "config", "%s admits no pattern for %s" % (where, path))


def _excluded_segment(path):
    return next((s for s in path.split("/")[:-1] if s in VITEST_EXCLUDE_SEGMENTS), "")


# --- vitest ---------------------------------------------------------------------

def _vitest_config(path, project):
    name, text = _read_text(project, VITEST_CONFIGS)
    if not name:
        name, text = _read_text(project, VITE_CONFIGS)
    if text is False:
        return _cannot("%s could not be read" % name)
    toks = _tokens(text) if text is not None else []
    if toks is None:
        return _cannot("%s has an unterminated string" % name)
    names = _names_in(toks)
    for word in ("mergeConfig", "projects", "workspace"):
        if word in names:
            return _cannot("%s uses %s, which can bring an include of its own" % (name, word))
    blocks = [j for j in range(len(toks) - 2)
              if _is_key(toks[j]) and toks[j][1] == "test" and toks[j + 1] == ("p", ":")]
    if len(blocks) > 1:
        return _cannot("%s names `test` more than once" % name)
    pairs = {}
    if blocks:
        if toks[blocks[0] + 2] != ("p", "{"):
            return _cannot("%s: `test` is not an object literal" % name)
        pairs, spread, dup = _direct_pairs(toks, blocks[0] + 2)
        if spread or dup:
            return _cannot("%s: the test object has a spread or a repeated key" % name)
        for key in ("root", "dir"):
            if key in pairs:
                return _cannot("%s sets test.%s, which moves what a path is relative to" % (name, key))
    reason = "exclude" in pairs and "%s sets test.exclude" % name or ""
    if "include" in pairs:
        patterns = _string_array(toks, pairs["include"])
        if not patterns:
            return _cannot("%s: test.include is not a non-empty array of string literals" % name)
        return _decide(path, patterns, "%s test.include" % name, reason)
    seg = _excluded_segment(path)
    if seg:
        return _cannot("%s is under %s/, which some vitest versions exclude by default" % (path, seg))
    return _decide(path, VITEST_DEFAULT_INCLUDE,
                   "vitest's default include (%s sets none)" % (name or "no config file"), reason)


def _local_binary(project, candidates):
    return next((os.path.join(project, *c.split("/")) for c in candidates
                 if os.path.isfile(os.path.join(project, *c.split("/")))), "")


def _run_lister(exe, args, project):
    """Stdout lines of `exe args` run in `project`; None when it fails or times out."""
    try:
        proc = subprocess.run([exe] + args, cwd=project, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=LIST_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [l.strip().replace("\\", "/") for l in proc.stdout.decode("utf-8", "replace").splitlines()]


def _relative_files(lines, project):
    """The existing files among `lines`, as `/`-separated paths relative to
    `project` (a runner may print them absolute); None when there are none."""
    root = os.path.realpath(project).replace("\\", "/").rstrip("/") + "/"
    files = []
    for l in lines:
        if not l:
            continue
        if os.path.isabs(l) or (len(l) > 1 and l[1] == ":"):
            real = os.path.realpath(l).replace("\\", "/")
            if not real.startswith(root):
                continue
            l = real[len(root):]
        if os.path.isfile(os.path.join(project, *l.split("/"))):
            files.append(l)
    return files or None


def vitest_list(runner, project):
    """The files `vitest list --filesOnly` prints, as `/`-separated paths relative
    to `project`; None when there is no local binary, it fails, times out, or
    prints no file. Never downloads: only `node_modules/.bin` is looked at."""
    exe = _local_binary(project, ("node_modules/.bin/vitest", "node_modules/.bin/vitest.cmd"))
    lines = _run_lister(exe, ["list", "--filesOnly"], project) if exe else None
    return _relative_files(lines, project) if lines else None


def jest_list(runner, project):
    """The files `jest --listTests` prints (absolute paths), relative to `project`;
    None when there is no local binary or it prints no file."""
    exe = _local_binary(project, ("node_modules/.bin/jest", "node_modules/.bin/jest.cmd"))
    lines = _run_lister(exe, ["--listTests"], project) if exe else None
    return _relative_files(lines, project) if lines else None


def pytest_list(runner, project):
    """The files holding a test that `pytest --collect-only -q` names (each line is
    `file::test`), relative to `project`; None when no virtualenv pytest is under
    the project or it names none. A file with no test is absent from the output,
    so this list can only ever prove a file collected."""
    exe = _local_binary(project, PYTEST_BINARIES)
    lines = _run_lister(exe, ["--collect-only", "-q"], project) if exe else None
    heads = sorted(set(l.split("::")[0] for l in lines or [] if "::" in l))
    return _relative_files(heads, project) if heads else None


LISTERS = {"vitest": vitest_list, "jest": jest_list, "pytest": pytest_list}


def _same_suffix_siblings(path, project):
    """Files beside a not-yet-existing `path` that end the way its name ends
    (`.test.ts` of `store.test.ts`)."""
    head, _, base = path.rpartition("/")
    suffix = base[base.find("."):] if "." in base else ""
    folder = os.path.join(project, *head.split("/")) if head else project
    if not suffix or not os.path.isdir(folder):
        return []
    return sorted((head + "/" if head else "") + f for f in os.listdir(folder)
                  if f.endswith(suffix) and os.path.isfile(os.path.join(folder, f)))


def _from_listing(path, listed, project, runner="vitest"):
    """The answer a listing gives, or None when it gives none. pytest's listing
    is only ever evidence of collection, never of its absence."""
    tool = {"vitest": "vitest list", "jest": "jest --listTests",
            "pytest": "pytest --collect-only"}[runner]
    can_refute = runner != "pytest"
    if path in listed:
        return _answer(COLLECTED, "list", "`%s` prints %s" % (tool, path))
    if not can_refute:
        return None
    if os.path.isfile(os.path.join(project, *path.split("/"))):
        return _answer(NOT_COLLECTED, "list",
                       "`%s` printed %d file(s) and %s is not one of them"
                       % (tool, len(listed), path))
    siblings = _same_suffix_siblings(path, project)
    if not siblings:
        return None
    if any(s in listed for s in siblings):
        return _answer(COLLECTED, "list", "%s does not exist yet; `%s` prints its "
                       "neighbour %s with the same suffix" % (path, tool, siblings[0]))
    return _answer(NOT_COLLECTED, "list", "%s does not exist yet; `%s` omits all %d "
                   "neighbour(s) with its suffix" % (path, tool, len(siblings)))


# --- jest -----------------------------------------------------------------------

def _jest_config(path, project):
    name, text = _read_text(project, JEST_CONFIGS)
    toks = None
    if name == "":
        name, pkg = _read_text(project, ("package.json",))
        if pkg is False:
            return _cannot("package.json could not be read")
        toks = _tokens(pkg) if pkg else []
        start = next((j for j in range(len(toks) - 2) if toks[j] == ("str", "jest")
                      and toks[j + 1] == ("p", ":")), None) if toks else None
        if start is None:
            toks, name = [], "no jest config"
        else:
            name, toks = "package.json jest", toks[start + 2:]
    elif text is False:
        return _cannot("%s could not be read" % name)
    else:
        toks = _tokens(text)
    if toks is None:
        return _cannot("%s has an unterminated string" % name)
    names = _names_in(toks)
    if any(t == ("p", "...") for t in toks):
        return _cannot("%s has a spread" % name)
    for word in ("projects", "testRegex", "preset"):
        if word in names:
            return _cannot("%s sets %s, which this reading does not follow" % (name, word))
    found = {}
    for key in ("testMatch", "roots"):
        at = [j for j in range(len(toks) - 1) if _is_key(toks[j]) and toks[j][1] == key
              and toks[j + 1] == ("p", ":")]
        if len(at) > 1:
            return _cannot("%s names %s more than once" % (name, key))
        if at:
            found[key] = _string_array(toks, at[0] + 2)
            if not found[key]:
                return _cannot("%s: %s is not a non-empty array of string literals" % (name, key))
    roots = found.get("roots", ["<rootDir>"])
    inside = [_under_root(path, r) for r in roots]
    if not any(v is True for v in inside):
        if any(v is None for v in inside):
            return _cannot("%s: a root is not a <rootDir> path" % name)
        return _answer(NOT_COLLECTED, "config", "%s roots %s do not contain %s"
                       % (name, ", ".join(roots), path))
    patterns = []
    for pat in found.get("testMatch", JEST_DEFAULT_MATCH):
        if pat.startswith("<rootDir>/"):
            patterns.append(pat[len("<rootDir>/"):])
        elif pat.startswith("**/"):
            patterns.append(pat)
        else:
            return _cannot("%s: testMatch %r starts with neither **/ nor <rootDir>/, so "
                           "what it matches against is not known here" % (name, pat))
    if "testMatch" not in found and path.endswith(JEST_VERSIONED_EXTENSIONS):
        return _cannot("%s is judged by jest's default testMatch, whose extension set "
                       "differs between jest versions for %s"
                       % (path, path[path.rfind("."):]))
    source = "%s testMatch" % name if "testMatch" in found else "jest's default testMatch"
    return _decide(path, patterns, source, "")


def _under_root(path, root):
    """True / False for a `<rootDir>` / `<rootDir>/sub` root; None for any other form."""
    if root == "<rootDir>":
        return True
    if not root.startswith("<rootDir>/"):
        return None
    sub = root[len("<rootDir>/"):].strip("/")
    return path == sub or path.startswith(sub + "/")


# --- pytest ---------------------------------------------------------------------

def _pytest_config(path, project):
    for name in PYTEST_CONFIG_FILES:
        full = os.path.join(project, name)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return _cannot("%s could not be read" % name)
        key = next((k for k in PYTEST_OVERRIDE_KEYS if re.search(r"(?m)^\s*%s\s*[=:]" % k, text)), "")
        if key:
            return _cannot("%s sets %s, which this reading does not follow" % (name, key))
    base = path.rpartition("/")[2]
    fits = any(re.match("^" + re.escape(p).replace(r"\*", ".*") + "$", base) for p in PYTEST_DEFAULT_FILES)
    return _answer(COLLECTED if fits else NOT_COLLECTED, "default",
                   "pytest's default python_files (%s) %s %s; a run with no file "
                   "argument is assumed" % (", ".join(PYTEST_DEFAULT_FILES),
                                            "match" if fits else "do not match", base))


# --- the question -----------------------------------------------------------------

def collects(path, runner, project, lister=None):
    """Does `runner` collect `path` (relative to `project`)?

    Returns {"answer": COLLECTED | NOT_COLLECTED | COULD_NOT_TELL,
             "via": "list" | "config" | "default" | None,
             "basis": the sentence that makes the answer true}.
    Only NOT_COLLECTED is a definite answer. `lister(runner, project)` is the
    runner's own file listing (a list of relative paths, or None) and defaults to
    the real lister of that runner (`LISTERS`); it is asked only for a runner
    this module knows.
    """
    name = runner.strip() if isinstance(runner, str) else ""
    if name not in ("vitest", "jest", "pytest"):
        return _cannot("runner %r is not one this reading knows (vitest, jest, pytest)"
                       % (runner,))
    path = path.replace("\\", "/")
    listed = (lister or LISTERS[name])(name, project)
    if listed:
        answer = _from_listing(path, listed, project, name)
        if answer is not None:
            return answer
    return {"vitest": _vitest_config, "jest": _jest_config, "pytest": _pytest_config}[name](path, project)


if __name__ == "__main__":
    from _output import safe_stdio, selftest_requested  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if selftest_requested(sys.argv[1:]):
        # Answers rather than falling through: it deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_runner_collects.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__runner_collects.py - run that file "
              "instead.")
        sys.exit(0)
    print(__doc__.strip())
