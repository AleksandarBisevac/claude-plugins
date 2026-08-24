// The gate-card fixture's `bypass.armed` row, and why it is read rather than typed
// (F167).
//
// WHAT WENT WRONG. `tools/capture-screenshots.mjs` seeded that row with a
// prompt-shaped sentence — the keyword followed by what somebody was doing — and
// `docs/screenshots/panel-gate.png` is a committed render of the card that paints
// it in the WHY column. `detect-plan-skip._arm_bypass` was repaired to record the
// FACT and the KEYWORD and never the wording, so the picture went on advertising a
// leak the product no longer has. That is worse than a stale screenshot: a reader
// learns from it that this surface publishes prompts.
//
// WHY THE CASES ARE HERE AND NOT IN THE CAPTURE. Driving the capture takes a
// machine-wide lock and minutes of browser time, and nothing here needs a browser:
// the fixture is a string, and the question is whether it still equals what the
// hook writes. What a browser would add is the shutter.
//
// BOTH SIDES ARE DERIVED, AND DELIBERATELY NOT THE SAME WAY. `armedBypassReason()`
// imports the hook module and reads the constant OBJECT; the case below reads the
// LITERAL out of the source text. Two derivations that cannot be wrong in the same
// way is the whole reason the fixture is not retyped a third time.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { armedBypassReason } from '../capture-screenshots.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const HOOKS = path.join(REPO, 'plugins', 'audit', 'hooks');
const CAPTURE = path.join(REPO, 'tools', 'capture-screenshots.mjs');

/** The `ARMED_REASON` literal, read as text rather than imported. */
function reasonLiteral() {
  const src = readFileSync(path.join(HOOKS, 'detect-plan-skip.py'), 'utf8');
  return /^ARMED_REASON = "([^"]*)"$/m.exec(src);
}

/** `_config.DEFAULTS`' bypass keyword, likewise as text. */
function defaultKeyword() {
  const src = readFileSync(path.join(HOOKS, '_config.py'), 'utf8');
  return /^ {4}"bypassKeyword": "([^"]*)",$/m.exec(src);
}

describe('armedBypassReason is the hook\'s own sentence', () => {
  it('matches the constant read straight out of the source', () => {
    const reason = reasonLiteral();
    expect(reason, 'detect-plan-skip.py no longer declares ARMED_REASON on one line')
      .not.toBe(null);
    const keyword = defaultKeyword();
    expect(keyword, '_config.DEFAULTS no longer declares bypassKeyword').not.toBe(null);
    expect(armedBypassReason()).toBe(reason[1].replace('%s', keyword[1]));
  });

  it('ends AT the keyword, which is what leaves no room for a typed sentence', () => {
    // The shape, not the spelling. A `reason` that ends at the configured word
    // cannot carry anything a person wrote after it, and the row that shipped —
    // the keyword followed by the rest of somebody's prompt — fails exactly here.
    const keyword = defaultKeyword();
    expect(keyword).not.toBe(null);
    const reason = armedBypassReason();
    expect(reason.endsWith(keyword[1]), reason).toBe(true);
    expect(reason.split(keyword[1]).length - 1, reason).toBe(1);
  });
});

describe('the seeded gate feed carries no sentence typed in this file', () => {
  // Counted over the seeded block alone rather than over the whole capture: the
  // file is thousands of lines and a needle that hit a comment somewhere else
  // would let a real fixture regression through.
  const src = readFileSync(CAPTURE, 'utf8');
  const block = src.slice(src.indexOf('const seeded = ['),
    src.indexOf('];', src.indexOf('const seeded = [')));

  it('has a bypass.armed row, and it is the derivation', () => {
    expect(block.split("'bypass.armed'").length - 1, block).toBe(1);
    expect(block.split('armedBypassReason()').length - 1, block).toBe(1);
  });

  it('and the keyword appears in no literal in it', () => {
    // The old row began with the keyword. Asserting the keyword is absent from the
    // seeded block says the sentence is not typed here in ANY spelling, which
    // "the old string is gone" would not: retyping the repaired sentence by hand
    // is the same fault one release later.
    const keyword = defaultKeyword();
    expect(keyword).not.toBe(null);
    expect(block).not.toContain(keyword[1]);
  });
});
