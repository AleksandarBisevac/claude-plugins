/**
 * The responsive width ladder, walked rung by rung.
 *
 * Shared by both browser gates. `walkResponsiveLadder` used to read a `FAST`
 * const from capture-screenshots.mjs's module scope, so the REPORT gate's ladder
 * width depended on a flag parsed by a different file from `process.argv` - a
 * coupling neither caller documented and only one of them knew about. It is an
 * explicit option now, defaulting to the full ladder.
 */

/* ---- the responsive contract ------------------------------------------------
 *
 * ONE ladder for both surfaces, exported so tools/check-report-interactive.mjs
 * drives the identical widths. Two lists would drift the way `.shell` and the
 * nav breakpoint already have (92rem vs 96rem, 70rem vs 72rem \u2014 writing-css
 * names both), and a width that is only in one list is a width the other
 * surface is never asked about.
 *
 * WHY THESE WIDTHS. Every entry sits either side of a breakpoint one of the two
 * stylesheets DECLARES. A breakpoint is precisely where the layout changes, so
 * it is where it breaks; a ladder of round numbers tests whatever happens to
 * fall between them. `@media (max-width:Xrem)` matches AT X*16 px (the root
 * font-size is the UA's 16px \u2014 neither sheet sets one), so the pair that
 * brackets it is X*16 and X*16+1, and `min-width` brackets the other way.
 *
 *   320  / 390   not breakpoints \u2014 the narrowest screen this UI claims, and the
 *                phone. 320 is where Settings' unwrapped label put 16px back on
 *                the document (F8) and 390 is where the report's filter panel
 *                was found hanging off the left edge. Both are kept because a
 *                defect was measured at each.
 *   544  / 545   34rem. report: .colswrap ticks shrink, .bud drops its bars,
 *                the heatmap re-lays. panel: .who disappears, dialog.confirm
 *                and dialog.drawer go full-bleed, .savenote caps its body.
 *   640  / 641   40rem. report: body re-pads and re-sizes, #audit-q takes the
 *                first row, .uphase/.rank/.mm collapse to one column.
 *                panel: .rule goes to one column and .rulehead disappears.
 *   688          not a breakpoint: A4 portrait inside the sheet's 1.4cm margin,
 *                the width the print rules are actually read at \u2014 and it sits
 *                INSIDE 52rem, so the phone rules apply to paper there.
 *   768  / 769   48rem. report: .tb-id takes the whole row. panel: two blocks.
 *   832  / 833   52rem, the report's whole tablet block and the biggest single
 *                change either sheet makes \u2014 .tablewrap starts scrolling, the
 *                <thead> unsticks, .filterpanel comes back into flow and
 *                .sectools stops being sticky while that panel is open.
 *   960  / 961   60rem. panel: .who drops its second line.
 *   1120 / 1121  70rem, the panel's nav breakpoint: sidebar becomes a strip.
 *   1152 / 1153  72rem, the report's shell breakpoint: the SAME change, 32px
 *                later, because the two sheets disagree about where it is.
 *   1200         not a breakpoint: the viewport every committed screenshot is
 *                taken at, and the only state between the shell breakpoints
 *                and .topgrid's.
 *   1247 / 1248  78rem, the only min-width rule in either sheet: .topgrid goes
 *                to two columns.
 *   1512         a laptop, and the viewport check-report-interactive opens at.
 *
 * No width here depends on the host's scrollbar model \u2014 that is pinned at
 * launch with --disable-features=OverlayScrollbar, because it moved geometry by
 * 15px between hosts and decided a release gate once.
 */
// --- the ladder, and measuring one rung of it ----------------------------------

export const RESPONSIVE_LADDER = [
  320, 390, 544, 545, 640, 641, 688, 768, 769, 832, 833,
  960, 961, 1120, 1121, 1152, 1153, 1200, 1247, 1248, 1512,
];

/**
 * One width's worth of the contract, measured IN THE PAGE. Serialized into the
 * browser by Playwright, so it closes over nothing and takes everything it
 * needs in `opts`.
 *
 * `opts.atEnd` says which end of the document the caller has scrolled to. It
 * changes exactly one thing \u2014 which sticky chrome is allowed to sit on top of a
 * control \u2014 and the reason is in the comment on `escapable` below.
 *
 * The whole measurement is one synchronous pass on purpose. The panel re-renders
 * its forms from a 5s poll; a measurement split across two evaluates can read a
 * rect from before the re-render and hit-test after it, and then reports a
 * collision between a node and its own replacement.
 */
