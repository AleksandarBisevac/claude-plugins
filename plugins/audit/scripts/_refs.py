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
`hooks/require-plan.py`'s three real `${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py`
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

THE SUBJECT GREW, AND IT GREW ALONG ONE LINE: what one file CLAIMS about another, checked
against the tree. A document naming a script that is gone is the original case; a document
whose sweep command names a retired glob, a published `curl` pinned to a moving ref, and a
link pointing at a page nobody kept are the same shape. `doc_link_drift()` is the newest and
the one that needed no precedent at all: nothing here had ever asked whether a document is
*reachable*, so a page could be added, linked once, and silently orphaned by the next edit to
whatever linked it.

KNOWN LIMIT, STATED RATHER THAN HIDDEN. Matching is per line, so a path split across two
adjacent string literals is invisible — `_deps.py` spells one as `"...plugins/audit/
scripts/" "_deps.py --render..."` and this module does not see it. Joining the file first
would not help: the break is inside the token either way. A path written on one line is
the shape everything else in the tree uses.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__refs.py`, byte-identical labels and all — see
`plugins/audit/tests/_harness.py`. The fixture CONSTANTS went with them, and that is
the one thing about this move worth knowing: a lint that scans the tree lives in the
tree it scans, so a fixture path spelled with an anchor in front of it is a REAL
reference to a file that exists for four milliseconds, and `c5` reports it. Every
fixture path over there is built from `PLUGIN_REL`; the surface changed name
(`scripts/` to `tests/`, both ANCHORED) and the rule did not.
"""

import hashlib
import json
import os
import posixpath
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
    # The two documents the audience split added. A quickstart names no script path
    # today and the compatibility contract names the validators that hold it - both
    # are listed so that a path either one grows is stat'd from the day it is written,
    # rather than the day somebody remembers this table exists.
    ("QUICKSTART.md", BARE),
    ("COMPATIBILITY.md", BARE),
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

# Basenames a tool INVENTS rather than names, with the reason each one exists.
#
# WHY THIS TABLE, AND WHY IT IS NOT A WEAKENING. The rule below is about REFERENCES:
# a tool naming a plugin script that has been renamed or deleted. A `.py` file a
# tool's own cases WRITE INTO A TEMP DIRECTORY is not a reference to anything - it is
# a fixture, and it must end in `.py` because the scanner under test only reads `.py`
# files, so it cannot be spelled around. The one deliberately-missing name is the
# same shape from the other side: a case proves the resolver fails loud, which needs
# a name that resolves to nothing.
#
# The distinction is not mechanical - "created here" needs dataflow this lint does
# not do - so it is DECLARED, one line per name, and the declaration is CHECKED: an
# entry that no longer appears anywhere under tools/ is reported by `tool_basename_
# drift()` exactly as a missing reference is. Every basename not named here is still
# a violation when it names nothing, which is what keeps the table from becoming a
# blanket.
#
# BEFORE ADDING A ROW: a name a case only TALKS ABOUT does not belong here, however
# much it looks like the entries below - it is spelled around instead, and
# `tool_basename_drift()`'s docstring lists the spellings and says which file uses
# each. A row is for a name that has to be on disk with the Python extension.
TOOL_FIXTURE_BASENAMES = (
    ("test_fx.py",
     "count-ui-pins: a fixture suite written into a temp dir so `collect()` has one "
     "literal and one computed pin to tell apart"),
    ("test_slice.py",
     "count-ui-pins: the fixture for the historical defect - one `.index()`-bounded "
     "slice must count as one order pin, not as the two calls that bound it"),
    ("test_split.py",
     "count-ui-pins: a pin whose literal is split across two lines, the blind spot "
     "that made a documented grep under-report"),
    ("big.py",
     "count-ui-pins: the over-the-limit half of `long_files()`'s pair"),
    ("small.py",
     "count-ui-pins: the under-the-limit half of that same pair, which is what makes "
     "the answer 1 rather than 2 or 0"),
    ("no-such-script-in-this-tree.py",
     "capture-demo-gif: a name that resolves to NOTHING on purpose, so a case can "
     "prove `resolve_script()` raises rather than returning something plausible"),
)


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

    ONE DECLARED EXCEPTION, ITSELF CHECKED. `TOOL_FIXTURE_BASENAMES` names the `.py`
    files a tool's own cases write into a temp directory - not references, and not
    spellable around, because the scanners under test only read `.py`. `staleFixtures`
    reports any entry nothing writes any more, so the table cannot quietly outlive
    what it describes; see the comment above it for why the distinction is declared
    rather than derived.

    AND IF YOU MET THIS RULE WITH A FIXTURE, THE TABLE IS PROBABLY NOT WHERE THE
    NAME GOES (F68). That exception is for a name that has to exist ON DISK carrying
    the Python extension, because the scanner under test opens nothing else. A name a
    case only TALKS ABOUT is spelled around instead, and the tree already holds a
    spelling for each reason there is to want one:

      * drop the extension, where nothing reads it - `sweep-selftests.py` starts its
        fixture child by path and the interpreter does not care what it is called;
      * borrow the JavaScript module extension, where the rule under test cannot tell
        the extensions apart - `gate-parity.py`'s gate pattern accepts every one it
        may see, so its invented gates are faithful fixtures rather than evasions;
      * ASSEMBLE the literal from pieces, where the Python shape itself is the
        fixture - `prove-gates.py` and this lint's own suite both do. The pattern
        above wants a word character immediately in front of the extension, and the
        tail of an assembled name starts with a quote instead.

    It is a spelling and not an exemption class because a fixture nothing creates is
    indistinguishable, to this rule or to any reader of it, from a reference that has
    gone stale - so an exemption for it would be a place to declare away the one
    defect the rule exists to find. What was wrong was never the rule; it was that
    two authors in a row inferred all of the above from a red build.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    known = _tool_known_basenames(root)
    fixtures = dict(TOOL_FIXTURE_BASENAMES)
    files = _surface_files(root, TOOLS_REL, BARE)
    unknown = []
    seen_fixtures = set()
    checked = 0
    for rel_file in files:
        path = os.path.join(root, rel_file.replace("/", os.sep))
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        for lineno, line in enumerate(lines, 1):
            for match in _TOOL_BASENAME_RE.finditer(line):
                checked += 1
                name = match.group(0)
                if name in fixtures:
                    seen_fixtures.add(name)
                    continue
                if name not in known:
                    unknown.append((rel_file, lineno, name))
    stale = sorted((name, "declared a tool fixture, but nothing under %s writes it "
                          "any more" % (TOOLS_REL,))
                   for name in fixtures if name not in seen_fixtures)
    return {"unknown": unknown, "checked": checked, "files": len(files),
            "staleFixtures": stale}


