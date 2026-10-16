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
import ast
import hashlib
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _output                                     # noqa: E402  (PLUGIN_ROOT, the agent briefs)
import _refs                                       # noqa: E402  (the brief's return block, the schema enum)
import _filed_returns as M                         # noqa: E402
import _journal_io                                 # noqa: E402  (pins `M.return_digest` to `file_hash`)

_START = "2026-01-01T00:00:00Z"


def _executor(**over):
    body = {"gates": {"python3 t.py": "pass"},
            "redFirst": {"status": "proved", "basis": "the run exited non-zero on its own case",
                         "at": "z"},
            "outcome": {"technical": "ran the gate command and it exited zero",
                        "descriptive": "the change landed and the gate stayed green"},
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

    placeholder = M.return_problems("executor", _executor(
        outcome={"technical": "placeholder", "descriptive": "placeholder"}))
    short = M.return_problems("executor", _executor(
        outcome={"technical": "did it", "descriptive": "done"}))
    check("rp13 an outcome whose `technical` and `descriptive` are both the "
          "bare word `placeholder` is refused - named for the template word "
          "and the identical pair - and so is one that merely falls under "
          "the stated floor, before anything is written: %r"
          % ((placeholder, short),),
          any("placeholder" in p for p in placeholder)
          and any("identical" in p for p in placeholder)
          and any("outcome.technical" in p and "floor" in p for p in short)
          and any("outcome.descriptive" in p and "floor" in p for p in short))

    tdd_task = dict(task, tests={"mode": "tdd",
                                 "add": ["tests/test_x.py: a case worth filing"]})
    empty_added = M.return_problems("executor", _executor(testsAdded=[]), tdd_task)
    filed_added = M.return_problems(
        "executor", _executor(testsAdded=["tests/test_x.py: a case worth filing"]),
        tdd_task)
    gate_only_task = dict(task, tests={"mode": "gate-only", "add": []})
    check("rp14 a tdd or regression return with `testsAdded` empty while the "
          "task's tests.add names a case is refused by naming `testsAdded`; "
          "one that files the case is not, and a gate-only task with no "
          "`tests.add` is never asked: %r"
          % ((empty_added, filed_added),),
          any("testsAdded" in p for p in empty_added)
          and filed_added == []
          and M.return_problems("executor", _executor(testsAdded=[]),
                                gate_only_task) == [])

    # The refusal is of an outcome that IS a placeholder - the whole trimmed
    # text, never a template word or a `<...>` span merely present somewhere
    # in a real sentence. Replayed over outcome text copied verbatim from
    # filed returns of this phase (fixtures, not a read of the evidence
    # directory at test time: a suite's cwd is pointed at scratch space under
    # `tools/sweep-selftests.py`, so a path relative to the project would read
    # nothing there) - every placeholder-shaped one refused, every real one
    # not, even where the real text uses the word "placeholder" to describe
    # the feature or carries a `<home>/...`- or `<taskId>`-shaped path.
    _PLACEHOLDER_OUTCOMES = (
        ("P125.1/20261013T125847Z", "placeholder", "placeholder"),
        ("P125.2/20261013T141945Z", "placeholder", "placeholder"),
        ("P125.11/20261013T144615Z", "pending", "pending"),
        ("P125.12/20261013T233613Z", "placeholder", "placeholder"),
        ("P125.22/20261013T175751Z", "placeholder", "placeholder"),
        ("P125.28/20261013T215547Z", "placeholder", "placeholder"),
        ("P125.36-0h5/20261014T022925Z", "placeholder", "placeholder"),
    )
    _REAL_OUTCOMES = (
        ("P125.18/20261014T010828Z",
         "Threaded a new chain line through drive-phase.py's finish() and a "
         "context-size reading through audit-status.py, reading the "
         "orchestrator's own transcript at <home>/projects/*/<sessionId>.jsonl "
         "for the snapshot, and naming the next phase as <next> when one is "
         "ready.",
         "A phase chain now tells the orchestrator to clear context before "
         "the next phase, and /audit:status names the orchestrator's own "
         "current context size."),
        ("P125.31-0h5/20261014T010832Z",
         "Factored the move/basename check into is_plugin_py_path(path) and "
         "moved_file_target(path, repo_root=None, index=None), the new home "
         "a plugin .py path <name> moved to, or None; audit-task.py now "
         "refuses a .py --files entry whose file moved elsewhere.",
         "add and scope now refuse a .py --files entry whose file moved "
         "elsewhere in the plugin, naming the new home."),
        ("P125.32-0h5/20261014T010836Z",
         "manifest_revalidated's breach now appends a write-provenance "
         "clause naming which journal row last wrote the index before the "
         "offending commit, composed as '(last written by <action> via "
         "<via> at <ts>)' or '(the write is not in the journal)'.",
         "An index-validity breach now names which journal-recorded "
         "command last wrote the manifest index before the offending "
         "commit, instead of leaving the operator to guess."),
        ("P125.8/20261013T215538Z",
         "New module _affected_tests.py selects suites a change can break "
         "by its related/python/e2e-changed/coupling/e2e-widening arms, "
         "run-test-gate.py now runs them attributed per arm, and every "
         "mutation this task relies on was confirmed to turn the guarding "
         "case red - none of this is a placeholder, the real work is the "
         "selection itself.",
         "A task's recorded gate now also runs every suite its change can "
         "break, each attributed to the arm that selected it."),
        ("P125.29-0h5/20261014T022918Z",
         "Added _outcome_problems() and _tests_add_empty_problem() so an "
         "executor return is refused whenever its outcome is a placeholder "
         "- the bare word, never a sentence that merely explains what a "
         "placeholder is while describing the feature.",
         "An agent can no longer file a placeholder or empty-testsAdded "
         "executor return through drive-phase.py submit."),
    )

    def _outcome_flagged(tech, desc):
        problems = M.return_problems("executor", _executor(
            outcome={"technical": tech, "descriptive": desc}))
        return any("outcome." in p or "identical" in p for p in problems)

    placeholder_misses = [name for name, t, d in _PLACEHOLDER_OUTCOMES
                          if not _outcome_flagged(t, d)]
    real_false_positives = [name for name, t, d in _REAL_OUTCOMES
                            if _outcome_flagged(t, d)]
    check("rp15 replayed over outcome text copied verbatim from filed "
          "returns of this phase: every placeholder-shaped one is refused "
          "and every real one passes, including one using the word "
          "\"placeholder\" in passing and ones carrying a `<home>/...`- or "
          "`<taskId>`-shaped path - the refusal is of an outcome that IS a "
          "placeholder, never one that merely CONTAINS one: misses=%r, "
          "false positives=%r" % (placeholder_misses, real_false_positives),
          placeholder_misses == [] and real_false_positives == [])

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
          and M.claims_from_return(root, {"id": "P1.2", "startedAt": _START},
                                   [], root)[1] is not None)
    claims, problem = M.claims_from_return(root, task, [], root)
    check("rp10 `claims_from_return` hands back the current start's `claims` "
          "verbatim, and None for a start with no return or a return without "
          "the field: %r" % (claims,),
          claims == "claims:\n1 n/a" and problem is None
          and M.claims_from_return(root, later, [], root) == (None, None)
          and M.claims_from_return(root, {"id": "P1.1"}, [], root)
          == (None, None))
    dirty = M.return_path(root, {"id": "P1.3", "startedAt": _START}, "executor")
    machine = "/Users/someone/work/proj/docs/audit/audit-plan.json"
    M.file_once(dirty, json.dumps(_executor(
        stamp='audit-stamp:{"manifest":"%s"}' % (machine,))) + "\n")
    with open(dirty, "r", encoding="utf-8", newline="") as fh:
        wrote = fh.read()
    check("rp11 a return carrying a machine path is filed with it scrubbed, "
          "and still parses as the same return otherwise: %r" % (wrote,),
          "someone" not in wrote and "/Users/" not in wrote
          and json.loads(wrote).get("gates") == _executor().get("gates"))
    clean = M.return_path(root, {"id": "P1.4", "startedAt": _START}, "executor")
    plain = json.dumps(_executor(
        stamp='audit-stamp:{"manifest":"docs/audit/audit-plan.json"}')) + "\n"
    M.file_once(clean, plain)
    with open(clean, "r", encoding="utf-8", newline="") as fh:
        check("rp12 THE ALLOW TWIN: a return with only a repo-relative path is "
              "filed byte for byte as given", fh.read() == plain)


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


