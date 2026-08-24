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
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _loader                                     # noqa: E402
import _status_facts as M                          # noqa: E402
# The comparator itself, and the OTHER surface that reads it. Both are here so
# the `porder` cases can measure the stamped rank against something derived a
# different way: `_priority.sort_key` is the rule, `_report_html.phase_ranks` is
# the report's own call, and a rank compared with itself could not fail.
import _priority as _prio                          # noqa: E402
import _report_html as _rhtml                      # noqa: E402

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
               "unmet_refs", "evaluate_gate", "budget_breaches")
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
