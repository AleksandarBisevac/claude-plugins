#!/usr/bin/env python3
"""
The cases for `_output.py` - the anchor every shipped script imports: the directory
constants, `safe_stdio`, the success line, `remove_tree`, the sharing wait, the file
walks a shipped script asks, the finding code and the project a manifest belongs to.

The half of `_output.py` that judges the repository's own source left it for
`tools/lints/_output_lints.py`, and its cases are in `tests/test__output_lints.py`.
This file holds only what a shipped script can still ask `_output` for.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `L` is `_output_lints`, imported only where a case needs a
lint to judge something about the anchor.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import json
import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output as M                                # noqa: E402
import _output_lints as L                          # noqa: E402
import _surface_digest                             # noqa: E402  (us1: the digest the walk feeds)



# --- literals that carry a command --------------------------------------------
def _lint_module_names():
    """The module names `tools/lints/` holds - the ones a command that puts only the
    plugin's scripts on sys.path can no longer import. Read off the directory so a
    lint module added there is covered the day it lands."""
    folder = os.path.join(M.REPO_ROOT, "tools", "lints")
    return sorted(n[:-3] for n in os.listdir(folder) if n.endswith(".py"))


def moved_module_imports(text, names):
    """The module names `text` imports from a command that puts the plugin's
    scripts on sys.path, none of which that command can reach.

    A literal that also names `tools/lints` puts the lints on the path itself, so it
    is a working command and reports nothing."""
    # The plugin's scripts directory however it is spelled: one literal, or joined
    # from parts (`os.path.join("plugins", "audit", "scripts")`), which is how
    # `tools/verify.sh` wrote it and which no search for the slash form finds.
    spot = re.search(r"plugins\W+audit\W+scripts", text)
    if spot is None or "tools/lints" in text:
        return []
    tail = text[spot.start():]
    alt = "|".join(re.escape(n) for n in names)
    found = re.findall(r"\b(?:import\s+(?:\w+\s*,\s*)*|from\s+)(%s)\b" % alt, tail)
    return sorted(set(found))


def _json_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            for text in _json_strings(value):
                yield text
    elif isinstance(node, list):
        for value in node:
            for text in _json_strings(value):
                yield text


# What a command may legitimately still name in its old form: the changelog and the
# dated design records are history, `docs/audit` is generated from the plan, and a
# case under `tests/` builds the very shapes this reading must detect.
_COMMAND_SCAN_SKIP = ("CHANGELOG.md", "docs/", "tests/")
_COMMAND_SCAN_EXTS = (".py", ".sh", ".yml", ".yaml", ".md", ".json")


def _comment_blocks(source):
    """The runs of consecutive `#` comment lines in `source`, `#` stripped - the other
    place a `.py` carries a command a reader will copy."""
    blocks = []
    run = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            run.append(line.lstrip()[1:])
        elif run:
            blocks.append("\n".join(run))
            run = []
    if run:
        blocks.append("\n".join(run))
    return blocks


def chunks_of(rel, source):
    """The texts in one file that can each hold a command, by the file's own grain.

    A `.py` holds one in a string literal or a comment block, an evals file in a JSON
    string, and everything else - a shell script and its heredocs, a workflow's `run:`
    step, a fenced block in a document - in a blank-line-separated block of its text.
    ONE reading for every kind, so a new extension is a row in
    `_COMMAND_SCAN_EXTS`, not a second scanner."""
    if rel.endswith(".py"):
        tree = ast.parse(source, rel)
        return ([node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)]
                + _comment_blocks(source))
    if rel.endswith(".json"):
        return list(_json_strings(json.loads(source)))
    return [b for b in re.split(r"\n\s*\n", source) if b.strip()]


def _command_files(top=None):
    """Repo-relative paths of the text files to read under `top` (this repo by
    default): the ones git lists (tracked, plus untracked and not ignored), or - for
    a tree git cannot answer for (an exported archive) - a walk, which names the
    files on disk without reading `.gitignore`."""
    top = top if top is not None else M.REPO_ROOT
    paths, _why = L.tracked_files(top, _COMMAND_SCAN_EXTS)
    if paths is None:
        paths = []
        for root, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in ("__pycache__", ".git", "node_modules"))
            paths.extend(M.posix_rel(os.path.join(root, n), top)
                         for n in sorted(filenames) if n.endswith(_COMMAND_SCAN_EXTS))
    return [p for p in paths if not p.startswith(_COMMAND_SCAN_SKIP)]


def _shipped_literals(top=None):
    """`(literals, unreadable)` for every file `_command_files` names: the
    `[(repo-relative path, text)]` chunks of each file that could be read, and the
    `[(path, reason)]` of each that could not.

    An untracked file is read now, and a scratch `.py` or `.json` an agent left
    half-written does not parse. It is named in `unreadable` rather than skipped
    (a file nobody read would pass the scan) or raised on (one stray file would
    take the whole suite down with it)."""
    top = top if top is not None else M.REPO_ROOT
    out = []
    unreadable = []
    for rel in _command_files(top):
        try:
            with open(os.path.join(top, rel), "r", encoding="utf-8") as fh:
                out.extend((rel, text) for text in chunks_of(rel, fh.read()))
        except (OSError, ValueError, SyntaxError) as exc:
            unreadable.append((rel, "%s: %s" % (type(exc).__name__, exc)))
    return out, unreadable


# --- cases --------------------------------------------------------------------
def _cases(check):
    import tempfile
    import shutil
    import io

    # ------------------------------------------------------------------ the anchors
    # BEFORE AND AFTER, MEASURED. Seventeen sites used to derive a parent directory
    # from their OWN `__file__`; they now read one of the five anchors. On a flat
    # tree each must evaluate to the string it evaluated to before, and the way to
    # know that is to recompute the OLD expression here and compare - not to assert
    # that the new one looks right.
    #
    # Every consumer at once rather than a hand-picked few: the old expressions were
    # all functions of the consuming file's `__file__`, so running them over EVERY
    # `.py` under scripts/ proves the claim for all thirty-seven and keeps proving it
    # for the thirty-eighth. `_ab`/`_ab2`/`_ab4` are the three depths that were
    # actually spelled in the tree (`dirname` once, twice and four times).
    #
    # SCOPED TO THE FILES STILL AT DEPTH 0, AND THAT SCOPE IS THE FINDING RATHER THAN
    # A CONVENIENCE. `dirname(abspath(__file__))` is a claim about how deep a file
    # sits; it was true of all thirty-eight while `scripts/` was flat, and the files
    # now filed under a domain (`scripts/report/`, `scripts/usage/`,
    # `scripts/governance/`) are precisely the ones for which it stopped being true.
    # Recomputing it over them would not measure "the anchor equals what the old code
    # produced" — it would measure that the old code is the thing the preamble
    # replaced. `an8` carries the other half: a file AT DEPTH resolves to the same
    # anchor, by walking up to `_output.py` rather than by counting `dirname` calls,
    # which is the claim the preamble makes and the one no `dirname` chain can make.
    _paths = [p for rel, p in M.script_files() if "/" not in rel]
    _nested = [p for rel, p in M.script_files() if "/" in rel]
    _ab = [os.path.dirname(os.path.abspath(p)) for p in _paths]
    _ab2 = [os.path.dirname(d) for d in _ab]
    _ab4 = [os.path.dirname(os.path.dirname(d)) for d in _ab2]
    check("an1 SCRIPTS_DIR is what a TOP-LEVEL file's old `dirname(abspath("
          "__file__))` produced - %d files, one answer: %r"
          % (len(_paths), M.SCRIPTS_DIR),
          _paths and set(_ab) == set([M.SCRIPTS_DIR]))
    check("an2 PLUGIN_ROOT is what `_areas`/`_policy`'s old "
          "`dirname(dirname(abspath(__file__)))` and `_help`'s old `dirname(_HERE)` "
          "both produced: %r" % (M.PLUGIN_ROOT,),
          set(_ab2) == set([M.PLUGIN_ROOT])
          and os.path.basename(M.PLUGIN_ROOT) == "audit")
    check("an3 HOOKS_DIR is what `_deps`/`audit-doctor`/`audit-journal`'s old "
          "`join(dirname(_HERE), 'hooks')` produced: %r" % (M.HOOKS_DIR,),
          set(os.path.join(d, "hooks") for d in _ab2) == set([M.HOOKS_DIR])
          and os.path.isdir(M.HOOKS_DIR))
    check("an4 TESTS_DIR is the `tests` directory beside the plugin, at the "
          "repository root - the old `join(dirname(_HERE), 'tests')` one level "
          "too deep now - and it is the directory this file is in: %r"
          % (M.TESTS_DIR,),
          set(os.path.join(d, "tests") for d in _ab4) == set([M.TESTS_DIR])
          and os.path.dirname(os.path.abspath(__file__)) == M.TESTS_DIR)
    check("an4b LINTS_DIR is `tools/lints` at the repository root, holds the two "
          "lint modules, and is NOT among the directories `install_path()` puts "
          "on sys.path - the product never reaches them by basename, which is "
          "the property that makes moving them out of scripts/ mean something: %r"
          % (M.LINTS_DIR,),
          set(os.path.join(d, "tools", "lints") for d in _ab4) == set([M.LINTS_DIR])
          and os.path.isfile(os.path.join(M.LINTS_DIR, "_deps.py"))
          and os.path.isfile(os.path.join(M.LINTS_DIR, "_refs.py"))
          and M.LINTS_DIR not in M.install_path()
          and not [r for r, _p in M.py_files(M.SCRIPTS_DIR)
                   if os.path.basename(r) in ("_deps.py", "_refs.py")])
    check("an5 REPO_ROOT is what `_output`'s and `_refs`' old three-deep "
          "`dirname(dirname(dirname(_HERE)))` produced - the duplicate derivation "
          "that is now one: %r" % (M.REPO_ROOT,),
          set(_ab4) == set([M.REPO_ROOT])
          and os.path.isdir(os.path.join(M.REPO_ROOT, "plugins")))
    # The two sites whose OLD value was not normalised: `_panel_state`'s
    # `join(_HERE, "..", "hooks", "guard-capabilities.py")` and `_deps`'
    # `join(_HERE, "..", "..", "..", "PLUGIN-BUILD-GUIDE.md")` each carried `..`
    # segments in the middle of the string. The new values are the normpath of the
    # old ones, which is the honest comparison and is stated rather than glossed.
    _old_gc = os.path.join(M.SCRIPTS_DIR, "..", "hooks", "guard-capabilities.py")
    _old_guide = os.path.join(M.SCRIPTS_DIR, "..", "..", "..",
                              "PLUGIN-BUILD-GUIDE.md")
    check("an6 the two `..`-carrying sites resolve to the SAME FILE, and the new "
          "spelling is the normpath of the old - not the same string, which is why "
          "this case compares normpaths and says so",
          os.path.normpath(_old_gc)
          == os.path.join(M.HOOKS_DIR, "guard-capabilities.py")
          and os.path.normpath(_old_guide)
          == os.path.join(M.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md")
          and os.path.isfile(os.path.normpath(_old_gc))
          and os.path.isfile(os.path.normpath(_old_guide)))
    def _walk_up(path):
        """The preamble's own loop, verbatim: up from the file until `_output.py` is
        beside it. Reproduced here rather than imported because the thing under test
        IS the loop - reading it off the module it bootstraps would be the module
        agreeing with itself."""
        d = os.path.dirname(os.path.abspath(path))
        while not os.path.isfile(os.path.join(d, "_output.py")):
            up = os.path.dirname(d)
            if up == d:
                return None
            d = up
        return d

    check("an8 a file AT DEPTH reaches the SAME anchor - the preamble walks up to "
          "_output.py instead of counting dirnames, so `scripts/report/*.py` lands on "
          "SCRIPTS_DIR where `dirname(abspath(__file__))` would have landed on "
          "scripts/report. %d nested file(s); this is the case that had nothing to "
          "measure while the tree was flat" % (len(_nested),),
          _nested and set(_walk_up(p) for p in _nested) == set([M.SCRIPTS_DIR]))
    check("an9 ...and the OLD expression would have got it wrong, which is the "
          "direction that fails if the preamble is quietly replaced by a dirname "
          "count again",
          all(os.path.dirname(os.path.abspath(p)) != M.SCRIPTS_DIR for p in _nested))
    check("an7 ...and all five anchors are real directories, so a typo in one is a "
          "failure here rather than an empty scan somewhere downstream",
          all(os.path.isdir(d) for d in (M.SCRIPTS_DIR, M.PLUGIN_ROOT, M.HOOKS_DIR,
                                         M.TESTS_DIR, M.REPO_ROOT)))

    # ------------------------------------- where a plugin `.py` moved to (`mv*`)
    # These three lived in `_refs` until it left `scripts/`; `audit-task.py` is
    # shipped and asks one of them, so they sit in the anchor. Fixture root, because
    # the real tree has no moved file to ask about - and BOTH answers are needed:
    # a check that said "moved" for everything, or for nothing, fails one of them.
    mv_root = tempfile.mkdtemp(prefix="audit-moved-")
    try:
        mv_plugin = os.path.join(mv_root, *M.PLUGIN_REL.split("/"))
        os.makedirs(os.path.join(mv_plugin, "scripts", "sub"))
        for _name in ("scripts/sub/relocated.py", "scripts/stays.py"):
            with open(os.path.join(mv_plugin, *_name.split("/")), "w",
                      encoding="utf-8") as fh:
                fh.write("x = 1\n")
        mv_idx = M.py_index(mv_root)
        mv_moved = M.moved_file_target(M.PLUGIN_REL + "/scripts/relocated.py", mv_root)
        mv_there = M.moved_file_target(M.PLUGIN_REL + "/scripts/stays.py", mv_root)
        mv_gone = M.moved_file_target(M.PLUGIN_REL + "/scripts/never_was.py", mv_root)
        mv_other = M.moved_file_target("elsewhere/scripts/relocated.py", mv_root)
        mv_given = M.moved_file_target(M.PLUGIN_REL + "/scripts/relocated.py",
                                       mv_root, index={})
    finally:
        shutil.rmtree(mv_root, ignore_errors=True)
    check("mv1 the index is keyed by BASENAME and lists the repo-relative path with "
          "forward slashes: %r" % (mv_idx,),
          mv_idx == {"relocated.py": [M.PLUGIN_REL + "/scripts/sub/relocated.py"],
                     "stays.py": [M.PLUGIN_REL + "/scripts/stays.py"]})
    check("mv2 a recorded path whose file moved answers with its new home; a path "
          "that is still there, one whose basename exists nowhere (a deletion) and "
          "one outside the plugin answer None - four different readings of "
          "'not a move' that one `is None` would have to tell apart: %r"
          % ((mv_moved, mv_there, mv_gone, mv_other),),
          mv_moved == M.PLUGIN_REL + "/scripts/sub/relocated.py"
          and mv_there is None and mv_gone is None and mv_other is None)
    check("mv3 a caller that hands in the index is answered from IT, not from a "
          "walk of its own - the empty one proves it: %r" % (mv_given,),
          mv_given is None)
    check("mv4 `is_plugin_py_path` is a prefix-and-extension question: a plugin "
          ".py is one; the same name outside the plugin, a non-.py file under "
          "it and a non-string are not",
          M.is_plugin_py_path(M.PLUGIN_REL + "/scripts/x.py")
          and not M.is_plugin_py_path("tools/x.py")
          and not M.is_plugin_py_path(M.PLUGIN_REL + "/README.md")
          and not M.is_plugin_py_path(None))

    # ------------------------------ the move to tests/ and tools/lints/ (`mv5`-`mv8`)
    # The index a moved file is looked up in must hold the places a plugin file went
    # to, not only the plugin: a suite filed under `tests/` or a lint under
    # `tools/lints/` read as GONE (quiet history) while it had only moved.
    mv_names = _lint_module_names()
    check("mv5 the modules that left `scripts/` are DERIVED from what `tools/lints/` "
          "holds - and the two the command-in-prose class was found with are among "
          "them, so an empty derivation cannot make mv6 vacuous: %r" % (mv_names,),
          "_deps" in mv_names and "_refs" in mv_names)
    mv_literals, mv_unreadable = _shipped_literals()
    mv_hits = [(rel, text[:60]) for rel, text in mv_literals
               if moved_module_imports(text, mv_names)]
    check("mv6 no command anywhere the repo keeps one - a string literal or a comment "
          "in a .py, an eval prompt, a shell heredoc, a workflow step, a fenced block "
          "in a document - puts the plugin's scripts on sys.path and then imports a "
          "module that now lives under tools/lints, and every file the scan lists "
          "could be read (unreadable, by name: %r): %r" % (mv_unreadable, mv_hits),
          mv_hits == [] and mv_unreadable == [])
    # The walk now lists untracked files, so a half-written scratch file is in it.
    # One tracked file that parses, and three untracked ones: a `.py` and a `.json`
    # that do not, and a `.py` that does. The scan must name the first two, still
    # read the third and the tracked one, and not raise.
    import shutil
    import tempfile
    mv_fix = tempfile.mkdtemp(prefix="mv-unreadable-")
    try:
        for mv_rel, mv_text in (("kept.py", "x = 'tracked'\n"),
                                ("broken.py", "def (:\n"),
                                ("broken.json", "{not json"),
                                ("fresh.py", "y = 'untracked'\n")):
            with open(os.path.join(mv_fix, mv_rel), "w", encoding="utf-8") as fh:
                fh.write(mv_text)
        _harness.git(mv_fix, "init", "-q")
        _harness.git(mv_fix, "add", "kept.py")
        mv_fix_lits, mv_fix_bad = _shipped_literals(mv_fix)
    finally:
        # `remove_tree`, not `rmtree(ignore_errors=True)`: git writes its objects
        # read-only, and on Windows the plain call leaves the fixture behind for
        # the sweep's watched TMPDIR to report.
        _harness.remove_tree(mv_fix)
    check("mv11 an untracked .py or .json that does not parse is reported as "
          "unreadable BY NAME and the scan carries on: unreadable %r, read %r"
          % (mv_fix_bad, sorted(set(r for r, _t in mv_fix_lits))),
          sorted(r for r, _why in mv_fix_bad) == ["broken.json", "broken.py"]
          and all(why for _r, why in mv_fix_bad)
          and sorted(set(r for r, _t in mv_fix_lits)) == ["fresh.py", "kept.py"])
    mv_scripts = M.PLUGIN_REL + "/scripts"
    mv_planted = ("python3 -c \"import sys;sys.path.insert(0,'%s');import _deps;"
                  "print(1)\"" % mv_scripts)
    mv_planted_from = "sys.path.insert(0, '%s'); from _refs import x" % mv_scripts
    mv_planted_list = "sys.path.insert(0,'%s');import json, _refs" % mv_scripts
    mv_fixed = ("sys.path.insert(0,'tools/lints');sys.path.insert(0,'%s');import _deps"
                % mv_scripts)
    mv_shipped = "sys.path.insert(0,'%s');import _output;_output.install_path()" % mv_scripts
    check("mv7 the detector fires on the planted shapes - `import`, `from ... import` "
          "and a name inside a comma list - the three spellings a command uses",
          moved_module_imports(mv_planted, mv_names)
          and moved_module_imports(mv_planted_from, mv_names)
          and moved_module_imports(mv_planted_list, mv_names))
    mv_sh = ("#!/bin/sh\nrefs_rule() {\n  python3 - \"$1\" <<'PYEOF'\nimport os, sys\n"
             "sys.path.insert(0, os.path.join(\"plugins\", \"audit\", \"scripts\"))\nimport _refs\nPYEOF\n}\n")
    mv_md = "text\n\n```sh\npython3 -c \"%s\"\n```\n" % mv_planted.split('"')[1]
    mv_py = "x = 1\n# run:\n#   python3 -c \"import sys;sys.path.insert(0, '%s'); \\\n# import _deps\"\n" % mv_scripts
    mv_two = "echo hi\n\n" + mv_sh.split("\n", 1)[1]
    check("mv9 the chunk reader finds the planted command in a shell heredoc, in a "
          "fenced document block and in a `.py` comment block - and not once per file "
          "but where it sits: a heredoc two blocks below an unrelated one still counts",
          all(any(moved_module_imports(c, mv_names) for c in chunks_of(rel, text))
              for rel, text in (("a.sh", mv_sh), ("b.md", mv_md), ("c.py", mv_py),
                                ("d.sh", mv_two))))
    check("mv10 ...and its allow twin: the same heredoc with tools/lints put on the "
          "path first yields no hit, so reading every file kind did not turn the "
          "reading into a flag on every sys.path insert",
          not any(moved_module_imports(c, mv_names)
                  for c in chunks_of("e.sh", mv_sh.replace(
                      "sys.path.insert(0, os.path.join(\"plugins\", \"audit\", \"scripts\"))",
                      "sys.path.insert(0, 'tools/lints')\n"
                      "sys.path.insert(0, os.path.join(\"plugins\", \"audit\", \"scripts\"))"))))
    # The over-fire direction, which looks vacuous and is the only case that goes red
    # if the detector is widened to every sys.path insert or to every import: a
    # command that also puts tools/lints on the path works, and so does one that
    # imports a module scripts/ still holds.
    check("mv8 ...and stays quiet on a command that names tools/lints beside the "
          "scripts, on one importing a module scripts/ still holds, and on a literal "
          "with no sys.path insert at all",
          not moved_module_imports(mv_fixed, mv_names)
          and not moved_module_imports(mv_shipped, mv_names)
          and not moved_module_imports("import _deps", mv_names))

    # ------------------------------------------------------------- script_files()
    check("sf1 script_files() is py_files(SCRIPTS_DIR) - the same list, not a "
          "second walk with its own rules", M.script_files() == M.py_files(M.SCRIPTS_DIR))
    check("sf2 ...and it is MEMOISED: the identical list object comes back, which "
          "is what keeps ~37 import-time bootstraps from doing ~37 os.walks",
          M.script_files() is M.script_files())
    check("sf3 refresh=True re-walks - the case that fails if the memo becomes "
          "permanent and a selftest that just wrote a fixture file cannot see it",
          M.script_files(refresh=True) is not M.script_files.__globals__[
              "_SCRIPT_FILES_CACHE"].get("nonexistent"))
    _fx = tempfile.mkdtemp(prefix="audit-anchor-")
    try:
        with open(os.path.join(_fx, "only.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        _held = list(M.script_files())
        _fixture_files = M.script_files(root=_fx)
        check("sf4 a fixture root is answered but NOT cached: the caller gets its "
              "own directory and the real tree's memo is untouched, so a case that "
              "passes a temp dir cannot poison what every other caller reads",
              [r for r, _p in _fixture_files] == ["only.py"]
              and M.script_files() == _held
              and M.script_files() is not _fixture_files)

        # ------------------------------------------------------------ install_path()
        _installed = M.install_path()
        check("ip1 install_path() RETURNS the list it installed - never None, never "
              "empty - so a caller can assert what happened instead of trusting "
              "that an import worked for some other reason: %r" % (_installed,),
              isinstance(_installed, list) and _installed)
        check("ip2 SCRIPTS_DIR is first, and every entry is on sys.path",
              _installed[0] == M.SCRIPTS_DIR
              and all(d in sys.path for d in _installed))
        check("ip3 the day a script moved has arrived: the list is SCRIPTS_DIR plus "
              "every domain under it - config/, git/, governance/, manifest/, "
              "panel/, report/ (the first ever created), status/ and usage/, in the "
              "walk's own sorted order rather than the order they were created, and "
              "the root holds only the cross-cutting modules. This line used to call "
              "the domain set COMPLETE and name a last one; git/ arrived after that "
              "and the sentence was simply false, which is what a document claiming "
              "to be finished about a growing thing always becomes. It said `exactly "
              "one directory` for as long as the tree was flat, and editing it is "
              "what each move COSTS - the mechanism is no longer a no-op and this is "
              "where that is stated: %r" % (_installed,),
              # `install_path()` MUST see a probe directory - `test__loader.py`
              # writes one into the real tree and needs it on sys.path - so the
              # filtering is in what this case COMPARES and never in the
              # function. The sweep runs both suites at once, and without it
              # the domain list gained a neighbour's fixture for the width of
              # one `finally`. `ip5` keeps the RAW list, because idempotence is
              # a property of the call and not of the tree.
              [d for d in _installed
               if not os.path.basename(d).startswith(M.LOADER_PROBE_DIR)]
              == [M.SCRIPTS_DIR,
                             os.path.join(M.SCRIPTS_DIR, "config"),
                             os.path.join(M.SCRIPTS_DIR, "git"),
                             os.path.join(M.SCRIPTS_DIR, "governance"),
                             os.path.join(M.SCRIPTS_DIR, "manifest"),
                             os.path.join(M.SCRIPTS_DIR, "panel"),
                             os.path.join(M.SCRIPTS_DIR, "report"),
                             os.path.join(M.SCRIPTS_DIR, "status"),
                             os.path.join(M.SCRIPTS_DIR, "usage")])
        check("ip3b ...and it is DERIVED from the walk, not a constant: every entry "
              "past the root is a real directory holding at least one `.py`, so a "
              "later domain joins the list by existing rather than by being added "
              "here",
              all(os.path.isdir(d)
                  and any(f.endswith(".py") for f in os.listdir(d))
                  for d in _installed[1:]))
        check("ip4 scripts/ui/ is NOT on it, and not by an exemption: the list is "
              "derived from the `.py` walk, and ui/ holds CSS and JS only",
              os.path.isdir(os.path.join(M.SCRIPTS_DIR, "ui"))
              and os.path.join(M.SCRIPTS_DIR, "ui") not in _installed)
        _before_len = len(sys.path)
        check("ip5 idempotent: a second call returns the same list and grows "
              "sys.path by nothing",
              M.install_path() == _installed and len(sys.path) == _before_len)
        # A fixture tree with a subdirectory, which the real tree deliberately does
        # not have. Without this the whole point of the function - EVERY directory
        # holding a `.py`, not just the root - is asserted by nothing.
        os.makedirs(os.path.join(_fx, "manifest"))
        os.makedirs(os.path.join(_fx, "assets"))          # no .py: must not appear
        with open(os.path.join(_fx, "manifest", "deep.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("y = 2\n")
        with open(os.path.join(_fx, "assets", "style.css"), "w",
                  encoding="utf-8") as fh:
            fh.write("body{}\n")
        _sub = M.install_path(root=_fx)
        check("ip6 a subdirectory holding a `.py` IS installed, root first then the "
              "subdirectories sorted - the ~81 module-level sibling imports need "
              "the directory the IMPORTED file is in, not just the root: %r"
              % (_sub,),
              _sub == [_fx, os.path.join(_fx, "manifest")])
        check("ip7 ...and a subdirectory holding no `.py` is not - an editorial "
              "rule about ui/ turned into a mechanical one. Reads vacuous beside "
              "ip6 and is the only case that fails if the walk starts listing "
              "every directory it sees",
              os.path.join(_fx, "assets") not in _sub)
        for _d in _sub:
            if _d in sys.path:
                sys.path.remove(_d)
    finally:
        shutil.rmtree(_fx, ignore_errors=True)

    # --- us: which files a surface is assembled from -------------------------
    # `_surface_digest.py` asks this walk which parts no surface claims, and nothing
    # may hold its own copy of the answer, so every case here is about the ONE walk.
    # The digest taken over the assembled pages has its cases in
    # test__surface_digest.py; these are about the walk underneath it.
    _us_live = _surface_digest.surface_digests()
    check("us1 the real tree files every `ui/` part under a surface, and both "
          "surfaces come back with a digest - the case that goes red the day a "
          "directory is added under `ui/` whose name answers nobody: %r"
          % ((_us_live["error"], _us_live["unassigned"]),),
          _us_live["error"] is None and _us_live["unassigned"] == []
          and sorted(_us_live["digests"]) == sorted(M.UI_SURFACES)
          and len(set(_us_live["digests"].values())) == len(M.UI_SURFACES))
    _us_src = M.ui_surface_sources()
    # READ WITH `.get`, AND THE EMPTY TERM FIRST. A surface that stopped being
    # filed at all is what this case exists to catch, and both the label's index
    # and `min()` over an empty walk raise on exactly that input - which would
    # report the finding as a traceback with no case id on it.
    _us_sources = _us_src.get("sources") or {}
    check("us2 ...over a real set of parts rather than an empty one, and the two "
          "surfaces are not the same set - a walk that reached nothing would "
          "return the same clean shape us1 accepts: %r"
          % ({"panel": len(_us_sources.get("panel") or ()),
              "report": len(_us_sources.get("report") or ())},),
          _us_sources != {}
          and min(len(v) for v in _us_sources.values()) > 5
          and (set(_us_sources.get("panel") or ())
               != set(_us_sources.get("report") or ()))
          and "panel.html" in (_us_sources.get("panel") or ()))
    check("us3 the FILING CONVENTION is what answers, so a part added under an "
          "existing directory is covered without anyone declaring it - and an "
          "unfamiliar directory returns no surface rather than a guess",
          M.ui_surfaces_of("panel/core.js") == ("panel",)
          and M.ui_surfaces_of("panel-css/app-shell.css") == ("panel",)
          and M.ui_surfaces_of("panel.html") == ("panel",)
          and M.ui_surfaces_of("report/filters.js") == ("report",)
          and M.ui_surfaces_of("report-css/shell.css") == ("report",)
          and M.ui_surfaces_of("shared/dates.js") == M.UI_SURFACES
          and M.ui_surfaces_of("widgets/thing.js") == ())

    tmp = tempfile.mkdtemp(prefix="audit-uisrc-")
    try:
        def _us_write(rel, text):
            path = os.path.join(tmp, "scripts", *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)

        def _us_sources():
            return M.ui_surface_sources(os.path.join(tmp, "scripts"))

        _us_scripts = os.path.join(tmp, "scripts")
        _us_write("ui/panel.html", "<!doctype html>\n")
        _us_write("ui/panel/core.js", "const el = 1;\n")
        _us_write("ui/panel-css/app-shell.css", ".shell{}\n")
        _us_write("ui/report/filters.js", "const chips = 1;\n")
        _us_write("ui/report-css/shell.css", ".rshell{}\n")
        _us_write("ui/shared/dates.js", "const DAY = 1;\n")
        _us_base = _us_sources()
        check("us4 a fixture tree files both surfaces, so every case below fails "
              "for the reason it names: %r" % (_us_base["error"],),
              _us_base["error"] is None and _us_base["unassigned"] == []
              and sorted(_us_base["sources"]) == sorted(M.UI_SURFACES))

        # THE SEPARATION THE WHOLE RULE RESTS ON: a report part belongs to the report
        # alone, a panel part to the panel alone, and `shared/` to both. Asserted as
        # exact sets, because "contains" would pass a walk that filed everything
        # under every surface.
        _us_src = _us_base["sources"]
        check("us5 a report part is filed under the REPORT only and a panel part "
              "under the panel only - the separation a per-surface digest rests on: "
              "%r" % (_us_src,),
              "report/filters.js" in _us_src["report"]
              and "report/filters.js" not in _us_src["panel"]
              and "panel/core.js" in _us_src["panel"]
              and "panel/core.js" not in _us_src["report"])
        check("us6 a `shared/` part is filed under BOTH, because both assemblies "
              "list it - the one place where moving everything is the right "
              "answer: %r" % (_us_src,),
              "shared/dates.js" in _us_src["panel"]
              and "shared/dates.js" in _us_src["report"])

        # The second direction, and it looks vacuous on purpose: it passes on a walk
        # that never changes. It is the only case that fails if the walk starts
        # reading something that is not a part - a README, a dotfile.
        _us_write("ui/report/README.md", "# what these parts are\n")
        _us_write("ui/panel/README.md", "# and these\n")
        _us_write("ui/.DS_Store_probe", "junk\n")
        _us_doc = _us_sources()
        check("us8 documentation and dotfiles are NOT parts, so adding them changes "
              "no filing and reports nothing - the guard against a walk that reads "
              "everything: %r"
              % (_us_doc["sources"] == _us_base["sources"],),
              _us_doc["sources"] == _us_base["sources"]
              and _us_doc["unassigned"] == [])

        _us_write("ui/widgets/thing.js", "const w = 1;\n")
        _us_odd = _us_sources()
        os.remove(os.path.join(_us_scripts, "ui", "widgets", "thing.js"))
        check("us9 a part under a directory no surface claims is REPORTED, never "
              "dropped - a part assembled into no page is a part whose change could "
              "never turn a picture red, which is the silence this whole rule is "
              "against: %r" % (_us_odd["unassigned"],),
              _us_odd["unassigned"] == ["widgets/thing.js"]
              and _us_odd["sources"] == _us_base["sources"])

        shutil.rmtree(os.path.join(_us_scripts, "ui", "report"))
        shutil.rmtree(os.path.join(_us_scripts, "ui", "report-css"))
        _us_gone = _us_sources()
        check("us11 a surface left with no part of its own is an ERROR with the "
              "sources left empty, not the shared parts alone - that answer would be "
              "stable and comparable and would clear every picture of a surface that "
              "is no longer there: %r" % (_us_gone,),
              _us_gone["sources"] == {} and _us_gone["error"] is not None
              and "report" in _us_gone["error"])

        _us_empty = M.ui_surface_sources(os.path.join(tmp, "nowhere"))
        # The message is asserted, not merely the presence of one: an ignored
        # `onerror` leaves an empty walk, which the no-parts branch below would
        # then report in different words - a right-looking error about the wrong
        # thing, and the reader sent to look for a deleted part.
        check("us12 an absent `ui/` is reported AS UNWALKABLE, because os.walk "
              "reports a missing tree by yielding nothing and raising nothing - "
              "the exact shape a renamed directory takes: %r" % (_us_empty,),
              _us_empty["sources"] == {} and _us_empty["error"] is not None
              and "cannot be walked" in _us_empty["error"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


    # --- the spelling a published path carries -----------------------------------
    # `os.path.relpath` answers in the PLATFORM's separator. Every value routed
    # through `posix_rel` is read back by something holding the other spelling:
    # the index stores `phases/P3.json`, the journal's chained rows are compared
    # across machines, git takes a POSIX pathspec on every platform, and the panel
    # matches `theme_state()["path"]` against what the theme write returned. The
    # backslash below is `chr(92)` rather than `os.sep`, so this asks the same
    # question on the platform where `os.sep` is already "/".
    _bs = chr(92)
    _joined = os.path.join("a", "b" + _bs + "P3.json")
    check("px1 posix_rel spells a project-relative path with \"/\" whatever the "
          "platform joined it with - the index stores that spelling, so a "
          "reported path that does not use it names a file the manifest has "
          "never heard of: %r" % (M.posix_rel(_joined, "a"),),
          M.posix_rel(_joined, "a") == "b/P3.json"
          and _bs not in M.posix_rel(_joined, "a")
          and M.posix_rel(os.path.join("a", "b", "c.json"), "a") == "b/c.json")

    # THE SWEEP, AND WHY IT IS A CASE AND NOT A GREP. Two writers returned the
    # same kind of value and drifted: one journal row spelled its target with "/"
    # while the `written` list beside it kept the platform's. Fixing the pair CI
    # named left roughly twenty siblings untouched, and the list below is what
    # turns "somebody should re-run that grep" into something that fails.
    #
    # It reads SOURCE. A behavioural case cannot do this: on POSIX both spellings
    # are the same string, so every assertion about them passes without the code
    # being right.
    #
    # THE SUITES ARE IN THE LIST, not only the modules. Respelling the writers
    # turned three `test__panel_write.py` expectations red on Windows and nowhere
    # else, because each had retyped `os.path.relpath` as the value it expected
    # back - a reader holding the spelling the writer had just stopped using. A
    # rule that binds only the producing side is half a rule.
    #
    # THIS TABLE STAYS HAND-KEPT, ON THE RECORD, rather than derived from a walk
    # for `os.path.relpath(`: whether a value is PUBLISHED is a judgement about
    # what happens to it downstream, not a fact the tree states. One file here,
    # `migrate-json-encoding.py`, calls `os.path.relpath` twice and the two calls
    # answer differently - a shard path is checked for climbing out of its
    # manifest by splitting the RAW, platform-separated result on `os.sep`, which
    # a forced "/" would break on Windows by leaving nothing for that split to
    # find; the same file's `_report` path is handed to `--json` and goes through
    # `_output.posix_rel`, exactly as this table requires. A derivation keyed on
    # the call alone would have to call both rows the same thing, which is
    # unsound in both directions - so a file earns a row here by what it does
    # with the value, and that is read by a person, not a walk.
    _publishers = (
        "../plugins/audit/scripts/_output.py",
        "../tools/lints/_refs.py",
        "../tools/lints/_deps.py",
        "../plugins/audit/scripts/_ui_theme.py",
        "../plugins/audit/scripts/manifest/audit-task.py",
        "../plugins/audit/scripts/manifest/set-priority.py",
        "../plugins/audit/scripts/manifest/repair-commits.py",
        "../plugins/audit/scripts/manifest/repair-tests-add.py",
        "../plugins/audit/scripts/panel/_panel_write.py",
        "../plugins/audit/scripts/panel/_panel_state.py",
        "../plugins/audit/scripts/panel/_panel_composition.py",
        "../plugins/audit/scripts/status/_doctor_completions.py",
        "../plugins/audit/scripts/status/_doctor_trail.py",
        "../plugins/audit/scripts/governance/_invariants.py",
        "../plugins/audit/scripts/governance/_evidence_io.py",
        # THESE TWO NEVER CALLED IT AND THAT IS A DECISION, not an accident. Both
        # say so in their own words: across Windows drives `os.path.relpath`
        # RAISES, and a redactor or a log renderer that raises hands its caller an
        # exception where a token or a line was wanted. They compare resolved
        # prefixes instead. Listing them here is what stops that being
        # "simplified" back - the value they publish is a journal row and a log
        # path, so the cost of the raise is paid by the reader.
        "../plugins/audit/scripts/governance/_journal_io.py",
        "../plugins/audit/scripts/status/audit-logs.py",
        # THE READERS, all of them. `test__panel_write.py` came first because CI
        # named it; these three retyped the same idiom against the same writer and
        # nothing was looking. The value they compare is a field of a CHAINED
        # journal row, so a reader holding the other spelling is a reader that
        # disagrees with the file on disk.
        "test__panel_write.py",
        "test__journal_io.py",
        "test_audit_journal.py",
        "test_journal_writes.py",
    )
    _here = os.path.dirname(os.path.abspath(__file__))
    # ONE allowance, and it is the implementation. `posix_rel` is where the call
    # belongs; a table with no exemption for its own body would be satisfied only
    # by a helper that does not work.
    _allowed = {"_output.py": 1}
    _raw = {}
    for _rel in _publishers:
        # A FILE THIS TABLE NAMES AND CANNOT OPEN IS A FINDING, not a traceback.
        # The list is hand-kept, so a rename is the way it goes wrong, and the
        # sentinel has to be a value px2 reads rather than an exception that
        # takes every case after it down while naming none of them.
        try:
            _src = io.open(os.path.join(_here, _rel), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            _raw[_rel.rsplit("/", 1)[-1]] = -1
            continue
        # The docstring in `_output` NAMES the function it replaces, and a
        # sentence is not a call: only lines that are not comment or prose count.
        _calls = 0
        for _line in _src.splitlines():
            _stripped = _line.strip()
            if _stripped.startswith("#") or _stripped.startswith("`"):
                continue
            _calls += _line.count("os.path.relpath(")
        _raw[_rel.rsplit("/", 1)[-1]] = _calls
    check("px2 no module that publishes a path calls os.path.relpath directly, "
          "nor the suite that compares against one - one spelling reaches the "
          "reader, and on POSIX nothing behavioural can tell the two apart: %r"
          % (_raw,),
          all(n == _allowed.get(f, 0) for f, n in _raw.items())
          and len(_raw) == len(_publishers))



    # --------------------------------------------- a written list is LF on every platform
    # THE CASE THAT WOULD HAVE CAUGHT THE WINDOWS FAILURE. "the output contains no
    # \r" is not it: on Linux it cannot contain one, which is exactly why the whole
    # migration went green here and red on the windows leg. The property is asserted
    # where the PLATFORM decides it - a text stream constructed WITH translation on,
    # which any platform can build - so the fixture tells the two implementations
    # apart on the machine running this suite.
    _sink = io.BytesIO()
    _crlf = io.TextIOWrapper(_sink, encoding="utf-8", newline="\r\n")
    M.write_lf_lines(["a/b.py", "c/d.py"], _crlf)
    _crlf.flush()
    check("lf1 a stream that WOULD translate is reconfigured not to: the bytes are "
          "LF, on a fixture any platform can build. Restore the `print()` and this "
          "goes red on ubuntu, which the real bug never did: %r" % (_sink.getvalue(),),
          _sink.getvalue() == b"a/b.py\nc/d.py\n")
    _sink2 = io.BytesIO()
    _crlf2 = io.TextIOWrapper(_sink2, encoding="utf-8", newline="\r\n")
    _crlf2.write("a/b.py\nc/d.py\n")
    _crlf2.flush()
    check("lf2 ...and the fixture really does translate without the fix - measured, "
          "not remembered. This is the case that fails if the fixture stops being "
          "able to tell the buggy version from the fixed one: %r"
          % (_sink2.getvalue(),),
          _sink2.getvalue() == b"a/b.py\r\nc/d.py\r\n")
    _plain = io.StringIO()
    check("lf3 a stream with no reconfigure() (a StringIO, which every capturing "
          "selftest installs) is written to anyway rather than skipped - it does "
          "not translate in the first place",
          M.write_lf_lines(["x"], _plain) is _plain
          and _plain.getvalue() == "x\n")
    check("lf4 an empty list writes nothing at all, which is the correct answer "
          "before the migration starts and after it ends",
          M.write_lf_lines([], io.StringIO()).getvalue() == "")


    _remove_tree_cases(check)
    _sharing_cases(check)
    _finding_code_cases(check)
    _success_line_cases(check)


# --- a name another process holds open -----------------------------------------
# The clock is a counter and the pause is recorded rather than slept, so a case
# that waits out a deadline costs no wall time at all.
def _ticking(start=0.0, step=1.0):
    now = {"t": start - step}

    def clock():
        now["t"] += step
        return now["t"]
    return clock


def _refusing(refusals, answer="landed"):
    """An operation raising each of `refusals` in turn, then answering."""
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] <= len(refusals):
            raise refusals[calls["n"] - 1]
        return answer
    return op, calls


def _sharing_cases(check):
    import errno
    denial = PermissionError(errno.EACCES, "Permission denied")
    pauses = []
    real_sleep = M.time.sleep
    M.time.sleep = pauses.append
    try:
        op, calls = _refusing([denial, OSError(errno.EACCES, "denied")])
        got = M.while_shared(op, deadline=10.0, clock=_ticking())
        check("ws1 a sharing denial is waited out: the operation is tried again "
              "after a pause until the holder lets go, and its answer comes back: "
              "%r" % ((got, calls["n"], len(pauses)),),
              got == "landed" and calls["n"] == 3 and len(pauses) == 2)

        del pauses[:]
        op, calls = _refusing([OSError(errno.ENOSPC, "No space left")] * 9)
        try:
            M.while_shared(op, deadline=10.0, clock=_ticking())
            raised = None
        except OSError as exc:
            raised = exc.errno
        check("ws2 ALLOW side: an error that is not a sharing denial is raised at "
              "once - one attempt, no pause: %r" % ((raised, calls["n"], pauses),),
              raised == errno.ENOSPC and calls["n"] == 1 and pauses == [])

        del pauses[:]
        op, calls = _refusing([denial] * 99)
        try:
            M.while_shared(op, deadline=2.5, clock=_ticking())
            raised = None
        except OSError as exc:
            raised = exc.errno
        check("ws3 a denial still there at the deadline is raised as the denial, "
              "after the attempts the deadline allowed and no more: %r"
              % ((raised, calls["n"]),),
              raised == errno.EACCES and calls["n"] == 4)

        del pauses[:]
        had = M.SHARING_WAIT_SECONDS
        M.SHARING_WAIT_SECONDS = 3.0
        op, calls = _refusing([denial] * 99)
        try:
            M.while_shared(op, clock=_ticking(start=100.0))
            raised = None
        except OSError as exc:
            raised = exc.errno
        finally:
            M.SHARING_WAIT_SECONDS = had
        check("ws4 no deadline given means SHARING_WAIT_SECONDS from the first "
              "reading of the clock, not an unbounded wait: %r"
              % ((raised, calls["n"]),),
              raised == errno.EACCES and calls["n"] == 3)
    finally:
        M.time.sleep = real_sleep

    readings = [(name, M.sharing_denied(exc)) for name, exc in (
        ("PermissionError EACCES", denial),
        ("OSError EACCES", OSError(errno.EACCES, "denied")),
        ("PermissionError EPERM", PermissionError(errno.EPERM, "not permitted")),
        ("FileExistsError", FileExistsError(errno.EEXIST, "exists")),
        ("ValueError", ValueError("x")))]
    check("ws5 EACCES in either spelling is a sharing denial; EPERM, a taken name "
          "and a non-OS error are not: %r" % (readings,),
          [r[1] for r in readings] == [True, True, False, False, False])


# --- the success line ---------------------------------------------------------
def _door(argv, run, summarize, keep_verbose=False):
    """`(stdout, code, argv the run saw)` for one pass through `terse_cli`."""
    import contextlib
    import io

    seen = []

    def recording(args):
        seen.append(list(args))
        return run(args)

    held = io.StringIO()
    with contextlib.redirect_stdout(held):
        code = M.terse_cli(recording, argv, summarize, keep_verbose=keep_verbose)
    return held.getvalue(), code, seen


def _success_line_cases(check):
    long_lines = ["[verb] did the thing to R1", "  detail one", "  written: plan.json"]

    def long_run(args, code=0):
        for line in long_lines:
            print(line)
        return code

    def name_it(lines):
        return "%s; wrote %s" % (lines[0], lines[-1].split(": ")[-1])

    out, code, seen = _door(["x", "--flag"], long_run, name_it)
    check("sl1 a success prints ONE line naming what was done and the record, "
          "within the byte bound: %r" % (out,),
          code == 0 and out == "[verb] did the thing to R1; wrote plan.json\n"
          and len(out.rstrip("\n").encode("utf-8")) <= M.SUCCESS_LINE_BYTES
          and seen == [["x", "--flag"]])

    out, code, seen = _door(["x", "--verbose", "--flag"], long_run, name_it)
    check("sl2 `--verbose` prints the verb's own text byte for byte, and the "
          "verb never sees the flag: %r" % ((out, seen),),
          out == "\n".join(long_lines) + "\n" and seen == [["x", "--flag"]])

    out, code, _seen = _door(["x"], lambda a: long_run(a, code=2), name_it)
    check("sl3 a refusal prints in full, unchanged, with its own exit code - "
          "the deny twin of sl1: %r" % (out,),
          code == 2 and out == "\n".join(long_lines) + "\n")

    out, code, _seen = _door(["x"], long_run, lambda lines: None)
    check("sl4 a success the verb's summary declines (it carries something "
          "still owed) prints in full", out == "\n".join(long_lines) + "\n")

    def broken(lines):
        raise ValueError("no summary")

    out, code, _seen = _door(["x"], long_run, broken)
    check("sl5 a summary that raises costs the caller nothing: the long form "
          "prints and the exit code stands",
          code == 0 and out == "\n".join(long_lines) + "\n")

    def one_line(args):
        print("P1.3-abc")
        return 0

    out, code, _seen = _door(["next-id"], one_line, name_it)
    check("sl6 an output that is already one line within the bound is kept "
          "exactly - a caller may be reading it as a value: %r" % (out,),
          out == "P1.3-abc\n")

    out, code, seen = _door(["red", "--", "pytest", "--verbose"], long_run,
                            name_it)
    check("sl7 a `--verbose` after `--` belongs to the command it precedes: it "
          "is passed on and does not ask for the long form: %r" % ((out, seen),),
          seen == [["red", "--", "pytest", "--verbose"]]
          and out.count("\n") == 1)

    out, code, _seen = _door(["x", "--json"], long_run, name_it)
    check("sl8 `--json` keeps its payload whole", out == "\n".join(long_lines) + "\n")

    token = "audit-stamp: {%s}" % ("\"k\":1," * 60,)
    out, code, _seen = _door(["take"], long_run,
                             lambda lines: ("took a stamp", token))
    check("sl15 a payload the caller carries byte for byte is printed whole "
          "after the success text - the one way a line exceeds the bound: %r"
          % (out[:80],),
          out == "took a stamp %s\n" % (token,)
          and len(token.encode("utf-8")) > M.SUCCESS_LINE_BYTES)

    import contextlib
    import io
    held = io.StringIO()
    with contextlib.redirect_stdout(held):
        M.terse_cli(long_run, ["x", "--full"], name_it, long_form=("--full",))
    check("sl14 a verb's own long-form flag keeps the long form, and only for "
          "that verb: %r" % (held.getvalue(),),
          held.getvalue() == "\n".join(long_lines) + "\n"
          and _door(["x", "--full"], long_run, name_it)[0].count("\n") == 1)

    out, code, seen = _door(["x", "--verbose"], long_run, name_it,
                            keep_verbose=True)
    check("sl9 a verb that reads `--verbose` itself is handed it: %r" % (seen,),
          seen == [["x", "--verbose"]] and out == "\n".join(long_lines) + "\n")

    wide = M.success_line("é" * 300)
    check("sl10 a line that does not fit is cut at a character boundary, within "
          "the bound, and SAYS it was cut: %r" % (wide[-60:],),
          len(wide.encode("utf-8")) <= M.SUCCESS_LINE_BYTES
          and wide.endswith(M.CLIPPED_MARK)
          and wide[:-len(M.CLIPPED_MARK)] == "é" * len(wide[:-len(M.CLIPPED_MARK)]))
    check("sl11 a line that fits is folded onto one line and otherwise kept",
          M.success_line("a\n  b  c") == "a b c")
    kept = M.success_line("x" * 300, "; written: plan.json")
    check("sl13 the record a verb wrote is kept whole and the cut falls in the "
          "text before it, saying so: %r" % (kept[-70:],),
          len(kept.encode("utf-8")) <= M.SUCCESS_LINE_BYTES
          and kept.endswith(M.CLIPPED_MARK + "; written: plan.json")
          and M.success_line("did it", "; written: plan.json")
          == "did it; written: plan.json")

    def dies(args):
        print("said before dying")
        raise RuntimeError("boom")

    import contextlib
    import io
    held = io.StringIO()
    raised = None
    with contextlib.redirect_stdout(held):
        try:
            M.terse_cli(dies, ["x"], name_it)
        except RuntimeError as exc:
            raised = exc
    check("sl12 an exception escaping the verb still prints what it said first, "
          "then propagates: %r" % (held.getvalue(),),
          raised is not None and held.getvalue() == "said before dying\n")


# --- removing a scratch tree --------------------------------------------------
def _refusing_tree():
    """A temp tree whose one file refuses deletion until made writable, on
    every platform CI runs: the file is read-only (windows checks the file's
    own attribute, as it does for git's loose objects) inside a read-only
    directory (POSIX checks the directory)."""
    import tempfile
    top = tempfile.mkdtemp(prefix="output-remove-tree-")
    inner = os.path.join(top, "objects")
    os.makedirs(inner)
    leaf = os.path.join(inner, "loose")
    with open(leaf, "w") as fh:
        fh.write("written read-only, as git writes an object\n")
    os.chmod(leaf, 0o444)
    os.chmod(inner, 0o555)
    return top


def _remove_tree_cases(check):
    import shutil
    top = _refusing_tree()
    try:
        shutil.rmtree(top, ignore_errors=True)
        # The fixture's own proof: plain `rmtree(ignore_errors=True)`, the call
        # the helper replaces, leaves this tree behind and says nothing. Run as
        # a superuser nothing refuses, and this case reports that rather than
        # letting the next one pass over a fixture that never resisted.
        check("rt0 the fixture refuses plain rmtree(ignore_errors=True): the "
              "tree survives it silently: %r" % (os.path.exists(top),),
              os.path.exists(top))
        remove = getattr(M, "remove_tree", None)
        gone = remove(top) if remove else None
        check("rt1 RED-FIRST: remove_tree removes a tree whose files refuse "
              "deletion until made writable, and answers True: helper %r, "
              "answered %r, still there %r"
              % (remove is not None, gone, os.path.exists(top)),
              remove is not None and gone is True and not os.path.exists(top))
        raised, again = None, None
        try:
            again = remove(top) if remove else None
        except Exception as exc:
            raised = exc
        check("rt2 ...and on a tree that is already gone it returns without "
              "raising, answering True: answered %r, raised %r"
              % (again, raised), remove is not None and raised is None
              and again is True)
    finally:
        # Removed with the harness's binding of the same helper; a subject that
        # left the tree behind has already failed rt1 above.
        _harness.remove_tree(top)
    _remove_tree_link_cases(check)


def _remove_tree_link_cases(check):
    """The fallback pass makes the TREE writable, never what a link in it
    points at: a chmod through a link changes its target, which may be any
    file on the machine."""
    import shutil
    import stat
    import tempfile
    outside_dir = tempfile.mkdtemp(prefix="output-remove-tree-outside-")
    top = None
    try:
        outside = os.path.join(outside_dir, "precious")
        with open(outside, "w") as fh:
            fh.write("not part of the tree being removed\n")
        # READ-ONLY, and compared against its own mode as read back rather
        # than a literal. Windows keeps one permission fact per file, the
        # read-only attribute, so a mode with the owner-write bit set reads
        # back as 666 whatever the other bits said; a writable target would
        # then look the same before and after a chmod through the link. The
        # owner-write bit is the one fact both platforms keep, and the
        # fallback's own chmod sets it.
        os.chmod(outside, stat.S_IREAD)
        before = stat.S_IMODE(os.stat(outside).st_mode)
        check("rt3a the link target is read-only before the removal, so a "
              "chmod through the link would show on every platform: mode %o"
              % (before,), not before & stat.S_IWRITE)
        top = _refusing_tree()
        inner = os.path.join(top, "objects")
        os.chmod(inner, 0o755)
        try:
            os.symlink(outside, os.path.join(inner, "link-out"))
            linked = None
        except (OSError, NotImplementedError, AttributeError) as exc:
            linked = "%s: %s" % (type(exc).__name__, exc)
        os.chmod(inner, 0o555)
        if linked is not None:
            _harness.skip(check, "rt3", "os.symlink is refused here (%s)"
                          % (linked,), True)
            return
        shutil.rmtree(top, ignore_errors=True)
        forced = os.path.exists(top)
        gone = M.remove_tree(top) if forced else None
        mode = stat.S_IMODE(os.stat(outside).st_mode)
        check("rt3 RED-FIRST: a tree the plain removal could not take (%r) is "
              "removed by the fallback pass (%r) without changing the mode of "
              "a file OUTSIDE it that a link inside it points at: mode %o, "
              "was %o" % (forced, gone, mode, before),
              forced and gone is True and mode == before
              and os.path.exists(outside))
    finally:
        if top:
            _harness.remove_tree(top)
        _harness.remove_tree(outside_dir)

# --- every validator finding carries the code of its rule --------------------
# THE WALK STARTS AT `validate()` AND FOLLOWS THE CALLS, across modules, rather
# than reading a list of files. A producer is a finding producer because the
# validator reaches it; a table of modules is the thing that left the ADO
# hierarchy findings - built in one module and turned into findings in another -
# outside every file it named.
VALIDATE_ROOT = ("_manifest_rules", "validate")


def _module_paths():
    out = {}
    for _rel, path in M.py_files(M.SCRIPTS_DIR):
        out[os.path.basename(path)[:-3]] = path
    return out


def _module_names(tree, paths):
    """`{local name: (module, attr or None)}` for the imports and aliases."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in paths:
                    names[a.asname or a.name] = (a.name, None)
        elif isinstance(node, ast.ImportFrom) and node.module in paths:
            for a in node.names:
                names[a.asname or a.name] = (node.module, a.name)
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and names.get(node.value.value.id, (None, 1))[1] is None):
            names[node.targets[0].id] = (names[node.value.value.id][0],
                                         node.value.attr)
    return names


