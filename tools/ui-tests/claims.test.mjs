// Claims the panel makes about things it did not decide.
//
// This repo's rule is that every claim in output carries the basis that makes it
// true, and that when the basis is missing, THAT is the thing to say. The help
// drawer broke it in the most direct way available: the guide card printed
// "read-only:" as fixed text while `_help.guide_card` computed a `readOnly`
// verdict the JavaScript never read. An agent that gained an `Edit` tool would
// have stayed advertised as read-only, on the surface whose whole job is telling
// a reader what an agent may do — and nothing anywhere asserted the badge's text,
// which is why it survived.
//
// The badge is built with `el()`, whose sandbox stub does not aggregate text from
// appended children, so the assertion here is on the pure function that decides
// the wording. That it is actually CALLED with the payload's flag is pinned in
// `test__panel_page.py`, where source text is the right instrument.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const { hToolClaim } = reach(loadPanel().ctx, ['hToolClaim']);

describe('the guide card says only what the payload supports', () => {
  it('claims read-only when the server said so', () => {
    expect(hToolClaim(true)).toBe('read-only: ');
  });

  it('says NOT read-only when the server said so — a fact worth saying loudly '
     + 'on this surface', () => {
    expect(hToolClaim(false)).toBe('NOT read-only: ');
    // And it does not name an EFFECT the tool list cannot prove: a tool beyond
    // the read-only set might be Bash or WebFetch, so "writes" would be the same
    // mistake pointing the other way.
    expect(hToolClaim(false)).not.toMatch(/write/i);
  });

  it('makes NO claim when the payload did not declare one', () => {
    for (const absent of [undefined, null]) {
      expect(hToolClaim(absent)).toBe('tools: ');
      expect(hToolClaim(absent)).not.toMatch(/read-only/);
    }
  });

  it('and a truthy-but-not-true value is not taken as a yes', () => {
    // `readOnly` is a boolean from `sorted(tools) == READ_ONLY_TOOLS`. Anything
    // else arriving there is a payload change, and guessing its meaning is how a
    // claim outlives its basis in the first place.
    for (const odd of ['true', 1, {}, []]) {
      expect(hToolClaim(odd)).toBe('tools: ');
    }
  });
});
