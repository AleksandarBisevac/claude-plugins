#!/usr/bin/env python3
"""
The cases for `_usage_detail.py` — everything the Usage section folds behind
its `Detail` disclosure.

These six blocks are the ones that make CLAIMS rather than merely showing
numbers, so most of these cases are about what each of them refuses to say:

  * the routing table compares models WITHIN a risk band only, because hard
    work is routed to the stronger model on purpose and a cross-band
    spend-per-task comparison would flag that working system as a fault;
  * the routing ADVICE renders nothing unless the ledger's own evidence clears
    every gate, and on a well-routed project that is the normal outcome rather
    than a gap;
  * the cost band says where its thresholds came from — or, on a young
    project, that it is waiting for a sample. A band whose definition is
    invisible is a number nobody can argue with;
  * retried spend is not wasted spend, and the paragraph says so.

Each gate is pinned in both directions: the case that fails if it never fires,
and the case that fails if it always does. The second reads vacuous and is the
only one that catches an unconditional block.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_detail as M                          # noqa: E402
import _usage_viz as _viz                          # noqa: E402
import _report_usage as _RU                        # noqa: E402


def _u(**kw):
    u = {"showCost": True, "phaseTitles": {}, "taskTitles": {},
         "phaseModel": {}, "seriesAuthorModel": {}, "monthly": {},
         "routing": {}, "unit": {}, "retry": {}, "bands": {}, "heatmap": [],
         "daily": {}}
    u.update(kw)
    return u


def _months(n):
    months = ["2026-0%d" % (i + 1) for i in range(n)]
    return {"months": months,
            "ledger": dict((m, {"tokens": 100, "costUSD": 1.0, "msgs": 5})
                           for m in months),
            "plan": dict((m, {"tasksCompleted": 1, "bugsReported": 0,
                              "bugsFixed": 0, "phasesMerged": 0})
                         for m in months)}


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- month by month ---
    check("ud1 one active month renders nothing: a one-month table restates "
          "the tiles above it", M._monthly_block(_u(monthly=_months(1))) == "")
    out = M._monthly_block(_u(monthly=_months(2)))
    check("ud2 ...and two do - the case that fails if the gate is dropped and "
          "every ledger gets a table", "<table class=\"data\">" in out, out[:80])
    check("ud3 ...and the caption names the derivation FIELD BY FIELD, because "
          "'3 bugs fixed in June' is a claim and its basis is not guessable "
          "from the number",
          "completedAt" in out and "reportedAt" in out and "mergedAt" in out,
          "")
    check("ud4 ...and each row carries its own month key, because the global "
          "date range hides months wholly outside it client-side",
          out.count('data-um=') == 2, out.count('data-um='))
    nc = M._monthly_block(_u(monthly=_months(2), showCost=False))
    check("ud5 ...and the cost column disappears with showCost off, header "
          "and cells together",
          "<th>cost</th>" in out and "<th>cost</th>" not in nc, "")

    # --- routing ---
    check("ud6 no risk bands renders nothing",
          M._routing_table(_u(routing={"risks": []})) == "")
    rt = {"risks": ["high"],
          "byRisk": {"high": {"opus": {"tasks": 3, "costPerTask": 0.5,
                                       "meanAttempts": 1.2}}}}
    out = M._routing_table(_u(routing=rt))
    check("ud7 ...and a band that HAS data draws, with the caption stating "
          "why the comparison is inside a band: hard work is routed to the "
          "stronger model deliberately",
          "<tr><td>high</td>" in out and "routed to the stronger model" in out,
          out[:120])
    check("ud8 ...and no advice is rendered when the ledger's evidence "
          "supports none - the normal outcome on a well-routed project, not a "
          "gap", "What the evidence supports" not in out, "")
    rt2 = dict(rt)
    rt2["advice"] = [{"risk": "high", "from": "opus", "to": "sonnet",
                      "tasks": 3, "fromMeanAttempts": 1.2, "atToRates": 0.2,
                      "atFromRates": 0.5, "saving": 0.3, "savingPct": 60.0,
                      "evidenceTasks": 4, "evidenceAttempts": 1.1}]
    out2 = M._routing_table(_u(routing=rt2))
    check("ud9 ...and when it does, the caveat rides WITH it: an upper bound, "
          "not a forecast, because a different model would not emit the same "
          "tokens", "upper bound, not a forecast" in out2, "")
    check("ud10 ...and both figures are stated so the reader has the whole "
          "divide beside the percentage - which is why savingPct is not "
          "floored", "60%" in out2 and "$0.20" in out2 and "$0.50" in out2, "")

    # --- economics + the band note ---
    check("ud11 no unit economics and no retry data renders nothing",
          M._economics_block(_u()) == "")
    # The projection is PRESENT in the fixture and `sufficient` is not: a
    # fixture with no projection at all cannot tell "gated" from "ungated",
    # which is how the first version of this case survived that mutation.
    out = M._economics_block(_u(unit={"completed": 2, "gate": 5,
                                      "remaining": 3,
                                      "projection": {"low": 1.0,
                                                     "high": 3.0}}))
    check("ud12 ...and a project below the sample gate SAYS the projection is "
          "suppressed and names both numbers, rather than showing a forecast "
          "off a sample too small to mean anything",
          "needs 5 completed tasks" in out and "there are 2" in out
          and "$1.00" not in out, out)
    out = M._economics_block(_u(unit={"completed": 9, "gate": 5,
                                      "sufficient": True, "remaining": 3,
                                      "projection": {"low": 1.0, "high": 3.0}}))
    check("ud13 ...and past the gate it projects a RANGE from the p25-p75 "
          "per-task rate, never a single number",
          "$1.00" in out and "$3.00" in out and "p25" in out, out[:200])
    out = M._economics_block(_u(retry={"totalCost": 1.0, "retriedCost": 0.4,
                                       "retriedTasks": 2, "retriedPct": 0.4,
                                       "blockedCost": 0.1, "blockedTasks": 1}))
    check("ud14 ...and the retry paragraph says retried spend is NOT wasted "
          "spend - the ledger buckets by hour, not by attempt - while naming "
          "the blocked figure as the one with no outcome",
          "not the same as wasted spend" in out
          and "spend with no outcome" in out, "")
    check("ud15 ...and its share is floored, because the total it is a share "
          "OF sits in the tiles far above rather than in this sentence",
          "&lt;1% of spend" in out, out[-400:])

    check("ud16 an absent bands block renders no note at all",
          M._band_note({}) == "")
    out = M._band_note({"sufficient": False, "gate": 5, "sample": 2})
    check("ud17 ...and on a young project the note IS the content: it says "
          "the feature is waiting for a sample, and names the escape hatch",
          "needs 5" in out and "usage.bands.highUSD" in out, out)
    out = M._band_note({"sufficient": True, "basis": "absolute", "high": 1.0,
                        "outlier": 5.0})
    check("ud18 ...and a calibrated band says where its thresholds came from, "
          "so 'this task is an outlier' is a checkable claim",
          "configured thresholds" in out and "$1.00" in out, out)
    out = M._band_note({"sufficient": True, "basis": "sample", "high": 1.0,
                        "outlier": 5.0})
    check("ud19 ...and the sample basis names itself differently - the case "
          "that fails if the two bases print the same sentence",
          "median / p90" in out, out)

    # --- phase composition ---
    check("ud20 no phase/model cross-tab renders nothing",
          M._phase_stacks(_u(), {}, []) == "")
    slots = {"opus": 1, "sonnet": 2}
    u = _u(phaseModel={"P0": {"opus": 60, "sonnet": 40},
                       "--": {"opus": 10}},
           phaseTitles={"P0": "First"})
    out = M._phase_stacks(u, slots, ["opus", "sonnet"])
    check("ud21 ...and a stacked bar carries a LEGEND when more than one "
          "model is plotted: an interior segment has no free end for a label, "
          "so identity must never come from colour alone",
          '<div class="legend">' in out, out[:120])
    check("ud22 ...and with ONE model there is no legend, because the ranked "
          "'By model' list above direct-labels instead",
          '<div class="legend">' not in M._phase_stacks(
              _u(phaseModel={"P0": {"opus": 5}}), {"opus": 1}, ["opus"]))
    check("ud23 ...and the empty phase bucket wears the shared word rather "
          "than its storage key",
          '<span class="nm"><span class="mono">--</span> Uncategorized</span>'
          in out, out[-300:])

    # --- small multiples ---
    check("ud24 one author renders no small-multiples grid: there is nothing "
          "to compare against", M._small_multiples(
              _u(seriesAuthorModel={"a": {"buckets": ["d1"],
                                          "entities": [{"key": "opus",
                                                        "values": [5]}]}}),
              slots) == "")
    sam = {"a": {"buckets": ["d1", "d2"],
                 "entities": [{"key": "opus", "values": [5, 1]}]},
           "b": {"buckets": ["d2", "d3"],
                 "entities": [{"key": "opus", "values": [2, 9]}]}}
    out = M._small_multiples(_u(seriesAuthorModel=sam), slots)
    check("ud25 ...and two authors on DIFFERENT day ranges are re-projected "
          "onto the union, so the same x position is the same date in every "
          "panel - a shared frame is the only thing that makes them comparable",
          "d1 to d3" in out, out[:400])
    check("ud26 ...and the caption STATES both the shared axis and the shared "
          "scale, because a shared frame the reader cannot see is one they "
          "cannot trust",
          "shares one axis" in out and "one scale (peak" in out, "")
    check("ud27 ...and it explains the hairline, so 'too small to draw' is "
          "not read as zero",
          "below this chart's resolution" in out, "")
    check("ud28 ...and every author's cell is in the DOCUMENT, with the top "
          "ones marked - so a chip can reveal one without a re-render, and "
          "paper still shows only the default set",
          out.count('class="smcell"') == 2 and 'data-top="1"' in out, "")

    # --- heatmap ---
    check("ud29 a grid that is not 7 rows renders nothing",
          M._usage_heatmap(_u(heatmap=[[0] * 24] * 3)) == "")
    check("ud30 ...and an all-zero grid renders nothing rather than a frame "
          "drawn to a scale nobody measured",
          M._usage_heatmap(_u(heatmap=[[0] * 24 for _ in range(7)])) == "")
    grid = [[0] * 24 for _ in range(7)]
    grid[0][9] = 100
    out = M._usage_heatmap(_u(heatmap=grid, daily={"2026-07-01": 100}))
    check("ud31 ...and a real grid draws 7x24 cells with a scale key, so the "
          "encoding is readable rather than guessed",
          out.count("<td>") == 7 * 24 and 'class="hmkey"' in out,
          out.count("<td>"))
    check("ud32 ...and BOTH navigation arrows start disabled: at 'all data' "
          "there is no previous period to step to, and an arrow that cannot "
          "act must say so rather than do nothing",
          out.count("disabled") == 2, out.count("disabled"))
    check("ud33 ...and the PNG button is gated on the per-day payload, "
          "because report.js redraws from it and without it the button would "
          "download nothing",
          'data-png="heatmap"' in out
          and 'data-png="heatmap"' not in M._usage_heatmap(
              _u(heatmap=grid, daily={})), "")

    # --- the aliases ---
    _names = ("_small_multiples", "_monthly_block", "_routing_table",
              "_routing_advice_block", "_economics_block", "_band_note",
              "_phase_stacks", "_usage_heatmap")
    _forked = [n for n in _names if getattr(_RU, n) is not getattr(M, n)]
    check("ud34 every fragment `_report_usage` re-exports from here IS this "
          "module's function: %r" % (_forked,), _forked == [])
    _shared = ("TOP_N", "e", "_bin_days", "_fill_pct", "_fmt_cost", "_fmt_pct",
               "_fmt_tokens", "_spark")
    _drift = [n for n in _shared if getattr(M, n) is not getattr(_viz, n)]
    check("ud35 ...and every primitive it draws with is `_usage_viz`'s "
          "object, the same ones the first-paint half uses: %r" % (_drift,),
          _drift == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_detail.py --selftest\n")
    raise SystemExit(2)
