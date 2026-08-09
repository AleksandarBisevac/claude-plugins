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
import { mkdtempSync, rmSync, mkdirSync, readFileSync, statSync } from 'node:fs';
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
async function startPanel(project) {
  const proc = spawn(PY, [path.join(SCRIPTS, 'panel-server.py'),
                          '--project', project, '--no-open'],
                     { cwd: REPO, stdio: 'ignore' });
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
  // The digits of the rendered `messages` tile.
  const shownMsgs = () => page.evaluate(() => {
    const t = [...document.querySelectorAll('#usage .utile')]
      .find((x) => x.querySelector('.k').textContent === 'messages');
    return t ? parseInt(t.querySelector('.v').firstChild.textContent
      .replace(/\D/g, ''), 10) : null;
  });
  const compare = async (label, body) => {
    const want = await oracle(body); const got = await shownMsgs();
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

async function shot(page, name, { full = false } = {}) {
  await settle(page);
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

      panel = await startPanel(big);
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

      // Settings is rendered by that script, from the field table panel-server.py
      // ships. Both halves are asserted: the cards exist, and every declared setting
      // put a control in the document — so a field added in Python and never wired
      // up in the UI fails here rather than silently not existing.
      const declared = JSON.parse(py([path.join(SCRIPTS, 'panel-server.py'),
                                      '--settings-paths']));
      const rendered = await page.evaluate((paths) => ({
        cards: [...document.querySelectorAll('#guards > .card')].map((c) => c.id),
        missing: paths.filter((p) => !document.getElementById('set-' + p)),
      }), declared);
      if (rendered.cards.length !== 4) {
        fail(`Settings rendered ${rendered.cards.length} group cards, expected 4 `
           + `(the script may not be running at all)`);
      } else if (rendered.missing.length) {
        fail(`Settings declares ${declared.length} config paths but rendered no `
           + `control for: ${rendered.missing.join(', ')}`);
      } else {
        note(`settings: 4 groups, ${declared.length}/${declared.length} controls rendered`);
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
      // Deliberately AFTER the last capture. Driving Usage ends in an export, and an
      // export raises a toast — which the dark shot caught and committed, a banner
      // reading "2132 row(s) exported" pinned across a screenshot of the default
      // view. A check that leaves transient UI behind must run where no shutter
      // follows it, not merely be timed to miss one.
      await assertUsageWorks(page);
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