def _um_cases(check):
    """`unsupported_match_basis` and its wiring into `return_problems`: a
    reviewer's `matches` note restating the executor's claim with none of the
    task's own words."""
    description = "src is set when the card enters the viewport"
    task = {"id": "P5.3", "description": description}
    quoting_note = ("the diff does what the description says - src is set "
                    "when the card enters the viewport, and nothing more")
    restating_note = ("ships a 200px rootMargin so the card loads near the "
                      "viewport before it is visible")
    check("um1 a `matches` note quoting the task's own clause holds up; one "
          "restating the claim with none of the task's words is named, "
          "quoting both: %r"
          % ((M.unsupported_match_basis(description, quoting_note),
             M.unsupported_match_basis(description, restating_note)),),
          M.unsupported_match_basis(description, quoting_note) is None
          and M.unsupported_match_basis(description, restating_note) is not None
          and description in M.unsupported_match_basis(description, restating_note)
          and restating_note in M.unsupported_match_basis(description,
                                                           restating_note))
    check("um2 no description, or no note, is nothing to grade - never a false "
          "unsupported: %r"
          % ((M.unsupported_match_basis("", restating_note),
             M.unsupported_match_basis(description, "")),),
          M.unsupported_match_basis("", restating_note) is None
          and M.unsupported_match_basis(description, "") is None)

    unsupported = M.return_problems("reviewer", {
        "findings": [], "verdict": "clean",
        "intent": {"answer": "matches", "note": restating_note}}, task)
    held = M.return_problems("reviewer", {
        "findings": [], "verdict": "clean",
        "intent": {"answer": "matches", "note": quoting_note}}, task)
    diverges = M.return_problems("reviewer", {
        "findings": [], "verdict": "findings",
        "intent": {"answer": "diverges", "note": restating_note}}, task)
    check("um3 `return_problems` refuses an unsupported `matches` when it is "
          "handed the task, files a quoting one, and never flags `diverges` "
          "or `cannot-tell` on this basis: %r"
          % ((unsupported, held, diverges),),
          any("unsupported" in p or "quotes no clause" in p for p in unsupported)
          and held == [] and diverges == [])


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

    # A round reviewed what its brief showed. A return records that in
    # `shown`; one filed before the list existed records it only in `tasks`.
    rounds = [("r1", {"tasks": [{"id": "P1.1", "commit": "a" * 12}]}, None),
              ("r2", {"tasks": [{"id": "P1.2", "commit": "b" * 12}],
                      "shown": [{"id": "P1.2", "commit": "b" * 12},
                                {"id": "P1.4", "commit": "e" * 12}]}, None),
              ("r3", {"tasks": [], "shown": [{"id": "P1.4",
                                              "commit": "e" * 12}]}, None)]
    seen = M.reviewed_entries(rounds) if hasattr(M, "reviewed_entries") else None
    check("pk5 what each round reviewed is its `tasks` entries and its `shown` "
          "list, keyed on the commit, the first return to name a commit "
          "winning; an older return with no list reads as its entries: %r"
          % (seen,),
          seen == {("P1.1", "a" * 12): "r1", ("P1.2", "b" * 12): "r2",
                   ("P1.4", "e" * 12): "r2"})
    parsed = [M.parse_shown(s) if hasattr(M, "parse_shown") else None
              for s in ("P1.1@%s,P1.4@%s" % ("a" * 12, "e" * 40), "",
                        "P1.1", "P1.1@zz", "P1.1@%s,P1.1@%s" % ("a" * 12,
                                                               "a" * 12))]
    check("pk6 a `--shown` list reads as its (id, commit) pairs in order, and "
          "an empty list, a pair with no commit, a commit that is not hex and "
          "a task named twice each read as a problem with no pairs: %r"
          % (parsed,),
          parsed[0] == ([("P1.1", "a" * 12), ("P1.4", "e" * 40)], None)
          and all(p is not None and p[0] == [] and p[1] for p in parsed[1:]))
    _shown_brief_cases(check)

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


