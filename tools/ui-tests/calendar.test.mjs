// The heatmap calendar, tested for the first time.
//
// It existed twice — once inside the report's IIFE and once inside the panel's
// uHeatmap, under the same five names — and this harness carried a note saying
// why neither copy could be checked: "they live inside an inner scope and close
// over locals, so neither is reachable without changing the source, and a source
// change is a separate decision from adding a test." Hoisting it into
// shared/calendar.js WAS that source change, and this is the test the note was
// waiting for.
//
// Every case is derived from the calendar, not from either old copy: agreeing
// with a copy is not the claim. The dates are picked where calendars go wrong —
// leap years, century non-leap years, month ends, ISO week starts, year edges.
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

const NAMES = ['weekdayIndex', 'periodStart', 'periodEnd', 'periodShift', 'seekPeriod'];
const panel = reach(loadPanel().ctx, NAMES);
const report = reach(loadReport().ctx, NAMES);

describe('both surfaces get the same calendar', () => {
  it('one implementation, not two that agree', () => {
    for (const n of NAMES) {
      expect(String(report[n]), n).toBe(String(panel[n]));
    }
  });
});

describe('weekdayIndex is Monday-first', () => {
  it('names each day of a known week', () => {
    // 2026-08-17 is a Monday.
    const week = ['2026-08-17', '2026-08-18', '2026-08-19', '2026-08-20',
      '2026-08-21', '2026-08-22', '2026-08-23'];
    expect(week.map(panel.weekdayIndex)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it('and Sunday is 6, not 0 — the rotation is the whole point', () => {
    expect(panel.weekdayIndex('2026-08-23')).toBe(6);
    expect(new Date('2026-08-23T00:00:00Z').getUTCDay()).toBe(0);
  });
});

describe('periodStart', () => {
  it('a week starts on its Monday, from any day inside it', () => {
    for (const d of ['2026-08-17', '2026-08-20', '2026-08-23']) {
      expect(panel.periodStart('week', d), d).toBe('2026-08-17');
    }
  });

  it('a month and a year start on their first day', () => {
    expect(panel.periodStart('month', '2026-08-20')).toBe('2026-08-01');
    expect(panel.periodStart('year', '2026-08-20')).toBe('2026-01-01');
  });

  it('a day is its own start, and so is an unknown granularity', () => {
    expect(panel.periodStart('day', '2026-08-20')).toBe('2026-08-20');
    expect(panel.periodStart('all', '2026-08-20')).toBe('2026-08-20');
  });

  it('a week crossing a month or a year boundary still starts on its Monday', () => {
    expect(panel.periodStart('week', '2026-09-02')).toBe('2026-08-31');
    expect(panel.periodStart('week', '2027-01-01')).toBe('2026-12-28');
  });
});

describe('periodEnd', () => {
  it('a week ends six days later', () => {
    expect(panel.periodEnd('week', '2026-08-17')).toBe('2026-08-23');
    expect(panel.periodEnd('week', '2026-12-28')).toBe('2027-01-03');
  });

  it('a month ends on its real last day — the leap-year cases', () => {
    expect(panel.periodEnd('month', '2024-02-01')).toBe('2024-02-29');
    expect(panel.periodEnd('month', '2026-02-01')).toBe('2026-02-28');
    // 2000 was a leap year; 1900 and 2100 are not. The "day zero of the
    // following month" spelling gets all three without a rule of its own.
    expect(panel.periodEnd('month', '2000-02-01')).toBe('2000-02-29');
    expect(panel.periodEnd('month', '2100-02-01')).toBe('2100-02-28');
  });

  it('a 30-day month, a 31-day month, and December', () => {
    expect(panel.periodEnd('month', '2026-04-01')).toBe('2026-04-30');
    expect(panel.periodEnd('month', '2026-07-01')).toBe('2026-07-31');
    expect(panel.periodEnd('month', '2026-12-01')).toBe('2026-12-31');
  });

  it('a year ends on the last of December', () => {
    expect(panel.periodEnd('year', '2026-01-01')).toBe('2026-12-31');
  });
});

describe('periodShift', () => {
  it('steps a day, a week, a month and a year in both directions', () => {
    expect(panel.periodShift('day', '2026-08-20', 1)).toBe('2026-08-21');
    expect(panel.periodShift('day', '2026-08-20', -1)).toBe('2026-08-19');
    expect(panel.periodShift('week', '2026-08-17', 1)).toBe('2026-08-24');
    expect(panel.periodShift('week', '2026-08-17', -1)).toBe('2026-08-10');
    expect(panel.periodShift('month', '2026-08-01', 1)).toBe('2026-09-01');
    expect(panel.periodShift('month', '2026-08-01', -1)).toBe('2026-07-01');
    expect(panel.periodShift('year', '2026-01-01', 1)).toBe('2027-01-01');
    expect(panel.periodShift('year', '2026-01-01', -1)).toBe('2025-01-01');
  });

  it('crosses a year boundary in both directions', () => {
    expect(panel.periodShift('month', '2026-12-01', 1)).toBe('2027-01-01');
    expect(panel.periodShift('month', '2026-01-01', -1)).toBe('2025-12-01');
    expect(panel.periodShift('day', '2026-12-31', 1)).toBe('2027-01-01');
  });

  it('and a step then its inverse is where it started, over every grain', () => {
    for (const [g, s] of [['day', '2026-08-20'], ['week', '2026-08-17'],
      ['month', '2026-08-01'], ['year', '2026-01-01']]) {
      expect(panel.periodShift(g, panel.periodShift(g, s, 1), -1), g).toBe(s);
    }
  });
});

describe('seekPeriod walks to the next period that HOLDS something', () => {
  const bounds = { lo: '2026-08-01', hi: '2026-08-31' };
  /** A predicate over an explicit set of recorded days. */
  const held = (days) => (from, to) => days.some((d) => d >= from && d <= to);

  it('steps over an empty period to reach a populated one', () => {
    // Data on the 3rd and the 20th only: from the 3rd, the next populated DAY is
    // the 20th, seventeen empty days later.
    expect(panel.seekPeriod('day', '2026-08-03', 1, bounds,
      held(['2026-08-03', '2026-08-20']))).toBe('2026-08-20');
  });

  it('answers null when nothing populated lies that way', () => {
    expect(panel.seekPeriod('day', '2026-08-20', 1, bounds,
      held(['2026-08-03', '2026-08-20']))).toBe(null);
  });

  it('stops at the bounds rather than walking out of them', () => {
    // Data outside the window must not be reachable.
    expect(panel.seekPeriod('day', '2026-08-30', 1, bounds,
      held(['2026-09-15']))).toBe(null);
  });

  it('walks backwards too', () => {
    expect(panel.seekPeriod('day', '2026-08-20', -1, bounds,
      held(['2026-08-03', '2026-08-20']))).toBe('2026-08-03');
  });

  it('clamps a period that straddles the bounds, so partial overlap counts', () => {
    // The week of the 27th runs to 2026-09-02, past `hi`. Its clamped window is
    // the 27th to the 31st, and data on the 28th is inside it.
    expect(panel.seekPeriod('week', '2026-08-17', 1,
      { lo: '2026-08-01', hi: '2026-08-31' }, held(['2026-08-28'])))
      .toBe('2026-08-24');
  });

  it('stops walking BACKWARD out of the bounds too, and the STEP COUNT is what '
     + 'shows it', () => {
    // `en < b.lo || cur > b.hi` — two halves, and the forward case above only
    // exercises the second. Asserting `null` cannot tell them apart: with the
    // first half removed the walk still returns null, having run its full four
    // thousand iterations to get there. So the predicate counts its calls, which
    // is the only observable difference between "stopped at the edge" and
    // "gave up eventually".
    let calls = 0;
    const counted = () => { calls += 1; return false; };
    expect(panel.seekPeriod('day', '2026-08-05', -1, bounds, counted)).toBe(null);
    // Four steps back from the 5th reaches the 1st; the fifth leaves the window.
    expect(calls, 'it walked ' + calls + ' step(s) instead of stopping at the '
      + 'lower bound').toBeLessThan(10);
  });

  it('and terminates on a granularity that fails to advance', () => {
    // An unknown grain returns its input from periodShift, so the walk makes no
    // progress and only the iteration cap ends it.
    //
    // THIS CASE CANNOT FAIL CLEANLY, and saying so is the point of the comment.
    // Removing the cap makes the loop spin SYNCHRONOUSLY inside the vm, which
    // blocks the worker — vitest's own per-test timeout cannot interrupt it, so
    // the suite hangs rather than going red. Verified by trying it. The value
    // here is that it terminates at all, and the cap's justification lives beside
    // the cap; nothing short of a watchdog process could turn its removal into a
    // failing test, and a watchdog for one line is not a trade worth making.
    expect(panel.seekPeriod('nonsense', '2026-08-10', 1, bounds, held([])))
      .toBe(null);
  });
});
