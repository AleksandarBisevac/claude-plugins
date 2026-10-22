#!/usr/bin/env python3
"""
The lints and walks that judge this repository's own source - development code, kept
out of the shipped plugin.

WHY IT IS A SEPARATE FILE. `_output.py` is the anchor every shipped script imports on
every start, and for a long time it also held everything that READS the repository to
judge it: the dialect lints, the preamble check, the prose-number scan, the selftest
coverage classifier. None of that runs in an installed copy, yet all of it shipped,
was parsed on every hook-adjacent start and was the largest part of the file. It
leaves with the other development modules (`_deps`, `_refs`) to `tools/lints/`, under
a basename that collides with nothing in `scripts/`, because `import` and `_loader`
both resolve by basename.

WHAT STAYED. The anchors, `safe_stdio`, the success line, the file walks a shipped
script asks (`py_files`, `lint_py_files`, `py_index`, `moved_file_target`, the UI
surface sources) and `install_path`. A name moved here is one no shipped file reads;
`tests/test__output.py` holds both halves.

`install_path()` never puts this directory on `sys.path` - that is the point of keeping
it out of `scripts/` - so a development caller (the harness, a tool) adds it itself.

This module carries no `--selftest`; its cases live in `tests/test__output_lints.py`.
"""
import ast
import functools
import os
import sys

# The path bootstrap for a development module that lives OUTSIDE the plugin: it
# walks UP to the directory that holds `plugins/audit/scripts/_output.py` instead
# of counting `dirname()` calls, so it does not encode how deep this file sits.
# The shipped scripts carry `_output.PATH_PREAMBLE`, which walks up to `_output.py`
# itself and would run off the filesystem root from here, because this directory
# is not under `scripts/`. `install_path()` then adds `scripts/` and every
# subdirectory of it holding a `.py`.
_anchor_root = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_root, "plugins", "audit", "scripts",
                                      "_output.py")):
    _anchor_up = os.path.dirname(_anchor_root)
    if _anchor_up == _anchor_root:
        raise ImportError("audit lints: walked to the filesystem root from %s "
                          "without finding plugins/audit/scripts/_output.py - the "
                          "repository root is gone and no sibling can be imported"
                          % (__file__,))
    _anchor_root = _anchor_up
_anchor_dir = os.path.join(_anchor_root, "plugins", "audit", "scripts")
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

from _output import (  # noqa: E402
    HOOKS_DIR, LINTS_DIR, LOADER_PROBE_DIR, REPO_ROOT, SCRIPTS_DIR,
    TESTS_DIR, lint_py_files, posix_rel, script_files)





# --- the files this repo KEEPS -------------------------------------------------
# ONE walk for every rule that asks which files this repo holds. `_refs` wrote it,
# for the sweep-document rule and the published-fetch rule, and its own note says
# why there is only one: the second rule had a walk of its own and it was a hand
# list of four directory names, wrong in both directions at once. It reached
# whatever the browser tool had last left in the tree, so the candidate set moved
# with what had recently run on this machine rather than with anything in the
# commit, and it pruned `.claude/` wholesale, which held the tracked skills out of
# a rule that is precisely about a document publishing a fetch.
#
# IT LIVES HERE, AT THE ANCHOR, and that is the only thing about it that is new.
# `_refs` sits above the anchor; the prose-number scan below is in this module
# and needs the same answer, so a copy here would be exactly the
# two-prune-lists defect one layer down. `_refs` keeps the names and delegates.
#
# `.claude/worktrees/` is the entry that makes the pruning necessary rather than
# tidy: it holds WHOLE CHECKOUTS of this repo - as many as there were recent
# agents. A scan that did not know about it would report every finding once per
# worktree, so the finding count would depend on nothing that is in the commit.
#
# Only the unambiguous half of the format is honoured: a line ending in `/` with no
# glob metacharacter names a directory. A pattern and a bare file path are the rest
# of gitignore, and reading them would be implementing it. The consequence is
# stated rather than hidden - an ignored FILE of a scanned extension stays a
# candidate of THIS walk, which is why the generated report has a row of its own in
# `PROSE_SCAN_EXEMPT`.
#
# THE PROSE SCANS DO NOT START FROM THIS WALK ANY MORE: `prose_scan_set()` asks git
# for the tracked files plus the untracked ones `.gitignore` does not name, so a
# file written during a task is read before the commit that lands it, and falls back to this derivation only where git cannot answer - these
# suites are also verified over a `git archive HEAD` export, which has no `.git` at
# all. The fallback says so in the set it returns.
_IGNORE_GLOB_CHARS = "*?[]!"