def _shown_brief_cases(check):
    """The record a phase brief writes of the set it showed, read back: absent
    is not unreadable, and the refusal compares sets, not their order."""
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix="fr-shown-brief-")
    try:
        head = "c" * 40
        pairs = [("P1.1", "a" * 40), ("P1.4", "e" * 40)]
        none = M.read_shown_brief(root, "P1", head)
        path = M.shown_brief_path(root, "P1", head)
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(M.shown_brief_text(head, pairs))
        back = M.read_shown_brief(root, "P1", head)
        other_head = M.read_shown_brief(root, "P1", "d" * 40)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        broken = M.read_shown_brief(root, "P1", head)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    check("pk7 a brief's shown record reads back as the pairs it was written "
          "with; a head with no record reads as none, not as a problem; a "
          "record that will not parse reads as a problem, not as none: %r"
          % ((none, back, other_head, broken),),
          none == (None, None) and back == (pairs, None)
          and other_head == (None, None)
          and broken[0] is None and bool(broken[1]))
    same = M.shown_brief_refusal(pairs, list(reversed(pairs)), "p", head)
    empty_ok = M.shown_brief_refusal([], None, "p", head)
    absent = M.shown_brief_refusal(pairs, None, "p", head)
    fewer = M.shown_brief_refusal(pairs, pairs[:1], "p", head)
    extra = M.shown_brief_refusal([], pairs[:1], "p", head)
    want = "P1.1@%s,P1.4@%s" % ("a" * 40, "e" * 40)
    check("pk8 the refusal names the set the brief showed when the return "
          "carries none or another, and is None for the same pairs in another "
          "order or for a brief that showed nothing filed without `--shown`: %r"
          % ((same, empty_ok, absent, fewer, extra),),
          same is None and empty_ok is None
          and absent and want in absent and "no `--shown`" in absent
          and fewer and want in fewer
          and extra and "showed no task" in extra)


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
    block = sv.red_verdict(run, ctx)[2]
    # `drive-phase.py submit` marks the block it files from the helper's output.
    return dict(block, source=M.HELPER_SOURCE) if isinstance(block, dict) else block


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
    mark = getattr(M, "HELPER_SOURCE", None)
    bare = dict((k, v) for k, v in block.items() if k != "source")
    check("ma1 the helper's own block - written by stamp-verification's "
          "`red_verdict`, not typed here - reads as the helper's only once "
          "`drive-phase.py submit` has marked it; the helper's exact words with "
          "no mark, a block typed by hand with the same word, and a mark of "
          "another value are not: %r" % ((block,),),
          isinstance(block, dict) and bool(mark)
          and helper_red(_executor(redFirst=block)) == block
          and helper_red(_executor(redFirst=bare)) is None
          and helper_red(_executor(redFirst=dict(bare, source="typed"))) is None
          and helper_red(_executor(redFirst=typed)) is None
          and helper_red(None) is None)

    build = {"test": "python3 -m pytest tests", "sweep": "python3 tools/sweep.py",
             "selftests": "python3 tools/sweep-selftests.py"}

    def kind(entries):
        resolved = [(e, build.get(e, e)) for e in entries]
        return (gate_reading(build, resolved) or (None, ""))[0]
    whole = [kind(["sweep"]), kind(["npx vitest run"]), kind(["true"]),
             kind(["python3 tools/sweep-selftests.py"]), kind(["pytest"]),
             kind(["npm test"]), kind(["pytest -q"]), kind(["go test ./..."])]
    named = [kind(["python3 tests/test_refund.py --selftest"]),
             kind(["python3 -m pytest -k refund"]),
             kind(["pytest tests/test_a.py::test_b"]),
             kind(["npx vitest run --testNamePattern=refund"]),
             kind(["sweep", "python3 tests/test_refund.py"])]
    unknown = [kind([]), kind(["unit:api"]), kind(["python3 'unclosed"]),
               kind(["test"])]
    check("ma2 a gate reads as the whole project only when every entry resolves "
          "and each command is its runner with no operand and no flag outside "
          "the no-selection set; one naming a test file or a selection flag "
          "selects named tests, and no entry, an unresolved `key:project`, a "
          "command that will not split, or a runner handed a bare test "
          "directory is unknown: %r"
          % ((whole, named, unknown),),
          whole == ["whole"] * 8 and named == ["named"] * 5
          and unknown == ["unknown"] * 4)
    selecting = ("pytest -m unit", "pytest --deselect x",
                 "go test ./internal/auth/...", "cargo test auth::login",
                 "npx jest src/auth", "npx jest --testPathPattern auth",
                 "npx vitest run src/auth", "python -m unittest pkg.test_auth")
    read = dict((c, gate_reading({}, [(c, c)]) or (None, ""))
                for c in selecting)
    check("ma9 a command passing its runner an operand or a flag the reading "
          "does not know to select nothing reads `unknown`, never `whole`, and "
          "its basis names what was passed - the allow twins are ma2's bare "
          "runners: %r" % (read,),
          all(read[c][0] == "unknown" for c in selecting)
          and "`-m`" in read["pytest -m unit"][1]
          and "`auth::login`" in read["cargo test auth::login"][1]
          and "`pkg.test_auth`" in read["python -m unittest pkg.test_auth"][1])
    # A package script other than `test`, and a script file the plan's build
    # commands do not declare, are operands; each allow twin below is the
    # mutation that reads every script as part of its runner gone the other way.
    sweep = "python3 tools/sweep-selftests.py"
    declared = {"selftests": sweep, "unit": "npm run test:unit"}
    scripts = dict((label, (gate_reading(b, r) or (None, ""))) for label, b, r in (
        ("npm run test:unit", {}, [("npm run test:unit",) * 2]),
        ("unit key", declared, [("unit", "npm run test:unit")]),
        ("node scripts/test.js", {}, [("node scripts/test.js",) * 2]),
        ("undeclared sweep", {}, [(sweep, sweep)]),
        ("declared with more", {"u": "node scripts/test.js --only unit"},
         [("node scripts/test.js",) * 2]),
        ("npm test", {}, [("npm test",) * 2]),
        ("npm run test", {}, [("npm run test",) * 2]),
        ("yarn run test", {}, [("yarn run test",) * 2]),
        ("selftests key", declared, [("selftests", sweep)]),
        ("declared sweep -q", declared, [(sweep + " -q",) * 2])))
    check("ma12 a package script other than `test`, and a script file run by an "
          "interpreter that `meta.buildCommands` does not declare as a command of "
          "its own, read `unknown` with the script named; `npm test`, "
          "`npm run test` and a declared sweep read `whole`: %r" % (scripts,),
          [k for k, v in scripts.items() if v[0] == "unknown"] == [
              "npm run test:unit", "unit key", "node scripts/test.js",
              "undeclared sweep", "declared with more"]
          and [k for k, v in scripts.items() if v[0] == "whole"] == [
              "npm test", "npm run test", "yarn run test", "selftests key",
              "declared sweep -q"]
          and "`test:unit`" in scripts["npm run test:unit"][1]
          and "`scripts/test.js`" in scripts["node scripts/test.js"][1]
          and "`tools/sweep-selftests.py`" in scripts["undeclared sweep"][1])
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
    # The computed red-first here is the helper's `could-not-prove`, so a typed
    # `proved` LOWERS the work: the disagreement an escalation does not cover.
    _d, _df, differ = complete(_phase_return([_entry(
        redFirst="proved"), _entry("P1.2", _SHA2)]), computed) or (
            {}, {}, [])
    _t, _tf, forged = complete(dict(_phase_return([bare]), computedAnswers={
        "P1.1": ["redFirst"]}), computed) or ({}, {}, [])
    check("ma8 a reviewer word equal to the computed one files as typed and is "
          "not recorded as computed; one that differs without escalating, and "
          "a typed `computedAnswers`, are refused by name: %r"
          % ((same_filled, same_p, differ, forged),),
          block["status"] != "proved"
          and same_p == [] and same_filled == {}
          and "computedAnswers" not in same
          and same.get("tasks", [{}])[0].get("redFirstBasis")
          == _entry()["redFirstBasis"]
          and any("'proved'" in p and "P1.1" in p for p in differ)
          and any("computedAnswers" in p for p in forged))

    up = _entry(redFirst="not-proved", redFirstBasis="no red was seen",
                inheritedTests="flagged",
                inheritedTestsBasis="test_b passes with the branch deleted")
    esc, esc_filled, esc_p = complete(_phase_return([up, _entry(
        "P1.2", _SHA2)]), computed) or ({}, {}, ["not completed"])
    kept = (esc.get("tasks") or [{}])[0] if isinstance(esc, dict) else {}
    over = (esc.get("computedOverridden") or {}).get("P1.1", {}) \
        if isinstance(esc, dict) else {}
    check("ma10 a typed answer only a human settles - `not-proved` over a "
          "computed red-first, `flagged` over a computed `not-asked` - is an "
          "escalation: it files with its own word and basis, nothing filled "
          "over it, the computed word recorded as overridden, and the return "
          "has no problem: %r" % ((kept, esc_filled, over, esc_p),),
          esc_p == [] and esc_filled == {}
          and kept.get("redFirst") == "not-proved"
          and kept.get("redFirstBasis") == "no red was seen"
          and kept.get("inheritedTests") == "flagged"
          and kept.get("inheritedTestsBasis")
          == "test_b passes with the branch deleted"
          and over.get("redFirst", {}).get("computed") == block["status"]
          and over.get("inheritedTests", {}).get("computed") == "not-asked"
          and "computedAnswers" in esc
          and M.phase_return_problems(esc, two, "phase", {}) == [])
    no_basis = dict(up)
    no_basis.pop("inheritedTestsBasis")
    _n, _nf, unsaid = complete(_phase_return([no_basis, _entry(
        "P1.2", _SHA2)]), computed) or ({}, {}, [])
    lower = _entry(inheritedTests="none-found",
                   inheritedTestsBasis="read every test")
    _l, _lf, lowered = complete(_phase_return([lower, _entry(
        "P1.2", _SHA2)]), computed) or ({}, {}, [])
    _o, _of, forged_over = complete(dict(_phase_return([bare]),
                                         computedOverridden={"P1.1": {}}),
                                    computed) or ({}, {}, [])
    check("ma11 REFUSAL TWINS of ma10: an escalation typed without its basis, a "
          "typed `none-found` over a computed `not-asked`, and a typed "
          "`computedOverridden` are each refused by name: %r"
          % ((unsaid, lowered, forged_over),),
          any("P1.1" in p and "inheritedTestsBasis" in p for p in unsaid)
          and any("P1.1" in p and "none-found" in p for p in lowered)
          and any("computedOverridden" in p for p in forged_over))


