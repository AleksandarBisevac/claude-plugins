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
 *   node tools/check-report-interactive.mjs <report.html> --record
 *   node tools/check-report-interactive.mjs <report.html> --stress-print
 *
 * Exit 0 = every interaction behaved. Exit 1 = something is inert; the failing
 * assertion names which. Exit 2 = could not run (no browser, bad arguments, or a
 * report older than these checks) — distinct on purpose, so a missing dependency
 * is never read as a passing check.
 *
 * `--record` is the only thing here that WRITES, and it writes one thing: this
 * document's row in `tools/ui-checks/report-layout-baseline.json`, the recorded
 * figures the relative layout arm compares against. It refuses on a report with
 * any other failure. `ui-checks/layout-baseline.mjs` carries the reasoning — why
 * a relative arm exists beside an absolute bar, what the two measure, and how far
 * a figure may move before somebody has to say the move was meant.
 *
 * `--stress-print` adds the one check too heavy for every leg: the report is grown
 * past the length that once crashed Chrome's printer and printed. It costs tens of
 * seconds and several gigabytes of renderer memory, so it is asked for by exactly
 * one report step of `tools/verify.sh`, run when no other leg is printing beside
 * it; without the flag the run says it was not asked rather than staying silent.
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
// ...and the liveness rule, from the same file for the same reason: it is one
// rule about whether a driven page is still the page that was set up, and a
// second copy of it is how a restored page silently going dead comes back on the surface that did not get the
// fix. The panel gate arms it on a `.tab`; this file arms it on the control it
// drives most.
import { RESPONSIVE_LADDER, walkResponsiveLadder, assertLadderMeasuredSomething,
         newLadderTally, assertStillLive, newLivenessTally,
         assertLivenessWasChecked } from './capture-screenshots.mjs';
import { FRAMED_BELOW } from './ui-checks/responsive.mjs';
// Naming a <details> by what it CONTAINS. `.more` is a shared BEHAVIOURAL class
// (print expansion) that several disclosures wear on purpose, so it identifies a
// behaviour and not a disclosure; the rule and the scar it came from are in that
// file. Imported by both gates so there is one copy of it.
import { HEATMAP_NAV, USAGE_DETAIL_CHARTS, readDisclosure,
         disclosureSummary } from './ui-checks/disclosures.mjs';
// The RELATIVE arm of the phone-layout question, beside the absolute stack check
// this file carries. That file says why there are two, why they measure different
// quantities and how far a figure may move; this one measures and reports.
import { PHONE_VIEWPORT, applyRecording, documentKey, emptyBaseline, judge,
         readBaseline, share, writeBaseline } from './ui-checks/layout-baseline.mjs';

// FLAGS ARE VALIDATED AND POSITIONALS ARE NOT, which is not an oversight. A
// mistyped flag is silently nothing — `--recrod` would leave a run that was asked
// to bless a figure quietly not blessing it — so an unknown one stops the tool. A
// second positional has always been ignored here and one caller relies on it: CI
// drives `/tmp/live-plan/*.html`, a glob the shell expands, and rejecting the
// extra would turn a green step red for a reason that has nothing to do with the
// report.
const args = process.argv.slice(2);
const flags = args.filter((a) => a.startsWith('--'));
const unknown = flags.filter((a) => a !== '--record' && a !== '--stress-print');
if (unknown.length) {
  console.error(`unknown option(s): ${unknown.join(' ')}`);
  console.error('usage: check-report-interactive.mjs <report.html> [--record] [--stress-print]');
  process.exit(2);
}
const RECORDING = flags.indexOf('--record') >= 0;
const STRESS = flags.indexOf('--stress-print') >= 0;
const file = args.find((a) => !a.startsWith('--'));
if (!file) {
  console.error('usage: check-report-interactive.mjs <report.html> [--record] [--stress-print]');
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
// keeps meeting (a restore that killed every listener, after which six tabs
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
// A whole FEATURE can be absent from a plan, and then every check about it is
// unrunnable rather than skipped. The harness already says so out loud at the
// guard -- "no phase in this plan carries an area tag - area chips skipped" --
// so the grader reads that note instead of demanding a site it could never have
// reached. Keyed by the note's own words and by label PREFIX, never by line
// number: this file is edited from the top.
//
// Without this the grader is a gate that only works on one report. Measured on a
// plan with no areas, no authors and nothing ready: 29 of 133 sites unreachable
// and every one of them correct.
// --- what a document may legitimately lack, and what is conditional ------------
// This file is a LINEAR SCRIPT, not a set of functions: most of what follows is
// `const x = await …` at top level, one step after another. The markers therefore
// name PHASES of one procedure rather than units that could be called separately,
// which is also why the spans between them are long.

const FEATURE_ABSENT = [
  { note: 'no author chips',
    covers: ['the author view is a link', 'releasing the chip restores the top-8',
             '...and the summary line leaves with it', '...and the au fragment leaves',
             'the authors dropdown narrows', 'the dropdown selection is a link (au=',
             '...and the author chips light', 'All authors restores',
             '...and au= leaves the URL'] },
  { note: 'no phase in this plan carries an area tag',
    covers: ['an area chip reports itself as on', 'the area view is a link (a=',
             'Clear filters restores the hidden phases',
             '...and the chip stops reporting itself as on', '...and a= leaves the URL',
             'the area dropdown keeps only', 'the dropdown selection is a link (a=',
             'in the Archived view the area select still offers every area',
             '...and so do the area chips',
             'All areas restores every phase', '...and hides all',
             'the "'] },
  // A plan naming no third place, or one that merged nothing, paints no chip;
  // the page-level requirement above it still runs on every document.
  { note: 'no full-run line in this report',
    covers: ['every full-run line carries an answer the renderer knows',
             'every full-run line reads the sentence its own answer renders',
             'no full-run line is hidden by the stylesheet',
             'a merged phase carries one full-run line and never two'] },
  // A plan that records no commit renders no copy button, so neither the
  // button's hover nor the row hover that reveals it has a box to read.
  { note: 'no task in this plan records a commit — sha hover skipped',
    covers: ['tr interaction-state parity', '.shacopy interaction-state parity'] },
  // The long print is opt-in (`--stress-print`): a run that did not ask for it
  // says so, and that note excuses its two sites.
  { note: 'the long-print stress check was not asked for',
    covers: ['(setting up the long print) the uncut sheet was grown past the crashing',
             'a page past the length that crashed the printer prints'] },
  // No More-filters disclosure on the phone: nothing to open while stuck, and no
  // open state for the stack over the table to be measured in. No chip inside
  // it: nothing to switch on so the summary has a count to say.
  { note: 'phone panel check skipped',
    covers: ['lm6', 'lm7', 'lm5 with More filters open', 'lm8 with More filters open'] },
  // No wide font installed, or none wider than the page's own: the layout
  // matrix reads one font, and says so in its notes and its summary line.
  { note: 'wide-font pass NOT RUN',
    covers: ['lm the wide-font pass draws the page in the font it names'] },
  // A plan that cancelled no task has no match the task fraction leaves out;
  // the basis check above still holds the clause absent on every report.
  { note: 'no cancelled task in this plan',
    covers: ['a search for the cancelled task'] },
  { note: 'its announced count skipped',
    covers: ['ax3 with one filter on, More filters is announced'] },
  { note: 'nothing is ready in this plan',
    covers: ['every ready task is a term', 'the list carries as many terms',
             'every term names its task id', 'every definition says why',
             'tasks of tagged phases wear the area chips'] },
  // Ready work with no area tag on the phase it sits in: the chip cross-check
  // has nothing to compare, and its own else-half prints this note. Keyed by
  // that note rather than by 'no phase in this plan carries an area tag',
  // because a plan can tag some phases and still have every ready task in an
  // untagged one - and with the note absent the site is still demanded, so a
  // ready task in a tagged phase keeps being checked.
  { note: 'no ready task sits in a tagged phase',
    covers: ['tasks of tagged phases wear the area chips'] },
  // A plan where no single press empties a narrowed view while phases outside
  // it match: the truth rule above still runs over every press, and only the
  // halves that prove it was exercised have nothing to point at.
  { note: 'no press empties a view while phases outside it match',
    covers: ['...and a view hiding every match is among the presses',
             'es2 after Show all phases the keyboard is on the View select'] },
  { note: 'no press empties the table',
    covers: ['es1 after the Clear inside the empty state'] },
  { note: 'no status chips in this report',
    covers: ['no matches-outside-this-view notice shows while rows do',
             '...and choosing All phases from the View select reaches them instead',
             '...with the search still applied'] },
  // The heatmap's absence is reported by the calendar block's own else, and it
  // stands for the whole usage payload: without a ledger the report renders no
  // heatmap, no range-scoped charts and no daily CSV. Its scope is a REGION
  // rather than a list of labels — twenty-one of them — because a list that long
  // is a list that rots, and the marked regions move with the code they wrap.
  { note: 'no heatmap in this report',
    covers: [],
    region: 'needs-usage-payload' },
  // Not a missing feature but a plan whose DEFAULT VIEW is not "active" - every
  // phase shares one status, so the renderer opens on all of them. The checks
  // that ride that fragment and the archived-vs-active search cannot run, and
  // the else-halves beside them do.
  { note: 'a plan with nothing active opens on all phases',
    covers: ['on load the archived phases are off screen',
             '...and the view rides the shareable fragment',
             'no matches-outside-this-view notice shows while rows do',
             '...and choosing All phases from the View select reaches them instead',
             '...with the search still applied'] },
];

const CONDITIONAL_EXPECTS = [
  // The two halves of the proposals branch. They are mutually exclusive per
  // document: a plan either carries proposals or it does not, and CI renders both
  // kinds. NO DOUBLE QUOTES in these labels - the extractor stops at one.
  { label: 'no proposals in this plan, so no Proposals section is claimed',
    why: 'runs only on a plan that carries no proposals at all',
    instead: 'every parked proposal is listed with a state the vocabulary knows' },
  { label: 'every parked proposal is listed with a state the vocabulary knows',
    why: 'runs only on a plan that carries proposals',
    instead: 'no proposals in this plan, so no Proposals section is claimed' },
  { label: '...and a DROPPED proposal carries why it was declined, or the '
         + 'archive is a tombstone',
    why: 'rides the same branch as the listing above it',
    instead: 'no proposals in this plan, so no Proposals section is claimed' },
  { label: '...and print opens them, so a PDF carries the payload a reader '
         + 'cannot click open',
    why: 'rides the same branch as the listing above it',
    instead: 'no proposals in this plan, so no Proposals section is claimed' },
  // The two halves of the ledger-attribution branch, each naming the other. NO
  // DOUBLE QUOTES in any of these strings: the label extractor stops at one, which
  // turned an earlier version of this label into the single word "every" - and a
  // one-word label is a wildcard prefix that reported an unrelated pair as skipped.
  { label: 'with no ledger authors for any task, no worked-by row is claimed',
    why: 'runs only on a report whose ledger attributes no task to any author '
       + '(metering off, or every metered row unattributed)',
    instead: 'every worked-by name is one the ledger actually recorded' },
  { label: 'every worked-by name is one the ledger actually recorded',
    why: 'runs only where the ledger does attribute at least one task, which a '
       + 'report rendered without a ledger never does',
    instead: 'with no ledger authors for any task, no worked-by row is claimed' },
  { label: '...and the check is not vacuous - the report really does list authors '
         + 'to compare against',
    why: 'rides the same branch as the name check above it',
    instead: 'with no ledger authors for any task, no worked-by row is claimed' },
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
// stack ending in this file: a diagnostic that dies computing its own
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
// The chip attributes the page's own script wires, read off the document. The
// empty-state block presses every chip carrying one, and the Clear block reports
// a wired attribute no exercised chip carries, so neither keeps a list by hand.
const WIRED_CHIP_ATTRS = [...new Set([...source.matchAll(/wireChips\([^,()]+, '(data-[a-z]+)'/g)]
  .map((m) => m[1]))].sort();
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
  ['.tablehead #audit-expand', 'the expand-all button, in the phases table\'s head'],
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

// Liveness, armed now that the sweep above has proved the anchor is in the
// document. `#audit-expand` is the control this file drives most and its handler
// is bound once, at load, with addEventListener — so it is exactly the node whose
// listeners an innerHTML restore would silently take away. What this asks is NOT
// "did anything change" (see the rule in capture-screenshots.mjs): it asks whether
// the nodes the report bound to are still the nodes on screen. Distinct from every
// other check in this file, which asks whether an interaction did the right thing —
// a question that has no meaning at all once the answer to this one is no.
const LIVE_ANCHOR = '#audit-expand';
const liveness = newLivenessTally();
const stillLive = (where) =>
  assertStillLive(page, LIVE_ANCHOR, `report: ${where}`,
    { report: (m) => failures.push(`FAIL ${m}`), tally: liveness });
await stillLive('at the start, before anything has been driven');

const load = await state();
if (load.total < 2) {
  console.error(`cannot check interactivity: only ${load.total} phase row(s); use a report with several`);
  await browser.close();
  process.exit(2);
}

// vw: the table renders in segments — active, pending, archived — and
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
// --- the segment order the report must render in -----------------------------------

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
// At rest too, the count says what it counts IN. A bare "165 phases" over a
// table showing five read as the size of the table, and the view was the reason.
// It names the view by the selected option's short name, read off the select
// here rather than written into this file, so a count that names some other
// view, or none, is wrong. The count is a live region: a screen reader hears it
// without the select beside it. No brackets: the option's full wording inside
// them wrapped the bar.
{
  const rest = /^(\d+) of (\d+) phases? · ([^()]+)$/.exec(load.count);
  const short = await page.evaluate(() => {
    const sel = document.getElementById('audit-view');
    const opt = sel ? sel.options[sel.selectedIndex] : null;
    return opt ? opt.getAttribute('data-short') : null;
  });
  expect('at rest the count names the view the View select sets, by its short name '
    + 'and without brackets (' + JSON.stringify(load.count) + ', short name '
    + JSON.stringify(short) + ')',
    !!rest && !!short && rest[3] === short
      && Number(rest[1]) === load.phases && Number(rest[2]) === load.total, true);
  // ...SAID, and not drawn. The View select beside the count already shows the
  // view, and drawn, the name wrapped the pinned bar at a laptop width. Drawn
  // means a text node no ancestor up to the count has clipped to a pixel - the
  // same reading lm3 holds inside the bar - so a name moved out of its clipped
  // box, or a clipped box that kept the whole count, is told apart.
  const drawn = await page.evaluate(() => {
    const c = document.getElementById('audit-count');
    let out = '';
    const walk = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      let clipped = false;
      for (let p = n.parentElement; p && p !== c.parentElement; p = p.parentElement) {
        const b = p.getBoundingClientRect();
        if (b.width <= 1 || b.height <= 1) clipped = true;
      }
      if (!clipped) out += n.textContent;
    }
    return out;
  });
  expect('vh1 at rest the count says the view to a screen reader and draws only the '
    + 'phase fraction (drawn ' + JSON.stringify(drawn) + ', said '
    + JSON.stringify(load.count) + ')',
    !!rest && !!short && drawn === rest[1] + ' of ' + rest[2] + ' phase'
      + (rest[2] === '1' ? '' : 's') && load.count.indexOf(short) >= 0, true);
}
// ...and the count it leaves stays inside its bar at every size, in either
// font: lm3 in the layout matrix below.

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
      const slot = document.querySelector('tr.norows [data-outside]');
      return {
        notice: !!slot && slot.getClientRects().length > 0,
        visible: [...document.querySelectorAll('table.phases tbody tr.phase')]
          .filter((r) => r.style.display !== 'none').length,
      };
    });
    // There is no STANDING "N phases match outside this view" row: it was removed
    // on the reader's second request, because the View select already offers
    // "All phases" and the row argued with a choice the reader had just made.
    // What replaced it is the empty state, which names those matches only when
    // nothing at all is drawn - so the rule is "no notice while rows show".
    expect('no matches-outside-this-view notice shows while rows do '
      + '(' + hidden.visible + ' phase rows shown)',
      hidden.notice && hidden.visible > 0, false);
    // What it must NOT cost: the route to those matches. The select is that route,
    // so the search has to survive switching to All and still find them.
    await page.selectOption('#audit-view', 'all');
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => ({
      view: document.getElementById('audit-view').value,
      visible: [...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((r) => r.style.display !== 'none').length,
    }));
    expect('...and choosing All phases from the View select reaches them instead',
      after.view, 'all');
    expect('...with the search still applied', after.visible > 0, true);
    await page.fill('#audit-q', '');
    await page.waitForTimeout(300);
  }
}

