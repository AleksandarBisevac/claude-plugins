// The report's test-gate filter: TWO axes, and the point of this file is that
// they are two.
//
// WHAT A SUBSTRING PIN CANNOT DO HERE. `'...' in M._SCRIPT` can assert that the
// text `tevFlagOk(t)` appears inside `refresh()`. It cannot assert that the name
// RESOLVES — `tevFlag` and `tevFlagOk` are declared in `report/page-state.js`
// and read from `report/filters.js` and `report/chips.js`, three separate files
// that become one inline script, so read as a file each of the readers
// references a name it never declares. An unresolved name there is fatal in the
// way this repo has been bitten by before: the whole block dies and every
// substring pin stays green. Every case below therefore EVALUATES the assembled
// script and calls the shipped function.
//
// And it cannot run the rule. The observation markers are a space-joined list in
// one attribute, so membership has to be a whole-word test; a bare `indexOf`
// would let `overlap` select every row carrying `no-overlap`, which is a filter
// that quietly answers a different question. That is a behaviour, and only
// calling the predicate can see it.

import { describe, expect, it } from 'vitest';
import vm from 'node:vm';
import { loadReport, reach } from './sandbox.mjs';

// A task row, as far as the filter is concerned: it reads two attributes and
// nothing else, which is the claim.
const row = (tev, flags) => ({
  getAttribute: (k) => {
    if (k === 'data-tev') return tev;
    if (k === 'data-tev-flags') return flags;
    return null;
  },
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

/**
 * The shipped predicate, with a marker selected inside the loaded context.
 *
 * The selection is written by evaluating an assignment IN the context rather
 * than by rebuilding one here: `tevFlag` is a module-scope `let` that the real
 * chip handler assigns to, and reaching for a copy would be testing a variable
 * this page does not have.
 *
 * @param {string} selected the marker to select; '' selects none
 * @param {object} [options] passed through to loadReport (a `mutate` hook)
 * @returns {(t: object) => boolean} the page's own tevFlagOk
 */
function flagPredicate(selected, options) {
  const { ctx } = loadReport(options);
  vm.runInContext('tevFlag = ' + JSON.stringify(selected) + ';', ctx);
  return reach(ctx, ['tevFlagOk']).tevFlagOk;
}

describe('the filter is wired across the parts, not just present in one', () => {
  it('resolves every cross-part binding the two axes read, in the ASSEMBLED '
    + 'script', () => {
    const { ctx, consoleErrors } = loadReport();
    // Evaluated, not grepped. `node --check` is a parse and returns 0 on a file
    // full of undefined references; this throws a ReferenceError naming the one
    // that is missing.
    for (const name of ['tevFilter', 'tevFlag', 'tevBar', 'tevFlagBar',
                        'tevFlagOk', 'refresh']) {
      expect(() => vm.runInContext(name, ctx), name).not.toThrow();
    }
    expect(consoleErrors).toEqual([]);
  });

  it('starts with neither axis filtering, so a report opens showing every '
    + 'task whatever its gate said', () => {
    const { ctx } = loadReport();
    expect(vm.runInContext('tevFilter', ctx)).toBe('');
    expect(vm.runInContext('tevFlag', ctx)).toBe('');
  });
});

describe('the two axes are independent', () => {
  it('gates on the status through one clause and on the observations through '
    + 'another, in the one pass', () => {
    const { refresh } = reach(loadReport().ctx, ['refresh']);
    // The SHIPPED function's own source, read off the evaluated object rather
    // than sliced out of the file — a slice can silently cover a different span.
    const src = String(refresh);
    expect(src).toContain("t.getAttribute('data-tev') === tevFilter");
    expect(src).toContain('tevFlagOk(t)');
  });

  it('never lets the observation axis narrow anything while nothing is '
    + 'selected on it — which is what makes a status selection a status '
    + 'selection', () => {
    const ok = flagPredicate('');
    expect(ok(row('failed', 'tree-mutated no-overlap'))).toBe(true);
    expect(ok(row('passed', null))).toBe(true);
    expect(ok(row(null, null))).toBe(true);
  });

  it('reads the observation list and NOT the status, so selecting a marker '
    + 'cannot silently select a verdict as well', () => {
    const ok = flagPredicate('failed');
    // `failed` is a status, never a marker. A predicate that had merged the two
    // axes would admit this row; the shipped one has nothing to match against.
    expect(ok(row('failed', null))).toBe(false);
    expect(ok(row('failed', 'tree-mutated'))).toBe(false);
  });
});

describe('a marker is matched whole, not as a substring', () => {
  it('admits the row that carries it and refuses the row that does not', () => {
    const ok = flagPredicate('tree-mutated');
    expect(ok(row('failed', 'tree-mutated no-overlap'))).toBe(true);
    expect(ok(row('passed', 'coverage-unknown'))).toBe(false);
    expect(ok(row('passed', null))).toBe(false);
  });

  it('refuses a fragment of a real marker — `overlap` is not `no-overlap`, and '
    + '`tree` is neither `tree-mutated` nor `tree-unknown`', () => {
    expect(flagPredicate('overlap')(row('failed', 'no-overlap'))).toBe(false);
    expect(flagPredicate('tree')(row('passed', 'tree-unknown'))).toBe(false);
    expect(flagPredicate('unknown')(row('passed', 'coverage-unknown'))).toBe(false);
  });

  it('matches the LAST marker in the list as readily as the first, so the '
    + 'padding really is on both sides', () => {
    expect(flagPredicate('checks-unknown')(
      row('passed', 'tree-unknown coverage-unknown checks-unknown'))).toBe(true);
    expect(flagPredicate('tree-unknown')(
      row('passed', 'tree-unknown coverage-unknown checks-unknown'))).toBe(true);
  });
});

describe('the proofs above can fail', () => {
  const PADDED = "    return (' ' + (t.getAttribute('data-tev-flags') || '') + ' ')\n"
    + "      .indexOf(' ' + tevFlag + ' ') !== -1;";

  it('goes red when the whole-word test is relaxed to a bare substring search', () => {
    const opts = {
      mutate: mutateOnce(PADDED,
        "    return (t.getAttribute('data-tev-flags') || '').indexOf(tevFlag) !== -1;"),
    };
    // The mutant answers TRUE for a fragment, which is the filter quietly
    // answering a different question than the chip that was pressed.
    expect(flagPredicate('overlap', opts)(row('failed', 'no-overlap'))).toBe(true);
    // ...while still passing the case that only asks about a real marker, which
    // is why the fragment case had to be written at all.
    expect(flagPredicate('tree-mutated', opts)(row('failed', 'tree-mutated')))
      .toBe(true);
  });

  it('goes red when the two axes are merged onto one attribute', () => {
    const opts = {
      mutate: mutateOnce("(' ' + (t.getAttribute('data-tev-flags') || '') + ' ')",
        "(' ' + (t.getAttribute('data-tev') || '') + ' ')"),
    };
    // The merged version admits a row by its VERDICT when a marker was selected.
    expect(flagPredicate('failed', opts)(row('failed', null))).toBe(true);
    expect(flagPredicate('tree-mutated', opts)(row('failed', 'tree-mutated')))
      .toBe(false);
  });

  it('goes red when an empty selection stops admitting everything — the shape '
    + 'that hides every task the moment the chip row exists', () => {
    const opts = {
      mutate: mutateOnce('    if (!tevFlag) return true;',
        '    if (!tevFlag) return false;'),
    };
    expect(flagPredicate('', opts)(row('passed', null))).toBe(false);
  });
});
