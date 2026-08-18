// report.js's `natCmp` — the comparator behind every sortable column in the
// report. It has no Python counterpart, so the reference here is the ordering
// the product depends on rather than another implementation.
//
// The reason it exists at all: task ids are `P1.1 … P1.10`, and a plain string
// sort puts `P1.10` between `P1.1` and `P1.2`. Every case below would pass
// against `localeCompare` alone EXCEPT the multi-digit ones, which is what makes
// them the cases worth having.

import { describe, expect, it } from 'vitest';
import { loadReport, reach } from './sandbox.mjs';

const { natCmp } = reach(loadReport().ctx, ['natCmp']);

const sorted = (list) => list.slice().sort(natCmp);
const sign = (n) => (n < 0 ? -1 : n > 0 ? 1 : 0);

describe('natCmp orders numbers as numbers', () => {
  it('puts P1.9 before P1.10, which a string sort does not', () => {
    const ids = ['P1.10', 'P1.2', 'P1.1', 'P1.9', 'P1.20', 'P1.3'];
    expect(sorted(ids)).toEqual(['P1.1', 'P1.2', 'P1.3', 'P1.9', 'P1.10', 'P1.20']);
    // The fixture earns its place only if the naive sort really does differ.
    expect(ids.slice().sort()).not.toEqual(sorted(ids));
  });

  it('orders phases across a digit-width boundary', () => {
    expect(sorted(['P10', 'P9', 'P1', 'P100', 'P11'])).toEqual(
      ['P1', 'P9', 'P10', 'P11', 'P100']);
  });

  it('ignores leading zeros, because 007 and 7 are one number', () => {
    expect(sign(natCmp('P007', 'P7'))).toBe(0);
    expect(sorted(['P08', 'P7', 'P009'])).toEqual(['P7', 'P08', 'P009']);
  });

  it('sorts a pure-text column alphabetically', () => {
    expect(sorted(['pending', 'done', 'blocked', 'in_progress'])).toEqual(
      ['blocked', 'done', 'in_progress', 'pending']);
  });

  it('puts a shorter prefix first', () => {
    expect(sorted(['P1.1.1', 'P1.1', 'P1'])).toEqual(['P1', 'P1.1', 'P1.1.1']);
  });
});

describe('natCmp is a comparator, not merely a function', () => {
  const PAIRS = [
    ['P1.9', 'P1.10'], ['P2', 'P10'], ['alpha', 'beta'], ['P1', 'P1'],
    ['', 'P1'], ['P1.1', 'P1.1.1'], ['999', '1000'], ['a1b', 'a1c'],
  ];

  // Summed rather than negated: `-sign(0)` is `-0`, and vitest's toBe is
  // Object.is, which tells -0 and 0 apart. The sum states the same claim
  // without inviting that argument.
  it('is antisymmetric on every pair', () => {
    for (const [a, b] of PAIRS) {
      expect(sign(natCmp(a, b)) + sign(natCmp(b, a)), a + ' vs ' + b).toBe(0);
    }
    // ...and a comparator that returned 0 for everything would also sum to 0,
    // so at least one pair has to be a real ordering.
    expect(PAIRS.filter(([a, b]) => sign(natCmp(a, b)) !== 0).length)
      .toBeGreaterThanOrEqual(6);
    expect(PAIRS.length).toBeGreaterThanOrEqual(8);
  });

  it('is reflexive', () => {
    for (const [a] of PAIRS) expect(sign(natCmp(a, a))).toBe(0);
  });

  it('is transitive across the boundary that motivated it', () => {
    expect(sign(natCmp('P1.2', 'P1.9'))).toBe(-1);
    expect(sign(natCmp('P1.9', 'P1.10'))).toBe(-1);
    expect(sign(natCmp('P1.2', 'P1.10'))).toBe(-1);
  });

  // Sorting a column of cell text means every value has already been through
  // `.textContent.trim()`, so '' is a real input and must not throw or reorder
  // the rest of the column around itself.
  it('handles the empty cell', () => {
    expect(sorted(['P2', '', 'P1'])).toEqual(['', 'P1', 'P2']);
  });
});
