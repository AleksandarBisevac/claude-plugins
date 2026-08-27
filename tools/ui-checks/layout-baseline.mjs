/**
 * The RELATIVE arm beside the report gate's absolute one (F219).
 *
 * WHAT WENT WRONG. `check-report-interactive.mjs` bounds the share of a phone
 * screen an OPEN filter panel may pin over the table it filters. That bar is
 * absolute — over it is a defect, under it is not — and it is the right thing to
 * bound: a layer that eats half the screen has stopped being a layer. What it
 * cannot see is a fixture that MOVES. Restoring the height bound's absence showed
 * `docs/demo-large.html` going red and `examples/acme-store/...` staying green on
 * the same regression, because the threshold happened to fall between the two
 * documents; the example had grown to nearly four times its former height under a
 * gate that could not say so, and what gave it away was its neighbour failing. Had
 * the change touched only the example, the regression would have shipped.
 *
 * SO THERE ARE TWO QUESTIONS AND THEY FAIL APART.
 *
 *   absolute — how much of the screen does the open bar PIN over the table after
 *              the reader has scrolled past it? Owned by the gate, unchanged, and
 *              reported on its own line.
 *   relative — how tall is that bar, as a share of the screen, compared with the
 *              figure this repository recorded for THIS document? Owned here.
 *
 * They measure different quantities on purpose, so a reader who sees one red knows
 * which they have. The absolute one saturates — the gate scrolls a fixed distance
 * past the bar, so every bar shorter than that scroll reports the same zero — and
 * a baseline built on a saturating measurement would be blind over its whole lower
 * range. The height share saturates nowhere.
 *
 * WHAT THE PAIR DOES AND DOES NOT BUY. The relative arm catches a JUMP; the
 * absolute arm catches the DESTINATION. Neither catches slow creep on its own —
 * enough sub-tolerance moves in one direction eventually arrive somewhere the
 * absolute bar does not like, and that is the run that goes red. Saying so is
 * cheaper than pretending a tolerance is a ratchet.
 *
 * TWO FIGURES, BECAUSE THE PAIR IS A DECOMPOSITION AND NOT A DUPLICATE. Today the
 * open bar is the shut bar plus the panel's own `max-height` cap plus a margin, so
 * the two figures move together — and that is exactly what makes them worth
 * recording apart. If both move, the bar's own controls grew; if only the open one
 * moves, the panel's height bound is what broke, which is F219 by name. One figure
 * could report that something moved and never which.
 *
 * The shut figure has NO absolute bar and is not getting one here: there is no
 * defensible constant for "a resting toolbar is too tall", and inventing one would
 * be the same arbitrary number this file exists to avoid. A recorded figure is the
 * honest instrument for a quantity with no natural bound — which is also why it is
 * worth having, since the gate's own comment records that bar at 156px on this
 * viewport and it measures over 200px today, with nothing having watched it grow.
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// --- what is recorded, at what size, and how far it may move -----------------

/** This checkout's root, from this file's own location rather than from cwd. */
export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * Repo-relative, because it is printed to a human and named in a diff.
 *
 * NOT A RELEASE FOLLOWER, and that is a decision rather than an omission. A version
 * bump stales the rendered artifacts because every report stamps the version it was
 * produced by — but the stamp lives in the page's header and these figures are the
 * height of the filter chrome on a phone, so re-rendering at a new version changes
 * the bytes and not the layout. Adding a non-follower to `verify.sh --release`'s
 * list would make the list wrong in the direction that matters: its whole value is
 * that it is the exact set a bump stales, and a reader who re-does a step that was
 * not stale learns to skim the others. If that assumption is ever false, the gate
 * that reads this file goes red on the next run and prints the command that fixes
 * it — which is a cheaper way to find out than a sentence in a document.
 */
export const BASELINE_REL = 'tools/ui-checks/report-layout-baseline.json';

/** @type {string} */
export const BASELINE_PATH = join(REPO_ROOT, ...BASELINE_REL.split('/'));

