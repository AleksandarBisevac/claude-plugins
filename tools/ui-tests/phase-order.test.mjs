// The phase-order control on BOTH surfaces: `sort: plan order | priority`, which
// the panel's Overview grew in dd60a11 and the report grew afterwards.
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
import { assemblePanelBody, loadPanel, loadReport, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

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
    // The panel DID re-express the rule for a while, as `(a.priority==null?1:0)-…`
    // with a comment saying it mirrored sort_key; this surface deliberately did
    // not, and that is the property worth pinning. Both read a rank now — the
    // panel's arrives on the rollup row instead of on an attribute — and the
    // block at the bottom of this file holds the same property for it.
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

// ---------- the panel, whose rank arrives on the rollup row ----------
//
// `overview.js` used to spell the rule again — an absent-tier class test and a
// tier compare beside it — under a comment saying the key mirrored
// `_priority.sort_key`. It was correct, nothing held it correct, and the repair
// was to delete the copy rather than to pin it: `_status_facts.rollup` stamps
// `porder` on every phase row and the sort is one subtraction.
//
// Three things this block does that a substring pin cannot. It runs the SHIPPED
// comparator rather than a retyped one — the arrow is lifted out of the
// assembled script text and evaluated inside the loaded panel context, so an
// expression that no longer resolves throws here instead of leaving a green
// suite over a dead page. It takes its rows from the real
// `_status_facts.rollup`, through the Python bridge, rather than from a
// hand-written fixture that would encode whatever this file's author believed.
// And it measures the resulting order against one derived from `sort_key` by a
// DIFFERENT route — the comparator's own tuples — because an order compared
// against itself cannot fail.
//
// READ THE TWO CASES TOGETHER, because their split IS the fault. The old copy
// was correct, so the ORDER case passes over it unchanged; only the case about
// the source text can see it. That is why deleting the copy was the fix and a
// pin asserting two spellings agree was not.

const PANEL_SORT_RE = /else if\(OVF\.sort==='priority'\)ordered\.sort\((.+)\);/;

// The fixture the panel is really served, built by Python. Tier 2 is shared and
// the tier-1 phase is written second, so document order is NOT the answer and an
// implementation that ignored the rank would be caught.
const PLAN = {
  meta: { version: 2 },
  phases: [
    { id: 'P1', title: 'a', status: 'pending', tasks: [] },
    { id: 'P2', title: 'b', status: 'pending', priority: 2, tasks: [] },
    { id: 'P3', title: 'c', status: 'pending', priority: 1, tasks: [] },
    { id: 'P4', title: 'd', status: 'pending', priority: 2, tasks: [] },
  ],
};

/** @returns {Array<{id: string, priority: (number|null), porder: number}>} */
function rollupPhases(manifest) {
  return pyCall('_status_facts', [['rollup', [manifest, [], []]]])[0].phases;
}

/**
 * The execution order, derived from `sort_key`'s own output rather than from
 * anything that already sorted by it.
 *
 * Comparing the tuples member by member here is not a second copy of the rule:
 * the rule is what decided the NUMBERS inside them, and Python did that. What
 * this file supplies is only "a tuple sorts lexicographically", which is the
 * same thing Python's `sorted` supplies on the other side.
 *
 * @param {{phases: Array<object>}} manifest
 * @returns {string[]} phase ids, first to run
 */
function orderFromSortKeys(manifest) {
  const phases = manifest.phases;
  const keys = pyCall('_priority', phases.map((p, i) => ['sort_key', [p, i]]));
  return phases
    .map((p, i) => [keys[i], p.id])
    .sort((a, b) => {
      for (let k = 0; k < a[0].length; k += 1) {
        if (a[0][k] !== b[0][k]) return a[0][k] - b[0][k];
      }
      return 0;
    })
    .map((entry) => entry[1]);
}

/**
 * The Overview's priority comparator, as the page receives it.
 * @param {{mutate: ((s: string) => string)}} [options] applied to the raw text
 *   AND to the loaded context, so both halves see the same source
 */
function panelPrioritySort(options) {
  const opts = options || {};
  const src = opts.mutate ? opts.mutate(assemblePanelBody()) : assemblePanelBody();
  const found = src.match(PANEL_SORT_RE);
  if (!found) {
    throw new Error('the Overview priority sort is no longer a single-line '
      + 'ordered.sort(...) in the assembled panel script. A multi-line '
      + 'comparator is exactly what a re-expressed rule looks like when it '
      + 'comes back, so this stops rather than testing nothing.');
  }
  const { ctx } = loadPanel(opts);
  // Evaluated in the LOADED context, never a bare one: the panel is one
  // concatenated script, so a name this expression reads must resolve there.
  return { cmp: vm.runInContext('(' + found[1] + ')', ctx), text: found[1] };
}

describe("the panel's Overview sorts by the rank, and holds no comparator", () => {
  it('lands on the order sort_key dictates, over rows rollup really produced', () => {
    const rows = rollupPhases(PLAN);
    const { cmp } = panelPrioritySort();
    const got = rows.slice().sort(cmp).map((r) => r.id);
    expect(got).toEqual(orderFromSortKeys(PLAN));
    // The fixture separates the implementations: a sort that ignored the rank
    // would answer document order, and this says that is a different list.
    expect(got).not.toEqual(rows.map((r) => r.id));
  });

  it('is handed a rank per row, not a tier to interpret', () => {
    const rows = rollupPhases(PLAN);
    // Every row, including the unprioritised one — a rank withheld for an absent
    // tier is a client left to invent a fallback, which is the whole defect.
    expect(rows.map((r) => r.porder)).toEqual([3, 1, 0, 2]);
    expect(rows.map((r) => r.priority)).toEqual([null, 2, 1, 2]);
  });

  it('spells no part of the rule: no absent-tier test, no tier arithmetic', () => {
    const { text } = panelPrioritySort();
    expect(text).toContain('porder');
    expect(text).not.toContain('priority');
    expect(text).not.toContain('null');
    expect(text).not.toContain('??');
    expect(text).not.toContain('||');
  });
});

describe('the panel proofs above can fail', () => {
  it('goes red when the client sorts by the TIER instead of the rank', () => {
    const opts = {
      mutate: mutateOnce('ordered.sort((a,b)=>a.porder-b.porder);',
        'ordered.sort((a,b)=>(a.priority||0)-(b.priority||0));'),
    };
    const rows = rollupPhases(PLAN);
    const { cmp } = panelPrioritySort(opts);
    // "absent means zero" is the answer `_priority` names as wrong, and it shows
    // as the unprioritised phase leading the run.
    const got = rows.slice().sort(cmp).map((r) => r.id);
    expect(got[0]).toBe('P1');
    expect(got).not.toEqual(orderFromSortKeys(PLAN));
  });

  it('keeps the ORDER while the source case goes red, when the deleted copy '
    + 'comes back — which is why the copy had to go rather than be pinned', () => {
    const opts = {
      mutate: mutateOnce('ordered.sort((a,b)=>a.porder-b.porder);',
        'ordered.sort((a,b)=>(a.priority==null?1:0)-(b.priority==null?1:0)'
        + '||(a.priority||0)-(b.priority||0));'),
    };
    const rows = rollupPhases(PLAN);
    const { cmp, text } = panelPrioritySort(opts);
    // The restored copy is CORRECT today, so the differential is blind to it.
    expect(rows.slice().sort(cmp).map((r) => r.id))
      .toEqual(orderFromSortKeys(PLAN));
    // Only the source property sees it. `_deps.SHARED_CONCERNS`' "phase
    // execution order" row fails the build on the same shape anywhere in ui/.
    expect(text).toContain('priority');
    expect(text).toContain('null');
  });
});
