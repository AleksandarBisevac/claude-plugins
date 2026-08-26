# The panel's stylesheet, by feature

The parts are joined in the order `_ui_theme.PANEL_CSS_PARTS` lists and spliced into
`panel.html`'s `/*@CSS@*/` marker by `_panel_ui.raw_template()`, as a single inline
`<style>` in a page served from `http://localhost`.

**Order is the cascade.** Two rules of equal specificity are decided by which one is
read last, so this sequence is behaviour: the reset before the shell, the shell
before the views drawn in it, and every narrow-screen block after the rules it
overrides. Sorting these names alphabetically changes what ships.

The order is declared in `_ui_theme` rather than beside the assembler, because the
theme lints run at that layer and must audit the sheet in the order that ships — a
lint over a differently-ordered join would clear a palette nobody serves.

**This was a cut, not a regrouping**, and three names admit it out loud.
`usage-narrow.css` holds the usage tab's below-34rem overrides, which sit after the
tooltip in the sheet and so cannot travel back to `usage-tab.css`.
`usage-tables.css` and `overview-rows.css` are the runs their features resume in
after another feature interrupts them. A tidier filing would move a rule past
another rule, which is a cascade change disguised as housekeeping.

| part | responsibility |
|---|---|
| `tokens-and-reset.css` | The `/*__THEME_TOKENS__*/` splice point, the three panel-only colour roles with their dark twins, and the document reset. |
| `app-shell.css` | The sticky topbar, the two-column shell, the five-view nav and its narrow-screen strip, and the page headings. |
| `base-controls.css` | The primitives every view composes from: cards and rows, fields, buttons, badges, chips, tags, pill inputs and bars. |
| `usage-tab.css` | The usage tab's filter bar, active-filter chips, tiles and sparklines, line chart, legend and ranked rows. |
| `usage-heatmap.css` | The tokens-per-day heatmap: its month nav, the grid, and the level ramp built from the accent by `color-mix`. |
| `usage-tables.css` | What the usage tab resumes with after the heatmap — table cells, the one advice block, the budget burn-down, the list controls. |
| `browse-dialog.css` | The two `<dialog>`s that are a table: the browse/task table with its sortable header, model-mix cell and cost band, and the full-screen frame the capability table borrows. |
| `identity-pill.css` | Who the panel thinks you are, as a pill in the topbar rather than plain text. |
| `confirm-dialog.css` | Confirm-before-write: the old→new diff table, its footer, and the live lock note. |
| `help-drawer.css` | The side-sheet `<dialog>` that explains one setting — header, body sections, topic list, facts grid, and the paid agent footer. |
| `tooltip.css` | The one shared tooltip element moved on hover, and the uncategorised-row colour that sits inside its run. |
| `usage-narrow.css` | What the usage tab does below 34rem: ranked rows stack, the date pair wraps, and the filter bar stops pinning. |
| `settings-form.css` | The Settings and Guards form — sub-headings, field variants, the checkbox exception proofs, the sticky save bar, invalid-value dressing, the price table, the arrival flash, the rule grid. |
| `save-result.css` | How a write reports itself: the toast, the save note's lifecycle, and grouped findings. |
| `labels-and-hints.css` | A field's label row, the ⓘ that opens the help drawer, and the one `#hinttip` element on `<body>` that shows its text. |
| `combobox.css` | The custom autocomplete combobox that replaces `<datalist>`, whose menu is placed by JS, and the chip containers beside it. |
| `blocks-and-ado.css` | The Blocks view's subtabs and registry table, and the ADO card's fixed-layout stateMap mini-tables. |
| `status-colours.css` | The one place a status name becomes `--st`, and the pill that wears it — for the plan's statuses and, in the same grammar, for a recorded test run's verdict. |
| `composition.css` | The Composition view: its filter toolbar and the collapsible phase/task table where models and skills are edited. |
| `overview-filters.css` | The Overview's summary strips — a legend that is also the filter — its toolbar and group headers. |
| `appearance-table.css` | The Appearance tab's token table: name, light and dark side by side, with the native swatch and the hex field. |
| `overview-rows.css` | The Overview's expandable phase rows, task detail table, risk text, the test-evidence badge with its markers and openable run, and the ready-now list. |
| `policy.css` | The policy switchboard: the wide table that scrolls inside its own frame, the per-rule select, the verdict pill and its basis, and the honesty note. |
| `proposals.css` | Parked phases: the disclosure card, its label/value fact stack, the action row and the drop-reason field. |

## Constraints that hold for every part

- **Every part ends with a newline.** `panel-server.py` lints over
  `UI_HTML.splitlines()`; a part without one joins two lines and can hide a real
  offender or manufacture a false one.
- **Every value comes from a token.** `_ui_theme` declares them once; rules reference
  `var(--…)` and never a raw colour or spacing value. The three raw-hex roles at the
  top of `tokens-and-reset.css` are a recorded exception, not a precedent.
- **Never define a colour only inside a media query.** A token declared only in a
  dark block vanishes in light mode, which once shipped invisible bars.
- **`color-scheme` must be restated wherever a theme is chosen** — custom properties
  cannot reach it, and it paints scrollbars, `<select>` menus and date pickers.
- **One component, one name, across both surfaces.** A rule that exists twice is a
  rule that will drift.
- **Prefer `:where()` for shared base rules** so specificity stays at zero and a
  surface override keeps winning without being made more specific.