def validator_reach(sources=None):
    """`{(module, function): FunctionDef}` - everything `validate()` calls.

    `sources` maps a module name to source text read in place of its file, so a
    case can walk a mutated module without writing it into the tree.
    """
    paths, trees, reach = _module_paths(), {}, {}
    sources = sources or {}

    def tree(mod):
        if mod not in trees:
            if mod in sources:
                trees[mod] = ast.parse(sources[mod])
            else:
                with open(paths[mod], encoding="utf-8") as fh:
                    trees[mod] = ast.parse(fh.read())
        return trees[mod]

    todo = [VALIDATE_ROOT]
    while todo:
        mod, name = todo.pop()
        if (mod, name) in reach or mod not in paths:
            continue
        top = dict((n.name, n) for n in tree(mod).body
                   if isinstance(n, ast.FunctionDef))
        names = _module_names(tree(mod), paths)
        if name not in top:
            target = names.get(name)
            if target and target[1]:
                todo.append(target)
            continue
        reach[(mod, name)] = top[name]
        for call in ast.walk(top[name]):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Name):
                todo.append((mod, call.func.id))
            elif (isinstance(call.func, ast.Attribute)
                  and isinstance(call.func.value, ast.Name)
                  and names.get(call.func.value.id, (None, 1))[1] is None
                  and call.func.value.id in names):
                todo.append((names[call.func.value.id][0], call.func.attr))
    return reach


