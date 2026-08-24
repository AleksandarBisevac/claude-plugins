// `node --check` per ui/ part, plus the pins the sandbox itself depends on.
//
// Why this is the first file: a syntax error anywhere in the assembled script
// kills the WHOLE inline <script>, and every substring pin on the Python side
// stays green over a dead page, because a pin reads text. The assembled-UI
// skill asks for this check in writing; nothing ran it until now.

import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import {
  PANEL_STRING_PLACEHOLDERS,
  panelParts,
  assemblePanelBody,
  pyParts,
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
  it('finds every report and panel part, all of them nested', () => {
    // Both scripts now live one directory down, so `ui/*.js` matches NOTHING —
    // a flat listing would exit 0 having parsed none of the tree, which is the
    // failure this count exists to make impossible. It used to match panel.js
    // alone and grade a tenth of the tree as clean; the hazard did not change
    // when the last flat file left, it got total.
    expect(parts.length).toBeGreaterThanOrEqual(2);
    const nested = parts.filter((n) => n.includes('/'));
    expect(nested.length).toBe(parts.length);
    // Every part either page is BUILT from must be a part this walk can see.
    for (const name of reportParts()) expect(parts).toContain(name);
    for (const name of panelParts()) expect(parts).toContain(name);
  });

  // THE OTHER DIRECTION, and it is the one that catches a SHORT list (F129).
  // The clause above compares the lists against the walk, so a list that lost
  // its tail still satisfies it - every name it still holds is on disk. The
  // directory is the independent second opinion this needs: a part that exists
  // and that neither page loads is either a part nobody registered or a part
  // list that was cut short, and both used to reach a green run.
  it('every part on disk is loaded by a surface, so no list is short', () => {
    const loaded = new Set([...reportParts(), ...panelParts()]);
    expect(parts.filter((n) => !loaded.has(n))).toEqual([]);
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

  it('the panel parts still carry the request-time placeholders', () => {
    const prepared = substitutePanelPlaceholders(assemblePanelBody());
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

  it('the panel parts run to the end and its formatters are reachable', () => {
    const { ctx } = loadPanel();
    const fns = reach(ctx, ['uTok', 'uCost', 'uPct', 'uShare', 'uCsvText', 'isDark', 'F']);
    for (const name of ['uTok', 'uCost', 'uPct', 'uShare', 'uCsvText', 'isDark']) {
      expect(typeof fns[name], name + ' is not a function').toBe('function');
    }
    // Top-level `const` is in TDZ until its own line runs, so reaching one
    // declared in a LATE part does prove execution got through every earlier
    // part — unlike a hoisted function declaration. `F` is declared in
    // usage-model.js, late in `_panel_ui._JS_PARTS`.
    expect(fns.F.tokens).toBe(7);
  });
});

// F129. The reader used to match `_JS_PARTS = \(([\s\S]*?)\)` over the module's
// SOURCE, which is a second Python parser written as one regex: it ended at the
// first closing parenthesis, so a comment inside the tuple carrying one cut the
// list short and every browser suite silently loaded a panel missing its tail.
// It surfaced as a function that did not exist, never as "the list was short".
//
// These run the SHIPPED reader against fixture modules, because a reader that can
// only ever be pointed at the real file is a reader whose failure cannot be
// reproduced - which is how this survived, and why the repair at the time was a
// comment in _panel_ui.py asking authors not to type a parenthesis.
describe('a part list is asked for, not scanned (F129)', () => {
  const PROBE = '_probe_ui_parts';

  function withModule(body, run) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'audit-ui-parts-'));
    try {
      fs.writeFileSync(path.join(dir, PROBE + '.py'), body, 'utf8');
      return run(dir);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }

  const read = (dir) => pyParts(PROBE, '_JS_PARTS', dir);

  it('a comment carrying parentheses does not truncate the list', () => {
    // Both names must come back. Under the regex the block ended inside
    // `el('thead')` and only the first survived, which is the exact shape the
    // panel shipped: shared parts present, boot part gone.
    const names = withModule(
      '_JS_PARTS = (\n'
      + '    "shared/first.js",\n'
      + "    # a note about el('thead') and (why) the order matters\n"
      + '    "panel/last.js",\n'
      + ')\n', read);
    expect(names).toEqual(['shared/first.js', 'panel/last.js']);
  });

  it('...and neither does a list that is not a literal at all', () => {
    // `_report_ui._CSS_PARTS` is already this shape - it points at a tuple
    // declared in _ui_theme - so a reader that can only see a literal cannot be
    // moved to the CSS side. No source scan reaches this value; the interpreter
    // that computed it does.
    const names = withModule(
      '_RAW = ["panel/b.js", "panel/a.js"]\n'
      + '_JS_PARTS = tuple(sorted(_RAW))\n', read);
    expect(names).toEqual(['panel/a.js', 'panel/b.js']);
  });

  // THE LOUD HALF. A short list must be impossible to mistake for a complete
  // one, so every degenerate shape raises with the attribute named rather than
  // returning something a caller would iterate zero or wrongly.
  it.each([
    ['a missing attribute', '_OTHER = ("panel/a.js",)\n', '_JS_PARTS'],
    ['an empty tuple', '_JS_PARTS = ()\n', 'empty'],
    ['a bare string', '_JS_PARTS = "panel/a.js"\n', 'not a list'],
    ['a non-asset entry', '_JS_PARTS = ("panel/a.js", "panel/a.css")\n', 'panel/a.css'],
  ])('%s raises and says so', (_label, body, needle) => {
    expect(() => withModule(body, read)).toThrow(new RegExp(needle));
  });

  // THE SECOND DIRECTION, and it looks vacuous on purpose: it is the only case
  // that fails if the guards above become unconditional. A well-formed fixture
  // must come back intact and raise nothing.
  it('a well-formed list raises nothing and arrives in order', () => {
    const names = withModule(
      '_JS_PARTS = (\n    "shared/z.js",\n    "panel/a.js",\n)\n', read);
    expect(names).toEqual(['shared/z.js', 'panel/a.js']);
  });
});

describe('the python bridge is present, not assumed', () => {
  it('runs python 3', async () => {
    const { pythonInterpreter } = await import('./python-fmt.mjs');
    const exe = pythonInterpreter();
    expect(execFileSync(exe, ['-c', 'print(1 + 1)'], { encoding: 'utf8' }).trim()).toBe('2');
  });
});
