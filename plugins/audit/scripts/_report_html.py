#!/usr/bin/env python3
"""
HTML fragment builders for the audit report: escaping, chips/badges, table
cells and the filter panel — stdlib only.

Moved out of render-report.py (P13.1). This is pure markup generation over
already-computed values: given a task, a bug, a phase or a manifest, each
function returns an HTML string. None of it decides layout, none of it reads
usage data, none of it renders the whole document — that stays in
render-report's `render_html` / `render_md`, which call these dozens of times
each and glue the fragments into the page.

Every manifest value that reaches these functions is untrusted input (the
manifest is user-authored JSON) and is escaped through `e()` before it
reaches the page; `_safe_url` is the one gate a URL passes through before it
is allowed to become an `href`.

render-report.py keeps thin module-level aliases (`e = _report_html.e`,
`_chip = _report_html._chip`, etc.) so render_html/render_md and the
selftest's many direct references keep working unchanged.

This module must never import render-report or _report_usage: nothing that
imports THIS module (render-report does) can form a cycle through it. It may
use `_ui_theme` for status/label vocabulary, same as the panel.
"""
import html
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# Run as a command, `sys.path[0]` is already this directory; imported from
# elsewhere it might not be.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _ui_theme as _theme  # noqa: E402  (tokens + labels shared with the panel)
import _areas  # noqa: E402  (one home for tag derivation; stdlib-only, no cycle)


# Chip and pipeline-rail colors live in the report's CSS theme tokens (see
# render-report's _CSS), keyed off the `data-status` / `data-risk` attributes
# the markup carries — so a single token set themes every status/risk
# consistently in both light and dark. Risk chips render only for these
# levels:
_RISK_LEVELS = ("low", "med", "high")


# --- escaping + basename ----------------------------------------------------
def e(value):
    """Escape ANY manifest value for HTML context."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _safe_url(url):
    """Return the url only when it is plain http(s) — else None (render as text)."""
    u = str(url or "")
    return u if u.startswith(("https://", "http://")) else None


def _report_basename(meta, cli_value):
    """Resolve the report file basename: --basename › meta.reportBasename ›
    'audit-report'. Sanitized to a bare filename ([A-Za-z0-9-_], no path
    separators / extension) so it can't escape --out-dir or break the download."""
    raw = cli_value if cli_value else (
        meta.get("reportBasename") if isinstance(meta, dict) else None)
    name = os.path.basename(str(raw or "").strip())          # drop any dir parts
    for ext in (".html", ".md"):                             # tolerate a given ext
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    name = "".join(c for c in name if c.isalnum() or c in "-_")
    return name or "audit-report"


# --- lookups ----------------------------------------------------------------
def _tasks_by_id(manifest):
    return {t["id"]: t for p in (manifest.get("phases") or []) if isinstance(p, dict)
            for t in (p.get("tasks") or []) if isinstance(t, dict) and t.get("id")}


# A phase's `area` -> its tags. One implementation, in `_areas`, the same one the
# panel and audit-status alias. This file carried a COPY that predated the trim and
# the de-duplication, so `"area": ["api","api"]` drew two chips in the HTML report
# and one on every other surface — the report was the last reader of the pre-fix
# six lines. A copy is not shared code; the alias is.
_areas_of = _areas.areas_of


# --- advisory area owners (D4, v0.36) ----------------------------------------
def _owner_map(manifest):
    """{tag: owner} for every registered area declaring a non-null string owner.

    The same filter _panel_state.usage_state ships to the panel: an explicit
    `owner: null` ("nobody owns this") and an undeclared owner read the same to
    a surface that only displays, and a non-string owner is the validator's
    finding, not this map's problem. Fail-soft to {} — the report renders from
    manifests the validator has only warned about."""
    try:
        out = {}
        for tag, entry in _areas.registry(manifest).items():
            o = entry.get("owner")
            if isinstance(o, str) and o.strip():
                out[tag] = o.strip()
        return out
    except Exception:
        return {}


def _area_tag_span(tag, owners):
    """One area tag chip, wearing its advisory owner when one is registered.

    The suffix is display, not assignment — the same claim the manifest makes,
    no more — and the title spells it the way the panel's area select already
    does (`owner: <who>`), so the two surfaces teach one habit. A tag with no
    owner emits EXACTLY the bytes it always did; the bare shape is pinned by
    name in the rd2/ready selftests and must not grow an empty suffix."""
    own = (owners or {}).get(tag)
    if not own:
        return '<span class="area-tag">%s</span>' % e(tag)
    return ('<span class="area-tag" title="owner: %s">%s'
            '<span class="aown"> — %s</span></span>'
            % (e(own), e(tag), e(own)))


# --- segments (D1, v0.36) -----------------------------------------------------
# The order the segments render in: the work in motion first, then the queue,
# then the archive. A dict, not an if-chain, so the emitter and the selftest
# read one table.
SEG_ORDER = ("active", "pending", "archived")
SEG_LABEL = {"active": "Active", "pending": "Pending", "archived": "Archived"}
# The two views a reader picks between, plus the escape hatch. `active` is the
# default and means "everything still to come or in hand" — active AND pending,
# because both are work nobody has finished.
VIEW_SEGS = {"active": ("active", "pending"),
             "archived": ("archived",),
             "all": SEG_ORDER}


def _seg_of(status):
    """Which segment a phase files under, from its ROLLED-UP status.

    in_progress and blocked are both "someone is (or should be) on this now";
    the archive holds both TERMINAL states — `done` (it landed) and `cancelled`
    (it will not be done) — because the question a reader asks of the top of
    this table is "what is left", and finished-by-dropping is finished.
    Everything else — pending, an unknown vocabulary value, a phase with no
    status at all — is work still to come. Unknowns land in pending on purpose:
    a segment that silently swallowed a typo'd status would hide the phase the
    validator is about to flag."""
    if status in ("done", "cancelled"):
        return "archived"
    if status in ("in_progress", "blocked"):
        return "active"
    return "pending"


