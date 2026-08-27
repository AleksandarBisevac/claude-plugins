#!/usr/bin/env python3
"""
The cases for `_status_facts.py` — the manifest's machine-readable answer, and its boundary.

`audit-status.py`'s cases live in `test_audit_status.py` and run over these
same functions through that command's aliases; they are not repeated here. What
this file asserts is what that suite structurally cannot: that there is ONE
implementation of each fact, that `audit-status.py` re-exports rather than
copies, and — the property the whole split was for — that nothing in here reads
the world. A "fact" that opens a file cannot be shared by a panel, a doctor and a
report generator without dragging their failure modes together.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import ast
import json
import os
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
import _output                                     # noqa: E402  (PLUGIN_ROOT, for the schema read)
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _status_facts as M                          # noqa: E402
# The comparator itself, and the OTHER surface that reads it. Both are here so
# the `porder` cases can measure the stamped rank against something derived a
# different way: `_priority.sort_key` is the rule, `_report_html.phase_ranks` is
# the report's own call, and a rank compared with itself could not fail.
import _priority as _prio                          # noqa: E402
import _report_html as _rhtml                      # noqa: E402
# The boundary blocks the `eb` cases classify against are built by the module
# that BUILDS them in production, never hand-written here. A fixture typed out
# beside the reader encodes the reader's idea of the shape, so a `sources` key
# that moved would leave every case green while the gate read `None` off a dict
# that no longer carried it.
import _evidence_io as _ebio                       # noqa: E402

_CMD = _loader.load_script("audit-status.py", modname="audit_status_boundary")


def _fixture():
    return {
        "meta": {"version": 2, "areas": {"web": {"root": "src/web",
                                                 "owner": "a@b.example"}}},
        "phases": [
            {"id": "P1", "title": "One", "status": "done", "area": "web",
             "tasks": [
                 {"id": "P1.1", "title": "t", "status": "done"},
                 {"id": "P1.2", "title": "t", "status": "cancelled"},
             ]},
            {"id": "P2", "title": "Two", "status": "pending",
             "tasks": [
                 {"id": "P2.1", "title": "t", "status": "pending",
                  "dependsOn": ["P1.1"]},
                 {"id": "P2.2", "title": "t", "status": "pending",
                  "blockedBy": ["P2.1"]},
                 {"id": "P2.3", "title": "t", "status": "blocked"},
             ]},
        ],
        "bugs": [
            {"id": "BUG-1", "title": "b", "severity": "sev1", "status": "open"},
            {"id": "BUG-2", "title": "b", "severity": "low", "status": "fixed"},
        ],
    }


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the boundary ---------------------------------------------------------
    _shared = ("CONDITIONS", "DEFAULT_GATE", "BUDGET_WARN_PCT", "CLOSED_BUG",
               "READY_LIST_MAX", "HIGH_SEVERITIES", "_is_high_severity",
               "parse_gitmodules", "_strip_git_root", "submodule_conflicts",
               "_status_index", "ready_tasks", "_by_status", "_by_status_values",
               "PARKED_PROPOSAL_STATUS", "is_parked_proposal",
               "areas_of", "effective_bug_status", "TERMINAL", "rollup",
               "unmet_refs", "evaluate_gate", "budget_breaches",
               "NO_SIGN_OFF_EVIDENCE", "KNOWN_EVIDENCE", "evidence_status",
               "evidence_rows", "test_evidence_summary", "evidence_subjects",
               # The boundary's half. `evidence_gap` and `GAP_CLASSES` are NOT
               # here: the command does not alias them, deliberately, and a
               # shared-name case that named them would be asserting an alias
               # nothing calls rather than that there is one implementation.
               "unevidenced", "GAP_BEFORE", "GAP_SINCE", "GAP_UNDATED")
    _forked = sorted(n for n in _shared
                     if getattr(_CMD, n, None) is not getattr(M, n))
    check("b1 audit-status.py re-exports all %d shared names as THIS module's "
          "own objects - not one is a second implementation: %r"
          % (len(_shared), _forked), _forked == [])
    _missing = sorted(n for n in _shared if not hasattr(_CMD, n))
    check("b2 ...and every one is actually present on audit-status.py, so b1 "
          "cannot pass over a list that quietly got shorter: %r" % (_missing,),
          _missing == [])

    # THE PROPERTY THE SPLIT WAS FOR, read out of the AST rather than asserted in
    # prose. Three modules share these facts precisely because computing one
    # cannot fail the way a read can. `usage_summary` and `discovery_block` DID
    # read the world, and they are the two that stayed with the command.
    with open(M.__file__, "r", encoding="utf-8") as fh:
        _tree = ast.parse(fh.read(), filename=M.__file__)
    _io_names = {"open", "input"}
    _io_attrs = {"run", "Popen", "check_output", "system", "listdir", "walk",
                 "getmtime", "makedirs", "unlink", "remove", "rename"}
    _io_hits = []
    for _n in ast.walk(_tree):
        if not isinstance(_n, ast.Call):
            continue
        if isinstance(_n.func, ast.Name) and _n.func.id in _io_names:
            _io_hits.append(_n.func.id)
        elif isinstance(_n.func, ast.Attribute) and _n.func.attr in _io_attrs:
            _io_hits.append(_n.func.attr)
    check("b3 nothing here opens a file or runs a process - the facts are a pure "
          "transform, which is what lets a panel, a doctor and a report share "
          "them without sharing a failure mode: %r" % (sorted(set(_io_hits)),),
          _io_hits == [])
    # The other direction: b3 would also pass if the AST walk were pointed at an
    # empty tree or the wrong file. This says the walk really read the module and
    # really can see a call.
    _calls = sum(1 for _n in ast.walk(_tree) if isinstance(_n, ast.Call))
    check("b4 ...and the scan that says so actually read this module and can see "
          "calls at all (%d found), so b3 is not vacuously green over nothing"
          % (_calls,), _calls > 50)
    check("b5 `main` and the human rendering stayed with the command",
          callable(getattr(_CMD, "main", None)) and not hasattr(M, "main")
          and hasattr(_CMD, "render_status") and not hasattr(M, "render_status"))
    check("b6 ...and so did the two functions that DO read the world, which is "
          "the seam stated as a case rather than as a comment",
          hasattr(_CMD, "usage_summary") and not hasattr(M, "usage_summary")
          and hasattr(_CMD, "discovery_block")
          and not hasattr(M, "discovery_block"))

    # --- the facts ------------------------------------------------------------
    m = _fixture()
    s = M.rollup(m, [], [])
    check("r1 rollup counts tasks by status over the whole plan",
          s["tasks"]["total"] == 5
          and s["tasks"]["byStatus"].get("done") == 1
          and s["tasks"]["byStatus"].get("blocked") == 1, s["tasks"])
    check("r2 a cancelled task is counted apart from done - a bar reading 2/2 "
          "for one landed task and one dropped one is a lie in the direction "
          "that matters",
          s["phases"][0]["done"] == 1 and s["phases"][0]["cancelled"] == 1
          and s["phases"][0]["total"] == 2)
    check("r3 `sev1` counts as high-severity-or-worse: severity is free text, "
          "and a merge gate that only knew the literal word 'high' would wave "
          "through critical, blocker and p0",
          s["bugs"]["openHighSeverity"] == 1 and s["bugs"]["open"] == 1)
    check("r4 findings/warnings are taken from the caller, not recomputed - "
          "which is what keeps this a pure transform",
          M.rollup(m, ["x"], ["y"])["valid"] is False
          and M.rollup(m, ["x"], ["y"])["findings"] == 1)
    check("r5 a non-dict manifest is an empty rollup, never an AttributeError - "
          "the read-only surfaces must RENDER a broken manifest, not refuse it",
          M.rollup("nope", [], [])["tasks"]["total"] == 0)
    check("r6 the area registry's owner is carried through when declared",
          s["areas"]["web"]["owner"] == "a@b.example"
          and s["areasRegistered"] is True)

    check("t1 readiness: pending, own refs satisfied, phase not blocked",
          M.ready_tasks(m) == ["P2.1"], M.ready_tasks(m))
    check("t2 unmet_refs says WHY, not just that something is not ready",
          M.unmet_refs(m).get("P2.2") == ["P2.1"], M.unmet_refs(m))

    # --- the gate -------------------------------------------------------------
    check("g1 the default gate trips on a blocked task and an open high bug",
          sorted(M.evaluate_gate(s, M.DEFAULT_GATE))
          == ["blocked-tasks", "open-high-bugs"], M.evaluate_gate(s, M.DEFAULT_GATE))
    check("g2 an empty condition list fails nothing - and it is a real answer, "
          "not an 'all clear': a gate configured to check nothing must not read "
          "as a gate that passed",
          M.evaluate_gate(s, ()) == [])
    check("g3 neither budget condition is in the default gate: spend is a signal, "
          "not a defect, and a gate that failed merges over it would be switched "
          "off wholesale",
          "over-budget" not in M.DEFAULT_GATE and "budget-80" not in M.DEFAULT_GATE
          and "over-budget" in M.CONDITIONS and "budget-80" in M.CONDITIONS)
    check("g4 with no usage block there are no budget breaches at any threshold",
          M.budget_breaches(s, 0.0) == [])

    # --- the post-hoc condition ------------------------------------------------
    # THREE STATES, and the middle one is the reason this is not a boolean. The
    # block is INJECTED by `audit-status.py` (the git and ledger reads live at a
    # layer this module may not reach), so "there were no breaches" and "nobody
    # looked" arrive here as different shapes - and only one of them is a pass.
    check("g5 a summary with NO invariants block trips the condition: a gate that "
          "reported a clean bill of health over checks that never ran would be "
          "the exact failure the post-hoc checker was written to end",
          M.evaluate_gate({}, ("invariant-breach",)) == ["invariant-breach"]
          and M.invariant_breaches({}) is not None)
    _clean = {"invariants": {"breaches": [], "gaps": ["a reflog is gone"]}}
    check("g6 ...and a block that WAS computed and found nothing passes - which "
          "is the direction that fails if g5 is implemented as 'always trip'",
          M.evaluate_gate(_clean, ("invariant-breach",)) == []
          and M.invariant_breaches(_clean) is None)
    _bad = {"invariants": {"breaches": ["P1 commit-scope: staged src/x.py"],
                           "gaps": []}}
    check("g7 ...and a block with a breach trips, handing the caller the lines "
          "themselves rather than a count it would have to go and re-derive",
          M.evaluate_gate(_bad, ("invariant-breach",)) == ["invariant-breach"]
          and M.invariant_breaches(_bad)
          == ["P1 commit-scope: staged src/x.py"])
    check("g8 a block whose `breaches` is not a LIST is read as 'nothing was "
          "verified' too - `{\"error\": ...}` is what audit-status returns when "
          "the checks raise, and an empty answer there would be a clean bill of "
          "health produced by a crash",
          M.invariant_breaches({"invariants": {"error": "boom"}}) is not None
          and M.evaluate_gate({"invariants": {"error": "boom"}},
                              ("invariant-breach",)) == ["invariant-breach"])
    check("g9 it is NOT in the default gate: it costs several git calls per "
          "started phase, and a default that slow is a default somebody replaces",
          "invariant-breach" in M.CONDITIONS
          and "invariant-breach" not in M.DEFAULT_GATE)

    # --- test evidence: two conditions, and what absence is allowed to mean ----
    # EVERY CASE HERE IS ANCHORED ON A SUBJECT NAME, never on "the list is not
    # empty" and never on "the gate returned []". A condition that matched nothing
    # returns an empty list, which reads exactly like a clean plan, so each fixture
    # carries a subject that MUST be named beside one that must not be.
    def _ev_plan(tasks, phase_ev=None):
        """A one-phase plan whose subjects carry the verdicts given.

        `tasks` is `(id, task status, recorded verdict or None)`; a None verdict
        writes NO block at all, which is the state this whole feature turns on -
        "no run was recorded", which is not a failure.
        """
        rows = []
        for tid, tstatus, verdict in tasks:
            t = {"id": tid, "title": "t", "status": tstatus}
            if verdict is not None:
                t["testEvidence"] = {"runId": "R-" + tid, "status": verdict,
                                     "at": "2026-01-01T00:00:00Z"}
            rows.append(t)
        ph = {"id": "PE", "title": "e", "status": "done", "tasks": rows}
        if phase_ev is not None:
            ph["testEvidence"] = {"runId": "R-PE", "status": phase_ev,
                                  "at": "2026-01-01T00:00:00Z"}
        return {"meta": {"version": 2}, "phases": [ph]}

    # One call site, driven over the vocabulary itself - which is why te2 below
    # has to exist: a loop derived from the set cannot notice the set shrinking.
    for _word in sorted(M.NO_SIGN_OFF_EVIDENCE):
        _ev_s = M.rollup(_ev_plan([("PE.1", "done", "passed"),
                                   ("PE.2", "done", _word)]), [], [])
        check("te1 `%s` cannot sign work off, so failing-tests trips and names "
              "PE.2 - while PE.1, which passed under the same walk, is not in "
              "the list" % (_word,),
              M.evaluate_gate(_ev_s, ("failing-tests",)) == ["failing-tests"]
              and [r["id"] for r in _ev_s["testEvidence"]["failing"]] == ["PE.2"],
              repr(_ev_s["testEvidence"]["failing"]))
    check("te2 the membership is PINNED here, so changing it is a deliberate "
          "edit rather than a side effect - and a loop derived from the set, "
          "like te1's, cannot notice a member being dropped",
          sorted(M.NO_SIGN_OFF_EVIDENCE)
          == ["cancelled", "could-not-run", "failed", "no-checks", "timed-out"]
          and M.PASSED_EVIDENCE not in M.NO_SIGN_OFF_EVIDENCE
          and M.NO_GATE_EVIDENCE not in M.NO_SIGN_OFF_EVIDENCE,
          repr(sorted(M.NO_SIGN_OFF_EVIDENCE)))
    with open(os.path.join(_output.PLUGIN_ROOT, "schema",
                           "audit-plan.schema.json"), "r",
              encoding="utf-8") as fh:
        _te_enum = (((json.load(fh).get("$defs") or {}).get("testEvidence") or {})
                    .get("properties") or {}).get("status", {}).get("enum")
    check("te3 ...and the vocabulary IS the schema's, read out of "
          "audit-plan.schema.json rather than re-typed: the enum gaining a "
          "member goes red here and somebody has to decide which side it falls "
          "on, which is the whole reason the classification is a positive set "
          "and not `everything except passed`",
          isinstance(_te_enum, list)
          and sorted(M.KNOWN_EVIDENCE) == sorted(_te_enum),
          repr((sorted(M.KNOWN_EVIDENCE), _te_enum)))
    _te_ok = M.rollup(_ev_plan([("PE.1", "done", "passed"),
                                ("PE.2", "done", "empty-gate")]), [], [])
    check("te4 SECOND DIRECTION: `passed` and `empty-gate` do NOT trip it - one "
          "is the verdict that signs off, the other says no gate was configured "
          "at all - and the walk demonstrably SAW both, which is what stops this "
          "reading as 'the condition matched nothing'",
          M.evaluate_gate(_te_ok, ("failing-tests",)) == []
          and _te_ok["testEvidence"]["byStatus"] == {"passed": 1, "empty-gate": 1}
          and _te_ok["testEvidence"]["recorded"] == 2,
          repr(_te_ok["testEvidence"]))
    _te_gap = M.rollup(_ev_plan([("PE.1", "done", None),
                                 ("PE.2", "pending", None)]), [], [])
    check("te5 ABSENT EVIDENCE IS NOT FAILURE: neither subject records a run and "
          "failing-tests trips on nothing - the reading every manifest written "
          "before the field existed depends on",
          M.evaluate_gate(_te_gap, ("failing-tests",)) == []
          and _te_gap["testEvidence"]["failing"] == []
          and _te_gap["testEvidence"]["recorded"] == 0,
          repr(_te_gap["testEvidence"]))
    check("te6 ...and the SAME fixture DOES trip no-test-evidence, naming every "
          "DONE subject - the phase and the done task, each with its scope - and "
          "not the pending one, which is what tells 'the condition is inert' "
          "apart from 'this plan is clean'",
          M.evaluate_gate(_te_gap, ("no-test-evidence",)) == ["no-test-evidence"]
          and [(r["scope"], r["id"])
               for r in _te_gap["testEvidence"]["missingOnDone"]]
          == [("phase", "PE"), ("task", "PE.1")],
          repr(_te_gap["testEvidence"]["missingOnDone"]))
    _te_covered = M.rollup(_ev_plan([("PE.1", "done", "passed"),
                                     ("PE.2", "pending", None)],
                                    phase_ev="passed"), [], [])
    check("te7 SECOND DIRECTION for no-test-evidence: a done task that DOES "
          "carry a pointer clears it, and the pending task with none never "
          "counted - a version reading 'any task with no evidence' passes te6 "
          "and fails here",
          M.evaluate_gate(_te_covered, ("no-test-evidence",)) == []
          and _te_covered["testEvidence"]["missingOnDone"] == []
          and _te_covered["testEvidence"]["recorded"] == 2,
          repr(_te_covered["testEvidence"]))
    _te_new = M.rollup(_ev_plan([("PE.1", "done", "failed"),
                                 ("PE.2", "done", "quarantined")]), [], [])
    check("te8 a status this build does not recognise is reported as itself and "
          "judged by nothing - NOT folded into `failed`, which is the reading "
          "the schema forbids by name. The known red one beside it is what "
          "proves the condition was live while the new word went unjudged",
          [r["id"] for r in _te_new["testEvidence"]["failing"]] == ["PE.1"]
          and [(r["id"], r["status"])
               for r in _te_new["testEvidence"]["unrecognised"]]
          == [("PE.2", "quarantined")],
          repr(_te_new["testEvidence"]))
    _te_phase = M.rollup(_ev_plan([("PE.1", "done", "passed")],
                                  phase_ev="timed-out"), [], [])
    check("te9 a PHASE's pointer is read too, and the row carries its SCOPE so "
          "a reader is never left guessing which kind of subject went red",
          M.evaluate_gate(_te_phase, ("failing-tests",)) == ["failing-tests"]
          and [(r["scope"], r["id"])
               for r in _te_phase["testEvidence"]["failing"]] == [("phase", "PE")],
          repr(_te_phase["testEvidence"]["failing"]))
    _te_junk = _ev_plan([("PE.1", "done", "failed")], phase_ev="passed")
    _te_junk["phases"][0]["tasks"][0]["testEvidence"] = {"runId": "R", "at": "x"}
    _te_junk["phases"][0]["tasks"].append(
        {"id": "PE.2", "title": "t", "status": "done",
         "testEvidence": "not an object"})
    _te_junk_s = M.rollup(_te_junk, [], [])
    check("te10 a half-written or non-object block reads as SILENCE and not as a "
          "verdict: both subjects land in missingOnDone and neither in failing. "
          "A block with no `status` caches nothing, and picking one for it would "
          "be this module answering a question the manifest did not",
          _te_junk_s["testEvidence"]["failing"] == []
          and [r["id"] for r in _te_junk_s["testEvidence"]["missingOnDone"]]
          == ["PE.1", "PE.2"], repr(_te_junk_s["testEvidence"]))
    _te_cancelled = M.rollup(_ev_plan([("PE.1", "cancelled", None),
                                       ("PE.2", "done", None)],
                                      phase_ev="passed"), [], [])
    check("te11 a CANCELLED task with no evidence is not a gap - nobody is going "
          "to run work that was dropped - so only the done one is named. The "
          "condition is about a claim of completion, not about every task alive",
          [r["id"] for r in _te_cancelled["testEvidence"]["missingOnDone"]]
          == ["PE.2"], repr(_te_cancelled["testEvidence"]["missingOnDone"]))
    check("te12 the DEFAULT gate is spelled out WHOLE here, so moving either "
          "condition into it is a deliberate edit that goes red first rather "
          "than a merge that quietly starts failing other people's builds",
          M.DEFAULT_GATE == ("invalid", "open-high-bugs", "blocked-tasks"),
          repr(M.DEFAULT_GATE))
    check("te13 ...and both ARE accepted by --fail-on, which is the direction "
          "that fails if te12 is satisfied by dropping them everywhere",
          "failing-tests" in M.CONDITIONS and "no-test-evidence" in M.CONDITIONS
          and "failing-tests" not in M.DEFAULT_GATE
          and "no-test-evidence" not in M.DEFAULT_GATE)
    _te_empty = M.rollup({"meta": {"version": 2}, "phases": []}, [], [])
    check("te14 the block is ALWAYS in the rollup and always whole, even over a "
          "plan with no phases - an empty `failing` list and a block nobody "
          "computed must not look alike to a consumer. The boundary classes are "
          "in the list SPELLED OUT, so adding or dropping one is a deliberate "
          "edit here rather than a shape that changes under a consumer",
          sorted(_te_empty["testEvidence"])
          == ["beforeBoundary", "byStatus", "failing", "missingOnDone",
              "recorded", "sinceBoundary", "undated", "unrecognised"]
          and _te_empty["testEvidence"]["recorded"] == 0,
          repr(_te_empty.get("testEvidence")))
    # THROUGH `attempt` FROM HERE DOWN: both cases are about a call NOT raising, and
    # a raise inside a `check()` argument escapes the whole body - so the very
    # failure they exist to catch would arrive as an unattributed traceback with
    # these two cases never printed at all.
    _te_ok_e, _te_e = _harness.attempt(M.evidence_subjects, {}, "failing")
    _te_ok_n, _te_n = _harness.attempt(M.evidence_subjects, None, "missingOnDone")
    check("te15 `evidence_subjects` over a summary carrying no block is [] and "
          "not a raise - and here that empty really IS 'nothing to report', "
          "because rollup computes the block unconditionally. Contrast g5, where "
          "an absent INJECTED block means 'nobody looked' and must trip: %r"
          % ((_te_e, _te_n),),
          _te_ok_e and _te_e == [] and _te_ok_n and _te_n == []
          and M.evidence_subjects(_te_new, "failing")
          == _te_new["testEvidence"]["failing"])
    _te_ok_r, _te_r = _harness.attempt(M.evidence_rows, "nope")
    _te_ok_ru, _te_ru = _harness.attempt(M.rollup, "nope", [], [])
    check("te16 a non-dict manifest is an empty block rather than an "
          "AttributeError - the same call r5 makes for the rest of the rollup, "
          "because a read-only surface must RENDER a broken plan: %r"
          % ((_te_r, _te_ru if not _te_ok_ru else "<rollup ok>"),),
          _te_ok_r and _te_r == [] and _te_ok_ru
          and isinstance(_te_ru, dict)
          and (_te_ru.get("testEvidence") or {}).get("recorded") == 0)

    # F2. `evidence_subjects` promises a subject LIST, and `block.get(key) or []`
    # kept that promise only for the keys that happen to hold one. `recorded` is an
    # int and `byStatus` a dict, so a non-zero count came back AS THE INT out of a
    # function whose every caller feeds it to `len()`, to a list comprehension and
    # to a truth test that a gate verdict hangs off.
    _te_int_ok, _te_int = _harness.attempt(M.evidence_subjects, _te_new,
                                           "recorded")
    _te_map_ok, _te_map = _harness.attempt(M.evidence_subjects, _te_new,
                                           "byStatus")
    check("te17 a key naming no subject list is REFUSED BY NAME rather than "
          "answered. The block really does carry a non-zero `recorded` here, "
          "which is the value the old read handed back: `or []` only substitutes "
          "for a FALSY one, so the empty plan every reviewer tries looks fine and "
          "the populated one leaks an int: %r" % ((_te_int, _te_map),),
          _te_new["testEvidence"]["recorded"] == 2
          and not _te_int_ok and "recorded" in _te_int
          and not _te_map_ok and "byStatus" in _te_map)
    check("te18 SECOND DIRECTION: every key that DOES name a subject list comes "
          "back as that very list, and the legal set is DERIVED from the block's "
          "own shape rather than typed a second time - so a subject list added "
          "later is accepted without an edit here, and `recorded` cannot be "
          "written into it by hand",
          sorted(M.EVIDENCE_SUBJECT_KEYS)
          == ["beforeBoundary", "failing", "missingOnDone", "sinceBoundary",
              "undated", "unrecognised"]
          and all(M.evidence_subjects(_te_new, k) is _te_new["testEvidence"][k]
                  for k in M.EVIDENCE_SUBJECT_KEYS)
          and [(r["id"], r["status"])
               for r in M.evidence_subjects(_te_new, "unrecognised")]
          == [("PE.2", "quarantined")],
          repr(sorted(M.EVIDENCE_SUBJECT_KEYS)))

    # F3. The two conditions read the SAME scopes. `failing-tests` always read
    # both, and a `no-test-evidence` that read only tasks was blind to exactly the
    # sign-off it exists to ask about - `run-test-gate.py --record` points
    # `phase.testEvidence` at the phase gate, and no task pointer stands in for it.
    _te_ph_gap = M.rollup(_ev_plan([("PE.1", "done", "passed")]), [], [])
    _te_ph_ok = M.rollup(_ev_plan([("PE.1", "done", "passed")],
                                  phase_ev="passed"), [], [])
    check("te19 a DONE PHASE with no pointer is a gap too, named with its scope. "
          "Every task under it recorded a run, so a task-only reading exits "
          "clean over a phase nothing signed off - the one shape this condition "
          "was asked for",
          M.evaluate_gate(_te_ph_gap, ("no-test-evidence",))
          == ["no-test-evidence"]
          and [(r["scope"], r["id"])
               for r in _te_ph_gap["testEvidence"]["missingOnDone"]]
          == [("phase", "PE")],
          repr(_te_ph_gap["testEvidence"]["missingOnDone"]))
    check("te20 SECOND DIRECTION: the same plan with the phase's own pointer in "
          "place clears the condition, and the walk demonstrably saw BOTH "
          "subjects - which is what stops te19 reading as 'this condition now "
          "matches every phase'",
          M.evaluate_gate(_te_ph_ok, ("no-test-evidence",)) == []
          and _te_ph_ok["testEvidence"]["missingOnDone"] == []
          and _te_ph_ok["testEvidence"]["recorded"] == 2,
          repr(_te_ph_ok["testEvidence"]))
    _te_hand = {"testEvidence": {"failing": "not a list",
                                "missingOnDone": [{"scope": "task",
                                                   "id": "PE.9"}]}}
    check("te22 ...and a LEGAL key whose value is not a list is [] as well - a "
          "hand-built summary is data, not a caller, so the reasoning for an "
          "absent block applies to it unchanged. The sibling key in the same "
          "block DOES carry a list and comes back whole, which is what stops "
          "this reading as 'the function answers [] to everything'",
          M.evidence_subjects(_te_hand, "failing") == []
          and [r["id"] for r in M.evidence_subjects(_te_hand, "missingOnDone")]
          == ["PE.9"], repr(_te_hand))
    _te_ph_run = _ev_plan([("PE.1", "done", "passed")])
    _te_ph_run["phases"][0]["status"] = "in_progress"
    _te_ph_run_s = M.rollup(_te_ph_run, [], [])
    check("te21 ...and a phase still IN PROGRESS with no pointer is not a gap "
          "either: the condition asks about a claim of completion, which is the "
          "same rule te11 pins for a cancelled task. The recorded count proves "
          "the walk reached this plan at all",
          _te_ph_run_s["testEvidence"]["missingOnDone"] == []
          and M.evaluate_gate(_te_ph_run_s, ("no-test-evidence",)) == []
          and _te_ph_run_s["testEvidence"]["recorded"] == 1,
          repr(_te_ph_run_s["testEvidence"]))

    # --- (eb) the evidence boundary: which gaps COULD have been recorded ------
    # `no-test-evidence` asked whether finished work is backed by a recorded run
    # and never whether it COULD have been, so a plan adopted mid-flight failed
    # on every subject finished before the recorder existed. The boundary is the
    # earliest moment anything says recording existed at all, and it arrives
    # here FROM A CALLER: `_evidence_io` is this module's layer-mate, a
    # layer-mate may not be imported, and `rollup` therefore takes the block the
    # way it already takes `usage`.
    _EB_AT = "2026-06-02T15:38:00Z"
    _eb_asked = _ebio.boundary_of({"at": _EB_AT}, None)
    _eb_silent = _ebio.boundary_of(None, None)

    def _eb_plan(tasks, merged=None):
        """A one-phase plan of DONE subjects that record NOTHING.

        `tasks` is `(id, completedAt or None)`. No subject carries a pointer, so
        every one of them is a gap and the only question left is which side of
        the boundary it sits on.
        """
        rows = [{"id": tid, "title": "t", "status": "done",
                 "completedAt": done} for tid, done in tasks]
        return {"meta": {"version": 2},
                "phases": [{"id": "PE", "title": "e", "status": "done",
                            "mergedAt": merged, "tasks": rows}]}

    def _eb_ids(summary, key):
        return [r.get("id") for r in M.evidence_subjects(summary, key)]

    _eb_pre = _eb_plan([("PE.1", "2026-05-01T00:00:00Z")],
                       merged="2026-05-01T00:00:00Z")
    _eb_post = _eb_plan([("PE.1", "2026-07-01T00:00:00Z")],
                        merged="2026-07-01T00:00:00Z")
    _eb_unasked_s = M.rollup(_eb_post, [], [])
    check("eb1 NOBODY ASKED and NOTHING WAS RECORDED are different answers. "
          "With no boundary handed in, the done subjects still trip the "
          "condition and land in `%s`, nothing is excused, and the rollup "
          "carries no `evidenceBoundary` key at all - the seam `usage` already "
          "sits on, so a consumer reads 'no key' as 'nobody computed one' "
          "without a second probe" % (M.GAP_SINCE,),
          M.evaluate_gate(_eb_unasked_s, ("no-test-evidence",))
          == ["no-test-evidence"]
          and _eb_ids(_eb_unasked_s, M.GAP_SINCE) == ["PE", "PE.1"]
          and _eb_ids(_eb_unasked_s, M.GAP_BEFORE) == []
          and _eb_ids(_eb_unasked_s, M.GAP_UNDATED) == []
          and "evidenceBoundary" not in _eb_unasked_s,
          repr(_eb_unasked_s.get("testEvidence")))
    _eb_silent_s = M.rollup(_eb_post, [], [], boundary=_eb_silent)
    # BOUND, NOT INDEXED INSIDE THE CHECK. A rollup that stopped carrying the key
    # raises out of a `check()` argument and takes every case after it with it -
    # te15's hazard - so the block is read once here and judged by isinstance,
    # which fails THIS case by name and lets the rest run.
    _eb_silent_b = _eb_silent_s.get("evidenceBoundary")
    check("eb2 ...and a boundary that WAS asked and answers nothing excuses "
          "everything: no key states a moment and no run is readable, so no "
          "work in this plan could have carried evidence. The gate passes and "
          "the basis travels in the payload to say why - a null with no "
          "sentence beside it would leave the reader to infer the reason",
          M.evaluate_gate(_eb_silent_s, ("no-test-evidence",)) == []
          and _eb_ids(_eb_silent_s, M.GAP_BEFORE) == ["PE", "PE.1"]
          and _eb_ids(_eb_silent_s, M.GAP_SINCE) == []
          and isinstance(_eb_silent_b, dict)
          and _eb_silent_b.get("at") is None
          and "no run is readable" in str(_eb_silent_b.get("basis")),
          repr(_eb_silent_b))
    _eb_mix = _eb_plan([("PE.1", "2026-05-01T00:00:00Z"),
                        ("PE.2", "2026-07-01T00:00:00Z")],
                       merged="2026-05-01T00:00:00Z")
    _eb_mix_s = M.rollup(_eb_mix, [], [], boundary=_eb_asked)
    check("eb3 pre-boundary work is EXCUSED and post-boundary work in the SAME "
          "plan is not - one fixture, both directions, which is what stops "
          "this reading as 'the boundary excuses everything' or as 'it excuses "
          "nothing'",
          _eb_ids(_eb_mix_s, M.GAP_BEFORE) == ["PE", "PE.1"]
          and _eb_ids(_eb_mix_s, M.GAP_SINCE) == ["PE.2"]
          and M.evaluate_gate(_eb_mix_s, ("no-test-evidence",))
          == ["no-test-evidence"],
          repr(_eb_mix_s["testEvidence"]))
    _eb_on_s = M.rollup(_eb_plan([("PE.1", _EB_AT)], merged=_EB_AT), [], [],
                        boundary=_eb_asked)
    check("eb4 the boundary MOMENT is inside recording, not before it: a "
          "subject finished at the very instant of the earliest evidence is "
          "NOT excused. `<` and `<=` disagree on this fixture and nowhere "
          "else, which is why it is written as its own case",
          _eb_ids(_eb_on_s, M.GAP_BEFORE) == []
          and _eb_ids(_eb_on_s, M.GAP_SINCE) == ["PE", "PE.1"],
          repr(_eb_on_s["testEvidence"]))
    _eb_undated_s = M.rollup(_eb_plan([("PE.1", None)],
                                      merged="2026-05-01T00:00:00Z"),
                             [], [], boundary=_eb_asked)
    check("eb5 a done subject the plan cannot date FAILS, and is named APART "
          "from one the recorder existed for. The repairs differ - run the "
          "gate, versus set the stamp - so a reader must be able to tell which "
          "they have without opening the manifest. The phase beside it IS "
          "dated and IS excused, which is what proves the walk saw both",
          _eb_ids(_eb_undated_s, M.GAP_UNDATED) == ["PE.1"]
          and _eb_ids(_eb_undated_s, M.GAP_SINCE) == []
          and _eb_ids(_eb_undated_s, M.GAP_BEFORE) == ["PE"]
          and M.evaluate_gate(_eb_undated_s, ("no-test-evidence",))
          == ["no-test-evidence"],
          repr(_eb_undated_s["testEvidence"]))
    # LEXICALLY LATER, CHRONOLOGICALLY EARLIER. `_evidence_io.earliest_recorded`
    # compares ledger stamps as TEXT and says why it may: every row is written
    # by one formatter in one UTC spelling. `completedAt` is a PLAN field a
    # human writes, so the same shortcut here excuses the wrong subjects - these
    # two sit a minute either side of the boundary and sort the other way round
    # as text.
    _eb_tz_s = M.rollup(_eb_plan([("PE.1", "2026-06-02T17:37:00+02:00"),
                                  ("PE.2", "2026-06-02T13:39:00-02:00")],
                                 merged="2026-05-01T00:00:00Z"),
                        [], [], boundary=_eb_asked)
    check("eb6 an offset stamp is compared AS A MOMENT and not as text: PE.1 "
          "reads 17:37+02:00, later than the boundary as a string and a minute "
          "earlier as a time, so it is excused; PE.2 reads 13:39-02:00, "
          "earlier as a string and a minute later as a time, so it is not. A "
          "text comparison gets both of them backwards",
          _eb_ids(_eb_tz_s, M.GAP_BEFORE) == ["PE", "PE.1"]
          and _eb_ids(_eb_tz_s, M.GAP_SINCE) == ["PE.2"],
          repr(_eb_tz_s["testEvidence"]))
    _eb_junk_s = M.rollup(_eb_plan([("PE.1", "last Tuesday")],
                                   merged="2026-05-01T00:00:00Z"),
                          [], [], boundary=_eb_asked)
    check("eb7 a stamp nothing can read DATES NOTHING, so it is `%s` and never "
          "excused - a parser answering the epoch for an unreadable string "
          "would put every one of them before the boundary, which is the "
          "direction that widens an excuse in silence" % (M.GAP_UNDATED,),
          _eb_ids(_eb_junk_s, M.GAP_UNDATED) == ["PE.1"]
          and _eb_ids(_eb_junk_s, M.GAP_BEFORE) == ["PE"],
          repr(_eb_junk_s["testEvidence"]))
    _eb_bad_b = _ebio.boundary_of({"at": "whenever"}, None)
    _eb_bad_s = M.rollup(_eb_pre, [], [], boundary=_eb_bad_b)
    check("eb8 ...and a BOUNDARY stating a moment nothing can read excuses "
          "nothing either. This is eb3's excused fixture exactly, so the case "
          "is the comparison failing rather than the plan being post-boundary",
          _eb_bad_b["at"] == "whenever"
          and _eb_ids(_eb_bad_s, M.GAP_BEFORE) == []
          and _eb_ids(_eb_bad_s, M.GAP_SINCE) == ["PE", "PE.1"]
          and M.evaluate_gate(_eb_bad_s, ("no-test-evidence",))
          == ["no-test-evidence"],
          repr(_eb_bad_s["testEvidence"]))
    _eb_torn = _ebio.boundary_of(
        {"at": _EB_AT}, None,
        unknown=["a ledger row could not be parsed, and it may carry an "
                 "earlier run than any that could"])
    _eb_torn_s = M.rollup(_eb_pre, [], [], boundary=_eb_torn)
    check("eb9 A SOURCE THAT COULD NOT BE ASKED WIDENS THE EXCUSE, and the "
          "gate says so by FAILING. The unaskable source may have held an "
          "EARLIER moment, so the boundary may be later than the truth and the "
          "work excused on it may not deserve to be. Nothing here is `%s` and "
          "nothing is `%s`, so without this arm the build goes green on an "
          "excuse nobody could check" % (M.GAP_SINCE, M.GAP_UNDATED),
          M.evaluate_gate(_eb_torn_s, ("no-test-evidence",))
          == ["no-test-evidence"]
          and _eb_ids(_eb_torn_s, M.GAP_SINCE) == []
          and _eb_ids(_eb_torn_s, M.GAP_UNDATED) == []
          and _eb_ids(_eb_torn_s, M.GAP_BEFORE) == ["PE", "PE.1"]
          and M.unevidenced(_eb_torn_s)["unsound"] == _eb_torn["unknown"],
          repr(M.unevidenced(_eb_torn_s)))
    _eb_torn_ok = M.rollup(_ev_plan([("PE.1", "done", "passed")],
                                    phase_ev="passed"), [], [],
                           boundary=_eb_torn)
    check("eb10 SECOND DIRECTION for eb9: the SAME unaskable source over a "
          "plan the boundary excused nothing in adds no failure of its own - "
          "nothing rested on it. Without this half eb9 is satisfied by a "
          "condition that fails whenever `unknown` is non-empty, which would "
          "red every build carrying one torn ledger line",
          M.unevidenced(_eb_torn_ok)["unsound"] == []
          and _eb_ids(_eb_torn_ok, M.GAP_BEFORE) == []
          and _eb_torn_ok["testEvidence"]["recorded"] == 2
          and M.evaluate_gate(_eb_torn_ok, ("no-test-evidence",)) == [],
          repr(M.unevidenced(_eb_torn_ok)))
    _eb_part_s = M.rollup(_eb_plan([("PE.1", "2026-05-01T00:00:00Z"),
                                    ("PE.2", "2026-07-01T00:00:00Z"),
                                    ("PE.3", None)],
                                   merged="2026-07-01T00:00:00Z"),
                          [], [], boundary=_eb_asked)
    _eb_all = [r for k in M.GAP_CLASSES
               for r in M.evidence_subjects(_eb_part_s, k)]
    check("eb11 the classes PARTITION `missingOnDone`: every gap lands in "
          "exactly one of them and none lands in two, so a count over the "
          "classes and a count over the gaps can never disagree. Every class "
          "is non-empty on this fixture, which is what stops the case passing "
          "over a plan that exercises one arm",
          sorted(r["id"] for r in _eb_all)
          == sorted(r["id"]
                    for r in _eb_part_s["testEvidence"]["missingOnDone"])
          and len(_eb_all)
          == len(_eb_part_s["testEvidence"]["missingOnDone"])
          and all(M.evidence_subjects(_eb_part_s, k) for k in M.GAP_CLASSES),
          repr(_eb_part_s["testEvidence"]))
    _eb_ph = _eb_plan([("PE.1", "2026-05-01T00:00:00Z")],
                      merged="2026-07-01T00:00:00Z")
    _eb_ph["phases"][0]["completedAt"] = "2026-05-01T00:00:00Z"
    _eb_ph_s = M.rollup(_eb_ph, [], [], boundary=_eb_asked)
    check("eb12 a PHASE is dated by `mergedAt` and a TASK by `completedAt`. "
          "This phase carries BOTH - a pre-boundary `completedAt` that would "
          "excuse it and a post-boundary `mergedAt` that does not - so a "
          "reader of the wrong field excuses a phase nobody may excuse. The "
          "task beside it is excused off its own stamp, so the rule this pins "
          "is not 'a phase is never excused'",
          _eb_ids(_eb_ph_s, M.GAP_SINCE) == ["PE"]
          and _eb_ids(_eb_ph_s, M.GAP_BEFORE) == ["PE.1"],
          repr(_eb_ph_s["testEvidence"]))
    _eb_door = _eb_plan([("PE.1", "2026-05-01T00:00:00Z"),
                         ("PE.2", "2026-07-01T00:00:00Z"),
                         ("PE.3", None)],
                        merged="2026-07-01T00:00:00Z")["phases"][0]
    check("eb13 `evidence_gap` is the door the report and the panel call, and "
          "it is the SAME rule the summary bucketed by rather than a second "
          "opinion about it: asked subject by subject it reproduces the class "
          "each one landed in above",
          M.evidence_gap(_eb_door, "phase", _eb_asked) == M.GAP_SINCE
          and [M.evidence_gap(t, "task", _eb_asked) for t in _eb_door["tasks"]]
          == [M.GAP_BEFORE, M.GAP_SINCE, M.GAP_UNDATED])
    _eb_covered = _ev_plan([("PE.1", "done", "passed")], phase_ev="passed")
    _eb_running = _eb_plan([("PE.1", "2026-05-01T00:00:00Z")])
    _eb_running["phases"][0]["tasks"][0]["status"] = "in_progress"
    check("eb14 SECOND DIRECTION: a subject with nothing to explain answers "
          "None and not a class - one that CARRIES a pointer, and one nobody "
          "has finished. A door answering `%s` for either would paint 'before "
          "recording' over a task somebody is running right now"
          % (M.GAP_BEFORE,),
          M.evidence_gap(_eb_covered["phases"][0], "phase", _eb_asked) is None
          and M.evidence_gap(_eb_covered["phases"][0]["tasks"][0], "task",
                             _eb_asked) is None
          and M.evidence_gap(_eb_running["phases"][0]["tasks"][0], "task",
                             _eb_asked) is None)
    _eb_ok_sc, _eb_sc = _harness.attempt(M.evidence_gap, _eb_door, "tasks",
                                         _eb_asked)
    check("eb15 a scope this module does not know is REFUSED BY NAME rather "
          "than answered. An unknown scope reads no stamp, so a quiet None "
          "would date nothing and call every subject undated - a mistyped word "
          "silently changing a verdict, which is te17's rule one argument "
          "over. The legal set is in the message: %r" % (_eb_sc,),
          not _eb_ok_sc and "tasks" in str(_eb_sc) and "phase" in str(_eb_sc))
    _eb_hand = {"testEvidence": {"missingOnDone": [{"scope": "task",
                                                    "id": "PE.9"}]}}
    check("eb16 a hand-built summary that names gaps and classifies NONE of "
          "them is not a pass. `rollup` always classifies, so this shape can "
          "only come from a caller that never built one - and the empty class "
          "lists it presents read exactly like a clean plan, which is the "
          "silent pass g5 refuses for the injected invariant block",
          M.evaluate_gate(_eb_hand, ("no-test-evidence",))
          == ["no-test-evidence"]
          and M.unevidenced(_eb_hand)["unsound"] != [],
          repr(M.unevidenced(_eb_hand)))
    check("eb17 `evidenceBoundary` is carried VERBATIM - basis, sources and "
          "unknown whole. The surfaces render the sentence and the gate reads "
          "`unknown`, and neither is served by a block this function "
          "summarised on its way past",
          _eb_torn_s.get("evidenceBoundary") == _eb_torn,
          repr(_eb_torn_s.get("evidenceBoundary")))

    # --- the submodule preflight ---------------------------------------------
    check("s1 .gitmodules paths are read out of `path =` lines, whatever the "
          "spacing",
          M.parse_gitmodules('[submodule "a"]\n\tpath = vendor/a\n'
                             '[submodule "b"]\npath=libs/b\n')
          == ["vendor/a", "libs/b"])
    _sm = {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "files": ["vendor/a/x.ts", "vendor/ab/y.ts", "src/z.ts"]}]}]}
    check("s2 a submodule match is path-BOUNDARY safe: vendor/a matches "
          "vendor/a/x but not vendor/ab/y, which is the off-by-one that would "
          "block a task for no reason",
          M.submodule_conflicts(_sm, ["vendor/a"])
          == [("P1.1", "vendor/a/x.ts", "vendor/a")],
          M.submodule_conflicts(_sm, ["vendor/a"]))
    check("s3 an empty submodule list finds nothing and says nothing",
          M.submodule_conflicts(_sm, []) == [])

    # --- priority: the sort re-orders the ready list and cannot change it -----
    # THE FIXTURE VALUES ARE CHOSEN SO THE TWO IMPLEMENTATIONS DISAGREE. The
    # pinned phase is written LAST, so a version that ignored priority would
    # answer P1.1 first and the pinned one third - which is the only reason
    # these assertions can fail.
    def _plan(pin=None, blocked=None):
        phases = [
            {"id": "P1", "title": "a", "status": "pending",
             "tasks": [{"id": "P1.1", "title": "t", "status": "pending"},
                       {"id": "P1.2", "title": "t", "status": "pending"}]},
            {"id": "P2", "title": "b", "status": "pending",
             "tasks": [{"id": "P2.1", "title": "t", "status": "pending"}]},
            {"id": "P5", "title": "e", "status": "pending",
             "tasks": [{"id": "P5.1", "title": "t", "status": "pending"}]},
        ]
        if pin is not None:
            phases[2]["priority"] = pin
        if blocked is not None:
            phases[2]["blockedBy"] = blocked
        return {"meta": {"version": 2}, "phases": phases}

    _plain, _pinned = _plan(), _plan(pin=1)
    check("pr1 SECOND-DIRECTION CASE: with no priority anywhere the ready list "
          "is document order, byte for byte what the pre-priority loop emitted. "
          "It reads vacuous and is the PROPERTY every case below is measured "
          "against - what goes red the day the ready list starts being ranked by "
          "something else entirely (pr2 is what catches the pin being ignored)",
          M.ready_tasks(_plain) == ["P1.1", "P1.2", "P2.1", "P5.1"],
          repr(M.ready_tasks(_plain)))
    check("pr2 pinning the LAST phase moves its task to the front - the fixture "
          "puts the pin last precisely so a version that ignored priority would "
          "answer differently",
          M.ready_tasks(_pinned) == ["P5.1", "P1.1", "P1.2", "P2.1"],
          repr(M.ready_tasks(_pinned)))
    check("pr3 THE SET IS UNCHANGED: not one id appears or disappears. Priority "
          "re-sorts work that is ALREADY ready; it can reorder the answer and "
          "must never be able to alter it",
          sorted(M.ready_tasks(_pinned)) == sorted(M.ready_tasks(_plain)),
          repr(M.ready_tasks(_pinned)))
    check("pr4 ...and the unpinned phases keep their order relative to each "
          "other, so adding one pin does not re-sort the rest of the plan",
          [t for t in M.ready_tasks(_pinned) if not t.startswith("P5")]
          == M.ready_tasks(_plain)[:3])
    _blocked = _plan(pin=1, blocked=["P2"])
    check("pr5 a PINNED phase whose blockedBy is unsatisfied is skipped: its "
          "task is not ready, and priority never makes an unready task ready",
          M.ready_tasks(_blocked) == ["P1.1", "P1.2", "P2.1"],
          repr(M.ready_tasks(_blocked)))
    check("pr6 ...and the skip is SAID, naming what it waits on and what runs "
          "instead - one key, so the CLI, both reports and the panel print one "
          "sentence rather than four",
          M.priority_note(_blocked)
          == "P5 holds priority 1 but is waiting on P2 (not done) - running "
             "P1.1 instead",
          repr(M.priority_note(_blocked)))
    check("pr7 SECOND-DIRECTION CASE: an honoured pin produces NO note. This is "
          "what goes red if the note becomes unconditional and every run starts "
          "carrying a sentence about a pin that was fine",
          M.priority_note(_pinned) is None and M.priority_note(_plain) is None,
          repr(M.priority_note(_pinned)))
    _roll = M.rollup(_blocked, [], [])
    check("pr8 rollup carries the note under `priorityNote`, ALWAYS present so "
          "no consumer has to probe for the key",
          "priorityNote" in _roll and _roll["priorityNote"]
          == M.priority_note(_blocked), repr(_roll.get("priorityNote")))
    check("pr9 ...and it is None rather than absent when there is nothing to "
          "say, so 'no pin was skipped' and 'nobody looked' stay different",
          M.rollup(_plain, [], [])["priorityNote"] is None)
    check("pr10 each phase row carries the tier the run actually honours - "
          "resolved through `_priority.tier_of`, so a badge can never advertise "
          "a pin the sort ignores",
          [p["priority"] for p in _roll["phases"]] == [None, None, 1],
          repr([p.get("priority") for p in _roll["phases"]]))
    _junk = _plan()
    _junk["phases"][2]["priority"] = "1"
    check("pr11 ...and a `priority` that is not a positive integer reads as no "
          "pin in BOTH the badge and the order - one answer, from one function",
          M.rollup(_junk, [], [])["phases"][2]["priority"] is None
          and M.ready_tasks(_junk) == M.ready_tasks(_plain),
          repr(M.ready_tasks(_junk)))

    # --- porder: the rank the client sorts by, so the client holds no rule -----
    # ONE COMPARATOR, TWO READERS. `_priority.sort_key` is the tree's only
    # expression of phase order; both surfaces are handed a NUMBER instead of the
    # rule - the report stamps it as `data-porder`, the panel ships it on this
    # row. Every case below measures the stamped number against the comparator
    # itself, or against the OTHER surface's function, rather than against a
    # re-typed permutation: an expectation typed out here could only agree with
    # whichever version was in front of the person typing it.
    _rp = M.rollup(_pinned, [], [])["phases"]
    _pinned_ph = _pinned["phases"]
    check("pd1 every phase row carries `porder`, and it orders two phases "
          "exactly as `sort_key` compares them - asserted as a PROPERTY against "
          "the comparator, which is the half a hand-typed list cannot do",
          all("porder" in r for r in _rp)
          and all((_rp[i]["porder"] < _rp[j]["porder"])
                  == (_prio.sort_key(_pinned_ph[i], i)
                      < _prio.sort_key(_pinned_ph[j], j))
                  for i in range(len(_rp)) for j in range(len(_rp)) if i != j),
          repr([r.get("porder") for r in _rp]))
    check("pd2 ...and the FIXTURE separates the two implementations: the pin is "
          "written last, so a rollup that stamped document order would answer "
          "0, 1, 2 and this is the only reason the case can fail",
          [r["porder"] for r in _rp] == [1, 2, 0],
          repr([r.get("porder") for r in _rp]))
    check("pd3 the tier and the rank are DIFFERENT numbers and not "
          "interchangeable - the tier-1 phase here ranks 0 - which is what makes "
          "a surface that sorted on `priority`, or showed `porder` as a badge, "
          "observably wrong rather than merely unidiomatic",
          [(r["priority"], r["porder"]) for r in _rp]
          == [(None, 1), (None, 2), (1, 0)],
          repr([(r.get("priority"), r.get("porder")) for r in _rp]))
    _plain_order = [r["porder"] for r in M.rollup(_plain, [], [])["phases"]]
    check("pd4 SECOND-DIRECTION CASE: with no priority anywhere the ranks are "
          "the identity, so a client sorting by them changes nothing and the "
          "panel's priority option degrades to plan order rather than to a "
          "second opinion about it. Reads vacuous, and is what goes red the day "
          "an absent tier becomes tier 0 and every plan grows a pin",
          _plain_order == list(range(len(_plain_order))) and _plain_order,
          repr(_plain_order))
    # A NON-DICT in `phases[]` is the fixture value that tells a rank computed
    # over the whole array from one computed over the rows: the two lists have
    # different lengths, so any off-by-one shows up as a shifted number rather
    # than as nothing at all.
    _gappy = _plan(pin=1)
    _gappy["phases"].insert(1, "not a phase")
    _gr = M.rollup(_gappy, [], [])["phases"]
    check("pd5 the ranks are computed over the SAME filtered list the rows are, "
          "so a non-dict entry in `phases[]` cannot shift them - a rank taken "
          "over a different sequence is a different number wearing the same name",
          len(_gr) == 3 and [r["porder"] for r in _gr] == [1, 2, 0],
          repr([(r.get("id"), r.get("porder")) for r in _gr]))
    check("pd6 THE TWO SURFACES ARE HANDED THE SAME NUMBER: this row's `porder` "
          "IS the report's `data-porder`. Both are layer 2 and cannot import "
          "each other, so two callers of `_priority.ranks` is structural - and "
          "this is what fails if either grows its own idea of the order",
          [r["porder"] for r in _rp] == _rhtml.phase_ranks(_pinned),
          repr((([r["porder"] for r in _rp]), _rhtml.phase_ranks(_pinned))))
    # --- what `parked` means, and that it is decided once ---------------------
    # Two surfaces print the word: `rollup`'s count, which the header line reads,
    # and `audit-status._proposal_lines`. Each used to decide it, so a proposed
    # entry with no payload made one render say two different numbers.
    check("pp1 the decision is the RAW status alone - a proposed entry with no "
          "payload is parked, because a status surface reports what is there "
          "and materializability is a different question",
          M.is_parked_proposal("proposed") is True
          and M.is_parked_proposal("dropped") is False
          and M.is_parked_proposal("materialized") is False)
    check("pp2 ...and a MISSING status is not parked. `proposal_rows` normalises "
          "an absent status to `proposed` for a badge to paint; a surface that "
          "counted through that reading would be inventing one",
          M.is_parked_proposal(None) is False
          and M.is_parked_proposal("open") is False)
    _pp = {"phases": [], "proposals": [
        {"id": "A", "status": "proposed",
         "payload": {"phase": {"id": "P9", "title": "x", "tasks": []}}},
        {"id": "B", "status": "proposed"},
        {"id": "C", "status": "dropped"},
        {"id": "D"}]}
    _ppsum = M.rollup(_pp, [], [])["proposals"]
    check("pp3 the rollup counts through that one predicate: the payload-bearing "
          "and the payload-less proposed entries both count, the dropped and "
          "the status-less ones do not",
          _ppsum["parked"] == 2 and _ppsum["total"] == 4, repr(_ppsum))
    check("pp4 SECOND-DIRECTION CASE: `parked` is not the total and not the "
          "count of anything that merely appears in `proposals[]`. A count that "
          "stopped reading the status passes pp3 only if this one is here",
          _ppsum["parked"] != _ppsum["total"])
    # Read out of the AST, because the property is about WHERE the decision is
    # taken and every case above passes just as well against a second copy of it
    # that happens to agree today. `_proposal_lines` is the renderer's half.
    with open(_CMD.__file__, "r", encoding="utf-8") as fh:
        _cmd_tree = ast.parse(fh.read(), filename=_CMD.__file__)
    _pl = [n for n in ast.walk(_cmd_tree)
           if isinstance(n, ast.FunctionDef) and n.name == "_proposal_lines"]
    _pl_calls = [c.func.attr for n in _pl for c in ast.walk(n)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]
    _pl_literal = [c for n in _pl for c in ast.walk(n)
                   if isinstance(c, ast.Compare)
                   and any(isinstance(v, ast.Constant)
                           and v.value == M.PARKED_PROPOSAL_STATUS
                           for v in c.comparators)]
    check("pp5 the renderer ASKS this function and does not spell the word "
          "again - one decision is the whole of the fix, and a comparison "
          "against the literal is how the second one came back: %r"
          % (sorted(set(_pl_calls)),),
          len(_pl) == 1 and "is_parked_proposal" in _pl_calls
          and _pl_literal == [])
    check("pd7 ...and its second direction: with nothing pinned the report emits "
          "NO ranks, because it hides the sort control in the same breath, while "
          "the panel offers the control always and stamps the identity. Same "
          "ORDER, different decision about emitting the number - said as a case "
          "so it is never read as the two surfaces disagreeing",
          _rhtml.phase_ranks(_plain) == []
          and _plain_order == list(range(len(_plain_order))),
          repr(_rhtml.phase_ranks(_plain)))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__status_facts.py --selftest\n")
    raise SystemExit(2)
