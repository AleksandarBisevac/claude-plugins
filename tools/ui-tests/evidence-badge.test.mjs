// What a recorded test run looks like on the Overview, driven rather than read.
//
// WHY THIS IS NOT MORE SUBSTRING PINS. `test__panel_page.py` can say the source
// contains `run.treeMutated==null` and that no truthy test on that field exists
// anywhere in the block. It cannot say that a run whose tree was never compared
// comes out with a DIFFERENT marker from one that was compared and found clean —
// that is a claim about what the functions answer, and the only instrument for it
// is calling them. A pin whose label names a behaviour while its clauses assert
// how the code is written goes on passing after the behaviour is gone; this file
// is the half that cannot.
//
// The painted half is still not here and cannot be: whether the badge and its
// markers are legible, laid out apart, and reachable belongs to
// `tools/capture-screenshots.mjs`. What this proves is what the words SAY.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const P = reach(loadPanel().ctx, [
  'evState', 'evMarks', 'evChecks', 'evWord', 'evRow', 'evTaskRoll', 'EVWORD',
]);

// The column list the server ships beside its rows — `_panel_composition`'s
// EVIDENCE_FIELDS. Spelled here because these are FIXTURES for the client half;
// `test__panel_composition.py`'s ev8 is what pins the server to the same order,
// and `evRow` reading the shipped list is what makes a disagreement impossible
// rather than merely unlikely.
const FIELDS = ['runId', 'scope', 'status', 'at', 'attempt', 'durationMs',
  'ranTotal', 'countsBasis', 'treeMutated', 'treeBasis',
  'coverage', 'coverageBasis', 'steps'];

// A run that answered everything: compared its tree, counted its checks, named a
// file this work owns. Every fixture below is this one with ONE answer changed,
// so a case that goes red names the field it is about.
const clean = {
  runId: 'r1', scope: 'task', status: 'passed', at: '2026-08-20T10:00:00Z',
  attempt: 1, durationMs: 1500, ranTotal: 12, countsBasis: 'counted',
  treeMutated: 0, treeBasis: 'git described the tree before and after',
  coverage: 1, coverageBasis: 'the task declares files', steps: [],
};
const row = (over) => FIELDS.map((f) => Object.assign({}, clean, over)[f]);
const ledger = (over) => ({
  fields: FIELDS,
  stepFields: ['name', 'exit', 'ran', 'durationMs', 'outcome'],
  runs: { r1: row(over || {}) }, files: 1, unreadable: 0,
});
const pointed = { testEvidence: { runId: 'r1', status: 'passed', at: 'x' },
  gateSource: 'task' };
const wordFor = (node, ev) => P.evWord(P.evState(node, ev).key);
const marksFor = (node, ev) => P.evMarks(P.evState(node, ev).run).map((m) => m.text);

describe('a verdict is one word, and it claims nothing else', () => {
  it('Passed is the word alone — no check count rides on it', () => {
    const ev = ledger();
    expect(wordFor(pointed, ev)).toBe('Passed');
    expect(marksFor(pointed, ev)).toEqual([]);
  });

  it('an unrecognised verdict is NAMED, never folded into Failed', () => {
    // The manifest schema leaves the status enum open and says a consumer owes
    // a default arm. A build that met a word from a newer plugin and rendered
    // it as a failure would be reporting a red test that nobody ran.
    const ev = ledger({ status: 'flaky-retry' });
    expect(wordFor(pointed, ev)).toBe('Flaky retry');
    expect(wordFor(pointed, ev)).not.toBe('Failed');
  });

  it('a run that cached no verdict says so rather than showing a dash', () => {
    expect(wordFor(pointed, ledger({ status: null }))).toBe('Verdict not recorded');
  });

  it('a verdict word cannot be inherited off Object.prototype', () => {
    // A status word comes out of a file a human edits, so it can be
    // `constructor` — and an unguarded table read hands `Object.prototype`'s
    // FUNCTION to the page. This is the case that found it: `label()` reads its
    // own table without the guard, so the humanised fallback needed a type
    // check of its own. What is promised is a string that names the word, never
    // the capitalisation, which belongs to whoever fixes `label`.
    for (const word of ['constructor', 'toString', 'valueOf']) {
      const shown = wordFor(pointed, ledger({ status: word }));
      expect(typeof shown).toBe('string');
      expect(shown.toLowerCase()).toContain(word.toLowerCase());
    }
  });
});

describe('ran/ranTotal is three-valued, and zero is not unknown', () => {
  it('null is not knowable from this runner — never a count of nothing', () => {
    const run = P.evRow(row({ ranTotal: null, countsBasis: 'no counter' }), FIELDS);
    expect(P.evChecks(run)).toBe('check count not knowable from this runner');
    expect(P.evChecks(run)).not.toMatch(/\b0\b/);
  });

  it('a positive zero is the one that earns "no checks ran"', () => {
    expect(P.evChecks(P.evRow(row({ ranTotal: 0 }), FIELDS))).toBe('no checks ran');
  });

  it('and a real count is stated', () => {
    expect(P.evChecks(P.evRow(row({ ranTotal: 12 }), FIELDS))).toBe('12 checks ran');
    expect(P.evChecks(P.evRow(row({ ranTotal: 1 }), FIELDS))).toBe('1 check ran');
  });

  it('only the unknown one raises a marker', () => {
    expect(marksFor(pointed, ledger({ ranTotal: null }))).toContain('checks unknown');
    expect(marksFor(pointed, ledger({ ranTotal: 0 }))).not.toContain('checks unknown');
    expect(marksFor(pointed, ledger({ ranTotal: 9 }))).not.toContain('checks unknown');
  });
});

