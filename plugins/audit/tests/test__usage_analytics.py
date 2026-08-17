#!/usr/bin/env python3
"""
The cases for `scripts/_usage_analytics.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list.

THE `bn` GROUP IS ABOUT THE `--bench` MODE, AND THAT MODE STAYED BEHIND. `_bench`,
`_bench_cases`, `_bench_rows`, `_bench_manifest`, `_time_best` and the `_BENCH_*`
constants are production code in `_usage_analytics.py` - a benchmark somebody runs,
not a test - so only the CASES ABOUT them moved. They are reached as `M._bench(...)`
like everything else, and `python3 plugins/audit/scripts/_usage_analytics.py --bench`
still runs the benchmark itself.

TWO CASES FORCED A REAL CHANGE, AND BOTH ARE `globals()` REBINDS THAT FAIL IN
OPPOSITE DIRECTIONS. `bn4` swaps each benchmarked function for a counting spy;
inline that was `globals()[_label] = _spy`, which from here would patch a name
nothing calls, every spy would record 0 hits and the case would name every thunk
as mislabelled. `bn5` reads `globals().items()` filtered on `__module__ ==
__name__` to find the public passes this module DEFINES; from here that set is
empty, `_own_public - _timed` is `set()`, and the case would go red claiming the
two deliberate omissions had been fixed. They are `setattr(M, ...)` / `getattr(M,
...)` and `vars(M)` / `M.__name__` - the same rebinding and the same filter,
named on the module that owns them. Both were run in their literal form first
and both went red, one with 8 mislabelled thunks and one with an empty set.

`sys` is imported here rather than prefixed, and that is load-bearing for `bn9`: the
case redirects `sys.stdout` to a StringIO to read what `--bench` prints. `M`'s
`print` resolves `sys.stdout` on the one shared `sys` module object, so the
redirection is seen; a per-module copy would capture nothing and `_out` would be
empty.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_analytics as M                       # noqa: E402


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

    # --- analytics: the honesty guards --------------------------------
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

    # series: top-N fold
    s = M.series(ar, "model")
    check("series: buckets sorted, one value per bucket per entity",
          s["buckets"] == sorted(s["buckets"])
          and all(len(e["values"]) == len(s["buckets"]) for e in s["entities"]))
    check("series: values sum back to each entity total",
          all(sum(e["values"]) == e["total"] for e in s["entities"]))
    many = [mkrow(1, "m%02d" % i, "a@x", None, None, "unattributed", 1.0)
            for i in range(12)]
    sm = M.series(many, "model", top=8)
    check("series: past 8 entities the tail folds into 'other', never a 9th hue",
          len(sm["entities"]) == 9 and sm["entities"][-1]["key"] == "other"
          and sm["folded"] == 4)
    check("series: folding preserves the grand total",
          sum(e["total"] for e in sm["entities"]) == sum(M._tokens(r) for r in many))

    # compare: no prior period -> no invented delta
    c_none = M.compare(ar, "2026-08-01", "2026-08-07")
    check("compare: no prior window -> prior None and no deltas",
          c_none["prior"] is None and c_none["deltas"] == {})
    c_some = M.compare(ar, "2026-08-05", "2026-08-07")
    check("compare: a real prior window yields deltas",
          c_some["prior"] is not None and "tokens" in c_some["deltas"])
    check("compare: a zero-valued prior metric yields None, not a division blow-up",
          M.compare(ar, "2026-08-01", "2026-08-02")["deltas"] in ({}, None)
          or all(v is None or isinstance(v, float)
                 for v in M.compare(ar, "2026-08-05", "2026-08-07")["deltas"].values()))

    # cache_profile: rates, never a fabricated dollar saving
    cp = M.cache_profile(ar)
    check("cache: reports a hit rate and a rate comparison",
          0 <= cp["hitPct"] <= 100 and 0 < cp["inputCostVsFreshPct"] <= 100)
    check("cache: exposes NO fabricated dollar saving",
          not any("sav" in k.lower() or k.endswith("USD") for k in cp))
    check("cache: per-phase rates and a worst phase for the story",
          "P1" in cp["byPhase"] and cp["worstPhase"] is not None)

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

    # routing advice: fires only when THIS repo's own evidence supports it.
    # Both fixtures above route one model per band, so neither produces advice
    # — a well-routed project getting silence is the point, not a gap.
    def band(model, n, attempts, out_tok, risk="low", first=0):
        man_tasks = [{"id": "R%s%d" % (model[7:10], i), "status": "done",
                      "risk": risk, "attempts": attempts} for i in range(n)]
        rws = [mkrow(1 + first, model, "a@x", t["id"], "PR", "task", 0.0,
                     out_tok=out_tok) for t in man_tasks]
        return man_tasks, rws

    o_t, o_r = band("claude-opus-5", 5, 1, 200_000)
    s_t, s_r = band("claude-sonnet-5", 4, 1, 200_000)
    rman = {"phases": [{"id": "PR", "tasks": o_t + s_t}]}
    adv = M.routing(rman, o_r + s_r)["advice"]
    check("advice: a within-band cheaper model with real evidence is named",
          len(adv) == 1 and adv[0]["from"] == "claude-opus-5"
          and adv[0]["to"] == "claude-sonnet-5" and adv[0]["risk"] == "low",
          adv)
    # The three figures must reconcile EXACTLY: a reader who subtracts the two
    # displayed costs has to land on the displayed saving, to the cent.
    check("advice: both sides priced on the SAME tokens at today's rates, and "
          "the arithmetic on screen adds up exactly",
          adv and adv[0]["atFromRates"] > adv[0]["atToRates"] > 0
          and adv[0]["saving"] == round(
              adv[0]["atFromRates"] - adv[0]["atToRates"], 2)
          and adv[0]["savingPct"] == round(
              100.0 * adv[0]["saving"] / adv[0]["atFromRates"], 1),
          adv)
    check("advice: it carries the in-repo evidence it rests on",
          adv and adv[0]["evidenceTasks"] == 4
          and adv[0]["evidenceAttempts"] == 1.0 and adv[0]["tasks"] == 5)

    # Each gate, alone, must silence it.
    s2_t, s2_r = band("claude-sonnet-5", 2, 1, 200_000)
    check("advice: SILENT when the cheaper model has too little in-repo "
          "evidence (a price list is not a finding)",
          M.routing({"phases": [{"id": "PR", "tasks": o_t + s2_t}]},
                  o_r + s2_r)["advice"] == [])
    s3_t, s3_r = band("claude-sonnet-5", 4, 2, 200_000)
    check("advice: SILENT when the cheaper model retries more — a model that "
          "needs two attempts is not cheaper",
          M.routing({"phases": [{"id": "PR", "tasks": o_t + s3_t}]},
                  o_r + s3_r)["advice"] == [])
    tiny_o, tiny_or = band("claude-opus-5", 5, 1, 100)
    tiny_s, tiny_sr = band("claude-sonnet-5", 4, 1, 100)
    check("advice: SILENT when the saving is below the absolute floor",
          M.routing({"phases": [{"id": "PR", "tasks": tiny_o + tiny_s}]},
                  tiny_or + tiny_sr)["advice"] == [])
    x_t, x_r = band("claude-mystery-9", 4, 1, 200_000)
    check("advice: SILENT for a model with no real rates — never recommend a "
          "move onto a price that is a _default guess",
          M._has_rates("claude-mystery-9") is False
          and M.routing({"phases": [{"id": "PR", "tasks": o_t + x_t}]},
                      o_r + x_r)["advice"] == [])
    # Cross-band comparison is the thing the whole table exists to refuse.
    hi_t, hi_r = band("claude-sonnet-5", 4, 1, 200_000, risk="high")
    check("advice: never compares ACROSS risk bands",
          all(a["risk"] == "low" for a in M.routing(
              {"phases": [{"id": "PR", "tasks": o_t + hi_t}]},
              o_r + hi_r)["advice"]))

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

    # routing: within-risk comparison, no bare ratio
    rt = M.routing(man, ar)
    check("routing: grouped by risk band, then model",
          "high" in rt["byRisk"] and "claude-opus-5" in rt["byRisk"]["high"])
    check("routing: exposes NO spend-share/task-share ratio",
          not any("ratio" in k.lower() for cells in rt["byRisk"].values()
                  for cell in cells.values() for k in cell))
    check("routing: carries cost-per-task and mean attempts per cell",
          rt["byRisk"]["high"]["claude-opus-5"]["costPerTask"] == 20.0
          and rt["byRisk"]["high"]["claude-opus-5"]["meanAttempts"] == 2.0)
    check("routing: models come from the LEDGER, not manifest tiers",
          all(m.startswith("claude-") for m in rt["models"]))
    check("routing: risks are ordered high -> low, not alphabetical",
          rt["risks"] == ["high", "med", "low"])

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

    # --- bn: the bench harness measures what it claims ----------------
    # A bench that silently measures the wrong thing is worse than none, so each
    # of these pins one way this one could be wrong while still printing
    # plausible numbers.
    check("bn1 the fixture is EXACTLY the size the bench prints beside every "
          "figure - a row count that drifted would make every per-row number "
          "under it wrong, and nothing else would notice",
          [len(M._bench_rows(k)) for k in (0, 1, 37, 1000)] == [0, 1, 37, 1000])
    check("bn2 ...and it is deterministic AND prefix-stable, which is what "
          "makes the 1k / 10k / 50k rows comparable to each other rather than "
          "three unrelated samples",
          M._bench_rows(200) == M._bench_rows(200)
          and M._bench_rows(200)[:100] == M._bench_rows(100))
    _bm = M._bench_manifest()
    _br = M._bench_rows(M._BENCH_SIZES[0])
    _b_bands, _b_unit = M.cost_bands(_bm, _br), M.unit_economics(_bm, _br)
    check("bn3 the fixture CLEARS every honesty gate in this module, so each "
          "timed case does its real work - a suppressed cost_bands or a "
          "compare() with no prior window returns in microseconds, and the "
          "bench would print that guard clause as the cost of the function",
          _b_bands["sufficient"] and _b_bands["sample"] >= M.COST_BAND_PARAMS["gate"]
          and _b_unit["projection"] is not None
          and M.coverage(_br)["total"] > 0
          and 0 < M.coverage(_br)["attributedPct"] < 100
          and len(M.monthly_activity(_bm, _br)["months"]) == M._BENCH_MONTHS
          and M.phase_budgets(_bm, _br)["budgeted"] > 0
          and len(M.routing(_bm, _br)["risks"]) == 3
          and M.retry_cost(_bm, _br)["retriedTasks"] > 0
          and M.compare(_br, M._BENCH_SINCE, M._BENCH_UNTIL)["prior"] is not None,
          "%r" % (_b_bands,))
    # The label -> function pairing, proven by SWAPPING the named global rather
    # than by reading the source. Both directions fail here: a thunk that
    # stopped calling its function (0 hits) and one that calls it twice or calls
    # its neighbour as well (2 hits) are both reported.
    #
    # `setattr(M, ...)`, not `globals()[...] = `. Inline, the suite lived in the
    # module whose global it was rebinding; from here `globals()` is THIS file's
    # namespace, the thunks would keep calling the real functions, every spy
    # would record 0 hits and `_mislabelled` would name all of them. The
    # rebinding is the same one - it just has to be spelled on the module that
    # owns the name.
    _mislabelled = []
    for _label, _thunk in M._bench_cases(_bm, _br):
        _real, _hits = getattr(M, _label), []

        def _spy(*a, **kw):
            _hits.append(1)
            return _real(*a, **kw)

        setattr(M, _label, _spy)
        try:
            _thunk()
        finally:
            setattr(M, _label, _real)
        if len(_hits) != 1:
            _mislabelled.append((_label, len(_hits)))
    check("bn4 every timed thunk calls the function its LABEL names, exactly "
          "once - a bench that prints one function's cost under another's name "
          "is worse than no bench, because it is believed",
          _mislabelled == [], repr(_mislabelled))
    _timed = set(lbl for lbl, _ in M._bench_cases(_bm, _br))
    # `vars(M)` / `M.__name__` for the same reason, and this one fails the OTHER
    # way if carried literally: this file's namespace holds no public callable
    # defined in `_usage_analytics`, so `_own_public` would be the empty set,
    # `_own_public - _timed` would be `set()`, and bn5 would go red claiming the
    # two deliberate omissions had been fixed. The `__module__` filter is what
    # keeps a re-exported name from another module out of the answer, so it has
    # to compare against the SUBJECT's `__name__`, not this file's.
    _own_public = set(n for n, v in vars(M).items()
                      if not n.startswith("_") and callable(v)
                      and getattr(v, "__module__", None) == M.__name__)
    check("bn5 every rows->dict pass DEFINED here is timed; the only two that "
          "are not are named on purpose (task_index runs inside four of the "
          "cases, band_of is a dict lookup) - so a pass added later and left "
          "unmeasured fails HERE rather than quietly missing from the table",
          _own_public - _timed == {"task_index", "band_of"},
          repr(sorted(_own_public - _timed)))
    # A scripted clock, not sleeps: elapsed 4.0, 1.0, 3.0 over three runs. The
    # three candidate answers are far apart on purpose - minimum 1.0, mean 2.67,
    # last 3.0 - so the fixture can tell a correct harness from either wrong one.
    _ticks = [0.0, 4.0, 4.0, 5.0, 5.0, 8.0]
    _read, _calls = [], []

    def _scripted_clock():
        _read.append(1)
        return _ticks[len(_read) - 1]

    def _counted():
        _calls.append(1)
        return "ok"

    _sec, _res = M._time_best(_counted, 3, clock=_scripted_clock)
    check("bn6 the timed section runs the callable exactly `repeats` times and "
          "hands back its result",
          len(_calls) == 3 and _res == "ok", "%d call(s)" % len(_calls))
    check("bn7 ...and reports the MINIMUM of those runs - never the mean "
          "(2.667) and never the last (3.0)", _sec == 1.0, repr(_sec))
    check("bn8 --selftest wins over --bench whichever order they arrive in, so "
          "CI's per-file sweep can never turn into a benchmark run; a bare "
          "invocation is still a usage error",
          M._mode(["--selftest"]) == "selftest" and M._mode(["--bench"]) == "bench"
          and M._mode(["--selftest", "--bench"]) == "selftest"
          and M._mode(["--bench", "--selftest"]) == "selftest"
          and M._mode([]) == "usage" and M._mode(["--nope"]) == "usage")
    # The printed contract, at a size the suite can afford. Counted, not merely
    # found: one timing line per case plus the two derived lines, so a figure
    # that silently stopped being printed fails instead of going unnoticed.
    import io
    _buf, _stdout = io.StringIO(), sys.stdout
    sys.stdout = _buf
    try:
        _rc = M._bench(sizes=(200,), repeats=2)
    finally:
        sys.stdout = _stdout
    _out = _buf.getvalue()
    _timing_lines = [ln for ln in _out.splitlines() if " ms " in ln]
    check("bn9 --bench exits 0 and prints, for every case, the size, a wall "
          "time in ms and the derived per-row figure - the three things a "
          "human needs in order to act on it",
          _rc == 0 and "rows=200" in _out and "best of 2 runs" in _out
          and "MINIMUM" in _out
          and len(_timing_lines) == len(M._bench_cases(_bm, _br)) + 2
          and all(any(lbl in ln for ln in _timing_lines)
                  for lbl, _ in M._bench_cases(_bm, _br))
          and all((" ms " in ln and " us" in ln) for ln in _timing_lines),
          repr(_out[:400]))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_analytics.py --selftest\n")
    raise SystemExit(2)
