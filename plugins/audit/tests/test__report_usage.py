#!/usr/bin/env python3
"""
The cases for `scripts/_report_usage.py`, moved out of it - an importable helper.

`M` is the module under test; see `test__cli_fmt.py` for why that prefix and not a
`from ... import` list. `_fmt`, `_loader` and `_ui_theme` are imported the way
`_report_usage` imports them - `_loader` because `ul1` REPLACES `_loader.load_script`
with a counting stub on the one shared module object (`load_usage` loads its own
`usage_ledger` with `cache=False`, so there is no module object to patch instead),
and patching a copy would count nothing.

ONE CASE FORCED A REAL CHANGE, AND IT IS `u27`. It is a source lint, not a render
check: every `"{:,}".format(...)` in the report's own source must name a COUNTABLE,
never a token magnitude, because a label reading `3.2M` beside a tooltip reading
`3,230,000` is the defect. Inline it scanned `(__file__, <scripts>/render-report.py)`
- itself, plus the file the formatters were moved out of. After the move `__file__`
is THIS file, and a test file scanning itself for a rule about rendered output is a
green case asserting nothing, so the subject had to be named explicitly.

Naming it as the same two files would have re-pinned a set that was only ever those
two because those were the two files that existed when the rule was written. The
report is assembled by SIX files now, and `_report_page.py` - which emits table cells
and did not exist then - was invisible to the old form. The scan set is every file
that builds the report, and the list is pinned inside the case so that a `_report_*`
file added later costs one deliberate look instead of arriving uncovered. The
widening was proven to catch something the old form did not: a token magnitude
planted in `_report_page.py` leaves the two-file form green and turns this one red.

Exit codes (as a command): 0 selftest pass - 1 selftest fail - 2 usage error.
"""

import os
import re
import sys

import _harness                                    # sets sys.path for scripts/ + hooks/
from _output import safe_stdio                     # noqa: E402
import _report_usage as M                          # noqa: E402
import _fmt                                        # noqa: E402  (as _report_usage imports it)
import _loader                                     # noqa: E402
import _ui_theme as _theme                         # noqa: E402


