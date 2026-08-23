// Where the panel lands, and the three things that decide it.
//
// WHY THIS IS A BEHAVIOUR TEST AND NOT A PIN. `test__panel_page.py` can only
// assert that some text appears in the assembled page. The rule here is control
// flow over three inputs — an explicit fragment, a remembered tab, and whether a
// plan exists — and a substring pin on `'over'` would pass just as happily if the
// precedence between them were inverted. The panel's own skill says it plainly:
// a behaviour belongs in a suite that can execute it.
//
// WHAT CHANGED AND WHY. The default used to be Settings, and for one commit it was
// a conditional — Overview when no plan existed, Settings otherwise. Reordering the
// section strip absorbed that: if Overview leads because "where are we" is the
// common visit, it is the right landing for a populated repo too, and a landing
// that disagreed with the top of the list would highlight one view and open
// another. So the rule is now `TABS[0]` and the tuple is the single order.
//
// Only the DEFAULT is decided there. A fragment somebody shared is an instruction
// and still wins; a remembered tab is this reader's own choice and still wins. Those
// two cases are the second direction here: without them "return TABS[0]" would pass
// every test while overriding a choice the reader had already made.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * Ask `initialTab()` under one arrangement of the three inputs.
 *
 * `rollup` is the fact the panel has for "a plan exists" — `renderOver` reads the
 * same field to decide between the empty state and the phase table, so the two
 * cannot disagree about what "no plan" means.
 */
function landing({ rollup = null, hash = '', stored = null } = {}) {
  const { ctx } = loadPanel(hash ? { hash } : {});
  vm.runInContext('STATE = ' + JSON.stringify({ rollup }) + ';', ctx);
  // The sandbox's storage is the blocked shape (reads return null), which is the
  // first-run condition. Override only when the case is about a returning reader.
  if (stored) ctx.localStorage.getItem = (k) => (k === 'audit-panel-tab' ? stored : null);
  return reach(ctx, ['initialTab']).initialTab();
}

describe('initialTab', () => {
  it('lands on the first view when there is no plan', () => {
    expect(landing({ rollup: null })).toBe('over');
  });

  // Whether a plan exists is no longer part of this answer, and that is worth a
  // case rather than a silence: it was part of it for one commit, and a reader of
  // that history needs to see the conditional deliberately gone rather than
  // wonder whether it was dropped by accident.
  it('and on the same view once a plan exists — the landing does not depend on it', () => {
    expect(landing({ rollup: { valid: true, warnings: 0 } })).toBe('over');
  });

  // Precedence, both arms. Either of these regressing would make the new default
  // look correct while quietly overriding a choice somebody already made.
  it('an explicit fragment outranks the default', () => {
    expect(landing({ rollup: null, hash: '#/usage' })).toBe('usage');
  });

  it('a remembered tab outranks the default', () => {
    expect(landing({ rollup: null, stored: 'policy' })).toBe('policy');
  });

  // An unrecognised fragment must not leave the reader on a blank page, and the
  // safe destination is the same first view rather than a second hard-coded id.
  it('an unknown fragment falls back to the first view, not to a blank one', () => {
    expect(landing({ rollup: null, hash: '#/nonsense' })).toBe('over');
  });
});
