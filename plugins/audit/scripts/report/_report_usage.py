#!/usr/bin/env python3
"""
The audit report's Usage section: the order the block is assembled in.

Moved out of render-report.py (P13.2) — the largest single block in that file —
and then cut into five, because at 1,477 lines it was five subjects in one file.
The cut follows the section's own design rule rather than a tidy grouping:

  `_usage_viz`       L3  how a number is formatted and a bar is drawn - the
                         primitives every fragment shares
  `_usage_load`      L3  the ledger read, the only I/O the section does
  `_usage_overview`  L4  what shows on FIRST PAINT: the metric strip, the one
                         dominant chart, the three ranked lists, the budget
  `_usage_detail`    L4  everything folded behind the `Detail` disclosure
  `_usage_markdown`  L4  the Markdown twin

What is left here is the ORDER — `_usage_section(u)` — plus `_usage_payload`,
the one `<script>` blob both halves read. Restraint is the whole shape of that
order: a metric strip, ONE dominant chart and three ranked lists on first paint;
everything else real but folded. Showing all of it at once was the old failure
mode, and the overview/detail split is that decision made structural rather than
left to a reviewer's memory.

Two rules the whole section is built on, stated here because they cross all five
files:

  * Every number states its basis. A cost is a claim: the rate date, the
    attribution coverage, the sample a band calibrated from and the caveat on
    a routing recommendation all render beside the figure, or the figure does
    not render.
  * No `or 1`, ever. That is not a divide guard — it fabricates a denominator
    and turns an unmeasurable share into a confident one. `_fmt.share_pct` owns
    every divide, and `_usage_viz` holds the two answers to "there is no whole":
    `_fill_pct` (a bar's) and `_hover_share` (a share string's).

One rule decides whether a rendered share carries `fmt_share`'s `<1%` floor, and
it is about what sits BESIDE the number:

  * A share that stands ALONE as a claim — a tooltip line, a stat tile, a
    sentence — floors. `0%` for a slice that exists reads as "none", which is
    the same lie `$0.00` tells about real spend, and `fmt_cost` has refused to
    tell that one since P10.6.
  * A share printed immediately NEXT TO the two numbers it was divided from —
    a bar's width beside its own token count, a budget label beside `$spent of
    $budget`, a saving beside both dollar figures — does not. The basis is
    already on screen, and a floor would only disagree with the geometry drawn
    beside it.
  * A percent CHANGE (`_delta`) is not a share at all: `+0%` says "essentially
    unchanged", which is true, where `<1%` would claim a slice exists.

THE NAMES ALL STAY REACHABLE FROM HERE. render-report.py keeps a thin
module-level alias for `load_usage`, `_report_page` for `_usage_section`, and
`tests/test__report_usage.py` reads 27 names off this module; every one of them
is re-exported below as the SAME object, never a copy. `_report_md.py` is the
one consumer that now reaches past this file — it imports `_usage_markdown`
directly, which is what keeps it strictly below the Usage section's assembly
rather than beside it.

This module moved from layer 4 to layer 5, and that is the whole structural cost
of the split: `_usage_overview`/`_usage_detail`/`_usage_markdown` sit at layer 4
above `_usage_viz`, so their only consumer has to sit above them. `_report_page`
(L6) and render-report (L7) are still strictly above; `_report_md` stays at L5
beside this file, with no edge either way.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__report_usage.py` - see
`plugins/audit/tests/_harness.py`.
"""
import json
import os
import sys

# The path bootstrap: byte-identical in every `.py` under `scripts/`, counted by
# `_output.path_preamble_violations()`. It walks UP to the directory holding
# `_output.py` instead of counting `dirname()` calls, so it does not encode how deep
# this file sits and keeps working if the file is moved into a subdirectory.
# `install_path()` then adds that directory AND every subdirectory of it holding a
# `.py`: the folders are LABELS, NOT NAMESPACES, and every sibling below is still
# reached by a bare basename.
_anchor_dir = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_anchor_dir, "_output.py")):
    _anchor_up = os.path.dirname(_anchor_dir)
    if _anchor_up == _anchor_dir:
        raise ImportError("audit plugin: walked to the filesystem root from %s "
                          "without finding _output.py - the scripts/ anchor is "
                          "gone and no sibling can be imported" % (__file__,))
    _anchor_dir = _anchor_up
