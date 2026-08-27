// The relative layout arm's decisions, without a browser.
//
// The measurement needs Chromium; nothing else here does. Reading the recorded
// file, refusing when it cannot be read, deciding what counts as a move and
// writing one row back are all pure, and they are where the interesting failures
// live — so they are asserted here rather than only being exercised through a
// 30-second gate run against three documents that all happen to be current.
//
// EVERY CONDITIONAL FIX HAS TWO WRONG IMPLEMENTATIONS and only one of them is the
// bug you started with. An arm that never fires is F219 back; an arm that always
// fires is a gate somebody switches off. The cases that catch the second read as
// vacuous — a figure inside the tolerance emits NO failure, a document outside the
// checkout emits no failure — and they say so in a comment so they survive review.
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { METRICS, PHONE_VIEWPORT, TOLERANCE_PP, applyRecording, documentKey,
         emptyBaseline, judge, readBaseline, serialize, share, tableProblems,
         trackedState } from '../ui-checks/layout-baseline.mjs';

const VIEW = PHONE_VIEWPORT;
const DOC = 'examples/acme-store/acme-store-audit.html';
const OTHER = 'docs/demo-large.html';

let root;
let baselinePath;

/** A checkout-shaped temp tree: the two documents exist, so a row for either is live. */
beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'layout-baseline-'));
  mkdirSync(join(root, 'examples', 'acme-store'), { recursive: true });
  mkdirSync(join(root, 'docs'), { recursive: true });
  writeFileSync(join(root, DOC), '<html></html>', 'utf8');
  writeFileSync(join(root, OTHER), '<html></html>', 'utf8');
  baselinePath = join(root, 'baseline.json');
});
afterEach(() => rmSync(root, { recursive: true, force: true }));

const write = (obj) => writeFileSync(baselinePath, JSON.stringify(obj, null, 2), 'utf8');

/** A real repository in the temp tree, so `trackedState` is asked of git itself. */
const git = (...argv) => {
  const r = spawnSync('git', ['-C', root, ...argv], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`git ${argv.join(' ')}: ${r.stderr || r.status}`);
};
const gitInit = () => {
  git('init', '-q');
  git('config', 'user.email', 'suite@example.invalid');
  git('config', 'user.name', 'suite');
};
const gitAdd = (rel) => git('add', '--', rel);

const table = (rows, viewport = VIEW) => ({ viewport, documents: rows });

const ask = (measured, reportPath = join(root, DOC)) =>
  judge({ reportPath, measured, viewport: VIEW, baselinePath, repoRoot: root });

// --- could not look is not clean ---------------------------------------------

describe('a baseline that cannot be read', () => {
  it('reports a file that is not there, and says so in its own words', () => {
    const { baseline, problem } = readBaseline(baselinePath);
    expect(baseline).toBe(null);
    expect(problem).toMatch(/is not in this tree/);
  });

  it('reports an unreadable file DIFFERENTLY from an absent one', () => {
    // A directory where a file belongs: readFileSync raises EISDIR on every
    // platform, and no chmod is involved, so the case means the same thing when
    // the suite is run as root.
    mkdirSync(baselinePath);
    const { problem } = readBaseline(baselinePath);
    expect(problem).toMatch(/cannot be read/);
    // The two repairs are different — build it vs. fix the permission — so the
    // two sentences must be too. Compared rather than merely both matching, so a
    // future edit that collapses them into one wording fails here.
    mkdirSync(join(root, 'gone'), { recursive: true });
    expect(problem).not.toBe(readBaseline(join(root, 'gone', 'nothing.json')).problem);
  });

  it('reports a file that will not parse', () => {
    writeFileSync(baselinePath, '{ not json', 'utf8');
    expect(readBaseline(baselinePath).problem).toMatch(/will not parse/);
  });

  it('refuses a file with no viewport, which is a figure with no basis', () => {
    write({ documents: {} });
    expect(readBaseline(baselinePath).problem).toMatch(/no viewport/);
  });

  it('refuses a file with no documents table', () => {
    write({ viewport: VIEW });
    expect(readBaseline(baselinePath).problem).toMatch(/no `documents` table/);
  });

  it('turns an unreadable baseline into a FAILURE carrying the way out', () => {
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/"could not look" is not "clean"/);
    expect(out.failures[0]).toMatch(/--record/);
    // ...and it is recordable, because rebuilding the file is exactly the repair.
    expect(out.recordable).not.toBe(null);
  });
});

