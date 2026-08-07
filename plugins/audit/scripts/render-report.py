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
import html
import importlib.util
import json
import os
import re
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
  /* Magnitude-only bars (phase, author, task). Deliberately NOT --accent and
     deliberately low-chroma: it must not read as a series colour. Validated
     against all 8 viz slots on this surface - worst normal-vision dE 16.4,
     worst CVD dE 7.5, which the 6-8 band permits because every bar wearing it
     carries a direct text label. */
  --bar-neutral:#5c636d;
  /* The gate rail. The line is STRUCTURE and carries no state — it is one colour
     the whole way down, so the only thing that changes along it is the gates. It
     dims below a gate that is closed, because nothing behind that gate can be
     worked on. Before this the left border repeated each row's status colour,
     which made the spine a second copy of the chip beside it rather than a
     drawing of what holds what. */
  --rail:#9aa8bd;--rail-held:#dfe5ee;
  --radius:9px;--radius-lg:14px;--pill:999px;
  --shadow-sm:0 1px 2px rgba(15,23,42,.05),0 2px 8px rgba(15,23,42,.06);
  --shadow-md:0 10px 30px rgba(15,23,42,.14);
  --dur:.22s;--ease:cubic-bezier(.4,0,.2,1);
  /* 8pt spacing scale + 3 text levels. Introduced so spacing stops being
     ad-hoc: every margin/padding/gap below snaps to one of these steps, which is
     what makes the vertical rhythm read as deliberate rather than accidental.
     Spacing and type are theme-independent, so unlike the colour tokens these are
     declared ONCE and are not repeated in the dark blocks. */
  --sp-0:.25rem;--sp-1:.5rem;--sp-2:.75rem;--sp-3:1rem;
  --sp-4:1.5rem;--sp-5:2rem;--sp-6:3rem;--sp-7:4rem;
  --t-1:1.7rem;--t-2:1.0625rem;--t-3:.875rem;--t-label:.68rem;
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
  --bar-neutral:#a6adb8;
  --rail:#4a5c7d;--rail-held:#1b2740;
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
  --bar-neutral:#a6adb8;
  --rail:#4a5c7d;--rail-held:#1b2740;
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
  padding:.25rem .4em;border-radius:.5em;background:var(--surface-2);color:var(--muted);vertical-align:middle}

/* ---- base ---------------------------------------------------------------- */
*{box-sizing:border-box}
html{background:var(--bg)}
body{font:15px/1.6 var(--sans);color:var(--text);background:var(--bg);
     margin:0;padding:0;-webkit-font-smoothing:antialiased}

/* ---- app shell -----------------------------------------------------------
   A 70rem centred column wasted half a laptop screen and gave a long document no
   map: this report runs verdict -> phases -> bugs -> ready -> usage, and usage
   alone has a chart, tiles, ranked lists, a budget block and a heatmap. So:
   navigation at the side, actions on top — the split follows what the controls
   DO, not where they fit.

   The side nav is not a menu of five links, which a top bar would carry perfectly
   well. It is a position indicator for a document you scroll for a long time, and
   that is a different job: it says where you are, not only where you can go.

   One information architecture, two presentations (the app-shell rule): above
   72rem it is a sticky column; below, the same items become a horizontal strip
   under the top bar. Never two different menus. */
.topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:.75rem 1rem;
  flex-wrap:wrap;padding:.6rem 1.5rem;background:color-mix(in srgb,var(--surface) 88%,transparent);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.topbar.scrolled{box-shadow:var(--shadow-sm)}
/* The title identifies the report and must survive being shared, so it stays in
   the bar — but capped and elided. Uncapped it pushed the actions onto a third
   row at 1440px, which is the opposite of what a persistent action bar is for. */
.tb-id{display:flex;flex-direction:column;min-width:0;margin-right:auto;
  max-width:min(40%,32rem)}
.tb-id h1,.tb-id .meta{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0}
.tb-id .meta{font-size:.72rem}
.tb-actions{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;justify-content:flex-end}
.shell{display:grid;grid-template-columns:14.5rem minmax(0,1fr);gap:2.5rem;
  max-width:96rem;margin:0 auto;padding:1.25rem 1.5rem 4rem;align-items:start}
.content{min-width:0}
/* Prose keeps a measure even when the shell is wide. A 1400px-wide sentence is
   not "using the space", it is unreadable. Tables and charts take the full
   column; text does not. */
.pmeta{max-width:82ch}
/* How the cards compose as the screen grows. Below 78rem they stack, because two
   400px columns of prose is worse than one. Above it they pair, which is the only
   honest use of the extra width: a summary paragraph set 1100px wide is not
   "filling the space", it is 130 characters per line and unreadable. The verdict
   takes the larger share — it is the answer, the summary is the elaboration.
   A lone card spans the full width rather than sitting in half of it. */
.topgrid{display:grid;gap:1rem;grid-template-columns:minmax(0,1fr);margin:1rem 0}
.topgrid>*{margin:0}
.topgrid>:only-child{grid-column:1/-1}
@media (min-width:78rem){.topgrid{grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);
  align-items:start}}
.snav{position:sticky;top:4.1rem;max-height:calc(100vh - 5.5rem);overflow:auto;
  padding-right:.25rem}
.snav ol{list-style:none;margin:0;padding:0}
.snav a{display:flex;align-items:center;gap:.5rem;text-decoration:none;color:var(--muted);
  font-size:.85rem;padding:.34rem .6rem;border-radius:var(--radius);
  border-left:2px solid transparent;transition:color var(--dur),background var(--dur)}
.snav a:hover{color:var(--text);background:var(--surface-2)}
.snav a[aria-current="true"]{color:var(--text);background:var(--surface-2);
  border-left-color:var(--accent);font-weight:600}
.snav .sub-item a{padding-left:1.5rem;font-size:.8rem}
/* The count is the point of putting it here: "Bugs 5" tells you whether the
   section is worth the scroll before you take it. */
.snav .n{margin-left:auto;font-family:var(--mono);font-size:.72rem;color:var(--muted);
  font-variant-numeric:tabular-nums}
