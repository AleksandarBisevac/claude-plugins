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


def _selftest():
    def body(check):
        _harness.stage(check, "fr-block", _cases)
        _harness.stage(check, "pk-block", _held_cases)
    return _harness.run(body)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__filed_returns.py --selftest\n")
    raise SystemExit(2)
