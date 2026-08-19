  // area chips (inside the More filters panel) — the phase-level gate.
  // highlight() paints exactly one active value; these chips hold a set, so
  // their painter reads membership instead.

  /**
   * Repaint both controls that show the area selection: the chips, which hold a
   * set, and the global select, which can only name one thing.
   * @returns {void}
   */
  function paintAreas() {
    if (areaBar) {
      [...areaBar.children].forEach((x) => {
        const on = areaFilter.indexOf(x.getAttribute('data-a')) !== -1;
        x.classList.toggle('on', on);
        x.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    // The global select shows the same selection. A select can only say one
    // thing, and the chips can hold several — so a multi-selection gets a
    // synthetic "N areas" option rather than the select naming one tag and
    // silently misdescribing the rest.
    if (areaSelect) {
      let multi = areaSelect.querySelector('option[data-multi]');
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
  if (areaSelect) areaSelect.addEventListener('change', () => {
    if (areaSelect.value === '~multi') return;   // the synthetic summary option
    areaFilter = areaSelect.value ? [areaSelect.value] : [];
    paintAreas();
    refresh();
  });
  wireChips(areaBar, 'data-a', (val) => {
    const i = areaFilter.indexOf(val);
    if (i === -1) areaFilter.push(val); else areaFilter.splice(i, 1);
    paintAreas();
    refresh();
  });