.snav-title{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.12em;
  color:var(--muted);font-weight:700;margin:0 0 .4rem .6rem}
@media (max-width:48rem){
  /* On a phone the title is the only thing identifying the report, and 40% of
     390px is not a title, it is three words and an ellipsis. It takes the row. */
  .tb-id{max-width:100%}
}
@media (max-width:72rem){
  .shell{grid-template-columns:minmax(0,1fr);gap:1rem;padding-top:.5rem}
  /* Same items, different presentation — a horizontal strip, not a second menu. */
  .snav{position:sticky;top:3.4rem;max-height:none;overflow-x:auto;overflow-y:hidden;
    margin:0 -1.5rem;padding:.4rem 1.5rem;background:var(--bg);
    border-bottom:1px solid var(--border);z-index:20}
  .snav-title{display:none}
  .snav ol{display:flex;gap:.25rem;white-space:nowrap}
  .snav a{border-left:none;border-bottom:2px solid transparent;border-radius:var(--radius) var(--radius) 0 0}
  .snav a[aria-current="true"]{border-left-color:transparent;border-bottom-color:var(--accent)}
  .snav .sub-item{display:none}
}
a{color:var(--accent);text-underline-offset:2px}
/* The title names the document; it does not lead it. §7: the reader arrives with
   one question and it is not "what is this called". So the h1 is set at body-ish
   size and the verdict below it carries the display weight. */
h1{font-size:1.22rem;font-weight:680;letter-spacing:-.01em;margin:0 0 .2rem}
h2{font-size:.82rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
   margin:2rem 0 .75rem;padding-bottom:.5rem;border-bottom:1px solid var(--border)}
.meta{color:var(--muted);font-family:var(--mono);font-size:.8rem;margin:0 0 1.5rem;
      font-variant-numeric:tabular-nums}
.invalid{color:var(--st-blocked);font-weight:600}
.muted{color:var(--muted)}
.mono{font-family:var(--mono);font-size:.86em;font-variant-numeric:tabular-nums}

/* ---- verdict hero --------------------------------------------------------
   The page opens on the question the reader actually has: can this ship? The
   answer is not composed here — it is `audit-status.py --gate`, the same verdict
   the CI job produces, with the conditions that decided it printed underneath.
   A hero that scored the plan by its own private rule would be a second opinion
   nobody asked for; this one can be checked by running the gate. */
.overall{background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--vd);
  border-radius:var(--radius-lg);padding:1rem 1.25rem;margin:1rem 0;box-shadow:var(--shadow-sm);
  --vd:var(--st-pending)}
.overall[data-gate="clear"]{--vd:var(--st-done)}
.overall[data-gate="blocked"]{--vd:var(--st-blocked)}
.vd-eyebrow{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.14em;
  color:var(--muted);font-weight:700;margin:0}
/* Mono, uppercase, tight: the display voice of this report is the stamp on an
   inspection record, not a marketing headline. §7 asked for typography with a
   point of view and for mono to stop being spent on chrome — this is both. */
.vd-word{font-family:var(--mono);font-size:2.15rem;line-height:1.1;letter-spacing:-.01em;
  font-weight:700;color:var(--vd);margin:.1rem 0 .3rem;text-transform:uppercase}
.vd-why{margin:0;font-size:.95rem}
.vd-basis{margin:.35rem 0 0;color:var(--muted);font-size:.78rem}
.vd-next{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-top:.9rem;
  padding-top:.9rem;border-top:1px solid var(--border)}
.vd-run{font-family:var(--mono);font-size:.9rem;background:var(--surface-2);
  border:1px solid var(--border-strong);border-radius:var(--radius);padding:.2rem .45rem;
  font-variant-numeric:tabular-nums}
.vd-stats{display:flex;align-items:center;gap:.6rem 1.25rem;flex-wrap:wrap;margin-top:.8rem}
.vd-stats .muted{font-family:var(--mono);font-size:.82rem;font-variant-numeric:tabular-nums}

/* ---- summary card -------------------------------------------------------- */
.summary{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
  border-radius:var(--radius);padding:.75rem 1rem;margin:1rem 0;box-shadow:var(--shadow-sm)}
.summary>strong{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;
  color:var(--accent);font-weight:700;margin-bottom:.25rem}

/* ---- progress bar (animated fill) ---------------------------------------- */
.bar{position:relative;display:inline-block;vertical-align:middle;width:13rem;max-width:38vw;
  height:.62rem;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--pill);overflow:hidden}
/* `display:block` is load-bearing, not tidiness: the fill is a <span>, and an inline
   box ignores width and height outright. Without it every progress bar in the report
   rendered as an empty track — including a phase at 2/2 — which is why the committed
   README screenshots showed 4/10 against a blank bar. The two bars that always worked
   (`.rank .track i`, `.bud .track i`) both declare it; this one was the omission. */
.fill{display:block;height:100%;border-radius:inherit;background:var(--accent);
  box-shadow:0 0 10px -2px var(--accent);
  width:var(--w,0);animation:fillIn .9s var(--ease) both}
/* Both endpoints are explicit. A single `from` keyframe leaves the end state to be
   synthesised from the underlying value, and combined with `fill-mode:both` that is
   how `fadeUp` pinned two blocks at opacity 0 the moment its easing token started
   resolving. An animation that reveals something states what "revealed" means. */
@keyframes fillIn{from{width:0}to{width:var(--w,0)}}

/* ---- toolbar ------------------------------------------------------------- */
/* The toolbar moved into the top bar: these are global actions (search the whole
   plan, filter every phase, print, download, theme) and they were scrolling away
   from the reader halfway down a long report. */
.toolbar{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;margin:0}
/* Section-scoped controls sit on the thing they act on, sticky under the top bar
   so they stay reachable while you scroll the table they filter — and stop
   existing once you have scrolled past it. */
