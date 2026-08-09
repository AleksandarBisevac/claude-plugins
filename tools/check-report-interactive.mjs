#!/usr/bin/env node
/**
 * Does the rendered report still WORK, not just still contain the right strings?
 *
 * CI has always grepped the report for markers (`grep -q 'id="usage"'`). A
 * JavaScript error that kills every event handler leaves every one of those
 * markers intact, so the report could ship completely inert with CI green — and
 * the interactive layer is roughly a third of render-report.py. This drives the
 * real file in a real browser and asserts on what a reader would see.
 *
 *   node tools/check-report-interactive.mjs <report.html>
 *
 * Exit 0 = every interaction behaved. Exit 1 = something is inert; the failing
 * assertion names which. Exit 2 = could not run (no browser, bad arguments) —
 * distinct on purpose, so a missing dependency is never read as a passing check.
 *
 * It also drives the one output nobody opens before shipping. The print rules
 * are checked under `emulateMedia('print')` and the orientation is read back out
 * of a generated PDF's page box — a stylesheet can be pinned string by string
 * and still lay the page out for the wrong medium, or refuse the reader an
 * orientation, with every pin green.
 *
 * Opened over `file://`, because that is how people actually open a report: the
 * product's whole sharing story before the Artifact path was "send them the HTML".
 * localStorage and clipboard behave differently on that origin, so testing over
 * http:// would be testing the easier case.
 */
import { chromium } from 'playwright';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const file = process.argv[2];
if (!file) {
  console.error('usage: check-report-interactive.mjs <report.html>');
  process.exit(2);
}
const path = resolve(file);
if (!existsSync(path)) {
  console.error(`no such file: ${path}`);
  process.exit(2);
}

const failures = [];
const notes = [];
function expect(label, actual, wanted) {
  const ok = actual === wanted;
  (ok ? notes : failures).push(`${ok ? 'ok  ' : 'FAIL'} ${label}: got ${actual}, want ${wanted}`);
}

let browser;
try {
  browser = await chromium.launch();
} catch (e) {
  console.error(`cannot launch chromium: ${e.message.split('\n')[0]}`);
  console.error('run `npx playwright install chromium`');
  process.exit(2);
}

