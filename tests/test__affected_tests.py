#!/usr/bin/env python3
"""
The cases for `_affected_tests.py` -- which suites a task's change can break.

Every case outside `_dogfood_cases` and `_gather_cases` builds its `facts` BY
HAND: the selection is pure, so a related listing's answer, the Python sources
and the tree's suite files are dicts and strings here, never a subprocess or a
checkout. The cases in `_dogfood_cases` make claims about this repository's own
listings, sources and plan, so they read them; the cases in `_gather_cases` are
about the gathering that measures those facts, so they run listing commands in
a scratch tree. `af`-prefixed cases.

The four headline cases are the four ways the selection has to be right: a
recorded listing naming the test a move broke (the testbed's own regression),
an import graph that reaches exactly the tests it should and no other, a
listing that could not answer widening to the phase gate rather than reading
as "nothing affected", and e2e specs selected wholesale when nothing recorded
can say which of them a source change reaches.
"""

import os
import re
import shlex
import sys

import _harness                                   # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402
from _output import safe_stdio                     # noqa: E402
import _affected_tests as M                        # noqa: E402


LISTING = "pnpm vitest related --run --passWithNoTests --listTests {paths}"


def _meta(listing=None, coupling=None, answer="vitest/3.2.4"):
    derived = {"runner": "test",
               "verifiedOn": {"command": "pnpm vitest --version",
                              "answer": answer}}
    if listing is not None:
        derived["listing"] = listing
    meta = {"buildCommands": {"test": "pnpm vitest run"},
            "phaseGate": {"derived": derived}}
    if coupling is not None:
        meta["coupling"] = coupling
    return meta


def _suites(result):
    return [(s["path"], s["arm"]) for s in result["suites"]]


