#!/usr/bin/env python3
"""
The cases for `_refs.py`, moved out of it - a lint that scans the tree, from
inside the tree it scans.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THE ONE SHAPE THIS MOVE HAD TO CARRY WITH IT, AND IT IS THE UNUSUAL ONE. Nothing here
patches a module global, reads `globals()` or slices a source file - the three hazards
the earlier batches were about are all absent. What this suite has instead is a hazard
of its own, and it did not go away by moving: `_refs` scans `plugins/audit/tests` as an
ANCHORED surface, so THIS FILE is one of the documents it reads. An anchor written
immediately in front of a `scripts/…py` inside a case would be a REAL reference to a
fixture that exists for four milliseconds, and `c5` - a case in this very file - would
report it as a missing file in the live tree. The suite's first run inside `_refs.py`
proved exactly that: c5 came back red naming ten of its own fixture lines and one
genuine defect, and the ten were indistinguishable from the one. So every fixture path
below is BUILT from `M.PLUGIN_REL` and never spelled, and the anchor lives in
`_ANCHOR_LITERAL` as its own token. The constants moved here with the cases because
nothing in `_refs.py` ever read them; the surface changed name (`scripts/` to `tests/`)
and the rule did not.

`_write` and `_fixture_tree` moved for the same reason - both were declared in
`_refs.py`'s own `# --- selftest ---` section and had no caller outside it.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _refs as M                                  # noqa: E402
import _loader                                     # noqa: E402  (the reference resolver)
# The one home for which files a surface's pictures are OF, asked here the way
# `tools/capture-screenshots.mjs` asks it. Seeding a fixture's sidecar from it is
# what a capture does and is not circular: every RED case below then edits a source
# WITHOUT re-recording, so the two sides of the comparison come from two different
# states of the tree.
import _output                                     # noqa: E402


# --- fixture paths: built, never spelled --------------------------------------
_ANCHOR_LITERAL = "${CLAUDE_PLUGIN_ROOT}/"
_FX_SCRIPTS = M.PLUGIN_REL + "/scripts/"
_FX_HOOKS = M.PLUGIN_REL + "/hooks/"
_FX_COMMANDS = M.PLUGIN_REL + "/commands/"
_FX_TESTS = M.PLUGIN_REL + "/tests/"


# The two tools, named rather than spelled as paths, for the same reason every fixture
# path above is built: a basename is what survives a move, and `tool_basename_drift()`
# is the lint that makes that true of `tools/` prose as well.
_MJS_TOOL = "capture-screenshots.mjs"
_GIF_TOOL = "capture-demo-gif.py"

# ONE node invocation, every answer. Each JavaScript string is injected with
# `json.dumps`, which emits a valid JS string literal too - and on Windows that is not a
# nicety, it is the only thing that stops a backslash in a temp path from being read as
# an escape sequence. The import is a `file://` URL rather than a relative specifier
# because `--input-type=module -e` resolves relative imports against the cwd, which is a
# second thing that would have to be right.
_JS_PROBE = """
import { scriptIndex, resolveScript } from %(url)s;
const err = (fn) => {
  try { return { ok: true, value: fn() }; }
  catch (e) { return { ok: false, message: String((e && e.message) || e) }; }
};
const index = {};
for (const [name, paths] of scriptIndex()) index[name] = paths;
process.stdout.write(JSON.stringify({
  index: index,
  depth: err(() => resolveScript(%(depth)s)),
  missing: err(() => resolveScript(%(nosuch)s)),
  emptyTree: err(() => resolveScript(%(nosuch)s, %(empty)s)),
  duplicate: err(() => resolveScript(%(dup)s, %(fixture)s)),
  single: err(() => resolveScript(%(one)s, %(fixture)s)),
  separator: err(() => resolveScript(%(sep)s))
}));
"""


def _tool_src(name):
    """The source text of a `tools/` file, read off the repo root."""
    with open(os.path.join(M.REPO_ROOT, "tools", name), "r", encoding="utf-8") as fh:
        return fh.read()


def _write(root, rel, text):
    path = os.path.join(root, rel.replace("/", os.sep))
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _sc_sidecar(root, entries):
    """The sidecar `screenshot_capture_drift()` reads, written as the tool writes it."""
    _write(root, M._CAPTURED_AT,
           json.dumps({"note": "fixture", "images": entries}) + "\n")


def _sc_digest(root, rel):
    """The hash the tool would have recorded for the bytes now on disk."""
    with open(os.path.join(root, rel.replace("/", os.sep)), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _sweep_doc(rel, command, prose=""):
    """`command` written into `rel`'s RUNNABLE region, with `prose` outside it.

    The sweep fixtures have to be format-valid now that `M._runnable_text()` reads a
    region rather than the whole file: a bash fence in Markdown, a `run:` block in the
    workflow, `meta.buildCommands` in the manifest. A fixture that ignored that would
    fail every case below for the wrong reason - which is exactly what the first run
    after the region scope landed did, and why this helper exists rather than six
    literals. `prose` goes where each format puts a sentence: a paragraph, a comment,
    an unrelated key.
    """
    if rel.endswith(".md"):
        return "%s\n```bash\n%s\n```\n" % (prose, command)
    if rel.endswith((".yml", ".yaml")):
        return ("# %s\njobs:\n  t:\n    steps:\n      - run: |\n          %s\n"
                % (prose.replace("\n", " "), command))
    return json.dumps({"prose": prose,
                       "meta": {"buildCommands": {"sweep": command}}}, indent=2) + "\n"


# --- the floor `tb2` reads ----------------------------------------------------
# `tb1` answers "did any reference go stale", and that answer is worth nothing from a
# walk nobody watched: a walk that reached one file names no stale reference either.
# So `tb2` carries a floor - and the floor is what F72 was about. It was two ABSOLUTE
# terms, and on the day it was written both sat far below what the run printed beside
# them, so the walk could have shed almost the whole tree and still cleared them. Same
# defect as F69's `p1`, one file over.
#
# TWO TERMS EACH NOW. The absolute ones are unchanged - they answer "did this walk
# return anything at all", and nothing about them was wrong. The derived ones measure
# the walk against the tree it is supposed to be reading, counted by `_tools_tree_
# size()` rather than by the walk itself.
#
# WHAT THE DERIVED TERMS GIVE UP, SAID RATHER THAN IMPLIED. They COUPLE the walk to
# the tree: delete most of `tools/` and the floor falls with it, so a tree that really
# did shrink stays green - as it should, because the same deletion is a legitimate
# change and no floor derived from the thing it measures can tell the two apart. The
# case that direction leaves uncovered is a `tools/` that emptied, and it is covered
# by the ABSOLUTE terms, which is the whole reason they stay.
#
# THE DIVISORS DIFFER, AND NOT DECORATIVELY. `files` is judged at a fraction because
# the walk filters by extension: a picture or a `.txt` dropped into `tools/` is a file
# the tree holds and the walk is right to skip, and a floor at the full count would
# report that as a lost tree. `checked` counts OCCURRENCES across those files and owes
# no such allowance, so its derived term is one basename literal per file the tree
# holds. The case prints both figures beside both floors, which is where the margin is
# read rather than claimed here.
TB2_CHECKED_MINIMUM = 20
TB2_FILES_MINIMUM = 3
TB2_FILES_DIVISOR = 2


def _tools_tree_size(repo_root):
    """How many files sit under `tools/`, counted WITHOUT the walk under test.

    `os.walk` here and not `M._surface_files()`: a floor derived from the call it is
    judging cannot fail, because the walk that lost the tree shrinks the floor by
    exactly as much. Cruder than that call on purpose - no extension filter - and
    crude in the safe direction for a number a fraction is then taken of.
    """
    total = 0
    top = os.path.join(repo_root, M.TOOLS_REL.replace("/", os.sep))
    for _dir, dirnames, filenames in os.walk(top):
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        total += len(filenames)
    return total


def _tb2_floors(tree_size):
    """`(checked, files)` - the fewest of each that still evidences a read tree."""
    return (max(TB2_CHECKED_MINIMUM, tree_size),
            max(TB2_FILES_MINIMUM,
                (tree_size + TB2_FILES_DIVISOR - 1) // TB2_FILES_DIVISOR))


def _fixture_tree(tmp, command_line, hook_line=None):
    """A minimal repo: one real script, one commands/ document, one hooks/ file."""
    _write(tmp, _FX_SCRIPTS + "real.py", "# a real file\n")
    _write(tmp, _FX_COMMANDS + "x.md", "Run %s to do the thing.\n" % command_line)
    if hook_line is not None:
        _write(tmp, _FX_HOOKS + "h.py", hook_line + "\n")
    return tmp


# --- reading the plugin's own command documents --------------------------------
# The phase-verb cases below judge REAL product prose rather than a fixture: the
# rule they hold is a rule about `plugins/audit/commands/`, and a fixture would
# encode the assumption instead of the documents.
def _product_doc(rel):
    """A file under `plugins/audit/`, as text. Unreadable comes back EMPTY, which
    every case below fails on - a document that could not be opened must not be
    indistinguishable from one that satisfies the rule."""
    path = os.path.join(M.REPO_ROOT, M.PLUGIN_REL.replace("/", os.sep),
                        *rel.split("/"))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _frontmatter(text, key):
    """One `key: value` line out of a command document's frontmatter, unquoted."""
    hit = re.search(r"^%s:\s*(.+)$" % re.escape(key), text, re.M)
    if hit is None:
        return ""
    val = hit.group(1).strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
        val = val[1:-1]
    return val


def _md_section(text, heading_prefix):
    """The lines from the first `## ` heading starting with `heading_prefix` up to
    the next `## `. `""` when nothing matches, for `_product_doc`'s reason."""
    out, taking = [], False
    for line in text.split("\n"):
        if line.startswith("## "):
            if taking:
                break
            taking = line.startswith(heading_prefix)
            if not taking:
                continue
        if taking:
            out.append(line)
    return "\n".join(out)