.sectools{position:sticky;top:3.6rem;z-index:15;padding:.5rem .75rem;margin:0 0 .75rem;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg)}
@media (max-width:72rem){.sectools{top:6.6rem}}
@media print{.sectools{display:none!important}}
#audit-q{flex:0 1 15rem;min-width:8rem;padding:.5rem .75rem;font:inherit;color:var(--text);
  background:var(--bg);border:1px solid var(--border);border-radius:var(--pill);
  transition:border-color var(--dur),box-shadow var(--dur)}
#audit-q::placeholder{color:var(--muted)}
#audit-q:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--ring)}
.tbl{font-size:.76rem;color:var(--muted);margin-left:.25rem}
#audit-phase-status{display:inline-flex;gap:.25rem;flex-wrap:wrap}

/* ---- buttons ------------------------------------------------------------- */
.btn{cursor:pointer;font:inherit;font-size:.82rem;line-height:1;display:inline-flex;align-items:center;
  gap:.4em;padding:.5rem .75rem;border-radius:var(--pill);border:1px solid var(--border);
  background:var(--surface);color:var(--text);
  transition:transform var(--dur) var(--ease),box-shadow var(--dur) var(--ease),background var(--dur),border-color var(--dur)}
.btn:hover{border-color:var(--border-strong);background:var(--surface-2);transform:translateY(-1px);box-shadow:var(--shadow-sm)}
.btn:active{transform:translateY(0);box-shadow:none}
.btn:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.btn-primary{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.btn-primary:hover{filter:brightness(1.08);background:var(--accent-solid);border-color:var(--accent-solid)}
.btn-icon{padding:.5rem .5rem;font-size:1rem}

/* ---- filter chips (toolbar phase-status + per-phase task-status) --------- */
.fchip,.tf-chip{cursor:pointer;font:inherit;font-size:.79rem;line-height:1;padding:.25rem .75rem;
  border-radius:var(--pill);border:1px solid var(--border);background:var(--surface);color:var(--text);
  transition:background var(--dur),border-color var(--dur),color var(--dur),transform var(--dur) var(--ease)}
.fchip:hover,.tf-chip:hover{border-color:var(--border-strong);transform:translateY(-1px)}
.fchip:focus-visible,.tf-chip:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
.fchip.on,.tf-chip.on{background:var(--accent-solid);border-color:var(--accent-solid);color:#fff}
.tf-chip{font-size:.73rem;padding:.25rem .5rem}

/* ---- status + risk chips ------------------------------------------------- */
.chip{display:inline-block;padding:.25rem .6em;border-radius:var(--pill);font-size:.76rem;font-weight:600;
  letter-spacing:.01em;background:var(--st,var(--st-pending));color:var(--chip-ink)}
.rchip{display:inline-block;padding:.25rem .55em;border-radius:var(--pill);font-size:.73rem;font-weight:600;border:1px solid transparent}
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
  padding:.5rem .75rem;border-bottom:1px solid var(--border)}
/* Only headers that actually sort look and behave like controls. `role="button"` is
   set by wireSort() on exactly the tables it wires, so the cursor and the focus ring
   cannot disagree with the behaviour — three tables (the two usage breakdowns and
   the heatmap) previously showed a pointer on headers that did nothing. */
thead th[role="button"]{cursor:pointer;user-select:none}
thead th[role="button"]:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
thead th:first-child{border-top-left-radius:var(--radius-lg)}
thead th:last-child{border-top-right-radius:var(--radius-lg)}
th.sorted::after{content:"\\25B2";font-size:.75em;margin-left:.35em;color:var(--accent)}
th.sorted[data-sort="desc"]::after{content:"\\25BC"}
td{padding:.5rem .75rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}
td.when,td.mono{font-variant-numeric:tabular-nums}
td.muted{font-size:.86em}
tbody tr:last-child td{border-bottom:none}
tbody tr:last-child td:first-child{border-bottom-left-radius:var(--radius-lg)}
tbody tr:last-child td:last-child{border-bottom-right-radius:var(--radius-lg)}

/* ---- the gate rail (signature) -------------------------------------------
   A continuous spine down the phase list, with one gate per phase. The CROSSBAR
   is the gate: broken in the middle when work can pass, solid when something
   holds it shut. Below a closed gate the rail dims, because that is exactly what
   `blockedBy` means and it was invisible in this report until now — the reader
   could see that P3 was pending but not that P2 was the reason.
   Colour is never the only carrier: every phase row also states its status in a
   text chip, and a held one names what holds it. */
tr.phase{cursor:pointer}
/* The spine is drawn on EVERY row in the body, not just phase rows, which is what
   makes it continuous: a rail that restarts at each group reads as a set of ticks,
   not as one line running the length of the plan. It sits INSIDE the table with
   clear space either side — sharing the card's left border made it read as the
   border it was sitting on rather than as a structure of its own. */
table.phases tbody>tr>td:first-child{position:relative;padding-left:2.3rem}
table.phases tbody>tr>td:first-child::after{content:"";position:absolute;left:1.15rem;top:0;bottom:0;
  width:2px;background:var(--rail)}
table.phases tbody>tr[data-held]>td:first-child::after{background:var(--rail-held)}
tr.phase>td{position:relative;background:var(--surface-2);border-top:1px solid var(--border-strong);
  padding:.75rem .75rem .75rem 2.3rem;transition:background var(--dur)}
tr.phase:hover>td{background:var(--surface)}
/* Open gate: a crossbar with a gap you can pass through. */
tr.phase>td::before{content:"";position:absolute;left:calc(1.15rem - 9px);top:1.2rem;width:20px;height:3px;
  border-radius:1px;z-index:1;
  background:linear-gradient(90deg,var(--st,var(--st-pending)) 0 7px,var(--surface-2) 7px 13px,
    var(--st,var(--st-pending)) 13px 20px)}
tr.phase:hover>td::before{background:linear-gradient(90deg,var(--st,var(--st-pending)) 0 7px,
  var(--surface) 7px 13px,var(--st,var(--st-pending)) 13px 20px)}
/* Closed gate: solid, no gap. Everything it holds is dimmed below it. */
tr.phase[data-held]>td::before,tr.phase[data-held]:hover>td::before{background:var(--st-blocked);width:22px;
  left:calc(1.15rem - 10px);height:3px}
/* The stamp: the last commit recorded inside a signed-off phase. */
.stamp{font-family:var(--mono);font-size:.7rem;letter-spacing:.02em;color:var(--muted);
  border:1px dashed var(--border-strong);border-radius:3px;padding:.05rem .3rem;margin-left:.4rem;
  vertical-align:.06em}
/* What holds this phase shut, named and linkable — the rail says "closed", this
   says by what. A gate that cannot tell you what shut it is a locked door with no
   sign on it. */
.heldby{font-family:var(--mono);font-size:.7rem;color:var(--st-blocked);border:1px solid currentColor;
  border-radius:3px;padding:.05rem .3rem;margin-left:.4rem;text-decoration:none;vertical-align:.06em}
.heldby:hover{background:var(--st-blocked);color:var(--chip-ink)}
.tri{display:inline-block;width:1em;color:var(--muted);transition:transform var(--dur) var(--ease)}
.tri::before{content:"\\25B6";font-size:.72em}
tr.phase.open .tri{transform:rotate(90deg)}
tr.phase strong{font-weight:650}
.pmeta{font-size:.82rem;color:var(--muted);margin-top:.25rem}

/* ---- task rows continue the rail ----------------------------------------- */
tr.task>td{background:var(--surface)}
tr.task:hover>td{background:var(--surface-2)}
tr.task>td.tid{padding-left:3.1rem}

/* ---- per-phase task-status filter row ------------------------------------ */
tr.taskfilter{display:none}
tr.taskfilter>td{background:var(--surface);padding:.5rem .75rem .5rem 3.1rem;border-bottom:1px dashed var(--border)}
.tf-label{font-size:.75rem;color:var(--muted);margin-right:.5rem}
.tf-chips{display:inline-flex;gap:.25rem;flex-wrap:wrap}

/* ---- load reveal (ends visible -> readable with JS off) ------------------ */
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
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
  /* Prose must not live at the table's scroll width. A phase's desiredOutcome is a
     sentence, and inside a 34rem-min table under overflow-x it was being laid out
     683px wide on a 390px screen — so reading one line meant scrolling sideways and
     back, per line. Sticky pins it to the visible left edge and the cap makes it
     wrap inside the viewport, so the prose reads straight down while the COLUMNS
     keep their scroll. Text wraps to the reader; data tables scroll. */
  .pmeta{position:sticky;left:0;max-width:calc(100vw - 5.5rem);white-space:normal}
  thead th{position:static}
  thead th:first-child,thead th:last-child,
  tbody tr:last-child td:first-child,tbody tr:last-child td:last-child{border-radius:0}
}
@media (max-width:40rem){
  body{padding:1.5rem .75rem 3rem;font-size:14.5px}
  h1{font-size:1.1rem}
  .vd-word{font-size:1.75rem}
  .overall,.summary{padding:.75rem 1rem}
  .toolbar{gap:.5rem .5rem}
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
  /* Paper has no scroll position to indicate and no controls to press, so the
     whole shell collapses back to the document it always was underneath. */
  .topbar,.snav,.toolbar,tr.taskfilter{display:none!important}
  .shell{display:block;max-width:none;padding:0}
  .pmeta{max-width:none}
  .topgrid{display:block}
  tr.task{display:table-row!important}
  tr.phase,tr.task{break-inside:avoid}
  thead th{position:static!important}
  table.phases,table.data{box-shadow:none}
  a[href]{color:inherit;text-decoration:none}
  .tiles,.uphase,.hm,.cols,.smcell,.rank{break-inside:avoid}
  /* a folded disclosure prints as a stub; force it open so the PDF is whole */
  details.more{display:block!important}
  details.more>summary{display:none!important}
  details.more>*{display:revert!important}
  .seg,.hm i,.cols rect{print-color-adjust:exact;-webkit-print-color-adjust:exact}
}