# --- fragment builders ------------------------------------------------------
def _bug_view(b, task_by_id):
    """Derived (status, fixedIn) for a bug — mirrors audit-status.effective_bug_status:
    a bug materialized into a done task reads as fixed (fixedIn = that task's commit),
    since the orchestrator never writes bugs[] during a run. Stored fixedIn/wontfix win."""
    stored = b.get("status")
    fixed_in = b.get("fixedIn")
    if stored != "wontfix":
        t = task_by_id.get(b.get("taskId"))
        if isinstance(t, dict) and t.get("status") == "done":
            return "fixed", (fixed_in or t.get("commit") or "—")
    return stored, (fixed_in or "—")


def _chip_buttons(statuses, attr, cls, humanize=True, titles=None):
    """Toggle buttons for a set of values — machine value in `attr`, words shown.

    `aria-pressed` is what makes a toggle's state readable; without it "which
    filter is on" is carried by colour alone.

    `humanize` is off for values that are IDENTIFIERS rather than vocabulary. A
    status is a word this product chose and should read as English; a model name
    is a string someone types into a manifest and reads back out of a bill, and
    running it through label() gave a chip reading "Opus" beside a table cell
    reading `opus` — two spellings of one value, in one table.

    `titles` (D4) maps a value to a native-tooltip string — the area chips use
    it to carry the advisory owner. A value without an entry emits EXACTLY the
    bytes it always did: the untitled shape is pinned by name in more than one
    selftest, and an empty title attribute would be a different chip.
    """
    return "".join(
        '<button type="button" class="%s" %s="%s"%s aria-pressed="false">%s</button>'
        % (cls, attr, e(s),
           (' title="%s"' % e((titles or {}).get(s))) if (titles or {}).get(s)
           else "",
           e(_theme.label(s) if humanize else s))
        for s in statuses)


def _chip(status):
    """A status badge: machine value in the attribute, words in the text.

    `in_progress` is a key — it sorts, compares and survives serialization — and
    it was being shown to people as-is, in the one place they look to find out how
    the work is going. The attribute keeps the key (the CSS themes off it and the
    filters compare it), the text says what it means.
    """
    return '<span class="chip" data-status="%s">%s</span>' % (
        e(status), e(_theme.label(status)))


def _ado_cell(item):
    ado = item.get("ado") if isinstance(item.get("ado"), dict) else None
    if not ado or ado.get("id") is None:
        return '<span class="muted">—</span>'
    label = "#%s" % e(ado.get("id"))
    url = _safe_url(ado.get("url"))
    if url:
        return '<a href="%s">%s</a>' % (e(url), label)
    return label


def _outcome_text(task):
    """One-line outcome (descriptive, else technical), truncated — for the table."""
    o = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    txt = str(o.get("descriptive") or o.get("technical") or "").strip()
    return (txt[:70].rstrip() + "…") if len(txt) > 70 else txt


def _short_date(iso):
    """ISO timestamp -> its date part ('2026-06-28T10:00:00Z' -> '2026-06-28')."""
    s = str(iso or "")
    return s.split("T", 1)[0] if "T" in s else s


def _stamp(iso):
    """ISO timestamp -> 'YYYY-MM-DD HH:MM', the date part when there is no time.

    tm (F-P-4): the table showed the DATE a task finished and kept the clock in
    a tooltip. "Which of these two finished first" is the question this column
    is asked on a busy day, and the answer was a hover away - on paper, not
    available at all. The value is the manifest's own string, cut rather than
    parsed: these are UTC stamps written by the orchestrator, and re-formatting
    them through a local timezone here would silently move a completion across
    midnight in a file that is also read offline. The zone is named in the
    column header once, not repeated per row."""
    s = str(iso or "")
    if "T" not in s:
        return s
    day, rest = s.split("T", 1)
    return "%s %s" % (day, rest[:5]) if len(rest) >= 5 else day


def _timing_cell(task):
    """Compact completion date for the table, with the full started/completed
    timestamps on hover. Done -> completed date; started-but-not-done -> the
    started date (muted); neither -> em dash."""
    started, completed = task.get("startedAt"), task.get("completedAt")
    tip = e("started %s · completed %s" % (started or "—", completed or "—"))
    if completed:
        return '<span title="%s">%s</span>' % (tip, e(_stamp(completed)))
    if started:
        return ('<span class="muted" title="%s">started %s</span>'
                % (tip, e(_stamp(started))))
    return '<span class="muted">—</span>'


def _commit_cell(task):
    """The commit, with one press that copies the WHOLE sha (F-P-4).

    The column shows nine characters because a table cannot carry forty, and
    nine is not what `git cherry-pick` wants - so a reader who needed the sha
    was retyping it off a screenshot or opening the manifest. The button carries
    the full value in `data-copy`; report.js already owns the copy behaviour and
    its file:// fallback (clipboard.writeText is refused there, and that is
    where this report is most often opened), so this is the same control the run
    command uses, one cell down."""
    sha = str(task.get("commit") or "").strip()
    if not sha:
        return '<span class="muted">\u2014</span>'
    return ('<span class="shacell"><code>%s</code>'
            '<button type="button" class="btn-copy shacopy" data-copy="%s" '
            'title="Copy the full commit sha (%s)" '
            'aria-label="Copy the full commit sha">Copy</button></span>'
            % (e(sha[:9]), e(sha), e(sha)))


