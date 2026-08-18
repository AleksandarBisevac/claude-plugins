#!/usr/bin/env python3
"""
What the Usage section shows on FIRST PAINT.

Split out of `_report_usage.py` along the seam that file's own design rule
draws: a metric strip, ONE dominant chart and three ranked lists are what a
reader gets without asking, and everything else is real but folded behind a
disclosure (`_usage_detail.py`). Showing all of it at once was the old failure
mode, and the two modules are that decision made structural.

EVERY NUMBER STATES ITS BASIS, which is why the context line is here rather than
in the tiles: the rate date behind every cost figure renders beside them or the
figures do not render, and when costs are shown with no date declared it says
THAT instead of falling back to the default table's date - a fallback would
manufacture a basis rather than state one.

The trend's axis labels live OUTSIDE the SVG, as absolutely-positioned HTML at
the same percentage offsets. The columns stretch to fill the width, which is the
intent, but that scales the coordinate system non-uniformly and anything drawn
inside it stretches with it - at a 1072px render of a 720-wide viewBox the
labels came out 49% too wide.

The budget block ties spend to the PLAN rather than the calendar - the
comparison a manifest-driven pipeline can make that a date-range dashboard
cannot - and renders nothing at all when no phase declares a budget, because an
empty frame reading "0 of 0" is worse than silence.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_overview.py` - see
`plugins/audit/tests/_harness.py`.
"""
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

import _fmt  # noqa: E402  (the one token/cost/share formatter)
import _ui_theme as _theme  # noqa: E402  (the one place a machine value gets its words)

import _usage_viz as _viz  # noqa: E402  (the section's number formatting and marks)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_report_usage.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
TOP_N = _viz.TOP_N
e = _viz.e
_delta = _viz._delta
_fill_pct = _viz._fill_pct
_fmt_cost = _viz._fmt_cost
_fmt_pct = _viz._fmt_pct
_fmt_tokens = _viz._fmt_tokens
_hover_share = _viz._hover_share
_tile = _viz._tile
_tip = _viz._tip


# --- context, tiles + notices --------------------------------------------------
def _usage_context(u):
    """Scale and span of what follows, in one muted line.

    These are counts, not metrics: nobody acts on "3 people" the way they act on
    a cost. Promoting them to tiles would dilute the five that ARE actionable, so
    they orient instead — the reader learns whether they are looking at one
    person's week or a team's quarter before reading a single number."""
    c = u.get("counts") or {}
    bits = []
    for n, one, many in ((c.get("phases"), "phase", "phases"),
                         (c.get("people"), "person", "people"),
                         (c.get("models"), "model", "models"),
                         (c.get("sessions"), "session", "sessions")):
        if n:
            bits.append("%d %s" % (n, one if n == 1 else many))
    if c.get("from") and c.get("to"):
        bits.append(c["from"] if c["from"] == c["to"]
                    else "%s to %s" % (c["from"], c["to"]))
    # The date behind every cost figure below. It used to appear in HTML only via
    # _usage_notices, i.e. only once the table was more than 90 days stale — so the
    # ordinary case showed dollars with no way to see what priced them, while the
    # Markdown twin printed "rates as of" every time. Same report, two different
    # answers to "on what basis". A cost is a claim; this is its basis, and the
    # threshold for stating it is not "when it has already gone bad".
    # Withheld when showCost is off, in both renderers: with no dollars on screen
    # this dates a table nothing visible was derived from. A basis without its
    # claim is noise, which is the same rule read backwards.
    #
    # And when costs ARE shown with no date declared, say THAT rather than nothing.
    # The default table carries a `pricingAsOf`, so falling back to it would almost
    # always produce a plausible date — which is exactly why it is not done. The
    # ledger stores `costUSD` priced at write time and no rate vintage, so a report
    # whose manifest omits the declaration genuinely does not know it, and printing
    # the default's date would manufacture a basis rather than state one. Silence
    # is worse still: it renders dollars that look pinned to a table nobody named.
    # Same rule the routing advisory follows when it refuses to recommend a move
    # onto a `_default` guess.
    # Gated on there being spend to price, not merely on showCost. u21 caught the
    # first version of this emitting "rates undated" for an EMPTY usage block —
    # a basis announced for a claim that was never made, which is the same noise
    # this branch exists to prevent, produced by the fix for it.
    if u.get("showCost", True) and (u.get("totals") or {}).get("tokens"):
        bits.append("rates as of %s" % u["pricingAsOf"] if u.get("pricingAsOf")
                    else "rates undated (set usage.pricingAsOf)")
    if not bits:
        return ""
    return '<p class="uctx">%s</p>' % e(" · ".join(bits))


