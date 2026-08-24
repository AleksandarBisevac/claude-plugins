#!/usr/bin/env python3
"""
The cases for `validate-manifest.py` - the command, which is all that file is now.

`validate-manifest.py` is hyphenated, so it comes through `_loader.load_script`
and this file substitutes underscores; see `test_migrate_manifest.py` for both
halves of that rule. `M` is the module under test.

WHY THIS SUITE IS SHORT AND NOT 131. It was 131, when the rules lived in the
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
import io
import json
import os
import sys
import tempfile

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402

M = _loader.load_script("validate-manifest.py", modname="validate_manifest")


def _run(argv):
    """`(exit code, stdout)` — the printed lines are half this command's contract.

    Counting them is the point rather than looking for one: the whole subject of
    c12 is HOW MANY lines a block of identical warnings becomes, and a presence
    assertion is green either way.
    """
    buf, real = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = M.main(argv)
    finally:
        sys.stdout = real
    return code, buf.getvalue()


def _skills_plan(counts):
    """A plan whose untagged phases hold tasks resolving no skills.

    The leading TAGGED phase is what makes the rule fire at all — `_check_skills`
    is gated on the manifest using skills somewhere, so without it the block
    under test is empty and c12 would pass over nothing.
    """
    phases = [{"id": "PT", "title": "T", "status": "pending", "area": "core",
               "tasks": [{"id": "PT.1", "title": "t", "status": "pending"}]}]
    for pid, n in counts:
        phases.append({"id": pid, "title": pid, "status": "pending",
                       "tasks": [{"id": "%s.%d" % (pid, i + 1), "title": "t",
                                  "status": "pending", "skills": []}
                                 for i in range(n)]})
    return {"meta": {"version": 2,
                     "areas": {"core": {"root": "src",
                                        "skills": ["writing-python"]}}},
            "phases": phases}


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

    fd2, path2 = tempfile.mkstemp(suffix=".json")
    os.close(fd2)
    try:
        _cases_output(record, path2)
    finally:
        if os.path.exists(path2):
            os.unlink(path2)


def _cases_output(record, path):
    """The printed contract: how many lines a repeated warning becomes."""
    # The plan the defect was measured on — four untagged phases holding
    # 7 + 5 + 1 + 6 tasks, which is what produced the block this collapses.
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_skills_plan((("P0", 7), ("P1", 5), ("BF1", 1), ("P8", 6))), fh)
    code, text = _run([path])
    warn_lines = [ln for ln in text.splitlines() if ln.startswith("WARNING: ")]
    vcode, vtext = _run([path, "--verbose"])
    vwarn = [ln for ln in vtext.splitlines() if ln.startswith("WARNING: ")]
    record("c12 a rule that fires once per task prints ONE line naming the count "
           "and the phases, and `--verbose` still prints every one - counted on "
           "both sides, because a collapse that also emitted the members would "
           "satisfy either assertion alone: %d line(s), %d with --verbose"
           % (len(warn_lines), len(vwarn)),
           code == 0 and vcode == 0
           and len(warn_lines) == 1 and len(vwarn) == 19
           and warn_lines[0].startswith("WARNING: 19 tasks in 4 phases "
                                        "(P0, P1, BF1, P8; --verbose names each): ")
           and text.rstrip().endswith("1 warning line(s), 19 item(s))"))

    # The negative that pairs with it, and the reason findings were left alone:
    # a finding stops the command and is read item by item. Three of them share
    # one body here, so a collapse applied to the wrong list would print one.
    bad = _valid_manifest()
    for task in bad["phases"][0]["tasks"]:
        task["blockedBy"] = ["ZZ"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    fcode, ftext = _run([path])
    flines = [ln for ln in ftext.splitlines() if ln.startswith("FINDING: ")]
    record("c13 findings that share one body are NOT collapsed - two identical "
           "messages naming two tasks stay two lines, and the INVALID tail still "
           "counts them: %d line(s)" % (len(flines),),
           fcode == 1 and len(flines) == 2
           and "INVALID: 2 finding(s)" in ftext)

    # --- F115: the summary has to be derivable from the body -------------------
    # The defect this pins closed printed a pair of WARNING lines and a total in
    # the twenties, both true, with nothing on the surface joining them. So the
    # assertion is not the literal tail: it is the tail rebuilt FROM THE LINES the
    # same run printed, which is the only thing that makes the number checkable
    # and the only shape that would have failed before the fix.
    plan = _skills_plan((("P0", 7), ("P1", 5), ("BF1", 1), ("P8", 6)))
    plan["meta"]["nonsenseKey"] = 1          # a second, differently-shaped warning
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh)
    tcode, ttext = _run([path])
    tlines = [ln for ln in ttext.splitlines() if ln.startswith("WARNING: ")]
    _, vtext2 = _run([path, "--verbose"])
    titems = [ln for ln in vtext2.splitlines() if ln.startswith("WARNING: ")]
    record("c15 when the collapse does something, the OK line names BOTH the "
           "lines it printed and the items behind them - rebuilt from this run's "
           "own output, so a total nobody can reach from the body fails here: "
           "%d line(s), %d item(s), tail %r"
           % (len(tlines), len(titems), ttext.rstrip()[-40:]),
           tcode == 0 and len(tlines) == 2 and len(titems) == 20
           and ttext.rstrip().endswith(
               M.warning_tail(len(tlines), len(titems)) + ")")
           and ttext.rstrip().endswith("2 warning line(s), 20 item(s))"))

    # THE SECOND DIRECTION, and it reads vacuous by design: a tail that named two
    # numbers unconditionally would satisfy c15 for ever while telling a reader of
    # an ordinary one-warning run to reconcile a number with itself. This is the
    # only case that fails when `warning_tail` stops being conditional.
    lone = _valid_manifest()
    lone["meta"]["nonsenseKey"] = 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(lone, fh)
    lcode, ltext = _run([path])
    llines = [ln for ln in ltext.splitlines() if ln.startswith("WARNING: ")]
    record("c16 ...and when nothing collapsed there is ONE number, because the "
           "two counts are then the same fact and a reader can count the lines: "
           "%d line(s), tail %r" % (len(llines), ltext.rstrip()[-30:]),
           lcode == 0 and len(llines) == 1
           and ltext.rstrip().endswith(", 1 warning(s))")
           and "item(s)" not in ltext)
    record("c17 warning_tail is silent when there is nothing to count - a plan "
           "with no warnings must not grow a `0` where the tail used to be "
           "absent: %r" % (M.warning_tail(0, 0),),
           M.warning_tail(0, 0) == ""
           and M.warning_tail(1, 1) == ", 1 warning(s)"
           and M.warning_tail(2, 20) == ", 2 warning line(s), 20 item(s)")

    record("c14 `--verbose` is a flag and not the path - passing it alone is "
           "still the usage error it was, so the flag cannot be mistaken for a "
           "manifest and silently validate nothing",
           M.main(["--verbose"]) == 2)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_validate_manifest.py --selftest\n")
    raise SystemExit(2)
