#!/usr/bin/env python3
"""
The audit report's Usage section: the ledger load and everything that plots it.

Moved out of render-report.py (P13.2) — the largest single block in that file.
Two public entry points, one per renderer: `_usage_section(u)` builds the HTML
block and `_usage_md(u)` builds its Markdown twin, off the dict `load_usage()`
reads from the usage ledger. Everything between them (tiles, trend, ranked
lists, budgets, small multiples, phase stacks, economics, routing, heatmap) is
a private fragment builder over already-computed numbers.

Two rules the whole section is built on, and the reason it is worth a module:

  * Restraint on first paint — a metric strip, ONE dominant chart and three
    ranked lists; everything else is real but folded behind a disclosure.
  * Every number states its basis. A cost is a claim: the rate date, the
    attribution coverage, the sample a band calibrated from and the caveat on
    a routing recommendation all render beside the figure, or the figure does
    not render.

Formatting is not decided here: `_fmt_tokens` / `_fmt_cost` delegate to _fmt
(P10.6), the one token/cost formatter shared with the panel and /audit:usage.

render-report.py keeps thin module-level aliases (`load_usage`,
`_usage_section`, `_usage_md`, `_fmt_tokens`, ...) so render_html / render_md
and its own selftest keep referring to these names unchanged.

Imports go one way only: _report_html -> _report_usage -> render-report. This
module may use _loader (to load usage_ledger.py), _fmt, _ui_theme and
_report_html; it must never import render-report.
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _loader        # noqa: E402  (the one way scripts/ loads a sibling script)
import _fmt           # noqa: E402  (the one token/cost formatter)
import _report_html   # noqa: E402  (escaping and the shared fragment helpers)

e = _report_html.e


# --- loading ------------------------------------------------------------------
def _iso_day(epoch):
    g = time.gmtime(epoch)
    return "%04d-%02d-%02dT00:00:00Z" % (g.tm_year, g.tm_mon, g.tm_mday)


def _pricing_stale(as_of, until, max_days=90):
    """True when the price table predates the newest ledger day by more than
    `max_days`. A silently stale rate is worse than no rate — every cost figure in
    the report is derived from it, so the report has to say when it cannot be
    trusted. Compared against the LEDGER's last day, not the wall clock, so a
    committed example does not rot into a warning on its own."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
        t_as_of = ul.parse_ts((as_of or "") + "T00:00:00Z")
        t_until = ul.parse_ts((until or "") + "T00:00:00Z")
        if t_as_of is None or t_until is None:
            return False
        return (t_until - t_as_of) > max_days * 86400
    except Exception:
        return False


def load_usage(manifest, manifest_path, project_dir=None):
    """Everything the Usage section plots, read straight from the ledger.

    Deliberately NOT taken from `audit-status.rollup`: the rollup is printed into a
    model's context by /audit:status, so the bulky series (day x hour heatmap,
    daily trend, phase x model cross-tab) are computed here in Python instead of
    being carried through a JSON payload nobody reads. Returns None when there is
    no ledger — the section then renders as nothing at all."""
    try:
        ul = _loader.load_script("usage_ledger.py", modname="usage_ledger",
                                  cache=False)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    if not isinstance(meta_usage, dict):
        meta_usage = {}
    rel = meta_usage.get("ledgerDir") or os.path.join(".claude", "usage")
    ledger_dir = ul.find_ledger_dir(
        manifest_path, rel,
        project_dir or os.environ.get("CLAUDE_PROJECT_DIR"))
    if not ledger_dir:
        return None

    try:
        rows = ul.read_ledger(ledger_dir)
        if not rows:
            return None

        def slim(by):
            return {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                        "msgs": v["msgs"]}
                    for k, v in ul.aggregate(rows, by).items()}

        phase_model = {}
        for r in rows:
            pid = r.get("phaseId") or "--"
            model = r.get("model") or "unknown"
            n = sum(int(r.get(k) or 0) for k in ul.TOKEN_KEYS)
            phase_model.setdefault(pid, {})
            phase_model[pid][model] = phase_model[pid].get(model, 0) + n

        titles = {}
        for ph in ((manifest or {}).get("phases") or []):
            if isinstance(ph, dict) and ph.get("id"):
                titles[ph["id"]] = ph.get("title") or ""

        # Comparison window is anchored to the LEDGER's own last day, not the wall
        # clock, so a committed example report is byte-stable across re-renders.
        days = sorted({ul.bucket_date(r.get("ts")) for r in rows} - {""})
        until = days[-1] if days else None
        since = None
        if until:
            t = ul.parse_ts(until + "T00:00:00Z")
            since = ul.hour_bucket(_iso_day(t - 29 * 86400))[:10] if t else None

        return {
            "totals": ul.totals(rows),
            "byPhase": slim("phase"),
            "byModel": slim("model"),
            "byAuthor": slim("author"),
            "byAgent": slim("agent"),
            "phaseModel": phase_model,
            "phaseTitles": titles,
            "taskTitles": {t["id"]: t.get("title") or ""
                           for ph in ((manifest or {}).get("phases") or [])
                           if isinstance(ph, dict)
                           for t in (ph.get("tasks") or [])
                           if isinstance(t, dict) and t.get("id")},
            "daily": {k: v["tokens"] for k, v in ul.aggregate(rows, "day").items()
                      if k != "unknown"},
            "dailyCost": {k: v["costUSD"] for k, v in ul.aggregate(rows, "day").items()
                          if k != "unknown"},
            "heatmap": ul.heatmap(rows),
            # the analytics layer — every one of these carries its own honesty guard
            "compare": ul.compare(rows, since, until) if since else None,
            "compareWindow": {"since": since, "until": until},
            "cache": ul.cache_profile(rows),
            "unit": ul.unit_economics(manifest, rows),
            "bands": ul.cost_bands(manifest, rows, meta_usage),
            "budgets": ul.phase_budgets(manifest, rows),
            "retry": ul.retry_cost(manifest, rows),
            "routing": ul.routing(manifest, rows, meta_usage.get("pricing")),
            "coverage": ul.coverage(rows),
            "monthly": ul.monthly_activity(manifest, rows),
            "seriesAuthorModel": {
                a: ul.series([r for r in rows if (r.get("author") or "unknown") == a],
                             "model")
                for a in sorted({r.get("author") or "unknown" for r in rows})},
            "showCost": bool(meta_usage.get("showCost", True)),
            "pricingAsOf": meta_usage.get("pricingAsOf"),
            "pricingStale": _pricing_stale(meta_usage.get("pricingAsOf"), until),
            # Orientation, not metrics. These answer "how big is the thing I am
            # looking at" — a question the tiles cannot answer, and one that would
            # cost five more tiles to answer badly.
            "counts": {
                "phases": len([k for k in ul.aggregate(rows, "phase") if k != "--"]),
                "people": len(ul.aggregate(rows, "author")),
                "models": len(ul.aggregate(rows, "model")),
                "sessions": len([k for k in ul.aggregate(rows, "session")
                                 if k != "unknown"]),
                "days": len(days),
                "from": days[0] if days else None,
                "to": until,
            },
        }
    except Exception:
        return None


