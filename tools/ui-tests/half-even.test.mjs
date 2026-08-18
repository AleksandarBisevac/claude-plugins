// The one rounding primitive, written twice — and held equal HERE rather than
// by a comment claiming it.
//
// report.js is ES5 (`var`, `function ()`) and panel.js is modern ES, there is
// no build step, and an inline <script> on a file:// origin cannot import
// anything. So `fixedHalfEven` and `uFixedHalfEven` are the same algorithm
// typed twice. That is the known cost of the assembly contract; what is NOT
// acceptable is discovering later that the two drifted, which is exactly what
// happened to the token formatters that preceded them: both carried a comment
// saying they mirrored the same Python and they disagreed for months, because
// a comment is not a check.
//
// Three claims, in order of how much they are worth:
//
//   1. the two copies produce the same string for every row of the table;
//   2. both produce what Python's `"%.*f"` produces — the expression _fmt.py
//      rounds every token, cost and share through;
//   3. the table is not vacuous: it contains rows on which the NATIVE
//      toFixed disagrees with Python. Without that count, cases 1 and 2 could
//      both pass over a table that never reaches a tie, and the whole file
//      would be asserting that two identical calls to toFixed agree.

import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';
import { pyFixed } from './python-fmt.mjs';

const { fixedHalfEven } = reach(loadReport().ctx, ['fixedHalfEven']);
const { uFixedHalfEven } = reach(loadPanel().ctx, ['uFixedHalfEven']);

// --- the table ------------------------------------------------------------

// dp 0, 1 and 2 are what the product asks for (a share, a label, a hover); 3
// and 4 are here because the rule must not be true only at the depths anyone
// happens to call today.
const DPS = [0, 1, 2, 3, 4];

// An exact tie at `dp` places is t / 2^(dp+1) with t odd, and nothing else is,
// so ties are enumerated rather than hoped for. Both signs, because JS breaks
// ties away from zero in BOTH directions and Python breaks them to even in
// both — -198.5 is as much a case as 198.5.
function exactTies() {
  const out = [];
  for (const dp of DPS) {
    const den = Math.pow(2, dp + 1);
    for (let t = -301; t <= 301; t += 2) out.push([t / den, dp]);
    // and the same ties carried up the magnitudes a token label walks
    for (const scale of [10, 1000, 1e5]) {
      for (let t = -21; t <= 21; t += 2) out.push([scale * t / den, dp]);
    }
  }
  return out;
}

// Values that are NOT ties, which is the direction a half-to-even applied
// unconditionally would break. 1.35 and 3.05 are the two named in the report's
// own regression cases; the rest walk decimal-looking values that a reader
// would guess are ties and that no double can actually be.
function nonTies() {
  const out = [];
  const decimals = [0.005, 0.015, 0.025, 0.045, 0.055, 0.065, 0.075, 0.085,
    0.095, 0.35, 0.45, 0.55, 0.65, 1.005, 1.05, 1.15, 1.35, 1.45, 1.55, 2.675,
    3.05, 8.575, 12.345, 99.995, 1234.5678, 0.1, 0.2, 0.3, 1 / 3, 2 / 3,
    Math.PI, Math.E, 1e-7, 1e-5, 1e-3];
  for (const dp of DPS) {
    for (const v of decimals) { out.push([v, dp]); out.push([-v, dp]); }
    for (const v of decimals) {
      for (const scale of [1e3, 1e6, 1e9]) {
        out.push([v * scale, dp]);
        out.push([-v * scale, dp]);
      }
    }
  }
  return out;
}

// A deterministic spread so the table is not only values a human chose. The
// generator is an LCG rather than Math.random: a table that differs per run
// turns a real disagreement into a flake nobody can reproduce.
function spread() {
  let seed = 20260816;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const out = [];
  for (let i = 0; i < 1200; i++) {
    const mag = Math.pow(10, Math.floor(rnd() * 12) - 5);
    const v = (rnd() * 2 - 1) * mag;
    const dp = DPS[Math.floor(rnd() * DPS.length)];
    out.push([v, dp]);
    // ...and the same value snapped onto a dyadic grid, which is where ties live
    const j = 1 + Math.floor(rnd() * 6);
    out.push([Math.round(v * Math.pow(2, j)) / Math.pow(2, j), dp]);
  }
  return out;
}

