// The shape of a heatmap grid, per granularity.
//
// THE BUG THIS EXISTS FOR: month, year and all shared one branch in both
// surfaces — seven weekday rows, each cell summed over the four-or-so
// occurrences of that weekday inside the period. Picking Month therefore
// repainted Week's picture with the numbers multiplied, and the report's own
// comment said so out loud ("Rows for a month, a year or the whole range: seven
// weekday rows"). Reported as "it should show the days of the month, and for
// each day the accumulated spend; honestly it looks like a copy of the weekly
// view."
//
// Every case here is written against the CONTRACT rather than against either old
// copy, for the reason calendar.test.mjs gives beside it: agreeing with a copy is
// not the claim. Four of them are load-bearing and each says which mutation it
// is the red for.
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

const NAMES = ['heatRows', 'dateRows', 'monthRows', 'weekdayRows',
  'WEEKDAY_NAMES', 'MONTH_NAMES', 'HEAT_HOURS'];
const panel = reach(loadPanel().ctx, NAMES);
const report = reach(loadReport().ctx, NAMES);

const HOURS = panel.HEAT_HOURS;

/**
 * A ledger fixture: `spec` maps an ISO day to [hour, tokens] pairs.
 *
 * The VALUES are deliberately distinct primes-ish numbers rather than a repeated
 * constant, because the buggy shape SUMS across dates: a fixture that put the
 * same number in every cell would let a weekday aggregate and a per-date grid
 * agree on far too much, which is the fixture failure no-silent-pass names.
 */
function ledger(spec) {
  const days = Object.keys(spec).sort();
  const hours = new Map();
  for (const d of days) {
    const vec = new Array(HOURS).fill(0);
    for (const [h, n] of spec[d]) vec[h] += n;
    hours.set(d, vec);
  }
  return { days: days, hoursOf: (d) => hours.get(d) || new Array(HOURS).fill(0) };
}

/** Every cell of a grid, flattened — a null row counts as 24 nulls. */
const cellsOf = (rows) => rows.flatMap(
  (r) => Array.from({ length: HOURS }, (unused, h) => (r.cells ? (r.cells[h] || 0) : null)));

/** The whole grid as one comparable string: labels AND every cell. */
const fingerprint = (rows) => rows.map(
  (r) => r.label + '|' + (r.cells ? r.cells.map((v) => v || 0).join(',') : 'null')).join('\n');

/** The tokens a grid accounts for, nulls excluded. */
const total = (rows) => cellsOf(rows).reduce((a, v) => a + (v || 0), 0);

/**
 * The grid the OLD code drew for month, year and all alike: seven weekday rows.
 * Recomputed here from the fixture rather than imported, so the totals case
 * compares two independently produced numbers instead of a value with itself.
 */
function oldWeekdayGrid(lo, hi, data) {
  const sums = Array.from({ length: 7 }, () => new Array(HOURS).fill(0));
  for (const d of data.days) {
    if (d < lo || d > hi) continue;
    const wd = (new Date(d + 'T00:00:00Z').getUTCDay() + 6) % 7;
    const vec = data.hoursOf(d);
    for (let h = 0; h < HOURS; h++) sums[wd][h] += vec[h] || 0;
  }
  return sums;
}

// 2026-08-03 is a Monday; this spans five calendar weeks inside ONE month, which
// is the case the old code collapsed to seven rows.
const AUGUST = ledger({
  '2026-08-03': [[9, 1100], [14, 700]],
  '2026-08-04': [[9, 130]],
  '2026-08-10': [[9, 1900], [22, 40]],
  '2026-08-11': [[13, 250]],
  '2026-08-17': [[9, 60], [14, 3300]],
  '2026-08-20': [[7, 480]],
  '2026-08-24': [[9, 15]],
  '2026-08-31': [[18, 900]],
});
const AUG = { s: '2026-08-01', en: '2026-08-31', lo: '2026-08-03', hi: '2026-08-31' };

describe('both surfaces get the same row builders', () => {
  it('one implementation, not two that agree', () => {
    for (const n of ['heatRows', 'dateRows', 'monthRows', 'weekdayRows']) {
      expect(String(report[n]), n).toBe(String(panel[n]));
    }
    expect(report.WEEKDAY_NAMES).toEqual(panel.WEEKDAY_NAMES);
    expect(report.MONTH_NAMES).toEqual(panel.MONTH_NAMES);
    expect(report.HEAT_HOURS).toBe(panel.HEAT_HOURS);
  });
});

