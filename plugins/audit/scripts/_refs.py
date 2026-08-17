#!/usr/bin/env python3
"""
The script paths documents name, checked against the files that have to be there.

About 150 places in this repo spell a path to a `.py` under `plugins/audit/` — the
command files that tell the orchestrator what to run, CI's own steps, the guide, the
plugin README, the schema descriptions, the worked example's shell scripts. Not one of
them was ever checked against the filesystem:

  * `validate-manifest.py` compares `fileIndex` against task `files` bidirectionally and
    never stats anything, so both halves can agree about a file that is gone;
  * `_deps.guide_enumeration()` matches by BASENAME, so `### plugins/audit/scripts/
    _areas.py` keeps passing on the day `_areas.py` moves into a subdirectory;
  * `_help.source_drift()` is the only `os.path.isfile` on a script path anywhere in the
    tree, and it covers three citations.

So a path can rot today, silently, and a restructure that moves files is exactly the
event that would rot many at once. Same shape as `_areas.rule_drift()` and
`_deps.map_drift()`: a document makes a claim, the code says what is true, and the two
are compared every run instead of trusted.

EVERY MATCH IS RETURNED, NOT ONLY THE BROKEN ONES. `referenced_paths()` is the count, and
the count is itself a check: a regex that quietly stops matching reports "0 missing",
which reads exactly like a clean tree. The selftest holds a floor under the total and
under four individual surfaces for that reason, and records the surfaces that are
legitimately zero today so they are accepted rather than unnoticed.

TWO MATCHING MODES, AND THE SECOND IS WHY THE FIRST IS SAFE. In a document, `scripts/
x.py` means this plugin's file and nothing else, so BARE matching (anchor optional) is
right. Inside the plugin's own `.py` files it is not: `hooks/guard-secrets-read.py`
carries `'scripts/build.py'` inside a bash payload as a fixture for a CONSUMER repo's
file, which no anchor precedes and which must never be looked for here. ANCHORED matching
requires `plugins/audit/`, `${CLAUDE_PLUGIN_ROOT}/`, `$CLAUDE_PLUGIN_ROOT/` or the
`$scripts/` shell variable in front, which drops that fixture and still catches
`hooks/require-plan.py`'s three real `${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py`
strings. Both claims are pinned on the real files, not on a fixture that could encode the
same assumption twice.

DELIBERATELY NOT SCANNED, each because a stale path there is correct rather than broken:

  * `CHANGELOG.md` — a v0.9.0 entry naming a path that has since moved is a true
    statement about v0.9.0. Rewriting released history to keep a lint quiet is worse than
    the lint.
  * `docs/design/` — dated design records. Same argument: they describe the tree as it
    was when the decision was taken.

`docs/audit/audit-report.{html,md}` are generated FROM the manifest and are not scanned
either; `manifest_moved_files()` checks the manifest itself, which is the source those
two are rendered from.

KNOWN LIMIT, STATED RATHER THAN HIDDEN. Matching is per line, so a path split across two
adjacent string literals is invisible — `_deps.py` spells one as `"...plugins/audit/
scripts/" "_deps.py --render..."` and this module does not see it. Joining the file first
would not help: the break is inside the token either way. A path written on one line is
the shape everything else in the tree uses.

This module carries no `--selftest` of its own any more; its 34 cases live in
`plugins/audit/tests/test__refs.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. The fixture CONSTANTS went with them, and that is
the one thing about this move worth knowing: a lint that scans the tree lives in the
tree it scans, so a fixture path spelled with an anchor in front of it is a REAL
reference to a file that exists for four milliseconds, and `c5` reports it. Every
fixture path over there is built from `PLUGIN_REL`; the surface changed name
(`scripts/` to `tests/`, both ANCHORED) and the rule did not.
"""

import json
import os
import re
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

# REPO_ROOT rather than "the plugin root": every `rel` this module produces already
# starts with `plugins/audit/`, so it is joined to the directory the plugin tree hangs
# UNDER, and joining it to the plugin's own directory would look for
# `plugins/audit/plugins/audit/scripts/...`. Re-exported off `_output` rather than
# derived again from this file's own `__file__` — two derivations of one directory is
# one directory and one place for it to go wrong.
REPO_ROOT = _output.REPO_ROOT
PLUGIN_REL = "plugins/audit"


