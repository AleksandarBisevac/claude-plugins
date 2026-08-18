#!/usr/bin/env python3
"""
The cases for `validate-manifest.py` - the command, which is all that file is now.

`validate-manifest.py` is hyphenated, so it comes through `_loader.load_script`
and this file substitutes underscores; see `test_migrate_manifest.py` for both
halves of that rule. `M` is the module under test.

WHY THIS SUITE IS FOUR CASES AND NOT 131. It was 131, when the rules lived in the
same file. They do not: `_panel_state` (L5), `audit-doctor`, `audit-status` and
`migrate-manifest` all needed `validate()` and all four reached it with
`_loader.load_script("validate-manifest.py")`, which `_deps.layer_violations()`
reads as a real edge - four of the seventeen entries in `KNOWN_LAYER_DEBT` were
this one file being used as a library by modules that could not import it. The
rules moved to `_manifest_rules.py` at layer 2, their cases moved to
`test__manifest_rules.py`, and what is left here is what is genuinely about the
COMMAND: the three-way exit code, and the usage error.

THAT IS THE WHOLE OBSERVABLE CONTRACT OF A CLI, AND IT IS WORTH ASSERTING
SEPARATELY. `validate()` returning findings and `main()` exiting 1 are two claims,
and the second is the one a CI job depends on. A suite that only called
`validate()` would stay green through a `main()` that printed the findings and
returned 0.

`_valid_manifest()` is a local copy of the fixture `test__manifest_rules.py` also
carries. Deliberate: the two suites are separately runnable files and CI runs each
on its own, so a fixture reached across test files would make one of them depend
on the other being present.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import copy
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("validate-manifest.py", modname="validate_manifest")


# --- the fixture the exit-code cases start from -------------------------------
def _valid_manifest():
    return {
        "meta": {"version": 2},
        "phases": [
            {"id": "P0", "title": "Phase", "status": "pending", "tasks": [
                {"id": "P0.1", "title": "Task", "status": "pending",
                 "tests": {"mode": "regression"}, "risk": "low",
                 "files": ["src/a.ts"],
                 "blockedBy": [], "dependsOn": []},
                {"id": "P0.2", "title": "Task 2", "status": "pending",
                 "dependsOn": ["P0.1"], "bugId": "BUG-1"},
            ]},
        ],
        "fileIndex": {"src/a.ts": ["P0.1"]},
        "bugs": [
            {"id": "BUG-1", "title": "A bug", "status": "in_progress",
             "taskId": "P0.2"},
        ],
    }


# --- cases --------------------------------------------------------------------
def _cases(record):
    # --- CLI exit codes: 0 valid · 1 findings · 2 usage/unreadable ---
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(_valid_manifest(), fh)
        record("c5 CLI accepts valid file (exit 0)", M.main([path]) == 0)
        bad = copy.deepcopy(_valid_manifest())
        bad["phases"][0]["tasks"][0]["status"] = "doing"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(bad, fh)
        record("c6 CLI reports findings (exit 1)", M.main([path]) == 1)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        record("c7 CLI rejects unparseable file (exit 2)", M.main([path]) == 2)
        record("c8 CLI usage error (exit 2)", M.main([]) == 2)
    finally:
        if os.path.exists(path):
            os.unlink(path)

    # --- the extraction contract ------------------------------------------------
    # c9-c11 are what stops the split silently becoming a fork. A copy of the
    # rules pasted back into this file would keep c5-c8 green forever: it would
    # validate, exit 1 on findings, and drift from `_manifest_rules` for as long
    # as nobody compared them. These three compare them.
    import _manifest_rules                                        # noqa: E402
    record("c9 the command validates through `_manifest_rules` and not through a "
           "second copy - `M.validate` IS that module's own function object, so "
           "a re-implementation here fails by identity rather than by drifting: "
           "%r" % (getattr(M.validate, "__module__", None),),
           M.validate is _manifest_rules.validate)
    # The other direction of the same mutation: a facade that re-exported every
    # private checker would put the rules' whole surface back on this command,
    # which is exactly what the layer split was for. This is the case that goes
    # red if the aliases creep back, and it reads vacuous next to c9 by design.
    _leaked = sorted(n for n in ("_check_meta", "_walk_phases", "_index_bugs",
                                 "_check_unique_ids", "_check_refs_and_cycles",
                                 "_check_file_index", "_check_bugs",
                                 "_check_proposals", "_check_areas",
                                 "_check_model_typos", "_check_skills",
                                 "check_ado_meta")
                     if hasattr(M, n))
    record("c10 ...and it re-exports NONE of the rules' internals - the command's "
           "surface is `main` plus the one function it calls, so `_manifest_rules` "
           "stays the only place a checker can be reached: %r" % (_leaked,),
           _leaked == [])
    record("c11 `main` is this file's own, not the rules module's - the half that "
           "did NOT move, asserted so that a later tidy cannot quietly relocate "
           "the exit codes too",
           callable(getattr(M, "main", None))
           and not hasattr(_manifest_rules, "main"))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_validate_manifest.py --selftest\n")
    raise SystemExit(2)
