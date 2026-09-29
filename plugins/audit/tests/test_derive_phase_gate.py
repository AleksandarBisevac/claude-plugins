#!/usr/bin/env python3
"""
The cases for `derive-phase-gate.py` -- observe, derive, record: a phase's
sign-off gate, computed rather than declared, beside the wide gate in shadow
and as the gate itself in enforce.

`_gate_derive.derive()`'s own cases (`test__gate_derive.py`) build `facts` by
hand and never touch a subprocess or git; this file is the other half -- did
the wiring around that pure function actually gather what it needs, and did
the write land in the right place under the right mode. Every fixture is a
REAL git repository (`_harness.fixture_root()`), and every observation the
manifest asks for is a REAL subprocess: a small Python script standing in for
"the version command" and for each of the two listings, never a fake handed
to `derive()` directly.

`dp`-prefixed cases.
"""

import json
import os
import shlex
import stat
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("derive-phase-gate.py", modname="derive_phase_gate")

# The interpreter as it is SPELLED IN A PLAN COMMAND, which is POSIX shell: an
# unquoted path with a space in it (a venv under a spaced directory, Windows'
# `Program Files`) split into two words and every observation failed.
PY = shlex.quote(sys.executable)

_VERSION_SCRIPT = "version.py"
_FULL_LIST_SCRIPT = "full_list.py"
_RELATED_LIST_SCRIPT = "related_list.py"


def _write_script(root, name, body):
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def _git(root, *args):
    subprocess.run(["git"] + list(args), cwd=root, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _build_commands():
    return {"unit": "%s -c \"pass\"" % (PY,),
           "lint": "%s -c \"pass\"" % (PY,),
           "listAll": "%s %s" % (PY, _FULL_LIST_SCRIPT)}


def _manifest(mode, version_answer="v20", base_ref=None, full_spelling=False,
             smoke=None, sib_files=None, sib_gate=None):
    related_script = _FULL_LIST_SCRIPT if full_spelling else _RELATED_LIST_SCRIPT
    phase_gate = {"mode": mode,
                 "derived": {"runner": "listAll",
                            "listing": {
                                "related": "%s %s {paths}" % (PY, related_script),
                                "all": "%s %s" % (PY, _FULL_LIST_SCRIPT)},
                            "verifiedOn": {
                                "command": "%s %s" % (PY, _VERSION_SCRIPT),
                                "answer": version_answer}}} if mode else None
    if phase_gate is not None and smoke is not None:
        phase_gate["smoke"] = smoke
    return {
        "meta": {"version": 2,
                "buildCommands": _build_commands(),
                "phaseGate": phase_gate},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                   "baseRef": base_ref,
                   "tasks": [{"id": "P1.1", "title": "sib", "status": "pending",
                              "files": sib_files or ["src/a.ts"],
                              "tests": {"mode": "gate-only",
                                       "gate": sib_gate or ["npm test -- ph.test.ts"],
                                       "gateBasis": "tests.add"}}]}],
    }


def _project(root, mode, version_answer="v20", write_manifest=True,
            full_spelling=False, smoke=None, sib_files=None, sib_gate=None,
            full_empty=False):
    """A fresh git repository with the three fake observation scripts on it,
    a manifest naming them, and `phase.baseRef` set to the first commit."""
    d = os.path.join(root, "proj-%d" % (len(os.listdir(root)) if
                                        os.path.isdir(root) else 0))
    os.makedirs(d)
    os.makedirs(os.path.join(d, ".claude"))
    _write_script(d, _VERSION_SCRIPT, "print('v20')\n")
    _write_script(d, _FULL_LIST_SCRIPT,
                 "pass\n" if full_empty
                 else "print('a.test.ts')\nprint('b.test.ts')\n")
    _write_script(d, _RELATED_LIST_SCRIPT, "print('a.test.ts')\n")
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "T")
    _write_script(d, "README.md", "hello\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    base_ref = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d,
                              stdout=subprocess.PIPE, check=True
                              ).stdout.decode().strip()
    os.makedirs(os.path.join(d, "docs", "audit"))
    mpath = os.path.join(d, "docs", "audit", "audit-plan.json")
    if write_manifest:
        manifest = _manifest(mode, version_answer=version_answer,
                             base_ref=base_ref, full_spelling=full_spelling,
                             smoke=smoke, sib_files=sib_files, sib_gate=sib_gate)
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
    return d, mpath, base_ref


