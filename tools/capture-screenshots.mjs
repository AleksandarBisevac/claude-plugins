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
import { fileURLToPath } from 'node:url';

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

const problems = [];
const note = (m) => console.log(`  ${m}`);
const fail = (m) => { problems.push(m); console.log(`  FAIL ${m}`); };

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
      + `((USAGE.taskMeta||{})[f[F.task]]||{}).title||''].join(' ').toLowerCase()`
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
    if (lines.length !== want + 1) {
      fail(`usage: CSV has ${lines.length - 1} data rows for ${want} facts`);
    } else if (!/^ts,phase,task,model,author,agent,attr,tokens,costUSD,msgs$/.test(lines[0])) {
      fail(`usage: CSV header is "${lines[0]}"`);
    } else if (lines.slice(1, 200).some((l) => /"?\d+,\d{3}[,."]/.test(l))) {
      fail('usage: CSV numbers carry thousands separators — a spreadsheet reads '
         + 'those as text and every sum over the column is then wrong');
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
  await shot(page, 'panel-confirm');
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
  // The lock is fabricated in the page rather than in the fixture: it lives in a
  // git dir this generated project does not have. What is under test is that the
  // dialog reads the 5s POLL's answer — a dialog that opened saying "nothing is
  // running" because nothing was running when the tab loaded is exactly the
  // reassurance this flow must not give.
  await modelInput.fill('lock-probe');
  await page.waitForTimeout(200);
  await page.evaluate((pid) => {
    RUNSTATUS = { index: null,
      phases: { [pid]: { lock: { hostname: 'other-box', live: true }, claim: null } } };
  }, target.phaseId);
  await saveBtn.click();
  await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
  const lockNote = await page.evaluate(() => {
    const n = document.querySelector('dialog.confirm .cflock');
    return n ? n.textContent : null;
  });
  await page.locator('dialog.confirm [data-cfcancel]').click();
  await page.waitForTimeout(200);
  await page.evaluate(() => { RUNSTATUS = null; renderComp(); });
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

async function shot(page, name, { full = false } = {}) {
  await settle(page);
  await noToast(page, name);
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
      if (!tabs.includes('usage')) {
        fail('panel has no Usage tab — the fixture or the UI is out of date');
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

      await shot(page, 'panel-guards');

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

      await page.click('.tab[data-t=usage]');
      await page.waitForTimeout(600);
      await shot(page, 'panel-usage');

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
      const overflow = await mob.evaluate(() => {
        const de = document.documentElement;
        return { page: de.scrollWidth - de.clientWidth,
                 body: document.body.scrollWidth - de.clientWidth };
      });
      if (overflow.page > 1 || overflow.body > 1) {
        fail(`panel at 390px scrolls sideways: document overflows by ${overflow.page}px `
           + `and body by ${overflow.body}px`);
      } else {
        note('panel at 390px: no horizontal page overflow');
      }
      await shot(mob, 'panel-mobile');
      await mobCtx.close();
      // Deliberately AFTER the last capture. Driving Usage ends in an export, and an
      // export raises a toast — which the dark shot caught and committed, a banner
      // reading "2132 row(s) exported" pinned across a screenshot of the default
      // view. A check that leaves transient UI behind must run where no shutter
      // follows it, not merely be timed to miss one.
      await assertUsageWorks(page);
      await assertViewerIdentity(page);
      // Last of all: it writes to the fixture's manifest and its config, so every
      // check above sees the state it was generated with.
      await assertConfirmFlowWorks(page);
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

main().catch((err) => { console.error(err); process.exit(1); });
