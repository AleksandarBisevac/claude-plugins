// The gate-card fixture's five `require-plan.py` rows, and why they are read
// rather than typed (F169).
//
// WHAT WENT WRONG, AND WHY IT LOOKED FINE. `tools/capture-screenshots.mjs` seeded
// the plan-gate feed with six rows. One of them — the armed bypass — was repaired
// to read its sentence out of the hook that writes it, because that sentence had
// drifted the moment its writer changed and its copy did not (F167). The other
// five stayed retyped literals, and every one of them still AGREED with
// `require-plan.decide`. That agreement is the fault, not the defence: nothing
// compared them, so they were not correct, they were untriggered. The sixth row is
// the experiment already run — same block, same shape, one release earlier.
//
// WHY THE CASES ARE HERE AND NOT IN THE CAPTURE. Driving the capture takes a
// machine-wide lock and minutes of browser time, and nothing below needs a
// browser: the fixture is a string and the question is whether it still equals
// what the hook would write. What a browser would add is the shutter.
//
// BOTH SIDES ARE DERIVED, AND DELIBERATELY NOT THE SAME WAY — the rule
// `armed-reason.test.mjs` set for its own row. `gateReason()` PARSES
// `require-plan.py`, resolving a literal, a literal under `%`, and a local bound
// to a two-armed choice. Every case here reads the same file as BYTES and never
// as code. Neither side names a sentence: the expectation is built by undoing the
// substitution on what `gateReason` returned and asking the hook's source whether
// it owns the result. A sentence typed into this file would be the same fault one
// layer out, and the case at the bottom is the one that would find it.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { gateReason } from '../capture-screenshots.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const WRITER = path.join(REPO, 'plugins', 'audit', 'hooks', 'require-plan.py');
const CAPTURE = path.join(REPO, 'tools', 'capture-screenshots.mjs');

const writerSrc = readFileSync(WRITER, 'utf8');
const captureSrc = readFileSync(CAPTURE, 'utf8');
// The capture again, with line wrapping flattened out. A retyped sentence does
// not have to arrive on one line to be a retyped sentence: the first version of
// this suite passed while three of them sat in a JSDoc block a few lines above
// the fixture, two of them wrapped across a ` * ` continuation and therefore
// invisible to a plain substring search. Prose is source text and rots the same
// way, so the haystack is the whole file with its wrapping removed.
const captureFlat = captureSrc.replace(/\n\s*\*?\s*/g, ' ').replace(/\s+/g, ' ');

/**
 * The rows this fixture seeds from `require-plan.py`, as the capture asks for
 * them. The numbers are the fixture's own — a magnitude and the bar it is graded
 * against — and are the only thing here that is not the hook's.
 * @type {Array<[string, Array<number>]>}
 */
const SEEDED = [
  ['observe', [96, 80]],
  ['allow.trivial', [41]],
  ['warn', []],
  ['deny', [214, 80]],
  ['bypass.consumed', []],
];

/**
 * Put the `%d`s back, so a filled sentence can be asked of the writer's source.
 *
 * Each value is undone ONCE, leftmost first, which is the order `gateReason` fills
 * them in. The count is returned alongside rather than trusted: a sentence that
 * never carried the value would come back unchanged and every assertion built on
 * it would then be about a string neither side produced.
 * @param {string} filled - what `gateReason` returned
 * @param {Array<number>} values - the numbers it was given, in order
 * @returns {{template: string, undone: number}}
 */
function unfill(filled, values) {
  let undone = 0;
  const template = values.reduce((text, value) => {
    const at = text.indexOf(String(value));
    if (at < 0) return text;
    undone += 1;
    return text.slice(0, at) + '%d' + text.slice(at + String(value).length);
  }, filled);
  return { template, undone };
}

