// What Settings sends when Save is pressed: a PATCH built from the form against
// the config the server last served, never the form's whole copy of the file.
//
// The whole copy rewrote keys nobody changed. It had been through a browser's
// JSON, which has no float/int distinction, and it was drawn before anything
// written since; and a list key that was unset drew its shipped default into the
// draft, so adding one entry wrote the whole default list into the file without
// the dialog saying so.
//
// `configPatch` is reached out of the loaded panel rather than retyped here, and
// the last case hands its output to the Python that applies it, so the two
// halves are checked against each other rather than each against a belief.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, pyCall, reach } from './sandbox.mjs';

const plain = (v) => JSON.parse(JSON.stringify(v));
const patchOf = (before, after, defaults) => {
  const { configPatch } = reach(loadPanel().ctx, ['configPatch']);
  return plain(configPatch(before, after, defaults));
};

const DEFAULTS = {
  trivialLineThreshold: 30,
  exemptGlobs: ['docs/**', '**/*.md'],
  secretPatterns: { extra: [] },
  usage: { bands: { highUSD: 10 }, pricingAsOf: '2026-01-01' },
};

/**
 * A DOM just deep enough to read what a renderer built: children are kept,
 * attributes are kept, listeners are kept and can be fired. The sandbox's own
 * stub drops every child, which is right for loading the page and wrong for
 * asking what a row contains.
 */
const FAKE_DOM = `
  document.createElement = function (t) {
    const n = { nodeType: 1, tagName: String(t).toUpperCase(), attrs: {}, kids: [],
      on: {}, value: '', className: '', id: '', tabIndex: 0,
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      append(...c) { this.kids.push(...c); },
      addEventListener(k, fn) { (this.on[k] = this.on[k] || []).push(fn); },
      fire(k, ev) { (this.on[k] || []).forEach((fn) => fn(ev)); },
      showModal() {}, close() {}, focus() {}, replaceWith() {},
    };
    Object.defineProperty(n, 'textContent', {
      get() { return this.kids.map((k) => k.textContent || '').join(''); },
      set(v) { this.kids = v ? [{ nodeType: 3, textContent: String(v) }] : []; },
    });
    return n;
  };
  document.createTextNode = function (t) { return { nodeType: 3, textContent: String(t) }; };
  __walk = function (n, pick, out) {
    out = out || [];
    if (n && n.nodeType === 1) { if (pick(n)) out.push(n); n.kids.forEach((k) => __walk(k, pick, out)); }
    return out;
  };`;
const withDom = () => {
  const { ctx } = loadPanel();
  vm.runInContext(FAKE_DOM, ctx);
  return ctx;
};

describe('the patch carries only what the form changed', () => {
  it('one edited key is one entry, every untouched key is absent', () => {
    const before = { trivialLineThreshold: 40, bypassKeyword: '#skip',
      usage: { bands: { highUSD: 5 } } };
    const after = plain(before);
    after.trivialLineThreshold = 41;
    expect(patchOf(before, after, DEFAULTS)).toEqual([
      { path: ['trivialLineThreshold'], value: 41 }]);
  });

  it('an unchanged form is an empty patch, not a whole-file rewrite', () => {
    const before = { trivialLineThreshold: 40, usage: { bands: { highUSD: 5 } } };
    expect(patchOf(before, plain(before), DEFAULTS)).toEqual([]);
  });

  it('a key holding a dot is addressed by segments, never by a dotted string', () => {
    const before = { usage: { pricing: { 'claude-x': { in: 1 } } } };
    const after = plain(before);
    after.usage.pricing['claude-3.5'] = { in: 2.5 };
    expect(patchOf(before, after, DEFAULTS)).toEqual([
      { path: ['usage', 'pricing', 'claude-3.5', 'in'], value: 2.5 }]);
  });
});

describe('absence is the default; a value present in the draft is written', () => {
  it('a scalar moved onto its shipped default value is WRITTEN, not removed', () => {
    // A default may change in a later release; a key set explicitly is how a
    // project keeps today's value through that.
    expect(patchOf({ trivialLineThreshold: 40 }, { trivialLineThreshold: 30 }, DEFAULTS))
      .toEqual([{ path: ['trivialLineThreshold'], value: 30 }]);
  });

  it('a scalar set from absent to its shipped default value is written', () => {
    expect(patchOf({}, { trivialLineThreshold: 30 }, DEFAULTS))
      .toEqual([{ path: ['trivialLineThreshold'], value: 30 }]);
  });

  it('usage.pricingAsOf typed equal to the shipped date is written, so the rate basis is declared', () => {
    expect(patchOf({}, { usage: { pricingAsOf: '2026-01-01' } }, DEFAULTS))
      .toEqual([{ path: ['usage', 'pricingAsOf'], value: '2026-01-01' }]);
  });

  it('a key the draft no longer holds is a removal', () => {
    expect(patchOf({ trivialLineThreshold: 40 }, {}, DEFAULTS)).toEqual([
      { path: ['trivialLineThreshold'], remove: true }]);
  });
});

