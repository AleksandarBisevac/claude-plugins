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
  /**
   * The pristine area options, in the order the renderer wrote them.
   *
   * `syncAreaOptions()` rebuilds the select rather than setting `hidden` on an
   * option, because `hidden` on `<option>` is honoured inconsistently - the
   * chips next to it are buttons and can simply be hidden, but a select needs
   * its list rebuilt to actually drop a choice. Captured once, before any view
   * has had a chance to remove anything.
   *
   * @type {Array<{value: string, text: string}>}
   */
  const AREA_OPTS = areaSelect
    ? [...areaSelect.options].filter((o) => !o.hasAttribute('data-multi'))
      .map((o) => ({ value: o.value, text: o.textContent }))
    : [];
  let areaSyncedFor = null;

  /**
   * Offer only the areas the current view can actually show.
   *
   * The same fault as the status chips, one control over: area and view are
   * ANDed in the filter, so with View on "Active" an area whose only phase is
   * archived can never match - it was still listed, and picking it gave
   * "0 / 4 phases". Found by sweeping every control rather than by a second
   * report, which is why it is fixed in the same breath as its sibling.
   *
   * Guarded on the view because an area can only become impossible when the
   * view changes; `refresh()` also runs on every keystroke, and rebuilding a
   * select under the reader's cursor is its own bug.
   *
   * @returns {void}
   */
  function syncAreaOptions() {
    if (areaSyncedFor === viewMode) return;
    areaSyncedFor = viewMode;
    const kept = areaFilter.filter((a) => areaInView(a));
    const cleared = kept.length !== areaFilter.length;
    areaFilter = kept;
    if (areaBar) {
      [...areaBar.children].forEach((x) => {
        x.hidden = !areaInView(x.getAttribute('data-a'));
      });
    }
    if (areaSelect) {
      const multi = areaSelect.querySelector('option[data-multi]');
      while (areaSelect.firstChild) areaSelect.removeChild(areaSelect.firstChild);
      AREA_OPTS.forEach((o) => {
        if (o.value && !areaInView(o.value)) return;
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.text;
        areaSelect.appendChild(opt);
      });
      if (multi) areaSelect.appendChild(multi);
    }
    paintAreas();
    if (cleared) refresh();
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

