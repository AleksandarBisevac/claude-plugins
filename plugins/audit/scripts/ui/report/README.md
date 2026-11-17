# The report's inline script, by feature

The parts are concatenated in the order `_report_ui._SCRIPT_PARTS` lists, wrapped once
by that module and served as a single inline `<script>` inside a self-contained
HTML file. There is no bundler and no network: the page is opened from disk, so
every byte it runs must already be in it.

**Order is behaviour.** `page-state.js` resolves the elements and shared values
every later part reads, so it runs first; the parts after it register handlers
against state that already exists. Reordering them is not a formatting change.

| part | responsibility |
|---|---|
| `page-state.js` | Element lookups, theme preference, sticky header measurement (a layer counts only while it is actually sticky), bringing an opened More filters into view, scroll spy (it lights a section once its top reaches the scroll-margin the stylesheet gives every id, read back resolved, so a nav jump lights the section it lands on; the stylesheet's room after the content lets the last sections reach that line too, so there is no end-of-page rule), expand/collapse persistence, number formatting, the task index the filters read, and `FILTER_AXES` — every filter axis declared once, with its link keys, default, reset, painter and what it narrows, so Clear, the link, the restore and the counters iterate it instead of listing axes by hand. The registry wraps every entry's `decode` in one check (`keptFromLink`) as it is built, so a link restores only a value a control offers — read off the toggles carrying the axis's `attrs` and its `twin` select — and an axis declared with no hook is held to it; a `takes` hook is the declared exception for values that are not whole chip values (a tag list, a date, free text). The keys are published as `data-link-keys` on the root for the browser gate. |
| `filters.js` | Which phase and task rows are on screen: the filter state, the single pass that applies it, and the URL hash that survives a reload — the hash and the panel count both read off `FILTER_AXES`, and the panel count only the axes with a control inside the panel. The phase count says its view to a screen reader and draws it for nobody (`.vh`, in `report-css/controls.css`), because the View select beside it shows the view and, drawn, the name wrapped the pinned bar. The count is the bar's last item: it takes a row of its own where it does not fit beside the controls, and wraps its own words only on a bar narrower than its whole text (`#audit-count` in `report-css/controls.css`). The empty state's two buttons hide the row they sit in, so both hand the keyboard to the View select. The test gate is TWO of those axes and not one — what a task's last recorded run said, and what else was true about that run — because a gate can fail and rewrite the tree, and one control could only express their combination. |
| `sorting.js` | Natural-order column sorting, inside a phase and across the table; and which order the phase rows themselves are listed in — the written plan, or the priority ranks the server stamped on the rows, chosen by the Sort select in the phases table's head (`.tablehead`, in `report-css/tables.css`). |
| `chips.js` | The toggle-chip behaviour shared by every filter bar, including which chip reads as pressed. |
| `areas.js` | Filtering by area tag, and the counts each tag shows. |
| `authors.js` | Selecting one author and narrowing the usage tables and rank rows to them; a pick goes through the same refresh as every other filter, so it offers Clear. |
| `date-range.js` | The task table's date window: the two inputs, the relative-span presets, and clearing back to all time — plus Clear filters, which resets and repaints every axis `FILTER_AXES` declares. |
| `usage-range.js` | The same window applied to the usage charts, which read a different data source. |
| `heatmap.js` | Calendar navigation and run selection in the activity heatmap. |
| `exports.js` | Per-segment and per-section export: CSV for tables, PNG for the heatmap, printing one segment — and, for every print, cutting the phases table into one table per phase on `beforeprint` and joining it back on `afterprint`, because Chrome's renderer crashes paginating one long table across many pages. It also restores the linked or stored view before the first pass, through each axis's `decode`. |

## Constraints that hold for every part

- **No `import` or `export`.** Module scripts are fetched with CORS semantics, and a
  page opened over `file://` has an opaque origin, so a cross-file import fails with
  `net::ERR_FAILED`. Verified in Chromium, not assumed.
- **No wall-clock call.** `Date.now()` and `new Date()` make the rendered artifact
  differ between runs, which is what stops anything comparing a committed report to
  a fresh one.
- **No external resource** — no CDN, font, image URL or stylesheet link.
- **Every top-level name shares one scope.** The parts are concatenated, so a name
  declared in one is visible to all; prefix by feature rather than relying on the
  file boundary.
- **Reach elements through `data-` attributes** rather than styling classes, so
  renaming a class cannot silently break behaviour.