def _is_finding_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "finding"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "_output")


def _items(arg):
    """What a literal list, tuple or comprehension puts into a list."""
    if isinstance(arg, (ast.List, ast.Tuple)):
        return list(arg.elts)
    if isinstance(arg, (ast.ListComp, ast.GeneratorExp)):
        return [arg.elt]
    return None


def _feeding_functions(reach):
    """`(module, name)` of every same-module function whose return value a
    reached function extends straight into `f` or `findings`."""
    out = set()
    for (mod, _name), fn in reach.items():
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "extend"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("f", "findings") and node.args
                    and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name)):
                out.add((mod, node.args[0].func.id))
    return out


def finding_sites(sources=None):
    """`(visited, uncoded, codes)` over every finding site `validate()` reaches.

    A FINDING LIST is `f`, `findings`, or the first half of any `(x, w)` a
    reached function returns. A SITE is each item that enters one: an `append`,
    an `extend` or `+=` of a literal list or comprehension, an assignment of
    one, or a list returned in place - the first half of a returned pair, or,
    in a function whose whole return is extended into a finding list, a literal
    list it returns early. An `extend` of a list another reached function built
    is a pass-through, and that function's own sites are walked.
    """
    visited, uncoded, codes = 0, [], {}
    reach = validator_reach(sources)
    feeds = _feeding_functions(reach)
    for (mod, name), fn in sorted(reach.items()):
        lists = set(("f", "findings"))
        for node in ast.walk(fn):
            if (isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)
                    and len(node.value.elts) == 2
                    and isinstance(node.value.elts[0], ast.Name)):
                lists.add(node.value.elts[0].id)
            # A function whose whole return value is extended into a finding
            # list returns findings under whatever name it builds them in.
            if ((mod, name) in feeds and isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Name)):
                lists.add(node.value.id)
        items = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in lists and node.args):
                if node.func.attr == "append":
                    items.append(node.args[0])
                elif node.func.attr == "extend":
                    items.extend(_items(node.args[0]) or [])
            elif (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add)
                  and isinstance(node.target, ast.Name)
                  and node.target.id in lists):
                items.extend(_items(node.value) or [])
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name)
                  and node.targets[0].id in lists):
                items.extend(_items(node.value) or [])
            elif (isinstance(node, ast.Return)
                  and isinstance(node.value, ast.Tuple) and node.value.elts):
                items.extend(_items(node.value.elts[0]) or [])
            # ...and a function whose whole return is a finding list may return
            # a literal one early, before it names the list it builds.
            elif ((mod, name) in feeds and isinstance(node, ast.Return)
                  and node.value is not None):
                items.extend(_items(node.value) or [])
        for arg in items:
            visited += 1
            where = "%s.%s:%d" % (mod, name, arg.lineno)
            if not _is_finding_call(arg):
                uncoded.append(where)
                continue
            code = arg.args[0] if arg.args else None
            if isinstance(code, ast.Constant) and isinstance(code.value, str):
                codes.setdefault(code.value, []).append(where)
    return visited, uncoded, codes

