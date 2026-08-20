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
  // `tChangeRows` too, and that is the repair this file needed: it compared
  // `r.token` against Python's `field`, which are equal for a layout row and are
  // NOT what the panel sends. The row that goes to the dialog and into
  // `appliedDiff` carries a COMPOSED field, and the composition appended a
  // separator to a row with no mode - so the real field was `'layout · density · '`
  // against the server's `'layout · density'`, and every layout save reported
  // "not exactly what the dialog listed". A test comparing the raw token could
  // not see it.
  const { tLayChanges, tChangeRows } = reach(ctx, ['tLayChanges', 'tChangeRows']);
  return { raw: tLayChanges().map((r) => ({ field: r.token, from: r.from, to: r.to })),
    sent: tChangeRows().map((r) => ({ field: r.field, from: r.from, to: r.to })) };
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
      const byField = (rows) => rows.slice()
        .sort((a, b) => a.field.localeCompare(b.field));
      const got = jsRows(saved, draft);
      expect(byField(got.raw)).toEqual(byField(want));
      // ...and the rows the panel ACTUALLY SENDS agree too. With no token
      // override in play, tChangeRows carries exactly the layout rows.
      expect(byField(got.sent)).toEqual(byField(want));
    });
  }

  it('and a saved density is NOT a change on load [was: 1 unsaved change]', () => {
    // The case the divergence was. Named separately from the sweep above because
    // it is the one a reader met.
    expect(jsRows({ density: 'spacious' }, null).raw).toEqual([]);
    expect(jsRows({ density: 'spacious' }, null).sent).toEqual([]);
  });

  it('while an actual edit still IS one — the guard is not satisfiable by '
     + 'reporting nothing', () => {
    const rows = jsRows({ density: 'spacious' },
      { density: 'compact', order: {} }).raw;
    expect(rows.length).toBe(1);
    expect(rows[0]).toEqual({ field: 'layout · density', from: 'spacious', to: 'compact' });
  });

  it('at least one case in the sweep produces a row', () => {
    // The check on the check: every case above would pass over two empty lists.
    const totals = CASES.map(([label, saved, draft]) =>
      [label, jsRows(saved, draft).raw.length]);
    expect(totals.filter(([, n]) => n > 0).length,
      'no case produced a row: ' + JSON.stringify(totals)).toBeGreaterThan(0);
  });
});