def _detail_row(task, phase, owners, ncol, seg, pid):
    """The row under a task row: everything the compact row had to leave out.

    ex (F-P-4). The table is read at a glance and acted on in detail, and those
    are different densities. The compact row answers "where is this" — id,
    title, status, risk, when, commit — and the detail row answers "what
    happened and who do I ask", in two labelled groups because the questions
    come in two kinds:

      meta    — who owns this area, when it started and finished (to the
                second, not the minute the cell shows), the whole sha, the
                phase's branch and its work item
      details — the FULL outcome (both voices, untruncated: the table's 70-char
                cut is what made this row necessary), the model, the skills,
                what it waits on, and how it was tested

    "Who" is the AREA's advisory owner, not an assignee: the manifest has no
    per-task assignee and inventing one here would be a claim the file does not
    make. It is labelled as what it is.
    """
    def rows(pairs):
        out = []
        for k, v in pairs:
            if not v:
                continue
            out.append('<div class="dt-r"><span class="dt-k">%s</span>'
                       '<span class="dt-v">%s</span></div>' % (e(k), v))
        return "".join(out)

    areas = [a for a in (phase.get("area") if isinstance(phase.get("area"), list)
                         else [phase.get("area")]) if isinstance(a, str) and a]
    owner_bits = []
    for a in areas:
        own = (owners or {}).get(a)
        if own:
            owner_bits.append("%s <span class=\"muted\">(area %s)</span>"
                              % (e(own), e(a)))
    o = task.get("outcome") if isinstance(task.get("outcome"), dict) else {}
    waits = [w for w in list(task.get("blockedBy") or [])
             + list(task.get("dependsOn") or []) if isinstance(w, str)]
    tests = task.get("tests") if isinstance(task.get("tests"), dict) else {}
    skills = task.get("skills")
    meta = rows([
        ("owner", " · ".join(owner_bits)),
        ("started", e(task.get("startedAt") or "")),
        ("completed", e(task.get("completedAt") or "")),
        ("commit", _commit_cell(task) if task.get("commit") else ""),
        ("branch", e(phase.get("branch") or "")),
        ("work item", _ado_cell(task) if isinstance(task.get("ado"), dict)
         and task["ado"].get("id") is not None else ""),
    ])
    details = rows([
        # Both voices, in the order a person reads them: what changed, then how.
        ("outcome", e(str(o.get("descriptive") or "").strip())),
        ("technical", e(str(o.get("technical") or "").strip())),
        ("model", e(task.get("model") or "")),
        ("skills", e(", ".join(s for s in (skills or []) if isinstance(s, str)))
         if isinstance(skills, list) and skills
         else ('<span class="muted">none \u2014 opted out</span>'
               if skills is None and "skills" in task else "")),
        ("waits on", e(", ".join(waits))),
        ("tests", e(str(tests.get("mode") or ""))),
    ])
    if not meta and not details:
        details = ('<div class="dt-r"><span class="dt-v muted">Nothing recorded '
                   "for this task yet.</span></div>")
    return ('<tr class="taskdetail" data-phase="%s" data-seg="%s" '
            'data-detail="%s" hidden><td colspan="%d"><div class="dtwrap">'
            '<div class="dtcol"><h4>meta</h4>%s</div>'
            '<div class="dtcol"><h4>task details</h4>%s</div>'
            "</div></td></tr>"
            % (e(pid), e(seg), e(task.get("id") or ""), ncol, meta, details))


def _filter_attrs(task):
    """The data a task row is filtered BY, in attributes rather than in its text.

    Model and dates are filtered on, and the text search already reads the row's
    rendered text — but neither of those is reliable to read back out of it. The
    model may not be a rendered column at all (`_present_columns` drops it when no
    task has one), and the `done` cell shows a date that is sometimes prefixed
    with the word "started". A filter reading its own attributes compares the
    manifest's values, not the table's prose.

    Dates are cut to their date part on purpose: ISO-8601 dates compare correctly
    as STRINGS while they are the same length and shape, so the whole range test
    in the script is `d >= from && d <= to` with no Date parsing per row. Whole
    timestamps would break that against a bare `<input type=date>` value.

    Emitted only when present — an absent value is an absent attribute, so the
    script's `getAttribute(...) || ''` sees the same thing either way and the
    markup does not carry a row of empty strings for a plan that tracks neither.
    """
    out = []
    if task.get("model"):
        out.append(' data-model="%s"' % e(task["model"]))
    for attr, key in (("data-started", "startedAt"), ("data-completed", "completedAt")):
        if task.get(key):
            out.append(' %s="%s"' % (attr, e(_short_date(task[key]))))
    return "".join(out)


