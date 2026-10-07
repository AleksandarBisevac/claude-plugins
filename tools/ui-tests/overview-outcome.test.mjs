// The Overview row's outcome: where it went, and what still has to show it.
//
// The row used to carry the phase's `desiredOutcome` on a second line, on EVERY
// row. On a real manifest that text is near-identical from row to row — the demo
// generator's own phases differ in one word — so it doubled the height of every
// row and separated none of them. It is on the row's tooltip and at the head of
// the opened detail now.
//
// What that removal put at risk is the reason this suite exists. The search box
// reaches the outcome (it says so: "id, title, area, outcome…"), so a row can be
// in a filtered list because of a field the row no longer renders — a claim with
// its basis off screen, which is the defect class this repo names most often. The
// answer is a line shown for exactly those rows, carrying a window of the outcome
// centred on the hit.
//
// Both halves are pure functions at the top level of `ui/panel/overview.js`, and
// they are here rather than in a Python case because a substring pin can only say
// the source contains a call — it cannot say the term is inside the window. The
// PAINTED half (a row is one line tall; the tooltip carries the text) belongs to
// the browser gate in `tools/ui-checks/stage-tabs.mjs`.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { REPO_ROOT, loadPanel, reach } from './sandbox.mjs';

const P = reach(loadPanel().ctx, ['ovExcerpt', 'ovShownText', 'ovOutcomeIsBasis']);

// Not invented prose: this is the sentence `gen-demo-manifest.py` gives every
// demo phase, which is what the panel's own screenshots are taken against. The
// case below asserts it is still that sentence, so a fixture that drifts away
// from the real source says so instead of quietly testing something else.
const OUTCOME = 'Everything under src/api that this phase touches is validated and '
  + 'covered by a test that would fail without the fix.';
const PHASE = {
  id: 'P1', title: 'Api pass 1', area: ['api'], desiredOutcome: OUTCOME,
};
const W = 64;

describe('the fixture is the demo generator\'s own outcome', () => {
  it('both halves of it are still in gen-demo-manifest.py', () => {
    const py = fs.readFileSync(path.join(REPO_ROOT, 'plugins', 'audit', 'scripts',
      'demo', 'gen-demo-manifest.py'), 'utf8');
    expect(py).toContain('Everything under src/%s that this phase touches is validated and ');
    expect(py).toContain('covered by a test that would fail without the fix.');
  });
});

describe('ovShownText is the fields the ROW puts on screen', () => {
  it('id, title and area tags, lower-cased', () => {
    expect(P.ovShownText(PHASE)).toBe('p1 api pass 1 api');
  });

  it('and NOT the outcome — the one that would make the basis line dead code', () => {
    // The second direction. `ovOutcomeIsBasis` asks whether a visible field
    // already carries the term; if this list grew to include the outcome, that
    // question would answer "yes" for every outcome hit, the line would never
    // render, and every case above would still pass.
    expect(P.ovShownText(PHASE)).not.toContain('validated');
  });

  it('a phase with no title and no areas is still a string', () => {
    expect(P.ovShownText({ id: 'P7' })).toBe('p7  ');
  });
});

describe('ovOutcomeIsBasis fires only when the row shows no other reason', () => {
  it('a term found only in the outcome', () => {
    expect(P.ovOutcomeIsBasis(PHASE, 'validated')).toBe(true);
  });

  it('a term the title and the area badge already carry — the noise direction', () => {
    // "api" is in the id-less visible text AND in the outcome. A predicate that
    // ignored the visible half would put the line back on every row, which is
    // the defect this change removed.
    expect(P.ovOutcomeIsBasis(PHASE, 'api')).toBe(false);
    expect(P.ovOutcomeIsBasis(PHASE, 'pass')).toBe(false);
  });

  it('no term at all: nothing is being explained, so nothing is shown', () => {
    expect(P.ovOutcomeIsBasis(PHASE, '')).toBe(false);
    expect(P.ovOutcomeIsBasis(PHASE, undefined)).toBe(false);
  });

  it('case is normalised here, not trusted from the caller', () => {
    expect(P.ovOutcomeIsBasis(PHASE, 'VALIDATED')).toBe(true);
  });

  it('a phase with no outcome cannot match on one', () => {
    expect(P.ovOutcomeIsBasis({ id: 'P2', title: 'x', area: [] }, 'validated')).toBe(false);
  });
});

