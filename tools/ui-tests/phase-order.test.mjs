// The report's phase-order control: `sort: plan order | priority`, the option
// the panel's Overview grew in dd60a11 and this page did not.
//
// WHAT THIS FILE IS FOR, AND WHY A SUBSTRING PIN CANNOT DO IT.
//
// The whole design decision is that the CLIENT HOLDS NO COMPARATOR. Python's
// `_priority.ranks` stamps a number on each phase row (`data-porder`) and the
// script orders by that number, so the report's order cannot drift from the
// order the orchestrator actually walks — there is nothing here to drift. A
// `'...' in M._SCRIPT` pin can assert that the text `getAttribute('data-porder')`
// is present; it cannot assert that ordering really is one attribute read, and
// it cannot run the thing.
//
// It also cannot see the failure that nearly shipped here. `phaseOrder` is
// declared in `report/page-state.js` and read in `report/sorting.js` and
// `report/exports.js` — three separate files that become ONE inline script. Read
// as a file, `sorting.js` references a name it never declares; read as the page,
// the name is in scope because page-state.js loads first. The two readings
// disagree, and only one of them is the product. An undefined reference there is
// fatal in the way this repo has been bitten by before: the whole block dies and
// every substring pin stays green. So the first case below resolves those
// bindings BY EVALUATION inside the loaded context, which is the only instrument
// that can tell the two readings apart.

import { describe, expect, it } from 'vitest';
import vm from 'node:vm';
import { loadReport, reach } from './sandbox.mjs';

// A phase group row, as far as the order functions are concerned: they read one
// attribute and nothing else, which is the claim.
const row = (porder) => ({
  getAttribute: (k) => (k === 'data-porder' ? porder : null),
});

function mutateOnce(needle, replacement) {
  return (src) => {
    const n = src.split(needle).length - 1;
    if (n !== 1) {
      throw new Error('mutation target occurs ' + n + ' times, expected exactly 1: '
        + JSON.stringify(needle) + ' — the source moved and this proof is no '
        + 'longer proving anything.');
    }
    return src.split(needle).join(replacement);
  };
}

describe('the order control is wired across the parts, not just present in one', () => {
  it('resolves every cross-part binding it reads in the ASSEMBLED script', () => {
    const { ctx } = loadReport();
    // Evaluated, not grepped. `node --check` is a parse and returns 0 on a file
    // full of undefined references; this throws a ReferenceError naming the one
    // that is missing.
    for (const name of ['phaseOrder', 'defaultOrder', 'sortSel', 'ORDERS',
                        'setPhaseOrder', 'orderPhaseBlocks', 'blockOf']) {
      expect(() => vm.runInContext(name, ctx), name).not.toThrow();
    }
    expect(vm.runInContext('phaseOrder', ctx)).toBe(vm.runInContext('defaultOrder', ctx));
  });

  it('starts on the written plan, because the table ARRIVES in that order', () => {
    const { ctx } = loadReport();
    expect(vm.runInContext('phaseOrder', ctx)).toBe('plan');
  });
});

describe('ORDERS is a lookup of numbers, not a comparator', () => {
  const orders = () => reach(loadReport().ctx, ['ORDERS']).ORDERS;

  it('offers exactly the two orders the select offers, under those names', () => {
    expect(Object.keys(orders()).sort()).toEqual(['plan', 'priority']);
  });

  it('reads the priority rank straight off data-porder', () => {
    expect(orders().priority(row('0'))).toBe(0);
    expect(orders().priority(row('7'))).toBe(7);
    // A string attribute coerced to a number, so the sort compares numbers and
    // not text — '10' must not land between '1' and '2'.
    const ranked = [row('10'), row('2'), row('1')]
      .map((r) => orders().priority(r)).sort((a, b) => a - b);
    expect(ranked).toEqual([1, 2, 10]);
  });

  it('is CONSTANT for plan order, which is what makes the plan restorable '
    + 'without keeping a second record of it', () => {
    // Every phase ranks equal, so the tie-break — the row's position in
    // `phaseRows`, the order the page loaded in — decides alone.
    expect(orders().plan(row('3'))).toBe(0);
    expect(orders().plan(row('0'))).toBe(0);
  });

  it('knows nothing about tiers: no null check, no absent-means-zero rule, '
    + 'nothing that could disagree with _priority.sort_key', () => {
    const src = String(orders().priority);
    expect(src).toContain('data-porder');
    // The panel re-expressed the rule as `(a.priority==null?1:0)-...`; this
    // deliberately did not, and that is the property worth pinning.
    expect(src).not.toContain('null');
    expect(src).not.toContain('tier');
    expect(src).not.toContain('priority ==');
  });
});

describe('the proofs above can fail', () => {
  it('goes red when the client re-derives the rule instead of reading the rank', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce("priority: (pr) => +pr.getAttribute('data-porder'),",
        'priority: (pr) => (pr.tier == null ? 1 : 0),'),
    });
    const { ORDERS } = reach(ctx, ['ORDERS']);
    // The mutant ignores the rank entirely, so two differently-ranked rows
    // compare equal — the exact shape of a client that decided order itself.
    expect(ORDERS.priority(row('7'))).not.toBe(7);
    expect(ORDERS.priority(row('7'))).toBe(ORDERS.priority(row('2')));
    expect(String(ORDERS.priority)).toContain('null');
  });

  it('goes red when plan order stops being constant', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce('plan: () => 0,', "plan: (pr) => +pr.getAttribute('data-porder'),"),
    });
    const { ORDERS } = reach(ctx, ['ORDERS']);
    // Plan order would then BE priority order, and the report would have lost
    // the written plan altogether — with both select options doing one thing.
    expect(ORDERS.plan(row('3'))).toBe(3);
    expect(ORDERS.plan(row('3'))).not.toBe(ORDERS.plan(row('1')));
  });
});