def _cases(check):
    # --- which paths a change touched ----------------------------------------
    moved = M.changed_paths("R100\0app/page.tsx\0app/[locale]/page.tsx\0"
                            "D\0lib/old.ts\0M\0lib/kept.ts\0")
    check("af1 a rename counts as BOTH its old and its new path, and a deletion "
          "as its old one - the old path is what another task's test still "
          "imports: %r" % (moved,),
          moved == ["app/page.tsx", "app/[locale]/page.tsx", "lib/old.ts",
                    "lib/kept.ts"])

    # --- the testbed's regression: a move, and the listing that sees it -------
    changed = M.changed_paths("R100\0app/page.tsx\0app/[locale]/page.tsx\0")
    command = LISTING.replace("{paths}", "app/page.tsx 'app/[locale]/page.tsx'")
    facts = {"versionAnswer": "vitest/3.2.4",
             "related": {"command": command, "exit": 0,
                         "paths": ["tests/unit/smoke.test.ts"]}}
    res = M.select(changed, _meta(listing={"related": LISTING}), facts)
    picked = [s for s in res["suites"] if s["path"] == "tests/unit/smoke.test.ts"]
    check("af2 a rename of app/page.tsx selects the smoke test importing "
          "@/app/page through the recorded related listing, and its basis names "
          "the listing command it came from: %r" % (res,),
          res["widen"] is None and len(picked) == 1
          and picked[0]["arm"] == "related" and command in picked[0]["basis"])

    # --- the Python import graph ----------------------------------------------
    sources = {
        "pkg/core.py": "import os\n",
        "pkg/mid.py": "from pkg import core\n",
        "pkg/other.py": "import json\n",
        "tests/test_direct.py": "import pkg.core\n",
        "tests/test_transitive.py": "from pkg.mid import thing\n",
        # a `.py` name handed to a call that loads nothing is not an import
        "tests/test_unrelated.py": ("import pkg.other\n"
                                    "WHERE = os.path.join('pkg', 'core.py')\n"),
        "tests/test_relative.py": "from .helpers import x\n",
        "tests/helpers.py": "from pkg.mid import y\n",
        "tests/test_loaded.py": "M = load_script('runner-tool.py')\n",
        "scripts/runner-tool.py": "import core\n",
    }
    res = M.select(["pkg/core.py"], {}, {"pySources": sources})
    got = sorted(p for p, arm in _suites(res) if arm == "python")
    check("af3 a Python module change selects EVERY test whose import closure "
          "reaches it - directly, through another module, through a relative "
          "import, and through a script loaded by its file name - and NO other: "
          "%r" % (res,),
          res["widen"] is None
          and got == ["tests/test_direct.py", "tests/test_loaded.py",
                      "tests/test_relative.py", "tests/test_transitive.py"])
    check("af4 ...and each python suite's basis names the changed path its "
          "imports reach: %r" % (res["suites"],),
          all("pkg/core.py" in s["basis"] for s in res["suites"]))

    gone = M.select(["pkg/core.py"], {},
                    {"pySources": dict((k, v) for k, v in sources.items()
                                       if k != "pkg/core.py")})
    check("af5 a DELETED module is still a node: the tests that import it are "
          "selected though its source no longer exists: %r" % (_suites(gone),),
          ("tests/test_direct.py", "python") in _suites(gone))

    broken = M.select(["pkg/other.py"], {},
                      {"pySources": {"pkg/other.py": "x = 1\n",
                                     "tests/test_bad.py": "def (:\n"}})
    check("af6 a test file that does not parse has imports nobody can read, so it "
          "is SELECTED with that basis rather than left out: %r" % (broken,),
          [(s["path"], s["arm"]) for s in broken["suites"]]
          == [("tests/test_bad.py", "python")]
          and "does not parse" in broken["suites"][0]["basis"])

    unread = M.select(["pkg/core.py"], {}, {})
    check("af7 a .py change whose sources were never read WIDENS - no graph is "
          "not an empty graph: %r" % (unread,),
          unread["widen"] is not None and unread["suites"] == [])

    # --- a listing that cannot answer ------------------------------------------
    failed = M.select(changed, _meta(listing={"related": LISTING}),
                      {"versionAnswer": "vitest/3.2.4",
                       "related": {"command": command, "exit": 2, "paths": []}})
    check("af8 a related listing that exits non-zero yields the PHASE GATE with "
          "the skip reason printed, never an empty selection read as 'nothing "
          "affected': %r" % (failed,),
          failed["suites"] == [] and failed["widen"] is not None
          and "exited 2" in failed["widen"]
          and "phase gate" in failed["widen"]
          and any(failed["widen"] in ln for ln in failed["lines"]))

    stale = M.select(changed, _meta(listing={"related": LISTING}),
                     {"versionAnswer": "vitest/4.0.0",
                      "related": {"command": command, "exit": 0,
                                  "paths": ["tests/unit/smoke.test.ts"]}})
    check("af9 a listing verified on another version is not trusted - it widens "
          "with both answers named: %r" % (stale["widen"],),
          stale["suites"] == [] and "vitest/3.2.4" in (stale["widen"] or "")
          and "vitest/4.0.0" in (stale["widen"] or ""))

    noversion = M.select(changed, _meta(listing={"related": LISTING}),
                         {"versionCheckFailed": True,
                          "related": {"command": command, "exit": 0,
                                      "paths": ["tests/unit/smoke.test.ts"]}})
    check("af10 a version command that failed is its own reason, never read as "
          "this machine answering None: %r" % (noversion["widen"],),
          noversion["suites"] == []
          and "version command failed" in (noversion["widen"] or ""))

    e2e_failed = M.select(["lib/a.ts"], _meta(listing={
        "e2eChanged": "pnpm playwright test --list --only-changed {paths}"}),
        {"versionAnswer": "vitest/3.2.4",
         "e2eChanged": {"command": "x", "exit": 1, "paths": []}})
    check("af11 the e2e runner's changed listing widens the same way when it "
          "exits non-zero: %r" % (e2e_failed["widen"],),
          e2e_failed["suites"] == [] and "exited 1" in (e2e_failed["widen"] or ""))

    # --- e2e specs nothing can see -------------------------------------------
    tree = ["e2e/i18n.spec.ts", "e2e/nav.spec.ts", "tests/unit/smoke.test.ts",
            "app/[locale]/page.tsx"]
    wide = M.select(["components/Team.tsx"], {}, {"suites": tree})
    got = sorted(p for p, arm in _suites(wide) if arm == "e2e-widening")
    check("af12 a task changing app source in a project with e2e specs and no "
          "listing that sees them selects EVERY e2e spec, each with the "
          "widening basis: %r" % (wide,),
          wide["widen"] is None
          and got == ["e2e/i18n.spec.ts", "e2e/nav.spec.ts"]
          and all("components/Team.tsx" in s["basis"]
                  and "no recorded listing" in s["basis"]
                  for s in wide["suites"]))

    seen = M.select(["components/Team.tsx"], _meta(listing={
        "e2eChanged": "pnpm playwright test --list --only-changed {paths}"}),
        {"versionAnswer": "vitest/3.2.4", "suites": tree,
         "e2eChanged": {"command": "x", "exit": 0,
                        "paths": ["e2e/nav.spec.ts"]}})
    check("af13 ...and with a recorded e2e listing that answered, only the specs "
          "it named run, under that arm: %r" % (_suites(seen),),
          _suites(seen) == [("e2e/nav.spec.ts", "e2e-changed")])

    docs = M.select(["README.md"], {}, {"suites": tree})
    check("af14 a change to documentation alone selects no e2e spec - prose is "
          "not app source: %r" % (docs,),
          docs["suites"] == [] and docs["widen"] is None)

    # --- what the task already runs --------------------------------------------
    # The two selections differ only in meta.coupling, whose entry names a test
    # nothing else selects: a reader of the key would add it, so equality and the
    # absence of that test are what separate "ignored" from "read".
    coupling = [{"test": "tests/unit/cart.test.ts", "sources": ["lib/store.ts"]}]
    plain = M.select(["lib/store.ts"], _meta(), {})
    coupled = M.select(["lib/store.ts"], _meta(coupling=coupling), {})
    check("af15 a manifest carrying meta.coupling selects exactly what the same "
          "manifest without it selects; no arm named coupling appears in the "
          "selection's basis",
          coupled == plain and plain["suites"] == []
          and "tests/unit/cart.test.ts" not in repr(coupled)
          and "coupling" not in repr(coupled).replace("meta.coupling", "")
          and "coupling" not in M.ARMS)

    own = M.select(["pkg/core.py"], {}, {"pySources": sources},
                   exclude=["tests/test_direct.py"])
    check("af16 a suite the task's own gate already names is not added twice: %r"
          % (_suites(own),),
          "tests/test_direct.py" not in [p for p, _a in _suites(own)]
          and "tests/test_transitive.py" in [p for p, _a in _suites(own)])

    check("af17 a task whose gate already carries every phase-gate entry is "
          "already wide, and one missing an entry is not",
          M.already_wide(["lint", "test", "e2e"], ["test", "e2e"])
          and not M.already_wide(["lint", "sh tests/a.sh"], ["test", "e2e"])
          and not M.already_wide(["lint"], []))

    nothing = M.select([], _meta(listing={"related": LISTING}), {})
    check("af18 no changed path selects nothing and widens nothing, and says so: "
          "%r" % (nothing,),
          nothing["suites"] == [] and nothing["widen"] is None
          and nothing["lines"])

    # --- turning suites into commands ------------------------------------------
    phase = {"id": "P1", "tasks": [
        {"id": "P1.1", "tests": {"gate": ["lint", "sh tests/own_test.sh"]}}]}
    picked = [{"path": "tests/smoke_test.sh", "arm": "related", "basis": "b"},
              {"path": "tests/x_test.sh", "arm": "python", "basis": "c"}]
    steps, why = M.entries_for(picked, phase, {"buildCommands": {"lint": "true"}},
                               ".")
    check("af19 each arm becomes its own step in the sibling's spelling, named "
          "for the arm and the suites it carries, and the shared key is not "
          "copied through: %r" % (steps,),
          why is None and steps == [
              ("affected/related: tests/smoke_test.sh", "sh tests/smoke_test.sh"),
              ("affected/python: tests/x_test.sh", "sh tests/x_test.sh")])

    spelled, why = M.entries_for(picked[:1], {"id": "P1", "tasks": []},
                                 {"phaseGate": {"derived": {
                                     "spelling": "pytest -q {paths}"}}}, ".")
    check("af20 with no sibling, meta.phaseGate.derived.spelling is filled in: %r"
          % (spelled,),
          why is None and spelled == [
              ("affected/related: tests/smoke_test.sh",
               "pytest -q tests/smoke_test.sh")])

    none, why = M.entries_for(picked, {"id": "P1", "tasks": []}, {}, ".")
    check("af21 no spelling to run them under WIDENS, with the reason: %r"
          % (why,),
          none == [] and why is not None and "phase gate" in why)

    # --- a declared entry that already runs what a step would add -------------
    # The dogfood shape: a shared key whose command is the selection's own
    # spelling with no path in it, which runs every suite that spelling runs.
    sweep = "python3 tools/sweep.py"
    swept = {"buildCommands": {"selftests": sweep, "lint": "ruff check ."},
             "phaseGate": {"derived": {"spelling": sweep + " {paths}"}}}
    chosen = [{"path": "tests/test_other.py", "arm": "related", "basis": "r"},
              {"path": "tests/test_core.py", "arm": "python", "basis": "p"}]
    sweep_steps, why = M.entries_for(chosen, {"id": "P1", "tasks": []}, swept,
                                     ".")
    kept, left, said = M.left_to_run(sweep_steps, chosen, ["selftests", "lint"],
                                     swept["buildCommands"])
    check("af22 a task gate holding a key whose command is the unscoped sweep is "
          "already wide for the Python arm: no affected/python or "
          "affected/related step is added, and each one left out is said, "
          "naming the key that runs it: %r" % ((sweep_steps, kept, left, said),),
          why is None and len(sweep_steps) == 2 and kept == [] and left == []
          and len(said) == 2
          and all("selftests" in ln and sweep in ln for ln in said)
          and any("tests/test_other.py" in ln for ln in said)
          and any("tests/test_core.py" in ln for ln in said))
    # The other direction: an "always drop" or "drop on any shared key" version
    # passes af22. A path-scoped call of the same runner, the same runner with
    # an option, and an unrelated key each leave the steps where they were.
    narrow = dict(swept["buildCommands"], fast=sweep + " --fast")
    for gate in (["python3 tools/sweep.py tests/test_own.py", "lint"],
                 ["fast"], ["lint"]):
        kept, left, said = M.left_to_run(sweep_steps, chosen, gate, narrow)
        check("af23 a declared gate that is not the unscoped spelling (%r) "
              "keeps every affected step and says nothing about one: %r"
              % (gate, (kept, said)),
              kept == sweep_steps and left == chosen and said == [])

    # --- a path no arm reads ----------------------------------------------------
    odd = M.select(["assets/logo.svg"], {}, {})
    check("af24 a changed path no arm reads (no listing, not Python, not prose, "
          "no e2e spec to widen to) WIDENS to the phase gate and names the "
          "path, never an empty selection read as 'nothing affected': %r"
          % (odd,),
          odd["suites"] == [] and odd["widen"] is not None
          and "assets/logo.svg" in odd["widen"] and "phase gate" in odd["widen"]
          and any(odd["widen"] in ln for ln in odd["lines"]))
    mixed = M.select(["pkg/core.py", "assets/logo.svg"], {},
                     {"pySources": sources})
    check("af24b ...and a Python change beside it does not hide it: %r"
          % (mixed["widen"],),
          mixed["suites"] == [] and "assets/logo.svg" in (mixed["widen"] or "")
          and "pkg/core.py" not in (mixed["widen"] or ""))
    # The other direction: an "always widen" version passes af24. A listing
    # that answered for the path read it, and so did the graph and prose.
    answered = M.select(["assets/logo.svg"], _meta(listing={"related": LISTING}),
                        {"versionAnswer": "vitest/3.2.4",
                         "related": {"command": "x", "exit": 0, "paths": []}})
    read = [M.select(["pkg/core.py"], {}, {"pySources": sources}),
            M.select(["README.md"], {}, {}),
            M.select(["tests/own_test.sh"], {}, {},
                     exclude=["tests/own_test.sh"])]
    # The measured miss: a change to the suite harness turned the harness's own
    # run red, and the listing - which answered, naming its importers - did not
    # name the harness itself.
    harnessed = {"tests/_harness.py": "X = 1\n",
                 "tests/test_a.py": "import _harness\n"}
    helper = M.select(["tests/_harness.py"], _meta(listing={"related": LISTING}),
                      {"versionAnswer": "vitest/3.2.4", "pySources": harnessed,
                       "related": {"command": "x", "exit": 0,
                                   "paths": ["tests/test_a.py"]}})
    spec = M.select(["e2e/nav.spec.ts"], {}, {"suites": tree})
    check("af26 a changed suite path no arm selected (test support such as the "
          "harness, or a spec nothing listed) WIDENS to the phase gate naming "
          "it - a listing that answered for it is not enough: %r / %r"
          % (helper["widen"], spec["widen"]),
          helper["suites"] == [] and "tests/_harness.py" in (helper["widen"] or "")
          and "phase gate" in (helper["widen"] or "")
          and "e2e/nav.spec.ts" in (spec["widen"] or ""))
    # The other direction: a changed suite the listing named, or the graph
    # reached as itself, is selected and widens nothing.
    named = M.select(["tests/test_a.py"], _meta(listing={"related": LISTING}),
                     {"versionAnswer": "vitest/3.2.4", "pySources": harnessed,
                      "related": {"command": "x", "exit": 0,
                                  "paths": ["tests/test_a.py"]}})
    itself = M.select(["tests/test_direct.py"], {}, {"pySources": sources})
    check("af26b ...and a changed suite an arm selected does not widen: %r / %r"
          % (named["widen"], itself["widen"]),
          named["widen"] is None and _suites(named) == [("tests/test_a.py",
                                                         "related")]
          and itself["widen"] is None
          and ("tests/test_direct.py", "python") in _suites(itself))
    check("af25 a path the related listing answered for, a .py path the graph "
          "read, prose, and a suite the task's own gate runs do NOT widen: %r"
          % ([answered["widen"]] + [r["widen"] for r in read],),
          answered["widen"] is None and all(r["widen"] is None for r in read))

    _walk_cases(check)
    _support_cases(check)
    _dogfood_cases(check)

    # ARMS carries machine ids, not human labels, so the guide's wording for
    # each id is mapped here; an arm with no entry fails by name rather than
    # being skipped, and a guide phrase with no arm behind it fails too.
    labels = {"related": "related listing", "python": "Python imports",
              "walk": "tree walks", "e2e-changed": "e2e listing",
              "e2e-widening": "e2e widening"}
    unmapped = [a for a in M.ARMS if a not in labels]
    guide_path = os.path.join(_output.REPO_ROOT, "PLUGIN-BUILD-GUIDE.md")
    with open(guide_path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines()
                 if ln.lstrip().startswith("_affected_tests.py ")]
    found = re.search(r"by arm \(([^)]*)\)", lines[0]) if len(lines) == 1 else None
    documented = [x.strip() for x in found.group(1).split(",")] if found else None
    wanted = [labels.get(a, a) for a in M.ARMS]
    check("the build guide's tree line for _affected_tests names exactly "
          "the arms ARMS holds, so a removed arm cannot stay documented "
          "(tree lines %d, documented %r, ARMS %r, unmapped %r)"
          % (len(lines), documented, wanted, unmapped),
          not unmapped and documented == wanted)


