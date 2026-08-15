#!/usr/bin/env node
/**
 * Capture the committed README screenshots — report and control panel.
 *
 * WHY THIS EXISTS. The eleven PNGs in docs/screenshots/ were captured by hand, and
 * they drifted twice over. The panel shots show three tabs against a UI that has
 * four. Worse, every report shot shows an EMPTY progress bar — including a phase at
 * 2/2 — because `.fill` carries `animation:fillIn .9s` and a manual capture caught
 * it at t=0. The README hero image is that file. The stylesheet already ships the
 * fix (`@media (prefers-reduced-motion:reduce){.fill{animation:none}}`); the capture
 * simply never asked for it. This does:
 *
 *     newContext({ reducedMotion: 'reduce' })
 *
 * FIXTURES ARE GENERATED, NEVER STORED. Panel shots need a large manifest to make
 * the "usable at 50 phases x 20 tasks" claim visible; that manifest was never
 * committed, which is why the shots could not be refreshed. gen-demo-manifest.py
 * rebuilds it deterministically, so this script builds what it needs in a temp dir
 * and throws it away.
 *
 *     node tools/capture-screenshots.mjs [--out docs/screenshots] [--only report|panel]
 *     node tools/capture-screenshots.mjs --check
 *
 * --check writes nothing. It asserts the DOM facts that the captures depend on —
 * chiefly that progress-bar fills have a real painted width. That assertion is
 * portable, which pixel comparison is not: browser font rasterisation differs
 * between macOS and CI Linux, so byte-comparing a committed PNG against a fresh CI
 * capture would fail for reasons that have nothing to do with the product. Run
 * --check in CI; run the capture locally when a UI change lands.
 */
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync, mkdirSync, readFileSync, statSync,
         writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPTS = path.join(REPO, 'plugins', 'audit', 'scripts');
const PY = process.env.PYTHON || 'python3';

const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const CHECK = argv.includes('--check');
const OUT = path.resolve(REPO, arg('--out', 'docs/screenshots'));
const ONLY = arg('--only', 'all');

/** The identity the panel fixture writes as. See where it is installed, below. */
const DEMO_AUTHOR = 'dev@example.com';

/** The endpoint the panel's run-status poll reads. Fixtures for it go HERE. */
const RUNSTATUS_URL = '**/api/runstatus';

const problems = [];
const note = (m) => console.log(`  ${m}`);
const fail = (m) => { problems.push(m); console.log(`  FAIL ${m}`); };

/**
 * One CSV record as fields, double-quote escaping respected (RFC 4180).
 *
 * F-D-1 (v0.37 A3): the borrowed substring regex this replaces
 * (`/"?\d+,\d{3}[,."]/`) read a legitimate 3-digit count after a date field
 * ("…-13,123,…" across a field boundary) as a thousands separator —
 * reproduced on a real ledger. Structure cannot be fooled that way: parse the
 * record into fields, then judge only the fields that claim to be numbers.
 * The report-side export check in tools/check-report-interactive.mjs is the
 * precedent. Exported so a probe can drive the assertion without a browser.
 */
export const csvFields = (line) => {
  const out = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < line.length; i += 1) {
    const c = line[i];
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i += 1; }
      else if (c === '"') q = false;
      else cur += c;
    } else if (c === '"') q = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
};

/**
 * First data line whose named numeric columns carry anything but a raw
 * number (grouping separators included), or whose field count disagrees with
 * the header — a spreadsheet reads either as text and every sum over the
 * column is then silently wrong. `lines` is header-first, BOM/CRLF stripped.
 * Returns null when every line is clean.
 */
export const firstNonRawNumberLine = (lines, numericCols) => {
  const head = csvFields(lines[0] || '');
  const idx = numericCols.map((c) => head.indexOf(c)).filter((i) => i >= 0);
  for (const line of lines.slice(1)) {
    const f = csvFields(line);
    if (f.length !== head.length) return line;
    if (idx.some((i) => !/^\d+(\.\d+)?$/.test(f[i]))) return line;
  }
  return null;
};

function py(args, env = {}) {
  return execFileSync(PY, args, {
    cwd: REPO, encoding: 'utf8', env: { ...process.env, ...env },
  });
}

/** Minimal static file server — Playwright refuses file:// for these pages. */
function serveDir(dir) {
  const types = { '.html': 'text/html; charset=utf-8', '.md': 'text/markdown',
                  '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json' };
  const server = createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '');
    const file = path.join(dir, rel);
    if (!file.startsWith(dir)) { res.writeHead(403).end(); return; }
    try {
      const body = readFileSync(file);
      res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
      res.end(body);
    } catch { res.writeHead(404).end('not found'); }
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

/**
 * Start the control panel and recover its URL from the pidfile.
 *
 * Deliberately NOT parsed from stdout: the panel prints a URL containing its
 * session token, and that print is being removed (it lands in terminal scrollback
 * and CI logs). The pidfile is the durable interface.
 */
async function startPanel(project, env = {}) {
  const proc = spawn(PY, [path.join(SCRIPTS, 'panel-server.py'),
                          '--project', project, '--no-open'],
                     { cwd: REPO, stdio: 'ignore', env: { ...process.env, ...env } });
  const pidfile = path.join(project, '.claude', 'audit-panel.json');
  for (let i = 0; i < 100; i++) {
    try {
      const info = JSON.parse(await readFile(pidfile, 'utf8'));
      if (info.url) {
        // The pidfile appears before the socket is necessarily accepting.
        for (let j = 0; j < 50; j++) {
          try {
            const r = await fetch(info.url, { redirect: 'manual' });
            if (r.status < 500) return { proc, url: info.url };
          } catch { /* not up yet */ }
          await new Promise((r) => setTimeout(r, 100));
        }
        return { proc, url: info.url };
      }
    } catch { /* not written yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('panel did not start (no pidfile at ' + pidfile + ')');
}

/**
 * Wait until nothing is still moving.
 *
 * reducedMotion alone is not enough. These pages animate on entry with
 * `animation-fill-mode: both`, so a capture taken before the first animation frame
 * sees the BACKWARDS fill — the from-state — and `fadeUp` starts at opacity 0. That
 * is a screenshot of an invisible summary card. Waiting on `load` does not help
 * because load fires before first paint.
 */
async function settle(page) {
  try { await page.evaluate(() => document.fonts && document.fonts.ready); } catch { /* ok */ }
  try {
    await page.waitForFunction(
      () => document.getAnimations().every((a) => a.playState === 'finished'),
      null, { timeout: 5000 });
  } catch { /* an infinite ambient animation would time out; carry on */ }
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
}

/** The defect this whole script exists to prevent. */
async function assertBarsPainted(page, label) {
  const bars = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.fill').forEach((el) => {
      // Only bars that are laid out at all: a bar inside the report's
      // collapsed done-archive (D1) sits in a display:none row, and 0px is
      // the CORRECT paint for it. offsetParent is null exactly then.
      if (el.offsetParent === null) return;
      const cs = getComputedStyle(el);
      out.push({
        declared: el.getAttribute('style') || '',
        // getBoundingClientRect, NOT parseFloat(getComputedStyle().width): an
        // unlaid-out inline box reports its width as the literal "100%", and
        // parseFloat("100%") is 100 — so the first version of this check passed
        // while every bar on the page was painting zero pixels wide.
        widthPx: el.getBoundingClientRect().width,
        trackPx: el.parentElement ? el.parentElement.getBoundingClientRect().width : 0,
        display: cs.display,
        animation: cs.animationName,
      });
    });
    return out;
  });
  if (!bars.length) { fail(`${label}: no progress bars found at all`); return; }
  const inline = bars.filter((b) => b.display === 'inline');
  if (inline.length) {
    fail(`${label}: ${inline.length} bar fill(s) are display:inline — an inline box `
       + `ignores width and height, so the bar paints as an empty track`);
  }
  const declared = bars.filter((b) => !/--w:\s*0%/.test(b.declared));
  const unpainted = declared.filter((b) => b.widthPx <= 0.5);
  if (unpainted.length) {
    fail(`${label}: ${unpainted.length} of ${declared.length} progress bars declare a `
       + `non-zero width but paint 0px wide`);
  } else {
    note(`${label}: ${declared.length}/${declared.length} progress bars painted`);
  }
  // A 100% bar must fill its track. Catches an animation or fill-mode that pins the
  // fill somewhere short of its declared value.
  for (const b of bars.filter((x) => /--w:\s*100%/.test(x.declared))) {
    if (b.trackPx > 0 && b.widthPx < b.trackPx * 0.9) {
      fail(`${label}: a 100% bar paints ${b.widthPx.toFixed(1)}px inside a `
         + `${b.trackPx.toFixed(1)}px track`);
    }
  }
  // Reveal animations must not leave content invisible.
  const hidden = await page.evaluate(() =>
    ['.overall', '.summary', 'h1'].filter((s) => {
      const el = document.querySelector(s);
      return el && parseFloat(getComputedStyle(el).opacity) < 0.99;
    }));
  if (hidden.length) {
    fail(`${label}: ${hidden.join(', ')} still at opacity < 1 — a reveal animation is `
       + `holding content hidden`);
  }
}

/**
 * Every ⓘ must open its bubble INSIDE the viewport (F9).
 *
 * A check of its own rather than one more selector in the overflow sweep, because
 * the bubble is `.hint::after` — a pseudo-element, with no node. Nothing can call
 * getBoundingClientRect on it, so the sweep's "widest element crossing the edge"
 * list comes back EMPTY while the document is 103px too wide. That mismatch is the
 * signature of this defect, and it is the reason it survived a check that was
 * already measuring the page it broke.
 *
 * Both edges are asserted, because the two failures look nothing alike. Past the
 * right edge the DOCUMENT scrolls sideways. Past the left edge nothing scrolls at
 * all — a left overflow is clipped, not scrolled to — and the tooltip is simply
 * unreadable, which is what the old `.flip` produced for 20 of Settings' 27
 * controls on a phone. A fix aimed at the overflow alone would have passed here.
 */
async function assertHintsFit(page, label) {
  const boxes = await page.evaluate(() => {
    const out = [];
    const vw = document.documentElement.clientWidth,
          vh = document.documentElement.clientHeight;
    const scrollParent = (n) => {
      for (let p = n.parentElement; p; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (/(auto|scroll)/.test(cs.overflowX + cs.overflowY)) return p;
      }
      return document.documentElement;
    };
    for (const h of document.querySelectorAll('.hint[data-tip]')) {
      const r = h.getBoundingClientRect();
      if (!r.width) continue;                 // a hint in a view that is not showing
      // Only hints inside the vertical viewport: an icon below the fold cannot
      // be hovered without scrolling, and when the user scrolls, its rect - and
      // the tip computed from it - is different. Asserting the unhoverable
      // geometry would fail every long form on facts nobody can reach.
      if (r.bottom < 0 || r.top > vh) continue;
      const sp = scrollParent(h);
      const pre = { dw: document.documentElement.scrollWidth,
                    dh: document.documentElement.scrollHeight,
                    pw: sp.scrollWidth, ph: sp.scrollHeight };
      showTip(h);
      const b = document.getElementById('hinttip');
      const br = b.getBoundingClientRect();
      const cs = getComputedStyle(b);
      const grewW = document.documentElement.scrollWidth - pre.dw;
      const grewH = document.documentElement.scrollHeight - pre.dh;
      const grewPW = sp.scrollWidth - pre.pw;
      const grewPH = sp.scrollHeight - pre.ph;
      out.push({
        name: h.getAttribute('data-hint')
          || (h.getAttribute('data-tip') || '').slice(0, 20) + '\u2026',
        left: Math.round(br.left), right: Math.round(br.right),
        top: Math.round(br.top), bottom: Math.round(br.bottom), vw, vh,
        pos: cs.position, shown: cs.display !== 'none',
        onBody: b.parentElement === document.body,
        grew: (grewW || grewH || grewPW || grewPH)
          ? [grewW, grewH, grewPW, grewPH] : null,
      });
      hideTip();
    }
    return out;
  });
  // A view with no (i) is not a defect - Usage has none, and pinning WHICH views
  // do is a list that goes stale the first time one gains a label. What would be
  // a defect is none anywhere, so the callers sum this across the panel.
  if (!boxes.length) { note(`${label}: no \u24d8 on this view`); return boxes; }
  const vw = boxes[0].vw;
  const wrong = boxes.filter((b) => !b.shown || b.pos !== 'fixed' || !b.onBody);
  if (wrong.length) {
    fail(`${label}: ${wrong.length} tip(s) not shown as a fixed body-level `
       + `element (${wrong.slice(0, 3).map((b) => b.name).join('; ')}) - a tip `
       + `living inside any other box is one ancestor away from being trapped, `
       + `buried or demoted to absolute again`);
  }
  // The live-repo defect, asserted directly: SHOWING a tip must not grow any
  // scroll box - not the document's, not the hint's own scroll frame's.
  const grew = boxes.filter((b) => b.grew);
  if (grew.length) {
    fail(`${label}: showing ${grew.length} tip(s) GREW a scroll box (`
       + grew.slice(0, 3).map((b) => `${b.name} +${b.grew.join('/')}`).join('; ')
       + `) - hovering an \u24d8 must never change any box's size`);
  }
  const bad = boxes.filter((b) => b.left < 0 || b.right > b.vw + 1
    || b.top < 0 || b.bottom > b.vh + 1);
  if (bad.length) {
    fail(`${label}: ${bad.length} of ${boxes.length} \u24d8 tips open outside `
       + `the viewport - `
       + bad.slice(0, 3).map((b) =>
           `${b.name} at ${b.left}..${b.right},${b.top}..${b.bottom}`).join('; '));
  } else if (!wrong.length && !grew.length) {
    note(`${label}: ${boxes.length}/${boxes.length} \u24d8 tips open inside `
       + `${vw}px, fixed on <body>, growing nothing`);
  }
  return boxes;
}

/**
 * The theme toggle must move the NATIVE controls, not just our boxes.
 *
 * Custom properties cannot reach a checkbox, a `<select>` menu, a number spinner,
 * an `<input type=date>` picker or a scrollbar — the UA paints those from
 * `color-scheme` alone. Declared once on bare `:root` as `light dark`, it resolves
 * from `prefers-color-scheme` and ignores the toggle entirely, so an OS-light
 * reader who picks dark gets our dark surface wearing light controls. That shipped
 * for four releases and reading the stylesheet is exactly what hid it: the property
 * was present, the OVERRIDE was missing.
 *
 * So this is measured in a browser and never inferred from the CSS. The page is
 * driven from an OS-light context, which is the case a stylesheet-only reading
 * gets wrong: `light dark` under a light OS looks correct until you press the
 * button. Both directions, because pinning only dark is half a fix.
 */
async function assertThemeMovesNativeControls(page, label, toggleSel) {
  const scheme = () => page.evaluate(() =>
    getComputedStyle(document.documentElement).colorScheme);
  const btn = page.locator(toggleSel);
  if (!(await btn.count())) {
    fail(`${label}: no theme toggle at ${toggleSel} — selector is stale`);
    return;
  }
  await btn.click();
  await page.waitForTimeout(120);
  const dark = await scheme();
  await btn.click();
  await page.waitForTimeout(120);
  const light = await scheme();
  if (dark !== 'dark' || light !== 'light') {
    fail(`${label}: the toggle leaves the native controls behind — root `
       + `color-scheme reads "${dark}" on dark and "${light}" on light `
       + `(want "dark" / "light"); checkboxes, selects, spinners, the date picker `
       + `and the scrollbars keep the OS theme`);
  } else {
    note(`${label}: color-scheme follows the toggle (dark -> light round trip)`);
  }
}

/**
 * Overview is a filter, not a poster — so drive it.
 *
 * A panel selftest can only assert that a string is present in the document; it
 * cannot tell a working view from a dead one, and the panel has already shipped an
 * inline script with a missing paren while 209/209 string pins passed. Everything
 * below is asserted against an INDEPENDENT count taken from `STATE` in the page —
 * the manifest the server sent — rather than against the rendering path's own idea
 * of what it drew, so a filter that quietly matches everything fails here.
 *
 * The strip/pill count is deliberately not asserted to DROP: on a plan whose tasks
 * all share one status the correct filtered set is every phase, and calling that
 * "inert" is exactly the false accusation check-report-interactive.mjs made once
 * (see F3). The oracle is the expected set, computed here; equality holds either way.
 */
async function assertOverviewWorks(page) {
  const facts = await page.evaluate(() => {
    const rollup = STATE.rollup || {};
    const tasks = (STATE.composition || {}).tasks || [];
    const byStatus = {};
    for (const t of tasks) {
      (byStatus[t.status] = byStatus[t.status] || new Set()).add(t.phaseId);
    }
    return {
      phases: (rollup.phases || []).length,
      statuses: Object.fromEntries(
        Object.entries(byStatus).map(([s, set]) => [s, set.size])),
      areas: Object.keys(rollup.areas || {}).length,
      untagged: (rollup.phases || []).filter((p) => !(p.area || []).length).length,
      ready: (rollup.ready || []).length,
      outcomes: (rollup.phases || []).filter((p) => p.desiredOutcome).length,
      firstPhase: (rollup.phases || [])[0] ? (rollup.phases || [])[0].id : null,
    };
  });
  const rows = () => page.locator('#over .ovrow:visible').count();

  const pills = await page.locator('#over .ovpill').count();
  if (!pills) { fail('overview: no summary pills — the rollup strips did not render'); return; }
  if (await rows() !== facts.phases) {
    fail(`overview: ${await rows()} phase rows for ${facts.phases} phases in the rollup`);
  }
  if (facts.outcomes && !(await page.locator('#over .ovout').count())) {
    fail(`overview: ${facts.outcomes} phases carry a desiredOutcome and none is shown`);
  }

  // A task-status pill scopes the phase list to the phases carrying that status.
  const [status, expected] = Object.entries(facts.statuses)[0] || [];
  if (status) {
    const pill = page.locator(`#over .ovpill[data-status="${status}"]`).first();
    await pill.click();
    await page.waitForTimeout(150);
    const got = await rows();
    const pressed = await pill.getAttribute('aria-pressed');
    if (got !== expected) {
      fail(`overview: filtering to "${status}" shows ${got} phase rows, but ${expected} `
         + `phases carry a ${status} task`);
    } else if (pressed !== 'true') {
      fail(`overview: the "${status}" pill filters but never says it is on `
         + `(aria-pressed=${pressed})`);
    } else {
      note(`overview: "${status}" pill -> ${got}/${facts.phases} phases, aria-pressed set`);
    }
    if (!(await page.locator('#over [data-ovclear]').count())) {
      fail('overview: a filter is on and there is no way back — no Clear filters button');
    }
    await page.locator('#over [data-ovclear]').first().click();
    await page.waitForTimeout(150);
    if (await rows() !== facts.phases) fail('overview: Clear filters did not restore every phase');
  }

  // Search reaches the phase's own fields — id, title, area tags and the
  // desiredOutcome. The expected set is computed from STATE by the same substring
  // rule rather than assumed to be one row: "P1" is a prefix of P10..P19, and an
  // assertion of 1 would be testing the fixture's id scheme, not the search.
  if (facts.firstPhase) {
    for (const term of [facts.firstPhase, 'zzq-matches-nothing']) {
      const want = await page.evaluate((t) => (STATE.rollup.phases || []).filter((p) =>
        (p.id + ' ' + (p.title || '') + ' ' + (p.area || []).join(' ') + ' '
         + (p.desiredOutcome || '')).toLowerCase().includes(t.toLowerCase())).length, term);
      await page.fill('#ovq', term);
      await page.waitForTimeout(250);
      const got = await rows();
      if (got !== want) fail(`overview: searching "${term}" shows ${got} phases, ${want} match`);
      else if (!want && !(await page.locator('#over .ovempty').count())) {
        fail('overview: a search that matches nothing shows an empty list and no empty state');
      }
    }
    note('overview: search filters phases and says so when nothing matches');
    await page.fill('#ovq', '');
    await page.waitForTimeout(250);
  }

  // Group by area, from the rollup's own registry.
  if (facts.areas) {
    await page.check('#ovarea');
    await page.waitForTimeout(200);
    const groups = await page.locator('#over .ovgrp').count();
    const want = facts.areas + (facts.untagged ? 1 : 0);
    if (groups !== want) fail(`overview: grouping by area drew ${groups} groups, expected ${want}`);
    else note(`overview: grouped into ${groups} area groups`);
    await page.uncheck('#ovarea');
    await page.waitForTimeout(200);
  }

  // Ready-now is the card you act from: it must carry a real, copyable command.
  if (facts.ready) {
    const cmd = await page.locator('#over .rdy .rcmd').first().textContent();
    if (!/^\/audit:run \S+/.test(cmd || '')) {
      fail(`overview: ${facts.ready} tasks are ready and the card shows "${cmd}"`);
    } else {
      note(`overview: ready-now offers ${cmd}`);
    }
  }

  // A phase row is a control: it opens that phase in Composition, pre-filtered.
  if (facts.firstPhase) {
    await page.locator('#over .ovrow').first().click();
    await page.waitForTimeout(300);
    const landed = await page.evaluate((pid) => {
      const visible = [...document.querySelectorAll('#comp tr.phase')]
        .filter((r) => r.offsetParent !== null);
      // The row whose id cell IS this phase — startsWith would also collect
      // P10..P19 when the target is P1, and then nothing here is being measured.
      const mine = visible.filter((r) => {
        const cell = r.querySelector('.mono');
        return cell && cell.textContent === pid;
      });
      return {
        hash: location.hash,
        hidden: document.getElementById('comp').classList.contains('hidden'),
        q: (document.querySelector('#comp input[type=search]') || {}).value,
        rows: visible.length,
        total: document.querySelectorAll('#comp tr.phase').length,
        // Filtered to it AND opened on it: landing on a collapsed row in a scrolled
        // table is not "pre-filtered", it is the same table with fewer rows.
        open: mine.length === 1 && mine[0].classList.contains('open'),
      };
    }, facts.firstPhase);
    if (landed.hidden || landed.hash !== '#/comp') {
      fail(`overview: clicking a phase row did not open Composition (hash ${landed.hash})`);
    } else if (landed.q !== facts.firstPhase || landed.rows >= landed.total || !landed.open) {
      fail(`overview: Composition did not open on ${facts.firstPhase} — search is `
         + `"${landed.q}", ${landed.rows}/${landed.total} phase rows visible, `
         + `target row expanded: ${landed.open}`);
    } else {
      note(`overview: a phase row opens Composition filtered to ${facts.firstPhase} `
         + `(${landed.rows}/${landed.total} rows)`);
    }
    await page.fill('#comp input[type=search]', '');
    await page.click('.tab[data-t=over]');
    await page.waitForTimeout(200);
  }
}

/**
 * Usage is a dashboard you interrogate, so interrogate it.
 *
 * Same rule as assertOverviewWorks: every expected value is computed HERE from
 * `USAGE.facts` — the rows the server sent — and never from the renderer's own
 * aggregation, so a filter that quietly matches everything fails. The measured
 * value is read out of the rendered `messages` tile, which is the one KPI printed
 * as a plain integer: parsing its digits compares an exact number against an exact
 * number, with no second implementation of the compact token format to drift.
 */
