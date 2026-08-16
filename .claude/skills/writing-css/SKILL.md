---
name: writing-css
description: How CSS is written in this repo — every value comes from a design token, one component gets one name across both surfaces, and the five theme lints decide what ships. Covers the token layer and the half-finished spacing migration, modern syntax that is actually safe here (cascade layers and container queries are Baseline widely; anchor positioning is not), keeping specificity flat with :where() instead of !important, component structure and shared partials, DRY across report.css and panel.css, dark mode and print, and the anti-patterns that have already shipped invisible bars and an unthemeable printed page. Use when planning, writing, reading, reviewing or refactoring report.css, panel.css or _ui_theme.py, when adding a component or a colour, or when the same rule is about to exist twice.
---

# Writing CSS here

Two stylesheets, ~2,000 lines, concatenated by Python after a generated token layer into one
inline `<style>`. Neither is valid alone — both reference custom properties they do not declare,
and `panel.css` on its own fails the `color-scheme` check. Assembly, splitting and the byte pins
belong to `refactoring-the-assembled-ui`; this is how you write a rule.

## Tokens are the language

`_ui_theme.py` declares **78 custom properties** on `:root` (58 of them user-themable) and
prepends them to both sheets. The discipline is already strong — `panel.css` uses `var(--…)` 605
times against 13 raw hex literals, `report.css` 429 against 8 — and it is the thing to protect.

- **Never write a raw colour.** If a role does not exist, add the token; do not inline a hex.
- **The spacing migration is half done, so finish it rather than widening it.** `--sp-0` … `--sp-7`
  exist and are used throughout the usage sections, yet `.5rem`, `.25rem`, `.75rem`, `1rem` and
  `1.5rem` are still written raw **204 times** elsewhere — and each of those five has an exact
  token. Use the token.
- **Type has a four-step scale and the sheets contain about 23 distinct font-size literals.** Pick
  a step; add one if the design genuinely needs it.
- **A metric both surfaces use is a token, or it will drift.** It already has: `.shell` is
  `max-width:92rem` in the panel and `96rem` in the report, `.bud`'s grid disagrees in four
  places, the nav breakpoint is `70rem` against `72rem`, `.tri` is `.9em` against `1em`.
- **Adding a token has obligations.** `compile_theme(DEFAULT_THEME) == TOKEN_CSS` is pinned
  byte-for-byte, so no comment inside `TOKEN_CSS` may contain a brace, and a new token must be
  placed in a theme group or the neutral list or the round-trip case fails.

## Modern syntax that is safe here

Check the feature before using it — `grep '^| container-queries '` in
`refactoring-the-assembled-ui/references/baseline-snapshot.md`. As of the 2026-07-08 snapshot:

- **Widely available, use freely:** cascade layers (`@layer`), container queries (`@container`),
  `:has()`, nesting, `:where()`/`:is()`.
- **Newly available, needs `@supports` plus a fallback:** `light-dark()`, view transitions.
- **Limited, do not use:** anchor positioning.

None of `@layer`, `:where()`, `:is()` or `@container` appears in either sheet today. That is the
gap worth closing first: with no specificity management, source order carries the whole cascade,
which is why `report.css` needs 18 `!important` declarations and a documented ordering dependency
between two blocks 290 lines apart.

- **`:where()` for anything shared.** It contributes zero specificity, so a base rule written
  `:where(a,button,input,summary):focus-visible{…}` lets both surfaces override it without
  escalation. The focus ring is currently written four times in each file with no base.
- **`@container` over `@media`** for component-level responsiveness — a report is read at widths
  nobody chose.
- **Media queries cannot read `var()`.** A shared breakpoint is either one agreed literal in the
  shared part or a Python-side substitution; it cannot be a token like `--nav-w` is.

## One component, one name

31 class names exist in both sheets. **35 pairs are the same component under different names** —
`.utip` and `.rtip` are 11 of 11 declarations identical, `.uhmperiod` and `.hmperiod` 5 of 5,
`.mut` and `.muted` the same idea. Worse, **ten names collide with incompatible meanings**:
`.bar` is an 8px track in the panel and a bordered 13rem block in the report; `.chip` is a
neutral tag versus a status pill; `.advice` is the styled block versus the list containing it.

- **Name the component once**, and use that name on both surfaces.
- **Rename before extracting.** Merging two rules that share a name and disagree silently breaks
  one surface. The rename touches the emitters (`panel.js`, `report.js`, `_report_html.py`) in
  the same commit.
- **Pick one modifier grammar.** The tree has both `.btn.primary` and `.btn-primary`.
- **A repeated selector prefix is a missing component class.** The sticky-table-header recipe is
  written six times in `panel.css` and the table root nine times, differing only in `font-size`.

## Dark mode, print

- Light is the base; dark is an override, and it is written **twice** on purpose — once under
  `prefers-color-scheme` and once under `[data-theme="dark"]` — because a media query and an
  attribute selector cannot share a block. Keep both in step.
- **Never define a colour only inside a media query.** A token declared only in a dark block
  vanishes in light mode; `theme_asymmetric_vars()` checks both directions because that shipped
  once as invisible bars.
- **`color-scheme` must be restated wherever a theme is chosen** — it is the one thing custom
  properties cannot reach, and it paints scrollbars, `<select>` menus and date pickers.
- **`@media print` is outside the theme compiler's reach.** A palette hard-coded there cannot be
  themed — which is the current state: the print block uses greys that exist in no token, so a
  themed report prints in someone else's colours.

## Anti-patterns and pitfalls

- **A raw value where a token exists** — the single most common one here.
- **`!important` outside `@media print` and `prefers-reduced-motion`.** Every one of the 18 in the
  tree is inside those and carries a comment justifying it. Reach for `:where()` or a better
  selector instead.
- **ID selectors for styling.** There are about eleven; do not add the twelfth.
- **Deep descendant chains** (`table.x tbody tr:last-child td`) — eight of these in `panel.css`
  are one missing `.tbl` component class.
- **A missing `;`** — it annexes the next declaration silently. `unterminated_css_decls()` exists
  because one such miss swallowed a five-line comment and a token declaration.
- **A `var(--x)` with no declaration** paints transparent and logs nothing.
  `undeclared_css_vars()` exists because that is how `--bar-neutral` shipped as invisible bars.
- **A CSS escape mangled by Python string handling** — `mangled_css_escapes()` exists because a
  filter chip shipped showing `¹30` instead of a tick, in every report for several versions.
- **Reflowing a rule casually.** Around 70 exact substring assertions pin the assembled
  stylesheet, two of them across line boundaries. Reflow deliberately and update the pin.

## What must stay green

All five theme lints run against the **assembled** string — `undeclared_css_vars`,
`unterminated_css_decls`, `theme_asymmetric_vars`, `mangled_css_escapes`,
`themes_missing_color_scheme`. A sheet that is valid alone proves nothing.

Then the browser: `node tools/capture-screenshots.mjs --check` and
`node tools/check-report-interactive.mjs` on a rendered report. These assert *computed* values and
are the only thing that can catch a cascade-order regression a substring pin cannot see — a
Python case can assert the CSS says `display:block`; only a browser proves the bar paints.
