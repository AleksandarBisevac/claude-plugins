// ---------- handing the viewer a file ----------
// One implementation, because there were four and they disagreed about the one
// thing that is easy to get wrong: WHEN to revoke the object URL.
//
// Revoking is not optional — without it the page holds the blob for the rest of
// its lifetime, and a report left open on a CI artifact holds a decoded copy of
// its own Markdown twin. Revoking EARLY is worse than not revoking: some engines
// have not started reading when `click()` returns, so a URL revoked at that point
// is a download that fails with no error anywhere, on some machines, sometimes.
//
// The four sites this replaces had three different answers — two waited 4000ms,
// one waited 1000ms, and one revoked synchronously right after `click()` with a
// comment defending it, while its sibling part in the SAME surface carried a
// comment arguing the opposite. That is the shape this layer exists to end: not
// four copies of one rule, but four copies that had quietly become three rules.

/**
 * Hand a blob to the browser as a file download.
 *
 * Self-contained on purpose: this part is concatenated into BOTH surfaces, and
 * the report has no `el()` builder, so the element is built with raw DOM calls
 * that exist on both pages.
 *
 * @param {string} name Filename offered to the reader.
 * @param {Blob} blob Payload to save.
 * @returns {void}
 */
function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Late, and this delay is the whole argument above. Do not shorten it to make
  // a test faster: the failure it prevents is invisible and machine-dependent.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/**
 * The same, for text: builds the blob so callers do not each pick a charset.
 *
 * Every caller was appending `;charset=utf-8` by hand, which is the second thing
 * four copies of one rule drift on.
 *
 * @param {string} name Filename offered to the reader.
 * @param {string} text Payload to save.
 * @param {string} mime Media type without a charset, e.g. `'text/csv'`.
 * @returns {void}
 */
function downloadText(name, text, mime) {
  download(name, new Blob([text], { type: mime + ';charset=utf-8' }));
}
