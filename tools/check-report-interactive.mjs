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
  console.error('  python3 plugins/audit/scripts/render-report.py <manifest> --out-dir <dir> --format html');
  await browser.close();
  process.exit(2);
}

const load = await state();
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
  expect('the author view is a link (au= in the hash)', /#!.*au=/.test(auOn.hash), true);
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
