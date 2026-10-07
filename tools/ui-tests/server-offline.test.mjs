// A panel whose server has stopped, with the tab still open.
//
// The page used to keep looking live: Save still opened its dialog, and the PUT
// behind it rejected into an uncaught TypeError with nothing on screen. Three
// claims are pinned here, each beside the twin that keeps it from over-firing:
//
//   - a WRITE whose fetch rejects resolves to a refusal-shaped answer, so every
//     save path can render it; a READ whose fetch rejects still rejects, because
//     boot and the poll decide on that rejection;
//   - the run-status poll owns liveness: a fetch that rejects marks the page
//     offline, the next one that answers clears it, and an answer carrying
//     `ok:false` is an answer — it never marks the page offline;
//   - while offline, `confirmSave` refuses before any dialog opens.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * A panel with a fetch the case controls, a recorded toast, a recorded confirm
 * dialog, and one write control the offline state can reach through its hook.
 *
 * `__net` is what the next fetch does: 'down' rejects the way a browser does on a
 * refused connection, anything else resolves with that value as the JSON body.
 */
function panel() {
  const { ctx } = loadPanel();
  vm.runInContext(
    '__log = []; __net = {};'
    + 'fetch = function () { return __net === "down"'
    + '  ? Promise.reject(new TypeError("Failed to fetch"))'
    + '  : Promise.resolve({ ok: true, json: function () { return Promise.resolve(__net); } }); };'
    + 'toast = function (m, k) { __log.push(["toast", m, k]); };'
    + 'confirmChanges = function (o) { __log.push(["confirm", o.verb]); return Promise.resolve(true); };'
    // One Save that is live, and one control already unavailable for a reason
    // of its own — the clear must hand back only what the offline state took.
    + '__save = document.createElement("button"); __save.setAttribute("data-save", "guards");'
    + '__other = document.createElement("button"); __other.setAttribute("data-psave", "1");'
    + '__other.setAttribute("aria-disabled", "true");'
    + '__sels = [];'
    + 'document.querySelectorAll = function (s) { __sels.push(s);'
    + '  return /\\[data-save\\]/.test(s) ? [__save, __other] : []; };', ctx);
  const net = (v) => vm.runInContext('__net = ' + JSON.stringify(v) + ';', ctx);
  const get = (n) => reach(ctx, [n])[n];
  const fn = (n) => reach(ctx, [n])[n];
  return { ctx, net, get, fn };
}

const ROWS = [{ target: 'config', field: 'mode', from: 'a', to: 'b' }];
const spec = () => ({
  rows: () => ROWS, title: 'Save settings', scope: 'guards',
  empty: 'no settings changed', note: 'writes .claude/audit.config.json',
});

describe('a write whose fetch rejects', () => {
  it('resolves to ok false, saying the server did not answer and the edits are '
     + 'still in the form', async () => {
    const p = panel();
    p.net('down');
    const res = await p.fn('api')('PUT', '/api/config', { a: 1 });
    expect(res.ok).toBe(false);
    expect(res.findings.length).toBe(1);
    expect(res.findings[0]).toMatch(/did not answer/);
    expect(res.findings[0]).toMatch(/no write is confirmed/);
    expect(res.findings[0]).toMatch(/still in the form/);
  });

  it('and saveOutcome says THAT, not that the save was rejected', async () => {
    // "rejected — nothing was written" is a claim about what the server did, and
    // a rejected fetch cannot tell a refused connection from an answer lost after
    // the write — so the page may only say what it knows.
    const p = panel();
    p.net('down');
    const res = await p.fn('api')('PUT', '/api/config', { a: 1 });
    p.fn('saveOutcome')(res, ROWS, 'the config', null);
    const toasts = p.get('__log').filter((e) => e[0] === 'toast');
    expect(toasts.length).toBe(1);
    expect(toasts[0][1]).toMatch(/did not answer/);
    expect(toasts[0][1]).not.toMatch(/nothing was written/);
    expect(toasts[0][2]).toBe('err');
  });

  it('allow twin: a server that answers with a refusal is still reported as one',
    async () => {
      const p = panel();
      p.net({ ok: false, findings: ['mode: not one of the allowed values'] });
      const res = await p.fn('api')('PUT', '/api/config', { a: 1 });
      expect(res).toEqual({ ok: false, findings: ['mode: not one of the allowed values'] });
      p.fn('saveOutcome')(res, ROWS, 'the config', null);
      expect(p.get('__log')[0][1]).toBe('rejected — nothing was written');
    });

  it('a READ whose fetch rejects still rejects', async () => {
    const p = panel();
    p.net('down');
    await expect(p.fn('api')('GET', '/api/state')).rejects.toThrow();
  });
});

describe('the poll owns liveness', () => {
  it('a poll whose fetch rejects marks the page offline, and the next poll that '
     + 'answers clears it', async () => {
    const p = panel();
    const root = p.get('document').documentElement;
    p.net('down');
    await p.fn('pollRunStatus')();
    expect(p.get('OFFLINE')).toBe(true);
    expect(root.getAttribute('data-offline')).toBe('1');
    p.net({ index: null, phases: {} });
    await p.fn('pollRunStatus')();
    expect(p.get('OFFLINE')).toBe(false);
    expect(root.getAttribute('data-offline')).toBe(null);
  });

  it('while offline the write controls are unavailable, and the clear hands back '
     + 'only what the offline state took', async () => {
    const p = panel();
    const save = p.get('__save'), other = p.get('__other');
    p.net('down');
    await p.fn('pollRunStatus')();
    expect(save.getAttribute('aria-disabled')).toBe('true');
    expect(other.getAttribute('aria-disabled')).toBe('true');
    p.net({ index: null, phases: {} });
    await p.fn('pollRunStatus')();
    expect(save.getAttribute('aria-disabled')).toBe('false');
    // Unavailable for its own reason before the outage, and still so after it.
    expect(other.getAttribute('aria-disabled')).toBe('true');
  });

  it('an answer that arrives with ok false never marks it offline', async () => {
    const p = panel();
    p.net({ ok: false, findings: ['the manifest could not be read'] });
    await p.fn('pollRunStatus')();
    expect(p.get('OFFLINE')).toBe(false);
    expect(p.get('document').documentElement.getAttribute('data-offline')).toBe(null);
    expect(p.get('__save').getAttribute('aria-disabled')).toBe(null);
  });
});

describe('Save while offline', () => {
  it('confirmSave refuses with the offline sentence and opens no dialog',
    async () => {
      const p = panel();
      p.net('down');
      await p.fn('pollRunStatus')();
      const got = await p.fn('confirmSave')(spec());
      expect(got).toBe(null);
      const log = p.get('__log');
      expect(log.filter((e) => e[0] === 'confirm')).toEqual([]);
      expect(log.length).toBe(1);
      expect(log[0][1]).toMatch(/not answering/);
      expect(log[0][1]).toMatch(/still in the form/);
      expect(log[0][2]).toBe('err');
    });

  it('allow twin: once a poll answers again, Save opens its dialog', async () => {
    const p = panel();
    p.net('down');
    await p.fn('pollRunStatus')();
    p.net({ index: null, phases: {} });
    await p.fn('pollRunStatus')();
    const got = await p.fn('confirmSave')(spec());
    expect(got).toEqual(ROWS);
    expect(p.get('__log')).toEqual([['confirm', 'Save 1 change']]);
  });
});
