// Copying to the clipboard, and both of the ways it fails.
//
// The rule is the shared thing, not the line: over `file://` some browsers make
// `navigator.clipboard` THROW and others hand back a promise that REJECTS, and an
// implementation handling one of those is broken exactly where a report is most
// often opened — from disk, by somebody who cannot fix it. Two sites had it right
// and the registry left the row unextracted on the grounds that the part was thin
// and the fallback had to be injected. Both true; neither a reason.
//
// The FALLBACK stays the caller's, and this file checks that too: it must be
// reached on either failure, and it must not be reached on success.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

/**
 * Drive `copyText` against a clipboard that behaves in a chosen way.
 * @param {function(Object): {ctx: Object}} load which surface to load
 * @param {'ok'|'reject'|'throw'|'missing'} how the clipboard's behaviour
 */
async function attempt(load, how) {
  const { ctx } = load({});
  vm.runInContext(
    // Reassigned wholesale rather than patched: `navigator.clipboard` is read at
    // call time, so what matters is what is there when copyText runs.
    'navigator = ' + ({
      ok: '{clipboard:{writeText:function(){return Promise.resolve();}}}',
      reject: '{clipboard:{writeText:function(){return Promise.reject(new Error("no"));}}}',
      throw: '{clipboard:{writeText:function(){throw new Error("blocked");}}}',
      // The shape a browser presents when the API is absent entirely: reading
      // `.writeText` of undefined throws, which is the same path as `throw`.
      missing: '{}',
    })[how] + '; __out = [];', ctx);
  const { copyText } = reach(ctx, ['copyText']);
  copyText('some text',
    () => vm.runInContext('__out.push("copied");', ctx),
    () => vm.runInContext('__out.push("fallback");', ctx));
  // The rejection path resolves on a microtask, so both are drained before the
  // result is read - otherwise 'reject' would look like "neither happened".
  for (let i = 0; i < 8; i++) await Promise.resolve();
  return reach(ctx, ['__out']).__out;
}

for (const [surface, load] of [['the panel', loadPanel], ['the report', loadReport]]) {
  describe('copyText on ' + surface, () => {
    it('reports success once, and does NOT run the fallback', async () => {
      expect(await attempt(load, 'ok')).toEqual(['copied']);
    });

    it('falls back when the promise REJECTS', async () => {
      expect(await attempt(load, 'reject')).toEqual(['fallback']);
    });

    it('falls back when the call THROWS — the half an implementation written '
       + 'from memory tends to miss', async () => {
      expect(await attempt(load, 'throw')).toEqual(['fallback']);
    });

    it('and when there is no clipboard API at all', async () => {
      expect(await attempt(load, 'missing')).toEqual(['fallback']);
    });
  });
}

describe('the two surfaces share one implementation', () => {
  it('not two that happen to agree', () => {
    const panel = reach(loadPanel().ctx, ['copyText']);
    const report = reach(loadReport().ctx, ['copyText']);
    expect(String(panel.copyText)).toBe(String(report.copyText));
  });

  it('and each keeps its OWN fallback, which is why the part takes one', () => {
    // Source text is the right instrument here: what the fallbacks DO is a
    // textarea and a selection, neither of which the stub DOM can carry.
    const panelSrc = String(reach(loadPanel().ctx, ['ovCopy']).ovCopy);
    expect(panelSrc).toContain('copyText(text,done,manual)');
    expect(panelSrc).toContain('execCommand');       // the panel's remedy
    expect(panelSrc).not.toContain('selectRun');     // not the report's
  });
});
