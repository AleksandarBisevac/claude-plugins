// The panel's model-id typo check against the Python one it claims to mirror.
//
// `mdNear`'s own JSDoc says it "is spelled a second time here only because this
// half runs in a browser — the two have to keep agreeing, or the panel and the
// validator will reach different verdicts about one pair of names." Nothing
// checked that. The comment was the whole basis, which is the shape this repo
// treats as a claim without one.
//
// So the expectation is not written here: every case is answered by
// `_manifest_typos._model_near_miss` at run time, over a corpus generated from
// the four typo shapes the docstring names rather than chosen by hand. A
// hand-picked table would only prove that whoever wrote the table agreed with
// whoever wrote the function — the same failure `python-fmt.mjs` exists to avoid.
//
// WHAT THIS CANNOT SEE: that the two are reached with the same inputs in
// production. They are not, and are not meant to be — the validator compares
// model ids WITHIN a manifest, the panel compares a manifest's ids against the
// ledger and the rate table. The claim under test is only that the same pair of
// names gets the same verdict from either side. It errs toward silence: a shape
// absent from the corpus below is a shape neither side is checked on.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

const { mdNear } = reach(loadPanel().ctx, ['mdNear']);

// The characters a mutation may introduce: a letter, the separator these ids are
// full of, and a digit — because a version bump is the typo people actually make.
const INSERT = ['x', '-', '4'];

/**
 * Every string one edit from `seed`, by the four shapes the docstring names.
 * @param {string} seed a model id, or a degenerate stand-in for one
 * @returns {string[]} the seed included, deduplicated
 */
function oneEditAway(seed) {
  const out = new Set([seed, seed.toUpperCase()]);
  for (let i = 0; i < seed.length; i++) {
    out.add(seed.slice(0, i) + seed.slice(i + 1));                   // deletion
    for (const c of INSERT) {
      out.add(seed.slice(0, i) + c + seed.slice(i));                 // insertion
      out.add(seed.slice(0, i) + c + seed.slice(i + 1));             // substitution
    }
    if (i + 1 < seed.length) {                                       // transposition
      out.add(seed.slice(0, i) + seed[i + 1] + seed[i] + seed.slice(i + 2));
    }
  }
  for (const c of INSERT) out.add(seed + c);
  return [...out];
}

// Two realistic ids and three degenerate ones. The short seeds are here because
// the length branches (`len(x) == len(y)` and the skip-one walk) are where an
// index is easiest to get wrong, and '' reaches the walk with nothing to walk.
const SEEDS = ['claude-opus-4-6', 'gpt-4o-mini', 'ab', 'a', ''];

// Pairs no single-edit generator produces: two edits, a length gap of two, a
// NON-adjacent transposition (the shape the docstring excludes on purpose), and
// a pair differing only in case at a position that also moved.
const HARD = [
  ['claude-opus-4-6', 'claude-opus-5-7'],
  ['claude-opus-4-6', 'claude-opus'],
  ['abcd', 'cbad'],
  ['abcd', 'abdc'],
  ['sonnet', 'SONNET'],
  ['sonnet', 'SONNE'],
  ['', ''],
  ['', 'x'],
];

const PAIRS = [];
const seen = new Set();
const add = (a, b) => {
  for (const [p, q] of [[a, b], [b, a]]) {        // both orders: symmetry for free
    const k = JSON.stringify([p, q]);
    if (!seen.has(k)) { seen.add(k); PAIRS.push([p, q]); }
  }
};
for (const seed of SEEDS) for (const m of oneEditAway(seed)) add(seed, m);
for (let i = 0; i < SEEDS.length; i++) {
  for (let j = i + 1; j < SEEDS.length; j++) add(SEEDS[i], SEEDS[j]);
}
for (const [a, b] of HARD) add(a, b);

// One process for the whole corpus; the interpreter start dominates a per-case call.
const PY = pyCall('_manifest_typos', PAIRS.map(([a, b]) => ['_model_near_miss', [a, b]]));

describe('mdNear agrees with _model_near_miss', () => {
  it('over the whole corpus, verdict for verdict', () => {
    const wrong = PAIRS
      // Named for the SIDE rather than the language. A field abbreviated to the
      // two letters of the Python extension makes `word.<ext>` in the source,
      // which is exactly the shape `_refs`'s tools/ scanner reads as a script
      // basename — and it then reports that script as missing. Its case is right
      // to fire; the repair is to stop writing the shape, here and in this
      // comment, rather than to widen the pattern.
      .map(([a, b], i) => ({ a, b, python: PY[i], panel: mdNear(a, b) }))
      .filter((r) => r.python !== r.panel);
    expect(wrong, wrong.length + ' of ' + PAIRS.length + ' pairs disagree: '
      + JSON.stringify(wrong.slice(0, 12))).toEqual([]);
  });

  // Three guards on the guard. The comparison above passes over an empty corpus,
  // over a corpus both sides call true, and over one both call false — so each is
  // measured and named with its number.
  it('the corpus is not empty, and is not one-sided', () => {
    expect(PAIRS.length, 'corpus size').toBeGreaterThan(200);
    const yes = PY.filter(Boolean).length;
    expect(yes, yes + ' of ' + PY.length + ' pairs are near misses').toBeGreaterThan(20);
    expect(PY.length - yes, (PY.length - yes) + ' of ' + PY.length + ' are not')
      .toBeGreaterThan(20);
  });

  it('and both sides call it symmetric, which the corpus can check '
     + 'because it carries both orders', () => {
    const answer = new Map(PAIRS.map(([a, b], i) => [JSON.stringify([a, b]), PY[i]]));
    const asymmetric = PAIRS.filter(([a, b]) =>
      answer.get(JSON.stringify([a, b])) !== answer.get(JSON.stringify([b, a])));
    expect(asymmetric.length, 'Python answers differently by argument order for '
      + JSON.stringify(asymmetric.slice(0, 6))).toBe(0);
    for (const [a, b] of PAIRS.slice(0, 60)) {
      expect(mdNear(a, b), 'JS: ' + JSON.stringify([a, b])).toBe(mdNear(b, a));
    }
  });
});

describe('the four shapes the docstring names are actually in the corpus', () => {
  // Without this, "the corpus covers the four typo shapes" would be a claim in a
  // comment — the exact thing this file was written to stop. Each shape is
  // located BY the verdict both sides give it, not by how it was generated.
  const verdict = (a, b) => PY[PAIRS.findIndex(([p, q]) => p === a && q === b)];

  it('case-only, substitution, insertion, deletion and transposition all '
     + 'read as near misses', () => {
    expect(verdict('claude-opus-4-6', 'CLAUDE-OPUS-4-6')).toBe(true);
    expect(verdict('claude-opus-4-6', 'claude-opus-4-4')).toBe(true);
    expect(verdict('claude-opus-4-6', 'claude-opus-4-64')).toBe(true);
    expect(verdict('claude-opus-4-6', 'claude-opus-46')).toBe(true);
    expect(verdict('gpt-4o-mini', 'gpt-4o-imni')).toBe(true);
  });

  it('while two edits, a two-character gap and a non-adjacent swap do not', () => {
    expect(verdict('claude-opus-4-6', 'claude-opus-5-7')).toBe(false);
    expect(verdict('claude-opus-4-6', 'claude-opus')).toBe(false);
    expect(verdict('abcd', 'cbad')).toBe(false);
  });

  it('and a name is never a near miss of itself', () => {
    expect(verdict('', '')).toBe(false);
    expect(mdNear('claude-opus-4-6', 'claude-opus-4-6')).toBe(false);
  });
});
