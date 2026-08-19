  // Author chips, inside the Usage section. They toggle `hidden` on the section's
  // per-author views and nothing else — the tiles and trend above stay
  // project-wide, and the task table has no author to filter by. The default view
  // is restored by re-applying hidden from the data-top marker the renderer
  // stamped on the top cells, so a release is exact rather than a re-render's
  // guess.

  /**
   * Narrow the Usage section to the selected author, or restore the default view
   * when no author is selected, and say in the note what the selection covers.
   * @returns {void}
   */
  function applyAuthor() {
    if (auSelect) auSelect.value = auFilter;   // the global twin says the same
    smCells.forEach((c) => {
      c.hidden = auFilter ? c.getAttribute('data-author') !== auFilter
                          : !c.hasAttribute('data-top');
    });
    auRows.forEach((r) => {
      r.hidden = !!auFilter && r.getAttribute('data-author') !== auFilter;
    });
    if (auNote) {
      /** @type {HTMLButtonElement|undefined} */
      const chip = authorBar && auFilter
        ? [...authorBar.children].find((x) => x.getAttribute('data-au') === auFilter)
        : undefined;
      if (chip) {
        // Assembled from the chip's own data attributes — the renderer already
        // did this arithmetic once, and a second implementation here is how a
        // summary ends up disagreeing with the chips it summarises.
        const cost = chip.getAttribute('data-cost');
        const sep = ' \u00b7 ';   // a middot, as an escape so the source stays ASCII
        auNote.textContent = auFilter + ': ' + chip.getAttribute('data-tokens')
          + ' tokens' + (cost ? sep + cost : '')
          + sep + chip.getAttribute('data-msgs') + ' msgs'
          + sep + chip.getAttribute('data-share') + ' of all spend';
        auNote.hidden = false;
      } else {
        auNote.hidden = true;
        auNote.textContent = '';
      }
    }
    syncHash();
  }
  wireChips(authorBar, 'data-au', (val, host, attr) => {
    auFilter = (auFilter === val) ? '' : val;
    highlight(host, attr, auFilter);
    applyAuthor();
  });
  // The authors dropdown drives the same state the chips do, and both are
  // painted from it, so touching either one leaves the other agreeing.
  if (auSelect) auSelect.addEventListener('change', () => {
    auFilter = auSelect.value;
    if (authorBar) highlight(authorBar, 'data-au', auFilter);
    applyAuthor();
  });

  // The More-filters panel closes on an outside click and on Escape. A <details>
  // natively closes only through its own summary, so a reader who opens it,
  // picks a filter and moves on leaves it hanging over the table — and it is
  // absolutely positioned, so it covers rows that have nothing to do with it.
  //
  // Clicking the summary to OPEN is not caught by this: the toggle is the click's
  // default action and runs after the event has finished bubbling, so at this
  // point the element is still closed and the query below finds nothing. Clicking
  // the summary to CLOSE is inside `contains`, so it is left to the native
  // behaviour rather than being closed twice. Clicks inside the panel — a chip, a
  // date field — are `contains` too, so changing a filter never dismisses the
  // thing you are changing it in.
