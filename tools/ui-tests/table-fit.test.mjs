// The report's table frame, and the measured fit that lifts it.
//
// Every table sits in a frame that scrolls sideways inside itself, so with no
// script at all no table can widen the page. That frame costs the column
// headers their stickiness, because a header sticks to its nearest scrolling
// ancestor and the frame never scrolls vertically. So the script measures each
// frame: where its table fits, the frame is marked and the stylesheet releases
// it, which gives the headers back to the page; where it does not, the frame
// stays contained and unmarked.
//
// WHAT A SUBSTRING PIN CANNOT DO HERE. It can find the attribute's name in the
// script and in the sheet. It cannot say that the two NAMES agree, that the
// measurement reads the table with the frame released, or that the mark goes
// away again when a narrower window makes the same table too wide - and that
// last one is the failure that matters, because a mark left behind releases a
// frame around a table that now overflows it, and the page widens. So the cases
// below evaluate the assembled script and drive the shipped functions, the
// resize listener and the observer over the frames and their tables included.

import { describe, expect, it } from 'vitest';
import { loadReport, reach, readPart } from './sandbox.mjs';

const CLAUSE = 'a table that fits its frame is marked to fit and keeps sticky column '
  + 'headers, a table that would widen the page stays contained, and the mark follows '
  + 'a resize';

// Run ahead of the page's own first line. The stub window drops every listener
// and never runs a frame callback, so the resize path would be unreachable;
// this records both, and hands the page the frames a test builds, without
// changing a byte of the shipped parts.
const PRELUDE = [
  'window.__on = Object.create(null);',
  'window.addEventListener = (t, f) => { (window.__on[t] || (window.__on[t] = [])).push(f); };',
  'window.__raf = [];',
  'window.requestAnimationFrame = (f) => { window.__raf.push(f); return window.__raf.length; };',
  'window.__wraps = [];',
  'document.querySelectorAll = ((orig) => (s) => (s === ".tablewrap" ? window.__wraps : orig(s)))'
    + '(document.querySelectorAll);',
  '',
].join('\n');

const load = () => loadReport({ mutate: (src) => PRELUDE + src });

// A frame and the table inside it. The table records what the frame's
// horizontal overflow was at the moment its width was read, because the
// measurement is only honest with the frame released: a contained frame is a
// scroll container, and the question is how wide the table is when nothing
// holds it in.
const frame = (clientWidth, tableWidth) => {
  const attrs = new Map();
  const seenOverflow = [];
  const wrap = {
    clientWidth,
    style: { overflowX: '' },
    setAttribute(k, v) { attrs.set(String(k), String(v)); },
    getAttribute(k) { return attrs.has(String(k)) ? attrs.get(String(k)) : null; },
    removeAttribute(k) { attrs.delete(String(k)); },
    hasAttribute(k) { return attrs.has(String(k)); },
    querySelector(s) { return s === 'table' ? table : null; },
  };
  const table = {
    width: tableWidth,
    get scrollWidth() { seenOverflow.push(wrap.style.overflowX); return this.width; },
  };
  return { wrap, table, seenOverflow };
};

const OBSERVED_CLAUSE = 'In leg 10c, after planting and before the planted ladder, wait two '
  + 'animation frames with no resize and fail on any frame marked over an overflowing '
  + 'table; a stubbed ResizeObserver sees every frame and its table, and its callback '
  + 'drops a stale mark';

// The stub window has no ResizeObserver, so the page's content-change path -
// the only one that re-measures a frame when an expand, filter or view switch
// widens its table with no window resize - never ran here. This stub records
// each observer the page builds, with its callback and every target handed to
// observe(). The frames must exist BEFORE the page's first line, because the
// observer is wired once at load, so they are built inside the context by the
// same `frame` helper as every other case, passed in as its source text.
const OBSERVER_PRELUDE = [
  'window.__observers = [];',
  'window.ResizeObserver = function ResizeObserver(cb) {',
  '  const rec = { cb, targets: [] };',
  '  window.__observers.push(rec);',
  '  this.observe = (t) => { rec.targets.push(t); };',
  '  this.unobserve = () => {};',
  '  this.disconnect = () => {};',
  '};',
  '',
].join('\n');

const loadObserved = (sizes) => loadReport({ mutate: (src) => PRELUDE + OBSERVER_PRELUDE
  + 'window.__frames = ' + JSON.stringify(sizes) + '.map(([c, t]) => ('
  + frame.toString() + ')(c, t));\n'
  + 'window.__wraps = window.__frames.map((f) => f.wrap);\n' + src });

const flushFrames = (ctx) => {
  const due = ctx.__raf.splice(0);
  due.forEach((f) => f(0));
  return due.length;
};