// THE EMPTY STATE IS TRUE. "No phase matches these filters" was printed over a
// view that hid every match: on acme-store, Test gate "Before recording" emptied
// the default view while the archived phase held both matching tasks. So for
// every press a reader can make, in each narrowed view, whenever the empty state
// shows: either View=All shows no phase either and the plain sentence is the
// truth, or the sentence names exactly the count View=All shows and its button
// lands there. And while rows show, the slot that names hidden matches stays
// hidden. Everything runs inside one evaluate: a refresh is synchronous, and a
// round trip per press would make this the slowest block in the file for no
// extra truth.
//
// The presses are DERIVED, never listed: every chip in the table's toolbar that
// carries an attribute the page's own script wires (WIRED_CHIP_ATTRS, the list
// the Clear block reads too), each again on top of a search, the search alone,
// and the date range set to a single day at either end of the span the date
// inputs allow. A chip axis added tomorrow is pressed here without this block
// naming it. The search term is a phase id from the archive when there is one,
// so in the default view the search alone already hides every match it has.
//
// The two buttons of the empty state then have to hand the keyboard somewhere
// that is still on the page: each hides the row it sits in, and a focus left on
// a hidden button sends the next Tab past the whole table. The View select is
// that place - the control that says which phases are drawn.
{
  const truth = await page.evaluate((wired) => {
    const viewSel = document.getElementById('audit-view');
    const norow = document.querySelector('tr.norows');
    const clear = document.querySelector('.sectools [data-clear]');
    if (!viewSel || !norow || !clear) return null;
    const before = viewSel.value;
    const slot = norow.querySelector('[data-outside]');
    const btn = norow.querySelector('[data-showall]');
    const norowClear = norow.querySelector('[data-clear]');
    const q = document.getElementById('audit-q');
    const from = document.getElementById('audit-from');
    const to = document.getElementById('audit-to');
    const seen = (el) => !!el && el.getClientRects().length > 0;
    const shown = () => [...document.querySelectorAll('table.phases tbody tr.phase')]
      .filter((r) => r.style.display !== 'none').length;
    const pick = (v) => { viewSel.value = v; viewSel.dispatchEvent(new Event('change')); };
    // Enter, not an input event: typing is debounced, and Enter is the key the
    // search filters on at once.
    const search = (v) => {
      q.value = v;
      q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    };
    const setDate = (el, v) => {
      el.value = v;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const chips = [...document.querySelectorAll('.sectools button')]
      .map((c) => ({ c, attr: wired.find((a) => c.hasAttribute(a)) }))
      .filter((x) => x.attr);
    const termRow = document.querySelector('table.phases tbody tr.phase[data-seg="archived"]')
      || document.querySelector('table.phases tbody tr.phase');
    const term = q && termRow
      ? (termRow.getAttribute('data-phase') || '').toLowerCase() : '';
    const presses = [];
    const chipPress = ({ c, attr }, withTerm) => ({
      what: (withTerm ? 'q=' + withTerm + ' + ' : '') + attr + '=' + c.getAttribute(attr),
      on: () => {
        if (c.hidden) return false;   // a chip this view does not offer
        if (withTerm) search(withTerm);
        c.click();
        return true;
      },
      // Released by its own second press, not by Clear alone: this block
      // proves the empty state, and leaning on Clear would make it a second
      // test of Clear that fails wherever Clear does.
      off: () => {
        if (c.getAttribute('aria-pressed') === 'true') c.click();
        if (withTerm) search('');
      },
    });
    chips.forEach((x) => presses.push(chipPress(x, '')));
    if (term) {
      presses.push({ what: 'q=' + term, on: () => { search(term); return true; },
                     off: () => search('') });
      chips.forEach((x) => presses.push(chipPress(x, term)));
    }
    const span = from && to && from.min && from.max ? [from.min, from.max] : [];
    span.forEach((day) => presses.push({
      what: 'from/to ' + day,
      on: () => { setDate(from, day); setDate(to, day); return true; },
      off: () => { setDate(from, ''); setDate(to, ''); },
    }));
    const out = [];
    ['active', 'archived'].forEach((v) => {
      presses.forEach((p, i) => {
        clear.click();
        pick(v);
        const resting = shown();
        if (!p.on()) return;
        // Whether the press did anything: fewer rows than the view draws at
        // rest, or the toolbar's Clear offered. Made is not the same as
        // effective - a search whose Enter no longer filters is still made.
        // The two are kept apart, because Clear shows for a term the search
        // never applied: a field holding text is a filter that is on.
        const r = { view: v, i, press: p.what,
                    rows: shown(), empty: seen(norow), slot: seen(slot) };
        r.fewer = r.rows < resting;
        r.narrowed = r.fewer || seen(clear);
        if (r.empty && r.slot) {
          const said = slot.textContent;
          const m = /(\d+)/.exec(said);
          r.said = said.trim();
          r.named = m ? Number(m[1]) : -1;
          btn.click();
          r.landedView = viewSel.value;
          r.landed = shown();
        } else if (r.empty) {
          pick('all');
          r.all = shown();
        }
        out.push(r);
        pick(v);
        p.off();
      });
    });
    // Where the keyboard lands after each empty-state button, from a press
    // that put the reader in front of it. Focus is moved OFF the select first,
    // so a select that merely kept a focus it already had cannot pass.
    const landsOnView = (r, act) => {
      clear.click();
      pick(r.view);
      presses[r.i].on();
      if (document.activeElement) document.activeElement.blur();
      act();
      const ok = document.activeElement === viewSel;
      pick(r.view);
      presses[r.i].off();
      return ok;
    };
    const emptied = out.find((r) => r.empty);
    const hid = out.find((r) => r.empty && r.slot);
    const focus = {
      clear: emptied && norowClear ? { press: emptied.view + ':' + emptied.press,
        onView: landsOnView(emptied, () => norowClear.click()) } : null,
      showAll: hid ? { press: hid.view + ':' + hid.press,
        onView: landsOnView(hid, () => btn.click()) } : null,
    };
    // Back to the view this block found, not the default: the steps below were
    // written against the view the search block above left behind.
    clear.click();
    pick(before);
    return { presses: presses.length, term, dates: span.length > 0, out, focus };
  }, WIRED_CHIP_ATTRS);
  if (!truth) {
    failures.push('FAIL the empty state, the View select and a Clear button are all on the page');
  } else {
    const lies = truth.out.filter((r) => r.empty && (r.slot
      ? (r.named !== r.landed || r.landedView !== 'all' || r.named < 1)
      : r.all !== 0));
    expect('the empty state is true - whenever nothing is drawn, it names exactly '
      + 'the count View=All shows and its button lands there, or All shows none '
      + 'either (' + truth.out.length + ' presses; wrong: ' + JSON.stringify(lies) + ')',
      lies.length, 0);
    const noisy = truth.out.filter((r) => r.rows > 0 && r.slot);
    expect('...and no press that leaves rows drawn shows the hidden-matches slot ('
      + JSON.stringify(noisy) + ')', noisy.length, 0);
    // Which kinds of press were made AND narrowed something, so a pass that
    // made none of a kind, or made only presses that filtered nothing, says so
    // rather than reading as covered. The search alone is its own kind: a
    // search with a chip still narrows through the chip when the search is dead.
    // A search counts only by the rows it took away: with the term held in the
    // field and never applied, Clear still shows. The term is an archived
    // phase's id, so the default view always draws fewer rows when it applies.
    const effective = (re, by) => truth.out.some((r) => re.test(r.press) && r[by]);
    const kinds = {
      chip: effective(/^(?!q=|from\/to )/, 'narrowed'),
      search: effective(/^q=(?!.* \+ )/, 'fewer'),
      'search + chip': effective(/ \+ /, 'fewer'),
      'from/to': effective(/^from\/to /, 'narrowed'),
    };
    expect('es0 the presses include a chip, a search, a search with a chip, and a date '
      + 'range, each at least once narrowing the view, a search by drawing fewer rows ('
      + JSON.stringify(kinds)
      + '; term ' + JSON.stringify(truth.term) + ')',
      Object.values(kinds).every(Boolean), true);
    const hiding = truth.out.filter((r) => r.empty && r.slot);
    if (hiding.length) {
      expect('...and a view hiding every match is among the presses, so the rule '
        + 'above was exercised and not satisfied by never emptying a view ('
        + hiding.map((r) => r.view + ':' + r.press + ' says ' + JSON.stringify(r.said))
          .join('; ') + ')', hiding.length > 0, true);
      expect('es2 after Show all phases the keyboard is on the View select, not on '
        + 'the hidden button (' + truth.focus.showAll.press + ')',
        truth.focus.showAll.onView, true);
    } else {
      notes.push('ok   (no press empties a view while phases outside it match - '
        + 'the hidden-matches sentence was not exercised)');
    }
    if (truth.focus.clear) {
      expect('es1 after the Clear inside the empty state the keyboard is on the View select, '
        + 'not on the hidden button (' + truth.focus.clear.press + ')',
        truth.focus.clear.onView, true);
    } else {
      notes.push('ok   (no press empties the table - the Clear inside the empty state was not pressed)');
    }
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
  // And the STATUS CHIPS follow the view, because the two gates are
  // ANDed. With Archived selected the bar used to keep offering Pending, and
  // pressing it produced "0 / 9 phases" — a control whose every use is empty by
  // construction. The segment each status files under is read off the rows, so
  // this asserts the coupling rather than a hard-coded vocabulary.
  {
    const chips = await page.evaluate(() => {
      const segOf = {};
      document.querySelectorAll('table.phases tbody tr.phase').forEach((r) => {
        const st = r.getAttribute('data-status');
        if (st && !(st in segOf)) segOf[st] = r.getAttribute('data-seg');
      });
      const bar = document.getElementById('audit-phase-status');
      return { segOf, offered: bar
        ? [...bar.querySelectorAll('[data-ps]')].filter((c) => !c.hidden)
            .map((c) => c.getAttribute('data-ps')) : [] };
    });
    const wrong = chips.offered.filter((st) => chips.segOf[st] !== 'archived');
    expect('in the Archived view only archived statuses are offered as chips '
      + '(' + JSON.stringify(chips.offered) + ')', wrong.length, 0);
    // The half that stops this passing by offering NOTHING: an archived plan has
    // at least one archived status, and its chip must be there.
    const wantedSome = Object.keys(chips.segOf).some((st) => chips.segOf[st] === 'archived');
    expect('...and the archived statuses that exist ARE offered, so the rule is '
      + 'not satisfiable by hiding everything', !wantedSome || chips.offered.length > 0, true);
  }
  // The AREA controls are NOT pruned by the view, and that is the decision rather
  // than the oversight. Pruning them left a select whose only option was "All
  // areas" - a control every use of which is a no-op - and an area the view
  // hides is now answered where the answer is true: the empty state names the
  // phases outside the view and offers the one press that shows them, which the
  // empty-state block above holds for every area chip. So in the Archived view
  // the select and the chips offer every area the plan tags.
  {
    const areas = await page.evaluate(() => {
      const tagged = new Set();
      document.querySelectorAll('table.phases tbody tr.phase').forEach((r) => {
        (r.getAttribute('data-area') || '').split(' ').filter(Boolean)
          .forEach((a) => tagged.add(a));
      });
      const sel = document.getElementById('audit-area-select');
      const bar = document.getElementById('audit-areas');
      return {
        tagged: [...tagged].sort(),
        offered: sel ? [...sel.options].filter((o) => o.value && !o.hasAttribute('data-multi'))
          .map((o) => o.value).sort() : null,
        chips: bar ? [...bar.querySelectorAll('[data-a]')].filter((c) => !c.hidden)
          .map((c) => c.getAttribute('data-a')).sort() : null,
      };
    });
    if (areas.offered !== null) {
      expect('in the Archived view the area select still offers every area the plan '
        + 'tags (' + JSON.stringify(areas.offered) + ')',
        areas.offered.join(','), areas.tagged.join(','));
    }
    if (areas.chips !== null) {
      expect('...and so do the area chips (' + JSON.stringify(areas.chips) + ')',
        areas.chips.join(','), areas.tagged.join(','));
    }
  }
  // The `technical` trim. The invariant holds on ANY fixture, which is what keeps
  // this out of the feature-absence table: a box that overflows five lines must
  // offer the control, and a box that fits must not. Vacuity is impossible - if
  // no box is trimmed the second half still asserts every button is hidden.
  {
    await page.evaluate(() => {
      document.querySelectorAll('.dtoggle').forEach((b) => b.click());
    });
    await page.waitForTimeout(400);
    const clamp = await page.evaluate(() => [...document.querySelectorAll('[data-clamp]')]
      .map((box) => {
        const btn = box.parentNode.querySelector('[data-clampmore]');
        return { cut: box.scrollHeight > box.clientHeight + 2, shown: btn ? !btn.hidden : null };
      }));
    expect('every task detail carries a trim control for its technical prose',
      clamp.length > 0 && clamp.every((c) => c.shown !== null), true);
    expect('...offered only where the text is actually cut off, never on prose '
      + 'that already fits (' + clamp.filter((c) => c.cut).length + ' of '
      + clamp.length + ' trimmed)', clamp.every((c) => c.shown === c.cut), true);
    await page.evaluate(() => {
      document.querySelectorAll('.dtoggle').forEach((b) => b.click());
    });
    await page.waitForTimeout(300);
  }
  // "worked by" comes from the LEDGER, not the plan. The page carries no per-task
  // author map for a client to check against - `window.AUDIT_USAGE` is a
  // deliberately narrow per-day payload and widening it for a test would be the
  // test changing the product. The oracle on the page is the AUTHOR FILTER, whose
  // options are exactly the ledger's authors: a name in "worked by" that is not
  // among them would be this row inventing an assignee, which is the one thing it
  // exists not to do.
  {
    const who = await page.evaluate(() => {
      const sel = document.getElementById('audit-au-select');
      // TWO spellings, because the report drops the dropdown when there is only
      // one author and names them in a line instead - reading only the select made
      // every real name look invented on a single-author plan.
      const only = document.getElementById('audit-au-only');
      const oracle = [
        sel ? [...sel.options].map((o) => o.value).filter(Boolean).join(' ') : '',
        only ? only.textContent : '',
      ].join(' ').trim();
      const shown = [...document.querySelectorAll('tr.taskdetail')].map((d) => {
        const cell = [...d.querySelectorAll('.dt-r')]
          .find((r) => (r.querySelector('.dt-k') || {}).textContent === 'worked by');
        return cell
          ? cell.querySelector('.dt-v').textContent
              .replace(/\(metered on this task\)/, '').trim()
          : '';
      }).filter(Boolean);
      const names = [...new Set(shown.join(', ').split(',').map((x) => x.trim()).filter(Boolean))];
      return { oracle, named: shown.length, names,
               unknown: oracle ? names.filter((n) => oracle.indexOf(n) < 0) : [] };
    });
    if (!who.named) {
      expect('with no ledger authors for any task, no worked-by row is claimed',
        who.names.length, 0);
    } else {
      // Static label, detail in the VALUE: the label extractor keeps only the
      // first literal, so a concatenated label and its entry in the table below
      // can never agree - and the offending name is worth more than a count.
      expect('every worked-by name is one the ledger actually recorded',
        who.unknown.join(', '), '');
      expect('...and the check is not vacuous - the report really does list '
        + 'authors to compare against', who.oracle.length > 0, true);
    }
  }
  // Parked proposals are ON the page. An /audit:init that parks everything
  // used to render zero phases and no hint that any proposal existed, and a report
  // that shows nothing does not read as "the proposals are elsewhere" - it reads as
  // "there is nothing", on the one surface a team is likely to be shown.
  {
    const props = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('[data-prop]')].map((d) => ({
        id: d.getAttribute('data-prop'),
        status: d.getAttribute('data-status'),
        open: d.tagName === 'DETAILS' ? d.open : null,
        text: (d.textContent || '').replace(/\s+/g, ' ').trim(),
      }));
      return { rows, sectioned: !!document.getElementById('proposals'),
               phaseRows: document.querySelectorAll('table.phases tbody tr.phase').length,
               meta: (document.querySelector('.topbar .meta') || {}).textContent || '' };
    });
    if (!props.rows.length) {
      expect('no proposals in this plan, so no Proposals section is claimed',
        props.sectioned, false);
    } else {
      expect('every parked proposal is listed with a state the vocabulary knows '
        + '(' + props.rows.length + ' shown)',
        props.rows.every((r) => ['proposed', 'materialized', 'dropped']
          .includes(r.status)), true);
      // The half that makes archiving worth more than deleting.
      const dropped = props.rows.filter((r) => r.status === 'dropped');
      expect('...and a DROPPED proposal carries why it was declined, or the '
        + 'archive is a tombstone',
        !dropped.length || dropped.every((r) => /why declined/i.test(r.text)), true);
      // The claim the stylesheet makes, checked rather than asserted in a comment:
      // report/date-range.js opens every <details> for print, which is why
      // <details> was the right mechanism.
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
      await page.waitForTimeout(120);
      const opened = await page.evaluate(() =>
        [...document.querySelectorAll('details[data-prop]')].every((d) => d.open));
      expect('...and print opens them, so a PDF carries the payload a reader '
        + 'cannot click open', opened, true);
      await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
    }
    // The other half of the parked-proposals check, written as an IMPLICATION so it always runs: a
    // plan with phases satisfies it vacuously, and one without phases has to carry
    // the sentence. A conditional pair would have been wrong here - on a report
    // with phases NEITHER half can run, which is a skipped leg rather than a
    // branch not taken.
    //
    // Vacuous on every document THIS tool is pointed at, and deliberately so: a
    // report with no plan has none of the elements this tool drives, so it exits 2
    // ("cannot check") - the correct answer for it, not a gap. The all-parked case
    // is proven in CI instead, by rendering that manifest and grepping for the
    // sentence. This line is the cheap guard for the other direction: a report WITH
    // phases must never start claiming proposals are parked.
    expect('an empty plan names its parked proposals rather than reading as '
      + 'nothing at all',
      props.phaseRows > 0 || !props.rows.length
        || /parked proposal/.test(props.meta), true);
  }
  // A reload is the one mutation that legitimately throws the armed nodes away,
  // so this re-arms rather than reporting. It is here so that everything below
  // is measured against a baseline taken AFTER the navigation, instead of being
  // compared with nodes that stopped existing three assertions ago.
  await stillLive('after the reload, re-arming against the fresh document');
  await page.selectOption('#audit-view', 'all');
  await page.waitForTimeout(250);
}

// ex: the per-task detail row. The compact row truncates the outcome at
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
    // THE GROUP COUNT IS A PROPERTY OF THE REPORT, NOT A CONSTANT, and pinning it
    // as a literal made this line green for the wrong reason: the shipped example
    // records no runs, so the drawer's third group was inert in the one document
    // this gate ever opened. Driving a report that DOES carry evidence is what
    // turned it red.
    //
    // NOT REWRITTEN AS "expect whatever the page showed" -- that reads the answer
    // out of the thing under test and can only fail on ordering. Two independent
    // claims instead: the groups that are never optional are always the first two,
    // in that order, and any third can only be the evidence one and can only come
    // last. A missing mandatory group, a renamed one, a stray one and a
    // mis-ordered one each fail a different half.
    expect('...opening in labelled groups, the two mandatory ones first',
           opened.groups.slice(0, 2).join(','), 'meta,task details');
    expect('...and any further group is the evidence one, last',
           opened.groups.slice(2).join(','),
           opened.groups.length > 2 ? 'test evidence' : '');
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

// sha: nine characters on screen, forty on the clipboard.
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