def _ignored_dirs(root):
    """`(patterns, problem)` - the directory patterns `.gitignore` declares.

    Exactly one of the two is None. Falling back to "nothing is ignored" would walk
    the agent worktrees and report every finding once per copy, which is a wrong
    answer wearing the shape of a right one. `.gitignore` is tracked, so a tree
    without a readable one is broken rather than minimal.
    """
    try:
        with open(os.path.join(root, ".gitignore"), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return None, ("unreadable, so the directories this repo does not keep "
                      "cannot be derived: %s" % exc)
    # `.git` is never IN `.gitignore` - git does not ignore its own directory - so it
    # is the one name here, and the only one this function spells.
    out = [".git"]
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or not line.endswith("/"):
            continue
        rel = line.strip("/")
        if not rel or [ch for ch in _IGNORE_GLOB_CHARS if ch in rel]:
            continue
        out.append(rel)
    return tuple(sorted(set(out))), None


def _ignored_files(root):
    """`(patterns, problem)` - the FILE paths `.gitignore` declares, same contract.

    The other half of `_ignored_dirs()`, and deliberately not merged with it: a rule
    whose subject is "what this repo keeps as source" wants ignored files SCANNED -
    where git cannot say what is tracked, a scratch file of a scanned extension is
    scanned like any other, and the way to opt out is a row somebody wrote. A rule
    whose subject is a COMMITTED
    artifact wants them gone, because a scratch render is not a published page and a
    finding about one depends on what somebody last rendered here rather than on the
    commit.

    Two subjects, two candidate sets, one format read twice - which is why this is a
    separate reader taken by the rules that need it rather than a change to the walk
    every rule shares.

    Only the unambiguous half again: a line that does NOT end in `/` and carries no
    glob metacharacter names a file. Anything else is a pattern, and reading patterns
    would be implementing gitignore.
    """
    try:
        with open(os.path.join(root, ".gitignore"), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return None, ("unreadable, so the files this repo does not keep "
                      "cannot be derived: %s" % exc)
    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.endswith("/"):
            continue
        rel = line.strip("/")
        if not rel or [ch for ch in _IGNORE_GLOB_CHARS if ch in rel]:
            continue
        out.append(rel)
    return tuple(sorted(set(out))), None


def _is_ignored(rel_dir, patterns):
    """Whether the directory at `rel_dir` is one the patterns name.

    Gitignore's anchoring rule, and the only part of it needed here: a pattern with
    no slash inside it matches a directory of that NAME at any depth
    (`__pycache__/`), one with a slash is anchored to the repo root
    (`.claude/usage/`). Collapsing the two would either prune every directory
    called `usage` or fail to prune the one that matters, and both readings look
    right in a review.
    """
    name = rel_dir.rsplit("/", 1)[-1]
    for pattern in patterns:
        if "/" in pattern:
            if rel_dir == pattern or rel_dir.startswith(pattern + "/"):
                return True
        elif name == pattern:
            return True
    return False


def kept_files(root, patterns, exts, drop=None):
    """Relative paths of every file of `exts` this repo KEEPS, sorted.

    `drop` is OPTIONAL and defaults to today's behaviour on purpose: ignored
    DIRECTORIES are always pruned, because one of them holds whole checkouts of this
    repo and a scan that walked them would report every finding once per agent.
    Ignored FILES are pruned only for a caller that asks, because whether they belong
    in the candidate set is a property of the RULE's subject and not of the walk -
    see `_ignored_files()`.

    Passing `drop` never widens the set, so a caller that adds it can only stop
    reporting things; a caller that forgets it keeps exactly the answer it had.
    """
    out = []
    for base, dirs, files in os.walk(root):
        rel_base = posix_rel(base, root)
        prefix = "" if rel_base == "." else rel_base + "/"
        dirs[:] = sorted(d for d in dirs if not _is_ignored(prefix + d, patterns))
        for name in sorted(files):
            if not name.endswith(exts):
                continue
            rel = prefix + name
            if drop and _is_ignored(rel, drop):
                continue
            out.append(rel)
    return sorted(out)


# The variables that point git at a repository other than the one `-C` names. A
# suite run from inside a hook or a scoped commit inherits some of them, and
# `ls-files` would then list THAT index while the scan reads this directory.
_GIT_REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")


def _git_out(root, args):
    """`(returncode, stdout bytes, stderr text)` of `git -C root <args>`, or
    `(None, b"", reason)` when git could not be started at all."""
    import subprocess
    env = dict((k, v) for k, v in os.environ.items() if k not in _GIT_REPO_VARS)
    try:
        done = subprocess.run(["git", "-C", root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, b"", "git could not be started: %s" % (exc,)
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


# What a verdict says its candidate set was, spelled once: `prose_scan_set()["basis"]`
# prints it and the cases that pin it read this name rather than a copy.
GIT_LISTED_BASIS = "the files git lists: tracked, plus untracked and not ignored"


def tracked_files(root, exts):
    """`(paths, why)` - the files of `exts` git lists under `root`, sorted, as
    `(list, None)` - the tracked ones plus the untracked ones `.gitignore` does not
    name, because a file a task has just created is not in the index until the
    commit that closes it, and a lint scoped by the index alone would first read
    it on the commit that lands it red; or `(None, why)` when git cannot answer for this root.

    Exactly one of the two is None, the contract `_ignored_dirs()` follows, so a
    caller cannot read "git could not say" as "nothing is tracked". Git cannot
    answer when it is absent, when `root` is no work tree (a `git archive HEAD`
    export, which these suites are also verified over), or when the work tree
    git finds belongs to a DIFFERENT repository than `root` - a scratch copy
    sitting inside some other checkout would otherwise be answered with that
    checkout's index.

    A path in the index that is not a file on disk is dropped: an uncommitted
    deletion is not a file to read. `--others` lists such a path never, and
    `--cached` lists it, which is why the `isfile` filter below stays.
    """
    code, said, err = _git_out(root, ["rev-parse", "--show-toplevel"])
    if code is None:
        return None, err
    if code != 0:
        return None, "%s is not a git work tree (%s)" % (
            root, (err.strip().splitlines() or ["no reason given"])[0])
    top = said.decode("utf-8", "replace").strip()
    if os.path.normcase(os.path.realpath(top)) != os.path.normcase(os.path.realpath(root)):
        return None, ("git's work tree for %s is %s, a different directory, so its "
                      "index says nothing about this one" % (root, top))
    code, said, err = _git_out(
        root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    if code is None:
        return None, err
    if code != 0:
        return None, "git ls-files failed: %s" % (
            (err.strip().splitlines() or ["no reason given"])[0],)
    names = [n for n in said.decode("utf-8", "replace").split("\0") if n]
    return sorted(n for n in names if n.endswith(exts)
                  and os.path.isfile(os.path.join(root, n))), None


# --- the pinned preamble ------------------------------------------------------
# The name of this module, spelled once. The preamble searches for the FILE and the
# lint looks for calls on the MODULE, and those two spellings drifting apart is the
# kind of thing that turns a lint into decoration.
_ANCHOR_MODULE = "_output"

# THE ONE FILE THAT MUST NOT CARRY THE PREAMBLE, EXEMPTED BY NAME. Two reasons, and
# the second is the one that would have bitten silently: this module IS the marker
# the preamble walks up to find, so a copy here would be a bootstrap searching for
# itself; and this module holds `PATH_PREAMBLE` as a string, so a text count over
# its own source finds exactly one occurrence and would read as COMPLIANT. That is
# the same self-matching trap `_harness`' m1 needle and `_refs`' fixture constants
# each document — a scanner that lives in the tree it scans must not plant its own
# needle there.
_PREAMBLE_EXEMPT = "_output.py"

# Byte-identical in every `.py` under `scripts/` except this one, placed after the
# stdlib imports and above the first sibling import. Three things it deliberately
# does NOT do, each already known to break something here:
#
#   * it does not touch the `__main__` blocks. `from _output import safe_stdio`
#     stays exactly as it is: rewritten to `_output.safe_stdio()` it becomes an
#     `ast.Attribute` call, which `entries_missing_guard`'s `_call_lines` does not
#     recognise, and every entry point in the tree would be reported as unguarded.
#   * it carries no `# --- name ---` banner. `_deps._NAV_HEADER_RE` matches those at
#     column 0, so a banner in every file would let a 2,000-line module satisfy
#     `navigability_violations()` on boilerplate.
#   * it adds no graph edge. Every one of these files already reaches `_output`
#     through the `from _output import safe_stdio` in its `__main__`, which
#     `_deps._imported_sibling_names` counts — the fence draws `_areas -> _output`
#     although `_areas.py` had no module-level import of it. `--render`'s output is
#     therefore byte-identical across this change, and that was verified, not
#     assumed.
PATH_PREAMBLE = '''\
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
'''


def _install_path_line(tree):
    """Line of the module-level `_output.install_path()` statement, or None.

    Module level via `_straight_line`, which stops at every `def` boundary: a call
    buried in a function is a plan to bootstrap later, and later is after the sibling
    imports it was supposed to enable.
    """
    for stmt in _straight_line(tree.body):
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        func = stmt.value.func
        if (isinstance(func, ast.Attribute) and func.attr == "install_path"
                and isinstance(func.value, ast.Name)
                and func.value.id == _ANCHOR_MODULE):
            return stmt.lineno
    return None


def _first_sibling_import_line(tree, sibling_names):
    """Lowest line number at which `tree` imports a scripts/ sibling, or None.

    `_output` itself does not count — the preamble's own `import _output` is the
    line that makes every other import possible, so counting it would report every
    correctly-written file. Anywhere in the tree, not only module level: an import
    fifty lines inside a function still has to sit below the bootstrap textually,
    and every file here puts the preamble at the top, so a whole-tree scan is
    strictly the safer reading.

    `_deps._imported_sibling_names` walks the same node shapes and cannot be shared:
    `_deps` imports THIS module, not the other way round, so the layer rule forbids
    the edge that would let this call it. Different questions in any case — that one
    returns the names for the graph, this one returns a line number for an ordering.
    """
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bases = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            bases = [(node.module or "").split(".")[0]]
        else:
            continue
        for base in bases:
            if base in sibling_names and base != _ANCHOR_MODULE:
                lines.append(node.lineno)
    return min(lines) if lines else None


def _preamble_line_repeats(src):
    """Source line numbers where a line of `PATH_PREAMBLE` occurs after its first.

    WHOLE-LINE EQUALITY, NOT `in`, and that is the whole reason this could be added
    without exempting anything. `_loader.py` and `panel-server.py` both MENTION
    `_output.install_path()` in prose - a docstring sentence and a commented
    one-liner - so a substring count would convict two correct files, and the
    repair for that would be a widening nobody could hold. A repeat is a source
    line that IS a preamble line, spelled identically down to its indentation.

    Counting the LINES rather than a named tail is the deliberate choice: the tail
    is where the repeat happened to land this time, and a constant naming it would
    be a second copy of a fact whose home is `PATH_PREAMBLE`. Derived from the
    block itself, this catches a repeat of any part of it.
    """
    wanted = set(line for line in PATH_PREAMBLE.splitlines() if line.strip())
    seen = set()
    repeats = []
    for number, line in enumerate(src.splitlines(), 1):
        if line not in wanted:
            continue
        if line in seen:
            repeats.append(number)
        else:
            seen.add(line)
    return repeats


def path_preamble_violations(script_dir=None):
    """(relname, problem) for every `.py` under `scripts/` whose bootstrap is wrong.

    The ways to be wrong, and every one but the first is a reason this is not one
    `if PATH_PREAMBLE in src`:

      * NOT EXACTLY ONCE. Counted, not tested for membership — a doubled preamble is
        as wrong as a missing one (it is a second `install_path()` call and a second
        walk-up under two more leaked names), and `in` cannot tell one from two.
      * PARTIALLY REPEATED. Counting the WHOLE block finds one occurrence in a file
        that pastes the block once and then repeats its last two statements, because
        a doubled `import _output` / `_output.install_path()` tail is not the whole
        block — so the files under `panel/` carrying exactly that were reported by
        nothing, while the house rule said this function counted the preamble "once,
        never twice". It counted the TEXT once; the bootstrap ran twice. Every line
        of the block is therefore counted too, and each must occur once.
      * NO `install_path()` CALL AT MODULE LEVEL. A file could carry the text inside
        a docstring and satisfy a text count; this is read off the AST.
      * A SIBLING IMPORT ABOVE THE CALL. A preamble pasted below the imports it
        exists to enable is decoration: those imports resolved for some other
        reason, and the day that reason goes away the file breaks with the bootstrap
        sitting right there looking correct.

    `_output.py` is exempt BY NAME — see `_PREAMBLE_EXEMPT` for the two reasons,
    one of which is that a naive count over this file's own source reads as
    compliant.

    A file that cannot be read or parsed is a violation rather than a skip, the same
    rule `entries_missing_guard` and `house_style_violations` follow.
    """
    # `script_files()` is the RESOLUTION walk - `_loader` builds its index from it
    # and must see every real file - so the filtering happens here, where a LINT
    # is the one asking. Same rule as `lint_py_files`, applied to the memoised
    # list rather than re-walking for it.
    files = (lint_py_files(script_dir) if script_dir is not None
             else [(rel, path) for rel, path in script_files()
                   if not rel.startswith(LOADER_PROBE_DIR)
                   and "/" + LOADER_PROBE_DIR not in rel])
    sibling_names = set(os.path.basename(rel)[:-3] for rel, _path in files)
    violations = []
    for rel, path in files:
        if os.path.basename(rel) == _PREAMBLE_EXEMPT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            violations.append((rel, "cannot be read or parsed: %s" % exc))
            continue
        found = src.count(PATH_PREAMBLE)
        if found != 1:
            violations.append((rel, "carries the pinned path preamble %d times, "
                                    "not once" % found))
        repeats = _preamble_line_repeats(src)
        if repeats:
            violations.append((rel, "repeats a line of the pinned path preamble at "
                                    "%s - a partial repeat is a second bootstrap, "
                                    "and counting the whole block reads it as "
                                    "compliant"
                                    % ", ".join(str(n) for n in repeats)))
        installed = _install_path_line(tree)
        first_sibling = _first_sibling_import_line(tree, sibling_names)
        if installed is None:
            violations.append((rel, "never calls %s.install_path() at module level"
                                    % _ANCHOR_MODULE))
        elif first_sibling is not None and first_sibling < installed:
            violations.append((rel, "imports a sibling on line %d, above the "
                                    "%s.install_path() on line %d - a bootstrap "
                                    "below the imports it exists to enable is "
                                    "decoration" % (first_sibling, _ANCHOR_MODULE,
                                                    installed)))
    return violations


# --- self-location lint -------------------------------------------------------
# `os.path.basename(__file__)` yields a NAME, not a location: `panel-server.py`
# prints its own filename in a usage line, which is depth-independent and stays
# legal. Every other read of `__file__` computes WHERE the file is, which is the
# thing this forbids.
_SELF_LOCATION_ALLOWED = "basename"


def _self_location_lines(tree):
    """Lines where `__file__` is read for anything but `os.path.basename(...)`."""
    named = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) != 1:
            continue
        func = node.func
        arg = node.args[0]
        if (isinstance(func, ast.Attribute) and func.attr == _SELF_LOCATION_ALLOWED
                and isinstance(arg, ast.Name) and arg.id == "__file__"):
            named.add(id(arg))
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and node.id == "__file__"
                  and id(node) not in named)


def depth_sensitive_paths(script_dir=None):
    """(relname, line, what) for a `.py` under `scripts/` that locates ITSELF.

    THE RULE IS "NO `__file__` AT ALL", NOT "NO PARENT OF `__file__`", and the
    stronger form is the only one that works. The seventeen sites this replaced
    were almost all written in TWO steps —
    `_HERE = os.path.dirname(os.path.abspath(__file__))` on one line and
    `os.path.join(os.path.dirname(_HERE), "hooks")` two hundred lines later — so a
    lint that only looked for `dirname(dirname(...))` nested in ONE expression
    would have passed every single one of them. Once the two-step is legal there
    is no version of "one level is fine" that a lint can hold.

    What makes the strong form affordable is that the pinned preamble carries the
    ONLY `os.path.dirname(os.path.abspath(__file__))` left in the tree, and it is
    cut out before the scan — replaced by blank lines rather than deleted, so a
    violation still reports the line number the reader will open. Anything a file
    genuinely needs is on `_output`: `SCRIPTS_DIR`, `PLUGIN_ROOT`, `HOOKS_DIR`,
    `TESTS_DIR`, `LINTS_DIR`, `REPO_ROOT`.

    `hooks/` IS NOT SCANNED. Hooks may not import `scripts/` (`_deps` r5/r6), so
    the anchors are out of their reach by design and `hooks/_config.find_script()`
    has to derive the directory from its own `__file__`. Reporting that would be
    demanding a fix the layer rule forbids.

    `_output.py` is exempt for the two reasons `_PREAMBLE_EXEMPT` records: it holds
    `PATH_PREAMBLE` as a string, and it is the file the anchors are defined in.
    """
    # `script_files()` is the RESOLUTION walk - `_loader` builds its index from it
    # and must see every real file - so the filtering happens here, where a LINT
    # is the one asking. Same rule as `lint_py_files`, applied to the memoised
    # list rather than re-walking for it.
    files = (lint_py_files(script_dir) if script_dir is not None
             else [(rel, path) for rel, path in script_files()
                   if not rel.startswith(LOADER_PROBE_DIR)
                   and "/" + LOADER_PROBE_DIR not in rel])
    blanked = "\n" * PATH_PREAMBLE.count("\n")
    violations = []
    for rel, path in files:
        if os.path.basename(rel) == _PREAMBLE_EXEMPT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src.replace(PATH_PREAMBLE, blanked), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            violations.append((rel, 0, "cannot be read or parsed: %s" % exc))
            continue
        for line in _self_location_lines(tree):
            violations.append((rel, line,
                               "reads __file__ outside the pinned preamble - a file "
                               "that locates itself carries its own depth; take the "
                               "directory from _output's anchors instead"))
    return violations


# --- a project derived from a manifest path -------------------------------------
# Sites that still derive a project by their own walk or by `dirname` of the
# manifest, each a statement about code that EXISTS: a row whose site no longer
# matches is reported, so the table cannot keep permission nobody uses.
# (file under scripts/, innermost function, reason)
MANIFEST_DIRNAME_PROJECTS = ()


def _identifier(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _names_manifest(node):
    """True when an identifier under `node` names a manifest path."""
    for n in ast.walk(node):
        ident = (_identifier(n) or "").lower()
        if "manifest" in ident or ident.startswith("mpath"):
            return True
    return False


def _dirname_of_manifest(expr):
    """True when `expr` holds a `dirname(...)` call over a manifest path."""
    return any(isinstance(n, ast.Call) and _identifier(n.func) == "dirname"
               and any(_names_manifest(a) for a in n.args)
               for n in ast.walk(expr))


def _project_derivations(tree):
    """`(line, innermost function or "<module>")` for each place a project is
    derived by `dirname` arithmetic on a manifest path: an assignment to a name
    saying `proj`, a keyword argument saying `proj`, or a `return` from a
    function whose name says `project`."""
    found = []

    def visit(node, where, in_project_fn):
        for child in ast.iter_child_nodes(node):
            inner, inner_proj = where, in_project_fn
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner, inner_proj = child.name, "project" in child.name.lower()
            value = None
            if isinstance(child, ast.Assign) and any(
                    "proj" in (_identifier(n) or "").lower()
                    for t in child.targets for n in ast.walk(t)):
                value = child.value
            elif isinstance(child, ast.keyword) and child.arg \
                    and "proj" in child.arg.lower():
                value = child.value
            elif isinstance(child, ast.Return) and in_project_fn:
                value = child.value
            if value is not None and _dirname_of_manifest(value):
                found.append((value.lineno, where))
            visit(child, inner, inner_proj)

    visit(tree, "<module>", False)
    return found


def manifest_dirname_project_violations(script_dir=None, table=None):
    """(file, what) for each project derived from a manifest path by `dirname`
    arithmetic outside `_output.project_of_manifest`, and each table row whose
    site no longer does it.

    THE CLASS, NOT THE INSTANCE. A plan's project was answered by more than
    one walk, and one of them fell back to the manifest's own directory -
    `docs/audit` on a default plan - so a hand-run gate left a `.claude/`
    there and every later run recorded under `docs/audit/docs/audit`. The
    repair is one resolver; this is what keeps a new site from deriving its
    own answer again.

    WHAT IT CANNOT SEE: a project derived by a name that says neither `proj`
    nor `manifest` (`root = os.path.dirname(path)`), a `pathlib` `.parent`
    chain, or a walk with no `dirname` over the manifest's name in it. A
    clean result means none of the shapes it reads matched - not that every
    site in the tree asks the resolver."""
    script_dir = script_dir or SCRIPTS_DIR
    table = MANIFEST_DIRNAME_PROJECTS if table is None else table
    allowed = set((f, fn) for f, fn, _why in table)
    seen = set()
    violations = []
    for rel, path in lint_py_files(script_dir):
        rel = rel.replace(os.sep, "/")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            violations.append((rel, "cannot be read or parsed: %s" % (exc,)))
            continue
        for line, where in _project_derivations(tree):
            seen.add((rel, where))
            if (rel, where) not in allowed:
                violations.append(
                    (rel, "line %d (%s): derives a project from a manifest path "
                          "by dirname - ask _output.project_of_manifest, so it "
                          "lands where the gate and the report do"
                          % (line, where)))
    for f, fn, _why in table:
        if (f, fn) not in seen:
            violations.append((f, "MANIFEST_DIRNAME_PROJECTS names %s, which no "
                                  "longer derives a project by dirname - drop the "
                                  "row" % (fn,)))
    return sorted(violations)


# --- entry-point guard check --------------------------------------------------
def _is_entry(node):
    """True for `if __name__ == "__main__":`, however the comparison is spelled."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    names = [node.test.left] + list(node.test.comparators)
    return (any(isinstance(n, ast.Name) and n.id == "__name__" for n in names)
            and any(isinstance(n, ast.Constant) and n.value == "__main__" for n in names))


def _straight_line(body):
    """Statements that run when `body` runs, in order — not the ones merely DEFINED.

    A `print` inside a `def` is not output; it is a plan to produce output later, after
    the entry block has already installed the guard. Descending into function and class
    bodies would flag every script in the directory for code that cannot run first, so
    this walks the executable spine (module level, `if`/`try`/`with`/loop bodies) and
    stops at every definition boundary.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list):
                for sub in _straight_line(inner):
                    yield sub
        for handler in getattr(stmt, "handlers", []) or []:
            for sub in _straight_line(handler.body):
                yield sub


def _call_lines(stmts, func):
    return [s.lineno for s in stmts
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Name) and s.value.func.id == func]


def entries_missing_guard(dirs=None):
    """Names of .py files that run as a command but do not call safe_stdio() first.

    SCOPE: `scripts/` AND `tests/`, and deliberately not `hooks/` — hooks stay
    importless on purpose (see the module docstring) and are covered by CI's cp1252
    pass instead. `tests/` is in because a test file is run exactly the way a script
    is, prints far more prose than a script does, and would take its own result down
    with it on a Windows pipe; there is no reason it is exempt except that nothing
    used to look there.

    Returns a sorted list of names, each relative to the directory it was found in.
    Two ways to be listed, because both ship the same crash: never calling it, or
    calling it after something has already printed — a guard installed after the
    output it guards is decoration.

    "First" is judged on what EXECUTES, via `ast`, not on where text appears. Every one of
    these scripts defines printing functions hundreds of lines above its `__main__` block,
    so a textual "the call must precede the first `print(`" would name every one of them
    for code that cannot possibly run before the guard. The rule is: among the statements
    that actually run — module level, then the entry block — no `print` may precede the
    `safe_stdio()` call. A file that cannot be parsed is reported rather than skipped,
    since a syntax error is a worse thing to pass over in silence.
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, TESTS_DIR, LINTS_DIR)
    missing = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                missing.append(name)
                continue
            entries = [n for n in tree.body if _is_entry(n)]
            if not entries:
                continue  # imported module: its importer holds the guard
            runs = list(_straight_line(tree.body))
            guards = _call_lines(runs, "safe_stdio")
            prints = _call_lines(runs, "print")
            if not guards or (prints and min(prints) < min(guards)):
                missing.append(name)
    return sorted(missing)


# --- usage-hint check ---------------------------------------------------------
# Read as a CALL, never as text: the lint that learns which flags argparse adds reads
# other files' constructions, and the hook's own docstring describes the seam, so a
# text match would convict two files that build no parser at all.
_PARSER_CTOR = "ArgumentParser"
_USAGE_HOOK = "attach_usage_hint"
_PARSE_CALLS = ("parse_args", "parse_known_args", "parse_intermixed_args",
                "parse_known_intermixed_args")


def _called(call):
    """The bare name a call reaches, `a.b.f(...)` and `f(...)` alike; '' otherwise."""
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return fn.id if isinstance(fn, ast.Name) else ""


def _scope_nodes(scope):
    """Every node of one scope, stopping at each nested def, class and lambda.

    A parser name is looked up in the scope that built it: `p` hooked in another
    function is another `p`, and descending would read it as this one's."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _scope_parsers(scope):
    """(line, why) per parser built in `scope`; `why` is None when it is hooked."""
    nodes = list(_scope_nodes(scope))
    calls = [n for n in nodes if isinstance(n, ast.Call)]
    hooked, wrapped, templates, parsed = {}, set(), set(), {}
    for call in calls:
        name = _called(call)
        first = call.args[0] if call.args else None
        if name == _USAGE_HOOK and isinstance(first, ast.Name):
            hooked[first.id] = min(call.lineno, hooked.get(first.id, call.lineno))
        elif name == _USAGE_HOOK and isinstance(first, ast.Call):
            wrapped.add(id(first))
        elif name in _PARSE_CALLS and isinstance(call.func, ast.Attribute) \
                and isinstance(call.func.value, ast.Name):
            held = call.func.value.id
            parsed[held] = min(call.lineno, parsed.get(held, call.lineno))
        for kw in call.keywords:
            if kw.arg == "parents" and isinstance(kw.value, (ast.List, ast.Tuple)):
                templates |= set(e.id for e in kw.value.elts
                                 if isinstance(e, ast.Name))
    held_by = {}
    for node in nodes:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            held_by[id(node.value)] = node.targets[0].id
    found = []
    for call in calls:
        if _called(call) != _PARSER_CTOR:
            continue
        name = held_by.get(id(call))
        if id(call) in wrapped or name in templates:
            found.append((call.lineno, None))
        elif name is None:
            found.append((call.lineno, "built where no name holds it, so nothing "
                          "can hand it to %s()" % (_USAGE_HOOK,)))
        elif name not in hooked:
            found.append((call.lineno, "`%s` is never handed to %s() in the scope "
                          "that built it" % (name, _USAGE_HOOK)))
        elif name in parsed and parsed[name] < hooked[name]:
            found.append((call.lineno, "`%s` parses argv on line %d, before %s() "
                          "on line %d - the usage error is raised by then"
                          % (name, parsed[name], _USAGE_HOOK, hooked[name])))
        else:
            found.append((call.lineno, None))
    return found


def parser_sites(files):
    """(rel, line, why) for every parser built in `files`, hooked or not.

    `files` is `(rel, path)` pairs as `lint_py_files` yields them; `why` is None for
    a parser handed to the usage hook before it parses, or for a `parents=` template
    that never parses argv itself. A file that cannot be parsed is one row at line 0
    with the reason, never skipped."""
    out = []
    for rel, path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            out.append((rel, 0, "cannot be read or parsed: %s" % (exc,)))
            continue
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))]
        for scope in scopes:
            out.extend((rel, line, why) for line, why in _scope_parsers(scope))
    return sorted(out, key=lambda row: (row[0], row[1]))


def usage_hint_violations(dirs=None):
    """(rel, line, why) for every parser under `dirs` the usage hook never reaches.

    The hook is `_claude_home.attach_usage_hint`: it makes a usage error name this
    copy's version and any newer installed copy, which is what tells a caller running
    an older cached copy that the verb it asked for lives in a newer one. One call
    beside each construction, never a local copy of the hook. Scoped to `scripts/`:
    hooks may not import it, and build no parser.

    `parser_sites()` is the argparse half; `verb_dispatch_sites()` is the other
    shape — a dispatcher that reads its verb by hand (`if verb not in (...):`)
    rather than through `ArgumentParser`, so nothing there ever calls
    `parse_args` for `parser_sites()` to find. A caller asking an older cached
    copy for a verb only a newer one knows must be told the same thing either way,
    so both shapes are read here."""
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, LINTS_DIR)
    found = []
    seen = set()
    for d in dirs:
        files = lint_py_files(d)
        for row in parser_sites(files) + verb_dispatch_sites(files):
            # A file that will not parse is reported by BOTH walks, with the
            # same (rel, 0, why) row either way - one finding, not two, for one
            # broken file.
            if row[2] and row not in seen:
                seen.add(row)
                found.append(row)
    return found


