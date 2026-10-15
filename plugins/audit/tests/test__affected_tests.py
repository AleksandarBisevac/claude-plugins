#!/usr/bin/env python3
"""
The cases for `_affected_tests.py` -- which suites a task's change can break.

Every case builds its `facts` BY HAND: the module is pure, so a related
listing's answer, the Python sources and the tree's suite files are dicts and
strings here, never a subprocess or a checkout. `af`-prefixed cases.

The four headline cases are the four ways the selection has to be right: a
recorded listing naming the test a move broke (the testbed's own regression),
an import graph that reaches exactly the tests it should and no other, a
listing that could not answer widening to the phase gate rather than reading
as "nothing affected", and e2e specs selected wholesale when nothing recorded
can say which of them a source change reaches.
"""

import os
import re
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

    # ARMS carries machine ids, not human labels, so the guide's wording for
    # each id is mapped here; an arm with no entry fails by name rather than
    # being skipped, and a guide phrase with no arm behind it fails too.
    labels = {"related": "related listing", "python": "Python imports",
              "e2e-changed": "e2e listing", "e2e-widening": "e2e widening"}
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__affected_tests.py --selftest\n")
    raise SystemExit(2)
