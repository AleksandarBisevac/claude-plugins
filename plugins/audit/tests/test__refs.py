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


def _fixture_tree(tmp, command_line, hook_line=None):
    """A minimal repo: one real script, one commands/ document, one hooks/ file."""
    _write(tmp, _FX_SCRIPTS + "real.py", "# a real file\n")
    _write(tmp, _FX_COMMANDS + "x.md", "Run %s to do the thing.\n" % command_line)
    if hook_line is not None:
        _write(tmp, _FX_HOOKS + "h.py", hook_line + "\n")
    return tmp


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
        check("p1 a placeholder and a glob are both SEEN (total 2) and both held out of "
              "the stat (checked 0), so neither vanishes and neither is a false miss",
              (res["total"], len(res["placeholders"]), res["checked"],
               res["missing"]) == (2, 2, 0, []), repr(res))
        # The three arguments stay SPELLED where every fixture path is built, and the
        # difference is the point: these are inputs to a pure predicate, not files a
        # case creates. Two are placeholders (held out of the stat by the very rule
        # under test) and the third is a real file, so all three are references this
        # module is happy to have - and keeping them literal is what makes `c1`'s
        # count identical on both sides of the move.
        check("p2 is_placeholder is the one rule, and it answers for both shapes",
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
    check("c3 agents/ and the root README name no script path today, and that is "
          "recorded rather than passed over",
          counts["plugins/audit/agents"] == 0 and counts["README.md"] == 0,
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
    check("tb1 no `.py` basename written anywhere in tools/ names a file that is gone: "
          "%r" % (tb["unknown"],), tb["unknown"] == [])
    check("tb2 ...and the run says how much it looked at - %d basename literals across "
          "%d files. `unknown == []` means one thing at the count printed here and "
          "something else entirely at 0, and a regex that quietly stopped matching "
          "would report the calm version of both" % (tb["checked"], tb["files"]),
          tb["checked"] >= 20 and tb["files"] >= 3,
          repr((tb["checked"], tb["files"])))

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
    check("d1 NO join of the SCRIPTS constant is left in the capture tool - the eight "
          "script sites go through the resolver, and the one exempt site (a read of "
          "ui/panel.js, argued safe because a UI asset cannot be relabelled) died "
          "when panel.js was cut into parts and the path stopped existing. It asks "
          "Python for the ASSEMBLED page now. This is the case that goes red when a "
          "join creeps back: %r" % (_joins,),
          not _joins)
    check("d2 ...and the NINE resolver calls are really there, resolving by BASENAME "
          "with no folder argument. Reads vacuous beside d1 and is the half that fails "
          "if the call sites were deleted rather than converted - the ninth arrived "
          "when the polled-state guard stopped reading ui/panel.js by path and started "
          "asking _panel_ui.py for the assembled page (got %d)"
          % (_mjs.count("resolveScript('"),),
          _mjs.count("resolveScript('") == 9
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
    check("s1 every document that shows the selftest sweep shows the recursive form: "
          "%r" % (drift,), drift == [])

    tmp = tempfile.mkdtemp()
    # One document per format, named rather than indexed, because the three cases that
    # matter now are each about a DIFFERENT runnable region and `SWEEP_DOCS[0]` says
    # nothing about which.
    _yml = [r for r in M.SWEEP_DOCS if r.endswith((".yml", ".yaml"))][0]
    _md = [r for r in M.SWEEP_DOCS if r.endswith(".md")][0]
    _jsn = [r for r in M.SWEEP_DOCS if r.endswith(".json")][0]
    try:
        for rel in M.SWEEP_DOCS:
            _write(tmp, rel, _sweep_doc(rel, M.SWEEP_FIND))
        check("s2 ...and that fixture is green, so the cases below fail for the reason "
              "they name and not because the fixture was broken",
              M.sweep_glob_drift(tmp) == [], repr(M.sweep_glob_drift(tmp)))
        _write(tmp, _yml, _sweep_doc(_yml, M.SWEEP_FLAT))
        _d = M.sweep_glob_drift(tmp)
        check("s3 a document that has drifted back to the flat glob is reported twice "
              "over - it lost the find form AND regained the glob",
              len([x for x in _d if x[0] == _yml]) == 2
              and any("flat sweep" in x[1] for x in _d)
              and any("recursive sweep" in x[1] for x in _d), repr(_d))
        _write(tmp, _yml, _sweep_doc(_yml, "make test"))
        _d = M.sweep_glob_drift(tmp)
        check("s4 a document that simply stops carrying the sweep is reported once, "
              "and the two failures stay distinguishable",
              [x for x in _d if x[0] == _yml]
              == [(_yml, "does not carry the recursive sweep %r" % M.SWEEP_FIND)],
              repr(_d))
        # Scoped to the executable shape AND to the executable REGION. A version aimed
        # at the substring `scripts/*.py` would fail the first half of this fixture, and
        # would fail the real guide - which is what c6's placeholders show it
        # legitimately writes twice. A version aimed at the whole FILE would fail the
        # second half, which is F21's shape exactly: a document warning against the
        # retired sweep, reported as carrying it.
        _write(tmp, _yml, _sweep_doc(
            _yml, M.SWEEP_FIND,
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
        _write(tmp, _yml, _sweep_doc(_yml, M.SWEEP_FIND))
        # The flat listing is BUILT, never spelled: this file is one of the ANCHORED
        # surfaces `_refs` scans, and an anchor written in front of a glob here would
        # be a real reference the placeholder counts have to account for. Same rule as
        # every other fixture path in this suite.
        _write(tmp, _md, _sweep_doc(
            _md, "for f in $(ls %s/scripts/*.py); do python3 \"$f\"; done"
                 % M.PLUGIN_REL,
            "The sweep must be recursive - it is `%s`, never a flat glob."
            % M.SWEEP_FIND))
        _d = M.sweep_glob_drift(tmp)
        check("s8 a document whose PROSE quotes the recursive sweep while the block a "
              "reader would run is a flat listing does NOT satisfy the rule - the "
              "direction that hurts is the mention that makes a check pass, and the "
              "whole-file substring could not tell the two apart",
              [x for x in _d if x[0] == _md]
              == [(_md, "does not carry the recursive sweep %r" % M.SWEEP_FIND)],
              repr(_d))

        # ---- mutation proof: the whole-file scan this replaced misses s8 ----------
        def _whole_file_sweep_drift(root):
            out = []
            for rel in M.SWEEP_DOCS:
                with open(os.path.join(root, rel.replace("/", os.sep)),
                          "r", encoding="utf-8") as fh:
                    text = fh.read()
                if M.SWEEP_FIND not in text:
                    out.append((rel, "does not carry the recursive sweep %r"
                                % M.SWEEP_FIND))
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

        # ---- a region that cannot be read is loud, never a fallback --------------
        _write(tmp, _md, _sweep_doc(_md, M.SWEEP_FIND))
        _write(tmp, _jsn, "{ this is not json at all\n%s\n" % M.SWEEP_FIND)
        _d = M.sweep_glob_drift(tmp)
        check("s11 a manifest that will not parse is reported as unreadable commands, "
              "not read as text - a fallback to the whole file would let the very "
              "string it is looking for pass from a broken document",
              [x for x in _d if x[0] == _jsn]
              == [(_jsn, "will not parse as JSON; its commands cannot be read")],
              repr(_d))
        check("s12 ...and a format with no runnable-region rule is a violation too, "
              "for the same reason: %r"
              % (M._runnable_text("NOTES.rst", M.SWEEP_FIND),),
              M._runnable_text("NOTES.rst", M.SWEEP_FIND)[0] is None
              and "no runnable-region rule"
              in M._runnable_text("NOTES.rst", M.SWEEP_FIND)[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # And on the real guide, which is where the prose actually lives.
    with open(os.path.join(M.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md"),
              "r", encoding="utf-8") as fh:
        _guide = fh.read()
    check("s7 the real guide writes `scripts/*.py` as prose twice and carries the "
          "recursive sweep, and is green on both counts",
          _guide.count("scripts/*.py") == 2 and M.SWEEP_FIND in _guide
          and M.SWEEP_FLAT not in _guide, repr(_guide.count("scripts/*.py")))

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


    # --- F36: a command's flags vs the README row that catalogues them ---------
    # The defect this exists for was live when it was written: /audit:status had
    # grown --gate and --fail-on while its README row said "-", and /audit:doctor
    # had grown --deep while its row still said [--json]. A capability nobody can
    # find is the thing this repo keeps meeting.
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__refs.py --selftest\n")
    raise SystemExit(2)
