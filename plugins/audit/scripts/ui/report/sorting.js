  function natCmp(a, b) {
    var ax = [], bx = [];
    a.replace(/(\d+)|(\D+)/g, function (_, n, s) { ax.push([n === undefined ? Infinity : +n, s || '']); });
    b.replace(/(\d+)|(\D+)/g, function (_, n, s) { bx.push([n === undefined ? Infinity : +n, s || '']); });
    while (ax.length && bx.length) {
      var an = ax.shift(), bn = bx.shift();
      var c = (an[0] - bn[0]) || an[1].localeCompare(bn[1]);
      if (c) return c;
    }
    return ax.length - bx.length;
  }
  function cell(r, idx) { return r.cells[idx] ? r.cells[idx].textContent.trim() : ''; }

  function wireSort(table, withinPhase, initial) {
    if (!table) return;
    var ths = table.querySelectorAll('thead th');
    [].forEach.call(ths, function (th, idx) {
      // A column header that sorts on click is a control, so it has to be one:
      // reachable by Tab, operable by Enter/Space, and announcing its own state.
      // Without aria-sort the current order is conveyed by a CSS ::after arrow
      // alone, which a screen reader never sees.
      th.setAttribute('role', 'button');
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-sort', 'none');
      var doSort = function () {
        var asc = th.getAttribute('data-sort') !== 'asc';
        [].forEach.call(ths, function (h) {
          h.removeAttribute('data-sort');
          h.classList.remove('sorted');
          h.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('data-sort', asc ? 'asc' : 'desc');
        th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
        th.classList.add('sorted');
        var cmp = function (r1, r2) { return asc ? natCmp(cell(r1, idx), cell(r2, idx)) : natCmp(cell(r2, idx), cell(r1, idx)); };
        if (withinPhase) {
          phaseRows.forEach(function (pr) {
            var pid = pr.getAttribute('data-phase');
            var anchor = tfOf(pid) || pr;   // keep tasks after the phase + its task-filter row
            tasksOf(pid).slice().sort(cmp).reverse()
              .forEach(function (r) { anchor.parentNode.insertBefore(r, anchor.nextSibling); });
          });
        } else {
          var body = table.tBodies[0];
          [].slice.call(body.querySelectorAll('tr')).sort(cmp).forEach(function (r) { body.appendChild(r); });
        }
        refresh();
      };
      th.addEventListener('click', doSort);
      th.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();   // Space would otherwise scroll the page
          doSort();
        }
      });
      // so (F-P-4): the table ARRIVES sorted — plan order, by id — and until
      // now nothing said so. The marker appeared on the first click, which
      // taught every reader that the column they were looking at was unsorted.
      // Marked, not re-sorted: the rows are already in this order, and running
      // the comparator at load would reorder a table that is correct (and
      // would tear the phase/task grouping apart to do it).
      if (initial && idx === 0) {
        th.setAttribute('data-sort', 'asc');
        th.setAttribute('aria-sort', 'ascending');
        th.classList.add('sorted');
      }
    });
  }