/* ---- usage section ---------------------------------------------------------
   Every mark is hand-rolled CSS/SVG: the report ships as one self-contained file
   with zero network fetches (selftest x5 pins that), so a chart library is not an
   option. Layout follows one rule — a metric strip, ONE dominant chart and three
   ranked lists on first paint, everything else behind a disclosure. */
.notice{border:1px solid var(--border);border-left:3px solid var(--st-prog);
  border-radius:var(--radius);padding:var(--sp-2) var(--sp-3);margin:var(--sp-2) 0;
  font-size:var(--t-3);background:var(--surface)}
.notice.warn{border-left-color:var(--st-blocked)}
/* Scale and span, ahead of the tiles. Counts, not metrics — five more cards would
   have said the same thing while diluting the five that can be acted on. */
.uctx{font-size:.75rem;color:var(--muted);margin:var(--sp-2) 0 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));
  gap:var(--sp-2);margin:var(--sp-2) 0 var(--sp-5)}
.tile{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:var(--sp-2) var(--sp-3);
  box-shadow:var(--shadow-sm)}
.tile .k{font-size:var(--t-label);text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted)}
/* Proportional figures on purpose: tabular-nums makes a big standalone value look
   loose. Columns of numbers below keep tabular alignment. */
.tile .v{font-size:1.55rem;font-weight:680;letter-spacing:-.02em;line-height:1.15;
  margin-top:var(--sp-0);display:flex;align-items:baseline;gap:var(--sp-1)}
.tile .s{font-size:.72rem;color:var(--muted);margin-top:var(--sp-0)}
.dl{font-size:.72rem;font-weight:600;padding:.05rem .3rem;border-radius:var(--pill);
  letter-spacing:0}
.dl.up{color:var(--st-done);background:color-mix(in srgb,var(--st-done) 14%,transparent)}
.dl.down{color:var(--muted);background:var(--surface-2)}
/* Cost band. Status colours are reserved and never travel alone, so the pill
   carries the word — the row's own status wears the same palette right beside it. */
