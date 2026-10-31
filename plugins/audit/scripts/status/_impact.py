#!/usr/bin/env python3
"""
Who, among a repository's tracked files, reads a file a task is about to change.

WHY THIS IS A MODULE. A task's brief names the task and its files and not the
parts of the system that read those files - a shell heredoc importing a module,
a CI step naming a script's path, a document whose fenced command runs it. A
change that did not account for one of them is the defect a task gate cannot
see, because the reader is not among the task's files. `audit-lookup.py` lists
what this module finds in the executor's brief, the writer's prompt and the
reviewer's brief, so the writer is asked about each reader and the reviewer can
check the answer.

WHAT COUNTS AS A REFERENCE. A tracked file references a declared file when one
of its lines carries, as a whole word, the declared file's module name inside a
Python `import`/`from` statement (`import`, `.py` files only), its path
(`path`), or its basename (`basename`); a JS/TS file (`JS_EXTS`) is also
imported by a relative specifier written without its extension, or with the
`.js` an ESM build resolves, or by its directory when it is an index file - each
resolved against the importing file's own directory (`import`). A dependant is
reported under the strongest kind among its lines, in that order, and prose
files come last within a kind, so a cap keeps the callers. A Python file's top-level
`def`/`class` names are searched as whole words too, and a name is reported with
the tracked files that name it - for a name with a leading underscore, only the
files that also reference the module and are not prose (`DOC_EXTS`), since a
private name said elsewhere is nearly always that file's own, and a document
naming the module's internals describes them rather than calls them. The declared file itself is never its own
dependant, and `exclude` drops whole directories (the plan's own state names
every file it indexes and reads none of them).

WHICH READERS A DISPATCH DEMANDS. `owed` narrows the dependants to the ones an
edit to the declared file can reach - its own suite, a file quoting its text
beside its path, a document section headed by its path - and `audit-task.py
start` refuses a task until each is declared or waived. The comment above
`owed` says why the rest of the listing is not demanded.

WHAT IT CANNOT SEE. Only `git grep` over TRACKED files is read, so an untracked
or gitignored file is never a dependant - by design, since neither ships. A
reference spelled in pieces (`os.path.join("status", name)`), an aliased or
computed JS/TS import (`@/util`, `import(name)`), or a name reached by `getattr`
is not on any line in a form this reads, and is not found; a file nothing names
says what it was searched by, so an empty answer is never wider than the search.
A defined name
that is a common word (`main`) is found in every file that says it; the
rendering lists the names named by the FEWEST files first, so the specific ones
lead, and prints how many were not shown.

THE COST IS BOUNDED. At most two `git grep` calls per declared file - one for
the references and a second for a `.py` file's names or a JS/TS file's import
stems - each with a timeout, whatever the size of the tree, plus one retry per
scan when git was built without PCRE and refused the fast form of the names
call. A brief's `section` scans at most `FILE_BUDGET` declared files, in
`scan_order` (those the description names, then source, then documents), and
renders at most `LINE_BUDGET` lines, closing with how many of the declared files
it showed and the command that lists the rest. A call that fails is reported as
an error on that file, never as an empty list.

This module carries no `--selftest` of its own; its cases live in
`tests/test__impact.py`.

Stdlib only, Python 3.8 compatible.
"""
import ast
import os
import posixpath
import re
import subprocess
import sys
import warnings

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

# --- the scan -------------------------------------------------------------------
# How many dependants a declared file keeps in its result; the total is kept
# beside it, so a longer list is a counted cut and never a silent one.
CAP = 8
# How many defined names, and how many files per name, the rendering prints.
NAME_CAP = 4
NAME_FILE_CAP = 3
GIT_TIMEOUT = 20
# The strongest kind first: an import is a caller, a path is usually a command
# that runs the file, a bare basename is most often a document mentioning it.
KINDS = ("import", "path", "basename")
# Extensions whose importers usually write the specifier WITHOUT the extension.
JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")
# Prose, read last in a scan and listed last among dependants of one kind.
DOC_EXTS = (".md", ".markdown", ".rst", ".txt", ".adoc")
# A relative JS/TS module specifier in an import, a re-export or a require.
_JS_SPEC = re.compile(r"""(?:\bfrom|\bimport|\brequire)\s*\(?\s*(['"`])(\.\.?/[^'"`\s]*)\1""")
_PRIVATE_NAME = re.compile(r"^__\w+__$")