# --- what is scanned ----------------------------------------------------------
BARE = "bare"
ANCHORED = "anchored"

# Surface -> matching mode. A file path is one surface; a directory is every readable
# file under it, recursively. Order is the order violations are reported in.
SURFACES = (
    ("plugins/audit/commands", BARE),
    ("plugins/audit/reference", BARE),
    ("plugins/audit/agents", BARE),
    ("plugins/audit/README.md", BARE),
    ("plugins/audit/schema", BARE),
    (".github/workflows/ci.yml", BARE),
    ("tools", BARE),
    ("examples", BARE),
    ("PLUGIN-BUILD-GUIDE.md", BARE),
    ("CONTRIBUTING.md", BARE),
    ("CLAUDE.md", BARE),
    ("README.md", BARE),
    ("SECURITY.md", BARE),
    # The plugin's own sources, where an unanchored `scripts/x.py` is a fixture about
    # somebody else's repo rather than a reference to ours. See the module docstring.
    ("plugins/audit/hooks", ANCHORED),
    ("plugins/audit/scripts", ANCHORED),
    # `tests/` is the plugin's Python too, and ANCHORED for a reason that is already
    # visible rather than anticipated: `hooks/_config.py` carries `"tests/test_cart.py"`
    # and `"tests/cart_test.py"` as fixtures for a CONSUMER repo's test globs, and when
    # that file's suite migrates those fixtures move into this directory. A bare match
    # here would then look for that consumer-repo filename inside the plugin's own
    # tests/ and report this tree as broken because a hook knows what a Python test is
    # usually called. (The path is described rather than written: this file is itself
    # an anchored surface, and spelling it here would BE a reference to a file that
    # does not exist - which is the trap the header warns about, and which the first
    # run of this very change walked into twice.)
    ("plugins/audit/tests", ANCHORED),
)

# Excluded on purpose, with the reason attached rather than left to a commit message.
# The selftest reads this table: an entry that also appears in SURFACES would be two
# tables disagreeing about the same file, which is the failure this pairing prevents.
EXCLUDED = (
    ("CHANGELOG.md",
     "released history: a path that has since moved was true when it was written"),
    ("docs/design/",
     "dated design records: they describe the tree as it was at the decision"),
    ("docs/audit/audit-report.html",
     "generated from the manifest, which manifest_moved_files() checks directly"),
    ("docs/audit/audit-report.md",
     "generated from the manifest, which manifest_moved_files() checks directly"),
)

# Bare surfaces are prose and configuration in half a dozen formats; anchored surfaces
# are the plugin's Python and nothing else.
_TEXT_EXT = (".md", ".json", ".jsonl", ".yml", ".yaml", ".sh", ".mjs", ".js",
             ".html", ".css", ".txt", ".py")
_ANCHORED_EXT = (".py",)

# `<name>` and `*` are inside the character class ON PURPOSE: a placeholder and a glob
# are references too, and dropping them at the regex would make them invisible instead
# of classified. missing_references() separates them out and counts them.
_SEG = r"[A-Za-z0-9_.<>*-]+"
_TAIL = r"(?:%s/)*%s\.py" % (_SEG, _SEG)
_DIR = r"(?:scripts|hooks)/"
_ROOT_ANCHOR = r"(?:plugins/audit/|\$\{CLAUDE_PLUGIN_ROOT\}/|\$CLAUDE_PLUGIN_ROOT/)"
# `$scripts` is examples/*.sh's variable for the scripts directory, so it STANDS IN FOR
# `plugins/audit/scripts/` rather than preceding it — which is why it cannot just join
# the alternation above and needs its own branch and its own group.
_SCRIPTS_VAR = r"\$scripts/"

# `tests/` gets its own branch instead of joining `_DIR`, and the anchor is REQUIRED on
# it in both modes — this is the only directory whose bare name means somebody else's
# repo more often than it means ours. `scripts/x.py` in a document is unambiguous;
# `tests/test_cart.py` is what half the prose about testing a CONSUMER project says, and
# `hooks/_config.py` already carries two of those as fixtures. Requiring the anchor
# removes that whole class rather than asking each future document to phrase itself
# around a lint, and it costs nothing real: every reference to this plugin's own test
# tree from outside it is written `plugins/audit/tests/...` anyway.
_TESTS_DIR = r"tests/"

