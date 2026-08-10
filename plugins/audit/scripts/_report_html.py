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


def _areas_of(area):
    """A phase's `area` (string, list, or absent) -> a list of tag strings."""
    if isinstance(area, str):
        return [area] if area else []
    if isinstance(area, list):
        return [a for a in area if isinstance(a, str) and a]
    return []


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


def _chip_buttons(statuses, attr, cls, humanize=True):
    """Toggle buttons for a set of values — machine value in `attr`, words shown.

    `aria-pressed` is what makes a toggle's state readable; without it "which
    filter is on" is carried by colour alone.

    `humanize` is off for values that are IDENTIFIERS rather than vocabulary. A
    status is a word this product chose and should read as English; a model name
    is a string someone types into a manifest and reads back out of a bill, and
    running it through label() gave a chip reading "Opus" beside a table cell
    reading `opus` — two spellings of one value, in one table.
    """
    return "".join(
        '<button type="button" class="%s" %s="%s" aria-pressed="false">%s</button>'
        % (cls, attr, e(s), e(_theme.label(s) if humanize else s))
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


def _timing_cell(task):
    """Compact completion date for the table, with the full started/completed
    timestamps on hover. Done -> completed date; started-but-not-done -> the
    started date (muted); neither -> em dash."""
    started, completed = task.get("startedAt"), task.get("completedAt")
    tip = e("started %s · completed %s" % (started or "—", completed or "—"))
    if completed:
        return '<span title="%s">%s</span>' % (tip, e(_short_date(completed)))
    if started:
        return ('<span class="muted" title="%s">started %s</span>'
                % (tip, e(_short_date(started))))
    return '<span class="muted">—</span>'


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
    """The model and date controls, server-rendered, or "" when the plan has neither.

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
    if not models and not dates:
        return ""

    rows = []
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
