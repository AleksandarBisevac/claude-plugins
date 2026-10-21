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
    _areas.py` keeps passing on the day `_areas.py` moves into a subdirectory.

So a path can rot today, silently, and a restructure that moves files is exactly the
event that would rot many at once. Same shape as `_deps.map_drift()`: a document
makes a claim, the code says what is true, and the two are compared every run
instead of trusted.

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
whose sweep command names a retired glob and a published `curl` pinned to a moving ref are
the same shape. The checks that once held a document graph's links and the published
handbook against the product were retired: nothing compares those any more, so a link
or a verb a page names is its author's to keep true.

A PATH SPLIT ACROSS STRING LITERALS IS REPORTED, BECAUSE THE PER-LINE SCAN CANNOT SEE IT.
Matching is per line, so a path assembled from two adjacent literals - or two literals
with a plus between them - names a file no scan above ever stats, and that blind spot
was being used on purpose: a fixture path that does not exist was split so the
reference lints would not report it. `split_literal_violations()` closes it from the
other side. It tokenizes every `.py` the surfaces hold, joins each run of string
literals, and reports - file, line, joined path - every path match that crosses a
boundary between two pieces. A split is reported whether or not its file exists and
whether or not the line carries the marker below: splitting is never the way to say
anything, so no reading of it is accepted.

A FIXTURE PATH IS DECLARED, NOT HIDDEN. A line that carries `FIXTURE_MARKER` - the
comment text `# refs: fixture`, written on the same line as the path, and that is the
only spelling - declares every reference on that line a fixture: `missing_references()`
puts a declared path whose file is absent under `fixtures` rather than `missing`. The
declaration is itself checked, as `TOOL_FIXTURE_BASENAMES` is: a marked line naming a
file that IS there goes under `staleFixtures`, because it would hide a real reference
from the day that file is deleted.

WHAT THE SPLIT RULE DOES NOT SEE, SAID RATHER THAN IMPLIED: a path assembled from a NAME
and a literal (`PLUGIN_REL + ...`, a `%` format, a `join`) is not a run of literals and
is not read; nor is any file that is not Python. Those spellings stay outside every
lint here, so a green run says no LITERAL split hides a path, and nothing more.

This module carries no `--selftest` of its own any more; its cases live in
`tests/test__refs.py`, byte-identical labels and all — see
`tests/_harness.py`. The fixture CONSTANTS went with them, and that is
the one thing about this move worth knowing: a lint that scans the tree lives in the
tree it scans, so a fixture path spelled with an anchor in front of it is a REAL
reference to a file that exists for four milliseconds, and `c5` reports it. Every
fixture path over there is built from `PLUGIN_REL`; the surface changed name
(`scripts/` to `tests/`, both ANCHORED) and the rule did not.
"""

import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tokenize

# The path bootstrap for a development module that lives OUTSIDE the plugin: it
# walks UP to the directory that holds `plugins/audit/scripts/_output.py` instead
# of counting `dirname()` calls, so it does not encode how deep this file sits.
# The shipped scripts carry `_output.PATH_PREAMBLE`, which walks up to `_output.py`
# itself and would run off the filesystem root from here, because this directory
# is not under `scripts/`. `install_path()` then adds `scripts/` and every
# subdirectory of it holding a `.py`, so every sibling below is reached by a bare
# basename - and `tools/lints/` itself is NOT put on the path by it, by design.
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
import _output_lints  # noqa: E402  (the lint half, development code)

_output.install_path()
import _manifest_io  # noqa: E402  (TERMINAL: which statuses are history)

# REPO_ROOT rather than "the plugin root": every `rel` this module produces already
# starts with `plugins/audit/`, so it is joined to the directory the plugin tree hangs
# UNDER, and joining it to the plugin's own directory would look for
# `plugins/audit/plugins/audit/scripts/...`. Re-exported off `_output` rather than
# derived again from this file's own `__file__` — two derivations of one directory is
# one directory and one place for it to go wrong.
REPO_ROOT = _output.REPO_ROOT
PLUGIN_REL = _output.PLUGIN_REL


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
    # `tests/` is the repository's Python too, and ANCHORED because a bare `tests/`
    # means somebody else's repo as often as ours: `hooks/_config.py` carries two
    # `tests/`-rooted file names as fixtures for a CONSUMER repo's test globs, and a
    # bare match would look for those inside this tree and report it as broken
    # because a hook knows what a Python test is usually called. The anchor is the
    # SUITE NAME - see `_suite_anchored` - since the old `plugins/audit/` prefix is
    # gone from every honest spelling. (The paths are described rather than written:
    # this file is itself an anchored surface, and spelling one here would BE a
    # reference to a file that does not exist - the trap the header warns about.)
    ("tests", ANCHORED),
    # The two lint modules were `scripts/` files and were scanned anchored there;
    # leaving them under `tools`' bare walk would read their fixtures as references.
    ("tools/lints", ANCHORED),
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

# `tests/` gets its own branch instead of joining `_DIR`, and a reference to it must
# be ANCHORED in both modes - this is the only directory whose bare name means
# somebody else's repo more often than it means ours. `scripts/x.py` in a document
# is unambiguous; a `tests/`-rooted file name is what half the prose about testing a
# CONSUMER project says, and `hooks/_config.py` already carries two as fixtures.
#
# THE ANCHOR USED TO BE THE `plugins/audit/` PREFIX AND IS NOW THE SUITE'S NAME. The
# suites left the plugin, so the honest spelling of a reference to one is a bare
# `tests/<suite>.py`, which carries no prefix to anchor on. What still tells our
# suite from a consumer's is the NAME: a suite here is `_harness` or `test_<module>`
# for a module this repository keeps (`known_suites`, `_suite_anchored`). The old
# prefix is still MATCHED, and always counts - a document that still says
# `plugins/audit/tests/...` is stale, and the stat of the path it names reports
# exactly that.
#
# A placeholder (`tests/*.py`, `tests/<name>.py`) is matched too, as it always was,
# and is classified rather than stat'd.
_TESTS_DIR = r"tests/"
_TESTS_NAME = (r"(?:_harness|test_%s|[A-Za-z0-9_.-]*[<*>][A-Za-z0-9_.<>*-]*)\.py"
               % _SEG)
_TESTS_OLD_PREFIX = "plugins/audit/"
# Its own `(?:old prefix | not-after-a-path-character)` rather than `_ROOT_ANCHOR`:
# a bare spelling must not start in the middle of a longer path.
_TESTS_BRANCH = r"(?:%s|(?<![A-Za-z0-9_./$}-]))(%s%s)" % (
    re.escape(_TESTS_OLD_PREFIX), _TESTS_DIR, _TESTS_NAME)

# This repository's OWN configuration tree, which shares `hooks/` and `skills/`
# with the plugin's product and means something else entirely. See `_match_rel`.
_REPO_DIR_PREFIX = ".claude/"

# THE LINT MODULES' OWN ROOT, as a fourth arm. A document pointing at `_deps.py` or
# `_refs.py` named `plugins/audit/scripts/...` and was stat'd; with the file moved,
# `tools/lints/<name>.py` matches no other arm, and the references to it would have
# stopped being checked with nothing said. The prefix is its own anchor in both
# modes, as `plugins/audit/` is for the others.
_LINTS_ARM = r"(?<![A-Za-z0-9_./$}-])(tools/lints/%s)" % _TAIL

_BARE_RE = re.compile(r"%s?(%s%s)|%s(%s)|%s|%s"
                      % (_ROOT_ANCHOR, _DIR, _TAIL, _SCRIPTS_VAR, _TAIL,
                         _TESTS_BRANCH, _LINTS_ARM))
_ANCHORED_RE = re.compile(r"%s(%s%s)|%s(%s)|%s|%s"
                          % (_ROOT_ANCHOR, _DIR, _TAIL, _SCRIPTS_VAR, _TAIL,
                             _TESTS_BRANCH, _LINTS_ARM))


def _match_rel(match):
    """The repo-relative path a match names, whichever branch of the pattern fired.

    A `.claude/`-PREFIXED reference resolves against the REPOSITORY, not the
    plugin. The two trees share directory names by design — `.claude/hooks/` is
    this repository's own configuration and `plugins/audit/hooks/` is the
    product — so `hooks/x.py` had exactly one reading until the first repo-level
    hook was written, and then it silently had two. Resolving the prefixed form
    to the plugin reported a missing file for one that is there, which is the
    same ambiguity this module already carves out for `tests/`, one directory
    over. The reference stays CHECKED either way: a typo under `.claude/hooks/`
    is still a missing file, just a missing file in the right tree.
    """
    text = match.string
    prefixed = text[max(0, match.start() - len(_REPO_DIR_PREFIX)):match.start()]
    if match.group(1):
        if prefixed.endswith(_REPO_DIR_PREFIX):
            return "%s%s" % (_REPO_DIR_PREFIX, match.group(1))
        return "%s/%s" % (PLUGIN_REL, match.group(1))
    if match.group(3):
        if match.string[match.start():match.start(3)] == _TESTS_OLD_PREFIX:
            return _TESTS_OLD_PREFIX + match.group(3)
        return match.group(3)
    if match.group(4):
        return match.group(4)
    return "%s/scripts/%s" % (PLUGIN_REL, match.group(2))


def known_suites(repo_root=None):
    """The `tests/` file names a reference may honestly mean: what is there, plus
    what a module this repository keeps WOULD be covered by.

    The second half is what makes a stale reference visible: a suite deleted while
    its module stays is still a name a document can wrongly keep, and a set read off
    the directory alone would say nothing about it. `_output._test_name_for` is the
    one place that maps a module to its suite's name.

    Only a `.py` or `.sh` MODULE names a suite. `_output._coverable_test_names`
    reads every file under a directory, and the front-end parts under `scripts/ui/`
    would then make a consumer repository's `boot` test read as ours.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    names = set()
    tests = os.path.join(root, "tests")
    if os.path.isdir(tests):
        names.update(os.listdir(tests))
    for rel in (PLUGIN_REL + "/scripts", PLUGIN_REL + "/hooks", "tools/lints"):
        directory = os.path.join(root, rel.replace("/", os.sep))
        for _dir, _dirnames, filenames in os.walk(directory):
            names.update(_output_lints._test_name_for(name) for name in filenames
                         if name.endswith((".py", ".sh")))
    return names