describe('ovExcerpt makes the hit visible, not merely claimed', () => {
  it('the term is inside the window wherever it sits in the text', () => {
    // The load-bearing case. The line is clipped to ONE line, so a head-only
    // truncation would ship rows announcing "matched in outcome" with the
    // matching words off screen — the exact shape of a claim without its basis.
    const term = 'xy';
    const missed = [];
    for (let i = 0; i <= OUTCOME.length - term.length; i += 1) {
      const text = OUTCOME.slice(0, i) + term + OUTCOME.slice(i + term.length);
      if (!P.ovExcerpt(text, term, W).includes(term)) missed.push(i);
    }
    expect(missed, 'offsets whose hit fell outside the window').toEqual([]);
  });

  it('and the window stays bounded, so the line cannot grow back to two', () => {
    // The other direction: an implementation that "fixed" a lost hit by
    // returning the whole outcome passes the case above and reintroduces the
    // height this change removed.
    for (const term of ['validated', 'Everything', 'fix.']) {
      expect(P.ovExcerpt(OUTCOME, term, W).length,
        term).toBeLessThanOrEqual(W + 2);
    }
  });

  it('text that already fits is returned untouched — no ellipsis for nothing', () => {
    expect(P.ovExcerpt('short outcome', 'outcome', W)).toBe('short outcome');
  });

  it('the ellipsis marks the side that was actually cut', () => {
    const head = P.ovExcerpt(OUTCOME, 'Everything', W);
    expect(head.startsWith('…'), head).toBe(false);
    expect(head.endsWith('…'), head).toBe(true);
    const tail = P.ovExcerpt(OUTCOME, 'without the fix', W);
    expect(tail.startsWith('…'), tail).toBe(true);
    expect(tail.endsWith('…'), tail).toBe(false);
    const mid = P.ovExcerpt(OUTCOME, 'touches', W);
    expect(mid.startsWith('…') && mid.endsWith('…'), mid).toBe(true);
  });

  it('a term longer than the window widens it rather than cutting the term', () => {
    const term = 'validated and covered by a test';
    expect(P.ovExcerpt(OUTCOME, term, 8)).toContain(term);
  });

  it('a term that is not there returns the head, never an empty line', () => {
    // Defensive: the caller decides whether to render, and a caller that got its
    // own condition wrong should paint the field rather than an empty span.
    const got = P.ovExcerpt(OUTCOME, 'zzq-matches-nothing', W);
    expect(got.length).toBeGreaterThan(1);
    expect(OUTCOME.startsWith(got.slice(0, 20))).toBe(true);
  });

  it('nothing in, nothing out', () => {
    expect(P.ovExcerpt('', 'x', W)).toBe('');
    expect(P.ovExcerpt(undefined, 'x', W)).toBe('');
  });
});

// The row's COPY NOTE. A phase worked on in another worktree reaches the Overview
// as that worktree holds it, and the rollup entry carries `copy` - the sentence
// naming where it was read from. The row is the only place a reader sees which
// copy a count came from, so the note is shown whenever the entry carries one and
// never otherwise. Reached per case rather than at the top, so a source without
// the helper fails these cases by name instead of the whole file.
describe('ovCopyNote names the copy a row was read from', () => {
  const C = () => reach(loadPanel().ctx, ['ovCopyNote']);

  it('a row read from a linked worktree says so, and is marked live', () => {
    const got = C().ovCopyNote({ id: 'P1', copy: {
      live: true, basis: 'read from the worktree file /x/p1-tree/P1.json' } });
    expect(got).toEqual({ live: true,
      text: 'copy: read from the worktree file /x/p1-tree/P1.json' });
  });

  it('a row that fell back to this checkout is marked stale, never live', () => {
    const got = C().ovCopyNote({ id: 'P1', copy: {
      live: false, basis: "shows this checkout's copy - may not be current" } });
    expect(got.live).toBe(false);
    expect(got.text).toContain("shows this checkout's copy");
  });

  it('the twin: a row of this checkout\'s own live copy carries no note', () => {
    // The over-fire direction. A helper that always answered would paint a
    // note on every row of every plan, and the cases above would still pass.
    expect(C().ovCopyNote({ id: 'P2' })).toBe(null);
    expect(C().ovCopyNote({ id: 'P2', copy: {} })).toBe(null);
    expect(C().ovCopyNote({ id: 'P2', copy: null })).toBe(null);
  });
});

