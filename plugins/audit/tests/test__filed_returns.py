#!/usr/bin/env python3
"""
The cases for `_filed_returns.py` - where a filed return lives, the shape each
role owes, the write-once create and the read.

WHAT IS PINNED, and why each one is here rather than trusted:

- **The shape is the brief's.** `fr6` reads the field list off
  `agents/audit-executor.md`'s own return block and deletes each declared field
  in turn, so a field the brief grows is one the check must refuse the absence
  of; `fr7` holds the red-first words equal to the schema enum. Neither keeps a
  second copy of what it compares.
- **Both directions.** Every refusal sits beside the whole return that files, so
  a check refusing everything fails here as surely as one refusing nothing.
- **A start is part of the path.** Two starts of one task read two files; a
  return under an earlier start is never this start's.
- **A file that will not parse is a problem, never an absence.**

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (PLUGIN_ROOT, the agent briefs)
import _refs                                       # noqa: E402  (the brief's return block, the schema enum)
import _filed_returns as M                         # noqa: E402

_START = "2026-01-01T00:00:00Z"


def _executor(**over):
    body = {"gates": {"python3 t.py": "pass"},
            "redFirst": {"status": "proved", "basis": "the run exited non-zero on its own case",
                         "at": "z"},
            "outcome": {"technical": "t", "descriptive": "d"},
            "testsAdded": ["one"], "stamp": "audit-stamp: v2 x"}
    body.update(over)
    return body


def _reviewer(answer="matches"):
    return {"findings": [], "intent": {"answer": answer}, "verdict": "clean"}


def _cases(check):
    root = _harness.fixture_root("filed-returns-")
    task = {"id": "P1.1", "startedAt": _START}

    check("rp1 the path is `returns/<task>/<start>.<role>.json`, the start "
          "spelled with letters and digits only: %r"
          % (M.return_rel("P1.1", _START, "executor"),),
          M.return_rel("P1.1", _START, "executor")
          == "returns/P1.1/20260101T000000Z.executor.json")
    later = dict(task, startedAt="2026-01-02T00:00:00Z")
    check("rp2 two starts of one task are two paths, and a task with no start "
          "has none - so an earlier start's return is never read as this one's",
          M.return_path(root, task, "executor")
          != M.return_path(root, later, "executor")
          and M.return_path(root, {"id": "P1.1"}, "executor") is None
          and M.return_path(root, task, "executor").startswith(root))

    # ---- the shape ----------------------------------------------------------
    with open(os.path.join(_output.PLUGIN_ROOT, "agents", "audit-executor.md"),
              "r", encoding="utf-8") as fh:
        block = _refs._return_block(fh.read()) or ""
    keys = _refs._return_keys(block)
    optional = [k for k in keys if '"%s": "optional:' % (k,) in block]
    unnamed = []
    for key in keys:
        if key in optional:
            continue
        body = _executor()
        body.pop(key, None)
        if not any("`%s" % (key,) in p for p in M.return_problems("executor", body)):
            unnamed.append(key)
    check("fr6 every field agents/audit-executor.md declares is one the check "
          "refuses the absence of, BY NAME - the keys read off the brief, so a "
          "field it grows is demanded here too; and a whole return has no "
          "problem: %r" % ((keys, optional, unnamed),),
          len(keys) >= 5 and unnamed == []
          and M.return_problems("executor", _executor()) == [])
    enum, problem = _refs._red_first_enum(_refs.REPO_ROOT)
    check("fr7 the red-first words are the schema's enum, in its order - the "
          "plugin runs from an installed copy where the schema is not where the "
          "lint reads it, so this tuple is kept here and this case keeps it from "
          "being a second vocabulary: %r" % ((M.RED_FIRST_WORDS, enum, problem),),
          problem is None and list(M.RED_FIRST_WORDS) == enum)
    bad_red = M.return_problems("executor", _executor(
        redFirst={"status": "not-proved", "basis": ""}))
    check("rp3 an executor word outside the vocabulary - the reviewer's own "
          "`not-proved` included - and an empty basis are each named: %r"
          % (bad_red,),
          any("not-proved" in p for p in bad_red)
          and any("redFirst.basis" in p for p in bad_red))
    check("rp4 the reviewer's shape: a word outside the three answers and a "
          "verdict outside its two are named, and a whole return files: %r"
          % (M.return_problems("reviewer", {"findings": [],
                                            "intent": {"answer": "yes"},
                                            "verdict": "ok"}),),
          len(M.return_problems("reviewer", {"findings": [],
                                             "intent": {"answer": "yes"},
                                             "verdict": "ok"})) == 2
          and M.return_problems("reviewer", _reviewer()) == [])
    check("rp5 a role the module does not know, or a body that is not an "
          "object, is a problem and never a pass",
          M.return_problems("phase", _reviewer()) != []
          and M.return_problems("executor", ["not", "an", "object"]) != [])
    check("rp6 `claims` is optional text: absent files, a non-text value is "
          "named",
          M.return_problems("executor", _executor()) == []
          and any("claims" in p for p in
                  M.return_problems("executor", _executor(claims=["x"]))))

    # ---- the write and the read ----------------------------------------------
    path = M.return_path(root, task, "executor")
    first = json.dumps(_executor(claims="claims:\n1 n/a")) + "\n"
    M.file_once(path, first)
    raised = False
    try:
        M.file_once(path, "{}")
    except FileExistsError:
        raised = True
    with open(path, "r", encoding="utf-8", newline="") as fh:
        kept = fh.read()
    check("rp7 the create is exclusive: a second write to one path raises and "
          "the first stays byte-identical", raised and kept == first)
    text, body, why = M.read_filed_return(path)
    none = M.read_filed_return(M.return_path(root, later, "executor"))
    check("rp8 a filed return reads back verbatim and parsed; one not filed "
          "reads as three Nones", text == first and body.get("stamp")
          and why is None and none == (None, None, None))
    broken = M.return_path(root, {"id": "P1.2", "startedAt": _START}, "executor")
    M.file_once(broken, "{not json")
    check("rp9 a file that is there and will not parse is a PROBLEM, never read "
          "as not filed: %r" % (M.read_filed_return(broken)[2],),
          M.read_filed_return(broken)[2] is not None
          and M.claims_from_return(root, {"id": "P1.2", "startedAt": _START})[1]
          is not None)
    claims, problem = M.claims_from_return(root, task)
    check("rp10 `claims_from_return` hands back the current start's `claims` "
          "verbatim, and None for a start with no return or a return without "
          "the field: %r" % (claims,),
          claims == "claims:\n1 n/a" and problem is None
          and M.claims_from_return(root, later) == (None, None)
          and M.claims_from_return(root, {"id": "P1.1"}) == (None, None))


_SHA = "0123456789abcdef0123456789abcdef01234567"
_SHA2 = "fedcba9876543210fedcba9876543210fedcba98"


def _answered(commit=_SHA, **over):
    """An `intentCheck` carrying the three answers a phase review writes."""
    block = {"answer": "matches", "commit": commit, "at": "z",
             "redFirst": "proved", "redFirstBasis": "t.py exit 1",
             "inheritedTests": "none-found", "inheritedTestsBasis": "t.py"}
    block.update(over)
    return block


def _entry(tid="P1.1", commit=_SHA, **over):
    """One `tasks` entry of a phase-mode reviewer return."""
    entry = {"id": tid, "commit": commit, "answer": "matches", "note": "n",
             "missing": [], "redFirst": "proved",
             "redFirstBasis": "t.py exit 1, its own case",
             "inheritedTests": "not-asked",
             "inheritedTestsBasis": "the gate runs the whole suite"}
    entry.update(over)
    return entry


def _phase_return(entries):
    return {"findings": [], "preExisting": [],
            "intent": {"answer": "matches", "note": "n", "missing": []},
            "verdict": "clean", "tasks": entries}


def _phase(tasks, key=None, findings=None):
    phase = {"id": "P1", "tasks": tasks}
    if key is not None:
        phase["reviewPerTask"] = key
    if findings is not None:
        phase["review"] = {"findings": findings}
    return phase


def _held_cases(check):
    """The per-task review's key, read once per phase and kept by the task, and
    the one property a landing asks of the plan's record under `phase`."""
    t = {"id": "P1.1", "commit": _SHA}
    check("pk1 the key is the task's own when it records one, else its phase's, "
          "else the live config's - and the answer names which it was",
          M.review_key(dict(t, reviewPerTask="always"), _phase([], "phase"),
                       "phase") == ("always", "task")
          and M.review_key(t, _phase([], "always"), "phase") == ("always", "phase")
          and M.review_key(t, _phase([]), "phase") == ("phase", "config"))
    # The second direction: a key recorded nowhere is NOT read as `always`.
    check("pk2 a key recorded nowhere reads the live config, never `always` by "
          "default: %r" % (M.review_key(t, _phase([]), "phase"),),
          M.review_key(t, _phase([]), "phase")[0] == "phase"
          and M.review_key(t, _phase([]), "always")[0] == "always")

    with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                           "audit-plan.schema.json"), "r", encoding="utf-8") as fh:
        ic = json.load(fh)["$defs"]["intentCheck"]["properties"]
    check("pk4 the reviewer-only grade is `_refs`'s, and the red-first and "
          "inherited-test words a phase entry may carry are the plan schema's "
          "`intentCheck` enums, so the filing verb holds no vocabulary of its "
          "own: %r" % ((ic.get("redFirst"), ic.get("inheritedTests")),),
          M.REVIEWER_ONLY_RED_FIRST == tuple(_refs.RED_FIRST_REVIEWER_ONLY)
          and list(M.INHERITED_WORDS) == (ic.get("inheritedTests") or {})
          .get("enum")
          and list(M.RED_FIRST_WORDS + M.REVIEWER_ONLY_RED_FIRST)
          == (ic.get("redFirst") or {}).get("enum")
          and M.INTENT_DEFERRED in ((ic.get("answer") or {}).get("enum") or []))

    fix = dict(t, fixes=["P1-R1"])
    linked = [{"id": "P1-R1", "fixTask": "P1.1"}]
    check("pk3 a task is a recorded fix task only while it carries `fixes` and "
          "every finding it names, in its own phase's review, names it as "
          "`fixTask` - the link alone is not the key, and a link moved away "
          "ends it",
          M.is_fix_task(fix, _phase([fix], findings=linked))
          and not M.is_fix_task(t, _phase([t], findings=linked))
          and not M.is_fix_task(fix, _phase([fix], findings=[
              {"id": "P1-R1", "fixTask": "P1.9"}]))
          and not M.is_fix_task(fix, _phase([fix], findings=[])))

    ok = dict(t, reviewPerTask="phase", intentCheck=_answered())
    deferred = dict(t, reviewPerTask="phase",
                    intentCheck={"answer": "deferred", "commit": _SHA})
    check("pp1 ALLOW: under `phase`, a task whose intentCheck carries the three "
          "answers bound to its commit passes the property",
          M.landing_refusals(_phase([ok]), "phase") == [])
    check("pp2 a task closed `deferred` fails the property, named by id",
          [r[0] for r in M.landing_refusals(_phase([deferred]), "phase")]
          == ["P1.1"])
    missing = []
    for field in ("answer", "redFirst", "inheritedTests"):
        block = _answered()
        block.pop(field)
        if not M.landing_refusals(_phase([dict(ok, intentCheck=block)]), "phase"):
            missing.append(field)
    check("pp3 each of the three answers removed alone fails the property: %r"
          % (missing,), missing == [])
    check("pp4 answers bound to another commit fail the property - the task's "
          "own commit moved, or the answer's",
          M.landing_refusals(_phase([dict(ok, commit=_SHA2)]), "phase")
          and M.landing_refusals(_phase([dict(ok, intentCheck=_answered(
              commit=_SHA2))]), "phase"))
    check("pp5 an inherited-test `not-asked` needs its basis",
          M.landing_refusals(_phase([dict(ok, intentCheck=_answered(
              inheritedTests="not-asked", inheritedTestsBasis=""))]), "phase")
          and not M.landing_refusals(_phase([dict(ok, intentCheck=_answered(
              inheritedTests="not-asked", inheritedTestsBasis="whole suite"))]),
              "phase"))
    fixed = dict(fix, reviewPerTask="phase",
                 intentCheck={"answer": "not-asked", "basis": "a fix task",
                              "commit": _SHA})
    check("pp6 ALLOW: a recorded fix task closed `not-asked` with its basis "
          "passes; the same record on a task with no `fixes` fails",
          M.landing_refusals(_phase([fixed], findings=linked), "phase") == []
          and M.landing_refusals(_phase([dict(fixed, fixes=None)],
                                        findings=linked), "phase"))
    # The second direction: the property must not fire where G1 is off.
    check("pp7 ALLOW: a task whose key reads `always` - its own, its phase's or "
          "the live config's - and a task with no commit are not asked",
          M.landing_refusals(_phase([dict(deferred, reviewPerTask="always")]),
                             "phase") == []
          and M.landing_refusals(_phase([{"id": "P1.1", "intentCheck": {}}]),
                                 "phase") == []
          and M.landing_refusals(_phase([dict(t, intentCheck={})]),
                                 "always") == [])

    # ---- the phase return ----------------------------------------------------
    two = _phase([dict(t, reviewPerTask="phase"),
                  {"id": "P1.2", "commit": _SHA2, "reviewPerTask": "phase"}])
    good = _phase_return([_entry(), _entry("P1.2", _SHA2)])
    check("ps1 ALLOW: a phase return with one whole entry per task owed an "
          "answer has no problem: %r"
          % (M.phase_return_problems(good, two, "phase", {}),),
          M.phase_return_problems(good, two, "phase", {}) == [])
    short = M.phase_return_problems(_phase_return([_entry()]), two, "phase", {})
    check("ps2 a return lacking the entry of a task owed an answer is refused "
          "naming that task: %r" % (short,),
          any("P1.2" in p for p in short))
    stray = M.phase_return_problems(_phase_return(
        [_entry(), _entry("P1.2", _SHA2), _entry("P9.9")]), two, "phase", {})
    moved = M.phase_return_problems(_phase_return(
        [_entry(), _entry("P1.2", _SHA)]), two, "phase", {})
    check("ps3 an entry naming a task outside the phase, or a commit other than "
          "the one its task records, is named: %r" % ((stray, moved),),
          any("P9.9" in p for p in stray) and any(_SHA[:12] in p for p in moved))
    earlier = M.phase_return_problems(
        good, two, "phase", {("P1.1", _SHA): ("returns/P1/x.reviewer.json", {})})
    check("ps4 an entry for a commit an earlier filed return already answers is "
          "refused, and the task it names is then not owed: %r" % (earlier,),
          any("already answers" in p for p in earlier)
          and M.phase_return_problems(
              _phase_return([_entry("P1.2", _SHA2)]), two, "phase",
              {("P1.1", _SHA): ("returns/P1/x.reviewer.json", {})}) == [])
    lacking = []
    for key in M.PHASE_ENTRY_KEYS:
        entry = _entry()
        entry.pop(key)
        if not M.phase_return_problems(_phase_return(
                [entry, _entry("P1.2", _SHA2)]), two, "phase", {}):
            lacking.append(key)
    check("ps5 every key of the entry is one whose absence is refused: %r"
          % (lacking,), lacking == [])
    bare = M.phase_return_problems(_phase_return(
        [_entry(inheritedTestsBasis=""), _entry("P1.2", _SHA2)]), two, "phase",
        {})
    check("ps6 `not-asked` with no basis is refused", bare != [])
    check("ps7 a return with no `tasks` array at all is refused as the old "
          "definition's shape, naming the entries it owes",
          any("P1.1" in p for p in M.phase_return_problems(
              dict(good, tasks=None), two, "phase", {})))
    check("ps8 the phase return's path is keyed on the head its brief was "
          "computed at: %r" % (M.phase_return_rel("P1", _SHA),),
          M.phase_return_rel("P1", _SHA)
          == "returns/P1/%s.reviewer.json" % (_SHA,))