def _finding_code_cases(check):
    one = M.finding("rules.x.y", "task P1: bad")
    check("fc1 a finding IS its sentence to every reader - equal, joined and "
          "serialised as the plain string - and carries the code beside it: %r"
          % (M.finding_code(one),),
          one == "task P1: bad" and json.dumps([one]) == '["task P1: bad"]'
          and "; ".join([one, one]) == "task P1: bad; task P1: bad"
          and M.finding_code(one) == "rules.x.y"
          and M.finding_code("task P1: bad") is None)
    visited, uncoded, codes = finding_sites()
    check("fc2 every finding site the validator has - each append to a finding "
          "list and each finding list returned as a literal - builds its "
          "finding with _output.finding(code, ...), and the walk VISITED them "
          "(%d sites; a walk that matched nothing would pass): uncoded %r"
          % (visited, uncoded), visited > 0 and uncoded == [])
    shared = dict((c, where) for c, where in codes.items() if len(where) > 1)
    check("fc3 ...and no literal code names two sites - a code is one rule, so "
          "a second site under it would let two rules key as one: %r" % (shared,),
          codes and shared == {})
    # The phase-gate family - `meta.phaseGate`, `meta.gateBudgetMs`,
    # `meta.coupling` - reaches the validator as warnings, through a check that
    # once wrote into the caller's list, a shape the walk never follows. So a
    # code stripped from one of its sites left fc2 green.
    family = ("_check_phase_gate", "_check_coupling",
              "_check_phase_gate_derived", "_comma_joined_gate")
    reached = sorted(set(w.split(":")[0].split(".")[1]
                         for ws in codes.values() for w in ws
                         if w.startswith("_manifest_phases.")) & set(family))
    check("fc5 the walk reaches every check of the phase-gate family and finds "
          "each coded: reached %r of %r" % (reached, sorted(family)),
          reached == sorted(family))
    phases_path = _module_paths()["_manifest_phases"]
    with open(phases_path, encoding="utf-8") as fh:
        phases_src = fh.read()
    coded = '_output.finding(\n                    "phases.coupling.head-shape",\n'
    stripped = phases_src.replace(coded, "(\n")
    _v, bare_sites, _c = finding_sites({"_manifest_phases": stripped})
    check("fc6 ...so a _check_coupling warning stripped of its code turns the "
          "walk red at that site (the mutation landed: %r): uncoded %r"
          % (phases_src.count(coded) == 1 and coded not in stripped, bare_sites),
          phases_src.count(coded) == 1 and coded not in stripped
          and [w.rsplit(":", 1)[0] for w in bare_sites]
          == ["_manifest_phases._check_coupling"])
    early = '[_output.finding(\n            "phases.coupling.array",\n'
    stripped = phases_src.replace(early, "[(\n")
    _v, bare_sites, _c = finding_sites({"_manifest_phases": stripped})
    check("fc7 ...and so does one returned early as a literal list, before the "
          "check names the list it builds (the mutation landed: %r): uncoded %r"
          % (phases_src.count(early) == 1 and early not in stripped, bare_sites),
          phases_src.count(early) == 1 and early not in stripped
          and [w.rsplit(":", 1)[0] for w in bare_sites]
          == ["_manifest_phases._check_coupling"])
    import _manifest_io as _mio
    import _manifest_rules
    acme = _mio.load_manifest(os.path.join(M.REPO_ROOT, "examples", "acme-store",
                                           "audit-plan.json"))
    task = acme["phases"][0]["tasks"][0]
    task.update({"status": "bogus", "risk": "extreme", "blockedBy": [5],
                 "dependsOn": [6, "NOPE"]})
    acme["fileIndex"]["zzz.py"] = ["P9.9"]
    acme["phases"][0]["budgetUSD"] = "x"
    acme.setdefault("meta", {})["ado"] = {"conventions": {"requiredFields": 5},
                                          "fields": {"x": []}}
    acme["meta"]["areas"] = {"bad": 5}
    # A declared parent loop: the ADO hierarchy findings are built in one module
    # and turned into findings in another, the path a list of files missed.
    acme["meta"]["ado"]["phaseWorkItems"] = False
    acme["phases"][0].update({"ado": {"id": 501}, "adoParent": {"id": 500}})
    acme["phases"][1].update({"ado": {"id": 500}, "adoParent": {"id": 501}})
    acme["bugs"] = [{"id": "x"}]
    found = _manifest_rules.validate(acme)[0]
    bare = [str(x)[:50] for x in found if not M.finding_code(x)]
    check("fc4 ...and a manifest broken across every producer module comes back "
          "from validate() with a code on every finding (%d findings): %r"
          % (len(found), bare), len(found) > 10 and bare == [])

