#!/usr/bin/env python3
"""
The audit report as a whole document: the vocabulary, the table, and the page.

Moved out of render-report.py (P13.3), which is left holding `main()` — argument
parsing, the manifest read, the theme resolve, the files it writes — and the
suite that reads what those files contain. This module is the assembly step in
between: which optional columns a plan has earned, what holds a phase, the rows
one phase emits, and `render_html`, which glues `_report_html`'s fragments and
`_report_usage`'s section into one self-contained page (or, with
`fragment=True`, into the same page with no document wrapper, for a host that
supplies its own).

WHY THE GATE VERDICT IS AN ARGUMENT AND NOT A CALL. The verdict at the top of
the report is the CI gate's own word, and the gate lives in `audit-status.py` —
an entry point, layer 7, which `_loader` loads at runtime. Reaching it from here
would be a helper calling UP, the one direction `_deps.layer_violations()`
refuses (and it reads `_loader` calls, so it would see it). So `render_html`
takes `verdict` as a callable the caller supplies; render-report.py owns
`_verdict`/`_load_status_lib` and injects it, keeping that edge L7 -> L7 exactly
where `_deps.KNOWN_LAYER_DEBT` already records it. With no verdict supplied the
hero renders the "could not be evaluated" state the product already has for a
gate that raises — an honest unknown, never a fabricated Clear.

Imports go one way only: `_report_md` (the Markdown twin this page embeds),
`_report_usage`, `_report_ui`, `_report_html` and `_manifest_io` (layer 1, which
owns reading a manifest's shape) are all below this file; it must never import
render-report.
"""
import base64
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _manifest_io  # noqa: E402  (one home for reading a manifest's shape)
import _report_ui    # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html  # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)
import _report_usage  # noqa: E402  (the Usage section: ledger load, charts, markdown twin)
import _report_md    # noqa: E402  (the Markdown twin this page embeds base64)


# --- module aliases (CSS/SCRIPT, fragment + usage re-exports) -------------------
# Chip and pipeline-rail colors live in the report's CSS theme tokens (see _CSS),
# keyed off the `data-status` / `data-risk` attributes the markup carries — so a
# single token set themes every status/risk consistently in both light and dark.
_CSS = _report_ui.CSS

# Inline, self-contained (no external fetch) filter/sort/search over the report
# tables. Progressive enhancement: the report is fully readable with JS off.
_SCRIPT = _report_ui.SCRIPT

# HTML fragment builders (escaping, chips, cells, filter panel) live in
# _report_html.py (P13.1) — bottom of the report's module graph, imported by
# nothing upward. Aliased here so the call sites below read as they did when all
# of this was one file.
e = _report_html.e
_areas_of = _report_html._areas_of
_bug_view = _report_html._bug_view
_chip_buttons = _report_html._chip_buttons
_chip = _report_html._chip
_ado_cell = _report_html._ado_cell
_outcome_text = _report_html._outcome_text
_short_date = _report_html._short_date
_timing_cell = _report_html._timing_cell
_commit_cell = _report_html._commit_cell
_detail_row = _report_html._detail_row
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
_tasks_by_id = _report_html._tasks_by_id

# The Usage section — the ledger load, every chart in it and the Markdown twin
# of the whole block — lives in _report_usage.py (P13.2).
_usage_section = _report_usage._usage_section

# The Markdown twin, embedded base64 as the "Download .md" payload. This is the
# one edge that makes _report_md non-optional for anyone taking this file.
render_md = _report_md.render_md


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


# --- report vocab ---------------------------------------------------------------
def _plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


# The conditions in the reader's words. `open-high-bugs` is a flag name; printing it
# raw makes the basis look like a config dump and quietly assumes the reader knows
# the CLI. The flag names still appear in the title attribute for whoever is going
# to type them. (Their COUNTS are worded by render-report's `_GATE_WORDS`, which
# sits beside `_verdict` because only that side knows what failed.)
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
# ex (F-P-4): which of the optional columns the COMPACT row carries. The rest
# (model, the work item, the outcome) live in the detail row, where they have
# room to be complete rather than truncated. Chosen by what a reader scans for:
# where is it, how risky is it, when did it land, which commit. The outcome was
# the worst offender in the other direction — a 70-character cut that pushed
# every row to three lines and still said too little, which is the complaint
# this whole change came from.
PRIMARY_COLS = ("risk", "commit", "done")
_OPTIONAL_COLS = (
    ("model", lambda t: t.get("model")),
    ("risk", lambda t: t.get("risk")),
    ("commit", lambda t: t.get("commit")),
    ("done", lambda t: t.get("completedAt") or t.get("startedAt")),
    ("ADO", lambda t: (t.get("ado") or {}).get("id")
     if isinstance(t.get("ado"), dict) else None),
    ("outcome", lambda t: _outcome_text(t)),
)