export const measureResponsiveFrame = (opts) => {
  const de = document.documentElement;
  const vw = de.clientWidth, vh = de.clientHeight;
  const nameOf = (n) => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '')
    + (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  // Not painted at all, so not this contract's business: display:none,
  // visibility:hidden, and \u2014 the one that costs a day if you miss it \u2014 a
  // subtree inside a closed <details>. Chromium skips that subtree with
  // content-visibility rather than display:none, which leaves every descendant
  // reporting a STALE rect and a non-null offsetParent while painting nothing.
  // The report's More-filters panel is exactly that, and read through
  // offsetParent it looks like an absolutely-positioned block lying across the
  // phase table at eleven of the widths below.
  const painted = (n) => n.checkVisibility({ contentVisibilityAuto: true,
    visibilityProperty: true });
  const opaque = (n) => n.checkVisibility({ contentVisibilityAuto: true,
    visibilityProperty: true, opacityProperty: true });
  const all = [...document.body.querySelectorAll('*')];

  // (2) Nothing outside its own frame. Anything with a scrolling or clipping
  // ancestor is excluded by asking its ancestors rather than by listing
  // selectors: overflow-x anything but `visible` scrolls or clips its content
  // and cannot push the document, which is the distinction being drawn.
  // BOTH edges, because the two failures look nothing alike \u2014 past the right
  // edge the document scrolls, past the left edge nothing scrolls at all and
  // the content is simply gone (F9's signature, and the filter panel's).
  const framed = (n) => {
    for (let p = n.parentElement; p; p = p.parentElement) {
      if (getComputedStyle(p).overflowX !== 'visible') return true;
    }
    return false;
  };
  const outside = [];
  for (const n of all) {
    const r = n.getBoundingClientRect();
    if (r.width < 0.5 && r.height < 0.5) continue;
    if (!painted(n) || framed(n)) continue;
    if (r.right > vw + 1) outside.push(`${nameOf(n)} right@${Math.round(r.right)}`);
    else if (r.left < -1) outside.push(`${nameOf(n)} left@${Math.round(r.left)}`);
  }

  // (3) and (4a): the controls.
  const CONTROLS = 'a[href],button,input:not([type=hidden]),select,textarea,'
    + 'summary,[role="button"]';
  const controls = all.filter((n) => {
    if (!n.matches(CONTROLS) || !opaque(n)) return false;
    const r = n.getBoundingClientRect();
    return r.width > 0.5 && r.height > 0.5;
  });

  // (3) No overlap between things that must not overlap, asked as a HIT TEST
  // rather than as rectangle arithmetic: a control must be the topmost thing at
  // its own centre. That is the question a reader actually asks \u2014 two controls
  // stacked, a menu over its own input and a bar over a row all come out as the
  // same answer \u2014 and it cannot accuse a deliberately layered thing of doing
  // its job, because the thing on top IS what the click would reach.
  //
  // Sticky chrome is the one case that needs the scroll position. A bar pinned
  // to an edge sits over whatever is beneath it at every scroll offset, and
  // that is not a defect while the reader can still scroll the content out from
  // under it. At the TOP of the document only a bottom-anchored bar is
  // escapable (scroll down and the row rises past it); at the END only a
  // top-anchored one is (scroll up). Anything else covering a control covers it
  // for good. Anchoring is read off `top`/`bottom` being definite rather than
  // off the box's position, because the panel's tab strip pins at 56px, not 0.
  const escapable = (n) => {
    for (let p = n; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
      const edge = cs.top !== 'auto' ? 'top' : cs.bottom !== 'auto' ? 'bottom' : null;
      if (edge === (opts.atEnd ? 'top' : 'bottom')) return true;
    }
    return false;
  };
  // A control scrolled out of its own frame is not on screen at all, and the
  // point where its rect claims to be shows whatever the frame is painting
  // there. Skipped rather than reported: the frame is doing its job, and the
  // policy table is 577 controls wide.
  const inFrames = (n, x, y) => {
    for (let p = n.parentElement; p; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const r = p.getBoundingClientRect();
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) return false;
    }
    return true;
  };
  let hitTested = 0;
  const buried = [];
  for (const n of controls) {
    const r = n.getBoundingClientRect();
    const cx = Math.round(r.left + r.width / 2), cy = Math.round(r.top + r.height / 2);
    if (cx < 0 || cx > vw - 1 || cy < 0 || cy > vh - 1) continue;
    if (!inFrames(n, cx, cy)) continue;
    hitTested += 1;
    const hit = document.elementFromPoint(cx, cy);
    if (hit === n || (hit && (n.contains(hit) || hit.contains(n)))) continue;
    // A <label> over its own control still activates it.
    if (hit && hit.tagName === 'LABEL' && hit.control === n) continue;
    if (hit && escapable(hit)) continue;
    buried.push(`${nameOf(n)} under ${hit ? nameOf(hit) : 'nothing paintable'}`);
  }

  // (4a) A control whose box has collapsed. The floor is 4px in either
  // direction, which separates "the layout crushed it" \u2014 a flex or grid item
  // squeezed to a line \u2014 from "small by design". It is deliberately NOT a tap
  // target rule: Settings' 27 remove-a-path buttons measure 6.4x12 at every
  // width on this ladder, which is a sizing decision to argue about and not a
  // responsive failure, so the smallest control seen is REPORTED instead.
  let smallest = null;
  const collapsed = [];
  for (const n of controls) {
    const r = n.getBoundingClientRect();
    if (n.tagName !== 'A' && (!smallest || r.width * r.height < smallest.area)) {
      smallest = { name: nameOf(n), w: r.width, h: r.height, area: r.width * r.height };
    }
    if (n.tagName === 'A') continue;
    if (r.width < 4 || r.height < 4) {
      collapsed.push(`${nameOf(n)} ${r.width.toFixed(1)}x${r.height.toFixed(1)}`);
    }
  }

  // (4b) Text clipped to unreadability WITH NO WAY TO REACH IT. Both halves are
  // load-bearing. An ellipsis is a design decision, so the rule is not "clipped"
  // \u2014 it is that less than a quarter of the string survives AND the whole of it
  // is nowhere: no title, no aria-label, no data-tip, on the element or on
  // anything containing it. The panel clips a great deal and hangs the full
  // value off a tooltip every time; the report's ranked-list names carry none.
  //
  // TEXT THAT IS NEVER PAINTED IS NOT A READING FAILURE. `checkVisibility`
  // answers display/visibility/content-visibility and knows nothing about
  // clip-path, so the visually-hidden recipe — a ~1px box with the rest clipped
  // away, which is how a <th> can be announced without being drawn — arrived
  // here as "shows 1px of 84px" and failed the panel at all 21 widths. Nothing
  // survives, so "less than a quarter survives" is not a claim about it.
  //
  // The exclusion is deliberately NOT "has class .vh": it asks for the recipe
  // itself — a box too small to hold a glyph AND an explicit clip. A label the
  // layout crushed to a line still carries no clip-path and still fails, which
  // is the case this must not swallow. And it is COUNTED, so losing it, or
  // widening it until it eats a real one, shows up in the summary rather than
  // as a check that quietly got easier.
  // F19: ask what a READER can reach, not which attribute is present. This
  // codebase deliberately moves tooltip text into a JS property -- `report.js`
  // sets `node.__tip` and its hover layer walks ancestors looking for it (the
  // same walk mirrored here), promoting it to a real `title` only on demand. So
  // an oracle that only reads attributes declared every tooltip-managed element
  // in the Usage section unreachable: measured on the shipped report at 1153px,
  // all 11 `.rank .nm` clipped to 49-78%, a `__tip` ancestor on every one of
  // them holding the full string, and zero `title` ancestors.
  //
  // It OVER-reported, so it was noise rather than a hole -- and it still cost a
  // real finding: the first record of what became F17 read "a truncated name
  // with nothing carrying the whole of it", which was false. The string was
  // carried; the actual fault was elsewhere and worse. A check that cries wolf
  // gets skimmed, and the thing it was really pointing at gets written down
  // wrong.
  const tipCarrier = (n) => {
    for (let p = n; p; p = p.parentElement) if (p.__tip) return p;
    return null;
  };
  const clipped = [];
  let unpainted = 0;
  let jsCarried = 0;
  for (const n of all) {
    if (n.children.length || !(n.textContent || '').trim()) continue;
    if (!opaque(n)) continue;
    const ncs = getComputedStyle(n);
    if (ncs.clipPath !== 'none' && n.clientWidth <= 2 && n.clientHeight <= 2) {
      unpainted += 1;
      continue;
    }
    if (!/hidden|clip/.test(ncs.overflowX)) continue;
    if (n.scrollWidth - n.clientWidth <= 1) continue;
    // Counted, so widening the oracle shows up in the summary instead of as a
    // check that quietly got easier -- the rule the unpainted exclusion follows.
    const byJs = tipCarrier(n);
    if (byJs) jsCarried += 1;
    clipped.push({
      name: nameOf(n), cw: n.clientWidth, sw: n.scrollWidth,
      shown: n.clientWidth / n.scrollWidth,
      reachable: !!(n.title || n.getAttribute('aria-label')
        || n.getAttribute('data-tip') || n.closest('[title],[data-tip],[aria-label]')
        || byJs),
    });
  }
  const stranded = clipped.filter((c) => !c.reachable && c.shown < 0.25);
  const tightest = clipped.filter((c) => !c.reachable)
    .sort((a, b) => a.shown - b.shown)[0] || null;

  return {
    vw, vh,
    doc: de.scrollWidth - vw, body: document.body.scrollWidth - vw,
    elements: all.length, controls: controls.length, hitTested,
    clipExamined: clipped.length, clipUnpainted: unpainted, clipJsCarried: jsCarried,
    outside: outside.slice(0, 3), outsideN: outside.length,
    buried: buried.slice(0, 3), buriedN: buried.length,
    collapsed: collapsed.slice(0, 3), collapsedN: collapsed.length,
    stranded: stranded.slice(0, 3).map((c) =>
      `${c.name} shows ${c.cw}px of ${c.sw}px`), strandedN: stranded.length,
    smallest: smallest && { name: smallest.name, w: +smallest.w.toFixed(1),
      h: +smallest.h.toFixed(1) },
    tightest: tightest && { name: tightest.name, shown: +tightest.shown.toFixed(2),
      cw: tightest.cw, sw: tightest.sw },
  };
};

