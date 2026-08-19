  // --- wiring the controls the document already carries -----------------------

  // Attach behaviour to chips that are already in the document. They used to be
  // created here, which meant the filter UI simply did not exist for anything
  // that does not run scripts — and "the filters are gone" and "the filters are
  // broken" look identical from the outside.
  function wireChips(host, dataAttr, onToggle) {
    if (!host) return;
    host.addEventListener('click', function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('[' + dataAttr + ']') : null;
      var val = btn && btn.getAttribute(dataAttr);
      if (!val) return;
      onToggle(val, host, dataAttr);
    });
  }
  function highlight(host, dataAttr, active) {
    [].forEach.call(host.children, function (x) {
      var on = x.getAttribute(dataAttr) === active;
      // classList, not a className rebuilt from its first word: that rebuild
      // silently dropped every class after the first, so any second utility class
      // a chip carries disappeared the moment the chip was toggled.
      x.classList.toggle('on', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  // phase expand/collapse (click or Enter/Space); state persists
  phaseRows.forEach(function (pr) {
    function toggle() { var pid = pr.getAttribute('data-phase'); expanded[pid] = !expanded[pid]; persist(); refresh(); }
    pr.addEventListener('click', function (e) {
      // A phase row contains its own controls — the "held by" link that jumps to
      // the phase holding this one shut, and anything a later section adds. Those
      // have their own meaning; swallowing them into the row's toggle meant
      // following the link ALSO collapsed the row you were about to read.
      if (e.target && e.target.closest && e.target.closest('a,button,input,select,summary,label')) return;
      toggle();
    });
    pr.addEventListener('keydown', function (e) {
      if (e.target !== pr) return;   // Enter on a focused link inside the row is the link's
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
  if (expandBtn) expandBtn.addEventListener('click', function () {
    var anyClosed = phaseRows.some(function (pr) { return !expanded[pr.getAttribute('data-phase')]; });
    phaseRows.forEach(function (pr) { expanded[pr.getAttribute('data-phase')] = anyClosed; });
    persist(); refresh();
  });

  // toolbar phase-status chips (distinct PHASE statuses, rendered server-side)
  wireChips(phaseStatusBar, 'data-ps', function (val, host, attr) {
    phaseStatus = (phaseStatus === val) ? '' : val;
    highlight(host, attr, phaseStatus);
    refresh();
  });

  // per-phase task-status chips (contextual — only that phase's task statuses)
  var tfHosts = [];
  phaseRows.forEach(function (pr) {
    var pid = pr.getAttribute('data-phase');
    var tfRow = tfOf(pid); if (!tfRow) return;
    var host = tfRow.querySelector('.tf-chips'); if (!host) return;
    tfHosts.push(host);
    wireChips(host, 'data-ts', function (val) {
      taskStatus[pid] = (taskStatus[pid] === val) ? '' : val;
      highlight(host, 'data-ts', taskStatus[pid]);
      refresh();
    });
  });

  // model chips (inside the More filters panel)
  wireChips(modelBar, 'data-m', function (val, host, attr) {
    modelFilter = (modelFilter === val) ? '' : val;
    highlight(host, attr, modelFilter);
    refresh();
  });

  // area chips (inside the More filters panel) — the phase-level gate.
  // highlight() paints exactly one active value; these chips hold a set, so
  // their painter reads membership instead.