def _suite_anchored(match, suites):
    """Whether `match` counts as a reference to something of ours.

    Every non-`tests/` branch is anchored by its own text. A `tests/` match counts
    when it carries the old plugin prefix (stale, and reported by the stat), is a
    placeholder, or names a suite in `suites` - anything else is a consumer
    repository's file name that this tree merely happens to spell.
    """
    if not match.group(3):
        return True
    rel = _match_rel(match)
    name = os.path.basename(rel)
    return (rel.startswith(_TESTS_OLD_PREFIX) or is_placeholder(rel)
            or name == "_harness.py" or name in suites)


# The one spelling that declares a fixture path; see the module docstring. Read per
# LINE, as every reference here is, so it sits on the line the path is written on.
FIXTURE_MARKER = "# refs: fixture"


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
    own = set(s for s, _m in SURFACES if s != surface)
    found = []
    for root, dirnames, filenames in os.walk(path):
        dirnames.sort()
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        # A directory that is a surface of its own is read in ITS mode, once: the
        # lint modules under `tools/lints/` hold the same unanchored fixtures the
        # plugin's own sources do, so they are scanned anchored, and a parent's
        # bare walk must not read them a second time in the wrong mode.
        dirnames[:] = [d for d in dirnames if _output.posix_rel(
            os.path.join(root, d), surface_root) not in own]
        for name in sorted(filenames):
            if not name.endswith(exts):
                continue
            found.append(_output.posix_rel(os.path.join(root, name),
                                           surface_root))
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
    return [hit[:4] for hit in _scanned_hits(surface_root)]


def _scanned_hits(surface_root):
    """`referenced_paths()`'s tuples with a fifth field: whether the line declares
    its references fixtures by carrying `FIXTURE_MARKER`."""
    root = surface_root if surface_root is not None else REPO_ROOT
    suites = known_suites(root)
    hits = []
    for surface, mode in SURFACES:
        pattern = _ANCHORED_RE if mode == ANCHORED else _BARE_RE
        for rel_file in _surface_files(root, surface, mode):
            path = os.path.join(root, rel_file.replace("/", os.sep))
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            for lineno, line in enumerate(lines, 1):
                marked = FIXTURE_MARKER in line
                for match in pattern.finditer(line):
                    if not _suite_anchored(match, suites):
                        continue
                    hits.append((rel_file, lineno, match.group(0), _match_rel(match),
                                 marked))
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
        # The MOST SPECIFIC surface wins: `tools/lints` is nested in `tools`, and
        # first-match would credit every lint-module hit to the parent.
        owners = [surface for surface, _mode in SURFACES
                  if rel_file == surface or rel_file.startswith(surface + "/")]
        if owners:
            counts[max(owners, key=len)] += 1
    return counts


# --- existence ----------------------------------------------------------------
def missing_references(repo_root=None, surface_root=None):
    """{"missing", "placeholders", "fixtures", "staleFixtures": [...], "checked", "total": n}.

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

    A line carrying `FIXTURE_MARKER` is still stat'd, and the answer is filed apart:
    an absent file there is a declared fixture (`fixtures`), a present one is a
    declaration hiding a real reference (`staleFixtures`). Both stay in `checked`.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    hits = _scanned_hits(surface_root)
    missing = []
    placeholders = []
    fixtures = []
    stale = []
    for hit in hits:
        rel, marked = hit[3], hit[4]
        if is_placeholder(rel):
            placeholders.append(hit[:4])
            continue
        present = os.path.isfile(os.path.join(root, rel.replace("/", os.sep)))
        if marked:
            (stale if present else fixtures).append(hit[:4])
        elif not present:
            missing.append(hit[:4])
    return {"missing": missing, "placeholders": placeholders, "fixtures": fixtures,
            "staleFixtures": stale,
            "checked": len(hits) - len(placeholders), "total": len(hits)}


# --- paths assembled from string literals ----------------------------------------
def _literal_value(token_text):
    """The str a STRING token evaluates to, or None for bytes and anything that is
    not a plain literal (an f-string on an interpreter that tokenizes it whole)."""
    try:
        value = ast.literal_eval(token_text)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def _literal_runs(text):
    """[[(value, lineno), ...], ...] - every run of TWO OR MORE string literals that
    Python joins: adjacent, or with a plus between them, across line breaks and
    comments. A run is broken by any other token, and a bytes literal breaks it."""
    runs = []
    run = []
    after_plus = False
    readline = io.StringIO(text).readline
    for tok in tokenize.generate_tokens(readline):
        kind, string = tok[0], tok[1]
        if kind in (tokenize.NL, tokenize.COMMENT):
            continue
        value = _literal_value(string) if kind == tokenize.STRING else None
        if value is not None:
            # A non-empty run means the last token that counted was a literal or
            # a plus after one - both are joins, so the piece always continues it.
            run.append((value, tok[2][0]))
            after_plus = False
            continue
        if kind == tokenize.OP and string == "+" and run and not after_plus:
            after_plus = True
            continue
        if len(run) > 1:
            runs.append(run)
        run = []
        after_plus = False
    if len(run) > 1:
        runs.append(run)
    return runs


# The anchor on its own. A run that splits the ANCHOR is reported even when no whole
# path follows it in the run, because the path is then finished through a name -
# which no rule here can follow - and an anchor has no other reason to be split.
_ANCHOR_RE = re.compile(_ROOT_ANCHOR)


def _split_matches(run, pattern, suites):
    """[(lineno, joined text), ...] for every path match in the joined run, and every
    bare anchor, that crosses a boundary between two of its pieces. An anchor inside
    a path already reported is not reported a second time."""
    starts = []
    offset = 0
    for value, lineno in run:
        starts.append((offset, lineno))
        offset += len(value)
    joined = "".join(value for value, _lineno in run)

    def crosses(match):
        return any(match.start() < start < match.end() for start, _ln in starts)

    def line_of(match):
        return [ln for start, ln in starts if start <= match.start()][-1]

    paths = [m for m in pattern.finditer(joined)
             if crosses(m) and _suite_anchored(m, suites)]
    anchors = [m for m in _ANCHOR_RE.finditer(joined) if crosses(m)
               and not any(p.start() <= m.start() < p.end() for p in paths)]
    return sorted((line_of(m), m.group(0)) for m in paths + anchors)


def split_literal_violations(repo_root=None):
    """{"violations": [(rel, lineno, joined path)], "checked": n, "files": n}.

    Every `.py` the SURFACES hold, in the mode its surface is scanned in, so a split
    is judged by the same pattern that would have seen the path written whole. See
    the module docstring for the rule and for what it does not read.

    `checked` is the number of literal runs examined and `files` the number of files
    tokenized: an empty `violations` over zero runs is a tokenizer that read nothing,
    not a clean tree. A file that will not tokenize is NAMED, never skipped."""
    root = repo_root if repo_root is not None else REPO_ROOT
    suites = known_suites(root)
    violations = []
    checked = 0
    files = 0
    for surface, mode in SURFACES:
        pattern = _ANCHORED_RE if mode == ANCHORED else _BARE_RE
        for rel_file in _surface_files(root, surface, mode):
            if not rel_file.endswith(".py"):
                continue
            path = os.path.join(root, rel_file.replace("/", os.sep))
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            try:
                runs = _literal_runs(text)
            except (tokenize.TokenError, SyntaxError) as exc:
                violations.append((rel_file, 0, "<untokenizable: %s>" % (exc,)))
                continue
            files += 1
            checked += len(runs)
            for run in runs:
                for lineno, joined in _split_matches(run, pattern, suites):
                    violations.append((rel_file, lineno, joined))
    return {"violations": violations, "checked": checked, "files": files}


# --- the plan's own file lists ------------------------------------------------
_MANIFEST_REL = "docs/audit/audit-plan.json"
_PHASES_REL = "docs/audit/phases"


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# The three questions about "did this `.py` move" are answered by the anchor, not
# here: `audit-task.py` is shipped and asks one of them, and this module is not.
_py_index = _output.py_index
_moved_index = _output.moved_index
is_plugin_py_path = _output.is_plugin_py_path
moved_file_target = _output.moved_file_target


def _recorded_paths(repo_root):
    """([(source, path, live), ...], [(rel, problem), ...]) - what the plan says it touches.

    Both the index's `fileIndex` keys and every shard task's `files`, each carrying where
    it was found so a violation names one place to go and fix. `live` is whether a task
    that still has work to do records the path: a done or cancelled task is history, and
    an index row is live when any task it lists is, or when a listed id is in no shard
    (an index row nobody owns is not history). A shard that will not parse becomes a
    problem rather than a shorter list."""
    recorded = []
    unreadable = []
    try:
        plan = _read_json(os.path.join(repo_root, _MANIFEST_REL.replace("/", os.sep)))
    except (OSError, ValueError) as exc:
        return recorded, [(_MANIFEST_REL, "unreadable: %s" % exc)]

    shard_paths = []
    settled = {}
    phases_dir = os.path.join(repo_root, _PHASES_REL.replace("/", os.sep))
    if not os.path.isdir(phases_dir):
        unreadable.append((_PHASES_REL, "no such directory"))
    else:
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
                live = task.get("status") not in _manifest_io.TERMINAL
                settled[task.get("id")] = not live
                for path in task.get("files") or []:
                    shard_paths.append(
                        ("%s task %s" % (rel, task.get("id") or "?"), path, live))

    file_index = plan.get("fileIndex")
    if file_index is None:
        unreadable.append((_MANIFEST_REL, "carries no fileIndex"))
    elif not isinstance(file_index, dict):
        unreadable.append((_MANIFEST_REL, "fileIndex is %s, not an object"
                           % type(file_index).__name__))
    else:
        for key in sorted(file_index):
            owners = file_index[key] if isinstance(file_index[key], list) else []
            live = not owners or not all(settled.get(o, False) for o in owners)
            recorded.append(("%s fileIndex" % _MANIFEST_REL, key, live))
    return recorded + shard_paths, unreadable


def manifest_moved_files(repo_root=None):
    """{"moved": [...], "history": [...], "gone": [...], "unreadable": [...], "checked": n}.

    Restricted to `.py` recorded under `plugins/audit/` - the manifest records project
    files of every kind, and only this plugin's own sources are ours to move. A file
    that LEFT the plugin is still a move: `_output.moved_index` looks in `tests/` and
    `tools/lints/` too.

    THE ASYMMETRY IS THE POINT, AND IT HAS TWO AXES. A recorded path whose file is gone
    but whose BASENAME exists elsewhere is a MOVE, and a document still pointing at the
    old place is stale: that is `moved` when a task with work left records it, and it is
    loud. A done or cancelled task naming the old place is correct history - the file was
    there when it ran - so that is `history`, listed apart so it is counted and never
    dropped. A recorded path whose basename exists nowhere is a DELETION, and a done task
    that says it deleted a file is correct history: that is `gone`, and it is not a
    violation. Classified rather than dropped, because "no moves found" and "nothing was
    examined" must not print the same way - `checked` is what separates them.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    recorded, unreadable = _recorded_paths(root)
    index = _moved_index(root)
    moved = []
    history = []
    gone = []
    checked = 0
    for source, path, live in recorded:
        # A `:line-range` SUFFIX IS NOT STRIPPED HERE, AND THAT IS STATED
        # RATHER THAN FIXED. The schema allows one on a `files` entry, and
        # every other consumer that turns a declared entry into a filesystem
        # path strips it first (`_manifest_vocab._strip_line_suffix`, taken by
        # `commit-task-work.py`, `audit-task.py` and `_manifest_crossrefs.py`
        # rather than re-parsed per caller). Importing it here would be a third
        # consumer of a rule that has one home, and writing the one-line split again
        # would be a fourth spelling of it.
        # So a suffixed entry fails `.endswith(".py")` and never reaches
        # `checked` - an UNDER-COUNT, not a false positive: nothing is
        # reported wrongly about it, a real move or deletion just goes
        # unexamined.
        if not is_plugin_py_path(path):
            continue
        checked += 1
        if os.path.isfile(os.path.join(root, path.replace("/", os.sep))):
            continue
        target = moved_file_target(path, root, index)
        if target is None:
            gone.append((source, path))
        elif live:
            moved.append((source, path, target))
        else:
            history.append((source, path, target))
    return {"moved": moved, "history": history, "gone": gone,
            "unreadable": unreadable, "checked": checked}


