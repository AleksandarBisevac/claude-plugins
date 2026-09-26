#!/usr/bin/env python3
"""
The cases for `_gate_derive.py` -- the gate helpers' one home, and `derive()`.

`is_shared_key`/`path_scoped_sibling`/`repointed` moved here from
`audit-task.py` unchanged; `test_audit_task.py`'s own `tg`-prefixed cases still
drive them end to end through `add`/`scope`, so this file's cases for the three
are narrow: they exist to pin the identity `audit-task.py`'s aliases hold, not
to re-litigate behaviour a sibling suite already proves.

The bulk of this file is `derive()`: a phase's sign-off gate, computed from a
manifest, a phase and a `facts` dict this suite builds BY HAND -- no
subprocess, no git, no listing ever really run. `dg`-prefixed cases.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _gate_derive as M                           # noqa: E402


def _phase(**kw):
    p = {"id": "P1", "title": "P", "status": "pending", "tasks": []}
    p.update(kw)
    return p


def _task(tid, **kw):
    t = {"id": tid, "title": tid, "status": "pending"}
    t.update(kw)
    return t


def _manifest(meta=None, phase=None):
    m = {"meta": meta or {}, "phases": [phase] if phase else []}
    return m


# A sibling task whose OWN gate is path-scoped: every phase below needs one of
# these before `derive()` has any spelling to narrow through at all.
def _sibling(gate):
    return _task("P1.1", tests={"gate": gate, "gateBasis": "tests.add"})


# --- cases --------------------------------------------------------------------
def _cases(check):
    build = {"unit": "npm test -- ph.test.ts", "lint": "eslint ."}

    # --- the moved functions, pinned by identity rather than re-tested --------
    check("m1 `is_shared_key` reads the DECLARATION, not the shape",
          M.is_shared_key("unit", build) is True
          and M.is_shared_key("npm test -- x", build) is False)
    check("m2 `path_scoped_sibling` finds the first task carrying a "
          "path-scoped entry",
          M.path_scoped_sibling(
              _phase(tasks=[_task("P0.1", tests={"gate": ["lint"]}),
                            _sibling(["npm test -- ph.test.ts"])]),
              build)
          == (["npm test -- ph.test.ts"], "P1.1"))
    check("m3 `repointed` swaps the path and keeps the flags",
          M.repointed(["npm test -- ph.test.ts"], build, ["src/a.test.ts"])
          == ["npm test -- src/a.test.ts"])

    # --- mode absent: no derivation at all ------------------------------------
    no_mode = _manifest(meta={"buildCommands": build},
                        phase=_phase(tasks=[_sibling(["npm test -- ph.test.ts"])]))
    result = M.derive(no_mode, no_mode["phases"][0], {})
    check("dg0 `meta.phaseGate.mode` absent -> no derivation at all, the wide "
          "default is the whole answer: %r" % (result,),
          result["derived"] is False and result["narrowed"] is False
          and result["entries"] == ["unit", "lint"])

    # --- dg1: importers arm, DERIVED = FULL vs. a strict subset ---------------
    def _importers_manifest():
        return _manifest(
            meta={"buildCommands": build,
                 "phaseGate": {"mode": "shadow",
                               "derived": {"listing": {},
                                          "verifiedOn": {"command": "node -v",
                                                        "answer": "v20"}}}},
            phase=_phase(tasks=[_sibling(["npm test -- ph.test.ts"])]))

    full_manifest = _importers_manifest()
    full_facts = {"versionAnswer": "v20",
                 "listing": {"exit": 0, "paths": ["a.test.ts", "b.test.ts"]},
                 "fullListing": {"exit": 0, "paths": ["a.test.ts", "b.test.ts"]}}
    full_result = M.derive(full_manifest, full_manifest["phases"][0], full_facts)
    check("dg1 an importer listing EQUAL to the full listing means the wide "
          "gate IS the answer - 'DERIVED = FULL' is printed and nothing is "
          "narrowed (mutation: drop the subset comparison -> red): %r"
          % (full_result,),
          full_result["narrowed"] is False
          and "DERIVED = FULL" in full_result["lines"]
          and full_result["basis"] == "wide: importers resolved to the full suite"
          and full_result["entries"] == ["unit", "lint"])

    subset_manifest = _importers_manifest()
    subset_facts = {"versionAnswer": "v20",
                    "listing": {"exit": 0, "paths": ["a.test.ts"]},
                    "fullListing": {"exit": 0,
                                   "paths": ["a.test.ts", "b.test.ts"]}}
    subset_result = M.derive(subset_manifest, subset_manifest["phases"][0],
                             subset_facts)
    check("dg1-allow a STRICT subset keeps narrowed true and prints no "
          "'DERIVED = FULL' line - the union also carries the sibling's own "
          "narrowed path, `ph.test.ts`: %r" % (subset_result,),
          subset_result["narrowed"] is True
          and "DERIVED = FULL" not in subset_result["lines"]
          and subset_result["entries"]
          == ["npm test -- ph.test.ts a.test.ts"])

    # --- dg2: NEITHER fallback (no spelling, or nothing to narrow to) ever ---
    # returns an empty gate, and both respect `meta.phaseGate.exclude` the same
    # way `phase_gate_default` already does for a NEW phase's wide gate.
    no_spelling_exclude = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow", "exclude": ["lint"]}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": []})]))
    empty_result = M.derive(no_spelling_exclude, no_spelling_exclude["phases"][0], {})
    check("dg2 no path-scoped sibling AND `exclude` in play - falls back to "
          "the DEFAULT's non-always part (exclude respected), never an empty "
          "gate (mutation: return [] -> red; mutation: fall back to every "
          "buildCommands key, ignoring exclude -> red): %r" % (empty_result,),
          empty_result["entries"] == ["unit"]
          and empty_result["narrowed"] is False
          and empty_result["basis"] == "phase-no-spelling")

    always_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow", "always": ["lint"],
                          "exclude": ["lint"]}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": []})]))
    always_result = M.derive(always_manifest, always_manifest["phases"][0], {})
    check("dg2b ALWAYS IS ALWAYS even inside that fallback: a key in both "
          "`always` and `exclude` stays in, first (it is a declared always) "
          "with `unit` following as the default's other buildCommands key: "
          "%r" % (always_result,),
          always_result["entries"] == ["lint", "unit"])

    # --- dg4: the pinned boundary sentence -------------------------------------
    coupling_manifest = _manifest(
        meta={"buildCommands": build, "phaseGate": {"mode": "shadow"},
             "coupling": [{"test": "coupled.test.ts",
                          "sources": ["src/shared.ts"],
                          "basis": {"runId": "r1"}}]},
        phase=_phase(tasks=[
            _task("P1.1", files=["src/shared.ts"],
                 tests={"gate": ["npm test -- ph.test.ts"],
                       "gateBasis": "tests.add"})]))
    coupled_result = M.derive(coupling_manifest, coupling_manifest["phases"][0], {})
    check("dg4 a NARROWED basis always carries the pinned sentence naming its "
          "own ceiling - widen-only pin, so an over-claiming basis is caught: "
          "%r" % (coupled_result["basis"],),
          coupled_result["basis"] == "selected by import graph and recorded "
                                     "couplings only")
    miss_manifest = _manifest(
        meta={"buildCommands": build, "phaseGate": {"mode": "shadow"},
             "coupling": [{"test": "coupled.test.ts",
                          "sources": ["src/unrelated.ts"],
                          "basis": {"runId": "r1"}}]},
        phase=_phase(tasks=[
            _task("P1.1", files=["src/shared.ts"],
                 tests={"gate": ["npm test -- ph.test.ts"],
                       "gateBasis": "tests.add"})]))
    miss_result = M.derive(miss_manifest, miss_manifest["phases"][0], {})
    check("dg4b ...and a coupling whose sources MISS the phase's files adds "
          "nothing - a SUBSTRING check, not list membership: `repointed` "
          "joins every narrowed path into ONE entry, so 'coupled.test.ts' "
          "would never be a whole list ELEMENT even if the arm wrongly added "
          "it (mutation: drop the overlap check -> red): %r"
          % (miss_result["entries"],),
          not any("coupled.test.ts" in e for e in miss_result["entries"]))

    # --- dg10: smoke is never decided by appRootPath ---------------------------
    def _smoke_manifest(touched, exempt):
        return _manifest(
            meta={"buildCommands": build,
                 "phaseGate": {"mode": "shadow", "smoke": "e2e"},
                 "runtimeBoot": {"appRootPath": "apps/web"}},
            phase=_phase(tasks=[
                _task("P1.1", files=touched,
                     tests={"gate": ["npm test -- ph.test.ts"],
                           "gateBasis": "tests.add"})])), exempt

    outside_manifest, outside_exempt = _smoke_manifest(
        ["packages/ui/Button.tsx"], {})
    outside_result = M.derive(outside_manifest, outside_manifest["phases"][0],
                              {"exempt": outside_exempt})
    check("dg10 a real source file OUTSIDE the declared appRootPath still "
          "gets the smoke suite added - nothing here reads the prefix "
          "(mutation: decide by the prefix -> red): %r" % (outside_result,),
          "e2e" in outside_result["entries"]
          and not any("smoke: skipped" in l for l in outside_result["lines"]))

    docs_manifest, docs_exempt = _smoke_manifest(
        ["docs/readme.md"], {"docs/readme.md": True})
    docs_result = M.derive(docs_manifest, docs_manifest["phases"][0],
                           {"exempt": docs_exempt})
    check("dg10-allow a docs-and-tests-only phase skips the smoke suite with "
          "the line: %r" % (docs_result,),
          "e2e" not in docs_result["entries"]
          and any("smoke: skipped" in l for l in docs_result["lines"]))

    # dg10 alone only catches a prefix rule that skips smoke for files OUTSIDE
    # appRootPath; a rule that (wrongly) skips smoke for files INSIDE it reads
    # the SAME fixture as "not outside" and would slip past dg10 unnoticed.
    # This fixture is inside `apps/web` and is neither exempt nor a test file,
    # so the correct answer is still to ADD the smoke suite - catching the
    # OTHER prefix direction.
    inside_manifest, inside_exempt = _smoke_manifest(
        ["apps/web/pages/index.tsx"], {})
    inside_result = M.derive(inside_manifest, inside_manifest["phases"][0],
                             {"exempt": inside_exempt})
    check("dg10b ...and a real source file INSIDE the declared appRootPath "
          "still gets the smoke suite added, for the SAME reason - not "
          "exempt and not a test - catching the prefix rule's OTHER "
          "direction (mutation: skip smoke when every touched file is "
          "inside appRootPath -> red): %r" % (inside_result,),
          "e2e" in inside_result["entries"]
          and not any("smoke: skipped" in l for l in inside_result["lines"]))

    # --- dg23: the importer listing's version must match this machine's ------
    stale_manifest = _importers_manifest()
    stale_facts = {"versionAnswer": "v21",
                  "listing": {"exit": 0, "paths": ["a.test.ts"]},
                  "fullListing": {"exit": 0,
                                 "paths": ["a.test.ts", "b.test.ts"]}}
    stale_result = M.derive(stale_manifest, stale_manifest["phases"][0],
                            stale_facts)
    check("dg23 a version answer that does NOT match `verifiedOn.answer` "
          "skips the importers arm with the reason, and the OTHER arms still "
          "narrow around the sibling's own path (mutation: ignore the "
          "version -> red): %r" % (stale_result,),
          any("listing verified on v20, this machine answers v21" in l
              for l in stale_result["lines"])
          and stale_result["entries"] == ["npm test -- ph.test.ts"])

    match_manifest = _importers_manifest()
    match_facts = {"versionAnswer": "v20",
                  "listing": {"exit": 0, "paths": ["a.test.ts"]},
                  "fullListing": {"exit": 0,
                                 "paths": ["a.test.ts", "b.test.ts"]}}
    match_result = M.derive(match_manifest, match_manifest["phases"][0],
                            match_facts)
    check("dg23-allow a MATCHING version answer uses the arm, adding the "
          "importer path beside the sibling's own: %r" % (match_result,),
          match_result["entries"] == ["npm test -- ph.test.ts a.test.ts"])

    # --- no path-scoped sibling at all -----------------------------------------
    no_spelling = _manifest(
        meta={"buildCommands": build, "phaseGate": {"mode": "shadow"}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    no_spelling_result = M.derive(no_spelling, no_spelling["phases"][0], {})
    check("dg6 no sibling task declares a path-scoped gate entry - always "
          "plus the default's non-always part, basis phase-no-spelling: %r"
          % (no_spelling_result,),
          no_spelling_result["basis"] == "phase-no-spelling"
          and no_spelling_result["entries"] == ["unit", "lint"]
          and no_spelling_result["narrowed"] is False)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__gate_derive.py --selftest\n")
    raise SystemExit(2)
