// The Discard control, once, for every writable surface.
//
// Four surfaces each carried the same eleven lines, and the copies had already
// diverged the way copies do: the label was refreshed from a shared view listener
// in two, from a bespoke set of card listeners in a third, and computed once at
// render time in the fourth — which is why only that one went stale between
// renders. The pins that guarded the shape counted the copies, so they required
// the duplication to stay; they now name the one helper each surface reaches.
//
// WHAT THIS CANNOT SEE: whether a control is dead on the painted page, or whether
// a click on a dead one is actually refused (that refusal is a document-level
// capture-phase listener). `assertSavebarCensus` in tools/capture-screenshots.mjs
// reads the rendered document for both.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * A Discard control over a controllable set of rows, plus what it did.
 * @param {number} n how many unsaved rows the surface reports
 * @param {boolean} [confirmed] what the confirm dialog answers
 */
function footer(n, confirmed) {
  const { ctx } = loadPanel();
  const rows = [];
  for (let i = 0; i < n; i++) rows.push({ target: 't', field: 'f' + i, from: 1, to: 2 });
  vm.runInContext(
    '__log = []; __rows = ' + JSON.stringify(rows) + ';'
    // The dialog is stubbed rather than driven: what it renders is its own
    // suite's business, and the claim here is about what Discard asks it and
    // what it does with the answer.
    + 'confirmChanges = function (o) { __log.push(["confirm", o]);'
    + '  return Promise.resolve(' + (confirmed ? 'true' : 'false') + '); };'
    + 'toast = function (m) { __log.push(["toast", m]); };', ctx);
  const { discardButton, refreshDiscard } = reach(ctx, ['discardButton', 'refreshDiscard']);
  const b = discardButton({
    key: 'guards',
    rows: () => reach(ctx, ['__rows']).__rows,
    title: 'Discard unsaved settings',
    note: 'nothing is written',
    toast: 'discarded — back to the saved file',
    revert: () => vm.runInContext('__log.push(["revert"]);', ctx),
  });
  return { b, refreshDiscard, ctx,
    log: () => reach(ctx, ['__log']).__log,
    // Through the recorded listener, because `el()` wires an `onclick` key with
    // addEventListener rather than assigning a property. The handler is async, so
    // __fire's return value is what there is to await.
    press: () => b.__fire('click'),
    setRows: (k) => vm.runInContext('__rows = __rows.slice(0, ' + k + ');', ctx) };
}

describe('the control says how much it would cost', () => {
  it('is dead and unnumbered before any refresh — built clean, not built live', () => {
    const f = footer(3);
    expect(f.b.getAttribute('aria-disabled')).toBe('true');
    expect(f.b.textContent).toBe('Discard');
  });

  it('names the count once refreshed, and agrees with the shared plural', () => {
    const f = footer(3);
    f.refreshDiscard(f.b, 3);
    expect(f.b.textContent).toBe('Discard 3 changes');
    expect(f.b.getAttribute('aria-disabled')).toBe('false');
  });

  it('and one change is singular — the bug the literal "(s)" convention had', () => {
    const f = footer(1);
    f.refreshDiscard(f.b, 1);
    expect(f.b.textContent).toBe('Discard 1 change');
  });

  it('back to dead and unnumbered when the form is saved or reverted', () => {
    const f = footer(2);
    f.refreshDiscard(f.b, 2);
    f.refreshDiscard(f.b, 0);
    expect(f.b.textContent).toBe('Discard');
    expect(f.b.getAttribute('aria-disabled')).toBe('true');
  });

  it('carries the surface key as its hook, which is what focusSel names it by', () => {
    expect(footer(1).b.getAttribute('data-discard')).toBe('guards');
  });
});

describe('pressing it', () => {
  it('does nothing at all when there is nothing to throw away', async () => {
    const f = footer(0);
    await f.press();
    expect(f.log()).toEqual([]);        // no dialog, no revert, no toast
  });

  it('confirms first, and a refused dialog reverts nothing', async () => {
    const f = footer(2, false);
    await f.press();
    const kinds = f.log().map((e) => e[0]);
    expect(kinds).toEqual(['confirm']);
    const o = f.log()[0][1];
    expect(o.danger).toBe(1);
    expect(o.lock).toBe(false);          // discarding is not a write the gate holds
    expect(o.verb).toBe('Discard 2 changes');
    expect(o.rows.length).toBe(2);
  });

  it('reverts and says so once confirmed', async () => {
    const f = footer(2, true);
    await f.press();
    expect(f.log().map((e) => e[0])).toEqual(['confirm', 'revert', 'toast']);
    expect(f.log()[2][1]).toBe('discarded — back to the saved file');
  });

  it('asks for the rows AGAIN on the press, not the ones the label was built '
     + 'from', async () => {
    // The reason `rows` is a function. The label is from the last repaint; what
    // gets discarded has to be what the form holds now, and a closed-over list
    // would confirm a count the form no longer has.
    const f = footer(5, true);
    f.refreshDiscard(f.b, 5);
    expect(f.b.textContent).toBe('Discard 5 changes');
    f.setRows(2);
    await f.press();
    expect(f.log()[0][1].verb).toBe('Discard 2 changes');
  });

  it('and a form emptied between the repaint and the press discards nothing', async () => {
    const f = footer(3, true);
    f.refreshDiscard(f.b, 3);
    f.setRows(0);
    await f.press();
    expect(f.log()).toEqual([]);
  });
});
