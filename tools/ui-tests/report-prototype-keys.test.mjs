// The REPORT's half of the prototype-key class, driven rather than read.
//
// `prototype-keys.test.mjs` beside this file covers the panel, which got the
// `lookup` helper first. The report carried the identical class and was out of
// that change's scope — and it is the worse of the two surfaces, because it
// needs no manifest and no config to reach: a rendered report is handed around
// as a CI artifact and published as `docs/index.html`, so `#!v=constructor` in
// a link was enough to make `VIEWS[viewMode]` answer with a function and throw
// out of the first filter pass. Whoever opened the link got a dead page.
//
// TWO DEFECTS, TWO DIFFERENT REPAIRS, and both are exercised here.
//
//   READING a table the code wrote as a literal (`VIEWS`, `ORDERS`) with a key
//   that came from the fragment: `lookup()`, now in `shared/lookup.js` and
//   therefore in both surfaces.
//
//   BUILDING a map from keys that came from outside (`TASKS`, `TFROW`,
//   `STATUS_SEG`, `AREA_SEGS`, `expanded`, `taskStatus`, `HASH`):
//   `Object.create(null)`, because `m['__proto__'] = v` on a plain object
//   re-points the prototype instead of storing anything and no read helper can
//   recover what was never written. Phase and task ids carry NO `pattern` in the
//   JSON Schema, so a plan may name a phase `constructor` — and on a plain
//   object `TASKS['constructor']` answered with `Object` itself, whose `.push`
//   is undefined, which threw while the page was still loading.
//
// A substring pin in plugins/audit/tests/ cannot see any of this and never
// will: it reads the text of the page, and the text was always right. What was
// wrong is what the text DOES, which is what this file runs.

import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadReport, reach } from './sandbox.mjs';

// Every name a plain object inherits that is also a legal manifest id, area tag
// or fragment value. `__proto__` is the odd one: an accessor rather than a
// method, so the unguarded read answered with an OBJECT while the other four
// answered with a function — and the unguarded WRITE was swallowed entirely.
const INHERITED = ['constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__'];

// --- a page for the script to run over --------------------------------------
//
// Installed as a source PROLOGUE rather than as a new sandbox option, the way
// `shared-storage.test.mjs` installs a refusing store: `document` is a property
// of the VM context, so an assignment ahead of the assembled body replaces the
// pieces this file needs and leaves the rest of the shim exactly as every other
// suite sees it. Nothing on disk is touched.
//
// THE FIXTURE IS CHOSEN SO A MISS IS VISIBLE. Each phase carries a different
// number of tasks and a different area tag, and no value equals its own key, so
// `tasksOf(id).length` tells a hit from a miss instead of agreeing with both.

/** @type {Array<{id: string, status: string, seg: string, area: string, tasks: number}>} */
const PHASES = [
  { id: 'P1', status: 'in_progress', seg: 'active', area: 'storefront', tasks: 1 },
  { id: 'constructor', status: 'blocked', seg: 'active', area: 'constructor', tasks: 2 },
  { id: '__proto__', status: 'pending', seg: 'pending', area: '__proto__', tasks: 3 },
  { id: 'toString', status: 'done', seg: 'archived', area: 'valueOf', tasks: 4 },
];

