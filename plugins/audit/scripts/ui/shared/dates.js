// ---------- one day, in milliseconds ----------
/**
 * Milliseconds in a day.
 *
 * Spelled `864e5` at eight sites across four panel parts and `86400000` once in
 * the report's heatmap, which is the same number under two names — and the
 * registry needled the CONSTANT rather than the arithmetic for exactly that
 * reason: a narrower pattern found five of the nine and a shell regex found
 * three, because the divisions and the multiplications look nothing alike.
 *
 * Named for its UNIT, not for what it divides. `DAY` alone reads as a date on
 * one side of a call and as a duration on the other, and the panel's uses are
 * both: `ms / DAY_MS` is a day NUMBER, `n * DAY_MS` is a timestamp.
 *
 * A CIVIL day is not always this long — a DST boundary makes one 23 or 25 hours.
 * Nothing here is affected, because every caller works in UTC: the panel's day
 * numbers come from `Date.UTC` and go back out through `toISOString`, and the
 * ledger's days are UTC dates. A caller that ever wants LOCAL day boundaries must
 * not reach for this; it wants a date library, or the arithmetic done by the
 * platform.
 *
 * @const {number}
 */
const DAY_MS = 86400000;

/**
 * A UTC day number — whole days since the epoch — from a `YYYY-MM-DD` string.
 *
 * The panel's whole date vocabulary is this integer: a span is a subtraction, a
 * week is `+7`, a bin lookup is a binary search over it. `Date.UTC` and not
 * `new Date(str)`, because the second parses `'2026-08-20'` as UTC midnight and
 * `'2026-8-20'` as LOCAL midnight, and every day here is a UTC date.
 *
 * SHARED, and it began the day in `panel/core.js` with a note saying it had one
 * reader. True then, and wrong as soon as the two heatmap calendars were factored
 * into `shared/calendar.js`: a shared part cannot reach back into a surface, so
 * the calendar's own primitives have to sit at least as high as it does. The note
 * is worth reading as a warning about notes, not about this function.
 *
 * @param {string} d - a `YYYY-MM-DD` date
 * @returns {number} whole days since 1970-01-01, UTC
 */
const dnum = (d) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1,
                             +d.slice(8, 10)) / DAY_MS;

/**
 * The inverse: a `YYYY-MM-DD` string from a UTC day number.
 *
 * Spelled identically as a local `const iso` inside three separate panel
 * functions before it had a home — the shape a one-line helper takes when there
 * is nowhere to put it: small enough to retype, and then three things to fix when
 * one of them is wrong. `toISOString` is UTC by definition, so the round trip
 * with `dnum` cannot drift.
 *
 * @param {number} n - whole days since 1970-01-01, UTC
 * @returns {string} the date as `YYYY-MM-DD`
 */
const dayIso = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);
