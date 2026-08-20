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
