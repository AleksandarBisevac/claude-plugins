  function applyAuthor() {
    if (auSelect) auSelect.value = auFilter;   // the global twin says the same
    smCells.forEach(function (c) {
      c.hidden = auFilter ? c.getAttribute('data-author') !== auFilter
                          : !c.hasAttribute('data-top');
    });
    auRows.forEach(function (r) {
      r.hidden = !!auFilter && r.getAttribute('data-author') !== auFilter;
    });
    if (auNote) {
      var chip = null;
      if (authorBar && auFilter) {
        [].forEach.call(authorBar.children, function (x) {
          if (x.getAttribute && x.getAttribute('data-au') === auFilter) chip = x;
        });
      }
      if (chip) {
        // Assembled from the chip's own data attributes — the renderer already
        // did this arithmetic once, and a second implementation here is how a
        // summary ends up disagreeing with the chips it summarises.
        var cost = chip.getAttribute('data-cost');
        var sep = ' \u00b7 ';   // a middot, as an escape so the source stays ASCII
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
  wireChips(authorBar, 'data-au', function (val, host, attr) {
    auFilter = (auFilter === val) ? '' : val;
    highlight(host, attr, auFilter);
    applyAuthor();
  });
  // The authors dropdown (C2) drives the same state the chips do; both paint.
  if (auSelect) auSelect.addEventListener('change', function () {
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
