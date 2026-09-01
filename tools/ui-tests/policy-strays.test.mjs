// The policy switchboard's portability narrowing, RUN rather than read.
//
// This tab is the one place where hiding a row could MISREPORT ENFORCEMENT. Its
// verdicts are what the guard hook will do on this machine, and a capability in a
// home directory really is governed here — so the narrowing is only ever legitimate
// for a row nobody wrote a rule about. `pStray` carries that whole argument in two
// conditions, and the cases below exist because dropping either one is invisible
// in a screenshot: drop the `rule` half and a DENY disappears; drop the `travels`
// half and the tab empties.
//
// Reported live before this was written: a project using a handful of repo skills
// listed a hundred and twenty rows, every one of them reading "policy.skills.default
// is allow".
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const panel = loadPanel();
const { pStray, pStrays } = reach(panel.ctx, ['pStray', 'pStrays']);

function setMode(mode) {
  vm.runInContext(`POLICY = {portability:${JSON.stringify(mode)}};`, panel.ctx);
  vm.runInContext('PF.strays = null;', panel.ctx);
}

const row = (over) => ({ name: 'x', travels: true, rule: null, ...over });

describe('pStray — which rows the filter may hide', () => {
  it('hides a capability that would not survive a clone and that no rule names', () => {
    expect(pStray(row({ travels: false }))).toBe(true);
  });

  // THE SECOND DIRECTION OF THE `travels` HALF. Drop it and every row becomes a
  // stray, which empties the tab on a machine whose skills are all repo-carried.
  it('keeps one that travels', () => {
    expect(pStray(row({ travels: true }))).toBe(false);
  });

  // THE SECOND DIRECTION OF THE `rule` HALF, and the one that matters most: a
  // refusal that is not on screen is a lie about what the guard will do. Each of
  // these is a row somebody deliberately wrote.
  it('keeps a denied capability wherever it lives', () => {
    expect(pStray(row({ travels: false, rule: 'web-*',
                        verdict: 'violation' }))).toBe(false);
  });

  it('keeps an allow-listed one', () => {
    expect(pStray(row({ travels: false, rule: 'web-security' }))).toBe(false);
  });

  it('keeps one audit itself requires', () => {
    expect(pStray(row({ travels: false, rule: 'audit-codebase',
                        required: true }))).toBe(false);
  });

  // An UNKNOWN verdict is not a refusal — the same rule the pickers follow. A
  // settings file that could not be parsed is no basis for hiding anything.
  it('keeps one whose verdict could not be reached', () => {
    expect(pStray(row({ travels: null }))).toBe(false);
  });
});

describe('pStrays — whether they are on screen', () => {
  it('opens narrowed under strict', () => {
    setMode('strict');
    expect(pStrays()).toBe(false);
  });

  // THE SECOND DIRECTION: a narrowing that ignored the tier would pass the case
  // above and fail these two, and it would be hiding rows in a project that never
  // asked for any of this.
  it('opens showing everything under warn and off', () => {
    setMode('warn');
    expect(pStrays()).toBe(true);
    setMode('off');
    expect(pStrays()).toBe(true);
  });

  it('lets the reader override the tier, in both directions', () => {
    setMode('strict');
    vm.runInContext('PF.strays = true;', panel.ctx);
    expect(pStrays()).toBe(true);
    setMode('warn');
    vm.runInContext('PF.strays = false;', panel.ctx);
    expect(pStrays()).toBe(false);
  });

  // `false` is a choice and `null` is "not yet asked" — folding them together is
  // how a reader's "show them" would be forgotten on the next render.
  it('tells a reader who chose to hide from one who has not chosen', () => {
    setMode('warn');
    vm.runInContext('PF.strays = false;', panel.ctx);
    expect(pStrays()).toBe(false);
    vm.runInContext('PF.strays = null;', panel.ctx);
    expect(pStrays()).toBe(true);
  });
});
