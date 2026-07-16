#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py <manifest> [--out-dir DIR] [--format html|md|both]
  render-report.py --selftest

Writes audit-report.html / audit-report.md into --out-dir (default: the
manifest's own directory) and prints the paths.
Exit codes: 0 ok · 2 usage error / unreadable manifest.
"""
import html
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

STATUS_COLORS = {
    "done": "#1a7f37", "in_progress": "#9a6700", "blocked": "#cf222e",
    "pending": "#57606a",
    "open": "#cf222e", "triaged": "#9a6700", "fixed": "#1a7f37",
    "wontfix": "#57606a",
}

_CSS = """
body{font:15px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;margin:2rem auto;
     max-width:64rem;padding:0 1rem;color:#1f2328}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #d1d9e0;
   padding-bottom:.3rem}
table{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.92em}
th,td{border:1px solid #d1d9e0;padding:.35rem .6rem;text-align:left;vertical-align:top}
th{background:#f6f8fa}
.chip{display:inline-block;padding:0 .5em;border-radius:1em;color:#fff;font-size:.85em}
.bar{background:#eaeef2;border-radius:.4em;height:.7em;width:12em;display:inline-block;
     vertical-align:middle;overflow:hidden}
.fill{background:#1a7f37;height:100%}
.muted{color:#57606a}.mono{font-family:ui-monospace,monospace;font-size:.9em}
.outcome{color:#57606a;font-style:italic;margin:.25rem 0 .5rem}
.overall{background:#f6f8fa;border:1px solid #d1d9e0;border-radius:.5em;padding:.6rem .8rem;margin:1rem 0}
td.muted{font-size:.88em}
.toolbar{position:sticky;top:0;background:#fff;padding:.6rem 0;margin:1rem 0 .5rem;
         border-bottom:1px solid #d1d9e0;display:flex;gap:.5rem;align-items:center;
         flex-wrap:wrap;z-index:3}
#audit-q{flex:1 1 16rem;min-width:11rem;padding:.35rem .6rem;font:inherit;
         border:1px solid #d1d9e0;border-radius:.4em}
.tbl{font-size:.82em;color:#57606a}
#audit-phase-status{display:inline-flex;gap:.3rem;flex-wrap:wrap}
.fchip{cursor:pointer;border:1px solid #d1d9e0;background:#f6f8fa;color:#1f2328;
       border-radius:1em;padding:.05rem .6rem;font:inherit;font-size:.85em}
.fchip.on{background:#0969da;color:#fff;border-color:#0969da}
table.phases thead th,table.data th{cursor:pointer;user-select:none;white-space:nowrap}
table.phases thead th{position:sticky;top:2.9rem;z-index:1}
th.sorted::after{content:"\\25B2";font-size:.7em;margin-left:.3em;color:#57606a}
th.sorted[data-sort="desc"]::after{content:"\\25BC"}
tr.phase{background:#f6f8fa;cursor:pointer}
tr.phase:hover{background:#eef1f4}
tr.phase>td{border-top:2px solid #c8d1da}
.tri::before{content:"\\25B6";display:inline-block;width:1em;color:#57606a;font-size:.8em}
tr.phase.open .tri::before{content:"\\25BC"}
tr.task>td.tid{padding-left:1.7rem}
.pmeta{font-size:.85em;margin-top:.15rem}
tr.taskfilter{display:none;background:#fbfcfd}
tr.taskfilter>td{padding:.3rem .6rem .3rem 1.7rem;border-top:none}
.tf-label{font-size:.82em;color:#57606a;margin-right:.4rem}
.tf-chips{display:inline-flex;gap:.3rem;flex-wrap:wrap}
.tf-chip{cursor:pointer;border:1px solid #d1d9e0;background:#fff;color:#1f2328;
         border-radius:1em;padding:0 .5em;font:inherit;font-size:.8em}
.tf-chip.on{background:#0969da;color:#fff;border-color:#0969da}
@media print{.toolbar,tr.taskfilter{display:none!important}tr.task{display:table-row!important}}
"""

# Inline, self-contained (no external fetch) filter/sort/search over the report
# tables. Progressive enhancement: the report is fully readable with JS off.
_SCRIPT = r"""<script>
(function () {
  var q = document.getElementById('audit-q');
  var count = document.getElementById('audit-count');
  var phaseStatusBar = document.getElementById('audit-phase-status');
  var expandBtn = document.getElementById('audit-expand');
  var grouped = document.querySelector('table.phases');
  var bugsTable = document.querySelector('table.bugs');
  if (!grouped) return;
  var phaseRows = [].slice.call(grouped.querySelectorAll('tbody tr.phase'));
  var bugRows = bugsTable ? [].slice.call(bugsTable.querySelectorAll('tbody tr')) : [];

  // Expand state persists across filtering AND page reload (best-effort;
  // localStorage may be unavailable on file:// in some browsers).
  var STORE = 'audit-report-expanded:' + (document.title || 'report');
  var expanded = {};
  try { expanded = JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) {}
  function persist() { try { localStorage.setItem(STORE, JSON.stringify(expanded)); } catch (e) {} }

  var phaseStatus = '';   // toolbar: filter which PHASES show, by phase status
  var taskStatus = {};    // per phase: filter that phase's TASKS, by task status

  function esc(v) { return (window.CSS && CSS.escape) ? CSS.escape(v) : v; }
  function tasksOf(pid) { return [].slice.call(grouped.querySelectorAll('tbody tr.task[data-phase="' + esc(pid) + '"]')); }
  function tfOf(pid) { return grouped.querySelector('tbody tr.taskfilter[data-phase="' + esc(pid) + '"]'); }
  function textHit(r, term) { return !term || r.textContent.toLowerCase().indexOf(term) !== -1; }
  function setOpen(pr, open) { pr.classList.toggle('open', !!open); pr.setAttribute('aria-expanded', open ? 'true' : 'false'); }

  function refresh() {
    var term = (q ? q.value : '').trim().toLowerCase();
    var visP = 0;
    phaseRows.forEach(function (pr) {
      var pid = pr.getAttribute('data-phase');
      var tasks = tasksOf(pid);
      var tf = taskStatus[pid] || '';
      var pText = textHit(pr, term);
      var taskShown = function (t) { return (pText || textHit(t, term)) && (!tf || t.getAttribute('data-status') === tf); };
      var anyTaskText = tasks.some(function (t) { return textHit(t, term); });
      // phase-level: phase-status filter + text (phase title OR any task matches)
      var showP = (!phaseStatus || pr.getAttribute('data-status') === phaseStatus)
                  && (term === '' || pText || anyTaskText);
      pr.style.display = showP ? '' : 'none';
      if (showP) visP++;
      // open when drilling into tasks (text or task-status filter active), else manual
      var open = showP && ((term !== '' || tf !== '') || !!expanded[pid]);
      setOpen(pr, open);
      var tfRow = tfOf(pid);
      if (tfRow) tfRow.style.display = open ? '' : 'none';
      tasks.forEach(function (t) { t.style.display = (open && taskShown(t)) ? '' : 'none'; });
    });
    bugRows.forEach(function (b) { b.style.display = textHit(b, term) ? '' : 'none'; });

    if (count) {
      var filtered = term !== '' || phaseStatus !== '';
      count.textContent = filtered ? (visP + ' / ' + phaseRows.length + ' phases') : (phaseRows.length + ' phases');
    }
    if (expandBtn) {
      var anyClosed = phaseRows.some(function (pr) { return !expanded[pr.getAttribute('data-phase')]; });
      expandBtn.textContent = anyClosed ? 'expand all' : 'collapse all';
    }
  }

  function natCmp(a, b) {
    var ax = [], bx = [];
    a.replace(/(\d+)|(\D+)/g, function (_, n, s) { ax.push([n === undefined ? Infinity : +n, s || '']); });
    b.replace(/(\d+)|(\D+)/g, function (_, n, s) { bx.push([n === undefined ? Infinity : +n, s || '']); });
    while (ax.length && bx.length) {
      var an = ax.shift(), bn = bx.shift();
      var c = (an[0] - bn[0]) || an[1].localeCompare(bn[1]);
      if (c) return c;
    }
    return ax.length - bx.length;
  }
  function cell(r, idx) { return r.cells[idx] ? r.cells[idx].textContent.trim() : ''; }

  function wireSort(table, withinPhase) {
    if (!table) return;
    var ths = table.querySelectorAll('thead th');
    [].forEach.call(ths, function (th, idx) {
      th.addEventListener('click', function () {
        var asc = th.getAttribute('data-sort') !== 'asc';
        [].forEach.call(ths, function (h) { h.removeAttribute('data-sort'); h.classList.remove('sorted'); });
        th.setAttribute('data-sort', asc ? 'asc' : 'desc');
        th.classList.add('sorted');
        var cmp = function (r1, r2) { return asc ? natCmp(cell(r1, idx), cell(r2, idx)) : natCmp(cell(r2, idx), cell(r1, idx)); };
        if (withinPhase) {
          phaseRows.forEach(function (pr) {
            var pid = pr.getAttribute('data-phase');
            var anchor = tfOf(pid) || pr;   // keep tasks after the phase + its task-filter row
            tasksOf(pid).sort(cmp).reverse()
              .forEach(function (r) { anchor.parentNode.insertBefore(r, anchor.nextSibling); });
          });
        } else {
          var body = table.tBodies[0];
          [].slice.call(body.querySelectorAll('tr')).sort(cmp).forEach(function (r) { body.appendChild(r); });
        }
        refresh();
      });
    });
  }

  // build a toggle-chip bar from a set of statuses
  function buildChips(host, statuses, dataAttr, onToggle) {
    Object.keys(statuses).sort().forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'fchip';
      b.setAttribute(dataAttr, s); b.textContent = s;
      host.appendChild(b);
    });
    host.addEventListener('click', function (e) {
      var val = e.target && e.target.getAttribute(dataAttr);
      if (!val) return;
      onToggle(val, host, dataAttr);
    });
  }
  function highlight(host, dataAttr, active) {
    [].forEach.call(host.children, function (x) {
      x.className = (x.getAttribute(dataAttr) === active ? x.className.split(' ')[0] + ' on' : x.className.split(' ')[0]);
    });
  }

  // phase expand/collapse (click or Enter/Space); state persists
  phaseRows.forEach(function (pr) {
    function toggle() { var pid = pr.getAttribute('data-phase'); expanded[pid] = !expanded[pid]; persist(); refresh(); }
    pr.addEventListener('click', toggle);
    pr.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });
  if (expandBtn) expandBtn.addEventListener('click', function () {
    var anyClosed = phaseRows.some(function (pr) { return !expanded[pr.getAttribute('data-phase')]; });
    phaseRows.forEach(function (pr) { expanded[pr.getAttribute('data-phase')] = anyClosed; });
    persist(); refresh();
  });

  // toolbar phase-status chips (distinct PHASE statuses)
  if (phaseStatusBar) {
    var pseen = {};
    phaseRows.forEach(function (pr) { var s = pr.getAttribute('data-status'); if (s) pseen[s] = 1; });
    buildChips(phaseStatusBar, pseen, 'data-ps', function (val, host, attr) {
      phaseStatus = (phaseStatus === val) ? '' : val;
      highlight(host, attr, phaseStatus);
      refresh();
    });
  }

  // per-phase task-status chips (contextual — only that phase's task statuses)
  phaseRows.forEach(function (pr) {
    var pid = pr.getAttribute('data-phase');
    var tfRow = tfOf(pid); if (!tfRow) return;
    var host = tfRow.querySelector('.tf-chips'); if (!host) return;
    var seen = {};
    tasksOf(pid).forEach(function (t) { var s = t.getAttribute('data-status'); if (s) seen[s] = 1; });
    Object.keys(seen).sort().forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'tf-chip';
      b.setAttribute('data-ts', s); b.textContent = s;
      host.appendChild(b);
    });
    host.addEventListener('click', function (e) {
      var val = e.target && e.target.getAttribute('data-ts'); if (!val) return;
      taskStatus[pid] = (taskStatus[pid] === val) ? '' : val;
      [].forEach.call(host.children, function (x) { x.className = x.getAttribute('data-ts') === taskStatus[pid] ? 'tf-chip on' : 'tf-chip'; });
      refresh();
    });
  });

  wireSort(grouped, true);
  wireSort(bugsTable, false);
  if (q) q.addEventListener('input', refresh);
  refresh();
})();
</script>"""


def _load_status_lib():
    spec = importlib.util.spec_from_file_location(
        "audit_status", os.path.join(_HERE, "audit-status.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def e(value):
    """Escape ANY manifest value for HTML context."""
    return html.escape(str(value if value is not None else ""), quote=True)


def _safe_url(url):
    """Return the url only when it is plain http(s) — else None (render as text)."""
    u = str(url or "")
    return u if u.startswith(("https://", "http://")) else None


def _chip(status):
    color = STATUS_COLORS.get(str(status), "#57606a")
    return '<span class="chip" style="background:%s">%s</span>' % (color, e(status))


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
    pct = int(round(100.0 * done / total)) if total else 0
    return ('<span class="bar"><span class="fill" style="width:%d%%"></span></span> '
            '<span class="muted">%d/%d</span>' % (pct, done, total))


def render_html(manifest, summary):
    meta = manifest.get("meta") or {}
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    # doctype + charset so the file renders standalone (not quirks mode) and its
    # UTF-8 punctuation (·, —, …) decodes correctly when opened from disk.
    out = ['<!doctype html>',
           '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<title>%s</title>' % e(meta.get("title") or "Audit report"),
           "<style>%s</style>" % _CSS]
    out.append("<h1>%s</h1>" % e(meta.get("title") or "Audit report"))
    out.append('<p class="muted">repo: %s · generated %s · %d phases · %d tasks'
               " · %d bugs</p>"
               % (e(meta.get("repo") or "?"), now, len(summary["phases"]),
                  summary["tasks"]["total"], summary["bugs"]["total"]))
    if not summary["valid"]:
        out.append('<p><strong style="color:#cf222e">INVALID MANIFEST: %d '
                   "validator finding(s) — fix before trusting this report."
                   "</strong></p>" % summary["findings"])

    # Overall progress header: total task completion + phase/bug rollup.
    tdone = sum(p["done"] for p in summary["phases"])
    ttotal = summary["tasks"]["total"]
    phdone = sum(1 for p in summary["phases"] if p["status"] == "done")
    out.append('<div class="overall"><strong>Overall</strong> %s '
               '<span class="muted">· %d/%d phases signed off · %d open bug(s)'
               " · %d ready now</span></div>"
               % (_bar(tdone, ttotal), phdone, len(summary["phases"]),
                  summary["bugs"]["open"], len(summary["ready"])))

    # Interactive toolbar (search + per-status quick-filter). Enhanced by
    # _SCRIPT; with JS off the tables below are still fully readable.
    out.append(
        '<div class="toolbar" role="search">'
        '<input id="audit-q" type="search" aria-label="Filter phases and tasks by text" '
        'placeholder="Filter phases &amp; tasks by text…">'
        '<span class="tbl">Phase status:</span><span id="audit-phase-status"></span>'
        '<button type="button" id="audit-expand" class="fchip">expand all</button>'
        '<span id="audit-count" class="muted"></span></div>')

    # One collapsible table: each phase is a group-row (click to expand its task
    # rows). Default-collapsed via _SCRIPT; with JS off every row is visible.
    out.append('<table class="phases"><thead><tr>'
               "<th>id</th><th>title</th><th>status</th><th>model</th>"
               "<th>risk</th><th>commit</th><th>ADO</th><th>outcome</th>"
               "</tr></thead><tbody>")
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        pid = psum["id"]
        out.append(
            '<tr class="phase" data-phase="%s" data-status="%s" tabindex="0" '
            'aria-expanded="false"><td colspan="8"><span class="tri"></span> '
            '<span class="mono">%s</span> <strong>%s</strong> %s %s%s</td></tr>'
            % (e(pid), e(psum["status"]), e(pid), e(psum["title"]),
               _chip(psum["status"]), _bar(psum["done"], psum["total"]),
               _phase_meta_div(ph)))
        # per-phase task-status filter (shown only when the phase is expanded);
        # _SCRIPT fills .tf-chips from this phase's own task statuses.
        out.append('<tr class="taskfilter" data-phase="%s"><td colspan="8">'
                   '<span class="tf-label">Filter tasks by status:</span>'
                   '<span class="tf-chips"></span></td></tr>' % e(pid))
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            out.append(
                '<tr class="task" data-phase="%s" data-status="%s">'
                '<td class="mono tid">%s</td><td>%s</td><td>%s</td>'
                "<td>%s</td><td>%s</td><td class=mono>%s</td><td>%s</td>"
                "<td class=muted>%s</td></tr>"
                % (e(pid), e(t.get("status")), e(t.get("id")), e(t.get("title")),
                   _chip(t.get("status")), e(t.get("model") or "—"),
                   e(t.get("risk") or "—"), e((t.get("commit") or "—")[:9]),
                   _ado_cell(t), e(_outcome_text(t))))
    out.append("</tbody></table>")

    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        out.append("<h2>Bugs</h2>")
        rows = []
        for b in bugs:
            rows.append(
                '<tr data-status="%s"><td class=mono>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                "<td class=mono>%s</td><td class=mono>%s</td><td>%s</td></tr>"
                % (e(b.get("status")), e(b.get("id")), e(b.get("title")),
                   _chip(b.get("status")),
                   e(b.get("severity") or "—"), e(b.get("taskId") or "—"),
                   e((b.get("fixedIn") or "—")[:9]), _ado_cell(b)))
        out.append('<table class="data bugs"><thead><tr><th>id</th><th>title</th>'
                   "<th>status</th><th>severity</th><th>task</th><th>fixedIn</th>"
                   "<th>ADO</th></tr></thead><tbody>%s</tbody></table>"
                   % "".join(rows))

    if summary["ready"]:
        out.append("<h2>Ready now</h2><p class=mono>%s</p>"
                   % ", ".join(e(r) for r in summary["ready"]))
    out.append(_SCRIPT)
    return "\n".join(out) + "\n"


def render_md(manifest, summary):
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
        out += ["", "| id | title | status | model | risk | commit | ADO |",
                "|---|---|---|---|---|---|---|"]
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            ado = t.get("ado") if isinstance(t.get("ado"), dict) else None
            ado_txt = "#%s" % ado["id"] if ado and ado.get("id") is not None else "—"
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                cell(t.get("id")), cell(t.get("title")), cell(t.get("status")),
                cell(t.get("model") or "—"), cell(t.get("risk") or "—"),
                cell((t.get("commit") or "—")[:9]), cell(ado_txt)))
        out.append("")
    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        out += ["## Bugs", "",
                "| id | title | status | severity | task | fixedIn |",
                "|---|---|---|---|---|---|"]
        for b in bugs:
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(b.get("id")), cell(b.get("title")), cell(b.get("status")),
                cell(b.get("severity") or "—"), cell(b.get("taskId") or "—"),
                cell((b.get("fixedIn") or "—")[:9])))
        out.append("")
    if summary["ready"]:
        out += ["## Ready now", "", ", ".join(cell(r) for r in summary["ready"]), ""]
    return "\n".join(out)


def main(argv):
    args = list(argv)
    out_dir = None
    fmt = "both"
    for flag, val in (("--out-dir", True), ("--format", True)):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.stderr.write("usage: %s needs a value\n" % flag)
                return 2
            if flag == "--out-dir":
                out_dir = args[i + 1]
            else:
                fmt = args[i + 1]
            del args[i:i + 2]
    if fmt not in ("html", "md", "both") or len(args) != 1:
        sys.stderr.write("usage: render-report.py <manifest> [--out-dir DIR] "
                         "[--format html|md|both]\n")
        return 2

    manifest_path = args[0]
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot read/parse %s: %s\n" % (manifest_path, exc))
        return 2
    if not isinstance(manifest, dict):
        sys.stderr.write("ERROR: %s is not a JSON object (got %s)\n"
                         % (manifest_path, type(manifest).__name__))
        return 2

    lib = _load_status_lib()
    vm = lib._load_validator()
    try:
        findings, warnings = vm.validate(manifest)
    except Exception as exc:  # defensive
        findings, warnings = ["internal validator error: %s" % exc], []
    summary = lib.rollup(manifest, findings, warnings)

    out_dir = out_dir or (os.path.dirname(os.path.abspath(manifest_path)) or ".")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if fmt in ("html", "both"):
        p = os.path.join(out_dir, "audit-report.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_html(manifest, summary))
        written.append(p)
    if fmt in ("md", "both"):
        p = os.path.join(out_dir, "audit-report.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(render_md(manifest, summary))
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
        "meta": {"version": 2, "title": evil_title, "repo": "r"},
        "phases": [
            {"id": "P1", "title": "Phase & <b>bold</b>", "status": "in_progress",
             "desiredOutcome": "Outcome with <img src=x onerror=alert(1)>",
             "branch": "audit/p1-x", "mergedAt": "2026-07-09T00:00:00Z",
             "tasks": [
                 {"id": "P1.1", "title": "done task", "status": "done",
                  "commit": "abcdef1234567", "files": ["src/a.ts"],
                  "outcome": {"descriptive": "did the thing cleanly"},
                  "ado": {"id": 42, "url": "https://dev.azure.com/o/p/_workitems/edit/42"}},
                 {"id": "P1.2", "title": "evil url", "status": "pending",
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
    check("x5 zero external fetches",
          "http" not in html_out.replace('href="https://dev.azure.com/o/p/_workitems/edit/42"', ""))
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
    check("r1 ready list rendered", "P1.2" in md_out)

    rc = main([mp, "--format", "nope"])
    check("c3 bad format is usage error (exit 2)", rc == 2)
    rc = main([os.path.join(tmp, "missing.json")])
    check("c4 unreadable manifest (exit 2)", rc == 2)
    arr = os.path.join(tmp, "arr.json")
    with open(arr, "w", encoding="utf-8") as fh:
        json.dump(["not", "an", "object"], fh)
    check("c5 non-object JSON root is a usage error (exit 2)", main([arr]) == 2)

    all_pass = all(results)
    print("\n%s: %d/%d cases passed"
          % ("ALL PASS" if all_pass else "SELFTEST FAILED",
             sum(1 for r in results if r), len(results)))
    return 0 if all_pass else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