# --- the basenames tools/ names -----------------------------------------------
# THE HOLE THIS CLOSES. Everything above matches a PATH — `<dir>/<name>.py` — per line.
# `tools/` does not write paths: it runs the plugin's scripts as subprocesses, and it
# builds each command by joining a directory constant with a bare filename, so the line
# carries `'panel-server.py'` and nothing a path pattern can catch. Nine such sites went
# unseen by every lint in this tree and failed at RUN time instead, inside a browser gate
# that only a machine with Playwright installed ever executes.
TOOLS_REL = "tools"

# The trees a `.py` basename written in `tools/` may legitimately name. The plugin's
# own `scripts` and `hooks` are what a tool RUNS. `tools/` itself is not a loophole: a
# tool's own usage line names its own file (`--check` instructions, an `argparse` prog)
# and a sibling tool is a real file too — leaving it out would make every usage string
# a violation, and a lint everyone has to argue with is a lint that gets deleted. The
# test tree is here for the same reason and was added by this lint's FIRST run, which
# reported the cross-language pin's own name: a tool that says where its behaviour is
# pinned is doing the right thing, and that name goes stale on a rename exactly like
# any other. `.claude/hooks` is a repository-level tree, not part of the
# plugin: `tools/release.py` loads `.claude/hooks/guard-release.py` by path and names
# it in its own prose, and that is this repository's configuration, not the plugin's
# product - the same reason `_tool_known_basenames` must look there too.
TOOL_NAME_TREES = (PLUGIN_REL + "/scripts", PLUGIN_REL + "/hooks",
                   "tests", TOOLS_REL, ".claude/hooks")

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
    NAME GOES. That exception is for a name that has to exist ON DISK carrying
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


# --- what a command declares vs what the README says it takes -------------------
# The args cell ends at an UNESCAPED pipe. Half these rows carry `\\|` inside
# them (`push [bugs\\|tasks\\|all] ...`), and a lazy `.*?` up to the first `|`
# truncates the cell there -- which reported six commands as missing flags that
# were plainly written two characters further along. Measured before believing:
# the first version of this check produced 20 findings, of which 2 were real.
_CMD_ROW = re.compile(r"^\|\s*`/audit:([a-z-]+)`\s*\|((?:\\\||[^|])*)\|",
                      re.MULTILINE)
_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


# THE FLAGS THAT CARRY A HUMAN'S OWN WORDS into the manifest and the
# hash-chained journal. A command doc that asks for one of these and does not say
# the text goes through UNCHANGED is a doc that lets a paraphrase be recorded --
# and the journal then proves the integrity of a sentence its subject never wrote.
# Measured live: the operator said "Tracked in ADO only, not executed here" and
# what was written was "tracked on the board only; this work is not executed
# through the audit pipeline".
#
# Matched on the FLAG rather than on a doc list, so a new command that gathers a
# reason is covered the day it is written rather than the day somebody remembers
# this rule. `--note` is `/audit:layout`'s, which composes its own value from the
# direction it was given and asks the operator for nothing - so the needle is what
# a HUMAN answers, which is a flag in three of the four cases and the WORD in the
# fourth: `/audit:bug close` records "a one-line `notes` justification" and names
# no flag at all, so a flag-only needle checked three docs and read the fourth as
# having nothing to discharge.
# `--confirm-high-risk` joined them the day it was written rather than the day
# somebody remembered this rule, which is what matching on the FLAG buys: its value
# is the human's answer to the orchestrator's high-risk gate and it reaches the same
# chain a cancel reason does, so a doc gathering it owes the same sentence.
VERBATIM_FLAGS = ("--reason", "justification", "--confirm-high-risk")

# The sentence that discharges it, and it is the BOLDED DIRECTIVE rather than the
# words. One spelling, because the rule itself lives in
# `reference/manifest-conventions.md` and this is the pointer at it -- two full
# copies of the argument is how one of them stops being true.
#
# WHY THE BOLD IS PART OF THE NEEDLE. The first version matched the bare words
# anywhere in the file, and `commands/task.md` then grew an ordinary
# cross-reference in prose - "(see *The operator's words go in VERBATIM* below)"
# - which is useful writing and not a rule being stated. That mention alone
# discharged the check, and the mutation harness caught it: deleting the real
# directive left the file passing. A MENTION IS NOT A STATEMENT, which is the
# same count-do-not-merely-find trap that `test__refs.py` guards elsewhere by
# checking a directive's survival inside the specific section it lives in,
# never merely its presence anywhere in the document.
VERBATIM_POINTER = "**The operator's words go in VERBATIM**"

# ...and the section the pointer names, so a pointer at a heading that has been
# renamed away is caught rather than read as compliance.
VERBATIM_RULE_DOC = "reference/manifest-conventions.md"
VERBATIM_RULE_HEADING = "## The operator's words go in unchanged"


def verbatim_rule_drift(repo_root=None):
    """{"missing": [command, ...], "checked": n, "ruleDoc": bool} -- docs that ask
    a human for text bound for the journal without saying it goes in unchanged.

    Subset, like `command_flag_drift`: the pointer has to be present, and where it
    sits inside the file is the author's business. `ruleDoc` is the other half --
    a pointer at a heading nobody kept is a pointer at nothing, and every doc
    would still pass.
    """
    root = repo_root or REPO_ROOT
    cdir = os.path.join(root, PLUGIN_REL, "commands")
    out, checked = [], 0
    try:
        names = sorted(os.listdir(cdir))
    except OSError as exc:
        return {"missing": ["<unlistable: %s>" % (exc,)], "checked": -1,
                "ruleDoc": False}
    for name in names:
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(cdir, name), "r",
                      encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        # The body only: a flag inside `argument-hint` is a DECLARATION, and a
        # command that merely accepts `--reason` passed on the command line asks
        # the operator for nothing.
        body = text.split("---", 2)[-1]
        if not any(flag in body for flag in VERBATIM_FLAGS):
            continue
        checked += 1
        if VERBATIM_POINTER not in body:
            out.append(name[:-3])
    rule_ok = False
    try:
        with open(os.path.join(root, PLUGIN_REL, VERBATIM_RULE_DOC),
                  "r", encoding="utf-8", errors="replace") as fh:
            rule_ok = VERBATIM_RULE_HEADING in fh.read()
    except OSError:
        rule_ok = False
    return {"missing": out, "checked": checked, "ruleDoc": rule_ok}


# --- the third word, for a proof that could not be made -------------------------
# AN EXECUTOR FIXED A SECURITY DEFECT, WROTE THE ASSERTION FOR IT, AND COULD
# NOT WATCH IT FAIL. Watching it fail meant undoing the fix for as long as one run
# takes - ordinary mutation testing - and the HOST's permission classifier refused
# that edit as a security-test removal. What came back was "treat that as an
# inference from the code, not as an observed red".
#
# The refusal is the host's and is not a defect. The INFERENCE is this plugin's.
# `agents/audit-executor.md` already says a verification claim carries its
# evidence and that a bare "verified" is reported as UNVERIFIED instead, so the
# rule was followed to the letter and still produced a sentence with no
# observation under it: a proof MADE and a proof NOT ATTEMPTED were the whole
# vocabulary, and a refusal is neither of them.
#
# THE WORD IS `could-not-run`'S SISTER AND NOT A SECOND CONVENTION.
# `run-test-gate.py` names the class "this produced NO VERDICT, for a reason that
# is not the work's" and `schema/audit-plan.schema.json` carries its doctrine -
# never rendered as a failure, never spends a retry. `could-not-prove` is that
# same sentence about the red-first proof instead of about the gate, and it is
# spelled to match rather than beside it.
RED_FIRST_PROVED = "proved"
RED_FIRST_CANNOT = "could-not-prove"
RED_FIRST_NOT_ATTEMPTED = "not-attempted"
RED_FIRST_WORDS = (RED_FIRST_PROVED, RED_FIRST_CANNOT, RED_FIRST_NOT_ATTEMPTED)

