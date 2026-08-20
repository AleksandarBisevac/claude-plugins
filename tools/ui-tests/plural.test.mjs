// `plural` on both surfaces, against the Python it mirrors.
//
// The rule is four words long, which is exactly why it spread: it was spelled as
// a bare suffix in the panel (`+(n===1?'':'s')`), as a literal `(s)` that agrees
// with nothing, and again in the report as a two-branch clause — while
// `_fmt.plural` existed the whole time and Python's own copies had already been
// merged into it. A rule small enough to look cheaper than reaching for it is the
// rule that ends up with no owner.
//
// It lives in `shared/`, so it is checked as BOTH surfaces receive it — a part
// that assembles into the panel and not the report would otherwise pass here on
// the panel's copy alone.
import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';
import { pyFmt } from './python-fmt.mjs';

const panel = reach(loadPanel().ctx, ['plural']);
const report = reach(loadReport().ctx, ['plural']);

// Every branch: the singular, the ordinary plural, zero (which is plural), the
// irregular `many`, a negative, and the `%d` truncation Python applies whether or
// not a caller ever passes a fraction.
const CASES = [
  [1, 'change', undefined],
  [2, 'change', undefined],
  [0, 'change', undefined],
  [1, 'person', 'people'],
  [3, 'person', 'people'],
  [0, 'person', 'people'],
  [-1, 'change', undefined],
  [-2, 'change', undefined],
  [1.7, 'change', undefined],
  [-1.7, 'change', undefined],
  [0.4, 'change', undefined],
  [1, 'phase matches outside this view', 'phases match outside this view'],
  [2, 'phase matches outside this view', 'phases match outside this view'],
];

describe('plural mirrors _fmt.plural', () => {
  const want = pyFmt(CASES.map(([n, one, many]) =>
    ['plural', many === undefined ? [n, one] : [n, one, many]]));
  const label = (i) => JSON.stringify(CASES[i]);

  it('on the panel, case for case', () => {
    CASES.forEach(([n, one, many], i) => {
      expect(panel.plural(n, one, many), label(i)).toBe(want[i]);
    });
  });

  it('and on the report, which receives the same part', () => {
    CASES.forEach(([n, one, many], i) => {
      expect(report.plural(n, one, many), label(i)).toBe(want[i]);
    });
  });

  it('the two surfaces are one implementation, not two that agree', () => {
    // A shared part is only shared if both sides got THIS one. Comparing the
    // function sources catches a copy pasted into a surface part, which would
    // pass both cases above.
    expect(String(panel.plural)).toBe(String(report.plural));
  });

  it('the sweep exercises the singular AND a plural AND an irregular — it is '
     + 'not passing over one branch', () => {
    // The check on the check: a `plural` that always appended 's' would pass a
    // corpus with no singular in it, and one that never did would pass a corpus
    // with no plural.
    const kinds = {
      singular: want.filter((s) => /^-?1 [a-z]/.test(s) && !/s$|people/.test(s)).length,
      suffixed: want.filter((s) => /changes$/.test(s)).length,
      irregular: want.filter((s) => /people$/.test(s)).length,
    };
    for (const [name, n] of Object.entries(kinds)) {
      expect(n, name + ' has no case: ' + JSON.stringify(kinds)).toBeGreaterThan(0);
    }
  });
});
