  // --- filter state, and the pass that applies it ----------------------------

  // The storage key for the encoded view, scoped by document title so two
  // reports opened from the same disk do not overwrite each other's filters.
  const STORE_KEY = 'audit-view-' + (document.title || 'report');

  /**
   * Write the encoded filter state to local storage, or clear it when nothing
   * is filtering.
   *
   * This is the copy of the view that survives a reload when History is
   * refused, which is the ordinary case here: a report is most often opened
   * straight off disk over `file://`, and that is exactly where filters used to
   * vanish on every refresh. Storage is best-effort on an opaque origin, so the
   * call is wrapped — a filter that throws on every pass is a filter that does
   * not run.
   *
   * @param {string[]} parts Encoded `key=value` pairs, already URL-escaped. An
   *   empty list removes the stored entry rather than storing an empty string.
   * @returns {void}
   */
  function saveState(parts) {
    if (parts.length) storageSet(STORE_KEY, parts.join('&'));
    else storageDrop(STORE_KEY);
  }

  /**
   * Encode the current filter state into the URL fragment and into storage, so
   * the filtered view can be sent to someone and survives a reload.
   *
   * `history.replaceState` and not an assignment to `location.hash`: assigning
   * pushes a history entry per keystroke and scrolls the document to whatever
   * it reads the fragment as. The call is wrapped because History is refused on
   * a `file://` document in some browsers, which is where this report is most
   * often opened.
   *
   * The per-phase task-status chips are deliberately not encoded. They are
   * keyed by phase id, so carrying them would put a list as long as the plan
   * into the URL to describe a drill-down inside one row. A link names the
   * view, not the state of every control on the page.
   *
   * @returns {void}
   */
  function syncHash() {
    const parts = [];
    /**
     * Append one encoded `key=value` pair, skipping empty values.
     *
     * @param {string} k Fragment key.
     * @param {string} v Raw value; a falsy value is omitted entirely, which is
     *   what keeps a default-valued control out of the link.
     * @returns {void}
     */
    function put(k, v) { if (v) parts.push(k + '=' + encodeURIComponent(v)); }
    put('v', viewMode === defaultView ? '' : viewMode);
    put('q', q ? q.value.trim() : '');
    put('ps', phaseStatus);
    // Space-joined, mirroring the data-area attribute — one separator rule for
    // both carriers of a tag list. `a` and `au` are distinct keys: the codec
    // that reads the fragment splits on '&' and the FIRST '=', so a key is
    // always matched whole.
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

  /**
   * Apply every filter to the whole table in one pass, then repaint the counts,
   * the empty state, the toolbar and the usage views.
   *
   * This is the single refresh every other feature triggers — a keystroke, a
   * chip, a date, a sort — so it runs over every phase and every task in the
   * plan on each call. It therefore reads only state that was resolved once up
   * front and marks its verdicts on the rows themselves; gathering matches into
   * per-phase arrays would be garbage this pass has no need to make.
   *
   * @returns {void}
   */
  function refresh() {
    const term = (q ? q.value : '').trim().toLowerCase();
    // Filters that narrow the TASKS inside a phase, rather than the phase list.
    // A phase none of whose tasks survive is not a phase that matches: keeping it
    // is the difference between "these four phases used opus" and "here are all
    // twelve, four of them usefully".
    const narrows = modelFilter !== '' || dFrom !== '' || dTo !== '';
    const anyFilter = narrows || term !== '' || phaseStatus !== ''
                    || areaFilter.length > 0;
    let visP = 0, visT = 0, totT = 0, hiddenByView = 0;
    const segVis = {};   // visible phases per segment, for the seghead painter
    phaseRows.forEach((pr) => {
      const pid = pr.getAttribute('data-phase');
      const tasks = tasksOf(pid);
      const tf = taskStatus[pid] || '';
      const pText = textHit(pr, term);
      let anyTaskText = false, nMatch = 0;
      totT += tasks.length;
      tasks.forEach((t) => {
        const tText = textHit(t, term);
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
      const matchAll = (!phaseStatus || pr.getAttribute('data-status') === phaseStatus)
                  && areaOk(pr)
                  && (term === '' || pText || anyTaskText)
                  && (!narrows || nMatch > 0);
      const showP = matchAll
                  // The view gates ALWAYS, filter or no filter. Lifting it
                  // whenever something was typed made the control a lie
                  // mid-search; matches the view hides are counted instead and
                  // announced under the table, with the way to see them.
                  && inView(pr.__seg);
      // Would this phase have shown in ALL? Counted before the view is applied,
      // so the note below can say what the reader is not seeing.
      if (matchAll && !showP) hiddenByView++;
      pr.style.display = showP ? '' : 'none';
      if (showP) {
        visP++; visT += nMatch;
        segVis[pr.__seg] = (segVis[pr.__seg] || 0) + 1;
      }
      // Manual state, and ONLY manual state. Or-ing the search term and the
      // per-phase task filter into this condition threw every matching phase
      // open on the first character typed: the page grew by several screens,
      // the row being read left the viewport, and clearing the filter afterwards
      // shut the phases that had been opened by hand. What a filter owes the
      // reader instead is a REASON to open a row, which is the job the match
      // badge below does.
      const open = showP && !!expanded[pid];
      setOpen(pr, open);
      const tfRow = tfOf(pid);
      // 'table-row', NOT '': clearing the inline style hands the row back to the
      // stylesheet, where `tr.taskfilter{display:none}` wins — so the per-phase
      // status filter was emitted into every report, populated by JS, and could
      // never be seen. `tr.task` survives the same pattern only because it has no
      // default display rule to fall back to.
      if (tfRow) tfRow.style.display = open ? 'table-row' : 'none';
      tasks.forEach((t) => {
        const vis = open && t.__hit;
        t.style.display = vis ? '' : 'none';
        // A detail row is visible only when its task is AND it was opened. Kept
        // open across a filter on purpose — a reader who opened a task and then
        // narrowed the table has not changed their mind about that task.
        if (t.__detail) t.__detail.hidden = !(vis && t.__open);
      });
      // "3 of 12 match" on a row that is closed and hiding its own evidence. Not
      // shown at rest, and not shown when everything matched — "12 of 12" is a
      // sentence that tells a reader nothing they did not already have.
      const badge = pr.__pmatch;
      if (badge) {
        const wanted = showP && !open && anyFilter && nMatch !== tasks.length;
        if (wanted) badge.textContent = nMatch + ' of ' + tasks.length + ' match';
        badge.hidden = !wanted;
      }
    });
    // A segment header follows its rows: a header over nothing says nothing.
    segRows.forEach((sh) => {
      sh.style.display = (segVis[sh.__seg] || 0) > 0 ? '' : 'none';
    });
    bugRows.forEach((b) => { b.style.display = textHit(b, term) ? '' : 'none'; });

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
    // What the view is keeping off screen, said plainly, with the way to see it.
    // Silent when the view is already `all` — there is nothing outside it.
    if (outsideRow) {
      const show = hiddenByView > 0 && viewMode !== 'all';
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
    clearBtns.forEach((b) => { b.hidden = !anyFilter; });
    // A filter folded away inside a closed <details> is how a reader concludes
    // rows are missing. The count on the summary says something is on.
    if (fcount) {
      const nHidden = (modelFilter ? 1 : 0) + ((dFrom || dTo) ? 1 : 0)
                    + (areaFilter.length ? 1 : 0);
      fcount.textContent = nHidden ? ' · ' + nHidden : '';
    }
    if (expandBtn) {
      const anyClosed = phaseRows.some((pr) => !expanded[pr.getAttribute('data-phase')]);
      expandBtn.textContent = anyClosed ? 'expand all' : 'collapse all';
    }
    // The usage views follow the same range the table just filtered by. Cheap
    // on a keystroke: it no-ops unless the range actually changed.
    applyUsageRange();
    syncHash();
  }