# --- verb-dispatch check (the hand-parsed shape) --------------------------------
# Two signals, both required, because `<name> not in (<literal>, ...)` alone is
# also how this tree validates an ordinary flag or a manifest field - `_ui_theme.
# validate_layout`'s `k not in ("density", "order")` and others shaped like it are
# NOT a verb dispatcher, and a lint that could not tell them apart would be unusable
# here. A genuine hand-parsed dispatcher is told apart by BOTH of what it does
# with the same name afterwards: it is DISPATCHED ON (compared with `==` against
# one of the same literals, elsewhere in the same function - the shape every
# `if verb == "plan": ... elif verb == "drop":` chain in this tree has), and the
# branch that refuses an unrecognised value PRINTS the shared usage block (a
# write naming a module constant called `USAGE` or `_USAGE`, this tree's own
# naming convention for one) - not merely some other error sentence. Either
# signal alone over-fired on the real tree before this was narrowed: the panel's
# `proposal_action` dispatches on `action` but returns a JSON finding, never a
# USAGE block, because an HTTP action has no "older cached copy" to warn; `ado-
# connect.py` prints `USAGE` for a bad `--transport` value but never dispatches
# on it elsewhere. Both are read right by requiring what the review's own finding
# named: a usage BLOCK, printed because a VERB a dispatcher has code for was not
# recognised.
_HINT_CALL = "usage_hint"
_USAGE_NAMES = ("USAGE", "_USAGE")


def _literal_verb_set(node):
    """Whether `node` is a tuple/list/set of two or more string literals — the
    shape a hand-parsed dispatcher compares its verb against, never a single
    flag check (`"--json" in rest`) or a computed membership test."""
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return False
    elts = node.elts
    return len(elts) >= 2 and all(isinstance(e, ast.Constant)
                                  and isinstance(e.value, str) for e in elts)


def _unknown_verb_test(node):
    """`(name, literals)` when `if` node `node`'s test reads
    `<name> not in (<literal>, ...)` — the shape a hand-parsed dispatcher uses to
    refuse a verb argparse would otherwise have rejected through `choices=`.
    `(None, None)` otherwise."""
    if not isinstance(node, ast.If):
        return None, None
    test = node.test
    if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
            and len(test.ops) == 1 and isinstance(test.ops[0], ast.NotIn)
            and len(test.comparators) == 1
            and _literal_verb_set(test.comparators[0])):
        return None, None
    return test.left.id, set(e.value for e in test.comparators[0].elts)


def _dispatches_on(scope_nodes, name, literals):
    """Whether `name` is compared with `==` to one of `literals` elsewhere in
    `scope_nodes` — the sign it is really dispatched on afterwards, and not
    merely validated once and never read again."""
    for node in scope_nodes:
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == name and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1):
            comp = node.comparators[0]
            if isinstance(comp, ast.Constant) and comp.value in literals:
                return True
    return False


def _prints_usage_block(node):
    """Whether `node`'s subtree writes a module-level `USAGE`/`_USAGE` name —
    this tree's own convention for the shared usage block, as opposed to some
    other one-line refusal (`"--all applies to plan and materialize only"`) that
    owes the hint no more than any other error sentence does.

    EACH ARGUMENT'S OWN SUBTREE IS WALKED, not merely tested for being a bare
    `ast.Name`: a usage name read through a `%`-format expression one level
    below the argument itself is still a write of the block, and a check that
    only recognised a bare name missed a shape this tree already writes."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            for arg in sub.args:
                for inner in ast.walk(arg):
                    if isinstance(inner, ast.Name) and inner.id in _USAGE_NAMES:
                        return True
    return False


def _reaches_usage_hint(node):
    """Whether any call inside `node` names `usage_hint` — `_claude_home`'s hint,
    however it is imported (`_claude_home.usage_hint`, or an aliased import)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _called(sub) == _HINT_CALL:
            return True
    return False


def verb_dispatch_sites(files):
    """(rel, line, why) per hand-parsed unknown-verb branch under `files`.

    The companion to `parser_sites()`: an entry point that never builds an
    `ArgumentParser` is invisible there, so a dispatcher written as
    `if verb not in ("list", "plan", ...): print(USAGE); return 2` could print a
    bare usage block forever with nothing catching it. `why` is None when the
    branch itself calls `_claude_home.usage_hint`, which an unknown-verb branch
    that only prints the bare usage block does not; otherwise it names the gap
    the same way `parser_sites` names a parser the hook never reached. A file
    that will not parse is reported at line 0, same as `parser_sites`."""
    out = []
    for rel, path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            out.append((rel, 0, "cannot be read or parsed: %s" % (exc,)))
            continue
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))]
        for scope in scopes:
            nodes = list(_scope_nodes(scope))
            for node in nodes:
                name, literals = _unknown_verb_test(node)
                if name is None:
                    continue
                if not _dispatches_on(nodes, name, literals):
                    continue
                if not _prints_usage_block(node):
                    continue
                if _reaches_usage_hint(node):
                    out.append((rel, node.lineno, None))
                else:
                    out.append((rel, node.lineno,
                                "unknown-verb branch never calls _claude_home."
                                "usage_hint(), so an older cached copy asked for "
                                "a verb only a newer one knows prints a bare "
                                "usage block and names no newer installed copy"))
    return sorted(out, key=lambda row: (row[0], row[1]))


# --- house-style AST checks ---------------------------------------------------
# The four bans: legal Python 3.8, illegal in this repo, and none of them caught by a
# version gate (vermin flags syntax the interpreter cannot run at all — every one of
# these runs fine on 3.8, it is just not this repo's style). Named here once so the
# checker and its selftest cases both read the same list rather than two lists drifting.
_BANNED_MODULES = ("typing", "dataclasses")


def _house_style_violations_in_tree(tree, name):
    """(line, what) tuples for one already-parsed module — the part `ast.walk` can see.

    Walks the WHOLE tree, not the straight-line spine `entries_missing_guard` walks:
    a walrus or a banned import is just as much a style violation buried inside a
    function body as it is at module level, so nothing here stops at a def boundary.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr):
            found.append((node.lineno, "walrus operator (:=)"))
        elif isinstance(node, ast.arg) and node.annotation is not None:
            # EVERY annotated parameter is an `ast.arg`, whichever list it came
            # from - positional, keyword-only, positional-only, `*args`, `**kw` -
            # so one branch covers all five. Written as a walk over each
            # FunctionDef's arg lists first, which is how `*args: str` came to be
            # missed by a version that looked complete.
            found.append((node.lineno, "annotated parameter %r" % (node.arg,)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.returns is not None:
            found.append((node.returns.lineno,
                          "return annotation on %r" % (node.name,)))
        elif isinstance(node, ast.AnnAssign):
            found.append((node.lineno, "annotated assignment"))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                found.append((node.lineno, "from __future__ import"))
            elif node.module in _BANNED_MODULES:
                found.append((node.lineno, "from %s import" % node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _BANNED_MODULES:
                    found.append((node.lineno, "import %s" % alias.name))
    return [(name, line, what) for line, what in found]


def house_style_violations(dirs=None):
    """(filename, line, what) tuples for every banned construct under `dirs`.

    House style, not the 3.8 floor: walrus, `from __future__ import ...`, `typing`,
    `dataclasses` AND ANNOTATIONS are all legal on Python 3.8, so vermin's version
    gate cannot see any of them — they are banned by convention, and conventions
    drift unless something reads the AST.

    ANNOTATIONS WERE THE HALF THAT WAS MISSING, and `CLAUDE.md` named this function
    as their enforcer the whole time. Nothing detected them: not this (which read
    walrus and two import shapes), not vermin (they are 3.8-legal), not ruff (E9+F).
    The tree had accumulated 113 of them, every one in `hooks/`, before a mutation
    asked whether the check went red and it did not. All three shapes are covered now
    — parameter, return and assignment — because a rule stated as "no annotations"
    that reads only one of the three is the same defect one step smaller. Scans every `.py` under `scripts/`, `hooks/` AND `tests/`
    RECURSIVELY through `py_files`, the same walk `entries_missing_guard` uses — and
    for the same reason a file that will not parse is reported as a violation rather
    than skipped, since a syntax error is a worse thing to pass over in silence than
    any single banned import.

    `tests/` is in scope from the first day it existed. A test file is the most
    tempting place in the tree to reach for `typing` or a walrus — nothing ships it,
    so the usual argument feels weaker — and it is also the place where a 3.8
    violation costs most: the suite that would have caught the regression is itself
    the thing that will not start.
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, HOOKS_DIR, TESTS_DIR, LINTS_DIR)
    violations = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError) as exc:
                violations.append((name, getattr(exc, "lineno", 0) or 0,
                                    "file does not parse: %s" % exc))
                continue
            violations.extend(_house_style_violations_in_tree(tree, name))
    return violations


# --- a count whose own evidence was truncated ----------------------------------
# This shape needed a lint of its own rather than an extension
# of either prose scan. Those two read a number that nothing prints; here the number
# IS printed, from a live source, and it is the EVIDENCE BESIDE IT that was cut. The
# claim stayed true the whole time, which is exactly why no existing check could see
# the defect and why the repair had to be mechanical: the same shape had been written
# by hand at sites across the tree, each with its own cap, and a sweep done once by
# hand would have grown a new instance the next time somebody printed a count.
_TRUNCATED_EVIDENCE = ("a count of the whole set beside a bounded slice of it, and "
                       "nothing in the same sentence says what was left out - "
                       "render the list through _output.some_of()")


def _mod_operands(node):
    """The values a `%` format consumes: a tuple's elements, or the single value."""
    if isinstance(node.right, ast.Tuple):
        return list(node.right.elts)
    return [node.right]


def _len_keys(expr):
    """`{collection: lineno}` for every `len(X)` reached anywhere inside `expr`."""
    found = {}
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "len" and len(node.args) == 1:
            found.setdefault(ast.dump(node.args[0]), node.lineno)
    return found


def _prefix_slice_keys(expr):
    """`{collection: lineno}` for every bounded `X[:n]` reached inside `expr`.

    Keyed by every name the SLICED EXPRESSION mentions and not only by the whole
    of it, because `sorted(bad)[:3]` is still a bounded slice of `bad` — one of
    the spellings this lint's sibling sites were written in, and the one a key
    built from the outermost expression alone walks straight past.

    The upper bound may be any expression, not just a literal. A cap held in a
    variable is the same cap, and the site that first proved that is the one
    already doing this correctly: `_warning_groups` slices to a `limit` argument
    and then states the remainder, so a rule reading only literals would have
    credited it for nothing and missed every sibling written that way.
    """
    found = {}
    for node in ast.walk(expr):
        if not isinstance(node, ast.Subscript):
            continue
        window = node.slice
        if not isinstance(window, ast.Slice) or window.upper is None \
                or window.lower is not None or window.step is not None:
            continue
        for inner in ast.walk(node.value):
            if isinstance(inner, (ast.Name, ast.Attribute, ast.Subscript)):
                found.setdefault(ast.dump(inner), node.lineno)
    return found


def _remainder_keys(expr):
    """The collections whose UNSHOWN part `expr` states, as `len(X) - <anything>`.

    STRUCTURAL RATHER THAN A SEARCH FOR THE WORDS. The tail phrase belongs to
    `some_of()` and to the two hand-written sites that predate it, and they do not
    agree on it — a lint reading for `and N more` would pin one wording and call
    the others defects, while this reads the only thing they have in common: the
    remainder is computed from the same count.
    """
    stated = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            stated.update(_len_keys(node.left))
    return stated


def truncated_evidence_violations(dirs=None):
    """(filename, line, what) for a count whose evidence was silently truncated.

    THE SHAPE, in one sentence: inside one `%` format, `len(X)` is interpolated,
    a bounded prefix slice of X is interpolated, and nothing in that same format
    states the remainder. All three halves are load-bearing:

    - **the count** — a bounded slice with no count beside it claims nothing, so
      `", ".join(drift[:3])` is a line this must stay quiet about. It is still a
      truncation, and a reader may still want the rest; it is not this defect,
      because nothing in it is untrue.
    - **the same collection** — `s[:12]` beside `len(trail["missing"])` is a SHA
      abbreviated for width, not evidence dropped from the set being counted.
    - **the remainder unstated** — `len(X) - n` anywhere in the same format is
      the repair, and `hooks/meter-usage.py` was written that way before this
      existed. A hook may not import `scripts/`, so it cannot reach `some_of()`
      and never will; reading the property rather than the wording is what keeps
      it correct instead of exempt.

    WHAT IT CANNOT SEE, in the same direction every scan in this file errs: a
    count and a slice that reach one sentence through two different format
    strings, a cap applied by a counting loop or by `islice` rather than by a
    slice, a truncated mapping, and any file outside `dirs` — `tools/` is not in
    the default, because the path to that directory already has two private homes
    and adding a third to widen a scope is a decision of its own. So a clean
    result means "none of this shape here", not "no truncated evidence".
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, HOOKS_DIR, TESTS_DIR, LINTS_DIR)
    violations = []
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                # house_style_violations already reports an unparseable file by
                # name; saying it twice adds noise, not information.
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.BinOp) \
                        or not isinstance(node.op, ast.Mod):
                    continue
                if not (isinstance(node.left, ast.Constant)
                        and isinstance(node.left.value, str)):
                    continue
                counted, sliced, stated = {}, {}, set()
                for operand in _mod_operands(node):
                    counted.update(_len_keys(operand))
                    sliced.update(_prefix_slice_keys(operand))
                    stated.update(_remainder_keys(operand))
                for key in sorted(counted):
                    if key in sliced and key not in stated:
                        violations.append((name, sliced[key],
                                           _TRUNCATED_EVIDENCE))
    return sorted(violations)


# --- a tool's output, cut at one end ------------------------------------------
# A refusal reason that quotes a subprocess's output cut the head off it, a failing
# step's print kept the tail, and each lost the line that named the failure for the
# tools that matter (a hook opens with a preamble, a test runner closes with a
# summary). `_excerpt` keeps both ends and the failure lines between them; this is
# the lint that stops the next site choosing an end again.
OUTPUT_RUNNERS = frozenset(("run_git", "_git", "_git_bytes", "run_verb",
                            "record_gate", "check_output", "communicate",
                            "run", "Popen"))
OUTPUT_STREAMS = frozenset(("stdout", "stderr"))
# Below this a head cut is an abbreviation (a SHA, an id), not a quotation.
OUTPUT_CUT_MIN = 40
# Files that still cut output head-only for a reason a row states. A row is a
# debt and not a permission: it is reported once the file holds no such cut, so
# the table cannot outlive its sites. It is empty, and stays so unless a site
# genuinely cannot reach `_excerpt`.
BARE_CUT_PENDING = ()
_BARE_OUTPUT_CUT = ("a head-only cut of a subprocess's output - it keeps whatever "
                    "the tool printed first and loses the line that names the "
                    "failure; quote it through _excerpt.excerpt()")


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _reads_output(expr):
    """True when `expr` contains a runner's call or a `.stdout` / `.stderr` read."""
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _call_name(node) in OUTPUT_RUNNERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in OUTPUT_STREAMS:
            return True
        if isinstance(node, ast.Call) and _call_name(node) == "getattr" \
                and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value in OUTPUT_STREAMS:
            return True
    return False


def _output_names(scope):
    """The names `scope` binds from a runner's result, nested functions excluded."""
    bound = set()
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Assign) and _reads_output(node.value):
            for target in node.targets:
                bound.update(n.id for n in ast.walk(target)
                             if isinstance(n, ast.Name))
        stack.extend(ast.iter_child_nodes(node))
    return bound


def _bare_cuts(scope, tainted):
    """`(line)` of every `X[:N]` in `scope` (nested functions excluded) whose X
    reads output, directly or through a name in `tainted`, with N a constant of
    at least OUTPUT_CUT_MIN."""
    hits = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))
        if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
            continue
        sl = node.slice
        if sl.lower is not None or sl.step is not None \
                or not isinstance(sl.upper, ast.Constant) \
                or not isinstance(sl.upper.value, int) \
                or sl.upper.value < OUTPUT_CUT_MIN:
            continue
        names = set(n.id for n in ast.walk(node.value) if isinstance(n, ast.Name))
        if _reads_output(node.value) or names & tainted:
            hits.append(node.lineno)
    return hits


