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
import stat
import subprocess
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("derive-phase-gate.py", modname="derive_phase_gate")

PY = sys.executable

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
                            "spelling": "%s %s {paths}" % (PY, related_script),
                            "listing": {},
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
            full_spelling=False, smoke=None, sib_files=None, sib_gate=None):
    """A fresh git repository with the three fake observation scripts on it,
    a manifest naming them, and `phase.baseRef` set to the first commit."""
    d = os.path.join(root, "proj-%d" % (len(os.listdir(root)) if
                                        os.path.isdir(root) else 0))
    os.makedirs(d)
    os.makedirs(os.path.join(d, ".claude"))
    _write_script(d, _VERSION_SCRIPT, "print('v20')\n")
    _write_script(d, _FULL_LIST_SCRIPT,
                 "print('a.test.ts')\nprint('b.test.ts')\n")
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