def _absent(*_args, **_kw):
    """Stands in for a function the module does not define yet, so a case asks
    its question and fails it rather than raising out of the block."""
    return None


def _helper_block():
    """A red-first block as `stamp-verification.py red` writes it - its own
    `red_verdict` over a run with no HEAD baseline - never a hand-typed copy."""
    import _loader                                 # noqa: E402  (load_script)
    sv = _loader.load_script("stamp-verification.py",
                             modname="stamp_verification_for_fr")
    run = {"cmd": ["python3", "tests/test_mine.py"], "code": 1,
           "text": "AssertionError\n", "problem": None, "second": None,
           "head": None, "fix": None}
    ctx = {"root": None, "implementation": [], "tests": ["tests/test_mine.py"],
           "cases": [], "symbols": [], "dropped": [], "new": [],
           "head_files": None, "head_defs": None, "head_modules": None,
           "path": None}
    return sv.red_verdict(run, ctx)[2]


def _mechanical_cases(check):
    """The answers of a phase review a script gives: the red-first word when
    the executor's block is the helper's, and `not-asked` when the gate runs the
    whole project - filled at filing, and left to the reviewer everywhere else."""
    helper_red = getattr(M, "helper_red_first", _absent)
    gate_reading = getattr(M, "gate_reading", _absent)
    is_test = getattr(M, "is_test_path", _absent)
    answers_of = getattr(M, "mechanical_answers", _absent)
    complete = getattr(M, "complete_phase_return", _absent)

    block = _helper_block()
    typed = {"status": "proved", "basis": "python3 t.py exit 1", "at": "z"}
    check("ma1 the helper's own block - written by stamp-verification's "
          "`red_verdict`, not typed here - reads as the helper's, and a block "
          "typed by hand with the same word does not: %r" % ((block,),),
          isinstance(block, dict)
          and helper_red(_executor(redFirst=block)) == block
          and helper_red(_executor(redFirst=typed)) is None
          and helper_red(None) is None)

    build = {"test": "python3 -m pytest tests", "sweep": "python3 tools/sweep.py"}

    def kind(entries):
        resolved = [(e, build.get(e, e)) for e in entries]
        return (gate_reading(build, resolved) or (None, ""))[0]
    whole = [kind(["test"]), kind(["sweep"]), kind(["npx vitest run"]),
             kind(["true"])]
    named = [kind(["python3 tests/test_refund.py --selftest"]),
             kind(["python3 -m pytest -k refund"]),
             kind(["pytest tests/test_a.py::test_b"]),
             kind(["npx vitest run --testNamePattern=refund"]),
             kind(["test", "python3 tests/test_refund.py"])]
    unknown = [kind([]), kind(["unit:api"]), kind(["python3 'unclosed"])]
    check("ma2 a gate runs the whole project only when every entry resolves and "
          "no command names a test file or a selection flag; one that names "
          "either selects named tests, and no entry, an unresolved `key:project` "
          "or a command that will not split is unknown: %r"
          % ((whole, named, unknown),),
          whole == ["whole"] * 4 and named == ["named"] * 5
          and unknown == ["unknown"] * 3)
    paths = dict((p, bool(is_test(p))) for p in (
        "tests/test_refund.py", "lib/specs/test__x.rb",
        "tools/ui-tests/a.test.js", "src/b.spec.ts", "pkg/x_test.go",
        "tests/unit/helpers.py", "src/refund.py", "tests", "tools/sweep.py",
        "docs/testing.md"))
    check("ma3 a test path is a file named as a test or one inside a test "
          "directory; a source file, a runner and a bare test directory are "
          "not: %r" % (paths,),
          [p for p, v in paths.items() if v] == [
              "tests/test_refund.py", "lib/specs/test__x.rb",
              "tools/ui-tests/a.test.js", "src/b.spec.ts", "pkg/x_test.go",
              "tests/unit/helpers.py"])

    rel = "returns/P1.1/20260101T000000Z.executor.json"
    got = answers_of((rel, _executor(redFirst=block), None),
                     ("whole", "the gate runs the whole project")) or ({}, {})
    check("ma4 a helper block and a whole-project gate give every mechanical field "
          "- the helper's word, a basis quoting its basis and naming the "
          "return, and `not-asked` with the gate's basis - and owe nothing: %r"
          % (got,),
          got[0].get("redFirst") == block["status"]
          and block["basis"] in got[0].get("redFirstBasis", "")
          and rel in got[0].get("redFirstBasis", "")
          and got[0].get("inheritedTests") == "not-asked"
          and "whole project" in got[0].get("inheritedTestsBasis", "")
          and got[1] == {})
    owed_typed = answers_of((rel, _executor(redFirst=typed), None),
                            ("named", "the gate names tests/test_a.py")) or ({}, {})
    owed_none = answers_of((rel, None, None), ("whole", "w")) or ({}, {})
    owed_bad = answers_of((rel, None, "%s cannot be read as JSON" % rel),
                          ("unknown", "unit:api resolves to nothing")) or ({}, {})
    check("ma5 REFUSAL TWINS of ma4: a hand-typed red-first, a gate naming "
          "tests, no executor return and an unreadable one each leave that "
          "answer to the reviewer, the reason said: %r"
          % ((owed_typed, owed_none, owed_bad),),
          set(owed_typed[0]) == set() and set(owed_typed[1]) == {
              "redFirst", "inheritedTests"}
          and "tests/test_a.py" in owed_typed[1]["inheritedTests"]
          and set(owed_none[0]) == {"inheritedTests", "inheritedTestsBasis"}
          and rel in owed_none[1].get("redFirst", "")
          and "cannot be read" in owed_bad[1].get("redFirst", "")
          and "unit:api" in owed_bad[1].get("inheritedTests", ""))

    two = _phase([{"id": "P1.1", "commit": _SHA, "reviewPerTask": "phase"},
                  {"id": "P1.2", "commit": _SHA2, "reviewPerTask": "phase"}])
    computed = {"P1.1": got[0], "P1.2": owed_typed[0]}
    bare = _entry()
    for key in ("redFirst", "redFirstBasis", "inheritedTests",
                "inheritedTestsBasis"):
        bare.pop(key)
    filed, filled, problems = complete(
        _phase_return([bare, _entry("P1.2", _SHA2)]), computed) or (
            {}, {}, ["not completed"])
    entry = ((filed.get("tasks") or [{}])[0]) if isinstance(filed, dict) else {}
    check("ma6 a phase return filed without the mechanical fields is completed "
          "from the executor's filed block and the gate's shape, the filled "
          "fields recorded under `computedAnswers`, and the completed return "
          "has no problem: %r" % ((entry, filled, problems),),
          problems == [] and entry.get("redFirst") == block["status"]
          and entry.get("inheritedTests") == "not-asked"
          and filed.get("computedAnswers") == {"P1.1": [
              "redFirst", "redFirstBasis", "inheritedTests",
              "inheritedTestsBasis"]}
          and M.phase_return_problems(filed, two, "phase", {}) == [])
    short = _entry("P1.2", _SHA2)
    short.pop("inheritedTests")
    short.pop("redFirst")
    filed2, _f2, p2 = complete(_phase_return([bare, short]), computed) or (
        {}, {}, [])
    left = M.phase_return_problems(filed2, two, "phase", {}) if filed2 else []
    check("ma7 REFUSAL TWIN of ma6: the task whose red-first the helper did not "
          "grade and whose gate names tests gets neither filled, so the entry "
          "lacking them is refused naming each: %r" % (left,),
          p2 == [] and any("P1.2" in p and "`redFirst`" in p for p in left)
          and any("P1.2" in p and "`inheritedTests`" in p for p in left))
    same, same_filled, same_p = complete(_phase_return([_entry(
        redFirst=block["status"]), _entry("P1.2", _SHA2)]), computed) or (
            {}, {"x": 1}, ["not completed"])
    _d, _df, differ = complete(_phase_return([_entry(
        redFirst="not-proved"), _entry("P1.2", _SHA2)]), computed) or (
            {}, {}, [])
    _t, _tf, forged = complete(dict(_phase_return([bare]), computedAnswers={
        "P1.1": ["redFirst"]}), computed) or ({}, {}, [])
    check("ma8 a reviewer word equal to the computed one files as typed and is "
          "not recorded as computed; one that differs, and a typed "
          "`computedAnswers`, are refused by name: %r"
          % ((same_filled, same_p, differ, forged),),
          same_p == [] and same_filled == {}
          and "computedAnswers" not in same
          and same.get("tasks", [{}])[0].get("redFirstBasis")
          == _entry()["redFirstBasis"]
          and any("not-proved" in p and "P1.1" in p for p in differ)
          and any("computedAnswers" in p for p in forged))


