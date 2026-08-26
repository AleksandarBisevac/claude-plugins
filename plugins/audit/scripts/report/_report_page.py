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

The page is assembled from BLOCK EMITTERS, each returning `(parts, records)` —
its HTML lines and the Contents-nav entries for the anchors in them. The nav and
the anchors were once kept in step by a `section()` closure appending to a list
both halves read, with a comment asking the next reader to remember to call it;
returning them together makes that one value from one place instead. The header
above `_anchor()` states the contract, including why `parts` is a list.

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
`_report_usage`, `_report_ui`, `_report_html`, `_status_facts` (layer 2, for
`is_parked_proposal`) and `_manifest_io` (layer 1, which owns reading a
manifest's shape) are all below this file; it must never import render-report.
`_status_facts` is imported for that ONE predicate and nothing else -- the gate
verdict it also holds still arrives as the injected `verdict` callable, because
retiring that edge is a separate decision from sharing a word.

This module carries no `--selftest` of its own any more; its cases live in
`plugins/audit/tests/test__report_page.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`. One of them, `pg2c`, parses THIS file and
fails if it ever grows an `import _loader` or a `".py"` literal.
"""
import base64
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

import _fmt          # noqa: E402  (the no-domain number/text formatters, incl. plural)
import _manifest_io  # noqa: E402  (one home for reading a manifest's shape)
import _report_ui    # noqa: E402  (CSS/SCRIPT, off disk as real files under ui/)
import _report_html  # noqa: E402  (HTML fragment builders: escaping, chips, cells, filter panel)
import _report_usage  # noqa: E402  (the Usage section: ledger load, charts, markdown twin)
import _report_md    # noqa: E402  (the Markdown twin this page embeds base64)
import _status_facts  # noqa: E402  (layer 2: what `parked` means, decided once)


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


# The version of the plugin that rendered this file. A report outlives the tree it
# came from - mailed, parked in a CI artifact, opened next week - so when someone
# says a control does not work, the first thing worth knowing is which renderer
# wrote the page in front of them. An ALIAS, not a copy: the panel stamps the same
# fact and two implementations would be two answers the first time one was fixed.
_plugin_version = _output.plugin_version


# --- report vocab ---------------------------------------------------------------
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
# `tests` is earned by a POINTER and by nothing else. Reading a declared gate
# instead would put a column of `No evidence` on every manifest written before
# the field existed - and `tools/check-rendered-artifacts.py` compares the
# committed example byte for byte against a fresh render, so a column that
# appears on a plan pointing at no run is a red build, correctly.
PRIMARY_COLS = ("risk", "commit", "done", "tests")
_OPTIONAL_COLS = (
    ("model", lambda t: t.get("model")),
    ("risk", lambda t: t.get("risk")),
    ("commit", lambda t: t.get("commit")),
    ("done", lambda t: t.get("completedAt") or t.get("startedAt")),
    ("tests", lambda t: _report_html.tev_pointer(t)),
    ("ADO", lambda t: (t.get("ado") or {}).get("id")
     if isinstance(t.get("ado"), dict) else None),
    ("outcome", lambda t: _outcome_text(t)),
)


# --- table helpers --------------------------------------------------------------
def _present_columns(manifest, evidence=None):
    """The optional columns at least one task actually fills.

    `tests` needs BOTH halves and that is why this grew an argument: a task
    carrying a pointer is what EARNS the column, and a loaded record is what
    FILLS it. `render-report` supplies the second exactly when the first exists -
    `load_evidence` answers None on the same predicate - so the two only come
    apart for a caller that renders a pointered plan with no model, and drawing
    that reader a column of em dashes would be the report claiming it looked at
    the record and found nothing there."""
    # Every task, id or not: a column is earned by a task FILLING it, and a task
    # with no `id` fills `ado` or `outcome` exactly as well as one that has an id.
    # `iter_tasks`, therefore, and not `_tasks_by_id` — the index drops id-less
    # tasks by contract, which here would silently un-earn a column.
    tasks = [t for _, t in _manifest_io.iter_tasks(manifest)]
    out = []
    for name, get in _OPTIONAL_COLS:
        if name == "tests" and evidence is None:
            continue
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


# --- phase rows ----------------------------------------------------------------
def _phase_rows(ph, psum, seg, ncol, cols, done_ids, owners, workers=None,
                prank=None, evidence=None):
    """One phase's rows — the group row, its task-filter row and its task rows.

    Extracted from render_html's former inline loop when segmentation (D1)
    made the iteration two levels deep; the MARKUP is byte-identical to what
    the loop emitted, plus `data-seg` on every row (the hook the archive gate
    and the per-segment print isolation select whole segments by) and the
    advisory owner suffix on the area tags (D4).

    pr: `prank` is this phase's position in EXECUTION order, from
    `_priority.ranks` — the number the sort control orders by, rather than a
    rule the script re-derives. `None` means no phase in the plan is pinned and
    the attribute is left off entirely, so the row is byte-identical to what it
    was before the sort option existed.

    `evidence` is `_evidence_view.load_evidence`'s answer, or None on a plan that
    points at no recorded run. The phase row then wears TWO marks and they are
    labelled apart: the run the gate this phase signs off with recorded, and an
    aggregate over its tasks' own runs. Merging them into one verdict would claim
    a measurement nobody made - the phase gate and a task gate are different
    commands over different files."""
    pid = psum["id"]
    tviews = (evidence or {}).get("tasks") or {}
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
        'data-seg="%s" data-area="%s"%s tabindex="0" '
        'aria-expanded="false"><td colspan="%d"><span class="tri"></span> '
        '<span class="mono">%s</span> <strong>%s</strong>%s %s%s%s%s%s %s'
        '<span class="pmatch" hidden></span>%s</td></tr>'
        % (e(pid), e(pid), e(psum["status"]),
           ' data-held="1"' if held else "",
           seg, e(" ".join(areas)),
           "" if prank is None else ' data-porder="%d"' % prank,
           ncol, e(pid), e(psum["title"]),
           area_tags, _chip(psum["status"]), blocked_mark, cancelled_mark,
           held_mark, stamp,
           _bar(psum["done"], psum["total"])
           + _report_html._tev_phase_marks(
               ((evidence or {}).get("phases") or {}).get(str(pid))),
           _phase_meta_div(ph)))
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
            "tests": lambda: '<td class="tevcell">%s</td>'
                             % _report_html._tev_cell(tviews.get(str(t.get("id")))),
            "ADO": lambda: "<td>%s</td>" % _ado_cell(t),
            "outcome": lambda: "<td class=muted>%s</td>" % e(_outcome_text(t)),
        }
        tview = tviews.get(str(t.get("id")))
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
               _filter_attrs(t, tview),
               e(t.get("id")), e(t.get("id")),
               e(t.get("id")), e(t.get("title")),
               _chip(t.get("status")),
               "".join(cells[c]() for c in cols)))
        out.append(_detail_row(t, ph, owners, ncol, seg, pid, workers, tview))
    return "\n".join(out)


# --- section emitters -----------------------------------------------------------
# A SECTION RECORD is `(anchor, label, count, sub)` — one entry in the Contents
# nav. Every emitter below returns `(parts, records)`: the HTML lines it
# contributes, and the nav entries for the anchors those lines carry.
#
# That pairing is the whole point of the shape. The nav and the anchors used to be
# kept in step by a `section()` closure appending to a list both halves read, with
# a comment asking the next reader to remember to call it — the same trap as a
# hand-maintained list, since adding a section and linking it were two separate
# acts and only one of them showed. Here they are ONE value returned from ONE
# place: an emitter cannot put its markup on the page without also handing back
# the nav entry, because `render_html` takes both out of the same return.
#
# `parts` is a LIST, never a pre-joined string, and the distinction is
# load-bearing: `[]` means "this block contributes nothing" while `[""]` means
# "one empty line". `_usage_block` genuinely returns the second when there is no
# ledger, and collapsing the two would move a newline in every report that has no
# Usage section.


def _anchor(record):
    """The id a section's own markup must carry, read off its nav entry.

    Named rather than spelled `record[0]` at four call sites: the anchor in the
    markup and the anchor in the nav are the same value BY CONSTRUCTION here, and
    a bare index would hide that they are one fact rather than two that agree.
    """
    return record[0]


def _head_block(meta, css, fragment):
    """The document wrapper, the page title and the one inline stylesheet."""
    # doctype + charset so the file renders standalone (not quirks mode) and its
    # UTF-8 punctuation (·, —, …) decodes correctly when opened from disk.
    parts = [] if fragment else [
        '<!doctype html>',
        # `lang` is why this element is emitted at all: without it a screen
        # reader guesses the language and can read the whole report in the wrong
        # voice. The control panel has always declared one; the report did not.
        '<html lang="en">',
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">']
    # th (F-P-6): the project's own theme when it has one. The report is a FILE —
    # mailed, published, opened months later — so the stylesheet is embedded
    # compiled, never fetched, and a theme travels with the report rather than
    # living in a panel.
    parts += ['<title>%s</title>' % e(meta.get("title") or "Audit report"),
              "<style>%s</style>" % (css or _CSS)]
    return parts, []


def _nojs_block():
    """Say so when the script did not run.

    This report is a static file people are meant to SEND each other, and a very
    common way of opening one — an IDE's HTML preview pane — sandboxes inline
    <script>. The page then renders completely and looks finished, while
    filtering, search and every expandable phase silently do nothing. Reported as
    "the report is broken", and it took two browsers, two origins, five viewports
    and real mouse input to establish that the report was fine and the viewer was
    not.

    Written into the HTML rather than a <noscript>: the failure is not only "JS
    disabled" — a sandbox can leave scripts enabled but strip inline ones, which
    <noscript> does not catch. The script's first act is to remove this, so it is
    visible exactly when it is true, and its absence is itself a live proof that
    the script ran (the CI interactivity check asserts that).
    """
    return ([
        '<div id="audit-nojs" class="nojs" role="status">'
        "<strong>This report is interactive, and its scripts are not running here.</strong> "
        "Filtering, search, sorting and expanding a phase all need them. "
        "An IDE preview pane usually blocks inline scripts — "
        "open this file in a real browser and it will work.</div>"], [])


def _parked_suffix(manifest, summary):
    """" · N parked proposal(s)" when the plan is empty and proposals exist.

    F-P-32's other half, and it is deliberately NOT part of the Proposals section:
    `--no-proposals` turns that section off, and a reader who asked for a report
    without proposals still must not be shown "0 phases" as if it were the whole
    truth. The count is stated where the other counts already are.

    `_status_facts.is_parked_proposal`, not `== "proposed"` spelled here (F141).
    The word had already been decided twice in two places and reconciled twice, in
    two separate faults -- and this file was spelling it inline in two MORE, so the
    next change to the rule had two more places to miss. The predicate agrees with
    what was written here today; that is the reason to route through it rather than
    the reason to leave it alone.
    """
    if summary["phases"]:
        return ""
    parked = len([p for p in (manifest.get("proposals") or [])
                  if isinstance(p, dict)
                  and _status_facts.is_parked_proposal(p.get("status"))])
    if not parked:
        return ""
    return (" · %d parked proposal%s, not started"
            % (parked, "" if parked == 1 else "s"))


def _topbar_block(manifest, meta, summary, usage, owners):
    """The sticky top bar — identity, the global filters — and the shell it opens."""
    now = _report_html.stamp_time()
    ver = _plugin_version()
    parts = ['<header class="topbar"><div class="tb-id">'
             '<h1>%s</h1><p class="meta">%s · %d phases · %d tasks · %d bugs · '
             "generated %s%s</p></div>"
             % (e(meta.get("title") or "Audit report"),
                e(meta.get("repo") or "?"), len(summary["phases"]),
                summary["tasks"]["total"], summary["bugs"]["total"],
                now + _parked_suffix(manifest, summary),
                (' · <span class="stampv" title="The plugin version that '
                 'rendered this file">audit %s</span>' % e(ver)) if ver else "")]
    # The global filter row (C1/C2): author, area and the date range, inside
    # the sticky top bar so they stay reachable however far the reader has
    # scrolled. Why the bar and not a new floating row is argued where the row
    # is built (_report_html._global_filter_row). Inputs: authors by spend
    # (matching the Usage chips' order), tags first-seen (matching the panel
    # chips), and the date bounds from ALL data actually present — task
    # timestamps and ledger days both, since the one range scopes both surfaces.
    gauthors = [a for a, v in sorted(
        ((usage or {}).get("byAuthor") or {}).items(),
        key=lambda kv: -kv[1].get("tokens", 0))]
    gdates = []
    for _, t in _manifest_io.iter_tasks(manifest):
        for k in ("startedAt", "completedAt"):
            if t.get(k):
                gdates.append(_short_date(t[k]))
    gdates += list(((usage or {}).get("daily") or {}).keys())
    parts.append("@@TOOLBAR@@%s</header>"
                 % _global_filter_row(gauthors,
                                      _report_html._areas.used_tags(manifest),
                                      min(gdates) if gdates else None,
                                      max(gdates) if gdates else None,
                                      owners=owners))
    parts.append('<div class="shell">@@NAV@@<main class="content">')
    return parts, []


def _invalid_block(summary):
    """The validator's own finding count, said before anything is trusted."""
    if summary["valid"]:
        return [], []
    return ['<p><strong class="invalid">INVALID MANIFEST: %d '
            "validator finding(s) — fix before trusting this report."
            "</strong></p>" % summary["findings"]], []


def _gate_block(meta, summary, verdict):
    """The verdict hero, the narrative summary, and the grid holding both.

    The old band led with the word "Overall" and a bar — true, but it answered
    "how far along" when the reader's question is "can I ship".
    """
    record = ("gate", "Gate", None, False)
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
    parts = ['<div class="topgrid">']
    parts.append(
        '<section class="overall" id="%s"%s aria-label="Gate verdict">'
        '<p class="vd-eyebrow">Gate</p>'
        '<p class="vd-word">%s</p><p class="vd-why">%s</p>'
        '<p class="vd-basis">%s</p>'
        '<div class="vd-next">%s</div>'
        '<div class="vd-stats">%s<span class="muted">%s · '
        "%d of %d phases signed off · %s</span></div></section>"
        % (_anchor(record),
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
           nxt, _bar(tdone, ttotal), _fmt.plural(tdone, "task") + " done",
           phdone, len(summary["phases"]),
           _fmt.plural(summary["bugs"]["open"], "open bug")))

    # AI-authored narrative summary (written by /audit:report into
    # meta.reportSummary); the quantitative "Overall" line above is the
    # always-present deterministic fallback. Escaped — treated as untrusted.
    rsum = meta.get("reportSummary")
    if isinstance(rsum, str) and rsum.strip():
        parts.append('<div class="summary"><strong>Summary</strong>%s</div>'
                     % e(rsum.strip()))
    parts.append("</div>")   # close .topgrid
    return parts, [record]


def _doc_actions(fragment):
    """The bar that acts on the DOCUMENT — spliced in at `@@TOOLBAR@@`.

    Controls are split by WHAT THEY ACT ON, which is the same rule that put
    navigation at the side and actions on top. Save-as-PDF, the markdown twin and
    the theme act on the document, so they live in the persistent bar. Search, the
    status chips and expand-all act on the phases table and nothing else — in the
    top bar they were three rows of chrome following the reader through the usage
    charts, where they do nothing at all. They now sit on the table they drive
    (`_table_tools`). Enhanced by _SCRIPT; with JS off both tables are still fully
    readable.
    """
    return (
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


def _table_tools(manifest, summary, evidence=None):
    """Search, the status chips, the view select, the sort select and
    expand-all — the controls that act on the phases table and on nothing else.

    The chips are rendered HERE, not built by the script. Built in JS they were
    invisible to anything that does not run it — a printed page, a reader with
    scripting off — which is the one context where "the filters are gone" is
    indistinguishable from "the filters are broken". Server-rendered they are
    always present; the script only attaches behaviour to them.
    """
    statuses = sorted({p["status"] for p in summary["phases"] if p.get("status")})
    # pr: the sort select, and only where a phase is actually pinned. The panel's
    # Overview grew `sort: priority` and this did not, so the same plan answered
    # "what runs first" in one surface and not the other. The option is spelled
    # the way the panel spells it — value and label both `priority`, against
    # `plan order` — because a reader who learns the words in one surface has to
    # find them in the other. Withheld when nothing is pinned: every use of it
    # would then be a no-op, which is the defect the one-author Author cell in
    # `_global_filter_row` already refuses to ship, and withholding it is also
    # what keeps a plan with no `priority` rendering byte-for-byte as before.
    sortpick = (
        '<span class="sortpick"><label class="tbl" for="audit-sort">Sort:</label>'
        '<select id="audit-sort" aria-label="Sort: the order the phases are '
        'listed in">'
        '<option value="plan">plan order</option>'
        '<option value="priority">priority</option></select></span>'
    ) if _report_html.any_phase_pinned(manifest) else ""
    return (
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
        '<select id="audit-view" aria-label="View: which phases to show">'
        '<option value="active">Active &amp; pending</option>'
        '<option value="archived">Archived (done &amp; cancelled)</option>'
        '<option value="all">All phases</option></select></span>'
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
        "— every row is shown.</span></noscript></div>"
        % (_chip_buttons(statuses, "data-ps", "fchip"),
           _filter_panel(manifest, evidence), sortpick))


def _phases_block(manifest, summary, owners, workers=None, evidence=None):
    """One collapsible table: each phase is a group-row (click to expand its task
    rows). Default-collapsed via _SCRIPT; with JS off every row is visible."""
    record = ("phases", "Phases", len(summary["phases"]), False)
    parts = ['<section id="%s" class="sec">' % _anchor(record),
             _table_tools(manifest, summary, evidence)]
    # `present` is every optional column this plan HAS data for; `cols` is the
    # subset the compact row shows. The detail row renders the difference, so
    # nothing is dropped from the page — only from the row.
    present = _present_columns(manifest, evidence)
    cols = [c for c in present if c in PRIMARY_COLS]
    ncol = 3 + len(cols)
    # vw: 'active' unless there is nothing active or pending to show — a
    # finished plan that greeted its reader with an empty table would be the
    # archive toggle's own failure wearing a select. Decided here, where the
    # statuses are, and read by report.js as the starting view.
    segs_present = {_seg_of(p["status"]) for p in summary["phases"]}
    defview = "active" if (segs_present & {"active", "pending"}) else "all"
    # tm: the zone is named ONCE, in the header, rather than repeated in every
    # cell or left for a reader to assume.
    # The column header names the SUBJECT, not the verdict: what a cell in it
    # carries is what the gate for that task last said, and a header reading
    # "status" beside the task's own status column would be two statuses.
    colhead = {"done": 'done <span class="muted">UTC</span>',
               "tests": "test gate"}
    parts.append('<div class="tablewrap"><table class="phases" '
                 'data-defaultview="%s"><thead><tr>'
                 "<th>id</th><th>title</th><th>status</th>%s</tr></thead><tbody>"
                 % (defview,
                    "".join('<th data-col="%s">%s</th>' % (e(c), colhead.get(c, e(c)))
                            for c in cols)))
    done_ids = {p["id"] for p in summary["phases"] if p["status"] == "done"}
    parts += _segment_rows(manifest, summary, ncol, cols, done_ids, owners,
                           workers, evidence)
    # Its own <tbody>, so `tbody tr:last-child` keeps meaning the last DATA row —
    # the table's rounded bottom corner and its missing final rule both hang off
    # that selector, and a permanently-present hidden row in the main body would
    # have quietly taken both.
    # vw: matches the VIEW is hiding. The archive gate used to lift itself
    # during a search, which meant the control said one thing and the table did
    # another; this says the true thing instead — how many matched, and the one
    # press that shows them.
    parts.append('</tbody><tbody><tr class="norows"><td colspan="%d">'
                 "No phase matches these filters."
                 '<button type="button" class="btn" data-clear>Clear filters'
                 "</button></td></tr>"
                 "</tbody></table></div></section>" % (ncol,))
    return parts, [record]


def _segment_rows(manifest, summary, ncol, cols, done_ids, owners,
                  workers=None, evidence=None):
    """The table body: one seghead per segment, then that segment's phase rows.

    D1: the table renders in SEGMENTS — active (in_progress/blocked) first, then
    pending, then done — grouped by rolled-up status, plan order kept inside each
    group. The done segment is the ARCHIVE: on a plan that still has other work
    its seghead is a toggle and report.js collapses the rows under it at load, so
    a long finished run stops burying the work in motion. When done is the ONLY
    segment there is nothing to keep prominent and no toggle is emitted — a table
    that opens empty explains nothing.

    The Markdown twin deliberately keeps manifest order: it is a data table read
    by machines, and reordering it would change every diff against an earlier
    render for a purely presentational reason.
    """
    phases = [p for p in (manifest.get("phases") or []) if isinstance(p, dict)]
    # pr: zipped in rather than looked up by id, because the rollup entry beside
    # it is already matched positionally against this same filtered list — one
    # alignment rule for both, and a phase with no id (or two sharing one) can
    # therefore not be handed another phase's rank. `[]` when nothing is pinned
    # spreads to `None` per row, which is what suppresses the attribute.
    ranks = _report_html.phase_ranks(manifest) or [None] * len(phases)
    by_seg = {}
    for pair in zip(phases, summary["phases"], ranks):
        by_seg.setdefault(_seg_of(pair[1]["status"]), []).append(pair)
    out = []
    for seg in [s for s in _report_html.SEG_ORDER if by_seg.get(s)]:
        sn = len(by_seg[seg])
        # D2: every segment header is also the segment's export surface — CSV
        # of the segment's DATA and a print run scoped to it, wired by
        # report.js (server-rendered buttons, the chips rule).
        exports = (
            '<span class="segx">'
            '<button type="button" class="btn segbtn" data-segcsv="%s" '
            'title="Download this segment&#39;s phases and tasks as CSV — the '
            'data, not the filtered view">CSV</button>'
            '<button type="button" class="btn segbtn" data-segprint="%s" '
            'title="Print only this segment — the print dialog opens scoped '
            'to it">Print</button></span>' % (seg, seg))
        # vw: every seghead is now a plain title. Which segments are ON SCREEN
        # is the view select's business, and a segment that also hid itself
        # would be a second, contradictory gate.
        head = ('<span class="segname">%s</span>'
                '<span class="segn">%s</span>'
                % (_report_html.SEG_LABEL[seg], _fmt.plural(sn, "phase")))
        out.append('<tr class="seghead" data-seg="%s"><td colspan="%d">%s%s'
                   "</td></tr>" % (seg, ncol, head, exports))
        for ph, psum, prank in by_seg[seg]:
            out.append(_phase_rows(ph, psum, seg, ncol, cols, done_ids, owners,
                                   workers, prank, evidence))
    return out


def _usage_block(usage):
    """The Usage section, and the sub-entries its own headings earn.

    Usage is the longest section by far — a chart, five tiles, three ranked
    lists, a budget block, economics and a heatmap — so its own headings become
    sub-items. A nav that stops at the section a reader is already inside stops
    helping exactly where the scrolling gets long.

    Returns `[""]`, not `[]`, when there is no ledger: the empty string is a
    line the page has always emitted there, and dropping it would move a newline
    in every report without usage.
    """
    html = _usage_section(usage)
    if not html:
        return [html], []
    records = [("usage", "Usage", None, False)]
    for label, anchor in (("Tokens per day", "usage-trend"),
                          ("Budget", "usage-budget")):
        tag = '<h3 class="sub">%s</h3>' % label
        if tag in html:
            html = html.replace(
                tag, '<h3 class="sub" id="%s">%s</h3>' % (anchor, label), 1)
            records.append((anchor, label, None, True))
    return [html], records


def _proposals_block(manifest, show=True):
    """Parked phases: what was synthesized and not taken on. Nothing when empty.

    F-P-32. An `/audit:init` that parks everything left this report showing zero
    phases and no hint that eight proposals existed - and a report that renders
    nothing does not read as "the proposals are not shown here", it reads as
    "there is nothing". The whole content of the plan was invisible on the one
    surface a team is likely to be shown.

    `<details>` rather than a JS-driven detail row: this is disclosure, which the
    platform already has, so the payload is readable with scripting off and in
    print. It is also the cheaper half of "reuse existing components" - a second
    expand mechanism would have to be indexed by report.js next to the task rows.

    A DROPPED proposal shows its reason. That is the point of archiving instead of
    deleting: an archive nobody can read is a tombstone.
    """
    props = [p for p in (manifest.get("proposals") or []) if isinstance(p, dict)]
    if not props or not show:
        return [], []
    # The same predicate the top bar's suffix asks, and the same one
    # `/audit:status` and the doctor ask -- see `_parked_suffix` above for why
    # this file stopped deciding the word for itself.
    parked = len([p for p in props
                  if _status_facts.is_parked_proposal(p.get("status"))])
    record = ("proposals", "Proposals", parked or None, False)
    parts = ['<h2 id="%s">Proposals</h2>' % _anchor(record),
             '<p class="muted">Phases that were synthesized and parked rather '
             "than started. Materialize one with "
             "<code>/audit:propose materialize &lt;id&gt;</code>; a dropped one "
             "keeps its reason as history.</p>"]
    for prop in props:
        payload = prop.get("payload")
        phase = payload.get("phase") if isinstance(payload, dict) else None
        tasks = [t for t in ((phase or {}).get("tasks") or []) if isinstance(t, dict)]
        # A missing status renders as parked, which is what `_proposals.proposal_rows`
        # normalises it to as well -- through the constant, so the word itself is
        # still only spelled in `_status_facts`.
        status = prop.get("status") or _status_facts.PARKED_PROPOSAL_STATUS
        head = ('<summary><span class="mono">%s</span> %s %s'
                '<span class="muted"> · %s</span></summary>'
                % (e(prop.get("id")), e(prop.get("name") or ""), _chip(status),
                   e("%d task(s)" % len(tasks)) if phase
                   else "no payload — nothing to materialize"))
        rows = []
        for label, value in (("scope", prop.get("scope")),
                             ("benefit", prop.get("benefit")),
                             ("note", prop.get("technicalNote")),
                             ("why declined", prop.get("notes")
                              if status == "dropped" else None),
                             ("became", prop.get("materializedAs"))):
            if value:
                rows.append('<div class="dt-r"><span class="dt-k">%s</span>'
                            '<span class="dt-v">%s</span></div>'
                            % (e(label), e(str(value))))
        oq = [q for q in (prop.get("openQuestions") or []) if isinstance(q, str)]
        if oq:
            rows.append('<div class="dt-r"><span class="dt-k">open questions</span>'
                        '<span class="dt-v">%s</span></div>'
                        % e(" · ".join(oq)))
        body = ['<div class="propmeta">%s</div>' % "".join(rows)]
        if tasks:
            trs = "".join(
                '<tr><td class=mono>%s</td><td>%s</td><td class=mono>%s</td></tr>'
                % (e(t.get("id")), e(t.get("title")), e(t.get("risk") or "—"))
                for t in tasks)
            body.append('<div class="tablewrap"><table class="data">'
                        "<thead><tr><th>task</th><th>title</th><th>risk</th></tr>"
                        "</thead><tbody>%s</tbody></table></div>" % trs)
        parts.append('<details class="prop" data-prop="%s" data-status="%s">%s%s'
                     "</details>"
                     % (e(prop.get("id")), e(status), head, "".join(body)))
    return parts, [record]


def _bugs_block(manifest, summary, evidence=None):
    """The bugs table, or nothing at all when the plan tracks none.

    The evidence column is DERIVED and conditional, for the two reasons the task
    table's is: a bug has no gate of its own, so its column shows the linked
    fixing task's verdict with the provenance attached; and it appears only where
    the plan points at some recorded run, so a manifest that carries none renders
    the table it always did."""
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if not bugs:
        return [], []
    tviews = (evidence or {}).get("tasks")
    record = ("bugs", "Bugs", summary["bugs"]["open"] or None, False)
    task_by_id = _tasks_by_id(manifest)
    # D2: the bugs table is tabular data, so it earns the same CSV control
    # the phase segments carry — server-rendered, wired by report.js.
    parts = ['<h2 id="%s">Bugs<span class="segx">'
             '<button type="button" class="btn segbtn" data-csv="bugs" '
             'title="Download the bugs table as CSV">CSV</button>'
             "</span></h2>" % _anchor(record)]
    rows = []
    for b in bugs:
        bstatus, bfixed = _bug_view(b, task_by_id)
        tev = ('<td class="tevcell">%s</td>'
               % _report_html._tev_bug_cell(b, tviews)) if tviews else ""
        rows.append(
            '<tr data-status="%s"><td class=mono>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            "<td class=mono>%s</td><td class=mono>%s</td>%s<td>%s</td></tr>"
            % (e(bstatus), e(b.get("id")), e(b.get("title")),
               _chip(bstatus),
               e(b.get("severity") or "—"), e(b.get("taskId") or "—"),
               e(bfixed[:9]), tev, _ado_cell(b)))
    parts.append('<div class="tablewrap"><table class="data bugs"><thead><tr>'
                 "<th>id</th><th>title</th>"
                 "<th>status</th><th>severity</th><th>task</th><th>fixedIn</th>"
                 "%s<th>ADO</th></tr></thead><tbody>%s</tbody></table></div>"
                 % ('<th data-col="tests">test gate</th>' if tviews else "",
                    "".join(rows)))
    return parts, [record]


def _ready_block(manifest, summary):
    """C4: a definition list, not a comma-joined id string.

    Each ready task names itself, wears its phase's area tags (same chip style as
    everywhere else) and states which blockers cleared. Empty stays as it was: no
    section at all, because the hero's "Nothing ready / nothing left to run" line
    already IS the empty state, with more context than a heading over nothing
    could carry."""
    # The pin that could not be honoured, from the same `summary` key the CLI, the
    # Markdown twin and the panel read. It is the ONE case that brings the section
    # back when nothing is ready: the hero's "Nothing ready" line is the empty
    # state, but a phase pinned first and skipped is news the empty state does not
    # carry, and a skip nobody mentions reads as the plan being followed.
    pnote = summary.get("priorityNote")
    # `.muted` rather than a class of its own: the note is a sentence, the
    # stylesheet already has a voice for a sentence, and a new selector would be
    # a CSS change to carry for one paragraph. `data-note` is what a pin (and a
    # reader in devtools) identifies it by.
    note_html = ('<p class="muted" data-note="priority">%s</p>'
                 % e(pnote)) if pnote else ""
    if not summary["ready"]:
        if not pnote:
            return [], []
        record = ("ready", "Ready now", 0, False)
        return ['<h2 id="%s">Ready now</h2>%s' % (_anchor(record), note_html)], [record]
    record = ("ready", "Ready now", len(summary["ready"]), False)
    return ['<h2 id="%s">Ready now</h2>%s%s'
            % (_anchor(record), note_html,
               _ready_now_dl(manifest, summary["ready"]))], [record]


def _tail_block(manifest, summary, usage, basename, fragment, evidence=None):
    """Closing the shell, the embedded Markdown twin, and the one inline script."""
    parts = ["</main></div>"]   # close .content and .shell
    # Embed the Markdown twin as base64 so the "Download .md" button works from a
    # standalone file. base64 (not raw text) keeps any manifest HTML/`</script>`
    # out of the page and preserves UTF-8 exactly.
    md_b64 = base64.b64encode(
        render_md(manifest, summary, usage, evidence).encode("utf-8")).decode("ascii")
    # basename is sanitized to [A-Za-z0-9-_], so it is safe in a JS string literal.
    parts.append('<script>window.AUDIT_MD_B64="%s";window.AUDIT_MD_NAME="%s.md";</script>'
                 % (md_b64, basename))
    parts.append(_SCRIPT)
    if not fragment:
        parts.append("</html>")
    return parts, []


def _nav_html(sections):
    """The Contents nav, emitted from the records the sections themselves returned.

    So it cannot list a section that is not there or miss one that is. It is
    rendered server-side rather than built by the script: with JS off this report
    still has to be a whole document, and a nav that only exists once JavaScript
    runs is a nav that is missing from every PDF and every reader with scripting
    disabled. The script adds scroll-spy on top; it does not supply the links.
    """
    if not sections:
        return ""
    items = "".join(
        '<li class="%s"><a href="#%s">%s%s</a></li>'
        % ("sub-item" if sub else "item", e(anchor), e(label),
           ('<span class="n">%d</span>' % count) if count else "")
        for anchor, label, count, sub in sections)
    return ('<nav class="snav" aria-label="Report sections">'
            '<p class="snav-title">Contents</p><ol>%s</ol></nav>' % items)


# --- the page -------------------------------------------------------------------
def render_html(manifest, summary, basename="audit-report", usage=None,
                fragment=False, css=None, verdict=None, show_proposals=True,
                evidence=None):
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

    The page is assembled from the block emitters above, in emission order. Each
    hands back its HTML lines AND the nav entries for the anchors in them, so the
    nav below is built from the same values the anchors were written from — see
    the section-emitter header for why that replaced a shared list.
    """
    meta = manifest.get("meta") or {}
    owners = _owner_map(manifest)   # advisory area owners (D4) — one lookup
    out = []
    sections = []
    for parts, records in (
            _head_block(meta, css, fragment),
            _nojs_block(),
            _topbar_block(manifest, meta, summary, usage, owners),
            _invalid_block(summary),
            _gate_block(meta, summary, verdict),
            _phases_block(manifest, summary, owners,
                          (usage or {}).get("taskAuthors"), evidence),
            _usage_block(usage),
            _bugs_block(manifest, summary, evidence),
            _proposals_block(manifest, show_proposals),
            _ready_block(manifest, summary),
            _tail_block(manifest, summary, usage, basename, fragment,
                        evidence)):
        out += parts
        sections += records
    body = "\n".join(out) + "\n"
    return (body.replace("@@NAV@@", _nav_html(sections))
            .replace("@@TOOLBAR@@", _doc_actions(fragment)))

# --- cli ------------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_report_page.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_page.py - run that file instead.")
    raise SystemExit(0)
