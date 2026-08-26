// A lookup table read with a key that came from outside the code.
//
// `LABELS[v]` walks the prototype chain, so a manifest, a config file or a URL
// fragment carrying `constructor`, `toString`, `valueOf`, `hasOwnProperty` or
// `__proto__` got Object.prototype's member back instead of a miss — and the
// `||` fallback written beside the read was unreachable for exactly those keys.
// `label()`, documented `@returns {string}`, returned a FUNCTION.
//
// The source pins in plugins/audit/tests/ could not see this and never will:
// they read the text of the page, and the text was always right. The bug is in
// what the text DOES, which is what this file runs.
//
// The keys are reachable rather than theoretical. `testEvidence.status` is
// enum-constrained in the JSON Schema and restated nowhere in `_manifest_vocab`,
// so `validate-manifest.py` accepts whatever a hand-written or third-party
// manifest puts there; `area` tags and `model` names are plain strings in the
// schema; `review.status` documents itself as free text; and the usage tab
// decodes its filter dimensions straight out of `location.hash`.

import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, panelParts, pyCall, readPart, reach } from './sandbox.mjs';

// The REAL table, fetched from the module the server substitutes it from. A
// stubbed `{}` would make every "a real label still resolves" case vacuous — it
// would be asserting the fallback under another name.
const [LABELS] = pyCall('_ui_theme', [['LABELS', []]]);

const panel = () => loadPanel({ placeholders: { __LABELS__: JSON.stringify(LABELS) } });

// Every name a plain object inherits that is also a plausible value in a
// manifest, a config file or a fragment. `__proto__` is the odd one: it is an
// accessor rather than a method, so the unguarded read answered with an OBJECT
// while the other four answered with a function.
const INHERITED = ['constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__'];

describe('lookup() reads a table as own properties only', () => {
  const { ctx } = panel();
  const { lookup } = reach(ctx, ['lookup']);
  const table = { done: 'Done', zero: 0, blank: '' };

  it('a key naming an inherited member is a MISS, not that member', () => {
    INHERITED.forEach((k) => {
      expect(lookup(table, k), k).toBeUndefined();
    });
  });

  it('and the bare read it replaces really did answer with one', () => {
    // The control. Without this the case above passes just as well against a
    // table that happens to be empty, and proves nothing about the chain.
    INHERITED.forEach((k) => {
      expect(table[k], k).toBeDefined();
    });
    expect(typeof table.constructor).toBe('function');
    expect(typeof table.__proto__).toBe('object');
  });

  it('an own key answers with its exact value', () => {
    expect(lookup(table, 'done')).toBe('Done');
  });

  it('a FALSY own value is returned, not swallowed', () => {
    // `||` is the caller's decision and several callers depend on it. A helper
    // that folded 0 or '' into undefined would move that decision here.
    expect(lookup(table, 'zero')).toBe(0);
    expect(lookup(table, 'blank')).toBe('');
  });

  it('a key that is absent, null or undefined is a miss', () => {
    expect(lookup(table, 'nothing')).toBeUndefined();
    expect(lookup(table, null)).toBeUndefined();
    expect(lookup(table, undefined)).toBeUndefined();
  });
});