def _usage_tiles(u):
    """The metric strip. Five tiles, because the discipline the whole section is
    built on says 5-9 elements on first paint — not everything we can compute."""
    t = u["totals"]
    cache = u.get("cache") or {}
    unit = u.get("unit") or {}
    cov = u.get("coverage") or {}
    tiles = [_tile("tokens", _fmt_tokens(t["tokens"]),
                   "%s messages" % "{:,}".format(t["msgs"]), _delta(u, "tokens"))]
    if u.get("showCost", True):
        tiles.append(_tile("equivalent cost", _fmt_cost(t["costUSD"]),
                           "not a bill — subscription plans have no per-token charge",
                           _delta(u, "costUSD")))
    # Floored through `_fmt_pct`: a tile value stands alone, so a real 0.4%
    # cache hit rendered `0%` says the cache never hits, and "bills at 0% of
    # fresh-token rates" says the input side is free. `_tile` escapes `value`
    # but passes `sub` through raw, so the sub-lines escape their own.
    tiles.append(_tile(
        "cache hit", _fmt_pct(cache.get("hitPct", 0)),
        "input side bills at %s of fresh-token rates"
        % e(_fmt_pct(cache.get("inputCostVsFreshPct", 100)))))
    if unit.get("costPerTask") is not None:
        tiles.append(_tile("cost per task", _fmt_cost(unit["costPerTask"]),
                           "%d task(s) completed" % unit.get("completed", 0)))
    tiles.append(_tile("attributed", _fmt_pct(cov.get("attributedPct", 0)),
                       "%s down to a specific task"
                       % e(_fmt_pct(cov.get("taskLevelPct", 0)))))
    return '<div class="tiles">%s</div>' % "".join(tiles)


def _usage_notices(u):
    """Warnings that change how every other number should be read."""
    out = []
    if u.get("pricingStale"):
        out.append(
            '<p class="notice warn">Price table dated %s is more than 90 days older '
            "than the newest recorded usage — every cost figure below is derived "
            "from it. Update <code>usage.pricing</code> before trusting them.</p>"
            % e(u.get("pricingAsOf") or "?"))
    cov = u.get("coverage") or {}
    if cov.get("warn"):
        # Floored: this notice fires precisely when coverage is low, so it is the
        # one sentence most likely to land in the 0-to-1 window — and "Only 0% of
        # spend is attributed" contradicts the breakdowns it is introducing.
        out.append(
            '<p class="notice warn">Only %s of spend is attributed to a phase, so '
            "the breakdowns below describe a minority of the total. This is normal "
            "on a repo that has not run a phase since metering was installed.</p>"
            % e(_fmt_pct(cov.get("attributedPct", 0))))
    return "".join(out)


