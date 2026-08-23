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
