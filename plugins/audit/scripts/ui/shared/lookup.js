// ---------- reading a table with a key that came from outside ----------
/**
 * One entry of a lookup table, read as an OWN property.
 *
 * A bare `TABLE[k]` walks the prototype chain, so a key that happens to name
 * something on `Object.prototype` answers with THAT instead of with a miss, and
 * the `||` fallback written beside the read is unreachable for exactly those
 * names. `label('constructor')` returned a function from a helper documented to
 * return a string; `label('toString')`, `'valueOf'`, `'hasOwnProperty'` did the
 * same, and `'__proto__'` returned an object.
 *
 * The keys are not hypothetical, and both surfaces are reachable. On the panel,
 * `testEvidence.status` is enum-constrained in the JSON Schema and restated
 * nowhere on the Python side, so a hand-written or third-party manifest carries
 * whatever it likes; `area` tags, `model` names and `review.status` are
 * documented free text; and the usage tab decodes its filter dimensions
 * straight out of the URL fragment. The REPORT is the worse case, because it
 * needs no manifest at all: a rendered report is handed around as a CI artifact
 * and published to a link, and `#!v=constructor` alone used to reach
 * `VIEWS[viewMode]` with a function and throw out of the first filter pass.
 *
 * A miss answers `undefined` — which is what the bare read answered — so an
 * existing `||`, `??` or `===undefined` beside the call keeps behaving exactly
 * as it did for every key that is not an inherited property name.
 *
 * This guards READING a table the code wrote as a literal. A map the code
 * BUILDS from outside keys needs `Object.create(null)` instead, because
 * `m['__proto__']=v` on a plain object re-points the prototype rather than
 * storing the value, and no read helper can recover what was never written. A
 * map built that way needs no `lookup` either: with no prototype, `m[k]` is
 * already own-or-undefined.
 *
 * @param {Object<string, *>} t - the table to read
 * @param {string|number|null|undefined} k - the key, from wherever it came
 * @returns {*} the table's own value for `k`, or undefined when it has none
 */
const lookup=(t,k)=>Object.prototype.hasOwnProperty.call(t,k)?t[k]:undefined;