# A return as a committed one is filed before a start carried anything finer
# than its second: the key is `startedAt` with the punctuation stripped, and the
# body is the executor's shape plus the stamp the submit takes.
_COMMITTED_AT = "2026-10-13T11:23:43Z"
_COMMITTED_KEY = "20261013T112343Z"


def _same_second_cases(check):
    root = _harness.fixture_root("filed-returns-same-second-")
    try:
        first = M.next_start_at(None, _COMMITTED_AT)
        second = M.next_start_at(first, _COMMITTED_AT)
        paths = [M.return_path(root, {"id": "P1.9", "startedAt": at}, "executor")
                 for at in (first, second)]
        committed = os.path.join(root, M.RETURNS_DIRNAME, "P1.9",
                                 "%s.executor.json" % (_COMMITTED_KEY,))
        os.makedirs(os.path.dirname(committed))
        with open(committed, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(_executor(), indent=2) + "\n")
        found = M.read_filed_return(paths[0])
        check("ss1 two starts of one task in the same second get distinct return "
              "paths, and a return filed under the old one-second key is still "
              "found for the start it answers: %r" % ((first, second, paths),),
              first == _COMMITTED_AT and paths[0] != paths[1]
              and os.path.normcase(paths[0]) == os.path.normcase(committed)
              and found[1] == _executor() and found[2] is None
              and M.read_filed_return(paths[1]) == (None, None, None))
        # The twin, for the guard that always fires: a start in a later second
        # keeps the wall clock, and only a clock at or behind the last start is
        # moved - to the first second after it, so the order of starts holds.
        later = M.next_start_at(_COMMITTED_AT, "2026-10-13T11:23:50Z")
        behind = M.next_start_at(_COMMITTED_AT, "2026-10-13T11:23:40Z")
        check("ss2 a start in a later second keeps its own clock reading, and one "
              "whose clock reads at or before the last start is the second after "
              "it: %r" % ((later, behind, second),),
              later == "2026-10-13T11:23:50Z"
              and behind == "2026-10-13T11:23:44Z" == second)
    finally:
        _harness.remove_tree(root)


