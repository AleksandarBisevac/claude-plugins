// The two ADO panel levers, RUN rather than read.
//
// Both are the kind of rule that can be wrong without looking wrong. Which
// patch value an option stands for is four branches and one of them must
// deliberately write nothing; which literal a typed box produces is a decision
// about a board that requires a number. A substring pin can say those functions
// exist and it cannot say what they answer, and the panel's own selftests are
// substring pins over the assembled page.
//
// The dot-shredding hazard is here for the same reason. `setPath`/`delPath`
// split on dots and an ADO reference name is full of them, so the source pin in
// test__panel_page.py says no dotted writer goes near the template. This says
// the direct-edit helpers really do keep the key whole - the thing that would
// actually break.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const { apUseFallback, apIsFallback, apChoiceOf, apPatchValue, apOptions,
  apFallbackWords, apCandidateLabel, adoFieldValue, adoFieldSet, adoFieldDrop,
  typedNumber } =
  reach(loadPanel().ctx, ['apUseFallback', 'apIsFallback', 'apChoiceOf',
    'apPatchValue', 'apOptions', 'apFallbackWords', 'apCandidateLabel',
    'adoFieldValue', 'adoFieldSet', 'adoFieldDrop', 'typedNumber']);

const CACHE = {
  fallback: { id: 41, source: 'meta' },
  candidates: [
    { id: 55, type: 'Feature', title: 'Payments', url: 'https://x/55' },
    { id: 56, type: null, title: null, url: null },
  ],
  fetchedAt: '2026-08-20T00:00:00Z',
  cache: 'items',
  basis: 'two cached candidates',
  refresh: '/audit:sync parents',
};
const EMPTY = { fallback: { id: null, source: 'none' }, candidates: [],
  fetchedAt: null, cache: 'absent', basis: 'nobody has asked',
  refresh: '/audit:sync parents' };

describe('the no-declaration marker', () => {
  it('is a fresh object each call, so one row cannot edit the next row’s', () => {
    const a = apUseFallback();
    a.id = 41;
    expect(apUseFallback()).toEqual({ useFallback: true });
  });

  it('is recognised strictly, in both directions', () => {
    expect(apIsFallback(apUseFallback())).toBe(true);
    // 1 is truthy and is not `true`: a loose read would accept a document that
    // says something else.
    expect(apIsFallback({ useFallback: 1 })).toBe(false);
    // A marker carrying anything else is a declaration somebody wrote.
    expect(apIsFallback({ useFallback: true, id: 41 })).toBe(false);
    expect(apIsFallback(null)).toBe(false);
    expect(apIsFallback({ id: 41 })).toBe(false);
    expect(apIsFallback([])).toBe(false);
  });
});

describe('which option a stored declaration selects', () => {
  it('reads the three stored states as three different choices', () => {
    expect(apChoiceOf(apUseFallback(), CACHE.candidates)).toBe('fallback');
    expect(apChoiceOf(null, CACHE.candidates)).toBe('none');
    expect(apChoiceOf({ id: 55 }, CACHE.candidates)).toBe('55');
  });

  it('degrades an UNCACHED id to "other" rather than to the fallback [the '
     + 'reading that would silently re-parent a phase]', () => {
    expect(apChoiceOf({ id: 999 }, CACHE.candidates)).toBe('other');
    expect(apChoiceOf({ id: 55 }, [])).toBe('other');
  });

  it('sends an unusable declaration to "other" too, so the id stays visible '
     + 'instead of the row reading as one of the clean answers', () => {
    expect(apChoiceOf({ id: '55' }, CACHE.candidates)).toBe('other');
    expect(apChoiceOf({ type: 'Feature' }, CACHE.candidates)).toBe('other');
  });
});

describe('the patch value an option stands for', () => {
  it('writes the marker for the fallback and null for the declared nowhere '
     + '- and those are opposite answers, not two spellings of one', () => {
    expect(apPatchValue('fallback', CACHE, '')).toEqual(
      { write: true, value: { useFallback: true }, why: '' });
    expect(apPatchValue('none', CACHE, '')).toEqual(
      { write: true, value: null, why: '' });
  });

  it('carries the cache’s basis AND its moment when a candidate is picked',
    () => {
      expect(apPatchValue('55', CACHE, '').value).toEqual({
        id: 55, source: 'declared', type: 'Feature', title: 'Payments',
        url: 'https://x/55', observedAt: '2026-08-20T00:00:00Z' });
    });

  it('omits a basis field the cache never recorded, rather than writing null '
     + 'into it - an absent basis is the thing to say', () => {
    expect(apPatchValue('56', CACHE, '').value).toEqual({
      id: 56, source: 'declared', observedAt: '2026-08-20T00:00:00Z' });
  });

  it('stamps NO observedAt on a typed id, because nobody looked at it', () => {
    expect(apPatchValue('other', CACHE, '77').value).toEqual(
      { id: 77, source: 'declared' });
    expect(apPatchValue('other', EMPTY, '77').value).toEqual(
      { id: 77, source: 'declared' });
  });

  it('DECLINES with a reason instead of writing nothing quietly', () => {
    // '4e2', '0x10' and ' 41 ' are the ones a bare Number() accepts: it would
    // have hung the phase under 400, 16 and 41 respectively, and only the last
    // of those is even arguably what was meant.
    for (const typed of ['', '   ', '0', '-3', 'abc', '1.5', '4e2', '0x10',
      '+41', '41.0']) {
      const out = apPatchValue('other', CACHE, typed);
      expect(out.write, 'typed ' + JSON.stringify(typed)).toBe(false);
      expect(out.why).toContain('positive whole number');
    }
  });

  it('declines a candidate the cache no longer carries, naming the refresh '
     + '- the alternative is inventing a parent out of an option value', () => {
    const out = apPatchValue('999', CACHE, '');
    expect(out.write).toBe(false);
    expect(out.why).toContain('/audit:sync parents');
  });
});