def bare_output_cut_violations(dirs=None, pending=None):
    """(filename, line, what) for a head-only cut of a subprocess's output.

    THE SHAPE: a slice `X[:N]`, N a constant of at least `OUTPUT_CUT_MIN`, where X
    reads a `.stdout` / `.stderr` or a name bound in the same function from a call
    to one of `OUTPUT_RUNNERS` -- `(err or out).strip()[:200]` is the case that
    started this. Under the minimum a cut is an abbreviation (`sha[:12]`), not a
    quotation, and a title or a summary is not output at all.

    WHAT IT CANNOT SEE, in the direction every scan in this file errs: output that
    reaches a name through a parameter, a return value of a runner it does not
    list, an attribute of an object or a second assignment, a cut by `textwrap`
    or by a loop, and any file outside `dirs` -- `hooks/` is not in the default
    because a hook may not import `scripts/` and cannot reach `_excerpt`. So a
    clean result means "none of this shape here", not "no output is cut".
    """
    dirs = dirs if dirs is not None else (SCRIPTS_DIR, LINTS_DIR)
    pending = set(BARE_CUT_PENDING if pending is None else pending)
    violations, cut = [], set()
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                continue
            scopes = [tree] + [n for n in ast.walk(tree)
                               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for scope in scopes:
                for line in _bare_cuts(scope, _output_names(scope)):
                    cut.add(name)
                    if name not in pending:
                        violations.append((name, line, _BARE_OUTPUT_CUT))
    violations.extend((name, 0, "BARE_CUT_PENDING names a file that holds no "
                       "head-only cut of output any more - delete the row")
                      for name in sorted(pending) if name not in cut)
    return sorted(violations)


# --- text-mode writes name their newline ---------------------------------------
# A text-mode handle opened for writing translates "\n" to the platform's line
# ending, so on Windows a committed file comes out CRLF and differs byte for byte
# from the same document written on another machine. The writers of committed or
# byte-compared files pass `newline="\n"`; this lint finds the ones that do not.
NEWLINE_OPENERS = frozenset(("open", "fdopen"))
# Where `newline` sits positionally in each opener's signature.
_NEWLINE_POSITION = {"open": 4, "fdopen": 5}
# Files under scripts/ that still open a text handle for writing without naming
# the newline: {file: why it is not converted yet}. A row is a debt and not a
# permission: it is reported once the file holds no such open, so the table can
# only shrink. Everything the plan, its shards, the journal, evidence or a filed
# return is written through already names its newline.
NEWLINE_PENDING = ()
# The directories the lint walks: the plugin's scripts and its hooks, the two lint
# modules that used to be scripts, plus the repository's own project hooks when
# that directory exists (an installed copy of the plugin has no such sibling).
_PROJECT_HOOKS_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
NEWLINE_DIRS = (SCRIPTS_DIR, HOOKS_DIR, LINTS_DIR) + (
    (_PROJECT_HOOKS_DIR,) if os.path.isdir(_PROJECT_HOOKS_DIR) else ())
_NEWLINE_WRITE = ("a text-mode open for writing that names no `newline` - on "
                  "Windows it writes CRLF into a file other machines write "
                  "with LF; pass newline=\"\\n\"")


def _opener_name(call):
    """`open` / `fdopen` for `open(...)`, `io.open(...)` and `os.fdopen(...)`, else ''."""
    name = _call_name(call)
    return name if name in NEWLINE_OPENERS else ""


def _text_write_mode(call, opener):
    """True when `call` is a literal text-mode mode that writes, appends or creates."""
    mode = None
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if not isinstance(mode, str) or "b" in mode:
        return False
    return any(c in mode for c in "wax+")


def _names_newline(call, opener):
    if any(kw.arg == "newline" or kw.arg is None for kw in call.keywords):
        return True
    return len(call.args) > _NEWLINE_POSITION[opener]


def text_write_newline_violations(dirs=None, pending=None):
    """(filename, line, what) for a text-mode open for writing with no `newline`.

    THE SHAPE: `open(...)`, `io.open(...)` or `os.fdopen(...)` whose mode is a
    string literal naming a write, an append, an exclusive create or an update and
    no `b`, called without a `newline=` keyword (or a positional one). Files in
    `pending` are the debt: silenced while they hold such an open, reported once
    they hold none.

    WHAT IT CANNOT SEE: a mode that is not a literal, a handle opened through a
    wrapper, `Path.write_text` (which takes no newline argument before Python
    3.10 - the floor here is 3.8), `tempfile` handles, a `**kwargs` forward
    (read as naming one), and any file outside `dirs`, which defaults to
    `NEWLINE_DIRS`. So a clean result means "none of this shape here", not "no
    file is written with the wrong ending".
    """
    dirs = dirs if dirs is not None else NEWLINE_DIRS
    pending = set(NEWLINE_PENDING if pending is None else pending)
    violations, holding = [], set()
    for d in dirs:
        for name, path in lint_py_files(d):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=name)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                opener = _opener_name(node)
                if not opener or not _text_write_mode(node, opener) \
                        or _names_newline(node, opener):
                    continue
                holding.add(name)
                if name not in pending:
                    violations.append((name, node.lineno, _NEWLINE_WRITE))
    violations.extend((name, 0, "NEWLINE_PENDING names a file that holds no "
                       "newline-less text write any more - delete the row")
                      for name in sorted(pending) if name not in holding)
    return sorted(violations)


# --- text I/O names its encoding --------------------------------------------------
# A text handle or a text-mode subprocess that names no encoding reads and writes
# in the locale's, which is cp1252 on a Windows runner and ASCII under LC_ALL=C:
# neither spells what this plugin writes, so a reader thread raises on the first
# arrow a verb prints, or a file comes back as different text than went in. The
# fix at each site is to say UTF-8 and how to treat a byte that is not.
# Where each opener takes `encoding` positionally.
_ENCODING_POSITION = {"open": 3, "fdopen": 3, "read_text": 0, "write_text": 1}
# The subprocess entry points that decode their output when told to.
_TEXT_RUNNERS = frozenset(("run", "Popen", "check_output", "check_call", "call"))
# The keywords that put one of them in text mode.
_TEXT_SWITCHES = ("text", "universal_newlines", "errors")
# Files that still read or write text without naming the encoding: a row is a
# debt and not a permission, reported once its file holds no such site, so the
# table can only shrink.
ENCODING_PENDING = ()
# The newline rule's walk: scripts, the plugin's hooks, and the repository's
# own project hooks when that directory exists.
ENCODING_DIRS = NEWLINE_DIRS
_UNENCODED = {
    "open": "a text-mode open that names no encoding - it reads and writes in the "
            "locale's (cp1252 on Windows); pass encoding=\"utf-8\"",
    "path": "a Path text read or write that names no encoding - pass "
            "encoding=\"utf-8\"",
    "subprocess": "a text-mode subprocess that names no encoding - its output is "
                  "decoded in the locale's, and a reader thread raises on a byte "
                  "it cannot spell; pass encoding=\"utf-8\" and an errors policy",
    "decode": "a .decode() that names no codec - say which one, and how a byte "
              "that is not in it is treated",
}