describe('the measured fit of a report table', () => {
  it(CLAUSE + ' (a table no wider than its frame is marked, measured with the frame '
    + 'released, and the frame is contained again afterwards)', () => {
    const { ctx } = load();
    const { TABLE_FIT_ATTR, markTableFits } = reach(ctx, ['TABLE_FIT_ATTR', 'markTableFits']);
    const f = frame(900, 900);
    markTableFits([f.wrap]);
    expect(f.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(true);
    expect(f.seenOverflow).toEqual(['visible']);
    expect(f.wrap.style.overflowX).toBe('');
  });

  it(CLAUSE + ' (a table wider than its frame by one pixel is left unmarked, and a '
    + 'mark it carried from an earlier measurement is taken off)', () => {
    const { ctx } = load();
    const { TABLE_FIT_ATTR, markTableFits } = reach(ctx, ['TABLE_FIT_ATTR', 'markTableFits']);
    const fresh = frame(900, 901);
    const stale = frame(900, 1400);
    stale.wrap.setAttribute(TABLE_FIT_ATTR, '');
    markTableFits([fresh.wrap, stale.wrap]);
    expect(fresh.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
    expect(stale.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
  });

  it(CLAUSE + ' (a window resize re-measures on the next frame: the mark comes off '
    + 'when the frame narrows past the table, and back when it widens again)', () => {
    const { ctx } = load();
    const { TABLE_FIT_ATTR } = reach(ctx, ['TABLE_FIT_ATTR']);
    const f = frame(1200, 1000);
    ctx.__wraps = [f.wrap];
    const onResize = ctx.__on.resize || [];
    expect(onResize.length).toBeGreaterThan(0);
    const resize = () => { onResize.forEach((fn) => fn({ type: 'resize' })); return flushFrames(ctx); };

    expect(resize()).toBeGreaterThan(0);
    expect(f.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(true);
    f.wrap.clientWidth = 600;
    resize();
    expect(f.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
    f.wrap.clientWidth = 1200;
    resize();
    expect(f.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(true);
    // Coalesced: a burst of resize events asks for ONE frame, not one each.
    onResize.forEach((fn) => fn({ type: 'resize' }));
    onResize.forEach((fn) => fn({ type: 'resize' }));
    expect(flushFrames(ctx)).toBe(1);
  });

  it(OBSERVED_CLAUSE + ' (every frame and its table are observed, and an observer '
    + 'callback with no window resize queues one measurement that drops a stale mark)', () => {
    // The two frames are told apart by the fixture: the first's table already
    // overflows, the second fits at load and then outgrows its frame, which is
    // the content change the observer exists for.
    const { ctx } = loadObserved([[900, 1400], [900, 800]]);
    const { TABLE_FIT_ATTR } = reach(ctx, ['TABLE_FIT_ATTR']);
    const [over, grows] = ctx.__frames;
    const wanted = [over.wrap, over.table, grows.wrap, grows.table];
    const fitObservers = ctx.__observers.filter((o) =>
      o.targets.some((t) => ctx.__wraps.includes(t)));
    expect(fitObservers.length).toBe(1);
    const [fitRo] = fitObservers;
    // Counted, in order, rather than found: each frame and its table once.
    expect(fitRo.targets).toEqual(wanted);

    // The load's own first measurement, so what follows starts from a known mark.
    expect(flushFrames(ctx)).toBe(1);
    expect(over.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
    expect(grows.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(true);

    // The content change: the table widens past its frame, the window does not
    // move, and a mark is planted on the other frame as left from a stale read.
    grows.table.width = 1000;
    over.wrap.setAttribute(TABLE_FIT_ATTR, '');
    expect(ctx.__raf.length).toBe(0);
    fitRo.cb([{ target: grows.table }]);
    fitRo.cb([{ target: grows.wrap }]);
    // Still marked until the frame runs: the drop below is the queued pass's.
    expect(grows.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(true);
    expect(flushFrames(ctx)).toBe(1);
    expect(grows.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
    expect(over.wrap.hasAttribute(TABLE_FIT_ATTR)).toBe(false);
  });

  it(CLAUSE + ' (the sheet releases a marked frame and pins its headers under the very '
    + 'attribute the script writes, and the contained frame is declared outside any '
    + 'media query)', () => {
    const { ctx } = load();
    const { TABLE_FIT_ATTR } = reach(ctx, ['TABLE_FIT_ATTR']);
    const css = readPart('report-css/tables.css').replace(/\/\*[\s\S]*?\*\//g, '');
    const sel = '.tablewrap[' + TABLE_FIT_ATTR + ']';
    expect(css).toContain(sel + '{overflow:visible}');
    expect(css).toContain(sel + ' thead th{position:sticky;top:var(--sticky-3);'
      + 'z-index:var(--z-thead)}');
    // The contained default is the first rule of the sheet's table section, at
    // depth zero: it must hold at every width, with no script.
    const at = css.indexOf('.tablewrap{');
    const before = css.slice(0, at);
    const depth = (before.match(/\{/g) || []).length - (before.match(/\}/g) || []).length;
    expect(at).toBeGreaterThanOrEqual(0);
    expect(depth).toBe(0);
    expect(css.slice(at, css.indexOf('}', at))).toContain('overflow-x:auto');
  });
});
