// The ADO panel levers, RUN rather than read.
//
// Each is the kind of rule that can be wrong without looking wrong. Which patch
// value an option stands for is four branches and one of them must deliberately
// write nothing; which literal a typed box produces is a decision about a board
// that requires a number; and whether a phase is on the board at all is a
// THREE-valued answer whose third value a truthiness test silently files under
// the second. A substring pin can say those functions exist and it cannot say
// what they answer, and the panel's own selftests are substring pins over the
// assembled page.
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
  typedNumber, atAnswer, atWords, atChoiceOf, atOptions, atPatchValue,
  AT_DEFAULT_SENTENCE, PHCELL_OPTION_CHARS, optionText } =
  reach(loadPanel().ctx, ['apUseFallback', 'apIsFallback', 'apChoiceOf',
    'apPatchValue', 'apOptions', 'apFallbackWords', 'apCandidateLabel',
    'adoFieldValue', 'adoFieldSet', 'adoFieldDrop', 'typedNumber',
    'atAnswer', 'atWords', 'atChoiceOf', 'atOptions', 'atPatchValue',
    'AT_DEFAULT_SENTENCE', 'PHCELL_OPTION_CHARS', 'optionText']);

// `state` is on the first candidate on purpose. `_candidate_row` has always
// returned it and the label used to drop it, so a fixture without one cannot
// tell the two versions of `apCandidateLabel` apart - it would print the same
// string either way and the case would be green against the bug.
const CACHE = {
  fallback: { id: 41, source: 'meta' },
  candidates: [
    { id: 55, type: 'Feature', title: 'Payments', state: 'Active',
      url: 'https://x/55' },
    { id: 56, type: null, title: null, state: null, url: null },
  ],
  fetchedAt: '2026-08-20T00:00:00Z',
  cache: 'items',
  basis: 'two cached candidates',
  refresh: '/audit:sync parents',
};
const EMPTY = { fallback: { id: null, source: 'none' }, candidates: [],
  fetchedAt: null, cache: 'absent', basis: 'nobody has asked',
  refresh: '/audit:sync parents' };

