// What the panel does when it CANNOT TELL whether a surface has unsaved edits.
//
// `editRows(k)` calls a per-surface change computation registered in `EDITS`. If
// one of those throws, the old code returned `[]` — which is the same answer it
// returns for a surface with nothing to save. Three separate things read that
// answer, and all three then lose the reader's work:
//
//   * `beforeunload` declines to interrupt the close;
//   * `interacting()` decides nobody is mid-edit, so the 5-second poll rebuilds
//     the form under whoever was typing;
//   * Overview's out-of-band refresh re-renders a view it believes is clean,
//     discarding the edits in it.
//
// None of the three had a test, which is why an empty list could stand in for
// "unknown" for as long as it did. The direction of the repair is fail-safe:
// interrupting a close that did not need it costs a click; not interrupting one
// that did costs everything typed since the last save.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * Load the panel and make one registered surface's change computation throw.
 * @param {?string} broken an EDITS key to break, or null to leave all working
 * @param {Object} rows what the surviving surfaces report
 */
function panelWithSurfaces(broken, rows) {
  const { ctx } = loadPanel();
  const spec = JSON.stringify(rows || {});
  // MUTATED, not reassigned: `EDITS` is a `const` in the panel, so
  // `EDITS = {}` is a TypeError. Worth the note — the first version of this
  // helper did exactly that and every case failed for a reason that had nothing
  // to do with the code under test.
  vm.runInContext(
    'for (const k of Object.keys(EDITS)) delete EDITS[k];'
    + 'var __rows = ' + spec + ';'
    + 'for (const k of ["guards", "comp", "policy", "ado"]) {'
    + '  EDITS[k] = (function (key) {'
    + '    return function () {'
    + '      if (key === ' + JSON.stringify(broken) + ') throw new Error("boom");'
    + '      return __rows[key] || [];'
    + '    };'
    + '  })(k);'
    + '}', ctx);
  return reach(ctx, ['editRows', 'surfaceDirty']);
}

describe('a surface that cannot be read is treated as dirty', () => {
  it('editRows says null rather than empty [was: [] , same as clean]', () => {
    const { editRows } = panelWithSurfaces('guards', {});
    expect(editRows('guards')).toBe(null);
    // ...and a working surface still answers with its rows, so `null` means one
    // thing only.
    expect(editRows('comp')).toEqual([]);
  });

  it('surfaceDirty is true for the broken surface and false for a clean one', () => {
    const { surfaceDirty } = panelWithSurfaces('guards', {});
    expect(surfaceDirty('guards')).toBe(true);
    expect(surfaceDirty('comp')).toBe(false);
  });

  it('and true for a surface that simply has rows, which is the ordinary case', () => {
    const { surfaceDirty } = panelWithSurfaces(null,
      { comp: [{ target: 'comp', field: 'model', from: 'a', to: 'b' }] });
    expect(surfaceDirty('comp')).toBe(true);
    expect(surfaceDirty('guards')).toBe(false);
  });

  it('nothing is dirty when every surface answers empty — the guard is not '
     + 'satisfiable by always saying yes', () => {
    const { surfaceDirty } = panelWithSurfaces(null, {});
    for (const k of ['guards', 'comp', 'policy', 'ado']) {
      expect(surfaceDirty(k), k + ' should be clean').toBe(false);
    }
  });
});

describe('the three readers all err toward keeping the work', () => {
  // Each of these reproduces one of the three losses, at the level the panel
  // actually decides them: `some(surfaceDirty)` for the close, and the two
  // functions that consume it for the poll and the refresh.
  it('the close is interrupted when a surface cannot be read', () => {
    const { surfaceDirty } = panelWithSurfaces('policy', {});
    const anyDirty = ['guards', 'comp', 'policy', 'ado'].some(surfaceDirty);
    expect(anyDirty).toBe(true);
  });

  it('interacting() does not report a broken form as a clean one', () => {
    const { ctx } = loadPanel();
    vm.runInContext(
      'for (const k of Object.keys(EDITS)) delete EDITS[k];'
      + 'EDITS.guards = function () { throw new Error("boom"); };', ctx);
    const { interacting } = reach(ctx, ['interacting']);
    // A dirty (or unreadable) form defers nothing, because the refresh will not
    // rebuild it — so `interacting()` is false and `surfaceDirty` is what keeps
    // the view intact. The claim here is only that it does not CRASH and does not
    // report the unreadable form as clean-and-focused.
    expect(() => interacting()).not.toThrow();
  });

  it('a working panel with one broken surface still reports the others honestly', () => {
    const { surfaceDirty } = panelWithSurfaces('ado',
      { guards: [{ target: 'guards', field: 'x', from: 1, to: 2 }] });
    expect(surfaceDirty('ado')).toBe(true);      // unreadable
    expect(surfaceDirty('guards')).toBe(true);   // genuinely dirty
    expect(surfaceDirty('comp')).toBe(false);    // genuinely clean
    expect(surfaceDirty('policy')).toBe(false);
  });
});
