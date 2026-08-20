// The Appearance tab's LAYOUT change rows, against the Python that produces the
// rows the server echoes back.
//
// `tLayChanges()` in the panel and `_panel_write._layout_changes()` in Python
// describe the same two decisions — the density and the per-view card order — and
// the panel's answer is what the confirm dialog SHOWS while Python's is what the
// save REPORTS. `appliedDiff` compares them by `field`, so a row one side invents
// is a save that says "Saved, but not exactly what the dialog listed".
//
// The divergence this file was written for: the panel compared the density with
// the shipped `'comfortable'` constant while Python compares it with the SAVED
// density. So wearing a theme that names a density read as one unsaved change the
// moment it loaded, for a change nobody had made — and pressing Save then produced
// that mismatch message. The card order was already compared against the saved
// value, one line below, which is what made the inconsistency visible at all.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

/**
 * `tLayChanges()` with a given saved layout and a given draft.
 * @param {Object} saved what THEME.layout carries
 * @param {?Object} draft what TLAY holds, or null for "no local edits"
 */
function jsRows(saved, draft) {
  const { ctx } = loadPanel();
  vm.runInContext('THEME = ' + JSON.stringify({ layout: saved })
    + '; TLAY = ' + JSON.stringify(draft) + ';', ctx);
  const { tLayChanges } = reach(ctx, ['tLayChanges']);
  // The panel's row carries `token`/`mode`/`layout`; Python's carries
  // `scope`/`field`. The comparable part is the FIELD and the two values, which is
  // exactly what appliedDiff keys on.
  return tLayChanges().map((r) => ({ field: r.token, from: r.from, to: r.to }));
}

/** The same question put to `_panel_write._layout_changes`. */
function pyRows(before, after) {
  const [rows] = pyCall('_panel_write', [['_layout_changes', [before, after]]]);
  return rows.map((r) => ({ field: r.field, from: r.from, to: r.to }));
}

// Each case is (label, saved layout, draft) — and `tLayout()` fills a missing
// density with 'comfortable', so the Python side is given the same completion.
const CASES = [
  ['nothing saved, nothing drafted', {}, null],
  ['a saved density, no local edit', { density: 'spacious' }, null],
  ['a saved density, drafted back to the default',
   { density: 'spacious' }, { density: 'comfortable', order: {} }],
  ['no saved density, a drafted one', {}, { density: 'compact', order: {} }],
  ['a saved order, no local edit',
   { order: { over: ['bugs', 'phases'] } }, null],
  ['a saved order, drafted to something else',
   { order: { over: ['bugs', 'phases'] } }, { order: { over: ['phases', 'bugs'] } }],
  ['both, drafted to both', { density: 'spacious', order: { over: ['a', 'b'] } },
   { density: 'compact', order: { over: ['b', 'a'] } }],
];

describe('the dialog shows the rows the save will report', () => {
  for (const [label, saved, draft] of CASES) {
    it('agrees with _layout_changes: ' + label, () => {
      const after = draft || { density: saved.density || 'comfortable',
                               order: saved.order || {} };
      const want = pyRows(saved, after);
      expect(jsRows(saved, draft).slice().sort((a, b) => a.field.localeCompare(b.field)))
        .toEqual(want.slice().sort((a, b) => a.field.localeCompare(b.field)));
    });
  }

  it('and a saved density is NOT a change on load [was: 1 unsaved change]', () => {
    // The case the divergence was. Named separately from the sweep above because
    // it is the one a reader met.
    expect(jsRows({ density: 'spacious' }, null)).toEqual([]);
  });

  it('while an actual edit still IS one — the guard is not satisfiable by '
     + 'reporting nothing', () => {
    const rows = jsRows({ density: 'spacious' }, { density: 'compact', order: {} });
    expect(rows.length).toBe(1);
    expect(rows[0]).toEqual({ field: 'layout · density', from: 'spacious', to: 'compact' });
  });

  it('at least one case in the sweep produces a row', () => {
    // The check on the check: every case above would pass over two empty lists.
    const totals = CASES.map(([label, saved, draft]) =>
      [label, jsRows(saved, draft).length]);
    expect(totals.filter(([, n]) => n > 0).length,
      'no case produced a row: ' + JSON.stringify(totals)).toBeGreaterThan(0);
  });
});