async function assertUsageWorks(page) {
  // Sum msgs over the rows a predicate keeps. `pred` is a function body evaluated
  // against (f, F) inside the page, so the oracle is written here, in this file.
  const oracle = (body) => page.evaluate((b) => {
    const fn = new Function('f', 'F', 'USAGE', 'return (' + b + ')');
    const rows = USAGE.facts.filter((f) => fn(f, F, USAGE));
    return { n: rows.length, msgs: rows.reduce((a, f) => a + f[F.msgs], 0) };
  }, body);
  const compare = async (label, body) => {
    const want = await oracle(body); const got = await shownMsgs(page);
    if (got !== want.msgs) {
      fail(`usage: ${label} shows ${got} messages, but ${want.n} matching rows `
         + `carry ${want.msgs}`);
      return false;
    }
    note(`usage: ${label} -> ${want.n} rows, ${want.msgs} messages`);
    return true;
  };
  const clear = async () => {
    await page.evaluate(() => clearAll());
    await page.waitForTimeout(200);
  };

  if (!(await page.locator('#usage .utile').count())) {
    fail('usage: no KPI tiles — the tab did not render'); return;
  }
  await compare('unfiltered', 'true');

  // --- sparklines -----------------------------------------------------------
  // Drawn, not merely present: a path element with one point, or with a `d` the
  // browser could not parse, occupies the DOM and paints nothing.
  const sparks = await page.evaluate(() => [...document.querySelectorAll('#usage .utile')]
    .map((t) => {
      const p = t.querySelector('svg.uspark .sl');
      const b = p && p.getBBox();
      return { k: t.querySelector('.k').textContent,
               pts: p ? (p.getAttribute('d').match(/[ML]/g) || []).length : 0,
               w: b ? b.width : 0, h: b ? b.height : 0,
               why: (t.querySelector('.utrend') || {}).title || '' };
    }));
  const flat = sparks.filter((s) => s.pts && (s.w < 10 || s.h <= 0.5));
  const missing = sparks.filter((s) => !s.pts);
  if (flat.length) {
    fail(`usage: ${flat.map((s) => s.k).join(', ')} draw a sparkline that paints `
       + `nothing (${flat.map((s) => `${s.w.toFixed(1)}x${s.h.toFixed(1)}px`).join(', ')})`);
  } else if (sparks.length - missing.length < 3) {
    fail(`usage: only ${sparks.length - missing.length} of ${sparks.length} tiles `
       + `drew a sparkline`);
  } else {
    note(`usage: ${sparks.length - missing.length}/${sparks.length} tiles sparked `
       + `(${sparks.filter((s) => s.pts).map((s) => s.pts + 'pt').join(', ')})`);
  }
  // A tile with no daily series must say why, not stand there blank.
  for (const s of missing) {
    if (s.why.length < 20) {
      fail(`usage: the "${s.k}" tile has no sparkline and no explanation `
         + `("${s.why}")`);
    }
  }

  // --- the all-time trend chip ---------------------------------------------
  // This ledger's last day is two months behind the wall clock, which is the
  // normal state of a finished project. Anchored on today, "the last 30 days" is
  // empty on both sides and the chip never appears at all; anchored on the data,
  // it is the last 30 days of the ledger against the 30 before. The expected
  // percentage is computed here from the facts.
  const trend = await page.evaluate(() => {
    const day = (f) => f[F.ts].slice(0, 10);
    const days = [...new Set(USAGE.facts.map(day))].sort();
    const anchor = days[days.length - 1];
    const n = (d) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10)) / 864e5;
    const iso = (x) => new Date(x * 864e5).toISOString().slice(0, 10);
    const cut = iso(n(anchor) - 29), prev = iso(n(anchor) - 59);
    const sum = (a, b) => USAGE.facts.filter((f) => day(f) >= a && day(f) < b)
      .reduce((t, f) => t + f[F.tokens], 0);
    const now = sum(cut, '9999'), was = sum(prev, cut);
    const el = document.querySelector('#usage .utile [data-dl="tokens"]');
    return { want: was ? 100 * (now - was) / was : null,
             got: el ? parseFloat(el.textContent) : null,
             title: el ? el.title : '', anchor, cut, prev };
  });
  if (trend.want == null) {
    note('usage: fixture has no prior 30-day window; trend chip correctly absent');
  } else if (trend.got == null) {
    fail(`usage: the ledger ends ${trend.anchor} and has a prior window, but no `
       + `trend chip rendered — the delta is anchored on the wall clock`);
  } else if (Math.abs(trend.got - trend.want) > 1) {
    fail(`usage: trend chip reads ${trend.got}%, the facts say `
       + `${trend.want.toFixed(1)}% (${trend.cut}..${trend.anchor} vs ${trend.prev})`);
  } else if (!trend.title.includes(trend.cut) || !trend.title.includes(trend.prev)) {
    fail(`usage: the trend chip does not name the two periods it compared `
       + `("${trend.title}")`);
  } else {
    note(`usage: trend ${trend.got}% vs prior 30d, both windows named`);
  }

  // --- the new filters ------------------------------------------------------
  for (const dim of ['agent', 'attr']) {
    const sel = page.locator(`#usage select[data-uf=${dim}]`);
    if (!(await sel.count())) { fail(`usage: no ${dim} filter`); continue; }
    const val = await page.evaluate((d) => {
      const s = document.querySelector(`#usage select[data-uf=${d}]`);
      return [...s.options].map((o) => o.value).filter(Boolean)[0] || null;
    }, dim);
    if (!val) { note(`usage: ${dim} has one value in this fixture; skipped`); continue; }
    await sel.selectOption(val);
    await page.waitForTimeout(250);
    await compare(`${dim}=${val}`, `f[F.${dim}]===${JSON.stringify(val)}`);
    // A filter that cannot be taken off is worse than one that was never applied.
    const chip = page.locator(`#usage .uchip[data-uchip=${dim}]`);
    if (!(await chip.count())) fail(`usage: ${dim} is filtered and there is no chip to clear it`);
    else { await chip.click(); await page.waitForTimeout(250); }
    await compare(`${dim} cleared`, 'true');
  }

  // Free text reaches the row's own fields AND the titles behind its ids.
  const term = await page.evaluate(() => (USAGE.facts[0] || [])[F.model] || '');
  if (term) {
    await page.fill('#usage #uq', term);
    await page.waitForTimeout(500);
    await compare(`search "${term}"`, `[f[F.phase],f[F.task],f[F.model],f[F.author],`
      + `f[F.agent],f[F.attr],(USAGE.phaseTitles||{})[f[F.phase]]||'',`
      + `((USAGE.taskMeta||{})[f[F.task]]||{}).title||'',`
      // The haystack grew area tags (D4); the mirror must grow with it or a
      // term that happens to hit a tag makes the oracle disagree with the page.
      + `(((USAGE.phaseAreas||{})[f[F.phase]])||[]).join(' ')].join(' ').toLowerCase()`
      + `.includes(${JSON.stringify(term.toLowerCase())})`);
    // Typing is a filter change, and a filter change repaints the whole tab.
    const focused = await page.evaluate(() => document.activeElement
      && document.activeElement.id);
    if (focused !== 'uq') {
      fail(`usage: the search box lost focus to "${focused}" when its own keystroke `
         + `repainted the tab`);
    }
    await page.fill('#usage #uq', 'zzq-matches-nothing');
    await page.waitForTimeout(500);
    // A way back is the floor, not the goal: with one filter on, the page can say
    // which one emptied the view and offer to lift that one alone.
    const dead = await page.evaluate(() => {
      const w = document.querySelector('#usage [data-uwhy]');
      const f = document.querySelector('#usage [data-ufix]');
      return { why: w && w.getAttribute('data-uwhy'), text: w ? w.textContent : '',
               fix: f && f.getAttribute('data-ufix'),
               clear: !!document.querySelector('#usage [data-uclear]') };
    });
    if (!dead.clear) {
      fail('usage: a search that matches nothing leaves no rows and no way back');
    } else if (dead.why !== 'q' || dead.fix !== 'q') {
      fail(`usage: a search that matches nothing blames "${dead.why}" and offers `
         + `to lift "${dead.fix}" — the only filter on is the text box`);
    } else {
      note(`usage: the dead search names itself ("${dead.text.slice(0, 64)}")`);
    }
    await clear();
  }

  // The date pair writes the chart's own UF.day grammar, and completes a half
  // pair from the LEDGER's ends rather than from today.
  const from = await page.evaluate(() => {
    const d = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
    return d[Math.floor(d.length / 2)];
  });
  if (from) {
    await page.fill('#usage input[data-uf=from]', from);
    await page.waitForTimeout(350);
    await compare(`from ${from}`, `f[F.ts].slice(0,10)>=${JSON.stringify(from)}`);
    const paired = await page.evaluate(() => ({
      to: document.querySelector('#usage input[data-uf=to]').value,
      end: (USAGE.counts || {}).to, day: UF.day }));
    if (paired.to !== paired.end) {
      fail(`usage: half a date pair completed to "${paired.to}", but the ledger `
         + `ends ${paired.end} — the empty end is being filled from the clock`);
    } else if (paired.day !== `${from}..${paired.end}`) {
      fail(`usage: the date pair wrote UF.day="${paired.day}", not the `
         + `"from..to" grammar the chart click writes`);
    } else {
      note(`usage: from/to wrote ${paired.day} in the chart's own grammar`);
    }
    await clear();
  }

  // --- a range preset that begins after the ledger ends ---------------------
  // Every preset counts back from the wall clock. On a ledger whose last row is
  // months old — the normal end state of a finished plan, and exactly when
  // someone opens this tab to ask what it cost — the window begins after the data
  // stops and the tab renders empty. Empty is the correct answer; saying nothing
  // about why is not, because the conclusion left on the table is "metering never
  // ran". Whether it SHOULD be empty is decided here, from the facts.
  await clear();
  {
    const w = await page.evaluate(() => {
      const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
      return { last: days[days.length - 1],
               cut: new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10),
               to: (USAGE.counts || {}).to };
    });
    await page.selectOption('#usage select[data-uf=range]', '7');
    await page.waitForTimeout(300);
    if (w.last >= w.cut) {
      note(`usage: fixture reaches ${w.last}, inside the last 7 days — the `
         + `stale-ledger empty state cannot be driven against it`);
    } else {
      // Three honest zeros and one fabricated share: `attributed` divided by a
      // `||1` denominator and reported 100% coverage of no rows at all — on the
      // one tile of the four that is coloured by polarity, so the emptiest view
      // in the tab carried its most confident-looking number.
      const tiles = await page.evaluate(() => Object.fromEntries(
        [...document.querySelectorAll('#usage .utile')].map((t) => [
          t.querySelector('.k').textContent,
          t.querySelector('.v').firstChild.textContent.trim()])));
      if (/\d/.test(tiles.attributed || '')) {
        fail(`usage: over an empty selection the attributed tile reads `
           + `"${tiles.attributed}" — a share of nothing is undefined, not a `
           + `number (the others read ${JSON.stringify(tiles)})`);
      } else {
        note(`usage: an empty selection reports attributed `
           + `"${tiles.attributed}", not a manufactured share`);
      }
      const got = await page.evaluate(() => {
        const e = document.querySelector('#usage [data-uwhy]');
        const f = document.querySelector('#usage [data-ufix=range]');
        return { why: e && e.getAttribute('data-uwhy'), text: e ? e.textContent : '',
                 fix: f ? f.textContent : null,
                 clear: !!document.querySelector('#usage [data-uclear]') };
      });
      if (got.why !== 'range-after-ledger') {
        fail(`usage: "last 7 days" on a ledger ending ${w.last} renders `
           + `data-uwhy="${got.why}" — the empty view does not say the window `
           + `begins after the last row ever written`);
      } else if (!got.text.includes(w.to) || !got.text.includes(w.cut)) {
        fail(`usage: the empty view names neither the ledger's end (${w.to}) nor `
           + `the window's start (${w.cut}): "${got.text}"`);
      } else if (!got.fix || !got.clear) {
        fail(`usage: the empty view offers fix=${JSON.stringify(got.fix)} `
           + `clear=${got.clear} — the way to the view that does hold the data `
           + `is missing`);
      } else {
        note(`usage: "last 7 days" starts ${w.cut}, ledger ends ${w.to}; the tab `
           + `says so and offers "${got.fix}"`);
        await page.click('#usage [data-ufix=range]');
        await page.waitForTimeout(300);
        const back = await page.evaluate(() => UF.range);
        if (back !== 'all') {
          fail(`usage: "Show all time" left the range at "${back}"`);
        } else {
          await compare('range restored to all time', 'true');
        }
      }
    }
    await clear();
  }

  // --- C1: the forced month bin ---------------------------------------------
  // The inline pins can prove monthBins exists; only a browser can prove the
  // chart actually redraws under it, names the month in its heading, and cuts
  // its bins on the 1st rather than every 28 days wearing the name.
  {
    const sel = page.locator('#usage select[data-uf=bin]');
    if (!(await sel.count())) {
      fail('usage: no forced-bin control');
    } else {
      const monthOk = await page.evaluate(() => {
        const o = [...document.querySelector('#usage select[data-uf=bin]').options]
          .find((x) => x.value === 'month');
        return !!o && !o.disabled;
      });
      if (!monthOk) {
        note('usage: the month option is disabled on this fixture; bin caption check skipped');
      } else {
        await sel.selectOption('month');
        await page.waitForTimeout(300);
        const got = await page.evaluate(() => {
          const h = [...document.querySelectorAll('#usage h2')]
            .map((x) => x.textContent).find((t) => t.indexOf('Tokens per') === 0) || '';
          const sr = uSeries(uFiltered(), chartDim());
          return { head: h, size: sr.binSize,
                   starts: sr.bins.slice(1).map((b) => b[0].slice(8)) };
        });
        if (got.head.indexOf('Tokens per month') !== 0 || got.size !== 28) {
          fail(`usage: forced month bin draws "${got.head}" at size ${got.size}`);
        } else if (got.starts.some((d) => d !== '01')) {
          fail(`usage: month bins are not cut at month boundaries (starts ${got.starts.join(',')})`);
        } else {
          note(`usage: forced month bin -> "${got.head}", every interior bin starts on the 1st`);
        }
        await page.evaluate(() => { UF.bin = 'auto'; renderUsage(); });
        await page.waitForTimeout(200);
      }
    }
  }

  // --- C2: the Monthly card ---------------------------------------------------
  // Its ledger half is recomputed client-side, so the numbers on screen are
  // checked against a recomputation from the facts; a row click must write the
  // existing UF.day grammar, first of the month to its true end.
  {
    const row = page.locator('#usage [data-umonthly] tbody tr').first();
    if (!(await row.count())) {
      const months = await page.evaluate(() =>
        new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 7))).size);
      if (months >= 2) fail(`usage: ${months} ledger months but no Monthly card`);
      else note('usage: one ledger month; the Monthly card correctly stays away');
    } else {
      const m = await page.evaluate(() => {
        const tr = document.querySelector('#usage [data-umonthly] tbody tr');
        const key = tr.getAttribute('data-um');
        const want = USAGE.facts.filter((f) => f[F.ts].slice(0, 7) === key)
          .reduce((a, f) => a + f[F.msgs], 0);
        const cells = [...tr.cells].map((c) => c.textContent);
        // msgs column: after month, tokens (+cost when shown)
        const at = USAGE.showCost ? 3 : 2;
        return { key, want, got: parseInt(cells[at].replace(/\D/g, ''), 10) };
      });
      if (m.got !== m.want) {
        fail(`usage: the Monthly card says ${m.got} messages in ${m.key}, the facts say ${m.want}`);
      } else {
        note(`usage: Monthly card ${m.key} matches the facts (${m.want} messages)`);
      }
      await row.click();
      await page.waitForTimeout(250);
      const day = await page.evaluate(() => UF.day);
      const wantRange = new RegExp(`^${m.key}-01\\.\\.${m.key}-\\d{2}$`);
      if (!wantRange.test(day)) {
        fail(`usage: clicking month ${m.key} wrote UF.day="${day}", not the first..end grammar`);
      } else {
        note(`usage: clicking ${m.key} scoped the view to ${day}`);
      }
      await clear();
    }
  }

  // --- C4: the person header --------------------------------------------------
  // Zero new state, so nothing but a browser can see it fail to render. The
  // counts it shows ride in data attributes and are compared against an
  // in-page recomputation from the same facts.
  {
    const who = await page.evaluate(() => {
      const t = {};
      for (const f of USAGE.facts) t[f[F.author]] = (t[f[F.author]] || 0) + f[F.tokens];
      return Object.keys(t).sort((a, b) => t[b] - t[a])[0] || null;
    });
    if (!who) {
      fail('usage: the fixture records no author to drive the person header');
    } else {
      await page.evaluate((a) => setF('author', a), who);
      await page.waitForTimeout(250);
      const got = await page.evaluate((a) => {
        const elx = document.querySelector('#usage [data-ptasks]');
        const mine = USAGE.facts.filter((f) => f[F.author] === a);
        const tasks = new Set(mine.map((f) => f[F.task]).filter((t) => t && t !== '--'));
        const phases = new Set(mine.map((f) => f[F.phase]).filter((p) => p && p !== '--'));
        const msgs = mine.reduce((x, f) => x + f[F.msgs], 0);
        return {
          has: !!elx,
          head: (document.querySelector('#usage [data-person]') || {}).textContent || '',
          tasks: elx && +elx.getAttribute('data-ptasks'),
          phases: elx && +elx.getAttribute('data-pphases'),
          msgs: elx && +elx.getAttribute('data-pmsgs'),
          want: { tasks: tasks.size, phases: phases.size, msgs },
        };
      }, who);
      if (!got.has) {
        fail(`usage: an author filter on ${who} renders no person header`);
      } else if (got.tasks !== got.want.tasks || got.phases !== got.want.phases
                 || got.msgs !== got.want.msgs) {
        fail(`usage: the person header says ${got.phases} phases / ${got.tasks} tasks / `
           + `${got.msgs} msgs; the facts say ${got.want.phases} / ${got.want.tasks} / ${got.want.msgs}`);
      } else if (!got.head.includes(who)) {
        fail(`usage: the person header does not name ${who} ("${got.head}")`);
      } else {
        note(`usage: person header for ${who} matches the facts `
           + `(${got.want.phases} phases, ${got.want.tasks} tasks, ${got.want.msgs} msgs)`);
      }
      await clear();
      const gone = await page.evaluate(() => !document.querySelector('#usage [data-person]'));
      if (!gone) fail('usage: the person header outlives the author filter');
      else note('usage: the person header leaves with the filter');
    }
  }

  // --- D4: the area filter ----------------------------------------------------
  // The expected count is recomputed HERE from the two structures the server
  // shipped — USAGE.facts joined against USAGE.phaseAreas — never from the
  // renderer's own aggregation, so a match that quietly keeps everything fails.
  // The states this fixture cannot reach are driven in-page (the same way the
  // identity check drives STATE.viewer): the hiding rule by emptying the join
  // map, the haystack by blanking the titles that would otherwise mask it.
  {
    const sel = page.locator('#usage select[data-uf=area]');
    const tags = await page.evaluate(() => {
      const t = new Set();
      for (const f of USAGE.facts) {
        ((USAGE.phaseAreas || {})[f[F.phase]] || []).forEach((x) => t.add(x));
      }
      return [...t].sort();
    });
    if (!tags.length) {
      if (await sel.count()) {
        fail('usage: no phase tag reaches this ledger, yet an area select rendered');
      } else {
        note('usage: fixture joins no area tags; the area select correctly stays '
           + 'away (the hiding rule cannot be driven the other way here)');
      }
    } else if (!(await sel.count())) {
      fail(`usage: ${tags.length} area tags reach this ledger and no area select rendered`);
    } else {
      const tag = tags[0];
      await sel.selectOption(tag);
      await page.waitForTimeout(250);
      await compare(`area=${tag}`,
        `((USAGE.phaseAreas||{})[f[F.phase]]||[]).includes(${JSON.stringify(tag)})`);
      const chip = page.locator('#usage .uchip[data-uchip=area]');
      if (!(await chip.count())) {
        fail('usage: area is filtered and there is no chip to clear it');
      } else { await chip.click(); await page.waitForTimeout(250); }
      await compare('area cleared', 'true');

      // 'untagged' is offered exactly when untagged spend exists — the ledger
      // keeps an untagged bucket, and hiding it would make the tagged shares lie.
      const hasUntagged = await page.evaluate(() => USAGE.facts.some((f) => {
        const a = (USAGE.phaseAreas || {})[f[F.phase]];
        return !(a && a.length);
      }));
      const offered = await page.evaluate(() => [...document.querySelector(
        '#usage select[data-uf=area]').options].some((o) => o.value === 'untagged'));
      if (hasUntagged !== offered) {
        fail(`usage: untagged spend ${hasUntagged ? 'exists' : 'does not exist'} `
           + `and the area select ${offered ? 'offers' : 'does not offer'} 'untagged'`);
      } else if (hasUntagged) {
        await sel.selectOption('untagged');
        await page.waitForTimeout(250);
        await compare('area=untagged',
          '!(((USAGE.phaseAreas||{})[f[F.phase]]||[]).length)');
        await clear();
      } else {
        note('usage: no untagged spend in this fixture; the untagged bucket '
           + 'correctly stays out of the select');
      }

      // Free text must reach the tags THEMSELVES. On this fixture every phase
      // title contains its area word, which would mask a haystack that never
      // read the tags — so the titles are blanked (and the per-row haystack
      // cache dropped) for the duration of the probe, then restored.
      await page.evaluate((t) => {
        window.__d4Titles = USAGE.phaseTitles; USAGE.phaseTitles = {};
        USAGE.facts.forEach((f) => { delete f.h; });
        setF('q', t);
      }, tag);
      await page.waitForTimeout(250);
      await compare(`search "${tag}" reaches the tags with the titles blanked`,
        `[f[F.phase],f[F.task],f[F.model],f[F.author],f[F.agent],f[F.attr],`
        + `(USAGE.phaseTitles||{})[f[F.phase]]||'',`
        + `((USAGE.taskMeta||{})[f[F.task]]||{}).title||'',`
        + `(((USAGE.phaseAreas||{})[f[F.phase]])||[]).join(' ')`
        + `].join(' ').toLowerCase().includes(${JSON.stringify(tag.toLowerCase())})`);
      await page.evaluate(() => {
        USAGE.phaseTitles = window.__d4Titles; delete window.__d4Titles;
        USAGE.facts.forEach((f) => { delete f.h; });
      });
      await clear();

      // The hiding rule, driven from the state this fixture does not have: with
      // no tags in the join map the select must leave, because its only option
      // would be 'untagged' and that partitions nothing.
      const hides = await page.evaluate(() => {
        const saved = USAGE.phaseAreas;
        USAGE.phaseAreas = {}; renderUsage();
        const gone = !document.querySelector('#usage select[data-uf=area]');
        USAGE.phaseAreas = saved;
        USAGE.facts.forEach((f) => { delete f.h; });
        renderUsage();
        return gone;
      });
      await page.waitForTimeout(250);
      if (!hides) fail('usage: with no tags in the join map the area select still renders');
      else note('usage: the area select leaves when the plan carries no tags');
    }
  }

  // --- D3 (v0.34): the advisory area owner ------------------------------------
  // Two read-only surfaces consume USAGE.areaOwners: a title tooltip on the
  // area select's options and an "owns:" line in the person header, joined
  // against the map's VALUES. Driven in-page, the same way the D4 hiding rule
  // and the identity check are (the fixture generator belongs to the final
  // demo step): injecting the map exercises exactly the join the
  // server-shipped one takes — _panel_state pins the shipping, panel-server
  // pins the strings, this pins the DOM.
  {
    const tags = await page.evaluate(() => {
      const t = new Set();
      for (const f of USAGE.facts) {
        ((USAGE.phaseAreas || {})[f[F.phase]] || []).forEach((x) => t.add(x));
      }
      return [...t].sort();
    });
    const who = await page.evaluate(() => {
      const t = new Set();
      for (const f of USAGE.facts) if (f[F.author] && f[F.author] !== 'unknown') t.add(f[F.author]);
      return [...t].sort()[0] || null;
    });
    if (!tags.length || !who) {
      fail('usage: the fixture carries no area tags or no author, so the owner '
         + 'surfaces cannot be driven');
    } else {
      const owned = tags[0];
      await page.evaluate(([t, a]) => {
        window.__d3Owners = USAGE.areaOwners;
        USAGE.areaOwners = { [t]: a };
        renderUsage();
      }, [owned, who]);
      await page.waitForTimeout(250);

      // 1. the tooltip: the owned tag's option carries `owner: <who>`; a tag
      // with no declared owner (and 'untagged') carries none.
      const tip = await page.evaluate((t) => {
        const sel = document.querySelector('#usage select[data-uf=area]');
        if (!sel) return null;
        const opt = [...sel.options].find((o) => o.value === t);
        const other = [...sel.options].find((o) => o.value && o.value !== t);
        return {
          title: opt ? opt.title : '',
          otherTitle: other ? other.title : '',
          hasOther: !!other,
        };
      }, owned);
      if (!tip) {
        fail('usage: the area select is gone while the owner tooltip is probed');
      } else if (tip.title !== `owner: ${who}`) {
        fail(`usage: the ${owned} option's tooltip reads "${tip.title}", `
           + `expected "owner: ${who}"`);
      } else if (tip.hasOther && tip.otherTitle) {
        fail(`usage: a tag with no declared owner carries a tooltip ("${tip.otherTitle}")`);
      } else {
        note(`usage: the ${owned} option tooltips its owner and the others stay bare`);
      }

      // 2. the owns line: filter to the owner and the person header names the
      // owned areas — data-owns is compared against a recomputation from the
      // live map, not against a copy of the renderer's output.
      await page.evaluate((a) => setF('author', a), who);
      await page.waitForTimeout(250);
      const owns = await page.evaluate(() => {
        const elx = document.querySelector('#usage [data-owns]');
        return elx ? { val: elx.getAttribute('data-owns'), text: elx.textContent } : null;
      });
      const expect = await page.evaluate((a) => Object.entries(USAGE.areaOwners || {})
        .filter(([, o]) => o === a).map(([t]) => t).sort().join(','), who);
      if (!owns) {
        fail(`usage: ${who} owns ${expect} and the person header renders no owns: line`);
      } else if (owns.val !== expect) {
        fail(`usage: the owns: line says "${owns.val}", the areaOwners map says "${expect}"`);
      } else if (!owns.text.includes('advisory')) {
        fail('usage: the owns: line does not say it is advisory');
      } else {
        note(`usage: person header owns: line matches the map (${expect}) and says advisory`);
      }
      await clear();

      // 3. an author who owns nothing gets no owns: line — the join is by
      // VALUE, not by having any owners in the map at all.
      await page.evaluate(([t, a]) => {
        USAGE.areaOwners = { [t]: a + '-someone-else' };
        renderUsage();
        setF('author', a);
      }, [owned, who]);
      await page.waitForTimeout(250);
      const bare = await page.evaluate(() => !document.querySelector('#usage [data-owns]'));
      if (!bare) fail('usage: an author who owns nothing still gets an owns: line');
      else note('usage: an author who owns nothing gets no owns: line');
      await clear();
      await page.evaluate(() => {
        USAGE.areaOwners = window.__d3Owners;
        delete window.__d3Owners;
        renderUsage();
      });
      await page.waitForTimeout(250);
    }
  }

  // --- D3 (v0.36): the tokens heatmap ----------------------------------------
  // Day-of-week x hour, derived CLIENT-side from the hourly fact timestamps,
  // inheriting the report's C3 semantics: granularity chips, prev/next
  // bounded by the data (disabled AND muted at an edge, stepping over gap
  // days), the period NAMED, and the custom range being the panel's own day
  // filter rather than a second range control. Every expected number is
  // recomputed here from USAGE.facts — the same join the renderer makes, a
  // different implementation of it.
  {
    await clear();
    const rolled = await page.evaluate(() => !!USAGE.rolled);
    const hmCount = await page.locator('#usage table.uhm').count();
    if (rolled) {
      if (hmCount) {
        fail('usage: the ledger is rolled to daily buckets and a heatmap '
           + 'rendered anyway — there is no hour left to draw');
      } else {
        note('usage: rolled ledger; the heatmap correctly stays away');
      }
    } else if (!hmCount) {
      fail('usage: hourly facts and no tokens heatmap rendered');
    } else {
      const rest = await page.evaluate(() => {
        const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
        const agg = {};
        for (const f of USAGE.facts) {
          const wd = (new Date(f[F.ts].slice(0, 10) + 'T00:00:00Z').getUTCDay() + 6) % 7;
          const k = wd + ':' + f[F.ts].slice(11, 13);
          agg[k] = (agg[k] || 0) + f[F.tokens];
        }
        const t = document.querySelector('#usage table.uhm');
        const wrap = t.closest('.uhmwrap');
        const chart = document.querySelector('#usage .chartslot');
        return {
          rows: t.querySelectorAll('tbody tr').length,
          cells: t.querySelector('tbody tr').querySelectorAll('td').length,
          peakAttr: +t.getAttribute('data-hmpeak'),
          peak: Math.max(0, ...Object.values(agg)),
          lo: days[0], hi: days[days.length - 1], nDays: days.length,
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          prevOff: document.querySelector('#usage [data-uhm=prev]').disabled,
          nextOff: document.querySelector('#usage [data-uhm=next]').disabled,
          w: wrap ? wrap.getBoundingClientRect().width : 0,
          cw: chart ? chart.getBoundingClientRect().width : 0,
        };
      });
      if (rest.rows !== 7 || rest.cells !== 24) {
        fail(`usage: the heatmap at rest draws ${rest.rows}x${rest.cells}, `
           + `want the 7x24 weekday grid`);
      } else if (rest.peakAttr !== rest.peak) {
        fail(`usage: the heatmap claims peak ${rest.peakAttr}, the facts say `
           + `${rest.peak}`);
      } else if (!rest.period.includes('All data')
                 || !rest.period.includes(rest.lo) || !rest.period.includes(rest.hi)) {
        fail(`usage: at rest the heatmap period reads "${rest.period}" — it `
           + `must name all data and the span ${rest.lo} to ${rest.hi}`);
      } else if (!rest.prevOff || !rest.nextOff) {
        fail(`usage: at all-data the arrows must both be disabled (prev `
           + `${rest.prevOff}, next ${rest.nextOff}) — there is no period to step to`);
      } else if (rest.cw && rest.w < rest.cw * 0.9) {
        fail(`usage: the heatmap is a thumbnail — ${Math.round(rest.w)}px beside `
           + `a ${Math.round(rest.cw)}px chart; it should fill the card like the `
           + `other charts`);
      } else {
        note(`usage: heatmap at rest — 7x24 grid, peak ${rest.peakAttr} matches `
           + `the facts, period "${rest.period}", arrows parked`);
      }

      // Day granularity: opens on the LAST recorded day; next is disabled AND
      // muted at the edge; prev steps to the previous day WITH data.
      await page.click('#usage [data-uhg=day]');
      await page.waitForTimeout(300);
      const day1 = await page.evaluate(() => {
        const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
        const next = document.querySelector('#usage [data-uhm=next]');
        return {
          last: days[days.length - 1], prev: days[days.length - 2] || null,
          rows: document.querySelectorAll('#usage table.uhm tbody tr').length,
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          prevOff: document.querySelector('#usage [data-uhm=prev]').disabled,
          nextOff: next.disabled,
          nextOp: parseFloat(getComputedStyle(next).opacity),
        };
      });
      if (day1.rows !== 1 || !day1.period.includes(day1.last)) {
        fail(`usage: Day granularity draws ${day1.rows} row(s) for "${day1.period}" `
           + `— want one row named ${day1.last}`);
      } else if (!day1.nextOff || !(day1.nextOp < 1)) {
        fail(`usage: at the data's edge the next arrow is disabled=${day1.nextOff} `
           + `opacity=${day1.nextOp} — it must be both inert and visibly muted`);
      } else {
        note(`usage: Day opens on ${day1.last}, next arrow parked and muted `
           + `(opacity ${day1.nextOp})`);
      }
      if (day1.prev) {
        if (day1.prevOff) {
          fail('usage: more than one recorded day and the prev arrow is disabled');
        } else {
          await page.click('#usage [data-uhm=prev]');
          await page.waitForTimeout(300);
          const day2 = await page.evaluate(() => ({
            period: document.querySelector('#usage [data-uhmperiod]').textContent,
            nextOff: document.querySelector('#usage [data-uhm=next]').disabled,
          }));
          if (!day2.period.includes(day1.prev)) {
            fail(`usage: prev stepped to "${day2.period}", want the previous `
               + `day with data (${day1.prev})`);
          } else if (day2.nextOff) {
            fail('usage: away from the edge the next arrow stays disabled');
          } else {
            note(`usage: prev steps to ${day1.prev} and next re-enables`);
          }
        }
      }

      // Month names the month; the grid aggregates back to weekday rows.
      await page.click('#usage [data-uhg=month]');
      await page.waitForTimeout(300);
      const mon = await page.evaluate(() => {
        const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
        const last = days[days.length - 1];
        const name = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November',
          'December'][+last.slice(5, 7) - 1];
        return {
          want: name + ' ' + last.slice(0, 4),
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          rows: document.querySelectorAll('#usage table.uhm tbody tr').length,
        };
      });
      if (!mon.period.includes(mon.want) || mon.rows !== 7) {
        fail(`usage: Month granularity reads "${mon.period}" with ${mon.rows} `
           + `rows — want "${mon.want}" over 7 weekday rows`);
      } else {
        note(`usage: Month names "${mon.want}" over weekday rows`);
      }

      // None of that navigation may grow a page scroll box (assertHintsFit's
      // standing rule): the wrap owns any sideways overflow.
      const hmGrow = await page.evaluate(() => ({
        dw: document.documentElement.scrollWidth,
        cw: document.documentElement.clientWidth,
      }));
      if (hmGrow.dw > hmGrow.cw + 1) {
        fail(`usage: heatmap navigation grew the page sideways `
           + `(scrollWidth ${hmGrow.dw} vs ${hmGrow.cw})`);
      } else {
        note('usage: heatmap navigation grew no page scroll box');
      }

      // The custom range IS the panel's day filter: scope to a mid..end
      // window and the heatmap's whole universe becomes that window.
      await page.click('#usage [data-uhg=all]');
      await page.waitForTimeout(200);
      const win = await page.evaluate(() => {
        const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
        const mid = days[Math.floor(days.length / 2)];
        uSetDays(mid, '');
        return { mid, end: (USAGE.counts || {}).to };
      });
      await page.waitForTimeout(300);
      const ranged = await page.evaluate(([mid, end]) => {
        const agg = {};
        for (const f of USAGE.facts) {
          const d = f[F.ts].slice(0, 10);
          if (d < mid || d > end) continue;
          const wd = (new Date(d + 'T00:00:00Z').getUTCDay() + 6) % 7;
          const k = wd + ':' + f[F.ts].slice(11, 13);
          agg[k] = (agg[k] || 0) + f[F.tokens];
        }
        const t = document.querySelector('#usage table.uhm');
        return {
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          peakAttr: t ? +t.getAttribute('data-hmpeak') : null,
          peak: Math.max(0, ...Object.values(agg)),
        };
      }, [win.mid, win.end]);
      if (!/Custom range/.test(ranged.period)
          || !ranged.period.includes(win.mid) || !ranged.period.includes(win.end)) {
        fail(`usage: with the day filter on, the heatmap period reads `
           + `"${ranged.period}" — want "Custom range" naming ${win.mid} to ${win.end}`);
      } else if (ranged.peakAttr !== ranged.peak) {
        fail(`usage: the ranged heatmap claims peak ${ranged.peakAttr}, the `
           + `facts inside ${win.mid}..${win.end} say ${ranged.peak}`);
      } else {
        note(`usage: the day filter scopes the heatmap — "${ranged.period}", `
           + `peak ${ranged.peak} matches`);
      }
      await clear();
    }
  }

  // --- CSV ------------------------------------------------------------------
  // The export is the one control here whose output leaves the browser, so its
  // row count is checked against the facts and its numbers against a spreadsheet's
  // requirements: no separators, or every sum over the column is silently wrong.
  try {
    const wait = page.waitForEvent('download', { timeout: 15000 });
    await page.click('#usage [data-ucsv]');
    const dl = await wait;
    const text = await readFile(await dl.path(), 'utf8');
    const lines = text.replace(/^\uFEFF/, '').trim().split('\r\n');
    const want = (await oracle('true')).n;
    // Structural, not substring: the borrowed regex that stood here read
    // "…-13,123,…" (a date field, then a legitimate 3-digit count) as a
    // thousands separator. Parse the record; judge only the numeric fields.
    const badNum = firstNonRawNumberLine(lines.slice(0, 201),
      ['tokens', 'costUSD', 'msgs']);
    if (lines.length !== want + 1) {
      fail(`usage: CSV has ${lines.length - 1} data rows for ${want} facts`);
    } else if (!/^ts,phase,task,model,author,agent,attr,tokens,costUSD,msgs$/.test(lines[0])) {
      fail(`usage: CSV header is "${lines[0]}"`);
    } else if (badNum) {
      fail(`usage: CSV numeric fields are not raw numbers ("${badNum}") — a `
         + 'spreadsheet reads grouped values as text and every sum over the '
         + 'column is then wrong');
    } else if (!/hourly|daily/.test(dl.suggestedFilename())) {
      fail(`usage: CSV filename "${dl.suggestedFilename()}" does not say what `
         + `resolution the rows are at`);
    } else {
      note(`usage: exported ${lines.length - 1} rows as ${dl.suggestedFilename()}`);
    }
  } catch (e) {
    fail(`usage: Export CSV produced no download (${String(e).split('\n')[0]})`);
  }
  await clear();
}

