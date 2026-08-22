#!/usr/bin/env python3
"""
The cases for `_status_facts.py` — the manifest's machine-readable answer, and its boundary.

`audit-status.py`'s 182 cases live in `test_audit_status.py` and run over these
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


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__status_facts.py --selftest\n")
    raise SystemExit(2)
