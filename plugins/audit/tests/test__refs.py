#!/usr/bin/env python3
"""
The cases for `scripts/_refs.py`, moved out of it - a lint that scans the tree, from
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
import shutil
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _refs as M                                  # noqa: E402


# --- fixture paths: built, never spelled --------------------------------------
_ANCHOR_LITERAL = "${CLAUDE_PLUGIN_ROOT}/"
_FX_SCRIPTS = M.PLUGIN_REL + "/scripts/"
_FX_HOOKS = M.PLUGIN_REL + "/hooks/"
_FX_COMMANDS = M.PLUGIN_REL + "/commands/"
_FX_TESTS = M.PLUGIN_REL + "/tests/"


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
          "${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py strings require-plan.py carries",
          len(hook_script_hits) == 3
          and set(h[0] for h in hook_script_hits) == set([_FX_HOOKS + "require-plan.py"])
          and set(h[3] for h in hook_script_hits)
          == set([_FX_SCRIPTS + "audit-lock.py"]), repr(hook_script_hits))
    # a4's subject moved with the suite it belongs to. The unanchored
    # `scripts/build.py` and `hooks/require-plan.py` inside guard-secrets-read's
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
          len(set(h[0] for h in hook_test_hits)) == 10
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

    # --- the sweep -------------------------------------------------------------------
    drift = M.sweep_glob_drift()
    check("s1 every document that shows the selftest sweep shows the recursive form: "
          "%r" % (drift,), drift == [])

    tmp = tempfile.mkdtemp()
    try:
        for rel in M.SWEEP_DOCS:
            _write(tmp, rel, "Run:\n\n    %s\n" % M.SWEEP_FIND)
        check("s2 ...and that fixture is green, so the cases below fail for the reason "
              "they name and not because the fixture was broken",
              M.sweep_glob_drift(tmp) == [], repr(M.sweep_glob_drift(tmp)))
        _write(tmp, M.SWEEP_DOCS[0], "Run:\n\n    %s\n" % M.SWEEP_FLAT)
        _d = M.sweep_glob_drift(tmp)
        check("s3 a document that has drifted back to the flat glob is reported twice "
              "over - it lost the find form AND regained the glob",
              len([x for x in _d if x[0] == M.SWEEP_DOCS[0]]) == 2
              and any("flat sweep" in x[1] for x in _d)
              and any("recursive sweep" in x[1] for x in _d), repr(_d))
        _write(tmp, M.SWEEP_DOCS[0], "Run the suites somehow.\n")
        _d = M.sweep_glob_drift(tmp)
        check("s4 a document that simply stops carrying the sweep is reported once, "
              "and the two failures stay distinguishable",
              [x for x in _d if x[0] == M.SWEEP_DOCS[0]]
              == [(M.SWEEP_DOCS[0],
                   "does not carry the recursive sweep %r" % M.SWEEP_FIND)],
              repr(_d))
        # Scoped to the executable shape. A version aimed at the substring `scripts/*.py`
        # would fail this fixture, and would fail the real guide - which is what c6's
        # placeholders show it legitimately writes twice.
        _write(tmp, M.SWEEP_DOCS[0],
               "The map is the import graph of `scripts/*.py`.\n\n    %s\n"
               % M.SWEEP_FIND)
        check("s5 prose that merely mentions the glob, beside a correct sweep, is NOT "
              "flagged - the rule is the runnable line, not the substring",
              M.sweep_glob_drift(tmp) == [], repr(M.sweep_glob_drift(tmp)))
        os.remove(os.path.join(tmp, M.SWEEP_DOCS[0].replace("/", os.sep)))
        _d = M.sweep_glob_drift(tmp)
        check("s6 a sweep document that has gone missing is unreadable, never absent",
              len(_d) == 1 and _d[0][0] == M.SWEEP_DOCS[0]
              and "unreadable" in _d[0][1], repr(_d))
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__refs.py --selftest\n")
    raise SystemExit(2)