def _case_title_cases(check):
    clause = "a filed title carries its detail after a parenthesis"
    task = {"tests": {"add": ["the-suite: " + clause]}}
    declared = task["tests"]["add"][0]
    detail = M.tests_add_gaps(task, [clause + " (sr1 counted 3 of 3)"])
    bare = M.tests_add_gaps(task, [clause])
    # The deny twin: a title that only STARTS with the clause, or paraphrases it,
    # is no counterpart - it is what makes the rule unconditional-proof.
    run_on = M.tests_add_gaps(task, [clause + "s and more"])
    spaced = M.tests_add_gaps(task, [clause + " extra words"])
    paraphrase = M.tests_add_gaps(task, ["detail follows a bracket in a filed title"])
    check("a filed case title that is the tests.add clause followed by its detail "
          "after an opening parenthesis counts as that clause's counterpart, and a "
          "title that only paraphrases it does not (%r)"
          % ((detail, bare, run_on, spaced, paraphrase),),
          detail == [] and bare == [] and run_on == [declared]
          and spaced == [declared] and paraphrase == [declared])


def _case_id_title_cases(check):
    import _loader                                 # noqa: E402  (load_script)
    clause = ("a filed title of one case-id token, then the clause verbatim, "
              "then its detail, names that clause; a paraphrase or an id glued "
              "to the clause does not")
    names = M.title_names_clause
    task = {"tests": {"add": ["the-suite: " + clause]}}
    accepted = [names("se3 " + clause, clause),
                names("ldoc1 " + clause + " (3 of 3)", clause),
                names("cas60 " + clause, clause)]
    refused = [names("se3 a paraphrase of the clause", clause),
               names("se3 ldoc1 " + clause, clause),
               names("se3" + clause, clause),
               names("se3  " + clause, clause),
               names("plain " + clause, clause),
               names("se3 " + clause + "s and more", clause),
               names("se3 " + clause + " extra", clause),
               names("se3 ", clause)]
    gaps = M.tests_add_gaps(task, ["se3 " + clause + " (detail)"])
    runner = _loader.load_script("_runner_output.py")
    shared = M._CASE_ID_TOKEN.pattern == runner._HOUSE_CASE_ID.pattern
    check(clause + " (id-prefixed titles accepted, paraphrase, two ids, glued "
          "id, run-on clause refused, id shape is the runner's own: %r)"
          % ((accepted, refused, gaps, shared),),
          accepted == [True] * 3 and refused == [False] * 8 and gaps == []
          and shared)


def _clause_marker_cases(check):
    import _loader                                 # noqa: E402  (load_script)
    lookup = _loader.load_script("audit-lookup.py")
    brief = "\n".join(lookup.CLAUSE_QUOTING_LINES)
    marker = M._CONTRADICTED_CLAUSE_MARKER
    # Written exactly as the brief directs: the issue STARTS with the marker.
    directed = {"severity": "low", "issue": marker + " (3): the diff narrows it"}
    # The deny twin: the same complaint in other words carries no marker, so the
    # floor leaves it low - it is what fails if the match is widened to guess.
    reworded = {"severity": "low", "issue": "the diff diverges from the clause"}
    floored = M.floor_contradicted_clause([directed, reworded])
    check("the reviewer brief's clause-quoting lines state the contradicted-clause "
          "marker built from the constant the floor matches, so a finding written "
          "as the brief directs is floored to med (%r)"
          % ((brief.count(marker), [f["severity"] for f in floored]),),
          brief.count(marker) == 1 and 'start the issue with "%s"' % marker in brief
          and [f["severity"] for f in floored] == ["med", "low"])


def _falsifiers_cases(check):
    """The return's optional `falsifiers`: a container that is not an object of
    objects is named, an absent one is no problem, and the gaps are a tdd
    task's planned tests that neither the plan nor the return covers."""
    mutation = {"file": "a.py", "find": "x", "replace": "y", "command": ["t"]}
    whole = M.return_problems("executor", _executor(falsifiers={"t.py: c": mutation}))
    flat = M.return_problems("executor", _executor(falsifiers=["t.py: c"]))
    inner = M.return_problems("executor", _executor(falsifiers={"t.py: c": "x"}))
    check("fz1 a `falsifiers` object of objects files, a list or a non-object "
          "value is named by the field, and an absent one is no problem: %r"
          % ((whole, flat, inner),),
          whole == [] and len(flat) == 1 and "`falsifiers`" in flat[0]
          and len(inner) == 1 and "t.py: c" in inner[0]
          and M.return_problems("executor", _executor()) == [])
    tdd = {"tests": {"mode": "tdd", "add": ["a: one", "b: two", "c: three"],
                     "falsifiers": {"a: one": mutation}}}
    reg = {"tests": {"mode": "regression", "add": ["a: one"]}}
    check("fz2 a tdd task's gaps are the planned tests neither the plan nor the "
          "return covers, in plan order; a regression task has none: %r"
          % ((M.falsifier_gaps(tdd, {"b: two": mutation}),
              M.falsifier_gaps(reg, {})),),
          M.falsifier_gaps(tdd, {"b: two": mutation}) == ["c: three"]
          and M.falsifier_gaps(reg, {}) == []
          and M.return_falsifiers({"falsifiers": {"b": mutation, "c": 1}})
          == {"b": mutation})