# A lint is a runner whose cases walk a directory and read every file under it,
# so a suite edited under that directory can turn it red without being named by
# any import. The fixture's walks reach their directory every way the real
# lints do: through a shared walk in another module, handed a constant anchored
# on that module's own file; through a local function whose parameter is the
# walked directory; and through a lint module whose function walks a fixed root.
_WALK_SOURCES = {
    "scripts/_out.py": (
        "import os\n"
        "HERE = os.path.dirname(os.path.abspath(__file__))\n"
        "ROOT = os.path.dirname(HERE)\n"
        "TESTS = os.path.join(ROOT, 'tests')\n"
        "SRC = os.path.join(ROOT, 'scripts')\n"
        "def files(directory):\n"
        "    found = []\n"
        "    for top, _dirs, names in os.walk(directory):\n"
        "        found.extend(names)\n"
        "    return found\n"),
    "tools/lints/_lint.py": (  # refs: fixture
        "import _out\n"
        "def everything():\n"
        "    return _out.files(_out.ROOT)\n"),
    # tools/_suite.py's own shape: a removal lint over TESTS_DIR, reached
    # through a parameter, with a fallback spelled as a conditional. The
    # fallback walks scripts/, so only the parameter route reaches tests/.
    "tools/_suite.py": (
        "import os\n"
        "import _out\n"
        "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
        "TESTS_DIR = os.path.join(os.path.dirname(_HERE), 'tests')\n"
        "def removals(root=None):\n"
        "    top = root if root is not None else _out.SRC\n"
        "    return [n for n in _out.files(top)]\n"
        "def _cases(check):\n"
        "    check('s1', removals(TESTS_DIR) == [])\n"),
    # tools/lints/_refs.py's shape: a table of surfaces, each joined onto a
    # root handed in, the separator swapped for the platform's, and walked.
    "tools/lints/_surf.py": (  # refs: fixture
        "import os\n"
        "import _out\n"
        "SURFACES = (('docs', 1), ('tests', 2))\n"
        "def _surface_files(root, surface):\n"
        "    path = os.path.join(root, surface.replace('/', os.sep))\n"
        "    return [n for _t, _d, n in os.walk(path)]\n"
        "def scanned(root=None):\n"
        "    top = root if root is not None else _out.ROOT\n"
        "    found = []\n"
        "    for surface, _mode in SURFACES:\n"
        "        found.extend(_surface_files(top, surface))\n"
        "    return found\n"),
    "tests/test_surf.py": (
        "import _surf\n"
        "def _cases(check):\n"
        "    check('r1', _surf.scanned() == [])\n"),
    "tools/_other.py": (
        "import _out\n"
        "def _cases(check):\n"
        "    check('o1', _out.files(_out.SRC) == [])\n"),
    # Walks a scratch directory and a directory read off a bare file name, and
    # holds the word `tests` in a literal: none of the three is the tree.
    "tests/test_tmp.py": (
        "import os, tempfile\n"
        "WHERE = 'tests'\n"
        "def _cases(check):\n"
        "    check('t1', os.listdir(tempfile.mkdtemp()) == [])\n"
        "    check('t2', os.listdir(os.path.dirname('plan.json')) != [])\n"),
    "tests/test_lint.py": (
        "import _lint\n"
        "def _cases(check):\n"
        "    check('l1', _lint.everything() == [])\n"),
    "tests/test_x.py": "pass\n",
    "e2e/a.spec.ts": "",
}
_WALK_RUNNERS = ["e2e/a.spec.ts", "tests/test_lint.py", "tests/test_surf.py",
                 "tests/test_tmp.py", "tests/test_x.py", "tools/_other.py",
                 "tools/_suite.py"]


