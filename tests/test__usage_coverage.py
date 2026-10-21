#!/usr/bin/env python3
"""
The cases for `_usage_coverage.py` - how much spend the attribution layers
resolved, and the calendar-month roll-up beside plan progress.

Written at U3.2, when `_usage_analytics.py` was cut on its own section markers.
These cases were the `ma` and `coverage` groups of `test__usage_analytics.py` and
moved with their subject, labels unchanged; the alias case at the foot is new,
and pins the one thing the split could have quietly broken. `M` is the module
under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

`mkrow` and the fixture rows below are a COPY of the ones in the three sibling
suites this file was cut from, and deliberately so: a shared fixture module would
make one suite's edit reach into four others, which is the coupling the split was
undoing. What is shared here is the subject, not the scaffolding.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_coverage as M                        # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- monthly_activity (ma) ----------------------------------------
    # One computation site for the 12-month overview's three surfaces
    # (report table, panel card, CLI) - so the honesty rules are pinned
    # here once instead of asserted per renderer.
    _ma_man = {"phases": [
        {"id": "P1", "mergedAt": "2026-06-05T10:00:00Z", "tasks": [
            {"id": "P1.1", "status": "done",
             "completedAt": "2026-06-03T10:00:00Z"},
            {"id": "P1.2", "status": "done",
             "completedAt": "2026-08-02T10:00:00Z"},
            {"id": "P1.3", "status": "pending",
             "completedAt": "2026-08-09T10:00:00Z"},
            {"id": "P1.4", "status": "done", "completedAt": "not-a-date"},
        ]}],
        "bugs": [
            {"id": "BUG-1", "status": "open",
             "reportedAt": "2026-07-15T10:00:00Z", "taskId": "P1.2"},
            {"id": "BUG-2", "status": "wontfix",
             "reportedAt": "2026-07-16T10:00:00Z", "taskId": "P1.1"},
            {"id": "BUG-3", "status": "open",
             "reportedAt": "2026-08-01T10:00:00Z"},
        ]}
    _ma_rows = [
        {"ts": "2026-06-10T09", "in": 5, "out": 100, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 20, "msgs": 2, "costUSD": 0.5},
        {"ts": "2026-08-05T14", "in": 1, "out": 40, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 9, "msgs": 1, "costUSD": 0.25},
        {"ts": "garbage", "in": 9, "out": 9, "cacheW5m": 0,
         "cacheW1h": 0, "cacheR": 0, "msgs": 9, "costUSD": 9.0},
    ]
    ma = M.monthly_activity(_ma_man, _ma_rows)
    check("ma1 months are zero-filled between the first and last month seen "
          "on either side",
          ma["months"] == ["2026-06", "2026-07", "2026-08"])
    check("ma2 both halves carry every month in months[], zeroed when quiet, "
          "so no renderer needs to .get() around holes",
          set(ma["ledger"]) == set(ma["months"]) == set(ma["plan"])
          and ma["ledger"]["2026-07"] == {"tokens": 0, "costUSD": 0.0,
                                          "msgs": 0})
    check("ma3 the ledger half buckets tokens/cost/msgs by calendar month, "
          "and a garbled ts is skipped rather than mis-bucketed",
          ma["ledger"]["2026-06"] == {"tokens": 125, "costUSD": 0.5,
                                      "msgs": 2}
          and ma["ledger"]["2026-08"]["msgs"] == 1
          and sum(v["msgs"] for v in ma["ledger"].values()) == 3)
    check("ma4 tasksCompleted counts DONE tasks by completedAt month - a "
          "completedAt on a pending task does not count, nor an unparseable one",
          ma["plan"]["2026-06"]["tasksCompleted"] == 1
          and ma["plan"]["2026-08"]["tasksCompleted"] == 1
          and sum(v["tasksCompleted"] for v in ma["plan"].values()) == 2)
    check("ma5 bugsReported buckets by reportedAt month",
          ma["plan"]["2026-07"]["bugsReported"] == 2
          and ma["plan"]["2026-08"]["bugsReported"] == 1)
    check("ma6 a bug counts as fixed in the month its LINKED TASK completed "
          "- the effective_bug_status derivation, not a status field",
          ma["plan"]["2026-08"]["bugsFixed"] == 1
          and ma["plan"]["2026-07"]["bugsFixed"] == 0)
    check("ma7 wontfix never reads as fixed, even with a done linked task",
          sum(v["bugsFixed"] for v in ma["plan"].values()) == 1)
    check("ma8 phasesMerged buckets by mergedAt month",
          ma["plan"]["2026-06"]["phasesMerged"] == 1
          and sum(v["phasesMerged"] for v in ma["plan"].values()) == 1)
    check("ma9 the window trims to the LAST n months, dropping older keys "
          "from both halves",
          M.monthly_activity(_ma_man, _ma_rows, months=2)["months"]
          == ["2026-07", "2026-08"]
          and "2026-06" not in M.monthly_activity(
              _ma_man, _ma_rows, months=2)["ledger"])
    check("ma10 empty everything is an empty shape, not a crash",
          M.monthly_activity({}, []) == {"months": [], "ledger": {},
                                       "plan": {}}
          and M.monthly_activity(None, None) == {"months": [], "ledger": {},
                                               "plan": {}})
    check("ma11 an offset timestamp lands in its UTC month",
          M.monthly_activity({"phases": [{"id": "P9", "tasks": [
              {"id": "P9.1", "status": "done",
               "completedAt": "2026-09-01T01:00:00+02:00"}]}]}, [])
          ["plan"]["2026-08"]["tasksCompleted"] == 1)

    def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
              cr=1000, cw=100, fin=10):
        return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                "taskId": task, "phaseId": phase, "attr": attr,
                "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                "cacheR": cr, "costUSD": cost}

    ar = [
        mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
        mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
        mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
        mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
        mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
        mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
        mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
    ]

    # coverage
    cv = M.coverage(ar)
    check("coverage: task-level share never exceeds attributed share",
          0 < cv["taskLevelPct"] <= cv["attributedPct"] <= 100)
    # phase-level spend is attributed but NOT task-level — the gap between the
    # two numbers is exactly the orchestrator's own turns
    cv2 = M.coverage(ar + [mkrow(8, "claude-opus-5", "a@x", None, "P1", "phase", 3.0)])
    check("coverage: phase-attributed spend counts as attributed, not task-level",
          cv2["taskLevelPct"] < cv2["attributedPct"])
    check("coverage: shares across attribution buckets sum to 100",
          abs(sum(cv2["byAttr"].values()) - 100.0) < 0.2, repr(cv2["byAttr"]))
    check("coverage: does not warn on a well-attributed ledger",
          cv["warn"] is False)
    bad = M.coverage([mkrow(1, "m", "a@x", None, None, "unattributed", 1.0)])
    check("coverage: warns when unattributed dominates",
          bad["warn"] is True and bad["attributedPct"] == 0.0)
    check("coverage: empty ledger is not a crash", M.coverage([])["total"] == 0)

    # The alias, not a second definition - see test__usage_spend.py's note.
    import _usage_core as _core
    check("alias: _tokens, _cost and task_index ARE _usage_core's, not "
          "same-named copies - the split moved them down a layer, so there is "
          "still exactly one definition of each",
          M._tokens is _core._tokens and M._cost is _core._cost
          and M.task_index is _core.task_index)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_coverage.py --selftest\n")
    raise SystemExit(2)
