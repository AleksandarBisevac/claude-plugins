  function paintAreas() {
    if (areaBar) {
      [].forEach.call(areaBar.children, function (x) {
        var on = areaFilter.indexOf(x.getAttribute('data-a')) !== -1;
        x.classList.toggle('on', on);
        x.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    // The global select shows the same selection. A select can only say one
    // thing, and the chips can hold several — so a multi-selection gets a
    // synthetic "N areas" option rather than the select naming one tag and
    // silently misdescribing the rest.
    if (areaSelect) {
      var multi = areaSelect.querySelector('option[data-multi]');
      if (areaFilter.length > 1) {
        if (!multi) {
          multi = document.createElement('option');
          multi.setAttribute('data-multi', '');
          multi.value = '~multi';
          areaSelect.appendChild(multi);
        }
        multi.textContent = areaFilter.length + ' areas';
        areaSelect.value = '~multi';
      } else {
        if (multi && multi.parentNode) multi.parentNode.removeChild(multi);
        areaSelect.value = areaFilter[0] || '';
      }
    }
  }
  // The global area select: one tag or all. Multi-select stays where it always
  // was (the chips in More filters); picking here replaces the selection.
  if (areaSelect) areaSelect.addEventListener('change', function () {
    if (areaSelect.value === '~multi') return;   // the synthetic summary option
    areaFilter = areaSelect.value ? [areaSelect.value] : [];
    paintAreas();
    refresh();
  });
  wireChips(areaBar, 'data-a', function (val) {
    var i = areaFilter.indexOf(val);
    if (i === -1) areaFilter.push(val); else areaFilter.splice(i, 1);
    paintAreas();
    refresh();
  });

  // Author chips (C3, inside the Usage section). They toggle `hidden` on the
  // section's per-author views and nothing else — the tiles and trend above
  // stay project-wide, and the task table has no author to filter by. The
  // default view is restored by re-applying hidden from the data-top marker
  // the renderer stamped on the top-8 cells, so a release is exact rather
  // than a re-render's guess.