def _walk_facts(**extra):
    facts = {"versionAnswer": "vitest/3.2.4",
             "pySources": dict((k, v) for k, v in _WALK_SOURCES.items()
                               if k.endswith(".py")),
             "all": {"command": "list-all", "exit": 0,
                     "paths": list(_WALK_RUNNERS)}}
    facts.update(extra)
    return facts


def _walk_cases(check):
    """A task editing a suite gets every runner whose walk covers it."""
    meta = _meta(listing={"all": "list-all"})
    res = M.select(["tests/test_x.py"], meta, _walk_facts(),
                   exclude=["tests/test_x.py"])
    walked = [(s["path"], s["basis"]) for s in res["suites"]
              if s["arm"] == "walk"]
    check("af30 A TASK EDITING A SUITE GETS EVERY LINT WHOSE WALK COVERS IT: a "
          "change to tests/test_x.py, which the task's own gate already runs, "
          "selects tools/_suite.py (a removal lint over tests/, reached through "
          "a parameter), tests/test_lint.py (a lint module walking the whole "
          "tree) and tests/test_surf.py (a table of surfaces joined onto a root "
          "handed in) under the walk arm, each basis naming the directory "
          "walked and the edited suite - and neither the runner walking only "
          "scripts/ nor the one walking a scratch directory: %r / widen %r"
          % (walked, res["widen"]),
          res["widen"] is None
          and [p for p, _b in walked] == ["tests/test_lint.py",
                                          "tests/test_surf.py",
                                          "tools/_suite.py"]
          and all("tests/test_x.py" in b for _p, b in walked)
          and "walk tests, which holds" in dict(walked)["tools/_suite.py"]
          and "the project root" in dict(walked)["tests/test_lint.py"])
    # The other direction: a version that walked every runner would pass af30
    # on the whole-tree lint alone. A suite outside tests/ is walked by the
    # whole-tree lint and NOT by the removal lint over tests/.
    spec = M.select(["e2e/a.spec.ts"], meta, _walk_facts(),
                    exclude=["e2e/a.spec.ts"])
    check("af31 ...and the walk read is the directory, not the runner: a spec "
          "outside tests/ selects the whole-tree lint and not the lint over "
          "tests/; a change to app source selects no walker at all: %r / %r"
          % (_suites(spec),
             _suites(M.select(["scripts/_out.py"], meta, _walk_facts()))),
          [p for p, arm in _suites(spec) if arm == "walk"]
          == ["tests/test_lint.py"]
          and not [p for p, arm in _suites(M.select(["scripts/_out.py"], meta,
                                                     _walk_facts()))
                   if arm == "walk"])
    runs = M.gate_runs(["python3 tools/_suite.py tests/test_x.py",
                        "python3 tests/test_lint.py --selftest", "lint",
                        "python3 a.py && python3 tools/_other.py tests/test_tmp.py"])
    check("af37 what a task's gate runs is the suites its entries hand their "
          "program, and a path an entry runs alone - never the program a "
          "path-scoped call names, whose own cases that call does not run: %r"
          % (runs,),
          runs == ["tests/test_x.py", "tests/test_lint.py", "a.py",
                   "tests/test_tmp.py"])
    failed = M.select(["tests/test_x.py"], meta,
                      _walk_facts(all={"command": "list-all", "exit": 3,
                                       "paths": []}),
                      exclude=["tests/test_x.py"])
    check("af32 a recorded all-runners listing that could not answer widens, "
          "naming it - a walker it would have named is not silently dropped: "
          "%r" % (failed["widen"],),
          failed["suites"] == [] and "exited 3" in (failed["widen"] or "")
          and "walk" in (failed["widen"] or ""))


