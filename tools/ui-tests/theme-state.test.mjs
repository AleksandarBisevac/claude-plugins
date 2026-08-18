// `isDark()` exists twice — once in report.js, once in panel.js — and both
// answer the same question: does the explicit data-theme on <html> win, and if
// there is none, what does the OS say? A user who toggles the panel and then
// opens the report from it expects one answer, so the two must agree on all
// four cells of the matrix.
//
// This is the one place the DOM stub is part of the system under test rather
// than scaffolding, so it does the two things that matter for real:
// setAttribute actually stores, and matchMedia actually answers per query.

import { describe, expect, it } from 'vitest';
import { loadPanel, loadReport, reach } from './sandbox.mjs';

function reportTheme(prefersDark, attr) {
  const { ctx, sandbox } = loadReport({ prefersDark });
  if (attr) sandbox.document.documentElement.setAttribute('data-theme', attr);
  const fns = reach(ctx, ['isDark', 'prefersDark']);
  return { isDark: fns.isDark(), prefersDark: fns.prefersDark() };
}

function panelTheme(prefersDark, attr) {
  const { ctx, sandbox } = loadPanel({ prefersDark });
  if (attr) sandbox.document.documentElement.setAttribute('data-theme', attr);
  return { isDark: reach(ctx, ['isDark']).isDark() };
}

// attr === null is "no explicit choice"; the panel's own load sets none,
// because localStorage is stubbed as the blocked shape it has on file://.
const MATRIX = [
  { prefersDark: false, attr: null, expected: false },
  { prefersDark: true, attr: null, expected: true },
  { prefersDark: false, attr: 'dark', expected: true },
  { prefersDark: true, attr: 'light', expected: false },
  // A value that is neither: `t ? t === 'dark' : …` treats any non-empty
  // attribute as an explicit choice, so 'auto' reads as light on BOTH surfaces.
  // Written down because it is surprising, and because the two agreeing on a
  // surprise is the fact worth protecting.
  { prefersDark: true, attr: 'auto', expected: false },
];

describe('the two isDark() implementations agree', () => {
  it.each(MATRIX)('prefersDark=$prefersDark data-theme=$attr -> $expected',
    ({ prefersDark, attr, expected }) => {
      const r = reportTheme(prefersDark, attr);
      const p = panelTheme(prefersDark, attr);
      expect(r.isDark).toBe(expected);
      expect(p.isDark).toBe(expected);
    });

  it('covers both OS preferences and both explicit choices', () => {
    // A matrix that lost a row would still pass every case above.
    expect(MATRIX.filter((c) => c.prefersDark).length).toBeGreaterThanOrEqual(2);
    expect(MATRIX.filter((c) => !c.prefersDark).length).toBeGreaterThanOrEqual(2);
    expect(MATRIX.filter((c) => c.attr === null).length).toBe(2);
  });
});

describe('report.js prefersDark asks the OS, and only the OS', () => {
  it('follows the media query', () => {
    expect(reportTheme(true, null).prefersDark).toBe(true);
    expect(reportTheme(false, null).prefersDark).toBe(false);
  });

  it('is not swayed by an explicit data-theme', () => {
    // The second direction: prefersDark must report the OS even when the page
    // is overriding it, or the toggle would have nothing to toggle away from.
    expect(reportTheme(true, 'light').prefersDark).toBe(true);
    expect(reportTheme(false, 'dark').prefersDark).toBe(false);
  });

  it('queries prefers-color-scheme and not something else', () => {
    const asked = [];
    const { ctx, sandbox } = loadReport({ prefersDark: true });
    sandbox.matchMedia = (q) => { asked.push(q); return { matches: true }; };
    reach(ctx, ['prefersDark']).prefersDark();
    expect(asked.length).toBe(1);
    expect(asked[0]).toMatch(/prefers-color-scheme:\s*dark/);
  });
});
