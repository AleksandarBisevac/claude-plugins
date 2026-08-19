  /**
   * The More-filters popover, if one is open.
   *
   * @returns {?HTMLDetailsElement} The open panel, or null when none is open.
   */
  function openPanel() { return document.querySelector('details.fdetails[open]'); }
  // A <details> closes only through its own summary, and this one is absolutely
  // positioned — left open it covers rows it has nothing to do with. So it
  // answers to the two things every popover answers to: an outside click, and
  // Escape.
  document.addEventListener('click', (ev) => {
    const d = openPanel();
    if (d && !d.contains(ev.target)) d.open = false;
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    // Escape in the search box already means "clear the search"; leave it alone
    // rather than have one key do two things at once.
    if (q && ev.target === q) return;
    const d = openPanel();
    if (!d) return;
    d.open = false;
    const sum = d.querySelector('summary');
    if (sum) sum.focus();          // put focus back on the control that opened it
  });

  /**
   * Repaint every control that shows the current date window.
   *
   * Both date pairs — the two inputs inside the filter panel and the two in the
   * global bar — mirror one piece of state, so editing either repaints both:
   * two controls, one range, never two answers.
   *
   * @returns {void}
   */
  function paintDates() {
    if (fromInput) fromInput.value = dFrom;
    if (toInput) toInput.value = dTo;
    if (gFrom) gFrom.value = dFrom;
    if (gTo) gTo.value = dTo;
    if (gClear) gClear.hidden = !(dFrom || dTo);
    if (presetBar) highlight(presetBar, 'data-days', preset);
  }

  /**
   * Set the date window and re-filter, from whichever control asked.
   *
   * One entry point for every control that sets the range: the panel inputs,
   * the global inputs, and the all-time reset. A hand-picked range is no longer
   * a preset, so the chip row unlights.
   *
   * Both bounds stay plain `YYYY-MM-DD` strings for their whole life. Every
   * comparison against them is a string comparison, which is timezone-free and
   * needs no parsing; turning either into a Date would reintroduce the local
   * offset the ISO form exists to avoid.
   *
   * @param {string} f Inclusive lower bound as `YYYY-MM-DD`, or '' for no bound.
   * @param {string} t Inclusive upper bound as `YYYY-MM-DD`, or '' for no bound.
   * @returns {void}
   */
  function setRange(f, t) {
    dFrom = f || '';
    dTo = t || '';
    preset = '';
    paintDates();
    refresh();
  }

  /**
   * Adopt the range the filter panel's two inputs currently show.
   *
   * @returns {void}
   */
  function onDateInput() {
    setRange(fromInput ? fromInput.value : '', toInput ? toInput.value : '');
  }
  if (fromInput) fromInput.addEventListener('change', onDateInput);
  if (toInput) toInput.addEventListener('change', onDateInput);

  /**
   * Adopt the range the global filter bar's two inputs currently show.
   *
   * @returns {void}
   */
  function onGDateInput() {
    setRange(gFrom ? gFrom.value : '', gTo ? gTo.value : '');
  }
  if (gFrom) gFrom.addEventListener('change', onGDateInput);
  if (gTo) gTo.addEventListener('change', onGDateInput);
  // Clearing returns to all time: one press, both pairs blank, every scoped
  // view back to the whole record.
  if (gClear) gClear.addEventListener('click', () => { setRange('', ''); });

  /**
   * Apply a relative span, measured back from the plan's last recorded day.
   *
   * The anchor is DMAX — the newest date in the data — and never the wall
   * clock. A span measured against today answers a different question every
   * morning, which would stop a committed report from staying byte-equal to a
   * fresh render of the same plan. With no DMAX there is nothing to measure
   * from, so the span is dropped rather than guessed at and the chip unlights.
   *
   * @param {string} days Either 'all', or a day count as a decimal string, read
   *   off the chip's `data-days` attribute.
   * @returns {void}
   */
  function applyPreset(days) {
    preset = days;
    const ms = DMAX ? Date.parse(DMAX + 'T00:00:00Z') : NaN;
    if (days === 'all' || isNaN(ms)) {
      dFrom = ''; dTo = '';
      if (days !== 'all') preset = '';   // nothing to measure from; claim nothing
    } else {
      // Inclusive of the last day, so "7 days" spans seven of them and not eight.
      // The arithmetic is UTC-anchored and lands back on a `YYYY-MM-DD` string,
      // so the value handed to setRange is the same shape every other bound has.
      dFrom = new Date(ms - (Number(days) - 1) * 86400000).toISOString().slice(0, 10);
      dTo = DMAX;
    }
    paintDates();
    refresh();
  }
  wireChips(presetBar, 'data-days', (val) => {
    applyPreset(preset === val ? 'all' : val);
  });

  /**
   * Lift every filter at once: search, statuses, model, dates, areas, author.
   *
   * The button that calls this lives in the empty state because that is the one
   * view from which no other control is reachable — every chip that could clear
   * itself has been filtered off the screen along with the rows.
   *
   * @returns {void}
   */
  function clearAll() {
    if (q) q.value = '';
    phaseStatus = ''; modelFilter = ''; dFrom = ''; dTo = ''; preset = '';
    taskStatus = {};
    auFilter = '';
    areaFilter = [];
    if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', '');
    if (modelBar) highlight(modelBar, 'data-m', '');
    paintAreas();
    if (authorBar) highlight(authorBar, 'data-au', '');
    // Clearing the state without unlighting these would leave rows claiming a
    // filter that no longer applies to them.
    tfHosts.forEach((h) => { highlight(h, 'data-ts', ''); });
    applyAuthor();
    paintDates();
    refresh();
  }
  clearBtns.forEach((b) => { b.addEventListener('click', clearAll); });

  // Save as PDF — the print stylesheet lays the whole plan out with every phase
  // expanded and leaves the sheet itself to the dialog, which is also where
  // "Save as PDF" lives (no bundled PDF library, so the file stays small and
  // self-contained).
  const printBtn = document.getElementById('audit-print');
  if (printBtn) printBtn.addEventListener('click', () => { window.print(); });

  // A CLOSED <details> still collapses in print media even when its children are
  // forced visible by CSS — the element clips them, so the print stylesheet alone
  // silently drops the Usage detail from the PDF. Open them for the duration of
  // the print and restore afterwards, so what you see is what you get.
  let reopen = [];
  window.addEventListener('beforeprint', () => {
    reopen = [];
    Array.prototype.forEach.call(document.querySelectorAll('details'), (d) => {
      if (!d.open) { reopen.push(d); d.open = true; }
    });
  });
  window.addEventListener('afterprint', () => {
    reopen.forEach((d) => { d.open = false; });
    reopen = [];
  });

  // Hover layer for the Usage charts. It renders NOTHING of its own: every value
  // it shows already sits in a `title` attribute (or an SVG <title> child) on the
  // mark, so with JS disabled the browser shows the same text natively and the
  // report still explains itself from a file:// URL. Titles are stashed and
  // removed while JS is live only so the native tooltip does not fight this one.
  (() => {
    // Scoped to the Usage section — the siblings between its <h2> and the next
    // one. Everything else in the report keeps its plain native tooltips.
    const start = document.getElementById('usage');
    if (!start) return;
    let found = 0;
    /**
     * Remember a mark's tooltip text on the mark itself.
     *
     * @param {?Element} node The mark the pointer or focus will land on.
     * @param {string} text The text to show; an empty one claims nothing.
     * @returns {void}
     */
    function claim(node, text) {
      if (!node || !text) return;
      node.__tip = text; found++;
    }
    for (let s = start.nextElementSibling; s && s.tagName !== 'H2';
         s = s.nextElementSibling) {
      // The attribute STAYS. `title` is what the accessibility tree uses as an
      // element's description, so stripping it permanently takes the text away
      // from a screen reader entirely — and this layer only ever gives it back
      // to a pointer or to focus. It is suppressed per element only while that
      // element is the current one, which is the whole reason it was ever
      // removed, so the two tooltips still never fight and everyone else keeps
      // the description.
      if (s.hasAttribute('title')) claim(s, s.getAttribute('title'));
      Array.prototype.forEach.call(s.querySelectorAll('[title]'), (n) => {
        claim(n, n.getAttribute('title'));
      });
      // SVG <title> children — same text, different carrier.
      Array.prototype.forEach.call(s.querySelectorAll('title'), (t) => {
        claim(t.parentNode, t.textContent);
        if (t.parentNode) t.parentNode.removeChild(t);
      });
    }
    if (!found) return;

    const box = document.createElement('div');
    box.className = 'rtip'; box.hidden = true;
    document.body.appendChild(box);

    /**
     * Rebuild the box's contents from one mark's stashed text.
     *
     * The first line is the heading; every line after it is a tab-separated
     * key/value pair. Built as element nodes rather than markup, because the
     * text comes from the manifest and must never be parsed as HTML.
     *
     * @param {string} text Newline-separated lines, tabs splitting key from value.
     * @returns {void}
     */
    function fill(text) {
      box.textContent = '';
      text.split('\n').forEach((line, i) => {
        if (i === 0) {
          const b = document.createElement('b'); b.textContent = line;
          box.appendChild(b); return;
        }
        const parts = line.split('\t');
        const row = document.createElement('span');
        const k = document.createElement('em'); k.textContent = parts[0];
        const v = document.createElement('i'); v.textContent = parts[1] || '';
        row.appendChild(k); row.appendChild(v); box.appendChild(row);
      });
    }

    /**
     * Place the box beside the pointer, flipping it inside the viewport.
     *
     * @param {MouseEvent} ev The pointer event carrying the coordinates.
     * @returns {void}
     */
    function place(ev) {
      const boxRect = box.getBoundingClientRect();
      let x = ev.clientX + 14, y = ev.clientY + 16;
      if (x + boxRect.width > window.innerWidth - 8) x = ev.clientX - boxRect.width - 14;
      if (y + boxRect.height > window.innerHeight - 8) y = ev.clientY - boxRect.height - 16;
      box.style.left = Math.max(8, x) + 'px';
      box.style.top = Math.max(8, y) + 'px';
    }

    /**
     * Place the box under a mark's own rect, flipping above it when there is no
     * room below, so it never covers the row it is describing.
     *
     * The focus half of the same box needs this because `place` reads
     * `ev.clientX`/`ev.clientY`, which a focus event does not carry — a keyboard
     * reader would otherwise get the tooltip pinned at 0,0 or wherever the mouse
     * was last left. (`markRect` rather than `q`: `q` is the search input at the
     * top of this one shared scope.)
     *
     * @param {Element} node The mark that just took focus.
     * @returns {void}
     */
    function placeAt(node) {
      const markRect = node.getBoundingClientRect();
      const boxRect = box.getBoundingClientRect();
      let x = markRect.left, y = markRect.bottom + 6;
      if (x + boxRect.width > window.innerWidth - 8) x = window.innerWidth - boxRect.width - 8;
      if (y + boxRect.height > window.innerHeight - 8) y = markRect.top - boxRect.height - 6;
      box.style.left = Math.max(8, x) + 'px';
      box.style.top = Math.max(8, y) + 'px';
    }

    /**
     * Close the box and give the current mark its native title back.
     *
     * Every close goes through here — Escape, focusout, and printing — so there
     * is one place that can forget to restore rather than three.
     *
     * @returns {void}
     */
    function hide() {
      restoreNative(current);
      box.hidden = true; current = null;
    }

    /**
     * The nearest ancestor-or-self carrying stashed tooltip text.
     *
     * Delegated lookup: three listeners instead of one per mark. A dense report
     * carries well over a thousand hoverable marks, and binding each of them is
     * a cost paid on every page load to serve one hover at a time.
     *
     * @param {?Node} node The event target to walk up from.
     * @returns {?Element} The owning mark, or null when the target owns none.
     */
    function owner(node) {
      for (let n = node; n && n !== document; n = n.parentNode) {
        if (n.__tip) return n;
      }
      return null;
    }

    /**
     * Suppress the native tooltip on one mark while this layer describes it.
     *
     * @param {?Element} node The mark now under the pointer or holding focus.
     * @returns {void}
     */
    function muteNative(node) {
      if (node && node.hasAttribute && node.hasAttribute('title')) {
        node.removeAttribute('title');
      }
    }

    /**
     * Give a mark its native tooltip back, from the text stashed on it.
     *
     * Restoring is not optional bookkeeping: skip it on any path and the first
     * hover strips the description from the accessibility tree permanently.
     *
     * @param {?Element} node The mark this layer is done describing.
     * @returns {void}
     */
    function restoreNative(node) {
      if (node && node.__tip && node.setAttribute && !node.hasAttribute('title')) {
        node.setAttribute('title', node.__tip);
      }
    }

    // The mark this layer is currently describing, or null.
    let current = null;
    document.addEventListener('mouseover', (ev) => {
      const m = owner(ev.target);
      if (m === current) return;
      restoreNative(current);
      current = m;
      if (!m) { box.hidden = true; return; }
      muteNative(m);
      fill(m.__tip); box.hidden = false; place(ev);
    });
    document.addEventListener('mousemove', (ev) => {
      if (current) place(ev);
    });
    // The keyboard half. Restoring `title` puts the description back in the
    // accessibility tree, which serves a screen-reader user and a JS-off reader.
    // It does nothing for a SIGHTED KEYBOARD reader: no browser surfaces a
    // native `title` on focus, and the two listeners above are pointer-only. So
    // the same box gets a second trigger rather than a second implementation —
    // one `fill`, one `hide`, one element on the page.
    document.addEventListener('focusin', (ev) => {
      const m = owner(ev.target);
      if (m === current) return;
      restoreNative(current);
      current = m;
      if (!m) { box.hidden = true; return; }
      muteNative(m);
      fill(m.__tip); box.hidden = false; placeAt(m);
    });
    document.addEventListener('focusout', (ev) => {
      if (current && owner(ev.target) === current) hide();
    });
    // Dismissible (WCAG SC 1.4.13). Escape closes the box WITHOUT moving the
    // caret — a reader who dismissed a tooltip has not asked to leave the row,
    // and sending focus elsewhere would make Escape cost them their place. The
    // mark keeps focus, so tabbing on still works from where they were.
    document.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Escape') return;
      if (!current) return;
      hide();
    });
    // Printing a floating tooltip would stamp it onto the page. Whatever was
    // hovered gets its `title` back here too: printing is the one path that
    // would otherwise clear the current mark without a mouseover to restore it.
    window.addEventListener('beforeprint', hide);
  })();