describe('label() answers with words for every key', () => {
  const { ctx } = panel();
  const { label } = reach(ctx, ['label']);

  it('an inherited name is humanised, exactly as any other unknown value is', () => {
    // The literal text, not `typeof x === 'string'` — which the fallback branch
    // satisfies whatever it returns, including the wrong thing.
    expect(label('constructor')).toBe('Constructor');
    expect(label('toString')).toBe('ToString');
    expect(label('valueOf')).toBe('ValueOf');
    expect(label('hasOwnProperty')).toBe('HasOwnProperty');
    // `__proto__` humanises to a space-wrapped word: the separator run at each
    // end collapses to one space and `^.` then upper-cases a space. That is what
    // the shipped humaniser does to any value with leading separators, and this
    // change does not touch it — it only stops the value reaching Object.prototype
    // first. Pinned as the text it is rather than tidied here, so a future fix to
    // the humaniser is a deliberate edit to this line.
    expect(label('__proto__')).toBe(' proto ');
  });

  it('and none of those is a function any more', () => {
    INHERITED.forEach((k) => {
      expect(typeof label(k), k).toBe('string');
    });
  });

  it('agrees with _ui_theme.label for the names that share its rule', () => {
    // Python reads a dict, so it never had this bug; it is the oracle for what
    // the humanised word should be. `__proto__` is excluded because Python
    // `.strip()`s and the JavaScript does not — a pre-existing difference in the
    // humaniser, not something this change introduced.
    const names = INHERITED.filter((k) => k !== '__proto__');
    const want = pyCall('_ui_theme', names.map((k) => ['label', [k]]));
    names.forEach((k, i) => {
      expect(label(k), k).toBe(want[i]);
    });
  });

  it('every real label still resolves to the table\'s own word', () => {
    const keys = Object.keys(LABELS);
    expect(keys.length).toBeGreaterThan(0);
    // Guards the loop against being vacuous: a falsy value would take the
    // fallback branch and the comparison below would be about the humaniser.
    expect(keys.filter((k) => !LABELS[k])).toEqual([]);
    keys.forEach((k) => {
      expect(label(k), k).toBe(LABELS[k]);
    });
  });

  it('and the two that everything renders read as they always did', () => {
    expect(label('done')).toBe('Done');
    expect(label('in_progress')).toBe('In progress');
  });

  it('the keys where the TABLE and the humaniser disagree still take the table', () => {
    // The loop above is nearly vacuous on its own: most of the shipped table
    // humanises to the word it maps to, so a `lookup` that answered "miss" for
    // everything would pass it. These are the keys that tell the two apart, and
    // the list is derived rather than typed, so a table edit cannot leave this
    // asserting nothing without saying so.
    const humanise = (v) => {
      const p = v.replace(/[_-]+/g, ' ');
      return p ? p[0].toUpperCase() + p.slice(1) : v;
    };
    const telling = Object.keys(LABELS).filter((k) => humanise(k) !== LABELS[k]);
    expect(telling.length).toBeGreaterThan(0);
    telling.forEach((k) => {
      expect(label(k), k).toBe(LABELS[k]);
      expect(label(k), k).not.toBe(humanise(k));
    });
  });

  it('an ordinary unknown word is still humanised', () => {
    expect(label('needs_triage')).toBe('Needs triage');
    expect(label('some-new-state')).toBe('Some new state');
    expect(label('wontfix_later')).toBe('Wontfix later');
  });

  it('and nothing at all is still the em dash', () => {
    expect(label('')).toBe('—');
    expect(label(null)).toBe('—');
    expect(label(undefined)).toBe('—');
  });
});

describe('uCol/uMCol hand back a token, never a stringified function', () => {
  const { ctx } = panel();
  const { uCol, uMCol } = reach(ctx, ['uCol', 'uMCol']);

  it('a ledger key naming an inherited member gets the neutral bar', () => {
    INHERITED.forEach((k) => {
      expect(uCol(k), k).toBe('var(--bar-neutral)');
      expect(uMCol(k), k).toBe('var(--bar-neutral)');
    });
  });

  it('and a key that really has a slot still gets its hue', () => {
    // Both maps are top-level `let`, reassigned wholesale on every redraw, so
    // seeding them here is what the render does.
    vm.runInContext("USLOTS={'claude-opus-5':3};MSLOTS={'claude-haiku-4':7};", ctx);
    expect(uCol('claude-opus-5')).toBe('var(--viz-3)');
    expect(uMCol('claude-haiku-4')).toBe('var(--viz-7)');
    expect(uCol('claude-haiku-4')).toBe('var(--bar-neutral)');
  });
});

describe('the usage fragment decoder refuses a key it does not know', () => {
  // The most reachable of the lot: no manifest and no config, just a link.
  // `#/usage!constructor=x` used to resolve `UFDIM['constructor']` to a
  // function, set `UF[<the function, stringified>]` and push the function itself
  // onto the order — which the "no rows match" banner then renders.

  it('an unknown fragment key changes nothing and reports nothing applied', () => {
    const { ctx } = panel();
    const { uApplyFragment } = reach(ctx, ['uApplyFragment']);
    const before = vm.runInContext('JSON.stringify(UF)', ctx);
    INHERITED.forEach((k) => {
      expect(uApplyFragment(k + '=x'), k).toBe(false);
    });
    expect(vm.runInContext('JSON.stringify(UF)', ctx)).toBe(before);
    expect(vm.runInContext('UORDER.length', ctx)).toBe(0);
  });

  it('and a real fragment key still applies', () => {
    const { ctx } = panel();
    const { uApplyFragment } = reach(ctx, ['uApplyFragment']);
    expect(uApplyFragment('m=claude-opus-5')).toBe(true);
    expect(vm.runInContext('UF.model', ctx)).toBe('claude-opus-5');
    expect(vm.runInContext('JSON.stringify(UORDER)', ctx)).toBe('["model"]');
  });
});

