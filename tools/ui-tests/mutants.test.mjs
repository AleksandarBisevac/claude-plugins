// Proof that the cases in the other files can fail.
//
// This repo's rule: a check that has only ever been seen passing may be
// asserting nothing — break the thing it guards and confirm it goes red. Doing
// that by hand once, in the session the case was written, leaves no evidence
// and does not survive the next refactor. So each mutation is applied HERE, to
// the source text in memory, and the file on disk is never touched: the loader
// takes a `mutate` hook for exactly this and nothing else.
//
// Every case asserts a DIFFERENCE, so a mutation that silently matched nothing
// fails this file instead of passing it. `mutateOnce` additionally refuses to
// run unless the text it replaces occurs exactly once, which turns "the source
// was reformatted" into a named failure rather than a vacuous green.

import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';
import { pyFmt } from './python-fmt.mjs';

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

describe('the token cases would catch a truncation change', () => {
  const pythonFractions = () => pyFmt([[2.6], [2.4], [-2.6], [999.9]]
    .map(([n]) => ['fmt_tokens', [n, 1]]));

  it('report.js fmtTokens goes wrong when Math.trunc becomes Math.round', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce('const whole = Math.trunc(n || 0);',
        'const whole = Math.round(n || 0);'),
    });
    const { fmtTokens } = reach(ctx, ['fmtTokens']);
    const got = [2.6, 2.4, -2.6, 999.9].map((n) => fmtTokens(n, 1));
    expect(got).not.toEqual(pythonFractions());
    expect(got[0]).toBe('3');       // and it is wrong in the way we said
  });

  // The one that matters, now pointing the other way. Before the fix this read
  // "uTok AGREES once Math.round becomes Math.trunc", because Math.round was
  // what shipped; the fix made Math.trunc the source, so the mutation that
  // reproduces the defect is the reverse one. Same single line, same two
  // directions — if this stops failing, panel.js has quietly gone back to
  // rounding a magnitude nothing else rounds.
  it('panel.js uTok goes wrong when Math.trunc becomes Math.round', () => {
    const { ctx } = loadPanel({
      mutate: mutateOnce('return String(Math.trunc(n));', 'return String(Math.round(n));'),
    });
    const { uTok } = reach(ctx, ['uTok']);
    const got = [2.6, 2.4, -2.6, 999.9].map((n) => uTok(n, 1));
    expect(got).not.toEqual(pythonFractions());
    expect(got[0]).toBe('3');       // and it is wrong in the way we said
  });

  it('...and unmutated it agrees, which is the repair', () => {
    const { uTok } = reach(loadPanel().ctx, ['uTok']);
    expect([2.6, 2.4, -2.6, 999.9].map((n) => uTok(n, 1))).toEqual(pythonFractions());
  });
});

// The half-even tie rule is a CONDITIONAL, so it has two wrong implementations
// and not one: the tie test never fires (native toFixed is back, and every
// exact tie rounds away from zero again), or it always fires (a value that is
// not a tie gets stepped down and a correct answer is broken). The second
// looks vacuous — it asserts that a non-tie is left alone — and it is the only
// case that fails when someone "simplifies" the guard away. Both are mutated
// in both files, because the helper exists twice and neither copy is covered
// by the other's mutation.
describe('the tie cases would catch either failure of the half-even rule', () => {
  const REPORT_GUARD =
    '    if (!isFinite(scaled) || Math.floor(scaled) !== scaled || scaled % 2 === 0) return s;';
  const PANEL_GUARD =
    ' if(!isFinite(scaled)||Math.floor(scaled)!==scaled||scaled%2===0)return s;';

  // 1250/1000 and 0.125 are exact ties; 3050/1000 at dp=2 is not (3.05 is not
  // representable, so Python rounds it UP and so must we).
  const [TIE_TOKENS, TIE_COST, NON_TIE] = pyFmt([
    ['fmt_tokens', [1250, 1]], ['fmt_cost', [0.125]], ['fmt_tokens', [3050, 2]]]);

  it('report.js reverts to away-from-zero when the tie test never fires', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce(REPORT_GUARD, '    if (true) return s;'),
    });
    const { fmtTokens, fmtCost } = reach(ctx, ['fmtTokens', 'fmtCost']);
    expect(fmtTokens(1250, 1)).not.toBe(TIE_TOKENS);
    expect(fmtTokens(1250, 1)).toBe('1.3K');
    expect(fmtCost(0.125)).not.toBe(TIE_COST);
  });

  it('report.js breaks a NON-tie when the tie test always fires', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce(REPORT_GUARD, '    if (false) return s;'),
    });
    const { fmtTokens } = reach(ctx, ['fmtTokens']);
    expect(fmtTokens(3050, 2)).not.toBe(NON_TIE);
    expect(fmtTokens(3050, 2)).toBe('3.04K');   // 3.05 was never a tie
  });

  it('panel.js reverts to away-from-zero when the tie test never fires', () => {
    const { ctx } = loadPanel({ mutate: mutateOnce(PANEL_GUARD, ' if(true)return s;') });
    const { uTok, uCost } = reach(ctx, ['uTok', 'uCost']);
    expect(uTok(1250, 1)).not.toBe(TIE_TOKENS);
    expect(uTok(1250, 1)).toBe('1.3K');
    expect(uCost(0.125)).not.toBe(TIE_COST);
  });

  it('panel.js breaks a NON-tie when the tie test always fires', () => {
    const { ctx } = loadPanel({ mutate: mutateOnce(PANEL_GUARD, ' if(false)return s;') });
    const { uTok } = reach(ctx, ['uTok']);
    expect(uTok(3050, 2)).not.toBe(NON_TIE);
    expect(uTok(3050, 2)).toBe('3.04K');
  });
});

