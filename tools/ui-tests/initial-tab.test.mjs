// Where the panel lands, and the three things that decide it.
//
// WHY THIS IS A BEHAVIOUR TEST AND NOT A PIN. `test__panel_page.py` can only
// assert that some text appears in the assembled page. The rule here is control
// flow over three inputs — an explicit fragment, a remembered tab, and whether a
// plan exists — and a substring pin on `'over'` would pass just as happily if the
// precedence between them were inverted. The panel's own skill says it plainly:
// a behaviour belongs in a suite that can execute it.
//
// WHAT CHANGED AND WHY. The default used to be Settings. Measured on a fresh
// `git init` repo with the plugin installed and nothing else: the first screen was
// a wall of configuration for an audit that does not exist, and the one screen
// that says what to do next — Overview — was third in the list. Only the DEFAULT
// moved. A fragment somebody shared is an instruction and still wins; a remembered
// tab is a returning reader's own choice and still wins. So the new rule fires on
// exactly the visit that has neither, which is the first one.
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
  it('lands on Overview when there is no plan', () => {
    expect(landing({ rollup: null })).toBe('over');
  });

  // The second direction, and the one that matters: this is not "always Overview".
  // A repo that HAS a plan keeps the old landing, so the change cannot be mistaken
  // for a reordering of the panel.
  it('still lands on Settings once a plan exists', () => {
    expect(landing({ rollup: { valid: true, warnings: 0 } })).toBe('guards');
  });

  // Precedence, both arms. Either of these regressing would make the new default
  // look correct while quietly overriding a choice somebody already made.
  it('an explicit fragment outranks the no-plan default', () => {
    expect(landing({ rollup: null, hash: '#/usage' })).toBe('usage');
  });

  it('a remembered tab outranks the no-plan default', () => {
    expect(landing({ rollup: null, stored: 'policy' })).toBe('policy');
  });

  // An unrecognised fragment must not leave the reader on a blank page, and with
  // no plan the safe destination is the one that says what to do next.
  it('an unknown fragment falls back to the no-plan default, not to a blank view', () => {
    expect(landing({ rollup: null, hash: '#/nonsense' })).toBe('over');
  });
});
