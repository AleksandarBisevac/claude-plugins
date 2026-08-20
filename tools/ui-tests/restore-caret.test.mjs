// Handing the caret back after a render replaced the element holding it.
//
// Four views spelled this identically — resolve the node, focus it, set the
// selection inside a try, otherwise fall back to the remembered reference — and
// two of them resolved by id while two resolved by selector. The panel already
// documented the rule as "ONE rule, and two places that need it"; it had four.
//
// WHAT THIS CANNOT SEE: whether the browser actually moves focus. The stub
// records the call. `focusBack` earned a line in the panel by asking the document
// afterwards rather than trusting `.focus()` — a disabled control accepts the call
// in silence — and that lesson lives in the browser gate, where there is a
// document to ask.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/** A panel, plus a fake control that records what was done to it. */
function withControl(opts) {
  const { ctx } = loadPanel();
  vm.runInContext('__acts = [];', ctx);
  const acts = () => reach(ctx, ['__acts']).__acts;
  const node = {
    focus() { vm.runInContext('__acts.push("focus");', ctx); },
    setSelectionRange: (opts && opts.noSelection) ? undefined
      : (a, b) => vm.runInContext('__acts.push("sel:' + a + ',' + b + '");', ctx),
  };
  if (opts && opts.selectionThrows) {
    node.setSelectionRange = () => { throw new Error('not a text field'); };
  }
  return { ctx, node, acts, ...reach(ctx, ['restoreCaret']) };
}

describe('a control that is still there', () => {
  it('gets the focus and the caret position', () => {
    const f = withControl();
    expect(f.restoreCaret(f.node, 7, null)).toBe(true);
    expect(f.acts()).toEqual(['focus', 'sel:7,7']);
  });

  it('is focused even when it has no selection to set — a <select> or a '
     + 'checkbox has none', () => {
    const f = withControl({ noSelection: true });
    expect(f.restoreCaret(f.node, 7, null)).toBe(true);
    expect(f.acts()).toEqual(['focus']);
  });

  it('and a setSelectionRange that THROWS does not cost the focus', () => {
    // The try is not decoration: an <input type=number> throws on this in some
    // browsers, and losing the focus would be a worse outcome than losing the
    // caret position.
    const f = withControl({ selectionThrows: true });
    expect(() => f.restoreCaret(f.node, 3, null)).not.toThrow();
    expect(f.acts()).toEqual(['focus']);
  });
});

describe('no control to restore', () => {
  it('falls back to the remembered reference', () => {
    const f = withControl();
    const ref = { node: null, sel: '#nothing-here' };
    // The stub's querySelectorAll returns [], so focusBack finds nothing and
    // says so rather than guessing.
    expect(f.restoreCaret(null, 0, ref)).toBe(false);
    expect(f.acts()).toEqual([]);
  });

  it('and a null reference is a no-op rather than a throw — which is why one '
     + 'call can serve both of the old branches', () => {
    const f = withControl();
    expect(f.restoreCaret(null, 0, null)).toBe(false);
    expect(f.acts()).toEqual([]);
  });

  it('a node that cannot be focused is treated as absent', () => {
    const f = withControl();
    expect(f.restoreCaret({}, 0, null)).toBe(false);
    expect(f.acts()).toEqual([]);
  });
});