/**
 * The screen every recorded figure is a share OF, defined here and imported by the
 * gate so there is one copy. A recorded percentage is meaningless without the
 * viewport it was taken at, so the file stores this too and a run that measures at
 * a different size REFUSES to compare rather than comparing a share of one screen
 * against a share of another.
 * @type {{width: number, height: number}}
 */
export const PHONE_VIEWPORT = { width: 390, height: 780 };

/**
 * How far a recorded figure may move before a human has to say it was meant, in
 * PERCENTAGE POINTS of the viewport's height — the same unit the figures are in,
 * and the unit a reader experiences ("this much of my screen is gone"). A ratio
 * was the alternative and is wrong for a quantity that is already a share: it
 * makes a small figure hair-triggered (5% to 10% is a doubling and 39px) and a
 * large one deaf (70% to 90% is a fifth and 156px).
 *
 * THE NUMBER IS DEFENDED BY THE GAP BETWEEN TWO MEASURED POPULATIONS, not chosen
 * for feel. On this viewport a point is 7.8px.
 *
 *   the largest LEGITIMATE single step. The bar and the panel are stacks of
 *   control rows, and a design change adds, removes or rewraps rows. Measured in
 *   the shipped reports: a chip row is 23px and a date input 38px, each with a
 *   .7rem gap, so one new row costs 4pp at the low end and 6pp at the high end.
 *   The panel's own cap is written in `vh`, and moving it by the 5vh anyone would
 *   plausibly move it by costs 5pp. Call the top of that band 6pp, and add the
 *   rounding noise of an integer percentage, which is half a point.
 *
 *   the smallest REGRESSION of the class this arm exists for. F219 restored —
 *   the filter panel with its height bound removed — moves the example by 30pp
 *   and the scale demo by 32pp. Nothing about those numbers was specific to the
 *   axes that happened to exist; the panel's content height is a property of
 *   somebody else's manifest, which is why it was capped at all.
 *
 * So any value from about 7 to about 25 behaves identically on every change either
 * population has ever produced, and the choice inside that gap is not fine-tuning.
 * It sits at the TIGHT end because the two mistakes cost differently: a false red
 * costs one re-record and a line in a diff, and a false green ships F219.
 *
 * A move is judged in BOTH directions. A figure that collapses is not good news —
 * it is what a filter panel that stopped rendering looks like, and the absolute
 * bar can never see a shrink.
 * @type {number}
 */
export const TOLERANCE_PP = 8;

/**
 * The recorded figures, in the order a reader wants them. The key is what the file
 * stores and the label is what a finding says, kept together so a renamed figure
 * cannot go on being reported under the old words.
 * @type {Array<{key: string, label: string}>}
 */
export const METRICS = [
  { key: 'filterBarShutShare',
    label: 'the sticky filter bar with its panel shut' },
  { key: 'filterBarOpenShare',
    label: 'the sticky filter bar with its panel open' },
];

const METRIC_KEYS = METRICS.map((m) => m.key);

/** A pixel height as a whole percentage of the viewport it was measured on. */
export const share = (px, viewportHeight) => Math.round((px / viewportHeight) * 100);

/**
 * The command that re-records one document, printed BESIDE every finding that
 * asks for it — the shape `check-rendered-artifacts.py` prints under each stale
 * artifact. A red gate that does not say how to go green teaches a follower list
 * one failure at a time.
 */
export const recordCommand = (reportPath) =>
  `node tools/check-report-interactive.mjs ${reportPath} --record`;

// --- reading the file, and refusing when it cannot be read -------------------

/**
 * `{baseline, problem}` — exactly one is null.
 *
 * MISSING IS A PROBLEM AND NOT AN EMPTY TABLE. A file that is not there, or will
 * not parse, or does not carry the shape this reads, means the relative arm made
 * no claim at all — and "could not look" must never print like "looked and found
 * nothing wrong". `check-committed-pii.py`'s `domain-unavailable` row is the same
 * refusal one tool over.
 */