_BARE_RE = re.compile(r"%s?(%s%s)|%s(%s)|%s(%s%s)"
                      % (_ROOT_ANCHOR, _DIR, _TAIL, _SCRIPTS_VAR, _TAIL,
                         _ROOT_ANCHOR, _TESTS_DIR, _TAIL))
_ANCHORED_RE = re.compile(r"%s(%s%s)|%s(%s)|%s(%s%s)"
                          % (_ROOT_ANCHOR, _DIR, _TAIL, _SCRIPTS_VAR, _TAIL,
                             _ROOT_ANCHOR, _TESTS_DIR, _TAIL))


def _match_rel(match):
    """The repo-relative path a match names, whichever branch of the pattern fired."""
    if match.group(1):
        return "%s/%s" % (PLUGIN_REL, match.group(1))
    if match.group(3):
        return "%s/%s" % (PLUGIN_REL, match.group(3))
    return "%s/scripts/%s" % (PLUGIN_REL, match.group(2))


def is_placeholder(rel):
    """True for a documented shape rather than a file: `scripts/<name>.py`, `*.py`.

    Named because three callers ask the same question and a repeated `"<" in rel or
    "*" in rel` is a rule with three homes."""
    return "<" in rel or "*" in rel


# --- reading the surfaces -----------------------------------------------------
def _surface_files(surface_root, surface, mode):
    """Repo-relative paths of every file `surface` contributes, sorted.

    Not `_output.py_files`: that walk is `.py`-only and returns names relative to the
    directory it was handed, while most surfaces here are Markdown/JSON/YAML and a
    violation has to name a path a reader can open from the repo root.

    A surface that does not exist yields nothing, which would be silent — the selftest
    asserts separately that every SURFACES entry is a real path, so an entry pointing at
    nothing fails by name instead of reading as a clean surface.
    """
    exts = _ANCHORED_EXT if mode == ANCHORED else _TEXT_EXT
    path = os.path.join(surface_root, surface.replace("/", os.sep))
    if os.path.isfile(path):
        return [surface]
    found = []
    for root, dirnames, filenames in os.walk(path):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in sorted(filenames):
            if not name.endswith(exts):
                continue
            rel = os.path.relpath(os.path.join(root, name), surface_root)
            found.append(rel.replace(os.sep, "/"))
    found.sort()
    return found


def referenced_paths(surface_root=None):
    """[(surface_rel, lineno, raw, rel), ...] — EVERY script/hook path any surface names.

    `raw` is the text as written (anchor included, so a reader can find it); `rel` is the
    repo-relative path it resolves to. Broken and intact alike: the total is a check in
    its own right, because a pattern that stops matching reports nothing wrong.

    An unreadable surface file RAISES rather than being skipped. A lint that quietly
    reads fewer files than it thinks reports a clean tree, and this one is read by cases
    that assert a floor — a skip would lower the floor's meaning without lowering the
    floor.
    """
    root = surface_root if surface_root is not None else REPO_ROOT
    hits = []
    for surface, mode in SURFACES:
        pattern = _ANCHORED_RE if mode == ANCHORED else _BARE_RE
        for rel_file in _surface_files(root, surface, mode):
            path = os.path.join(root, rel_file.replace("/", os.sep))
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            for lineno, line in enumerate(lines, 1):
                for match in pattern.finditer(line):
                    hits.append((rel_file, lineno, match.group(0), _match_rel(match)))
    return hits


def counts_by_surface(hits=None, surface_root=None):
    """{surface: n} with EVERY surface present, including the ones at zero.

    Seeded from SURFACES rather than accumulated from the hits, so a surface that stops
    producing matches reads as `0` and a surface that has been deleted from the table
    reads as absent. Those are different facts and a defaultdict would merge them.

    Keyed by SURFACE, not by file: a hit in `plugins/audit/commands/task.md` counts
    against `plugins/audit/commands`.
    """
    hits = referenced_paths(surface_root) if hits is None else hits
    counts = dict((surface, 0) for surface, _mode in SURFACES)
    for rel_file, _lineno, _raw, _rel in hits:
        for surface, _mode in SURFACES:
            if rel_file == surface or rel_file.startswith(surface + "/"):
                counts[surface] += 1
                break
    return counts


