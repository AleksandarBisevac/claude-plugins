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

// --- the patch, built from two configs ---------------------------------------

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
    // `STATE` is a top-level `let`, so it is assigned inside the context. Only
    // the defaults come from it: the base is the second argument.
    vm.runInContext('STATE = ' + JSON.stringify({ defaults: DEFAULTS }) + ';', ctx);
    const rows = plain(configChanges({ trivialLineThreshold: 30,
      exemptGlobs: ['docs/**', '**/*.md', 'vendor/**'] }, { trivialLineThreshold: 40 }));
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

// --- the base a form diffs against, under another writer ----------------------

// The base a form diffs against is the config it was DRAWN from, never whatever
// `STATE.config` holds when Save is pressed. The disk refresh replaces `STATE`
// while a form is dirty — it defers the re-render, not the read — so a diff taken
// against the fresh read lists another writer's change as the user's own and the
// patch sends it back at the value the form was drawn with.
describe('a form diffs its draft against the config it was rendered from', () => {
  const GROUPS = [{ id: 'g', title: 'G', fields: [
    { path: 'trivialLineThreshold', kind: 'int', label: 'Trivial' },
    { path: 'bypassKeyword', kind: 'text', label: 'Bypass' }] }];
  const SERVED = { trivialLineThreshold: 40, bypassKeyword: '#skip' };

  /**
   * The Settings form, drawn over SERVED, with the save path's two exits
   * recorded: what the confirm dialog was handed, and what the PUT carried.
   */
  const settingsForm = async () => {
    const { ctx } = loadPanel({ placeholders: { __SETTINGS__: JSON.stringify(GROUPS) } });
    // Loading the page starts its boot, which assigns STATE from the stub fetch
    // after its first await. Let it finish first, or it lands on top of the
    // fixture below in the middle of a case.
    await new Promise((r) => setTimeout(r, 0));
    vm.runInContext(FAKE_DOM, ctx);
    vm.runInContext(`
      (function () {
        const make = document.createElement;
        document.createElement = function (t) {
          const n = make(t);
          n.replaceChildren = function (...c) { this.kids = c; };
          n.classList = { add() {}, remove() {}, contains() { return false; } };
          n.querySelectorAll = function () { return []; };
          Object.defineProperty(n, 'childNodes', { get() { return this.kids; } });
          return n;
        };
      })();
      __root = document.createElement('div');
      document.querySelector = function (s) {
        return s === '#guards' ? __root : document.createElement('div'); };
      __shown = []; __sent = [];
      confirmSave = async function (o) { const r = o.rows(); __shown.push(r); return r; };
      fetch = async function (p, init) {
        const body = JSON.parse(init.body); __sent.push(body);
        return { json: async () => ({ ok: true, findings: [], warnings: [],
          applied: __shown[__shown.length - 1] }) };
      };
      STATE = ${JSON.stringify({ config: SERVED, defaults: DEFAULTS })};`, ctx);
    const f = reach(ctx, ['renderSettings', '__root', '__walk', 'EDITS']);
    f.renderSettings();
    const pick = (attr, v) => f.__walk(f.__root, (n) => n.getAttribute(attr) === v)[0];
    return {
      ctx,
      type: (path, v) => { const i = pick('id', 'set-' + path); i.value = v; i.oninput(); },
      // Awaited: Save is async, and a case that read the state before the PUT
      // resolved would be asserting the moment before the write.
      save: () => Promise.all((pick('data-save', 'guards').on.click || []).map((fn) => fn())),
      pending: () => plain(f.EDITS.guards()),
      shown: () => plain(reach(ctx, ['__shown']).__shown),
      sent: () => plain(reach(ctx, ['__sent']).__sent),
      replaceState: (config) => vm.runInContext('STATE = ' + JSON.stringify(
        { config, defaults: DEFAULTS }) + ';', ctx),
    };
  };

  it('another writer changed b while a was dirty: the patch and the rows name only a', async () => {
    const form = await settingsForm();
    form.type('trivialLineThreshold', '41');
    form.replaceState({ trivialLineThreshold: 40, bypassKeyword: '#other' });
    await form.save();
    expect(form.shown().map((rows) => rows.map((r) => r.field)))
      .toEqual([['trivialLineThreshold']]);
    expect(form.sent()).toEqual([
      { patch: [{ path: ['trivialLineThreshold'], value: 41 }] }]);
  });

  it('...while with no other writer the same edit is the same single row', async () => {
    // The allow twin: a base read from anywhere that drops the user's own key
    // would pass the case above by sending nothing at all.
    const form = await settingsForm();
    form.type('trivialLineThreshold', '41');
    expect(form.pending().map((r) => [r.field, r.from, r.to]))
      .toEqual([['trivialLineThreshold', 40, 41]]);
    await form.save();
    expect(form.sent()).toEqual([
      { patch: [{ path: ['trivialLineThreshold'], value: 41 }] }]);
  });

  it('after a successful save the form reads clean, so its base moved with the write', async () => {
    // For the mutation that never resets the base: the saved key would stay
    // listed as unsaved, and a second Save would send it again.
    const form = await settingsForm();
    form.type('trivialLineThreshold', '41');
    form.replaceState({ trivialLineThreshold: 40, bypassKeyword: '#other' });
    await form.save();
    expect(form.pending()).toEqual([]);
  });
});

