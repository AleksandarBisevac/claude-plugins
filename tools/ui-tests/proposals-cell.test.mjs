// The Proposals tab's two derived strings, against the Python they mirror.
//
// F93 was one cell — the phase a proposal reserves and how big it is — existing
// in three spellings, two of which counted their own tasks and did not count the
// same ones. The Python side was reduced to `_proposals.reserved_cell`; this file
// is the JavaScript half, and the comparison is made against the LIVE function
// rather than against a string somebody typed here, because a hand-written
// expectation proves only that two authors agreed.
//
// The status half is the same fault one field over. `proposal_rows` carries
// `status`, `statusRaw` and `statusKnown` so a surface can tell a normalised
// reading from what is actually written, and the panel read the normalised one
// for everything — which sent a record carrying a word this plugin never writes
// into the branch that says its phase is live.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

const { propReservedCell, propStatusWords } =
  reach(loadPanel().ctx, ['propReservedCell', 'propStatusWords']);

// Every branch of the Python: a plural count, the singular (which is where the
// two old spellings disagreed with each other), zero, and the absent payload.
const ROWS = [
  { hasPayload: true, phaseId: 'P4', taskCount: 3 },
  { hasPayload: true, phaseId: 'P4', taskCount: 1 },
  { hasPayload: true, phaseId: 'P12', taskCount: 0 },
  { hasPayload: false, phaseId: null, taskCount: 0 },
  // A legacy entry that DOES carry a phase id and no payload. Python refuses to
  // read the id here on purpose; a JS copy testing `phaseId` instead of
  // `hasPayload` would print a phase this record never reserved, and this is the
  // only row that separates the two.
  { hasPayload: false, phaseId: 'P9', taskCount: 2 },
];

describe('propReservedCell mirrors _proposals.reserved_cell', () => {
  const want = pyCall('_proposals', ROWS.map((r) => ['reserved_cell', [r]]));

  it('row for row, including the singular and the dash', () => {
    ROWS.forEach((row, i) => {
      expect(propReservedCell(row), JSON.stringify(row)).toBe(want[i]);
    });
  });

  it('the sweep really exercises both branches — a corpus with no dash in it '
     + 'would pass a version that never returns one', () => {
    expect(want.filter((s) => s === '-').length).toBeGreaterThan(0);
    expect(want.filter((s) => /\(1 task\)$/.test(s)).length).toBeGreaterThan(0);
    expect(want.filter((s) => /\(\d+ tasks\)$/.test(s)).length).toBeGreaterThan(0);
  });

  // NOT ASSERTED HERE: that the count goes through `shared/plural.js` rather
  // than through a hand-rolled `=== 1 ? '' : 's'`. Over every value a real row
  // can carry — `taskCount` is a list length on both the row and the plan step —
  // the two expressions return the same string, so no fixture separates them and
  // a case claiming to check it would be one that cannot fail. It is a property
  // of the SOURCE, and `test__panel_page.py` is where source is the right
  // instrument; the values where they DO differ are values neither producer can
  // emit, and asserting over one would pin a divergence nothing can reach.
});

describe('the badge names what is actually written', () => {
  it('renders the vocabulary word when the status IS one', () => {
    for (const s of ['proposed', 'dropped', 'materialized']) {
      expect(propStatusWords({ status: s, statusRaw: s, statusKnown: true }),
        s).not.toContain('not a status');
    }
  });

  it('says a MISSING status is missing, rather than showing the `proposed` the '
     + 'server normalised it to as though somebody had written it', () => {
    const words = propStatusWords(
      { status: 'proposed', statusRaw: null, statusKnown: false });
    expect(words).toContain('none recorded');
  });

  it('NAMES a value outside the vocabulary instead of title-casing it into '
     + 'something that looks official [label() would render `Parked` in the '
     + 'same type as the three words this plugin writes]', () => {
    const words = propStatusWords(
      { status: 'parked', statusRaw: 'parked', statusKnown: false });
    expect(words).toContain('parked');
    expect(words).toContain('not a status this plugin writes');
  });

  it('reads `statusKnown` and not a list of its own, so the browser and the '
     + 'validator cannot come to hold different vocabularies', () => {
    // `proposed` is in the vocabulary; a surface keeping its own list would
    // answer off the word and ignore the flag. This row is the one that tells
    // the two implementations apart.
    const words = propStatusWords(
      { status: 'proposed', statusRaw: 'proposed', statusKnown: false });
    expect(words).toContain('not a status this plugin writes');
  });
});