.bandpill{display:inline-block;padding:.05rem .45rem;border-radius:var(--pill);
  font-size:.72rem;font-weight:600;white-space:nowrap}
.b-typical{color:var(--st-done);
  background:color-mix(in srgb,var(--st-done) 13%,transparent)}
.b-high{color:var(--st-prog);
  background:color-mix(in srgb,var(--st-prog) 16%,transparent)}
.b-outlier{color:var(--st-blocked);
  background:color-mix(in srgb,var(--st-blocked) 14%,transparent)}
h3.sub,h4.sub{font-size:var(--t-2);font-weight:640;letter-spacing:-.01em;
  margin:var(--sp-4) 0 var(--sp-1);border:0;text-transform:none;color:var(--text)}
.small{font-size:.75rem}
.fact{font-size:var(--t-3);margin:var(--sp-1) 0}
/* The one recommendation in the section — flagged so it reads as advice rather
   than as another measurement. */
.advice{margin:var(--sp-1) 0;padding-left:0;list-style:none;font-size:var(--t-3)}
.advice li{border-left:3px solid var(--st-prog);padding:var(--sp-1) var(--sp-2);
  background:var(--surface);border-radius:var(--radius);margin:var(--sp-1) 0}
/* The one dominant chart. The bars stretch to fill the width, which is the intent;
   the type does NOT live in that stretched space (see _usage_trend) — it is HTML
   positioned over the same percentages, so a digit is the same shape at 390px and
   at 1400px. */
.colswrap{position:relative;height:210px;margin-bottom:var(--sp-1)}
.cols{width:100%;height:210px;display:block;overflow:visible}
.cols .grid{stroke:var(--border);stroke-width:1;fill:none}
.cols .col{fill:var(--viz-1)}
.colswrap .yt,.colswrap .xt{position:absolute;font-size:.62rem;color:var(--muted);
  font-variant-numeric:tabular-nums;line-height:1;white-space:nowrap;
  pointer-events:none}
.colswrap .yt{left:0}
.xts{position:absolute;left:0;right:0;bottom:2px;height:.8rem}
.colswrap .xt{bottom:0;transform:translateX(-50%)}
@media (max-width:34rem){.colswrap .yt,.colswrap .xt{font-size:.55rem}}
/* three ranked lists, side by side on wide screens */
.ranks{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));
  gap:var(--sp-1) var(--sp-5);margin-top:var(--sp-2)}
.rank{display:grid;grid-template-columns:minmax(0,1fr) 6rem auto;
  align-items:center;gap:var(--sp-1);margin:var(--sp-0) 0;font-size:.8rem}
.rank .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rank .track{height:.5rem;background:var(--surface-2);border-radius:var(--pill);
  overflow:hidden}
.rank .track i{display:block;height:100%;border-radius:var(--pill)}
.rank .amt{font-size:.72rem;color:var(--muted);white-space:nowrap;
  font-variant-numeric:tabular-nums}
/* One shared tooltip element, moved on hover. Its content is NOT a second copy of
   the numbers: it is the `title` already on the mark, re-rendered. With JS off the
   browser shows the same text natively, so the file still explains itself from a
   file:// URL — which is how a shared report is usually opened. */
.rtip{position:fixed;z-index:60;pointer-events:none;background:var(--surface);
  border:1px solid var(--border-strong);border-radius:var(--radius);
  box-shadow:var(--shadow-md);padding:var(--sp-1) var(--sp-2);font-size:.74rem;
  max-width:18rem;color:var(--text)}
.rtip[hidden]{display:none}
.rtip b{display:block;font-weight:600;margin-bottom:var(--sp-0);
  word-break:break-word}
.rtip span{display:flex;gap:var(--sp-2);font-variant-numeric:tabular-nums;
  line-height:1.5}
.rtip span em{color:var(--muted);font-style:normal;flex:1 1 auto;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rtip span i{font-style:normal;font-weight:600}
@media print{.rtip{display:none!important}}
/* Budget burn-down. Only rendered when a phase declares one, so it costs nothing
   in the common case and is prominent in the case that matters. */
.buds{margin-top:var(--sp-1)}
/* Name capped, bar takes the slack — otherwise a 1fr name column pushes the bar
   to the far right and the row stops reading as one thing. */
.buds{max-width:58rem}
.bud{display:grid;grid-template-columns:minmax(9rem,20rem) minmax(5rem,1fr) 3rem auto;
  align-items:center;gap:var(--sp-2);margin:var(--sp-1) 0;font-size:.8rem}
.bud .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bud .track{height:.55rem;background:var(--surface-2);border-radius:var(--pill);
  overflow:hidden}
.bud .track i{display:block;height:100%;border-radius:var(--pill);
  background:var(--st-done)}
.bud.over .track i{background:var(--st-blocked)}
.bud .pct{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.bud.over .pct{color:var(--st-blocked);font-weight:640}
.bud .amt{font-size:.72rem;color:var(--muted);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.bud.total{border-top:1px solid var(--border);padding-top:var(--sp-1);
  margin-top:var(--sp-1)}
.bud.total .nm{color:var(--muted)}
/* The total has no bar; an empty track would paint a grey rail that reads as a
   phase sitting at zero, which is the one thing this block must never imply. */
.bud.total .track{background:none}
@media (max-width:34rem){
  .bud{grid-template-columns:1fr auto;gap:.15rem}
  .bud .track{display:none}
}
.legend{display:flex;flex-wrap:wrap;gap:var(--sp-1) var(--sp-3);
  margin:var(--sp-1) 0 var(--sp-2);font-size:.78rem;color:var(--muted)}
.legend b{display:inline-flex;align-items:center;gap:var(--sp-1);
  font-weight:500;color:var(--text)}
.legend i{width:.62rem;height:.62rem;border-radius:3px;display:inline-block}
details.more{margin-top:var(--sp-5);border-top:1px solid var(--border);
  padding-top:var(--sp-2)}
details.more>summary{cursor:pointer;font-size:.8rem;color:var(--muted);
  padding:var(--sp-1) 0}
details.more>summary:hover{color:var(--text)}
/* small multiples: one cell per author, one row per model */
.smgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));
  gap:var(--sp-3)}