// --- adoParent: where ONE item hangs on the board --------------------------
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
     + 'link by the parent’s TYPE, so the type is in the label - and the board '
     + 'STATE is in it too, because hanging a phase under a closed Feature is '
     + 'the mistake nothing else on this screen would catch', () => {
    expect(apCandidateLabel(CACHE.candidates[0]))
      .toBe('#55 · Feature · Payments · state Active');
    expect(apCandidateLabel(CACHE.candidates[1]))
      .toBe('#56 · nothing recorded but the id');
  });

  it('LABELS the state rather than joining it in as a fourth fragment, so a '
     + 'title that ends in a word cannot be read as a state', () => {
    // `#77 · Epic · Payments · Closed` is the spelling this rejects: the last
    // two fragments are then indistinguishable to a reader.
    expect(apCandidateLabel({ id: 77, type: 'Epic', title: 'Payments',
      state: 'Closed' })).toBe('#77 · Epic · Payments · state Closed');
    expect(apCandidateLabel({ id: 77, type: 'Epic', title: 'Payments · Closed' }))
      .toBe('#77 · Epic · Payments · Closed');
  });

  it('says "nothing recorded but the id" only when that is TRUE - a cache '
     + 'carrying a state and nothing else is not nothing', () => {
    expect(apCandidateLabel({ id: 58, type: null, title: null, state: 'New' }))
      .toBe('#58 · state New');
    expect(apCandidateLabel({ id: 59 })).toBe('#59 · nothing recorded but the id');
  });

  it('keeps the state OUT of what a pick writes: it is a live board attribute '
     + 'read at fetch time, and a declaration recording one would be a fact '
     + 'about the board frozen into the manifest', () => {
    expect(apPatchValue('55', CACHE, '').value).toEqual({
      id: 55, source: 'declared', type: 'Feature', title: 'Payments',
      url: 'https://x/55', observedAt: '2026-08-20T00:00:00Z' });
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

// --- F211: the phase cell's controls clip what they cannot show ------------
// A closed <select> renders ONE line and clips it — no wrap, no ellipsis — so a
// label longer than the control is a phrase cut off mid-word. Every pin passed
// while `use the fallback — nothing is set (…)` painted as `use the fallback —`,
// because the literal WAS in the page and only the paint was wrong. A screenshot
// found it; these are the instruments that keep it found.
describe('what a phase-cell option is allowed to show', () => {
  const CACHE = {
    fallback: { id: 103205, source: 'meta' },
    candidates: [
      { id: 77, type: 'Epic', title: 'Payments', state: 'Active' },
      { id: 78, type: 'Feature',
        title: 'A programme name nobody on this team would ever call short',
        state: 'Closed' },
    ],
    fetchedAt: '2026-08-26T00:00:00Z', cache: 'fresh', basis: 'a fetch',
    refresh: '/audit:sync parents',
  };

  it('leads the parent options with what DECIDES, so a cut loses the tail and '
     + 'never the id', () => {
    const labels = Object.fromEntries(apOptions(CACHE));
    // the id survives the budget on both the fallback and a candidate
    expect(labels.fallback.slice(0, PHCELL_OPTION_CHARS)).toContain('103205');
    expect(labels['77'].slice(0, PHCELL_OPTION_CHARS)).toContain('#77');
    expect(labels['77'].slice(0, PHCELL_OPTION_CHARS)).toContain('Epic');
  });

  it('bounds what a parent option SHOWS and keeps the whole label where it can '
     + 'be read, so a long board title is truncated rather than lost', () => {
    for (const [value, label] of apOptions(CACHE)) {
      const { text, title } = optionText(label, PHCELL_OPTION_CHARS);
      expect(text.length, `option ${value} shows "${text}"`)
        .toBeLessThanOrEqual(PHCELL_OPTION_CHARS);
      if (title !== null) expect(title).toBe(label);
    }
    // the candidate whose board title runs long is the one that must be cut
    const long = Object.fromEntries(apOptions(CACHE))['78'];
    const cut = optionText(long, PHCELL_OPTION_CHARS);
    expect(cut.text.endsWith('…')).toBe(true);
    expect(cut.title).toContain('nobody on this team');
  });

  it('and an option that already FITS is left alone - no ellipsis, no title, '
     + 'so the marker means something when it appears', () => {
    expect(optionText('short', PHCELL_OPTION_CHARS))
      .toEqual({ text: 'short', title: null });
  });

  it('with NO bound passed, nothing is truncated - the wide selects elsewhere '
     + 'in the panel must not inherit a narrow cell\'s budget', () => {
    const long = 'a label far longer than any phase cell would ever allow';
    expect(optionText(long)).toEqual({ text: long, title: null });
  });

  // That BOTH phase-cell selects are actually filled through the bound is a
  // property of the assembled page's TEXT, not of a function's behaviour, so it
  // is pinned in `plugins/audit/tests/test__panel_page.py` (case at13) where the
  // other text pins live. Asserting it here would mean re-reading the source in
  // a suite whose whole point is running the code instead.
});

// --- meta.ado.fields: what THIS project supplies to a governed board -------
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

// --- adoTracked: whether it belongs on the board AT ALL --------------------
// The third ADO lever, and the one whose answer is THREE-VALUED. A substring pin
// can say `atAnswer` tests `=== null`; only running it can say what the cell
// reads for a phase nothing could answer about — which is the single reading
// this whole key exists to stop being "not on the board".
describe('the three-valued answer', () => {
  it('reads the three by IDENTITY, so null is its own answer and not a falsy '
     + '"untracked"', () => {
    expect(atAnswer({ tracked: true })).toBe('tracked');
    expect(atAnswer({ tracked: false })).toBe('untracked');
    expect(atAnswer({ tracked: null })).toBe('unanswered');
  });

  it('reports anything outside the three rather than borrowing the commonest '
     + 'one’s word', () => {
    // A missing block is a defect, not an old server: the payload comes from
    // the process serving the page. Each of these would read as "tracked"
    // under a `!!` and as "untracked" under a `=== false` with an else.
    expect(atAnswer(undefined)).toBe('not-reported');
    expect(atAnswer({})).toBe('not-reported');
    expect(atAnswer({ tracked: 'true' })).toBe('not-reported');
    expect(atAnswer({ tracked: 1 })).toBe('not-reported');
  });
});

describe('the line under the control', () => {
  it('says WHAT THE ANSWER CAME FROM: absent and true are one answer from two '
     + 'places', () => {
    // The pair that tells the two versions apart. A line printing only the
    // answer gives the same string for both of these, and the first is nobody
    // having looked while the second is a decision somebody wrote down.
    expect(atWords({ tracked: true }, null)).toBe(
      'tracking: on the board — the default');
    expect(atWords({ tracked: true }, true)).toBe(
      'tracking: on the board — declared');
  });

  it('gives every answer words of its own', () => {
    const said = [atWords({ tracked: true }, null),
      atWords({ tracked: true }, true),
      atWords({ tracked: false }, false),
      atWords({ tracked: null }, 'yes'),
      atWords(undefined, undefined)];
    expect(new Set(said).size).toBe(said.length);
    expect(said[2]).toBe('tracking: off the board — declared');
    expect(said[3]).toContain('not answered');
  });

  it('qualifies, and never decides: a declaration the answer disagrees with '
     + 'cannot flip the answer', () => {
    // `decl` is only ever read for the "declared / the default" half. If it
    // ever reached the answer, this unreadable declaration would drag the
    // sentence away from what `_ado_tracked.resolve` said.
    expect(atWords({ tracked: false }, 'nonsense')).toBe(
      'tracking: off the board — the default');
  });
});

describe('the declaration a stored value selects', () => {
  it('maps the three states, and reads absent from BOTH spellings', () => {
    expect(atChoiceOf(true)).toBe('true');
    expect(atChoiceOf(false)).toBe('false');
    expect(atChoiceOf(null)).toBe('default');
    // `undefined` is what a row from a build that did not send the key would
    // carry, and it means the same absence.
    expect(atChoiceOf(undefined)).toBe('default');
  });

  it('lands an unreadable value on an option of its OWN, never on the '
     + 'default’s', () => {
    // 1 is truthy and 0 is falsy; both are typos, and either read as a
    // declaration would be the panel answering about a board on its own.
    expect(atChoiceOf(1)).toBe('unreadable');
    expect(atChoiceOf(0)).toBe('unreadable');
    expect(atChoiceOf('false')).toBe('unreadable');
    expect(atChoiceOf({})).toBe('unreadable');
  });
});

describe('the option list', () => {
  it('is the same fixed three for every readable row - nothing here is '
     + 'cached, so no state can take an answer away', () => {
    const values = d => atOptions(d).map(o => o[0]);
    expect(values(null)).toEqual(['default', 'true', 'false']);
    expect(values(true)).toEqual(['default', 'true', 'false']);
    expect(values(false)).toEqual(['default', 'true', 'false']);
  });

  it('adds the unreadable option ONLY for the row that is in it, and first so '
     + 'the menu opens on what is actually stored', () => {
    expect(atOptions('yes').map(o => o[0]))
      .toEqual(['unreadable', 'default', 'true', 'false']);
    expect(atOptions('yes')[0][1]).toContain('unreadable');
  });

  it('names what each choice IS, in words that survive a 9rem select', () => {
    const labels = Object.fromEntries(atOptions(null));
    expect(labels.default).toBe('no declaration');
    expect(labels.true).toBe('on the board');
    expect(labels.false).toBe('off the board');
  });

  // THE CASE A SCREENSHOT BOUGHT. Every label used to say what the choice DOES
  // — 'no declaration — tracked, the default' — and the control is 9rem wide, so
  // the closed select rendered `no declaration — t`, clipped mid-word into
  // something that tells the reader nothing. No substring pin could see it: the
  // literal was present in the page and the assertion passed. A width budget is
  // the property that was actually violated, so it is the property under test.
  //
  // The bound is characters and not pixels on purpose — a unit test has no
  // layout — and it is deliberately generous: it catches a label written as a
  // sentence, which is the mistake that happened, and stays quiet about one or
  // two characters of drift, which is the argument a pixel gate must settle.
  it('keeps every option inside the width the control actually has', () => {
    for (const decl of [null, true, false, 'yes']) {
      for (const [value, label] of atOptions(decl)) {
        expect(label.length,
          `option ${value} is ${label.length} chars: "${label}"`)
          .toBeLessThanOrEqual(PHCELL_OPTION_CHARS);
      }
    }
  });

  it('and the dialog gets the long form, BUILT from the short one so the two '
     + 'cannot disagree about which way an absent declaration goes', () => {
    const labels = Object.fromEntries(atOptions(null));
    expect(AT_DEFAULT_SENTENCE.startsWith(labels.default)).toBe(true);
    expect(AT_DEFAULT_SENTENCE).toContain('tracked, the default');
    // ...and it is the one that would NOT fit, which is why it is not the label.
    expect(AT_DEFAULT_SENTENCE.length).toBeGreaterThan(18);
  });
});

describe('the patch value a choice stands for', () => {
  it('sends null for "no declaration" - the clear, and the same value the row '
     + 'showed for it', () => {
    // `null` is the CLEAR here and a VALUE on the adoParent row. The pair is
    // asserted together so the difference reads as deliberate.
    expect(atPatchValue('default')).toEqual({ write: true, value: null, why: '' });
    expect(apPatchValue('none', CACHE, '')).toEqual(
      { write: true, value: null, why: '' });
  });

  it('sends the booleans as booleans, so `true` is stored rather than pruned '
     + 'as "the same as the default"', () => {
    expect(atPatchValue('true')).toEqual({ write: true, value: true, why: '' });
    expect(atPatchValue('false')).toEqual({ write: true, value: false, why: '' });
    // Not the strings the <select> option values are: a stored "true" is
    // exactly the unreadable declaration this control refuses to write.
    expect(atPatchValue('true').value).not.toBe('true');
  });

  it('writes NOTHING for the unreadable option and says why - an option that '
     + 'saved silently would report success for a change nobody made', () => {
    const out = atPatchValue('unreadable');
    expect(out.write).toBe(false);
    expect(out.value).toBe(undefined);
    expect(out.why).toContain('neither true nor false');
  });
});
