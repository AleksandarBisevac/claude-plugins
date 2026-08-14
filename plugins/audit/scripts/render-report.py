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
import _report_ui             # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html           # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)
import _report_usage          # noqa: E402  (the Usage section: ledger load, charts, markdown twin)


# --- module aliases (CSS/SCRIPT, fragment + usage re-exports) -------------------
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
_global_filter_row = _report_html._global_filter_row
_ready_now_dl = _report_html._ready_now_dl
_risk_chip = _report_html._risk_chip
_phase_meta_div = _report_html._phase_meta_div
_bar = _report_html._bar
_owner_map = _report_html._owner_map
_area_tag_span = _report_html._area_tag_span
_seg_of = _report_html._seg_of


# The stylesheet lints live beside the stylesheet they police, in _ui_theme,
# so the panel is held to the same rules. Aliased rather than renamed at the
# call sites: these names are what the selftest below asks for by hand.
_undeclared_css_vars = _theme.undeclared_css_vars
_unterminated_css_decls = _theme.unterminated_css_decls
_mangled_css_escapes = _theme.mangled_css_escapes
_theme_asymmetric_vars = _theme.theme_asymmetric_vars
_themes_missing_color_scheme = _theme.themes_missing_color_scheme


# The Usage section — the ledger load, every chart in it and the Markdown twin
# of the whole block — lives in _report_usage.py (P13.2). It sits above
# _report_html and below this file: it imports the fragment helpers, nothing
# imports it but render-report. Aliased here so render_html/render_md and this
# file's selftest keep referring to these names unchanged.
load_usage = _report_usage.load_usage
_iso_day = _report_usage._iso_day
_pricing_stale = _report_usage._pricing_stale
VIZ_SLOTS = _report_usage.VIZ_SLOTS
TOP_N = _report_usage.TOP_N
SPARK_COLS = _report_usage.SPARK_COLS
_fmt_tokens = _report_usage._fmt_tokens
_fmt_cost = _report_usage._fmt_cost
_model_slots = _report_usage._model_slots
_delta = _report_usage._delta
_tip = _report_usage._tip
_tile = _report_usage._tile
_usage_context = _report_usage._usage_context
_usage_tiles = _report_usage._usage_tiles
_usage_notices = _report_usage._usage_notices
_usage_trend = _report_usage._usage_trend
_budget_block = _report_usage._budget_block
_ranked = _report_usage._ranked
_spark = _report_usage._spark
_bin_days = _report_usage._bin_days
_small_multiples = _report_usage._small_multiples
_routing_table = _report_usage._routing_table
_routing_advice_block = _report_usage._routing_advice_block
_economics_block = _report_usage._economics_block
_band_note = _report_usage._band_note
_phase_stacks = _report_usage._phase_stacks
_usage_heatmap = _report_usage._usage_heatmap
_usage_section = _report_usage._usage_section
_md = _report_usage._md
_usage_md = _report_usage._usage_md


# --- report vocab ---------------------------------------------------------------
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


# --- table + verdict helpers ----------------------------------------------------
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


