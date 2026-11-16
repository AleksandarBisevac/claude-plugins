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
    // Beside the view for the same reason the view is here: a toolbar select is
    // part of the view somebody would send as a link, unlike a column-header
    // sort, which is a poke at one table. The default is omitted, so a report
    // nobody has re-ordered still mints no fragment of its own.
    put('so', phaseOrder === defaultOrder ? '' : phaseOrder);
    // Every axis under its own keys. The codec that reads the fragment splits
    // on '&' and the FIRST '=', so a key is always matched whole and `a`/`au`
    // or `tev`/`tevf` never read as one another.
    FILTER_AXES.forEach((axis) => {
      const vals = axis.encode();
      axis.keys.forEach((k, i) => { put(k, vals[i]); });
    });
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
   * The current view by its option's data-short, the bracket-free name the
   * phase count carries. Without one the option's full wording stands in,
   * which is still the true basis, merely longer.
   *
   * @returns {string} e.g. "active & pending"
   */
  const viewShort = () => {
    const opt = viewSel ? [...viewSel.options].find((o) => o.value === viewMode) : null;
    return (opt && opt.getAttribute('data-short')) || viewName();
  };
  // The count's view name: said to a screen reader, drawn to nobody (`.vh`).
  const countView = document.createElement('span');
  countView.className = 'vh';

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
    // FIRST, because it can clear a selection this pass then has to honour. The
    // chip set follows the view, and this is the only place every path that
    // changes the view arrives at: `setView` calls it, and so does the restore
    // that runs after a reload — which reads the view out of the fragment or
    // localStorage and never touches setView. Wiring it to setView alone left
    // the chips correct until the reader refreshed the page, which the report
    // gate caught by asserting after exactly that reload.
    syncStatusChips();
    const term = (q ? q.value : '').trim().toLowerCase();
    // Filters that narrow the TASKS inside a phase, rather than the phase list.
    // A phase none of whose tasks survive is not a phase that matches: keeping it
    // is the difference between "these four phases used opus" and "here are all
    // twelve, four of them usefully".
    //
    // Read off the registry, never listed here: a list written by hand is how
    // an axis came to filter the table while the counter and Clear ignored it.
    // `anyFilter` is about the TABLE, so the Usage-only author scope is not in
    // it; it still offers Clear below, which lifts every axis that is on.
    const live = FILTER_AXES.filter((axis) => axis.on());
    const narrows = live.some((axis) => axis.scope === 'tasks');
    const anyFilter = live.some((axis) => axis.scope !== 'usage');
    // `totT` and `visT` leave cancelled tasks out on BOTH sides of the
    // fraction, which is the header's own basis for its task total: a
    // denominator that counted what the header did not was a second number for
    // one question. `visX` is what that basis leaves out of the drawn phases -
    // cancelled tasks that match - so the count can name them instead of
    // calling a phase drawn for one of them a phase with no match. `outP`
    // counts the phases that match but sit outside the view, off the verdict
    // below rather than a second filter pass.
    let visP = 0, visT = 0, totT = 0, visX = 0, outP = 0;
    const outSegs = [];
    // Plain `{}` on purpose, and the one map here that keeps its prototype:
    // the key is `data-seg`, which Python's `_seg_of` emits from a closed
    // set of three words. Every other map in this report is keyed by a
    // manifest id, a status or a fragment value and is prototype-free.
    const segVis = {};   // visible phases per segment, for the seghead painter
    phaseRows.forEach((pr) => {
      const pid = pr.getAttribute('data-phase');
      const tasks = tasksOf(pid);
      const tf = taskStatus[pid] || '';
      const pText = textHit(pr, term);
      let anyTaskText = false, nMatch = 0, nCounted = 0, nLeftOut = 0;
      tasks.forEach((t) => {
        const counted = t.getAttribute('data-status') !== 'cancelled';
        if (counted) totT++;
        const tText = textHit(t, term);
        if (tText) anyTaskText = true;
        // Marked on the row rather than gathered into an array: this runs on
        // every keystroke over every task in the plan, and one array per phase
        // per pass is garbage the filter has no need to make.
        t.__hit = (pText || tText)
                  && (!tf || t.getAttribute('data-status') === tf)
                  && (!modelFilter || t.getAttribute('data-model') === modelFilter)
                  // Two clauses and not one: the status a run reached and the
                  // observations it made are separate questions, so selecting a
                  // status must not silently narrow by an observation as well.
                  && (!tevFilter || t.getAttribute('data-tev') === tevFilter)
                  && tevFlagOk(t)
                  && dateOk(t);
        if (t.__hit) {
          nMatch++;
          if (counted) nCounted++;
          else nLeftOut++;
        }
      });
      // phase-level: status + area gates + text (phase title OR any task matches)
      const matchAll = (!phaseStatus || pr.getAttribute('data-status') === phaseStatus)
                  && areaOk(pr)
                  && (term === '' || pText || anyTaskText)
                  && (!narrows || nMatch > 0);
      const showP = matchAll
                  // The view gates ALWAYS, filter or no filter. Lifting it
                  // whenever something was typed made the control a lie
                  // mid-search; matches the view hides are counted instead, and
                  // the empty state names them when they are all there is.
                  && inView(pr.__seg);
      pr.style.display = showP ? '' : 'none';
      if (showP) {
        visP++; visT += nCounted; visX += nLeftOut;
        segVis[pr.__seg] = (segVis[pr.__seg] || 0) + 1;
      }
      // A match the view is hiding: it would have shown under All phases.
      if (matchAll && !showP) {
        outP++;
        if (outSegs.indexOf(pr.__seg) === -1) outSegs.push(pr.__seg);
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
        if (t.__detail) {
          t.__detail.hidden = !(vis && t.__open);
          // A filter can reveal a detail row that was never toggled open by hand,
          // and the trim control has to be decided there too.
          if (!t.__detail.hidden) syncClamp(t.__detail);
        }
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
      // The view is the basis at rest as well as filtered: "165 phases" over a
      // table showing five read as the size of the table, and the view was why
      // it was not. The count is a live region, so a screen reader hears it
      // without the select beside it, and it names the view by the option's
      // short name - inside a box clipped to nothing, because a sighted reader
      // has the View select right beside it, and drawn, the name wrapped the
      // pinned bar at a laptop width once anything filtered. Tasks join the
      // phases once something filters, since a filter can narrow a phase from
      // the inside while the phase count barely moves. The cancelled tasks the
      // task fraction leaves out of the drawn phases are named as left out,
      // which stays true whichever filter drew them: called "matches", the
      // clause claimed tasks in phases no filter had touched.
      count.textContent = visP + ' of ' + plural(phaseRows.length, 'phase');
      countView.textContent = ' · ' + viewShort();
      count.appendChild(countView);
      if (anyFilter) {
        count.appendChild(document.createTextNode(' · ' + visT + ' of ' + plural(totT, 'task')
          + (visX ? ', ' + visX + ' cancelled not counted' : '')));
      }
    }
    // Filtered down to nothing, the table was an empty frame with no explanation
    // and no way back except undoing each control by hand.
    const empty = anyFilter && visP === 0;
    if (norow) norow.style.display = empty ? 'table-row' : 'none';
    // Which of its two sentences is true. "No phase matches these filters" is
    // false when the VIEW hides every match, so then the slot says how many
    // phases outside it do, by segment, and offers the press that shows them.
    // Only inside the empty state: a standing notice over drawn rows was removed
    // on the reader's second request, because it argued with a view they had
    // just chosen.
    if (norowOutside) {
      norowOutside.hidden = !(empty && outP > 0);
      if (norowSays) norowSays.hidden = empty && outP > 0;
      if (norowOutsideSays && empty && outP > 0) {
        const segs = ['active', 'pending', 'archived']
          .filter((sg) => outSegs.indexOf(sg) !== -1).join(' or ');
        norowOutsideSays.textContent = 'No phase in ' + viewName() + ' matches — '
          + plural(outP, segs + ' phase does', segs + ' phases do');
      }
    }
    // The toolbar copy appears the moment anything is filtering, so there is a way
    // back that does not depend on the table having rows left to draw it in.
    clearBtns.forEach((b) => { b.hidden = !live.length; });
    // A filter folded away inside a closed <details> is how a reader concludes
    // rows are missing. The count on the summary says something is on.
    if (fcount) {
      const nHidden = live.filter((axis) => axis.counts).length;
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

  // Show all phases takes the View control's own path - the select set and its
  // change dispatched - so the stored view, the link and the select cannot
  // disagree about what is on screen.
  //
  // Both buttons of the empty state hide the row they sit in, so each hands
  // the keyboard to the View select on the way out: a focus left on a hidden
  // button sends the next Tab past the whole table. The select is the control
  // that says which phases are now drawn. The Clear here is the second copy of
  // the toolbar's, whose own press is wired with the others in date-range.js;
  // only the empty state's copy moves focus, because only it disappears.
  if (showAllBtn && viewSel) {
    showAllBtn.addEventListener('click', () => {
      viewSel.value = 'all';
      viewSel.dispatchEvent(new Event('change'));
      viewSel.focus();
    });
  }
  if (norowClear && viewSel) {
    norowClear.addEventListener('click', () => { viewSel.focus(); });
  }