# --- absolute paths used to REACH a file ----------------------------------------
# The rule is narrower than "no absolute path anywhere", and the narrowness is the
# whole design. An absolute path is legitimate as DATA - `validate_registry` is
# handed `{"root": "/Users/me/proj"}` precisely to check that it warns, and the
# guard suites classify bash strings full of `/tmp/...` - and it is legitimate as a
# SYSTEM location, which is why `capture-demo-gif.py` carries a list of font paths
# under `/usr/share/fonts`. What is never legitimate is reaching a file with one:
# it encodes one machine's layout into a repository other people check out.
#
# So the check is SYNTACTIC POSITION, not the literal. A path that appears as a
# module specifier or as the first argument of a read/write call is a reach; the
# same string inside a list, a dict or a test fixture is not. That distinction is
# what gives this rule zero false positives on the fixtures above, and it is also
# its limit: a reach through a VARIABLE is invisible here, exactly as
# `tool_basename_drift` cannot see a move. Said rather than implied.
#
# This repo already forbids the Python half of the problem by a stronger rule -
# `_output.depth_sensitive_paths()` lets no `.py` under `scripts/` read `__file__`
# outside the pinned preamble, so no module may derive its own location at all.
# There was no equivalent for JavaScript, and that gap is what this closes.
# The examples below deliberately write the forbidden shape as `<ABS>` rather than
# spelling a leading slash inside quotes. This function reads TEXT, comments
# included - as `tool_basename_drift` does and for its reason - so a comment that
# showed the real literal would be reported by the rule it documents. That is the
# same trap `test__refs.py` avoids by BUILDING every fixture path from
# `M.PLUGIN_REL` instead of writing it, and it caught this file on its first run.
_REACH_RES = (
    # `import x from '<ABS>'`, `export … from "<ABS>"`, `import('<ABS>')`
    re.compile(r"""\bfrom\s+(['"])(?P<p>[^'"]+)\1"""),
    re.compile(r"""\bimport\s*\(\s*(['"])(?P<p>[^'"]+)\1"""),
    re.compile(r"""\brequire\s*\(\s*(['"])(?P<p>[^'"]+)\1"""),
    # Node's file API and Python's, first argument only.
    re.compile(r"""\b(?:readFileSync|writeFileSync|readFile|writeFile|createReadStream|"""
               r"""createWriteStream)\s*\(\s*(['"])(?P<p>[^'"]+)\1"""),
    re.compile(r"""\b(?:io\.)?open\s*\(\s*(['"])(?P<p>[^'"]+)\1"""),
)

# A reach may be absolute only with a reason recorded here, the way EXCLUDED does
# it. Empty today, and an entry is a decision rather than a convenience.
REACH_ALLOWED = ()

_REACH_SURFACES = ("tools", "plugins/audit/scripts", "plugins/audit/hooks",
                   "plugins/audit/tests")


def absolute_reach_violations(repo_root=None):
    """{"violations": [(rel, lineno, path)], "checked": n, "files": n}.

    A reach is a module specifier or the first argument of a read/write call. An
    absolute one hard-codes one machine's layout into a checkout, so it fails here
    unless `REACH_ALLOWED` records a reason.

    `checked` counts EVERY reach found, relative ones included, and that is the
    check on the check rather than a statistic: an empty `violations` list means one
    thing when hundreds of reaches were examined and something entirely different
    when the regexes matched nothing at all - which is what a typo in one of them
    would look like, and it would look exactly like a clean tree.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    allowed = set(REACH_ALLOWED)
    violations = []
    checked = 0
    files = 0
    for surface in _REACH_SURFACES:
        for rel_file in _surface_files(root, surface, BARE):
            path = os.path.join(root, rel_file.replace("/", os.sep))
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except (IOError, OSError):
                # Naming it beats skipping it: an unreadable file is not a clean one.
                violations.append((rel_file, 0, "<unreadable>"))
                continue
            files += 1
            for lineno, line in enumerate(lines, 1):
                for rex in _REACH_RES:
                    for match in rex.finditer(line):
                        spec = match.group("p")
                        checked += 1
                        if spec.startswith("/") and spec not in allowed:
                            violations.append((rel_file, lineno, spec))
    return {"violations": violations, "checked": checked, "files": files}


# --- what a command declares vs what the README says it takes -------------------
# The args cell ends at an UNESCAPED pipe. Half these rows carry `\\|` inside
# them (`push [bugs\\|tasks\\|all] ...`), and a lazy `.*?` up to the first `|`
# truncates the cell there -- which reported six commands as missing flags that
# were plainly written two characters further along. Measured before believing:
# the first version of this check produced 20 findings, of which 2 were real.
_CMD_ROW = re.compile(r"^\|\s*`/audit:([a-z-]+)`\s*\|((?:\\\||[^|])*)\|",
                      re.MULTILINE)
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def command_flag_drift(repo_root=None):
    """{"missing": [(command, flag), ...], "checked": n} -- flags the README omits.

    THE RULE: every flag a command's `argument-hint` declares must appear in that
    command's row of the README's command table. A SUBSET check and deliberately
    not equality: the two are written for different readers, and the README's
    column legitimately carries prose (`[scope/goals - you'll be interviewed]`)
    and escaped pipes that no frontmatter string would.

    Why it exists (F36, and it was already true when written): `/audit:status`
    grew `--gate` and `--fail-on` and its README row said `-`; `/audit:doctor`
    grew `--deep` and its row still said `[--json]`. A capability nobody can find
    is the defect this repo keeps meeting, and a second copy of a list with
    nothing comparing it is how it comes back.

    A command with no `argument-hint`, or with no README row, is not a finding:
    the first takes no arguments and the second is `counts_by_surface`' business.
    Silence there is an answer, not a gap.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    readme = os.path.join(root, "plugins", "audit", "README.md")
    cmd_dir = os.path.join(root, "plugins", "audit", "commands")
    try:
        with open(readme, "r", encoding="utf-8") as fh:
            rows = dict((m.group(1), m.group(2)) for m in _CMD_ROW.finditer(fh.read()))
    except (OSError, UnicodeDecodeError):
        return {"missing": [], "checked": 0}

    missing, checked = [], 0
    for name in sorted(os.listdir(cmd_dir) if os.path.isdir(cmd_dir) else []):
        if not name.endswith(".md"):
            continue
        cmd = name[:-3]
        if cmd not in rows:
            continue
        try:
            with open(os.path.join(cmd_dir, name), "r", encoding="utf-8") as fh:
                head = fh.read(4096)
        except (OSError, UnicodeDecodeError):
            continue
        hint = re.search(r"^argument-hint:\s*(.+)$", head, re.MULTILINE)
        if not hint:
            continue
        checked += 1
        row_flags = set(_FLAG.findall(rows[cmd]))
        for flag in sorted(set(_FLAG.findall(hint.group(1)))):
            if flag not in row_flags:
                missing.append((cmd, flag))
    return {"missing": missing, "checked": checked}