describe('the density preview refuses a density it does not know', () => {
  // `TDENSITY[d]===undefined?1:TDENSITY[d]` is spelled out rather than `||1` on
  // purpose — the multiplier is a denominator's disguise and a silent 1 would
  // hide a typo. The prototype chain defeated that: `constructor` is not
  // undefined, so the guard passed a FUNCTION through as the multiplier and the
  // paint wrote `NaNrem` onto every spacing token :root declares.

  const seeded = () => {
    const { ctx } = panel();
    // One captured base value, so exactly one property is in play; the stub's
    // getComputedStyle answers '' for the rest and tScale refuses those.
    vm.runInContext(
      "globalThis.__written=[];"
      + "document.documentElement.style.setProperty=(n,v)=>{__written.push([n,v]);};"
      + "TBASE['--sp-1']='1rem';", ctx);
    return ctx;
  };

  it('an unknown density paints nothing, rather than painting NaN', () => {
    const ctx = seeded();
    const { tPaintLayout } = reach(ctx, ['tPaintLayout']);
    vm.runInContext("TLAY={density:'constructor',order:{}};", ctx);
    tPaintLayout();
    expect(vm.runInContext('__written', ctx)).toEqual([]);
  });

  it('and a real density still scales the token it always did', () => {
    const ctx = seeded();
    const { tPaintLayout } = reach(ctx, ['tPaintLayout']);
    vm.runInContext("TLAY={density:'compact',order:{}};", ctx);
    tPaintLayout();
    expect(vm.runInContext('__written', ctx)).toEqual([['--sp-1', '.8rem']]);
  });
});