def _keyword(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return kw
    return None


def _forwards_kwargs(call):
    return any(kw.arg is None for kw in call.keywords)


def _names_encoding(call, position):
    kw = _keyword(call, "encoding")
    if kw is not None:
        return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return len(call.args) > position


def _text_open_mode(call, opener):
    """True when `open` / `io.open` / `os.fdopen` is in text mode: a literal mode
    with no `b`, no mode at all, or one the lint cannot read - nothing says it
    is binary."""
    mode = call.args[1] if len(call.args) > 1 else None
    kw = _keyword(call, "mode")
    if kw is not None:
        mode = kw.value
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return "b" not in mode.value
    return True


def _is_text_opener(call):
    """`open` / `fdopen` for the builtin, `io.open` and `os.fdopen`; '' for
    `os.open` and any other object's `.open`, which return no text handle this
    lint can judge."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open"
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return ""
    if func.attr == "open" and func.value.id == "io":
        return "open"
    if func.attr == "fdopen" and func.value.id == "os":
        return "fdopen"
    return ""


def _text_switched(call):
    """True when a subprocess call names a text switch whose value is not the
    constant False or None."""
    for name in _TEXT_SWITCHES:
        kw = _keyword(call, name)
        if kw is None:
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value in (False, None):
            continue
        return True
    return False


def _unencoded_kind(call):
    """Which `_UNENCODED` shape `call` is, or ''."""
    if _forwards_kwargs(call):
        return ""
    opener = _is_text_opener(call)
    if opener:
        if _text_open_mode(call, opener) \
                and not _names_encoding(call, _ENCODING_POSITION[opener]):
            return "open"
        return ""
    name = _call_name(call)
    if name in ("read_text", "write_text") and isinstance(call.func, ast.Attribute):
        return "" if _names_encoding(call, _ENCODING_POSITION[name]) else "path"
    if name in _TEXT_RUNNERS and _text_switched(call) \
            and _keyword(call, "encoding") is None:
        return "subprocess"
    if name == "decode" and isinstance(call.func, ast.Attribute) \
            and not call.args and _keyword(call, "encoding") is None:
        return "decode"
    return ""


def unencoded_text_io(source, filename="<source>"):
    """Sorted `(line, what)` for every text I/O in `source` that names no
    encoding - the one walker both `text_encoding_violations` and any suite
    asking it of its own source run."""
    tree = ast.parse(source, filename=filename)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind = _unencoded_kind(node)
            if kind:
                found.append((node.lineno, _UNENCODED[kind]))
    return sorted(found)


def text_encoding_violations(dirs=None, pending=None):
    """(filename, line, what) for a text-mode open or subprocess call, or a
    decode, that names no encoding. `filename` is the walked directory's own
    name and the path under it - `scripts/git/integrate-task.py`, and
    `.claude/hooks/<file>` for the project hooks, which would otherwise read as
    the plugin's own `hooks/`.

    THE SHAPE: the builtin `open`, `io.open` or `os.fdopen` in a text mode (a
    literal with no `b`, no mode, or a mode it cannot read) without an
    `encoding` by keyword or position; a `.read_text()` / `.write_text()` without
    one; `run` / `Popen` / `check_output` / `check_call` / `call` given
    `text=`, `universal_newlines=` or `errors=` (any value but the constant
    False or None) without `encoding=`; and a `.decode()` with no codec, which
    is strict UTF-8 whatever the author meant. Files in `pending` are the debt.

    WHAT IT CANNOT SEE: a `**kwargs` forward (read as naming one), a
    `pathlib.Path.open` or any other object's `.open` (indistinguishable by
    name from an archive's or a browser's), `tempfile` handles opened in text
    mode, `os.popen`, an `.encode()` with no codec, a runner reached under
    another name, and any file outside `dirs`, which defaults to
    `ENCODING_DIRS`. So a clean result means "none of this shape here", not
    "every byte this plugin reads is decoded as UTF-8".

    WHY ONLY SHIPPED CODE: `ENCODING_DIRS` is `scripts/`, `hooks/` and
    `.claude/hooks/` - what runs on a user's machine - and stays that way. A
    test or a tool under `tests/` or `tools/` is not walked here; what one of
    them actually decodes is caught by the sweep's legacy-locale pass
    (`tools/sweep-selftests.py --encoding cp1252`), which runs each child under
    a legacy code page for stdio and - only where the pin gives a Windows-shaped
    environment, a non-UTF-8 preferred encoding with UTF-8 file names - a
    non-UTF-8 locale, printing which half ran, so a read with no encoding fails
    where it runs instead of being guessed at by name.
    """
    dirs = dirs if dirs is not None else ENCODING_DIRS
    pending = set(ENCODING_PENDING if pending is None else pending)
    violations, holding = [], set()
    for d in dirs:
        top = os.path.basename(os.path.normpath(d))
        if os.path.normpath(d) == os.path.normpath(_PROJECT_HOOKS_DIR):
            top = ".claude/hooks"
        for rel, path in lint_py_files(d):
            name = "%s/%s" % (top, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    found = unencoded_text_io(fh.read(), filename=rel)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            if found:
                holding.add(name)
            if name in pending:
                continue
            violations.extend((name, line, what) for line, what in found)
    violations.extend((name, 0, "ENCODING_PENDING names a file that holds no "
                       "unencoded text I/O any more - delete the row")
                      for name in sorted(pending) if name not in holding)
    return sorted(violations)


# --- a shell script finds its own directory on any spelling of $0 -------------
# `case "$0" in */*)` reads a Windows caller's backslash-only `$0` as "no
# directory", and `dirname "$0"` is handed the same string unchecked. The one
# idiom everywhere normalises separators first (see hooks/py-launch.sh).
_SH_SELF_DIR_SHAPES = (
    (r'\bcase\s+"?\$\{?0\}?"?\s+in\b',
     'case on "$0" - normalise the separators into a variable first and match that'),
    (r'\bdirname\s+"?\$\{?0\}?"?',
     'dirname of "$0" - it does not see a backslash separator'),
    (r'\$\{0[%#]',
     'a pattern cut of "$0" - cut the normalised copy instead'),
)
_SH_SKIP_DIRS = frozenset((".git", "node_modules", "__pycache__"))


def sh_self_dir_violations(root=None):
    """(relpath, line, what) for every `.sh` under `root` that works out its own
    directory from a raw `$0`.

    WHAT IT CANNOT SEE: a script that reaches `$0` through another variable
    (`me=$0`), a script that never works out its own directory, and any file that
    is not named `*.sh`. Comment lines are skipped, so a comment may name the
    pattern it explains.
    """
    import re                       # lazy: hooks import this module on every call
    root = root if root is not None else REPO_ROOT
    shapes = [(re.compile(p), what) for p, what in _SH_SELF_DIR_SHAPES]
    found = []
    for base, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SH_SKIP_DIRS)
        for fname in sorted(filenames):
            if not fname.endswith(".sh"):
                continue
            path = os.path.join(base, fname)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = posix_rel(path, root)
            for number, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                for pattern, what in shapes:
                    if pattern.search(line):
                        found.append((rel, number, what))
    return sorted(found)


# --- the raw JSON writer, by name only ----------------------------------------
# `_manifest_io.atomic_write_json` scrubs every string of machine paths before it
# writes, and that is the default because a rule each caller must remember is the
# rule the next caller does not know about. The writer that does NOT scrub is
# reached only from the sites below, each with the reason its bytes must stay as
# given. `_manifest_io` defines it and may call it anywhere.
RAW_JSON_WRITER = "raw_atomic_write_json"
RAW_JSON_WRITER_HOME = "scripts/manifest/_manifest_io.py"
# (file, innermost function, reason). A row is a statement about code that
# EXISTS: one whose site no longer names the raw writer is reported, so the table
# cannot carry permission for a site nobody wrote.
RAW_JSON_WRITERS = (
    ("scripts/manifest/migrate-json-encoding.py", "_locked_migrate",
     "it changes a document's escaping and nothing else; its dry run promised "
     "exactly that diff, and a scrub would add changes nobody was shown."),
    ("scripts/panel/_panel_write.py", "write_config",
     "the user's own settings, not a record the plugin composed: a typed "
     "machine path is refused at the door, and one already on disk is the "
     "user's to change, not this save's."),
    ("scripts/panel/_panel_write.py", "write_theme",
     "a theme file is the user's own settings, written as they set them."),
)


def _raw_writer_references(tree):
    """`(line, innermost function or "<module>")` for every reference to
    `RAW_JSON_WRITER` - a call, an attribute read or a bare name. A REFERENCE and
    not only a call, because `raw = _mio.raw_atomic_write_json` followed by
    `raw(...)` is the same write under a name no call-only scan would read."""
    found = []

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            inner = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = child.name
            named = (isinstance(child, ast.Attribute)
                     and child.attr == RAW_JSON_WRITER) \
                or (isinstance(child, ast.Name) and child.id == RAW_JSON_WRITER)
            if named:
                found.append((child.lineno, where))
            visit(child, inner)

    visit(tree, "<module>")
    return found


def raw_json_writer_violations(script_dir=None, hooks_dir=None, table=None):
    """(file, what) for every reach of the raw JSON writer the table does not
    name, and every table row naming a site that no longer reaches it.

    THE INVARIANT, NOT A LIST OF CALLERS. Scrubbing was added to a plan's
    savers one writer at a time, and the CLI's single writer behind every
    verb went on writing the checkout's absolute root into shards because it
    reached the low-level writer directly. Moving the scrub INTO that writer
    closes the class; this lint is what keeps the unscrubbed path from being
    re-opened by a new caller who wanted the old behaviour.

    A tree in which nothing defines the raw writer is reported as BLIND, not
    clean: a rule about one function has nothing to say when it is gone.

    WHAT IT CANNOT SEE: a write that skips both writers (`json.dump` to an open
    file, `atomic_write_text` of a hand-built document). Those carry their
    own rules - `_deps.json_encoding_violations()` and the state-write lint -
    and a clean result here means "nothing reaches the raw writer unnamed"."""
    script_dir = script_dir or SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else HOOKS_DIR
    table = RAW_JSON_WRITERS if table is None else table
    allowed = set((f, fn) for f, fn, _why in table)
    seen = set()
    violations = []
    defined = False
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)):
        if not directory or not os.path.isdir(directory):
            continue
        for rel, path in lint_py_files(directory):
            named = "%s/%s" % (kind, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
            except (OSError, SyntaxError):
                continue
            if named == RAW_JSON_WRITER_HOME:
                defined = defined or any(
                    isinstance(n, ast.FunctionDef) and n.name == RAW_JSON_WRITER
                    for n in ast.walk(tree))
                continue
            for line, where in _raw_writer_references(tree):
                seen.add((named, where))
                if (named, where) not in allowed:
                    violations.append(
                        (named, "line %d (%s): reaches %s, the writer that does "
                                "not scrub machine paths - call "
                                "atomic_write_json, or add a RAW_JSON_WRITERS "
                                "row saying why these bytes must stay as given"
                         % (line, where, RAW_JSON_WRITER)))
    for f, fn, _why in table:
        if (f, fn) not in seen:
            violations.append((f, "RAW_JSON_WRITERS names %s, which no longer "
                                  "reaches %s - drop the row"
                               % (fn, RAW_JSON_WRITER)))
    if not defined:
        violations.append(("<tree>", "%s does not define %s - this rule is "
                                     "blind, not clean"
                           % (RAW_JSON_WRITER_HOME, RAW_JSON_WRITER)))
    return sorted(violations)


# --- the returns writer, by name only ------------------------------------------
# A filed return is committed under `<evidence>/returns`, and it is composed by
# an agent and by the stamp helper, so it can carry any machine's path. The
# scrub is `_filed_returns.file_once`'s, and the rule below keeps it the only
# route: a function that BUILDS a return's path and WRITES a file is a second
# route unless it is the home module.
RETURNS_WRITER_HOME = "scripts/manifest/_filed_returns.py"
RETURNS_WRITER = "file_once"
RETURNS_SCRUBS = ("scrubbed_values", "scrubbed_return_text")
RETURN_PATH_BUILDERS = ("return_path", "return_rel", "phase_return_rel")
_FILE_WRITE_ATTRS = ("write_text", "write_bytes", "atomic_write_text",
                     "atomic_write_json", "raw_atomic_write_json", "dump")


def _called_name(node):
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)


def _opens_for_writing(node):
    """Whether a Call is `open(path, "<a mode that writes>")`."""
    if _called_name(node) != "open":
        return False
    modes = [a for a in node.args[1:2]] + [k.value for k in node.keywords
                                           if k.arg == "mode"]
    return any(isinstance(m, ast.Constant) and isinstance(m.value, str)
               and any(c in m.value for c in "wxa+") for m in modes)


def _returns_writes_by_function(tree):
    """`{function: (path-builder line or 0, write line or 0)}` for every
    function (innermost) that names a return-path builder and/or writes."""
    found = {}

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else where
            built, wrote = found.get(where, (0, 0))
            name = (child.attr if isinstance(child, ast.Attribute) else
                    child.id if isinstance(child, ast.Name) else None)
            if name in RETURN_PATH_BUILDERS and not built:
                built = child.lineno
            if isinstance(child, ast.Call) and not wrote and (
                    _opens_for_writing(child)
                    or _called_name(child) in _FILE_WRITE_ATTRS):
                wrote = child.lineno
            if built or wrote:
                found[where] = (built, wrote)
            visit(child, inner)

    visit(tree, "<module>")
    return found


def returns_writer_violations(script_dir=None):
    """(file, what) for every function that builds a filed return's path and
    writes a file itself, and for a home writer that no longer scrubs.

    THE INVARIANT, NOT A LIST OF CALLERS. Plan shards were scrubbed one saver at
    a time and the returns - committed beside them - were not, which is the same
    defect a third time. The scrub is moved into `file_once`; this keeps a new
    caller from writing a return some other way.

    A tree without the home module is BLIND, not clean. WHAT IT CANNOT SEE: a
    path assembled without a builder (`os.path.join(evidence, "returns", ...)`);
    those spell the directory name, which `_filed_returns` owns."""
    script_dir = script_dir or SCRIPTS_DIR
    violations = []
    home_seen = False
    for rel, path in lint_py_files(script_dir):
        named = "scripts/%s" % rel
        try:
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (OSError, SyntaxError):
            continue
        if named == RETURNS_WRITER_HOME:
            home_seen = True
            scrubbing = any(
                isinstance(fn, ast.FunctionDef) and fn.name == RETURNS_WRITER
                and any(isinstance(n, ast.Name) and n.id in RETURNS_SCRUBS
                        for n in ast.walk(fn))
                for fn in ast.walk(tree))
            if not scrubbing:
                violations.append((named, "%s no longer calls the scrub (%s) - "
                                          "a committed return would carry machine "
                                          "paths" % (RETURNS_WRITER,
                                                     "/".join(RETURNS_SCRUBS))))
            continue
        for where, (built, wrote) in sorted(_returns_writes_by_function(tree).items()):
            if built and wrote:
                violations.append((named, "line %d (%s): builds a filed return's "
                                          "path and writes a file itself - file "
                                          "it through %s, which scrubs machine "
                                          "paths" % (wrote, where, RETURNS_WRITER)))
    if not home_seen:
        violations.append(("<tree>", "%s is missing - this rule is blind, not "
                                     "clean" % (RETURNS_WRITER_HOME,)))
    return sorted(violations)


# --- a timestamp ordered as text ------------------------------------------------
# A row's `ts` is ordered by the MOMENT it names - `_evidence_io.oldest_first`,
# `newest_row` and `stamp_moment` on the ledger, `_journal_io.row_moment` on the
# trail - because text orders a stamp by its spelling: `10:30+02:00` sorts after
# `09:30Z` though it is an hour earlier, and `09:30:00.5Z` before `09:30:00Z`.
TS_FIELD = "ts"
_ORDERING_CALLS = ("sorted", "max", "min", "sort")
_ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
# (file, innermost function, reason) - a site allowed to order `ts` as text. A
# row is a statement about code that EXISTS: one whose site no longer does is
# reported. `tools/gate-parity.py`'s `AUDITED_EXEMPTIONS` classifies this table.
TS_ORDER_SITES = ()


def _is_ts_text(node):
    """Whether `node` IS a `ts` field's value, read as it stands: `x["ts"]` or
    `x.get("ts", ...)`, also wrapped in `str(...)` or `... or default`. A value
    computed FROM it - `stamp_moment(x.get("ts"))` - is not: that is the moment
    the stamp names, which is what an order should be taken over."""
    if isinstance(node, ast.Call) and _called_name(node) == "str" \
            and len(node.args) == 1:
        return _is_ts_text(node.args[0])
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _is_ts_text(node.values[0])
    if isinstance(node, ast.Subscript):
        key = node.slice
        key = getattr(key, "value", key) if type(key).__name__ == "Index" else key
        return isinstance(key, ast.Constant) and key.value == TS_FIELD
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        first = node.args[0]
        return isinstance(first, ast.Constant) and first.value == TS_FIELD
    return False


def _ordered_by_ts(expr):
    """Whether the values `expr` orders are a `ts` field's text: the element of
    a comprehension, each branch of an `or`, each member of a tuple key, or the
    expression itself. A comprehension's FILTER orders nothing and is not read."""
    if isinstance(expr, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
        return _ordered_by_ts(expr.elt)
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        return any(_ordered_by_ts(v) for v in expr.values)
    if isinstance(expr, (ast.Tuple, ast.List)):
        return any(_ordered_by_ts(e) for e in expr.elts)
    if isinstance(expr, ast.Lambda):
        return _ordered_by_ts(expr.body)
    if isinstance(expr, ast.Call) and _called_name(expr) == "itemgetter":
        return any(isinstance(a, ast.Constant) and a.value == TS_FIELD
                   for a in expr.args)
    return _is_ts_text(expr)


def _ts_text_orders(tree):
    """`(line, innermost function or "<module>", what)` for every order taken
    over a `ts` field's text in one parsed module."""
    found = []

    def judge(node, where):
        if isinstance(node, ast.Call) and _called_name(node) in _ORDERING_CALLS:
            keyed = [k.value for k in node.keywords if k.arg == "key"]
            if any(_ordered_by_ts(k) for k in keyed):
                found.append((node.lineno, where, "%s() keyed on a ts field's "
                              "text" % (_called_name(node),)))
            elif _called_name(node) != "sort" and not keyed \
                    and any(_ordered_by_ts(a) for a in node.args):
                found.append((node.lineno, where, "%s() over ts fields' text"
                              % (_called_name(node),)))
        elif isinstance(node, ast.Compare) \
                and any(isinstance(op, _ORDERING_OPS) for op in node.ops) \
                and any(_is_ts_text(side)
                        for side in [node.left] + list(node.comparators)):
            found.append((node.lineno, where, "an ordering comparison on a ts "
                                              "field's text"))

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            inner = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inner = child.name
            judge(child, where)
            visit(child, inner)

    visit(tree, "<module>")
    return found


def ts_order_violations(script_dir=None, hooks_dir=None, table=None):
    """(file, what) for every `sorted`/`max`/`min`/`.sort` keyed on - or taken
    over - a `ts` field's text, and every `<`/`<=`/`>`/`>=` with one as an
    operand, at a site `TS_ORDER_SITES` does not name; and every table row
    whose site no longer does.

    THE INVARIANT, NOT A LIST OF READERS. Text order and time order agree only
    while every writer spells a stamp the same way, and the readers that relied
    on it were found one at a time - a newest red row, a full run's age, a
    report's run list, a watermark, the journal's read order and its merge.
    Routing them through one moment reader closes the class; this lint keeps a
    new reader from re-opening it.

    QUIET ON THE MOMENT READERS BY CONSTRUCTION, with no table row: an order
    over `stamp_moment(r.get("ts"))` is an order over a number, and a `ts` read
    that orders nothing (a filter, an equality, a label) is not an order.

    WHAT IT CANNOT SEE: a stamp bound to a name first and ordered later
    (`stamps.append(r["ts"])` then `min(stamps)`), a field holding a stamp under
    another name (`completedAt`, `startedAt`), and an order taken by a helper
    whose own body never names `ts`. A clean result means "no order is taken
    over a `ts` field read in place"."""
    script_dir = script_dir or SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else HOOKS_DIR
    table = TS_ORDER_SITES if table is None else table
    allowed = set((f, fn) for f, fn, _why in table)
    seen = set()
    violations = []
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)):
        if not directory or not os.path.isdir(directory):
            continue
        for rel, path in lint_py_files(directory):
            named = "%s/%s" % (kind, rel)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
            except (OSError, SyntaxError):
                continue
            for line, where, what in _ts_text_orders(tree):
                seen.add((named, where))
                if (named, where) in allowed:
                    continue
                violations.append(
                    (named, "line %d (%s): %s - order by the moment it names "
                            "(_evidence_io.oldest_first / newest_row / "
                            "stamp_moment, _journal_io.row_moment), or add a "
                            "TS_ORDER_SITES row saying why text order is right "
                            "here" % (line, where, what)))
    for f, fn, _why in table:
        if (f, fn) not in seen:
            violations.append((f, "TS_ORDER_SITES names %s, which no longer "
                                  "orders a ts field's text - drop the row"
                               % (fn,)))
    return sorted(violations)


# --- selftest coverage --------------------------------------------------------
# THE RULE: every module the repository carries without a suite of its own - the
# shipped `.py` under `scripts/` and `hooks/`, and the development modules whose
# cases live in `tests/` - has `tests/test_<name>.py`, or a NAMED exemption saying
# why it has none. Nothing here returns a boolean: every module is placed in exactly
# one class and the caller asserts the classes, so a green answer names what it
# looked at (`total`) instead of reading the same as "looked at nothing".
#
# THERE IS NO "MIGRATED" CLASS ANY MORE. While the cases moved out of the modules
# they test, a module could carry its own suite or point at `tests/`, and this told
# the two apart by reading a file's string constants for the contract line. Shipped
# modules no longer answer `--selftest` at all, so nothing is left to tell apart and
# the question reduces to the one that stays true: is there a test file for it.

_TEST_PREFIX = "test_"

# A module with no `tests/test_<name>.py` and a reason for it: `{named: reason}`,
# `named` being the kind-prefixed path this classifier reports (`scripts/x.py`). A
# row is a debt with its cause written down. A row naming a module that does not
# exist, or one that has a test file after all, is a finding (`stale_exempt`), so the
# table cannot outlive its premise.
COVERAGE_EXEMPT = {}

# The development modules, outside `scripts/` and `hooks/`, whose cases live in
# `tests/`. A DIRECTORY is named for `tools/lints/` and `tools/demo/`; a single FILE
# is named for the two benchmarks, because the rest of `tools/` carries its own
# suites and the sweep runs those.
DEV_DIRS = (("lints", LINTS_DIR),
            ("demo", os.path.join(REPO_ROOT, "tools", "demo")))
DEV_FILES = (("tools", os.path.join(REPO_ROOT, "tools", "_usage_bench.py")),
             ("tools", os.path.join(REPO_ROOT, "tools", "bench-report.py")))

# The classes a build must be empty of. Named once, here, rather than re-spelled as a
# tuple of keys at each call site.
_DEFECT_CLASSES = ("uncovered", "stale_exempt", "orphans", "collisions")


def _test_name_for(rel):
    """The `tests/` filename that covers the module `rel`.

    Hyphens become underscores because a hyphenated name is not importable and never
    will be: `import test_migrate-manifest` is a syntax error, so the entry points -
    which are hyphenated BY CONVENTION here, to mark a thing something invokes - could
    not otherwise have a test module at all. Stated in code, in one place, because the
    sweep and the guide both need the same answer.
    """
    return "%s%s.py" % (_TEST_PREFIX,
                        os.path.splitext(os.path.basename(rel))[0]
                        .replace("-", "_"))


def _coverable_test_names(directory):
    """Every `tests/` filename some file under `directory` could be covered by.

    EXTENSION-AGNOSTIC: whether a `tests/test_*.py` is an ORPHAN asks whether the
    test names anything the plugin ships, and `py-launch.sh` is shipped, runs ahead of
    every hook on every tool call, and has cases. Reading `.py` only would have called
    those cases dead weight. A file here is therefore ALLOWED a suite and never
    REQUIRED one - `uncovered` stays a question about Python modules.
    """
    names = set()
    for root, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for fname in filenames:
            names.add(_test_name_for(posix_rel(os.path.join(root, fname),
                                               directory)))
    return names


