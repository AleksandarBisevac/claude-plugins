// Which area columns the capability table draws.
//
// One column per area does not scale: the tags come from the plan, so eight areas
// is eight selects on every row and a sideways scroll of em-dashes. A column is
// drawn for an area that CARRIES A RULE, and the rest are offered by name.
//
// WHY HERE AND NOT AS A PIN. `pCols` is a pure function over `POLICY` and
// `PDRAFT`, and the claim is about what it ANSWERS, not about how the source is
// spelled. A substring pin over the assembled page can say the predicate exists;
// it cannot tell "only the areas with a rule" from "all of them" or from "none of
// them", which are the two ways this can be wrong. Those two are mutated in
// tools/ui-tests/mutants.test.mjs, and this file is what those mutations break.
//
// "Carries a rule" and "is active" are DIFFERENT PREDICATES, and conflating them
// is the defect this file exists to prevent: an area rule applies only while some
// phase in that area has work in progress, so a dormant area's rule decides
// nothing today and everything the moment that phase starts. Every case below
// therefore uses a fixture in which the two predicates DISAGREE — one live area
// with no rule, one dormant area with one — because a fixture where they agree
// cannot tell the right predicate from the wrong one.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/** Four areas: liveness and ruledness vary independently, one of each pairing. */
const AREA_INFO = [
  { tag: 'api', active: true, registered: true, description: null },
  { tag: 'web', active: true, registered: true, description: null },
  { tag: 'infra', active: false, registered: true, description: null },
  { tag: 'docs', active: false, registered: true, description: null },
];

/**
 * A loaded panel whose policy states rules for exactly the areas named.
 *
 * @param {Object<string, Object>} areas the `areas` sub-block for `skills`
 * @param {Object} [extra] fields merged onto the state (e.g. a differing draft)
 */
function panelWithAreas(areas, extra) {
  const { ctx } = loadPanel();
  const stored = { skills: { deny: ['shell-runner'], areas } };
  const state = { stored, areaInfo: AREA_INFO,
                  activeAreas: AREA_INFO.filter((a) => a.active).map((a) => a.tag),
                  resolved: {}, rules: {}, ...(extra || {}) };
  vm.runInContext('POLICY = ' + JSON.stringify(state)
    + '; PDRAFT = ' + JSON.stringify(extra && extra.draft ? extra.draft : stored)
    + '; PF.kind = "skills"; PF.cols = [];', ctx);
  return reach(ctx, ['pCols', 'pRuledAreas', 'pStatesRule', 'pToggleCol', 'PF',
                     'PDRAFT', 'policyChanges']);
}

const tags = (list) => list.map((a) => a.tag);

describe('a column is drawn for an area that carries a rule', () => {
  it('shows only those, and NAMES the rest as ruleless', () => {
    // web is live and has no rule; infra is dormant and has one. A predicate that
    // read `active` instead of "carries a rule" would answer [api, web].
    const { pCols } = panelWithAreas({ infra: { deny: ['db-*'] },
                                       api: { allow: ['code-*'] } });
    const got = pCols('skills');
    expect(tags(got.shown)).toEqual(['api', 'infra']);
    expect(tags(got.hidden)).toEqual(['web', 'docs']);
    expect(tags(got.ruleless)).toEqual(['web', 'docs']);
  });

  it('keeps the DORMANT one, which is the whole point of not using `active`', () => {
    const { pCols } = panelWithAreas({ docs: { deny: ['publish-*'] } });
    const got = pCols('skills');
    expect(tags(got.shown)).toEqual(['docs']);
    expect(got.shown[0].active).toBe(false);
    // ...and does not smuggle the live-but-ruleless ones in with it.
    expect(tags(got.hidden)).toEqual(['api', 'web', 'infra']);
  });

  it('preserves the server\'s order, so a column cannot move under a reader', () => {
    const { pCols } = panelWithAreas({ docs: { deny: ['x'] }, api: { deny: ['y'] } });
    expect(tags(pCols('skills').shown)).toEqual(['api', 'docs']);
  });

  it('draws none when no area states anything, and hides none when all do', () => {
    // Both ends, because a predicate stuck at one of them passes every case that
    // only ever asks about the middle.
    const none = panelWithAreas({}).pCols('skills');
    expect(tags(none.shown)).toEqual([]);
    expect(tags(none.hidden)).toEqual(['api', 'web', 'infra', 'docs']);
    const all = panelWithAreas(Object.fromEntries(
      AREA_INFO.map((a) => [a.tag, { deny: ['x-*'] }]))).pCols('skills');
    expect(tags(all.shown)).toEqual(['api', 'web', 'infra', 'docs']);
    expect(tags(all.hidden)).toEqual([]);
    expect(tags(all.ruleless)).toEqual([]);
  });

  it('is per KIND: a rule for subagents does not widen the skills table', () => {
    const { ctx } = loadPanel();
    const stored = { skills: {}, agents: { areas: { web: { deny: ['doc-writer'] } } } };
    vm.runInContext('POLICY = ' + JSON.stringify({ stored, areaInfo: AREA_INFO })
      + '; PDRAFT = ' + JSON.stringify(stored) + '; PF.cols = [];', ctx);
    const { pCols } = reach(ctx, ['pCols']);
    expect(tags(pCols('skills').shown)).toEqual([]);
    expect(tags(pCols('agents').shown)).toEqual(['web']);
  });
});