const prologue = (opts) => {
  const o = opts || {};
  return `
(() => {
  const listeners = () => {
    const map = {};
    return {
      add(t, fn) { (map[t] || (map[t] = [])).push(fn); },
      fire(t, ev) { (map[t] || []).forEach((fn) => fn(ev || { target: null,
        key: '', preventDefault() {}, stopPropagation() {} })); },
    };
  };
  const node = (attrs, text) => {
    const a = Object.assign({}, attrs);
    const ls = listeners();
    const classes = {};
    const self = {
      nodeType: 1, textContent: text || '', hidden: false, style: {},
      classList: {
        add(c) { classes[c] = true; }, remove(c) { delete classes[c]; },
        toggle(c, on) { if (on) classes[c] = true; else delete classes[c]; },
        contains(c) { return classes[c] === true; },
      },
      getAttribute(k) {
        return Object.prototype.hasOwnProperty.call(a, k) ? a[k] : null;
      },
      setAttribute(k, v) { a[k] = String(v); },
      hasAttribute(k) { return Object.prototype.hasOwnProperty.call(a, k); },
      removeAttribute(k) { delete a[k]; },
      addEventListener(t, fn) { ls.add(String(t), fn); },
      removeEventListener() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
      closest() { return null; },
      append() {}, appendChild(c) { return c; }, remove() {},
      __fire(t, ev) { ls.fire(String(t), ev); },
    };
    return self;
  };
  const PLAN = ${JSON.stringify(PHASES)};
  const phaseRows = [], taskRows = [], tfRows = [];
  PLAN.forEach((p) => {
    phaseRows.push(node({ 'data-phase': p.id, 'data-status': p.status,
      'data-seg': p.seg, 'data-area': p.area }, 'phase ' + p.id));
    tfRows.push(node({ 'data-phase': p.id, 'data-seg': p.seg }, ''));
    for (let i = 0; i < p.tasks; i++) {
      taskRows.push(node({ 'data-phase': p.id, 'data-seg': p.seg,
        'data-status': 'done', 'data-completed': '2026-0' + (i + 1) + '-01' },
        'task ' + p.id + '-' + i));
    }
  });
  const BY_SELECTOR = {
    'tbody tr.phase': phaseRows,
    'tbody tr.task': taskRows,
    'tbody tr.taskfilter': tfRows,
    'tbody tr.taskdetail': [],
    'tbody tr.seghead': [],
  };
  const table = node({ 'data-defaultview': 'active' }, '');
  table.querySelectorAll = (sel) => BY_SELECTOR[sel] || [];
  table.querySelector = () => null;
  const control = () => {
    const c = node({}, '');
    c.value = '';
    return c;
  };
  const byId = { 'audit-sort': control(), 'audit-view': control() };
  globalThis.__fixture = { phaseRows, taskRows, tfRows, byId, table };

  const priorQuery = document.querySelector.bind(document);
  document.querySelector = (sel) => (sel === 'table.phases' ? table : priorQuery(sel));
  const priorById = document.getElementById.bind(document);
  document.getElementById = (id) => (
    Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : priorById(id));

  const store = new Map(${JSON.stringify(Object.entries(o.store || {}))});
  localStorage = {
    getItem(k) { return store.has(k) ? store.get(k) : null; },
    setItem(k, v) { store.set(k, String(v)); },
    removeItem(k) { store.delete(k); },
  };
  globalThis.__store = store;
})();
`;
};

/** Load the assembled report over the fixture page above. */
function page(opts) {
  const o = opts || {};
  const pre = prologue(o);
  return loadReport({
    hash: o.hash || '',
    mutate: (src) => {
      // The prologue is worthless if it landed on something that is not the
      // report, so the body is identified before it is prefixed.
      if (!src.includes('const VIEWS = {') || !src.includes('const ORDERS = {')) {
        throw new Error('the assembled report no longer declares VIEWS and ORDERS, '
          + 'so this fixture would be measuring something else');
      }
      // The mutation runs over prologue AND body, so a case may rewrite the
      // FIXTURE (a plan whose statuses are the inherited names) as readily as
      // the code under test.
      const whole = pre + src;
      return o.mutate ? o.mutate(whole) : whole;
    },
  });
}

/** Replace `needle` exactly once, or stop. */
function mutateOnce(needle, replacement) {
  return (src) => {
    const n = src.split(needle).length - 1;
    if (n !== 1) {
      throw new Error('mutation target occurs ' + n + ' times, expected exactly 1: '
        + JSON.stringify(needle) + ' — the source moved and this proof is no '
        + 'longer proving anything.');
    }
    return src.split(needle).join(replacement);
  };
}

const EXPAND_KEY = 'audit-report-expanded:report';
const FILTER_KEY = 'audit-view-report';

// ---------------------------------------------------------------- the reads --