# What makes a document owe the word: it NAMES a red-first proof. Deliberately
# WIDER than "orders one", and the widening is measured rather than assumed - the
# order is spelled three ways in this plugin ("confirm red", "FAIL on current
# code", "red-first repro test"), so a needle per spelling is three needles each
# free to go stale on its own, while the concept has one spelling in this tree.
# What the widening costs is a clause in a document that only mentions a red-first
# proof in passing, and a document whose reader may be about to make one is not
# the wrong place for it.
RED_FIRST_TRIGGER = "red-first"

# ...and the word it then owes, written as the VALUE rather than as English. The
# same argument `VERBATIM_POINTER` makes for its bold: "could not prove" in a
# sentence is a report about a session, `could-not-prove` in backticks is the word
# that goes on the record, and only the second is what an executor writes down.
RED_FIRST_POINTER = "`" + RED_FIRST_CANNOT + "`"

# The directories read for the trigger - WHOLE DIRECTORIES rather than the
# documents carrying it today, because a check pointed only where a rule already
# holds can never report a new document arriving without it. That new document is
# what this exists for: this repo intends to offer "prove this test can fail" as
# an optional gate entry, which ships the mutate-the-fix instruction to users and
# puts the refusal in reach of any host's classifier. Whatever document states it
# is covered the day it is written, and not the day somebody remembers this rule.
#
# Each file is read WHOLE, frontmatter included, which is the opposite of
# `verbatim_rule_drift` above and for the reason that check gives: there,
# `argument-hint` is a DECLARATION and a command merely accepting a flag asks the
# operator for nothing. Here the frontmatter `description` is product prose - the
# line a user reads in the command list - so a proof ordered there is ordered in
# public.
RED_FIRST_DIRS = ("agents", "reference", "commands")

# Where the vocabulary is DEFINED rather than pointed at. The plan schema is where
# `could-not-run` keeps its own doctrine, and a pointer at a word nothing declares
# is a pointer at nothing - the half `verbatim_rule_drift` checks as `ruleDoc`.
RED_FIRST_SCHEMA = "schema/audit-plan.schema.json"
RED_FIRST_DEF = "redFirst"


def _red_first_schema_gaps(root):
    """[gap, ...] -- what the plan schema does not declare about the proof record.

    Empty is the healthy answer. An unreadable schema is a gap and not a skip: a
    check that quietly stopped reading the document it names would report a clean
    sheet over the one thing it could no longer see.
    """
    path = os.path.join(root, PLUGIN_REL, *RED_FIRST_SCHEMA.split("/"))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return ["<unreadable: %s>" % (exc,)]
    defs = doc.get("$defs") or {}
    props = (defs.get(RED_FIRST_DEF) or {}).get("properties") or {}
    enum = (props.get("status") or {}).get("enum") or []
    gaps = ["%s.status is missing %r" % (RED_FIRST_DEF, word)
            for word in RED_FIRST_WORDS if word not in enum]
    if "basis" not in props:
        gaps.append("%s.basis: a status with no basis under it is the inference "
                    "this word exists to replace" % RED_FIRST_DEF)
    ref = ((defs.get("task") or {}).get("properties")
           or {}).get(RED_FIRST_DEF) or {}
    if not str(ref.get("$ref") or "").endswith("/" + RED_FIRST_DEF):
        gaps.append("task.%s: the block is declared and the task does not carry "
                    "it, so the observation dies with the session" % RED_FIRST_DEF)
    return gaps


