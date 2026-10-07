// A manifest that EXISTS and will not parse is not the same absence as no
// manifest at all, and Overview, Plan & models and Proposals used to tell the
// reader the wrong one: all three branched on a missing rollup alone, so a
// parse failure read as "no plan yet. /audit:init writes one" - advice that is
// wrong for a file already on disk and broken. `planState()` is the one place
// that now tells the three states apart, and every view's empty-state branch
// reads it rather than re-deriving "no rollup" for itself.
//
// WHY BEHAVIOUR AND NOT A PIN. `test__panel_page.py` holds the structural half
// (no view branches on a missing rollup except through `planState`), which is a
// property of the SOURCE. This file is the other half: what the three states
// actually answer, and what a view with each of them actually tells the reader
// — captured through the DOM text nodes `el()` creates and through the
// `manifestFindingsBox` call each unreadable branch makes, since the sandbox's
// stub elements do not accumulate appended children (see sandbox.mjs's own
// note on what it cannot reach).
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * Run `fn` with `document.createTextNode` recording every string a part of the
 * page built with `el()` would turn into text, and with `manifestFindingsBox`
 * recording the arguments it was called with. Both are plain properties of the
 * sandbox's global object — `document` because it is never declared with
 * `const`/`let` in the loaded source, `manifestFindingsBox` because a
 * top-level `function` declaration attaches to the global object the same way
 * `var` does — so neither needs `vm.runInContext` to intercept.
 * @param {import('node:vm').Context} ctx
 * @param {() => void} fn
 * @returns {{texts: string[], findingsCalls: Array<[number, string[]]>}}
 */
function observe(ctx, fn) {
  const texts = [];
  const findingsCalls = [];
  const origCreateTextNode = ctx.document.createTextNode;
  const origFindingsBox = ctx.manifestFindingsBox;
  ctx.document.createTextNode = (t) => {
    texts.push(String(t));
    return origCreateTextNode(t);
  };
  ctx.manifestFindingsBox = (n, list) => {
    findingsCalls.push([n, list]);
    return origFindingsBox(n, list);
  };
  try {
    fn();
  } finally {
    ctx.document.createTextNode = origCreateTextNode;
    ctx.manifestFindingsBox = origFindingsBox;
  }
  return { texts, findingsCalls };
}

function setState(ctx, state) {
  vm.runInContext('STATE = ' + JSON.stringify(state) + ';', ctx);
}

describe('planState: the one fact every empty-state branch reads', () => {
  it('a manifest that does not exist at all: none', () => {
    const { planState } = reach(loadPanel().ctx, ['planState']);
    expect(planState(false, null)).toBe('none');
  });

  it('a manifest that EXISTS and did not produce a rollup: unreadable', () => {
    const { planState } = reach(loadPanel().ctx, ['planState']);
    expect(planState(true, null)).toBe('unreadable');
  });

  it('a rollup in hand: ready, regardless of manifestExists', () => {
    const { planState } = reach(loadPanel().ctx, ['planState']);
    const rollup = { valid: true, findings: 0, warnings: 0 };
    expect(planState(true, rollup)).toBe('ready');
    // A truthy rollup settles it even if the caller's manifestExists disagreed -
    // the rollup cannot exist without a readable file, so this direction is
    // defensive rather than a path the server would ever actually produce.
    expect(planState(false, rollup)).toBe('ready');
  });
});

describe('Overview: the unreadable notice names the findings, never /audit:init', () => {
  const findings = ['cannot parse manifest: Expecting property name enclosed in '
    + 'double quotes: line 4 column 3 (char 58)'];

  it('renders manifestFindingsBox with the server\'s own findings and says to '
     + 'fix the file or restore it, with no mention of /audit:init', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: true, rollup: null, manifestFindings: findings,
                    manifestPath: 'docs/audit/audit-plan.json' });
    const { renderOver } = reach(ctx, ['renderOver']);
    const { texts, findingsCalls } = observe(ctx, renderOver);

    expect(findingsCalls.length).toBe(1);
    expect(findingsCalls[0][0]).toBe(findings.length);
    expect(findingsCalls[0][1]).toEqual(findings);

    const joined = texts.join('\n');
    expect(joined).not.toContain('/audit:init');
    expect(joined).toContain('restore it from git');
    expect(joined).toContain('docs/audit/audit-plan.json');
  });

  it('a missing manifest keeps today\'s /audit:init sentence, and never calls '
     + 'manifestFindingsBox', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: false, rollup: null, manifestFindings: [],
                    manifestPath: 'docs/audit/audit-plan.json' });
    const { renderOver } = reach(ctx, ['renderOver']);
    const { texts, findingsCalls } = observe(ctx, renderOver);

    expect(findingsCalls.length).toBe(0);
    expect(texts.join('\n')).toContain('/audit:init');
  });
});