# --- viz constants + formatting helpers ---------------------------------------
VIZ_SLOTS = 8
# One folding rule for every categorical list in the section. Past this many
# entities a reader stops comparing and starts scrolling, and the palette runs out
# of distinguishable hues — so the tail is folded and SAID, never silently cut.
TOP_N = 8


def _fmt_tokens(n, dp=1):
    """Token counts are a MAGNITUDE and are always compact — `3.2M`, never
    `3,230,000`. Eight digits are unreadable at a glance and unreadable in a
    tooltip; what a reader compares is the order of magnitude and one or two
    figures past it.

    `dp=2` is for hover: pointing at a bar buys you `3.23M` instead of `3.2M` —
    more precision than the label, without dumping the raw integer.

    Countables (messages, sessions, tasks) are NOT magnitudes and keep their
    thousand separators: `47,625` messages is a number you can act on, `47.6K`
    throws away the thing that made it a count.

    Delegates to _fmt.py (the one token/cost formatter); this wrapper exists
    only to keep this file's own default (`dp=1`) as its own default rather
    than relying on _fmt's `dp=None` sentinel."""
    return _fmt.fmt_tokens(n, dp=dp)


def _fmt_cost(x):
    return _fmt.fmt_cost(x)


def _model_slots(models):
    """model -> categorical slot, assigned by NAME (sorted), never by rank.

    Colour follows the entity: filtering or re-sorting the chart must not repaint
    the survivors. Past 8 models the tail folds into one 'other' slot rather than
    generating a 9th hue nothing can distinguish."""
    ordered = sorted(models)
    slots = {}
    for i, m in enumerate(ordered):
        slots[m] = (i + 1) if i < VIZ_SLOTS else VIZ_SLOTS
    return slots


def _delta(u, key):
    """`+12%` / `-4%` vs the previous period, or '' when there is nothing to compare
    against. A first-run report must not invent a trend."""
    cmp_ = u.get("compare") or {}
    d = (cmp_.get("deltas") or {}).get(key)
    if d is None:
        return ""
    sign = "up" if d >= 0 else "down"
    return ('<span class="dl %s">%s%.0f%%</span>' % (sign, "+" if d >= 0 else "", d))


def _tip(header, rows):
    """Hover text, written ONCE and used twice: as the `title` the browser shows
    natively when JavaScript is off, and as the payload the styled tooltip
    re-renders. One encoding means the two can never drift apart.

    Newline separates lines, tab separates a row's label from its value — both
    survive a native tooltip, so the fallback is readable rather than merely
    present."""
    body = "\n".join("%s\t%s" % (a, b) for a, b in rows if b is not None)
    return e(("%s\n%s" % (header, body)) if body else header)


# --- tiles + notices ----------------------------------------------------------
def _tile(label, value, sub, delta=""):
    return ('<div class="tile"><div class="k">%s</div>'
            '<div class="v">%s%s</div><div class="s">%s</div></div>'
            % (e(label), e(value), delta, sub))


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
    tiles.append(_tile(
        "cache hit", "%.0f%%" % cache.get("hitPct", 0),
        "input side bills at %.0f%% of fresh-token rates"
        % cache.get("inputCostVsFreshPct", 100)))
    if unit.get("costPerTask") is not None:
        tiles.append(_tile("cost per task", _fmt_cost(unit["costPerTask"]),
                           "%d task(s) completed" % unit.get("completed", 0)))
    tiles.append(_tile("attributed", "%.0f%%" % cov.get("attributedPct", 0),
                       "%.0f%% down to a specific task" % cov.get("taskLevelPct", 0)))
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
        out.append(
            '<p class="notice warn">Only %.0f%% of spend is attributed to a phase, so '
            "the breakdowns below describe a minority of the total. This is normal "
            "on a repo that has not run a phase since metering was installed.</p>"
            % cov.get("attributedPct", 0))
    return "".join(out)


# --- trend + budget -----------------------------------------------------------
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
    peak = max(daily[d] for d in days) or 1
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
        if bw < 6.0:
            # Below ~6px a two-corner rounded cap is a 1px curve nobody can see,
            # and the nine-point path costs three times a plain rect. Long spans
            # are exactly where that difference adds up.
            bars.append('<rect class="col" x="%.1f" y="%.1f" width="%.1f" '
                        'height="%.1f" rx="%.1f">%s</rect>'
                        % (x, y, bw, bh, r, tip))
        else:
            bars.append(
                '<path class="col" d="M%.1f %.1fL%.1f %.1fQ%.1f %.1f %.1f %.1f'
                'L%.1f %.1fQ%.1f %.1f %.1f %.1fL%.1f %.1fZ">%s</path>'
                % (x, y + bh, x, y + r, x, y, x + r, y,
                   x + bw - r, y, x + bw, y, x + bw, y + r, x + bw, y + bh, tip))
        if i % every == 0 or i == len(days) - 1:
            # Percent of the plot width, so the tick tracks its column at any
            # rendered size. The first and last are anchored to their own edge so
            # neither can hang outside the chart.
            pos = 100.0 * (x + bw / 2.0) / w
            side = ("left:0;transform:none" if i == 0
                    else "right:0;left:auto;transform:none"
                    if i == len(days) - 1 else "left:%.3f%%" % pos)
            labels.append('<span class="xt" style="%s">%s</span>'
                          % (side, e(d[5:])))
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


# --- rankings + sparklines + tables -------------------------------------------
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
    total = sum(v["tokens"] for v in data.values()) or 1
    show_cost = u.get("showCost", True)
    chips = []
    for a, v in sorted(data.items(), key=lambda kv: -kv[1]["tokens"]):
        share = 100.0 * v["tokens"] / total
        share_txt = "<1%" if 0 < share < 1 else "%.0f%%" % share
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
    peak = max(v["tokens"] for _, v in head) or 1
    grand = sum(v["tokens"] for _, v in items) or 1
    rows = []
    for k, v in head:
        label = k
        if key == "byPhase":
            label = "%s %s" % (k, u["phaseTitles"].get(k, "")) if k != "--" \
                else "-- unattributed"
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
                ("share", "%.0f%%" % (100.0 * v["tokens"] / grand)),
                ("cost", _fmt_cost(v["costUSD"])
                 if u.get("showCost", True) else None),
                ("messages", "{:,}".format(v["msgs"]))]),
               e(label.strip()),
               # Floored: a row at 0.08% of the peak rounds to 0.0% and paints an
               # empty track, which reads as "no data" rather than "a little".
               max(0.8 if v["tokens"] else 0.0, 100.0 * v["tokens"] / peak),
               colour, amt))
    return '<div class="rankgrp"><h3 class="sub">%s</h3>%s</div>' % (
        e(title), "".join(rows))


