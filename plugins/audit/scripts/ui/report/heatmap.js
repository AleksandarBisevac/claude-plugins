  // --- heatmap calendar navigation (C3) --------------------------------------
  // The server renders the all-data 7x24 grid; this re-renders the tbody from
  // the embedded per-day payload for one day / week / month / year at a time,
  // prev/next strictly bounded by the data (an arrow at the edge is disabled
  // and muted, never a dead click), and the period on display NAMED in the
  // label. The custom range IS C1's range control: while a range is active the
  // heatmap's whole universe is that range — granularity navigation clamps to
  // it, and "All" reads "Custom range" with the span. One range, one meaning.
  (function () {
    var body = document.getElementById('audit-hm-body');
    var granBar = document.getElementById('audit-hm-gran');
    var prevBtn = document.getElementById('audit-hm-prev');
    var nextBtn = document.getElementById('audit-hm-next');
    var periodEl = document.getElementById('audit-hm-period');
    var peakEl = document.getElementById('audit-hm-peak');
    if (!U || !body || !granBar || !prevBtn || !nextBtn || !periodEl) return;
    var DAY = 86400000;
    var WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December'];
    var gran = 'all';
    var anchor = '';             // period start (ISO day) when gran !== 'all'
    function dParse(d) { return Date.parse(d + 'T00:00:00Z'); }
    function dIso(ms) { return new Date(ms).toISOString().slice(0, 10); }
    function wdayOf(d) { return (new Date(dParse(d)).getUTCDay() + 6) % 7; }
    function bounds() {
      var lo = U.min, hi = U.max;
      if (dFrom && dFrom > lo) lo = dFrom;
      if (dTo && dTo < hi) hi = dTo;
      return lo > hi ? null : { lo: lo, hi: hi };
    }
    function startOf(g, day) {
      if (g === 'week') return dIso(dParse(day) - wdayOf(day) * DAY);
      if (g === 'month') return day.slice(0, 7) + '-01';
      if (g === 'year') return day.slice(0, 4) + '-01-01';
      return day;
    }
    function endOf(g, s) {
      if (g === 'week') return dIso(dParse(s) + 6 * DAY);
      if (g === 'month') {
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7), 0));
      }
      if (g === 'year') return s.slice(0, 4) + '-12-31';
      return s;
    }
    function shift(g, s, dir) {
      if (g === 'day') return dIso(dParse(s) + dir * DAY);
      if (g === 'week') return dIso(dParse(s) + dir * 7 * DAY);
      if (g === 'month') {
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1 + dir, 1));
      }
      if (g === 'year') return (+s.slice(0, 4) + dir) + '-01-01';
      return s;
    }
    function hasData(from, to) {
      for (var d in U.days) { if (d >= from && d <= to) return true; }
      return false;
    }
    // The next period in `dir` that is inside the bounds AND records anything
    // — "never navigate into empty periods" is a rule about data, not about
    // the calendar, so gap days between two worked weeks are stepped OVER.
    function seek(g, s, dir, b) {
      for (var i = 0; i < 4000; i++) {
        s = shift(g, s, dir);
        var en = endOf(g, s);
        if (en < b.lo || s > b.hi) return null;
        var lo = s < b.lo ? b.lo : s;
        var hi = en > b.hi ? b.hi : en;
        if (hasData(lo, hi)) return s;
      }
      return null;
    }
    function labelOf(g, s, b) {
      if (g === 'day') return WD[wdayOf(s)] + ' ' + s;
      if (g === 'week') return 'Week of ' + s + ' to ' + endOf('week', s);
      if (g === 'month') return MON[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4);
      if (g === 'year') return s.slice(0, 4);
      return ((dFrom || dTo) ? 'Custom range' : 'All data')
        + ' · ' + b.lo + ' to ' + b.hi;
    }
    function hoursOf(d) { return (U.days[d] || [0, 0, 0, []])[3] || []; }
    // The current view as DATA — rows, peak, label — split from the DOM paint
    // so the PNG export (D2) can redraw exactly what is on screen without
    // touching it. The anchor clamp lives here because the view is what the
    // clamp is FOR: render() paints whatever this returns.
    function view() {
      var b = bounds();
      if (!b) return null;
      if (gran !== 'all') {
        if (!anchor) anchor = startOf(gran, b.hi);
        var aEnd = endOf(gran, anchor);
        if (aEnd < b.lo || anchor > b.hi) anchor = startOf(gran, b.hi);
      }
      var s = gran === 'all' ? b.lo : anchor;
      var en = gran === 'all' ? b.hi : endOf(gran, s);
      var lo = s < b.lo ? b.lo : s;
      var hi = en > b.hi ? b.hi : en;
      // rows: [{label, days:[iso|null x cells]}] — day/week keep the calendar
      // (one row per date), coarser grains aggregate by weekday like the
      // server's all-data view.
      var rows = [];
      if (gran === 'day') {
        rows.push({ label: WD[wdayOf(lo)] + ' ' + lo.slice(5), cells: hoursOf(lo).slice(),
                    head: WD[wdayOf(lo)] + ' ' + lo });
      } else if (gran === 'week') {
        for (var ms = dParse(s); ms <= dParse(en); ms += DAY) {
          var d = dIso(ms);
          var inR = d >= lo && d <= hi;
          rows.push({ label: WD[wdayOf(d)] + ' ' + d.slice(5),
                      cells: inR ? hoursOf(d).slice() : null,
                      head: WD[wdayOf(d)] + ' ' + d });
        }
      } else {
        var agg = [];
        for (var w = 0; w < 7; w++) agg.push([]);
        for (var dd in U.days) {
          if (dd < lo || dd > hi) continue;
          var vec = hoursOf(dd);
          var tgt = agg[wdayOf(dd)];
          for (var h = 0; h < 24; h++) tgt[h] = (tgt[h] || 0) + (vec[h] || 0);
        }
        for (var w2 = 0; w2 < 7; w2++) {
          rows.push({ label: WD[w2], cells: agg[w2], head: WD[w2] });
        }
      }
      var peak = 0;
      rows.forEach(function (r) {
        (r.cells || []).forEach(function (v) { if (v > peak) peak = v; });
      });
      return { rows: rows, peak: peak, s: s, b: b,
               label: labelOf(gran, s, b) };
    }
    function render() {
      var v = view();
      var setArrow = function (btn, ok) {
        if (ok) btn.removeAttribute('disabled');
        else btn.setAttribute('disabled', '');
      };
      if (!v) {
        body.innerHTML = '';
        periodEl.textContent = 'No recorded usage in this range';
        if (peakEl) peakEl.textContent = '0';
        setArrow(prevBtn, false); setArrow(nextBtn, false);
        return;
      }
      var htmlRows = [], tips = [];
      v.rows.forEach(function (r) {
        var tds = [];
        for (var h2 = 0; h2 < 24; h2++) {
          var val = r.cells ? (r.cells[h2] || 0) : 0;
          var lv = (!val || !v.peak) ? 0
            : Math.min(6, 1 + Math.floor(5 * val / v.peak));
          tds.push('<td><i data-l="' + lv + '"></i></td>');
          // Same one-line shape the server's titles use; a day the range
          // excludes says so instead of claiming a zero it cannot know.
          tips.push(r.cells
            ? r.head + ' ' + (h2 < 10 ? '0' : '') + h2 + ':00 - '
              + fmtTokens(val, 2) + ' tokens'
            : r.head + ' - outside the selected range');
        }
        htmlRows.push('<tr><th>' + r.label + '</th>'
          + tds.join('') + '</tr>');
      });
      body.innerHTML = htmlRows.join('');
      [].forEach.call(body.querySelectorAll('i'), function (cell, i) {
        cell.__tip = tips[i];
      });
      if (peakEl) peakEl.textContent = fmtTokens(v.peak, 1);
      periodEl.textContent = v.label;
      var canStep = gran !== 'all';
      setArrow(prevBtn, canStep && seek(gran, v.s, -1, v.b) !== null);
      setArrow(nextBtn, canStep && seek(gran, v.s, 1, v.b) !== null);
    }
    function step(dir) {
      var b = bounds();
      if (!b || gran === 'all') return;
      var s2 = seek(gran, anchor, dir, b);
      if (!s2) return;
      anchor = s2;
      render();
    }
    prevBtn.addEventListener('click', function () { step(-1); });
    nextBtn.addEventListener('click', function () { step(1); });
    wireChips(granBar, 'data-g', function (val) {
      if (val === gran) return;
      gran = val;
      var b = bounds();
      anchor = (val === 'all' || !b) ? '' : startOf(val, b.hi);
      highlight(granBar, 'data-g', gran);
      render();
    });
    highlight(granBar, 'data-g', gran);   // 'all' is lit from the start
    // Called when the global range moves: clamp the current period into the
    // new bounds and redraw. The initial no-range state deliberately keeps the
    // server-rendered tbody untouched.
    hmApply = render;
    hmView = view;
  })();

  // Download the Markdown twin (embedded as base64, decoded to a Blob).
  // Copy the run command. clipboard.writeText is unavailable on file:// in some
  // browsers, which is exactly where this report is most often opened, so the
  // fallback selects the text and lets the reader use their own copy key rather
  // than failing silently and leaving a button that does nothing.
  [].slice.call(document.querySelectorAll('.btn-copy')).forEach(function (b) {
    b.addEventListener('click', function () {
      var text = b.getAttribute('data-copy') || '';
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1600); };
      try {
        navigator.clipboard.writeText(text).then(done, function () { selectRun(b); });
      } catch (e) { selectRun(b); }
    });
  });
  function selectRun(btn) {
    var code = btn.parentNode.querySelector('.vd-run');
    if (!code) return;
    var r = document.createRange(); r.selectNodeContents(code);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    btn.textContent = 'Press to copy';
    setTimeout(function () { btn.textContent = 'Copy'; }, 2400);
  }

  var dlBtn = document.getElementById('audit-dl-md');
  if (dlBtn) dlBtn.addEventListener('click', function () {
    try {
      var bin = atob(window.AUDIT_MD_B64 || '');
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var url = URL.createObjectURL(new Blob([bytes], { type: 'text/markdown;charset=utf-8' }));
      var a = document.createElement('a');
      a.href = url; a.download = (window.AUDIT_MD_NAME || 'audit-report.md');
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {}
  });

  // ex (F-P-4): the per-task detail toggle. The compact row answers "where is
  // this"; this opens the row that answers "what happened and who do I ask" —
  // the full outcome above all, which the table can only show 70 characters of.
  [].slice.call(document.querySelectorAll('.dtoggle')).forEach(function (b) {
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();          // the row itself is not a control
      var row = b.closest('tr.task');
      if (!row || !row.__detail) return;
      row.__open = !row.__open;
      row.__detail.hidden = !row.__open;
      b.setAttribute('aria-expanded', row.__open ? 'true' : 'false');
      b.setAttribute('aria-label', (row.__open ? 'Hide' : 'Show')
        + ' details for ' + (b.getAttribute('data-dfor') || 'this task'));
    });
  });

  // vw: the view select. Unlike the toggle it replaces, this IS part of the
  // view someone would send as a link (and expect back after a reload), so it
  // rides the fragment and the local fallback with the filters.
  function setView(v) {
    if (!VIEWS[v]) return;
    viewMode = v;
    if (viewSel && viewSel.value !== v) viewSel.value = v;
    refresh();
  }
  if (viewSel) {
    viewSel.value = viewMode;
    viewSel.addEventListener('change', function () { setView(viewSel.value); });
  }
  [].slice.call(document.querySelectorAll('[data-viewall]')).forEach(function (b) {
    b.addEventListener('click', function () { setView('all'); });
  });

