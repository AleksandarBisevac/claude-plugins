  function openPanel() { return document.querySelector('details.fdetails[open]'); }
  document.addEventListener('click', function (ev) {
    var d = openPanel();
    if (d && !d.contains(ev.target)) d.open = false;
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape') return;
    // Escape in the search box already means "clear the search"; leave it alone
    // rather than have one key do two things at once.
    if (q && ev.target === q) return;
    var d = openPanel();
    if (!d) return;
    d.open = false;
    var sum = d.querySelector('summary');
    if (sum) sum.focus();          // put focus back on the control that opened it
  });

  function paintDates() {
    if (fromInput) fromInput.value = dFrom;
    if (toInput) toInput.value = dTo;
    // The global pair mirrors the same state, so editing either pair repaints
    // both — two controls, one range, never two answers.
    if (gFrom) gFrom.value = dFrom;
    if (gTo) gTo.value = dTo;
    if (gClear) gClear.hidden = !(dFrom || dTo);
    if (presetBar) highlight(presetBar, 'data-days', preset);
  }
  // One entry point for every control that sets the range: panel inputs,
  // global inputs, the All-time reset. A hand-picked range is no longer a
  // preset, so the chip row unlights.
  function setRange(f, t) {
    dFrom = f || '';
    dTo = t || '';
    preset = '';
    paintDates();
    refresh();
  }
  function onDateInput() {
    setRange(fromInput ? fromInput.value : '', toInput ? toInput.value : '');
  }
  if (fromInput) fromInput.addEventListener('change', onDateInput);
  if (toInput) toInput.addEventListener('change', onDateInput);
  function onGDateInput() {
    setRange(gFrom ? gFrom.value : '', gTo ? gTo.value : '');
  }
  if (gFrom) gFrom.addEventListener('change', onGDateInput);
  if (gTo) gTo.addEventListener('change', onGDateInput);
  // Clearing returns to all-time (C1): one press, both pairs blank, every
  // scoped view back to the whole record.
  if (gClear) gClear.addEventListener('click', function () { setRange('', ''); });

  // Relative spans, measured back from the plan's last recorded day (DMAX) rather
  // than from today — see DMAX above for why the wall clock is not an option here.
  function applyPreset(days) {
    preset = days;
    var ms = DMAX ? Date.parse(DMAX + 'T00:00:00Z') : NaN;
    if (days === 'all' || isNaN(ms)) {
      dFrom = ''; dTo = '';
      if (days !== 'all') preset = '';   // nothing to measure from; claim nothing
    } else {
      // Inclusive of the last day, so "7 days" spans seven of them and not eight.
      dFrom = new Date(ms - (Number(days) - 1) * 86400000).toISOString().slice(0, 10);
      dTo = DMAX;
    }
    paintDates();
    refresh();
  }
  wireChips(presetBar, 'data-days', function (val) {
    applyPreset(preset === val ? 'all' : val);
  });

  // One control that undoes all of them. It lives in the empty state because that
  // is the one view from which no other control is reachable — every chip that
  // could clear itself has been filtered off the screen along with the rows.
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
    tfHosts.forEach(function (h) { highlight(h, 'data-ts', ''); });
    applyAuthor();
    paintDates();
    refresh();
  }
  clearBtns.forEach(function (b) { b.addEventListener('click', clearAll); });

  // Save as PDF — the print stylesheet lays the whole plan out with every phase
  // expanded and leaves the sheet itself to the dialog, which is also where
  // "Save as PDF" lives (no bundled PDF library, so the file stays small and
  // self-contained).
  var printBtn = document.getElementById('audit-print');
  if (printBtn) printBtn.addEventListener('click', function () { window.print(); });

  // A CLOSED <details> still collapses in print media even when its children are
  // forced visible by CSS — the element clips them, so the print stylesheet alone
  // silently drops the Usage detail from the PDF. Open them for the duration of
  // the print and restore afterwards, so what you see is what you get.
  var reopen = [];
  window.addEventListener('beforeprint', function () {
    reopen = [];
    Array.prototype.forEach.call(document.querySelectorAll('details'), function (d) {
      if (!d.open) { reopen.push(d); d.open = true; }
    });
  });
  window.addEventListener('afterprint', function () {
    reopen.forEach(function (d) { d.open = false; });
    reopen = [];
  });

  // Hover layer for the Usage charts. It renders NOTHING of its own: every value
  // it shows already sits in a `title` attribute (or an SVG <title> child) on the
  // mark, so with JS disabled the browser shows the same text natively and the
  // report still explains itself from a file:// URL. Titles are stashed and
  // removed while JS is live only so the native tooltip does not fight this one.
  (function () {
    // Scoped to the Usage section — the siblings between its <h2> and the next
    // one. Everything else in the report keeps its plain native tooltips.
    var start = document.getElementById('usage');
    if (!start) return;
    var found = 0;
    function claim(node, text) {
      if (!node || !text) return;
      node.__tip = text; found++;
    }
    for (var s = start.nextElementSibling; s && s.tagName !== 'H2';
         s = s.nextElementSibling) {
      // The attribute STAYS. Stripping it permanently was a real loss and not
      // the one it looked like: `title` is what the accessibility tree uses as
      // an element's description, so removing it takes the text away from a
      // screen reader entirely - and this layer only ever gives it back to a
      // pointer. Measured on the shipped report at 1153px: all 11 `.rank .nm`
      // are clipped (49-78% shown), `.rank` rows carry no `tabindex`, and the
      // only listeners here are `mouseover`/`mousemove`. No mouse, no text.
      // It is now suppressed per element only while that element is hovered,
      // which is the whole reason it was removed - so the two tooltips still
      // never fight, and everyone else keeps the description.
      if (s.hasAttribute('title')) claim(s, s.getAttribute('title'));
      Array.prototype.forEach.call(s.querySelectorAll('[title]'), function (n) {
        claim(n, n.getAttribute('title'));
      });
      // SVG <title> children — same text, different carrier.
      Array.prototype.forEach.call(s.querySelectorAll('title'), function (t) {
        claim(t.parentNode, t.textContent);
        if (t.parentNode) t.parentNode.removeChild(t);
      });
    }
    if (!found) return;

    var box = document.createElement('div');
    box.className = 'rtip'; box.hidden = true;
    document.body.appendChild(box);

    function fill(text) {
      box.textContent = '';
      text.split('\n').forEach(function (line, i) {
        if (i === 0) {
          var b = document.createElement('b'); b.textContent = line;
          box.appendChild(b); return;
        }
        var parts = line.split('\t');
        var row = document.createElement('span');
        var k = document.createElement('em'); k.textContent = parts[0];
        var v = document.createElement('i'); v.textContent = parts[1] || '';
        row.appendChild(k); row.appendChild(v); box.appendChild(row);
      });
    }
    function place(ev) {
      var r = box.getBoundingClientRect();
      var x = ev.clientX + 14, y = ev.clientY + 16;
      if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - 14;
      if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 16;
      box.style.left = Math.max(8, x) + 'px';
      box.style.top = Math.max(8, y) + 'px';
    }
    // The focus half of the same box. `place` reads ev.clientX/clientY, which a
    // focus event does not carry - so a keyboard reader would have got the
    // tooltip pinned at 0,0 or wherever the mouse was last left. Placed under the
    // mark's own rect instead, flipping above it when there is no room below, so
    // it never covers the row it is describing.
    function placeAt(node) {
      var q = node.getBoundingClientRect();
      var r = box.getBoundingClientRect();
      var x = q.left, y = q.bottom + 6;
      if (x + r.width > window.innerWidth - 8) x = window.innerWidth - r.width - 8;
      if (y + r.height > window.innerHeight - 8) y = q.top - r.height - 6;
      box.style.left = Math.max(8, x) + 'px';
      box.style.top = Math.max(8, y) + 'px';
    }
    function hide() {
      restoreNative(current);
      box.hidden = true; current = null;
    }
    // Delegated: three listeners instead of one per mark. A dense report carries
    // well over a thousand hoverable marks, and binding each of them is a cost
    // paid on every page load to serve one hover at a time.
    function owner(node) {
      for (var n = node; n && n !== document; n = n.parentNode) {
        if (n.__tip) return n;
      }
      return null;
    }
    // Suppress the native tooltip on the hovered element ONLY, and give it back
    // the moment the pointer leaves. Restoring is not optional bookkeeping: skip
    // it and the first hover strips the description permanently, which is the
    // bug this replaced wearing a slower disguise.
    function muteNative(node) {
      if (node && node.hasAttribute && node.hasAttribute('title')) {
        node.removeAttribute('title');
      }
    }
    function restoreNative(node) {
      if (node && node.__tip && node.setAttribute && !node.hasAttribute('title')) {
        node.setAttribute('title', node.__tip);
      }
    }
    var current = null;
    document.addEventListener('mouseover', function (ev) {
      var m = owner(ev.target);
      if (m === current) return;
      restoreNative(current);
      current = m;
      if (!m) { box.hidden = true; return; }
      muteNative(m);
      fill(m.__tip); box.hidden = false; place(ev);
    });
    document.addEventListener('mousemove', function (ev) {
      if (current) place(ev);
    });
    // F17 - THE KEYBOARD HALF. Restoring `title` (u24d) put the description back
    // in the accessibility tree, which serves a screen-reader user and a JS-off
    // reader. It does nothing for a SIGHTED KEYBOARD reader: no browser surfaces
    // a native `title` on focus, and the two listeners above are pointer-only. So
    // the same box gets a second trigger rather than a second implementation -
    // one `fill`, one `hide`, one element on the page.
    document.addEventListener('focusin', function (ev) {
      var m = owner(ev.target);
      if (m === current) return;
      restoreNative(current);
      current = m;
      if (!m) { box.hidden = true; return; }
      muteNative(m);
      fill(m.__tip); box.hidden = false; placeAt(m);
    });
    document.addEventListener('focusout', function (ev) {
      if (current && owner(ev.target) === current) hide();
    });
    // Dismissible (SC 1.4.13). Escape closes the box WITHOUT moving the caret -
    // a reader who dismissed a tooltip has not asked to leave the row, and
    // sending focus elsewhere would make Escape cost them their place. The mark
    // keeps focus, so tabbing on still works from where they were.
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      if (!current) return;
      hide();
    });
    // Printing a floating tooltip would stamp it onto the page. Whatever was
    // hovered gets its `title` back here too - dropping `current` without
    // restoring is exactly how one element would keep losing its description,
    // and printing is the one path that clears `current` without a mouseover.
    window.addEventListener('beforeprint', hide);
  })();