# --- filter panel -----------------------------------------------------------
def _filter_panel(manifest):
    """The area, model and date controls, server-rendered, or "" with none of them.

    Everything here is emitted from the manifest rather than built by the script,
    which is the rule the status chips already follow: built in JS, a filter UI is
    missing from every printed page and every reader that runs no script, and
    "the filters are gone" is indistinguishable from "the filters are broken".

    The date inputs carry the plan's own range as `min`/`max`, so the picker opens
    on the months the work actually happened in rather than on this century.
    """
    models, dates = set(), []
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for t in (ph.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            if t.get("model"):
                models.add(str(t["model"]))
            for key in ("startedAt", "completedAt"):
                if t.get(key):
                    dates.append(_short_date(t[key]))
    tags = _areas.used_tags(manifest)
    if not models and not dates and not tags:
        return ""

    rows = []
    # Area first: it gates PHASES, where model and dates narrow the tasks inside
    # them — the panel reads top-down from the coarser filter to the finer ones.
    # First-seen order, not sorted: tags are read in the order the plan
    # introduces them, same as the phase list below the panel. humanize=False
    # because a tag is an identifier someone typed into the manifest, exactly
    # like a model name (see _chip_buttons).
    if tags:
        # The advisory owner rides each chip as a native tooltip (D4) — the
        # same `owner: <who>` the panel's area select options carry. Tags with
        # no registered owner keep the pinned untitled shape.
        _owners = _owner_map(manifest)
        rows.append('<div class="frow"><span class="tbl">Area:</span>'
                    '<span id="audit-areas">%s</span></div>'
                    % _chip_buttons(tags, "data-a", "fchip", humanize=False,
                                    titles={t: "owner: %s" % _owners[t]
                                            for t in tags if t in _owners}))
    if models:
        rows.append('<div class="frow"><span class="tbl">Model:</span>'
                    '<span id="audit-model">%s</span></div>'
                    % _chip_buttons(sorted(models), "data-m", "fchip",
                                    humanize=False))
    if dates:
        span = ' min="%s" max="%s"' % (e(min(dates)), e(max(dates)))
        # The presets are relative to the LAST DAY IN THE DATA, not to today.
        # "Last 30 days" measured against the wall clock answers a different
        # question every morning, and would make the committed example — which CI
        # byte-compares against docs/index.html — a file that cannot stay equal to
        # itself. The script derives the dates from the rows; these carry only the
        # span, so the arithmetic has one home.
        rows.append(
            '<div class="frow"><span class="tbl">Worked between:</span>'
            '<input type="date" id="audit-from" aria-label="Show tasks worked on '
            'or after this date"%s>'
            '<span class="tbl">and</span>'
            '<input type="date" id="audit-to" aria-label="Show tasks worked on or '
            'before this date"%s></div>' % (span, span))
        rows.append(
            '<div class="frow"><span class="tbl">Last:</span><span id="audit-presets">'
            '<button type="button" class="fchip" data-days="7" aria-pressed="false">'
            '7 days</button>'
            '<button type="button" class="fchip" data-days="30" aria-pressed="false">'
            '30 days</button>'
            '<button type="button" class="fchip" data-days="all" aria-pressed="false">'
            'All</button></span></div>')
        # Says which "last 30 days" this is. Without it a reader compares the
        # dates against their own calendar, finds them stale, and concludes the
        # report is out of date rather than that it is measuring the work.
        rows.append('<p class="fnote">Counted back from %s, the last day this '
                    "plan recorded work — not from today.</p>" % e(max(dates)))
    return ('<details class="fdetails"><summary aria-label="More filters">'
            'More filters<span class="fcount" id="audit-fcount"></span></summary>'
            '<div class="filterpanel">%s</div></details>' % "".join(rows))


# --- global filter row (C1/C2) ----------------------------------------------
def _global_filter_row(authors, tags, dmin, dmax, owners=None):
    """The compact global filter row — author, area, date range — or "".

    DESIGN DECISION (C2, delegated): this row is a second line INSIDE the
    existing sticky `.topbar`, not a separate floating/anchored bar. Three
    reasons, in the order they decided it:

      * The report is long and its sticky stack is already measured geometry —
        `--topbar-h` (written by measureStack() in report.js) is what the side
        nav, the strip, the phases filter bar and every anchor offset hang off.
        Growing the bar the stack already measures keeps ONE sticky stack; a
        new independently-stuck row would be a fourth layer needing its own
        z-index token, its own offset in --sticky-*, and its own stuck-state
        handling for zero extra reachability.
      * Print must never show floating chrome mid-page: `.topbar` is already
        `display:none!important` in the print sheet (a pinned rule), so the row
        can never reach paper — the active range prints instead as the named
        line in the Usage section (#audit-urange).
      * Mobile width exists: inside the topbar the row wraps under the title
        with `flex-wrap` and compact controls, and the measured `--topbar-h`
        absorbs the extra height at every width — no breakpoint-specific
        arithmetic, because there is no second bar to place.

    Server-rendered like every other filter control (the chips rule): built in
    JS it would be missing wherever scripts do not run, and "the filters are
    gone" is indistinguishable from "the filters are broken". The controls are
    selects and date inputs rather than chip rows on purpose — this row stays
    one line; the full multi-select vocabulary lives where it always did (area
    chips in More filters, author chips in Usage), and report.js keeps the two
    presentations of each filter in sync over one state.

    `authors` arrives ordered (by spend, matching the Usage chips); `tags` in
    first-seen order (matching the panel chips). An author set smaller than two
    renders no select — one author has nothing to filter."""
    bits = []
    if len(authors or []) >= 2:
        opts = '<option value="">All authors</option>' + "".join(
            '<option value="%s">%s</option>' % (e(a), e(a)) for a in authors)
        bits.append('<label class="gf"><span class="tbl">Author</span>'
                    '<select id="audit-au-select" aria-label="Scope the Usage '
                    'section&#39;s per-author views to one author">%s</select>'
                    "</label>" % opts)
    if tags:
        # Each option titles its advisory owner (D4) — exactly the panel's
        # area-select behaviour, so a habit learned there reads here too.
        opts = '<option value="">All areas</option>' + "".join(
            '<option value="%s"%s>%s</option>'
            % (e(t),
               (' title="owner: %s"' % e((owners or {}).get(t)))
               if (owners or {}).get(t) else "",
               e(t))
            for t in tags)
        bits.append('<label class="gf"><span class="tbl">Area</span>'
                    '<select id="audit-area-select" aria-label="Show only '
                    'phases tagged with this area">%s</select></label>' % opts)
    if dmin and dmax:
        span = ' min="%s" max="%s"' % (e(dmin), e(dmax))
        bits.append(
            '<label class="gf"><span class="tbl">From</span>'
            '<input type="date" id="audit-gfrom" aria-label="Start of the date '
            'range scoping the task table and the usage charts"%s></label>'
            '<label class="gf"><span class="tbl">to</span>'
            '<input type="date" id="audit-gto" aria-label="End of the date '
            'range scoping the task table and the usage charts"%s></label>'
            '<button type="button" class="btn" id="audit-gclear" hidden '
            'title="Clear the date range - back to all time">All time</button>'
            % (span, span))
    if not bits:
        return ""
    return ('<div class="gfilters" role="group" aria-label="Global filters">'
            "%s</div>" % "".join(bits))


# --- ready now (C4) ----------------------------------------------------------
def _ready_now_dl(manifest, ready_ids):
    """The Ready-now section as a definition list: each ready task is a term
    (id, title, its phase's area tags in the same chip style areas wear
    everywhere else), and the definition says WHY it is ready — the blockers
    that have cleared, or that nothing ever blocked it.

    The old rendering was a comma-joined id list in monospace: correct, and
    unreadable past five entries — a reader had to look every id up by hand to
    learn what any of them was. This carries the lookup with the id.

    Renders "" for an empty list; the caller already omits the section then
    (the hero's "Nothing ready / nothing left to run" line is the empty state,
    and a heading over an empty list would say less than that line does)."""
    if not ready_ids:
        return ""
    owners = _owner_map(manifest)   # tags here wear their advisory owner too
    task_of, phase_of = {}, {}
    for ph in (manifest.get("phases") or []):
        if not isinstance(ph, dict):
            continue
        for t in (ph.get("tasks") or []):
            if isinstance(t, dict) and t.get("id"):
                task_of[t["id"]] = t
                phase_of[t["id"]] = ph
    items = []
    for rid in ready_ids:
        t = task_of.get(rid) or {}
        ph = phase_of.get(rid) or {}
        tags = "".join(" " + _area_tag_span(a, owners)
                       for a in _areas_of(ph.get("area")))
        title = (' <strong>%s</strong>' % e(t["title"])) if t.get("title") else ""
        cleared = []
        for word, refs in (("depends on", t.get("dependsOn")),
                           ("blocked by", t.get("blockedBy")),
                           ("phase blocked by", ph.get("blockedBy"))):
            names = [r for r in (refs or []) if isinstance(r, str) and r]
            if names:
                cleared.append("%s %s (done)"
                               % (word, ", ".join(e(r) for r in names)))
        # A ready task's blockers are all satisfied by definition (that is what
        # ready MEANS), so listing them with "(done)" states the evidence
        # rather than re-deriving it.
        why = ("Cleared: " + " · ".join(cleared)) if cleared \
            else "Nothing blocked it — ready from the start."
        where = ""
        if ph.get("id"):
            where = 'In <span class="mono">%s</span>%s. ' % (
                e(ph["id"]),
                (" — %s" % e(ph["title"])) if ph.get("title") else "")
        items.append('<dt><code class="mono">%s</code>%s%s</dt><dd>%s%s</dd>'
                     % (e(rid), title, tags, where, why))
    return '<dl class="ready">%s</dl>' % "".join(items)


# --- risk + progress fragments ----------------------------------------------
def _risk_chip(risk):
    """Tinted risk chip (low/med/high); em dash for null/unknown. Colored by the
    CSS theme token selected via data-risk (see render-report's _CSS)."""
    r = str(risk or "").lower()
    if r not in _RISK_LEVELS:
        return '<span class="muted">—</span>'
    return '<span class="rchip" data-risk="%s">%s</span>' % (r, e(r))


def _phase_meta_div(phase):
    """Muted sub-line for a phase group-row: desired outcome, branch, merge
    timestamp, and (once signed off) the summary — all escaped."""
    bits = []
    if phase.get("desiredOutcome"):
        bits.append("Desired: " + e(phase["desiredOutcome"]))
    if phase.get("branch"):
        bits.append("branch " + e(phase["branch"]))
    if phase.get("mergedAt"):
        bits.append("merged " + e(phase["mergedAt"]))
    if phase.get("summary"):
        bits.append(e(phase["summary"]))
    return ('<div class="pmeta muted">%s</div>' % " · ".join(bits)) if bits else ""


def _bar(done, total):
    # Fill width is a CSS var so the stylesheet can animate 0 -> --w on load.
    pct = int(round(100.0 * done / total)) if total else 0
    return ('<span class="bar"><span class="fill" style="--w:%d%%"></span></span> '
            '<span class="muted">%d/%d</span>' % (pct, done, total))


# --- selftest ---------------------------------------------------------------
def _selftest():
    cases = []

    def check(label, cond):
        cases.append((label, bool(cond)))

    # --- e(): escaping is the whole point --------------------------------------
    check("e() escapes a script tag", e("<script>alert(1)</script>") ==
          "&lt;script&gt;alert(1)&lt;/script&gt;")
    check("e() escapes quotes (attribute context)",
          e('a "quoted" value') == "a &quot;quoted&quot; value")
    check("e() turns None into an empty string, not the word None",
          e(None) == "")
    check("e() stringifies non-strings before escaping", e(42) == "42")

    # --- _safe_url(): the one gate a URL passes before becoming an href -------
    check("_safe_url accepts https", _safe_url("https://x.io/a") == "https://x.io/a")
    check("_safe_url accepts http", _safe_url("http://x.io/a") == "http://x.io/a")
    check("_safe_url rejects javascript:", _safe_url("javascript:alert(1)") is None)
    check("_safe_url rejects a bare string", _safe_url("not a url") is None)
    check("_safe_url rejects None", _safe_url(None) is None)

    # --- _report_basename(): sanitized to a bare filename ----------------------
    check("_report_basename prefers --basename over meta",
          _report_basename({"reportBasename": "meta-name"}, "cli-name") == "cli-name")
    check("_report_basename falls back to meta.reportBasename",
          _report_basename({"reportBasename": "meta-name"}, None) == "meta-name")
    check("_report_basename falls back to 'audit-report' with neither",
          _report_basename({}, None) == "audit-report")
    check("_report_basename strips a leading path (cannot escape --out-dir)",
          _report_basename({}, "../../etc/passwd") == "passwd")
    check("_report_basename tolerates a given extension",
          _report_basename({}, "name.html") == "name")
    check("_report_basename strips characters outside [A-Za-z0-9-_]",
          _report_basename({}, "a b!c") == "abc")

    # --- _tasks_by_id / _areas_of -----------------------------------------------
    _m = {"phases": [{"id": "P1", "tasks": [{"id": "P1.1", "title": "t"}]},
                     "not-a-dict"]}
    check("_tasks_by_id indexes every task across every phase",
          _tasks_by_id(_m) == {"P1.1": {"id": "P1.1", "title": "t"}})
    check("_tasks_by_id tolerates a malformed phase entry",
          isinstance(_tasks_by_id({"phases": [None, "x"]}), dict))
    check("_areas_of wraps a bare string", _areas_of("frontend") == ["frontend"])
    check("_areas_of passes a list of strings through, dropping junk",
          _areas_of(["a", 1, "b", None]) == ["a", "b"])
    check("_areas_of returns [] for absent/other types", _areas_of(None) == []
          and _areas_of(3) == [])
    # The three cases above ALL pass on the pre-fix local copy — not one of them
    # repeats a tag or pads one, which is how the report kept drawing two chips
    # for `["api","api"]` while every other surface drew one, protected by a
    # green case. The three below are the ones that can tell the copy from
    # `_areas.areas_of`. The dedupe fixture is `["web","api","api"]` rather than
    # the alphabetical `["api","api","web"]` because a set-based dedupe answers
    # that one correctly by accident, and chip order is written order.
    check("_areas_of DEDUPES in written order - a repeated tag is one chip, not "
          "two (the local copy of this function shipped un-deduped)",
          _areas_of(["api", "api"]) == ["api"]
          and _areas_of(["web", "api", "api"]) == ["web", "api"])
    check("_areas_of TRIMS, so ' api' and 'api' are the same tag - written "
          "spacing must not split one area into two chips",
          _areas_of([" api", "api"]) == ["api"]
          and _areas_of(" frontend ") == ["frontend"])
    check("_areas_of is the shared implementation, not a copy of it",
          _areas_of is _areas.areas_of)

    # --- _bug_view(): derived status mirrors audit-status ----------------------
    _tbi = {"T1": {"status": "done", "commit": "abc1234"}}
    check("_bug_view reads fixed from a done task when nothing is stored",
          _bug_view({"taskId": "T1"}, _tbi) == ("fixed", "abc1234"))
    check("_bug_view prefers a stored fixedIn over the task's commit",
          _bug_view({"taskId": "T1", "fixedIn": "manual"}, _tbi) ==
          ("fixed", "manual"))
    check("_bug_view leaves a wontfix bug alone even if its task is done",
          _bug_view({"taskId": "T1", "status": "wontfix"}, _tbi) ==
          ("wontfix", "—"))
    check("_bug_view falls back to em dash with no task and no fixedIn",
          _bug_view({"taskId": "nope", "status": "open"}, _tbi) == ("open", "—"))

    # --- chips / badges ----------------------------------------------------------
    check("_chip carries the machine value in the attribute and the label in text",
          _chip("in_progress") == '<span class="chip" data-status="in_progress">%s</span>'
          % e(_theme.label("in_progress")))
    check("_chip_buttons humanizes vocabulary but not identifiers",
          "opus</button>" in _chip_buttons(["opus"], "data-m", "fchip", humanize=False)
          and "opus</button>" not in _chip_buttons(["done"], "data-s", "fchip"))
    check("_chip_buttons escapes a hostile status value",
          "&lt;script&gt;" in _chip_buttons(["<script>"], "data-s", "fchip",
                                            humanize=False))
    check("_risk_chip renders only the three known levels",
          '<span class="rchip" data-risk="high">high</span>' == _risk_chip("high")
          and _risk_chip("HIGH") == _risk_chip("high"))
    check("_risk_chip is an em dash for an unknown/null risk",
          '<span class="muted">—</span>' == _risk_chip(None) == _risk_chip("extreme"))

    # --- _ado_cell(): a link only when the url is safe --------------------------
    check("_ado_cell links a safe https ado url",
          _ado_cell({"ado": {"id": 7, "url": "https://dev.azure.com/x/7"}}) ==
          '<a href="https://dev.azure.com/x/7">#7</a>')
    check("_ado_cell renders text-only for an unsafe url (never an href)",
          "href=" not in _ado_cell({"ado": {"id": 7, "url": "javascript:alert(1)"}})
          and "#7" in _ado_cell({"ado": {"id": 7, "url": "javascript:alert(1)"}}))
    check("_ado_cell is an em dash with no ado id",
          '<span class="muted">—</span>' == _ado_cell({}))

    # --- _outcome_text(): descriptive over technical, truncated -----------------
    check("_outcome_text prefers descriptive over technical",
          _outcome_text({"outcome": {"descriptive": "d", "technical": "t"}}) == "d")
    check("_outcome_text falls back to technical",
          _outcome_text({"outcome": {"technical": "t"}}) == "t")
    _long = "x" * 100
    check("_outcome_text truncates past 70 chars with an ellipsis",
          _outcome_text({"outcome": {"descriptive": _long}}) ==
          (_long[:70] + "…"))
    check("_outcome_text is '' with no outcome at all", _outcome_text({}) == "")

    # --- _short_date() / _timing_cell() -----------------------------------------
    check("_short_date splits an ISO timestamp at T",
          _short_date("2026-06-28T10:00:00Z") == "2026-06-28")
    check("_short_date passes a bare date through unchanged",
          _short_date("2026-06-28") == "2026-06-28")
    check("_short_date is '' for None", _short_date(None) == "")
    check("_timing_cell shows the completed date when done",
          "2026-07-09" in _timing_cell({"completedAt": "2026-07-09T09:30:00Z"}))
    check("_timing_cell shows a muted started date when only started",
          "muted" in _timing_cell({"startedAt": "2026-07-01T00:00:00Z"})
          and "2026-07-01" in _timing_cell({"startedAt": "2026-07-01T00:00:00Z"}))
    check("_timing_cell is an em dash with neither",
          '<span class="muted">—</span>' == _timing_cell({}))

    # --- _filter_attrs() / _filter_panel(): server-rendered filter state --------
    check("_filter_attrs emits only what is present",
          _filter_attrs({}) == ""
          and 'data-model="opus"' in _filter_attrs({"model": "opus"}))
    check("_filter_attrs cuts dates to their date part",
          'data-completed="2026-07-09"' in
          _filter_attrs({"completedAt": "2026-07-09T09:30:00Z"}))
    _plain = {"phases": [{"tasks": [{"id": "t1"}]}]}
    check("_filter_panel is '' for a plan with no models and no dates",
          _filter_panel(_plain) == "")
    _withmodel = {"phases": [{"tasks": [{"model": "opus"}]}]}
    check("_filter_panel renders the model chip row when a task has a model",
          'data-m="opus"' in _filter_panel(_withmodel))
    _withdates = {"phases": [{"tasks": [
        {"startedAt": "2026-07-01T00:00:00Z", "completedAt": "2026-07-09T00:00:00Z"}]}]}
    check("_filter_panel's date range spans the earliest to the latest date",
          'min="2026-07-01" max="2026-07-09"' in _filter_panel(_withdates))
    # D1: the Area chip row. A tag is enough on its own to earn the panel — the
    # plan below has no models and no dates — and the chips keep the tags'
    # first-seen order, deduped across phases by _areas.used_tags.
    _witharea = {"phases": [
        {"id": "P1", "area": "backend", "tasks": [{"id": "P1.1"}]},
        {"id": "P2", "area": ["web", "backend"], "tasks": []}]}
    _area_panel = _filter_panel(_witharea)
    check("_filter_panel renders the Area chip row when any phase carries a tag "
          "(a tag alone earns the panel)",
          'id="audit-areas"' in _area_panel
          and 'class="fchip" data-a="backend"' in _area_panel
          and 'data-a="web"' in _area_panel)
    check("_filter_panel keeps area tags in first-seen order, deduped, spelled "
          "as identifiers rather than humanized",
          _area_panel.index('data-a="backend"') < _area_panel.index('data-a="web"')
          and _area_panel.count('data-a="backend"') == 1
          and ">backend</button>" in _area_panel)
    check("_filter_panel omits the Area row for a plan without tags",
          'id="audit-areas"' not in _filter_panel(_withmodel))

    # --- _global_filter_row(): the sticky bar's compact filter line (C1/C2) ----
    _grow = _global_filter_row(["b@x.io", "a@x.io"], ["api", "web"],
                               "2026-07-01", "2026-08-02")
    check("_global_filter_row renders author select, area select and the date "
          "pair with the data's own bounds",
          'id="audit-au-select"' in _grow and 'id="audit-area-select"' in _grow
          and 'id="audit-gfrom"' in _grow and 'id="audit-gto"' in _grow
          and _grow.count('min="2026-07-01" max="2026-08-02"') == 2)
    check("_global_filter_row keeps the callers' ordering (authors by spend, "
          "tags first-seen) instead of re-sorting identifiers",
          _grow.index('value="b@x.io"') < _grow.index('value="a@x.io"')
          and _grow.index('value="api"') < _grow.index('value="web"'))
    check("_global_filter_row offers the way back from a range (the All time "
          "reset, hidden until a range is on)",
          'id="audit-gclear" hidden' in _grow)
    check("_global_filter_row renders no author select for a single author "
          "(a set of one has nothing to filter)",
          'id="audit-au-select"' not in
          _global_filter_row(["only@x.io"], ["api"], None, None))
    check("_global_filter_row is '' with nothing to filter by",
          _global_filter_row([], [], None, None) == "")
    check("_global_filter_row escapes a hostile tag before it reaches an "
          "attribute",
          "&lt;script&gt;" in _global_filter_row([], ["<script>"], None, None))

    # --- _ready_now_dl(): the Ready-now definition list (C4) --------------------
    _rm = {"phases": [
        {"id": "P1", "title": "Alpha", "status": "done", "area": ["api", "web"],
         "tasks": [{"id": "P1.1", "title": "done dep", "status": "done"}]},
        {"id": "P2", "title": "Beta", "status": "pending",
         "blockedBy": ["P1"],
         "tasks": [
             {"id": "P2.1", "title": "cleared one", "status": "pending",
              "blockedBy": ["P1.1"], "dependsOn": ["P1.1"]},
             {"id": "P2.2", "title": "free one", "status": "pending"}]}]}
    _rdl = _ready_now_dl(_rm, ["P2.1", "P2.2"])
    check("_ready_now_dl is a definition list with one term per ready task, "
          "id and title both named",
          _rdl.startswith('<dl class="ready">')
          and _rdl.count("<dt>") == 2 and _rdl.count("<dd>") == 2
          and ">P2.1</code>" in _rdl and "<strong>cleared one</strong>" in _rdl)
    check("_ready_now_dl states the blockers that cleared, with the evidence",
          "depends on P1.1 (done)" in _rdl
          and "blocked by P1.1 (done)" in _rdl
          and "phase blocked by P1 (done)" in _rdl)
    _rdl_area = _ready_now_dl(
        {"phases": [{"id": "P1", "area": "api",
                     "tasks": [{"id": "P1.1", "title": "t",
                                "status": "pending"}]}]}, ["P1.1"])
    # P2.2 above does NOT earn this line: its own list is empty but its PHASE
    # cleared a blocker, and that context is the more useful sentence. Only a
    # task with no blockers anywhere says nothing ever blocked it.
    check("_ready_now_dl says when nothing ever blocked a task, and only when "
          "nothing did (a cleared phase blocker still counts as context)",
          "Nothing blocked it" in _rdl_area
          and "Nothing blocked it" not in _rdl)
    check("_ready_now_dl carries the phase's area tags in the same chip style "
          "areas wear everywhere else",
          '<span class="area-tag">api</span>' in _rdl_area)
    check("_ready_now_dl names the phase the task sits in",
          'In <span class="mono">P2</span>' in _rdl)
    check("_ready_now_dl is '' for an empty list (the hero line is the empty "
          "state)", _ready_now_dl(_rm, []) == "")
    check("_ready_now_dl escapes a hostile title",
          "&lt;script&gt;" in _ready_now_dl(
              {"phases": [{"id": "P1", "tasks": [
                  {"id": "P1.1", "title": "<script>", "status": "pending"}]}]},
              ["P1.1"]))

    # --- _owner_map() / _area_tag_span(): advisory area owners (D4, v0.36) ------
    _own_m = {"meta": {"areas": {"api": {"owner": " ana@x.io "},
                                 "web": {"owner": None},
                                 "db": {"owner": 3},
                                 "ops": {"description": "no owner key"}}}}
    check("_owner_map keeps only tags declaring a non-empty string owner, "
          "trimmed - null, junk and undeclared all read as nobody",
          _owner_map(_own_m) == {"api": "ana@x.io"})
    check("_owner_map is {} for a manifest without a registry",
          _owner_map({}) == {} and _owner_map(None) == {})
    check("_area_tag_span with no owner is byte-identical to the bare chip",
          _area_tag_span("web", {"api": "a@x.io"})
          == '<span class="area-tag">web</span>')
    check("_area_tag_span with an owner wears the advisory suffix and the "
          "panel's exact title wording",
          _area_tag_span("api", {"api": "ana@x.io"})
          == '<span class="area-tag" title="owner: ana@x.io">api'
             '<span class="aown"> — ana@x.io</span></span>')
    check("_area_tag_span escapes a hostile owner",
          "&lt;script&gt;" in _area_tag_span("api", {"api": "<script>"})
          and "<script>" not in _area_tag_span("api", {"api": "<script>"}))
    check("_chip_buttons titles: an entry in `titles` becomes the chip's title "
          "attribute, and an untitled chip keeps the pinned untitled shape",
          '<button type="button" class="fchip" data-a="api" '
          'title="owner: a@x.io" aria-pressed="false">api</button>'
          == _chip_buttons(["api"], "data-a", "fchip", humanize=False,
                           titles={"api": "owner: a@x.io"})
          and '<button type="button" class="fchip" data-a="api" '
              'aria-pressed="false">api</button>'
          == _chip_buttons(["api"], "data-a", "fchip", humanize=False))
    check("_filter_panel titles its area chips from the registry",
          'data-a="backend" title="owner: bo@x.io"' in _filter_panel(
              dict(_witharea, meta={"areas": {"backend": {"owner": "bo@x.io"}}}))
          and 'title="owner:' not in _area_panel)
    check("_global_filter_row titles its options the same way, and only where "
          "an owner is declared",
          '<option value="api" title="owner: ana@x.io">api</option>'
          in _global_filter_row([], ["api", "web"], None, None,
                                owners={"api": "ana@x.io"})
          and '<option value="web">web</option>'
          in _global_filter_row([], ["api", "web"], None, None,
                                owners={"api": "ana@x.io"}))
    check("_ready_now_dl wears the same suffix on its tags",
          '<span class="aown"> — ro@x.io</span>' in _ready_now_dl(
              {"meta": {"areas": {"api": {"owner": "ro@x.io"}}},
               "phases": [{"id": "P1", "area": "api",
                           "tasks": [{"id": "P1.1", "title": "t",
                                      "status": "pending"}]}]}, ["P1.1"]))

    # --- _seg_of(): the segment a phase row files under (D1, v0.36) -------------
    check("_seg_of maps in_progress and blocked to active, BOTH terminal states "
          "to the archive, and everything else - pending, unknown, None - to "
          "pending",
          _seg_of("in_progress") == "active" and _seg_of("blocked") == "active"
          and _seg_of("done") == "archived" and _seg_of("cancelled") == "archived"
          and _seg_of("pending") == "pending"
          and _seg_of("weird") == "pending" and _seg_of(None) == "pending")
    check("VIEW_SEGS names the three views, and 'active' covers the two "
          "segments of unfinished work - a reader asking what is left means "
          "pending too",
          set(VIEW_SEGS) == {"active", "archived", "all"}
          and VIEW_SEGS["active"] == ("active", "pending")
          and VIEW_SEGS["all"] == SEG_ORDER)

    # --- tm / sha: the two table cells a reader has to ACT on --------------------
    check("tm the completion cell carries the clock, not just the day - two "
          "tasks finishing on one day is the case the column is read for",
          _stamp("2026-06-28T10:04:59Z") == "2026-06-28 10:04"
          and _stamp("2026-06-28") == "2026-06-28" and _stamp(None) == ""
          and "2026-06-28 10:04" in _timing_cell({"completedAt": "2026-06-28T10:04:59Z"}))
    check("tm ...and the full stamps stay on hover, both of them",
          "started 2026-06-28T09:00:00Z" in _timing_cell(
              {"startedAt": "2026-06-28T09:00:00Z",
               "completedAt": "2026-06-28T10:04:59Z"}))
    check("sha the commit cell shows nine characters and copies FORTY - nine is "
          "not what cherry-pick wants",
          "abc1234de" in _commit_cell({"commit": "abc1234de567890"})
          and 'data-copy="abc1234de567890"' in _commit_cell(
              {"commit": "abc1234de567890"})
          and "btn-copy" in _commit_cell({"commit": "abc1234de567890"}))
    check("sha a task with no commit gets an em dash and no button to press",
          "btn-copy" not in _commit_cell({})
          and "\u2014" in _commit_cell({"commit": "  "}))

    # --- _phase_meta_div() / _bar() ----------------------------------------------
    check("_phase_meta_div is '' with nothing to say",
          _phase_meta_div({}) == "")
    check("_phase_meta_div joins present bits with a middot, all escaped",
          "branch audit/p1" in _phase_meta_div({"branch": "audit/p1"})
          and "&lt;script&gt;" in _phase_meta_div({"summary": "<script>"}))
    check("_bar computes a rounded percentage",
          '--w:50%' in _bar(1, 2) and "1/2" in _bar(1, 2))
    check("_bar is 0% for a zero total (never a ZeroDivisionError)",
          '--w:0%' in _bar(0, 0) and "0/0" in _bar(0, 0))

    passed = sum(1 for _, ok in cases if ok)
    for label, ok in cases:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    print("\n%s: %d/%d cases passed" % (
        "ALL PASS" if passed == len(cases) else "FAILURES", passed, len(cases)))
    return 0 if passed == len(cases) else 1


# --- cli --------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(_selftest())
    print(__doc__.strip())