def _support_cases(check):
    """A test-support change is covered by a declared unscoped sweep."""
    sweep = "python3 tools/sweep.py"
    meta = {"buildCommands": {"selftests": sweep, "lint": "ruff check .",
                              "fast": sweep + " --fast"},
            "phaseGate": {"derived": {"spelling": sweep + " {paths}"}}}
    phase = {"id": "P1", "tasks": []}
    facts = {"pySources": {"tests/_harness.py": "X = 1\n",
                           "tests/test_a.py": "import os\n"}}
    info = M.select(["tests/_harness.py"], meta, facts)
    steps, settled = M.steps_for(info, phase, meta, ".", ["selftests"])
    check("af33 GATE [selftests] WITH ONLY tests/_harness.py CHANGED ADDS NO "
          "PHASE-GATE STEP and names the covering key: the support widening "
          "is satisfied by the declared entry whose command is the spelling "
          "with its paths taken out - the same word comparison left_to_run "
          "makes: widen before %r, steps %r, widen after %r, lines %r"
          % (info["widen"], steps, settled["widen"], settled["lines"]),
          info["widen"] is not None and steps == []
          and settled["widen"] is None
          and any("selftests" in ln and "tests/_harness.py" in ln
                  and sweep in ln for ln in settled["lines"]))
    # The other direction: a version that read any declared key, or any call
    # of the same runner, as covering would pass af33.
    for gate in (["python3 tools/sweep.py tests/test_own.py"], ["fast"],
                 ["lint"]):
        steps, kept = M.steps_for(info, phase, meta, ".", gate)
        check("af34 a narrow path-scoped gate, the same runner with an "
              "option, and an unrelated key (%r) with the same change STILL "
              "WIDEN to the phase gate: steps %r widen %r"
              % (gate, steps, kept["widen"]),
              steps == [] and kept["widen"] == info["widen"])
    # A support change beside a selected suite: the covering sweep runs that
    # suite too, so nothing joins, and each step left out is said.
    both = M.select(["tests/_harness.py", "pkg/core.py"], meta,
                    {"pySources": dict(facts["pySources"], **{
                        "pkg/core.py": "X = 1\n",
                        "tests/test_core.py": "import pkg.core\n"})})
    steps, settled = M.steps_for(both, phase, meta, ".", ["selftests"])
    check("af35 ...and a suite an arm selected beside the support change is "
          "run by the same covering entry, so no step joins and its line is "
          "said: steps %r widen %r lines %r"
          % (steps, settled["widen"], settled["lines"]),
          steps == [] and settled["widen"] is None
          and any("tests/test_core.py" in ln and "selftests" in ln
                  for ln in settled["lines"]))


