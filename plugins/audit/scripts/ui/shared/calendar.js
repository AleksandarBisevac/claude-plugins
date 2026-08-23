// ---------- the heatmap calendar, for both surfaces ----------
// WRITTEN TWICE, under the same names, for as long as both heatmaps have existed:
// startOf / endOf / shift / seek and a Monday-first weekday, once inside the
// report's nested IIFE and once inside the panel's uHeatmap. The sandbox harness
// has carried a note the whole time saying so and saying why neither copy was
// tested — "they live inside an inner scope and close over locals, so neither is
// reachable without changing the source, and a source change is a separate
// decision from adding a test".
//
// This is that source change. The calendar is arithmetic over ISO day strings and
// closes over nothing, so hoisting it costs no state; what it buys is one
// implementation and, for the first time, one that a test can call.
//
// The two copies had already drifted in spelling without drifting in meaning —
// the panel built a month's last day from its day-of-month while the report
// formatted the whole instant, and the panel counted days where the report
// counted milliseconds. Every case below is checked against the calendar rather
// than against either copy, because agreeing with a copy is not the claim.

/**
 * Weekday index of an ISO day, MONDAY FIRST, which is what both grids' rows are.
 *
 * `getUTCDay` is Sunday-first, so the `+6 % 7` is the rotation and not a fudge.
 *
 * @param {string} iso - a `YYYY-MM-DD` day
 * @returns {number} 0 for Monday through 6 for Sunday
 */
const weekdayIndex = (iso) => (new Date(iso + 'T00:00:00Z').getUTCDay() + 6) % 7;

/**
 * The first ISO day of the period `iso` falls in.
 *
 * @param {'day'|'week'|'month'|'year'} g - granularity; anything else is a day
 * @param {string} iso - a `YYYY-MM-DD` day
 * @returns {string} the day the period starts on
 */
function periodStart(g, iso) {
  if (g === 'week') return dayIso(dnum(iso) - weekdayIndex(iso));
  if (g === 'month') return iso.slice(0, 7) + '-01';
  if (g === 'year') return iso.slice(0, 4) + '-01-01';
  return iso;
}

/**
 * The last ISO day of the period STARTING at `s`.
 *
 * @param {'day'|'week'|'month'|'year'} g - granularity
 * @param {string} s - the day the period starts on
 * @returns {string} the day the period ends on
 */
function periodEnd(g, s) {
  if (g === 'week') return dayIso(dnum(s) + 6);
  // Day zero of the FOLLOWING month is the last day of this one, which is the
  // only spelling that gets February right without a leap-year rule of its own.
  if (g === 'month') return dayIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7), 0) / DAY_MS);
  if (g === 'year') return s.slice(0, 4) + '-12-31';
  return s;
}

/**
 * The period one step away, whether or not it holds anything.
 *
 * @param {'day'|'week'|'month'|'year'} g - granularity
 * @param {string} s - the day the current period starts on
 * @param {number} dir - -1 for earlier, 1 for later
 * @returns {string} the day the neighbouring period starts on
 */
function periodShift(g, s, dir) {
  if (g === 'day') return dayIso(dnum(s) + dir);
  if (g === 'week') return dayIso(dnum(s) + 7 * dir);
  if (g === 'month') {
    return dayIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1 + dir, 1) / DAY_MS);
  }
  if (g === 'year') return (+s.slice(0, 4) + dir) + '-01-01';
  return s;
}

/**
 * The next period in `dir` that lies inside the bounds AND records something.
 *
 * "Never navigate into an empty period" is a rule about DATA rather than about
 * the calendar, which is why the data arrives as a predicate: each surface holds
 * its days differently — one a sorted array, the other an object — and each has a
 * reason. Both loop rather than materialising keys, because this walk steps up to
 * four thousand periods and an allocation per step turns a first-hit scan into a
 * full one.
 *
 * BOUNDED rather than `while (true)`: leaving the bounds is what normally stops
 * the walk, and a granularity whose shift failed to advance would otherwise spin
 * with the tab frozen.
 *
 * @param {'day'|'week'|'month'|'year'} g - granularity
 * @param {string} s - the day the current period starts on
 * @param {number} dir - -1 for earlier, 1 for later
 * @param {{lo: string, hi: string}} b - the window the surface may show
 * @param {function(string, string): boolean} hasData - whether any recorded day
 *   falls inside a closed range of ISO days
 * @returns {?string} the start of the next populated period, or null when the
 *   walk leaves the bounds first
 */
