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

      await page.click('.tab[data-t=usage]');
      await page.waitForTimeout(600);
      await shot(page, 'panel-usage');

      await page.click('#theme');
      await page.waitForTimeout(300);
      await shot(page, 'panel-dark');
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