describe('the shared lookup() really reached the report', () => {
  const { ctx } = page();
  const { lookup, VIEWS, ORDERS } = reach(ctx, ['lookup', 'VIEWS', 'ORDERS']);

  it('answers a MISS for every inherited name, on both literal tables', () => {
    INHERITED.forEach((k) => {
      expect(lookup(VIEWS, k), k).toBeUndefined();
      expect(lookup(ORDERS, k), k).toBeUndefined();
    });
  });

  it('and the bare read it replaces really did answer with a member', () => {
    // The control. Without it the case above passes just as well against tables
    // that happen to be empty, and proves nothing about the chain.
    INHERITED.forEach((k) => {
      expect(VIEWS[k], k).toBeDefined();
      expect(ORDERS[k], k).toBeDefined();
    });
    expect(typeof VIEWS.constructor).toBe('function');
    expect(typeof ORDERS.__proto__).toBe('object');
  });

  it('and a real name still answers with the table\'s own value', () => {
    expect(lookup(VIEWS, 'archived')).toEqual(['archived']);
    expect(lookup(VIEWS, 'all')).toEqual(['active', 'pending', 'archived']);
    expect(typeof lookup(ORDERS, 'plan')).toBe('function');
    expect(lookup(ORDERS, 'plan')()).toBe(0);
  });
});

describe('inView answers a boolean whatever the view is called', () => {
  it('an inherited SEGMENT name is simply not in the view', () => {
    const { ctx } = page();
    const { inView } = reach(ctx, ['inView']);
    INHERITED.forEach((k) => {
      expect(inView(k), k).toBe(false);
    });
    expect(inView('active')).toBe(true);
    expect(inView('archived')).toBe(false);
  });

  it('and an inherited VIEW name falls back to `all` instead of throwing', () => {
    // The table key, which is the half the fragment controls. Documented
    // `@returns {boolean}`; the bare read handed `.includes` to a function.
    INHERITED.forEach((k) => {
      const { ctx } = page();
      vm.runInContext('viewMode=' + JSON.stringify(k) + ';', ctx);
      const { inView } = reach(ctx, ['inView']);
      expect(inView('active'), k).toBe(true);
      expect(inView('pending'), k).toBe(true);
      expect(inView('archived'), k).toBe(true);
      expect(inView('nothing-like-this'), k).toBe(false);
    });
  });

  it('and a real view still narrows, so the fallback is not the only answer', () => {
    const { ctx } = page();
    vm.runInContext("viewMode='archived';", ctx);
    const { inView } = reach(ctx, ['inView']);
    expect(inView('archived')).toBe(true);
    expect(inView('active')).toBe(false);
  });
});

describe('the fragment cannot name a view or an order that does not exist', () => {
  INHERITED.forEach((k) => {
    it('#!v=' + k + ' leaves the view exactly where it was', () => {
      const { ctx, consoleErrors } = page({ hash: '#!v=' + k });
      expect(vm.runInContext('viewMode', ctx)).toBe('active');
      expect(vm.runInContext('__fixture.byId["audit-view"].value', ctx)).toBe('active');
      expect(consoleErrors).toEqual([]);
    });

    it('#!so=' + k + ' leaves the order exactly where it was', () => {
      const { ctx, consoleErrors } = page({ hash: '#!so=' + k });
      expect(vm.runInContext('phaseOrder', ctx)).toBe('plan');
      expect(vm.runInContext('__fixture.byId["audit-sort"].value', ctx)).toBe('plan');
      expect(consoleErrors).toEqual([]);
    });
  });

  it('and a REAL view name in the link still selects that view', () => {
    const { ctx } = page({ hash: '#!v=archived' });
    expect(vm.runInContext('viewMode', ctx)).toBe('archived');
    expect(vm.runInContext('__fixture.byId["audit-view"].value', ctx)).toBe('archived');
    // ...and it really took effect: the archived phase is the only one showing.
    const shown = vm.runInContext(
      '__fixture.phaseRows.filter(r=>r.style.display!=="none")'
      + '.map(r=>r.getAttribute("data-phase"))', ctx);
    expect(shown).toEqual(['toString']);
  });

  it('and a REAL order name in the link still selects that order', () => {
    const { ctx } = page({ hash: '#!so=priority' });
    expect(vm.runInContext('phaseOrder', ctx)).toBe('priority');
    expect(vm.runInContext('__fixture.byId["audit-sort"].value', ctx)).toBe('priority');
  });

  it('and setPhaseOrder refuses an inherited name from the select too', () => {
    const { ctx } = page();
    const { setPhaseOrder } = reach(ctx, ['setPhaseOrder']);
    INHERITED.forEach((k) => {
      setPhaseOrder(k);
      expect(vm.runInContext('phaseOrder', ctx), k).toBe('plan');
    });
    setPhaseOrder('priority');
    expect(vm.runInContext('phaseOrder', ctx)).toBe('priority');
  });

  it('and setView refuses one, while a real name still switches', () => {
    const { ctx } = page();
    const { setView } = reach(ctx, ['setView']);
    INHERITED.forEach((k) => {
      setView(k);
      expect(vm.runInContext('viewMode', ctx), k).toBe('active');
    });
    setView('all');
    expect(vm.runInContext('viewMode', ctx)).toBe('all');
  });
});