# --- table helpers --------------------------------------------------------------
def _present_columns(manifest):
    """The optional columns at least one task actually fills."""
    # Every task, id or not: a column is earned by a task FILLING it, and a task
    # with no `id` fills `ado` or `outcome` exactly as well as one that has an id.
    # `iter_tasks`, therefore, and not `_tasks_by_id` — the index drops id-less
    # tasks by contract, which here would silently un-earn a column.
    tasks = [t for _, t in _manifest_io.iter_tasks(manifest)]
    out = []
    for name, get in _OPTIONAL_COLS:
        try:
            if any(get(t) not in (None, "", [], {}) for t in tasks):
                out.append(name)
        except Exception:                 # a malformed task never removes a column
            out.append(name)
    return out


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
    # bl (F-P-4): blocked TASKS inside a phase that is not itself blocked. The
    # phase chip answers "is this phase blocked"; nothing answered "is anything
    # in it stuck", which is the question that decides whether a phase in
    # progress is actually moving. Emitted only when it says something the chip
    # does not — on a blocked phase the chip already carries the word.
    _nblocked = sum(1 for t in (ph.get("tasks") or [])
                    if isinstance(t, dict) and t.get("status") == "blocked")
    blocked_mark = ""
    if _nblocked and psum["status"] != "blocked":
        blocked_mark = ('<span class="pblocked" title="%d task(s) in this phase '
                        'are blocked">%d blocked</span>'
                        % (_nblocked, _nblocked))
    # ...and the dropped ones, for the same reason: a bar reading 3/5 on a phase
    # whose other two tasks were cancelled is a phase that is finished, and the
    # bar cannot say so on its own.
    _ncancelled = sum(1 for t in (ph.get("tasks") or [])
                      if isinstance(t, dict) and t.get("status") == "cancelled")
    cancelled_mark = ('<span class="pcancelled" title="%d task(s) in this phase '
                      'were cancelled">%d cancelled</span>'
                      % (_ncancelled, _ncancelled)) if _ncancelled else ""
    out.append(
        '<tr class="phase" id="phase-%s" data-phase="%s" data-status="%s"%s '
        'data-seg="%s" data-area="%s" tabindex="0" '
        'aria-expanded="false"><td colspan="%d"><span class="tri"></span> '
        '<span class="mono">%s</span> <strong>%s</strong>%s %s%s%s%s%s %s'
        '<span class="pmatch" hidden></span>%s</td></tr>'
        % (e(pid), e(pid), e(psum["status"]),
           ' data-held="1"' if held else "",
           seg, e(" ".join(areas)), ncol, e(pid), e(psum["title"]),
           area_tags, _chip(psum["status"]), blocked_mark, cancelled_mark,
           held_mark, stamp,
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
            "commit": lambda: "<td class=mono>%s</td>" % _commit_cell(t),
            "done": lambda: "<td class=when>%s</td>" % _timing_cell(t),
            "ADO": lambda: "<td>%s</td>" % _ado_cell(t),
            "outcome": lambda: "<td class=muted>%s</td>" % e(_outcome_text(t)),
        }
        # ex (F-P-4): the compact row plus a control that opens the rest. The
        # button lives in the id cell and carries the task id, so a keyboard
        # reader tabs id -> detail rather than hunting a bare chevron.
        out.append(
            '<tr class="task" data-phase="%s" data-seg="%s" data-status="%s"%s%s>'
            '<td class="mono tid"><button type="button" class="dtoggle" '
            'data-dfor="%s" aria-expanded="false" aria-label="Show details for '
            '%s"></button>%s</td><td>%s</td><td>%s</td>%s</tr>'
            % (e(pid), seg, e(t.get("status")),
               ' data-held="1"' if held else "",
               _filter_attrs(t),
               e(t.get("id")), e(t.get("id")),
               e(t.get("id")), e(t.get("title")),
               _chip(t.get("status")),
               "".join(cells[c]() for c in cols)))
        out.append(_detail_row(t, ph, owners, ncol, seg, pid))
    return "\n".join(out)


def render_html(manifest, summary, basename="audit-report", usage=None,
                fragment=False, css=None, verdict=None):
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

    `verdict` is `render-report._verdict` or anything with its shape: called with
    `summary`, it answers `(gate, why, conds)`. It is injected rather than called
    directly because the gate lives in an entry point this module sits below —
    see the module docstring. Omitted, the hero renders the same "could not be
    evaluated" state a gate that raised already produces.
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
            # th (F-P-6): the project's own theme when it has one. The
            # report is a FILE — mailed, published, opened months later —
            # so the stylesheet is embedded compiled, never fetched, and a
            # theme travels with the report rather than living in a panel.
            "<style>%s</style>" % (css or _CSS)]
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
    for _, _t in _manifest_io.iter_tasks(manifest):
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
    gate, why, conds = verdict(summary) if verdict else (None, [], [])
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
           '☾</button>')
        + '</div>')
    # The chips are rendered HERE, not built by the script. Built in JS they were
    # invisible to anything that does not run it — a printed page, a reader with
    # scripting off — which is the one context where "the filters are gone" is
    # indistinguishable from "the filters are broken". Server-rendered they are
    # always present; the script only attaches behaviour to them.
    _phase_statuses = sorted({p["status"] for p in summary["phases"] if p.get("status")})
    table_tools = (
        '<div class="toolbar sectools" role="search" aria-label="Filter the phases table">'
        '<input id="audit-q" type="search" aria-label="Filter phases and tasks by text" '
        'placeholder="Filter phases &amp; tasks by text…">'
        '<span class="tbl">Phase status:</span><span id="audit-phase-status">%s</span>'
        '%s'
        # vw (F-P-4): WHICH phases are on screen, said out loud. The archive used
        # to be a toggle nobody found — a plan with forty done phases opened
        # looking half-empty and there was no control saying why. Three named
        # views, the default is the work that is left, and the select carries
        # the answer even with the script dead.
        '<span class="viewpick"><label class="tbl" for="audit-view">View:</label>'
        '<select id="audit-view" aria-label="Which phases to show">'
        '<option value="active">Active &amp; pending</option>'
        '<option value="archived">Archived (done &amp; cancelled)</option>'
        '<option value="all">All phases</option></select></span>'
        '<button type="button" id="audit-expand" class="btn">expand all</button>'
        # Shown only while something is actually filtering. It is a second copy of
        # the empty state's button on purpose: the More-filters panel is drawn OVER
        # the top of the table, so when a filter leaves no rows at all, the empty
        # state — and the only way back from it — ends up underneath the very panel
        # that caused it. A browser click found that; no string check could.
        '<button type="button" class="btn" data-clear hidden>Clear filters</button>'
        '<span id="audit-count" class="muted"></span>'
        "<noscript><span class=\"tbl\">Filtering and collapsing need JavaScript "
        "— every row is shown.</span></noscript></div>"
        % (_chip_buttons(_phase_statuses, "data-ps", "fchip"),
           _filter_panel(manifest)))

    # One collapsible table: each phase is a group-row (click to expand its task
    # rows). Default-collapsed via _SCRIPT; with JS off every row is visible.
    out.append('<section id="%s" class="sec">' % section("phases", "Phases",
                                                        len(summary["phases"])))
    out.append(table_tools)
    # `present` is every optional column this plan HAS data for; `cols` is the
    # subset the compact row shows. The detail row renders the difference, so
    # nothing is dropped from the page — only from the row.
    present = _present_columns(manifest)
    cols = [c for c in present if c in PRIMARY_COLS]
    ncol = 3 + len(cols)
    # vw: 'active' unless there is nothing active or pending to show — a
    # finished plan that greeted its reader with an empty table would be the
    # archive toggle's own failure wearing a select. Decided here, where the
    # statuses are, and read by report.js as the starting view.
    _segs_present = {_seg_of(p["status"]) for p in summary["phases"]}
    _defview = "active" if (_segs_present & {"active", "pending"}) else "all"
    # tm: the zone is named ONCE, in the header, rather than repeated in every
    # cell or left for a reader to assume.
    _colhead = {"done": 'done <span class="muted">UTC</span>'}
    out.append('<div class="tablewrap"><table class="phases" '
               'data-defaultview="%s"><thead><tr>'
               "<th>id</th><th>title</th><th>status</th>%s</tr></thead><tbody>"
               % (_defview,
                  "".join('<th data-col="%s">%s</th>' % (e(c), _colhead.get(c, e(c)))
                          for c in cols)))
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
        # vw: every seghead is now a plain title. Which segments are ON SCREEN
        # is the view select's business, and a segment that also hid itself
        # would be a second, contradictory gate.
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
    # vw: matches the VIEW is hiding. The archive gate used to lift itself
    # during a search, which meant the control said one thing and the table did
    # another; this says the true thing instead — how many matched, and the one
    # press that shows them.
    out.append('</tbody><tbody><tr class="norows"><td colspan="%d">'
               "No phase matches these filters."
               '<button type="button" class="btn" data-clear>Clear filters'
               "</button></td></tr>"
               '<tr class="outside" data-outside hidden><td colspan="%d">'
               '<span data-outside-n></span>'
               '<button type="button" class="btn" data-viewall>Show all phases'
               "</button></td></tr>"
               "</tbody></table></div></section>" % (ncol, ncol))
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