// --- the figures --------------------------------------------------------------

describe('judging one document', () => {
  it('says nothing when the figures still hold', () => {
    // THE SECOND-DIRECTION CASE for the whole arm: it passes on the pre-F219 code
    // by construction, and it is the only case that fails if the comparison
    // becomes unconditional. Keep it.
    write(table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toEqual([]);
    expect(out.notes).toHaveLength(METRICS.length);
    expect(out.recordable).toBe(null);
  });

  it('holds its tolerance at the boundary, on both sides of it', () => {
    // The fixture values are chosen so `<` and `<=` disagree: a move of EXACTLY
    // the tolerance is allowed and one point further is not. A case that only
    // tested a 30-point move would pass against either.
    write(table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 } }));
    const atLimit = ask({ filterBarShutShare: 30 + TOLERANCE_PP,
      filterBarOpenShare: 76 - TOLERANCE_PP });
    expect(atLimit.failures).toEqual([]);
    const past = ask({ filterBarShutShare: 30 + TOLERANCE_PP + 1,
      filterBarOpenShare: 76 - TOLERANCE_PP - 1 });
    expect(past.failures).toHaveLength(2);
  });

  it('reports a growth and a shrink of the same size apart', () => {
    // A shrink is not good news: it is what a filter panel that stopped rendering
    // looks like, and the absolute bar can never see one. Both directions are
    // judged at the same magnitude so a one-sided comparison fails here.
    write(table({ [DOC]: { filterBarOpenShare: 76 } }));
    const grew = ask({ filterBarOpenShare: 76 + TOLERANCE_PP + 20 });
    const shrank = ask({ filterBarOpenShare: 76 - TOLERANCE_PP - 20 });
    expect(grew.failures).toHaveLength(1);
    expect(shrank.failures).toHaveLength(1);
    expect(grew.failures[0]).toMatch(/grew from a recorded 76%/);
    expect(shrank.failures[0]).toMatch(/shrank from a recorded 76%/);
    expect(grew.failures[0]).toMatch(/\+28pp/);
    expect(shrank.failures[0]).toMatch(/-28pp/);
  });

  it('names the two arms apart in the words it uses', () => {
    // The absolute bar and this are two questions, and a reader who sees one red
    // has to know which. If this sentence ever stops distinguishing them, the
    // failure they read is ambiguous.
    write(table({ [DOC]: { filterBarOpenShare: 76 } }));
    const out = ask({ filterBarOpenShare: 105 });
    expect(out.failures[0]).toMatch(/RELATIVE arm/);
    expect(out.failures[0]).toMatch(/separate line above/);
  });

  it('refuses a COMMITTED document with no recorded row', () => {
    // A REAL git repository, not a stub. The question "is this a committed report"
    // is git's, and a fake that answered it here would encode this file's
    // assumption about git rather than git's behaviour — which is the shape of
    // fixture that leaves a guard green against a case it cannot handle.
    gitInit();
    gitAdd(DOC);
    write(table({ [OTHER]: { filterBarOpenShare: 79 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/records no row for "examples\/acme-store/);
    expect(out.failures[0]).toMatch(/committed report/);
    expect(out.recordable).not.toBe(null);
    expect(out.refusal).toBe(null);
  });

  it('says a tracked-but-unrecorded document apart from a scratch render', () => {
    // THE SECOND DIRECTION of the rule above, and the reason it consults git at
    // all: this repo dogfoods its own plugin, so an ignored report can sit in
    // `docs/audit/` at any moment. Demanding a row for it would invite a row no
    // other checkout has — which the dead-row rule then reports for everybody.
    gitInit();
    gitAdd(OTHER);                       // ...and DOC deliberately left untracked
    write(table({ [OTHER]: { filterBarOpenShare: 79 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toEqual([]);
    expect(out.notes).toHaveLength(1);
    expect(out.notes[0]).toMatch(/not in the repository/);
    expect(out.refusal).toMatch(/scratch render/);
  });

  it('refuses when git cannot be asked which of the two it is', () => {
    // No `git init` here: "could not look" is not "clean", and the two things it
    // could not tell apart need opposite treatment.
    write(table({ [OTHER]: { filterBarOpenShare: 79 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/git could not be asked/);
    expect(out.recordable).toBe(null);
    expect(out.refusal).toMatch(/no other checkout has/);
  });

  it('needs no git at all once the row exists', () => {
    // The tracked question is asked ONLY where there is no row, which keeps the
    // normal path free of it. This temp tree is not a repository, and the
    // comparison still happens.
    write(table({ [DOC]: { filterBarOpenShare: 76 } }));
    expect(trackedState(DOC, root).state).toBe('unknown');
    expect(ask({ filterBarOpenShare: 76 }).failures).toEqual([]);
  });

  it('says out loud that it did not run for a document outside the checkout', () => {
    // THE OTHER SECOND-DIRECTION CASE. CI renders throwaway reports into a temp
    // directory and drives this gate over them; demanding a recorded row there
    // would turn every one of those steps red. The note is required so the run
    // never reads as "compared, and fine".
    write(table({ [DOC]: { filterBarOpenShare: 76 } }));
    const elsewhere = mkdtempSync(join(tmpdir(), 'not-the-checkout-'));
    try {
      const out = judge({ reportPath: join(elsewhere, 'r.html'),
        measured: { filterBarOpenShare: 999 }, viewport: VIEW, baselinePath, repoRoot: root });
      expect(out.failures).toEqual([]);
      expect(out.notes).toHaveLength(1);
      expect(out.notes[0]).toMatch(/did not run for it/);
      expect(out.recordable).toBe(null);
    } finally {
      rmSync(elsewhere, { recursive: true, force: true });
    }
  });

  it('refuses to compare shares of two different screens', () => {
    write(table({ [DOC]: { filterBarOpenShare: 76 } }, { width: 412, height: 915 }));
    const out = ask({ filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/share of a different screen/);
    // ...and it compared NOTHING. A run that reported the mismatch and then went
    // on comparing would be reading one screen's figure against another's.
    expect(out.notes).toEqual([]);
  });

  it('reports a recorded figure this run could not measure', () => {
    // The panel disappearing from a report is a regression the absolute bar
    // cannot see either: with nothing to measure, it has nothing to exceed.
    write(table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 } }));
    const out = ask({ filterBarShutShare: 30 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/did not measure it/);
  });

  it('reports a measured figure the row does not carry', () => {
    write(table({ [DOC]: { filterBarShutShare: 30 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/half-recorded row/);
  });
});

// --- the table must describe this tree ----------------------------------------

describe('the recorded table itself', () => {
  it('reports a row for a document that is not here any more', () => {
    const problems = tableProblems(table({ 'docs/gone.html': { filterBarOpenShare: 1 } }), root);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/not in this tree any more/);
  });

  it('reports a recorded key no metric measures', () => {
    const problems = tableProblems(table({ [DOC]: { filterBarWidthShare: 12 } }), root);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/which no metric here measures/);
  });

  it('reports a figure that is not a number', () => {
    const problems = tableProblems(table({ [DOC]: { filterBarOpenShare: '76%' } }), root);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/rather than a number/);
  });

  it('says nothing about a table that describes this tree', () => {
    // Second direction again: every row above is a live row here.
    expect(tableProblems(table({ [DOC]: { filterBarShutShare: 30 },
      [OTHER]: { filterBarOpenShare: 79 } }), root)).toEqual([]);
  });

  it('carries table problems into the verdict for whichever document is driven', () => {
    write(table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 },
      'docs/gone.html': { filterBarOpenShare: 1 } }));
    const out = ask({ filterBarShutShare: 30, filterBarOpenShare: 76 });
    expect(out.failures).toHaveLength(1);
    expect(out.failures[0]).toMatch(/docs\/gone\.html/);
  });
});

// --- recording ----------------------------------------------------------------

describe('recording one row', () => {
  it('replaces only the named document', () => {
    // COUNTED, not merely present: a recorder that rebuilt the file from one run
    // would leave exactly one document behind and every assertion about that one
    // would still pass.
    const before = table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 },
      [OTHER]: { filterBarShutShare: 33, filterBarOpenShare: 79 } });
    const { baseline, changes } = applyRecording(before, DOC,
      { filterBarShutShare: 30, filterBarOpenShare: 105 }, VIEW);
    expect(Object.keys(baseline.documents)).toHaveLength(2);
    expect(baseline.documents[OTHER]).toEqual({ filterBarShutShare: 33, filterBarOpenShare: 79 });
    expect(changes).toEqual([{ metric: 'filterBarOpenShare', from: 76, to: 105 }]);
  });

  it('records a figure the row did not have, and drops one nothing measures', () => {
    const grown = applyRecording(table({ [DOC]: { filterBarShutShare: 30 } }), DOC,
      { filterBarShutShare: 30, filterBarOpenShare: 76 }, VIEW);
    expect(grown.changes).toEqual([{ metric: 'filterBarOpenShare', from: undefined, to: 76 }]);
    const shrunk = applyRecording(table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 } }),
      DOC, { filterBarShutShare: 30 }, VIEW);
    expect(shrunk.baseline.documents[DOC]).toEqual({ filterBarShutShare: 30 });
    expect(shrunk.changes).toEqual([{ metric: 'filterBarOpenShare', from: 76, to: undefined }]);
  });

  it('bootstraps from an empty table', () => {
    const { baseline, changes } = applyRecording(emptyBaseline(VIEW), DOC,
      { filterBarShutShare: 30, filterBarOpenShare: 76 }, VIEW);
    expect(Object.keys(baseline.documents)).toEqual([DOC]);
    expect(changes).toHaveLength(2);
  });

  it('serializes in a total order, so a diff shows the line that moved', () => {
    // BOTH INSERTION ORDERS ARE THE REVERSE OF THE SORTED ONE, which is the whole
    // case: written the other way round, insertion order and sorted order agree
    // and a serializer that never sorted would pass this. It did — the first
    // version of this fixture could not tell the two apart, and the mutation that
    // removes the sort survived it.
    const jumbled = table({ [DOC]: { filterBarShutShare: 30, filterBarOpenShare: 76 },
      [OTHER]: { filterBarShutShare: 33, filterBarOpenShare: 79 } });
    const text = serialize(jumbled);
    expect(text.indexOf(OTHER)).toBeLessThan(text.indexOf(DOC));
    expect(text.indexOf('filterBarOpenShare')).toBeLessThan(text.indexOf('filterBarShutShare'));
    expect(text.endsWith('\n')).toBe(true);
    // ...and it is a file this reader accepts, which is the only thing that makes
    // the pair a round trip rather than two independent shapes.
    writeFileSync(baselinePath, text, 'utf8');
    expect(readBaseline(baselinePath).problem).toBe(null);
  });

  it('carries the command that rebuilds it inside the file', () => {
    expect(serialize(emptyBaseline(VIEW))).toMatch(/--record/);
  });
});

// --- the small pieces ---------------------------------------------------------

describe('the measurements themselves', () => {
  it('rounds a pixel height to a whole share of the screen', () => {
    expect(share(390, 780)).toBe(50);
    expect(share(203, 780)).toBe(26);
    // Over the viewport is a real answer, not a clamp: an open bar taller than
    // the screen is precisely the state F219 produces.
    expect(share(792, 780)).toBe(102);
  });

  it('keys a document by its path in the checkout, and nothing outside it', () => {
    expect(documentKey(join(root, DOC), root)).toBe(DOC);
    expect(documentKey(join(root, '..', 'elsewhere.html'), root)).toBe(null);
  });
});
