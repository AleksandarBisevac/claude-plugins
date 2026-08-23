  // --- exports: CSV of the tables --------------------------------------------
  // Every export reads the DATA behind a table, never the filtered view on
  // screen: a file named "phases-active" that held whatever the search box
  // happened to leave visible would be a different file on every download.
  // Every button is server-rendered, so this only attaches behaviour.

  /** @type {string} Download basename: the Markdown twin's name without `.md`. */
  const BASE = String(window.AUDIT_MD_NAME || 'audit-report.md').replace(/\.md$/, '');

  /**
   * Quote one CSV field per RFC 4180.
   * @param {string|number|null|undefined} v Raw field value.
   * @returns {string} `v` wrapped in quotes with inner quotes doubled when it
   *   carries a comma, a quote or a newline; otherwise `v` as a plain string.
   */
  function csvQuote(v) {
    const s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  /**
   * Serialise rows to CSV text and download them.
   * @param {string} name Filename offered to the reader.
   * @param {(string|number|null)[][]} rows Header row first, then data rows.
   * @returns {void}
   */
  function csvDownload(name, rows) {
    const text = rows.map((r) => r.map(csvQuote).join(',')).join('\r\n') + '\r\n';
    // U+FEFF: without the BOM Excel reads a UTF-8 CSV in the local 8-bit
    // codepage. Written as an escape and never as the character itself, because
    // an invisible literal in the source is unreviewable.
    download(name, new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' }));
  }

  /**
   * Machine names of the task table's optional columns, read once off the
   * table's own header so the export cannot disagree with what was rendered.
   *
   * The name comes from `data-col` rather than the header's words: the done
   * header carries a UTC note beside the word, and a CSV keyed on rendered text
   * stops recognising a column the moment that header gains a second word. The
   * leading three columns are the fixed id/title/status trio, written by hand
   * into every row, so they are dropped here.
   * @type {string[]}
   */
  const COLNAMES = grouped
    ? Array.from(grouped.querySelectorAll('thead th'))
        .map((h) => h.getAttribute('data-col') || h.textContent.trim())
        .slice(3)
    : [];

  /**
   * Read one labelled value out of a task's expandable detail row.
   * @param {HTMLTableRowElement} t Task row; its detail row hangs off `__detail`.
   * @param {string} key Label text to match, e.g. 'completed'.
   * @returns {string} The value beside that label, or '' when there is none.
   */
  function detailValue(t, key) {
    const detail = t.__detail;
    if (!detail) return '';
    const label = Array.from(detail.querySelectorAll('.dt-k'))
      .find((k) => k.textContent.trim() === key);
    const value = label && label.nextElementSibling;
    return value ? value.textContent.trim() : '';
  }

  /**
   * Blank the em dash a table prints where there is nothing — a data file says
   * nothing by saying nothing, and an em dash in a spreadsheet is a value.
   * @param {string} v Rendered cell text.
   * @returns {string} '' for an em dash or a bare hyphen, otherwise `v`.
   */
  function csvPlain(v) { return (v === '\u2014' || v === '-') ? '' : v; }

  /**
   * One task's value for an optional column, at full precision.
   *
   * Three columns are lossy on screen and must not be exported lossy: the commit
   * cell shows nine characters plus the copy control's own text, the done cell
   * is cut to the minute, and the outcome cell is cut at 70 characters. A
   * spreadsheet is where someone re-derives a figure, so each of those is read
   * from the detail row the reader can open for themselves.
   * @param {HTMLTableRowElement} t Task row.
   * @param {string} name Machine column name, one of COLNAMES.
   * @param {number} ci Index of that column within COLNAMES.
   * @returns {string} The value to export for this cell.
   */
  function csvCell(t, name, ci) {
    if (name === 'commit') {
      const copyBtn = t.querySelector('.shacopy');
      // `getAttribute` is string-or-null; the declared return type is string, so
      // the coalesce is what makes that true rather than nearly true.
      return (copyBtn && copyBtn.getAttribute('data-copy')) || '';
    }
    if (name === 'done') {
      // The data attribute is cut to the date on purpose — the range filter
      // compares those as plain strings — and the cell is cut to the minute.
      // The detail row carries the whole stamp, seconds included.
      return detailValue(t, 'completed') || detailValue(t, 'started')
        || t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
    }
    if (name === 'outcome') return detailValue(t, 'outcome') || csvPlain(cell(t, 3 + ci));
    return csvPlain(cell(t, 3 + ci));
  }

  /**
   * Build and download the CSV for one segment of the phases table.
   * @param {string} seg Segment name, as carried by `data-segcsv`.
   * @returns {void}
   */
  function segCsv(seg) {
    // The columns the compact row moved into the detail. A CSV is the complete
    // view by definition: a column that left the table must not leave the file
    // with it.
    const detailCols = ['started', 'model', 'outcome', 'technical outcome',
                        'work item', 'owner', 'waits on'];
    const rows = [['phase', 'phase title', 'phase status',
                   'task', 'task title', 'task status']
      .concat(COLNAMES).concat(detailCols)];
    phaseRows.forEach((pr) => {
      if (pr.__seg !== seg) return;
      const pid = pr.getAttribute('data-phase');
      const titleEl = pr.querySelector('strong');
      const head = [pid, titleEl ? titleEl.textContent : '',
                    pr.getAttribute('data-status') || ''];
      const tasks = tasksOf(pid);
      if (!tasks.length) {
        // A phase with no tasks is still a data row.
        rows.push(head.concat(['', '', ''])
          .concat(COLNAMES.map(() => ''))
          .concat(detailCols.map(() => '')));
        return;
      }
      tasks.forEach((t) => {
        // Machine statuses from the data attributes; prose from the cells; and
        // the fields the table has no column for, so a reader who opened one row
        // to find them does not have to open fifty to tabulate them.
        rows.push(head
          .concat([cell(t, 0), cell(t, 1), t.getAttribute('data-status') || ''])
          .concat(COLNAMES.map((name, ci) => csvCell(t, name, ci)))
          .concat([detailValue(t, 'started') || t.getAttribute('data-started') || '',
                   detailValue(t, 'model') || t.getAttribute('data-model') || '',
                   detailValue(t, 'outcome'),
                   detailValue(t, 'technical'),
                   detailValue(t, 'work item'),
                   detailValue(t, 'owner'),
                   detailValue(t, 'waits on')]));
      });
    });
    csvDownload(BASE + '-phases-' + seg + '.csv', rows);
  }

  /**
   * Build and download the CSV of the bugs table.
   * @returns {void}
   */
  function bugsCsv() {
    const header = ['id', 'title', 'status', 'severity', 'task', 'fixedIn', 'ADO'];
    const rows = bugRows.map((b) => [
      cell(b, 0), cell(b, 1),
      b.getAttribute('data-status') || cell(b, 2),
      cell(b, 3), cell(b, 4), cell(b, 5), cell(b, 6)]);
    csvDownload(BASE + '-bugs.csv', [header].concat(rows));
  }

  /**
   * Build and download the daily usage CSV, one row per recorded day.
   * @returns {void}
   */
  function usageCsv() {
    if (!U) return;
    const showCost = U.showCost !== false;
    const header = ['date', 'tokens'].concat(showCost ? ['costUSD'] : []).concat(['msgs']);
    // Raw numbers on purpose: '3,230,000' lands in a spreadsheet as text, and
    // every sum over the column is then wrong without saying so.
    const rows = Object.keys(U.days).sort().map((d) => {
      const v = U.days[d];
      return showCost ? [d, v[0], v[1], v[2]] : [d, v[0], v[2]];
    });
    csvDownload(BASE + '-usage-daily.csv', [header].concat(rows));
  }

  Array.from(document.querySelectorAll('[data-segcsv]')).forEach((b) => {
    b.addEventListener('click', () => segCsv(b.getAttribute('data-segcsv')));
  });
  Array.from(document.querySelectorAll('[data-csv]')).forEach((b) => {
    b.addEventListener('click',
      b.getAttribute('data-csv') === 'bugs' ? bugsCsv : usageCsv);
  });

  // --- exports: PNG of the charts --------------------------------------------
  // The marks are bars on a grid, so each chart is REDRAWN from
  // window.AUDIT_USAGE onto a canvas. Serialising the DOM into a canvas would
  // need a resource this page may not fetch, and the page has no network at all.

  /**
   * Resolve a CSS custom property to the colour the browser actually computed.
   * @param {string} token Custom-property name, e.g. '--text'.
   * @param {string} fallback Literal colour used when the token resolves to
   *   nothing.
   * @returns {string} A computed CSS colour string.
   */
  function cssColor(token, fallback) {
    // Resolved through a live element rather than read raw off the root:
    // several tokens are color-mix() expressions, and what a canvas needs is the
    // colour the browser settled on, not the expression.
    const probe = document.createElement('i');
    probe.style.color = 'var(' + token + ',' + fallback + ')';
    document.body.appendChild(probe);
    const c = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    return c || fallback;
  }

  /**
   * A detached canvas backed at 2x, with its context pre-scaled so callers draw
   * in CSS pixels. The doubling is what lets the file survive being pasted into
   * a document at print density.
   * @param {number} w Width in CSS pixels.
   * @param {number} h Height in CSS pixels.
   * @returns {{el: HTMLCanvasElement, ctx: CanvasRenderingContext2D}} The canvas
   *   and its scaled 2d context.
   */
  function pngCanvas(w, h) {
    const c = document.createElement('canvas');
    c.width = w * 2;
    c.height = h * 2;
    const ctx = c.getContext('2d');
    // A 2d context is null when the browser cannot back the surface — a large
    // canvas under memory pressure is the realistic case. Throwing here names
    // the cause; letting it through produces `cannot read scale of null` from
    // whichever draw call happens to run first.
    if (!ctx) throw new Error('canvas 2d context unavailable at ' + w + 'x' + h);
    ctx.scale(2, 2);
    return { el: c, ctx: ctx };
  }

  /**
   * Hand a canvas to the browser as a PNG download.
   * @param {string} name Filename offered to the reader.
   * @param {HTMLCanvasElement} canvas Canvas to encode.
   * @returns {void}
   */
  function pngDownload(name, canvas) {
    // toDataURL rather than a blob: synchronous, and these payloads are small,
    // so there is no object URL whose lifetime has to be managed.
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  /**
   * Redraw the tokens-per-day trend onto a canvas and download it as a PNG.
   * @returns {void}
   */
  function trendPng() {
    if (!U) return;
    const days = Object.keys(U.days).sort();
    if (!days.length) return;
    const peak = days.reduce((hi, d) => (U.days[d][0] > hi ? U.days[d][0] : hi), 0);
    // Bar width follows the span, so a three-year ledger still fits one image.
    const barW = Math.max(1, Math.min(10, Math.floor(1100 / days.length)));
    const left = 58, top = 44, bottom = 34;
    const W = left + days.length * (barW + 1) + 14, H = 280;
    const g = pngCanvas(W, H), ctx = g.ctx;
    const ink = cssColor('--text', '#111827');
    const mut = cssColor('--muted', '#6b7280');
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = ink;
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens per day · ' + days[0] + ' to '
      + days[days.length - 1], 10, 20);
    const plot = H - top - bottom;
    ctx.strokeStyle = cssColor('--border', '#d1d5db');
    ctx.fillStyle = mut;
    ctx.font = '11px sans-serif';
    for (const f of [0, 0.5, 1]) {
      const y = top + plot * f;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(W - 6, y);
      ctx.stroke();
      ctx.fillText(fmtTokens(peak * (1 - f), 1), 8, y + 4);
    }
    ctx.fillStyle = cssColor('--accent-solid', '#4f46e5');
    for (const [i, d] of days.entries()) {
      const bh = peak ? Math.max(1, plot * U.days[d][0] / peak) : 1;
      ctx.fillRect(left + i * (barW + 1), top + plot - bh, barW, bh);
    }
    ctx.fillStyle = mut;
    ctx.fillText(days[0], left, H - 12);
    const lastD = days[days.length - 1];
    ctx.fillText(lastD, W - 8 - ctx.measureText(lastD).width, H - 12);
    pngDownload(BASE + '-trend.png', g.el);
  }

  /**
   * Redraw the activity heatmap's CURRENT view onto a canvas and download it.
   *
   * `hmView()` is the heatmap's own view as data — granularity, period, range —
   * so the file shows what the screen shows rather than a second
   * implementation's idea of it.
   * @returns {void}
   */
  function heatmapPng() {
    const v = hmView ? hmView() : null;
    if (!v) return;
    const cellW = 26, cellH = 18, gap = 2, labelW = 96, top = 44;
    const W = labelW + 24 * (cellW + gap) + 12;
    const H = top + v.rows.length * (cellH + gap) + 30;
    const g = pngCanvas(W, H), ctx = g.ctx;
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = cssColor('--text', '#111827');
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens by hour (UTC) · ' + v.label, 10, 20);
    // Seven ramp steps, resolved once: index 0 is "nothing recorded", 1-6 are
    // the intensity bands the on-screen grid uses.
    const ramp = Array.from({ length: 7 },
      (unused, lv) => cssColor('--hm-' + lv, '#eeeeee'));
    const mut = cssColor('--muted', '#6b7280');
    ctx.font = '11px sans-serif';
    for (const [ri, r] of v.rows.entries()) {
      const y = top + ri * (cellH + gap);
      ctx.fillStyle = mut;
      ctx.fillText(r.label, 8, y + cellH - 5);
      for (let h = 0; h < 24; h++) {
        const val = r.cells ? (r.cells[h] || 0) : 0;
        const lv = (!val || !v.peak) ? 0
          : Math.min(6, 1 + Math.floor(5 * val / v.peak));
        ctx.fillStyle = ramp[lv];
        ctx.fillRect(labelW + h * (cellW + gap), y, cellW, cellH);
      }
    }
    ctx.fillStyle = mut;
    for (let tk = 0; tk < 24; tk += 6) {
      ctx.fillText((tk < 10 ? '0' : '') + tk, labelW + tk * (cellW + gap), H - 10);
    }
    pngDownload(BASE + '-heatmap.png', g.el);
  }

  Array.from(document.querySelectorAll('[data-png]')).forEach((b) => {
    b.addEventListener('click',
      b.getAttribute('data-png') === 'trend' ? trendPng : heatmapPng);
  });

  // --- exports: printing one segment -----------------------------------------

  /**
   * Isolate one segment for print. The print stylesheet keys on
   * `body[data-printseg]`, and `afterprint` takes the attribute back off, so a
   * cancelled dialog restores the page exactly like a completed one.
   * @param {string} seg Segment name, as carried by `data-segprint`.
   * @returns {void}
   */
  function printSegment(seg) {
    document.body.setAttribute('data-printseg', seg);
    window.print();
  }

  Array.from(document.querySelectorAll('[data-segprint]')).forEach((b) => {
    b.addEventListener('click', () => printSegment(b.getAttribute('data-segprint')));
  });
  window.addEventListener('afterprint', () => {
    document.body.removeAttribute('data-printseg');
  });

  // --- boot: sorting, the search box, and the view the link asked for --------

  wireSort(grouped, true, true);
  wireSort(bugsTable, false, true);

  if (q) {
    /** @type {number|null} Pending debounce timer id, or null when idle. */
    let qTimer = null;
    /**
     * Schedule the single filter pass that follows a burst of typing.
     *
     * Typing is a burst, not a series of questions. One pass per keystroke means
     * five full passes over every row for a five-character word — half a second
     * of blocked main thread on a 200-phase plan — to show four intermediate
     * results nobody reads. 90ms is below the delay a reader notices and above
     * the fastest realistic repeat rate, and the timer is cleared on every
     * keystroke so a long word still costs exactly one pass.
     * @returns {void}
     */
    const queueRefresh = () => {
      if (qTimer) clearTimeout(qTimer);
      qTimer = setTimeout(() => { qTimer = null; refresh(); }, 90);
    };
    /**
     * Filter immediately for the keys that are decisions rather than typing.
     * Escape also empties the box, which is what makes it a way out.
     * @param {KeyboardEvent} ev Keydown on the search box.
     * @returns {void}
     */
    const filterOnDecisionKey = (ev) => {
      if (ev.key !== 'Enter' && ev.key !== 'Escape') return;
      if (ev.key === 'Escape') q.value = '';
      if (qTimer) { clearTimeout(qTimer); qTimer = null; }
      refresh();
    };
    q.addEventListener('input', queueRefresh);
    q.addEventListener('keydown', filterOnDecisionKey);
  }

  /**
   * Fold one `key=value` pair of the stored filter string into HASH.
   * @param {string} pair One `&`-separated pair; an empty pair is ignored.
   * @returns {void}
   */
  function restoreStoredPair(pair) {
    if (!pair) return;
    const eq = pair.indexOf('=');
    const k = eq < 0 ? pair : pair.slice(0, eq);
    const v = eq < 0 ? '' : pair.slice(eq + 1);
    // A malformed percent-escape throws, and one unreadable pair must not cost
    // the reader the rest of the restored view.
    try { HASH[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) {}
  }

  // Restore what the link asked for BEFORE the first pass, so a shared URL
  // renders the view it names instead of rendering everything and then
  // rearranging itself. A link WINS over the local copy: somebody sent it on
  // purpose. With no link, the local copy is what this reader last had on screen.
  if (!Object.keys(HASH).length) {
    const stored = storageGet(STORE_KEY);
    if (stored) stored.split('&').forEach(restoreStoredPair);
  }
  if (HASH.v && VIEWS[HASH.v]) {
    viewMode = HASH.v;
    if (viewSel) viewSel.value = viewMode;
  }
  // Same shape as the view above, and deliberately NOT through setPhaseOrder:
  // that one ends in refresh(), and the single pass at the bottom of this file
  // is the first pass. Going through it would paint the table in plan order and
  // then rearrange it in front of the reader. `sortSel` gates it because a plan
  // with nothing pinned has no ranks on its rows, and a fragment can name an
  // order the page cannot honour.
  if (HASH.so && ORDERS[HASH.so] && sortSel) {
    phaseOrder = HASH.so;
    sortSel.value = phaseOrder;
    orderPhaseBlocks(ORDERS[phaseOrder]);
  }
  if (q && HASH.q) q.value = HASH.q;
  if (HASH.ps) {
    phaseStatus = HASH.ps;
    if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', phaseStatus);
  }
  if (HASH.m) {
    modelFilter = HASH.m;
    if (modelBar) highlight(modelBar, 'data-m', modelFilter);
  }
  if (HASH.a) {
    areaFilter = HASH.a.split(/\s+/).filter(Boolean);
    paintAreas();
  }
  if (HASH.from || HASH.to) { dFrom = HASH.from || ''; dTo = HASH.to || ''; paintDates(); }
  if (HASH.au) {
    auFilter = HASH.au;
    if (authorBar) highlight(authorBar, 'data-au', auFilter);
    applyAuthor();
  }
  refresh();