function seekPeriod(g, s, dir, b, hasData) {
  let cur = s;
  for (let i = 0; i < 4000; i++) {
    cur = periodShift(g, cur, dir);
    const en = periodEnd(g, cur);
    if (en < b.lo || cur > b.hi) return null;
    const lo = cur < b.lo ? b.lo : cur;
    const hi = en > b.hi ? b.hi : en;
    if (hasData(lo, hi)) return cur;
  }
  return null;
}

// ---------- the rows a granularity draws, for both surfaces ----------
// THE SHAPE IS THE GRANULARITY, and it was not.
//
// Month used to fall into the same branch as year and all — seven weekday rows,
// each cell summed over the four-or-so occurrences of that weekday — so picking
// Month repainted Week's picture with the numbers quietly multiplied. Reported
// as exactly that: "it should show the days of the month, and for each day the
// accumulated spend; honestly it looks like a copy of the weekly view." Both
// surfaces did it, under one comment each saying so.
//
// The ladder now reduces once per rung and never twice: a day is one date, a
// week is its seven dates, a month is its own dates, a year is its twelve
// months, and All is the weekly rhythm over the whole span. No two rungs can
// draw the same grid, because no two produce the same rows — which is what
// leaves each surface's own "cannot differ" rule free to be about navigation
// rather than about the picture.
//
// The HOUR AXIS survives every rung on purpose. It is the card's entire subject
// ("when the tokens are spent"), so a rung that traded it for a daily total — a
// calendar grid of weeks by weekdays, say — would answer a different question
// than the four rungs around it.
//
// The DATA arrives as an accessor and a day list, for the same reason seekPeriod
// takes a predicate: the report holds its days as an object keyed by date and
// the panel as a Map built from the filtered facts, and each has a reason.

/**
 * Row labels for the weekday grid, Monday first — the order weekdayIndex()
 * returns. Both surfaces spelled this array themselves.
 * @type {string[]}
 */
const WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/**
 * Month names, January at index 0. Both surfaces spelled this one too, one of
 * them under a prefix.
 * @type {string[]}
 */
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

/** @const {number} Columns in every heatmap grid: the hours of a UTC day. */
const HEAT_HOURS = 24;

/**
 * One row of a heatmap grid.
 *
 * @typedef {Object} HeatRow
 * @property {string} label Printed in the leftmost column, and kept short
 *   because that column is narrow on a phone.
 * @property {string} head Row name used in every cell's tooltip, where there is
 *   room to say it in full.
 * @property {?number[]} cells The 24 hourly totals, or null for a row the active
 *   range excludes entirely — which a cell renders as "outside the selected
 *   range" rather than as a zero it cannot know.
 */

/**
 * A zero-filled hour vector. Built per call rather than shared between rows: a
 * caller that mutated one would otherwise move every row that took the default.
 *
 * @returns {number[]} 24 zeroes
 */
const zeroHours = () => new Array(HEAT_HOURS).fill(0);

/**
 * Add one day's hours into a running total, in place.
 *
 * `vec` may be shorter than 24 — the report ships a day's hours as whatever the
 * ledger recorded — so every read is defaulted rather than the length trusted.
 *
 * @param {number[]} into - the running total, always 24 long
 * @param {number[]} vec - one day's hours
 * @returns {void}
 */
function addHours(into, vec) {
  for (let h = 0; h < HEAT_HOURS; h++) into[h] += vec[h] || 0;
}

/**
 * One row per calendar date from `s` to `en` — the shape a day, a week and a
 * month all draw, differing only in how many dates that is.
 *
 * The row list is the whole PERIOD, not the part of it the range leaves: a week
 * clipped by a custom range still shows seven rows, so the reader sees which
 * days are missing instead of a shorter grid that looks complete. A month does
 * the same, which is why its row count is the length of the month rather than
 * the number of dates that recorded anything.
 *
 * @param {string} s - first ISO day of the period
 * @param {string} en - last ISO day of the period
 * @param {string} lo - first ISO day the active range admits
 * @param {string} hi - last ISO day the active range admits
 * @param {function(string): number[]} hoursOf - a day's 24 hourly totals
 * @returns {HeatRow[]}
 */
