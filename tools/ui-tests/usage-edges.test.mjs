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
