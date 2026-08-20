// The Appearance tab as a WRITABLE SURFACE, which is the thing it was not.
//
// Every other surface registers a change-row function in `EDITS`, and three
// readers depend on that: `beforeunload` earns the right to interrupt a close,
// the confirm dialog lists what is about to be written, and the browser gate's
// `dirtyRows()` spans the lot. The theme card registered nothing. Its draft lives
// in memory only - nothing persists TDRAFT or TLAY - so closing the tab took every
// unsaved colour with it, silently, on the one surface whose Save has no Discard
// beside it because it offers an undo trail instead. An undo trail does not
// survive the page.
//
// The rows were also the wrong shape. They carried a `scope` key of their own
// where the protocol says `target`, so both readers that dereference it got
// `undefined`: the dialog printed a blank target cell and stamped
// `data-cfrow="undefined <field>"`, and `cfTouched` - which names the phases a
// lock notice mentions - collected a null for every theme row. Python said `scope`
// too, so the two agreed with each other and with nothing else.
//
// WHAT THIS CANNOT SEE: the painted dialog. The rows are asserted, not the cells
// they become; `assertSavebarCensus` in tools/capture-screenshots.mjs asks the
// live page whether every view offering a Save has a registry entry at all.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

/**
 * A rendered Appearance tab over a saved theme, with an optional draft edit.
 * @param {boolean} edited whether to put one override on the draft
 */
function appearance(edited) {
  // `__CONTRAST_PAIRS__: '[]'` for the reason theme-undo.test.mjs gives: the
  // sandbox stubs a non-string placeholder as `{}`, and renderAppearance grades
  // the draft's contrast, so `TPAIRS.forEach` is not a function. An empty table
  // is the honest value - this file is about the registry, not the grading.
  const { ctx } = loadPanel({ placeholders: { __CONTRAST_PAIRS__: '[]' } });
  vm.runInContext(
    // cfTouched reads STATE.composition to map a task id to its phase; a theme
    // row is neither, and that is the point of the case below.
    'STATE = {composition:{tasks:[{id:"t1",phaseId:"p1"}]}};'
    + 'THEME = ' + JSON.stringify({
      theme: { '--accent': { $value: '#111111', $dark: '#111111' } },
      default: { '--accent': { $value: '#000000', $dark: '#ffffff' } },
      groups: [{ title: 'Colour', tokens: ['--accent'] }],
      layout: {}, warnings: [],
    }) + '; TDRAFT = null; TLAY = null;', ctx);
  const f = reach(ctx, ['renderAppearance', 'tSet', 'tChangeRows', 'cfTouched',
    'surfaceDirty', 'editRows']);
  f.renderAppearance();
  if (edited) f.tSet('--accent', 'light', '#222222');
  // Read fresh: EDITS is mutated by the render, and tSet reassigns TDRAFT.
  f.editsKeys = () => Object.keys(reach(ctx, ['EDITS']).EDITS);
  f.anyDirty = () => f.editsKeys().some(f.surfaceDirty);
  return f;
}

describe('the theme card registers its unsaved work', () => {
  it('renderAppearance puts an entry in the registry [was: none at all]', () => {
    expect(appearance(false).editsKeys()).toContain('look');
  });

  it('and beforeunload can therefore see a theme draft', () => {
    const p = appearance(true);
    expect(p.surfaceDirty('look')).toBe(true);
    expect(p.anyDirty()).toBe(true);
  });

  it('while a matching theme is clean — the entry is not just always dirty', () => {
    const p = appearance(false);
    expect(p.editRows('look')).toEqual([]);
    expect(p.surfaceDirty('look')).toBe(false);
  });
});

describe('the rows are the shape every reader of a row expects', () => {
  it('each row names its target, and none carries a scope key of its own', () => {
    const rows = appearance(true).tChangeRows();
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(r.target).toBe('theme');
      expect('scope' in r).toBe(false);
      expect(r.field).toMatch(/^--accent/);
    }
  });

  it('cfTouched answers "theme" [was: null, for every theme row]', () => {
    const p = appearance(true);
    expect(p.cfTouched(p.tChangeRows())).toEqual(['theme']);
  });

  it('and the dialog row hook the census reaches by does not read "undefined"', () => {
    // The literal `'data-cfrow':r.target+' '+r.field` in confirmChanges. Asserted
    // on the value rather than the DOM, because the stub does not build a tree.
    for (const r of appearance(true).tChangeRows()) {
      expect(r.target + ' ' + r.field).not.toContain('undefined');
    }
  });

  it('a clean theme produces no rows, so nothing above passes over an empty '
     + 'list', () => {
    expect(appearance(false).tChangeRows()).toEqual([]);
  });
});