describe('the option list', () => {
  it('always offers the three answers, cache or no cache', () => {
    const vals = (c) => apOptions(c).map((o) => o[0]);
    expect(vals(EMPTY)).toEqual(['fallback', 'none', 'other']);
    expect(vals(CACHE)).toEqual(['fallback', '55', '56', 'none', 'other']);
  });

  it('names what the fallback resolves to, and says so when nothing is set',
    () => {
      expect(apFallbackWords({ id: 41 })).toBe('#41');
      expect(apFallbackWords({ id: null })).toContain('nothing is set');
      expect(apOptions(CACHE)[0][1]).toContain('#41');
    });

  it('never shows a bare number for a candidate: the hierarchy check grades a '
     + 'link by the parent’s TYPE, so the type is in the label', () => {
    expect(apCandidateLabel(CACHE.candidates[0])).toBe('#55 · Feature · Payments');
    expect(apCandidateLabel(CACHE.candidates[1]))
      .toBe('#56 · nothing recorded but the id');
  });
});

describe('one round-trip rule, two boxes', () => {
  it('is the SAME function, so the two cannot disagree about 4e2', () => {
    expect(typedNumber('4e2')).toBe(null);
    expect(typedNumber('0x10')).toBe(null);
    expect(typedNumber(' 41 ')).toBe(41);
    expect(typedNumber('')).toBe(null);
    // The parent box refuses what the rule refuses...
    expect(apPatchValue('other', CACHE, '4e2').write).toBe(false);
    // ...and the template box keeps it as the text it is, rather than as 400.
    expect(adoFieldValue('4e2')).toBe('4e2');
  });

  it('tells "not a number" apart from 0 and from NaN, which are values', () => {
    expect(typedNumber('0')).toBe(0);
    expect(typedNumber('NaN')).toBe(null);
    expect(typedNumber('nonsense')).toBe(null);
  });
});

describe('the per-type field template', () => {
  it('keeps a dotted ADO reference name as ONE key [the setPath shredder]',
    () => {
      const f = {};
      adoFieldSet(f, 'Task', 'Microsoft.VSTS.Common.Activity', 'Development');
      expect(f).toEqual(
        { Task: { 'Microsoft.VSTS.Common.Activity': 'Development' } });
      // The shape a dotted writer would have produced, spelled out so this
      // cannot pass by asserting something weaker.
      expect(f.Task.Microsoft).toBeUndefined();
      expect(Object.keys(f.Task)).toEqual(['Microsoft.VSTS.Common.Activity']);
    });

  it('removes one field and PRUNES a type left with none - an empty template '
     + 'is a validator warning about the removal itself', () => {
    const f = { Task: { 'Microsoft.VSTS.Common.Activity': 'Development',
      'Microsoft.VSTS.Scheduling.OriginalEstimate': 4 }, Bug: { Severity: '2' } };
    adoFieldDrop(f, 'Task', 'Microsoft.VSTS.Common.Activity');
    expect(f.Task).toEqual({ 'Microsoft.VSTS.Scheduling.OriginalEstimate': 4 });
    adoFieldDrop(f, 'Task', 'Microsoft.VSTS.Scheduling.OriginalEstimate');
    expect(f.Task).toBeUndefined();
    expect(f.Bug).toEqual({ Severity: '2' });
  });

  it('drops nothing and throws nothing for a type or field that is not there',
    () => {
      const f = { Task: { Activity: 'Development' } };
      expect(() => adoFieldDrop(f, 'Bug', 'Severity')).not.toThrow();
      expect(() => adoFieldDrop(f, 'Task', 'Nope')).not.toThrow();
      expect(f).toEqual({ Task: { Activity: 'Development' } });
    });

  it('types a value by ROUND TRIP, so an estimate is a number and a version '
     + 'string is not', () => {
    expect(adoFieldValue('4')).toBe(4);
    expect(adoFieldValue('0')).toBe(0);
    expect(adoFieldValue('-2.5')).toBe(-2.5);
    expect(adoFieldValue('true')).toBe(true);
    expect(adoFieldValue('false')).toBe(false);
    expect(adoFieldValue('Development')).toBe('Development');
  });

  it('leaves every spelling Number() is more generous than a person as the '
     + 'string it plainly is', () => {
    // Each of these would store a value nobody typed under a bare Number().
    expect(adoFieldValue('0x10')).toBe('0x10');
    expect(adoFieldValue('1e3')).toBe('1e3');
    expect(adoFieldValue('007')).toBe('007');
    expect(adoFieldValue('1.0.0')).toBe('1.0.0');
    expect(adoFieldValue('')).toBe('');
    expect(adoFieldValue('Infinity')).toBe('Infinity');
    expect(adoFieldValue('NaN')).toBe('NaN');
  });
});