# --- render_html ----------------------------------------------------------------
def _phase_rows(ph, psum, seg, ncol, cols, done_ids, owners):
    """One phase's rows — the group row, its task-filter row and its task rows.

    Extracted from render_html's former inline loop when segmentation (D1)
    made the iteration two levels deep; the MARKUP is byte-identical to what
    the loop emitted, plus `data-seg` on every row (the hook the archive gate
    and the per-segment print isolation select whole segments by) and the
    advisory owner suffix on the area tags (D4)."""
    pid = psum["id"]
    areas = psum["area"] if isinstance(psum.get("area"), list) \
        else _areas_of(ph.get("area"))
    area_tags = "".join(" " + _area_tag_span(a, owners) for a in areas)
    held = _held_by(ph, done_ids)
    out = []
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
        'data-seg="%s" data-area="%s" tabindex="0" '
        'aria-expanded="false"><td colspan="%d"><span class="tri"></span> '
        '<span class="mono">%s</span> <strong>%s</strong>%s %s%s%s %s'
        '<span class="pmatch" hidden></span>%s</td></tr>'
        % (e(pid), e(pid), e(psum["status"]),
           ' data-held="1"' if held else "",
           seg, e(" ".join(areas)), ncol, e(pid), e(psum["title"]),
           area_tags, _chip(psum["status"]), held_mark, stamp,
           _bar(psum["done"], psum["total"]), _phase_meta_div(ph)))
    # per-phase task-status filter (shown only when the phase is expanded);
    # _SCRIPT fills .tf-chips from this phase's own task statuses.
    _tstat = sorted({t.get("status") for t in (ph.get("tasks") or [])
                     if isinstance(t, dict) and t.get("status")})
    out.append('<tr class="taskfilter" data-phase="%s" data-seg="%s">'
               '<td colspan="%d">'
               '<span class="tf-label">Filter tasks by status:</span>'
               '<span class="tf-chips">%s</span></td></tr>'
               % (e(pid), seg, ncol,
                  _chip_buttons(_tstat, "data-ts", "tf-chip")))
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
            '<tr class="task" data-phase="%s" data-seg="%s" data-status="%s"%s%s>'
            '<td class="mono tid">%s</td><td>%s</td><td>%s</td>%s</tr>'
            % (e(pid), seg, e(t.get("status")),
               ' data-held="1"' if held else "",
               _filter_attrs(t),
               e(t.get("id")), e(t.get("title")),
               _chip(t.get("status")),
               "".join(cells[c]() for c in cols)))
    return "\n".join(out)


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
    # The global filter row (C1/C2): author, area and the date range, inside
    # the sticky top bar so they stay reachable however far the reader has
    # scrolled. Why the bar and not a new floating row is argued where the row
    # is built (_report_html._global_filter_row). Inputs: authors by spend
    # (matching the Usage chips' order), tags first-seen (matching the panel
    # chips), and the date bounds from ALL data actually present — task
    # timestamps and ledger days both, since the one range scopes both surfaces.
    _gauthors = [a for a, v in sorted(
        ((usage or {}).get("byAuthor") or {}).items(),
        key=lambda kv: -kv[1].get("tokens", 0))]
    _gdates = []
    for _ph in (manifest.get("phases") or []):
        if isinstance(_ph, dict):
            for _t in (_ph.get("tasks") or []):
                if isinstance(_t, dict):
                    for _k in ("startedAt", "completedAt"):
                        if _t.get(_k):
                            _gdates.append(_short_date(_t[_k]))
    _gdates += list(((usage or {}).get("daily") or {}).keys())
    _owners = _owner_map(manifest)   # advisory area owners (D4) — one lookup
    out.append("@@TOOLBAR@@%s</header>"
               % _global_filter_row(_gauthors, _report_html._areas.used_tags(manifest),
                                    min(_gdates) if _gdates else None,
                                    max(_gdates) if _gdates else None,
                                    owners=_owners))
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
    # D1: the table renders in SEGMENTS — active (in_progress/blocked) first,
    # then pending, then done — grouped by rolled-up status, plan order kept
    # inside each group. The done segment is the ARCHIVE: on a plan that still
    # has other work its seghead is a toggle and report.js collapses the rows
    # under it at load, so a long finished run stops burying the work in
    # motion. When done is the ONLY segment there is nothing to keep prominent
    # and no toggle is emitted — a table that opens empty explains nothing.
    # The Markdown twin deliberately keeps manifest order: it is a data table
    # read by machines, and reordering it would change every diff against an
    # earlier render for a purely presentational reason.
    _pairs = list(zip(
        [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
        summary["phases"]))
    _by_seg = {}
    for _pair in _pairs:
        _by_seg.setdefault(_seg_of(_pair[1]["status"]), []).append(_pair)
    _segs = [s for s in _report_html.SEG_ORDER if _by_seg.get(s)]
    for _seg in _segs:
        _sn = len(_by_seg[_seg])
        # D2: every segment header is also the segment's export surface — CSV
        # of the segment's DATA and a print run scoped to it, wired by
        # report.js (server-rendered buttons, the chips rule).
        _exports = (
            '<span class="segx">'
            '<button type="button" class="btn segbtn" data-segcsv="%s" '
            'title="Download this segment&#39;s phases and tasks as CSV — the '
            'data, not the filtered view">CSV</button>'
            '<button type="button" class="btn segbtn" data-segprint="%s" '
            'title="Print only this segment — the print dialog opens scoped '
            'to it">Print</button></span>' % (_seg, _seg))
        if _seg == "done" and len(_segs) > 1:
            _head = ('<button type="button" class="segtoggle" id="audit-arch" '
                     'aria-expanded="false" data-count="%d">Archive — %s'
                     "</button>" % (_sn, _plural(_sn, "done phase")))
        else:
            _head = ('<span class="segname">%s</span>'
                     '<span class="segn">%s</span>'
                     % (_report_html.SEG_LABEL[_seg], _plural(_sn, "phase")))
        out.append('<tr class="seghead" data-seg="%s"><td colspan="%d">%s%s'
                   "</td></tr>" % (_seg, ncol, _head, _exports))
        for ph, psum in _by_seg[_seg]:
            out.append(_phase_rows(ph, psum, _seg, ncol, cols, _done_ids,
                                   _owners))
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
        # D2: the bugs table is tabular data, so it earns the same CSV control
        # the phase segments carry — server-rendered, wired by report.js.
        out.append('<h2 id="%s">Bugs<span class="segx">'
                   '<button type="button" class="btn segbtn" data-csv="bugs" '
                   'title="Download the bugs table as CSV">CSV</button>'
                   "</span></h2>"
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
        # C4: a definition list, not a comma-joined id string — each ready task
        # names itself, wears its phase's area tags (same chip style as
        # everywhere else) and states which blockers cleared. Empty stays as it
        # was: no section at all, because the hero's "Nothing ready / nothing
        # left to run" line already IS the empty state, with more context than
        # a heading over nothing could carry.
        out.append('<h2 id="%s">Ready now</h2>%s'
                   % (section("ready", "Ready now", len(summary["ready"])),
                      _ready_now_dl(manifest, summary["ready"])))
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


# --- render_md ------------------------------------------------------------------
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


# --- cli ------------------------------------------------------------------------
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
    # This case read `"2026-08-06" in uh` for four releases and asserted nothing:
    # render_html stamps `generated <today>`, so on the day it was written the
    # report's own timestamp satisfied it. It failed for the first time when the
    # clock rolled to the 7th — and what it uncovered was real. HTML surfaced
    # pricingAsOf ONLY through the >90-day stale notice, so the ordinary report
    # showed dollars with no way to see what priced them, while the Markdown twin
    # printed it every time. The phrase itself is asserted in _report_usage's
    # u4/u4b, off the section directly; what stays here is the half that needs a
    # whole document, because only a document carries the generation stamp.
    check("u4c and the date is not merely today's generation stamp "
          "(the trap this case sat in)",
          "rates as of %s" % time.strftime("%Y-%m-%d", time.gmtime()) not in uh)
    check("u10 heatmap opts out of the sticky thead used by the phases table",
          ".hm thead th{position:static" in uh)
    # A closed <details> clips its children in print media regardless of CSS, so
    # the PDF silently loses the detail block without this. Verified in-browser.
    check("u10b the disclosure is force-opened for printing, not just CSS-hinted",
          "beforeprint" in uh and "afterprint" in uh)
    check("u12 md twin carries the usage table (the contrast relief)",
          "## Usage" in um and "### By phase" in um and "### By model" in um)
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
    # --- C3: author chips scope the usage section, and only it -----------------
    # The chip markup itself is pinned in _report_usage's ua cases; what needs a
    # whole document is the WIRING - that report.js drives the chips, restores
    # the top-8 default, writes the summary line off the chip's own data
    # attributes, and carries the state in the hash as au=.
    check("c3: the author chips are in the document and report.js wires them "
          "rather than building them",
          'id="audit-authors"' in uh
          and "wireChips(authorBar, 'data-au'" in _SCRIPT)
    check("c3: releasing the chip restores the top-8 default by re-applying "
          "hidden from data-top, never by re-rendering",
          "c.getAttribute('data-author') !== auFilter" in _SCRIPT
          and ": !c.hasAttribute('data-top')" in _SCRIPT)
    check("c3: the summary line is assembled from the chip's own data "
          "attributes, not recomputed by a second implementation",
          "chip.getAttribute('data-tokens')" in _SCRIPT
          and "chip.getAttribute('data-share')" in _SCRIPT
          and "of all spend" in _SCRIPT)
    check("c3: the author filter is a link (au=) and restores from one",
          "put('au', auFilter)" in _SCRIPT and "if (HASH.au)" in _SCRIPT)
    check("c3: clear-all lifts the author scope with everything else "
          "(pinned INSIDE clearAll - the declaration up top spells the same "
          "bytes and satisfied a whole-script substring)",
          "auFilter = '';" in _SCRIPT.split("function clearAll()")[1])
    check("c3: hidden actually hides a rank row and a hidden smcell - the "
          "author-facing rules a UA default cannot win against",
          ".rank[hidden]{display:none}" in _CSS
          and ".smcell[hidden]{display:none}" in _CSS)
    check("c3: the task table is untouched by the author filter - no task or "
          "phase row carries an author, and refresh() never reads the state",
          re.search(r'<tr class="(?:task|phase)[^>]*data-author', uh) is None
          and "auFilter" not in _SCRIPT.split("function refresh()")[1]
              .split("function natCmp")[0])

    # --- D1: area chips finally read the data-area the renderer always emitted -
    # The phase-row emitter above has stamped space-joined tags into `data-area`
    # since areas landed; until D1 no script read it back. The chip markup is
    # pinned in _report_html's own selftest; what needs a whole document is the
    # WIRING - report.js reads the attribute, gates PHASES on it (multi-select,
    # any tag admits, no tags hides while a selection is active), and carries
    # the selection in the hash as a= - a key distinct from the author's au=.
    _ma = json.loads(json.dumps(manifest))
    _ma["phases"][0]["area"] = ["api", "web"]
    _mah = render_html(_ma, _lib.rollup(_ma, [], []), "audit-report", None)
    check("d1: a tagged plan renders the Area chip row and an untagged plan "
          "omits it (markup pinned in _report_html; this pins the document)",
          'id="audit-areas"' in _mah and 'data-a="api"' in _mah
          and 'id="audit-areas"' not in html_out)
    check("d1: report.js reads data-area off the phase row, splitting the "
          "space-joined tags the emitter writes",
          "getAttribute('data-area')" in _SCRIPT
          and "function areaOk" in _SCRIPT
          and "areaOk(pr)" in _SCRIPT)
    check("d1: the gate is multi-select and any selected tag admits a phase; "
          "with none selected it admits everything",
          "areaFilter.indexOf(tags[i])" in _SCRIPT
          and "if (!areaFilter.length) return true;" in _SCRIPT)
    check("d1: the area selection is a link (a=) and restores from one - "
          "spelled apart from the author's au=, which stays wired",
          "put('a', areaFilter.join(' '));" in _SCRIPT
          and "if (HASH.a)" in _SCRIPT
          and "put('au', auFilter)" in _SCRIPT and "if (HASH.au)" in _SCRIPT)
    check("d1: clear-all lifts the area gate with everything else, and both "
          "the way-back button and the panel count own it "
          "(the reset is pinned INSIDE clearAll - the declaration up top "
          "spells the same bytes and satisfied a whole-script substring)",
          "areaFilter = [];" in _SCRIPT.split("function clearAll()")[1]
          and "|| areaFilter.length > 0" in _SCRIPT
          and "(areaFilter.length ? 1 : 0)" in _SCRIPT)
    check("d1: the chips are wired, not built - report.js attaches behaviour "
          "to the server-rendered row",
          "wireChips(areaBar, 'data-a'" in _SCRIPT
          and "function paintAreas()" in _SCRIPT)

    # --- g: the global filter row (C1/C2) — document-level composition. --------
    # The row's own markup is pinned in _report_html's selftest; what needs a
    # whole document is what render_html feeds it and where it lands.
    check("g1 the sticky top bar carries the global filter row when there is "
          "anything to filter by, with both authors as options",
          'class="gfilters"' in uh
          and uh.index('class="gfilters"') < uh.index('<div class="shell">')
          and 'value="a@x.io"' in uh and 'value="b@x.io"' in uh)
    check("g2 the date bounds are the union of task dates AND ledger days - "
          "one range scopes both surfaces, so it must span both",
          uh.count('min="2026-07-09" max="2026-08-02"') == 2)
    check("g3 without a ledger the row still offers the task-date range, and "
          "no author select (nothing records an author)",
          'id="audit-gfrom"' in html_out
          and 'id="audit-au-select"' not in html_out)
    check("g4 a tagged plan earns the area select",
          'id="audit-area-select"' in _mah
          and 'id="audit-area-select"' not in html_out)
    _bare = {"meta": {"version": 2, "title": "b", "repo": "r"},
             "phases": [{"id": "P1", "title": "p", "status": "pending",
                         "tasks": [{"id": "P1.1", "title": "t",
                                    "status": "pending"}]}]}
    check("g5 nothing to filter by, no row at all",
          'class="gfilters"' not in render_html(
              _bare, _lib.rollup(_bare, [], []), "audit-report", None))
    check("g6 report.js wires the row over the SAME state as the panel and "
          "chips - one range entry point, both date pairs painted",
          "audit-au-select" in _SCRIPT and "audit-area-select" in _SCRIPT
          and "function setRange(" in _SCRIPT
          and "gFrom.value = dFrom" in _SCRIPT
          and "applyUsageRange();" in _SCRIPT.split("function refresh()")[1]
                                            .split("function natCmp")[0])
    check("g7 the row is a flex row OF the sticky bar (print drops it with the "
          "bar - the pinned .topbar print rule - and the range prints instead "
          "as the named line report.js writes into #audit-urange)",
          ".gfilters{flex-basis:100%" in _CSS
          and "audit-urange" in _SCRIPT)

    # --- rd: Ready now as a definition list (C4) --------------------------------
    check("rd1 Ready now is a definition list naming the ready task, and the "
          "old comma-joined mono line is gone",
          '<dl class="ready">' in html_out
          and ">P1.2</code>" in html_out
          and "Ready now</h2><p class=mono>" not in html_out)
    check("rd2 a ready task in a tagged phase wears the area chips inside the "
          "list (same .area-tag style as everywhere else)",
          '<dl class="ready">' in _mah
          and '<span class="area-tag">api</span>'
              in _mah[_mah.index('<dl class="ready">'):])
    check("rd3 the list is styled as a quiet queue, not cards",
          "dl.ready dt" in _CSS and "dl.ready dd" in _CSS)

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

    # --- sg: phase segmentation (D1, v0.36) -----------------------------------
    # On a large plan the Phases table is one long run. Segmentation groups the
    # rows into three blocks — active (in_progress/blocked), pending, done — so
    # the work in motion reads first, and the done run collapses into an
    # archive the reader can expand. The markup is pinned here; whether the
    # collapse and the toggle actually behave is asserted in a browser by
    # tools/check-report-interactive.mjs, because every string below survives a
    # dead script.
    _sgm = {"meta": {"title": "seg"}, "bugs": [], "phases": [
        {"id": "S1", "title": "first done", "status": "done",
         "tasks": [{"id": "S1.1", "title": "t", "status": "done",
                    "commit": "abc1234"}]},
        {"id": "S2", "title": "working", "status": "in_progress",
         "tasks": [{"id": "S2.1", "title": "t", "status": "in_progress"}]},
        {"id": "S3", "title": "queued", "status": "pending",
         "tasks": [{"id": "S3.1", "title": "t", "status": "pending"}]},
        {"id": "S4", "title": "stuck", "status": "blocked",
         "tasks": [{"id": "S4.1", "title": "t", "status": "blocked"}]}]}
    _sgh = render_html(_sgm, _lib.rollup(_sgm, [], []), "r", None)
    check("sg1 a mixed plan renders one seghead per non-empty segment, in "
          "active, pending, done order",
          _sgh.count('<tr class="seghead"') == 3
          and _sgh.index('data-seg="active"') < _sgh.index('data-seg="pending"')
          < _sgh.index('data-seg="done"'))
    check("sg2 phases are grouped under their segments - active rows first, "
          "then pending, then done - whatever the manifest order",
          _sgh.index('id="phase-S2"') < _sgh.index('id="phase-S4"')
          < _sgh.index('id="phase-S3"') < _sgh.index('id="phase-S1"'))
    check("sg3 phase, taskfilter and task rows all carry data-seg, so the "
          "archive gate and the print isolation can select whole segments",
          re.search(r'<tr class="phase" id="phase-S1"[^>]*data-seg="done"', _sgh)
          is not None
          and re.search(r'<tr class="taskfilter" data-phase="S1"[^>]*'
                        r'data-seg="done"', _sgh) is not None
          and re.search(r'<tr class="task" data-phase="S1"[^>]*data-seg="done"',
                        _sgh) is not None)
    check("sg4 the done segment is the archive: its seghead is a toggle that "
          "names the count and starts collapsed, because other segments exist",
          re.search(r'<button[^>]*id="audit-arch"[^>]*aria-expanded="false"',
                    _sgh) is not None
          and "Archive — 1 done phase<" in _sgh)
    _sgd = {"meta": {"title": "alldone"}, "bugs": [], "phases": [
        {"id": "D1", "title": "a", "status": "done",
         "tasks": [{"id": "D1.1", "title": "t", "status": "done"}]},
        {"id": "D2", "title": "b", "status": "done",
         "tasks": [{"id": "D2.1", "title": "t", "status": "done"}]}]}
    _sgdh = render_html(_sgd, _lib.rollup(_sgd, [], []), "r", None)
    check("sg5 an all-done plan keeps its archive OPEN - there is nothing left "
          "to keep prominent, and a table that opens empty explains nothing",
          'id="audit-arch"' not in _sgdh
          and _sgdh.count('<tr class="seghead"') == 1
          and 'data-seg="done"' in _sgdh)
    check("sg6 a single-segment plan still gets its one seghead - the home of "
          "the export controls",
          _fh.count('<tr class="seghead"') == 1
          and 'id="audit-arch"' not in _fh)
    check("sg7 report.js gates the archive inside refresh() and lifts it while "
          "any filter is active - a search must reach the archived rows",
          "archOpen || anyFilter || pr.__seg !== 'done'" in _SCRIPT
          and "audit-arch" in _SCRIPT)
    check("sg8 print: a page break lands before every segment header except "
          "the first, and the header itself always prints",
          "tr.seghead{break-before:page;display:table-row!important}" in _print
          and "#phases tbody tr.seghead:first-child{break-before:auto}"
          in _print)
    check("sg9 the archive prints EXPANDED - the pinned whole-plan rule "
          "already forces every row onto paper, and the stylesheet argues the "
          "choice where the rules live",
          "tr.phase,tr.task{display:table-row!important" in _print
          and "archive prints expanded" in _CSS.lower())

    # --- ex: per-segment export (D2, v0.36) -----------------------------------
    # CSV of the data, PNG of the charts (redrawn from the embedded data onto a
    # canvas - never DOM-to-canvas), and a print mode that isolates one
    # segment. All markup pinned here; the downloads themselves are driven in
    # tools/check-report-interactive.mjs, where the file that leaves the
    # browser is read back and checked.
    check("ex1 every seghead carries its CSV and Print controls, named by "
          "segment",
          _sgh.count("data-segcsv=") == 3 and _sgh.count("data-segprint=") == 3
          and 'data-segcsv="done"' in _sgh and 'data-segprint="active"' in _sgh)
    check("ex2 the bugs table earns a CSV control beside its heading; a "
          "bugless plan renders none",
          'data-csv="bugs"' in html_out and 'data-csv="bugs"' not in _sgh)
    check("ex3 the CSV leaves as RFC 4180 with Excel's BOM, through the same "
          "blob-anchor download the .md button uses",
          "replace(/\"/g, '\"\"')" in _SCRIPT and "\\ufeff" in _SCRIPT
          and "text/csv;charset=utf-8" in _SCRIPT)
    check("ex4 the chart exports redraw from data onto a canvas and leave as "
          "PNG",
          "toDataURL('image/png')" in _SCRIPT
          and 'data-png="trend"' in uh and 'data-png="heatmap"' in uh)
    check("ex5 print-to-PDF per segment: the button stamps body[data-printseg], "
          "print CSS isolates that segment, and afterprint restores the page",
          "data-printseg" in _SCRIPT
          and "body[data-printseg] .content>*:not(#phases){display:none"
              "!important}" in _print
          and 'body[data-printseg="active"]' in _print
          and 'body[data-printseg="pending"]' in _print
          and 'body[data-printseg="done"]' in _print
          and "removeAttribute('data-printseg')" in _SCRIPT)
    check("ex6 the export controls never reach paper",
          ".segx,.secx{display:none!important}" in _print)

    # --- ow: advisory area owner chips (D4, v0.36) ----------------------------
    # meta.areas[tag].owner (v0.34, advisory) surfaces wherever the report
    # shows a tag: a small suffix on the tag chip, and a title on the filter
    # chip and the global select option - the same `owner: <who>` wording the
    # panel's area select already uses. Advisory only; an area with no owner
    # (or an explicit null) shows exactly what it always did.
    _mo = json.loads(json.dumps(manifest))
    _mo["phases"][0]["area"] = ["api", "web"]
    _mo["meta"]["areas"] = {"api": {"owner": "ana@x.io"},
                            "web": {"owner": None},
                            "infra": {"description": "unused"}}
    _moh = render_html(_mo, _lib.rollup(_mo, [], []), "audit-report", None)
    check("ow1 a registered owner rides the tag as a small advisory suffix on "
          "the phase row, with the panel's exact title wording",
          '<span class="area-tag" title="owner: ana@x.io">api'
          '<span class="aown">' in _moh)
    check("ow2 the filter chip and the global select option say the same "
          "through their titles",
          'data-a="api" title="owner: ana@x.io"' in _moh
          and '<option value="api" title="owner: ana@x.io">api</option>' in _moh)
    check("ow3 an area with no owner - or an explicit null - shows exactly "
          "what it always did",
          '<span class="area-tag">web</span>' in _moh
          and 'title="owner:' not in _mah)
    check("ow4 the Ready-now list wears the same suffix on its tags",
          '<dl class="ready">' in _moh
          and 'title="owner: ana@x.io"'
              in _moh[_moh.index('<dl class="ready">'):])
    _mx = json.loads(json.dumps(_mo))
    _mx["meta"]["areas"] = {"api": {"owner": '<script>alert(1)</script>'}}
    check("ow5 a hostile owner is escaped before it reaches an attribute",
          "<script>alert" not in render_html(
              _mx, _lib.rollup(_mx, [], []), "r", None).replace(_SCRIPT, ""))

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

    check("u24 the hover layer re-renders the mark's own title — never a second "
          "copy of the numbers — so JS-off keeps the native tooltip",
          "__tip" in uh and "removeAttribute('title')" in uh
          and uh.count("split('\\t')") == 1)
    check("u24b hover is delegated, not one listener per mark",
          uh.count("addEventListener('mouseover'") == 1
          and "mouseenter" not in uh)
    check("u24c the floating tooltip is suppressed for print",
          "@media print{.rtip{display:none!important}" in uh)
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