export function readBaseline(path = BASELINE_PATH) {
  let text;
  try {
    text = readFileSync(path, 'utf8');
  } catch (e) {
    // The two are worded apart because they are two different repairs: a file
    // that is not there has to be built, and one that is there and unreadable is
    // a permission or an encoding to fix before anything is recorded over it.
    return { baseline: null,
      problem: e.code === 'ENOENT'
        ? `is not in this tree (${BASELINE_REL})`
        : `cannot be read (${BASELINE_REL}: ${e.code || e.message})` };
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return { baseline: null, problem: `will not parse as JSON: ${e.message}` };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { baseline: null, problem: 'is not a JSON object' };
  }
  const { viewport, documents } = parsed;
  if (!viewport || typeof viewport.width !== 'number' || typeof viewport.height !== 'number') {
    return { baseline: null,
      problem: 'records no viewport, so nothing in it says what its figures are a share OF' };
  }
  if (!documents || typeof documents !== 'object' || Array.isArray(documents)) {
    return { baseline: null, problem: 'carries no `documents` table' };
  }
  return { baseline: parsed, problem: null };
}

/**
 * The key a report is recorded under: its path relative to this checkout, with
 * forward slashes. `null` when the report is not in this tree at all — which is
 * the normal case for the throwaway documents CI renders into a temp directory,
 * and the reason a missing row cannot simply be a failure everywhere.
 */
export function documentKey(reportPath, repoRoot = REPO_ROOT) {
  const rel = relative(repoRoot, resolve(reportPath));
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) return null;
  return rel.split(sep).join('/');
}

/**
 * `{state, why}` — is this a document the baseline is ABOUT?
 *
 * ASKED ONLY WHEN THERE IS NO ROW, which is what keeps a git dependency off the
 * normal path: a document with a recorded row has already answered the question by
 * having one. Without a row there are two very different documents in the same
 * place — a committed report whose row somebody deleted, and a scratch render
 * somebody made this afternoon (this repo dogfoods its own plugin, and
 * `/audit:report` writes an ignored HTML file into `docs/audit/`). Demanding a row
 * for the second would invite a row for a file no other checkout has, which the
 * table rule above would then report as dead for everybody else.
 *
 *   'tracked'   git carries this path: a committed report, and it owes a row
 *   'untracked' in the tree but not in the repository: a scratch render
 *   'unknown'   git could not be asked, so this run cannot tell the two apart
 *
 * The third is a finding and never a pass. `check-committed-pii.py` refuses the
 * same way for the same reason when git cannot say what a tree tracks.
 */
export function trackedState(key, repoRoot = REPO_ROOT) {
  const r = spawnSync('git', ['-C', repoRoot, 'ls-files', '--error-unmatch', '--', key],
    { encoding: 'utf8' });
  if (r.error) return { state: 'unknown', why: r.error.code || r.error.message };
  if (r.status === 0) return { state: 'tracked', why: null };
  // 1 is "no such tracked path" and everything else is git declining to answer —
  // 128 for a directory that is not a repository, most often. Read by CODE and not
  // by the wording of the message, which is localised and has changed before.
  if (r.status === 1) return { state: 'untracked', why: null };
  return { state: 'unknown',
    why: ((r.stderr || '').trim().split('\n')[0] || `git exited ${r.status}`) };
}

/**
 * What is wrong with the TABLE itself, regardless of which document is being
 * driven — checked on every run, because a table that has stopped describing this
 * tree is how a recorded figure quietly stops being read.
 *
 * Both directions of the one rule: a row naming a document that is not here any
 * more records a figure nothing will ever compare again, and a row carrying a key
 * no metric measures is a number that cannot go stale loudly.
 */
export function tableProblems(baseline, repoRoot = REPO_ROOT) {
  const out = [];
  for (const key of Object.keys(baseline.documents).sort()) {
    if (!existsSync(join(repoRoot, ...key.split('/')))) {
      out.push(`${BASELINE_REL} records "${key}", which is not in this tree any more `
        + '— a row for a document nobody renders is a figure nothing checks');
    }
    const row = baseline.documents[key];
    if (!row || typeof row !== 'object' || Array.isArray(row)) {
      out.push(`${BASELINE_REL} records "${key}" as something other than a table of figures`);
      continue;
    }
    for (const metric of Object.keys(row).sort()) {
      if (METRIC_KEYS.indexOf(metric) < 0) {
        out.push(`${BASELINE_REL} records "${metric}" for "${key}", which no metric here `
          + 'measures — a recorded figure nothing reads cannot go stale loudly');
      } else if (typeof row[metric] !== 'number') {
        out.push(`${BASELINE_REL} records "${metric}" for "${key}" as `
          + `${JSON.stringify(row[metric])} rather than a number`);
      }
    }
  }
  return out;
}

