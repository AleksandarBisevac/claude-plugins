#!/usr/bin/env python3
"""
Render the audit manifest as a self-contained HTML + Markdown report.

Publishable as a CI artifact (see docs/examples/azure-pipelines.yml) or opened
locally — the HTML inlines all CSS and fetches NOTHING. Every string from the
manifest is escaped (manifest content is untrusted input), and ado/link URLs
render as links only when they are http(s).

Usage:
  render-report.py <manifest> [--out-dir DIR] [--format html|md|both]
                              [--summary-file PATH] [--basename NAME]
  render-report.py --selftest

Writes <basename>.html / <basename>.md into --out-dir (default: the manifest's
own directory) and prints the paths. `basename` is `--basename` › the manifest's
`meta.reportBasename` › `audit-report`, sanitized to [A-Za-z0-9-_].
Exit codes: 0 ok · 2 usage error / unreadable manifest.
"""
import base64
import html
import importlib.util
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _HERE)
import _manifest_io as _mio  # noqa: E402  (dual-format loader; single-file OR index+shards)

# Chip and pipeline-rail colors live in the report's CSS theme tokens (see _CSS),
# keyed off the `data-status` / `data-risk` attributes the markup carries — so a
# single token set themes every status/risk consistently in both light and dark.
# Risk chips render only for these levels:
_RISK_LEVELS = ("low", "med", "high")