# --- cases --------------------------------------------------------------------
def _cases(check):

    # The fixture the usage cases have always used: two models, two authors, two
    # phases, two days, and a heatmap with exactly two hot cells.
    _u = {
        "totals": {"tokens": 1500000, "in": 1000, "out": 200000,
                   "cacheW5m": 100000, "cacheW1h": 0, "cacheR": 1199000,
                   "msgs": 42, "costUSD": 12.3456, "sessions": 3, "authors": 2,
                   "models": 2, "tasks": 4, "phases": 2, "cacheHitPct": 79.9},
        "byPhase": {"P1": {"tokens": 1000000, "costUSD": 8.0, "msgs": 30},
                    "--": {"tokens": 500000, "costUSD": 4.3456, "msgs": 12}},
        "byModel": {"claude-opus-5": {"tokens": 900000, "costUSD": 9.0, "msgs": 20},
                    "claude-haiku-4-5": {"tokens": 600000, "costUSD": 3.3, "msgs": 22}},
        "byAuthor": {"a@x.io": {"tokens": 1000000, "costUSD": 8.0, "msgs": 30},
                     "b@x.io": {"tokens": 500000, "costUSD": 4.3, "msgs": 12}},
        "byAgent": {}, "phaseTitles": {"P1": "Alpha"},
        "phaseModel": {"P1": {"claude-opus-5": 900000, "claude-haiku-4-5": 100000},
                       "--": {"claude-haiku-4-5": 500000}},
        "daily": {"2026-08-01": 900000, "2026-08-02": 600000},
        "heatmap": [[0] * 24 for _ in range(7)],
        "showCost": True, "pricingAsOf": "2026-08-06",
        "counts": {"phases": 2, "people": 2, "models": 2, "sessions": 3,
                   "days": 2, "from": "2026-08-01", "to": "2026-08-02"},
        "monthly": {
            "months": ["2026-07", "2026-08"],
            "ledger": {"2026-07": {"tokens": 900000, "costUSD": 7.0,
                                   "msgs": 20},
                       "2026-08": {"tokens": 600000, "costUSD": 5.3456,
                                   "msgs": 22}},
            "plan": {"2026-07": {"tasksCompleted": 2, "bugsReported": 1,
                                 "bugsFixed": 0, "phasesMerged": 1},
                     "2026-08": {"tasksCompleted": 1, "bugsReported": 2,
                                 "bugsFixed": 1, "phasesMerged": 0}}},
    }
    _u["heatmap"][2][14] = 900000
    _u["heatmap"][4][9] = 600000

    uh = M._usage_section(_u)
    um = M._usage_md(_u)

    # uc (F-P-2): the empty bucket is named, not printed as its storage key.
    _uc_html = M._ranked(_u, "byPhase", "By phase")
    check("uc the phase with no id is named from the shared label map in the "
          "ranked list, and its storage key never reaches the page",
          _theme.UNCATEGORIZED in _uc_html
          and "-- unattributed" not in _uc_html
          and ">--<" not in _uc_html)
    _uc_md = M._usage_md(_u)
    check("uc ...and the Markdown twin says the same word, in the same table",
          _theme.UNCATEGORIZED in _uc_md and "| -- |" not in _uc_md)
    check("u3 stat tiles carry compacted totals and equivalent cost",
          "1.5M" in uh and "$12.35" in uh and "equivalent cost" in uh)
    # This case read `"2026-08-06" in uh` for four releases and asserted nothing:
    # render_html stamps `generated <today>`, so on the day it was written the
    # report's own timestamp satisfied it. It failed for the first time when the
    # clock rolled to the 7th - and what it uncovered was real. HTML surfaced
    # pricingAsOf ONLY through the >90-day stale notice, so the ordinary report
    # showed dollars with no way to see what priced them, while the Markdown twin
    # printed it every time. Assert the PHRASE, which no timestamp can produce.
    # (The document-level half of that trap - that the date is not merely the
    # generation stamp - stays in render-report, where the stamp exists.)
    check("u4 pricingAsOf surfaced in HTML, not only once the table has gone stale",
          "rates as of 2026-08-06" in uh)
    # A sub-cent fixture: real spend, but under a cent. `_fmt_cost` delegates to
    # _fmt.fmt_cost for this rule (P10.6) — nothing above spends under $0.01, so a
    # broken delegation (e.g. a raw "$%.2f") would round this to "$0.00" and every
    # OTHER case here would stay green. Asserted through the rendered tile, the
    # narrowest renderer that carries a formatted cost, not through _fmt_cost
    # directly — a call-site regression must fail here even if _fmt.py is fine.
    _uc = dict(_u, totals=dict(_u["totals"], costUSD=0.004))
    check("u42 sub-cent spend renders as <$0.01 in the stat tile, never $0.00",
          "&lt;$0.01" in M._usage_tiles(_uc), M._usage_tiles(_uc))
    check("u4b the Markdown twin says the same thing",
          "rates as of 2026-08-06" in um)
    _uq = dict(_u, showCost=False)
    _hq, _mq = M._usage_section(_uq), M._usage_md(_uq)
    check("u4d withheld when showCost is off, in both renderers - with no dollars "
          "on screen it dates a table nothing visible came from",
          "rates as of" not in _hq and "rates as of" not in _mq
          and "rates undated" not in _hq and "rates undated" not in _mq)
    # Costs shown with no date declared. The default price table HAS a pricingAsOf,
    # so a fallback would nearly always render a plausible date - which is why there
    # is none. The ledger stores costUSD priced at write time and no rate vintage,
    # so the report genuinely does not know it, and printing the default's date
    # would manufacture a basis instead of stating one.
    _un = dict(_u)
    _un.pop("pricingAsOf", None)
    _hn, _mn = M._usage_section(_un), M._usage_md(_un)
    check("u4e costs with no declared rate date say so, rather than showing bare "
          "dollars that look pinned to a table nobody named",
          "rates undated" in _hn and "rates undated" in _mn)
    check("u4f and it never invents one - the default table's date must not leak "
          "in as though the manifest had declared it",
          "rates as of" not in _hn and "rates as of" not in _mn)
    check("u4g the undated notice names the cheap exit, since a reader who cannot "
          "act on it will learn to scroll past it",
          "usage.pricingAsOf" in _hn and "usage.pricingAsOf" in _mn)
    check("u4h silent when there is no spend to price at all - announcing a basis "
          "for a claim never made is the same noise this branch prevents",
          "rates" not in M._usage_context({})
          and "rates" not in M._usage_context({"counts": {"phases": 1}})
          and "rates" not in M._usage_context({"totals": {"tokens": 0}}))
    check("u5 model identity is never colour-alone: legend on the unlabelled "
          "stacks, direct labels on the ranked list",
          'class="legend"' in uh and uh.count("claude-opus-5") >= 2)
    check("u6 model colour follows the entity (slot by NAME, not by rank)",
          M._model_slots(["claude-opus-5", "claude-haiku-4-5"])["claude-haiku-4-5"] == 1
          and M._model_slots(["claude-opus-5", "claude-haiku-4-5"])["claude-opus-5"] == 2)
    check("u7 a 9th model folds into the last slot, never a generated hue",
          max(M._model_slots(["m%d" % i for i in range(12)]).values()) == M.VIZ_SLOTS)
    # Asserted on the stack itself, not on the page. The document-level form of
    # this case (`uh.index("var(--viz-1)") < uh.index("var(--viz-2)")`) was
    # satisfied by the STYLESHEET, which declares --viz-1 before --viz-2 near the
    # top of every report - so it passed whatever order the segments came out in.
    # Read off the section alone it fails immediately, because the ranked "By
    # model" list above sorts by spend and legitimately puts viz-2 first.
    _stack = M._phase_stacks(_u, M._model_slots(_u["byModel"].keys()),
                           sorted(_u["byModel"],
                                  key=lambda m: M._model_slots(
                                      _u["byModel"].keys())[m]))
    check("u8 stacked segments are emitted in slot order (validated adjacency)",
          _stack.index('class="seg" style="flex:100000 0 0;'
                       "background:var(--viz-1)")
          < _stack.index('class="seg" style="flex:900000 0 0;'
                         "background:var(--viz-2)"))
    check("u9 daily column chart and heatmap render",
          'class="cols"' in uh and 'class="hm"' in uh)

    # --- ug: the date-range data layer (C1) ------------------------------------
    # ug1: _hourly regroups ledger rows by calendar date and hour. Fed through a
    # shim so the case tests the regrouping, not the ledger loader.
    class _UlShim(object):
        TOKEN_KEYS = ("in", "out")

        @staticmethod
        def bucket_date(b):
            return b[:10] if isinstance(b, str) and len(b) >= 10 else ""

        @staticmethod
        def bucket_hour(b):
            try:
                return int(b[11:13])
            except (TypeError, ValueError, IndexError):
                return None
    _hrows = [{"ts": "2026-08-01T09", "in": 5, "out": 7},
              {"ts": "2026-08-01T09", "in": 1, "out": 0},
              {"ts": "2026-08-02T23", "in": 2, "out": 2},
              {"ts": "garbage", "in": 9, "out": 9}]
    _hout = M._hourly(_hrows, _UlShim)
    check("ug1 _hourly regroups rows into per-date 24-hour vectors and drops "
          "the unparseable",
          set(_hout) == {"2026-08-01", "2026-08-02"}
          and _hout["2026-08-01"][9] == 13
          and sum(_hout["2026-08-01"]) == 13
          and _hout["2026-08-02"][23] == 4)
    # ug2: the payload script is embedded, deterministic, and carries min/max.
    check("ug2 the per-day payload is embedded as window.AUDIT_USAGE with the "
          "data bounds",
          "window.AUDIT_USAGE=" in uh
          and '"min":"2026-08-01"' in uh and '"max":"2026-08-02"' in uh)
    check("ug2b the payload is byte-deterministic across two renders",
          M._usage_payload(_u) == M._usage_payload(dict(_u)))
    # ug3: no daily data, no payload — and a payload never carries a fetch.
    check("ug3 no daily series renders no payload at all",
          M._usage_payload(dict(_u, daily={})) == "")
    _uhr = dict(_u, hourly={"2026-08-01": [0] * 9 + [123456] + [0] * 14})
    check("ug4 the payload carries the hour vector for a day that has one",
          ",123456," in M._usage_payload(_uhr))
    check("ug4b showCost=false zeroes the payload's costs - no dollars reach a "
          "page that shows none",
          '"2026-08-01":[900000,0,' in M._usage_payload(dict(_uhr, showCost=False))
          and '"showCost":false' in M._usage_payload(dict(_uhr, showCost=False)))
    # ug5: every trend column and tick label says which day it draws — the hook
    # the client-side range dimming filters by.
    check("ug5 trend columns and tick labels carry data-d for the range filter",
          'data-d="2026-08-01"' in M._usage_trend(_u)
          and M._usage_trend(_u).count('data-d="2026-08-02"') >= 2)
    # ug6: monthly rows carry their month key for the same reason.
    check("ug6 monthly rows carry data-um",
          'data-um="2026-07"' in M._monthly_block(_u)
          and 'data-um="2026-08"' in M._monthly_block(_u))
    # ug7: the range line exists (empty + hidden at rest; report.js fills it
    # when a range is active — it is the print story for a scoped chart).
    check("ug7 the range summary line is in the document, hidden at rest",
          'id="audit-urange" hidden' in uh)

    # --- uh: heatmap calendar navigation (C3) ----------------------------------
    check("uh1 the heatmap nav renders all five granularity chips",
          'id="audit-hm-gran"' in uh
          and all('data-g="%s"' % g in uh
                  for g in ("all", "year", "month", "week", "day")))
    check("uh2 both arrows start disabled - at 'all data' there is no period "
          "to step to, and an arrow that cannot act must say so",
          'aria-label="Previous period" disabled>' in uh
          and 'aria-label="Next period" disabled>' in uh)
    check("uh3 the period on display is NAMED, not implied, and the tbody and "
          "peak carry the ids the re-renderer drives",
          'id="audit-hm-period">All data &middot; 2026-08-01 to 2026-08-02<' in uh
          and 'id="audit-hm-body"' in uh and 'id="audit-hm-peak"' in uh)
    _no_hm = dict(_u, heatmap=[])
    check("uh4 no heatmap, no nav - the controls never outlive the grid",
          'id="audit-hm-gran"' not in M._usage_section(_no_hm))

    # --- ux: usage export controls (D2, v0.36) ---------------------------------
    # The daily CSV and the chart PNGs are generated CLIENT-side from the
    # embedded payload (window.AUDIT_USAGE) - these pins only prove the
    # controls exist where the data does, and nowhere else. The downloads
    # themselves are driven in tools/check-report-interactive.mjs.
    check("ux1 with a daily series the usage section offers the daily CSV and "
          "the trend PNG, beside the chart they export",
          'data-csv="usage"' in uh and 'data-png="trend"' in uh)
    check("ux2 the heatmap nav carries its own PNG control",
          'data-png="heatmap"' in M._usage_heatmap(_u))
    _no_daily = M._usage_section(dict(_u, daily={}))
    check("ux3 no daily series, no usage export controls - a button whose "
          "payload is missing would download nothing",
          'data-csv="usage"' not in _no_daily
          and "data-png=" not in _no_daily)
    check("u11 every chart mark carries a title for hover/AT",
          uh.count("<title>") >= 2 and 'role="img"' in uh)
    check("u13 md twin lists authors only when there is more than one",
          "### By author" in um
          and "### By author" not in M._usage_md(
              dict(_u, byAuthor={"a@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})))
    # The whole-page fetch count is pinned by render-report's x5; this narrows it
    # to the section, since that fixture manifest carries a legitimate https link.
    check("u14 the usage section itself adds no external fetch",
          "http" not in M._usage_section(_u))

    # At scale every categorical list must fold and SAY it folded. Silent truncation
    # reads as "that is all of it", which is the worst possible failure for a
    # spend report.
    _big = dict(_u)
    _big["byPhase"] = {"P%d" % i: {"tokens": 100 - i, "costUSD": 1.0, "msgs": 1}
                       for i in range(30)}
    _big["phaseModel"] = {"P%d" % i: {"claude-opus-5": 100 - i} for i in range(30)}
    _big["phaseTitles"] = {"P%d" % i: "Phase %d" % i for i in range(30)}
    _big["seriesAuthorModel"] = {
        "a%02d@x.io" % i: {"buckets": ["2026-08-01"],
                           "entities": [{"key": "claude-opus-5", "total": 100 - i,
                                         "values": [100 - i]}]}
        for i in range(20)}
    _bh = M._usage_section(_big)
    check("u17 ranked lists fold past the top N and label the remainder",
          "other (" in _bh, "no fold marker")
    check("u18 phase composition folds and says how many are hidden",
          _bh.count('class="uphase"') == M.TOP_N and "+22 more phase" in _bh,
          "%d rows" % _bh.count('class="uphase"'))
    # u19 CONTRACT CHANGE (C3): every author's cell is now IN the document —
    # the top 8 by spend visible (data-top), the rest present but `hidden`, so
    # the author chips can reveal any one of them without a re-render. The old
    # pin (exactly TOP_N cells) asserted the tail was NOT in the document; that
    # is the behaviour C3 replaces, and the fold is still said out loud.
    check("u19 small multiples render every author - top-8 visible, the rest "
          "hidden for the chips to reveal - and still say how many are hidden",
          _bh.count('class="smcell"') == 20
          and _bh.count('data-top="1"') == 8
          and _bh.count('" hidden><h4>') == 12
          and "+12 more author" in _bh,
          "%d cells, %d top, %d hidden" % (_bh.count('class="smcell"'),
                                           _bh.count('data-top="1"'),
                                           _bh.count('" hidden><h4>')))
    check("u20 no categorical axis ever exceeds the 8 validated hues",
          max((int(m) for m in re.findall(r"var\(--viz-(\d)\)", _bh)),
              default=0) <= M.VIZ_SLOTS)
    # --- orientation + hover -----------------------------------------------------
    check("u21 context line states scale and span without spending a tile on it",
          'class="uctx"' in uh and "2 people" in uh and "3 sessions" in uh
          and "2026-08-01 to 2026-08-02" in uh and M._usage_context({}) == "")
    # The separator is a middot, spelled as an escape so this file stays ASCII:
    # asserting on "1 phase" alone would also match "1 phases".
    check("u21b counts are singularised (1 phase, not '1 phases')",
          ("1 phase \u00b7"
           in M._usage_context({"counts": {"phases": 1, "people": 3}})))
    _rank_tip = re.search(r'<div class="rank" title="([^"]*)"', uh)
    check("u22 a ranked bar hovers to the exact count, its share of the whole, "
          "cost and messages - none of which the bar itself can show",
          bool(_rank_tip) and "1.00M" in _rank_tip.group(1)
          and "share\t67%" in _rank_tip.group(1)
          and "$8.00" in _rank_tip.group(1) and "messages\t30" in _rank_tip.group(1),
          _rank_tip.group(1) if _rank_tip else "no title on .rank")

    # Small multiples are only comparable on a shared frame, and series() hands us
    # one x axis PER AUTHOR. Two authors active on different days must still line
    # up column-for-column, or the same x means two different dates.
    _sm = dict(_u, seriesAuthorModel={
        "early@x.io": {"buckets": ["2026-08-01", "2026-08-02"],
                       "entities": [{"key": "claude-opus-5", "total": 30,
                                     "values": [10, 20]}]},
        "late@x.io": {"buckets": ["2026-08-05"],
                      "entities": [{"key": "claude-opus-5", "total": 40,
                                    "values": [40]}]}})
    _smh = M._usage_section(_sm)
    _sparks = re.findall(r'<svg class="spark".*?</svg>', _smh, re.S)
    # Proof of a shared axis is GEOMETRIC: with three days in the union, every
    # panel must use the same three column positions at the same width. Before the
    # re-projection the two-day panel drew at 70px slots and the one-day panel at
    # 140px, so the same x meant a different date in each.
    _geom = [set(re.findall(r'<rect(?! class="hit") x="([\d.]+)" y="[\d.]+" '
                            r'width="([\d.]+)"', s)) for s in _sparks]
    check("u23 every small multiple is re-projected onto ONE shared x axis",
          len(_sparks) == 2
          and set().union(*_geom) <= {("0.00", "45.67"), ("46.67", "45.67"),
                                      ("93.33", "45.67")}
          and _geom[0] != _geom[1],
          "%d sparks, geometry %s" % (len(_sparks), _geom))
    check("u23b the shared axis and scale are stated, not merely implemented",
          "2026-08-01 to 2026-08-05" in _smh and "one column per day" in _smh
          and "peak 40 tokens" in _smh)
    # 140px cannot draw a year. Past SPARK_COLS the days bin, and the caption has
    # to say so - silently changing the resolution is the same lie as silently
    # truncating a list.
    _long = ["2026-%02d-%02d" % (1 + i // 28, 1 + i % 28) for i in range(280)]
    _lu = dict(_u, seriesAuthorModel={
        "a@x.io": {"buckets": _long,
                   "entities": [{"key": "claude-opus-5", "total": 280,
                                 "values": [1] * 280}]},
        "b@x.io": {"buckets": _long[:1],
                   "entities": [{"key": "claude-opus-5", "total": 5,
                                 "values": [5]}]}})
    _lh = M._usage_section(_lu)
    _lbars = [len(re.findall(r'<rect(?! class="hit")', s))
              for s in re.findall(r'<svg class="spark".*?</svg>', _lh, re.S)]
    check("u23e 280 days bin down to <=%d columns and the caption says the bin "
          "size (0.5px per column is noise, not a shape)" % M.SPARK_COLS,
          _lbars and max(_lbars) <= M.SPARK_COLS and "one column per 5 days" in _lh,
          "%s cols" % _lbars)
    _late = [s for s in _sparks if "2026-08-05" in s]
    check("u23c a value lands on ITS OWN day after re-projection",
          len(_late) == 1
          and re.search(r'<rect class="hit" x="93', _late[0]) is not None,
          _late[0][-260:] if _late else "no spark carries 2026-08-05")
    check("u23d hover targets are full-height and only on days with spend "
          "(a 2px column is a hit target nobody can hit)",
          _smh.count('class="hit"') == 3
          and _smh.count('<rect class="hit" x="0.00" y="0" width="45.67" '
                         'height="30">') == 1)
    # 0.08% of the peak rounds to width:0.0% - an empty track reads as "no data".
    _tiny = M._ranked(dict(_u, byModel={
        "big": {"tokens": 1000000, "costUSD": 1.0, "msgs": 9},
        "sliver": {"tokens": 300, "costUSD": 0.01, "msgs": 1}}), "byModel", "By model")
    check("u25 a tiny non-zero bar still paints a sliver, never an empty track",
          "width:0.8%" in _tiny and "width:100.0%" in _tiny,
          re.findall(r"width:[\d.]+%", _tiny))

    # --- ud: four fabricated denominators (`or 1` is not a divide guard) --------
    # Four sites forced a divisor to 1: two bar peaks, one share denominator and
    # one sparkline peak. An `or 1` does not prevent a wrong answer, it invents
    # one and dresses it as a measurement. `_fmt.share_pct` is the single divide;
    # the two answers to "there is no whole" are `_fill_pct` (an empty track,
    # because the row prints its own count beside it) and `_hover_share` (`?`,
    # because that string travels alone) — the split `_fmt.bar_cells` and
    # `_fmt.fmt_share` already make, and the one u28b/ua8 already made here.
    _udz = M._ranked(dict(_u, byModel={
        "quiet-a": {"tokens": 0, "costUSD": 0.0, "msgs": 3},
        "quiet-b": {"tokens": 0, "costUSD": 0.0, "msgs": 2}}),
        "byModel", "By model")
    # COUNTED, not found: an implementation that answers `?` for one row and
    # `0%` for the other satisfies a presence assertion and is still wrong.
    check("ud1 with no tokens anywhere the ranked hover says the share could not "
          "be computed, never the confident `0%` a denominator of 1 manufactured",
          _udz.count("share\t?") == 2 and "share\t0%" not in _udz, _udz)
    # ud2 UPDATED, deliberately. It used to pin the ABSENCE of the `<1%` floor
    # ("a row at 0.03% of the grand total reads `0%` here today"), because
    # guarding the divide was not licence to move a measurable share. That
    # decision has since been reversed on purpose: `_hover_share` is now a pure
    # alias for `_fmt.fmt_share` and uf1/uf2 pin the floor in both directions.
    # What survives here is the half that never changed — a share at or above
    # one percent rounds exactly as it always did — which is still the ONLY
    # thing that fails if the floor goes unconditional.
    #
    # The old case also carried `"share\t<1%" not in _tiny`, and that clause
    # asserted nothing: `_tip` escapes its payload, so the raw `<1%` can never
    # appear in the markup and the clause was green either way. uf1 counts the
    # escaped `share\t&lt;1%` instead.
    check("ud2 a share at or above one percent is untouched by the divide "
          "guard: same rounding, same digits as the removed expression",
          "share\t67%" in uh and _tiny.count("share\t100%") == 1
          and "share\t0%" not in _tiny,
          re.findall(r"share\t[^\n\"]*", _tiny))
    # Restoring `or 1` does NOT turn ud3/ud6 red, and that is stated rather than
    # hidden: a peak of zero forces every part to zero, so the fabricated `1` and
    # the honest `None` both render 0.0%. What these two separate is a guarded
    # divide from an unguarded one (the raw expression raises ZeroDivisionError),
    # and an empty track from a sentinel or a floor someone might add later.
    check("ud3 an all-zero ranked list still draws every row - empty track, its "
          "own count beside it - which is why the BAR answers 0 cells where the "
          "hover answers `?`",
          _udz.count('style="width:0.0%;') == 2
          and _udz.count('<span class="amt">0 &middot; $0.00</span>') == 2, _udz)
    _uddays = ["2026-08-01", "2026-08-02"]
    check("ud4 a small-multiples grid whose every panel recorded nothing draws "
          "nothing at all, rather than an empty frame scaled to a peak of one "
          "token nobody spent",
          M._spark([0, 0], 0, "var(--viz-1)", _uddays, "m") == "")
    _udfr = M._spark([0, 0], 40, "var(--viz-1)", _uddays, "m")
    _udbar = M._spark([0, 40], 40, "var(--viz-1)", _uddays, "m")
    check("ud5 ...and the other direction: on a REAL shared peak an all-zero "
          "panel keeps its empty frame - beside a panel that ran plenty, that "
          "emptiness is the finding",
          '<svg class="spark"' in _udfr and "<rect" not in _udfr
          and _udbar.count('<rect class="hit"') == 1
          and _udbar.count("<rect") == 2,
          "%r | %r" % (_udfr, _udbar))
    _udzs = M._phase_stacks(dict(_u, phaseModel={"P1": {"claude-opus-5": 0},
                                               "P2": {"claude-opus-5": 0}}),
                          M._model_slots(["claude-opus-5"]), ["claude-opus-5"])
    check("ud6 a phase stack with nothing in it draws an empty track beside its "
          "own total - the ranked bar's answer, for the same reason",
          _udzs.count('style="width:0.0%"') == 2
          and _udzs.count('<span class="amt">0</span>') == 2, _udzs)
    check("ud6b ...and the measurable stacks are pixel-identical to what the "
          "`or 1` version drew",
          'style="width:100.0%"' in _stack and 'style="width:50.0%"' in _stack,
          re.findall(r'class="stack" style="width:[\d.]+%"', _stack))

    # The removed expressions, restored verbatim, so the manufactured answers are
    # in the suite rather than only in a commit message. `_fmt.py` proves its own
    # the same way. 5-of-0 is not reachable through today's `load_usage` (every
    # breakdown sums to the same total the section gates on), but it is the shape
    # that was written, and it is one filtered `items` away from being served.
    def _share_with_the_or_1(part, whole):
        whole = whole or 1
        return "%.0f%%" % (100.0 * part / whole)

    def _fill_with_the_or_1(part, whole):
        whole = whole or 1
        return 100.0 * part / whole

    check("ud7 mutation proof: the removed `or 1` answers `0%` for 0-of-0 and "
          "fabricates `500%` for 5-of-0, so ud1 goes red on it",
          _share_with_the_or_1(0, 0) == "0%"
          and _share_with_the_or_1(5, 0) == "500%"
          and M._hover_share(0, 0) == "?" and M._hover_share(5, 0) == "?")
    check("ud7b mutation proof (the bar half): the same guard puts a 500%-wide "
          "fill in a track that cannot hold it, where `_fill_pct` draws none",
          _fill_with_the_or_1(5, 0) == 500.0 and M._fill_pct(5, 0) == 0.0
          # ...and the blind spot ud3/ud6 name: at a REACHABLE zero peak every
          # part is zero too, and the two agree exactly. Said here so nobody
          # reads those cases as proof the peaks ever rendered differently.
          and _fill_with_the_or_1(0, 0) == M._fill_pct(0, 0) == 0.0)
    check("ud7c mutation proof (measurable side): every computable divide is "
          "bit-for-bit the removed expression, so no bar or stack moves a pixel "
          "and no hover at or above one percent changes a digit",
          all(M._fill_pct(p, w) == 100.0 * p / w == _fill_with_the_or_1(p, w)
              for p, w in ((1, 3), (900000, 1500000), (7, 12), (0, 5), (300, 1000300)))
          and all(M._hover_share(p, w) == "%.0f%%" % (100.0 * p / w)
                  for p, w in ((1, 3), (0, 5), (900000, 1500000)))
          # (300, 1000300) left the `all(...)` above and is named here instead
          # of being quietly dropped from the tuple: 0.03% is the ONE hover this
          # change moves, and the bar at the same ratio is pinned unmoved on the
          # line above. uf1/uf3 own the rest of that story.
          and M._hover_share(300, 1000300) == "<1%"
          and _share_with_the_or_1(300, 1000300) == "0%")

    # --- uf: the `<1%` floor, and the sites that deliberately refuse it -------
    # `0%` for a slice that EXISTS is the same lie `$0.00` tells about real
    # spend, and `_fmt.fmt_share` has owned that rule since P10.6.
    # `_hover_share` was the last share string in this file still spelling out
    # fmt_share WITHOUT it — ud2 above used to pin that absence. It is now a
    # pure alias, and the derived rates (cache, coverage, retry) render through
    # `_fmt_pct`, which is the same rule for a percentage that arrives already
    # divided.
    #
    # ONE fixture proves both directions at once, and it has to: a case built
    # only from a tiny row passes on an implementation that floors EVERYTHING,
    # and a case built only from a zero passes on one that floors nothing.
    # Three rows over a grand total of 1,000,300 — 99.97%, 0.03% and a true
    # zero — so the three implementations produce three different maps.
    _uf = M._ranked(dict(_u, byModel={
        "big": {"tokens": 1000000, "costUSD": 1.0, "msgs": 9},
        "sliver": {"tokens": 300, "costUSD": 0.01, "msgs": 1},
        "silent": {"tokens": 0, "costUSD": 0.0, "msgs": 1}}),
        "byModel", "By model")
    # label -> the share its own tooltip reports, read back off the markup, so a
    # row cannot borrow its neighbour's answer the way a bare `in` check allows.
    _ufshares = dict(re.findall(r'title="([^"\n]*)\n[^"]*?share\t([^\n"]*)', _uf))
    check("uf1 a measurable-but-tiny row hovers `&lt;1%`: 0.03% of the grand "
          "total is a slice that exists, and `0%` reported it as nothing",
          _ufshares.get("sliver") == "&lt;1%"
          and _uf.count("share\t&lt;1%") == 1, _ufshares)
    # The second direction, and the one that would be cut in review: it passes
    # on the PRE-fix code by construction and is the only case that fails if the
    # floor becomes unconditional — `<1%` for a row with no tokens would invent
    # a presence, the mirror-image lie fmt_share's own `pct and` guard prevents.
    check("uf2 ...and a genuine zero still reads `0%`, beside a full row that "
          "still reads `100%` - the floor fires on smallness, never absence",
          _ufshares == {"big": "100%", "sliver": "&lt;1%", "silent": "0%"}
          and _uf.count("share\t0%") == 1, _ufshares)

    def _hover_without_the_floor(part, whole):
        pct = _fmt.share_pct(part, whole)
        return "?" if pct is None else "%.0f%%" % pct   # the floor, removed

    # The second pair is not invented: claude-fable-5 spends 655,243 of
    # acme-store's committed 93,126,797 tokens, and that row is the one string
    # this change moves in the worked example. It also shows the floor is not
    # merely about rounding DOWN — 0.70% was being rounded UP to a confident
    # `1%`, overstating a slice that never reached one percent.
    check("uf3 mutation proof: the removed `\"%.0f%%\" % pct` calls a real "
          "0.03% row `0%` and rounds a real 0.70% row UP to `1%`, so uf1 goes "
          "red on it - while a true zero renders the same either way",
          _hover_without_the_floor(300, 1000300) == "0%"
          and M._hover_share(300, 1000300) == "<1%"
          and _hover_without_the_floor(655243, 93126797) == "1%"
          and M._hover_share(655243, 93126797) == "<1%"
          and _hover_without_the_floor(0, 100) == M._hover_share(0, 100) == "0%"
          # the sentinel is unchanged by the adoption - fmt_share's own default
          and M._hover_share(5, 0) == _hover_without_the_floor(5, 0) == "?")

    # The derived rates. Each stands alone in a tile, a warning or a sentence,
    # with the total it is a share OF nowhere near it, so each floors.
    _ufr = dict(_u,
                cache={"hitPct": 0.4, "inputCostVsFreshPct": 0.4,
                       "worstPhase": ("P2", 0.4)},
                coverage={"attributedPct": 0.4, "taskLevelPct": 0.0,
                          "warn": True},
                retry={"totalCost": 10.0, "retriedCost": 0.5, "retriedTasks": 1,
                       "retriedPct": 0.4, "blockedCost": 0.0, "blockedTasks": 0,
                       "overlaps": 0},
                totals=dict(_u["totals"], cacheHitPct=0.4))
    _uftiles = M._usage_tiles(_ufr)
    check("uf4 a real-but-tiny cache hit, attribution and retried share render "
          "`&lt;1%` in the tiles, the coverage warning and the economics line - "
          "'bills at 0% of fresh-token rates' says the input side is free",
          _uftiles.count('<div class="v">&lt;1%</div>') == 2
          and "bills at &lt;1% of fresh-token rates" in _uftiles
          and "Only &lt;1% of spend is attributed" in M._usage_notices(_ufr)
          and "(1 task(s), &lt;1% of spend)" in M._economics_block(_ufr),
          _uftiles)
    # ...and the other direction, on the same four sites: a rate that really is
    # zero must not be dressed up as a tiny one. `taskLevelPct` is 0.0 in the
    # fixture above precisely so one tile answers each way.
    _ufz = dict(_u,
                cache={"hitPct": 0.0, "inputCostVsFreshPct": 0.0,
                       "worstPhase": ("P2", 0.0)},
                coverage={"attributedPct": 0.0, "taskLevelPct": 0.0,
                          "warn": True},
                retry={"totalCost": 10.0, "retriedCost": 0.0, "retriedTasks": 0,
                       "retriedPct": 0.0, "blockedCost": 0.0, "blockedTasks": 0,
                       "overlaps": 0},
                totals=dict(_u["totals"], cacheHitPct=0.0))
    _ufztiles = M._usage_tiles(_ufz)
    check("uf5 a rate that is genuinely zero still reads `0%` at every one of "
          "those sites - the case that fails if `_fmt_pct` floors everything",
          "&lt;1% down to a specific task" not in _uftiles
          and "0% down to a specific task" in _uftiles
          and "&lt;1%" not in _ufztiles
          and _ufztiles.count('<div class="v">0%</div>') == 2
          and "Only 0% of spend is attributed" in M._usage_notices(_ufz)
          and "(0 task(s), 0% of spend)" in M._economics_block(_ufz),
          _ufztiles)
    # The twin must not be the more honest of the two, or the less: this table
    # IS the documented relief for the light-mode palette slots.
    _ufmd = M._usage_md(_ufr)
    check("uf6 the Markdown twin floors the same six rates the page does, and "
          "carries the bare `<1%` the way it already carries `<$0.01`",
          "cache hit <1%" in _ufmd
          and "**Cache:** <1% hit; the input side bills at <1% of "
              "fresh-token rates." in _ufmd
          and "**Lowest cache phase:** P2 at <1%." in _ufmd
          and "**Attribution:** <1% of spend attributed (0% to a specific "
              "task)." in _ufmd
          and "(<1% of spend)" in _ufmd
          # Exactly six: the head's cacheHitPct, the cache pair, the worst
          # phase, attribution and the retried share. Counted rather than
          # found, so taskLevelPct's genuine 0.0 cannot drift into the floor
          # without this going red.
          and _ufmd.count("<1%") == 6,
          [ln for ln in _ufmd.splitlines() if "%" in ln])

    # The refusals. Each of these prints the two numbers it was divided from
    # within a few characters of the percentage, so `0%` cannot mislead and a
    # floor would only disagree with the track drawn beside it.
    _ufbud = M._budget_block(dict(_u, budgets={
        "phases": [{"id": "P1", "title": "Alpha", "budget": 40.0, "spent": 0.03,
                    "pct": 0.075, "over": False}],
        "budgeted": 1, "totalBudget": 40.0, "totalSpent": 0.03,
        "anyOver": False}))
    check("uf7 a budget label does NOT floor: `$0.03 of $40.00` is on the same "
          "row, so the whole divide is on screen and `<1%` would only disagree "
          "with the 0.1%-wide track beside it",
          '<span class="pct">0%</span>' in _ufbud
          and "$0.03 of $40.00" in _ufbud
          and "&lt;1%" not in _ufbud and "<1%" not in _ufbud, _ufbud)
    check("uf8 nor does a bar width, a percent CHANGE, or a saving printed "
          "between both of its dollar figures - a width cannot say `<1%`, and "
          "`+0%` means unchanged rather than `a slice exists`",
          "width:0.8%" in _uf            # the geometric form of the same floor
          and '<span class="dl up">+0%</span>'
              == M._delta({"compare": {"deltas": {"tokens": 0.4}}}, "tokens")
          and "$0.30 less (0%)" in M._routing_advice_block({"advice": [{
              "risk": "low", "from": "a", "to": "b", "tasks": 9,
              "fromMeanAttempts": 1.0, "atFromRates": 148.30,
              "atToRates": 148.00, "saving": 0.30, "savingPct": 0.2,
              "evidenceTasks": 4, "evidenceAttempts": 1.0}]}))

    # --- one number format, everywhere ------------------------------------------
    check("u26 tokens are compact at one decimal, and two on hover",
          M._fmt_tokens(3230000) == "3.2M" and M._fmt_tokens(3230000, 2) == "3.23M"
          and M._fmt_tokens(942) == "942" and M._fmt_tokens(2000000000) == "2.0B"
          and M._fmt_tokens(214300, 2) == "214.30K",
          M._fmt_tokens(3230000, 2))
    # The rule is easy to state and easy to break one call site at a time: the
    # label reads 3.2M and the tooltip that opens over it reads 3,230,000. So the
    # guard is mechanical - every raw thousands-separated number must be a
    # COUNTABLE (messages, sessions, tasks), never a token magnitude. It reads
    # render-report's source too: the formatters moved here, the rule did not stop
    # applying to the file they left (a file read, never an import - the DAG says
    # nothing in here may depend on that module).
    #
    # _COUNTABLES IS A CLOSED LIST, ON PURPOSE, and that is the maintenance cost of
    # this guard rather than a defect in it. A permissive default - "allow anything
    # that does not look like tokens" - would let the next magnitude through
    # silently, which is the one failure a lint like this must not have. So every
    # genuinely new countable is added HERE, deliberately, and the diff that adds it
    # is the record that somebody looked. `rows` is the case that proved it:
    # render-report's --bench banner prints a count of LEDGER ROWS, the rule allowed
    # it in words, and the vocabulary did not - so a correct line went red until this
    # list caught up. Widen it only for a true countable; a magnitude belongs in
    # `_fmt_tokens`.
    _COUNTABLES = r"msgs|sessions|tasks|phases|rows"
    # THE SCAN SET WIDENED WHEN THIS SUITE MOVED, and the move is what exposed
    # why it had to. Inline the loop read `(__file__, .../render-report.py)`:
    # this file, plus the file the formatters came from. `__file__` is the TEST
    # now, and a test scanning itself for a rule about rendered output proves
    # nothing - so the subject had to be named explicitly anyway. Naming it as a
    # two-item tuple would have re-pinned a set that was only ever those two
    # because those were the two files that existed when the rule was written.
    # The report is assembled by SIX files today, `_report_page.py` emits table
    # cells, and a `"{:,}".format(...)` added there was invisible to the old
    # form. So the set is every file that builds the report, listed once.
    #
    # PINNED, not merely globbed, for the same reason `_COUNTABLES` is a closed
    # list: a glob that silently narrowed to nothing would leave `_bad == []`
    # reading as all clear, and a NEW `_report_*.py` should cost one deliberate
    # look rather than arriving uncovered.
    _REPORT_SOURCES = ["_report_html.py", "_report_md.py", "_report_page.py",
                       "_report_ui.py", "_report_usage.py", "render-report.py"]
    #
    # RESOLVED BY BASENAME, NOT BY `listdir(SCRIPTS_DIR)`. All six sit in
    # `scripts/report/` now, and the flat listing found none of them - `_scanned`
    # narrowed to `[]`, which is exactly the "reads as all clear" failure the
    # paragraph above is about, and the `_scanned == _REPORT_SOURCES` half of the
    # assertion is the only reason it was a red line instead of a green one.
    # `script_index()` is the tree's one answer to where a basename lives, so this
    # keeps finding them wherever a later domain move puts them.
    _index = _loader.script_index()
    _scanned = sorted(n for n in _REPORT_SOURCES if n in _index)
    _bad = []
    for _n in _scanned:
        with open(_index[_n][0], encoding="utf-8") as _fh:
            _src = _fh.read()
        _bad += [(_n, x)
                 for x in re.findall(r'"\{:,\}"\.format\(([^)]*)\)', _src)
                 if not re.search(_COUNTABLES, x)]
    check("u27 no token value is ever rendered with thousand separators "
          "(counts may be; magnitudes may not)",
          _bad == [] and _scanned == _REPORT_SOURCES,
          "%r; scanned %r" % (_bad, _scanned))
    check("u28 the md twin uses the same compact tokens as the HTML labels",
          "**Total:** 1.5M tokens" in um and "| P1 | 1.0M |" in um,
          [ln for ln in um.splitlines() if "1.0M" in ln or "Total:" in ln][:3])
    # preserveAspectRatio="none" scales the coordinate system non-uniformly, and
    # that scales the glyphs with it - measured at +49% width on a 1072px render.
    # The bars are meant to stretch; the type is not, so the type is not in there.
    # u28b: the trend's own `or 1`. Two days that both recorded zero tokens is a
    # peak of zero, and the fabricated denominator drew a flat 1px baseline under
    # a y axis labelled `1` and an aria-label reading "peak 1" — a token count
    # nothing in the ledger recorded. The fixture keeps TWO days so the
    # `len(days) < 2` guard above cannot be what produces the empty string.
    check("u28b an all-zero trend renders nothing rather than a flat baseline "
          "under a y axis labelled with a peak nobody recorded",
          M._usage_trend(dict(_u, daily={"2026-08-01": 0, "2026-08-02": 0})) == ""
          and "peak 1" not in M._usage_trend(dict(_u, daily={"2026-08-01": 0,
                                                           "2026-08-02": 0})))
    # ...and the other direction: the guard must not swallow a real series. A
    # single zero DAY inside a series that has a peak still draws its column, so
    # an implementation that returned "" on any zero is caught here.
    check("u28c one quiet day inside a real series still draws its chart",
          'data-d="2026-08-02"' in M._usage_trend(
              dict(_u, daily={"2026-08-01": 900000, "2026-08-02": 0}))
          and "peak 900.0K" in M._usage_trend(
              dict(_u, daily={"2026-08-01": 900000, "2026-08-02": 0})))
    _trend = M._usage_trend(_u)
    check("u29 no text is drawn inside the stretched chart space",
          "<text" not in _trend and 'class="xt"' in _trend
          and 'class="yt"' in _trend and 'class="colswrap"' in _trend)
    check("u29b gridlines keep a true 1px hairline under any stretch",
          'vector-effect="non-scaling-stroke"' in _trend)
    check("u29c the first and last date tick anchor to their own edge so "
          "neither can hang outside the plot",
          "left:0;transform:none" in _trend
          and "right:0;left:auto;transform:none" in _trend)
    # --- cost bands ---------------------------------------------------------------
    # The young-project case is the one that matters here: acme has 4 completed
    # tasks, so the report must SAY the band is waiting for a sample rather than
    # print nothing and leave the column unexplained.
    _sup = M._band_note({"sufficient": False, "gate": 5, "sample": 3})
    check("u30 below the gate the report explains the absence and names the "
          "config escape hatch",
          "needs 5" in _sup and "there are 3" in _sup
          and "usage.bands.highUSD" in _sup)
    _rel = M._band_note({"sufficient": True, "basis": "relative",
                       "high": 5.5936, "outlier": 35.4031})
    check("u31 an active band states its basis AND its thresholds",
          "median / p90" in _rel and "$5.59" in _rel and "$35.40" in _rel)
    check("u32 an absolute basis says so instead of claiming a percentile",
          "configured thresholds" in M._band_note(
              {"sufficient": True, "basis": "absolute", "high": 15, "outlier": 50}))
    _bh2 = M._usage_section(dict(
        _u, unit={"mostExpensive": [("P1.1", 40.0, 2)], "completed": 6,
                  "remaining": 1, "gate": 5, "sufficient": True},
        taskTitles={"P1.1": "Hash passwords"},
        bands={"sufficient": True, "basis": "relative", "high": 5.0,
               "outlier": 20.0, "byTask": {"P1.1": "outlier"}}))
    check("u33 the band renders as a labelled pill, never colour alone",
          '<span class="bandpill b-outlier">outlier</span>' in _bh2
          and "<th>cost band</th>" in _bh2)
    # --- phase budgets ------------------------------------------------------------
    # The common case is that nobody set a budget; an empty "0 of 0" frame would be
    # worse than silence.
    check("u34 no budget anywhere renders nothing at all",
          M._budget_block(dict(_u, budgets={"phases": [
              {"id": "P1", "title": "A", "budget": None, "spent": 5.0,
               "pct": None, "over": False}], "budgeted": 0,
              "totalBudget": None, "totalSpent": None, "anyOver": False})) == "")
    _bud = M._budget_block(dict(_u, budgets={
        "phases": [
            {"id": "P1", "title": "Alpha", "budget": 40.0, "spent": 28.22,
             "pct": 70.6, "over": False},
            {"id": "P2", "title": "Beta", "budget": 25.0, "spent": 32.53,
             "pct": 130.1, "over": True},
            {"id": "P3", "title": "Gamma", "budget": None, "spent": 9.0,
             "pct": None, "over": False}],
        "budgeted": 2, "totalBudget": 65.0, "totalSpent": 60.75, "anyOver": True}))
    check("u35 an overrun sorts first, reads past 100% and is labelled 'over'",
          _bud.index("Beta") < _bud.index("Alpha")
          and "130%" in _bud and "&middot; over" in _bud
          and 'class="bud over"' in _bud)
    check("u36 the bar caps at the track while the number does not, so the "
          "overrun stays visible",
          'style="width:100.0%"' in _bud and 'style="width:70.6%"' in _bud)
    check("u37 unbudgeted phases are counted in a footnote, never drawn at 0%",
          "1 phase(s) have no" in _bud and "not phases at zero" in _bud
          # exactly 2 phase rows + the total; the `buds` container must not count
          and len(re.findall(r'class="bud(?: over| total)?"', _bud)) == 3,
          re.findall(r'class="bud[^"]*"', _bud))
    check("u38 the total covers only budgeted phases",
          "$60.75 of $65.00" in _bud)
    # --- routing advice -----------------------------------------------------------
    check("u39 no advice renders nothing - silence is the normal outcome on a "
          "well-routed project, not a gap",
          M._routing_advice_block({"advice": []}) == ""
          and M._routing_advice_block({}) == "")
    _adv = M._routing_advice_block({"advice": [{
        "risk": "low", "from": "claude-opus-5", "to": "claude-sonnet-5",
        "tasks": 9, "fromMeanAttempts": 1.0, "atFromRates": 148.30,
        "atToRates": 89.00, "saving": 59.30, "savingPct": 40.0,
        "evidenceTasks": 4, "evidenceAttempts": 1.0}]})
    check("u40 the advice names the band, both models, the saving and the "
          "in-repo evidence it rests on",
          all(s in _adv for s in ("low", "claude-opus-5", "claude-sonnet-5",
                                  "$59.30", "40%", "already run 4 task(s)")),
          _adv)
    check("u41 the caveat is present and specific - upper bound, one rate epoch, "
          "and the in-repo condition",
          "upper bound, not a forecast" in _adv
          and "would not emit the same tokens" in _adv
          and "one rate epoch" in _adv)

    # --- author chips (ua) ----------------------------------------------------
    # Honestly scoped: tasks record no author, so the chips must not claim the
    # task table. They scope THIS section's per-author views, and each chip
    # carries its own totals as data attributes so report.js can write the
    # summary line off the page instead of recomputing it.
    _ac = M._author_chips(_u)
    check("ua1 with more than one author the chip row renders one chip per "
          "author, each carrying its totals as data attributes",
          _ac.count('data-au=') == 2
          and 'data-au="a@x.io"' in _ac
          and 'data-tokens="1.0M"' in _ac and 'data-cost="$8.00"' in _ac
          and 'data-msgs="30"' in _ac and 'data-share="67%"' in _ac
          and 'aria-pressed="false"' in _ac)
    check("ua2 a single author renders no chip row - there is nothing to "
          "compare",
          M._author_chips(dict(_u, byAuthor={
              "a@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})) == "")
    check("ua3 the chips, the scope note and the summary-line slot reach the "
          "section, and the note says what stays project-wide",
          'id="audit-authors"' in uh and 'id="audit-au-note"' in uh
          and "stay project-wide" in uh
          and "records no author" in uh)
    check("ua4 showCost off empties the cost attribute rather than shipping a "
          "dollar the page hides",
          'data-cost=""' in M._author_chips(dict(_u, showCost=False)))
    check("ua5 By author rows carry data-author for the chips to drive; other "
          "ranked lists do not",
          'data-author="a@x.io"' in M._ranked(_u, "byAuthor", "By author",
                                            row_attr="data-author")
          and 'data-author' not in M._ranked(_u, "byPhase", "By phase"))
    check("ua6 an author name is escaped in the chip like everywhere else",
          "&lt;script&gt;" in M._author_chips(dict(_u, byAuthor={
              "<script>": {"tokens": 5, "costUSD": 0.0, "msgs": 1},
              "b@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}}))
          and "<script>" not in M._author_chips(dict(_u, byAuthor={
              "<script>": {"tokens": 5, "costUSD": 0.0, "msgs": 1},
              "b@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})))
    check("ua7 every smcell names its author so a chip can find it",
          M._usage_section(_sm).count('data-author=') >= 2)
    # ua8: the `or 1` that used to sit under this share was not a divide guard.
    # Two authors, both at zero tokens, is a whole of zero — and the old
    # expression fabricated a denominator of 1 and printed a confident `0%`,
    # indistinguishable from a real measurement of a real share. `?` says the
    # share could not be computed. Counted, not merely found: BOTH chips must
    # carry it, so an implementation that says `?` for one and `0%` for the other
    # is caught too.
    _ac0 = M._author_chips(dict(_u, byAuthor={
        "a@x.io": {"tokens": 0, "costUSD": 0.0, "msgs": 3},
        "b@x.io": {"tokens": 0, "costUSD": 0.0, "msgs": 2}}))
    check("ua8 with no tokens at all the share is `?`, never the `0%` an `or 1` "
          "denominator manufactured",
          _ac0.count('data-share="?"') == 2
          and 'data-share="0%"' not in _ac0)
    # ua9 is the other direction, and it looks vacuous on purpose: it is the case
    # that fails if the unmeasurable branch becomes unconditional. A share that
    # CAN be computed must still render exactly as it always did — 500K of 1.5M
    # is 33%, and the sub-one-percent floor still says `<1%` rather than `0%`.
    # (`<1%` reaches the attribute escaped, as every value in this file does.)
    check("ua9 a measurable share is unchanged by the adoption - and a real "
          "sub-one-percent slice still floors at `<1%`, never `0%`",
          'data-share="33%"' in _ac
          and 'data-share="&lt;1%"' in M._author_chips(dict(_u, byAuthor={
              "a@x.io": {"tokens": 1000000, "costUSD": 8.0, "msgs": 30},
              "b@x.io": {"tokens": 500, "costUSD": 0.1, "msgs": 1}})))

    # --- monthly overview (um) ------------------------------------------------
    check("um1 the monthly table renders both halves and its caption names the "
          "derivation, field by field",
          "Month by month" in uh and "completedAt" in uh
          and "reportedAt" in uh and "mergedAt" in uh
          and "linked task" in uh
          and "<td class=mono>2026-07</td>" in uh
          and "<td class=mono>2026-08</td>" in uh)
    check("um2 below two ledger-active months it renders nothing - one row "
          "would restate the tiles",
          M._monthly_block(dict(_u, monthly={
              "months": ["2026-07", "2026-08"],
              "ledger": {"2026-07": {"tokens": 0, "costUSD": 0.0, "msgs": 0},
                         "2026-08": {"tokens": 5, "costUSD": 0.1, "msgs": 1}},
              "plan": {"2026-07": {"tasksCompleted": 1, "bugsReported": 0,
                                   "bugsFixed": 0, "phasesMerged": 0},
                       "2026-08": {"tasksCompleted": 0, "bugsReported": 0,
                                   "bugsFixed": 0, "phasesMerged": 0}}})) == ""
          and M._monthly_block(dict(_u, monthly=None)) == "")
    check("um3 showCost off drops the monthly cost column and every dollar "
          "with it",
          "<th>cost</th>" not in M._monthly_block(dict(_u, showCost=False))
          and "$" not in M._monthly_block(dict(_u, showCost=False))
          and "<th>cost</th>" in M._monthly_block(_u))
    check("um4 the markdown twin carries the same months and the same "
          "derivation note",
          "### Month by month" in um
          and "| 2026-07 | 900.0K |" in um
          and "completedAt" in um and "mergedAt" in um)
    # um5: the wiring, not the fragment - load_usage computes `monthly` off the
    # real ledger + manifest through usage_ledger.monthly_activity, so the three
    # surfaces read one computation site.
    import json as _json
    import shutil as _sh
    import tempfile as _tf
    _tmp = _tf.mkdtemp(prefix="report-usage-monthly-")
    try:
        _led = os.path.join(_tmp, ".claude", "usage")
        os.makedirs(_led)
        for _month, _day in (("2026-07", "2026-07-03"), ("2026-08", "2026-08-04")):
            with open(os.path.join(_led, _month + ".jsonl"), "w",
                      encoding="utf-8") as _fh:
                _fh.write(_json.dumps({
                    "ts": _day + "T10", "model": "claude-opus-5",
                    "author": "a@x.io", "msgs": 1, "in": 5, "out": 10,
                    "cacheW5m": 0, "cacheW1h": 0, "cacheR": 0,
                    "costUSD": 0.1}) + "\n")
        _lu = M.load_usage({"meta": {}, "phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done",
             "completedAt": "2026-08-01T10:00:00Z"}]}], "bugs": []},
            os.path.join(_tmp, "m.json"), _tmp)
        check("um5 load_usage computes `monthly` from ledger + manifest through "
              "the one computation site",
              bool(_lu) and _lu.get("monthly", {}).get("months")
              == ["2026-07", "2026-08"]
              and _lu["monthly"]["plan"]["2026-08"]["tasksCompleted"] == 1)

        # ul1: one aggregate pass per dimension. `aggregate` walks every ledger
        # row, and the return dict used to ask for `day` three times and
        # phase/model/author twice each — eleven full scans for six answers, all
        # of them identical. COUNTED rather than merely observed: a `>= 1` here
        # would pass on the three-pass version, which is the whole thing being
        # pinned. The spy hangs off `_loader.load_script` because `load_usage`
        # loads its own usage_ledger with `cache=False`, so there is no module
        # object to patch from out here — and it is restored in a `finally`,
        # since a leaked patch would silently re-route every later case.
        _agg_calls = []
        _real_load = _loader.load_script

        def _counting_load(*a, **kw):
            mod = _real_load(*a, **kw)
            _real_agg = mod.aggregate

            def _spy(rows, by):
                _agg_calls.append(by)
                return _real_agg(rows, by)

            mod.aggregate = _spy
            return mod

        _loader.load_script = _counting_load
        try:
            _lu2 = M.load_usage({"meta": {}, "phases": [], "bugs": []},
                              os.path.join(_tmp, "m.json"), _tmp)
        finally:
            _loader.load_script = _real_load
        check("ul1 load_usage aggregates each dimension exactly once - the day, "
              "phase, model and author passes are hoisted, not repeated",
              bool(_lu2)
              and [_agg_calls.count(_d) for _d in ("day", "phase", "model",
                                                   "author", "agent", "session")]
              == [1, 1, 1, 1, 1, 1],
              repr(sorted(_agg_calls)))
        # ul1b, the other direction: hoisting must not have dropped a dimension.
        # A pass that stops happening at all also satisfies "not repeated", and
        # the counts above would still read 1 for the rest — this asserts the
        # OUTPUT the hoisted passes feed is still there and still distinct.
        check("ul1b the hoisted passes still produce their three distinct day "
              "series and their phase/model/author breakdowns",
              bool(_lu2)
              and sorted(_lu2["daily"]) == ["2026-07-03", "2026-08-04"]
              and sorted(_lu2["dailyCost"]) == sorted(_lu2["daily"])
              and sorted(_lu2["dailyMsgs"]) == sorted(_lu2["daily"])
              and _lu2["daily"]["2026-07-03"] == 15
              and _lu2["dailyCost"]["2026-07-03"] == 0.1
              and _lu2["dailyMsgs"]["2026-07-03"] == 1
              and list(_lu2["byModel"]) == ["claude-opus-5"]
              and list(_lu2["byAuthor"]) == ["a@x.io"]
              and _lu2["counts"]["models"] == 1
              and _lu2["counts"]["people"] == 1)
    finally:
        _sh.rmtree(_tmp, ignore_errors=True)

    check("u15 zero-token ledger renders nothing rather than an empty frame",
          M._usage_section(dict(_u, totals=dict(_u["totals"], tokens=0))) == ""
          and M._usage_md(dict(_u, totals=dict(_u["totals"], tokens=0))) == "")
    check("u16 model names are HTML-escaped",
          "&lt;script&gt;" in M._usage_section(
              dict(_u, byModel={"<script>": {"tokens": 5, "costUSD": 0.0,
                                             "msgs": 1}},
                   phaseModel={"P1": {"<script>": 5}})))


def _selftest():
    return _harness.run(_cases)


if __name__ == "__main__":
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    sys.stderr.write("usage: test__report_usage.py --selftest\n")
    raise SystemExit(2)