def run_git(argv, cwd):
    """`(exit, stdout, stderr)` of one git call; `exit` is None when git could
    not be started or did not finish, with the reason in `stderr`."""
    try:
        done = subprocess.run(["git", "-c", "core.quotePath=false"] + list(argv),
                              cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "", "git %s did not finish within %ss" % (argv[0], GIT_TIMEOUT)
    except OSError as exc:
        return None, "", "git could not be started: %s" % (exc,)
    return (done.returncode, done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"))


def _norm(path):
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return posixpath.normpath(path) if path else path


def _module_name(path):
    """The name a Python `import` would use for `path`, or None: a hyphenated
    entry point is loaded by its basename and has no import name."""
    stem, ext = posixpath.splitext(posixpath.basename(path))
    if ext != ".py":
        return None
    if stem == "__init__":
        stem = posixpath.basename(posixpath.dirname(path))
    if not stem.isidentifier() or stem == "__main__":
        return None
    return stem


def _import_pattern(module):
    word = re.escape(module)
    return re.compile(
        r"\bfrom\s+(?:\w+\.)*%s\b"
        r"|\bimport\s+(?:[\w.]+(?:\s+as\s+\w+)?\s*,\s*)*(?:\w+\.)*%s\b"
        r"|\bfrom\s+[\w.]+\s+import\s+\(?[\w\s,]*\b%s\b" % (word, word, word))


def _line_kind(text, path, basename, importer):
    """The strongest kind of reference one line makes, or None."""
    if importer is not None and importer.search(text):
        return "import"
    if path != basename and re.search(r"(?<![\w.-])%s(?![\w-])"
                                      % re.escape(path), text):
        return "path"
    if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(basename), text):
        return "basename"
    return None


def _pathspec(exclude):
    return ["--", "."] + [":(exclude)%s" % _norm(e) for e in exclude]


def _grep_lines(out):
    """`[(file, text)]` from `git grep -z` output, one pair per matching line."""
    pairs = []
    for row in out.split("\n"):
        name, sep, text = row.partition("\0")
        if sep:
            pairs.append((name, text))
    return pairs


def _grep_error(code, err):
    """The error a `git grep` exit means, or None: 1 is git's 'nothing matched'."""
    if code in (0, 1):
        return None
    first = (err.strip().splitlines() or ["exit %s" % (code,)])[0]
    return first


def is_js(path):
    return posixpath.splitext(path)[1] in JS_EXTS


def is_doc(path):
    return posixpath.splitext(path)[1].lower() in DOC_EXTS


def _js_targets(path):
    """What a relative specifier resolves to when it means `path`: the path
    without its extension, and for an index file its directory too."""
    stem = posixpath.splitext(path)[0]
    targets = {stem}
    if posixpath.basename(stem) == "index" and posixpath.dirname(stem):
        targets.add(posixpath.dirname(stem))
    return targets


def _js_resolves(importer, spec, targets):
    """Whether `spec`, written in `importer`, names one of `targets` - with a
    `.js`-family extension or a trailing `/index` taken off, since an ESM build
    of a `.ts` file is imported as `./x.js`."""
    target = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
    if posixpath.splitext(target)[1] in JS_EXTS:
        target = posixpath.splitext(target)[0]
    if target in targets:
        return True
    return target.endswith("/index") and target[:-len("/index")] in targets


def _js_importers(root, path, exclude, git):
    """`(files, error)` - the tracked files whose relative import, re-export or
    require resolves to `path`. One `git grep` for `/<stem>` (and `/<dir>` for
    an index file), every specifier on a matching line then resolved against
    the importing file's own directory, so a `./api` beside another `api.ts`
    is not this file's importer. An aliased specifier (`@/x`) is not relative
    and is not resolved."""
    targets = _js_targets(path)
    argv = ["grep", "-z", "-I", "-F"]
    for word in sorted(set("/" + posixpath.basename(t) for t in targets)):
        argv += ["-e", word]
    code, out, err = git(argv + _pathspec(exclude), root)
    error = _grep_error(code, err)
    if error is not None:
        return None, error
    found = set()
    for name, text in _grep_lines(out):
        if _norm(name) != path and any(
                _js_resolves(_norm(name), m.group(2), targets)
                for m in _JS_SPEC.finditer(text)):
            found.add(name)
    return found, None


def _ranked(best):
    """Dependants strongest kind first, prose last within a kind, then by name -
    so a cap keeps the callers and drops the mentions."""
    return sorted(({"file": f, "via": k} for f, k in best.items()),
                  key=lambda r: (KINDS.index(r["via"]), is_doc(r["file"]),
                                 r["file"]))


def _references(root, path, exclude, git):
    basename = posixpath.basename(path)
    module = _module_name(path)
    terms = sorted(set(t for t in (path, basename, module) if t))
    argv = ["grep", "-z", "-I", "-w", "-F"]
    for term in terms:
        argv += ["-e", term]
    code, out, err = git(argv + _pathspec(exclude), root)
    error = _grep_error(code, err)
    if error is not None:
        return None, error
    importer = _import_pattern(module) if module else None
    best = {}
    for name, text in _grep_lines(out):
        if _norm(name) == path:
            continue
        kind = _line_kind(text, path, basename, importer)
        if kind is None:
            continue
        held = best.get(name)
        if held is None or KINDS.index(kind) < KINDS.index(held):
            best[name] = kind
    if is_js(path):
        importers, error = _js_importers(root, path, exclude, git)
        if error is not None:
            return None, error
        best.update((name, "import") for name in importers)
    return _ranked(best), None


def defined_names(source):
    """The top-level `def`/`class` names of a Python source, in order; raises
    `SyntaxError` for a source that does not parse."""
    tree = ast.parse(source)
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return [n.name for n in tree.body
            if isinstance(n, kinds) and not _PRIVATE_NAME.match(n.name)]


def _read_names(root, path):
    """`(names, error)` - the file's defined names, or why they were not read.
    A declared file that does not exist yet defines nothing, which is no error."""
    full = os.path.join(root, *path.split("/"))
    if not os.path.isfile(full):
        return [], None
    try:
        with open(full, "r", encoding="utf-8") as fh:
            return defined_names(fh.read()), None
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
        return [], "%s: %s" % (type(exc).__name__, exc)


_NO_PCRE = re.compile(r"perl|pcre", re.IGNORECASE)


def _names_argv(names, pcre):
    """One `git grep -o` over every name. A PCRE alternation is the fast form -
    over this repository's largest modules it took a twentieth of the time
    `-F -w` with one pattern per name did (measured once, 2026-10-21) - and a
    git built without PCRE refuses it, which `_name_users` answers by asking
    again in the fixed-string form."""
    if pcre:
        return ["grep", "-z", "-o", "-I", "-P", "-e",
                r"\b(?:%s)\b" % "|".join(re.escape(n) for n in names)]
    argv = ["grep", "-z", "-o", "-I", "-w", "-F"]
    for name in names:
        argv += ["-e", name]
    return argv


def _name_users(root, path, names, referrers, exclude, cap, git, pcre):
    """`(symbols, error, pcre)` - per defined name, the tracked files naming it.
    A name with a leading underscore is private by Python's convention, so a
    file naming one counts only when it is in `referrers` - the code files that
    reference the module; any other file saying `_write` has a `_write` of its
    own, and a document beside the module describes the name rather than calls
    it. `pcre` comes back False once
    git has refused the PCRE form, so the caller stops offering it."""
    if not names:
        return [], None, pcre
    code, out, err = git(_names_argv(names, pcre) + _pathspec(exclude), root)
    if pcre and code not in (0, 1) and _NO_PCRE.search(err):
        pcre = False
        code, out, err = git(_names_argv(names, pcre) + _pathspec(exclude), root)
    error = _grep_error(code, err)
    if error is not None:
        return [], error, pcre
    wanted = set(names)
    users = {}
    for name, word in _grep_lines(out):
        if _norm(name) == path or word not in wanted:
            continue
        if word.startswith("_") and name not in referrers:
            continue
        users.setdefault(word, set()).add(name)
    found = [{"name": n, "files": sorted(users[n])[:cap], "total": len(users[n])}
             for n in names if n in users]
    return sorted(found, key=lambda s: (s["total"], s["name"])), None, pcre


def _file_dependants(root, path, cap, exclude, git, pcre):
    path = _norm(path)
    result = {"path": path, "files": [], "total": 0, "symbols": [],
              "defined": 0, "error": None, "namesError": None}
    refs, error = _references(root, path, exclude, git)
    if error is not None:
        result["error"] = error
        return result, pcre
    result["files"], result["total"] = refs[:cap], len(refs)
    if path.endswith(".py"):
        names, names_error = _read_names(root, path)
        result["defined"] = len(names)
        referrers = set(r["file"] for r in refs if not is_doc(r["file"]))
        symbols, grep_error, pcre = _name_users(root, path, names, referrers,
                                                exclude, cap, git, pcre)
        result["symbols"] = symbols
        result["namesError"] = names_error or grep_error
    return result, pcre


def file_dependants(root, path, cap=CAP, exclude=(), git=None):
    """One declared file's dependants:
    `{"path", "files": [{"file", "via"}] (at most cap), "total", "symbols":
    [{"name", "files", "total"}], "defined", "error", "namesError"}`.
    `error` is set when the references could not be read, and `files` is then
    empty - an answer `total == 0` never stands in for."""
    return _file_dependants(root, path, cap, exclude,
                            git if git is not None else run_git, True)[0]


def dependants(root, paths, cap=CAP, exclude=(), git=None):
    """`file_dependants` for each declared path, in the order given; a git that
    refused the PCRE form once is not offered it again for the rest."""
    run = git if git is not None else run_git
    results, pcre = [], True
    for path in paths:
        result, pcre = _file_dependants(root, path, cap, exclude, run, pcre)
        results.append(result)
    return results


# --- the readers an edit can reach ------------------------------------------------
# `dependants` answers "who names this file"; a task's dispatch asks a narrower
# question - which of those readers an EDIT to the file can break - because it
# refuses to start until each is declared or waived, and a refusal that demanded
# every name would be routed around inside a day. The kinds demanded
# (`OWED_KINDS`) each read the file's content rather than its name:
#
#   suite    - the file's own test suite by name (`test_<stem>`, `<stem>_test`,
#              `<stem>.test`, `<stem>.spec`, `<stem>_spec`), among its dependants:
#              it asserts on the behaviour the edit changes;
#   text     - a code file quoting, within ANCHOR_WINDOW lines of the file's
#              full path, a passage of the file's own text: a literal of at least
#              ANCHOR_MIN characters holding whitespace and naming no path, found
#              verbatim in the file - the shape of a mutation row or a source pin;
#   section  - a document with a Markdown heading naming the file's full path:
#              prose that describes this file specifically.
#
# NOT DEMANDED, because an edit that keeps the path cannot break them by being
# made: a file that only runs or names the path, an importer that is not the
# suite, a passing basename mention, and a quoted identifier (no whitespace) or
# path beside the path. A delete or a rename breaks every one of those - and no
# field a dispatch reads says a task deletes or renames, so those readers stay in
# the brief's listing, answered by the executor, and are not refused over. A
# declared file that does not exist yet is a creation, and nothing reads it.
ANCHOR_WINDOW = 4
ANCHOR_MIN = 12
_QUOTED = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'')
_PATHISH = re.compile(r"[\w.-]+/[\w.-]|\w\.(?:py|md|json|ya?ml|sh|mjs|cjs|js|"
                      r"ts|tsx|jsx|txt|toml|cfg|ini|html|css)\b")
