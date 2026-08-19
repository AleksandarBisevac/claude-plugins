  // --- the date range over the usage views (C1) -----------------------------
  // The tables filter their own rows; the usage section is drawings, so the
  // range treats it differently: trend columns outside the range RECEDE (the
  // geometry never moves — hiding bars would silently re-scale a chart whose
  // committed render is byte-compared), months wholly outside the range hide,
  // the heatmap re-renders from the per-day payload, and one line names the
  // span with that span's own totals. That line is also what reaches paper:
  // the sticky bar carrying the pickers never prints, and a scoped chart on a
  // sheet with no visible scope would be a chart that lies.
  var hmApply = null;          // set by the heatmap module below, when present
  var hmView = null;           // ...and its current view as data, for the PNG
  var lastRange = '|';         // sentinel: "no range applied yet"
  function applyUsageRange() {
    var key = dFrom + '|' + dTo;
    if (key === lastRange) return;
    lastRange = key;
    var active = !!(dFrom || dTo);
    [].forEach.call(document.querySelectorAll('.cols [data-d], .xts [data-d]'),
      function (el) {
        var d = el.getAttribute('data-d');
        var out = active && ((dFrom && d < dFrom) || (dTo && d > dTo));
        // SVG 1.1 elements have no classList in some engines; setAttribute is
        // universal and the stylesheet only needs the class present/absent.
        var cls = (el.getAttribute('class') || '').replace(/\s*\bdimout\b/, '');
        el.setAttribute('class', out ? cls + ' dimout' : cls);
      });
    [].forEach.call(document.querySelectorAll('tr[data-um]'), function (r) {
      var m = r.getAttribute('data-um');
      var out = active && ((dFrom && m < dFrom.slice(0, 7))
                           || (dTo && m > dTo.slice(0, 7)));
      r.style.display = out ? 'none' : '';
    });
    var note = document.getElementById('audit-urange');
    if (note) {
      if (active && U) {
        var f = dFrom || U.min, t = dTo || U.max;
        var tok = 0, cost = 0, msgs = 0;
        for (var d2 in U.days) {
          if (d2 >= f && d2 <= t) {
            tok += U.days[d2][0]; cost += U.days[d2][1]; msgs += U.days[d2][2];
          }
        }
        var sep = ' · ';
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

