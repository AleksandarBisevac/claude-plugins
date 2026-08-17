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
use layer 1 — `_ui_theme` for status/label vocabulary (same as the panel),
`_areas` for tag derivation, and `_manifest_io` for reading a manifest's
shape, which is where the id -> task index and the derived bug status live so
this file and the layer-7 commands cannot drift apart.

This module carries no `--selftest` of its own any more; its 93 cases live in
`plugins/audit/tests/test__report_html.py`, byte-identical labels and all - see
`plugins/audit/tests/_harness.py`.
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
import _manifest_io  # noqa: E402  (one home for reading a manifest's shape)


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
# The id -> task index. One implementation, in `_manifest_io`, the same one
# audit-status and the panel reach for. The local copy this alias replaced agreed
# with it on every manifest a validator would accept — same falsy-id filter, same
# LAST-wins duplicate rule, same tolerance of a non-dict phase or task — and
# disagreed on exactly one input: a JSON document whose ROOT is not an object
# survives `load_manifest` unchanged, and the copy raised AttributeError on it
# where the shared one returns {}. render-report would have crashed rather than
# rendered an empty report; a lookup is not the right place to discover that, and
# `validate-manifest` is the reader that names it.
_tasks_by_id = _manifest_io.tasks_by_id


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
    """(status, fixedIn) for a bug row — the PRESENTATION half of the bug status.

    The rule itself is not decided here any more: `_manifest_io.effective_bug_status`
    owns it, and this is the wrapper that adds the `fixedIn` cell. That split is the
    point — the derivation had three homes (audit-status, the panel, this file, whose
    docstring said it "mirrored" audit-status) and layer 2 cannot import layer 7, so
    the copy was structural. The em dash stays HERE, deliberately: a placeholder is
    what a table draws when a cell is empty, and layer 1 has no table.

    Adopting the shared rule also picks up its falsy-`taskId` guard, which this file
    did not have: given an index built WITHOUT the truthy-id filter (audit-status's
    ready-list index is one), a bug carrying no `taskId` used to look up the `None`
    key, find a task, and read 'fixed'. Pinned below by two cases.
    """
    status = _manifest_io.effective_bug_status(b, task_by_id)
    # DECIDED, and it is the `x or default` shape the house rules single out, so it
    # is written down rather than left to the reader: an empty-string `fixedIn` means
    # "nothing recorded", NOT "recorded as empty". The field holds a commit-ish
    # reference and "" is not one — it is the shape a form or a hand edit leaves
    # behind, carrying no claim about where the fix landed. So it falls through to
    # the linked task's commit exactly as a missing key does; treating it as a
    # recorded value would print the placeholder beside a bug whose fix has a known
    # commit, which is less true, not more careful.
    recorded = b.get("fixedIn")
    if recorded:
        return status, recorded
    if status == "fixed":
        # The inner `done` check is not redundant with `status == "fixed"`: a bug can
        # carry a STORED 'fixed' while its linked task is still running, and that
        # task's commit is not the fix. The commit is borrowed only where the
        # derivation itself fired.
        tid = b.get("taskId")
        task = task_by_id.get(tid) if tid else None
        if isinstance(task, dict) and task.get("status") == "done":
            return status, (task.get("commit") or "—")
    return status, "—"


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
    for _, t in _manifest_io.iter_tasks(manifest):
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
    # One pass, not two: `phase_of` wants the phase BODY (its `area` and its
    # `blockedBy` are read below), which `_manifest_io.phase_of_task` deliberately
    # does not carry — it answers with an id. `iter_tasks` yields the pair, which
    # is the case its docstring names, and both dicts keep the shared truthy-id
    # filter and LAST-wins rule for free.
    task_of, phase_of = {}, {}
    for ph, t in _manifest_io.iter_tasks(manifest):
        if t.get("id"):
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


# --- cli --------------------------------------------------------------------
if __name__ == "__main__":
    from _output import safe_stdio  # same dir; sys.path[0] when run as a command
    safe_stdio()
    if "--selftest" in sys.argv[1:]:
        # Answers rather than exits silently: `--selftest` is what every other
        # file here still accepts, so nothing would tell a reader whether this
        # one ran nothing or has nothing. It deliberately does NOT print the
        # suite contract - that literal is how `_output.selftest_coverage()`
        # tells an inline suite from a migrated one.
        print("_report_html.py has no inline --selftest; its cases moved to "
              "plugins/audit/tests/test__report_html.py - run that file instead.")
        raise SystemExit(0)
    print(__doc__.strip())
