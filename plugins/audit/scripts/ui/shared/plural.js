// ---------- a count and its noun, agreeing ----------
/**
 * `n` and its noun, agreeing — `1 task`, `3 tasks`, `2 people`.
 *
 * A mirror of `_fmt.plural`, down to the `%d`: the number is TRUNCATED toward
 * zero the way Python's `%d` truncates, so a fractional count cannot render a
 * decimal on one surface and an integer on the other. Held equal to it by
 * `tools/ui-tests/plural.test.mjs`, which asks the live Python.
 *
 * `many` is for the irregular case and is not decoration. Python's caller counts
 * `person`/`people`, which no suffix rule produces; the report's one caller needs
 * both halves of a clause where the NOUN and the VERB both change — `phase
 * matches` against `phases match` — and supplying `many` in full is what lets one
 * function serve that as well as `1 change` / `2 changes`.
 *
 * Shared rather than surface-local because both surfaces spell it. The panel had
 * two competing conventions for the same rule (a bare suffix, `+(n===1?'':'s')`,
 * and a literal `(s)` that agrees with nothing), and the report had a third; a
 * rule small enough to look cheaper than reaching for it is exactly the rule that
 * ends up with no owner.
 *
 * @param {number} n - the count
 * @param {string} one - the noun as it reads for a count of one
 * @param {string} [many] - the plural form, when adding 's' will not do
 * @returns {string} the count and the agreeing noun, space-separated
 */
function plural(n, one, many) {
  const i = Math.trunc(n) || 0;
  return i + ' ' + (i === 1 ? one : (many || one + 's'));
}
