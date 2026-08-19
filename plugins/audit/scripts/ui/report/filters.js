  // --- filter state, and the pass that applies it ----------------------------

  // The filtered view, written back into the URL so it can be sent to someone.
  // `history.replaceState` and not an assignment to location.hash: assigning
  // pushes a history entry per keystroke and scrolls the document to whatever it
  // reads the fragment as. Wrapped, because History is refused on a file://
  // document in some browsers — which is where this report is most often opened,
  // and a filter that throws on every pass is a filter that does not run.
  //
  // Deliberately NOT encoded: the per-phase task-status chips. They are keyed by
  // phase id, so carrying them would put a list as long as the plan into the URL
  // to describe a drill-down inside one row. A link names the view, not the state
  // of every control on the page.
  // vw: the same state, written twice on purpose. The fragment is the SHAREABLE
  // copy; localStorage is the copy that survives a reload when History is
  // refused — which is the ordinary case for this file, because a report is
  // most often opened straight off disk over file://, and that is exactly where
  // filters used to vanish on every refresh.
  var STORE_KEY = 'audit-view-' + (document.title || 'report');
  function saveState(parts) {
    try {
      if (parts.length) localStorage.setItem(STORE_KEY, parts.join('&'));
      else localStorage.removeItem(STORE_KEY);
    } catch (e) {}
  }
  function syncHash() {
    var parts = [];
    function put(k, v) { if (v) parts.push(k + '=' + encodeURIComponent(v)); }
    put('v', viewMode === defaultView ? '' : viewMode);
    put('q', q ? q.value.trim() : '');
    put('ps', phaseStatus);
    // Space-joined, mirroring the data-area attribute — one separator rule for
    // both carriers of a tag list. `a` and `au` are distinct keys: the codec
    // above splits on '&' and the FIRST '=', so a key is always matched whole.
    put('a', areaFilter.join(' '));
    put('m', modelFilter);
    put('from', dFrom);
    put('to', dTo);
    put('au', auFilter);
    // Only where this report OWNS the toggle. Embedded as a fragment, the host
    // stamps data-theme on the same root, and a link carrying a theme would flip
    // the page AROUND the report rather than the report. And only alongside a
    // real filter: a theme alone must not mint a `#!` fragment, or simply opening
    // the report with a remembered theme would overwrite the heading you linked to.
    if (themeBtn && parts.length) put('th', root.getAttribute('data-theme') || '');
    saveState(parts);
    try {
      if (parts.length) history.replaceState(null, '', '#!' + parts.join('&'));
      else if ((location.hash || '').indexOf('#!') === 0) {
        // Strip only OUR fragment. A plain `#usage` belongs to the nav, and
        // clearing the filters has no business throwing away where you are.
        history.replaceState(null, '', location.pathname + location.search);
      }
    } catch (e) {}
  }

  function refresh() {
    var term = (q ? q.value : '').trim().toLowerCase();
    // Filters that narrow the TASKS inside a phase, rather than the phase list.
    // A phase none of whose tasks survive is not a phase that matches: keeping it
    // is the difference between "these four phases used opus" and "here are all
    // twelve, four of them usefully".
    var narrows = modelFilter !== '' || dFrom !== '' || dTo !== '';
    var anyFilter = narrows || term !== '' || phaseStatus !== ''
                    || areaFilter.length > 0;
    var visP = 0, visT = 0, totT = 0, hiddenByView = 0;
    var segVis = {};   // visible phases per segment, for the seghead painter
    phaseRows.forEach(function (pr) {
      var pid = pr.getAttribute('data-phase');
      var tasks = tasksOf(pid);
      var tf = taskStatus[pid] || '';
      var pText = textHit(pr, term);
      var anyTaskText = false, nMatch = 0;
      totT += tasks.length;
      tasks.forEach(function (t) {
        var tText = textHit(t, term);
        if (tText) anyTaskText = true;
        // Marked on the row rather than gathered into an array: this runs on
        // every keystroke over every task in the plan, and one array per phase
        // per pass is garbage the filter has no need to make.
        t.__hit = (pText || tText)
                  && (!tf || t.getAttribute('data-status') === tf)
                  && (!modelFilter || t.getAttribute('data-model') === modelFilter)
                  && dateOk(t);
        if (t.__hit) nMatch++;
      });
      // phase-level: status + area gates + text (phase title OR any task matches)
      var matchAll = (!phaseStatus || pr.getAttribute('data-status') === phaseStatus)
                  && areaOk(pr)
                  && (term === '' || pText || anyTaskText)
                  && (!narrows || nMatch > 0);
      var showP = matchAll
                  // vw: the view gates, and it gates ALWAYS. The old rule
                  // lifted the archive whenever a filter was on, which made
                  // the control a lie mid-search; matches the view hides are
                  // counted instead and announced under the table, with the
                  // way to see them.
                  && inView(pr.__seg);
      // vw: would this phase have shown in ALL? Counted before the view is
      // applied, so the note below can say what the reader is not seeing.
      if (matchAll && !showP) hiddenByView++;
      pr.style.display = showP ? '' : 'none';
      if (showP) {
        visP++; visT += nMatch;
        segVis[pr.__seg] = (segVis[pr.__seg] || 0) + 1;
      }
      // Manual state, and ONLY manual state. This used to OR the search term and
      // the per-phase task filter into the condition, so one character typed
      // into the filter threw every matching phase open at once: the page grew by
      // several screens, the row being read left the viewport, and clearing the
      // filter afterwards shut the phases that had been opened by hand. What a
      // filter owes the reader instead is a REASON to open a row, which is the
      // job the match badge below does.
      var open = showP && !!expanded[pid];
      setOpen(pr, open);
      var tfRow = tfOf(pid);
      // 'table-row', NOT '': clearing the inline style hands the row back to the
      // stylesheet, where `tr.taskfilter{display:none}` wins — so the per-phase
      // status filter was emitted into every report, populated by JS, and could
      // never be seen. `tr.task` survives the same pattern only because it has no
      // default display rule to fall back to.
      if (tfRow) tfRow.style.display = open ? 'table-row' : 'none';
      tasks.forEach(function (t) {
        var vis = open && t.__hit;
        t.style.display = vis ? '' : 'none';
        // ex: a detail row is visible only when its task is AND it was opened.
        // Kept open across a filter on purpose — a reader who opened a task and
        // then narrowed the table has not changed their mind about that task.
        if (t.__detail) t.__detail.hidden = !(vis && t.__open);
      });
      // "3 of 12 match" on a row that is closed and hiding its own evidence. Not
      // shown at rest, and not shown when everything matched — "12 of 12" is a
      // sentence that tells a reader nothing they did not already have.
      var badge = pr.__pmatch;
      if (badge) {
        var wanted = showP && !open && anyFilter && nMatch !== tasks.length;
        if (wanted) badge.textContent = nMatch + ' of ' + tasks.length + ' match';
        badge.hidden = !wanted;
      }
    });
    // A segment header follows its rows: a header over nothing says nothing.
    // (The archive's old exception — a header that stayed to announce what it
    // was hiding — belonged to the toggle, and the view select says it now.)
    segRows.forEach(function (sh) {
      sh.style.display = (segVis[sh.__seg] || 0) > 0 ? '' : 'none';
    });
    bugRows.forEach(function (b) { b.style.display = textHit(b, term) ? '' : 'none'; });

    if (count) {
      // Tasks as well as phases, now that a filter can narrow a phase from the
      // inside: with the model or date filters on, the phase count alone moves
      // hardly at all while the thing being counted moves a great deal.
      count.textContent = anyFilter
        ? (visP + ' / ' + phaseRows.length + ' phases · ' + visT + ' of ' + totT + ' tasks')
        : (phaseRows.length + ' phases');
    }
    // Filtered down to nothing, the table was an empty frame with no explanation
    // and no way back except undoing each control by hand.
    if (norow) norow.style.display = (anyFilter && visP === 0) ? 'table-row' : 'none';
    // vw: what the view is keeping off screen, said plainly, with the way to
    // see it. Silent when the view is already `all` — there is nothing outside it.
    if (outsideRow) {
      var show = hiddenByView > 0 && viewMode !== 'all';
      outsideRow.hidden = !show;
      outsideRow.style.display = show ? 'table-row' : 'none';
      if (show && outsideN) {
        outsideN.textContent = hiddenByView + (hiddenByView === 1
          ? ' phase matches outside this view'
          : ' phases match outside this view') + ' \u2014 ';
      }
    }
    // The toolbar copy appears the moment anything is filtering, so there is a way
    // back that does not depend on the table having rows left to draw it in.
    clearBtns.forEach(function (b) { b.hidden = !anyFilter; });
    // A filter folded away inside a closed <details> is how a reader concludes
    // rows are missing. The count on the summary says something is on.
    if (fcount) {
      var nHidden = (modelFilter ? 1 : 0) + ((dFrom || dTo) ? 1 : 0)
                    + (areaFilter.length ? 1 : 0);
      fcount.textContent = nHidden ? ' · ' + nHidden : '';
    }
    if (expandBtn) {
      var anyClosed = phaseRows.some(function (pr) { return !expanded[pr.getAttribute('data-phase')]; });
      expandBtn.textContent = anyClosed ? 'expand all' : 'collapse all';
    }
    // The usage views follow the same range the table just filtered by. Cheap
    // on a keystroke: it no-ops unless the range actually changed.
    applyUsageRange();
    syncHash();
  }

