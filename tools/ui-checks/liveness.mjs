/**
 * Is the page still the page we armed? The half a screenshot cannot answer.
 *
 * A gate that drives a page it has silently lost reports on nothing and passes. Two
 * gates share these - the panel capture and the report check - which is why they are
 * a module rather than a section: a shared concern with two callers and no
 * dependency on either one's run state.
 */

/** Written on the anchor element. Dies with an innerHTML rewrite AND with a load. */
const LIVE_MARK = '__auditLiveMark';
/** Written on `window`. Survives an innerHTML rewrite; dies with a load. */
const LIVE_TOKENS = '__auditLiveTokens';

/**
 * The liveness verdict at `anchorSel`, arming a baseline when there is none.
 *
 * Keyed BY SELECTOR on both sides, which is not decoration: two anchors on one page
 * (`.tab` here, `#audit-expand` in the report gate) would otherwise read each other's
 * token, and the second one asked would report `rebuilt` on a perfectly healthy page.
 * A liveness check that fires on a healthy run is the failure mode this file is most
 * careful about, so the shared state is per-anchor and never global.
 *
 * Verdicts: `live` (same nodes as when armed), `armed` (fresh document — baseline
 * taken, nothing claimed), `rebuilt` (the F23 shape), `no-anchor` (the selector
 * matches nothing, which is a fact about the document), `confused` (a mark with no
 * token, which neither a load nor a rewrite produces — reported, never swallowed).
 */
export async function livenessAt(page, anchorSel) {
  return page.evaluate((a) => {
    const el = document.querySelector(a.sel);
    if (!el) return { verdict: 'no-anchor', sel: a.sel };
    const store = window[a.tokKey] || (window[a.tokKey] = {});
    const marks = el[a.markKey] || (el[a.markKey] = {});
    const token = store[a.sel];
    const mark = marks[a.sel];
    if (token === undefined && mark === undefined) {
      const fresh = String(Date.now()) + ':' + Math.random().toString(16).slice(2);
      store[a.sel] = fresh;
      marks[a.sel] = fresh;
      return { verdict: 'armed', sel: a.sel };
    }
    if (token !== undefined && mark === token) return { verdict: 'live', sel: a.sel };
    if (token !== undefined) {
      return { verdict: 'rebuilt', sel: a.sel,
               mark: mark === undefined ? null : mark };
    }
    return { verdict: 'confused', sel: a.sel, mark };
  }, { sel: anchorSel, markKey: LIVE_MARK, tokKey: LIVE_TOKENS });
}

/**
 * Assert CONTINUITY at `anchorSel`, and count the verdict.
 *
 * `report` is `fail`-shaped so the one rule serves this file and
 * check-report-interactive.mjs, which keep their failures in different places —
 * the same injection walkResponsiveLadder already uses. There is no `ok`: a green
 * line per call would be 40-odd lines of noise, and the green statement belongs to
 * assertLivenessWasChecked, which reports the tally once.
 *
 * Returns the verdict so a caller can decline to measure a page it has just been
 * told is inert. Measuring one anyway produces a second, louder failure that names
 * the product for the harness's fault, which is worse than a flake: the next person
 * to meet it on a real regression remembers it as noise.
 */
export async function assertStillLive(page, anchorSel, where, { report, tally = null }) {
  const s = await livenessAt(page, anchorSel);
  if (tally) {
    tally.checks += 1;
    if (s.verdict === 'live') tally.live += 1;
    if (s.verdict === 'armed') tally.armed += 1;
  }
  if (s.verdict === 'live' || s.verdict === 'armed') return s.verdict;
  if (s.verdict === 'no-anchor') {
    report(`${where}: nothing matches "${anchorSel}", so this run cannot say whether `
      + 'the page is still the one it set up. That is a fact about the DOCUMENT — it '
      + 'never rendered, or the anchor moved — and not a verdict about the product.');
    return s.verdict;
  }
  if (s.verdict === 'rebuilt') {
    report(`${where}: the "${anchorSel}" node is NOT the node this run armed, while `
      + 'the script context that armed it IS still the same one. Only one thing '
      + 'produces that pair: something in THIS HARNESS rewrote the DOM — restoring a '
      + 'saved innerHTML string is the shape that did it in F23 — and every listener '
      + 'the page had bound went with the nodes it replaced. Read this as a harness '
      + 'fault, not a product defect; every measurement taken after it is a '
      + 'measurement of an inert page.');
    return s.verdict;
  }
  report(`${where}: liveness at "${anchorSel}" is unreadable (${JSON.stringify(s)}). `
    + 'The element carries a mark the window has no token for, which neither a page '
    + 'load nor a DOM rewrite produces — so this is a bug in the check, not in the '
    + 'page, and it is said out loud rather than passed over.');
  return s.verdict;
}

/** A fresh liveness tally, so the guard below can name what never happened. */
export const newLivenessTally = () => ({ checks: 0, armed: 0, live: 0 });

/**
 * The vacuity guard OVER the liveness guard — because the liveness guard is itself a
 * check that could quietly measure nothing.
 *
 * `armed` alone can never fail: it is the verdict for a fresh document, taken as a
 * baseline. A run whose every liveness call armed has therefore never compared
 * anything, and would report a clean page while asserting exactly nothing about it.
 * That is the same sentence assertLadderMeasuredSomething exists for, one layer in.
 */
export function assertLivenessWasChecked(label, tally, { report, ok }) {
  if (!tally.checks) {
    report(`${label}: liveness was never checked at all, so nothing here can say the `
      + 'page being measured is still the page that was set up — which is the one '
      + 'failure a full, plausible result set does not reveal (F23)');
    return;
  }
  if (!tally.live) {
    // Both non-confirming outcomes are counted and named, because they mean
    // different things and a summary that folded them together would describe
    // one of the two runs wrongly: arming is a baseline being taken, an
    // unreadable anchor is nothing being taken at all. Measured — the first
    // spelling of this line said "all N ARMED" and printed it over a run in
    // which nothing had armed.
    const unreadable = tally.checks - tally.armed - tally.live;
    report(`${label}: ${tally.checks} liveness check(s) ran and not one confirmed `
      + `continuity against an earlier baseline — ${tally.armed} armed a fresh one, `
      + `${unreadable} could not be read at all. Arming cannot fail and an anchor `
      + 'that cannot be read asserts nothing, so this is the check reporting on '
      + 'itself: the page is reloading between every step, or the anchor is not the '
      + 'same node twice, or it is not in the document.');
    return;
  }
  ok(`${label}: liveness — ${tally.live} of ${tally.checks} check(s) confirmed the DOM `
    + `is still the one armed; ${tally.armed} armed a fresh baseline after a load`);
}