describe('Month draws the days of the month', () => {
  // RED FOR: month falling back into the weekday branch — the reported bug. The
  // fixture spans five weeks inside one August, so the buggy shape gives 7 and
  // the fixed one gives 31. A fixture inside a single week could not tell them
  // apart.
  it('a ledger spanning several weeks in ONE month gives a row per DATE', () => {
    const rows = panel.heatRows('month', AUG, AUGUST.days, AUGUST.hoursOf);
    expect(rows.length).toBe(31);
    expect(rows[0].label).toBe('Sat 08-01');
    expect(rows[30].label).toBe('Mon 08-31');
  });

  it('...and every date of the month is present, worked or not', () => {
    const rows = panel.heatRows('month', AUG, AUGUST.days, AUGUST.hoursOf);
    expect(rows.map((r) => r.head.slice(-2)))
      .toEqual(Array.from({ length: 31 }, (unused, i) => ('0' + (i + 1)).slice(-2)));
  });

  it('...a date the active range excludes carries null, not a zero it cannot know',
    () => {
      // lo is the 3rd, so the 1st and 2nd are outside the range the filter left.
      const rows = panel.heatRows('month', AUG, AUGUST.days, AUGUST.hoursOf);
      expect(rows[0].cells).toBe(null);
      expect(rows[1].cells).toBe(null);
      expect(rows[2].cells[9]).toBe(1100);
    });

  it('...and a February knows its own length, leap year included', () => {
    const feb = { s: '2024-02-01', en: '2024-02-29', lo: '2024-02-01', hi: '2024-02-29' };
    expect(panel.heatRows('month', feb, [], () => []).length).toBe(29);
    const feb26 = { s: '2026-02-01', en: '2026-02-28', lo: '2026-02-01', hi: '2026-02-28' };
    expect(panel.heatRows('month', feb26, [], () => []).length).toBe(28);
  });
});

describe('Month and Week are not the same picture', () => {
  // RED FOR: any fix that leaves the two grains sharing a builder or a branch.
  // The whole grid is fingerprinted rather than one number, because the two
  // shapes agree on plenty of individual cells.
  it('over the same underlying data they draw DIFFERENT grids', () => {
    const week = { s: '2026-08-17', en: '2026-08-23', lo: '2026-08-17', hi: '2026-08-23' };
    const monthGrid = panel.heatRows('month', AUG, AUGUST.days, AUGUST.hoursOf);
    const weekGrid = panel.heatRows('week', week, AUGUST.days, AUGUST.hoursOf);
    expect(fingerprint(monthGrid)).not.toBe(fingerprint(weekGrid));
    expect(monthGrid.length).not.toBe(weekGrid.length);
  });

  it('and no two granularities over one ledger draw the same grid', () => {
    const win = {
      all: { s: '2026-08-03', en: '2026-08-31', lo: '2026-08-03', hi: '2026-08-31' },
      year: { s: '2026-01-01', en: '2026-12-31', lo: '2026-08-03', hi: '2026-08-31' },
      month: AUG,
      week: { s: '2026-08-17', en: '2026-08-23', lo: '2026-08-17', hi: '2026-08-23' },
      day: { s: '2026-08-17', en: '2026-08-17', lo: '2026-08-17', hi: '2026-08-17' },
    };
    const seen = new Map();
    for (const g of ['all', 'year', 'month', 'week', 'day']) {
      const fp = fingerprint(panel.heatRows(g, win[g], AUGUST.days, AUGUST.hoursOf));
      expect(seen.has(fp), g + ' draws the same grid as ' + seen.get(fp)).toBe(false);
      seen.set(fp, g);
    }
  });
});

describe('Year draws its twelve months', () => {
  const YEAR = { s: '2026-01-01', en: '2026-12-31', lo: '2026-08-03', hi: '2026-08-31' };

  it('twelve rows, named for the months', () => {
    const rows = panel.heatRows('year', YEAR, AUGUST.days, AUGUST.hoursOf);
    expect(rows.length).toBe(12);
    expect(rows.map((r) => r.label)).toEqual(
      ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct',
        'Nov', 'Dec']);
    expect(rows[7].head).toBe('August 2026');
  });

  it('a month outside the active range is null; the one inside carries the sum',
    () => {
      const rows = panel.heatRows('year', YEAR, AUGUST.days, AUGUST.hoursOf);
      expect(rows[0].cells).toBe(null);          // January, outside 08-03..08-31
      expect(rows[11].cells).toBe(null);         // December, ditto
      // Hour 9 in August: 1100 + 130 + 1900 + 60 + 15 across five dates.
      expect(rows[7].cells[9]).toBe(1100 + 130 + 1900 + 60 + 15);
    });

  it('a month INSIDE the range that recorded nothing is zero, not null - that '
     + 'is a fact rather than an absence', () => {
    // The second direction: the null must not become unconditional. This case
    // passes trivially on a builder that never nulls anything, and is the only
    // one that fails when every month is nulled.
    const wide = { s: '2026-01-01', en: '2026-12-31', lo: '2026-01-01', hi: '2026-12-31' };
    const rows = panel.heatRows('year', wide, AUGUST.days, AUGUST.hoursOf);
    expect(rows[0].cells).not.toBe(null);
    expect(rows[0].cells.every((v) => v === 0)).toBe(true);
    expect(rows[0].cells.length).toBe(HOURS);
  });
});