const page = await browser.newPage({ viewport: { width: 1512, height: 945 } });
const pageErrors = [];
page.on('pageerror', (e) => pageErrors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error' && !/favicon/.test(m.text())) pageErrors.push(m.text()); });

await page.goto('file://' + path);
await page.waitForTimeout(300);

// Counts of what is VISIBLE, which is the only thing a reader can act on.
// `style.display` for phase rows because the filter sets it inline; offsetParent
// for task rows because those are collapsed by a class on the parent.
const state = () => page.evaluate(() => {
  const g = document.querySelector('table.phases');
  if (!g) return null;
  return {
    phases: [...g.querySelectorAll('tbody tr.phase')].filter((r) => r.style.display !== 'none').length,
    tasks: [...g.querySelectorAll('tbody tr.task')].filter((r) => r.offsetParent !== null).length,
    total: g.querySelectorAll('tbody tr.phase').length,
    count: (document.getElementById('audit-count') || {}).textContent || '',
  };
});

const load = await state();
if (!load) {
  console.error('FAIL: no table.phases in the document — the report did not render its phase table');
  await browser.close();
  process.exit(1);
}
if (load.total < 2) {
  console.error(`cannot check interactivity: only ${load.total} phase row(s); use a report with several`);
  await browser.close();
  process.exit(2);
}
expect('on load, every phase is listed', load.phases, load.total);
expect('on load, tasks are collapsed', load.tasks, 0);

// The no-script banner. It is rendered into the HTML and removed by the script's
// very first statement, so its ABSENCE is live proof that the script ran — and
// its presence is exactly what a reader sees in an IDE preview pane, which
// sandboxes inline <script> and was the real cause of one "the report is broken"
// report. Checking it here means the banner can never rot into a lie: if the
// removal breaks, the banner shows in a working browser and this goes red.
const banner = await page.$('#audit-nojs');
expect('the no-script banner is removed once the script runs', banner === null, true);

// 1. A click on the phase TITLE — where a reader actually clicks, not the <tr>.
await page.click('table.phases tbody tr.phase strong');
await page.waitForTimeout(150);
const opened = await state();
if (opened.tasks <= 0) failures.push('FAIL clicking a phase title expands its tasks: got 0 visible tasks');
else notes.push(`ok   clicking a phase title expands its tasks: ${opened.tasks} shown`);

await page.click('table.phases tbody tr.phase strong');
await page.waitForTimeout(150);
expect('clicking it again collapses', (await state()).tasks, 0);

// 2. Expand-all, then collapse-all.
await page.click('#audit-expand');
await page.waitForTimeout(150);
const all = await state();
if (all.tasks <= opened.tasks) {
  failures.push(`FAIL expand-all shows more than one phase's tasks: got ${all.tasks}, one phase alone showed ${opened.tasks}`);
} else notes.push(`ok   expand-all shows every phase's tasks: ${all.tasks} shown`);
await page.click('#audit-expand');
await page.waitForTimeout(150);
expect('collapse-all hides them again', (await state()).tasks, 0);

// 3. The filter. 250 ms, not 0 — the input is debounced by 90 ms, and asserting
//    synchronously reads as "the whole script is dead". That false reading has
//    already been made once.
await page.click('#audit-q');
await page.keyboard.type('zzzznotpresentanywhere', { delay: 10 });
await page.waitForTimeout(250);
expect('a filter term that matches nothing hides every phase', (await state()).phases, 0);

await page.keyboard.press('Escape');
await page.waitForTimeout(250);
expect('Escape clears the filter', (await state()).phases, load.total);

// A term taken from the document itself, so this works on any report.
const term = await page.evaluate(() => {
  const s = document.querySelector('table.phases tbody tr.phase strong');
  return s ? s.textContent.trim().split(/\s+/)[0] : '';
});
await page.click('#audit-q');
await page.keyboard.type(term, { delay: 10 });
await page.waitForTimeout(250);
const hit = await state();
if (hit.phases < 1 || hit.phases >= load.total) {
  failures.push(`FAIL filtering by "${term}" narrows the list: got ${hit.phases} of ${load.total}`);
} else notes.push(`ok   filtering by "${term}" narrows the list: ${hit.phases} of ${load.total}`);
if (!/\d+\s*\/\s*\d+/.test(hit.count)) {
  failures.push(`FAIL the count reports the filtered total: got "${hit.count}"`);
} else notes.push(`ok   the count reports the filtered total: "${hit.count}"`);
// A TEXT filter is the one that used to force its matches open — one character
// typed grew the page by screens and scrolled away what was being read, and
// clearing it afterwards shut rows that had been opened by hand. Asserted here
// rather than in a string pin, because `expanded[pid]` reads identically either
// way: only a browser can say whether the rows are on screen.
expect('a text filter does not auto-expand the phases it matches', hit.tasks, 0);
await page.keyboard.press('Escape');
await page.waitForTimeout(250);

// ...and the closed row has to say WHY it survived, which is what replaces the
// expansion: a row reading "1 of 3 match" is a row worth opening. That needs a
// term matching some of a phase's tasks and not the phase's own heading — a term
// the heading carries makes every task a match, and "3 of 3" is deliberately not
// drawn. Found in the document rather than hard-coded, so this works on any report.
const partial = await page.evaluate(() => {
  const g = document.querySelector('table.phases');
  const q = (sel) => [...g.querySelectorAll(sel)];
  for (const pr of q('tbody tr.phase')) {
    const pid = pr.getAttribute('data-phase');
    const sibs = q('tbody tr.task').filter((t) => t.getAttribute('data-phase') === pid);
    if (sibs.length < 2) continue;
    const head = pr.textContent.toLowerCase();
    for (const t of sibs) {
      for (const w of t.textContent.match(/[A-Za-z]{5,}/g) || []) {
        const term = w.toLowerCase();
        if (head.includes(term)) continue;
        const hits = sibs.filter((s) => s.textContent.toLowerCase().includes(term)).length;
        if (hits > 0 && hits < sibs.length) return { term, hits, of: sibs.length };
      }
    }
  }
  return null;
});
if (!partial) {
  notes.push('ok   (no phase in this plan has a partly-matching task set — badge check skipped)');
} else {
  await page.click('#audit-q');
  await page.keyboard.type(partial.term, { delay: 5 });
  await page.waitForTimeout(250);
  const shown = await page.evaluate(() =>
    [...document.querySelectorAll('tr.phase')]
      .filter((r) => r.style.display !== 'none')
      .map((r) => { const b = r.querySelector('.pmatch'); return b && !b.hidden ? b.textContent : ''; })
      .filter(Boolean));
  const wanted = `${partial.hits} of ${partial.of} match`;
  if (!shown.includes(wanted)) {
    failures.push(`FAIL a collapsed phase states how many of its tasks matched: wanted "${wanted}", got ${JSON.stringify(shown)}`);
  } else notes.push(`ok   a collapsed phase states its own match count: "${wanted}"`);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
}

// 4. A status chip in the toolbar.
if (await page.$('#audit-phase-status .fchip')) {
  await page.click('#audit-phase-status .fchip');
  await page.waitForTimeout(250);
  const chip = await state();
  if (chip.phases === load.total) failures.push('FAIL a status chip filters the phase list: nothing changed');
  else notes.push(`ok   a status chip filters the phase list: ${chip.phases} of ${load.total}`);

  expect('a status chip does not auto-expand either', chip.tasks, 0);
  await page.click('#audit-phase-status .fchip');   // release it
  await page.waitForTimeout(250);
  expect('releasing the chip restores every phase', (await state()).phases, load.total);
} else notes.push('ok   (no status chips in this report — skipped)');

// 6. The More-filters panel: model, and the empty state that offers a way back.
//    Skipped rather than failed on a plan that records no models — the panel is
//    emitted from the data, so its absence there is correct.
if (await page.$('#audit-model .fchip')) {
  await page.click('.fdetails > summary');
  await page.waitForTimeout(80);
  await page.click('#audit-model .fchip');
  await page.waitForTimeout(250);
  const m = await state();
  if (m.phases < 1 || m.phases > load.total) {
    failures.push(`FAIL a model chip narrows the table: got ${m.phases} of ${load.total}`);
  } else notes.push(`ok   a model chip narrows the table: ${m.phases} of ${load.total}`);
  if (!/#!.*m=/.test(await page.evaluate(() => location.hash))) {
    failures.push(`FAIL the filtered view is a link: hash is "${await page.evaluate(() => location.hash)}"`);
  } else notes.push('ok   the filtered view is written into the URL');

  // Model AND a text term that cannot co-occur: nothing survives, and the empty
  // state has to appear with the one control that undoes all of it.
  await page.click('#audit-q');
  await page.keyboard.type('zzzznotpresentanywhere', { delay: 5 });
  await page.waitForTimeout(250);
  const empty = await state();
  expect('filtered to nothing, no phase is left', empty.phases, 0);
  const emptyShown = await page.evaluate(() => {
    const r = document.querySelector('tr.norows');
    return !!r && r.style.display !== 'none';
  });
  expect('...and the table says so instead of showing an empty frame', emptyShown, true);
  // The TOOLBAR copy, deliberately: with the panel open, the empty state's own
  // button lands underneath it and cannot be clicked. That is how this line came
  // to exist — the first version clicked the one in the table and timed out
  // against the date input covering it.
  await page.click('.sectools [data-clear]');
  await page.waitForTimeout(250);
  expect('Clear filters puts every phase back', (await state()).phases, load.total);
  expect('...and takes the filter fragment out of the URL with it',
    /#!/.test(await page.evaluate(() => location.hash)), false);
} else notes.push('ok   (this plan records no models — More filters skipped)');

// 7. Paper — the one output nobody looks at before shipping, and the only part
//    of the report a string pin genuinely cannot check: whether the print rules
//    FIRE, and which way round the sheet is allowed to be.
//
//    The document is left filtered down to nothing on purpose. That is the state
//    in which the screen and the page disagree most: the screen says no phase
//    matched, and the page prints every one of them.
await page.click('#audit-q');
await page.keyboard.type('zzzznotpresentanywhere', { delay: 5 });
await page.waitForTimeout(250);
expect('(setting up the print check) the screen is filtered to nothing',
  (await state()).phases, 0);

// A4 portrait inside the stylesheet's 1.4cm margin is ~688px, which is INSIDE
// the 52rem tablet breakpoint — so this is also the width at which the print
// sheet has to undo the small-screen layout.
const paperState = async () => {
  await page.emulateMedia({ media: 'print' });
  await page.setViewportSize({ width: 688, height: 900 });
  await page.waitForTimeout(100);
  const s = await page.evaluate(() => {
    const vis = (el) => el && getComputedStyle(el).display !== 'none';
    const g = document.querySelector('table.phases');
    const rows = [...g.querySelectorAll('tbody tr.phase')];
    const tasks = [...g.querySelectorAll('tbody tr.task')];
    return {
      phases: rows.filter(vis).length,
      total: rows.length,
      tasks: tasks.filter(vis).length,
      totalTasks: tasks.length,
      norows: vis(document.querySelector('tr.norows')),
      pmatch: [...document.querySelectorAll('.pmatch')].filter(vis).length,
      thead: getComputedStyle(g.querySelector('thead')).display,
      wrapOverflow: getComputedStyle(g.closest('.tablewrap')).overflowX,
      topbar: vis(document.querySelector('.topbar')),
    };
  });
  await page.emulateMedia({ media: null });
  await page.setViewportSize({ width: 1512, height: 945 });
  return s;
};

const paper = await paperState();
expect('on paper every phase prints, filtered or not', paper.phases, paper.total);
expect('...and every task with them', paper.tasks, paper.totalTasks);
expect('...so the empty state never reaches the page it contradicts', paper.norows, false);
expect('portrait paper is not treated as a small screen (no scroll frame)', paper.wrapOverflow, 'visible');
expect('the app shell is gone and the document is back', paper.topbar, false);
// Restating a default, and worth asserting for what it catches rather than for
// what it proves: deleting `thead{display:table-header-group}` does NOT turn
// this red, because that is what a <thead> does anyway. What would is the
// responsive pattern that rebuilds a table out of blocks — one `thead{display:
// block}` and page two of a 40-phase plan is unlabelled cells, with the print
// rule still sitting in the stylesheet looking correct.
expect('the column headers repeat onto every page of a long table', paper.thead, 'table-header-group');

// The match badge needs a DIFFERENT filter to be checked at all: filtered to
// nothing there is no visible row to carry one. A partial term leaves the badge
// on screen — asserted above — and paper prints every task it was counting, so
// "1 of 2 match" beside both of them is the statement that must not reach it.
if (partial) {
  await page.click('#audit-q');
  await page.keyboard.press('Escape');       // the setup term is still in there
  await page.waitForTimeout(250);
  await page.keyboard.type(partial.term, { delay: 5 });
  await page.waitForTimeout(250);
  const withBadge = await paperState();
  expect('a badge counting a filtered subset never reaches a page printing all of it',
    withBadge.pmatch, 0);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
} else notes.push('ok   (no partly-matching phase in this plan — print badge check skipped)');

// The orientation itself, measured from the PDF page box rather than believed.
// `size:A4` in the stylesheet is not a hint about paper — Chrome reads it as the
// page box the document REQUIRES and greys the dialog's orientation control out.
// With it present this loop produced 595x842 for BOTH calls; the nine-column
// task table is exactly the thing that wants the other one.
const box = async (landscape) => {
  const pdf = await page.pdf({ preferCSSPageSize: true, landscape });
  const m = /MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]/.exec(pdf.toString('latin1'));
  return m ? { w: Math.round(+m[1]), h: Math.round(+m[2]) } : null;
};
const portrait = await box(false);
const landscape = await box(true);
if (!portrait || !landscape) {
  failures.push('FAIL could not read a page box out of the generated PDF');
} else {
  expect('printed portrait, the page is taller than it is wide',
    portrait.h > portrait.w, true);
  expect(`printed landscape, the reader gets the wider page they asked for `
    + `(portrait ${portrait.w}x${portrait.h}, landscape ${landscape.w}x${landscape.h})`,
    landscape.w > landscape.h, true);
}

if (pageErrors.length) failures.push(`FAIL the page raised ${pageErrors.length} error(s): ${pageErrors.slice(0, 3).join(' | ')}`);
else notes.push('ok   no page errors');

await browser.close();

for (const n of notes) console.log(n);
for (const f of failures) console.log(f);
console.log(
  failures.length
    ? `\nREPORT IS INERT: ${failures.length} interaction(s) did not work in ${file}`
    : `\nreport is interactive: ${notes.length} checks passed in ${file}`);
process.exit(failures.length ? 1 : 0);