describe('Reset shows the same rows reversed', () => {
  // Built as a reversal of the one builder rather than a second copy of the
  // mapping - the copy is what let the shape drift in the first place.
  it('same fields, from and to swapped', () => {
    const p = appearance(true);
    const rows = p.tChangeRows();
    const reversed = rows.map((r) => ({ target: 'theme', field: r.field,
      from: r.to, to: r.from }));
    expect(reversed.map((r) => r.field)).toEqual(rows.map((r) => r.field));
    for (let i = 0; i < rows.length; i++) {
      expect(reversed[i].from).toBe(rows[i].to);
      expect(reversed[i].to).toBe(rows[i].from);
    }
    // And a reversal is only meaningful where the two ends differ.
    expect(rows.some((r) => String(r.from) !== String(r.to))).toBe(true);
  });
});

describe('the token rows agree with _theme_changes', () => {
  // The gate that was missing. `tLayChanges` had a differential test against
  // `_layout_changes`; the TOKEN half had none, which is how the panel came to
  // measure against the shipped default while the server measured against the
  // saved theme. Nothing compared them, so nothing complained.
  //
  // Both sides are given the SAME token set, read from `_ui_theme` rather than
  // invented here: Python walks THEME_TOKENS and the panel walks the groups the
  // server sent, so a hand-picked group would compare two different sweeps.
  // Read from `theme_state`, which is the payload the panel is actually SERVED -
  // not from `_ui_theme`'s own tables, whose THEME_SINGLE is a set that JSON
  // will not carry. Using the served shape also means this compares the groups
  // the page really walks.
  const [state] = pyCall('_panel_write', [['theme_state', ['.']]]);
  const groups = state.groups, single = state.single;
  const tokens = groups.flatMap((g) => g.tokens);
  const twoValued = tokens.filter((t) => !single.includes(t));

  /** `tUnsaved` over a given saved theme and draft, as {field, from, to}. */
  function jsRows(saved, draft) {
    const { ctx } = loadPanel({ placeholders: { __CONTRAST_PAIRS__: '[]' } });
    // The REAL default and the REAL single-valued set, both from the same
    // payload: `tSingle` reads THEME.single, and a fixture without it calls every
    // token two-valued - which showed up here as a `· light` the server does not
    // spell.
    vm.runInContext('THEME = ' + JSON.stringify({
      theme: saved, default: state.default, single: single, groups: groups,
      layout: {}, warnings: [],
    }) + '; TDRAFT = ' + JSON.stringify(draft) + '; TLAY = null;', ctx);
    const { tUnsaved, tRowField } = reach(ctx, ['tUnsaved', 'tRowField']);
    return tUnsaved().map((ch) => ({ field: tRowField(ch),
      from: ch.from, to: ch.to }));
  }

  /** The same question put to Python, which is handed the MERGED after-state. */
  function pyRows(saved, draft) {
    const after = Object.assign({}, saved);
    for (const [name, entry] of Object.entries(draft || {})) {
      after[name] = Object.assign({}, saved[name] || {}, entry);
    }
    const [rows] = pyCall('_panel_write', [['_theme_changes', [saved, after]]]);
    return rows.map((r) => ({ field: r.field, from: r.from, to: r.to }));
  }

  const A = twoValued[0], B = twoValued[1], S = single[0];
  const CASES = [
    ['nothing saved, nothing drafted', {}, {}],
    ['a saved token, no draft — the case that used to read as a change',
     { [A]: { $value: '#111111', $dark: '#222222' } }, {}],
    ['one column drafted over a saved token',
     { [A]: { $value: '#111111', $dark: '#222222' } },
     { [A]: { $value: '#333333' } }],
    ['both columns drafted', {},
     { [A]: { $value: '#444444', $dark: '#555555' } }],
    ['two tokens at once', { [B]: { $value: '#666666', $dark: '#777777' } },
     { [A]: { $value: '#888888' }, [B]: { $dark: '#999999' } }],
    ['a single-valued token has no dark row', {}, { [S]: { $value: '4px' } }],
  ];

  for (const [label, saved, draft] of CASES) {
    it('agrees: ' + label, () => {
      const byField = (rows) => rows.slice()
        .sort((a, b) => (a.field + a.from).localeCompare(b.field + b.from));
      expect(byField(jsRows(saved, draft))).toEqual(byField(pyRows(saved, draft)));
    });
  }

  it('and a saved token with no draft is NOT a change [was: every token in a '
     + 'worn theme]', () => {
    expect(jsRows({ [A]: { $value: '#111111', $dark: '#222222' } }, {})).toEqual([]);
  });

  it('at least one case in the sweep produces a row', () => {
    // The check on the check: every case above passes over two empty lists.
    const totals = CASES.map(([label, saved, draft]) =>
      [label, jsRows(saved, draft).length]);
    expect(totals.filter(([, n]) => n > 0).length,
      'no case produced a row: ' + JSON.stringify(totals)).toBeGreaterThan(1);
  });
});