.smcell{border:1px solid var(--border);border-radius:var(--radius);
  padding:var(--sp-2);background:var(--surface)}
.smcell h4{font-size:.78rem;margin:0 0 var(--sp-1);font-weight:600;border:0;
  text-transform:none;letter-spacing:0;color:var(--text)}
.mm{display:grid;grid-template-columns:.62rem 8rem 1fr;align-items:center;
  gap:var(--sp-1);margin:var(--sp-0) 0}
.mk{width:.62rem;height:.62rem;border-radius:3px}
.mn{font-size:.68rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.spark{width:100%;height:30px;display:block}
.spark rect{fill:var(--sc,var(--bar-neutral));opacity:.9}
/* Full-height invisible hit targets, so a 2px column is still hoverable.
   pointer-events is set explicitly: the default (visiblePainted) is not required
   to hit a fully transparent fill. */
.spark rect.hit{fill:transparent;opacity:1;pointer-events:all;cursor:default}
/* phase composition */
.uphase{display:grid;grid-template-columns:minmax(6rem,13rem) 1fr auto;
  gap:var(--sp-1) var(--sp-2);align-items:center;margin:var(--sp-0) 0}
.uphase .nm{font-size:.83rem;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.uphase .amt{font-size:.78rem;color:var(--muted);
  font-variant-numeric:tabular-nums;white-space:nowrap}
/* Stacked bar: the 2px flex gap IS the separator - no strokes around segments. */
.stack{display:flex;gap:2px;height:14px;align-items:stretch}
.seg{min-width:2px;border-radius:1px}
.seg:last-child{border-radius:1px 4px 4px 1px}
/* day x hour heatmap */
.hmwrap{overflow-x:auto}
.hm{border-collapse:separate;border-spacing:2px;font-size:.62rem;color:var(--muted)}
/* The report's global `thead th` is sticky for the long phases table; a 7-row
   heatmap must opt out or its hour ruler detaches and floats over the grid. */
.hm thead th{position:static;background:none;border:0;padding:0 var(--sp-0)}
.hm th{font-weight:500;color:var(--muted);padding:0 var(--sp-0);text-align:right;
  white-space:nowrap}
.hm td{padding:0}
.hm i{display:block;width:20px;height:15px;border-radius:2px;background:var(--hm-0)}
.hm i[data-l="1"]{background:var(--hm-1)}.hm i[data-l="2"]{background:var(--hm-2)}
.hm i[data-l="3"]{background:var(--hm-3)}.hm i[data-l="4"]{background:var(--hm-4)}
.hm i[data-l="5"]{background:var(--hm-5)}.hm i[data-l="6"]{background:var(--hm-6)}
.hmkey{display:flex;align-items:center;gap:var(--sp-0);font-size:.7rem;
  color:var(--muted);margin-top:var(--sp-1)}
.hmkey i{width:20px;height:15px;border-radius:2px;display:inline-block}
@media (max-width:40rem){
  .uphase,.rank{grid-template-columns:1fr;gap:.15rem}
  .uphase .amt,.rank .amt{text-align:left}
  .rank .track{display:none}
  .mm{grid-template-columns:.62rem 1fr}
  .mm .spark{grid-column:1/-1}
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
  // Restore only when this report owns the toggle. Embedded (no button), the host
  // sets data-theme and must win; restoring a value saved on some earlier visit
  // would silently override the theme the viewer is actually looking at. A page
  // that does not offer the control has no business reinstating its state.
  if (themeBtn) {
    try { var savedTheme = localStorage.getItem(THEME_KEY); if (savedTheme) root.setAttribute('data-theme', savedTheme); } catch (e) {}
  }
  paintTheme();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var next = isDark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    paintTheme();
  });

  // Scroll-spy. The links work without any of this — they are plain anchors
  // rendered server-side — so this only adds the half a nav cannot do statically:
  // saying where you ARE. Without it the sidebar is a menu; with it, a position.
  var navLinks = [].slice.call(document.querySelectorAll('.snav a'));
  if (navLinks.length && window.IntersectionObserver) {
    var targets = navLinks.map(function (a) {
      return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)));
    });
    var visible = {};
    var mark = function () {
      // Topmost visible section wins. Picking "most visible" instead makes the
      // marker jump backwards when a long section scrolls past a short one.
      var best = -1;
      targets.forEach(function (el, i) {
        if (el && visible[i] && (best < 0 || el.getBoundingClientRect().top <
            targets[best].getBoundingClientRect().top)) best = i;
      });
      navLinks.forEach(function (a, i) {
        if (i === best) a.setAttribute('aria-current', 'true');
        else a.removeAttribute('aria-current');
      });
    };
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        var i = targets.indexOf(en.target);
        if (i >= 0) visible[i] = en.isIntersecting;
      });
      mark();
    }, { rootMargin: '-15% 0px -70% 0px' });
    targets.forEach(function (el) { if (el) io.observe(el); });
  }

  // Toolbar elevation once the page scrolls under it.
  var toolbar = document.querySelector('.topbar');
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
      // 'table-row', NOT '': clearing the inline style hands the row back to the
      // stylesheet, where `tr.taskfilter{display:none}` wins — so the per-phase
      // status filter was emitted into every report, populated by JS, and could
      // never be seen. `tr.task` survives the same pattern only because it has no
      // default display rule to fall back to.
      if (tfRow) tfRow.style.display = open ? 'table-row' : 'none';
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
      // A column header that sorts on click is a control, so it has to be one:
      // reachable by Tab, operable by Enter/Space, and announcing its own state.
      // Without aria-sort the current order is conveyed by a CSS ::after arrow
      // alone, which a screen reader never sees.
      th.setAttribute('role', 'button');
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-sort', 'none');
      var doSort = function () {
        var asc = th.getAttribute('data-sort') !== 'asc';
        [].forEach.call(ths, function (h) {
          h.removeAttribute('data-sort');
          h.classList.remove('sorted');
          h.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('data-sort', asc ? 'asc' : 'desc');
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
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
      };
      th.addEventListener('click', doSort);
      th.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();   // Space would otherwise scroll the page
          doSort();
        }
      });
    });
  }

  // build a toggle-chip bar from a set of statuses
  function buildChips(host, statuses, dataAttr, onToggle) {
    Object.keys(statuses).sort().forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'fchip';
      // Which filter is on was conveyed by the `on` class alone — i.e. by colour.
      // aria-pressed is what makes a toggle button's state readable.
      b.setAttribute('aria-pressed', 'false');
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
      var on = x.getAttribute(dataAttr) === active;
      x.className = (on ? x.className.split(' ')[0] + ' on' : x.className.split(' ')[0]);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
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

  // A CLOSED <details> still collapses in print media even when its children are
  // forced visible by CSS — the element clips them, so the print stylesheet alone
  // silently drops the Usage detail from the PDF. Open them for the duration of
  // the print and restore afterwards, so what you see is what you get.
  var reopen = [];
  window.addEventListener('beforeprint', function () {
    reopen = [];
    Array.prototype.forEach.call(document.querySelectorAll('details'), function (d) {
      if (!d.open) { reopen.push(d); d.open = true; }
    });
  });
  window.addEventListener('afterprint', function () {
    reopen.forEach(function (d) { d.open = false; });
    reopen = [];
  });

  // Hover layer for the Usage charts. It renders NOTHING of its own: every value
  // it shows already sits in a `title` attribute (or an SVG <title> child) on the
  // mark, so with JS disabled the browser shows the same text natively and the
  // report still explains itself from a file:// URL. Titles are stashed and
  // removed while JS is live only so the native tooltip does not fight this one.
  (function () {
    // Scoped to the Usage section — the siblings between its <h2> and the next
    // one. Everything else in the report keeps its plain native tooltips.
    var start = document.getElementById('usage');
    if (!start) return;
    var found = 0;
    function claim(node, text) {
      if (!node || !text) return;
      node.__tip = text; found++;
    }
    for (var s = start.nextElementSibling; s && s.tagName !== 'H2';
         s = s.nextElementSibling) {
      if (s.hasAttribute('title')) {
        claim(s, s.getAttribute('title')); s.removeAttribute('title');
      }
      Array.prototype.forEach.call(s.querySelectorAll('[title]'), function (n) {
        claim(n, n.getAttribute('title')); n.removeAttribute('title');
      });
      // SVG <title> children — same text, different carrier.
      Array.prototype.forEach.call(s.querySelectorAll('title'), function (t) {
        claim(t.parentNode, t.textContent);
        if (t.parentNode) t.parentNode.removeChild(t);
      });
    }
    if (!found) return;

    var box = document.createElement('div');
    box.className = 'rtip'; box.hidden = true;
    document.body.appendChild(box);

    function fill(text) {
      box.textContent = '';
      text.split('\n').forEach(function (line, i) {
        if (i === 0) {
          var b = document.createElement('b'); b.textContent = line;
          box.appendChild(b); return;
        }
        var parts = line.split('\t');
        var row = document.createElement('span');
        var k = document.createElement('em'); k.textContent = parts[0];
        var v = document.createElement('i'); v.textContent = parts[1] || '';
        row.appendChild(k); row.appendChild(v); box.appendChild(row);
      });
    }
    function place(ev) {
      var r = box.getBoundingClientRect();
      var x = ev.clientX + 14, y = ev.clientY + 16;
      if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - 14;
      if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 16;
      box.style.left = Math.max(8, x) + 'px';
      box.style.top = Math.max(8, y) + 'px';
    }
    // Delegated: three listeners instead of one per mark. A dense report carries
    // well over a thousand hoverable marks, and binding each of them is a cost
    // paid on every page load to serve one hover at a time.
    function owner(node) {
      for (var n = node; n && n !== document; n = n.parentNode) {
        if (n.__tip) return n;
      }
      return null;
    }
    var current = null;
    document.addEventListener('mouseover', function (ev) {
      var m = owner(ev.target);
      if (m === current) return;
      current = m;
      if (!m) { box.hidden = true; return; }
      fill(m.__tip); box.hidden = false; place(ev);
    });
    document.addEventListener('mousemove', function (ev) {
      if (current) place(ev);
    });
    // Printing a floating tooltip would stamp it onto the page.
    window.addEventListener('beforeprint', function () {
      box.hidden = true; current = null;
    });
  })();

  // Download the Markdown twin (embedded as base64, decoded to a Blob).
  // Copy the run command. clipboard.writeText is unavailable on file:// in some
  // browsers, which is exactly where this report is most often opened, so the
  // fallback selects the text and lets the reader use their own copy key rather
  // than failing silently and leaving a button that does nothing.
  [].slice.call(document.querySelectorAll('.btn-copy')).forEach(function (b) {
    b.addEventListener('click', function () {
      var text = b.getAttribute('data-copy') || '';
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1600); };
      try {
        navigator.clipboard.writeText(text).then(done, function () { selectRun(b); });
      } catch (e) { selectRun(b); }
    });
  });
  function selectRun(btn) {
    var code = btn.parentNode.querySelector('.vd-run');
    if (!code) return;
    var r = document.createRange(); r.selectNodeContents(code);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    btn.textContent = 'Press to copy';
    setTimeout(function () { btn.textContent = 'Copy'; }, 2400);
  }

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


