// ---------- the build serving this page, against the one installed (F100) ----------
//
// The panel is ephemeral and keyed by a per-project pidfile, so a relaunch after
// an upgrade FINDS the running instance and points at it — and that instance is
// still serving the page an older build assembled. `core.js` stamps the build the
// page was assembled FROM into the header, which is half the answer; the other
// half is what is on disk NOW, and only the server can read that. This part asks
// `GET /api/version` for the comparison and interrupts the reader when, and only
// when, the answer is that the two disagree.
//
// NOTHING HERE RE-ASSEMBLES ANYTHING, and that is a decision recorded in
// panel-server.py rather than an omission: a per-request re-assembly would serve
// a new front end off an old API and stamp the new version on it, which is a page
// that lies rather than one that lags. The honest repair is a relaunch, so that is
// what the banner asks for.
/**
 * The sentence a stale panel shows, naming both builds.
 *
 * SEPARATE FROM THE NODE BECAUSE THE WORDS ARE THE CLAIM. "you are on an old
 * build" is an assertion, and these two strings are its basis: a reader who can
 * see which build against which knows whether the difference explains what they
 * came to the panel about. A sentence built inside a DOM call is a sentence no
 * suite can read back, so it lives here where one can.
 *
 * @param {{assembled: ?string, installed: ?string}} state - the
 *   `GET /api/version` payload
 * @returns {string} the banner's prose
 */
function vbWords(state) {
  return 'The page came from plugin ' + state.assembled + ', and plugin.json now '
    + 'says ' + state.installed + '. A reload will not pick that up — the page is '
    + 'assembled once, when the server starts — so stop the panel and start it '
    + 'again.';
}

/**
 * The banner for a panel serving a page an older build assembled, or null when
 * there is nothing to say.
 *
 * ONE OF THE THREE ANSWERS PAINTS AND THE OTHER TWO DO NOT, and which two is the
 * whole reason the endpoint reports three. `stale:false` is a comparison that was
 * made and came out equal — there is nothing to interrupt anybody about.
 * `stale:null` is NOT a quieter version of that: it means one half of the
 * comparison was missing, so no comparison happened, and a page that answered it
 * with "up to date" would manufacture exactly the reassurance the endpoint was
 * built to withhold. Silence is what this surface can honestly give it — the same
 * choice `core.js` already makes about the version stamp, which is omitted
 * entirely rather than shown empty when the build cannot be read, and `--status`
 * is where a no-basis answer has the room to be said in words.
 *
 * The test is `=== true` and not a truthy one. `stale` arrives as JSON, so a
 * truthy read would put the banner up for any non-empty string a future payload
 * carried, and the reader would be told to relaunch on the strength of a value
 * nobody here understood.
 *
 * The block wears `.findings warn`, the panel's existing notice, so this is not a
 * second warning component; `.buildstale` on the wrapper is placement and the
 * hook a browser gate reads. `role=status` names the block for what it is — an
 * inserted live region is announced inconsistently across engines, so nothing
 * here depends on its being read out.
 *
 * @param {{assembled: ?string, installed: ?string, stale: (boolean|null)}} state -
 *   the `GET /api/version` payload
 * @returns {HTMLElement|null} the banner to insert, or null to paint nothing
 */
function vbBanner(state) {
  if (!state || state.stale !== true) return null;
  return el('div', { class: 'buildstale', 'data-buildstale': '1' },
    el('div', { class: 'findings warn', role: 'status' },
      el('strong', {}, 'This panel is serving an older build.'),
      ' ' + vbWords(state)));
}

/**
 * Ask which build is installed, and put the banner above the shell if this page
 * is behind it.
 *
 * ABOVE `.shell` AND BELOW `.top`: the notice is about the whole panel rather
 * than about one tab, so it must not scroll away with a view or be redrawn by
 * one. Every tab renderer empties its own container; this sits outside all of
 * them and is written once.
 *
 * `insertBefore` rather than `before()`: the convenience method is absent from
 * the Baseline snapshot this repo checks against, and a feature the snapshot does
 * not carry is treated as Limited. `insertBefore` needs no gate.
 *
 * @returns {Promise<void>} resolves once the answer is in and the banner is up or
 *   deliberately absent; it rejects when `/api/version` cannot be reached, does
 *   not answer JSON, or the skeleton it inserts into is gone
 */
async function vbCheck() {
  const node = vbBanner(await api('GET', '/api/version'));
  if (!node) return;
  // Dereferenced straight away, by `core.js`'s rule for a name that comes out of
  // `panel.html`'s static skeleton: a null here would mean `.shell` was renamed,
  // which is a defect to hear about rather than a state to handle. The `.catch`
  // below turns it into a console line naming this feature; guarding it instead
  // would turn "the skeleton moved" into a banner that silently never appears,
  // which is indistinguishable from a build that is current.
  const shell = $('.shell');
  shell.parentNode.insertBefore(node, shell);
}

// Contained, by the rule `boot.js` states for `keepFocusClear`: this is a notice
// ABOUT the panel, and a notice that cannot be drawn must never be the reason the
// panel is not there. `.catch` is the containment for an async feature the way
// `runContained` is for a synchronous one — that helper collects what THREW, and
// nothing here throws synchronously.
//
// A failure is logged and the page stays silent, which is the same answer
// `stale:null` gets and for the same reason: a request that did not complete is a
// comparison that was not made. What must not go missing is the console line,
// because without it a banner that never came up and a build that is current read
// identically from the outside.
vbCheck().catch((cause) => console.error('the build check did not run', cause));