def selftest_coverage(script_dir=None, hooks_dir=None, tests_dir=None,
                      dev_dirs=None, dev_files=None, exempt=None):
    """Where every module's cases live right now - a classification, not a verdict.

    Returns a dict of sorted lists, keyed by what is true of a module:

      covered      `tests/test_<name>.py` exists - the clean class
      exempt       no test file, and `COVERAGE_EXEMPT` names it: listed so a review
                   can read the debts, and not a defect while the reason stands
      uncovered    DEFECT: no test file and no exemption - the module nobody tests
      stale_exempt DEFECT: an exemption naming a module that does not exist, or one
                   that has a test file after all
      orphans      DEFECT: a `tests/test_*.py` naming no module that exists. Asked of
                   every file under `scripts/` and `hooks/` WHATEVER its extension,
                   unlike the other classes - `_coverable_test_names` says why
      collisions   DEFECT: two modules mapping to one test name (`a-b.py` and `a_b.py`
                   both want `test_a_b.py`)
      defects      every name in every defect class above, each tagged with the class
                   it fell into, so a caller asserts ONE thing and a failure names
                   the file rather than only a count
      total        how many modules were classified, so "no defects" and "nothing was
                   looked at" cannot print the same way

    Names are kind-prefixed (`scripts/_cli_fmt.py`, `hooks/remind-tdd.py`,
    `lints/_deps.py`, `demo/gen-demo-usage.py`, `tools/bench-report.py`) so a finding
    names a path the reader can open; orphans are named `tests/x.py`.
    `tests/_harness.py` is not a test file and is not an orphan candidate: the rule is
    about `test_*.py`, and the harness is the thing they all import.

    A caller handing in its own `script_dir` is classifying a fixture, and the real
    development modules must not leak into the fixture's answer: `dev_dirs`,
    `dev_files` and `exempt` default to the real ones only when the real `scripts/`
    is the subject.
    """
    real = script_dir is None
    dev_dirs = dev_dirs if dev_dirs is not None else (DEV_DIRS if real else ())
    dev_files = dev_files if dev_files is not None else (DEV_FILES if real else ())
    exempt = exempt if exempt is not None else (COVERAGE_EXEMPT if real else {})
    script_dir = script_dir or SCRIPTS_DIR
    hooks_dir = hooks_dir if hooks_dir is not None else HOOKS_DIR
    tests_dir = tests_dir if tests_dir is not None else TESTS_DIR

    test_files = set(rel for rel, _path in lint_py_files(tests_dir)
                     if os.path.basename(rel).startswith(_TEST_PREFIX))

    out = {"covered": [], "exempt": [], "uncovered": [], "stale_exempt": [],
           "orphans": [], "collisions": [], "defects": [], "total": 0}
    claimed = {}
    modules = []
    for kind, directory in (("scripts", script_dir), ("hooks", hooks_dir)) + tuple(dev_dirs):
        if directory is None or not os.path.isdir(directory):
            continue
        modules.extend(("%s/%s" % (kind, rel), rel)
                       for rel, _path in lint_py_files(directory))
    for kind, path in dev_files:
        if os.path.isfile(path):
            modules.append(("%s/%s" % (kind, os.path.basename(path)),
                            os.path.basename(path)))
    for named, rel in modules:
        out["total"] += 1
        expected = _test_name_for(rel)
        claimed.setdefault(expected, []).append(named)
        if expected in test_files:
            out["covered"].append(named)
        elif named in exempt:
            out["exempt"].append(named)
        else:
            out["uncovered"].append(named)
    present = set(named for named, _rel in modules)
    for named in sorted(exempt):
        if named not in present:
            out["stale_exempt"].append("%s (no such module)" % named)
        elif named in out["covered"]:
            out["stale_exempt"].append("%s (has a test file)" % named)

    coverable = set(claimed)
    for directory in (script_dir, hooks_dir) + tuple(d for _k, d in dev_dirs):
        if directory is not None and os.path.isdir(directory):
            coverable |= _coverable_test_names(directory)
    for name in sorted(test_files - coverable):
        out["orphans"].append("tests/%s" % name)
    for expected in sorted(claimed):
        if len(claimed[expected]) > 1:
            out["collisions"].append("tests/%s <- %s"
                                     % (expected, ", ".join(sorted(claimed[expected]))))
    for key in ("covered", "exempt", "uncovered"):
        out[key].sort()
    out["defects"] = ["%s %s" % (cls, name)
                      for cls in _DEFECT_CLASSES for name in out[cls]]
    return out


