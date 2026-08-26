  // --- wiring the controls the document already carries -----------------------

  /**
   * Attach toggle behaviour to chips that are already in the document.
   *
   * The chips are never created here. A filter bar that exists only once a script
   * has run is simply absent for a reader without scripts, and "the filters are
   * gone" and "the filters are broken" look identical from the outside.
   *
   * One delegated listener on the host serves every chip inside it, however many
   * the renderer emitted.
   *
   * This signature is a contract: four other features — the area chips, the author
   * chips, the range presets and the heatmap granularity — call it with their own
   * attribute and their own handler, so the shape `(host, dataAttr, onToggle)`
   * cannot change without changing them. `onToggle` is handed the host and the
   * attribute back so a caller can share one painter without building a closure.
   *
   * @param {HTMLElement|null} host - the element the chips sit in; a missing one
   *   is a no-op, since a report may render a bar with nothing to filter by
   * @param {string} dataAttr - the attribute carrying a chip's value, e.g. 'data-ps'
   * @param {(value: string, host: HTMLElement, dataAttr: string) => void} onToggle -
   *   called with the clicked chip's value; it owns the state change and the repaint
   * @returns {void}
   */
  function wireChips(host, dataAttr, onToggle) {
    if (!host) return;
    host.addEventListener('click', (e) => {
      const btn = e.target && e.target.closest ? e.target.closest('[' + dataAttr + ']') : null;
      const val = btn && btn.getAttribute(dataAttr);
      if (!val) return;
      onToggle(val, host, dataAttr);
    });
  }

  /**
   * Paint one chip of a bar as pressed and every other as released.
   *
   * A chip reports its state through aria-pressed, so the `on` class alone is not
   * the source of truth: the colour is for the eye and the attribute is what a
   * screen reader reads, and they have to be set together or they disagree.
   *
   * @param {HTMLElement} host - the element whose children are the chip buttons
   * @param {string} dataAttr - the attribute carrying a chip's value, e.g. 'data-ps'
   * @param {string} active - the value to press; '' presses none of them
   * @returns {void}
   */
  function highlight(host, dataAttr, active) {
    [...host.children].forEach((x) => {
      const on = x.getAttribute(dataAttr) === active;
      // classList, not a className rebuilt from its first word: that rebuild
      // silently dropped every class after the first, so any second utility class
      // a chip carries disappeared the moment the chip was toggled.
      x.classList.toggle('on', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  // phase expand/collapse (click or Enter/Space); state persists
  phaseRows.forEach((pr) => {
    /**
     * Flip this phase between expanded and collapsed, and remember the choice.
     * @returns {void}
     */
    function toggle() {
      const pid = pr.getAttribute('data-phase');
      expanded[pid] = !expanded[pid];
      persist();
      refresh();
    }
    pr.addEventListener('click', (e) => {
      // A phase row contains its own controls — the "held by" link that jumps to
      // the phase holding this one shut, and anything a later section adds. Those
      // have their own meaning; swallowing them into the row's toggle meant
      // following the link ALSO collapsed the row you were about to read.
      if (e.target && e.target.closest && e.target.closest('a,button,input,select,summary,label')) return;
      toggle();
    });
    pr.addEventListener('keydown', (e) => {
      if (e.target !== pr) return;   // Enter on a focused link inside the row is the link's
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
  if (expandBtn) expandBtn.addEventListener('click', () => {
    const anyClosed = phaseRows.some((pr) => !expanded[pr.getAttribute('data-phase')]);
    phaseRows.forEach((pr) => { expanded[pr.getAttribute('data-phase')] = anyClosed; });
    persist(); refresh();
  });

  // toolbar phase-status chips (distinct PHASE statuses, rendered server-side)
  wireChips(phaseStatusBar, 'data-ps', (val, host, attr) => {
    phaseStatus = (phaseStatus === val) ? '' : val;
    highlight(host, attr, phaseStatus);
    refresh();
  });

  // per-phase task-status chips (contextual — only that phase's task statuses).
  // Each phase keeps its own slot in taskStatus, so filtering one phase's tasks
  // leaves the others showing everything they have.
  const tfHosts = [];
  phaseRows.forEach((pr) => {
    const pid = pr.getAttribute('data-phase');
    const tfRow = tfOf(pid); if (!tfRow) return;
    const host = tfRow.querySelector('.tf-chips'); if (!host) return;
    tfHosts.push(host);
    wireChips(host, 'data-ts', (val) => {
      taskStatus[pid] = (taskStatus[pid] === val) ? '' : val;
      highlight(host, 'data-ts', taskStatus[pid]);
      refresh();
    });
  });

  // model chips (inside the More filters panel)
  wireChips(modelBar, 'data-m', (val, host, attr) => {
    modelFilter = (modelFilter === val) ? '' : val;
    highlight(host, attr, modelFilter);
    refresh();
  });

  // test-gate chips (inside the More filters panel) — what a task's last
  // recorded run SAID.
  wireChips(tevBar, 'data-tev', (val, host, attr) => {
    tevFilter = (tevFilter === val) ? '' : val;
    highlight(host, attr, tevFilter);
    refresh();
  });

  // ...and the observation chips beside them, on their OWN axis. A gate that
  // failed and also rewrote the tree is two facts; one control expressing only
  // their combination would need a name for every pairing, and would leave
  // "which gates rewrote the tree" unaskable.
  wireChips(tevFlagBar, 'data-tevf', (val, host, attr) => {
    tevFlag = (tevFlag === val) ? '' : val;
    highlight(host, attr, tevFlag);
    refresh();
  });