def red_first_drift(repo_root=None):
    """{"missing": [doc, ...], "checked": n, "schema": [gap, ...]} -- documents
    that name a red-first proof and offer no word for one that could not be made.

    Subset, like `verbatim_rule_drift` above: the pointer has to be present, and
    where it sits inside the file is the author's business. `schema` is the other
    half and it is the same argument one level down - every document can point at
    `could-not-prove` while nothing declares it, and the record then has nowhere
    to put the word the documents just promised.
    """
    root = repo_root or REPO_ROOT
    out, checked = [], 0
    for sub in RED_FIRST_DIRS:
        ddir = os.path.join(root, PLUGIN_REL, sub)
        try:
            names = sorted(os.listdir(ddir))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".md"):
                continue
            rel = "%s/%s" % (sub, name)
            try:
                with open(os.path.join(ddir, name), "r",
                          encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                out.append("%s <unreadable: %s>" % (rel, exc))
                continue
            if RED_FIRST_TRIGGER not in text:
                continue
            checked += 1
            if RED_FIRST_POINTER not in text:
                out.append(rel)
    return {"missing": out, "checked": checked,
            "schema": _red_first_schema_gaps(root)}


# --- one red-first vocabulary, from the schema outward -------------------------
# `red_first_drift` above holds that a document OFFERS the third word. This holds
# which words the two returns that carry a red-first grade may use at all, because
# they had drifted apart while each read as consistent on its own: the executor
# and the schema said `proved|could-not-prove|not-attempted`, and the reviewer
# graded with two words the schema rejects - one of them standing where the
# executor's `not-attempted` belonged - and told its reader the executor sends
# a word it never sends.
#
# THE SCHEMA ENUM IS THE ONE SOURCE, read here rather than copied. The executor's
# return writes onto `task.redFirst`, so it offers exactly those words: one fewer
# is a word nobody can write, one more is a word the record refuses. The
# reviewer ECHOES the executor's word when its basis holds, so it offers every
# schema word, plus the grades declared reviewer-only below and nothing else.
#
# PROSE IS READ FOR THE RETIRED WORDS ONLY. A word the vocabulary gave up is
# refused anywhere in either brief, as a backticked value, because a sentence
# telling an agent to write it is the drift the shape check cannot see. Other
# backticked words in prose are not graded: the gate words and the
# inherited-test words share this vocabulary's spelling shape, and a word being
# CURRENT is what the return shapes decide.
RED_FIRST_EXECUTOR_BRIEF = "agents/audit-executor.md"
RED_FIRST_REVIEWER_BRIEF = "agents/audit-reviewer.md"

# Grades only the reviewer gives, each with the reason no executor may use it.
# `not-proved` is the reviewer's own conclusion that nothing it was handed shows
# a red - a green run, a run that collected no test, a compile error, no named
# command at all. An executor that has watched nothing fail has a schema word for
# each of those cases, so the word is never the executor's to write onto the
# record, and it is kept apart from `could-not-prove` because the reviewer is
# grading evidence it was handed, not reporting an attempt of its own.
RED_FIRST_REVIEWER_ONLY = ("not-proved",)

# Words this vocabulary retired, refused anywhere in either brief. `not-applicable`
# was the reviewer's word for a proof nobody owed, which the schema spells
# `not-attempted`.
RED_FIRST_RETIRED = ("not-applicable",)

_RF_EXEC_SHAPE = re.compile(r'"redFirst":\s*\{\s*"status":\s*"([a-z|-]+)"')
_RF_REV_SHAPE = re.compile(r'"redFirst":\s*"([a-z|-]+)"')


def _red_first_enum(root):
    """`(words, problem)` - the schema's `redFirst.status` enum. Exactly one is None."""
    path = os.path.join(root, PLUGIN_REL, *RED_FIRST_SCHEMA.split("/"))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "%s: unreadable (%s)" % (RED_FIRST_SCHEMA, exc)
    enum = ((((doc.get("$defs") or {}).get(RED_FIRST_DEF) or {})
             .get("properties") or {}).get("status") or {}).get("enum") or []
    if not enum:
        return None, ("%s: $defs.%s.status declares no enum, so there is nothing "
                      "to hold either brief to" % (RED_FIRST_SCHEMA, RED_FIRST_DEF))
    return list(enum), None


def _declared_words(root, rel, shape):
    """`(words, problem)` - the one `a|b|c` list a brief's return shape declares."""
    path = os.path.join(root, PLUGIN_REL, *rel.split("/"))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return None, "%s: unreadable (%s)" % (rel, exc)
    hits = shape.findall(text)
    if len(hits) != 1:
        return None, ("%s: its return shape declares a `redFirst` word list %d "
                      "times, where one is the only count a reader can follow"
                      % (rel, len(hits)))
    return hits[0].split("|"), None


def red_first_vocabulary_drift(repo_root=None):
    """{"schema", "executor", "reviewer": [word, ...], "problems": [str, ...]}.

    Empty `problems` is the healthy answer. A list that could not be read is
    `[]` beside a problem naming why, never a list compared as if it were empty.
    """
    root = repo_root or REPO_ROOT
    schema, problem = _red_first_enum(root)
    problems = [problem] if problem else []
    execw, problem = _declared_words(root, RED_FIRST_EXECUTOR_BRIEF, _RF_EXEC_SHAPE)
    if problem:
        problems.append(problem)
    revw, problem = _declared_words(root, RED_FIRST_REVIEWER_BRIEF, _RF_REV_SHAPE)
    if problem:
        problems.append(problem)
    if schema is None:
        return {"schema": [], "executor": execw or [], "reviewer": revw or [],
                "problems": problems}
    allowed = set(schema) | set(RED_FIRST_REVIEWER_ONLY)
    problems.extend("%s: declared reviewer-only, but the schema declares it too, so "
                    "an executor may write it after all" % (w,)
                    for w in RED_FIRST_REVIEWER_ONLY if w in schema)
    if execw is not None:
        problems.extend("%s: offers %r, which the schema does not declare"
                        % (RED_FIRST_EXECUTOR_BRIEF, w)
                        for w in execw if w not in schema)
        problems.extend("%s: omits %r, which the schema declares, so no executor "
                        "can write it" % (RED_FIRST_EXECUTOR_BRIEF, w)
                        for w in schema if w not in execw)
    for rel in (RED_FIRST_EXECUTOR_BRIEF, RED_FIRST_REVIEWER_BRIEF):
        try:
            with open(os.path.join(root, PLUGIN_REL, *rel.split("/")), "r",
                      encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        problems.extend("%s: carries the retired word %r %d time(s) - the "
                        "vocabulary gave it up, so no sentence may ask for it"
                        % (rel, w, text.count("`%s`" % (w,)) + text.count(
                            '"%s"' % (w,)) + text.count("|%s" % (w,)))
                        for w in RED_FIRST_RETIRED
                        if ("`%s`" % (w,)) in text or ("|%s" % (w,)) in text
                        or ('"%s"' % (w,)) in text)
    if revw is not None:
        problems.extend("%s: grades with %r, which is neither a schema word nor a "
                        "declared reviewer-only grade" % (RED_FIRST_REVIEWER_BRIEF, w)
                        for w in revw if w not in allowed)
        problems.extend("%s: omits the schema word %r, so it cannot echo an "
                        "executor that sent it" % (RED_FIRST_REVIEWER_BRIEF, w)
                        for w in schema if w not in revw)
        problems.extend("%s: the declared reviewer-only grade %r is not in its "
                        "return, so the declaration admits a word nothing uses"
                        % (RED_FIRST_REVIEWER_BRIEF, w)
                        for w in RED_FIRST_REVIEWER_ONLY if w not in revw)
    return {"schema": schema, "executor": execw or [], "reviewer": revw or [],
            "problems": problems}


# --- the keys of a phase review's per-task entry ----------------------------------
# Under `review.perTask: phase` the phase reviewer answers each task in a `tasks`
# entry, and the filing verb refuses an entry that lacks a key of
# `_filed_returns.PHASE_ENTRY_KEYS`. The reviewer learns the keys from its return
# format, so the two are one tuple stated twice: a key the format drops is one no
# reviewer sends and every filing refuses, and a key the verb gains is one the
# format never asks for. The tuple is read off the verb's SOURCE rather than
# imported, because `_filed_returns` is a layer-mate of this module.
PHASE_RETURN_VERB = "scripts/manifest/_filed_returns.py"
PHASE_ENTRY_TUPLE = "PHASE_ENTRY_KEYS"
_PHASE_ENTRY_RE = re.compile(r'"tasks":\s*\[\{(.*?)\}', re.S)
_ENTRY_KEY_RE = re.compile(r'"([A-Za-z]+)":')


def _verb_entry_keys(root):
    """`(keys, problem)` - the literal `PHASE_ENTRY_KEYS` tuple in the verb."""
    rel = PHASE_RETURN_VERB
    try:
        with open(os.path.join(root, PLUGIN_REL, *rel.split("/")), "r",
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError) as exc:
        return None, "%s: unreadable (%s)" % (rel, exc)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == PHASE_ENTRY_TUPLE
                for t in node.targets) and isinstance(node.value, ast.Tuple):
            keys = [e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if keys:
                return keys, None
    return None, ("%s: declares no literal %s tuple, so there is nothing to hold "
                  "the reviewer's entry to" % (rel, PHASE_ENTRY_TUPLE))


def phase_return_key_drift(repo_root=None):
    """{"brief": [key, ...], "verb": [key, ...], "problems": [str, ...]} - the
    keys of the `tasks` entry in `agents/audit-reviewer.md`'s return format
    against the filing verb's tuple. Empty `problems` is the healthy answer; a
    side that cannot be read is a problem, never a list compared as empty."""
    root = repo_root or REPO_ROOT
    problems = []
    verb, problem = _verb_entry_keys(root)
    if problem:
        problems.append(problem)
    rel = RED_FIRST_REVIEWER_BRIEF
    try:
        with open(os.path.join(root, PLUGIN_REL, *rel.split("/")), "r",
                  encoding="utf-8", errors="replace") as fh:
            blocks = _PHASE_ENTRY_RE.findall(fh.read())
    except OSError as exc:
        blocks = None
        problems.append("%s: unreadable (%s)" % (rel, exc))
    brief = None
    if blocks is not None and len(blocks) != 1:
        problems.append("%s: its return format declares a `tasks` entry %d "
                        "times, where one is the only count a reader can follow"
                        % (rel, len(blocks)))
    elif blocks:
        brief = _ENTRY_KEY_RE.findall(blocks[0])
    if brief is not None and verb is not None:
        problems.extend("%s: the `tasks` entry omits %r, which the filing verb "
                        "refuses an entry without" % (rel, k)
                        for k in verb if k not in brief)
        problems.extend("%s: the `tasks` entry names %r, which the filing verb "
                        "does not read" % (rel, k) for k in brief if k not in verb)
    return {"brief": brief or [], "verb": verb or [], "problems": problems}


# --- the shape the executor hands back, and who has to keep asking for it -------
# A RETURN THE AGENT FILES IS CHECKED AT THE BOUNDARY; ONE IT DOES NOT IS PROSE.
# `audit-task.py file-return` parses a filed return and refuses one missing a
# field the brief declares (`_filed_returns.return_problems`), and `fr6` in
# `tests/test__filed_returns.py` deletes each declared field in
# turn and holds that the check names it - so the
# brief and the verb cannot drift apart. A return handed back without filing is
# still prose nothing parses, and the orchestrator -- the one actor that could
# quietly fill a gap in -- is its only reader. What THIS function checks is the
# other pair: the brief that declares the shape and the reference that has to ask
# for every field of it.
#
# THE DEFECT IT WAS WRITTEN FOR. `agents/audit-executor.md` declares the shape.
# `reference/execute-task.md` (the `## Execute the task` section, split out of
# `orchestrator.md` so a command that never runs a task does not read it) tells an
# orchestrator what to ask for, and carries a FALLBACK path -- the agent type is
# unavailable, so the rules get restated inline -- which named no `testsAdded` at
# all. That is the field `task.verifiedBy` is filled from, so on that path the
# test names an executor reported were asked for by nobody and recorded nowhere,
# and no gate could say so.
#
# WHY NOT THE OTHER TWO ROUTES, because both were available and neither reaches it.
# A manifest vocabulary entry grades a value once it has been WRITTEN INTO the plan,
# and a field nobody asked for never is -- the same blind spot the `redFirst` enum
# one function up states about itself. A script the orchestrator runs on the
# returned object would grade what the ORCHESTRATOR TYPED, which is a transcription
# made by the actor whose omission is the bug.
#
# WHAT IT STILL CANNOT SEE, written here because a green run is evidence of nothing
# wider: that the reader asks for a field in the right place, that it does anything
# with the answer, or that an executor ever filled the field in. A document naming
# every key in one dead sentence passes.
RETURN_SHAPE_BRIEF = RED_FIRST_EXECUTOR_BRIEF
RETURN_SHAPE_READER = "reference/execute-task.md"

# The sentence the declared block follows. The brief keeps the shape in one place
# and this reads it from there; a copy of the keys here would be the second
# declaration this check exists to refuse.
RETURN_SHAPE_TRIGGER = "Report back a structured outcome:"

# ...and how the reader has to name a field: IN BACKTICKS, never as the English
# word. `RED_FIRST_POINTER` makes this argument one function up -- `gates` in a
# sentence is a report about a run, `gates` in backticks is a key of the object a
# subagent hands back, and only the second is something a prompt can ask for.
_RETURN_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def _plugin_doc(root, rel):
    """(text, finding) for a document under the plugin, read whole.

    An unreadable document comes back as a FINDING and never as empty text: a scan
    that lost its own subject would otherwise report a clean sheet over the one
    thing it could no longer see.
    """
    path = os.path.join(root, PLUGIN_REL, *rel.split("/"))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, "%s <unreadable: %s>" % (rel, exc)


def _return_block(text):
    """The declared return object in the brief, or None when it declares none.

    The paragraph after the trigger, read by position: the brief writes the shape as
    one unbroken block, so blank-line to blank-line is the whole rule and no needle
    per field has to be kept in step with it.
    """
    at = (text or "").find(RETURN_SHAPE_TRIGGER)
    if at < 0:
        return None
    lines, started = [], False
    for line in text[at + len(RETURN_SHAPE_TRIGGER):].splitlines():
        if not line.strip():
            if started:
                break
            continue
        started = True
        lines.append(line)
    return "\n".join(lines) if started else None


def _return_keys(block):
    """The TOP-LEVEL field names of the declared block, in written order.

    DEPTH-AWARE RATHER THAN A LINE REGEX, and the restriction is the rule rather
    than an implementation detail. A nested key is named by the object that holds
    it -- `outcome` = `{ technical, descriptive }` names both halves in one breath
    -- so demanding each one again as a standalone backticked word would convict a
    reader for prose it has no reason to carry, and a check that over-fires on
    honest documents is one somebody routes around. A placeholder (`"<gate>"`) is
    not an identifier and is not one of these.
    """
    keys, depth, i = [], 0, 0
    while i < len(block):
        ch = block[i]
        if ch == '"':
            end = block.find('"', i + 1)
            if end < 0:
                break
            word = block[i + 1:end]
            after = end + 1
            while after < len(block) and block[after] in " \t\r\n":
                after += 1
            if (depth == 1
                    and after < len(block) and block[after] == ":"
                    and _RETURN_IDENT.match(word) and word not in keys):
                keys.append(word)
            i = end + 1
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return keys


def return_shape_drift(repo_root=None):
    """{"missing": [finding, ...], "keys": [field, ...]} -- fields of the executor's
    declared return that the orchestrator reference never asks for.

    Empty `missing` is the healthy answer. A brief that declares no shape, a block
    with no field in it and a document that cannot be read are all findings rather
    than skips, for the reason `_plugin_doc` gives.
    """
    root = repo_root or REPO_ROOT
    brief, unreadable = _plugin_doc(root, RETURN_SHAPE_BRIEF)
    if unreadable is not None:
        return {"missing": [unreadable], "keys": []}
    block = _return_block(brief)
    if block is None:
        return {"missing": ["%s: no return shape under %r"
                            % (RETURN_SHAPE_BRIEF, RETURN_SHAPE_TRIGGER)],
                "keys": []}
    keys = _return_keys(block)
    if not keys:
        return {"missing": ["%s: a declared return shape with no field in it"
                            % (RETURN_SHAPE_BRIEF,)], "keys": []}
    reader, unreadable = _plugin_doc(root, RETURN_SHAPE_READER)
    if unreadable is not None:
        return {"missing": [unreadable], "keys": keys}
    missing = ["%s: %s never asks for it" % (key, RETURN_SHAPE_READER)
               for key in keys if ("`" + key + "`") not in reader]
    return {"missing": missing, "keys": keys}


# --- the runners red reads, named in the documents that send an executor to it ---
# "A run whose output carries no tally the helper reads is `could-not-prove`" told
# an operator the answer and never which runners the helper reads, so one who had
# just linked their dependencies in learned nothing about whether their runner was
# one. Both documents now name them, and the list is graded against red's tally
# table rather than kept as prose a reader has to trust.
#
# READ BY AST, NOT IMPORTED. `_runner_output` is a layer-mate of this module, and
# the layer rule forbids a sideways import; the table is a tuple of literal pairs,
# so its names can be read off the source without running it. A table that stops
# being literal is a finding, never an empty list the documents are graded against.
RUNNER_LIST_SOURCE = ("scripts", "governance", "_runner_output.py")
RUNNER_LIST_TABLE = "TALLY_READERS"
RUNNER_LIST_DOCS = (RED_FIRST_EXECUTOR_BRIEF, RETURN_SHAPE_READER)

# The sentence each document carries, once. The runners are the backticked words
# from here to the sentence's first full stop, so the sentence holds the list and
# nothing else, and its explanation follows in the next sentence.
RUNNER_LIST_TRIGGER = "The runners whose tally the helper reads are"
_RUNNER_NAME = re.compile(r"`([^`\s]+)`")


def _tally_table_names(root):
    """`(names, problem)` - the runner names of red's tally table, read by AST.
    Exactly one of the two is None."""
    rel = "/".join(RUNNER_LIST_SOURCE)
    path = os.path.join(root, PLUGIN_REL, *RUNNER_LIST_SOURCE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError) as exc:
        return None, "%s: unreadable (%s)" % (rel, exc)
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == RUNNER_LIST_TABLE
                      for t in node.targets)]
    if len(values) != 1:
        return None, ("%s: assigns %s %d times at module level, where one is the "
                      "only count this check can read"
                      % (rel, RUNNER_LIST_TABLE, len(values)))
    value = values[0]
    pairs = value.elts if isinstance(value, (ast.Tuple, ast.List)) else []
    names = [pair.elts[0].value for pair in pairs
             if isinstance(pair, ast.Tuple) and pair.elts
             and isinstance(pair.elts[0], ast.Constant)
             and isinstance(pair.elts[0].value, str)]
    if not pairs or len(names) != len(pairs):
        return None, ("%s: %s is not a literal tuple of (name, reader) pairs, so "
                      "its runner names cannot be read without running it"
                      % (rel, RUNNER_LIST_TABLE))
    return names, None