def suite_elsewhere_paths(repo_root=None):
    """Repo-relative paths of the development modules whose cases live in `tests/`,
    which the sweep must not run with `--selftest`, because they answer none.

    The shipped modules are not listed here: the sweep does not walk `scripts/` or
    `hooks/` at all, since `selftest_coverage()` already accounts for every one of
    them.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    out = []
    for _kind, real_dir in DEV_DIRS:
        # `DEV_DIRS` and `DEV_FILES` are absolute under THIS repo. Re-rooting each
        # at `root` before walking keeps every relpath between two paths under
        # `root`: relpath-ing this repo's paths against a fixture root raises
        # across drives on Windows and returns `../` climbs on posix.
        directory = os.path.join(root, posix_rel(real_dir, REPO_ROOT))
        if os.path.isdir(directory):
            out.extend(posix_rel(path, root) for _rel, path in lint_py_files(directory))
    for _kind, real_path in DEV_FILES:
        path = os.path.join(root, posix_rel(real_path, REPO_ROOT))
        if os.path.isfile(path):
            out.append(posix_rel(path, root))
    return sorted(out)


# --- numbers written into prose -----------------------------------------------

# NO REGEX ON PURPOSE. This module is the anchor every other `.py` imports, and
# it deliberately carries only `ast`, `os` and `sys`; adding `re` here would put
# a compile on the import path of every hook that must start fast on every tool
# call. Word scanning is enough for shapes this narrow, and it is faster.
#
# The shapes below are PRESENT-TENSE claims. Historical prose ("down from the
# seventeen", "it stood at 70 that day") stays writable on purpose: the past
# tense is how a decision record explains itself, and forbidding it would push
# the rot into vaguer wording rather than removing it.
#
# FOUR FAMILIES, EACH ADOPTED ONLY AFTER MEASURING ITS SITES AND HOW MANY WERE
# ALREADY WRONG. An extension that fires on forty correct lines is worse than no
# extension: it gets routed around, and then it is its own defect class.
#
#   cardinality  "its N cases", "N cases live in", "--selftest (N cases)"
#                51 sites when adopted, 9 already wrong.
#   persistence  "`NAME` stayed at N", "`NAME` is still N" - a claim that a
#                number HAS NOT CHANGED as of writing. 2 sites, BOTH wrong
#                (`KNOWN_LAYER_DEBT` written as 17 twice against a real 1,
#                once in each of two separate documents).
#   completeness "all N of them", "all N ... have/are" - a claim that a
#                collection's whole is N. 2 sites beyond the first shape, BOTH
#                wrong (48 against a real 83).
#   ratio        "N of M <noun>" - the tally a command prints, quoted with no
#                command beside it. Adopted after reading every hit the
#                unbounded reading produced over this whole tree: the one real
#                claim it left was `.claude/skills/writing-css/SKILL.md`'s
#                declaration count, and every other hit was a rendered tally or
#                a measurement anchored to a past run. `_ratio_claim()` carries
#                each narrowing beside the class of line that bought it.
#
# THREE MORE WERE SURVEYED AND REFUSED - a measurement family, a before/after
# family, and the bare `the N <noun>` with an ordinary noun - and what each survey
# found is in `prose_number_claims()`'s list of what this cannot see, beside the
# other gaps, because a refusal is only useful to the next author if it is filed
# where they will look for the shape.
#
# WHY EVERY ONE OF THEM TAKES "REMOVE THE NUMBER" AND NOT "REQUIRE THE BASIS".
# Both remedies satisfy the house rule on paper. What separated them was a
# measurement taken the day this was written: `CONTRIBUTING.md`'s files-over-500
# figure DOES name its basis -- `tools/count-ui-pins.py`, a command that really
# does print that number -- and it had rotted anyway, in both of its halves (it
# read 21 where the tool printed 22, and named `_deps.py` at 1,479 lines where
# the file held 1,621). A basis makes a claim CHECKABLE; only deleting the
# number makes it un-rottable, because nothing runs a command on a reader's
# behalf. So the basis stays the escape hatch for a number a reader genuinely
# acts on, and is not the remedy of choice for one that restates a live source.
_CASE_WORDS = ("cases", "case")


# --- a numeral, in either spelling ------------------------------------------------
# A count SPELLED OUT is the same claim as a count in digits, so it is read by the
# shapes above rather than by a grammar of its own. THE TABLE'S OMISSIONS ARE THE
# DESIGN. A bare number-word is not a claim, it is English, and the shapes are all
# that separates the two.
#
# WHERE THE BOUNDARY CAME FROM, and it is a measurement rather than taste. With the
# small words admitted as well, this lint and `_deps.doc_prose_numbers()` between
# them reported nineteen sites across `hooks/`, `scripts/` and the three prose
# documents on the day this landed - every one of them below `ten`, and only two were
# the defect. Of the rest: thirteen were an ANAPHOR pointing at an enumeration the
# reader can see in the same breath ("all three are honest about what they are:",
# and the three are the next lines), which is a number carrying its own basis; one
# was a RATE, one a UNIQUENESS claim whose sentence dies if the word goes, one a
# COUNTERFACTUAL about cases that do not exist, and one a noun compound the shape
# misread. Sixteen good sentences would have had to be rewritten to catch two
# marginal ones, and the pressure after that is to loosen a shape.
#
# At `ten` and above the same run reported four sites, and three had already rotted -
# two spellings of a check count that had grown by three, and a file count that had
# doubled. That is the hit rate the earlier families were adopted on.
#
# So the band under `ten` is an UNDER-count, and it is documented as one rather than
# closed. Widening it is the repair to refuse: a pattern loosened to admit prose
# stops catching the thing it exists for, and the case that would have noticed is
# the one being changed.
_NUMERAL_TENS = ("twenty", "thirty", "forty", "fifty", "sixty", "seventy",
                 "eighty", "ninety")

# Read ONLY as the tail of a tens word, never on its own. A hyphenated compound is
# punctuation `_words()` has already dropped, so a tens word and its tail arrive as
# two tokens; without this the compounds this tree really writes would read as a
# number followed by an unrelated word and slip every shape.
_NUMERAL_TAILS = ("one", "two", "three", "four", "five", "six", "seven",
                  "eight", "nine")

_NUMERAL_WORDS = ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                  "sixteen", "seventeen", "eighteen", "nineteen",
                  "hundred", "thousand") + _NUMERAL_TENS

# NOT the same table as `config/_help._COUNT_WORDS`, and merging them would break
# both. That one RESOLVES a word to a number by its index, against a phrase a regex
# has already pinned, so it needs exactly the small words this one leaves out. This
# one RECOGNISES a numeral in arbitrary prose, where those same words are ambiguous.
# A single table serving both would have to be ordered and complete, which is the
# widening the second-direction case exists to stop.


def _numeral_span(w, i, small=False):
    """`(text, index past it)` if a numeral starts at `w[i]`, else None.

    ONE entry point for both spellings, so no shape can end up reading a digit and
    a word by different rules. Returns the text rather than the value: the finding
    quotes the claim back, and nothing here compares magnitudes.

    `small` admits a BARE `_NUMERAL_TAILS` word - `five` standing on its own
    rather than as the tail of `twenty-five`. It is the same table read one way
    further, and it is what keeps the rule that a shape added later must read
    both spellings THROUGH HERE and must not grow a numeral reader of its own.

    IT IS OFF BY DEFAULT, AND THE DEFAULT IS THE MEASUREMENT. Switched on for
    the families that read a bare noun, it reported over a hundred sites across
    this tree the day it was written, and reading them is the argument: `all
    three are honest about what they are`, `one case`, `two cases wearing one
    name`. Under `ten` the word is ordinary English machinery, so a shape may
    ask for it ONLY where the shape itself supplies the bound - `N of M <noun>`
    is bounded by its `of`, and a bare noun is bounded by nothing.
    """
    tok = w[i]
    if tok.isdigit():
        return (tok, i + 1)
    if small and tok in _NUMERAL_TAILS:
        return (tok, i + 1)
    if tok not in _NUMERAL_WORDS:
        return None
    if tok in _NUMERAL_TENS and w[i + 1:i + 2] and w[i + 1] in _NUMERAL_TAILS:
        return ("%s-%s" % (tok, w[i + 1]), i + 2)
    return (tok, i + 1)

# Token sequences that assert a number has not changed AS OF WRITING. The past
# tense of `stayed`/`remained` is not what makes them history: "it stayed at N"
# with no anchor to a past moment means "and it is N now", which is why
# `_deps.py`'s own persistence note classifies exactly that spelling as the defect.
# `was still N` and `stood at N` are deliberately absent - those ARE anchored to
# a past moment, and `pn4` pins them as writable.
#
# EVERY EXAMPLE IN THIS SECTION SPELLS ITS NUMBER `N` ON PURPOSE. A lint that
# scans the tree it lives in must not plant its own needle there - `_refs.py`
# learned it with fixture paths and this module learned it twice on its own
# first run. A real digit in an example below is a real finding, and exempting
# the file would be the wrong repair.
_PERSISTS = (
    ("unchanged", "at"),
    ("remained", "at"),
    ("remains", "at"),
    ("remain", "at"),
    ("stayed", "at"),
    ("staying", "at"),
    ("stays", "at"),
    ("is", "still"),
    ("are", "still"),
    ("remains",),
)

# A completeness claim is present-tense only when it carries one of these.
# "all N files CARRIED their own copy" is a sentence about the world before a
# migration and stays writable; "all N files HAVE moved" is a claim about now.
# A whitelist of auxiliaries is the only half of that distinction a word scanner
# can make honestly - there is no way to recognise an arbitrary past-tense verb
# without a lexicon, so the miss is documented rather than guessed at.
_PRESENT_AUX = ("is", "are", "has", "have")

_BASIS_MARKERS = ("python3", "grep", "for f in")


# A separator that stays INSIDE a token when digits flank it. Nothing else survives
# tokenizing, and the two characters are chosen rather than guessed: one makes a
# ratio, the other a decimal.
_NUMBER_SEPARATORS = "./"


def _is_digit_char(ch):
    """One CHARACTER, is it a digit - the tokenizer's question, not the shapes'.

    Named so that the two questions cannot be confused for one. `_numeral_span()`
    asks whether a TOKEN is a numeral and is the single entry point every shape
    reads its number through; this asks whether a character may hold a separator
    inside a token, which happens before any shape sees anything. A case counts
    both occurrences and would go red on a third, so a family added later cannot
    quietly grow a numeral reader of its own out of a character test.
    """
    return ch.isdigit()


def _words(line):
    """`line` as lowercase alphanumeric tokens - except a separator INSIDE a number.

    `7/7` and `0.01` come back as ONE token each rather than as two numerals, and a
    token carrying a separator is not a numeral to `_numeral_span()`. That is the
    whole rule, and it is a NARROWING adopted when the scan below stopped being
    scoped to `scripts/`: a ratio is a tally and a decimal is a measurement, and
    neither is a count of things.

    THE MEASUREMENT THAT BOUGHT IT. The tally this whole tree prints - the
    `<passed>/<total>` line every suite ends with - appears outside `scripts/` as a
    fixture, as a regex and as an asserted literal, in the sweep runner, the test
    harness and half a dozen suites. Not one of those is a claim about how many
    cases exist, and none of them can be reworded away: the bytes ARE the contract
    CI greps for. Without this rule the widened scan reported every one of them.

    WHAT IT GIVES UP, said rather than left to be found: a cardinality genuinely
    written as a fraction stops being read. Nobody writes one that way, and the
    direction is an under-count - the direction `prose_number_claims()` already
    documents as the only one these shapes can be wrong in.

    AN UNDERSCORE INSIDE A WORD IS THE SAME NARROWING, one character further. An
    identifier is one word, which is a fact about TEXT and not about Python - so
    this does not teach the scanner to read code, it stops it splitting a name into
    pieces that were never written. Without it a numeric index in front of
    `case_id(` yielded a numeral and the noun `case`, and the line reported itself
    as a cardinality claim with no prose on it at all. Measured across the derived
    set and three tree states before adopting: it removes exactly that hit and
    loses nothing.

    A THOUSANDS COMMA IS DELIBERATELY NOT HERE. A grouped number is still a count,
    so the comma keeps being dropped, which leaves two numerals and lets the second
    one keep whatever noun follows it. That is how a line pairing a line count with
    a case count still reports its live half.

    THE WALK ITSELF IS `_tokenize()`, which answers this question and the sentence
    question in one pass. This name stays the contract every shape reads and the
    cases pin.
    """
    return _tokenize(line)["words"]


# A sentence terminator, and it is read as one only where the character after it is
# not alphanumeric - which is what keeps `x.py has` one sentence while `x.py. Next`
# is two, with no table of abbreviations and no lookahead past one character.
_SENTENCE_ENDS = ".!?"


def _in_dot_run(text, i):
    """True if `text[i]` is one stop of an ellipsis rather than a sentence end.

    A run of stops is a MARKUP elision here, not a full stop - the panel's own
    docstring writes a tag pair with the body elided, and reading each stop as a
    boundary cut that one sentence into four, which threw away the past tense the
    sentence opened with and reported its history as a claim.
    """
    before = text[i - 1:i] if i else ""
    return text[i] == "." and "." in (before, text[i + 1:i + 2])


# MEMOISED, AND THE SIZE IS THE POINT. The prose scan tokenizes every line of every
# file it keeps, and it tokenizes each one more than once: as itself, again inside
# `_historical_sentences`, and again as the `preceding` of the next line and the
# `following` of the one before. Profiled with `cProfile`, that was the single
# hottest function in `tests/test__output.py --selftest`, entered several hundred
# thousand times for a few tens of thousands of distinct lines. The repeats are
# ADJACENT calls on the same string, so a small LRU catches nearly all of them
# while holding a few thousand short lists at most - an unbounded cache would keep
# a token list for every line in the tree alive for the whole process, which is
# memory spent on lines the scan will never look at again. Safe because the
# function is PURE in its one argument and no caller mutates what comes back
# (grep for it before changing either half of that sentence).
@functools.lru_cache(maxsize=4096)
def _tokenize(line):
    """`{"words", "sentence"}` - `line`'s tokens, and which sentence each sits in.

    ONE walk for both answers, because they read the same characters and the
    hardest rule is shared: a separator kept INSIDE a number is not a sentence
    end. A second walk asking only about boundaries would be a second home for
    that rule, and the two would disagree about a decimal the first time either
    was edited.

    `sentence` is an ordinal PER TOKEN, parallel to `words`, rather than a list
    of sentences. Every shape below indexes the line's tokens positionally, so
    the tokens have to arrive as one flat list; which sentence a token sits in is
    an extra fact about it, not a different shape of the same data.
    """
    low = line.lower()
    words, sentence = [], []
    cur, index = [], 0
    for i, ch in enumerate(low):
        if ch.isalnum():
            cur.append(ch)
            continue
        if (ch in _NUMBER_SEPARATORS and cur and _is_digit_char(cur[-1])
                and _is_digit_char(low[i + 1:i + 2])):
            cur.append(ch)
            continue
        if ch == "_" and cur and low[i + 1:i + 2].isalnum():
            cur.append(ch)
            continue
        if cur:
            words.append("".join(cur))
            sentence.append(index)
            cur = []
        if (ch in _SENTENCE_ENDS and not low[i + 1:i + 2].isalnum()
                and not _in_dot_run(low, i)):
            index += 1
    if cur:
        words.append("".join(cur))
        sentence.append(index)
    return {"words": words, "sentence": sentence}


def _backtick_chunks(line):
    """The backticked spans of `line`, in order."""
    return line.split("`")[1::2] if "`" in line else []


# The delimiters that mean "these bytes are SHOWN, not asserted by the author".
# The apostrophe is deliberately absent: `module's` would open a span nothing
# closes, and a single-quoted tally in this tree is always nested inside a
# double-quoted one, so it is covered without costing every possessive.
_QUOTE_DELIMS = ("`", '"')


def _quoted_spans(line):
    """`[(start, end)]` - the column ranges of `line` holding quoted material.

    THE SAME READING OF A DELIMITER `_carries_basis()` AND `_names_code()`
    ALREADY RELY ON, one step further: those ask what a backticked span SAYS,
    and this asks which columns one covers. A number inside such a span is a
    byte this tree renders or asserts - `"fetched %s of %s linked item(s)"` in a
    suite, a rollup quoted in a command's help - and its basis is the code or
    the command around it, not a sentence.

    AN ODD NUMBER OF DELIMITERS OPENS A SPAN THAT RUNS TO THE END OF THE LINE.
    Both prose and source wrap here, so a quoted tally is routinely split across
    two lines and the closing delimiter is on neither of them; reading an
    unpartnered delimiter as a non-event put the first half of every such tally
    back into the finding set.

    AND WHAT THAT BUYS IS PAID FOR WITH THE REST OF THE LINE, which is wider than
    the tally it was adopted for and is stated here because a widening nobody
    states is a widening nobody checks. From an unpartnered delimiter to the end
    of its line, this scan reads NOTHING - not the tally, and not any of the
    other shapes `_prose_number_claim()` knows. The two delimiters are counted
    apart, so balanced backticks do not rescue a line whose double quotes are
    odd, and the opener need not be a quotation at all: a code span opened before
    a wrap, an apostrophe-free `"` inside a sentence, a format string that spells
    one, each blind everything after it. A large minority of the lines this scan
    reads carry an odd count of one delimiter or the other, so the blind tail is
    ordinary rather than exceptional.

    WHAT IT HIDES TODAY IS NOT, and that measurement is the argument for keeping
    it: swept over this whole tree with the span bounded to partnered pairs
    alone, what comes back is a rendered rollup quoted inside a command's help -
    the bytes a formatter prints, whose basis is the command beside them - and no
    author's claim at all. The blind spot stays deliberate; its EXTENT is what
    was never written down. `pn33` and `pn35` hold both ends of it, so it cannot
    grow past the line it is bounded to without a case going red.
    """
    out = []
    for delim in _QUOTE_DELIMS:
        cols = [i for i, ch in enumerate(line) if ch == delim]
        while len(cols) >= 2:
            out.append((cols[0], cols[1] + 1))
            cols = cols[2:]
        if cols:
            out.append((cols[0], len(line)))
    return out


def _in_quoted_span(line, start, end):
    """True if columns `start:end` of `line` overlap quoted material.

    OVERLAP, not containment: a run that begins inside a quoted tally and ends
    past its closing delimiter is still that tally, and requiring containment
    reported the half of it that leaned out.
    """
    for a, b in _quoted_spans(line):
        if start < b and a < end:
            return True
    return False


def _carries_basis(line, following):
    """True if this claim names the command that re-derives it.

    `following` is the NEXT line, and it is read for one reason: prose wraps.
    Every document here is hard-wrapped, so "print it with" routinely ends a
    line and the command begins the next one. Judging the claim by its own line
    alone would call a claim that HAS satisfied the house rule a violation, and
    the repair for that false positive is to delete the basis - the exact
    opposite of what this is for.
    """
    for chunk in _backtick_chunks(line) + _backtick_chunks(following or ""):
        for marker in _BASIS_MARKERS:
            if marker in chunk:
                return True
    return False


def _names_code(line):
    """True if the line quotes a code identifier in backticks.

    THE GATE ON THE PERSISTENCE FAMILY, and it is the reason that family can be
    adopted at all. A persistence claim about a number with a live source is a
    claim about a NAMED thing in this tree, and this repo writes code names in
    backticks; a persistence claim with no code name on the line is prose about
    something the tree does not hold, where neither remedy fits. The measured
    case is `hooks/_config.py`: "the result is still N characters" is the width
    of an invariant format string in a counterfactual about `time.localtime()`,
    it is correct, removing the number would destroy the sentence, and it names
    no code on that line. Without this gate the shape would fire on it.

    A space inside the span means it is a command or a phrase (`_deps.py
    --render` is still a name by its first token, so the check is on the span
    having a spaceless form, not on the whole span).
    """
    for chunk in _backtick_chunks(line):
        if chunk.strip() and " " not in chunk.strip():
            return True
    return False


# Past-tense markers. The broadest family below ("N cases", with no "its" and no
# "live in" in front of it) is the only one wide enough to catch ordinary
# recollection, and recollection is exactly what a decision record is made of.
# Anything on this list means the SENTENCE is talking about THEN, so the number is
# not a claim about now and must stay writable. The sentence and not the line -
# `_historical_sentences()` below carries the two directions the line got wrong.
#
# `measured`, `saw` and `did` were added later, closing a gap in past-tense
# coverage one word at a time rather than as a wholesale loosening. The ratio family below reads the
# spelling a measurement is USUALLY written in, so every sentence it reached that
# was already legal was legal under CONTRIBUTING's third shape - "put it in the
# past" - and this table could not read the past tense the tree actually writes
# it in: "measured on two separate live runs, 39 breaches across N of M tasks",
# "one saw `NO OVERLAP` on N of M tasks because jest prints suite paths", "N of M
# commands behaved; the three that did not are one class", "proven red by making
# exactly that change: N of M rendered fixtures moved". A table of past-tense
# markers missing the tree's own past-tense verbs reports recollection as a claim,
# which is the direction a reader meets by disagreeing with a finding - and the
# way past a finding they disagree with is to route around the lint.
_PAST = ("was", "were", "had", "used", "stood", "down", "up", "once",
         "previously", "then", "before", "originally", "until", "old",
         "measured", "saw", "did", "proven")


def _looks_historical(w):
    """True if these tokens are recollection rather than a present-tense claim."""
    for tok in w:
        if tok in _PAST:
            return True
    return False


# What a hard-wrapped sentence may trail after its stop: quotes, brackets and
# markdown emphasis. Without them a bolded sentence ending in a stop reads as
# unfinished, and the next line would inherit a tense that is not its own.
_SENTENCE_TAIL = " \t\"'`)]}*_"


def _ends_sentence(text):
    """True if `text` finishes a sentence, so a following line starts a new one."""
    tail = text.rstrip(_SENTENCE_TAIL)
    return bool(tail) and tail[-1] in _SENTENCE_ENDS


def _edge_sentences(text):
    """`{"first", "last"}` - the tokens of `text`'s opening and closing sentences.

    The two halves a wrap can join to: a line continues whatever sentence its
    predecessor left open, and leaves one open for its successor to finish. Both
    come from one tokenize because both are that walk's answer, and a text with no
    tokens yields two empty lists rather than None - there is nothing to join,
    which is an answer and not a failure.
    """
    tok = _tokenize(text or "")
    words, sent = tok["words"], tok["sentence"]
    if not words:
        return {"first": [], "last": []}
    return {"first": [w for w, k in zip(words, sent) if k == sent[0]],
            "last": [w for w, k in zip(words, sent) if k == sent[-1]]}


def _historical_sentences(line, preceding, following):
    """The ordinals of `line`'s sentences that read as recollection, not a claim.

    A SENTENCE, NEVER THE PHYSICAL LINE - both directions of that difference were
    met on one day. A past marker in the sentence BEFORE the number -
    two clauses earlier on the same line, about something else entirely - was
    excusing a live count: the escape reading too widely. And a marker in the SAME
    sentence one line up was not reaching the number at all, because prose wraps:
    the escape reading too narrowly. One scope fixes both, and the first half is
    why this is not a loosening - a marker that used to excuse a whole line now
    excuses one sentence of it.

    The join reaches ONE line each way, the window `_carries_basis()` already
    reads and for the same reason. A sentence running further keeps its marker out
    of reach and its number reported, which is the direction a reader meets by
    disagreeing with a finding; the other direction is met by silence.
    """
    tok = _tokenize(line)
    words, sent = tok["words"], tok["sentence"]
    if not words:
        return set()
    before = ([] if _ends_sentence(preceding or "")
              else _edge_sentences(preceding)["last"])
    after = [] if _ends_sentence(line) else _edge_sentences(following)["first"]
    out = set()
    for s in set(sent):
        scope = [w for w, k in zip(words, sent) if k == s]
        if s == sent[0]:
            scope = before + scope
        if s == sent[-1]:
            scope = scope + after
        if _looks_historical(scope):
            out.add(s)
    return out


def _cardinality_claim(tok, historical):
    """"its N cases" / "N cases live in" / "--selftest (N cases)" / "all N of them".

    `historical` is the set of sentence ordinals `_historical_sentences()` read as
    recollection. It arrives as an argument rather than being derived here because
    that reading needs the neighbouring LINES, which a shape holding one line's
    tokens cannot see.
    """
    w, sent = tok["words"], tok["sentence"]
    for i in range(len(w)):
        span = _numeral_span(w, i)
        if span is None:
            continue
        num, end = span
        nxt = w[end] if end < len(w) else ""
        prv = w[i - 1] if i else ""
        if nxt in _CASE_WORDS:
            if prv == "its":
                return "its %s %s" % (num, nxt)
            if w[end + 1:end + 3] == ["live", "in"]:
                return "%s %s live in" % (num, nxt)
            if "selftest" in w[max(0, i - 4):i]:
                return "--selftest (%s %s)" % (num, nxt)
        # "all N of them", the shape selftest_coverage's own docstring used
        if prv == "all" and w[end:end + 2] == ["of", "them"]:
            return "all %s of them" % num
        # The BARE shape: a number sitting in front of "cases", however it is
        # introduced -- "the N cases in tests/", "across N cases", "the ~N cases
        # below". Every example here spells N on purpose: written with real
        # digits, this comment is itself a finding, and the first draft of it
        # was. Fix the example, never exempt the file.
        #
        # Adopted on the measurement, not on taste: eight sites, of which SEVEN
        # were already wrong -- two claiming a suite that has since grown by
        # forty-four, one short by ten, three short by twenty-one, one short by
        # forty-six. The eighth was correct that day, which is the whole
        # argument: it is one added case away from joining the other seven.
        #
        # This family is wide enough to catch ordinary recollection, so it is the
        # one that has to ask whether the SENTENCE is talking about THEN. Skipping
        # that check turns "it stood at N cases that day" into a violation and
        # makes the decision record unwritable. The sentence the NUMERAL sits in,
        # not the line: a marker two clauses back, about something else, used to
        # excuse a live count on the same line.
        if nxt in _CASE_WORDS or (nxt == "selftest" and w[end + 1:end + 2] and
                                  w[end + 1] in _CASE_WORDS):
            if sent[i] not in historical:
                return "%s cases" % num
    return None


def _persistence_claim(line, w):
    """"`NAME` stayed at N" / "`NAME` is still N" - a count claimed to persist,
    which goes stale the moment the named thing changes without the prose being
    re-read."""
    if not _names_code(line):
        return None
    for i in range(len(w)):
        span = _numeral_span(w, i)
        if span is None:
            continue
        for phrase in _PERSISTS:
            n = len(phrase)
            if i >= n and tuple(w[i - n:i]) == phrase:
                return "%s %s" % (" ".join(phrase), span[0])
    return None


def _completeness_claim(w):
    """"all N <noun> have/are ..." - a cardinality for a whole, in the present.

    The auxiliary must fall within three tokens of the number. That window is
    not arbitrary: it separates "all N files have moved" (a claim about now)
    from "pins all N alias lines this module's names ARE re-exported through"
    (a count, and a relative clause seven tokens later that has nothing to do
    with it). Both spellings are in this tree, and a window of three is what
    tells them apart.
    """
    for i in range(len(w)):
        if not i or w[i - 1] != "all":
            continue
        span = _numeral_span(w, i)
        if span is None:
            continue
        num, end = span
        for aux in w[end:end + 3]:
            if aux in _PRESENT_AUX:
                return "all %s ... %s" % (num, aux)
    return None


# --- a ratio quoted without its basis -------------------------------------------
# `N of M <noun>` is not a fourth question, it is the third answer to the one
# already asked. A ratio READS as a quotation - it shows its own whole, so it looks
# self-verifying - and the three spellings this repo keeps legal all read that way
# too: history, a number carrying the command that re-derives it, and the repair
# itself. What separates them is not whether a line quotes something. It is whether
# the count CARRIES ITS BASIS, which is exactly what `_carries_basis()` decides for
# a bare cardinality, and this family asks it through the same gate rather than a
# new one: a denominator is not a basis, because nothing re-derives it either.
#
# THE SHAPE IS THE TALLY A COMMAND PRINTS, and that bound is the whole reason this
# family could be adopted where the bare `the N <noun>` still cannot. A formatter
# writes `%s of %s %s`, so the printed form carries NO ARTICLE; `N of the M <noun>`
# is the author's own sentence about the tree, which is the ordinary-noun shape
# `CONTRIBUTING.md` declares author-enforced. The bound was chosen by reading every
# hit of the unbounded reading over this tree, and the count is deliberately not
# written here: it fell by better than an order of magnitude, and what it shed was
# almost entirely rendered output and measurements rather than claims.
#
# THE ARTICLE IS REFUSED TWICE OVER, and that is worth knowing before mutating
# either half: the loop wants the whole to follow `of` DIRECTLY, and the verbatim
# rule below refuses `N of the M <noun>` again, because the run built from the
# tokens leaves the article out and the text does not. So neither mutation alone
# turns `pn32` red - proven by running both, separately and together - and a
# reader who removes one and sees green has not found a dead rule.
#
# The narrowings under it were each bought by a class of real line - and which one
# stops a given line is a fact about the CODE PATH, so the attributions below were
# taken by removing them one at a time and re-reading the fixtures, not off the
# sentence that introduced them:
#   * the token after the whole must not itself be a numeral. A number a document
#     GROUPS (`22,363 of 49,393 lines`) arrives as two tokens, and the second of
#     them stands where the noun would - so this is what stops a grouped ratio,
#     and it stops it before the verbatim rule below is ever reached. That rule
#     refuses the same line again, so neither mutation alone opens it and a reader
#     who removes one and sees green has not found a dead rule; `pn36` is the
#     fixture that isolates this narrowing on its own. WHAT IT GIVES UP is a tally
#     whose noun really is a numeral (`13 of 14 2026`), which is an UNDER-count -
#     the one direction these shapes are already documented as being wrong in;
#   * the run must appear in the TEXT exactly as it tokenized, one space between
#     each part - which is what tells `13 of 14 sections` from `5-of-0` and from a
#     numeral the backticks around it were never beside;
#   * the noun must be a noun. A closed table of function words is the only half of
#     that a word scanner can make honestly, the same admission
#     `_completeness_claim()` makes about auxiliaries: `8 of 40 can be coloured`
#     and `it fails at 17 of 353 with this feature off` do not say what they count,
#     and a tally that names nothing is one no reader could check anyway;
#   * neither the run nor its noun may sit in a quoted span, because there the
#     tally is a byte and its basis is the code beside it.
#
# AND ONE LINE HERE IS FILED UNDER NO NARROWING AT ALL, said because it used to be
# filed under the verbatim rule and is not refused by it: `index["phases"][1]["claim"]`
# never reaches a run, since this arm needs a bare `of` between the two numerals
# and that line has none. It stays in the suite as a line this family must be
# silent about - which it is, one level up from any narrowing below.
_RATIO_NON_NOUN = (
    "a", "an", "the", "and", "or", "but", "as", "than", "that", "which",
    "of", "in", "on", "at", "to", "for", "with", "from", "by", "into",
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did",
    "can", "could", "will", "would", "may", "might", "must", "should",
    "not", "no", "so", "if", "when", "then", "there", "here", "it",
)

# `one of N <noun>` is English, not a tally. "this is one of four classes" names a
# MEMBERSHIP, the sentence dies if the word goes, and neither number is a claim
# about how many of anything there are. It is the one word in `_NUMERAL_TAILS`
# carrying that second job, which is why this is a word and not a band: measured
# over this tree, every `one of N <noun>` the arm reached was that idiom - eight
# sites in `scripts/`, `tests/` and `reference/` - and no other small word
# produced one. A formatter prints `1 of N`, so the DIGIT spelling of the same
# position stays read and only the word is given up.
_RATIO_NOT_A_PART = ("one",)


def _ratio_claim(line, tok, historical):
    """"N of M <noun>" - a printed tally quoted with no command beside it.

    `historical` arrives from `_historical_sentences()` for the reason the bare
    cardinality family needs it: a measurement is a fact about a moment and stays
    writable for ever, and a ratio is the spelling a measurement usually wears.
    """
    w, sent = tok["words"], tok["sentence"]
    low = line.lower()
    for i in range(len(w)):
        span = _numeral_span(w, i, True)
        if span is None or w[i] in _RATIO_NOT_A_PART:
            continue
        part, mid = span
        if w[mid:mid + 1] != ["of"] or mid + 1 >= len(w):
            continue
        whole = _numeral_span(w, mid + 1, True)
        if whole is None:
            continue
        total, end = whole
        if end >= len(w) or _numeral_span(w, end, True) is not None:
            continue
        noun = w[end]
        if noun in _RATIO_NON_NOUN or sent[i] in historical:
            continue
        run = "%s of %s %s" % (part, total, noun)
        at = low.find(run)
        while at >= 0:
            if not _in_quoted_span(line, at, at + len(run)):
                return run
            at = low.find(run, at + 1)
    return None


def _prose_number_claim(line, following=None, preceding=None):
    """The claim's text if this line writes a present-tense number, else None.

    A line that names the command recomputing the number is NOT a finding: the
    house rule is that a claim carries the basis that makes it true, and such a
    line has done exactly that.

    `following` and `preceding` are the neighbouring PHYSICAL lines, and neither
    is decoration: every document here is hard-wrapped, so a claim's basis and
    the tense of the sentence carrying it both routinely land one line away from
    its number. Called with neither - which is what a caller handing over a
    single string means - this reads the line as one whole sentence.

    THIS IS THE ONLY DEFINITION OF THE SHAPES. `_deps` scans the documents and
    delegates here rather than restating them; a second copy of the pattern
    would be precisely the defect both scanners exist to catch, and a case in
    each suite asserts there is no second `def`.
    """
    if _carries_basis(line, following):
        return None
    tok = _tokenize(line)
    w = tok["words"]
    past = _historical_sentences(line, preceding, following)
    return (_cardinality_claim(tok, past)
            or _ratio_claim(line, tok, past)
            or _persistence_claim(line, w)
            or _completeness_claim(w))


# --- what the prose scan reads ------------------------------------------------
# DERIVED, NOT LISTED, and that is the whole of this section. The scanned set used
# to be a hand-written pair - `.py` under `hooks/` and `scripts/`, plus three named
# documents - so everything else in the repo was unguarded, and that is where the
# claims had gone: a part count in `scripts/ui/*/README.md` (three sites, two of
# them already wrong), a suite size in a `tests/` docstring (most of them wrong),
# and a file count in the prover under `tools/` - the directory holding the sweep
# runner, the gate parity check and the mutation table, every one of which exists
# to talk about counts. The tree's own counting tools were the unaudited part.
#
# So the set is now every `.py` and every `.md` the walk reaches, and a file added
# to this repo is scanned by default. Excluding one is a row below carrying a
# reason a reader can disagree with - the shape `tools/gate-parity.py` uses for a
# gate a side may legitimately not name, and `_refs.EXCLUDED` for the documents
# where a stale path is correct rather than broken.
#
# A row is a repo-relative path or, ending in `/`, a directory prefix.
PROSE_SCAN_EXEMPT = (
    ("tools/measure-affected-miss.py",
     "its self-test fixtures are strings that imitate the sweep's own summary line "
     "(files ok, then a case count) so the tool can be shown to read that output; "
     "they are data handed to a parser, not prose that claims a number, and "
     "rewording them would stop them being the line the parser reads. The cost is "
     "the thing to disagree with: a genuinely stale count in this tool's own "
     "docstrings and comments is unguarded too, because the row exempts the whole "
     "file and not only the fixture lines"),
    ("CHANGELOG.md",
     "released history: a count in a shipped entry was true of that release, and "
     "rewriting released history to keep a lint quiet is worse than the lint"),
    ("docs/design/",
     "dated design records: they describe the tree as it was at the decision, so "
     "the numbers in them are history in the same way a past tense is"),
    ("docs/audit/audit-report.md",
     "generated from the manifest on every render, so a count in it is derived "
     "rather than written. It is also gitignored as a FILE, which this walk does "
     "not read, so without this row the finding set would move with whether "
     "anybody had rendered a report in this checkout"),
    ("tests/test__output_lints.py",
     "holds THIS scanner's own fixtures: every shape it recognises appears there "
     "as an argument spelled on purpose, because a text scanner can only be shown "
     "to fire by handing it the literal it must recognise. The house rule is to "
     "build a forbidden literal rather than write one, and here the literal IS "
     "the argument under test - building it would move the needle out of the "
     "fixture and into the assertion. The cost is the thing to disagree with: a "
     "genuinely stale count in this one suite is unguarded"),
    ("tests/test__deps.py",
     "the same, for the document half - its cases hand the shapes to "
     "`_deps.doc_prose_numbers()` as fixture documents"),
)


def prose_scan_exemption(rel, table=PROSE_SCAN_EXEMPT):
    """The declared reason `rel` is out of a scan reusing this walk, or None.

    `table` defaults to `PROSE_SCAN_EXEMPT` - this scan's own rows - so every
    existing caller is unchanged. A DIFFERENT scan sharing the walk (the
    register-citation scan reads the same tree for a different vocabulary)
    hands its own table instead, so a path is judged by the rows written for
    THAT scan and never by another scan's reasons.
    """
    for path, why in table:
        if path.endswith("/"):
            if rel.startswith(path):
                return why
        elif rel == path:
            return why
    return None


def prose_scan_set(exts, repo_root=None, table=PROSE_SCAN_EXEMPT):
    """`{"paths", "candidates", "exempted", "problem", "basis"}` - what a scan
    sharing this walk reads.

    `basis` says where the candidate set came from, in words a message can carry:
    the files git LISTS (tracked, plus untracked and not ignored) when git can
    answer for the root; otherwise the `.gitignore` derivation, with
    the reason git could not answer. A scan that fell back is a wider scan - it
    reads whatever of the scanned extensions is on disk and not ignored - and the
    only way a reader can tell the two verdicts apart is that the set says which
    one it is.

    `problem` is a string or None, and it is the loud half. A tree git cannot
    answer for whose `.gitignore` cannot be read either yields no paths, and
    "read no files" must not print the way "found no claims" prints - which is the
    whole reason this returns the candidate count alongside the paths rather than
    just the paths.

    `table` is the exemption rows candidates are judged against, defaulting to
    this module's own `PROSE_SCAN_EXEMPT`. THE WALK IS SHARED, THE EXEMPTIONS
    ARE NOT: a caller reading the same derived file set for a different
    vocabulary hands its own table so its exemptions carry its own reasons
    rather than inheriting another scan's.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    candidates, why = tracked_files(root, tuple(exts))
    if candidates is not None:
        basis = GIT_LISTED_BASIS
    else:
        patterns, problem = _ignored_dirs(root)
        if problem is not None:
            return {"paths": [], "candidates": 0, "exempted": [],
                    "problem": ".gitignore is %s" % problem,
                    "basis": "nothing - git could not answer (%s) and the "
                             ".gitignore derivation failed" % (why,)}
        candidates = kept_files(root, patterns, tuple(exts))
        basis = ("the .gitignore derivation - git could not answer (%s), so files "
                 "git does not track are read too" % (why,))
    exempted = [rel for rel in candidates
                if prose_scan_exemption(rel, table) is not None]
    skip = set(exempted)
    return {"paths": [rel for rel in candidates if rel not in skip],
            "candidates": len(candidates), "exempted": exempted,
            "problem": None, "basis": basis}


