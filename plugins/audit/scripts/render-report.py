#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py <manifest> [--out-dir DIR] [--format html|md|both|artifact]
                              [--summary-file PATH] [--basename NAME]

  --format artifact writes <basename>.artifact.html: the same report with no
  document wrapper, for a host that supplies its own (a Claude Code Artifact).
  render-report.py --selftest

Writes <basename>.html / <basename>.md into --out-dir (default: the manifest's
own directory) and prints the paths. `basename` is `--basename` › the manifest's
`meta.reportBasename` › `audit-report`, sanitized to [A-Za-z0-9-_].
Exit codes: 0 ok · 2 usage error / unreadable manifest.
"""
import base64
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)
import _ui_theme as _theme   # noqa: E402  (tokens + labels shared with the panel)
import _loader                # noqa: E402  (the one way scripts/ loads a sibling script as a library)
import _fmt                   # noqa: E402  (the one token/cost formatter)
import _report_ui             # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html           # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)


def _plugin_version():
    """The version of the plugin that rendered this file, or '' if unknown.

    A report is a file that outlives the tree it came from: it gets mailed, put in
    a CI artifact, opened next week. When someone says a control does not work,
    the first thing worth knowing is which renderer wrote the page in front of
    them — and until now nothing on the page could answer that. Best-effort by
    construction: a missing or malformed plugin.json costs the stamp, never the
    report.
    """
    try:
        with open(os.path.join(os.path.dirname(_HERE), ".claude-plugin",
                               "plugin.json"), encoding="utf-8") as fh:
            v = json.load(fh).get("version")
        return v if isinstance(v, str) and v.strip() else ""
    except Exception:
        return ""

# Chip and pipeline-rail colors live in the report's CSS theme tokens (see _CSS),
# keyed off the `data-status` / `data-risk` attributes the markup carries — so a
# single token set themes every status/risk consistently in both light and dark.
# Risk chips render only for these levels:
_RISK_LEVELS = _report_html._RISK_LEVELS

_CSS = _report_ui.CSS

# Inline, self-contained (no external fetch) filter/sort/search over the report
# tables. Progressive enhancement: the report is fully readable with JS off.
_SCRIPT = _report_ui.SCRIPT


def _load_status_lib():
    return _loader.load_script("audit-status.py", modname="audit_status",
                                cache=False)


# HTML fragment builders (escaping, chips, cells, filter panel) live in
# _report_html.py (P13.1) — bottom of the report's module graph, imported by
# nothing upward. Aliased here so render_html/render_md and this file's own
# selftest keep referring to these names unchanged.
e = _report_html.e
_safe_url = _report_html._safe_url
_report_basename = _report_html._report_basename
_tasks_by_id = _report_html._tasks_by_id
_areas_of = _report_html._areas_of
_bug_view = _report_html._bug_view
_chip_buttons = _report_html._chip_buttons
_chip = _report_html._chip
_ado_cell = _report_html._ado_cell
_outcome_text = _report_html._outcome_text
_short_date = _report_html._short_date
_timing_cell = _report_html._timing_cell
_filter_attrs = _report_html._filter_attrs
_filter_panel = _report_html._filter_panel
_risk_chip = _report_html._risk_chip
_phase_meta_div = _report_html._phase_meta_div
_bar = _report_html._bar


# The stylesheet lints live beside the stylesheet they police, in _ui_theme,
# so the panel is held to the same rules. Aliased rather than renamed at the
# call sites: these names are what the selftest below asks for by hand.
_undeclared_css_vars = _theme.undeclared_css_vars
_unterminated_css_decls = _theme.unterminated_css_decls
_mangled_css_escapes = _theme.mangled_css_escapes
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme


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


def _ranked(u, key, title, slots=None, models=None):
    """One ranked bar list. Top 8 then a folded `other` row — past 8 entities a
    categorical palette cannot keep adjacent pairs distinguishable, so folding is a
    correctness bound rather than a style choice."""
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
        # The bar is a share the eye reads against its neighbours; the hover adds
        # the exact count and the share of the whole, which the bar cannot show
        # because it is scaled to the largest row, not to the total.
        rows.append(
            '<div class="rank" title="%s"><span class="nm">%s</span>'
            '<span class="track"><i style="width:%.1f%%;background:%s"></i></span>'
            '<span class="amt">%s</span></div>'
            % (_tip(label.strip(), [
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
    cells = []
    for author in shown:
        panels = "".join(
            '<div class="mm"><span class="mk" style="background:%s"></span>'
            '<span class="mn">%s</span>%s</div>'
            % (col, e(model), _spark(grid[author][model], peak, col,
                                     labels, model))
            for model, col in ((m, ("var(--viz-%d)" % slots[m])
                                if m in slots else "var(--bar-neutral)")
                               for m in sorted(grid[author],
                                               key=lambda y: slots.get(y, 99))))
        cells.append('<div class="smcell"><h4>%s</h4>%s</div>'
                     % (e(author), panels))
    more = ('<p class="muted small">+%d more author(s) not shown — the top %d '
            "account for the bulk of spend; use the panel's author filter for the "
            "rest.</p>" % (len(hidden), TOP_N)) if hidden else ""
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

    out.append('<div class="ranks">%s%s%s</div>' % (
        _ranked(u, "byPhase", "By phase"),
        _ranked(u, "byModel", "By model", slots, models),
        _ranked(u, "byAuthor", "By author")))
    out.append(_budget_block(u))

    detail = "".join([
        _small_multiples(u, slots),
        _phase_stacks(u, slots, models),
        _economics_block(u),
        _routing_table(u),
        _usage_heatmap(u),
    ])
    if detail:
        out.append("<details class=\"more\"><summary>Detail — per-author split, "
                   "phase composition, unit economics, model routing, hourly "
                   "pattern</summary>%s</details>" % detail)
    return "".join(out)


def _plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


_GATE_WORDS = {
    "invalid": lambda n: _plural(n, "validator finding"),
    "open-high-bugs": lambda n: _plural(n, "high-severity bug") + " still open",
    "blocked-tasks": lambda n: _plural(n, "blocked task"),
}
# The conditions in the reader's words. `open-high-bugs` is a flag name; printing it
# raw makes the basis look like a config dump and quietly assumes the reader knows
# the CLI. The flag names still appear in the title attribute for whoever is going
# to type them.
_GATE_LABELS = {
    "invalid": "manifest validity",
    "open-high-bugs": "high-severity bugs",
    "blocked-tasks": "blocked tasks",
    "open-bugs": "any open bug",
    "in-progress": "work in progress",
    "over-budget": "phases over budget",
    "budget-80": "phases past 80% of budget",
}


# Columns that exist only when the plan has something to put in them. `id`, `title`
# and `status` are not here: they are never empty, and a table with no status column
# is not this table.
#
# §7 asked for "collapse to four always-visible columns", on the reading that six of
# nine were blank. Measured across three real manifests that turned out to describe
# the PHASE rows (which span the table) rather than the task rows: model and risk are
# 100% filled everywhere, outcome 35-100%, commit and done track completion — and
# only ADO is consistently empty (0%, 0%, 10%), because it exists solely for repos
# that run the Azure DevOps sync. Cutting to a fixed four would have thrown away
# columns that are full for everyone in order to lose one that is empty for most.
#
# So the rule rather than the decree: density follows the data. A plan on day one
# renders id/title/status and little else; a finished one renders all nine; and a
# repo that has never touched Azure DevOps never sees an ADO column at all.
_OPTIONAL_COLS = (
    ("model", lambda t: t.get("model")),
    ("risk", lambda t: t.get("risk")),
    ("commit", lambda t: t.get("commit")),
    ("done", lambda t: t.get("completedAt") or t.get("startedAt")),
    ("ADO", lambda t: (t.get("ado") or {}).get("id")
     if isinstance(t.get("ado"), dict) else None),
    ("outcome", lambda t: _outcome_text(t)),
)


def _present_columns(manifest):
    """The optional columns at least one task actually fills."""
    tasks = [t for p in (manifest.get("phases") or []) if isinstance(p, dict)
             for t in (p.get("tasks") or []) if isinstance(t, dict)]
    out = []
    for name, get in _OPTIONAL_COLS:
        try:
            if any(get(t) not in (None, "", [], {}) for t in tasks):
                out.append(name)
        except Exception:                 # a malformed task never removes a column
            out.append(name)
    return out


def _verdict(summary):
    """The gate's own verdict, not a second opinion composed here.

    Runs `evaluate_gate` with the same DEFAULT_GATE the CI job uses, so the word at
    the top of the report is the word the pipeline would print, and the conditions
    that produced it are named underneath. A hero that scored the plan by a private
    rule would be unverifiable — this one is reproducible with one command.
    """
    lib = _load_status_lib()
    try:
        failed = lib.evaluate_gate(summary, lib.DEFAULT_GATE)
    except Exception:                     # defensive: a hero must never be the crash
        return None, [], []
    counts = {
        "invalid": summary.get("findings") or 0,
        "open-high-bugs": summary["bugs"]["openHighSeverity"],
        "blocked-tasks": summary["tasks"]["byStatus"].get("blocked", 0),
    }
    why = [_GATE_WORDS[c](counts[c]) for c in failed if c in _GATE_WORDS]
    return ("blocked" if failed else "clear"), why, list(lib.DEFAULT_GATE)


def _held_by(ph, done_ids):
    """Which of this phase's `blockedBy` targets are not done yet.

    The manifest has carried this since v0.1.0 and the report has never drawn it:
    a reader could see that a phase was pending but not that another phase was the
    reason. It is also what actually decides what you can work on next."""
    out = []
    for b in ph.get("blockedBy") or []:
        if isinstance(b, str) and b not in done_ids:
            out.append(b)
    return out


def render_html(manifest, summary, basename="audit-report", usage=None,
                fragment=False):
    """The HTML report. `fragment=True` emits it for an embedding host.

    A Claude Code Artifact wraps what it is given in its own
    `<!doctype>…<head>…</head><body>`, so a standalone document published as one
    nests a second `<html>` inside the first. The fragment carries no document
    wrapper — but it keeps `<title>` (the host reads it to name the page) and the
    whole `<style>`, which already does what an embedded page needs: it declares
    `color-scheme:light dark` for the reader who has chosen nothing and restates it
    under each `:root[data-theme]` so a chosen theme takes the native controls with
    it, honours both `prefers-color-scheme` and that attribute for colour, and
    scrolls its wide tables inside `.tablewrap` instead of the page.

    Nothing here is fetched from a network, in either mode. That was true before
    this flag existed — it is why the report can be embedded at all under a CSP
    that blocks every external host.
    """
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    # doctype + charset so the file renders standalone (not quirks mode) and its
    # UTF-8 punctuation (·, —, …) decodes correctly when opened from disk.
    out = [] if fragment else [
        '<!doctype html>',
        # `lang` is why this element is emitted at all: without it a screen
        # reader guesses the language and can read the whole report in the wrong
        # voice. The control panel has always declared one; the report did not.
        '<html lang="en">',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">']
    out += ['<title>%s</title>' % e(meta.get("title") or "Audit report"),
            "<style>%s</style>" % _CSS]
    # The shell. `sections` is the ONE list both the nav and the content are drawn
    # from — a hand-kept nav beside hand-placed anchors is the same trap as the
    # hand-maintained selftest list that drifted three ways: adding a section and
    # remembering to link it would be two separate acts, and only one of them shows.
    sections = []

    def section(anchor, label, count=None, sub=False):
        sections.append((anchor, label, count, sub))
        return anchor

    # Say so when the script did not run. This report is a static file people are
    # meant to SEND each other, and a very common way of opening one — an IDE's
    # HTML preview pane — sandboxes inline <script>. The page then renders
    # completely and looks finished, while filtering, search and every expandable
    # phase silently do nothing. Reported as "the report is broken", and it took
    # two browsers, two origins, five viewports and real mouse input to establish
    # that the report was fine and the viewer was not.
    #
    # Written into the HTML rather than a <noscript>: the failure is not only "JS
    # disabled" — a sandbox can leave scripts enabled but strip inline ones, which
    # <noscript> does not catch. The script's first act is to remove this, so it is
    # visible exactly when it is true, and its absence is itself a live proof that
    # the script ran (the CI interactivity check asserts that).
    out.append(
        '<div id="audit-nojs" class="nojs" role="status">'
        "<strong>This report is interactive, and its scripts are not running here.</strong> "
        "Filtering, search, sorting and expanding a phase all need them. "
        "An IDE preview pane usually blocks inline scripts — "
        "open this file in a real browser and it will work.</div>")

    _ver = _plugin_version()
    out.append('<header class="topbar"><div class="tb-id">'
               '<h1>%s</h1><p class="meta">%s · %d phases · %d tasks · %d bugs · '
               "generated %s%s</p></div>"
               % (e(meta.get("title") or "Audit report"),
                  e(meta.get("repo") or "?"), len(summary["phases"]),
                  summary["tasks"]["total"], summary["bugs"]["total"], now,
                  (' · <span class="stampv" title="The plugin version that '
                   'rendered this file">audit %s</span>' % e(_ver)) if _ver else ""))
    out.append("@@TOOLBAR@@</header>")
    out.append('<div class="shell">@@NAV@@<main class="content">')
    if not summary["valid"]:
        out.append('<p><strong class="invalid">INVALID MANIFEST: %d '
                   "validator finding(s) — fix before trusting this report."
                   "</strong></p>" % summary["findings"])

    # The verdict hero. The old band led with the word "Overall" and a bar — true,
    # but it answered "how far along" when the reader's question is "can I ship".
    tdone = sum(p["done"] for p in summary["phases"])
    ttotal = summary["tasks"]["total"]
    phdone = sum(1 for p in summary["phases"] if p["status"] == "done")
    gate, why, conds = _verdict(summary)
    ready = summary["ready"]
    if ready:
        # The most actionable string on the page. It used to sit at the bottom in
        # small monospace with no affordance; it is now the one thing in the hero
        # you can act on, and it is copyable because reading an id off a screen and
        # retyping it is a transcription error waiting to happen.
        nxt = ('<span class="tbl">Next</span> <code class="vd-run">/audit:run %s</code>'
               '<button type="button" class="btn btn-copy" data-copy="/audit:run %s">'
               "Copy</button>" % (e(ready[0]), e(ready[0])))
        if len(ready) > 1:
            nxt += ('<span class="muted">%d more ready</span>'
                    % (len(ready) - 1))
    elif ttotal and tdone == ttotal:
        nxt = '<span class="muted">Nothing left to run — every task is done.</span>'
    else:
        nxt = ('<span class="muted">Nothing ready — every remaining task is '
               "waiting on something.</span>")
    out.append('<div class="topgrid">')
    out.append(
        '<section class="overall" id="%s"%s aria-label="Gate verdict">'
        '<p class="vd-eyebrow">Gate</p>'
        '<p class="vd-word">%s</p><p class="vd-why">%s</p>'
        '<p class="vd-basis">%s</p>'
        '<div class="vd-next">%s</div>'
        '<div class="vd-stats">%s<span class="muted">%s · '
        "%d of %d phases signed off · %s</span></div></section>"
        % (section("gate", "Gate", None),
           (' data-gate="%s"' % gate) if gate else "",
           e({"clear": "Clear", "blocked": "Blocked"}.get(gate, "Unknown")),
           e(" · ".join(why)) if why
           else ("No blocking condition." if gate == "clear"
                 else "The gate could not be evaluated."),
           # The conditions are printed, not implied. A verdict whose criteria are
           # invisible is a score, and the reader cannot tell whether it covers the
           # thing they care about — spend, for instance, is deliberately NOT here.
           ('<span title="audit-status.py --gate --fail-on %s">Checks %s. '
            "Spend is deliberately not one of them.</span>"
            % (e(",".join(conds)),
               e(", ".join(_GATE_LABELS.get(c, c) for c in conds)))) if conds else "",
           nxt, _bar(tdone, ttotal), _plural(tdone, "task") + " done",
           phdone, len(summary["phases"]),
           _plural(summary["bugs"]["open"], "open bug")))

    # AI-authored narrative summary (written by /audit:report into
    # meta.reportSummary); the quantitative "Overall" line above is the
    # always-present deterministic fallback. Escaped — treated as untrusted.
    rsum = meta.get("reportSummary")
    if isinstance(rsum, str) and rsum.strip():
        out.append('<div class="summary"><strong>Summary</strong>%s</div>'
                   % e(rsum.strip()))
    out.append("</div>")   # close .topgrid

    # Controls are split by WHAT THEY ACT ON, which is the same rule that put
    # navigation at the side and actions on top. Save-as-PDF, the markdown twin and
    # the theme act on the document, so they live in the persistent bar. Search,
    # the status chips and expand-all act on the phases table and nothing else — in
    # the top bar they were three rows of chrome following the reader through the
    # usage charts, where they do nothing at all. They now sit on the table they
    # drive. Enhanced by _SCRIPT; with JS off both tables are still fully readable.
    doc_actions = (
        '<div class="toolbar tb-actions">'
        '<button type="button" id="audit-print" class="btn btn-primary" '
        'title="Print / Save as PDF — the whole plan, every phase expanded. '
        'Paper size and orientation are yours to pick in the print dialog.">'
        'Save as PDF</button>'
        '<button type="button" id="audit-dl-md" class="btn">Download .md</button>'
        # Withheld in a fragment: the host owns the theme there and stamps
        # `data-theme` on the same root element this button writes. Two controls
        # over one attribute is not a redundancy, it is a race — and the report
        # would lose it, since it restores its own persisted value on load and
        # would flip a viewer who had picked dark back to a light report saved on
        # some earlier visit. One toggle, owned by whoever owns the page.
        + ('' if fragment else
           '<button type="button" id="audit-theme" class="btn btn-icon" '
           'aria-label="Toggle light/dark theme" title="Toggle light/dark theme">'
           '\u263e</button>')
        + '</div>')
    # The chips are rendered HERE, not built by the script. Built in JS they were
    # invisible to anything that does not run it \u2014 a printed page, a reader with
    # scripting off \u2014 which is the one context where "the filters are gone" is
    # indistinguishable from "the filters are broken". Server-rendered they are
    # always present; the script only attaches behaviour to them.
    _phase_statuses = sorted({p["status"] for p in summary["phases"] if p.get("status")})
    table_tools = (
        '<div class="toolbar sectools" role="search" aria-label="Filter the phases table">'
        '<input id="audit-q" type="search" aria-label="Filter phases and tasks by text" '
        'placeholder="Filter phases &amp; tasks by text\u2026">'
        '<span class="tbl">Phase status:</span><span id="audit-phase-status">%s</span>'
        '%s'
        '<button type="button" id="audit-expand" class="btn">expand all</button>'
        # Shown only while something is actually filtering. It is a second copy of
        # the empty state's button on purpose: the More-filters panel is drawn OVER
        # the top of the table, so when a filter leaves no rows at all, the empty
        # state — and the only way back from it — ends up underneath the very panel
        # that caused it. A browser click found that; no string check could.
        '<button type="button" class="btn" data-clear hidden>Clear filters</button>'
        '<span id="audit-count" class="muted"></span>'
        "<noscript><span class=\"tbl\">Filtering and collapsing need JavaScript "
        "\u2014 every row is shown.</span></noscript></div>"
        % (_chip_buttons(_phase_statuses, "data-ps", "fchip"),
           _filter_panel(manifest)))

    # One collapsible table: each phase is a group-row (click to expand its task
    # rows). Default-collapsed via _SCRIPT; with JS off every row is visible.
    out.append('<section id="%s" class="sec">' % section("phases", "Phases",
                                                        len(summary["phases"])))
    out.append(table_tools)
    cols = _present_columns(manifest)
    ncol = 3 + len(cols)
    out.append('<div class="tablewrap"><table class="phases"><thead><tr>'
               "<th>id</th><th>title</th><th>status</th>%s</tr></thead><tbody>"
               % "".join("<th>%s</th>" % e(c) for c in cols))
    _done_ids = {p["id"] for p in summary["phases"] if p["status"] == "done"}
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        pid = psum["id"]
        areas = psum["area"] if isinstance(psum.get("area"), list) else _areas_of(ph.get("area"))
        area_tags = "".join(' <span class="area-tag">%s</span>' % e(a) for a in areas)
        held = _held_by(ph, _done_ids)
        # The gate closes only where something actually holds it. A phase that is
        # merely pending is an OPEN gate nobody has walked through yet, and drawing
        # those the same way would make the rail a restatement of status rather
        # than a drawing of dependency.
        held_mark = "".join(
            '<a class="heldby" href="#phase-%s" title="This phase is held until %s '
            'is done">held by %s</a>' % (e(h), e(h), e(h)) for h in held)
        # The stamp on a signed-off phase: the last commit recorded inside it. The
        # manifest has no separate sign-off SHA, so this is labelled as what it is
        # rather than presented as a signature it is not.
        stamp = ""
        if psum["status"] == "done":
            shas = [t.get("commit") for t in (ph.get("tasks") or [])
                    if isinstance(t, dict) and isinstance(t.get("commit"), str)
                    and t["commit"].strip()]
            if shas:
                stamp = ('<span class="stamp" title="Last commit recorded in this '
                         'phase">%s</span>' % e(shas[-1][:7]))
        out.append(
            '<tr class="phase" id="phase-%s" data-phase="%s" data-status="%s"%s '
            'data-area="%s" tabindex="0" '
            'aria-expanded="false"><td colspan="%d"><span class="tri"></span> '
            '<span class="mono">%s</span> <strong>%s</strong>%s %s%s%s %s'
            '<span class="pmatch" hidden></span>%s</td></tr>'
            % (e(pid), e(pid), e(psum["status"]),
               ' data-held="1"' if held else "",
               e(" ".join(areas)), ncol, e(pid), e(psum["title"]),
               area_tags, _chip(psum["status"]), held_mark, stamp,
               _bar(psum["done"], psum["total"]), _phase_meta_div(ph)))
        # per-phase task-status filter (shown only when the phase is expanded);
        # _SCRIPT fills .tf-chips from this phase's own task statuses.
        _tstat = sorted({t.get("status") for t in (ph.get("tasks") or [])
                         if isinstance(t, dict) and t.get("status")})
        out.append('<tr class="taskfilter" data-phase="%s"><td colspan="%d">'
                   '<span class="tf-label">Filter tasks by status:</span>'
                   '<span class="tf-chips">%s</span></td></tr>'
                   % (e(pid), ncol, _chip_buttons(_tstat, "data-ts", "tf-chip")))
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            cells = {
                "model": lambda: "<td>%s</td>" % e(t.get("model") or "—"),
                "risk": lambda: "<td>%s</td>" % _risk_chip(t.get("risk")),
                "commit": lambda: "<td class=mono>%s</td>"
                % e((t.get("commit") or "—")[:9]),
                "done": lambda: "<td class=when>%s</td>" % _timing_cell(t),
                "ADO": lambda: "<td>%s</td>" % _ado_cell(t),
                "outcome": lambda: "<td class=muted>%s</td>" % e(_outcome_text(t)),
            }
            out.append(
                '<tr class="task" data-phase="%s" data-status="%s"%s%s>'
                '<td class="mono tid">%s</td><td>%s</td><td>%s</td>%s</tr>'
                % (e(pid), e(t.get("status")),
                   ' data-held="1"' if held else "",
                   _filter_attrs(t),
                   e(t.get("id")), e(t.get("title")),
                   _chip(t.get("status")),
                   "".join(cells[c]() for c in cols)))
    # Its own <tbody>, so `tbody tr:last-child` keeps meaning the last DATA row —
    # the table's rounded bottom corner and its missing final rule both hang off
    # that selector, and a permanently-present hidden row in the main body would
    # have quietly taken both.
    out.append('</tbody><tbody><tr class="norows"><td colspan="%d">'
               "No phase matches these filters."
               '<button type="button" class="btn" data-clear>Clear filters'
               "</button></td></tr></tbody></table></div></section>" % ncol)

    # Usage is the longest section by far — a chart, five tiles, three ranked
    # lists, a budget block, economics and a heatmap — so its own headings become
    # sub-items. A nav that stops at the section a reader is already inside stops
    # helping exactly where the scrolling gets long.
    _usage_html = _usage_section(usage)
    if _usage_html:
        section("usage", "Usage", None)
        for _label, _anchor in (("Tokens per day", "usage-trend"),
                                ("Budget", "usage-budget")):
            _tag = '<h3 class="sub">%s</h3>' % _label
            if _tag in _usage_html:
                _usage_html = _usage_html.replace(
                    _tag, '<h3 class="sub" id="%s">%s</h3>' % (_anchor, _label), 1)
                section(_anchor, _label, None, sub=True)
    out.append(_usage_html)

    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        task_by_id = _tasks_by_id(manifest)
        out.append('<h2 id="%s">Bugs</h2>'
                   % section("bugs", "Bugs", summary["bugs"]["open"] or None))
        rows = []
        for b in bugs:
            bstatus, bfixed = _bug_view(b, task_by_id)
            rows.append(
                '<tr data-status="%s"><td class=mono>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                "<td class=mono>%s</td><td class=mono>%s</td><td>%s</td></tr>"
                % (e(bstatus), e(b.get("id")), e(b.get("title")),
                   _chip(bstatus),
                   e(b.get("severity") or "—"), e(b.get("taskId") or "—"),
                   e(bfixed[:9]), _ado_cell(b)))
        out.append('<div class="tablewrap"><table class="data bugs"><thead><tr>'
                   "<th>id</th><th>title</th>"
                   "<th>status</th><th>severity</th><th>task</th><th>fixedIn</th>"
                   "<th>ADO</th></tr></thead><tbody>%s</tbody></table></div>"
                   % "".join(rows))

    if summary["ready"]:
        out.append('<h2 id="%s">Ready now</h2><p class=mono>%s</p>'
                   % (section("ready", "Ready now", len(summary["ready"])),
                      ", ".join(e(r) for r in summary["ready"])))
    out.append("</main></div>")   # close .content and .shell

    # Embed the Markdown twin as base64 so the "Download .md" button works from a
    # standalone file. base64 (not raw text) keeps any manifest HTML/`</script>`
    # out of the page and preserves UTF-8 exactly.
    md_b64 = base64.b64encode(
        render_md(manifest, summary, usage).encode("utf-8")).decode("ascii")
    # basename is sanitized to [A-Za-z0-9-_], so it is safe in a JS string literal.
    out.append('<script>window.AUDIT_MD_B64="%s";window.AUDIT_MD_NAME="%s.md";</script>'
               % (md_b64, basename))
    out.append(_SCRIPT)
    if not fragment:
        out.append("</html>")

    # The nav is emitted from `sections`, the same list the anchors were written
    # from, so it cannot list a section that is not there or miss one that is. It
    # is rendered server-side rather than built by the script: with JS off this
    # report still has to be a whole document, and a nav that only exists once
    # JavaScript runs is a nav that is missing from every PDF and every reader
    # with scripting disabled. The script adds scroll-spy on top; it does not
    # supply the links.
    nav = ""
    if sections:
        items = "".join(
            '<li class="%s"><a href="#%s">%s%s</a></li>'
            % ("sub-item" if sub else "item", e(anchor), e(label),
               ('<span class="n">%d</span>' % count) if count else "")
            for anchor, label, count, sub in sections)
        nav = ('<nav class="snav" aria-label="Report sections">'
               '<p class="snav-title">Contents</p><ol>%s</ol></nav>' % items)
    body = "\n".join(out) + "\n"
    return body.replace("@@NAV@@", nav).replace("@@TOOLBAR@@", doc_actions)


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


def render_md(manifest, summary, usage=None):
    """Markdown twin of render_html. Only Markdown metacharacters (pipes,
    newlines) are escaped here — raw HTML inside manifest strings is passed
    through and relies on the Markdown renderer (e.g. GitHub) to sanitise it.
    render_html is the hardened, self-contained output; prefer it when the
    source is untrusted and no sanitising renderer sits in front."""
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    def cell(v):
        return str(v if v is not None else "—").replace("|", "\\|").replace(
            "\n", " ")

    out = ["# %s" % cell(meta.get("title") or "Audit report"), "",
           "repo: %s · generated %s" % (cell(meta.get("repo") or "?"), now), ""]
    rsum = meta.get("reportSummary")
    if isinstance(rsum, str) and rsum.strip():
        out += ["> " + cell(rsum.strip()), ""]
    if not summary["valid"]:
        out += ["**INVALID MANIFEST: %d validator finding(s).**" % summary["findings"], ""]
    tdone = sum(p["done"] for p in summary["phases"])
    phdone = sum(1 for p in summary["phases"] if p["status"] == "done")
    out += ["**Overall:** %d/%d tasks done · %d/%d phases signed off · %d open bug(s) · %d ready now"
            % (tdone, summary["tasks"]["total"], phdone, len(summary["phases"]),
               summary["bugs"]["open"], len(summary["ready"])), ""]
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        out.append("## %s — %s (%s, %d/%d)"
                   % (cell(psum["id"]), cell(psum["title"]),
                      cell(psum["status"]), psum["done"], psum["total"]))
        if ph.get("desiredOutcome"):
            out.append("_%s_" % cell(ph["desiredOutcome"]))
        out += ["", "| id | title | status | model | risk | commit | done | ADO |",
                "|---|---|---|---|---|---|---|---|"]
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            ado = t.get("ado") if isinstance(t.get("ado"), dict) else None
            ado_txt = "#%s" % ado["id"] if ado and ado.get("id") is not None else "—"
            done_txt = _short_date(t.get("completedAt")) or (
                "started " + _short_date(t.get("startedAt")) if t.get("startedAt") else "—")
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                cell(t.get("id")), cell(t.get("title")), cell(t.get("status")),
                cell(t.get("model") or "—"), cell(t.get("risk") or "—"),
                cell((t.get("commit") or "—")[:9]), cell(done_txt), cell(ado_txt)))
        out.append("")
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        task_by_id = _tasks_by_id(manifest)
        out += ["## Bugs", "",
                "| id | title | status | severity | task | fixedIn |",
                "|---|---|---|---|---|---|"]
        for b in bugs:
            bstatus, bfixed = _bug_view(b, task_by_id)
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(b.get("id")), cell(b.get("title")), cell(bstatus),
                cell(b.get("severity") or "—"), cell(b.get("taskId") or "—"),
                cell(bfixed[:9])))
        out.append("")
    if summary["ready"]:
        out += ["## Ready now", "", ", ".join(cell(r) for r in summary["ready"]), ""]
    usage_md = _usage_md(usage)
    if usage_md:
        out.append(usage_md)
    return "\n".join(out)


def main(argv):
    args = list(argv)
    out_dir = None
    fmt = "both"
    summary_file = None
    cli_basename = None
    for flag in ("--out-dir", "--format", "--summary-file", "--basename"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.stderr.write("usage: %s needs a value\n" % flag)
                return 2
            val = args[i + 1]
            if flag == "--out-dir":
                out_dir = val
            elif flag == "--format":
                fmt = val
            elif flag == "--summary-file":
                summary_file = val
            else:
                cli_basename = val
            del args[i:i + 2]
    if fmt not in ("html", "md", "both", "artifact") or len(args) != 1:
        sys.stderr.write("usage: render-report.py <manifest> [--out-dir DIR] "
                         "[--format html|md|both|artifact] [--summary-file PATH] "
                         "[--basename NAME]\n")
        return 2

    manifest_path = args[0]
    try:
        manifest = _mio.load_manifest(manifest_path)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (manifest_path, type(manifest).__name__))
        return 2

    # --summary-file lets /audit:report pass an AI-authored narrative summary
    # WITHOUT mutating the manifest (the command stays read-only). It is injected
    # into the in-memory manifest's meta.reportSummary; the file is never rewritten.
    if summary_file:
        try:
            with open(summary_file, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                meta = manifest.get("meta")
                if not isinstance(meta, dict):
                    meta = manifest["meta"] = {}
                meta["reportSummary"] = text
        except Exception as exc:
            sys.stderr.write("WARNING: could not read --summary-file %s: %s\n"
                             % (summary_file, exc))

    lib = _load_status_lib()
    vm = lib._load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []
    summary = lib.rollup(manifest, findings, warnings)
    usage = load_usage(manifest, manifest_path)

    basename = _report_basename(manifest.get("meta"), cli_basename)
    out_dir = out_dir or (os.path.dirname(os.path.abspath(manifest_path)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if fmt in ("html", "both"):
        p = os.path.join(out_dir, basename + ".html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary, basename, usage))
        written.append(p)
    if fmt == "artifact":
        # A separate name, never the .html one. The standalone file is what people
        # open from disk and what CI diffs the live demo against; overwriting it
        # with a fragment would leave both looking fine and one of them broken.
        p = os.path.join(out_dir, basename + ".artifact.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary, basename, usage,
                                 fragment=True))
        written.append(p)
    if fmt in ("md", "both"):
        p = os.path.join(out_dir, basename + ".md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_md(manifest, summary, usage))
        written.append(p)
    for p in written:
        print("wrote %s" % p)
    return 0


# --- selftest -------------------------------------------------------------------
def _selftest():
    import tempfile

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    evil_title = "<script>alert(1)</script>"
    manifest = {
        "meta": {"version": 2, "title": evil_title, "repo": "r",
                 "reportSummary": "closed all criticals & shipped v0.5.0"},
        "phases": [
            {"id": "P1", "title": "Phase & <b>bold</b>", "status": "in_progress",
             "desiredOutcome": "Outcome with <img src=x onerror=alert(1)>",
             "branch": "audit/p1-x", "mergedAt": "2026-07-09T00:00:00Z",
             "tasks": [
                 {"id": "P1.1", "title": "done task", "status": "done",
                  "commit": "abcdef1234567", "files": ["src/a.ts"], "risk": "high",
                  "model": "sonnet",
                  "startedAt": "2026-07-09T08:00:00Z",
                  "completedAt": "2026-07-09T09:30:00Z",
                  "outcome": {"descriptive": "did the thing cleanly"},
                  "ado": {"id": 42, "url": "https://dev.azure.com/o/p/_workitems/edit/42"}},
                 # A SECOND model, so the filter has something to choose between:
                 # one model renders one chip, and a set of one cannot tell a
                 # working filter from a filter that always matches.
                 {"id": "P1.2", "title": "evil url", "status": "pending",
                  "model": "opus",
                  "ado": {"id": 7, "url": "javascript:alert(1)"}},
             ]},
        ],
        "fileIndex": {"src/a.ts": ["P1.1"]},
        "bugs": [{"id": "BUG-1", "title": "a|bug", "status": "open",
                  "severity": "high"}],
    }

    tmp = tempfile.mkdtemp(prefix="render-report-selftest-")
    mp = os.path.join(tmp, "m.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)

    rc = main([mp, "--out-dir", tmp])
    check("c1 CLI exits 0", rc == 0)
    hp, dp = os.path.join(tmp, "audit-report.html"), os.path.join(tmp, "audit-report.md")
    check("c2 both artifacts exist and are non-empty",
          os.path.getsize(hp) > 0 and os.path.getsize(dp) > 0)

    html_out = open(hp, encoding="utf-8").read()
    md_out = open(dp, encoding="utf-8").read()

    check("x1 script tag escaped", "<script>alert" not in html_out
          and "&lt;script&gt;" in html_out)
    check("x2 attribute injection escaped", "onerror=alert" not in html_out
          or "&lt;img" in html_out)
    check("x3 javascript: url NOT a link",
          'href="javascript:' not in html_out)
    check("x4 https ado url IS a link",
          'href="https://dev.azure.com/o/p/_workitems/edit/42"' in html_out)
    # exclude the ADO link and the opaque embedded-markdown blob (data, not a fetch)
    _marker = 'window.AUDIT_MD_B64="'
    _s = html_out
    if _marker in _s:
        _i = _s.index(_marker)
        _j = _s.index('"', _i + len(_marker))
        _s = _s[:_i] + _s[_j:]
    _s = _s.replace('href="https://dev.azure.com/o/p/_workitems/edit/42"', "")
    check("x5 zero external fetches (ado link + embedded md blob excluded)",
          "http" not in _s)
    # --- usage section ---------------------------------------------------------
    check("u1 no ledger -> no Usage section at all (back-compat)",
          'id="usage"' not in html_out and "## Usage" not in md_out)
    _u = {
        "totals": {"tokens": 1_500_000, "in": 1000, "out": 200_000,
                   "cacheW5m": 100_000, "cacheW1h": 0, "cacheR": 1_199_000,
                   "msgs": 42, "costUSD": 12.3456, "sessions": 3, "authors": 2,
                   "models": 2, "tasks": 4, "phases": 2, "cacheHitPct": 79.9},
        "byPhase": {"P1": {"tokens": 1_000_000, "costUSD": 8.0, "msgs": 30},
                    "--": {"tokens": 500_000, "costUSD": 4.3456, "msgs": 12}},
        "byModel": {"claude-opus-5": {"tokens": 900_000, "costUSD": 9.0, "msgs": 20},
                    "claude-haiku-4-5": {"tokens": 600_000, "costUSD": 3.3, "msgs": 22}},
        "byAuthor": {"a@x.io": {"tokens": 1_000_000, "costUSD": 8.0, "msgs": 30},
                     "b@x.io": {"tokens": 500_000, "costUSD": 4.3, "msgs": 12}},
        "byAgent": {}, "phaseTitles": {"P1": "Alpha"},
        "phaseModel": {"P1": {"claude-opus-5": 900_000, "claude-haiku-4-5": 100_000},
                       "--": {"claude-haiku-4-5": 500_000}},
        "daily": {"2026-08-01": 900_000, "2026-08-02": 600_000},
        "heatmap": [[0] * 24 for _ in range(7)],
        "showCost": True, "pricingAsOf": "2026-08-06",
        "counts": {"phases": 2, "people": 2, "models": 2, "sessions": 3,
                   "days": 2, "from": "2026-08-01", "to": "2026-08-02"},
    }
    _u["heatmap"][2][14] = 900_000
    _u["heatmap"][4][9] = 600_000
    _lib = _load_status_lib()
    _sum = _lib.rollup(manifest, [], [])
    uh = render_html(manifest, _sum, "audit-report", _u)
    um = render_md(manifest, _sum, _u)
    check("u2 Usage section renders when a ledger exists", 'id="usage"' in uh)
    check("u3 stat tiles carry compacted totals and equivalent cost",
          "1.5M" in uh and "$12.35" in uh and "equivalent cost" in uh)
    # This case read `"2026-08-06" in uh` for four releases and asserted nothing:
    # render_html stamps `generated <today>`, so on the day it was written the
    # report's own timestamp satisfied it. It failed for the first time when the
    # clock rolled to the 7th — and what it uncovered was real. HTML surfaced
    # pricingAsOf ONLY through the >90-day stale notice, so the ordinary report
    # showed dollars with no way to see what priced them, while the Markdown twin
    # printed it every time. Assert the PHRASE, which no timestamp can produce.
    check("u4 pricingAsOf surfaced in HTML, not only once the table has gone stale",
          "rates as of 2026-08-06" in uh)
    check("u4b the Markdown twin says the same thing",
          "rates as of 2026-08-06" in um)
    check("u4c and the date is not merely today's generation stamp "
          "(the trap this case sat in)",
          "rates as of %s" % time.strftime("%Y-%m-%d", time.gmtime()) not in uh)
    _uq = dict(_u, showCost=False)
    _hq, _mq = (render_html(manifest, _sum, "audit-report", _uq),
                render_md(manifest, _sum, _uq))
    check("u4d withheld when showCost is off, in both renderers - with no dollars "
          "on screen it dates a table nothing visible came from",
          "rates as of" not in _hq and "rates as of" not in _mq
          and "rates undated" not in _hq and "rates undated" not in _mq)
    # Costs shown with no date declared. The default price table HAS a pricingAsOf,
    # so a fallback would nearly always render a plausible date - which is why there
    # is none. The ledger stores costUSD priced at write time and no rate vintage,
    # so the report genuinely does not know it, and printing the default's date
    # would manufacture a basis instead of stating one.
    _un = dict(_u); _un.pop("pricingAsOf", None)
    _hn, _mn = (render_html(manifest, _sum, "audit-report", _un),
                render_md(manifest, _sum, _un))
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
    check("u8 stacked segments are emitted in slot order (validated adjacency)",
          uh.index("var(--viz-1)") < uh.index("var(--viz-2)"))
    check("u9 daily column chart and heatmap render",
          'class="cols"' in uh and 'class="hm"' in uh)
    check("u10 heatmap opts out of the sticky thead used by the phases table",
          ".hm thead th{position:static" in uh)
    # A closed <details> clips its children in print media regardless of CSS, so
    # the PDF silently loses the detail block without this. Verified in-browser.
    check("u10b the disclosure is force-opened for printing, not just CSS-hinted",
          "beforeprint" in uh and "afterprint" in uh)
    check("u11 every chart mark carries a title for hover/AT",
          uh.count("<title>") >= 2 and 'role="img"' in uh)
    check("u12 md twin carries the usage table (the contrast relief)",
          "## Usage" in um and "### By phase" in um and "### By model" in um)
    check("u13 md twin lists authors only when there is more than one",
          "### By author" in um)
    # The whole-page fetch count is pinned by x5; this narrows it to the section,
    # since the fixture manifest legitimately carries an https ADO link.
    check("u14 the usage section itself adds no external fetch",
          "http" not in _usage_section(_u))
    # Check the rendered ARTIFACT, not just the stylesheet: inline styles emitted
    # from Python land only in the output, and that is exactly where an undeclared
    # token hides.
    _missing = _undeclared_css_vars(_CSS + uh)
    check("u14b every fallback-less var(--token) is declared "
          "(an undeclared one paints transparent and logs nothing)",
          _missing == [], repr(_missing))
    _asym = _theme_asymmetric_vars(_CSS)
    check("u14c no colour token exists in only one theme (either direction)",
          _asym == [], repr(_asym))
    # Tokens paint our boxes; the UA paints the checkboxes, selects, spinners,
    # date picker and scrollbars from `color-scheme` alone. A theme that does not
    # restate it leaves those wearing the OS's theme while everything around them
    # follows the toggle — invisible in the stylesheet, obvious on screen.
    _nocs = _themes_missing_color_scheme(_CSS)
    check("u14i every explicit data-theme restates color-scheme, so the toggle "
          "moves the native controls with it", _nocs == [], repr(_nocs))
    # This stylesheet lives in a non-raw Python string, so every CSS escape has to
    # be written twice over. `content:"\2713\a0"` compiled to `¹3<BEL>0` and drew
    # exactly that on the one chip whose whole job was to state its own state
    # without colour — for as long as that chip has existed, with the suite green.
    _esc = _mangled_css_escapes(_CSS)
    check("u14j no CSS escape was eaten by Python before the browser saw it",
          _esc == [], repr(_esc))
    # A missing `;` after a custom property annexes the comment and declarations
    # that follow it. Silent, and it killed every animation in this stylesheet once.
    _unterm = _unterminated_css_decls(_CSS)
    check("u14d no custom-property declaration runs past its line without a ';' "
          "(it would annex whatever follows)", _unterm == [], repr(_unterm))
    check("u14e the annexing case is detected",
          _unterminated_css_decls(
              ":root{\n  --ease:linear\n  /* c */\n  --sp-0:.25rem;\n}") != [])
    check("u14f the last declaration in a block may legally omit its ';'",
          _unterminated_css_decls(":root{\n  --a:1px;\n  --b:2px\n}") == [])
    check("u14g --ease resolves to a single value (its shorthand users depend on it)",
          re.search(r"--ease:\s*cubic-bezier\([^)]*\);", _CSS) is not None)
    check("u14h --sp-0 survives as its own declaration",
          re.search(r"--sp-0:\s*\.25rem", _CSS) is not None)
    # The progress fill is a <span>. Inline boxes ignore width and height, so without
    # an explicit display the bar paints as an empty track at every percentage —
    # which is what shipped from the redesign until it was caught by a capture.
    check("u14i the progress fill declares a non-inline display "
          "(a <span> would otherwise ignore its width)",
          re.search(r"\.fill\{[^}]*display:\s*block", _CSS) is not None)
    # A reveal animation with only a `from` keyframe leaves its end state to be
    # synthesised, and `fill-mode:both` can then hold the element at the from-state.
    for _kf in ("fillIn", "fadeUp"):
        _body = re.search(r"@keyframes %s\{([^}]*\}[^}]*)\}" % _kf, _CSS)
        check("u14k %s declares both endpoints (from AND to)" % _kf,
              _body is not None and "to{" in _body.group(1), _kf)

    # --- accessibility of the interactive layer --------------------------------
    # Each of these shipped broken: the report is the product's most public artifact
    # and its controls were mouse-and-sighted-only.
    check("a1 the document declares a language "
          "(without it a screen reader guesses, and may read the whole report "
          "in the wrong voice)",
          '<html lang="en">' in html_out)
    check("a2 the document element is closed", html_out.rstrip().endswith("</html>"))

    # --- the gate rail (signature) --------------------------------------------
    # A phase row's class stays exactly `phase` whatever the gate is doing. The
    # first version carried held-ness in the class (`class="phase held"`), which
    # silently broke CI's `grep -c 'tr class="phase"'` on the scale demo — 37 of 40
    # phases counted, because three were held. Gate state is derived state and
    # belongs with `data-status`, not in the identity of the row.
    check("rail: a phase row is class=phase whatever its gate state, so counting "
          "phase rows cannot depend on the plan's shape",
          html_out.count('<tr class="phase"') == len(_sum["phases"]))
    # A purpose-built chain rather than the main fixture: A done, B blocked by A
    # (satisfied), C blocked by B (not). That is the whole point of the rail in
    # three phases — one gate that opened, one that has not.
    _rm = {"meta": {"title": "rail"}, "bugs": [], "phases": [
        {"id": "A", "title": "First", "status": "done",
         "tasks": [{"id": "A.1", "title": "t", "status": "done",
                    "commit": "abc1234def"}]},
        {"id": "B", "title": "Second", "status": "pending", "blockedBy": ["A"],
         "tasks": [{"id": "B.1", "title": "t", "status": "pending"}]},
        {"id": "C", "title": "Third", "status": "pending", "blockedBy": ["B"],
         "tasks": [{"id": "C.1", "title": "t", "status": "pending"}]}]}
    _rh = render_html(_rm, _load_status_lib().rollup(_rm, [], []), "r", None)
    check("rail: a held phase is marked with data-held, beside data-status",
          _rh.count('data-held="1"') == 2)   # phase C and its one task
    check("rail: it names what holds it, and links there - a closed gate with no "
          "sign on it is just a locked door",
          'class="heldby" href="#phase-B"' in _rh)
    check("rail: a gate whose blocker is DONE is drawn open - B is blocked by A "
          "and A is signed off, so nothing holds B",
          'id="phase-B"' in _rh and 'href="#phase-A"' not in _rh)
    check("rail: a phase blocked by a phase that IS done is not held - the gate "
          "draws dependency, not a restatement of status",
          _held_by({"blockedBy": ["P1"]}, {"P1"}) == []
          and _held_by({"blockedBy": ["P1", "P2"]}, {"P1"}) == ["P2"])
    check("rail: the line is one colour and the gates carry the state, so the "
          "spine is structure rather than a second copy of the status chip",
          "--rail:" in _CSS and "border-left:2px solid var(--st" not in _CSS)
    check("rail: a signed-off phase is stamped with a commit it actually has, "
          "short-formed, and labelled as the last commit rather than as a "
          "signature the manifest does not record",
          'class="stamp"' in _rh and ">abc1234<" in _rh
          and "Last commit recorded in this phase" in _rh)
    check("rail: an unsigned phase carries no stamp",
          _rh.count('class="stamp"') == 1)
    # The verdict is the gate's, not the report's.
    check("verdict: the hero states the same verdict --gate would, with the "
          "conditions that produced it named",
          'data-gate=' in html_out and "vd-word" in html_out
          and "Spend is deliberately not one of them" in html_out)
    check("verdict: the conditions are in the reader's words, with the flag "
          "names kept in the title for whoever will type them",
          "manifest validity" in html_out and "--fail-on" in html_out)
    check("verdict: the ready task is promoted into the hero and is copyable",
          'class="vd-run"' in html_out and "btn-copy" in html_out)

    # --- app shell -------------------------------------------------------------
    check("shell: navigation at the side, document actions on top",
          'class="topbar"' in html_out and 'class="snav"' in html_out
          and 'class="shell"' in html_out)
    # The nav and the anchors come from ONE list, so a section cannot be linked
    # without existing or exist without being linked.
    _anchors = set(re.findall(r'<(?:section|div|h2|h3)[^>]*id="([a-z0-9-]+)"', html_out))
    _links = set(re.findall(r'class="snav"[\s\S]*?</nav>', html_out)
                 and re.findall(r'<a href="#([a-z0-9-]+)"',
                                html_out[html_out.index('class="snav"'):
                                         html_out.index("</nav>")]))
    check("shell: every nav link points at a section that exists: %r"
          % sorted(_links - _anchors), _links and _links <= _anchors)
    check("shell: the nav is rendered server-side, so a report read with JS off - "
          "or printed - still has its contents list",
          "<nav class=\"snav\"" in html_out and 'href="#gate"' in html_out)
    check("shell: scroll-spy only ADDS position; it does not supply the links",
          "markSpy" in _SCRIPT and "aria-current" in _SCRIPT)
    # The observer this replaced watched each target inside a 15%-30% band of the
    # viewport. Most targets are <h2> elements a line and a half tall, so usually
    # NONE was in the band and the nav marked nothing at all. Order, not
    # visibility: whichever heading last passed under the bar is where you are.
    check("shell: the marker is decided by which heading last passed the fold, so "
          "one link is always marked - a band-based observer marked none",
          "new IntersectionObserver" not in _SCRIPT
          and "if (best < 0) best = 0;" in _SCRIPT
          and "getBoundingClientRect().top <= fold" in _SCRIPT)

    # --- the sticky stack ------------------------------------------------------
    # Four hand-tuned offsets (4.1rem nav, 3.6rem filter bar, 3.5rem headers,
    # 6.6rem below 72rem) were four guesses at ONE number. The bar measures 70px:
    # the filter bar pinned 12px under it and the column headers pinned ABOVE the
    # filter bar and were painted out entirely.
    check("sticky: one measured offset, and every pinned layer derives from it",
          "--topbar-h:" in _CSS and "--sticky-2:calc(var(--sticky-1)" in _CSS
          and "--sticky-3:calc(var(--sticky-2)" in _CSS
          and "top:var(--sticky-2)" in _CSS and "top:var(--sticky-3)" in _CSS)
    # Checked against declarations only: the prose above these rules still names
    # the old constants, and it should - it is the record of what went wrong.
    _css_decl = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)
    check("sticky: no layer keeps a hand-tuned offset the bar can outgrow",
          not re.search(r"top:\s*(3\.4|3\.5|3\.6|4\.1|6\.6)rem", _css_decl))
    check("sticky: the column headers pin BELOW the bar that filters them, and "
          "paint under it rather than over it",
          "--z-sectools:15" in _CSS and "--z-thead:10" in _CSS
          and "z-index:var(--z-thead)" in _CSS
          and "z-index:var(--z-sectools)" in _CSS)
    check("sticky: the stack is restated at runtime, because its height depends "
          "on the title, the width and the reader's font size",
          "measureStack" in _SCRIPT and "--topbar-h" in _SCRIPT
          and "ResizeObserver" in _SCRIPT)
    # Anchors are how this report is navigated; every one of them landed under the
    # bar, which reads as "the link goes somewhere slightly below the heading".
    check("sticky: every anchor clears the stack instead of landing beneath it",
          "[id]{scroll-margin-top:calc(var(--sticky-2)" in _CSS)
    check("sticky: the scrollbar's width is reserved, so a short page and a long "
          "one do not centre the shell at two different offsets",
          "scrollbar-gutter:stable" in _CSS)

    # --- one missing element must not take the page down -----------------------
    check("guards: no early return above the print/download/copy/tooltip wiring - "
          "they have nothing to do with the phases table",
          "if (!grouped) return;" not in _SCRIPT
          and "grouped ? [].slice.call(grouped" in _SCRIPT)
    check("guards: a link inside a phase row is followed, not swallowed by the "
          "row's own expand/collapse",
          "closest('a,button,input,select,summary,label')" in _SCRIPT)
    check("guards: a chip's other classes survive being toggled",
          "classList.toggle('on', on)" in _SCRIPT
          and "x.className.split(' ')[0]" not in _SCRIPT)
    # A report outlives its tree: it gets mailed, archived, opened next week. When
    # someone reports a control that does not work, which renderer wrote the page
    # is the first thing worth knowing.
    check("stamp: the page names the plugin version that rendered it",
          'class="stampv"' in html_out and "audit " in html_out)

    # --- one badge grammar, and words instead of keys --------------------------
    check("badges: a status reads as English, with the machine value kept in the "
          "attribute so filtering and theming still compare keys",
          'data-status="in_progress"' in html_out
          and ">In progress<" in html_out
          and ">in_progress<" not in html_out)
    check("badges: one tinted grammar drives every status, so the amber "
          "special case is gone with the solid fill that required it",
          "--st-ink" in _CSS and "color-mix(in srgb,var(--st" in _CSS
          and "--chip-ink" not in _CSS)
    check("badges: the hue is carried by a dot, not only by the text colour",
          ".chip::before{" in _CSS)
    # The GLYPH, not just the selector. The selector-only version of this check was
    # green for the entire life of a chip that drew `¹30` where the tick belonged.
    check("filters: an active chip says so without relying on hue - and the tick "
          "reaches the browser as an escape, not as the octal wreckage of one",
          ".fchip.on::before" in _CSS
          and _mangled_css_escapes(
              _CSS[_CSS.index(".fchip.on::before"):][:120]) == [])
    # The markdown twin is a data table read by machines and by GitHub; it keeps
    # the machine spelling on purpose.
    check("badges: the markdown twin still speaks the manifest's own vocabulary",
          "| done |" in md_out or "| in_progress |" in md_out)
    # Built in JS, the whole filter bar was missing from any context that does not
    # run scripts - the one case where "gone" and "broken" look the same.
    check("filters: the chips are in the document, not created by the script",
          'class="fchip" data-ps=' in html_out
          and 'class="tf-chip" data-ts=' in html_out
          and 'aria-pressed="false"' in html_out
          and "createElement('button')" not in _SCRIPT)
    check("filters: the script attaches behaviour rather than building the UI",
          "function wireChips" in _SCRIPT and "buildChips" not in _SCRIPT)

    # --- c5: model + date filters, no auto-expand, match counts, hash state ----
    # These pin the SHAPE. Whether any of it works is settled in a browser by
    # tools/check-report-interactive.mjs, because a report whose script dies on
    # line one still contains every string below.
    check("c5: a task row carries what the filters compare, rather than making "
          "them read it back out of the rendered prose",
          'data-model="' in html_out and 'data-completed="' in html_out)
    check("c5: dates are cut to their date part, so a range test is a string "
          "comparison and an <input type=date> value can be one end of it",
          re.search(r'data-completed="\d{4}-\d{2}-\d{2}"', html_out) is not None
          and 'data-completed="20' in html_out
          and not re.search(r'data-(completed|started)="[^"]*T', html_out))
    check("c5: the model and date controls are in the document inside a native "
          "<details> - built in JS they would be missing from every no-script "
          "reader and every printed page, the same trap the status chips fell in",
          'class="fdetails"' in html_out
          and 'class="filterpanel"' in html_out
          and '<summary' in html_out
          and 'class="fchip" data-m=' in html_out
          and '<input type="date" id="audit-from"' in html_out)
    check("c5: a model chip is spelled the way the table spells it - a model name "
          "is an identifier, not a word this product chose",
          '<button type="button" class="fchip" data-m="opus" aria-pressed="false">'
          "opus</button>" in html_out)
    check("c5: the date picker opens on the months the plan actually covers",
          re.search(r'id="audit-from"[^>]*min="\d{4}-\d{2}-\d{2}"[^>]*'
                    r'max="\d{4}-\d{2}-\d{2}"', html_out) is not None)
    check("c5: the panel is out of flow, so opening it cannot move the sticky "
          "stack every anchor and column header is pinned against",
          ".filterpanel{position:absolute" in _CSS and ".fdetails{position:relative}" in _CSS)
    # The panel is a popover, so it answers to the two things every popover
    # answers to. A <details> does neither on its own — it closes only through its
    # own summary — and this one is absolutely positioned, so left open it covers
    # rows it has nothing to do with.
    check("filters: an outside click closes the More-filters panel",
          "details.fdetails[open]" in _SCRIPT and "!d.contains(ev.target)" in _SCRIPT)
    check("filters: Escape closes it and returns focus to the control that opened it",
          "if (ev.key !== 'Escape') return;" in _SCRIPT and "sum.focus()" in _SCRIPT)
    # Escape already means "clear the search" in the search box. One key doing two
    # things at once is worse than either.
    check("filters: Escape in the search box keeps its own meaning",
          "if (q && ev.target === q) return;" in _SCRIPT)
    # Room to read, not just room to fit: 27rem cleared the wrapping floor but left
    # four control rows crowded inside .75rem of padding.
    check("filters: the panel has room for its four rows",
          "min-width:32rem" in _CSS and "padding:1rem 1.1rem" in _CSS)
    check("filters: and still cannot outgrow a narrow viewport",
          "max-width:calc(100vw - 2rem)" in _CSS)
    # A relative span measured against the wall clock answers a different question
    # every morning — and would make the committed example a file that cannot stay
    # byte-equal to itself, which is precisely what ci.yml compares.
    check("c5: the presets measure back from the plan's own last recorded day, "
          "never from today",
          "var DMAX" in _SCRIPT
          and "Date.now()" not in _SCRIPT
          and "new Date()" not in _SCRIPT
          and "DMAX + 'T00:00:00Z'" in _SCRIPT)
    check("c5: filtering no longer forces its matches open - it offers a reason "
          "to open a row instead",
          "var open = showP && !!expanded[pid];" in _SCRIPT
          and "(term !== '' || tf !== '')" not in _SCRIPT)
    check("c5: and that reason is rendered - the match badge is in the row, "
          "hidden until there is something to say",
          'class="pmatch" hidden' in html_out
          and "' of ' + tasks.length + ' match'" in _SCRIPT)
    check("c5: the badge's `hidden` is honoured (a class with a display would "
          "otherwise beat it and pin '10 of 10 match' to every row at rest)",
          ".pmatch[hidden]{display:none}" in _CSS)
    check("c5: the count reports tasks as well as phases, now that a filter can "
          "narrow a phase from the inside without changing the phase count",
          "' of ' + totT + ' tasks'" in _SCRIPT)
    # Same trap as tr.taskfilter: with no script running every row is shown, so an
    # empty state that rendered by default would be a statement contradicted by
    # the table directly beneath it.
    check("c5: the empty state is hidden by default and revealed explicitly",
          "tr.norows{display:none}" in _CSS
          and 'class="norows"' in html_out
          and "'table-row' : 'none'" in _SCRIPT)
    check("c5: the way back out of an empty table does not live only INSIDE the "
          "empty table - the filter panel is drawn over that row",
          html_out.count('<button type="button" class="btn" data-clear') == 2
          and html_out.index("data-clear") < html_out.index('class="phases"'))
    check("c5: the view is a link, written with replaceState so it neither piles "
          "up history per keystroke nor throws on a file:// document",
          "history.replaceState(null, '', '#!'" in _SCRIPT
          and "try {" in _SCRIPT and "catch (e) {}" in _SCRIPT)
    check("c5: `#!` distinguishes filter state from the nav's plain fragments, "
          "and clearing filters strips only ours",
          "h.indexOf('#!') !== 0" in _SCRIPT
          and "(location.hash || '').indexOf('#!') === 0" in _SCRIPT)
    check("c5: the theme travels in the link only where this report owns the "
          "toggle - embedded, the host stamps data-theme on the same root",
          "if (themeBtn && parts.length) put('th'" in _SCRIPT)
    # The panel is emitted from the manifest, so a plan that records neither must
    # not ship an empty disclosure promising filters it cannot offer.
    _plain = {"meta": {}, "bugs": [], "phases": [
        {"id": "P1", "title": "x", "status": "pending",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}
    check("c5: a plan that records no models and no dates gets no panel at all",
          _filter_panel(_plain) == ""
          and 'class="fdetails"' not in render_html(
              _plain, _load_status_lib().rollup(_plain, [], []), "r", None))
    check("filters: a no-script reader is told why nothing filters",
          "<noscript>" in html_out)
    # Controls sit with what they act on.
    check("shell: document-level actions are in the top bar",
          html_out.index('id="audit-print"') < html_out.index('class="shell"'))
    check("shell: the phases filter sits on the phases table, not in the top bar - "
          "it does nothing while you are reading the usage charts",
          html_out.index('id="audit-q"') > html_out.index('class="shell"')
          and html_out.index('id="audit-q"') < html_out.index('class="phases"'))
    check("shell: prose pairs with the verdict on a wide screen instead of being "
          "set 130 characters wide",
          'class="topgrid"' in html_out and ".topgrid{" in _CSS
          and "min-width:78rem" in _CSS)
    check("shell: paper gets the document back - no bars, no nav, no section "
          "tools, and no disclosure arrow on a row already printed open",
          ".topbar,.snav,.toolbar,tr.taskfilter,.nojs,.tri{display:none!important}"
          in _CSS)
    # The no-script banner is screen-only: on paper there is no script to run and
    # no browser to open the file in, so it would be advice about nothing.
    check("shell: the no-script banner never reaches paper",
          ".nojs" in _CSS[_CSS.index("@media print"):])

    # ---- c6: the page belongs to the reader ------------------------------
    # Everything below is a string pin, and a string pin cannot tell whether a
    # print rule ever fires. The orientation itself is checked where it can be
    # measured - tools/check-report-interactive.mjs renders the report to PDF in
    # both orientations and reads the page box back out.
    _print = _CSS[_CSS.index("@page"):]
    check("c6: the stylesheet asks for a margin and does not dictate the sheet - "
          "`size` greys the print dialog's orientation control out",
          "@page{margin:1.4cm}" in _CSS and "size:" not in _print[:_print.index("}")])
    # The one place the reader was ever told a sheet size: the tooltip on the
    # control that opens the dialog. Scoped to that attribute rather than to the
    # whole document, which also carries the CSS comment explaining the removal
    # and a base64 blob in which "A4" turns up by chance.
    _ptitle = re.search(r'id="audit-print"[^>]*title="([^"]*)"', html_out)
    check("c6: the button no longer promises a sheet it does not choose - it "
          "says where the choice lives instead",
          bool(_ptitle) and "A4" not in _ptitle.group(1)
          and "orientation" in _ptitle.group(1))
    check("c6: a table spanning pages carries its column headers onto each one",
          "thead{display:table-header-group}" in _print)
    check("c6: no line stranded alone by a page break",
          "orphans:3;widows:3" in _print)
    check("c6: and no heading printed at the foot of a page, introducing nothing",
          "h1,h2,h3,h4,.sub{break-after:avoid;break-inside:avoid}" in _print)
    # Portrait inside a 1.4cm margin is ~688px == 43rem, so it MATCHES the 52rem
    # tablet rules while landscape (~1016px) does not. Allowing both orientations
    # is what made that divergence reachable.
    check("c6: portrait paper falls inside the tablet breakpoint, so the print "
          "sheet takes the small-screen scroll frame back off",
          ".tablewrap{overflow:visible" in _print
          and "table.phases,table.data{min-width:0" in _print
          and ".pmeta{position:static" in _print)
    # Paper prints the plan whole. Everything the screen's filter says about a
    # narrowed view is false on that page, and every one of those statements is
    # an inline style, so every one of them needs !important to take back.
    check("c6: paper prints every phase and every task, not the filtered "
          "leftovers - task rows under headings the filter hid",
          "tr.phase,tr.task{display:table-row!important" in _print)
    check("c6: ...so the match badge and the empty state never reach it - "
          "'3 of 12 match' beside all twelve, 'no phase matched' above every one",
          ".pmatch,tr.norows{display:none!important}" in _print)
    check("c6: the pills that carry meaning in their fill print it - one tinted "
          "grammar now covers status, risk, holder, cost band and delta",
          ".chip,.fill,.rchip,.heldby,.bandpill,.dl,tr.phase>td::before,"
          in _CSS and ".rank .track i,.bud .track i{"
          "-webkit-print-color-adjust:exact;print-color-adjust:exact}" in _CSS)

    # ---- c7: the polish, and the one control that was unreachable ---------
    # The headline here is not polish. `.filterpanel` is hung out of flow at
    # `min-width:32rem`, and MIN-WIDTH BEATS MAX-WIDTH - so the `max-width:calc(
    # 100vw - 2rem)` written to cap it to the viewport never capped anything.
    # Measured on a 390px viewport before the fix: a 512px panel spanning x=-353
    # to x=159, both date inputs at -225..-100, i.e. entirely off the left of the
    # screen, with document.scrollWidth still 390 - so not even scrollable to.
    # The whole date-range filter was unreachable on a phone.
    #
    # These are string pins and they cannot see any of that: every one of them was
    # green while the panel was off-screen. The check with teeth is in
    # tools/check-report-interactive.mjs, which opens the panel at 390x780 and
    # asserts every control's box lies inside the viewport.
    _tablet = _CSS[_CSS.index("@media (max-width:52rem)"):]
    _tablet = _tablet[:_tablet.index("@media (max-width:40rem)")]
    check("c7: the filter panel comes back into the flow on a small screen, "
          "where out of flow it hung its date inputs off the side of the page",
          ".filterpanel{position:static;min-width:0;max-width:none" in _tablet)
    # In flow the panel's height is the BAR's height, and a sticky bar 62% of the
    # viewport tall is a control that covers the content it filters.
    check("c7: ...and the bar stops being sticky while it carries it, rather "
          "than pinning 62% of a phone screen over the table",
          ".sectools:has(.fdetails[open]){position:static}" in _tablet)
    _mobile = _CSS[_CSS.index("@media (max-width:40rem)"):]
    check("c7: a date field takes the row rather than being squeezed until the "
          "UA elides its year",
          ".frow input[type=date]{flex:1 1 100%" in _mobile)

    # Elevation that says "this is stuck", the same statement the top bar makes.
    # There is no selector for it, so the class is toggled from the ONE scroll
    # listener that already runs - and the condition is read out of the CSS rather
    # than recomputed, so where this bar sits has one definition.
    check("c7: the filter bar reads as a layer once it is stuck, not before",
          ".sectools.stuck{box-shadow:var(--shadow-sm)}" in _CSS
          and "transition:box-shadow var(--dur) var(--ease)" in _CSS)
    check("c7: ...decided from the bar's own resolved sticky offset, not from a "
          "scrollY threshold that goes wrong the moment anything above it moves",
          "getComputedStyle(sectools)" in _SCRIPT
          and "classList.toggle('stuck'" in _SCRIPT)
    # Two states this bar really reaches and a naive `top <= stickAt` gets wrong:
    # not sticky at all (narrow + panel open, above), and scrolled past with its
    # section, where the top is far ABOVE the stick line.
    check("c7: ...and it is not 'stuck' when it is not sticky, nor when the "
          "table has scrolled away and taken it with it",
          "cs.position === 'sticky'" in _SCRIPT and "sr.bottom > stickAt" in _SCRIPT)

    # A table row cannot be height-animated, so the reveal is opacity alone, and
    # it is a STARTING STYLE rather than a keyframe animation on purpose: an
    # unsupported at-rule is dropped with its block and the rows simply appear.
    # This sheet has already pinned two blocks at opacity 0 forever by animating a
    # reveal (`fadeUp`, when its easing token stopped resolving), which is why
    # check-report-interactive.mjs asserts every revealed row settles at 1.
    check("c7: an expanded task row fades in, so the reader can see which rows "
          "are the new ones",
          "@starting-style{tr.task{opacity:0}}" in _CSS
          and "tr.task{transition:opacity var(--dur) var(--ease)}" in _CSS)
    check("c7: ...on screen only - a transition caught mid-run would put a "
          "half-faded row on paper",
          "@media screen and (prefers-reduced-motion:no-preference){" in _CSS)

    # 168 heatmap cells and 11 rank rows, every one of them carrying a tooltip
    # the mark itself never advertised.
    check("c7: a heatmap cell says it is hoverable - and with an OUTLINE, which "
          "takes no space, so hovering one cell cannot nudge the other 167",
          ".hm i:hover{outline:2px solid var(--text);outline-offset:1px}" in _CSS
          and "cursor:help" in _CSS)
    check("c7: a rank row's bar brightens under the pointer, on the mark the "
          "tooltip is about",
          ".rank:hover .track i{filter:brightness(1.15)}" in _CSS)

    # The banner exists because a report is a file people SEND each other, and a
    # common way of opening one - an IDE preview pane - sandboxes inline <script>.
    # The page then renders completely, looks finished, and every interaction
    # silently does nothing. Reported as "the report is broken"; it took two
    # browsers, two origins, five viewports and real mouse input to establish that
    # the report was fine and the viewer was not. Now it says so itself.
    check("nojs: the banner is in the HTML, so it shows without any script",
          'id="audit-nojs"' in html_out)
    check("nojs: it names the likely cause and the one-step fix",
          "IDE preview" in html_out and "browser" in html_out)
    check("nojs: it says which features are affected, not just 'interactive'",
          all(w in html_out for w in ("Filtering", "search", "expanding")))
    # NOT inside the <noscript>. The report already had one ("Filtering and
    # collapsing need JavaScript"), and it was the right intent with a mechanism
    # that could not fire: <noscript> renders only when SCRIPTING IS DISABLED. An
    # IDE preview pane leaves scripting on and strips the inline <script>, so the
    # page ran no code and still showed no warning. That existing note stays - it
    # is correct for the disabled case and adds "every row is shown" - but it
    # cannot be the only signal.
    _banner = html_out[html_out.index('id="audit-nojs"'):]
    check("nojs: the banner renders unconditionally, not only when scripting is off",
          "<noscript" not in html_out[:html_out.index('id="audit-nojs"')]
          or html_out.index("</noscript>") > html_out.index('id="audit-nojs"'))
    check("nojs: and the older <noscript> note is still there for the disabled case",
          "<noscript>" in html_out)
    # Removal is the script's FIRST act, ahead of anything that can throw. If a
    # later line fails, the banner staying up is then true and useful.
    _first = _SCRIPT[:_SCRIPT.index("var count = document.getElementById")]
    check("nojs: the script removes it before any statement that could throw",
          "audit-nojs" in _first and "removeChild" in _first)
    check("nojs: removal is guarded, so a report rendered without it cannot throw",
          "if (_nojs && _nojs.parentNode)" in _SCRIPT)

    # --- table density follows the data ---------------------------------------
    _fresh = {"meta": {}, "bugs": [], "phases": [
        {"id": "P1", "title": "x", "status": "pending",
         "tasks": [{"id": "P1.1", "title": "t", "status": "pending"}]}]}
    check("cols: a plan with nothing done renders id/title/status and no more - "
          "six columns of em dashes describe the schema, not the work",
          _present_columns(_fresh) == [])
    _ado = json.loads(json.dumps(_fresh))
    _ado["phases"][0]["tasks"][0]["ado"] = {"id": 7}
    check("cols: ADO appears only for a repo that actually syncs to Azure DevOps",
          _present_columns(_ado) == ["ADO"])
    _done = json.loads(json.dumps(_fresh))
    _done["phases"][0]["tasks"][0].update(
        {"status": "done", "commit": "abc1234", "completedAt": "2026-01-02T00:00:00Z"})
    check("cols: a column appears as soon as ONE task fills it",
          _present_columns(_done) == ["commit", "done"])
    check("cols: a malformed task never silently removes a column",
          _present_columns({"phases": [{"tasks": [{"ado": "not-an-object"}]}]}) is not None)
    # The header, the cells and both colspans have to agree, or the table skews.
    _fh = render_html(_fresh, _load_status_lib().rollup(_fresh, [], []), "r", None)
    check("cols: header, colspan and cells agree on the count",
          _fh.count("<th>") == 3 and 'colspan="3"' in _fh
          and "<th>ADO</th>" not in _fh)
    # Scoped to the phases table: the bugs table has its own headers, and counting
    # <th> across the document measured both.
    _phead = html_out[html_out.index('<table class="phases">'):]
    _phead = _phead[:_phead.index("</thead>")]
    check("cols: the full example still renders every column it has data for",
          _phead.count("<th>") == 3 + len(_present_columns(manifest)))

    # --- scale: the filter must not re-query the DOM per phase ----------------
    # Measured on a 200-phase / 4000-task report: one keystroke took 145ms and a
    # five-character burst blocked the main thread for 508ms, because refresh()
    # called querySelectorAll ONCE PER PHASE inside its own loop over phases.
    _body = _SCRIPT[_SCRIPT.index("function refresh()"):]
    _body = _body[:_body.index("\n  function ", 10)] if "\n  function " in _body[10:] else _body
    check("scale: refresh() runs no DOM query per phase - that loop is O(phases x "
          "rows) and it ran on every keystroke",
          "querySelectorAll" not in _body and "querySelector(" not in _body)
    check("scale: the phase->tasks index is built once, up front",
          "var TASKS = {}, TFROW = {};" in _SCRIPT)
    check("scale: row text is lowercased once and kept, not re-derived per keystroke",
          "r.__auditText" in _SCRIPT)
    check("scale: sorting copies the index before ordering it, so the index is "
          "never left permuted behind the table",
          "tasksOf(pid).slice().sort(cmp)" in _SCRIPT)
    check("scale: typing is debounced - five characters is one pass, not five",
          "setTimeout(function () { qTimer = null; refresh(); }, 90)" in _SCRIPT)
    check("scale: Enter and Escape bypass the debounce, because they are decisions "
          "rather than typing",
          "ev.key !== 'Enter' && ev.key !== 'Escape'" in _SCRIPT)

    # --- fragment mode (publishable as a Claude Code Artifact) --------------
    # The host wraps what it is given in its own doctype/head/body, so every one
    # of these tags would nest a second document inside the first.
    _frc = main([mp, "--out-dir", tmp, "--format", "artifact"])
    _fp = os.path.join(tmp, "audit-report.artifact.html")
    check("artifact: --format artifact exits 0 and writes its own file",
          _frc == 0 and os.path.getsize(_fp) > 0)
    check("artifact: it never overwrites the standalone .html "
          "(that file is what CI diffs the live demo against)",
          os.path.getsize(hp) > 0 and open(hp, encoding="utf-8").read() == html_out)
    frag = open(_fp, encoding="utf-8").read()
    for tag in ("<!doctype", "<html", "</html>", "<meta charset",
                "<meta name=\"viewport\""):
        check("artifact: fragment carries no %s" % tag, tag not in frag.lower())
    check("artifact: fragment keeps the title (the host reads it to name the page)",
          "<title>" in frag)
    check("artifact: fragment keeps the whole stylesheet inline "
          "(a CSP blocks every external host, so a linked one would not load)",
          "<style>" in frag and ":root{" in frag)
    # Tags, not the substring " src=": this fixture's desiredOutcome deliberately
    # contains `<img src=x onerror=...>`, which the report ESCAPES. A naive
    # substring test fails on the very input that proves the escaping works.
    check("artifact: fragment loads nothing over the network "
          "(a CSP blocks every external host, so a resource tag is a blank space)",
          not any(t in frag.lower() for t in
                  ("<script src", "<img ", "<link ", "<iframe", "url(http")))
    check("artifact: and the hostile fixture is still escaped, not stripped",
          "&lt;img src=x" in frag)
    check("artifact: fragment drops the theme toggle, since the host owns the "
          "theme and stamps the same data-theme attribute",
          'id="audit-theme"' not in frag)
    check("artifact: the standalone report KEEPS its toggle "
          "(the fragment is the exception, not a rewrite)",
          'id="audit-theme"' in html_out)
    check("artifact: the persisted theme is reinstated only where the toggle "
          "exists, so an embedded report cannot override its host",
          "if (themeBtn) {" in _SCRIPT)
    check("artifact: the report body itself is unchanged - same phases table, "
          "same usage section, same markdown twin",
          '<table class="phases"' in frag
          and ("AUDIT_MD_B64" in frag) == ("AUDIT_MD_B64" in html_out))
    check("artifact: wide tables scroll inside their own box, not the page",
          ".tablewrap{" in frag and "overflow-x:auto" in frag)
    check("artifact: the fragment answers to the host's theme in BOTH directions",
          'data-theme="dark"' in frag and 'data-theme="light"' in frag)
    check("a3 sortable headers are focusable and announce their state",
          "aria-sort" in _SCRIPT and "'tabindex', '0'" in _SCRIPT
          and "'role', 'button'" in _SCRIPT)
    check("a4 sorting is operable from the keyboard, not click-only",
          "keydown" in _SCRIPT and "'Enter'" in _SCRIPT)
    check("a5 aria-sort is reset on the other columns, not left stale",
          _SCRIPT.count("aria-sort") >= 3)
    check("a6 filter chips expose their pressed state rather than colour alone",
          "aria-pressed" in _SCRIPT)
    check("a7 the per-phase task filter is revealed with an explicit display "
          "(clearing it would hand the row back to `tr.taskfilter{display:none}`)",
          "'table-row'" in _SCRIPT)
    check("a8 the rule that made it invisible is still the one being overridden",
          "tr.taskfilter{display:none}" in _CSS)
    check("a9 only headers that sort are styled as controls "
          "(three tables showed a pointer on headers that did nothing)",
          'thead th[role="button"]{cursor:pointer' in _CSS
          and "border-bottom:1px solid var(--border)}" in _CSS)
    check("a10 a bare thead th no longer claims to be clickable",
          not re.search(r"thead th\{[^}]*cursor:pointer", _CSS))
    check("a11 keyboard focus on a sortable header is visible",
          'thead th[role="button"]:focus-visible' in _CSS)

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
    _bh = render_html(manifest, _sum, "audit-report", _big)
    check("u17 ranked lists fold past the top N and label the remainder",
          "other (" in _bh, "no fold marker")
    check("u18 phase composition folds and says how many are hidden",
          _bh.count('class="uphase"') == TOP_N and "+22 more phase" in _bh,
          "%d rows" % _bh.count('class="uphase"'))
    check("u19 small multiples fold and say how many authors are hidden",
          _bh.count('class="smcell"') == TOP_N and "+12 more author" in _bh,
          "%d cells" % _bh.count('class="smcell"'))
    check("u20 no categorical axis ever exceeds the 8 validated hues",
          max((int(m) for m in re.findall(r"var\(--viz-(\d)\)", _bh)),
              default=0) <= VIZ_SLOTS)
    # --- orientation + hover -----------------------------------------------------
    check("u21 context line states scale and span without spending a tile on it",
          'class="uctx"' in uh and "2 people" in uh and "3 sessions" in uh
          and "2026-08-01 to 2026-08-02" in uh and _usage_context({}) == "")
    check("u21b counts are singularised (1 phase, not '1 phases')",
          "1 phase ·" in _usage_context({"counts": {"phases": 1, "people": 3}}))
    _rank_tip = re.search(r'<div class="rank" title="([^"]*)"', uh)
    check("u22 a ranked bar hovers to the exact count, its share of the whole, "
          "cost and messages — none of which the bar itself can show",
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
    # to say so — silently changing the resolution is the same lie as silently
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
    check("u24 the hover layer re-renders the mark's own title — never a second "
          "copy of the numbers — so JS-off keeps the native tooltip",
          "__tip" in uh and "removeAttribute('title')" in uh
          and uh.count("split('\\t')") == 1)
    check("u24b hover is delegated, not one listener per mark",
          uh.count("addEventListener('mouseover'") == 1
          and "mouseenter" not in uh)
    check("u24c the floating tooltip is suppressed for print",
          "@media print{.rtip{display:none!important}" in uh)
    # 0.08% of the peak rounds to width:0.0% — an empty track reads as "no data".
    _tiny = _ranked(dict(_u, byModel={
        "big": {"tokens": 1_000_000, "costUSD": 1.0, "msgs": 9},
        "sliver": {"tokens": 300, "costUSD": 0.01, "msgs": 1}}), "byModel", "By model")
    check("u25 a tiny non-zero bar still paints a sliver, never an empty track",
          "width:0.8%" in _tiny and "width:100.0%" in _tiny,
          re.findall(r"width:[\d.]+%", _tiny))

    # --- one number format, everywhere ------------------------------------------
    check("u26 tokens are compact at one decimal, and two on hover",
          _fmt_tokens(3_230_000) == "3.2M" and _fmt_tokens(3_230_000, 2) == "3.23M"
          and _fmt_tokens(942) == "942" and _fmt_tokens(2_000_000_000) == "2.0B"
          and _fmt_tokens(214_300, 2) == "214.30K",
          _fmt_tokens(3_230_000, 2))
    # The rule is easy to state and easy to break one call site at a time: the
    # label reads 3.2M and the tooltip that opens over it reads 3,230,000. So the
    # guard is mechanical — every raw thousands-separated number in this file must
    # be a COUNTABLE (messages, sessions, tasks), never a token magnitude.
    with open(__file__, encoding="utf-8") as _fh:
        _src = _fh.read()
    _raw = re.findall(r'"\{:,\}"\.format\(([^)]*)\)', _src)
    _bad = [x for x in _raw if not re.search(r"msgs|sessions|tasks|phases", x)]
    check("u27 no token value is ever rendered with thousand separators "
          "(counts may be; magnitudes may not)", _bad == [], repr(_bad))
    # preserveAspectRatio="none" scales the coordinate system non-uniformly, and
    # that scales the glyphs with it — measured at +49% width on a 1072px render.
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
    _bh2 = render_html(manifest, _sum, "audit-report", dict(
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
    check("u39 no advice renders nothing — silence is the normal outcome on a "
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
    check("u41 the caveat is present and specific — upper bound, one rate epoch, "
          "and the in-repo condition",
          "upper bound, not a forecast" in _adv
          and "would not emit the same tokens" in _adv
          and "one rate epoch" in _adv)
    check("u28 the md twin uses the same compact tokens as the HTML labels",
          "**Total:** 1.5M tokens" in um and "| P1 | 1.0M |" in um,
          [l for l in um.splitlines() if "1.0M" in l or "Total:" in l][:3])

    check("u15 zero-token ledger renders nothing rather than an empty frame",
          'id="usage"' not in render_html(
              manifest, _sum, "audit-report",
              dict(_u, totals=dict(_u["totals"], tokens=0))))
    check("u16 model names are HTML-escaped",
          "&lt;script&gt;" in render_html(
              manifest, _sum, "audit-report",
              dict(_u, byModel={"<script>": {"tokens": 5, "costUSD": 0.0, "msgs": 1}},
                   phaseModel={"P1": {"<script>": 5}})))

    check("m1 md contains phase heading and escaped pipe",
          "## P1" in md_out and "a\\|bug" in md_out)
    check("m2 md table row for the done task",
          "| P1.1 | done task | done |" in md_out and "#42" in md_out)
    check("h1 progress bar rendered", 'class="bar"' in html_out
          and "1/2" in html_out)
    check("h2 overall header present (html + md)",
          'class="overall"' in html_out and "**Overall:**" in md_out
          and "phases signed off" in html_out)
    check("h3 task outcome shown + escaped", "did the thing cleanly" in html_out)
    check("h4 phase branch/mergedAt meta shown",
          "branch audit/p1-x" in html_out and "merged 2026-07-09" in html_out)
    check("h5 html has doctype + charset + title (standalone render, tab name)",
          html_out.lstrip().lower().startswith("<!doctype html>")
          and 'charset="utf-8"' in html_out and "<title>" in html_out)
    check("h6 collapsible grouped table + separate phase/task filters + script",
          'class="phases"' in html_out and 'tr class="phase"' in html_out
          and 'tr class="task"' in html_out and 'tr class="taskfilter"' in html_out
          and "aria-expanded" in html_out and 'id="audit-q"' in html_out
          and 'id="audit-phase-status"' in html_out and 'id="audit-expand"' in html_out
          and "<script>" in html_out and "addEventListener" in html_out)
    check("h7 phase + task rows carry data-phase/data-status (grouping + filter)",
          'data-phase="P1"' in html_out and 'data-status="done"' in html_out
          and 'data-status="pending"' in html_out and 'data-status="open"' in html_out)
    check("h8 AI summary box rendered + escaped (from meta.reportSummary)",
          '<div class="summary">' in html_out
          and "closed all criticals &amp; shipped" in html_out)
    check("h9 PDF (print) + Download .md buttons + embedded md + print CSS",
          'id="audit-print"' in html_out and 'id="audit-dl-md"' in html_out
          and 'window.AUDIT_MD_B64="' in html_out and "@page" in html_out
          and "@media print" in html_out)
    check("h10 done column: completion date + full timestamps on hover",
          "<th>done</th>" in html_out and "2026-07-09" in html_out
          and 'title="started 2026-07-09T08:00:00Z · completed '
          '2026-07-09T09:30:00Z"' in html_out)
    check("h11 risk chip (data-risk) + status token drives rail/chip",
          'class="rchip" data-risk="high"' in html_out and ">high</span>" in html_out
          and 'class="chip" data-status="done"' in html_out
          and '[data-status="blocked"]' in html_out and "--st-blocked" in html_out)
    check("h12 theme toggle + design tokens + dark + reduced-motion present",
          'id="audit-theme"' in html_out and ":root{" in html_out
          and "--accent" in html_out and "prefers-color-scheme:dark" in html_out
          and "prefers-reduced-motion" in html_out)
    # Counts the CLASS, not one exact tag: the phases wrapper gained an id when it
    # became a nav anchor, and an assertion that breaks on an added attribute was
    # testing the markup rather than the guarantee (both wide tables scroll in
    # their own box).
    check("h13 responsive: wide tables wrapped + mobile breakpoint",
          html_out.count('class="tablewrap"') == 2
          and ".tablewrap{overflow-x:auto" in html_out
          and "@media (max-width:40rem)" in html_out)
    check("m4 markdown twin has the done column with the completion date",
          "| done | ADO |" in md_out and "2026-07-09" in md_out)
    check("r1 ready list rendered", "P1.2" in md_out)

    rc = main([mp, "--format", "nope"])
    check("c3 bad format is usage error (exit 2)", rc == 2)
    rc = main([os.path.join(tmp, "missing.json")])
    check("c4 unreadable manifest (exit 2)", rc == 2)
    arr = os.path.join(tmp, "arr.json")
    with open(arr, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5 non-object JSON root is a usage error (exit 2)", main([arr]) == 2)
    # --summary-file injects the summary WITHOUT a reportSummary in the manifest
    sf = os.path.join(tmp, "sum.txt")
    with open(sf, "w", encoding="utf-8") as fh:
        fh.write("Injected via CLI summary file.")
    m2 = json.loads(json.dumps(manifest))
    m2["meta"].pop("reportSummary", None)
    mp2 = os.path.join(tmp, "m2.json")
    with open(mp2, "w", encoding="utf-8") as fh:
        json.dump(m2, fh)
    main([mp2, "--out-dir", tmp, "--format", "html", "--summary-file", sf])
    inj = open(os.path.join(tmp, "audit-report.html"), encoding="utf-8").read()
    check("c6 --summary-file injects the Summary box (manifest untouched)",
          '<div class="summary">' in inj and "Injected via CLI summary file." in inj)

    # --basename controls the output filenames AND the Download-.md name
    bdir = os.path.join(tmp, "bn")
    main([mp, "--out-dir", bdir, "--basename", "q3-audit"])
    bn_html = os.path.join(bdir, "q3-audit.html")
    check("c7 --basename writes q3-audit.html/.md + sets download name",
          os.path.exists(bn_html) and os.path.exists(os.path.join(bdir, "q3-audit.md"))
          and 'window.AUDIT_MD_NAME="q3-audit.md"'
          in open(bn_html, encoding="utf-8").read())
    # meta.reportBasename is honored, and a path-y value is sanitized to a bare
    # name INSIDE out_dir (the leading ../../ is dropped, not traversed).
    mb = json.loads(json.dumps(manifest))
    mb["meta"]["reportBasename"] = "../../etc/passwd"
    mpb = os.path.join(tmp, "mb.json")
    with open(mpb, "w", encoding="utf-8") as fh:
        json.dump(mb, fh)
    bdir2 = os.path.join(tmp, "bn2")
    main([mpb, "--out-dir", bdir2, "--format", "html"])
    check("c8 meta.reportBasename sanitized to a bare name (no path escape)",
          os.path.exists(os.path.join(bdir2, "passwd.html"))
          and not os.path.exists(os.path.join(bdir2, "audit-report.html"))
          and not os.path.exists(os.path.join(tmp, "etc", "passwd.html")))

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
