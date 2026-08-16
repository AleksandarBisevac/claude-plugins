
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
  // Area chips (D1): a PHASE-level gate like phaseStatus, not a task narrower —
  // `data-area` lives on the phase row and tasks carry none. Multi-select,
  // unlike every filter above, because areas are how one plan holds several
  // subsystems and "the backend AND the web work" is a view someone actually
  // wants; a phase shows when ANY of its tags is selected. While a selection is
  // active a phase with no tags has no answer to the question being asked and
  // is hidden — the same reasoning dateOk applies to a task without dates.
  var areaFilter = [];    // panel: selected area tags, in click order

  var modelBar = document.getElementById('audit-model');
  var areaBar = document.getElementById('audit-areas');
  var fromInput = document.getElementById('audit-from');
  var toInput = document.getElementById('audit-to');
  var presetBar = document.getElementById('audit-presets');
  var fcount = document.getElementById('audit-fcount');
  var clearBtns = [].slice.call(document.querySelectorAll('[data-clear]'));
  var norow = grouped ? grouped.querySelector('tr.norows') : null;
  var outsideRow = grouped ? grouped.querySelector('[data-outside]') : null;
  var outsideN = outsideRow ? outsideRow.querySelector('[data-outside-n]') : null;
  // The author chips (C3) live in the Usage section and scope ONLY it: tasks
  // record no author, so these never enter refresh() or touch the task table.
  var authorBar = document.getElementById('audit-authors');
  var auNote = document.getElementById('audit-au-note');
  var auFilter = '';
  var smCells = [].slice.call(document.querySelectorAll('.smcell'));
  var auRows = [].slice.call(document.querySelectorAll('.rank[data-author]'));

  // The global filter row (C1/C2) — a second line of the sticky top bar. Each
  // control is a compact twin of a filter that already exists (author chips,
  // area chips, the panel's date pair) over the SAME state variables, so the
  // two presentations can never disagree about what is filtered.
  var gFrom = document.getElementById('audit-gfrom');
  var gTo = document.getElementById('audit-gto');
  var gClear = document.getElementById('audit-gclear');
  var auSelect = document.getElementById('audit-au-select');
  var areaSelect = document.getElementById('audit-area-select');
  // The per-day data layer both C1 (range scoping) and C3 (heatmap calendar
  // navigation) read: {min, max, showCost, days: {date: [tokens, cost, msgs,
  // [24 hour counts]]}}. Absent on a report without a ledger.
  var U = window.AUDIT_USAGE || null;

  // Client-side mirrors of _fmt.py's formatters, for text this script has to
  // compose itself (the range summary line, the re-rendered heatmap tips).
  // Same table, same shapes: magnitudes compact ("3.2M"), countables keep
  // their thousands separators, real-but-sub-cent spend never reads $0.00.
  function fmtTokens(n, dp) {
    n = Math.trunc(n || 0);
    var a = Math.abs(n);
    var t = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
    for (var i = 0; i < t.length; i++) {
      if (a >= t[i][0]) return (n / t[i][0]).toFixed(dp) + t[i][1];
    }
    return String(n);
  }
  function fmtCost(x) {
    x = x || 0;
    if (x && Math.abs(x) < 0.01) return '<$0.01';
    return '$' + x.toFixed(2);
  }
  function fmtInt(n) {
    return String(Math.trunc(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

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
    // ex (F-P-4): each task's detail row, resolved once and hung on the task
    // row itself — refresh() shows and hides these in the same pass, and a
    // querySelector per task per keystroke is the cliff this index exists for.
    [].forEach.call(grouped.querySelectorAll('tbody tr.taskdetail'), function (d) {
      var id = d.getAttribute('data-detail');
      var host = grouped.querySelector('tr.task .dtoggle[data-dfor="' + id + '"]');
      var row = host ? host.closest('tr.task') : null;
      if (row) { row.__detail = d; d.__task = row; }
    });
    [].forEach.call(grouped.querySelectorAll('tbody tr.taskfilter'), function (t) {
      TFROW[t.getAttribute('data-phase')] = t;
    });
  }
  // Resolved once, with everything else that refresh() would otherwise have to
  // look up per phase per keystroke.
  phaseRows.forEach(function (pr) { pr.__pmatch = pr.querySelector('.pmatch'); });
  // Segments (D1), indexed once like everything else refresh() reads. The
  // archive starts collapsed exactly when the renderer emitted the toggle:
  // the server decides (done phases exist AND something else does too), this
  // script only obeys — a second copy of that decision here would be the two
  // drifting apart.
  var segRows = grouped
    ? [].slice.call(grouped.querySelectorAll('tbody tr.seghead')) : [];
  segRows.forEach(function (sh) { sh.__seg = sh.getAttribute('data-seg'); });
  var archN = 0;
  phaseRows.forEach(function (pr) {
    pr.__seg = pr.getAttribute('data-seg') || '';
    if (pr.__seg === 'archived') archN++;
  });
  // vw (F-P-4): which phases are on screen is a NAMED view, not a toggle
  // somebody has to find. `active` covers both segments of unfinished work;
  // `archived` is done AND cancelled; `all` is the escape hatch. The starting
  // value is the renderer's (it stamps `all` on a plan with nothing active),
  // then whatever the reader last chose, then whatever the link says.
  var viewSel = document.getElementById('audit-view');
  var VIEWS = { active: ['active', 'pending'], archived: ['archived'],
                all: ['active', 'pending', 'archived'] };
  var defaultView = (grouped && grouped.getAttribute('data-defaultview')) || 'active';
  var viewMode = defaultView;
  function inView(seg) {
    return (VIEWS[viewMode] || VIEWS.all).indexOf(seg) >= 0;
  }
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
  // The renderer joins a phase's tags with single spaces into `data-area`
  // (render-report's phase-row emitter), so splitting on whitespace and
  // dropping the empties reads an untagged phase as no tags rather than [''].
  function areaOk(pr) {
    if (!areaFilter.length) return true;
    var tags = (pr.getAttribute('data-area') || '').split(/\s+/);
    for (var i = 0; i < tags.length; i++) {
      if (tags[i] && areaFilter.indexOf(tags[i]) !== -1) return true;
    }
    return false;
  }

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
  function paintAreas() {
    if (areaBar) {
      [].forEach.call(areaBar.children, function (x) {
        var on = areaFilter.indexOf(x.getAttribute('data-a')) !== -1;
        x.classList.toggle('on', on);
        x.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    // The global select shows the same selection. A select can only say one
    // thing, and the chips can hold several — so a multi-selection gets a
    // synthetic "N areas" option rather than the select naming one tag and
    // silently misdescribing the rest.
    if (areaSelect) {
      var multi = areaSelect.querySelector('option[data-multi]');
      if (areaFilter.length > 1) {
        if (!multi) {
          multi = document.createElement('option');
          multi.setAttribute('data-multi', '');
          multi.value = '~multi';
          areaSelect.appendChild(multi);
        }
        multi.textContent = areaFilter.length + ' areas';
        areaSelect.value = '~multi';
      } else {
        if (multi && multi.parentNode) multi.parentNode.removeChild(multi);
        areaSelect.value = areaFilter[0] || '';
      }
    }
  }
  // The global area select: one tag or all. Multi-select stays where it always
  // was (the chips in More filters); picking here replaces the selection.
  if (areaSelect) areaSelect.addEventListener('change', function () {
    if (areaSelect.value === '~multi') return;   // the synthetic summary option
    areaFilter = areaSelect.value ? [areaSelect.value] : [];
    paintAreas();
    refresh();
  });
  wireChips(areaBar, 'data-a', function (val) {
    var i = areaFilter.indexOf(val);
    if (i === -1) areaFilter.push(val); else areaFilter.splice(i, 1);
    paintAreas();
    refresh();
  });

  // Author chips (C3, inside the Usage section). They toggle `hidden` on the
  // section's per-author views and nothing else — the tiles and trend above
  // stay project-wide, and the task table has no author to filter by. The
  // default view is restored by re-applying hidden from the data-top marker
  // the renderer stamped on the top-8 cells, so a release is exact rather
  // than a re-render's guess.
  function applyAuthor() {
    if (auSelect) auSelect.value = auFilter;   // the global twin says the same
    smCells.forEach(function (c) {
      c.hidden = auFilter ? c.getAttribute('data-author') !== auFilter
                          : !c.hasAttribute('data-top');
    });
    auRows.forEach(function (r) {
      r.hidden = !!auFilter && r.getAttribute('data-author') !== auFilter;
    });
    if (auNote) {
      var chip = null;
      if (authorBar && auFilter) {
        [].forEach.call(authorBar.children, function (x) {
          if (x.getAttribute && x.getAttribute('data-au') === auFilter) chip = x;
        });
      }
      if (chip) {
        // Assembled from the chip's own data attributes — the renderer already
        // did this arithmetic once, and a second implementation here is how a
        // summary ends up disagreeing with the chips it summarises.
        var cost = chip.getAttribute('data-cost');
        var sep = ' \u00b7 ';   // a middot, as an escape so the source stays ASCII
        auNote.textContent = auFilter + ': ' + chip.getAttribute('data-tokens')
          + ' tokens' + (cost ? sep + cost : '')
          + sep + chip.getAttribute('data-msgs') + ' msgs'
          + sep + chip.getAttribute('data-share') + ' of all spend';
        auNote.hidden = false;
      } else {
        auNote.hidden = true;
        auNote.textContent = '';
      }
    }
    syncHash();
  }
  wireChips(authorBar, 'data-au', function (val, host, attr) {
    auFilter = (auFilter === val) ? '' : val;
    highlight(host, attr, auFilter);
    applyAuthor();
  });
  // The authors dropdown (C2) drives the same state the chips do; both paint.
  if (auSelect) auSelect.addEventListener('change', function () {
    auFilter = auSelect.value;
    if (authorBar) highlight(authorBar, 'data-au', auFilter);
    applyAuthor();
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

  // --- heatmap calendar navigation (C3) --------------------------------------
  // The server renders the all-data 7x24 grid; this re-renders the tbody from
  // the embedded per-day payload for one day / week / month / year at a time,
  // prev/next strictly bounded by the data (an arrow at the edge is disabled
  // and muted, never a dead click), and the period on display NAMED in the
  // label. The custom range IS C1's range control: while a range is active the
  // heatmap's whole universe is that range — granularity navigation clamps to
  // it, and "All" reads "Custom range" with the span. One range, one meaning.
  (function () {
    var body = document.getElementById('audit-hm-body');
    var granBar = document.getElementById('audit-hm-gran');
    var prevBtn = document.getElementById('audit-hm-prev');
    var nextBtn = document.getElementById('audit-hm-next');
    var periodEl = document.getElementById('audit-hm-period');
    var peakEl = document.getElementById('audit-hm-peak');
    if (!U || !body || !granBar || !prevBtn || !nextBtn || !periodEl) return;
    var DAY = 86400000;
    var WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December'];
    var gran = 'all';
    var anchor = '';             // period start (ISO day) when gran !== 'all'
    function dParse(d) { return Date.parse(d + 'T00:00:00Z'); }
    function dIso(ms) { return new Date(ms).toISOString().slice(0, 10); }
    function wdayOf(d) { return (new Date(dParse(d)).getUTCDay() + 6) % 7; }
    function bounds() {
      var lo = U.min, hi = U.max;
      if (dFrom && dFrom > lo) lo = dFrom;
      if (dTo && dTo < hi) hi = dTo;
      return lo > hi ? null : { lo: lo, hi: hi };
    }
    function startOf(g, day) {
      if (g === 'week') return dIso(dParse(day) - wdayOf(day) * DAY);
      if (g === 'month') return day.slice(0, 7) + '-01';
      if (g === 'year') return day.slice(0, 4) + '-01-01';
      return day;
    }
    function endOf(g, s) {
      if (g === 'week') return dIso(dParse(s) + 6 * DAY);
      if (g === 'month') {
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7), 0));
      }
      if (g === 'year') return s.slice(0, 4) + '-12-31';
      return s;
    }
    function shift(g, s, dir) {
      if (g === 'day') return dIso(dParse(s) + dir * DAY);
      if (g === 'week') return dIso(dParse(s) + dir * 7 * DAY);
      if (g === 'month') {
        return dIso(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1 + dir, 1));
      }
      if (g === 'year') return (+s.slice(0, 4) + dir) + '-01-01';
      return s;
    }
    function hasData(from, to) {
      for (var d in U.days) { if (d >= from && d <= to) return true; }
      return false;
    }
    // The next period in `dir` that is inside the bounds AND records anything
    // — "never navigate into empty periods" is a rule about data, not about
    // the calendar, so gap days between two worked weeks are stepped OVER.
    function seek(g, s, dir, b) {
      for (var i = 0; i < 4000; i++) {
        s = shift(g, s, dir);
        var en = endOf(g, s);
        if (en < b.lo || s > b.hi) return null;
        var lo = s < b.lo ? b.lo : s;
        var hi = en > b.hi ? b.hi : en;
        if (hasData(lo, hi)) return s;
      }
      return null;
    }
    function labelOf(g, s, b) {
      if (g === 'day') return WD[wdayOf(s)] + ' ' + s;
      if (g === 'week') return 'Week of ' + s + ' to ' + endOf('week', s);
      if (g === 'month') return MON[+s.slice(5, 7) - 1] + ' ' + s.slice(0, 4);
      if (g === 'year') return s.slice(0, 4);
      return ((dFrom || dTo) ? 'Custom range' : 'All data')
        + ' · ' + b.lo + ' to ' + b.hi;
    }
    function hoursOf(d) { return (U.days[d] || [0, 0, 0, []])[3] || []; }
    // The current view as DATA — rows, peak, label — split from the DOM paint
    // so the PNG export (D2) can redraw exactly what is on screen without
    // touching it. The anchor clamp lives here because the view is what the
    // clamp is FOR: render() paints whatever this returns.
    function view() {
      var b = bounds();
      if (!b) return null;
      if (gran !== 'all') {
        if (!anchor) anchor = startOf(gran, b.hi);
        var aEnd = endOf(gran, anchor);
        if (aEnd < b.lo || anchor > b.hi) anchor = startOf(gran, b.hi);
      }
      var s = gran === 'all' ? b.lo : anchor;
      var en = gran === 'all' ? b.hi : endOf(gran, s);
      var lo = s < b.lo ? b.lo : s;
      var hi = en > b.hi ? b.hi : en;
      // rows: [{label, days:[iso|null x cells]}] — day/week keep the calendar
      // (one row per date), coarser grains aggregate by weekday like the
      // server's all-data view.
      var rows = [];
      if (gran === 'day') {
        rows.push({ label: WD[wdayOf(lo)] + ' ' + lo.slice(5), cells: hoursOf(lo).slice(),
                    head: WD[wdayOf(lo)] + ' ' + lo });
      } else if (gran === 'week') {
        for (var ms = dParse(s); ms <= dParse(en); ms += DAY) {
          var d = dIso(ms);
          var inR = d >= lo && d <= hi;
          rows.push({ label: WD[wdayOf(d)] + ' ' + d.slice(5),
                      cells: inR ? hoursOf(d).slice() : null,
                      head: WD[wdayOf(d)] + ' ' + d });
        }
      } else {
        var agg = [];
        for (var w = 0; w < 7; w++) agg.push([]);
        for (var dd in U.days) {
          if (dd < lo || dd > hi) continue;
          var vec = hoursOf(dd);
          var tgt = agg[wdayOf(dd)];
          for (var h = 0; h < 24; h++) tgt[h] = (tgt[h] || 0) + (vec[h] || 0);
        }
        for (var w2 = 0; w2 < 7; w2++) {
          rows.push({ label: WD[w2], cells: agg[w2], head: WD[w2] });
        }
      }
      var peak = 0;
      rows.forEach(function (r) {
        (r.cells || []).forEach(function (v) { if (v > peak) peak = v; });
      });
      return { rows: rows, peak: peak, s: s, b: b,
               label: labelOf(gran, s, b) };
    }
    function render() {
      var v = view();
      var setArrow = function (btn, ok) {
        if (ok) btn.removeAttribute('disabled');
        else btn.setAttribute('disabled', '');
      };
      if (!v) {
        body.innerHTML = '';
        periodEl.textContent = 'No recorded usage in this range';
        if (peakEl) peakEl.textContent = '0';
        setArrow(prevBtn, false); setArrow(nextBtn, false);
        return;
      }
      var htmlRows = [], tips = [];
      v.rows.forEach(function (r) {
        var tds = [];
        for (var h2 = 0; h2 < 24; h2++) {
          var val = r.cells ? (r.cells[h2] || 0) : 0;
          var lv = (!val || !v.peak) ? 0
            : Math.min(6, 1 + Math.floor(5 * val / v.peak));
          tds.push('<td><i data-l="' + lv + '"></i></td>');
          // Same one-line shape the server's titles use; a day the range
          // excludes says so instead of claiming a zero it cannot know.
          tips.push(r.cells
            ? r.head + ' ' + (h2 < 10 ? '0' : '') + h2 + ':00 - '
              + fmtTokens(val, 2) + ' tokens'
            : r.head + ' - outside the selected range');
        }
        htmlRows.push('<tr><th>' + r.label + '</th>'
          + tds.join('') + '</tr>');
      });
      body.innerHTML = htmlRows.join('');
      [].forEach.call(body.querySelectorAll('i'), function (cell, i) {
        cell.__tip = tips[i];
      });
      if (peakEl) peakEl.textContent = fmtTokens(v.peak, 1);
      periodEl.textContent = v.label;
      var canStep = gran !== 'all';
      setArrow(prevBtn, canStep && seek(gran, v.s, -1, v.b) !== null);
      setArrow(nextBtn, canStep && seek(gran, v.s, 1, v.b) !== null);
    }
    function step(dir) {
      var b = bounds();
      if (!b || gran === 'all') return;
      var s2 = seek(gran, anchor, dir, b);
      if (!s2) return;
      anchor = s2;
      render();
    }
    prevBtn.addEventListener('click', function () { step(-1); });
    nextBtn.addEventListener('click', function () { step(1); });
    wireChips(granBar, 'data-g', function (val) {
      if (val === gran) return;
      gran = val;
      var b = bounds();
      anchor = (val === 'all' || !b) ? '' : startOf(val, b.hi);
      highlight(granBar, 'data-g', gran);
      render();
    });
    highlight(granBar, 'data-g', gran);   // 'all' is lit from the start
    // Called when the global range moves: clamp the current period into the
    // new bounds and redraw. The initial no-range state deliberately keeps the
    // server-rendered tbody untouched.
    hmApply = render;
    hmView = view;
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

  // ex (F-P-4): the per-task detail toggle. The compact row answers "where is
  // this"; this opens the row that answers "what happened and who do I ask" —
  // the full outcome above all, which the table can only show 70 characters of.
  [].slice.call(document.querySelectorAll('.dtoggle')).forEach(function (b) {
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();          // the row itself is not a control
      var row = b.closest('tr.task');
      if (!row || !row.__detail) return;
      row.__open = !row.__open;
      row.__detail.hidden = !row.__open;
      b.setAttribute('aria-expanded', row.__open ? 'true' : 'false');
      b.setAttribute('aria-label', (row.__open ? 'Hide' : 'Show')
        + ' details for ' + (b.getAttribute('data-dfor') || 'this task'));
    });
  });

  // vw: the view select. Unlike the toggle it replaces, this IS part of the
  // view someone would send as a link (and expect back after a reload), so it
  // rides the fragment and the local fallback with the filters.
  function setView(v) {
    if (!VIEWS[v]) return;
    viewMode = v;
    if (viewSel && viewSel.value !== v) viewSel.value = v;
    refresh();
  }
  if (viewSel) {
    viewSel.value = viewMode;
    viewSel.addEventListener('change', function () { setView(viewSel.value); });
  }
  [].slice.call(document.querySelectorAll('[data-viewall]')).forEach(function (b) {
    b.addEventListener('click', function () { setView('all'); });
  });

  // --- per-segment and per-section exports (D2) ------------------------------
  // CSV of the DATA — never the filtered view: a file named "phases-active"
  // that silently held whatever the search box happened to leave visible
  // would be a different file every download. PNG of the charts, REDRAWN from
  // window.AUDIT_USAGE onto a canvas: the marks are bars on a grid, and
  // DOM-to-canvas serialisation is exactly the dependency this
  // zero-external-fetch file cannot take. And a print mode that isolates one
  // segment. Every button is server-rendered (the chips rule); this only
  // attaches behaviour.
  var BASE = String(window.AUDIT_MD_NAME || 'audit-report.md').replace(/\.md$/, '');
  function csvQuote(v) {
    // RFC 4180, the same rule the panel's export uses: quote anything that
    // carries a comma, a quote or a newline, and double the quotes inside.
    var s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function download(name, blob) {
    // The .md button's own mechanism: a temporary object URL on an anchor,
    // revoked LATE — some engines have not started reading the blob when
    // click() returns, and a revoked URL there is a download that fails with
    // no error anywhere.
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }
  function csvDownload(name, rows) {
    var text = rows.map(function (r) { return r.map(csvQuote).join(','); })
      .join('\r\n') + '\r\n';
    // U+FEFF: without the BOM Excel reads a UTF-8 CSV in the local 8-bit
    // codepage. As an escape, never the character — an invisible literal in
    // the source is unreviewable (the panel export's own rule).
    download(name, new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' }));
  }
  // Column names read once off the table's own header — the export must not
  // restate _present_columns, or the two would disagree the first time a
  // column appears.
  // The MACHINE name of each optional column, from the header's own attribute
  // rather than its words: the done header carries a "UTC" note beside the
  // word, and a CSV keyed on rendered text would stop recognising the column
  // the moment a header gained a second word (it did).
  var COLNAMES = grouped
    ? [].slice.call(grouped.querySelectorAll('thead th')).map(function (h) {
        return h.getAttribute('data-col') || h.textContent.trim();
      }).slice(3)
    : [];
  // csv (F-P-4): the file carries the DATA, not what the cell happens to show.
  // Three columns are lossy on screen and were being exported lossy: the commit
  // cell shows nine characters (and, since the copy control landed, the word
  // "Copy" inside its own text), the done cell shows minutes, and the outcome
  // cell is cut at 70 characters. A spreadsheet is where someone re-derives
  // things, so each of those exports its full value — read from the same place
  // the reader can see it, the detail row.
  function detailValue(t, key) {
    var d = t.__detail;
    if (!d) return '';
    var ks = [].slice.call(d.querySelectorAll('.dt-k'));
    for (var i = 0; i < ks.length; i++) {
      if (ks[i].textContent.trim() === key) {
        var v = ks[i].nextElementSibling;
        return v ? v.textContent.trim() : '';
      }
    }
    return '';
  }
  // An em dash is what a table prints where there is nothing; a data file says
  // nothing by saying nothing. Every column goes through this.
  function csvPlain(v) { return (v === '\u2014' || v === '-') ? '' : v; }
  function csvCell(t, name, ci) {
    if (name === 'commit') {
      var b = t.querySelector('.shacopy');
      return b ? b.getAttribute('data-copy') : '';
    }
    if (name === 'done') {
      // The DETAIL row carries the whole stamp; the data-attribute is cut to
      // the date on purpose (the range filter compares those as strings), and
      // the cell is cut to the minute. A spreadsheet gets the seconds.
      return detailValue(t, 'completed') || detailValue(t, 'started')
        || t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
    }
    if (name === 'outcome') return detailValue(t, 'outcome') || csvPlain(cell(t, 3 + ci));
    return csvPlain(cell(t, 3 + ci));
  }
  function segCsv(seg) {
    var rows = [['phase', 'phase title', 'phase status',
                 'task', 'task title', 'task status'].concat(COLNAMES)
      // ...plus everything the compact row moved into the detail. A CSV is the
      // complete view by definition: a column that left the table must not
      // leave the file with it.
      .concat(['started', 'model', 'outcome', 'technical outcome', 'work item',
               'owner', 'waits on'])];
    phaseRows.forEach(function (pr) {
      if (pr.__seg !== seg) return;
      var pid = pr.getAttribute('data-phase');
      var strongEl = pr.querySelector('strong');
      var head = [pid, strongEl ? strongEl.textContent : '',
                  pr.getAttribute('data-status') || ''];
      var tasks = tasksOf(pid);
      if (!tasks.length) {   // a phase with no tasks is still a data row
        rows.push(head.concat(['', '', ''])
          .concat(COLNAMES.map(function () { return ''; }))
          .concat(['', '', '', '', '', '', '']));
        return;
      }
      tasks.forEach(function (t) {
        // Machine statuses from the data attributes; prose from the cells.
        var line = head.concat([cell(t, 0), cell(t, 1),
                                t.getAttribute('data-status') || '']);
        for (var ci = 0; ci < COLNAMES.length; ci++) {
          line.push(csvCell(t, COLNAMES[ci], ci));
        }
        // The four the table has no column for and the detail row does. A
        // reader who opened the row to find them should not have to open
        // fifty rows to tabulate them.
        line.push(detailValue(t, 'started') || t.getAttribute('data-started') || '',
                  detailValue(t, 'model') || t.getAttribute('data-model') || '',
                  detailValue(t, 'outcome'),
                  detailValue(t, 'technical'),
                  detailValue(t, 'work item'),
                  detailValue(t, 'owner'),
                  detailValue(t, 'waits on'));
        rows.push(line);
      });
    });
    csvDownload(BASE + '-phases-' + seg + '.csv', rows);
  }
  function bugsCsv() {
    var rows = [['id', 'title', 'status', 'severity', 'task', 'fixedIn', 'ADO']];
    bugRows.forEach(function (b) {
      rows.push([cell(b, 0), cell(b, 1),
                 b.getAttribute('data-status') || cell(b, 2),
                 cell(b, 3), cell(b, 4), cell(b, 5), cell(b, 6)]);
    });
    csvDownload(BASE + '-bugs.csv', rows);
  }
  function usageCsv() {
    if (!U) return;
    var showCost = U.showCost !== false;
    var rows = [['date', 'tokens'].concat(showCost ? ['costUSD'] : [])
      .concat(['msgs'])];
    var days = [];
    for (var ud in U.days) days.push(ud);
    days.sort();
    days.forEach(function (d) {
      var v = U.days[d];
      // Raw numbers on purpose: '3,230,000' lands in a spreadsheet as text
      // and every sum over the column is then wrong, silently.
      var line = [d, v[0]];
      if (showCost) line.push(v[1]);
      line.push(v[2]);
      rows.push(line);
    });
    csvDownload(BASE + '-usage-daily.csv', rows);
  }
  [].slice.call(document.querySelectorAll('[data-segcsv]')).forEach(function (b) {
    b.addEventListener('click', function () {
      segCsv(b.getAttribute('data-segcsv'));
    });
  });
  [].slice.call(document.querySelectorAll('[data-csv]')).forEach(function (b) {
    b.addEventListener('click',
      b.getAttribute('data-csv') === 'bugs' ? bugsCsv : usageCsv);
  });

  function cssColor(token, fallback) {
    // Resolved through a live element rather than read raw off the root:
    // several tokens are color-mix() expressions, and what a canvas needs is
    // the colour the browser actually computed.
    var probe = document.createElement('i');
    probe.style.color = 'var(' + token + ',' + fallback + ')';
    document.body.appendChild(probe);
    var c = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    return c || fallback;
  }
  function pngCanvas(w, h) {
    var c = document.createElement('canvas');
    // 2x, so the file survives being pasted into a document at print density.
    c.width = w * 2; c.height = h * 2;
    var ctx = c.getContext('2d');
    ctx.scale(2, 2);
    return { el: c, ctx: ctx };
  }
  function pngDownload(name, canvas) {
    // toDataURL rather than a blob: synchronous, and the payload is small.
    var a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }
  function trendPng() {
    if (!U) return;
    var days = [];
    for (var td in U.days) days.push(td);
    days.sort();
    if (!days.length) return;
    var peak = 0;
    days.forEach(function (d) { if (U.days[d][0] > peak) peak = U.days[d][0]; });
    // Bar width follows the span so a three-year ledger still fits one image.
    var barW = Math.max(1, Math.min(10, Math.floor(1100 / days.length)));
    var left = 58, top = 44, bottom = 34;
    var W = left + days.length * (barW + 1) + 14, H = 280;
    var g = pngCanvas(W, H), ctx = g.ctx;
    var ink = cssColor('--text', '#111827');
    var mut = cssColor('--muted', '#6b7280');
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = ink;
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens per day · ' + days[0] + ' to '
      + days[days.length - 1], 10, 20);
    var plot = H - top - bottom;
    ctx.strokeStyle = cssColor('--border', '#d1d5db');
    ctx.fillStyle = mut;
    ctx.font = '11px sans-serif';
    [0, 0.5, 1].forEach(function (f) {
      var y = top + plot * f;
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(W - 6, y); ctx.stroke();
      ctx.fillText(fmtTokens(peak * (1 - f), 1), 8, y + 4);
    });
    ctx.fillStyle = cssColor('--accent-solid', '#4f46e5');
    days.forEach(function (d, i) {
      var v = U.days[d][0];
      var bh = peak ? Math.max(1, plot * v / peak) : 1;
      ctx.fillRect(left + i * (barW + 1), top + plot - bh, barW, bh);
    });
    ctx.fillStyle = mut;
    ctx.fillText(days[0], left, H - 12);
    var lastD = days[days.length - 1];
    ctx.fillText(lastD, W - 8 - ctx.measureText(lastD).width, H - 12);
    pngDownload(BASE + '-trend.png', g.el);
  }
  function heatmapPng() {
    // hmView is set by the heatmap module below; it answers with the CURRENT
    // view — granularity, period, range — so the file shows what the screen
    // shows, not a second implementation's idea of it.
    var v = hmView ? hmView() : null;
    if (!v) return;
    var cellW = 26, cellH = 18, gap = 2, labelW = 96, top = 44;
    var W = labelW + 24 * (cellW + gap) + 12;
    var H = top + v.rows.length * (cellH + gap) + 30;
    var g = pngCanvas(W, H), ctx = g.ctx;
    ctx.fillStyle = cssColor('--surface', '#ffffff');
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = cssColor('--text', '#111827');
    ctx.font = '600 13px sans-serif';
    ctx.fillText('Tokens by hour (UTC) · ' + v.label, 10, 20);
    var ramp = [];
    for (var lv0 = 0; lv0 <= 6; lv0++) ramp.push(cssColor('--hm-' + lv0, '#eeeeee'));
    ctx.font = '11px sans-serif';
    v.rows.forEach(function (r, ri) {
      var y = top + ri * (cellH + gap);
      ctx.fillStyle = cssColor('--muted', '#6b7280');
      ctx.fillText(r.label, 8, y + cellH - 5);
      for (var h2 = 0; h2 < 24; h2++) {
        var val = r.cells ? (r.cells[h2] || 0) : 0;
        var lv = (!val || !v.peak) ? 0
          : Math.min(6, 1 + Math.floor(5 * val / v.peak));
        ctx.fillStyle = ramp[lv];
        ctx.fillRect(labelW + h2 * (cellW + gap), y, cellW, cellH);
      }
    });
    ctx.fillStyle = cssColor('--muted', '#6b7280');
    for (var tk = 0; tk < 24; tk += 6) {
      ctx.fillText((tk < 10 ? '0' : '') + tk, labelW + tk * (cellW + gap), H - 10);
    }
    pngDownload(BASE + '-heatmap.png', g.el);
  }
  [].slice.call(document.querySelectorAll('[data-png]')).forEach(function (b) {
    b.addEventListener('click',
      b.getAttribute('data-png') === 'trend' ? trendPng : heatmapPng);
  });

  // Print one segment (D2): stamp the attribute the print CSS keys on, open
  // the dialog, and let afterprint take it back off — the same event the
  // details-reopening handler above already rides, so a cancelled dialog
  // restores exactly like a completed one.
  [].slice.call(document.querySelectorAll('[data-segprint]')).forEach(function (b) {
    b.addEventListener('click', function () {
      document.body.setAttribute('data-printseg', b.getAttribute('data-segprint'));
      window.print();
    });
  });
  window.addEventListener('afterprint', function () {
    document.body.removeAttribute('data-printseg');
  });

  wireSort(grouped, true, true);
  wireSort(bugsTable, false, true);
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
  // A link WINS over the local copy: somebody sent it on purpose. With no link,
  // the local copy is what this reader last had on screen.
  if (!Object.keys(HASH).length) {
    try {
      var stored = localStorage.getItem(STORE_KEY);
      if (stored) {
        stored.split('&').forEach(function (pair) {
          if (!pair) return;
          var i = pair.indexOf('=');
          var k = i < 0 ? pair : pair.slice(0, i);
          var v = i < 0 ? '' : pair.slice(i + 1);
          try { HASH[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) {}
        });
      }
    } catch (e) {}
  }
  if (HASH.v && VIEWS[HASH.v]) {
    viewMode = HASH.v;
    if (viewSel) viewSel.value = viewMode;
  }
  if (q && HASH.q) q.value = HASH.q;
  if (HASH.ps) {
    phaseStatus = HASH.ps;
    if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', phaseStatus);
  }
  if (HASH.m) {
    modelFilter = HASH.m;
    if (modelBar) highlight(modelBar, 'data-m', modelFilter);
  }
  if (HASH.a) {
    areaFilter = HASH.a.split(/\s+/).filter(Boolean);
    paintAreas();
  }
  if (HASH.from || HASH.to) { dFrom = HASH.from || ''; dTo = HASH.to || ''; paintDates(); }
  if (HASH.au) {
    auFilter = HASH.au;
    if (authorBar) highlight(authorBar, 'data-au', auFilter);
    applyAuthor();
  }
  refresh();
})();
