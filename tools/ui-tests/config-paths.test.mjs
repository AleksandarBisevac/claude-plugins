// The three dotted-path accessors the Settings form writes config through —
// `getPath`, `setPath`, `delPath` in `ui/panel/settings.js`. They are reached
// out of the loaded panel rather than retyped here, so a case cannot pass
// against a copy of the code that no longer ships.
//
// WHY THIS SUITE EXISTS. `delPath` used to throw on a null intermediate while
// its two siblings tolerated one. `typeof null === 'object'`, so the object
// test passed, the walk stepped onto `null`, and `delete` on it raised
// `TypeError: Cannot convert undefined or null to object` — inside an `oninput`
// handler, where nothing catches it and nothing reports it. The visible effect
// is not an error message: it is an edit the panel silently did not record.
//
// Reachable from a hand-written `"usage": null` in `.claude/audit.config.json`,
// then clearing any box under it or toggling a checkbox back to its default.
// The three accessors have to agree about a broken shape, because the form calls
// them against the same document.
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';

const accessors = () => reach(loadPanel().ctx, ['getPath', 'setPath', 'delPath']);

describe('dotted config paths: the three accessors agree about a broken shape', () => {
  it('all three tolerate a NULL intermediate [was DEFECT: delPath threw]', () => {
    const { getPath, setPath, delPath } = accessors();
    // Read: answers undefined rather than throwing.
    expect(getPath({ usage: null }, 'usage.showCost')).toBe(undefined);
    // Delete: a no-op that leaves the document exactly as it was. This is the
    // regression — `toEqual` would pass on a partly-mutated object, so the
    // whole document is compared.
    const doc = { usage: null, other: { keep: 1 } };
    expect(() => delPath(doc, 'usage.showCost')).not.toThrow();
    expect(doc).toEqual({ usage: null, other: { keep: 1 } });
    // Write: setPath already guarded this explicitly, which is what made
    // delPath's silence a disagreement rather than a shared limitation.
    const w = { usage: null };
    setPath(w, 'usage.showCost', true);
    expect(w.usage.showCost).toBe(true);
  });

  it('all three tolerate a MISSING intermediate', () => {
    const { getPath, setPath, delPath } = accessors();
    expect(getPath({}, 'usage.showCost')).toBe(undefined);
    const doc = { other: 1 };
    expect(() => delPath(doc, 'usage.showCost')).not.toThrow();
    expect(doc).toEqual({ other: 1 });
    const w = {};
    setPath(w, 'a.b.c', 7);
    expect(w).toEqual({ a: { b: { c: 7 } } });
  });

  it('all three tolerate a SCALAR intermediate', () => {
    const { getPath, delPath } = accessors();
    // A string is not an object, so the walk must stop rather than index into it.
    expect(getPath({ usage: 'yes' }, 'usage.showCost')).toBe(undefined);
    const doc = { usage: 'yes' };
    expect(() => delPath(doc, 'usage.showCost')).not.toThrow();
    expect(doc).toEqual({ usage: 'yes' });
  });

  // The half that stops the guard from being satisfiable by refusing everything:
  // a fix that turned delPath into an unconditional no-op would pass every case
  // above. These are the cases it fails.
  it('delPath still actually deletes, at depth and at the top level', () => {
    const { delPath } = accessors();
    const deep = { usage: { showCost: true, keep: 1 }, other: 2 };
    delPath(deep, 'usage.showCost');
    expect(deep).toEqual({ usage: { keep: 1 }, other: 2 });
    const top = { showCost: true, keep: 1 };
    delPath(top, 'showCost');
    expect(top).toEqual({ keep: 1 });
  });

  it('the null guard is what makes the tolerant case pass, not the object test', () => {
    // Mutation proof, and it has to remove the GUARD rather than the whole
    // condition: dropping `typeof cur[k] !== 'object'` too would make the scalar
    // case throw as well, and then this test would be proving the wrong branch.
    const { ctx } = loadPanel({
      mutate: (src) => {
        const target = "||cur[k]===null)return;cur=cur[k];}";
        if (!src.includes(target)) {
          throw new Error('the null guard is no longer spelled as expected, so this '
            + 'mutation proof would silently test nothing: ' + target);
        }
        return src.replace(target, ')return;cur=cur[k];}');
      },
    });
    const { delPath } = reach(ctx, ['delPath']);
    expect(() => delPath({ usage: null }, 'usage.showCost')).toThrow(/null|undefined/);
  });
});