// Hover, read off each control's OWN box. A screenshot of a whole table at rest
// says nothing about what a pointer over one chevron does, and a pixel diff over
// a section would let a colour change of a few pixels through. So each control
// is hovered for real and its computed style compared twice: against its own
// rest state, which proves the hover changed something, and against the token
// the sheet names for that state, resolved in the same cell, which proves it
// changed to the right thing.
{
  const view0 = await page.evaluate(() => {
    const sel = document.getElementById('audit-view');
    return sel ? sel.value : null;
  });
  if (view0 !== null && view0 !== 'all') {
    await page.selectOption('#audit-view', 'all');
    await page.waitForTimeout(200);
  }
  const shut = await page.evaluate(() =>
    [...document.querySelectorAll('tr.task')].every((r) => r.offsetParent === null));
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  // The token as this very cell resolves it, so a theme or a dark sheet
  // cannot make the comparison disagree with itself.
  const tokenIn = (sel, prop, token) => page.evaluate(({ s, p, t }) => {
    const host = document.querySelector(s);
    const probe = document.createElement('span');
    probe.style.setProperty(p, `var(${t})`);
    host.append(probe);
    const v = getComputedStyle(probe).getPropertyValue(p);
    probe.remove();
    return v;
  }, { s: sel, p: prop, t: token });
  const styleOf = (sel, props) => page.evaluate(({ s, ps }) => {
    const n = document.querySelector(s);
    const cs = getComputedStyle(n);
    return Object.fromEntries(ps.map((p) => [p, cs.getPropertyValue(p)]));
  }, { s: sel, ps: props });
  const rest = async () => { await page.mouse.move(1, 1); await page.waitForTimeout(450); };
  const hoverOn = async (sel) => { await page.hover(sel); await page.waitForTimeout(450); };

  // Each target is marked by attribute, so the selector names one element and
  // a later re-render cannot move the question onto a different one.
  const marked = await page.evaluate(() => {
    const visible = (n) => n && n.checkVisibility();
    const tog = [...document.querySelectorAll('tr.task .dtoggle')].find(visible);
    if (tog) tog.setAttribute('data-hover-probe', 'dtoggle');
    const sha = [...document.querySelectorAll('tr.task .shacopy')]
      .find((b) => visible(b.closest('tr')));
    if (sha) {
      sha.setAttribute('data-hover-probe', 'shacopy');
      sha.closest('tr').setAttribute('data-hover-probe', 'row');
      // A cell of the row that is not the button, so hovering the ROW never
      // also hovers the control inside it.
      const cell = [...sha.closest('tr').cells].find((c) => !c.contains(sha));
      if (cell) cell.setAttribute('data-hover-probe', 'rowcell');
    }
    return { tog: !!tog, sha: !!sha };
  });

  if (marked.tog) {
    const T = '[data-hover-probe="dtoggle"]';
    await rest();
    const at0 = await styleOf(T, ['color']);
    await hoverOn(T);
    const at1 = await styleOf(T, ['color']);
    const accent = await tokenIn(T, 'color', '--accent');
    expect('.dtoggle interaction-state parity - a clipped snapshot (or a computed-style '
      + 'assertion) of its OWN box in its hover state, not only rest (its colour at rest, '
      + 'hovered, and the --accent the hover rule names)',
      `${at1.color !== at0.color} ${at1.color === accent}`, 'true true');
  } else {
    failures.push('FAIL no visible task row carries a .dtoggle to hover, so its hover state '
      + 'was never measured');
  }

  if (marked.sha) {
    const B = '[data-hover-probe="shacopy"]';
    const R = '[data-hover-probe="row"]';
    const C = '[data-hover-probe="rowcell"]';
    await rest();
    const rowRest = await styleOf(`${R} > td`, ['background-color']);
    const btnRest = await styleOf(B, ['opacity', 'color', 'border-top-color']);
    await hoverOn(C);
    const rowHover = await styleOf(`${R} > td`, ['background-color']);
    const btnInRow = await styleOf(B, ['opacity']);
    const surface2 = await tokenIn(C, 'background-color', '--surface-2');
    expect('tr interaction-state parity - a clipped snapshot (or a computed-style '
      + 'assertion) of its OWN box in its hover state, not only rest (a task row hovered '
      + 'away from its copy button: its cells change from rest to --surface-2, and the '
      + 'copy button it holds goes from invisible to opaque)',
      `${rowHover['background-color'] !== rowRest['background-color']} `
      + `${rowHover['background-color'] === surface2} `
      + `${btnRest.opacity} ${btnInRow.opacity}`, 'true true 0 1');
    await hoverOn(B);
    const btnHover = await styleOf(B, ['opacity', 'color', 'border-top-color']);
    const accentC = await tokenIn(B, 'color', '--accent');
    expect('.shacopy interaction-state parity - a clipped snapshot (or a computed-style '
      + 'assertion) of its OWN box in its hover state, not only rest (its ink and its '
      + 'border, at rest and hovered, against the --accent the hover rule names)',
      `${btnHover.color !== btnRest.color} ${btnHover.color === accentC} `
      + `${btnHover['border-top-color'] === accentC} ${btnHover.opacity}`,
      'true true true 1');
  } else notes.push('ok   (no task in this plan records a commit — sha hover skipped)');

  await rest();
  await page.evaluate(() => {
    for (const n of document.querySelectorAll('[data-hover-probe]')) {
      n.removeAttribute('data-hover-probe');
    }
  });
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  if (view0 !== null && view0 !== 'all') {
    await page.selectOption('#audit-view', view0);
    await page.waitForTimeout(200);
  }
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

// A term taken from the document itself, so this works on any report. The
// naive pick - the title's first word - can be "A", "The", "Do" or another
// word so common it sits inside almost every row's own rendered text (dates,
// statuses, the words "task" and "phase" themselves); a term like that cannot
// narrow this document no matter how correctly the filter runs, which is a
// fixture problem wearing a filter-is-broken message. So each word is checked
// against every phase row BEFORE being trusted, and the first one that is not
// already everywhere is used - the same guard already applied to the status
// chip below (asserted one way with two-or-more chips, the OTHER way with
// exactly one), generalised to free text instead of skipped when it cannot
// fire.
const termInfo = await page.evaluate(() => {
  const s = document.querySelector('table.phases tbody tr.phase strong');
  const words = s ? s.textContent.trim().split(/\s+/) : [];
  const rows = [...document.querySelectorAll('table.phases tbody tr.phase')]
    .map((r) => r.textContent.toLowerCase());
  const vacuous = [];
  for (const raw of words) {
    const w = raw.toLowerCase();
    if (!w) continue;
    if (rows.every((h) => h.includes(w))) { vacuous.push(w); continue; }
    return { term: w, vacuous: vacuous };
  }
  return { term: null, vacuous: vacuous };
});
if (termInfo.term === null) {
  notes.push('ok   (every word of the first phase title sits inside every phase row - '
    + 'no free-text term in this report could narrow it; narrowing check skipped)');
} else {
  const term = termInfo.term;
  const guardNote = termInfo.vacuous.length
    ? ` (rejected ${termInfo.vacuous.map((w) => `"${w}"`).join(', ')} first - already in every phase row)`
    : '';
  await page.click('#audit-q');
  await page.keyboard.type(term, { delay: 10 });
  await page.waitForTimeout(250);
  const hit = await state();
  if (hit.phases < 1 || hit.phases >= load.total) {
    failures.push(`FAIL filtering by "${term}" narrows the list: got ${hit.phases} of ${load.total}${guardNote}`);
  } else notes.push(`ok   filtering by "${term}" narrows the list: ${hit.phases} of ${load.total}${guardNote}`);
  if (!/\d+ of \d+ phases? · [^()]+ · \d+ of \d+ tasks?/.test(hit.count)) {
    failures.push(`FAIL the count reports the filtered total: got "${hit.count}"`);
  } else notes.push(`ok   the count reports the filtered total: "${hit.count}"`);
  // The counter's BASIS, read against what it must agree with: the header's own
  // totals (whose task total leaves cancelled work out), and the cancelled
  // matches it leaves out named rather than dropped - counted here off the rows
  // the page shows, so a clause that is missing and one that is invented both
  // disagree. "165 phases" over a table showing five, and a task denominator
  // counting what the header did not, were the defect.
  {
    const basis = await page.evaluate((t) => {
      const meta = (document.querySelector('.tb-id .meta') || {}).textContent || '';
      const hp = /(\d+) phases? · (\d+) tasks?/.exec(meta);
      const shownRows = [...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((r) => r.style.display !== 'none');
      // A task is a match when its own row OR its phase's row holds the term:
      // a phase found by its title brings every one of its tasks with it. The
      // row's match badge is left out - the page read the row's words before
      // any filter wrote one.
      const own = (r) => {
        const badge = r.querySelector('.pmatch');
        return r.textContent.replace(badge ? badge.textContent : '', '').toLowerCase();
      };
      const phaseHit = new Map(shownRows.map((r) =>
        [r.getAttribute('data-phase'), own(r).includes(t)]));
      const sel = document.getElementById('audit-view');
      const opt = sel ? sel.options[sel.selectedIndex] : null;
      return {
        count: (document.getElementById('audit-count') || {}).textContent || '',
        short: opt ? opt.getAttribute('data-short') : null,
        phases: hp ? Number(hp[1]) : null,
        tasks: hp ? Number(hp[2]) : null,
        shown: shownRows.length,
        cancelled: [...document.querySelectorAll('table.phases tbody tr.task[data-status="cancelled"]')]
          .filter((r) => phaseHit.has(r.getAttribute('data-phase'))
            && (phaseHit.get(r.getAttribute('data-phase'))
              || r.textContent.toLowerCase().includes(t))).length,
      };
    }, term);
    const m = /^(\d+) of (\d+) phases? · ([^()]+) · (\d+) of (\d+) tasks?(?:, (\d+) cancelled not counted)?$/
      .exec(basis.count);
    expect('the filtered count names its basis - shown of the header\'s phases, the '
      + 'view by its short name, tasks of the header\'s task total, and the cancelled '
      + 'tasks it leaves out (' + JSON.stringify(basis) + ')',
      !!m && Number(m[1]) === basis.shown && Number(m[2]) === basis.phases
        && !!basis.short && m[3] === basis.short
        && Number(m[5]) === basis.tasks && Number(m[6] || 0) === basis.cancelled, true);
  }
  // A TEXT filter is the one that used to force its matches open — one character
  // typed grew the page by screens and scrolled away what was being read, and
  // clearing it afterwards shut rows that had been opened by hand. Asserted here
  // rather than in a string pin, because `expanded[pid]` reads identically either
  // way: only a browser can say whether the rows are on screen.
  expect('a text filter does not auto-expand the phases it matches', hit.tasks, 0);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);
}

// A cancelled task a search finds is shown in its phase, and the task fraction
// leaves it out - so the count has to say it is there, or the screen holds a
// match the count calls zero. Searched by the task's own id, in View=All so its
// phase is drawn whatever segment it files under.
{
  const cx = await page.evaluate(() => {
    const r = document.querySelector('table.phases tbody tr.task[data-status="cancelled"]');
    const id = r && r.querySelector('td.tid');
    return id ? id.textContent.trim().toLowerCase() : null;
  });
  if (cx === null) {
    notes.push('ok   (no cancelled task in this plan - the cancelled clause was not exercised)');
  } else {
    const viewWas = await page.$eval('#audit-view', (s) => s.value);
    await page.selectOption('#audit-view', 'all');
    await page.fill('#audit-q', cx);
    await page.waitForTimeout(300);
    const said = await page.evaluate((t) => {
      // The same rule as the basis check above: its own row or its phase's,
      // the phase's match badge left out.
      const own = (r) => {
        const badge = r.querySelector('.pmatch');
        return r.textContent.replace(badge ? badge.textContent : '', '').toLowerCase();
      };
      const phaseHit = new Map([...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((r) => r.style.display !== 'none')
        .map((r) => [r.getAttribute('data-phase'), own(r).includes(t)]));
      return {
        count: document.getElementById('audit-count').textContent,
        truth: [...document.querySelectorAll('table.phases tbody tr.task[data-status="cancelled"]')]
          .filter((r) => phaseHit.has(r.getAttribute('data-phase'))
            && (phaseHit.get(r.getAttribute('data-phase'))
              || r.textContent.toLowerCase().includes(t))).length,
      };
    }, cx);
    const m = /, (\d+) cancelled not counted$/.exec(said.count);
    expect(`a search for the cancelled task ${cx} names the cancelled tasks the task count `
      + `leaves out (${JSON.stringify(said)})`,
      !!m && said.truth > 0 && Number(m[1]) === said.truth, true);
    await page.fill('#audit-q', '');
    await page.selectOption('#audit-view', viewWas);
    await page.waitForTimeout(250);
  }
}

// ...and the closed row has to say WHY it survived, which is what replaces the
// expansion: a row reading "1 of 3 match" is a row worth opening. That needs a
// term matching some of a phase's tasks and not the phase's own heading — a term
// the heading carries makes every task a match, and "3 of 3" is deliberately not
// drawn. Found in the document rather than hard-coded, so this works on any report.
// --- partial matches, and the chip state they imply --------------------------------

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
// --- the panel's parts, as the report shows them -----------------------------------

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
// --- the area chips ----------------------------------------------------------------

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

// 6d. The header filter row (C1/C2): a second line of the top bar
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
      // @needs-usage-payload — every assertion to the matching end marker reads
      // window.AUDIT_USAGE, so on a report rendered without a ledger they cannot
      // run and their silence is not a skipped check. See the verdict block.
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
      // @end-needs-usage-payload
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
// filter row lives in the top bar at every width (sticky above 52rem unless the
// screen is under 32rem tall, scrolling with the page otherwise), so at no width may the PAGE scroll sideways because
// of it. 390px is the width that found the last
// such defect (the filter panel).
for (const w of [1512, 390]) {
  await page.setViewportSize({ width: w, height: w > 700 ? 945 : 780 });
  await page.waitForTimeout(250);
  const grow = await page.evaluate(() => ({
    dw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
    row: !!document.querySelector('.gfilters'),
  }));
  if (grow.row) {
    expect(`at ${w}px the header filter row does not push the page sideways `
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
  // @needs-usage-payload — the whole calendar rides the per-day payload.
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

  // The heatmap lives inside the Usage section's Detail disclosure; a reader
  // opens it to reach the nav, and so does this. Driven like the reader would,
  // via the summary, not by poking the open property.
  //
  // WHICH disclosure comes from the nav itself: `disclosureSummary` takes the
  // `<details>` around `#audit-hm-gran`. This used to read `details.more`, which
  // named a shared print-behaviour class rather than a disclosure — and once the
  // test-evidence history started wearing it too, the click went to whichever
  // came first in the document, found it invisible inside a closed task drawer,
  // and spent thirty seconds dying.
  if (await readDisclosure(page, HEATMAP_NAV) === 'shut') {
    const summary = await disclosureSummary(page, HEATMAP_NAV);
    if (summary) {
      await summary.click();
      await page.waitForTimeout(150);
    }
  }
  const hmDisclosure = await readDisclosure(page, HEATMAP_NAV);
  expect('a reader opening the Detail disclosure by its summary reaches the '
    + 'heatmap calendar navigation - the disclosure that opens is the one '
    + 'CONTAINING the nav, not whichever .more the document happens to hold '
    + 'first', hmDisclosure, 'open');
  // Recovered, not repaired. The line above has already recorded that a reader
  // could not reach the nav; forcing it open keeps the assertions below running
  // instead of losing every one of them to a 30-second Playwright timeout that
  // reads as the CHECKER dying (the rule this file opens with).
  if (hmDisclosure !== 'open') await readDisclosure(page, HEATMAP_NAV, { open: true });
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

  // THE WHOLE GRID, not a row count. Month and Week used to draw the identical
  // 7x24 picture — month, year and all shared one branch — so a row count alone
  // could not tell the two controls apart, and neither could a reader. The
  // fingerprint is every row label plus every cell's intensity band, which is
  // exactly what is on the screen.
  const gridPrint = () => page.evaluate(() =>
    Array.from(document.querySelectorAll('#audit-hm-body tr')).map((tr) =>
      tr.querySelector('th').textContent + '|'
      + Array.from(tr.querySelectorAll('i'))
        .map((i) => i.getAttribute('data-l')).join('')).join('\n'));
  const rowsIn = (print) => (print ? print.split('\n').length : 0);

  await page.click('#audit-hm-gran [data-g="week"]');
  await page.waitForTimeout(250);
  const weekGrid = await gridPrint();
  expect('Week granularity draws the seven days of one week', rowsIn(weekGrid), 7);
  await page.click('#audit-hm-gran [data-g="month"]');
  await page.waitForTimeout(250);
  const monGrid = await gridPrint();
  const mon = await page.evaluate(() => ({
    period: document.getElementById('audit-hm-period').textContent,
  }));
  const monName = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'][+lastDay.slice(5, 7) - 1];
  const monLen = new Date(Date.UTC(+lastDay.slice(0, 4), +lastDay.slice(5, 7), 0))
    .getUTCDate();
  expect(`Month granularity names the month (${monName} ${lastDay.slice(0, 4)})`,
    mon.period.includes(monName) && mon.period.includes(lastDay.slice(0, 4)), true);
  expect(`...over one row per DATE of that month, not seven weekday rows`,
    rowsIn(monGrid), monLen);
  expect('...and it is NOT the grid Week just drew — two controls, two pictures',
    monGrid !== weekGrid, true);
  await page.click('#audit-hm-gran [data-g="year"]');
  await page.waitForTimeout(250);
  const yearGrid = await gridPrint();
  expect('Year granularity names the year',
    await page.evaluate(() => document.getElementById('audit-hm-period').textContent),
    lastDay.slice(0, 4));
  expect('...over its twelve months, which is where the ladder stops going '
    + 'per-date because 365 rows is not a grid anyone reads', rowsIn(yearGrid), 12);
  expect('...and it is not the month grid either', yearGrid !== monGrid, true);

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
  const allGrid = await gridPrint();
  expect('...over the seven weekday rows, the one shape only All draws now',
    rowsIn(allGrid), 7);
  // Both are seven rows, so a count cannot separate them and the fingerprint has
  // to: All's rows are weekday AGGREGATES over the whole span, Week's are seven
  // dates. This is the pair the reshape leaves closest together.
  expect('...and All is not Week, though both are seven rows',
    allGrid !== weekGrid, true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  // @end-needs-usage-payload
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
    // csv: the file carries the DATA. Three columns are lossy on
    // screen — the commit is cut to nine characters and wears a Copy control,
    // the done cell is cut to the minute, the outcome is cut at seventy — and
    // the export used to take the cell text, Copy included.
    const head = csvFields(lines[0]);
    const iCommit = head.indexOf('commit');
    const iDone = head.indexOf('done');
    const iOut = head.indexOf('outcome');
    const iTask = head.indexOf('task');
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
    if (iOut >= 0) {
      // The third column this block indexes, asserted like its two
      // siblings above rather than left computed and unread. The header is
      // named once — a second "outcome" column would mean a future compact
      // column collided with the detail one and this index started
      // pointing at the lossy copy instead — and every exported value is
      // compared against the SAME detail row the page itself renders it
      // from, independent of the export code: outcome is the widest
      // free-text column here, so it is the one most likely to carry a
      // stray "Copy" control's own label if the export ever again took the
      // cell instead of the record behind it.
      expect('the header names "outcome" exactly once',
        head.filter((h) => h === 'outcome').length, 1);
      const outByTask = await page.evaluate((sg) => {
        const map = {};
        document.querySelectorAll(`tr.task[data-seg="${sg}"]`).forEach((t) => {
          const id = (t.querySelector('td.tid') || {}).textContent || '';
          const detail = t.nextElementSibling;
          const label = detail && [...detail.querySelectorAll('.dt-k')]
            .find((k) => k.textContent.trim() === 'outcome');
          const v = label && label.nextElementSibling;
          map[id.trim()] = v ? v.textContent.trim() : '';
        });
        return map;
      }, segName);
      expect('every exported outcome is the full text the detail row carries '
        + 'for that task, and never a stray "Copy" control label',
        iTask >= 0 && body.every((l) => {
          const f = csvFields(l);
          const tid = f[iTask];
          if (!tid || !(tid in outByTask)) return true; // taskless-phase row
          return f[iOut] === outByTask[tid] && !/Copy/.test(f[iOut] || '');
        }), true);
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

  // The Markdown twin, and it is here because of what it USED to do. Every other
  // download on this page went through one helper that revokes the object URL
  // late; this one built its own anchor and revoked SYNCHRONOUSLY right after
  // click(), defended by a comment, while a comment in the sibling part argued
  // the opposite. It now goes through the shared helper — and this check exists
  // because it was the only download site the gate did not drive, which is how
  // the two policies stayed contradictory without anything going red.
  //
  // WHAT THIS CANNOT SEE, MEASURED RATHER THAN ASSUMED. Putting the synchronous
  // revoke back and re-rendering leaves this check GREEN on this machine: the
  // failure it guards is a race, so it is machine- and timing-dependent, and a
  // pass here is not evidence that the timing is right. That is the whole reason
  // the timing rule is enforced STATICALLY instead — test__panel_page.py pins
  // `URL.revokeObjectURL` as occurring exactly once in the page, with the late
  // spelling. This check's job is narrower and still worth having: it proves the
  // path RUNS at all, and would catch an exception, a missing control, a wrong
  // filename or a decode that produced nothing.
  const mdBtn = await page.$('#audit-dl-md');
  const hasTwin = await page.evaluate(() => !!window.AUDIT_MD_B64);
  if (hasTwin && !mdBtn) {
    failures.push('FAIL the report carries a Markdown twin but no control to save it');
  } else if (mdBtn) {
    try {
      const wait = page.waitForEvent('download', { timeout: 15000 });
      await mdBtn.click();
      const dl = await wait;
      const text = readFileSync(await dl.path(), 'utf8');
      // Decoded, not merely non-empty: a revoke that lands too early yields a
      // download event and a truncated or empty file, which is exactly the
      // failure the late revoke prevents and the one a size check would miss.
      const heading = text.split('\n').find((l) => l.startsWith('# '));
      expect('the Markdown twin downloads and its first heading survives the decode',
             typeof heading === 'string' && heading.length > 2, true);
      expect('the Markdown twin is offered under the name the page carries',
             dl.suggestedFilename(),
             await page.evaluate(() => window.AUDIT_MD_NAME || 'audit-report.md'));
    } catch (e) {
      failures.push(`FAIL the Markdown twin produced no download (${String(e).split('\n')[0]})`);
    }
  } else notes.push('ok   (no Markdown twin in this report — twin download skipped)');

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
      // @needs-usage-payload — one site, for the same reason.
      expect('the usage CSV carries one row per recorded day', lines.length - 1, want);
      // @end-needs-usage-payload
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
  // is stubbed — a real dialog would hang a headless run — and the stub fires
  // `beforeprint` the way the dialog does, so the sheet is read with the table
  // cut into its per-phase parts, which is the shape paper gets. afterprint is
  // dispatched by hand, which is the same event a closed dialog fires.
  const pBtn = await page.$(`tr.seghead [data-segprint="${segName}"]`);
  if (!pBtn) {
    failures.push(`FAIL the "${segName}" seghead carries a CSV control but no Print control`);
  } else {
    await page.evaluate(() => {
      window.__printed = 0;
      window.print = () => {
        window.__printed++;
        window.dispatchEvent(new Event('beforeprint'));
      };
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
      // Painted, not merely styled: a row inside a `display:none` table still
      // computes as `table-row`, so reading `display` off the row would count a
      // whole hidden part as printed. A box that lays out has client rects.
      const vis = (el) => !!el && el.getClientRects().length > 0;
      const rows = [...document.querySelectorAll('table.phases tbody tr.phase')];
      return {
        shown: rows.filter(vis).length,
        inSeg: rows.filter((r) => vis(r) && r.getAttribute('data-seg') === s).length,
        wantSeg: rows.filter((r) => r.getAttribute('data-seg') === s).length,
        usageGone: !vis(document.getElementById('usage')),
        otherHeads: [...document.querySelectorAll('tr.seghead')]
          .filter((h) => vis(h) && h.getAttribute('data-seg') !== s).length,
        // A part of another segment would print its column headers over no
        // rows at all: the rows hide, the table around them does not.
        parts: document.querySelectorAll('table[data-paperpart]').length,
        otherParts: [...document.querySelectorAll('table[data-paperpart]')]
          .filter((t) => vis(t) && t.getAttribute('data-seg') !== s).length,
      };
    }, segName);
    await page.emulateMedia({ media: null });
    expect(`one segment on paper: every "${segName}" phase prints`,
      isolated.inSeg, isolated.wantSeg);
    expect('...and nothing from the other segments does',
      isolated.shown, isolated.inSeg);
    expect('...their headers included', isolated.otherHeads, 0);
    expect(`...and so are their tables (${isolated.parts} parts on the sheet)`,
      isolated.parts > 0 && isolated.otherParts === 0, true);
    expect('...and the other sections stay off the sheet', isolated.usageGone, true);
    await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
    await page.waitForTimeout(100);
    const after = await page.evaluate(() => ({
      seg: document.body.getAttribute('data-printseg'),
      dw: document.documentElement.scrollWidth,
      cw: document.documentElement.clientWidth,
      parts: document.querySelectorAll('table[data-paperpart]').length,
    }));
    expect('afterprint takes the stamp back off', after.seg, null);
    expect('...and joins the table back together', after.parts, 0);
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
//
// On paper the phases table is ONE TABLE PER PHASE: `beforeprint` moves the
// rows into parts and `afterprint` moves them back (report/exports.js says
// why). `emulateMedia` fires neither event, so this dispatches both by hand —
// the same two events the dialog and `page.pdf` fire — and reads the page in
// between, which is the only state paper ever sees.
const paperState = async () => {
  await page.evaluate(() => {
    const g = document.querySelector('table.phases');
    window.__screenRows = g && g.tBodies[0] ? [...g.tBodies[0].rows] : [];
    window.dispatchEvent(new Event('beforeprint'));
  });
  await page.emulateMedia({ media: 'print' });
  await page.setViewportSize({ width: 688, height: 900 });
  await page.waitForTimeout(100);
  const s = await page.evaluate(() => {
    // Painted, not merely styled — the per-segment block above says why: a
    // hidden part's rows would still compute as `table-row`.
    const vis = (el) => !!el && el.getClientRects().length > 0;
    const sec = document.getElementById('phases');
    const whole = sec.querySelector('table.phases:not([data-paperpart])');
    const parts = [...sec.querySelectorAll('table[data-paperpart]')];
    const rows = [...sec.querySelectorAll('tbody tr.phase')];
    const tasks = [...sec.querySelectorAll('tbody tr.task')];
    // One grid, not a stack of tables that each measured themselves: every
    // part's column headers start at the same x as the first part's.
    const lefts = (t) => [...t.tHead.rows[0].cells]
      .map((c) => Math.round(c.getBoundingClientRect().left)).join(',');
    const shown = parts.filter(vis);
    return {
      phases: rows.filter(vis).length,
      total: rows.length,
      tasks: tasks.filter(vis).length,
      totalTasks: tasks.length,
      parts: parts.length,
      onePhaseEach: parts.filter((t) => t.querySelectorAll('tr.phase').length === 1).length,
      headed: parts.filter((t) => t.tHead && vis(t.tHead)).length,
      wholeShown: vis(whole),
      grids: new Set(shown.map(lefts)).size,
      norows: vis(document.querySelector('tr.norows')),
      pmatch: [...document.querySelectorAll('.pmatch')].filter(vis).length,
      thead: shown.length ? getComputedStyle(shown[0].tHead).display : 'no part',
      wrapOverflow: getComputedStyle(whole.closest('.tablewrap')).overflowX,
      topbar: vis(document.querySelector('.topbar')),
    };
  });
  await page.emulateMedia({ media: null });
  await page.setViewportSize({ width: 1512, height: 945 });
  // ...and back: every row in the screen's one table, in the order it left, the
  // same nodes rather than copies of them, and no part left behind.
  s.back = await page.evaluate(() => {
    window.dispatchEvent(new Event('afterprint'));
    const g = document.querySelector('table.phases');
    const now = [...g.tBodies[0].rows];
    const was = window.__screenRows;
    const moved = now.length === was.length ? now.filter((r, i) => r !== was[i]).length : -1;
    delete window.__screenRows;
    return {
      moved,
      count: now.length,
      left: document.querySelectorAll('table[data-paperpart]').length,
      marked: g.hasAttribute('data-papercut'),
    };
  });
  return s;
};

const paper = await paperState();
expect('on paper every phase prints, filtered or not', paper.phases, paper.total);
expect('...and every task with them', paper.tasks, paper.totalTasks);
expect('...so the empty state never reaches the page it contradicts', paper.norows, false);
expect(`on paper each phase is a table of its own (${paper.parts} parts for `
  + `${paper.total} phases)`, paper.onePhaseEach === paper.total && paper.parts === paper.total, true);
expect("...the screen's one table stays off the sheet", paper.wholeShown, false);
expect('...every part carries the column headers', paper.headed, paper.parts);
expect('...and the parts line up as one grid (distinct column layouts)', paper.grids, 1);
expect(`afterprint puts every row back in the order it left (${paper.back.count} rows)`,
  paper.back.moved, 0);
expect('...and leaves no part and no mark behind',
  `${paper.back.left} ${paper.back.marked}`, '0 false');
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

// Between the print block and the polish checks, because the print block is the
// most invasive thing this file does to the page: two full PDF renders, four
// media-emulation swaps and two viewport changes. None of those SHOULD replace a
// node — and "should" is the word every silent page rebuild was written under.
await stillLive('after the print and PDF block, before the polish checks');

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
// --- the pinned selections ---------------------------------------------------------

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
//    The size comes from layout-baseline.mjs rather than from a literal here,
//    because every figure recorded below is a SHARE of it: two spellings of this
//    viewport is a recorded percentage of one screen compared against a
//    measurement of another, with nothing able to say so.
await page.setViewportSize(PHONE_VIEWPORT);
await page.waitForTimeout(250);
//    The first of the two recorded figures, taken BEFORE anything is opened. It is
//    read back with the disclosure's own state so a run cannot record the open bar
//    under the shut figure's name: everything above this line opens and closes
//    disclosures for a living, and a measurement of the wrong state is a baseline
//    that is wrong in the quiet direction forever.
//    ...and measured with EVERY phase status in view, which is the tallest the
//    chip row gets and so the state worth recording. Measured on the example: the
//    Done chip alone wraps the row and adds 28px to the bar. The script has
//    already reached this state by here on every report CI drives, so the line
//    changes nothing today — it is here so an edit ABOVE cannot quietly move the
//    basis under a number recorded from it, which is a shift a tolerance would
//    absorb rather than report.
const measured = {};
if (await page.$('#audit-view option[value="all"]')) {
  await page.selectOption('#audit-view', 'all');
  await page.waitForTimeout(250);
}
const barState = await page.evaluate(() => {
  const st = document.querySelector('.sectools');
  const d = document.querySelector('.fdetails');
  return { h: st.getBoundingClientRect().height, open: d ? d.open : null };
});
if (barState.open === true) {
  failures.push('FAIL the More-filters disclosure is already open where the shut filter '
    + 'bar is measured, so the recorded shut figure would be a measurement of the open one');
} else {
  measured.filterBarShutShare = share(barState.h, PHONE_VIEWPORT.height);
}

//    The stack pinned over the table, the lines the bars take and where an open
//    More filters lands are the layout matrix's, below, at every measured size
//    and in every state. What stays here is the PHONE's own: the open panel's
//    controls, and the two figures the layout baseline records at PHONE_VIEWPORT.
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

  //    The second recorded figure, and the one a missing filter-panel height bound moves. Read with the
  //    disclosure's state for the same reason the shut one is.
  const openState = await page.evaluate(() => {
    const st = document.querySelector('.sectools');
    return { h: st.getBoundingClientRect().height, open: document.querySelector('.fdetails').open };
  });
  if (openState.open !== true) {
    failures.push('FAIL clicking the More-filters summary did not open the disclosure, so '
      + 'the open filter bar could not be measured at all');
  } else {
    measured.filterBarOpenShare = share(openState.h, PHONE_VIEWPORT.height);
  }
  await page.click('.fdetails > summary');
  await page.waitForTimeout(150);
} else notes.push('ok   (this plan records no models or dates — phone panel check skipped)');

// --- the layout matrix: every measured size, in every state, in two fonts -----
//
// ONE method for one question - what the pinned chrome costs a reader of the
// table - asked at every size below, in every state a reader reaches, and in
// two fonts. A size or a state added here is asked every question; a question
// added here is asked of every cell; a failing cell is named by size, state and
// font.
//
// Sizes: a phone upright and on its side, a tablet upright, a small laptop, the
// laptop this file reads the page at, and a desktop. States, read off the page:
// every View option at rest, then the default view with one phase-status chip
// on, and with a search typed. Each cell asks:
//   lm1  the stack pinned over the table is no more than the layers pinned there
//   lm2  ...and leaves the table its share of the screen, whatever those are
//   lm3  the count's drawn text lies inside its bar
//   lm4  the pinned stack is within the budget of the size's viewport class
//   lm5  no control, chip or label of the chrome breaks inside a word
//   lm6  More filters, opened over the table, is on the screen and painted
//   lm7  ...and where it opens in the bar's flow, the bar holding it does not pin
//   lm8  nothing runs past its box, no control's text is cut off, and the page
//        is no wider than the screen
// and lm5 and lm8 again with More filters open.
//
// WHY NO CELL COUNTS LINES. How many lines a row of controls takes is a property
// of the font's metrics, and the page ships no font: it names a stack and takes
// whatever the machine resolves. The matrix used to hold the filter bar to one
// line at a laptop and the header's filter row to one line at a tablet; both
// held on the machine that wrote them, with no room to spare, and both failed on
// a CI runner whose default sans is wider. A line count asserted there is a
// claim about one font. What the page DOES control, and what a reader pays for,
// is asked instead: whether anything overflows or is cut off (lm8), whether a
// word is split (lm5), whether the count stays in its bar (lm3), and how much of
// the screen the pinned layers take (lm1, lm2, lm4). Wrapping onto another row
// is allowed wherever those hold - the stylesheet lays the rows out with a gap
// on purpose - and it is the budget, not a line count, that says when the rows
// have cost the reader too much.
//
// THE SECOND PASS. The same cells are read again with every element's
// font-family overridden to the first font of WIDE_FONTS that is installed and
// draws a sample line wider than the page's own font does on this machine (the
// pass prints both widths), so a layout that holds here has headroom against a
// runner's wider font rather than fitting this machine's to the pixel. Every label of that pass carries "wide
// font" and the font's name. Where no candidate is installed, or the widest one
// installed is no wider than the page's own font, the pass does not run and the
// output says so, in its notes and in the closing summary line; it is never
// reported as a pass it did not make.
//
// lm1 measures what a reader sees, not a sum of heights: scrolled into the table,
// from the top of the screen down its middle, the first point that is the table's
// own is where the pinned layers end - a hit-test sees whatever pins over the
// rows, including a layer nobody meant to make sticky. Its bound is the layers
// whose computed position is sticky in that same layout and that span the
// column the scan walks - the top bar, the section strip, the filter bar - plus
// STACK_SLACK_PX. Where TOPBAR_SCROLLS's query matches, a phone's screen, the top
// bar is not granted: it pinning there fails lm1 by name, however small it is.
// The slack is there because the scan steps whole pixels, and the bar sticks at
// an offset published rounded to a whole pixel (px() in page-state.js), so the
// first table pixel can sit up to a pixel and a half below the layers' exact sum. Anything else pinning clears that slack many
// times over.
//
// What that bound cannot see is the layers themselves growing, or a layer that
// should scroll pinning instead, because it grows with them. So lm2 holds the
// same measurement to a bound read off nothing on the page - STACK_CEILING_SHARE
// of the screen it is read on - and it is that ceiling, not the relative arm, that
// stands for a report the layout baseline is not about (outside this checkout, or
// a scratch render), where judge() records nothing and compares nothing. The
// basis of the ceiling: the pinned layers are chrome over the rows a reader
// scrolled down to read, so the table keeps at least half of the screen. Past
// that the chrome is the page and the table is what peeks out under it. It is a
// destination bound, not a ratchet: how far a committed report's bar moved is the
// relative arm's question, asked through the figures recorded above.
//
// lm4 is the stricter, per-class form of the same bound: STACK_BUDGET, stated
// once below, gives each viewport class the share of its screen the pinned
// layers may take, and viewportClass() derives a size's class from the size
// itself, so a size added to the list is budgeted without a row of its own.
// The shares are what each class is designed to spend - a desktop pins every
// layer on one row each; a laptop or tablet may wrap the filter bar, and the
// header's filter row, onto a second row; a phone pins only the strip and the
// filter bar, which wraps the most - and every class must be reached by some
// size, or the run fails naming the class nothing measured.
// lm3 reads the count's lines off its text's own client rects, which is what a
// reader sees, and holds every one to the bar's content box: the count may wrap
// onto its own row or wrap its own words, but never run out of the card.
// lm5 reads each word's own rects: a word drawn on two lines was split inside
// itself, which no font makes legible. A word is a run of letters and digits, so
// a break at a space, a hyphen or a slash is a row break and not a split word.
// lm8 holds every in-flow child of the bar, the header's filter row, the top
// bar's actions and the table's head to its container's content box; every
// field to the width of what it shows - a select to the width it takes holding
// only its chosen option, a date field to its own natural width, an empty search
// field to its placeholder - and every button and chip to its own content; and
// the page to the screen's width.
const STACK_SLACK_PX = 2;
const STACK_CEILING_SHARE = 0.5;
const STACK_TABLE_SHARE = +(1 - STACK_CEILING_SHARE).toFixed(2);
// The share of the screen the pinned stack may take, per viewport class.
// The rule the shares aim at: the largest stack the class's cells draw in
// either font, plus one row of headroom, over the class's screen height. They
// were set before that was measured and are not computed from it, so meeting
// the rule is not assumed: the measurement below says which classes do, and
// the phone does not. A share is a fraction of the HEIGHT while
// the stack is a sum of rows, so a tall screen spends a smaller share on the
// same rows: the tablet cell is portrait and pins more pixels than the laptop
// cell does, yet a smaller part of its screen, which is why the tablet's share
// is the smaller of the two.
// Measured 2026-11-17 on macOS, as headroom = budget - stack at each class's
// tightest cell over both passes; re-derive it by running
//   node tools/check-report-interactive.mjs <report> 2>&1 | grep lm4
// over examples/acme-store/acme-store-audit.html and docs/demo-large.html and
// taking the smallest gap per class between "<stack>px against <budget>px" -
// a wide-font cell's label carries "[wide font: <name>]", and the wide font
// here was Verdana. Each line names the pass its cell was read in:
//   phone    27px at 844x390, both passes, either report, a status chip on
//            or a search typed (stack 148px, budget 175px)
//   laptop   37px at 1024x768, both passes, demo-large, a status chip on
//            (270px, 307px)
//   tablet   52px at 834x1194, a status chip on or a search typed: the
//            wide-font pass in either report, the page's own font in
//            acme-store only (306px, 358px)
//   desktop  56px at 1920x1080, wide-font pass only, demo-large, a status
//            chip on or a search typed (214px, 270px) - the page's own font
//            pins 182px there, so the extra 32px is a row the desktop wraps
//            only in the wider font.
// What one more row costs at the phone was read in the wide font at 844x390
// itself, not carried over from the desktop: the filter bar's rows sit 8px
// apart, its shortest item is 19.4px tall and its count 24px, so a further
// row costs at least 27.4px and, holding the count, 32px. The check prints
// none of that; it was read off the bar's own boxes, twice with a gap, by
//   [...document.querySelectorAll('.sectools > *')].map((e) => e.getBoundingClientRect())
// in a page sized 844x390 with the wide-font pass's override applied.
// So the phone has LESS than a row of headroom: its 27px is under the
// cheapest row the bar can add there, and a phone whose filter bar wraps one
// more row fails lm4. That is a fact of the phone's budget at 0.45, stated
// here rather than met; the laptop, tablet and desktop each clear 32px.
// Changing a share means re-measuring this, not editing a figure above.
const STACK_BUDGET = { phone: 0.45, tablet: 0.3, laptop: 0.4, desktop: 0.25 };
// A phone is where the top bar scrolls (TOPBAR_SCROLLS, read by the page's own
// matchMedia); past that the class is the width's: under 64rem a tablet, under
// 100rem a laptop, a desktop beyond.
const viewportClass = (size, phone) => (phone ? 'phone'
  : size.width < 1024 ? 'tablet' : size.width < 1600 ? 'laptop' : 'desktop');
const LAYOUT_SIZES = [
  { width: PHONE_VIEWPORT.width, height: 844 },
  { width: 844, height: PHONE_VIEWPORT.width },
  { width: 834, height: 1194 },
  { width: 1024, height: 768 },
  { width: 1512, height: 945 },
  { width: 1920, height: 1080 },
];
// Wide sans fonts, in the order a pass reaches for them: Verdana is on macOS
// and Windows; DejaVu Sans, the usual Linux default, and Bitstream Vera Sans,
// its parent, are the fallbacks where it is not. Which one is wider than the
// page's own font is measured, never assumed (wideFontsHere()).
const WIDE_FONTS = ['Verdana', 'DejaVu Sans', 'Bitstream Vera Sans'];
// The layers that may pin over the table, by the names a label prints.
const STACK_LAYERS = [['top bar', '.topbar'], ['strip', '.snav'], ['filter bar', '.sectools']];
// Where the top bar scrolls instead: the query is written here and not read
// off the stylesheet, because the fault it is held against is that rule going
// missing, and a query read off a missing rule asks nothing.
const TOPBAR_SCROLLS = ['top bar', '(max-width:52rem),(max-height:32rem)'];
// The chrome lm5 and lm8 read: the pinned layers, the header's own rows and the
// table's head. `open` adds the More-filters panel.
const CHROME = ['.topbar', '.snav', '.sectools', '.tablehead'];
const readChrome = (open) => page.evaluate(([roots, withPanel]) => {
  const shown = (n) => !!n && n.getClientRects().length > 0
    && (!n.checkVisibility || n.checkVisibility());
  const inFlow = (box) => [...(box ? box.children : [])]
    .filter((k) => shown(k) && getComputedStyle(k).position !== 'absolute');
  // A node inside a box clipped to a pixel is said to a screen reader and drawn
  // to nobody, so neither its lines nor its words are on the screen.
  const drawn = (n, upTo) => {
    for (let p = n.parentElement; p && p !== upTo; p = p.parentElement) {
      const b = p.getBoundingClientRect();
      if (b.width <= 1 || b.height <= 1 || !shown(p)) return false;
    }
    return true;
  };
  const contentBox = (el) => {
    const cs = getComputedStyle(el);
    const b = el.getBoundingClientRect();
    return {
      left: b.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
      right: b.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight),
      top: b.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop),
      bottom: b.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom),
    };
  };
  // Half a pixel either way: edges land on fractional pixels, and a box laid
  // flush against the padding edge reads a rounding error past it.
  const outside = (r, box) => r.left < box.left - 0.5 || r.right > box.right + 0.5
    || r.top < box.top - 0.5 || r.bottom > box.bottom + 0.5;
  const named = (k) => (k.id ? `#${k.id}`
    : `${k.tagName.toLowerCase()}${[...k.classList].map((c) => `.${c}`).join('')}`);
  const textRects = (el) => {
    const rects = [];
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!drawn(n, el.parentElement)) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      rects.push(...[...r.getClientRects()].filter((x) => x.width > 0));
    }
    return rects;
  };
  const rootEls = roots.concat(withPanel ? ['.filterpanel'] : [])
    .map((s) => document.querySelector(s)).filter(shown);
  // lm5: a word whose own rects sit on two lines was split inside itself.
  const split = [];
  for (const root of rootEls) {
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!drawn(n, root.parentElement)) continue;
      const re = /[\p{L}\p{N}]+/gu;
      for (let m = re.exec(n.data); m; m = re.exec(n.data)) {
        const r = document.createRange();
        r.setStart(n, m.index);
        r.setEnd(n, m.index + m[0].length);
        const tops = new Set([...r.getClientRects()].filter((x) => x.width > 0)
          .map((x) => Math.round(x.top)));
        if (tops.size > 1) split.push(`${named(n.parentElement)} "${m[0]}"`);
      }
    }
  }
  // lm8: children out of their row, fields cut short, buttons overrun.
  const rows = ['.sectools', '.topbar .gfilters', '.topbar .tb-actions', '.tablehead']
    .concat(withPanel ? ['.filterpanel'] : [])
    .map((s) => document.querySelector(s)).filter(shown);
  // A box that scrolls on an axis holds its rows past its edge on purpose -
  // the More-filters panel is capped in height and scrolls the rest - so only
  // the axis it does not scroll is held to its edges.
  const spill = rows.flatMap((row) => {
    const box = contentBox(row);
    const scrollsY = /auto|scroll/.test(getComputedStyle(row).overflowY);
    const held = scrollsY ? { ...box, top: -Infinity, bottom: Infinity } : box;
    return inFlow(row).filter((k) => outside(k.getBoundingClientRect(), held))
      .map((k) => `${named(k)} out of ${named(row)}`);
  });
  const ctx = document.createElement('canvas').getContext('2d');
  const cut = [];
  for (const root of rootEls) {
    for (const el of root.querySelectorAll('input, select, button, summary, .fchip, .tf-chip')) {
      if (!shown(el)) continue;
      const w = el.getBoundingClientRect().width;
      if (el.tagName === 'SELECT' || (el.tagName === 'INPUT' && el.type === 'date')) {
        // The width the same control takes unconstrained, holding only what it
        // shows now: a select's chosen option, a date field's own fields.
        const twin = el.cloneNode(el.tagName !== 'SELECT');
        if (el.tagName === 'SELECT' && el.selectedOptions[0]) {
          twin.append(el.selectedOptions[0].cloneNode(true));
        }
        twin.style.cssText = 'position:absolute;visibility:hidden;width:auto;'
          + 'min-width:0;max-width:none;flex:none';
        el.parentElement.append(twin);
        const need = twin.getBoundingClientRect().width;
        twin.remove();
        if (need > w + 0.5) cut.push(`${named(el)} ${Math.round(w)}px of ${Math.round(need)}px`);
      } else if (el.tagName === 'INPUT') {
        if (el.value || !el.placeholder) continue;
        const cs = getComputedStyle(el);
        ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        const need = ctx.measureText(el.placeholder).width;
        const room = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
        if (need > room + 0.5) {
          cut.push(`${named(el)} placeholder ${Math.round(need)}px in ${Math.round(room)}px`);
        }
      } else if (el.scrollWidth > el.clientWidth + 1) {
        cut.push(`${named(el)} ${el.clientWidth}px of ${el.scrollWidth}px`);
      }
    }
  }
  const st = document.querySelector('.sectools');
  const count = document.getElementById('audit-count');
  const top = document.querySelector('.topbar');
  const sort = document.getElementById('audit-sort');
  const head = document.querySelector('.tablehead');
  const bar = contentBox(st);
  return {
    countOut: textRects(count).filter((r) => outside(r, bar)).length,
    room: Math.round(bar.right - bar.left),
    split,
    spill,
    cut,
    pageWide: document.scrollingElement.scrollWidth,
    screenWide: window.innerWidth,
    barPx: Math.round(st.getBoundingClientRect().height),
    sortDrawn: !!sort && !!head && shown(sort) && head.contains(sort),
    topPx: Math.round(top.getBoundingClientRect().height),
  };
}, [CHROME, !!open]);
// Scrolled into the table, the hit-test and the layers it is held to, read in
// one pass so the bound and the measurement come from one layout.
const stackInTable = () => page.evaluate(() => {
  const t = document.querySelector('table.phases');
  window.scrollTo(0, window.scrollY + t.getBoundingClientRect().top + 10);
}).then(() => page.waitForTimeout(300)).then(() => page.evaluate(([layers, scrolls]) => {
  const t = document.querySelector('table.phases');
  const wrap = t.closest('.tablewrap') || t;
  const x = Math.round(window.innerWidth / 2);
  let stack = null;
  for (let y = 0; stack === null && y < window.innerHeight; y += 1) {
    const at = document.elementFromPoint(x, y);
    if (at && wrap.contains(at)) stack = y;
  }
  // A layer is held to only where it pins over the column the scan walks: on
  // a wide screen the section strip is a sidebar, sticky and as tall as its
  // links, beside the table rather than over it.
  const pinned = layers.map(([name, sel]) => {
    const el = document.querySelector(sel);
    const r = el ? el.getBoundingClientRect() : null;
    return { name, px: r ? r.height : 0,
             over: !!el && getComputedStyle(el).position === 'sticky'
               && r.left <= x && r.right >= x };
  }).filter((l) => l.over);
  // Where the screen is a phone's, the top bar is not a layer the bound may
  // grant: it pinning there is the fault, and counting it in would grow the
  // bound with it.
  const phone = window.matchMedia(scrolls[1]).matches;
  const refused = phone ? pinned.filter((l) => l.name === scrolls[0]) : [];
  return { stack, pinned: pinned.filter((l) => refused.indexOf(l) < 0), refused, phone };
}, [STACK_LAYERS, TOPBAR_SCROLLS]));
const judgeStack = (id, cell, size, m) => {
  if (id === 'lm1') {
    expect(`lm1 ${cell}: where ${TOPBAR_SCROLLS[1]} matches, the top bar scrolls rather `
      + `than pinning over the table (${m.phone ? 'the query matches' : 'the query does not match'}; `
      + `pinned there and refused: ${m.refused.map((l) => `${l.name} ${l.px.toFixed(1)}px`).join(', ') || 'nothing'})`,
      m.refused.length, 0);
  }
  const bound = m.pinned.reduce((sum, l) => sum + l.px, 0) + STACK_SLACK_PX;
  const parts = m.pinned.map((l) => `${l.name} ${l.px.toFixed(1)}`).join(' + ') || 'nothing';
  const ceiling = Math.floor(size.height * STACK_CEILING_SHARE);
  const pct = share(m.stack, size.height);
  if (id === 'lm7') {
    expect(`lm7 ${cell}: with More filters open in the bar's flow the bar does not pin, and `
      + `the stack is no more than the layers still pinned (${m.stack}px against `
      + `${bound.toFixed(1)}px = ${parts} + slack ${STACK_SLACK_PX}; ${pct}% of the screen)`,
      m.stack <= bound && !m.pinned.some((l) => l.name === 'filter bar'), true);
    return;
  }
  expect(`lm1 ${cell}: the stack pinned over the table is no more than the layers pinned `
    + `there (${m.stack}px against ${bound.toFixed(1)}px = ${parts} + slack `
    + `${STACK_SLACK_PX}; ${pct}% of the screen)`,
    m.stack <= bound, true);
  expect(`lm2 ${cell}: the table keeps at least ${STACK_TABLE_SHARE} of the screen (${m.stack}px `
    + `pinned against a ${ceiling}px ceiling = ${STACK_CEILING_SHARE} of ${size.height}px)`,
    m.stack <= ceiling, true);
  const klass = viewportClass(size, m.phone);
  const budget = Math.floor(size.height * STACK_BUDGET[klass]);
  expect(`lm4 ${cell}: the pinned stack is within the ${klass} budget (${m.stack}px against `
    + `${budget}px = ${STACK_BUDGET[klass]} of ${size.height}px; ${parts})`,
    m.stack <= budget, true);
  return klass;
};
// The font a run of the page's text is drawn in, asked of the renderer: the
// family it actually used, not the stack the stylesheet names.
const drawnFont = async (selector) => {
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
    return fonts.map((f) => f.familyName).join(' + ') || 'no font reported';
  } catch (e) {
    return `unknown (${e.message.split('\n')[0]})`;
  } finally {
    await cdp.detach();
  }
};
// Which WIDE_FONTS are installed, and how wide a sample line is in each against
// the page's own font. Installed means the name changes what a canvas draws over
// two different generic fallbacks, so a missing font is never read as present.
const wideFontsHere = () => page.evaluate((names) => {
  const ctx = document.createElement('canvas').getContext('2d');
  const sample = 'Filter phases & tasks by text - Phase status: In progress';
  const wide = (family) => { ctx.font = `15px ${family}`; return ctx.measureText(sample).width; };
  const present = (n) => wide(`"${n}",monospace`) !== wide('monospace')
    && wide(`"${n}",serif`) !== wide('serif');
  const own = getComputedStyle(document.querySelector('.sectools .tbl')).fontFamily;
  return { own: Math.round(wide(own)),
           fonts: names.map((n) => ({ name: n, present: present(n),
                                      px: Math.round(wide(`"${n}",monospace`)) })) };
}, WIDE_FONTS);
const FONT_PASSES = [];
{
  const hasPanel = !!(await page.$('.fdetails > summary')) && !!(await page.$('.filterpanel'));
  const viewWas = await page.$eval('#audit-view', (s) => s.value);
  const viewOpts = await page.$$eval('#audit-view option', (os) => os.map((o) => o.value));
  // A row as tall as two screens at the foot of the table, for the matrix's
  // length only: a narrowed table can be shorter than the chrome over it, and
  // then no point under the stack is the table and the stack is unmeasured.
  // The chrome is the subject; the table only has to be there to be covered.
  await page.evaluate(() => {
    const body = document.querySelector('table.phases tbody');
    const tr = document.createElement('tr');
    tr.setAttribute('data-lm-spacer', '');
    tr.innerHTML = '<td colspan="99" style="height:200vh"></td>';
    body.append(tr);
  });
  await page.selectOption('#audit-view', seg0.defaultView);
  await page.waitForTimeout(200);
  const probe = await page.evaluate(() => {
    const chip = [...document.querySelectorAll('#audit-phase-status .fchip')]
      .find((c) => c.getClientRects().length > 0);
    if (chip) chip.setAttribute('data-lm-chip', '');
    const row = [...document.querySelectorAll('table.phases tbody tr.phase')]
      .find((r) => r.style.display !== 'none');
    const id = row && row.querySelector('.mono');
    return { chip: !!chip, term: id ? id.textContent.trim() : null };
  });
  const states = viewOpts.map((v) => ({ name: `View=${v} at rest`, view: v, rest: true }));
  if (probe.chip) states.push({ name: `View=${seg0.defaultView}, one phase-status chip on`, view: seg0.defaultView, chip: true });
  else failures.push('FAIL lm the default view draws no phase-status chip, so no cell was read with one on');
  if (probe.term) states.push({ name: `View=${seg0.defaultView}, searched for ${probe.term}`, view: seg0.defaultView, term: probe.term });
  else failures.push('FAIL lm the default view draws no phase row, so no cell was read with a search typed');
  let cells = 0, sortCells = 0;
  const classesRead = new Set();
  const runPass = async (tag) => {
    for (const s of states) {
      await page.setViewportSize({ width: 1512, height: 945 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.selectOption('#audit-view', s.view);
      if (s.chip) await page.click('[data-lm-chip]');
      if (s.term) await page.fill('#audit-q', s.term);
      await page.waitForTimeout(350);
      for (const size of LAYOUT_SIZES) {
        const cell = `${size.width}x${size.height}${tag} ${s.name}`;
        await page.setViewportSize(size);
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForTimeout(250);
        const at = await readChrome(false);
        cells += 1;
        if (at.sortDrawn) sortCells += 1;
        expect(`lm3 ${cell}: the count's drawn text lies inside its bar (${at.countOut} line(s) `
          + `outside a ${at.room}px bar; bar ${at.barPx}px)`, at.countOut, 0);
        expect(`lm5 ${cell}: no control, chip or label of the chrome breaks inside a word `
          + `(split: ${at.split.join(', ') || 'nothing'})`, at.split.length, 0);
        expect(`lm8 ${cell}: nothing runs past its box, no control's text is cut off, and the `
          + `page is no wider than the screen (outside: ${at.spill.join(', ') || 'nothing'}; `
          + `cut off: ${at.cut.join(', ') || 'nothing'}; page ${at.pageWide}px on a `
          + `${at.screenWide}px screen; top bar ${at.topPx}px)`,
          at.spill.length === 0 && at.cut.length === 0 && at.pageWide <= at.screenWide, true);
        const shut = await stackInTable();
        if (shut.stack === null) {
          failures.push(`FAIL lm1 ${cell}: scrolled into the table, no point down the middle of `
            + 'the screen is the table - the stack over it could not be measured');
        } else classesRead.add(judgeStack('lm1', cell, size, shut));
        if (!hasPanel) continue;
        await page.click('.fdetails > summary');
        await page.waitForTimeout(350);
        const open = await page.evaluate(() => {
          const p = document.querySelector('.filterpanel');
          const b = p.getBoundingClientRect();
          const x = b.left + b.width / 2;
          const painted = [b.top + 4, b.bottom - 4].every((y) => {
            const hit = document.elementFromPoint(x, y);
            return Boolean(hit && p.contains(hit));
          });
          return { open: document.querySelector('.fdetails').open,
                   inFlow: getComputedStyle(p).position === 'static',
                   top: Math.round(b.top), bottom: Math.round(b.bottom),
                   left: Math.round(b.left), right: Math.round(b.right),
                   w: innerWidth, h: innerHeight, painted };
        });
        expect(`lm6 ${cell}: More filters opened over the table lies within the screen and is `
          + `painted top and bottom (open ${open.open}, box ${open.left},${open.top}-`
          + `${open.right},${open.bottom} on ${open.w}x${open.h})`,
          open.open && open.top >= 0 && open.bottom <= open.h && open.left >= 0
            && open.right <= open.w && open.painted, true);
        const inside = await readChrome(true);
        expect(`lm5 with More filters open, ${cell}: no control, chip or label of the chrome or `
          + `the panel breaks inside a word (split: ${inside.split.join(', ') || 'nothing'})`,
          inside.split.length, 0);
        expect(`lm8 with More filters open, ${cell}: nothing runs past its box, no control's `
          + `text is cut off, and the page is no wider than the screen (outside: `
          + `${inside.spill.join(', ') || 'nothing'}; cut off: ${inside.cut.join(', ') || 'nothing'}; `
          + `page ${inside.pageWide}px on a ${inside.screenWide}px screen)`,
          inside.spill.length === 0 && inside.cut.length === 0
            && inside.pageWide <= inside.screenWide, true);
        if (open.open && open.inFlow) {
          const m = await stackInTable();
          if (m.stack === null) {
            failures.push(`FAIL lm7 ${cell}: scrolled into the table with More filters open, no `
              + 'point down the middle of the screen is the table');
          } else judgeStack('lm7', cell, size, m);
        }
        await page.click('.fdetails > summary');
        await page.waitForTimeout(150);
      }
      await page.setViewportSize({ width: 1512, height: 945 });
      if (s.chip) await page.click('[data-lm-chip]');
      if (s.term) await page.fill('#audit-q', '');
      await page.waitForTimeout(300);
    }
  };
  // Pass one, in the page's own font.
  await page.setViewportSize({ width: 1512, height: 945 });
  const ownFont = await drawnFont('.sectools .tbl');
  FONT_PASSES.push(`page's own font (${ownFont})`);
  notes.push(`ok   (layout matrix, first pass: the page's own font, drawn in ${ownFont})`);
  await runPass('');
  const firstCells = cells;
  // Pass two, in the first installed wide font - when there is one wider than
  // the page's own, which is the only thing that pass is for.
  const here = await wideFontsHere();
  const said = here.fonts.map((f) => (f.present ? `${f.name} ${f.px}px` : `${f.name} not installed`))
    .join(', ');
  const installed = here.fonts.filter((f) => f.present);
  const wide = installed.find((f) => f.px > here.own);
  if (!installed.length) {
    FONT_PASSES.push(`wide-font pass NOT RUN - none of ${WIDE_FONTS.join(', ')} is installed`);
    notes.push(`ok   (layout matrix, wide-font pass NOT RUN: none of ${WIDE_FONTS.join(', ')} `
      + 'is installed, so the layout was read in one font only)');
  } else if (!wide) {
    FONT_PASSES.push('wide-font pass NOT RUN - no installed candidate is wider than the page\'s '
      + 'own font');
    notes.push(`ok   (layout matrix, wide-font pass NOT RUN: no installed candidate draws a `
      + `sample line wider than the ${here.own}px it takes in the page's own font, so a second `
      + `pass would repeat the first; candidates: ${said})`);
  } else {
    const style = await page.addStyleTag({ content: ':root,*,*::before,*::after'
      + `{font-family:"${wide.name}",sans-serif!important}` });
    await page.waitForTimeout(200);
    const wideDrawn = await drawnFont('.sectools .tbl');
    FONT_PASSES.push(`wide font ${wide.name} (${wideDrawn})`);
    notes.push(`ok   (layout matrix, wide-font pass: ${wide.name}, drawn in ${wideDrawn}; a `
      + `sample line is ${wide.px}px in it against ${here.own}px in the page's own font; `
      + `candidates: ${said})`);
    expect(`lm the wide-font pass draws the page in the font it names (asked for ${wide.name}, `
      + `drawn in ${wideDrawn})`, wideDrawn.split(' + ')[0], wide.name);
    await runPass(` [wide font: ${wide.name}]`);
    await style.evaluate((n) => n.remove());
    await page.waitForTimeout(200);
  }
  notes.push(`ok   (the layout matrix read ${cells} cells: ${LAYOUT_SIZES.length} sizes by `
    + `${states.length} states, ${cells === firstCells ? 'in one font' : 'in two fonts'})`);
  for (const k of Object.keys(STACK_BUDGET)) {
    if (!classesRead.has(k)) {
      failures.push(`FAIL lm4 no size in the layout list is a ${k} by viewportClass(), so the `
        + `${k} budget (${STACK_BUDGET[k]} of the screen) was never asked`);
    }
  }
  // Whether the Sort select was drawn in the phases table's head in every cell
  // the matrix measured. The select is drawn only for a plan that pins a phase,
  // and the rows' execution ranks are the other half of that same plan fact,
  // emitted on their own: ranks with no select drawn is a pinned plan whose
  // ordering control is missing, or has gone back into the pinned filter bar.
  const ranked = await page.$$eval('table.phases tr.phase[data-porder]', (rs) => rs.length);
  if (ranked > 0 && sortCells < cells) {
    failures.push(`FAIL lm the plan pins a phase (${ranked} rows carry an execution rank) but `
      + `the Sort select was drawn in the phases table's head in ${sortCells} of the ${cells} `
      + 'cells read');
  } else if (ranked > 0) {
    notes.push(`ok   (the Sort select was in the phases table's head in every cell: ${ranked} `
      + 'rows carry an execution rank)');
  } else {
    notes.push('ok   (this plan pins no phase, so the Sort select is not drawn and no cell '
      + 'measured the table\'s head with it - that coverage is absent from this run)');
  }
  await page.evaluate(() => {
    for (const n of document.querySelectorAll('[data-lm-spacer]')) n.remove();
    for (const n of document.querySelectorAll('[data-lm-chip]')) n.removeAttribute('data-lm-chip');
  });
  await page.selectOption('#audit-view', viewWas);
  await page.setViewportSize(PHONE_VIEWPORT);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
}

// --- the relative arm: what this document's layout was recorded at ------------
//
// The stack check above is ABSOLUTE: shut or open, no layer but the ones its
// bound names may pin over the table, and never more than the ceiling's share of
// the screen, whatever it did yesterday.
// This asks the other question — has THIS document's filter chrome moved from the
// figure this repository recorded — and the two are reported on separate lines so
// a reader knows which they have.
//
// It is here rather than beside the bar because it judges figures taken on both
// sides of the disclosure, and because a document with no More-filters panel still
// has a shut bar worth recording: the `else` above skips a check, not a document.
// `file` and not `path`: both resolve to the same document, and the one the caller
// typed is the one that belongs in a command printed back to them.
const layout = judge({ reportPath: file, measured, viewport: PHONE_VIEWPORT });
for (const f of layout.failures) failures.push(`FAIL ${f}`);
for (const n of layout.notes) notes.push(`ok   ${n}`);

//    Portrait paper is ~688px, INSIDE the 52rem breakpoint — so every rule added
//    for a phone above is also a rule about paper. These two are inert there only
//    because the whole bar is dropped from the printed page; if that ever stops
//    being true, a filter panel prints in the middle of the plan.
await page.setViewportSize({ width: 688, height: 900 });
await page.emulateMedia({ media: 'print' });
await page.waitForTimeout(150);
// --- on paper: the print rules -----------------------------------------------------

const onPaper = await page.evaluate(() => {
  const st = document.querySelector('.sectools');
  const fp = document.querySelector('.filterpanel');
  const th = document.querySelector('.tablehead');
  const gone = (el) => !el || getComputedStyle(el).display === 'none' || el.offsetParent === null;
  return { bar: gone(st), panel: gone(fp), head: !!th, headGone: gone(th) };
});
await page.emulateMedia({ media: null });
await page.setViewportSize({ width: 1512, height: 945 });
expect('the filter bar never reaches portrait paper, where its phone rules also apply', onPaper.bar, true);
expect('...nor the panel inside it', onPaper.panel, true);
expect('...nor the phases table\'s head, whose Sort and expand-all do nothing on paper '
  + `(the head rendered: ${onPaper.head})`, onPaper.head && onPaper.headGone, true);

// --- interaction states: each control's own box ------------------------------
//
// A rest-state snapshot cannot see a hover or focus rule that stopped matching,
// and a focus ring drawn only as box-shadow is erased by forced-colours mode,
// which drops every shadow. So each control is put in its state and its OWN
// computed style compared with its rest: at least one property its rule sets
// must have moved. A focus rule must also leave an outline standing under
// forced colours, which is what that mode repaints instead of a shadow.
// `needs` opens whatever the control lives behind and returns its undo.
{
  const READ = ['outlineStyle', 'outlineWidth', 'borderTopColor', 'boxShadow',
    'backgroundColor', 'color', 'transform', 'filter'];
  const openPanel = async () => {
    await page.click('.fdetails > summary');
    await page.waitForTimeout(250);
    return () => page.click('.fdetails > summary');
  };
  const expandAll = async () => {
    await page.click('#audit-expand');
    await page.waitForTimeout(300);
    return () => page.click('#audit-expand');
  };
  const STATES = [
    { id: 'is1', sel: '#audit-q', how: 'focus', sets: ['borderTopColor', 'boxShadow', 'outlineStyle'] },
    { id: 'is2', sel: '.frow input[type=date]', how: 'focus', needs: openPanel,
      sets: ['borderTopColor', 'boxShadow', 'outlineStyle'] },
    { id: 'is3', sel: '.gfilters select', how: 'focus', sets: ['borderTopColor', 'boxShadow', 'outlineStyle'] },
    { id: 'is4', sel: '.gfilters input[type=date]', how: 'focus',
      sets: ['borderTopColor', 'boxShadow', 'outlineStyle'] },
    { id: 'is5', sel: '.tablehead .btn:not(.btn-primary)', how: 'hover',
      sets: ['borderTopColor', 'backgroundColor', 'transform', 'boxShadow'] },
    { id: 'is6', sel: '.btn-primary', how: 'hover', sets: ['filter'] },
    { id: 'is7', sel: '#audit-phase-status .fchip:not(.on)', how: 'hover', sets: ['borderTopColor', 'transform'] },
    { id: 'is8', sel: '.fdetails > summary', how: 'hover', sets: ['borderTopColor', 'backgroundColor'] },
    { id: 'is9', sel: '.tf-chip:not(.on)', how: 'hover', needs: expandAll, sets: ['borderTopColor', 'transform'] },
    { id: 'is10', sel: '.snav a:not([aria-current="true"])', how: 'hover', sets: ['color', 'backgroundColor'] },
    // The same links drawn as the strip under the bar, where shell.css gives
    // them a presentation of their own (a bottom border, not a left one), so
    // the hover is read again in that box rather than assumed from the column.
    { id: 'is11', sel: '.snav a:not([aria-current="true"])', how: 'hover', at: { width: 1000, height: 800 },
      sets: ['color', 'backgroundColor'] },
  ];
  const styleOf = (loc) => loc.evaluate((el, props) => {
    const cs = getComputedStyle(el);
    return Object.fromEntries(props.map((p) => [p, cs[p]]));
  }, READ);
  const settle = async () => {
    await page.mouse.move(1, 1);
    await page.evaluate(() => document.activeElement && document.activeElement.blur());
    await page.waitForTimeout(350);    // > --dur, so a transition has finished
  };
  await page.setViewportSize({ width: 1512, height: 945 });
  await page.evaluate(() => window.scrollTo(0, 0));
  for (const s of STATES) {
    if (s.at) await page.setViewportSize(s.at);
    const undo = s.needs ? await s.needs() : null;
    const loc = page.locator(s.sel).filter({ visible: true }).first();
    if (!(await loc.count())) {
      failures.push(`FAIL ${s.id} no visible ${s.sel} to put in its ${s.how} state - the `
        + 'interaction rule for it could not be checked');
      if (undo) await undo();
      if (s.at) await page.setViewportSize({ width: 1512, height: 945 });
      continue;
    }
    await loc.scrollIntoViewIfNeeded();
    await settle();
    const rest = await styleOf(loc);
    if (s.how === 'hover') await loc.hover();
    else await loc.focus();
    await page.waitForTimeout(350);
    const on = await styleOf(loc);
    const moved = s.sets.filter((p) => rest[p] !== on[p]);
    let forced = 'n/a';
    if (s.how === 'focus') {
      await page.emulateMedia({ forcedColors: 'active' });
      await loc.focus();
      await page.waitForTimeout(100);
      const fc = await styleOf(loc);
      forced = fc.outlineStyle !== 'none' && parseFloat(fc.outlineWidth) >= 1 ? 'outline' : 'no outline';
      await page.emulateMedia({ forcedColors: 'none' });
    }
    expect(`${s.id} ${s.sel} in its ${s.how} state changes its own box (${moved.join(',') || 'nothing'} moved)`
      + (s.at ? ` at ${s.at.width}x${s.at.height}` : '')
      + (s.how === 'focus' ? ' and keeps an outline under forced colours' : ''),
      `${moved.length > 0}/${forced}`, `true/${s.how === 'focus' ? 'outline' : 'n/a'}`);
    await settle();
    if (undo) await undo();
    if (s.at) await page.setViewportSize({ width: 1512, height: 945 });
  }

  // The More-filters summary is NAMED by its text, so the count it shows is the
  // count a screen reader hears. Asked of the browser's accessibility tree,
  // because a name is computed - an aria-label replaces the text, generated
  // content joins it - and no markup check can see either.
  const chip = page.locator('.filterpanel .fchip').first();
  if (await chip.count()) {
    await page.click('.fdetails > summary');
    await chip.click();
    await page.waitForTimeout(200);
    const cdp = await page.context().newCDPSession(page);
    const { root } = await cdp.send('DOM.getDocument', { depth: -1 });
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '.fdetails > summary' });
    const { nodes } = await cdp.send('Accessibility.getPartialAXTree', { nodeId, fetchRelatives: false });
    const name = (nodes[0] && nodes[0].name && nodes[0].name.value) || '';
    const shown = await page.evaluate(() => document.querySelector('.fdetails > summary').textContent);
    await cdp.detach();
    expect(`ax3 with one filter on, More filters is announced by the words and the count it shows (${JSON.stringify(name)})`,
      name, shown.trim());
    await chip.click();
    await page.click('.fdetails > summary');
    await page.waitForTimeout(150);
  } else notes.push('ok   (this plan has no chip in More filters — its announced count skipped)');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
}

