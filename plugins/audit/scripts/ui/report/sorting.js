  /**
   * Compare two cell strings in natural order, so `P2` sorts before `P10`.
   *
   * Each side is cut into alternating runs of digits and non-digits. A digit run
   * compares by value; a text run carries Infinity in the numeric slot, which is
   * what puts every number ahead of every word at the same position. The runs are
   * consumed in lockstep and the first difference decides; when one side runs out
   * first, the shorter string sorts first.
   *
   * @param {string} a - text of the cell on the left of the comparison
   * @param {string} b - text of the cell on the right of the comparison
   * @returns {number} below 0 when `a` sorts first, above 0 when `b` does, 0 when
   *   the two are indistinguishable
   */
  function natCmp(a, b) {
    const ax = [], bx = [];
    a.replace(/(\d+)|(\D+)/g, (_, n, s) => { ax.push([n === undefined ? Infinity : +n, s || '']); });
    b.replace(/(\d+)|(\D+)/g, (_, n, s) => { bx.push([n === undefined ? Infinity : +n, s || '']); });
    while (ax.length && bx.length) {
      const an = ax.shift(), bn = bx.shift();
      const c = (an[0] - bn[0]) || an[1].localeCompare(bn[1]);
      if (c) return c;
    }
    return ax.length - bx.length;
  }

  /**
   * Read one cell of a row as trimmed text.
   *
   * @param {HTMLTableRowElement} r - the row to read
   * @param {number} idx - zero-based column index
   * @returns {string} the cell's trimmed text, or '' when the row is that short
   */
  function cell(r, idx) { return r.cells[idx] ? r.cells[idx].textContent.trim() : ''; }

  /**
   * Make every header of a table a sort control over its own column.
   *
   * @param {HTMLTableElement|null} table - the table to wire; a missing one is a
   *   no-op, because a report can be rendered without this table at all
   * @param {boolean} withinPhase - true to reorder each phase's own task rows and
   *   leave the phases where they are, false to reorder the tbody as one list
   * @param {boolean} initial - true when the rows already arrive in the first
   *   column's ascending order, so that column is marked without being re-sorted
   * @returns {void}
   */
  function wireSort(table, withinPhase, initial) {
    if (!table) return;
    const ths = [...table.querySelectorAll('thead th')];
    ths.forEach((th, idx) => {
      // A column header that sorts on click is a control, so it has to be one:
      // reachable by Tab, operable by Enter/Space, and announcing its own state.
      // Without aria-sort the current order is conveyed by a CSS ::after arrow
      // alone, which a screen reader never sees.
      th.setAttribute('role', 'button');
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-sort', 'none');
      /**
       * Order the rows by this column, flipping direction when it already owns
       * the sort, and leave every other header reading as unsorted.
       * @returns {void}
       */
      const doSort = () => {
        const asc = th.getAttribute('data-sort') !== 'asc';
        ths.forEach((h) => {
          h.removeAttribute('data-sort');
          h.classList.remove('sorted');
          h.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('data-sort', asc ? 'asc' : 'desc');
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        th.classList.add('sorted');
        /** @type {(r1: HTMLTableRowElement, r2: HTMLTableRowElement) => number} */
        const cmp = (r1, r2) => (asc ? natCmp(cell(r1, idx), cell(r2, idx)) : natCmp(cell(r2, idx), cell(r1, idx)));
        if (withinPhase) {
          phaseRows.forEach((pr) => {
            const pid = pr.getAttribute('data-phase');
            const anchor = tfOf(pid) || pr;   // keep tasks after the phase + its task-filter row
            tasksOf(pid).slice().sort(cmp).reverse()
              .forEach((r) => { anchor.parentNode.insertBefore(r, anchor.nextSibling); });
          });
        } else {
          const body = table.tBodies[0];
          [...body.querySelectorAll('tr')].sort(cmp).forEach((r) => { body.appendChild(r); });
        }
        refresh();
      };
      th.addEventListener('click', doSort);
      th.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();   // Space would otherwise scroll the page
          doSort();
        }
      });
      // The table ARRIVES sorted — plan order, by id — so the first column says
      // so from the start. Marked, not re-sorted: the rows are already in that
      // order, and running the comparator at load would reorder a table that is
      // correct, and tear the phase/task grouping apart to do it.
      if (initial && idx === 0) {
        th.setAttribute('data-sort', 'asc');
        th.setAttribute('aria-sort', 'ascending');
        th.classList.add('sorted');
      }
    });
  }

  // --- the order the phases are listed in -------------------------------------

  /**
   * Every row that belongs to one phase, in the order the table has them NOW.
   *
   * Walked from the DOM rather than assembled from `tasksOf` and `tfOf`, and
   * that is not a preference: `wireSort` above permutes the task rows in the
   * table while deliberately leaving the index in document order (`.slice()`
   * before `.sort()`), so rebuilding a phase's block from the index would
   * silently undo a column sort the reader had just asked for.
   *
   * @param {HTMLTableRowElement} pr - the phase's group row
   * @returns {HTMLTableRowElement[]} the group row, its task-filter row, and
   *   its task and detail rows, in table order
   */
  function blockOf(pr) {
    const rows = [pr];
    for (let n = pr.nextElementSibling;
         n && !n.classList.contains('phase') && !n.classList.contains('seghead');
         n = n.nextElementSibling) rows.push(n);
    return rows;
  }

  /**
   * Re-order the phase blocks INSIDE each segment, leaving the segments and the
   * rows inside a phase where they are.
   *
   * Within a segment and not across the table, because the segments are already
   * an ordering by whether the work can run at all — active, then pending, then
   * the archive — and a done phase pinned first still cannot run. Sorting over
   * that would answer "what runs first" with a finished phase.
   *
   * @param {(pr: HTMLTableRowElement) => number} rank - the number to order a
   *   phase's group row by, ascending
   * @returns {void}
   */
  function orderPhaseBlocks(rank) {
    segRows.forEach((sh) => {
      const mine = phaseRows.filter((pr) => pr.__seg === sh.__seg);
      // Read every block BEFORE moving anything: the first insertBefore changes
      // the sibling chain the rest of the walks would have followed.
      const blocks = mine.map(blockOf);
      let anchor = sh;
      mine
        // The position in `phaseRows` is the tie-break, and `phaseRows` is the
        // order the page LOADED in — so `plan` is a rank of 0 for everything
        // and this restores the written plan exactly, with no second record of
        // it to keep in step.
        .map((pr, i) => [rank(pr), i])
        .sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]))
        .forEach((entry) => {
          blocks[entry[1]].forEach((r) => {
            anchor.parentNode.insertBefore(r, anchor.nextSibling);
            anchor = r;
          });
        });
    });
  }

  /**
   * The orders the phases table offers, by the name the control uses.
   *
   * `priority` reads `data-porder`, which `_priority.ranks` computed on the
   * server. The client is handed a NUMBER and never the rule: re-expressing
   * `sort_key` here is the one way the report's order could come to disagree
   * with the order the orchestrator actually walks, and there is nothing here
   * to disagree with it.
   *
   * @type {Object<string, (pr: HTMLTableRowElement) => number>}
   */
  const ORDERS = {
    plan: () => 0,
    priority: (pr) => +pr.getAttribute('data-porder'),
  };

  /**
   * Switch the phases table between the written plan and the priority overlay.
   *
   * Refuses an order it cannot honour rather than reordering by NaN: an unknown
   * name, or `priority` on a plan where the renderer emitted no ranks and so no
   * select. Both are reachable only from a hand-edited fragment, and a table
   * shuffled into an arbitrary order is worse than one that ignored the request.
   *
   * @param {string} v - order name; anything else is ignored
   * @returns {void}
   */
  function setPhaseOrder(v) {
    // `lookup`, because "anything else is ignored" was not true of five names:
    // `ORDERS['constructor']` is a function, so the guard passed and the table
    // was then sorted by `+pr.getAttribute(...)` of nothing - or rather by
    // whatever the inherited function returned, which is not a rank at all.
    if (!lookup(ORDERS, v) || !sortSel) return;
    phaseOrder = v;
    if (sortSel.value !== v) sortSel.value = v;
    orderPhaseBlocks(lookup(ORDERS, v));
    refresh();                       // which also writes the choice to the link
  }

  if (sortSel) {
    sortSel.value = phaseOrder;
    sortSel.addEventListener('change', () => setPhaseOrder(sortSel.value));
  }

