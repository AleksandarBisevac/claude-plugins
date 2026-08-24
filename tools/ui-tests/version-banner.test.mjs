// The staleness banner's three answers, RUN rather than read.
//
// This is the JavaScript half of F100, and the whole fault it repairs is a
// distinction between two ways of not warning: a comparison that was made and
// came out equal, and a comparison that never happened because one half of it was
// missing. Both paint nothing, so a substring pin over the assembled page cannot
// tell them apart — it can only say the words exist somewhere in the source. The
// endpoint reports three states precisely so this surface can keep them three,
// and only calling the function proves it does.
//
// The value is deliberately probed in both directions: the mutation that never
// warns and the mutation that always warns are two different bugs, and the second
// is the one a suite written only against `stale:true` cannot see.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const { vbBanner, vbWords } = reach(loadPanel().ctx, ['vbBanner', 'vbWords']);

const STALE = { assembled: '1.3.0', installed: '1.4.0', stale: true };

describe('when the banner paints', () => {
  it('paints for a comparison that was made and DISAGREED, and nothing else '
     + 'reaches that branch', () => {
    expect(vbBanner(STALE)).not.toBe(null);
    expect(vbBanner(STALE).getAttribute('data-buildstale')).toBe('1');
    expect(vbBanner(STALE).className).toBe('buildstale');
  });

  it('paints NOTHING for a comparison that agreed - there is nothing to '
     + 'interrupt anybody about', () => {
    expect(vbBanner({ assembled: '1.4.0', installed: '1.4.0', stale: false }))
      .toBe(null);
  });

  it('paints nothing for NO BASIS either, and that is the distinction the '
     + 'endpoint exists to keep: `null` is one half of the comparison missing, '
     + 'so answering it with "up to date" would invent the reassurance', () => {
    expect(vbBanner({ assembled: null, installed: '1.4.0', stale: null }))
      .toBe(null);
    expect(vbBanner({ assembled: '1.4.0', installed: null, stale: null }))
      .toBe(null);
    expect(vbBanner({ assembled: null, installed: null, stale: null })).toBe(null);
  });

  it('reads `stale` STRICTLY, so no payload this page did not understand can '
     + 'put a banner up [the always-warns mutation, which a suite written only '
     + 'against `true` cannot see]', () => {
    // Every one of these is truthy or absent, and a `if (state.stale)` would
    // warn on the first four and throw on the last two.
    for (const stale of ['true', 1, 'no', {}]) {
      expect(vbBanner({ assembled: 'a', installed: 'b', stale }),
        'stale ' + JSON.stringify(stale)).toBe(null);
    }
    expect(vbBanner({ assembled: 'a', installed: 'b' })).toBe(null);
    expect(vbBanner(null)).toBe(null);
    expect(vbBanner(undefined)).toBe(null);
  });
});

describe('what the banner says', () => {
  it('names BOTH builds, because "you are on an old build" is a claim and '
     + 'these two strings are the basis for it', () => {
    const words = vbWords(STALE);
    expect(words).toContain('1.3.0');
    expect(words).toContain('1.4.0');
    // The order is the claim's direction: the page came from the first and the
    // installed build is the second. Reversed, the sentence tells the reader to
    // relaunch INTO the build they are already running.
    expect(words.indexOf('1.3.0')).toBeLessThan(words.indexOf('1.4.0'));
  });

  it('asks for the repair that works, and not for the one that does not - the '
     + 'page is assembled once at startup, so a reload serves the same bytes',
    () => {
      expect(vbWords(STALE)).toContain('stop the panel and start it again');
      expect(vbWords(STALE)).toContain('A reload will not');
    });
});
