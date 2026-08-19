#!/usr/bin/env python3
"""
The cases for `_usage_economics.py` - what the work cost, and what the plan said
it could.

Written at U3.2, when `_usage_analytics.py` was cut on its own section markers.
These cases were the `unit` / `bands` / `budget` / `retry` groups of
`test__usage_analytics.py` and moved with their subject, labels unchanged; the
alias case at the foot is new, and pins the one thing the split could have
quietly broken. `M` is the module under test; see `test__cli_fmt.py` for why
that prefix and not a `from ... import` list.

`mkrow` and the fixture rows below are a COPY of the ones in the three sibling
suites this file was cut from, and deliberately so: a shared fixture module would
make one suite's edit reach into four others, which is the coupling the split was
undoing. What is shared here is the subject, not the scaffolding.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_economics as M                       # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):
    def mkrow(day, model, author, task, phase, attr, cost, out_tok=100,
              cr=1000, cw=100, fin=10):
        return {"ts": "2026-08-%02dT10" % day, "model": model, "author": author,
                "taskId": task, "phaseId": phase, "attr": attr,
                "sessionId": "s1", "agentType": "audit-executor", "msgs": 1,
                "in": fin, "out": out_tok, "cacheW5m": cw, "cacheW1h": 0,
                "cacheR": cr, "costUSD": cost}

    man = {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done", "risk": "high", "attempts": 1},
        {"id": "P1.2", "status": "done", "risk": "high", "attempts": 3},
        {"id": "P1.3", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.4", "status": "done", "risk": "low", "attempts": 1},
        {"id": "P1.5", "status": "done", "risk": "med", "attempts": 1},
        {"id": "P1.6", "status": "blocked", "risk": "med", "attempts": 3},
        {"id": "P1.7", "status": "pending", "risk": "low"},
    ]}]}
    ar = [
        mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
        mkrow(2, "claude-opus-5", "a@x", "P1.2", "P1", "task", 30.0),
        mkrow(3, "claude-haiku-4-5", "b@x", "P1.3", "P1", "task", 1.0),
        mkrow(4, "claude-haiku-4-5", "b@x", "P1.4", "P1", "task", 2.0),
        mkrow(5, "claude-sonnet-5", "c@x", "P1.5", "P1", "task", 5.0),
        mkrow(6, "claude-sonnet-5", "c@x", "P1.6", "P1", "task", 7.0),
        mkrow(7, "claude-opus-5", "a@x", None, None, "unattributed", 4.0),
    ]

    # unit_economics: the sample gate
    few = M.unit_economics({"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
    check("unit: projection SUPPRESSED below the sample gate",
          few["projection"] is None and few["sufficient"] is False
          and few["gate"] == M.MIN_TASKS_FOR_PROJECTION)
    ue = M.unit_economics(man, ar)
    check("unit: 5 completed tasks clears the gate", ue["sufficient"] is True)
    check("unit: projection is a p25-p75 RANGE, never a point estimate",
          ue["projection"] and ue["projection"]["low"] <= ue["projection"]["high"])
    check("unit: only DONE tasks count toward cost-per-task",
          ue["completed"] == 5)
    check("unit: remaining counts pending + in_progress + blocked",
          ue["remaining"] == 2)
    check("unit: most-expensive list carries attempts for context",
          ue["mostExpensive"] and len(ue["mostExpensive"][0]) == 3)

    # cost_bands: the same sample gate, and a name that does not collide
    cb = M.cost_bands(man, ar)
    check("bands: 5 completed tasks clears the gate on the relative basis",
          cb["basis"] == "relative" and cb["sufficient"] is True
          and cb["sample"] == 5)
    _ti = M.task_index(man)
    _done_cost = {}
    for _r in ar:
        _t = _r.get("taskId")
        if _t and (_ti.get(_t) or {}).get("status") == "done":
            _done_cost[_t] = _done_cost.get(_t, 0.0) + _r["costUSD"]
    _dc = list(_done_cost.values())
    check("bands: thresholds ARE the project's own median and p90 "
          "(computed from completed tasks only)",
          cb["high"] == round(M._percentile(_dc, 50), 4)
          and cb["outlier"] == round(M._percentile(_dc, 90), 4)
          and cb["high"] <= cb["outlier"])
    check("bands: every classified task lands in exactly one band",
          sum(cb["counts"].values()) == len(cb["byTask"])
          and set(cb["byTask"].values()) <= set(M.BAND_ORDER))
    # COST_BAND_PARAMS is the ONE place the relative basis's shape is stated —
    # panel-server.py JSON-dumps this exact dict into the page as
    # __COST_BAND_PARAMS__, and panel.js reads it back instead of restating the
    # numbers. Pinned against LITERAL values (not re-derived through the
    # constant itself) so a skewed boundary here goes red by name instead of
    # trivially agreeing with itself.
    check("bands: COST_BAND_PARAMS is exactly {gate:5, high:p50, outlier:p90} "
          "— the values panel.js's __COST_BAND_PARAMS__ is generated from",
          M.COST_BAND_PARAMS == {"gate": 5, "percentileHigh": 50,
                                "percentileOutlier": 90})
    # And cost_bands() actually SOURCES its gate/percentiles from that constant
    # rather than a second copy of the numbers: recomputing the same run's
    # thresholds with literal 50/90 must match what cost_bands() returned.
    check("bands: gate and percentiles used ARE COST_BAND_PARAMS, not a "
          "restated copy — this is the constant the JS mirror is generated from",
          cb["gate"] == M.COST_BAND_PARAMS["gate"] == M.MIN_TASKS_FOR_PROJECTION
          and cb["high"] == round(M._percentile(_dc, 50), 4)
          and cb["outlier"] == round(M._percentile(_dc, 90), 4))
    cb_few = M.cost_bands({"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 5.0)])
    check("bands: SUPPRESSED below the gate — no basis, no classification",
          cb_few["basis"] is None and cb_few["sufficient"] is False
          and cb_few["byTask"] == {}
          and cb_few["gate"] == M.MIN_TASKS_FOR_PROJECTION)
    check("bands: band_of returns None while suppressed, so callers cannot "
          "accidentally render a band that was never computed",
          M.band_of(cb_few, "P1.1") is None and M.band_of(None, "P1.1") is None)
    # A configured threshold is an opinion the user already holds, so it needs
    # no sample — but a malformed one must never classify anything.
    cb_abs = M.cost_bands(cb_few and {"phases": [{"id": "P1", "tasks": [
        {"id": "P1.1", "status": "done"}]}]},
        [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 40.0)],
        {"bands": {"highUSD": 5, "outlierUSD": 20}})
    check("bands: an absolute basis needs no sample and is labelled as such",
          cb_abs["basis"] == "absolute" and cb_abs["sufficient"] is True
          and cb_abs["byTask"]["P1.1"] == "outlier")
    for bad in ({"highUSD": "x", "outlierUSD": 20}, {"highUSD": 50, "outlierUSD": 10},
                {"highUSD": 0, "outlierUSD": 10}, {"highUSD": 5}):
        got = M.cost_bands(man, ar, {"bands": bad})
        if got["basis"] != "relative":
            break
    else:
        bad = None
    check("bands: a garbled or inverted threshold pair falls back to the "
          "relative basis instead of classifying wrongly", bad is None)
    check("bands: the word 'risk' is not reused — that axis already exists",
          "risk" not in cb and set(M.BAND_ORDER) == {"typical", "high", "outlier"})

    # phase_budgets: an absent budget is "—", never 0% and never 100%.
    # Explicit rows, so the assertions do not silently depend on what some
    # other fixture happens to price out to.
    _brows = [mkrow(1, "claude-opus-5", "a@x", "P1.1", "P1", "task", 10.0),
              mkrow(2, "claude-opus-5", "a@x", "P2.1", "P2", "task", 13.0),
              mkrow(3, "claude-opus-5", "a@x", None, "P3", "phase", 99.0)]
    pb = M.phase_budgets({"phases": [
        {"id": "P1", "title": "Alpha", "budgetUSD": 40, "tasks": []},
        {"id": "P2", "title": "Beta", "budgetUSD": 10, "tasks": []},
        {"id": "P3", "title": "Gamma", "tasks": []}]}, _brows)
    _byid = {p["id"]: p for p in pb["phases"]}
    check("budget: a phase without one reports None, not zero",
          _byid["P3"]["budget"] is None and _byid["P3"]["pct"] is None
          and _byid["P3"]["over"] is False and _byid["P3"]["spent"] == 99.0)
    check("budget: spend is summed per phase from the ledger",
          _byid["P1"]["spent"] == 10.0 and _byid["P1"]["pct"] == 25.0
          and _byid["P1"]["over"] is False)
    check("budget: pct is uncapped so an overrun reads as an overrun",
          _byid["P2"]["pct"] == 130.0 and _byid["P2"]["over"] is True)
    check("budget: totals cover only the phases that declared a budget "
          "(P3's 99.0 must not inflate them)",
          pb["budgeted"] == 2 and pb["totalBudget"] == 50.0
          and pb["totalSpent"] == 23.0 and pb["anyOver"] is True)
    check("budget: a zero, negative, boolean or string budget is no budget",
          all(M.phase_budgets({"phases": [dict(
              {"id": "P1", "tasks": []}, budgetUSD=bad)]},
              ar)["phases"][0]["budget"] is None
              for bad in (0, -5, True, False, "40", None)))
    check("budget: no budgets anywhere -> totals are None, not 0",
          M.phase_budgets({"phases": [{"id": "P1", "tasks": []}]},
                        ar)["totalBudget"] is None)

    # retry_cost: retried and blocked reported apart, never summed
    rc = M.retry_cost(man, ar)
    check("retry: retried and blocked are SEPARATE figures",
          rc["retriedCost"] == 37.0 and rc["blockedCost"] == 7.0)
    check("retry: no combined 'waste' key exists to be misread",
          not any("waste" in k.lower() for k in rc))
    check("retry: the overlap between the two sets is stated, not hidden",
          rc["overlaps"] == 1)
    check("retry: percentages are of total spend",
          abs(rc["retriedPct"] - 100.0 * 37.0 / 59.0) < 0.2)

    # The alias, not a second definition - see test__usage_spend.py's note.
    import _usage_core as _core
    check("alias: _cost and task_index ARE _usage_core's, not same-named copies "
          "- the split moved them down a layer, so there is still exactly one "
          "definition of each",
          M._cost is _core._cost and M.task_index is _core.task_index)


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_economics.py --selftest\n")
    raise SystemExit(2)
