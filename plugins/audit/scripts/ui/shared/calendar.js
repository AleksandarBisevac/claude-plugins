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