describe('what counts as stating a rule', () => {
  it('an empty list does not, matching what pPrune deletes', () => {
    const { pCols, pStatesRule } = panelWithAreas({ web: { deny: [] } });
    expect(pStatesRule({ deny: [] })).toBe(false);
    expect(tags(pCols('skills').shown)).toEqual([]);
  });

  it('a MALFORMED value does, so a column cannot hide a hand-edited config', () => {
    // `"deny": "nope"` is a shape a person can write and the server reports as a
    // finding. It names nothing, so the cells in its column read as no rule - but
    // the AREA is not empty, and a column that vanished on it would be hiding the
    // reader's own file behind a screen that says nothing is there.
    const { pCols, pStatesRule } = panelWithAreas({ web: { deny: 'nope' } });
    expect(pStatesRule({ deny: 'nope' })).toBe(true);
    expect(tags(pCols('skills').shown)).toEqual(['web']);
  });

  it('an areas value that is not an object answers rather than throwing', () => {
    // Same class as the four walkers that blanked the tab. A throw inside pCols
    // lands in renderPolicy, and no substring pin can see a dead tab.
    const { ctx } = loadPanel();
    vm.runInContext('POLICY = ' + JSON.stringify(
      { stored: { skills: { areas: 'nope' } }, areaInfo: AREA_INFO })
      + '; PDRAFT = ' + JSON.stringify({ skills: { areas: 'nope' } })
      + '; PF.cols = [];', ctx);
    const { pCols, pRuledAreas } = reach(ctx, ['pCols', 'pRuledAreas']);
    expect(() => pCols('skills')).not.toThrow();
    expect(pRuledAreas({ skills: { areas: 'nope' } }, 'skills')).toEqual([]);
    expect(tags(pCols('skills').shown)).toEqual([]);
  });
});

describe('the draft and the saved block are BOTH consulted', () => {
  it('a rule only in the draft draws its column, so a new one is visible at once', () => {
    const { pCols } = panelWithAreas({}, { draft: {
      skills: { areas: { web: { deny: ['db-*'] } } } } });
    expect(tags(pCols('skills').shown)).toEqual(['web']);
  });

  it('a rule only in the SAVED block keeps its column while it is being removed', () => {
    // The case for the union rather than the draft alone. Putting a cell back to
    // no-rule empties the area and pPrune deletes it, so a draft-only predicate
    // would take the column away in the same repaint that put the "unsaved" badge
    // inside it: the edit and the evidence of the edit would vanish together.
    const { pCols } = panelWithAreas({ web: { deny: ['db-migrations'] } },
                                     { draft: { skills: {} } });
    expect(tags(pCols('skills').shown)).toEqual(['web']);
    expect(tags(pCols('skills').hidden)).toEqual(['api', 'infra', 'docs']);
  });
});

describe('the reader can ask for a column, and that writes nothing', () => {
  it('a revealed area is shown and no longer hidden, and pressing again undoes it', () => {
    const { pCols, pToggleCol, PF } = panelWithAreas({ api: { deny: ['x'] } });
    expect(tags(pCols('skills').hidden)).toEqual(['web', 'infra', 'docs']);
    pToggleCol('infra');
    expect(tags(pCols('skills').shown)).toEqual(['api', 'infra']);
    expect(tags(pCols('skills').hidden)).toEqual(['web', 'docs']);
    // Still ruleless: it has a column because it was asked for, not because
    // anything was written. That distinction is what keeps the strip honest.
    expect(tags(pCols('skills').ruleless)).toEqual(['web', 'infra', 'docs']);
    expect(PF.cols).toEqual(['infra']);
    pToggleCol('infra');
    expect(tags(pCols('skills').shown)).toEqual(['api']);
    expect(PF.cols).toEqual([]);
  });

  it('revealing writes nothing - the pill decides the screen, pSetRule the file', () => {
    // The constraint that keeps "add a column" from becoming a second way to
    // write a rule. Compared as JSON, so a nested list the toggle reached into
    // would show up rather than being aliased past a reference check.
    const { pToggleCol, PDRAFT } = panelWithAreas({ api: { deny: ['db-*'] } });
    const before = JSON.stringify(PDRAFT);
    pToggleCol('web');
    pToggleCol('docs');
    pToggleCol('web');
    expect(JSON.stringify(PDRAFT)).toBe(before);
    // ...and the tab is therefore still clean: nothing to save, so no savebar
    // count and no beforeunload guard from having looked at a column.
    expect(before).toContain('db-*');
  });
});