# --- the selftest sweep -------------------------------------------------------
# `for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py` stops at the top level:
# put a file one directory down, the glob does not match it, the loop never runs it, and
# the sweep EXITS 0. Not a check that fires later — a green build over a partial tree.
# cf50f9f converted the copies that were still flat; this is what keeps them converted.
# THE SWEEP IS A RUNNER NOW, and this rule followed the reason rather than the
# wording. It began as "the documented sweep must be the RECURSIVE find, never the
# flat glob", because a flat glob silently stopped visiting a subdirectory and
# nothing went red. `tools/sweep-selftests.py` walks the tree through
# `_output.py_files` - the same recursive walk the lints use - and adds the two
# checks neither hand-written loop had: the `N/M cases passed` contract and the
# `--covered` skip. So a document telling a reader to run EITHER loop is now the
# defect: the flat one for the old reason, the hand-written recursive one because it
# is strictly weaker than the thing it would be standing in for.
SWEEP_RUNNER = "tools/sweep-selftests.py"
SWEEP_FIND = "find plugins/audit/hooks plugins/audit/scripts -name '*.py'"
SWEEP_FLAT = "for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py"

# Retired shapes, each with the word a violation is reported under. A tuple so the
# two are checked by one loop: they failed for different reasons and are now the
# same kind of finding, and a second `if` is how the two would drift apart.
RETIRED_SWEEPS = ((SWEEP_FLAT, "flat sweep"),
                  (SWEEP_FIND, "hand-written sweep"))

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
    # A skill about deciding what to make faster necessarily quotes the sweep, and a
    # document that shows it owes the runner like every other. Added WITH the skill
    # rather than after it: the alternative is one document carrying the command and
    # standing outside the rule about the command, which is the shape this list
    # exists to prevent.
    ".claude/skills/choosing-what-to-optimize/SKILL.md",
)


# THE REGION EACH SWEEP DOCUMENT IS ACTUALLY CHECKED OVER. Both halves of the rule
# below are about a COMMAND — what a reader or CI is told to RUN — and a whole-file
# substring cannot tell a command from a sentence about one. Both directions were
# reproduced before this existed, and the quiet one is the dangerous one:
#
#   * a document whose prose says "the sweep must be `find ...`" while the block a
#     reader would actually run is a flat glob of some other shape SATISFIED the
#     requirement — green over exactly the partial tree `SWEEP_FIND` exists to prevent;
#   * a document warning "never write `for f in .../*.py ...`" was reported as still
#     carrying the flat sweep, i.e. red for describing the check. That is the same
#     failure `_panel_viewer.py`'s docstring hit from the other side, and rewording the
#     document is the weaker repair: nothing stops the next author writing it again.
#
# There is no AST to reach for here — these documents are Markdown, YAML and JSON, not
# Python — so the structural move is the one `_executable_raw_refs` already makes for
# published fetch instructions: read the runnable region, not the prose around it. One
# rule per format, and a format with no rule is a LOUD violation rather than a silent
# fallback to the whole file, which would put the hole straight back.
_MD_EXT = (".md",)
_YAML_EXT = (".yml", ".yaml")
_JSON_EXT = (".json",)

# Markdown's runnable region, shared with `_executable_raw_refs` below rather than
# spelled twice: "what a reader is told to run" is one idea, and two fence patterns
# would be two answers to it the day somebody adds a language tag to one of them.
_FENCE_RE = re.compile(r"```(?:bash|sh|shell|console)\n(.*?)```", re.S)

# `run:` in a workflow, inline (`run: make x`) or as a block scalar (`run: |`). The
# indent captured is the key's own, so a block ends at the first non-blank line that is
# not indented deeper than it — which is what YAML itself means by the block.
_YAML_RUN_RE = re.compile(r"^(\s*)(?:-\s+)?run:[ \t]*(.*)$")

# The manifest is data, not prose with fences, so its runnable region is named rather
# than pattern-matched: `meta.buildCommands` is the map of commands the orchestrator
# RUNS. A task description that quotes a sweep is prose in this file exactly as it is
# in a Markdown paragraph, and it is out of scope for the same reason.
_BUILD_COMMANDS_PATH = ("meta", "buildCommands")


