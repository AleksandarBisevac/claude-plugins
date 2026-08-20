// When the 5-second disk poll defers, and when deferring costs the reader the
// live view for nothing.
//
// Two functions decide this and they used to answer the same question twice:
//
//   `refreshFromDisk` works out which views hold unsaved edits, and folds the
//   ADO card's rows into `#comp` because that card LIVES inside #comp. A dirty
//   view is left alone rather than re-rendered.
//
//   `interacting()` defers the whole refresh while a caret sits in a CLEAN form
//   the refresh would rebuild - and asked `surfaceDirty('comp')` alone.
//
// So a reader who typed in the ADO card and then left the caret in an untouched
// Composition field froze the live view for as long as it rested there: comp read
// clean to the deferral and dirty to the refresh, which would not have rebuilt it
// anyway. The same failure the search-box comment in `interacting` describes,
// with a narrower trigger. One map now answers for both, and the selector is
// derived from it rather than typed a second time.
//
// WHAT THIS CANNOT SEE: real focus. `document.activeElement` and `closest` are
// set here directly, which is exactly the pair `interacting` reads - but nothing
// below proves the browser puts focus where a reader's click would. The panel
// gate drives that.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * A panel with a caret in a named view and a chosen set of dirty surfaces.
 * @param {?string} viewId the id `closest` resolves to, or null for "no form"
 * @param {string[]} dirty EDITS keys whose surfaces report unsaved rows
 * @param {boolean} [comboOpen] whether a combo menu is up
 */
function panelWithCaret(viewId, dirty, comboOpen) {
  const { ctx } = loadPanel();
  vm.runInContext(
    'for (const k of Object.keys(EDITS)) delete EDITS[k];'
    + 'var __dirty = ' + JSON.stringify(dirty) + ';'
    + 'for (const k of ["guards", "comp", "policy", "ado"]) {'
    + '  EDITS[k] = (function (key) { return function () {'
    + '    return __dirty.indexOf(key) >= 0'
    + '      ? [{ target: key, field: "f", from: 1, to: 2 }] : [];'
    + '  }; })(k);'
    + '}'
    // The pair `interacting` actually reads. `matches` must say yes or it
    // returns before looking at anything else.
    + 'var __view = ' + (viewId === null ? 'null' : '{ id: ' + JSON.stringify(viewId) + ' }')
    + ';'
    + 'document.activeElement = { matches: function () { return true; },'
    + '  closest: function () { return __view; } };'
    // `comboOpen` is a const arrow, so it is driven through the state it reads:
    // the shared listbox and its 'hidden' class. Reassigning the function is a
    // TypeError, and reaching past it would test the harness rather than the page.
    + 'CMENU = ' + (comboOpen
      ? '{ classList: { contains: function () { return false; } } }' : 'null') + ';',
    ctx);
  return reach(ctx, ['interacting', 'dirtyViews']);
}

describe('a caret in a clean form defers the refresh', () => {
  it('defers for a clean Composition form — the case the deferral exists for', () => {
    expect(panelWithCaret('comp', []).interacting()).toBe(true);
  });

  it('defers for guards and policy too', () => {
    expect(panelWithCaret('guards', []).interacting()).toBe(true);
    expect(panelWithCaret('policy', []).interacting()).toBe(true);
  });

  it('does NOT defer for a dirty form: the refresh will leave it alone', () => {
    expect(panelWithCaret('comp', ['comp']).interacting()).toBe(false);
  });

  it('does NOT defer for a caret outside every rebuildable form — a filter box '
     + 'must not freeze the live view', () => {
    expect(panelWithCaret(null, []).interacting()).toBe(false);
  });

  it('and an open combo defers regardless of where the caret is', () => {
    expect(panelWithCaret(null, [], true).interacting()).toBe(true);
  });
});

describe('the ADO card counts toward the view it lives in', () => {
  it('a dirty ADO card makes #comp dirty [was: only surfaceDirty("comp")]', () => {
    // The defect: `comp` read clean here, so the caret deferred the refresh that
    // would have skipped #comp anyway — the live view stopped for nothing.
    expect(panelWithCaret('comp', ['ado']).interacting()).toBe(false);
  });

  it('while guards and policy are unaffected by it — the fold is not a blanket '
     + '"anything dirty defers nothing"', () => {
    expect(panelWithCaret('guards', ['ado']).interacting()).toBe(true);
    expect(panelWithCaret('policy', ['ado']).interacting()).toBe(true);
  });
});

describe('one map answers for both readers', () => {
  it('dirtyViews is keyed by VIEW id, and comp folds ado in', () => {
    const { dirtyViews } = panelWithCaret('comp', ['ado']);
    expect(dirtyViews()).toEqual({ guards: false, comp: true, policy: false });
  });

  it('and it reports nothing dirty on a clean panel — not satisfiable by '
     + 'always saying dirty', () => {
    expect(panelWithCaret('comp', []).dirtyViews())
      .toEqual({ guards: false, comp: false, policy: false });
  });

  it('every key it names is a view the deferral can resolve a caret into', () => {
    // The guard against the two lists drifting apart again: a key here that
    // `closest` could never return would be dead, and a view id missing from
    // here would defer on a stale reading.
    const { dirtyViews } = panelWithCaret(null, []);
    const keys = Object.keys(dirtyViews());
    expect(keys.length).toBeGreaterThan(2);
    for (const id of keys) {
      expect(panelWithCaret(id, [id === 'comp' ? 'ado' : id]).interacting(),
        id + ' did not read its own dirtiness').toBe(false);
    }
  });
});