// 10. The responsive contract, at every width either side of a breakpoint
//     the report's or the panel's stylesheet declares. What existed before this was two
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
  //     The Usage section's Detail disclosure is IN FLOW: opening it does not
  //     cover anything, it makes the document longer, and the heatmap and the
  //     small multiples are only laid out at all when it is open. It is opened,
  //     so the ladder measures them rather than measuring their absence.
  //
  //     NAMED BY THE CHARTS IT WRAPS, never by `.more`. This line read
  //     `document.querySelector('details.more')`, and when the test-evidence
  //     history started wearing that same print-behaviour class it came first in
  //     the document — so this opened the evidence history, left the Usage
  //     detail shut, and the ladder measured precisely the absence the paragraph
  //     above says it must not. Nothing failed. The assertion below is what
  //     ends that: this step is only worth running if it actually laid the
  //     charts out, so it now has to say so.
  //
  //     Every disclosure is SHUT FIRST — `.fdetails` among them, which is where
  //     its close now happens — and then exactly one is re-opened. The order is
  //     what makes the assertion below a statement about THIS step: section 6e
  //     opens the same disclosure a thousand lines earlier and nothing since has
  //     closed it, so a wrong derivation here would have ridden 6e's coat-tails
  //     and reported "open" about a disclosure it never touched.
  await page.evaluate(() => {
    for (const d of document.querySelectorAll('details')) d.open = false;
    window.scrollTo(0, 0);
  });
  const usageDetail = await readDisclosure(page, USAGE_DETAIL_CHARTS, { open: true });
  if (usageDetail === 'absent') {
    notes.push('ok   (no usage detail in this report — the ladder has no charts '
      + 'to lay out, and nothing to open)');
  } else {
    // @needs-usage-payload — the one site here rides the usage charts existing.
    expect('the ladder measures the Usage detail LAID OUT rather than measuring '
      + 'its absence - the disclosure that opened is the one CONTAINING the '
      + 'usage charts', usageDetail, 'open');
    // @end-needs-usage-payload
  }
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