if _anchor_dir not in sys.path:
    sys.path.insert(0, _anchor_dir)

import _output  # noqa: E402  (the anchor: install_path, py_files, safe_stdio)

_output.install_path()

import _usage_viz as _viz  # noqa: E402  (number formatting, shares, marks)
import _usage_load  # noqa: E402  (the ledger read - the section's only I/O)
import _usage_overview as _over  # noqa: E402  (what shows on first paint)
import _usage_detail as _detail  # noqa: E402  (what the Detail disclosure folds)
import _usage_markdown as _md_view  # noqa: E402  (the Markdown twin)

# --- the re-exported surface ------------------------------------------------------
# ALIASES, NOT COPIES. Each name is the SAME object the module beside it defines.
# They exist because render-report, `_report_page` and this section's own suite
# already spell them off THIS module, and a split that made each of them learn
# which of five files a fragment moved to would charge the callers for a change
# they did not ask for. A case pins the whole set with `is`.
load_usage = _usage_load.load_usage
_iso_day = _usage_load._iso_day
_pricing_stale = _usage_load._pricing_stale
_hourly = _usage_load._hourly

e = _viz.e
VIZ_SLOTS = _viz.VIZ_SLOTS
TOP_N = _viz.TOP_N
SPARK_COLS = _viz.SPARK_COLS
_fmt_tokens = _viz._fmt_tokens
_fmt_cost = _viz._fmt_cost
_fmt_pct = _viz._fmt_pct
_model_slots = _viz._model_slots
_delta = _viz._delta
_tip = _viz._tip
_tile = _viz._tile
_fill_pct = _viz._fill_pct
_hover_share = _viz._hover_share
_bin_days = _viz._bin_days
_spark = _viz._spark

_usage_context = _over._usage_context
_usage_tiles = _over._usage_tiles
_usage_notices = _over._usage_notices
_usage_trend = _over._usage_trend
_budget_block = _over._budget_block
_author_chips = _over._author_chips
_ranked = _over._ranked

_small_multiples = _detail._small_multiples
_monthly_block = _detail._monthly_block
_routing_table = _detail._routing_table
_routing_advice_block = _detail._routing_advice_block
_economics_block = _detail._economics_block
_band_note = _detail._band_note
_phase_stacks = _detail._phase_stacks
_usage_heatmap = _detail._usage_heatmap

_md = _md_view._md
_usage_md = _md_view._usage_md


# --- the data layer both halves read ----------------------------------------------
def _usage_payload(u):
    """The per-day data layer (C1/C3), embedded as one JSON blob.

    `window.AUDIT_USAGE` = {"min", "max", "days": {date: [tokens, costUSD,
    msgs, [24 hourly token counts]]}} — everything report.js needs to scope
    the time-based views to a date range and to navigate the heatmap by
    calendar period, in a file that has no server to ask. Same embedding
    precedent as `window.AUDIT_MD_B64` in render-report.

    It stays here rather than in either half because BOTH read it: the range
    scoping is the overview's, the calendar navigation is the heatmap's, and a
    payload owned by one of them would be a data layer the other reaches
    sideways for.

    Deterministic on purpose (sorted keys, compact separators, costs rounded
    to 6dp): the committed example report is byte-compared by CI. The payload
    is data about dates and integers, so it cannot contain "</script>" or an
    external URL — render-report's x5 zero-fetch pin scans it like everything
    else."""
    daily = u.get("daily") or {}
    if not daily:
        return ""
    show_cost = bool(u.get("showCost", True))
    cost = u.get("dailyCost") or {}
    msgs = u.get("dailyMsgs") or {}
    hourly = u.get("hourly") or {}
    days = {}
    for d in sorted(daily):
        # showCost off zeroes the cost column: a page that shows no dollars
        # must not smuggle them in through its own data layer.
        days[d] = [int(daily.get(d) or 0),
                   round(float(cost.get(d) or 0.0), 6) if show_cost else 0,
                   int(msgs.get(d) or 0),
                   [int(n) for n in (hourly.get(d) or [0] * 24)]]
    blob = json.dumps({"min": min(daily), "max": max(daily),
                       "showCost": show_cost, "days": days},
                      sort_keys=True, separators=(",", ":"))
    return "<script>window.AUDIT_USAGE=%s;</script>" % blob


