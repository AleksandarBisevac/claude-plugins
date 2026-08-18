#!/usr/bin/env python3
"""
The cases for `_usage_overview.py` — what the Usage section shows on first
paint.

Every fragment here has a "renders nothing" branch, and half these cases are
about that branch rather than about the markup: the trend refuses to plot a
ledger whose peak is zero, the budget block refuses to draw "0 of 0", the author
chips refuse to compare a set of one. Each of those is a place where an empty
frame drawn to a scale nobody measured would look exactly like a measurement,
and each therefore gets **both** directions — the refusal, and the case that
would fail if the refusal became unconditional.

THE CONTEXT LINE IS WHERE THE BASIS LIVES. A cost is a claim, and the rate date
behind every dollar on screen renders beside them or the dollars do not render.
When costs are shown with no date declared it says *that* rather than falling
back to the default table's date, because the ledger prices at write time and
records no rate vintage — a fallback would manufacture a basis. And it is gated
on there being spend to price at all: "rates undated" announced over an empty
usage block is a basis for a claim nobody made.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _usage_overview as M                        # noqa: E402
import _usage_viz as _viz                          # noqa: E402
import _report_usage as _RU                        # noqa: E402


def _u(**kw):
    u = {"totals": {"tokens": 1000, "costUSD": 1.0, "msgs": 10, "sessions": 1,
                    "cacheHitPct": 50.0},
         "counts": {"phases": 1, "people": 1, "models": 1, "sessions": 1,
                    "days": 2, "from": "2026-07-01", "to": "2026-07-02"},
         "showCost": True, "pricingAsOf": "2026-06-01", "pricingStale": False,
         "cache": {"hitPct": 50.0, "inputCostVsFreshPct": 20.0},
         "coverage": {"attributedPct": 90.0, "taskLevelPct": 80.0},
         "unit": {}, "byAuthor": {}, "byPhase": {}, "byModel": {},
         "phaseTitles": {}, "daily": {}, "dailyCost": {}, "budgets": {}}
    u.update(kw)
    return u


# --- cases --------------------------------------------------------------------
def _cases(check):
    # --- the context line: the basis for every dollar below it ---
    out = M._usage_context(_u())
    check("uo1 the context line names the rate date, because every cost "
          "figure below is derived from it", "rates as of 2026-06-01" in out,
          out)
    out = M._usage_context(_u(pricingAsOf=None))
    check("uo2 ...and when costs are shown with NO date declared it says so, "
          "rather than falling back to the default table's date - the ledger "
          "prices at write time and records no vintage, so a fallback would "
          "manufacture a basis", "rates undated" in out, out)
    out = M._usage_context(_u(showCost=False, pricingAsOf=None))
    check("uo3 ...and it is withheld entirely when showCost is off: a basis "
          "with no claim beside it is noise",
          "rates" not in out, out)
    out = M._usage_context(_u(totals={"tokens": 0, "costUSD": 0.0, "msgs": 0},
                              pricingAsOf=None))
    check("uo4 ...and it is gated on there being SPEND to price, not merely "
          "on showCost - 'rates undated' announced over an empty usage block "
          "is a basis for a claim nobody made", "rates" not in out, out)
    check("uo5 ...and a context with nothing to say renders as the empty "
          "string, not as an empty paragraph",
          M._usage_context({"showCost": False}) == "")

    # --- tiles ---
    out = M._usage_tiles(_u())
    check("uo6 the metric strip is five tiles at most - the restraint the "
          "whole section is built on, not everything that can be computed",
          out.count('class="tile"') <= 5 and out.count('class="tile"') >= 3,
          out.count('class="tile"'))
    out_nc = M._usage_tiles(_u(showCost=False))
    check("uo7 ...and the cost tile disappears with showCost off, so a page "
          "that shows no dollars really shows none",
          "equivalent cost" in out and "equivalent cost" not in out_nc, "")
    out = M._usage_tiles(_u(cache={"hitPct": 0.4, "inputCostVsFreshPct": 100}))
    check("uo8 ...and a tile value is FLOORED: a real 0.4% cache hit rendered "
          "`0%` would say the cache never hits, and a tile value stands alone",
          "&lt;1%" in out, out)

    # --- notices ---
    check("uo9 a healthy report has no notices at all",
          M._usage_notices(_u()) == "")
    out = M._usage_notices(_u(pricingStale=True))
    check("uo10 ...and a stale price table is named with its date, because "
          "every cost figure below is derived from it",
          "more than 90 days older" in out and "2026-06-01" in out, out)
    out = M._usage_notices(_u(coverage={"attributedPct": 0.4,
                                        "taskLevelPct": 0.0, "warn": True}))
    check("uo11 ...and the low-coverage notice floors its share: it fires "
          "precisely when coverage is low, so it is the sentence most likely "
          "to land in the 0-to-1 window, and 'Only 0% is attributed' "
          "contradicts the breakdowns it introduces", "&lt;1%" in out, out)

    # --- the one dominant chart ---
    check("uo12 the trend needs at least two days to be a trend",
          M._usage_trend(_u(daily={"2026-07-01": 5})) == "")
    check("uo13 ...and a peak of ZERO plots nothing rather than a flat 1px "
          "baseline under an axis reading '1' - the `or 1` this section "
          "refuses, in the place it would have been least visible",
          M._usage_trend(_u(daily={"2026-07-01": 0, "2026-07-02": 0})) == "")
    out = M._usage_trend(_u(daily={"2026-07-01": 5, "2026-07-02": 10}))
    check("uo14 ...and a real series does plot, which is the case that fails "
          "if either refusal becomes unconditional",
          '<svg class="cols"' in out and 'class="col"' in out, out[:80])
    # Judged over what is INSIDE the <svg>, not over document order: the first
    # version of this case compared two `.index()` values and passed happily
    # when the two format placeholders were merely swapped. What has to be true
    # is that no tick span is inside the scaled coordinate system at all.
    _inside = out[out.index("<svg"):out.index("</svg>")]
    check("uo15 ...and NO axis label is inside the SVG - they are HTML at the "
          "same percentage offsets, because the columns stretch to fill the "
          "width and anything drawn inside a non-uniformly scaled coordinate "
          "system stretches with them (labels came out 49% too wide)",
          '<div class="xts">' in out and 'class="xt"' not in _inside
          and out.count('class="xt"') >= 2, _inside[-120:])
    check("uo16 ...and every column carries its own day, because the global "
          "date range dims the ones outside it client-side",
          out.count('data-d="2026-07-01"') >= 1, "")

    # --- budget ---
    check("uo17 no phase with a budget renders NOTHING: an empty frame "
          "reading '0 of 0' is worse than silence",
          M._budget_block(_u(budgets={"phases": [{"id": "P0", "title": "t",
                                                  "budget": 0, "pct": 0,
                                                  "over": False,
                                                  "spent": 0}]})) == "")
    out = M._budget_block(_u(budgets={
        "phases": [{"id": "P0", "title": "t", "budget": 40.0, "pct": 130.0,
                    "over": True, "spent": 52.0},
                   {"id": "P1", "title": "u", "budget": 0, "pct": 0,
                    "over": False, "spent": 1.0}]}))
    check("uo18 ...while a declared budget draws, the fill CAPS at 100% "
          "because a bar cannot draw past its track, and the number beside it "
          "does not - so the overrun stays visible",
          "width:100.0%" in out and ">130%<" in out, out[:200])
    check("uo19 ...and an unbudgeted phase is COUNTED and named as a "
          "footnote, never drawn as a 0% bar: an unbudgeted phase is not a "
          "phase at zero",
          "1 phase(s) have no" in out and out.count('class="nm"') == 1, out[-260:])

    # --- author chips ---
    check("uo20 one author renders no chips: a set of one has nothing to "
          "compare", M._author_chips(_u(byAuthor={"a": {"tokens": 1,
                                                        "costUSD": 0.1,
                                                        "msgs": 1}})) == "")
    out = M._author_chips(_u(byAuthor={"a": {"tokens": 3, "costUSD": 0.1,
                                             "msgs": 1},
                                       "b": {"tokens": 1, "costUSD": 0.1,
                                             "msgs": 1}}))
    check("uo21 ...and two do, ranked by spend, each carrying its own "
          "pre-formatted totals so report.js writes the summary off the page "
          "rather than through a second implementation of the arithmetic",
          out.count('class="fchip"') == 2 and 'data-tokens=' in out
          and out.index('data-au="a"') < out.index('data-au="b"'), "")
    check("uo22 ...and the note says exactly what the chips scope, because "
          "tasks record no author and the chips must not claim the task table",
          "records no author" in out, "")
    out = M._author_chips(_u(byAuthor={"a": {"tokens": 0, "costUSD": 0.0,
                                             "msgs": 0},
                                       "b": {"tokens": 0, "costUSD": 0.0,
                                             "msgs": 0}}))
    check("uo23 ...and with every author at zero the share is `?`, not a "
          "confident `0%`: no `or 1` fabricating a denominator here either",
          'data-share="?"' in out, out[:200])

    # --- ranked lists ---
    check("uo24 a ranked list over no data renders nothing",
          M._ranked(_u(), "byPhase", "By phase") == "")
    data = dict(("p%d" % i, {"tokens": 100 - i, "costUSD": 0.1, "msgs": 1})
                for i in range(12))
    out = M._ranked(_u(byPhase=data), "byPhase", "By phase")
    check("uo25 ...and past TOP_N the tail is FOLDED and SAID, never silently "
          "cut: a categorical palette cannot keep adjacent pairs "
          "distinguishable past that, so folding is a correctness bound",
          out.count('class="rank"') == M.TOP_N + 1 and "other (4)" in out,
          out.count('class="rank"'))
    out = M._ranked(_u(byPhase={"--": {"tokens": 5, "costUSD": 0.1,
                                       "msgs": 1}}), "byPhase", "By phase")
    check("uo26 ...and the empty bucket wears the shared WORD rather than its "
          "storage key, the same one the HTML, the Markdown and the CLI use",
          '<span class="nm">Uncategorized</span>' in out
          and '<span class="nm">--</span>' not in out, out)
    out = M._ranked(_u(byPhase={"a": {"tokens": 1, "costUSD": 0.1, "msgs": 1},
                                "b": {"tokens": 10000, "costUSD": 0.1,
                                      "msgs": 1}}), "byPhase", "By phase")
    check("uo27 ...and a real-but-tiny row is floored to a visible 0.8% "
          "track: a row at 0.08% of the peak paints an empty bar, which reads "
          "as 'no data' rather than 'a little'", "width:0.8%" in out, out[:400])

    # --- the aliases ---
    _names = ("_usage_context", "_usage_tiles", "_usage_notices",
              "_usage_trend", "_budget_block", "_author_chips", "_ranked")
    _forked = [n for n in _names if getattr(_RU, n) is not getattr(M, n)]
    check("uo28 every fragment `_report_usage` re-exports from here IS this "
          "module's function: %r" % (_forked,), _forked == [])
    _shared = ("TOP_N", "e", "_delta", "_fill_pct", "_fmt_cost", "_fmt_pct",
               "_fmt_tokens", "_hover_share", "_tile", "_tip")
    _drift = [n for n in _shared if getattr(M, n) is not getattr(_viz, n)]
    check("uo29 ...and every primitive it draws with is `_usage_viz`'s "
          "object, so the divide rule has one implementation across both "
          "halves of the section: %r" % (_drift,), _drift == [])


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__usage_overview.py --selftest\n")
    raise SystemExit(2)