describe('no panel part reads one of these tables bare', () => {
  // A property of the SOURCE, and labelled as one: the cases above prove the
  // five sites that exist today behave, and this is what stops a sixth being
  // written next week. It is the reason the fix is one helper rather than a
  // guard pasted into each reader.
  //
  // Every table here is keyed by a value that originates outside the code — a
  // manifest string, a config value, a ledger key, a URL fragment.
  const TABLES = ['LABELS', 'UFDIM', 'TDENSITY', 'USLOTS', 'MSLOTS'];

  // `UFDIM` is BUILT by element assignment on its own declaration line, from
  // `UFKEY`'s own keys. That is a write with a key the code owns, and it is the
  // only bare bracket any of these tables is allowed.
  const ALLOWED = 'const UFDIM={};for(const d in UFKEY)UFDIM[UFKEY[d]]=d;';

  it('every read goes through lookup()', () => {
    const offenders = [];
    for (const name of panelParts()) {
      const src = readPart(name).split(ALLOWED).join('');
      for (const table of TABLES) {
        const re = new RegExp('\\b' + table + '\\s*\\[', 'g');
        for (const m of src.matchAll(re)) {
          offenders.push(name + ': ' + src.slice(m.index, m.index + 60).split('\n')[0]);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('and the guard can see one when it is there', () => {
    // The allow case. Without it the assertion above passes just as well when
    // the regex matches nothing anywhere — which is what a table renamed out
    // from under it would look like.
    const re = new RegExp('\\bLABELS\\s*\\[', 'g');
    expect([...'const x=LABELS[v]||v;'.matchAll(re)].length).toBe(1);
    expect(panelParts().some((n) => readPart(n).includes('lookup(LABELS,'))).toBe(true);
  });
});

describe('a map the panel BUILDS from outside keys stores what it is given', () => {
  // The other half of the class, and the one no read helper can repair:
  // `m['__proto__']=v` on a plain object re-points the prototype instead of
  // storing the value, so nothing ever reads it back. Task and phase ids carry
  // NO `pattern` in the JSON Schema, and model names and authors are free text
  // in the ledger, so every key here comes from outside.

  it('the Overview remembers a phase called `__proto__` is open', () => {
    const { ctx } = panel();
    expect(vm.runInContext('Object.getPrototypeOf(OVF.open)', ctx)).toBe(null);
    expect(vm.runInContext('Object.getPrototypeOf(OVF.evOpen)', ctx)).toBe(null);
    vm.runInContext("OVF.open['__proto__']=true;OVF.evOpen['constructor']=true;", ctx);
    expect(vm.runInContext("OVF.open['__proto__']", ctx)).toBe(true);
    expect(vm.runInContext('OVF.evOpen.constructor', ctx)).toBe(true);
    expect(vm.runInContext('Object.keys(OVF.open)', ctx)).toEqual(['__proto__']);
  });

  it('...and an id nobody opened still reads as closed, not as a function', () => {
    // The other direction: a map that answered `true` for everything would pass
    // the case above and fold nothing.
    const { ctx } = panel();
    INHERITED.forEach((k) => {
      expect(vm.runInContext('!!OVF.open[' + JSON.stringify(k) + ']', ctx), k)
        .toBe(false);
      expect(vm.runInContext('!!OVF.evOpen[' + JSON.stringify(k) + ']', ctx), k)
        .toBe(false);
    });
  });

  it('the palette ranks a model called `constructor` by its spend', () => {
    // `uRanks` accumulates tokens into a map keyed by a LEDGER value. On a plain
    // object `t['constructor']` came back as a function, `fn + tokens` made a
    // string, and the comparator then subtracted two strings and sorted by NaN.
    const { ctx } = panel();
    // Spends chosen so the answer is a real order and no value equals its key.
    vm.runInContext(
      'USAGE={facts:['
      + "['t',null,null,'constructor',null,null,null,50,0,0],"
      + "['t',null,null,'__proto__',null,null,null,10,0,0],"
      + "['t',null,null,'claude-opus-5',null,null,null,30,0,0]"
      + ']};', ctx);
    const { uRanks } = reach(ctx, ['uRanks']);
    const bySpend = uRanks(3, 'spend');
    expect(Object.getPrototypeOf(bySpend)).toBe(null);
    // Descending by tokens: constructor 50, opus 30, __proto__ 10 — which is
    // NOT the lexical order the other mode gives, so neither answer is the
    // other's under a different name.
    expect(bySpend.constructor).toBe(0);
    expect(bySpend['claude-opus-5']).toBe(1);
    expect(bySpend['__proto__']).toBe(2);
    const byName = uRanks(3, 'name');
    expect(Object.keys(byName).sort()).toEqual(
      ['__proto__', 'claude-opus-5', 'constructor']);
  });

  it('and the ranks really do differ from the order they were written in', () => {
    // Guards the case above against a comparator that answered iteration order:
    // 'name' sorts lexically and 'spend' by tokens, and the two disagree here.
    const { ctx } = panel();
    vm.runInContext(
      'USAGE={facts:['
      + "['t',null,null,'constructor',null,null,null,50,0,0],"
      + "['t',null,null,'__proto__',null,null,null,10,0,0],"
      + "['t',null,null,'claude-opus-5',null,null,null,30,0,0]"
      + ']};', ctx);
    const { uRanks } = reach(ctx, ['uRanks']);
    const bySpend = uRanks(3, 'spend');
    const byName = uRanks(3, 'name');
    expect(byName['__proto__']).toBe(0);
    expect(byName.constructor).toBe(2);
    expect(bySpend.constructor).not.toBe(byName.constructor);
    expect(bySpend['__proto__']).not.toBe(byName['__proto__']);
  });

  it('the proof above can fail: a plain object drops the `__proto__` rank', () => {
    const src = 'const o=Object.create(null);'.replace('Object.create(null)', '{}');
    expect(src).toBe('const o={};');
    // Driven rather than argued: the same write against a plain object.
    const plain = {};
    plain['__proto__'] = 3;
    expect(Object.prototype.hasOwnProperty.call(plain, '__proto__')).toBe(false);
    expect(Object.keys(plain)).toEqual([]);
    const bare = Object.create(null);
    bare['__proto__'] = 3;
    expect(bare['__proto__']).toBe(3);
    expect(Object.keys(bare)).toEqual(['__proto__']);
  });
});
