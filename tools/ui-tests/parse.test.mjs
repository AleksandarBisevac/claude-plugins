// `node --check` per ui/ part, plus the pins the sandbox itself depends on.
//
// Why this is the first file: a syntax error anywhere in the assembled script
// kills the WHOLE inline <script>, and every substring pin on the Python side
// stays green over a dead page, because a pin reads text. The assembled-UI
// skill asks for this check in writing; nothing ran it until now.

import { execFileSync, spawnSync } from 'node:child_process';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import {
  PANEL_STRING_PLACEHOLDERS,
  REPORT_IIFE_HEAD,
  REPORT_IIFE_TAIL,
  UI_DIR,
  loadPanel,
  loadReport,
  reach,
  readPart,
  substitutePanelPlaceholders,
  uiParts,
  unwrapReportSource,
} from './sandbox.mjs';

describe('every ui/ part parses', () => {
  const parts = uiParts();

  // Counted, not merely iterated. `for (const p of [])` is a green test over
  // nothing, and a directory read that returned an empty list would look
  // exactly like a tree in which every part is fine.
  it('finds at least the two known parts', () => {
    expect(parts.length).toBeGreaterThanOrEqual(2);
    expect(parts).toContain('report.js');
    expect(parts).toContain('panel.js');
  });

  it.each(parts)('node --check %s', (name) => {
    const result = spawnSync(process.execPath, ['--check', path.join(UI_DIR, name)],
      { encoding: 'utf8' });
    expect(result.stderr + result.stdout).toBe('');
    expect(result.status).toBe(0);
  });
});

describe('the sandbox reads what it thinks it reads', () => {
  it('report.js is still exactly one file-spanning IIFE', () => {
    const src = readPart('report.js');
    expect(src.startsWith(REPORT_IIFE_HEAD)).toBe(true);
    expect(src.endsWith(REPORT_IIFE_TAIL)).toBe(true);
    // The claim is not "the head and tail are present" — report.js contains
    // three more inner IIFEs that also close with `})();`. The claim is that
    // the FIRST head and the LAST tail are each other's match, i.e. the wrapper
    // spans the whole file. Compiling proves it in both directions: the body
    // alone is balanced, and the body with the tail still attached is not.
    expect(() => new vm.Script(unwrapReportSource(src))).not.toThrow();
    expect(() => new vm.Script(src.slice(REPORT_IIFE_HEAD.length)))
      .toThrow(/Unexpected token|Unexpected end/);
  });

  it('panel.js still carries the request-time placeholders', () => {
    const prepared = substitutePanelPlaceholders(readPart('panel.js'));
    for (const name of PANEL_STRING_PLACEHOLDERS) {
      expect(prepared.placeholders).toContain(name);
    }
    expect(prepared.source).not.toMatch(/__[A-Z0-9_]+__/);
  });

  // WHAT MAKES "runs to the end" TRUE: a throw inside vm.runInContext
  // propagates, so a load that returns at all is a load that finished. It is
  // worth saying because reachability alone would NOT prove it — every
  // `function` declaration in report.js hoists, so `typeof fmtTokens` is
  // 'function' even when the script died on its 71st line. The `var` and
  // `const` pins below are the ones that need the statements to have run.
  it('report.js runs to the end and its formatters are reachable', () => {
    const { ctx } = loadReport();
    const fns = reach(ctx, ['fmtTokens', 'fmtCost', 'fmtInt', 'natCmp', 'csvQuote',
      'isDark', 'prefersDark']);
    for (const [name, fn] of Object.entries(fns)) {
      expect(typeof fn, name + ' is not a function').toBe('function');
    }
    // Assigned by a statement, not hoisted: '' is what an empty stub table
    // leaves behind, and `undefined` is what an aborted load leaves behind.
    expect(ctx.DMAX).toBe('');
  });

  it('panel.js runs to the end and its formatters are reachable', () => {
    const { ctx } = loadPanel();
    const fns = reach(ctx, ['uTok', 'uCost', 'uPct', 'uShare', 'uCsvText', 'isDark', 'F']);
    for (const name of ['uTok', 'uCost', 'uPct', 'uShare', 'uCsvText', 'isDark']) {
      expect(typeof fns[name], name + ' is not a function').toBe('function');
    }
    // Top-level `const` is in TDZ until its own line runs, so reaching one
    // declared past panel.js's three-thousandth line does prove execution got
    // that far — unlike a hoisted function declaration.
    expect(fns.F.tokens).toBe(7);
  });
});

describe('the python bridge is present, not assumed', () => {
  it('runs python 3', async () => {
    const { pythonInterpreter } = await import('./python-fmt.mjs');
    const exe = pythonInterpreter();
    expect(execFileSync(exe, ['-c', 'print(1 + 1)'], { encoding: 'utf8' }).trim()).toBe('2');
  });
});
