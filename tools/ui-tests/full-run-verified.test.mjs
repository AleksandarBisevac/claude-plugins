// The third place's word and basis, beside a merged phase's evidence — driven
// rather than pinned, for `evidence-badge.test.mjs`'s own reason: a substring
// pin can say the source contains `not_declared:'Not declared'` and it cannot
// say that an UNKNOWN answer comes out with a DIFFERENT word from a
// PROVISIONAL one. That is a claim about what the function returns, and the
// only instrument for it is calling it.
//
// `evFullRunFacts` is asked rather than `evFullRunLine`'s DOM tree, and for
// `evidence-badge.test.mjs`'s own reason one field over: this sandbox stores
// attributes and returns stub elements, and it says nothing true about a
// PARENT's `.textContent` aggregating what its children were built with — a
// real browser recomputes that on read, and the stub does not. So what this
// file can ask is what the FACTS are, never whether the assembled tree paints
// them; that painted half belongs to `tools/capture-screenshots.mjs`.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const P = reach(loadPanel().ctx, ['fullRunWord', 'evFullRunFacts', 'FULLWORD']);

const cphOf = (fullRun) => (fullRun === undefined ? {} : { fullRun });

describe('the word is a table, not a guess', () => {
  it('the four answers get four different words', () => {
    const words = ['whole', 'provisional', 'unknown', 'not_declared']
      .map((a) => P.fullRunWord(a));
    expect(words).toEqual(['Verified — full run', 'Provisional', 'Unknown',
      'Not declared']);
    expect(new Set(words).size).toBe(4);
  });

  it('an answer this build does not recognise is shown AS ITSELF, never '
    + 'folded into a familiar word', () => {
    expect(P.fullRunWord('something-new')).toBe('something-new');
    expect(P.fullRunWord('something-new')).not.toBe('Unknown');
  });

  it('no answer at all reads as Unknown rather than a blank', () => {
    expect(P.fullRunWord('')).toBe('Unknown');
    expect(P.fullRunWord(undefined)).toBe('Unknown');
  });

  it('a word cannot be inherited off Object.prototype', () => {
    for (const word of ['constructor', 'toString', 'valueOf']) {
      expect(P.fullRunWord(word)).toBe(word);
    }
  });
});

describe('the facts are the payload, verbatim — never recomputed', () => {
  it('WHOLE carries its own word and the basis the server wrote', () => {
    const facts = P.evFullRunFacts(cphOf({ answer: 'whole',
      basis: "abc123 is contained in run r1's head def456", runId: 'r1' }));
    expect(facts.word).toBe('Verified — full run');
    expect(facts.basis).toBe("abc123 is contained in run r1's head def456");
    expect(facts.key).toBe('whole');
  });

  it('PROVISIONAL is its own word, never WHOLE and never a bare "no"', () => {
    const facts = P.evFullRunFacts(cphOf({ answer: 'provisional',
      basis: 'the newest measured full run does not contain the merge' }));
    expect(facts.word).toBe('Provisional');
    expect(facts.word).not.toBe('Verified — full run');
  });

  it('UNKNOWN reads as Unknown, never as Provisional — MUTATION: map '
    + "UNKNOWN to provisional's word -> red", () => {
    const facts = P.evFullRunFacts(cphOf({ answer: 'unknown',
      basis: 'phase P1 records no mergedHead' }));
    expect(facts.word).toBe('Unknown');
    expect(facts.word).not.toBe('Provisional');
  });

  it('the basis rides beside the word, never silently dropped', () => {
    const facts = P.evFullRunFacts(cphOf({ answer: 'whole',
      basis: 'THE ONE SENTENCE THAT PROVES IT' }));
    expect(facts.basis).toBe('THE ONE SENTENCE THAT PROVES IT');
  });

  it('a fullRun carrying no basis at all says nothing false rather than '
    + 'throwing', () => {
    const facts = P.evFullRunFacts(cphOf({ answer: 'whole' }));
    expect(facts.word).toBe('Verified — full run');
    expect(facts.basis).toBe('');
  });
});

describe('the facts are absent exactly when the payload says so', () => {
  it('no fullRun key at all: no facts, not a silent "Not declared"', () => {
    expect(P.evFullRunFacts({})).toBe(null);
    expect(P.evFullRunFacts(cphOf(undefined))).toBe(null);
  });

  it('a null fullRun (not merely absent) is the same silence', () => {
    expect(P.evFullRunFacts({ fullRun: null })).toBe(null);
  });

  it('a row that is not an object at all is the same silence, never a throw', () => {
    expect(P.evFullRunFacts(null)).toBe(null);
    expect(P.evFullRunFacts(undefined)).toBe(null);
  });
});
