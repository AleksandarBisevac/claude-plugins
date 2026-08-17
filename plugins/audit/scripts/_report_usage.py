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

Formatting is not decided here: `_fmt_tokens` / `_fmt_cost` / `_fmt_pct`
delegate to _fmt (P10.6), the one token/cost/share formatter shared with the
panel and /audit:usage. Neither is the divide: every share and every bar width
in this file goes through `_fmt.share_pct`, via `_fill_pct` (a bar's answer to
"there is no whole") or `_hover_share` (a share string's). No `or 1` — that
fabricates a denominator and turns an unmeasurable share into a confident one.

One rule decides whether a rendered share carries `fmt_share`'s `<1%` floor,
and it is about what sits BESIDE the number:

  * A share that stands ALONE as a claim — a tooltip line, a stat tile, a
    sentence — floors. `0%` for a slice that exists reads as "none", which is
    the same lie `$0.00` tells about real spend, and `fmt_cost` has refused to
    tell that one since P10.6.
  * A share printed immediately NEXT TO the two numbers it was divided from —
    a bar's width beside its own token count, a budget label beside `$spent of
    $budget`, a saving beside both dollar figures — does not. The basis is
    already on screen, and a floor would only disagree with the geometry drawn
    beside it. Same asymmetry `_fmt.bar_cells` and `_fmt.fmt_share` already
    make about the missing denominator.
  * A percent CHANGE (`_delta`) is not a share at all: `+0%` says "essentially
    unchanged", which is true, where `<1%` would claim a slice exists.

render-report.py keeps thin module-level aliases (`load_usage`,
`_usage_section`, `_usage_md`, `_fmt_tokens`, ...) so render_html / render_md
and its own selftest keep referring to these names unchanged.

Imports go one way only: _report_html -> _report_usage -> render-report. This
module may use _loader (to load usage_ledger.py), _fmt, _ui_theme and
_report_html; it must never import render-report.

This module carries no `--selftest` of its own any more; its 104 cases live in
`plugins/audit/tests/test__report_usage.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. `import re` went with them: every use of it
in this file was inside that suite, and a stdlib import kept for a reader who is
no longer here is an import ruff fails by name.
"""
import json
import os
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
import _ui_theme as _theme  # noqa: E402  (the one place a machine value gets its words)

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


def _hourly(rows, ul):
    """rows -> {"YYYY-MM-DD": [24 ints]} — tokens per hour per calendar date.

    The ledger already keys rows by hour bucket (`YYYY-MM-DDTHH`), so this is a
    straight regrouping, not a new derivation. Days appear only when they carry
    at least one parseable row; absent days are absent keys, and the client
    treats a missing day as 24 zeros."""
    out = {}
    for row in rows:
        bucket = row.get("ts")
        day = ul.bucket_date(bucket)
        hour = ul.bucket_hour(bucket)
        if not day or hour is None:
            continue
        vec = out.get(day)
        if vec is None:
            vec = out[day] = [0] * 24
        vec[hour] += sum(int(row.get(k) or 0) for k in ul.TOKEN_KEYS)
    return out


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

        # One pass per dimension, hoisted. `aggregate` walks EVERY ledger row and
        # this dict asked for the same four dimensions more than once: `day` three
        # times (the token, cost and message series are three reads of one
        # aggregate) and phase/model/author twice each — once for the breakdown,
        # once for the orientation counts. Eleven full scans for six answers.
        # Sharing the dicts is safe because nothing here mutates one: `slim` builds
        # new dicts and the counts only measure key sets.
        by_day = ul.aggregate(rows, "day")
        by_phase = ul.aggregate(rows, "phase")
        by_model = ul.aggregate(rows, "model")
        by_author = ul.aggregate(rows, "author")

        def slim(agg):
            """The three fields a breakdown renders, out of a finished aggregate."""
            return {k: {"tokens": v["tokens"], "costUSD": v["costUSD"],
                        "msgs": v["msgs"]}
                    for k, v in agg.items()}

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
            "byPhase": slim(by_phase),
            "byModel": slim(by_model),
            "byAuthor": slim(by_author),
            "byAgent": slim(ul.aggregate(rows, "agent")),
            "phaseModel": phase_model,
            "phaseTitles": titles,
            # Through `_report_html._tasks_by_id`, which IS `_manifest_io`'s
            # index (aliased, not copied — a case in that file pins the identity).
            # Same truthy-id filter and same LAST-wins duplicate rule this
            # comprehension had, so a duplicated task id still labels rows with
            # the last title the plan gives it.
            "taskTitles": {tid: t.get("title") or ""
                           for tid, t in
                           _report_html._tasks_by_id(manifest).items()},
            "daily": {k: v["tokens"] for k, v in by_day.items()
                      if k != "unknown"},
            "dailyCost": {k: v["costUSD"] for k, v in by_day.items()
                          if k != "unknown"},
            "dailyMsgs": {k: v["msgs"] for k, v in by_day.items()
                          if k != "unknown"},
            # Per-date hour vectors (C1/C3): {"YYYY-MM-DD": [24 ints]}. The 7x24
            # heatmap aggregates AWAY the calendar, so it cannot be navigated by
            # day/week/month/year after the fact — this keeps the calendar. It is
            # embedded into the page (see _usage_payload) for the report's own
            # date-range and heatmap navigation, both of which run client-side in
            # a file with no server to ask.
            "hourly": _hourly(rows, ul),
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
                "phases": len([k for k in by_phase if k != "--"]),
                "people": len(by_author),
                "models": len(by_model),
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


def _fmt_pct(x):
    """An ALREADY-DERIVED rate — cache hit, attribution coverage, retried share
    of spend — rendered under the one share rule: `<1%` for a real-but-tiny
    rate, never the `0%` that reads as "none".

    These arrive as percentages rather than as a part and a whole: the divide
    happened in _usage_analytics, which rounds each to one decimal.
    `fmt_share(x, 100)` is that percentage read back as a share of a hundred —
    the same identity `_fmt.bar_cells(part, whole, 100)` already uses for the
    CSS fill, and byte-identical to the `"%.0f%%"` it replaces everywhere
    outside the 0-to-1 window.

    The floor therefore only reaches what survived that rounding: a rate under
    0.05% arrives here as `0.0` and is indistinguishable from a genuine zero.
    That is upstream's information to keep, not this renderer's to guess at —
    so `0.0` renders `0%`, which is what the number actually says."""
    return _fmt.fmt_share(x, 100)


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
    against. A first-run report must not invent a trend.

    NOT floored, because this is not a share: `+0%` says "essentially unchanged",
    which is true and is what a reader wants from a delta, where `<1%` would
    claim a slice exists. The sign is part of the string too, and `+<1%` is not
    a thing anyone reads."""
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


# --- rankings + sparklines + tables -------------------------------------------
def _fill_pct(part, whole):
    """How wide a bar's fill is, in percent — 0.0 when there is no whole.

    `_fmt.share_pct` owns the divide; this only names the BAR's answer to a share
    nobody can compute, which is not the share string's answer. No bar in this
    section travels alone: the ranked rows and the phase stacks each print their
    own token count beside the track, so an empty track sits next to the number
    that explains it, while a `width:` has nowhere to put a sentinel. Same
    asymmetry, same reasoning as `_fmt.bar_cells`, which returns 0 cells here.

    Not `_fmt.bar_cells(part, whole, 100)` itself: these tracks are drawn at one
    decimal, and the ranked list floors a real-but-tiny row at 0.8% — a whole-cell
    minimum would round that to 1.0% and change every measurable row that has it.

    Left unfloored when `_hover_share` adopted `fmt_share`'s `<1%`: a CSS width
    has no way to say "<1%", the ranked list's own 0.8% minimum is the geometric
    form of the same rule, and the token count printed beside the track already
    says what the empty-looking bar is worth."""
    pct = _fmt.share_pct(part, whole)
    return 0.0 if pct is None else pct


def _hover_share(part, whole):
    """`part` as a percentage of `whole` for a hover line — `<1%` for a
    real-but-tiny slice, `0%` only for a genuine zero, `?` when there is no
    whole to divide by.

    A PURE ALIAS for `_fmt.fmt_share`, and said out loud rather than dressed up:
    it adds nothing, not even the sentinel, which is fmt_share's own default. It
    keeps its name because `_fill_pct` and `_hover_share` are how the rest of
    this file names the two answers to "there is no whole" — a bar's and a share
    string's — and a name is cheaper to keep than a second copy of the rule,
    which is how the two drift.

    The mirror of `_fill_pct`: this string sits alone inside a tooltip with
    nothing beside it, so an unmeasurable share must say so rather than report a
    confident `0%` that reads exactly like a measured one — and, since this
    change, a MEASURABLE one must not say `0%` either. It used to reimplement
    fmt_share without the `<1%` floor on purpose, so that guarding the divide
    could not move a measurable share; that exception is over. A row at 0.03% of
    the grand total read `0%` here, and a slice that exists reported as nothing
    is the same lie `fmt_cost` refuses to tell about sub-cent spend. Saying what
    a row is worth is the tooltip's entire job.

    Note the floor is not only about rounding DOWN: `0.7%` read `1%` here too,
    overstating a slice that never reached one percent. `fmt_share` answers
    `<1%` to both."""
    return _fmt.fmt_share(part, whole)


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
    if not peak:
        # No `or 1`. `peak` is the SHARED peak of the whole small-multiples grid,
        # so a peak of zero says every panel in it recorded nothing — and against
        # a fabricated peak of 1 every column is still zero and skipped, leaving
        # an empty <svg> frame drawn to a scale nobody measured. The same answer
        # the daily trend gives (`_usage_trend`) and the same answer this section
        # gives a zero-token ledger: no shape to plot, so nothing is plotted.
        #
        # Only a whole EMPTY GRID takes this exit. A panel that is all zeros
        # against a real shared peak keeps its frame, because on a shared axis
        # that empty frame is the finding — this author ran nothing on this model
        # while the panel beside it ran plenty.
        return ""
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
        # data-um is the month's own key (C1): the global date range hides the
        # rows for months wholly outside it, client-side.
        rows.append(
            '<tr data-um="%s"><td class=mono>%s</td><td class=mono>%s</td>%s<td>%s</td>'
            "<td>%d</td><td>%d</td><td>%d</td><td>%d</td></tr>"
            % (e(m), e(m), e(_fmt_tokens(lg.get("tokens", 0))), cost_cell,
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
    # `savingPct` is NOT floored: the sentence prints both sides of the divide a
    # few words earlier ("cost X at <to> rates versus Y"), so the basis for the
    # percentage is in the same clause. The bar-label case, in prose.
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
        # Floored: the total spend this is a share OF is in the tiles far above,
        # not in this sentence, so "0% of spend" travels alone beside a dollar
        # figure that says the opposite.
        out.append(
            '<p class="fact">%s on tasks that needed more than one attempt '
            "(%d task(s), %s of spend) &middot; <strong>%s</strong> on tasks that "
            "ended blocked (%d task(s)).</p>"
            % (e(_fmt_cost(retry["retriedCost"])), retry["retriedTasks"],
               e(_fmt_pct(retry["retriedPct"])), e(_fmt_cost(retry["blockedCost"])),
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
    # No `or 1`; the divide is guarded once, in `_fill_pct`. A stack is a bar with
    # its own total printed beside it, so an unmeasurable width draws an empty
    # track rather than a sentinel — `_fill_pct` says why.
    peak = max(sum(v.values()) for _, v in phases)
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
        label = (_theme.UNCATEGORIZED if pid == "--"
                 else u["phaseTitles"].get(pid) or "")
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
            % (e(pid), e(label), _fill_pct(total, peak), e(pid),
               _fmt_tokens(total), segs, e(_fmt_tokens(total))))
    if hidden:
        out.append('<p class="muted small">+%d more phase(s) not shown; the ranked '
                   '"By phase" list above covers every one.</p>' % len(hidden))
    return '<h4 class="sub">Phase composition by model</h4>%s' % "".join(out)


# --- heatmap ------------------------------------------------------------------
_WDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _usage_heatmap(u):
    """Day-of-week x hour grid on a single-hue sequential ramp (never a rainbow).
    Zero recedes into the surface; a scale key makes the encoding readable.

    C3 adds calendar navigation on top: granularity chips (all/year/month/week/
    day) with prev/next arrows, server-rendered like every other chip row so
    the controls exist on paper and without scripts — report.js attaches the
    behaviour and re-renders the tbody from the embedded per-date hour vectors
    (see _usage_payload). The static render IS the "all data" view, so a page
    that runs no script still shows a true heatmap; the period label under the
    heading names what is on screen rather than leaving it implied. Both arrows
    start disabled: at "all data" there is no previous period to step to, and
    an arrow that cannot act must say so rather than do nothing."""
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
    days = sorted(u.get("daily") or {})
    span = ("%s to %s" % (days[0], days[-1])) if days else "every recorded day"
    gran_chips = "".join(
        '<button type="button" class="fchip" data-g="%s" aria-pressed="false">'
        "%s</button>" % (g, label)
        for g, label in (("all", "All"), ("year", "Year"), ("month", "Month"),
                         ("week", "Week"), ("day", "Day")))
    # D2: the PNG export, gated on the per-day payload — report.js redraws the
    # CURRENT view (granularity, period, range) from window.AUDIT_USAGE onto a
    # canvas; without the payload the button would download nothing.
    png_btn = ('<button type="button" class="btn segbtn" data-png="heatmap" '
               'title="Download this heatmap as a PNG image, redrawn from '
               'the data">PNG</button>' if u.get("daily") else "")
    nav = ('<div class="hmnav">'
           '<span id="audit-hm-gran">%s</span>'
           '<button type="button" class="btn btn-icon hmarrow" id="audit-hm-prev" '
           'aria-label="Previous period" disabled>&lsaquo;</button>'
           '<span class="hmperiod" id="audit-hm-period">All data &middot; %s</span>'
           '<button type="button" class="btn btn-icon hmarrow" id="audit-hm-next" '
           'aria-label="Next period" disabled>&rsaquo;</button>'
           "%s</div>" % (gran_chips, e(span), png_btn))
    return ('<h4 class="sub">When the tokens are spent (UTC)</h4>%s'
            '<div class="hmwrap"><table class="hm"><thead><tr>'
            '<th class="hmc"></th>%s</tr>'
            '</thead><tbody id="audit-hm-body">%s</tbody></table></div>'
            '<p class="hmkey">0 %s <span id="audit-hm-peak">%s</span> tokens/hour</p>'
            % (nav, ticks, "".join(rows), key, e(_fmt_tokens(peak))))


def _usage_payload(u):
    """The per-day data layer (C1/C3), embedded as one JSON blob.

    `window.AUDIT_USAGE` = {"min", "max", "days": {date: [tokens, costUSD,
    msgs, [24 hourly token counts]]}} — everything report.js needs to scope
    the time-based views to a date range and to navigate the heatmap by
    calendar period, in a file that has no server to ask. Same embedding
    precedent as `window.AUDIT_MD_B64` in render-report.

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
    head += " · %s msgs · %d session(s) · cache hit %s" % (
        "{:,}".format(t["msgs"]), t["sessions"], _fmt_pct(t["cacheHitPct"]))
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
            # uc (F-P-2): the Markdown twin is read by people too — the same
            # word as the HTML and the CLI, never the storage key.
            cells = [_theme.UNCATEGORIZED if k == "--" else k,
                     _fmt_tokens(v["tokens"])]
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
    # Every rate here is floored through `_fmt_pct`, exactly as its HTML twin is:
    # this table IS the documented relief for the light-mode palette slots, so a
    # `0%` it prints where the page prints `<1%` would make the relief the less
    # honest of the two. Markdown carries the bare `<1%` the way it already
    # carries `_fmt_cost`'s bare `<$0.01`.
    facts = []
    if cache:
        facts.append("- **Cache:** %s hit; the input side bills at %s of "
                     "fresh-token rates."
                     % (_fmt_pct(cache.get("hitPct", 0)),
                        _fmt_pct(cache.get("inputCostVsFreshPct", 100))))
        if cache.get("worstPhase"):
            facts.append("- **Lowest cache phase:** %s at %s."
                         % (_md(cache["worstPhase"][0]),
                            _fmt_pct(cache["worstPhase"][1])))
    if cov:
        facts.append("- **Attribution:** %s of spend attributed (%s to a "
                     "specific task)." % (_fmt_pct(cov.get("attributedPct", 0)),
                                          _fmt_pct(cov.get("taskLevelPct", 0))))
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
        facts.append("- **Retried tasks:** %s across %d task(s) (%s of spend). "
                     "Not the same as wasted spend — the ledger buckets by hour, "
                     "not by attempt."
                     % (_fmt_cost(retry["retriedCost"]), retry["retriedTasks"],
                        _fmt_pct(retry["retriedPct"])))
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
