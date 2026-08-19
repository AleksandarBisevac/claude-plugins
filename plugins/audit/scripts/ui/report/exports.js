  // --- per-segment and per-section exports (D2) ------------------------------
  // CSV of the DATA — never the filtered view: a file named "phases-active"
  // that silently held whatever the search box happened to leave visible
  // would be a different file every download. PNG of the charts, REDRAWN from
  // window.AUDIT_USAGE onto a canvas: the marks are bars on a grid, and
  // DOM-to-canvas serialisation is exactly the dependency this
  // zero-external-fetch file cannot take. And a print mode that isolates one
  // segment. Every button is server-rendered (the chips rule); this only
  // attaches behaviour.
  var BASE = String(window.AUDIT_MD_NAME || 'audit-report.md').replace(/\.md$/, '');
  function csvQuote(v) {
    // RFC 4180, the same rule the panel's export uses: quote anything that
    // carries a comma, a quote or a newline, and double the quotes inside.
    var s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function download(name, blob) {
    // The .md button's own mechanism: a temporary object URL on an anchor,
    // revoked LATE — some engines have not started reading the blob when
    // click() returns, and a revoked URL there is a download that fails with
    // no error anywhere.
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  function csvDownload(name, rows) {
    var text = rows.map(function (r) { return r.map(csvQuote).join(','); })
      .join('\r\n') + '\r\n';
    // U+FEFF: without the BOM Excel reads a UTF-8 CSV in the local 8-bit
    // codepage. As an escape, never the character — an invisible literal in
    // the source is unreviewable (the panel export's own rule).
    download(name, new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' }));
  }
  // Column names read once off the table's own header — the export must not
  // restate _present_columns, or the two would disagree the first time a
  // column appears.
  // The MACHINE name of each optional column, from the header's own attribute
  // rather than its words: the done header carries a "UTC" note beside the
  // word, and a CSV keyed on rendered text would stop recognising the column
  // the moment a header gained a second word (it did).
  var COLNAMES = grouped
    ? [].slice.call(grouped.querySelectorAll('thead th')).map(function (h) {
        return h.getAttribute('data-col') || h.textContent.trim();
      }).slice(3)
    : [];
  // csv (F-P-4): the file carries the DATA, not what the cell happens to show.
  // Three columns are lossy on screen and were being exported lossy: the commit
  // cell shows nine characters (and, since the copy control landed, the word
  // "Copy" inside its own text), the done cell shows minutes, and the outcome
  // cell is cut at 70 characters. A spreadsheet is where someone re-derives
  // things, so each of those exports its full value — read from the same place
  // the reader can see it, the detail row.
  function detailValue(t, key) {
    var d = t.__detail;
    if (!d) return '';
    var ks = [].slice.call(d.querySelectorAll('.dt-k'));
    for (var i = 0; i < ks.length; i++) {
      if (ks[i].textContent.trim() === key) {
        var v = ks[i].nextElementSibling;
        return v ? v.textContent.trim() : '';
      }
    }
    return '';
  }
  // An em dash is what a table prints where there is nothing; a data file says
  // nothing by saying nothing. Every column goes through this.
  function csvPlain(v) { return (v === '\u2014' || v === '-') ? '' : v; }
  function csvCell(t, name, ci) {
    if (name === 'commit') {
      var b = t.querySelector('.shacopy');
      return b ? b.getAttribute('data-copy') : '';
    }
    if (name === 'done') {
      // The DETAIL row carries the whole stamp; the data-attribute is cut to
      // the date on purpose (the range filter compares those as strings), and
      // the cell is cut to the minute. A spreadsheet gets the seconds.
      return detailValue(t, 'completed') || detailValue(t, 'started')
        || t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
    }
    if (name === 'outcome') return detailValue(t, 'outcome') || csvPlain(cell(t, 3 + ci));
    return csvPlain(cell(t, 3 + ci));
  }
  function segCsv(seg) {
    var rows = [['phase', 'phase title', 'phase status',
                 'task', 'task title', 'task status'].concat(COLNAMES)
      // ...plus everything the compact row moved into the detail. A CSV is the
      // complete view by definition: a column that left the table must not
      // leave the file with it.
      .concat(['started', 'model', 'outcome', 'technical outcome', 'work item',
               'owner', 'waits on'])];
    phaseRows.forEach(function (pr) {
      if (pr.__seg !== seg) return;
      var pid = pr.getAttribute('data-phase');
      var strongEl = pr.querySelector('strong');
      var head = [pid, strongEl ? strongEl.textContent : '',
                  pr.getAttribute('data-status') || ''];
      var tasks = tasksOf(pid);
      if (!tasks.length) {   // a phase with no tasks is still a data row
        rows.push(head.concat(['', '', ''])
          .concat(COLNAMES.map(function () { return ''; }))
          .concat(['', '', '', '', '', '', '']));
        return;
      }
      tasks.forEach(function (t) {
        // Machine statuses from the data attributes; prose from the cells.
        var line = head.concat([cell(t, 0), cell(t, 1),
                                t.getAttribute('data-status') || '']);
        for (var ci = 0; ci < COLNAMES.length; ci++) {
          line.push(csvCell(t, COLNAMES[ci], ci));
        }
        // The four the table has no column for and the detail row does. A
        // reader who opened the row to find them should not have to open
        // fifty rows to tabulate them.
        line.push(detailValue(t, 'started') || t.getAttribute('data-started') || '',
                  detailValue(t, 'model') || t.getAttribute('data-model') || '',
                  detailValue(t, 'outcome'),
                  detailValue(t, 'technical'),
                  detailValue(t, 'work item'),
                  detailValue(t, 'owner'),
                  detailValue(t, 'waits on'));
        rows.push(line);
      });
    });
    csvDownload(BASE + '-phases-' + seg + '.csv', rows);
  }
  function bugsCsv() {
    var rows = [['id', 'title', 'status', 'severity', 'task', 'fixedIn', 'ADO']];
    bugRows.forEach(function (b) {
      rows.push([cell(b, 0), cell(b, 1),
                 b.getAttribute('data-status') || cell(b, 2),
                 cell(b, 3), cell(b, 4), cell(b, 5), cell(b, 6)]);
    });
    csvDownload(BASE + '-bugs.csv', rows);
  }
  function usageCsv() {
    if (!U) return;
    var showCost = U.showCost !== false;
    var rows = [['date', 'tokens'].concat(showCost ? ['costUSD'] : [])
      .concat(['msgs'])];
    var days = [];
    for (var ud in U.days) days.push(ud);
    days.sort();
    days.forEach(function (d) {
      var v = U.days[d];
      // Raw numbers on purpose: '3,230,000' lands in a spreadsheet as text
      // and every sum over the column is then wrong, silently.
      var line = [d, v[0]];
      if (showCost) line.push(v[1]);
      line.push(v[2]);
      rows.push(line);
    });
    csvDownload(BASE + '-usage-daily.csv', rows);
  }
  [].slice.call(document.querySelectorAll('[data-segcsv]')).forEach(function (b) {
    b.addEventListener('click', function () {
      segCsv(b.getAttribute('data-segcsv'));
    });
  });
  [].slice.call(document.querySelectorAll('[data-csv]')).forEach(function (b) {
    b.addEventListener('click',
      b.getAttribute('data-csv') === 'bugs' ? bugsCsv : usageCsv);
  });

  function cssColor(token, fallback) {
    // Resolved through a live element rather than read raw off the root:
    // several tokens are color-mix() expressions, and what a canvas needs is
    // the colour the browser actually computed.
    var probe = document.createElement('i');
    probe.style.color = 'var(' + token + ',' + fallback + ')';
    document.body.appendChild(probe);
    var c = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    return c || fallback;
  }
  function pngCanvas(w, h) {
    var c = document.createElement('canvas');
    // 2x, so the file survives being pasted into a document at print density.
    c.width = w * 2; c.height = h * 2;
    var ctx = c.getContext('2d');
    ctx.scale(2, 2);
    return { el: c, ctx: ctx };
  }
  function pngDownload(name, canvas) {
    // toDataURL rather than a blob: synchronous, and the payload is small.
    var a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }
  function trendPng() {
    if (!U) return;
    var days = [];
    for (var td in U.days) days.push(td);
    days.sort();
    if (!days.length) return;
    var peak = 0;
    days.forEach(function (d) { if (U.days[d][0] > peak) peak = U.days[d][0]; });
    // Bar width follows the span so a three-year ledger still fits one image.
    var barW = Math.max(1, Math.min(10, Math.floor(1100 / days.length)));
    var left = 58, top = 44, bottom = 34;
    var W = left + days.length * (barW + 1) + 14, H = 280;
    var g = pngCanvas(W, H), ctx = g.ctx;
    var ink = cssColor('--text', '#111827');
    var mut = cssColor('--muted', '#6b7280');
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = ink;
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens per day · ' + days[0] + ' to '
      + days[days.length - 1], 10, 20);
    var plot = H - top - bottom;
    ctx.strokeStyle = cssColor('--border', '#d1d5db');
    ctx.fillStyle = mut;
    ctx.font = '11px sans-serif';
    [0, 0.5, 1].forEach(function (f) {
      var y = top + plot * f;
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(W - 6, y); ctx.stroke();
      ctx.fillText(fmtTokens(peak * (1 - f), 1), 8, y + 4);
    });
    ctx.fillStyle = cssColor('--accent-solid', '#4f46e5');
    days.forEach(function (d, i) {
      var v = U.days[d][0];
      var bh = peak ? Math.max(1, plot * v / peak) : 1;
      ctx.fillRect(left + i * (barW + 1), top + plot - bh, barW, bh);
    });
    ctx.fillStyle = mut;
    ctx.fillText(days[0], left, H - 12);
    var lastD = days[days.length - 1];
    ctx.fillText(lastD, W - 8 - ctx.measureText(lastD).width, H - 12);
    pngDownload(BASE + '-trend.png', g.el);
  }
  function heatmapPng() {
    // hmView is set by the heatmap module below; it answers with the CURRENT
    // view — granularity, period, range — so the file shows what the screen
    // shows, not a second implementation's idea of it.
    var v = hmView ? hmView() : null;
    if (!v) return;
    var cellW = 26, cellH = 18, gap = 2, labelW = 96, top = 44;
    var W = labelW + 24 * (cellW + gap) + 12;
    var H = top + v.rows.length * (cellH + gap) + 30;
    var g = pngCanvas(W, H), ctx = g.ctx;
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = cssColor('--text', '#111827');
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens by hour (UTC) · ' + v.label, 10, 20);
    var ramp = [];
    for (var lv0 = 0; lv0 <= 6; lv0++) ramp.push(cssColor('--hm-' + lv0, '#eeeeee'));
    ctx.font = '11px sans-serif';
    v.rows.forEach(function (r, ri) {
      var y = top + ri * (cellH + gap);
      ctx.fillStyle = cssColor('--muted', '#6b7280');
      ctx.fillText(r.label, 8, y + cellH - 5);
      for (var h2 = 0; h2 < 24; h2++) {
        var val = r.cells ? (r.cells[h2] || 0) : 0;
        var lv = (!val || !v.peak) ? 0
          : Math.min(6, 1 + Math.floor(5 * val / v.peak));
        ctx.fillStyle = ramp[lv];
        ctx.fillRect(labelW + h2 * (cellW + gap), y, cellW, cellH);
      }
    });
    ctx.fillStyle = cssColor('--muted', '#6b7280');
    for (var tk = 0; tk < 24; tk += 6) {
      ctx.fillText((tk < 10 ? '0' : '') + tk, labelW + tk * (cellW + gap), H - 10);
    }
    pngDownload(BASE + '-heatmap.png', g.el);
  }
  [].slice.call(document.querySelectorAll('[data-png]')).forEach(function (b) {
    b.addEventListener('click',
      b.getAttribute('data-png') === 'trend' ? trendPng : heatmapPng);
  });

  // Print one segment (D2): stamp the attribute the print CSS keys on, open
  // the dialog, and let afterprint take it back off — the same event the
  // details-reopening handler above already rides, so a cancelled dialog
  // restores exactly like a completed one.
  [].slice.call(document.querySelectorAll('[data-segprint]')).forEach(function (b) {
    b.addEventListener('click', function () {
      document.body.setAttribute('data-printseg', b.getAttribute('data-segprint'));
      window.print();
    });
  });
  window.addEventListener('afterprint', function () {
    document.body.removeAttribute('data-printseg');
  });

  wireSort(grouped, true, true);
  wireSort(bugsTable, false, true);
  // Typing is a burst, not a series of questions. Five characters used to mean five
  // full passes over every row — half a second of blocked main thread on a
  // 200-phase plan — to show four intermediate results nobody reads. One pass once
  // you stop. 90ms is below the threshold where a filter feels delayed and above
  // the fastest realistic repeat rate, and the timer is cleared on every keystroke
  // so a long word still costs exactly one pass.
  if (q) {
    var qTimer = null;
    q.addEventListener('input', function () {
      if (qTimer) clearTimeout(qTimer);
      qTimer = setTimeout(function () { qTimer = null; refresh(); }, 90);
    });
    // Enter and Escape are decisions, not typing: act at once.
    q.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== 'Escape') return;
      if (ev.key === 'Escape') q.value = '';
      if (qTimer) { clearTimeout(qTimer); qTimer = null; }
      refresh();
    });
  }
  // Restore what the link asked for BEFORE the first pass, so a shared URL renders
  // the view it names instead of rendering everything and then rearranging itself.
  // A link WINS over the local copy: somebody sent it on purpose. With no link,
  // the local copy is what this reader last had on screen.
  if (!Object.keys(HASH).length) {
    try {
      var stored = localStorage.getItem(STORE_KEY);
      if (stored) {
        stored.split('&').forEach(function (pair) {
          if (!pair) return;
          var i = pair.indexOf('=');
          var k = i < 0 ? pair : pair.slice(0, i);
          var v = i < 0 ? '' : pair.slice(i + 1);
          try { HASH[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) {}
        });
      }
    } catch (e) {}
  }
  if (HASH.v && VIEWS[HASH.v]) {
    viewMode = HASH.v;
    if (viewSel) viewSel.value = viewMode;
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