// The digits of the rendered `messages` tile — the one KPI printed as a plain
// integer, so parsing it compares an exact number with an exact number and no
// second implementation of the compact token format exists to drift.
const shownMsgs = (page) => page.evaluate(() => {
  const t = [...document.querySelectorAll('#usage .utile')]
    .find((x) => x.querySelector('.k').textContent === 'messages');
  return t ? parseInt(t.querySelector('.v').firstChild.textContent
    .replace(/\D/g, ''), 10) : null;
});

/**
 * Who the panel says you are, and the one filter that depends on that answer.
 *
 * The name in the topbar and the name in the ledger's `author` column have to be
 * one string: "my spend" compares them, so two ways of naming the same person
 * would produce a chip that silently selects nothing. This drives both ends — the
 * pill against `STATE.viewer`, and the chip against `USAGE.facts`.
 */
async function assertViewerIdentity(page) {
  const v = await page.evaluate(() => STATE.viewer || null);
  if (!v) { fail('panel: /api/state carries no viewer — the topbar cannot name you'); return; }
  const pill = await page.evaluate(() => {
    const w = document.querySelector('#who');
    if (!w) return null;
    return { hidden: w.hidden, name: (w.querySelector('b') || {}).textContent || null,
             link: !!w.querySelector('.lnk'), text: w.textContent };
  });
  if (!pill) { fail('panel: no "viewing as" pill in the topbar'); return; }
  if (pill.hidden) {
    fail('panel: the "viewing as" pill is in the DOM but hidden — the identity '
       + 'the panel writes with is not on screen');
  } else if (v.author && pill.name !== v.author) {
    fail(`panel: the topbar says "${pill.text}" but the server resolved `
       + `"${v.author}" — the name that will be written is not the name shown`);
  } else if (!v.author && !pill.link) {
    fail(`panel: no author could be resolved (mode ${v.mode}) and the pill offers `
       + `no way to the setting that decides it: "${pill.text}"`);
  } else {
    note(`panel: viewing as ${v.author || '(' + pill.text.trim() + ')'} (mode ${v.mode})`);
  }

  // The chip. This fixture's ledger carries generated author names, so the honest
  // thing to drive is the WIRING: point the viewer at an author the ledger really
  // has, and check the chip selects exactly that author's rows — measured against
  // USAGE.facts, never against the renderer's own aggregation.
  const pick = await page.evaluate(() => {
    const by = {};
    for (const f of USAGE.facts) by[f[F.author]] = (by[f[F.author]] || 0) + f[F.msgs];
    const names = Object.keys(by).filter((n) => n && n !== 'unknown');
    return names.length ? { name: names[0], msgs: by[names[0]] } : null;
  });
  if (!pick) { note('usage: the ledger records no author — my-spend cannot be driven'); return; }
  const was = await page.evaluate((name) => {
    const prev = STATE.viewer.author; STATE.viewer.author = name; renderUsage();
    return prev;
  }, pick.name);
  await page.waitForTimeout(250);
  try {
    const chip = page.locator('#usage [data-umine]');
    if (!(await chip.count())) {
      fail('usage: the viewer has a name and there is no "my spend" chip'); return;
    }
    await chip.click();
    await page.waitForTimeout(300);
    const got = await shownMsgs(page);
    const state = await page.evaluate(() => ({ author: UF.author,
      pressed: (document.querySelector('#usage [data-umine]') || {})
        .getAttribute('aria-pressed') }));
    if (got !== pick.msgs) {
      fail(`usage: "my spend" shows ${got} messages, but ${pick.name}'s rows carry `
         + `${pick.msgs}`);
    } else if (state.author !== pick.name || state.pressed !== 'true') {
      fail(`usage: "my spend" filtered to "${state.author}" and reports `
         + `aria-pressed=${state.pressed}`);
    } else {
      note(`usage: "my spend" -> ${pick.msgs} messages for ${pick.name}, pressed`);
      // A toggle, not a one-way door: the same chip is the way back.
      await chip.click();
      await page.waitForTimeout(300);
      if (await page.evaluate(() => UF.author) !== '') {
        fail('usage: pressing "my spend" a second time did not lift the filter');
      }
    }
  } finally {
    await page.evaluate((prev) => {
      STATE.viewer.author = prev; clearAll();
    }, was);
    await page.waitForTimeout(200);
  }
}

/**
 * The confirm dialog, with more than one row in it.
 *
 * assertConfirmFlowWorks below proves the flow, and it does so with a single edit
 * because "the dialog lists exactly this one change" is the strongest form of that
 * assertion. A picture of a one-row dialog, though, does not show what the feature
 * is for — a list you read before you agree to it. So this makes three edits, takes
 * the shot and throws them away again through the panel's own Discard, which leaves
 * the fixture exactly as it was found; the check that follows opens with "a freshly
 * rendered panel is clean", so anything left behind here is named there rather than
 * quietly changing what a later assertion measures.
 *
 * It carries its own assertion for the same reason the report's filters shot does:
 * under --check nothing is written, and an unasserted capture step is a step that
 * can only be wrong in a file nobody diffs.
 */
async function captureConfirmDialog(page) {
  const inputs = page.locator('#comp tr.task .tmodel input');
  const n = Math.min(3, await inputs.count());
  if (n < 2) { fail('composition: fewer than two task rows to edit for the confirm shot'); return; }
  for (let i = 0; i < n; i++) {
    const box = inputs.nth(i);
    const was = await box.inputValue();
    await box.fill(was === 'opus' ? 'sonnet' : 'opus');
  }
  await page.waitForTimeout(200);
  await page.locator('#comp').getByRole('button', { name: 'Save composition' }).click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')].length);
  if (rows !== n) {
    fail(`composition: ${n} edits produced a dialog listing ${rows} row(s)`);
  } else {
    note(`composition: ${n} edits -> a dialog listing ${rows} rows`);
  }
  // Reaching Save scrolled to it, which is past a thousand task rows: the shot
  // would show a dialog about P1.1 over a table of P50.x. The dialog is modal and
  // stays put, so put the rows it is talking about back behind it.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await shot(page, 'panel-confirm', { dialog: true });
  await page.locator('dialog.confirm [data-cfcancel]').click();
  await page.waitForTimeout(200);

  // Discard is itself a confirm — a control that throws work away is not one click.
  await page.locator('#comp [data-discard=comp]').click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);
  const dirty = await page.evaluate(() => editRows('comp').length);
  if (dirty !== 0) {
    fail(`composition: Discard left ${dirty} unsaved change(s) behind the confirm shot`);
  }
}

/**
 * The guard for F4's class: a fixture must not be an assignment to state the
 * panel itself rewrites on a timer.
 *
 * F4 was one such assignment, racing a 5s poll — a check that failed once in a
 * month of CI and passed on every rerun, which is the shape that gets learned as
 * "just flaky" and then waves a real regression through. The rule is: anything the
 * poll owns is installed at its ENDPOINT (page.route), where every later poll
 * re-serves it, and never written into the page.
 *
 * The names are read out of the poll itself rather than listed here, so a second
 * polled global is covered the day someone adds one — the same reason the Settings
 * coverage check derives its expected paths from validate-config's own key sets.
 */
function assertNoHandAssignedPolledState() {
  const src = readFileSync(path.join(SCRIPTS, 'ui', 'panel.js'), 'utf8');
  const at = src.indexOf('async function pollRunStatus');
  if (at < 0) {
    fail('panel: pollRunStatus is gone from panel.js — the polled-state guard is '
       + 'reading a function that no longer exists and can no longer protect '
       + 'anything');
    return;
  }
  const body = src.slice(at, src.indexOf('\n}', at));
  // {1,}, not {2,}: the poll owns the two-letter FP as well as RUNSTATUS, and a
  // three-character minimum silently waved every hand-write of FP through.
  const owned = [...new Set([...body.matchAll(/(?:^|[;{\s])([A-Z][A-Z0-9_]{1,})\s*=[^=]/g)]
    .map((m) => m[1]))];
  if (!owned.length) {
    fail('panel: the run-status poll assigns nothing, so the polled-state guard '
       + 'has no names to check — it would pass whatever this file did');
    return;
  }
  const me = readFileSync(fileURLToPath(import.meta.url), 'utf8');
  const bad = owned.filter((n) =>
    new RegExp(`(?:^|[;{\\s])${n}\\s*=[^=]`).test(me));
  if (bad.length) {
    fail(`panel: this file writes ${bad.join(', ')} into the page, and the panel's `
       + `own poll rewrites ${bad.length === 1 ? 'it' : 'them'} every 5s — that is `
       + `F4: a fixture the product destroys mid-check, red once in N runs. Serve `
       + `it from ${RUNSTATUS_URL} instead`);
  } else {
    note(`panel: no fixture hand-writes polled state (${owned.join(', ')} owned by `
       + `the poll, served from the endpoint)`);
  }
}

/**
 * Confirm-before-write: the dialog, the discard, the beforeunload guard and the
 * server's echo.
 *
 * The point of every assertion here is that the panel says what it is about to do
 * and then does exactly that. So the expected rows are computed from
 * `STATE.composition` — the document the form was built from — and the value on
 * disk is read back through /api/state rather than from the form that claims to
 * have written it. A confirm dialog that lists the wrong changes is worse than no
 * dialog: it is a screenful of reassurance about values nobody checked.
 */
async function assertConfirmFlowWorks(page) {
  assertNoHandAssignedPolledState();
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(300);

  const target = await page.evaluate(() => {
    const t = ((STATE.composition || {}).tasks || [])[0];
    return t ? { id: t.id, phaseId: t.phaseId, was: t.model == null ? null : t.model } : null;
  });
  if (!target) { fail('composition: the fixture has no task to edit'); return; }
  const NEW = target.was === 'opus' ? 'haiku' : 'opus';

  // The same hand-off Overview uses: filter to the phase and open it.
  await page.evaluate((pid) => openInComp(pid), target.phaseId);
  await page.waitForTimeout(300);
  const row = page.locator('#comp tr.task').filter({
    has: page.locator('td.tid', { hasText: new RegExp(`^${esc(target.id)}$`) }) });
  if (!(await row.count())) {
    fail(`composition: no row for ${target.id} after opening ${target.phaseId}`); return;
  }
  const modelInput = row.locator('.tmodel input');
  const saveBtn = page.locator('#comp').getByRole('button', { name: 'Save composition' });
  const discardBtn = page.locator('#comp [data-discard=comp]');
  const onDisk = () => page.evaluate(async (id) => {
    const s = await api('GET', '/api/state');
    const t = (s.composition.tasks || []).find((x) => x.id === id);
    return t && t.model != null ? t.model : null;
  }, target.id);

  // --- a freshly loaded panel has nothing to confirm anywhere ----------------
  // dirtyRows() spans BOTH editable surfaces on purpose: this is the assertion
  // that catches a field which writes into the form while merely rendering, and
  // one already did — customRulesField created `guardEdits.customRules: []` on
  // sight, so every fresh panel arrived with an unsaved change nobody had made.
  // A panel that warns when nothing is at stake is a panel whose warning gets
  // clicked through.
  const clean = await page.evaluate(() => {
    const ev = new Event('beforeunload', { cancelable: true });
    dispatchEvent(ev);
    return { rows: dirtyRows(), comp: editRows('comp').length,
             blocked: ev.defaultPrevented,
             discard: (document.querySelector('#comp [data-discard=comp]') || {}).disabled };
  });
  if (clean.rows.length || clean.blocked || clean.discard !== true) {
    fail(`panel: a freshly rendered panel reports ${clean.rows.length} unsaved `
       + `change(s) ${JSON.stringify(clean.rows.slice(0, 3))}, beforeunload `
       + `blocked=${clean.blocked}, Discard disabled=${clean.discard}`);
  } else {
    note('panel: a freshly rendered panel is clean and does not block a close');
  }
  await saveBtn.click();
  await page.waitForTimeout(250);
  if (await page.locator('dialog.confirm[open]').count()) {
    fail('composition: Save opened a confirm dialog with no changes to confirm');
    await page.locator('dialog.confirm [data-cfcancel]').click();
  }

  // --- one edit: dirty, counted, and it blocks a close ------------------------
  await modelInput.fill(NEW);
  await page.waitForTimeout(200);
  const dirty = await page.evaluate(() => {
    const ev = new Event('beforeunload', { cancelable: true });
    dispatchEvent(ev);
    const d = document.querySelector('#comp [data-discard=comp]');
    return { rows: editRows('comp').length, blocked: ev.defaultPrevented,
             label: d ? d.textContent : null, disabled: d ? d.disabled : null };
  });
  if (dirty.rows !== 1 || !dirty.blocked) {
    fail(`composition: after one edit dirtyRows()=${dirty.rows} and beforeunload `
       + `blocked=${dirty.blocked}`);
  } else if (dirty.disabled || !/1 change\b/.test(dirty.label || '')) {
    fail(`composition: Discard reads "${dirty.label}" (disabled=${dirty.disabled}) `
       + `for one unsaved change`);
  } else {
    note(`composition: one edit -> dirty, "${dirty.label}", close is guarded`);
  }

  // --- the dialog lists that change, and Cancel writes nothing ---------------
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const listed = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim())));
  if (await page.locator('dialog.confirm .cflock').count()) {
    fail('composition: the dialog reports a lock with nothing running');
  }
  {
    const foot = await page.evaluate(() => {
      const f = document.querySelector('dialog.confirm [data-cfwho]');
      return { text: f ? f.textContent : null, who: (STATE.viewer || {}).author };
    });
    if (foot.who && !(foot.text || '').includes(foot.who)) {
      fail(`composition: the dialog does not say who the write is recorded as `
         + `(footer reads ${JSON.stringify(foot.text)}, viewer is ${foot.who})`);
    }
  }
  const wantFrom = target.was === null ? 'not set' : target.was;
  if (listed.length !== 1) {
    fail(`composition: the confirm dialog lists ${listed.length} rows for one edit`);
  } else if (listed[0][0] !== target.id || listed[0][1] !== 'model'
             || !listed[0][2].includes(wantFrom) || !listed[0][2].includes(NEW)) {
    fail(`composition: the dialog lists ${JSON.stringify(listed[0])} for `
       + `${target.id} model ${wantFrom} -> ${NEW}`);
  } else {
    note(`composition: the dialog lists exactly "${listed[0].join(' · ')}"`);
  }
  await page.locator('dialog.confirm [data-cfcancel]').click();
  await page.waitForTimeout(250);
  const afterCancel = await onDisk();
  const stillDirty = await page.evaluate(() => editRows('comp').length);
  if (afterCancel !== target.was) {
    fail(`composition: Cancel wrote anyway — ${target.id}.model is now `
       + `${JSON.stringify(afterCancel)}`);
  } else if (stillDirty !== 1) {
    fail(`composition: Cancel threw the edit away (${stillDirty} unsaved) — it is `
       + `the confirm that was declined, not the work`);
  } else {
    note('composition: Cancel wrote nothing and kept the edit');
  }

  // --- confirming writes exactly that, and the view re-reads from disk --------
  // The re-render is proved with a value this form never typed: a SECOND task in
  // the same phase is changed through the API while the form sits there, and has
  // to be showing that value once the save comes back. Checking only the field
  // that was edited proves nothing — the form already displays what you typed,
  // whether or not it ever re-read anything.
  const other = await page.evaluate((o) => {
    const t = ((STATE.composition || {}).tasks || [])
      .find((x) => x.phaseId === o.pid && x.id !== o.id);
    return t ? { id: t.id } : null;
  }, { pid: target.phaseId, id: target.id });
  const MARK = 'changed-elsewhere';
  if (other) {
    await page.evaluate(async (o) => api('PUT', '/api/composition',
      { meta: {}, phases: {}, tasks: { [o.id]: { model: o.v } } }),
    { id: other.id, v: MARK });
    await page.waitForTimeout(200);
  }
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const saved = await onDisk();
  const shownFor = (id) => page.evaluate((x) => {
    const tr = [...document.querySelectorAll('#comp tr.task')]
      .find((r) => (r.querySelector('.tid') || {}).textContent === x);
    const i = tr && tr.querySelector('.tmodel input');
    return i ? i.value : null;
  }, id);
  const after = await page.evaluate(() => ({
    dirty: editRows('comp').length,
    q: (document.querySelector('#comp input[type=search]') || {}).value,
    diff: !!document.querySelector('#comp [data-cfdiff]'),
    toast: (document.querySelector('#toast') || {}).textContent,
  }));
  after.shown = await shownFor(target.id);
  after.elsewhere = other ? await shownFor(other.id) : MARK;
  if (saved !== NEW) {
    fail(`composition: confirmed save left ${target.id}.model = ${JSON.stringify(saved)}`);
  } else if (after.dirty !== 0 || after.shown !== NEW) {
    fail(`composition: after saving the form still reports ${after.dirty} unsaved `
       + `change(s) and shows "${after.shown}"`);
  } else if (after.elsewhere !== MARK) {
    fail(`composition: ${other.id}.model was set to "${MARK}" while this form was `
       + `open and the table still shows "${after.elsewhere}" after a save — the `
       + `view is not re-read from disk, so it shows what you typed rather than `
       + `what is stored`);
  } else if (after.q !== target.phaseId) {
    fail(`composition: the post-save re-render dropped the filter (search is `
       + `"${after.q}", was "${target.phaseId}") — COMPF is not surviving it`);
  } else if (after.diff) {
    fail('composition: the server\'s applied[] disagreed with the dialog on an '
       + 'uncontested save');
  } else if (!/^Saved · 1 change/.test((after.toast || '').trim())) {
    fail(`composition: the save toast reads "${after.toast}"`);
  } else {
    note(`composition: confirmed -> "${after.toast.trim()}", filter and open row kept`);
  }

  // --- the echo earns its keep: a manifest that moved under the form ----------
  // The one case a confirm dialog makes WORSE without it — the values it listed
  // were already stale. Driven for real: edit here, write a different value to the
  // same field through the API, then confirm. The server recomputes `applied`
  // against what is actually on disk, and the mismatch has to surface.
  //
  // v0.34 lv: the panel now refreshes ITSELF when the disk stamp moves, and
  // this step writes to the manifest out-of-band on purpose — a poll landing
  // in the window would swap STATE under the exact staleness the echo exists
  // to catch, and the check would go red once in N runs (the F4 shape). So
  // the stamp is frozen at the ENDPOINT for the duration and thawed after;
  // the deferred refresh then lands on a clean form, which is the ordinary
  // case — and the echo stays the guard for a move the refresh cannot see,
  // a dialog already open (refreshes are deferred while any dialog is).
  //
  // The freeze alone is HALF the fix (F-C-1's second face, found when the
  // gate-card shot shifted the poll's phase): the saves above moved the stamp,
  // and if the client has not adopted that move yet, the first poll against
  // the frozen route sees a stamp it does not hold and refreshes anyway —
  // updating the form's own from-values and dissolving the very staleness
  // this leg exists to produce. So the hand-off is drained BEFORE the form
  // goes stale, exactly as the model-combo step opens.
  const frozenRun = await page.evaluate(() => api('GET', '/api/runstatus'));
  await page.route(RUNSTATUS_URL, (r) => r.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(frozenRun) }));
  await page.evaluate(async () => { await pollRunStatus(); await refreshFromDisk(); });
  await page.waitForTimeout(300);
  const OTHER = NEW === 'opus' ? 'sonnet' : 'opus';
  const THIRD = 'haiku-3';
  await modelInput.fill(THIRD);
  await page.waitForTimeout(200);
  await page.evaluate(async (o) => api('PUT', '/api/composition',
    { meta: {}, phases: {}, tasks: { [o.id]: { model: o.v } } }), { id: target.id, v: OTHER });
  await page.waitForTimeout(300);
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const warned = await page.evaluate(() => ({
    diff: (document.querySelector('#comp [data-cfdiff]') || {}).textContent || null,
    toast: (document.querySelector('#toast') || {}).className,
  }));
  if (!warned.diff) {
    fail(`composition: the manifest moved to "${OTHER}" under a form that listed `
       + `"${NEW}", and the save reported no disagreement — applied[] is not `
       + `being compared with what the dialog showed`);
  } else if (!/warn/.test(warned.toast || '')) {
    fail(`composition: applied[] disagreed and the toast is "${warned.toast}"`);
  } else {
    note('composition: a manifest that moved under the form is reported, not hidden');
  }
  // Thaw the stamp and let the deferred refresh land now, on a clean form,
  // so the steps below see the panel's ordinary live behaviour.
  await page.unroute(RUNSTATUS_URL);
  await page.evaluate(() => pollRunStatus());
  await page.waitForTimeout(400);

  // --- Discard puts the form back, and only after confirming -----------------
  const before = await onDisk();
  await modelInput.fill('discard-me');
  await page.waitForTimeout(200);
  await discardBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(500);
  const discarded = await page.evaluate((id) => ({
    dirty: editRows('comp').length,
    shown: (() => {
      const tr = [...document.querySelectorAll('#comp tr.task')]
        .find((r) => (r.querySelector('.tid') || {}).textContent === id);
      const i = tr && tr.querySelector('.tmodel input');
      return i ? i.value : null;
    })(),
  }), target.id);
  // Back to what is ON DISK, which is what "discard" means — not back to some
  // earlier value the form happens to remember.
  if (discarded.dirty !== 0 || discarded.shown !== (before === null ? '' : before)) {
    fail(`composition: Discard left ${discarded.dirty} unsaved change(s) and the `
       + `field reads "${discarded.shown}" for a saved value of `
       + `${JSON.stringify(before)}`);
  } else if (await onDisk() !== before) {
    fail('composition: Discard wrote to the manifest');
  } else {
    note(`composition: Discard restored the saved value ("${discarded.shown}")`);
  }

  // --- the dialog states a lock that is live NOW -----------------------------
  // The lock is fabricated rather than taken for real: it lives in a git dir this
  // generated project does not have. What is under test is that the dialog reads
  // the 5s POLL's answer — a dialog that opened saying "nothing is running"
  // because nothing was running when the tab loaded is exactly the reassurance
  // this flow must not give.
  //
  // It is installed at the ENDPOINT, and this is F4. The fixture used to be an
  // assignment to the panel's own `RUNSTATUS`, which the poll owns and rewrites
  // every five seconds — so a poll landing between the assignment and the click
  // put the real (unlocked) answer back, `cfLock` returned nothing, and the check
  // read a `.cflock` that had never been rendered. Once in ~N runs, on a machine
  // slow enough to leave the window open: CI 31434177985, green on rerun, green
  // standalone, and unreproducible for a month. Served from the endpoint the
  // fixture survives every poll, and the poll below is deliberately fired INSIDE
  // the old race window, so the flow that used to be a coin toss is now the
  // ordinary path — a check that hand-assigns polled state again goes red here
  // every time rather than once in a hundred runs.
  //
  // It also proves more than it did: the value the dialog states has now travelled
  // the poll's own fetch-and-adopt path, which is the claim the comment above
  // makes and which assigning the global never tested.
  const realRun = await page.evaluate(() => api('GET', '/api/runstatus'));
  const lockedRun = { ...realRun,
    phases: { ...(realRun.phases || {}),
      [target.phaseId]: { lock: { hostname: 'other-box', live: true }, claim: null } } };
  await page.route(RUNSTATUS_URL, (r) => r.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(lockedRun) }));
  await modelInput.fill('lock-probe');
  await page.waitForTimeout(200);
  await page.evaluate(() => pollRunStatus());
  // Bare, not `window.` — the panel declares it with `let` at top level, which
  // lands in the global lexical environment and never on `window`.
  const adopted = await page.waitForFunction((pid) => !!(RUNSTATUS
    && (RUNSTATUS.phases || {})[pid] && RUNSTATUS.phases[pid].lock),
  target.phaseId, { timeout: 5000 }).then(() => true, () => false);
  if (!adopted) {
    fail(`composition: the panel never adopted a lock on ${target.phaseId} from `
       + `/api/runstatus — the poll is not reading the endpoint, so nothing after `
       + `this is a test of the dialog`);
  }
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const lockNote = await page.evaluate(() => {
    const n = document.querySelector('dialog.confirm .cflock');
    return n ? n.textContent : null;
  });
  await page.locator('dialog.confirm [data-cfcancel]').click();
  await page.waitForTimeout(200);
  // Put the real answer back the same way it was taken away — through the poll —
  // so the tabs after this one see the server's truth rather than a global some
  // earlier step blanked.
  await page.unroute(RUNSTATUS_URL);
  await page.evaluate(() => pollRunStatus());
  await page.waitForFunction((pid) => !((RUNSTATUS || {}).phases || {})[pid]
    || !RUNSTATUS.phases[pid].lock, target.phaseId, { timeout: 5000 })
    .catch(() => {});
  await page.evaluate(() => renderComp());
  await page.waitForTimeout(300);
  if (!lockNote || !lockNote.includes(target.phaseId)) {
    fail(`composition: ${target.phaseId} is locked by another run and the confirm `
       + `dialog says ${JSON.stringify(lockNote)}`);
  } else {
    note(`composition: the dialog states the live lock on ${target.phaseId}`);
  }

  // --- Settings writes through the same flow ---------------------------------
  await page.click('.tab[data-t=guards]');
  await page.waitForSelector('#guards .savebar', { timeout: 10000 });
  const box = page.locator('#guards input[type=checkbox]').first();
  if (!(await box.count())) { fail('settings: no boolean field to drive'); return; }
  const path = await box.getAttribute('id');
  await box.click();
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const cfgRows = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim())));
  const wantPath = (path || '').replace(/^set-/, '');
  if (cfgRows.length !== 1 || cfgRows[0][0] !== 'config' || cfgRows[0][1] !== wantPath) {
    fail(`settings: toggling ${wantPath} listed ${JSON.stringify(cfgRows)}`);
  } else {
    note(`settings: the dialog lists "${cfgRows[0].join(' · ')}"`);
  }
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(700);
  const cfgSaved = await page.evaluate(async (p) => {
    const s = await api('GET', '/api/state');
    const v = p.split('.').reduce((o, k) => (o == null ? o : o[k]), s.config);
    return { value: v === undefined ? null : v,
             toast: (document.querySelector('#toast') || {}).textContent,
             dirty: editRows('guards').length };
  }, wantPath);
  if (cfgSaved.dirty !== 0 || !/^Saved · 1 change/.test((cfgSaved.toast || '').trim())) {
    fail(`settings: after saving, toast="${cfgSaved.toast}" and `
       + `${cfgSaved.dirty} change(s) still unsaved`);
  } else {
    note(`settings: ${wantPath} -> ${JSON.stringify(cfgSaved.value)}, `
       + `"${cfgSaved.toast.trim()}"`);
  }

  // --- and every one of those saves is now in the journal (v0.29) ------------
  // The saves above are the fixture: this asks whether the record of them exists,
  // holds together, and says the right thing. The oracle is what this file just
  // DID — the config path it toggled and the task it edited — never the panel's
  // own rendering of it. Before v0.29 the call site was there and the module was
  // not, so every save reported `journaled:false` and nothing said so out loud;
  // that is exactly the state this proves is over.
  const jr = await page.evaluate(async () => api('GET', '/api/journal'));
  if (!jr.available || !jr.verify) {
    fail('journal: /api/journal reports no journal on an install that ships one');
  } else if (!jr.verify.ok) {
    fail(`journal: the chain the panel itself wrote does not verify: `
       + `${JSON.stringify(jr.verify.findings)}`);
  } else if (!jr.rows.length) {
    fail('journal: the panel saved the config and the composition and the journal '
       + 'is empty — the writes are not being recorded');
  } else {
    const acts = jr.rows.map((r) => r.action);
    const newest = jr.rows[0];
    if (!acts.includes('config.write') || !acts.includes('composition.write')) {
      fail(`journal: rows are [${[...new Set(acts)].join(', ')}] — both a config `
         + `save and a composition save happened above`);
    } else if (newest.action !== 'config.write'
               || !(newest.summary || '').includes(wantPath)) {
      fail(`journal: the newest row is ${JSON.stringify(newest.action)} / `
         + `${JSON.stringify(newest.summary)}; the last save was ${wantPath}`);
    } else if (!(newest.hash && newest.prev && newest.stateHash)) {
      fail(`journal: a row with no chain on it: ${JSON.stringify(newest)}`);
    } else if ((newest.actor || {}).via !== 'panel'
               || (newest.actor || {}).author !== (await page.evaluate(
                 () => (STATE.viewer || {}).author))) {
      fail(`journal: the row's actor is ${JSON.stringify(newest.actor)}, and the `
         + `panel is showing ${JSON.stringify(await page.evaluate(
              () => (STATE.viewer || {}).author))}`);
    } else if (!/· logged/.test((cfgSaved.toast || ''))) {
      fail(`journal: the row was written and the toast never said so `
         + `("${cfgSaved.toast}") — a save that IS logged has to say it, or the `
         + `clause only ever appears when something is wrong`);
    } else {
      note(`journal: ${jr.verify.rows} row(s) chain cleanly; newest is `
         + `"${newest.summary}" by ${newest.actor.author || 'unknown'}`);
    }
  }
}