OWED_KINDS = ("suite", "text", "section")


def suite_stems(path):
    """The names, extension off, a test suite of `path` goes by."""
    stem = posixpath.splitext(posixpath.basename(path))[0]
    snake = stem.replace("-", "_")
    return set(["test_%s" % snake, "%s_test" % snake, "%s.test" % stem,
                "%s.spec" % stem, "%s_spec" % snake])


def _literals(line):
    """The string values quoted on one line; a token Python cannot read as a
    literal (a JS template, an unbalanced escape) is taken between its quotes."""
    found = []
    for match in _QUOTED.finditer(line):
        token = match.group(0)
        # A regex in a reader (`"\d+"`) is an invalid escape to the parser, which
        # newer Pythons report as a SyntaxWarning on stderr - output about the
        # reader's source, not this scan, so it is not let through.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                value = ast.literal_eval(token)
        except (ValueError, SyntaxError):
            value = token[1:-1]
        if isinstance(value, str):
            found.append(value)
    return found


def _is_passage(value, path):
    """Whether a quoted value is a passage of text rather than a name: long
    enough, holding whitespace, and naming no path - this file's or another's."""
    text = value.strip()
    return (len(text) >= ANCHOR_MIN and re.search(r"\s", text) is not None
            and path not in value
            and posixpath.basename(path) not in value
            and _PATHISH.search(text) is None)


