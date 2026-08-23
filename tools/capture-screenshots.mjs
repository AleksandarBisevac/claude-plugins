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
 * SO IS THE ENVIRONMENT. A panel reads the machine it runs on — `git config` for the
 * identity it writes as, `~/.claude` for the skills, subagents and MCP servers it
 * lists — and both of those have reached a committed PNG: a maintainer's personal
 * address in four shots, and one developer's hundred-odd installed skills, by name,
 * in `panel-blocks`. Every panel here is therefore handed a demo git identity AND a
 * fixture HOME, and asserts it got exactly those before a shutter opens. Nothing
 * about the product changes; see the fixture-homes section.
 *
 * AND THE TEMP DIR IS PART OF THE PICTURE. The panel prints its project path in the
 * topbar, so the scratch tree sits at a FIXED path, claimed under a lockfile, and
 * two consecutive captures ON ONE MACHINE produce byte-identical PNGs. See
 * claimScratch(). Without that, panel drift could not be detected by comparison at
 * all, which is the only kind of detection a committed PNG supports.
 *
 * "ON ONE MACHINE" IS THE WHOLE OF THE CLAIM, and it is load-bearing rather than
 * cautious (F18). The path is now a LITERAL root — /tmp/audit-shots-<uid> on every
 * POSIX host, the platform root on Windows — because it used to come from
 * `tmpdir()`, which reads TMPDIR: one host under two environments produced two
 * paths, and thirteen panel PNGs "changed" for that reason alone. What remains
 * genuinely per-host is the font rasterisation, which moves the pixels and which
 * no environment variable pins. So the committed PNGs are byte-comparable against
 * a fresh capture from the machine that made them and against nothing else. That limit is not papered over: it is printed,
 * with the machine, by --repro. The three repairs that would each fake a wider claim
 * are named and declined in claimScratch(), including why SOURCE_DATE_EPOCH — which
 * solved exactly this class for the HTML report — does not transfer.
 *
 *     node tools/capture-screenshots.mjs [--out docs/screenshots] [--only report|panel]
 *     node tools/capture-screenshots.mjs --check
 *     node tools/capture-screenshots.mjs --repro [--only report|panel]
 *
 * --check writes nothing. It asserts the DOM facts that the captures depend on —
 * chiefly that progress-bar fills have a real painted width. That assertion is
 * portable, which pixel comparison is not, for the reasons above. Run --check in CI;
 * run the capture locally when a UI change lands.
 *
 * --repro writes nothing into the repo either. It captures twice into throwaway
 * directories on the machine it is running on, byte-compares the two, and prints the
 * result next to that machine. It is the re-derivable form of the reproducibility
 * claim above, which had been measured once, by hand, and written down.
 */