/* ---- (sk3) the three skill states — chips, filter, and the null round trip --
 *
 * v0.37 B1: `skills: null` is an explicit answer ("none applies") that stops
 * the area default; `[]`/absent is "unconsidered". The panel must keep the
 * three apart everywhere a reader looks: the chips area (an opted-out task
 * SAYS so, muted, instead of showing the same empty row), the "needs skills"
 * filter (an answered task is not a need), and the WRITE path (the "none
 * applies" control writes a real null into the manifest, and the chip's ×
 * clears it back to []). Driven through the real UI and the real save flow;
 * the on-disk oracle is /api/state, whose composition view ships the three
 * states apart on purpose (_panel_state._skills_of).
 */
async function assertSkillTriState(page) {
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(300);
  // Drain any in-flight poll hand-off before editing (the model-combo rule).
  await page.evaluate(async () => { await pollRunStatus(); await refreshFromDisk(); });
  await page.waitForTimeout(200);
  // A phase holding TWO tasks with empty skills: one becomes the opt-out, the
  // other stays [] so the filter check has both sides in one viewport.
  const pick = await page.evaluate(() => {
    const byP = {};
    ((STATE.composition || {}).tasks || []).forEach((t) => {
      (byP[t.phaseId] = byP[t.phaseId] || []).push(t);
    });
    for (const pid of Object.keys(byP)) {
      const empty = byP[pid].filter((t) => Array.isArray(t.skills) && !t.skills.length);
      if (empty.length >= 2) return { pid, optId: empty[0].id, refId: empty[1].id };
    }
    return null;
  });
  if (!pick) {
    fail('skills: the fixture has no phase with two empty-skills tasks to drive');
    return;
  }
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await page.evaluate((pid) => openInComp(pid), pick.pid);
  await page.waitForTimeout(300);
  const rowOf = (id) => page.locator('#comp tr.task').filter({
    has: page.locator('td.tid', { hasText: new RegExp(`^${esc(id)}$`) }) });
  if (!(await rowOf(pick.optId).count()) || !(await rowOf(pick.refId).count())) {
    fail(`skills: no rows for ${pick.optId}/${pick.refId} after opening ${pick.pid}`);
    return;
  }
  // --- state 1: an empty list offers the "none applies" affordance -----------
  const noneBtn = rowOf(pick.optId).locator('.tskills button.optnone');
  if (!(await noneBtn.count())) {
    fail(`skills: ${pick.optId} has empty skills and no "none applies" control — `
       + `null cannot be written from the UI`);
    return;
  }
  await noneBtn.click();
  await page.waitForTimeout(200);
  const afterClick = await page.evaluate((o) => {
    const r = [...document.querySelectorAll('#comp tr.task')].find((x) =>
      (x.querySelector('.tid') || {}).textContent === o.id);
    const c = r && r.querySelector('.tskills .chip.optout');
    return { text: c ? c.textContent : null,
             rows: editRows('comp').map((x) => x.target + ' ' + x.field) };
  }, { id: pick.optId });
  if (!/none — opted out/.test(afterClick.text || '')) {
    fail(`skills: clicking "none applies" rendered ${JSON.stringify(afterClick.text)} `
       + `— the opted-out state is not visibly distinct from an empty row`);
  } else if (!afterClick.rows.includes(pick.optId + ' skills')) {
    fail(`skills: the opt-out registered no change row `
       + `(${JSON.stringify(afterClick.rows)})`);
  } else {
    note('skills: "none applies" renders the muted opt-out chip and one change row');
  }
  // --- the needs-skills filter: an answer is not a need -----------------------
  const needsBtn = page.locator('#comp').getByRole('button', { name: 'needs skills' });
  await needsBtn.click();
  await page.waitForTimeout(250);
  const vis = await page.evaluate((o) => {
    const st = (id) => {
      const r = [...document.querySelectorAll('#comp tr.task')].find((x) =>
        (x.querySelector('.tid') || {}).textContent === id);
      return r ? r.style.display !== 'none' : null;
    };
    return { opt: st(o.opt), ref: st(o.ref) };
  }, { opt: pick.optId, ref: pick.refId });
  await needsBtn.click();       // filter off again
  await page.waitForTimeout(200);
  if (vis.opt !== false || vis.ref !== true) {
    fail(`skills: with "needs skills" on, the opted-out task shows=${vis.opt} and `
       + `the []-task shows=${vis.ref} — null is being counted as a need (or the `
       + `real need dropped)`);
  } else {
    note('skills: "needs skills" keeps the []-task and drops the opted-out one');
  }
  // --- save: the dialog names the answer, the file holds a real null ----------
  const saveBtn = page.locator('#comp').getByRole('button', { name: 'Save composition' });
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const dlg = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim())));
  const skRow = dlg.find((r) => r[1] === 'skills');
  if (!skRow || !/none — opted out \(null\)/.test(skRow[2] || '')) {
    fail(`skills: the confirm dialog lists ${JSON.stringify(dlg)} — null must read `
       + `as the opt-out, not as "not set"`);
  }
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const onDisk = await page.evaluate(async (id) => {
    const s = await api('GET', '/api/state');
    const t = (s.composition.tasks || []).find((x) => x.id === id);
    return t ? (t.skills === null ? 'null' : JSON.stringify(t.skills)) : 'missing';
  }, pick.optId);
  const shown = await page.evaluate((id) => {
    const r = [...document.querySelectorAll('#comp tr.task')].find((x) =>
      (x.querySelector('.tid') || {}).textContent === id);
    return { optout: !!(r && r.querySelector('.tskills .chip.optout')),
             dirty: editRows('comp').length };
  }, pick.optId);
  if (onDisk !== 'null') {
    fail(`skills: after saving the opt-out, ${pick.optId}.skills on disk is `
       + `${onDisk} — null did not round-trip through the save`);
  } else if (!shown.optout || shown.dirty !== 0) {
    fail(`skills: the saved opt-out re-rendered as optout=${shown.optout} with `
       + `${shown.dirty} dirty row(s) — the state does not survive the disk round trip`);
  } else {
    note(`skills: ${pick.optId}.skills saved as null and re-read as the opt-out chip`);
  }
  // --- and back: the chip's × clears the answer to [] -------------------------
  await rowOf(pick.optId).locator('.tskills .chip.optout button').click();
  await page.waitForTimeout(200);
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const back = await page.evaluate(async (id) => {
    const s = await api('GET', '/api/state');
    const t = (s.composition.tasks || []).find((x) => x.id === id);
    return t && Array.isArray(t.skills) && t.skills.length === 0;
  }, pick.optId);
  if (!back) {
    fail(`skills: clearing the opt-out did not write [] back for ${pick.optId}`);
  } else {
    note('skills: the opt-out clears back to [] through the same save flow');
  }
  // --- the inventory hint (v0.37 B3): a name discovery does not know ----------
  // Injected rather than relied on: the fixture pool's names are real public
  // skills that may exist on the machine running this, and a hint that depends
  // on what someone has installed is exactly the flake F4 forbids.
  const hint = await page.evaluate(() => {
    if (!REG.skills || !REG.skills.length) return 'no-inventory';
    const t = (STATE.composition.tasks || []).find((x) => Array.isArray(x.skills));
    if (!t) return 'no-task';
    t.skills = (t.skills || []).concat('0-no-such-skill-probe');
    renderComp();
    const seen = !!document.querySelector('#comp [data-skhint="0-no-such-skill-probe"]');
    t.skills = t.skills.filter((s) => s !== '0-no-such-skill-probe');
    renderComp();
    const gone = !document.querySelector('#comp [data-skhint="0-no-such-skill-probe"]');
    return { seen, gone };
  });
  if (hint === 'no-inventory') {
    note('skills: discovery found no skills on this machine — the inventory-hint '
       + 'leg is skipped (the hint is silent by design with nothing to compare)');
  } else if (hint === 'no-task') {
    fail('skills: no task row to hang the inventory-hint probe on');
  } else if (!hint.seen || !hint.gone) {
    fail(`skills: a manifest-only skill name drew hint=${hint.seen} and cleanup `
       + `left it=${!hint.gone} — the skillHints note is not tracking the manifest`);
  } else {
    note('skills: a manifest-only name draws the "discovery knows no such skill" '
       + 'note, and leaves with it');
  }
}

/**
 * No shutter photographs a toast.
 *
 * The panel's toast is a 2.6-second banner across the bottom of the viewport, and
 * it has now been committed twice: once across the dark shot (an export saying
 * "2132 row(s) exported"), and once across Overview ("discarded — the table is back
 * to the saved manifest", pinned over phase P7 by a capture step added below). Both
 * times the fix was to move the step that raised it, which fixes the instance and
 * leaves the trap set for the next person. The rule belongs where every capture
 * passes: wait for it, and say so if it will not go.
 */
async function noToast(page, label) {
  const showing = await page.evaluate(() => {
    const t = document.querySelector('#toast');
    return !!t && t.classList.contains('show');
  });
  if (!showing) return;                       // the report has no toast at all
  try {
    await page.waitForFunction(() => {
      const t = document.querySelector('#toast');
      return !t || !t.classList.contains('show');
    }, null, { timeout: 6000 });
    await page.waitForTimeout(300);           // ...and then the fade out
    note(`${label}: waited for a toast to clear before capturing`);
  } catch {
    const text = await page.evaluate(() =>
      ((document.querySelector('#toast') || {}).textContent || '').trim());
    fail(`${label}: a toast reading "${text}" is still on screen — this capture `
       + `would pin a transient banner across a committed screenshot`);
  }
}

/* ---- v0.34 C1 (cs): combo search — the footer count and the keyboard rail --
 *
 * Every count is recomputed in-page from the same data the combo reads
 * (USAGE.facts), never from the menu's own rendering. Description search is
 * asserted only on the policy fixture's controlled registry (below), where
 * every skill and its description are written by this file — a real machine's
 * discovery is never asserted numerically.
 */
async function assertComboSearchCount(page) {
  await page.click('.tab[data-t=usage]');
  await page.waitForTimeout(400);
  const want = await page.evaluate(() => {
    const tasks = [...new Set(USAGE.facts.map((f) => f[F.task]).filter(Boolean))];
    return { total: tasks.length, shown: Math.min(60, tasks.length),
             more: Math.max(0, tasks.length - 60) };
  });
  if (want.total <= 60) {
    fail(`usage: the fixture ledger carries only ${want.total} distinct tasks — `
       + `the combo's overflow footer cannot exist here and this check is blind`);
    return;
  }
  const inp = page.locator('#usage input[aria-label="filter by task"]');
  if (!(await inp.count())) { fail('usage: no task filter combo'); return; }
  await inp.click();
  await page.waitForTimeout(250);
  const menu = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    if (!m) return null;
    const r = m.getBoundingClientRect();
    return { items: m.querySelectorAll('.combo-it').length,
             foot: (m.querySelector('.combo-more') || {}).textContent || null,
             fixed: getComputedStyle(m).position,
             inView: r.left >= -1 && r.top >= -1
               && r.right <= document.documentElement.clientWidth + 1
               && r.bottom <= innerHeight + 1 };
  });
  if (!menu) { fail('usage: focusing the task combo opened no menu'); return; }
  if (menu.items !== want.shown || !menu.foot
      || !menu.foot.includes(`${want.more} more`)) {
    fail(`usage: the task combo lists ${menu.items} of ${want.total} rows with `
       + `footer ${JSON.stringify(menu.foot)} — expected ${want.shown} rows and `
       + `a "…${want.more} more" footer counted BEFORE the slice`);
  } else if (menu.fixed !== 'fixed' || !menu.inView) {
    fail(`usage: the combo menu is position:${menu.fixed}, inView=${menu.inView} `
       + `— a menu clipped by its host's frame is the defect the fixed `
       + `placement exists to remove`);
  } else {
    note(`usage: task combo lists 60 of ${want.total} + "…${want.more} more", `
       + `fixed and inside the viewport`);
  }
  // The footer must be unreachable by keyboard: with 60 choosable rows, 61
  // ArrowDowns pin the highlight to the LAST choosable row, never the footer.
  for (let i = 0; i < 61; i++) await page.keyboard.press('ArrowDown');
  await page.waitForTimeout(150);
  const nav = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    const act = m && m.querySelector('.combo-it.active');
    const items = m ? [...m.querySelectorAll('.combo-it')] : [];
    return { active: !!act, last: !!act && act === items[items.length - 1],
             footActive: !!(m && m.querySelector('.combo-more.active')) };
  });
  if (!nav.active || nav.footActive || !nav.last) {
    fail(`usage: 61 ArrowDowns left active=${nav.active}, footer-active=`
       + `${nav.footActive}, on-last-choosable=${nav.last} — the footer must `
       + `stay outside the keyboard rail`);
  } else {
    note('usage: keyboard nav stops on the last choosable row; the footer is '
       + 'not reachable');
  }
  await page.keyboard.press('Escape');
  await page.evaluate(() => clearAll());
  await page.waitForTimeout(200);
}

/** cs, second half: description search, on the policy fixture's own registry. */
async function assertComboDescriptionSearch(page) {
  // 'behaviour' appears in exactly one skill DESCRIPTION (code-simplifier's)
  // and in no skill name — the oracle is recomputed from REG in-page, so a
  // fixture edit re-aims this check instead of silently blinding it.
  const term = 'behaviour';
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(200);
  const want = await page.evaluate((t) =>
    REG.skills.filter((s) => (s.name + ' ' + (s.description || '') + ' '
      + (s.source || '')).toLowerCase().includes(t)).map((s) => s.name), term);
  if (want.length !== 1 || want[0].toLowerCase().includes(term)) {
    fail(`policy: the fixture registry no longer has exactly one description-`
       + `only match for "${term}" (${JSON.stringify(want)}) — re-aim the oracle`);
    return;
  }
  const inp = page.locator('#comp input[placeholder^="search a skill"]').first();
  await inp.click();
  await inp.fill(term);
  await page.waitForTimeout(300);
  const got = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    return m ? [...m.querySelectorAll('.combo-n')].map((n) => n.textContent) : [];
  });
  if (got.length !== 1 || got[0] !== want[0]) {
    fail(`policy: searching skills for "${term}" listed ${JSON.stringify(got)}, `
       + `expected ${JSON.stringify(want)} — the combo is not reading descriptions`);
  } else {
    note(`policy: description search "${term}" -> ${got[0]} (its name carries `
       + `no match)`);
  }
  // renderComp resets the patch this typing created — leave the form clean.
  await page.keyboard.press('Escape');
  await page.evaluate(() => renderComp());
  await page.waitForTimeout(200);
}

/* ---- v0.34 C2 (mc): the model combo's three sources -------------------------
 *
 * The ledger-only case is the load-bearing one — a model only the ledger knows
 * is what a typo'd manifest model looks like from the other side — and every
 * model in the generated ledger is also a default rate-table key, so a
 * ledger-only row is INJECTED into the page's own USAGE.facts, computed back
 * from those same facts, and removed. In-page data is still data a refresh
 * REPLACES: USAGE is refetched whenever the disk stamp moves, and the
 * confirm-flow checks just moved it (saves to the manifest and its config) —
 * so a refetch landing between the injection and the menu swapped USAGE and
 * erased the probe, red once in ~10 runs (F-C-1, the F4 shape). The endpoint
 * is therefore frozen for the step's duration, pending refreshes are drained
 * before the probe goes in, and the race window is then driven ON PURPOSE —
 * a real stamp move plus a poll — so a lost freeze goes red every run rather
 * than once in N.
 */
async function assertModelCombo(page, project) {
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(200);
  // Freeze the poll's endpoint for the whole step (the F4 rule, the same
  // page.route the stale-echo and lock legs use): frozen, every mid-step poll
  // re-serves the same stamp, and the refetch that would swap USAGE cannot
  // start.
  const frozen = await page.evaluate(() => api('GET', '/api/runstatus'));
  await page.route(RUNSTATUS_URL, (r) => r.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(frozen) }));
  // Drain what is already in motion: pollRunStatus fires refreshFromDisk
  // WITHOUT awaiting it, so a poll that landed a moment ago may be swapping
  // USAGE right now. One awaited poll adopts the frozen stamp through the
  // product's own hand-off (never a hand-write of polled state — the guard
  // above now covers two-letter names too), then one awaited refresh runs to
  // completion behind it; after that, the injection below cannot be overtaken
  // by a refetch that started before the freeze.
  await page.evaluate(async () => { await pollRunStatus(); await refreshFromDisk(); });
  await page.waitForTimeout(300);
  const LONLY = 'claude-ledger-only-probe';
  const pre = await page.evaluate((name) => {
    const f = [];
    f[F.ts] = (USAGE.facts[0] || [])[F.ts] || '2026-04-01T09';
    f[F.phase] = '--'; f[F.task] = '--'; f[F.model] = name;
    f[F.author] = 'probe@example.com'; f[F.agent] = 'orchestrator';
    f[F.attr] = 'unattributed'; f[F.tokens] = 12345; f[F.cost] = 0; f[F.msgs] = 1;
    USAGE.facts.push(f);
    MITEMS = null;
    const items = modelItems();
    return {
      sources: [...new Set(items.map((it) => it.source))].sort(),
      probe: items.find((it) => it.name === name) || null,
      aManifest: (items.find((it) => it.source === 'manifest') || {}).name || null,
    };
  }, LONLY);
  if (JSON.stringify(pre.sources) !== JSON.stringify(['ledger', 'manifest', 'rates'])) {
    fail(`composition: modelItems() carries sources ${JSON.stringify(pre.sources)} `
       + `— expected all three of ledger/manifest/rates on this fixture`);
  }
  if (!pre.probe || pre.probe.source !== 'ledger'
      || !/tokens in this ledger/.test(pre.probe.description || '')) {
    fail(`composition: a ledger-only model resolves to `
       + `${JSON.stringify(pre.probe)} — expected source "ledger" with its `
       + `token count as the description`);
  }
  // The old race, now driven on purpose (the lock-dialog precedent): the disk
  // stamp moves for real — a byte-identical rewrite of the fixture's config
  // plus a newline, so the JSON is untouched but (mtime, size) is not — and a
  // poll fires inside the injection->menu window. Against the frozen endpoint
  // the poll re-serves the frozen stamp and nothing refetches; remove the
  // freeze and this goes red every run instead of once in ~10.
  const cfgPath = path.join(project, '.claude', 'audit.config.json');
  writeFileSync(cfgPath, readFileSync(cfgPath, 'utf8') + '\n');
  await page.evaluate(() => pollRunStatus());
  await page.waitForTimeout(400);
  const held = await page.evaluate((name) =>
    USAGE.facts.some((f) => f[F.model] === name), LONLY);
  if (!held) {
    fail('composition: the ledger-only probe vanished from USAGE.facts before '
       + 'the menu opened — a mid-step refetch swapped USAGE under the check '
       + '(F-C-1); the runstatus freeze is not holding');
  }
  // Open a real task-model combo and find the probe on screen, un-clipped.
  const pid = await page.evaluate(() =>
    ((STATE.composition || {}).tasks[0] || {}).phaseId);
  await page.evaluate((p) => openInComp(p), pid);
  await page.waitForTimeout(300);
  const box = page.locator('#comp tr.task .tmodel input').first();
  await box.click();
  await box.fill('ledger-only');
  await page.waitForTimeout(250);
  const seen = await page.evaluate((name) => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    if (!m) return null;
    const it = [...m.querySelectorAll('.combo-it')].find((x) =>
      (x.querySelector('.combo-n') || {}).textContent === name);
    if (!it) return { found: false };
    const r = it.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + 6, (r.top + r.bottom) / 2);
    return { found: true,
             badge: (it.querySelector('.src.badge') || {}).textContent || null,
             clickable: it === hit || it.contains(hit) };
  }, LONLY);
  if (!seen || !seen.found) {
    fail(`composition: typing "ledger-only" into a task-model combo does not `
       + `list the ledger-only model (${JSON.stringify(seen)})`);
  } else if (seen.badge !== 'ledger' || !seen.clickable) {
    fail(`composition: the ledger-only row wears badge ${JSON.stringify(seen.badge)} `
       + `and clickable=${seen.clickable} — a row the table's frame clips is a `
       + `row nobody can choose`);
  } else {
    note('composition: a ledger-only model is listed with its ledger badge, '
       + 'un-clipped by the table frame');
  }
  // Choosing from the review combo must not toggle the phase row it rides on
  // (the STOP moved to the wrapper), and the choice must land in the form's
  // own patch. The oracle is a LEAK COUNTER, not the row's open state: a comp
  // filter force-opens phases and a propagated click can double-toggle a row
  // back open, so "still open afterwards" was provably green under sabotage.
  // A delegated listener on #comp counts clicks that REACH a phase row —
  // with the wrapper's stop in place, both halves of the interaction (the
  // input click and the menu click) must leave it at zero.
  await page.keyboard.press('Escape');
  // No quiesce needed here: the endpoint has been frozen since the top of the
  // step, so a poll cannot start the refresh that would blow away the open
  // menu mid-leg.
  await page.evaluate(() => { COMPF.q = ''; COMPF.status = ''; COMPF.needs = false;
    if (COMPF.apply) COMPF.apply(); });
  await page.waitForTimeout(250);
  await page.evaluate(() => {
    window.__phaseClicks = 0;
    document.getElementById('comp').addEventListener('click', (ev) => {
      if (ev.target.closest && ev.target.closest('tr.phase')) window.__phaseClicks++;
    });
  });
  const rev = await page.locator('#comp tr.phase .comp-review input').first()
    .elementHandle();
  if (!rev) {
    fail('composition: no review-model input to drive the combo on');
  } else {
    await rev.click();
    await page.waitForTimeout(250);
    const pick = page.locator('.combo-menu:not(.hidden) .combo-it').first();
    if (!(await pick.count())) {
      fail('composition: focusing the review-model input opened no menu');
    } else {
      const name = await pick.locator('.combo-n').textContent();
      await pick.click();
      await page.waitForTimeout(250);
      const after = await page.evaluate(() => ({
        leaks: window.__phaseClicks,
        rows: editRows('comp').map((r) => r.field),
      }));
      after.value = await rev.evaluate((n) => n.value);
      if (after.leaks) {
        fail(`composition: ${after.leaks} click(s) from inside the review combo `
           + `reached the phase row — the stopPropagation is not on the wrapper, `
           + `so choosing a model also toggles the phase under the menu`);
      } else if (after.value !== name || !after.rows.includes('review model')) {
        fail(`composition: the menu choice "${name}" landed as `
           + `${JSON.stringify(after.value)} with change rows `
           + `${JSON.stringify(after.rows)} — onChoose is not writing the patch`);
      } else {
        note(`composition: review combo chose "${name}" — zero clicks leaked to `
           + `the phase row, and the change registered`);
      }
    }
  }
  // Put everything back: the injected fact out, the typed patch dropped.
  await page.evaluate(() => {
    USAGE.facts.pop(); MITEMS = null; renderComp();
  });
  // Thaw the stamp the same way the confirm-flow legs do. The poll now sees
  // the move this step made on purpose, and the deferred refresh lands here,
  // on a clean form, before the next check begins.
  await page.unroute(RUNSTATUS_URL);
  await page.evaluate(() => pollRunStatus());
  await page.waitForTimeout(400);
}

