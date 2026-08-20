// The shared storage helpers, driven with storage that REFUSES.
//
// This is the case the fourteen hand-written `try`/`catch` blocks existed for and
// that nothing tested: a document opened over `file://` may refuse localStorage
// outright, and the report is opened exactly that way — from a CI artifact, by
// somebody who cannot fix it. The panel is served from a real origin and works,
// which is how a report-only failure stays invisible.
//
// The refusing store is installed by PREPENDING an assignment to the loaded
// source rather than by teaching the sandbox a new option: `localStorage` is a
// property of the VM context, so a plain assignment replaces it for the whole
// run, in both the panel's classic script and the report's module.
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

/** Source prologue installing a store whose every method throws. */
const REFUSES = `localStorage = {
  getItem() { throw new Error('refused'); },
  setItem() { throw new Error('refused'); },
  removeItem() { throw new Error('refused'); },
};
`;

/** Source prologue installing a store that actually works, for the round trip. */
const WORKS = `localStorage = (() => {
  const m = new Map();
  return {
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { m.set(k, String(v)); },
    removeItem(k) { m.delete(k); },
  };
})();
`;

/** Assert the prologue really landed, so a green run cannot be an un-mutated one. */
const withStore = (prologue) => (src) => {
  if (!src.startsWith('//') && !src.includes('const')) {
    throw new Error('the loaded source does not look like the assembled script, so '
      + 'this test would be measuring nothing');
  }
  return prologue + src;
};

describe('shared/storage.js: a refusal is survivable', () => {
  it('the panel runs to the end even though every storage call throws', () => {
    const { ctx } = loadPanel({ mutate: withStore(REFUSES) });
    // `F` is declared in usage-model.js, late in the load order, so reaching it
    // proves execution passed every storage call on the way rather than dying at
    // the first one.
    expect(reach(ctx, ['F']).F.tokens).toBe(7);
  });

  it('storageGet answers null rather than throwing, and the writers stay quiet', () => {
    const { ctx } = loadPanel({ mutate: withStore(REFUSES) });
    const { storageGet, storageSet, storageDrop } = reach(
      ctx, ['storageGet', 'storageSet', 'storageDrop']);
    expect(storageGet('anything')).toBe(null);
    expect(() => storageSet('k', 'v')).not.toThrow();
    expect(() => storageDrop('k')).not.toThrow();
  });

  it('the report carries the same helpers — the part ships into BOTH surfaces', () => {
    const { ctx } = loadReport({ mutate: withStore(REFUSES) });
    const { storageGet, storageSet } = reach(ctx, ['storageGet', 'storageSet']);
    expect(storageGet('anything')).toBe(null);
    expect(() => storageSet('k', 'v')).not.toThrow();
  });
});

describe('shared/storage.js: and it still stores when it is allowed to', () => {
  // The other half. A helper that swallowed everything would pass every case
  // above, so these are what stop "survives a refusal" from meaning "never works".
  it('round-trips a value', () => {
    const { ctx } = loadPanel({ mutate: withStore(WORKS) });
    const { storageGet, storageSet } = reach(ctx, ['storageGet', 'storageSet']);
    storageSet('audit-test-key', 'kept');
    expect(storageGet('audit-test-key')).toBe('kept');
  });

  it('drop is not the same as storing an empty string', () => {
    const { ctx } = loadPanel({ mutate: withStore(WORKS) });
    const { storageGet, storageSet, storageDrop } = reach(
      ctx, ['storageGet', 'storageSet', 'storageDrop']);
    storageSet('audit-test-key', '');
    // An empty string is a VALUE: a reader that stored one would restore an empty
    // filter instead of falling back to its default, which is why storageDrop
    // exists as its own function.
    expect(storageGet('audit-test-key')).toBe('');
    storageDrop('audit-test-key');
    expect(storageGet('audit-test-key')).toBe(null);
  });

  it('the panel really did persist its tab through the helper', () => {
    // Not a unit test of the helper: proof that a CALL SITE was converted, so the
    // suite fails if a site goes back to touching localStorage directly.
    const { ctx } = loadPanel({ mutate: withStore(WORKS) });
    const { showTab, storageGet } = reach(ctx, ['showTab', 'storageGet']);
    showTab('usage');
    expect(storageGet('audit-panel-tab')).toBe('usage');
  });
});