def _spark(values, peak, colour, days=None, label="", width=140, height=30):
    """A tiny column sparkline for the small-multiples grid, in the series' own
    colour — the row already names the model, so an anonymous grey spark would
    throw away the identity the swatch beside it establishes.

    A sparkline is deliberately unlabelled: it shows shape, not values. Hover
    supplies the day and the count for the one column being pointed at, which is
    the only way to read a value off a 140px chart with no axis.

    The tooltip hangs off a full-height transparent rect, not off the visible bar:
    a quiet day draws 2px tall, and a 2px hit target is one nobody can hit. Zero
    days get neither — there is nothing to report, and titling them all would grow
    the section by hundreds of marks to say "0"."""
    if not values:
        return ""
    peak = peak or 1
    n = len(values)
    slot = float(width) / n
    bw = max(1.0, slot - 1.0)
    days = days or []
    bars, hits = [], []
    for i, v in enumerate(values):
        if not v:
            # A zero column draws a zero-height rect: markup that renders nothing.
            # On a shared axis most panels are mostly zeros, so emitting them cost
            # 74 KB of invisible <rect> in a 300-phase report.
            continue
        # A hairline, not a bar: on a shared scale with a 200x range most columns
        # land below a pixel, and a 1.5px floor made twenty different days look
        # identical — presence reading as magnitude. 1px is visibly "some, below
        # this chart's resolution", and the caption says so.
        bh = max(1.0, height * v / peak)
        bars.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="1">'
                    "</rect>" % (i * slot, height - bh, bw, bh))
        if i < len(days):
            hits.append(
                '<rect class="hit" x="%.2f" y="0" width="%.2f" height="%d">'
                "<title>%s</title></rect>"
                % (i * slot, max(bw, 3.0), height,
                   _tip(days[i], [(label, _fmt_tokens(v, 2))] if label else [])))
    return ('<svg class="spark" viewBox="0 0 %d %d" preserveAspectRatio="none" '
            'aria-hidden="true" style="--sc:%s">%s%s</svg>'
            % (width, height, colour, "".join(bars), "".join(hits)))


SPARK_COLS = 60
# A 140px sparkline cannot draw a year: at half a pixel per column the shape stops
# being a shape and the markup grows without adding information. Past this many
# days the columns are binned into equal-width buckets and the caption SAYS the bin
# size, so the reader knows the resolution they are looking at.


