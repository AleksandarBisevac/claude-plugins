# The panel's inline script, by feature

The parts are concatenated in the order `_panel_ui._JS_PARTS` lists and spliced
into `panel.html`'s `/*@JS@*/` marker as a single inline `<script>`. The panel is
served by `panel-server.py` over `http://127.0.0.1`, and the page it returns is
built once at import and re-substituted per request for the session token.

**This directory is a CUT, not a filing.** Each part is one contiguous run of the
old single-file `panel.js` in its original sequence, which is what makes the
assembled page byte-for-byte what it was — the whole safety argument for the split.
Substring assertions and index-bounded slices over `UI_HTML` are pinned to that
order; print how many of each before you start (`python3 tools/count-ui-pins.py`,
`--json` for a machine-readable shape). Both figures used to be written out here and
had rotted well below the live ones by the time anybody re-derived them, which is the
defect this repo's own rule about numbers in prose exists for — and the repair it
prescribes is to delete the number and keep the command, never to correct it. Some of
those slices use a COMMENT as an endpoint, which makes those comment lines
load-bearing source — print the live list rather than trusting one, because a slice
can be taken over an intermediate variable and a scan that looks only for
`UI_HTML[...]` misses it:

    grep -rn '\.index("//' plugins/audit/tests/

**Order is behaviour.** `core.js` declares `$`, `el`, `api` and `TOKEN`, which
statements further down read at load time; every top-level `const`/`let` is in TDZ
until its own line runs. `boot.js` ends with the `boot()` call. Sorting `_JS_PARTS`
alphabetically leaves every Python suite green while the page dies on the first read
of an undeclared name.

Two consequences of a cut that a tidier filing would not have, both deliberate:
`boot()` is *defined* in `write-confirmation.js` and *called* in `boot.js`, because
that is where the two statements sat; and a few widgets ride at the end of the part
they followed rather than in a part of their own (the combo menu after the help
views, the CSV export after the usage metrics). Moving either would be a regrouping.

| part | responsibility |
|---|---|
| `core.js` | The primitives every later part reads — `$`, `el`, `api`, the token-bearing `url()` — plus shared state, the light/dark paint, label lookup, tab routing and `toast`. |
| `write-confirmation.js` | Who is writing, what exactly, and whether it was recorded: the change viewer, the row-level diff of a form against the file, the caret hand-back rule, the confirm dialog, and what the server echoed back. Defines `boot()`. |
| `hints.js` | The form's shape, microcopy and enum choices as Python substitutes them; the `ⓘ` hint, the one body-level tip element it opens into, and the label builders that carry it. The autocomplete's DATA is here; its widget is in `help-drawer.js`. |
| `help-drawer.js` | The help drawer: field descriptions and concept pages from `GET /api/help`, its three views, and the combo menu widget. |
| `settings.js` | The Settings tab: the config form, its field renderers, and deep links to one setting. |
| `composition.js` | The Composition tab: model suggestions unioned from the manifest, the rate table and the ledger, plus the skill pickers. |
| `branch-convention.js` | The branch-naming card inside Composition — `meta.branch`, a FORM key, so it rides the Composition save rather than owning an endpoint. The worked example comes from Python; the expansion rule is not reimplemented here. |
| `ado-connector.js` | The Azure DevOps connector card inside Composition — API-only `meta.ado`, saved through `PUT /api/ado`. |
| `theme-state.js` | The theme draft: token values, layout and density, the undo stack, and what a save sends. |
| `appearance-view.js` | The Appearance tab: rendering the theme editor, contrast warnings, and theme export/import. |
| `run-status.js` | Who is driving which phase while you watch — the poll and the badges it owns. |
| `overview.js` | Out-of-band change handling (the file moved under you), the Overview rollup, and the recorded-test-run badges in a phase's detail — the verdict, the observations beside it, and the run a reader can open. |
| `policy-state.js` | The capability policy draft: rules, patterns, which area columns the table draws, and what changed against the server's copy. |
| `policy-view.js` | The policy switchboard's rendering: the capability table, the full-list dialog, and the per-rule cells. |
| `usage-model.js` | One usage filter state, the dimensions derived from it, and the number formatters that mirror `_fmt.py`. |
| `usage-filtering.js` | The filtered view as a link: the `#/<tab>!k=v` grammar, its stored twin, and the matching and aggregation every chart reads. |
| `usage-charts.js` | The shared tooltip and the multi-line chart with its crosshair. |
| `usage-metrics.js` | Sparklines, the metrics recomputed under the current filter, CSV export, and the bar renderer. |
| `usage-cards.js` | Phase budgets, the monthly overview, the tokens heatmap, the person header and the cost bands. |
| `browse-dialog.js` | The sortable, searchable dialog behind every ranked usage list. |
| `usage-view.js` | `renderUsage()` — the Usage tab assembled from everything above. |
| `version-banner.js` | The build serving this page against the build installed, from `GET /api/version` — a page-level notice, above the shell, and only when the two are known to differ. Self-starting and contained; no view renders it and `boot()` does not route it. |
| `boot.js` | The last two statements: the focus-obscured repair, registered inside its own guard, and the `boot()` call. |

## Constraints that hold for every part

- **No `import` or `export` today, and that is now a measured position rather than
  an inherited one.** Real cross-file ES modules *do* work over this panel's
  `http://127.0.0.1` origin — unlike the report's `file://` one, where a sibling
  import fails with `net::ERR_FAILED`. What stands in the way is not the browser:
  `panel-server.py` has no static route (a module fetch gets 403 without the session
  token and 404 with it), a relative specifier inherits the path but never the `?t=`
  query, module scripts are strictly MIME-checked, and the `__*__` placeholders
  substituted into this text would need a new home. Until that is decided, Python
  joins the parts.
- **Every top-level name shares one scope.** The parts are concatenated into one
  classic `<script>`, so a name declared in one part is visible to all of them, and
  every top-level `function` declaration is additionally a property of `window`
  (`grep -hc '^\(async \)\?function ' *.js | paste -sd+ - | bc`).
  Prefix by feature — the `u*`, `p*`, `t*`, `ov*` conventions already here — rather
  than relying on the file boundary, which is not a scope.
- **No external resource** — no CDN, font, image URL or stylesheet link.
- **Reach elements through `data-` attributes** rather than styling classes, so
  renaming a class cannot silently break behaviour.
- **A selftest cannot see a dead page.** A syntax error kills the whole inline script
  while every `'…' in UI_HTML` pin still passes, so
  `node tools/capture-screenshots.mjs --check` is what proves the panel comes up. It
  is not optional after any edit here.