// 10a. No ordinary title word is split mid-letter where the table is not framed.
//     A cell that may break anywhere has a narrowest width of about one
//     letter, and the table's column algorithm will happily take it there: a
//     wrap rule meant for an unbroken token once squeezed the task title column
//     to a few dozen pixels and set "Deduplicate" as two lines on every shipped
//     report. The ladder cannot see that - nothing left the frame - so the
//     question is asked of the words themselves: in every visible bare-text
//     cell (a task or bug title, a severity), at every rung wider than the
//     breakpoint below which the tables scroll in their own frame, does any
//     word change line BETWEEN TWO LETTERS? A break after a hyphen, a slash or
//     a colon is a break the browser offers in ordinary wrapping, and is not
//     what this asks about.
//     Task rows are opened for it and closed again, because the resting layout
//     the ladder measures shows none of their titles.
{
  const shut = await page.evaluate(() =>
    [...document.querySelectorAll('tr.task')].every((r) => r.offsetParent === null));
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  const split = [];
  let measured = 0;
  let cellsInDom = 0;
  for (const w of RESPONSIVE_LADDER.filter((x) => x > FRAMED_BELOW)) {
    await page.setViewportSize({ width: w, height: 945 });
    await page.waitForTimeout(60);
    const m = await page.evaluate(() => {
      const bare = [...document.querySelectorAll(
        'table.phases td:not([class]), table.data td:not([class])')]
        .filter((td) => !td.children.length);
      const out = [];
      let n = 0;
      for (const td of bare) {
        if (!td.checkVisibility()) continue;
        const tn = td.firstChild;
        if (!tn || tn.nodeType !== 3) continue;
        const lineOf = (i) => {
          const r = document.createRange();
          r.setStart(tn, i); r.setEnd(tn, i + 1);
          const box = r.getClientRects()[0];
          return box ? Math.round(box.top) : null;
        };
        for (const word of tn.data.matchAll(/\S+/g)) {
          n += 1;
          for (let k = 1; k < word[0].length; k += 1) {
            const a = lineOf(word.index + k - 1), b = lineOf(word.index + k);
            if (a === null || b === null || a === b) continue;
            if (/[\p{L}\p{N}]/u.test(word[0][k - 1]) && /[\p{L}\p{N}]/u.test(word[0][k])) {
              out.push(`${td.closest('table').className} "${word[0]}"`);
            }
            break;
          }
        }
      }
      return { out, n, inDom: bare.length };
    });
    measured += m.n;
    cellsInDom = Math.max(cellsInDom, m.inDom);
    for (const s of m.out) split.push(`${w}px ${s}`);
  }
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  await page.setViewportSize({ width: 1512, height: 945 });
  await page.waitForTimeout(200);
  // A page that HAS bare-text cells and measured no word in them looked at
  // nothing, and must not read as "no word was split".
  const verdict = cellsInDom && !measured ? 'measured no word'
    : (split.slice(0, 6).join(', ') + (split.length > 6 ? ` (+${split.length - 6} more)` : '')) || 'none';
  expect(`no visible title word splits mid-letter wider than ${FRAMED_BELOW}px `
    + `(${measured} word-rungs read)`, verdict, 'none');
}