def _undeclared_css_vars(css):
    """Custom properties referenced by var() but never declared anywhere.

    This check exists because the failure mode is SILENT and total: an undeclared
    `var(--x)` makes the whole declaration invalid at computed-value time, so the
    property falls back to its INITIAL value rather than to the stylesheet rule
    underneath it. An undeclared colour token therefore paints transparent — a bar
    chart with no bars — and logs nothing. That is exactly how `--bar-neutral`
    shipped invisible in light mode once."""
    declared = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", css))
    # Only FALLBACK-LESS references are dangerous. `var(--x, something)` degrades
    # gracefully by design, and tokens set inline per element from Python (--w on a
    # progress fill, --sc on a sparkline) are always written that way for exactly
    # this reason.
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)", css))
    return sorted(used - declared)


def _unterminated_css_decls(css):
    """Custom-property declarations that run past their line without a `;`.

    A custom property's value is almost anything up to the next `;` or the block's
    closing `}` — comments and later declarations included. So a missing semicolon
    does not raise; it silently ANNEXES whatever follows. One missing `;` after
    `--ease` swallowed a five-line comment plus the `--sp-0` declaration, which cost
    two things at once: `--ease` became a garbage multi-line value, making every
    `animation`/`transition` shorthand that referenced it invalid at computed-value
    time (so the report's progress-bar fill, card and button transitions and the
    heading fade were all dead), and `--sp-0` was never declared at all.

    `_undeclared_css_vars` cannot see this: the annexed text still reads as
    `--sp-0:` to a regex looking for declarations, so the token appears declared.
    That is why this is a separate check rather than a stricter one.

    Omitting the `;` on the LAST declaration in a block is legal and common, so a
    line only counts when more content follows before the block closes."""
    bad, lines = [], css.split("\n")
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not re.search(r"--[A-Za-z0-9_-]+\s*:", line):
            continue
        if line.endswith((";", "{", "}")):
            continue
        # Unterminated. Harmless only if the block ends before any further content.
        for nxt in lines[i + 1:]:
            nxt = nxt.strip()
            if not nxt:
                continue
            if nxt.startswith("}"):
                break                      # last declaration in its block — legal
            bad.append("line %d: %s" % (i + 1, line[:72]))
            break
    return bad