/**
 * Drive RESPONSIVE_LADDER over one view and assert the contract at every width.
 *
 * `report` is `fail`-shaped and `ok` is `note`-shaped, so the same walk serves
 * both this file and check-report-interactive.mjs, which keep their failures in
 * different places. `tally` accumulates what was MEASURED across every view a
 * caller drives, and the caller asserts it is non-zero afterwards \u2014 that is the
 * vacuity guard, and it is the whole reason this is written as a tally rather
 * than as twenty-one independent passes. The 390px overflow assertion this
 * generalises ran on one tab of five for its entire life and was green
 * throughout; a check that measured nothing has to fail, not pass.
 *
 * Every width is measured at BOTH ends of the document, because a bar pinned to
 * the bottom traps content only at the end and one pinned to the top only at
 * the start.
 */
// --- walking the ladder, and whether it measured anything ----------------------

export async function walkResponsiveLadder(page, label, tally,
                                           { report: reportOne, ok, fast = false }) {
  const seen = [];
  // In --fast mode only the rungs that BOUND a rule are walked: the narrowest
  // viewport, both sides of the 768/769 and 1247/1248 breakpoints, and the widest.
  // A regression that survives those four boundaries and dies at 961px exists, so
  // this is a sampling, not an equivalent — which is why the skip is announced.
  // EXPLICIT, not a const read out of another module's scope. This used to be
  // capture-screenshots.mjs's `FAST`, parsed from process.argv there - so the
  // REPORT gate, which never mentions --fast, narrowed its ladder whenever that
  // flag happened to be on the command line. A caller that wants the sampling now
  // says so.
  const ladder = fast ? [320, 768, 769, 1247, 1248, 1512] : RESPONSIVE_LADDER;
  // The extremes are carried ACROSS the ladder rather than read off the last
  // rung. The tightest clip on the report is at 1153px and the widest viewport
  // has none at all, so a summary that reported the final width would have said
  // "no unreachable clipping" about a document that clips a model name down to
  // 42% one rung earlier. A number nobody can see drift is a threshold nobody
  // notices being approached.
  let tightest = null, smallest = null, dirty = 0, unpainted = 0, jsCarried = 0;
  for (const width of ladder) {
    await page.setViewportSize({ width, height: 900 });
    // A resize is answered on the next frame; reading the layout mid-reflow
    // reports the width it came from and calls that a defect.
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
    await page.waitForTimeout(120);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(90);
    const top = await page.evaluate(measureResponsiveFrame, { atEnd: false });
    await page.evaluate(() =>
      window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(90);
    const end = await page.evaluate(measureResponsiveFrame, { atEnd: true });
    await page.evaluate(() => window.scrollTo(0, 0));

    tally.widths += 1;
    tally.elements += top.elements;
    tally.controls += top.controls;
    tally.hitTested += top.hitTested + end.hitTested;
    tally.clipExamined += top.clipExamined;
    unpainted += top.clipUnpainted;
    jsCarried += top.clipJsCarried;
    seen.push(top.hitTested + end.hitTested);

    const at = `${label} at ${width}px`;
    // Every report also counts, so the summary below cannot call a view clean
    // that had a width fail in it. That sentence was printed once, next to the
    // failure it contradicted.
    const report = (m) => { dirty += 1; reportOne(m); };
    if (top.doc > 1 || top.body > 1) {
      report(`${at}: the document scrolls sideways by ${top.doc}px (body `
        + `${top.body}px) in a ${top.vw}px viewport \u2014 widest: `
        + `${top.outside.join(', ') || 'nothing outside its own frame, so a '
        + 'margin or a negative offset'}`);
    } else if (top.outsideN) {
      report(`${at}: ${top.outsideN} element(s) sit outside the viewport with no `
        + `frame of their own to scroll in \u2014 ${top.outside.join(', ')}`);
    }
    for (const [where, m] of [['at rest', top], ['scrolled to the end', end]]) {
      if (m.buriedN) {
        report(`${at}, ${where}: ${m.buriedN} control(s) are not the topmost `
          + `thing at their own centre \u2014 ${m.buried.join('; ')}`);
      }
    }
    if (top.collapsedN) {
      report(`${at}: ${top.collapsedN} control box(es) collapsed to a line \u2014 `
        + `${top.collapsed.join(', ')}`);
    }
    if (top.strandedN) {
      report(`${at}: ${top.strandedN} label(s) clipped past reading with nothing `
        + `carrying the whole of them \u2014 ${top.stranded.join('; ')}`);
    }
    if (top.tightest && (!tightest || top.tightest.shown < tightest.shown)) {
      tightest = { ...top.tightest, width };
    }
    if (top.smallest && (!smallest
        || top.smallest.w * top.smallest.h < smallest.w * smallest.h)) {
      smallest = { ...top.smallest, width };
    }
  }
  // Printed green as well as red, so the two values the thresholds are drawn
  // against are in the log at every run and a drift toward one is visible
  // before it crosses it. Guarded on the walk having happened at all: with an
  // empty ladder this line read "0 widths undefined-undefinedpx clean" beside
  // the vacuity failure — a summary that says "clean" about nothing is the
  // sentence this whole file exists to stop being printed.
  if (!seen.length) return;
  ok(`${label}: ${ladder.length} widths `
    + `${ladder[0]}-${ladder[ladder.length - 1]}px, `
    + (dirty ? `${dirty} failure(s) above` : 'all clean')
    + `; ${Math.min(...seen)}-${Math.max(...seen)} controls hit-tested per width`
    + (smallest ? `; smallest control ${smallest.name} ${smallest.w}x${smallest.h} `
      + `at ${smallest.width}px` : '')
    + (tightest ? `; tightest label with nothing carrying the whole of it, `
      + `${tightest.name} showing ${Math.round(tightest.shown * 100)}% `
      + `(${tightest.cw} of ${tightest.sw}px) at ${tightest.width}px`
      : '; every clipped label reachable')
    // Reported rather than dropped: the count is what makes the exclusion
    // arguable. A view that suddenly hides forty labels this way is visible
    // here before anyone has to go looking for why the ladder went quiet.
    + (unpainted ? `; ${unpainted} visually-hidden node(s) excluded as never `
      + `painted` : '')
    // F19: reported for the same reason `unpainted` is. This oracle used to read
    // only attributes and called every JS-carried tooltip unreachable; the count
    // is what makes widening it arguable instead of invisible.
    + (jsCarried ? `; ${jsCarried} clipped label(s) reachable through a JS tip `
      + `carrier rather than an attribute` : ''));
}

/**
 * The vacuity guard for the ladder, asserted once per surface.
 *
 * Named separately from the walk because it is the assertion that the walk
 * HAPPENED. Each number is one of the four checks' oracles: zero widths means
 * the loop never ran, zero elements means the page never rendered, zero
 * hit-tests means every control was off screen or inside a frame and check (3)
 * looked at nothing, zero clip candidates means check (4b) had no input.
 */
export function assertLadderMeasuredSomething(label, tally, { report, ok }) {
  const empty = Object.entries(tally).filter(([, n]) => !n).map(([k]) => k);
  if (empty.length) {
    report(`${label}: the width ladder measured NOTHING for ${empty.join(', ')} `
      + `\u2014 ${JSON.stringify(tally)}. A check with nothing to look at passes for `
      + `free, which is how the 390px assertion stayed green while running on `
      + `one tab of five`);
  } else {
    ok(`${label}: ladder vacuity guard \u2014 ${tally.widths} width-passes, `
      + `${tally.elements} elements, ${tally.controls} controls, `
      + `${tally.hitTested} hit tests, ${tally.clipExamined} clipped labels`);
  }
}

/** A fresh tally, so `assertLadderMeasuredSomething` names every empty oracle. */
export const newLadderTally = () =>
  ({ widths: 0, elements: 0, controls: 0, hitTested: 0, clipExamined: 0 });
