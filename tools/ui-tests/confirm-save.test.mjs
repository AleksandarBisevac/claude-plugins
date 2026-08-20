// The three steps every Save begins with, once.
//
// Five writable surfaces opened their Save the same way — ask the form what it
// would write, refuse an empty save, get consent — and then diverged completely: a
// different endpoint, payload and re-render each. Only the opening was ever
// shared, which is why `confirmSave` is that and nothing more.
//
// The scout found this after the save/discard footers were factored: reshaping the
// tree moved the next-largest duplication into view, which is the argument for
// running it again after every extraction rather than once.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * Drive `confirmSave` over a chosen number of rows and a chosen consent.
 * @param {number} n how many unsaved rows the surface reports
 * @param {boolean} consent what the confirm dialog answers
 */
async function attempt(n, consent) {
  const { ctx } = loadPanel();
  const rows = [];
  for (let i = 0; i < n; i++) rows.push({ target: 't', field: 'f' + i, from: 1, to: 2 });
  vm.runInContext(
    '__log = []; __rows = ' + JSON.stringify(rows) + ';'
    + 'confirmChanges = function (o) { __log.push(["confirm", o]);'
    + '  return Promise.resolve(' + (consent ? 'true' : 'false') + '); };'
    + 'toast = function (m) { __log.push(["toast", m]); };', ctx);
  const { confirmSave } = reach(ctx, ['confirmSave']);
  const got = await confirmSave({
    rows: () => reach(ctx, ['__rows']).__rows,
    title: 'Save settings', scope: 'guards',
    empty: 'no settings changed', note: 'writes .claude/audit.config.json',
  });
  return { got, log: reach(ctx, ['__log']).__log, ctx };
}

describe('nothing to save', () => {
  it('says so and asks nothing', async () => {
    const r = await attempt(0, true);
    expect(r.got).toBe(null);
    expect(r.log).toEqual([['toast', 'nothing to save — no settings changed']]);
  });

  it('and the sentence is the caller\'s half, not a generic one', async () => {
    // Each surface names what did not change in its own words; the helper owns
    // only the part that is the same everywhere.
    expect((await attempt(0, true)).log[0][1]).toContain('no settings changed');
  });
});

describe('something to save', () => {
  it('confirms with the rows, the scope and an agreeing verb', async () => {
    const r = await attempt(3, true);
    expect(r.log.map((e) => e[0])).toEqual(['confirm']);
    const o = r.log[0][1];
    expect(o.title).toBe('Save settings');
    expect(o.scope).toBe('guards');
    expect(o.verb).toBe('Save 3 changes');
    expect(o.note).toContain('audit.config.json');
    expect(o.rows.length).toBe(3);
  });

  it('one change is singular, which the old per-surface copies each spelled '
     + 'themselves', async () => {
    expect((await attempt(1, true)).log[0][1].verb).toBe('Save 1 change');
  });

  it('hands the rows back when the reader agrees', async () => {
    const r = await attempt(2, true);
    expect(r.got).not.toBe(null);
    expect(r.got.length).toBe(2);
  });

  it('and NULL when they decline — the caller has nothing different to do about '
     + 'that and an empty form', async () => {
    const r = await attempt(2, false);
    expect(r.got).toBe(null);
    // Declining is not an error and says nothing extra: the dialog closing IS
    // the feedback.
    expect(r.log.map((e) => e[0])).toEqual(['confirm']);
  });
});

describe('the rows are asked HERE', () => {
  it('not captured by the caller, so a form that moved is what gets confirmed',
    async () => {
      const { ctx } = loadPanel();
      vm.runInContext(
        '__log = []; __rows = [{target:"t",field:"a",from:1,to:2},'
        + '{target:"t",field:"b",from:1,to:2}];'
        + 'confirmChanges = function (o) { __log.push(o); return Promise.resolve(true); };'
        + 'toast = function () {};', ctx);
      const { confirmSave } = reach(ctx, ['confirmSave']);
      // The caller's `rows` closure reads current state each time it is called.
      const spec = {
        rows: () => reach(ctx, ['__rows']).__rows,
        title: 't', scope: 's', empty: 'e', note: 'n',
      };
      await confirmSave(spec);
      vm.runInContext('__rows = __rows.slice(0, 1);', ctx);
      await confirmSave(spec);
      const verbs = reach(ctx, ['__log']).__log.map((o) => o.verb);
      expect(verbs).toEqual(['Save 2 changes', 'Save 1 change']);
    });
});
