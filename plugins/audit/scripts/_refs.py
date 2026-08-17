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
"""

import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# scripts -> audit -> plugins -> the repo root. REPO_ROOT rather than "the plugin root":
# every `rel` this module produces already starts with `plugins/audit/`, so it is joined
# to the directory the plugin tree hangs UNDER, and joining it to the plugin's own
# directory would look for `plugins/audit/plugins/audit/scripts/...`.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
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


def _plugin_py_index(repo_root):
    """{basename: [repo-relative path, ...]} for every `.py` under `plugins/audit/`.

    Basename-keyed because that is the question a moved file poses: the recorded path is
    gone, is the FILE gone too or did it just move? `_deps` already forbids two `.py`
    sharing a basename, so a list with more than one entry means the tree is broken in a
    way that lint reports by name."""
    index = {}
    base = os.path.join(repo_root, PLUGIN_REL.replace("/", os.sep))
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
    index = _plugin_py_index(root)
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


# --- selftest -----------------------------------------------------------------
# EVERY FIXTURE PATH BELOW IS BUILT, NEVER SPELLED, and that is not fastidiousness. This
# file is itself an ANCHORED surface, so an anchor written immediately in front of a
# `scripts/…py` inside these cases is a REAL reference, and `c5` then reports the
# fixture as a missing file in the live tree. The first run of this suite proved it:
# c5 came back red naming ten of the lines below and one genuine defect, and the ten
# were indistinguishable from the one. Keeping the anchor and the path in separate
# string tokens on the same line is what the line-based pattern cannot rejoin.
# The self-scan is the module working; do not exempt the module from it.
_ANCHOR_LITERAL = "${CLAUDE_PLUGIN_ROOT}/"
_FX_SCRIPTS = PLUGIN_REL + "/scripts/"
_FX_HOOKS = PLUGIN_REL + "/hooks/"
_FX_COMMANDS = PLUGIN_REL + "/commands/"
_FX_TESTS = PLUGIN_REL + "/tests/"


def _write(root, rel, text):
    path = os.path.join(root, rel.replace("/", os.sep))
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _fixture_tree(tmp, command_line, hook_line=None):
    """A minimal repo: one real script, one commands/ document, one hooks/ file."""
    _write(tmp, _FX_SCRIPTS + "real.py", "# a real file\n")
    _write(tmp, _FX_COMMANDS + "x.md", "Run %s to do the thing.\n" % command_line)
    if hook_line is not None:
        _write(tmp, _FX_HOOKS + "h.py", hook_line + "\n")
    return tmp


def _selftest():
    """Nothing else in the tree stats a referenced script path, so this is the gate."""
    import shutil
    import tempfile

    ok = bad = 0

    def check(name, cond, detail=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("PASS %s" % name)
        else:
            bad += 1
            print("FAIL %s%s" % (name, (" :: %s" % detail) if detail else ""))

    # --- the tables ----------------------------------------------------------------
    surfaces = [s for s, _m in SURFACES]
    check("t1 every SURFACES entry is a real path - a surface pointing at nothing "
          "produces zero matches and reads exactly like a clean surface",
          [s for s in surfaces if not os.path.exists(os.path.join(REPO_ROOT, s))] == [],
          repr([s for s in surfaces if not os.path.exists(os.path.join(REPO_ROOT, s))]))
    _overlap = [x for x, _why in EXCLUDED
                if any(x == s or x.rstrip("/") == s for s in surfaces)]
    check("t2 nothing is both scanned and excluded - two tables disagreeing about one "
          "file is how an exclusion outlives its reason", _overlap == [], repr(_overlap))

    # --- a missing reference is reported --------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/no-such.py")
        res = missing_references(tmp, tmp)
        check("m1 a commands/ file naming a script that is not there is reported",
              len(res["missing"]) == 1
              and res["missing"][0][3] == _FX_SCRIPTS + "no-such.py"
              and res["missing"][0][0] == _FX_COMMANDS + "x.md",
              repr(res["missing"]))
        check("m2 ...and the placeholder/concrete split accounts for it: 1 checked, "
              "0 placeholders, 1 total",
              (res["checked"], len(res["placeholders"]), res["total"]) == (1, 0, 1),
              repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # MUTATION, BOTH DIRECTIONS. m3 is the case that looks vacuous and is not: it is the
    # only one that fails if the check becomes unconditional. m4 changes ONE character of
    # the same name, so a version that merely matched the regex would score m3 and m4
    # identically - `real.py` exists, `rea1.py` does not, and nothing else differs.
    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/real.py")
        res = missing_references(tmp, tmp)
        check("m3 a reference to a file that IS there is not reported, and the run "
              "still says it checked one - the always-fires mutation dies here",
              res["missing"] == [] and res["checked"] == 1, repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/rea1.py")
        res = missing_references(tmp, tmp)
        check("m4 one character of that same name changed and it is reported again - "
              "the check is the isfile, not the regex",
              len(res["missing"]) == 1
              and res["missing"][0][2] == "scripts/rea1.py", repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- placeholders are classified, never dropped ---------------------------------
    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/<name>.py and scripts/*.py")
        res = missing_references(tmp, tmp)
        check("p1 a placeholder and a glob are both SEEN (total 2) and both held out of "
              "the stat (checked 0), so neither vanishes and neither is a false miss",
              (res["total"], len(res["placeholders"]), res["checked"],
               res["missing"]) == (2, 2, 0, []), repr(res))
        check("p2 is_placeholder is the one rule, and it answers for both shapes",
              is_placeholder("plugins/audit/scripts/<n>.py")
              and is_placeholder("plugins/audit/scripts/*.py")
              and not is_placeholder("plugins/audit/scripts/_refs.py"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- anchored mode ---------------------------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        # The exact shape hooks/guard-secrets-read.py carries: a CONSUMER repo's file,
        # inside a bash payload, with nothing in front of it.
        _fixture_tree(tmp, "scripts/real.py",
                      hook_line="    bash('python3 -c \"open(\\'scripts/build.py\\')\"')")
        hits = [h for h in referenced_paths(tmp) if h[0].startswith(_FX_HOOKS)]
        check("a1 an UNanchored scripts/ path inside a hooks/*.py is a fixture about "
              "somebody else's repo and is not a reference here", hits == [], repr(hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/real.py",
                      hook_line='    MSG = "python3 \\"' + _ANCHOR_LITERAL
                                + 'scripts/real.py\\" status"')
        hits = [h for h in referenced_paths(tmp) if h[0].startswith(_FX_HOOKS)]
        check("a2 ...and the anchored form in the very same position IS one - the mode "
              "narrows by anchor, not by giving up on .py files",
              len(hits) == 1 and hits[0][3] == _FX_SCRIPTS + "real.py", repr(hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The same two claims on the REAL files, because a hand-written fixture and a
    # hand-written matcher can encode one assumption twice and agree about nothing.
    real = referenced_paths()
    hook_hits = [h for h in real if h[0].startswith(_FX_HOOKS)]
    hook_script_hits = [h for h in hook_hits if h[3].startswith(_FX_SCRIPTS)]
    check("a3 the real hooks/ tree reaches SCRIPTS exactly three times - the three "
          "${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py strings require-plan.py carries",
          len(hook_script_hits) == 3
          and set(h[0] for h in hook_script_hits) == set([_FX_HOOKS + "require-plan.py"])
          and set(h[3] for h in hook_script_hits)
          == set([_FX_SCRIPTS + "audit-lock.py"]), repr(hook_script_hits))
    check("a4 ...and guard-secrets-read.py's build.py fixture contributes none of them",
          [h for h in hook_hits
           if h[0].endswith("guard-secrets-read.py")] == [], repr(hook_hits))
    # The tests/ branch, on the real tree rather than on a fixture: `remind-tdd.py` is
    # a migrated hook, and its docstring and its `--selftest` pointer both name where
    # its cases went. Those are references, they are anchored, and they are now stat'd
    # - which is the whole reason the branch was added.
    hook_test_hits = [h for h in hook_hits if h[3].startswith(_FX_TESTS)]
    check("a5 an ANCHORED tests/ path in the plugin's own source is a reference and "
          "is resolved into plugins/audit/tests/: %r" % (hook_test_hits,),
          hook_test_hits
          and all(h[0] == _FX_HOOKS + "remind-tdd.py" for h in hook_test_hits)
          and set(h[3] for h in hook_test_hits)
          == set([_FX_TESTS + "test_remind_tdd.py", _FX_TESTS + "_harness.py"]))
    check("a6 ...and an UNanchored one is not - `hooks/_config.py` carries two "
          "consumer-repo test filenames as glob fixtures, and neither may be looked "
          "for in this plugin. Reads vacuous, and is the only case that fails if "
          "`tests` ever joins the bare alternation: %r"
          % ([h for h in real if h[0].endswith("_config.py")],),
          not any(h[3].startswith(_FX_TESTS)
                  for h in real if h[0].endswith("_config.py")))

    # --- anti-vacuity ----------------------------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        res = missing_references(tmp, REPO_ROOT)
        check("v1 with the tree pointed at an EMPTY directory every concrete reference "
              "comes back missing (%d of %d checked) - the existence test is a real "
              "stat, not something that short-circuits to fine"
              % (len(res["missing"]), res["checked"]),
              res["checked"] >= 120 and len(res["missing"]) == res["checked"],
              repr((len(res["missing"]), res["checked"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the count floor -------------------------------------------------------------
    counts = counts_by_surface(real)
    check("c1 the real tree carries at least 120 references (%d) - a pattern that "
          "quietly stops matching must fail HERE, not report 0 missing" % len(real),
          len(real) >= 120, repr(len(real)))
    _load_bearing = ("plugins/audit/commands", ".github/workflows/ci.yml",
                     "PLUGIN-BUILD-GUIDE.md", "plugins/audit/README.md")
    check("c2 each of the four surfaces that carry the bulk is non-zero: %r"
          % (dict((s, counts[s]) for s in _load_bearing),),
          all(counts[s] > 0 for s in _load_bearing))
    # SEEN AND ACCEPTED, not unnoticed: both are keys in the tally, so the day one of
    # them stops being scanned at all this reads KeyError rather than a comfortable 0.
    check("c3 agents/ and the root README name no script path today, and that is "
          "recorded rather than passed over",
          counts["plugins/audit/agents"] == 0 and counts["README.md"] == 0,
          repr((counts["plugins/audit/agents"], counts["README.md"])))
    check("c4 counts_by_surface is seeded from SURFACES, so every surface appears "
          "including the empty ones",
          sorted(counts) == sorted(surfaces))
    _res = missing_references()
    check("c5 nothing in the real tree references a script that is not there: %r"
          % (_res["missing"],), _res["missing"] == [])
    # The two prose uses of `scripts/*.py` in the guide have to survive as CLASSIFIED
    # placeholders. Counted, not merely found: one of the two disappearing would leave
    # a `>= 1` assertion green.
    _guide_globs = [h for h in _res["placeholders"]
                    if h[0] == "PLUGIN-BUILD-GUIDE.md"]
    check("c6 the guide's two prose `scripts/*.py` mentions are counted as "
          "placeholders, not dropped and not reported as missing files",
          len(_guide_globs) == 2 and all(h[2] == "scripts/*.py" for h in _guide_globs),
          repr(_guide_globs))

    # --- the plan's own file lists ---------------------------------------------------
    plan = manifest_moved_files()
    check("q1 the dogfood plan records no moved file, over %d recorded .py paths - "
          "the count is what separates that from having examined nothing"
          % plan["checked"],
          plan["moved"] == [] and plan["checked"] >= 70, repr(plan["checked"]))
    check("q2 ...and nothing in it is unreadable", plan["unreadable"] == [],
          repr(plan["unreadable"]))

    tmp = tempfile.mkdtemp()
    try:
        _moved_from = _FX_SCRIPTS + "_areas.py"
        _moved_to = _FX_SCRIPTS + "areas/_areas.py"
        _deleted = _FX_SCRIPTS + "_deleted.py"
        _write(tmp, _moved_to, "# moved down one\n")
        _write(tmp, _MANIFEST_REL, json.dumps(
            {"fileIndex": {_moved_from: ["P1.1"], _deleted: ["P1.2"],
                           "docs/index.html": ["P1.3"]}}))
        _write(tmp, _PHASES_REL + "/P1.json", json.dumps(
            {"tasks": [{"id": "P1.1", "files": [_moved_from]}]}))
        res = manifest_moved_files(tmp)
        check("q3 a recorded path whose file MOVED is loud, and says where it went - "
              "reported once per place that records it, index and shard alike",
              len(res["moved"]) == 2
              and all(m[1] == _moved_from and m[2] == _moved_to
                      for m in res["moved"]), repr(res["moved"]))
        # The other direction, and the case a reviewer would cut: a done task that
        # deleted a file is correct history, so an unconditional version fails here.
        check("q4 a recorded path whose basename exists NOWHERE is a deletion, stays "
              "out of `moved`, and is still counted in `gone`",
              res["gone"] == [("%s fileIndex" % _MANIFEST_REL, _deleted)],
              repr(res["gone"]))
        check("q5 a recorded path that is not this plugin's .py is not this lint's "
              "business: 3 recorded, 3 checked, docs/index.html untouched",
              res["checked"] == 3, repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, _MANIFEST_REL, "{not json")
        res = manifest_moved_files(tmp)
        check("q6 an unreadable plan is named, not reported as a clean zero",
              res["checked"] == 0 and len(res["unreadable"]) == 1
              and "unreadable" in res["unreadable"][0][1], repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the sweep -------------------------------------------------------------------
    drift = sweep_glob_drift()
    check("s1 every document that shows the selftest sweep shows the recursive form: "
          "%r" % (drift,), drift == [])

    tmp = tempfile.mkdtemp()
    try:
        for rel in SWEEP_DOCS:
            _write(tmp, rel, "Run:\n\n    %s\n" % SWEEP_FIND)
        check("s2 ...and that fixture is green, so the cases below fail for the reason "
              "they name and not because the fixture was broken",
              sweep_glob_drift(tmp) == [], repr(sweep_glob_drift(tmp)))
        _write(tmp, SWEEP_DOCS[0], "Run:\n\n    %s\n" % SWEEP_FLAT)
        _d = sweep_glob_drift(tmp)
        check("s3 a document that has drifted back to the flat glob is reported twice "
              "over - it lost the find form AND regained the glob",
              len([x for x in _d if x[0] == SWEEP_DOCS[0]]) == 2
              and any("flat sweep" in x[1] for x in _d)
              and any("recursive sweep" in x[1] for x in _d), repr(_d))
        _write(tmp, SWEEP_DOCS[0], "Run the suites somehow.\n")
        _d = sweep_glob_drift(tmp)
        check("s4 a document that simply stops carrying the sweep is reported once, "
              "and the two failures stay distinguishable",
              [x for x in _d if x[0] == SWEEP_DOCS[0]]
              == [(SWEEP_DOCS[0], "does not carry the recursive sweep %r" % SWEEP_FIND)],
              repr(_d))
        # Scoped to the executable shape. A version aimed at the substring `scripts/*.py`
        # would fail this fixture, and would fail the real guide - which is what c6's
        # placeholders show it legitimately writes twice.
        _write(tmp, SWEEP_DOCS[0],
               "The map is the import graph of `scripts/*.py`.\n\n    %s\n" % SWEEP_FIND)
        check("s5 prose that merely mentions the glob, beside a correct sweep, is NOT "
              "flagged - the rule is the runnable line, not the substring",
              sweep_glob_drift(tmp) == [], repr(sweep_glob_drift(tmp)))
        os.remove(os.path.join(tmp, SWEEP_DOCS[0].replace("/", os.sep)))
        _d = sweep_glob_drift(tmp)
        check("s6 a sweep document that has gone missing is unreadable, never absent",
              len(_d) == 1 and _d[0][0] == SWEEP_DOCS[0]
              and "unreadable" in _d[0][1], repr(_d))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # And on the real guide, which is where the prose actually lives.
    with open(os.path.join(REPO_ROOT, "PLUGIN-BUILD-GUIDE.md"),
              "r", encoding="utf-8") as fh:
        _guide = fh.read()
    check("s7 the real guide writes `scripts/*.py` as prose twice and carries the "
          "recursive sweep, and is green on both counts",
          _guide.count("scripts/*.py") == 2 and SWEEP_FIND in _guide
          and SWEEP_FLAT not in _guide, repr(_guide.count("scripts/*.py")))

    print(("ALL PASS: %d/%d cases passed" if not bad else
           "SELFTEST FAILED: %d/%d cases passed") % (ok, ok + bad))
    return 1 if bad else 0


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__.strip())