def _selftest():
    def body(check):
        _harness.stage(check, "fr-block", _cases)
        _harness.stage(check, "ma-block", _mechanical_cases)
        _harness.stage(check, "pk-block", _held_cases)
        _harness.stage(check, "hn-block", _human_cases)
        _harness.stage(check, "dm-block", _drive_mark_cases)
        _harness.stage(check, "rd-block", _read_set_cases)
    return _harness.run(body)


def _drive_mark_cases(check):
    """The driver's state read whole, for what the sign-off verb's remedy says
    the driver will do next, and a return's text parsed by the one rule a
    landing reading the branch tip shares with the read off disk."""
    root = _harness.fixture_root("filed-returns-mark-")
    try:
        none_yet = M.drive_state(root, "P1")
        path = M.drive_state_path(root, "P1")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({M.REVIEW_MARK_FIELD: {"head": "abc1234"}}, fh)
        marked = M.drive_state(root, "P1")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({M.REVIEW_MARK_FIELD: {"findings": True}}, fh)
        headless = M.drive_state(root, "P1")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        broken = M.drive_state(root, "P1")
        check("dm1 no state is `{}` and no mark; a mark with a head is marked; "
              "one with no head is not - the driver re-dispatches there too; and "
              "a file that will not parse is a problem, never an empty state: %r"
              % ((none_yet, marked, headless, broken[1][:50]),),
              none_yet == ({}, "") and not M.review_marked(none_yet[0])
              and M.review_marked(marked[0]) and marked[1] == ""
              and not M.review_marked(headless[0])
              and broken[0] == {} and broken[1])
    finally:
        _harness.remove_tree(root)
    ok, bad, gone = (M.return_body('{"verdict": "clean"}', "x"),
                     M.return_body("{not json", "tip:x"),
                     M.return_body(None, "tip:y"))
    check("dm2 a return's text parses to its body; text that will not parse and "
          "text that could not be read are each a problem naming the label, "
          "never an empty body: %r" % ((ok, bad, gone),),
          ok == ({"verdict": "clean"}, None) and bad[0] is None
          and "tip:x" in bad[1] and gone[0] is None and "tip:y" in gone[1])


