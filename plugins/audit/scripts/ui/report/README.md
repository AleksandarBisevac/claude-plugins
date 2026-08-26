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
| `page-state.js` | Element lookups, theme preference, sticky header measurement, scroll spy, expand/collapse persistence, number formatting, and the task index the filters read. |
| `filters.js` | Which phase and task rows are on screen: the filter state, the single pass that applies it, and the URL hash that survives a reload. The test gate is TWO of those axes and not one — what a task's last recorded run said, and what else was true about that run — because a gate can fail and rewrite the tree, and one control could only express their combination. |
| `sorting.js` | Natural-order column sorting, inside a phase and across the table; and which order the phase rows themselves are listed in — the written plan, or the priority ranks the server stamped on the rows. |
| `chips.js` | The toggle-chip behaviour shared by every filter bar, including which chip reads as pressed. |
| `areas.js` | Filtering by area tag, and the counts each tag shows. |
| `authors.js` | Selecting one author and narrowing the usage tables and rank rows to them. |
| `date-range.js` | The task table's date window: the two inputs, the relative-span presets, and clearing back to all time. |
| `usage-range.js` | The same window applied to the usage charts, which read a different data source. |
| `heatmap.js` | Calendar navigation and run selection in the activity heatmap. |
| `exports.js` | Per-segment and per-section export: CSV for tables, PNG for the heatmap. |

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