// --------------------------------------------------------------- the builds --

describe('a phase id that names an inherited member is an ordinary phase', () => {
  it('the page loads at all — this is the shipped throw', () => {
    // `(TASKS[k] || (TASKS[k] = [])).push(t)` on a plain object resolved
    // `TASKS['constructor']` to Object itself, whose `.push` is undefined. The
    // whole inline script died there, with the no-JS banner already removed.
    expect(() => page()).not.toThrow();
  });

  it('every index is prototype-free, which is what makes the reads safe', () => {
    const { ctx } = page();
    ['TASKS', 'TFROW', 'STATUS_SEG', 'AREA_SEGS', 'expanded', 'taskStatus', 'HASH']
      .forEach((name) => {
        expect(vm.runInContext('Object.getPrototypeOf(' + name + ')', ctx), name)
          .toBe(null);
      });
  });

  it('tasksOf hands back that phase\'s OWN rows, not Object.prototype', () => {
    const { ctx } = page();
    const { tasksOf } = reach(ctx, ['tasksOf']);
    // Counts differ per phase, so a table that answered the same thing for
    // every key — or for none — cannot pass this.
    PHASES.forEach((p) => {
      expect(tasksOf(p.id).length, p.id).toBe(p.tasks);
      expect(tasksOf(p.id).map((r) => r.getAttribute('data-phase')), p.id)
        .toEqual(new Array(p.tasks).fill(p.id));
    });
    expect(tasksOf('no-such-phase')).toEqual([]);
    expect(Array.isArray(tasksOf('constructor'))).toBe(true);
  });

  it('tfOf hands back a ROW, and null for a phase that has none', () => {
    const { ctx } = page();
    const { tfOf } = reach(ctx, ['tfOf']);
    PHASES.forEach((p) => {
      const row = tfOf(p.id);
      expect(typeof row, p.id).toBe('object');
      expect(row === null, p.id).toBe(false);
      expect(row.getAttribute('data-phase'), p.id).toBe(p.id);
    });
    expect(tfOf('no-such-phase')).toBe(null);
  });

  it('areaInView answers true/false, and answers it per area', () => {
    const { ctx } = page();
    const { areaInView } = reach(ctx, ['areaInView']);
    // The default view is `active`, whose segments are active AND pending, so
    // the archived phase's tag is the one that must answer false. Both
    // directions, or a function that always said true would pass this.
    expect(areaInView('storefront')).toBe(true);
    expect(areaInView('constructor')).toBe(true);
    expect(areaInView('__proto__')).toBe(true);
    expect(areaInView('valueOf')).toBe(false);
    // An area nothing is tagged with is not in view either; an empty tag is the
    // documented "no area filter" case and stays true.
    expect(areaInView('toString')).toBe(false);
    expect(areaInView('')).toBe(true);
  });

  it('statusInView reads the segment each STATUS was filed under', () => {
    const { ctx } = page();
    const { statusInView } = reach(ctx, ['statusInView']);
    expect(statusInView('in_progress')).toBe(true);
    expect(statusInView('blocked')).toBe(true);
    expect(statusInView('pending')).toBe(true);
    expect(statusInView('done')).toBe(false);
    expect(statusInView('')).toBe(true);
    // A status no phase carries files under no segment at all, so it is out of
    // every view — which is what the missing STATUS_SEG entry used to look like.
    expect(statusInView('nothing-like-this')).toBe(false);
  });

  it('...and the segment map recorded the inherited-name statuses at all', () => {
    // `st in STATUS_SEG` walks the chain on a plain object, so `'constructor'`
    // read as already-present and the entry was never written — the phase then
    // failed every view test in silence. Asserted through the map rather than
    // through a verdict, because both spellings of the bug answer `false`.
    const { ctx } = page({
      // A plan whose statuses ARE the inherited names. Free text reaches here:
      // `_seg_of` documents an unknown status as landing in `pending`.
      mutate: mutateOnce("'data-status': p.status", "'data-status': p.id"),
    });
    const seen = vm.runInContext('Object.keys(STATUS_SEG)', ctx);
    expect(seen.slice().sort())
      .toEqual(['P1', '__proto__', 'constructor', 'toString'].sort());
    const { statusInView } = reach(ctx, ['statusInView']);
    // `constructor` is on the active phase and `toString` on the archived one,
    // so the two answers differ and neither is the whole table's answer.
    expect(statusInView('constructor')).toBe(true);
    expect(statusInView('__proto__')).toBe(true);
    expect(statusInView('toString')).toBe(false);
  });
});

