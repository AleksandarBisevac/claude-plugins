  // --- heatmap calendar navigation -------------------------------------------
  // The server renders the all-data 7x24 grid; this re-renders the tbody from
  // the embedded per-day payload for one day / week / month / year at a time.
  // The rows each of those draws are shared/calendar.js's business — Month is
  // the month's own dates and Year its twelve months, which is what stops two
  // chips painting one picture.
  // prev/next are bounded strictly by the data, so an arrow at the edge is
  // disabled and muted rather than a dead click, and the period on display is
  // NAMED in the label. While a global date range is active the heatmap's whole
  // universe is that range: granularity navigation clamps to it, and "All" reads
  // "Custom range" with the span. One range, one meaning.
  //
  // Every date below is derived from the keys of window.AUDIT_USAGE.days, and
  // every Date is constructed from an explicit instant. The clock is never read:
  // a wall-clock call would make two renders of the same manifest differ, and
  // nothing could then compare a committed report against a fresh one.
  (() => {
    const body = document.getElementById('audit-hm-body');
    const granBar = document.getElementById('audit-hm-gran');
    const prevBtn = document.getElementById('audit-hm-prev');
    const nextBtn = document.getElementById('audit-hm-next');
    const periodEl = document.getElementById('audit-hm-period');
    const peakEl = document.getElementById('audit-hm-peak');
    if (!U || !body || !granBar || !prevBtn || !nextBtn || !periodEl) return;

    // The hour count, the weekday names and the month names are all in
    // shared/calendar.js now — this file spelled each of them and so did the
    // panel, for as long as there have been two heatmaps.

    /** @type {string} Granularity: 'all', 'day', 'week', 'month' or 'year'. */
    let gran = 'all';
    /** @type {string} Period start as an ISO day; '' while `gran` is 'all'. */
    let anchor = '';

    /**
     * The window the heatmap may show: the ledger's own span, narrowed by the
     * global date range whenever one is active.
     * @returns {{lo: string, hi: string}|null} null when the range and the
     *   recorded days do not overlap at all.
     */
    function bounds() {
      let lo = U.min;
      let hi = U.max;
      if (dFrom && dFrom > lo) lo = dFrom;
      if (dTo && dTo < hi) hi = dTo;
      return lo > hi ? null : { lo: lo, hi: hi };
    }

    /**
     * The calendar is in shared/calendar.js — the panel's heatmap spelled the
     * same five functions under the same names inside its own closure. Only the
     * DATA half stays here, and this is it plus the wrapper that hands it over.
     *
     * The four JSDoc blocks that used to sit above this one described those
     * five, and stayed behind when they left: docs for functions this file no
     * longer contains, which is a comment that cannot go stale because it was
     * never true again after the move.
     * @param {'day'|'week'|'month'|'year'} g Granularity.
     * @param {string} s ISO day the current period starts on.
     * @param {number} dir -1 for earlier, 1 for later.
     * @param {{lo: string, hi: string}} b Active bounds.
     * @returns {string|null} Start of the next populated period, or null.
     */
    function seek(g, s, dir, b) { return seekPeriod(g, s, dir, b, hasData); }

    /**
     * Whether any recorded day falls inside a closed ISO-day range.
     * @param {string} from First ISO day.
     * @param {string} to Last ISO day.
     * @returns {boolean}
     */
    function hasData(from, to) {
      // A plain loop, not `Object.keys(...).some(...)`: this runs inside seek()'s
      // bounded walk, which steps up to four thousand periods looking for the
      // next one that records anything. Materialising the whole key array on
      // every step turns a first-hit scan into a full allocation per step, and a
      // year-wide gap at day granularity is hundreds of steps.
      for (const day in U.days) {
        if (day >= from && day <= to) return true;
      }
      return false;
    }

    /**
     * The name of the period on display, so the grid never shows an unlabelled
     * slice of time.
     * @param {string} g Granularity.
     * @param {string} s ISO day the period starts on.
     * @param {{lo: string, hi: string}} b Active bounds, named when `g` is 'all'.
     * @returns {string} Human-readable period name.
     */
    function labelOf(g, s, b) {
      if (g === 'day') return WEEKDAY_NAMES[weekdayIndex(s)] + ' ' + s;
      if (g === 'week') return 'Week of ' + s + ' to ' + periodEnd('week', s);
      if (g === 'month') {
        return MONTH_NAMES[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4);
      }
      if (g === 'year') return s.slice(0, 4);
      return ((dFrom || dTo) ? 'Custom range' : 'All data')
        + ' · ' + b.lo + ' to ' + b.hi;
    }

    /**
     * The 24 hourly totals recorded for one ISO day.
     * @param {string} d ISO day.
     * @returns {number[]} Hourly totals, or [] for a day with nothing recorded.
     */
    function hoursOf(d) { return (U.days[d] || [0, 0, 0, []])[3] || []; }

    // The row SHAPES are in shared/calendar.js — dayRows, weekRows and
    // weekdayRows lived here, the panel spelled the same three inline, and both
    // sent month and year down the weekday branch. `heatRows` is the one place
    // that decides now; only the two data halves stay here, because the report
    // keys its days by date and the panel keeps a Map of the filtered facts.

    /**
     * The current view as DATA — rows, peak, period start, bounds and label —
     * split from the DOM paint so the PNG export can redraw exactly what is on
     * screen without reading it back out of the page. The anchor clamp lives
     * here because the view is what the clamp is for: render() paints whatever
     * this returns.
     * @returns {{rows: HeatRow[], peak: number, s: string,
     *   b: {lo: string, hi: string}, label: string}|null} null when the active
     *   range holds no recorded day at all.
     */
    function view() {
      const b = bounds();
      if (!b) return null;
      if (gran !== 'all') {
        if (!anchor) anchor = periodStart(gran, b.hi);
        const anchorEnd = periodEnd(gran, anchor);
        if (anchorEnd < b.lo || anchor > b.hi) anchor = periodStart(gran, b.hi);
      }
      const s = gran === 'all' ? b.lo : anchor;
      const en = gran === 'all' ? b.hi : periodEnd(gran, s);
      const lo = s < b.lo ? b.lo : s;
      const hi = en > b.hi ? b.hi : en;
      const rows = heatRows(gran, { s: s, en: en, lo: lo, hi: hi },
                            Object.keys(U.days), hoursOf);
      const peak = rows.reduce((outer, r) =>
        (r.cells || []).reduce((m, v) => (v > m ? v : m), outer), 0);
      return { rows: rows, peak: peak, s: s, b: b, label: labelOf(gran, s, b) };
    }

    // --- painting the grid -----------------------------------------------------

    /**
     * Intensity band for one cell.
     * @param {number} val Tokens recorded in that hour.
     * @param {number} peak Highest value anywhere in the current view.
     * @returns {number} 0 where nothing was recorded, 1-6 for the shaded bands.
     */
    function level(val, peak) {
      return (!val || !peak) ? 0 : Math.min(6, 1 + Math.floor(5 * val / peak));
    }

    /**
     * One cell's tooltip, in the same one-line shape the server's own titles
     * use. A date the active range excludes says so rather than claiming a zero
     * it cannot know.
     * @param {HeatRow} r Row the cell belongs to.
     * @param {number} h Hour of day, 0-23.
     * @param {number} val Tokens recorded in that hour.
     * @returns {string}
     */
    function tipFor(r, h, val) {
      if (!r.cells) return r.head + ' - outside the selected range';
      return r.head + ' ' + (h < 10 ? '0' : '') + h + ':00 - '
        + fmtTokens(val, 2) + ' tokens';
    }

    /**
     * Enable or disable one navigation arrow. A step that would leave the data
     * is disabled rather than dead, so the control says there is nothing there.
     * @param {HTMLButtonElement} btn The prev or next arrow.
     * @param {boolean} ok Whether a step that way lands on recorded data.
     * @returns {void}
     */
    function setArrow(btn, ok) {
      if (ok) btn.removeAttribute('disabled');
      else btn.setAttribute('disabled', '');
    }

    /**
     * Paint the current view into the tbody and update the label, the peak
     * readout and both arrows.
     * @returns {void}
     */
    function render() {
      const v = view();
      if (!v) {
        body.innerHTML = '';
        periodEl.textContent = 'No recorded usage in this range';
        if (peakEl) peakEl.textContent = '0';
        setArrow(prevBtn, false);
        setArrow(nextBtn, false);
        return;
      }
      const htmlRows = [];
      const tips = [];
      // Markup is assembled as text because the whole grid is rebuilt on every
      // navigation. That is safe here and only here: every byte written below is
      // a number this module computed or a label built from WD and an ISO day,
      // so nothing derived from the manifest can reach this string.
      for (const r of v.rows) {
        const cells = Array.from({ length: HEAT_HOURS },
          (unused, h) => (r.cells ? (r.cells[h] || 0) : 0));
        htmlRows.push('<tr><th>' + r.label + '</th>'
          + cells.map((val) => '<td><i data-l="' + level(val, v.peak)
            + '"></i></td>').join('')
          + '</tr>');
        cells.forEach((val, h) => tips.push(tipFor(r, h, val)));
      }
      body.innerHTML = htmlRows.join('');
      // The tooltip text rides on the element rather than in a title attribute:
      // the hover layer reads `__tip` to set `title` for the duration of a
      // hover, so the text has to survive the repaint on the mark itself.
      Array.from(body.querySelectorAll('i')).forEach((mark, i) => {
        mark.__tip = tips[i];
      });
      if (peakEl) peakEl.textContent = fmtTokens(v.peak, 1);
      periodEl.textContent = v.label;
      const canStep = gran !== 'all';
      setArrow(prevBtn, canStep && seek(gran, v.s, -1, v.b) !== null);
      setArrow(nextBtn, canStep && seek(gran, v.s, 1, v.b) !== null);
    }

    /**
     * Move the anchor one populated period in `dir` and repaint. A step that
     * would land outside the data does nothing at all.
     * @param {number} dir -1 for earlier, 1 for later.
     * @returns {void}
     */
    function step(dir) {
      const b = bounds();
      if (!b || gran === 'all') return;
      const next = seek(gran, anchor, dir, b);
      if (!next) return;
      anchor = next;
      render();
    }

    /**
     * Switch granularity and re-anchor on the latest period that holds data.
     * @param {string} val New granularity, from the chip's `data-g`.
     * @returns {void}
     */
    function setGranularity(val) {
      if (val === gran) return;
      gran = val;
      const b = bounds();
      anchor = (val === 'all' || !b) ? '' : periodStart(val, b.hi);
      highlight(granBar, 'data-g', gran);
      render();
    }

    prevBtn.addEventListener('click', () => step(-1));
    nextBtn.addEventListener('click', () => step(1));
    wireChips(granBar, 'data-g', setGranularity);
    highlight(granBar, 'data-g', gran);   // 'all' is lit from the start

    // Handed to the global range control, which calls render() when the window
    // moves and reads view() for the PNG export. The initial no-range state
    // deliberately leaves the server-rendered tbody untouched.
    hmApply = render;
    hmView = view;
  })();

  // --- run commands and the Markdown twin ------------------------------------

  /**
   * Select the run command beside a copy button so the reader can copy it with
   * their own key.
   * @param {HTMLButtonElement} btn The copy button.
   * @returns {void}
   */
  function selectRun(btn) {
    const code = btn.parentNode.querySelector('.vd-run');
    if (!code) return;
    const r = document.createRange();
    r.selectNodeContents(code);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
    btn.textContent = 'Press to copy';
    setTimeout(() => { btn.textContent = 'Copy'; }, 2400);
  }

  /**
   * Confirm a copy on the button itself, then put its label back.
   * @param {HTMLButtonElement} btn The copy button.
   * @returns {void}
   */
  function markCopied(btn) {
    btn.textContent = 'Copied';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1600);
  }

  /**
   * Copy a button's `data-copy` payload to the clipboard.
   *
   * clipboard.writeText is unavailable on file:// in some browsers, which is
   * exactly where this report is most often opened, so both the throw and the
   * rejection fall back to selecting the text. A button that silently does
   * nothing is worse than one that asks for a keystroke.
   * @param {HTMLButtonElement} btn The copy button.
   * @returns {void}
   */
  function copyRun(btn) {
    const text = btn.getAttribute('data-copy') || '';
    copyText(text, () => markCopied(btn), () => selectRun(btn));
  }

  Array.from(document.querySelectorAll('.btn-copy')).forEach((b) => {
    b.addEventListener('click', () => copyRun(b));
  });

  /**
   * Download the Markdown twin, which ships inside the page as base64.
   * @returns {void}
   */
  function downloadMarkdownTwin() {
    try {
      // atob yields a binary string in which one character is exactly one byte,
      // so a per-character charCodeAt is the whole decode.
      const bin = atob(window.AUDIT_MD_B64 || '');
      const bytes = Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
      // Through the shared helper, which revokes LATE. This site used to revoke
      // synchronously after click() - defended by a comment here, and argued
      // against by a comment in exports.js, in the same surface.
      download((window.AUDIT_MD_NAME || 'audit-report.md'),
               new Blob([bytes], { type: 'text/markdown;charset=utf-8' }));
    } catch (e) {}
  }

  const dlBtn = document.getElementById('audit-dl-md');
  if (dlBtn) dlBtn.addEventListener('click', downloadMarkdownTwin);

  // --- task detail rows and the view select ----------------------------------

  /**
   * Open or close one task's detail row. The compact row answers "where is
   * this"; the detail row answers "what happened and who do I ask" — the full
   * outcome above all, which the table can only show 70 characters of.
   * @param {HTMLButtonElement} btn The row's disclosure button.
   * @param {MouseEvent} ev Click on that button.
   * @returns {void}
   */
  function toggleTaskDetail(btn, ev) {
    ev.stopPropagation();          // the row itself is not a control
    const row = btn.closest('tr.task');
    if (!row || !row.__detail) return;
    row.__open = !row.__open;
    row.__detail.hidden = !row.__open;
    syncClamp(row.__detail);
    btn.setAttribute('aria-expanded', row.__open ? 'true' : 'false');
    btn.setAttribute('aria-label', (row.__open ? 'Hide' : 'Show')
      + ' details for ' + (btn.getAttribute('data-dfor') || 'this task'));
  }

  /**
   * Show the trim control only when there is something trimmed.
   *
   * MEASURED, not guessed. Whether five lines cuts a given `technical` off
   * depends on the width it is read at, so the server ships the button hidden
   * and this decides. Once the box is open the button must stay - it is the only
   * way back - which is why `open` short-circuits the overflow test instead of
   * being folded into it.
   *
   * @param {HTMLElement} detail a task's detail row, or null
   * @returns {void}
   */
  function syncClamp(detail) {
    if (!detail) return;
    Array.from(detail.querySelectorAll('[data-clamp]')).forEach((box) => {
      const btn = box.parentNode.querySelector('[data-clampmore]');
      if (!btn) return;
      const open = box.classList.contains('open');
      btn.hidden = !open && box.scrollHeight <= box.clientHeight + 2;
      btn.textContent = open ? 'Show less' : 'Show more';
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // One delegated listener rather than one per task: a plan with forty phases
  // carries hundreds of these, and the report already made this choice for its
  // heatmap marks.
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest && ev.target.closest('[data-clampmore]');
    if (!btn) return;
    const box = btn.parentNode.querySelector('[data-clamp]');
    if (!box) return;
    box.classList.toggle('open');
    syncClamp(btn.closest('tr'));
  });

  Array.from(document.querySelectorAll('.dtoggle')).forEach((b) => {
    b.addEventListener('click', (ev) => toggleTaskDetail(b, ev));
  });

  // The view select rides the shareable fragment and the local fallback along
  // with the filters: it IS part of the view someone would send as a link and
  // expect back after a reload.

  /**
   * Switch the phases table between active, archived and all.
   * @param {string} v View name; an unknown name is ignored.
   * @returns {void}
   */
  function setView(v) {
    // Own-property read: see `inView` in page-state.js. This caller is the
    // select rather than the link, but one guard on one table beats two.
    if (!lookup(VIEWS, v)) return;
    viewMode = v;
    if (viewSel && viewSel.value !== v) viewSel.value = v;
    refresh();                       // which syncs the chips, for every caller

  }

  /**
   * Offer only the status chips the current view can actually show.
   *
   * Reported: with View on "Archived (done & cancelled)" the bar still offered
   * Pending, and pressing it gave "0 / 9 phases" — a control whose every use is
   * empty by construction. The two gates are ANDed in the filter, so a chip
   * outside the view can never match anything; showing it is offering a choice
   * the page cannot honour.
   *
   * HIDDEN, not disabled, and the set is small enough that the bar simply says
   * what this view sorts by. A selection that the new view has just made
   * impossible is CLEARED rather than left pressed-but-inert — a pressed chip
   * filtering nothing is the same lie one step later.
   *
   * @returns {void}
   */
  function syncStatusChips() {
    if (!phaseStatusBar) return;
    let cleared = false;
    Array.from(phaseStatusBar.querySelectorAll('[data-ps]')).forEach((chip) => {
      const st = chip.getAttribute('data-ps');
      const ok = statusInView(st);
      chip.hidden = !ok;
      if (!ok && phaseStatus === st) { phaseStatus = ''; cleared = true; }
    });
    if (cleared) highlight(phaseStatusBar, 'data-ps', '');
  }

  if (viewSel) {
    viewSel.value = viewMode;
    viewSel.addEventListener('change', () => setView(viewSel.value));
  }