describe('an observation nobody made is not a clean one', () => {
  it('a tree that was never compared and a tree that is clean READ APART', () => {
    const unknown = marksFor(pointed, ledger({ treeMutated: null }));
    const cleanTree = marksFor(pointed, ledger({ treeMutated: 0 }));
    expect(unknown).toContain('tree unknown');
    expect(cleanTree).toEqual([]);
    expect(unknown).not.toEqual(cleanTree);
  });

  it('a rewritten tree is its own finding, and it survives a failed run', () => {
    // Two facts, two markers: the gate failed AND rewrote the tree, and a reader
    // who fixes the failure must not meet the rewrite afterwards.
    const ev = ledger({ status: 'failed', treeMutated: 3 });
    expect(wordFor(pointed, ev)).toBe('Failed');
    expect(marksFor(pointed, ev)).toContain('tree mutated');
  });

  it('the marker carries the basis the ledger recorded for it', () => {
    const run = P.evRow(row({ treeMutated: null, treeBasis: 'the run was interrupted' }),
      FIELDS);
    expect(P.evMarks(run).find((m) => m.text === 'tree unknown').why)
      .toBe('the run was interrupted');
  });

  it('coverage the same way, with its own sentence for the middle value', () => {
    expect(marksFor(pointed, ledger({ coverage: null }))).toContain('coverage unknown');
    expect(marksFor(pointed, ledger({ coverage: 0 }))).toContain('no overlap');
    expect(marksFor(pointed, ledger({ coverage: 4 }))).toEqual([]);
  });

  it('a run that answered nothing at all raises all three, in reading order', () => {
    expect(marksFor(pointed, ledger({ ranTotal: null, treeMutated: null,
      coverage: null })))
      .toEqual(['tree unknown', 'coverage unknown', 'checks unknown']);
  });
});

describe('the silences are three sentences, never one grey blob', () => {
  const ev = ledger();

  it('no pointer, but a gate that would grade it: no run has been recorded', () => {
    const s = P.evState({ testEvidence: null, gateSource: 'phase' }, ev);
    expect(P.evWord(s.key)).toBe('No evidence');
    expect(s.why).toContain('an absent record is not a failure');
    // A silence carries no observation, because nobody observed anything.
    expect(P.evMarks(s.run)).toEqual([]);
  });

  it('no gate anywhere: nothing COULD have run, which is a different problem', () => {
    const s = P.evState({ testEvidence: null, gateSource: null }, ev);
    expect(P.evWord(s.key)).toBe('No gate configured');
    expect(s.why).toContain('no test gate is declared');
  });

  it('a pointer the ledger cannot answer is the third, with its basis', () => {
    const s = P.evState({ testEvidence: { runId: 'gone', status: 'passed', at: 'x' },
      gateSource: 'task' }, ev);
    expect(P.evWord(s.key)).toBe('Pointer without evidence');
    expect(s.why).toContain('1 file read');
    expect(s.why).toContain('0 lines unreadable');
    // The cached verdict is REPORTED rather than rendered as if it had been read.
    expect(s.why).toContain('The plan caches the verdict "passed"');
  });

  it('...and all three are different words', () => {
    const words = [
      wordFor({ testEvidence: null, gateSource: 'phase' }, ev),
      wordFor({ testEvidence: null, gateSource: null }, ev),
      wordFor({ testEvidence: { runId: 'gone' }, gateSource: 'task' }, ev),
    ];
    expect(new Set(words).size).toBe(3);
  });

  it('a block present but naming no run is a pointer, not a silence', () => {
    expect(wordFor({ testEvidence: {}, gateSource: 'task' }, ev))
      .toBe('Pointer without evidence');
  });
});

describe('the ledger is read against the columns it shipped', () => {
  it('a row is decoded by NAME, so a reordered payload cannot shift a field', () => {
    const shuffled = ['status', 'runId'];
    expect(P.evRow(['failed', 'r9'], shuffled)).toEqual({ status: 'failed', runId: 'r9' });
  });

  it('no row at all is null, never an empty object', () => {
    // `{}` would answer `undefined` to every three-valued read, which is the one
    // value a caller cannot tell from "the run observed nothing".
    expect(P.evRow(undefined, FIELDS)).toBe(null);
    expect(P.evRow({ ranTotal: 3 }, FIELDS)).toBe(null);
  });
});

describe('a phase counts its tasks apart from its own sign-off run', () => {
  it('the roll-up leads with what needs a human and names every class', () => {
    const ev = ledger({ status: 'failed' });
    const tasks = [
      { testEvidence: { runId: 'r1', status: 'failed', at: 'x' }, gateSource: 'task' },
      { testEvidence: null, gateSource: 'phase' },
      { testEvidence: null, gateSource: null },
      { testEvidence: { runId: 'r1', status: 'failed', at: 'x' }, gateSource: 'task' },
    ];
    expect(P.evTaskRoll(tasks, ev).map((r) => r.n + ' ' + P.evWord(r.key)))
      .toEqual(['2 Failed', '1 No evidence', '1 No gate configured']);
  });

  it('a passing class sorts last, so a red one is never below a green one', () => {
    const ev = ledger();
    const tasks = [
      { testEvidence: { runId: 'r1', status: 'passed', at: 'x' }, gateSource: 'task' },
      { testEvidence: null, gateSource: 'phase' },
    ];
    expect(P.evTaskRoll(tasks, ev).map((r) => P.evWord(r.key)))
      .toEqual(['No evidence', 'Passed']);
  });

  it('a phase with no tasks rolls up to nothing rather than to a verdict', () => {
    expect(P.evTaskRoll([], ledger())).toEqual([]);
  });
});