def _selftest():
    def body(check):
        _harness.stage(check, "fz-block", _falsifiers_cases)
        _harness.stage(check, "cm-block", _clause_marker_cases)
        _harness.stage(check, "ct-block", _case_title_cases)
        _harness.stage(check, "ci-block", _case_id_title_cases)
        _harness.stage(check, "fr-block", _cases)
        _harness.stage(check, "ss-block", _same_second_cases)
        _harness.stage(check, "um-block", _um_cases)
        _harness.stage(check, "ma-block", _mechanical_cases)
        _harness.stage(check, "pk-block", _held_cases)
        _harness.stage(check, "hn-block", _human_cases)
        _harness.stage(check, "dm-block", _drive_mark_cases)
        _harness.stage(check, "rd-block", _read_set_cases)
        _harness.stage(check, "rj-block", _journaled_cases)
        _harness.stage(check, "pr-block", _plain_read_cases)
        _harness.stage(check, "rc-block", _crlf_cases)
        _harness.stage(check, "ds-block", _digest_site_cases)
    return _harness.run(body)


def _plain_read_tree(root, files):
    """A scripts directory holding the home module and `files`
    (`{scripts-relative path: source}`), for the lint to walk."""
    for rel, text in dict({M.PLAIN_READ_HOME: "def read_filed_return(p):\n"
                                               "    return p\n"},
                          **files).items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return root


def _plain_read_cases(check):
    """The checked read is the one a closer may call, held as an invariant
    over the source rather than one call site at a time: the plain read is
    reachable only from its own module and from the reads the exemption
    table names, each with its reason."""
    root = _harness.fixture_root("filed-returns-plain-")
    try:
        plain = _plain_read_tree(os.path.join(root, "plain"), {
            "governance/closer-x.py":
                "import _filed_returns as _fr\n\n"
                "def close_it(path):\n"
                "    return _fr.read_filed_return(path)\n",
            "manifest/closer-y.py":
                "from _filed_returns import read_filed_return as r\n\n"
                "def other(path):\n"
                "    return r(path)\n"})
        found = M.plain_read_violations(plain, exempt={})
        real = M.plain_read_violations()
        named = "\n".join("%s: %s" % pair for pair in found)
        check("pr1 every module that closes a task reads returns only through "
              "read_filed_return_checked (a closer calling the plain read is "
              "reported by name): %r / the tree: %r" % (found, real),
              real == [] and len(found) == 2
              and "scripts/governance/closer-x.py" in named
              and "close_it" in named
              and "scripts/manifest/closer-y.py" in named
              and "read_filed_return" in named)

        checked = _plain_read_tree(os.path.join(root, "checked"), {
            "governance/closer-x.py":
                "import _filed_returns as _fr\n\n"
                "def close_it(path, rows, here):\n"
                "    return _fr.read_filed_return_checked(path, rows, here)\n"})
        quiet = M.plain_read_violations(checked, exempt={})
        check("pr2 THE ALLOW TWIN, for the over-fire mutation: a closer "
              "calling only the checked read is reported by nothing, and the "
              "home module's own plain read is its own: %r" % (quiet,),
              quiet == [])

        held = _plain_read_tree(os.path.join(root, "held"), {
            "governance/closer-x.py":
                "import _filed_returns as _fr\n\n"
                "def show(path):\n"
                "    return _fr.read_filed_return(path)\n"})
        exempt = {"governance/closer-x.py::show": "a display read",
                  "governance/closer-x.py::gone": "a read since removed"}
        stale = M.plain_read_violations(held, exempt=exempt)
        check("pr3 an exempted read is quiet, and an exemption naming a "
              "function that no longer calls the plain read is reported as "
              "stale - an exemption outliving its read would excuse the next "
              "one under that name: %r" % (stale,),
              len(stale) == 1 and "gone" in stale[0][1]
              and "show" not in stale[0][1])

        blind = os.path.join(root, "blind")
        os.makedirs(blind)
        check("pr4 a tree without the home module is BLIND, never clean: %r"
              % (M.plain_read_violations(blind, exempt={}),),
              len(M.plain_read_violations(blind, exempt={})) == 1)
        reasons = [why for why in M.PLAIN_READ_EXEMPT.values()
                   if not (isinstance(why, str) and why.strip())]
        check("pr5 every exemption of the real table carries a reason: %r"
              % (sorted(M.PLAIN_READ_EXEMPT),),
              M.PLAIN_READ_EXEMPT and reasons == [])
    finally:
        _harness.remove_tree(root)


