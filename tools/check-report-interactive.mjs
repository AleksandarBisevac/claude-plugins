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
await page.keyboard.press('Escape');
await page.waitForTimeout(250);

// 4. A status chip in the toolbar.
if (await page.$('.fchip')) {
  await page.click('.fchip');
  await page.waitForTimeout(250);
  const chip = await state();
  if (chip.phases === load.total) failures.push('FAIL a status chip filters the phase list: nothing changed');
  else notes.push(`ok   a status chip filters the phase list: ${chip.phases} of ${load.total}`);
} else notes.push('ok   (no status chips in this report — skipped)');

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
