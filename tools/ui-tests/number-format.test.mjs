// Three implementations of one set of formatters, compared against each other
// instead of against a hand-written expectation.
//
// The reference is plugins/audit/scripts/_fmt.py, because that is what both
// JavaScript sources SAY they are. report.js: "Client-side mirrors of _fmt.py's
// formatters ... Same table, same shapes". panel.js: "Mirrors _fmt_tokens in
// render-report.py; the two must agree or one surface will quietly disagree
// with the other about the same number."
//
// Two of those sentences were wrong when this file was written, and this file
// is where that stopped being invisible. Both defects are fixed now and the two
// cases that found them are kept as regressions — see the `WAS DEFECT` blocks
// below for what each one broke and which mutation puts it back.

import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';
import { pyFmt } from './python-fmt.mjs';

const report = reach(loadReport().ctx, ['fmtTokens', 'fmtCost', 'fmtInt']);
const panel = reach(loadPanel().ctx, ['uTok', 'uCost', 'uPct', 'uShare']);

// --- token magnitudes -----------------------------------------------------

// Integers, which is what a token count is on every path that reaches these
// functions today. Chosen to walk each magnitude boundary from both sides, and
// deliberately free of exact binary ties (x.5 at the requested precision) —
// tie-breaking is a SEPARATE rule with a separate defect, pinned on its own
// below rather than smuggled in here where it would be read as noise.
const TOKEN_INTEGERS = [0, 1, 942, 999, 1000, 1001, 3230, 214300, 999999,
  1000000, 3230000, 2000000000, -1500, -3230000];

// The fractional inputs. `2.6` is the value the whole exercise turns on: it is
// the smallest tidy number on which truncation and rounding disagree, and every
// integer above renders identically under both, so a table without it would let
// the defect through.
const TOKEN_FRACTIONS = [2.6, 2.4, -2.6, 999.9, 0.6, 1500.7];

// A SWEEP, not a table, and it exists because the table above was green over a
// real divergence for as long as this file has existed.
//
// The defect was WHERE the truncation happened, not how it rounded: uTok dropped
// the fraction only on its sub-1000 path, so at or above a magnitude it divided
// the fraction into the quotient while Python and report.js dropped it first.
// `1500.7` is in the table and IS above the boundary — and it still cannot see
// this, because at one or two decimals 1.5007 and 1.5 render the same. Only a
// fraction whose effect survives to the third decimal of the quotient shows it,
// which is why a hand-picked table kept missing it: you have to already know the
// answer to pick the value.
//
// So every magnitude boundary is crossed from just below and just above, with
// fractions chosen to land on and around the rounding step, at both precisions
// the product asks for.
const TOKEN_BOUNDARY_FRACTIONS = (() => {
  const out = [];
  for (const base of [0, 1, 999, 1000, 1005, 1250, 1500, 999999,
                      1000000, 1000500, 1000000000, 1000000500]) {
    for (const frac of [0.005, 0.05, 0.1, 0.4, 0.5, 0.6, 0.9]) {
      out.push(base + frac, -(base + frac));
    }
  }
  return out;
})();

const DPS = [1, 2];   // the two the product asks for: labels, then hover.

function tokenCases(values) {
  const cases = [];
  for (const n of values) for (const dp of DPS) cases.push({ n, dp });
  return cases;
}

function pythonTokens(cases) {
  return pyFmt(cases.map((c) => ['fmt_tokens', [c.n, c.dp]]));
}

/**
 * Which cases each formatter got wrong, rather than a boolean.
 *
 * A sweep this size fails as two unreadable 300-element arrays otherwise, and the
 * first thing anyone needs from a divergence is the input that produced it.
 * @returns {{panel: string[], report: string[]}}
 */
function panelAndReport(cases, want) {
  const bad = { panel: [], report: [] };
  cases.forEach((c, i) => {
    const p = panel.uTok(c.n, c.dp);
    const r = report.fmtTokens(c.n, c.dp);
    if (p !== want[i]) bad.panel.push('n=' + c.n + ' dp=' + c.dp + ' py=' + want[i] + ' panel=' + p);
    if (r !== want[i]) bad.report.push('n=' + c.n + ' dp=' + c.dp + ' py=' + want[i] + ' report=' + r);
  });
  return bad;
}

