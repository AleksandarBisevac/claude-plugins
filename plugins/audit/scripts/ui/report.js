
(function () {
  var q = document.getElementById('audit-q');
  // First, before anything below can throw: the page is running scripts, so drop
  // the banner that says it is not. Deliberately ahead of every other statement —
  // if a later line fails, the banner staying up is then TRUE and useful, because
  // the interactive layer really is dead.
  var _nojs = document.getElementById('audit-nojs');
  if (_nojs && _nojs.parentNode) _nojs.parentNode.removeChild(_nojs);

  // A filtered view of this report is a LINK. Read here, written by syncHash()
  // below. The `#!` prefix is not decoration: the side nav's links are plain
  // fragments over the same slot, and without a marker separating the two,
  // restoring filter state and following a heading link would each undo the other.
  var HASH = {};
  (function () {
    var h = location.hash || '';
    if (h.indexOf('#!') !== 0) return;
    h.slice(2).split('&').forEach(function (pair) {
      if (!pair) return;
      var i = pair.indexOf('=');
      var k = i < 0 ? pair : pair.slice(0, i);
      var v = i < 0 ? '' : pair.slice(i + 1);
      try { HASH[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { HASH[k] = ''; }
    });
  })();

  var count = document.getElementById('audit-count');
  var phaseStatusBar = document.getElementById('audit-phase-status');
  var expandBtn = document.getElementById('audit-expand');
  var grouped = document.querySelector('table.phases');
  var bugsTable = document.querySelector('table.bugs');

  // Theme: follow the OS by default; the toolbar toggle overrides + persists.
  var root = document.documentElement;
  var themeBtn = document.getElementById('audit-theme');
  var THEME_KEY = 'audit-report-theme';
  function prefersDark() { return window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches; }
  function isDark() { var t = root.getAttribute('data-theme'); return t ? t === 'dark' : prefersDark(); }
  function paintTheme() { if (themeBtn) themeBtn.textContent = isDark() ? '☀' : '☾'; }
  // Restore only when this report owns the toggle. Embedded (no button), the host
  // sets data-theme and must win; restoring a value saved on some earlier visit
  // would silently override the theme the viewer is actually looking at. A page
  // that does not offer the control has no business reinstating its state.
  if (themeBtn) {
    try { var savedTheme = localStorage.getItem(THEME_KEY); if (savedTheme) root.setAttribute('data-theme', savedTheme); } catch (e) {}
    // A theme carried in the link beats one saved on an earlier visit: whoever
    // sent this URL chose how it should be read, and they chose more recently.
    if (HASH.th === 'dark' || HASH.th === 'light') root.setAttribute('data-theme', HASH.th);
  }
  paintTheme();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var next = isDark() ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    paintTheme();
    syncHash();
  });

  // The sticky stack, measured rather than assumed. --topbar-h decides where the
  // nav strip, the filter bar, the column headers and every anchor land, and it
  // depends on things a stylesheet cannot know: how far the title wraps, how tall
  // the strip is at this width, what text size the reader chose. The CSS values
  // are the no-JS fallback; these are the truth.
  var toolbar = document.querySelector('.topbar');
  var snav = document.querySelector('.snav');
  // Only the horizontal strip stacks UNDER the bar. Above 72rem the same nav is a
  // column beside the content and adds nothing to what follows it, so the query
  // that switches the presentation is the one that decides whether it counts.
  var stripQ = window.matchMedia ? matchMedia('(max-width:72rem)') : null;
  function px(el) { return el ? Math.round(el.getBoundingClientRect().height) : 0; }
  function measureStack() {
    if (toolbar) root.style.setProperty('--topbar-h', px(toolbar) + 'px');
    root.style.setProperty('--strip-h',
      (snav && stripQ && stripQ.matches ? px(snav) : 0) + 'px');
    var st = document.querySelector('.sectools');
    if (st) root.style.setProperty('--sectools-h', px(st) + 'px');
  }
  measureStack();
  if (window.ResizeObserver) {
    var ro = new ResizeObserver(measureStack);
    [toolbar, snav, document.querySelector('.sectools')].forEach(function (el) { if (el) ro.observe(el); });
  }
  window.addEventListener('resize', measureStack, { passive: true });

  // Scroll-spy. The links work without any of this — they are plain anchors
  // rendered server-side — so this only adds the half a nav cannot do statically:
  // saying where you ARE. Without it the sidebar is a menu; with it, a position.
  //
  // This was an IntersectionObserver watching each target inside a 15%-30% band of
  // the viewport. Most of those targets are <h2> elements a line and a half tall,
  // so at any given scroll position usually NONE of them was inside the band and
  // the nav marked nothing at all — the state existed and was almost never shown.
  // Position is not a question about visibility, it is a question about order:
  // whichever heading most recently passed under the bar is the one being read.
  var navLinks = [].slice.call(document.querySelectorAll('.snav a'));
  var spyTargets = navLinks.map(function (a) {
    try { return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1))); }
    catch (e) { return null; }
  });
  function markSpy() {
    if (!navLinks.length) return;
    var fold = px(toolbar) + (snav && stripQ && stripQ.matches ? px(snav) : 0) + 4;
    var best = -1;
    spyTargets.forEach(function (el, i) {
      if (el && el.getBoundingClientRect().top <= fold) best = i;
    });
    if (best < 0) best = 0;   // above the first heading, the first link still answers
    // At the end of the document nothing further can cross the fold, so a short
    // final section would otherwise be unreachable by the marker.
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      for (var j = spyTargets.length - 1; j >= 0; j--) { if (spyTargets[j]) { best = j; break; } }
    }
    navLinks.forEach(function (a, i) {
      if (i === best) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
  }

  // One scroll listener drives the marker and BOTH bars' elevation, coalesced to a
  // frame: scroll fires far faster than the screen repaints.
  var ticking = false;
  var sectools = document.querySelector('.sectools');
  function onScroll() {
    if (toolbar) toolbar.classList.toggle('scrolled', (window.scrollY || 0) > 8);
    // The filter bar is stuck when its own top has reached the offset it is stuck
    // AT, which the stylesheet computed from --sticky-2 and the browser has already
    // resolved to pixels. Asking for it rather than recomputing the stack here
    // keeps one definition of where this bar sits: the CSS. `scrollY > n` would be
    // wrong the moment anything above the table changes height, which is most of
    // what the top of this report does.
    // Three conditions, and the two beyond the obvious one are both states this
    // bar really reaches. It stops being sticky at all on a narrow screen with the
    // filter panel open (see the 52rem block), where `top` is `auto` and there is
    // nothing to be stuck against. And sticky only holds while its section is in
    // view: scroll past the phases table and the bar goes with it, leaving a top
    // far ABOVE the stick line — which the first version read as "stuck" and
    // elevated an element nobody could see.
    if (sectools) {
      var cs = getComputedStyle(sectools);
      var stickAt = parseFloat(cs.top);
      var sr = sectools.getBoundingClientRect();
      sectools.classList.toggle('stuck',
        cs.position === 'sticky' && sr.top <= stickAt + 1 && sr.bottom > stickAt);
    }
    markSpy();
  }
  window.addEventListener('scroll', function () {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { ticking = false; onScroll(); });
  }, { passive: true });
  window.addEventListener('hashchange', markSpy);
  onScroll();

  // No early return here. The print button, the markdown download, the copy
  // buttons and the whole chart tooltip layer have nothing to do with the phases
  // table, and a single `if (!grouped) return` above them took all of them down
  // together whenever that one element was absent. Everything below degrades to a
  // no-op instead: an empty phaseRows makes every loop over it vacuous.
  var phaseRows = grouped ? [].slice.call(grouped.querySelectorAll('tbody tr.phase')) : [];
  var bugRows = bugsTable ? [].slice.call(bugsTable.querySelectorAll('tbody tr')) : [];

  // Expand state persists across filtering AND page reload (best-effort;
  // localStorage may be unavailable on file:// in some browsers).
  var STORE = 'audit-report-expanded:' + (document.title || 'report');
  var expanded = {};
  try { expanded = JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) {}
  function persist() { try { localStorage.setItem(STORE, JSON.stringify(expanded)); } catch (e) {} }

  var phaseStatus = '';   // toolbar: filter which PHASES show, by phase status
  var taskStatus = {};    // per phase: filter that phase's TASKS, by task status
  var modelFilter = '';   // panel: only tasks run by this model
  var dFrom = '', dTo = '';  // panel: ISO dates, compared as plain strings
  var preset = '';        // which relative-span chip is lit, if any

  var modelBar = document.getElementById('audit-model');
  var fromInput = document.getElementById('audit-from');
  var toInput = document.getElementById('audit-to');
  var presetBar = document.getElementById('audit-presets');
  var fcount = document.getElementById('audit-fcount');
  var clearBtns = [].slice.call(document.querySelectorAll('[data-clear]'));
  var norow = grouped ? grouped.querySelector('tr.norows') : null;

  function esc(v) { return (window.CSS && CSS.escape) ? CSS.escape(v) : v; }
  // Indexed ONCE, not per call. These were `querySelectorAll` per phase, and
  // refresh() calls them inside a loop over phases — so one keystroke in the filter
  // ran 200 selector queries across a 4200-row tbody, roughly 840,000 node visits,
  // and it ran again on the next keystroke. That is the whole superlinear cliff
  // between 100 phases (41ms) and 200 (145ms, and 200ms for the first press).
  // Sorting reorders these rows but never replaces them, so an index of element
  // references stays correct across a sort.
  // The newest day this plan has any record of. The relative presets measure back
  // from HERE and never from the wall clock: "the last 30 days" read off the
  // system clock answers a different question every morning, and it would make the
  // committed example a file that cannot stay byte-equal to itself between two CI
  // runs — which is exactly what ci.yml compares docs/index.html against.
  var DMAX = '';
  var TASKS = {}, TFROW = {};
  if (grouped) {
    [].forEach.call(grouped.querySelectorAll('tbody tr.task'), function (t) {
      var k = t.getAttribute('data-phase');
      (TASKS[k] || (TASKS[k] = [])).push(t);
      var d = t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
      if (d > DMAX) DMAX = d;
    });
    [].forEach.call(grouped.querySelectorAll('tbody tr.taskfilter'), function (t) {
      TFROW[t.getAttribute('data-phase')] = t;
    });
  }
  // Resolved once, with everything else that refresh() would otherwise have to
  // look up per phase per keystroke.
  phaseRows.forEach(function (pr) { pr.__pmatch = pr.querySelector('.pmatch'); });
  function tasksOf(pid) { return TASKS[pid] || []; }
  function tfOf(pid) { return TFROW[pid] || null; }
  // Lowercased once per row and kept. The text of a rendered report never changes,
  // so re-lowercasing 4200 rows on every keystroke was work with a constant answer.
  function hay(r) {
    var v = r.__auditText;
    if (v === undefined) { v = r.textContent.toLowerCase(); r.__auditText = v; }
    return v;
  }
  function textHit(r, term) { return !term || hay(r).indexOf(term) !== -1; }
  function setOpen(pr, open) { pr.classList.toggle('open', !!open); pr.setAttribute('aria-expanded', open ? 'true' : 'false'); }

  // The date this task SHOWS in the table: completed if it is, else started.
  // Filtering on a date other than the one printed in the row reads as a bug the
  // first time a reader checks one against the other.
  function taskDate(t) {
    return t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
  }
  function dateOk(t) {
    if (!dFrom && !dTo) return true;
    var d = taskDate(t);
    // A task with no dates at all is not "inside every range"; it is unknown, and
    // a date filter is a question it has no answer to.
    if (!d) return false;
    // Plain string comparison. Fixed-width ISO dates order lexicographically, and
    // <input type=date> hands back exactly that shape — so a range test over four
    // thousand rows costs no Date parsing at all.
    return (!dFrom || d >= dFrom) && (!dTo || d <= dTo);
  }

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
  function syncHash() {
    var parts = [];
    function put(k, v) { if (v) parts.push(k + '=' + encodeURIComponent(v)); }
    put('q', q ? q.value.trim() : '');
    put('ps', phaseStatus);
    put('m', modelFilter);
    put('from', dFrom);
    put('to', dTo);
    // Only where this report OWNS the toggle. Embedded as a fragment, the host
    // stamps data-theme on the same root, and a link carrying a theme would flip
    // the page AROUND the report rather than the report. And only alongside a
    // real filter: a theme alone must not mint a `#!` fragment, or simply opening
    // the report with a remembered theme would overwrite the heading you linked to.
    if (themeBtn && parts.length) put('th', root.getAttribute('data-theme') || '');
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
    var anyFilter = narrows || term !== '' || phaseStatus !== '';
    var visP = 0, visT = 0, totT = 0;
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
      // phase-level: phase-status filter + text (phase title OR any task matches)
      var showP = (!phaseStatus || pr.getAttribute('data-status') === phaseStatus)
                  && (term === '' || pText || anyTaskText)
                  && (!narrows || nMatch > 0);
      pr.style.display = showP ? '' : 'none';
      if (showP) { visP++; visT += nMatch; }
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
      tasks.forEach(function (t) { t.style.display = (open && t.__hit) ? '' : 'none'; });
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
    // The toolbar copy appears the moment anything is filtering, so there is a way
    // back that does not depend on the table having rows left to draw it in.
    clearBtns.forEach(function (b) { b.hidden = !anyFilter; });
    // A filter folded away inside a closed <details> is how a reader concludes
    // rows are missing. The count on the summary says something is on.
    if (fcount) {
      var nHidden = (modelFilter ? 1 : 0) + ((dFrom || dTo) ? 1 : 0);
      fcount.textContent = nHidden ? ' · ' + nHidden : '';
    }
    if (expandBtn) {
      var anyClosed = phaseRows.some(function (pr) { return !expanded[pr.getAttribute('data-phase')]; });
      expandBtn.textContent = anyClosed ? 'expand all' : 'collapse all';
    }
    syncHash();
  }

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

  function wireSort(table, withinPhase) {
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
    });
  }

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

  // The More-filters panel closes on an outside click and on Escape. A <details>
  // natively closes only through its own summary, so a reader who opens it,
  // picks a filter and moves on leaves it hanging over the table — and it is
  // absolutely positioned, so it covers rows that have nothing to do with it.
  //
  // Clicking the summary to OPEN is not caught by this: the toggle is the click's
  // default action and runs after the event has finished bubbling, so at this
  // point the element is still closed and the query below finds nothing. Clicking
  // the summary to CLOSE is inside `contains`, so it is left to the native
  // behaviour rather than being closed twice. Clicks inside the panel — a chip, a
  // date field — are `contains` too, so changing a filter never dismisses the
  // thing you are changing it in.
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
    if (presetBar) highlight(presetBar, 'data-days', preset);
  }
  function onDateInput() {
    dFrom = fromInput ? fromInput.value : '';
    dTo = toInput ? toInput.value : '';
    preset = '';                       // a hand-picked range is no longer a preset
    if (presetBar) highlight(presetBar, 'data-days', '');
    refresh();
  }
  if (fromInput) fromInput.addEventListener('change', onDateInput);
  if (toInput) toInput.addEventListener('change', onDateInput);

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
    if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', '');
    if (modelBar) highlight(modelBar, 'data-m', '');
    // Clearing the state without unlighting these would leave rows claiming a
    // filter that no longer applies to them.
    tfHosts.forEach(function (h) { highlight(h, 'data-ts', ''); });
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
      if (s.hasAttribute('title')) {
        claim(s, s.getAttribute('title')); s.removeAttribute('title');
      }
      Array.prototype.forEach.call(s.querySelectorAll('[title]'), function (n) {
        claim(n, n.getAttribute('title')); n.removeAttribute('title');
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
    // Delegated: three listeners instead of one per mark. A dense report carries
    // well over a thousand hoverable marks, and binding each of them is a cost
    // paid on every page load to serve one hover at a time.
    function owner(node) {
      for (var n = node; n && n !== document; n = n.parentNode) {
        if (n.__tip) return n;
      }
      return null;
    }
    var current = null;
    document.addEventListener('mouseover', function (ev) {
      var m = owner(ev.target);
      if (m === current) return;
      current = m;
      if (!m) { box.hidden = true; return; }
      fill(m.__tip); box.hidden = false; place(ev);
    });
    document.addEventListener('mousemove', function (ev) {
      if (current) place(ev);
    });
    // Printing a floating tooltip would stamp it onto the page.
    window.addEventListener('beforeprint', function () {
      box.hidden = true; current = null;
    });
  })();

  // Download the Markdown twin (embedded as base64, decoded to a Blob).
  // Copy the run command. clipboard.writeText is unavailable on file:// in some
  // browsers, which is exactly where this report is most often opened, so the
  // fallback selects the text and lets the reader use their own copy key rather
  // than failing silently and leaving a button that does nothing.
  [].slice.call(document.querySelectorAll('.btn-copy')).forEach(function (b) {
    b.addEventListener('click', function () {
      var text = b.getAttribute('data-copy') || '';
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy'; }, 1600); };
      try {
        navigator.clipboard.writeText(text).then(done, function () { selectRun(b); });
      } catch (e) { selectRun(b); }
    });
  });
  function selectRun(btn) {
    var code = btn.parentNode.querySelector('.vd-run');
    if (!code) return;
    var r = document.createRange(); r.selectNodeContents(code);
    var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    btn.textContent = 'Press to copy';
    setTimeout(function () { btn.textContent = 'Copy'; }, 2400);
  }

  var dlBtn = document.getElementById('audit-dl-md');
  if (dlBtn) dlBtn.addEventListener('click', function () {
    try {
      var bin = atob(window.AUDIT_MD_B64 || '');
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var url = URL.createObjectURL(new Blob([bytes], { type: 'text/markdown;charset=utf-8' }));
      var a = document.createElement('a');
      a.href = url; a.download = (window.AUDIT_MD_NAME || 'audit-report.md');
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {}
  });

  wireSort(grouped, true);
  wireSort(bugsTable, false);
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
  if (q && HASH.q) q.value = HASH.q;
  if (HASH.ps) {
    phaseStatus = HASH.ps;
    if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', phaseStatus);
  }
  if (HASH.m) {
    modelFilter = HASH.m;
    if (modelBar) highlight(modelBar, 'data-m', modelFilter);
  }
  if (HASH.from || HASH.to) { dFrom = HASH.from || ''; dTo = HASH.to || ''; paintDates(); }
  refresh();
})();
