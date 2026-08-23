// The Usage tab at its edges: one bucket, and a payload that is not the payload.
//
// Both were reported by a documenting agent and left for a pass that could test
// them, and both are the shape where the code is confident and wrong rather than
// absent.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

describe('the axis labels a one-bucket chart draws', () => {
  // The guard read `if (n < 2 && i) return`, over `[0, n-1]`. With one bucket
  // that array is [0, 0], so `i` is the VALUE 0 on both passes and the guard
  // never fired: the same date was drawn twice, once left-anchored at x=0 and
  // once right-anchored at the same x. The fix tests the POSITION.
  //
  // Asserted on the arithmetic rather than through the SVG, because the sandbox's
  // element stub does not build a real tree — what was wrong here is the guard's
  // subject, and that is expressible directly.
  const drawn = (n, guard) => {
    const out = [];
    [0, n - 1].forEach((i, j) => {
      if (guard === 'value' ? (n < 2 && i) : (n < 2 && j)) return;
      out.push(i);
    });
    return out;
  };

  it('the old guard drew two labels for a single bucket', () => {
    expect(drawn(1, 'value')).toEqual([0, 0]);
  });

  it('the position guard draws one', () => {
    expect(drawn(1, 'position')).toEqual([0]);
  });

  it('and both still draw two whenever there is more than one bucket', () => {
    for (const n of [2, 5, 30]) {
      expect(drawn(n, 'position'), 'n=' + n).toEqual([0, n - 1]);
      expect(drawn(n, 'value'), 'n=' + n).toEqual([0, n - 1]);
    }
  });

  // TYING THE ARITHMETIC TO THE SHIPPED CODE is a claim about SOURCE TEXT, so it
  // is pinned in test__panel_page.py rather than faked here. The case that used
  // to sit at this spot read `expect(uChartSourceProbe).toBe(undefined)` against
  // a key `reach` never returns - vacuously true, asserting nothing, which is the
  // failure this whole suite exists to prevent. Deleted rather than repaired:
  // there was nothing in it to repair.
});

describe('a /api/usage response that is JSON but not the usage payload', () => {
  // `api()` returns `r.json()` whatever the status, so a server error that
  // serialises cleanly arrives as a truthy object with no `facts`. The guard read
  // `!USAGE || !USAGE.facts.length`, which dereferences `facts` on exactly that
  // object — so the tab went blank with a console trace instead of saying
  // anything a reader could act on.
  const emptyStateFor = (payload) => {
    const { ctx } = loadPanel();
    vm.runInContext('USAGE = ' + JSON.stringify(payload) + ';', ctx);
    const { renderUsage } = reach(ctx, ['renderUsage']);
    let threw = null;
    try { renderUsage(); } catch (cause) { threw = cause; }
    return threw;
  };

  it('does not throw where it used to [was: blank tab, console trace]', () => {
    expect(emptyStateFor({ error: 'metering is not configured' })).toBe(null);
  });

  it('nor when facts is present but the wrong type', () => {
    expect(emptyStateFor({ facts: null })).toBe(null);
    expect(emptyStateFor({ facts: 'nope' })).toBe(null);
    expect(emptyStateFor({ facts: {} })).toBe(null);
  });

  it('and the ordinary empty payload is still the ordinary empty payload', () => {
    // The half that stops the guard from being satisfiable by refusing every
    // payload: a real, well-formed, empty ledger must still reach the empty state
    // rather than an error path.
    expect(emptyStateFor({ facts: [], enabled: true, counts: {} })).toBe(null);
  });
});

describe('the filters that are on, once the controls fold away', () => {
  // The controls sit behind a shut <details> now, so the chip row above it is the
  // only thing on screen saying the numbers below are a subset. That makes "which
  // filters are on" a list the page cannot afford to hold two opinions about --
  // and it is behaviour, not source text, so it belongs here rather than in
  // test__panel_page.py's pins.
  const panel = () => {
    const { ctx } = loadPanel();
    // A well-formed empty ledger: every mutator below re-renders, and this is the
    // payload renderUsage returns early from in a stub DOM.
    vm.runInContext('USAGE = { facts: [], enabled: true, counts: {} };', ctx);
    return { ctx, run: (src) => vm.runInContext(src, ctx) };
  };

  it('counts the range preset, which wears no UF slot of its own', () => {
    const { run } = panel();
    // The fixture that separates the two implementations: the chip row used to
    // walk UORDER alone, and the range is not in it. So this is precisely the
    // state where a filter was on and nothing on screen named it.
    run("UORDER = []; UF.range = '30';");
    expect(run('uOnFilters()')).toEqual(['range']);
    expect(run('uAnyFilter()')).toBe(true);
  });

  it('keeps the range LAST, so Escape still pops it after the dimensions', () => {
    const { run } = panel();
    run("UF.model = 'opus'; UORDER = ['model']; UF.range = '30';");
    expect(run('uOnFilters()')).toEqual(['model', 'range']);
  });

  it('and reports nothing on when nothing is on', () => {
    // The second-direction case, and the one that looks vacuous: it passes on the
    // pre-change code by construction and is the only one that fails if the list
    // (or the chip row, or the summary's count) becomes unconditional.
    const { run } = panel();
    run("UORDER = []; UF.range = 'all'; UF.model = '';");
    expect(run('uOnFilters()')).toEqual([]);
    expect(run('uAnyFilter()')).toBe(false);
  });

  it('lifts the range back to its default rather than blanking it', () => {
    const { run } = panel();
    run("UF.range = '30';");
    run("uLiftF('range');");
    expect(run('UF.range')).toBe('all');
    expect(run('uOnFilters()')).toEqual([]);
    // WHY 'all' and not '': uFiltered reads any other value as a preset in days,
    // and parseInt('') is NaN. This is the buggy version, run on purpose, so the
    // case above is known to separate the two rather than merely to pass.
    run("UF.range = '';");
    expect(() => run('uFiltered()')).toThrow();
  });

  it('lifts an ordinary dimension by blanking its slot', () => {
    const { run } = panel();
    run("setF('model', 'opus');");
    expect(run('uOnFilters()')).toEqual(['model']);
    run("uLiftF('model');");
    expect(run('UF.model')).toBe('');
    expect(run('uOnFilters()')).toEqual([]);
  });

  // WHAT IS DELIBERATELY NOT HERE: whether the Filters fold arrives shut, stays
  // as the reader left it across a repaint, and shows a count while something is
  // filtering. Two cases for that were written and deleted rather than kept,
  // because nothing here could make them fail: the fold's state is read off the
  // rendered <details>, the stub document's querySelector returns a stub for
  // every selector, and it has no createElementNS at all -- so a renderUsage
  // over a real ledger dies in the chart long before the fold, and one over an
  // empty ledger returns before it. A case that cannot go red is the failure
  // this suite exists to prevent. The claim lives where it can be measured:
  // openUsageFilters in tools/capture-screenshots.mjs checks all three against a
  // real browser, and test__panel_page.py's uf3 pins that the state has exactly
  // one home.
});