// --- the verdict -------------------------------------------------------------

/**
 * Judge one driven document against the recorded figures.
 *
 * @param {Object} args
 * @param {string} args.reportPath the document the gate is driving
 * @param {Object} args.measured   {metricKey: percentage}, only what this run measured
 * @param {{width: number, height: number}} args.viewport what it measured at
 * @param {string} [args.baselinePath]
 * @param {string} [args.repoRoot]
 * @returns {{failures: string[], notes: string[], recordable: ?Object, refusal: ?string}}
 *   `recordable` is the measured figures when `--record` could write them, and
 *   null when there is nothing a recording could fix. `refusal` is set only where
 *   there is a POSITIVE reason not to record — a document the baseline is not
 *   about — so the recorder can say that instead of "nothing to record", which
 *   would be a different sentence and a false one.
 */
export function judge({ reportPath, measured, viewport,
                        baselinePath = BASELINE_PATH, repoRoot = REPO_ROOT }) {
  const failures = [];
  const notes = [];
  const cmd = recordCommand(reportPath);
  const { baseline, problem } = readBaseline(baselinePath);
  if (problem !== null) {
    failures.push(`the recorded layout baseline ${problem}, so the relative arm made no `
      + `claim about this report — "could not look" is not "clean". Rebuild it with: ${cmd}`);
    return { failures, notes, recordable: measured, refusal: null };
  }
  for (const p of tableProblems(baseline, repoRoot)) failures.push(p);

  if (baseline.viewport.width !== viewport.width
      || baseline.viewport.height !== viewport.height) {
    failures.push('the layout baseline was recorded at '
      + `${baseline.viewport.width}x${baseline.viewport.height} and this run measured at `
      + `${viewport.width}x${viewport.height}, so every recorded figure is a share of a `
      + `different screen. Re-record every document, starting with: ${cmd}`);
    return { failures, notes, recordable: measured, refusal: null };
  }

  const key = documentKey(reportPath, repoRoot);
  if (key === null) {
    notes.push('no recorded layout baseline applies: this document is not in this '
      + 'checkout, so the relative arm did not run for it (the absolute bar above did)');
    return { failures, notes, recordable: null,
      refusal: 'it is not in this checkout, and the baseline records the committed '
        + 'reports of this repository' };
  }
  const row = baseline.documents[key];
  if (row === undefined) {
    const tracked = trackedState(key, repoRoot);
    if (tracked.state === 'untracked') {
      notes.push(`no recorded layout baseline applies: "${key}" is in the tree but not in `
        + 'the repository, so it is a scratch render rather than a committed report and '
        + 'the relative arm did not run for it (the absolute bar above did)');
      return { failures, notes, recordable: null,
        refusal: `"${key}" is in the tree but not in the repository, so it is a scratch `
          + 'render rather than a committed report the baseline is about' };
    }
    if (tracked.state === 'unknown') {
      failures.push(`the layout baseline records no row for "${key}" and git could not be `
        + `asked whether it is a committed report (${tracked.why}), so this run cannot tell `
        + 'a lost row from a scratch render — and neither is something to pass over');
      return { failures, notes, recordable: null,
        refusal: `git could not be asked whether "${key}" is a committed report `
          + `(${tracked.why}), so recording it might add a row no other checkout has` };
    }
    failures.push(`the layout baseline records no row for "${key}", a committed report of `
      + 'this repository, so the relative arm cannot say whether its layout moved. '
      + `Record it with: ${cmd}`);
    return { failures, notes, recordable: measured, refusal: null };
  }

  const moved = [];
  for (const { key: metric, label } of METRICS) {
    const before = row[metric];
    const now = measured[metric];
    if (before === undefined && now === undefined) continue;
    if (before === undefined) {
      failures.push(`this run measured ${label} at ${now}% of the screen and the layout `
        + `baseline records no "${metric}" for "${key}" — a half-recorded row leaves the `
        + `figure it omits unwatched. Record it with: ${cmd}`);
      moved.push(metric);
      continue;
    }
    if (now === undefined) {
      failures.push(`the layout baseline records ${label} for "${key}" and this run did `
        + `not measure it — the thing "${metric}" is about is not on this report any more`);
      continue;
    }
    const delta = now - before;
    if (Math.abs(delta) <= TOLERANCE_PP) {
      notes.push(`${label} still measures what was recorded for "${key}" `
        + `(${now}% of the screen, recorded ${before}%, tolerance ${TOLERANCE_PP}pp)`);
      continue;
    }
    moved.push(metric);
    failures.push(`${label} ${delta > 0 ? 'grew' : 'shrank'} from a recorded ${before}% of `
      + `the screen to ${now}% (${delta > 0 ? '+' : ''}${delta}pp against a ${TOLERANCE_PP}pp `
      + `tolerance) in "${key}". This is the RELATIVE arm — whether the open panel also pins `
      + `too much of the screen is a separate line above. If the move was meant, bless it `
      + `with: ${cmd}`);
  }
  return { failures, notes, recordable: moved.length ? measured : null, refusal: null };
}