/* ---- (wn) the why-note beside a phase whose rows all read done --------------
 *
 * A real state that reads like a contradiction: every task done, badge still
 * "In progress", because sign-off is part of the phase — and on a live repo it
 * DID read as one. The note names the reason where the eye trips on it. Driven
 * through renderComp() with an injected composition, both legs: the note must
 * be earned by ALL tasks being done, and must leave when one is not.
 */
async function assertPhaseWhyNote(page) {
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  // Freeze the poll for the step — an untimely refetch would swap STATE under
  // the injection (the F-C-1 class), and the injected phase with it.
  const frozen = await page.evaluate(() => api('GET', '/api/runstatus'));
  await page.route(RUNSTATUS_URL, (r) => r.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(frozen) }));
  await page.evaluate(async () => { await pollRunStatus(); await refreshFromDisk(); });
  await page.waitForTimeout(300);
  const got = await page.evaluate(() => {
    const saved = JSON.stringify(STATE.composition);
    const comp = STATE.composition;
    const ph = comp.phases[0];
    ph.status = 'in_progress';
    const mine = comp.tasks.filter((t) => t.phaseId === ph.id);
    mine.forEach((t) => { t.status = 'done'; });
    renderComp();
    const noteOf = () => {
      const row = [...document.querySelectorAll('#comp tr.phase')]
        .find((r) => (r.textContent || '').includes(ph.id));
      const n = row && row.querySelector('.whynote');
      return n ? n.textContent : null;
    };
    const earned = noteOf();
    if (mine[0]) mine[0].status = 'in_progress';
    renderComp();
    const unearned = noteOf();
    STATE.composition = JSON.parse(saved);
    renderComp();
    return { earned, unearned, tasks: mine.length };
  });
  if (!got.tasks) {
    fail('composition: the fixture\'s first phase has no tasks to drive the '
       + 'why-note legs on');
  } else if (!got.earned || !/awaiting sign-off/.test(got.earned)) {
    fail(`composition: a phase with every task done and status in_progress `
       + `carries no why-note (${JSON.stringify(got.earned)}) — the badge reads `
       + `like a contradiction with nothing naming the sign-off`);
  } else if (got.unearned) {
    fail('composition: the why-note stays up while a task is still running — '
       + 'it must be earned by ALL tasks being done, not decorate the badge');
  } else {
    note('composition: the awaiting-sign-off note appears exactly when every '
       + 'task is done and the phase is not');
  }
  await page.unroute(RUNSTATUS_URL);
  await page.evaluate(() => pollRunStatus());
  await page.waitForTimeout(300);
}

/* ---- v0.34 C3 (sv): the save-result card's lifecycle ------------------------
 *
 * Success card up after a landed save and GONE after its 5s clock; refusal
 * card up after a refused save, still there past that same deadline, and
 * dismissed by its own ×. The bad regex is decided by the SERVER's engine —
 * '(' fails Python's re, which is the one the hook uses.
 */
async function assertSaveNoteLifecycle(page) {
  await page.click('.tab[data-t=guards]');
  await page.waitForSelector('#guards .savebar', { timeout: 10000 });
  const rex = page.locator('#set-secretPatterns\\.extra input');
  if (!(await rex.count())) { fail('settings: no secretPatterns.extra editor'); return; }
  await rex.click();
  await rex.fill('(');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(700);
  const err = await page.evaluate(() => {
    const c = document.querySelector('#guards .findings-slot .findings.err');
    return c ? { title: (c.querySelector('b') || {}).textContent || '',
                 body: (c.querySelector('.fbody') || {}).textContent || '',
                 close: !!c.querySelector('[data-notex]') } : null;
  });
  if (!err || !/nothing was written/.test(err.title) || !err.close || !err.body) {
    fail(`settings: a refused save drew ${JSON.stringify(err)} — expected a `
       + `bold title, the findings body and a dismiss button`);
  }
  // The refusal must outlive the success card's own deadline — that is the
  // "no timer on this branch" half of the design.
  await page.waitForTimeout(5600);
  if (!(await page.evaluate(() =>
    !!document.querySelector('#guards .findings-slot .findings.err')))) {
    fail('settings: the refusal card timed itself out — a refusal has to '
       + 'outlive a glance away');
  } else {
    await page.locator('#guards [data-notex]').click();
    await page.waitForTimeout(200);
    if (await page.evaluate(() =>
      !!document.querySelector('#guards .findings-slot .findings.err'))) {
      fail('settings: the refusal card ignored its own dismiss button');
    } else {
      note('settings: refusal card up, still up 5.6s later, closed by its ×');
    }
  }
  // Throw the refused edit away through the panel's own Discard.
  await page.locator('#guards [data-discard=guards]').click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);

  // The landed save: card up, then gone on its own clock — including across
  // the disk-stamp refresh an own save triggers (the carry keeps the node).
  const box = page.locator('#guards input[type=checkbox]').first();
  await box.click();
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(700);
  const okUp = await page.evaluate(() => {
    const c = document.querySelector('#guards .findings-slot .findings.ok');
    return c ? c.textContent : null;
  });
  if (!okUp || !okUp.includes('saved')) {
    fail(`settings: a landed save drew no success card (${JSON.stringify(okUp)})`);
  }
  await page.waitForTimeout(5600);
  const okGone = await page.evaluate(() =>
    !document.querySelector('#guards .findings-slot .findings.ok'));
  if (!okGone) {
    fail('settings: the "saved" card is still up 6.3s after the save — the '
       + 'card that never leaves is the class this lifecycle exists to end');
  } else if (okUp) {
    note('settings: "saved" card present after the save, gone on its 5s clock');
  }
  // Leave the fixture as found.
  await box.click();
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);
}

/* ---- v0.34 C4 (fp): filter persistence — reload, share link, clearAll -------
 *
 * The author is picked from USAGE.facts in-page; every survival assertion
 * compares UF/DOM state against that same pick. The share-link leg runs in a
 * NEW browser context: fresh localStorage, so what survives there survived in
 * the URL and nowhere else.
 */
async function assertFilterPersistence(page, browser, panelUrl) {
  await page.click('.tab[data-t=usage]');
  await page.waitForTimeout(300);
  await page.evaluate(() => clearAll());
  await page.waitForTimeout(200);
  const who = await page.evaluate(() => {
    const t = {};
    for (const f of USAGE.facts) t[f[F.author]] = (t[f[F.author]] || 0) + f[F.tokens];
    return Object.keys(t).filter((a) => a && a !== 'unknown')
      .sort((a, b) => t[b] - t[a])[0] || null;
  });
  if (!who) { fail('usage: no author in the ledger to persist a filter for'); return; }
  await page.evaluate((a) => setF('author', a), who);
  await page.waitForTimeout(250);
  const hash1 = await page.evaluate(() => location.hash);
  if (!hash1.startsWith('#/usage!') || !/[!&]au=/.test(hash1)) {
    fail(`usage: an author filter wrote hash "${hash1}" — expected the `
       + `'#/usage!au=…' grammar`);
  }
  // Tab routing works WITH the fragment: away and back, filter intact.
  await page.click('.tab[data-t=comp]');
  await page.waitForTimeout(250);
  const onComp = await page.evaluate(() => ({
    hash: location.hash, compShown: !document.getElementById('comp')
      .classList.contains('hidden') }));
  if (!onComp.compShown || !onComp.hash.startsWith('#/comp!')) {
    fail(`usage: switching tabs under a filter fragment gave hash `
       + `"${onComp.hash}" with comp shown=${onComp.compShown}`);
  }
  await page.click('.tab[data-t=usage]');
  await page.waitForTimeout(250);
  // The reload: chip, person header and hash all survive.
  await page.reload({ waitUntil: 'load' });
  await page.waitForSelector('.tab', { timeout: 15000 });
  await page.waitForTimeout(600);
  const back = await page.evaluate(() => ({
    author: UF.author, order: UORDER.slice(), hash: location.hash,
    chip: !!document.querySelector('#usage [data-uchip=author]'),
    person: !!document.querySelector('#usage [data-person]'),
    usageShown: !document.getElementById('usage').classList.contains('hidden'),
  }));
  if (back.author !== who || !back.chip || !back.person
      || !/[!&]au=/.test(back.hash) || !back.usageShown) {
    fail(`usage: after a reload the filter state is author=`
       + `${JSON.stringify(back.author)}, chip=${back.chip}, person header=`
       + `${back.person}, hash="${back.hash}" — the filters did not survive`);
  } else {
    note(`usage: reload kept the ${who} filter — chip, person header and hash`);
  }
  // The share link, in a NEW context: no localStorage, only the URL.
  const shareCtx = await browser.newContext({
    viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1,
    reducedMotion: 'reduce', colorScheme: 'light',
  });
  try {
    const p2 = await shareCtx.newPage();
    await p2.goto(panelUrl + '#/usage!au=' + encodeURIComponent(who),
                  { waitUntil: 'load' });
    await p2.waitForSelector('.tab', { timeout: 15000 });
    await p2.waitForTimeout(600);
    const shared = await p2.evaluate(() => ({
      author: UF.author,
      usageShown: !document.getElementById('usage').classList.contains('hidden'),
      chip: !!document.querySelector('#usage [data-uchip=author]'),
    }));
    if (shared.author !== who || !shared.usageShown || !shared.chip) {
      fail(`usage: a share link opened in a fresh context landed on author=`
         + `${JSON.stringify(shared.author)}, usage shown=${shared.usageShown}, `
         + `chip=${shared.chip} — the link is not carrying the view`);
    } else {
      note('usage: a share link reproduces the filtered view in a fresh context');
    }
  } finally {
    await shareCtx.close();
  }
  // clearAll clears the STORE and the FRAGMENT — then a reload stays clean.
  await page.evaluate(() => clearAll());
  await page.waitForTimeout(200);
  const cleared = await page.evaluate(() => ({
    hash: location.hash,
    stored: (() => { try {
      return localStorage.getItem('audit-panel-uf:' + PROJECT);
    } catch (e) { return 'unreadable'; } })(),
  }));
  if (cleared.hash.includes('!') || cleared.stored !== null) {
    fail(`usage: clearAll left hash "${cleared.hash}" and store `
       + `${JSON.stringify(cleared.stored)} — both must be gone`);
  }
  await page.reload({ waitUntil: 'load' });
  await page.waitForSelector('.tab', { timeout: 15000 });
  await page.waitForTimeout(600);
  const clean = await page.evaluate(() => ({
    author: UF.author, order: UORDER.length,
    chips: document.querySelectorAll('#usage .uchip').length }));
  if (clean.author !== '' || clean.order || clean.chips) {
    fail(`usage: after clearAll + reload the view still carries `
       + `${JSON.stringify(clean)} — cleared filters must stay cleared`);
  } else {
    note('usage: clearAll cleans the hash and the store; a reload stays clean');
  }
}

/* ---- v0.34 C5 (lv): live data — an out-of-band write reaches the screen -----
 *
 * The write goes to the SHARD file on disk (writeFileSync, no panel API), and
 * the panel has ≤6.5s — one 5s poll plus margin — to show it without a reload.
 * Filters survive because renderUsage/renderOver re-render through the same
 * UF/COMPF state they always had; a dirty form is left alone and says why.
 */
async function assertLiveData(page, project) {
  const pid = await page.evaluate(() =>
    ((STATE.composition || {}).tasks[0] || {}).phaseId);
  const who = await page.evaluate(() => {
    const t = {};
    for (const f of USAGE.facts) t[f[F.author]] = (t[f[F.author]] || 0) + f[F.tokens];
    return Object.keys(t).filter((a) => a && a !== 'unknown')
      .sort((a, b) => t[b] - t[a])[0] || null;
  });
  await page.click('.tab[data-t=usage]');
  await page.waitForTimeout(200);
  await page.evaluate((a) => setF('author', a), who);
  await page.evaluate((p) => openInComp(p), pid);
  await page.waitForTimeout(300);

  const idx = JSON.parse(readFileSync(path.join(project, 'audit-plan.json'), 'utf8'));
  const stub = (idx.phases || []).find((p) => p.id === pid);
  if (!stub || !stub.shard) {
    fail(`live: ${pid} has no shard in the fixture index — the out-of-band `
       + `write has nowhere to land`);
    return;
  }
  const shardPath = path.join(project, stub.shard);
  const mark1 = 'LIVE-PROBE-TITLE-ONE';
  const body = JSON.parse(readFileSync(shardPath, 'utf8'));
  body.title = mark1;
  writeFileSync(shardPath, JSON.stringify(body, null, 2));
  const sawIt = await page.waitForFunction((m) =>
    [...document.querySelectorAll('#over .ptitle')].some((n) => n.textContent === m)
    && [...document.querySelectorAll('#comp tr.phase strong')]
      .some((n) => n.textContent === m),
  mark1, { timeout: 6500 }).then(() => true, () => false);
  const kept = await page.evaluate(() => ({
    author: UF.author, compQ: COMPF.q,
    chip: !!document.querySelector('#usage [data-uchip=author]') }));
  if (!sawIt) {
    fail(`live: a title written straight to ${stub.shard} never reached `
       + `Overview/Composition within 6.5s — the fingerprint hand-off is not `
       + `refreshing from disk`);
  } else if (kept.author !== who || kept.compQ !== pid || !kept.chip) {
    fail(`live: the refresh reached the screen but ate the filters — author=`
       + `${JSON.stringify(kept.author)}, COMPF.q=${JSON.stringify(kept.compQ)}, `
       + `chip=${kept.chip}`);
  } else {
    note(`live: an out-of-band shard write reached Overview and Composition `
       + `in under 6.5s, filters intact`);
  }

  // The dirty leg: typed work survives the next refresh, with the notice up.
  const box = page.locator('#comp tr.task .tmodel input').first();
  await box.click();
  await box.fill('dirty-probe');
  await page.waitForTimeout(200);
  const mark2 = 'LIVE-PROBE-TITLE-TWO';
  body.title = mark2;
  writeFileSync(shardPath, JSON.stringify(body, null, 2));
  const sawOver = await page.waitForFunction((m) =>
    [...document.querySelectorAll('#over .ptitle')].some((n) => n.textContent === m),
  mark2, { timeout: 6500 }).then(() => true, () => false);
  const dirty = await page.evaluate(() => ({
    value: (document.querySelector('#comp tr.task .tmodel input') || {}).value,
    stale: !!document.querySelector('#comp [data-stale=comp]'),
    compTitle: [...document.querySelectorAll('#comp tr.phase strong')]
      .some((n) => n.textContent === 'LIVE-PROBE-TITLE-TWO'),
  }));
  if (!sawOver) {
    fail('live: with a dirty composition form, Overview never showed the '
       + 'second out-of-band write — clean views must keep refreshing');
  } else if (dirty.value !== 'dirty-probe' || !dirty.stale) {
    fail(`live: the second refresh ${dirty.value === 'dirty-probe'
      ? 'left the edit but drew no notice' : 'ATE the half-typed edit'} `
       + `(value=${JSON.stringify(dirty.value)}, notice=${dirty.stale}) — a `
       + `dirty view is left alone and told the file moved`);
  } else if (dirty.compTitle) {
    fail('live: the dirty composition table re-rendered anyway — its half-typed '
       + 'patch would have been reset with it');
  } else {
    note('live: a dirty form kept its edit through the refresh, with the '
       + 'file-moved notice up; Overview refreshed regardless');
  }
  // Leave the page clean for whatever runs after.
  await page.evaluate(() => { renderComp(); clearAll(); });
  await page.waitForTimeout(200);
}

/* ---- the plan gate card (gt, v0.34 B3) --------------------------------------
 *
 * Server truth is pinned in _panel_state (the gate block) and panel-server (the
 * card's source slice); what only a browser can prove is the LOOP: a line
 * appended to the events feed ON DISK reaches the Overview table through the
 * 5s poll, because the gate block is part of runStatusKey. The ask dialog
 * itself cannot be driven from here — the hook selftests pin the ask payload's
 * shape — so this asserts the card, the bypass indicator, and the feed's round
 * trip, each within one poll plus margin.
 */
async function assertGateCard(page, project) {
  await page.click('.tab[data-t=over]');
  await page.waitForTimeout(250);
  const card = await page.evaluate(() => {
    const c = document.getElementById('gatecard');
    if (!c) return null;
    return { tier: (c.querySelector('.st') || {}).textContent || '',
             src: (c.querySelector('.mut') || {}).textContent || '' };
  });
  if (!card) { fail('gate card: #gatecard is not in the Overview at all'); return; }
  if (!['Observe', 'Warn', 'Ask', 'Deny'].includes(card.tier) || !card.src.trim()) {
    fail(`gate card: tier/source not rendered (tier=${JSON.stringify(card.tier)}, `
       + `source=${JSON.stringify(card.src)})`);
  } else {
    note(`gate card: tier ${card.tier} — ${card.src}`);
  }

  // A synthetic event lands in the table within one poll + margin.
  const logsDir = path.join(project, '.claude', 'logs');
  mkdirSync(logsDir, { recursive: true });
  const marker = `gate-probe-${Date.now()}.ts`;
  writeFileSync(path.join(logsDir, 'plan-gate-events.jsonl'),
    JSON.stringify({ ts: '2026-08-13T00:00:00Z', event: 'deny', file: marker,
                     mode: 'deny', reason: 'browser-check probe' }) + '\n',
    { flag: 'a' });
  const sawEvent = await page.waitForFunction((m) =>
    [...document.querySelectorAll('#gatecard td')].some((n) => n.textContent === m),
  marker, { timeout: 6500 }).then(() => true, () => false);
  if (!sawEvent) {
    fail('gate card: an event appended to plan-gate-events.jsonl never reached '
       + 'the Overview table within 6.5s — the gate block is not repainting');
  } else {
    note('gate card: a fresh feed line reached the events table in under 6.5s');
  }

  // The bypass indicator follows a live slot, and leaves with it.
  const slot = path.join(project, '.claude', 'state', 'plan-bypass-shotcheck.json');
  mkdirSync(path.dirname(slot), { recursive: true });
  writeFileSync(slot, JSON.stringify({ ts: 't', reason: 'browser-check',
    armedAtEpoch: Math.floor(Date.now() / 1000) }));
  const sawArmed = await page.waitForFunction(() =>
    !!document.querySelector('#gatecard [data-bypass-armed]'),
  null, { timeout: 6500 }).then(() => true, () => false);
  rmSync(slot, { force: true });
  const armedGone = await page.waitForFunction(() =>
    !document.querySelector('#gatecard [data-bypass-armed]'),
  null, { timeout: 6500 }).then(() => true, () => false);
  if (!sawArmed) {
    fail('gate card: an armed bypass slot never lit the indicator within 6.5s');
  } else if (!armedGone) {
    fail('gate card: the indicator stayed lit after the slot was removed');
  } else {
    note('gate card: the bypass indicator follows the slot, on and off');
  }
}

/* ---- the ADO connector card (connector v2) ---------------------------------
 *
 * The fixture's manifest carries meta.ado plus one linked phase and one linked
 * task, so the card's banner must read from EVIDENCE ('linked'), never from the
 * form. The flow exercises the card's own dotted change rows and both of its
 * dialogs WITHOUT writing: Save is cancelled, Discard restores the saved draft.
 */
async function assertAdoCardWorks(page) {
  await page.click('.tab[data-t=comp]');
  await page.waitForTimeout(250);
  const st = await page.evaluate(() => {
    const b = document.querySelector('#adocard [data-adostate]');
    return b ? { state: b.getAttribute('data-adostate'),
                 text: b.textContent } : null;
  });
  if (!st) {
    fail('ado card: #adocard or its banner is not in the Composition tab');
    return;
  }
  if (st.state !== 'linked' || !/1 task/.test(st.text) || !/1 phase/.test(st.text)) {
    fail(`ado card: expected a 'linked' banner counting 1 task + 1 phase from `
       + `the fixture's links, got state=${st.state} text=${JSON.stringify(st.text)}`);
  } else {
    note(`ado card: the banner reads from manifest evidence — "${st.state}"`);
  }

  // One toggled switch = one dotted change row, counted by Discard and listed
  // by the Save dialog.
  await page.click('#ado-enabled');
  await page.waitForTimeout(250);
  const disc = await page.evaluate(() => {
    const d = document.querySelector('[data-discard=ado]');
    return d ? { text: d.textContent, disabled: d.disabled } : null;
  });
  if (!disc || disc.disabled || disc.text !== 'Discard 1 change') {
    fail(`ado card: one toggled switch should read 'Discard 1 change', got `
       + JSON.stringify(disc));
  } else {
    note('ado card: the toggle registered as exactly one unsaved change');
  }
  await page.click('#adocard .btn.primary');
  await page.waitForTimeout(250);
  const row = await page.evaluate(() => {
    const r = document.querySelector(
      'dialog.confirm[open] [data-cfrow="meta ado.enabled"]');
    return r ? r.textContent : null;
  });
  if (!row) {
    fail('ado card: the Save dialog does not list the dotted meta · ado.enabled row');
  } else {
    note('ado card: the Save dialog lists the dotted row (meta · ado.enabled)');
  }
  await page.evaluate(() =>
    document.querySelector('dialog.confirm[open] [data-cfcancel]')?.click());
  await page.waitForTimeout(250);
  await page.click('[data-discard=ado]');
  await page.waitForTimeout(250);
  await page.evaluate(() =>
    document.querySelector('dialog.confirm[open] [data-cfgo]')?.click());
  await page.waitForTimeout(350);
  const after = await page.evaluate(() => ({
    state: (document.querySelector('#adocard [data-adostate]') || {})
      .getAttribute?.('data-adostate'),
    discardDead: (document.querySelector('[data-discard=ado]') || {}).disabled,
  }));
  if (after.state !== 'linked' || !after.discardDead) {
    fail(`ado card: after Discard the card should be back to the saved manifest `
       + `(banner 'linked', Discard dead), got ${JSON.stringify(after)}`);
  } else {
    note('ado card: Discard restored the saved card; nothing was written');
  }

  // The identityMap pair editor: adding a pair renders a row; a second key
  // aimed at an ALREADY-MAPPED value raises the duplicate hint the validator
  // would warn about; Discard clears both. Nothing is saved.
  await page.evaluate(() => {
    const ki = document.querySelector('#adocard input[placeholder^="ledger identity"]');
    const vi = document.querySelector('#adocard input[placeholder^="ADO identity"]');
    ki.value = 'second@demo.example';
    vi.value = 'dev@demo-corp.example.com';   // the fixture entry's value → dup
    document.querySelector('#adocard [data-imadd]').click();
  });
  await page.waitForTimeout(250);
  const im = await page.evaluate(() => ({
    row: !!document.querySelector('#adocard [data-imrow="second@demo.example"]'),
    dup: !!document.querySelector('#adocard [data-imdup]'),
  }));
  if (!im.row || !im.dup) {
    fail(`ado card: identityMap add should render its row and, aimed at an `
       + `already-mapped value, the duplicate hint — got ${JSON.stringify(im)}`);
  } else {
    note('ado card: identityMap pair editor adds rows and flags duplicate targets');
  }
  await page.click('[data-discard=ado]');
  await page.waitForTimeout(250);
  await page.evaluate(() =>
    document.querySelector('dialog.confirm[open] [data-cfgo]')?.click());
  await page.waitForTimeout(300);
  const imAfter = await page.evaluate(() =>
    !!document.querySelector('#adocard [data-imrow="second@demo.example"]'));
  if (imAfter) {
    fail('ado card: Discard left the added identityMap row behind');
  } else {
    note('ado card: identityMap edit discarded cleanly');
  }
}

/* ---- the help drawer -------------------------------------------------------
 *
 * Every oracle here is `GET /api/help` — the payload itself, fetched inside the
 * page — and never the drawer's own output. That is the only way this proves
 * anything: the whole claim of the feature is that what you read came out of the
 * shipped schemas and out of the code that runs the rule, so a check that compared
 * the drawer with the drawer would be green for a page that invented every word.
 */