def _tool_module(name, filename):
    """A `tools/` script as a module, loaded by path: its name is no identifier."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_output.REPO_ROOT, "tools", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dogfood_cases(check):
    """THE ONE PLACE THIS SUITE READS THE REPOSITORY rather than hand-built facts.

    The claim is about this repository's configuration, not the module's logic:
    the related listing its plan records is what a task's gate reads, and the
    suites that walk the whole tree are left out of it because the phase gate
    runs them. Hand-built facts would say only what the fixture was written to
    say, so the listing is asked of `tools/affected.py` itself and the phase gate
    is read off the plan."""
    import contextlib
    import io
    import _manifest_io

    plan = _manifest_io.load_manifest(
        os.path.join(_output.REPO_ROOT, "docs", "audit", "audit-plan.json"))
    meta = plan.get("meta") or {}
    derived = (meta.get("phaseGate") or {}).get("derived") or {}
    template = M.listing_templates(meta).get("related") or ""
    selector = _tool_module("dogfood_affected", "affected.py")
    leaf = "plugins/audit/scripts/governance/record-outside-run.py"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        listed_exit = selector.main(["--list-related", leaf])
    listed = [ln.strip() for ln in out.getvalue().splitlines() if ln.strip()]
    graph = selector.reach_graph()
    scanners = graph["scanners"]
    scanner_suites = [s for s in scanners if s.startswith("tests/")]
    sources = {}
    for top in ("plugins", "tests", "tools", os.path.join(".claude", "hooks")):
        for rel, path in _output.py_files(os.path.join(_output.REPO_ROOT, top)):
            with open(path, encoding="utf-8", errors="replace") as fh:
                sources["%s/%s" % (top.replace(os.sep, "/"), rel)] = fh.read()
    facts = {"versionAnswer": (derived.get("verifiedOn") or {}).get("answer"),
             "pySources": sources,
             "related": {"command": template.replace("{paths}", leaf),
                         "exit": listed_exit, "paths": listed}}
    res = M.select([leaf], meta, facts)
    picked = [s["path"] for s in res["suites"]]
    # A scanner that imports or runs the module is selected for that edge like
    # any other suite; the ones left are those only the blanket rule brought in,
    # and there must be some or the case could not tell the two rules apart.
    by_edge = set(selector.reached_by(graph, leaf)) | set(
        s["path"] for s in res["suites"] if s["arm"] == "python")
    blanket = sorted(set(scanner_suites) - by_edge)
    check("af27 FOR A CHANGED MODULE THE PER-TASK SELECTION EXCLUDES THE TREE "
          "SCANNERS (a changed SUITE is af36's): this plan's "
          "related listing for one changed module, read through select(), "
          "names the module's own suite and no suite that walks the whole tree "
          "unless it reaches the module by an edge. Blanket scanners selected %r "
          "of %d; selected %r; widen %r"
          % (sorted(set(picked) & set(blanket)), len(blanket), picked,
             res["widen"]),
          "tools/affected.py --list-related" in template and listed_exit == 0
          and blanket and res["widen"] is None
          and "tests/test_record_outside_run.py" in picked
          and not set(picked) & set(blanket))

    # A module the release hooks and the tools import: `--json` names gates
    # that are not `tests/` suites, and the per-task listing must carry every
    # one of them that is not a blanket scanner - the hook selftests are what
    # a task gate would otherwise never run.
    import json
    vocab = "plugins/audit/scripts/manifest/_manifest_vocab.py"
    hooks = [".claude/hooks/guard-release.py",
             ".claude/hooks/arm-release-bypass.py"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        vocab_exit = selector.main(["--list-related", vocab])
    vocab_listed = [ln.strip() for ln in out.getvalue().splitlines()
                    if ln.strip()]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        json_exit = selector.main(["--json", vocab])
    gates = json.loads(out.getvalue()).get("gates") or []
    # Only the gates that run a file's own cases: a command gate (the parity
    # check, vitest, a browser gate) is no path a listing can carry.
    gate_paths = sorted(set(g.split()[1] for g in gates
                            if len(g.split()) == 3 and g.split()[0] == "python3"
                            and g.split()[2] == "--selftest"))
    vocab_edge = set(selector.reached_by(graph, vocab))
    vocab_blanket = sorted(set(scanners) - vocab_edge)
    owed = [p for p in gate_paths if p not in vocab_blanket]
    vocab_res = M.select([vocab], meta, dict(facts, related={
        "command": template.replace("{paths}", vocab), "exit": vocab_exit,
        "paths": vocab_listed}))
    vocab_picked = [s["path"] for s in vocab_res["suites"]]
    steps, why = M.entries_for(vocab_res["suites"], {"id": "PX", "tasks": []},
                               meta, _output.REPO_ROOT)
    commands = " ".join(cmd for _, cmd in steps)
    check("af29 A TASK'S LISTING KEEPS THE HOOK AND TOOL GATES --json NAMES: "
          "for %s, --json names %r, the listing drops %r of the non-scanner "
          "gates %d, select() drops %r, the step commands lack %r; blanket "
          "scanners listed %r; exits %r/%r, widen %r, why %r"
          % (vocab, [g for g in gates if any(h in g for h in hooks)],
             [p for p in owed if p not in vocab_listed], len(owed),
             [p for p in owed if p not in vocab_picked],
             [h for h in hooks if h not in commands],
             sorted(set(vocab_listed) & set(vocab_blanket)), vocab_exit,
             json_exit, vocab_res["widen"], why),
          vocab_exit == 0 and json_exit == 0 and why is None
          and all(("python3 %s --selftest" % h) in gates for h in hooks)
          and all(h in owed for h in hooks)
          and all(p in vocab_listed for p in owed)
          and all(p in vocab_picked for p in owed)
          and all(h in commands for h in hooks)
          and not set(vocab_listed) & set(vocab_blanket)
          and vocab_res["widen"] is None)
    # The other direction, on af27's leaf, where scanners reach the module by
    # no edge: a listing that printed every runner path would pass af29, and
    # af27 counts only the scanner SUITES. This counts the scanner TOOLS too.
    leaf_blanket = set(scanners) - set(selector.reached_by(graph, leaf))
    blanket_tools = sorted(p for p in leaf_blanket if not p.startswith("tests/"))
    check("af29b ...AND NO BLANKET SCANNER, SUITE OR TOOL, JOINS IT: the listing "
          "for %s names none of the %d scanners that reach it by no edge "
          "(tools among them %r); listed %r"
          % (leaf, len(leaf_blanket), blanket_tools,
             sorted(set(listed) & leaf_blanket)),
          blanket_tools and not set(listed) & leaf_blanket)

    # The class that turned main red: a task gated on the one suite it edited,
    # and tools/_suite.py's removal lint over tests/ convicted that suite. The
    # runners come from this plan's own all-runners listing and the walks from
    # this tree's sources - nothing here names the lint but the assertion.
    edited = "tests/test_stamp_verification.py"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        all_exit = selector.main(["--list-all"])
    runners = [ln.strip() for ln in out.getvalue().splitlines() if ln.strip()]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        edited_exit = selector.main(["--list-related", edited])
    walk_res = M.select([edited], meta, dict(facts, related={
        "command": template.replace("{paths}", edited), "exit": edited_exit,
        "paths": [ln.strip() for ln in out.getvalue().splitlines()
                  if ln.strip()]}, all={
        "command": M.all_template(meta), "exit": all_exit, "paths": runners}),
        exclude=[edited])
    walkers = sorted(s["path"] for s in walk_res["suites"]
                     if s["arm"] == "walk")
    # A runner another arm selected first keeps that arm; it is selected all
    # the same, and its walk is asked of the reading directly. The reference
    # lint also lists the suites directory by a plain join, so `tests` alone
    # would stay green with its surfaces table unread; `tools` is a surface
    # reached only through that table, its separator swap and the join of two
    # parameters filled at the call - the reading this case is about.
    walk_index = M._walk_index(M._parsed(sources))
    refs_walk = sorted(M.runner_walks("tests/test__refs.py", walk_index))
    check("af36 THIS PLAN'S TASK EDITING A SUITE GETS tools/_suite.py: a change "
          "to %s, gated on that suite alone, selects the removal lint over "
          "tests/ and the reference lint's surfaces walk under the walk arm, and "
          "not tests/test__worktrees.py, whose walk is the scripts directory; "
          "all-runners listing exit %r over %d runners, walkers %r, selected "
          "%r, the reference lint walks %r, widen %r"
          % (edited, all_exit, len(runners), walkers,
             [(s["path"], s["arm"]) for s in walk_res["suites"]], refs_walk,
             walk_res["widen"]),
          all_exit == 0 and walk_res["widen"] is None
          and "tools/_suite.py" in walkers
          and "tests" in refs_walk and "tools" in refs_walk
          and "tests/test__refs.py" in [s["path"] for s in walk_res["suites"]]
          and "tests/test__worktrees.py" not in walkers)

    # The phase gate's half: every phase still to sign off carries an entry whose
    # command is the plan's own path-scoped spelling with the paths taken out - the
    # unscoped sweep - and that sweep runs every scanner, suite or tool.
    unscoped = [w for w in (M._words(derived.get("spelling")) or [])
                if w != "{paths}"]
    build = meta.get("buildCommands") or {}
    live = [p for p in plan.get("phases") or []
            if isinstance(p, dict) and p.get("status") not in _manifest_io.TERMINAL]
    without = [p.get("id") for p in live
               if not any(M._words(build.get(e, e)) == unscoped
                          for e in _manifest_io.gate_entries(p)[0])]
    swept = set(_tool_module("dogfood_sweep", "sweep-selftests.py")
                .sweep_files(_output.REPO_ROOT))
    check("af28 ...AND THE PHASE GATE KEEPS THEM: every phase still to sign off "
          "runs the unscoped sweep %r, and the sweep runs every scanner. Phases "
          "without it %r of %d; scanners not swept %r"
          % (" ".join(unscoped), without, len(live),
             sorted(set(scanners) - swept)),
          unscoped and live and not without and scanners
          and set(scanners) <= swept)


def _gather_cases(check):
    """`af38`-`af42`: the one gathering of the facts `select` reads, and the
    runner under it. These are the cases that shell out: the subject is what a
    listing command does when it is run, so each one runs."""
    import shutil
    import subprocess
    import tempfile
    import time
    tree = tempfile.mkdtemp(prefix="affected-gather-")
    try:
        if hasattr(os, "killpg"):
            pid_file = os.path.join(tree, "grandchild.pid")
            started = time.time()
            # Quoted: a temp directory with a space in it otherwise sends the
            # pid to another file and leaves the case nothing to look for.
            res = M.run_listing(tree, {}, "sleep 30 & echo $! > %s; wait"
                                % (shlex.quote(pid_file),), 1)
            took = time.time() - started
            try:
                with open(pid_file) as fh:
                    grandchild = int(fh.read().strip())
            except (OSError, ValueError):
                grandchild = None
            # Judged by the product's liveness rule through the one deadline
            # helper: a `ps` of this suite's own would raise where a sandbox
            # refuses it, and the orphaned grandchild is reaped by init, so the
            # pid it leaves reads gone without the state letter.
            alive = (grandchild is not None
                     and not _harness.gone_within(grandchild, 5))
            check("af38 a listing that outlives its bound is torn down WHOLE: "
                  "the grandchild it started in the background is gone, the "
                  "answer is no exit 0, and the wait ended near the bound "
                  "rather than at the grandchild's end: %r"
                  % ((res, grandchild, alive, round(took, 1)),),
                  grandchild is not None and not alive
                  and res.get("exit") not in (0, None) and took < 20)
        else:
            _harness.skip(check, "af38 a timed-out listing torn down whole",
                          "posix", "no process groups on this platform")

        res = M.run_listing(tree, {"nodePreamble": "PRE=said"},
                            "printf '%s\\n' \"$PRE\"; echo err >&2; exit 3", 10)
        check("af39 a listing runs the way a plan command runs: the plan's "
              "node preamble in front, stderr folded into the output, and its "
              "own exit kept: %r" % (res,),
              res.get("exit") == 3
              and sorted(res.get("output", "").split()) == ["err", "said"])

        for rel in ("tests/test_a.py", "src/a.py", "docs/a.md"):
            path = os.path.join(tree, *rel.split("/"))
            if not os.path.isdir(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            with open(path, "w") as fh:
                fh.write("import a\n" if rel.endswith(".py") else "# a\n")
        # A checkout, so the gathering's own file list is git's answer: the
        # fresh gathering below is handed no list and reads the tree itself.
        subprocess.run(["git", "init", "-q", tree], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        meta = {"phaseGate": {"derived": {
            "listing": {"related": "printf '%s\\n' tests/test_a.py # {paths}"},
            "verifiedOn": {"command": "echo v1", "answer": "v1"}}}}
        heard = []
        real = M.run_listing

        def counted(project, meta_, command, timeout):
            heard.append(command)
            return real(project, meta_, command, timeout)
        M.run_listing = counted
        try:
            seen = {"files": ["tests/test_a.py", "src/a.py", "docs/a.md"]}
            first = M.gather_facts(tree, meta, ["docs/a.md"], seen=seen,
                                   sources=False)
            again = M.gather_facts(tree, meta, ["docs/a.md"], seen=seen)
            fresh = M.gather_facts(tree, meta, ["src/a.py"])
        finally:
            M.run_listing = real
        check("af40 one `seen` asks each command once: two gatherings of one "
              "path ran the version command and its listing a single time, "
              "and a fresh gathering asks again: %r" % (heard,),
              heard.count("echo v1") == 2
              and len([c for c in heard if "docs/a.md" in c]) == 1
              and len([c for c in heard if "src/a.py" in c]) == 1)
        check("af41 the facts are the ones `select` reads: the listing's "
              "paths, the tree's suites off the file list a caller handed in, "
              "the version answer, and Python sources only for a Python "
              "change: %r" % ((first, sorted(fresh)),),
              (first.get("related") or {}).get("paths") == ["tests/test_a.py"]
              and first.get("suites") == ["tests/test_a.py"]
              and first.get("versionAnswer") == "v1"
              and "pySources" not in first and "pySources" not in again
              and "src/a.py" in (fresh.get("pySources") or {})
              and M.select(["src/a.py"], meta, fresh)["widen"] is None)

        seen = {"files": []}
        M.run_listing = counted
        del heard[:]
        try:
            M.prefetch_listings(tree, meta, ["docs/a.md", "src/a.py"], seen)
            M.gather_facts(tree, meta, ["docs/a.md"], seen=seen, sources=False)
        finally:
            M.run_listing = real
        check("af42 a prefetch runs each path's listing into `seen`, and the "
              "gathering after it reads them rather than running them again: "
              "%r" % (heard,),
              len([c for c in heard if "docs/a.md" in c]) == 1
              and len([c for c in heard if "src/a.py" in c]) == 1
              and sorted(seen.get("listings") or {}) == sorted(
                  c for c in heard if "{" not in c and "echo v1" != c))
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def _pids_in(path):
    """The pids one per line in `path`, or [] while it is not written yet."""
    try:
        with open(path) as fh:
            return [int(ln) for ln in fh.read().split() if ln.strip().isdigit()]
    except OSError:
        return []


def _interrupt_cases(check):
    """`af43`: an interrupt landing while a prefetch waits on its listings.
    Every listing runs in a session of its own, so the interrupt the terminal
    sends the caller's group never reaches one; the prefetch is what has to stop
    them. Each listing starts a background grandchild that would outlive a
    teardown of the shell alone, and a slow one, so a prefetch that waited the
    listings out reads as a late return rather than as a pass."""
    if not hasattr(os, "killpg"):
        _harness.skip(check, "af43 an interrupted prefetch stops every listing",
                      "posix", "no process groups or SIGINT delivery here")
        return
    import shutil
    import signal
    import tempfile
    import threading
    import time
    tree = tempfile.mkdtemp(prefix="affected-interrupt-")
    pid_file = os.path.join(tree, "grandchildren.pid")
    paths = ["docs/a.md", "src/a.py"]
    meta = {"phaseGate": {"derived": {"listing": {
        "related": "sleep 6 & echo $! >> %s; wait # {paths}"
                   % (shlex.quote(pid_file),)}}}}
    stop = threading.Event()

    def interrupt():
        # Sent once every listing has started its grandchild, so the case
        # judges a teardown of started groups and never a race with a start.
        deadline = time.time() + 5
        while not stop.is_set() and time.time() < deadline:
            if len(_pids_in(pid_file)) >= len(paths):
                break
            time.sleep(0.05)
        if not stop.is_set():
            os.kill(os.getpid(), signal.SIGINT)
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    sender = threading.Thread(target=interrupt)
    raised, took = None, None
    try:
        started = time.time()
        try:
            sender.start()
            M.prefetch_listings(tree, meta, paths, {"files": []})
        except KeyboardInterrupt:
            raised = "KeyboardInterrupt"
        took = time.time() - started
        stop.set()
        sender.join()
        pids = _pids_in(pid_file)
        # The product's liveness rule through the deadline helper, as af38
        # judges its grandchild; each pid is waited for in turn, so a survivor
        # is reported after its own bound rather than a shared one.
        alive = [p for p in pids if not _harness.gone_within(p, 2)]
        check("af43 an interrupt during a prefetch stops every listing it "
              "started - no grandchild survives it - and the call gives the "
              "interrupt back near when it landed rather than when the "
              "listings would have ended: %r"
              % ((raised, round(took, 1), pids, alive),),
              raised == "KeyboardInterrupt" and len(pids) == len(paths)
              and not alive and took < 4)
    except KeyboardInterrupt:
        stop.set()
        check("af43 an interrupt during a prefetch stops every listing it "
              "started: the interrupt landed outside the prefetch", False)
    finally:
        stop.set()
        if sender.is_alive():
            sender.join()
        signal.signal(signal.SIGINT, previous)
        for pid in _pids_in(pid_file):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(tree, ignore_errors=True)


def _selftest():
    def body(check):
        _cases(check)
        _gather_cases(check)
        _interrupt_cases(check)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__affected_tests.py --selftest\n")
    raise SystemExit(2)