describe('the totals are conserved by the reshape', () => {
  // RED FOR: a reshaping that drops a date or counts one twice. Both would look
  // like a success on the screen, which is why this compares against a grid
  // computed independently above rather than against another call.
  const cases = [
    ['month', AUG],
    ['year', { s: '2026-01-01', en: '2026-12-31', lo: '2026-08-03', hi: '2026-08-31' }],
    ['all', { s: '2026-08-03', en: '2026-08-31', lo: '2026-08-03', hi: '2026-08-31' }],
  ];
  const everyToken = 1100 + 700 + 130 + 1900 + 40 + 250 + 60 + 3300 + 480 + 15 + 900;

  for (const [g, win] of cases) {
    it(g + ' accounts for exactly the tokens the old weekday grid did', () => {
      const old = oldWeekdayGrid(win.lo, win.hi, AUGUST)
        .reduce((a, row) => a + row.reduce((b, v) => b + v, 0), 0);
      expect(old).toBe(everyToken);        // the fixture agrees with itself first
      expect(total(panel.heatRows(g, win, AUGUST.days, AUGUST.hoursOf))).toBe(old);
    });
  }

  it('and a clipped range drops exactly the dates outside it, no more', () => {
    const clipped = { s: '2026-08-01', en: '2026-08-31',
      lo: '2026-08-10', hi: '2026-08-20' };
    const kept = 1900 + 40 + 250 + 60 + 3300 + 480;
    expect(total(panel.heatRows('month', clipped, AUGUST.days, AUGUST.hoursOf)))
      .toBe(kept);
    expect(total(panel.heatRows('all', clipped, AUGUST.days, AUGUST.hoursOf)))
      .toBe(kept);
  });
});

describe('Day and Week are exactly what they were', () => {
  // RED FOR: the opposite over-correction — a fix that made every granularity
  // per-date, or that changed the two rungs nobody complained about.
  it('Day is one row, carrying that date and no other', () => {
    const win = { s: '2026-08-17', en: '2026-08-17', lo: '2026-08-17', hi: '2026-08-17' };
    const rows = panel.heatRows('day', win, AUGUST.days, AUGUST.hoursOf);
    expect(rows.length).toBe(1);
    expect(rows[0].head).toBe('Mon 2026-08-17');
    expect(rows[0].cells[9]).toBe(60);
    expect(rows[0].cells[14]).toBe(3300);
    expect(total(rows)).toBe(3360);
  });

  it('Week is seven dated rows, Monday first, keeping its shape where the range '
     + 'clips it', () => {
    const win = { s: '2026-08-17', en: '2026-08-23', lo: '2026-08-17', hi: '2026-08-20' };
    const rows = panel.heatRows('week', win, AUGUST.days, AUGUST.hoursOf);
    expect(rows.length).toBe(7);
    expect(rows.map((r) => r.label)).toEqual(
      ['Mon 08-17', 'Tue 08-18', 'Wed 08-19', 'Thu 08-20', 'Fri 08-21',
        'Sat 08-22', 'Sun 08-23']);
    expect(rows[4].cells).toBe(null);          // the 21st is past `hi`
    expect(total(rows)).toBe(60 + 3300 + 480);
  });

  it('All is still the seven weekday aggregates, cell for cell', () => {
    const win = { s: '2026-08-03', en: '2026-08-31', lo: '2026-08-03', hi: '2026-08-31' };
    const rows = panel.heatRows('all', win, AUGUST.days, AUGUST.hoursOf);
    expect(rows.map((r) => r.label)).toEqual(panel.WEEKDAY_NAMES);
    expect(rows.map((r) => r.cells))
      .toEqual(oldWeekdayGrid(win.lo, win.hi, AUGUST));
  });

  it('...and an unrecognised granularity draws All rather than nothing', () => {
    const win = { s: '2026-08-03', en: '2026-08-31', lo: '2026-08-03', hi: '2026-08-31' };
    expect(fingerprint(panel.heatRows('nonsense', win, AUGUST.days, AUGUST.hoursOf)))
      .toBe(fingerprint(panel.heatRows('all', win, AUGUST.days, AUGUST.hoursOf)));
  });
});

describe('a row never shares its cell array with another', () => {
  // The default hour vector used to be a fresh array at every call site; a
  // shared one would make a single mutation move every empty row at once.
  it('two empty AGGREGATE rows do not alias - the shapes that build their own '
     + 'zero vector', () => {
    const wide = { s: '2026-01-01', en: '2026-12-31', lo: '2026-01-01', hi: '2026-12-31' };
    for (const g of ['year', 'all']) {
      const rows = panel.heatRows(g, wide, [], () => []);
      rows[0].cells[5] = 99;
      expect(rows[1].cells[5], g).toBe(0);
    }
  });

  it('and a date row does not alias the surface\'s own storage', () => {
    const rows = panel.heatRows('day',
      { s: '2026-08-17', en: '2026-08-17', lo: '2026-08-17', hi: '2026-08-17' },
      AUGUST.days, AUGUST.hoursOf);
    rows[0].cells[9] = 1;
    expect(AUGUST.hoursOf('2026-08-17')[9]).toBe(60);
  });
});