def _journaled_cases(check):
    """A filed return's "once" used to rest on the file alone - delete
    it and a second filing went unrecorded. This module's own layer may not
    import `_journal_io` (`_deps.LAYERS`), so `drive-phase.py submit` is the
    caller that reads and appends the real journal; these drive the same
    scenario directly through the row shape this module owns."""
    root = _harness.fixture_root("filed-returns-journal-")
    task = {"id": "P1.9", "startedAt": _START}
    path = M.return_path(root, task, "executor")
    first = json.dumps(_executor()) + "\n"
    M.file_once(path, first)
    row = M.filed_return_row(path, root, task["id"], "executor", "proved")
    row = dict(row, ts="2026-01-01T00:00:01Z", stateHash=M.return_digest(path))
    check("rj1 the row a filing builds names the task, the role and the "
          "red-first verdict, and its target is the return's own path: %r"
          % (row,),
          row["action"] == M.RETURN_FILED_ACTION
          and row["target"] == "returns/P1.9/20260101T000000Z.executor.json"
          and row["details"]["taskId"] == "P1.9"
          and "executor" in row["summary"] and "proved" in row["summary"])

    os.remove(path)
    refused = M.refiling_refusal([row], path, root)
    check("rj2 filing, deleting the file and filing again for the same start "
          "is refused - the FILE is gone, and the refusal is still made, "
          "naming the journal row of the first filing: %r" % (refused,),
          not os.path.exists(path) and refused is not None
          and row["stateHash"] in refused)
    allowed = M.refiling_refusal([], path, root)
    check("rj2a THE ALLOW TWIN: with no such row in the journal, this check "
          "refuses nothing", allowed is None)

    M.file_once(path, first)
    intact = M.filed_digest_problem(path, row)
    check("rj3 a return whose bytes still match the row's recorded digest "
          "reads clean at the close: %r" % (intact,), intact is None)
    # `newline=""`, as `file_once` writes: a text-mode write on Windows turns
    # every "\n" into CRLF, which is a change of bytes the row is right to refuse.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(_executor(claims="claims:\n1 a tampered edit")) + "\n")
    changed = M.filed_digest_problem(path, row)
    check("rj4 a return whose bytes changed after filing is refused at the "
          "close, naming both the recorded and the present digest: %r"
          % (changed,),
          changed is not None and row["stateHash"] in changed
          and M.return_digest(path) in changed
          and row["stateHash"] != M.return_digest(path))

    text, body, problem, unchecked = M.read_filed_return_checked(
        path, [row], root)
    check("rj5 `read_filed_return_checked` is the close's reading: it "
          "refuses the same edited return through the row, rather than "
          "reading its current bytes silently: %r"
          % ((text, body, problem, unchecked),),
          text is None and body is None and problem is not None
          and row["stateHash"] in problem and unchecked is None
          and M.filed_mismatch(path, [row], root) == problem)
    claims, why = M.claims_from_return(root, task, [row], root)
    check("rj5c `claims_from_return` reads through the checked read, so the "
          "same edited return is a problem for the claims too, naming both "
          "digests: %r" % ((claims, why),),
          claims is None and why is not None and row["stateHash"] in why
          and M.return_digest(path) in why)

    # A RETURN WITH NO FILING ROW is read as it stands, and says so: never
    # refused, and never read as one the row vouched for.
    old = M.return_path(root, {"id": "P1.8", "startedAt": _START}, "executor")
    old_text = json.dumps(_executor(claims="claims:\n1 old")) + "\n"
    M.file_once(old, old_text)
    text, body, problem, unchecked = M.read_filed_return_checked(
        old, [row], root)
    unread = M.read_filed_return_checked(old, None, root)
    check("rj7 a return no `task.return.filed` row names reads as it stands "
          "and the reading says it was not checked against a row - the "
          "journal read and holding no row, or not read at all: %r"
          % ((problem, unchecked, unread[3]),),
          text == old_text and problem is None
          and unchecked is not None and M.UNCHECKED_LEAD in unchecked
          and "returns/P1.8/" in unchecked
          and unread[0] == old_text and unread[3] is not None
          and M.UNCHECKED_LEAD in unread[3])
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(first)
    text, body, problem, unchecked = M.read_filed_return_checked(
        path, [row], root)
    no_hash = M.read_filed_return_checked(
        path, [dict(row, stateHash=None)], root)
    check("rj8 SECOND DIRECTION: a return whose bytes match its row reads "
          "with NO unchecked note - a note on every read would say nothing - "
          "while a row recording no digest vouches for nothing and is noted: "
          "%r" % ((problem, unchecked, no_hash[3]),),
          text == first and problem is None and unchecked is None
          and no_hash[0] == first and no_hash[3] is not None)
    nothing = M.read_filed_return_checked(
        M.return_path(root, {"id": "P1.7", "startedAt": _START}, "executor"),
        [row], root)
    check("rj9 nothing filed reads as four Nones - no return, so no note "
          "about checking one: %r" % (nothing,),
          nothing == (None, None, None, None))

    # A DELETED RETURN whose filing row is in the journal. rj9 holds the
    # no-row half, and `other` below is the over-fire direction: a row for
    # ANOTHER return must not turn an unfiled one into a problem.
    os.remove(path)
    gone = M.read_filed_return_checked(path, [row], root)
    bare = M.read_filed_return_checked(path, [dict(row, stateHash=None)], root)
    other = M.read_filed_return_checked(
        M.return_path(root, {"id": "P1.7", "startedAt": _START}, "executor"),
        [row], root)
    check("a filed return whose file was deleted reads as a problem naming "
          "the filing row's digest and the missing file, never as unfiled "
          "(rj10 %r; a row recording no digest still refuses: %r; a row for "
          "another return refuses nothing: %r)" % (gone, bare[2], other),
          gone[0] is None and gone[1] is None and gone[3] is None
          and gone[2] is not None and row["stateHash"] in gone[2]
          and path in gone[2] and "missing" in gone[2]
          and M.filed_mismatch(path, [row], root) == gone[2]
          and bare[2] is not None and path in bare[2] and "missing" in bare[2]
          and other == (None, None, None, None))
    claims, why = M.claims_from_return(root, task, [row], root)
    check("rj10c `claims_from_return` reads through the checked read, so a "
          "deleted return is a problem for the claims too, not an absence: %r"
          % ((claims, why),),
          claims is None and why is not None and row["stateHash"] in why)

    pin_path = os.path.join(root, "pin.txt")
    with open(pin_path, "w", encoding="utf-8") as fh:
        fh.write("pin\n")
    check("rj6`return_digest` spells a file's sha256 exactly as "
          "`_journal_io.file_hash` would - duplicated because that module is "
          "this one's own layer-mate, so the two are pinned equal here "
          "rather than left to drift apart in silence: %r"
          % (M.return_digest(pin_path),),
          M.return_digest(pin_path) == _journal_io.file_hash(pin_path))


