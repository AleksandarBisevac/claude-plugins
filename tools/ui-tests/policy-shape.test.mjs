// The capability policy against a MALFORMED list, which is a shape a person can
// put in `.claude/audit.config.json` by hand.
//
// `_policy.validate_policy` calls it a finding and `_panel_policy._policy_rules`
// guards it with `isinstance(patterns, list)`, so the server has always known this
// shape exists. The panel did not, in four places, and the panel is the surface
// that decides whether a skill may run at all.
//
// WHY A BROWSER-SIDE TEST AND NOT A PIN. Three of the four throw, and the throw
// lands inside `renderPolicy` — so the Policy tab renders nothing. A substring
// pin over the assembled page cannot see a dead tab; every `'…' in UI_HTML`
// assertion passes against a page whose script died. That is the panel's
// documented blind spot, and this is the shape of check that covers it.
//
// The fourth is worse than a throw. `pRuleOf` used to ask
// `(src[l]||[]).indexOf(name) >= 0`, and on a STRING `indexOf` is a substring
// search: `"nope".indexOf("op")` is 1, so it reported a rule of `deny` for a
// capability nothing had denied. A wrong answer, silently, in the security view.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

/**
 * Load the panel with a policy whose `deny` is a string rather than a list.
 * @param {unknown} deny what to put where a list belongs
 */
function panelWithPolicy(deny) {
  const { ctx } = loadPanel();
  const stored = { skills: { deny, allow: ['code-review'] } };
  vm.runInContext('POLICY = ' + JSON.stringify({ stored })
    + '; PDRAFT = ' + JSON.stringify(stored) + ';', ctx);
  return reach(ctx, ['pRuleOf', 'pDraftRules', 'pSetRule', 'pAddPattern']);
}

describe('a malformed policy list does not take the tab down', () => {
  it('pDraftRules answers rather than throwing [was: the tab went blank]', () => {
    const { pDraftRules } = panelWithPolicy('nope');
    expect(() => pDraftRules('skills')).not.toThrow();
    // And it still reports the list that IS well formed, rather than giving up on
    // the whole kind: a malformed `deny` must not hide a valid `allow`.
    const rows = pDraftRules('skills');
    expect(rows.map((r) => r.pattern)).toContain('code-review');
  });

  it('pSetRule and pAddPattern answer rather than throwing', () => {
    const { pSetRule, pAddPattern } = panelWithPolicy('nope');
    expect(() => pSetRule('skills', 'shell-runner', null, 'deny')).not.toThrow();
    expect(() => pAddPattern('skills', 'deny', null, 'code-*')).not.toThrow();
  });
});

describe('pRuleOf matches a NAME, not a substring', () => {
  it('a string where a list belongs reports no rule [was: reported deny]', () => {
    const { pRuleOf } = panelWithPolicy('nope');
    // "nope".indexOf("op") === 1, which is how this reported a rule that did not
    // exist. Nothing denied `op`, so the answer is the empty string.
    expect(pRuleOf({ skills: { deny: 'nope' } }, 'skills', 'op', null)).toBe('');
  });

  it('and a real list still matches exactly, which is the property the retired '
     + 'pin claimed to guarantee', () => {
    const { pRuleOf } = panelWithPolicy(['shell-runner']);
    const block = { skills: { deny: ['shell-runner'], allow: ['code-review'] } };
    expect(pRuleOf(block, 'skills', 'shell-runner', null)).toBe('deny');
    expect(pRuleOf(block, 'skills', 'code-review', null)).toBe('allow');
    // The exactness the old pin was written for: a name that is a PREFIX of a
    // stored entry is not a match, so pressing Default on one row cannot silently
    // drop a glob covering ten.
    expect(pRuleOf(block, 'skills', 'shell', null)).toBe('');
    expect(pRuleOf(block, 'skills', 'runner', null)).toBe('');
    expect(pRuleOf(block, 'skills', 'code', null)).toBe('');
  });

  it('an area scope with a malformed list behaves the same way', () => {
    const { pRuleOf } = panelWithPolicy('nope');
    const block = { skills: { areas: { api: { deny: 'nope' } } } };
    expect(pRuleOf(block, 'skills', 'op', 'api')).toBe('');
  });
});

describe('the well-formed case is untouched', () => {
  // The half that stops the guards from being satisfiable by refusing
  // everything: a fix that made every walker return empty would pass every case
  // above.
  it('a normal policy still round-trips through the walkers', () => {
    const { pDraftRules, pSetRule, pRuleOf } = panelWithPolicy(['shell-runner']);
    const rows = pDraftRules('skills');
    expect(rows.map((r) => r.pattern).sort()).toEqual(['code-review', 'shell-runner']);
    expect(rows.every((r) => r.list === 'deny' || r.list === 'allow')).toBe(true);
    // A switch moves the name out of deny and into allow, and nothing else moves.
    pSetRule('skills', 'shell-runner', null, 'allow');
    expect(pRuleOf({ skills: { deny: [], allow: ['shell-runner', 'code-review'] } },
                   'skills', 'shell-runner', null)).toBe('allow');
  });
});
