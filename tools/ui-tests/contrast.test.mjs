// The Appearance tab's contrast warnings, against the Python that produces the
// other half of the same list.
//
// WHY THIS EXISTS. `tLocalWarnings()` in the panel and
// `_ui_theme.contrast_warnings()` in Python judge the same thing, and their
// results are CONCATENATED into one list the reader sees. So a difference between
// them is not an inconsistency a reader could notice and discount — it is a list
// where two sentences about the same theme disagree and nothing says which half
// produced which. Three differences were measured before this file existed:
//
//   * the panel graded FOUR pairs where Python graded six (`--text/--surface-2`
//     and `--muted/--bg` were missing), so a draft could report no warnings where
//     the server reported two;
//   * `contrast_ratio` rounds to 2dp BEFORE comparing to the floor and `tRatio`
//     did not, so the two disagreed for any true ratio in [4.495, 4.5);
//   * Python formats the floor with `%.1f` and the panel interpolated the number,
//     so the same warning read "below 3.0:1" from one side and "below 3:1" from
//     the other.
//
// The pairs are no longer duplicated at all — `_panel_page.py` substitutes
// `_ui_theme.CONTRAST_PAIRS` into the page — so the first case below is checking
// that the substitution really happened, not that two tables agree.
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import { loadPanel, reach } from './sandbox.mjs';
import { pyCall } from './python-fmt.mjs';

const [pairs, defaultTheme] = pyCall('_ui_theme',
  [['CONTRAST_PAIRS', []], ['DEFAULT_THEME', []]]);

/**
 * Load the panel with the REAL pair table and `THEME` set as the server hands it.
 *
 * The table is passed as a placeholder override rather than injected afterwards,
 * so what runs is the same substitution the page gets. The sandbox's default is a
 * `{}` stub for every non-string placeholder, which would make `TPAIRS.forEach`
 * a no-op and every case below pass over nothing.
 */
function panelWithTheme(theme) {
  const { ctx } = loadPanel({
    placeholders: { __CONTRAST_PAIRS__: JSON.stringify(pairs) },
  });
  vm.runInContext('THEME = ' + JSON.stringify({ theme, default: defaultTheme })
    + '; TDRAFT = null;', ctx);
  return reach(ctx, ['tLocalWarnings', 'TPAIRS', 'tRatio']);
}

// Themes chosen to make the checker SPEAK: the first is the shipped default and
// should be clean, and the rest each break a specific pair — including the two
// the panel used to be blind to.
const THEMES = {
  'the default': {},
  'text on surface-2 only': { '--surface-2': { $value: '#767676', $dark: '#767676' } },
  'muted on bg only': { '--muted': { $value: '#a0a0a0', $dark: '#a0a0a0' } },
  'a low-contrast accent': { '--accent': { $value: '#9fd0c8', $dark: '#9fd0c8' } },
  'text itself too light': { '--text': { $value: '#9a9a9a', $dark: '#9a9a9a' } },
  // A single-valued entry: `$value` and no `$dark`. Python falls back to `$value`
  // WITHIN the entry for dark mode; the panel's `tVal` falls through to the next
  // source instead. If those differ, this is where it shows.
  'a single-valued override': { '--text': { $value: '#8f8f8f' } },
};

describe('contrast pairs come from Python, not from a copy', () => {
  it('TPAIRS is _ui_theme.CONTRAST_PAIRS, substituted into the page', () => {
    const { TPAIRS } = panelWithTheme({});
    expect(TPAIRS.length).toBe(pairs.length);
    expect(TPAIRS).toEqual(pairs);
    // The vacuity guard: an empty table on both sides would satisfy the equality
    // above and check nothing. Six is what ships; the floor is what matters.
    expect(pairs.length).toBeGreaterThanOrEqual(5);
  });

  it('...including the two the panel used to be blind to', () => {
    const { TPAIRS } = panelWithTheme({});
    const flat = TPAIRS.map(([fg, bg]) => fg + '/' + bg);
    expect(flat).toContain('--text/--surface-2');
    expect(flat).toContain('--muted/--bg');
  });
});

describe('the two halves of one warning list agree', () => {
  for (const [label, theme] of Object.entries(THEMES)) {
    it('matches _ui_theme.contrast_warnings for ' + label, () => {
      const { tLocalWarnings } = panelWithTheme(theme);
      const [want] = pyCall('_ui_theme', [['contrast_warnings', [theme]]]);
      // Sorted: both sides iterate pairs then modes, but the ORDER is not the
      // claim — the set of sentences is. Comparing sorted lists means a
      // reordering of CONTRAST_PAIRS cannot fail this for the wrong reason.
      expect(tLocalWarnings().slice().sort()).toEqual(want.slice().sort());
    });
  }

  it('and at least one of those themes actually produced a warning', () => {
    // The check on the check. Every case above would pass over two empty lists,
    // which is exactly what a checker that silently measures nothing returns.
    const counts = Object.entries(THEMES).map(([label, theme]) => {
      const { tLocalWarnings } = panelWithTheme(theme);
      return [label, tLocalWarnings().length];
    });
    const spoke = counts.filter(([, n]) => n > 0);
    expect(spoke.length, 'no theme produced a warning: ' + JSON.stringify(counts))
      .toBeGreaterThan(0);
  });

  it('the shipped default is clean on both sides', () => {
    const { tLocalWarnings } = panelWithTheme({});
    const [want] = pyCall('_ui_theme', [['contrast_warnings', [{}]]]);
    expect(tLocalWarnings()).toEqual([]);
    expect(want).toEqual([]);
  });
});

describe('the ratio itself', () => {
  it('tRatio matches _ui_theme.contrast_ratio, rounding included', () => {
    const { tRatio } = panelWithTheme({});
    // Colours spread so some quotients land near a 2dp boundary, which is where
    // "round before comparing" and "compare the raw quotient" part company.
    const colours = ['#000000', '#111111', '#767676', '#949494', '#a0a0a0',
                     '#cccccc', '#ffffff', '#1f6feb', '#9fd0c8'];
    const cases = [];
    for (const a of colours) for (const b of colours) cases.push([a, b]);
    const want = pyCall('_ui_theme', cases.map(([a, b]) => ['contrast_ratio', [a, b]]));
    const bad = [];
    cases.forEach(([a, b], i) => {
      const got = tRatio(a, b);
      if (got !== want[i]) bad.push(a + ' on ' + b + ': py=' + want[i] + ' js=' + got);
    });
    expect(bad).toEqual([]);
    expect(cases.length).toBe(colours.length * colours.length);
  });

  it('a value that is not a colour is unmeasurable on both sides, not zero', () => {
    const { tRatio } = panelWithTheme({});
    const [want] = pyCall('_ui_theme', [['contrast_ratio', ['inherit', '#fff']]]);
    expect(want).toBe(null);
    expect(tRatio('inherit', '#fff')).toBe(null);
  });
});