def _yaml_run_scripts(text):
    """Every `run:` script in a workflow, joined by newlines."""
    out = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        match = _YAML_RUN_RE.match(lines[i])
        i += 1
        if not match:
            continue
        indent = len(match.group(1))
        inline = match.group(2).strip()
        if inline and inline[0] not in "|>":
            out.append(inline)
            continue
        while i < len(lines):
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            out.append(line)
            i += 1
    return "\n".join(out)


def _json_build_commands(text):
    """The manifest's `meta.buildCommands` values joined, or None if it will not parse.

    An absent `buildCommands` yields the empty string, not None: the document parsed
    and simply runs nothing, which the caller must report as "does not carry the
    recursive sweep" rather than as a broken file.
    """
    try:
        node = json.loads(text)
    except ValueError:
        return None
    for key in _BUILD_COMMANDS_PATH:
        if not isinstance(node, dict):
            return ""
        node = node.get(key)
        if node is None:
            return ""
    if not isinstance(node, dict):
        return ""
    return "\n".join("%s" % (value,) for _key, value in sorted(node.items()))


def _runnable_text(rel, text):
    """`(runnable, problem)` — the part of `rel` a reader is told to RUN, or why not.

    Exactly one of the two is None. `problem` covers the two ways this can fail to
    produce an answer, and both are violations rather than skips: a format nobody has
    written a rule for, and a document of a known format that will not parse.
    """
    if rel.endswith(_MD_EXT):
        return "\n".join(f.group(1) for f in _FENCE_RE.finditer(text)), None
    if rel.endswith(_YAML_EXT):
        return _yaml_run_scripts(text), None
    if rel.endswith(_JSON_EXT):
        runnable = _json_build_commands(text)
        if runnable is None:
            return None, "will not parse as JSON; its commands cannot be read"
        return runnable, None
    return None, ("no runnable-region rule for this format, so the sweep cannot be "
                  "checked without falling back to the whole file")


def sweep_glob_drift(repo_root=None):
    """[(doc, problem), ...] — every sweep document not running the sweep runner.

    Scoped to the RUNNABLE REGION of each document (`_runnable_text`), and to the
    EXECUTABLE SHAPE within it — `SWEEP_FLAT`, never the substring `scripts/*.py`. The
    guide says "the real static import graph of `scripts/*.py`" and "`LAYERS` groups
    every `scripts/*.py` basename", both correct prose about a set of files; a check
    aimed at the substring would fail the guide for describing itself, and a check
    everyone has to argue with is a check that gets removed. The region scope is that
    same argument carried to its end: a document may now quote EITHER sweep in prose,
    including the retired one it is warning against, and only what it tells someone to
    run is judged.
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
        runnable, problem = _runnable_text(rel, text)
        if problem is not None:
            out.append((rel, problem))
            continue
        if SWEEP_RUNNER not in runnable:
            out.append((rel, "does not carry the sweep runner %r" % SWEEP_RUNNER))
        for shape, label in RETIRED_SWEEPS:
            if shape in runnable:
                out.append((rel, "still carries the %s %r" % (label, shape)))
    return out


# --- is the sweep list the whole set? -----------------------------------------
# `SWEEP_DOCS` is hand-written, and until this rule existed nothing said it was
# COMPLETE. A new document telling a reader to run the retired glob was green twice
# over: `sweep_glob_drift()` never opens a document that is not in the list, and
# nothing else in the tree reads a runnable region looking for a sweep. So the weaker
# half of the pair was not the rule but the LIST, and a list nothing checks is the
# shape every other derived table in this file exists to avoid.
#
# Written while the list was still complete - measured, zero unlisted carriers - which
# is the only cheap moment to start holding it. A completeness rule adopted after the
# drift arrives is a backlog, not a gate.
#
# THE SCAN SEES ONLY FORMATS `_runnable_text` HAS A RULE FOR, and that is the guarantee
# rather than a gap to apologise for: the extension set is DERIVED from the three format
# constants, so the day somebody teaches `_runnable_text` a fourth format this scan
# starts reading it without being told.
SWEEP_DOC_EXT = _MD_EXT + _YAML_EXT + _JSON_EXT

# Every shape that makes a document a sweep document, with the word it is reported
# under. The runner belongs here for the same reason the two retired globs do, and it
# is the half that is easy to leave out: a document teaching the sweep CORRECTLY must
# be in the list so that `sweep_glob_drift()` keeps it correct the day the runner is
# renamed, and one teaching a retired glob must be in the list so that the same check
# can fail it at all. One tuple, one loop - as two `if`s they would drift apart.
SWEEP_SHAPES = ((SWEEP_RUNNER, "sweep runner"),) + RETIRED_SWEEPS

# DIRECTORIES THIS REPO DOES NOT KEEP, and the walk over what is left. Both moved to
# `_output` when the prose-number scan needed the same answer: that scan is in the
# anchor at layer 0, this module is at layer 1, and a copy at layer 0 would be the
# two-prune-lists defect one layer down. The reasoning - why `.gitignore` and not a
# hand list, why only the unambiguous half of its format, why not `git ls-files` -
# went with the code and is not restated here.
#
# THE NAMES STAY, as three aliases rather than three wrappers: this module's cases
# call them, and a wrapper would be a second place for the argument order to be
# wrong.
_ignored_dirs = _output._ignored_dirs
_is_ignored = _output._is_ignored
_iter_docs = _output.kept_files


def sweep_doc_drift(repo_root=None):
    """[(doc, problem), ...] — the ways `SWEEP_DOCS` stops being the whole set.

    `sweep_glob_drift()` judges the documents in the list; this judges the LIST. Two
    directions, because it has two failure modes and only one of them is obvious:

      * **a document that teaches a sweep and is not listed** — the silent case, and
        the reason this exists. Nothing else reads a runnable region for a sweep, so a
        new guide telling a reader to run the flat glob passed both checks at once;
      * **a listed document the walk cannot reach** — the blind case. The candidate set
        is derived from `.gitignore`, and a derivation is only as good as its pattern:
        the day one prunes a directory a sweep document lives in, this rule would go
        QUIET rather than wrong, which is precisely the failure it exists to prevent.
        Documents in this list live under `.claude/` as well as at the top level, one
        directory away from a pruned one.

    A candidate it could not read or could not parse is REPORTED, never skipped: "I
    cannot clear this file" and "this file is clean" are different answers, and a
    skipped file is the second one told as the first. Measured over the tree when this
    was written: no unreadable candidate and no unparseable one, so the loud path costs
    nothing today and is here for the day it does not.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    patterns, problem = _ignored_dirs(root)
    if problem is not None:
        return [(".gitignore", problem)]
    listed = set(SWEEP_DOCS)
    seen = set()
    out = []
    for rel in _iter_docs(root, patterns, SWEEP_DOC_EXT):
        if rel in listed:
            seen.add(rel)
            continue
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, "cannot be read, so it cannot be cleared of teaching a "
                             "sweep: %s" % exc))
            continue
        runnable, problem = _runnable_text(rel, text)
        if problem is not None:
            out.append((rel, "cannot be cleared of teaching a sweep: %s" % problem))
            continue
        for shape, label in SWEEP_SHAPES:
            if shape in runnable:
                out.append((rel, "tells a reader to run the %s %r but is not in "
                                 "SWEEP_DOCS, so nothing holds it to the rule"
                                 % (label, shape)))
    for rel in sorted(listed - seen):
        out.append((rel, "is in SWEEP_DOCS but the walk cannot reach it, so the scan "
                         "has gone blind rather than clean"))
    return out