async function assertHelpDrawerWorks(page, declared) {
  const doc = await page.evaluate(() => api('GET', '/api/help'));

  // --- no ⓘ opens on an empty page -------------------------------------------
  // Through the real endpoint, path by path, the way the drawer asks. `_help`
  // asserts the same coverage against its own table; this asserts the HTTP route
  // that stands between that table and the reader.
  const unresolved = await page.evaluate(async (paths) => {
    const out = [];
    for (const p of paths) {
      const r = await api('GET', `/api/help?doc=config&path=${encodeURIComponent(p)}`);
      if (!r.found || !(r.entry || {}).description) out.push(p);
    }
    return out;
  }, declared);
  if (unresolved.length) {
    fail(`help: ${unresolved.length} setting(s) the form binds a ⓘ to resolve to no `
       + `description — the drawer opens on an empty page for: `
       + `${unresolved.slice(0, 5).join(', ')}`);
  } else {
    note(`help: all ${declared.length} bound settings resolve to schema words`);
  }

  // --- and no ⓘ promises a tooltip it does not have ---------------------------
  // The bubble's content IS the attribute, so an empty one is an empty box under
  // the cursor. Two fields reached that state the moment a ⓘ stopped needing
  // tooltip text in order to exist.
  const blankTips = await page.evaluate(() =>
    [...document.querySelectorAll('.hint')]
      .filter((h) => h.hasAttribute('data-tip') && !h.getAttribute('data-tip').trim())
      .map((h) => h.dataset.hint || '(no ref)'));
  if (blankTips.length) {
    fail(`help: ${blankTips.length} hint(s) carry an empty data-tip and draw an `
       + `empty bubble on hover: ${blankTips.slice(0, 4).join(', ')}`);
  } else {
    note('help: no hint draws an empty tooltip');
  }

  // --- one field, opened the way a reader opens it ----------------------------
  // Whichever tab the run left behind, this one is about Settings. Selected
  // rather than assumed: `#guards` is merely hidden on the other four, and a
  // click on a hidden button is a 30-second Playwright timeout whose stack reads
  // exactly like a dead panel (F7's lesson, in this harness).
  await page.click('.tab[data-t=guards]');
  await page.waitForTimeout(200);
  // trivialLineThreshold as the worked example since v0.34 B1: `enforce` lost
  // its dedicated control (the planGate select owns the gate's tier now), and
  // this field keeps every assertion meaningful — a schema sentence, a real
  // default (80; planGate's is null), microcopy, and the same gate-tiers topic.
  const opener = page.locator('#guards [data-hint="trivialLineThreshold"]').first();
  if (!(await opener.count()) || !(await opener.isVisible())) {
    fail('help: the "trivialLineThreshold" setting has no ⓘ that can be pressed '
       + '— every Settings control is supposed to carry one');
    return;
  }
  await opener.click();
  await page.waitForSelector('dialog.drawer[open]', { timeout: 10000 });
  await page.waitForTimeout(150);
  const field = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    const sec = [...d.querySelectorAll('.dsec')].map((s) => ({
      h: (s.querySelector('h3') || {}).textContent || '',
      t: s.textContent || '',
    }));
    const facts = [...d.querySelectorAll('.dfacts dt')].map((dt, i) => [
      dt.textContent, d.querySelectorAll('.dfacts dd')[i].textContent]);
    return {
      path: (d.querySelector('[data-hpath]') || {}).textContent,
      means: (sec.find((s) => s.h === 'What it means') || {}).t || '',
      panel: (sec.find((s) => s.h === 'In this panel') || {}).t || '',
      facts,
      topic: (d.querySelector('[data-htopic]') || {}).dataset?.htopic || null,
      sources: [...d.querySelectorAll('.dsrc span')].map((s) => s.textContent),
    };
  });
  const want = doc.fields.config.trivialLineThreshold;
  if (field.path !== 'trivialLineThreshold'
      || !field.means.includes(want.description)) {
    fail(`help: the drawer for "trivialLineThreshold" does not carry the `
       + `schema's own sentence (path=${JSON.stringify(field.path)}, shown=`
       + `${JSON.stringify(field.means.slice(0, 80))})`);
  } else {
    note('help: the trivialLineThreshold drawer quotes the schema verbatim');
  }
  // The default is the value the HOOKS fall back to. A drawer that showed a
  // different one would be worse than one that showed none, because "leave it
  // empty and you get this" is the whole reason it is there.
  const dflt = field.facts.find(([k]) => k === 'Default');
  if (!dflt || dflt[1] !== String(want.default)) {
    fail(`help: the drawer says the default of trivialLineThreshold is `
       + `${JSON.stringify(dflt)}, the payload says ${JSON.stringify(want.default)}`);
  } else if (!field.sources.some((s) => s === doc.schemas.config)) {
    fail(`help: the description is not attributed to ${doc.schemas.config} — a `
       + `quotation with no source is just prose`);
  } else {
    note(`help: type/default/citation shown (default ${dflt[1]}, `
       + `from ${doc.schemas.config})`);
  }
  // The panel's own microcopy is the OTHER voice, and it is labelled as such
  // rather than run together with the schema's sentence.
  const microcopy = await page.evaluate(() => HELP.trivialLineThreshold);
  if (!field.panel.includes(microcopy)) {
    fail('help: the drawer drops the panel\'s own note for trivialLineThreshold, '
       + 'which is the half that says what this form does about the setting');
  }

  // --- the concept page behind the field --------------------------------------
  if (field.topic !== want.topic) {
    fail(`help: the trivialLineThreshold drawer offers topic `
       + `${JSON.stringify(field.topic)}, the payload links it to `
       + `${JSON.stringify(want.topic)}`);
  } else {
    await page.click(`dialog.drawer [data-htopic="${want.topic}"]`);
    await page.waitForSelector(`dialog.drawer [data-htable="${want.topic}"]`,
      { timeout: 10000 });
    const shown = await page.evaluate(() => {
      const t = document.querySelector('dialog.drawer table.dtbl');
      return [...t.querySelectorAll('tbody tr')].map((r) =>
        [...r.querySelectorAll('td')].map((td) => td.textContent));
    });
    const oracle = doc.topics.find((t) => t.id === want.topic).table.rows;
    // The tier column, cell for cell. These are plan_gate_mode's own answers to
    // the hook's own three questions — a page that typed them out would read
    // identically and be a claim about nothing.
    const same = shown.length === oracle.length
      && shown.every((r, i) => r.join('|') === oracle[i].join('|'));
    if (!same) {
      fail(`help: the ${want.topic} page draws ${shown.length} rows that do not `
         + `match the ${oracle.length} the payload computed: `
         + `${JSON.stringify(shown.slice(0, 2))}`);
    } else {
      note(`help: the ${want.topic} page is the payload's own ${oracle.length} rows`);
    }
    // Back returns to the field, not to the index: a reader who drilled in to
    // check how the gate grades is still asking about the field they left.
    await page.click('dialog.drawer [data-hback]');
    await page.waitForTimeout(200);
    const back = await page.evaluate(() =>
      (document.querySelector('dialog.drawer [data-hpath]') || {}).textContent);
    if (back !== 'trivialLineThreshold') {
      fail(`help: going back from the topic landed on ${JSON.stringify(back)} `
         + `rather than the field it was opened from`);
    } else {
      note('help: back returns to the field the topic was reached from');
    }
  }

  // --- the paid half, described and not spent ---------------------------------
  const agent = await page.evaluate(() => {
    const a = document.querySelector('dialog.drawer [data-hagent]');
    // The BADGE, not the card's whole text. The agent's own description happens
    // to name its three tools in prose, so a card whose badge advertised an edit
    // tool still contained the string "Grep" and the first version of this check
    // passed against exactly that mutation.
    return a ? { name: a.dataset.hagent, text: a.textContent,
                 tools: (a.querySelector('.dtools .badge') || {}).textContent || '',
                 buttons: a.querySelectorAll('button').length } : null;
  });
  if (!doc.agent) {
    if (agent) fail('help: a guide card is drawn although the payload ships none');
  } else if (!agent || agent.name !== doc.agent.name) {
    fail(`help: the drawer does not name the ${doc.agent.name} agent`);
  } else if (!doc.agent.tools.every((t) => agent.tools.includes(t))
             || agent.tools.split('·').length !== doc.agent.tools.length) {
    fail(`help: the guide card does not name the tools the agent actually holds `
       + `(${doc.agent.tools.join(', ')}) — a card that advertises more is the one `
       + `thing reading it off the file was meant to prevent`);
  } else if (agent.buttons) {
    fail(`help: the guide card carries ${agent.buttons} button(s). It documents an `
       + `agent you invoke yourself; a control here would spend a model on a `
       + `question this drawer just answered`);
  } else if (agent.text.includes("''")) {
    fail('help: the guide card prints a YAML escape (the plugin\'\'s own README) — '
       + 'the frontmatter quote was stripped without being unescaped');
  } else {
    note(`help: the guide card names ${doc.agent.tools.join('/')}, model `
       + `${doc.agent.model}, and offers no way to spend one`);
  }

  // --- Esc, and where the focus lands -----------------------------------------
  // `box` is the other half, and it is the half no viewport-sized screenshot can
  // show: a shut dialog must occupy NOTHING. The UA hides one with
  // `dialog:not([open]){display:none}`, and an author `display` of equal
  // specificity beats it — which left a 100dvh block laid out at the end of
  // <body> once the drawer had been opened, and printed it across the bottom of
  // the full-page Overview shot. Asserted as the element's own rendered size
  // rather than as a page height, because by now this page has opened and closed
  // the drawer several times and a "before" measurement is already polluted.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  const closed = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer'),
      r = d.getBoundingClientRect();
    return { open: !!document.querySelector('dialog.drawer[open]'),
             box: Math.round(r.width) + 'x' + Math.round(r.height),
             display: getComputedStyle(d).display,
             focus: (document.activeElement && document.activeElement.dataset
               ? document.activeElement.dataset.hint : null) || null };
  });
  if (closed.box !== '0x0' || closed.display !== 'none') {
    fail(`help: a closed drawer still renders (${closed.box}, display:`
       + `${closed.display}) — it is laid out at the end of the document, which `
       + `nothing but a full-page capture would ever show`);
  } else {
    note('help: a closed drawer occupies nothing');
  }
  if (closed.open || closed.focus !== 'trivialLineThreshold') {
    fail(`help: after Esc the drawer is open=${closed.open} and focus is on `
       + `${JSON.stringify(closed.focus)} — a keyboard reader who asked what a `
       + `field means has to find their way back to it`);
  } else {
    note('help: Esc closes and hands focus back to the ⓘ that opened it');
  }

  // --- a path into a DOCUMENT, resolved by the server --------------------------
  // `usage.pricing.<model>.in` is the case the browser must not try to work out
  // for itself. Driven through the real drawer rather than the endpoint alone, so
  // what is proven is the path a reader takes.
  await page.evaluate(() =>
    openHelp({ path: 'usage.pricing.claude-opus-4-1.in', doc: 'config',
               label: 'input rate' }));
  await page.waitForSelector('dialog.drawer[open] [data-hpath]', { timeout: 10000 });
  await page.waitForTimeout(150);
  const concrete = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    return { path: (d.querySelector('[data-hpath]') || {}).textContent,
             srcs: [...d.querySelectorAll('.dsrc span')].map((s) => s.textContent),
             means: d.textContent };
  });
  const shape = doc.fields.config['usage.pricing.<name>.in'];
  if (concrete.path !== 'usage.pricing.claude-opus-4-1.in'
      || !concrete.srcs.some((s) => s === 'documented as usage.pricing.<name>.in')
      || !concrete.means.includes(shape.description)) {
    fail('help: a concrete pricing path did not resolve onto the shape that '
       + `documents it: ${JSON.stringify(concrete.srcs)}`);
  } else {
    note('help: usage.pricing.<model>.in resolves server-side onto its shape');
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);

  // --- the index lists every page the payload ships ---------------------------
  await page.click('#helpbtn');
  await page.waitForSelector('dialog.drawer[open] [data-htopic]', { timeout: 10000 });
  const index = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.drawer [data-htopic]')]
      .map((b) => [b.dataset.htopic, (b.querySelector('b') || {}).textContent]));
  const wantTopics = doc.topics.map((t) => [t.id, t.title]);
  if (JSON.stringify(index) !== JSON.stringify(wantTopics)) {
    fail(`help: the index lists ${JSON.stringify(index.map((x) => x[0]))} but the `
       + `payload ships ${JSON.stringify(wantTopics.map((x) => x[0]))}`);
  } else {
    note(`help: the index is the payload's own ${index.length} concept pages`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);

  // --- a composition lever is documented by the MANIFEST schema ---------------
  await page.click('.tab[data-t=comp]');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.click('#comp [data-hint="taskModel"]');
  await page.waitForSelector('dialog.drawer[open] [data-hpath]', { timeout: 10000 });
  const lever = await page.evaluate(() => {
    const d = document.querySelector('dialog.drawer');
    return { path: (d.querySelector('[data-hpath]') || {}).textContent,
             text: d.textContent };
  });
  const leverPath = doc.composition.taskModel;
  if (lever.path !== leverPath
      || !lever.text.includes(doc.fields.manifest[leverPath].description)) {
    fail(`help: the task model lever opened on ${JSON.stringify(lever.path)} rather `
       + `than ${leverPath}, or without the manifest schema's words`);
  } else {
    note(`help: the task model lever is explained from ${leverPath}`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);
  await page.click('.tab[data-t=guards]');
  await page.waitForTimeout(200);
}

/* ---- the policy switchboard ------------------------------------------------
 *
 * This one gets its own project AND its own HOME, which none of the other panel
 * shots need. The reason is what the tab shows: every skill, subagent and MCP
 * server the project can reach — which, run against a real machine, is a list of
 * whatever the person capturing happens to have installed. That is two problems at
 * once. The committed PNG would publish somebody's plugin inventory (the same
 * class of leak as the identity that reached four shots before it was caught, and
 * just as permanent); and the CHECKS would be asserting against a set that is
 * different on every machine and empty on a CI runner, where ~/.claude does not
 * exist. So discovery is given a home of its own, with five skills, two agents and
 * two MCP servers in it, and the fixture asserts it got exactly those before the
 * shutter opens.
 */
const POL_SKILLS = [
  ['code-review', 'Reviews a diff for correctness, reuse and test coverage.'],
  ['code-simplifier', 'Simplifies recently changed code without altering behaviour.'],
  ['db-migrations', 'Writes and checks database migrations.'],
  ['release-notes', 'Drafts release notes from the changelog.'],
  ['shell-runner', 'Runs arbitrary shell commands on the developer machine.'],
];
const POL_AGENTS = [
  ['doc-writer', 'Writes reference documentation from source.'],
  ['perf-hunter', 'Profiles a workload and reports the hot paths.'],
];
// One of audit's own, under the name the Skill tool spells it with, so the table
// has a REQUIRED row — the one row this panel refuses to let anyone deny.
const POL_PLUGIN = [
  ['skills', 'report', 'audit:report', 'Renders the audit report.'],
  ['agents', 'audit-explorer', 'audit:audit-explorer', 'Read-only subsystem auditor.'],
];
const POL_MCP = ['acme-tickets', 'vector-store'];

function writePolicyFixture(work) {
  const project = path.join(work, 'pol');
  const home = path.join(work, 'polhome');
  py([path.join(SCRIPTS, 'gen-demo-manifest.py'), project, '--phases', '6', '--tasks', '3']);
  for (const [name, description] of POL_SKILLS) {
    const dir = path.join(home, '.claude', 'skills', name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, 'SKILL.md'),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  mkdirSync(path.join(home, '.claude', 'agents'), { recursive: true });
  for (const [name, description] of POL_AGENTS) {
    writeFileSync(path.join(home, '.claude', 'agents', `${name}.md`),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  for (const [kind, file, name, description] of POL_PLUGIN) {
    const dir = kind === 'skills'
      ? path.join(home, '.claude', 'plugins', 'audit', 'skills', file)
      : path.join(home, '.claude', 'plugins', 'audit', 'agents');
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, kind === 'skills' ? 'SKILL.md' : `${file}.md`),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  writeFileSync(path.join(project, '.mcp.json'), JSON.stringify(
    { mcpServers: Object.fromEntries(POL_MCP.map((n) => [n, { command: 'x' }])) }, null, 2));
  return { project, home };
}

/** The `policy` block for the fixture, aimed at the area that is actually live. */
function policyFixtureBlock(liveArea) {
  return {
    onViolation: 'deny',
    skills: {
      default: 'deny',
      allow: ['code-*', 'release-notes', 'db-migrations'],
      deny: ['shell-runner'],
      // Scoped to the one area with work in progress, so the column that decides
      // something and the columns that do not are both on screen.
      areas: liveArea ? { [liveArea]: { deny: ['db-*'] } } : {},
    },
    agents: { deny: ['doc-writer'] },
  };
}

/**
 * The switchboard: does it show what the SERVER decided, and does a switch write
 * what the dialog said it would?
 *
 * Every oracle here is computed from `POLICY` — the JSON the page was handed, whose
 * verdicts come from `_policy.resolve`, the function the guard hook itself calls —
 * and never from the renderer. A check that reads the verdict out of the same DOM
 * it is checking proves only that a string was copied.
 */
async function assertPolicyWorks(page, statePath) {
  await page.click('.tab[data-t=policy]');
  await page.waitForSelector('#policy .card', { timeout: 15000 });
  await page.waitForTimeout(250);

  // --- a row per discovered capability, with the server's verdict on it -------
  const table = await page.evaluate(() => ({
    kind: PF.kind,
    oracle: (POLICY.resolved[PF.kind] || []).map((r) => ({
      name: r.name, verdict: r.verdict, basis: r.basis, required: r.required })),
    rendered: [...document.querySelectorAll('#policy tr[data-pcap]')].map((tr) => ({
      name: tr.dataset.pcap,
      verdict: tr.dataset.verdict,
      word: (tr.querySelector('.pv') || {}).textContent || '',
      basis: (tr.querySelector('.pbasis') || {}).textContent || '',
      locked: !!(tr.querySelector('select.prule') || {}).disabled,
      required: !!tr.querySelector('.badge.req'),
    })),
    kindCounts: [...document.querySelectorAll('#policy [data-pk]')].map((b) =>
      [b.dataset.pk, Number((b.querySelector('b') || {}).textContent || -1),
       (POLICY.resolved[b.dataset.pk] || []).length]),
  }));
  if (table.rendered.length !== table.oracle.length) {
    fail(`policy: ${table.oracle.length} ${table.kind} resolved by the server, `
       + `${table.rendered.length} rows rendered`);
  } else {
    const byName = Object.fromEntries(table.rendered.map((r) => [r.name, r]));
    const wrong = table.oracle.filter((o) => {
      const r = byName[o.name];
      return !r || r.verdict !== o.verdict
        || r.word.trim() !== (o.verdict === 'violation' ? 'Violation' : 'Allowed')
        || r.basis.trim() !== (o.basis || '').trim();
    });
    const violations = table.oracle.filter((o) => o.verdict === 'violation').length;
    if (wrong.length) {
      fail(`policy: ${wrong.length} row(s) do not show the verdict or the basis the `
         + `server computed — first: ${JSON.stringify(wrong[0])}`);
    } else if (!violations || violations === table.oracle.length) {
      fail(`policy: the fixture resolves ${violations}/${table.oracle.length} to a `
         + `violation, so this check could not tell the two apart`);
    } else {
      note(`policy: ${table.rendered.length} ${table.kind} rows, each carrying the `
         + `server's verdict and its basis (${violations} violation(s))`);
    }
  }
  const bad = table.kindCounts.filter(([, shown, want]) => shown !== want);
  if (bad.length) {
    fail(`policy: the kind pills count ${JSON.stringify(bad)} (shown vs resolved)`);
  }

  // --- audit's own components cannot be denied here ---------------------------
  const req = table.rendered.filter((r) => r.required);
  const wantReq = table.oracle.filter((o) => o.required).length;
  if (!wantReq) {
    fail('policy: the fixture discovered none of audit\'s own skills, so the '
       + '"required" row could not be checked at all');
  } else if (req.length !== wantReq || req.some((r) => !r.locked)) {
    fail(`policy: ${wantReq} required capabilit(ies), ${req.length} marked and `
       + `${req.filter((r) => r.locked).length} actually locked`);
  } else {
    note(`policy: ${wantReq} required capabilit(ies) shown locked`);
  }

  // --- area columns say which of them decides anything today ------------------
  const cols = await page.evaluate(() => ({
    oracle: (POLICY.areaInfo || []).map((a) => [a.tag, a.active]),
    rendered: [...document.querySelectorAll('#policy th.ar')].map((th) =>
      [th.firstChild.textContent, !th.classList.contains('dormant'),
       (th.querySelector('.mut') || {}).textContent]),
  }));
  const colsOk = cols.oracle.length === cols.rendered.length
    && cols.oracle.every(([tag, live], i) => cols.rendered[i][0] === tag
      && cols.rendered[i][1] === live
      && cols.rendered[i][2] === (live ? 'live' : 'dormant'));
  if (!cols.oracle.length || !cols.oracle.some(([, live]) => live)
      || !cols.oracle.some(([, live]) => !live)) {
    fail(`policy: the fixture's areas are ${JSON.stringify(cols.oracle)} — it needs `
       + `both a live and a dormant one or the column check proves nothing`);
  } else if (!colsOk) {
    fail(`policy: area columns ${JSON.stringify(cols.rendered)} do not match the `
       + `server's ${JSON.stringify(cols.oracle)}`);
  } else {
    note(`policy: ${cols.oracle.length} area columns, each naming whether it is live`);
  }

  // --- the block as written, including the patterns no switch can express -----
  const rules = await page.evaluate(() => ({
    oracle: (POLICY.rules[PF.kind] || []).map((r) =>
      `${r.scope || 'project'} ${r.list} ${r.pattern}`),
    rendered: [...document.querySelectorAll('#policy tr[data-prule]')]
      .map((tr) => tr.dataset.prule),
  }));
  if (rules.oracle.join('|') !== rules.rendered.join('|')) {
    fail(`policy: the rules table shows ${JSON.stringify(rules.rendered)} for a block `
       + `the server reads as ${JSON.stringify(rules.oracle)}`);
  } else if (!rules.oracle.some((r) => r.includes('*'))) {
    fail('policy: the fixture has no glob rule, so "a pattern is visible and '
       + 'removable" was not actually checked');
  } else {
    note(`policy: ${rules.oracle.length} rules listed as written, globs included`);
  }

  // --- one switch: dirty, counted, guarded, and the dialog says what it will do
  const subject = await page.evaluate(() => (POLICY.resolved[PF.kind] || [])
    .find((r) => !r.required && r.verdict === 'allow') || null);
  if (!subject) { fail('policy: no allowed, non-required row to deny'); return; }
  await page.selectOption(`#policy tr[data-pcap="${subject.name}"] select.prule`, 'deny');
  await page.waitForTimeout(200);
  const dirty = await page.evaluate(() => {
    const ev = new Event('beforeunload', { cancelable: true });
    dispatchEvent(ev);
    const d = document.querySelector('#policy [data-discard=policy]');
    return { rows: editRows('policy'), blocked: ev.defaultPrevented,
             label: d ? d.textContent : null, disabled: d ? d.disabled : null,
             pend: document.querySelectorAll('#policy td.pend').length };
  });
  if (dirty.rows.length !== 1 || dirty.rows[0].field !== 'policy.skills.deny'
      || !dirty.blocked || dirty.disabled || !/1 change\b/.test(dirty.label || '')
      || dirty.pend !== 1) {
    fail(`policy: one switch produced ${JSON.stringify(dirty.rows)}, beforeunload `
       + `blocked=${dirty.blocked}, Discard "${dirty.label}", ${dirty.pend} pending cell(s)`);
  } else {
    note(`policy: denying ${subject.name} -> one change row, one pending cell, `
       + `"${dirty.label}", close guarded`);
  }
  await page.locator('#policy [data-psave]').click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const listed = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim())));
  if (listed.length !== 1 || listed[0][1] !== 'policy.skills.deny'
      || !listed[0][2].includes(subject.name)) {
    fail(`policy: the dialog lists ${JSON.stringify(listed)} for one denial`);
  } else {
    note(`policy: the dialog lists "${listed[0].join(' · ')}"`);
  }
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);

  // The point of the whole flow: the file changed, and the verdict on screen is
  // the server's fresh answer about the file — not the client's guess about it.
  const after = await page.evaluate(async (name) => {
    const p = await api('GET', '/api/policy');
    const tr = document.querySelector(`#policy tr[data-pcap="${CSS.escape(name)}"]`);
    return { stored: ((p.stored || {}).skills || {}).deny || [],
             verdict: tr ? tr.dataset.verdict : null,
             basis: tr ? (tr.querySelector('.pbasis') || {}).textContent : null,
             pend: document.querySelectorAll('#policy td.pend').length,
             dirty: editRows('policy').length };
  }, subject.name);
  if (!after.stored.includes(subject.name)) {
    fail(`policy: after confirming, policy.skills.deny on disk is `
       + `${JSON.stringify(after.stored)}`);
  } else if (after.verdict !== 'violation' || !(after.basis || '').includes('deny')
             || after.pend || after.dirty) {
    fail(`policy: after saving, ${subject.name} still reads ${after.verdict} `
       + `("${after.basis}") with ${after.pend} pending cell(s) and ${after.dirty} `
       + `unsaved change(s)`);
  } else {
    note(`policy: saved -> on disk, re-read, and the row now says violation`);
  }

  // --- the promise about audit's own components, kept by the server -----------
  // The switch for a required row is disabled, which is the friendly half. This is
  // the half that holds when someone writes the rule as a pattern instead.
  await page.fill('#poladdpat', 'audit:*');
  await page.evaluate(() => {
    const sels = document.querySelectorAll('#policy .poladd select');
    sels[0].value = 'deny'; sels[1].value = '';
  });
  await page.locator('#policy [data-poladd]').click();
  await page.waitForTimeout(200);
  await page.locator('#policy [data-psave]').click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const refused = await page.evaluate(async () => {
    const p = await api('GET', '/api/policy');
    return { deny: ((p.stored || {}).skills || {}).deny || [],
             said: (document.querySelector('#policy .findings-slot .findings.err')
                    || {}).textContent || '' };
  });
  if (refused.deny.includes('audit:*')) {
    fail('policy: a rule denying audit\'s own components was written to the file');
  } else if (!/audit/i.test(refused.said)) {
    fail(`policy: the refusal did not say why — the box reads "${refused.said}"`);
  } else {
    note('policy: a deny aimed at audit\'s own components is refused, in the '
       + 'validator\'s words');
  }
  // Put the form back to the file, through the control that does it.
  await page.locator('#policy [data-discard=policy]').click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);
  const restored = await page.evaluate(() => editRows('policy').length);
  if (restored !== 0) {
    fail(`policy: Discard left ${restored} unsaved change(s) behind`);
  }
  if (statePath) note(`policy: enforcement marker read from ${statePath}`);
}

/* v0.38: a saved pattern the server marks dead gets a .mut note near the rules.
 * The oracle is POLICY.rules[kind][].dead — the server's own verdict, computed by
 * _policy.dead_patterns beside the guard's matcher — never the renderer's output.
 * The written block holds BOTH a dead and a live pattern, or presence and absence
 * could not both be checked and the assertion would prove nothing. The note is a
 * static .mut line (no hover, no overlay, nothing that can grow a scroll box), so
 * presence/absence IS the whole assertion. Rewrites the fixture's config, so it
 * runs last in the policy leg. */
async function assertDeadPatternNote(page, cfgPath) {
  const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'));
  cfg.policy = {
    onViolation: 'deny',
    skills: { default: 'allow', deny: ['shell-runner', 'zzz-ghost-*'] },
  };
  writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
  await page.reload({ waitUntil: 'load' });
  await page.click('.tab[data-t=policy]');
  await page.waitForSelector('#policy .card', { timeout: 15000 });
  await page.waitForTimeout(250);
  const got = await page.evaluate(() => ({
    oracle: (POLICY.rules[PF.kind] || []).map((r) => [r.pattern, !!r.dead]),
    notes: [...document.querySelectorAll('#policy [data-pdead]')]
      .map((n) => [n.dataset.pdead, n.textContent]),
  }));
  const deadOracle = got.oracle.filter(([, d]) => d).map(([p]) => p);
  const liveOracle = got.oracle.filter(([, d]) => !d).map(([p]) => p);
  if (!deadOracle.length || !liveOracle.length) {
    fail(`policy: the dead-pattern fixture resolves to dead=${JSON.stringify(deadOracle)} `
       + `live=${JSON.stringify(liveOracle)} — it needs one of each, or presence `
       + `and absence cannot both be checked`);
    return;
  }
  const noted = got.notes.map(([k]) => k);
  const missing = deadOracle.filter((p) => !noted.some((k) => k.endsWith(' ' + p)));
  const extra = got.notes.filter(([k]) => liveOracle.some((p) => k.endsWith(' ' + p)));
  const worded = got.notes.every(([, t]) => t.includes('matches nothing installed here'));
  if (missing.length || extra.length || !worded) {
    fail(`policy: dead-pattern notes ${JSON.stringify(got.notes)} vs the server's `
       + `dead=${JSON.stringify(deadOracle)} (missing=${JSON.stringify(missing)}, `
       + `extra=${JSON.stringify(extra.map(([k]) => k))}, worded=${worded})`);
  } else {
    note(`policy: dead pattern ${deadOracle[0]} carries its note, live `
       + `${liveOracle[0]} does not (a static .mut line — nothing to grow)`);
  }
}

/**
 * An open dialog is the toast lesson with a longer memory.
 *
 * A toast clears itself in 2.6 seconds; a `<dialog>` left open stays open, and the
 * next shutter photographs it. It is worse than a toast, too: the panel's dialogs
 * are modal, so on a `fullPage` capture the top layer lands at the bottom of a
 * 5900px image with the rest of the page dimmed behind it — which is exactly how
 * the help drawer arrived in the middle of the Overview screenshot. Declared per
 * shot rather than tidied up per step, so the shot that WANTS one says so and
 * every other shot is guarded by default.
 */
async function noDialog(page, name) {
  const open = await page.evaluate(() =>
    [...document.querySelectorAll('dialog[open]')]
      .map((d) => d.className || '(unclassed)'));
  if (!open.length) return;
  fail(`${name}: a <dialog> is still open (${open.join(', ')}) — this capture `
     + `would show it over the view it is supposed to be a picture of`);
}

async function shot(page, name, { full = false, dialog = false } = {}) {
  await settle(page);
  await noToast(page, name);
  if (!dialog) await noDialog(page, name);
  if (CHECK) return;
  mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: full });
  note(`wrote ${path.relative(REPO, file)} (${statSync(file).size} B)`);
}