describe('token magnitudes', () => {
  it('report.js fmtTokens matches _fmt.fmt_tokens on integers', () => {
    const cases = tokenCases(TOKEN_INTEGERS);
    expect(cases.length).toBe(TOKEN_INTEGERS.length * DPS.length);
    const want = pythonTokens(cases);
    const got = cases.map((c) => report.fmtTokens(c.n, c.dp));
    expect(labelled(cases, got)).toEqual(labelled(cases, want));
  });

  it('report.js fmtTokens matches _fmt.fmt_tokens on fractions', () => {
    const cases = tokenCases(TOKEN_FRACTIONS);
    const want = pythonTokens(cases);
    const got = cases.map((c) => report.fmtTokens(c.n, c.dp));
    expect(labelled(cases, got)).toEqual(labelled(cases, want));
  });

  it('panel.js uTok matches _fmt.fmt_tokens on integers', () => {
    const cases = tokenCases(TOKEN_INTEGERS);
    const want = pythonTokens(cases);
    const got = cases.map((c) => panel.uTok(c.n, c.dp));
    expect(labelled(cases, got)).toEqual(labelled(cases, want));
  });

  // ------------------------------------------------------------------------
  // WAS DEFECT 1 — this case was red on purpose until the fix landed, and it
  // is kept because it is the only thing that would notice the fix coming out.
  //
  //   _fmt.fmt_tokens(2.6)  -> "2"   (int(n) truncates at entry)
  //   report.js fmtTokens   -> "2"   (Math.trunc at entry)
  //   panel.js  uTok        -> "3"   (String(Math.round(n)) on the sub-1000 path)
  //
  // panel.js was the odd one out and its own comment claimed the opposite. The
  // comment also cited `_fmt_tokens in render-report.py`, and that function was
  // not there: it lives in plugins/audit/scripts/report/_report_usage.py, and
  // it delegates to _fmt.py. A stale citation and a false claim, in the same
  // three lines — which is why panel.js now names _fmt.py and names this file
  // instead of asserting the agreement in prose.
  //
  // THE FIX, one line, in plugins/audit/scripts/ui/panel.js:
  //   -  ...return (n/l).toFixed(dp)+s;return String(Math.round(n));};
  //   +  ...return uFixedHalfEven(n/l,dp)+s;return String(Math.trunc(n));};
  // (the first half of that line is DEFECT 2's fix, below). The mutation that
  // puts the rounding back, and proves this case can still fail, is in
  // tools/ui-tests/mutants.test.mjs.
  // ------------------------------------------------------------------------
  it('panel.js uTok matches _fmt.fmt_tokens on fractions [was DEFECT 1]', () => {
    const cases = tokenCases(TOKEN_FRACTIONS);
    const want = pythonTokens(cases);
    const got = cases.map((c) => panel.uTok(c.n, c.dp));
    expect(labelled(cases, got)).toEqual(labelled(cases, want));
  });

  // The case that would have caught DEFECT 3, and the reason it is a sweep: both
  // JavaScript formatters are compared against live Python across every magnitude
  // boundary, so "where does it truncate" is checked rather than assumed. Before
  // the fix this was red at 28 of these cases for the panel and 0 for the report.
  it('both formatters match _fmt.fmt_tokens across every magnitude boundary '
     + '[was DEFECT 3]', () => {
    const cases = tokenCases(TOKEN_BOUNDARY_FRACTIONS);
    // The vacuity guard: a sweep that generated nothing would pass silently, and
    // this is the case that is meant to be broad.
    expect(cases.length).toBeGreaterThan(150);
    const want = pythonTokens(cases);
    expect(panelAndReport(cases, want)).toEqual({ panel: [], report: [] });
  });

  it('the two dialects agree with each other on integers', () => {
    const cases = tokenCases(TOKEN_INTEGERS);
    const a = cases.map((c) => report.fmtTokens(c.n, c.dp));
    const b = cases.map((c) => panel.uTok(c.n, c.dp));
    expect(labelled(cases, b)).toEqual(labelled(cases, a));
  });
});