_CSS = """
/* ---- design tokens (Slate & Teal) ---------------------------------------- */
:root{
  color-scheme:light dark;
  --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,system-ui,sans-serif;
  --mono:ui-monospace,'SF Mono','JetBrains Mono',Menlo,Consolas,monospace;
  --bg:#f5f7fb;--surface:#ffffff;--surface-2:#eef2f7;--text:#0f172a;--muted:#64748b;
  --border:#e2e8f0;--border-strong:#cbd5e1;
  --accent:#0d9488;--accent-solid:#0d9488;--ring:rgba(13,148,136,.35);
  --st-done:#15803d;--st-prog:#f59e0b;--st-blocked:#dc2626;--st-pending:#64748b;
  --chip-ink:#ffffff;
  --rk-low-bg:#dcfce7;--rk-low-fg:#166534;--rk-med-bg:#fef9c3;--rk-med-fg:#854d0e;
  --rk-high-bg:#fee2e2;--rk-high-fg:#b91c1c;
  /* Usage viz. Categorical slots carry MODEL identity (assigned by name, never by
     rank, so a filter can't repaint the survivors). Palette validated for CVD and
     contrast against this report's own surfaces with the dataviz validator:
     light worst-adjacent CVD dE 9.1 / normal-vision 19.6 - dark 8.4 / 19.3. Three
     light slots sit under 3:1, which the per-phase token/cost table relieves. */
  --viz-1:#2a78d6;--viz-2:#eb6834;--viz-3:#1baf7a;--viz-4:#eda100;
  --viz-5:#e87ba4;--viz-6:#008300;--viz-7:#4a3aa7;--viz-8:#e34948;
  /* Sequential single-hue ramp for the day x hour heatmap: light -> dark, zero
     recedes into the surface. Never a rainbow. */
  --hm-0:#eef2f7;--hm-1:#cde2fb;--hm-2:#9ec5f4;--hm-3:#6da7ec;
  --hm-4:#3987e5;--hm-5:#256abf;--hm-6:#0d366b;--hm-ink:#ffffff;
  --radius:9px;--radius-lg:14px;--pill:999px;
  --shadow-sm:0 1px 2px rgba(15,23,42,.05),0 2px 8px rgba(15,23,42,.06);
  --shadow-md:0 10px 30px rgba(15,23,42,.14);
  --dur:.22s;--ease:cubic-bezier(.4,0,.2,1)
}
/* dark tokens: OS default (JS off) + explicit toggle. --theme=light pins light. */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
  --border:#1f2b40;--border-strong:#33425c;
  --accent:#2dd4bf;--accent-solid:#0f766e;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;--chip-ink:#07130f;
  --rk-low-bg:rgba(52,211,153,.16);--rk-low-fg:#6ee7b7;--rk-med-bg:rgba(251,191,36,.16);
  --rk-med-fg:#fcd34d;--rk-high-bg:rgba(248,113,113,.16);--rk-high-fg:#fca5a5;
  --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
  --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
  /* Dark heatmap steps are SELECTED for the dark surface, not an inverted copy:
     zero still recedes into the surface, so the ramp runs dark -> light. */
  --hm-0:#172236;--hm-1:#104281;--hm-2:#184f95;--hm-3:#1c5cab;
  --hm-4:#2a78d6;--hm-5:#5598e7;--hm-6:#9ec5f4;--hm-ink:#07130f;
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)
}}
:root[data-theme="dark"]{
  --bg:#0a1120;--surface:#111a2b;--surface-2:#172236;--text:#e6edf6;--muted:#93a4bd;
  --border:#1f2b40;--border-strong:#33425c;
  --accent:#2dd4bf;--accent-solid:#0f766e;--ring:rgba(45,212,191,.4);
  --st-done:#34d399;--st-prog:#fbbf24;--st-blocked:#f87171;--st-pending:#94a3b8;--chip-ink:#07130f;
  --rk-low-bg:rgba(52,211,153,.16);--rk-low-fg:#6ee7b7;--rk-med-bg:rgba(251,191,36,.16);
  --rk-med-fg:#fcd34d;--rk-high-bg:rgba(248,113,113,.16);--rk-high-fg:#fca5a5;
  --viz-1:#3987e5;--viz-2:#d95926;--viz-3:#199e70;--viz-4:#c98500;
  --viz-5:#d55181;--viz-6:#008300;--viz-7:#9085e9;--viz-8:#e66767;
  /* Dark heatmap steps are SELECTED for the dark surface, not an inverted copy:
     zero still recedes into the surface, so the ramp runs dark -> light. */
  --hm-0:#172236;--hm-1:#104281;--hm-2:#184f95;--hm-3:#1c5cab;
  --hm-4:#2a78d6;--hm-5:#5598e7;--hm-6:#9ec5f4;--hm-ink:#07130f;
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);--shadow-md:0 12px 34px rgba(0,0,0,.5)
}
/* one status token drives both the pipeline rail and the status chip */
[data-status="done"],[data-status="fixed"]{--st:var(--st-done)}
[data-status="in_progress"],[data-status="triaged"]{--st:var(--st-prog)}
[data-status="blocked"],[data-status="open"]{--st:var(--st-blocked)}
[data-status="pending"],[data-status="wontfix"]{--st:var(--st-pending)}
/* amber status chips read best with dark ink (both themes) */
[data-status="in_progress"] .chip,[data-status="triaged"] .chip,
.chip[data-status="in_progress"],.chip[data-status="triaged"]{--chip-ink:#78350f}
.area-tag{display:inline-block;font-size:.62rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  padding:.05rem .4em;border-radius:.5em;background:var(--surface-2);color:var(--muted);vertical-align:middle}

/* ---- base ---------------------------------------------------------------- */
*{box-sizing:border-box}
html{background:var(--bg)}
body{font:15px/1.6 var(--sans);color:var(--text);background:var(--bg);max-width:70rem;
     margin:0 auto;padding:2rem 1.3rem 4rem;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-underline-offset:2px}
h1{font-size:1.7rem;font-weight:680;letter-spacing:-.02em;margin:0 0 .15rem}
h2{font-size:.82rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
   margin:2.4rem 0 .7rem;padding-bottom:.4rem;border-bottom:1px solid var(--border)}
.meta{color:var(--muted);font-family:var(--mono);font-size:.8rem;margin:0 0 1.3rem;
      font-variant-numeric:tabular-nums}
.invalid{color:var(--st-blocked);font-weight:600}
.muted{color:var(--muted)}
.mono{font-family:var(--mono);font-size:.86em;font-variant-numeric:tabular-nums}

/* ---- hero / overall band ------------------------------------------------- */
.overall{display:flex;align-items:center;gap:.7rem 1.3rem;flex-wrap:wrap;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--radius-lg);padding:1rem 1.2rem;margin:1rem 0;
  box-shadow:var(--shadow-sm)}
.overall>strong{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:700}
.overall .muted{font-family:var(--mono);font-size:.82rem;font-variant-numeric:tabular-nums}

/* ---- summary card -------------------------------------------------------- */
.summary{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
  border-radius:var(--radius);padding:.8rem 1rem;margin:1rem 0;box-shadow:var(--shadow-sm)}
.summary>strong{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;
  color:var(--accent);font-weight:700;margin-bottom:.28rem}

/* ---- progress bar (animated fill) ---------------------------------------- */
.bar{position:relative;display:inline-block;vertical-align:middle;width:13rem;max-width:38vw;
  height:.62rem;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--pill);overflow:hidden}
.fill{height:100%;border-radius:inherit;background:var(--accent);box-shadow:0 0 10px -2px var(--accent);
  width:var(--w,0);animation:fillIn .9s var(--ease) both}
@keyframes fillIn{from{width:0}}

/* ---- toolbar ------------------------------------------------------------- */
.toolbar{position:sticky;top:.5rem;z-index:10;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;
  padding:.55rem .7rem;margin:1.4rem 0 1rem;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);transition:box-shadow var(--dur) var(--ease)}
.toolbar.scrolled{box-shadow:var(--shadow-md)}
#audit-q{flex:1 1 17rem;min-width:11rem;padding:.42rem .85rem;font:inherit;color:var(--text);
  background:var(--bg);border:1px solid var(--border);border-radius:var(--pill);
  transition:border-color var(--dur),box-shadow var(--dur)}
#audit-q::placeholder{color:var(--muted)}
#audit-q:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.tbl{font-size:.76rem;color:var(--muted);margin-left:.15rem}
#audit-phase-status{display:inline-flex;gap:.35rem;flex-wrap:wrap}

/* ---- buttons ------------------------------------------------------------- */
.btn{cursor:pointer;font:inherit;font-size:.82rem;line-height:1;display:inline-flex;align-items:center;
  gap:.4em;padding:.44rem .8rem;border-radius:var(--pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text);
  transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),background var(--dur),border-color var(--dur)}
.btn:hover{border-color:var(--border-strong);background:var(--surface-2);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.btn:active{transform:translateY(0);box-shadow:none}
.btn:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.btn-primary{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.btn-primary:hover{filter:brightness(1.08);background:var(--accent-solid);border-color:var(--accent-solid)}
.btn-icon{padding:.44rem .6rem;font-size:1rem}

/* ---- filter chips (toolbar phase-status + per-phase task-status) --------- */
.fchip,.tf-chip{cursor:pointer;font:inherit;font-size:.79rem;line-height:1;padding:.3rem .65rem;
  border-radius:var(--pill);border:1px solid var(--border);background:var(--surface);color:var(--text);
  transition:background var(--dur),border-color var(--dur),color var(--dur),transform var(--dur) var(--ease)}
.fchip:hover,.tf-chip:hover{border-color:var(--border-strong);transform:translateY(-1px)}
.fchip:focus-visible,.tf-chip:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.fchip.on,.tf-chip.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.tf-chip{font-size:.73rem;padding:.2rem .55rem}

/* ---- status + risk chips ------------------------------------------------- */
.chip{display:inline-block;padding:.06rem .6em;border-radius:var(--pill);font-size:.76rem;font-weight:600;
  letter-spacing:.01em;background:var(--st,var(--st-pending));color:var(--chip-ink)}
.rchip{display:inline-block;padding:.06rem .55em;border-radius:var(--pill);font-size:.73rem;font-weight:600;border:1px solid transparent}
.rchip[data-risk="low"]{background:var(--rk-low-bg);color:var(--rk-low-fg);border-color:var(--rk-low-fg)}
.rchip[data-risk="med"]{background:var(--rk-med-bg);color:var(--rk-med-fg);border-color:var(--rk-med-fg)}
.rchip[data-risk="high"]{background:var(--rk-high-bg);color:var(--rk-high-fg);border-color:var(--rk-high-fg)}

/* ---- tables -------------------------------------------------------------- */
.tablewrap{margin:.5rem 0 1rem}
table.phases,table.data{border-collapse:separate;border-spacing:0;width:100%;font-size:.92rem;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  box-shadow:var(--shadow-sm);margin:0}
thead th{position:sticky;top:3.5rem;z-index:2;background:var(--surface-2);color:var(--muted);font-weight:700;
  font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap;text-align:left;
  padding:.55rem .7rem;border-bottom:1px solid var(--border);cursor:pointer;user-select:none}
thead th:first-child{border-top-left-radius:var(--radius-lg)}
thead th:last-child{border-top-right-radius:var(--radius-lg)}
th.sorted::after{content:"\\25B2";font-size:.75em;margin-left:.35em;color:var(--accent)}
th.sorted[data-sort="desc"]::after{content:"\\25BC"}
td{padding:.5rem .7rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
td.when,td.mono{font-variant-numeric:tabular-nums}
td.muted{font-size:.86em}
tbody tr:last-child td{border-bottom:none}
tbody tr:last-child td:first-child{border-bottom-left-radius:var(--radius-lg)}
tbody tr:last-child td:last-child{border-bottom-right-radius:var(--radius-lg)}

/* ---- phase group-rows: the pipeline rail + status node (signature) ------- */
tr.phase{cursor:pointer}
tr.phase>td{position:relative;background:var(--surface-2);border-top:1px solid var(--border-strong);
  border-left:2px solid var(--st,var(--st-pending));padding:.7rem .75rem .7rem 1.1rem;transition:background var(--dur)}
tr.phase:hover>td{background:var(--surface)}
tr.phase>td::before{content:"";position:absolute;left:-6px;top:1.05rem;width:11px;height:11px;border-radius:50%;
  background:var(--st,var(--st-pending));box-shadow:0 0 0 3px var(--surface)}
.tri{display:inline-block;width:1em;color:var(--muted);transition:transform var(--dur) var(--ease)}
.tri::before{content:"\\25B6";font-size:.72em}
tr.phase.open .tri{transform:rotate(90deg)}
tr.phase strong{font-weight:650}
.pmeta{font-size:.82rem;color:var(--muted);margin-top:.28rem}

/* ---- task rows continue the rail ----------------------------------------- */
tr.task>td{background:var(--surface)}
tr.task:hover>td{background:var(--surface-2)}
tr.task>td.tid{padding-left:1.9rem;border-left:2px solid var(--st,var(--border))}

/* ---- per-phase task-status filter row ------------------------------------ */
tr.taskfilter{display:none}
tr.taskfilter>td{background:var(--surface);padding:.42rem .7rem .42rem 1.9rem;border-bottom:1px dashed var(--border)}
.tf-label{font-size:.75rem;color:var(--muted);margin-right:.5rem}
.tf-chips{display:inline-flex;gap:.35rem;flex-wrap:wrap}

/* ---- load reveal (ends visible -> readable with JS off) ------------------ */
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}}
h1,.meta,.overall,.summary{animation:fadeUp .5s var(--ease) both}
.meta{animation-delay:.04s}.overall{animation-delay:.09s}.summary{animation-delay:.14s}

/* ---- colored bits must print --------------------------------------------- */
.chip,.fill,.rchip,tr.phase>td::before{-webkit-print-color-adjust:exact;print-color-adjust:exact}

/* ---- responsive: tablet / mobile ----------------------------------------- */
/* Wide tables (9 / 7 cols) scroll INSIDE their own frame instead of pushing the
   whole page sideways. The scroll container breaks viewport-sticky headers, so
   sticky is disabled only at these widths (desktop keeps it). */
@media (max-width:52rem){
  .tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);
    border-radius:var(--radius-lg);box-shadow:var(--shadow-sm)}
  table.phases,table.data{border:none;border-radius:0;box-shadow:none;min-width:34rem}
  thead th{position:static}
  thead th:first-child,thead th:last-child,
  tbody tr:last-child td:first-child,tbody tr:last-child td:last-child{border-radius:0}
}
@media (max-width:40rem){
  body{padding:1.4rem .85rem 3rem;font-size:14.5px}
  h1{font-size:1.4rem}
  .overall,.summary{padding:.8rem .9rem}
  .toolbar{gap:.4rem .5rem}
  #audit-q{flex-basis:100%;order:-1}
  .bar{max-width:52vw}
}

/* ---- reduced motion ------------------------------------------------------ */
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;animation-delay:0!important;transition-duration:.001ms!important}
  .fill{animation:none;width:var(--w,0)}
}

/* ---- print: force a light sheet + keep the interactive semantics --------- */
@page{size:A4;margin:1.4cm}
@media print{
  :root,:root[data-theme="dark"]{--bg:#fff;--surface:#fff;--surface-2:#f3f4f6;--text:#111827;
    --muted:#374151;--border:#d1d5db;--chip-ink:#fff}
  body{max-width:none;margin:0;padding:0;font-size:10.5pt}
  .toolbar,tr.taskfilter{display:none!important}
  tr.task{display:table-row!important}
  tr.phase,tr.task{break-inside:avoid}
  thead th{position:static!important}
  table.phases,table.data{box-shadow:none}
  a[href]{color:inherit;text-decoration:none}
  .tiles,.uphase,.hm,.cols{break-inside:avoid}
  .seg,.hm i,.cols rect{print-color-adjust:exact;-webkit-print-color-adjust:exact}
}

/* ---- usage section ---------------------------------------------------------
   Every mark here is hand-rolled CSS/SVG: the report ships as one self-contained
   file with zero network fetches (selftest x5 pins that), so a chart library is
   not an option. Marks follow the house spec - thin, 4px rounded data-end square
   at the baseline, 2px surface gaps doing the separating, hairline recessive
   grid, and text in text tokens rather than the series color. */
.tiles{display:flex;flex-wrap:wrap;gap:.7rem;margin:.9rem 0 1.3rem}
.tile{flex:1 1 8.5rem;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:.7rem .9rem;box-shadow:var(--shadow-sm)}
.tile .k{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted)}
/* Proportional figures on purpose: tabular-nums makes a big standalone value
   look loose. Columns of numbers below keep tabular alignment. */
.tile .v{font-size:1.55rem;font-weight:680;letter-spacing:-.02em;line-height:1.15;
  margin-top:.15rem}
.tile .s{font-size:.72rem;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:.45rem 1rem;margin:.2rem 0 .9rem;
  font-size:.78rem;color:var(--muted)}
.legend b{display:inline-flex;align-items:center;gap:.35rem;font-weight:500;
  color:var(--text)}
.legend i{width:.62rem;height:.62rem;border-radius:3px;display:inline-block}
.uphase{display:grid;grid-template-columns:minmax(6rem,13rem) 1fr auto;
  gap:.5rem .8rem;align-items:center;margin:.34rem 0}
.uphase .nm{font-size:.83rem;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.uphase .amt{font-size:.78rem;color:var(--muted);
  font-variant-numeric:tabular-nums;white-space:nowrap}
/* Stacked bar: the 2px flex gap IS the separator - no strokes around segments. */
.stack{display:flex;gap:2px;height:14px;align-items:stretch}
.seg{min-width:2px;border-radius:1px}
.seg:last-child{border-radius:1px 4px 4px 1px}
.cols{width:100%;height:120px;display:block;overflow:visible}
.cols .grid{stroke:var(--border);stroke-width:1;fill:none}
.cols .col{fill:var(--viz-1)}
.cols text{fill:var(--muted);font-size:9px;font-family:var(--sans)}
.hmwrap{overflow-x:auto}
.hm{border-collapse:separate;border-spacing:2px;font-size:.62rem;
  color:var(--muted)}
/* The report's global `thead th` is sticky for the long phases table; a 7-row
   heatmap must opt out or its hour ruler detaches and floats over the grid. */
.hm thead th{position:static;background:none;border:0;padding:0 .2rem}
.hm th{font-weight:500;color:var(--muted);padding:0 .2rem;text-align:right;
  white-space:nowrap}
.hm td{padding:0}
.hm i{display:block;width:20px;height:15px;border-radius:2px;
  background:var(--hm-0)}
.hm i[data-l="1"]{background:var(--hm-1)}.hm i[data-l="2"]{background:var(--hm-2)}
.hm i[data-l="3"]{background:var(--hm-3)}.hm i[data-l="4"]{background:var(--hm-4)}
.hm i[data-l="5"]{background:var(--hm-5)}.hm i[data-l="6"]{background:var(--hm-6)}
.hmkey{display:flex;align-items:center;gap:.3rem;font-size:.7rem;
  color:var(--muted);margin-top:.4rem}
.hmkey i{width:20px;height:15px;border-radius:2px;display:inline-block}
.stale{color:var(--st-blocked)}
@media (max-width:40rem){
  .uphase{grid-template-columns:1fr;gap:.15rem}
  .uphase .amt{text-align:left}
}
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

  // Theme: follow the OS by default; the toolbar toggle overrides + persists.
  var root = document.documentElement;
  var themeBtn = document.getElementById('audit-theme');
  var THEME_KEY = 'audit-report-theme';
  function prefersDark() { return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches; }
  function isDark() { var t = root.getAttribute('data-theme'); return t ? t === 'dark' : prefersDark(); }
  function paintTheme() { if (themeBtn) themeBtn.textContent = isDark() ? '☀' : '☾'; }
  try { var savedTheme = localStorage.getItem(THEME_KEY); if (savedTheme) root.setAttribute('data-theme', savedTheme); } catch (e) {}
  paintTheme();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var next = isDark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    paintTheme();
  });

  // Toolbar elevation once the page scrolls under it.
  var toolbar = document.querySelector('.toolbar');
  if (toolbar) {
    var onScroll = function () { toolbar.classList.toggle('scrolled', (window.scrollY || 0) > 8); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

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

  // Save as PDF — the print stylesheet lays the report out on A4 with every
  // phase expanded; the browser's print dialog offers "Save as PDF" (no bundled
  // PDF library, so the file stays small and self-contained).
  var printBtn = document.getElementById('audit-print');
  if (printBtn) printBtn.addEventListener('click', function () { window.print(); });

  // Download the Markdown twin (embedded as base64, decoded to a Blob).
  var dlBtn = document.getElementById('audit-dl-md');
  if (dlBtn) dlBtn.addEventListener('click', function () {
    try {
      var bin = atob(window.AUDIT_MD_B64 || '');
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var url = URL.createObjectURL(new Blob([bytes], { type: 'text/markdown;charset=utf-8' }));
      var a = document.createElement('a');
      a.href = url; a.download = (window.AUDIT_MD_NAME || 'audit-report.md');
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {}
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


def _chip(status):
    # Colored by the CSS theme token selected via data-status (see _CSS).
    return '<span class="chip" data-status="%s">%s</span>' % (e(status), e(status))


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


def _risk_chip(risk):
    """Tinted risk chip (low/med/high); em dash for null/unknown. Colored by the
    CSS theme token selected via data-risk (see _CSS)."""
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


def load_usage(manifest, manifest_path, project_dir=None):
    """Everything the Usage section plots, read straight from the ledger.

    Deliberately NOT taken from `audit-status.rollup`: the rollup is printed into a
    model's context by /audit:status, so the bulky series (day x hour heatmap,
    daily trend, phase x model cross-tab) are computed here in Python instead of
    being carried through a JSON payload nobody reads. Returns None when there is
    no ledger — the section then renders as nothing at all."""
    try:
        spec = importlib.util.spec_from_file_location(
            "usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
        ul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ul)
    except Exception:
        return None

    meta_usage = ((manifest or {}).get("meta") or {}).get("usage") or {}
    if not isinstance(meta_usage, dict):
        meta_usage = {}
    rel = meta_usage.get("ledgerDir") or os.path.join(".claude", "usage")
    if project_dir is None:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(manifest_path))))
    ledger_dir = rel if os.path.isabs(rel) else os.path.join(project_dir, rel)

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

        return {
            "totals": ul.totals(rows),
            "byPhase": slim("phase"),
            "byModel": slim("model"),
            "byAuthor": slim("author"),
            "byAgent": slim("agent"),
            "phaseModel": phase_model,
            "phaseTitles": titles,
            "daily": {k: v["tokens"] for k, v in ul.aggregate(rows, "day").items()
                      if k != "unknown"},
            "heatmap": ul.heatmap(rows),
            "showCost": bool(meta_usage.get("showCost", True)),
            "pricingAsOf": meta_usage.get("pricingAsOf"),
        }
    except Exception:
        return None


VIZ_SLOTS = 8


def _fmt_tokens(n):
    n = int(n or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return "%.1f%s" % (n / float(limit), suffix)
    return str(n)


def _fmt_cost(x):
    x = float(x or 0.0)
    if x and abs(x) < 0.01:
        return "<$0.01"
    return "$%.2f" % x


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


def _usage_tiles(u):
    t = u["totals"]
    tiles = [("total tokens", _fmt_tokens(t["tokens"]),
              "%s msgs across %d session(s)" % ("{:,}".format(t["msgs"]),
                                                t["sessions"]))]
    if u.get("showCost", True):
        asof = u.get("pricingAsOf")
        tiles.append(("equivalent cost", _fmt_cost(t["costUSD"]),
                      "at %s rates" % e(asof) if asof else "no per-token bill on a subscription"))
    tiles.append(("cache hit", "%.0f%%" % t["cacheHitPct"],
                  "%s read vs %s written" % (_fmt_tokens(t["cacheR"]),
                                             _fmt_tokens(t["cacheW5m"] + t["cacheW1h"]))))
    tiles.append(("output tokens", _fmt_tokens(t["out"]),
                  "%s in, uncached" % _fmt_tokens(t["in"])))
    if t["authors"] > 1:
        tiles.append(("authors", str(t["authors"]), "%d task(s) attributed" % t["tasks"]))
    return ('<div class="tiles">%s</div>' % "".join(
        '<div class="tile"><div class="k">%s</div><div class="v">%s</div>'
        '<div class="s">%s</div></div>' % (e(k), e(v), s if s.startswith("at ") else e(s))
        for k, v, s in tiles))


def _usage_section(u):
    """The Usage block: stat tiles, a per-phase stacked bar by model, a daily
    column chart and a day x hour heatmap. Returns '' when there is no ledger."""
    if not u or not u.get("totals", {}).get("tokens"):
        return ""
    out = ['<h2 id="usage">Usage</h2>']
    out.append(_usage_tiles(u))

    slots = _model_slots(u["byModel"].keys())
    # Draw order is SLOT order, not magnitude order. The palette's CVD separation is
    # only validated for ADJACENT slot pairs (1-2, 2-3, 3-4, ...); sorting segments
    # by size would put arbitrary pairs side by side — orange beside yellow, say,
    # which the palette notes as failing the separation floor. Slot order keeps the
    # rendered adjacency identical to the validated adjacency, and has the bonus
    # that a model holds its position across every bar.
    models = sorted(u["byModel"], key=lambda m: slots[m])
    # A legend is the dependable identity channel whenever more than one series is
    # on screen; with one model the heading already says what is plotted.
    if len(models) > 1:
        out.append('<div class="legend">%s</div>' % "".join(
            '<b><i style="background:var(--viz-%d)"></i>%s</b>' % (slots[m], e(m))
            for m in models))

    phases = sorted(u["phaseModel"].items(),
                    key=lambda kv: -sum(kv[1].values()))
    if phases:
        peak = max(sum(v.values()) for _, v in phases) or 1
        out.append('<h3 class="sub">Tokens by phase</h3>')
        for pid, per_model in phases:
            total = sum(per_model.values())
            label = u["phaseTitles"].get(pid) or (
                "unattributed" if pid == "--" else "")
            segs = []
            for m in models:
                n = per_model.get(m, 0)
                if not n:
                    continue
                segs.append(
                    '<i class="seg" style="flex:%d 0 0;background:var(--viz-%d)" '
                    'title="%s - %s - %s tokens"></i>'
                    % (n, slots[m], e(pid), e(m), "{:,}".format(n)))
            cost = (" &middot; %s" % e(_fmt_cost(u["byPhase"][pid]["costUSD"]))
                    if u.get("showCost", True) and pid in u["byPhase"] else "")
            out.append(
                '<div class="uphase"><span class="nm"><span class="mono">%s</span> %s</span>'
                '<span class="stack" style="width:%.1f%%" role="img" '
                'aria-label="%s: %s tokens">%s</span>'
                '<span class="amt">%s%s</span></div>'
                % (e(pid), e(label), 100.0 * total / peak, e(pid),
                   "{:,}".format(total), "".join(segs),
                   e(_fmt_tokens(total)), cost))

    out.append(_usage_trend(u))
    out.append(_usage_heatmap(u))
    return "".join(out)


def _usage_trend(u):
    """Daily column chart. Columns cap at 24px thick, 4px rounded cap, square at
    the baseline; one hairline gridline at the peak carries the scale."""
    daily = u.get("daily") or {}
    days = sorted(daily)
    if len(days) < 2:
        return ""
    w, h, pad_b, pad_t = 720.0, 120.0, 18.0, 10.0
    peak = max(daily[d] for d in days) or 1
    slot = w / len(days)
    bw = min(24.0, max(2.0, slot - 2.0))
    plot = h - pad_b - pad_t
    bars, labels = [], []
    every = max(1, len(days) // 12)
    for i, d in enumerate(days):
        n = daily[d]
        bh = max(1.0, plot * n / peak)
        x = i * slot + (slot - bw) / 2.0
        y = pad_t + plot - bh
        r = min(4.0, bw / 2.0, bh)
        bars.append(
            '<path class="col" d="M%.1f %.1fL%.1f %.1fQ%.1f %.1f %.1f %.1f'
            'L%.1f %.1fQ%.1f %.1f %.1f %.1fL%.1f %.1fZ">'
            '<title>%s - %s tokens</title></path>'
            % (x, y + bh, x, y + r, x, y, x + r, y,
               x + bw - r, y, x + bw, y, x + bw, y + r, x + bw, y + bh,
               e(d), "{:,}".format(n)))
        if i % every == 0 or i == len(days) - 1:
            labels.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                          % (x + bw / 2.0, h - 5, e(d[5:])))
    return ('<h3 class="sub">Daily tokens</h3>'
            '<svg class="cols" viewBox="0 0 %d %d" preserveAspectRatio="none" '
            'role="img" aria-label="Daily token usage, peak %s tokens">'
            '<line class="grid" x1="0" y1="%.1f" x2="%d" y2="%.1f"></line>'
            '%s%s</svg>'
            '<p class="muted" style="font-size:.75rem;margin:.1rem 0 0">'
            'peak %s tokens on %s</p>'
            % (int(w), int(h), "{:,}".format(peak), pad_t, int(w), pad_t,
               "".join(bars), "".join(labels), e(_fmt_tokens(peak)),
               e(max(days, key=lambda d: daily[d]))))


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
                         "</i></td>" % (level, _WDAY[d], hh, "{:,}".format(n)))
        rows.append("<tr><th>%s</th>%s</tr>" % (_WDAY[d], "".join(cells)))
    ticks = "".join('<th>%s</th>' % (str(h).zfill(2) if h % 6 == 0 else "")
                    for h in range(24))
    key = "".join('<i style="background:var(--hm-%d)"></i>' % i for i in range(7))
    return ('<h3 class="sub">When the tokens are spent (UTC)</h3>'
            '<div class="hmwrap"><table class="hm"><thead><tr><th></th>%s</tr>'
            "</thead><tbody>%s</tbody></table></div>"
            '<p class="hmkey">0 %s %s tokens/hour</p>'
            % (ticks, "".join(rows), key, e(_fmt_tokens(peak))))


def render_html(manifest, summary, basename="audit-report", usage=None):
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
    out.append('<p class="meta">repo: %s · generated %s · %d phases · %d tasks'
               " · %d bugs</p>"
               % (e(meta.get("repo") or "?"), now, len(summary["phases"]),
                  summary["tasks"]["total"], summary["bugs"]["total"]))
    if not summary["valid"]:
        out.append('<p><strong class="invalid">INVALID MANIFEST: %d '
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

    # AI-authored narrative summary (written by /audit:report into
    # meta.reportSummary); the quantitative "Overall" line above is the
    # always-present deterministic fallback. Escaped — treated as untrusted.
    rsum = meta.get("reportSummary")
    if isinstance(rsum, str) and rsum.strip():
        out.append('<div class="summary"><strong>Summary</strong>%s</div>'
                   % e(rsum.strip()))

    # Interactive toolbar (search + per-status quick-filter). Enhanced by
    # _SCRIPT; with JS off the tables below are still fully readable.
    out.append(
        '<div class="toolbar" role="search">'
        '<input id="audit-q" type="search" aria-label="Filter phases and tasks by text" '
        'placeholder="Filter phases &amp; tasks by text…">'
        '<span class="tbl">Phase status:</span><span id="audit-phase-status"></span>'
        '<button type="button" id="audit-expand" class="btn">expand all</button>'
        '<button type="button" id="audit-print" class="btn btn-primary" '
        'title="Print / Save as PDF — all phases expanded, A4">Save as PDF</button>'
        '<button type="button" id="audit-dl-md" class="btn">Download .md</button>'
        '<button type="button" id="audit-theme" class="btn btn-icon" '
        'aria-label="Toggle light/dark theme" title="Toggle light/dark theme">☾</button>'
        '<span id="audit-count" class="muted"></span></div>')

    # One collapsible table: each phase is a group-row (click to expand its task
    # rows). Default-collapsed via _SCRIPT; with JS off every row is visible.
    out.append('<div class="tablewrap"><table class="phases"><thead><tr>'
               "<th>id</th><th>title</th><th>status</th><th>model</th>"
               "<th>risk</th><th>commit</th><th>done</th><th>ADO</th>"
               "<th>outcome</th></tr></thead><tbody>")
    for ph, psum in zip(
            [p for p in (manifest.get("phases") or []) if isinstance(p, dict)],
            summary["phases"]):
        pid = psum["id"]
        areas = psum["area"] if isinstance(psum.get("area"), list) else _areas_of(ph.get("area"))
        area_tags = "".join(' <span class="area-tag">%s</span>' % e(a) for a in areas)
        out.append(
            '<tr class="phase" data-phase="%s" data-status="%s" data-area="%s" tabindex="0" '
            'aria-expanded="false"><td colspan="9"><span class="tri"></span> '
            '<span class="mono">%s</span> <strong>%s</strong>%s %s %s%s</td></tr>'
            % (e(pid), e(psum["status"]), e(" ".join(areas)), e(pid), e(psum["title"]),
               area_tags, _chip(psum["status"]), _bar(psum["done"], psum["total"]),
               _phase_meta_div(ph)))
        # per-phase task-status filter (shown only when the phase is expanded);
        # _SCRIPT fills .tf-chips from this phase's own task statuses.
        out.append('<tr class="taskfilter" data-phase="%s"><td colspan="9">'
                   '<span class="tf-label">Filter tasks by status:</span>'
                   '<span class="tf-chips"></span></td></tr>' % e(pid))
        for t in ph.get("tasks") or []:
            if not isinstance(t, dict):
                continue
            out.append(
                '<tr class="task" data-phase="%s" data-status="%s">'
                '<td class="mono tid">%s</td><td>%s</td><td>%s</td>'
                "<td>%s</td><td>%s</td><td class=mono>%s</td><td class=when>%s</td>"
                "<td>%s</td><td class=muted>%s</td></tr>"
                % (e(pid), e(t.get("status")), e(t.get("id")), e(t.get("title")),
                   _chip(t.get("status")), e(t.get("model") or "—"),
                   _risk_chip(t.get("risk")), e((t.get("commit") or "—")[:9]),
                   _timing_cell(t), _ado_cell(t), e(_outcome_text(t))))
    out.append("</tbody></table></div>")

    out.append(_usage_section(usage))

    bugs = [b for b in (manifest.get("bugs") or []) if isinstance(b, dict)]
    if bugs:
        task_by_id = _tasks_by_id(manifest)
        out.append("<h2>Bugs</h2>")
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
        out.append("<h2>Ready now</h2><p class=mono>%s</p>"
                   % ", ".join(e(r) for r in summary["ready"]))
    # Embed the Markdown twin as base64 so the "Download .md" button works from a
    # standalone file. base64 (not raw text) keeps any manifest HTML/`</script>`
    # out of the page and preserves UTF-8 exactly.
    md_b64 = base64.b64encode(
        render_md(manifest, summary, usage).encode("utf-8")).decode("ascii")
    # basename is sanitized to [A-Za-z0-9-_], so it is safe in a JS string literal.
    out.append('<script>window.AUDIT_MD_B64="%s";window.AUDIT_MD_NAME="%s.md";</script>'
               % (md_b64, basename))
    out.append(_SCRIPT)
    return "\n".join(out) + "\n"


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
    if u.get("pricingAsOf"):
        head += " · rates as of %s" % u["pricingAsOf"]
    lines += [head, ""]

    def block(title, data, key_label):
        if not data:
            return []
        cols = "| %s | tokens | %smsgs |" % (key_label, "cost | " if show_cost else "")
        sep = "|---|---:|%s---:|" % ("---:|" if show_cost else "")
        rows = []
        for k, v in sorted(data.items(), key=lambda kv: -kv[1]["tokens"]):
            cells = [k, "{:,}".format(v["tokens"])]
            if show_cost:
                cells.append(_fmt_cost(v["costUSD"]))
            cells.append("{:,}".format(v["msgs"]))
            rows.append("| %s |" % " | ".join(_md(c) for c in cells))
        return ["### %s" % title, "", cols, sep] + rows + [""]

    lines += block("By phase", u["byPhase"], "phase")
    lines += block("By model", u["byModel"], "model")
    if len(u.get("byAuthor") or {}) > 1:
        lines += block("By author", u["byAuthor"], "author")
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
    if fmt not in ("html", "md", "both") or len(args) != 1:
        sys.stderr.write("usage: render-report.py <manifest> [--out-dir DIR] "
                         "[--format html|md|both] [--summary-file PATH] "
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
                  "startedAt": "2026-07-09T08:00:00Z",
                  "completedAt": "2026-07-09T09:30:00Z",
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
    check("u4 pricingAsOf surfaced so a stale rate is visible",
          "2026-08-06" in uh)
    check("u5 legend present for two models",
          'class="legend"' in uh and "claude-opus-5" in uh)
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
    check("h9 PDF (print) + Download .md buttons + embedded md + A4 print CSS",
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
    check("h13 responsive: wide tables wrapped + mobile breakpoint",
          html_out.count('<div class="tablewrap">') == 2
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
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
