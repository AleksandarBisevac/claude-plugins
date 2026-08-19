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
 * assertion names which. Exit 2 = could not run (no browser, bad arguments, or a
 * report older than these checks) — distinct on purpose, so a missing dependency
 * is never read as a passing check.
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
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
// The width ladder and the contract measured at each rung, defined once in the
// panel's gate and imported here so the two surfaces are asked the SAME
// question at the SAME widths. Two copies would drift the way the shell width
// and the nav breakpoint already have between the two stylesheets (92rem vs
// 96rem, 70rem vs 72rem), and a width present in only one copy is a width the
// other surface is never asked about. Importing that file is inert: everything
// at its top level is a const, and its `main()` runs only when it is the
// process entry point.
import { RESPONSIVE_LADDER, walkResponsiveLadder, assertLadderMeasuredSomething,
         newLadderTally } from './capture-screenshots.mjs';

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
// RFC 4180 field split. The checks below index a CSV row BY COLUMN, and a naive
// `split(',')` lands on the wrong field for any row whose earlier column is a
// quoted field carrying a comma. That is not hypothetical: this repo's own
// manifest has 13 task titles with commas in them and the acme example has none,
// so the sha and stamp assertions passed on every fixture CI rendered and went
// red only against the one plan whose titles read like prose — accusing the
// export of a defect that was in the diagnosis. A checker that reports the wrong
// thing is worse than one that reports nothing.
function csvFields(line) {
  const out = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') quoted = false;
      else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

// --- coverage of this harness's own checks ------------------------------------
//
// `153 checks passed` had NO FLOOR. Every `expect()` result lands in `notes` or
// `failures`, so a section that never executes -- an early guard that skips, an
// element that moved, a leg wrapped in a condition nobody re-read -- simply
// contributes nothing, and the run still ends "report is interactive". A harness
// that reports success for work it did not do is the failure mode this project
// keeps meeting (F23: a restore that killed every listener, after which six tabs
// measured as one and produced a complete, plausible, wrong result set).
//
// The floor is DERIVED FROM THIS FILE'S OWN SOURCE -- the set of `expect(` call
// sites it declares -- and never written down as a number. A constant here would
// rot on the first added check, which is the defect class the count-claim lint
// exists to stop; hard-coding 153 would have been that same bug in a new file.
//
// Measured when this was written, against `examples/acme-store`: 134 declared
// call sites, 130 reached, 153 results (the difference is sites inside loops).
const EXPECT_SITES = new Set();

// The three sites legitimately not reached on every report. Keyed by LABEL TEXT,
// never by line number: a line-number exemption rots the instant anything above
// it moves, and this file is edited from the top. Each names the sibling that
// must have run INSTEAD, so the exemption is self-checking -- if both halves of
// a pair go silent, that is a skipped leg and it fails.
const CONDITIONAL_EXPECTS = [
  { label: 'a plan with nothing active opens on all phases',
    why: 'the else-half of the default-view branch: it runs only on a plan whose '
       + 'default view is not "active"',
    instead: 'on load the archived phases are off screen' },
  { label: '...carrying the outcome the table had to cut short, in full',
    why: 'runs only when a cell actually had to truncate with an ellipsis, which '
       + 'depends on the outcome text in the fixture',
    instead: 'opening one shows the row under its task' },
  { label: '...and hides all',
    why: 'runs only on a plan that HAS untagged phases; where every phase carries '
       + 'a tag there is no untagged half to hide',
    instead: 'every phase in this plan is tagged' },
  { label: 'every phase in this plan shares one status, so its chip hides nothing',
    why: 'the else-half of the chip branch: it runs only on a plan with ONE status, '
       + 'where a chip that hides nothing is the correct behaviour',
    instead: 'a status chip filters the phase list' },
];

function expect(label, actual, wanted) {
  // The call site, so coverage can be graded against the sites this file
  // DECLARES rather than against a number somebody wrote down.
  const frame = (new Error().stack || '').split('\n')[2] || '';
  const at = frame.match(/check-report-interactive\.mjs:(\d+):/);
  if (at) EXPECT_SITES.add(Number(at[1]));
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

// Is this a document these checks can speak about at all?
//
// Every selector below is emitted by the CURRENT renderer into every report,
// whatever the plan contains — so a document without one is a document this tool
// is newer than, and that is a fact about the FILE, not a verdict about the
// product. It has to be said in those words, because both of the ways it used to
// come out read as the report being broken. `.sectools` was dereferenced inside
// page.evaluate and the tool died with `Cannot read properties of null` and a
// stack ending in this file (F7): a diagnostic that dies computing its own
// diagnosis reports the wrong thing twice, and everything it had already checked
// is lost with it, since the notes are printed at the end. Worse, `#audit-nojs`
// was asserted as `banner === null` — trivially true of a report that never
// rendered a banner, so absence came out as a PASS on the one check whose whole
// job is to prove the script ran.
//
// Hence the rule, and it is the rule rather than the patch: an element this tool
// depends on is declared here and its absence is REPORTED BY NAME, never
// dereferenced and never read as an answer. All of them are collected in one
// pass so an old report names everything it is missing at once, instead of one
// element per run.
const source = readFileSync(path, 'utf8');
const REQUIRED = [
  ['table.phases', 'the phase table'],
  ['table.phases thead', 'its column headers'],
  ['table.phases tbody tr.phase strong', 'the phase titles, which is where a reader clicks'],
  ['table.phases tbody tr.task', 'the task rows'],
  ['.tablewrap', 'the frame the wide table scrolls inside'],
  ['tr.norows', 'the filtered-to-nothing empty state'],
  ['.topbar', 'the app shell header'],
  ['.sectools', 'the sticky filter bar'],
  ['.sectools [data-clear]', 'the Clear-filters button'],
  ['#audit-q', 'the filter box'],
  ['#audit-expand', 'the expand-all button'],
  ['#audit-phase-status', 'the status chip row'],
  ['table.phases tbody tr.seghead', 'the segment header rows (D1)'],
  ['tr.seghead [data-segcsv]', 'the per-segment CSV export (D2)'],
];
const gone = [];
for (const [sel, what] of REQUIRED) if (!(await page.$(sel))) gone.push([sel, what]);
// The one element checked in the SOURCE, because its absence from the DOM is the
// assertion: the script's first statement removes it. Asking the live page
// whether it is there cannot tell "the script ran" from "no banner was ever
// written", and those are opposite readings of the same null.
if (!/id="audit-nojs"/.test(source)) gone.push(['#audit-nojs', 'the no-script banner, in the source']);
if (gone.length) {
  // The report's own stamp, so this names its basis rather than asserting age.
  // Deliberately NOT a table of which version added which element: that would be
  // a second place the renderer's history lives, and it would be wrong the first
  // time an element moved.
  const ver = await page.evaluate(() => {
    const s = document.querySelector('.stampv');
    return s ? s.textContent.trim() : '';
  });
  console.error(`cannot check ${file}: it was rendered before these checks existed.`);
  console.error('');
  for (const [sel, what] of gone) console.error(`  no ${sel}  --  ${what}`);
  console.error('');
  console.error(ver
    ? `The file names its renderer: ${ver}.`
    : 'The file names no renderer at all, so it predates the version stamp too.');
  console.error('Nothing here is inert -- the elements these checks drive are simply not in');
  console.error('this document. Render the manifest again and run this against the fresh file:');
  console.error('  python3 plugins/audit/scripts/report/render-report.py <manifest> --out-dir <dir> --format html');
  await browser.close();
  process.exit(2);
}

const load = await state();
if (load.total < 2) {
  console.error(`cannot check interactivity: only ${load.total} phase row(s); use a report with several`);
  await browser.close();
  process.exit(2);
}

// vw (F-P-4): the table renders in segments — active, pending, archived — and
// WHICH of them is on screen is a named View (active / archived / all), not a
// disclosure toggle a reader has to find. The old D1 pins asserted the toggle;
// they are replaced rather than kept, because the control they described is
// gone on purpose: a plan that opened looking half-empty, with the explanation
// hidden inside a button, is the report this replaced.
const seg0 = await page.evaluate(() => {
  const heads = [...document.querySelectorAll('table.phases tbody tr.seghead')]
    .map((h) => h.getAttribute('data-seg'));
  const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
  let cur = null, misfiled = 0;
  for (const r of document.querySelectorAll('table.phases tbody tr')) {
    if (r.classList.contains('seghead')) cur = r.getAttribute('data-seg');
    else if (r.classList.contains('phase')
             && r.getAttribute('data-seg') !== cur) misfiled++;
  }
  const sel = document.getElementById('audit-view');
  return {
    heads,
    misfiled,
    archived: rows.filter((r) => r.getAttribute('data-seg') === 'archived').length,
    view: sel ? sel.value : null,
    defaultView: document.querySelector('table.phases').getAttribute('data-defaultview'),
    options: sel ? [...sel.options].map((o) => o.value) : [],
    legacyToggle: !!document.getElementById('audit-arch'),
  };
});
const SEG_ORDER = ['active', 'pending', 'archived'];
expect('the segment headers come in active, pending, archived order',
  seg0.heads.join(','),
  SEG_ORDER.filter((s) => seg0.heads.includes(s)).join(','));
expect('every phase row sits under the seghead of its own segment', seg0.misfiled, 0);
expect('the toolbar offers the three named views', seg0.options.join(','),
  'active,archived,all');
expect('no archive toggle survives', seg0.legacyToggle, false);
expect('the select opens on the view the renderer chose', seg0.view, seg0.defaultView);
if (seg0.defaultView === 'active') {
  expect(`on load the archived phases are off screen (${seg0.archived} of them), `
    + 'and the rest are listed', load.phases, load.total - seg0.archived);
} else {
  expect('a plan with nothing active opens on all phases', load.phases, load.total);
}
expect('on load, tasks are collapsed', load.tasks, 0);

// Switching the view is an EXPANDER in the standing sense — it may not grow a
// sideways scroll box — and it must not lose the reader's place either.
{
  const preW = await page.evaluate(() => document.documentElement.scrollWidth);
  await page.selectOption('#audit-view', 'all');
  await page.waitForTimeout(250);
  const all = await page.evaluate(() => ({
    phases: [...document.querySelectorAll('table.phases tbody tr.phase')]
      .filter((r) => r.style.display !== 'none').length,
    dw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
    hash: location.hash,
  }));
  expect('choosing All lists every phase', all.phases, load.total);
  expect(`...growing no horizontal scroll box (scrollWidth ${preW} -> ${all.dw})`,
    all.dw <= Math.max(preW, all.cw + 1), true);
  if (seg0.defaultView === 'active') {
    expect('...and the view rides the shareable fragment', /[?&#!]v=all/.test(all.hash), true);
  }
}

// A search that matches rows the view is hiding SAYS SO. The old gate lifted
// itself silently during a filter, which made the control disagree with the
// table; the honest version keeps the gate and offers the way past it.
if (seg0.defaultView === 'active' && seg0.archived > 0) {
  await page.selectOption('#audit-view', 'active');
  await page.waitForTimeout(200);
  const archivedTerm = await page.evaluate(() => {
    const r = [...document.querySelectorAll('table.phases tbody tr.phase')]
      .find((x) => x.getAttribute('data-seg') === 'archived');
    return r ? (r.querySelector('.mono') || {}).textContent : null;
  });
  if (archivedTerm) {
    await page.fill('#audit-q', archivedTerm.trim());
    await page.waitForTimeout(350);
    const hidden = await page.evaluate(() => {
      const row = document.querySelector('[data-outside]');
      return {
        shown: !!row && !row.hidden && row.style.display !== 'none',
        text: row ? row.textContent.trim() : '',
        visible: [...document.querySelectorAll('table.phases tbody tr.phase')]
          .filter((r) => r.style.display !== 'none').length,
      };
    });
    expect(`searching "${archivedTerm.trim()}" from the Active view says its `
      + 'matches are elsewhere rather than reporting nothing', hidden.shown, true);
    expect('...and names how many', /\d+ phase/.test(hidden.text), true);
    await page.click('[data-viewall]');
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => ({
      view: document.getElementById('audit-view').value,
      visible: [...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((r) => r.style.display !== 'none').length,
    }));
    expect('...and the one press shows them', after.view, 'all');
    expect('...with the search still applied', after.visible > 0, true);
    await page.fill('#audit-q', '');
    await page.waitForTimeout(300);
  }
}

// The view and the filters survive a RELOAD — the failure a reader meets every
// time they refresh a report opened off disk, where History is refused and the
// fragment never gets written.
{
  await page.selectOption('#audit-view', 'archived');
  await page.waitForTimeout(250);
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(500);
  const back = await page.evaluate(() => ({
    view: (document.getElementById('audit-view') || {}).value,
    archivedOnly: [...document.querySelectorAll('table.phases tbody tr.phase')]
      .filter((r) => r.style.display !== 'none')
      .every((r) => r.getAttribute('data-seg') === 'archived'),
  }));
  expect('after a reload the report comes back in the view it was left in',
    back.view, 'archived');
  expect('...showing that view\'s rows and no others', back.archivedOnly, true);
  await page.selectOption('#audit-view', 'all');
  await page.waitForTimeout(250);
}

// ex (F-P-4): the per-task detail row. The compact row truncates the outcome at
// 70 characters — that truncation is what this row exists to undo — so the
// oracle is the TEXT: whatever the table shows must be a prefix of what the
// detail row shows, and longer for at least one task, or the row is decoration.
{
  await page.selectOption('#audit-view', 'all');
  await page.waitForTimeout(200);
  // Open every phase so task rows are reachable, the way a reader would.
  await page.click('#audit-expand');
  await page.waitForTimeout(300);
  const toggles = await page.$$('tr.task .dtoggle');
  expect('every task row carries a detail control', toggles.length > 0, true);
  if (toggles.length) {
    const before = await page.evaluate(() =>
      [...document.querySelectorAll('tr.taskdetail')].filter((r) => !r.hidden).length);
    expect('...and none of them is open at load', before, 0);
    const opened = await page.evaluate(() => {
      const b = document.querySelector('tr.task .dtoggle');
      b.click();
      const row = b.closest('tr.task');
      const d = row.nextElementSibling;
      const cellText = (row.querySelector('td.muted') || {}).textContent || '';
      return {
        isDetail: d.classList.contains('taskdetail'),
        visible: !d.hidden,
        aria: b.getAttribute('aria-expanded'),
        keys: [...d.querySelectorAll('.dt-k')].map((k) => k.textContent),
        groups: [...d.querySelectorAll('.dtcol h4')].map((h) => h.textContent),
        truncated: cellText.trim(),
        full: d.textContent,
      };
    });
    expect('opening one shows the row under its task', opened.isDetail && opened.visible, true);
    expect('...and the control says it is open', opened.aria, 'true');
    expect('...in two labelled groups', opened.groups.join(','), 'meta,task details');
    if (opened.truncated.endsWith('\u2026')) {
      const stem = opened.truncated.slice(0, -1).trim();
      expect('...carrying the outcome the table had to cut short, in full',
        opened.full.indexOf(stem) >= 0 && opened.full.length > opened.truncated.length,
        true);
    }
    // A detail row is a table row: it must obey the filter its task obeys.
    const q = await page.evaluate(() => {
      const open = [...document.querySelectorAll('tr.taskdetail')].find((r) => !r.hidden);
      return open ? open.getAttribute('data-detail') : null;
    });
    await page.fill('#audit-q', 'zzz-no-such-task-anywhere');
    await page.waitForTimeout(350);
    const hiddenWithTask = await page.evaluate(() =>
      [...document.querySelectorAll('tr.taskdetail')].filter((r) => !r.hidden).length);
    expect(`a filter that hides task ${q} hides its detail row with it`,
      hiddenWithTask, 0);
    await page.fill('#audit-q', '');
    await page.waitForTimeout(350);
    const backAgain = await page.evaluate(() =>
      [...document.querySelectorAll('tr.taskdetail')].filter((r) => !r.hidden).length);
    expect('...and clearing the filter brings it back still open', backAgain, 1);
    await page.evaluate(() => {
      const b = document.querySelector('tr.task .dtoggle[aria-expanded="true"]');
      if (b) b.click();
    });
    await page.waitForTimeout(150);
  }
  // Leave the table exactly as this block found it: collapsed, on the view the
  // checks below were written against. (The old archive block left itself open
  // for the same reason, stated the same way.)
  await page.click('#audit-expand');
  await page.waitForTimeout(300);
}

// sha (F-P-4): nine characters on screen, forty on the clipboard.
{
  const sha = await page.evaluate(() => {
    const b = document.querySelector('.shacopy');
    if (!b) return null;
    return { shown: (b.previousElementSibling || {}).textContent || '',
             copies: b.getAttribute('data-copy') || '' };
  });
  if (sha) {
    // The example's shas may already be short; what must hold is that the
    // clipboard carries the manifest's value and the cell carries its prefix.
    expect('the commit cell copies the sha the manifest recorded, whole',
      sha.copies.length >= sha.shown.replace(/\s/g, '').length
      && sha.copies.indexOf(sha.shown.replace(/\s/g, '')) === 0, true);
  } else notes.push('ok   (no task in this plan records a commit — sha copy skipped)');
}

// The no-script banner. It is rendered into the HTML and removed by the script's
// very first statement, so its ABSENCE is live proof that the script ran — and
// its presence is exactly what a reader sees in an IDE preview pane, which
// sandboxes inline <script> and was the real cause of one "the report is broken"
// report. Checking it here means the banner can never rot into a lie: if the
// removal breaks, the banner shows in a working browser and this goes red.
// This assertion is only worth making because the sweep above has already found
// the banner in the source; without that, a null here means either reading.
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
//
// How many DISTINCT statuses the plan has decides what this step can prove. With
// two or more, selecting one must leave the others behind, and that row count is
// the strongest evidence available that the filter really runs. With exactly one,
// every phase carries it, so selecting it correctly hides NOTHING — and the first
// version of this step read that as the report being inert. It printed
// `REPORT IS INERT` and exited 1 against a working report, on what is simply the
// normal end state of a plan: every phase done. Found by pointing the tool at
// this repo's own manifest, whose phases are all `done` and which therefore
// renders exactly one chip.
//
// So the count is asserted only where it can move, and the wiring is asserted
// either way — a chip that reports itself pressed and brings up the way back is a
// chip that ran the filter. Deliberately not a skip: "one status" is the case
// where a silently dead chip would be least likely to be noticed by hand.
const chips = await page.$$('#audit-phase-status .fchip');
const chipState = () => page.evaluate(() => ({
  pressed: document.querySelector('#audit-phase-status .fchip').getAttribute('aria-pressed'),
  clearOffered: !!document.querySelector('.sectools [data-clear]:not([hidden])'),
}));
if (chips.length) {
  await page.click('#audit-phase-status .fchip');
  await page.waitForTimeout(250);
  const chip = await state();
  const on = await chipState();
  if (chips.length > 1) {
    if (chip.phases === load.total) {
      failures.push(`FAIL a status chip filters the phase list: nothing changed, and this plan `
        + `has ${chips.length} statuses — one of them has to hide the rest`);
    } else notes.push(`ok   a status chip filters the phase list: ${chip.phases} of ${load.total}`);
  } else {
    expect('every phase in this plan shares one status, so its chip hides nothing '
      + '— and must not', chip.phases, load.total);
  }
  expect('a status chip reports itself as on', on.pressed, 'true');
  expect('...and a filter that is on offers the way back', on.clearOffered, true);
  expect('a status chip does not auto-expand either', chip.tasks, 0);
  await page.click('#audit-phase-status .fchip');   // release it
  await page.waitForTimeout(250);
  const off = await chipState();
  expect('releasing the chip restores every phase', (await state()).phases, load.total);
  expect('...and it stops reporting itself as on', off.pressed, 'false');
  expect('...and the way back goes away with it', off.clearOffered, false);
} else notes.push('ok   (no status chips in this report — skipped)');

// 6. The More-filters panel: model, and the empty state that offers a way back.
//    Skipped rather than failed on a plan that records no models — the panel is
//    emitted from the data, so its absence there is correct.
//
//    The two elements around the chip are NOT data-driven once the chip is here:
//    `_filter_panel` emits the <details>, the panel and the chips together, so a
//    document with one and not the others is inconsistent with itself rather than
//    merely old. That is a FAIL and not a sweep entry — but it is still named
//    rather than clicked, because clicking a selector that is not there buys a
//    30-second Playwright timeout and a stack, which reads as the report being
//    dead when it is the checker that could not find its footing.
const panelParts = [];
if (await page.$('#audit-model .fchip')) {
  for (const sel of ['.fdetails > summary', '.filterpanel']) {
    if (!(await page.$(sel))) panelParts.push(sel);
  }
}
if (panelParts.length) {
  failures.push(`FAIL the report emits model chips but no ${panelParts.join(' and ')} to hold them`);
} else if (await page.$('#audit-model .fchip')) {
  await page.click('.fdetails > summary');
  await page.waitForTimeout(80);
  await page.click('#audit-model .fchip');
  await page.waitForTimeout(250);
  const m = await state();
  if (m.phases < 1 || m.phases > load.total) {
    failures.push(`FAIL a model chip narrows the table: got ${m.phases} of ${load.total}`);
  } else notes.push(`ok   a model chip narrows the table: ${m.phases} of ${load.total}`);
  // Anchored on [!&] like the area checks below: /#!.*m=/ also matches the
  // `m=` inside a `from=` date fragment, so a report that lost the model key
  // but carried a date filter would pass this line with no m= param at all.
  if (!/[!&]m=/.test(await page.evaluate(() => location.hash))) {
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
  // vw: the fragment may still carry the VIEW (`v=all` — this file switched to
  // it above, and a view is not a filter). What must be gone is every filter
  // key; a leftover `q=` or `m=` is a link that reopens the state just cleared.
  expect('...and takes every filter key out of the URL with it',
    (await page.evaluate(() => location.hash))
      .replace(/^#!/, '').split('&').filter((p) => p && !/^v=/.test(p)).join('&'),
    '');
} else notes.push('ok   (this plan records no models — More filters skipped)');

// 6b. Author chips in the Usage section (C3). Emitted only when the ledger
//     records more than one author, so their absence is a fact about the FILE
//     (single author, no ledger, or rendered before the chips existed) — a
//     skip, not a failure, exactly like the model chips above. What they claim:
//     a chip narrows the per-author small multiples to exactly that author,
//     the state is a link (au=), and releasing the chip restores the top-8
//     default by re-applying `hidden` — none of which a string pin can see die.
if (await page.$('#audit-authors .fchip')) {
  const auBefore = await page.evaluate(() => {
    const cells = [...document.querySelectorAll('.smcell')];
    return {
      cells: cells.length,
      vis: cells.filter((c) => !c.hidden).length,
      top: document.querySelectorAll('.smcell[data-top]').length,
      chip: document.querySelector('#audit-authors .fchip').getAttribute('data-au'),
    };
  });
  await page.click('#audit-authors .fchip');
  await page.waitForTimeout(250);
  const auOn = await page.evaluate(() => {
    const vis = [...document.querySelectorAll('.smcell')].filter((c) => !c.hidden);
    const note = document.getElementById('audit-au-note');
    return {
      vis: vis.length,
      head: vis.length === 1 ? vis[0].querySelector('h4').textContent : null,
      note: note && !note.hidden ? note.textContent : '',
      hash: location.hash,
    };
  });
  if (auBefore.cells >= 2) {
    if (auOn.vis !== 1) {
      failures.push(`FAIL an author chip leaves exactly one .smcell visible: got ${auOn.vis} of ${auBefore.cells}`);
    } else if (auOn.head !== auBefore.chip) {
      failures.push(`FAIL the one visible cell is "${auOn.head}", the chip said "${auBefore.chip}"`);
    } else notes.push(`ok   author chip "${auBefore.chip}" leaves exactly one .smcell visible`);
  } else notes.push('ok   (fewer than two .smcell panels — the chip cannot narrow them; skipped that half)');
  expect('the author view is a link (au= in the hash)', /[!&]au=/.test(auOn.hash), true);
  if (!auOn.note.includes(auBefore.chip)) {
    failures.push(`FAIL the summary line names the selected author: got "${auOn.note}"`);
  } else notes.push(`ok   the summary line reads off the chip: "${auOn.note}"`);
  await page.click('#audit-authors .fchip');   // release it
  await page.waitForTimeout(250);
  const auOff = await page.evaluate(() => ({
    vis: [...document.querySelectorAll('.smcell')].filter((c) => !c.hidden).length,
    noteHidden: (document.getElementById('audit-au-note') || {}).hidden,
    hash: location.hash,
  }));
  // Absolute, against the renderer's own data-top marker — NOT against the
  // count measured at load. An earlier clearAll has already run applyAuthor
  // once by this point, so "same as before" would also pass a restore that
  // consistently hides everything; the marker is what "default" means.
  if (auBefore.cells && !auBefore.top) {
    failures.push(`FAIL ${auBefore.cells} smcell panels but none marked data-top — the default view would be empty`);
  }
  expect('releasing the chip restores the top-8 default (the data-top set)', auOff.vis, auBefore.top);
  expect('...and the summary line leaves with it', auOff.noteHidden, true);
  expect('...and the au fragment leaves the URL', /au=/.test(auOff.hash), false);
} else notes.push('ok   (no author chips — one author, no ledger, or a report older than them — skipped)');

// 6c. Area chips in the More-filters panel (D1). Emitted only when a phase
//     carries an `area` tag, so their absence is a fact about the FILE — a
//     skip, not a failure, exactly like the model chips above. What they claim:
//     the chip is a PHASE-level gate — a phase tagged with the selected area
//     stays, a phase with no tags is hidden while the selection is active —
//     the selection is a link (a=, a key distinct from the author's au=), and
//     Clear filters restores the hidden phases and takes a= out of the URL.
//     The a= regex anchors on [!&] on purpose: /a=/ alone also matches au=,
//     and would read the author fragment as this one.
const areaParts = [];
if (await page.$('#audit-areas .fchip')) {
  for (const sel of ['.fdetails > summary', '.filterpanel']) {
    if (!(await page.$(sel))) areaParts.push(sel);
  }
}
if (areaParts.length) {
  failures.push(`FAIL the report emits area chips but no ${areaParts.join(' and ')} to hold them`);
} else if (await page.$('#audit-areas .fchip')) {
  const areaTag = await page.evaluate(() =>
    document.querySelector('#audit-areas .fchip').getAttribute('data-a'));
  const areaBefore = await page.evaluate((tag) => {
    const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
    const tagsOf = (r) => (r.getAttribute('data-area') || '').split(/\s+/).filter(Boolean);
    return {
      tagged: rows.filter((r) => tagsOf(r).indexOf(tag) !== -1).length,
      untagged: rows.filter((r) => tagsOf(r).length === 0).length,
      total: rows.length,
    };
  }, areaTag);
  await page.click('.fdetails > summary');
  await page.waitForTimeout(80);
  await page.click('#audit-areas .fchip');
  await page.waitForTimeout(250);
  const areaOn = await page.evaluate((tag) => {
    const vis = (r) => r.style.display !== 'none';
    const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
    const tagsOf = (r) => (r.getAttribute('data-area') || '').split(/\s+/).filter(Boolean);
    return {
      taggedShown: rows.filter((r) => vis(r) && tagsOf(r).indexOf(tag) !== -1).length,
      untaggedShown: rows.filter((r) => vis(r) && tagsOf(r).length === 0).length,
      pressed: document.querySelector('#audit-areas .fchip').getAttribute('aria-pressed'),
      hash: location.hash,
    };
  }, areaTag);
  expect(`the "${areaTag}" area chip keeps every phase carrying that tag`,
    areaOn.taggedShown, areaBefore.tagged);
  if (areaBefore.untagged > 0) {
    expect(`...and hides all ${areaBefore.untagged} untagged phase(s) — no tags is no answer to an area`,
      areaOn.untaggedShown, 0);
  } else notes.push('ok   (every phase in this plan is tagged — the untagged half cannot be proven here)');
  expect('an area chip reports itself as on', areaOn.pressed, 'true');
  expect('the area view is a link (a= in the hash, apart from au=)',
    /[!&]a=/.test(areaOn.hash), true);
  // The TOOLBAR clear button, same reason as step 6: the open panel covers the
  // table's own copy.
  await page.click('.sectools [data-clear]');
  await page.waitForTimeout(250);
  const areaOff = await page.evaluate(() => ({
    phases: [...document.querySelectorAll('table.phases tbody tr.phase')]
      .filter((r) => r.style.display !== 'none').length,
    pressed: document.querySelector('#audit-areas .fchip').getAttribute('aria-pressed'),
    hash: location.hash,
  }));
  expect('Clear filters restores the hidden phases with everything else',
    areaOff.phases, areaBefore.total);
  expect('...and the chip stops reporting itself as on', areaOff.pressed, 'false');
  expect('...and a= leaves the URL', /[!&]a=/.test(areaOff.hash), false);
} else notes.push('ok   (no phase in this plan carries an area tag — area chips skipped)');

// 6d. The global filter row (C1/C2): a second line of the sticky top bar
//     carrying an authors dropdown, an area dropdown and the date range. Each
//     control is a twin of a filter that already exists elsewhere in the
//     document, so the gates here are PAIRINGS, not a version sweep: a report
//     that renders the panel's date pair but no global range, or author chips
//     but no authors dropdown, is missing half of one feature — that is a
//     FAIL, the same shape as the model-chips-without-a-panel case above.
if (await page.$('#audit-from') && !(await page.$('#audit-gfrom'))) {
  failures.push('FAIL the report renders the panel date pair but no global date range in the top bar');
}
if (await page.$('#audit-authors .fchip') && !(await page.$('#audit-au-select'))) {
  failures.push('FAIL the report renders author chips but no authors dropdown in the top bar');
}
if (await page.$('#audit-areas .fchip') && !(await page.$('#audit-area-select'))) {
  failures.push('FAIL the report renders area chips but no area dropdown in the top bar');
}
if (await page.$('#audit-gfrom')) {
  // Reachable while scrolled — the entire point of putting it in the sticky
  // bar. Asserted as BEHAVIOUR: scroll deep, then the control must still be
  // inside the viewport and usable from there.
  await page.evaluate(() => window.scrollTo(0, 1500));
  await page.waitForTimeout(300);
  const reach = await page.evaluate(() => {
    const el = document.getElementById('audit-gfrom');
    const b = el.getBoundingClientRect();
    return { top: Math.round(b.top), visible: b.top >= 0 && b.bottom <= window.innerHeight && b.width > 0 };
  });
  expect('scrolled 1500px down, the global date input is still on screen (sticky bar)',
    reach.visible, true);

  // A mid-span range, taken from the report's own data (payload if present,
  // else the panel's min/max), applied FROM the scrolled position.
  const range = await page.evaluate(() => {
    const U = window.AUDIT_USAGE;
    const gf = document.getElementById('audit-gfrom');
    const lo = (U && U.min) || gf.min, hi = (U && U.max) || gf.max;
    if (!lo || !hi) return null;
    const mid = new Date((Date.parse(lo + 'T00:00:00Z') + Date.parse(hi + 'T00:00:00Z')) / 2)
      .toISOString().slice(0, 10);
    return { lo, hi, mid, hasU: !!U };
  });
  if (!range) {
    failures.push('FAIL the global date inputs carry no min/max bounds from the data');
  } else {
    await page.fill('#audit-gfrom', range.lo);
    await page.fill('#audit-gto', range.mid);
    await page.waitForTimeout(300);
    const on = await page.evaluate(() => ({
      hash: location.hash,
      panelFrom: (document.getElementById('audit-from') || {}).value,
      panelTo: (document.getElementById('audit-to') || {}).value,
      gclear: !(document.getElementById('audit-gclear') || {}).hidden,
      count: (document.getElementById('audit-count') || {}).textContent || '',
    }));
    expect('the global range is a link (from= and to= in the hash)',
      /[!&]from=/.test(on.hash) && /[!&]to=/.test(on.hash), true);
    expect('the panel date pair mirrors the same range — two controls, one state',
      on.panelFrom === range.lo && on.panelTo === range.mid, true);
    expect('a live range offers the way back (the All time reset shows)',
      on.gclear, true);
    if (!/\d+ of \d+ tasks/.test(on.count)) {
      failures.push(`FAIL a date range narrows the task table and the count says so: got "${on.count}"`);
    } else notes.push(`ok   a date range narrows the task table: "${on.count}"`);

    // The usage views follow the same range (only on a report with the
    // per-day payload — without a ledger there is nothing to scope).
    if (range.hasU) {
      const usage = await page.evaluate(() => {
        const cols = [...document.querySelectorAll('.cols .col')];
        const dim = cols.filter((c) => /\bdimout\b/.test(c.getAttribute('class') || ''));
        const note = document.getElementById('audit-urange');
        const per = document.getElementById('audit-hm-period');
        return {
          cols: cols.length, dim: dim.length,
          dimOp: dim.length ? getComputedStyle(dim[0]).opacity : null,
          litOp: cols.length > dim.length
            ? getComputedStyle(cols.find((c) => !/\bdimout\b/.test(c.getAttribute('class') || ''))).opacity : null,
          note: note && !note.hidden ? note.textContent : '',
          period: per ? per.textContent : '',
        };
      });
      if (usage.cols && !(usage.dim > 0 && usage.dim < usage.cols)) {
        failures.push(`FAIL a mid-span range dims some trend columns and keeps others: ${usage.dim} of ${usage.cols} dimmed`);
      } else if (usage.cols) {
        notes.push(`ok   the trend recedes outside the range: ${usage.dim} of ${usage.cols} columns dimmed`);
        expect('...and dimming is real paint, not a class name (opacity < 1)',
          usage.dimOp !== null && parseFloat(usage.dimOp) < 1, true);
        expect('...while in-range columns stay at full opacity',
          usage.litOp === null || parseFloat(usage.litOp) === 1, true);
      }
      if (!usage.note.includes(range.lo) || !usage.note.includes(range.mid)) {
        failures.push(`FAIL the range line names the active span: got "${usage.note}"`);
      } else notes.push(`ok   the range line names the span: "${usage.note.slice(0, 72)}..."`);
      if (usage.period && !/Custom range/.test(usage.period)) {
        failures.push(`FAIL with a range active the heatmap period reads as the custom range: got "${usage.period}"`);
      } else if (usage.period) notes.push(`ok   the heatmap period names the custom range: "${usage.period}"`);

      // C1's print requirement: the active range is a LINE ON PAPER, not an
      // implication. The bar carrying the pickers never prints (asserted with
      // the other paper facts below); this line is what prints instead.
      await page.emulateMedia({ media: 'print' });
      await page.waitForTimeout(100);
      const paperRange = await page.evaluate(() => {
        const n = document.getElementById('audit-urange');
        const row = document.querySelector('.gfilters');
        return {
          shown: !!n && getComputedStyle(n).display !== 'none' && !n.hidden,
          text: n ? n.textContent : '',
          barGone: !row || row.offsetParent === null,
        };
      });
      await page.emulateMedia({ media: null });
      expect('the active range prints as a line naming it', paperRange.shown
        && paperRange.text.includes(range.lo) && paperRange.text.includes(range.mid), true);
      expect('...while the picker row itself never reaches paper', paperRange.barGone, true);
    } else notes.push('ok   (no usage payload — the range scopes only the task table here)');

    // Clearing returns to all-time: one press, every scoped view back. The
    // click is guarded on the button actually showing — its absence has
    // already failed the way-back assertion above, and clicking a hidden
    // element is a 30-second timeout, not a verdict.
    const gclearBtn = await page.$('#audit-gclear:not([hidden])');
    if (gclearBtn) await gclearBtn.click();
    else await page.evaluate(() => {   // fall back so later checks still run
      const gf = document.getElementById('audit-gfrom');
      const gt = document.getElementById('audit-gto');
      if (gf) gf.value = ''; if (gt) gt.value = '';
    });
    await page.waitForTimeout(300);
    const off = await page.evaluate(() => ({
      hash: location.hash,
      phases: [...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((r) => r.style.display !== 'none').length,
      dims: [...document.querySelectorAll('.cols .col')]
        .filter((c) => /\bdimout\b/.test(c.getAttribute('class') || '')).length,
      noteHidden: (document.getElementById('audit-urange') || { hidden: true }).hidden,
    }));
    expect('All time restores every phase', off.phases, load.total);
    expect('...takes from=/to= out of the URL', /[!&](from|to)=/.test(off.hash), false);
    expect('...undims every trend column', off.dims, 0);
    expect('...and the range line leaves with it', off.noteHidden, true);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
} else if (!(await page.$('#audit-from'))) {
  notes.push('ok   (this plan records no dates — global date range skipped)');
}

// The authors dropdown drives the same state as the chips.
if (await page.$('#audit-au-select')) {
  const who = await page.evaluate(() =>
    document.querySelector('#audit-au-select option[value]:not([value=""])').value);
  await page.selectOption('#audit-au-select', who);
  await page.waitForTimeout(250);
  const auOn = await page.evaluate(() => ({
    vis: [...document.querySelectorAll('.smcell')].filter((c) => !c.hidden).length,
    hash: location.hash,
    chipOn: (document.querySelector('#audit-authors .fchip.on') || {}).textContent || '',
  }));
  expect(`the authors dropdown narrows the per-author panels to one (picked ${who})`,
    auOn.vis, 1);
  expect('the dropdown selection is a link (au= in the hash)', /[!&]au=/.test(auOn.hash), true);
  if (await page.$('#audit-authors .fchip')) {
    expect('...and the author chips light the same selection', auOn.chipOn, who);
  }
  await page.selectOption('#audit-au-select', '');
  await page.waitForTimeout(250);
  const auOff = await page.evaluate(() => ({
    vis: [...document.querySelectorAll('.smcell')].filter((c) => !c.hidden).length,
    top: document.querySelectorAll('.smcell[data-top]').length,
    hash: location.hash,
  }));
  expect('All authors restores the top-8 default', auOff.vis, auOff.top);
  expect('...and au= leaves the URL', /[!&]au=/.test(auOff.hash), false);
}

// The area dropdown replaces the chip selection with one tag (or none).
if (await page.$('#audit-area-select')) {
  const pickTag = await page.evaluate(() =>
    document.querySelector('#audit-area-select option[value]:not([value=""])').value);
  await page.selectOption('#audit-area-select', pickTag);
  await page.waitForTimeout(250);
  const arOn = await page.evaluate((tag) => {
    const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
    const tagsOf = (r) => (r.getAttribute('data-area') || '').split(/\s+/).filter(Boolean);
    const shown = rows.filter((r) => r.style.display !== 'none');
    return {
      offTag: shown.filter((r) => !tagsOf(r).includes(tag)).length,
      shown: shown.length,
      hash: location.hash,
    };
  }, pickTag);
  expect(`the area dropdown keeps only "${pickTag}"-tagged phases (${arOn.shown} shown)`,
    arOn.offTag, 0);
  expect('the dropdown selection is a link (a= in the hash)', /[!&]a=/.test(arOn.hash), true);
  await page.selectOption('#audit-area-select', '');
  await page.waitForTimeout(250);
  expect('All areas restores every phase',
    (await state()).phases, load.total);
}

// The new chrome must not grow any scroll box (the assertHintsFit rule): the
// filter row lives in the sticky bar at every width, so at no width may the
// PAGE scroll sideways because of it. 390px is the width that found the last
// such defect (the filter panel).
for (const w of [1512, 390]) {
  await page.setViewportSize({ width: w, height: w > 700 ? 945 : 780 });
  await page.waitForTimeout(250);
  const grow = await page.evaluate(() => ({
    dw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
    row: !!document.querySelector('.gfilters'),
  }));
  if (grow.row) {
    expect(`at ${w}px the global filter row does not push the page sideways `
      + `(scrollWidth ${grow.dw} vs client ${grow.cw})`, grow.dw <= grow.cw + 1, true);
  }
}
await page.setViewportSize({ width: 1512, height: 945 });
await page.waitForTimeout(200);

// 6e. Heatmap calendar navigation (C3). Same pairing gate: a report that draws
//     the heatmap but renders no navigation for it is missing half of one
//     feature. The nav itself only functions with the per-day payload.
if (await page.$('.hm') && !(await page.$('#audit-hm-gran'))) {
  failures.push('FAIL the report draws the tokens heatmap but no calendar navigation for it');
} else if (await page.$('#audit-hm-gran') && await page.evaluate(() => !!window.AUDIT_USAGE)) {
  const hmDays = await page.evaluate(() => Object.keys(window.AUDIT_USAGE.days).sort());
  const hm0 = await page.evaluate(() => ({
    period: document.getElementById('audit-hm-period').textContent,
    rows: document.querySelectorAll('#audit-hm-body tr').length,
    prevOff: (document.getElementById('audit-hm-prev') || {}).disabled,
    nextOff: (document.getElementById('audit-hm-next') || {}).disabled,
  }));
  expect('at rest the heatmap NAMES its period: all data with the span',
    hm0.period.includes('All data') && hm0.period.includes(hmDays[0])
    && hm0.period.includes(hmDays[hmDays.length - 1]), true);
  expect('...with both arrows disabled (nothing to step through at all-data)',
    hm0.prevOff === true && hm0.nextOff === true, true);
  expect('...and the grid is proportional to the other charts, not a thumbnail: '
    + 'it fills the column like the trend does', await page.evaluate(() => {
      const hm = document.querySelector('.hm');
      const cols = document.querySelector('.cols');
      if (!hm) return false;
      const hw = hm.getBoundingClientRect().width;
      const cw = cols ? cols.getBoundingClientRect().width
        : hm.closest('.hmwrap').getBoundingClientRect().width;
      return hw >= cw * 0.9;
    }), true);

  // The heatmap lives inside the Detail disclosure; a reader opens it to
  // reach the nav, and so does this. Driven like the reader would, via the
  // summary, not by poking the open property.
  const moreOpen = await page.evaluate(() => !!document.querySelector('details.more[open]'));
  if (!moreOpen) {
    await page.click('details.more > summary');
    await page.waitForTimeout(150);
  }
  await page.evaluate(() => document.getElementById('audit-hm-gran')
    .scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(200);
  await page.click('#audit-hm-gran [data-g="day"]');
  await page.waitForTimeout(250);
  const lastDay = hmDays[hmDays.length - 1];
  const day1 = await page.evaluate(() => ({
    period: document.getElementById('audit-hm-period').textContent,
    rows: document.querySelectorAll('#audit-hm-body tr').length,
    prevOff: (document.getElementById('audit-hm-prev') || {}).disabled,
    nextOff: (document.getElementById('audit-hm-next') || {}).disabled,
    nextMuted: parseFloat(getComputedStyle(document.getElementById('audit-hm-next')).opacity),
  }));
  expect('Day granularity draws exactly one row', day1.rows, 1);
  expect(`...opens on the LAST recorded day and names it (${lastDay})`,
    day1.period.includes(lastDay), true);
  expect('...the next arrow is disabled at the data edge', day1.nextOff, true);
  expect('...and visibly muted, not just inert', day1.nextMuted < 1, true);
  if (hmDays.length > 1) {
    expect('...while prev can still step back', day1.prevOff, false);
    // Clicked only when enabled: a broken page that leaves it disabled has
    // already failed the line above, and clicking it anyway buys a 30-second
    // Playwright timeout that reads as the CHECKER dying (the rule this file
    // opens with).
    if (!day1.prevOff) {
      await page.click('#audit-hm-prev');
      await page.waitForTimeout(250);
      const prevDay = hmDays[hmDays.length - 2];
      const day2 = await page.evaluate(() => ({
        period: document.getElementById('audit-hm-period').textContent,
        nextOff: (document.getElementById('audit-hm-next') || {}).disabled,
      }));
      expect(`prev steps to the previous day WITH data (${prevDay}), skipping any gap`,
        day2.period.includes(prevDay), true);
      expect('...and next re-enables away from the edge', day2.nextOff, false);
    }
  }

  // Tooltips survive the re-render: the styled hover layer must speak for
  // JS-built cells exactly as it does for server-rendered ones.
  await page.hover('#audit-hm-body tr:first-child td:nth-child(10) i');
  await page.waitForTimeout(200);
  const tip = await page.evaluate(() => {
    const b = document.querySelector('.rtip');
    return { shown: !!b && !b.hidden, text: b ? b.textContent : '' };
  });
  if (!tip.shown || !/tokens|outside/.test(tip.text)) {
    failures.push(`FAIL hovering a re-rendered heatmap cell still shows the tooltip: shown=${tip.shown}, text="${tip.text}"`);
  } else notes.push(`ok   the tooltip layer survives a heatmap re-render: "${tip.text}"`);

  await page.click('#audit-hm-gran [data-g="week"]');
  await page.waitForTimeout(250);
  expect('Week granularity draws the seven days of one week',
    await page.evaluate(() => document.querySelectorAll('#audit-hm-body tr').length), 7);
  await page.click('#audit-hm-gran [data-g="month"]');
  await page.waitForTimeout(250);
  const mon = await page.evaluate(() => ({
    period: document.getElementById('audit-hm-period').textContent,
    rows: document.querySelectorAll('#audit-hm-body tr').length,
  }));
  const monName = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'][+lastDay.slice(5, 7) - 1];
  expect(`Month granularity names the month (${monName} ${lastDay.slice(0, 4)})`,
    mon.period.includes(monName) && mon.period.includes(lastDay.slice(0, 4)), true);
  expect('...aggregated back to weekday rows', mon.rows, 7);
  await page.click('#audit-hm-gran [data-g="year"]');
  await page.waitForTimeout(250);
  expect('Year granularity names the year',
    await page.evaluate(() => document.getElementById('audit-hm-period').textContent),
    lastDay.slice(0, 4));

  // None of that navigation may widen the page (its wrap owns any overflow).
  const hmGrow = await page.evaluate(() => ({
    dw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  }));
  expect(`heatmap navigation grew no page scroll box (scrollWidth ${hmGrow.dw})`,
    hmGrow.dw <= hmGrow.cw + 1, true);

  await page.click('#audit-hm-gran [data-g="all"]');
  await page.waitForTimeout(250);
  expect('back at All the period names all data again',
    await page.evaluate(() => /All data/.test(
      document.getElementById('audit-hm-period').textContent)), true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
} else if (await page.$('#audit-hm-gran')) {
  notes.push('ok   (heatmap nav present but no payload — nothing to navigate)');
} else notes.push('ok   (no heatmap in this report — calendar navigation skipped)');

// 6f. Ready now as a definition list (C4). The pairing gate: a report whose
//     nav still links a #ready section must render it as the list.
if (await page.$('#ready') && !(await page.$('dl.ready'))) {
  failures.push('FAIL the report has a Ready now section but no definition list in it');
} else if (await page.$('dl.ready')) {
  const ready = await page.evaluate(() => {
    const dl = document.querySelector('dl.ready');
    const dts = [...dl.querySelectorAll('dt')];
    const dds = [...dl.querySelectorAll('dd')];
    const navN = document.querySelector('.snav a[href="#ready"] .n');
    // Cross-check every term against the phase its own definition names: a
    // tagged phase's task must wear the same tags in the list.
    let tagChecked = 0, tagWrong = 0;
    dts.forEach((dt, i) => {
      const dd = dds[i];
      const m = dd && dd.textContent.match(/In (\S+)/);
      if (!m) return;
      const ph = document.getElementById('phase-' + m[1]);
      if (!ph) return;
      const tags = (ph.getAttribute('data-area') || '').split(/\s+/).filter(Boolean);
      if (!tags.length) return;
      tagChecked++;
      // The tag's IDENTITY is its first text node; D4 may append an advisory
      // owner suffix (.aown) inside the same chip, which is part of the chip
      // but not part of the tag name being compared here.
      const worn = [...dt.querySelectorAll('.area-tag')]
        .map((t) => (t.firstChild ? t.firstChild.textContent : '').trim());
      if (!tags.every((t) => worn.includes(t))) tagWrong++;
    });
    return {
      dts: dts.length, dds: dds.length,
      navN: navN ? +navN.textContent : null,
      ids: dts.every((d) => !!d.querySelector('code')),
      whys: dds.every((d) => d.textContent.trim().length > 0),
      tagChecked, tagWrong,
    };
  });
  expect('every ready task is a term with a definition', ready.dts === ready.dds
    && ready.dts > 0, true);
  if (ready.navN !== null) {
    expect(`the list carries as many terms as the nav count (${ready.navN})`,
      ready.dts, ready.navN);
  }
  expect('every term names its task id', ready.ids, true);
  expect('every definition says why the task is ready', ready.whys, true);
  if (ready.tagChecked) {
    expect(`tasks of tagged phases wear the area chips (${ready.tagChecked} checked)`,
      ready.tagWrong, 0);
  } else notes.push('ok   (no ready task sits in a tagged phase — chip cross-check skipped)');
} else notes.push('ok   (nothing is ready in this plan — Ready now skipped)');

// 6g. Per-segment exports (D2): CSV of the data, PNG of the charts, print
//     scoped to one segment. The downloads are read back off disk and checked
//     against the document's own counts — a button that downloads the wrong
//     rows, or an empty PNG, is indistinguishable from a working one in any
//     string pin. The segment CSV exports the segment's DATA (every row of
//     the segment), never the filtered view, so the oracle is the row count
//     of that segment, not what happens to be visible.
{
  const segBtn = await page.$('tr.seghead [data-segcsv]');
  const segName = await segBtn.getAttribute('data-segcsv');
  const segOracle = await page.evaluate((s) => {
    const phases = [...document.querySelectorAll(
      `table.phases tbody tr.phase[data-seg="${s}"]`)];
    const tasks = [...document.querySelectorAll(
      `table.phases tbody tr.task[data-seg="${s}"]`)];
    const taskless = phases.filter((p) => !tasks.some((t) =>
      t.getAttribute('data-phase') === p.getAttribute('data-phase'))).length;
    return { rows: tasks.length + taskless };
  }, segName);
  try {
    const wait = page.waitForEvent('download', { timeout: 15000 });
    await segBtn.click();
    const dl = await wait;
    const text = readFileSync(await dl.path(), 'utf8');
    const lines = text.replace(/^\uFEFF/, '').trim().split('\r\n');
    if (!/^phase,phase title,phase status,task,task title,task status/.test(lines[0])) {
      failures.push(`FAIL the segment CSV header names its columns: got "${lines[0]}"`);
    } else notes.push('ok   the segment CSV header names its columns');
    expect(`the "${segName}" segment CSV carries one row per task (plus taskless phases)`,
      lines.length - 1, segOracle.rows);
    expect('...and the filename names the segment',
      dl.suggestedFilename().includes(`-phases-${segName}.csv`), true);
    // csv (F-P-4): the file carries the DATA. Three columns are lossy on
    // screen — the commit is cut to nine characters and wears a Copy control,
    // the done cell is cut to the minute, the outcome is cut at seventy — and
    // the export used to take the cell text, Copy included.
    const head = csvFields(lines[0]);
    const iCommit = head.indexOf('commit');
    const iDone = head.indexOf('done');
    const iOut = head.indexOf('outcome');
    const body = lines.slice(1);
    // Every data row must carry as many fields as the header names — an
    // appended column with no value pushed into the row is how a CSV silently
    // shifts every later column by one. Quoted rows used to be skipped here
    // rather than parsed, which meant the rows most likely to shift a column
    // were the only ones exempt from the check.
    expect('every CSV row has as many fields as the header names',
      body.every((l) => csvFields(l).length === head.length), true);
    expect('the CSV never exports a control as if it were data',
      body.some((l) => /,?"?[^,]*Copy[^,]*"?,/.test(l)), false);
    if (iCommit >= 0) {
      const shas = body.map((l) => (csvFields(l)[iCommit] || '')).filter(Boolean);
      // The oracle is THIS segment's shas: the file is one segment, and the
      // document holds them all.
      const shown = await page.evaluate((sg) =>
        [...document.querySelectorAll(`tr.task[data-seg="${sg}"] .shacopy`)]
          .map((b) => b.getAttribute('data-copy')), segName);
      expect(`every exported commit is the manifest's own sha, and a task `
        + `without one exports nothing rather than an em dash `
        + `(${shas.length} of ${body.length} rows carry one)`,
        shas.length === shown.length && shas.every((x) => shown.indexOf(x) >= 0),
        true);
    }
    if (iDone >= 0) {
      const stamps = body.map((l) => (csvFields(l)[iDone] || '')).filter(Boolean);
      expect('every exported completion is the full ISO stamp, not the minute '
        + 'the cell shows',
        stamps.every((x) => /T/.test(x)), true);
    }
    expect('...and the file carries every column the compact row leaves out',
      head.includes('started') && head.includes('model')
      && head.includes('outcome') && head.includes('technical outcome')
      && head.includes('work item') && head.includes('owner')
      && head.includes('waits on'), true);
  } catch (e) {
    failures.push(`FAIL the segment CSV button produced no download (${String(e).split('\n')[0]})`);
  }

  // Bugs CSV — paired with the table it exports.
  const bugsTable = await page.$('table.bugs');
  const bugsBtn = await page.$('[data-csv="bugs"]');
  if (bugsTable && !bugsBtn) {
    failures.push('FAIL the report has a bugs table but no CSV control for it');
  } else if (bugsBtn) {
    try {
      const wait = page.waitForEvent('download', { timeout: 15000 });
      await bugsBtn.click();
      const dl = await wait;
      const lines = readFileSync(await dl.path(), 'utf8')
        .replace(/^\uFEFF/, '').trim().split('\r\n');
      const want = await page.evaluate(() =>
        document.querySelectorAll('table.bugs tbody tr').length);
      expect('the bugs CSV carries one row per bug', lines.length - 1, want);
    } catch (e) {
      failures.push(`FAIL the bugs CSV produced no download (${String(e).split('\n')[0]})`);
    }
  } else notes.push('ok   (no bugs table in this plan — bugs CSV skipped)');

  // Usage daily CSV + the chart PNGs — paired with the payload they read.
  const hasU = await page.evaluate(() => !!window.AUDIT_USAGE);
  const usageBtn = await page.$('[data-csv="usage"]');
  if (hasU && !usageBtn) {
    failures.push('FAIL the report embeds the usage payload but offers no daily CSV');
  } else if (usageBtn) {
    try {
      const wait = page.waitForEvent('download', { timeout: 15000 });
      await usageBtn.click();
      const dl = await wait;
      const lines = readFileSync(await dl.path(), 'utf8')
        .replace(/^\uFEFF/, '').trim().split('\r\n');
      const want = await page.evaluate(() =>
        Object.keys(window.AUDIT_USAGE.days).length);
      expect('the usage CSV carries one row per recorded day', lines.length - 1, want);
      // Raw numbers, checked structurally rather than by the panel's substring
      // regex — which read a legitimate 3-digit token count after the date
      // ("…-10,167,…") as a thousands separator. No field in this CSV is ever
      // quoted (dates and numbers only), so a separator would ADD a field.
      const nf = lines[0].split(',').length;
      const bad = lines.slice(1).filter((l) => l.split(',').length !== nf
        || !l.split(',').slice(1).every((v) => /^\d+(\.\d+)?$/.test(v)));
      if (bad.length) {
        failures.push(`FAIL the usage CSV ships non-raw numbers or ragged rows: `
          + `"${bad[0]}"`);
      } else notes.push('ok   the usage CSV ships raw numbers');
    } catch (e) {
      failures.push(`FAIL the usage CSV produced no download (${String(e).split('\n')[0]})`);
    }
  }
  const pngIsReal = (buf) => buf.length > 2000
    && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47;
  for (const kind of ['trend', 'heatmap']) {
    const btn = await page.$(`[data-png="${kind}"]`);
    if (hasU && !btn && kind === 'trend') {
      failures.push('FAIL the report embeds the usage payload but offers no trend PNG');
      continue;
    }
    if (!btn) { notes.push(`ok   (no ${kind} PNG control in this report — skipped)`); continue; }
    try {
      const wait = page.waitForEvent('download', { timeout: 15000 });
      await btn.click();
      const dl = await wait;
      const buf = readFileSync(await dl.path());
      expect(`the ${kind} PNG is a real image, redrawn from the data `
        + `(${buf.length} bytes)`, pngIsReal(buf), true);
    } catch (e) {
      failures.push(`FAIL the ${kind} PNG produced no download (${String(e).split('\n')[0]})`);
    }
  }

  // Print one segment: the button stamps body[data-printseg], the print sheet
  // shows only that segment, and afterprint restores the page. window.print
  // is stubbed — a real dialog would hang a headless run — and afterprint is
  // dispatched by hand, which is the same event a closed dialog fires.
  const pBtn = await page.$(`tr.seghead [data-segprint="${segName}"]`);
  if (!pBtn) {
    failures.push(`FAIL the "${segName}" seghead carries a CSV control but no Print control`);
  } else {
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => { window.__printed++; };
    });
    const preW = await page.evaluate(() => document.documentElement.scrollWidth);
    await pBtn.click();
    await page.waitForTimeout(150);
    const stamped = await page.evaluate(() => ({
      seg: document.body.getAttribute('data-printseg'),
      printed: window.__printed,
    }));
    expect('the Print button stamps the segment on the body', stamped.seg, segName);
    expect('...and opens the print dialog', stamped.printed, 1);
    await page.emulateMedia({ media: 'print' });
    await page.waitForTimeout(150);
    const isolated = await page.evaluate((s) => {
      const vis = (el) => el && getComputedStyle(el).display !== 'none';
      const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
      return {
        shown: rows.filter(vis).length,
        inSeg: rows.filter((r) => vis(r) && r.getAttribute('data-seg') === s).length,
        wantSeg: rows.filter((r) => r.getAttribute('data-seg') === s).length,
        usageGone: !vis(document.getElementById('usage')),
        otherHeads: [...document.querySelectorAll('tr.seghead')]
          .filter((h) => vis(h) && h.getAttribute('data-seg') !== s).length,
      };
    }, segName);
    await page.emulateMedia({ media: null });
    expect(`one segment on paper: every "${segName}" phase prints`,
      isolated.inSeg, isolated.wantSeg);
    expect('...and nothing from the other segments does',
      isolated.shown, isolated.inSeg);
    expect('...their headers included', isolated.otherHeads, 0);
    expect('...and the other sections stay off the sheet', isolated.usageGone, true);
    await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
    await page.waitForTimeout(100);
    const after = await page.evaluate(() => ({
      seg: document.body.getAttribute('data-printseg'),
      dw: document.documentElement.scrollWidth,
      cw: document.documentElement.clientWidth,
    }));
    expect('afterprint takes the stamp back off', after.seg, null);
    expect(`...and the whole round trip grew no scroll box (scrollWidth ${preW} -> ${after.dw})`,
      after.dw <= Math.max(preW, after.cw + 1), true);
  }
}

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

// 8. Back to a clean document for the polish checks below — the print block above
//    deliberately leaves it filtered down to nothing.
const clearAll = async () => {
  const btn = await page.$('.sectools [data-clear]:not([hidden])');
  if (btn) await btn.click();
  await page.click('#audit-q');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
};
await clearAll();

// A revealed row settles VISIBLE. This is the one assertion the fade genuinely
// needs, and it is here rather than in a string pin because the failure it guards
// is silent and total: this stylesheet has already pinned two blocks at opacity 0
// forever, when `fadeUp`'s easing token stopped resolving. `@starting-style` has
// the same shape of accident available to it — one brace out of place and
// `opacity:0` stops being a starting value and becomes the row's actual style, so
// every expanded task is invisible while the row counts, the match badges and
// every string pin in the suite stay exactly as green as they are now.
await page.click('#audit-expand');
await page.waitForTimeout(400);        // > --dur (.22s), so the fade has finished
const revealed = await page.evaluate(() => {
  const rows = [...document.querySelectorAll('tr.task')].filter((r) => r.offsetParent !== null);
  return { n: rows.length, faded: rows.filter((r) => +getComputedStyle(r).opacity < 1).length };
});
if (revealed.n === 0) failures.push('FAIL expand-all revealed no task rows to check for visibility');
else expect(`every one of the ${revealed.n} revealed task rows is actually visible`, revealed.faded, 0);

// ...and the reveal is screen-only. A transition caught mid-run by the print
// snapshot puts a half-faded row on paper, and paper has no second frame.
await page.emulateMedia({ media: 'print' });
await page.waitForTimeout(100);
const printedRow = await page.evaluate(() => {
  const r = document.querySelector('tr.task');
  const cs = getComputedStyle(r);
  return { transition: cs.transitionProperty, opacity: +cs.opacity };
});
await page.emulateMedia({ media: null });
expect('paper does not inherit the row-reveal transition', /opacity/.test(printedRow.transition), false);
expect('...and prints the row at full opacity', printedRow.opacity, 1);
await page.click('#audit-expand');
await page.waitForTimeout(150);

// The filter bar says when it is stuck. No CSS selector reports that, so it is a
// class toggled from the scroll listener — which means it can silently stop
// toggling with the rule it drives still sitting in the stylesheet, correct and
// unreachable. Checked as elevation rather than as a class name: what the reader
// gets is the shadow.
const shadowAt = async (y) => {
  await page.evaluate((to) => window.scrollTo(0, to), y);
  await page.waitForTimeout(400);      // > --dur, so the box-shadow transition has settled
  return page.evaluate(() => {
    const st = document.querySelector('.sectools');
    const r = st.getBoundingClientRect();
    return { shadow: getComputedStyle(st).boxShadow !== 'none', top: Math.round(r.top),
             stickAt: Math.round(parseFloat(getComputedStyle(st).top) || 0) };
  });
};
const atRest = await shadowAt(0);
expect('at rest the filter bar sits in the flow and casts no shadow', atRest.shadow, false);
const barY = await page.evaluate(() => window.scrollY + document.querySelector('.sectools').getBoundingClientRect().top);
const pinned = await shadowAt(barY + 400);
expect(`stuck against the top bar it reads as a layer over the rows it filters `
  + `(top ${pinned.top}, sticks at ${pinned.stickAt})`, pinned.shadow, true);
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(400);

// 9. A phone. The More-filters panel is hung out of flow at `min-width:32rem`, and
//    min-width BEATS max-width — so the `max-width:calc(100vw - 2rem)` written to
//    cap it to the viewport capped nothing. Measured at 390px before the fix: a
//    512px panel spanning x=-353 to x=159, with both date inputs at -225..-100,
//    entirely off the left of the screen. document.scrollWidth stayed 390, so
//    there was no scroll that reached them either: the date filter simply did not
//    exist on a phone. Every string pin in the suite was green throughout.
await page.setViewportSize({ width: 390, height: 780 });
await page.waitForTimeout(250);
//    Same pairing as step 6: the <details> without the panel inside it is a
//    contradiction in one document, so it is named rather than dereferenced.
if (await page.$('.fdetails > summary') && !(await page.$('.filterpanel'))) {
  failures.push('FAIL the report emits a More-filters <details> with no .filterpanel inside it');
} else if (await page.$('.fdetails > summary')) {
  await page.click('.fdetails > summary');
  await page.waitForTimeout(250);
  const phone = await page.evaluate(() => {
    const panel = document.querySelector('.filterpanel');
    const els = [panel, ...panel.querySelectorAll('input,button')];
    const name = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '');
    return {
      controls: els.length,
      offscreen: els.filter((el) => {
        const b = el.getBoundingClientRect();
        return b.left < -1 || b.right > window.innerWidth + 1;
      }).map(name),
      pageOverflows: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
  expect(`all ${phone.controls} controls of the open filter panel are on screen`,
    phone.offscreen.join(',') || 'none', 'none');
  expect('...without pushing the document sideways to get there', phone.pageOverflows, false);

  //    In flow the panel's height IS the bar's height, and the bar is sticky: 156px
  //    shut, 481px open, on a 780px screen. Pinned, that is 62% of the viewport
  //    covering the table it filters. Open, it has to scroll away like the block of
  //    controls it now is.
  const covered = await page.evaluate(async () => {
    const st = document.querySelector('.sectools');
    window.scrollTo(0, window.scrollY + st.getBoundingClientRect().top + 500);
    await new Promise((r) => setTimeout(r, 300));
    const b = st.getBoundingClientRect();
    const vis = Math.max(0, Math.min(b.bottom, window.innerHeight) - Math.max(b.top, 0));
    return Math.round((vis / window.innerHeight) * 100);
  });
  if (covered > 40) {
    failures.push(`FAIL an open filter panel does not pin itself over the table: ${covered}% of the screen is filter bar`);
  } else notes.push(`ok   scrolled, the open filter panel gives the table the screen back (${covered}% bar)`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
} else notes.push('ok   (this plan records no models or dates — phone panel check skipped)');

//    Portrait paper is ~688px, INSIDE the 52rem breakpoint — so every rule added
//    for a phone above is also a rule about paper. These two are inert there only
//    because the whole bar is dropped from the printed page; if that ever stops
//    being true, a filter panel prints in the middle of the plan.
await page.setViewportSize({ width: 688, height: 900 });
await page.emulateMedia({ media: 'print' });
await page.waitForTimeout(150);
const onPaper = await page.evaluate(() => {
  const st = document.querySelector('.sectools');
  const fp = document.querySelector('.filterpanel');
  const gone = (el) => !el || getComputedStyle(el).display === 'none' || el.offsetParent === null;
  return { bar: gone(st), panel: gone(fp) };
});
await page.emulateMedia({ media: null });
await page.setViewportSize({ width: 1512, height: 945 });
expect('the filter bar never reaches portrait paper, where its phone rules also apply', onPaper.bar, true);
expect('...nor the panel inside it', onPaper.panel, true);

// 10. The responsive contract, at every width either side of a breakpoint
//     report.css or panel.css declares. What existed before this was two
//     widths — 390 and 688 — and only `.gfilters` and `.filterpanel` at them:
//     no whole-document assertion at any width, and nothing at all between 390
//     and 688 or between 688 and 1200. The ladder and the four things measured
//     at each rung live in tools/capture-screenshots.mjs, imported above, so
//     the panel is asked the same question at the same widths.
//
//     Driven against the RESTING layout, deliberately. Everything above has
//     been opening panels, typing filters and expanding rows, and a layout
//     measured with a disclosure hanging open is a measurement of that
//     disclosure. Deliberately layered UI — an open <details>, a dialog, the
//     tooltip, a combo menu — is out of scope here and checked where it is
//     opened; so is @media print, which section 7 owns; so is vertical extent,
//     because a report is allowed to be tall.
{
  const clear = await page.$('.sectools [data-clear]:not([hidden])');
  if (clear) await clear.click();
  await page.click('#audit-q');
  await page.keyboard.press('Escape');
  //     The two disclosures are treated differently ON PURPOSE. `.fdetails` is
  //     a popover — absolutely positioned, hung off its control — so it is a
  //     layer, and a layer over the table is what a layer is for; it is closed.
  //     `details.more` is IN FLOW: opening it does not cover anything, it makes
  //     the document longer, and the heatmap, the small multiples and the
  //     ranked lists are only laid out at all when it is open. It is opened, so
  //     the ladder measures them rather than measuring their absence.
  await page.evaluate(() => {
    const d = document.querySelector('.fdetails');
    if (d) d.open = false;
    const m = document.querySelector('details.more');
    if (m) m.open = true;
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(300);
  const openRows = await page.evaluate(() =>
    [...document.querySelectorAll('tr.task')].filter((r) => r.offsetParent !== null).length);
  if (openRows) {
    await page.click('#audit-expand');
    await page.waitForTimeout(250);
  }
  const tally = newLadderTally();
  await walkResponsiveLadder(page, 'report', tally, {
    report: (m) => failures.push(`FAIL ${m}`),
    ok: (m) => notes.push(`ok   ${m}`),
  });
  assertLadderMeasuredSomething('report', tally, {
    report: (m) => failures.push(`FAIL ${m}`),
    ok: (m) => notes.push(`ok   ${m}`),
  });
  if (tally.widths !== RESPONSIVE_LADDER.length) {
    failures.push(`FAIL the ladder visited ${tally.widths} of `
      + `${RESPONSIVE_LADDER.length} widths — it did not finish`);
  }
  await page.setViewportSize({ width: 1512, height: 945 });
  await page.waitForTimeout(200);
}

if (pageErrors.length) failures.push(`FAIL the page raised ${pageErrors.length} error(s): ${pageErrors.slice(0, 3).join(' | ')}`);
else notes.push('ok   no page errors');

// The coverage verdict. Runs last, and deliberately AFTER the page-error check,
// so a run that both crashed and skipped reports both rather than the first.
{
  const src = readFileSync(new URL(import.meta.url), 'utf8').split('\n');
  const declared = [];
  src.forEach((line, i) => {
    const t = line.trim();
    // Prose about expect() is not a call site. The first version of this counted
    // its own comments and the machinery below, and reported five phantom
    // "never ran" sites on a clean report -- a coverage check that fails on
    // itself teaches everyone to ignore it.
    if (t.startsWith('//') || t.startsWith('*')) return;
    if (/function expect/.test(line)) return;
    // A real call always opens with a LITERAL label, which is also what makes
    // the site identifiable. A call whose label were a variable would be missed
    // -- under-counting, the quiet direction; there is none today, and this
    // comment is the record if one appears.
    const m = line.match(/(?<![A-Za-z_.])expect\(\s*(['"`])([^'"`$]*)/);
    if (!m) return;
    declared.push({ line: i + 1, label: m[2].trim() });
  });
  const missed = declared.filter((d) => !EXPECT_SITES.has(d.line));
  const said = notes.concat(failures).join('\n');

  // The exemption table must describe THIS file, or it is a list of excuses for
  // checks that no longer exist.
  for (const c of CONDITIONAL_EXPECTS) {
    if (!declared.some((d) => d.label && c.label.startsWith(d.label))) {
      failures.push(`FAIL the conditional-expect table names "${c.label}", which no `
        + `expect() call site declares any more — the exemption outlived its check`);
    }
  }
  const unexplained = missed.filter((d) => !d.label
    || !CONDITIONAL_EXPECTS.some((c) => c.label.startsWith(d.label)));
  if (unexplained.length) {
    failures.push(`FAIL ${unexplained.length} of ${declared.length} expect() call site(s) `
      + `never ran, so this report was graded on work that did not happen: `
      + unexplained.map((d) => `line ${d.line} ${JSON.stringify(d.label.slice(0, 48))}`)
        .join(' · '));
  }
  // A pair whose BOTH halves went silent is a skipped leg wearing an exemption.
  for (const c of CONDITIONAL_EXPECTS) {
    const skipped = missed.some((d) => d.label && c.label.startsWith(d.label));
    if (skipped && said.indexOf(c.instead) < 0) {
      failures.push(`FAIL "${c.label}" was skipped and so was its counterpart `
        + `"${c.instead}" — the exemption says one of the two always runs, and `
        + `neither did, which is a skipped leg rather than a branch not taken`);
    }
  }
  if (!unexplained.length) {
    notes.push(`ok   coverage: ${EXPECT_SITES.size} of ${declared.length} expect() call `
      + `sites ran; ${missed.length} conditional branch(es) not taken, each with its `
      + `counterpart confirmed`);
  }
}

await browser.close();

for (const n of notes) console.log(n);
for (const f of failures) console.log(f);
console.log(
  failures.length
    ? `\nREPORT IS INERT: ${failures.length} interaction(s) did not work in ${file}`
    : `\nreport is interactive: ${notes.length} checks passed in ${file}`);
process.exit(failures.length ? 1 : 0);