def pinned_passage(reader_text, path, file_text):
    """The first passage of `file_text` that `reader_text` quotes within
    ANCHOR_WINDOW lines of a line naming `path`, or None."""
    if path not in reader_text:
        return None
    lines = reader_text.split("\n")
    for i, line in enumerate(lines):
        if path not in line:
            continue
        for near in lines[max(0, i - ANCHOR_WINDOW):i + ANCHOR_WINDOW + 1]:
            for value in _literals(near):
                if _is_passage(value, path) and value in file_text:
                    return value
    return None


def heads_section(doc_text, path):
    """Whether a document has a Markdown heading naming `path` in full."""
    if path not in doc_text:
        return False
    word = re.compile(r"(?<![\w./-])%s(?![\w-]|\.\w)" % re.escape(path))
    return any(line.lstrip().startswith("#") and word.search(line)
               for line in doc_text.split("\n"))


def _read_text(root, path):
    """A tracked file's text off the working tree, or "" when it cannot be read."""
    try:
        with open(os.path.join(root, *path.split("/")), "r", encoding="utf-8",
                  errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _owed_reason(root, path, reader, file_text, read):
    """`(kind, basis)` when `reader` is a reader an edit to `path` can reach,
    else None."""
    stem = posixpath.splitext(posixpath.basename(reader))[0]
    if stem in suite_stems(path):
        return "suite", "its own suite"
    text = read(root, reader)
    if is_doc(reader):
        if heads_section(text, path):
            return "section", "a section headed by its path"
        return None
    passage = pinned_passage(text, path, file_text)
    if passage is not None:
        shown = passage.strip()
        shown = shown if len(shown) <= 60 else shown[:57] + "..."
        return "text", "quotes its text beside its path: %r" % (shown,)
    return None


def owed(root, paths, exclude=(), git=None, read=None):
    """The readers an edit to the declared `paths` can reach:
    `{"owed": [{"file", "reads", "kind", "basis"}], "errors": [{"path",
    "error"}]}`, one row per reader (the first declared path it reads), in the
    order `dependants` ranks them. A path not on disk is a creation and is
    skipped; a path whose references could not be read is an error, never an
    empty answer."""
    run = git if git is not None else run_git
    read = read if read is not None else _read_text
    rows, errors, seen = [], [], set()
    for raw in paths:
        path = _norm(raw)
        if not os.path.isfile(os.path.join(root, *path.split("/"))):
            continue
        refs, error = _references(root, path, exclude, run)
        if error is not None:
            errors.append({"path": path, "error": error})
            continue
        file_text = read(root, path)
        for ref in refs:
            reader = ref["file"]
            if reader in seen:
                continue
            reason = _owed_reason(root, path, reader, file_text, read)
            if reason is not None:
                seen.add(reader)
                rows.append({"file": reader, "reads": path, "kind": reason[0],
                             "basis": reason[1]})
    return {"owed": rows, "errors": errors}


# --- the rendering --------------------------------------------------------------
# What one section of a brief may hold: the declared files it scans and the lines
# it renders. Every brief carries the section, and a task can declare hundreds of
# files, so a cut is counted and the command listing the rest is printed with it.
FILE_BUDGET = 12
LINE_BUDGET = 24
_UNSEEN = "aliased or dynamic imports are not seen"


def _searched(path):
    """How `path` was searched, as the words after `names it`."""
    if path.endswith(".py"):
        return "by path, basename or module import"
    if is_js(path):
        return "by path, basename or import stem; %s" % (_UNSEEN,)
    return "by path or basename"


def none_line(results):
    """The one line for results that found nothing - saying what was searched,
    since an empty answer is only as wide as the search behind it."""
    paths = [r["path"] for r in results]
    ways = ["path", "basename"]
    if any(p.endswith(".py") for p in paths):
        ways.append("Python module import")
    if any(is_js(p) for p in paths):
        ways.append("JS/TS import stem")
    text = "No tracked file names any file searched here, by %s or %s" % (
        ", ".join(ways[:-1]), ways[-1])
    if any(p.endswith(".py") for p in paths):
        text += ", or a top-level name a Python file defines"
    if any(is_js(p) for p in paths):
        text += "; %s" % (_UNSEEN,)
    return text + "."


def _has_any(result):
    return bool(result["error"] or result["total"] or result["symbols"]
                or result["namesError"])


def _counted(shown, total, noun):
    plural = noun if total == 1 else noun + "s"
    if len(shown) < total:
        return "%d of %d %s shown" % (len(shown), total, plural)
    return "%d %s" % (total, plural)


def _names_line(result):
    symbols = result["symbols"]
    shown = symbols[:NAME_CAP]
    parts = []
    for sym in shown:
        files = sym["files"][:NAME_FILE_CAP]
        more = "" if len(files) == sym["total"] else " (%d of %d)" % (
            len(files), sym["total"])
        parts.append("%s in %s%s" % (sym["name"], ", ".join(files), more))
    if result["namesError"]:
        parts.append("names not read: %s" % (result["namesError"],))
    cut = "" if len(shown) == len(symbols) else ", %d shown" % (len(shown),)
    return "  names used elsewhere (%d of %d defined%s): %s" % (
        len(symbols), result["defined"], cut, "; ".join(parts))


def _block(result):
    """One declared file's lines."""
    if result["error"]:
        return ["- %s: could not read its dependants: %s"
                % (result["path"], result["error"])]
    if result["total"]:
        listed = ", ".join("%s (%s)" % (f["file"], f["via"])
                           for f in result["files"])
        lines = ["- %s: %s - %s" % (
            result["path"], _counted(result["files"], result["total"], "file"),
            listed)]
    else:
        lines = ["- %s: no tracked file names it %s"
                 % (result["path"], _searched(result["path"]))]
    if result["symbols"] or result["namesError"]:
        lines.append(_names_line(result))
    return lines


def render(results):
    """Every result's lines, unbounded - one line in all when nothing names any
    of the files, so the answer is never silently absent."""
    if not any(_has_any(r) for r in results):
        return [none_line(results)]
    return [line for result in results for line in _block(result)]


def _named_in(path, text):
    return bool(text) and (path in text or re.search(
        r"(?<![\w-])%s(?![\w-])" % re.escape(posixpath.basename(path)), text)
        is not None)


def scan_order(paths, description):
    """Which declared files a budgeted section reaches first: the ones the
    task's description names (by path or basename), then source files, then
    documents - each group in the order the task declares them."""
    def rank(path):
        if _named_in(path, description or ""):
            return 0
        return 2 if is_doc(path) else 1
    return [p for _i, p in sorted(enumerate(paths),
                                  key=lambda ip: (rank(ip[1]), ip[0]))]


def section(root, paths, description, rest_command, exclude=(), git=None,
            file_budget=FILE_BUDGET, line_budget=LINE_BUDGET):
    """A brief's bounded section: `{"lines", "shown", "declared",
    "answerable"}`. At most `file_budget` files are scanned, in `scan_order`,
    and whole files' lines are kept while they fit `line_budget`; when fewer
    files are shown than were declared, the last line says how many of how many
    and gives `rest_command`, which lists them all. `answerable` is whether any
    shown file has something to answer for."""
    order = scan_order([_norm(p) for p in paths], description)
    scanned = order if file_budget is None else order[:file_budget]
    results = dependants(root, scanned, exclude=exclude, git=git)
    if not any(_has_any(r) for r in results):
        lines, shown = [none_line(results)], results
    else:
        lines, shown = [], []
        for result in results:
            block = _block(result)
            if line_budget is not None and len(lines) + len(block) > line_budget:
                break
            lines += block
            shown.append(result)
    if len(shown) < len(paths):
        lines.append("dependants of %d of %d declared files shown; the rest: %s"
                     % (len(shown), len(paths), rest_command))
    return {"lines": lines, "shown": len(shown), "declared": len(paths),
            "answerable": any(_has_any(r) for r in shown)}
