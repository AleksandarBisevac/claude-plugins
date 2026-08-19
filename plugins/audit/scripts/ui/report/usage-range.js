  // --- the date range over the usage views ----------------------------------
  // The tables filter their own rows; the usage section is drawings, so the
  // range treats it differently: trend columns outside the range RECEDE (the
  // geometry never moves — hiding bars would silently re-scale a chart whose
  // committed render is byte-compared), months wholly outside the range hide,
  // the heatmap re-renders from the per-day payload, and one line names the
  // span with that span's own totals. That line is also what reaches paper:
  // the sticky bar carrying the pickers never prints, and a scoped chart on a
  // sheet with no visible scope would be a chart that lies.
  let hmApply = null;          // set by the heatmap module below, when present
  let hmView = null;           // ...and its current view as data, for the PNG
  let lastRange = '|';         // sentinel: "no range applied yet"

  /**
   * Scope the usage charts, the monthly table and the heatmap to the current
   * date window, and write the line that names the span.
   *
   * Called from every refresh, so it opens with a cheap guard: the range is
   * keyed as one string and the whole pass is skipped unless that key moved.
   *
   * Bounds and per-day keys are compared as plain `YYYY-MM-DD` strings, and
   * month keys as their `YYYY-MM` prefixes. Nothing here is parsed into a Date:
   * lexical order on an ISO string is chronological order, with no timezone to
   * get wrong and no wall-clock call to make the rendered report differ between
   * runs.
   *
   * @returns {void}
   */
  function applyUsageRange() {
    const key = dFrom + '|' + dTo;
    if (key === lastRange) return;
    lastRange = key;
    const active = !!(dFrom || dTo);
    [].forEach.call(document.querySelectorAll('.cols [data-d], .xts [data-d]'),
      (el) => {
        const d = el.getAttribute('data-d');
        const out = active && ((dFrom && d < dFrom) || (dTo && d > dTo));
        // SVG 1.1 elements have no classList in some engines; setAttribute is
        // universal and the stylesheet only needs the class present/absent.
        const cls = (el.getAttribute('class') || '').replace(/\s*\bdimout\b/, '');
        el.setAttribute('class', out ? cls + ' dimout' : cls);
      });
    [].forEach.call(document.querySelectorAll('tr[data-um]'), (r) => {
      const m = r.getAttribute('data-um');
      const out = active && ((dFrom && m < dFrom.slice(0, 7))
                           || (dTo && m > dTo.slice(0, 7)));
      r.style.display = out ? 'none' : '';
    });
    const note = document.getElementById('audit-urange');
    if (note) {
      if (active && U) {
        const f = dFrom || U.min, t = dTo || U.max;
        // One pass over the per-day payload accumulating three totals. A
        // filter-then-reduce chain would allocate a key array and a filtered
        // copy of it to produce the same three numbers.
        let tok = 0, cost = 0, msgs = 0;
        for (const d2 in U.days) {
          if (d2 >= f && d2 <= t) {
            tok += U.days[d2][0]; cost += U.days[d2][1]; msgs += U.days[d2][2];
          }
        }
        const sep = ' · ';
        note.textContent = 'Date range ' + f + ' to ' + t + ': '
          + fmtTokens(tok, 1) + ' tokens'
          + (U.showCost !== false ? sep + fmtCost(cost) : '')
          + sep + fmtInt(msgs) + ' msgs. The tiles above stay all-time; the '
          + 'trend, monthly and hourly views below are scoped to this range.';
        note.hidden = false;
      } else {
        note.hidden = true;
        note.textContent = '';
      }
    }
    if (hmApply) hmApply();
  }