# --- existence ----------------------------------------------------------------
def missing_references(repo_root=None, surface_root=None):
    """{"missing": [...], "placeholders": [...], "checked": n, "total": n}.

    `missing` is every reference whose file is not there; `placeholders` is every
    `<name>`/`*` shape, kept and counted rather than dropped, because a placeholder is
    still a thing a reader will follow. `checked` is how many concrete paths were
    actually stat'd, which is what tells "nothing is broken" apart from "nothing was
    looked at" — the two are the same empty list otherwise.

    TWO ROOTS, SEPARABLE ON PURPOSE. `surface_root` is where the documents are read from
    and `repo_root` is where their paths are resolved. Point the second at an empty
    directory with the first left alone and every concrete reference must come back
    missing; that case is the only proof that the existence test is a real stat rather
    than something that short-circuits to "fine".
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    hits = referenced_paths(surface_root)
    missing = []
    placeholders = []
    for hit in hits:
        rel = hit[3]
        if is_placeholder(rel):
            placeholders.append(hit)
            continue
        if not os.path.isfile(os.path.join(root, rel.replace("/", os.sep))):
            missing.append(hit)
    return {"missing": missing, "placeholders": placeholders,
            "checked": len(hits) - len(placeholders), "total": len(hits)}


# --- the plan's own file lists ------------------------------------------------
_MANIFEST_REL = "docs/audit/audit-plan.json"
_PHASES_REL = "docs/audit/phases"


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _py_index(repo_root, rel_root=None):
    """{basename: [repo-relative path, ...]} for every `.py` under one tree.

    Basename-keyed because that is the question a moved file poses: the recorded path is
    gone, is the FILE gone too or did it just move? `_deps` already forbids two `.py`
    sharing a basename, so a list with more than one entry means the tree is broken in a
    way that lint reports by name.

    `rel_root` defaults to the plugin, which is what `manifest_moved_files()` asks about;
    `tool_basename_drift()` asks the same question of three narrower trees, and one walk
    answering for both is a walk that cannot drift from itself."""
    index = {}
    base = os.path.join(repo_root, (rel_root or PLUGIN_REL).replace("/", os.sep))
    for root, dirnames, filenames in os.walk(base):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(root, name), repo_root)
            index.setdefault(name, []).append(rel.replace(os.sep, "/"))
    return index


def _recorded_paths(repo_root):
    """([(source, path), ...], [(rel, problem), ...]) — what the plan says it touches.

    Both the index's `fileIndex` keys and every shard task's `files`, each carrying where
    it was found so a violation names one place to go and fix. A shard that will not
    parse becomes a problem rather than a shorter list."""
    recorded = []
    unreadable = []
    try:
        plan = _read_json(os.path.join(repo_root, _MANIFEST_REL.replace("/", os.sep)))
    except (OSError, ValueError) as exc:
        return recorded, [(_MANIFEST_REL, "unreadable: %s" % exc)]

    file_index = plan.get("fileIndex")
    if file_index is None:
        unreadable.append((_MANIFEST_REL, "carries no fileIndex"))
    elif not isinstance(file_index, dict):
        unreadable.append((_MANIFEST_REL, "fileIndex is %s, not an object"
                           % type(file_index).__name__))
    else:
        for key in sorted(file_index):
            recorded.append(("%s fileIndex" % _MANIFEST_REL, key))

    phases_dir = os.path.join(repo_root, _PHASES_REL.replace("/", os.sep))
    if not os.path.isdir(phases_dir):
        unreadable.append((_PHASES_REL, "no such directory"))
        return recorded, unreadable
    for name in sorted(os.listdir(phases_dir)):
        if not name.endswith(".json"):
            continue
        rel = "%s/%s" % (_PHASES_REL, name)
        try:
            shard = _read_json(os.path.join(phases_dir, name))
        except (OSError, ValueError) as exc:
            unreadable.append((rel, "unreadable: %s" % exc))
            continue
        for task in shard.get("tasks") or []:
            for path in task.get("files") or []:
                recorded.append(("%s task %s" % (rel, task.get("id") or "?"), path))
    return recorded, unreadable


def manifest_moved_files(repo_root=None):
    """{"moved": [...], "gone": [...], "unreadable": [...], "checked": n}.

    Restricted to `.py` under `plugins/audit/` — the manifest records project files of
    every kind, and only this plugin's own sources are ours to move.

    THE ASYMMETRY IS THE POINT. A recorded path whose file is gone but whose BASENAME
    exists elsewhere in the plugin is a MOVE, and a document still pointing at the old
    place is stale: that is `moved`, and it is loud. A recorded path whose basename
    exists nowhere is a DELETION, and a done task that says it deleted a file is correct
    history: that is `gone`, and it is not a violation. Classified rather than dropped,
    because "no moves found" and "nothing was examined" must not print the same way —
    `checked` is what separates them.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    recorded, unreadable = _recorded_paths(root)
    index = _py_index(root)
    prefix = PLUGIN_REL + "/"
    moved = []
    gone = []
    checked = 0
    for source, path in recorded:
        if not isinstance(path, str) or not path.endswith(".py") \
                or not path.startswith(prefix):
            continue
        checked += 1
        if os.path.isfile(os.path.join(root, path.replace("/", os.sep))):
            continue
        elsewhere = [p for p in index.get(os.path.basename(path), ()) if p != path]
        if elsewhere:
            moved.append((source, path, ", ".join(elsewhere)))
        else:
            gone.append((source, path))
    return {"moved": moved, "gone": gone, "unreadable": unreadable, "checked": checked}