# --- cases --------------------------------------------------------------------
def _cases(check):
    """Nothing else in the tree stats a referenced script path, so this is the gate."""
    # --- the repo root ---------------------------------------------------------------
    # This module used to derive REPO_ROOT itself, three `dirname`s off its own
    # `__file__`, beside an identical derivation in `_output`. One went. The case
    # recomputes the OLD expression rather than asserting the new one looks right.
    import _output as _out
    check("rr1 REPO_ROOT is the one in `_output`, not a second walk that happens "
          "to agree: %r" % (M.REPO_ROOT,), M.REPO_ROOT is _out.REPO_ROOT)
    check("rr2 ...and it is exactly what the old "
          "`dirname(dirname(dirname(_HERE)))` produced, with `plugins/audit` "
          "under it where every `rel` this module emits expects to find it",
          M.REPO_ROOT == os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.abspath(M.__file__)))))
          and os.path.isdir(os.path.join(M.REPO_ROOT, M.PLUGIN_REL.replace("/", os.sep))))

    # --- the tables ----------------------------------------------------------------
    surfaces = [s for s, _m in M.SURFACES]
    check("t1 every SURFACES entry is a real path - a surface pointing at nothing "
          "produces zero matches and reads exactly like a clean surface",
          [s for s in surfaces
           if not os.path.exists(os.path.join(M.REPO_ROOT, s))] == [],
          repr([s for s in surfaces
                if not os.path.exists(os.path.join(M.REPO_ROOT, s))]))
    _overlap = [x for x, _why in M.EXCLUDED
                if any(x == s or x.rstrip("/") == s for s in surfaces)]
    check("t2 nothing is both scanned and excluded - two tables disagreeing about one "
          "file is how an exclusion outlives its reason", _overlap == [], repr(_overlap))

    # --- a missing reference is reported --------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/no-such.py")
        res = M.missing_references(tmp, tmp)
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
        res = M.missing_references(tmp, tmp)
        check("m3 a reference to a file that IS there is not reported, and the run "
              "still says it checked one - the always-fires mutation dies here",
              res["missing"] == [] and res["checked"] == 1, repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/rea1.py")
        res = M.missing_references(tmp, tmp)
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
        res = M.missing_references(tmp, tmp)
        check("ph1 a placeholder and a glob are both SEEN (total 2) and both held out of "
              "the stat (checked 0), so neither vanishes and neither is a false miss",
              (res["total"], len(res["placeholders"]), res["checked"],
               res["missing"]) == (2, 2, 0, []), repr(res))
        # The three arguments stay SPELLED where every fixture path is built, and the
        # difference is the point: these are inputs to a pure predicate, not files a
        # case creates. Two are placeholders (held out of the stat by the very rule
        # under test) and the third is a real file, so all three are references this
        # module is happy to have - and keeping them literal is what makes `c1`'s
        # count identical on both sides of the move.
        check("ph2 is_placeholder is the one rule, and it answers for both shapes",
              M.is_placeholder("plugins/audit/scripts/<n>.py")
              and M.is_placeholder("plugins/audit/scripts/*.py")
              and not M.is_placeholder("plugins/audit/scripts/_refs.py"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- anchored mode ---------------------------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        # The exact shape hooks/guard-secrets-read.py carries: a CONSUMER repo's file,
        # inside a bash payload, with nothing in front of it.
        _fixture_tree(tmp, "scripts/real.py",
                      hook_line="    bash('python3 -c \"open(\\'scripts/build.py\\')\"')")
        hits = [h for h in M.referenced_paths(tmp) if h[0].startswith(_FX_HOOKS)]
        check("a1 an UNanchored scripts/ path inside a hooks/*.py is a fixture about "
              "somebody else's repo and is not a reference here", hits == [], repr(hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _fixture_tree(tmp, "scripts/real.py",
                      hook_line='    MSG = "python3 \\"' + _ANCHOR_LITERAL
                                + 'scripts/real.py\\" status"')
        hits = [h for h in M.referenced_paths(tmp) if h[0].startswith(_FX_HOOKS)]
        check("a2 ...and the anchored form in the very same position IS one - the mode "
              "narrows by anchor, not by giving up on .py files",
              len(hits) == 1 and hits[0][3] == _FX_SCRIPTS + "real.py", repr(hits))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The same two claims on the REAL files, because a hand-written fixture and a
    # hand-written matcher can encode one assumption twice and agree about nothing.
    real = M.referenced_paths()
    hook_hits = [h for h in real if h[0].startswith(_FX_HOOKS)]
    hook_script_hits = [h for h in hook_hits if h[3].startswith(_FX_SCRIPTS)]
    check("a3 the real hooks/ tree reaches SCRIPTS exactly three times - the three "
          "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py strings "
          "require-plan.py carries. The DEPTH is part of the claim: the anchored "
          "pattern's tail spans directories, so a domain folder appearing in the "
          "path must keep the hit resolving to the file rather than dropping it",
          len(hook_script_hits) == 3
          and set(h[0] for h in hook_script_hits) == set([_FX_HOOKS + "require-plan.py"])
          and set(h[3] for h in hook_script_hits)
          == set([_FX_SCRIPTS + "governance/audit-lock.py"]), repr(hook_script_hits))
    # a4's subject moved with the suite it belongs to. The unanchored
    # `build.py` and `hooks/require-plan.py` inside guard-secrets-read's
    # Bash payloads are text a CONSUMER's shell command carries, and those cases now
    # live in `tests/test_guard_secrets_read.py`. The claim is unchanged - an
    # unanchored plugin path inside the plugin's OWN Python is a fixture, not a
    # reference - so it is made where the fixture actually is. Both halves matter:
    # the hook no longer carries it, and the test file must not start counting it.
    _fx_file = _FX_TESTS + "test_guard_secrets_read.py"
    check("a4 ...and guard-secrets-read.py's build.py fixture contributes none of them",
          [h for h in real if h[0] == _fx_file] == []
          and [h for h in hook_script_hits
               if h[0].endswith("guard-secrets-read.py")] == [],
          repr([h for h in real if h[0] == _fx_file]))
    # The tests/ branch, on the real tree rather than on a fixture: every hook is a
    # migrated hook now, and each one's docstring and `--selftest` pointer name where
    # its cases went. Those are references, they are anchored, and they are stat'd -
    # which is the whole reason the branch was added. Asserted as a MAP rather than as
    # a count: every hit must resolve either to `_harness.py` or to the test file
    # `_output._test_name_for()` derives from that hook's own name, so a docstring
    # pointing a reader at some OTHER hook's suite fails here rather than passing as
    # one more anchored path that happens to exist.
    hook_test_hits = [h for h in hook_hits if h[3].startswith(_FX_TESTS)]

    def _own_suite(hook_rel):
        base = os.path.basename(hook_rel)[:-3].replace("-", "_")
        return _FX_TESTS + "test_%s.py" % base

    check("a5 an ANCHORED tests/ path in the plugin's own source is a reference, is "
          "resolved into plugins/audit/tests/, and names that file's OWN suite (or "
          "the harness): %d hits over %d hooks"
          % (len(hook_test_hits),
             len(set(h[0] for h in hook_test_hits))),
          len(set(h[0] for h in hook_test_hits)) == 11
          and all(h[3] in (_FX_TESTS + "_harness.py", _own_suite(h[0]))
                  for h in hook_test_hits), repr(hook_test_hits))
    # The two consumer-repo glob fixtures moved WITH `_config.py`'s suite, from
    # `hooks/_config.py` into `tests/test__config.py` - which is the arrival this
    # surface was made ANCHORED for, and the reason the case now names the file they
    # live in rather than the file they came from.
    _consumer = (_FX_TESTS + "test_cart.py", _FX_TESTS + "cart_test.py")
    check("a6 ...and an UNanchored one is not - `tests/test__config.py` carries two "
          "consumer-repo test filenames as glob fixtures, and neither may be looked "
          "for in this plugin. Reads vacuous, and is the only case that fails if "
          "`tests` ever joins the bare alternation: %r"
          % ([h for h in real if h[3] in _consumer],),
          not any(h[3] in _consumer for h in real))

    # --- anti-vacuity ----------------------------------------------------------------
    tmp = tempfile.mkdtemp()
    try:
        res = M.missing_references(tmp, M.REPO_ROOT)
        check("v1 with the tree pointed at an EMPTY directory every concrete reference "
              "comes back missing (%d of %d checked) - the existence test is a real "
              "stat, not something that short-circuits to fine"
              % (len(res["missing"]), res["checked"]),
              res["checked"] >= 120 and len(res["missing"]) == res["checked"],
              repr((len(res["missing"]), res["checked"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the count floor -------------------------------------------------------------
    counts = M.counts_by_surface(real)
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
    # The root README used to be a zero here too. It stopped being one when its
    # enforcement table began naming `scripts/governance/verify-invariants.py` — the
    # script that turns the table's own `post-hoc` rows into checked ones — and a
    # README that names a script path is exactly what this scanner is FOR, so the
    # recorded fact moved rather than the rule.
    check("c3 agents/ names no script path today, and that is recorded rather "
          "than passed over; the root README names at least one and every one of "
          "them is stat'd like any other",
          counts["plugins/audit/agents"] == 0 and counts["README.md"] > 0,
          repr((counts["plugins/audit/agents"], counts["README.md"])))
    check("c4 counts_by_surface is seeded from SURFACES, so every surface appears "
          "including the empty ones",
          sorted(counts) == sorted(surfaces))
    _res = M.missing_references()
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
    plan = M.manifest_moved_files()
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
        _write(tmp, M._MANIFEST_REL, json.dumps(
            {"fileIndex": {_moved_from: ["P1.1"], _deleted: ["P1.2"],
                           "docs/index.html": ["P1.3"]}}))
        _write(tmp, M._PHASES_REL + "/P1.json", json.dumps(
            {"tasks": [{"id": "P1.1", "files": [_moved_from]}]}))
        res = M.manifest_moved_files(tmp)
        check("q3 a recorded path whose file MOVED is loud, and says where it went - "
              "reported once per place that records it, index and shard alike",
              len(res["moved"]) == 2
              and all(m[1] == _moved_from and m[2] == _moved_to
                      for m in res["moved"]), repr(res["moved"]))
        # The other direction, and the case a reviewer would cut: a done task that
        # deleted a file is correct history, so an unconditional version fails here.
        check("q4 a recorded path whose basename exists NOWHERE is a deletion, stays "
              "out of `moved`, and is still counted in `gone`",
              res["gone"] == [("%s fileIndex" % M._MANIFEST_REL, _deleted)],
              repr(res["gone"]))
        check("q5 a recorded path that is not this plugin's .py is not this lint's "
              "business: 3 recorded, 3 checked, docs/index.html untouched",
              res["checked"] == 3, repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, M._MANIFEST_REL, "{not json")
        res = M.manifest_moved_files(tmp)
        check("q6 an unreadable plan is named, not reported as a clean zero",
              res["checked"] == 0 and len(res["unreadable"]) == 1
              and "unreadable" in res["unreadable"][0][1], repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the basenames tools/ names --------------------------------------------------
    tb = M.tool_basename_drift()
    # The detail prints only on FAILURE, which is the one moment an author needs it:
    # meeting this rule with a fixture used to end in a guess, and it was guessed
    # twice (F68).
    check("tb1 no `.py` basename written anywhere in tools/ names a file that is gone: "
          "%r" % (tb["unknown"],), tb["unknown"] == [],
          "if a name above is a FIXTURE rather than a reference, it is spelled around "
          "rather than exempted - `tool_basename_drift()`'s docstring lists the "
          "spellings; TOOL_FIXTURE_BASENAMES is only for a name that must be on disk")
    check("tb1b ...and no declared tool fixture has outlived what writes it: %r"
          % (tb["staleFixtures"],), tb["staleFixtures"] == [])
    _tb_size = _tools_tree_size(M.REPO_ROOT)
    _tb_cfloor, _tb_ffloor = _tb2_floors(_tb_size)
    check("tb2 ...and the run says how much it looked at - %d basename literals across "
          "%d files, against floors of %d and %d derived from the %d files tools/ holds. "
          "`unknown == []` means one thing at the counts printed here and something "
          "else entirely at 0, and a walk that lost most of the tree, or a regex that "
          "quietly stopped matching, would report the calm version of both"
          % (tb["checked"], tb["files"], _tb_cfloor, _tb_ffloor, _tb_size),
          tb["checked"] >= _tb_cfloor and tb["files"] >= _tb_ffloor,
          repr((tb["checked"], _tb_cfloor, tb["files"], _tb_ffloor, _tb_size)))

    # THE FIXTURE SIZE IS THE OLD FLOOR'S BLIND SPOT (F72), which is the only reason
    # this case is worth anything: a walk down to a handful of files CLEARS two
    # absolute terms of this size, and both versions of the floor score this fixture
    # while disagreeing about it.
    check("tb2a a tree this size lifts both floors above their absolute terms, which "
          "is what makes a walk that dropped to a handful of files red rather than "
          "green: %r" % (_tb2_floors(40),),
          _tb2_floors(40) == (40, 20))
    check("tb2b ...and a tools/ that holds NOTHING falls back to the absolute terms. "
          "This is the direction the derived ones cannot cover on their own - a "
          "fraction of nothing is nothing, and a floor of 0 would accept the emptiest "
          "walk there is: %r" % (_tb2_floors(0),),
          _tb2_floors(0) == (TB2_CHECKED_MINIMUM, TB2_FILES_MINIMUM))

    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, M.TOOLS_REL + "/probe.mjs", "// a tool\n")
        _write(tmp, M.TOOLS_REL + "/shot.png", "not really a picture\n")
        check("tb2c the size the floor is derived from is a SECOND walk, not the one "
              "it judges - it counts a file the lint's own walk filters out by "
              "extension, so a walk that lost the tree cannot shrink the floor with "
              "it: %r vs %r"
              % (_tools_tree_size(tmp), M._surface_files(tmp, M.TOOLS_REL, M.BARE)),
              _tools_tree_size(tmp) == 2
              and M._surface_files(tmp, M.TOOLS_REL, M.BARE)
              == [M.TOOLS_REL + "/probe.mjs"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, _FX_SCRIPTS + "real.py", "# a real file\n")
        _write(tmp, "tools/t.mjs", "spawn(PY, [join(S, 'no-such-name.py')]);\n")
        res = M.tool_basename_drift(tmp)
        check("tb3 a tools/ file naming a `.py` that exists nowhere is reported, with "
              "the file, the line and the name - this is the RENAME and the DELETION "
              "the path-matching lint above cannot see, because the line carries a "
              "basename and no directory in front of it",
              res["unknown"] == [("tools/t.mjs", 1, "no-such-name.py")],
              repr(res["unknown"]))
        # MUTATION, THE OTHER DIRECTION. One character apart from tb3 and nothing else
        # differs, so a version that merely matched the regex scores both the same.
        _write(tmp, "tools/t.mjs", "spawn(PY, [join(S, 'real.py')]);\n")
        res = M.tool_basename_drift(tmp)
        check("tb4 ...and the same shape naming a script that IS there is not reported, "
              "while the run still says it examined one - the check is the lookup, not "
              "the regex", res["unknown"] == [] and res["checked"] == 1, repr(res))
        # The tool trees, each proven by a name only that tree can supply.
        _write(tmp, _FX_HOOKS + "h.py", "# a hook\n")
        _write(tmp, _FX_TESTS + "test_h.py", "# a suite\n")
        _write(tmp, "tools/self.py", "usage: self.py --check; drives h.py, test_h.py\n")
        res = M.tool_basename_drift(tmp)
        check("tb5 a tool naming ITSELF, a hook, and a test file is green on all three "
              "- the four trees in TOOL_NAME_TREES are the ones a tool may legitimately "
              "name, and a rule that flagged a usage line would be switched off",
              res["unknown"] == [] and res["checked"] == 4, repr(res))
        # ---- the declared fixture table, both directions -------------------------
        # It exists because a tool's own cases WRITE `.py` files into a temp dir, and
        # those names are not references. The danger of any such table is that it
        # quietly becomes a blanket, so both halves are asserted here.
        first_fixture = M.TOOL_FIXTURE_BASENAMES[0][0]
        _write(tmp, "tools/fx.py",
               "open(join(tmp, '%s'), 'w').write(src)\n" % (first_fixture,))
        res = M.tool_basename_drift(tmp)
        check("tb5b a DECLARED fixture basename is not reported, even though no such "
              "file exists - that is the whole point of the table: %r"
              % (res["unknown"],),
              not any(n == first_fixture for _f, _l, n in res["unknown"]))
        _write(tmp, "tools/fx.py",
               "open(join(tmp, 'undeclared-fixture-name.py'), 'w').write(src)\n")
        res = M.tool_basename_drift(tmp)
        check("tb5c ...while an UNDECLARED name in the very same position IS reported. "
              "One entry apart from tb5b and nothing else differs, so a version that "
              "exempted every fixture-looking name scores both the same: %r"
              % (res["unknown"],),
              any(n == "undeclared-fixture-name.py" for _f, _l, n in res["unknown"]))
        check("tb5d ...and in a tree where NO fixture name is written, every declared "
              "entry is reported as STALE - a table of exemptions that cannot go out "
              "of date is a table that stops describing the system: %d of %d"
              % (len(res["staleFixtures"]), len(M.TOOL_FIXTURE_BASENAMES)),
              len(res["staleFixtures"]) == len(M.TOOL_FIXTURE_BASENAMES),
              repr(res["staleFixtures"][:2]))
        # PUT THE FIXTURE TREE BACK. tb6 below reads the same tmp root, and leaving
        # `tools/fx.py` behind made its `unknown == []` fail on a name this block
        # invented - a fixture leaking one case forward, which is the shape that
        # makes a suite order-dependent.
        _write(tmp, "tools/fx.py", "# nothing named here\n")
        # THE LIMIT, AS A CASE RATHER THAN AS A SENTENCE IN A DOCSTRING.
        _write(tmp, _FX_SCRIPTS + "domain/moved.py", "# filed under a label\n")
        _write(tmp, "tools/t.mjs", "spawn(PY, [join(S, 'domain', 'moved.py')]);\n")
        res = M.tool_basename_drift(tmp)
        check("tb6 a file that MOVED into a subdirectory is NOT reported - the basename "
              "still exists, so this lint is blind to it by construction. That is the "
              "whole reason the joins became resolvers: this covers a name that ceased "
              "to exist, and only a resolver covers a name that moved",
              res["unknown"] == [], repr(res["unknown"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        _write(tmp, "tools/t.mjs", "docs say <name>.py and *.py and cached.pyc\n")
        res = M.tool_basename_drift(tmp)
        check("tb7 the placeholder shapes and a `.pyc` are not tokens at all - excluded "
              "at the regex, which is why nothing filters them afterwards. Its own tmp "
              "root, because `checked` is a whole-tree count and a fixture carried over "
              "from tb5 would have made this read 3",
              res["unknown"] == [] and res["files"] == 1 and res["checked"] == 0,
              repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        # THE DOCUMENTED CONVENTION, AS A CASE (F68). The docstring tells an author
        # holding a fixture nothing creates to spell it around instead of adding a
        # table row, and names the shapes: no extension, the JavaScript module
        # extension, or a literal assembled from pieces. That is advice about THIS
        # REGEX, so it stops being true the moment the regex widens - and without
        # this case it would stop being true silently, in some later author's
        # unrelated edit. Every name below is invented, so any of the shapes
        # becoming a token raises `checked` AND puts a name that exists nowhere
        # into `unknown`.
        _write(tmp, "tools/t.mjs",
               "child = join(work, 'fixture_child')\n"
               "gates = ['tools/ghost.mjs', 'tools/alpha.mjs']\n"
               "probe = 'probe-' + 'no-such-tool' + '.py'\n")
        res = M.tool_basename_drift(tmp)
        check("tb7b the spellings the docstring offers for a fixture nothing creates "
              "are not tokens at all - an extensionless name, the JavaScript module "
              "extension, and an assembled literal - over a file that WAS read, "
              "which is what tells a convention that holds from a walk that found "
              "nothing",
              res["unknown"] == [] and res["files"] == 1 and res["checked"] == 0,
              repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp()
    try:
        res = M.tool_basename_drift(tmp)
        check("tb8 a root with no tools/ at all reads as 0 files and 0 literals, never "
              "as a clean tree - `unknown == []` is the same empty list either way and "
              "the counts are the only thing that tells them apart",
              res["unknown"] == [] and (res["files"], res["checked"]) == (0, 0),
              repr(res))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the JS resolver, held equal to `_loader`'s by READING both -------------------
    # `.mjs` cannot import Python, so `capture-screenshots.mjs` states the basename
    # resolution rule a fourth time (`_loader.py`, `_config.py`'s find_script and
    # `_output.py`'s script_files are the other three). It cannot be merged, so it is
    # pinned the way the pricing table is pinned between `_config.py` and
    # `_usage_core.py`: by a case that obtains both answers and compares them. The WHOLE
    # index, not one lookup - a probe asking about a single name would agree on that name
    # and know nothing about the other thirty-seven.
    _node = shutil.which("node")
    if _node is None:
        print("SKIP js1-js9 (node is not on PATH; the cross-language pin needs it)")
    else:
        tmp = tempfile.mkdtemp()
        try:
            _write(tmp, "fixture/one.py", "# the only claimant\n")
            _write(tmp, "fixture/a/dup.py", "# claimant one\n")
            _write(tmp, "fixture/b/dup.py", "# claimant two\n")
            os.makedirs(os.path.join(tmp, "empty"))
            _probe = _JS_PROBE % {
                "url": json.dumps(Path(os.path.join(M.REPO_ROOT, "tools",
                                                    _MJS_TOOL)).as_uri()),
                "depth": json.dumps("render-report.py"),
                "nosuch": json.dumps("no-such-script.py"),
                "dup": json.dumps("dup.py"),
                "one": json.dumps("one.py"),
                "sep": json.dumps("domain/render-report.py"),
                "empty": json.dumps(os.path.join(tmp, "empty")),
                "fixture": json.dumps(os.path.join(tmp, "fixture")),
            }
            _proc = subprocess.run([_node, "--input-type=module", "-e", _probe],
                                   cwd=M.REPO_ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
            check("js1 the probe ran - every case below is about its output, so a node "
                  "that refused to import the tool must fail HERE rather than leave "
                  "eight cases quietly asking about an empty dict",
                  _proc.returncode == 0 and _proc.stdout.strip(),
                  _proc.stderr.decode("utf-8", "replace")[-600:])
            js = json.loads(_proc.stdout.decode("utf-8")) if _proc.returncode == 0 \
                else {"index": {}}
            py_index = _loader.script_index()
            _only_py = sorted(set(py_index) - set(js["index"]))
            _only_js = sorted(set(js["index"]) - set(py_index))
            check("js2 the JavaScript index covers exactly the basenames "
                  "`_loader.script_index()` does - %d names, and the two difference "
                  "lists are the check: a walk that narrowed to nothing would disagree "
                  "about everything and a walk that widened would disagree about the "
                  "extras" % (len(py_index),),
                  py_index and not _only_py and not _only_js,
                  repr((_only_py, _only_js)))
            def _real(p):
                """Both sides build absolute paths their own way - one through
                `os.path.abspath`, one through node's path.join - and on macOS the
                temp root is a symlink, so the comparison has to be by realpath or it
                compares two spellings rather than two files."""
                return os.path.realpath(p or "")

            _differ = sorted(
                name for name in py_index
                if name in js["index"]
                and sorted(_real(p) for p in py_index[name])
                != sorted(_real(p) for p in js["index"][name]))
            check("js3 ...and every one of them resolves to the SAME FILE on both "
                  "sides, compared by realpath: %r" % (_differ,), not _differ)
            _depth = js.get("depth") or {}
            _py_depth = _loader.script_path("render-report.py")
            check("js4 the depth proof, and the one the migration turns on: the script "
                  "that has already moved resolves out of a SUBDIRECTORY of scripts/, "
                  "the same file `_loader` finds, and the tool never spelled the folder "
                  "- %r" % (_depth.get("value"),),
                  _depth.get("ok")
                  and _real(_depth.get("value") or "") == _real(_py_depth)
                  and os.path.dirname(_real(_py_depth))
                  != _real(_harness.SCRIPTS_DIR), repr(_depth))
            _miss = js.get("missing") or {}
            check("js5 refusal one: nothing with that name names the basename AND how "
                  "many files were searched, and the count here is non-zero",
                  not _miss.get("ok")
                  and "no-such-script.py" in (_miss.get("message") or "")
                  and ("among the %d " % sum(len(v) for v in py_index.values())
                       in (_miss.get("message") or "")), repr(_miss))
            _empty = js.get("emptyTree") or {}
            check("js6 ...and the SAME call over an empty tree says 0, which is what "
                  "keeps a typo distinguishable from a tree that was never walked. "
                  "Reads redundant beside js5 and is the only case that fails if the "
                  "count becomes a constant",
                  not _empty.get("ok")
                  and "among the 0 " in (_empty.get("message") or ""), repr(_empty))
            _dup = js.get("duplicate") or {}
            _single = js.get("single") or {}
            check("js7 refusal two: two files claiming one basename is refused naming "
                  "BOTH paths - picking either would run the wrong script under the "
                  "right name, which is the only failure this shape can produce in "
                  "silence",
                  not _dup.get("ok")
                  and os.path.join("a", "dup.py") in (_dup.get("message") or "")
                  and os.path.join("b", "dup.py") in (_dup.get("message") or ""),
                  repr(_dup))
            check("js8 ...and the very same fixture resolves the name only ONE file "
                  "claims, so js7 fails for the duplication and not because the test "
                  "seam was broken",
                  _single.get("ok")
                  and _real(_single.get("value") or "")
                  == _real(os.path.join(tmp, "fixture", "one.py")), repr(_single))
            _sep = js.get("separator") or {}
            check("js9 refusal three: a value carrying a directory separator is refused "
                  "naming the value, rather than being reduced to its basename - "
                  "dropping the directory a caller spelled is how a caller comes to "
                  "believe the directory mattered",
                  not _sep.get("ok")
                  and "domain/render-report.py" in (_sep.get("message") or ""),
                  repr(_sep))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- the domain name is gone from the tools --------------------------------------
    _mjs = _tool_src(_MJS_TOOL)
    _joins = re.findall(r"path\.join\(SCRIPTS,[^)]*\)", _mjs)
    check("d1 NO join of the SCRIPTS constant is left in the capture tool - every "
          "script site goes through the resolver (d2 counts them), and the one exempt "
          "site (a read of "
          "ui/panel.js, argued safe because a UI asset cannot be relabelled) died "
          "when panel.js was cut into parts and the path stopped existing. It asks "
          "Python for the ASSEMBLED page now. This is the case that goes red when a "
          "join creeps back: %r" % (_joins,),
          not _joins)
    check("d2 ...and THIRTEEN resolver calls are really there, resolving by BASENAME "
          "with no folder argument. Reads vacuous beside d1 and is the half that fails "
          "if the call sites were deleted rather than converted - the ninth arrived "
          "when the polled-state guard stopped reading ui/panel.js by path and started "
          "asking _panel_ui.py for the assembled page, three more when the "
          "report leg grew a PINNED fixture of its own (two set-priority.py writes and "
          "the render that reads them), and the newest when the run started asking "
          "_output.py which UI sources each surface's pictures are of. The number is "
          "exact on purpose - a floor would go on passing while a site was deleted, "
          "which is the only thing this case is for (got %d)"
          % (_mjs.count("resolveScript('"),),
          _mjs.count("resolveScript('") == 13
          and not re.search(r"resolveScript\('[^']*[/\\]", _mjs))
    _gif = _tool_src(_GIF_TOOL)
    check("d3 the Python tool carries no join of the SCRIPTS constant at all - it can "
          "import the resolver that already owns the answer, so it does, and there is "
          "no fifth copy of the rule",
          "os.path.join(SCRIPTS" not in _gif and 'resolve_script("' in _gif)
    check("d4 ...while its HOOKS join is untouched, because hooks/ is not being "
          "reorganised - flat by design, reached by a launcher that knows only the "
          "directory. The scope of the change is a claim, so it is asserted",
          "os.path.join(HOOKS" in _gif)
    _gif_mod = _loader.load(os.path.join(M.REPO_ROOT, "tools", _GIF_TOOL))
    check("d5 and the Python tool's resolver IS `_loader`'s, not a lookalike: it "
          "returns the identical path for the script it drives, at depth or not",
          _gif_mod.resolve_script("audit-status.py")
          == _loader.script_path("audit-status.py")
          and _gif_mod.resolve_script("render-report.py")
          == _loader.script_path("render-report.py"))

    # --- absolute paths used to reach a file -----------------------------------------
    _reach = M.absolute_reach_violations()
    check("ar1 nothing in this tree reaches a file by absolute path: %r"
          % (_reach["violations"],), _reach["violations"] == [])
    # The check on the check. An empty violations list is only meaningful if the
    # regexes matched anything at all; a typo in one of them reports a clean tree.
    check("ar2 ...and that verdict is over real observations - %d reach(es) across "
          "%d file(s), floors held so a regex that stopped matching cannot read as "
          "agreement" % (_reach["checked"], _reach["files"]),
          _reach["checked"] >= 40 and _reach["files"] >= 100)

    tmp = tempfile.mkdtemp()
    try:
        # A module specifier is a reach. The absolute specifier is BUILT rather
        # than spelled, for the reason this module's docstring already gives about
        # anchored fixtures: `tests/` is one of the surfaces this very lint scans,
        # so a literal here would be a real violation in the live tree - and it
        # was, on the first run of these cases. `/nowhere/` rather than a
        # plausible repo path for the same reason, one layer out.
        _abs_spec = "/" + "nowhere/sandbox.mjs"
        _write(tmp, "tools/bad.mjs",
               "import { x } from '%s';\n" % (_abs_spec,))
        _bad = M.absolute_reach_violations(repo_root=tmp)
        check("ar3 an absolute module specifier is caught, and named with its line: "
              "%r" % (_bad["violations"],),
              [(r, n) for r, n, _p in _bad["violations"]] == [("tools/bad.mjs", 1)])

        # THE REPAIR MUST PASS, or the lint forbids its own remedy.
        _write(tmp, "tools/bad.mjs", "import { x } from './sandbox.mjs';\n")
        _ok = M.absolute_reach_violations(repo_root=tmp)
        check("ar4 the repair passes: the same import written relatively is clean, "
              "and still COUNTED (%d) so the file was really read"
              % (_ok["checked"],),
              _ok["violations"] == [] and _ok["checked"] == 1)

        # The narrowness IS the design: an absolute path is legitimate as data.
        _write(tmp, "tools/bad.mjs",
               "const FONTS = ['/usr/share/fonts/x.ttf'];\n"
               "validate({ root: '/Users/me/proj' });\n")
        _data = M.absolute_reach_violations(repo_root=tmp)
        check("ar5 an absolute path that is DATA rather than a reach is not a "
              "violation - a font list and a fixture the code under test is asked "
              "to classify both stay clean (%r)" % (_data["violations"],),
              _data["violations"] == [])

        # The limit, in the direction it errs: this rule UNDER-reports.
        _write(tmp, "tools/bad.mjs",
               "const p = '/nowhere/sandbox.mjs';\nconst s = readFileSync(p);\n")
        _var = M.absolute_reach_violations(repo_root=tmp)
        check("ar6 a reach through a VARIABLE is invisible here, and that is stated "
              "rather than implied: this lint under-reports, the same way "
              "tool_basename_drift cannot see a move (%r)" % (_var["violations"],),
              _var["violations"] == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the sweep -------------------------------------------------------------------
    drift = M.sweep_glob_drift()
    check("s1 every document that shows the selftest sweep runs the RUNNER, and "
          "neither hand-written loop survives in a runnable region: %r" % (drift,),
          drift == [])

    tmp = tempfile.mkdtemp()
    # One document per format, named rather than indexed, because the three cases that
    # matter now are each about a DIFFERENT runnable region and `SWEEP_DOCS[0]` says
    # nothing about which.
    _yml = [r for r in M.SWEEP_DOCS if r.endswith((".yml", ".yaml"))][0]
    _md = [r for r in M.SWEEP_DOCS if r.endswith(".md")][0]
    _jsn = [r for r in M.SWEEP_DOCS if r.endswith(".json")][0]
    try:
        for rel in M.SWEEP_DOCS:
            _write(tmp, rel, _sweep_doc(rel, M.SWEEP_RUNNER))
        check("s2 ...and that fixture is green, so the cases below fail for the reason "
              "they name and not because the fixture was broken",
              M.sweep_glob_drift(tmp) == [], repr(M.sweep_glob_drift(tmp)))
        _write(tmp, _yml, _sweep_doc(_yml, M.SWEEP_FLAT))
        _d = M.sweep_glob_drift(tmp)
        check("s3 a document that has drifted back to the flat glob is reported twice "
              "over - it lost the runner AND regained a retired shape",
              len([x for x in _d if x[0] == _yml]) == 2
              and any("flat sweep" in x[1] for x in _d)
              and any("sweep runner" in x[1] for x in _d), repr(_d))
        _write(tmp, _yml, _sweep_doc(_yml, "make test"))
        _d = M.sweep_glob_drift(tmp)
        check("s4 a document that simply stops carrying the sweep is reported once, "
              "and the two failures stay distinguishable",
              [x for x in _d if x[0] == _yml]
              == [(_yml, "does not carry the sweep runner %r" % M.SWEEP_RUNNER)],
              repr(_d))
        # Scoped to the executable shape AND to the executable REGION. A version aimed
        # at the substring `scripts/*.py` would fail the first half of this fixture, and
        # would fail the real guide - which is what c6's placeholders show it
        # legitimately writes twice. A version aimed at the whole FILE would fail the
        # second half, which is F21's shape exactly: a document warning against the
        # retired sweep, reported as carrying it.
        _write(tmp, _yml, _sweep_doc(
            _yml, M.SWEEP_RUNNER,
            "The map is the import graph of `scripts/*.py`. "
            "Never write `%s ...` - the glob is flat." % M.SWEEP_FLAT))
        check("s5 prose beside a correct sweep is NOT flagged, and that now covers the "
              "retired sweep QUOTED IN A WARNING AGAINST IT: the rule is the runnable "
              "region, not the substring and not the file",
              M.sweep_glob_drift(tmp) == [], repr(M.sweep_glob_drift(tmp)))
        os.remove(os.path.join(tmp, _yml.replace("/", os.sep)))
        _d = M.sweep_glob_drift(tmp)
        check("s6 a sweep document that has gone missing is unreadable, never absent",
              len(_d) == 1 and _d[0][0] == _yml
              and "unreadable" in _d[0][1], repr(_d))

        # ---- the quiet direction: prose that makes the check PASS ----------------
        _write(tmp, _yml, _sweep_doc(_yml, M.SWEEP_RUNNER))
        # The flat listing is BUILT, never spelled: this file is one of the ANCHORED
        # surfaces `_refs` scans, and an anchor written in front of a glob here would
        # be a real reference the placeholder counts have to account for. Same rule as
        # every other fixture path in this suite.
        _write(tmp, _md, _sweep_doc(
            _md, "for f in $(ls %s/scripts/*.py); do python3 \"$f\"; done"
                 % M.PLUGIN_REL,
            "The sweep is `%s`, never a hand-written loop." % M.SWEEP_RUNNER))
        _d = M.sweep_glob_drift(tmp)
        check("s8 a document whose PROSE quotes the recursive sweep while the block a "
              "reader would run is a flat listing does NOT satisfy the rule - the "
              "direction that hurts is the mention that makes a check pass, and the "
              "whole-file substring could not tell the two apart",
              [x for x in _d if x[0] == _md]
              == [(_md, "does not carry the sweep runner %r" % M.SWEEP_RUNNER)],
              repr(_d))

        # ---- mutation proof: the whole-file scan this replaced misses s8 ----------
        def _whole_file_sweep_drift(root):
            out = []
            for rel in M.SWEEP_DOCS:
                with open(os.path.join(root, rel.replace("/", os.sep)),
                          "r", encoding="utf-8") as fh:
                    text = fh.read()
                if M.SWEEP_RUNNER not in text:
                    out.append((rel, "does not carry the sweep runner %r"
                                % M.SWEEP_RUNNER))
                if M.SWEEP_FLAT in text:
                    out.append((rel, "still carries the flat sweep %r" % M.SWEEP_FLAT))
            return out

        check("s9 mutation proof: the whole-file form this replaced reads that same "
              "fixture as clean, because the prose mention satisfied it - red proves "
              "s8 tests the region and not the wording",
              [x for x in _whole_file_sweep_drift(tmp) if x[0] == _md] == [],
              repr(_whole_file_sweep_drift(tmp)))
        check("s10 mutation proof: the real, region-scoped sweep_glob_drift() still "
              "catches it - nothing was left mutated behind",
              any(x[0] == _md for x in M.sweep_glob_drift(tmp)))

        # ---- the OTHER retired shape, which is the half this rule just grew -----
        _write(tmp, _yml, _sweep_doc(_yml, M.SWEEP_FIND))
        _d = [x for x in M.sweep_glob_drift(tmp) if x[0] == _yml]
        check("s13 the hand-written recursive loop is RETIRED TOO, and reported for "
              "both halves: it is not the runner, and it is a shape a document may "
              "no longer tell anyone to run. It was the REQUIRED form until the "
              "runner existed, so without this case half the rule could be deleted "
              "with everything above still green: %r" % (_d,),
              len(_d) == 2
              and any("does not carry the sweep runner" in x[1] for x in _d)
              and any("hand-written sweep" in x[1] for x in _d))
        check("s14 ...and the two retired shapes are reported under DIFFERENT words, "
              "so a reader is told which loop they wrote rather than that something "
              "is wrong",
              M.RETIRED_SWEEPS[0][1] != M.RETIRED_SWEEPS[1][1]
              and len(M.RETIRED_SWEEPS) == 2)

        # ---- a region that cannot be read is loud, never a fallback --------------
        _write(tmp, _md, _sweep_doc(_md, M.SWEEP_RUNNER))
        _write(tmp, _jsn, "{ this is not json at all\n%s\n" % M.SWEEP_RUNNER)
        _d = M.sweep_glob_drift(tmp)
        check("s11 a manifest that will not parse is reported as unreadable commands, "
              "not read as text - a fallback to the whole file would let the very "
              "string it is looking for pass from a broken document",
              [x for x in _d if x[0] == _jsn]
              == [(_jsn, "will not parse as JSON; its commands cannot be read")],
              repr(_d))
        check("s12 ...and a format with no runnable-region rule is a violation too, "
              "for the same reason: %r"
              % (M._runnable_text("NOTES.rst", M.SWEEP_RUNNER),),
              M._runnable_text("NOTES.rst", M.SWEEP_RUNNER)[0] is None
              and "no runnable-region rule"
              in M._runnable_text("NOTES.rst", M.SWEEP_RUNNER)[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # And on the real guide, which is where the prose actually lives.
    with open(os.path.join(M.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md"),
              "r", encoding="utf-8") as fh:
        _guide = fh.read()
    check("s7 the real guide writes `scripts/*.py` as prose twice and carries the "
          "recursive sweep, and is green on both counts",
          _guide.count("scripts/*.py") == 2 and M.SWEEP_RUNNER in _guide
          and M.SWEEP_FLAT not in _guide, repr(_guide.count("scripts/*.py")))

    # --- is the sweep list the WHOLE set? ---------------------------------------------
    # `sweep_glob_drift()` above judges the documents in `SWEEP_DOCS`; these judge the
    # LIST. Until this rule existed a new document teaching the retired glob was green
    # in both directions at once - unopened by the rule, and unseen by everything else.
    check("s15 no document in the tree teaches a sweep without being in SWEEP_DOCS, "
          "and no listed document has become unreachable: %r" % (M.sweep_doc_drift(),),
          M.sweep_doc_drift() == [])

    tmp = tempfile.mkdtemp()
    # The directory the fixture declares ignored, and the one a listed document lives
    # in - both READ off the constant rather than spelled, so a document moving into a
    # new directory cannot leave these cases asserting about a path nothing uses.
    _ign_dir = "scratch"
    _nested = [r for r in M.SWEEP_DOCS if "/" in r][0]
    _top = _nested.split("/")[0]
    _unlisted = "docs/onboarding.md"
    try:
        for rel in M.SWEEP_DOCS:
            _write(tmp, rel, _sweep_doc(rel, M.SWEEP_RUNNER))
        _write(tmp, ".gitignore", "# fixture\n%s/\n" % _ign_dir)
        check("s16 ...and the fixture that mirrors it is clean, so every case below "
              "fails for the reason it names rather than because the fixture was "
              "already red", M.sweep_doc_drift(tmp) == [], repr(M.sweep_doc_drift(tmp)))

        _write(tmp, _unlisted, _sweep_doc(_unlisted, M.SWEEP_RUNNER))
        _d = M.sweep_doc_drift(tmp)
        check("s17 a NEW document telling a reader to run the sweep is reported until "
              "it is listed - correct today is not the point, it is that nothing would "
              "hold it correct the day the runner is renamed",
              len(_d) == 1 and _d[0][0] == _unlisted
              and "sweep runner" in _d[0][1] and "SWEEP_DOCS" in _d[0][1], repr(_d))

        _write(tmp, _unlisted, _sweep_doc(_unlisted, M.SWEEP_FLAT))
        _d = M.sweep_doc_drift(tmp)
        check("s18 ...and the case this rule exists for: an unlisted document teaching "
              "the RETIRED glob, which sweep_glob_drift() never opens and nothing else "
              "reads a fence for. Reported under the retired shape's own word, so the "
              "finding says which loop somebody wrote",
              len(_d) == 1 and _d[0][0] == _unlisted
              and "flat sweep" in _d[0][1], repr(_d))

        _write(tmp, _unlisted, _sweep_doc(
            _unlisted, "make test",
            "The suites are swept by `%s`; never write `%s ...` yourself."
            % (M.SWEEP_RUNNER, M.SWEEP_FLAT)))
        check("s19 prose about the sweep does NOT put a document under the rule - the "
              "region scope is the same one sweep_glob_drift() uses, or half the tree "
              "would owe an entry for mentioning the command",
              M.sweep_doc_drift(tmp) == [], repr(M.sweep_doc_drift(tmp)))

        # ---- the candidate set is DERIVED, and both directions are proven ---------
        _scratch = "%s/notes.md" % _ign_dir
        _write(tmp, _scratch, _sweep_doc(_scratch, M.SWEEP_FLAT))
        check("s20 a document inside a directory `.gitignore` names is not a document "
              "of this repo: `.claude/worktrees/` holds whole checkouts, so without "
              "this the finding count would be one per recent agent rather than "
              "anything in the commit", M.sweep_doc_drift(tmp) == [],
              repr(M.sweep_doc_drift(tmp)))
        _write(tmp, ".gitignore", "# fixture\n")
        _d = M.sweep_doc_drift(tmp)
        check("s21 ...and the other direction, which is the one that proves s20 tests "
              "the derivation and not the path: drop that one line from `.gitignore` "
              "and the same file IS reported",
              [x[0] for x in _d] == [_scratch], repr(_d))

        # ---- the blind direction: the walk stops reaching a listed document -------
        _write(tmp, ".gitignore", "# fixture\n%s/\n" % _top)
        _d = M.sweep_doc_drift(tmp)
        check("s22 a listed document the walk can no longer reach is reported as BLIND, "
              "never as clean. A derivation is only as good as its pattern, and the day "
              "one prunes a directory a sweep document lives in, this rule would go "
              "quiet - which is the failure it exists to prevent",
              [x for x in _d if x[0] == _nested]
              == [(_nested, "is in SWEEP_DOCS but the walk cannot reach it, so the "
                            "scan has gone blind rather than clean")], repr(_d))

        # ---- a premise it cannot read is loud, never a fallback -------------------
        os.remove(os.path.join(tmp, ".gitignore"))
        _d = M.sweep_doc_drift(tmp)
        check("s23 with no readable `.gitignore` the rule reports THAT and stops: it "
              "cannot know which directories the repo does not keep, and answering "
              "'none of them' would be a wrong answer wearing the shape of a right one",
              len(_d) == 1 and _d[0][0] == ".gitignore"
              and "cannot be derived" in _d[0][1], repr(_d))

        def _empty_prune_drift(root):
            """The fallback s23 refuses: an unreadable `.gitignore` prunes nothing."""
            listed = set(M.SWEEP_DOCS)
            return [(rel, "unlisted") for rel in M._iter_docs(root, (), M.SWEEP_DOC_EXT)
                    if rel not in listed and M.SWEEP_FLAT
                    in M._runnable_text(rel, open(
                        os.path.join(root, rel.replace("/", os.sep)),
                        encoding="utf-8").read())[0]]

        check("s24 mutation proof for s23: the fallback reads the ignored copy as a "
              "real unlisted carrier, so the loud path is the difference between a "
              "finding about this repo and a finding about a scratch directory: %r"
              % (_empty_prune_drift(tmp),),
              [x[0] for x in _empty_prune_drift(tmp)] == [_scratch])

        # ---- gitignore's anchoring rule, on the pure function --------------------
        check("s25 a pattern with no slash matches a directory of that NAME at any "
              "depth, one with a slash is anchored to the root - collapsing the two "
              "would either prune every directory called `usage` or miss the one that "
              "matters, and both readings look right in review",
              M._is_ignored("a/b/__pycache__", (".claude/usage", "__pycache__"))
              and M._is_ignored(".claude/usage", (".claude/usage", "__pycache__"))
              and M._is_ignored(".claude/usage/x", (".claude/usage",))
              and not M._is_ignored("plugins/usage", (".claude/usage",))
              and not M._is_ignored("docs/audit", (".claude/usage", "__pycache__")))
        check("s26 the shapes that put a document under the rule are ONE table with the "
              "retired ones, reported under distinct words - the runner is in it "
              "because a correct document still has to be held correct: %r"
              % (M.SWEEP_SHAPES,),
              M.SWEEP_SHAPES[0][0] == M.SWEEP_RUNNER
              and set(M.RETIRED_SWEEPS) <= set(M.SWEEP_SHAPES)
              and len(set(lbl for _s, lbl in M.SWEEP_SHAPES)) == len(M.SWEEP_SHAPES))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- the document graph ---------------------------------------------------------
    check("dl1 every root-level document is reachable by a link and every link in the "
          "tree names a file that is there: %r" % (M.doc_link_drift(),),
          M.doc_link_drift() == [])
    check("dl2 the entry point reachability is measured FROM is a real root-level "
          "document, and nothing is both the entry point and exempt from needing a "
          "link - two tables disagreeing about one file is how an exemption outlives "
          "its reason",
          os.path.isfile(os.path.join(M.REPO_ROOT, M.DOC_ENTRY))
          and "/" not in M.DOC_ENTRY
          and M.DOC_ENTRY not in [r for r, _w in M.UNLINKED_BY_DESIGN],
          repr(M.DOC_ENTRY))
    check("dl3 every exemption carries a REASON - an entry with an empty one is a "
          "silent exclusion wearing a declaration's shape: %r"
          % ([r for r, _w in M.UNLINKED_BY_DESIGN],),
          all(isinstance(w, str) and w.strip() for _r, w in M.UNLINKED_BY_DESIGN))

    # The fixture MIRRORS the constants rather than spelling them, the same discipline
    # the sweep fixture above follows: a document added to `UNLINKED_BY_DESIGN` cannot
    # leave these cases asserting about a tree the rule no longer describes. The names
    # that are NOT in either table are deliberately not this repo's, because a real
    # filename would make a passing case ambiguous about which tree it read.
    tmp = tempfile.mkdtemp(prefix="qg-dlg-")
    _dl_other = "HANDBOOK.md"
    _dl_nested = "docs/notes/deep.md"

    def _dl_write(links):
        """The mirror tree: the exempt documents, and an entry point with `links`."""
        for _rel, _why in M.UNLINKED_BY_DESIGN:
            _write(tmp, _rel, "reached some other way\n")
        _write(tmp, ".gitignore", "# fixture\nscratch/\n")
        _write(tmp, M.DOC_ENTRY, "".join("[x](%s)\n" % t for t in links))

    try:
        _dl_write([])
        check("dl4 the mirror fixture is clean, so every case below fails for the "
              "reason it names rather than because the fixture was already red",
              M.doc_link_drift(tmp) == [], repr(M.doc_link_drift(tmp)))

        _write(tmp, _dl_other, "a new page\n")
        _d = M.doc_link_drift(tmp)
        check("dl5 a root document nothing links to is reported - the SILENT half, "
              "and the one a documentation split creates: adding a page adds a page "
              "whose discoverability rested on somebody remembering a link",
              len(_d) == 1 and _d[0][0] == _dl_other
              and "nothing links to" in _d[0][1]
              and M.DOC_ENTRY in _d[0][1], repr(_d))

        _dl_write([_dl_other])
        check("dl6 ...and linking it clears it. The other direction, which is what "
              "proves dl5 tested the LINK rather than whether the file exists",
              M.doc_link_drift(tmp) == [], repr(M.doc_link_drift(tmp)))

        _dl_write([_dl_other, "MOVED.md"])
        _d = M.doc_link_drift(tmp)
        check("dl7 a link naming a file that is not there is reported, quoting the "
              "target AS WRITTEN so the finding says what to grep for",
              len(_d) == 1 and _d[0][0] == M.DOC_ENTRY
              and "MOVED.md" in _d[0][1] and "not in the tree" in _d[0][1], repr(_d))

        # Resolution is relative to the document that WROTE the link. The plugin README
        # climbs out of its own directory to reach the root documents, so reading every
        # target as root-relative would report those as broken while missing a genuinely
        # broken sibling link - wrong in both directions at once.
        _dl_write([_dl_other, _dl_nested])
        _write(tmp, _dl_nested, "[home](../../%s)\n" % (M.DOC_ENTRY,))
        check("dl8 a target resolves against the directory of the document that wrote "
              "it, so a nested page climbing back to the entry point is not a broken "
              "link", M.doc_link_drift(tmp) == [], repr(M.doc_link_drift(tmp)))

        _write(tmp, "docs/notes/lonely.md", "nobody links me\n")
        check("dl9 a NESTED document nothing links to is NOT a finding, and the "
              "asymmetry is recorded rather than passed over: reachability is a "
              "property of the published root, and demanding an inbound link for "
              "every skill document would need a blanket exemption - which is noise "
              "wearing a rule's clothes", M.doc_link_drift(tmp) == [],
              repr(M.doc_link_drift(tmp)))

        _write(tmp, _dl_nested, "[out](../../../escape.md)\n")
        _d = M.doc_link_drift(tmp)
        check("dl10 a link resolving OUTSIDE the repository is reported as that rather "
              "than stat'd - stat'ing it would look on whatever machine ran the check, "
              "which is a finding about a laptop",
              len(_d) == 1 and _d[0][0] == _dl_nested
              and "outside the repository" in _d[0][1], repr(_d))

        _write(tmp, _dl_nested,
               "[a](https://example.invalid/x.md) [b](mailto:nobody@example.invalid) "
               "[c](#a-section)\n")
        check("dl11 another host, a `mailto:` and an in-page anchor are not claims "
              "about a file in this tree and produce nothing - a rule that reported "
              "them is one somebody switches off", M.doc_link_drift(tmp) == [],
              repr(M.doc_link_drift(tmp)))

        _dl_write([_dl_other] + [r for r, _w in M.UNLINKED_BY_DESIGN])
        _d = M.doc_link_drift(tmp)
        check("dl12 an exemption something links to after all is reported, naming who "
              "links it: a dead row here is exactly where the next real orphan hides",
              len(_d) == len(M.UNLINKED_BY_DESIGN)
              and all("outlived its reason" in p for _r, p in _d), repr(_d))

        _dl_write([_dl_other])
        for _rel, _why in M.UNLINKED_BY_DESIGN:
            os.remove(os.path.join(tmp, _rel.replace("/", os.sep)))
        _d = M.doc_link_drift(tmp)
        check("dl13 ...and an exemption that has stopped being a root document is "
              "reported too, so the table cannot excuse nothing while looking full",
              len(_d) == len(M.UNLINKED_BY_DESIGN)
              and all("excuses nothing" in p for _r, p in _d), repr(_d))

        _dl_write([_dl_other, _dl_nested])
        with open(os.path.join(tmp, _dl_nested.replace("/", os.sep)), "wb") as _fh:
            _fh.write(b"[x](\xff\xfe.md)\n")
        _d = M.doc_link_drift(tmp)
        check("dl14 a document that cannot be decoded is a NAMED finding, never a "
              "skip: 'I could not resolve this file's links' and 'this file's links "
              "are fine' are different answers, and skipping tells the second as the "
              "first", len(_d) == 1 and _d[0][0] == _dl_nested
              and "cannot be read" in _d[0][1], repr(_d))

        _write(tmp, _dl_nested, "readable again\n")
        _dl_write([_dl_other])
        os.remove(os.path.join(tmp, M.DOC_ENTRY))
        _d = M.doc_link_drift(tmp)
        check("dl15 with no entry point the rule says THAT: every other document would "
              "otherwise read as unreachable at once, which is a wrong answer wearing "
              "the shape of a right one",
              [p for r, p in _d if r == M.DOC_ENTRY and "entry point" in p] != [],
              repr(_d))

        _dl_write([_dl_other])
        os.remove(os.path.join(tmp, ".gitignore"))
        _d = M.doc_link_drift(tmp)
        check("dl16 with no readable `.gitignore` the rule reports that and stops - it "
              "cannot know which directories the repo does not keep, and walking the "
              "agent worktrees would report this repo's own documents once per "
              "checkout", len(_d) == 1 and _d[0][0] == ".gitignore"
              and "cannot be derived" in _d[0][1], repr(_d))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- published fetch instructions -----------------------------------------
    check("p1 the tree publishes no runnable fetch from a moving ref, and no stale "
          "pin in the plugin README", M.raw_url_pin_drift() == [],
          repr(M.raw_url_pin_drift()))
    with open(os.path.join(M.REPO_ROOT, "plugins", "audit", ".claude-plugin",
                           "plugin.json"), "r", encoding="utf-8") as fh:
        _pv = json.load(fh)["version"]
    check("p2 the version the currency rule compares against is READ from plugin.json, "
          "never defaulted - a guessed version would fail every pin for the wrong "
          "reason", M.plugin_version() is not None and M.plugin_version() == _pv,
          repr(M.plugin_version()))

    tmp = tempfile.mkdtemp()
    try:
        for rel in ("plugins/audit/README.md", "docs/examples/azure-pipelines.yml",
                    "plugins/audit/.claude-plugin/plugin.json",
                    "docs/audit/audit-plan.json"):
            dst = os.path.join(tmp, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(os.path.join(M.REPO_ROOT, rel.replace("/", os.sep)), dst)
        _rp = os.path.join(tmp, "plugins", "audit", "README.md")
        with open(_rp, "r", encoding="utf-8") as fh:
            _orig = fh.read()
        # READ the shipped version, never spell it. Both mutations below used to
        # name v0.39.0 and 0.40.0 as literals, so cutting 0.40.0 made p4's
        # replace() a no-op and p6's "bump" a no-op -- two cases that go GREEN by
        # measuring nothing, at the exact moment a release needs them.
        _pjr = os.path.join(tmp, "plugins", "audit", ".claude-plugin", "plugin.json")
        with open(_pjr, "r", encoding="utf-8") as fh:
            _cur = json.load(fh)["version"]
        # The candidate set is derived from `.gitignore`, so a fixture without one
        # exercises the loud path instead of the rule - p8 and p9 filter by path and
        # went green over that finding, which is exactly the shape they exist to catch.
        _write(tmp, ".gitignore", "# fixture\n")

        check("p3 ...and that fixture is green, so the cases below fail for the "
              "reason they name", M.raw_url_pin_drift(tmp) == [],
              repr(M.raw_url_pin_drift(tmp)))

        with open(_rp, "w", encoding="utf-8") as fh:
            fh.write(_orig.replace("/v%s/" % _cur, "/main/"))
        _d = M.raw_url_pin_drift(tmp)
        check("p4 a README reverted to the moving ref reports EVERY runnable fetch, "
              "not just the first", len(_d) == 3
              and all("moving ref" in r[2] for r in _d), repr(_d))
        check("p5 ...and names the line, because a file with three fetches needs the "
              "one that is wrong", all(isinstance(r[1], int) and r[1] > 0 for r in _d),
              repr(_d))
        with open(_rp, "w", encoding="utf-8") as fh:
            fh.write(_orig)

        # The release moment: plugin.json moves first, and the README must follow.
        _pj = os.path.join(tmp, "plugins", "audit", ".claude-plugin", "plugin.json")
        with open(_pj, "r", encoding="utf-8") as fh:
            _data = json.load(fh)
        _next = "99.0.0"
        _data["version"] = _next
        with open(_pj, "w", encoding="utf-8") as fh:
            json.dump(_data, fh, indent=2)
        _d = M.raw_url_pin_drift(tmp)
        check("p6 bumping plugin.json without the README turns the pin red - the rule "
              "fires at the moment it is needed", len(_d) == 3
              and all("plugin.json says %s" % _next in r[2] for r in _d), repr(_d))
        check("p7 ...and the report names both versions, since 'stale' without the "
              "pair is not actionable",
              all("v%s" % _cur in r[2] and _next in r[2] for r in _d), repr(_d))
        _data["version"] = _cur
        with open(_pj, "w", encoding="utf-8") as fh:
            json.dump(_data, fh, indent=2)

        # Two things that must STAY green. Without these the rule would "work" by
        # flagging everything, which is the failure mode a pin-checker falls into.
        check("p8 a deliberate historical pin outside the README is legal: "
              "azure-pipelines.yml names v0.5.0 on purpose and is not reported",
              [r for r in M.raw_url_pin_drift(tmp) if "azure" in r[0]] == [],
              repr(M.raw_url_pin_drift(tmp)))
        with open(os.path.join(tmp, "docs", "audit", "audit-plan.json"),
                  "r", encoding="utf-8") as fh:
            _mf = fh.read()
        check("p9 a `$schema` identity URL on `main` is NOT a fetch instruction - "
              "pinning an $id per release would break $ref resolution, so the rule "
              "must never reach it",
              "raw.githubusercontent.com" in _mf and "/main/" in _mf
              and [r for r in M.raw_url_pin_drift(tmp)
                   if r[0].endswith(".json")] == [], repr(_mf[:80]))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The boundary that makes the whole rule usable: PROSE IS NOT AN INSTRUCTION.
    # CHANGELOG.md quotes the dead `main` URL as history and must keep doing so. The
    # fence scope is what allows that - there is no CHANGELOG exemption, and this case
    # is what proves one would be dead code rather than a safety net.
    with open(os.path.join(M.REPO_ROOT, "CHANGELOG.md"), "r", encoding="utf-8") as fh:
        _ch = fh.read()
    check("p10 the CHANGELOG really does quote a `main` raw URL, so this case is not "
          "vacuous", len(re.findall(M._RAW_RE, _ch)) >= 1,
          repr(len(re.findall(M._RAW_RE, _ch))))
    check("p11 ...and it is reported by nothing, because it sits in prose rather than "
          "in a runnable fence - the scope, not an exemption, is what spares it",
          M._executable_raw_refs(_ch) == []
          and [r for r in M.raw_url_pin_drift() if r[0] == "CHANGELOG.md"] == [],
          repr(M._executable_raw_refs(_ch)))
    check("p12 a fenced URL in the SAME text is caught, which is what tells p11 apart "
          "from a scanner that simply never looks at this file",
          M._executable_raw_refs(
              "```bash\ncurl https://raw.githubusercontent.com/o/r/main/x\n```") != [],
          "the fence scope must be able to fire here")


    # --- the candidate set this rule walks ------------------------------------
    # It pruned four directory names by hand, and a hand list is the thing that rots:
    # it reached whatever the browser tool had last left in the tree - so the set moved
    # with what had recently run on the machine rather than with the commit - and it
    # pruned `.claude/` wholesale, which held the tracked skills out of a rule that is
    # exactly about a document publishing a fetch. Both wrong at once, in one list.
    # Read off the rule's OWN accessor, not off `_iter_docs` with the arguments the
    # rule is believed to pass: the second form passed with the hand list restored,
    # because it was testing the helper rather than what the rule hands it.
    _pats, _ = M._ignored_dirs(M.REPO_ROOT)
    _fdocs, _pat_problem = M._fetch_docs(M.REPO_ROOT)
    _ignored_hits = [r for r in _fdocs
                     if "/" in r and M._is_ignored(r.rsplit("/", 1)[0], _pats)]
    check("p13 the rule walks the documents this repo KEEPS: no candidate sits inside "
          "a directory `.gitignore` names, and the tracked documents under `.claude/` "
          "are judged rather than pruned by name",
          _pat_problem is None and _ignored_hits == []
          and [r for r in _fdocs if r.startswith(".claude/")] != [],
          repr(_ignored_hits[:4]))

    # p9 asserts no JSON is REPORTED, which a rule that reads every JSON in the tree
    # also satisfies - the identity URLs it must not touch sit in files carrying no
    # Markdown fence, so nothing separates the two. This is the case that does: the
    # format set is an argument, and the first version of the shared walk took it and
    # then judged by the sweep's. Green suites either way, because no candidate the
    # extra formats added carries a fence today.
    check("p19 the rule's formats are the ones it was handed: a schema identity is not "
          "reachable at all, rather than reachable and quiet - which is what p9 needs "
          "to be about the scope instead of about today's file contents",
          [r for r in _fdocs if not r.endswith(M._FETCH_DOC_EXT)] == []
          and [r for r in _fdocs if r.endswith(".json")] == [],
          repr([r for r in _fdocs if not r.endswith(M._FETCH_DOC_EXT)][:4]))

    tmp = tempfile.mkdtemp()
    # Built, never spelled: the host lives in the module and a literal here would be a
    # second copy of it, in a file the same rule reads.
    _ign_dir = "scratch"
    _scratch = "%s/notes.md" % _ign_dir
    _fetch_md = ("```bash\ncurl -O https://%s/o/r/main/x.json\n```\n" % M._RAW_HOST)
    try:
        _write(tmp, ".gitignore", "# fixture\n%s/\n" % _ign_dir)
        _write(tmp, _scratch, _fetch_md)
        # The currency arm reads this, and reading it is not optional: a root without
        # one raises rather than reporting, which is a boundary worth meeting here
        # rather than in whatever consumer tree hits it first.
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": "0.0.0"}) + "\n")
        check("p14 a runnable fetch inside a directory `.gitignore` names is not "
              "something this repo published: the walk that reached one read scratch "
              "output as an instruction a reader could copy",
              M.raw_url_pin_drift(tmp) == [], repr(M.raw_url_pin_drift(tmp)))

        _write(tmp, ".gitignore", "# fixture\n")
        _d = M.raw_url_pin_drift(tmp)
        check("p15 ...and the direction that proves p14 tests the derivation rather "
              "than the path: drop that one line and the same file IS reported",
              [(r[0], "moving ref" in r[2]) for r in _d] == [(_scratch, True)],
              repr(_d))

        os.remove(os.path.join(tmp, ".gitignore"))
        _d = M.raw_url_pin_drift(tmp)
        check("p16 with no readable `.gitignore` the rule reports THAT and stops - "
              "answering 'nothing is ignored' would scan the ignored copies and call "
              "what they carry published",
              len(_d) == 1 and _d[0][0] == ".gitignore"
              and "cannot be derived" in _d[0][2], repr(_d))

        def _no_prune_drift(root):
            """The fallback p16 refuses: an unreadable `.gitignore` prunes nothing."""
            out = []
            for rel in M._iter_docs(root, (), M._FETCH_DOC_EXT):
                with open(os.path.join(root, rel.replace("/", os.sep)),
                          "r", encoding="utf-8") as fh:
                    text = fh.read()
                out += [(rel, ref) for ref, _ln in M._executable_raw_refs(text)
                        if ref in M._MOVING_REFS]
            return out

        check("p17 mutation proof for p16: that fallback reports the ignored copy as a "
              "published fetch - a finding about a scratch directory wearing the shape "
              "of a finding about this repo: %r" % (_no_prune_drift(tmp),),
              [r[0] for r in _no_prune_drift(tmp)] == [_scratch])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Looks vacuous, and is the only case that fails the other mutation. `EXCLUDED` is
    # the table that pairs with `SURFACES` (t2), and this walk once carried a filter
    # against it that could not fire - a path string tested against (path, reason)
    # pairs. Deleting it changed nothing, and this is what says so: the documents that
    # table names are CANDIDATES here, spared by the fence scope (p10-p12) and not by
    # an exemption. Make the filter work and p11 goes green for the wrong reason.
    check("p18 the documents `EXCLUDED` names are read by this rule rather than held "
          "out of it - prose is what spares them, which is what keeps p11 measured "
          "instead of assumed",
          "CHANGELOG.md" in _fdocs
          and [r for r in _fdocs if r.startswith("docs/design/")] != [],
          repr([r for r in _fdocs
                if r == "CHANGELOG.md" or r.startswith("docs/design/")]))

    # --- F12: the version a committed artifact stamps -------------------------
    # The defect: the scale demo under `docs/` is published and linked from the
    # README, and it served a stamp several releases behind the plugin while every
    # check over it stayed green - they asserted CONTENT (no invalid-manifest
    # banner, a usage section present), which is true of a report rendered by any
    # version, for ever.
    _av = M.artifact_version_drift()
    check("av1 every committed page stamps the release plugin.json names - the live "
          "claim, and the one that goes red on the day a bump is not followed by a "
          "re-render: %r" % (_av,), _av == [])

    _pages, _pprob = M._stamp_pages(M.REPO_ROOT)
    _seen = []
    for _rel in (_pages or []):
        with open(os.path.join(M.REPO_ROOT, _rel.replace("/", os.sep)),
                  "r", encoding="utf-8") as fh:
            _seen += [(_rel, _v) for _v, _ln in M._artifact_stamps(fh.read())]
    check("av2 ...and it cleared real pages rather than an empty set - av1 returns "
          "[] over a walk that reaches nothing too, and this is what tells the two "
          "apart: the published reports are all in the candidate set, each carries "
          "exactly ONE stamp, and every stamp is the version read straight out of "
          "plugin.json: %r" % (_seen,),
          _pprob is None and len(_seen) >= 3
          and len(set(_r for _r, _v in _seen)) == len(_seen)
          and set(_v for _r, _v in _seen) == set([_pv]))

    _tmpl = _FX_SCRIPTS + "ui/panel.html"
    check("av3 the panel TEMPLATE is READ and stamps nothing, and that is not a "
          "finding: this rule is about a claim that is wrong, not about a page that "
          "makes none. Looks vacuous and is the only case that fails the other "
          "mutation - a rule demanding a stamp per page would report the template "
          "for ever",
          _tmpl in (_pages or []) and [_r for _r, _v in _seen if _r == _tmpl] == [])

    _two = M._artifact_stamps(
        '<span class="stampv" title="t">audit 1.2.3</span>\n'
        '<span class="stampv" title="t">audit 4.5.6</span>\n')
    check("av4 a page carrying two stamps contributes BOTH, with the line each sits "
          "on - a base template and an override each emitting one is the generated-"
          "output failure a presence test cannot see: %r" % (_two,),
          _two == [("1.2.3", 1), ("4.5.6", 2)])

    tmp = tempfile.mkdtemp()
    # Built from the module's own extension set, so a rule that stops reading this
    # format cannot leave a fixture behind that silently tests nothing.
    _av_page = "docs/demo" + M.STAMP_EXT[0]
    _av_ignored = "scratch"
    _av_scratch = _av_ignored + "/old" + M.STAMP_EXT[0]
    _av_html = ('<p class="meta">generated · <span class="stampv" '
                'title="The plugin version that rendered this file">audit '
                '%s</span></p>\n')
    try:
        _write(tmp, ".gitignore", "# fixture\n%s/\n" % _av_ignored)
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": _pv}) + "\n")
        _write(tmp, _av_page, _av_html % _pv)
        check("av5 a fixture whose page stamps the version plugin.json names is "
              "green, so every case below fails for the reason it names: %r"
              % (M.artifact_version_drift(tmp),),
              M.artifact_version_drift(tmp) == [])

        # A version the fixture's plugin.json cannot be mistaken for, so the buggy
        # and fixed comparisons disagree about it: a rule that compared a page with
        # itself, or that read the version off the page, is green here.
        _stale = "0.0.1"
        _write(tmp, _av_page, _av_html % _stale)
        _d = M.artifact_version_drift(tmp)
        check("av6 a page a release left behind IS reported - by path, by line, and "
              "with BOTH versions in the message, because 'stale' without the pair "
              "is not something a reader can act on: %r" % (_d,),
              len(_d) == 1 and _d[0][0] == _av_page and _d[0][1] > 0
              and _stale in _d[0][2] and _pv in _d[0][2])

        # The shape F12 actually took: plugin.json moves first.
        _next = "99.0.0"
        _write(tmp, _av_page, _av_html % _pv)
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": _next}) + "\n")
        _d = M.artifact_version_drift(tmp)
        check("av7 bumping plugin.json without re-rendering the published page turns "
              "it red at the moment the gate is needed, which is the release rather "
              "than whenever somebody next looks: %r" % (_d,),
              len(_d) == 1 and _pv in _d[0][2] and _next in _d[0][2])
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": _pv}) + "\n")

        _write(tmp, _av_page, "<p>a page that claims nothing about its version</p>\n")
        _d = M.artifact_version_drift(tmp)
        check("av8 a tree where NOTHING is stamped is reported as exactly that: a "
              "candidate set that narrowed to nothing must not be spelled the same "
              "way as a tree that is current, and that is the shape a renamed stamp "
              "or a walk that stopped reaching the reports takes: %r" % (_d,),
              len(_d) == 1 and _d[0][0] == "*" + M.STAMP_EXT[0]
              and "cleared nothing" in _d[0][2])

        _write(tmp, _av_page, _av_html % _pv)
        _write(tmp, _av_scratch, _av_html % _stale)
        check("av9 a page inside a directory `.gitignore` names is not something "
              "this repo published - a walk that reached one would read whatever a "
              "scratch render left behind as a live claim: %r"
              % (M.artifact_version_drift(tmp),),
              M.artifact_version_drift(tmp) == [])

        # av10-av12: the FILE half of the format, which the directory half cannot
        # reach. `av9` covers a page inside an ignored DIRECTORY; this is a page
        # ignored BY NAME - what `docs/audit/audit-report.html` is in the real tree.
        # Gitignored, untracked, on no branch, and reported as a stale published page
        # on any machine that had ever rendered one.
        _av_named = "kept/generated-report.html"
        _write(tmp, ".gitignore",
               "# fixture\n%s/\n%s\n" % (_av_ignored, _av_named))
        _write(tmp, _av_page, _av_html % _pv)
        _write(tmp, _av_named, _av_html % _stale)
        check("av14 a page `.gitignore` names BY FILE is not published either - this "
              "rule's own first line says COMMITTED, and its finding would otherwise "
              "depend on what somebody last rendered on this machine rather than on "
              "anything in the commit: %r" % (M.artifact_version_drift(tmp),),
              M.artifact_version_drift(tmp) == [])
        # The direction that would vanish. Dropping ignored files is a NARROWING, so
        # its failure mode is silence - and silence here reads exactly like a tree
        # that is current, which is the defect av8 exists for.
        _write(tmp, _av_page, _av_html % _stale)
        _d = M.artifact_version_drift(tmp)
        check("av15 ...and a page that is NOT ignored is still reported when its "
              "stamp is stale - the narrowing must cost the ignored file and nothing "
              "else: %r" % (_d,),
              len(_d) == 1 and _d[0][0] == _av_page and _stale in _d[0][2])
        _write(tmp, _av_page, _av_html % _pv)
        # And the reader itself, both halves: one line must not be read as both, or a
        # rule taking both would prune a path twice for two different reasons.
        _dirs, _dprob = M._output._ignored_dirs(tmp)
        _files, _fprob = M._output._ignored_files(tmp)
        check("av16 a trailing slash decides which half reads a line - `%s/` "
              "is a directory pattern and not a file one, `%s` is a file pattern "
              "and not a directory one: %r / %r"
              % (_av_ignored, _av_named, _dirs, _files),
              _dprob is None and _fprob is None
              and _av_ignored in _dirs and _av_named not in _dirs
              and _av_named in _files and _av_ignored not in _files)
        # Put the fixture back the way the cases below expect to find it. This block
        # both wrote a file and rewrote `.gitignore`, and the next case DROPS the
        # ignore line on purpose - so a leftover here would be reported by it and
        # read as that case failing, which is a defect in this file rather than in
        # the rule either case is about.
        os.remove(os.path.join(tmp, _av_named.replace("/", os.sep)))
        _write(tmp, ".gitignore", "# fixture\n%s/\n" % _av_ignored)

        _write(tmp, ".gitignore", "# fixture\n")
        _d = M.artifact_version_drift(tmp)
        check("av10 ...and the direction that proves av9 tests the derivation rather "
              "than the path: drop that one line and the same file IS reported: %r"
              % (_d,), [_r[0] for _r in _d] == [_av_scratch])

        os.remove(os.path.join(tmp, ".gitignore"))
        _d = M.artifact_version_drift(tmp)
        check("av11 with no readable `.gitignore` the rule reports THAT and stops - "
              "answering 'nothing is ignored' would publish a scratch render's "
              "claim on this repo's behalf: %r" % (_d,),
              len(_d) == 1 and _d[0][0] == ".gitignore"
              and "cannot be derived" in _d[0][2])

        # Undecodable rather than unreadable: a permission bit does not mean the same
        # thing on both platforms CI runs, and bytes that are not UTF-8 do.
        _write(tmp, ".gitignore", "# fixture\n")
        os.remove(os.path.join(tmp, _av_scratch.replace("/", os.sep)))
        _bad = "docs/bad" + M.STAMP_EXT[0]
        with open(os.path.join(tmp, _bad.replace("/", os.sep)), "wb") as fh:
            fh.write(b"\xff\xfe not utf-8 at all \xff")
        _d = M.artifact_version_drift(tmp)
        check("av12 a page that cannot be decoded is REPORTED, never counted as one "
              "that stamps nothing: 'I could not read this claim' and 'this page "
              "makes none' are different answers, and the second spares the file: %r"
              % (_d,),
              [(_r[0], "unreadable" in _r[2]) for _r in _d] == [(_bad, True)])
        os.remove(os.path.join(tmp, _bad.replace("/", os.sep)))

        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"name": "audit"}) + "\n")
        _d = M.artifact_version_drift(tmp)
        check("av13 a plugin.json with no readable version is reported, never "
              "defaulted - the comparison has no basis, and a guessed version would "
              "fail every page for the wrong reason: %r" % (_d,),
              len(_d) == 1 and _d[0][0] == M._PLUGIN_JSON_REL
              and "no readable version" in _d[0][2])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


    # --- screenshot_capture_drift: the same question, asked of a PICTURE -------
    # The claim cannot be read back out of the pixels - `capture-screenshots.mjs`
    # refuses to compare them, and F18 records why - so it is recorded beside them
    # and this is what compares it.
    _sc = M.screenshot_capture_drift()
    check("sc1 every committed screenshot records the build plugin.json names - the "
          "live claim, and the one that goes red the day a bump is not followed by "
          "a re-capture: %r" % (_sc,), _sc == [])

    _sc_dir = os.path.join(M.REPO_ROOT, M.SHOT_DIR_REL.replace("/", os.sep))
    _sc_pngs = sorted(n for n in os.listdir(_sc_dir) if n.endswith(".png"))
    with open(os.path.join(M.REPO_ROOT, M._CAPTURED_AT.replace("/", os.sep)),
              "r", encoding="utf-8") as fh:
        _sc_rec = json.load(fh)["images"]
    _sc_live_ui = _output.ui_surface_digests()
    check("sc2 ...and it cleared a real set rather than an empty one - sc1 returns "
          "[] over a directory it never reached too, and telling those two apart is "
          "the whole point of the rule: every committed .png has an entry, every "
          "entry names a committed .png, every recorded version is the one "
          "plugin.json carries, and every entry names a surface this tree "
          "assembles and carries THAT surface's live source digest: %r"
          % (len(_sc_pngs),),
          len(_sc_pngs) > 5 and sorted(_sc_rec) == _sc_pngs
          and set(v.get("version") for v in _sc_rec.values()) == set([_pv])
          and set(v.get("surface") for v in _sc_rec.values())
              == set(_output.UI_SURFACES)
          and [n for n, v in sorted(_sc_rec.items())
               if v.get("uiDigest")
               != _sc_live_ui["digests"].get(v.get("surface"))] == [])

    tmp = tempfile.mkdtemp()
    _sc_a = M.SHOT_DIR_REL + "/one.png"
    _sc_b = M.SHOT_DIR_REL + "/two.png"
    try:
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": _pv}) + "\n")
        _write(tmp, _sc_a, "PIXELS-ONE\n")
        _write(tmp, _sc_b, "PIXELS-TWO\n")
        # The UI the fixture's pictures are OF. Both surfaces need a part of their
        # own or the walk reports a surface that is gone, so this is the smallest
        # tree the rule can actually clear - and `one.png` is a panel picture while
        # `two.png` is a report one, which is what makes the separation cases below
        # able to say anything.
        _sc_ui_dir = M._UI_DIR_REL
        _sc_panel_src = _sc_ui_dir + "/panel/core.js"
        _sc_report_src = _sc_ui_dir + "/report/filters.js"
        _sc_shared_src = _sc_ui_dir + "/shared/dates.js"
        _sc_token = M._UI_SCRIPTS_REL + "/_ui_theme.py"
        _write(tmp, _sc_ui_dir + "/panel.html", "<!doctype html>\n")
        _write(tmp, _sc_panel_src, "const el = 1;\n")
        _write(tmp, _sc_ui_dir + "/panel-css/app-shell.css", ".shell{}\n")
        _write(tmp, _sc_report_src, "const chips = 1;\n")
        _write(tmp, _sc_ui_dir + "/report-css/shell.css", ".rshell{}\n")
        _write(tmp, _sc_shared_src, "const DAY = 1;\n")
        _write(tmp, _sc_token, "TOKEN_CSS = ':root{--bg:#fff}'\n")

        def _sc_ui_now():
            """The digests a capture running against this fixture would record."""
            return _output.ui_surface_digests(
                os.path.join(tmp, *M._UI_SCRIPTS_REL.split("/")))["digests"]

        def _sc_entries(surfaces=None, digests=None):
            """The sidecar a clean capture of this fixture would leave behind."""
            faces = surfaces if surfaces is not None else {"one.png": "panel",
                                                           "two.png": "report"}
            marks = digests if digests is not None else _sc_ui_now()
            out = {}
            for name, rel in (("one.png", _sc_a), ("two.png", _sc_b)):
                entry = {"sha256": _sc_digest(tmp, rel), "version": _pv}
                if faces.get(name) is not None:
                    entry["surface"] = faces[name]
                if marks.get(faces.get(name)) is not None:
                    entry["uiDigest"] = marks[faces[name]]
                out[name] = entry
            return out

        _sc_ok = _sc_entries()
        _sc_sidecar(tmp, _sc_ok)
        check("sc3 a fixture whose sidecar agrees with the BYTES, the VERSION and "
              "the SOURCE DIGEST of the surface each picture is of is green, so "
              "every case below fails for the reason it names: %r"
              % (M.screenshot_capture_drift(tmp),),
              M.screenshot_capture_drift(tmp) == [])

        os.remove(os.path.join(tmp, M._CAPTURED_AT.replace("/", os.sep)))
        _sc_none = M.screenshot_capture_drift(tmp)
        check("sc4 no sidecar is a FINDING, not silence - the pictures still make a "
              "claim and nothing can settle it, which is the state this rule exists "
              "to end: %r" % (_sc_none,),
              len(_sc_none) == 1 and _sc_none[0][0] == M._CAPTURED_AT
              and "missing or unreadable" in _sc_none[0][2])

        # A version this fixture's plugin.json cannot be mistaken for, so a rule
        # that compared the sidecar with itself is green here.
        _sc_stale = dict(_sc_ok)
        _sc_stale["one.png"] = {"sha256": _sc_ok["one.png"]["sha256"],
                                "version": "0.0.1"}
        _sc_sidecar(tmp, _sc_stale)
        _sc_old = M.screenshot_capture_drift(tmp)
        check("sc5 a recorded version that is not the current one is named WITH the "
              "pair - 'stale' without both halves is not something a reader can act "
              "on: %r" % (_sc_old,),
              len(_sc_old) == 1 and _sc_old[0][0] == M.SHOT_DIR_REL + "/one.png"
              and "0.0.1" in _sc_old[0][2] and _pv in _sc_old[0][2])

        # The two branches must not be spelled the same way: here the VERSION is
        # right and the bytes are not, which is a re-capture that never finished.
        _sc_sidecar(tmp, _sc_ok)
        _write(tmp, _sc_a, "PIXELS-ONE-BUT-DIFFERENT\n")
        _sc_moved = M.screenshot_capture_drift(tmp)
        check("sc6 bytes that changed since the record was written are reported as "
              "CHANGED, not as a version mismatch - the recorded version is then "
              "about different pixels, and saying 'stale build' would send the "
              "reader to the wrong repair: %r" % (_sc_moved,),
              len(_sc_moved) == 1 and "has changed since" in _sc_moved[0][2]
              and "plugin.json says" not in _sc_moved[0][2])

        _write(tmp, _sc_a, "PIXELS-ONE\n")
        _sc_sidecar(tmp, {"one.png": _sc_ok["one.png"]})
        _sc_extra = M.screenshot_capture_drift(tmp)
        check("sc7 an image the sidecar does not mention is named - adding a "
              "screenshot without re-capturing leaves it claiming a build nothing "
              "wrote down: %r" % (_sc_extra,),
              len(_sc_extra) == 1 and _sc_extra[0][0] == M.SHOT_DIR_REL + "/two.png"
              and "unrecorded" in _sc_extra[0][2])

        _sc_ghost = dict(_sc_ok)
        _sc_ghost["gone.png"] = {"sha256": "0" * 64, "version": _pv}
        _sc_sidecar(tmp, _sc_ghost)
        _sc_orphan = M.screenshot_capture_drift(tmp)
        check("sc8 an entry whose picture is gone is named too - a record about "
              "nothing is how a deleted shot keeps being vouched for: %r"
              % (_sc_orphan,),
              len(_sc_orphan) == 1 and _sc_orphan[0][0] == M._CAPTURED_AT
              and "gone.png" in _sc_orphan[0][2])

        _sc_sidecar(tmp, _sc_ok)
        os.remove(os.path.join(tmp, _sc_a.replace("/", os.sep)))
        os.remove(os.path.join(tmp, _sc_b.replace("/", os.sep)))
        _sc_empty = M.screenshot_capture_drift(tmp)
        check("sc9 a directory with no .png at all is a FINDING - a candidate set "
              "that narrowed to nothing must not be spelled the same way as a set "
              "that all agrees, which is the shape a moved output directory takes: "
              "%r" % (_sc_empty,),
              len(_sc_empty) == 1 and _sc_empty[0][0] == M.SHOT_DIR_REL
              and "holds no .png" in _sc_empty[0][2])

        _write(tmp, _sc_a, "PIXELS-ONE\n")
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"name": "x"}) + "\n")
        _sc_nover = M.screenshot_capture_drift(tmp)
        check("sc10 a plugin.json with no readable version is reported instead of "
              "failing every image for the wrong reason - the comparison has no "
              "basis, and a guessed one would be worse than none: %r" % (_sc_nover,),
              len(_sc_nover) == 1 and _sc_nover[0][0] == M._PLUGIN_JSON_REL
              and "no readable version" in _sc_nover[0][2])

        # --- sc11-sc19 (F85): the picture against the UI it is a picture OF ----
        # The version answers "captured at this release". It cannot answer "still
        # shows this UI", and it did not: commits landed under `scripts/ui/` after
        # the last re-capture and this rule stayed green over stale pixels. Every
        # case below leaves the VERSION agreeing, so nothing here can pass for the
        # older reason.
        _write(tmp, M._PLUGIN_JSON_REL, json.dumps({"version": _pv}) + "\n")
        _write(tmp, _sc_b, "PIXELS-TWO\n")
        _sc_sidecar(tmp, _sc_entries())

        def _sc_named(findings, rel):
            """The findings about one image, by path."""
            return [f for f in findings if f[0] == rel]

        # THE SEPARATION, BOTH DIRECTIONS IN TWO CASES. A digest that fired on
        # everything would ask for every picture back on every commit and would be
        # switched off, so the negative half of each is the load-bearing half.
        _write(tmp, _sc_panel_src, "const el = 2;\n")
        _sc_pan = M.screenshot_capture_drift(tmp)
        _write(tmp, _sc_panel_src, "const el = 1;\n")
        check("sc11 a changed PANEL source reddens the panel picture and NOT the "
              "report one, naming the surface and both digests - this is F85's own "
              "shape, and the version still agrees throughout: %r" % (_sc_pan,),
              len(_sc_pan) == 1 and _sc_pan[0][0] == _sc_a
              and "panel sources" in _sc_pan[0][2]
              and "nobody re-shot" in _sc_pan[0][2]
              and _sc_named(_sc_pan, _sc_b) == [])

        _write(tmp, _sc_report_src, "const chips = 2;\n")
        _sc_rep = M.screenshot_capture_drift(tmp)
        _write(tmp, _sc_report_src, "const chips = 1;\n")
        check("sc12 ...and a changed REPORT source reddens the report picture and "
              "NOT the panel one. Both directions, because one of them alone is "
              "also what a rule that reddens everything prints: %r" % (_sc_rep,),
              len(_sc_rep) == 1 and _sc_rep[0][0] == _sc_b
              and "report sources" in _sc_rep[0][2]
              and _sc_named(_sc_rep, _sc_a) == [])

        _write(tmp, _sc_shared_src, "const DAY = 2;\n")
        _sc_both = M.screenshot_capture_drift(tmp)
        _write(tmp, _sc_shared_src, "const DAY = 1;\n")
        check("sc13 a changed `shared/` part reddens BOTH, because both assemblies "
              "ship it - the one place where firing on everything is the right "
              "answer, and the case that fails if `shared/` is quietly filed under "
              "one surface: %r" % (_sc_both,),
              len(_sc_both) == 2 and len(_sc_named(_sc_both, _sc_a)) == 1
              and len(_sc_named(_sc_both, _sc_b)) == 1)

        _write(tmp, _sc_token, "TOKEN_CSS = ':root{--bg:#000}'\n")
        _sc_tok = M.screenshot_capture_drift(tmp)
        _write(tmp, _sc_token, "TOKEN_CSS = ':root{--bg:#fff}'\n")
        check("sc14 a changed TOKEN LAYER reddens both, though it is a `.py` "
              "outside `ui/` - a palette edit moves every pixel and a walk over "
              "`ui/` alone would sleep through the change most likely to matter: "
              "%r" % (_sc_tok,),
              len(_sc_tok) == 2 and len(_sc_named(_sc_tok, _sc_a)) == 1
              and len(_sc_named(_sc_tok, _sc_b)) == 1)

        _sc_nodig = _sc_entries()
        del _sc_nodig["one.png"]["uiDigest"]
        _sc_sidecar(tmp, _sc_nodig)
        _sc_missing = M.screenshot_capture_drift(tmp)
        check("sc15 an entry with NO source digest is a finding, not silence - "
              "absence is not agreement, and this is why the rule is red until a "
              "capture has written one rather than defaulting into a pass: %r"
              % (_sc_missing,),
              len(_sc_missing) == 1 and _sc_missing[0][0] == _sc_a
              and "records no UI source digest" in _sc_missing[0][2])

        _sc_wrongface = _sc_entries()
        _sc_wrongface["one.png"]["surface"] = "nowhere"
        _sc_sidecar(tmp, _sc_wrongface)
        _sc_face = M.screenshot_capture_drift(tmp)
        check("sc16 an entry naming a surface this tree does not assemble is "
              "reported rather than compared - a digest with nothing to compare it "
              "to must not be spelled the same way as one that matches: %r"
              % (_sc_face,),
              len(_sc_face) == 1 and _sc_face[0][0] == _sc_a
              and "'nowhere'" in _sc_face[0][2]
              and "stands for nothing" in _sc_face[0][2])

        _sc_sidecar(tmp, _sc_entries())
        _write(tmp, _sc_ui_dir + "/widgets/thing.js", "const w = 1;\n")
        _sc_unplaced = M.screenshot_capture_drift(tmp)
        os.remove(os.path.join(tmp, (_sc_ui_dir + "/widgets/thing.js")
                                    .replace("/", os.sep)))
        check("sc17 a `ui/` part under a directory no surface claims is named - it "
              "is covered by no picture's digest, so changing it could never turn "
              "one red, which is the silence this rule exists to end: %r"
              % (_sc_unplaced,),
              len(_sc_unplaced) == 1
              and _sc_unplaced[0][0] == _sc_ui_dir + "/widgets/thing.js"
              and "no surface this tree assembles" in _sc_unplaced[0][2])

        # THE SECOND-DIRECTION CASE, and it looks vacuous on purpose: it passes on
        # a rule that never fires. It is the only one that fails if the comparison
        # becomes unconditional - a rule permanently red once any source has ever
        # moved is a rule people delete.
        _write(tmp, _sc_panel_src, "const el = 3;\n")
        _sc_sidecar(tmp, _sc_entries())
        _sc_recaptured = M.screenshot_capture_drift(tmp)
        check("sc18 a source that changed and was then RE-RECORDED, exactly as a "
              "re-capture records it, reports nothing again: %r"
              % (_sc_recaptured,), _sc_recaptured == [])

        shutil.rmtree(os.path.join(tmp, *(_sc_ui_dir.split("/"))))
        _sc_nosrc = M.screenshot_capture_drift(tmp)
        check("sc19 UI sources that cannot be walked are ONE finding and the rule "
              "stops - every image would otherwise be reported for want of a "
              "comparison rather than because it disagrees, which is a red run "
              "pointing at the wrong repair: %r" % (_sc_nosrc,),
              len(_sc_nosrc) == 1 and _sc_nosrc[0][0] == _sc_ui_dir
              and "unknown rather than unchanged" in _sc_nosrc[0][2])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # A value that has to exist in two languages, pinned rather than commented.
    # The capture writes a LEG name into each entry and this rule looks it up among
    # the SURFACES; a leg whose name is not a surface would put sc16's finding on
    # every picture it took, and a surface no leg is named after would never be
    # photographed at all. Both directions, from one comparison.
    _sc_legs = re.search(r"const LEGS = \[([^\]]*)\]", _mjs)
    _sc_leg_names = sorted(re.findall(r"'([^']+)'", _sc_legs.group(1))
                           ) if _sc_legs else []
    check("sc20 the capture's legs and the surfaces this rule knows are the same "
          "names - the claim is about two files in two languages, so it is tested "
          "rather than written in a comment: %r"
          % ((_sc_leg_names, sorted(_output.UI_SURFACES)),),
          _sc_leg_names == sorted(_output.UI_SURFACES))

    # --- F36: a command's flags vs the README row that catalogues them ---------
    # The defect this exists for was live when it was written: /audit:status had
    # grown --gate and --fail-on while its README row said "-", and /audit:doctor
    # had grown --deep while its row still said [--json]. A capability nobody can
    # find is the thing this repo keeps meeting.
    # --- F191: the operator's own words, and the doc that has to say so -------
    # The journal is tamper-evident and works on whatever sentence it is given, so
    # a paraphrased reason makes the chain guarantee something its subject never
    # wrote. Measured live: "Tracked in ADO only, not executed here" was recorded
    # as "tracked on the board only; this work is not executed through the audit
    # pipeline" - longer, smoother, and a claim about this plugin's role the
    # operator never made.
    #
    # The RULE lives once, in `reference/manifest-conventions.md`; the command docs
    # carry a pointer. This asserts both halves, because a pointer at a heading
    # nobody kept is a pointer at nothing and every doc would still pass.
    _vrd = M.verbatim_rule_drift()
    check("vb1 every command doc that asks a human for text bound for the journal "
          "says it goes in UNCHANGED - the flag is the needle, not a doc list, so "
          "a new command that gathers a reason is covered the day it is written: "
          "%r" % (_vrd,),
          not _vrd["missing"] and _vrd["checked"] >= 4)
    check("vb2 ...and the section the pointers name still exists - the other half, "
          "since a pointer at a renamed heading reads as compliance while naming "
          "nothing: %r" % (_vrd["ruleDoc"],),
          _vrd["ruleDoc"] is True)
    # THE NEEDLE MUST REACH THE FOURTH DOC, and a flag-only one did not: `bug
    # close` records "a one-line `notes` justification" and names no flag, so the
    # census read three docs and treated the fourth as having nothing to discharge.
    # A MENTION IS NOT A STATEMENT, and this is the case that says so. The needle
    # started as the bare words and `commands/task.md` then grew an ordinary
    # cross-reference in prose - useful writing, not a rule being stated - which
    # alone discharged the check: deleting the real directive left the file
    # passing, and the mutation harness is what found it. Counted against the
    # DIRECTIVE, so a doc that only points at the rule elsewhere still owes it.
    check("vb4 the pointer is the BOLDED directive, so a doc that merely mentions "
          "the rule in prose has not stated it - the count-do-not-merely-find "
          "trap, caught here by a mutation rather than by reading: %r"
          % (M.VERBATIM_POINTER,),
          M.VERBATIM_POINTER.startswith("**")
          and M.VERBATIM_POINTER.endswith("**")
          and "words go in VERBATIM" in M.VERBATIM_POINTER)

    check("vb3 the census reaches a doc that gathers the text WITHOUT naming a "
          "flag - counted, because a needle that quietly covered three of four "
          "would report a clean sheet over the one it could not see: %r"
          % (sorted(M.VERBATIM_FLAGS),),
          "justification" in M.VERBATIM_FLAGS and len(M.VERBATIM_FLAGS) >= 2)

    _cfd = M.command_flag_drift()
    check("cf1 the README's command table names every flag its commands declare "
          "- %d command(s) with an argument-hint and a row, missing %r"
          % (_cfd["checked"], _cfd["missing"]),
          _cfd["checked"] >= 12 and _cfd["missing"] == [])
    # The vacuity guard, and it is not decoration: `missing == []` is also what a
    # scan that read no commands returns, which is exactly how this check would
    # rot into an always-green line.
    check("cf2 ...and it read the commands rather than finding nothing to read - "
          "a scan over an empty set reports no drift too",
          M.command_flag_drift()["checked"] > 0)
    # A SUBSET, never equality. The two are written for different readers: the
    # README column carries prose and escaped pipes that no frontmatter string
    # would, so demanding they match would fail on the difference that is the
    # point of having both.
    _tmp_ref = tempfile.mkdtemp(prefix="qg-cfd-")
    try:
        os.makedirs(os.path.join(_tmp_ref, "plugins", "audit", "commands"))
        with open(os.path.join(_tmp_ref, "plugins", "audit", "README.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("| Command | Arguments | What |\n|---|---|---|\n"
                     "| `/audit:demo` | `push [a\\|b] [--task <id>] \\| pull` | x |\n")
        with open(os.path.join(_tmp_ref, "plugins", "audit", "commands", "demo.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("---\nargument-hint: 'push [a|b] [--task <id>] | pull'\n---\n")
        _d = M.command_flag_drift(_tmp_ref)
        check("cf3 an escaped pipe inside the args cell does not truncate it: the "
              "cell ends at an UNESCAPED bar, and reading it the other way "
              "reported six commands as missing flags written two characters "
              "further along: %r" % (_d,),
              _d["checked"] == 1 and _d["missing"] == [])
        with open(os.path.join(_tmp_ref, "plugins", "audit", "commands", "demo.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("---\nargument-hint: 'push [a|b] [--task <id>] [--deep] | pull'\n---\n")
        _d = M.command_flag_drift(_tmp_ref)
        check("cf4 ...and a flag the row really does omit IS reported, by command "
              "and by flag: %r" % (_d["missing"],),
              _d["missing"] == [("demo", "--deep")])
        with open(os.path.join(_tmp_ref, "plugins", "audit", "commands", "noargs.md"),
                  "w", encoding="utf-8") as fh:
            fh.write("---\ndescription: 'x'\n---\n")
        check("cf5 a command with no argument-hint is not a finding - it takes no "
              "arguments, and silence there is an answer",
              M.command_flag_drift(_tmp_ref)["checked"] == 1)
    finally:
        shutil.rmtree(_tmp_ref, ignore_errors=True)

    # --- the phase verbs: two spellings, one writer ----------------------------
    # WHY HERE. `tools/affected.py` routes an edit under `plugins/audit/commands/`
    # to this suite and to `test__deps.py`, and to nothing else. A pin on a command
    # document parked beside its script's own suite would therefore not run on the
    # change that breaks it, and this suite already owns the README-versus-command
    # relation above.
    #
    # THE RULE THESE HOLD. A verb that mutates a PHASE is spelled under
    # `/audit:phase`. `/audit:task priority` and `/audit:task cancel <phaseId>`
    # still work and are documented as the legacy spellings - `commands/migrate.md`
    # is the shape being copied - and neither command file carries a second copy of
    # the other's procedure. The defect: `phase.priority` is the field the schema
    # has and `task.priority` is a field it does not, so a command named `task`
    # taking a phase id taught the command list the opposite of the truth.
    _PH = _product_doc("commands/phase.md")
    _TK = _product_doc("commands/task.md")
    _PRD = _product_doc("README.md")
    _SP_BASE = "set-priority.py"
    _AT_BASE = "audit-task.py"

    _ph_hint = _frontmatter(_PH, "argument-hint")
    _ph_alts = [a.strip() for a in _ph_hint.split("|")]
    _ph_verbs = sorted(set(a.split()[0] for a in _ph_alts[1:] if a.split()))
    check("pv1 /audit:phase's argument-hint still opens with the BARE run form: a "
          "first alternative beginning with a word would mean running a phase now "
          "needs a verb, which is the one thing adding subcommands must not "
          "change: %r" % (_ph_alts[:1],),
          len(_ph_alts) >= 2 and _ph_alts[0].startswith("<phaseId>")
          and "--dry-run" in _ph_alts[0])
    # The pair for pv1. A reserved token spelled `<something>` could not be told
    # from a phase id by any rule at all, which is the failure mode of dispatching
    # on a first token.
    check("pv1b ...and every later alternative opens with a literal lowercase "
          "word, never a placeholder: %r" % (_ph_verbs,),
          _ph_verbs != [] and all(re.match(r"^[a-z]+$", w) for w in _ph_verbs))

    _ph_dispatch = _md_section(_PH, "## 0.")
    check("pv2 the dispatch section names every reserved token the hint declares, "
          "and the set is DERIVED from the hint rather than typed a second time - "
          "two lists of reserved words is how one of them stops being reserved: "
          "%r" % (_ph_verbs,),
          _ph_verbs != []
          and all(("`%s`" % w) in _ph_dispatch for w in _ph_verbs))
    # COUNTED BOTH WAYS, which presence cannot do: a verb advertised in the hint
    # with no section is unreachable, and a section no hint declares is a verb
    # nobody can find. Duplicate headings are rejected too, since `set()` on the
    # left would otherwise hide a second copy of one on the right.
    _ph_subs = re.findall(r"^## Subcommand: `([a-z]+)", _PH, re.M)
    # The emptiness guard is not decoration: two empty lists compare equal, so a
    # document this stopped being able to read would satisfy the comparison while
    # checking nothing at all - and it did, on the first run of this block.
    check("pv3 one section per reserved token, counted from both documents' own "
          "words: hint %r vs headings %r" % (_ph_verbs, _ph_subs),
          _ph_subs != [] and _ph_verbs == sorted(_ph_subs)
          and len(_ph_subs) == len(set(_ph_subs)))

    check("pv4 the priority procedure sits in ONE command file - /audit:phase "
          "names the writer, /audit:task names it not at all (%d vs %d). Two "
          "command files with two copies of one invocation is what "
          "`commands/propose.md` states the rule against."
          % (_PH.count(_SP_BASE), _TK.count(_SP_BASE)),
          _PH.count(_SP_BASE) > 0 and _TK.count(_SP_BASE) == 0)

    # THE SAME ARGUMENTS, and read off the writer's own parser rather than a list
    # kept here. A flag documented on the command side only is the half that
    # silently does nothing, which is exactly what a second spelling risks.
    _sp_src = ""
    try:
        with open(os.path.join(M.REPO_ROOT,
                               M.PLUGIN_REL.replace("/", os.sep),
                               "scripts", "manifest", _SP_BASE),
                  "r", encoding="utf-8") as _fh:
            _sp_src = _fh.read()
    except (OSError, UnicodeDecodeError):
        _sp_src = ""
    _sp_flags = set(re.findall(r'add_argument\(\s*"(--[a-z][a-z-]*)"', _sp_src))
    _ph_pri = _md_section(_PH, "## Subcommand: `priority")
    _pri_flags = set(re.findall(r"--[a-z][a-z-]*", _ph_pri))
    _pri_unknown = sorted(_pri_flags - _sp_flags)
    check("pv5 every flag the new spelling documents is one the writer's parser "
          "declares - both spellings must reach the script with the same "
          "arguments: unknown %r, parser %r"
          % (_pri_unknown, sorted(_sp_flags)),
          _sp_flags != set() and _pri_flags != set() and _pri_unknown == [])

    _tk_pri = _md_section(_TK, "## Subcommand: `priority")
    check("pv6 the legacy spelling is documented AS legacy and hands the reader "
          "the new one: `commands/migrate.md`'s shape, applied to a subcommand",
          "legacy" in _tk_pri.lower()
          and _tk_pri.count("/audit:phase priority") > 0)
    # THE SECOND DIRECTION, and it looks vacuous on purpose. The wrong fix here is
    # not "the alias stops working" but "the alias nags": a warning on a spelling
    # that still works teaches people to skip warnings, which is how a real refusal
    # gets missed later. `commands/migrate.md` emits none either.
    check("pv7 ...and it does not nag - the alias runs, says the new name once and "
          "gets on with it",
          _tk_pri != ""
          and _tk_pri.lower().count("warn") == 0
          and _tk_pri.lower().count("deprecat") == 0)

    _ph_run = _md_section(_PH, "## Run a phase")
    _ph_steps = re.findall(r"^\d+\. ", _ph_run, re.M)
    check("pv8 the bare run form is untouched: its numbered steps, its dry-run "
          "branch, the branch resolver and the sign-off are all still in it "
          "(steps found: %r)" % (_ph_steps,),
          len(_ph_steps) == 5 and "--dry-run" in _ph_run
          and "resolve-branch.py" in _ph_run and "Phase sign-off" in _ph_run)
    # The pair for pv8, and the one that fails if a verb leaks downward: a run
    # procedure naming either writer would mean `/audit:phase P2` could mutate the
    # plan before executing anything in it.
    check("pv9 ...and the run procedure names neither writer",
          _ph_run != "" and _ph_run.count(_SP_BASE) == 0
          and _ph_run.count(_AT_BASE) == 0)

    _ph_cancel = _md_section(_PH, "## Subcommand: `cancel")
    _tk_cancel = _md_section(_TK, "## Subcommand: `cancel")
    check("pv10 cancellation is described once, in the file that owns its writer: "
          "the phase spelling routes to `commands/task.md` and restates nothing "
          "of what the script writes, which the task spelling still carries",
          _ph_cancel.count("commands/task.md") > 0
          and _ph_cancel.count("outcome.descriptive") == 0
          and _tk_cancel.count("outcome.descriptive") > 0)
    check("pv11 ...and the phase spelling REFUSES a task id, naming the spelling "
          "that takes one - a command called `phase` mutating a task is the same "
          "noun/verb mismatch this change removes. The needle is the TASK-ID form: "
          "the section names the other spelling twice, once for each id shape, so "
          "a bare `/audit:task cancel` cannot tell the narrowing from the legacy "
          "note beneath it",
          _ph_cancel.count("/audit:task cancel <taskId>") == 1
          and "refuse" in _ph_cancel.lower())

    # The args cell is read with `_CMD_ROW`, the module's own rule for where a cell
    # ends, rather than a second regex here - `cf3` is the case that exists because
    # the naive reading truncated half these cells at an escaped pipe.
    _prd_args = dict((m.group(1), m.group(2)) for m in M._CMD_ROW.finditer(_PRD))

    def _cell_verbs(cell):
        """The verbs a README args cell declares, parsed the way the command's own
        `argument-hint` is parsed - so the two are compared as SETS. Asking whether
        a word appears somewhere in the row instead passes on a row that merely
        mentions the verb while declaring something else."""
        alts = [a.strip().strip("`").strip() for a in cell.split("\\|")]
        return sorted(set(a.split()[0] for a in alts[1:] if a.split()))

    check("pv12 the README's `/audit:phase` row DECLARES the same verbs the command "
          "does - the command table is where a reader learns a PHASE is the thing "
          "with a priority, which is the reading the old spelling inverted: row %r "
          "vs hint %r" % (_cell_verbs(_prd_args.get("phase", "")), _ph_verbs),
          _ph_verbs != [] and _cell_verbs(_prd_args.get("phase", "")) == _ph_verbs)
    check("pv13 ...and the `/audit:task` row sends new work to the phase spelling "
          "instead of teaching the old one",
          _PRD.count("`/audit:phase priority <phaseId> <tier\\|--clear>`") > 0)

    # --- F198: the hint is the only view a caller gets of the interface --------
    # Measured live: an operator holding a whole task specification - files, gate,
    # risk, tests-mode, description - asked whether to paste it as the command,
    # because the hint advertised `--phase` and nothing else while the script took
    # eleven write flags for `add`. Five tasks were about to be created through
    # rounds of `AskUserQuestion` each, and every question that did not need
    # asking is another chance to PARAPHRASE a value the caller had already
    # decided, which is the defect F191 fixed for `--reason`.
    #
    # DERIVED FROM THE SCRIPT'S OWN USAGE BLOCK, never a list kept here - `pv5`'s
    # rule, applied per verb. The flags common to EVERY verb are the global ones
    # by construction, so nothing has to be declared global by hand and a new
    # global does not have to be added in two places.
    _at_src = ""
    try:
        with open(os.path.join(M.REPO_ROOT,
                               M.PLUGIN_REL.replace("/", os.sep),
                               "scripts", "manifest", _AT_BASE),
                  "r", encoding="utf-8") as _fh:
            _at_src = _fh.read()
    except (OSError, UnicodeDecodeError):
        _at_src = ""
    _at_parser = set(re.findall(r'add_argument\(\s*"(--[a-z][a-z-]*)"', _at_src))

    def _usage_flags(src):
        """`(per_verb, common)` off `audit-task.py`'s own `Usage:` block. A line
        opening with the script name and a WORD starts a verb; a continuation line
        keeps it; `--selftest` opens with neither and ends attribution, which is
        what keeps the prose under the block out of every verb's set."""
        block = src.split("Usage:", 1)[-1].split("Exit codes:", 1)[0]
        per, verb = {}, None
        for line in block.splitlines():
            head = line.strip().split()
            if head[:1] == [_AT_BASE]:
                verb = head[1] if len(head) > 1 and head[1][:1].isalpha() else None
            if verb:
                per.setdefault(verb, set()).update(
                    re.findall(r"--[a-z][a-z-]*", line))
        common = set.intersection(*per.values()) if per else set()
        return dict((v, f - common) for v, f in per.items()), common

    _at_usage, _at_common = _usage_flags(_at_src)
    _tk_hint = _frontmatter(_TK, "argument-hint")
    _tk_alts = [a.strip() for a in _tk_hint.split("|")]
    _tk_verbs = [a.split()[0] for a in _tk_alts if a.split()]
    _tk_flags = dict((a.split()[0], set(re.findall(r"--[a-z][a-z-]*", a)))
                     for a in _tk_alts if a.split())

    # F207. THE HINTS OF BOTH DOCS, because the verb where this class recurred a
    # third time lives in the other one. `_tk_flags` is `commands/task.md`'s, and
    # `pf1` skipped any verb absent from it -- so `add-phase` was outside the check
    # that exists BECAUSE of `scope` (F196) and `add` (F201). Measured: a row added
    # to `_AT_WRITERS` for it stayed green with the flag's read DELETED, which is a
    # check asserting nothing.
    #
    # `phase.md` spells the command verb `add` while the script spells it
    # `add-phase`, so the two names are mapped rather than assumed equal - and the
    # map is here, once, instead of a second table.
    # DERIVED FROM `_ph_alts`, which `pv1`/`pv1b` above already parsed and
    # guarded. The first draft re-read the frontmatter here, which is one
    # document parsed twice in one function -- two sources for one fact, and the
    # copy would have been the one to rot.
    _ph_flags = dict((a.split()[0], set(re.findall(r"--[a-z][a-z-]*", a)))
                     for a in _ph_alts if a.split())
    _SCRIPT_VERB = {"add-phase": ("phase", "add")}

    check("tk1 every alternative in /audit:task's hint opens with a literal "
          "lowercase verb - the parse below splits on the bar, so an enumerated "
          "VALUE written with one (`--tests-mode tdd|regression`) would turn half "
          "a flag list into a verb nobody can run and read as compliance: %r"
          % (_tk_verbs,),
          _tk_verbs != []
          and all(re.match(r"^[a-z]+$", v) for v in _tk_verbs))
    # F210. BOTH COMMAND DOCS, because reading one of them was the defect twice.
    # `tk2` compared `commands/task.md` against the usage block and nothing
    # compared `commands/phase.md`, so that hint advertised three flags for `add`
    # against a usage block naming eight - F198's defect surviving in the
    # document F198 did not touch. `phase.md` spells the verb `add` while the
    # script spells it `add-phase`, so the two are MAPPED, in the same one place
    # `pf1` maps them.
    _tk_all = dict(_tk_flags)
    for _tkv in sorted(_SCRIPT_VERB):
        _tkcmd = _SCRIPT_VERB[_tkv][1]
        if _ph_flags.get(_tkcmd):
            _tk_all[_tkv] = _ph_flags[_tkcmd]
    _tk_shared = sorted(set(_tk_all) & set(_at_usage))
    _tk_off = dict((v, (sorted(_tk_all[v]), sorted(_at_usage[v])))
                   for v in _tk_shared if _tk_all[v] != _at_usage[v])
    check("tk2 for every verb both the hint and the writer's usage block name, "
          "the flags are the SAME SET - equality rather than a subset, because "
          "the fault ran in one direction (a hint advertising `--phase` against a "
          "verb taking eleven) and a flag the script later drops would rot in the "
          "other. Read over BOTH command docs, so a phase verb is not outside "
          "the check that exists for a task verb: %r" % (_tk_off,),
          _tk_shared != [] and _tk_off == {}
          # The vacuity half OF THE WIDENING, which the count below cannot give:
          # if the verb map stopped resolving, the loop above would silently
          # compare `task.md` alone and this line would read exactly as it does.
          and all(v in _tk_shared for v in _SCRIPT_VERB))
    # THE VACUITY GUARD, and it is not decoration: `_tk_off == {}` is also what an
    # intersection that had gone EMPTY returns, which is how a renamed verb on
    # either side would leave this line green over nothing.
    check("tk3 ...and the intersection is the four verbs the script owns across "
          "the two docs, with `move` on the hint side alone because it is an "
          "Edit procedure rather than a script call - counted, so a rename on "
          "either side is a finding rather than a silent skip: %r"
          % ((_tk_shared, sorted(_tk_flags)),),
          _tk_shared == ["add", "add-phase", "cancel", "scope"]
          and "move" in _tk_flags and "move" not in _at_usage)
    # `_tk_all`, not `_tk_flags`: the latter has no row for a verb that came from
    # the other document, and indexing it here raised `KeyError` the first time
    # the widening ran - which is worth a comment because the traceback pointed
    # at this line and the cause was six lines up.
    _tk_unknown = sorted(set(f for v in _tk_shared for f in _tk_all[v])
                         - _at_parser)
    check("tk4 every flag the hint declares for a SCRIPT verb is one argparse "
          "defines - a hint is typed by hand, and a flag the parser does not "
          "know is a command the operator types and gets a usage error for: "
          "unknown %r" % (_tk_unknown,),
          _at_parser != set() and _tk_unknown == [])
    _tk_desc = _frontmatter(_TK, "description")
    check("tk5 the frontmatter no longer calls `add` interactive - the dialogue is "
          "the FALLBACK for arguments the caller did not supply, not the verb's "
          "nature, and a description that says otherwise is what stopped a caller "
          "from passing values it had already decided: %r" % (_tk_desc[:120],),
          _tk_desc != "" and "(interactive)" not in _tk_desc
          and "flag" in _tk_desc)
    # THE SECOND DIRECTION for tk5. The wrong over-correction is to delete the
    # dialogue: the command must still ask for what the caller left out, and a
    # document that dropped that would satisfy the line above.
    # THE SECOND DIRECTION for tk5, and it is looked for in the `add` SECTION
    # rather than in the file: the intro carries its own copy of the phrase, so a
    # document that deleted the instruction from the procedure would still satisfy
    # a presence check over the whole text. It did, on the first red-first run.
    _tk_add = _md_section(_TK, "## Subcommand: `add")
    check("tk6 ...and the PROCEDURE still says it asks only for what is missing - "
          "the wrong over-correction is to delete the dialogue rather than demote "
          "it, and a caller who supplies nothing must still be asked",
          "ask only for what's missing" in _tk_add
          and "the dialogue is the fallback" in _TK.lower())

    # --- F196 / F201: a flag ADVERTISED for a verb the verb never reads --------
    # `tk4` above proves every advertised flag is one argparse defines, and that is
    # not the same question. Every flag on this parser is GLOBAL, so argparse
    # accepts `add --gate-clear` and `scope --gate-clear` alike whether or not the
    # verb's own writer looks at it - which is how the same defect shipped twice:
    # `scope --gate-clear` exited 0 and left the gate where it was (F196), and
    # `add --gate-clear` reported success and wrote the phase's testGate (F201).
    # Both were found by RUNNING the command, and nothing in the tree could see
    # them. A whole-file search for `args.gate_clear` would not have: the string was
    # in the file, in the other verb.
    #
    # THE VERB-TO-WRITER TABLE IS DECLARED, and it is the one hand-kept thing here.
    # A verb's flags are read across its door and the function that builds its
    # payload, and there is no mechanical link from the subcommand STRING to those
    # names - so they are named, and `pf2` fails if a name stops resolving rather
    # than letting a missing function read as a verb with nothing to check.
    # F207 put `add-phase` in this table. It was the third verb to accept
    # `--gate-clear` off the global parser and ignore it, after `scope` (F196) and
    # `add` (F201) -- the check that exists BECAUSE of those two did not cover the
    # verb where it happened again. `_phase_gate` is listed as a writer because it
    # is where the flag is read, the way `_build_task` is for `add`.
    _AT_WRITERS = {"add": ("cmd_add", "_locked_add", "_build_task"),
                   # `_build_phase` is `add`'s `_build_task` one verb over, and
                   # it was MISSING here until F210 widened the hint that names
                   # its flags. Nothing was wrong with the code: the row was
                   # incomplete, and the check went quiet over the gap rather
                   # than reporting one - which is what a writer table costs when
                   # it is maintained by hand and read by only one case.
                   "add-phase": ("cmd_phase_add", "_locked_phase_add",
                                 "_phase_gate", "_build_phase"),
                   "scope": ("cmd_scope", "_locked_scope"),
                   "cancel": ("cmd_cancel", "_locked_cancel", "_cancel_task")}

    def _at_dests(src):
        """`{flag: dest}` off the parser - argparse's own rule, plus the explicit
        `dest=` where the file spells one."""
        out = {}
        for flag, dest in re.findall(
                r'add_argument\(\s*"(--[a-z][a-z-]*)"(?:,\s*dest="([a-z_]+)")?',
                src):
            out[flag] = dest or flag[2:].replace("-", "_")
        return out

    def _fn_body(src, name):
        """`def name(` down to the next top-level `def` - the slice the fault
        entries' own `sed` takes, and `""` when the name is not there."""
        head = "\ndef %s(" % (name,)
        at = src.find(head)
        if at < 0:
            return ""
        rest = src[at + 1:]
        end = rest.find("\ndef ")
        return rest if end < 0 else rest[:end]

    def _at_reads(src, name):
        """The `args.<attr>` a top-level function actually READS, off the AST.

        Not a text search of the function body, and F207 is why. `pf1` searched
        for the literal `args.<dest>` in the writer's SOURCE, so a line of prose
        naming the dest satisfied it -- the comment explaining this very repair
        contained `args.gate_clear`, and with the read DELETED the check stayed
        green on the comment alone. A docstring, a `%r` in a message or a
        commented-out line all count as a read to a grep and none of them is
        one. The AST cannot be fooled by any of the three.
        """
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return None                      # pf2 turns this into a failure
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name != name:
                continue
            found = set()
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Attribute)
                        and isinstance(sub.value, ast.Name)
                        and sub.value.id == "args"):
                    found.add(sub.attr)
                # `getattr(args, "x")` IS a read, and counting only the dotted
                # spelling would fail a writer that reads defensively. Which
                # spelling to prefer is a style question and belongs to
                # `house_style_violations()`, not here: this case asks whether
                # the flag is read at all.
                elif (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "getattr"
                        and len(sub.args) >= 2
                        and isinstance(sub.args[0], ast.Name)
                        and sub.args[0].id == "args"
                        and isinstance(sub.args[1], ast.Constant)
                        and isinstance(sub.args[1].value, str)):
                    # `ast.Constant`, not `ast.Str`: 3.8 already produces the
                    # former and 3.12 REMOVED the latter, so the deprecated
                    # alias is the one spelling that fails at both ends of this
                    # repo's supported range. It read green here only because
                    # no source in the tree takes this branch - the red-first
                    # probe for the defensive spelling is what runs it.
                    found.add(sub.args[1].value)
            return found
        return None                          # the name no longer resolves

    _at_dest = _at_dests(_at_src)
    _pf_found = dict((v, [n for n in names if _fn_body(_at_src, n)])
                     for v, names in _AT_WRITERS.items())
    _pf_unread = []
    for _pfv in sorted(_AT_WRITERS):
        if _pfv in _SCRIPT_VERB:
            _doc, _cmdverb = _SCRIPT_VERB[_pfv]
            _pf_flags = _ph_flags.get(_cmdverb)
        else:
            _pf_flags = _tk_flags.get(_pfv)
        if not _pf_flags:
            continue
        _pf_read = set()
        for _pfn in _AT_WRITERS[_pfv]:
            _pf_read |= (_at_reads(_at_src, _pfn) or set())
        for _pff in sorted(_pf_flags):
            _pfd = _at_dest.get(_pff)
            if _pfd and _pfd not in _pf_read:
                _pf_unread.append((_pfv, _pff))
    # WHAT IT CANNOT SEE, measured by mutation rather than reasoned about: a dest
    # named in the verb's REFUSAL and then never applied still satisfies this, and
    # deleting the write while leaving the guard was tried and left it green. It
    # catches the shape both faults actually had - a dest absent from the verb
    # entirely - and the cases in `test_audit_task.py` are what cover the other.
    check("pf1 every flag the hint advertises FOR A VERB is one that verb's own "
          "writer reads - the parser is global, so argparse accepts a flag the "
          "verb ignores and reports success without it, which is F196 and F201 "
          "twice over and is invisible to a whole-file search for the dest: "
          "unread %r" % (_pf_unread,),
          _pf_unread == [])
    # THE VACUITY GUARD, and it is the half that matters: an empty flag set, a
    # `dest` map that failed to parse, or a writer name that no longer resolves all
    # make the loop above green over nothing.
    _pf_checked = sorted(set(
        f for v in _AT_WRITERS
        for f in ((_ph_flags.get(_SCRIPT_VERB[v][1]) if v in _SCRIPT_VERB
                   else _tk_flags.get(v)) or ())))
    _pf_resolved = sorted((v, n) for v in _AT_WRITERS for n in _AT_WRITERS[v]
                          if _at_reads(_at_src, n) is None)
    check("pf2 ...over a flag set and a writer table that both actually resolved, "
          "AND over an AST every writer could be found in - "
          "a renamed function or an unparsed dest map would leave pf1 green over "
          "nothing at all: %r"
          % ((len(_pf_checked), sorted(_pf_found.items())),),
          _pf_checked != [] and "--gate-clear" in _pf_checked
          and _pf_resolved == []
          and all(list(_pf_found[v]) == list(_AT_WRITERS[v])
                  for v in _AT_WRITERS)
          and _at_dest.get("--gate-clear") == "gate_clear"
          and _at_dest.get("--blocked-by") == "blocked_by")


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__refs.py --selftest\n")
    raise SystemExit(2)
