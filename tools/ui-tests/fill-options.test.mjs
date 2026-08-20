// Filling a <select>, once.
//
// Five sites spelled the same three steps: build the option, set `selected` when
// its value is the chosen one, append. Three others are deliberately NOT here and
// the helper's own doc says which — two decorate individual options and one
// decides `selected` through a path normalisation.
//
// This file exists because the mutation pass found the marking asserted nowhere:
// removing `if(cur===v)o.selected=true` left every suite green. The lint suite was
// the wrong instrument and the source pins named the pair lists rather than the
// helper's body.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const { fillOptions, el } = reach(loadPanel().ctx, ['fillOptions', 'el']);

/**
 * The options a select ended up with, as [value, selected] pairs.
 *
 * NOT the label: `el()` appends text through the stub's `append`, which drops it,
 * so `textContent` is empty here for every option. The value survives because the
 * stub really stores attributes. What the labels READ is a claim about words on
 * screen and is pinned as source text in test__panel_page.py, where the pair
 * lists are; what this file is about is which option gets MARKED.
 */
const shape = (sel) => sel.children.map((o) =>
  [o.getAttribute('value'), o.selected === true]);

/**
 * A select stub that records what was appended.
 *
 * `el()`'s stub drops appended children, so the collection is kept here — this is
 * about which option gets marked, not about the DOM doing the appending.
 */
function stubSelect() {
  const children = [];
  return { children, append(o) { children.push(o); } };
}

describe('fillOptions', () => {
  const PAIRS = [['plan', 'plan order'], ['progress', 'progress'],
    ['status', 'status']];

  it('adds one option per pair, in order, carrying the value', () => {
    const sel = stubSelect();
    fillOptions(sel, PAIRS, 'plan');
    expect(sel.children.length).toBe(3);
    expect(shape(sel).map((r) => r[0])).toEqual(['plan', 'progress', 'status']);
  });

  it('marks the chosen one, and ONLY that one [was: asserted nowhere]', () => {
    const sel = stubSelect();
    fillOptions(sel, PAIRS, 'progress');
    expect(shape(sel).map((r) => r[1])).toEqual([false, true, false]);
  });

  it('marks nothing when the current value is not among the options', () => {
    const sel = stubSelect();
    fillOptions(sel, PAIRS, 'nonsense');
    expect(shape(sel).some((r) => r[1])).toBe(false);
  });

  it('treats the empty string as a real value, because one caller uses it for '
     + 'the "no rule" option', () => {
    const sel = stubSelect();
    fillOptions(sel, [['', '—'], ['allow', 'allow'], ['deny', 'deny']], '');
    expect(shape(sel).map((r) => r[1])).toEqual([true, false, false]);
  });

  it('compares STRICTLY, as every site it replaced did', () => {
    // A loosening here would mark 0 for '' and 1 for '1'. The sites all carry
    // string values today; the point is that the helper did not change the rule
    // while collecting them.
    const sel = stubSelect();
    fillOptions(sel, [[0, 'zero'], [1, 'one']], '1');
    expect(shape(sel).some((r) => r[1])).toBe(false);
  });

  it('keeps options a caller already appended — two sites add an "all" option '
     + 'before the list', () => {
    const sel = stubSelect();
    sel.append(el('option', { value: '' }, 'all areas (3)'));
    fillOptions(sel, [['a', 'a'], ['b', 'b']], 'b');
    expect(sel.children.length).toBe(3);
    expect(shape(sel).map((r) => r[1])).toEqual([false, false, true]);
  });

  it('returns the select, so a builder can return the call', () => {
    const sel = stubSelect();
    expect(fillOptions(sel, PAIRS, 'plan')).toBe(sel);
  });

  it('an empty pair list adds nothing and is not an error', () => {
    const sel = stubSelect();
    expect(() => fillOptions(sel, [], 'plan')).not.toThrow();
    expect(sel.children.length).toBe(0);
  });
});