async function main() {
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    console.error('playwright is not available. Run with:\n'
      + '  npx --yes --package=playwright@1.56.0 node tools/capture-screenshots.mjs');
    process.exit(2);
  }

  const work = mkdtempSync(path.join(tmpdir(), 'audit-shots-'));
  const servers = [];
  let panel = null;
  let polPanel = null;          // the policy fixture's own panel — its own HOME
  const browser = await chromium.launch();

  try {
    // ---- report shots, from the committed example -------------------------------
    if (ONLY === 'all' || ONLY === 'report') {
      const acme = path.join(work, 'acme');
      mkdirSync(acme, { recursive: true });
      py([path.join(SCRIPTS, 'render-report.py'),
          'examples/acme-store/audit-plan.json', '--out-dir', acme],
         { CLAUDE_PROJECT_DIR: path.join(REPO, 'examples', 'acme-store') });

      const { server, port } = await serveDir(acme);
      servers.push(server);
      const url = `http://127.0.0.1:${port}/acme-store-audit.html`;

      const ctx = await browser.newContext({
        viewport: { width: 1200, height: 900 },
        deviceScaleFactor: 1,
        reducedMotion: 'reduce',      // the fix for the empty-bar hero image
        colorScheme: 'light',
      });
      const page = await ctx.newPage();

      await page.goto(url, { waitUntil: 'load' });
      await settle(page);
      await assertBarsPainted(page, 'report/light');
      await shot(page, 'overview', { full: true });

      await page.click('#audit-expand');
      await page.waitForTimeout(120);
      await shot(page, 'expanded');

      // Filter to one phase status, which is what the chip row is for.
      const chip = page.locator('#audit-phase-status button').first();
      if (await chip.count()) { await chip.click(); await page.waitForTimeout(120); }
      await shot(page, 'filtered');

      // The More-filters panel — model chips, the two date inputs and the presets.
      // Captured with a chip PRESSED, because an open panel over an unfiltered
      // table is a picture of a control that might do nothing; the on-state is the
      // subject. The status chip above is released first: two filters at once can
      // legitimately select no phase at all, and a screenshot of the filters would
      // then be a screenshot of the empty state. That the table still has rows is
      // asserted rather than hoped for, since --check runs this path too and a
      // capture nobody looks at is how the empty-progress-bar hero shipped.
      if (await chip.count()) { await chip.click(); await page.waitForTimeout(120); }
      const models = page.locator('#audit-model .fchip');
      if (await models.count()) {
        await page.click('.fdetails > summary');
        await page.waitForTimeout(120);
        await models.first().click();
        await page.waitForTimeout(250);
        const left = await page.evaluate(() => ({
          phases: [...document.querySelectorAll('tr.phase')]
            .filter((r) => r.style.display !== 'none').length,
          panelOpen: !!document.querySelector('.fdetails[open]'),
          on: (document.querySelector('#audit-model .fchip') || {}).ariaPressed,
        }));
        if (!left.panelOpen || left.on !== 'true' || left.phases < 1) {
          fail(`report: the filters shot would show panel open=${left.panelOpen}, `
             + `chip pressed=${left.on}, ${left.phases} phase rows — capture it and `
             + `the README gains a picture of a filter that filtered everything away`);
        } else {
          note(`filters: a model chip leaves ${left.phases} phase rows, panel open`);
        }
        await shot(page, 'filters');
        await models.first().click();          // leave the view as it was found
        await page.click('.fdetails > summary');
        await page.waitForTimeout(120);
      } else {
        fail('report: the example records no per-task model, so there is no More-'
           + 'filters panel to capture — the filters shot cannot be refreshed');
      }

      // The area chips (D1), photographed ON — the subject is a filter that
      // filters: the chip row with one chip pressed, the phases carrying that tag
      // kept, every other phase (the untagged one included) actually gone, and the
      // selection riding in the shareable hash. The tag is chosen by measurement
      // rather than by name — whichever keeps the most phases while still hiding
      // at least one — so the picture shows both halves of the feature and this
      // file never pins the example's own vocabulary.
      if (!(await page.locator('#audit-areas .fchip').count())) {
        fail('report: the example carries no area tags, so there is no chip row '
           + 'and the areas shot cannot be refreshed');
      } else {
        const pick = await page.evaluate(() => {
          const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
          const tagsOf = (r) => (r.getAttribute('data-area') || '')
            .split(/\s+/).filter(Boolean);
          let best = null;
          for (const c of document.querySelectorAll('#audit-areas .fchip')) {
            const tag = c.getAttribute('data-a');
            const kept = rows.filter((r) => tagsOf(r).includes(tag)).length;
            const hidden = rows.length - kept;
            if (kept && hidden && (!best || kept > best.kept)) {
              best = { tag, kept, hidden, total: rows.length,
                       untagged: rows.filter((r) => !tagsOf(r).length).length };
            }
          }
          return best;
        });
        if (!pick) {
          fail('report: no area tag both keeps and hides a phase, so the areas '
             + 'shot could not show the filter doing anything');
        } else {
          await page.click('.fdetails > summary');
          await page.waitForTimeout(120);
          await page.click(`#audit-areas .fchip[data-a="${pick.tag}"]`);
          await page.waitForTimeout(250);
          const on = await page.evaluate((tag) => {
            const vis = (r) => r.style.display !== 'none';
            const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
            const tagsOf = (r) => (r.getAttribute('data-area') || '')
              .split(/\s+/).filter(Boolean);
            const shown = rows.filter(vis);
            const chip = document.querySelector(`#audit-areas .fchip[data-a="${tag}"]`);
            return {
              shown: shown.length,
              offTag: shown.filter((r) => !tagsOf(r).includes(tag)).length,
              untaggedShown: shown.filter((r) => !tagsOf(r).length).length,
              pressed: chip ? chip.getAttribute('aria-pressed') : null,
              panelOpen: !!document.querySelector('.fdetails[open]'),
              hash: location.hash,
            };
          }, pick.tag);
          if (!on.panelOpen || on.pressed !== 'true' || on.shown !== pick.kept
              || on.offTag || on.untaggedShown || !/[!&]a=/.test(on.hash)) {
            fail(`report: the areas shot would show panel open=${on.panelOpen}, `
               + `chip pressed=${on.pressed}, ${on.shown}/${pick.total} phase rows `
               + `(${on.offTag} off-tag, ${on.untaggedShown} untagged) for `
               + `"${pick.tag}", hash "${on.hash}" - a picture of area chips must `
               + `show the tagged phases kept and the rest actually gone`);
          } else {
            note(`areas: "${pick.tag}" keeps ${pick.kept}/${pick.total} phases, `
               + `hides ${pick.hidden} (${pick.untagged} untagged), a= in the hash`);
          }
          await shot(page, 'areas');
          await page.click(`#audit-areas .fchip[data-a="${pick.tag}"]`);
          await page.waitForTimeout(250);
          // Releasing the chip returns to the AT-REST view, and since D1 the
          // rest state may hold done phases collapsed under the archive —
          // the expectation reads the document's own contract (the toggle's
          // state) rather than assuming every row shows.
          const back = await page.evaluate(() => {
            const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
            const arch = document.getElementById('audit-arch');
            const archived = (arch && arch.getAttribute('aria-expanded') === 'false')
              ? rows.filter((r) => r.getAttribute('data-seg') === 'done').length : 0;
            return { shown: rows.filter((r) => r.style.display !== 'none').length,
                     want: rows.length - archived };
          });
          if (back.shown !== back.want) {
            fail(`report: releasing the "${pick.tag}" area chip left `
               + `${back.shown}/${pick.total} phase rows (want ${back.want} — `
               + `the rest sit in the collapsed archive)`);
          }
          await page.click('.fdetails > summary');
          await page.waitForTimeout(120);
        }
      }

      // The author chips (C3) — the usage section scoped to one person: the chip
      // pressed, the summary line reading off the chip's own data attributes, the
      // By author list down to that one row, and exactly one per-author cell left
      // in Detail. The chips render only when the ledger records more than one
      // author, and the committed example's ledger records three — so an absent
      // row here is a regression, never a fixture choice.
      if (!(await page.locator('#audit-authors .fchip').count())) {
        fail('report: the example ledger records more than one author and no '
           + 'author chip row rendered - the authors shot cannot be refreshed');
      } else {
        const who = await page.evaluate(() =>
          document.querySelector('#audit-authors .fchip').getAttribute('data-au'));
        await page.evaluate(() => document.getElementById('audit-authors')
          .scrollIntoView({ block: 'start' }));
        await page.waitForTimeout(200);
        await page.click('#audit-authors .fchip');
        await page.waitForTimeout(250);
        const on = await page.evaluate((au) => {
          const cells = [...document.querySelectorAll('.smcell')];
          const visCells = cells.filter((c) => !c.hidden);
          const rows = [...document.querySelectorAll('.rank[data-author]')];
          const chip = document.querySelector('#audit-authors .fchip');
          const auNote = document.getElementById('audit-au-note');
          return {
            cells: cells.length, vis: visCells.length,
            visMine: visCells.length === 1
              && visCells[0].getAttribute('data-author') === au,
            rows: rows.length,
            rowsVis: rows.filter((r) => !r.hidden).length,
            pressed: chip ? chip.getAttribute('aria-pressed') : null,
            said: auNote && !auNote.hidden ? auNote.textContent : null,
            hash: location.hash,
          };
        }, who);
        if (on.pressed !== 'true' || !on.visMine || on.rowsVis !== 1
            || !on.said || !on.said.includes(who) || !/#!.*au=/.test(on.hash)) {
          fail(`report: the authors shot would show chip pressed=${on.pressed}, `
             + `${on.vis}/${on.cells} per-author cells and ${on.rowsVis}/${on.rows} `
             + `By-author rows visible for ${who}, summary `
             + `${JSON.stringify(on.said)}, hash "${on.hash}" - the single-author `
             + `state is the subject, and it has to be real before it is committed`);
        } else {
          note(`authors: ${who} selected - 1/${on.cells} cells, 1/${on.rows} rows, `
             + `summary line on, au= in the hash`);
        }
        await shot(page, 'authors');
        await page.click('#audit-authors .fchip');     // release it
        await page.waitForTimeout(250);
        const off = await page.evaluate(() => ({
          hash: location.hash,
          noteHidden: (document.getElementById('audit-au-note') || {}).hidden,
        }));
        if (/#!.*au=/.test(off.hash) || off.noteHidden === false) {
          fail(`report: releasing the author chip left hash "${off.hash}" and the `
             + `summary line ${off.noteHidden === false ? 'showing' : 'hidden'}`);
        }
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForTimeout(120);
      }
      // After the last shot this context takes: the round trip ends where it
      // started, but it also writes localStorage, and nothing below reuses it.
      await assertThemeMovesNativeControls(page, 'report', '#audit-theme');
      await ctx.close();

      const darkCtx = await browser.newContext({
        viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'dark',
      });
      const dark = await darkCtx.newPage();
      await dark.goto(url, { waitUntil: 'load' });
      await settle(dark);
      await assertBarsPainted(dark, 'report/dark');
      await shot(dark, 'dark');
      await darkCtx.close();

      const mobCtx = await browser.newContext({
        viewport: { width: 360, height: 800 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'light', isMobile: false,
      });
      const mob = await mobCtx.newPage();
      await mob.goto(url, { waitUntil: 'load' });
      await shot(mob, 'mobile', { full: true });
      await mobCtx.close();
    }

    // ---- panel shots, from a generated 50 x 20 fixture --------------------------
    if (ONLY === 'all' || ONLY === 'panel') {
      const big = path.join(work, 'big');
      py([path.join(SCRIPTS, 'gen-demo-manifest.py'), big, '--phases', '50', '--tasks', '20']);
      py([path.join(SCRIPTS, 'gen-demo-usage.py'), path.join(big, 'audit-plan.json')]);

      // The panel names the identity it writes as, in the topbar and again in the
      // confirm dialog — resolved by usage_ledger.resolve_author, which asks git.
      // Left alone that is whoever ran the capture, and these PNGs are committed to
      // a public repository: the first run after the identity pill landed put a
      // maintainer's personal address in four of them. The fixture is a demo, so it
      // gets a demo identity, supplied the way git itself supports rather than by
      // writing to anyone's real config. GIT_CONFIG_NOSYSTEM, not a /dev/null path,
      // because this also runs on Windows.
      const gitcfg = path.join(work, 'demo.gitconfig');
      writeFileSync(gitcfg, `[user]\n\temail = ${DEMO_AUTHOR}\n\tname = Demo Dev\n`);
      panel = await startPanel(big, {
        GIT_CONFIG_GLOBAL: gitcfg, GIT_CONFIG_NOSYSTEM: '1',
      });
      const ctx = await browser.newContext({
        viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'light',
        acceptDownloads: true,        // the Usage tab's CSV export is driven below
      });
      const page = await ctx.newPage();
      // The panel is ONE inline script. A syntax error anywhere in it kills every
      // view at once, and the page still serves 200 with its full static shell — so
      // a check that asserts on the HTML source, or even on `.tab` being present,
      // passes against a completely dead panel. That is the same failure the report
      // shipped once (see tools/check-report-interactive.mjs); this is the panel's
      // half of it, and it costs nothing because a browser is already open.
      const jsErrors = [];
      page.on('pageerror', (e) => jsErrors.push(String(e.message).split('\n')[0]));
      page.on('console', (m) => { if (m.type() === 'error') jsErrors.push(m.text()); });
      await page.goto(panel.url, { waitUntil: 'load' });
      await page.waitForSelector('.tab', { timeout: 15000 });
      await page.waitForTimeout(400);

      const tabs = await page.$$eval('.tab', (els) => els.map((e) => e.dataset.t));
      note(`panel tabs present: ${tabs.join(', ')}`);
      for (const t of ['guards', 'comp', 'over', 'usage', 'policy']) {
        if (!tabs.includes(t)) {
          fail(`panel has no ${t} tab — the fixture or the UI is out of date`);
        }
      }

      // Asserted BEFORE the first shutter, not by the identity check further down.
      // If git ever stops honouring the override the failure is silent and lands in
      // a committed PNG, and the whole point of doing it in the environment is that
      // nothing about the product changes — including the part that would notice.
      const who = await page.evaluate(() => ((STATE || {}).viewer || {}).author || null);
      if (who !== DEMO_AUTHOR) {
        fail(`panel: these shots would be captured as ${JSON.stringify(who)} rather `
           + `than the demo identity "${DEMO_AUTHOR}" — GIT_CONFIG_GLOBAL did not `
           + `take, and the topbar and confirm dialog name whoever ran this`);
      } else {
        note(`panel: capturing as ${DEMO_AUTHOR}`);
      }

      // Settings is rendered by that script, from the field table panel-server.py
      // ships. Both halves are asserted: the cards exist, and every declared setting
      // put a control in the document — so a field added in Python and never wired
      // up in the UI fails here rather than silently not existing.
      const declared = JSON.parse(py([path.join(SCRIPTS, 'panel-server.py'),
                                      '--settings-paths']));
      const rendered = await page.evaluate((paths) => ({
        cards: [...document.querySelectorAll('#guards > .card')].map((c) => c.id),
        // The expected cards come from the group table Python injected, not from a
        // number written here: a count in this file goes stale the first time a
        // group is added, and then reads as "the script is dead" (it was 4 until
        // the audit trail became the fifth).
        want: SETTINGS.map((g) => 'setgrp-' + g.id),
        missing: paths.filter((p) => !document.getElementById('set-' + p)),
      }), declared);
      if (rendered.cards.join(',') !== rendered.want.join(',')) {
        fail(`Settings rendered cards [${rendered.cards.join(', ')}], expected `
           + `[${rendered.want.join(', ')}] (the script may not be running at all)`);
      } else if (rendered.missing.length) {
        fail(`Settings declares ${declared.length} config paths but rendered no `
           + `control for: ${rendered.missing.join(', ')}`);
      } else {
        note(`settings: ${rendered.cards.length} groups, `
           + `${declared.length}/${declared.length} controls rendered`);
      }

      // The wide case, which is the one the old flip was written for: a 290px bubble
      // hung off a hint in the right half of a 1200px layout runs past the edge just
      // as surely as it does on a phone, and here it is the only thing that would.
      await page.mouse.move(0, 0);
      const deskHints = await assertHintsFit(page, 'settings at 1200px');
      // A view with no ⓘ is legitimate in general — Usage has none — but not this
      // one, three lines under an assertion that every declared control rendered.
      // Said HERE, and not only in the panel-wide tally further down, because the
      // next step reaches the help drawer by clicking a ⓘ: with none on the page
      // that click spends 30 seconds timing out and takes the run down with a
      // stack, and a diagnostic that dies before it can accuse anything is F7.
      if (!deskHints.length) {
        fail('Settings rendered every one of its declared controls and not one ⓘ — '
           + 'every containment check in this file now has nothing to look at');
      }

      await shot(page, 'panel-guards');

      // The help drawer, over the form it explains — which is the point of a side
      // sheet rather than a centred dialog, and the reason it is photographed here
      // rather than on a page of its own. `exemptGlobs` is the field it is opened
      // on because that one shows every part doing a different job at once: the
      // schema's sentence, the eight globs you get for free (the DEFAULT, read off
      // what the hooks fall back to), a panel note that adds what the schema does
      // not say (globs are matched against the bare name too), and the concept
      // page behind it. The checks below drive `enforce` instead — a boolean
      // default is a crisper oracle than a list — and the two need not agree.
      await page.click('#guards [data-hint="exemptGlobs"]');
      await page.waitForSelector('dialog.drawer[open]', { timeout: 10000 });
      await page.waitForTimeout(250);
      await shot(page, 'panel-help', { dialog: true });
      await page.keyboard.press('Escape');
      await page.waitForTimeout(200);

      // Composition — the tab that carries the "usable at 50 x 20" claim.
      await page.click('.tab[data-t=comp]');
      await page.waitForSelector('#comp table', { timeout: 15000 });
      await page.waitForTimeout(300);

      // The table opens COLLAPSED — 50 phase rows standing in for 1000 tasks, which
      // is the compact view the scale claim is about. The single control toggles, so
      // capture the default first and expand for the second shot. The row count is
      // asserted rather than assumed: a stale selector would otherwise write two
      // identical files and nothing would say so.
      const visibleRows = () => page.evaluate(() =>
        [...document.querySelectorAll('#comp table tr')]
          .filter((r) => r.offsetParent !== null).length);

      await shot(page, 'panel-composition');
      const before = await visibleRows();
      const toggle = page.locator('#comp').getByRole('button', {
        name: /^(collapse all|expand all)$/i }).first();
      if (!(await toggle.count())) {
        fail('composition tab has no expand/collapse control — selector is stale');
      } else {
        await toggle.click();
        await page.waitForTimeout(500);
        const after = await visibleRows();
        if (after <= before) {
          fail(`expanding the composition table changed nothing (${before} -> ${after} `
             + `visible rows) — the two composition shots would be identical`);
        } else {
          note(`composition rows ${before} collapsed -> ${after} expanded`);
        }
      }
      await shot(page, 'panel-composition-expanded');

      // Taken here, on the tab it belongs to and with its rows already open, and
      // deliberately BEFORE the checks that end in a toast: a shutter that follows
      // one photographs it. It reverts what it typed.
      await captureConfirmDialog(page);

      // The discovered building-blocks table lives in Composition too, below the
      // phase table — not in Overview, which is where a previous reading put it.
      const blocks = page.locator('#comp', { hasText: /Available building blocks/i });
      if (await blocks.count()) {
        await page.locator('text=/Available building blocks/i').first()
          .scrollIntoViewIfNeeded();
        await page.waitForTimeout(200);
      } else {
        fail('composition tab has no "Available building blocks" section');
      }
      await shot(page, 'panel-blocks');

      // Overview renders from STATE.rollup, fetched async — wait for real content
      // rather than a fixed sleep, or the shot is of an empty div.
      await page.click('.tab[data-t=over]');
      await page.waitForFunction(
        () => { const o = document.querySelector('#over');
                return o && o.querySelectorAll('.card').length > 0; },
        null, { timeout: 20000 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await shot(page, 'panel-overview', { full: true });
      await assertOverviewWorks(page);

      // gt (v0.34): the Plan gate card with a populated events table — the shot
      // the README's gate-events paragraph sits beside. Seeded straight into the
      // fixture's feed file and read back through the poll, the same loop the
      // gate check at the end drives; every row uses the vocabulary the hooks
      // really write (event names, reason shapes), because a committed PNG that
      // invents its own vocab is documentation of a product that does not exist.
      // Asserted before the shutter: a card that fell back to its "no events
      // yet" state would photograph the feature as absent.
      {
        const gateLogs = path.join(big, '.claude', 'logs');
        mkdirSync(gateLogs, { recursive: true });
        const seeded = [
          ['2026-04-18T09:12:04Z', 'observe', 'src/web/mod06_02.ts', 'observe',
            'change magnitude 96 (> 80)'],
          ['2026-04-18T09:40:31Z', 'allow.trivial', 'src/web/mod06_04.ts', 'allow',
            'first small file (magnitude 41)'],
          ['2026-04-19T10:02:47Z', 'warn', 'src/mobile/mod07_01.ts', 'warn',
            'second distinct file in session'],
          ['2026-04-19T14:21:09Z', 'deny', 'src/mobile/mod07_03.ts', 'deny',
            'change magnitude 214 (> 80)'],
          ['2026-04-19T14:24:52Z', 'bypass.armed', null, null,
            '#no-plan hotfix the retry policy config'],
          ['2026-04-19T14:26:10Z', 'bypass.consumed', 'src/mobile/mod07_03.ts',
            'allow', 'single-use bypass consumed'],
        ];
        writeFileSync(path.join(gateLogs, 'plan-gate-events.jsonl'),
          seeded.map(([ts, event, file, mode, reason]) => JSON.stringify(
            { ts, event, ...(file ? { file } : {}), ...(mode ? { mode } : {}),
              reason, sessionId: 'sess-demo' })).join('\n') + '\n');
        await page.evaluate(() => pollRunStatus());
        const landed = await page.waitForFunction((n) => {
          const c = document.getElementById('gatecard');
          return !!c && c.querySelectorAll('tbody tr').length === n;
        }, seeded.length, { timeout: 6500 }).then(() => true, () => false);
        const shown = await page.evaluate(() => {
          const c = document.getElementById('gatecard');
          return c ? { rows: c.querySelectorAll('tbody tr').length,
                       tier: (c.querySelector('.st') || {}).textContent || '',
                       first: ((c.querySelector('tbody tr td:nth-child(2)') || {})
                         .textContent || '') } : null;
        });
        if (!landed || !shown || !shown.tier.trim()) {
          fail(`gate shot: ${seeded.length} seeded feed lines drew `
             + `${JSON.stringify(shown)} — the card is not showing the feed, so `
             + `the shot would show the feature as absent`);
        } else if (shown.first !== 'bypass.consumed') {
          fail(`gate shot: the newest seeded event is "bypass.consumed" and the `
             + `top row reads "${shown.first}" — the table is not newest-first`);
        } else {
          note(`gate shot: tier ${shown.tier}, all ${shown.rows} seeded events `
             + `listed newest-first`);
        }
        await page.evaluate(() =>
          document.getElementById('gatecard').scrollIntoView({ block: 'center' }));
        await page.waitForTimeout(250);
        await shot(page, 'panel-gate');
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForTimeout(200);
      }

      await page.click('.tab[data-t=usage]');
      await page.waitForTimeout(600);
      await shot(page, 'panel-usage');

      // C2's Monthly card — the ledger half beside the project-wide plan half.
      // The card renders only once the ledger spans two calendar months, so that
      // precondition is asserted rather than hoped for; and the WHOLE card has to
      // sit inside the frame, below the sticky topbar/tab/filter stack — a
      // capture that clipped the plan columns, or slid the heading under the
      // pinned bars, would be a picture of half the feature. Both halves are also
      // required to carry a number: a fixture whose plan half summed to zero
      // would photograph the card half dead and nothing would say so.
      {
        const months = await page.evaluate(() =>
          new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 7))).size);
        if (months < 2) {
          fail(`usage: the fixture ledger spans ${months} calendar month(s), so `
             + `the Monthly card does not render and its shot cannot be taken`);
        } else if (!(await page.locator('#usage [data-umonthly]').count())) {
          fail(`usage: ${months} ledger months and no Monthly card in the DOM`);
        } else {
          const m = await page.evaluate(() => {
            const tbl = document.querySelector('#usage [data-umonthly]');
            const heads = [...tbl.querySelectorAll('thead th')].map((h) => h.textContent);
            const rows = [...tbl.querySelectorAll('tbody tr')];
            const iTok = heads.indexOf('tokens'), iDone = heads.indexOf('tasks done');
            const num = (c) => parseFloat(String(c.textContent)
              .replace(/[^0-9.]/g, '')) || 0;
            const sum = (i) => rows.reduce((a, r) => a + num(r.cells[i]), 0);
            // The card is [h2, crumb, wrapper]; scroll from its own structure so a
            // reshuffle fails loudly here rather than framing the wrong heading.
            const wrap = tbl.closest('.umwrap');
            const h2 = wrap && wrap.previousElementSibling
              ? wrap.previousElementSibling.previousElementSibling : null;
            if (h2) h2.scrollIntoView({ block: 'start' });
            return { heads, rows: rows.length,
                     h2: h2 ? h2.textContent : null,
                     ledger: iTok < 0 ? 0 : sum(iTok),
                     plan: iDone < 0 ? 0 : heads.slice(iDone)
                       .reduce((a, _, k) => a + sum(iDone + k), 0) };
          });
          await page.waitForTimeout(200);
          // Slide the card out from under the sticky stack, then measure it.
          await page.evaluate(() => {
            const bars = ['.top', '.tabs', '#usage .ufil']
              .map((s) => document.querySelector(s)).filter(Boolean);
            const stack = Math.max(0, ...bars.map((b) => b.getBoundingClientRect().bottom));
            const h2 = document.querySelector('#usage [data-umonthly]')
              .closest('.umwrap').previousElementSibling.previousElementSibling;
            window.scrollBy(0, h2.getBoundingClientRect().top - stack - 8);
          });
          await page.waitForTimeout(200);
          const fits = await page.evaluate(() => {
            const tbl = document.querySelector('#usage [data-umonthly]');
            const h2 = tbl.closest('.umwrap').previousElementSibling.previousElementSibling;
            const bars = ['.top', '.tabs', '#usage .ufil']
              .map((s) => document.querySelector(s)).filter(Boolean);
            return { top: Math.round(h2.getBoundingClientRect().top),
                     stack: Math.round(Math.max(0,
                       ...bars.map((b) => b.getBoundingClientRect().bottom))),
                     bottom: Math.round(tbl.getBoundingClientRect().bottom),
                     right: Math.round(tbl.getBoundingClientRect().right),
                     vh: window.innerHeight,
                     vw: document.documentElement.clientWidth };
          });
          if (m.h2 !== 'Monthly' || !m.heads.includes('tokens')
              || !m.heads.includes('tasks done') || !m.heads.includes('merged')) {
            fail(`usage: the Monthly card's shape moved - heading `
               + `${JSON.stringify(m.h2)}, columns [${m.heads.join(', ')}]`);
          } else if (!m.ledger || !m.plan) {
            fail(`usage: the Monthly card would photograph half dead - ledger sum `
               + `${m.ledger}, plan sum ${m.plan} over ${m.rows} month row(s)`);
          } else if (fits.top < fits.stack - 1 || fits.bottom > fits.vh
                     || fits.right > fits.vw) {
            fail(`usage: the Monthly card does not fit the frame (heading at `
               + `${fits.top}px under a ${fits.stack}px sticky stack, table ends `
               + `${fits.bottom}/${fits.vh}px, right ${fits.right}/${fits.vw}px) - `
               + `raise the viewport rather than clip the plan half`);
          } else {
            note(`usage: Monthly card in frame - ${m.rows} month row(s), ledger `
               + `and plan halves both non-zero`);
          }
          await shot(page, 'panel-monthly');
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.waitForTimeout(200);
        }
      }

      // C4's person header — the author drill-down with a face on it. The filter
      // is set through the page's own setF (the same call the legend click makes),
      // and every number the header shows is checked against a recomputation from
      // USAGE.facts before the shutter opens — so under --check this step still
      // proves the header renders and counts honestly, and the capture cannot
      // commit a card whose all-time strip disagrees with the ledger it fronts.
      {
        const who = await page.evaluate(() => {
          const t = {};
          for (const f of USAGE.facts) t[f[F.author]] = (t[f[F.author]] || 0) + f[F.tokens];
          return Object.keys(t).filter((a) => a && a !== 'unknown')
            .sort((a, b) => t[b] - t[a])[0] || null;
        });
        if (!who) {
          fail('usage: the fixture ledger records no author, so the person-header '
             + 'shot cannot be taken');
        } else {
          await page.evaluate((a) => setF('author', a), who);
          await page.waitForTimeout(300);
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.waitForTimeout(200);
          const got = await page.evaluate((a) => {
            const head = document.querySelector('#usage [data-person]');
            const strip = document.querySelector('#usage [data-ptasks]');
            const mine = USAGE.facts.filter((f) => f[F.author] === a);
            const tasks = new Set(mine.map((f) => f[F.task])
              .filter((t) => t && t !== '--'));
            const phases = new Set(mine.map((f) => f[F.phase])
              .filter((p) => p && p !== '--'));
            const r = head && head.getBoundingClientRect();
            const s = strip && strip.getBoundingClientRect();
            return {
              named: head ? head.textContent : null,
              tasks: strip ? +strip.getAttribute('data-ptasks') : null,
              phases: strip ? +strip.getAttribute('data-pphases') : null,
              msgs: strip ? +strip.getAttribute('data-pmsgs') : null,
              want: { tasks: tasks.size, phases: phases.size,
                      msgs: mine.reduce((x, f) => x + f[F.msgs], 0) },
              split: [...document.querySelectorAll('#usage .mut.small')]
                .some((d) => /^Their touched tasks:/.test(d.textContent)),
              inFrame: !!(r && s && r.top >= 0 && s.bottom <= window.innerHeight),
            };
          }, who);
          if (!got.named || !got.named.includes(who)) {
            fail(`usage: an author filter on ${who} renders no person header to `
               + `photograph`);
          } else if (got.tasks !== got.want.tasks || got.phases !== got.want.phases
                     || got.msgs !== got.want.msgs) {
            fail(`usage: the person header would photograph the wrong numbers - `
               + `${got.phases} phases / ${got.tasks} tasks / ${got.msgs} msgs on `
               + `screen, ${got.want.phases} / ${got.want.tasks} / `
               + `${got.want.msgs} in the facts`);
          } else if (!got.split) {
            fail(`usage: ${who}'s header carries no status-split line - half the `
               + `card this shot exists to show`);
          } else if (!got.inFrame) {
            fail(`usage: ${who}'s person header does not fit the frame at the top `
               + `of the tab`);
          } else {
            note(`usage: person header for ${who} in frame (${got.want.phases} `
               + `phases, ${got.want.tasks} tasks, ${got.want.msgs} msgs, status `
               + `split shown)`);
          }
          await shot(page, 'panel-person');
          await page.evaluate(() => clearAll());
          await page.waitForTimeout(250);
          if (await page.evaluate(() =>
            !!document.querySelector('#usage [data-person]'))) {
            fail('usage: the person header outlived its filter after the shot');
          }
        }
      }

      // Round trip first — it ends where it started, so the shot below is still
      // the first press. The panel needs this more than the report does: Settings
      // alone ships a <select>, an <input type=date> and four number inputs.
      await assertThemeMovesNativeControls(page, 'panel', '#theme');
      await page.click('#theme');
      await page.waitForTimeout(300);
      await shot(page, 'panel-dark');

      // The phone. Its own context, so it starts from the theme the OS asks for
      // rather than the dark one just written to this origin's localStorage, and
      // its own error handlers, because a layout that only breaks at 390px breaks
      // in script the same way it breaks in CSS. The report has had a mobile shot
      // since the app shell landed; the panel's was specified with the shared
      // theme work and never taken, so until now nothing in the repo showed — or
      // checked — what this UI does on a phone. 390x844 is the viewport the Usage
      // bar was measured against when it was made to stop pinning below 34rem.
      const mobCtx = await browser.newContext({
        viewport: { width: 390, height: 844 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'light',
      });
      const mob = await mobCtx.newPage();
      mob.on('pageerror', (e) => jsErrors.push('mobile: ' + String(e.message).split('\n')[0]));
      mob.on('console', (m) => { if (m.type() === 'error') jsErrors.push('mobile: ' + m.text()); });
      await mob.goto(panel.url, { waitUntil: 'load' });
      await mob.waitForSelector('.tab', { timeout: 15000 });
      await mob.click('.tab[data-t=over]');
      await mob.waitForFunction(
        () => { const o = document.querySelector('#over');
                return o && o.querySelectorAll('.card').length > 0; },
        null, { timeout: 20000 });
      await mob.waitForTimeout(300);
      // The one thing a phone shot must not show, and the one thing a reviewer
      // scrolling a PNG cannot see: the page itself sliding sideways. Wide tables
      // are allowed to scroll inside their own frame; the document is not.
      //
      // Driven over EVERY tab, not whichever one the shot happens to sit on. This
      // assertion has existed since panel c2 and only ever ran on Overview — one of
      // the views that passed — so it was green for its whole life while Settings
      // took the document 76px sideways (F8). A check that looks at one of five
      // views is not an assertion about the panel, and the tab it looks at is
      // decided by where the photographer stopped. Proven rather than argued: with
      // the defect restored and this loop cut back to Overview, the gate is green.
      //
      // The failure names the widest element that crosses the edge, because "76px"
      // does not say which row to fix. Anything inside a frame of its own is
      // excluded by asking its ancestors, not by listing selectors: `overflow-x`
      // anything but `visible` scrolls or clips its content and cannot push the
      // document, which is exactly the distinction this check is drawing.
      //
      // What it measures is the resting layout of each view, and deliberately only
      // that: the pointer is parked off every control first, so what is reported is
      // the layout rather than the layout plus whatever the mouse happens to be
      // touching. The ⓘ bubble is the other thing that reaches past the edge, and it
      // is measured separately by assertHintsFit — it has no node to be named in a
      // list of widest elements, so a sweep tripping over it would report a number
      // with an empty list of causes, which is exactly how F9 stayed open.
      const overflowAt = async (tab) => {
        await mob.mouse.move(0, 0);
        await mob.click(`.tab[data-t=${tab}]`);
        await mob.mouse.move(0, 0);
        await mob.waitForFunction(
          (t) => { const v = document.getElementById(t);
                   return v && !v.classList.contains('hidden')
                     && v.querySelectorAll('.card').length > 0; },
          tab, { timeout: 20000 });
        await mob.waitForTimeout(250);
        return mob.evaluate(() => {
          const de = document.documentElement, w = de.clientWidth;
          const framed = (n) => {
            for (let p = n.parentElement; p; p = p.parentElement) {
              if (getComputedStyle(p).overflowX !== 'visible') return true;
            }
            return false;
          };
          const name = (n) => n.tagName.toLowerCase()
            + (typeof n.className === 'string' && n.className.trim()
              ? '.' + n.className.trim().split(/\s+/).join('.') : '');
          const widest = [...document.body.querySelectorAll('*')]
            .filter((n) => n.getBoundingClientRect().right > w + 1 && !framed(n))
            .map((n) => `${name(n)} @${Math.round(n.getBoundingClientRect().right)}px`);
          return { page: de.scrollWidth - w, body: document.body.scrollWidth - w,
                   width: w, widest: widest.slice(0, 3) };
        });
      };
      let hintsSeen = 0;
      for (const t of ['guards', 'comp', 'over', 'usage', 'policy']) {
        const o = await overflowAt(t);
        hintsSeen += (await assertHintsFit(mob, `${t} at 390px`)).length;
        if (o.page > 1 || o.body > 1) {
          fail(`the ${t} tab at 390px scrolls the document sideways by ${o.page}px `
             + `(body ${o.body}px) in a ${o.width}px viewport — widest: `
             + `${o.widest.join(', ') || 'nothing outside its own frame, so a '
             + 'margin or a negative offset'}`);
        } else {
          note(`${t} at 390px: no horizontal page overflow`);
        }
      }
      if (!hintsSeen) {
        fail('not one ⓘ was measured across five views at 390px — either every '
           + 'label lost its hint or nothing rendered, and the containment checks '
           + 'above passed by having nothing to look at');
      } else {
        note(`hints: ${hintsSeen} ⓘ measured across five views at 390px`);
      }

      // The one thing that moves a hint sideways without the page moving at all:
      // the Composition table scrolls inside its own frame, and its column headers
      // carry ⓘ. Nothing here resizes and nothing scrolls the document, so a
      // placement that only listens for those is left describing where the hint
      // used to be. Measured rather than argued — the wrapper is asked how far it
      // can go, and the check says so if the answer is nothing, because a table
      // that stopped overflowing would make this step silently vacuous.
      await mob.click('.tab[data-t=comp]');
      await mob.waitForSelector('#comp table', { timeout: 15000 });
      await mob.mouse.move(0, 0);
      await mob.waitForTimeout(250);
      const room = await mob.evaluate(() => {
        const w = document.querySelector('.comptblwrap');
        if (!w || !w.querySelector('.hint')) return 0;
        w.scrollLeft = w.scrollWidth;
        return w.scrollLeft;
      });
      await mob.waitForTimeout(250);
      if (!room) {
        fail('the composition table at 390px no longer scrolls sideways with a ⓘ '
           + 'inside it — this step can no longer see what it is for');
      } else {
        await assertHintsFit(mob, `comp scrolled ${room}px inside its own frame`);
      }
      await mob.evaluate(() => {
        const w = document.querySelector('.comptblwrap'); if (w) w.scrollLeft = 0;
      });
      // One width narrower, on the one tab that needed the fix. 390px is the phone
      // this shot is taken on, and at 390px letting the ROW shrink is on its own
      // enough — the label's words rewrap inside their own box and the page is
      // clean whether or not `.lbl` may wrap. Deleting the `.lbl` half therefore
      // proved nothing here, which by this repo's own rule means either the code
      // goes or the claim narrows. It is 320px that the second half is for: there
      // the unwrapped label puts 16px back on the document. So the narrow width is
      // measured rather than the rule being pinned in Python and called covered.
      await mob.setViewportSize({ width: 320, height: 844 });
      const narrow = await overflowAt('guards');
      if (narrow.page > 1 || narrow.body > 1) {
        fail(`Settings at 320px scrolls the document sideways by ${narrow.page}px `
           + `— widest: ${narrow.widest.join(', ') || 'nothing outside its own frame'}`);
      } else {
        note('guards at 320px: no horizontal page overflow either');
      }
      await mob.setViewportSize({ width: 390, height: 844 });
      // A resize is answered on the next frame, so this waits for one rather than
      // racing it — a check that reads the layout mid-reflow reports the width it
      // came from and calls it a defect.
      await mob.waitForTimeout(250);
      await assertHintsFit(mob, 'guards back at 390px');

      // The failure this block used to chase - a bubble whose placement was
      // never computed, opening at its default anchor from inside a :hover no
      // event announced - is structurally gone: nothing exists until showTip()
      // runs, and an unshown tip has no box to break the page with. What can
      // still go wrong is an OPEN tip outliving its anchor, and both ways that
      // happens are driven for real here.
      await mob.click('.tab[data-t=guards]');
      await mob.waitForTimeout(250);
      // (a) the 5s poll re-renders the form under an open tip: the icon node
      // is replaced, and an orphaned fixed box would float over a node that no
      // longer exists. The body observer must hide it.
      const orphan = await mob.evaluate(async () => {
        const h = [...document.querySelectorAll('#guards .hint[data-tip]')]
          .find((n) => n.getBoundingClientRect().width);
        if (!h) return null;
        showTip(h);
        const b = document.getElementById('hinttip');
        const before = getComputedStyle(b).display;
        renderSettings();
        await new Promise((r) => setTimeout(r, 120));
        return { before, after: getComputedStyle(b).display };
      });
      if (!orphan) {
        fail('no visible \u24d8 on Settings at 390px to drive the orphan-tip leg on');
      } else if (orphan.before !== 'block' || orphan.after !== 'none') {
        fail(`an open tip survived its anchor's re-render (display `
           + `${orphan.before} -> ${orphan.after}) - an orphaned tip floats `
           + `over a node that no longer exists`);
      } else {
        note('a tip whose anchor is re-rendered away hides itself');
      }
      // (b) scrolling under an open FOCUS tip: the icon moves, and a fixed tip
      // that does not follow describes where the icon used to be. Focus is the
      // path where following is even correct - a pointer tip is SUPPOSED to die
      // on scroll, because Chromium's synthetic mouseover says the pointer now
      // rests on something else. A keyboard user's tip must ignore that parked
      // pointer and ride its anchor instead.
      const follow = await mob.evaluate(async () => {
        const h = [...document.querySelectorAll('#guards .hint[data-tip]')]
          .find((n) => n.getBoundingClientRect().width);
        if (!h) return null;
        window.scrollTo(0, 0);
        await new Promise((r) => setTimeout(r, 60));
        h.focus();                               // focusin -> showTip(h,'focus')
        await new Promise((r) => setTimeout(r, 60));
        const b = document.getElementById('hinttip');
        const shown = getComputedStyle(b).display === 'block';
        const t0 = parseFloat(b.style.top);
        window.scrollBy(0, 40);
        await new Promise((r) => setTimeout(r, 150));
        const scrolled = window.scrollY;
        const still = getComputedStyle(b).display === 'block';
        const t1 = parseFloat(b.style.top);
        h.blur();
        window.scrollTo(0, 0);
        return { shown, still, t0, t1, scrolled };
      });
      if (!follow) {
        fail('no visible \u24d8 on Settings at 390px to drive the follow leg on');
      } else if (!follow.shown) {
        fail('focusing a \u24d8 did not open its tip \u2014 the keyboard path is dead');
      } else if (!follow.scrolled) {
        fail('the Settings page at 390px could not scroll 40px, so the '
           + 'follow-the-anchor leg measured nothing');
      } else if (!follow.still) {
        fail('a FOCUS-shown tip was hidden by the scroll \u2014 the parked pointer\'s '
           + 'synthetic mouseover closed a keyboard user\'s tooltip');
      } else if (Math.abs((follow.t0 - follow.t1) - follow.scrolled) > 8) {
        fail(`an open focus tip did not follow its scrolled anchor: top went `
           + `${follow.t0} -> ${follow.t1} for a ${follow.scrolled}px scroll`);
      } else {
        note(`a focus tip follows its anchor through a scroll `
           + `(${follow.t0} -> ${follow.t1} for ${follow.scrolled}px)`);
      }

      // Back where the sweep started, so the shot below is still Overview.
      await mob.click('.tab[data-t=over]');
      await mob.waitForTimeout(250);
      // Five views do not fit a 390px strip, and the fifth is the one off the
      // edge. A scrolling row with no edge treatment reads as a row with four
      // items — so the strip is asked whether it overflowed, and whether it said
      // so, against the same measurement the page makes.
      const strip = await mob.evaluate(() => {
        const n = document.querySelector('.tabs');
        return { over: n.scrollWidth > n.clientWidth + 1,
                 says: n.classList.contains('scrolls'),
                 masked: getComputedStyle(n).maskImage };
      });
      if (strip.over !== strip.says) {
        fail(`the tab strip at 390px overflows=${strip.over} but marks itself `
           + `scrollable=${strip.says}`);
      } else if (strip.over && (!strip.masked || strip.masked === 'none')) {
        fail('the tab strip at 390px scrolls with no edge to say so — the fifth '
           + 'view is off screen and nothing suggests it is there');
      } else {
        note(`tab strip at 390px: overflows=${strip.over}, edge shown=`
           + `${strip.masked !== 'none'}`);
      }
      await shot(mob, 'panel-mobile');
      // The drawer on a phone. A 31rem side sheet on a 390px screen hangs off the
      // edge, so it goes full width below the breakpoint — measured rather than
      // trusted to the media query, because the UA sheet caps every dialog at
      // `calc(100% - 2px - 2em)` and quietly made the first version 339px wide.
      //
      // The page-level overflow is measured as a DELTA across opening it, not as
      // an absolute. It was written that way because Settings overflowed by 76px
      // before anything was opened (F8, since fixed, and the sweep above is now the
      // check for it); it stays that way because what this step is asking is what
      // the DRAWER adds. An absolute here would be red for whatever else is on the
      // page, which proves nothing about the drawer — and there is still one such
      // thing, F9.
      await mob.click('.tab[data-t=guards]');
      await mob.waitForSelector('#guards [data-hint="trivialLineThreshold"]', { timeout: 15000 });
      const before390 = await mob.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      await mob.click('#guards [data-hint="trivialLineThreshold"]');
      await mob.waitForSelector('dialog.drawer[open]', { timeout: 10000 });
      await mob.waitForTimeout(250);
      const sheet = await mob.evaluate(() => {
        const d = document.querySelector('dialog.drawer'),
          r = d.getBoundingClientRect(), de = document.documentElement,
          b = d.querySelector('.dbody');
        // Against the document's own content width, not the raw viewport: this
        // panel reserves a scrollbar gutter (`scrollbar-gutter:stable`), so the
        // width every full-bleed thing on the page gets is 15px short of
        // `clientWidth` and always will be.
        return { w: Math.round(r.width), vw: document.body.clientWidth,
                 screen: de.clientWidth, left: Math.round(r.left),
                 over: de.scrollWidth - de.clientWidth,
                 body: b.scrollWidth - b.clientWidth };
      });
      if (sheet.left < 0 || sheet.w < sheet.vw - 1 || sheet.w > sheet.screen + 1) {
        fail(`help drawer at 390px: ${sheet.w}px wide at x=${sheet.left} in a `
           + `${sheet.vw}px content area — below 34rem it is supposed to be the `
           + `screen`);
      } else if (sheet.over > before390 + 1) {
        fail(`help drawer at 390px: opening it added `
           + `${sheet.over - before390}px of sideways page scroll`);
      } else if (sheet.body > 1) {
        fail(`help drawer at 390px: its own body scrolls sideways by ${sheet.body}px `
           + `— a description is text, and text wraps`);
      } else {
        note(`help drawer at 390px: full width (${sheet.w}/${sheet.vw}), adds no `
           + `sideways scroll and none of its own`);
      }
      await mob.keyboard.press('Escape');
      await mob.waitForTimeout(150);
      // The Policy table is the widest thing this UI draws — a column per area on
      // top of four fixed ones — and it is drawn against this machine's real
      // discovery here, which is the biggest table anyone will get. A wide table
      // may scroll inside its own frame; the document may not.
      await mob.click('.tab[data-t=policy]');
      await mob.waitForSelector('#policy .card', { timeout: 15000 });
      await mob.waitForTimeout(200);
      const polOverflow = await mob.evaluate(() => {
        const de = document.documentElement, w = document.querySelector('#poltbl');
        return { page: de.scrollWidth - de.clientWidth,
                 body: document.body.scrollWidth - de.clientWidth,
                 framed: w ? w.scrollWidth > w.clientWidth : null };
      });
      if (polOverflow.page > 1 || polOverflow.body > 1) {
        fail(`the policy table at 390px pushes the document sideways by `
           + `${polOverflow.page}px — it must scroll inside its own frame`);
      } else {
        note(`policy at 390px: no page overflow (table scrolls in its own frame: `
           + `${polOverflow.framed})`);
      }
      // cs at 390px: the fixed-position combo menu must open INSIDE the phone
      // viewport — the width the old anchored-in-the-wrap menu had no answer
      // for (any host frame clipped it; the screen edge now clamps it).
      await mob.click('.tab[data-t=usage]');
      await mob.waitForTimeout(400);
      const mobInp = mob.locator('#usage input[aria-label="filter by task"]');
      if (!(await mobInp.count())) {
        fail('usage at 390px: no task combo to open');
      } else {
        await mobInp.click();
        await mob.waitForTimeout(250);
        const mm = await mob.evaluate(() => {
          const m = [...document.querySelectorAll('.combo-menu')]
            .find((x) => !x.classList.contains('hidden'));
          if (!m) return null;
          const r = m.getBoundingClientRect();
          return { left: Math.round(r.left), right: Math.round(r.right),
                   top: Math.round(r.top), bottom: Math.round(r.bottom),
                   vw: document.documentElement.clientWidth, vh: innerHeight };
        });
        if (!mm) {
          fail('usage at 390px: focusing the task combo opened no menu');
        } else if (mm.left < 0 || mm.right > mm.vw + 1 || mm.bottom > mm.vh + 1) {
          fail(`usage at 390px: the combo menu opens at ${mm.left}..${mm.right} x `
             + `${mm.top}..${mm.bottom} in a ${mm.vw}x${mm.vh} viewport — the `
             + `clamp is not holding on a phone`);
        } else {
          note(`usage at 390px: the combo menu fits the viewport `
             + `(${mm.left}..${mm.right} of ${mm.vw})`);
        }
        await mob.keyboard.press('Escape');
        await mob.waitForTimeout(150);
      }
      await mobCtx.close();
      // Deliberately AFTER the last capture. Driving Usage ends in an export, and an
      // export raises a toast — which the dark shot caught and committed, a banner
      // reading "2132 row(s) exported" pinned across a screenshot of the default
      // view. A check that leaves transient UI behind must run where no shutter
      // follows it, not merely be timed to miss one.
      await assertUsageWorks(page);
      await assertViewerIdentity(page);
      // Reads only, but it opens a modal over every tab it visits, so it runs
      // where no shutter follows it — the same rule the toast waiter enforces.
      await assertHelpDrawerWorks(page, declared);
      // Connector v2: opens both of the ADO card's dialogs (Save is cancelled,
      // Discard restores), so it runs with the other modal-openers where no
      // shutter follows it; it writes nothing.
      await assertAdoCardWorks(page);
      // Last of all: it writes to the fixture's manifest and its config, so every
      // check above sees the state it was generated with.
      await assertConfirmFlowWorks(page);
      // v0.37 B1: writes too (a null and its clearing), so it lives in the same
      // writes-last block.
      await assertSkillTriState(page);
      // v0.34 panel UX (C1-C5). Same writes-last discipline: the save-note
      // lifecycle saves the config twice, and the live-data check writes the
      // manifest's shard straight on disk — so both run after everything that
      // measures the fixture as generated, and live-data runs dead last.
      await assertModelCombo(page, big);
      await assertPhaseWhyNote(page);
      await assertComboSearchCount(page);
      await assertFilterPersistence(page, browser, panel.url);
      await assertSaveNoteLifecycle(page);
      await assertLiveData(page, big);
      // gt (v0.34 B3): writes into the fixture's logs/state dirs, so it keeps
      // to the same writes-last discipline and runs after live-data.
      await assertGateCard(page, big);

      // ---- the policy switchboard, on a fixture of its own ---------------------
      // Its own project and its own HOME — see writePolicyFixture for why a tab
      // that lists everything installed cannot be photographed against a real one.
      {
        const fx = writePolicyFixture(work);
        polPanel = await startPanel(fx.project, {
          HOME: fx.home, USERPROFILE: fx.home,
          GIT_CONFIG_GLOBAL: gitcfg, GIT_CONFIG_NOSYSTEM: '1',
        });
        polPanel.project = fx.project;
        // Taller than the other panel contexts, and NOT captured fullPage. The
        // save bar is `position:sticky; bottom:0`, so a fullPage capture of a page
        // longer than the viewport paints it across the middle of the table — the
        // first attempt at this shot hid two capability rows behind it. A viewport
        // that fits the view leaves the bar where it really sits, at the end.
        const pctx = await browser.newContext({
          viewport: { width: 1200, height: 1680 }, deviceScaleFactor: 1,
          reducedMotion: 'reduce', colorScheme: 'light',
        });
        const ppage = await pctx.newPage();
        ppage.on('pageerror', (e) => jsErrors.push('policy: ' + String(e.message).split('\n')[0]));
        ppage.on('console', (m) => { if (m.type() === 'error') jsErrors.push('policy: ' + m.text()); });
        await ppage.goto(polPanel.url, { waitUntil: 'load' });
        await ppage.waitForSelector('.tab', { timeout: 15000 });
        await ppage.waitForTimeout(400);

        // Discovery reached exactly the fixture and nothing of this machine's.
        // Asserted before anything is captured: the failure is silent, and lands
        // in a committed PNG that lists whatever the person capturing installed.
        const found = await ppage.evaluate(async () => {
          const r = await api('GET', '/api/registry');
          return { skills: r.skills.map((s) => s.name).sort(),
                   agents: r.agents.map((a) => a.name).sort(),
                   mcp: (r.mcp || []).slice().sort() };
        });
        const want = {
          skills: [...POL_SKILLS.map(([n]) => n),
                   ...POL_PLUGIN.filter((p) => p[0] === 'skills').map((p) => p[2])].sort(),
          agents: [...POL_AGENTS.map(([n]) => n),
                   ...POL_PLUGIN.filter((p) => p[0] === 'agents').map((p) => p[2])].sort(),
          mcp: POL_MCP.slice().sort(),
        };
        if (JSON.stringify(found) !== JSON.stringify(want)) {
          fail('policy: discovery reached beyond the fixture — HOME did not take, and '
             + `this shot would publish it: ${JSON.stringify(found)}`);
        } else {
          note(`policy: discovery is the fixture's own (${found.skills.length} skills, `
             + `${found.agents.length} agents, ${found.mcp.length} MCP)`);
        }

        // The area rule is aimed at whichever area the generated plan actually has
        // work in progress in — asked of the server rather than worked out here,
        // so the fixture cannot disagree with the thing it is a fixture for.
        const live = await ppage.evaluate(async () =>
          (await api('GET', '/api/policy')).activeAreas || []);
        const cfgPath = path.join(fx.project, '.claude', 'audit.config.json');
        const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'));
        cfg.policy = policyFixtureBlock(live[0] || null);
        writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
        await ppage.reload({ waitUntil: 'load' });
        await ppage.waitForSelector('#policy, .tab', { timeout: 15000 });
        await ppage.click('.tab[data-t=policy]');
        await ppage.waitForSelector('#policy .card', { timeout: 15000 });

        // Enforced, or only written down? The marker guard-capabilities leaves is
        // the only local evidence, and a page full of denials that does not say
        // which of the two it is would be claiming enforcement nobody has. Both
        // states are driven, because the honest one is the one nobody would notice
        // was missing.
        const seen = JSON.parse(py(['-c',
          'import importlib.util,json,os,pathlib,sys;'
          + 'sys.path.insert(0,os.path.join("plugins","audit","hooks"));'
          + 'import _config;'
          + 'p=pathlib.Path(sys.argv[1]);'
          + 'cfg=json.load(open(p/".claude"/"audit.config.json"));'
          + 's=importlib.util.spec_from_file_location("gc",os.path.join('
          + '"plugins","audit","hooks","guard-capabilities.py"));'
          + 'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
          + 'print(json.dumps({"dir":str(_config.state_dir(p,cfg)),"file":m.SEEN_FILE}))',
          fx.project]));
        const before = await ppage.evaluate(() =>
          (document.querySelector('#policy [data-pstate]') || {}).dataset?.pstate);
        if (before !== 'unproven') {
          fail(`policy: with no marker on disk the page reports "${before}" rather `
             + `than saying the guard has never been seen to run here`);
        }
        mkdirSync(seen.dir, { recursive: true });
        writeFileSync(path.join(seen.dir, seen.file), JSON.stringify({ lastRun: 'now' }));
        await ppage.reload({ waitUntil: 'load' });
        await ppage.click('.tab[data-t=policy]');
        await ppage.waitForSelector('#policy .card', { timeout: 15000 });
        const withMarker = await ppage.evaluate(() =>
          (document.querySelector('#policy [data-pstate]') || {}).dataset?.pstate);
        if (withMarker !== 'enforced') {
          fail(`policy: with the guard's own marker present the page still reports `
             + `"${withMarker}"`);
        } else {
          note(`policy: unproven without the marker, enforced with it (${before} -> `
             + `${withMarker})`);
        }

        await ppage.evaluate(() => window.scrollTo(0, 0));
        // The guard for the overlap above, rather than the instance of it: a view
        // taller than the viewport puts the sticky save bar over its own content in
        // the capture. Said here so the next person raises the viewport instead of
        // shipping a shot with two rows behind a button.
        const fits = await ppage.evaluate(() =>
          ({ h: document.documentElement.scrollHeight, v: window.innerHeight }));
        if (fits.h > fits.v) {
          fail(`the policy view is ${fits.h}px tall in a ${fits.v}px viewport — the `
             + `sticky save bar would be captured across the middle of the table`);
        }
        await shot(ppage, 'panel-policy');
        // Everything below writes to the fixture's config, so it runs after.
        await assertPolicyWorks(ppage, path.join(seen.dir, seen.file));
        // cs, second half: the description search, on the one registry whose
        // every description this file wrote.
        await assertComboDescriptionSearch(ppage);
        // v0.38: dead-pattern notes. Rewrites the fixture's policy block, so
        // it is the leg's last word.
        await assertDeadPatternNote(ppage, cfgPath);
        await pctx.close();
      }
      // Collected across every tab this run touched, and reported last so the more
      // specific failures above name themselves first.
      if (jsErrors.length) {
        fail(`the panel logged ${jsErrors.length} script error(s): `
           + [...new Set(jsErrors)].slice(0, 5).join(' | '));
      } else {
        note('panel: no uncaught exceptions and no console errors');
      }
      await ctx.close();
    }
  } finally {
    await browser.close();
    if (panel) {
      try { py([path.join(SCRIPTS, 'panel-server.py'), '--project',
                path.join(work, 'big'), '--stop']); } catch { /* best effort */ }
      try { panel.proc.kill('SIGTERM'); } catch { /* already gone */ }
    }
    if (polPanel) {
      try { py([path.join(SCRIPTS, 'panel-server.py'), '--project',
                polPanel.project, '--stop']); } catch { /* best effort */ }
      try { polPanel.proc.kill('SIGTERM'); } catch { /* already gone */ }
    }
    for (const s of servers) s.close();
    rmSync(work, { recursive: true, force: true });
  }

  if (problems.length) {
    console.log(`\n${problems.length} problem(s):`);
    for (const p of problems) console.log(`  - ${p}`);
    process.exit(1);
  }
  console.log(CHECK ? '\nOK: capture preconditions hold' : '\nOK: screenshots captured');
}

// Run only when invoked as a CLI: the exported CSV helpers above are imported
// by red-first probes, and an import that launched a full capture would make
// every probe a screenshot run.
if (process.argv[1]
    && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((err) => { console.error(err); process.exit(1); });
}