# --- the basenames tools/ names -----------------------------------------------
# THE HOLE THIS CLOSES. Everything above matches a PATH — `<dir>/<name>.py` — per line.
# `tools/` does not write paths: it runs the plugin's scripts as subprocesses, and it
# builds each command by joining a directory constant with a bare filename, so the line
# carries `'panel-server.py'` and nothing a path pattern can catch. Nine such sites went
# unseen by every lint in this tree and failed at RUN time instead, inside a browser gate
# that only a machine with Playwright installed ever executes.
TOOLS_REL = "tools"

# The four trees a `.py` basename written in `tools/` may legitimately name. The first
# two are what a tool RUNS. `tools/` itself is not a loophole: a tool's own usage line
# names its own file (`--check` instructions, an `argparse` prog) and a sibling tool is a
# real file too — leaving it out would make every usage string a violation, and a lint
# everyone has to argue with is a lint that gets deleted. The test tree is here for the
# same reason and was added by this lint's FIRST run, which reported the cross-language
# pin's own name: a tool that says where its behaviour is pinned is doing the right
# thing, and that name goes stale on a rename exactly like any other.
TOOL_NAME_TREES = (PLUGIN_REL + "/scripts", PLUGIN_REL + "/hooks",
                   PLUGIN_REL + "/tests", TOOLS_REL)

# A basename, not a path: at least one leading word character (so `*.py` and the `.py`
# in a bare `.py file(s)` are not tokens), then the name, then `.py` not followed by a
# word character (so `x.pyc` is not read as `x.py`). `<name>.py` cannot match either —
# `<` and `>` are outside the class and the name must reach `.py` uninterrupted — which
# is why nothing here calls `is_placeholder()`: the placeholder shapes are excluded at
# the regex, and stating that is cheaper than a filter that can never fire.
_TOOL_BASENAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py(?![A-Za-z0-9_])")


def _tool_known_basenames(repo_root):
    """{basename: [repo-relative path, ...]} across TOOL_NAME_TREES, merged.

    Merged rather than kept per tree because the question is only "does a file with this
    name exist anywhere a tool may name", and a name found in two of the trees is a
    `_deps.layer_violations()` matter, not this one's."""
    known = {}
    for tree in TOOL_NAME_TREES:
        for name, rels in _py_index(repo_root, tree).items():
            known.setdefault(name, []).extend(rels)
    return known


