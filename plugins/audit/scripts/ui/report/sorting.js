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