def _run(argv):
    lines = []
    code = M.main(argv, out=lines.append)
    return code, "\n".join(lines)


def _raw(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- cases --------------------------------------------------------------------
def _cases(check):
    root = _harness.fixture_root("derive-phase-gate-selftest-")

    # --- dp1: no meta.phaseGate.mode -> nothing derived, nothing written ------
    d1, m1, _base = _project(root, mode=None)
    before = _raw(m1)
    code1, out1 = _run([m1, "P1"])
    after1 = _raw(m1)
    check("dp1 tests.add repro: no meta.phaseGate.mode -> exit 0, nothing "
          "written, and the reason is printed: %r" % (out1,),
          code1 == 0 and after1 == before
          and "mode is not set" in out1)

    # --- dp-listing (tests.add repro): _gather_facts spawns EXACTLY the -----
    # declared listing.related ({paths} filled) and listing.all commands, and
    # never a derived.runner/derived.spelling reading -- red at HEAD, where
    # the manifest below (no top-level `spelling`, `listing` carrying real
    # commands) makes the OLD reading find nothing usable and skip the arm
    # entirely rather than spawn either listing.
    d11, m11, _base11 = _project(root, mode="shadow")
    calls = []
    real_spawn = M._spawn

    def _capture(command, cwd, timeout):
        calls.append(command)
        return real_spawn(command, cwd, timeout)

    M._spawn = _capture
    try:
        code11, out11 = _run([m11, "P1"])
    finally:
        M._spawn = real_spawn
    expected_related = "%s %s %s" % (PY, _RELATED_LIST_SCRIPT, "src/a.ts")
    expected_all = "%s %s" % (PY, _FULL_LIST_SCRIPT)
    check("dp-listing spawns listing.related (paths filled) and listing.all "
          "verbatim, and the old runner/spelling skip line never appears: %r"
          % (calls,),
          code11 == 0
          and expected_related in calls
          and expected_all in calls
          and "runner/spelling pair" not in out11)

    # --- dp2: shadow mode writes testGateDerived + testGateBasis, testGate ----
    # UNCHANGED -- this IS the tests.add repro: on a tree with no
    # derive-phase-gate.py at all this case cannot even import M, which is the
    # red this is the fix for.
    d2, m2, _base2 = _project(root, mode="shadow")
    wide_before = _raw(m2)["phases"][0].get("testGate")
    code2, out2 = _run([m2, "P1"])
    ph2 = _raw(m2)["phases"][0]
    check("dp2 tests.add repro: shadow mode writes testGateDerived and "
          "testGateBasis and leaves phase.testGate UNTOUCHED (the wide gate "
          "still signs off): %r" % (ph2,),
          code2 == 0
          and ph2.get("testGate") == wide_before
          and isinstance(ph2.get("testGateDerived"), dict)
          and isinstance(ph2.get("testGateBasis"), str))
    check("dp2b the derived gate actually narrowed to the sibling's own path "
          "plus the related listing's one path: %r"
          % (ph2.get("testGateDerived", {}).get("tests"),),
          ph2.get("testGateDerived", {}).get("tests") == ["a.test.ts"] or
          any("a.test.ts" in t for t in
              (ph2.get("testGateDerived", {}).get("tests") or [])))
    check("dp2c (allow case, dg1's sibling) a NARROWED derivation - the "
          "related listing (['a.test.ts']) is a STRICT SUBSET of the full "
          "listing (['a.test.ts', 'b.test.ts']) -- must NEVER print "
          "'DERIVED = FULL': %r" % (out2,),
          "DERIVED = FULL" not in out2
          and ph2.get("testGateDerived", {}).get("full") is not True)
    check("dp2d fullListing carries its OWN durationMs beside the related "
          "listing's - both costs are recorded (mutation: drop it -> red): "
          "%r" % (ph2.get("testGateDerived", {}).get("fullListing"),),
          isinstance(ph2.get("testGateDerived", {})
                    .get("fullListing", {}).get("durationMs"), int)
          and isinstance(ph2.get("testGateDerived", {})
                        .get("listing", {}).get("durationMs"), int))

    # --- dp-full: the related listing resolves to the FULL listing (dg1) -----
    d2f, m2f, _base2f = _project(root, mode="shadow", full_spelling=True)
    code2f, out2f = _run([m2f, "P1"])
    ph2f = _raw(m2f)["phases"][0]
    check("dp-full (dg1, end to end through a REAL subprocess) an importer "
          "listing EQUAL to the full listing means the wide gate IS the "
          "answer - 'DERIVED = FULL' is printed and testGateDerived.full is "
          "True: %r" % (out2f,),
          code2f == 0 and "DERIVED = FULL" in out2f
          and ph2f.get("testGateDerived", {}).get("full") is True
          and ph2f.get("testGateBasis")
          == "wide: importers resolved to the full suite")
    check("dp-full-honest (round-final repro) a full-suite resolution is NOT "
          "narrowed - it prints NO 'test file(s)' count (that would be an "
          "attribution for a gate that is not narrowed), still prints "
          "'DERIVED = FULL', and carries the MEASURED listed-of-full pair as "
          "an advisory (mutation: restore a non-None attribution on the "
          "full-suite branch, or key the render off attribution again -> "
          "red): %r" % (out2f,),
          "test file(s)" not in out2f
          and "DERIVED = FULL" in out2f
          and "listed 2 of 2 (full)" in out2f
          and ph2f.get("testGateDerived", {}).get("arms") is None)
    code2f_brief, out2f_brief = _run([m2f, "P1", "--brief", "--dry-run"])
    check("dp-full-honest-brief --brief on a full-suite resolution prints "
          "ONLY measured counts (listed of full), never an attribution: %r"
          % (out2f_brief,),
          code2f_brief == 0
          and "derived: full suite (2 of 2)" in out2f_brief
          and "couplings" not in out2f_brief)

    # --- dp-empty (tests.add repro): an ALL listing that runs, exits 0 and --
    # prints nothing turns the derivation wide with basis derived-empty, end
    # to end through a REAL subprocess.
    de, me, _basee = _project(root, mode="shadow", full_empty=True)
    codee, oute = _run([me, "P1"])
    phe = _raw(me)["phases"][0]
    check("dp-empty an ALL listing that ran, exited 0 and printed nothing "
          "writes phase.testGateBasis == derived-empty, prints the GENERIC "
          "'nothing to narrow to' line (never a fabricated 'N test file(s)') "
          "plus the SPECIFIC advisory reason (mutation: reintroduce a second "
          "derivation, or key the render off something other than "
          "result['basis'] -> red): %r" % (oute,),
          codee == 0
          and "nothing to narrow to" in oute
          and "test file(s)" not in oute
          and "named no suite" in oute
          and phe.get("testGateBasis") == "derived-empty")
    codee_brief, oute_brief = _run([me, "P1", "--brief", "--dry-run"])
    check("dp-empty-brief --brief prints its own derived-empty NOTE (never "
          "'could not be bounded'), with no path in it (mutation: let the "
          "brief basis-check branch fall to 'could not be bounded' -> red): "
          "%r" % (oute_brief,),
          codee_brief == 0 and "derived: derived-empty for" in oute_brief
          and "could not be bounded" not in oute_brief
          and "a.test.ts" not in oute_brief
          and "npm test" not in oute_brief)

    # --- dp3: enforce mode writes testGate too, plus one journal row ----------
    d3, m3, _base3 = _project(root, mode="enforce")
    code3, out3 = _run([m3, "P1"])
    ph3 = _raw(m3)["phases"][0]
    check("dp3 enforce mode writes testGate, testGateBasis and "
          "testGateDerived: %r" % (ph3,),
          code3 == 0 and ph3.get("testGate")
          and any("a.test.ts" in e for e in ph3["testGate"])
          and isinstance(ph3.get("testGateBasis"), str)
          and isinstance(ph3.get("testGateDerived"), dict))
    journal_dir = os.path.join(d3, "docs", "audit", "journal")
    journaled = (os.path.isdir(journal_dir)
                and any(True for n in os.listdir(journal_dir)
                       if n.endswith(".jsonl")))
    check("dp3b a phase.gateDerived journal row was appended: %r"
          % (os.listdir(journal_dir) if os.path.isdir(journal_dir) else None,),
          journaled)

    # --- dp23: a differing version answer skips the importers arm ------------
    d4, m4, _base4 = _project(root, mode="shadow", version_answer="v21")
    code4, out4 = _run([m4, "P1"])
    ph4 = _raw(m4)["phases"][0]
    check("dp23 a version answer that does not match verifiedOn.answer skips "
          "the importers arm with the reason printed (end to end, through a "
          "REAL subprocess): %r" % (out4,),
          code4 == 0 and "this machine answers v20" in out4)
    check("dp23b ...and the derived gate still narrows around the sibling's "
          "OWN path alone, with no importer path added: %r"
          % (ph4.get("testGateDerived", {}).get("tests"),),
          ph4.get("testGateDerived", {}).get("tests") == [] or
          "a.test.ts" not in (ph4.get("testGateDerived", {}).get("tests") or []))

    # --- dp-brief: --brief carries no path and no failing text (tk2) ----------
    d5, m5, _base5 = _project(root, mode="shadow")
    code5, out5 = _run([m5, "P1", "--brief", "--dry-run"])
    check("dp-brief --brief prints ONE reviewer line with counts and a basis, "
          "and NEVER a path or runner text: %r" % (out5,),
          code5 == 0 and "derived:" in out5
          and "basis:" in out5
          and "a.test.ts" not in out5
          and "npm test" not in out5)
    check("dp-brief-dry --dry-run wrote nothing: %r" % (_raw(m5),),
          _raw(m5)["phases"][0].get("testGateDerived") is None)

    # --- dp-rollback: a write that would leave the manifest invalid is -------
    # rolled back byte for byte. Forced by making the SECOND validate() call
    # (the one asked of what actually landed on disk) report a finding, while
    # the pre-write call still sees a clean tree -- the only way to reach the
    # post-write branch specifically rather than the pre-write refusal.
    d6, m6, _base6 = _project(root, mode="shadow")
    before6 = open(m6, "rb").read()
    real_cores = M._panel_write._cores

    class _FlipValidator(object):
        def __init__(self):
            self.calls = 0

        def validate(self, manifest):
            self.calls += 1
            if self.calls == 1:
                return [], []
            return (["forced: the second validate() call always reports a "
                    "finding, to prove the post-write path rolls back"], [])

    def _fake_cores():
        real = real_cores()
        return (_FlipValidator(),) + tuple(real[1:])

    M._panel_write._cores = _fake_cores
    try:
        code6, out6 = _run([m6, "P1"])
    finally:
        M._panel_write._cores = real_cores
    after6 = open(m6, "rb").read()
    check("dp-rollback a write that fails post-write validation is rolled "
          "back BYTE FOR BYTE, and REFUSED is printed: exit=%r %r"
          % (code6, out6),
          code6 == M.E_INVALID and after6 == before6
          and "REFUSED" in out6)

    # --- dp-smoke: dg10 end to end -- a real source file gets smoke ADDED, ---
    # never skipped (the allow case a mutation that always skips smoke would
    # fail): a docs-only phase skips it with the line.
    d8, m8, _base8 = _project(root, mode="shadow", smoke="e2e",
                              sib_files=["src/real.ts"])
    code8, out8 = _run([m8, "P1"])
    ph8 = _raw(m8)["phases"][0]
    check("dp-smoke (dg10, allow case) a phase touching a REAL SOURCE file "
          "must NOT skip smoke - 'smoke added' is printed, never "
          "'smoke: skipped', and testGateDerived.smoke names the suite: %r"
          % (out8,),
          code8 == 0 and "smoke: skipped" not in out8
          and "smoke added" in out8
          and ph8.get("testGateDerived", {}).get("smoke") == "e2e")

    d9, m9, _base9 = _project(root, mode="shadow", smoke="e2e",
                              sib_files=["README.md"])
    code9, out9 = _run([m9, "P1"])
    ph9 = _raw(m9)["phases"][0]
    check("dp-smoke-skip (dg10) a phase touching only a docs/exempt file "
          "skips smoke, with the line printed once and never doubled: %r"
          % (out9,),
          code9 == 0
          and "| smoke: skipped - every file this phase touched is docs or "
              "tests" in out9
          and "smoke smoke:" not in out9
          and "e2e" not in (ph9.get("testGateDerived", {}).get("tests") or []))

    # --- dp-nospelling: dg2 end to end -- mode IS set, but no sibling task's --
    # own gate is path-scoped, so there is nothing to repoint at anything
    # narrower: "could not be bounded", and nothing narrower is written.
    d10, m10, _base10 = _project(root, mode="shadow", sib_gate=["lint"])
    code10, out10 = _run([m10, "P1"])
    ph10 = _raw(m10)["phases"][0]
    check("dp-nospelling (dg2, end to end) no path-scoped sibling gate -> "
          "'could not be bounded', basis phase-no-spelling, testGateDerived "
          "carries no narrowed test list: %r" % (out10,),
          code10 == 0 and "could not be bounded" in out10
          and ph10.get("testGateBasis") == "phase-no-spelling"
          and "tests" not in (ph10.get("testGateDerived") or {}))

    # --- dp-spelling-empty (tests.add repro): a BARE derived.spelling, no ----
    # listing, no sibling and no arm contribution - end to end through a REAL
    # subprocess, the derived-empty rendering must be the SAME honest wide
    # line the ALL-listing trigger uses (keyed off result["basis"] alone),
    # never a fabricated "0 test file(s)".
    d12, m12, base12 = _project(root, mode="shadow", write_manifest=False)
    manifest12 = {
        "meta": {"version": 2, "buildCommands": _build_commands(),
                "phaseGate": {"mode": "shadow",
                             "derived": {"spelling": "pytest {paths}"}}},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                   "baseRef": base12,
                   "tasks": [{"id": "P1.1", "title": "sib", "status": "pending",
                              "files": ["src/a.ts"],
                              "tests": {"mode": "gate-only", "gate": ["lint"],
                                       "gateBasis": "tests.add"}}]}],
    }
    with open(m12, "w", encoding="utf-8") as fh:
        json.dump(manifest12, fh, indent=2)
    code12, out12 = _run([m12, "P1"])
    ph12 = _raw(m12)["phases"][0]
    check("dp-spelling-empty a bare declared spelling with NO listing, no "
          "sibling and no arm contribution renders the SAME 'nothing to "
          "narrow to' line as the ALL-listing trigger, never '0 test "
          "file(s)' (mutation: reintroduce a second derivation, or key the "
          "render off something other than result['basis'] -> red): %r"
          % (out12,),
          code12 == 0
          and "nothing to narrow to" in out12
          and "test file(s)" not in out12
          and "nothing to substitute" in out12
          and ph12.get("testGateBasis") == "derived-empty")
    code12b, out12b = _run([m12, "P1", "--brief", "--dry-run"])
    check("dp-spelling-empty-brief --brief renders its own derived-empty "
          "note too, with no path and no runner text: %r" % (out12b,),
          code12b == 0 and "derived: derived-empty for" in out12b
          and "pytest" not in out12b)

    # --- dp-spelling-space (shlex.quote repro): a changedSince path with a ---
    # SPACE in it is carried shell-quoted as ONE token in the final spelling
    # entry - end to end, through a REAL git diff and a REAL subprocess.
    d13, m13, base13 = _project(root, mode="shadow", write_manifest=False)
    os.makedirs(os.path.join(d13, "tests"), exist_ok=True)
    with open(os.path.join(d13, "tests", "my file.test.ts"), "w",
             encoding="utf-8") as fh:
        fh.write("// a test file whose NAME carries a space\n")
    _git(d13, "add", "-A")
    _git(d13, "commit", "-q", "-m", "add a spaced test path")
    manifest13 = {
        "meta": {"version": 2, "buildCommands": _build_commands(),
                "phaseGate": {"mode": "enforce",
                             "derived": {"spelling": "pytest {paths}"}}},
        "phases": [{"id": "P1", "title": "P", "status": "pending",
                   "baseRef": base13,
                   "tasks": [{"id": "P1.1", "title": "sib", "status": "pending",
                              "files": ["src/a.ts"],
                              "tests": {"mode": "gate-only", "gate": ["lint"],
                                       "gateBasis": "tests.add"}}]}],
    }
    with open(m13, "w", encoding="utf-8") as fh:
        json.dump(manifest13, fh, indent=2)
    code13, out13 = _run([m13, "P1"])
    ph13 = _raw(m13)["phases"][0]
    check("dp-spelling-space a changedSince path with a SPACE is carried "
          "shell-quoted as ONE token in the written testGate entry (mutation: "
          "drop shlex.quote -> red, the raw path splits the command into two "
          "words): %r" % (ph13.get("testGate"),),
          code13 == 0
          and ph13.get("testGate") == ["pytest 'tests/my file.test.ts'"])

    # --- dp-muted: a quarantined failure is not a suite to learn -------------
    _named = "the suite file(s) jest named as failing, read from jest's FAIL"
    _red_row = {"steps": [
        {"name": "unit", "exit": 1, "failingSuites": ["src/cart.test.ts"],
         "failingSuitesBasis": _named,
         "muted": [{"test": "src/cart.test.ts", "bugId": "B1",
                    "until": "2026-10-01"}]},
        {"name": "e2e", "exit": 1, "failingSuites": ["src/pay.test.ts"],
         "failingSuitesBasis": _named}]}
    # The reading is `_evidence_io.named_failing_suites`, the one every
    # learner shares; dp-shared below pins that this script reaches it.
    _learn = M._evidence_io.named_failing_suites
    check("dp-muted a MUTED step's suite is not learned as last-failed - its "
          "failure is quarantined and a bug owns it - while the unmuted "
          "failed step beside it still is (mutation: drop the muted skip -> "
          "red): %r" % (_learn(_red_row["steps"]),),
          _learn(_red_row["steps"]) == ["src/pay.test.ts"])
    check("dp-muted-allow ALLOW: with no marker the same step is read as "
          "before: %r"
          % (_learn([dict(_red_row["steps"][0], muted=None)]),),
          _learn([dict(_red_row["steps"][0], muted=None)])
          == ["src/cart.test.ts"])

    # --- dp-shared: last-failed is learned through the SHARED reader --------
    # A spy stands in for `_evidence_io.named_failing_suites` while
    # `_gather_facts` reads a ledger holding one red phase row. A private
    # copy of the reading in this script would never call the spy, so
    # `lastFailedSuites` would come back as the copy's answer, not the spy's.
    d_sh, m_sh, _base_sh = _project(root, mode="shadow")
    manifest_sh = _raw(m_sh)
    red = {"scope": "phase", "phaseId": "P1", "status": "failed",
           "ts": "2026-09-27T00:00:00Z", "steps": [
               {"name": "unit", "exit": 1, "failingSuites": ["a.test.ts"],
                "failingSuitesBasis": _named}]}
    seen = []
    real_read, real_learn = M._evidence_io.read_rows, _learn

    def _spy(steps):
        seen.append(steps)
        return ["spy.test.ts"]

    M._evidence_io.read_rows = lambda _project_dir, config=None: {"rows": [red]}
    M._evidence_io.named_failing_suites = _spy
    try:
        facts_sh, _lines_sh = M._gather_facts(
            manifest_sh, manifest_sh["phases"][0], d_sh, lambda _l: None)
    finally:
        M._evidence_io.read_rows = real_read
        M._evidence_io.named_failing_suites = real_learn
    check("dp-shared lastFailedSuites is the SHARED reader's answer over the "
          "newest red phase row's steps - no private copy of the reading "
          "lives in this script: %r"
          % ((facts_sh.get("lastFailedSuites"), seen),),
          facts_sh.get("lastFailedSuites") == ["spy.test.ts"]
          and seen == [red["steps"]])

    # --- dp-no-sh: a machine with no POSIX shell is told so, ONCE -----------
    # Every observation here is a plan command run under `_proc_group`'s one
    # POSIX shell. With none, each skip line below would read as that
    # command's own failure; the missing prerequisite is said by name ahead of
    # them, and no observation claims an exit it never had.
    real_resolve = M._proc_group.resolve_sh
    M._proc_group.resolve_sh = lambda: (None, M._proc_group.NO_POSIX_SH)
    try:
        facts_ns, lines_ns = M._gather_facts(
            manifest_sh, manifest_sh["phases"][0], d_sh, lambda _l: None)
    finally:
        M._proc_group.resolve_sh = real_resolve
    shell_lines = [ln for ln in lines_ns if ln.startswith("shell:")]
    check("dp-no-sh with no POSIX shell the derivation says so in ONE line "
          "naming Git for Windows, and no observation carries an exit it "
          "never had (mutation: `_spawn` ignores the refusal and spawns "
          "through `shell=True` -> the listings report an exit -> red): %r"
          % ((shell_lines, facts_ns.get("fullListing"),
              facts_ns.get("versionCheckFailed")),),
          len(shell_lines) == 1 and "Git for Windows" in shell_lines[0]
          and (facts_ns.get("fullListing") or {}).get("exit") is None
          and facts_ns.get("versionCheckFailed") is True
          and "changedSince" not in facts_ns)

    # --- dp-usage: unknown phase is an error, never a silent fallback ---------
    d7, m7, _base7 = _project(root, mode="shadow")
    code7, out7 = _run([m7, "NOPE"])
    check("dp-usage an unknown phase id is a usage error, not a silent no-op: "
          "%r" % (out7,),
          code7 == M.E_USAGE and "no phase" in out7)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_derive_phase_gate.py --selftest\n")
    raise SystemExit(2)
