#!/usr/bin/env python3
"""
The cases for `_doctor_report.py` — and for the re-export surface it anchors.

Two subjects, and the second is the reason this suite is the one that grew
identity cases. `Report` and `_load` are ordinary functions with ordinary
contracts. The ALIASES are not: `audit-doctor.py` re-exports every name its six
check modules hold, and each of those modules re-exports `_load` off this one,
so a split that quietly forked any of them into a second definition would leave
every suite green while two copies drifted. Identity is asserted with `is`,
across all seven files, because that is the only assertion a copy fails.

`_load`'s `cache=False` is asserted the same way, and it is not a style
preference: `tests/test_audit_doctor.py` re-`diagnose()`s ONE fixture project
it mutates between calls, in one process. A cached module would serve the
pre-mutation code back and be indistinguishable from a real regression.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _output                                     # noqa: E402
import _doctor_report as M                         # noqa: E402
import _doctor_setup as _setup                     # noqa: E402
import _doctor_policy as _policy_checks            # noqa: E402
import _doctor_ado as _ado                         # noqa: E402
import _doctor_trail as _trail                     # noqa: E402
import _doctor_completions as _completions         # noqa: E402
import _doctor_hygiene as _hygiene                 # noqa: E402

_DOCTOR = _loader.load_script("audit-doctor.py", modname="audit_doctor_x")


# --- cases --------------------------------------------------------------------
def _cases(check):
    # ---------------------------------------------------------------- Report
    r = M.Report()
    check("dr1 a fresh Report holds no rows and exits 0 - an empty diagnosis is "
          "not a failed one: %r" % (r.rows,),
          r.rows == [] and r.exit_code() == 0
          and r.counts() == {"OK": 0, "WARNING": 0, "FINDING": 0})

    r.ok("a", "d1")
    r.warn("b", "d2")
    r.warn("c", "d3", "fix me")
    check("dr2 every row carries all four fields, and `ok`/`warn` differ only in "
          "the level - `fix` defaults to None rather than to the empty string, "
          "which is what `render` tests on: %r" % (r.rows,),
          r.rows == [{"level": "OK", "check": "a", "detail": "d1", "fix": None},
                     {"level": "WARNING", "check": "b", "detail": "d2",
                      "fix": None},
                     {"level": "WARNING", "check": "c", "detail": "d3",
                      "fix": "fix me"}])
    check("dr3 warnings alone keep the exit code at 0. THE OTHER-DIRECTION CASE: "
          "it is the one that fails if `exit_code` ever grows to count warnings, "
          "which would fail every healthy repo carrying a single advisory row",
          r.exit_code() == 0 and r.counts()["WARNING"] == 2)

    r.finding("d", "d4")
    check("dr4 one finding flips the exit code, and counts are counts rather "
          "than presence - two warnings are reported as two: %r" % (r.counts(),),
          r.exit_code() == 1
          and r.counts() == {"OK": 1, "WARNING": 2, "FINDING": 1})

    r.add("SURPRISE", "e", "d5")
    check("dr5 a level `counts()` has no column for is COUNTED, not dropped: the "
          "seed dict is a floor and `out.get(level, 0) + 1` is what makes an "
          "unknown level visible instead of silently absent: %r" % (r.counts(),),
          r.counts().get("SURPRISE") == 1)
    check("dr6 ...and it still does not flip the exit code, which reads FINDING "
          "and nothing else", r.exit_code() == 1)

    r2 = M.Report()
    check("dr7 two Reports do not share rows - the collector holds instance "
          "state, never module state, so two diagnoses in one process cannot "
          "accumulate into each other: %r" % (r2.rows,), r2.rows == [])

    # ---------------------------------------------------------------- _load
    a = M._load("_probe_areas_1", "_areas.py")
    b = M._load("_probe_areas_2", "_areas.py")
    check("dr8 `_load` resolves a scripts/ sibling by BASENAME, wherever it "
          "sits - `_areas.py` is under scripts/manifest/ and the call names no "
          "directory", hasattr(a, "registry") and hasattr(a, "areas_of"))
    check("dr9 ...and two loads of one file are two module objects, because "
          "`cache=False` is fixed here. The suite that re-diagnoses a mutated "
          "fixture in one process is what this is for; a cached module would "
          "serve the pre-mutation code back", a is not b)

    hooked = M._load("_probe_config", "_config.py", M._HOOKS)
    check("dr10 a `directory` argument switches to the explicit join, which is "
          "how the two hooks/ files are reached - hooks/ is not on the "
          "basename walk", hasattr(hooked, "load") and hasattr(hooked, "DEFAULTS"))

    ok, why = _harness.attempt(M._load, "_probe_missing", "no-such-file-xyz.py")
    check("dr11 a load that cannot resolve RAISES rather than returning None, "
          "and the error NAMES the file it could not find. The wrapper shapes no "
          "errors: a check calling a method on a None it was handed would report "
          "a traceback about the wrong thing: %r" % (why,),
          not ok and "no-such-file-xyz.py" in why)

    # ------------------------------------------------------------- constants
    check("dr12 `LAUNCHER_INTERPRETERS` is py-launch.sh's own order, and the "
          "ORDER is the fact - `check_interpreter` reports found[0] as the one "
          "the hooks will use: %r" % (M.LAUNCHER_INTERPRETERS,),
          M.LAUNCHER_INTERPRETERS == ("python3", "python", "py"))
    launcher = os.path.join(M._HOOKS, "py-launch.sh")
    check("dr13 ...and the file those names are read out of is really there, so "
          "the tuple is a claim about a launcher that exists: %s" % (launcher,),
          os.path.isfile(launcher))
    with open(launcher, "r", encoding="utf-8") as fh:
        launcher_src = fh.read()
    check("dr14 ...and every name in it appears in py-launch.sh. Two files "
          "spelling one list is exactly the drift the constant was extracted to "
          "prevent, so the agreement is tested rather than asserted in a "
          "comment: %r" % (M.LAUNCHER_INTERPRETERS,),
          all(name in launcher_src for name in M.LAUNCHER_INTERPRETERS))
    check("dr15 `RECENT_DAYS` matches detect-plan-skip's 7-day GC, so a quiet "
          "week is not read as broken: %r" % (M.RECENT_DAYS,),
          M.RECENT_DAYS == 7)
    check("dr16 `_HOOKS` is `_output`'s anchor, not a path this file derived - "
          "no `.py` under scripts/ may read `__file__` outside the pinned "
          "preamble", M._HOOKS is _output.HOOKS_DIR)

    # ------------------------------------------------- the re-export surface
    borrowers = (("_doctor_setup", _setup), ("_doctor_policy", _policy_checks),
                 ("_doctor_ado", _ado), ("_doctor_trail", _trail),
                 ("_doctor_completions", _completions),
                 ("audit-doctor", _DOCTOR))
    forked = [name for name, mod in borrowers if mod._load is not M._load]
    check("dr17 every module that spells `_load` is spelling THIS one. Six files "
          "share it, which is the whole reason it moved down here; a copy in any "
          "of them would be a second answer to 'how does a check reach a "
          "sibling': %r" % (forked,), forked == [])
    check("dr18 `_doctor_hygiene` deliberately borrows NOTHING - it loads no "
          "sibling at runtime at all, which is what keeps it at layer 3 beside "
          "`_doctor_ado` rather than up with the four that do",
          not hasattr(_hygiene, "_load"))

    aliased = {
        "Report": M.Report, "_load": M._load, "_HOOKS": M._HOOKS,
        "LAUNCHER_INTERPRETERS": M.LAUNCHER_INTERPRETERS,
        "RECENT_DAYS": M.RECENT_DAYS,
        "check_interpreter": _setup.check_interpreter,
        "check_git": _setup.check_git, "check_config": _setup.check_config,
        "check_plan_gate": _setup.check_plan_gate,
        "check_manifest": _setup.check_manifest,
        "_check_shards": _setup._check_shards,
        "check_submodules": _setup.check_submodules,
        "check_areas": _policy_checks.check_areas,
        "check_policy": _policy_checks.check_policy,
        "check_build_commands": _policy_checks.check_build_commands,
        "_leading_executable": _policy_checks._leading_executable,
        "check_ado": _ado.check_ado,
        "check_hooks_fired": _trail.check_hooks_fired,
        "check_ledger": _trail.check_ledger,
        "_journal_never_committed": _trail._journal_never_committed,
        "check_journal": _trail.check_journal,
        "_hours_between": _completions._hours_between,
        "check_completions": _completions.check_completions,
        "check_locks": _hygiene.check_locks,
        "check_local_artifacts": _hygiene.check_local_artifacts,
    }
    missing = [n for n in aliased if not hasattr(_DOCTOR, n)]
    check("dr19 `audit-doctor` re-exports all %d names the six modules hold, so "
          "the suite and the command keep spelling one import: %r"
          % (len(aliased), missing), missing == [])
    diverged = [n for n, obj in aliased.items()
                if getattr(_DOCTOR, n, None) is not obj]
    check("dr20 ...and every one of them IS the object beside it, pinned with "
          "`is`. A re-export that forked into a copy passes dr19 and fails only "
          "here, which is why presence is not enough: %r" % (diverged,),
          diverged == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__doctor_report.py --selftest\n")
    raise SystemExit(2)