def _named_runners(text):
    """`(names, count)` - the backticked runners of the one list sentence, and how
    many times the sentence occurs. `names` is None unless it occurs exactly once."""
    count = text.count(RUNNER_LIST_TRIGGER)
    if count != 1:
        return None, count
    start = text.index(RUNNER_LIST_TRIGGER) + len(RUNNER_LIST_TRIGGER)
    stop = text.find(".", start)
    span = text[start:stop if stop >= 0 else len(text)]
    return _RUNNER_NAME.findall(span), count


def runner_list_drift(repo_root=None):
    """{"runners": [name, ...], "problems": [finding, ...]} -- documents whose
    runner list names a runner red's tally table does not hold, or omits one it
    holds, each reported by document and runner.

    Empty `problems` is the healthy answer. An unreadable table, an unreadable
    document and a document carrying the sentence zero or several times are
    findings rather than skips, for the reason `_plugin_doc` gives.
    """
    root = repo_root or REPO_ROOT
    runners, problem = _tally_table_names(root)
    if problem is not None:
        return {"runners": [], "problems": [problem]}
    problems = []
    for rel in RUNNER_LIST_DOCS:
        text, unreadable = _plugin_doc(root, rel)
        if unreadable is not None:
            problems.append(unreadable)
            continue
        named, count = _named_runners(text)
        if named is None:
            problems.append("%s: carries %r %d time(s), where once is the only "
                            "count a reader can follow"
                            % (rel, RUNNER_LIST_TRIGGER, count))
            continue
        problems.extend("%s: names the runner %r, which red's tally table does "
                        "not hold" % (rel, name)
                        for name in named if name not in runners)
        problems.extend("%s: omits the runner %r, which red's tally table holds"
                        % (rel, name) for name in runners if name not in named)
    return {"runners": runners, "problems": problems}


# --- a followed rule names where the model meets it -------------------------------
# THE PIPELINE STOPPED READING REFERENCE PROSE, AND THE FOLLOWED TABLE HAD TO MOVE
# WITH IT. The README's second table lists the rules nothing refuses - the model
# follows them - and each row named a section of `reference/orchestrator.md` as
# where the rule is stated. That was true while every pipeline command told the main
# loop to read that file first. Once the step driver prints what a step needs, and
# the commands read no reference file (`tools/measure-context.py --gate` holds that),
# a row citing a reference section names prose its reader never opens: the rule is
# then followed by nobody, and the table still presents it as stated.
#
# So a row's "Stated in" has exactly two legal shapes, the two places the model meets
# a followed rule now:
#   * step `<name>` - a step of `drive-phase.py`'s `STEPS` whose `rule` is not
#     empty, so the driver prints the rule under that step's instruction;
#   * `<agent>.md` -> **<lead>** - a bullet of that agent's prompt opening with the
#     bolded lead, the prompt being the one text an agent always reads.
# WHAT THIS CANNOT SEE: whether the printed rule SAYS what the row says. It holds that
# the row names a place the model reads and that the place states a rule; reading the
# sentence against the row is the reviewer's, as it is for every prose rule.
FOLLOWED_DOC = "README.md"
FOLLOWED_HEADING = "### Followed from"
FOLLOWED_END = "**How a row moves left"
FOLLOWED_STEP_SOURCE = "scripts/governance/drive-phase.py"
FOLLOWED_STEP_TABLE = "STEPS"
_FOLLOWED_STEP = re.compile(r"\bstep `([a-z][a-z-]*)`")
_FOLLOWED_AGENT = re.compile("`([a-z][a-z-]*\\.md)` → \\*\\*(.+?)\\*\\*")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _followed_rows(text):
    """`(rows, problem)` - `[(invariant, stated_in)]` of the followed table, or why
    there is no table to read."""
    start = text.find(FOLLOWED_HEADING)
    if start < 0:
        return [], "%s has no `%s` table" % (FOLLOWED_DOC, FOLLOWED_HEADING)
    stop = text.find(FOLLOWED_END, start)
    rows = []
    for line in text[start:stop if stop >= 0 else len(text)].splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in _CELL_SPLIT.split(line.strip().strip("|"))]
        if len(cells) < 2 or cells[1] == "Stated in":
            continue
        rows.append((cells[0], cells[1]))
    if not rows:
        return [], "the `%s` table in %s has no row" % (FOLLOWED_HEADING, FOLLOWED_DOC)
    return rows, None


def _step_rules(root):
    """`(steps, problem)` - `{name: rule tuple}` read off the driver's literal
    `STEPS`, never by importing an entry point."""
    rel = FOLLOWED_STEP_SOURCE
    try:
        with open(os.path.join(root, PLUGIN_REL, *rel.split("/")), "r",
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError) as exc:
        return None, "%s: unreadable (%s)" % (rel, exc)
    # A rule shared by several steps is one module-level string the table names,
    # so a name bound to a string literal at module level reads as that string.
    strings = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                continue
            if isinstance(value, str):
                strings[node.targets[0].id] = value
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == FOLLOWED_STEP_TABLE
                for t in node.targets):
            for sub in ast.walk(node.value):
                for _field, child in ast.iter_fields(sub):
                    if isinstance(child, list):
                        child[:] = [ast.Constant(value=strings[c.id])
                                    if isinstance(c, ast.Name) and c.id in strings
                                    else c for c in child]
            try:
                table = ast.literal_eval(node.value)
            except ValueError:
                break
            return dict((k, tuple((v or {}).get("rule") or ()))
                        for k, v in table.items()), None
    return None, "%s: no literal %s table" % (rel, FOLLOWED_STEP_TABLE)


