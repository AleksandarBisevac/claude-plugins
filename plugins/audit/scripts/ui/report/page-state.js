  // --- elements, and the filter state carried in the link ---------------------

  // The free-text search box. Like every lookup below it may be null: a report
  // renders only the controls its plan has something to put in.
  const q = document.getElementById('audit-q');

  // The page is running scripts, so the banner saying the interactive layer is
  // off is wrong and goes now — ahead of every statement that can throw. If
  // something below does throw, the banner stays up and is then TRUE, because
  // filtering, search and expanding really are dead.
  const _nojs = document.getElementById('audit-nojs');
  if (_nojs && _nojs.parentNode) _nojs.parentNode.removeChild(_nojs);

  /**
   * The filter state a shared link carries, decoded once at load. A filtered
   * view of this report is a LINK: this is the read side, and the filter part
   * writes it back through syncHash().
   *
   * The `#!` prefix is not decoration. The side nav's links are plain fragments
   * over the same slot, so without a marker separating the two, restoring filter
   * state and following a heading link would each undo the other.
   *
   * @type {Object<string, string>} decoded key/value pairs; empty for a plain
   *   fragment, or for no fragment at all
   */
  const HASH = (() => {
    const h = location.hash || '';
    if (h.indexOf('#!') !== 0) return {};
    return h.slice(2).split('&').filter(Boolean).reduce((acc, pair) => {
      const i = pair.indexOf('=');
      const k = i < 0 ? pair : pair.slice(0, i);
      const v = i < 0 ? '' : pair.slice(i + 1);
      // A malformed percent-escape costs one value, never the whole hash: the
      // key stays present so the control it drives is still restored.
      try { acc[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { acc[k] = ''; }
      return acc;
    }, {});
  })();

  const count = document.getElementById('audit-count');
  const phaseStatusBar = document.getElementById('audit-phase-status');
  const expandBtn = document.getElementById('audit-expand');
  const grouped = document.querySelector('table.phases');
  const bugsTable = document.querySelector('table.bugs');

  // --- theme ------------------------------------------------------------------

  // Follow the OS by default; the toolbar toggle overrides it and persists.
  const root = document.documentElement;
  const themeBtn = document.getElementById('audit-theme');
  const THEME_KEY = 'audit-report-theme';

  /**
   * Whether the reader's OS asks for a dark UI.
   * @returns {boolean} false when the browser cannot answer the question
   */
  const prefersDark = () =>
    Boolean(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);

  /**
   * The theme actually in force: an explicit data-theme wins, else the OS.
   * @returns {boolean} true when the page renders dark
   */
  const isDark = () => {
    const t = root.getAttribute('data-theme');
    return t ? t === 'dark' : prefersDark();
  };

  /**
   * Put the glyph for the theme the toggle would switch TO on the button.
   * @returns {void}
   */
  const paintTheme = () => {
    if (themeBtn) themeBtn.textContent = isDark() ? '☀' : '☾';
  };

  // Restore a saved theme only where this report owns the toggle. Embedded in a
  // host page there is no button, the host stamps data-theme itself, and it must
  // win: reinstating a value saved on some earlier visit would silently override
  // the theme the viewer is actually looking at. A page that does not offer the
  // control has no business reinstating its state.
  if (themeBtn) {
    const savedTheme = storageGet(THEME_KEY);
    if (savedTheme) root.setAttribute('data-theme', savedTheme);
    // A theme carried in the link beats one saved on an earlier visit: whoever
    // sent this URL chose how it should be read, and they chose more recently.
    if (HASH.th === 'dark' || HASH.th === 'light') root.setAttribute('data-theme', HASH.th);
  }
  paintTheme();
  // syncHash() belongs to the filter part, which is concatenated after this one.
  // Reachable here because a click can only happen once every part has run.
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = isDark() ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      storageSet(THEME_KEY, next);
      paintTheme();
      syncHash();
    });
  }

  // --- the sticky stack, measured rather than assumed --------------------------

  // The --topbar-h token decides where the nav strip, the filter bar, the column
  // headers and every anchor land, and it depends on things a stylesheet cannot know:
  // how far the title wraps, how tall the strip is at this width, what text size
  // the reader chose. The CSS values are the no-JS fallback; these are the truth.
  const toolbar = document.querySelector('.topbar');
  const snav = document.querySelector('.snav');
  // Only the horizontal strip stacks UNDER the bar. Above 72rem the same nav is
  // a column beside the content and adds nothing to what follows it, so the
  // query that switches the presentation is the one that decides whether it
  // counts toward the offset.
  const stripQ = window.matchMedia ? matchMedia('(max-width:72rem)') : null;

  /**
   * @param {Element|null} el
   * @returns {number} the element's rendered height in whole pixels; 0 when it
   *   is not on the page
   */
  const px = (el) => (el ? Math.round(el.getBoundingClientRect().height) : 0);

  /**
   * Publish the measured height of each sticky layer as a custom property.
   * @returns {void}
   */
  const measureStack = () => {
    if (toolbar) root.style.setProperty('--topbar-h', px(toolbar) + 'px');
    root.style.setProperty('--strip-h',
      (snav && stripQ && stripQ.matches ? px(snav) : 0) + 'px');
    // Queried here rather than through the sectools binding further down: the
    // first measuring pass runs before that binding exists.
    const st = document.querySelector('.sectools');
    if (st) root.style.setProperty('--sectools-h', px(st) + 'px');
  };
  measureStack();
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(measureStack);
    for (const el of [toolbar, snav, document.querySelector('.sectools')]) {
      if (el) ro.observe(el);
    }
  }
  window.addEventListener('resize', measureStack, { passive: true });

  // --- scroll position ---------------------------------------------------------

  // Scroll-spy. The links work without any of this — they are plain anchors
  // rendered server-side — so this only adds the half a nav cannot do
  // statically: saying where you ARE. Without it the sidebar is a menu; with it,
  // a position.
  //
  // Position is a question about ORDER, not about visibility: whichever heading
  // most recently passed under the bar is the one being read. Deciding it from
  // whether a target sits inside a band of the viewport marks nothing most of
  // the time, because most targets are <h2> elements a line and a half tall and
  // no band holds one at a typical scroll offset.
  const navLinks = Array.from(document.querySelectorAll('.snav a'));

  /**
   * The section each nav link points at, in link order; an entry is null when
   * the href names no element on the page.
   *
   * Array types are spelled with a trailing `[]` throughout this file, never
   * with angle brackets: the artifact format ships this script inside a host
   * page and asserts the fragment opens no second document, and an angle
   * bracket in front of a DOM interface name reads as a document tag to that
   * check.
   * @type {(HTMLElement|null)[]}
   */
  const spyTargets = navLinks.map((a) => {
    try { return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1))); }
    catch (e) { return null; }
  });

  /**
   * Mark exactly one nav link as the section being read.
   * @returns {void}
   */
  const markSpy = () => {
    if (!navLinks.length) return;
    const fold = px(toolbar) + (snav && stripQ && stripQ.matches ? px(snav) : 0) + 4;
    let best = -1;
    spyTargets.forEach((el, i) => {
      if (el && el.getBoundingClientRect().top <= fold) best = i;
    });
    if (best < 0) best = 0;   // above the first heading, the first link still answers
    // At the end of the document nothing further can cross the fold, so a short
    // final section would otherwise be unreachable by the marker.
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
      const lastResolved = spyTargets.findLastIndex((el) => Boolean(el));
      if (lastResolved >= 0) best = lastResolved;
    }
    navLinks.forEach((a, i) => {
      if (i === best) a.setAttribute('aria-current', 'true');
      else a.removeAttribute('aria-current');
    });
  };

  // One scroll listener drives the marker and BOTH bars' elevation, coalesced to
  // a frame: scroll fires far faster than the screen repaints.
  let ticking = false;
  const sectools = document.querySelector('.sectools');

  /**
   * Repaint everything whose answer depends on the scroll offset.
   * @returns {void}
   */
  const onScroll = () => {
    if (toolbar) toolbar.classList.toggle('scrolled', (window.scrollY || 0) > 8);
    // The filter bar is stuck when its own top has reached the offset it is
    // stuck AT, which the stylesheet computed from --sticky-2 and the browser
    // has already resolved to pixels. Asking for that rather than recomputing
    // the stack here keeps one definition of where this bar sits: the CSS. A
    // `scrollY > n` test goes wrong the moment anything above the table changes
    // height, which is most of what the top of this report does.
    //
    // Three conditions, because two of the states this bar reaches are not
    // "stuck". On a narrow screen with the filter panel open it is not sticky at
    // all (the 52rem block gives it `top: auto`), so there is nothing to be
    // stuck against. And sticky only holds while its section is in view: scroll
    // past the phases table and the bar goes with it, leaving a top far ABOVE
    // the stick line with nothing on screen to elevate.
    if (sectools) {
      const cs = getComputedStyle(sectools);
      const stickAt = parseFloat(cs.top);
      const sr = sectools.getBoundingClientRect();
      sectools.classList.toggle('stuck',
        cs.position === 'sticky' && sr.top <= stickAt + 1 && sr.bottom > stickAt);
    }
    markSpy();
  };
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { ticking = false; onScroll(); });
  }, { passive: true });
  window.addEventListener('hashchange', markSpy);
  onScroll();

  // --- the rows, and what persists about them ----------------------------------

  // No early return on a missing phases table. The print button, the markdown
  // download, the copy buttons and the whole chart tooltip layer have nothing to
  // do with that table, and a single `if (!grouped) return` above them takes all
  // of them down together whenever it is absent. Everything below degrades to a
  // no-op instead: an empty phaseRows makes every loop over it vacuous.
  const phaseRows = grouped ? Array.from(grouped.querySelectorAll('tbody tr.phase')) : [];
  const bugRows = bugsTable ? Array.from(bugsTable.querySelectorAll('tbody tr')) : [];

  // Which phases are expanded survives filtering AND a page reload.
  const STORE = 'audit-report-expanded:' + (document.title || 'report');
  let expanded = {};
  // The `try` is for the PARSE, not for storage: storageGet cannot throw, so a
  // refused read and a corrupt stored value no longer share one handler.
  try { expanded = JSON.parse(storageGet(STORE)) || {}; } catch (e) {}

  /**
   * Write the expand state back to storage, ignoring a refusal.
   * @returns {void}
   */
  const persist = () => {
    storageSet(STORE, JSON.stringify(expanded));
  };

  // --- filter state, and the controls that write it ----------------------------

  let phaseStatus = '';   // toolbar: filter which PHASES show, by phase status
  let taskStatus = {};    // per phase: filter that phase's TASKS, by task status
  let modelFilter = '';   // panel: only tasks run by this model
  let dFrom = '';         // panel: ISO dates, compared as plain strings
  let dTo = '';
  let preset = '';        // which relative-span chip is lit, if any

  // Areas are a PHASE-level gate like phaseStatus, not a task narrower —
  // `data-area` lives on the phase row and tasks carry none. Multi-select,
  // unlike every filter above, because areas are how one plan holds several
  // subsystems and "the backend AND the web work" is a view someone actually
  // wants; a phase shows when ANY of its tags is selected. While a selection is
  // active, a phase with no tags has no answer to the question being asked and
  // is hidden — the same reasoning dateOk applies to a task without dates.
  let areaFilter = [];    // selected area tags, in click order

  const modelBar = document.getElementById('audit-model');
  const areaBar = document.getElementById('audit-areas');
  const fromInput = document.getElementById('audit-from');
  const toInput = document.getElementById('audit-to');
  const presetBar = document.getElementById('audit-presets');
  const fcount = document.getElementById('audit-fcount');
  const clearBtns = Array.from(document.querySelectorAll('[data-clear]'));
  const norow = grouped ? grouped.querySelector('tr.norows') : null;
  const outsideRow = grouped ? grouped.querySelector('[data-outside]') : null;
  const outsideN = outsideRow ? outsideRow.querySelector('[data-outside-n]') : null;

  // The author chips live in the Usage section and scope ONLY it: tasks record
  // no author, so these never enter refresh() or touch the task table.
  const authorBar = document.getElementById('audit-authors');
  const auNote = document.getElementById('audit-au-note');
  let auFilter = '';
  const smCells = Array.from(document.querySelectorAll('.smcell'));
  const auRows = Array.from(document.querySelectorAll('.rank[data-author]'));

  // The global filter row is a second line of the sticky top bar. Each control
  // is a compact twin of a filter that already exists (author chips, area chips,
  // the panel's date pair) over the SAME state variables, so the two
  // presentations can never disagree about what is filtered.
  const gFrom = document.getElementById('audit-gfrom');
  const gTo = document.getElementById('audit-gto');
  const gClear = document.getElementById('audit-gclear');
  const auSelect = document.getElementById('audit-au-select');
  const areaSelect = document.getElementById('audit-area-select');

  /**
   * The per-day usage layer that both the range controls and the heatmap
   * calendar read. Absent on a report rendered without a ledger.
   * @type {{min: string, max: string, showCost: boolean,
   *         days: Object<string, [number, number, number, number[]]>}|null}
   */
  const U = window.AUDIT_USAGE || null;

  // --- number formatting -------------------------------------------------------

  // Client-side mirrors of _fmt.py's formatters, for text this script has to
  // compose itself (the range summary line, the re-rendered heatmap tips). Same
  // table, same shapes: magnitudes compact ("3.2M"), countables keep their
  // thousands separators, real-but-sub-cent spend never reads $0.00.

  /**
   * `x.toFixed(dp)` with Python's rounding rule: an exact tie breaks to EVEN,
   * where toFixed breaks it AWAY from zero. Without this, 1250 tokens read
   * "1.3K" here against _fmt.py's "1.2K", and $0.125 reads "$0.13" against
   * "$0.12" — a different rounding MODE, not float noise, since both inputs are
   * exactly representable in binary.
   *
   * A double is an exact tie at `dp` places IFF x * 2^(dp+1) is an ODD integer.
   * A tie is (2j+1)/(2*10^dp), and a double is only ever a dyadic rational, so
   * 5^dp must divide (2j+1) — which leaves x = t/2^(dp+1) with t odd. Scaling by
   * a power of two only shifts the exponent, so that test is exact. Scaling by
   * 10^dp is NOT, and that is the trap: `n * 100 === Math.round(n * 100)`
   * misclassifies the majority of values, which are not representable. A value
   * that is not a tie (1.35, 3.05) fails this test and keeps toFixed's answer,
   * which already agrees with Python.
   *
   * On a tie toFixed returns the away-from-zero neighbour, so its last digit is
   * odd exactly when Python picks the other one — and stepping that digit down
   * by one never borrows, because an odd digit is never 0.
   *
   * The panel's `uFixedHalfEven` is this same function in the other dialect;
   * there is no build step that could share one copy, so
   * tools/ui-tests/half-even.test.mjs holds the two equal against _fmt.py.
   *
   * @param {number} x
   * @param {number} dp decimal places
   * @returns {string} the fixed-point rendering
   */
  const fixedHalfEven = (x, dp) => {
    const s = x.toFixed(dp);
    const scaled = x * Math.pow(2, dp + 1);
    if (!isFinite(scaled) || Math.floor(scaled) !== scaled || scaled % 2 === 0) return s;
    const last = s.charCodeAt(s.length - 1) - 48;
    return last % 2 === 1 ? s.slice(0, -1) + String(last - 1) : s;
  };

  /**
   * A token count as a compact magnitude, mirroring `_fmt.fmt_tokens`.
   * @param {number} n
   * @param {number} dp decimal places kept on the compacted value
   * @returns {string} e.g. "3.2M"; the plain integer below a thousand
   */
  const fmtTokens = (n, dp) => {
    const whole = Math.trunc(n || 0);
    const a = Math.abs(whole);
    const scale = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]
      .find(([magnitude]) => a >= magnitude);
    if (!scale) return String(whole);
    const [magnitude, suffix] = scale;
    return fixedHalfEven(whole / magnitude, dp) + suffix;
  };

  /**
   * A dollar amount, mirroring `_fmt.fmt_cost`. Spend that is real but below a
   * cent says so rather than rendering as $0.00, which reads as free.
   * @param {number} x
   * @returns {string}
   */
  const fmtCost = (x) => {
    const v = x || 0;
    if (v && Math.abs(v) < 0.01) return '<$0.01';
    return '$' + fixedHalfEven(v, 2);
  };

  /**
   * A countable with thousands separators, mirroring `_fmt.fmt_int`.
   * @param {number} n
   * @returns {string}
   */
  const fmtInt = (n) => String(Math.trunc(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  // --- the row index every later part reads ------------------------------------

  // Indexed ONCE, not per call. refresh() loops over phases, so a
  // querySelectorAll per phase costs O(phases x rows) on every keystroke — a
  // 200-phase report is several times slower per keypress than a 100-phase one
  // for that reason alone. Sorting reorders these rows but never replaces them,
  // so an index of element references stays correct across a sort.

  /**
   * The newest day this plan has any record of. The relative presets measure
   * back from HERE and never from the wall clock: "the last 30 days" read off
   * the system clock answers a different question every morning, and it would
   * stop the rendered report being byte-identical between two renders of one
   * unchanged plan.
   * @type {string} an ISO date, or '' when no task carries one
   */
  let DMAX = '';
  /** @type {Object<string, HTMLTableRowElement[]>} phase id -> its task rows */
  const TASKS = {};
  /** @type {Object<string, HTMLTableRowElement>} phase id -> its task-filter row */
  const TFROW = {};
  if (grouped) {
    for (const t of grouped.querySelectorAll('tbody tr.task')) {
      const k = t.getAttribute('data-phase');
      (TASKS[k] || (TASKS[k] = [])).push(t);
      const d = t.getAttribute('data-completed') || t.getAttribute('data-started') || '';
      if (d > DMAX) DMAX = d;
    }
    // Each task's detail row, resolved once and hung on the task row itself:
    // refresh() shows and hides the pair in the same pass, and a querySelector
    // per task per keystroke is the cliff this index exists to avoid.
    for (const d of grouped.querySelectorAll('tbody tr.taskdetail')) {
      const id = d.getAttribute('data-detail');
      const host = grouped.querySelector('tr.task .dtoggle[data-dfor="' + id + '"]');
      const row = host ? host.closest('tr.task') : null;
      if (row) { row.__detail = d; d.__task = row; }
    }
    for (const t of grouped.querySelectorAll('tbody tr.taskfilter')) {
      TFROW[t.getAttribute('data-phase')] = t;
    }
  }
  // Resolved once, with everything else that refresh() would otherwise have to
  // look up per phase per keystroke.
  phaseRows.forEach((pr) => { pr.__pmatch = pr.querySelector('.pmatch'); });

  // Segment rows, indexed once like everything else refresh() reads. Whether the
  // archive starts collapsed is the renderer's decision — it emits the toggle
  // only when done phases exist AND something else does too — and this script
  // only obeys it; a second copy of that rule here would be the two drifting
  // apart.
  const segRows = grouped
    ? Array.from(grouped.querySelectorAll('tbody tr.seghead')) : [];
  segRows.forEach((sh) => { sh.__seg = sh.getAttribute('data-seg'); });
  phaseRows.forEach((pr) => { pr.__seg = pr.getAttribute('data-seg') || ''; });

  // Which phases are on screen is a NAMED view, not a toggle somebody has to
  // find. `active` covers both segments of unfinished work; `archived` is done
  // AND cancelled; `all` is the escape hatch. The starting value is the
  // renderer's (it stamps `all` on a plan with nothing active), then whatever
  // the reader last chose, then whatever the link says.
  const viewSel = document.getElementById('audit-view');
  const VIEWS = { active: ['active', 'pending'], archived: ['archived'],
                  all: ['active', 'pending', 'archived'] };
  const defaultView = (grouped && grouped.getAttribute('data-defaultview')) || 'active';
  let viewMode = defaultView;

  /**
   * @param {string} seg a phase row's segment
   * @returns {boolean} whether the current view shows that segment
   */
  const inView = (seg) => (VIEWS[viewMode] || VIEWS.all).includes(seg);

  /**
   * Which segment each phase STATUS files under, read off the rows themselves.
   *
   * Python decides this in `_report_html._seg_of` — done and cancelled are the
   * archive, in_progress and blocked are active, everything else is pending — and
   * writing that rule again here would be a second copy of it, which is the defect
   * this report has spent a release removing. Every row already carries BOTH its
   * status and the segment Python filed it under, so the mapping is derived rather
   * than restated: a status the plan does not use has no row, no chip, and no
   * entry, which is the right answer for all three.
   *
   * @type {Object<string, string>}
   */
  const STATUS_SEG = {};
  phaseRows.forEach((pr) => {
    const st = pr.getAttribute('data-status');
    if (st && !(st in STATUS_SEG)) STATUS_SEG[st] = pr.__seg;
  });
  /** Can a phase of this status appear in the current view at all? */
  const statusInView = (st) => !st || inView(STATUS_SEG[st]);

  /**
   * Which segments each area tag actually occurs in.
   *
   * An area is not one segment the way a status is: `storefront` can tag an
   * active phase AND an archived one, so this keeps the whole set and asks
   * whether ANY of it survives the view. Derived from the rendered rows for the
   * same reason `STATUS_SEG` is - the alternative is a second copy of Python's
   * segment rule, and two copies of a rule is one copy and one lie.
   *
   * @type {Object<string, string[]>}
   */
  const AREA_SEGS = {};
  phaseRows.forEach((pr) => {
    (pr.getAttribute('data-area') || '').split(' ').filter(Boolean).forEach((a) => {
      if (!(a in AREA_SEGS)) AREA_SEGS[a] = [];
      if (AREA_SEGS[a].indexOf(pr.__seg) === -1) AREA_SEGS[a].push(pr.__seg);
    });
  });
  /** Can a phase tagged with this area appear in the current view at all? */
  const areaInView = (a) => !a || (AREA_SEGS[a] || []).some((seg) => inView(seg));

  /**
   * @param {string} pid a phase id
   * @returns {HTMLTableRowElement[]} that phase's task rows; empty when unknown
   */
  const tasksOf = (pid) => TASKS[pid] || [];

  /**
   * @param {string} pid a phase id
   * @returns {HTMLTableRowElement|null} that phase's task-filter row
   */
  const tfOf = (pid) => TFROW[pid] || null;

  /**
   * A row's text, lowercased once and kept on the row. The text of a rendered
   * report never changes, so re-lowercasing thousands of rows on every keystroke
   * is work with a constant answer.
   * @param {HTMLTableRowElement} r
   * @returns {string} the row's text content, lowercased
   */
  const hay = (r) => {
    if (r.__auditText === undefined) r.__auditText = r.textContent.toLowerCase();
    return r.__auditText;
  };

  /**
   * @param {HTMLTableRowElement} r
   * @param {string} term already lowercased; an empty term matches every row
   * @returns {boolean}
   */
  const textHit = (r, term) => !term || hay(r).includes(term);

  /**
   * Expand or collapse a phase row, keeping the ARIA state with the class so a
   * screen reader and the stylesheet never disagree.
   * @param {HTMLTableRowElement} pr
   * @param {boolean} open
   * @returns {void}
   */
  const setOpen = (pr, open) => {
    pr.classList.toggle('open', Boolean(open));
    pr.setAttribute('aria-expanded', open ? 'true' : 'false');
  };

  /**
   * The date a task SHOWS in the table: completed if it is, else started.
   * Filtering on a date other than the one printed in the row reads as a bug the
   * first time a reader checks one against the other.
   * @param {HTMLTableRowElement} t
   * @returns {string} an ISO date, or '' when the task carries neither
   */
  const taskDate = (t) =>
    t.getAttribute('data-completed') || t.getAttribute('data-started') || '';

  /**
   * @param {HTMLTableRowElement} t
   * @returns {boolean} whether the task falls inside the active date window
   */
  const dateOk = (t) => {
    if (!dFrom && !dTo) return true;
    const d = taskDate(t);
    // A task with no dates at all is not "inside every range"; it is unknown,
    // and a date filter is a question it has no answer to.
    if (!d) return false;
    // Plain string comparison. Fixed-width ISO dates order lexicographically,
    // and <input type=date> hands back exactly that shape — so a range test over
    // four thousand rows costs no Date parsing at all.
    return (!dFrom || d >= dFrom) && (!dTo || d <= dTo);
  };

  /**
   * @param {HTMLTableRowElement} pr a phase row
   * @returns {boolean} whether any selected area tag admits this phase; true
   *   whenever nothing is selected
   */
  const areaOk = (pr) => {
    if (!areaFilter.length) return true;
    // The renderer joins a phase's tags with single spaces into `data-area`, so
    // splitting on whitespace and dropping the empties reads an untagged phase
    // as no tags rather than one empty tag.
    const tags = (pr.getAttribute('data-area') || '').split(/\s+/);
    return tags.some((tag) => tag && areaFilter.includes(tag));
  };