describe('every seeded gate reason is require-plan.py\'s own sentence', () => {
  it.each(SEEDED)('%s: the template comes back out of the writer\'s source',
    (event, values) => {
      const filled = gateReason(event, ...values);
      const { template, undone } = unfill(filled, values);
      // Undoing every value is what stops the rest of this case being vacuous: a
      // template that had lost its conversions would return the sentence
      // unchanged, and `toContain` would then be asking the hook about a string
      // with the fixture's numbers baked into it.
      expect(undone, `${filled} does not carry ${JSON.stringify(values)}`)
        .toBe(values.length);
      expect(template.split('%d').length - 1).toBe(values.length);
      // The claim, and the reason nothing here spells a sentence: whatever
      // `gateReason` said, the hook has to own those bytes.
      expect(writerSrc, `require-plan.py does not contain ${JSON.stringify(template)}`)
        .toContain(template);
    });

  it.each(SEEDED)('%s: and the capture owns none of them', (event, values) => {
    // The direct statement of the fault. A retyped copy — the original one, or
    // the same sentence typed back by hand a release later, which is how this
    // arrived the first time — puts these bytes into the capture, and that is
    // what fails here. The sentence is computed, never written, so this file
    // cannot be the place the copy comes back to either.
    const filled = gateReason(event, ...values);
    const { template } = unfill(filled, values);
    for (const needle of [filled, template]) {
      expect(captureFlat, needle).not.toContain(needle.replace(/\s+/g, ' '));
    }
  });

  it('fills with the numbers it is given, rather than ignoring them', () => {
    // The mutation this separates: a `gateReason` that returned its template
    // unfilled, or filled from somewhere other than its arguments, would make
    // these two equal. Both magnitudes are graded against the same bar on the
    // card, so the magnitude is the only thing that differs between them.
    const [, quiet] = SEEDED[0];
    const [, loud] = SEEDED[3];
    expect(gateReason('observe', ...quiet)).not.toBe(gateReason('deny', ...loud));
    expect(gateReason('deny', ...loud)).toContain(String(loud[0]));
  });
});

describe('gateReason refuses rather than inventing a sentence', () => {
  // The second direction. The cases above would all pass against a derivation
  // that never refuses anything; these are the ones that fail if the throwing
  // is removed — and the last one in this block is the pair to them, failing
  // instead if the throwing became unconditional.
  it('throws on an event the hook writes no reason for', () => {
    expect(() => gateReason('bypass.armed')).toThrow(/writes no reason/);
  });

  it('throws when no arm of the reason takes the numbers given', () => {
    // `reason` in `decide()` is one of two sentences, and the count of values is
    // the only thing that says which. Asking for a count neither arm takes is
    // the shape a rewording would produce, and guessing at it is what would put
    // a sentence nobody writes into a committed PNG.
    expect(() => gateReason('warn', 5)).toThrow(/needs exactly one/);
    expect(() => gateReason('allow.trivial')).toThrow(/needs exactly one/);
  });

  it('but takes either arm when the hook really writes either', () => {
    // The boundary, and it is not a refusal. `deny` is reached down both arms of
    // that choice, so asking for it with no numbers is a legitimate request for
    // the other sentence — the first draft of the case above expected a throw
    // here and was wrong about the hook, not about the code. A derivation that
    // refused this would be narrower than the writer it derives from.
    expect(gateReason('deny')).toBe(gateReason('warn'));
    expect(gateReason('deny', 214, 80)).not.toBe(gateReason('deny'));
  });

  it('throws on a value a %d cannot print', () => {
    expect(() => gateReason('allow.trivial', 4.5)).toThrow(/whole numbers/);
  });

  it('and refuses nothing the capture actually asks of it', () => {
    // Looks vacuous and is not: it is the only case here that fails when the
    // refusals above become unconditional, which is the other way to get this
    // wrong. Every row the fixture seeds has to come back a non-empty string.
    for (const [event, values] of SEEDED) {
      expect(gateReason(event, ...values).length,
        `${event} came back empty`).toBeGreaterThan(0);
    }
  });
});

describe('the seeded gate feed has no reason typed into it', () => {
  // Counted over the seeded block alone rather than over the whole capture: the
  // file is thousands of lines and a needle that hit a comment somewhere else
  // would let a real fixture regression through.
  const from = captureSrc.indexOf('const seeded = [');
  const block = captureSrc.slice(from, captureSrc.indexOf('];', from));

  it('has one derivation per row, and one row per derivation', () => {
    // COUNTED, not found. Every row opens with its timestamp, and every row's
    // last cell is a call; a row that got its sentence back would leave the two
    // totals apart, which "there is a gateReason call in here" could not see.
    const rows = block.split(/'\d{4}-\d{2}-\d{2}T/).length - 1;
    const derived = (block.split('gateReason(').length - 1)
      + (block.split('armedBypassReason()').length - 1);
    expect(rows, block).toBe(SEEDED.length + 1);
    expect(derived, block).toBe(rows);
  });

  it('derives each row for the event that row is', () => {
    // A multiset, not a membership test: a row that asked for its neighbour's
    // sentence would leave one event named twice and one not at all, which
    // "every seeded event appears somewhere" could not see. A clean SWAP between
    // two rows survives this and is caught one layer down instead — the two arms
    // of `reason` take different counts of numbers, so a swapped pair stops the
    // capture rather than mislabelling a card.
    const asked = [...block.matchAll(/gateReason\('([\w.]+)'/g)].map((m) => m[1]);
    expect(asked.slice().sort(), block).toEqual(SEEDED.map(([e]) => e).sort());
  });
});