// The repo's signature rule — a real value must never render as nothing —
// has TWO wrong implementations, not one: the guard never fires (real spend
// prints $0.00, a real slice prints 0%), or it always fires (a true zero
// prints <$0.01, an empty slice prints <1%). Both directions are mutated,
// because the second one is the case that looks vacuous and gets cut.
describe('the money and share cases would catch either failure of the sub-unit rule', () => {
  it('fmtCost prints $0.00 for real spend when the guard never fires', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce("if (v && Math.abs(v) < 0.01) return '<$0.01';",
        "if (false && Math.abs(v) < 0.01) return '<$0.01';"),
    });
    const { fmtCost } = reach(ctx, ['fmtCost']);
    expect(fmtCost(0.004)).toBe('$0.00');
    expect(fmtCost(0.004)).not.toBe(pyFmt([['fmt_cost', [0.004]]])[0]);
  });

  it('fmtCost prints <$0.01 for a true zero when the guard always fires', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce("if (v && Math.abs(v) < 0.01) return '<$0.01';",
        "if (Math.abs(v) < 0.01) return '<$0.01';"),
    });
    const { fmtCost } = reach(ctx, ['fmtCost']);
    expect(fmtCost(0)).toBe('<$0.01');
    expect(fmtCost(0)).not.toBe(pyFmt([['fmt_cost', [0]]])[0]);
  });

  it('uPct rounds a real slice away to 0% without its sub-percent branch', () => {
    const { ctx } = loadPanel({
      mutate: mutateOnce("const uPct=x=>x==null?'—':x<1&&x>0?'<1%':uFixedHalfEven(x,0)+'%';",
        "const uPct=x=>x==null?'—':uFixedHalfEven(x,0)+'%';"),
    });
    const { uPct, uShare } = reach(ctx, ['uPct', 'uShare']);
    expect(uPct(uShare(4, 1000))).toBe('0%');
    expect(uPct(uShare(4, 1000))).not.toBe(pyFmt([['fmt_share', [4, 1000, '—']]])[0]);
  });
});

describe('the CSV cases would catch a narrowed quoting rule', () => {
  it('report.js csvQuote stops quoting newlines when \\r\\n leaves the class', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce('return /[",\\r\\n]/.test(s)', 'return /[",]/.test(s)'),
    });
    const { csvQuote } = reach(ctx, ['csvQuote']);
    expect(csvQuote('a\nb')).toBe('a\nb');          // the corruption
    expect(csvQuote('a,b')).toBe('"a,b"');          // still quotes what it kept
  });

  it('panel.js uCsvText stops quoting newlines under the same cut', () => {
    const { ctx } = loadPanel({
      mutate: mutateOnce('return /[",\\r\\n]/.test(s)', 'return /[",]/.test(s)'),
    });
    const { uCsvText, F } = reach(ctx, ['uCsvText', 'F']);
    const row = [];
    for (const k of Object.keys(F)) row[F[k]] = 'x';
    row[F.cost] = 0.5;
    row[F.task] = 'a\nb';
    expect(uCsvText([row])).toContain('a\nb');
    expect(uCsvText([row])).not.toContain('"a\nb"');
  });
});

describe('the sort cases would catch a comparator that stopped comparing numbers', () => {
  it('natCmp reverts to a string sort without the numeric term', () => {
    const { ctx } = loadReport({
      mutate: mutateOnce(
        'const c = (an[0] - bn[0]) || an[1].localeCompare(bn[1]);',
        'const c = an[1].localeCompare(bn[1]);'),
    });
    const { natCmp } = reach(ctx, ['natCmp']);
    const ids = ['P1.10', 'P1.2', 'P1.9'];
    expect(ids.slice().sort(natCmp)).not.toEqual(['P1.2', 'P1.9', 'P1.10']);
  });
});

describe('the theme matrix would catch a looser explicit-choice test', () => {
  it("isDark treats 'auto' as dark once `=== dark` becomes `!== light`", () => {
    const { ctx, sandbox } = loadReport({
      prefersDark: true,
      mutate: mutateOnce(
        "return t ? t === 'dark' : prefersDark();",
        "return t ? t !== 'light' : prefersDark();"),
    });
    sandbox.document.documentElement.setAttribute('data-theme', 'auto');
    expect(reach(ctx, ['isDark']).isDark()).toBe(true);   // the matrix says false
  });
});

describe('the sandbox pins would catch a source that moved', () => {
  it('refuses a mutation whose target is gone', () => {
    expect(() => loadReport({ mutate: mutateOnce('no such text here', 'x') }))
      .toThrow(/occurs 0 times/);
  });

  it('refuses to load a panel whose request-time placeholder is gone', () => {
    // Substituting nothing would leave `__AUDIT_TOKEN__` as a bare identifier
    // and the load would die on a ReferenceError somewhere unrelated. Named
    // here instead.
    expect(() => loadPanel({ mutate: (src) => src.replace('__AUDIT_TOKEN__', '"x"') }))
      .toThrow(/no longer carries __AUDIT_TOKEN__/);
  });

  it('refuses a mutation whose target is not in the source', () => {
    // The harness's loud-failure path. A mutation that silently matches nothing
    // leaves every case below running against unmodified source and passing for
    // the wrong reason - the proof stops proving anything without saying so.
    expect(() => loadReport({
      mutate: mutateOnce('a string no part of the report contains', 'x'),
    })).toThrow(/occurs 0 times/);
  });
});