# --- the one dominant chart, and the budget ------------------------------------
def _usage_trend(u):
    """The one dominant chart: total tokens per day.

    A single series, so no legend box — the heading already says what is plotted.
    Columns cap at 24px, 4px rounded cap, square at the baseline; two hairline
    gridlines carry the scale so no value needs a label.

    The columns stretch to fill the width (`preserveAspectRatio="none"`), which is
    the intent — but that scales the coordinate system non-uniformly, and anything
    drawn inside it scales with it. At a 1072px-wide render of a 720-wide viewBox
    the axis labels came out 49% too wide. So the LABELS live outside the SVG, as
    absolutely-positioned HTML at the same percentage offsets, where nothing can
    stretch them. The report is static and must survive JavaScript being off, so
    measuring the container the way the panel does is not available here."""
    daily = u.get("daily") or {}
    days = sorted(daily)
    if len(days) < 2:
        return ""
    w, h, pad_b, pad_t = 720.0, 210.0, 22.0, 14.0
    peak = max(daily[d] for d in days)
    if not peak:
        # No `or 1`. Every column is scaled against the peak and the y axis is
        # LABELLED with it, so a fabricated denominator of 1 drew a flat 1px
        # baseline under an axis reading "1" and an aria-label claiming a peak of
        # one token — a measurement of a ledger that recorded none. There is no
        # shape to plot, so nothing is plotted, the same answer this section
        # already gives a zero-token ledger rather than an empty frame.
        return ""
    slot = w / len(days)
    bw = min(24.0, max(2.0, slot - 3.0))
    plot = h - pad_b - pad_t
    bars, labels = [], []
    every = max(1, len(days) // 10)
    for i, d in enumerate(days):
        n = daily[d]
        bh = max(1.0, plot * n / peak)
        x = i * slot + (slot - bw) / 2.0
        y = pad_t + plot - bh
        r = min(4.0, bw / 2.0, bh)
        tip = "<title>%s</title>" % _tip(
            d, [("tokens", _fmt_tokens(n, 2)),
                ("cost", _fmt_cost((u.get("dailyCost") or {}).get(d, 0.0))
                 if u.get("showCost", True) else None)])
        # data-d is the filter hook (C1): the global date range dims the columns
        # outside it CLIENT-side, so the mark has to say which day it draws.
        if bw < 6.0:
            # Below ~6px a two-corner rounded cap is a 1px curve nobody can see,
            # and the nine-point path costs three times a plain rect. Long spans
            # are exactly where that difference adds up.
            bars.append('<rect class="col" data-d="%s" x="%.1f" y="%.1f" '
                        'width="%.1f" height="%.1f" rx="%.1f">%s</rect>'
                        % (e(d), x, y, bw, bh, r, tip))
        else:
            bars.append(
                '<path class="col" data-d="%s" d="M%.1f %.1fL%.1f %.1fQ%.1f '
                '%.1f %.1f %.1fL%.1f %.1fQ%.1f %.1f %.1f %.1fL%.1f %.1fZ">%s</path>'
                % (e(d), x, y + bh, x, y + r, x, y, x + r, y,
                   x + bw - r, y, x + bw, y, x + bw, y + r, x + bw, y + bh, tip))
        if i % every == 0 or i == len(days) - 1:
            # Percent of the plot width, so the tick tracks its column at any
            # rendered size. The first and last are anchored to their own edge so
            # neither can hang outside the chart.
            pos = 100.0 * (x + bw / 2.0) / w
            side = ("left:0;transform:none" if i == 0
                    else "right:0;left:auto;transform:none"
                    if i == len(days) - 1 else "left:%.3f%%" % pos)
            labels.append('<span class="xt" data-d="%s" style="%s">%s</span>'
                          % (e(d), side, e(d[5:])))
    # vector-effect keeps the hairline exactly 1px however the x axis is stretched.
    grid = "".join(
        '<line class="grid" x1="0" y1="%.1f" x2="%d" y2="%.1f" '
        'vector-effect="non-scaling-stroke"></line>'
        % (pad_t + plot * f, int(w), pad_t + plot * f)
        for f in (0.0, 0.5))
    yaxis = "".join(
        '<span class="yt" style="top:%.3f%%">%s</span>'
        % (100.0 * (pad_t + plot * f - 11) / h,
           e(_fmt_tokens(int(peak * (1 - f)))))
        for f in (0.0, 0.5))
    return ('<div class="colswrap">'
            '<svg class="cols" viewBox="0 0 %d %d" preserveAspectRatio="none" '
            'role="img" aria-label="Tokens per day, peak %s">%s%s</svg>'
            '%s<div class="xts">%s</div></div>'
            % (int(w), int(h), _fmt_tokens(peak), grid, "".join(bars),
               yaxis, "".join(labels)))


def _budget_block(u):
    """Spend against each phase's declared budget.

    Ties spend to the PLAN rather than the calendar — the comparison a
    manifest-driven pipeline can make that a date-range dashboard cannot.

    Renders NOTHING when no phase declares a budget, which is the common case: an
    empty frame reading "0 of 0" would be worse than silence. When a budget does
    exist it sits on first paint rather than behind the disclosure, because "P2 is
    at 130%" is the kind of fact that should not need looking for.

    Phases with no budget are counted and named as a footnote, never rendered as a
    0% bar — an unbudgeted phase is not a phase at zero."""
    pb = u.get("budgets") or {}
    rows_in = [p for p in (pb.get("phases") or []) if p.get("budget")]
    if not rows_in:
        return ""
    rows = []
    for p in sorted(rows_in, key=lambda x: -x["pct"]):
        pct = p["pct"]
        # The fill caps at 100% because a bar cannot draw past its track; the
        # number beside it does not, so the overrun stays visible.
        #
        # And the `%.0f%%` label is NOT floored the way the tooltip share is:
        # `$0.03 of $40.00` prints on this same row, so a reader has the whole
        # divide in front of them and `0%` cannot mislead — while `<1%` beside a
        # track drawn at 0.1% would only disagree with the geometry. The
        # bar-label case the module docstring names, and `_fill_pct`'s reason.
        fill = min(100.0, pct)
        rows.append(
            '<div class="bud%s"><span class="nm"><span class="mono">%s</span> %s</span>'
            '<span class="track"><i style="width:%.1f%%"></i></span>'
            '<span class="pct">%.0f%%</span>'
            '<span class="amt">%s of %s%s</span></div>'
            % (" over" if p["over"] else "", e(p["id"]), e(p["title"]), fill, pct,
               e(_fmt_cost(p["spent"])), e(_fmt_cost(p["budget"])),
               " &middot; over" if p["over"] else ""))
    nobudget = len(pb.get("phases") or []) - len(rows_in)
    foot = ('<p class="muted small">%d phase(s) have no <code>budgetUSD</code> set '
            "and are not shown here — they are not phases at zero.</p>"
            % nobudget) if nobudget else ""
    total = ""
    if pb.get("totalBudget"):
        total = ('<div class="bud total"><span class="nm">All budgeted phases</span>'
                 '<span class="track"></span><span class="pct"></span>'
                 '<span class="amt">%s of %s</span></div>'
                 % (e(_fmt_cost(pb["totalSpent"])), e(_fmt_cost(pb["totalBudget"]))))
    return ('<h3 class="sub">Budget</h3><div class="buds">%s%s</div>%s'
            % ("".join(rows), total, foot))


# --- the author chips and the three ranked lists -------------------------------
def _author_chips(u):
    """The author chip row — rendered only when the ledger records more than
    one author, because a set of one has nothing to compare.

    Honestly scoped: tasks record no author, so these chips must NOT claim the
    task table. They scope this Usage section's per-author views (the By author
    rows and the small-multiples cells), and the note beside them says exactly
    that. Each chip carries its own totals as pre-formatted data attributes so
    report.js writes the summary line off the page rather than through a second
    implementation of the arithmetic."""
    data = u.get("byAuthor") or {}
    if len(data) < 2:
        return ""
    # No `or 1`. That is not a divide guard, it is a fabricated denominator: with
    # every author at zero tokens it turned an unmeasurable share into a confident
    # `0%`, and any non-zero part over a zero whole into a multiple of 100%.
    # `fmt_share` is the one share rule in the tree and it says `?` for "there is
    # no whole to divide by" — the same `<1%` floor and the same rounding for
    # every share that CAN be computed, so nothing measurable renders differently.
    total = sum(v["tokens"] for v in data.values())
    show_cost = u.get("showCost", True)
    chips = []
    for a, v in sorted(data.items(), key=lambda kv: -kv[1]["tokens"]):
        share_txt = _fmt.fmt_share(v["tokens"], total)
        chips.append(
            '<button type="button" class="fchip" data-au="%s" data-tokens="%s" '
            'data-cost="%s" data-msgs="%s" data-share="%s" '
            'aria-pressed="false">%s</button>'
            % (e(a), e(_fmt_tokens(v["tokens"])),
               e(_fmt_cost(v["costUSD"])) if show_cost else "",
               "{:,}".format(v["msgs"]), e(share_txt), e(a)))
    return ('<div class="auchips" id="audit-authors">%s</div>'
            '<p class="muted small">Author chips scope the per-author views of '
            "this section (the By author list, and the per-author panels in "
            "Detail) &mdash; the tiles and trend above stay project-wide, and "
            "the task table records no author to filter by. The panel has the "
            "full drill-down.</p>"
            '<p class="muted small aunote" id="audit-au-note" hidden></p>'
            % "".join(chips))


def _ranked(u, key, title, slots=None, models=None, row_attr=None):
    """One ranked bar list. Top 8 then a folded `other` row — past 8 entities a
    categorical palette cannot keep adjacent pairs distinguishable, so folding is a
    correctness bound rather than a style choice.

    `row_attr` stamps each REAL entity's key on its row (the folded `other` row
    never gets one) — the hook the author chips drive."""
    data = u.get(key) or {}
    if not data:
        return ""
    items = sorted(data.items(), key=lambda kv: -kv[1]["tokens"])
    head, tail = items[:TOP_N], items[TOP_N:]
    if tail:
        head.append(("other (%d)" % len(tail),
                     {"tokens": sum(v["tokens"] for _, v in tail),
                      "costUSD": sum(v["costUSD"] for _, v in tail),
                      "msgs": sum(v["msgs"] for _, v in tail)}))
    # No `or 1` on either denominator. It is not a divide guard — it fabricates a
    # whole of one token and every number measured against it becomes a confident
    # claim about a ledger that recorded nothing. The guard is `_fmt.share_pct`,
    # once per divide, and the two answers below differ because a bar and a share
    # string are read differently: `_fill_pct` (empty track, the count beside it)
    # and `_hover_share` (`?`, because it travels alone).
    peak = max(v["tokens"] for _, v in head)
    grand = sum(v["tokens"] for _, v in items)
    rows = []
    for k, v in head:
        label = k
        if key == "byPhase":
            # uc (F-P-2): the empty bucket wears the shared word, not its key.
            label = "%s %s" % (k, u["phaseTitles"].get(k, "")) if k != "--" \
                else _theme.UNCATEGORIZED
        colour = ("var(--viz-%d)" % slots[k]) if (slots and k in slots) \
            else "var(--bar-neutral)"
        amt = _fmt_tokens(v["tokens"])
        if u.get("showCost", True):
            amt += " &middot; %s" % e(_fmt_cost(v["costUSD"]))
        attr_bit = (' %s="%s"' % (row_attr, e(k))) \
            if (row_attr and k in data) else ""
        # The bar is a share the eye reads against its neighbours; the hover adds
        # the exact count and the share of the whole, which the bar cannot show
        # because it is scaled to the largest row, not to the total.
        rows.append(
            '<div class="rank"%s title="%s"><span class="nm">%s</span>'
            '<span class="track"><i style="width:%.1f%%;background:%s"></i></span>'
            '<span class="amt">%s</span></div>'
            % (attr_bit,
               _tip(label.strip(), [
                ("tokens", _fmt_tokens(v["tokens"], 2)),
                ("share", _hover_share(v["tokens"], grand)),
                ("cost", _fmt_cost(v["costUSD"])
                 if u.get("showCost", True) else None),
                ("messages", "{:,}".format(v["msgs"]))]),
               e(label.strip()),
               # Floored: a row at 0.08% of the peak rounds to 0.0% and paints an
               # empty track, which reads as "no data" rather than "a little".
               # The floor reads the row's OWN tokens, so a peak of zero (every
               # row at zero) still floors nothing and draws nothing.
               max(0.8 if v["tokens"] else 0.0, _fill_pct(v["tokens"], peak)),
               colour, amt))
    return '<div class="rankgrp"><h3 class="sub">%s</h3>%s</div>' % (
        e(title), "".join(rows))

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exiting silently: `--selftest` is what every other
        # file here accepts, so nothing would tell a reader whether this one ran
        # nothing or has nothing. It deliberately does NOT print the
        # `N/M cases passed` contract - that literal is how
        # `_output.selftest_coverage()` tells an inline suite from a migrated one.
        print("_usage_overview.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_overview.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