function dateRows(s, en, lo, hi, hoursOf) {
  const rows = [];
  for (let n = dnum(s); n <= dnum(en); n++) {
    const d = dayIso(n);
    const name = WEEKDAY_NAMES[weekdayIndex(d)];
    rows.push({ label: name + ' ' + d.slice(5),
                head: name + ' ' + d,
                cells: (d >= lo && d <= hi) ? hoursOf(d).slice() : null });
  }
  return rows;
}

/**
 * Twelve rows, one per calendar month of the year `s` falls in.
 *
 * A year is the one rung where per-date rows stop being readable — 365 of them
 * is not a grid anyone reads — so this is where the ladder aggregates, and it
 * aggregates by the unit below it rather than jumping to weekdays. A month the
 * active range excludes outright carries null, the same claim `dateRows` makes
 * about an excluded date; a month inside the range that simply recorded nothing
 * carries zeroes, because that is a fact rather than an absence.
 *
 * @param {string} s - any ISO day in the year to draw
 * @param {string} lo - first ISO day the active range admits
 * @param {string} hi - last ISO day the active range admits
 * @param {string[]} days - every ISO day the surface holds data for
 * @param {function(string): number[]} hoursOf - a day's 24 hourly totals
 * @returns {HeatRow[]}
 */
function monthRows(s, lo, hi, days, hoursOf) {
  const year = s.slice(0, 4);
  const sums = Array.from({ length: 12 }, zeroHours);
  for (const d of days) {
    if (d < lo || d > hi || d.slice(0, 4) !== year) continue;
    addHours(sums[+d.slice(5, 7) - 1], hoursOf(d));
  }
  return sums.map((cells, m) => {
    const first = year + '-' + ('0' + (m + 1)).slice(-2) + '-01';
    const inRange = first <= hi && periodEnd('month', first) >= lo;
    return { label: MONTH_NAMES[m].slice(0, 3),
             head: MONTH_NAMES[m] + ' ' + year,
             cells: inRange ? cells : null };
  });
}

/**
 * Seven weekday rows, each the hour-by-hour sum over every matching date in the
 * range — the weekly rhythm of a whole span.
 *
 * This is what "All" draws, and after the reshape it is the ONLY rung that draws
 * it: the range All covers has no calendar unit of its own, so there is no
 * per-period row list to build, and the weekday question ("are Thursday evenings
 * where the tokens go") is one a whole span can answer that a single month
 * cannot.
 *
 * @param {string} lo - first ISO day the active range admits
 * @param {string} hi - last ISO day the active range admits
 * @param {string[]} days - every ISO day the surface holds data for
 * @param {function(string): number[]} hoursOf - a day's 24 hourly totals
 * @returns {HeatRow[]}
 */
function weekdayRows(lo, hi, days, hoursOf) {
  const sums = Array.from({ length: 7 }, zeroHours);
  for (const d of days) {
    if (d < lo || d > hi) continue;
    addHours(sums[weekdayIndex(d)], hoursOf(d));
  }
  return sums.map((cells, wd) => ({ label: WEEKDAY_NAMES[wd],
                                    head: WEEKDAY_NAMES[wd], cells: cells }));
}

/**
 * The rows one granularity draws — the single place that decides the shape.
 *
 * @param {'all'|'year'|'month'|'week'|'day'} g - granularity; anything
 *   unrecognised draws the whole-span weekday grid, which is what 'all' is
 * @param {{s: string, en: string, lo: string, hi: string}} win - the period
 *   (`s`..`en`) and the part of it the active range admits (`lo`..`hi`)
 * @param {string[]} days - every ISO day the surface holds data for
 * @param {function(string): number[]} hoursOf - a day's 24 hourly totals
 * @returns {HeatRow[]}
 */
function heatRows(g, win, days, hoursOf) {
  if (g === 'day') return dateRows(win.lo, win.lo, win.lo, win.hi, hoursOf);
  if (g === 'week' || g === 'month') {
    return dateRows(win.s, win.en, win.lo, win.hi, hoursOf);
  }
  if (g === 'year') return monthRows(win.s, win.lo, win.hi, days, hoursOf);
  return weekdayRows(win.lo, win.hi, days, hoursOf);
}