// The READY NOW card's copy notes. The card's numbers - which tasks are ready,
// and so which command a reader copies - can come from a phase read from another
// worktree's copy, either because the ready task is in that phase or because it
// depends on a task there. The server names those phases (`readyCopies`, one
// line each in `/audit:status`'s wording); this turns them into what the card
// draws, and nothing when there are none.
describe('ovReadyCopyNotes draws the copies Ready now was read from', () => {
  const C = () => reach(loadPanel().ctx, ['ovReadyCopyNotes']);

  it('one note per named phase, in the server\'s words, live or stale', () => {
    const got = C().ovReadyCopyNotes({ readyCopies: [
      { phase: 'P1', live: true, line: 'phase P1 read from the worktree file /x/P1.json' },
      { phase: 'P4', live: false, line: "phase P4 shows this checkout's copy - may not be current" },
    ] });
    expect(got).toEqual([
      { live: true, text: 'phase P1 read from the worktree file /x/P1.json' },
      { live: false, text: "phase P4 shows this checkout's copy - may not be current" },
    ]);
  });

  it('the twin: nothing named, or an older payload with no key, draws nothing', () => {
    // The over-fire direction: a card that drew a note for every payload would
    // pass the case above.
    expect(C().ovReadyCopyNotes({ readyCopies: [] })).toEqual([]);
    expect(C().ovReadyCopyNotes({})).toEqual([]);
    expect(C().ovReadyCopyNotes({ readyCopies: [{ phase: 'P1', live: true }] })).toEqual([]);
  });
});

// The TASK STRIP. Its pills count `tasks.byStatus`, which the server takes over
// the plan with each live copy laid over it. The filter a pill sets keeps a
// phase by that phase's own count of the status - and those counts used to come
// from the composition, which is this checkout's copy, so with a phase finished
// in a worktree the `done` pill read 1 and pressing it showed no phase.
describe('ovPhaseStatus is the strip filter\'s counts, off the pills\' plan', () => {
  const C = () => reach(loadPanel().ctx, ['ovPhaseStatus']);
  // P1 read from a worktree that finished P1.1; this checkout's composition
  // still has it pending, which is what the filter must NOT read.
  const ROLLUP = {
    tasks: { total: 3, byStatus: { done: 1, pending: 2 } },
    phaseTaskStatus: { P1: { done: 1, pending: 1 }, P2: { pending: 1 } },
  };

  it('every pill\'s count is what its filter finds, with a phase overlaid', () => {
    const per = C().ovPhaseStatus(ROLLUP);
    for (const [st, n] of Object.entries(ROLLUP.tasks.byStatus)) {
      const found = Object.keys(per).reduce((a, pid) => a + ((per[pid] || {})[st] || 0), 0);
      expect(found, st).toBe(n);
    }
    expect(Object.keys(per).filter((pid) => (per[pid] || {}).done)).toEqual(['P1']);
  });

  it('the twin: nothing overlaid, nothing done, and no phase kept by `done`', () => {
    const per = C().ovPhaseStatus({ tasks: { total: 2, byStatus: { pending: 2 } },
      phaseTaskStatus: { P1: { pending: 1 }, P2: { pending: 1 } } });
    expect(Object.keys(per).filter((pid) => (per[pid] || {}).done)).toEqual([]);
  });

  it('a phase id that is an Object.prototype name is a phase, not a property', () => {
    const per = C().ovPhaseStatus({ phaseTaskStatus: { constructor: { done: 2 } } });
    expect(per.constructor.done).toBe(2);
    expect(C().ovPhaseStatus({}).toString).toBe(undefined);
  });
});
