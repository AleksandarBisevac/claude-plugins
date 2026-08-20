// ---------- remembering something, best-effort ----------
// Fourteen sites wrapped `localStorage` in their own `try`/`catch` and every one
// of them meant the same thing: a document opened over `file://` may refuse
// storage outright, and neither surface may break when it does. The report is
// opened from a CI artifact by someone who cannot fix it; the panel is served
// from a real origin and works, which is exactly how a report-only failure
// hides.
//
// Nothing here reports a refusal, and that is the contract rather than an
// omission: every existing caller was already ignoring it, and a return value
// nobody reads is noise. A caller that one day needs to say "your filter could
// not be saved" should add the reporting variant then, and say it in the UI —
// not read a boolean and drop it.

/**
 * A stored string, or `null` if there is none or storage refused.
 *
 * The two cases collapse deliberately: no caller here can act differently on
 * "never stored" than on "cannot read", and both mean fall back to the default.
 *
 * @param {string} key Storage key.
 * @returns {?string} The stored value, or null.
 */
function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

/**
 * Store a string, ignoring a refusal.
 *
 * @param {string} key Storage key.
 * @param {string} value Value to store.
 * @returns {void}
 */
function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) { /* a file:// document may refuse; the page still works */ }
}

/**
 * Forget a key, ignoring a refusal.
 *
 * Separate from `storageSet(key, '')`: an empty string is a value, and a reader
 * that stored one would restore an empty filter rather than its default.
 *
 * @param {string} key Storage key.
 * @returns {void}
 */
function storageDrop(key) {
  try {
    localStorage.removeItem(key);
  } catch (e) { /* as above */ }
}