// --- writing one row back ----------------------------------------------------

/**
 * `{baseline, changes}` — the table with one document's figures replaced, and what
 * moved. A pure function so the writer below has nothing to decide.
 *
 * Only the named document is touched. A recorder that rebuilt the whole file from
 * one run would drop every row it did not drive, which is a way to turn the arm
 * off for two documents while blessing a third.
 */
export function applyRecording(baseline, key, measured, viewport) {
  const documents = Object.assign({}, baseline.documents);
  const before = documents[key] || {};
  const after = {};
  const changes = [];
  for (const { key: metric } of METRICS) {
    if (measured[metric] === undefined) continue;
    after[metric] = measured[metric];
    if (before[metric] !== measured[metric]) {
      changes.push({ metric, from: before[metric], to: measured[metric] });
    }
  }
  for (const metric of Object.keys(before)) {
    if (after[metric] === undefined && measured[metric] === undefined) {
      changes.push({ metric, from: before[metric], to: undefined });
    }
  }
  documents[key] = after;
  return { baseline: Object.assign({}, baseline, { viewport, documents }), changes };
}

/**
 * The file's bytes. Every key is sorted, because an unordered serialization
 * reshuffles the file on each write and the one line that moved drowns in the
 * noise — which is the whole reason this artifact is worth committing.
 */
export function serialize(baseline) {
  const documents = {};
  for (const key of Object.keys(baseline.documents).sort()) {
    const row = baseline.documents[key];
    const sorted = {};
    for (const metric of Object.keys(row).sort()) sorted[metric] = row[metric];
    documents[key] = sorted;
  }
  const doc = {
    about: 'Recorded layout figures for the committed reports, as whole percentages '
      + 'of the viewport below. The gate that reads them is tools/check-report-'
      + 'interactive.mjs; re-record one document with `node tools/check-report-'
      + 'interactive.mjs <report.html> --record`. Blessing a move here is a claim '
      + 'that the move was meant.',
    viewport: { width: baseline.viewport.width, height: baseline.viewport.height },
    documents,
  };
  return `${JSON.stringify(doc, null, 2)}\n`;
}

/**
 * Write the table. Separated from `applyRecording` so every decision is testable
 * without a filesystem, and so this function has exactly one failure mode.
 */
export function writeBaseline(baseline, path = BASELINE_PATH) {
  writeFileSync(path, serialize(baseline), 'utf8');
}

/**
 * An empty table, for the one legitimate case where there is nothing to read: the
 * file has never existed. Its viewport comes from the run doing the recording, so
 * a bootstrapped file cannot claim a size nothing measured at.
 */
export const emptyBaseline = (viewport) => ({ viewport, documents: {} });