# --- the document graph -------------------------------------------------------
# NOTHING IN THIS TREE HELD A DOCUMENT'S DISCOVERABILITY, and the gap was total: no
# rule enumerated the root-level documents, none counted them, and none asked whether
# one is linked from anywhere at all. There was no Markdown link checker of any kind.
# A document nobody links to is a document nobody reads, and it fails SILENTLY - every
# gate green, the page simply never reached.
#
# That became load-bearing the moment the documentation was split by audience, because
# the split's whole value is that a new reader's path to first success is SHORT, and a
# path is a property of the link graph rather than of any one file. Written while the
# graph was still clean - measured, nothing dangling and no unreachable root document
# - which is the only cheap moment to start holding one, exactly as `sweep_doc_drift`
# above says of its own list.
#
# Two directions, asymmetric on purpose, and what each half is ABOUT is the reason:
#
#   * a LINK is a claim about another file, so every one the walk can reach is
#     resolved - in a skill, in the plugin README, anywhere. A claim is checkable
#     wherever it is written, and the file it names either exists or does not;
#   * REACHABILITY is a property of the PUBLISHED ROOT, so only root-level documents
#     are required to have an inbound link. A document under `docs/` or a `SKILL.md`
#     is reached by being named rather than by being linked, and requiring a link for
#     each would need a blanket exemption - which is noise wearing a rule's clothes.
#
# Inline links only (`[text](target)`, images with them). Reference-style links and
# autolinks are not resolved, so this UNDER-reports rather than over-reports, the same
# limit the header of this file states about a path split across two literals. The
# `.gitignore` caveat above applies unchanged: directories it names are pruned, an
# ignored FILE of a scanned extension stays a candidate, and `git ls-files` may not be
# used because these suites run over an export with no `.git` in it.

# The root of the graph: where a reader arrives, so it needs no inbound link. Not an
# exemption - an exemption is something that could be removed, and this cannot be.
DOC_ENTRY = "README.md"

# Root-level documents reached some other way, each with the reason attached rather
# than left to a commit message. Checked in BOTH directions: an entry that has stopped
# being a root document, or that something links to after all, is reported - otherwise
# this becomes a place where dead exemptions accumulate and the rule quietly stops
# covering what it claims. Same shape, and same argument, as `EXCLUDED` above.
UNLINKED_BY_DESIGN = (
    ("CLAUDE.md",
     "loaded by the harness at the start of every session, so a reader never arrives "
     "by following a link and adding one would not make it any more read"),
)

# `[text](target)`, and `![alt](src)` with it - an image whose file is gone is the same
# defect as a link whose page is gone. The angle brackets Markdown permits around a
# target are stripped; a title after the target is not matched, which is part of the
# under-reporting the header states rather than a bug to fix quietly.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^)>\s]+)>?\s*\)")


def _doc_links(rel, text):
    """[(written, target), ...] — the in-repo links `rel` makes, target repo-relative.

    A link to another host, a `mailto:` or an anchor inside the same page is not a
    claim about a file in this tree and is not yielded at all. A `None` target means
    the link resolves OUTSIDE the repository, which is a finding rather than something
    to stat: `../thing` from the root reaches the machine, and a document may not.
    """
    here = rel.rsplit("/", 1)[0] if "/" in rel else ""
    out = []
    for match in _MD_LINK_RE.finditer(text):
        written = match.group(1)
        if written.startswith("#") or written.startswith("//"):
            continue
        if "://" in written or written.startswith("mailto:"):
            continue
        target = written.split("#", 1)[0].split("?", 1)[0]
        if not target:
            continue
        joined = posixpath.normpath(posixpath.join(here, target))
        if joined == ".." or joined.startswith("../"):
            out.append((written, None))
            continue
        out.append((written, joined))
    return out


