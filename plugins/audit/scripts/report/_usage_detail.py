#!/usr/bin/env python3
"""
Everything the Usage section folds behind its `Detail` disclosure.

Split out of `_report_usage.py` along the same seam as `_usage_overview.py`:
these six blocks are real and are worth having, and none of them belongs on
first paint. The disclosure is the product's own division, so it is the one the
files follow.

WHAT EACH ONE REFUSES TO SAY, which is the half worth reading:

  * the small multiples share ONE axis and ONE scale across every author, and
    the caption states both - a shared frame the reader cannot see is a shared
    frame they cannot trust. A column too small to draw is a hairline, not a
    1.5px floor, because a floor made twenty different days look identical.
  * the routing table compares models WITHIN a risk band only. Hard work is
    routed to the stronger model on purpose, so a spend-per-task comparison
    across bands would flag that working system as a fault.
  * the routing ADVICE is the one place this section recommends rather than
    reports, and it renders nothing unless the ledger's own evidence clears
    every gate. Its caveat is not boilerplate: the figure re-prices the tokens
    that were actually spent, and a different model would not emit the same
    tokens.
  * the cost band says where its thresholds came from, or why there are none.
    A band whose definition is invisible is a number nobody can argue with.
  * retried spend is not wasted spend, and the paragraph says so: the ledger
    buckets by hour, not by attempt. Only the BLOCKED figure is spend with no
    outcome.

This module carries no `--selftest` of its own; its cases live in
`plugins/audit/tests/test__usage_detail.py` - see
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

import _ui_theme as _theme  # noqa: E402  (the one place a machine value gets its words)

import _usage_viz as _viz  # noqa: E402  (the section's number formatting and marks)

# Thin module-level aliases, not copies: the bodies below were moved out of
# `_report_usage.py` unchanged, and an alias keeps them reading the same names
# while there is still exactly one definition of each. A case pins the identity.
TOP_N = _viz.TOP_N
e = _viz.e
_bin_days = _viz._bin_days
_fill_pct = _viz._fill_pct
_fmt_cost = _viz._fmt_cost
_fmt_pct = _viz._fmt_pct
_fmt_tokens = _viz._fmt_tokens
_spark = _viz._spark


# --- per-author panels, and the calendar month table ---------------------------
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


# --- routing, economics and phase composition ----------------------------------
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


# --- heatmap -------------------------------------------------------------------
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
        print("_usage_detail.py has no inline --selftest; its cases live in "
              "plugins/audit/tests/test__usage_detail.py - run that file instead.")
        sys.exit(0)
    print(__doc__.strip())