// 10b. Content no fixture carries. The ladder above measures the plan it was
//     handed, so it can only ever be as hostile as that plan's prose - and the
//     demo's is short. A plan whose phases record paragraphs of summary, and an
//     accepted-commit reason as long as an essay, pushed this table far past the
//     viewport while every committed fixture stayed green. So the hostile
//     content is PUT INTO the rendered page: one row per table, cloned from the
//     table's own first body row so it wears the markup the renderer really
//     emits. Every prose cell of it gets a very long summary; the full-width
//     cells and the evidence marks also get a very long unbroken token, and the
//     phase row gets the free-text evidence chip that once carried such a
//     reason.
//
//     A prose cell is a full-width cell, or a bare-text cell in a column where
//     the rendered plan itself puts words separated by spaces (a title). A
//     column that only ever holds one word, a number or a pill - a severity,
//     a count, a status - is not given a paragraph, because the renderer never
//     emits one there and the question would stop being about long content:
//     an ordinary word planted in a column whose widest value is a dash grows
//     that column's narrowest width by the word, and on a runner whose fonts
//     are wider the bugs table has no slack left at the first unframed rung,
//     so the row widened the page with nothing in it longer than a word.
//
//     A bare-text cell (a title) gets the summary AND the token, the token
//     carrying the <wbr> break opportunities the renderer puts inside a long
//     run in a title - the stylesheet cannot break it without lowering the
//     cell's narrowest width to a letter, which 10a above exists to catch.
//     Each table's label says what it was given, because a table with no
//     prose bare column gets the token in its full-width cells alone. Each width either
//     side of a breakpoint is then asked one question: did that row make the
//     DOCUMENT any wider than it already was? Compared to the page's own width
//     before the row went in, so a plan that already overflows is accused of
//     nothing it did not do here - the ladder above owns that.
//
//     The second expectation is the one that keeps the first honest: a row that
//     never reached the page, or a token that was never painted, would widen
//     nothing and pass. It must be on screen, at the narrowest rung too, and
//     wrapped onto more than one line.
{
  const LONG_TOKEN = '0123456789abcdef'.repeat(60);
  const LONG_PROSE = Array.from({ length: 120 }, (_, i) =>
    `sentence ${i} of a summary that runs on far past any measure a reader keeps`).join(', ');
  const planted = await page.evaluate(({ token, prose }) => {
    const made = [];
    const skipped = [];
    for (const table of document.querySelectorAll('table.phases, table.data')) {
      // A table inside a shut disclosure is laid out by nobody, so a row put
      // there could neither widen the page nor be seen. Its disclosures are
      // opened for the measurement and shut again afterwards; a table that is
      // still not rendered after that is named as skipped, never planted.
      for (let d = table.closest('details:not([open])'); d;
        d = d.parentElement && d.parentElement.closest('details:not([open])')) {
        d.open = true;
        d.setAttribute('data-hostile-opened', '');
      }
      if (!table.checkVisibility()) { skipped.push(`${table.className} (not rendered)`); continue; }
      const body = table.tBodies[0];
      const proto = body && ([...body.rows].find((r) => r.classList.contains('phase'))
        || body.rows[0]);
      if (!proto) { skipped.push(`${table.className} (no body row)`); continue; }
      const row = proto.cloneNode(true);
      row.removeAttribute('id');
      row.removeAttribute('hidden');
      row.style.display = '';
      row.setAttribute('data-hostile-row', '');
      const isBare = (c) => !c.className && !c.children.length && c.colSpan === 1;
      const proseCols = new Set();
      for (const r of body.rows) {
        if ([...r.cells].some((c) => c.colSpan > 1)) continue;
        for (const c of r.cells) {
          if (isBare(c) && /\S\s+\S/.test(c.textContent)) proseCols.add(c.cellIndex);
        }
      }
      const cells = [...row.cells].filter((c) => c.colSpan > 1
        || (isBare(c) && proseCols.has(c.cellIndex)));
      const got = { bare: 0, full: 0, marks: 0 };
      for (const cell of cells) {
        // A phase with no desired outcome and no summary renders no .pmeta,
        // and that is the one block this row exists to fill.
        let meta = cell.querySelector('.pmeta');
        if (!meta && row.classList.contains('phase')) {
          meta = document.createElement('div');
          meta.className = 'pmeta muted';
          cell.append(meta);
        }
        if (meta) {
          meta.textContent = `${prose} ${token}`;
          const chip = document.createElement('span');
          chip.className = 'ptev';
          chip.textContent = `accepted ${token.slice(0, 12)}: ${prose}`;
          meta.before(chip);
          const unbroken = document.createElement('span');
          unbroken.className = 'ptev';
          unbroken.textContent = token;
          meta.before(unbroken);
          got.marks += 1;
        } else {
          if (cell.colSpan > 1) {
            cell.textContent = `${prose} ${token}`;
            got.full += 1;
          } else {
            // A bare cell is broken by the <wbr> the renderer puts inside a
            // long run in a title, so the planted token wears the same.
            cell.textContent = `${prose} `;
            token.match(/.{1,16}/g).forEach((chunk, i) => {
              if (i) cell.append(document.createElement('wbr'));
              cell.append(chunk);
            });
            got.bare += 1;
          }
        }
      }
      if (!cells.length) { skipped.push(`${table.className} (no prose cell)`); continue; }
      proto.after(row);
      made.push(`${table.className} [prose in ${cells.length} cell(s), token in ${got.bare} bare + `
        + `${got.full} full-width + ${got.marks} evidence-mark cell(s)]`);
    }
    return { made, skipped };
  }, { token: LONG_TOKEN, prose: LONG_PROSE });
  const widened = [];
  let narrowest = null;
  for (const w of RESPONSIVE_LADDER) {
    await page.setViewportSize({ width: w, height: 945 });
    await page.waitForTimeout(60);
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const rows = [...document.querySelectorAll('[data-hostile-row]')];
      const off = rows.map((r) => { const s = r.style.display; r.style.display = 'none'; return s; });
      const before = de.scrollWidth;
      rows.forEach((r, i) => { r.style.display = off[i]; });
      const after = de.scrollWidth;
      // Taller than a handful of lines: the prose alone is thousands of
      // characters, so a row this short never laid it out.
      const painted = rows.length > 0 && rows.every((r) => r.checkVisibility()
        && r.getBoundingClientRect().height > 120);
      return { before, after, cw: de.clientWidth, painted };
    });
    if (m.after > Math.max(m.before, m.cw + 1)) widened.push(`${w}px (${m.before} -> ${m.after})`);
    if (narrowest === null) narrowest = m;
  }
  await page.evaluate(() => {
    for (const r of document.querySelectorAll('[data-hostile-row]')) r.remove();
    for (const d of document.querySelectorAll('[data-hostile-opened]')) {
      d.open = false;
      d.removeAttribute('data-hostile-opened');
    }
  });
  if (planted.skipped.length) {
    notes.push(`ok   (the hostile row skipped ${planted.skipped.join(', ')})`);
  }
  await page.setViewportSize({ width: 1512, height: 945 });
  await page.waitForTimeout(200);
  expect(`hostile content (planted per table: ${planted.made.join(' + ') || 'no table'}) `
    + 'widens the document at no width', widened.join(', ') || 'none', 'none');
  expect('...and the planted rows were really on the page, wrapped, at the narrowest width',
    planted.made.length > 0 && narrowest !== null && narrowest.painted, true);
}