describe('the list editor draws the default in without writing it', () => {
  const field = { path: 'exemptGlobs', kind: 'list', label: 'Exempt' };
  const build = (served) => {
    const ctx = withDom();
    vm.runInContext('__cfg = ' + JSON.stringify(served) + ';', ctx);
    const { scalarField, __cfg, __walk } = reach(ctx, ['scalarField', '__cfg', '__walk']);
    const row = scalarField(__cfg, DEFAULTS, field, undefined);
    const box = () => __walk(row, (n) => n.tagName === 'INPUT')[0];
    const add = (v) => { box().value = v; box().fire('keydown', { key: 'Enter' }); };
    const drop = (v) => __walk(row, (n) => n.getAttribute('aria-label') === 'remove ' + v)[0]
      .fire('click');
    return { cfg: __cfg, add, drop };
  };

  it('adding an entry to an unset list writes the list, default included', () => {
    const f = build({});
    f.add('vendor/**');
    expect(plain(f.cfg)).toEqual({ exemptGlobs: ['docs/**', '**/*.md', 'vendor/**'] });
  });

  it('...and taking it back out leaves the key absent, not the default written', () => {
    const f = build({});
    f.add('vendor/**');
    f.drop('vendor/**');
    expect(plain(f.cfg)).toEqual({});
  });

  it('a list already set in the file stays written when edited back onto the default', () => {
    const f = build({ exemptGlobs: ['docs/**', '**/*.md', 'x/**'] });
    f.drop('x/**');
    expect(plain(f.cfg)).toEqual({ exemptGlobs: ['docs/**', '**/*.md'] });
  });
});

describe('a list key set from absent pins the shipped default', () => {
  it('adding one entry to an unset list with a default carries the pin flag', () => {
    const after = { exemptGlobs: ['docs/**', '**/*.md', 'vendor/**'] };
    expect(patchOf({}, after, DEFAULTS)).toEqual([
      { path: ['exemptGlobs'], value: ['docs/**', '**/*.md', 'vendor/**'], pin: true }]);
  });

  it('no pin when the list was already in the file — nothing new is frozen', () => {
    const before = { exemptGlobs: ['docs/**'] };
    expect(patchOf(before, { exemptGlobs: ['docs/**', 'x/**'] }, DEFAULTS)).toEqual([
      { path: ['exemptGlobs'], value: ['docs/**', 'x/**'] }]);
  });

  it('no pin for a list whose shipped default is EMPTY — nothing shipped is copied', () => {
    expect(patchOf({}, { secretPatterns: { extra: ['\\.pem$'] } }, DEFAULTS)).toEqual([
      { path: ['secretPatterns', 'extra'], value: ['\\.pem$'] }]);
  });

  it('no pin for a list with no shipped default — there is nothing to freeze', () => {
    expect(patchOf({}, { extraGlobs: ['a/**'] }, DEFAULTS)).toEqual([
      { path: ['extraGlobs'], value: ['a/**'] }]);
  });
});

describe('the rows the dialog lists are the patch, read for a person', () => {
  it('one row per entry, and the pin rides the row', () => {
    const { ctx } = loadPanel();
    const { configChanges } = reach(ctx, ['configChanges']);
    // `STATE` is a top-level `let`, so it is assigned inside the context.
    vm.runInContext('STATE = ' + JSON.stringify({
      config: { trivialLineThreshold: 40 }, defaults: DEFAULTS }) + ';', ctx);
    const rows = plain(configChanges({ trivialLineThreshold: 30,
      exemptGlobs: ['docs/**', '**/*.md', 'vendor/**'] }));
    expect(rows).toEqual([
      { target: 'config', field: 'exemptGlobs', from: null,
        to: ['docs/**', '**/*.md', 'vendor/**'], pin: true },
      { target: 'config', field: 'trivialLineThreshold', from: 40, to: 30 }]);
  });
});

describe('the confirm dialog marks the pinned row and no other', () => {
  it('exactly one pin note, inside the pinned row', () => {
    const ctx = withDom();
    const { confirmChanges } = reach(ctx, ['confirmChanges']);
    confirmChanges({ title: 'Save settings', verb: 'Save 2 changes', lock: false,
      rows: [
        { target: 'config', field: 'exemptGlobs', from: null, to: ['a/**'], pin: true },
        { target: 'config', field: 'trivialLineThreshold', from: 40, to: 41 }] });
    const { CFDLG, __walk } = reach(ctx, ['CFDLG', '__walk']);
    const rows = __walk(CFDLG, (n) => n.getAttribute('data-cfrow') !== null);
    const pins = (n) => __walk(n, (m) => m.getAttribute('data-cfpin') !== null).length;
    expect(rows.map((r) => [r.getAttribute('data-cfrow'), pins(r)])).toEqual([
      ['config exemptGlobs', 1], ['config trivialLineThreshold', 0]]);
    expect(pins(CFDLG)).toBe(1);
  });
});

describe('the server applies the patch to the file it read', () => {
  it('Python applying the patch to the file reproduces the form', () => {
    const before = { trivialLineThreshold: 40, bypassKeyword: '#skip',
      usage: { bands: { highUSD: 5 }, pricing: { 'claude-x': { in: 1 } } } };
    const after = plain(before);
    after.bypassKeyword = '#go';
    delete after.usage.bands;
    after.usage.pricing['claude-3.5'] = { in: 2.5 };
    const patch = patchOf(before, after, DEFAULTS);
    const [applied] = pyCall('_panel_write', [['apply_config_patch', [before, patch]]]);
    expect(applied).toEqual(after);
  });
});