// --- the tie-breaking rule ------------------------------------------------

// WAS DEFECT 2, found by this suite rather than reported: JavaScript's
// Number.prototype.toFixed breaks an exact tie AWAY from zero, and Python's
// "%.*f" breaks it to EVEN. Every formatter in the family goes through one of
// those two, so the divergence was systematic and not specific to tokens:
//
//   1250 tokens at dp=1 -> "1.3K" in both JS files, "1.2K" in _fmt.py
//   $0.125              -> "$0.13" in both JS files, "$0.12" in _fmt.py
//   a 2.5% share        -> "3%"    in the panel,    "2%"    in _fmt.py
//
// The inputs are exactly-representable binary fractions, so this was not float
// noise — 1.35 and 3.05 are NOT ties and both sides always agreed on them.
//
// The decision taken: JavaScript rounds half-to-even, because Python is the
// reference. Both files grew a `fixedHalfEven` / `uFixedHalfEven` that detects
// a TRUE tie (x * 2^(dp+1) is an odd integer — a test that is exact, where
// scaling by 10^dp is not) and steps only those to the even neighbour. The
// helper exists twice because the two dialects cannot share code without a
// build step; the two copies are held equal, against _fmt.py, in
// tools/ui-tests/half-even.test.mjs over a few thousand generated rows.
describe('tie-breaking', () => {
  it('a decimal tie rounds the same way on both sides [was DEFECT 2]', () => {
    const [pyTok, pyCost, pyShare] = pyFmt([
      ['fmt_tokens', [1250, 1]],
      ['fmt_cost', [0.125]],
      ['fmt_share', [25, 1000, '—']],
    ]);
    expect({
      tokens: report.fmtTokens(1250, 1),
      panelTokens: panel.uTok(1250, 1),
      cost: report.fmtCost(0.125),
      share: panel.uPct(panel.uShare(25, 1000)),
    }).toEqual({
      tokens: pyTok, panelTokens: pyTok, cost: pyCost, share: pyShare,
    });
  });

  // The second direction, and it looks vacuous on purpose: it is the case that
  // fails if someone "fixes" DEFECT 2 by rounding half-to-even EVERYWHERE
  // instead of only on ties. 1.35 and 3.05 are not representable, so both
  // sides round them UP and must keep doing so. The mutation that makes the
  // tie test fire unconditionally is in tools/ui-tests/mutants.test.mjs, and
  // it is what proves this case is not decoration.
  it('a non-tie is unaffected, in both directions', () => {
    const want = pyFmt([['fmt_tokens', [1350, 1]], ['fmt_tokens', [3050, 2]]]);
    expect([report.fmtTokens(1350, 1), report.fmtTokens(3050, 2)]).toEqual(want);
    expect([panel.uTok(1350, 1), panel.uTok(3050, 2)]).toEqual(want);
  });
});

// --- money ----------------------------------------------------------------

// 0.004 is the "<$0.01" rule; 0 must read "$0.00" and NOT "<$0.01", because a
// zero that exists is not a zero that rounded away. Both directions of the one
// conditional in fmt_cost, which is why both are here.
const COSTS = [0, 0.004, 0.01, 0.0099, 1.234, 1234.5, -0.004, -1.5];

describe('cost', () => {
  it('report.js fmtCost matches _fmt.fmt_cost', () => {
    const want = pyFmt(COSTS.map((x) => ['fmt_cost', [x]]));
    expect(labelled(COSTS, COSTS.map((x) => report.fmtCost(x)))).toEqual(labelled(COSTS, want));
  });

  it('panel.js uCost matches _fmt.fmt_cost', () => {
    const want = pyFmt(COSTS.map((x) => ['fmt_cost', [x]]));
    expect(labelled(COSTS, COSTS.map((x) => panel.uCost(x)))).toEqual(labelled(COSTS, want));
  });
});