describe('a map built from a `__proto__` key stores it and reads it back', () => {
  it('the expand state survives a round trip through storage', () => {
    // The whole path: JSON in localStorage -> `expanded` -> a click on the phase
    // row -> JSON back out. Every key here is a phase id.
    const { ctx } = page({
      // Written as TEXT: `{ __proto__: true }` in a JavaScript object literal
      // sets the prototype instead of a key, so building this with JSON.stringify
      // would have shipped a fixture missing the very key under test.
      store: { [EXPAND_KEY]: '{"__proto__":true,"constructor":true,"P1":false}' },
    });
    expect(vm.runInContext('expanded["__proto__"]', ctx)).toBe(true);
    expect(vm.runInContext('expanded.constructor', ctx)).toBe(true);
    expect(vm.runInContext('expanded.P1', ctx)).toBe(false);
    // ...and the rows agree with the map, which is the part a reader sees.
    const open = vm.runInContext(
      '__fixture.phaseRows.filter(r=>r.getAttribute("aria-expanded")==="true")'
      + '.map(r=>r.getAttribute("data-phase"))', ctx);
    // Both, because the default view's segments are active AND pending; `P1`
    // was stored false and the archived phase was never stored at all, so this
    // is two of four rather than "everything the map happened to hold".
    expect(open).toEqual(['constructor', '__proto__']);
  });

  it('clicking a `__proto__` phase opens it, and the choice is written out', () => {
    const { ctx } = page();
    expect(vm.runInContext('expanded["__proto__"]', ctx)).toBeUndefined();
    vm.runInContext('__fixture.phaseRows[2].__fire("click", {target:null});', ctx);
    expect(vm.runInContext('expanded["__proto__"]', ctx)).toBe(true);
    // Stored, not merely held: `JSON.stringify` of a swallowed write is `{}`.
    const written = JSON.parse(vm.runInContext(
      '__store.get(' + JSON.stringify(EXPAND_KEY) + ')', ctx));
    expect(Object.prototype.hasOwnProperty.call(written, '__proto__')).toBe(true);
    expect(written['__proto__']).toBe(true);
  });

  it('a `constructor` phase toggles on the FIRST click, not the second', () => {
    // `expanded['constructor']` inherited a function, which is truthy, so the
    // row rendered open before anyone touched it and the first click shut it.
    const { ctx } = page();
    expect(vm.runInContext('__fixture.phaseRows[1].getAttribute("aria-expanded")', ctx))
      .toBe('false');
    vm.runInContext('__fixture.phaseRows[1].__fire("click", {target:null});', ctx);
    expect(vm.runInContext('expanded.constructor', ctx)).toBe(true);
    expect(vm.runInContext('__fixture.phaseRows[1].getAttribute("aria-expanded")', ctx))
      .toBe('true');
  });

  it('the per-phase task filter keeps one slot per phase, id notwithstanding', () => {
    const { ctx } = page();
    vm.runInContext("taskStatus['__proto__']='done';taskStatus.constructor='blocked';", ctx);
    expect(vm.runInContext('taskStatus["__proto__"]', ctx)).toBe('done');
    expect(vm.runInContext('taskStatus.constructor', ctx)).toBe('blocked');
    expect(vm.runInContext('Object.keys(taskStatus).sort()', ctx))
      .toEqual(['__proto__', 'constructor']);
  });

  it('a fragment key of `__proto__` is decoded into the hash like any other', () => {
    const { ctx } = page({ hash: '#!__proto__=kept&v=all' });
    expect(vm.runInContext('HASH["__proto__"]', ctx)).toBe('kept');
    expect(vm.runInContext('HASH.v', ctx)).toBe('all');
    // It was really COUNTED, which is what decides whether the link beats the
    // local copy: a swallowed write left `Object.keys(HASH).length` at 1 here.
    expect(vm.runInContext('Object.keys(HASH).length', ctx)).toBe(2);
  });

  it('and the stored filter string restores one too', () => {
    const { ctx } = page({ store: { [FILTER_KEY]: '__proto__=kept&v=all' } });
    expect(vm.runInContext('HASH["__proto__"]', ctx)).toBe('kept');
    expect(vm.runInContext('viewMode', ctx)).toBe('all');
  });
});

