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
  reportParts,
  reportTags,
  assembleReportBody,
  UI_DIR,
  loadPanel,
  loadReport,
  reach,
  readPart,
  substitutePanelPlaceholders,
  uiParts,
} from './sandbox.mjs';

describe('every ui/ part parses', () => {
  const parts = uiParts();

  // Counted, not merely iterated. `for (const p of [])` is a green test over
  // nothing, and a directory read that returned an empty list would look
  // exactly like a tree in which every part is fine.
  it('finds the panel and every report part, including nested ones', () => {
    // The report's script lives one directory down. A flat listing would find
    // panel.js alone and report a clean syntax check over a tenth of the tree,
    // which is the failure this count exists to make impossible.
    expect(parts.length).toBeGreaterThanOrEqual(2);
    expect(parts).toContain('panel.js');
    const nested = parts.filter((n) => n.includes('/'));
    expect(nested.length).toBeGreaterThan(0);
    // Every part the page is BUILT from must be a part this walk can see.
    for (const name of reportParts()) expect(parts).toContain(name);
  });

  it.each(parts)('node --check %s', (name) => {
    const result = spawnSync(process.execPath, ['--check', path.join(UI_DIR, name)],
      { encoding: 'utf8' });
    expect(result.stderr + result.stdout).toBe('');
    expect(result.status).toBe(0);
  });
});

describe('the sandbox reads what it thinks it reads', () => {
  it('the parts assemble into one module script with no wrapper of their own', () => {
    // A module has its own scope, so the parts need no IIFE: nothing they
    // declare at top level reaches the page's globals. What must hold is that
    // no part smuggles a wrapper back in, and that the joined body is a
    // complete program rather than a fragment that only parses in context.
    const tags = reportTags();
    expect(tags.open).toContain('type="module"');
    for (const name of reportParts()) {
      const part = readPart(name);
      expect(part.startsWith('(function () {')).toBe(false);
      expect(part).not.toContain('<script');
    }
    const body = assembleReportBody();
    expect(() => new vm.Script(body)).not.toThrow();
    // A module is always strict, so the body has to parse that way too. A
    // sloppy-mode parse accepts octal literals, duplicate parameter names and
    // assignments to undeclared names, all of which the page would reject at
    // load — this is the parse that matches what the browser actually does.
    expect(() => new vm.Script("'use strict';\n" + body)).not.toThrow();
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
    // Read through `reach`, not off the context object: a top-level `let` lives
    // in the global LEXICAL environment and never appears as a property.
    expect(reach(ctx, ['DMAX']).DMAX).toBe('');
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