// --- countables -----------------------------------------------------------

const COUNTS = [0, 1, 999, 1000, 47625, 1000000, -1234567, 2.9, -2.9];

describe('countables keep their separators', () => {
  it('report.js fmtInt matches _fmt.fmt_int', () => {
    const want = pyFmt(COUNTS.map((n) => ['fmt_int', [n]]));
    expect(labelled(COUNTS, COUNTS.map((n) => report.fmtInt(n)))).toEqual(labelled(COUNTS, want));
  });

  // The rule the countable/magnitude split exists for: 47625 messages is
  // '47,625', never '47.6K'. If fmtInt ever grows the magnitude table, this
  // says so — the case above would still pass if BOTH sides compacted.
  it('a countable is never compacted', () => {
    expect(report.fmtInt(47625)).toBe('47,625');
    expect(report.fmtTokens(47625, 1)).toBe('47.6K');
  });
});

// --- shares ---------------------------------------------------------------

// Every branch of share_pct/fmt_share: a real slice, a sub-one-percent slice
// that must not read 0%, an exact zero that must NOT read <1% (the mirror-image
// lie), an unmeasurable share, and an overlap past 100 that must not be clamped.
//
// AND THE NEGATIVES, which this corpus had none of. `fmt_share` takes its <1%
// branch on magnitude; `uPct` took it on a positive fraction only, and a comment
// argued that no caller meets the difference. It was right about the callers and
// it meant these cases could not fail, so the two sides were free to disagree
// where nobody was looking. A share is non-negative by construction today; the
// point is that the agreement is now checked rather than reasoned about.
const SHARES = [[25, 100], [4, 1000], [0, 100], [5, 0], [0, 0],
  [1499, 100000], [999, 100000], [3, 2],
  [-4, 1000], [-999, 100000], [-25, 100], [-3, 2], [4, -1000], [-0.4, 100]];

describe('shares', () => {
  it('panel.js uShare matches _fmt.share_pct, None and all', () => {
    const want = pyFmt(SHARES.map(([p, w]) => ['share_pct', [p, w]]));
    const got = SHARES.map(([p, w]) => panel.uShare(p, w));
    // null and None must line up too: "no whole to divide by" is the whole
    // reason share_pct exists, and a JS `0` there would be the invented answer
    // it was written to stop.
    expect(labelled(SHARES, got)).toEqual(labelled(SHARES, want));
  });

  it('a NaN whole is unmeasurable on this side too', () => {
    // THE ONE CASE THE BRIDGE CANNOT CARRY. Everything else in this file is
    // answered by live Python, but the calls cross as JSON and JSON has no NaN -
    // so the two sides state the same answer separately, and the Python half is
    // `share_pct: a NaN whole is unmeasurable` in plugins/audit/tests/test__fmt.py.
    // They disagreed here until that case was written: NaN is TRUTHY in Python,
    // so `not whole` let it through and fmt_share rendered a percentage of NaN.
    expect(panel.uShare(5, NaN)).toBe(null);
    expect(panel.uPct(panel.uShare(5, NaN))).toBe('—');
    // ...and a real whole still divides, so this is not "always null".
    expect(panel.uShare(5, 200)).toBe(2.5);
  });

  it('panel.js uPct(uShare(..)) matches _fmt.fmt_share', () => {
    const want = pyFmt(SHARES.map(([p, w]) => ['fmt_share', [p, w, '—']]));
    const got = SHARES.map(([p, w]) => panel.uPct(panel.uShare(p, w)));
    expect(labelled(SHARES, got)).toEqual(labelled(SHARES, want));
  });
});

// --- reporting ------------------------------------------------------------

// Pair each result with the input that produced it before comparing. A bare
// array diff on 28 strings names an index; this names the case, which is the
// difference between "[13] differs" and "n=2.6 dp=1 differs".
function labelled(cases, values) {
  const out = {};
  cases.forEach((c, i) => { out[JSON.stringify(c)] = values[i]; });
  return out;
}