# --- selftest -------------------------------------------------------------------
def _selftest():
    import ast
    import re

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" (%s)" % detail) if detail and not ok else ""))

    # WHAT IS NOT HERE, AND WHY. The ~230 cases that pin the rendered document —
    # its markup, its emission ORDER, the stylesheet and the embedded script —
    # live with render-report.py, because they read a report written by `main()`
    # into a temp directory and a fragment module cannot write one. Splitting
    # them across two files by which function happens to emit each string would
    # have made both suites unreadable and neither complete. What is asserted
    # here is what this module decides on its OWN: the two seams the split
    # created, and the vocabulary that came with it.
    _m = {"meta": {"title": "page", "repo": "r"}, "bugs": [], "phases": [
        {"id": "P1", "title": "one", "status": "done",
         "tasks": [{"id": "P1.1", "title": "t", "status": "done",
                    "commit": "abc1234", "completedAt": "2026-01-02T00:00:00Z"}]},
        {"id": "P2", "title": "two", "status": "pending", "blockedBy": ["P1", "P3"],
         "tasks": [{"id": "P2.1", "title": "t", "status": "pending"}]}]}
    _s = {"valid": True, "findings": 0, "ready": ["P2.1"],
          "tasks": {"total": 2, "byStatus": {"done": 1, "pending": 1}},
          "bugs": {"total": 0, "open": 0, "openHighSeverity": 0},
          "phases": [{"id": "P1", "title": "one", "status": "done",
                      "done": 1, "total": 1},
                     {"id": "P2", "title": "two", "status": "pending",
                      "done": 0, "total": 1}]}

    # --- the _report_md seam ---------------------------------------------------
    # The one edge that makes _report_md non-optional for anyone taking this
    # file: the page carries the Markdown twin as its "Download .md" payload, so
    # the two modules ship together or the button downloads something else.
    # Decoded and compared whole rather than probed for a phrase — a truncated or
    # differently-built payload passes every `in` test the phrase version could
    # make.
    _doc = render_html(_m, _s, "b", None)
    _mark = 'window.AUDIT_MD_B64="'
    _i = _doc.index(_mark)
    _blob = _doc[_i + len(_mark):_doc.index('"', _i + len(_mark))]
    check("pg1 the page embeds the Markdown twin base64, byte-for-byte what "
          "_report_md renders for the same plan - the Download .md button is "
          "this edge, and a split that dropped _report_md would break it",
          base64.b64decode(_blob).decode("utf-8")
          == _report_md.render_md(_m, _s, None))
    check("pg1b ...under the basename it was given, so two reports in one "
          "directory do not both offer to save 'audit-report.md'",
          'window.AUDIT_MD_NAME="b.md"' in _doc)

    # --- the verdict seam ------------------------------------------------------
    # The gate lives in audit-status.py, an ENTRY POINT this module sits below.
    # Calling it here would be a helper reaching up, which is the one direction
    # _deps.layer_violations() refuses - and it reads _loader calls, so it would
    # see it. The verdict is therefore injected.
    _called = []

    def _fake_verdict(summary):
        _called.append(summary)
        return "blocked", ["1 blocked task"], ["invalid", "blocked-tasks"]

    _vh = render_html(_m, _s, "b", None, verdict=_fake_verdict)
    # Read off the hero's own opening tag, never the whole document: `data-gate`
    # is also a SELECTOR in the embedded stylesheet (`.overall[data-gate=
    # "clear"]`), so a whole-document substring is satisfied by the CSS alone and
    # would pass with no verdict rendered at all.
    _hero = re.compile(r'<section class="overall"[^>]*>')
    check("pg2 a supplied verdict is the word in the hero, with its conditions "
          "spelled in the reader's words and the flag names kept for typing",
          len(_called) == 1
          and 'data-gate="blocked"' in _hero.search(_vh).group(0)
          and ">Blocked</p>" in _vh
          and "1 blocked task" in _vh
          and "manifest validity, blocked tasks" in _vh
          and "--fail-on invalid,blocked-tasks" in _vh)
    # The other direction. A hero that manufactured "Clear" from a missing
    # verdict would pass pg2 and would be the worst possible defect in this
    # file: an unevaluated gate reading as a passing one.
    check("pg2b no verdict is reported as UNKNOWN, never as clear - an "
          "unevaluated gate that reads as a passing one is the one failure a "
          "verdict hero must not have",
          "data-gate" not in _hero.search(_doc).group(0)
          and ">Unknown</p>" in _doc
          and "The gate could not be evaluated." in _doc
          and ">Clear</p>" not in _doc)
    # The seam is only real if this module genuinely never reaches the entry
    # point, so it is asserted in the two shapes `_deps` itself reads: an
    # `import` of `_loader`, and a `"....py"` literal that a loader call could
    # carry. Read off the AST rather than grepped, because both the docstring
    # above and the hero's own `title="audit-status.py --gate ..."` mention the
    # names in prose that is not an edge.
    with open(os.path.abspath(__file__), "r", encoding="utf-8") as _fh:
        _src = _fh.read()
    _tree = ast.parse(_src)
    # The PRODUCTION half only: this function's own `.endswith(".py")` is a
    # literal ending in `.py`, and scanning it would report the check itself.
    _tree.body = [_n for _n in _tree.body
                  if not (isinstance(_n, ast.FunctionDef)
                          and _n.name == "_selftest")]
    _imported = set()
    for _n in ast.walk(_tree):
        if isinstance(_n, ast.Import):
            for _a in _n.names:
                _imported.add(_a.name.split(".")[0])
        elif isinstance(_n, ast.ImportFrom) and not _n.level:
            _imported.add((_n.module or "").split(".")[0])
    _py_literals = sorted(set(
        _n.value for _n in ast.walk(_tree)
        if isinstance(_n, ast.Constant) and isinstance(_n.value, str)
        and _n.value.endswith(".py")))
    check("pg2c ...and this module can reach no entry point at all: it imports "
          "no _loader and spells no '.py' target, so the audit-status edge "
          "stays L7 -> L7 where KNOWN_LAYER_DEBT records it. %r"
          % (_py_literals,),
          "_loader" not in _imported and _py_literals == [])

    # --- the vocabulary that moved with the page -------------------------------
    check("pg3 density follows the data: a plan on day one has earned none of "
          "the optional columns, and ONE task filling one earns exactly it",
          _present_columns({"phases": [{"tasks": [{"id": "x"}]}]}) == []
          and _present_columns(_m) == ["commit", "done"])
    # Both directions on the one optional column that is empty for almost every
    # repo: it appears for a repo that syncs, and a task whose `ado` is not an
    # object does not manufacture it. Dropping the isinstance guard in
    # `_OPTIONAL_COLS` makes the getter raise, `_present_columns` swallows that
    # into "keep the column", and the second half goes red.
    check("pg3b the ADO column belongs to repos that actually sync to Azure "
          "DevOps - and a task whose `ado` is not an object does not conjure it",
          _present_columns({"phases": [{"tasks": [{"ado": {"id": 7}}]}]})
          == ["ADO"]
          and _present_columns(
              {"phases": [{"tasks": [{"ado": "not-an-object"}]}]}) == [])
    check("pg4 a phase is held only by blockers that are NOT done - the rail "
          "draws dependency, not a second copy of status",
          _held_by(_m["phases"][1], {"P1"}) == ["P3"]
          and _held_by(_m["phases"][1], {"P1", "P3"}) == []
          and _held_by({}, set()) == [])
    check("pg5 counts are worded, and the irregular plural is the caller's to "
          "give (`1 phase` / `2 phases`, `1 open bug` / `0 open bugs`)",
          _plural(1, "phase") == "1 phase" and _plural(2, "phase") == "2 phases"
          and _plural(0, "open bug") == "0 open bugs"
          and _plural(2, "entry", "entries") == "2 entries")

    # --- one page, three surfaces ---------------------------------------------
    # `fragment=True` is the Artifact mode. The document-level pins live with
    # render-report; what is asserted here is the DIFFERENCE the flag makes,
    # counted in both directions so a flag that did nothing fails.
    _frag = render_html(_m, _s, "b", None, fragment=True)
    check("pg6 the fragment drops the document wrapper and the theme toggle "
          "(the host supplies both) and keeps everything else",
          not any(t in _frag.lower() for t in
                  ("<!doctype", "<html", "</html>", "<meta charset"))
          and 'id="audit-theme"' not in _frag
          and "<title>" in _frag and '<table class="phases"' in _frag
          and "<!doctype html>" in _doc and 'id="audit-theme"' in _doc)
    # css=... is how a project's compiled theme reaches the page; the default is
    # the shipped sheet. Counted, because a page carrying BOTH would be a
    # stylesheet fight the reader loses at random.
    _themed = render_html(_m, _s, "b", None, css="/*THEMED*/")
    check("pg7 a supplied stylesheet replaces the shipped one rather than "
          "joining it - two <style> blocks is a cascade race, not a theme",
          _themed.count("<style>") == 1 and "/*THEMED*/" in _themed
          and _CSS not in _themed and _CSS in _doc)

    # --- _phase_rows -----------------------------------------------------------
    # The rows one phase emits. `data-seg` on EVERY one of them is what the view
    # gate and the per-segment print isolation select by; a row missing it is a
    # row that neither can reach.
    _rows = _phase_rows(_m["phases"][0], _s["phases"][0], "archived", 3, [],
                        {"P1"}, {})
    check("pg8 a phase emits its group row, its task-status filter row and one "
          "row per task, and every one of them carries the segment",
          _rows.count('<tr class="phase"') == 1
          and _rows.count('<tr class="taskfilter"') == 1
          and _rows.count('<tr class="task"') == 1
          and _rows.count('data-seg="archived"') == 4)  # 3 rows + the detail row
    check("pg8b a malformed task is skipped without taking the phase's other "
          "rows with it",
          _phase_rows({"tasks": ["not-a-dict"]},
                      {"id": "P9", "title": "t", "status": "pending",
                       "done": 0, "total": 0},
                      "pending", 3, [], set(), {}).count("<tr ") == 2)
    # Every manifest string is untrusted JSON. The document-level x* cases prove
    # the whole page escapes; this proves the row builder does, which is where a
    # `%s` added later would land.
    _evil = _phase_rows(
        {"tasks": [{"id": "<script>alert(1)</script>", "title": "t",
                    "status": "pending"}]},
        {"id": "<img src=x>", "title": "<b>", "status": "pending",
         "done": 0, "total": 1}, "pending", 3, [], set(), {})
    check("pg9 a hostile id or title is escaped where the row is built, not "
          "only somewhere further up - and it is escaped, not deleted",
          "<script>" not in _evil and "<img src=x>" not in _evil
          and "&lt;script&gt;" in _evil and "&lt;img src=x&gt;" in _evil
          and "&lt;b&gt;" in _evil)
    check("pg10 the compact row shows only the columns it was handed; the rest "
          "of what the plan HAS lives in the detail row",
          _phase_rows(_m["phases"][0], _s["phases"][0], "archived", 5,
                      ["commit", "done"], {"P1"}, {}).count("<td") -
          _rows.count("<td") == 2
          and re.search(r'<tr class="taskdetail"', _rows) is not None)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    sys.exit(_selftest() if "--selftest" in sys.argv else 0)