def followed_anchor_drift(repo_root=None):
    """{"rows": n, "anchors": n, "problems": [str, ...]} - every followed row whose
    "Stated in" names neither a driver step that prints its rule nor a bullet of
    an agent prompt.

    `rows` and `anchors` are counts beside the list because an empty list over a
    table that was never read is the silent pass this repository keeps
    re-finding; a missing table and a table with no row are problems themselves.
    """
    root = repo_root or REPO_ROOT
    text, problem = _plugin_doc(root, FOLLOWED_DOC)
    if problem is not None:
        return {"rows": 0, "anchors": 0, "problems": [problem]}
    rows, problem = _followed_rows(text)
    if problem is not None:
        return {"rows": 0, "anchors": 0, "problems": [problem]}
    steps, problem = _step_rules(root)
    problems = [problem] if problem else []
    prompts = {}
    anchors = 0
    for invariant, stated in rows:
        label = _clip_row(invariant)
        if "§" in stated:
            problems.append("%s: cites a reference section (%s), which no pipeline "
                            "command reads - name the driver step or the agent "
                            "prompt that states it" % (label, stated))
            continue
        named = 0
        for name in _FOLLOWED_STEP.findall(stated):
            named += 1
            if steps is None:
                continue
            if name not in steps:
                problems.append("%s: names step `%s`, which %s does not have"
                                % (label, name, FOLLOWED_STEP_SOURCE))
            elif not steps[name]:
                problems.append("%s: names step `%s`, whose rule is empty - the "
                                "driver prints no rule there" % (label, name))
        for agent, lead in _FOLLOWED_AGENT.findall(stated):
            named += 1
            if agent not in prompts:
                prompts[agent] = _plugin_doc(root, "agents/" + agent)
            body, unreadable = prompts[agent]
            if unreadable is not None:
                problems.append("%s: %s" % (label, unreadable))
            elif not re.search(r"^- \*\*" + re.escape(lead), body, re.M):
                problems.append("%s: names **%s** in %s, and no bullet of that "
                                "prompt opens with it" % (label, lead, agent))
        anchors += named
        if not named:
            problems.append("%s: names no driver step and no agent prompt section "
                            "(%s)" % (label, stated))
    return {"rows": len(rows), "anchors": anchors, "problems": problems}


def _clip_row(invariant):
    """A row's invariant, short enough to name it in a finding."""
    return invariant if len(invariant) <= 60 else invariant[:57] + "..."


def command_flag_drift(repo_root=None):
    """{"missing": [(command, flag), ...], "checked": n} -- flags the README omits.

    THE RULE: every flag a command's `argument-hint` declares must appear in that
    command's row of the README's command table. A SUBSET check and deliberately
    not equality: the two are written for different readers, and the README's
    column legitimately carries prose (`[scope/goals - you'll be interviewed]`)
    and escaped pipes that no frontmatter string would.

    Why it exists (and it was already true when written): `/audit:status`
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


# --- a placeholder the script answers itself -------------------------------------
# A command document that hands its script a `<manifestPath>` placeholder makes the
# MODEL fill it in. A thin command reads no reference stating the default, so the
# model guesses - and narrates the guess to the user. Once a script resolves the
# manifest itself (it calls `_manifest_io.resolve_manifest`), the placeholder is a
# question the model need not be asked, so a command line still asking it is
# reported. Which scripts resolve is read off their source, not listed here: a
# script that starts resolving later is held to this rule from that commit on.
MANIFEST_PLACEHOLDER = "<manifestPath>"
_RESOLVER_ATTR = "resolve_manifest"
_PLACEHOLDER_AFTER_RE = re.compile(
    r"([A-Za-z0-9_-]+\.py)\"?`?\s+" + re.escape(MANIFEST_PLACEHOLDER))
# Command documents that still hand a self-resolving script the placeholder, each
# with the reason it is not yet repaired. A row whose document no longer carries
# one is reported stale, so this table shrinks with the debt and never outlives it.
# Empty since the pipeline commands stopped reading the orchestration reference:
# their bodies now hand no self-resolving script a placeholder at all.
MANIFEST_PLACEHOLDER_PENDING = ()


def _calls_resolver(source):
    """True when `source` CALLS `<module>.resolve_manifest(...)`. Read off the AST,
    not the text: this file names the resolver in a string and a docstring, and
    neither is a call."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == _RESOLVER_ATTR
               for node in ast.walk(tree))


def self_resolving_scripts(repo_root=None):
    """Sorted basenames of every `.py` under `plugins/audit/scripts/` that calls
    `<module>.resolve_manifest(...)` - the scripts that find the manifest
    themselves."""
    root = repo_root or REPO_ROOT
    scripts = os.path.join(root, PLUGIN_REL.replace("/", os.sep), "scripts")
    out = []
    for relname, path in _output.py_files(scripts):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue
        if _calls_resolver(source):
            out.append(relname.rsplit("/", 1)[-1])
    return sorted(set(out))


def _logical_lines(lines):
    """[(first physical line number, text)] with every backslash-continued run
    joined into one line, the way the shell reads it - so a placeholder on a
    continuation is seen beside the script the command starts with. A line that
    does not end in a backslash is never joined to the next."""
    out = []
    start, parts = None, []
    for lineno, line in enumerate(lines, 1):
        if start is None:
            start = lineno
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            parts.append(stripped[:-1])
            continue
        parts.append(line)
        out.append((start, " ".join(parts)))
        start, parts = None, []
    if parts:
        out.append((start, " ".join(parts)))
    return out