def doc_link_drift(repo_root=None):
    """[(doc, problem), ...] — the ways the document graph stops holding.

    Three findings, and the middle one is the reason this exists:

      * **a link that names nothing** — the loud half. A page moved or was renamed and
        the pointer to it stayed, so a reader following it lands on a 404 while every
        other gate is green;
      * **a root-level document nothing links to** — the silent half, and the one a
        documentation split creates. Adding a page adds a page whose discoverability
        rests on somebody having remembered a link, and nothing here noticed when that
        link went away;
      * **an exemption that no longer describes the tree** — a declared entry that has
        stopped being a root document, or that is linked after all. Without this the
        table becomes the place a real orphan hides behind a stale reason.

    A document it cannot read is REPORTED, never skipped: "I could not resolve this
    file's links" and "this file's links are fine" are different answers, and skipping
    is the second one told as the first.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    patterns, problem = _ignored_dirs(root)
    if problem is not None:
        return [(".gitignore", problem)]
    out = []
    linked = {}
    docs = _iter_docs(root, patterns, _MD_EXT)
    for rel in docs:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, "cannot be read, so the links in it cannot be resolved "
                             "and it is unclear rather than clean: %s" % exc))
            continue
        for written, target in _doc_links(rel, text):
            if target is None:
                out.append((rel, "links to %r, which resolves outside the repository"
                                 % (written,)))
                continue
            if target != rel:
                linked.setdefault(target, set()).add(rel)
            if not os.path.exists(os.path.join(root, target.replace("/", os.sep))):
                out.append((rel, "links to %r, which is not in the tree - either the "
                                 "link rotted or the file moved" % (written,)))
    roots = [rel for rel in docs if "/" not in rel]
    excused = dict(UNLINKED_BY_DESIGN)
    if DOC_ENTRY not in roots:
        out.append((DOC_ENTRY, "is the entry point reachability is measured from and "
                               "the walk cannot see it, so every other document would "
                               "read as unreachable at once"))
    for rel in roots:
        if rel == DOC_ENTRY or rel in excused:
            continue
        if rel not in linked:
            out.append((rel, "is a root-level document nothing links to, so a reader "
                             "following links never reaches it - link it from %s, or "
                             "declare it in UNLINKED_BY_DESIGN with the reason"
                             % (DOC_ENTRY,)))
    for rel, _why in UNLINKED_BY_DESIGN:
        if rel not in roots:
            out.append((rel, "is declared UNLINKED_BY_DESIGN but is not a root-level "
                             "document the walk reaches, so the exemption excuses "
                             "nothing and hides the next real orphan"))
        elif rel in linked:
            out.append((rel, "is declared UNLINKED_BY_DESIGN but %s links to it, so "
                             "the exemption has outlived its reason"
                             % (", ".join(sorted(linked[rel])),)))
    return out


# --- published raw URLs -------------------------------------------------------
# A raw.githubusercontent URL encodes a PATH into somebody else's CI. When it names a
# moving ref, every layout change here is a silent 404 there, with no deprecation
# window - which is exactly what the move of `validate-manifest.py` into `manifest/`
# would have done to anyone who copied the README's `curl`.
#
# Scoped to EXECUTABLE fences, and that scope is the whole design. Four `main` URLs in
# this repo are JSON Schema `$id`/`$schema` identities, and pinning those would be a
# defect, not a fix: an `$id` is the schema's NAME, so a per-release `$id` gives every
# release a different schema identity and breaks `$ref` resolution and cache keys for
# consumers. Identity is not a download. Only what a reader is told to RUN is checked.
_MOVING_REFS = ("main", "master", "HEAD")
_RAW_HOST = "raw.githubusercontent.com"
_RAW_RE = re.compile(r"%s/[^/\s]+/[^/\s]+/([^/\s]+)/" % re.escape(_RAW_HOST))
# `_FENCE_RE` lives with the sweep's runnable-region rules above: both sections ask
# the same question of a Markdown file and one pattern is the answer to it.

# The canonical install document, and the only one required to name the CURRENT
# release: a reader copies from here expecting today's plugin. Other documents may
# pin an older tag on purpose - `docs/examples/azure-pipelines.yml` pins `v0.5.0` and
# says in prose that the single-file layout is a snapshot of it. That is a correct
# use of a tag, so the currency rule must not fail it.
_PIN_CURRENT_REL = PLUGIN_REL + "/README.md"
_PLUGIN_JSON_REL = PLUGIN_REL + "/.claude-plugin/plugin.json"

# Derived from the format constants the sweep's scan reads, not spelled again. `.json`
# is deliberately absent rather than forgotten: every `main` URL this tree keeps in JSON
# is a schema `$id`/`$schema` identity, and identity is not a download.
_FETCH_DOC_EXT = _MD_EXT + _YAML_EXT


def _fetch_docs(root):
    """`(rels, problem)` — the documents whose FENCES this rule reads.

    Fences, said precisely rather than "runnable regions": `_executable_raw_refs()`
    reads a Markdown fence, so the YAML in this set contributes nothing today even
    though `_runnable_text` has a `run:` rule the scan could use. That is a gap with a
    finding of its own, not something this docstring should paper over.

    Exactly one of the two is None, the contract `_ignored_dirs()` and `_runnable_text`
    both use. It is a named function rather than two lines inside the rule so that a
    case can read the candidate set directly: the defect this replaced was invisible in
    the rule's OUTPUT - a scratch directory nobody had written a fetch into reports
    nothing, and reports nothing right up to the day somebody does.
    """
    patterns, problem = _ignored_dirs(root)
    if problem is not None:
        return None, problem
    return _iter_docs(root, patterns, _FETCH_DOC_EXT), None


def _executable_raw_refs(text):
    """[(ref, line_no), ...] — every raw-URL ref inside a runnable fence."""
    out = []
    for fence in _FENCE_RE.finditer(text):
        base = text.count("\n", 0, fence.start(1)) + 1
        for i, line in enumerate(fence.group(1).split("\n")):
            for m in _RAW_RE.finditer(line):
                out.append((m.group(1), base + i))
    return out


def plugin_version(repo_root=None):
    """The version string in plugin.json, or None when it cannot be read.

    None rather than a default: the currency rule has no basis without it, and a
    guessed version would fail every pin in the README for the wrong reason.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    data = _read_json(os.path.join(root, _PLUGIN_JSON_REL.replace("/", os.sep)))
    if not isinstance(data, dict):
        return None
    v = data.get("version")
    return v if isinstance(v, str) and v else None