import { spawn, spawnSync, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { rmSync, mkdirSync, readFileSync, statSync, cpSync,
         writeFileSync, readdirSync, appendFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { tmpdir, release } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// --- the extracted modules, re-exported ------------------------------------
// Four concerns moved out of this file into tools/ui-checks/ and are re-exported
// here so every existing importer keeps working while each symbol has ONE home.
// The names below are the shared surface: check-report-interactive.mjs imports
// seven of them, and red-first probes import the CSV readers.
// IMPORTED, then re-exported. A bare `export ... from` is a facade and nothing
// more: it does not bind the name in THIS module's scope, and this file still
// calls several of them - which is how the first cut of this split failed with
// 'newLivenessTally is not defined' on the very next import.
import { csvFields, firstNonRawNumberLine } from './ui-checks/csv.mjs';
import { scriptIndex, resolveScript } from './ui-checks/scripts.mjs';
import { livenessAt, assertStillLive, newLivenessTally,
         assertLivenessWasChecked } from './ui-checks/liveness.mjs';
import { RESPONSIVE_LADDER, measureResponsiveFrame, walkResponsiveLadder,
         assertLadderMeasuredSomething, newLadderTally } from './ui-checks/responsive.mjs';
import { unwiredStages, stageSources } from './ui-checks/wiring.mjs';
// The panel-tab stages. They are NOT re-exported: nothing outside this file
// has ever called them, and a facade for a name with one caller is a second home
// for no reason. What they need is handed over as `stageCtx`, built once in main().
import { assertOverviewWorks, assertHelpDrawerWorks, assertPolicyWorks,
         assertAppearanceWorks,
         assertCompositionColumns } from './ui-checks/stage-tabs.mjs';

export { csvFields, firstNonRawNumberLine, scriptIndex, resolveScript,
         livenessAt, assertStillLive, newLivenessTally, assertLivenessWasChecked,
         RESPONSIVE_LADDER, measureResponsiveFrame, walkResponsiveLadder,
         assertLadderMeasuredSomething, newLadderTally };

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PY = process.env.PYTHON || 'python3';

const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const CHECK = argv.includes('--check');
const REPRO = argv.includes('--repro');
const OUT = path.resolve(REPO, arg('--out', 'docs/screenshots'));

/**
 * The two halves of this capture, and which of them this invocation asked for.
 *
 * `--only` is free text off the command line, and a value naming no leg used to
 * run NOTHING and then print "OK: capture preconditions hold" and exit 0 — a
 * gate reporting success having measured nothing at all, on a typo. That is the
 * one result this file exists to make impossible, and it is exactly the vacuity
 * the width ladder already guards against inside itself
 * (assertLadderMeasuredSomething); this is the same guard one level up, over the
 * run. TWO checks, because they are two different claims: an unknown value is a
 * usage error, and a leg that did not run despite being asked for is a gate
 * failure. `legsRun` is filled by the leg BODIES rather than recomputed here, so
 * an edit to a leg's condition cannot leave this saying the leg ran.
 */
const LEGS = ['report', 'panel'];
const ONLY = arg('--only', 'all');
// --fast: an ITERATION aid, never the gate. It drops the three systematic sweeps
// that dominate the wall clock (measured: the width ladder ~48s of a 218s panel
// leg, focus traversal 27s, the target-size census 6s) and keeps every functional
// assertion. It exists because the full leg is nearly four minutes, which is long
// enough that a person edits three things before running it once — and then cannot
// tell which one broke.
//
// LOUD by construction: what it skipped is printed by name at the end, and the
// closing line does not say the preconditions hold. A quiet fast mode would be a
// gate that lies, which is the failure this whole tool is built against.
const FAST = process.argv.includes('--fast');
const FAST_SKIPPED = [];
const wanted = (leg) => ONLY === 'all' || ONLY === leg;
const legsRun = [];
if (ONLY !== 'all' && !LEGS.includes(ONLY)) {
  console.error(`--only ${JSON.stringify(ONLY)} names no leg of this capture. `
    + `Use one of: ${LEGS.join(', ')} — or leave it off for all of them.`);
  process.exit(2);
}

/** The identity the panel fixture writes as. See where it is installed, below. */
const DEMO_AUTHOR = 'dev@example.com';

/** The endpoint the panel's run-status poll reads. Fixtures for it go HERE. */
const RUNSTATUS_URL = '**/api/runstatus';

const problems = [];
const note = (m) => console.log(`  ${m}`);
const fail = (m) => { problems.push(m); console.log(`  FAIL ${m}`); };

// --- reading a CSV the report exported -----------------------------------------
// --- child processes and the static server -------------------------------------


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
  const proc = spawn(PY, [resolveScript('panel-server.py'),
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

/* ---- liveness: is the page I am measuring still the page I set up? ---------
 *
 * NOT THE SAME THING AS VACUITY, and the two are kept apart on purpose because
 * they fail in opposite directions:
 *
 *   VACUITY  asks "did this step measure ANYTHING?" — assertLadderMeasuredSomething,
 *            the legsRun guard, the --sp-3 read in the density loop, the 200-focus-
 *            stop floor. It catches a check with no input.
 *   LIVENESS asks "is the thing I measured still the thing I set up?" It catches a
 *            check with the WRONG input, which looks nothing like an empty one.
 *
 * A run can be entirely non-vacuous and entirely wrong. F23: a probe validated its
 * own direction by writing `document.body.innerHTML = '<p>x</p>'` and then restored
 * the saved HTML **string**. That puts the markup back and drops every listener the
 * page had bound, so the `.tab` clicks after it were inert and all six tabs were
 * measured as whichever one happened to be open. It passed everything it had — 11 of
 * 11 mutations still went red, no JS error, a full and plausible per-tab result set —
 * and the only tell was that the six numbers were IDENTICAL, found by comparing
 * against an earlier run. Comparing against an earlier run is not a check.
 *
 * The guard is deliberately NOT "did something change". Clicking the tab that is
 * already open legitimately changes nothing, and a guard that fires on a healthy run
 * is a guard everyone learns to route around. It is two facts instead, and each one
 * points at a different culprit:
 *
 *   CONTINUITY — the nodes the product bound its handlers to are still the nodes on
 *   screen. A mark is written on the anchor ELEMENT and a token on `window`. A page
 *   load drops both; an innerHTML rewrite under a surviving script context drops only
 *   the element mark. That asymmetry is the whole reason there are two halves: it is
 *   what tells a HARNESS mutation apart from a navigation, so the message can say
 *   which without guessing.
 *
 *   RESPONSE — after the click, the view the click asked for is the view on screen.
 *   Checked only once continuity holds, so a failure here cannot be the harness
 *   having thrown the listeners away: it is the page not following its own control.
 *
 * WHAT IT CANNOT SEE, AND THE DIRECTION. A rewrite that happens between a navigation
 * and the first liveness call is ADOPTED as the baseline — there is nothing yet to
 * compare against. That is an UNDER-report, the quiet direction, so a clean liveness
 * verdict means "nothing rebuilt the DOM since I last looked here", never "nothing
 * ever rebuilt it". It also says nothing about listeners bound with addEventListener
 * on a node that survived: those are unobservable from script, and a product that
 * removed one would be caught by RESPONSE rather than by CONTINUITY.
 */

// --- liveness: is the page still the page we armed -----------------------------

/** The anchor for every panel liveness check: a `.tab` is server-rendered in
 *  panel.html, is never re-created by panel.js, and is exactly where the product
 *  binds the handler F23 threw away (`t.onclick = () => showTab(...)`). */
const PANEL_LIVE_ANCHOR = '.tab';
const panelLiveness = newLivenessTally();

/**
 * How long tabTo waits before it is willing to say anything is wrong.
 *
 * Generous on purpose, and generous for a stated reason rather than by feel: every
 * panel page here is opened with `waitUntil: 'load'`, and the inline script runs
 * during parsing, so the handler is bound before that promise resolves. The wait is
 * therefore not a guess at how long binding takes — it is headroom over a wait that
 * has already finished, so a slow CI runner cannot turn this into a flake. The cost
 * is paid only by a run that is already failing.
 *
 * The switch itself is a class toggle over panes that are already rendered, so it is
 * held to a much shorter wait: a switch that needs seconds is a defect in its own
 * right, and giving it the wiring wait's headroom would hide that.
 */
const TAB_WIRED_MS = 10000;
const TAB_SWITCH_MS = 3000;

// --- tab navigation, and whether a tab painted ---------------------------------

/**
 * Switch the panel to tab `t` — and prove the page still answers being driven.
 *
 * Every bare `page.click('.tab[data-t=…]')` in this file went through here for one
 * reason: that click is the exact operation F23 measured six times against a page
 * that had stopped listening. A second copy of this rule is how the bug comes back.
 *
 * The landing is WAITED FOR, not asserted on the next tick. A view that renders
 * slowly must never be reported as an inert one; only a wait that runs OUT is
 * evidence of anything. The predicate is derived from the DOM's own tab strip rather
 * than from a list of view ids kept here — a second copy of the panel's TABS would
 * go stale the first time a view was added, and would then assert nothing about it.
 *
 * Returns whether the view landed, so a caller can skip a measurement that would
 * otherwise be taken against the wrong tab.
 */
async function tabTo(page, t) {
  const sel = `.tab[data-t="${t}"]`;
  const live = await assertStillLive(page, PANEL_LIVE_ANCHOR,
    `panel: about to switch to the ${t} tab`,
    { report: fail, tally: panelLiveness });
  if (live !== 'live' && live !== 'armed') return false;
  // Named rather than clicked. Clicking a selector that is not there buys a
  // 30-second Playwright timeout and a stack, which reads as the panel being dead
  // when it is this file that could not find its footing.
  if (!(await page.$(sel))) {
    fail(`panel: no tab control matches ${sel}, so the ${t} view cannot be reached — `
       + 'a fact about the document, not about the view');
    return false;
  }
  // WAITED FOR, and this is a race removed rather than a check added. The tab
  // strip is server-rendered in panel.html, so `waitForSelector('.tab')` is
  // satisfied BEFORE panel.js has run and bound anything: a click landing in that
  // window does nothing, through nobody's fault. Waiting for the handler means the
  // refusal below is about a page that had its chance, and it is the difference
  // between a diagnosis and a flake that teaches people to re-run the gate.
  try {
    await page.waitForFunction((s) => {
      const b = document.querySelector(s);
      return !!b && typeof b.onclick === 'function';
    }, sel, { timeout: TAB_WIRED_MS });
  } catch {
    fail(`panel: ${TAB_WIRED_MS}ms after it appeared, the ${t} tab still carries no `
       + 'click handler, so a click on it can do nothing. panel.js binds '
       + '`t.onclick` at script evaluation, and these ARE the nodes this run '
       + 'armed — so this harness has not replaced them since. That '
       + 'leaves the page script: it never finished running (a syntax error kills '
       + 'the whole inline script while every markup pin still passes), or the '
       + 'binding itself is gone. The JS errors this run collected tell the two '
       + 'apart; this line does not guess between them.');
    return false;
  }
  await page.click(sel);
  let landed = true;
  try {
    await page.waitForFunction((want) => {
      const btn = document.querySelector(`.tab[data-t="${want}"]`);
      const pane = document.getElementById(want);
      if (!btn || !pane) return false;
      const others = [...document.querySelectorAll('.tab')]
        .map((x) => x.dataset.t)
        .filter((id) => id !== want)
        .map((id) => document.getElementById(id))
        .filter(Boolean);
      return !pane.classList.contains('hidden')
        && btn.classList.contains('on')
        && btn.getAttribute('aria-current') === 'true'
        && others.every((p) => p.classList.contains('hidden'));
    }, t, { timeout: TAB_SWITCH_MS });
  } catch {
    landed = false;
  }
  if (landed) return true;
  // Only now — continuity established, the handler present and waited for — is it
  // fair to say anything about the product.
  const st = await page.evaluate((want) => {
    const btn = document.querySelector(`.tab[data-t="${want}"]`);
    const ids = [...document.querySelectorAll('.tab')].map((x) => x.dataset.t);
    return {
      shown: ids.filter((id) => {
        const p = document.getElementById(id);
        return p && !p.classList.contains('hidden');
      }),
      missing: ids.filter((id) => !document.getElementById(id)),
      on: !!btn && btn.classList.contains('on'),
      current: !!btn && btn.getAttribute('aria-current') === 'true',
      wired: !!btn && typeof btn.onclick === 'function',
    };
  }, t);
  if (st.missing.length) {
    fail(`panel: the tab strip names view(s) ${st.missing.join(', ')} that no element `
       + `in the document carries — clicking ${t} cannot show a pane that is not there`);
  } else if (!st.wired) {
    fail(`panel: the ${t} tab lost its click handler between being waited for and `
       + 'being clicked, which is a rebinding this file cannot account for');
  } else {
    fail(`panel: the ${t} tab is still wired and the view did not follow it — after `
       + `the click the visible pane(s) are [${st.shown.join(', ') || 'none'}], the `
       + `control reads on=${st.on} aria-current=${st.current}. The handler ran and `
       + 'left the wrong view on screen, which is the panel\'s tab routing and not '
       + 'this harness.');
  }
  return false;
}

/**
 * Open the Usage tab's Filters fold — and say what it looked like on arrival.
 *
 * TWO JOBS, and the first is mechanical. The usage filters live behind a
 * `<details>` now, and Playwright refuses to type into or select from a control
 * inside a shut one: `element is not visible`, after a 30-second wait that reads
 * as a dead panel rather than as a fold nobody opened. Every measurement in this
 * file that drives a usage filter needs it open, and `tabTo` is the only place
 * that the next leg to be written cannot forget.
 *
 * The second is the half no `'…' in UI_HTML` pin can reach, which is why it is
 * here and not in test__panel_page.py. Whether the tab LEADS with its numbers is
 * a fact about a rendered document: the fold must be shut when the tab is first
 * opened, the chip row must sit above it, and the summary must carry a count
 * whenever something is filtering — a shut fold that says nothing while a filter
 * is on is how a reader concludes the numbers are missing rows. All three are
 * checked once per page, before this function changes the state it is reading.
 *
 * CALLED FROM THE LEGS THAT DRIVE A FILTER, deliberately not from `tabTo`. Every
 * `tabTo(page, 'usage')` would then leave the fold open, including the one the
 * committed `panel-usage` screenshot is taken through — and that shot's whole job
 * is to show the default the tab actually opens in. What a leg needs open, a leg
 * opens.
 */
async function openUsageFilters(page) {
  if (!(await page.$('#usage details[data-uffold]'))) {
    fail('usage: no Filters fold in the tab — the filter controls are not behind '
       + 'a disclosure, so the measurements below are against a layout nobody '
       + 'designed');
    return;
  }
  const st = await page.evaluate(() => {
    const d = document.querySelector('#usage details[data-uffold]');
    const c = document.querySelector('#usage .uchips');
    return {
      open: d.open,
      summary: (d.querySelector('summary') || {}).textContent,
      counted: !!d.querySelector('.fcount'),
      chips: document.querySelectorAll('#usage [data-uchip]').length,
      // DOCUMENT_POSITION_FOLLOWING: the fold comes after the chip row.
      chipsFirst: c ? c.compareDocumentPosition(d) === 4 : null,
    };
  });
  if (!page.__usageFoldSeen) {
    page.__usageFoldSeen = true;
    if (st.open) {
      fail('usage: the Filters fold was already open when the tab was first '
         + 'reached. The tab is meant to open on its numbers; a fold that opens '
         + 'itself puts the wall of controls back above them.');
    } else {
      note('usage: the Filters fold arrives shut');
    }
    if (st.chips && !st.counted) {
      fail(`usage: ${st.chips} filter(s) are on and the shut fold's summary reads `
         + `"${st.summary}" with no count on it — a fold that hides an active `
         + 'filter is how a reader concludes rows are missing');
    }
    if (st.chips && st.chipsFirst === false) {
      fail('usage: the chip row is not above the fold, so a shut fold leaves '
         + 'nothing on screen naming what is scoping every number below it');
    }
  }
  if (!st.open) await page.click('#usage summary[data-ufilters]');
}

/** The defect this whole script exists to prevent. */
/**
 * Does the phases table's `Sort:` control actually MOVE the phase blocks?
 *
 * A substring pin can say the `<option>` was emitted and `_priority.ranks()`
 * stamped a `data-porder`. It cannot say a block moved, because the move walks
 * real siblings inside each segment with `insertBefore` — and the report's own
 * interactive gate cannot say it either, since it drives the COMMITTED example
 * and that plan carries no priority at all, so the control is not on the page.
 * A conditional check on a page that never has the control is spelled exactly
 * like a passing one.
 *
 * So this drives a fixture the gate builds: the committed example plan, copied
 * and then pinned through `set-priority.py` — the real write path, not a hand-
 * edited JSON. `examples/` is untouched, which keeps `gen-demo-manifest.py`'s
 * recorded reason intact ("the fixture's whole point is a plan running in
 * written order", and the committed screenshots show that order).
 *
 * The block boundary is the next phase row OR the next `tr.seghead`. A seghead
 * PRECEDES its segment and stays put, so walking only to the next phase absorbs
 * the following segment's heading into whichever block is last — and "last"
 * changes when the order does, which reads as rows crossing a boundary when
 * nothing moved.
 */
async function assertPhaseOrderMoves(page) {
  const sel = '#audit-sort';
  if (!(await page.$(sel))) {
    fail('report/order: the prioritised fixture rendered no Sort control, so the '
       + 'phase-order checks below would assert nothing about a page nobody ships');
    return;
  }
  const opts = await page.$$eval(`${sel} option`, (o) => o.map((x) => x.value));
  if (opts.join() !== 'plan,priority') {
    fail(`report/order: the Sort control offers ${JSON.stringify(opts)}; the panel `
       + 'offers plan and priority, and one name per surface is the rule');
  }
  if (await page.$eval(sel, (s) => s.value) !== 'plan') {
    fail('report/order: the report does not open in plan order — written order is '
       + 'the plan, and priority is an overlay a reader chooses');
  }

  const shape = () => Array.from(document.querySelectorAll('tr.phase')).map((tr) => {
    const rows = [];
    let n = tr.nextElementSibling;
    while (n && !n.classList.contains('phase') && !n.classList.contains('seghead')) {
      rows.push([n.className, n.getAttribute('data-phase'),
                 n.getAttribute('data-detail') || ''].join('|'));
      n = n.nextElementSibling;
    }
    return { id: tr.getAttribute('data-phase'), seg: tr.getAttribute('data-seg'),
             rank: Number(tr.getAttribute('data-porder')), rows };
  });
  const heads = () => Array.from(document.querySelectorAll('tr.seghead'))
    .map((r) => r.getAttribute('data-seg'));

  const plan = await page.evaluate(shape);
  const planHeads = await page.evaluate(heads);
  if (!plan.length) {
    fail('report/order: no phase rows in the prioritised fixture');
    return;
  }
  if (plan.some((p) => !p.rows.length)) {
    fail('report/order: a phase block reads as having no rows of its own, so the '
       + 'comparison below would be between two empty lists');
    return;
  }

  await page.selectOption(sel, 'priority');
  await page.waitForTimeout(200);
  const prio = await page.evaluate(shape);

  const ids = (s) => s.map((p) => p.id);
  if (ids(plan).slice().sort().join() !== ids(prio).slice().sort().join()) {
    fail(`report/order: re-ordering changed the SET of phases, ${JSON.stringify(ids(plan))} `
       + `-> ${JSON.stringify(ids(prio))}`);
  }
  if (ids(plan).join() === ids(prio).join()) {
    fail('report/order: picking priority moved nothing, so every assertion here is '
       + 'about one list read twice — the fixture must pin a phase that is not '
       + 'already first in its segment');
  }
  for (const seg of [...new Set(prio.map((p) => p.seg))]) {
    const ranks = prio.filter((p) => p.seg === seg).map((p) => p.rank);
    const asc = ranks.slice().sort((a, b) => a - b);
    if (ranks.join() !== asc.join()) {
      fail(`report/order: segment ${seg} lists ranks ${JSON.stringify(ranks)}, which is `
         + 'not the order the server stamped — the client is deciding an order the '
         + 'comparator already decided');
    }
  }
  const bySeg = (s) => JSON.stringify(s.reduce((a, p) => {
    (a[p.seg] = a[p.seg] || []).push(p.id); return a;
  }, {}));
  if (new Set(prio.map((p) => p.seg)).size !== new Set(plan.map((p) => p.seg)).size) {
    fail(`report/order: a phase left its segment, ${bySeg(plan)} -> ${bySeg(prio)} — `
       + 'priority sorts inside a segment and never promotes across one');
  }
  const rowsOf = (s) => JSON.stringify(s.slice()
    .sort((a, b) => a.id.localeCompare(b.id)).map((p) => [p.id, p.rows]));
  if (rowsOf(prio) !== rowsOf(plan)) {
    fail('report/order: a phase did not keep its own rows through the move — the '
       + 'block moved without the rows that belong to it');
  }
  const strays = prio.flatMap((p) => p.rows
    .map((r) => r.split('|')[1]).filter((d) => d !== p.id));
  if (strays.length) {
    fail(`report/order: ${strays.length} row(s) now sit under a phase they do not `
       + 'belong to');
  }

  await page.selectOption(sel, 'plan');
  await page.waitForTimeout(200);
  const back = await page.evaluate(shape);
  if (ids(back).join() !== ids(plan).join()) {
    fail(`report/order: plan order did not come back exactly, ${JSON.stringify(ids(plan))} `
       + `-> ${JSON.stringify(ids(back))}`);
  }
  if (rowsOf(back) !== rowsOf(plan)) {
    fail('report/order: the rows did not come back with their phases');
  }
  if ((await page.evaluate(heads)).join() !== planHeads.join()) {
    fail('report/order: the segment headings moved, so a block was inserted past one');
  }
  note(`report/order: ${ids(plan).join(',')} -> ${ids(prio).join(',')} by priority and `
     + `back, rows and ${planHeads.length} segment heading(s) intact`);
}


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

// --- the responsive width ladder -----------------------------------------------

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
  // Everything below types into or selects from a filter, and the filters live
  // behind a shut <details>. This also records what the fold looked like on
  // arrival, which is the claim no substring pin can make.
  await openUsageFilters(page);
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
    // Not a note. The ledger is GENERATED by this repo, so a dimension with one
    // value means the generator moved and this filter stopped being driven — and
    // a check that stopped running has to say so in the colour that stops a
    // build. The same situation is already a fail two hundred lines down ("the
    // fixture carries no area tags or no author"); this was the odd one out.
    if (!val) {
      fail(`usage: the ${dim} filter has one value in this fixture, so selecting `
         + `one and clearing it again was never driven — the check did not run`);
      continue;
    }
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
        fail('usage: the month bin option is disabled on this fixture, so the bin '
           + 'caption was never driven — the generated ledger spans more than one '
           + 'month by construction, so this means the generator moved and the '
           + 'check stopped running');
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

      // F-P-9: a cell hands over its DATUM through the panel's own tip layer.
      // It used to carry a native `title` and `cursor:help`, which macOS draws as
      // an arrow-with-a-question-mark on every cell whether or not it holds
      // anything — reported as "a question mark regardless of whether there is
      // data". The cursor was the whole of what the reader saw.
      {
        const cell = page.locator('#usage table.uhm tbody i').first();
        const cur = await cell.evaluate((n) => ({
          cursor: getComputedStyle(n).cursor,
          title: n.getAttribute('title'),
          tip: n.getAttribute('data-tip'),
        }));
        if (cur.cursor === 'help') {
          fail('usage: a heatmap cell still asks for `cursor:help` — that is an '
             + 'arrow-with-a-question-mark on macOS, on every cell, and it '
             + 'promises an explanation where the cell hands over a value');
        } else if (cur.title) {
          fail(`usage: a heatmap cell still carries a native title (${cur.title}) — `
             + 'the OS tooltip competes with the panel\'s own tip and arrives a '
             + 'second later, in a different language');
        } else if (!cur.tip || !/\d/.test(cur.tip)) {
          fail(`usage: a heatmap cell carries no readable data-tip (${cur.tip})`);
        } else {
          // ...and it OPENS, in the panel's own box, with that text.
          await page.mouse.move(4, 4);
          await page.waitForTimeout(200);
          await cell.hover();
          await page.waitForTimeout(900);              // past the group's grace
          const tip = await page.evaluate(() => {
            const b = document.getElementById('hinttip');
            return { up: !!b && b.style.display !== 'none',
                     text: b ? b.textContent.trim() : null };
          });
          if (!tip.up || tip.text !== cur.tip) {
            fail(`usage: hovering a heatmap cell did not open the panel tip — `
               + `up=${tip.up} text=${JSON.stringify(tip.text)} `
               + `wanted ${JSON.stringify(cur.tip)}`);
          } else {
            // The GROUP delay: the first cell waits, the next opens on contact.
            // Measured rather than assumed, because "immediate" is the half a
            // reader notices and a fixed sleep would pass either way.
            const second = page.locator('#usage table.uhm tbody i').nth(9);
            await second.hover();
            const t0 = Date.now();
            let ms = null;
            while (Date.now() - t0 < 900) {
              const t = await page.evaluate(() => {
                const b = document.getElementById('hinttip');
                return b && b.style.display !== 'none' ? b.textContent.trim() : null;
              });
              if (t && t !== tip.text) { ms = Date.now() - t0; break; }
              await page.waitForTimeout(20);
            }
            if (ms === null) {
              fail('usage: moving to a second heatmap cell never opened its tip — '
                 + 'inside one grid the tip is meant to follow the pointer');
            } else if (ms > 250) {
              fail(`usage: the second cell's tip took ${ms}ms — inside a warm grid `
                 + 'it must open on contact, or reading the grid is slower than '
                 + 'not reading it');
            } else {
              note(`usage: heatmap tips are the panel's own — first opens after the `
                 + `grace, the next in ${ms}ms, cursor "${cur.cursor}", no native title`);
            }
          }
          await page.mouse.move(4, 4);
          await page.waitForTimeout(150);
        }
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

      // Month names the month and draws THE DAYS OF THAT MONTH.
      //
      // It used to aggregate back to seven weekday rows, sharing one branch with
      // year and all, so Month repainted Week's picture with each cell summed
      // over the four-or-so occurrences of that weekday. Reported as "it should
      // show the days of the month, and for each day the accumulated spend;
      // honestly it looks like a copy of the weekly view."
      //
      // THE WHOLE GRID is compared, not the row count: a count alone cannot say
      // that two controls draw two pictures, and that was the defect. The print
      // is every row label plus every cell's intensity band.
      const gridPrint = () => page.evaluate(() =>
        [...document.querySelectorAll('#usage table.uhm tbody tr')].map((tr) =>
          tr.querySelector('th').textContent + '|'
          + [...tr.querySelectorAll('i')]
            .map((i) => i.getAttribute('data-l')).join('')).join('\n'));
      const rowsIn = (print) => (print ? print.split('\n').length : 0);
      await page.click('#usage [data-uhg=week]');
      await page.waitForTimeout(300);
      const weekPrint = await gridPrint();
      if (rowsIn(weekPrint) !== 7) {
        fail(`usage: Week granularity drew ${rowsIn(weekPrint)} rows — a week is `
           + 'its seven dates, clipped ones included');
      } else {
        note('usage: Week draws the seven dates of one week');
      }
      await page.click('#usage [data-uhg=month]');
      await page.waitForTimeout(300);
      const monPrint = await gridPrint();
      const mon = await page.evaluate(() => {
        const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
        const last = days[days.length - 1];
        const name = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November',
          'December'][+last.slice(5, 7) - 1];
        return {
          want: name + ' ' + last.slice(0, 4),
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          len: new Date(Date.UTC(+last.slice(0, 4), +last.slice(5, 7), 0)).getUTCDate(),
        };
      });
      if (!mon.period.includes(mon.want) || rowsIn(monPrint) !== mon.len) {
        fail(`usage: Month granularity reads "${mon.period}" with `
           + `${rowsIn(monPrint)} rows — want "${mon.want}" over one row per date `
           + `of that month (${mon.len})`);
      } else if (monPrint === weekPrint) {
        fail('usage: Month and Week drew the IDENTICAL grid — two controls, one '
           + 'picture, which is the defect this pair of clicks exists for');
      } else {
        note(`usage: Month names "${mon.want}" over its ${mon.len} dates, and it `
           + 'is not the grid Week drew');
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
      // F-P-13: a granularity the ledger holds exactly ONE of says so, and a dead
      // arrow says why it is dead.
      //
      // Reported as "the filters do not work — Year instead of Month shows the
      // same chart". Two things were true at once: month, year and all shared one
      // row builder (fixed in shared/calendar.js, and the Month clicks above are
      // where that is checked), AND a ledger inside one calendar year has no
      // neighbouring year holding tokens, so both arrows park. This block is the
      // second half. Its predicate did not change with the reshape — what changed
      // is the reason it gives: a grain the ledger holds one period of cannot
      // step, and its window is the whole ledger, so every cell in it is a cell
      // All already shows. Nothing is lost by withholding it, because the finer
      // grains stay on the ladder.
      {
        const g = await page.evaluate(async () => {
          const out = {};
          const days = [...new Set(USAGE.facts.map((f) => f[F.ts].slice(0, 10)))].sort();
          out.span = [days[0], days[days.length - 1]];
          out.oneYear = days[0].slice(0, 4) === days[days.length - 1].slice(0, 4);
          out.oneMonth = days[0].slice(0, 7) === days[days.length - 1].slice(0, 7);
          return out;
        });
        const readNav = () => page.evaluate(() => ({
          period: document.querySelector('#usage [data-uhmperiod]').textContent,
          offered: [...document.querySelectorAll('#usage [data-uhg]')]
            .map((b) => b.getAttribute('data-uhg')),
          why: (document.querySelector('#usage [data-uhmwhy]') || {}).textContent || null,
          armReasons: ['prev', 'next'].map((d) => {
            const a = document.querySelector(`#usage [data-uhm=${d}]`);
            return { d, off: !!a.disabled, why: a.getAttribute('data-tip') };
          }),
        }));
        const nav = await readNav();
        // A granularity the ledger holds one period of is NOT OFFERED. It used to
        // be offered-and-dimmed; the same reader reported that twice as broken ("I
        // can still pick them and the grid does not change"), which is what a
        // dimmed control that still accepts a click earns.
        if (g.oneYear && nav.offered.includes('year')) {
          fail(`usage: the ledger (${g.span[0]}..${g.span[1]}) is inside one year, so Year `
             + `can neither step nor reach a cell All is missing — it must not be `
             + `offered: ` + JSON.stringify(nav.offered));
        } else if (g.oneYear && !/Year/.test(nav.why || '')) {
          fail('usage: Year is missing from the ladder with nothing saying why — a gap '
             + `is not an explanation: why=${JSON.stringify(nav.why)}`);
        } else if (g.oneYear && !new RegExp(g.span[0]).test(nav.why || '')) {
          fail(`usage: the reason omits the span that causes it: ${JSON.stringify(nav.why)}`);
        } else {
          note(`usage: Year is not offered on a single-year ledger, and the reason says `
             + `which question cannot be asked yet — "${(nav.why || '').trim()}"`);
        }
        // The half that stops all of this being satisfied by an empty ladder: a
        // granularity that genuinely narrows MUST still be there. This fixture
        // spans more than one month, so Month is live and clickable.
        if (!g.oneMonth && !nav.offered.includes('month')) {
          fail(`usage: Month is missing on a ledger spanning ${g.span[0]}..${g.span[1]}, `
             + 'where it genuinely narrows — the rule cannot be satisfied by hiding '
             + 'everything');
        } else if (!g.oneMonth) {
          await page.click('#usage [data-uhg=month]');
          await page.waitForTimeout(250);
          const m = await readNav();
          if (/whole ledger/.test(m.period)) {
            fail(`usage: the period line still claims a degenerate window: "${m.period}"`);
          } else if (m.armReasons.some((a) => a.off && !a.why)) {
            fail('usage: an arrow is disabled with no reason on it — a dead control that '
               + `says nothing reads as a broken one: ${JSON.stringify(m.armReasons)}`);
          } else {
            note(`usage: Month is offered and narrows — "${m.period}", arrows `
               + `${m.armReasons.map((a) => a.d + (a.off ? ':' + a.why : ':live')).join(' ')}`);
          }
        }
      }

      await page.click('#usage [data-uhg=all]');
      await page.waitForTimeout(200);
      // All is the seven weekday aggregates, and after the reshape it is the ONLY
      // rung that draws them. Week is also seven rows, so a count cannot separate
      // the two and the fingerprint has to — this is the closest pair the ladder
      // still has.
      const allPrint = await gridPrint();
      if (rowsIn(allPrint) !== 7) {
        fail(`usage: All drew ${rowsIn(allPrint)} rows — it is the weekly rhythm of `
           + 'the whole span, which is seven');
      } else if (allPrint === weekPrint || allPrint === monPrint) {
        fail('usage: All drew the same grid as another granularity — every rung '
           + 'must partition the period its own way');
      } else {
        note('usage: All draws the seven weekday aggregates, and no other rung '
           + 'draws that grid');
      }
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
/**
 * SC 2.4.11 Focus Not Obscured (Minimum, AA): a control that takes focus may not
 * be ENTIRELY hidden by author content.
 *
 * There was no check for this, and the absence was easy to miss because one
 * looks like it: the hit test in `measureResponsiveFrame` excuses sticky chrome
 * through `escapable`, and that excuse is CORRECT for the question it asks —
 * "is this control buried" — because the reader can scroll a bar off a resting
 * layout. 2.4.11 asks a different question. A keyboard user does not scroll
 * first; the browser scrolls the control just into view and stops, which with
 * pinned chrome lands it underneath. Nothing measured that until this.
 *
 * Drives REAL Tab presses rather than calling `.focus()`: programmatic focus is
 * a different path in the engine, and a probe in this repo has already reported
 * a confident wrong answer by taking it.
 */
// --- accessibility: target size and the LIN census -----------------------------

/**
 * SC 2.5.8 Target Size across DENSITIES (F30).
 *
 * `--sp-*` are scaled by `layout.density`, and the spacing migration keeps moving
 * declarations onto that scale — so a control that clears 24px today can be
 * walked under it by `compact` tomorrow without a line of CSS changing. Measured
 * 2026-08-19 it does not happen (175/176/175 under 24 across the three, which is
 * the glyph size of shapes whose target comes from an `::after` overlay). This is
 * here so that stays true rather than being remembered as true.
 *
 * Compares densities against each other rather than against 24: the register in
 * `test__panel_page.py` owns the absolute judgement, including which shapes lean
 * on an overlay. What this asks is narrower and is the thing density can break —
 * did any control SHRINK when the scale did.
 */
async function assertTargetSizeAcrossDensities(page) {
  const SEL = 'button,[role=button],a[href],input:not([type=hidden]),select,'
            + 'textarea,summary,[tabindex]:not([tabindex="-1"])';
  const TABS = ['guards', 'comp'];
  const read = () => page.evaluate((sel) => {
    const out = { min: {}, n: 0 };
    document.querySelectorAll(sel).forEach((n) => {
      if (!n.getClientRects().length) return;
      const r = n.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const key = n.tagName.toLowerCase()
        + (n.className && n.className.toString().trim()
           ? '.' + n.className.toString().trim().split(/\s+/).slice(0, 2).join('.') : '');
      const min = Math.min(r.width, r.height);
      if (!(key in out.min) || min < out.min[key]) out.min[key] = Math.round(min * 10) / 10;
      out.n += 1;
    });
    return out;
  }, SEL);

  const seen = {}, counts = {};
  for (const density of ['comfortable', 'compact', 'spacious']) {
    await tabTo(page, 'look');
    await page.waitForTimeout(250);
    const btn = await page.$(`#look [data-thdensity=${density}]`);
    if (!btn) { fail(`2.5.8/density: no control for density=${density}`); return; }
    await btn.click();
    await page.waitForTimeout(350);
    // The vacuity guard, and it is the whole reason this can be believed: three
    // rounds that measured the same page would report "no shrinkage" and mean
    // nothing by it. Read the token the density is supposed to move.
    const sp3 = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--sp-3').trim());
    const want = { comfortable: '1rem', compact: '.8rem', spacious: '1.25rem' }[density];
    if (sp3 !== want) {
      fail(`2.5.8/density: --sp-3 reads "${sp3}" under density=${density}, expected `
         + `"${want}" — the density did not apply, so any comparison below is three `
         + 'readings of one page');
      return;
    }
    const merged = {};
    let controls = 0;
    for (const t of TABS) {
      await tabTo(page, t);
      await page.waitForTimeout(250);
      const got = await read();
      controls += got.n;
      for (const k of Object.keys(got.min)) {
        if (!(k in merged) || got.min[k] < merged[k]) merged[k] = got.min[k];
      }
    }
    seen[density] = merged;
    counts[density] = controls;
  }
  await tabTo(page, 'look');
  await page.waitForTimeout(200);
  const back = await page.$('#look [data-thdensity=comfortable]');
  if (back) { await back.click(); await page.waitForTimeout(300); }

  const base = seen.comfortable || {};
  const shapes = Object.keys(base);
  // The bar is on CONTROLS, not distinct shapes. A shape count is a poor guard:
  // these two tabs carry 13 shapes across 359 controls, so a threshold set by
  // feel (20) failed a walk that had reached everything — measured, not guessed,
  // after that guard refused a number nobody had derived. Controls is the
  // quantity that says the forms rendered; shapes is what a UI edit legitimately
  // moves.
  if ((counts.comfortable || 0) < 150) {
    fail(`2.5.8/density: only ${counts.comfortable || 0} control(s) measured across `
       + `${TABS.join(' + ')} — the walk is not reaching the forms, so "nothing `
       + 'shrank" is not a claim about anything');
    return;
  }
  // CROSSING the floor, not moving. Shrinking is what density IS -- nine shapes
  // move here and that is the feature. The failure is a shape that clears 24 at
  // the default density and stops clearing it at another, because the register in
  // test__panel_page.py graded it "ok" on a measurement taken at one density.
  // A first version of this asserted non-movement and failed on the feature.
  //
  // Shapes already under 24 at the default are skipped on purpose: those are the
  // glyph buttons whose target comes from an ::after overlay declared in px, and
  // grading them is the register's job, not this one's.
  const crossed = [];
  for (const d of ['compact', 'spacious']) {
    for (const k of shapes) {
      if (base[k] < 24) continue;
      const now = (seen[d] || {})[k];
      if (now !== undefined && now < 24) {
        crossed.push(`${k} ${base[k]}→${now} under ${d}`);
      }
    }
  }
  if (crossed.length) {
    fail(`2.5.8 target size crosses the 24px floor with density: `
       + `${crossed.length} shape(s) — ${crossed.slice(0, 4).join('; ')}`
       + `${crossed.length > 4 ? `; +${crossed.length - 4} more` : ''}. `
       + 'Declare the floor (min-width/min-height) rather than clearing it by '
       + 'coincidence, and update the register.');
  } else {
    note(`2.5.8: ${shapes.length} shapes over ${counts.comfortable} controls, `
       + 'measured at all three densities (--sp-3 confirmed 1rem/.8rem/1.25rem) '
       + '— none that clears 24px at the default stops clearing it');
  }
}

/**
 * SC 2.5.3 Label in Name (AA). When a control carries a VISIBLE text label, its
 * accessible name must CONTAIN that text -- speech users say what they can see.
 *
 * Kept HERE rather than in a scratch harness on purpose. F28's figure ("91
 * instances across 41 shapes") was measured by a probe that then vanished, so by
 * the time anyone read the number the population had changed and nothing could
 * re-derive it. A criterion measured once is a criterion nobody is watching.
 *
 * Four things this got wrong before its numbers were worth reading, each kept as
 * a rule rather than a memory:
 *
 *  1. A BUTTON or LINK is labelled by its OWN text. Letting one fall through to
 *     the caption of the row it sits in charges that caption to every control in
 *     the row -- 233 of 340 "failures", 53 of 53 on one tab. A 100% rate is a
 *     harness defect until proven otherwise.
 *  2. Every panel tab stays in the DOM (showTab only toggles .hidden), so marks
 *     must be namespaced and cleared. A per-tab counter collides with marks left
 *     on other tabs and DOM.querySelector returns the first match in document
 *     order -- an element from a tab nobody is looking at.
 *  3. Compare WORDS, not characters, and build the visible string by joining TEXT
 *     NODES the way the browser assembles a name. `textContent` concatenates them
 *     raw, so a row rendering "P18 Web pass" comes back "P18Web pass".
 *  4. An ICON is not a visible text label. The ⓘ renders one glyph; under a
 *     substring test it PASSED for the wrong reason, because "i" occurs inside
 *     "What is this?".
 *
 * An empty accessible name is SC 4.1.2, a worse and different defect, and is
 * counted separately -- never folded in, which would inflate this figure with
 * cases 2.5.3 has nothing to say about.
 */
const LIN_CENSUS = ({ rootSel, pfx }) => {
  // A selector that matches nothing must FAIL, not fall back to `document`:
  // falling back silently widens the scope to the whole page and reports a
  // healthy count for a walk that never reached the thing it was aimed at.
  const root = document.querySelector(rootSel);
  if (!root) return { missing: rootSel };
  document.querySelectorAll('[data-lin253]').forEach((n) => n.removeAttribute('data-lin253'));
  const SEL = 'button,select,textarea,a[href],[role="button"],[tabindex]:not([tabindex="-1"]),'
    + 'input:not([type="hidden"])';
  // A rect is NOT enough. Content inside a CLOSED <details> keeps its layout box
  // in Chromium -- 52x23 for a filter chip -- while the accessibility tree marks
  // it ignored/notRendered, correctly, because nobody can see it. Judged on the
  // rect alone, fifteen hidden filter chips read as "no accessible name" and
  // this gate published that number. A control nobody can reach is not a control
  // with a defect. <summary> is the exception: it IS rendered while its details
  // is shut, and it is the thing you click to open it.
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return false;
    if (getComputedStyle(e).visibility === 'hidden') return false;
    const shut = e.closest('details:not([open])');
    if (shut && !e.closest('summary')) return false;
    return true;
  };
  const norm = (t) => (t || '').replace(/[\u2013\u2014\u2018\u2019\u201c\u201d]/g, ' ')
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim().toLowerCase();
  const strip = (el) => {
    const c = el.cloneNode(true);
    c.querySelectorAll('.hint,button,input,select,textarea,code.k2').forEach((n) => n.remove());
    const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
    const parts = []; let t;
    while ((t = w.nextNode())) { const v = (t.nodeValue || '').trim(); if (v) parts.push(v); }
    return parts.join(' ');
  };
  const out = []; let i = 0;
  for (const e of root.querySelectorAll(SEL)) {
    if (!vis(e)) continue;
    let visible = '', src = '';
    const isCmd = /^(BUTTON|A)$/.test(e.tagName) || e.getAttribute('role') === 'button';
    if (isCmd) {
      visible = strip(e); src = 'self';
      if (!norm(visible) && e.labels && e.labels.length) {
        visible = [...e.labels].map(strip).join(' '); src = 'labels';
      }
    } else {
      if (e.labels && e.labels.length) { visible = [...e.labels].map(strip).join(' '); src = 'labels'; }
      if (!norm(visible) && e.getAttribute('aria-labelledby')) {
        visible = e.getAttribute('aria-labelledby').split(/\s+/)
          .map((id) => { const t = document.getElementById(id); return t ? strip(t) : ''; }).join(' ');
        src = 'labelledby';
      }
      if (!norm(visible)) {
        const wrap = e.closest('label,.gf,.f,.viewpick');
        const sp = wrap && wrap.querySelector('.lbl,.tbl');
        const fields = wrap ? wrap.querySelectorAll('input,select,textarea') : [];
        if (sp && fields.length === 1) { visible = strip(sp); src = 'span'; }
      }
    }
    if (!norm(visible)) continue;
    if (norm(visible).replace(/\s+/g, '').length < 2) continue;   // an icon is not a text label
    const mark = pfx + '-' + (i++);
    e.setAttribute('data-lin253', mark);
    out.push({ mark, visible, src, tag: e.tagName.toLowerCase(), id: e.id || '',
      cls: typeof e.className === 'string' ? e.className : '' });
  }
  return out;
};

const linWords = (t) => (t || '').replace(/[\u2013\u2014\u2018\u2019\u201c\u201d]/g, ' ')
  .replace(/[^\p{L}\p{N}]+/gu, ' ').trim().toLowerCase().split(' ').filter(Boolean);
const linContains = (hay, needle) => {
  if (!needle.length) return true;
  for (let i = 0; i + needle.length <= hay.length; i++) {
    let ok = true;
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) { ok = false; break; }
    if (ok) return true;
  }
  return false;
};

async function linCensus(page, rootSel, pfx) {
  const cands = await page.evaluate(LIN_CENSUS, { rootSel, pfx });
  if (!Array.isArray(cands)) {
    fail(`SC 2.5.3 census: selector ${JSON.stringify(cands.missing)} matched nothing — `
       + `the walk never reached the area it names, so any verdict from it is empty`);
    return [];
  }
  if (!cands.length) return [];
  const cdp = await page.context().newCDPSession(page);
  const rows = [];
  try {
    await cdp.send('DOM.enable'); await cdp.send('Accessibility.enable');
    const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true });
    for (const c of cands) {
      const { nodeId } = await cdp.send('DOM.querySelector',
        { nodeId: root.nodeId, selector: `[data-lin253="${c.mark}"]` });
      if (!nodeId) continue;
      // Never getFullAXTree: it stops at 1000 nodes and says nothing about it.
      const { nodes } = await cdp.send('Accessibility.getPartialAXTree',
        { nodeId, fetchRelatives: false });
      const n = nodes && nodes[0];
      // The browser's own verdict on whether this node is in the tree at all.
      // `notRendered` and the aria-hidden/inert family mean deliberately absent,
      // which is an answer and not a finding; anything else means the node is
      // present and unnamed, which is.
      const HIDDEN_ON_PURPOSE = ['notRendered', 'ariaHiddenElement',
        'ariaHiddenSubtree', 'inertElement', 'inertSubtree', 'presentationalRole',
        'uninteresting', 'notVisible'];
      const why = (n && n.ignoredReasons || []).map((r) => r.name);
      if (n && n.ignored && why.some((r) => HIDDEN_ON_PURPOSE.indexOf(r) >= 0)) continue;
      const accName = n && n.name ? String(n.name.value || '') : '';
      const v = linWords(c.visible), a = linWords(accName);
      let verdict;
      if (!v.length) verdict = 'n/a';
      else if (!a.length) verdict = 'NO-NAME';
      else verdict = linContains(a, v) ? 'pass' : 'FAIL';
      rows.push({ ...c, accName, verdict });
    }
  } finally { await cdp.detach(); }
  return rows;
}

// --- accessibility: hints, names, focus, identity ------------------------------

/**
 * Reading the help must not change the setting it explains.
 *
 * The ⓘ is a control inside another control's activation area. While the wrapper
 * was a `<label>`, clicking the hint activated the labelled field: MEASURED in
 * Chromium before the F41 repair, **6 of 12 checkbox+hint pairs flipped** — six
 * settings a user silently changed by reading about them. The F41 fix made those
 * wrappers `<span>`s, and this is the gate that stops the shape returning, since
 * the defect is invisible to every substring pin (the markup was valid, the names
 * were fine, nothing threw).
 *
 * Covers checkbox/radio checked state, select value and text value, because the
 * activation-area bug is not specific to checkboxes — it is specific to a control
 * nested inside another control's hit area, and a check that only knew about
 * checkboxes would go green on the first `<select>` that regressed.
 *
 * Every value it disturbs is put back: this runs in a file that also takes
 * screenshots, and a probe that left a setting flipped would publish it.
 */
async function assertHintClickIsInert(page, areas) {
  let pairs = 0;
  const changed = [];
  for (const a of areas) {
    if (a.show) await a.show();
    const res = await page.evaluate(async (sel) => {
      const root = document.querySelector(sel);
      if (!root) return { missing: sel };
      const out = [];
      const fields = [...root.querySelectorAll('input,select,textarea')]
        .filter((f) => f.type !== 'hidden');
      for (const f of fields) {
        const wrap = f.closest('label,.f,.gf,.lbl,.row');
        const hint = wrap && wrap.querySelector('.hint');
        if (!hint || hint === f) continue;
        const was = (f.type === 'checkbox' || f.type === 'radio') ? f.checked : f.value;
        hint.click();
        await new Promise((r) => setTimeout(r, 40));
        const now = (f.type === 'checkbox' || f.type === 'radio') ? f.checked : f.value;
        out.push({ id: f.id || f.name || f.type, moved: now !== was });
        if (now !== was) {                       // never leave it disturbed
          if (f.type === 'checkbox' || f.type === 'radio') f.checked = was;
          else f.value = was;
        }
      }
      return { out };
    }, a.sel);
    if (res.missing) {
      fail(`hint-inertness: selector ${JSON.stringify(res.missing)} matched nothing, `
         + `so this area was never examined`);
      continue;
    }
    pairs += res.out.length;
    changed.push(...res.out.filter((r) => r.moved).map((r) => `${a.name}/${r.id}`));
    // Clicking the ⓘ OPENS THE HELP DRAWER — a <dialog> that then intercepts
    // pointer events for every stage after this one. The first version of this
    // probe restored the field values and left the drawer standing, and the
    // next stage timed out clicking through it. Restoring what you disturbed
    // means the whole page, not the value you were watching.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(120);
  }
  // ...and ASSERT the restore, rather than trusting the Escape landed. A probe
  // that half-restores is worse than one that does not restore at all: the
  // failure surfaces inside somebody else's stage, wearing their name.
  const stillOpen = await page.evaluate(() =>
    document.querySelectorAll('dialog[open]').length);
  if (stillOpen) {
    fail(`hint-inertness left ${stillOpen} dialog(s) open, which will intercept `
       + `pointer events for every stage after this one`);
  }
  // Vacuity: a page where no field sits beside a hint cannot test this at all.
  if (pairs < 5) {
    fail(`hint-inertness: only ${pairs} field(s) sit beside a ⓘ across `
       + `${areas.length} area(s) — too few to have tested anything, so a clean `
       + `result here would mean nothing`);
    return;
  }
  if (changed.length) {
    fail(`hint-inertness: clicking the ⓘ CHANGED ${changed.length} of ${pairs} `
       + `control(s) — reading the help edits the setting it explains: `
       + `${changed.slice(0, 8).join(', ')}`);
  } else {
    note(`panel: reading the help changes nothing — ${pairs} control(s) beside a ⓘ, `
       + `none moved when it was clicked`);
  }
}

async function assertLabelInName(page, areas, surface) {
  const all = [];
  for (const a of areas) {
    if (a.show) await a.show();
    const rows = await linCensus(page, a.sel, `${surface}_${a.name}`);
    all.push(...rows.map((r) => ({ ...r, area: a.name })));
  }
  const bad = all.filter((r) => r.verdict === 'FAIL');
  const noname = all.filter((r) => r.verdict === 'NO-NAME');
  // Vacuity: a census that reached nothing reports a page with nothing wrong.
  // The floor is per SURFACE and deliberately well under the measured counts
  // (233 panel + report at the time of writing), so it fails a walk that broke
  // rather than a page that changed.
  if (all.length < 20) {
    fail(`${surface}: SC 2.5.3 census reached only ${all.length} labelled control(s) `
        + `across ${areas.length} area(s) — the walk is not reaching the page, so `
        + `"no failures" would mean nothing`);
    return;
  }
  if (bad.length) {
    const shown = bad.slice(0, 6).map((r) =>
      `${r.tag}${r.id ? '#' + r.id : '.' + (r.cls || '?').split(' ')[0]} `
      + `[${r.area}] shows ${JSON.stringify(r.visible.slice(0, 40))} `
      + `but is named ${JSON.stringify(r.accName.slice(0, 40))}`);
    fail(`${surface}: SC 2.5.3 Label in Name — ${bad.length} control(s) whose `
        + `accessible name does not contain their visible label, so a speech user `
        + `saying what they see cannot reach them: ${shown.join(' · ')}`
        + (bad.length > 6 ? ` (+${bad.length - 6} more)` : ''));
  } else {
    note(`${surface}: SC 2.5.3 Label in Name — ${all.length} control(s) with a visible `
     + `text label, every accessible name contains it`);
  }
  // SC 4.1.2 is a SEPARATE criterion and now a separate FAILURE. It was a note
  // while the number was untrustworthy — fifteen of the twenty-six turned out
  // to be inside a closed <details> — and a number nobody can act on has no
  // business failing a build. Both surfaces read zero now, so it gates: a
  // control the browser gives no name is worse than one whose name disagrees
  // with its label, because a screen-reader user gets nothing at all.
  if (noname.length) {
    const shown = noname.slice(0, 6).map((r) =>
      `${r.tag}${r.id ? '#' + r.id : '.' + (r.cls || '?').split(' ')[0]} [${r.area}] `
      + `shows ${JSON.stringify(r.visible.slice(0, 36))}`);
    fail(`${surface}: SC 4.1.2 — ${noname.length} focusable control(s) with NO `
       + `accessible name, so a screen reader announces nothing at all for them: `
       + `${shown.join(' · ')}`
       + (noname.length > 6 ? ` (+${noname.length - 6} more)` : ''));
  }
}

async function assertFocusNotObscured(page) {
  const TABS = ['guards', 'comp', 'over', 'usage', 'policy', 'props', 'look'];
  const STEPS = 30;
  // Measured after the browser's own scroll-into-view AND anything the page does
  // in response to focus have landed. Reading immediately measures the position
  // the control is leaving — which once credited a fix with 10 repairs when it
  // had made 31.
  const settle = () => page.evaluate(() => new Promise((r) =>
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 30)))));
  const read = () => page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body || !el.getClientRects().length) return null;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    const cx = r.left + r.width / 2;
    const pts = [[cx, r.top + 1], [cx, r.top + r.height / 2], [cx, r.bottom - 1],
                 [r.left + 1, r.top + 1], [r.right - 1, r.bottom - 1]];
    let on = 0, covered = 0, by = null;
    for (const [x, y] of pts) {
      if (x < 0 || y < 0 || x > innerWidth - 1 || y > innerHeight - 1) continue;
      on += 1;
      const hit = document.elementFromPoint(x, y);
      if (hit === el || (hit && (el.contains(hit) || hit.contains(el)))) continue;
      for (let p = hit; p && p !== document.body; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.position === 'fixed' || cs.position === 'sticky') {
          covered += 1; by = (p.className || p.tagName).toString().split(/\s+/)[0]; break;
        }
      }
    }
    if (!on) return null;
    return { on, covered, by,
             what: el.tagName.toLowerCase()
                 + (el.id ? '#' + el.id : '')
                 + ((el.className || '').toString().trim()
                    ? '.' + (el.className || '').toString().trim().split(/\s+/)[0] : '') };
  });

  let stops = 0;
  const bad = [];
  for (const t of TABS) {
    for (const key of ['Tab', 'Shift+Tab']) {
      await tabTo(page, t);
      await page.waitForTimeout(250);
      await page.evaluate(() => { window.scrollTo(0, 0);
        if (document.activeElement) document.activeElement.blur(); });
      for (let i = 0; i < STEPS; i += 1) {
        await page.keyboard.press(key);
        await settle();
        const r = await read();
        if (!r) continue;
        stops += 1;
        if (r.covered === r.on) bad.push(`${t}/${key}: ${r.what} entirely under .${r.by}`);
      }
    }
  }

  // The vacuity guard, and it is not decoration: every count below narrows this
  // set, so a walk that focused nothing would report a panel with no obscured
  // control on it. Twelve walks that reach almost nothing is the shape a broken
  // selector produces, and it would otherwise read as a clean pass.
  if (stops < 200) {
    fail(`2.4.11: only ${stops} focus stop(s) were measured across ${TABS.length} `
       + 'tabs in both directions — the walk is not reaching the form, so "no '
       + 'obscured control" is not a claim about anything');
    return;
  }
  if (bad.length) {
    fail(`2.4.11 Focus Not Obscured: ${bad.length} of ${stops} focus stop(s) land `
       + `ENTIRELY under pinned chrome — ${bad.slice(0, 4).join('; ')}`
       + (bad.length > 4 ? `; +${bad.length - 4} more` : ''));
  } else {
    note(`2.4.11: ${stops} focus stops across six tabs, both directions — none `
       + 'entirely obscured by pinned chrome');
  }
}

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
  if (!pick) {
    fail('usage: the ledger records no author, so "my spend" was never driven — '
       + 'and a check that quietly returns without running is the one result a '
       + 'gate must not report as a pass');
    return;
  }
  const was = await page.evaluate((name) => {
    const prev = STATE.viewer.author; STATE.viewer.author = name; renderUsage();
    return prev;
  }, pick.name);
  await page.waitForTimeout(250);
  try {
    // The my-spend control sits in the filter rows, so it is behind the fold.
    await openUsageFilters(page);
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

// --- the write-confirmation flow -----------------------------------------------

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
  // NOT `.first()` over every task row: a row whose task (or whose phase) has
  // finished is frozen, and its model box is disabled, so a fill() against it
  // waits for an element that will never become editable and fails as a timeout
  // rather than as the layout claim this function makes. The subject was always
  // "a model box a reader can change" — `:not([data-frozen])` says so outright.
  const inputs = page.locator('#comp tr.task:not([data-frozen]) .tmodel input');
  const n = Math.min(3, await inputs.count());
  if (n < 2) { fail('composition: fewer than two task rows to edit for the confirm shot'); return; }
  for (let i = 0; i < n; i++) {
    const box = inputs.nth(i);
    const was = await box.inputValue();
    await box.fill(was === 'opus' ? 'sonnet' : 'opus');
  }
  await page.waitForTimeout(200);
  await page.locator('#comp').getByRole('button', { name: 'Save plan & models' }).click();
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  // The ASSEMBLED page, not a file. This used to read `ui/panel.js` by literal
  // path, with a long argument for why that join could not go stale — and then
  // panel.js was cut into twenty-one parts and the path stopped existing. The
  // lesson is not "pick a better path": the subject of this guard is what the
  // POLL OWNS IN THE PAGE, so the page is what it should have been reading. Which
  // part `pollRunStatus` happens to sit in is not a fact this check needs, and
  // asking for it is how a check comes to depend on a filing decision.
  //
  // Reached through the resolver rather than by joining the SCRIPTS constant, so no
  // directory under scripts/ is spelled here either; `_panel_ui.py` carries its
  // own path preamble, so putting the directory it lives in on sys.path is enough
  // for it to find the anchor and assemble.
  const panelUiDir = path.dirname(resolveScript('_panel_ui.py'));
  const src = py(['-c', 'import sys; sys.path.insert(0, sys.argv[1]); import _panel_ui; '
                      + 'sys.stdout.write(_panel_ui.raw_template())', panelUiDir]);
  const at = src.indexOf('async function pollRunStatus');
  if (at < 0) {
    fail('panel: pollRunStatus is gone from the assembled panel page — the '
       + 'polled-state guard is reading a function that no longer exists and can '
       + 'no longer protect anything');
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
/**
 * Wait for the confirm dialog — and when it never opens, say WHY.
 *
 * F-P-17. This wait timed out once in a full run and passed on every re-run. A
 * bare timeout is the least useful failure a gate can produce: it says the dialog
 * is absent and nothing about the panel that failed to open it, so the only way
 * forward was guessing, and each guess costs a ~160s run.
 *
 * Two plausible causes were tested and DISPROVED before this was written: a poll
 * redraw landing immediately before the Save click, and a redraw after the field
 * was blurred. Both left the gate green, so the panel is robust to the redraw at
 * that point and the cause is still unknown. Rather than "fix" a mechanism that
 * was just ruled out, this makes the next occurrence diagnose itself in one shot:
 * whether Save was disabled, whether anything was actually pending, which dialogs
 * existed, and what the last toast said.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<void>} resolves when the dialog is open; throws with state
 */
async function awaitConfirmDialog(page) {
  try {
    // The ONE real wait. Written with the selector inline rather than reusing a
    // constant: an earlier edit replaced this very line by a substring match and
    // turned the helper into a call to itself, which blew the stack and reported
    // "the dialog never opened" about a dialog the dump then showed as open.
    await page.waitForSelector('dialog.confirm[open]', { timeout: 5000 });
    return;
  } catch (timedOut) {
    let state;
    try {
      state = await page.evaluate(() => {
        const save = [...document.querySelectorAll('button')]
          .find((b) => /^Save\b/.test((b.textContent || '').trim()));
        const discard = document.querySelector('[data-discard]');
        return {
          dialogs: [...document.querySelectorAll('dialog')]
            .map((d) => (d.className || '(no class)') + (d.open ? ':open' : ':closed')),
          saveButton: save
            ? { text: save.textContent.trim(),
                dead: !!save.disabled || save.getAttribute('aria-disabled') === 'true' }
            : 'no Save button on screen',
          discardLabel: discard ? discard.textContent.trim() : null,
          toast: ((document.querySelector('#toast') || {}).textContent || '').trim() || null,
          pending: typeof EDITS === 'object' && typeof editRows === 'function'
            ? Object.keys(EDITS).map((k) => k + ':' + (editRows(k) || []).length).join(' ')
            : 'EDITS/editRows not reachable',
        };
      });
    } catch (dumpFailed) {
      state = { dumpFailed: String(dumpFailed).split('\n')[0] };
    }
    throw new Error('the confirm dialog never opened within 5s (F-P-17). Panel '
      + 'state at that moment: ' + JSON.stringify(state));
  }
}

/**
 * The first task a reader could actually change, as the page itself decides it.
 *
 * A finished task, or any task inside a finished phase, is frozen by design, and
 * `fill()` against a disabled box does not fail as the claim its caller is making
 * - it fails sixty retries later as a TimeoutError, which reads like a hang. So
 * the choice is made up front, and made with `segOf`: the panel's own segment
 * classifier, reached through the page rather than restated here, so this cannot
 * drift from the rule the UI applies.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<{id: string, phaseId: string, was: (string|null)}|null>}
 *   the task, or null when the fixture has no editable one at all
 */
async function firstEditableTask(page) {
  return page.evaluate(() => {
    const c = STATE.composition || {};
    const st = {};
    (c.phases || []).forEach((p) => { st[p.id] = p.status; });
    const t = (c.tasks || []).find((x) => segOf(x.status) !== 'archived'
      && segOf(st[x.phaseId]) !== 'archived');
    return t ? { id: t.id, phaseId: t.phaseId, was: t.model == null ? null : t.model } : null;
  });
}

async function assertConfirmFlowWorks(page) {
  assertNoHandAssignedPolledState();
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await tabTo(page, 'comp');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(300);

  const target = await firstEditableTask(page);
  if (!target) { fail('composition: the fixture has no EDITABLE task to edit'); return; }
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
  const saveBtn = page.locator('#comp').getByRole('button', { name: 'Save plan & models' });
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
    // aria-disabled, not `.disabled`: these buttons keep their tab stop (F16), so
    // the DOM property is permanently false and reading it would report every
    // Discard as live. The attribute is the state now.
    const d = document.querySelector('#comp [data-discard=comp]');
    return { rows: dirtyRows(), comp: editRows('comp').length,
             blocked: ev.defaultPrevented,
             discard: d ? d.getAttribute('aria-disabled') === 'true' : undefined };
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
             label: d ? d.textContent : null,
             disabled: d ? d.getAttribute('aria-disabled') === 'true' : null };
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
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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

  // The panel stamps which build is serving it. The plugin cache is keyed BY
  // VERSION, so `marketplace update` plus a reload can hand you a different build
  // than you meant with nothing on screen to say so — this is the line that says
  // so. Compared against plugin.json rather than a literal, because a literal
  // here would be a second place to bump on every release.
  {
    const want = JSON.parse(
      // NOT path.join: this function declares its own `path` const further down,
      // which shadows the module import and puts it in TDZ up here.
      readFileSync(REPO + '/plugins/audit/.claude-plugin/plugin.json', 'utf8')).version;
    // PAINTED, not merely present. This used to read the text of `#proj` and
    // pass on a substring, which is how the stamp spent releases being invisible
    // while this stayed green: it was appended to the END of the project-path
    // line, and that line is nowrap + ellipsis, so the version sat past the clip
    // edge — in the DOM, on no screen. A gate that cannot tell those two apart is
    // not guarding the thing its label names. So this asks the geometry instead:
    // a real box, inside the bar it belongs to.
    const shown = await page.evaluate(() => {
      const s = document.querySelector('.top .stampv');
      if (!s) return null;
      const r = s.getBoundingClientRect();
      const bar = document.querySelector('.top').getBoundingClientRect();
      const brand = document.querySelector('.top .brand');
      return {
        text: s.textContent,
        // the stamp yields to a cramped header by design, so report that state:
        // a failure here is either "wrong text" or "no room", and they differ.
        roomy: !!brand && brand.classList.contains('roomy'),
        painted: r.width > 0 && r.left >= bar.left - 1 && r.right <= bar.right + 1,
      };
    });
    if (!shown || shown.text !== 'v' + want || !shown.painted) {
      fail(`panel: the topbar does not name the build serving it — wanted `
         + `"v${want}" painted inside the bar, got ${JSON.stringify(shown)}`);
    } else {
      note(`panel: the topbar names the build serving it (v${want}), painted `
         + `inside the bar rather than merely present in the DOM`);
    }
  }

  // --- Settings writes through the same flow ---------------------------------
  await tabTo(page, 'guards');
  await page.waitForSelector('#guards .savebar', { timeout: 10000 });
  const box = page.locator('#guards input[type=checkbox]').first();
  if (!(await box.count())) { fail('settings: no boolean field to drive'); return; }
  const path = await box.getAttribute('id');
  await box.click();
  await page.waitForTimeout(200);
  // F-P-15: the savebar counts ("Discard 1 change") and the form must say WHICH
  // field that is. The count's basis existed - Discard lists the rows - but a
  // click away, while the Policy tab next door marks its pending cells inline.
  {
    const pend = await page.evaluate((id) => {
      const marked = [...document.querySelectorAll('#guards .f.pend')];
      const mine = document.getElementById(id);
      const wrap = mine && mine.closest ? mine.closest('.f') : null;
      return { n: marked.length,
        isTheEditedOne: marked.length === 1 && wrap !== null && marked[0] === wrap,
        badge: marked.length ? [...marked[0].querySelectorAll('[data-pendbadge]')]
          .map((b) => b.textContent.trim()).join(',') : '' };
    }, path);
    if (!pend.isTheEditedOne || pend.badge !== 'unsaved') {
      fail(`settings: one edit marked ${pend.n} field(s), edited-one=${pend.isTheEditedOne}, `
         + `badge="${pend.badge}" - the savebar's count has no basis on the form`);
    } else {
      note('settings: the edited field alone is marked unsaved, so the savebar\'s '
         + 'count says which field it means');
    }
  }
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await awaitConfirmDialog(page);
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
  // The clearing half, free from the save above: a marker that outlives the
  // change it describes is the same lie one step later.
  {
    const left = await page.evaluate(() =>
      document.querySelectorAll('#guards .f.pend, #guards [data-pendbadge]').length);
    if (left !== 0) {
      fail(`settings: ${left} unsaved marker(s) survived the save`);
    } else {
      note('settings: ...and the marks come off once it is saved');
    }
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

// --- skills tri-state and the combo box ----------------------------------------

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
  await tabTo(page, 'comp');
  await page.waitForSelector('#comp table', { timeout: 15000 });
  await page.waitForTimeout(300);
  // Drain any in-flight poll hand-off before editing (the model-combo rule).
  await page.evaluate(async () => { await pollRunStatus(); await refreshFromDisk(); });
  await page.waitForTimeout(200);
  // A phase holding TWO tasks with empty skills: one becomes the opt-out, the
  // other stays [] so the filter check has both sides in one viewport.
  // ...and an EDITABLE one. A finished phase, or a finished task inside a live
  // one, has its chips frozen, so a click on the opt-out chip waits for a button
  // that will never enable and reports a timeout instead of the tri-state claim.
  // `segOf` is the page's own classifier rather than a done/cancelled list kept
  // here, which is the same reason the UI itself calls it.
  const pick = await page.evaluate(() => {
    const c = STATE.composition || {};
    const st = {};
    (c.phases || []).forEach((x) => { st[x.id] = x.status; });
    const byP = {};
    (c.tasks || []).forEach((t) => {
      if (segOf(st[t.phaseId]) === 'archived' || segOf(t.status) === 'archived') return;
      (byP[t.phaseId] = byP[t.phaseId] || []).push(t);
    });
    for (const pid of Object.keys(byP)) {
      const empty = byP[pid].filter((t) => Array.isArray(t.skills) && !t.skills.length);
      if (empty.length >= 2) return { pid, optId: empty[0].id, refId: empty[1].id };
    }
    return null;
  });
  if (!pick) {
    fail('skills: the fixture has no OPEN phase with two empty-skills tasks to drive');
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
  const saveBtn = page.locator('#comp').getByRole('button', { name: 'Save plan & models' });
  await saveBtn.click();
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  // The probe name is INJECTED, and the fixture home declares every name the
  // manifest spells (assertManifestSkillsDiscovered), so this leg drives the one
  // unknown name on the panel: a hint that appears is the hint tracking the
  // probe, not a pre-existing gap between a demo pool and someone's installed
  // set. Before the fixture home, "0-no-such-skill-probe" was the only part of
  // this that was ever certain.
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
    // Was a `note`, and that was the reading that let this leg evaporate: the
    // hint is silent against an empty inventory BY DESIGN, so "skipped" was
    // indistinguishable from "green" and on a CI runner — no ~/.claude at all —
    // it was the only outcome this branch ever had. The panel is now handed a
    // home whose every skill is declared in this file, so an empty registry has
    // exactly one meaning left.
    fail('skills: the panel discovered no skills, but this capture hands it a '
       + 'fixture HOME declaring several — HOME did not take, so the '
       + 'inventory-hint leg had nothing to compare and every other check that '
       + 'reads the registry is equally blind');
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
 * (USAGE.facts), never from the menu's own rendering. That oracle is the
 * generated ledger and nothing else: `/api/usage` is byte-identical whether the
 * panel is handed a fixture HOME or the capturing machine's — measured, both
 * ways, on this fixture — so nothing in this function has ever depended on
 * discovery, and giving the panel a home did not re-aim it.
 *
 * Description search is the half that reads the registry, and it stays where it
 * is (assertComboDescriptionSearch, on the policy panel). Both panels now have a
 * declared inventory, so that is no longer forced; it is kept because the policy
 * fixture is the registry SHAPED for it — exactly one skill whose description
 * matches "behaviour" and whose name does not — and moving the check to a
 * registry that happens to satisfy that today would be the fixture choosing the
 * answer.
 */
async function assertComboSearchCount(page) {
  await tabTo(page, 'usage');
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
  // The task combo is one of the filter rows, so it is behind the fold.
  await openUsageFilters(page);
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
  await tabTo(page, 'comp');
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
  // NAMED, not positional. This used `placeholder^="search a skill"` with
  // `.first()`, which the task-row adder also matches - it worked only while the
  // config cards sat above the table, and reordering them pointed it at a control
  // inside a collapsed phase.
  const inp = page.locator('#comp input[data-skillpick="reviewSkill"]');
  await inp.click();
  await inp.fill(term);
  // POLL, do not sleep-and-peek. A fixed 300ms then one read made this flaky:
  // `renderComp()` runs on the composition poll, and a refresh landing inside
  // that window rebuilds the form, closes the menu, and leaves the read with an
  // empty list. Measured: red on some runs and green on the very next one with
  // nothing changed. The neighbour below already cured this disease by freezing
  // its endpoint; this one just never noticed it had it.
  // The discriminator is a MARKER ON THE ELEMENT, not the value in the box.
  // A first attempt compared the box's text to the term, and with a REAL defect
  // planted (the filter reading names only) the box held a different skill and
  // the probe blamed a re-render — mis-reporting a genuine regression as "this
  // run measured nothing", which is worse than the flake it was fixing. A
  // re-render builds a NEW input and the marker cannot survive it; a defect
  // leaves the element exactly where it was.
  await inp.evaluate((n) => n.setAttribute('data-descprobe', '1'));
  const read = () => page.evaluate(() => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    return {
      items: m ? [...m.querySelectorAll('.combo-n')].map((n) => n.textContent) : [],
      alive: !!document.querySelector('#comp input[data-descprobe="1"]'),
    };
  });
  let seen = await read();
  for (let i = 0; i < 20 && !(seen.items.length === 1 && seen.items[0] === want[0]); i++) {
    await page.waitForTimeout(150);
    seen = await read();
  }
  const got = seen.items;
  // A form that re-rendered under the probe loses the typed term. Say THAT,
  // rather than blaming the feature: reporting "the combo is not reading
  // descriptions" for a harness race is how a real defect gets disbelieved
  // later, and this check spent a while doing exactly that.
  if (!seen.alive) {
    fail(`policy: the composition form re-rendered under the description-search `
       + `probe — the input carrying the term was replaced, so this run measured `
       + `nothing about the combo. Re-run; if it persists, the poll is landing `
       + `inside the probe and the endpoint needs freezing the way the model-combo `
       + `step freezes its own`);
  } else if (got.length !== 1 || got[0] !== want[0]) {
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

// --- the model combo, notes, filters and live data -----------------------------

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
 *
 * The three sources are three readings of the fixture PROJECT — the manifest,
 * the rate tables (shipped defaults merged with the project's config) and the
 * generated ledger. None of them is discovery: `/api/state` and `/api/usage` are
 * both byte-identical whether this panel is handed a fixture HOME or the
 * capturing machine's, measured both ways, so the fixture home below neither
 * aimed this check nor blinded it. Recorded because the question looks open from
 * the outside — a combo, on the panel whose inventory was the leak — and it is
 * cheaper to have answered it once.
 */
async function assertModelCombo(page, project) {
  await tabTo(page, 'comp');
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
  // The phase of an EDITABLE task, not simply the first task's: opening a
  // finished phase leaves only frozen rows, and the `:not([data-frozen])` model
  // box below would then match nothing at all.
  const picked = await firstEditableTask(page);
  if (!picked) { fail('composition: the fixture has no editable task to type into'); return; }
  const pid = picked.phaseId;
  await page.evaluate((p) => openInComp(p), pid);
  await page.waitForTimeout(300);
  const box = page.locator('#comp tr.task:not([data-frozen]) .tmodel input').first();
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
  // Reached by its own data- hook, not by the wrapper class it used to sit in.
  // `.comp-review` was a styling wrapper and it is gone now that the control is
  // a table cell — a selector bound to a class is a selector bound to a layout
  // decision, which is the rule the panel's other hooks already follow.
  // `:not([data-frozen])` for the same reason the task selector two blocks up
  // carries it: a done or cancelled row's controls are disabled, so clicking one
  // opens no menu and the failure reads as "the combo is broken" rather than as
  // "this row was never editable". Whether the FIRST phase happens to be frozen is
  // a property of the fixture, which is why this passed on one machine and failed
  // on CI. Freezing was a class and this was the site nobody converted with it.
  const rev = await page.locator('#comp tr.phase:not([data-frozen]) input[data-revmodel]')
    .first().elementHandle();
  if (!rev) {
    fail('composition: no review-model input to drive the combo on');
  } else {
    await rev.click();
    await page.waitForTimeout(250);
    const items = page.locator('.combo-menu:not(.hidden) .combo-it');
    const nItems = await items.count();
    // The menu is FILTERED by whatever the input already holds, so its first
    // entry is routinely the current value verbatim - `opus` filtering to
    // ["opus", "claude-opus-4-5", ...]. Choosing that is a no-op, the panel
    // correctly writes no change row, and a test that picked `.first()` then
    // read the absence as "onChoose is broken". It is not: refusing to record
    // an edit that changes nothing is the behaviour we want. Pick the first
    // entry that would actually MOVE the value, so the assertion below is
    // about onChoose rather than about which model a generated fixture
    // happened to sort first.
    const current = ((await rev.evaluate((n) => n.value)) || '').trim();
    let pick = null, name = null;
    for (let i = 0; i < nItems; i++) {
      const it = items.nth(i);
      const t = ((await it.locator('.combo-n').textContent()) || '').trim();
      if (t && t !== current) { pick = it; name = t; break; }
    }
    if (!nItems) {
      fail('composition: focusing the review-model input opened no menu');
    } else if (!pick) {
      // Never skip: a menu whose every entry equals the current value cannot
      // test onChoose, and passing quietly would assert nothing at all.
      fail(`composition: all ${nItems} review-menu entr(ies) equal the current `
         + `value ${JSON.stringify(current)} - nothing to choose that would be `
         + `a change, so onChoose went untested`);
    } else {
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
  await tabTo(page, 'comp');
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
  await tabTo(page, 'guards');
  await page.waitForSelector('#guards .savebar', { timeout: 10000 });
  const rex = page.locator('#set-secretPatterns\\.extra input');
  if (!(await rex.count())) { fail('settings: no secretPatterns.extra editor'); return; }
  await rex.click();
  await rex.fill('(');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(400);

  // The landed save: card up, then gone on its own clock — including across
  // the disk-stamp refresh an own save triggers (the carry keeps the node).
  const box = page.locator('#guards input[type=checkbox]').first();
  await box.click();
  await page.waitForTimeout(200);
  await page.locator('#guards').getByRole('button', { name: 'Save settings' }).click();
  await awaitConfirmDialog(page);
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
  await awaitConfirmDialog(page);
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
  await tabTo(page, 'usage');
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
  await tabTo(page, 'comp');
  await page.waitForTimeout(250);
  const onComp = await page.evaluate(() => ({
    hash: location.hash, compShown: !document.getElementById('comp')
      .classList.contains('hidden') }));
  if (!onComp.compShown || !onComp.hash.startsWith('#/comp!')) {
    fail(`usage: switching tabs under a filter fragment gave hash `
       + `"${onComp.hash}" with comp shown=${onComp.compShown}`);
  }
  await tabTo(page, 'usage');
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
  // The phase of an EDITABLE task, not simply the first task's: opening a
  // finished phase leaves only frozen rows, and the `:not([data-frozen])` model
  // box below would then match nothing at all.
  const picked = await firstEditableTask(page);
  if (!picked) { fail('composition: the fixture has no editable task to type into'); return; }
  const pid = picked.phaseId;
  const who = await page.evaluate(() => {
    const t = {};
    for (const f of USAGE.facts) t[f[F.author]] = (t[f[F.author]] || 0) + f[F.tokens];
    return Object.keys(t).filter((a) => a && a !== 'unknown')
      .sort((a, b) => t[b] - t[a])[0] || null;
  });
  await tabTo(page, 'usage');
  await page.waitForTimeout(200);
  await page.evaluate((a) => setF('author', a), who);
  await page.evaluate((p) => openInComp(p), pid);
  await page.waitForTimeout(300);
  // ov (F-P-5): Overview opens on the ACTIVE view now, and the phase this step
  // writes to is a finished one — off screen there by design. The view is a
  // precondition of what this step measures (does a disk write reach the
  // screen), not part of it, so it is set explicitly rather than assumed.
  await page.evaluate(() => { OVF.view = 'all'; renderOver(); });
  await page.waitForTimeout(150);

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
  const box = page.locator('#comp tr.task:not([data-frozen]) .tmodel input').first();
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
    value: (document.querySelector('#comp tr.task:not([data-frozen]) .tmodel input') || {}).value,
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

/* ---- F-P-2 (uc): the empty usage bucket is named, and findable ---------------
 *
 * "--" is the ledger's storage key for spend with no phase or task behind it.
 * It reached the screen as those two characters in four places (the ranked
 * list said "-- unattributed", the browse table's id column, the chart legend
 * and the filter chips said "--"), which reads as a missing value rather than
 * as the answer it is. The word now comes from the shared LABELS map — one
 * spelling for the panel, the report and the CLI — and wears the warn role so
 * a reader can find how much of the bill has no plan behind it.
 *
 * Two oracles, because the failures look nothing alike: nothing rendered in the
 * Usage tab may READ as the storage key, and the label's computed colour must
 * be the warn token's (a class that exists but resolves to the body colour is
 * the silent half).
 */
async function assertUncategorizedNamed(page) {
  await tabTo(page, 'usage');
  await page.waitForTimeout(400);
  const seen = await page.evaluate(() => {
    const probe = document.createElement('span');
    probe.style.color = 'var(--warn)';
    document.body.appendChild(probe);
    const warn = getComputedStyle(probe).color;
    probe.remove();
    // Every leaf that carries text in the Usage tab, plus the SVG legend.
    const raw = [];
    document.querySelectorAll('#usage *').forEach((n) => {
      if (n.children.length) return;
      const t = (n.textContent || '').trim();
      if (t === '--' || t === '-- unattributed' || t === 'unattributed') {
        raw.push((n.className || '') + ':' + t);
      }
    });
    const marks = [...document.querySelectorAll('#usage .uncat')];
    return {
      raw, warn,
      count: marks.length,
      texts: [...new Set(marks.map((m) => m.textContent.trim()))],
      colours: [...new Set(marks.map((m) => getComputedStyle(m).color))],
    };
  });
  if (seen.raw.length) {
    fail(`usage: ${seen.raw.length} element(s) in the Usage tab still read as the `
       + `ledger's storage key rather than a word — ${JSON.stringify(seen.raw.slice(0, 4))}`);
  } else if (!seen.count) {
    fail('usage: nothing in the Usage tab is marked .uncat — the fixture ledger '
       + 'carries unattributed rows, so the empty bucket must be on screen and '
       + 'named; a check that finds neither the key nor the label is blind');
  } else if (seen.texts.length !== 1 || !seen.texts[0]) {
    fail(`usage: the empty bucket is spelled ${JSON.stringify(seen.texts)} — one `
       + `fact, one word`);
  } else if (seen.colours.some((c) => c !== seen.warn)) {
    fail(`usage: the "${seen.texts[0]}" label computes to ${JSON.stringify(seen.colours)} `
       + `but the warn role is ${seen.warn} — the class is on the element and the `
       + `colour is not reaching it`);
  } else {
    note(`usage: spend with no plan behind it reads "${seen.texts[0]}" in `
       + `${seen.count} place(s), painted in the warn role`);
  }
}

/* ---- F-P-1 (co): the combo menu is an overlay, and an open one is not a target -
 *
 * Four faces of one report ("the composition dropdown flickers, sometimes shows,
 * sometimes not, and moves the layout"), each reproduced in a real browser
 * before the fix and each asserted on its CAUSE rather than its symptom —
 * headless hover is lazy (it applies on the next pointer move, not the first),
 * so a check that only clicked would stay green under the bug:
 *
 *   a. `tr.phase:hover>td` carried a `filter`, which makes the td the containing
 *      block of every position:fixed descendant — the review-model menu, a DOM
 *      child of that td, jumped ~550px on hover and grew the table frame's
 *      scroll box (scrollbars = the "layout change"). The menu now lives on
 *      <body>, the way #hinttip already does: no ancestor can trap, clip or
 *      restack it. Asserted: hover the row → menu rect unchanged, frame's
 *      scroll box unchanged, and the menu's parent IS document.body.
 *   b. A moved disk stamp re-rendered a CLEAN Composition (renderComp resets
 *      the tab), and the ledger stamp moves after every Claude turn in the
 *      project — so an open menu or a focused field with nothing typed yet was
 *      wiped every ≤5s. The refresh now defers while a menu is open or a
 *      control is focused, exactly as it defers for an open dialog, and lands
 *      once the interaction ends. Asserted with a real ledger write.
 *   c. After a choice (or Escape) the input kept focus and a click on it did
 *      nothing — the menu only rendered on focus/input. A click reopens it.
 *   d. A mousedown on the menu's own padding/footer/scrollbar blurred the input
 *      and closed the menu 150ms later. The menu swallows mousedown.
 */

// --- combo overlay, the gate card and the ADO card -----------------------------

/** The gutter place() keeps between the menu and the viewport edge. */
const COMBO_GUT = 8;

/**
 * Why the menu's x is where it is — or null when no rule explains it.
 *
 * place() writes `Math.min(Math.max(gut, r.left), vw - gut - w)`: under its input
 * where a menu of that width fits, and pulled flush against the viewport gutter
 * where it does not. So "aligned with the input, always" is not the product's
 * rule, and asserting it fails a CORRECTLY clamped menu. It did: the phase
 * header's review-model input sits near the right-hand end of the table (an auto
 * margin then, the "model" column now)
 * and lands within ~15px of the clamp threshold, and 15px is exactly what
 * `html{scrollbar-gutter:stable}` reserves under classic scrollbar metrics and
 * does not reserve under overlay ones. Input at 1011 → no clamp, green by one
 * pixel; input at 1026 → clamp fires at 1200-8-180=1012, red. Same code, same
 * viewport; the difference was which scrollbar model the host chose. (The launch
 * flag in main() now pins that, so the two halves of this are independent fixes.)
 *
 * Asserting the RULE keeps the check honest without widening a tolerance until it
 * stops complaining: a menu at a stale x, at an unset left, or anchored to the
 * wrong element is neither under its input nor flush against a gutter it could
 * have been clamped to, and still fails.
 */
function comboMenuX(g, gut) {
  const right = g.menuLeft + g.menuWidth;
  if (Math.abs(g.menuLeft - g.inputLeft) <= 2) return 'under its input';
  // Flush alone is not enough: a menu that HAD room under its input and sits at
  // the gutter anyway is misplaced, so the clamp must also have been reachable.
  if (g.inputLeft + g.menuWidth > g.vw - gut && Math.abs(right - (g.vw - gut)) <= 2) {
    return `clamped flush to the right gutter (it needs ${g.menuWidth}px from `
         + `x=${g.inputLeft} in a ${g.vw}px viewport)`;
  }
  if (g.inputLeft < gut && Math.abs(g.menuLeft - gut) <= 2) return 'clamped flush to the left gutter';
  return null;
}

async function assertComboOverlay(page, project) {
  await page.evaluate(() => { COMPF.q = ''; COMPF.status = ''; COMPF.needs = false;
    if (COMPF.apply) COMPF.apply(); showTab('comp'); });
  await page.waitForTimeout(250);
  const REV = '#comp tr.phase input[data-revmodel]';
  const geo = () => page.evaluate((sel) => {
    const inp = document.querySelector(sel);
    const menu = [...document.querySelectorAll('.combo-menu')]
      .find((m) => !m.classList.contains('hidden')) || null;
    const wrap = document.querySelector('#comp .comptblwrap');
    const r = inp.getBoundingClientRect();
    const m = menu ? menu.getBoundingClientRect() : null;
    return {
      open: !!menu, onBody: !!menu && menu.parentElement === document.body,
      tdFilter: getComputedStyle(inp.closest('td')).filter,
      inputBottom: Math.round(r.bottom), inputLeft: Math.round(r.left),
      menuTop: m ? Math.round(m.top) : null, menuLeft: m ? Math.round(m.left) : null,
      frame: [wrap.scrollWidth, wrap.scrollHeight, wrap.clientWidth, wrap.clientHeight],
      // The three place() reads, so the clamp can be re-derived here rather than
      // assumed away — see comboMenuX.
      menuWidth: m ? Math.round(m.width) : null,
      vw: document.documentElement.clientWidth,
    };
  }, REV);
  // a. open with the pointer parked away, then hover the phase row itself.
  await page.mouse.move(2, 2);
  await page.focus(REV);
  await page.waitForTimeout(200);
  const g0 = await geo();
  if (!g0.open) {
    fail('combo: focusing the phase review-model input opened no menu');
    return;
  }
  const rowBox = await page.locator('#comp tr.phase').first().boundingBox();
  await page.mouse.move(rowBox.x + 160, rowBox.y + rowBox.height / 2);
  await page.mouse.move(rowBox.x + 162, rowBox.y + rowBox.height / 2);   // hover is lazy
  await page.waitForTimeout(200);
  const g1 = await geo();
  const moved = g1.menuTop !== g0.menuTop || g1.menuLeft !== g0.menuLeft;
  const grew = JSON.stringify(g1.frame) !== JSON.stringify(g0.frame);
  if (!g0.onBody) {
    fail(`combo(a): the open menu's parent is not <body> — it hangs inside the `
       + `phase row, one filtered/transformed ancestor away from being demoted `
       + `to absolute (menu at ${g0.menuTop},${g0.menuLeft} under input bottom `
       + `${g0.inputBottom})`);
  } else if (moved || grew) {
    fail(`combo(a): hovering the phase row (td filter=${JSON.stringify(g1.tdFilter)}) `
       + `moved the menu ${g0.menuTop},${g0.menuLeft} → ${g1.menuTop},${g1.menuLeft} `
       + `and/or grew the table frame ${JSON.stringify(g0.frame)} → `
       + `${JSON.stringify(g1.frame)} — the row is the menu's containing block`);
  } else if (Math.abs(g1.menuTop - g1.inputBottom) > 12) {
    fail(`combo(a): the menu's top is ${g1.menuTop} for an input whose bottom is `
       + `${g1.inputBottom} — not under its input`);
  } else if (!comboMenuX(g1, COMBO_GUT)) {
    fail(`combo(a): the menu spans x ${g1.menuLeft}..${g1.menuLeft + g1.menuWidth} for an `
       + `input at x ${g1.inputLeft} in a ${g1.vw}px viewport — neither under its input nor `
       + `flush against the ${COMBO_GUT}px gutter a clamp would have pulled it to`);
  } else {
    note(`combo(a): the phase review-model menu lives on <body>, stays at `
       + `${g1.menuTop},${g1.menuLeft} under hover (${comboMenuX(g1, COMBO_GUT)}), and the `
       + `table frame does not grow`);
  }
  // d. a mousedown on the menu's padding (not an item) must not close it.
  // The probe is taken at the TOP EDGE'S HORIZONTAL CENTRE, not at the corner.
  // It used to read `left + 2, top + 2`, which is outside the menu: the sheet
  // rounds this box by var(--radius), and a point 2px along each axis from a
  // 9px corner sits beyond the curve — ((9-2)^2)*2 > 9^2 — so hit-testing sent
  // the click straight through the cut-out to whatever was painted behind. That
  // made the case a question about the BACKDROP rather than about the menu, and
  // it answered "pass" only while the thing behind the corner was harmless;
  // shifting the menu a few px sideways put a phase-row <td> there, whose click
  // toggles the row, and the case failed for a reason it was never testing.
  // Centred, the point is clear of both corners at any radius, and it is still
  // the padding band and not an item: the border is 1px and the padding 4px, so
  // the first .combo-it begins 5px down.
  const pad = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.combo-menu')]
      .find((x) => !x.classList.contains('hidden'));
    const r = m.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + 2 };
  });
  await page.mouse.move(pad.x, pad.y);
  await page.mouse.down(); await page.mouse.up();
  await page.waitForTimeout(300);
  const dRes = await page.evaluate((sel) => ({
    open: !![...document.querySelectorAll('.combo-menu')].find((m) => !m.classList.contains('hidden')),
    focused: document.activeElement === document.querySelector(sel) }), REV);
  if (!dRes.open || !dRes.focused) {
    fail(`combo(d): a mousedown on the menu's own padding closed it (open=${dRes.open}, `
       + `input focused=${dRes.focused}) — a scrollbar drag or a stray click inside `
       + `the menu blurs the input and the menu goes with it`);
  } else {
    note('combo(d): a mousedown inside the menu (not on an item) keeps it open and the input focused');
  }
  // c. choose by keyboard, then click the still-focused input: it must reopen.
  //    Independent of (d): the input is blurred and re-focused first, so a menu
  //    (d) closed does not decide this leg.
  await page.mouse.move(2, 2);
  await page.evaluate((sel) => { const i = document.querySelector(sel); i.blur(); }, REV);
  await page.waitForTimeout(250);
  await page.focus(REV);
  await page.waitForTimeout(200);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(150);
  const chosen = await page.evaluate((sel) => ({
    value: document.querySelector(sel).value,
    open: !![...document.querySelectorAll('.combo-menu')].find((m) => !m.classList.contains('hidden')),
    focused: document.activeElement === document.querySelector(sel) }), REV);
  const revBox = await page.locator(REV).first().boundingBox();
  await page.mouse.click(revBox.x + revBox.width / 2, revBox.y + revBox.height / 2);
  await page.waitForTimeout(250);
  const cRes = await page.evaluate(() =>
    !![...document.querySelectorAll('.combo-menu')].find((m) => !m.classList.contains('hidden')));
  if (!chosen.value || chosen.open || !chosen.focused) {
    fail(`combo(c): the keyboard choice landed as ${JSON.stringify(chosen)} — `
       + `expected a value, a closed menu and a still-focused input`);
  } else if (!cRes) {
    fail('combo(c): after choosing, a click on the still-focused input did not '
       + 'reopen the menu — it only renders on focus/input, so the reader has to '
       + 'type or leave and come back');
  } else {
    note(`combo(c): after choosing "${chosen.value}", a click on the input reopens the menu`);
  }
  // b. a ledger write while the menu is open must NOT tear the tab down under
  //    the reader — and must land once the interaction ends.
  await page.keyboard.press('Escape');
  await page.evaluate(() => { renderComp(); });   // drop the choice above
  await page.waitForTimeout(200);
  await page.evaluate(async () => { await pollRunStatus(); });   // adopt the current stamp
  await page.waitForTimeout(200);
  const handle = await page.$(REV);
  await page.mouse.move(2, 2);
  await handle.focus();
  await page.waitForTimeout(150);
  const led = path.join(project, '.claude', 'usage');
  const files = readdirSync(led).filter((f) => f.endsWith('.jsonl')).sort();
  if (!files.length) {
    fail(`combo(b): no ledger file under ${led} to move the stamp with`);
  } else {
    appendFileSync(path.join(led, files[files.length - 1]), '\n');   // blank line: skipped by the reader
    await page.waitForTimeout(6500);   // > one 5s poll
    const held = await page.evaluate((sel) => ({
      open: !![...document.querySelectorAll('.combo-menu')].find((m) => !m.classList.contains('hidden')),
      focused: document.activeElement === document.querySelector(sel) }), REV);
    held.sameNode = await handle.evaluate((n) => document.contains(n));
    if (!held.sameNode || !held.open || !held.focused) {
      fail(`combo(b): a ledger write with the menu open re-rendered Composition `
       + `(same input node=${held.sameNode}, menu open=${held.open}, focused=${held.focused}) `
       + `— the disk refresh does not defer for an open combo, so every Claude turn `
       + `in the project tears the tab down under the reader`);
    } else {
      // ...and the deferred refresh must land once the reader lets go.
      await page.evaluate(() => document.activeElement && document.activeElement.blur());
      await page.waitForTimeout(6500);
      const landed = !(await handle.evaluate((n) => document.contains(n)));
      if (!landed) {
        fail('combo(b): the deferred refresh never landed after the input was blurred '
           + '— the stamp move was swallowed, not deferred');
      } else {
        note('combo(b): a ledger write is deferred while the combo is open, and lands '
           + 'once the reader lets go');
      }
    }
  }
  await page.evaluate(() => { renderComp(); });
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
  await tabTo(page, 'over');
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
  await tabTo(page, 'comp');
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
    return d ? { text: d.textContent,
                 disabled: d.getAttribute('aria-disabled') === 'true' } : null;
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
    discardDead: document.querySelector('[data-discard=ado]')
      ?.getAttribute('aria-disabled') === 'true',
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

// --- the help drawer -----------------------------------------------------------

/**
 * Write the `.claude` tree discovery walks under `base` — a fixture HOME, or a
 * fixture PROJECT (`_scan_skills` reads `<base>/.claude/skills` for both, badging
 * them `user` and `project` by which one it was handed).
 *
 * `plugin` entries land under `<base>/.claude/plugins/audit/`, which discovery
 * badges `plugin`; that path is only ever walked for a HOME.
 */
function writeDiscoveryTree(base, { skills = [], agents = [], plugin = [] }) {
  for (const [name, description] of skills) {
    const dir = path.join(base, '.claude', 'skills', name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, 'SKILL.md'),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  if (agents.length) mkdirSync(path.join(base, '.claude', 'agents'), { recursive: true });
  for (const [name, description] of agents) {
    writeFileSync(path.join(base, '.claude', 'agents', `${name}.md`),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  for (const [kind, file, name, description] of plugin) {
    const dir = kind === 'skills'
      ? path.join(base, '.claude', 'plugins', 'audit', 'skills', file)
      : path.join(base, '.claude', 'plugins', 'audit', 'agents');
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, kind === 'skills' ? 'SKILL.md' : `${file}.md`),
                  `---\nname: ${name}\ndescription: ${description}\n---\n`);
  }
  return base;
}

/** `<project>/.mcp.json` naming exactly `names` — the MCP half of a fixture. */
function writeFixtureMcp(project, names) {
  writeFileSync(path.join(project, '.mcp.json'), JSON.stringify(
    { mcpServers: Object.fromEntries(names.map((n) => [n, { command: 'x' }])) }, null, 2));
  return names;
}

/**
 * Did discovery reach exactly the fixture, and nothing of this machine's?
 *
 * The oracle is `/api/registry` — the endpoint the page itself renders from — against
 * a want computed from the declarations below, so a fixture edit re-aims this check
 * instead of blinding it. Asserted BEFORE anything is captured on that panel: the
 * failure is silent, and it lands in a committed PNG that lists whatever the person
 * capturing installed.
 */
async function assertFixtureDiscovery(page, want, label) {
  const found = await page.evaluate(async () => {
    const r = await api('GET', '/api/registry');
    return { skills: r.skills.map((s) => s.name).sort(),
             agents: r.agents.map((a) => a.name).sort(),
             mcp: (r.mcp || []).slice().sort() };
  });
  const wanted = { skills: want.skills.slice().sort(),
                   agents: want.agents.slice().sort(),
                   mcp: want.mcp.slice().sort() };
  if (JSON.stringify(found) !== JSON.stringify(wanted)) {
    fail(`${label}: discovery reached beyond the fixture — HOME did not take, and `
       + `these shots would publish it: ${JSON.stringify(found)}`);
    return false;
  }
  note(`${label}: discovery is the fixture's own (${found.skills.length} skills, `
     + `${found.agents.length} agents, ${found.mcp.length} MCP)`);
  return true;
}

/* ---- the 50 x 20 panel's inventory ------------------------------------------
 *
 * Shaped by what the panel does with it, not by what makes a table look full.
 *
 *   * The five USER skills are the five `gen-demo-manifest.SKILL_POOL` spells into
 *     every area default and every task that carries skills. They are here because
 *     `skillHints()` draws "discovery knows no such skill" beside a manifest name
 *     the scan does not know: declare all five and the composition shots are clean,
 *     declare four and one note is documentation of a defect the fixture invented.
 *     The set is not trusted to stay in step — `assertManifestSkillsDiscovered`
 *     recomputes `skillHints`' own difference from the running panel and goes red if
 *     the pool moves.
 *   * That same completeness is what makes `assertSkillTriState`'s last leg mean
 *     anything: its probe name is then the ONLY name discovery does not know, so a
 *     hint appearing is the hint tracking the probe rather than a pre-existing gap.
 *   * PROJECT and PLUGIN entries exist so the `source` column of the building-blocks
 *     table carries more than one badge — the card's own subtitle promises three
 *     origins, and a shot showing one word repeated documents the opposite.
 *   * The MCP pair is what makes the third sub-tab's `mcp (2)` a number rather than
 *     `mcp (0)`, and it comes from the project's own `.mcp.json` — the home's
 *     `.claude.json` is deliberately left absent, so nothing outside this file can
 *     add a name.
 */
const BIG_USER_SKILLS = [
  ['clean-typescript', 'Writes TypeScript the way this codebase already reads.'],
  ['pragmatic-testing', 'Chooses what to test, and at which level, before writing it.'],
  ['web-security', 'Checks a change for the web vulnerabilities it could introduce.'],
  ['safe-incremental-refactor', 'Restructures code in reviewable, behaviour-preserving steps.'],
  ['structured-code-review', 'Reads a diff for correctness, reuse and coverage in turn.'],
];
const BIG_PROJECT_SKILLS = [
  ['storefront-conventions', 'This repo\'s own component, routing and data-loading conventions.'],
  ['mobile-release-checklist', 'The steps this repo runs before a mobile release goes out.'],
];
const BIG_AGENTS = [
  ['api-contract-checker', 'Compares a handler against the published API contract.'],
  ['bundle-size-watcher', 'Reports what a change adds to the shipped bundle.'],
];
// One of audit's own, under the name the Skill tool spells it with — the `plugin`
// badge, and the row the policy tab marks required.
const BIG_PLUGIN = [
  ['skills', 'report', 'audit:report', 'Renders the audit report.'],
  ['agents', 'audit-explorer', 'audit:audit-explorer', 'Read-only subsystem auditor.'],
];
const BIG_MCP = ['design-tokens', 'storefront-db'];

/** Build the 50 x 20 panel's fixture home, and say what it declares. */
function writeBigFixture(work, project) {
  const home = path.join(work, 'bighome');
  writeDiscoveryTree(home, { skills: BIG_USER_SKILLS, agents: BIG_AGENTS,
                             plugin: BIG_PLUGIN });
  writeDiscoveryTree(project, { skills: BIG_PROJECT_SKILLS });
  writeFixtureMcp(project, BIG_MCP);
  return {
    home,
    want: {
      skills: [...BIG_USER_SKILLS.map(([n]) => n),
               ...BIG_PROJECT_SKILLS.map(([n]) => n),
               ...BIG_PLUGIN.filter((p) => p[0] === 'skills').map((p) => p[2])],
      agents: [...BIG_AGENTS.map(([n]) => n),
               ...BIG_PLUGIN.filter((p) => p[0] === 'agents').map((p) => p[2])],
      mcp: BIG_MCP.slice(),
    },
  };
}

/**
 * Every skill name the fixture MANIFEST spells is a name the fixture HOME declares.
 *
 * Not a restatement of the declaration above: the difference is recomputed in-page
 * from the two inputs `skillHints()` itself reads (`STATE.composition.tasks[].skills`
 * plus `areaSkills`, against `REG.skills`), so this is the product's own arithmetic
 * asked one question — is the answer empty? It is red when the demo generator's
 * skill pool moves and the declaration above does not follow, which is the moment
 * the composition screenshots would start carrying "discovery knows no such skill"
 * notes about a gap the fixture invented.
 */
async function assertManifestSkillsDiscovered(page) {
  const gap = await page.evaluate(() => {
    const comp = (STATE || {}).composition || {};
    const spelled = new Set();
    (comp.tasks || []).forEach((t) => {
      (Array.isArray(t.skills) ? t.skills : []).forEach((s) => spelled.add(s));
    });
    (comp.areaSkills || []).forEach((s) => spelled.add(s));
    return { unknown: [...spelled].sort()
               .filter((n) => !REG.skills.some((s) => s.name === n)),
             spelled: spelled.size };
  });
  if (!gap.spelled) {
    fail('panel: the fixture manifest spells no skill at all, so neither the '
       + 'inventory hint nor this check has anything to be about');
  } else if (gap.unknown.length) {
    fail(`panel: the fixture manifest spells ${JSON.stringify(gap.unknown)}, which `
       + `the fixture home does not declare — every composition shot would carry a `
       + `"discovery knows no such skill" note about a gap the fixture invented. `
       + `Add them to BIG_USER_SKILLS.`);
  } else {
    note(`panel: all ${gap.spelled} skill name(s) the fixture manifest spells are `
       + `declared by the fixture home`);
  }
}

/* ---- the policy switchboard ------------------------------------------------
 *
 * Its own PROJECT as well as its own home, which the 50 x 20 fixture does not need:
 * the tab renders one row per discovered capability with the server's verdict on it,
 * so the inventory has to be shaped for the verdicts — a glob to match, a name to
 * deny, and one of audit's own to be refused a denial. See the section above for why
 * the home itself is not optional here or anywhere.
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
  py([resolveScript('gen-demo-manifest.py'), project, '--phases', '6', '--tasks', '3']);
  writeDiscoveryTree(home, { skills: POL_SKILLS, agents: POL_AGENTS,
                             plugin: POL_PLUGIN });
  writeFixtureMcp(project, POL_MCP);
  return {
    project,
    home,
    want: {
      skills: [...POL_SKILLS.map(([n]) => n),
               ...POL_PLUGIN.filter((p) => p[0] === 'skills').map((p) => p[2])],
      agents: [...POL_AGENTS.map(([n]) => n),
               ...POL_PLUGIN.filter((p) => p[0] === 'agents').map((p) => p[2])],
      mcp: POL_MCP.slice(),
    },
  };
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
// --- proposals and the capability policy ---------------------------------------

/**
 * The Proposals tab, driven for real: drop → revive → materialize.
 *
 * F-P-32. The panel could not see `proposals[]` at all, so an /audit:init that
 * parked every phase left the tab that shows the plan showing nothing. Pins over
 * UI_HTML can prove the constructs exist; only this can prove the round trip
 * writes the manifest and comes back.
 *
 * The half that matters most is REVIVE: dropping is supposed to be an archive
 * rather than a deletion, and the only way to tell those apart is to put one back
 * and find the reason still attached.
 *
 * @param {import('playwright').Page} page
 * @returns {Promise<void>}
 */
async function assertProposalsWork(page) {
  await tabTo(page, 'props');
  await page.waitForSelector('#props .card', { timeout: 15000 });
  const read = () => page.evaluate(() =>
    [...document.querySelectorAll('#props details.prop')].map((d) => ({
      id: d.getAttribute('data-prop'),
      status: d.getAttribute('data-status'),
      chip: (d.querySelector('.st') || {}).textContent || '',
      text: (d.textContent || '').replace(/\s+/g, ' ').trim(),
    })));
  const before = await read();
  if (!before.length) { fail('proposals: the fixture parks none to drive'); return; }
  const states = [...new Set(before.map((p) => p.status))].sort();
  if (states.length < 3) {
    fail(`proposals: the fixture shows ${JSON.stringify(states)} — all three `
       + 'states are needed, or two thirds of the tab is unchecked');
  } else {
    note(`proposals: ${before.length} shown, all three states (${states.join(', ')})`);
  }
  // A dropped one must carry its reason, or archiving is indistinguishable from
  // deleting with extra steps.
  const dropped = before.find((p) => p.status === 'dropped');
  if (dropped && !/why declined/i.test(dropped.text)) {
    fail(`proposals: ${dropped.id} is dropped and does not say why`);
  } else if (dropped) {
    note('proposals: a dropped proposal shows why it was declined');
  }

  const target = before.find((p) => p.status === 'proposed');
  if (!target) { fail('proposals: nothing parked to drop'); return; }
  // Its body is a disclosure, so everything below it is invisible until opened —
  // which is the design (a long list stays readable) and a precondition here.
  const open = async () => { await page.evaluate((pid) => {
    const d = document.querySelector('#props details.prop[data-prop="' + pid + '"]');
    if (d) d.open = true;
  }, target.id); await page.waitForTimeout(150); };
  await open();

  // --- drop, with the reason typed where the button will read it -------------
  const dropBtn = page.locator(`#props [data-propdrop="${target.id}"]`);
  const dead = await dropBtn.getAttribute('aria-disabled');
  if (dead !== 'true' && !(await dropBtn.isDisabled().catch(() => false))) {
    fail('proposals: Drop is live with no reason typed — the affordance should '
       + 'wait for one');
  }
  await page.fill(`#props [data-propreason="${target.id}"]`, 'declined by the gate');
  await dropBtn.click();
  await awaitConfirmDialog(page);
  const shown = await page.evaluate(() =>
    [...document.querySelectorAll('dialog.confirm tbody tr')]
      .map((r) => [...r.children].map((c) => c.textContent.trim()).join(' · ')));
  if (!shown.some((r) => /declined by the gate/.test(r))) {
    fail(`proposals: the drop dialog does not show the reason about to be written: `
       + JSON.stringify(shown));
  } else {
    note('proposals: the drop dialog shows the reason before it is written');
  }
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const afterDrop = (await read()).find((p) => p.id === target.id) || {};
  if (afterDrop.status !== 'dropped' || !/declined by the gate/.test(afterDrop.text)) {
    fail(`proposals: after dropping, ${target.id} reads `
       + `${JSON.stringify(afterDrop.status)} and does not carry the reason`);
  } else {
    note(`proposals: ${target.id} dropped, and the reason is on the card`);
  }

  // --- revive: the half that makes it an archive -----------------------------
  await open();
  await page.locator(`#props [data-proprevive="${target.id}"]`).click();
  await awaitConfirmDialog(page);
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(900);
  const revived = (await read()).find((p) => p.id === target.id) || {};
  if (revived.status !== 'proposed') {
    fail(`proposals: revive left ${target.id} at ${JSON.stringify(revived.status)}`);
  } else {
    note(`proposals: ${target.id} revived — dropping archives rather than deletes`);
  }

  // --- materialize: the write that reaches the plan --------------------------
  await open();
  await page.locator(`#props [data-propmat="${target.id}"]`).click();
  await awaitConfirmDialog(page);
  await page.locator('dialog.confirm [data-cfgo]').click();
  await page.waitForTimeout(1200);
  const done = (await read()).find((p) => p.id === target.id) || {};
  const inPlan = await page.evaluate((pid) => {
    // Bare `STATE`, not `window.STATE`: a top-level `let` in the page's script
    // lives in the global LEXICAL environment and never becomes a window
    // property, so the window spelling reads undefined and this check would pass
    // itself as a failure about the product.
    const st = (typeof STATE === 'object' && STATE) || {};
    const prop = ((st.proposals) || []).find((x) => x.id === pid) || {};
    const phases = ((st.composition || {}).phases) || [];
    return { became: prop.materializedAs || null,
             live: phases.some((ph) => ph.id === prop.materializedAs) };
  }, target.id);
  if (done.status !== 'materialized' || !inPlan.became || !inPlan.live) {
    fail(`proposals: materialize left ${target.id} at `
       + `${JSON.stringify(done.status)}; became=${JSON.stringify(inPlan.became)} `
       + `live=${inPlan.live} — the phase must be in the plan, not just flagged`);
  } else {
    note(`proposals: ${target.id} materialized as ${inPlan.became}, and that phase `
       + 'is in the plan');
  }
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
  await tabTo(page, 'policy');
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
// --- appearance, tables and the save bar ---------------------------------------
/**
 * SC 1.3.1, read off the RENDERED page: every table has header cells, and the
 * stateMap grid names both of its axes.
 *
 * This exists because the selftest that used to carry the claim could only see
 * source text. It asserted `el('th'` inside each table builder and counted
 * `scope:'col'` at three - both fair proxies while three builders each nested
 * their own headers, and neither survivable once the fifteen hand-nested headers
 * across the panel became one `tableHead`. The count went to one because there is
 * one spelling now, mapped over three column names, which is a better state of
 * affairs that the proxy reads as a regression.
 *
 * So the proxy stays where it belongs - "the builders reach the helper" is a
 * source fact - and the claim it was standing in for is answered here, from the
 * cells that actually exist.
 */
async function assertTableHeaders(page) {
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => document.querySelector('#guards')?.children.length > 0,
    { timeout: 10000 }).catch(() => {});
  const tabs = await page.$$eval('.tab', (bs) => bs.map((b) => b.getAttribute('data-t')));
  for (const t of tabs) { await tabTo(page, t); await page.waitForTimeout(200); }

  const found = await page.evaluate(() => Array.from(document.querySelectorAll('table'))
    .map((tb) => ({
      cls: tb.className || '(none)',
      view: (() => {
        for (let n = tb; n; n = n.parentElement) {
          if (['guards', 'comp', 'over', 'usage', 'policy', 'props', 'look'].includes(n.id)) return n.id;
        }
        return '(none)';
      })(),
      ths: tb.querySelectorAll('th').length,
      // A data row is one with a td in it, so a table that is nothing BUT
      // headers is not reported as missing them.
      dataRows: Array.from(tb.rows).filter((r) => r.querySelector('td')).length,
      colScoped: tb.querySelectorAll('th[scope="col"]').length,
      rowScoped: tb.querySelectorAll('th[scope="row"]').length,
    })));

  // The vacuity guard first: everything below narrows this set.
  if (found.length < 6) {
    fail(`tables: only ${found.length} table(s) found across ${tabs.length} tab(s) `
       + '\u2014 too few to be checking anything, so either the fixture stopped '
       + 'reaching the views that build them or they stopped being tables');
    return;
  }
  // EVERY table, not only the ones with rows in this fixture. Gating on
  // `dataRows > 0` was the first version and it passed a deliberate mutation:
  // the policy rules table has no rules on this fixture, so removing its headers
  // was invisible. A table declares its columns whether or not this project
  // happens to fill it, and "the fixture did not exercise it" is the one excuse a
  // gate must never make silently.
  const bare = found.filter((t) => t.ths === 0);
  const empty = found.filter((t) => t.dataRows === 0);
  if (bare.length) {
    fail('tables: ' + bare.length + ' table(s) with NO header cell at all '
       + '\u2014 SC 1.3.1 needs the axes named: '
       + bare.map((t) => `#${t.view} .${t.cls}`).join(', '));
  } else {
    // NAMED, not counted. This can only see the tables this fixture RENDERS -
    // the policy rules table needs rules to exist before it is built at all, and
    // a mutation removing its headers passed here for exactly that reason. A
    // reader who can see the covered set can see what is missing from it; a bare
    // count hides the gap it has.
    note(`tables: ${found.length} table(s) across ${tabs.length} tab(s), every one `
       + `carries header cells (${empty.length} empty of data, checked anyway) - `
       + found.map((t) => `#${t.view} .${t.cls}`).sort().join(', '));
  }

  // The stateMap grids specifically, because their ROW axis is what carries the
  // meaning: the column says what kind of value, the row says which transition.
  const grids = found.filter((t) => /adosm/.test(t.cls));
  if (grids.length !== 3) {
    fail(`tables: expected three stateMap grids (phase, task, bug), found `
       + `${grids.length} \u2014 the axis check below would pass over the wrong set`);
  } else {
    const wrong = grids.filter((g) => g.colScoped !== 3 || g.rowScoped < 1);
    if (wrong.length) {
      fail('tables: a stateMap grid does not name both axes \u2014 '
         + wrong.map((g) => `col=${g.colScoped} row=${g.rowScoped}`).join(', ')
         + ' (three scope=col and at least one scope=row are the claim)');
    } else {
      note('tables: all three stateMap grids name both axes '
         + `(3 scope=col, ${grids[0].rowScoped} scope=row each)`);
    }
  }
}

async function assertSavebarCensus(page) {
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => document.querySelector('#guards')?.children.length > 0,
    { timeout: 10000 }).catch(() => {});
  // Visit every tab: a view that has never rendered has no footer to inspect, and
  // its absence reads exactly like a view that legitimately has none.
  const tabs = await page.$$eval('.tab', (bs) => bs.map((b) => b.getAttribute('data-t')));
  for (const t of tabs) { await tabTo(page, t); await page.waitForTimeout(200); }

  const found = await page.evaluate(() => {
    const dataHooks = (el) => Array.from(el.attributes).map((a) => a.name)
      .filter((n) => n.startsWith('data-'));
    const viewOf = (el) => {
      for (let n = el; n; n = n.parentElement) {
        if (n.id && ['guards', 'comp', 'over', 'usage', 'policy', 'props', 'look'].includes(n.id)) return n.id;
      }
      return '(none)';
    };
    return Array.from(document.querySelectorAll('button'))
      .filter((b) => /^(save|discard)\b/i.test((b.textContent || '').trim()))
      .map((b) => ({
        kind: /^save/i.test((b.textContent || '').trim()) ? 'save' : 'discard',
        text: (b.textContent || '').trim().slice(0, 26),
        view: viewOf(b),
        hooks: dataHooks(b),
        aria: b.getAttribute('aria-disabled'),
        // Nameability is computed by the PAGE'S OWN focusSel, not by a rule
        // re-derived here. focusSel prefers an id and otherwise builds a selector
        // out of whatever `data-` attributes it finds, so "carries a hook" is not
        // the property - "focusSel can produce a selector that resolves to
        // exactly this element" is. A census that reimplemented the rule would
        // drift from it, and a first attempt here asserted only that SOME data-
        // attribute existed, which a meaningless one satisfies.
        sel: (() => { try { return focusSel(b); } catch (e) { return '(threw)'; } })(),
        selMatches: (() => {
          try {
            const s = focusSel(b);
            return s ? document.querySelectorAll(s).length : 0;
          } catch (e) { return -1; }
        })(),
        // The footer is whatever element holds both, so it is found rather than
        // named: two container conventions ship today and a third would not break
        // this.
        footerHasDiscard: !!(b.parentElement
          && Array.from(b.parentElement.querySelectorAll('button'))
              .some((x) => /^discard\b/i.test((x.textContent || '').trim()))),
      }));
  });

  const saves = found.filter((f) => f.kind === 'save');
  const discards = found.filter((f) => f.kind === 'discard');
  // The vacuity guard first: everything below narrows this set, and a set that
  // narrowed to nothing would report a page with no unhooked control on it.
  if (saves.length < 4 || discards.length < 3) {
    fail(`panel footers: the census found ${saves.length} Save and `
       + `${discards.length} Discard control(s) across ${tabs.length} tab(s), which `
       + 'is too few to be checking anything — either the fixture stopped reaching '
       + 'the writable views or the labels changed');
    return;
  }

  for (const s of saves) {
    if (!s.sel || s.selMatches !== 1) {
      fail(`panel footers: #${s.view} "${s.text}" is not uniquely nameable — `
         + `focusSel gives ${JSON.stringify(s.sel)} matching ${s.selMatches} `
         + 'element(s), so a caret handed back after the view is rebuilt lands '
         + 'nowhere or on the wrong control');
    }
    // Two exemptions, and they are named by HOOK rather than by view on purpose.
    // Exempting `#look` wholesale - which is what this did first - would exempt
    // any future writable footer added to that tab, forever and silently.
    //
    //   data-thsave   the theme card's Save. The one writable footer with no
    //                 Discard, by design: it offers an undo/redo trail instead,
    //                 which is why the retired count read 4 discards to 5 saves.
    //   data-thsaveas "Save as…", which writes a theme FILE rather than the
    //                 config. It is not a footer save and is owed no Discard;
    //                 it is in this census at all only because the label reads
    //                 "Save as", and being hooked is still required of it.
    const exempt = s.hooks.some((h) => h === 'data-thsave' || h === 'data-thsaveas');
    if (!s.footerHasDiscard && !exempt) {
      fail(`panel footers: #${s.view} "${s.text}" has no Discard beside it — every `
         + 'writable view owes the reader a way back, and only the theme card is '
         + 'exempt because it carries an undo trail instead');
    }
  }
  for (const d of discards) {
    if (!d.sel || d.selMatches !== 1) {
      fail(`panel footers: #${d.view} Discard is not uniquely nameable — focusSel `
         + `gives ${JSON.stringify(d.sel)} matching ${d.selMatches} element(s)`);
    }
    // Dead while there is nothing to throw away. `null` is the state that let a
    // Discard look live over a clean form: nobody ever set the attribute.
    if (d.aria !== 'true') {
      fail(`panel footers: #${d.view} Discard reads aria-disabled=${d.aria} on a `
         + 'freshly loaded page — it should be dead until something is dirty');
    }
  }
  // EVERY VIEW OFFERING A SAVE MUST BE ONE beforeunload CAN PROTECT, asked of the
  // live page rather than of a list in a test. The registry is built at render
  // time, so this is the only place the question has a real answer: a new
  // writable view that never registers is invisible to a substring pin, and its
  // reader loses everything typed the moment they close the tab. The theme card
  // was exactly that for as long as it existed.
  //
  // A view is covered either by its own key or by a documented FOLD onto another
  // view - the ADO card has a key of its own but lives inside #comp - so the
  // dirtiness map is consulted too rather than requiring the ids to match.
  const registry = await page.evaluate(() => ({
    keys: Object.keys(EDITS), views: Object.keys(dirtyViews()),
  }));
  if (!registry.keys.length) {
    fail('panel footers: Object.keys(EDITS) is empty on a rendered page — the '
       + 'coverage check below would pass over nothing at all');
  } else {
    const covered = new Set([...registry.keys, ...registry.views]);
    for (const view of new Set(saves.map((f) => f.view))) {
      if (view === '(none)') continue;      // a Save outside every view container
      if (!covered.has(view)) {
        fail(`panel footers: #${view} offers a Save but nothing registers its `
           + 'unsaved work — beforeunload will let a closing tab discard it '
           + `silently. Registered: ${[...covered].sort().join(', ')}`);
      }
    }
    note(`panel footers: every view with a Save is covered — keys `
       + `[${registry.keys.sort().join(', ')}], views `
       + `[${registry.views.sort().join(', ')}]`);
  }
  const shape = saves.map((s) => `${s.view}:${s.sel}`).join(', ');
  note(`panel footers: ${saves.length} Save / ${discards.length} Discard across `
     + `${tabs.length} tab(s); every Save hooked, every Discard hooked and dead while `
     + `clean — ${shape}`);
  // Stated rather than implied: the Save hooks are NOT uniform (data-save,
  // data-psave, data-thsave) and the containers are not either (.savebar vs a
  // bare .row). This census accepts any of them on purpose, so it keeps holding
  // when the footers become one helper emitting one convention.
}

async function assertPolicyExpand(page) {
  await tabTo(page, 'policy');
  await page.waitForTimeout(300);
  const btn = page.locator('#policy [data-polexpand]');
  if (!(await btn.count())) {
    fail('policy: no expand control on the capability table — the reader is left '
       + 'scrolling a 34rem frame to compare verdicts across areas');
    return;
  }
  const inTab = await page.evaluate(() =>
    [...document.querySelectorAll('#policy [data-pcap]')].map((r) => r.getAttribute('data-pcap')));
  await btn.click();
  await page.waitForTimeout(350);
  const open = await page.evaluate(() => {
    const d = document.querySelector('dialog.polfull[open]');
    if (!d) return null;
    const r = d.getBoundingClientRect();
    return {
      rows: [...d.querySelectorAll('[data-pcap]')].map((x) => x.getAttribute('data-pcap')),
      onBody: d.parentElement === document.body,
      // The point of the control: the table gets the screen, not another frame.
      wide: r.width >= innerWidth * 0.9 && r.height >= innerHeight * 0.85,
      hasSearch: !!d.querySelector('input[type=search]'),
    };
  });
  if (!open) {
    fail('policy: the expand control opened no dialog.polfull');
    return;
  }
  if (JSON.stringify(open.rows) !== JSON.stringify(inTab)) {
    fail(`policy: the expanded table lists ${open.rows.length} capabilities and the `
       + `tab lists ${inTab.length} — two builders drifting, which is the failure `
       + `this was refactored to make impossible`);
  } else if (!open.onBody || !open.wide || !open.hasSearch) {
    fail(`policy: the dialog is ${JSON.stringify(open)} — expected a body-mounted, `
       + `full-viewport panel with its own search`);
  } else {
    note(`policy: expand opens the same ${open.rows.length} capabilities full-screen`);
  }
  // The shot is taken here rather than in the capture block: the dialog is open
  // for exactly this step, and photographing it means opening it a second time.
  await shot(page, 'panel-policy-expanded', { dialog: true });
  // Typing in the dialog filters BOTH, because the filter is the tab's own state.
  const first = inTab[0] || '';
  await page.fill('dialog.polfull input[type=search]', first);
  await page.waitForTimeout(350);
  const filtered = await page.evaluate(() => ({
    dlg: [...document.querySelectorAll('dialog.polfull [data-pcap]')].length,
    tab: [...document.querySelectorAll('#policy [data-pcap]')].length,
    focused: document.activeElement && document.activeElement.closest
      && !!document.activeElement.closest('dialog.polfull'),
  }));
  if (filtered.dlg !== filtered.tab || filtered.dlg >= inTab.length) {
    fail(`policy: filtering inside the dialog left ${filtered.dlg} rows there and `
       + `${filtered.tab} in the tab (of ${inTab.length}) — the two must be one view`);
  } else if (!filtered.focused) {
    fail('policy: the caret left the dialog search box as it filtered — the '
       + 'rebuild is not putting focus back, so the reader types one letter per click');
  } else {
    note(`policy: a search inside the dialog narrows both views to ${filtered.dlg} `
       + `and keeps the caret`);
  }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const closed = await page.evaluate(() => ({
    open: !!document.querySelector('dialog.polfull[open]'),
    focus: document.activeElement && document.activeElement.getAttribute
      ? document.activeElement.getAttribute('data-polexpand') : null,
    q: PF.q,
  }));
  if (closed.open) {
    fail('policy: Esc did not close the expanded table');
  } else if (closed.focus !== '1') {
    fail(`policy: after Esc the focus is on ${JSON.stringify(closed.focus)} rather `
       + `than the expand control that opened the dialog`);
  } else {
    note('policy: Esc closes it and hands the focus back to the expand control');
  }
  await page.evaluate(() => { PF.q = ''; PF.bad = false; renderPolicy(); });
  await page.waitForTimeout(200);
}
// --- the shutter, and claiming the fixed scratch path --------------------------


async function noDialog(page, name) {
  const open = await page.evaluate(() =>
    [...document.querySelectorAll('dialog[open]')]
      .map((d) => d.className || '(unclassed)'));
  if (!open.length) return;
  fail(`${name}: a <dialog> is still open (${open.join(', ')}) — this capture `
     + `would show it over the view it is supposed to be a picture of`);
}

/** Where a capture run records WHICH BUILD it photographed. See recordCapture(). */
const CAPTURED_AT = 'captured-at.json';

/**
 * Which leg is holding the shutter — read from `legsRun`, never from the file name.
 *
 * The leg bodies push their own name as they enter and the legs run in sequence, so
 * the last name pushed is the one taking the picture. Deriving it from the `panel-`
 * prefix instead would be a second opinion about which surface a picture is OF, held
 * by a naming habit rather than by the code that opened the shutter — and the whole
 * job of the sidecar is to write down what was actually true at that moment.
 */
const currentLeg = () => legsRun[legsRun.length - 1];

/**
 * The digest of the SOURCES each surface is assembled from — ASKED FOR, not computed.
 *
 * `_output.ui_surface_digests()` is the one home for which files a surface's pictures
 * are of, and this asks it over a pipe. A walk here would be the second
 * implementation of "which files", which is the defect F85's round exists to remove:
 * right on the day it was written, and free to drift from the assembler's afterwards.
 *
 * ONCE PER RUN, not per shot. The sources cannot move while a capture is in flight,
 * and a digest that changed between two shots would leave one sidecar describing two
 * trees. Read before the first shutter for the other half of that: a run that cannot
 * get the digest should say so having written nothing.
 *
 * Reached through the resolver rather than by joining a directory name, for the reason
 * the assembled-page read further up gives — `_output.py` IS the anchor, so putting
 * its own directory on sys.path is all it needs.
 *
 * FAILURE IS RETURNED, not thrown, and it is loud twice over: this run fails by name,
 * and the images it writes carry no digest, which `_refs.screenshot_capture_drift()`
 * reports as a missing basis rather than passing over.
 */
let UI_DIGESTS = null;

function loadUiSourceDigests() {
  const dir = path.dirname(resolveScript('_output.py'));
  let parsed;
  try {
    parsed = JSON.parse(py(['-c', 'import json, sys; '
                                + 'sys.path.insert(0, sys.argv[1]); import _output; '
                                + 'sys.stdout.write(json.dumps('
                                + '_output.ui_surface_digests()))', dir]));
  } catch (err) {
    return `_output.ui_surface_digests() could not be read, so no picture this run `
         + `writes can say which UI it is of: ${err.message}`;
  }
  if (parsed.error) return `the UI sources cannot be digested: ${parsed.error}`;
  if (parsed.unassigned?.length) {
    return `scripts/ui/ holds part(s) belonging to no surface `
         + `(${parsed.unassigned.join(', ')}), so no picture would ever be red `
         + `about a change to them`;
  }
  UI_DIGESTS = parsed.digests;
  note(`ui sources: ${Object.entries(UI_DIGESTS)
    .map(([s, d]) => `${s} ${d.slice(0, 12)}`).join(', ')}`);
  return null;
}

/**
 * Record the version this image was photographed at, beside the image.
 *
 * WHY A SIDECAR AND NOT THE PIXELS. The panel paints its own version in the
 * topbar, so every panel PNG makes a claim about which build it shows, and until
 * this file nothing could settle that claim: reading it back means reading text
 * out of an image, and comparing the pixels is the thing this tool refuses for
 * the reasons in claimScratch's header - font rasterisation differs by host and
 * no environment variable pins it.
 *
 * So the claim is recorded where it CAN be read. It is not a guess either: the
 * panel leg asserts the live topbar names `plugin.json`'s version before any
 * shutter opens, so at the moment a file is written the build in the picture is
 * that version. This writes down what was already checked.
 *
 * PER FILE, NOT PER RUN, and that is the load-bearing part. `--only report`
 * rewrites the report images and leaves the panel ones alone; a single
 * run-level version would then claim the new build for pictures nobody re-shot.
 * Each entry is updated only when its own file is written, so a partial run at a
 * new version leaves the untouched entries naming the old one - which is exactly
 * the state that must go red.
 *
 * Written after EVERY shot rather than once at the end: a run that dies halfway
 * has still changed the images on disk, and an entry whose hash no longer
 * matches its file is the loud version of that. The hash is what stops this file
 * being edited into agreement without the pictures being the ones captured.
 *
 * AND THE VERSION IS NOT THE WHOLE CLAIM (F85). A stamp says which release a
 * picture was taken at; it cannot say whether the UI has moved since, and it did —
 * commits landed under `scripts/ui/` after a re-capture and the rule stayed green
 * over pictures of a panel that no longer existed. So each entry also carries the
 * surface it belongs to and the digest of that surface's SOURCES, which are
 * committed bytes and therefore comparable on any host, unlike the pixels. Per
 * surface for the same reason the version is per file: a report-only change must
 * not ask for the panel's pictures back.
 */
function recordCapture(name, file, surface) {
  const sidecar = path.join(OUT, CAPTURED_AT);
  let body = { note: '', images: {} };
  try {
    const prior = JSON.parse(readFileSync(sidecar, 'utf8'));
    if (prior && typeof prior === 'object' && prior.images) body = prior;
  } catch { /* absent or unreadable: this run rebuilds what it can vouch for */ }
  const version = JSON.parse(
    readFileSync(REPO + '/plugins/audit/.claude-plugin/plugin.json', 'utf8')).version;
  body.note = 'Written by tools/capture-screenshots.mjs. Each entry is the plugin '
    + 'version that was in the picture when that file was written, the hash of the '
    + 'bytes it was written as, the surface it is a picture of, and the digest of '
    + 'that surface\'s UI sources at the moment of the shutter '
    + '(_output.ui_surface_digests). _refs.screenshot_capture_drift() compares all '
    + 'of them; an entry missing the digest is a finding, not silence.';
  if (!surface) {
    fail(`${name}: no capture leg was running when the shutter opened, so which `
       + `surface this picture is of cannot be recorded`);
  }
  const entry = {
    sha256: createHash('sha256').update(readFileSync(file)).digest('hex'),
    version: version,
  };
  if (surface) entry.surface = surface;
  // Omitted rather than defaulted when the digest is unavailable. A placeholder
  // would be a basis the rule could compare and clear, which is the one thing a
  // missing basis must never be able to do.
  if (surface && UI_DIGESTS && UI_DIGESTS[surface]) {
    entry.uiDigest = UI_DIGESTS[surface];
  }
  body.images[`${name}.png`] = entry;
  const ordered = {};
  Object.keys(body.images).sort().forEach((k) => { ordered[k] = body.images[k]; });
  writeFileSync(sidecar, `${JSON.stringify({ note: body.note, images: ordered }, null, 2)}\n`);
}

async function shot(page, name, { full = false, dialog = false } = {}) {
  await settle(page);
  await noToast(page, name);
  if (!dialog) await noDialog(page, name);
  if (CHECK) return;
  mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: full });
  recordCapture(name, file, currentLeg());
  note(`wrote ${path.relative(REPO, file)} (${statSync(file).size} B)`);
}

/** The lockfile that says who owns the scratch tree. See claimScratch(). */
const SCRATCH_LOCK = 'capture.lock';

/**
 * Where the fixture tree goes — the one place that decides it.
 *
 * Named rather than inlined because the panel PAINTS this path (see claimScratch),
 * so it is a value the reproducibility report has to be able to quote. Two spellings
 * of it would let the report name a directory the capture did not use, which is the
 * one thing a provenance line must never do.
 *
 * Per-uid where uids exist, because /tmp is one shared directory and two users
 * capturing at once would meet on a tree neither may write into.
 *
 * NOT `tmpdir()`, and that is the fix rather than a preference: `tmpdir()` reads
 * TMPDIR, so the SAME host under a different environment paints a different path
 * into the topbar and every panel PNG moves. Thirteen of them did exactly that
 * once, and the difference read as product drift until it was chased down — the
 * header above claimed the path was "fixed per HOST", which was nearly true and
 * therefore worse than either alternative. A literal root makes it true as
 * written.
 *
 * `/tmp` and not the home directory, because the panel PAINTS this path: a scratch
 * tree under $HOME carries a username into every committed PNG, which is the same
 * class of leak the fixture-homes section exists to stop. Windows has no /tmp and
 * keeps the platform root; its temp directory is already per-user, and a shell
 * exporting TMPDIR for one command is a POSIX habit rather than a Windows one.
 */
function scratchPath() {
  const root = process.platform === 'win32' ? tmpdir() : '/tmp';
  return path.join(root,
    `audit-shots${process.getuid ? `-${process.getuid()}` : ''}`);
}

/**
 * Does `pid` name a process that exists right now?
 *
 * The JavaScript half of `panel-server._pid_alive`, including its EPERM answer: a
 * pid owned by another user cannot be signalled and IS running, and reading that
 * refusal as "gone" is how one run deletes another's tree.
 */
function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
}

/**
 * The scratch tree this run builds its fixtures in, at a path that is THE SAME ON
 * EVERY RUN — because the path is in the picture.
 *
 * `mkdtempSync(join(tmpdir(), 'audit-shots-'))` was what stood here, and it made
 * every panel screenshot unreproducible. The panel's topbar renders its own project
 * path (`#proj`, middle-elided to 56 characters), so six random characters of a temp
 * directory name were painted into the pixels. Measured on one macOS host, on the 16
 * panel shots that existed then: 14 differed between two runs, and each differed in
 * ONE box — 45x13px at (376,52), the same box every time, and nothing else on any
 * page. The two that held still are the two where that text is not on screen:
 * `panel-mobile`, where `.sub{max-width:min(56ch,100%)}` clips the line at 390px
 * long before the random tail, and `panel-policy-expanded`, where a full-viewport
 * dialog covers the header. The report shots were already byte-identical because
 * they are served over http:// and name no filesystem path at all.
 *
 * That is not a cosmetic difference. While it stood, NO panel regression that
 * reached a screenshot could be found by comparing PNGs, so 14 committed images
 * were documentation and not evidence.
 *
 * FIXED IN THE ENVIRONMENT, NOT IN THE PAGE. Overwriting `#proj` from here after
 * load would put a string in the picture that the product never produced, and it
 * would fix only the surface someone remembered — the theme card names the file it
 * read, the help drawer quotes paths, and each would drift on its own schedule.
 * This is the choice the demo git identity already makes below: hand the fixture a
 * demo environment and change nothing about the product.
 *
 * A FIXED PATH IS A SHARED PATH, so it is claimed rather than assumed. Two captures
 * at once would otherwise share one fixture tree AND one panel: `panel-server.serve`
 * enforces one panel per project, so the second run would attach to the first run's
 * panel — a different fixture behind a different token — and whichever finished
 * first would `--stop` it and delete the tree under the other. The claim is an
 * exclusive-create lockfile carrying the owner's pid. A pid that is gone means a run
 * that died before its `finally`, not a live one, so that tree is reclaimed with a
 * note rather than blocking every capture until someone deletes it by hand.
 *
 * AND HERE IS WHAT IT DOES NOT BUY, which is F18 and is stated here because this is
 * where somebody reads about reproducibility and decides what it is worth. The fixed
 * path is fixed PER MACHINE and cannot be anything else: a Linux runner writes
 * `/tmp/audit-shots-<uid>` where a Mac writes `/var/folders/…/T/audit-shots-<uid>`,
 * so the panel images carry different bytes on different hosts — `--repro` prints
 * how many of them and on which host. Every candidate repair for that trades
 * something real, and the reasons they were declined are kept, because the next
 * person to look will have the same three ideas:
 *
 *   * A CONSTANT PATH. Dropping the uid suffix loses the thing it is there for —
 *     two users on one Linux box colliding in a shared /tmp — and there is no
 *     constant that holds anyway: Windows has no `/tmp`, and macOS's `tmpdir()` is
 *     not it either, so "pin it" means "pick one platform".
 *   * OVERWRITING `#proj` FROM HERE. Argued against three paragraphs up, and the
 *     argument is unchanged: it puts a string in the picture the product never
 *     produced, on whichever surface someone remembered.
 *   * MASKING THE TOPBAR BOX in a comparison. That region is 45x13px of a bar that
 *     also carries the tab strip, the render control and the report link — the
 *     chrome a reader looks at first — so a mask there is a promise never to see
 *     drift in the most-looked-at part of the page. The argument that would be owed
 *     for that cannot honestly be made.
 *
 * IS THIS THE SOURCE_DATE_EPOCH TRICK AGAIN? It was asked, and the answer is no.
 * `_report_html.stamp_time()` honours SOURCE_DATE_EPOCH, and the artifact
 * freshness check under `tools/` uses it to pin the report's ONE
 * machine-dependent input to a
 * constant, which makes a byte comparison exact. It does not transfer twice over.
 * A clock can be pinned to any integer; a scratch directory has to EXIST and be
 * writable, so there is no constant to pin it to. And the path is not even the
 * binding constraint here — font rasterisation differs between macOS and CI Linux,
 * which is why CI already refuses to compare these pixels, and no environment
 * variable pins that at all. The report had one such input and the panel has at
 * least two, one of them unpinnable; that is the difference between the two cases.
 *
 * SO THE LIMIT IS STATED RATHER THAN FAKED, and it is stated as something that runs:
 * `--repro` measures within-machine reproducibility on the host it is running on and
 * prints that host alongside the number. See reproduce().
 */
function claimScratch() {
  const work = scratchPath();
  const lock = path.join(work, SCRATCH_LOCK);
  const mine = String(process.pid);
  mkdirSync(work, { recursive: true });
  try {
    writeFileSync(lock, mine, { flag: 'wx' });   // create-or-fail, in one syscall
  } catch (e) {
    if (e.code !== 'EEXIST') throw e;
    const held = Number(String(readFileSync(lock, 'utf8')).trim());
    if (pidAlive(held)) {
      throw new Error(`another capture (pid ${held}) already holds ${work}. Both runs `
        + 'would build fixtures in the same tree and talk to the same panel — '
        + 'panel-server allows one panel per project — so this one would photograph '
        + 'that one\'s state and then delete it. Wait for it to finish, or stop it.');
    }
    note(`scratch: ${work} was locked by pid ${held || '(unreadable)'}, which is gone `
       + '— that run died before its cleanup, so reclaiming the tree');
    rmSync(work, { recursive: true, force: true });
    mkdirSync(work, { recursive: true });
    try {
      writeFileSync(lock, mine, { flag: 'wx' });
    } catch (raced) {
      throw new Error(`two captures reclaimed the stale ${work} in the same instant `
        + `(${raced.code}) — neither can trust the tree it is holding; run again`);
    }
  }
  // Anything else in here is debris from a run that died without its `finally`. A
  // stale manifest or a stale panel pidfile would make this run's pictures a
  // function of the last one's, which is the property being fixed.
  for (const entry of readdirSync(work)) {
    if (entry !== SCRATCH_LOCK) {
      rmSync(path.join(work, entry), { recursive: true, force: true });
    }
  }
  return work;
}

/**
 * The host, in the terms that decide what a panel PNG's bytes come out as.
 *
 * Not decoration and not a log line: it is the SCOPE attached to the number
 * `--repro` prints, and a number without its scope is the defect this repo keeps
 * meeting. The browser build is read by launching one rather than by reading a
 * package version — the version that matters is the binary that rasterised the
 * text, and a lockfile entry is a claim about which binary was fetched.
 */
async function machineFingerprint() {
  let browser = '(chromium could not be launched, so the build that would '
              + 'rasterise these pixels is unknown)';
  try {
    const { chromium } = await import('playwright');
    const b = await chromium.launch();
    browser = `chromium ${b.version()}`;
    await b.close();
  } catch (e) {
    browser = `(chromium could not be launched: ${String(e.message).split('\n')[0]})`;
  }
  return {
    host: `${process.platform}/${process.arch}`,
    kernel: release(),
    node: process.version,
    browser,
    scratch: scratchPath(),
  };
}

// --- reproduce: two captures compared ------------------------------------------

/**
 * `--repro`: are two consecutive captures ON THIS MACHINE byte-identical?
 *
 * F18. The panel PNGs became reproducible within one machine and nothing could
 * re-derive that: it was a sentence in a docstring, measured once, by hand. A
 * property nobody can print is a property that rots, and this repo has the scars to
 * prove it. So the claim is a mode of the tool, and its output carries the machine
 * it was measured on — because that machine IS the scope of the claim.
 *
 * IT DELIBERATELY DOES NOT COMPARE AGAINST docs/screenshots/. That comparison is the
 * one that would quietly pass on the maintainer's Mac and fail on a Linux runner with
 * nobody able to tell whether the difference was drift or the host, which is exactly
 * the outcome F18 rules out. Two fresh captures on one host hold everything except
 * the product constant, so a difference between them is the product or it is a bug in
 * this file — and nothing else.
 *
 * Both captures go to throwaway directories, so this never touches the committed
 * images and cannot be mistaken for a refresh of them.
 *
 * Exit 0 every PNG identical, 1 any difference (including the two runs disagreeing
 * about WHICH files exist, which is a nastier drift than differing bytes), 2 when
 * there was nothing to compare — a capture that failed, or one that wrote no image.
 * "0 of 0 identical" must never print as a pass.
 */
async function reproduce() {
  if (CHECK) {
    console.error('--repro and --check cannot be combined: --check writes no PNGs, so '
      + 'the comparison would run over two empty directories and report that nothing '
      + 'differed. Run --repro on its own.');
    process.exit(2);
  }
  // Refused rather than ignored. A caller who passed --out expects images where they
  // asked for them, and silently putting them somewhere else is the shape of bug
  // this file's own docstring opens with.
  if (argv.includes('--out')) {
    console.error('--repro cannot honour --out: it captures TWICE and the two runs must '
      + 'not land in the same directory, so it uses throwaway ones. Run --repro on its '
      + 'own, or run a plain capture if what you want is images at a path.');
    process.exit(2);
  }
  const self = fileURLToPath(import.meta.url);
  const dirs = [];
  const passthrough = ONLY === 'all' ? [] : ['--only', ONLY];
  try {
    for (let i = 0; i < 2; i += 1) {
      const dir = path.join(tmpdir(), `audit-repro-${process.pid}-${i}`);
      rmSync(dir, { recursive: true, force: true });
      mkdirSync(dir, { recursive: true });
      dirs.push(dir);
      console.log(`\n=== repro capture ${i + 1} of 2 -> ${dir}\n`);
      const r = spawnSync(process.execPath, [self, '--out', dir, ...passthrough],
                          { stdio: 'inherit' });
      if (r.status !== 0) {
        console.error(`\ncapture ${i + 1} of 2 exited ${r.status === null ? 'on a signal'
          : r.status}. There is nothing to compare, and comparing what it did manage to `
          + 'write would report "identical" about a run that fell over — exit 2.');
        process.exit(2);
      }
    }
    const pngs = (d) => readdirSync(d).filter((f) => f.endsWith('.png')).sort();
    const [a, b] = dirs.map(pngs);
    const fp = await machineFingerprint();
    const scope = [
      '',
      'THIS IS A WITHIN-MACHINE CLAIM AND NOTHING MORE (F18).',
      '  * Nothing here was compared against docs/screenshots/.',
      '  * It does not hold on another machine, and that is not a gap waiting to be',
      '    closed: the panel paints its own project path into the topbar, so the',
      '    scratch tree above is in the pixels and no constant path exists across',
      '    macOS, Linux and Windows. The committed PNGs are additionally rasterised',
      '    by the host fonts, which no environment variable pins — so even a fixed',
      '    path would not make a cross-machine byte comparison mean anything. That',
      '    is why CI runs --check and never diffs these images.',
      '  * What it therefore CANNOT see: any drift that both captures reproduce,',
      '    which is every drift the product introduces deliberately. This says the',
      '    capture is deterministic, never that the pictures are right.',
      '',
      `machine: ${fp.host}, kernel ${fp.kernel}, node ${fp.node}, ${fp.browser}`,
      `scratch tree this capture used, which the panel paints: ${fp.scratch}`,
    ].join('\n');

    if (!a.length && !b.length) {
      console.error(`\nboth captures exited 0 and neither wrote a PNG, so 0 files were `
        + 'compared. A comparison with nothing in it is not a pass — exit 2.');
      console.error(scope);
      process.exit(2);
    }
    const onlyA = a.filter((f) => !b.includes(f));
    const onlyB = b.filter((f) => !a.includes(f));
    const shared = a.filter((f) => b.includes(f));
    const differ = shared.filter((f) =>
      !readFileSync(path.join(dirs[0], f)).equals(readFileSync(path.join(dirs[1], f))));
    const bad = [];
    if (onlyA.length || onlyB.length) {
      bad.push(`the two runs disagree about which files exist — only in run 1: `
        + `${onlyA.join(', ') || 'none'}; only in run 2: ${onlyB.join(', ') || 'none'}`);
    }
    if (differ.length) {
      bad.push(`${differ.length} of ${shared.length} PNG(s) differ between two `
        + `consecutive captures on this machine: ${differ.join(', ')}`);
    }
    if (bad.length) {
      console.log('');
      for (const m of bad) console.log(`FAIL ${m}`);
      console.log(scope);
      console.log(`\nFAILED (exit 1): the capture is not reproducible even on one host, `
        + 'so comparing its output against anything cannot tell drift from noise');
      console.error(`capture-screenshots --repro FAILED: ${bad.length} problem(s)`);
      process.exit(1);
    }
    console.log(`\nOK (exit 0): ${shared.length} of ${shared.length} PNG(s) are `
      + 'byte-identical across two consecutive captures');
    console.log(scope);
  } finally {
    for (const d of dirs) rmSync(d, { recursive: true, force: true });
  }
}
// --- the run itself ------------------------------------------------------------


async function main() {
  // What the extracted stages used to close over from module scope, handed to them
  // instead. Built once and read-only: a stage that needed something new would have
  // to say so in its signature, which is the property the split was for. `tabTo`,
  // `shot` and `awaitConfirmDialog` are function declarations and therefore hoisted,
  // so naming them here is safe however far below they sit.
  const stageCtx = { note, fail, tabTo, shot, awaitConfirmDialog };
  let chromium;
  try {
    ({ chromium } = await import('playwright'));
  } catch {
    console.error('playwright is not available. Run with:\n'
      + '  npx --yes --package=playwright@1.56.0 node tools/capture-screenshots.mjs');
    process.exit(2);
  }

  // BEFORE the scratch tree and before any shutter: a run that cannot say which UI
  // its pictures are of should say so having written nothing, and --check reaches
  // this line too, so the pipe to `_output.py` is exercised by the gate rather than
  // only by the run that needs it.
  const uiProblem = loadUiSourceDigests();
  if (uiProblem) fail(uiProblem);

  const work = claimScratch();
  const servers = [];
  let panel = null;
  let polPanel = null;          // the policy fixture's own panel — its own HOME
  // SCROLLBAR METRICS ARE AMBIENT, AND THIS FILE MEASURES WIDTHS. Chromium picks
  // overlay scrollbars or classic ones from the host: on macOS from a system
  // preference whose default ("Automatic") flips with whether a mouse is plugged
  // in, on CI Linux from the platform default. `html{scrollbar-gutter:stable}`
  // then reserves 15px or nothing, which moves every right-aligned box by 15px —
  // and 15px was enough to fail combo(a) on the maintainer's Mac while CI stayed
  // green through a release, the check people then learn to ignore locally. One
  // model, pinned, so a width measured here is the width CI measures. Disable
  // beats enable in Chromium's feature list, so this holds whatever the host
  // would have chosen; it is the model CI resolves to today, so --check does not
  // move there. A capture taken on a host that WAS choosing overlay will move by
  // those 15px — which is the drift this removes, not one it introduces.
  const browser = await chromium.launch({ args: ['--disable-features=OverlayScrollbar'] });

  try {
    // ---- report shots, from the committed example -------------------------------
    if (wanted('report')) {
      legsRun.push('report');
      const acme = path.join(work, 'acme');
      mkdirSync(acme, { recursive: true });
      py([resolveScript('render-report.py'),
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
      // Before any click: 2.5.3 is about the page as it is FOUND, and the legs
      // below expand rows and press chips.
      await assertLabelInName(page, [{ name: 'report', sel: 'body' }], 'report');
      await shot(page, 'overview', { full: true });

      await page.click('#audit-expand');
      await page.waitForTimeout(120);
      await shot(page, 'expanded');

      // Filter to one phase status, which is what the chip row is for.
      //
      // `:not([hidden])`, because the chip set now FOLLOWS the view: with the
      // default `active` view a plan's `done` chip is hidden, and it is usually
      // first in DOM order. Clicking blind picked it and timed out on an element
      // the page had deliberately taken away — which is the change working, and
      // this harness assuming otherwise.
      const chip = page.locator('#audit-phase-status button:not([hidden])').first();
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
          // Releasing the chip returns to the AT-REST view, and since vw
          // (F-P-4) "at rest" means the chosen VIEW — the archived phases are
          // off screen unless the reader asked for them. The expectation reads
          // the select's own value rather than assuming every row shows.
          const back = await page.evaluate(() => {
            const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
            const view = (document.getElementById('audit-view') || {}).value || 'all';
            const segs = view === 'active' ? ['active', 'pending']
              : view === 'archived' ? ['archived'] : ['active', 'pending', 'archived'];
            return { shown: rows.filter((r) => r.style.display !== 'none').length,
                     view,
                     want: rows.filter((r) =>
                       segs.indexOf(r.getAttribute('data-seg')) >= 0).length };
          });
          if (back.shown !== back.want) {
            fail(`report: releasing the "${pick.tag}" area chip left `
               + `${back.shown}/${pick.total} phase rows (want ${back.want} in `
               + `the "${back.view}" view)`);
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

      // The report's half of the responsive contract. Its own context, AFTER
      // every shot, because the walk resizes twenty-one times and scrolls to
      // both ends of the document: run before a shutter it would decide what
      // the picture is a picture of. The report had no whole-document overflow
      // assertion at any width before this — 360x800 was opened, photographed,
      // and asserted nothing — so this is the first time any of it is measured.
      const ladderCtx = await browser.newContext({
        viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'light',
      });
      const ladder = await ladderCtx.newPage();
      const ladderErrors = [];
      ladder.on('pageerror', (e) => ladderErrors.push(String(e.message).split('\n')[0]));
      await ladder.goto(url, { waitUntil: 'load' });
      await settle(ladder);
      // The Detail disclosure is IN FLOW: opening it lengthens the document
      // rather than covering it, and the heatmap, the small multiples and the
      // ranked lists have no layout at all while it is shut. Opened here so the
      // ladder measures them; the More-filters popover, which IS a layer, is
      // left shut. Same split as check-report-interactive.mjs's step 10.
      await ladder.evaluate(() => {
        const m = document.querySelector('details.more');
        if (m) m.open = true;
        const d = document.querySelector('.fdetails');
        if (d) d.open = false;
      });
      await ladder.waitForTimeout(250);
      const reportTally = newLadderTally();
      await walkResponsiveLadder(ladder, 'report', reportTally,
                                 { report: fail, ok: note, fast: FAST });
      assertLadderMeasuredSomething('report', reportTally, { report: fail, ok: note });
      if (ladderErrors.length) {
        fail(`the report logged ${ladderErrors.length} script error(s) while being `
           + `resized across the ladder: ${[...new Set(ladderErrors)].slice(0, 3).join(' | ')}`);
      }
      await ladderCtx.close();

      // ---- the same example, PINNED, so the Sort control is on the page ------
      // No shot is taken here: the published pictures show written order on
      // purpose. This exists because the control cannot be reached from the
      // committed artifact at all, and an unreachable check is a green one.
      const prioDir = path.join(work, 'acme-prio');
      mkdirSync(prioDir, { recursive: true });
      cpSync(path.join(REPO, 'examples', 'acme-store', 'audit-plan.json'),
             path.join(prioDir, 'audit-plan.json'));
      cpSync(path.join(REPO, 'examples', 'acme-store', 'phases'),
             path.join(prioDir, 'phases'), { recursive: true });
      // Through the real write path, so a change that breaks writing a priority
      // breaks this too. BF1 is last in the array and P3 is held by P2, which is
      // the pair the feature exists for: one phase reached first, one pinned and
      // still waiting.
      py([resolveScript('set-priority.py'),
          path.join(prioDir, 'audit-plan.json'), 'BF1', '1']);
      py([resolveScript('set-priority.py'),
          path.join(prioDir, 'audit-plan.json'), 'P3', '2']);
      const prioOut = path.join(prioDir, 'out');
      py([resolveScript('render-report.py'),
          path.join(prioDir, 'audit-plan.json'), '--out-dir', prioOut],
         { CLAUDE_PROJECT_DIR: prioDir });

      const { server: prioServer, port: prioPort } = await serveDir(prioOut);
      servers.push(prioServer);
      const prioCtx = await browser.newContext({
        viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1,
        reducedMotion: 'reduce', colorScheme: 'light',
      });
      const prioPage = await prioCtx.newPage();
      const prioErrors = [];
      prioPage.on('pageerror', (e) => prioErrors.push(String(e.message).split('\n')[0]));
      await prioPage.goto(`http://127.0.0.1:${prioPort}/acme-store-audit.html`,
                          { waitUntil: 'load' });
      await settle(prioPage);
      await assertPhaseOrderMoves(prioPage);
      if (prioErrors.length) {
        fail(`report/order: the prioritised report logged ${prioErrors.length} script `
           + `error(s): ${[...new Set(prioErrors)].slice(0, 3).join(' | ')}`);
      }
      await prioCtx.close();
    }

    // ---- panel shots, from a generated 50 x 20 fixture --------------------------
    if (wanted('panel')) {
      legsRun.push('panel');
      const big = path.join(work, 'big');
      py([resolveScript('gen-demo-manifest.py'), big, '--phases', '50', '--tasks', '20']);
      py([resolveScript('gen-demo-usage.py'), path.join(big, 'audit-plan.json')]);

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
      // ...and a HOME, for the same reason and by the same mechanism: discovery
      // walks `~/.claude`, the building-blocks table paints what it finds, and
      // `panel-blocks` committed one machine's hundred-odd installed skills.
      // See the fixture-homes section for the whole argument.
      const bigfx = writeBigFixture(work, big);
      panel = await startPanel(big, {
        HOME: bigfx.home, USERPROFILE: bigfx.home,
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
      // NAME THE VIEW, do not inherit it. Everything from here to the help drawer
      // photographs and drives Settings, and it used to arrive there by landing
      // there: `guards` led the strip, so a fresh load opened it. It does not any
      // more - Overview leads - and the failure that change produced is the reason
      // this line exists: the drawer click found a control inside a hidden view and
      // spent its whole timeout on it. The shot above it would have been the wrong
      // tab entirely, and silently.
      await tabTo(page, 'guards');
      for (const t of ['guards', 'comp', 'over', 'usage', 'policy', 'props']) {
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

      // The other half of the same rule, and asserted in the same place and for the
      // same reason: an env override that stops taking fails silently, and here the
      // silence lands in `panel-blocks` as somebody's plugin inventory.
      await assertFixtureDiscovery(page, bigfx.want, 'panel');
      await assertManifestSkillsDiscovered(page);

      // Settings is rendered by that script, from the field table panel-server.py
      // ships. Both halves are asserted: the cards exist, and every declared setting
      // put a control in the document — so a field added in Python and never wired
      // up in the UI fails here rather than silently not existing.
      const declared = JSON.parse(py([resolveScript('panel-server.py'),
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
      await tabTo(page, 'comp');
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
      await tabTo(page, 'over');
      await page.waitForFunction(
        () => { const o = document.querySelector('#over');
                return o && o.querySelectorAll('.card').length > 0; },
        null, { timeout: 20000 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await shot(page, 'panel-overview', { full: true });
      await assertOverviewWorks(page, stageCtx);

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

      await tabTo(page, 'usage');
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
      await tabTo(mob, 'over');
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
        await tabTo(mob, tab);
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
      for (const t of ['guards', 'comp', 'over', 'usage', 'policy', 'props']) {
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
      await tabTo(mob, 'comp');
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
      // The same grid claim at phone width. It is not the desktop run repeated:
      // below the shell breakpoint every column is at its minimum and the table
      // is wider than its frame, which is where a cell that quietly grew the
      // minimum shows up as sideways scroll rather than as a narrower column.
      await assertCompositionColumns(mob, stageCtx);
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
      await tabTo(mob, 'guards');
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
      await tabTo(mob, 'over');
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
      await tabTo(mob, 'guards');
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
      await tabTo(mob, 'policy');
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
      await tabTo(mob, 'usage');
      await mob.waitForTimeout(400);
      // The task combo lives inside the Filters fold, and Playwright will not
      // click into a shut `<details>` — it waits the full 30s and the timeout
      // reads like a dead panel rather than a closed disclosure. This is the
      // fourth leg that drives a usage filter; the other three call the same
      // helper, and a leg that opens the fold itself would be a second way of
      // doing it. `mob` keeps its own first-visit assertions, so the fold is
      // held to arriving shut at 390px too, not only at desktop width.
      await openUsageFilters(mob);
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

      // The panel's half of the responsive contract, over all five views. The
      // 390px sweep above stays: it is the phone this shot is taken on and it
      // drives the ⓘ, the tab strip and the drawer, none of which the ladder
      // touches. What the ladder adds is every OTHER width — 320 and 390 were
      // the only two ever exercised, so nothing between 390 and 1200 had been
      // looked at on either surface.
      //
      // Last in this context, after the shot and after every check that needs a
      // 390px viewport, because it leaves the page at 1512px and at the top of
      // whichever view it finished on.
      const panelTally = newLadderTally();
      for (const t of ['guards', 'comp', 'over', 'usage', 'policy', 'props']) {
        await mob.setViewportSize({ width: 390, height: 844 });
        await mob.mouse.move(0, 0);
        await tabTo(mob, t);
        await mob.waitForFunction(
          (v) => { const n = document.getElementById(v);
                   return n && !n.classList.contains('hidden')
                     && n.querySelectorAll('.card').length > 0; },
          t, { timeout: 20000 });
        await mob.waitForTimeout(250);
        // The pointer is parked off every control first, for the same reason
        // the 390px sweep parks it: what is measured is the resting layout, not
        // the layout plus whatever the mouse happens to be touching.
        await mob.mouse.move(0, 0);
        await walkResponsiveLadder(mob, `panel ${t}`, panelTally,
                                   { report: fail, ok: note, fast: FAST });
      }
      assertLadderMeasuredSomething('panel', panelTally, { report: fail, ok: note });
      await mobCtx.close();
      // Deliberately AFTER the last capture. Driving Usage ends in an export, and an
      // export raises a toast — which the dark shot caught and committed, a banner
      // reading "2132 row(s) exported" pinned across a screenshot of the default
      // view. A check that leaves transient UI behind must run where no shutter
      // follows it, not merely be timed to miss one.
      await assertUsageWorks(page);
      await assertViewerIdentity(page);
      await assertHintClickIsInert(page, ['guards', 'comp', 'policy', 'look']
        .map((t) => ({ name: t, sel: '#' + t,
          show: async () => { await page.evaluate((x) => {
            if (typeof showTab === 'function') showTab(x); }, t);
            await page.waitForTimeout(250); } })));
      await assertLabelInName(page, ['guards', 'comp', 'over', 'usage', 'policy', 'look']
        .map((t) => ({ name: t, sel: '#' + t,
          show: async () => { await page.evaluate((x) => {
            if (typeof showTab === 'function') showTab(x); }, t);
            await page.waitForTimeout(250); } })), 'panel');
      if (FAST) {
        FAST_SKIPPED.push('focus traversal (SC 2.4.11, every focus stop in both '
          + 'directions across six tabs)');
        FAST_SKIPPED.push('target-size census (SC 2.5.8, every control at three '
          + 'densities)');
      } else {
        await assertFocusNotObscured(page);
        await assertTargetSizeAcrossDensities(page);
      }
      // Reads only, but it opens a modal over every tab it visits, so it runs
      // where no shutter follows it — the same rule the toast waiter enforces.
      await assertHelpDrawerWorks(page, declared, stageCtx);
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
      // Injects a long title into the fixture's IN-PAGE composition and puts it
      // back inside the same synchronous evaluate, so it writes nothing to disk
      // and leaves no state behind — but it re-renders #comp, so it keeps to the
      // same block as the why-note leg rather than running before a shutter.
      await assertCompositionColumns(page, stageCtx);
      await assertComboSearchCount(page);
      await assertFilterPersistence(page, browser, panel.url);
      await assertSaveNoteLifecycle(page);
      await assertLiveData(page, big);
      // co (F-P-1): appends a blank line to the fixture's ledger, so it keeps to
      // the writes-last discipline too.
      await assertComboOverlay(page, big);
      await assertUncategorizedNamed(page);
      await assertAppearanceWorks(page, stageCtx);
      // gt (v0.34 B3): writes into the fixture's logs/state dirs, so it keeps
      // to the same writes-last discipline and runs after live-data.
      await assertGateCard(page, big);
      await assertSavebarCensus(page);
      await assertTableHeaders(page);

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

        await assertFixtureDiscovery(ppage, fx.want, 'policy');

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
        await tabTo(ppage, 'policy');
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
        await tabTo(ppage, 'policy');
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
        await assertPolicyWorks(ppage, path.join(seen.dir, seen.file), stageCtx);
        // The shot comes FIRST: assertProposalsWork below drops and materializes,
        // so a capture taken after it would publish a tab mid-experiment. One card
        // is opened so the payload is in frame — a page of collapsed summaries
        // shows the list but not what a proposal actually is.
        await tabTo(ppage, 'props');
        await ppage.waitForSelector('#props .card', { timeout: 15000 });
        await ppage.evaluate(() => {
          const d = document.querySelector('#props details.prop');
          if (d) d.open = true;
        });
        await ppage.waitForTimeout(250);
        await shot(ppage, 'panel-proposals');
        // Writes the fixture's MANIFEST (not its config), so it runs beside the
        // other writers rather than before the shots above.
        await assertProposalsWork(ppage);
        await assertPolicyExpand(ppage);
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
      try { py([resolveScript('panel-server.py'), '--project',
                path.join(work, 'big'), '--stop']); } catch { /* best effort */ }
      try { panel.proc.kill('SIGTERM'); } catch { /* already gone */ }
    }
    if (polPanel) {
      try { py([resolveScript('panel-server.py'), '--project',
                polPanel.project, '--stop']); } catch { /* best effort */ }
      try { polPanel.proc.kill('SIGTERM'); } catch { /* already gone */ }
    }
    for (const s of servers) s.close();
    rmSync(work, { recursive: true, force: true });
  }

  // The liveness verdict for the panel leg. Reported here rather than inside the
  // leg because it is a statement ABOUT the leg — every tabTo along the way fed
  // the tally, and this is the one line that says whether any of them compared
  // anything. Asked only when the leg ran: a --only report run has no tabs, and a
  // guard that fails for not having been given work to do is a guard people learn
  // to pass a flag around.
  if (legsRun.includes('panel')) {
    assertLivenessWasChecked('panel', panelLiveness, { report: fail, ok: note });
  }

  // The vacuity guard for the run itself: a capture that ran no leg has measured
  // nothing, and "nothing to report" must never be printed as "nothing wrong".
  if (!legsRun.length) {
    fail(`no leg of this capture ran (--only ${JSON.stringify(ONLY)}), so nothing `
       + `was measured — a run with nothing to look at has to fail, not print OK`);
  }

  // A stage nobody calls reports nothing and fails nothing, which reads exactly
  // like a stage that passed.
  // THE ORCHESTRATOR PLUS ITS MODULES. Handing this its own source alone was
  // correct while every stage lived in one file; after four concerns moved into
  // tools/ui-checks/ it would have graded their stages as absent rather than as
  // unwired — a guard narrowing itself, silently, as a side effect of a split.
  const unwired = unwiredStages(stageSources());
  if (unwired.length) {
    fail(`${unwired.length} assert stage(s) are declared and never called, so `
       + `whatever they check went ungraded: ${unwired.join(', ')}`);
  }

  if (problems.length) {
    console.log(`\n${problems.length} problem(s):`);
    for (const p of problems) console.log(`  - ${p}`);
    // The verdict is the LAST line, it names its own exit code, and it is
    // repeated on stderr. The problem list used to end the output, so a caller
    // that piped this — `... | tee log`, `... | tail -20` — read a red run's
    // findings while `$?` reported the pipeline's last command and not this one.
    // A summary that cannot be told apart from a green one by the text alone is
    // the same silent pass one layer out, wearing somebody else's exit code.
    console.log(`\nFAILED (exit 1): ${problems.length} problem(s) across `
      + `${legsRun.join(' + ') || 'no leg'}`);
    console.error(`capture-screenshots FAILED: ${problems.length} problem(s)`);
    process.exit(1);
  }
  if (FAST) {
    // Deliberately NOT the word this prints on a full run. A fast run that ends
    // with "preconditions hold" is a green light nobody earned, and the next
    // person to trust it will be the author of whatever it skipped.
    console.log(`\nFAST (exit 0): the functional checks passed on `
      + `${legsRun.join(' + ')} — THIS IS NOT THE GATE.`);
    for (const s2 of ['width ladder narrowed to 6 boundary rungs of '
                      + `${RESPONSIVE_LADDER.length}`].concat(FAST_SKIPPED)) {
      console.log(`  skipped: ${s2}`);
    }
    console.log('  run without --fast before trusting a change.');
    return;
  }
  console.log(`\nOK (exit 0): ${CHECK ? 'capture preconditions hold'
    : 'screenshots captured'} — ${legsRun.join(' + ')}`);
}

// Run only when invoked as a CLI: the exported CSV helpers above are imported
// by red-first probes, and an import that launched a full capture would make
// every probe a screenshot run.
if (process.argv[1]
    && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  (REPRO ? reproduce() : main())
    .catch((err) => { console.error(err); process.exit(1); });
}