describe('Plan & models: the same two states, through the same helper', () => {
  const findings = ['manifest is not a JSON object (got list)'];

  it('unreadable: findings shown, /audit:init never named', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: true, rollup: null, manifestFindings: findings,
                    manifestPath: 'plan.json' });
    const { renderComp } = reach(ctx, ['renderComp']);
    const { texts, findingsCalls } = observe(ctx, renderComp);

    expect(findingsCalls.length).toBe(1);
    expect(findingsCalls[0][1]).toEqual(findings);
    const joined = texts.join('\n');
    expect(joined).not.toContain('/audit:init');
    expect(joined).toContain('restore it from git');
  });

  it('none: keeps "there is no plan. /audit:init writes one."', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: false, rollup: null, manifestFindings: [],
                    manifestPath: 'plan.json' });
    const { renderComp } = reach(ctx, ['renderComp']);
    const { texts, findingsCalls } = observe(ctx, renderComp);

    expect(findingsCalls.length).toBe(0);
    expect(texts.join('\n')).toContain('/audit:init');
  });
});

describe('Proposals: an existing, unreadable file is not "nowhere to park them"', () => {
  const findings = ['cannot parse manifest: unexpected EOF'];

  it('unreadable: the server\'s findings, and no /audit:init advice', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: true, rollup: null, manifestFindings: findings,
                    manifestPath: 'plan.json', proposals: [] });
    const { renderProposals } = reach(ctx, ['renderProposals']);
    const { texts, findingsCalls } = observe(ctx, renderProposals);

    expect(findingsCalls.length).toBe(1);
    expect(findingsCalls[0][1]).toEqual(findings);
    const joined = texts.join('\n');
    expect(joined).not.toContain('/audit:init');
    expect(joined).toContain('restore it from git');
  });

  it('none: keeps "No plan yet, so nothing can be parked. /audit:init ..."', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: false, rollup: null, manifestFindings: [],
                    manifestPath: 'plan.json', proposals: [] });
    const { renderProposals } = reach(ctx, ['renderProposals']);
    const { texts, findingsCalls } = observe(ctx, renderProposals);

    expect(findingsCalls.length).toBe(0);
    expect(texts.join('\n')).toContain('/audit:init');
  });

  it('ready, with none parked, still says "No parked proposals." - the third '
     + 'state this card must not confuse with either absence', () => {
    const { ctx } = loadPanel();
    setState(ctx, { manifestExists: true, rollup: { valid: true }, manifestFindings: [],
                    manifestPath: 'plan.json', proposals: [] });
    const { renderProposals } = reach(ctx, ['renderProposals']);
    const { texts, findingsCalls } = observe(ctx, renderProposals);

    expect(findingsCalls.length).toBe(0);
    // Unlike the other two states, "ready" is untouched by this change and still
    // names /audit:init here (it is how a declined proposal gets parked) - the
    // point of this case is only that it is NOT the unreadable branch: no
    // findings box, and the distinct "No parked proposals." sentence.
    expect(texts.join('\n')).toContain('No parked proposals.');
  });
});

describe('planUnreadableNote: the one sentence shared by every unreadable branch', () => {
  it('never names /audit:init, whatever the path', () => {
    const { planUnreadableNote } = reach(loadPanel().ctx, ['planUnreadableNote']);
    expect(planUnreadableNote('docs/audit/audit-plan.json')).not.toContain('/audit:init');
    expect(planUnreadableNote(null)).not.toContain('/audit:init');
  });

  it('says to fix the file or restore it from git, naming the path when it has one', () => {
    const { planUnreadableNote } = reach(loadPanel().ctx, ['planUnreadableNote']);
    expect(planUnreadableNote('docs/audit/audit-plan.json'))
      .toBe('fix docs/audit/audit-plan.json, or restore it from git.');
    expect(planUnreadableNote(null)).toBe('fix the manifest, or restore it from git.');
  });
});