def _crlf_cases(check):
    """A return whose bytes carry CRLF, as a text-mode write on Windows leaves
    them, written by hand here so a POSIX run sees the bytes that platform
    does. The row is appended through `_journal_io` for real, so its digest is
    the one a filing records, not one this case computed."""
    root = _harness.fixture_root("filed-returns-crlf-")
    try:
        task = {"id": "P1.9", "startedAt": _START}
        path = M.return_path(root, task, "executor")
        crlf = json.dumps(_executor(), indent=2).replace("\n", "\r\n") + "\r\n"
        M.file_once(path, crlf)
        with open(path, "rb") as fh:
            on_disk = fh.read()
        row = M.filed_return_row(path, root, task["id"], "executor", "proved")
        written, why = _journal_io.append_from_cli_why(root, row)
        rows = _journal_io.read_all(root)
        filed = [r for r in rows if r.get("action") == M.RETURN_FILED_ACTION]
        recorded = filed[0].get("stateHash") if len(filed) == 1 else None
        # The digest a reading over the TRANSLATED text would take: what the
        # fixture value must tell apart from the bytes, or the case proves
        # nothing about line endings.
        lf_bytes = crlf.replace("\r\n", "\n").encode("utf-8")
        untranslated = "sha256:" + hashlib.sha256(lf_bytes).hexdigest()
        text, _body, problem, unchecked = M.read_filed_return_checked(
            path, rows, root)
        with open(path, "wb") as fh:
            fh.write(lf_bytes)
        gone = M.read_filed_return_checked(path, rows, root)
        check("rc1 a return written with CRLF line endings and its filing row "
              "agree on one digest, and a return whose bytes changed after "
              "filing is still refused (row %r, untranslated %r, read %r, "
              "after the CRLF became LF %r, append %r)"
              % (recorded, untranslated, (problem, unchecked), gone[2],
                 (written, why)),
              bool(written) and on_disk == crlf.encode("utf-8")
              and on_disk.count(b"\r\n") > 1
              and recorded is not None and recorded != untranslated
              and text == crlf and problem is None and unchecked is None
              and gone[0] is None and gone[2] is not None
              and recorded in gone[2] and untranslated in gone[2])
    finally:
        _harness.remove_tree(root)


def _digest_function(source, name):
    """`ast.dump` of the `try` body of `name` in `source`, or None."""
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.FunctionDef) and node.name == name
                and node.body and isinstance(node.body[-1], ast.Try)):
            return ast.dump(ast.Module(body=node.body[-1].body,
                                       type_ignores=[]))
    return None


def _state_hash_sources(source):
    """The names called on the right of every `<x>["stateHash"] = <call>`."""
    names = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        tgt = node.targets[0]
        key = getattr(tgt, "slice", None)
        if key.__class__.__name__ == "Index":       # the 3.8 wrapper
            key = key.value
        if not (isinstance(tgt, ast.Subscript)
                and isinstance(key, ast.Constant) and key.value == "stateHash"):
            continue
        call = node.value
        names.append(getattr(getattr(call, "func", None), "id", None)
                     if isinstance(call, ast.Call) else repr(
                         getattr(call, "value", call)))
    return names


def _calls(source, function):
    """Every bare or attribute name `function` in `source` calls."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return sorted(set(
                getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                for c in ast.walk(node) if isinstance(c, ast.Call)))
    return None


def _digest_site_cases(check):
    """The filing row's digest is `_journal_io.file_hash`'s, taken at the
    append; the checked read's is `return_digest`'s. The two modules are
    layer-mates and may not import each other, so the one function is held
    as one body in two places, and any other site that hashes a file a
    reading opened is reported by name."""
    def source(rel):
        with open(os.path.join(_output.SCRIPTS_DIR, rel), "r",
                  encoding="utf-8") as fh:
            return fh.read()
    filed_src = source(os.path.join("manifest", "_filed_returns.py"))
    journal_src = source(os.path.join("governance", "_journal_io.py"))
    drive_src = source(os.path.join("governance", "drive-phase.py"))
    # With no reader there is no way to report a second site, so its absence
    # fails these cases rather than raising past them.
    read_sites = getattr(M, "file_digest_sites", lambda _src: None)
    sites = (read_sites(filed_src), read_sites(journal_src),
             read_sites(drive_src))
    bodies = (_digest_function(filed_src, "return_digest"),
              _digest_function(journal_src, "file_hash"))
    hashes = _state_hash_sources(journal_src)
    compared = _calls(filed_src, "filed_digest_problem")
    check("ds1 the digest a filing row records and the digest the checked "
          "read compares are computed by the same function over the same "
          "bytes (sites %r, row's stateHash from %r, the comparison calls %r, "
          "one body: %r)" % (sites, hashes, compared,
                             bodies[0] is not None and bodies[0] == bodies[1]),
          sites[0] == ["return_digest"] and "file_hash" in (sites[1] or [])
          and sites[2] == []
          and bodies[0] is not None and bodies[0] == bodies[1]
          and "file_hash" in hashes
          and set(hashes) <= set(["file_hash", "None"])
          and compared is not None and "return_digest" in compared
          and "sha256" not in compared)
    second = (filed_src + "\n\ndef _text_digest(path):\n"
              "    with open(path, encoding=\"utf-8\") as fh:\n"
              "        return hashlib.sha256(fh.read().encode()).hexdigest()\n")
    check("ds2 a second hashing site - one over the text a text-mode read "
          "hands back, which is the shape that sees translated bytes - is "
          "reported by name: %r" % (read_sites(second),),
          read_sites(second) == ["_text_digest", "return_digest"])
    handed = ("import hashlib\n\ndef sig(text):\n"
              "    return hashlib.sha256(text.encode()).hexdigest()\n\n"
              "def peek(path):\n    with open(path, \"rb\") as fh:\n"
              "        return fh.read()\n")
    check("ds2a THE ALLOW TWIN: hashing text a caller handed over, and opening "
          "a file without hashing it, are neither a site: %r"
          % (read_sites(handed),),
          read_sites(handed) == [])


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
