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
    if (h.indexOf('#!') !== 0) return Object.create(null);
    return h.slice(2).split('&').filter(Boolean).reduce((acc, pair) => {
      const i = pair.indexOf('=');
      const k = i < 0 ? pair : pair.slice(0, i);
      const v = i < 0 ? '' : pair.slice(i + 1);
      // A malformed percent-escape costs one value, never the whole hash: the
      // key stays present so the control it drives is still restored.
      try { acc[k] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { acc[k] = ''; }
      return acc;
    // No prototype, because every key here is whatever the link said. On a plain
    // object `acc['__proto__'] = 'dark'` is swallowed by the prototype setter
    // rather than stored, so `#!__proto__=x` would decode to an empty hash and
    // silently restore the LOCAL copy instead of the view the link names.
    }, Object.create(null));
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

  // `isDark()` is `shared/theme.js`'s, concatenated ahead of this part. This
  // surface owned the guarded reading of `matchMedia` and the panel owned an
  // unguarded one; the shared part keeps this one, for the reasons written there.

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
   * The height an element pins over the content: its rendered height while it
   * is sticky, and nothing while it scrolls with the page. Below 52rem the top
   * bar is not sticky, and an offset still carrying its height would leave the
   * strip, the filter bar and every anchor hanging a bar's height below the
   * top of the screen with nothing above them. Read off the computed style so
   * the stylesheet stays the one place that says where the bar sticks.
   * @param {Element|null} el
   * @returns {number}
   */
  const pinnedPx = (el) => (el && getComputedStyle(el).position === 'sticky' ? px(el) : 0);

  /**
   * Publish the measured height of each sticky layer as a custom property.
   * @returns {void}
   */
  const measureStack = () => {
    if (toolbar) root.style.setProperty('--topbar-h', pinnedPx(toolbar) + 'px');
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

  // More filters, opened where it can be seen. On a phone the open bar leaves the sticky stack (the 52rem block makes it
  // static, so an open panel cannot pin itself over the table). Opened while the
  // bar was STUCK, that sends the bar back to its place in the flow - above the
  // top of the screen - and the panel the reader just asked for opens out of
  // sight. So an opened disclosure that is not wholly on screen is scrolled to
  // the nearest edge. "On screen" starts below what stays pinned, and that line
  // is the disclosure's own scroll-margin, which the stylesheet computes from
  // the sticky offsets - read back resolved rather than recomputed here.
  // Measured after the frame the layout changes in, and only acted on when the
  // disclosure is off screen, so a panel that opened in view never moves the page.
  const moreFilters = document.querySelector('.fdetails');
  if (moreFilters) {
    moreFilters.addEventListener('toggle', () => {
      if (!moreFilters.open) return;
      requestAnimationFrame(() => {
        const b = moreFilters.getBoundingClientRect();
        const clear = parseFloat(getComputedStyle(moreFilters).scrollMarginTop) || 0;
        if (b.top < clear - 1 || b.bottom > window.innerHeight) {
          moreFilters.scrollIntoView({ block: 'nearest' });
        }
      });
    });
  }

  // --- the table frames, released where their table fits -----------------------

  // The sheet contains every table in a frame that scrolls sideways inside
  // itself, so with no script no table can widen the page. The cost is the
  // column headers: a header sticks to its nearest scrolling ancestor, which is
  // then the frame, and the frame never scrolls vertically. So a frame whose
  // table fits it is marked, and the sheet answers the mark by releasing the
  // frame and pinning its headers to the page again. The mark is only ever a
  // measurement: a frame whose table grows past it - a narrower window, rows
  // expanded, a filter or a view that brings a wider row in - loses it on the
  // next measurement, and the frame is contained again.
  const TABLE_FIT_ATTR = 'data-fits';

  /**
   * Mark each frame whose table fits it, and unmark every other one. The width
   * is read with the frame's overflow released, because the question is how
   * wide the table is when nothing holds it in; the frame's own value is put
   * back before the next frame is read.
   * @param {Element[]} wraps the `.tablewrap` frames to measure
   * @returns {void}
   */
  const markTableFits = (wraps) => {
    for (const w of wraps) {
      const t = w.querySelector('table');
      const held = w.style.overflowX;
      w.style.overflowX = 'visible';
      const fits = Boolean(t) && t.scrollWidth <= w.clientWidth;
      w.style.overflowX = held;
      if (fits) w.setAttribute(TABLE_FIT_ATTR, '');
      else w.removeAttribute(TABLE_FIT_ATTR);
    }
  };

  // Coalesced to a frame, like the scroll listener below: a drag-resize or a
  // filter pass reports many changes, and one measurement per paint answers
  // all of them. The frames are queried per pass rather than kept from load:
  // it is one query, and the answer then never rests on a list taken earlier.
  let tableFitQueued = false;

  /**
   * Ask for one re-measurement of every table frame on the next frame.
   * @returns {void}
   */
  const queueTableFit = () => {
    if (tableFitQueued) return;
    tableFitQueued = true;
    requestAnimationFrame(() => {
      tableFitQueued = false;
      markTableFits(Array.from(document.querySelectorAll('.tablewrap')));
    });
  };
  // Observed rather than hooked event by event: a frame changes width with the
  // window, and a table changes size with every expand, filter and view switch,
  // so watching the two boxes follows each of those without a list of them to
  // keep in step. The window's own resize is the fallback where no observer
  // exists.
  if (window.ResizeObserver) {
    const fitRo = new ResizeObserver(queueTableFit);
    for (const w of document.querySelectorAll('.tablewrap')) {
      fitRo.observe(w);
      const t = w.querySelector('table');
      if (t) fitRo.observe(t);
    }
  }
  window.addEventListener('resize', queueTableFit, { passive: true });
  queueTableFit();

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
    const fold = pinnedPx(toolbar) + (snav && stripQ && stripQ.matches ? px(snav) : 0) + 4;
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
  // No prototype, because the keys are phase ids and the schema puts no
  // `pattern` on an id at all. On a plain object `expanded['__proto__'] = true`
  // is swallowed, so that phase could never be opened; `expanded.constructor`
  // reads back as a function, so that phase renders open before anyone clicks
  // it and the first click closes it.
  const expanded = Object.create(null);
  // The `try` is for the PARSE, not for storage: storageGet cannot throw, so a
  // refused read and a corrupt stored value no longer share one handler.
  // Own keys are COPIED IN rather than the map being replaced: JSON.parse hands
  // back a plain object, and a corrupt value hands back a string or an array,
  // both of which used to be adopted whole by `|| {}` and then written to.
  try { Object.assign(expanded, JSON.parse(storageGet(STORE))); } catch (e) {}

  /**
   * Write the expand state back to storage, ignoring a refusal.
   * @returns {void}
   */
  const persist = () => {
    storageSet(STORE, JSON.stringify(expanded));
  };

  // --- filter state, and the controls that write it ----------------------------

  let phaseStatus = '';   // toolbar: filter which PHASES show, by phase status
  // Keyed by phase id, so prototype-free for the reason `expanded` above is.
  let taskStatus = Object.create(null);   // per phase: filter its TASKS by status
  let modelFilter = '';   // panel: only tasks run by this model
  let dFrom = '';         // panel: ISO dates, compared as plain strings
  let dTo = '';
  let preset = '';        // which relative-span chip is lit, if any
  // The test gate's TWO axes, and they are independent on purpose. `tevFilter`
  // is what a task's last recorded run SAID; `tevFlag` is what else was true
  // about that run. A gate can fail and also rewrite the tree, so a reader
  // hunting rewrites cannot reach them through the status axis at all, and a
  // single combined control would need a name for every pairing of the two.
  let tevFilter = '';     // panel: only tasks whose recorded run reached this
  let tevFlag = '';       // panel: only tasks whose run carries this observation

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
  // Absent on a plan that points at no recorded run: the renderer emits no chip
  // row at all rather than an empty one, so these are null and every reader
  // below already tolerates a missing control.
  const tevBar = document.getElementById('audit-tev');
  const tevFlagBar = document.getElementById('audit-tevf');
  const fromInput = document.getElementById('audit-from');
  const toInput = document.getElementById('audit-to');
  const presetBar = document.getElementById('audit-presets');
  const fcount = document.getElementById('audit-fcount');
  const clearBtns = Array.from(document.querySelectorAll('[data-clear]'));
  const norow = grouped ? grouped.querySelector('tr.norows') : null;
  // The empty state's two sentences: the plain one, and the slot that names the
  // matches the view is hiding, with the press that shows them.
  const norowSays = norow ? norow.querySelector('[data-norows-says]') : null;
  const norowOutside = norow ? norow.querySelector('[data-outside]') : null;
  const norowOutsideSays = norow ? norow.querySelector('[data-outside-says]') : null;
  const showAllBtn = norow ? norow.querySelector('[data-showall]') : null;

  // The author chips live in the Usage section and scope ONLY it: tasks record
  // no author, so these never enter refresh() or touch the task table.
  const authorBar = document.getElementById('audit-authors');
  const auNote = document.getElementById('audit-au-note');
  let auFilter = '';
  const smCells = Array.from(document.querySelectorAll('.smcell'));
  const auRows = Array.from(document.querySelectorAll('.rank[data-author]'));

  // The header filter row is a second line of the top bar. Each control
  // is a compact twin of a filter that already exists (author chips, area chips,
  // the panel's date pair) over the SAME state variables, so the two
  // presentations can never disagree about what is filtered.
  const gFrom = document.getElementById('audit-gfrom');
  const gTo = document.getElementById('audit-gto');
  const gClear = document.getElementById('audit-gclear');
  const auSelect = document.getElementById('audit-au-select');
  const areaSelect = document.getElementById('audit-area-select');

  // --- the filter axes, declared once ------------------------------------------

  /**
   * Every filter this page offers, declared ONCE.
   *
   * Clear, the link writer, the restore after a reload and the counters in
   * refresh() each used to list the axes by hand, and three axes in a row were
   * added to some of those lists and not the others: a filter Clear could not
   * lift, still counted, still written to the link and restored on the next
   * open. They all iterate this array now, so an axis declared here is cleared,
   * encoded, restored and counted without being named anywhere else.
   *
   * What an entry carries:
   * - `attrs`: the chip attributes its controls carry, so a test can hold the
   *   chips the page wires against the axes declared here.
   * - `keys`: its link keys, in the order `encode` returns values; empty when
   *   the axis is deliberately not kept, and then `unkept` says why.
   * - `scope`: what it narrows - `text` (the search), `phases` (whole phase
   *   rows), `tasks` (tasks, hiding a phase none of whose tasks survive),
   *   `drill` (tasks inside one phase only) or `usage` (the Usage section, never
   *   the table).
   * - `counts`: whether the More-filters badge counts it.
   * - `on`, `reset`, `paint`, `encode`, `decode`: is it filtering; return it to
   *   its default; repaint every control that shows it; its values for `keys`;
   *   take its state from the decoded link, saying whether there was any.
   *
   * The behaviours call painters declared in later parts (`highlight`,
   * `paintAreas`, `paintDates`, `applyAuthor`, `tfHosts`). They run only once
   * the whole script has loaded, never while this array is being built.
   *
   * @type {Array<{id: string, attrs: string[], keys: string[], unkept?: string,
   *   scope: string, counts: boolean, on: () => boolean, reset: () => void,
   *   paint: () => void, encode: () => string[],
   *   decode: (h: Object<string, string>) => boolean}>}
   */
  const FILTER_AXES = [
    {
      id: 'search', attrs: [], keys: ['q'], scope: 'text', counts: false,
      on: () => !!q && q.value.trim() !== '',
      reset: () => { if (q) q.value = ''; },
      paint: () => {},
      encode: () => [q ? q.value.trim() : ''],
      decode: (h) => { if (!q || !h.q) return false; q.value = h.q; return true; },
    },
    {
      id: 'phase-status', attrs: ['data-ps'], keys: ['ps'], scope: 'phases',
      counts: false,
      on: () => phaseStatus !== '',
      reset: () => { phaseStatus = ''; },
      paint: () => { if (phaseStatusBar) highlight(phaseStatusBar, 'data-ps', phaseStatus); },
      encode: () => [phaseStatus],
      decode: (h) => { if (!h.ps) return false; phaseStatus = h.ps; return true; },
    },
    {
      // Space-joined in the link, mirroring the data-area attribute: one
      // separator rule for both carriers of a tag list.
      id: 'area', attrs: ['data-a'], keys: ['a'], scope: 'phases', counts: true,
      on: () => areaFilter.length > 0,
      reset: () => { areaFilter = []; },
      paint: () => { paintAreas(); },
      encode: () => [areaFilter.join(' ')],
      decode: (h) => {
        if (!h.a) return false;
        areaFilter = h.a.split(/\s+/).filter(Boolean);
        return true;
      },
    },
    {
      id: 'model', attrs: ['data-m'], keys: ['m'], scope: 'tasks', counts: true,
      on: () => modelFilter !== '',
      reset: () => { modelFilter = ''; },
      paint: () => { if (modelBar) highlight(modelBar, 'data-m', modelFilter); },
      encode: () => [modelFilter],
      decode: (h) => { if (!h.m) return false; modelFilter = h.m; return true; },
    },
    {
      // Two axes and two keys, never one: a link can carry either alone.
      id: 'test-gate', attrs: ['data-tev'], keys: ['tev'], scope: 'tasks',
      counts: true,
      on: () => tevFilter !== '',
      reset: () => { tevFilter = ''; },
      paint: () => { if (tevBar) highlight(tevBar, 'data-tev', tevFilter); },
      encode: () => [tevFilter],
      decode: (h) => { if (!h.tev) return false; tevFilter = h.tev; return true; },
    },
    {
      id: 'observed', attrs: ['data-tevf'], keys: ['tevf'], scope: 'tasks',
      counts: true,
      on: () => tevFlag !== '',
      reset: () => { tevFlag = ''; },
      paint: () => { if (tevFlagBar) highlight(tevFlagBar, 'data-tevf', tevFlag); },
      encode: () => [tevFlag],
      decode: (h) => { if (!h.tevf) return false; tevFlag = h.tevf; return true; },
    },
    {
      // The presets are a way of SETTING this range, not a filter of their
      // own: the span a lit chip chose is what from/to carry, so a restored
      // range comes back as a range and the chip stays unlit.
      id: 'dates', attrs: ['data-days'], keys: ['from', 'to'], scope: 'tasks',
      counts: true,
      on: () => dFrom !== '' || dTo !== '',
      reset: () => { dFrom = ''; dTo = ''; preset = ''; },
      paint: () => { paintDates(); },
      encode: () => [dFrom, dTo],
      decode: (h) => {
        if (!h.from && !h.to) return false;
        dFrom = h.from || ''; dTo = h.to || '';
        return true;
      },
    },
    {
      // Scopes the Usage section only: tasks record no author, so this never
      // narrows the table and the badge in the table's own panel skips it.
      id: 'author', attrs: ['data-au'], keys: ['au'], scope: 'usage', counts: false,
      on: () => auFilter !== '',
      reset: () => { auFilter = ''; },
      paint: () => {
        if (authorBar) highlight(authorBar, 'data-au', auFilter);
        applyAuthor();
      },
      encode: () => [auFilter],
      decode: (h) => { if (!h.au) return false; auFilter = h.au; return true; },
    },
    {
      id: 'task-status', attrs: ['data-ts'], keys: [],
      unkept: 'keyed by phase id, so the link would carry a list as long as '
        + 'the plan to describe a drill-down inside one row',
      scope: 'drill', counts: true,
      on: () => Object.keys(taskStatus).some((pid) => taskStatus[pid] !== ''),
      reset: () => { taskStatus = Object.create(null); },
      paint: () => {
        tfHosts.forEach((h) => { highlight(h, 'data-ts', taskStatus[h.__pid] || ''); });
      },
      encode: () => [],
      decode: () => false,
    },
  ];

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
  // Both are keyed by `data-phase`, i.e. by a phase id out of the manifest, and
  // both are BUILT rather than read from a literal - so the fix is a map with no
  // prototype rather than a guarded read. On a plain object a phase called
  // `constructor` made `TASKS[k]` answer with a function, and `.push` on it
  // threw at load: one manifest id blanked the whole interactive layer of a
  // report somebody opened from a link.
  /** @type {Object<string, HTMLTableRowElement[]>} phase id -> its task rows */
  const TASKS = Object.create(null);
  /** @type {Object<string, HTMLTableRowElement>} phase id -> its task-filter row */
  const TFROW = Object.create(null);
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
  // `lookup`, not `VIEWS[viewMode]`: VIEWS is a literal this file wrote, and
  // `viewMode` is whatever the fragment said. `#!v=constructor` passed the guard
  // in exports.js (a function is truthy), landed here, and `.includes` on
  // Object.prototype.constructor threw out of the first filter pass.
  const inView = (seg) => (lookup(VIEWS, viewMode) || VIEWS.all).includes(seg);

  /**
   * The current view as the View select words it, so the counter and the
   * empty state name the basis in the reader's own vocabulary rather than a
   * second copy of it. The view id stands in only when the select is absent,
   * which is still the true basis, merely terser.
   *
   * @returns {string} e.g. "Active & pending"
   */
  const viewName = () => {
    const opt = viewSel ? [...viewSel.options].find((o) => o.value === viewMode) : null;
    return opt ? opt.textContent : viewMode;
  };

  // Which order the phase rows are listed in, the same shape as the view above:
  // the element, the vocabulary, the default. `plan` is the written plan, which
  // is how the table always ARRIVES; `priority` is the overlay, spelled the way
  // the panel's Overview spells it. The renderer emits this select only where a
  // phase is actually pinned, so a null here means the plan has no priority to
  // sort by — which is why every path that changes the order asks for the
  // element rather than for the option name alone.
  const sortSel = document.getElementById('audit-sort');
  const defaultOrder = 'plan';
  let phaseOrder = defaultOrder;

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
   * Prototype-free: the key is a phase STATUS, and `_seg_of` on the Python side
   * says in as many words that an unknown vocabulary value reaches it. With a
   * prototype, `'constructor' in STATUS_SEG` was already true, so the entry was
   * never recorded and every phase of that status was filtered out of every
   * view - the `in` test walks the chain exactly as the bracket read does.
   *
   * @type {Object<string, string>}
   */
  const STATUS_SEG = Object.create(null);
  phaseRows.forEach((pr) => {
    const st = pr.getAttribute('data-status');
    if (st && !(st in STATUS_SEG)) STATUS_SEG[st] = pr.__seg;
  });
  /** Can a phase of this status appear in the current view at all? */
  const statusInView = (st) => !st || inView(STATUS_SEG[st]);

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
   * @param {HTMLTableRowElement} t a task row
   * @returns {boolean} whether the task's recorded run carries the selected
   *   observation; true whenever none is selected
   */
  const tevFlagOk = (t) => {
    if (!tevFlag) return true;
    // Padded both sides before the search, so a marker name can never match
    // inside a longer one. The renderer joins these with single spaces, which is
    // the same rule `data-area` already uses for its list.
    return (' ' + (t.getAttribute('data-tev-flags') || '') + ' ')
      .indexOf(' ' + tevFlag + ' ') !== -1;
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
