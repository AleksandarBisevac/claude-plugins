// A ledger the server could not read, driven rather than read.
//
// WHY THIS IS A SEPARATE FILE FROM evidence-badge.test.mjs. That suite is about
// what a RUN says; this one is about what the page says when there was no read
// to take a run from. The server used to hand the page a clean empty read in
// that case, and the page then said the ledger does not hold the run and that
// nothing was read - the answer a ledger nobody ever wrote gives. The payload
// now carries `readError`, and what is asserted here is that the words differ.
import { describe, expect, it } from 'vitest';
import { loadPanel, pyCall, reach } from './sandbox.mjs';

const P = reach(loadPanel().ctx, ['evState', 'evReadNote', 'evWord', 'evTaskRoll']);

const FIELDS = ['runId', 'scope', 'status', 'at', 'attempt', 'durationMs',
  'ranTotal', 'countsBasis', 'treeMutated', 'treeBasis',
  'coverage', 'coverageBasis', 'steps'];
const pointed = { testEvidence: { runId: 'r1', status: 'passed', at: 'x' },
  gateSource: 'task' };
// `_panel_composition.empty_evidence()`'s shape, and the same shape with the
// read error `evidence_view` fills when the caller's read raised.
const empty = { fields: FIELDS, stepFields: [], runs: {}, files: 0,
  unreadable: 0, readError: null };
const failed = Object.assign({}, empty, { files: null, unreadable: null,
  readError: { error: 'permission denied (fixture)',
    basis: 'the evidence ledger could not be read: permission denied (fixture)' } });

describe('a ledger that could not be read is not an empty ledger', () => {
  it('the badge WORD differs: Ledger unreadable, not Pointer without evidence', () => {
    // The word is what a reader sees without hovering, so it is the difference.
    const s = P.evState(pointed, failed);
    expect(s.key).toBe('ledger-unreadable');
    expect(P.evWord(s.key)).toBe('Ledger unreadable');
    expect(P.evWord(s.key)).not.toBe('Pointer without evidence');
    expect(s.run).toBeNull();
  });

  it('the roll-up counts every unread pointer under its own word, never as dangling', () => {
    const other = { testEvidence: { runId: 'r2' }, gateSource: 'task' };
    const roll = P.evTaskRoll([pointed, other], failed).map((r) => r.key);
    expect(roll).toEqual(['ledger-unreadable']);
  });

  it('the error payload says the read failed, and names why', () => {
    const why = P.evState(pointed, failed).why;
    expect(why).toContain('could not be read: permission denied (fixture)');
    expect(why).toContain('not a missing record');
    // The fabricated answer, which is the defect: counts nobody measured.
    expect(why).not.toContain('files read');
    expect(why).not.toContain('does not hold it');
  });

  it('ALLOW: an empty read still says the ledger does not hold the run', () => {
    // Guards the mutation that renders the error sentence for every payload.
    const s = P.evState(pointed, empty);
    expect(s.key).toBe('dangling');
    expect(P.evWord(s.key)).toBe('Pointer without evidence');
    const why = s.why;
    expect(why).toContain('the evidence ledger does not hold it');
    expect(why).toContain('0 files read');
    expect(why).not.toContain('could not be read');
    expect(P.evReadNote(empty)).toBe('');
  });

  it('a read error with no basis still says the read failed', () => {
    const bare = Object.assign({}, failed, { readError: { error: 'x' } });
    expect(P.evReadNote(bare)).toContain('could not be read');
  });
});

// --- one payload, two surfaces ------------------------------------------------
// THE PANEL AND THE REPORT READ THE SAME POINTER AND MUST SAY THE SAME WORD. They
// are keyed differently on purpose (`none` here, `no-evidence` there), so the
// comparison is over the WORD a reader sees, the same thing ev1 holds for the two
// label tables - only here each word is REACHED by calling the real functions,
// `evState` in the page and `tev_pointer` + `tev_view` in `_report_html`.
describe('the panel and the report agree, subject by subject', () => {
  const runRow = FIELDS.map((f) => ({ runId: 'r1', status: 'passed' })[f] ?? null);
  const withRun = Object.assign({}, empty, { runs: { r1: runRow }, files: 1 });
  const reportRow = { runId: 'r1', status: 'passed' };
  const block = { runId: 'r1', status: 'passed', at: 'x' };
  // [name, holder, configured, panel payload, the row the report found, readError]
  const matrix = [
    ['a pointer whose run was found', { testEvidence: block }, true, withRun, reportRow, null],
    ['a pointer whose run is not in the ledger', { testEvidence: block }, true, empty, null, null],
    ['a pointer when the ledger could not be read', { testEvidence: block }, true, failed, null,
      'permission denied (fixture)'],
    ['a block naming no run', { testEvidence: { status: 'passed', at: 'x' } }, true, empty, null, null],
    // The schema's runId is a string; a number is no run id on either surface.
    ['a block whose runId is not a string', { testEvidence: { runId: 7, status: 'passed' } }, true,
      empty, null, null],
    ['no pointer, a gate declared', {}, true, empty, null, null],
    ['no pointer, no gate anywhere', {}, false, empty, null, null],
  ];
  const pointers = pyCall('_report_html', matrix.map(([, holder]) => ['tev_pointer', [holder]]));
  const views = pyCall('_report_html', matrix.map(([, , configured, , row, readError], i) =>
    ['tev_view', [pointers[i], row, configured, null, null, readError]]));

  matrix.forEach(([name, holder, configured, ev], i) => {
    it(name, () => {
      const node = Object.assign({ gateSource: configured ? 'task' : null }, holder);
      expect(P.evWord(P.evState(node, ev).key)).toBe(views[i].label);
    });
  });

  it('the matrix reached every word it names, so no row passed by agreeing on nothing', () => {
    expect(new Set(views.map((v) => v.label))).toEqual(new Set([
      'Passed', 'Pointer without evidence', 'Ledger unreadable', 'No evidence',
      'No gate configured']));
  });
});
