  // --- heatmap calendar navigation -------------------------------------------
  // The server renders the all-data 7x24 grid; this re-renders the tbody from
  // the embedded per-day payload for one day / week / month / year at a time.
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

    const DAY = 86400000;
    const HOURS = 24;
    const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                 'August', 'September', 'October', 'November', 'December'];

    /**
     * One row of the grid.
     * @typedef {Object} HeatRow
     * @property {string} label Row label printed in the leftmost column.
     * @property {number[]|null} cells The 24 hourly token totals, or null for a
     *   date the active range excludes.
     * @property {string} head Row name used in every cell's tooltip.
     */

    /** @type {string} Granularity: 'all', 'day', 'week', 'month' or 'year'. */
    let gran = 'all';
    /** @type {string} Period start as an ISO day; '' while `gran` is 'all'. */
    let anchor = '';

    /**
     * Parse an ISO day as midnight UTC.
     * @param {string} d ISO day, `YYYY-MM-DD`.
     * @returns {number} Milliseconds since the epoch.
     */
    function dParse(d) { return Date.parse(d + 'T00:00:00Z'); }

    /**
     * Format an explicit instant back as an ISO day in UTC.
     * @param {number} ms Milliseconds since the epoch.
     * @returns {string} `YYYY-MM-DD`.
     */
    function dIso(ms) { return new Date(ms).toISOString().slice(0, 10); }

    /**
     * Weekday index of an ISO day, Monday first, to match the grid's rows.
     * @param {string} d ISO day.
     * @returns {number} 0 for Monday through 6 for Sunday.
     */
    function wdayOf(d) { return (new Date(dParse(d)).getUTCDay() + 6) % 7; }

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
     * First ISO day of the period `day` falls in.
     * @param {string} g Granularity.
     * @param {string} day ISO day.
     * @returns {string} ISO day the period starts on.
     */
    function startOf(g, day) {
      if (g === 'week') return dIso(dParse(day) - wdayOf(day) * DAY);
      if (g === 'month') return day.slice(0, 7) + '-01';
      if (g === 'year') return day.slice(0, 4) + '-01-01';
      return day;
    }

    /**
     * Last ISO day of the period starting at `s`.
     * @param {string} g Granularity.
     * @param {string} s ISO day the period starts on.
     * @returns {string} ISO day the period ends on.
     */
    function endOf(g, s) {
      if (g === 'week') return dIso(dParse(s) + 6 * DAY);
      if (g === 'month') {
        // Day zero of the FOLLOWING month is the last day of this one, which is
        // the only spelling that gets February right without a leap-year rule.
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7), 0));
      }
      if (g === 'year') return s.slice(0, 4) + '-12-31';
      return s;
    }

    /**
     * The period one step away, whether or not it holds any data.
     * @param {string} g Granularity.
     * @param {string} s ISO day the current period starts on.
     * @param {number} dir -1 for earlier, 1 for later.
     * @returns {string} ISO day the neighbouring period starts on.
     */
    function shift(g, s, dir) {
      if (g === 'day') return dIso(dParse(s) + dir * DAY);
      if (g === 'week') return dIso(dParse(s) + dir * 7 * DAY);
      if (g === 'month') {
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1 + dir, 1));
      }
      if (g === 'year') return (+s.slice(0, 4) + dir) + '-01-01';
      return s;
    }

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
     * The next period in `dir` that lies inside the bounds AND records
     * something. "Never navigate into an empty period" is a rule about data
     * rather than about the calendar, so gap days between two worked weeks are
     * stepped over instead of shown.
     * @param {string} g Granularity.
     * @param {string} s ISO day the current period starts on.
     * @param {number} dir -1 for earlier, 1 for later.
     * @param {{lo: string, hi: string}} b Active bounds.
     * @returns {string|null} Start of the next populated period, or null when
     *   the walk leaves the bounds first.
     */
    function seek(g, s, dir, b) {
      let cur = s;
      // Bounded rather than `while (true)`: leaving the bounds is what normally
      // stops this walk, and a granularity whose shift failed to advance would
      // otherwise spin forever with the tab frozen.
      for (let i = 0; i < 4000; i++) {
        cur = shift(g, cur, dir);
        const en = endOf(g, cur);
        if (en < b.lo || cur > b.hi) return null;
        const lo = cur < b.lo ? b.lo : cur;
        const hi = en > b.hi ? b.hi : en;
        if (hasData(lo, hi)) return cur;
      }
      return null;
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
      if (g === 'day') return WD[wdayOf(s)] + ' ' + s;
      if (g === 'week') return 'Week of ' + s + ' to ' + endOf('week', s);
      if (g === 'month') return MON[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4);
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

    /**
     * Rows for a single day: one row carrying that day's 24 hours.
     * @param {string} day ISO day inside the active range.
     * @returns {HeatRow[]}
     */
    function dayRows(day) {
      return [{ label: WD[wdayOf(day)] + ' ' + day.slice(5),
                cells: hoursOf(day).slice(),
                head: WD[wdayOf(day)] + ' ' + day }];
    }

    /**
     * Rows for one week: one row per calendar date, so the week keeps its shape
     * even where the active range clips it.
     * @param {string} s ISO day the week starts on.
     * @param {string} en ISO day the week ends on.
     * @param {string} lo First ISO day inside the active range.
     * @param {string} hi Last ISO day inside the active range.
     * @returns {HeatRow[]}
     */
    function weekRows(s, en, lo, hi) {
      const rows = [];
      for (let ms = dParse(s); ms <= dParse(en); ms += DAY) {
        const d = dIso(ms);
        const inRange = d >= lo && d <= hi;
        rows.push({ label: WD[wdayOf(d)] + ' ' + d.slice(5),
                    cells: inRange ? hoursOf(d).slice() : null,
                    head: WD[wdayOf(d)] + ' ' + d });
      }
      return rows;
    }

    /**
     * Rows for a month, a year or the whole range: seven weekday rows, each the
     * hour-by-hour sum over every matching date, the way the server's all-data
     * view aggregates.
     * @param {string} lo First ISO day to include.
     * @param {string} hi Last ISO day to include.
     * @returns {HeatRow[]}
     */
    function weekdayRows(lo, hi) {
      const agg = Array.from({ length: 7 }, () => []);
      for (const d of Object.keys(U.days)) {
        if (d < lo || d > hi) continue;
        const vec = hoursOf(d);
        const tgt = agg[wdayOf(d)];
        for (let h = 0; h < HOURS; h++) tgt[h] = (tgt[h] || 0) + (vec[h] || 0);
      }
      return agg.map((cells, wd) => ({ label: WD[wd], cells: cells, head: WD[wd] }));
    }

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
        if (!anchor) anchor = startOf(gran, b.hi);
        const anchorEnd = endOf(gran, anchor);
        if (anchorEnd < b.lo || anchor > b.hi) anchor = startOf(gran, b.hi);
      }
      const s = gran === 'all' ? b.lo : anchor;
      const en = gran === 'all' ? b.hi : endOf(gran, s);
      const lo = s < b.lo ? b.lo : s;
      const hi = en > b.hi ? b.hi : en;
      const rows = gran === 'day' ? dayRows(lo)
        : gran === 'week' ? weekRows(s, en, lo, hi)
        : weekdayRows(lo, hi);
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
        const cells = Array.from({ length: HOURS },
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
      anchor = (val === 'all' || !b) ? '' : startOf(val, b.hi);
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
    try {
      navigator.clipboard.writeText(text)
        .then(() => markCopied(btn), () => selectRun(btn));
    } catch (e) { selectRun(btn); }
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
    btn.setAttribute('aria-expanded', row.__open ? 'true' : 'false');
    btn.setAttribute('aria-label', (row.__open ? 'Hide' : 'Show')
      + ' details for ' + (btn.getAttribute('data-dfor') || 'this task'));
  }

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
    if (!VIEWS[v]) return;
    viewMode = v;
    if (viewSel && viewSel.value !== v) viewSel.value = v;
    refresh();
  }

  if (viewSel) {
    viewSel.value = viewMode;
    viewSel.addEventListener('change', () => setView(viewSel.value));
  }
  Array.from(document.querySelectorAll('[data-viewall]')).forEach((b) => {
    b.addEventListener('click', () => setView('all'));
  });