def manifest_placeholder_drift(repo_root=None, pending=None):
    """[(doc, lineno, script)] - every line of `commands/*.md` handing a
    self-resolving script `<manifestPath>`, plus `(doc, 0, reason)` for a pending
    row whose document carries no such line any more. A command continued over
    backslash-ended lines is read as one line and reported at its first.

    WHAT THIS CANNOT SEE: `reference/` is not scanned - it is read by the
    orchestrator-driven commands, which state the default where the placeholder
    is used. A placeholder separated from its script by another argument
    (`x.py --json <manifestPath>`) is not matched; every call site writes the
    manifest first, which is the shape argparse's positional takes.
    """
    root = repo_root or REPO_ROOT
    rows = MANIFEST_PLACEHOLDER_PENDING if pending is None else pending
    excused = dict(rows)
    resolving = set(self_resolving_scripts(root))
    cmd_dir = os.path.join(root, PLUGIN_REL.replace("/", os.sep), "commands")
    try:
        names = sorted(n for n in os.listdir(cmd_dir) if n.endswith(".md"))
    except OSError as exc:
        return [("commands <unreadable: %s>" % (exc,), 0, "")]
    out = []
    carrying = set()
    for name in names:
        rel = "commands/" + name
        try:
            with open(os.path.join(cmd_dir, name), "r", encoding="utf-8",
                      errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError as exc:
            out.append(("%s <unreadable: %s>" % (rel, exc), 0, ""))
            continue
        for lineno, line in _logical_lines(lines):
            for match in _PLACEHOLDER_AFTER_RE.finditer(line):
                script = match.group(1)
                if script not in resolving:
                    continue
                carrying.add(rel)
                if rel not in excused:
                    out.append((rel, lineno, script))
    for rel, _reason in rows:
        if rel not in carrying:
            out.append((rel, 0, "stale pending row: no self-resolving script "
                                "is handed %s there any more"
                        % (MANIFEST_PLACEHOLDER,)))
    return out


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
# conversion named only half of the ones the tree carried, and pinning half would leave
# the rest free to rot in exactly the way this constant exists to prevent. Nothing
# holds the list whole any more - the rule that asked whether a document teaching the
# sweep was missing from it was retired - so a document that shows how to run the
# suites owes its entry here to whoever writes it.
#
# THE WORKFLOW IS NOT ONE ANY MORE. Every ci.yml job is setup plus one `tools/verify.sh
# --only <slices>` call, so the workflow teaches no sweep: verify.sh's sweep slices do,
# and a workflow listed here would be red for carrying no runner it has no reason to
# carry.
SWEEP_DOCS = (
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


# DIRECTORIES THIS REPO DOES NOT KEEP, and the walk over what is left. Both moved to
# `_output` when the prose-number scan needed the same answer: that scan is in the
# anchor, this module sits above it, and a copy in the anchor would be the
# two-prune-lists defect one layer down. The reasoning - why `.gitignore` and not a
# hand list, why only the unambiguous half of its format, and why the prose scans ask
# git for the tracked files first - went with the code and is not restated here.
#
# THE NAMES STAY, as three aliases rather than three wrappers: this module's cases
# call them, and a wrapper would be a second place for the argument order to be
# wrong.
_ignored_dirs = _output_lints._ignored_dirs
_is_ignored = _output_lints._is_ignored
_iter_docs = _output_lints.kept_files


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

    A `.gitignore` it cannot read is REPORTED and the scan stops: answering "nothing
    is ignored" would read scratch copies as things this repo published.

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


def pin_followers(drift):
    """The follower records `raw_url_pin_drift()`'s findings owe, one per
    document: a finding AT A LINE is a pin in that document, which only a hand
    can repair, so its recipe is None. A finding at line 0 is a document or a
    `.gitignore` that could not be read, and no edit of it is owed."""
    rels = sorted(set(rel for rel, line, _problem in drift if line > 0))
    return [{"path": rel, "recipe": None, "owner": "_refs.raw_url_pin_drift"}
            for rel in rels]


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
    # THE ONLY CALLER THAT DROPS IGNORED FILES, because it is the only one whose
    # subject is a COMMITTED page. The docstring above says so in its first line,
    # and the reason it gives for reading `.gitignore` at all - "scratch renders
    # would be read as published pages" - is exactly what the directory half alone
    # could not deliver: `docs/audit/audit-report.html` is gitignored, untracked
    # and on no branch, and it was reported as a stale published page on any
    # machine that had ever rendered one. The finding then depended on what
    # somebody last ran here rather than on anything in the commit.
    #
    # NOT an entry in a table: the exemption is the category "not committed", not
    # this file. A row per generated artifact is a hand list that grows with every
    # new one, and `EXCLUDED` already carries this same path for a DIFFERENT rule -
    # two tables naming one file for two reasons is how they come to disagree.
    ignored, problem = _output_lints._ignored_files(root)
    if problem is not None:
        return None, problem
    return _iter_docs(root, patterns, STAMP_EXT, drop=ignored), None


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

    - a `.gitignore` it cannot read: reported, and the scan stops - scratch renders
      would be read as published pages;
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

# Where a finding about the UI sources is filed. Spelled repo-relative because the
# rule is given a ROOT - a fixture, in every case but the live one.
_UI_DIR_REL = PLUGIN_REL + "/scripts/ui"

# The command that answers "what UI is a picture of". The digest is taken over the
# assembled report and panel pages, which sit in layers above this one, so this
# module may not import them and asks over a process boundary instead - the same
# question `tools/capture-screenshots.mjs` asks the same way.
_SURFACE_DIGEST_SCRIPT = "_surface_digest.py"
_SURFACE_DIGEST_TIMEOUT = 120


def _ui_digests_by_command(script=None):
    """`{"digests": ..., "unassigned": [...], "error": None|str}` from `_surface_digest.py`.

    `script` is the file to run and is the module's own unless a caller names another:
    the contract between this rule and the command is the thing under test, and it is
    tested with children that fail in each way a real one could.

    Always about the plugin tree THIS module was loaded from, never about the root
    the rule was handed: the pages are code, and a fixture root holds no code to
    assemble. A caller judging a fixture hands its own answer in as `ui`.

    A command that cannot be run, times out, exits without printing JSON, or prints
    something that is not the shape is an `error`, with what it wrote to stderr - so
    the rule reports "no digest" by name rather than comparing every picture against
    nothing. An exit status of 1 is not that: the command exits 1 for an `error` of
    its own and still prints it, so stdout is read before the status is trusted.
    """
    if script is None:
        script = os.path.join(_output.SCRIPTS_DIR, _SURFACE_DIGEST_SCRIPT)
    none = {"digests": {}, "unassigned": []}
    try:
        done = subprocess.run([sys.executable, script, "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=_SURFACE_DIGEST_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(none, error="%s could not be run, so no digest can stand for "
                                "what the pictures are of: %s"
                                % (os.path.basename(script), exc))
    out = done.stdout.decode("utf-8", "replace")
    err = done.stderr.decode("utf-8", "replace").strip()
    try:
        answer = json.loads(out)
    except ValueError:
        answer = None
    shaped = (isinstance(answer, dict) and isinstance(answer.get("digests"), dict)
              and isinstance(answer.get("unassigned"), list)
              and "error" in answer)
    if not shaped:
        return dict(none, error="%s exited %d without the answer it prints, so no "
                                "digest can stand for what the pictures are of: %s"
                                % (os.path.basename(script), done.returncode,
                                   err or out.strip() or "no output"))
    return answer


def _ui_source_findings(rel, entry, digests):
    """[(rel, line, problem), ...] - what one image's recorded UI digest says now.

    A MISSING DIGEST IS A FINDING, NOT SILENCE. Absence is not agreement: an entry
    with no digest makes the same claim every picture makes and nothing can settle
    it, which is exactly the gap this rule exists to close. The consequence is deliberate - this rule is
    red until a capture has written one, and a re-capture is the repair rather than
    a default filled in here.

    The surface comes off the ENTRY, written by the leg that took the shot, and is
    never inferred from the file name. A rule that read `panel-` off the front would
    be a second opinion about which surface a picture is of, and the capture's own
    answer is the one the pixels came from.
    """
    surface = entry.get("surface")
    digest = entry.get("uiDigest")
    if not isinstance(digest, str) or not digest:
        return [(rel, 0, "records no UI source digest, so whether it still shows "
                         "the current UI is unknown rather than settled - re-run "
                         "`node tools/capture-screenshots.mjs`")]
    if surface not in digests:
        return [(rel, 0, "records the surface %r, which is not one this tree "
                         "assembles (%s), so the digest beside it stands for "
                         "nothing" % (surface, ", ".join(sorted(digests))))]
    if digests[surface] != digest:
        return [(rel, 0, "was captured from a %s page digesting %s and it now "
                         "digests %s - the recorded version still agrees, so this "
                         "is the UI moving under a picture nobody re-shot; re-run "
                         "`node tools/capture-screenshots.mjs`"
                         % (surface, digest[:12], digests[surface][:12]))]
    return []


def _host_format_findings(rel, entry):
    """[(rel, line, problem), ...] - whether one image was written under the escape.

    `tools/capture-screenshots.mjs` refuses a shot whose native date inputs paint the
    host's regional format, unless it is run with `--accept-host-date-format`, and
    then records `nativeDateInput.hostFormatAccepted: true` beside the picture. The
    record is a basis; this is the claim made from it, so that a committed picture
    whose date fields are host-shaped is not something only a reader of the sidecar
    can learn.

    A FINDING, NOT A WARNING. This rule has no warning tier - what it returns is
    what `verify.sh` and CI fail on - and a warning nobody is made to read would
    restore the silence this exists to end. The picture is also not merely
    imperfect: its date fields show a format the product does not paint on the
    reference host, and the only way an entry carries the record is a deliberate
    override at capture time, which was already loud. Keeping the committed state
    loud too costs one re-capture on a host the check passes on, and it is the
    escape's own contract - the capture's note says the picture is written
    "as asked", not that it is fit to ship.

    ONLY A LITERAL `true` COUNTS. The tool never writes `false` (it leaves the key
    out), so an entry saying `false`, one with a `nativeDateInput` that is not an
    object, and one with none at all are all entries no escape wrote.
    """
    native = entry.get("nativeDateInput")
    if not isinstance(native, dict) or native.get("hostFormatAccepted") is not True:
        return []
    return [(rel, 0, "was written under --accept-host-date-format "
                     "(hostFormatAccepted: true, regional format %r), so its date "
                     "fields are host-shaped rather than en_US - re-run "
                     "`node tools/capture-screenshots.mjs` on a host the check "
                     "passes on and commit the result"
                     % (native.get("regionalFormat"),))]


def screenshot_capture_drift(repo_root=None, ui=None):
    """[(rel, line, problem), ...] - a committed screenshot that no longer shows this build.

    THE SAME QUESTION AS `artifact_version_drift()` ASKED OF A PICTURE, which is why
    it cannot be answered the same way. The panel paints its own version in the
    topbar and every shot starts at the top of the page, so each panel PNG makes a
    claim about which build it shows - and reading that claim back means reading text
    out of an image. `tools/capture-screenshots.mjs` refuses to compare these pixels
    at all, for reasons its own header sets out at length: font rasterisation differs
    between hosts and no environment variable pins it. That was settled once, and three
    repairs that would fake a wider claim are declined there by name.

    So the basis is recorded beside the pictures instead, by the run that took them,
    and this compares it. The record is not a guess: the panel leg asserts the LIVE
    topbar names `plugin.json`'s version before any shutter opens, so what the
    sidecar writes down is what was already checked.

    TWO QUESTIONS, NOT ONE, AND THE SECOND ARRIVED LATER. "Was this captured at
    this release" is what the version answers, but that is not
    the whole question: commits landed under `scripts/ui/` after the last
    re-capture, the recorded version was still current, and this rule was green
    over pictures of a panel that had since moved. "Does this picture still show
    the current UI" needs a basis of its own, so each entry also carries the digest
    of the PAGE its surface sends the browser, and `_ui_source_findings()`
    compares that. PER SURFACE, which is what makes it a rule rather than a
    nuisance: a report-only change reddens the report's pictures and leaves the
    panel's alone, and `_surface_digest.py` is the one home for what each of those
    pages is. It is taken over the assembled text, so an edit that leaves the page
    as it was - a comment in `_ui_theme.py` - owes no picture back. This module is
    below the pages and cannot import them, so the digest is asked of that file as
    a command; `ui` hands in an answer of the same shape instead (a fixture root
    holds no code to assemble, so a caller judging one supplies its own).

    Answers. The first four STOP the rule rather than adding to a list, because each
    of them leaves the comparison with no basis at all and every image would then be
    reported for want of one:

    - no sidecar, or one that will not parse: reported. The pictures make a claim
      and nothing can settle it, which is the state this rule exists to end - and
      staying quiet here would be indistinguishable from a tree that is current;
    - a `plugin.json` with no readable version: reported, for the reason the sibling
      rule gives - a guessed version would fail every image for the wrong reason;
    - not one image in the directory: reported. A candidate set that narrowed to
      nothing must not be spelled the same way as a set that all agrees, and that is
      the shape a moved output directory takes;
    - a UI digest that cannot be had (the command fails, or the sources cannot be
      walked): reported, for the same reason - there is then nothing for any
      recorded digest to be compared against;
    - otherwise a list: one per `ui/` part belonging to no surface, because a part
      no picture's digest covers is a part whose change could never turn one red;
      one per image whose recorded version is not the current one, naming BOTH; one
      per image the sidecar does not mention; one per entry whose file is gone or
      whose bytes have changed since it was written; and one per image whose
      recorded source digest is absent, names a surface this tree does not
      assemble, or no longer matches.
    - and one per image whose entry records `nativeDateInput.hostFormatAccepted:
      true`, in addition to any of the above (`_host_format_findings()` says why
      that is a finding and not a warning).

    WHAT THE HASH IS FOR. Without it the sidecar could be edited into agreement
    while the pictures stayed stale, and this rule would pass on a file someone
    typed. With it, agreeing with `plugin.json` requires the bytes to be the ones a
    capture wrote. It does not make the claim unforgeable - a hash can be recomputed
    - but forging it stops being something you do by accident, which is the failure
    this is about.

    `demo-gate.gif` is deliberately NOT in scope: its record lives in the same
    sidecar under its own `gifs` key, written by `tools/capture-demo-gif.py` when it
    records, and it is graded by that tool's `--check` rather than by this rule.
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
    if ui is None:
        ui = _ui_digests_by_command()
    if ui["error"]:
        # No fallback: without a digest to compare against, every image below
        # would clear for want of a comparison rather than because it agrees.
        return [(_UI_DIR_REL, 0, ui["error"])]
    out = []
    for unplaced in ui["unassigned"]:
        out.append((_UI_DIR_REL + "/" + unplaced, 0,
                    "ships in no surface this tree assembles, so no picture's "
                    "source digest covers it and changing it could never turn one "
                    "red"))
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
        else:
            # LAST, because the repairs are the same command and one finding per
            # image is what a reader can act on. A stale version already says
            # "re-capture"; saying it twice about one picture is noise.
            out.extend(_ui_source_findings(rel, entry, ui["digests"]))
        # Its own question, asked of every entry whose bytes could be read: the repair
        # differs from a stale build's (another host), so it may not be swallowed by
        # the chain above.
        out.extend(_host_format_findings(rel, entry))
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
    print(__doc__.strip())