// -0 is dropped, not silently formatted: JSON.stringify(-0) is "0", so a -0 in
// the table would be compared against Python's answer for +0. It is a real
// (pre-existing, tie-unrelated) divergence — JS `(-0).toFixed(1)` is "0.0",
// Python's `"%.1f" % -0.0` is "-0.0" — and it belongs in its own case, not
// smuggled in here where it would read as a tie failure.
const TABLE = [...exactTies(), ...nonTies(), ...spread()]
  .filter(([x]) => Number.isFinite(x) && !Object.is(x, -0) && Math.abs(x) < 1e21);

const label = ([x, dp]) => 'x=' + x + ' dp=' + dp;

describe('the table itself', () => {
  it('is broad, signed, and spans many magnitudes', () => {
    expect(TABLE.length).toBeGreaterThan(3000);
    expect(TABLE.some(([x]) => x < 0)).toBe(true);
    expect(TABLE.some(([x]) => x > 0)).toBe(true);
    expect(new Set(TABLE.map(([, dp]) => dp)).size).toBe(DPS.length);
    const mags = new Set(TABLE.map(([x]) => x === 0 ? 0 : Math.floor(Math.log10(Math.abs(x)))));
    expect(mags.size).toBeGreaterThan(10);
  });

  // The case that stops the other three from being decoration. If native
  // toFixed already agreed with Python everywhere in this table, then
  // `fixedHalfEven` returning `s` unconditionally would pass every case below.
  it('contains rows where the NATIVE toFixed disagrees with Python', () => {
    const want = pyFixed(TABLE);
    const native = TABLE.map(([x, dp]) => x.toFixed(dp));
    const off = TABLE.filter((_, i) => native[i] !== want[i]);
    expect(off.length).toBeGreaterThan(200);
    // and they are ties, every one of them: x * 2^(dp+1) an odd integer
    const notATie = off.filter(([x, dp]) => {
      const scaled = x * Math.pow(2, dp + 1);
      return !Number.isInteger(scaled) || scaled % 2 === 0;
    });
    expect(notATie.map(label)).toEqual([]);
  });
});

describe('one rule, two dialects', () => {
  it('report.js fixedHalfEven and panel.js uFixedHalfEven agree on every row', () => {
    const a = TABLE.map(([x, dp]) => fixedHalfEven(x, dp));
    const b = TABLE.map(([x, dp]) => uFixedHalfEven(x, dp));
    const off = TABLE.filter((_, i) => a[i] !== b[i])
      .map((c, i) => label(c) + ': report=' + a[i] + ' panel=' + b[i]);
    expect(off).toEqual([]);
  });
});

describe('and both agree with the Python they mirror', () => {
  const want = pyFixed(TABLE);

  it('report.js fixedHalfEven matches "%.*f"', () => {
    const got = TABLE.map(([x, dp]) => fixedHalfEven(x, dp));
    const off = TABLE.filter((_, i) => got[i] !== want[i])
      .map((c, i) => label(c) + ': js=' + got[i] + ' py=' + want[i]);
    expect(off).toEqual([]);
  });

  it('panel.js uFixedHalfEven matches "%.*f"', () => {
    const got = TABLE.map(([x, dp]) => uFixedHalfEven(x, dp));
    const off = TABLE.filter((_, i) => got[i] !== want[i])
      .map((c, i) => label(c) + ': js=' + got[i] + ' py=' + want[i]);
    expect(off).toEqual([]);
  });

  // Named separately because it is the value the bridge cannot carry, and
  // because it is a REAL divergence that has nothing to do with tie-breaking:
  // leaving it inside the table would have looked like the fix failing.
  it('negative zero is a known, separate divergence and is not claimed fixed', () => {
    expect(fixedHalfEven(-0, 1)).toBe('0.0');
    expect(uFixedHalfEven(-0, 1)).toBe('0.0');
    expect(pyFixed([[0, 1]])[0]).toBe('0.0');   // what Python gives for +0
  });
});