def _hn_body(entries, intent="matches"):
    return {"findings": [], "preExisting": [], "verdict": "clean",
            "intent": {"answer": intent, "note": "phase note", "missing": []},
            "tasks": entries}


def _hn_entry(tid, **over):
    entry = {"id": tid, "commit": _SHA, "answer": "matches", "note": "n",
             "missing": [], "redFirst": "proved", "redFirstBasis": "rb",
             "inheritedTests": "not-asked", "inheritedTestsBasis": "ib"}
    entry.update(over)
    return entry


def _human_cases(check):
    """The answers only a human settles - one predicate the sign-off verb and
    the driver's triage both read - and the settlement record they are read
    against."""
    rel = "returns/P1/abc1234.reviewer.json"
    mixed = [(rel, _hn_body([
        _hn_entry("P1.1", answer="diverges", note="does the other thing"),
        _hn_entry("P1.2", redFirst="not-proved", redFirstBasis="no red seen"),
        _hn_entry("P1.3", inheritedTests="flagged", inheritedTestsBasis="t.py"),
        _hn_entry("P1.4")], intent="cannot-tell"), "")]
    got = M.needs_human(mixed)
    check("hn1 a `diverges` intent, a `not-proved` red-first grade, a `flagged` "
          "inherited test and a phase intent of `cannot-tell` are each one "
          "answer for a human, keyed by return, task and word, with the "
          "reviewer's note - and the `matches` entry beside them is none: %r"
          % (got,),
          [(a["key"], a["who"], a["what"], a["note"]) for a in got] == [
              (rel + "#P1.1#intent diverges", "P1.1", "intent diverges",
               "does the other thing"),
              (rel + "#P1.2#red-first not-proved", "P1.2",
               "red-first not-proved", "no red seen"),
              (rel + "#P1.3#inherited tests flagged", "P1.3",
               "inherited tests flagged", "t.py"),
              (rel + "#phase", "phase", "intent cannot-tell", "phase note")])
    # The second direction: a predicate firing on every answer fails here.
    clean = [(rel, _hn_body([_hn_entry("P1.1"), _hn_entry("P1.2")]), "")]
    check("hn2 ALLOW: a return answering `matches`, `proved` and `not-asked` "
          "throughout holds nothing for a human, and an unreadable return "
          "(its body None) adds nothing here - it is the filing reader's "
          "refusal: %r" % (M.needs_human(clean + [(rel, None, "bad json")]),),
          M.needs_human(clean + [(rel, None, "bad json")]) == [])
    keys = [a["key"] for a in got]
    left = M.needs_human(mixed, settled=keys[:2])
    check("hn3 a settled key is not asked again and an unsettled one still is: "
          "%r" % ([a["key"] for a in left],),
          [a["key"] for a in left] == keys[2:]
          and M.needs_human(mixed, settled=keys) == [])

    root = _harness.fixture_root("filed-returns-settle-")
    try:
        path = M.drive_state_path(root, "P1")
        none_yet = M.settled_answers(root, "P1")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({M.SETTLED_FIELD: {"keys": keys[:1],
                                         "reasons": ["the human's words"]}}, fh)
        recorded = M.settled_answers(root, "P1")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        broken = M.settled_answers(root, "P1")
        check("hn4 the settlement is read off the driver's state for the phase: "
              "no file is nothing settled, a recorded accept is its keys and "
              "reasons, and a file that will not parse is a problem, never "
              "nothing settled: %r" % ((none_yet, recorded, broken[2][:60]),),
              path == os.path.join(root, "drive", "P1.json")
              and none_yet == (set(), [], "")
              and recorded == (set(keys[:1]), ["the human's words"], "")
              and broken[0] == set() and broken[2])
    finally:
        _harness.remove_tree(root)

    import _loader                                 # noqa: E402  (load_script)
    drive = _loader.load_script("drive-phase.py")
    ev = _harness.fixture_root("filed-returns-drive-")
    try:
        folder = os.path.join(ev, M.RETURNS_DIRNAME, "P1")
        os.makedirs(folder)
        with open(os.path.join(folder, "abc1234.reviewer.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(mixed[0][1], fh)
        theirs = drive.human_answers({"evidence": ev}, {"id": "P1"})
        ours = M.needs_human(M.phase_returns(ev, "P1"))
        state = drive.state_path({"stateDir": ev, "phase": "P1"})
        check("hn5 the driver's triage reads the same answers the sign-off verb "
              "does, and keeps its state at the path the verb reads the "
              "settlement from - two readings here would let one route sign "
              "off what the other stops: %r"
              % ((len(theirs), len(ours), state),),
              theirs == ours and len(ours) == 4
              and state == M.drive_state_path(ev, "P1"))
    finally:
        _harness.remove_tree(ev)
    _bound_settlement_cases(check, rel, mixed)


def _bound_settlement_cases(check, rel, mixed):
    """A human's settlement binds to the answer it settled - the return's
    content signature - never to the name alone, which another answer filed
    later under the same name would share."""
    first = M.needs_human(mixed)
    sig = M.return_signature(mixed[0])
    check("hn6 every answer for a human carries the signature of the return it "
          "came from - the content a settlement binds to: %r"
          % (sorted(set(a.get("sha256") for a in first)),),
          len(first) == 4 and all(a.get("sha256") == sig for a in first))
    other = [(rel, _hn_body([_hn_entry("P1.1", answer="diverges",
                                       note="another note")]), "")]
    pairs = set((a["key"], a["sha256"]) for a in first)
    same_name = M.needs_human(other, bound=pairs)
    check("hn7 a settlement bound to one answer's signature does not cover "
          "another answer filed under the same name: %r"
          % ([a["key"] for a in same_name],),
          [a["key"] for a in same_name] == [rel + "#P1.1#intent diverges"])
    check("hn7b THE ALLOW TWIN: ...and it covers the answer it was given for, "
          "a byte-identical copy included: %r" % (M.needs_human(
              json.loads(json.dumps(mixed)), bound=pairs),),
          M.needs_human([tuple(e) for e in json.loads(json.dumps(mixed))],
                        bound=pairs) == [])

    held = M.settlement_after({}, first[:2], "the human's word")
    again = M.settlement_after(held, first[2:3], "a second word")
    check("hn8 the record a settlement writes keeps the key list older readers "
          "read and adds one key-and-signature entry per answer, appending "
          "across settlements: %r" % (again,),
          again["keys"] == [a["key"] for a in first[:3]]
          and again["reasons"] == ["the human's word", "a second word"]
          and again[M.SIGNATURES_FIELD] == [
              {"key": a["key"], "sha256": sig} for a in first[:3]])

    root = _harness.fixture_root("filed-returns-bound-")
    other_dir = _harness.fixture_root("filed-returns-bound-other-")
    try:
        for where, block in ((root, {"keys": [first[0]["key"]],
                                     "reasons": ["by name only"]}),
                             (other_dir, again)):
            path = M.drive_state_path(where, "P1")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({M.SETTLED_FIELD: block}, fh)
        named = M.settlement_record(root, "P1")
        both = M.settlements([root, other_dir, other_dir], "P1")
        check("hn9 a record naming keys alone binds no signature; read across "
              "several checkouts' records, the bound pairs and the keys are "
              "each one union and a directory named twice is read once: %r"
              % ((named, both),),
              named["pairs"] == set() and named["keys"] == set([first[0]["key"]])
              and both["pairs"] == set((a["key"], sig) for a in first[:3])
              and both["keys"] == set(a["key"] for a in first[:3])
              and both["reasons"] == ["by name only", "the human's word",
                                      "a second word"]
              and both["problems"] == [])
        only_named = M.settled_by_name_only(first, named)
        check("hn10 the answers a record settles by name only - the key there, "
              "its signature not - are named so a refusal can say how to "
              "settle them again: %r" % ([a["key"] for a in only_named],),
              [a["key"] for a in only_named] == [first[0]["key"]]
              and M.settled_by_name_only(first, both) == [])
        with open(M.drive_state_path(root, "P1"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        broken = M.settlements([root, other_dir], "P1")
        check("hn11 a record that will not parse is a problem the union keeps, "
              "never read as nothing settled there: %r" % (broken["problems"],),
              len(broken["problems"]) == 1
              and broken["pairs"] == set((a["key"], sig) for a in first[:3]))
    finally:
        _harness.remove_tree(root)
        _harness.remove_tree(other_dir)

    top = _harness.fixture_root("filed-returns-checkouts-")
    try:
        main, linked, gone = (os.path.join(top, n) for n in ("main", "wt", "gone"))
        for path in (os.path.join(main, "sub"), os.path.join(linked, "sub")):
            os.makedirs(path)
        trees = [{"path": main}, {"path": linked},
                 {"path": gone, "prunable": True}]
        found = M.settlement_checkouts(main, os.path.join(main, "sub"), trees)
        check("hn12 the checkouts whose settlement records count are the "
              "project's and the same project inside every worktree git lists, "
              "each once, a prunable one skipped: %r" % (found,),
              [os.path.realpath(p) for p in found]
              == [os.path.realpath(os.path.join(main, "sub")),
                  os.path.realpath(os.path.join(linked, "sub"))])
    finally:
        _harness.remove_tree(top)


def _git_repo(root):
    """`git -C root ...` in a fresh repository on `main` with a repo-local
    identity, returning the CompletedProcess."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", "-C", root] + list(a),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    return git


def _put_return(evidence, phase_id, head, body):
    rel = M.phase_return_rel(phase_id, head)
    path = os.path.join(evidence, *rel.split("/"))
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    return rel


def _read_set_cases(check):
    """What a sign-off records as read, and the one signature a landing
    compares against it - one definition for both verbs, so a copy of a read
    return is covered wherever it sits and a different answer never is."""
    a = ("returns/P1/abc1234.reviewer.json", _reviewer("diverges"), None)
    a_copy = ("returns/P1/abc1234.reviewer.json",
              json.loads(json.dumps(_reviewer("diverges"))), None)
    other_answer = ("returns/P1/abc1234.reviewer.json", _reviewer("matches"),
                    None)
    other_name = ("returns/P1/def5678.reviewer.json", _reviewer("diverges"),
                  None)
    unread = ("returns/P1/abc1234.reviewer.json", None, "will not parse")
    sig = M.return_signature
    check("rd1 a copy of a return signs the same wherever it was read from; "
          "another answer under the name, the answer under another name, and "
          "a copy that will not parse each sign differently: %r"
          % ([sig(e)[:12] for e in (a, a_copy, other_answer, other_name,
                                    unread)],),
          sig(a) == sig(a_copy)
          and len(set(sig(e) for e in (a, other_answer, other_name,
                                       unread))) == 4)
    record = M.read_record([other_name, a, a_copy])
    check("rd2 the record a sign-off writes is one row per distinct return, "
          "in a total order, naming each return beside its signature: %r"
          % (record,),
          record == sorted(record, key=lambda r: (r["return"], r["sha256"]))
          and len(record) == 2
          and set(r["sha256"] for r in record) == set([sig(a), sig(other_name)])
          and set(r["return"] for r in record) == set([a[0], other_name[0]]))
    absent = M.read_set({"status": "passed"})
    empty = M.read_set({"status": "passed", M.READ_RETURNS_FIELD: []})
    held = M.read_set({"status": "passed", M.READ_RETURNS_FIELD: record})
    check("rd3 a verdict recording no read set reads as None - the landing's "
          "older reading - and one recording an empty set reads as the empty "
          "set, never as None: %r" % ((absent, empty, held),),
          absent is None and empty == set() and isinstance(empty, set)
          and held == set([sig(a), sig(other_name)])
          and M.read_set(None) is None)
    names = M.read_names({"status": "passed", M.READ_RETURNS_FIELD: record})
    check("rd3n the names a verdict records as read are their own reading - "
          "what a landing compares a later return's name against - and a "
          "verdict recording no read set names none: %r" % (names,),
          names == set([a[0], other_name[0]])
          and M.read_names({"status": "passed"}) == set())

    root = _harness.fixture_root("filed-returns-tip-")
    outside = _harness.fixture_root("filed-returns-tip-outside-")
    try:
        git = _git_repo(root)
        evidence = os.path.join(root, "docs", "audit", "evidence")
        with open(os.path.join(root, "seed.txt"), "w") as fh:
            fh.write("seed\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "audit/p1")
        rel = _put_return(evidence, "P1", "abc1234", _reviewer("diverges"))
        git("add", "-A")
        git("commit", "-q", "-m", "return")
        _put_return(evidence, "P1", "def5678", _reviewer("matches"))
        at_tip, why = M.tip_phase_returns(root, evidence, "audit/p1", "P1")
        on_main, _w = M.tip_phase_returns(root, evidence, "main", "P1")
        nowhere, gone_why = M.tip_phase_returns(root, evidence, "no-such",
                                                "P1")
        out, out_why = M.tip_phase_returns(root, outside, "audit/p1", "P1")
        check("rd4 a ref's committed returns are read off git, named as the "
              "filing verb names them on disk - an uncommitted return is not "
              "the tip's; a ref with none commits none; a ref git does not "
              "have, and evidence outside the repository, are said, never "
              "read as an empty tip: %r"
              % ((at_tip, why, on_main, nowhere, gone_why, out, out_why),),
              [(r, b) for r, b, _p in at_tip] == [(rel, _reviewer("diverges"))]
              and why == "" and on_main == [] and nowhere == []
              and "no-such" in gone_why and out == [] and out_why)
    finally:
        _harness.remove_tree(root)
        _harness.remove_tree(outside)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__filed_returns.py --selftest\n")
    raise SystemExit(2)
