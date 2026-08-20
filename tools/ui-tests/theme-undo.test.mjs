// Undo and Redo on the theme draft, including the step the trail could not
// express.
//
// `tUndo(stack, other)` is one function used twice with the stacks swapped, so
// Undo and Redo cannot drift apart. It carried one special case: a step whose
// `to` was `undefined` was pushed onto the other trail UNCHANGED, on the grounds
// that it "has no inverse to offer". The inverse is `{from: undefined, to: A}`,
// and applying `from: undefined` is exactly the clear — so the special case did
// not avoid an impossible operation, it made Redo re-apply the value Undo had
// just put back.
//
// Reachable through the Revert control: it calls `tSet(name, mode,
// tDefault(name, mode))`, and `tDefault` answers `undefined` for any token the
// default payload does not name.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * A panel whose saved theme names `--accent` and whose DEFAULT does not.
 *
 * That combination is what makes `tDefault('--accent', 'light')` undefined, which
 * is the input the special case was written for.
 *
 * The trails are READ FRESH every time rather than captured once, because `tSet`
 * REASSIGNS `TREDO` (`TREDO=[]` on every recorded edit). A reference taken at
 * setup time is stale after the first edit — which is how the first version of
 * this file failed four cases for a reason that had nothing to do with the code.
 */
function panelWithPartialDefault() {
  // `__CONTRAST_PAIRS__: '[]'` because `tUndo` ends in `renderAppearance()`, which
  // grades the draft's contrast — and the sandbox's default stub for a non-string
  // placeholder is `{}`, so `TPAIRS.forEach` is not a function. An EMPTY table is
  // the honest value here: this file is about the undo trail, and grading no pairs
  // keeps the render out of the way instead of importing a second subject.
  const { ctx } = loadPanel({ placeholders: { __CONTRAST_PAIRS__: '[]' } });
  vm.runInContext(
    'THEME = ' + JSON.stringify({
      theme: { '--accent': { $value: '#111111', $dark: '#111111' } },
      default: {},                      // names nothing at all
      groups: [{ title: 'Colour', tokens: ['--accent'] }],
      layout: {},
    }) + '; TDRAFT = null; TUNDO.length = 0; TREDO.length = 0;', ctx);
  const fns = reach(ctx, ['tSet', 'tUndo', 'tVal', 'tDefault']);
  return {
    ...fns,
    trails: () => reach(ctx, ['TUNDO', 'TREDO']),
    // TDRAFT is reassigned by tSet too, so it is read fresh for the same reason.
    draft: () => reach(ctx, ['TDRAFT']).TDRAFT || {},
    undo: () => { const t = reach(ctx, ['TUNDO', 'TREDO']); fns.tUndo(t.TUNDO, t.TREDO); },
    redo: () => { const t = reach(ctx, ['TUNDO', 'TREDO']); fns.tUndo(t.TREDO, t.TUNDO); },
  };
}

describe('clearing an override, when clearing changes something', () => {
  // The scenario that makes the clear OBSERVABLE, and finding it is most of what
  // this file is worth. With no draft override, clearing falls back to the saved
  // colour — the same colour — so the whole revert is a visual no-op and its undo
  // and redo are too. Only an override that DIFFERS from its fallback shows the
  // difference, and then it shows through `tVal` directly.
  const withOverride = () => {
    const p = panelWithPartialDefault();
    p.tSet('--accent', 'light', '#222222');      // an override over the saved value
    return p;
  };

  it('tDefault answers undefined here, or this file tests nothing', () => {
    expect(panelWithPartialDefault().tDefault('--accent', 'light')).toBe(undefined);
  });

  it('clearing falls back to the saved value', () => {
    const p = withOverride();
    expect(p.tVal('--accent', 'light')).toBe('#222222');
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));   // Revert
    expect(p.tVal('--accent', 'light')).toBe('#111111');
  });

  it('undo puts the override back', () => {
    const p = withOverride();
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));
    p.undo();
    expect(p.tVal('--accent', 'light')).toBe('#222222');
  });

  it('and REDO clears it again [was: re-applied the override]', () => {
    const p = withOverride();
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));
    p.undo();
    p.redo();
    // The bug: the redo trail held the original step, so redo applied its `from`
    // — the override Undo had just restored — instead of repeating the clear.
    expect(p.tVal('--accent', 'light')).toBe('#111111');
  });

  it('and the trails stay balanced across the round trip', () => {
    const p = withOverride();
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));
    p.undo();
    expect([p.trails().TUNDO.length, p.trails().TREDO.length]).toEqual([1, 1]);
    p.redo();
    expect([p.trails().TUNDO.length, p.trails().TREDO.length]).toEqual([2, 0]);
  });
});

describe('clearing an override that changes nothing is not a change', () => {
  // The other half of the same repair, and the one a reader actually met: with no
  // override present, Revert used to record an undo step and count as one unsaved
  // change for an edit that altered nothing. `String(was) === String(undefined)`
  // never matched, so the early return never fired.
  it('reverting a token with no override records nothing', () => {
    const p = panelWithPartialDefault();
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));
    expect(p.trails().TUNDO.length).toBe(0);
    expect(p.tVal('--accent', 'light')).toBe('#111111');
  });

  it('and reverting twice in a row records nothing the second time either', () => {
    const p = panelWithPartialDefault();
    p.tSet('--accent', 'light', '#222222');
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));   // a real clear
    const first = p.trails().TUNDO.length;
    p.tSet('--accent', 'light', p.tDefault('--accent', 'light'));   // now a no-op
    expect(p.trails().TUNDO.length).toBe(first);
  });
});

describe('the ordinary step is unaffected', () => {
  // The half that stops the repair from being "always push the step back": an
  // ordinary value-to-value edit has to keep undoing and redoing correctly.
  it('a value-to-value edit undoes and redoes, by VALUE', () => {
    const p = panelWithPartialDefault();
    p.tSet('--accent', 'light', '#222222');
    expect(p.tVal('--accent', 'light')).toBe('#222222');
    p.undo();
    expect(p.tVal('--accent', 'light')).toBe('#111111');
    p.redo();
    expect(p.tVal('--accent', 'light')).toBe('#222222');
  });

  it('undoing an empty trail is a no-op rather than an error', () => {
    const p = panelWithPartialDefault();
    expect(() => p.undo()).not.toThrow();
    expect(p.trails().TREDO.length).toBe(0);
  });
});
