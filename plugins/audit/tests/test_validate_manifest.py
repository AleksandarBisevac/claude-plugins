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
        _cases_test_evidence(record, path2)
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


def _cases_test_evidence(record, path):
    """The evidence recorder's manifest keys through the front door.

    Two of them now, at three levels: `testEvidence` on a task and on a phase,
    and `meta.evidenceSince` on the document's header. They share a suite because
    they share the command's entire involvement in them - the typo-catcher, and
    the back-compat claim that a plan carrying neither validates identically -
    and because the three level sets are separate literals, so a case at one
    level says nothing about the other two.

    `testEvidence` is a POINTER at the append-only evidence ledger kept beside
    the manifest; `meta.evidenceSince` says when that ledger could first have
    held anything at all. Both are worth driving from here rather than from the
    sets: "the key is in `_manifest_vocab.KNOWN_TASK`" is a fact about a literal,
    while "a real key draws no warning and a misspelt one does" is the consequence
    a user sees, and only the second fails when the level stops consulting the set.
    """
    good = {"runId": "2026-08-26T14:03:11Z.7f3a91", "status": "failed",
            "at": "2026-08-26T14:03:11Z"}

    def _out(plan):
        """`(exit code, FINDING lines, WARNING lines)` for one manifest."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        code, text = _run([path])
        return (code,
                [ln for ln in text.splitlines() if ln.startswith("FINDING: ")],
                [ln for ln in text.splitlines() if ln.startswith("WARNING: ")])

    bare = _out(_valid_manifest())

    _task_ok = _valid_manifest()
    _task_ok["phases"][0]["tasks"][0]["testEvidence"] = dict(good)
    task_ok = _out(_task_ok)
    # A CASE collision, because that is the hint's mechanism: `_unknown_keys` folds
    # case and looks the key up, so `testevidence` names the key it was meant to be
    # and `testEvidenc` would only get the generic line. The generic line is the one
    # this key already drew before it was declared, so it proves nothing.
    _task_typo = _valid_manifest()
    _task_typo["phases"][0]["tasks"][0]["testevidence"] = dict(good)
    task_typo = _out(_task_typo)
    record("c18 a task carrying `testEvidence` validates in silence, and a "
           "misspelling of it draws a did-you-mean naming the real key - the PAIR, "
           "because silence on its own is also what a validator that has stopped "
           "looking produces, and a hint on its own would fire for a set that holds "
           "the key at the wrong level: %r / %r" % (task_ok, task_typo),
           task_ok == (0, [], [])
           and task_typo[0] == 0 and task_typo[1] == []
           and len(task_typo[2]) == 1
           and "task P0.1" in task_typo[2][0]
           and "did you mean 'testEvidence'" in task_typo[2][0])

    _phase_ok = _valid_manifest()
    _phase_ok["phases"][0]["testEvidence"] = dict(good)
    phase_ok = _out(_phase_ok)
    _phase_typo = _valid_manifest()
    _phase_typo["phases"][0]["testevidence"] = dict(good)
    phase_typo = _out(_phase_typo)
    record("c19 ...and the same pair holds one level up, on the phase - the key is "
           "declared at both levels and the two sets are separate literals, so a "
           "task-only case would pass over a phase that never learned the word: "
           "%r / %r" % (phase_ok, phase_typo),
           phase_ok == (0, [], [])
           and phase_typo[0] == 0 and phase_typo[1] == []
           and len(phase_typo[2]) == 1
           and "phase P0" in phase_typo[2][0]
           and "did you mean 'testEvidence'" in phase_typo[2][0])

    _both = _valid_manifest()
    _both["phases"][0]["testEvidence"] = dict(good)
    _both["phases"][0]["tasks"][0]["testEvidence"] = dict(good)
    both = _out(_both)
    record("c20 a manifest carrying NO `testEvidence` anywhere gets the same "
           "verdict as one carrying it at both levels - which is the whole "
           "back-compat claim, since absent means 'no evidence recorded' and the "
           "field is additive. The misspelt run is what stops that equality being "
           "a validator that answers the same thing to everything: %r / %r"
           % (bare, both),
           bare == (0, [], []) and both == bare and task_typo != bare)

    # CURRENT BEHAVIOUR, asserted so a later fix changes a case on purpose rather
    # than discovering one - the same reason mv12 pins `bool` being an `int`.
    # `additionalProperties` is permissive at this level and no `_unknown_keys()`
    # call descends into the block, so the command cannot see a cached `attempt`
    # (cut on purpose: a count beside the thing that produces it is this repo's
    # most-repeated defect) or a `status` the schema does not declare. ajv over
    # `audit-plan.schema.json` is what refuses both.
    _inside = _valid_manifest()
    _inside["phases"][0]["tasks"][0]["testEvidence"] = dict(good, attempt=3,
                                                            status="green")
    _inside["phases"][0]["tasks"][0]["zzzProbe"] = 1
    inside = _out(_inside)
    record("c21 the command sees nothing INSIDE the block - a cached `attempt` and "
           "a `status` no enum declares both pass here - while the sibling probe on "
           "the same task draws its one warning in the same run. That pairing is "
           "what makes this a fact about the level rather than about the "
           "typo-catcher being off, and it is why the enum is ajv's to enforce: %r"
           % (inside,),
           inside[0] == 0 and inside[1] == []
           and len(inside[2]) == 1 and "'zzzProbe'" in inside[2][0]
           and "testEvidence" not in inside[2][0])


    # `meta.evidenceSince` through the same door, one level up. The command's
    # whole involvement is the typo-catcher here too, and the level is a SEPARATE
    # literal from the two above - so a task-and-phase pair would pass over a
    # `meta` that never learned the word.
    _meta_ok = _valid_manifest()
    _meta_ok["meta"]["evidenceSince"] = {
        "at": "2026-06-02T15:38:00Z",
        "runId": "2026-06-02T15:38:00Z.4c1ba7",
        "basis": "the first run this plan recorded"}
    meta_ok = _out(_meta_ok)
    _meta_typo = _valid_manifest()
    _meta_typo["meta"]["evidencesince"] = {"at": "2026-06-02T15:38:00Z"}
    meta_typo = _out(_meta_typo)
    record("c22 a plan stating `meta.evidenceSince` validates in silence, and a "
           "misspelling draws a did-you-mean naming the real key - the PAIR, for "
           "c18's reason, and at a level with its own literal set. The key says "
           "when this plan could FIRST have recorded a run, so a warning about a "
           "correct one would push somebody to delete the thing that excuses "
           "their pre-recorder work: %r / %r" % (meta_ok, meta_typo),
           meta_ok == (0, [], [])
           and meta_typo[0] == 0 and meta_typo[1] == []
           and len(meta_typo[2]) == 1
           and "did you mean 'evidenceSince'" in meta_typo[2][0])

    record("c23 ...and a plan carrying NO boundary gets the same verdict as one "
           "carrying it, which is the whole back-compat claim: the key is "
           "additive, absent means 'nothing here says when recording began', and "
           "every plan written before it existed validates exactly as it did. "
           "The misspelt run is what stops that equality being a validator "
           "answering the same thing to everything: %r / %r" % (bare, meta_ok),
           bare == (0, [], []) and meta_ok == bare and meta_typo != bare)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test_validate_manifest.py --selftest\n")
    raise SystemExit(2)
