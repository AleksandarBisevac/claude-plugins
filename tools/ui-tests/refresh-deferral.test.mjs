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

// ---------- F90: the answer is re-asked where it is USED --------------------
//
// Every check above drives `interacting()` in isolation, and the predicate has
// always been right. That is exactly why F90 shipped: the poll asked it, then
// awaited three endpoints, and only then rendered. A reader who opened a combo
// menu inside that window was overruled by an answer taken before they touched
// anything, because `renderComp` opens with `closeCombo()`.
//
// So this drives the WINDOW rather than the predicate. `api` is a const arrow
// and cannot be reassigned, so it is driven through what it reads - `fetch` -
// with the menu opening between the first response and the last, which is what
// a person doing it mid-poll looks like from in here.
//
// WHAT THIS CANNOT SEE: the same thing the note at the top names. Nothing below
// proves a real click lands focus, and nothing proves the browser schedules the
// microtasks in the order a slow network would. The panel gate drives that, and
// it is what caught this in the first place.

/**
 * A panel whose fetches resolve in order, running a hook before the last one.
 * @param {() => void} duringFetches called after the first response, i.e. while
 *   the refresh is still in flight - the window F90 lived in
 * @returns {{ctx: object, calls: string[]}} the context and what it rendered
 */
function panelMidFetch(duringFetches) {
  const { ctx } = loadPanel();
  ctx.__calls = [];
  ctx.__during = duringFetches;
  vm.runInContext(
    'var __n = 0;'
    + 'fetch = function (p) { __n += 1;'
    + '  if (__n === 1) { __during(); }'
    + '  return Promise.resolve({ json: function () { return Promise.resolve('
    + '    p === "/api/state" ? { rollup: {}, composition: { phases: [] } }'
    + '    : p === "/api/usage" ? { facts: [] } : null); } }); };'
    // Renders are recorded rather than run: this asserts WHETHER the refresh
    // committed, and the renderers have their own suites.
    + 'renderViewer = function () { __calls.push("viewer"); };'
    + 'renderProposals = function () { __calls.push("proposals"); };'
    + 'renderComp = function () { __calls.push("comp"); };'
    + 'renderSettings = function () { __calls.push("settings"); };'
    + 'renderPolicy = function () { __calls.push("policy"); };'
    + 'renderOver = function () { __calls.push("over"); };'
    + 'renderUsage = function () { __calls.push("usage"); };'
    + 'staleNote = function () {};'
    + 'dirtyViews = function () { return { guards: false, comp: false, policy: false }; };'
    // `reRender` reaches for each view's findings slot; with no DOM behind it
    // the whole refresh throws into its own catch and commits nothing, which
    // would make the control case below pass for the wrong reason.
    // Stubbing `fetch` wakes any other panel path that was waiting on one, and
    // those report through `toast`, which writes into a DOM that is not here.
    // Silenced so the run has no unhandled rejections - vitest warns that they
    // can turn a real failure into a pass, and a suite about a race is the last
    // place to accept that.
    + 'toast = function () {};'
    + 'document.querySelector = function () { return null; };'
    + 'document.activeElement = null;'
    + 'CMENU = null;',
    ctx);
  return { ctx, calls: ctx.__calls };
}

describe('the deferral answer is re-asked after the fetches, not before', () => {
  it('a combo opened WHILE the refresh is in flight still stops it, and FP rewinds', async () => {
    const { ctx, calls } = panelMidFetch(() => {
      // The reader opens the menu mid-poll. Same state `comboOpen` reads.
      vm.runInContext('CMENU = { classList: { contains: function () { return false; } } };', ctx);
    });
    vm.runInContext('FP = "before";', ctx);
    await vm.runInContext('refreshFromDisk("before")', ctx);
    // Nothing rendered: renderComp would have closed the menu under them.
    expect(calls).toEqual([]);
    // ...and the change is DEFERRED rather than swallowed - the next tick sees
    // the moved fingerprint again because FP went back to what it was.
    expect(vm.runInContext('FP', ctx)).toBe('before');
  });

  it('and an untouched panel still refreshes, so the re-ask is not a blanket freeze', async () => {
    const { ctx, calls } = panelMidFetch(() => {});
    vm.runInContext('FP = "before";', ctx);
    await vm.runInContext('refreshFromDisk("before")', ctx);
    expect(calls).toContain('comp');
    expect(calls).toContain('over');
  });
});