// ------------------------------------------------------------- the red half --
//
// Every case above is worth exactly what its failure mode is worth, so each
// repair is mutated back out and the case that must catch it is named. The
// mutations run against the SAME loader, so a mutation that no longer matches
// its anchor stops the run rather than passing.

describe('the proofs above can fail', () => {
  it('goes red when the view read stops being an own-property read', () => {
    const { ctx } = page({
      hash: '#!v=constructor',
      mutate: mutateOnce('if (HASH.v && lookup(VIEWS, HASH.v)) {',
        'if (HASH.v && VIEWS[HASH.v]) {'),
    });
    // The guard passes on an inherited function and the view is set to a name
    // no view exists for — which is what the case above says cannot happen.
    expect(vm.runInContext('viewMode', ctx)).toBe('constructor');
    expect(vm.runInContext('__fixture.byId["audit-view"].value', ctx)).toBe('constructor');
  });

  it('goes red — by THROWING — when inView reads VIEWS bare', () => {
    const { ctx } = page({
      mutate: mutateOnce('(lookup(VIEWS, viewMode) || VIEWS.all)',
        '(VIEWS[viewMode] || VIEWS.all)'),
    });
    vm.runInContext("viewMode='constructor';", ctx);
    const { inView } = reach(ctx, ['inView']);
    expect(() => inView('active')).toThrow(/includes is not a function/);
  });

  it('goes red when the order read stops being an own-property read', () => {
    const { ctx } = page({
      hash: '#!so=constructor',
      mutate: mutateOnce('if (HASH.so && lookup(ORDERS, HASH.so) && sortSel) {',
        'if (HASH.so && ORDERS[HASH.so] && sortSel) {'),
    });
    expect(vm.runInContext('phaseOrder', ctx)).toBe('constructor');
    expect(vm.runInContext('__fixture.byId["audit-sort"].value', ctx)).toBe('constructor');
  });

  it('goes red when the task index gets a prototype back — at LOAD', () => {
    expect(() => page({
      mutate: mutateOnce('const TASKS = Object.create(null);', 'const TASKS = {};'),
    })).toThrow(/\.push is not a function/);
  });

  it('goes red when the task-filter index gets a prototype back', () => {
    const { ctx } = page({
      mutate: mutateOnce('const TFROW = Object.create(null);', 'const TFROW = {};'),
    });
    const { tfOf } = reach(ctx, ['tfOf']);
    // `TFROW['__proto__'] = row` re-points the PROTOTYPE — so the map now
    // inherits from a table row, and every miss falls through to it. The
    // `__proto__` accessor hands the row back, which is why this case asserts
    // the collateral damage rather than that one key: a phase called
    // `nodeType` now resolves to the number 1, and `constructor` to Object.
    expect(tfOf('nodeType')).toBe(1);
    expect(typeof tfOf('getAttribute')).toBe('function');
    expect(Object.getPrototypeOf(vm.runInContext('TFROW', ctx))).not.toBe(null);
  });

  it('goes red when the area index gets a prototype back — at LOAD', () => {
    expect(() => page({
      mutate: mutateOnce('const AREA_SEGS = Object.create(null);', 'const AREA_SEGS = {};'),
    })).toThrow(/\.indexOf is not a function/);
  });

  it('goes red when the status index gets a prototype back', () => {
    const { ctx } = page({
      mutate: (src) => mutateOnce('const STATUS_SEG = Object.create(null);',
        'const STATUS_SEG = {};')(
        mutateOnce("'data-status': p.status", "'data-status': p.id")(src)),
    });
    // The `in` test finds the inherited names, so nothing is ever recorded for
    // them and the phase drops out of every view.
    expect(vm.runInContext('Object.keys(STATUS_SEG).sort()', ctx)).toEqual(['P1']);
    const { statusInView } = reach(ctx, ['statusInView']);
    expect(statusInView('constructor')).toBe(false);
  });

  it('goes red when the expand map gets a prototype back', () => {
    const { ctx } = page({
      mutate: mutateOnce('const expanded = Object.create(null);', 'const expanded = {};'),
    });
    vm.runInContext('__fixture.phaseRows[2].__fire("click", {target:null});', ctx);
    // The write is swallowed by the prototype setter: nothing is stored, so
    // nothing comes back and nothing is written out.
    expect(vm.runInContext('Object.prototype.hasOwnProperty.call(expanded,"__proto__")',
      ctx)).toBe(false);
    expect(JSON.parse(vm.runInContext(
      '__store.get(' + JSON.stringify(EXPAND_KEY) + ')', ctx))).toEqual({});
  });

  it('goes red when the hash map gets a prototype back', () => {
    const { ctx } = page({
      hash: '#!__proto__=kept&v=all',
      mutate: mutateOnce('}, Object.create(null));', '}, {});'),
    });
    expect(vm.runInContext('Object.keys(HASH).length', ctx)).toBe(1);
    expect(vm.runInContext('typeof HASH["__proto__"]', ctx)).toBe('object');
  });

  it('and the ALLOW case: a guard weakened until it finds nothing goes red too', () => {
    // The other direction. Every case above is satisfied by a `lookup` that
    // answers `undefined` for EVERYTHING, which would also refuse every real
    // view and every real order — so the suite has to be able to see that.
    const { ctx } = page({
      hash: '#!v=archived',
      mutate: mutateOnce(
        'const lookup=(t,k)=>Object.prototype.hasOwnProperty.call(t,k)?t[k]:undefined;',
        'const lookup=()=>undefined;'),
    });
    // The real name is now refused, which is the over-firing guard.
    expect(vm.runInContext('viewMode', ctx)).toBe('active');
    const { setPhaseOrder } = reach(ctx, ['setPhaseOrder']);
    setPhaseOrder('priority');
    expect(vm.runInContext('phaseOrder', ctx)).toBe('plan');
  });

  it('...and the same weakening seen from the helper itself', () => {
    const { ctx } = page({
      mutate: mutateOnce(
        'const lookup=(t,k)=>Object.prototype.hasOwnProperty.call(t,k)?t[k]:undefined;',
        'const lookup=()=>undefined;'),
    });
    const { lookup, VIEWS } = reach(ctx, ['lookup', 'VIEWS']);
    expect(lookup(VIEWS, 'archived')).toBeUndefined();
    expect(VIEWS.archived).toEqual(['archived']);
  });
});