def raw_url_pin_drift(repo_root=None):
    """[(rel, line, problem), ...] — published fetch instructions that will rot.

    Two rules, and they answer different failures:

    - a moving ref in ANY runnable fence: breaks the moment this repo moves a file;
    - a tag in the plugin README that is not the current release: the README is what a
      reader copies expecting today's plugin, so a stale pin hands them an old one.

    The second is deliberately scoped to one file so that a considered historical pin
    elsewhere stays legal. It fires at release time, when `plugin.json` is bumped and
    the README has not been - which is the moment the pin needs a human.

    A `.gitignore` it cannot read is REPORTED and the scan stops, for the reason
    `sweep_doc_drift()` gives: answering "nothing is ignored" would read scratch copies
    as things this repo published.

    There is no CHANGELOG exemption, and that is deliberate rather than an omission: it
    quotes the dead `main` URL as history, in prose, and the fence scope already spares
    that - measured, not assumed (test__refs p10-p12, p18). The walk this replaced
    carried one, against a table of `(path, reason)` pairs it compared a path string to,
    so it could not fire; deleting it changed nothing, which is what p18 pins.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    docs, problem = _fetch_docs(root)
    if problem is not None:
        return [(".gitignore", 0, problem)]
    version = plugin_version(root)
    out = []
    for rel in docs:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, 0, "unreadable: %s" % exc))
            continue
        for ref, line in _executable_raw_refs(text):
            if ref in _MOVING_REFS:
                out.append((rel, line, "fetches from the moving ref %r - pin a tag" % ref))
            elif rel == _PIN_CURRENT_REL and version is not None and ref != "v" + version:
                out.append((rel, line,
                            "pinned to %s but plugin.json says %s" % (ref, version)))
    return out


# --- the version a committed artifact stamps ----------------------------------
# A rendered report stamps the plugin version that produced it, so a COMMITTED report
# is a published claim about which release the reader is looking at. The scale demo
# under `docs/` served a stamp several releases behind the plugin, and every check over
# it stayed green, because they asserted CONTENT - no invalid-manifest banner, a usage
# section present - and content is exactly what does not change with a release. Content
# assertions cannot see age.
#
# NOT A SECOND LIST OF ARTIFACTS, and that is the design. The byte comparison in
# `tools/check-rendered-artifacts.py` would also notice a stale stamp, among the bytes,
# for the artifacts ITS table names - and its own docstring calls the artifact nobody
# listed the direction it cannot cover. This rule DISCOVERS the claim instead: every
# page this repo keeps is read, every stamp found is compared, and the finding names
# BOTH versions rather than a byte count. A page committed tomorrow is covered without
# anybody adding a row.
# Public because `tools/affected.py` derives its selection from it: a
# narrowed local run that skipped this rule for the very file it judges
# would be the under-selection that file exists to prevent.
STAMP_EXT = (".html",)

# The stamp as the report writes it. The class is the marker and the version follows
# the label inside the same element, with the title attribute in between - which is why
# this is a pattern rather than an offset.
#
# The markup literal lives here and in the renderer, and the agreement is pinned by a
# CASE over the real committed pages rather than by a comment claiming they match: the
# module that owns paths and process I/O is the wrong home for report markup, and a
# renamed class does not go quiet here - a tree where nothing is stamped is itself a
# finding below.
_STAMP_RE = re.compile(r'class="stampv"[^>]*>audit ([^<]*)<')


def _stamp_pages(root):
    """`(rels, problem)` - the pages whose version stamp this rule reads.

    Every page this repo KEEPS, not a table of the published reports: a table is the
    thing that goes stale, and an artifact nobody listed is the direction the byte
    comparison names as the one it cannot cover. The panel's TEMPLATE is in this set
    and stamps nothing, which is correct and is what a case reads it for.

    Exactly one of the two is None, the contract `_fetch_docs()` uses. A named
    accessor for the reason that one gives: a walk's defect is invisible in the rule's
    OUTPUT, because a tree it never reached reports nothing and goes on reporting
    nothing.
    """
    patterns, problem = _ignored_dirs(root)
    if problem is not None:
        return None, problem
    return _iter_docs(root, patterns, STAMP_EXT), None


def _artifact_stamps(text):
    """[(version, line_no), ...] - every version stamp in one page.

    EVERY one, not the first. Generated output is where a base template and an
    override each emit one and disagree, and a presence test cannot tell that from a
    page carrying a single correct stamp.
    """
    return [(m.group(1), text.count("\n", 0, m.start()) + 1)
            for m in _STAMP_RE.finditer(text)]


def artifact_version_drift(repo_root=None):
    """[(rel, line, problem), ...] - a committed page stamped with a stale release.

    THE CLAIM A PAGE MAKES ABOUT ITSELF, checked against the only thing that can
    settle it: the page says which plugin rendered it, `plugin.json` says which plugin
    this is, and until this rule nothing compared the two.

    Four answers, and three of them are the loud ones:

    - a `.gitignore` it cannot read: reported, and the scan stops, for the reason
      `sweep_doc_drift()` gives - scratch renders would be read as published pages;
    - a `plugin.json` with no readable version: reported. The comparison has no basis,
      and a guessed version would fail every page for the wrong reason;
    - not one stamped page anywhere: reported. A rule whose candidate set narrowed to
      nothing must not be spelled the same way as a tree that is current, and that is
      the shape a renamed stamp or a walk that stopped reaching the reports takes;
    - otherwise one finding per stamp that is not the current version, naming BOTH -
      "stale" without the pair is not something a reader can act on.

    A page it cannot decode is reported rather than counted as unstamped, which is the
    same distinction: "I could not read this claim" is not "this page makes none".
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    pages, problem = _stamp_pages(root)
    if problem is not None:
        return [(".gitignore", 0, problem)]
    version = plugin_version(root)
    if version is None:
        return [(_PLUGIN_JSON_REL, 0,
                 "carries no readable version, so no stamp has anything to be "
                 "compared against")]
    out = []
    stamped = 0
    for rel in pages:
        try:
            with open(os.path.join(root, rel.replace("/", os.sep)),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            out.append((rel, 0, "unreadable, so the version it publishes cannot be "
                                "cleared: %s" % exc))
            continue
        for stamp, line in _artifact_stamps(text):
            stamped += 1
            if stamp != version:
                out.append((rel, line,
                            "stamps audit %s but plugin.json says %s - re-render it "
                            "and commit the result" % (stamp, version)))
    if not stamped:
        out.append(("*" + STAMP_EXT[0], 0,
                    "no page this repo keeps carries a version stamp, so this rule "
                    "cleared nothing rather than clearing the tree - either the "
                    "renderer stopped stamping or the markup moved"))
    return out


SHOT_DIR_REL = "docs/screenshots"
_CAPTURED_AT = SHOT_DIR_REL + "/captured-at.json"


def screenshot_capture_drift(repo_root=None):
    """[(rel, line, problem), ...] - a committed screenshot that no longer shows this build.

    THE SAME QUESTION AS `artifact_version_drift()` ASKED OF A PICTURE, which is why
    it cannot be answered the same way. The panel paints its own version in the
    topbar and every shot starts at the top of the page, so each panel PNG makes a
    claim about which build it shows - and reading that claim back means reading text
    out of an image. `tools/capture-screenshots.mjs` refuses to compare these pixels
    at all, for reasons its own header sets out at length: font rasterisation differs
    between hosts and no environment variable pins it. F18 settled that, and three
    repairs that would fake a wider claim are declined there by name.

    So the basis is recorded beside the pictures instead, by the run that took them,
    and this compares it. The record is not a guess: the panel leg asserts the LIVE
    topbar names `plugin.json`'s version before any shutter opens, so what the
    sidecar writes down is what was already checked.

    Four answers, and the first three are the loud ones:

    - no sidecar, or one that will not parse: reported. The pictures make a claim
      and nothing can settle it, which is the state this rule exists to end - and
      staying quiet here would be indistinguishable from a tree that is current;
    - a `plugin.json` with no readable version: reported, for the reason the sibling
      rule gives - a guessed version would fail every image for the wrong reason;
    - not one image in the directory: reported. A candidate set that narrowed to
      nothing must not be spelled the same way as a set that all agrees, and that is
      the shape a moved output directory takes;
    - otherwise one finding per image whose recorded version is not the current one,
      naming BOTH, plus one per image the sidecar does not mention and one per entry
      whose file is gone or whose bytes have changed since it was written.

    WHAT THE HASH IS FOR. Without it the sidecar could be edited into agreement
    while the pictures stayed stale, and this rule would pass on a file someone
    typed. With it, agreeing with `plugin.json` requires the bytes to be the ones a
    capture wrote. It does not make the claim unforgeable - a hash can be recomputed
    - but forging it stops being something you do by accident, which is the failure
    this is about.

    `demo-gate.gif` is deliberately NOT in scope: `tools/capture-demo-gif.py` writes
    it, so demanding an entry here would report a missing basis against a producer
    that was never asked to record one. It owes its own answer, not this one's.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    shot_dir = os.path.join(root, SHOT_DIR_REL.replace("/", os.sep))
    version = plugin_version(root)
    if version is None:
        return [(_PLUGIN_JSON_REL, 0,
                 "carries no readable version, so no screenshot has anything to be "
                 "compared against")]
    try:
        names = sorted(n for n in os.listdir(shot_dir) if n.endswith(".png"))
    except OSError as exc:
        return [(SHOT_DIR_REL, 0,
                 "cannot be listed, so whether its images name this build is "
                 "unknown rather than fine: %s" % exc)]
    if not names:
        return [(SHOT_DIR_REL, 0,
                 "holds no .png at all - the rule has nothing to check, which is "
                 "not the same as every image agreeing")]
    try:
        recorded = _read_json(os.path.join(root, _CAPTURED_AT.replace("/", os.sep)))
    except (OSError, ValueError):
        # `_read_json` propagates both, deliberately - its callers decide what a
        # missing file means, and here it means the basis is absent, which is the
        # finding below rather than a reason to fall back to anything.
        recorded = None
    images = recorded.get("images") if isinstance(recorded, dict) else None
    if not isinstance(images, dict):
        return [(_CAPTURED_AT, 0,
                 "is missing or unreadable, so %d committed image(s) claim a build "
                 "with nothing to settle the claim - re-run "
                 "`node tools/capture-screenshots.mjs`" % (len(names),))]
    out = []
    for name in names:
        rel = SHOT_DIR_REL + "/" + name
        entry = images.get(name)
        if not isinstance(entry, dict):
            out.append((rel, 0, "is not in %s, so the build it shows is unrecorded"
                                % (_CAPTURED_AT,)))
            continue
        try:
            with open(os.path.join(shot_dir, name), "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
        except OSError as exc:
            out.append((rel, 0, "unreadable, so its recorded build cannot be "
                                "cleared: %s" % exc))
            continue
        if entry.get("sha256") != digest:
            out.append((rel, 0, "has changed since its build was recorded, so the "
                                "recorded version is about different bytes - re-run "
                                "the capture"))
        elif entry.get("version") != version:
            out.append((rel, 0, "was captured at %s but plugin.json says %s - "
                                "re-run the capture and commit the result"
                                % (entry.get("version"), version)))
    for name in sorted(images):
        if name not in names:
            out.append((_CAPTURED_AT, 0,
                        "records %s, which is not in %s - a record with no picture "
                        "is a claim about nothing" % (name, SHOT_DIR_REL)))
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