def _bin_days(days, limit=SPARK_COLS):
    """days -> (labels, index groups, bin size). Identity below the limit."""
    if len(days) <= limit:
        return list(days), [[i] for i in range(len(days))], 1
    size = -(-len(days) // limit)
    groups = [list(range(i, min(i + size, len(days))))
              for i in range(0, len(days), size)]
    labels = [days[g[0]] if len(g) == 1
              else "%s to %s" % (days[g[0]], days[g[-1]]) for g in groups]
    return labels, groups, size


def _small_multiples(u, slots):
    """One panel per author, columns coloured by model — the static stand-in for the
    panel's drill-down, because a printed page has nothing to click."""
    sam = u.get("seriesAuthorModel") or {}
    if len(sam) < 2:
        return ""

    # Small multiples are only comparable on a SHARED frame, and they arrive here
    # without one: series() buckets each author over the days THAT AUTHOR was
    # active, so a panel covering 06-02..07-06 and one covering 06-02..07-21 draw
    # at the same width — the same x position means a different date in each. Fix
    # the x axis by re-projecting every panel onto the union of days; the y peak
    # below is already shared. The caption then states both, because a shared
    # frame the reader cannot see is a shared frame they cannot trust.
    alldays = sorted({d for s in sam.values() for d in (s.get("buckets") or [])})
    at = {d: i for i, d in enumerate(alldays)}
    grid = {}
    for author, s in sam.items():
        buckets = s.get("buckets") or []
        for ent in s["entities"]:
            row = [0] * len(alldays)
            for i, v in enumerate(ent["values"]):
                if v and i < len(buckets):
                    row[at[buckets[i]]] = v
            grid.setdefault(author, {})[ent["key"]] = row

    labels, groups, binsize = _bin_days(alldays)
    if binsize > 1:
        grid = {a: {m: [sum(r[i] for i in g) for g in groups]
                    for m, r in per.items()} for a, per in grid.items()}

    peak = max((max(r) for per in grid.values() for r in per.values()), default=0)
    if not peak or not alldays:
        return ""
    ranked = sorted(grid, key=lambda a: -sum(sum(r) for r in grid[a].values()))
    shown, hidden = ranked[:TOP_N], ranked[TOP_N:]
    # EVERY author's cell goes into the document (C3): the top 8 by spend are
    # visible (data-top marks the default set report.js restores), the tail is
    # present but `hidden` so an author chip can reveal any one of them without
    # a re-render — a printed page still shows only the top 8.
    cells = []
    for author in ranked:
        panels = "".join(
            '<div class="mm"><span class="mk" style="background:%s"></span>'
            '<span class="mn">%s</span>%s</div>'
            % (col, e(model), _spark(grid[author][model], peak, col,
                                     labels, model))
            for model, col in ((m, ("var(--viz-%d)" % slots[m])
                                if m in slots else "var(--bar-neutral)")
                               for m in sorted(grid[author],
                                               key=lambda y: slots.get(y, 99))))
        marker = ' data-top="1"' if author in shown else " hidden"
        cells.append('<div class="smcell" data-author="%s"%s><h4>%s</h4>%s</div>'
                     % (e(author), marker, e(author), panels))
    more = ('<p class="muted small">+%d more author(s) hidden — the top %d by '
            "spend show by default; pick an author chip above to see any one "
            "of them.</p>" % (len(hidden), TOP_N)) if hidden else ""
    unit = "day" if binsize == 1 else ("%d days" % binsize)
    return ('<h4 class="sub">Each author, by model</h4>'
            '<p class="muted small">Every panel shares one axis (%s to %s, one '
            "column per %s) and one scale (peak %s tokens per column), so heights "
            "and positions compare directly across people. A column too small to "
            "draw shows as a hairline — some spend, below this chart's resolution; "
            "hover it for the dates and the count.</p>"
            '<div class="smgrid">%s</div>%s'
            % (e(alldays[0]), e(alldays[-1]), e(unit), e(_fmt_tokens(peak)),
               "".join(cells), more))


def _monthly_block(u):
    """Calendar-month table: ledger spend beside plan progress, off the
    `monthly` dict usage_ledger.monthly_activity computed — the same
    computation site the CLI table and the panel card read.

    Rendered only when at least two months carry ledger activity: a one-month
    table restates the tiles. The caption names the derivation field by field,
    because "3 bugs fixed in June" is a claim and its basis (the linked task's
    completedAt, not a status flag) is not guessable from the number."""
    ma = u.get("monthly") or {}
    months = ma.get("months") or []
    led = ma.get("ledger") or {}
    plan = ma.get("plan") or {}
    active = [m for m in months
              if (led.get(m) or {}).get("tokens")
              or (led.get(m) or {}).get("msgs")]
    if len(active) < 2:
        return ""
    show_cost = u.get("showCost", True)
    rows = []
    for m in months:
        lg = led.get(m) or {}
        pl = plan.get(m) or {}
        cost_cell = ("<td class=mono>%s</td>"
                     % e(_fmt_cost(lg.get("costUSD", 0.0)))) if show_cost else ""
        rows.append(
            "<tr><td class=mono>%s</td><td class=mono>%s</td>%s<td>%s</td>"
            "<td>%d</td><td>%d</td><td>%d</td><td>%d</td></tr>"
            % (e(m), e(_fmt_tokens(lg.get("tokens", 0))), cost_cell,
               "{:,}".format(lg.get("msgs", 0)),
               pl.get("tasksCompleted", 0), pl.get("bugsReported", 0),
               pl.get("bugsFixed", 0), pl.get("phasesMerged", 0)))
    cost_th = "<th>cost</th>" if show_cost else ""
    return ('<h4 class="sub">Month by month</h4>'
            '<p class="muted small">Ledger columns are this ledger\'s spend by '
            "calendar month. Plan columns count the whole project by event "
            "month &mdash; a task in its <code>completedAt</code> month, a bug "
            "in its <code>reportedAt</code> month, a fix in the month its "
            "linked task completed (the same derivation the bug list uses), a "
            "phase in its <code>mergedAt</code> month.</p>"
            '<div class="tablewrap"><table class="data"><thead><tr>'
            "<th>month</th><th>tokens</th>%s<th>msgs</th><th>tasks done</th>"
            "<th>bugs</th><th>fixed</th><th>merged</th></tr></thead>"
            "<tbody>%s</tbody></table></div>" % (cost_th, "".join(rows)))


def _routing_table(u):
    """Cost per completed task and mean attempts, compared WITHIN a risk band.

    Never a spend-share ratio: tasks are not equal-sized, and the plugin routes hard
    work to the strong model on purpose. Comparing across risk bands would show that
    working system as a fault."""
    rt = u.get("routing") or {}
    if not rt.get("risks"):
        return ""
    rows = []
    for risk in rt["risks"]:
        cells = rt["byRisk"][risk]
        for i, (model, c) in enumerate(sorted(cells.items())):
            rows.append(
                "<tr><td>%s</td><td class=mono>%s</td><td>%d</td>"
                "<td class=mono>%s</td><td class=mono>%.1f</td></tr>"
                % (e(risk) if i == 0 else "", e(model), c["tasks"],
                   e(_fmt_cost(c["costPerTask"])), c["meanAttempts"] or 0))
    return ('<h4 class="sub">Model cost within each risk band</h4>'
            '<p class="muted small">Compared inside a band on purpose. Hard work is '
            "routed to the stronger model deliberately, so a raw spend-per-task "
            "comparison across bands would flag that working system as a fault.</p>"
            '<div class="tablewrap"><table class="data"><thead><tr><th>risk</th>'
            "<th>model</th><th>tasks</th><th>cost/task</th><th>mean attempts</th>"
            "</tr></thead><tbody>%s</tbody></table></div>%s"
            % ("".join(rows), _routing_advice_block(rt)))


def _routing_advice_block(rt):
    """The one place this section makes a recommendation rather than a report.

    Renders nothing unless the ledger's own evidence clears every gate in
    `_routing_advice` — and on a well-routed project that is the normal outcome,
    not a gap. The caveat is not boilerplate: the figure is the same tokens
    re-priced, and a different model would not emit the same tokens."""
    advice = (rt or {}).get("advice") or []
    if not advice:
        return ""
    items = []
    for a in advice:
        items.append(
            "<li><strong>%s</strong> work is running on <code>%s</code> — "
            "%d task(s) at %.1f mean attempts. Those same tokens cost %s at "
            "<code>%s</code> rates versus %s, <strong>%s less (%.0f%%)</strong>. "
            "<code>%s</code> has already run %d task(s) in this band here, at "
            "%.1f mean attempts.</li>"
            % (e(a["risk"]), e(a["from"]), a["tasks"], a["fromMeanAttempts"] or 0,
               e(_fmt_cost(a["atToRates"])), e(a["to"]),
               e(_fmt_cost(a["atFromRates"])), e(_fmt_cost(a["saving"])),
               a["savingPct"], e(a["to"]), a["evidenceTasks"],
               a["evidenceAttempts"] or 0))
    return ('<h4 class="sub">What the evidence supports</h4>'
            '<ul class="advice">%s</ul>'
            '<p class="muted small">An upper bound, not a forecast: this re-prices '
            "the tokens that were actually spent at the other model's rates, and a "
            "different model would not emit the same tokens. Both sides use "
            "today's price table, so the two figures share one rate epoch. Stated "
            "only where that model has already done comparable work in this repo "
            "at no worse an attempt rate.</p>" % "".join(items))


def _economics_block(u):
    """Unit economics, retry exposure and blocked spend — each stated as what it
    actually is."""
    unit = u.get("unit") or {}
    retry = u.get("retry") or {}
    if not (unit or retry):
        return ""
    out = ['<h4 class="sub">Unit economics</h4>']
    if unit.get("sufficient") and unit.get("projection"):
        out.append(
            '<p class="fact">Remaining %d task(s) project to '
            "<strong>%s&ndash;%s</strong> at the p25&ndash;p75 per-task rate.</p>"
            % (unit["remaining"], e(_fmt_cost(unit["projection"]["low"])),
               e(_fmt_cost(unit["projection"]["high"]))))
    elif unit.get("completed") is not None:
        out.append(
            '<p class="muted small">Projection needs %d completed tasks to mean '
            "anything; there are %d. A forecast off a smaller sample would be noise."
            "</p>" % (unit.get("gate", 5), unit.get("completed", 0)))
    if retry.get("totalCost"):
        out.append(
            '<p class="fact">%s on tasks that needed more than one attempt '
            "(%d task(s), %.0f%% of spend) &middot; <strong>%s</strong> on tasks that "
            "ended blocked (%d task(s)).</p>"
            % (e(_fmt_cost(retry["retriedCost"])), retry["retriedTasks"],
               retry["retriedPct"], e(_fmt_cost(retry["blockedCost"])),
               retry["blockedTasks"]))
        out.append(
            '<p class="muted small">Retried spend is not the same as wasted spend: '
            "the ledger buckets by hour, not by attempt, so a task that retried and "
            "then landed did not burn every attempt for nothing. Only the blocked "
            "figure is spend with no outcome%s.</p>"
            % (" (the same task is in both figures here)"
               if retry.get("overlaps") else ""))
    if unit.get("mostExpensive"):
        bands = u.get("bands") or {}
        by_task = (bands.get("byTask") or {}) if bands.get("sufficient") else {}
        rows = "".join(
            "<tr><td class=mono>%s</td><td>%s</td><td>%s</td>"
            "<td class=mono>%s</td><td>%s</td></tr>"
            % (e(tid), e(u.get("taskTitles", {}).get(tid, "")),
               ('<span class="bandpill b-%s">%s</span>' % (b, b)) if b
               else "&mdash;",
               e(_fmt_cost(cost)), e(str(att)) if att else "&mdash;")
            for tid, cost, att in unit["mostExpensive"]
            for b in (by_task.get(tid),))
        out.append('<h4 class="sub">Most expensive tasks</h4>'
                   "%s"
                   '<div class="tablewrap"><table class="data"><thead><tr>'
                   "<th>id</th><th>title</th><th>cost band</th><th>cost</th>"
                   "<th>attempts</th>"
                   "</tr></thead><tbody>%s</tbody></table></div>"
                   % (_band_note(bands), rows))
    return "".join(out)


def _band_note(bands):
    """Say where the thresholds came from — or why there are none.

    A band whose definition is invisible is a number nobody can argue with, and
    "this task is an outlier" is exactly the kind of claim that has to be
    checkable. On a young project this note is the whole content: it explains that
    the feature is waiting for a sample rather than silently showing nothing."""
    if not bands:
        return ""
    if not bands.get("sufficient"):
        return ('<p class="muted small">No cost band yet — it calibrates from this '
                "project's own completed tasks and needs %d, of which there are "
                "%d. Set <code>usage.bands.highUSD</code> and "
                "<code>usage.bands.outlierUSD</code> to band against a fixed "
                "budget instead.</p>"
                % (bands.get("gate", 5), bands.get("sample", 0)))
    return ('<p class="muted small">Cost band from %s: typical &le; %s · high &le; '
            "%s · outlier above.</p>"
            % ("configured thresholds" if bands.get("basis") == "absolute"
               else "this project's own completed tasks (median / p90)",
               e(_fmt_cost(bands.get("high"))), e(_fmt_cost(bands.get("outlier")))))


def _phase_stacks(u, slots, models):
    """Per-phase stacked bars by model. Segments are emitted in SLOT order so the
    rendered adjacency is the adjacency the palette was validated on."""
    allp = sorted((u.get("phaseModel") or {}).items(),
                  key=lambda kv: -sum(kv[1].values()))
    if not allp:
        return ""
    phases, hidden = allp[:TOP_N], allp[TOP_N:]
    peak = max(sum(v.values()) for _, v in phases) or 1
    # Segments carry no inline labels (an interior stacked segment has no free end
    # to put one on), so identity here MUST come from a legend — never colour alone.
    # The ranked "By model" list above direct-labels instead, which is why it does
    # not repeat this.
    out = []
    if len(models) > 1:
        out.append('<div class="legend">%s</div>' % "".join(
            '<b><i style="background:var(--viz-%d)"></i>%s</b>' % (slots[m], e(m))
            for m in models))
    for pid, per_model in phases:
        total = sum(per_model.values())
        label = u["phaseTitles"].get(pid) or ("unattributed" if pid == "--" else "")
        segs = "".join(
            '<i class="seg" style="flex:%d 0 0;background:var(--viz-%d)" '
            'title="%s - %s - %s tokens"></i>'
            % (per_model[m], slots[m], e(pid), e(m),
               _fmt_tokens(per_model[m], 2))
            for m in models if per_model.get(m))
        out.append(
            '<div class="uphase"><span class="nm"><span class="mono">%s</span> %s</span>'
            '<span class="stack" style="width:%.1f%%" role="img" '
            'aria-label="%s: %s tokens">%s</span>'
            '<span class="amt">%s</span></div>'
            % (e(pid), e(label), 100.0 * total / peak, e(pid),
               _fmt_tokens(total), segs, e(_fmt_tokens(total))))
    if hidden:
        out.append('<p class="muted small">+%d more phase(s) not shown; the ranked '
                   '"By phase" list above covers every one.</p>' % len(hidden))
    return '<h4 class="sub">Phase composition by model</h4>%s' % "".join(out)


# --- heatmap ------------------------------------------------------------------
_WDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _usage_heatmap(u):
    """Day-of-week x hour grid on a single-hue sequential ramp (never a rainbow).
    Zero recedes into the surface; a scale key makes the encoding readable."""
    grid = u.get("heatmap") or []
    if len(grid) != 7:
        return ""
    peak = max((max(row) for row in grid), default=0)
    if not peak:
        return ""
    rows = []
    for d in range(7):
        cells = []
        for hh in range(24):
            n = grid[d][hh]
            level = 0 if not n else min(6, 1 + int(5.0 * n / peak))
            cells.append('<td><i data-l="%d" title="%s %02d:00 - %s tokens">'
                         "</i></td>" % (level, _WDAY[d], hh, _fmt_tokens(n, 2)))
        rows.append("<tr><th>%s</th>%s</tr>" % (_WDAY[d], "".join(cells)))
    ticks = "".join("<th>%s</th>" % (str(h).zfill(2) if h % 6 == 0 else "")
                    for h in range(24))
    key = "".join('<i style="background:var(--hm-%d)"></i>' % i for i in range(7))
    return ('<h4 class="sub">When the tokens are spent (UTC)</h4>'
            '<div class="hmwrap"><table class="hm"><thead><tr><th></th>%s</tr>'
            "</thead><tbody>%s</tbody></table></div>"
            '<p class="hmkey">0 %s %s tokens/hour</p>'
            % (ticks, "".join(rows), key, e(_fmt_tokens(peak))))


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

    win = u.get("compareWindow") or {}
    out.append('<h3 class="sub">Tokens per day</h3>')
    if u.get("compare") and (u["compare"].get("prior") is not None):
        out.append('<p class="muted small" style="margin:0 0 var(--sp-1)">'
                   "Deltas above compare %s to %s with the 30 days before it.</p>"
                   % (e(win.get("since") or "?"), e(win.get("until") or "?")))
    out.append(_usage_trend(u))

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
    return "".join(out)


# --- markdown rendering -------------------------------------------------------
def _md(v):
    """Markdown cell escaper — same contract as render_md's local `cell`: only the
    metacharacters that would break a pipe table."""
    return str(v if v is not None else "—").replace("|", "\\|").replace("\n", " ")


def _usage_md(u):
    """The table view of the Usage section. This is not decoration: three light-mode
    categorical slots sit under 3:1 contrast, and the documented relief for that is
    a table carrying the same numbers. It also keeps the Markdown twin honest."""
    if not u or not u.get("totals", {}).get("tokens"):
        return ""
    t = u["totals"]
    show_cost = u.get("showCost", True)
    lines = ["", "## Usage", ""]
    head = "**Total:** %s tokens" % _fmt_tokens(t["tokens"])
    if show_cost:
        head += " · ~%s equiv" % _fmt_cost(t["costUSD"])
    head += " · %s msgs · %d session(s) · cache hit %.0f%%" % (
        "{:,}".format(t["msgs"]), t["sessions"], t["cacheHitPct"])
    if show_cost:                       # see _usage_context for why there is no fallback
        head += (" · rates as of %s" % u["pricingAsOf"] if u.get("pricingAsOf")
                 else " · rates undated (set usage.pricingAsOf)")
    lines += [head, ""]

    def block(title, data, key_label):
        if not data:
            return []
        cols = "| %s | tokens | %smsgs |" % (key_label, "cost | " if show_cost else "")
        sep = "|---|---:|%s---:|" % ("---:|" if show_cost else "")
        rows = []
        for k, v in sorted(data.items(), key=lambda kv: -kv[1]["tokens"]):
            # One decimal, matching the ranked list this table mirrors. The
            # two-decimal form is the hover affordance, and Markdown has no hover.
            cells = [k, _fmt_tokens(v["tokens"])]
            if show_cost:
                cells.append(_fmt_cost(v["costUSD"]))
            cells.append("{:,}".format(v["msgs"]))
            rows.append("| %s |" % " | ".join(_md(c) for c in cells))
        return ["### %s" % title, "", cols, sep] + rows + [""]

    lines += block("By phase", u["byPhase"], "phase")
    lines += block("By model", u["byModel"], "model")
    if len(u.get("byAuthor") or {}) > 1:
        lines += block("By author", u["byAuthor"], "author")

    # The monthly overview, same gate and same derivation note as the HTML —
    # the twin must not know months the page does not, or vice versa.
    _ma = u.get("monthly") or {}
    _mm = _ma.get("months") or []
    _mled = _ma.get("ledger") or {}
    _mplan = _ma.get("plan") or {}
    if len([m for m in _mm
            if (_mled.get(m) or {}).get("tokens")
            or (_mled.get(m) or {}).get("msgs")]) >= 2:
        cols = ("| month | tokens | %smsgs | tasks done | bugs | fixed | "
                "merged |" % ("cost | " if show_cost else ""))
        sep = "|---|---:|%s---:|---:|---:|---:|---:|" % (
            "---:|" if show_cost else "")
        lines += ["### Month by month", "",
                  "Plan columns count the whole project by event month (task "
                  "completedAt, bug reportedAt, the linked task's completedAt "
                  "for a fix, phase mergedAt).", "", cols, sep]
        for m in _mm:
            lg = _mled.get(m) or {}
            pl = _mplan.get(m) or {}
            cells = [m, _fmt_tokens(lg.get("tokens", 0))]
            if show_cost:
                cells.append(_fmt_cost(lg.get("costUSD", 0.0)))
            cells += ["{:,}".format(lg.get("msgs", 0)),
                      str(pl.get("tasksCompleted", 0)),
                      str(pl.get("bugsReported", 0)),
                      str(pl.get("bugsFixed", 0)),
                      str(pl.get("phasesMerged", 0))]
            lines.append("| %s |" % " | ".join(_md(c) for c in cells))
        lines.append("")

    # The analytics carry the same honesty caveats as the HTML. This is not a
    # summary of the charts — for the three light-mode palette slots that sit under
    # 3:1 contrast, this table IS the documented relief, so it has to hold every
    # number the charts encode in colour.
    unit, retry = u.get("unit") or {}, u.get("retry") or {}
    cache, cov = u.get("cache") or {}, u.get("coverage") or {}
    facts = []
    if cache:
        facts.append("- **Cache:** %.0f%% hit; the input side bills at %.0f%% of "
                     "fresh-token rates." % (cache.get("hitPct", 0),
                                             cache.get("inputCostVsFreshPct", 100)))
        if cache.get("worstPhase"):
            facts.append("- **Lowest cache phase:** %s at %.0f%%."
                         % (_md(cache["worstPhase"][0]), cache["worstPhase"][1]))
    if cov:
        facts.append("- **Attribution:** %.0f%% of spend attributed (%.0f%% to a "
                     "specific task)." % (cov.get("attributedPct", 0),
                                          cov.get("taskLevelPct", 0)))
    if unit.get("costPerTask") is not None:
        facts.append("- **Cost per completed task:** %s across %d task(s)."
                     % (_fmt_cost(unit["costPerTask"]), unit.get("completed", 0)))
    if unit.get("sufficient") and unit.get("projection"):
        facts.append("- **Projection:** remaining %d task(s) at the p25-p75 rate = "
                     "%s to %s." % (unit["remaining"],
                                    _fmt_cost(unit["projection"]["low"]),
                                    _fmt_cost(unit["projection"]["high"])))
    elif unit.get("completed") is not None:
        facts.append("- **Projection:** suppressed — needs %d completed tasks, has "
                     "%d." % (unit.get("gate", 5), unit.get("completed", 0)))
    if retry.get("totalCost"):
        facts.append("- **Retried tasks:** %s across %d task(s) (%.0f%% of spend). "
                     "Not the same as wasted spend — the ledger buckets by hour, "
                     "not by attempt."
                     % (_fmt_cost(retry["retriedCost"]), retry["retriedTasks"],
                        retry["retriedPct"]))
        facts.append("- **Blocked tasks:** %s across %d task(s) — spend with no "
                     "outcome." % (_fmt_cost(retry["blockedCost"]),
                                   retry["blockedTasks"]))
    if facts:
        lines += ["### Economics", ""] + facts + [""]

    rt = u.get("routing") or {}
    if rt.get("risks"):
        lines += ["### Model cost within each risk band", "",
                  "Compared inside a band on purpose: hard work is routed to the "
                  "stronger model deliberately, so a raw spend-per-task comparison "
                  "across bands would flag that working system as a fault.", "",
                  "| risk | model | tasks | cost/task | mean attempts |",
                  "|---|---|---:|---:|---:|"]
        for risk in rt["risks"]:
            for model, c in sorted(rt["byRisk"][risk].items()):
                lines.append("| %s | %s | %d | %s | %.1f |" % (
                    _md(risk), _md(model), c["tasks"],
                    _fmt_cost(c["costPerTask"]), c["meanAttempts"] or 0))
        lines.append("")
    return "\n".join(lines)


# --- selftest -----------------------------------------------------------------
def _selftest():
    """The usage region's own cases, moved here with the code they are about
    (P13.2). Whole-document pins stayed in render-report: that a report with no
    ledger has no Usage section, that render_html composes one in when there is,
    and every CSS/script pin about the page these fragments land on. What is
    below renders through `_usage_section` / `_usage_md` directly, so a failure
    names the fragment rather than the page."""
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

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

    uh = _usage_section(_u)
    um = _usage_md(_u)

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
          "&lt;$0.01" in _usage_tiles(_uc), _usage_tiles(_uc))
    check("u4b the Markdown twin says the same thing",
          "rates as of 2026-08-06" in um)
    _uq = dict(_u, showCost=False)
    _hq, _mq = _usage_section(_uq), _usage_md(_uq)
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
    _hn, _mn = _usage_section(_un), _usage_md(_un)
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
          "rates" not in _usage_context({})
          and "rates" not in _usage_context({"counts": {"phases": 1}})
          and "rates" not in _usage_context({"totals": {"tokens": 0}}))
    check("u5 model identity is never colour-alone: legend on the unlabelled "
          "stacks, direct labels on the ranked list",
          'class="legend"' in uh and uh.count("claude-opus-5") >= 2)
    check("u6 model colour follows the entity (slot by NAME, not by rank)",
          _model_slots(["claude-opus-5", "claude-haiku-4-5"])["claude-haiku-4-5"] == 1
          and _model_slots(["claude-opus-5", "claude-haiku-4-5"])["claude-opus-5"] == 2)
    check("u7 a 9th model folds into the last slot, never a generated hue",
          max(_model_slots(["m%d" % i for i in range(12)]).values()) == VIZ_SLOTS)
    # Asserted on the stack itself, not on the page. The document-level form of
    # this case (`uh.index("var(--viz-1)") < uh.index("var(--viz-2)")`) was
    # satisfied by the STYLESHEET, which declares --viz-1 before --viz-2 near the
    # top of every report - so it passed whatever order the segments came out in.
    # Read off the section alone it fails immediately, because the ranked "By
    # model" list above sorts by spend and legitimately puts viz-2 first.
    _stack = _phase_stacks(_u, _model_slots(_u["byModel"].keys()),
                           sorted(_u["byModel"],
                                  key=lambda m: _model_slots(
                                      _u["byModel"].keys())[m]))
    check("u8 stacked segments are emitted in slot order (validated adjacency)",
          _stack.index('class="seg" style="flex:100000 0 0;'
                       "background:var(--viz-1)")
          < _stack.index('class="seg" style="flex:900000 0 0;'
                         "background:var(--viz-2)"))
    check("u9 daily column chart and heatmap render",
          'class="cols"' in uh and 'class="hm"' in uh)
    check("u11 every chart mark carries a title for hover/AT",
          uh.count("<title>") >= 2 and 'role="img"' in uh)
    check("u13 md twin lists authors only when there is more than one",
          "### By author" in um
          and "### By author" not in _usage_md(
              dict(_u, byAuthor={"a@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})))
    # The whole-page fetch count is pinned by render-report's x5; this narrows it
    # to the section, since that fixture manifest carries a legitimate https link.
    check("u14 the usage section itself adds no external fetch",
          "http" not in _usage_section(_u))

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
    _bh = _usage_section(_big)
    check("u17 ranked lists fold past the top N and label the remainder",
          "other (" in _bh, "no fold marker")
    check("u18 phase composition folds and says how many are hidden",
          _bh.count('class="uphase"') == TOP_N and "+22 more phase" in _bh,
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
              default=0) <= VIZ_SLOTS)
    # --- orientation + hover -----------------------------------------------------
    check("u21 context line states scale and span without spending a tile on it",
          'class="uctx"' in uh and "2 people" in uh and "3 sessions" in uh
          and "2026-08-01 to 2026-08-02" in uh and _usage_context({}) == "")
    # The separator is a middot, spelled as an escape so this file stays ASCII:
    # asserting on "1 phase" alone would also match "1 phases".
    check("u21b counts are singularised (1 phase, not '1 phases')",
          ("1 phase \u00b7"
           in _usage_context({"counts": {"phases": 1, "people": 3}})))
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
    _smh = _usage_section(_sm)
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
    _lh = _usage_section(_lu)
    _lbars = [len(re.findall(r'<rect(?! class="hit")', s))
              for s in re.findall(r'<svg class="spark".*?</svg>', _lh, re.S)]
    check("u23e 280 days bin down to <=%d columns and the caption says the bin "
          "size (0.5px per column is noise, not a shape)" % SPARK_COLS,
          _lbars and max(_lbars) <= SPARK_COLS and "one column per 5 days" in _lh,
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
    _tiny = _ranked(dict(_u, byModel={
        "big": {"tokens": 1000000, "costUSD": 1.0, "msgs": 9},
        "sliver": {"tokens": 300, "costUSD": 0.01, "msgs": 1}}), "byModel", "By model")
    check("u25 a tiny non-zero bar still paints a sliver, never an empty track",
          "width:0.8%" in _tiny and "width:100.0%" in _tiny,
          re.findall(r"width:[\d.]+%", _tiny))

    # --- one number format, everywhere ------------------------------------------
    check("u26 tokens are compact at one decimal, and two on hover",
          _fmt_tokens(3230000) == "3.2M" and _fmt_tokens(3230000, 2) == "3.23M"
          and _fmt_tokens(942) == "942" and _fmt_tokens(2000000000) == "2.0B"
          and _fmt_tokens(214300, 2) == "214.30K",
          _fmt_tokens(3230000, 2))
    # The rule is easy to state and easy to break one call site at a time: the
    # label reads 3.2M and the tooltip that opens over it reads 3,230,000. So the
    # guard is mechanical - every raw thousands-separated number must be a
    # COUNTABLE (messages, sessions, tasks), never a token magnitude. It reads
    # render-report's source too: the formatters moved here, the rule did not stop
    # applying to the file they left (a file read, never an import - the DAG says
    # nothing in here may depend on that module).
    _bad = []
    for _f in (__file__, os.path.join(_HERE, "render-report.py")):
        with open(_f, encoding="utf-8") as _fh:
            _src = _fh.read()
        _bad += [(os.path.basename(_f), x)
                 for x in re.findall(r'"\{:,\}"\.format\(([^)]*)\)', _src)
                 if not re.search(r"msgs|sessions|tasks|phases", x)]
    check("u27 no token value is ever rendered with thousand separators "
          "(counts may be; magnitudes may not)", _bad == [], repr(_bad))
    check("u28 the md twin uses the same compact tokens as the HTML labels",
          "**Total:** 1.5M tokens" in um and "| P1 | 1.0M |" in um,
          [ln for ln in um.splitlines() if "1.0M" in ln or "Total:" in ln][:3])
    # preserveAspectRatio="none" scales the coordinate system non-uniformly, and
    # that scales the glyphs with it - measured at +49% width on a 1072px render.
    # The bars are meant to stretch; the type is not, so the type is not in there.
    _trend = _usage_trend(_u)
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
    _sup = _band_note({"sufficient": False, "gate": 5, "sample": 3})
    check("u30 below the gate the report explains the absence and names the "
          "config escape hatch",
          "needs 5" in _sup and "there are 3" in _sup
          and "usage.bands.highUSD" in _sup)
    _rel = _band_note({"sufficient": True, "basis": "relative",
                       "high": 5.5936, "outlier": 35.4031})
    check("u31 an active band states its basis AND its thresholds",
          "median / p90" in _rel and "$5.59" in _rel and "$35.40" in _rel)
    check("u32 an absolute basis says so instead of claiming a percentile",
          "configured thresholds" in _band_note(
              {"sufficient": True, "basis": "absolute", "high": 15, "outlier": 50}))
    _bh2 = _usage_section(dict(
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
          _budget_block(dict(_u, budgets={"phases": [
              {"id": "P1", "title": "A", "budget": None, "spent": 5.0,
               "pct": None, "over": False}], "budgeted": 0,
              "totalBudget": None, "totalSpent": None, "anyOver": False})) == "")
    _bud = _budget_block(dict(_u, budgets={
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
          _routing_advice_block({"advice": []}) == ""
          and _routing_advice_block({}) == "")
    _adv = _routing_advice_block({"advice": [{
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
    _ac = _author_chips(_u)
    check("ua1 with more than one author the chip row renders one chip per "
          "author, each carrying its totals as data attributes",
          _ac.count('data-au=') == 2
          and 'data-au="a@x.io"' in _ac
          and 'data-tokens="1.0M"' in _ac and 'data-cost="$8.00"' in _ac
          and 'data-msgs="30"' in _ac and 'data-share="67%"' in _ac
          and 'aria-pressed="false"' in _ac)
    check("ua2 a single author renders no chip row - there is nothing to "
          "compare",
          _author_chips(dict(_u, byAuthor={
              "a@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})) == "")
    check("ua3 the chips, the scope note and the summary-line slot reach the "
          "section, and the note says what stays project-wide",
          'id="audit-authors"' in uh and 'id="audit-au-note"' in uh
          and "stay project-wide" in uh
          and "records no author" in uh)
    check("ua4 showCost off empties the cost attribute rather than shipping a "
          "dollar the page hides",
          'data-cost=""' in _author_chips(dict(_u, showCost=False)))
    check("ua5 By author rows carry data-author for the chips to drive; other "
          "ranked lists do not",
          'data-author="a@x.io"' in _ranked(_u, "byAuthor", "By author",
                                            row_attr="data-author")
          and 'data-author' not in _ranked(_u, "byPhase", "By phase"))
    check("ua6 an author name is escaped in the chip like everywhere else",
          "&lt;script&gt;" in _author_chips(dict(_u, byAuthor={
              "<script>": {"tokens": 5, "costUSD": 0.0, "msgs": 1},
              "b@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}}))
          and "<script>" not in _author_chips(dict(_u, byAuthor={
              "<script>": {"tokens": 5, "costUSD": 0.0, "msgs": 1},
              "b@x.io": {"tokens": 1, "costUSD": 0.0, "msgs": 1}})))
    check("ua7 every smcell names its author so a chip can find it",
          _usage_section(_sm).count('data-author=') >= 2)

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
          _monthly_block(dict(_u, monthly={
              "months": ["2026-07", "2026-08"],
              "ledger": {"2026-07": {"tokens": 0, "costUSD": 0.0, "msgs": 0},
                         "2026-08": {"tokens": 5, "costUSD": 0.1, "msgs": 1}},
              "plan": {"2026-07": {"tasksCompleted": 1, "bugsReported": 0,
                                   "bugsFixed": 0, "phasesMerged": 0},
                       "2026-08": {"tasksCompleted": 0, "bugsReported": 0,
                                   "bugsFixed": 0, "phasesMerged": 0}}})) == ""
          and _monthly_block(dict(_u, monthly=None)) == "")
    check("um3 showCost off drops the monthly cost column and every dollar "
          "with it",
          "<th>cost</th>" not in _monthly_block(dict(_u, showCost=False))
          and "$" not in _monthly_block(dict(_u, showCost=False))
          and "<th>cost</th>" in _monthly_block(_u))
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
        _lu = load_usage({"meta": {}, "phases": [{"id": "P1", "tasks": [
            {"id": "P1.1", "status": "done",
             "completedAt": "2026-08-01T10:00:00Z"}]}], "bugs": []},
            os.path.join(_tmp, "m.json"), _tmp)
        check("um5 load_usage computes `monthly` from ledger + manifest through "
              "the one computation site",
              bool(_lu) and _lu.get("monthly", {}).get("months")
              == ["2026-07", "2026-08"]
              and _lu["monthly"]["plan"]["2026-08"]["tasksCompleted"] == 1)
    finally:
        _sh.rmtree(_tmp, ignore_errors=True)

    check("u15 zero-token ledger renders nothing rather than an empty frame",
          _usage_section(dict(_u, totals=dict(_u["totals"], tokens=0))) == ""
          and _usage_md(dict(_u, totals=dict(_u["totals"], tokens=0))) == "")
    check("u16 model names are HTML-escaped",
          "&lt;script&gt;" in _usage_section(
              dict(_u, byModel={"<script>": {"tokens": 5, "costUSD": 0.0,
                                             "msgs": 1}},
                   phaseModel={"P1": {"<script>": 5}})))

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