def tool_basename_drift(repo_root=None):
    """{"unknown": [(tool_rel, lineno, basename), ...], "checked": n, "files": n}.

    THE RULE, PLAINLY: a `.py` basename literal written anywhere under `tools/` must name
    a file that exists under one of TOOL_NAME_TREES. Comments and docstrings count — a
    tool's prose names the script it drives as often as its code does, and a reader
    following stale prose is misled exactly as far as a stale argument list would take
    a process.

    WHAT IT CATCHES: a RENAME and a DELETION. Both are the shape where the basename stops
    existing anywhere, which is the only shape a name-only rule can see.

    WHAT IT DOES NOT CATCH, SAID RATHER THAN IMPLIED: a MOVE. `render-report.py` filed
    under a domain folder still has the same basename, so a tool naming it stays green —
    which is correct, because a tool that resolves BY BASENAME is genuinely unaffected by
    the move. That is the whole division of labour here and it is worth being explicit
    about: this lint cannot make a join safe, so the joins were replaced by resolvers
    (`resolveScript` in the JavaScript tool, `resolve_script` in the Python one) and this
    lint covers what a resolver cannot — a name that has ceased to exist at all. A lint
    whose limits are written down is worth more than one that implies it covers
    everything; nothing here should be read as proof that a tool still points at the
    right file, only that it points at a file.

    NOT SCANNED: nothing. Every readable text file under `tools/` is read, `.md` and
    `.mjs` and `.py` alike, and `checked` is the number of basename literals examined
    while `files` is the number of files read. Those two counts are the check on the
    check: an empty `unknown` list means one thing when 20 literals across 3 files were
    examined and something entirely different when the walk found nothing at all.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    known = _tool_known_basenames(root)
    files = _surface_files(root, TOOLS_REL, BARE)
    unknown = []
    checked = 0
    for rel_file in files:
        path = os.path.join(root, rel_file.replace("/", os.sep))
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        for lineno, line in enumerate(lines, 1):
            for match in _TOOL_BASENAME_RE.finditer(line):
                checked += 1
                if match.group(0) not in known:
                    unknown.append((rel_file, lineno, match.group(0)))
    return {"unknown": unknown, "checked": checked, "files": len(files)}


# --- the selftest sweep -------------------------------------------------------
# `for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py` stops at the top level:
# put a file one directory down, the glob does not match it, the loop never runs it, and
# the sweep EXITS 0. Not a check that fires later — a green build over a partial tree.
# cf50f9f converted the copies that were still flat; this is what keeps them converted.
SWEEP_FIND = "find plugins/audit/hooks plugins/audit/scripts -name '*.py'"
SWEEP_FLAT = "for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py"

# Every document that shows a reader how to run the suites. The commit that did the
# conversion named three; the tree carries six, and pinning three of six would leave the
# other three free to rot in exactly the way this constant exists to prevent.
SWEEP_DOCS = (
    ".github/workflows/ci.yml",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "PLUGIN-BUILD-GUIDE.md",
    "docs/audit/audit-plan.json",
    ".claude/skills/refactoring-the-assembled-ui/SKILL.md",
)


def sweep_glob_drift(repo_root=None):
    """[(doc, problem), ...] — every sweep document that has drifted back to the glob.

    Scoped to the EXECUTABLE shape, `SWEEP_FLAT`, not to the substring `scripts/*.py`.
    The guide says "the real static import graph of `scripts/*.py`" and "`LAYERS` groups
    every `scripts/*.py` basename", both correct prose about a set of files; a check
    aimed at the substring would fail the guide for describing itself, and a check
    everyone has to argue with is a check that gets removed.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    out = []
    for rel in SWEEP_DOCS:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, "unreadable: %s" % exc))
            continue
        if SWEEP_FIND not in text:
            out.append((rel, "does not carry the recursive sweep %r" % SWEEP_FIND))
        if SWEEP_FLAT in text:
            out.append((rel, "still carries the flat sweep %r" % SWEEP_FLAT))
    return out


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than falling through to the docstring dump, which would
        # exit 0 with no word about the flag. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_refs.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__refs.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