# Two terms, one absolute and one derived: an absolute floor answers
# "did this read return anything at all" and nothing more, so a set that had lost
# most of the tree would still clear it. The derived term measures the SCANNED set
# against the CANDIDATE set the same walk produced, which is the best available
# evidence of how big the real set is - and it is the term that fires when a row
# in the table above grows to swallow a directory.
#
# WHAT IT COUPLES, said rather than implied: if the walk itself collapses, both
# terms fall together and this stays green. That direction is not covered here and
# must not be, because a floor derived from the thing it measures cannot cover it -
# the cases hold the scanned set against a PLAIN recursive walk of the directories
# that have to exist, which needs no `.gitignore` and so cannot fail the same way.
SCAN_FLOOR_MINIMUM = 8
SCAN_FLOOR_DIVISOR = 2


def scan_floor(candidates):
    """The fewest files a prose scan may read before its result stops being evidence."""
    return max(SCAN_FLOOR_MINIMUM,
               (candidates + SCAN_FLOOR_DIVISOR - 1) // SCAN_FLOOR_DIVISOR)


def prose_claims_in(root, rels):
    """[(rel, lineno, claim), ...] - every claim in `rels`, read relative to `root`.

    ONE read loop for both halves of the scan. `_deps` keeps its own only for the
    caller that hands it absolute fixture paths; the tree is read here.

    An unreadable file is NAMED, never skipped. A skip would return
    the same empty list a clean file returns, and "nothing to report" would then
    mean either "clean" or "could not look".
    """
    out = []
    for rel in rels:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, 0, "<unreadable: %s>" % exc))
            continue
        lines = text.split("\n")
        for lineno, line in enumerate(lines, 1):
            nxt = lines[lineno] if lineno < len(lines) else ""
            prv = lines[lineno - 2] if lineno >= 2 else ""
            claim = _prose_number_claim(line, nxt, prv)
            if claim is not None:
                out.append((rel, lineno, claim))
    return out


def prose_number_claims(repo_root=None):
    """[(relpath, lineno, text), ...] -- present-tense numbers written into prose.

    THE RULE: do not write the number. Every suite prints `N/M cases passed` on
    every run and CI runs all of them; `len(_deps.KNOWN_LAYER_DEBT)` is one
    command away; `selftest_coverage()['covered']` is another. The count already
    has a live source, so a copy in a docstring has no reader who acts on it and
    nothing comparing it. The pointer to the source is the informative half, and
    it stays.

    Measured when the first family was written, and the reason this is a lint
    rather than a round of corrections: **9 of the 51 such claims in the tree
    were already wrong** -- `_panel_page.py` said 285 against a real 325,
    `_refs.py` said 32 against 80, `guard-secrets-read.py` said 93 against 108,
    and `selftest_coverage`'s own docstring said 64 while 84 test files existed.
    Correcting them buys one green day: every one rots again the next time
    somebody adds a case, which is the entire point of adding cases. The two
    families added after it were measured the same way and were **4 sites, 4 of
    them already wrong** -- a hit rate that is itself the argument.

    MEASURED AGAIN WHEN THE LOCATION WIDENED, because a scan that fires on
    honest prose is a scan that gets routed around. Every hit the widened walk
    produced over this tree was read. The real claims were suite sizes in
    `tests/` docstrings and part counts in `scripts/ui/*/README.md`, most of them
    already wrong; the false positives were all ONE thing, the
    `<passed>/<total>` tally, appearing as a fixture, as a regex and as an
    asserted literal in the files whose job is that contract. Removing them is
    `_words()`'s interior-separator rule, which is a NARROWING - nothing that
    was already a finding stopped being one - and the rest were reworded or
    built rather than written, never admitted by loosening a shape.

    WHAT IT CANNOT SEE, stated rather than implied, and the direction matters
    more than the list:

      * a count spelled as one of the small number-words `_NUMERAL_WORDS`
        leaves out -- under `ten` the word is ordinary English machinery and a
        family reading a bare noun cannot tell it from a count. `_numeral_span`
        will read it for a family whose SHAPE supplies the bound instead, which
        today is the ratio and nothing else; switched on for the rest it
        reported over a hundred sites in this tree, essentially all honest;
      * the bare `the N <noun>` with an ordinary noun, which is the shape two
        earlier real instances wore, one of them "five claims deep". This one
        is REFUSED rather than missing: the noun is unbounded,
        so reading it means reading every count in every sentence this tree
        writes. Measured before refusing, on the two nouns those instances used
        and on nothing wider: with the small words admitted it reported dozens
        of sites and not one was a claim -- "the one claim neither of them
        covers", "two claims, and each one carries the basis", "one section
        marker per 400 lines". `CONTRIBUTING.md` says the same affirmatively and
        `CLAUDE.md` says whose job it therefore is. `pn31`;
      * a claim whose NUMBER and whose SHAPE-WORD land on different lines --
        the basis and the SENTENCE the number sits in are both read across the
        wrap, but never the claim itself;
      * a ratio the AUTHOR wrote rather than a command printed: `N of the M
        <noun>` carries an article no formatter emits, so it is the bare
        ordinary-noun shape above and is left to the author for the same reason.
        Nor is one read inside a quoted span, where the bytes are shown rather
        than claimed, nor where the token after the whole is one of the function
        words `_RATIO_NON_NOUN` names, nor `one of N <noun>`, which is English;
      * a MEASUREMENT -- a duration, a byte count, a line count. A units family
        was surveyed over this whole tree before being refused, and the refusal
        IS the measurement: on the widest vocabulary honest prose outran real
        claims by better than two to one, and on the narrowest defensible cut
        (size units, on a line naming code, the gate the persistence family
        uses) it still outran them. A size or a duration here is usually a
        threshold, a budget, a hypothetical, or a fact about somebody else's
        system, and in every one of those the number is what the sentence is
        for. `pn27` holds the lines that decided it, so adopting one without
        measuring again goes red;
      * a BEFORE/AFTER sentence -- "it was N lines and is M". The first number
        is history and legal for ever, the second is a live claim, and the tense
        that makes the first legal sits in the same sentence as the second,
        which is exactly why a reader trusts both. The `is N` shape that would
        reach it was surveyed too: real claims were about a quarter of its hits
        and the rest were arithmetic, format shapes and external facts. `pn28`;
      * a completeness claim with no auxiliary ("(all 64)", "all 8 viz slots"),
        because recognising an arbitrary present-tense verb needs a lexicon;
      * a persistence claim that names no code in backticks on its own line;
      * a number written with an interior separator -- `_words()` keeps a ratio
        and a decimal whole on purpose, and neither is then a numeral;
      * a file of an extension this does not read. `.py` is here and `.md` is
        `_deps.doc_prose_numbers()`; `.mjs`, `.js`, `.sh`, `.yml` and `.json`
        carry prose too and are read by nothing;
      * a file with a row in `PROSE_SCAN_EXEMPT`, which is the only remaining
        LOCATION gap and is the only one somebody had to write down.

    Every one of those is an UNDER-count. Over-counting is impossible with
    shapes this narrow, and under-counting is the quiet direction -- so a clean
    result means "none of the known shapes", not "no claims".
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    scan = prose_scan_set((".py",), root)
    if scan["problem"] is not None:
        # A read that could not happen is a finding, not an empty result.
        return [(".gitignore", 0, scan["problem"])]
    return sorted(prose_claims_in(root, scan["paths"]))


