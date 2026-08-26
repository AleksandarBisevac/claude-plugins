# The report's stylesheet, by feature

The parts are joined in the order `_ui_theme.REPORT_CSS_PARTS` lists, behind the
token layer, and served as a single inline `<style>` in a self-contained HTML file.

**Order is the cascade.** Two rules of equal specificity are decided by which one is
read last, so this sequence is behaviour: the shell before the components that sit
in it, and the print and forced-colours blocks after the colours they override.
Sorting these names alphabetically changes what ships.

The order is declared in `_ui_theme` rather than beside the assembler, because the
theme lints run at that layer and must audit the sheet in the order that ships — a
lint over a differently-ordered join would clear a palette nobody serves.

| part | responsibility |
|---|---|
| `shell.css` | Reset, scroll behaviour, the app shell, and how its cards compose as the screen grows. |
| `summary.css` | The verdict hero, the summary card and the animated progress bar. |
| `controls.css` | Toolbar, buttons, filter chips, and the More-filters disclosure. |
| `badges.css` | Status and severity badges, and the test gate's verdict — which reuses the same pill and adds only a hue, while the observations beside it are deliberately not pills. |
| `tables.css` | The phase and bug tables. |
| `gate-rail.css` | The gate rail and its signature. |
| `empty-state.css` | What the page shows when a filter matches nothing. |
| `forced-colors.css` | Colour that must survive forced-colours mode and paper. |
| `motion-and-print.css` | Reduced motion, and forcing a light sheet for print. |
| `ready-now.css` | The ready-now list. |
| `segments.css` | Phase segments and their headers. |
| `usage.css` | The usage section: tiles, charts, heatmap. |
| `print-segments.css` | Per-segment and single-segment print rules. |

## Constraints that hold for every part

- **Every value comes from a token.** `_ui_theme` declares them once; rules reference
  `var(--…)` and never a raw colour or spacing value.
- **Never define a colour only inside a media query.** A token declared only in a
  dark block vanishes in light mode, which once shipped invisible bars.
- **`@media print` is outside the theme compiler's reach**, so a palette hard-coded
  there cannot be themed; print colours still belong in the token layer.
- **One component, one name, across both surfaces.** A rule that exists twice is a
  rule that will drift.
- **Prefer `:where()` for shared base rules** so specificity stays at zero and a
  surface override keeps winning without being made more specific.
