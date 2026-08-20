// One day in milliseconds, and the panel's day-number arithmetic on top of it.
//
// The constant was spelled `864e5` at eight sites across four panel parts and
// `86400000` twice in the report — the same number under two names, which is why
// the registry needled the CONSTANT rather than the arithmetic: the divisions and
// the multiplications look nothing alike. Widening the needle to both spellings is
// what found the report's second one at all.
//
// `dayIso` was three identical local `const iso` inside three separate functions:
// the shape a one-line helper takes when it has no home.
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

const panel = reach(loadPanel().ctx, ['DAY_MS', 'dnum', 'dayIso']);
const report = reach(loadReport().ctx, ['DAY_MS']);

describe('DAY_MS', () => {
  it('is a day, and both surfaces get the SAME one', () => {
    expect(panel.DAY_MS).toBe(24 * 60 * 60 * 1000);
    expect(report.DAY_MS).toBe(panel.DAY_MS);
  });
});

describe('the panel counts days as integers', () => {
  it('the epoch is day zero, and a day later is day one', () => {
    expect(panel.dnum('1970-01-01')).toBe(0);
    expect(panel.dnum('1970-01-02')).toBe(1);
  });

  it('round-trips through dayIso, which is the claim the two make together', () => {
    for (const d of ['1970-01-01', '2000-02-29', '2026-08-20', '2026-12-31',
      '2024-02-29', '1999-12-31']) {
      expect(panel.dayIso(panel.dnum(d)), d).toBe(d);
    }
  });

  it('a span is a subtraction, which is what the whole vocabulary rests on', () => {
    expect(panel.dnum('2026-03-01') - panel.dnum('2026-02-01')).toBe(28);
    expect(panel.dnum('2024-03-01') - panel.dnum('2024-02-01')).toBe(29);
    expect(panel.dnum('2027-01-01') - panel.dnum('2026-01-01')).toBe(365);
  });

  it('and UTC, not local — the ledger\'s days are UTC dates', () => {
    // `new Date('2026-08-20')` is UTC midnight while `new Date('2026-8-20')` is
    // LOCAL midnight, which is the trap `Date.UTC` avoids. A local parse lands on
    // a fraction of a day in any zone east or west of UTC.
    //
    // WHICH THIS CASE CANNOT SEE ON A UTC HOST, and CI is one: it sets no TZ, so
    // the runner is UTC and a local-midnight parse is arithmetically identical
    // there. Verified by mutation from a +0200 host, where it goes red; in CI it
    // passes either way. So the claim is ALSO pinned as source text, in
    // test__panel_page.py, where `Date.UTC` is checked no matter what clock the
    // machine keeps. Two weak instruments, and between them the gap is named
    // rather than left for somebody to find.
    for (const d of ['2026-01-01', '2026-06-15', '2026-12-31']) {
      expect(Number.isInteger(panel.dnum(d)), d).toBe(true);
    }
  });

  it('crosses a DST boundary without drifting, because nothing here is civil '
     + 'time', () => {
    // A civil day is 23 or 25 hours at a DST edge; these are UTC days, so the
    // arithmetic is unaffected. The dates below straddle the EU and US
    // transitions in 2026.
    expect(panel.dnum('2026-03-30') - panel.dnum('2026-03-28')).toBe(2);
    expect(panel.dnum('2026-11-02') - panel.dnum('2026-10-31')).toBe(2);
    expect(panel.dayIso(panel.dnum('2026-03-29') + 1)).toBe('2026-03-30');
  });
});
