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

  // toFixed breaks an exact tie AWAY from zero; Python's "%.*f" breaks it to
  // EVEN. That shipped: 1250 tokens read "1.3K" here against _fmt.py's "1.2K",
  // and $0.125 read "$0.13" against "$0.12". A different rounding MODE, not
  // float noise — the inputs are exactly representable in binary.
  //
  // A double is an exact tie at `dp` places IFF x * 2^(dp+1) is an ODD integer.
  // A tie is (2j+1)/(2*10^dp), and a double is only ever a dyadic rational, so
  // 5^dp must divide (2j+1) — which leaves x = t/2^(dp+1) with t odd. Scaling
  // by a power of two only shifts the exponent, so that test is exact. Scaling
  // by 10^dp is NOT, and that is the trap: `n * 100 === Math.round(n * 100)`
  // misclassifies the majority of values, which are not representable. A value
  // that is not a tie (1.35, 3.05) fails this test and keeps toFixed's answer,
  // which already agrees with Python.
  //
  // On a tie toFixed returns the away-from-zero neighbour, so its last digit is
  // odd exactly when Python picks the other one — and stepping that digit down
  // by one never borrows, because an odd digit is never 0.
  //
  // Written twice, once per dialect, because there is no build step that could
  // share it with panel.js's `uFixedHalfEven`. That is the known cost, and
  // tools/ui-tests/half-even.test.mjs holds the two copies equal against
  // _fmt.py — a comment asserting they match is the thing that was already
  // false in this family once.
  function fixedHalfEven(x, dp) {
    var s = x.toFixed(dp);
    var scaled = x * Math.pow(2, dp + 1);
    if (!isFinite(scaled) || Math.floor(scaled) !== scaled || scaled % 2 === 0) return s;
    var last = s.charCodeAt(s.length - 1) - 48;
    return last % 2 === 1 ? s.slice(0, -1) + String(last - 1) : s;
  }
  function fmtTokens(n, dp) {
    n = Math.trunc(n || 0);
    var a = Math.abs(n);
    var t = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
    for (var i = 0; i < t.length; i++) {
      if (a >= t[i][0]) return fixedHalfEven(n / t[i][0], dp) + t[i][1];
    }
    return String(n);
  }
  function fmtCost(x) {
    x = x || 0;
    if (x && Math.abs(x) < 0.01) return '<$0.01';
    return '$' + fixedHalfEven(x, 2);
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