def _theme_asymmetric_vars(css):
    """Colour tokens that exist in one theme but not the other - in EITHER direction.

    The light `:root` is the base token set; the dark blocks are overrides. There are
    two distinct silent failures here, and the first version of this check only
    caught one of them:

      * declared in light, missing from dark -> the token vanishes in dark mode
      * declared ONLY in a dark block        -> it vanishes in LIGHT mode, which is
        exactly how `--bar-neutral` shipped as invisible bars

    Both render transparent with nothing in the console, so both are checked."""
    light = re.search(r":root\s*\{([^}]*)\}", css)
    if not light:
        return []
    light_vars = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", light.group(1)))
    dark_vars = set()
    for block in re.findall(
            r"(?:prefers-color-scheme\s*:\s*dark|data-theme=.?dark)[^{]*\{(.*?)\}\}?",
            css, re.S):
        dark_vars |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", block))
    if not dark_vars:
        return []
    # spacing / type / motion / font tokens are theme-independent by design and are
    # deliberately declared once, in the base only.
    neutral = ("--sp-", "--t-", "--dur", "--ease", "--radius", "--pill",
               "--sans", "--mono", "--shadow")

    def colourish(names):
        return {v for v in names if not any(v.startswith(n) for n in neutral)}

    return sorted("%s (light only)" % v
                  for v in colourish(light_vars) - dark_vars) + \
        sorted("%s (dark only)" % v for v in colourish(dark_vars) - light_vars)


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
        spec = importlib.util.spec_from_file_location(
            "usage_ledger", os.path.join(_HERE, "usage_ledger.py"))
        ul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ul)
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
    throws away the thing that made it a count."""
    n = int(n or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return "%.*f%s" % (dp, n / float(limit), suffix)
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
    `color-scheme:light dark`, honours both `prefers-color-scheme` and an explicit
    `:root[data-theme]`, and scrolls its wide tables inside `.tablewrap` instead of
    the page.

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

    out.append('<header class="topbar"><div class="tb-id">'
               '<h1>%s</h1><p class="meta">%s · %d phases · %d tasks · %d bugs · '
               "generated %s</p></div>"
               % (e(meta.get("title") or "Audit report"),
                  e(meta.get("repo") or "?"), len(summary["phases"]),
                  summary["tasks"]["total"], summary["bugs"]["total"], now))
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
        'title="Print / Save as PDF — all phases expanded, A4">Save as PDF</button>'
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
    table_tools = (
        '<div class="toolbar sectools" role="search">'
        '<input id="audit-q" type="search" aria-label="Filter phases and tasks by text" '
        'placeholder="Filter phases &amp; tasks by text\u2026">'
        '<span class="tbl">Phase status:</span><span id="audit-phase-status"></span>'
        '<button type="button" id="audit-expand" class="btn">expand all</button>'
        '<span id="audit-count" class="muted"></span></div>')

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
            '<span class="mono">%s</span> <strong>%s</strong>%s %s%s%s %s%s</td></tr>'
            % (e(pid), e(pid), e(psum["status"]),
               ' data-held="1"' if held else "",
               e(" ".join(areas)), ncol, e(pid), e(psum["title"]),
               area_tags, _chip(psum["status"]), held_mark, stamp,
               _bar(psum["done"], psum["total"]), _phase_meta_div(ph)))
        # per-phase task-status filter (shown only when the phase is expanded);
        # _SCRIPT fills .tf-chips from this phase's own task statuses.
        out.append('<tr class="taskfilter" data-phase="%s"><td colspan="%d">'
                   '<span class="tf-label">Filter tasks by status:</span>'
                   '<span class="tf-chips"></span></td></tr>' % (e(pid), ncol))
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
                '<tr class="task" data-phase="%s" data-status="%s"%s>'
                '<td class="mono tid">%s</td><td>%s</td><td>%s</td>%s</tr>'
                % (e(pid), e(t.get("status")),
                   ' data-held="1"' if held else "",
                   e(t.get("id")), e(t.get("title")),
                   _chip(t.get("status")),
                   "".join(cells[c]() for c in cols)))
    out.append("</tbody></table></div></section>")

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
          "IntersectionObserver" in _SCRIPT and "aria-current" in _SCRIPT)
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
    check("shell: paper gets the document back - no bars, no nav, no section tools",
          ".topbar,.snav,.toolbar,tr.taskfilter{display:none!important}" in _CSS)

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
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