def _project_of_manifest_cases(check):
    """The one answer to which project a manifest belongs to."""
    base = _harness.fixture_root("audit-project-of-")

    def mk(*parts):
        path = os.path.join(base, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def plan(*parts):
        path = os.path.join(mk(*parts), "audit-plan.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")
        return path

    try:
        repo = mk("repo")
        mk("repo", ".git")
        mk("repo", "docs", "audit", ".claude", "logs")
        mk("repo", "docs", "audit", "docs", "audit", ".claude")
        got = M.project_of_manifest(plan("repo", "docs", "audit"))
        check("po1 RED-FIRST: a .claude/ a gate left in the plan's own docs/audit "
              "is never taken for the project - the git toplevel answers "
              "(mutation: accept any .claude/ -> docs/audit): %r" % (got,),
              got == repo)
        got = M.project_of_manifest(plan("repo", "docs", "audit", "docs",
                                         "audit"))
        check("po2 ...nor is one anywhere inside a DOUBLED record directory: "
              "%r" % (got,), got == repo)
        sub = mk("repo", "packages", "web")
        mk("repo", "packages", "web", ".claude")
        got = M.project_of_manifest(plan("repo", "packages", "web", "docs",
                                         "audit"))
        check("po3 ALLOW: a project nested in a larger repository keeps its own "
              ".claude/ root, outside the record directory (mutation: answer "
              "the git toplevel alone -> red): %r" % (got,), got == sub)
        wt = mk("wt")
        with open(os.path.join(wt, ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: /elsewhere\n")
        mk("wt", "docs", "audit", ".claude")
        got = M.project_of_manifest(plan("wt", "docs", "audit"))
        check("po4 a linked worktree's .git FILE is a toplevel too: %r" % (got,),
              got == wt)
        bare = mk("bare")
        got = (M.project_of_manifest(plan("bare", "docs", "audit")),
               M.project_of_manifest(plan("bare", "plans")))
        check("po5 markerless: a default-layout plan belongs to the directory "
              "above docs/audit, any other to its own directory: %r" % (got,),
              got == (bare, os.path.join(bare, "plans")))
        ex = mk("repo", "examples", "store")
        mk("repo", "examples", "store", ".claude")
        got = M.project_of_manifest(plan("repo", "examples", "store"))
        check("po6 ALLOW: a plan kept beside its own project's .claude/, outside "
              "any record directory, belongs to that directory: %r" % (got,),
              got == ex)
    finally:
        _harness.remove_tree(base)

    # ---------------------------------- a project derived by dirname arithmetic
    md = _harness.fixture_root("audit-dirname-project-")
    try:
        def _md(rel, text):
            full = os.path.join(md, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(text)

        _md("assign.py", "import os\n"
                         "def f(manifest_path):\n"
                         "    project = os.environ.get('X') or os.path.dirname(\n"
                         "        os.path.abspath(manifest_path))\n"
                         "    return project\n")
        _md("sub/kw.py", "import os\n"
                         "def g(mpath, h):\n"
                         "    return h(project_dir=os.path.dirname(mpath))\n")
        _md("ret.py", "import os\n"
                      "def project_root(mpath):\n"
                      "    return os.path.dirname(os.path.abspath(mpath))\n")
        _md("quiet.py", "import os\n"
                        "def out_dir(manifest_path):\n"
                        "    base = os.path.dirname(os.path.abspath(manifest_path))\n"
                        "    project = resolve(manifest_path)\n"
                        "    return base, project\n")
        _md("listed.py", "import os\n"
                         "def legacy(mpath):\n"
                         "    proj = os.path.dirname(mpath)\n"
                         "    return proj\n")
        md_table = (("listed.py", "legacy", "debt"),
                    ("gone.py", "vanished", "a site deleted since"))
        hits = L.manifest_dirname_project_violations(md, table=md_table)
        files = sorted(set(f for f, _w in hits))
        check("md1 RED-FIRST: a project taken as dirname of a manifest path is "
              "reported whether it is assigned, passed as a keyword or returned "
              "from a project-named function: %r" % (hits,),
              "assign.py" in files and "sub/kw.py" in files and "ret.py" in files)
        check("md2 ALLOW: dirname of a manifest bound to a name that is not a "
              "project, and a project asked of a resolver, are silent - and so "
              "is a site the table names (a lint reading every dirname, or "
              "ignoring the table, fails here): %r" % (hits,),
              "quiet.py" not in files and "listed.py" not in files)
        check("md3 a table row whose site no longer derives a project is "
              "reported, so the table cannot keep unused permission: %r"
              % (hits,),
              any(f == "gone.py" and "vanished" in w for f, w in hits))
    finally:
        _harness.remove_tree(md)
    check("md4 ...and the real tree derives no project by dirname of a manifest "
          "with MANIFEST_DIRNAME_PROJECTS empty: %r"
          % (L.manifest_dirname_project_violations(),),
          L.MANIFEST_DIRNAME_PROJECTS == ()
          and L.manifest_dirname_project_violations() == [])


def _selftest():
    def body(check):
        _cases(check)
        _project_of_manifest_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__output.py --selftest\n")
    raise SystemExit(2)
