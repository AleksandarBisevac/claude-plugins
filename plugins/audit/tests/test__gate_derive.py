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

import os
import shlex
import subprocess
import sys
import tempfile

import _harness                                   # sets sys.path for scripts/ + hooks/
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


# --- re-pointed paths are quoted for the shell the gate runs in ---------------
# `run-test-gate.py` hands every gate entry to a POSIX shell, so a path the
# re-point substitutes is one shell word only if it is quoted as one. Each
# fixture path below is chosen so the unquoted join and the quoted one differ.
def _shell_words(command):
    """The words a POSIX shell reads out of `command`, or None when an
    unbalanced quote leaves it unreadable -- an entry the shell would refuse
    must fail its case, not end the suite before the cases after it run."""
    try:
        return shlex.split(command)
    except ValueError:
        return None


def _quoting_cases(check, build):
    spaced = M.repointed(["python3 tests/test_a.py"], build,
                         ["backend/tests/test old.py"])
    check("q1 a path with a SPACE is substituted as ONE shell word: %r"
          % (spaced,),
          spaced == ["python3 'backend/tests/test old.py'"]
          and _shell_words(spaced[0]) == ["python3", "backend/tests/test old.py"])

    apostrophe = "tests/it" + "'" + "s.py"
    quoted = M.repointed(["python3 tests/test_a.py -v"], build, [apostrophe])
    check("q2 a path with a SINGLE QUOTE survives the shell's own reading: %r"
          % (quoted,),
          len(quoted) == 1
          and _shell_words(quoted[0]) == ["python3", apostrophe, "-v"])

    # The allow case: the direction a quote-everything mutation breaks. An
    # ordinary path, a flag, a `--` separator and a shared key all come back
    # byte for byte as the unquoted join has always written them.
    plain = M.repointed(["npm test -- --runInBand ph.test.ts", "lint",
                         "cd web && npx vitest run a.test.ts"], build,
                        ["src/a.test.ts", "src/b-c_d.test.ts"])
    check("q3 an ordinary path, its flags and a shared key are unchanged "
          "byte for byte: %r" % (plain,),
          plain == ["npm test -- --runInBand src/a.test.ts src/b-c_d.test.ts",
                    "lint",
                    "cd web && npx vitest run src/a.test.ts src/b-c_d.test.ts"])

    single = M.repointed(["python3 'tests/test old.py' -v"], build,
                         ["tests/b.py"])
    double = M.repointed(['pytest -k "a or b" "tests/x y.py"'], build,
                         ["tests/z w.py"])
    check("q4 a sibling that already QUOTES its path is re-pointed, never "
          "quoted twice, and its other quoted words keep their spelling: "
          "%r %r" % (single, double),
          single == ["python3 tests/b.py -v"]
          and double == ['pytest -k "a or b" \'tests/z w.py\''])

    quoted_only = ["python3 'tests/test old.py' -v"]
    picked = M.path_scoped_sibling(
        _phase(tasks=[_task("P0.1", tests={"gate": ["lint"]}),
                      _sibling(quoted_only)]), build)
    moved = M.repointed(picked[0] or [], build, ["tests/b c.py"])
    check("q6 a sibling whose ONLY path is quoted is picked as the shape, and "
          "re-points to a quoted path: %r -> %r" % (picked, moved),
          picked == (quoted_only, "P1.1")
          and moved == ["python3 'tests/b c.py' -v"])

    if not os.path.exists("/bin/sh"):
        _harness.skip(check, "q5", "no POSIX `/bin/sh` here, which is the "
                      "shell run-test-gate spawns elsewhere", True)
        return
    root = tempfile.mkdtemp(prefix="gate-derive-quote-")
    try:
        suite_dir = os.path.join(root, "backend", "tests")
        os.makedirs(suite_dir)
        marker = os.path.join(root, "ran.txt")
        with open(os.path.join(suite_dir, "test old.py"), "w") as fh:
            fh.write("open(%r, 'w').write('ran')\n" % (marker,))
        # The interpreter arrives through the environment rather than as a
        # literal: its own absolute path can end in a dotted version, which
        # reads as a file token and would itself be re-pointed.
        entry = M.repointed(['"$GATE_DERIVE_PY" tests/test_a.py'], build,
                            ["backend/tests/test old.py"])[0]
        env = dict(os.environ, GATE_DERIVE_PY=sys.executable)
        proc = subprocess.run(["/bin/sh", "-c", entry], cwd=root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        ran = os.path.isfile(marker)
        output = proc.stdout.decode("utf-8", "replace")
    finally:
        _harness.remove_tree(root)
    check("q5 the re-pointed entry RUNS from the project root through "
          "`/bin/sh -c`: exit %s, ran %s, output %r"
          % (proc.returncode, ran, output),
          proc.returncode == 0 and ran)


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
    _quoting_cases(check, build)

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

    # --- dg-empty (tests.add repro): an ALL listing that ran, exited 0 and --
    # named no suite turns the WHOLE derivation wide with basis derived-empty
    # and a printed reason, before any other arm runs - red at HEAD, where
    # `derive()`'s own docstring calls this basis unreachable and no branch
    # tests `facts["fullListing"]` at all.
    empty_manifest = _importers_manifest()
    empty_facts = {"versionAnswer": "v20",
                  "listing": {"exit": 0, "paths": []},
                  "fullListing": {"exit": 0, "paths": []}}
    empty_result = M.derive(empty_manifest, empty_manifest["phases"][0],
                            empty_facts)
    check("dg-empty an ALL listing that ran, exited 0 and named no suite "
          "widens with basis derived-empty and a printed reason (mutation: "
          "let it narrow instead -> red): %r" % (empty_result,),
          empty_result["narrowed"] is False
          and empty_result["basis"] == "derived-empty"
          and empty_result["entries"] == ["unit", "lint"]
          and any("derived-empty" in l for l in empty_result["lines"]))

    # --- dg-changed: changedSince adds only suite paths, drops non-suite -----
    changed_manifest = _manifest(
        meta={"buildCommands": build, "phaseGate": {"mode": "shadow"}},
        phase=_phase(tasks=[_sibling(["npm test -- ph.test.ts"])]))
    changed_facts = {"changedSince": ["src/other.test.ts", "src/plain.ts"]}
    changed_result = M.derive(changed_manifest, changed_manifest["phases"][0],
                              changed_facts)
    check("dg-changed a changedSince path that IS a suite file is added, one "
          "that is NOT is dropped (mutation: drop the is_suite_path filter -> "
          "red): %r" % (changed_result["entries"],),
          changed_result["entries"]
          == ["npm test -- ph.test.ts src/other.test.ts"])

    # --- dg-lastfailed: lastFailedSuites paths are added and DEDUPED ---------
    # against a path another arm already added.
    lastfailed_manifest = _manifest(
        meta={"buildCommands": build, "phaseGate": {"mode": "shadow"}},
        phase=_phase(tasks=[_sibling(["npm test -- ph.test.ts"])]))
    lastfailed_facts = {"changedSince": ["src/dup.test.ts"],
                       "lastFailedSuites": ["src/dup.test.ts", "src/new.test.ts"]}
    lastfailed_result = M.derive(lastfailed_manifest,
                                 lastfailed_manifest["phases"][0],
                                 lastfailed_facts)
    check("dg-lastfailed lastFailedSuites paths are added, deduped against an "
          "already-added changedSince path (mutation: drop the dedupe check "
          "-> red, `src/dup.test.ts` appearing twice): %r"
          % (lastfailed_result["entries"],),
          lastfailed_result["entries"]
          == ["npm test -- ph.test.ts src/dup.test.ts src/new.test.ts"])

    # --- dg-red: the newest FAILED phase-scope row by ts, never a green ------
    # row, another phase or another scope.
    row_failed_old = {"scope": "phase", "phaseId": "P1", "status": "failed",
                      "ts": "2026-01-01T00:00:00Z", "steps": []}
    row_failed_new = {"scope": "phase", "phaseId": "P1", "status": "failed",
                      "ts": "2026-01-02T00:00:00Z", "steps": []}
    row_green_newest = {"scope": "phase", "phaseId": "P1", "status": "passed",
                        "ts": "2026-01-03T00:00:00Z", "steps": []}
    row_other_phase = {"scope": "phase", "phaseId": "P2", "status": "failed",
                       "ts": "2026-01-04T00:00:00Z", "steps": []}
    row_task_scope = {"scope": "task", "taskId": "P1.1", "status": "failed",
                      "ts": "2026-01-05T00:00:00Z", "steps": []}
    rows = [row_failed_old, row_failed_new, row_green_newest, row_other_phase,
           row_task_scope]
    check("dg-red picks the newest FAILED phase-scope row by ts, ignoring a "
          "later GREEN row and rows for another phase/scope (mutation: pick "
          "the oldest row instead -> red): %r"
          % (M.newest_red_phase_row(rows, "P1"),),
          M.newest_red_phase_row(rows, "P1") == row_failed_new)

    # --- dg-nonerelated: the RELATED listing named NONE while the ALL --------
    # listing named SOME - the arm contributes nothing, with a printed reason
    # rather than a silent fallthrough (`_importers_arm`'s final `return [],
    # False, None` used to answer this with no reason at all).
    nonerelated_manifest = _importers_manifest()
    nonerelated_facts = {"versionAnswer": "v20",
                        "listing": {"exit": 0, "paths": []},
                        "fullListing": {"exit": 0,
                                       "paths": ["a.test.ts", "b.test.ts"]}}
    nonerelated_result = M.derive(nonerelated_manifest,
                                  nonerelated_manifest["phases"][0],
                                  nonerelated_facts)
    check("dg-nonerelated a related listing naming no suite while the full "
          "listing named some prints its own reason, contributing nothing "
          "(mutation: fall through with no reason -> red): %r"
          % (nonerelated_result["lines"],),
          any("named no suite while the full listing named" in l
              for l in nonerelated_result["lines"])
          and nonerelated_result["entries"] == ["npm test -- ph.test.ts"])

    # --- dg-vfail: a version command that FAILED is its own printed reason, --
    # never folded into "this machine answers None" (a mismatch reading).
    vfail_manifest = _importers_manifest()
    vfail_facts = {"versionCheckFailed": True,
                  "listing": {"exit": 0, "paths": ["a.test.ts"]},
                  "fullListing": {"exit": 0,
                                 "paths": ["a.test.ts", "b.test.ts"]}}
    vfail_result = M.derive(vfail_manifest, vfail_manifest["phases"][0],
                            vfail_facts)
    check("dg-vfail a version command that failed skips the importers arm "
          "with its OWN reason, never 'this machine answers None' (mutation: "
          "treat it as a mismatch -> red): %r" % (vfail_result["lines"],),
          any(l == "importers: skipped - the version command failed"
              for l in vfail_result["lines"])
          and not any("answers None" in l for l in vfail_result["lines"]))

    # --- dg-spelling (tests.add repro): no sibling path-scoped gate, but a --
    # declared meta.phaseGate.derived.spelling narrows onto IT instead, with
    # {paths} filled by the resolved test paths and the source named.
    spelling_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"spelling": "pytest {paths}"}}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    spelling_facts = {"changedSince": ["tests/test_new.py"]}
    spelling_result = M.derive(spelling_manifest,
                               spelling_manifest["phases"][0], spelling_facts)
    check("dg-spelling no path-scoped sibling but a declared spelling narrows "
          "onto it, {paths} filled with the resolved test paths, and the "
          "source is named (mutation: drop the spelling fallback -> red): %r"
          % (spelling_result,),
          spelling_result["narrowed"] is True
          and spelling_result["entries"] == ["pytest tests/test_new.py"]
          and spelling_result["shapeSource"] == "meta.phaseGate.derived.spelling")

    # --- dg-spelling-empty (tests.add repro): a declared spelling, no -------
    # sibling, and NO arm naming a test path - the wide gate runs, with the
    # reason printed and basis derived-empty (the most accurate EXISTING
    # word: it already means "this run computed nothing to narrow to", and a
    # spelling with nothing to substitute is exactly that, one shape source
    # over).
    spelling_empty_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"spelling": "pytest {paths}"}}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    spelling_empty_result = M.derive(spelling_empty_manifest,
                                     spelling_empty_manifest["phases"][0], {})
    check("dg-spelling-empty a spelling-sourced shape with NO arm naming a "
          "test path widens to the wide gate, the reason printed and basis "
          "derived-empty, never an entry with nothing substituted "
          "(mutation: drop the guard -> red, `pytest ` with an empty "
          "substitution): %r" % (spelling_empty_result,),
          spelling_empty_result["narrowed"] is False
          and spelling_empty_result["basis"] == "derived-empty"
          and spelling_empty_result["entries"] == ["unit", "lint"]
          and any("nothing to substitute" in l
                 for l in spelling_empty_result["lines"])
          and not any("pytest" in e for e in spelling_empty_result["entries"]))

    # --- dg-spelling-empty-allow: the SAME phase, but ONE tests.add path ----
    # exists - the spelling-sourced shape narrows onto it as usual.
    spelling_onepath_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"spelling": "pytest {paths}"}}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    spelling_onepath_facts = {"changedSince": ["tests/test_new.py"]}
    spelling_onepath_result = M.derive(spelling_onepath_manifest,
                                       spelling_onepath_manifest["phases"][0],
                                       spelling_onepath_facts)
    check("dg-spelling-empty-allow the same phase, but ONE arm-named path, "
          "narrows onto the spelling as usual: %r"
          % (spelling_onepath_result,),
          spelling_onepath_result["narrowed"] is True
          and spelling_onepath_result["entries"] == ["pytest tests/test_new.py"]
          and spelling_onepath_result["shapeSource"]
          == "meta.phaseGate.derived.spelling")

    # --- dg-neither: no sibling AND no usable spelling - phase-no-spelling, --
    # UNCHANGED from before the spelling fallback existed.
    neither_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"listing": {},
                                     "verifiedOn": {"command": "node -v",
                                                   "answer": "v20"}}}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    neither_result = M.derive(neither_manifest, neither_manifest["phases"][0], {})
    check("dg-neither no sibling and no usable spelling - phase-no-spelling, "
          "unchanged: %r" % (neither_result,),
          neither_result["basis"] == "phase-no-spelling"
          and neither_result["narrowed"] is False
          and neither_result["shapeSource"] is None)

    # --- dg-both: a sibling AND a declared spelling both exist - the SIBLING --
    # wins (its entry is evidence the runner already accepted it).
    both_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"spelling": "pytest {paths}"}}},
        phase=_phase(tasks=[_sibling(["npm test -- ph.test.ts"])]))
    both_result = M.derive(both_manifest, both_manifest["phases"][0], {})
    check("dg-both a sibling's own path-scoped gate AND a declared spelling "
          "both exist - the sibling wins (mutation: prefer the spelling over "
          "the sibling -> red): %r" % (both_result,),
          both_result["shapeSource"] == "P1.1"
          and both_result["entries"] == ["npm test -- ph.test.ts"]
          and "pytest" not in " ".join(both_result["entries"]))

    # --- dg-spelling-nopaths: a spelling with no {paths} placeholder is -------
    # ignored, with a printed reason.
    nopaths_manifest = _manifest(
        meta={"buildCommands": build,
             "phaseGate": {"mode": "shadow",
                          "derived": {"spelling": "pytest tests/"}}},
        phase=_phase(tasks=[_task("P1.1", tests={"gate": ["lint"]})]))
    nopaths_result = M.derive(nopaths_manifest, nopaths_manifest["phases"][0], {})
    check("dg-spelling-nopaths a spelling with no {paths} placeholder is "
          "ignored, with a printed reason, and the basis stays "
          "phase-no-spelling: %r" % (nopaths_result,),
          nopaths_result["basis"] == "phase-no-spelling"
          and nopaths_result["shapeSource"] is None
          and any("carries no {paths} placeholder" in l
                 for l in nopaths_result["lines"]))

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