// The Policy tab is the same class with a worse ending: its Save replaced the
// whole block, so a rule another writer added while the draft was open was not
// merely misattributed in the dialog — it was overwritten. Driven through the
// page's own boot, disk refresh and Save button, so the draft and its base are
// taken wherever the page takes them rather than where this file assumes.
describe('the policy save carries only the reader\'s own change', () => {
  const MINE = { skills: { deny: ['shell-runner'] } };

  /**
   * A booted panel whose server answers from `server`, a mutable stand-in for
   * the config file; every write the page sends is recorded with its route.
   */
  const policyPanel = async (server) => {
    const { ctx } = loadPanel();
    await new Promise((r) => setTimeout(r, 0));
    vm.runInContext(FAKE_DOM, ctx);
    vm.runInContext(`
      (function () {
        const make = document.createElement;
        document.createElement = function (t) {
          const n = make(t);
          n.replaceChildren = function (...c) { this.kids = c; };
          n.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
          n.querySelector = function () { return null; };
          n.querySelectorAll = function () { return []; };
          n.style = {};
          Object.defineProperty(n, 'childNodes', { get() { return this.kids; } });
          return n;
        };
      })();
      __root = document.createElement('div');
      document.querySelector = function (s) {
        return s === '#policy' ? __root : document.createElement('div'); };
      __writes = [];
      confirmSave = async function (o) { const r = o.rows(); __shown = r; return r; };`, ctx);
    const answer = (m, p, body) => {
      if (m !== 'GET') {
        vm.runInContext('__writes.push(' + JSON.stringify({ m, p, body }) + ')', ctx);
        return { ok: true, findings: [], warnings: [], applied: [] };
      }
      if (p.indexOf('/api/state') === 0) {
        return { config: server.config, defaults: DEFAULTS, composition: { tasks: [] } };
      }
      if (p.indexOf('/api/policy') === 0) {
        return { stored: server.config.policy || null, rules: {}, areaInfo: [],
          activeAreas: [], resolved: {}, findings: [], warnings: [] };
      }
      return {};
    };
    ctx.__answer = answer;
    vm.runInContext(`fetch = async function (p, init) {
      const m = (init && init.method) || 'GET';
      const r = __answer(m, p, init && init.body ? JSON.parse(init.body) : null);
      return { json: async () => r }; };`, ctx);
    const f = reach(ctx, ['boot', 'refreshFromDisk', 'pEdit', 'pAddPattern',
      'pDropPattern', 'renderPolicy', '__root', '__walk', 'EDITS']);
    await f.boot().catch(() => {});
    return {
      add: (kind, list, pattern) => f.pEdit(() => f.pAddPattern(kind, list, null, pattern)),
      drop: (kind, list, pattern) => f.pEdit(() => f.pDropPattern(kind, list, null, pattern)),
      pending: () => plain(f.EDITS.policy()),
      refresh: () => f.refreshFromDisk(null),
      save: () => Promise.all((f.__walk(f.__root,
        (n) => n.getAttribute('data-psave') === '1')[0].on.click || []).map((fn) => fn())),
      shown: () => plain(reach(ctx, ['__shown']).__shown),
      writes: () => plain(reach(ctx, ['__writes']).__writes),
    };
  };

  it('another writer adds a rule while the draft is dirty: the request carries only '
     + 'the reader\'s rule, and the other one survives the write', async () => {
    const server = { config: { trivialLineThreshold: 40 } };
    const page = await policyPanel(server);
    page.add('skills', 'deny', 'shell-runner');
    // Another writer, between the draft and the Save: the poll reads it in.
    server.config = { trivialLineThreshold: 40,
      policy: { agents: { deny: ['doc-writer'] } } };
    await page.refresh();
    await page.save();
    const writes = page.writes();
    expect(writes.map((w) => [w.m, w.p.split('?')[0]])).toEqual([['PUT', '/api/config']]);
    expect(writes[0].body).toEqual({ patch: [
      { path: ['policy', 'skills', 'deny'], value: ['shell-runner'] }] });
    expect(page.shown().map((r) => r.field)).toEqual(['policy.skills.deny']);
    const [applied] = pyCall('_panel_write',
      [['apply_config_patch', [server.config, writes[0].body.patch]]]);
    expect(applied.policy).toEqual({ agents: { deny: ['doc-writer'] }, ...MINE });
  });

  it('removing the reader\'s last rule does not take another writer\'s new one with it', async () => {
    // The block goes empty in the draft. Written as "set policy to {}", the
    // patch would replace the whole block on the server and drop the rule the
    // other writer added; the removal alone says what the reader did.
    const server = { config: { policy: { skills: { deny: ['shell-runner'] } } } };
    const page = await policyPanel(server);
    page.drop('skills', 'deny', 'shell-runner');
    server.config = { policy: { skills: { deny: ['shell-runner'] },
      agents: { deny: ['doc-writer'] } } };
    await page.refresh();
    await page.save();
    const writes = page.writes();
    expect(writes.map((w) => w.body)).toEqual([{ patch: [
      { path: ['policy', 'skills', 'deny'], remove: true }] }]);
    const [applied] = pyCall('_panel_write',
      [['apply_config_patch', [server.config, writes[0].body.patch]]]);
    expect(applied.policy).toEqual({ agents: { deny: ['doc-writer'] } });
  });

  it('a block the reader empties, with no other writer, is sent as removals and '
     + 'lands ABSENT, not as an empty block', async () => {
    // Pinned because it is a choice: the diff never writes a literal `{}` over a
    // branch it clears. Absent and `{}` read the same for the policy block, but
    // not for every key the same diff serves.
    const server = { config: { trivialLineThreshold: 40,
      policy: { skills: { deny: ['shell-runner'] } } } };
    const page = await policyPanel(server);
    page.drop('skills', 'deny', 'shell-runner');
    await page.save();
    const writes = page.writes();
    expect(writes.map((w) => w.body)).toEqual([{ patch: [
      { path: ['policy', 'skills', 'deny'], remove: true }] }]);
    const [applied] = pyCall('_panel_write',
      [['apply_config_patch', [server.config, writes[0].body.patch]]]);
    expect(applied).toEqual({ trivialLineThreshold: 40 });
  });

  it('with no other writer the same edit is the same single entry, and the tab '
     + 'reads clean once the server has said yes', async () => {
    // The allow twin, and the base-reset direction: a base that never moved
    // would keep listing the saved rule as unsaved.
    const server = { config: { trivialLineThreshold: 40 } };
    const page = await policyPanel(server);
    page.add('skills', 'deny', 'shell-runner');
    expect(page.pending().map((r) => r.field)).toEqual(['policy.skills.deny']);
    server.config = { trivialLineThreshold: 40, policy: MINE };
    await page.save();
    expect(page.writes().map((w) => w.body)).toEqual([{ patch: [
      { path: ['policy', 'skills', 'deny'], value: ['shell-runner'] }] }]);
    expect(page.pending()).toEqual([]);
  });
});