// 10c. 10b plants a long run into the columns the renderer gives a paragraph.
//     This plants one into EVERY column of EVERY table on the page, header and
//     body alike, because which column a long run can reach is a fact about
//     some future plan and not about this sheet. A column KIND is one table's
//     cells of one tag that start at one column and span the same number of
//     columns - a phase row's full-width cell is its own kind, beside the
//     seven ordinary columns of the task rows under it.
//
//     The token is made unbreakable by the planted element's own inline
//     style, so the answer does not lean on any wrap rule the sheet carries:
//     a wrap override is a first resort for a column the sheet happens to
//     name, and the guarantee asked about here is the one that must hold for
//     a column it does not. Measured at every rung of the ladder, under a
//     monospace fallback - a portable stand-in for a font wide enough to find
//     the margin, whichever host runs this.
//
//     NO KIND PRESENT ON THE PAGE MAY GO UNPLANTED. Every disclosure, view and
//     collapsed task row is opened first, the way a reader could; a kind
//     whose every cell is still not rendered after that is a failure by
//     name, never a note, so a page that planted one kind cannot read as one
//     that planted them all.
//
//     The same ladder is walked once BEFORE planting, because the containing
//     frame has a second half: a table that fits is released by the script
//     and keeps sticky column headers on a desktop width. Planting then makes
//     every table outgrow its frame, which is the content change the script
//     must follow by taking the release back.
{
  const styleHandle = await page.addStyleTag({ content: 'table{font-family:monospace}' });
  const HOSTILE_RUN = 'q9z7k2m4'.repeat(20);
  const view0 = await page.evaluate(() => {
    const sel = document.getElementById('audit-view');
    return sel ? sel.value : null;
  });
  if (view0 !== null && view0 !== 'all') {
    await page.selectOption('#audit-view', 'all');
    await page.waitForTimeout(200);
  }
  const shut = await page.evaluate(() =>
    [...document.querySelectorAll('tr.task')].every((r) => r.offsetParent === null));
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  await page.evaluate(() => {
    for (const table of document.querySelectorAll('table')) {
      for (let d = table.closest('details:not([open])'); d;
        d = d.parentElement && d.parentElement.closest('details:not([open])')) {
        d.open = true;
        d.setAttribute('data-hostile-opened', '');
      }
    }
  });
  // The frame each table sits in is contained by the sheet alone, and the
  // script releases the ones whose table fits - which is what gives their
  // column headers back to the page. Read here the way a reader meets it: per
  // rendered frame, whether its table fits (measured by this gate itself, with
  // the frame released for the reading, not by asking the script), whether the
  // frame carries the mark, and whether its first header is sticky. Both
  // directions are held: a fitting frame above the tablet block must be marked
  // and stick, and every other frame must be unmarked and must not stick,
  // because a mark left on a table that has since outgrown its frame is how the
  // page would widen again.
  const fitState = () => page.evaluate(() =>
    [...document.querySelectorAll('.tablewrap')].filter((w) => w.checkVisibility())
      .map((w, i) => {
        const t = w.querySelector('table');
        const th = t && t.querySelector('thead th');
        const prev = w.style.overflowX;
        w.style.overflowX = 'visible';
        const fits = Boolean(t) && t.scrollWidth <= w.clientWidth;
        w.style.overflowX = prev;
        return { label: `${t ? `table.${t.classList[0] || '(no class)'}` : '(no table)'}#${i}`,
          fits, marked: w.hasAttribute('data-fits'),
          sticky: th ? getComputedStyle(th).position === 'sticky' : null };
      }));
  const fitWrong = (w, frames) => frames.flatMap((f) => {
    const stickWanted = w > FRAMED_BELOW && f.fits;
    const out = [];
    if (stickWanted && !f.marked) out.push('fits but is not marked');
    if (!f.fits && f.marked) out.push('is marked but its table overflows the frame');
    if (f.sticky !== null && f.sticky !== stickWanted) {
      out.push(stickWanted ? 'fits but its header does not stick'
        : 'has a sticky header in a contained frame');
    }
    return out.map((s) => `${w}px ${f.label} ${s}`);
  });
  const cleanWrong = [];
  const cleanWidened = [];
  let fitAtDesk = 0;
  // The rung the clean walk ends on and what it read there: the planting below
  // happens at that width, and the content-change read compares against it.
  let cleanLast = { w: 0, frames: [] };
  for (const w of RESPONSIVE_LADDER) {
    await page.setViewportSize({ width: w, height: 945 });
    await page.waitForTimeout(60);
    const frames = await fitState();
    const de = await page.evaluate(() => [document.documentElement.scrollWidth,
      document.documentElement.clientWidth]);
    if (de[0] > de[1] + 1) cleanWidened.push(`${w}px (${de[1]} -> ${de[0]})`);
    if (w > FRAMED_BELOW) fitAtDesk += frames.filter((f) => f.fits && f.sticky !== null).length;
    cleanWrong.push(...fitWrong(w, frames));
    cleanLast = { w, frames };
  }
  expect('every column kind of every table on the page is planted with an unbreakable '
    + 'token and none widens the document, and a kind present on the page that cannot '
    + 'be planted fails the leg (before any planting: at every rung the document does not '
    + 'widen, and above the tablet block every frame whose table fits is marked and its '
    + `column header is sticky - ${fitAtDesk} fitting frame(s) with a header measured)`,
    [fitAtDesk ? '' : 'no table fits its frame at any desktop width, so stickiness was never measured',
     cleanWidened.length ? `widened at ${cleanWidened.join(', ')}` : '',
     cleanWrong.length ? cleanWrong.slice(0, 6).join('; ') : '']
      .filter(Boolean).join('; ') || 'none', 'none');
  const planted = await page.evaluate((token) => {
    const kinds = [];
    const unplanted = [];
    const tables = [...document.querySelectorAll('table')];
    tables.forEach((table, n) => {
      const label = `table.${table.classList[0] || '(no class)'}#${n}`;
      const byKind = new Map();
      for (const row of table.rows) {
        let col = 0;
        for (const cell of row.cells) {
          const key = `${cell.tagName.toLowerCase()}@${col}`
            + (cell.colSpan > 1 ? `+${cell.colSpan}` : '');
          if (!byKind.has(key)) byKind.set(key, []);
          byKind.get(key).push(cell);
          col += cell.colSpan;
        }
      }
      if (!byKind.size) unplanted.push(`${label} (no cell at all)`);
      for (const [key, cells] of byKind) {
        const cell = cells.find((c) => c.checkVisibility());
        if (!cell) { unplanted.push(`${label} ${key} (no cell of it rendered)`); continue; }
        const run = document.createElement('span');
        run.setAttribute('data-hostile-run', '');
        run.style.cssText = 'white-space:nowrap;overflow-wrap:normal;word-break:keep-all';
        run.textContent = token;
        cell.append(run);
        kinds.push(`${label} ${key}`);
      }
    });
    return { tables: tables.length, kinds, unplanted };
  }, HOSTILE_RUN);
  // The content change on its own, with the window left where the clean walk
  // put it. Every rung of the ladder below resizes the window first, and the
  // script's resize listener re-measures by itself there, so the ladder cannot
  // tell the observer over the frames and their tables from that fallback.
  // Here nothing resizes: only the observer can take back a mark that planting
  // made stale. Two animation frames - one for the observer's notification,
  // one for the measurement it queues.
  await page.evaluate(() => new Promise((done) =>
    requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  const settled = await fitState();
  const settledViewport = await page.evaluate(() => window.innerWidth);
  const outgrown = settled.filter((f, i) => !f.fits && cleanLast.frames[i]
    && cleanLast.frames[i].marked).length;
  const settledStale = settled.filter((f) => !f.fits && f.marked).map((f) => f.label);
  expect('every column kind of every table on the page is planted with an unbreakable '
    + 'token and none widens the document, and a kind present on the page that cannot '
    + 'be planted fails the leg (once planted, with no window resize: two animation '
    + `frames at ${cleanLast.w}px later, none of the ${outgrown} frame(s) marked before `
    + 'planting whose table now overflows still carries the mark, nor does any other '
    + 'overflowing frame)',
    [settledViewport === cleanLast.w ? ''
      : `the viewport moved to ${settledViewport}px, so a resize could have answered`,
     outgrown ? '' : 'no frame marked before planting outgrew its frame, so the content '
       + 'change was never measured',
     settledStale.length ? `still marked over an overflowing table: ${settledStale.slice(0, 6).join(', ')}` : '',
     fitWrong(cleanLast.w, settled).slice(0, 6).join('; ')]
      .filter(Boolean).join('; ') || 'none', 'none');
  const widened = [];
  const unpainted = new Set();
  const plantedWrong = [];
  let overflowAtDesk = 0;
  for (const w of RESPONSIVE_LADDER) {
    await page.setViewportSize({ width: w, height: 945 });
    await page.waitForTimeout(60);
    const frames = await fitState();
    if (w > FRAMED_BELOW) overflowAtDesk += frames.filter((f) => !f.fits && f.sticky !== null).length;
    plantedWrong.push(...fitWrong(w, frames));
    const m = await page.evaluate(() => {
      const de = document.documentElement;
      const runs = [...document.querySelectorAll('[data-hostile-run]')];
      return {
        sw: de.scrollWidth, cw: de.clientWidth,
        unpainted: runs.filter((r) => !r.checkVisibility()
          || r.getBoundingClientRect().width === 0)
          .map((r) => r.closest('table').className || '(no class)'),
      };
    });
    if (m.sw > m.cw + 1) widened.push(`${w}px (${m.cw} -> ${m.sw})`);
    m.unpainted.forEach((t) => unpainted.add(`${w}px ${t}`));
  }
  await page.evaluate(() => {
    for (const r of document.querySelectorAll('[data-hostile-run]')) r.remove();
    for (const d of document.querySelectorAll('[data-hostile-opened]')) {
      d.open = false;
      d.removeAttribute('data-hostile-opened');
    }
  });
  await styleHandle.evaluate((el) => el.remove());
  if (shut) { await page.click('#audit-expand'); await page.waitForTimeout(250); }
  if (view0 !== null && view0 !== 'all') {
    await page.selectOption('#audit-view', view0);
    await page.waitForTimeout(200);
  }
  await page.setViewportSize({ width: 1512, height: 945 });
  await page.waitForTimeout(200);
  expect('every column kind of every table on the page is planted with an unbreakable '
    + 'token and none widens the document, and a kind present on the page that cannot '
    + `be planted fails the leg (${planted.kinds.length} kind(s) across `
    + `${planted.tables} table(s), at every rung of the ladder)`,
    [planted.tables ? '' : 'no table on the page',
     planted.unplanted.length ? `not planted: ${planted.unplanted.join(', ')}` : '',
     widened.length ? `widened at ${widened.join(', ')}` : '',
     unpainted.size ? `planted but not painted: ${[...unpainted].slice(0, 6).join(', ')}` : '']
      .filter(Boolean).join('; ') || 'none', 'none');
  expect('every column kind of every table on the page is planted with an unbreakable '
    + 'token and none widens the document, and a kind present on the page that cannot '
    + 'be planted fails the leg (once planted, a table that outgrew its frame loses the '
    + 'mark and its sticky header at every rung, each read after a window resize that '
    + `re-measures by itself - ${overflowAtDesk} overflowing frame(s) with a header `
    + 'measured above the tablet block)',
    [overflowAtDesk ? '' : 'no planted table overflowed its frame at a desktop width, so '
      + 'the contained direction was never measured',
     plantedWrong.length ? plantedWrong.slice(0, 6).join('; ') : '']
      .filter(Boolean).join('; ') || 'none', 'none');
}

// --- the full-run line: the third place's verdict, as a reader gets it -------
// `_report_html._verified_line` is pinned string by string in Python, and no
// browser had ever looked at what it paints: a stylesheet rule hiding the chip,
// or a renderer emitting an answer with the wrong sentence, would pass every
// one of those pins. So this reads the painted chips themselves - one per merged
// phase of a plan that declares `meta.fullGate` - and holds each to the sentence
// its answer renders.
//
// WHICH ANSWERS A PAGE MUST SHOW is a property of the fixture it was rendered
// from, never of the page: a plan whose runs cover every merge is right to show
// no provisional line. So the requirement is keyed by the committed document,
// for the one fixture BUILT to show every answer - `gen-demo-manifest.py` makes
// the scale demo a git repository with one full run whose head contains exactly
// one merge. Red against the page it replaced, which showed no whole line.
const FULLRUN_REQUIRED = {
  'docs/demo-large.html': ['whole', 'provisional', 'unknown'],
};
// The sentence each answer renders, from `_verified_line`'s own docstring. A
// sha is the prefix `_verified_line` cuts, and the whole line's counts may be
// `?` - the renderer's honest "not recorded" - so they are not pinned.
const FULLRUN_SHAPES = {
  // The count clause is present only when a count was recorded, and never as
  // two question marks: that is the placeholder `_verified_line` drops.
  whole: /^sign-off: (derived|wide)(, (?!\? of \?)(\d+|\?) of (\d+|\?) suites)?, \S+ \S+; whole at [0-9a-f]{9}$/,
  provisional: /^whole: pending - record a full run at [0-9a-f]{9} \(pre-push, CI, or \/audit:review \S+ --full\)$/,
  unknown: /^unknown - \S/,
};
{
  // EVERY PHASE ON SCREEN FIRST. The View select and the filters hide phase
  // rows by design, and a chip inside a row a VIEW took away is not a chip the
  // stylesheet hid - so both are cleared before anything is measured, and a
  // row still filtered out afterwards is named as that rather than as a hide.
  await clearAll();
  if (await page.$('#audit-view option[value="all"]')) {
    await page.selectOption('#audit-view', 'all');
    await page.waitForTimeout(250);
  }
  // RENDERED, NOT MERELY STYLED. The chip's own computed `display` says nothing
  // about an ancestor a rule took out of the layout; `getClientRects()` is empty
  // exactly when the chip or any ancestor generates no box. `visibility`
  // inherits, so the chip's own computed value already carries an ancestor's.
  // What neither sees is a chip painted at zero opacity or off screen - this
  // measures "laid out and not visibility-hidden", and the label says no more.
  const fullLines = await page.evaluate(() =>
    [...document.querySelectorAll('tr.phase [data-fullrun]')].map((n) => {
      const row = n.closest('tr.phase');
      return { answer: n.getAttribute('data-fullrun'), text: n.textContent.trim(),
               phase: row.getAttribute('data-phase'),
               filtered: row.style.display === 'none',
               shown: n.getClientRects().length > 0
                 && getComputedStyle(n).visibility !== 'hidden' };
    }));
  const fullKey = documentKey(path);
  const fullWant = FULLRUN_REQUIRED[fullKey] || [];
  const fullMissing = fullWant.filter((a) => !fullLines.some((l) => l.answer === a));
  expect('this page carries every full-run answer its fixture is built to show',
    fullMissing.join(', '), '');
  if (!fullLines.length) {
    notes.push(`ok   no full-run line in this report - its plan names no meta.fullGate `
      + `or has merged no phase${fullWant.length ? '' : ` (and ${fullKey || file} `
      + 'is not a document whose fixture requires one)'}`);
  } else {
    expect('every full-run line carries an answer the renderer knows',
      fullLines.filter((l) => !FULLRUN_SHAPES[l.answer]).map((l) => l.answer).join(', '), '');
    expect('every full-run line reads the sentence its own answer renders',
      fullLines.filter((l) => FULLRUN_SHAPES[l.answer] && !FULLRUN_SHAPES[l.answer].test(l.text))
        .map((l) => `${l.phase} ${l.answer}: ${l.text}`).slice(0, 3).join(' | '), '');
    expect('no full-run line is hidden by the stylesheet',
      fullLines.filter((l) => !l.shown)
        .map((l) => (l.filtered ? `${l.phase} (its row is still filtered out)` : l.phase))
        .join(', '), '');
    const fullSeen = new Map();
    for (const l of fullLines) fullSeen.set(l.phase, (fullSeen.get(l.phase) || 0) + 1);
    expect('a merged phase carries one full-run line and never two',
      [...fullSeen].filter(([, n]) => n > 1).map(([p]) => p).join(', '), '');
    notes.push(`ok   full-run lines: ${['whole', 'provisional', 'unknown']
      .map((a) => `${a} ${fullLines.filter((l) => l.answer === a).length}`).join(', ')}`);
  }
}

// The last liveness reading, and the one that covers the whole run: the ladder
// above resized the viewport at every rung and scrolled the document to both ends
// at each. If any of that had rebuilt the document, everything from the reload
// onwards was measured against nodes nobody was listening to.
await stillLive('at the end, over everything driven since the reload');

// A plan long enough to have crashed the printer, printed for real. Chrome's
// renderer died in `page.pdf` (and the real Save as PDF tab with it) when ONE
// table was paginated across many pages: its memory grew with that table's
// rows times the pages it spanned. On the day it was measured, the demo plan at
// twenty tasks a phase printed at 168 phases and crashed at 175, and this
// repository's own plan crashed inside this file's PDF step above. Nothing in
// the report's bytes or node count predicted it, and its row count did not
// either: the acme example's rows are taller than the demo's, so the same rows
// spanned more pages. What tracked it was how long the table ran on paper, so
// the report under test is grown, in a page of its own, by copying its own
// phase blocks until the uncut sheet runs past `STRESS_PRINT_PX` at portrait
// width — past where every report measured that day crashed — and it must
// then print. Only the first sheet is asked for: Chrome paginates the whole
// document to produce any page of it, so the crash needs no more than that.
//
// The bound covers the WHOLE block — load, growth, every measurement and the
// print — because each of those waits on the same renderer, and a bound on the
// print alone left the rest free to hang the run. Opt-in (`--stress-print`, see
// the header); it runs AFTER the last liveness reading and in a context of its
// own, so a renderer that does die cannot take the page every other check drove
// down with it.
if (!STRESS) {
  notes.push('ok   (the long-print stress check was not asked for - '
    + '`--stress-print` runs it)');
} else {
  const STRESS_PRINT_PX = 3400000;
  const STRESS_BOUND_MS = 300000;
  const ctx = await browser.newContext({ viewport: { width: 1512, height: 945 } });
  const sp = await ctx.newPage();
  let died = null;
  const crashed = new Promise((r) => { died = r; });
  sp.on('crash', () => died('the renderer crashed'));
  // What the setup reached, kept outside the race so a block that ran out of
  // time still reports how far it got.
  const grown = { rows: 0, px: 0 };
  // How tall the sheet runs uncut, at the portrait width section 7 uses. Read
  // without `beforeprint`, so the same figure is measured whatever shape the
  // report prints in.
  const printPx = async () => {
    await sp.emulateMedia({ media: 'print' });
    await sp.setViewportSize({ width: 688, height: 900 });
    const h = await sp.evaluate(() => document.documentElement.scrollHeight);
    await sp.emulateMedia({ media: null });
    await sp.setViewportSize({ width: 1512, height: 945 });
    return h;
  };
  // Append copies of the table's own phase blocks until it holds `want` rows.
  const growTo = (target) => sp.evaluate((want) => {
    const g = document.querySelector('table.phases');
    const body = g && g.tBodies[0];
    if (!body) return 0;
    const blocks = [];
    let cur = null;
    for (const r of body.rows) {
      if (r.classList.contains('phase')) { cur = [r]; blocks.push(cur); }
      else if (r.classList.contains('seghead')) cur = null;
      else if (cur) cur.push(r);
    }
    if (!blocks.length) return 0;
    const frag = document.createDocumentFragment();
    for (let n = body.rows.length, i = 0; n < want; i++) {
      for (const r of blocks[i % blocks.length]) { frag.appendChild(r.cloneNode(true)); n++; }
    }
    body.appendChild(frag);
    return body.rows.length;
  }, target);
  const stressBlock = async () => {
    await sp.goto('file://' + path, { timeout: 0 });
    grown.rows = await sp.evaluate(() => {
      const g = document.querySelector('table.phases');
      return g && g.tBodies[0] ? g.tBodies[0].rows.length : 0;
    });
    grown.px = await printPx();
    // Rows are not all one height, and the copies start from the first blocks
    // every round, so an estimate is scaled by what it actually printed to and
    // a short fall is grown again.
    for (let round = 0; round < 6 && grown.rows > 0 && grown.px < STRESS_PRINT_PX; round++) {
      grown.rows = await growTo(Math.ceil(grown.rows * (STRESS_PRINT_PX / grown.px) * 1.1));
      grown.px = await printPx();
    }
    if (grown.px < STRESS_PRINT_PX) return 'not grown far enough to print';
    return sp.pdf({ preferCSSPageSize: true, pageRanges: '1' }).then(() => 'printed',
      (e) => `failed: ${String(e.message || e).split('\n')[0]}`);
  };
  const t0 = Date.now();
  let timer = null;
  const outcome = await Promise.race([
    stressBlock().catch((e) => `failed: ${String(e.message || e).split('\n')[0]}`),
    crashed,
    new Promise((r) => {
      timer = setTimeout(() => r(`the long-print stress block did not finish within `
        + `${STRESS_BOUND_MS / 1000} s`), STRESS_BOUND_MS);
    }),
  ]);
  clearTimeout(timer);
  const took = Date.now() - t0;
  expect(`(setting up the long print) the uncut sheet was grown past the crashing `
    + `length (${grown.rows} rows, ${grown.px} px)`, grown.px >= STRESS_PRINT_PX, true);
  expect(`a page past the length that crashed the printer prints, the whole block `
    + `within ${STRESS_BOUND_MS / 1000} s (${grown.rows} rows, ${(took / 1000).toFixed(1)} s)`,
    outcome, 'printed');
  // A crashed or still-busy page can leave close() waiting on a process that is
  // gone or not answering.
  await Promise.race([ctx.close(), new Promise((r) => setTimeout(r, 5000))]);
}

// --- Clear lifts every axis, derived from the page ----------------------------
// Each filter control is turned on ALONE on a fresh load, Clear is pressed, and
// the page has to be back where it opened - nothing pressed, no count on More
// filters, nothing in the link or the stored view, every phase back - and still
// so after a reload. The controls are read off the DOM by KIND (every pressable
// chip in a filter bar, every field in the toolbar and the global row), never
// listed, so a chip row added tomorrow is exercised without editing this. Its
// own page and context: the main page above carries expanded rows and stored
// state that would make "back where it opened" a different place.
{
  const CL_CHIPS = '.sectools [aria-pressed], .tf-chips [aria-pressed], .auchips [aria-pressed]';
  const CL_FIELDS = '.sectools input, .gfilters input, .gfilters select';
  const CL_ALL = CL_CHIPS + ', ' + CL_FIELDS;
  // A wired attribute no exercised chip carries is reported as not exercised.
  const wiredAttrs = WIRED_CHIP_ATTRS;
  const cctx = await browser.newContext({ viewport: { width: 1512, height: 945 } });
  const cp = await cctx.newPage();
  const clErrors = [];
  cp.on('pageerror', (e) => clErrors.push(e.message));
  const fresh = async () => {
    // A hash-only change is a same-document navigation and would not reload.
    await cp.goto('about:blank');
    await cp.goto('file://' + path);
    await cp.waitForTimeout(60);
  };
  const dropStored = () => cp.evaluate(() => {
    Object.keys(localStorage).filter((k) => k.indexOf('audit-') === 0)
      .forEach((k) => localStorage.removeItem(k));
  });
  // What "back where it opened" means, read the same way at load, after Clear
  // and after the reload.
  const clSnap = () => cp.evaluate(({ all, chips }) => {
    const g = document.querySelector('table.phases');
    const h = location.hash || '';
    const hashKeys = h.indexOf('#!') === 0
      ? h.slice(2).split('&').filter(Boolean).map((p) => p.split('=')[0]).sort() : [];
    return {
      phases: [...g.querySelectorAll('tbody tr.phase')].filter((r) => r.style.display !== 'none').length,
      tasks: [...g.querySelectorAll('tbody tr.task')].filter((r) => r.offsetParent !== null).length,
      pressed: [...document.querySelectorAll(chips)]
        .filter((c) => c.getAttribute('aria-pressed') === 'true')
        .map((c) => [...c.attributes].filter((a) => a.name.indexOf('data-') === 0)
          .map((a) => a.name + '=' + a.value)[0] || c.textContent.trim()),
      fcount: ((document.getElementById('audit-fcount') || {}).textContent || '').trim(),
      hashKeys: hashKeys.join(','),
      stored: Object.keys(localStorage).filter((k) => k.indexOf('audit-view-') === 0)
        .map((k) => localStorage.getItem(k)).filter(Boolean).join(' | '),
      fields: [...document.querySelectorAll(all)].filter((e) => 'value' in e && !e.hasAttribute('aria-pressed'))
        .map((e) => e.value).join('\u0001'),
      clear: !!document.querySelector('.sectools [data-clear]:not([hidden])'),
      // What More filters folds away and has switched on: a pressed chip or a
      // field holding a value inside the disclosure. Its badge is about these.
      panelOn: [...document.querySelectorAll('.fdetails [aria-pressed], .fdetails input, .fdetails select')]
        .filter((e) => (e.hasAttribute('aria-pressed')
          ? e.getAttribute('aria-pressed') === 'true' : !!e.value)).length,
    };
  }, { all: CL_ALL, chips: CL_CHIPS });
  const describe = (s) => [
    s.pressed.length ? 'pressed ' + s.pressed.join(' ') : '',
    s.fcount ? 'More filters says ' + JSON.stringify(s.fcount) : '',
    s.hashKeys ? 'link keys ' + s.hashKeys : '',
    s.stored ? 'stored ' + JSON.stringify(s.stored) : '',
  ].filter(Boolean).join(', ');

  await fresh();
  await dropStored();
  await fresh();
  const atLoad = await clSnap();
  const n = await cp.evaluate((all) => document.querySelectorAll(all).length, CL_ALL);
  const left = { offer: [], pressed: [], fcount: [], hash: [], stored: [], phases: [], fields: [], reload: [],
                 badge: [] };
  const idle = [];
  const unseen = [];
  const exercised = new Set();
  for (let i = 0; i < n; i++) {
    // Turn on exactly control i. Returns its label and what kind of input it
    // needs, or why it cannot be reached on this page.
    const prep = await cp.evaluate(({ all, i, wired }) => {
      const el = document.querySelectorAll(all)[i];
      const attr = [...el.attributes].map((a) => a.name).find((a) => wired.indexOf(a) >= 0);
      const label = attr ? attr + '=' + el.getAttribute(attr)
        : el.id ? '#' + el.id : el.tagName.toLowerCase();
      const d = el.closest('details');
      if (d) d.open = true;
      const tf = el.closest('tr.taskfilter');
      return { label, attr: attr || '', tag: el.tagName, type: el.type || '',
               tfPhase: tf ? tf.getAttribute('data-phase') : '',
               min: el.min || '', max: el.max || '',
               opt: el.tagName === 'SELECT'
                 ? ([...el.options].find((o) => o.value && o.value !== '~multi') || {}).value || '' : '' };
    }, { all: CL_ALL, i, wired: wiredAttrs });
    // The page's own querySelectorAll order, the one `i` was counted in.
    const handle = (await cp.evaluateHandle(({ all, i }) => document.querySelectorAll(all)[i],
      { all: CL_ALL, i })).asElement();
    if (prep.tfPhase) {
      const row = await cp.$(`tr.phase[data-phase="${prep.tfPhase}"] strong`);
      if (row && await row.isVisible()) await row.click();
    }
    if (!(await handle.isVisible())) {
      unseen.push(prep.label + ' (not on screen in the default view)');
      await dropStored(); await fresh(); continue;
    }
    const before = await clSnap();
    if (prep.tag === 'SELECT') {
      if (!prep.opt) { unseen.push(prep.label + ' (no option to pick)'); await dropStored(); await fresh(); continue; }
      await handle.selectOption(prep.opt);
    } else if (prep.type === 'date') {
      const v = /to$/.test(prep.label) ? prep.min : prep.max;
      if (!v) { unseen.push(prep.label + ' (no min or max to pick a date from)'); await dropStored(); await fresh(); continue; }
      await handle.evaluate((e, val) => { e.value = val; e.dispatchEvent(new Event('change', { bubbles: true })); }, v);
    } else if (prep.tag === 'INPUT') {
      const term = await cp.evaluate(() => {
        const t = document.querySelector('table.phases tbody tr.phase strong');
        return t ? t.textContent.trim().split(/\s+/)[0].toLowerCase() : 'a';
      });
      await handle.fill(term);
      await handle.press('Enter');
    } else {
      await handle.click();
    }
    await cp.evaluate(() => { document.querySelectorAll('details.fdetails').forEach((d) => { d.open = false; }); });
    const on = await clSnap();
    if (prep.attr) exercised.add(prep.attr);
    if (!on.clear) {
      // A control that changed nothing a reader can see (the All-time preset
      // on a view already spanning all time) has nothing to lift. One that
      // changed the table, the link or the stored view and offers no way back
      // is the defect this case exists for.
      const changed = on.phases !== before.phases || on.tasks !== before.tasks
        || on.hashKeys !== atLoad.hashKeys || on.stored !== atLoad.stored || on.fcount !== atLoad.fcount;
      if (changed) left.offer.push(prep.label + ' (' + (describe(on) || 'the table narrowed') + ')');
      else idle.push(prep.label);
      await dropStored();
      await fresh();
      continue;
    }
    // The More-filters badge counts what is on INSIDE it, and only that: a
    // count over a panel with nothing pressed sends the reader looking for a
    // filter that is not there, and no count over a pressed one hides it.
    // Judged here, past the branch above, so only a control that is filtering
    // is asked: the All-time preset lights a chip and filters nothing.
    if (Boolean(on.fcount) !== (on.panelOn > 0)) {
      left.badge.push(prep.label + ' (More filters says ' + JSON.stringify(on.fcount)
        + ' with ' + on.panelOn + ' of its own controls on)');
    }
    await cp.click('.sectools [data-clear]');
    const cleared = await clSnap();
    if (cleared.pressed.length) left.pressed.push(prep.label + ' (still pressed: ' + cleared.pressed.join(' ') + ')');
    if (cleared.fcount !== atLoad.fcount) left.fcount.push(prep.label + ' (' + JSON.stringify(cleared.fcount) + ')');
    if (cleared.hashKeys !== atLoad.hashKeys) left.hash.push(prep.label + ' (' + cleared.hashKeys + ')');
    if (cleared.stored !== atLoad.stored) left.stored.push(prep.label + ' (' + JSON.stringify(cleared.stored) + ')');
    if (cleared.phases !== atLoad.phases) left.phases.push(prep.label + ' (' + cleared.phases + ' of ' + atLoad.phases + ')');
    if (cleared.fields !== atLoad.fields) left.fields.push(prep.label);
    await fresh();
    const reloaded = await clSnap();
    const stillDirty = describe(reloaded) || (reloaded.phases !== atLoad.phases ? reloaded.phases + ' phases' : '')
      || (reloaded.fields !== atLoad.fields ? 'a field kept a value' : '');
    if (stillDirty) left.reload.push(prep.label + ' (' + stillDirty + ')');
    // Whatever a failed Clear left behind must not leak into the next control,
    // and neither may a phase opened to reach its task-status chips.
    if (stillDirty || reloaded.stored || prep.tfPhase) { await dropStored(); await fresh(); }
  }
  await cctx.close();
  const ran = n - unseen.length - idle.length;
  expect('cl0 Clear lifts every axis - the page offers filter controls to exercise, '
    + 'read off the DOM', ran > 0, true);
  expect('cl1 Clear lifts every axis - every control that filters offers Clear',
    left.offer.join(' · ') || 'none', 'none');
  expect('cl2 Clear lifts every axis - nothing stays pressed after Clear',
    left.pressed.join(' · ') || 'none', 'none');
  expect('cl3 Clear lifts every axis - More filters counts nothing after Clear',
    left.fcount.join(' · ') || 'none', 'none');
  expect('cl4 Clear lifts every axis - no filter key is left in the link after Clear',
    left.hash.join(' · ') || 'none', 'none');
  expect('cl5 Clear lifts every axis - the stored view is gone after Clear',
    left.stored.join(' · ') || 'none', 'none');
  expect('cl6 Clear lifts every axis - every phase shown at load is shown again after Clear',
    left.phases.join(' · ') || 'none', 'none');
  expect('cl7 Clear lifts every axis - every field holds its value at load again after Clear',
    left.fields.join(' · ') || 'none', 'none');
  expect('cl8 Clear lifts every axis - the cleared view is still clear after a reload',
    left.reload.join(' · ') || 'none', 'none');
  expect('cl10 More filters counts a filter exactly while one of its own controls is on',
    left.badge.join(' · ') || 'none', 'none');
  expect('cl9 Clear lifts every axis - the page raised no error while being driven',
    clErrors.slice(0, 2).join(' | ') || 'none', 'none');
  const notExercised = wiredAttrs.filter((a) => !exercised.has(a));
  notes.push(`note Clear lifts every axis: ${ran} of ${n} controls exercised`
    + (idle.length ? `; turned on nothing to clear: ${idle.join(', ')}` : '')
    + (unseen.length ? `; not exercised: ${unseen.join(', ')}` : '')
    + (notExercised.length ? `; wired chip attributes no exercised control carries `
      + `(not exercised, not passed): ${notExercised.join(', ')}` : ''));
}

// --- a link restores only what a control can show -----------------------------
// A filtered view is a link, and a link is typed by whoever sends it. A value
// no control offers - an area the plan has no tag for, a model nobody ran, a
// prototype key, a string that is not a date - used to be restored as it
// stood: it hid rows, and nothing on the page was pressed to say why. Each key
// of every axis in the page's registry is loaded ALONE with such a value, and
// the page has to open exactly as it opens with no link. The keys are the
// ones the running page publishes off its own registry (`data-link-keys` on
// the root), not listed here and not read out of the source text, and the
// allow half (hr2) loads each one with a value its control DOES offer and
// wants that value back on - so a key read wrongly, or a check that drops
// everything, is red rather than vacuously quiet.
{
  // Free text: every string is a value a search box offers, so a link's value
  // there is the reader's query, not a filter nothing shows. The one exemption,
  // and it must name a key the page still publishes (hr0).
  const HR_FREE_TEXT = ['q'];
  const HR_DATE_KEYS = { from: ['#audit-from', '#audit-gfrom'], to: ['#audit-to', '#audit-gto'] };
  const HR_BOGUS = ['nosuch-value', 'constructor', 'toString'];
  const HR_BOGUS_DATE = ['notadate', '2026-02-30', 'constructor'];
  const hctx = await browser.newContext({ viewport: { width: 1512, height: 945 } });
  const hp = await hctx.newPage();
  const hrErrors = [];
  hp.on('pageerror', (e) => hrErrors.push(e.message));
  const openAt = async (frag) => {
    await hp.goto('about:blank');
    await hp.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
    await hp.goto('file://' + path + (frag ? '#!' + frag : ''));
    await hp.waitForTimeout(60);
  };
  // Everything a restored filter can change that a reader sees: which phases
  // and usage rows are drawn, what is pressed, what the fields hold, whether
  // More filters counts anything and whether Clear is offered.
  const hrSnap = () => hp.evaluate(() => {
    const g = document.querySelector('table.phases');
    const shown = (sel) => [...document.querySelectorAll(sel)]
      .filter((r) => !r.hidden && r.style.display !== 'none').length;
    return {
      phases: g ? [...g.querySelectorAll('tbody tr.phase')].filter((r) => r.style.display !== 'none')
        .map((r) => r.getAttribute('data-phase')).join(' ') : '',
      usage: shown('.smcell') + '/' + shown('.rank[data-author]'),
      pressed: [...document.querySelectorAll('.sectools [aria-pressed="true"], .auchips [aria-pressed="true"]')]
        .map((c) => [...c.attributes].filter((a) => a.name.indexOf('data-') === 0)
          .map((a) => a.name + '=' + a.value)[0] || c.textContent.trim()).sort().join(' '),
      fields: [...document.querySelectorAll('.sectools input, .gfilters input, .gfilters select, #audit-view')]
        .map((e) => (e.id || e.tagName) + '=' + e.value).join(' '),
      fcount: ((document.getElementById('audit-fcount') || {}).textContent || '').trim(),
      clear: !!document.querySelector('.sectools [data-clear]:not([hidden])'),
    };
  });
  const hrDiff = (a, b) => Object.keys(a).filter((k) => a[k] !== b[k])
    .map((k) => `${k} ${JSON.stringify(b[k])} (no link: ${JSON.stringify(a[k])})`).join('; ');
  await openAt('');
  const hrBase = await hrSnap();
  const published = await hp.evaluate(() => document.documentElement.getAttribute('data-link-keys'));
  const pageKeys = (published || '').split(' ').filter(Boolean);
  const HR_KEYS = pageKeys.filter((k) => !HR_FREE_TEXT.includes(k));
  const staleFree = HR_FREE_TEXT.filter((k) => !pageKeys.includes(k));
  const leaked = [];
  const kept = [];
  const gaps = [];
  let bogusRan = 0;
  for (const key of HR_KEYS) {
    for (const bad of (HR_DATE_KEYS[key] ? HR_BOGUS_DATE : HR_BOGUS)) {
      await openAt(key + '=' + encodeURIComponent(bad));
      const d = hrDiff(hrBase, await hrSnap());
      bogusRan++;
      if (d) leaked.push(`${key}=${bad}: ${d}`);
    }
    // The allow half: a value the control offers comes back on.
    const offered = await hp.evaluate(([k, dateSels]) => {
      if (dateSels) {
        const f = dateSels.map((s) => document.querySelector(s)).find(Boolean);
        return f ? { v: f.min || f.max || '', sels: dateSels } : null;
      }
      const c = document.querySelector('[data-' + k + ']');
      return c ? { v: c.getAttribute('data-' + k) } : null;
    }, [key, HR_DATE_KEYS[key] || null]);
    if (!offered || !offered.v) { gaps.push(key); continue; }
    // An area link may name several tags: the one offered must survive the
    // bogus one beside it, not be dropped with it.
    const val = key === 'a' ? offered.v + ' ' + HR_BOGUS[0] : offered.v;
    await openAt(key + '=' + encodeURIComponent(val));
    const got = await hp.evaluate(([k, v, sels]) => {
      if (sels) return sels.map((s) => document.querySelector(s)).filter(Boolean).map((f) => f.value === v);
      return [...document.querySelectorAll('[data-' + k + ']')]
        .filter((c) => c.getAttribute('aria-pressed') === 'true')
        .map((c) => c.getAttribute('data-' + k) === v);
    }, [key, offered.v, offered.sels || null]);
    const ok = got.length > 0 && got.every(Boolean);
    kept.push(`${key}=${val}: ${ok ? 'on' : 'NOT restored (' + JSON.stringify(got) + ')'}`);
  }
  expect(`hr0 the running page publishes its registry's link keys (${published === null
    ? 'no data-link-keys on the root' : JSON.stringify(published)}), every one but free text `
    + `was driven, and the free-text exemption names a key the page still has`,
    published === null ? 'the page publishes no link keys'
      : !HR_KEYS.length ? 'no key to drive'
        : staleFree.length ? `exempt key the page no longer has: ${staleFree.join(', ')}`
          : bogusRan > 0 ? 'ok' : 'nothing driven',
    'ok');
  expect(`hr1 a link naming a value no control offers restores nothing, on every key of every `
    + `axis the registry declares (${HR_KEYS.join(',')}) - nothing hidden, nothing pressed, `
    + 'no field filled', !HR_KEYS.length ? 'no key driven' : (leaked.join(' · ') || 'none'), 'none');
  expect('hr2 a link naming a value its control offers restores it on'
    + (gaps.length ? ` (no control on this page for: ${gaps.join(', ')})` : ''),
    kept.filter((k) => !/: on$/.test(k)).join(' · ') || (kept.length ? 'none' : 'no axis had a control'),
    'none');

  // A status the restored view hides. The link writer never emits that pairing -
  // a view change clears a status it hides - so it is a hand-made link, or one
  // made before the plan's default view changed. Either way the reader asked
  // for those phases, and the page answers with a chip pressed for that status
  // and the phases of it drawn under a view that holds them, never with a
  // filter silently dropped or a pressed chip the view has hidden.
  const statuses = await hp.evaluate(() => [...document.querySelectorAll('#audit-phase-status [data-ps]')]
    .map((c) => c.getAttribute('data-ps')));
  const psWrong = [];
  for (const st of statuses) {
    await openAt('ps=' + encodeURIComponent(st));
    const r = await hp.evaluate((s) => {
      const chip = document.querySelector('#audit-phase-status [data-ps="' + s + '"]');
      const drawn = [...document.querySelectorAll('table.phases tbody tr.phase')]
        .filter((p) => p.style.display !== 'none');
      return { pressed: !!chip && chip.getAttribute('aria-pressed') === 'true' && !chip.hidden,
               drawn: drawn.length, other: drawn.filter((p) => p.getAttribute('data-status') !== s).length,
               view: (document.getElementById('audit-view') || {}).value || '' };
    }, st);
    if (!r.pressed || !r.drawn || r.other) psWrong.push(`ps=${st} in view ${r.view}: ${JSON.stringify(r)}`);
  }
  expect(`hr3 a link naming any status the plan has presses that chip and draws only its phases, `
    + `whatever view the page opens on (${statuses.length} statuses)`,
    psWrong.join(' · ') || (statuses.length ? 'none' : 'no status chips'), 'none');
  expect('hr4 the page raised no error while restoring links', hrErrors.slice(0, 2).join(' | ') || 'none', 'none');
  await hctx.close();
}

// --- a side-nav jump lights the section it lands on ----------------------------
// The nav's links are plain anchors and the marker is a script, so the two
// decide "which section is this" separately: the jump by the scroll-margin the
// stylesheet gives every id, the marker by the line it reads back off the same
// rule. When those lines differed the jump stopped just short of the marker's,
// and every click lit the section ABOVE the one it opened. And where the
// document ended before a target reached the line, the jump stopped short of
// it and a different entry was lit. Each visible entry is clicked at every
// size of the layout matrix, and the marker has to name it - with no
// exemption for the end of the document, which the stylesheet's room after
// the content is there to remove.
{
  const sctx = await browser.newContext({ viewport: { width: 1512, height: 945 } });
  const snp = await sctx.newPage();
  const snErrors = [];
  snp.on('pageerror', (e) => snErrors.push(e.message));
  const wrong = [];
  let clicked = 0;
  for (const { width: w, height: h } of LAYOUT_SIZES) {
    await snp.setViewportSize({ width: w, height: h });
    await snp.goto('about:blank');
    await snp.goto('file://' + path);
    await snp.waitForTimeout(150);
    const hrefs = await snp.evaluate(() => [...document.querySelectorAll('.snav a')]
      .filter((a) => a.getClientRects().length && getComputedStyle(a).visibility !== 'hidden')
      .map((a) => a.getAttribute('href')));
    for (const href of hrefs) {
      await snp.locator(`.snav a[href="${href}"]`).first().click();
      await snp.waitForTimeout(200);
      const r = await snp.evaluate((hr) => {
        const cur = document.querySelector('.snav a[aria-current="true"]');
        let t = null;
        try { t = document.getElementById(decodeURIComponent(hr.slice(1))); } catch (e) { t = null; }
        const top = t ? t.getBoundingClientRect().top : NaN;
        const line = t ? parseFloat(getComputedStyle(t).scrollMarginTop) || 0 : NaN;
        const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
        return { cur: cur ? cur.getAttribute('href') : '', top: Math.round(top), line: Math.round(line), atEnd };
      }, href);
      clicked++;
      if (r.cur === href) continue;
      wrong.push(`${w}x${h} ${href} lit ${r.cur || 'nothing'} (landed at ${r.top}px, line ${r.line}px`
        + `${r.atEnd ? ', the document ended first' : ''})`);
    }
  }
  await sctx.close();
  expect(`sn1 clicking a side-nav entry lights that entry, at every layout size `
    + `(${LAYOUT_SIZES.map((s) => s.width + 'x' + s.height).join(', ')}; ${clicked} clicks)`,
    clicked > 0 ? (wrong.join(' · ') || 'none') : 'no entry clicked', 'none');
  expect('sn2 the page raised no error while the side nav was driven',
    snErrors.slice(0, 2).join(' | ') || 'none', 'none');
}

assertLivenessWasChecked('report', liveness, {
  report: (m) => failures.push(`FAIL ${m}`),
  ok: (m) => notes.push(`ok   ${m}`),
});

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
    //
    // The capture runs to the OPENING delimiter (back-referenced), not to any
    // quote character. Stopping at any quote cost a whole afternoon: a label
    // reading `every "worked by" name is ...` truncated to `every`, and a
    // one-word label is a wildcard prefix - `c.label.startsWith('every')` matched
    // an unrelated conditional pair and reported it as a skipped leg. The bug was
    // in this line and every symptom appeared somewhere else.
    const m = line.match(/(?<![A-Za-z_.])expect\(\s*(['"`])((?:(?!\1)[^$])*)/);
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
  // Regions, parsed from this file's own source the way `declared` is. A marker
  // pair names a span whose assertions all depend on one thing being present, so
  // the exemption travels with the code instead of with a list of labels.
  const regions = {};
  const openAt = {};
  src.forEach((line, i) => {
    const start = line.match(/@needs-([a-z-]+)\b/);
    const end = line.match(/@end-needs-([a-z-]+)\b/);
    if (end) {
      const key = 'needs-' + end[1];
      if (openAt[key] === undefined) {
        failures.push(`FAIL line ${i + 1} closes the "${key}" region and none was open `
          + '— an unbalanced marker would exempt whatever follows it');
      } else {
        (regions[key] = regions[key] || []).push([openAt[key], i + 1]);
        delete openAt[key];
      }
    } else if (start) {
      const key = 'needs-' + start[1];
      if (openAt[key] !== undefined) {
        failures.push(`FAIL line ${i + 1} opens the "${key}" region while one is `
          + `already open at line ${openAt[key]} — nested markers have no meaning here`);
      }
      openAt[key] = i + 1;
    }
  });
  for (const [key, at] of Object.entries(openAt)) {
    failures.push(`FAIL the "${key}" region opened at line ${at} is never closed, so it `
      + 'would exempt every site below it');
  }
  // A region with no sites in it is a marker that excuses nothing and hides the
  // fact — the same shape as a conditional exemption whose check has gone.
  for (const [key, spans] of Object.entries(regions)) {
    for (const [from, to] of spans) {
      if (!declared.some((d) => d.line > from && d.line < to)) {
        failures.push(`FAIL the "${key}" region at lines ${from}-${to} contains no `
          + 'expect() call site — the marker outlived what it wrapped');
      }
    }
  }
  const inRegion = (key, line) =>
    (regions[key] || []).some(([from, to]) => line > from && line < to);

  // A feature that reported itself absent excuses the sites that ask about it —
  // by label, by region, or both. The note is required either way: with the
  // feature PRESENT, a marked site that never ran is still a skipped check.
  const absent = FEATURE_ABSENT.filter((f) => said.indexOf(f.note) >= 0);
  const excusedByAbsence = (label, line) => absent.some((f) =>
    (f.covers || []).some((c) => c === label || c.startsWith(label) || label.startsWith(c))
    || (f.region !== undefined && line !== undefined && inRegion(f.region, line)));
  const unexplained = missed.filter((d) => !d.label
    || (!CONDITIONAL_EXPECTS.some((c) => c.label.startsWith(d.label))
        && !excusedByAbsence(d.label, d.line)));
  if (unexplained.length) {
    failures.push(`FAIL ${unexplained.length} of ${declared.length} expect() call site(s) `
      + `never ran, so this report was graded on work that did not happen: `
      + unexplained.map((d) => `line ${d.line} ${JSON.stringify(d.label.slice(0, 48))}`)
        .join(' · '));
  }
  // A pair whose BOTH halves went silent is a skipped leg wearing an exemption.
  for (const c of CONDITIONAL_EXPECTS) {
    const skipped = missed.some((d) => d.label && c.label.startsWith(d.label));
    // A pair whose whole FEATURE is absent has no halves to run. Demanding one
    // of them there turns a report that simply does not use areas into a
    // failure, which is the overreach that gets a gate switched off.
    const at = (missed.find((d) => d.label && c.label.startsWith(d.label)) || {}).line;
    if (skipped && !excusedByAbsence(c.label, at) && said.indexOf(c.instead) < 0) {
      failures.push(`FAIL "${c.label}" was skipped and so was its counterpart `
        + `"${c.instead}" — the exemption says one of the two always runs, and `
        + `neither did, which is a skipped leg rather than a branch not taken`);
    }
  }
  // The table must describe this file, or it is a list of excuses for checks
  // that no longer exist.
  for (const f of FEATURE_ABSENT) {
    for (const c of f.covers) {
      if (!declared.some((d) => d.label
          && (c === d.label || c.startsWith(d.label) || d.label.startsWith(c)))) {
        failures.push(`FAIL the feature-absence table excuses ${JSON.stringify(c)}, `
          + `which no expect() call site declares any more`);
      }
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

// --- blessing a layout move, the one thing this tool may WRITE ----------------
//
// EASY TO BLESS: the command is printed under the finding that asks for it, and it
// is this same gate with one flag, so a figure can only be recorded by a run that
// actually measured it.
//
// HARD TO BLESS BY ACCIDENT, in three ways that cost nothing to keep:
//   * a plain run never writes. The measurement and the recording are the same
//     code, but only the flag reaches the filesystem;
//   * a run with any OTHER failure refuses. A figure blessed off a report whose
//     interactions are broken is a figure recorded from a page nobody has seen
//     working, and that is the state a regression is most likely to be in;
//   * one document per invocation, so each blessing is one row in one diff, with
//     the old value on the line above the new one.
// What it deliberately does NOT do is decide whether the move was legitimate. That
// is a judgement, the diff is where it is reviewed, and a tool that made it would
// be the arm switching itself off.
if (RECORDING) {
  const cmdFailures = new Set(layout.failures.map((f) => `FAIL ${f}`));
  const others = failures.filter((f) => !cmdFailures.has(f));
  const key = documentKey(path);
  const { baseline, problem } = readBaseline();
  const table = problem === null ? baseline : emptyBaseline(PHONE_VIEWPORT);
  const sameViewport = table.viewport.width === PHONE_VIEWPORT.width
    && table.viewport.height === PHONE_VIEWPORT.height;
  if (layout.refusal !== null) {
    // A POSITIVE reason not to record, never "nothing to record". The two are
    // different sentences and only one of them is true here: a document the
    // baseline is not about has no row to match, so "every figure already matches"
    // would be a cheerful way of saying nothing happened.
    console.log(`\nREFUSING TO RECORD: ${layout.refusal}. Nothing was written.`);
    process.exit(1);
  }
  if (key === null) {
    console.log(`\nREFUSING TO RECORD: ${file} is not in this checkout, and the baseline `
      + 'records the committed reports of this repository. Nothing was written.');
    process.exit(1);
  }
  if (others.length) {
    console.log(`\nREFUSING TO RECORD: ${others.length} failure(s) above are not layout `
      + 'figures, so this report is not a page to take a measurement from. Fix those '
      + 'first. Nothing was written.');
    process.exit(1);
  }
  if (!sameViewport && Object.keys(table.documents).length) {
    console.log(`\nREFUSING TO RECORD: the baseline was recorded at ${table.viewport.width}x`
      + `${table.viewport.height} and this run measured at ${PHONE_VIEWPORT.width}x`
      + `${PHONE_VIEWPORT.height}. Recording one document would leave every other row a `
      + 'share of a screen nothing measured at. Delete the file and record each document '
      + 'again. Nothing was written.');
    process.exit(1);
  }
  if (layout.recordable === null) {
    console.log(`\nnothing to record: every figure recorded for ${key} already matches `
      + 'this run, so the file is unchanged.');
    process.exit(0);
  }
  const applied = applyRecording(table, key, layout.recordable, PHONE_VIEWPORT);
  writeBaseline(applied.baseline);
  console.log(`\nrecorded ${key}:`);
  for (const c of applied.changes) {
    console.log(`  ${c.metric}: ${c.from === undefined ? '(none)' : `${c.from}%`}`
      + ` -> ${c.to === undefined ? '(gone)' : `${c.to}%`}`);
  }
  console.log('Commit tools/ui-checks/report-layout-baseline.json with the change that '
    + 'moved it: the recorded figure is a claim that the move was meant.');
  process.exit(0);
}

// The fonts the layout matrix read the page in, on the summary line itself: a
// pass that could not run is said where the verdict is read, not only in a note.
console.log(
  (failures.length
    ? `\nREPORT IS INERT: ${failures.length} interaction(s) did not work in ${file}`
    : `\nreport is interactive: ${notes.length} checks passed in ${file}`)
  + `\nlayout matrix fonts: ${FONT_PASSES.join('; ') || 'the matrix did not run'}`);
process.exit(failures.length ? 1 : 0);