# --- section assembly ---------------------------------------------------------
def _usage_section(u):
    """The Usage block.

    Deliberately shaped by restraint: a metric strip, ONE dominant chart and three
    ranked lists on first paint; everything else is real but folded behind a
    disclosure. Showing all of it at once was the old failure mode."""
    if not u or not u.get("totals", {}).get("tokens"):
        return ""
    slots = _model_slots(u["byModel"].keys())
    models = sorted(u["byModel"], key=lambda m: slots[m])

    out = ['<h2 id="usage">Usage</h2>']
    out.append(_usage_notices(u))
    out.append(_usage_context(u))
    out.append(_usage_tiles(u))
    # The active date range, said in one line (C1). Filled by report.js when a
    # range is on: it names the span, gives that span's own totals, and says
    # which views are scoped — the tiles above deliberately stay all-time,
    # because sessions and cache economics cannot be recomputed from per-day
    # data and a partly-true tile is worse than a labelled all-time one. This
    # line is also the print story: the scoped charts print as scoped, and the
    # sheet needs the range NAMED on it rather than implied (the sticky bar
    # carrying the pickers never reaches paper).
    out.append('<p class="uctx urange" id="audit-urange" hidden></p>')

    win = u.get("compareWindow") or {}
    out.append('<h3 class="sub">Tokens per day</h3>')
    if u.get("compare") and (u["compare"].get("prior") is not None):
        out.append('<p class="muted small" style="margin:0 0 var(--sp-1)">'
                   "Deltas above compare %s to %s with the 30 days before it.</p>"
                   % (e(win.get("since") or "?"), e(win.get("until") or "?")))
    out.append(_usage_trend(u))
    # D2: the daily rows and the trend leave as files — CSV of the per-day
    # data and a PNG redrawn from it, both generated client-side from
    # window.AUDIT_USAGE (the same payload the range scoping reads), so both
    # are gated on the daily series existing at all.
    if u.get("daily"):
        out.append(
            '<div class="secx usx">'
            '<button type="button" class="btn segbtn" data-csv="usage" '
            'title="Download the per-day usage rows (date, tokens, cost, '
            'msgs) as CSV — the whole recorded span">CSV</button>'
            '<button type="button" class="btn segbtn" data-png="trend" '
            'title="Download this chart as a PNG image, redrawn from the '
            'data">PNG</button></div>')

    out.append(_author_chips(u))
    out.append('<div class="ranks">%s%s%s</div>' % (
        _ranked(u, "byPhase", "By phase"),
        _ranked(u, "byModel", "By model", slots, models),
        _ranked(u, "byAuthor", "By author", row_attr="data-author")))
    out.append(_budget_block(u))

    detail = "".join([
        _monthly_block(u),
        _small_multiples(u, slots),
        _phase_stacks(u, slots, models),
        _economics_block(u),
        _routing_table(u),
        _usage_heatmap(u),
    ])
    if detail:
        out.append("<details class=\"more\"><summary>Detail — monthly "
                   "activity, per-author split, phase composition, unit "
                   "economics, model routing, hourly pattern</summary>"
                   "%s</details>" % detail)
    out.append(_usage_payload(u))
    return "".join(out)


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_report_usage.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_usage.py - run that file instead.")
    raise SystemExit(0)
