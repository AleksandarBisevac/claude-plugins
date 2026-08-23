# Changelog

All notable changes to the `quality-gates` marketplace and its `audit` plugin.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are the
`audit` plugin's `plugin.json` version, tagged `v<version>` on this repo.

## [Unreleased]

**The manifest layout is a choice with a name, and it goes both ways.** `/audit:layout
sharded|single-file` replaces `/audit:migrate` as the command that decides how the manifest is
stored -- an index plus one file per phase, or one file. The old name described a version upgrade,
and there was never one to do: single-file and sharded are two current shapes of one schema, a
single-file manifest does not go out of date, and installing a newer plugin never made migrating
due. The documents had already been corrected twice; the command's own name was the last thing in
the product still saying otherwise.

**`/audit:init` now asks**, at the point where the question is answerable -- after the plan is
approved, so the phase count is on screen -- and phrases it by what actually decides it: parallel
phases across separate worktrees, or a plan big enough that loading every phase to run one costs
real context, versus one session and a handful of phases. **The default is one file**, which is
what every manifest was before the question existed, so accepting it changes nothing for anyone.
Choosing sharded calls the same splitter `/audit:layout` calls, rather than hand-writing shards.

**Going back has a cost, and the command says it before it writes.** Assembling shards into one
file is not the forward path with a word swapped. It reads the index AND every shard, and those
are governed by different locks, so the index lock is not enough: a phase run holds `phase-<id>`
and writes only its own shard, and assembling underneath one yields a single file mixed from two
moments with nothing downstream to say so. `/audit:layout single-file` refuses while any `phase-*`
lock is held, names the phase worktrees and unmerged `audit/*` branches whose shard edits would
otherwise merge into a file nothing assembles, and afterwards names every shard file left on disk
-- unread, still committed, still looking authoritative -- so that `git rm` and the assembled file
land as one commit.

**`/audit:doctor` states the layout and its cost instead of nominating a fix.** The line read
`single-file layout (meta.version < 3); /audit:migrate splits it into per-phase shards`, which
turned a supported shape into a to-do every time it was read. It now names the layout, what that
layout costs (running one phase loads them all; two worktrees running phases in parallel write the
same file) and no command at all. It also stopped reading `meta.version` as the layout: the layout
is `_manifest_io.is_sharded()` -- the phase stubs -- which is the reading every writer in the
plugin already used, and the doctor held the only second copy of it. Where the stamp and the stubs
disagree, that disagreement is now a finding of its own instead of being reported as a layout.

### Deprecated

- **`/audit:migrate` is an alias for `/audit:layout sharded` and will be removed in a future
  release.** It still works and still does exactly that, kept so existing transcripts, runbooks
  and older documents resolve. When it goes, a runbook whose line says `/audit:migrate` fails at
  that line -- so anything written down is worth changing to `/audit:layout sharded` now, while
  both spellings work. No manifest is affected either way: the alias is a name, not a format.

## [0.43.0] - 2026-08-21

**A granularity that cannot differ from All is no longer offered.** The heatmap's Year and
Month buttons were dimmed-but-clickable when the whole ledger fell inside one year or one
month, which reads as broken and was reported as broken twice: pressing them repainted an
identical grid. The arithmetic was never wrong -- on a ten-day ledger, "all data", "this year"
and "this month" are the same set of hours -- so what changed is the control. The impossible
choice leaves the ladder, a selection it just invalidated is cleared, and the reason sits under
the buttons as plain text ("Year needs a ledger spanning more than one year -- this one runs
2026-04-01 to 2026-05-23") rather than as a tooltip on a control that is no longer there. Proven
against an 18-month ledger, where all five granularities draw five different grids and the
arrows step between months.

**The "N phases match outside this view" row is gone.** It offered to undo a choice the reader
had just made, next to a View select that already says "All phases". The counter still reports
`N / M phases` whenever anything is filtering, which is the same fact without the extra row; the
browser gate now asserts the row's ABSENCE and that the select still reaches those phases.

**A task's `technical` prose is trimmed to five lines**, with an ellipsis and a Show more /
Show less control -- it was pushing `model`, `skills` and `tests` off the screen. `max-height`
rather than `line-clamp`, which the Baseline snapshot lists as Limited. The control ships hidden
and the page reveals it only where the text really is cut off, because whether five lines
truncates depends on the width it is read at.

**Task details now say who did the work.** The manifest records no assignee and inventing one
would be a claim the file does not make -- but the usage ledger records an author against a
taskId on every metered turn, so `worked by` reports that instead, strongest spend first, with
`(metered on this task)` naming its basis. Rendered server-side, so it survives into the PDF and
the Markdown twin, and absent entirely when there is no ledger.

**The panel stamps the build serving it**, in the topbar beside the project path -- the same
words and the same place the report already stamps the renderer that wrote it. The plugin cache
is keyed by version, so `marketplace update` plus a reload can hand over a different build with
nothing on screen to say so. `plugin_version()` moved into `_output.py` and the report now reads
it as an alias: two surfaces stamping one fact, one implementation.

## [0.42.0] - 2026-08-21

**A control that cannot honour a choice stops offering it.** Six reports this round turned out
to be one fault wearing different clothes, and the shape is worth naming because it will
recur: two filters ANDed together, one of them offering a value the other has already made
impossible. The report's status chips offered `Pending` while the view was `Archived`, and
pressing it gave `0 / 9 phases`. The area dropdown had the same bug one control over -- found
by sweeping every control rather than by waiting for a second report -- offering an area whose
only phase the current view hides. Both now follow the view: the impossible choice is gone from
the set, and a selection the new view has just made impossible is CLEARED rather than left
pressed-but-inert, because a pressed chip filtering nothing is the same lie one step later.
Both derive their view mapping from the rendered rows rather than from a second copy of the
Python that assigns segments.

**The heatmap's granularity buttons were telling the truth and sounding like a lie.** When a
ledger fits inside one calendar year, `Year` draws the same grid as `All` -- by definition,
not by bug -- and the arrows are dead because no neighbouring period holds data. All correct,
and none of it said out loud, so three buttons drew one picture and two arrows did nothing. The
arithmetic is untouched; what changed is that a degenerate granularity is now dimmed and says
why, a dead arrow gives its reason, and the period line adds `the whole ledger falls in this
month`. A heatmap cell also stops handing its datum to the OS: `cursor:help` drew a question
mark over every cell including the empty ones, and the number arrived a second later in a
native tooltip. The cell now uses the panel's own tip layer through ONE delegated listener --
the report had already settled this for a larger grid -- and the timing is a group warm-up:
the first hover waits, every later one is immediate until the pointer leaves the heatmap.

**An unsaved setting says which one it is.** The Guards savebar counted (`Discard 1 change`)
while nothing on the form marked the field, so the count's basis was a click away in the
confirm dialog -- and the Policy tab next door had been marking its pending cells inline all
along. Two surfaces disagreeing about whether a claim shows its basis is the thing to fix, so
the edited field now carries the same `pend` vocabulary Policy uses plus an `unsaved` badge (a
word, not only a colour, so it survives forced colours). Writing that gate found an older bug
behind it: `onViewEdit` fires on the Save *click*, before the write resolves, so the last thing
it ever computed was the state just before the save -- which left **Discard offering to throw
away a change already on disk**. Both are fixed by one named read that the save path also
calls.

**Author joins the report's filter bar**, with its limit stated rather than implied: it scopes
the Usage section's per-author views and cannot filter phases, because tasks record no author
to filter by. A plan with exactly one author gets a line naming them instead of an inert
one-option dropdown.

**The ADO conformance gate checks the shape before it grades the substance.** Handed the output
of `az boards work-item show` -- the most available JSON anyone has, and the flag is called
`--item` -- it used to half-read it: `fields` matched, so the tag rules really ran, while `type`
and `parent` live elsewhere in that shape, so `requireParent` fired on an item that HAS a
parent and the answer was a confident `DOES NOT CONFORM: do NOT create this item` about a
correct, long-existing work item. A fetched payload is now refused as a usage error (exit 2)
naming what gave it away, never exit 1 -- a 1 means the item does not belong on the board, and
saying that about a payload we could not read is the confident wrong answer the gate exists to
prevent.

**And a board standard that contradicts the connector is named when it is written, not at
push time.** `meta.ado.tag` defaults to `audit-plugin`, which carries no prefix, so a
`tagVocabulary` admitting only prefixed tags refuses every item the connector creates -- and
the manifest validated clean, because each block was graded alone. Same for `requireParent`
with no `parentWorkItem`: the top of the created tree has nothing to hang under. Both are now
warnings from the one front door every surface already shares, so the validator, the doctor and
the panel's ADO card report them without three copies of the rule. Warnings rather than
findings on purpose: once every item is linked a push does only updates, the gate runs on
CREATE alone, and the contradiction lies dormant -- calling that setup invalid would fail a
working config's CI on upgrade.

## [0.41.0] - 2026-08-20

**The two surfaces stop being two codebases.** A `ui/shared/` layer now exists and holds
the rules that had been retyped into both -- a blob download whose four copies had drifted
to three revoke policies, fourteen hand-written storage guards, one agreement rule for a
count and its noun, one day-in-milliseconds constant, the clipboard's two failure paths, and
the heatmap calendar that had existed twice under the same names for as long as both heatmaps
have. `report.js` speaks the same modern dialect as the panel for the first time. And the
duplication is no longer a matter of anyone remembering: `_deps.SHARED_CONCERNS` is a
register with a home, a needle and an allowance per concern, and it fails the build when a
row spreads past its cap.

Twenty-nine fix commits landed against the panel and the report, most of them reproduced in
a browser before anything was written. Several were the same shape: a claim on screen that
the code had not established.

### Added

- **`ui/shared/`** -- `download.js`, `storage.js`, `plural.js`, `dates.js`, `calendar.js`,
  `clipboard.js`, joined into BOTH surfaces ahead of every part that reads them. The
  promotion rule is one reader stays put, two readers move up, and a shared part may not
  reach back into a surface -- which is what decides how high a helper's own primitives have
  to sit. Its `README.md` carries the rule, the four wiring steps and both feature gates,
  because the previous phrasing "anything both surfaces need goes in the shared layer" was
  in force while fifteen rules were retyped: it named a directory that did not exist, so
  complying meant inventing it and retyping was one edit.
- **`_deps.SHARED_CONCERNS`** -- twelve rows, each with the file that owns the concern, a
  needle (substring or `re:` pattern), an allowance and a reason. It is a CAP, never an
  equality, which is the whole difference between it and the three save/discard counts it
  replaced: those required the duplication to stay, so removing a copy turned them red.
  Two rows carry a declared residual and say what it is.
- **`tools/find-shared-candidates.mjs`** -- a scout that reads the assembled sources and
  reports repeated windows across files. It found the table-header duplication that five
  agents had read past, and after each extraction it surfaced the next-largest one, which is
  the argument for running it again rather than once.
- **A harness that grades its own coverage.** `tools/check-report-interactive.mjs` derives
  the set of assertions it declares from its own source and refuses to report success for
  work it did not do; the floor is never written down as a number, because a constant there
  would rot on the first added check.
- **`/audit:sync` learns a board's standard** -- the ADO connector reads what the project's
  board actually uses rather than assuming, and nested ADO vocabularies now answer to the
  schema.

### Fixed

- **One broken view took the whole panel, and then blamed the load.** `boot()` ran seven
  view renderers, the initial-tab restore, the run poller and the tip placement as a single
  sequence of bare calls. A throw in any one of them -- a malformed ledger reaching the usage
  view is the realistic one -- skipped every later view, the poller and the tips, and the
  outer catch then reported "load failed" about the one thing that had not failed. Each step
  now runs contained, and what a reader gets is the parts that are missing, by name.
- **Closing the Appearance tab discarded an unsaved theme, silently.** Every other writable
  surface registers a way to ask it what is unsaved; the theme card registered nothing, and
  its draft lives in memory only. It is the one surface whose Save has no Discard beside it,
  on the grounds that it offers an undo trail instead -- and an undo trail does not survive
  the page.
- **The Appearance pill said "unsaved" about a number that was not.** It counted the theme
  minus the shipped default, so a project wearing any theme opened claiming changes nobody
  had made. The pill, the out-of-band repaint and the save now count one set.
- **Every density or card-order save reported "not exactly what the dialog listed."** The
  change row's field read `layout · density · ` against the server's `layout · density` --
  two characters, invisible on screen, and the applied-diff keys on that field. A separate
  version of the same fault made every FIRST-TIME token edit report drift, because the panel
  showed the value on screen while the server reported the raw file entry.
- **A caret resting in a clean Composition field froze the live view.** The disk refresh and
  the deferral that holds it back each worked out which views hold unsaved edits, and
  disagreed about the ADO card: the refresh folds it into `#comp` and the deferral did not.
  One map answers both now, and the CSS selector is derived from its keys rather than typed
  a second time.
- **A malformed policy list blanked the Policy tab**, and the rule lookup matched a
  serialised list rather than a name.
- **The theme's undo trail could not express a clear**, so Redo re-applied the value Undo had
  just put back; and a clear that changed nothing counted as one unsaved change.
- **Numbers that disagreed with the Python that renders them elsewhere.** The panel's token
  formatter rounded where Python truncates. The contrast checker graded four pairs against
  Python's six. `plural(1.7, "task")` rendered `1 tasks`, because `%d` truncated while the
  agreement was decided on the raw value. `share_pct` let a NaN whole through -- NaN is
  truthy in Python -- and `fmt_share` rendered it `nan%`. Each is now held equal by a
  differential test that asks live Python, and the NaN case is pinned on both sides
  separately because JSON cannot carry it between them.
- **The panel said "1 task(s)".** Two competing conventions for one job, thirty-one sites;
  six of them put a count in front of a clause whose verb agrees too, which the literal
  `(s)` could never express -- "1 task(s) are blocked", "1 linked item stay frozen".
- **A focused control could land underneath the chrome pinned over it** (SC 2.4.11).
  Measured before anything was written: 85 of 942 focus stops across six tabs and two
  viewports were entirely covered.
- **SC 2.5.3 Label in Name: six failures, measured, now none** -- and the tooltip-only ⓘ was
  a focusable element that announced nothing (SC 4.1.2). Both are gates now rather than
  probes that vanish.
- **Reading the help edited the setting it explained.** Opening a field's explanation wrote
  to the field. Gated.
- **`--help` was treated as a filename and `--json` stopped being JSON** in `/audit:status`
  and `/audit:doctor`.
- **The shipped example carried the accessibility bug the plugin had already fixed**, because
  nothing compared a committed artifact against what its source would now produce. It is
  compared on every run now, which is what caught this release's own artifacts drifting.

### Changed

- **The assembled UI is parts, not four big files.** `panel.js` became twenty-one feature
  parts, `panel.css` twenty-three, the report's script ten and its stylesheet thirteen --
  every cut order-preserving and proven byte-for-byte identical, because the statement order
  is a machine-checked contract and a "logical" regrouping would break it.
- **The report's inline script is a `<script type="module">` and the file-spanning IIFE is
  gone.** A module's own scope is what keeps the parts' top-level names off the page.
  `import` between parts remains impossible on an opaque origin, which is why Python still
  does the joining -- the experiment that measured this is recorded in the decision record,
  along with the two claims it disproved.
- **One dialect.** `report.js` had been ES5 with `var` and hand-rolled DOM assembly against a
  modern panel, undocumented drift rather than a compatibility decision. Zero `var`, zero
  `function ()`, and JSDoc on every function across both surfaces -- with concrete types,
  never `{Object}`.
- **A theme save's change rows carry `target`, not `scope`.** Both sides spelled it the way
  nothing else in the protocol does, so the confirm dialog printed a blank target cell and
  the phase lookup collected a null for every theme row. Journal entries for `theme.save`
  record the new key.
- **`/api/theme` no longer sends a `presets` field**, which nothing read and which contradicted
  the reasoning two lines below it in the same payload.
- **Published counts in the documentation are gone, and the command that prints them stays.**
  Six figures in one table were wrong at once, twice over. A number carrying its command is
  legal here; only deleting the number stops it rotting.
- **`tools/capture-screenshots.mjs` pins its scratch root.** It read `TMPDIR`, so one host
  under two environments painted two different paths into the topbar the panel photographs --
  and fifteen committed PNGs "changed" for that reason alone.

## [0.40.0] - 2026-08-19

**The panel's dropdown stops running away, the report's table starts answering — and
`scripts/` stops being one flat pile.** Five dogfooding findings, each reproduced in a real
browser before the fix; then a restructure that moved all 48 `--selftest` blocks out of the
modules they test, grouped `scripts/` into domain directories, and gave JavaScript its first
unit test — which immediately found two formatters printing different numbers from the CLI.

### Fixed

**The panel and the report commit to WCAG 2.2 AA, and the criteria were measured before
anything was written.** Of the 55 AA criteria, 19 are N/A here; of the 36 that apply the
panel conclusively met 15 and conclusively failed 8. Every fix below was reproduced in a
browser first and re-measured after -- none of them was read off the stylesheet.

- **Two cases in the raw-URL pin lint went green by measuring nothing at a release.**
  `test__refs.py` spelled `v0.39.0` and `0.40.0` as literals in its own mutations, so
  cutting 0.40.0 turned p4's `replace()` and p6's "bump" into no-ops -- the two cases that
  exist to catch a stale README pin would have passed at the exact moment they were needed.
  Both now read the shipped version instead of naming it, and p6 bumps to a version that
  cannot collide with one.
- **A focused control could be activated but not reached, and the gate was reading a dead
  property** (SC 2.4.3, 2.4.7). The four Discard buttons carried native `disabled`, which
  removes the tab stop, so the caret landed on `BODY` after a discard. They now carry
  `aria-disabled` and keep their stop, with **one capture-phase guard** refusing activation
  for anything claiming it -- because `aria-disabled` is a promise the platform does not
  keep. `tools/capture-screenshots.mjs` read `.disabled` at **six** sites rather than the
  four this was expected to touch, and one of them (`[data-discard=policy]`) asserted a
  button is *not* dead: it would have passed vacuously for the rest of time.
- **A clipped name had no keyboard path** (SC 1.4.13). The report's `.rank` rows became tab
  stops (11 on the shipped report) and the hover layer grew `focusin`/`focusout` plus a
  `placeAt()` that positions from the element's own rect -- `place()` read `ev.clientX`,
  which a focus event has not got. Escape dismisses, and every close funnels through one
  `hide()`. The negative meant to guard this had been scanning the whole 190KB page and
  asserting nothing.
- **Contrast is a token problem, and one palette was not in the token layer** (SC 1.4.11).
  The control boundary measured **1.23** against the card surface and **1.10** against the
  page where 3:1 is required -- a field a sighted reader finds by habit and a low-vision
  reader does not find at all. Repaired with a `--field-border` token rather than per-rule
  colours; the palette that sat outside the token layer is why this had been missed.
- **Three tables named neither axis** (SC 1.3.1). The ADO connector's phase / task / bug
  stateMap grids are one builder called three times, and every cell was a `<td>` -- so the
  checkbox in row three announced as "never" with nothing saying never *what*. The manifest
  status is a `<th scope=row>` now, and a clipped `<thead>` carries the column names because
  their legend already sits in the label above each grid. Two browser-only consequences no
  substring pin can see: `table-layout:fixed` takes its column widths from the **first row**,
  which is now the header row (90 / 682 / 67 CSS px with the rule naming `:is(th,td)`, an
  even 280 / 280 / 280 without it); and Chromium folds `text-transform` into the computed
  accessible **name**, so the uppercase meant for painted text had the three headers
  announcing as "MANIFEST STATUS".
- **The i was a `<button>` inside the `<label>`, so the `<label>` named the i** (SC 1.3.1,
  3.3.2, 4.1.2). A `<button>` is a labelable element, and HTML resolves a label's control to
  its *first labelable descendant*. Measured over `element.labels` across 2335 fields:
  **20 fields on the Guards tab bound no label at all** and announced their own value --
  `"docs/audit/audit-plan.json"` where "The plan" was meant, `"80"` for "Free first touch,
  in lines" -- and three `<select>` announced nothing whatever. `closest('label')` reports
  all 20 as labelled and always did, which is why a pass dedicated to labels had missed it:
  the defect is not in the text, it is in what the browser does with the text. The `<label>`
  now holds the words and points at the control by id, with the i beside it as a sibling.
  **17 of the 20 are repaired**, and the six checkboxes that already bound a label lost the
  i's own name from theirs ("Meter token usage usage.enabled What is Meter token usage?").
- **A placeholder is not a name** (SC 3.3.2, 4.1.2). A placeholder is the accessible name of
  last resort and is gone the moment a character is typed, so a field labelled by one is
  nameless exactly while it is being used. 38 `aria-label`s, each written where no visible
  text names one field, each folding in the row's own id, and each still containing the
  visible word so SC 2.5.3 holds with it. At this release: **334 visible fields, 0 with no
  programmatic name.** The exemption table that had recorded 20 of them as already labelled
  is re-grounded on the explicit `for`-by-id association -- it previously verified that a
  source construction was still present, which stayed true throughout the defect, so it could
  not have failed.

- **The panel's Usage tab pushed the whole page sideways on a small phone** — 49px of it at
  320px, and anything narrower than 369px was affected. Two independent causes, both now
  repaired: the risk/model table is 332px intrinsic and sat in a card with **no scroll frame**,
  unlike its monthly twin; and the date-range pair does not wrap, so it kept a 313px line inside
  a 305px box. The dates now wrap below 34rem — a different layout, which beats a broken one —
  and the table is framed, with the 34rem minimum that frame carries scoped to the monthly table
  by a hook it already had, so the smaller table does not start scrolling at every width to fix
  an overflow that only existed below 369px. The rule's own comment said *"Measured at 390px"*,
  which is the whole bug: the 320px assertion that should have caught it only ever ran on one tab
  of five.
- **The composition dropdown flickered, moved the layout, and could not be clicked with a
  mouse** (F-P-1). Four causes, one report: `tr.phase:hover>td` carried a `filter`, which
  makes that cell the containing block of every `position:fixed` descendant — the phase
  row's model menu jumped ~550px on hover and grew the table's scroll box, and because
  hovering the MENU counts as hovering the row, it fled from under the pointer. The menu is
  now ONE element on `<body>` (the `#hinttip` rule, applied to the second overlay this page
  has), so no ancestor can trap, clip or restack it. Beside it: a mousedown on the menu's
  own padding, footer or scrollbar no longer blurs the input and closes it; a click on an
  already-focused input reopens the menu; and the 5s disk refresh — which fires after every
  Claude turn in the project, because the Stop hook meters the ledger — now defers while a
  menu is open or a caret sits in a clean form, exactly as it already deferred for an open
  dialog.
- **A read-only one-liner was refused as a source write** (F-P-7, reported from a live
  repo). `guard-secrets-read`'s eval-write backstop looked for a write-shaped fragment and a
  source-looking path *anywhere in the same clause*, never checking they were the same thing
  — so a `>` inside the code (`len(x) > 3`, or a redirect into `/tmp`) paired with the quoted
  name of the file being **read**, and `python3 -c "json.load(open('x.json'))…"` was blocked.
  The pattern now captures the path each write call actually names, and only that path is
  graded; the bare redirect left this heuristic entirely, since a shell redirect into source
  is the other backstop's grammar and duplicating it here is what produced the false
  positive. A guard that fires on reads teaches people to route around it, which costs more
  than the writes it catches.
- **Spend with no plan behind it read as `--`** (F-P-2). The ledger's storage keys (`--` for
  a row with no phase/task, `unattributed` for the attribution bucket) reached the screen in
  four different spellings across the panel, the report and the CLI. One word now, from the
  shared label map — **Uncategorized** — in the panel's ranked lists, browse table, chart
  legend, crosshair, filter chips and attribution select, in the report's HTML and Markdown,
  and in `/audit:usage`; the panel paints it in the warn role so a reader can find how much
  of the bill has no plan behind it. Storage keys, the `--attr unattributed` selector and the
  CSV are untouched: a file that is parsed is not a surface that is read.
- **`/audit:status` and `/audit:task add` disagreed about a cancelled blocker.** One tested
  "is it done", the other "is it done **or** cancelled" — so the same manifest gave a task
  blocked by cancelled work two answers depending on which command you asked. `cancelled`
  arrived as the second terminal state and one call site never followed it. The rule now has
  a single home, and the two commands that each declared it — plus the one that disagreed with
  both — all read it from there.
- **`/audit:status` died on a malformed blocker reference.** `blockedBy` is unvalidated input
  on the one surface whose job is to *render* a manifest the validator has already faulted
  rather than refuse it, and two different shapes killed the command outright: a non-hashable
  entry crashed inside the id lookup, and a non-string one survived the lookup only to die
  building the column. Both now appear in the "waiting on" column as what they are, and count
  as unmet — a ref naming no task can never be satisfied. Shown rather than dropped, because a
  quietly blank column would hide which entry is broken, which is worse than the crash it
  replaced.
- **The browser's numbers disagreed with the CLI's and the Markdown's, in two ways.** 6,375
  lines of JavaScript had no unit test: everything checking the front end was either a Python
  substring pin (which reads TEXT) or a browser drive (which needs the whole artifact), and
  neither can call a function with an argument — which is how both of these lived. The panel's
  `uTok` **rounded** where `_fmt.fmt_tokens` and the report's `fmtTokens` **truncate**, so 2.6
  read as `3` on the Usage tab and `2` on every other surface. And every `toFixed` in both
  files broke an exact tie **away from zero** while Python's `"%.*f"` breaks it **to even**:
  1,250 tokens at one decimal painted `1.3K` where the Markdown said `1.2K`, a cost of `0.125`
  painted `$0.13` against `$0.12`, and a 25-of-1000 share painted `3%` against `2%`. Both files
  now round through one helper whose tie test is exact rather than heuristic — a double is a
  dyadic rational, so `x` is a tie at `dp` places exactly when `x·2^(dp+1)` is an odd integer,
  while the obvious `n*10^dp === Math.round(n*10^dp)` misclassifies most values because that
  scaling is not exact — checked against exact rational arithmetic over 141,930 (value, dp)
  pairs and 199,910 random bit-pattern doubles with 0 mismatches. **No number in the shipped
  example moved**: the demo's own 405 token values and 276 cost values replay through both
  implementations with 0 differences, because that ledger holds no fractional token and no
  exact tie. Other data will. One divergence was pinned as its own case rather than folded in,
  where it would have read as the fix failing: JS `(-0).toFixed(1)` is `"0.0"`, Python's is
  `"-0.0"`.
- **A release gate's verdict depended on whether a mouse was plugged in.**
  `capture-screenshots --check` failed on macOS with `combo(a): the menu sits at 632,1012 for
  an input whose bottom/left is 628,1026` — and the menu was where it belongs. `place()`'s
  clamp had deliberately pulled it 14px left so its right edge landed flush on the viewport
  gutter, which is the clamp's entire purpose, while the assertion demanded unconditionally
  that the menu sit under its input. It failed on one machine because `scrollbar-gutter:
  stable` resolves from the host's scrollbar model — classic metrics put that input at 1011,
  overlay metrics at 1026, and macOS flips between them with whether a mouse is attached — and
  the passing state had been passing by one pixel. The fix is not a wider tolerance: a bound
  loose enough to accept this would have to accept a 14px misplacement. The check re-derives
  the clamp from measurement instead (legal if the menu is under its input, or flush against a
  gutter it could not have avoided), and the scrollbar model is now pinned at launch, which
  retires the class for all 5,600 lines of geometry assertions rather than this one instance.
- **`.claude/settings.local.json` was ignored by one developer's global git config, not by this
  repo.** Claude Code writes that file itself and it accumulates whatever paths a developer
  happened to allow — in this checkout, paths into a private sibling repo. `git check-ignore
  -v` named the reason as a personal `~/.config/git/ignore`, and `git show HEAD:.gitignore`
  contained the pattern zero times: the file was invisible on exactly one machine and
  untracked-but-offerable to `git add .` on every other. The repo carries the pattern now,
  verified in both directions with `GIT_CONFIG_GLOBAL=/dev/null`.
- **A share whose total was zero printed a number anyway, and a real slice under one percent
  printed as `0%` or `1%`.** Five sites carried `tot["tokens"] or 1` as though it were a divide
  guard: run verbatim, a part of 5 against a true total of 0 renders `500%`, and 0 of 0 renders
  `0%`. That does not prevent a wrong answer, it manufactures a large one. `_fmt.share_pct`
  returns None when the whole is zero and `fmt_share` renders a caller-named `?` instead — a
  share that could not be computed is not a share of nothing — and the usage sparkline, which
  drew a flat baseline under a y-axis labelled `1` when every value was zero, now draws
  nothing. Two of those sites are reported as **latent** rather than claimed as fixed: their
  whole is a max over the parts, so a zero peak forces every part to zero and the fabricated 1
  and the honest guard render identically (`width:0.0%` either way) — restoring `or 1` there
  turns nothing red, which is said plainly instead of dressed up. At the other end of the same
  rule, shares now carry the `<1%` floor `fmt_cost` already gives money ("$0.00 reads as
  free"), applied per site rather than everywhere: a share that stands alone as a claim floors,
  a share printed beside the two numbers it was divided from does not, and a percent CHANGE is
  not a share. The one visible instance in the shipped example is the other branch of that rule
  — `share 1%` for a row at 655,243 of 93,126,797, i.e. **0.7036%**, rounded UP past one
  percent — and the example and `docs/index.html` were re-rendered so the published demo stops
  showing it. The floor recovers `[0.05%, 1%)` and not everything, because `_usage_analytics`
  rounds every rate to one decimal before it arrives; that limit is in the docstring rather
  than left to be discovered.
- **A repeated `area` tag drew two chips in the HTML report and one on every other surface.**
  `_report_html._areas_of` was the PRE-FIX copy of `_areas.areas_of` — no trim, no dedupe — and
  still live, so `"area": ["api", "api"]` rendered twice and `[" api", "api"]` rendered twice
  in two different spellings. The two branches of one expression disagreed with each other, at
  that: `render-report._phase_rows` fed `data-area` from `/audit:status`' already-canonical
  value on the main path and from this copy on the fallback. The duplicate is gone, and the old
  case turns out to have pinned the WRONG behaviour — `["a", 1, "b", None]` is the one input on
  which the two implementations agreed, so a green selftest had been protecting the defect.
- **The panel's "my spend" filter compared against the identity it saw at startup.**
  `_VIEWER_CACHE` was populated once and never expired, and the panel runs for hours: change
  `git config user.email` mid-session and it kept answering with the name it first saw — a
  silently wrong answer, not a failure. The cache token is now built by the resolve itself
  rather than guessed beside it, from `git config --list --show-origin --name-only`, so the
  `includeIf "gitdir:…"` file that actually decides the answer is watched (and `--name-only` is
  load-bearing, since a plain `--list` prints every VALUE too). The environment is pinned by
  value rather than by stat, because no stat can see `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n` or a
  moved `HOME`. Deliberately not a TTL: 16 watched paths revalidate in 0.05 ms against a 30 ms
  resolve, so a window short enough to be honest buys nothing.
- **Two hooks rewrote a shared file through a fixed temp name, and one Edit fans out to seven
  hook processes.** `append_gate_event`'s self-trim and `guard-capabilities`' `_mark_seen` both
  wrote `path + ".tmp"` and then `os.replace`d it, so concurrent hooks opened, truncated and
  renamed the same name. Reproduced rather than reasoned about: 12 processes × 400 rounds gave
  **1,773 corrupt reads out of 4,800** for the gate log — empty or torn — against 0 out of
  4,800 after, and a controlled A/B on the capability marker gave 1,167 out of 4,800 against 0.
  The damage was invisible from outside: a bare `except` swallowed the `FileNotFoundError` and
  `/audit:doctor` read a truncated marker as "the matchers never reach this hook", while the
  docstring directly above the gate-log bug claimed the rewrite was "atomic on POSIX and
  Windows alike", so a reader had no reason to look. `atomic_write_text()` owns the shape now
  (`mkstemp` in the TARGET's own directory, `os.replace`, `finally` cleanup) and it RAISES,
  with the fail-open boundary kept separate rather than tangled into it. Its `tempfile` import
  stays inside the function — a cold `import _config` goes 18.2 → 23.1 ms median over 40 runs
  with it hoisted, times seven processes, on every tool call — and a subprocess case pins that,
  so a future hoist to module scope goes red instead of quietly costing 34 ms per Edit. Beside
  it, `remind-tdd` created `.claude/state/` with a bare `mkdir` instead of
  `_config.ensure_local_dir()`, so it never dropped the `*` ignore marker and `/audit:doctor`
  then reported the plugin's own directory as a hygiene finding.

### Added

- **A responsive contract over 21 widths, on both surfaces.** The widths are derived from the
  `@media` rules the two stylesheets actually declare and bracket each one — 544/545, 640/641,
  832/833 (the largest single change either sheet makes), 1120/1121 and 1152/1153 for the nav and
  shell breakpoints that already disagree by 32px — plus 320, 390 and 688 for A4 portrait inside
  the print margin. At every rung: no horizontal document scroll, nothing outside its own frame,
  no control buried under another (asked as a hit test at both ends of the document, since chrome
  you can scroll away from covers nothing permanently), and nothing clipped past reading with no
  `title` anywhere in its ancestry to reach the rest. **Every check carries a vacuity guard**,
  because the assertion this replaces did not: the old 320px check ran on one tab of five and was
  green for its whole life. The ladder is defined once and imported by both tools — two lists
  drift, which is how the nav and shell breakpoints came to differ in the first place.
- **A lint against published fetch instructions rotting.** `raw_url_pin_drift()` refuses a moving
  ref in any runnable fence — `main` moves, a raw URL has no deprecation window, and a layout
  change here becomes a silent 404 in somebody else's CI — and requires the plugin README's pin to
  equal `plugin.json`'s version, which turns red at exactly the moment a release bumps one and not
  the other. Scoped to executable fences on purpose, so schema identity URLs are never touched.
- **`cancelled`** — a fifth lifecycle state for phases and tasks, and the second TERMINAL
  one. A phase can finish without being done: the feature was dropped, part of the work
  landed, the phase closes. It is the phase/task twin of a bug's `wontfix` (Linear's
  Canceled, Jira's Won't Do, GitHub's closed-as-not-planned, ADO's `Removed`, which
  `/audit:sync` now maps it to). Nothing is deleted to express it; readiness treats a
  cancelled blocker as settled so a plan cannot deadlock on work nobody will do; sign-off
  accepts a phase whose tasks are done **or** cancelled; the report files it under Archived.
- **A named View on the report's phases table** (F-P-4) — *active & pending* (the default),
  *archived* (done **and** cancelled), *all* — replacing the archive toggle nobody found. A
  search that matches rows the current view hides now says so and offers the one press that
  shows them, instead of silently lifting the gate. The view and every filter survive a
  reload, including over `file://`, where the URL fragment cannot be written.
- **A detail row per task** (F-P-4): the compact row keeps id, title, status, risk, commit
  and completion; opening it shows the parts a table cannot hold — the full outcome (both
  voices, untruncated), both timestamps, the area owner, the branch, the work item, the
  model, the skills and what the task waits on. Model, outcome and ADO left the compact row
  for it, so rows are one line again; the CSV carries every column either surface shows,
  plus the full sha and full ISO stamps.
- Table details the eye was doing without: the **sort marker on the column the table is
  already sorted by** (it used to appear only on the first click), **risk as coloured text**
  rather than a second pill competing with status, **one press that copies the whole commit
  sha**, completion **to the minute with its zone named once**, and per-phase **"N blocked" /
  "N cancelled"** counts.
- **The panel's Overview follows that table** (F-P-5): the same three views, the same
  archive rule, the same sentence when a match falls outside the view — and a phase row now
  **opens in place** with its tasks in the report's own columns. Clicking a phase used to
  jump to Composition, a tab for editing tasks and models; that is now a named button inside
  the detail rather than what a click happens to do.
- **An Appearance tab, and themes as data** (F-P-6). The panel and the report share one token
  layer, so the look is editable without touching a rule: a theme is token VALUES in a
  DTCG-shaped JSON file, and the server compiles them into the stylesheet when a page is
  served. The CSS is never stored and never uploaded, and a theme may set values and nothing
  else — no rule, no `url()`, no `@import` — because a report is a file that gets emailed and
  published. The default theme is read *out of* the shipped stylesheet and compiles back to it
  **byte for byte**, so installing this changes nothing on screen until a token changes.
  Colours are edited in light/dark pairs side by side (the parity lint refuses a colour that
  exists in one theme only), the column you are viewing is marked *previewing* and repaints as
  you type — the panel is the preview — contrast is measured and warned about but never
  refused, and the chart palette opens behind a deliberate unlock because it is validated for
  colour-vision deficiency against these surfaces. Three ways back: revert a row, undo a step
  (the trail rides the file, so it survives a reload), or reset, which removes the theme file
  rather than writing one that equals the default. Resolution is project
  (`.claude/audit.theme.json`, committed, so a team shares one look) → `~/.claude` → built-in,
  with `ui.theme` overriding the search. Reports render wearing the same theme.
  Beyond colours: **density** (one multiplier over the spacing scale; type follows at a third
  of it), the shell metrics as ordinary tokens, and a per-view **card order** moved with ↑↓ —
  a card the theme never heard of keeps its place, so an old theme cannot hide a new card.
  **Save as…** keeps a named copy in `.claude/themes/` and wears it; the theme menu lists the
  built-in beside everything saved there, and switching is a one-key config edit.
- **`/audit:task cancel <id> --reason "<why>"`** — the verb that sets the new state. It
  records the three things a hand-edit loses: the reason (into `outcome.descriptive`, or the
  phase's `summary`), the moment, and a `task.cancel`/`phase.cancel` journal row. Cancelling
  a phase releases its claim and cascades to the work still open inside it, because a pending
  task under a dropped phase is a task `/audit:next` would otherwise still offer. A blank
  reason is refused, and terminal work is never re-decided by the verb.
- **An expand control on the panel's capability table** (F-P-3): one press gives it the
  whole viewport, built by the same builder the tab uses (one filter, one set of rows), with
  Esc handled on the dialog so a search box cannot swallow it.
- **`--bench` on `render-report.py` and `_usage_analytics.py`.** There was not one
  `perf_counter` or benchmark in the tree, and yet several comments carried hard numbers, so
  no timing claim here was checkable and no regression would have been caught. It reports the
  minimum of N runs (timing noise is one-sided, so the mean measures the machine's mood) at
  three ledger sizes (a flat per-row cost is the only thing that separates linear from
  quadratic), phase by phase for a whole render. Deliberately **not** a CI threshold — a
  shared runner's noise floor is wider than the regressions worth catching. `--selftest`
  beats `--bench` in either order, so the per-file sweep can never become a benchmark run.
  First findings: everything is linear and already fast enough that tuning it would be
  pointless (~68 ms for a full pass over an 8,740-row ledger, ~74 ms for a 1,000-task
  report), and two long-standing comments were wrong — `aggregate` runs six times per report,
  not eleven, and the ledger pass leads the HTML build by 2.4×, not the "roughly 6×" that had
  been repeated without ever being measured.
- **A lint that every referenced script path must exist.** The commands, the reference prose,
  `ci.yml`, both READMEs, the guide, the schema descriptions, `tools/`, the examples and the
  dogfood manifest carry 158 references to `plugins/audit/{scripts,hooks}/*.py`, and not one of
  them was verified: `validate-manifest` checks `fileIndex` against task `files` bidirectionally
  and never stats the filesystem, and the guide's enumeration lint matches by BASENAME, so a
  section heading keeps passing after its file moves. A trial `git mv` broke eleven references
  with nothing red — one of them a path `hooks/require-plan.py` resolves at runtime, inside a
  blocking gate. `_refs.missing_references()` now stats every one, and the case that matters
  most is the anti-vacuity one: point the tree at an empty directory and all 147 checked
  references must report missing, because a lint that returns `[]` from having looked at
  nothing reads exactly like a clean tree. `tool_basename_drift()` covers the half no per-line
  regex can see — `tools/` spells its paths as `path.join(SCRIPTS, 'panel-server.py')`, nine
  sites that would have failed at RUN time rather than lint time — and its limit is stated
  rather than implied: it catches a rename or a deletion, never a move, because a tool that
  resolves by basename is genuinely unaffected by one.
- **JavaScript has unit tests, and CI runs them.** `tools/ui-tests/` on vitest, wired into the
  one job that has both Python and Node, because a suite that runs only when somebody types the
  command is barely a gate. `node --check` per assembled part rides along and catches the class
  that kills the whole inline script while every substring pin stays green. The first suite
  found the two formatting defects above. The new rounding helper exists twice — `report.js` is
  ES5, `panel.js` is not, and there is no build step to share it — so the copies are held equal
  BY A TEST over 5,410 generated rows, 1,608 of them exact ties, with an anti-vacuity case
  asserting the table really does contain rows where native `toFixed` disagrees; without that,
  a helper that returned its input unchanged would pass everything else. A comment claiming the
  two copies match is exactly what was false before.

### Changed

- **`panel.css` spacing moved into the token layer, which makes it density-responsive.**
  77 lines, **107 -> 226** `var(--sp-*)` references. Nothing about the default rendering
  changes: expanding every token back to its declared literal reproduces the previous line
  byte for byte across all 1063 lines, 0 exceptions. The consequence is the other two
  densities -- 119 declarations that used to hold still are now scaled by `layout.density`
  (compact .8, roomy 1.25), and the target-size register records default-theme measurements
  only. **72 literal rem values remain** in padding/margin/gap declarations, so this is a
  step in the migration rather than its end.
- **`_panel_state.py` 1594 -> 414, split six ways**, and `_usage_analytics.py` split on its
  own six markers. The blocker was never `_stamp`/`_settled` but `_cores()`'s positional
  four-tuple, which bundled `_manifest_rules` with three modules that have nothing to do
  with it. Differential: **0/289 probes differ**, on a corpus whose harness catches 39/39
  planted mutations, with `UI_HTML` sha256 unchanged.
- **The browser dialect is decided: modern ES, and still no build step.** `report.js` is
  strictly ES5 and `panel.js` is modern, so the same feature exists twice and cannot be
  shared -- two `isDark()`, two tooltip placers, two CSV quoters, and two token formatters
  that already disagree while both claiming to mirror the same Python function. ES modules
  stay impossible here (the opaque `file://` origin), but that restricts *loading*, not
  syntax. The decision takes effect for new code immediately; the rewrite waits behind the
  pin migration, because the pins assert text.

- **BREAKING — `validate-manifest.py` now lives at
  `plugins/audit/scripts/manifest/validate-manifest.py`.** The plugin README publishes a `curl`
  of that file from `main`, so anyone who copied
  `https://raw.githubusercontent.com/AleksandarBisevac/claude-plugins/main/plugins/audit/scripts/validate-manifest.py`
  into their CI gets a 404 the moment this lands — `main` moves, and a raw URL has no
  deprecation window. Tag-pinned consumers are unaffected until they bump, since a tag keeps
  the layout it shipped with: `docs/examples/azure-pipelines.yml` fetches from `v0.5.0`. Two
  more documented invocations moved with it — `${CLAUDE_PLUGIN_ROOT}/scripts/render-report.py`
  → `scripts/report/render-report.py`, and `scripts/audit-journal.py` →
  `scripts/governance/audit-journal.py` — which break only for someone who scripted them by
  hand and then upgrades the plugin. The schema and template URLs are untouched.
- **That published `curl` had not worked since v0.14.0 anyway — 26 releases.** Run the two
  lines the README gives, verbatim, against `v0.39.0` and the answer is `ModuleNotFoundError:
  No module named '_manifest_io'`. The validator gained sibling imports in `4f9a8a2`
  (2026-07-24, first shipped in `v0.15.0`) and stopped being a standalone file that afternoon;
  `v0.14.0`'s copy still runs alone, and none of the 26 releases since does. The move above is
  not what broke it. Today the failure at least names itself — the anchor preamble raises
  "walked to the filesystem root … without finding `_output.py`" — and the two forms that do
  work are the in-session `"${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py"` and,
  from a checkout, `python3 plugins/audit/scripts/manifest/validate-manifest.py <manifest>`.
  Fetching one file out of a modular tree cannot be repaired by a better URL, so **the recipe is
  removed rather than repointed** — and named in prose where it stood, because it was published
  for 26 releases and anyone who copied it deserves the reason rather than a quiet disappearance.
  What replaces it states its own cost: the JSON Schema route validates **shape**, and cannot
  express reference integrity, so a `blockedBy` naming a task that does not exist passes the
  schema and fails the validator.
- **The three `curl`s that do work are pinned to `v0.39.0` instead of `main`** — the two starter
  templates and the schema, all pure data. **The four `$id`/`$schema` URLs are deliberately left
  on `main`**, and that exclusion is load-bearing rather than an oversight: an `$id` is the
  schema's *name*, so a per-release `$id` would give every release a different schema identity
  and break `$ref` resolution and cache keys for consumers. Identity is not a download.
- **`plugins/audit/scripts/` is no longer one flat directory.** Files are grouped into
  per-domain subdirectories — `report/`, `panel/`, `manifest/` and their siblings, a migration
  still running — and the rule that makes it safe is that **the directories are labels, not
  namespaces**: a `.py` basename must still be unique across the whole of `scripts/` —
  `_deps.layer_violations()` fails the build on a duplicate — so nothing outside has to know
  which domain a file sits in. `_loader.load_script()`, `hooks/_config.find_script()` and
  `tools/` each resolve a script by basename at any depth, and each refuses rather than
  guesses: a miss names the basename AND the number of files searched ("among 0" is a tree that
  was never walked, which is a different problem from a typo), a collision names both paths,
  and a value carrying a separator is refused rather than silently stripped. The moves were
  also the one-shot proof that the new path lint works — the first domain turned 0 missing
  references into 24 the instant the files moved, and `manifest/`, the widest reference surface
  of them, into 42. CI's three copies of the selftest sweep were converted from `scripts/*.py`
  to `find` before any of it, because a flat glob skips a nested file and exits 0: not a check
  that shows up missing later, a GREEN BUILD over a partial tree. No move changed a shipped
  byte — the assembled `UI_HTML`'s sha256 is unchanged and the committed example re-renders
  clean at every step. Alongside the moves, the four longest functions in the tree came apart
  (396 → 49, 354 → 42, 178 → 56, 147 → 23 lines) with behaviour held by differential run
  rather than by suite: 65 manifests validating to the same `(findings, warnings)` pair
  including order, and 13 report fixtures rendering 2,346,326 byte-identical bytes from both
  trees.
- **Every `--selftest` block moved out of the module it tests into `plugins/audit/tests/`, all
  48 of them.** 45% of this tree — 22,363 of 49,393 lines — was test cases living inside their
  own subjects, and all 48 files carried their own copy of `check()`. The old shape's failure
  was measured rather than argued: inject one fault and the inline form printed 0 PASS lines, a
  bare traceback and **exit 0** under `2>/dev/null`, while the same fault through the shared
  `_harness.run` gives 8 PASS lines, then a NAMED failure, and exit 1 — and nine of those files
  had been printing the identical last line whether the suite passed or failed. What a new
  `.py` owes changed with it: its cases go in `plugins/audit/tests/test_<name>.py` (hyphens
  become underscores) on the shared harness, never inline; a migrated module still answers
  `--selftest` by printing where its cases went, so a stale sweep cannot read as green; and
  `_output.selftest_coverage()` classifies every file as inline / covered / both / neither
  rather than returning a boolean, because a rule with an OR in it is exactly the shape that
  lets a file with NEITHER through. Three `KNOWN_LAYER_DEBT` entries retired on the way, 20 →
  17, without a line of production code changing — those edges were a test loading a validator
  to check its own output, never production coupling. And the migration caught four suites that
  had been passing while the thing they test was gone: a `getattr(..., lambda *a: None)`
  default answering in place of a deleted production function, a `.split(end_marker)[0]` slice
  that silently widened from 4,011 to 16,507 characters and reported `ALL PASS 51/51` over the
  rest of the file, a `globals()` rebind whose "allocates nothing" case is precisely the one a
  broken counter cannot fail, and a security case still "finding" the `git config --name-only`
  flag it had stopped looking at. `.split(a)[1]` fails loud; `.split(b)[0]` fails silent.
- **CI now re-renders the shipped example instead of comparing two committed copies to each
  other.** The old check proved `docs/index.html` was a byte copy of the example report — not
  that either file still reflected the renderer. So when `render-report.py` changed and nobody
  refreshed the artifacts, both drifted together and the gate stayed green; that is exactly
  how the published demo spent a while claiming `share 1%` for a row at 0.7%. The new step
  renders into a scratch directory and diffs, which means normalizing the `generated <UTC>`
  stamp in **both** places it appears — the visible header and the base64 Markdown twin
  embedded in the page — and treating a zero hit as a failure rather than a quiet pass. The
  Markdown twin is compared now too; CI had only ever grepped a *fresh* one and never looked
  at the shipped copy.
- **One home for "every task, and which phase it came from".** Thirty-three hand-rolled task
  walks across twelve files now go through `_manifest_io`'s owners, and the duplicated
  `effective_bug_status` body — whose own docstring admitted it "mirrors" the other copy — is
  gone. Just as deliberate are the **twenty sites left alone**, each with its reason recorded
  where the code is: `validate-manifest` must not adopt a *skipping* traversal when its job is
  to report what would be skipped; `gen-demo-usage` draws one random number per phase, so
  skipping task-less phases would change every generated ledger row; `audit-status`' index
  keeps phase ids and task ids in one map, where splitting the walk lets a task win a
  duplicate-id collision that document order used to decide. That last one was caught by a
  4,000-manifest differential fuzz **after** the conversion looked right, and reverted.
- **Hooks stamp time through one helper.** The same
  `strftime("%Y-%m-%dT%H:%M:%SZ", gmtime())` was typed out in five files, and the sixth would
  eventually have been typed with `localtime` — which nothing would have caught, because the
  `Z` is a literal in the format string and the result still parses. A lock taken at 14:00
  CEST recorded as `14:00Z` makes every consumer compute a negative age. The new cases pin
  that the digits really are UTC, and force a timezone around themselves to do it: on a UTC
  box — which is every CI runner — the obvious assertions are blind to exactly this bug.
- **A constant that is both copied and never read is now a build failure.** `panel-server.py`
  declared `CONFIG_REL` and never used it while importing the module that owns it — nothing
  broke, it was just a second place the fact could drift from. The lint is narrow on purpose:
  a duplicate that *is* read stays silent (removing that one is a refactor, not a deletion),
  and the `hooks/`↔`scripts/` pair is exempt because the layer rule forbids merging it — a
  lint that demands an impossible fix is a lint people learn to skip.
- **The panel's 5-second poll stopped walking `~/.claude`.** `discover()` did 1,381 `scandir`,
  105 `listdir` and 337 front-matter reads — 154 ms cold — on every call, and it is reached
  from `policy_state`, `/api/registry` and `audit-status --discovery`. `data_fingerprint`
  includes the newest ledger mtime, which the Stop hook bumps on every turn, so during an
  active phase the panel re-fetched state, usage and policy every five seconds purely because
  someone spent tokens. Now 0 `scandir` and ~2 ms on a hit — 15× on the poll path, same answer
  — and the invalidation stamps what was actually scanned rather than the roots, because a
  plugin installed a level down moves that directory's mtime and not the root's. In the same
  pass `usage_state` stopped reading one manifest five times: 5 calls and 101 file opens become
  1 and 21 on a 19-shard fixture, payload byte-identical by `cmp` rather than by reasoning —
  and reading once is also the more correct of the two, since five reads can straddle a
  concurrent write and ship five mutually inconsistent views of one plan.

## [0.39.0] - 2026-08-15

**The ADO connector grows up: boards, sprints, and a card in the panel.** `/audit:sync`
learns the whole board: one PBI per phase with parent-linked items (`phaseWorkItems`,
auto-detecting the process's phase-level type and writing the pick back), a configurable
`stateMap` (a `null` transition = "the team moves that card by hand"; cards move via
`System.State` only — a column not backed by a state is reported as unreachable, never
faked), `onComplete.remainingWork` written on the done move, opt-in generated comments on
blocked/completed, current-sprint resolution (`sprint.team`) with drift reporting, scoped
push (`--task`/`--phase`) and a sprint pull that imports a shared sprint's PBIs as parked
proposals — filtered by `pull.areaPath`/`pull.tags`, refusing to import blind when no
filter says which items belong to this repo.

**⚠ Default-on echo.** With `meta.ado` configured, the orchestrator now best-effort
UPDATES already-linked work items on task done/blocked/reopen and phase sign-off
(state, Remaining Work, comments — update-only, never creates, never blocks a run;
`/audit:sync push` reconciles anything it missed). Existing `meta.ado` users who want
manual-only sync set `"echo": false` — one key, links and sync keep working.

The connector is visible: an **ADO card** on the panel's Composition tab (its own
`PUT /api/ado` through the one composition writer, validated by the same
`check_ado_meta` the CLI runs; dotted presence-aware change rows; an honesty banner —
unconfigured / off / unverified / linked — computed from manifest evidence only, no
network in the panel, plus an identityMap pair editor). The journal gains `task.blocked`
and `ado.link` rows (a `lastSyncedAt` bump deliberately writes no row), `/audit:doctor`
gains the operational half (transport, switches, the Scrum-vs-Agile stateMap advisory,
what the links prove), and the shared contract lives in `reference/tracker-sync.md`,
written tracker-neutrally so a future `meta.jira` mirrors the same keys 1:1. The
user-facing story — setup, every key with an example, recipes for Scrum / sprints /
shared-sprint pulls / identity mapping, the echo contract and troubleshooting — is a
new field guide at `docs/ado-connector.md`; the README section stays the summary and
links to it.

Four contract truths came back from the LIVE gate (a real ADO org, both stock
processes) and are folded in: states are applied by UPDATE, never at create (ADO
allows only the initial state at creation); phase work items carry a different
state vocabulary than tasks, so `stateMap` gains a `phase` block; both stock
processes force-clear Remaining Work at done, so the combined write degrades to
state-only with a report (and a doctor advisory); and tag writes are read-merge-
write, because `System.Tags` updates are wholesale and writing blind would erase
the team's own tags. Plus, user-requested: `meta.ado.tag` — the provenance tag is
personalizable per repo (default `audit-plugin`, `null` = none), pairing with
`pull.tags` for per-repo push/pull symmetry on shared sprints.

**A fifth lifecycle state, and a table that answers.** `cancelled` joins `done` as
terminal: a phase can finish without being done. Readiness treats a cancelled blocker as
settled, sign-off accepts done-or-cancelled, the report files it under Archived, sync maps
it to Removed, and `/audit:task cancel <id> --reason "<why>"` records the reason, the
moment and a journal row, cascading to work still open inside a cancelled phase. The
report's phases table gains a named **View** — active & pending / archived / all —
replacing an archive toggle nobody found; a search that matches rows the view hides says
so and offers the one press that shows them, and the view and every filter survive a
reload, including over `file://`. Each task gains a detail row carrying the full outcome
in both voices, both timestamps, owner, branch, work item, model, skills and what it waits
on, so model / outcome / ADO could leave the compact row and rows are one line again. The
panel's Overview follows the same shape and opens a phase in place.

**Themes as data.** A new Appearance tab, and a theme is token *values* in a DTCG-shaped
JSON file: the compiler substitutes them into the stylesheet, so the default theme compiles
back to the shipped sheet byte for byte and a theme can change values and nothing else.
Light and dark pairs sit side by side with the live column marked, contrast is warned but
never refused, charts sit behind a deliberate unlock, density is one multiplier over the
spacing scale, and Save-as writes to `.claude/themes/`. Reports render wearing the same
theme.

**Seven dogfooding findings, each reproduced before it was fixed.** The composition
dropdown flickered and fled the pointer because `tr.phase:hover>td` carried a `filter`,
making that cell the containing block of every `position:fixed` descendant; the menu is now
one element on `<body>`. Spend with no plan behind it read as `--` across four spellings on
three surfaces and is now one word from the shared label map. And `guard-secrets-read`
refused a read-only one-liner as a source write — the heuristic matched a write shape and a
source path anywhere in one clause without checking they were the same thing.

**The rules that govern an edit became something a session can read.** A root `CLAUDE.md`
states the hard rules and defers to `CONTRIBUTING.md` and `PLUGIN-BUILD-GUIDE.md` rather
than restating them, and eight dev-time skills land under `.claude/skills/` — three copied
from `wdm0006/python-skills` (MIT) at a pinned commit and trimmed where they contradict this
repo, five written here because nothing off the shelf fits a stdlib-only, annotation-free,
3.8-floor tree with a build-less front end. `writing-python`, `writing-javascript` and
`writing-css` fire at write time rather than at review time. None of it ships to plugin
users; `plugins/audit/skills/` still holds exactly the two thin routers.

**Two gates that were lying, and one that could not see.** The segment-CSV checks pulled the
commit sha and completion stamp out of a row with a naive `split(',')`, so any row whose
title carried a comma shifted every later column and the export was accused of a defect that
was in the diagnosis — green on every fixture CI renders, red only against a plan whose
titles read like prose. `docs/demo-large.html` predated the report's view selector, so the
interactive checker died on an unhandled timeout instead of the exit-2 "cannot check" it has
for older reports. And `_deps` gained `ui_navigability_violations()`: the 400-line
section-marker rule now reaches `scripts/ui/`, which the `.py`-only lint had never seen, as a
density (one marker per 400 lines) because those assets run 2–11× longer than the longest
`.py` in the tree.

## [0.38.1] - 2026-08-15

**The round's own leftovers, swept.** `meta.ado` itself now has a shape — a bare string
there used to draw neither finding nor warning while the identityMap check silently stepped
around it; the item-level rule ("an object or null") simply applies at meta level too. And
`/audit:init`'s workspace step stops scanning the filesystem for area skills: it feeds a stub
manifest to the same `audit-status --json --discovery` source every other skills step already
uses — one inventory, fail-open, real names only.

## [0.38.0] - 2026-08-15

**A pattern that names nothing decides nothing — and now something says so.** The capability
policy's dead patterns (a glob matching nothing installed on this machine) surface as
advisories on the two surfaces that can see the inventory: `/audit:doctor` warns with the
honest hedge that a teammate may have the tool, and the panel's Policy tab marks the rule
where it gets edited — one implementation, config-pure, never a refusal. `/audit:init` and
`/audit:task` stop scanning the filesystem for skills themselves: `audit-status --json
--discovery` is the one mechanical source (the bare payload stays byte-identical — pinned),
fail-open when discovery breaks. `meta.ado.identityMap` maps ledger identities to ADO
emails, advisory in every direction — push proposes assignment one batched question per
person and never on updates, pull reverse-maps new imports without ever rewriting existing
rows, status shows coverage, and the validator checks shape only. And the tag history is
whole again: every released version from 0.10.0 on carries its annotated tag on the exact
release commit — except v0.20.0, whose deleted tag remains the honest record of a release
that never happened, exactly as CONTRIBUTING tells it.

## [0.37.0] - 2026-08-14

**Skills learn the difference between "none applies" and "nobody asked", and the journal
learns to retire its months.** `skills: null` is now a conscious opt-out in reviewSkill's
exact idiom — an answer, not a miss — stopping the area fallback, while `[]` stays
"unconsidered" with the area default in force; the panel shows all three states, the
validator warns (never refuses) on tasks that resolve to nothing without having answered,
a near-miss detector catches one-letter skill typos, and untagged phases in an
area-registered project get one aggregated advisory line. `/audit:task add` stops
hand-templating fifteen fields: the new `audit-task.py` allocates the id under the index
lock, initializes everything exactly once, revalidates from disk with byte-for-byte
rollback, and journals beside the NAMED manifest (its one mid-round misroute was caught by
this repo's own bash-write-guard — the gate guarding its author). `/audit:init` suggests
skills per task at approval, real names only. `audit-journal.py archive` retires old
month-files into `journal/archive/` by `git mv` — the chain seeds from the basename and
survives only untouched bytes, which is exactly what a move preserves — with verify and
doctor following them there. And the checker debt from 0.36 is paid: the inline-eval
backstop shares the gate's definition of a test file, whole-document pins (selftest AND
the CI step's three probes) judge markup with scripts stripped, the panel-CSV assertion
parses instead of pattern-matching, and a task in progress under a pending phase heals at
the write site instead of nagging after it.

## [0.36.0] - 2026-08-14

**The gate stops blaming the innocent, and the report learns time.** Five trust repairs from
live reports: a test-suffix glob no longer exempts a data/markup file (`tsconfig.test.json`
is a build config, not a test — fixed once, in the shared matcher, for every guard);
guard-bash-writes baselines a session's pre-existing dirt silently instead of blaming the
first command for it; guard-secrets-read judges multi-clause commands per clause (a redirect
in one clause plus an eval in another is no longer a false DENY) and its verdicts finally
land in the gate events feed; a declared non-string `reviewSkill` normalizes instead of
leaking onto display surfaces.

The report gains a global filter row in its sticky top bar — authors dropdown, area select
and a from/to date range scoping every time-based view, each choice a shareable link that
prints as a named line; the tokens heatmap grows to full width with calendar navigation
(day/week/month/year, arrows bounded by the data, the period always named); Ready now becomes
a definition list with area chips and what cleared each task; long plans split into
active / pending / done-archive segments with per-segment CSV export, chart PNGs redrawn
from data, and print-to-PDF of one segment; area owners ride the tags, advisory. The panel's
Usage tab gets the same calendar-navigated heatmap, driven by its persisted filters, with
zero payload changes. And the CLIs learn `--color auto|always|never` through one shared
helper — plain output stays byte-identical, `NO_COLOR` respected, an explicit `always`
outranking it — while the executor agent's "verified" now requires the exact command and
exit code, or it counts as not done.

## [0.35.1] - 2026-08-14

**A tip that does not exist cannot break anything.** 0.35.0's fixed-position ⓘ bubble still
lived inside the box that carried the icon — one transformed or containing ancestor from
silently demoting to absolute, where showing it grew the scroll frame: hover an ⓘ, get
scrollbars, which is exactly what a live repo got. The tip is now one element on
`document.body` — no ancestor can trap, clip or resize anything, nothing exists until it is
shown, its height is measured rather than estimated, and every coordinate lives in the script.
It also learned how it was opened: a pointer tip closes when the pointer rests elsewhere
(including Chromium's synthetic mouseover after a scroll), a keyboard user's focus tip ignores
the parked pointer and follows its anchor. The browser checks gained the assertion this bug
proved missing — showing a tip must never grow any scroll box. And the combo menus (skills and
models) wrap instead of scrolling sideways: names may break anywhere, descriptions take their
own line when they need one, and the menu clips the X axis outright.

## [0.35.0] - 2026-08-14

**What the plugin claims, the plugin now does.** The panel had told every repo its token file
was gitignored while nothing anywhere wrote the rule — found on a live repo one `git add
.claude` away from publishing a live session token beside a ledger of person identities. Now
every local artifact makes ITSELF ignorable: state, logs and the usage ledger drop a `*`
.gitignore into their own directories as they are created, the panel writes a targeted rule
for its pidfile and claims only what it verified, and a new doctor **hygiene** check names
anything already tracked — loudest for the token, with the rotation step spelled out. The
release requires no manual configuration change anywhere, which is now the standing rule:
an update either automates its migration or names the one thing it will not do for you
(untracking already-committed history stays a human decision, and doctor hands you the command).

Also here: `/audit:usage` renders markdown pipe tables on the chat surface (`--format ascii`
keeps the fixed-width shape for terminals, pipes and CI); the guide agent sheds its stutter —
`audit:audit-guide` is now **`audit:guide`**, with a `/audit:guide` command to match, a
registry that renames itself and a validator warning for any policy pattern still naming the
old id; the composition table says WHY a phase with every task done still reads in progress
("all tasks done — awaiting sign-off"); and the ⓘ tooltip joins the product's fixed-position
family after a live repo found it painted under the model column — clipped and buried by the
same scroll-frame/stacking-context class the combo menu crossed in 0.34. Every new behaviour
proven red first; three sabotage proofs restored byte-identically; 40/40 suites in both
encodings; the full browser check three times over.

## [0.34.0] - 2026-08-13

**A gate that cannot explain itself gets worked around; this release makes the plan gate speak
to the human it protects.** The old refusal stated one cause — "A phase is in_progress" —
whether or not that was true: with `enforce: true` and nothing running, the message named a
phase that did not exist, and the agent relaying it padded the gap with invented explanation,
so the person downstream got the confabulation instead of the verdict. Now every refusal names
its true cause, a `planGate` knob adds an **ask** tier that routes the decision *to* the human
rather than around them, warnings open by telling the agent to relay them verbatim, every
verdict leaves a line in an events feed the panel reads back, and the bypass is something only
a human can arm — single-use, logged, and expired unused after 30 minutes. Around that: the
dogfooding fault backlog paid down (thirteen fixes, plus three faults this release found and
fixed in its own verification tooling — every one proven red first), a panel that searches,
persists and refreshes itself, and monorepo areas that can name an owner — advisory, never an
assignee.

### Added
- **`planGate` pins the gate's tier by hand: `observe` | `warn` | `ask` | `deny`.** Unset, the
  graded ladder stays exactly as it was; set, the tier is fixed and both plan gates (edit tools
  and the shell-write branch) obey it identically. **`ask`** holds each out-of-plan edit for the
  human's approval, one edit at a time — approving the dialog *is* the evidence, recorded as an
  `ask.approved` event. It supersedes the legacy `enforce` key (`true` = `planGate: "deny"`,
  and `planGate` wins when both are set, with a validator warning); a typo'd value fails **open**
  to the ladder — never to deny — and the validator names it. The panel's Settings gains one
  select for it whose preset also reads the legacy flag and whose change writes `planGate` while
  deleting `enforce`; `/audit:doctor` names which key pinned the tier, and warns loudly about the
  one setting that holds the gate *below* its evidence — `planGate: "observe"` while a phase runs.
- **Gate events: the gate's decisions are on file, not in scrollback.** Every verdict — deny,
  warn, observe, an approved ask, a bypass armed / consumed / expired — appends one compact JSON
  line to `<logsDir>/plan-gate-events.jsonl` (fail-open, self-trimming past ~512KB, never
  blocking a verdict on telemetry). The panel's Overview gains a **Plan gate** card: the tier in
  force and its source, whether a bypass is armed right now, and the latest events — landing
  within one poll, because the gate block rides the run-status payload the panel already fetches.
- **Advisory area ownership.** `meta.areas[tag].owner` names who to coordinate with, written the
  way `usage.authorMode` records authors so the ledger can join it; an explicit `null` is an
  answer ("nobody"), and across several tags written order decides, like every other area field.
  When someone else edits a covered file in an owned area, the gate adds a once-per-session
  heads-up — measured tone, "fine to continue, say so in the handoff" — and never blocks.
  `/audit:status` prints the owner in BY AREA, the panel shows `owns: …` in the person header
  and on area options, and doctor hints when an owner never appears in the ledger's author
  column (usually an identity spelled differently from what git reports). Deliberately no
  `task.assignee` and no enforcement — the ledger's author×task join stays the only identity
  claim the data supports.
- **The panel's model fields get a real autocomplete with its sources named.** Task model,
  phase review model: one menu merging the manifest's models ("used by N task(s)"), the rate
  table's ("$in/$out per MTok") and — the load-bearing one — models **the token ledger has
  actually seen** ("N tokens in this ledger"), because a ledger-only name is what a typo'd
  manifest model looks like from the spend side. The validator's new near-miss check warns on
  exactly that shape inside the manifest (a model used once, edit-distance-1 from one used
  elsewhere), and never on an honestly single-model plan.
- **Usage filters persist and travel.** The Usage tab's filter state rides the URL fragment
  (`#/usage!au=…` — the tab router splits on the first `!`), so a filtered view is a share link
  the way the report's is, and it is remembered per repo across reopens (hash wins over the
  remembered state; clearing filters clears both). Combo search now matches **descriptions** as
  well as names everywhere, and a long list says `…N more — keep typing` instead of cutting off
  silently.
- **The panel refreshes itself without eating anyone's edits.** A fingerprint of the manifest,
  its shards, the config and the ledger rides the existing 5s poll; when the files move on disk,
  clean views re-render within a poll, while a form holding unsaved edits is left untouched and
  gets a persistent notice — Save is still checked against the file on disk, Discard reloads
  what is really there, and refreshes hold while any dialog is open. SSE was considered and
  rejected: for a localhost tool already polling, a second streaming path buys nothing.

### Changed
- **Refusals and warnings state their true cause and their real alternatives.** A deny names
  the running phase by id, or the config key that pinned the tier — three different sentences
  for three different causes, now pinned by tests (the old single sentence was pinned by
  nothing, which is how it shipped false). The refusal weighs the two ways forward — add a task
  covering the file (preferred), or the **human** types the bypass keyword in their own prompt —
  and tells an agent reading it to ask, not to recommend the bypass. Warnings open with "Tell
  the human this verbatim before continuing."
- **The `#no-plan` bypass expires unused after 30 minutes.** Arming it says so; consuming an
  expired one instead logs `expired unused`. Hooks only see prompts a human submits, which is
  what makes the keyword the human's — an agent cannot type it for them.
- **A refused save now outlives a glance away.** The panel's save-result card gets a lifecycle:
  success says `✓ saved` and dissolves after 5s; a refusal stays — bold title, the findings,
  its own dismiss — until closed or superseded. Previously both faded on the same clock.
- **The journal's git policy is stated everywhere it was implied.** Never gitignore the journal
  — git history is one of the trail's three anchors and only pins committed history; README,
  the config table, troubleshooting and the conventions doc now say so, and doctor warns when
  journal files sit uncommitted past a week (mirroring the GC horizon). A new **Growth**
  paragraph states the honest arithmetic — one small file per writer per month, no compactor by
  design, because rewriting chained files is indistinguishable from the forgery the chain
  exists to catch.
- **Ledger writer ids sanitize cleanly** (F-F2): a slice can no longer leave a filename ending
  in `-`/`.`, and a pathological id falls back to `writer`. In-flight sessions simply start a
  fresh file mid-month — harmless, chains are per-file and multi-writer is the normal case.

### Fixed
The v0.33 dogfooding backlog paid down, plus three faults this release found in itself — every
fix proven red first, or by sabotage with the original restored (F-F2 sits under Changed):
- **Ledger discovery could walk out of the repo and bill it with the home ledger** (F-E1):
  `find_ledger_dir` now stops at the first ancestor owning a `.git` (dir *or* file — worktrees)
  and never returns a path under `~/.claude`, fixing all four callers at once.
- **A repo that never metered read "ledger empty"** (F-E2): doctor now tells a directory nothing
  created ("no ledger yet — would live at …") apart from one that exists and holds no rows.
- **Free-form proposals were invisible** (F-E3): entries whose status is outside the vocabulary
  now surface as a one-line legacy footer in status and a count in doctor, instead of vanishing
  from every list while still occupying the file.
- **The plugin's own journal append warned about itself** (F-F3): `journal-writes` records what
  it wrote to a single-writer sidecar and `guard-bash-writes` skips exactly those rows — a real
  `sed` into the journal still warns. One racing shared file was the bug's shape; one writer per
  file is the fix's.
- **Journal pre-image slots were never garbage-collected** (F-B1): `journal-preimage-` joined
  the GC prefix set; an 8-day-old slot is now removed like every other stale session file.
- **Trail verification cost one `git show` per journal file** (F-B3): `verify()` batches one
  porcelain call per directory and pays the per-file check only for dirty files — doctor and
  the panel's state build inherit the flat cost.
- Doctor's selftest was **date-dependent** (F-A1): a fixture hardcoded `completedAt:
  2026-08-14`, so the drift check legitimately stopped firing the day the calendar caught up;
  the timestamp is now derived from the clock.
- The hooks' ledger module loads through the same cache as its siblings (F-B2); the report
  checker's `clearAll` pin now reads the function it names rather than the whole file (F-D1)
  and its `m=` filter regex is anchored like the area check's (F-D2); a dead `esc()` left the
  report's source (F-C1); the submodule selftest group no longer shares letters with the shard
  group, and a duplicate-name guard makes the next collision a red build instead of a silent
  overwrite (F-D3).
- **The new model-combo browser check was itself flaky** (F-C-1, found by this release's own
  verification): it injected a probe into in-page state that the panel's new live-refresh
  replaces wholesale, so a refetch landing mid-step erased the fixture — the same F4 shape the
  lock check had. The run-status endpoint is now frozen for the step, in-flight refreshes are
  drained before the probe goes in, and the old race window is driven on purpose every run —
  proven red with a forced mid-step stamp move, then green with the freeze, then stable across
  three consecutive full `--check` runs. Fixing it surfaced two more of the same class: the
  stale-echo check's freeze could itself trigger the one refresh it existed to block (a poll
  against the frozen route seeing a stamp the client had not adopted yet — green only by the
  grace of the poll's phase, deterministic the moment a new step shifted it), which now drains
  the hand-off first; and the build lint that forbids hand-writing polled state required names of three
  letters or more, so the two-letter `FP` was invisible to it — tightened, and proven red on a
  real violation before being believed.

## [0.33.0] - 2026-08-12

**Four questions from one team adopting the plugin mid-project, and one posture answers all of
them: propose rather than presume, and carry the evidence for what you claim.** A team introducing
the plugin into a living repo does not want forty generated phases written into it unasked — so
init now asks, and "no" parks the plan losslessly instead of discarding it. A `status: done` is
only worth what it can prove, so completing a task now leaves a hash-chained record cross-anchored
to git and the token ledger — sold as tamper-*evidence*, never immutability, because absolute
immutability of a local file does not exist and claiming it would be the exact overpromise this
plugin exists to refuse. And the two questions every ledger is eventually asked — *what did this
month cost* and *which part of the system is spending* — get answers computed in exactly one place
each, so no two surfaces can drift apart.

### Added
- **`/audit:init` presents its synthesized phases for approval before writing anything.**
  Materialize all, park all, or choose per phase — materializing a phase pulls its `blockedBy`
  predecessors in with it, announced; an interrupted gate parks everything, conservatively. Parked
  phases live in the schema's previously dead `proposals[]` as full payloads with their phase ids
  reserved, and the new **`/audit:propose`** command `list`s, `materialize`s (a move, not a
  re-synthesis) or `drop`s them. Status prints a PROPOSALS block, doctor counts them, and the
  validator enforces the `PROP-<n>` vocabulary.
- **Completion records: done now carries evidence.** The journal hook caches a pre-image at
  PreToolUse and writes field-level diffs (`P2.3: status in_progress->done, completedAt set`)
  where a row used to say only that a tool wrote a path; a task completing, a commit landing and
  a phase signing off each leave a chained `task.complete` / `task.commit` / `phase.signoff` row;
  `verify()` anchors committed journal bytes to git history, so rewriting the file with freshly
  recomputed hashes is a FINDING that costs an attacker the git history too; and doctor's new
  `check_completions` cross-checks every done task in scope against its record, its commit SHA —
  the first place a `task.commit` is ever tested against `git rev-parse` — and the ledger. A
  watermark rule keeps every manifest that predates the feature green.
- **`/audit:task move <taskId> --to <phaseId>`** — the sanctioned path for renumbering a task
  into another phase: id re-allocation in the target phase, every `blockedBy`/`dependsOn`/
  `fileIndex`/bug reference rewritten across shards, `movedFrom` on the task, and a chained
  `task.move` row. Historical ledger rows keep the old id on purpose — history is not rewritten;
  `movedFrom` is the join.
- **`journal.strictManifestState: "ask"`** — an opt-in confirmation when an edit changes a task's
  or phase's state fields (`status`, `completedAt`, `commit`, `attempts`). Deliberately no
  `deny`: the orchestrator finishes tasks through the same tools the guard watches.
- **The calendar is a first-class dimension.** `--by month` groups spend by calendar month
  (`byMonth` in `--json`), and one function — `monthly_activity` — computes the 12-month view of
  tokens beside plan progress (tasks by `completedAt`, bugs by `reportedAt`, fixes by the month
  their linked task completed, phases by `mergedAt`) that three surfaces render and none may
  reimplement: a MONTHLY table in the CLI, a Month-by-month table in the report, and a clickable
  Monthly card in the panel whose plan half stays project-wide and says so. All three wait for a
  second calendar month, because a one-month table restates the totals. The panel chart's 28-day
  rung became true calendar months, with a forced day/week/month bin control and a last-12-months
  preset.
- **Author views that claim only what the join supports.** Tasks record no author, so the
  report's new author chips scope the Usage section's per-author views and nothing else — the
  page says so, and the tiles and trend above stay project-wide. The panel, where the author
  filter already is the drill-down, adds a person header when one is selected: all-time share of
  spend, models, phases and tasks touched with a status split, active range.
- **Areas reach every surface through one read-time join.** A row's `phaseId` meets its phase's
  tags at read time (`phase_tags` + `aggregate_area`), so re-tagging a phase re-attributes its
  whole ledger history on the next read, with no backfill — area is a property of the plan, not
  of the moment the tokens were spent. `/audit:status` prints the BY AREA block it had always
  computed but only ever shipped in `--json`; `/audit:usage` gains `--area`, a BY AREA table and
  `byArea` in `--json`; the report's dormant `data-area` attribute finally gets its filter (area
  chips, `a=` in the shareable hash); and the panel's Usage tab gains an area select fed by both
  state branches. Two edges stated wherever they apply: a phase tagged with several areas counts
  under each of its tags, so area rows can sum past the total; and `untagged` is a real bucket —
  untagged phases, unknown phases, and rows that never carried a phase.

### Changed
- **Doctor grades a switched-off journal honestly.** `journal.enabled: false` beside existing
  journal rows is now a WARNING — *was running and has been turned off* — instead of OK, and the
  flip itself is recorded as a last-will row evaluated against the pre-image config, closing the
  hole where disabling the journal was the one config edit the journal never saw. Never a
  FINDING: nothing overrides the user's own switch. The one intentionally changed pin in the
  integrity work.
- **The report's small multiples render every author's cell**, everything past the top eight
  `hidden` until an author chip reveals it. The series was always computed for all authors; only
  the render was cutting to top-N, and a filter over cells that do not exist would have been a
  filter that lies.
- **The worked example now carries area tags.** `acme-store`'s phases are tagged from their own
  file paths — auth hardening under `auth`, input validation under `storefront` + `checkout` (a
  real multi-tag phase), the performance pass under `storefront`, the bugfix batch left untagged
  on purpose — with a `meta.areas` registry describing each. The live demo now shows the area
  chips, and CI's interactive check exercises the real area-filter path on every push instead of
  skipping it for want of a tag.

## [0.32.1] - 2026-08-11

**Three faults, and in every one the check that should have caught it was already running.** A
gate that reddened once a month was racing its own fixture. A tooltip took a phone's page 103px
sideways past a sweep that measures exactly that page — and could not see it, because the thing
overflowing has no element to name. And the rule "hooks import nothing from scripts" was written
in three places, one of which was an allow-list holding the single import that broke it. Nothing
here is a new feature; the theme is that a passing check is not the same as a covered one.

### Fixed
- **The ⓘ tooltip had no right answer on a phone, and it was placed by an event that need not
  fire.** Placement lived in a `mouseenter` handler, and a pointer can come to rest on a hint
  without one — scroll the page under a stationary mouse and Chromium updates `:hover` silently,
  and the panel's 5s poll re-renders the form underneath it the same way. Measured on Settings at
  390px: a hint whose placement had simply never run opens left-anchored and takes the **document
  103px sideways**. The deeper half is that fixing the timing alone would not have been enough —
  the old answer chose between two anchors, and on a phone that choice has no correct answer for
  **20 of Settings' 27 controls**: left-anchored the bubble runs past the right edge, flipped it
  starts at **x=-117**, off screen, where nothing scrolls and nothing can be read. The bubble is
  now clamped into the viewport — the hint's own position where that fits, the nearest edge where
  it does not — and placement is driven by the document changing (a `MutationObserver`, resize and
  scroll) rather than by a pointer being seen to arrive. A third defect surfaced while measuring
  the fix: `*{box-sizing:border-box}` does not reach a pseudo-element, so a 17rem bubble painted
  290px for a number that said 272, and the old flip threshold had been wrong by that same 18px in
  the same direction as the bug it existed to prevent.
- **The plan gate now reads a sharded manifest through the launcher, proven rather than assumed.**
  `hooks/_config.py` loaded `scripts/_manifest_io` by inserting `scripts/` at the front of
  `sys.path` — a process-wide change to import resolution, made in a hook that runs on every tool
  call, to load one module. It now loads by path like every other scripts/-owned feature the hooks
  reach for. The behaviour that depends on it had no end-to-end coverage: the CI wiring proof drove
  its tiers on a single-file manifest, the one layout that needs nothing from `scripts/` to read,
  while a sharded index carries phase stubs with **no status** — so a hook that failed to load the
  module would fall back, see no phase running, and go **silent on a project whose gate should be
  denying**. That case is now driven end to end.
- **The panel's own composition check was racing its fixture, not failing under load.** It
  installed a lock fixture by assigning the panel's polled `RUNSTATUS` global, which the 5s poll
  rewrites from `/api/runstatus`; a poll landing in the gap put the real answer back and the check
  read `null`. Nothing in the product was wrong. The fixture is served from the endpoint now, so
  every later poll re-serves it, and a build lint reads the names the poll assigns out of
  `panel.js` and fails if a check writes any of them into the page.

### Changed
- **`hooks/` statically imports nothing from `scripts/`, with no allow-list.** The rule was
  already the stated design and already machine-checked; the checker carried one documented
  exception, which was the only thing standing between the rule and being true. The exception is
  gone with the import, and a new drift lint fails the build on any document that states the rule
  and then carves an allowance out of it — the build guide had been doing exactly that.



**The code gets the treatment the product sells.** This plugin's whole pitch is enforcement over
persuasion — plan gates, drift lints, mutation-proven selftests — while its own two biggest files
were an 8,286-line and a 4,596-line scroll, its module boundaries lived in prose, and its build
guide described nine files out of twenty-nine. This release refactors the plugin by its own
rules: every move proven byte-identical before being believed, every new boundary enforced by a
lint that was shown red before being trusted, and the suite growing from 1,945 to 2,173 cases
across 40 suites on the way.

### Changed
- **`panel-server.py` 8,286 → 1,843 lines; `render-report.py` 4,596 → 1,611.** The settings
  schema, discovery, read-side state and write path live in four flat `_panel_*` modules; the
  report's fragment builders and the whole usage section (with its markdown twin) in two
  `_report_*` modules — each carrying the selftest cases that pin it, moved with their labels
  intact and their counts audited (nothing dropped; the panel family alone grew 428 → 469).
  Entry-point filenames never changed; every downstream reference still works.
- **The embedded UI is real files now.** 5,340 lines of CSS/JS/HTML moved out of Python
  r-strings into `scripts/ui/panel.{html,css,js}` and `scripts/ui/report.{css,js}`, read at
  import with explicit utf-8 and assembled into the exact same constants — proven by comparing
  the assembled page old-vs-new: 244,588 == 244,588 bytes for the panel, 61,698 and 37,708 for
  the report's CSS and script. The served page is still one self-contained document; only the
  source stopped being a blob. One trap found and dodged: slicing a non-raw literal out of
  source text captures pre-escape bytes, so the report extractor reads the evaluated AST
  constant instead.
- **Four duplication classes became single definitions.** `_loader.py` replaces fourteen
  hand-rolled importlib copies that had grown five different caching policies (fresh-reload
  sites now say `cache=False` instead of implying it); `_manifest_io.atomic_write_json` is the
  one writer, with the collision-free mkstemp semantics and byte-stability proven for both
  `ensure_ascii` shapes; `_help.front_matter` is the one front-matter parser, with the edge
  cases the two old parsers disagreed on decided and locked; `_fmt.py` is the one token/cost
  formatter, proven byte-identical to both prior shapes by 36 goldens frozen from the originals
  before anything moved.

### Added
- **A dev-only lint gate — the runtime stays at zero dependencies.** `pyproject.toml` carries a
  ruff config (E9 + pyflakes, py38 target, deliberately no formatter), CI pins `ruff` and
  `vermin -t=3.8-` as the floor gate, and `_output.py` AST-enforces what version gates cannot
  see: the walrus, `__future__`, `typing` and `dataclasses` bans are build failures now, each
  proven red individually before being believed.
- **The module structure is data with a lint (`_deps.py`).** An eight-layer table over the real
  import graph (83 static edges): a cycle, an upward import, a file without a layer, or a new
  hooks→scripts dependency fails the build by name. Its first run earned its keep — the layer
  sketch was corrected twice by the real graph, and the one genuine pre-existing
  hooks→scripts import (`_config` → `_manifest_io`) is carried as a named exception the
  selftest holds to exactly one.
- **The build guide is complete and stays complete.** A generated module map under a
  byte-for-byte drift lint; every one of the 40 shipped Python files present in the directory
  tree and the file-by-file sections, under an enumeration lint that names a missing file; a
  navigability lint that fails any bare file over 400 lines. The enumeration lint found three
  gaps the migration plan itself had missed, which is the argument for it in one sentence.
- **`.gitattributes`, because the newline a checkout chooses is part of the build.** The ui/
  assets are byte-read inputs; a Windows checkout rewrote them to CRLF and failed two selftest
  pins two files away from the cause. The eol is pinned to LF now, and a guard beside each
  reader names a CRLF asset directly.
- **CONTRIBUTING: an add-a-script checklist and three recorded decisions** — folders under
  `scripts/` declined (revisit at 40+ files), the `usage_ledger.py` split deferred with its
  trigger, and the typing ban standing — each with its reasons written down.

### Fixed
- **The Settings tab no longer scrolls a phone sideways (F8), and the check that missed it now
  looks everywhere.** A checkbox row could never shrink (`flex:0 0 auto`), so one long setting
  name held a 447px floor on a 390px screen and took the whole document with it; the row may
  shrink now and its label wraps. The 390px overflow gate drives every panel tab instead of the
  one the photographer stopped on, names the widest offender, and measures 320px too.
- **`journal_dir` answers in one spelling on every platform.** It joined config-side forward
  slashes onto OS-side separators, and the hooks' delegation check rightly refused to call the
  two spellings equal on Windows. Normalized at the API, proven red-first on POSIX via the
  root-manifest `./` case the same bug produced there.
- **Two checks that were green for the wrong reason now bite.** The report's stacked-segment
  order case matched the stylesheet's variable declarations rather than the markup (re-aimed at
  the real segments, proven red under reversed order), and the sub-cent cost rule was proven
  only in `_fmt`'s own suite — a broken delegation left all 49 consumer cases green. A
  four-tenths-of-a-cent fixture now renders through the real tile, red by name when the
  delegation breaks.
- **The cost bands have one definition.** The panel's JS mirror of `cost_bands()` was kept
  honest by a selftest asserting a *comment* was still present; the band parameters are now a
  single constant injected into the page like every other substituted value, pinned by logic
  from both sides.
- **The capture viewport fits Linux fonts** (the policy view rendered 30px taller on ubuntu
  than on the macOS the viewport was sized against), and the panel's capture gate again proved
  it reads real pages: the one non-reproducible failure it ever produced is now a named race in
  the fault ledger with its reproduction condition recorded.



**"What is this field?" cost a model.** Every explanation the plugin could give you lived in a
document you had to go and find, or in an answer you paid a model to compose — including for
questions the schemas already answer in writing. This release serves the written answers for
free, and makes the paid one a deliberate choice rather than the only one.

### Added
- **`GET /api/help` in the panel — every field, in the schema's own words.** The endpoint returns
  each dotted config and manifest path with its description **extracted from
  `schema/audit-config.schema.json` and `schema/audit-plan.schema.json` at request time**, so what
  the panel says and what your editor validates against cannot drift apart. A description retyped
  into the UI would be a second thing to keep true, which is the bug this repository has already
  shipped once (`exemptGlobs` and `tddReminder.testGlobs`, two lists disagreeing about what a test
  file is). Each field carries its type, enum, and — for config — the default the hooks actually
  fall back to, flattened out of `_config.DEFAULTS` rather than listed again.

- **Four concept pages alongside the fields, each deriving its rule from the code that runs it.**
  The plan gate's tier table is `_config.plan_gate_mode`'s own answers to the hook's own three
  questions; the areas page states `_areas.REVIEW_RULE` — the pinned sentence four documents are
  already linted against — and resolves a worked example through `resolve_review_skill`; the
  policy page is a worked example run through `_policy.resolve`, so each verdict and the basis
  beside it are the guard's words; the journal page's row shape is whatever
  `audit-journal._normalise` produces. Where the product already states something authoritatively
  in prose — the four limits of the capability policy, "tamper-evident, not tamper-proof" — a page
  **names it and cites where it is stated** instead of restating it.

- **`agents/audit-guide.md` — the conversational half, invoked on purpose.** A subagent
  (`Read`/`Grep`/`Glob`, `model: haiku`, `effort: low`) that answers questions about the plugin
  from the plugin's own README, `reference/`, schemas, `commands/*.md` and SECURITY.md, with a
  file-and-line citation per claim and "the documents do not say" when they do not. It is
  **mechanically read-only** — a fact about its tool list, not a promise in its prompt — so it
  hands you the command to run and never reports having run it. `scripts/_help.py` reads its
  frontmatter, so the panel's card cannot advertise a tool the agent does not hold, and the build
  fails if it ever gains one that writes. Being an agent also makes it **required** by the
  capability policy, which is read off the agents directory: a deny-all policy cannot switch off
  the one thing that explains the policy.

- **Deliberately NOT an auto-triggering skill.** A skill fires on what someone types, which would
  quietly bill a model for questions `/api/help` answers for nothing. The zero-token half is the
  default and the paid half is a choice you make.

- **The panel's help drawer — the surface all of that was built for.** Every ⓘ in Settings and on
  the composition levers, plus a **Help** button in the topbar, opens a side sheet carrying the
  field's dotted path, the schema's own sentence *with the file it came from cited under it*, the
  type and allowed values, the default the hooks really fall back to, and the concept page behind
  it. A side sheet rather than a centred dialog because it is read **against** the form: the
  control you asked about stays on screen beside its own explanation. Three decisions are worth
  naming. **Not one word of a concept page is in the UI** — a selftest fails the build if a topic's
  title, summary or any paragraph ever appears in `panel-server.py`, because a sentence copied
  there would render identically and be a second thing to keep true. **No path is resolved in the
  browser**: `usage.pricing.claude-opus-4-1.in` is a path into your document and the help table is
  keyed by shapes, so `GET /api/help?path=…` answers through `_help.entry_for` and echoes back
  which shape resolved it — the same bargain the Policy tab strikes with verdicts, and the reason
  a second matcher cannot drift into disagreeing with the first. And the schema's words and the
  panel's own microcopy are shown **as two labelled voices, never merged**: one describes the key
  your editor validates, the other says what this form does about it (it refuses a regex that will
  not compile; your list replaces the defaults).

- **The ⓘ is now a real button.** It was a `<span tabindex=0>` — not interactive content, so
  inside a `<label>` a click on it also toggled the checkbox it was explaining, and a screen reader
  announced it as text.

- **A shut `<dialog>` is laid out unless you are careful, and this one was not.** The UA sheet
  hides a closed dialog with `dialog:not([open]){display:none}`; an author rule of equal
  specificity beats it, so `dialog.drawer{display:flex}` un-hid the drawer the moment it closed —
  and a shut dialog sits `position:absolute` at its static position, the end of `<body>`. Every
  view carried a dead 100dvh block below the fold once help had been opened once. The only place
  it was ever visible was the full-page Overview screenshot, which grew 900px with the drawer
  printed across the bottom of it; `display` now lives on `[open]`, a check requires a closed
  drawer to measure `0x0`, and the capture tool refuses to take any shot while an undeclared
  dialog is open — the toast rule, for something that does not clear itself after 2.6 seconds.

### Changed
- **`task.skills` gained the schema description it never had**, which is what lets the panel's
  Composition levers be explained from the schema like every Settings control already is. The
  coverage check is mechanical in both directions: a control the panel binds with no schema words
  fails the build, and so does a composition lever whose schema key is renamed.
- **A doc that enumerates the shipped agents is linted against the directory.** Adding this fourth
  agent left "three pinned-tool agents" true nowhere and written in two places; `agent_doc_drift`
  now fails the build on a doc that misses an agent or states a count the directory contradicts.

### Fixed
- **A quoted frontmatter value is unquoted by the one function that knows how.** Both readers of
  the plugin's `---` blocks stripped the quotes and stopped there, so the guide agent's own
  description rendered as *"the plugin''s own README"* — YAML escapes a quote inside a quoted
  scalar by doubling it — on the one surface built to explain the plugin. The same stripper ate
  the apostrophe off an unquoted `'sup`. `_help.unquote_scalar` is now both of them.

### Verification
- **1943 selftest cases across 29 suites** (from 1859 across 28): a new `_help` suite of 59, and
  `panel-server` 401→426. Plus **13 new live checks** in `capture-screenshots.mjs` and a new
  `panel-help` screenshot, every oracle computed from the `/api/help` payload rather than from the
  drawer's own output — a check that compared the drawer with the drawer would be green for a page
  that invented every word — and `check-report-interactive.mjs` on all three shipped reports.
- **60 mutations proven red, each naming its own defect** — a config key documented in the form
  but not the schema, a composition lever with no schema words, the gate table typed out instead
  of asked of `plan_gate_mode`, the areas page restating the rule in its own words, area
  precedence quietly reversed, allow evaluated before deny, audit's own components no longer
  forced allow, a journal row losing a field, a renamed heading breaking a citation, a doc left
  saying "three", a guide handed an edit tool or an expensive model, the guide agent deleted
  outright, the `/api/help` route dropped or made writable, a topic missing from the payload, and
  a payload naming a path on this machine. For the drawer: a concept page retyped into the UI, a
  panel note become the schema's own sentence word for word, the browser growing its own path
  normaliser or truncating a path instead of asking, the ⓘ back to a `<span>`, the default typed
  out instead of read, a description shown with no source under it, a concept table drawn short,
  Back going to the index instead of the field, a card advertising a tool the agent does not
  hold, a card gaining a control that would spend a model, and the frontmatter escape published.
- **Six of those mutations changed a check rather than confirming it.** Deleting the guide agent
  reddened four checks by name and then killed the run with a `TypeError`, because three later
  checks subscripted a card that is legitimately `None` on an install without it — and the same
  trap caught `/api/help?path=`'s own checks, which read `["found"]` off a response whose missing
  key was the thing under test. A traceback exits 1 exactly like an assertion does, so the harness
  requires the expected FAIL line and not merely a non-zero exit (F3, one level down). The other
  three were checks that could not fail: the guide card's tools were asserted against the card's
  whole text, and the agent's own description names its three tools in prose, so a badge reading
  "Read · Edit" still passed; `width:100%` in the drawer's mobile breakpoint was redundant beside
  `min(31rem,100%)`, so deleting it changed nothing and it is gone rather than left looking load-
  bearing; and turning the dialog into a `<div>` reddened the focus check by timing out before it
  ran, and leaving the drawer open to prove the shot guard died on the NEXT tab click instead, because a modal intercepts it — both are mutations going red for the wrong reason, and both had to be re-aimed before the check could be trusted.

---

## [0.30.0] - 2026-08-10

**"Which of these may run here?" had no answer.** A repo could say what its agents must do and
what they must not edit; it could not say which skills, subagents and MCP servers exist for them
at all. Every capability installed on the machine was available in every project — including the
production database server that has no business being reachable from a refactor. The policy block
is the answer, and it is careful to claim only what a tool hook can actually hold.

### Added
- **`policy` in `.claude/audit.config.json` — which skills, subagents and MCP tools may be used
  in this repository**, enforced by a new PreToolUse hook `hooks/guard-capabilities.py`
  (matcher `Skill|Task|Agent|mcp__.*`).

  ```json
  "policy": {
    "onViolation": "deny",
    "agents": {"default": "deny", "allow": ["audit:*", "code-reviewer"]},
    "mcp":    {"deny": ["mcp__prod-db__*"]},
    "skills": {"areas": {"api": {"deny": ["deploy-*"]}}}
  }
  ```

  **Shipped inert**: every kind defaults to `allow` with no rules, which cannot refuse anything,
  and `_policy.is_active` says so — the hook returns on it before it even reads a manifest. A repo
  that writes nothing behaves exactly as it did before this release.

  Resolution, once, in `scripts/_policy.py`: **required** (audit's own commands, skills and
  agents) → **deny** (project-wide, or any area with work in progress) → **allow** (project-wide,
  or any active area) → **default**. Every verdict carries the rule that produced it, because a
  refusal nobody can explain is a refusal they will switch off.

  `areas` rules are scoped to a `meta.areas` tag and in force **only while a phase carrying it has
  work `in_progress`** — a hook sees a tool name, not a directory, so "in this area" can only mean
  "while this area is being worked on". Several active areas **union** their allow lists (the more
  permissive answer, documented) while any one's deny wins.

- **`onViolation`: `deny` | `ask` | `warn`.** `warn` is a `systemMessage`, deliberately **not** a
  `permissionDecision: "allow"` — that value does not mean "carry on", it means "skip the
  permission system", so an advisory written that way would silently grant more than it found.

- **`GET/PUT /api/policy` in the panel.** GET serves the block **and what it resolves to** for
  every discovered skill, agent and MCP server — computed by the same `_policy.resolve` the guard
  calls, because a preview that ran its own matching would eventually disagree with the guard, and
  a denial is the last place a panel should be creative. PUT goes through the one config writer,
  so it locks, validates, echoes its change rows and journals them.

- **The panel's fifth tab, `Policy` — the switchboard that makes the block readable.** Four words
  (`{"default":"deny","allow":["code-*"]}`) decide the fate of every skill on the machine, and
  nobody can hold that cross-product in their head. The tab *is* the cross-product: one row per
  capability the project can actually reach, carrying **the verdict and the basis** the guard
  would give it. The browser never matches a pattern itself — an edited row is marked *unsaved*
  rather than re-judged, and the verdicts are re-read from the server after every save, because
  two matchers eventually disagree and a denial is the one thing a preview must not invent.

  Three consequences worth naming. A per-row switch can only write an **exact name**, so the
  block's globs get a table of their own — in resolution order (deny before allow, project before
  area), each saying what it matches *today* — which is both where a `code-*` is added and the
  reason a wholesale PUT cannot quietly destroy a rule this form never showed. Area columns say
  which areas are **live** and which are **dormant**, since an area rule decides nothing until
  that area has work in progress and decides everything the moment it does. And the state line
  distinguishes *inert*, *turned off*, *enforcing* and **active but never seen to run here** —
  read from the marker `guard-capabilities` leaves, because a page full of denials that cannot
  say whether anything is enforcing them is claiming enforcement nobody has. Audit's own
  components are shown locked with the reason; the four limits from SECURITY.md sit one click
  above the table.

- **`/audit:doctor` reports the policy**: inert or enforcing, any capability the *plan itself*
  references that the policy would refuse (a denied review skill otherwise surfaces at phase
  sign-off, which is the worst possible moment), and whether the guard has **ever actually run
  here** — the honest local evidence for the subagent-inheritance gap below.

### Changed
- **The plugin's own components are not deniable through its own policy.** A rule matching one of
  audit's commands, skills or agents does not take effect, and is now a validator **FINDING**
  rather than a line that quietly does nothing — so the panel and `/audit` preflight both refuse a
  file that claims an enforcement nobody is getting. The claim this makes is *not removable
  quietly*, never "unremovable": removing them means disabling the plugin, which is visible in
  `/plugin` and to the doctor. The required set is **read off the plugin's own directory**
  (`commands/*.md`, `skills/*/`, `agents/*.md`) rather than typed out, so it cannot drift from
  what ships.
- **SECURITY.md states four limits in full**: subagents do not inherit parent hooks on every
  Claude Code version (anthropics/claude-code#43772), so a policy may be advisory inside one; it
  governs the tool, not the knowledge; the user's own switch outranks it; and hooks cannot gate
  hooks. Its fail-mode table also gained the two rows it had been missing — `guard-capabilities`
  and `journal-writes`, which shipped in 0.29.0 without one — and the three counts it prints
  (nine scripts, ten registrations, seven that guard) now agree with the directory.

### Verification
- **1859 selftest cases across 28 suites** (from 1692 across 26): `_policy` 60 new,
  `guard-capabilities` 26 new, `panel-server` 350→401, `audit-doctor` 66→77, `_config` 71→81,
  `validate-config` 54→63. Plus `capture-screenshots.mjs --check` and
  `check-report-interactive.mjs` on all three shipped reports.
- **The switchboard adds 14 live checks**, each measured against an oracle computed from the
  `POLICY` JSON the page was served rather than from the renderer, and **29 more mutations proven
  red** — a row that always reads *Allowed*, a basis that stops being printed, a required
  capability that can be denied, an area column that claims to be live, area rules that vanish
  from the block, an edit that is not registered as unsaved work, verdicts that are not re-read
  after a save, enforcement assumed rather than evidenced, and a policy table that pushes the
  document sideways on a phone. Two of them changed a check rather than confirming it: the
  malformed-block case died with a traceback instead of a named failure, and the pin on "the draft
  is the block as written" asked only whether the string appeared *somewhere* — it appears three
  times, so pointing one of them at the merged block left it green.
- **The `panel-policy` shot is captured against its own project and its own `HOME`.** This tab
  lists every skill, subagent and MCP server the project can reach: taken against a real machine
  the committed PNG would publish whoever captured it's plugin inventory, and the checks would be
  asserting against a set that differs per machine and is empty on CI. That discovery reached no
  further than the fixture is asserted **before** the shutter, for the same reason the demo
  identity is.
- **The wiring is checked end to end through the launcher**, in CI, beside the plan gate's: the
  selftests call `decide()` directly and so prove nothing about the matcher's payload, the stdin
  contract or the emitted JSON. Five payloads — inert, denied, allowed by rule, audit's own, and
  `warn` — go through `py-launch.sh` and are asserted on what comes back.
- **29 mutations proven red, each naming its own defect** — a lost required exemption, allow
  consulted before deny, area rules that ignore which areas are live, an intersection where the
  union is documented, a marker written on the inert path, an unthrottled marker, a refusal that
  stops naming its rule, a doctor that stops noticing the guard never fired, a preview resolved
  without the active areas, and a policy PUT that bypasses the one config writer.
- **Three of those mutations changed a check rather than confirming it.** The case-sensitivity
  case could not fail on this machine at all: `fnmatch.fnmatch` normalises case through
  `os.path.normcase`, which is the identity everywhere except Windows — so the wrong function
  passed on macOS and would have reddened only the Windows leg, i.e. somebody else's build. It is
  now pinned at the call site as well, with the needle assembled at runtime so the check does not
  contain the string it forbids. The `onViolation` fallback existed in two places (the sanitiser
  and the hook), so no single mutation could flip it — the hook's copy is gone, and the case now
  proves it reads the sanitised value. And the doctor's own OK line crashed with a `TypeError`
  under mutation instead of failing an assertion (the F3 trap): a diagnostic that dies computing
  its own output reports the wrong thing twice.
- **The panel's policy fixture creates the capabilities it resolves verdicts for**, project-local,
  instead of trusting `discover()` to find something on the machine. The first version named
  `code-reviewer` because this laptop has one installed — green here, absent on CI, and silently
  vacuous either way.

## [0.29.0] - 2026-08-10

**Who changed the plan?** Nothing could answer that. The panel wrote the manifest, `/audit` wrote
it, a hand edit wrote it, and the only evidence afterwards was `git log` — which says nothing at
all about a manifest nobody committed, and nothing ever about the config, which most repos
gitignore. Two questions had no answer: *who moved this task to done*, and *has anything been
changed behind the pipeline's back*. The audit trail is the answer to both, and it is careful
about which one it can actually settle.

### Added
- **`scripts/audit-journal.py` — an append-only, hash-chained record of every write to the plan
  and the config.** `append(project, entry) -> bool` for the writers, `append | verify | show` on
  the CLI.

  ```
  docs/audit/journal/2026-08.<writerId>.jsonl        # one file per writer per month
  {"v":1,"ts":"2026-08-10T09:12:44Z","actor":{"author":"dev@example.com","via":"panel",…},
   "action":"composition.write","target":"docs/audit/audit-plan.json",
   "summary":"1 change(s): P1.2 model: sonnet -> opus","stateHash":"sha256:…",
   "prev":"<the row before this one>","hash":"<this row>"}
  ```

  `verify` names an **edited** row (it no longer hashes to its own contents), a **deleted** or
  **reordered** one (the chain breaks there), a file **renamed** into another writer's slot (the
  first row's anchor is derived from the file's own base name — without that, a whole file could be
  copied over another writer's and verify perfectly), a **torn tail** from an interrupted write,
  and **out-of-band drift**: a document that moved with no row to explain it. The first three are
  FINDINGS and exit 1; the last two are warnings, because a crash and a `git checkout` are not
  tampering.

  **Tamper-evident, not tamper-proof**, said in every place the feature is described — the module,
  the README, SECURITY.md, the panel's own Settings card — because the limit is real: with no
  secret key, and nowhere on a user's machine to keep one from that same user, a forger who
  rewrites the whole file forward produces a chain that verifies. It is a smoke detector, not a
  vault. A feature that overstated this would be worse than none.

- **`hooks/journal-writes.py` (PostToolUse) records manifest and config writes mechanically.** A
  hook rather than an instruction in the orchestrator prose, and that is the whole design: a model
  that forgets to log a change leaves a gap indistinguishable from one somebody hid, so the record
  cannot be as reliable as compliance. It has **no stdout at all** — a recorder that talks turns
  every manifest edit into a line of transcript nobody asked for — and every failure is silent,
  because a journal that cannot be written must never break the write it was recording.
- **The panel's journal call site, which shipped in v0.28 against a stub, is now real.** A save
  says `Saved · 1 change · logged`, and `GET /api/journal` serves the recent rows **with the
  verdict beside them**: a list with no verdict invites trust, and a verdict with no list is a
  claim about something you cannot see.
- **`/audit:doctor` checks the chain**, delegating to `verify` rather than re-deriving it. A broken
  chain is its only journal FINDING — it is the only one that cannot happen by accident.
- **Config `journal.{enabled, dir}`**, with a control for each in a new **Audit trail** card in the
  panel's Settings tab (the coverage selftest derives its expectations from `validate-config`'s own
  key sets, so a documented key with no control is a build failure). `dir` unset means *beside the
  manifest*, which is what lets one commit carry both the change and the record of it — the
  orchestrator now stages the journal with each task commit and at sign-off.

### Changed
- **The journal is a third protected path.** `guard-edits.py` refuses an edit tool anywhere inside
  it — nothing legitimate writes those files by hand, and an edit there is either the accident this
  catches or the tamper `verify` is built to name. A shell write cannot be refused after the fact,
  so `guard-bash-writes.py` reports it instead, and the check runs **before** the exempt globs:
  the journal lives under `docs/audit/**`, which is exempt from the plan gate on purpose, so a
  check placed after them would have seen nothing at all. That hook now also reports **every**
  class that fired rather than the first — a command that wrote into a locked shard and into the
  journal did two separate things.
- **A boolean in a change row is spelled `true`, not `True`.** `_fmt_change` renders the confirm
  dialog's rows and now the journal's summaries; every value except a plain string goes through
  JSON. Found the moment the journal made it visible: the dialog said `enforce · not set → true`
  and the row beside it said `(unset) -> True`, which is not something the reader — who is holding
  a JSON file — can type. Same reason the areas validator spells its values in JSON.

### Verification
- **1692 selftest cases across 26 suites** (from 1552 across 24): `audit-journal` 51 new,
  `journal-writes` 30 new, `panel-server` 330→350, `_config` 59→71, `guard-edits` 18→25,
  `validate-config` 46→54, `audit-doctor` 59→66, `guard-bash-writes` 16→21. Plus
  `capture-screenshots.mjs --check` and `check-report-interactive.mjs` on all three shipped
  reports.
- **The panel's half is proven end to end in a browser**, not by a string pinned in the HTML: the
  `--check` run saves the config through the real confirm flow, then reads `/api/journal` and
  requires the chain to verify, the newest row to name the setting this check itself just changed,
  the actor to match the identity the topbar is showing, and the toast to have said `· logged`. The
  oracle is what the check DID, never the panel's own rendering of it.
- **35 mutations proven red, each naming its own defect** — 30 in the suites and 5 through the
  browser. Four of them changed a check rather than confirming it. `append()`'s "never raises"
  cases died with a *traceback* instead of a named failure, which exits 1 the same way an assertion
  does and proves nothing (the F3 trap, one level down); they now catch and report. The panel's
  `/api/journal` case passed against a **hardcoded** `ok: true`, so it now requires the verdict to
  count the rows the reader can see. `in_journal` was only ever asked about the default location,
  so a guard reading the wrong directory stayed green in `_config`'s own suite. And the Settings
  coverage check derived its expectations from a container map that could name a key the validator
  has never heard of — with `journal` dropped from `KNOWN_ROOT` it went on agreeing with itself
  about a key the hooks ignore.
- The screenshot harness stopped counting Settings cards with a number written in the check file.
  It was `4`, the audit trail makes it five, and a stale count there does not read as "a group was
  added" — it reads as "the script is not running at all". The expected cards now come from the
  group table Python injects.

## [0.28.0] - 2026-08-10

**A tag becomes a thing.** A phase has carried an `area` tag since v0.16 — free text, one string or
a list, purely a label for grouping. That is enough to *see* a monorepo and not enough to *work* in
one: the tag could not say where its code lives, who reviews it, or which conventions its subagents
should load. `meta.areas` is the other half.

### Added
- **`meta.areas` — the registry a phase's `area` tag can name.**

  ```json
  "areas": {
    "api":    {"root": "services/api", "description": "Django service",
               "reviewSkill": "backend-review", "skills": ["python-conventions"]},
    "mobile": {"root": "apps/mobile",  "description": "Expo app"}
  }
  ```

  Two things resolve against it, and both are stated in exactly one sentence wherever they appear:

  | | Resolution |
  |---|---|
  | Review skill | `phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill` |
  | Executor skills | area `skills` (per tag) then `task.skills`, deduped, **area first** |

  The first level that is **present** answers, and an explicit `null` **is** an answer — setting
  `phase.reviewSkill: null` on one phase of a reviewed project is how you say *not this one*, and
  falling through to the area would ignore it. When a phase carries several tags, **written order
  decides**; that rule is arbitrary, so the validator warns whenever it actually breaks a tie
  between two areas that disagree, naming the winner rather than letting a silent tie-break choose
  a reviewer nobody can explain. (An area saying `null` — *tests sign this off* — disagrees with an
  area naming a reviewer, so it counts; the warning prints its values JSON-spelled, since whoever
  acts on it is editing a JSON file, where `None` is not something they can type.)

  **Registration is optional in both directions and deprecates nothing.** A tag with no entry stays
  legal — v0.16 free-text tagging is the behaviour you get by writing nothing — and an entry no
  phase uses is legal too. A single-app repo writes none of this and behaves identically: the
  validator's unregistered-tag warning fires *only* in a manifest that registers areas at all,
  which is where an unregistered tag is nearly always a typo of a registered one. A typo'd tag
  resolves to no area, so the reviewer and the skills the author expected simply never happen —
  which is the failure this warning exists to make loud.

- **`scripts/_areas.py`** — the registry and the resolution, in one module with its own `--selftest`,
  imported by the validator, the status renderer, the doctor and the panel. It also owns tag
  normalisation, which the panel and `audit-status` had each written for themselves.
- **`/audit:status` shows the effective reviewer, with its basis** — `review: backend-review
  (area api)` under the phase row, beside `area: api, security`. Both facts were computable and
  neither was shown: the terminal, which is the surface a run is actually watched on, could not
  tell you which part of a monorepo a phase belonged to, and a reader had to check three places to
  learn who signs it off. The basis is printed with the answer because a reviewer chosen three
  levels away is otherwise unexplainable — and `backend-review` alone gives no hint which of the
  three files to edit to change it. Nothing is printed when there is nothing to say, so a repo with
  no tags and no reviewer pays nothing for a monorepo feature it does not use.
- **`/audit:doctor` checks the registry against the tree** — an area whose `root` is not a
  directory, and a phase tag with no entry. Both WARNINGS, never findings: areas are informational
  and must not be able to stop a pipeline. Silent when nothing is registered.
- **Panel `GET/PUT /api/areas`** — the registry plus every tag the phases actually use, each marked
  registered or not, with its phases and whether its root exists. `PUT` replaces the registry
  wholesale (a registry is a set; dropping an area has to be as expressible as adding one) and goes
  through the one composition writer, so it takes the lock, validates, echoes its change row and is
  journaled like every other write. `meta` lives on the index, so a registry save touches the index
  and no shard — asserted by byte-comparing an untouched shard, because rewriting one would
  manufacture a merge conflict on a branch nobody is on. **There is no form for it yet**; the panel
  command file says so rather than sending someone looking for a tab that is not there.
- **`/audit:init` detects a workspace** (pnpm/yarn workspaces, turbo, nx, lerna, `go.work`, a Cargo
  workspace, a `.sln`), proposes the areas it found as a multi-select, and tags the phases it
  generates. Capped at 8 with the remainder stated, since a silent cap reads as "that is all of
  them". When nothing matches, the step is skipped entirely and never mentioned — a single-app repo
  must come out exactly as it did before.

### Changed
- **`/audit:status` stopped printing machine spellings.** The phase row, the task table, the bug
  list and the RESUMABLE line all said `in_progress`. The report and the panel have read as English
  since v0.24/v0.25 via `_ui_theme.LABELS`; the terminal now uses the same map. The `[x] [~] [!] [ ]`
  markers are unchanged — they key off the machine value and are the legend `/audit:status`
  documents.

### Fixed
- **A repeated area tag counted its phase twice.** `areas_of` did not de-duplicate, so
  `"area": ["api", "api"]` — or `["api", " api"]`, which no reader can see — made a phase that was
  1-of-1 done read **2/2** in the per-area rollup, a completion figure above 100% on the one number
  a monorepo reader looks at first. Tags are now trimmed and de-duplicated in the single
  implementation both surfaces call.

- **A script could be killed by a character it could not spell.** A pipe on Windows is not UTF-8;
  it is the machine's legacy code page, and Python does not drop an unencodable character, it
  raises. One selftest case name contained a `✓`, so the Windows CI leg died inside `print` with
  the run's real result never computed — and the same fault reaches a user, because manifest text
  is user-supplied: a phase titled with a tick or an emoji would have taken `/audit:status` down
  with a traceback the moment anyone piped or tee'd it. **`scripts/_output.py`** installs the fix
  at every entry point under `scripts/`: UTF-8 first, `errors="replace"` second, so a capable
  consumer gets the real character and an incapable one gets `?` instead of a crash. Adoption is
  linted, not remembered — `entries_missing_guard()` parses the directory with `ast` and names any
  `__main__` block that does not install the guard *before it prints*, so a new script that forgets
  fails in a suite CI already runs. It reasons about what executes rather than where text sits: a
  `print` inside a `def` is a plan to print, and a textual check would have flagged all fifteen
  real scripts for code that cannot run first. `hooks/` stays importless on purpose — its product
  output is `ensure_ascii` JSON — and is covered instead by a second CI pass that runs every suite
  under `PYTHONIOENCODING=cp1252`, which reproduces the Windows-only failure on every OS.

### Verification
- **1552 selftest cases across 24 suites** (from 1429 across 22): `_areas` 55 new, `_output` 14 new,
  `validate-manifest` 47→56, `audit-status` 106→120, `audit-doctor` 52→59, `panel-server` 306→330.
  Plus `capture-screenshots.mjs --check`, `check-report-interactive.mjs` on all three shipped
  reports, the schema exercised with `ajv` over a registry it must accept and one it must reject,
  and the doctor over this repo and the example.
- **The encoding guard is proven by reproduction, not by reasoning.** `_output`'s selftest runs the
  same one-line program twice under `PYTHONIOENCODING=cp1252`, differing only in whether the guard
  is installed: unguarded it must exit non-zero *with a `UnicodeEncodeError`* and print nothing at
  all — the whole line lost, not just the glyph — and guarded it must exit 0 and still say
  everything. A third run under UTF-8 asserts the real character survives, so `replace` stays the
  floor rather than the behaviour. The adoption lint was watched failing for all fifteen scripts
  before any of them were changed.
- **24 mutations proven red**, each naming its own defect — including the two that made the
  difference between a test and a decoration. The written-order case had **two** tags but only one
  declaring area, so reversing the resolution order left it green: precedence was never tested until
  a second declaring area was added. And `ar1` asserted "no finding **and** no unknown-key warning"
  in its label while checking only the findings, so dropping `areas` from `KNOWN_META` — which makes
  every registry in the world warn as a typo — passed. A third mutation went red with a `KeyError`
  rather than a named failure, which exits 1 the same way an assertion does; the check now reads its
  fixture with `.get` so a broken endpoint is reported by the check that noticed it.
- **The prose is linted, not remembered.** The resolution is executed by `_areas.py` and *obeyed* by
  a model reading `orchestrator.md`, `manifest-conventions.md`, `review.md` and the README. Two
  statements of one rule is the drift this repository has already shipped once (`exemptGlobs` and
  `tddReminder.testGlobs` disagreeing about what a test file is), and prose drift is worse than code
  drift because nothing runs it. `_areas.rule_drift()` reads those four files and fails the build if
  any states the rule differently — including the pre-v0.28 two-level wording surviving in one of
  them, which is precisely how this would rot.

## [0.27.0] - 2026-08-08

**The lock stops being advice.** v0.26.0 made it *correct* — it can tell a live holder from an
abandoned one instead of guessing from a clock. This makes it *binding*: a session that ignores
a refusal no longer gets to write anyway.

### Added
- **The plan gate refuses a manifest write held by another live session.** `require-plan.py`
  now checks the concurrency lock before allowing a write to `manifestPath` or a phase shard.
  This is the plugin's **first denial keyed on session identity**, so the scope is narrow and
  every uncertainty resolves to *allow*:

  | Situation | Verdict |
  |---|---|
  | No lock file for that path | allow — taking a lock is honoured, not required |
  | Lock has no `sessionId` | allow — an unattributable lock must never be able to deny |
  | The lock is this session's | allow |
  | Another session, pid **alive** on this host | **deny** |
  | Another session, pid **gone** | allow, with a PostToolUse notice |
  | No git, unreadable lock, module missing | allow |

  The hazard it closes is specific: two live sessions writing one shard **in one working tree**
  produce no git conflict, because git never sees two versions. The loser's bookkeeping silently
  overwrites the winner's, and neither ever learns. An *abandoned* lock deliberately does not
  deny — nobody is writing against you, so blocking would add friction after a crash and protect
  nothing.

  The refusal names the holder, what they are doing, the basis for calling them alive, and the
  one command that resolves it. Ordinary source files are untouched by this and remain entirely
  the plan gate's business.

  **"This session" turned out to have more than one name.** The lock is taken from Bash, which
  reads `$CLAUDE_CODE_SESSION_ID`; the decision is made in a hook, which is handed `session_id`
  in its payload. Measured in a live session those are *different values*
  (`ad510b54…` vs `f6cea720…`), so the first cut of this would have locked under one identity
  and then refused the write under another — the gate denying the orchestrator its own
  bookkeeping, which is the exact bug class the previous release fixed twice. Selftests could
  not have caught it: they pass explicit ids to both sides. A hook subprocess inherits the
  parent environment, so it now compares against the payload id, `$CLAUDE_CODE_SESSION_ID` and
  `$CLAUDE_PID`, and any match is its own lock.

### Changed
- **`guard-bash-writes` reports a shell write onto a locked manifest.** A `sed -i` on a shard
  cannot be caught before it lands, so the deny above does not apply — and it was invisible
  twice over, since `manifestPath` was skipped outright and `.json` is not a source extension.
  It is now surfaced after the fact, worded as what already happened, which is all a PostToolUse
  hook can honestly say. Keeps this inside the already-documented bypass class 1 rather than
  opening a new one.

### Fixed
- **Token attribution had the same identity split, silently.** `phase.claim.sessionId` is
  written by the orchestrator from Bash (`$CLAUDE_CODE_SESSION_ID`); `meter-usage` matched it
  against the id in its own hook payload. Those are different values, so the comparison could
  only ever fail — and it fails quietly, as orchestrator spend that stays `unattributed`
  instead of landing on the phase that claimed the session. Found while fixing the same
  assumption in the lock, not by hitting it: no `phase.claim` has ever been written in this
  repo, and all 148 ledger rows here are `unattributed` for the unrelated reason that these
  sessions were not phase runs. The reader now accepts either name; every ledger row still
  carries the payload id, so the ledger's shape is unchanged. The orchestrator's instruction
  now says *which* id to write, instead of leaving it to be inferred.
- **A selftest that only passed on a day someone edited the file.** `audit-lock.py`'s j6 used
  `__file__` as a stand-in for "a file with a recent mtime", so it asserted the source file had
  been touched in the last hour. It went red the first time the full suite ran against an
  unmodified checkout. Replaced with a temp file whose mtime is set explicitly, plus the case
  that actually matters and is clock-independent: a lock whose file is *gone* reads live, never
  seizable.

### Documentation
- **`SECURITY.md`** gains a section for the one denial that is not about the plan, with the
  full situation/verdict table — anyone reasoning about this plugin's guarantees now has the
  condition rather than the headline.
- **`docs/design/audit-concurrency-report.md`** closes the enforcement gap it recorded in
  v0.26.0, with the measured cost (0.14 ms on an ordinary edit, since the check does not fire;
  19 ms on a manifest write, 11 ms of it `git rev-parse`) and the reason it was not optimised.
  What remains open is stated: that you take a lock at all is still not enforced.

## [0.26.0] - 2026-08-07

**Three rules that were right for the repo that wrote them.** A test-file exemption that knew
only the JavaScript spelling. A manifest exemption that matched one exact path while the
sharded layout writes several. And a lock that judged its holder by a clock because nothing
could ask the holder directly. Each was correct on this repository and wrong on a consumer's,
which is the failure mode dogfooding cannot see — you have to run the thing somewhere else.

### Fixed
- **The plan gate denied the orchestrator its own phase shards.** `require-plan.py` exempted
  the manifest by exact equality with `manifestPath`, but the sharded layout writes
  `<manifest dir>/phases/<phaseId>.json` on every bookkeeping step — task status, attempts,
  the commit SHA, the outcome. At the default path it worked by accident: `docs/audit/**` is
  an exempt glob and swallows the shards. At a custom path there is no such glob, and the
  ordering makes it worse than a nuisance — phase entry writes the shard while the gate is
  still at *warn*, then sets `status: in_progress`, which is exactly what flips the gate to
  *deny*. The run died one step into itself, on the layout `/audit:migrate` produces, and the
  refusal named the orchestrator's own manifest as an unplanned edit. Scoped to
  `<dir>/phases/*.json`, deliberately not to the manifest's directory: a manifest at the repo
  root would make that directory `.` and hand every file in the repo a permanent bypass.
- **The test-file exemption knew only the JavaScript spelling.** `exemptGlobs` listed
  `**/*.spec.*` and `**/*.test.*` and nothing else, so `test_cart.py` — what unittest and
  pytest discover by default — and `cart_test.go`, which the Go toolchain requires, were
  denied by the plan gate. On those stacks the exemption did the opposite of its purpose:
  red-first TDD begins by writing a failing test, and a gate that blocks that blocks the
  discipline. The same `_config.py` already listed those patterns under
  `tddReminder.testGlobs` — two lists in one file disagreeing about what a test file is. Now
  covers `**/*_test.*`, `**/*_spec.*` and `**/test_*.*` as well. This is a **wider** bypass
  by design; pin `exemptGlobs` in `.claude/audit.config.json` for the narrow set.
- **The concurrency lock decides by whether the holder is alive, not by how old the lock is.**
  See below.

### Added
- **`scripts/audit-lock.py`** — the concurrency lock as code. It was previously taken, judged
  and released entirely by the orchestrator's prose; no script acquired it, and all three code
  references only read it. A convention nobody can execute is not a lock. Now `acquire` /
  `release` / `status`, with exit codes as the protocol: **0** acquired, **3** held by a live
  run (stop), **4** the holder is gone (confirm, then `--takeover`).

  The 60-minute staleness rule was a proxy for "is the holder still alive", and it was wrong in
  both directions. A healthy 90-minute phase run read as crashed — and the protocol *itself*
  says human-confirmation pauses keep the lock, of which a phase run has at least three. A run
  that crashed after ten minutes held its lock for the remaining fifty. Measured what a
  takeover actually does: the winner overwrites the loser's claim with no error and no
  conflict, the loser's next write is accepted, and the loser then **deletes the winner's
  lock** on its way out. Neither ever learns.

  The verdict is now the holder's pid on this host, at any age; the age rule remains only where
  liveness is unknowable (no pid recorded, or a lock from another machine). Same-host is the
  right jurisdiction rather than a compromise — this lock lives in the shared git dir, so it
  only ever coordinated worktrees and clones of one machine, and `phase.claim` plus the shard
  merge conflict cover the rest. Every uncertainty resolves to *live*: a false "dead" is two
  writers and a corrupted shard; a false "alive" is a refusal cleared by deleting one file.

  Also: acquire is `O_CREAT|O_EXCL`, closing the window in the prose's check-then-write; and
  **release refuses when the lock is no longer yours**, which is how a taken-over session finds
  out. Liveness is probed through kernel32 on Windows — CPython implements `os.kill` there as
  OpenProcess + TerminateProcess, so `os.kill(pid, 0)` would silently kill the process it was
  asked about, and CI runs `windows-latest`.

### Changed
- **`/audit:doctor` stops calling healthy runs stale.** It had its own copy of the 60-minute
  rule, so it told the human a working 90-minute phase run had crashed — the diagnostic
  manufacturing the very takeover that loses work. It now reports the lock script's verdict,
  and prints the basis for it.
- **The panel distinguishes a live run from an abandoned lock.** `● running · <host>` was
  shown for any lock file, which is a claim about a process the panel had never checked. An
  abandoned lock now reads `○ lock, no live run` in the warning colour, with the basis in the
  tooltip.
- **The usage backfill lock records its pid.** A backfill that crashed used to keep the next
  one out for the rest of the hour, and the lock file named nobody — so "delete it if that is
  stale" was advice the human had no way to act on.

### Documentation
- **`docs/design/audit-concurrency-report.md`** closes C1 and re-rates it. The report had the
  false-stale direction at likelihood *Low* and did not have the false-fresh direction at all;
  both are now recorded with the measurement behind them. The report's own B2 retraction from
  v0.25.0 stands. What remains open is stated plainly: the write path still does not verify
  that the writer holds the lock, so a session that ignores an exit 3 is stopped by nothing —
  a separate decision, since it would be the plugin's first denial based on session identity.

## [0.25.0] - 2026-08-07

**Three things that were half-true.** A feature the TODO said was missing and was in fact
built but not live. A filter that was fast at the scale we test and slow at the scale we
claim. And a product whose whole thesis is a refusal, with no artifact anywhere showing a
refusal happening.

None of them were visible from inside. Each needed something measured, recorded or run
rather than reasoned about.

### Added
- **The panel's run badges are live.** `● running · <host>` and `◷ claimed · <session>`
  already existed and were already correct — what was missing was the word the TODO used:
  *live*. State was fetched once at page load, so a colleague taking a phase lock in
  another worktree appeared only if you happened to reload, which is exactly the situation
  the badges exist for. `/api/runstatus` polls every 5s.
  - **It is deliberately not `/api/state` on a timer.** That is correctness, not economy:
    full state re-renders the guards form and would discard whatever the human had
    half-typed into it. The narrow endpoint returns the lock dir and the phases' claims,
    and the client repaints Overview alone — the one view with no inputs.
  - Identical payloads do not repaint; polling stops while the tab is hidden and catches up
    on return; a failed poll is swallowed, because a panel that dies over one request is
    worse than a badge thirty seconds old.
- **A recording of the gate refusing an edit** — `docs/screenshots/demo-gate.gif`, and
  `tools/capture-demo-gif.py` that produces it. Every artifact this repo ships shows the
  product at rest; a refusal is an event, and a still frame of a denied edit is
  indistinguishable from a still frame of an allowed one.
  - **Nothing in it is typed by hand.** `audit-status.py` renders the plan and
    `require-plan.py` is fed the same `PreToolUse` payload Claude Code sends it — its
    stdout is the refusal on screen, down to `change magnitude 96 (> 80)` and the exempt
    globs. Both outcomes are real: the edit a task covers produces no output at all,
    because that is what an allow looks like from outside.
  - **CI asserts the behaviour, not the bytes.** Nothing can tell that a committed GIF has
    gone stale — it is pixels. `--check` runs the whole capture and fails if the in-plan
    edit is denied, the out-of-plan edit is allowed, or the refusal stops naming the file
    or the way out. It writes no file and needs no font, so it runs anywhere.

### Changed
- **The phases table stopped re-querying the DOM once per phase.** Measured first, at
  10/50/100/200 phases. Python was never the problem (0.38s and 2.4MB for 4000 tasks, linear
  at ~0.62 KB/task) and neither was load (249ms). The cost was in the one thing you do
  continuously: `refresh()` looped over phases and called `querySelectorAll` inside that
  loop — at 200 phases, 200 selector queries over 4200 rows, roughly 840,000 node visits,
  again on the next keystroke. Row text was re-lowercased every pass, work with a constant
  answer. The index is built once, the text cached, and typing debounced at 90ms; Enter and
  Escape bypass the debounce because they are decisions rather than typing.

      5-key typing burst, main thread blocked   333ms  ->    0ms
      one filter pass                           117ms  ->    9ms
      sort, collapsed                           708ms  ->   51ms
      expand all (JS)                          42-47ms ->    2ms

  **Expand-all's total time did not move**, and that is the honest result: repeated four
  times per build it is 196–272ms before and 203–242ms after, because what remains is the
  browser laying out 4000 rows that just became visible. An early isolated reading looked
  like a 2.5× regression and was one cheap first paint, not a difference between builds.
  `content-visibility:auto` was measured and rejected — 433ms and 228ms for the same
  operation, no clear win, and it perturbs column widths, find-in-page and printing in a
  report whose two most-used controls are Ctrl+F and Save as PDF.
- **`remind-tdd`'s throttle is described as per-session**, which is what it has always been:
  state is loaded per `session_id`, so concurrent sessions throttle independently. Two lines
  called it "global" and contradicted the header docstring.

### Decisions recorded
- **The plugin keeps the name `audit`**, decided before submission because the catalog pins
  an approved plugin to a commit SHA and the name becomes a public install id. Measured:
  2287 plugins, `audit` not taken, `displayName` used by 2 of 2287 and never differing from
  `name` — so there is no separate display lever. Kept because the prefix is typed daily
  while the name is read once, because `quality-gates` (the thesis) and `audit` (the job)
  are already the right two levels, and because the names that would cut through 2287
  entries buy memorability with precision. Its revisit trigger is observable — someone
  reporting they could not find it, or an actual collision — rather than aesthetic.
- **Submitted to the community marketplace** on 2026-08-07, awaiting screening and review.
  Recorded as submitted rather than done: the action is finished, the outcome is not.

### Validation
- **1022 cases across 20 suites** (from 1011). The scale cases pin the shape rather than the
  timings, which are machine-dependent: no DOM query inside the refresh loop, the index
  built once, text cached, sorting copying the index before ordering it, the debounce, and
  Enter/Escape bypassing it. The hot path was re-verified functionally at 200 phases after
  the rewrite — filtering narrows, Escape clears without waiting, sorting reorders in both
  directions with every task preserved and none leaking into a neighbour.

### Compatibility
No schema change, no command renamed, no flag or exit code altered. The panel gains one
read-only endpoint. The report's markup and rendering are unchanged — only the script that
filters it is faster.

## [0.24.0] - 2026-08-07

**The report stops being a table and starts being an answer.** For a product whose whole
thesis is *gates*, nothing in the report expressed one. It opened with a title, a metadata
line and a progress bar; the readiness graph that decides what you can work on next was in
the manifest and drawn nowhere; and the most actionable string on the page — the one task
you can start right now — sat at the bottom in small monospace with no affordance.

Nothing here changes what the plugin does. It changes what it says first.

### Added
- **The verdict leads.** The hero is the same verdict `audit-status.py --gate` produces,
  with the conditions that decided it printed underneath — `Checks manifest validity,
  high-severity bugs, blocked tasks. Spend is deliberately not one of them.` A hero that
  scored the plan by a private rule would be a second opinion nobody asked for; this one is
  reproducible with one command.
- **The gate rail.** A continuous spine down the phase list with one gate per phase: a
  crossbar with a gap where work can pass, solid where something holds it shut, and the rail
  **dimmed below a closed gate**. `blockedBy` has been in the manifest since v0.1.0 and had
  never been drawn — a reader could see that a phase was pending but not that another phase
  was the reason. A held phase names what holds it and links there. A signed-off one carries
  a stamp with the last commit recorded inside it, labelled as that rather than as a
  signature the manifest does not record.
- **`Next → /audit:run P2.4`, copyable**, in the hero. Reading an id off a screen and
  retyping it is a transcription error waiting to happen. The clipboard API is unavailable
  on `file://` in some browsers — exactly where this report is most often opened — so the
  fallback selects the text rather than leaving a button that does nothing.
- **An app shell: navigation at the side, actions on top.** A 70rem centred column wasted
  half a laptop and gave a long document no map. The split follows what a control acts on:
  Save-as-PDF, the markdown twin and the theme act on the document and stay in the top bar;
  search, the status chips and expand-all act on the phases table and now sit on it, where
  they were previously following the reader through the usage charts doing nothing.
  - The side nav is **not a menu of five links** — a top bar carries that fine. It is a
    position indicator for a document you scroll for a long time, so it has scroll-spy.
  - It is rendered **server-side**, from the same list the anchors are written from. Built
    by scanning headings in JS it would have been shorter and would have left every PDF, and
    every reader with scripting off, with no contents list.
  - One information architecture, two presentations: under 72rem the same items become a
    horizontal strip. Above 78rem the verdict and summary pair, verdict taking the larger
    share. On paper the shell disappears entirely.
- **The panel gets the same shell**, with the difference that matters: its four sections are
  exclusive views, not anchors, so it has real navigation — `aria-current` and a scroll
  reset — and no scroll-spy. Deliberately not collapsible to an icon rail: that pattern
  stops a long nav competing for width, and with four items it would add a control, a
  persisted preference and four hand-drawn icons to save 230px on screens that have it.

### Changed
- **The phases table renders the columns the plan actually fills.** §7 asked to collapse to
  four always-visible columns, on the reading that six of nine were blank. Measured across
  three real manifests first, and that describes the phase rows, which span the table by
  design. For task rows `model` and `risk` are 100% filled everywhere, `outcome` 35–100%,
  and `commit`/`done` track completion — an unfinished task has no commit, which is the
  column working. Only `ADO` is consistently empty (0%, 0%, 10%), because it exists for
  repos that run the Azure DevOps sync. A fixed cut would have discarded columns that are
  full for everyone to lose one that is empty for most, so: a fresh plan renders **3**
  columns, this repo and the scale demo **8**, the shipped example **9**.
- **Panel settings are named by what they do**, with the JSON key beside them.
  `h2{text-transform:uppercase}` was not merely shouting `GUARDEDITS.TOKENVARS` — config
  keys are case-sensitive, so the uppercased string could not be pasted back into the file.
  "Secrets never written to logs" cannot be typed into JSON; `guardEdits.tokenVars` tells
  you nothing about what it does. Both audiences are real and they want different strings.
- **The project path in the panel header is middle-elided on one line**, full path in the
  tooltip. `word-break:break-all` wrapped it across two rows and broke at an arbitrary
  character, so neither the root nor the project name stayed readable.
- **Typography has a point of view.** The display voice is mono, uppercase and tight — the
  stamp on an inspection record, not a marketing headline — and mono stopped being spent on
  metadata chrome.

### Fixed
- **Phase prose no longer lives at the table's scroll width.** A `desiredOutcome` was being
  laid out 683px wide inside a 34rem-min table under `overflow-x` on a 390px screen, so
  reading one line meant scrolling sideways and back, per line. It wraps inside the viewport
  now: text wraps to the reader, data tables scroll.
- **The panel scrolled sideways by 34px before anyone touched it.** The 17rem hint bubble is
  anchored left and overflows for any hint in the right half — and an absolutely-positioned
  box counts toward scrollable overflow *while hidden*, so `visibility:hidden` was not
  enough. `display:none` is, at the cost of a fade, and it flips to the right edge when
  shown, measured from that hint's own position.
- **The composition table overflowed by 96px**, because `.comptblwrap` only scrolled under
  48rem — the page had been a 64rem column the table happened to fit. Both guards were tied
  to the viewport rather than to the thing overflowing.
- All twelve README screenshots recaptured. Every one showed the pre-shell layout, which is
  the one drift a redesign cannot leave behind: they are what people see before installing.

### Validation
- **1011 cases across 20 suites** (from 968). Verified by measurement at 1920/1440/1150/
  1100/1000/390 and on all four panel views: no sideways scroll anywhere, prose capped at a
  measure, tables scrolling in their own boxes. A case pins that the header, both colspans
  and the task cells agree on the column count — a table that disagrees with itself skews
  every row — and that every nav link points at a section that exists.

### Compatibility
No schema change, no command renamed, no flag or exit code altered, and no manifest renders
differently except in layout. The `--json` rollup is untouched. A report generated by 0.23.0
and one generated by 0.24.0 describe the same plan; only the second one answers the question
first.

## [0.23.0] - 2026-08-07

**A principle you apply where you remember to is one you are persuading yourself of.**
Every release note here has said some version of the same thing: a claim carries the basis
that makes it true, or it does not get made. The routing advisory stays silent without
evidence. The projection is a range, suppressed below a sample gate. The cache section
refuses to state a dollar saving it would have to invent.

Meanwhile every dollar figure this plugin printed said nothing about the rate table it was
priced from — on five surfaces, for five releases. The HTML report named it only once the
rates were more than ninety days stale, while the Markdown twin named it every time. One
report, two answers to *on what basis*, and the more public half gave the worse one.

Nobody noticed because the case guarding it read `"2026-08-06" in html`, and the report
stamps `generated <today>`. On the day it was written its own timestamp satisfied the
assertion. It asserted nothing for four releases and failed for the first time when the
clock rolled over — which is the only reason any of this was found.

### Fixed
- **A setting that existed for one purpose and did not work.** `audit-usage.py` resolved
  `docs/audit/audit-plan.json` and nothing else, so a project keeping its manifest anywhere
  else loaded **no manifest** and then read every project value off `{}` —
  **`meta.usage.showCost` included**. A repo that had set `showCost: false`, asking for
  dollars to stay off the screen, got them printed anyway. Resolution is now
  `<argument> > config manifestPath > docs/audit/audit-plan.json`, taking the first that
  exists, falling back rather than raising on a malformed config. `/audit:panel` was taught
  to read that key long ago; `/audit:usage` never was — and the shipped example is exactly
  such a project, its own config comment warning what happens without it.
- **All five surfaces that render a cost now name the rate table behind it**: the HTML
  report, its Markdown twin, `/audit:usage`, `/audit:status` and the panel's Usage tab.
  They print `rates as of <date>`, or `rates undated (set usage.pricingAsOf)`.
  - **`/audit:status` matters most.** Its budget lines are what the preflight check reads
    before spawning the next executor, and a number that can halt a phase should say what
    priced it.
  - **There is deliberately no fallback to the default table's date.** The default carries
    one, so a fallback would nearly always render something plausible that the project never
    chose. Plausible is the argument against it. The ledger stores `costUSD` priced at write
    time and no rate vintage, so a manifest that declares nothing genuinely leaves the
    report not knowing.
  - **The panel needed a different fix for the same reason.** `usage_cfg()` merges
    `DEFAULTS`, so its `pricingAsOf` is set even for a project that never chose one. The
    server now reports `pricingAsOfDeclared` from the **raw** config as a separate fact, so
    the client cannot mistake a default for a declaration.
  - All five stay silent under `showCost: false` and when there is no spend to price.
- **The demo fixture, not the renderer.** `gen-demo-manifest.py` now declares a usage block
  like the example does. Without it the scale demo was an honest report of a badly-formed
  manifest, published on the page whose whole job is to show a well-formed one.

### Changed
- **`meter-usage.py`'s session-end line is deliberately exempt**, and that is now a rule
  rather than an oversight: **consulted surfaces carry the basis, pushed ones carry the
  minimum**. You open a report and run a command; a hook line arrives uninvited and already
  hedged to `~$2.40`. Growing it is how it becomes the message people learn to skip — the
  same reasoning that keeps that hook de-duplicated and advisory.
- **`CONTRIBUTING.md` carries the rule as a hard rule**, with the three parts that are not
  obvious until you have got them wrong: never fall back to a default to fill a missing
  basis; a basis with no claim is noise (the first version of this fix shipped exactly that
  bug, and an existing case caught it); and the consulted/pushed distinction above.
- **The roadmap's T2.12 premise was wrong and is corrected.** `claude-plugins-official` is
  curated at Anthropic's discretion — there is no application process and the submission
  form does not add plugins to it. The form feeds `claude-plugins-community`, which is the
  achievable target. The auto-propagation claim survives in a sharper form: approved plugins
  are pinned to a commit SHA and CI bumps the pin as commits land, with the catalog syncing
  nightly. Recorded in the status table beside the wrong claim, not edited over it.

### Validation
- **968 cases across 20 suites** (from 941). Both rate-basis branches on every surface, that
  the default date never leaks in, silence under `showCost: false` and under an empty
  ledger, and each rung of the manifest resolution order including the malformed-config and
  nothing-anywhere paths. The panel's Usage tab was checked in a browser, not only by
  assertion.

### Compatibility
No schema change, no command renamed, no flag or exit code altered. Two behaviour changes,
both toward saying less rather than more: the Markdown twin no longer prints `rates as of`
when `showCost` is false, and `/audit:usage` on a project with a configured `manifestPath`
now honours that manifest's `usage` block — which is the fix, and which will hide costs on
any repo that had asked for them hidden and been ignored.

## [0.22.0] - 2026-08-07

**Everything here is about the boundary.** Every release before this one made the tool
better for someone already inside it — someone who had installed the plugin, learned the
command names, and was reading the changelog. That person is not the problem. The repo has
938 test cases and four unique visitors in a fortnight.

So three changes, and they are the same change three times. The report can now be opened by
someone who never installed anything. The plugin can now be reached by someone who does not
know it is called `/audit:usage`. And the argument behind it can be read by someone who was
never going to read a changelog to find it.

None of this alters a single existing behaviour. That is the point: the tool was not the
thing that needed fixing.

### Added
- **`/audit:report --share` publishes the report to a link.** A self-contained file is
  shareable only by sending the file, and `file://` does not travel. `--share` publishes it
  as a Claude Code Artifact — a URL a reviewer opens having installed nothing.
  - **It asks first, every time, and names what is in the page**: phase and task titles,
    `desiredOutcome` prose, the file paths under audit, commit hashes, open bugs, and spend
    when `usage.showCost` is on. A `--share` in the arguments is a request, not consent.
    This is the only outward-facing thing any `/audit:*` command does.
  - The page is private until you share it from its own menu. Re-rendering an audit and
    publishing to the **same** URL is the intended loop — a stale audit link that still
    resolves is worse than no link.
- **`render-report.py --format artifact`** writes `<basename>.artifact.html`: the same
  report with no document wrapper. An Artifact supplies its own `<!doctype>`, `<head>` and
  `<body>`, so publishing the standalone file would nest a second document inside the first.
  It writes a separate file and **never overwrites the `.html`** — that one is what people
  open from disk and what CI diffs the live demo against.
- **Two thin skills, `audit-codebase` and `audit-spend`.** Skills auto-trigger on what
  someone types; commands do not. "Audit this codebase" and "what did that cost" now reach
  the plugin without knowing a command name. They carry a triggering description and a
  routing table and restate no procedure — they name the command file to read, because two
  copies of a procedure is one copy and one lie.
  - `audit-codebase` carries an explicit **do not use this for**, sending one-shot diff
    review back to `/review`. A skill that fired on "review this code" would be worse than
    silence; a skill without a negative condition is a claim without one.
  - `audit-spend` leads with `--backfill`, which needs no manifest and no agents and answers
    from transcripts already on disk. Someone asking what things cost should not first be
    sold a pipeline.
- **The essay, [`docs/essays/enforcement-over-persuasion.md`](docs/essays/enforcement-over-persuasion.md).**
  One claim with one test — *what happens when the model does not comply?* Two of its five
  sections are failures this repo shipped: the hand-maintained selftest list that drifted
  three ways, and the plan gate that denied on no evidence. It states what enforcement
  cannot do rather than leaving that to `SECURITY.md`, because an enforcement claim
  published without its limits is persuasion wearing a lab coat.

### Changed
- **The report withholds its own theme toggle when embedded**, and only reinstates a
  persisted theme where that toggle exists. The host stamps `data-theme` on the same root
  element the button writes, so a viewer who had chosen dark would have been flipped back to
  a light report saved on some earlier visit. A page that does not offer the control has no
  business reinstating its state. Standalone reports are unchanged.
- **The `commands/` vs `skills/` decision record is amended, not replaced.** It asked "is
  `commands/` going away yet" three times and answered NO-GO three times; each answer was
  defensible and the question was wrong. The cost was never deprecation — it was that skills
  auto-trigger and commands do not, true since v0.4.0, and a revisit trigger set to
  "deprecation only" could never fire on it. The answer is neither NO-GO nor migrate: both
  layouts ship. Its next trigger is now something observable in a transcript.

### Fixed
- **The HTML report showed costs without saying what priced them.** `pricingAsOf` reached
  the HTML only through the >90-day stale notice, so the ordinary report rendered dollar
  figures with no visible rate date, while the Markdown twin printed "rates as of" every
  time. Same report, two different answers to *on what basis*. It is now in the usage
  context line in both renderers — and **withheld in both when `usage.showCost` is off**,
  since with no dollars on screen it dates a table nothing visible came from.
- **The test that should have caught it asserted nothing.** `u4` read
  `"2026-08-06" in html` — and `render_html` stamps `generated <today>`, so on the day it
  was written the report's own timestamp satisfied it. It passed for four releases and
  failed for the first time when the clock rolled over, which is the only reason the gap
  above was found. It now asserts the phrase `rates as of <date>`, which no timestamp can
  produce, plus a case pinning that the date is not today's generation stamp — the trap
  the original sat in.

### Validation
- **941 cases across 20 suites** (from 921). The fragment is verified in a browser rather
  than by assertion alone: one `<html>` element and not two, no theme button, background and
  text responding to `data-theme` in both directions, and at 380px the phases table
  scrolling inside its own box while the document does not scroll sideways at all.

### Compatibility
Nothing breaks and nothing changes for an existing user who does not type `--share`. The
new format writes a new file and touches no existing one; the skills add a discovery path
beside the commands and remove none of them; `/audit:report` without arguments behaves
exactly as it did in 0.21.0.

## [0.21.0] - 2026-08-07

**The instrument stops improvising.** Two surfaces here had a number and did nothing
with it. `/audit:status` had a rollup and asked the model to lay it out — differently
every run, at a token cost, in the one command whose sibling `commands/usage.md`
already refuses that in bold. `budgetUSD` had a ceiling and enforced it nowhere: a
figure that appears in a report after the money is spent is a receipt, not a budget.

Both are the same omission. A value that only ever describes is not an instrument, and
this release is the plugin's own rule — every claim carries the basis that makes it
true — turned on the two places where it was making claims it could not act on.

> **On 0.20.0.** It was cut but never tagged: CI came back from an outage long enough
> to run on that commit and found two real failures, and this repo does not push a tag
> the build has not verified. The 0.20.0 section below describes work that first ships
> here. There is no v0.20.0 tag and never was one.

### Added
- **A phase budget now gates the work.** Three surfaces act on `budgetUSD`, and all
  three read the block `ul.phase_budgets()` already computes rather than deriving a
  percentage of their own — so they cannot disagree about what counts as over, and the
  rule that 0, negative, boolean and non-numeric all mean "no budget" stays in one
  place instead of becoming a fourth copy.
  - **Headless**, no Claude session involved: `audit-status.py --fail-on over-budget`
    (or `budget-80`) exits 1 and names the phase with both numbers — `P2 at 130%
    ($32.53 of $25.00)` — because "2 phases over budget" sends the reader hunting.
  - **In `/audit:status`**, a line per budgeted phase, WARN at 80% and OVER at 100%,
    with the overrun uncapped so 130% reads as 130%.
  - **During a run**, as preflight step 6 after the lock so an ask keeps it: silent
    under 80%, one line per phase per session at 80–99%, and at 100% an
    `AskUserQuestion` before spawning the next executor — continue, stop and resume, or
    raise `budgetUSD` to a number the human gives. It never raises the budget itself.
- **`budgetUSD` is in the manifest schema**, with `exclusiveMinimum: 0`. It had been
  validating only through `additionalProperties: true` — tolerable while it was
  decoration, not while it gates. Verified against ajv: 0, negative and `"40"` rejected;
  40 and 0.5 accepted, which is what `validate-manifest.py` already enforced. The two
  agreeing is the point.
- **`waiting on`, per task.** `unmet_refs()` reports which `blockedBy`/`dependsOn`
  targets are not done yet, and a task inherits its phase's gate as `P2 (phase)`. "Not
  ready" now says why.
- **`audit-status.py --phase <id>`** — a deterministic entry view for `/audit:phase`
  and `/audit:next`. Scoping changes only which phases are listed; totals stay
  whole-plan and the output says so, because a phase view that quietly rescoped them
  would misreport the project.
- **`workflow_dispatch` on the CI workflow.** A push was the only thing that created a
  run, so a commit whose run was never created had no way to get one — during the
  2026-08-06 Actions outage six commits landed on `main` with zero runs between them,
  and the only ways to verify the tip were an empty commit (which changes the sha you
  would tag) or a throwaway PR (whose run is on a merge ref, not on `main`). Neither
  verifies the thing being released. `gh workflow run ci.yml --ref main` now does.

### Changed
- **`/audit:status` renders in Python, not in prose.** `render_status()` produces the
  whole report; `--json` is byte-identical to before, verified by diffing both
  revisions against a 1000-task manifest, so nothing consuming the rollup breaks. It
  reuses `audit-usage.py`'s `bar`/`table`/`fmt_tokens`/`fmt_cost` rather than
  reimplementing them, because those carry rules this output must not contradict —
  chiefly that real spend never renders as `$0.00`.
  - **One table, not one per phase.** Column widths are computed across every task and
    the header printed once. Per-phase tables re-derived their own widths, so a
    fifty-phase manifest would have produced fifty header rows and fifty alignments —
    the columns would have stopped being columns.
  - **The ready list folds at 12** and states the true count and the remainder. A
    wide-open plan had 464 ready tasks; a silent cap reads as "that is all of them",
    which is the worst failure a to-do list can have.
  - The rollup itself is **untouched**. Adding per-task `model`/blockers/commit would
    have grown the payload the panel fetches on every state read from 22KB to roughly
    ten times that, for consumers that never asked for it. What mattered was that the
    *model* stop reading the manifest, and the renderer runs in the process that
    already loaded it.
- **The doctor reports a missing runner as WARNING, not FINDING.** It exited 1 on
  `runner not on PATH: plugin-validate (claude)` in a job that deliberately does not
  install the Claude CLI. The observation was correct; the severity was not. Every
  other FINDING is a defect in the **repo** — an invalid manifest, a malformed config,
  broken shards. A runner that is not installed is a gap in **this machine**, and
  failing a build over an accurate statement is how a doctor teaches people to ignore
  it.
- Neither budget condition is in the default gate, deliberately. Spend is a signal, not
  a defect, and failing someone's merge over a phase at 105% they never agreed to gate
  on is how a gate becomes something people switch off. The interactive check gates
  *starting* work, never finishing it — a task mid-edit is not interrupted for spend,
  since stopping there strands a half-finished change.
- Every budget surface stays silent when `usage.showCost` is false. A budget is a claim
  about money; naming dollars there would leak exactly what that setting exists to hide.

### Fixed
- **The Windows selftest leg, which had never run this code.** `audit-usage.py`'s slug
  case asserted `"-Users-x-repo" in project_slug_candidates("/Users/x/repo")`. `abspath`
  on Windows prepends the drive, so the strict slug is `D:-Users-x-repo` — and `x in
  [list]` is exact membership, not containment, so that assertion could only ever pass
  on POSIX. The function was right; the test was the thing tied to one operating
  system. `audit-usage.py` was added in 0.17.0 and the last CI run before 2026-08-06
  was on v0.16.0, so the Windows leg had never once executed the file.
- **The selftest step that hid the failure.** It captured stdout into a variable and
  echoed only the last line, so under `set -e` a failing suite aborted before printing
  anything — the Windows log showed a filename, then `exit code 1`, and nothing else. It
  prints the full output on failure now. A step that withholds its diagnostics in
  exactly the case you need them is worse than one that prints everything.
- **Three doctor cases depended on git being installed.** The suite ran `git init`
  without checking it worked, then asserted a git root resolves. Proven by running
  against a `PATH` holding python and nothing else, which surfaced a fourth: the finding
  names `meta.gitRoot` when the directory is not a repo, but names the missing binary
  when git is absent. 44/44 with git absent, 47/47 with it present.
- **Ledger discovery returned a mixed-separator path on Windows.** `ledgerDir` is
  authored in JSON and ships as the literal `".claude/usage"`, so `os.path.join` built
  `C:\proj\.claude/usage`. That opens directories fine, which is why it survived — it is
  wrong only where the path is compared or printed, and `audit-status.py` puts it in the
  `ledgerDir` field of the JSON the panel reads. `find_ledger_dir` normalises every path
  it returns now, which is the rule `panel-server.py` already applied to the manifest
  path. Three selftests had been asserting exactly this and could only fail on Windows;
  the fix is in the function, not in them.
- **`encoding="utf-8"` pinned on the last three unguarded fixture writes**
  (`migrate-manifest.py`). Harmless today — `json.dump` defaults to `ensure_ascii` — but
  the Windows default is cp1252, so the first fixture to gain an em dash would fail on
  one platform only. Found while auditing for the rest of the class the Windows leg
  exposed; that audit came back otherwise clean.
- Truncation marks elision with `...` and backs up to a word boundary. A bare slice
  produced `Fix BUG-3: cart total off-by-one with st`, which reads as corruption.

### Validation
- **921 cases across 20 suites** (from 864). Including: a repo with no budgets and a
  repo with no metering both trip nothing — a budget gate that fires where no budget
  exists would be the worst possible version of this; a satisfied gate reports nothing
  rather than an empty warning; and cost is withheld when `showCost` is false.

### Compatibility
The manifest schema gains `budgetUSD` as a described, constrained property — it was
already accepted and already rendered, so no existing manifest becomes invalid unless
it declared a `budgetUSD` of 0 or below, which never meant anything. `--json` output is
byte-identical. No command changes its name, flags or exit codes except the two new
`--fail-on` values and `--phase`, both additive.

## [0.20.0] - 2026-08-06

**The gate learns what it knows.** Every release before this one could say "nothing
breaks." This one cannot, and saying so plainly is the point: the plan-first gate
denied on its weakest evidence, and fixing that changes a default.

In a repo with no manifest there is no plan to check an edit against, so the gate fell
back to a heuristic — one small file per session, then deny. That is not enforcement
of a discipline; it is a default-deny on an empty policy, and it was the one surface
here exempt from the rule every other one follows. The routing advisory stays silent
until it has three comparable tasks. The cost report prints the thresholds behind
every number. The gate issued its strongest claim where it knew the least.

So it is graded on the evidence it actually has: **observe** with no manifest,
**warn** with a manifest but no phase running, **deny** once a phase is `in_progress`.
`enforce: true` restores always-on deny. Not a softening — the thesis applied to the
surface that was skipping it.

### Changed — behavior, read this before upgrading
- **The plan gate no longer denies in a repo without an audit manifest.** It records
  what it would have held and says so once per session. A repo that relied on
  always-on deny needs `"enforce": true` in `.claude/audit.config.json`.
- **The shell-write plan gate in `guard-secrets-read` is graded identically**, so
  `Edit src/x.ts` and `sed -i src/x.ts` now agree on the same file. Leaving one
  graded and the other not would have made the verdict depend on which tool the agent
  happened to reach for.
- **No secret guard is graded.** Secret reads, the token-logging ban and the shell
  secret checks deny at every tier, with or without a manifest — reading `.env` is
  wrong whether or not a plan exists. If you rely on this plugin for secret
  containment, nothing changed.
- The deny message is rewritten. It says "outside the running plan" and names a cheap
  exit, rather than asking someone who has never run `/audit:init` to hand-author a
  schema-validated manifest. A guard whose cheapest exit is a bypass keyword teaches
  people to reach for the bypass keyword.

### Added
- **`/audit:doctor`** — answers "is this working?" before you find out the hard way:
  the interpreter the *hooks* will resolve (not the one running the script), whether
  `gitRoot` is a repo, config and manifest validity, shard integrity, which plan-gate
  tier is active, submodule conflicts that would fail at commit time, whether the
  `buildCommands` runners exist, whether a hook has ever fired in this project, and
  the usage ledger. Read-only: no writes, no lock, and it never executes a
  `buildCommands` entry. Exits 1 on findings, so CI can run it too.
- **`enforce`** config key — force the plan gate to deny regardless of evidence.
- **`gen-demo-manifest.py`** — a deterministic large-manifest fixture. The panel
  screenshots and the scale demo both needed one and neither had it, which is why
  neither could be refreshed.
- **`tools/capture-screenshots.mjs`** — screenshot capture that asserts its own
  preconditions (the panel must expose a Usage tab; expanding the composition table
  must change the visible row count; progress bars must paint a real width) and waits
  for animations to settle before every shot.
- CI now drives all four gate tiers through `py-launch.sh`, runs the doctor against
  this repo and the example, and gates the live demo and the scale demo.

### Fixed
- **The report's progress bars had never painted, for anyone.** The fill is a
  `<span>` whose rule declared no `display`, and an inline box ignores width — so
  every bar was 0px at every percentage since the 0.12.0 redesign, including phases
  at 100%. This is why every committed screenshot showed an empty bar.
- **A missing semicolon after `--ease` annexed the comment block and the `--sp-0`
  declaration that followed it**, making every `animation`/`transition` shorthand
  that referenced it invalid at computed-value time. All report animations and
  transitions were dead and `--sp-0` resolved to nothing. `_undeclared_css_vars`
  could not see it: the annexed text still reads as a declaration.
- `fillIn` and `fadeUp` declared only a `from` keyframe while asking for
  `fill-mode: both`. Latent while the easing token was broken; repairing it made them
  run and pinned the summary card at opacity 0.
- **The per-phase task-status filter could never be seen.** The row, its label and
  its chips were emitted into every report and populated from JS, while the
  stylesheet said `display:none` and the script cleared the inline style instead of
  setting one.
- The report declared no language — there was no `<html>` element to carry `lang`.
- Sortable column headers were mouse-only, with no role, tab stop or `aria-sort`;
  the sort order was conveyed by a CSS arrow alone. Filter chips conveyed their
  state by colour alone.
- Three tables showed a pointer cursor on headers that do nothing; the cursor is now
  scoped to the attribute `wireSort()` itself sets.
- A port collision printed a Python traceback — the bind had no error handling while
  the existing guard wrapped only the serve loop.
- **The panel printed its session token to stdout**, putting a live credential in
  terminal scrollback and in the Claude transcript — the same value whose pidfile is
  gitignored with the note "Never history". It is printed only when the caller must
  open the URL by hand.
- `/audit:panel` on an already-running panel refused with a link instead of opening
  the panel that was asked for.
- An unbalanced brace had been shipping in the panel stylesheet. Harmless at top
  level; the same slip one level deeper drops every rule after it.
- **`tddReminder.inProgressPolicy: "warn-always"` was rejected by both validators**
  while being documented in four places, implemented, and covered by a passing
  selftest — so following the documentation produced an invalid config.
- **The shipped config template produced nine warnings from this plugin's own
  validator**: `"//"` and `"//<key>"` are the annotated-comment convention the
  template itself ships, because JSON has no comments.
- `docs/index.html` — the live demo and the README's "See it" target — had been a
  month stale with no Usage section at all. `docs/demo-large.html` had been serving a
  report rendered from an *invalid* manifest, banner included.

### Validation
- Selftests are **globbed, not enumerated**. The hand-maintained list had drifted
  three ways, and `gen-demo-usage.py`'s cases were never run by CI at all. Every
  `.py` under `hooks/` and `scripts/` must now carry a `--selftest`; a file without
  one fails the step rather than being silently skipped.
- 864 cases across 20 suites (from 675 across 17).
- Per-file case counts are gone from `PLUGIN-BUILD-GUIDE.md`. All ten were stale.

### Compatibility
The manifest schema is unchanged and every existing manifest keeps working. The only
behavioral change is the plan gate's default, above.

## [0.19.0] - 2026-08-06

**Spend becomes a signal.** 0.18.0 made token spend readable. This makes it
*actionable*: tasks are banded by what they cost, phases can carry a budget, the
metering hook speaks up while there is still time to act, and the ledger's own
evidence — never a price list — is what backs a routing recommendation.

### Added
- **Cost bands** — every task is `typical` / `high` / `outlier`, calibrated from
  **this project's own** completed tasks (median / p90), so it means something on
  day one with no configuration. Pin absolute thresholds with
  `usage.bands.highUSD` / `outlierUSD` when you have a real budget; a malformed or
  inverted pair falls back to the relative basis rather than banding wrongly.
  Suppressed below 5 completed tasks. Every surface prints the thresholds it used.
  Deliberately **not** called risk — tasks already carry `risk`, meaning risk of
  the *change*.
- **One advisory, once.** When the task in flight passes `outlier`, `meter-usage`
  emits a `systemMessage` naming the task, its cost and the threshold. Fires once
  per task per session and blocks nothing — a `Stop` hook could not block anyway
  (`decision: "block"` there means "do not stop"), and stopping mid-edit on spend
  would strand a half-finished change.
- **Session cost summary** on `SessionEnd` — one line, where the work happened.
  Silent when the session recorded nothing.
- **Per-phase budgets** — optional `budgetUSD` on a phase, with a burn-down in the
  report and panel. The bar caps at the track but the number does not, so an
  overrun reads as 130%. Phases without a budget are counted in a footnote, never
  drawn at 0% — an unbudgeted phase is not a phase at zero.
- **Model-routing recommendation**, gated hard enough to be worth trusting: within
  one risk band only; the cheaper model must already have run ≥3 tasks in that
  band **in this repo** at no worse an attempt rate; both models need real rates,
  never a `_default` guess; and the saving must clear a percentage *and* an
  absolute floor. On a well-routed project the output is silence. The figure is a
  re-priced counterfactual — the same tokens at the other model's rates, both
  sides at today's prices — and says so.
- **Model mix** in the browse tables for phase, task and author rows: a stack in
  slot order with the dominant model named, exact split on hover.
- **Export report** from the panel — renders the standalone HTML and its Markdown
  twin and opens it through the panel's own origin (a browser will not follow a
  `file://` link from an `http://` page). No PDF library: the report's print
  stylesheet already does Save-as-PDF.

### Fixed
- `usage_state`'s no-ledger stub was missing keys the populated branch returns,
  handing a fresh install `undefined` for part of the Usage tab.
- A second `findingsBox()` would have hoisted over the save-result one and broken
  every config save.
- `/audit:panel` pidfile (live pid, port and session token) is now gitignored.

## [0.18.0] - 2026-08-06

**The usage dashboard.** 0.17.0 answered "what did that cost?" with numbers.
This makes those numbers *readable*: a seeded demo ledger so the example
actually shows the feature, an analytics layer that refuses to overstate what it
knows, and a report and panel rebuilt around one interaction model.

### Added
- **Analytics with honesty guards** in `usage_ledger.py` — `series` (top-N with a
  stated remainder), `compare` (vs the previous window; `null` on a first run
  rather than an invented trend), `cache_profile` (a rate comparison, never a
  fabricated dollar saving), `unit_economics` (a p25–p75 range, suppressed below
  5 completed tasks), `retry_cost` (retried and blocked reported *apart*, never
  summed into "waste"), `routing` (compared **within** a risk band, because the
  pipeline routes hard work to the strong model on purpose) and `coverage`.
- **`scripts/gen-demo-usage.py`** — a seeded, deterministic ledger generator, and
  a committed 166-row ledger for `examples/acme-store` (93.1M tokens, 4 models,
  3 authors). CI asserts the committed ledger reproduces byte-identically.
- **Drill-down panel** — one filter state with a *derived* chart dimension, so
  clicking a line and using the dropdowns can no longer disagree. Clickable rows,
  columns and lines; active-filter chips with `Esc` to pop the last one; a
  browse dialog with search and sortable columns for lists past the fold.
- **Compact tooltips** on both surfaces. In the report the hover text lives in the
  mark's own `title`, so the file still explains itself from `file://` with
  JavaScript off.
- A **context line** (phases · people · models · sessions · span · resolution) —
  orientation without spending a metric tile on a count nobody acts on.

### Fixed
- **Colliding hues past 8 entities.** Slots were assigned by alphabetical index
  capped at 8, so 40 authors shared one red between 33 of them. Slots now go to
  the entities actually drawn, ordered by global spend, so a filter never
  repaints a survivor and two series never share a colour.
- **Charts stretched their own type.** `preserveAspectRatio="none"` scales the
  coordinate system non-uniformly — measured at +49% glyph width in the report
  and +38% in the panel. The panel now renders 1:1 against a measured viewBox;
  the report moves its axis labels out of the stretched space into HTML.
- **250 daily points of spaghetti.** Long spans roll up into natural bins (week /
  4 weeks / quarter) and every surface *names* the bin it used.
- **Small multiples did not share an x axis** — each author spanned only their own
  active days at the same pixel width, so the same x meant a different date per
  panel.
- **Sub-0.05% bars painted nothing**, reading as "no data" rather than "a little".
- **1009 validation findings joined into one unbounded paragraph.** They were four
  mistakes repeated; the panel now groups by shape with counts and keeps the raw
  list one click away.
- One number format everywhere: token magnitudes are compact (`3.2M`, two
  decimals on hover), countables keep their separators. A selftest guard fails if
  any token value regresses to `3,230,000`.
- `meta.usage` is a known manifest key — the shipped example no longer warns
  against the plugin's own validator.

## [0.17.0] - 2026-08-06

**Token usage, attributed.** The most common tester question — "what did that
cost?" — now has an answer at every surface: a CLI, the report and the panel.
Spend is broken down by phase, task, model, **author** and time window, and work
that happens outside the pipeline entirely (ad-hoc edits, `#no-plan`) is still
counted rather than quietly dropped.

### Added
- **`/audit:usage`** — token spend with cache economics, cost-per-task, a daily
  trend and peak/quiet hours. Filters: `--by phase|task|model|author|agent|day|
  hour|session|branch|attr`, `--phase/--task/--model/--author/--attr`,
  `--since 7d|2w|3m|<date>`, `--until`, `--top`, `--no-cost`, `--json`.
  `--backfill` rebuilds the ledger from transcripts already on disk (idempotent).
  The script renders its own ASCII output and the command prints it **verbatim** —
  a usage tool that spends a pile of tokens formatting its own tables would defeat
  its purpose.
- **`meter-usage.py`** on `Stop` / `SubagentStop` / `SessionEnd` — tails the
  session transcript (and each subagent's) from a saved byte offset and appends to
  `.claude/usage/<YYYY-MM>.jsonl`. Advisory and fail-silent, like every other
  non-guard hook.
- **`scripts/usage_ledger.py`** — the shared metering core (scan, dedup, attribute,
  price, aggregate), used by both the hook and `--backfill` so there is one
  implementation and no drift.
- **Usage section in `/audit:report`** — stat tiles, per-phase stacked bars
  segmented by model, a daily column chart and a day × hour heatmap. Hand-rolled
  inline CSS/SVG: the report stays one self-contained file with zero network
  fetches. The categorical palette is validated for colour-vision deficiency and
  contrast against the report's own light and dark surfaces, and segments are
  drawn in slot order so the rendered adjacency matches the validated adjacency.
- **Usage tab in `/audit:panel`** — the same data with live filtering by model,
  author, phase and date range. The server ships facts; the browser re-aggregates,
  so a filter change never round-trips. Read-only; takes no lock.
- **`usage` config block** (`.claude/audit.config.json`) — `enabled`, `ledgerDir`,
  `authorMode` (`email`/`name`/`hash`/`none`), `showCost`, `backfillOnFirstRun`,
  `maxScanBytes`, `currency`, `pricingAsOf` and a `pricing` table in USD per
  million tokens. Rates live in config so a price change is a one-line edit in your
  repo, not a plugin release; cost is priced and stored at write time, so editing
  the table never rewrites history.
- **`meta.usage`** in the manifest (`ledgerDir`, `showCost`, `pricingAsOf`) — the
  commands' half of the plugin's standing split (commands read project values from
  manifest `meta`, hooks from `audit.config.json`). Both default to
  `.claude/usage`.
- **Optional `usage` key on the `audit-status.py` rollup**, and a one-line spend
  summary in `/audit:status` — read from the rollup already fetched, not a second
  command.

### Changed
- `reference/orchestrator.md` now asks the orchestrator to prefix the executor
  Agent's `description` with the task id. That one word is what makes per-task
  attribution exact when a phase runs tasks in parallel; without it spend simply
  falls back to phase level, so it never blocks a run.
- `.gitignore` covers `.claude/usage/`, with a note on the `*.jsonl merge=union`
  route for teams that want a shared ledger.

### Fixed
- Cache-write spend could be over-counted. Real transcripts contain entries whose
  `cache_creation_input_tokens` total is `0` while the TTL breakdown still reports
  a non-zero 1-hour figure; the breakdown is now clamped to the authoritative
  total. Found by reconciling against this repo's own transcripts, where it
  inflated one session by 2,494 tokens.

### Compatibility
- Nothing breaks. The `usage` rollup key is present **only** when a ledger exists,
  so every existing consumer of `audit-status.py --json` is untouched; the report's
  Usage section renders as nothing at all without one. Schema changes are purely
  additive (`meta.usage`, `usage`), and both existing manifest layouts validate
  unchanged. `render_html`/`render_md` gained an optional trailing argument and
  keep their old call shape. Metering is on by default and disabled with
  `usage.enabled: false`; the ledger records counts, model ids, timestamps, branch
  and author — never prompt content (see SECURITY.md). Selftest suites 14 → 16;
  `claude plugin validate` covers the new command (14 → 15).

## [0.16.0] - 2026-07-30

Richer **per-phase configuration** and **monorepo/multi-team ergonomics** — all
additive and backward compatible (single-file and sharded manifests unchanged).

### Added
- **Per-phase `reviewSkill`** — a phase overrides `meta.reviewSkill` at its own sign-off
  (resolved `phase.reviewSkill ?? meta.reviewSkill`), so a monorepo reviews backend vs
  mobile vs web phases with different reviewers.
- **Phase `area` tag(s)** — a single string partition (`"backend"`) OR a list of tags for
  cross-cutting concerns (`["backend","security"]`; any vocabulary —
  devops/security/embedded/data/ml/…). The rollup groups a phase under **each** tag (a
  `security` area collects security phases across every app); the report and the panel
  Overview/Composition render a badge per tag and make it searchable.
- **`/audit:worktree <phaseId>`** — creates (or `--remove`s) a git worktree for a phase and
  prints the `cd … && claude` line, removing the manual setup for the sharded
  parallel-phases workflow. Never edits the manifest.

### Compatibility
- Nothing breaks — a plain-string `area` still validates (schema stays permissive); all 14
  selftest suites pass on both layouts; `claude plugin validate` covers the new command
  (13 → 14). Ships as PRs #11–#14 (this being #14).

## [0.15.0] - 2026-07-30

Safe **parallel phases** across worktrees/sessions, and **fewer tokens per phase** —
via an opt-in **sharded manifest layout** (an index + one file per phase). Fully
backward compatible: single-file manifests keep working, and reading is transparent.

### Added
- **Sharded manifest layout (`meta.version: 3`).** `manifestPath` becomes an *index*
  (meta · bugs · fileIndex) whose phases are `{id, title, shard}` stubs pointing at
  `phases/<phaseId>.json`, where each phase's full body lives. A phase command loads
  only its own phase (**fewer tokens** at scale), and two phase branches edit different
  files so they **merge without a manifest conflict**. Whole-tree work (status, report,
  validate, readiness) is assembled off-context by the dependency-free scripts.
- **`scripts/_manifest_io.py`** — the dual-format loader/writer: `load_manifest`
  reads both layouts into the same assembled dict; `save_sharded`/`split_manifest`
  write the sharded form atomically. Wired into all five scripts and the guard hooks'
  in-progress read path.
- **`/audit:migrate`** (+ `scripts/migrate-manifest.py`) — opt-in, reversible
  conversion to the sharded layout: validates the source, refuses a mid-run migration
  (unless `--force`), backs up to `<manifest>.bak-<UTC>`, writes index + shards, and
  restores the backup on any post-migration failure. `--renumber` repairs duplicate
  `BUG-` ids from a cross-machine collision; `--dry-run` previews.
- **Optimistic phase `claim`** — a run records `{sessionId, host, branch, at}` in the
  phase shard, so a same-phase double-claim across machines surfaces as a shard merge
  conflict. `validate-manifest` gained claim shape + stale-claim checks.

### Changed
- **Locks moved to the shared git dir** (`$(git rev-parse --git-common-dir)/audit-locks`)
  and are now **two-tier**: a brief **index lock** (structural writes + id allocation)
  and a per-phase **shard lock** (a phase run). They coordinate across worktrees on one
  machine and no longer live in the working tree (so `git status`/hooks never see them).
  Falls back to the legacy `<manifestPath>.lock` when there is no git repo.
- **Id allocation is now collision-proof** — done under the index lock (read max, +1,
  write, release); a rare cross-machine duplicate is caught by the validator and
  repaired with `/audit:migrate --renumber`.
- **A phase run writes only its shard.** Bug status is **derived** from the linked task
  (a bug materialized into a `done` task reads as `fixed`, `fixedIn` = that commit), so
  a run never writes the shared `bugs[]` — keeping parallel phases merge-clean. The
  per-task commit stages the shard, not the index.
- **Schema v3** documents the sharded layout: a phase requires only `id`/`title` (an
  index stub omits `status`/`tasks`; the referential validator enforces them on the
  assembled manifest), with `shard`/`claim` and a `claim` `$def` added. v2 manifests
  validate unchanged.

### Compatibility
- **Nothing breaks.** Legacy single-file manifests keep working indefinitely (dual-read);
  migration is opt-in. A mutating command notes once that `/audit:migrate` is available.
  All script/hook selftests pass on both layouts; CI, `--gate`, report filenames, and
  ADO sync are unaffected (they go through the scripts).

## [0.14.0] - 2026-07-22

The control panel's Composition tab scales — a compact, collapsible, filterable
table replaces the per-task cards, staying fast and readable at hundreds of tasks.

### Changed
- **Control-panel Composition tab is now a compact, collapsible, filterable table.**
  Replaced the big per-task cards (which didn't scale) with the report's proven
  shape: phases are collapsible group-rows (collapsed by default) over a dense table
  (`id · title · status · model · skills`), plus a filter toolbar — text search
  (auto-expands matches), phase-status chips, a **"needs skills"** bulk-assign
  filter, expand/collapse-all, and a live count. Verified against a 50-phase ×
  20-task (1000-task) manifest; the panel stays fast and readable. The edit/save
  contract (`PUT /api/composition`) is unchanged; the state view now also carries
  each phase/task `status`.

## [0.13.2] - 2026-07-22

`/audit:panel` becomes a clean open / stop / status lifecycle — a running panel is
always discoverable and stoppable (a per-project pidfile), never a stray process.

### Added
- **`/audit:panel` is now an open / stop / status trio.** The panel server writes a
  per-project pidfile (`.claude/audit-panel.json`) on launch, so a running panel is
  always discoverable and stoppable — no stray background process:
  - `/audit:panel` opens it (and reports the live URL); a second open just points at
    the already-running one instead of spawning a duplicate.
  - `/audit:panel stop` stops it (`panel-server.py --stop`); `/audit:panel status`
    reports whether it's running and where.
  - New `panel-server.py` flags `--stop` / `--status`; clean shutdown on SIGTERM and
    Ctrl-C removes the pidfile.
  - For a foreground/visible run, a terminal one-liner still works, and Node repos can
    use `npm run panel` / `npm run panel:stop`.

## [0.13.1] - 2026-07-22

A UX pass on the `/audit:panel` control panel (all in the served UI; no API change).

### Changed
- **Info-hint labels** — every field and section label carries an ⓘ hint with a
  plain-language tooltip, so the raw config keys are self-explanatory.
- **Custom autocomplete** — replaced the native `<datalist>` with a combobox: the
  menu opens directly under the input, with a limited height + scroll and clear
  items (name + source badge + description) and full keyboard + click select. Used
  by `meta.reviewSkill` and per-task `skills`.
- **Tabbed registry** — "Available building blocks" is now one table with
  Skills / Agents / MCP sub-tabs (name · source · description, sticky header),
  replacing the stacked lists.
- Fixed `model`/`skills` top-alignment in task rows.

## [0.13.0] - 2026-07-22

A visual, on-demand way to manage the plugin: `/audit:panel` launches a local
control panel to edit the per-repo config (now schema-backed) and wire the manifest's
composition levers — with discovery of the skills & agents actually available. The
shareable report is unchanged (still self-contained / zero network fetch).

### Added
- **`/audit:panel` — a local control panel for config + composition.** An ephemeral,
  on-demand Python-stdlib server (Ctrl-C to stop; not a running service) serves a
  themeable browser UI (the report's Slate & Teal system, light/dark, responsive)
  to visually manage the plugin:
  - **Guards & paths** — a form over `.claude/audit.config.json`, now backed by a
    JSON schema (`schema/audit-config.schema.json`) + a `validate-config.py`
    validator; edits are validated before an atomic write.
  - **Composition** — set `meta.reviewSkill`, per-task `skills`/`model`, per-phase
    `review.model`, and `meta.buildCommands`, with pickers **populated by discovery**
    of the skills & agents actually available (project `.claude/`, `~/.claude/`, and
    installed plugins) plus the MCP servers in scope. Writes back only these
    composition fields — never structural CRUD — validated via `validate-manifest.py`.
  - **Overview** — the live rollup + validation status.
  Safety: binds `127.0.0.1` only + a per-launch token on every API call, refuses
  writes that escape the project dir, and refuses manifest writes while
  `<manifestPath>.lock` is held. New: `commands/panel.md`, `scripts/panel-server.py`,
  `scripts/validate-config.py`, `schema/audit-config.schema.json`. The shareable
  report is unchanged (still self-contained / zero network fetch).

## [0.12.0] - 2026-07-16

A visual/UX overhaul of the HTML report: a modern, themeable, responsive design
built on CSS tokens — light + dark, a pipeline-rail signature, refined components,
and tasteful motion — with every interaction and invariant of the previous report
preserved (one self-contained file, zero network fetches, escaped, print-safe).

### Changed
- **Report redesign — a modern, themeable visual system.** The HTML report moves
  onto CSS design tokens (a "Slate & Teal" palette) with **light + dark themes**:
  it follows the OS by default and adds a toolbar toggle that persists. The phases
  table gains a **pipeline rail** — a continuous status-colored spine with a node
  per phase and per-task rail segments — as its signature, plus soft cards for the
  overall/summary bands, pill buttons + a primary Save-as-PDF action, refined
  status/risk chips, a monospace tabular data-face for ids/SHAs/dates, an animated
  progress fill, and toolbar elevation on scroll. Tasteful motion throughout,
  gated by `prefers-reduced-motion`; still one self-contained file, **zero network
  fetches** (system fonts only), fully escaped, keyboard-navigable, **responsive**
  (on phones/tablets the wide tables scroll inside their own frame instead of the
  page), and print/PDF renders on a light A4 sheet regardless of theme. Verified in a browser (light +
  dark, all interactions, reduced-motion). Status/risk colors moved from inline
  styles into theme tokens keyed off `data-status`/`data-risk`.

## [0.11.0] - 2026-07-16

Turned the report into a shareable, scalable artifact and gave the plugin a real
front door. The HTML report is now one collapsible, filterable table that scales
to 40+ phases, prints to PDF, and can carry an AI summary; a curated
`examples/acme-store/` audit + a GitHub Pages demo + README quickstart/screenshots
let people see what the plugin does without installing it.

### Changed
- **Interactive report scales to large audits.** The HTML report is now one
  collapsible table: each phase is a group-row (status chip, progress bar,
  desired outcome) that expands to its task rows on click; phases are **collapsed
  by default**, so a 40-phase / 200-task audit opens as ~40 scannable rows
  instead of one endless scroll. Filtering is split by level: the toolbar holds a
  **phase** text search and **phase-status** chips, both *visually removing*
  non-matching phases; a **task-status** filter is **contextual** — it appears
  inside each phase when expanded and filters only that phase's tasks (filtering
  one phase never touches another). Text search auto-expands matching phases;
  sort is per-phase (tasks stay grouped); **expand-all / collapse-all persists**
  across filtering and page reload (localStorage); the page gains a `<title>`
  (browser-tab name). Still one self-contained file, zero network fetches, every
  value escaped, and fully readable with JS off (rows render expanded; JS
  collapses them). Verified in a browser against a synthetic 40×5 report.
- **Report readability: completion dates + status coloring.** The task table gains
  a sortable **done** column (completion date; the full started/completed
  timestamps show on hover; in-progress tasks show their start date). Risk is now
  a tinted chip (low/med/high = green/amber/red, distinct from the solid status
  chips), and every task and phase row carries a **status-colored left edge**
  (green/amber/red/grey) so state reads at a glance. The Markdown twin gains the
  matching `done` column.

### Added
- **Report: PDF, an AI summary, and a Markdown download.** A **Save as PDF**
  button prints the report on **A4 with every phase expanded** (via the browser
  print dialog + a print stylesheet — no bundled PDF library, so the file stays
  small and self-contained). A **Summary** box shows an AI-authored narrative
  when present — `/audit:report` composes 2–4 sentences and passes them via a new
  `render-report.py --summary-file PATH` (or a manifest `meta.reportSummary`);
  the file is injected in-memory, so the command stays read-only. A **Download
  .md** button saves the Markdown twin (embedded as base64) even from a
  standalone HTML. The quantitative "Overall" line remains the always-present
  fallback. Verified end-to-end in a browser.
- **Onboarding: a worked example, a live demo, and quickstart docs.** New
  `examples/acme-store/` — a small, schema-valid manifest that covers every
  phase/task status, a blocked task, cross-task deps, a hard phase gate, the full
  bug lifecycle (open→triaged→in_progress→fixed→wontfix), a reciprocal bug↔task
  link, and an ADO link — plus its generated report. CI validates it on every
  push. A GitHub Pages demo (`docs/index.html` = the example report;
  `docs/demo-large.html` = a 40×5 report) gives a click-through live link, and the
  READMEs gain a Quickstart, screenshots, and a per-field **`meta` reference**
  table + a **Reports** section.
- **`meta.reportBasename` / `render-report.py --basename`** — custom report
  filenames (e.g. `q3-audit` → `q3-audit.html/.md`; default `audit-report`),
  sanitized to `[A-Za-z0-9-_]`. The **Download .md** button uses the same name.
  Both `reportBasename` and `reportSummary` are now first-class `meta` keys
  (schema + validator).

### Fixed
- **Validator now flags a `done` phase that still has non-done tasks.** A phase
  is `done` only after sign-off (every task done); `validate-manifest` never
  checked that invariant, so a stale-status slip passed silently. Added the
  check + a regression selftest, and corrected the dogfood roadmap manifest's
  **P3** — its four tasks carried commits + outcomes (the work shipped in
  v0.5.0) but were still marked `pending` from a hand-regeneration. Surfaced by
  the interactive report showing P3 as `done` with a `0/4` progress bar.

## [0.10.0] - 2026-07-16

A self gap-audit of the whole plugin (trust core, guards, command surface,
packaging) drove a round of hardening plus one feature. Deliberately-accepted
trade-offs documented in `SECURITY.md` (fail-open on internal error, `cp`/`mv`
Bash-write coverage, name-based secret matching) were left as-is by design.
Every fix carries a regression selftest (suites now: `_config` 6, `guard-edits`
16, `guard-secrets-read` 58, `require-plan` 25, `remind-tdd` 13,
`guard-bash-writes` 14, `detect-plan-skip` 4, `validate-manifest` 41,
`audit-status` 33, `render-report` 20).

### Added
- **Interactive HTML report** — the report tables now support a text filter,
  click-to-sort columns (natural order, so `P2` before `P10`), and per-status
  quick-filter chips. Inline, self-contained JavaScript: no server, zero network
  fetches, still one shareable file / CI artifact. Progressive enhancement (fully
  readable with JS off); the untrusted manifest still cannot inject (every value
  HTML-escaped; script touches only `textContent`/attributes). Verified
  end-to-end in a browser.

### Fixed
- **CI gate false-negative on the worst bugs.** `open-high-bugs` counted only the
  literal severity `"high"`, so an open `critical`/`blocker`/`sev1`/`p0` bug
  passed the merge gate. It now matches a normalised high-or-worse vocabulary.
- **Crash on a malformed manifest.** A non-object JSON root (`null`/`[]`/scalar)
  raised an uncaught `AttributeError` in `audit-status`/`render-report`; both now
  exit 2 cleanly, and `validate-manifest` upholds its "never raises on arbitrary
  JSON" contract (non-list/unhashable `blockedBy`/`dependsOn`/`fileIndex`/`tasks`
  become findings; boolean `version` rejected).
- **Manifest concurrency lock now covers `init`/`task`/`bug`/`sync`** (previously
  only the execution verbs locked). `/audit:init` regenerate can no longer clobber
  an in-flight run; the quick-mutation commands hold the lock around writes.
- **Re-opening a `done` bugfix task** now also reopens its linked bug instead of
  leaving `bugs[]` marked `fixed` at a stale SHA.
- `/audit:sync` `allowed-tools` now grants the `mcp__azure-devops__wit_*` tools
  its body tells the model to use; `/audit:status` reads the ready-now list from
  `audit-status.py` (one implementation of the readiness rule, no drift);
  `review`/`resume` emit progress output like their siblings.
- `render-report` HTML now carries `<!doctype>`/charset (standalone render, not
  quirks mode); the `.md` twin documents that it relies on the renderer to
  sanitise HTML.

### Security
- **`guard-secrets-read`** now blocks SSH private keys
  (`id_rsa`/`id_dsa`/`id_ecdsa`/`id_ed25519`), bare `~/.aws/credentials` read via
  Bash, and `.pfx`; the shell-write backstop also catches `1>`/`>|` redirects.
- **`guard-edits`** token-logging ban now catches a token as the sole/first
  argument (`console.log(accessToken)`) and via property access
  (`this.accessToken`) — previously only later args / interpolations were caught.

### Docs
- Marketplace/plugin descriptions no longer advertise a removed bare `/audit`
  command and now list `/audit:sync`; "five hooks" → "six" in SECURITY/README;
  residual space-form commands fixed; Python floor notes CI verifies 3.12;
  build-guide selftest tallies and guard coverage refreshed.

## [0.9.0] - 2026-07-15

Made the audit's compute choices deliberate and reproducible instead of
inherited from the calling session: reasoning effort is now pinned per agent,
and the task model floor is raised to `sonnet`.

### Changed
- **Reasoning effort is pinned per agent, no longer inherited from the calling
  session.** Each audit agent sets `effort` in its own definition:
  `audit-reviewer` → `high` (sign-off analysis, once per phase), `audit-executor`
  and `audit-explorer` → `medium`. Previously effort silently rode on whatever
  the invoking session ran at — a `max`-effort session made every executor run at
  `max` (observed: ~360k tokens on a single review-fix task) — so an audit's
  cost/latency was not reproducible. The `Agent` tool has no per-spawn effort
  override, so the definition frontmatter is the only lever; `orchestrator.md` now
  states the spawn passes **only** `model`, never effort (and that the
  general-purpose fallback reverts to session effort — an accepted degradation).
- **Task model floor raised to `sonnet`; `haiku` is no longer assigned to fix
  work.** `/audit:init` synthesis and `/audit:task` now default to `sonnet` for
  all low/med-risk work (mechanical included) and escalate to `opus` for
  `risk: "high"`. A botched `haiku` attempt burns retries plus a reviewer round,
  costing more than one clean `sonnet` pass. The `risk:"high"` → never-`haiku`
  guard in `orchestrator.md`/schema stays as defense for hand-written manifests.
  This is a creation-time rule — existing manifests with `haiku` tasks are not
  auto-upgraded.

## [0.8.0] - 2026-07-09

Live-validated the orchestrator for the first time, then made a long run legible
and previewable.

### Fixed
- **Gate commands broke on git-in-a-subdir manifests** (found by the first real
  end-to-end run). 0.7.0 told the orchestrator to run gates "from the git root";
  0.2.0-generated manifests carry `cd <gitRoot> && …` in `buildCommands` and
  expect the project dir. Now: **git** runs via `git -C <gitRoot>`, **gate
  commands run from the project dir verbatim** (the manifest carries any needed
  `cd`), and `/audit:init` prefixes `cd <gitRoot> && ` when the workspace is a
  subdir. `orchestrator.md`, `init.md`, README updated.
- A subagent that returns no usable result (died / no parseable outcome / no
  file change) is now explicitly a failure → retry to `maxAttempts` → `blocked`
  (previously implicit).

### Added
- **Progress output** — the execution verbs emit a short line as each step
  happens (phase entry, per-task start/result/commit, each sign-off gate, merge)
  so a long `/audit:phase` is legible instead of silent until the end.
- **`--dry-run`** on `/audit:next`, `/audit:run`, `/audit:phase` — read-only
  preview of the plan (branch, ready tasks, parallel groups, gates, merge target)
  with nothing created, spawned, or committed.
- **Richer `/audit:report`** — an overall progress header (tasks/phases/bugs/
  ready), per-phase branch + merged-at, and a per-task outcome column; still
  self-contained and fully escaped. 16 selftest cases.
- **Readability** — README TL;DR quickstart at top, an "At a glance" summary in
  `orchestrator.md`, and scannable `[x]/[~]/[!]/[ ]` status markers + an overall
  line in `/audit:status`.

### Validation
First real end-to-end `/audit:phase` run against a live repo (throwaway Nx
monorepo, git in `test/`, nothing pushed): preflight → phase branch → parallel
subagents → real lint gate → per-task commits (gitRoot prefix stripped, clean
hygiene) → sign-off → ff-merge, then full restore. Confirmed the 0.6.1 gitRoot
fix and the lock/preflight work in a live run; surfaced the gate-cd bug fixed
above.

## [0.7.0] - 2026-07-08

Command surface: split the orchestrator into `/audit:<verb>` commands
(no more `/audit:audit`).

### Changed
- **The single orchestrator command is gone.** Because Claude Code namespaces
  plugin commands as `/<plugin>:<command>`, the old `audit.md` was only
  reachable as the awkward `/audit:audit` (and bare `/audit` — which every doc
  and the plugin's own recap text wrongly suggested — is not a command at all,
  producing "Unknown command: /audit"). Each action is now its own verb command:
  - `/audit:status` · `/audit:next` · `/audit:run <id>` · `/audit:phase <id>` ·
    `/audit:review <id>` · `/audit:resume` · `/audit:report`
  - consistent with the existing `/audit:init` · `/audit:task` · `/audit:bug` ·
    `/audit:sync`.
- Shared execution logic (config resolution, preflight incl. git-root/submodule/
  lock, guardrails, readiness, branch-per-phase, Execute-the-task, Phase sign-off,
  resume, reporting) moved to **`reference/orchestrator.md`**, which every verb
  command reads; each verb file is thin (its slice + a pointer to the reference).
- **All handoff/recap text and docs now emit `/audit:<verb>`** — previously the
  commands' own output told users to run `/audit run …`, `/audit phase …`, etc.,
  which don't exist, so copy-pasting them failed. Fixed in the command bodies,
  README, PLUGIN-BUILD-GUIDE, schema descriptions, and hook comments.

### Migration
No manifest changes. If you used `/audit:audit <sub>` (or tried bare `/audit`),
switch to the matching verb: `/audit:audit status` → `/audit:status`,
`/audit:audit run X` → `/audit:run X`, `/audit:audit phase P0` → `/audit:phase P0`.
After updating, `/reload-plugins` (or restart) so the session picks up the new
command set.

## [0.6.2] - 2026-07-07

Submodule preflight guard.

### Added
- **Git-submodule detection.** The orchestrator commits from one repo (the git
  root); files inside a submodule belong to a separate nested repo the parent
  cannot stage (`git add` → "Pathspec is in submodule") — so a task touching
  them would fail at commit time. `/audit` now **preflights** this: when
  `<gitRoot>/.gitmodules` exists it checks every `task.files` entry and STOPS
  with guidance (point `meta.gitRoot` at the submodule, or drop those files)
  instead of failing mid-run.
  - `scripts/audit-status.py` gains `parse_gitmodules()` + `submodule_conflicts()`
    (pure, path-boundary safe: `vendor/child` matches `vendor/child/x` but not
    `vendor/child-other/x`) and a `--submodules <.gitmodules> [--git-root
    <prefix>]` CLI mode (exit 1 on conflict). 22 selftest cases.
  - `/audit:init` no longer routes tasks at files inside a submodule (defers
    them instead); README Troubleshooting documents the boundary.

### Note
Plan-first and secret guards still apply to submodule paths by path (they don't
touch git). Only the per-task commit and the PostToolUse shell-write check are
submodule-boundary limited — both now surfaced rather than silent.

## [0.6.1] - 2026-07-07

Fix: git repo in a subdirectory (found by end-to-end testing against a real Nx
monorepo where the git root was `test/`, not the project dir).

### Fixed
- **The orchestrator assumed the project dir IS the git root.** When the git
  repo lived in a subdirectory, every git operation failed (`not a git
  repository`), the manifest (outside the git tree) could not be committed, and
  `guard-bash-writes` went silent — all four failures were silent. Now:
  - `meta.gitRoot` (+ `gitRoot` in `.claude/audit.config.json`) — path of the
    git root relative to the project dir (default `.`). `/audit` runs
    `git -C <gitRoot>`, runs gates there, and strips the prefix when staging;
    `guard-bash-writes` runs its git check there too.
  - **`/audit` preflight** verifies the git root is a git repo and STOPS with
    guidance if not — turning a silent 4-way break into one clear message. It
    also warns when the manifest lives outside the git root.
  - `/audit:init` detects the git root and sets `meta.gitRoot`; `/audit` reads
    the 0.2.0-era `meta.workspaceRoot` as a fallback, so existing manifests work.
- Validator no longer warns on `phase.description` (now a real schema field) or
  on the 0.2.0-era `meta.notes`/`meta.workspaceRoot`/`meta.baseCommit`/`task.details`
  keys — a 0.2.0-generated manifest dropped from 21 warnings to 0.

### Added
- README: "Git repo in a subdirectory" and "Troubleshooting" sections
  (git-root preflight, stale version-pinned permission after `/plugin update`,
  interpreter/Git-Bash, state files). 185 selftest cases.

## [0.6.0] - 2026-07-07

Agents & full-coverage enforcement: prompt discipline becomes mechanical.

### Added
- **Plugin agents** (`agents/`): the commands now spawn pinned-tool subagents
  instead of free-form ones — `audit-explorer` (Glob/Grep/Read only:
  **mechanically read-only**, used by `/audit:init` fan-out), `audit-executor`
  (no web tools, no nested agents; task execution and review fixes),
  `audit-reviewer` (no edit tools; sign-off review runs the project review
  skill inside the agent, keeping the diff out of the orchestrator's context).
  Tool lists are a hard boundary independent of subagent hook inheritance
  (#43772); commands fall back to general subagents on older Claude Code.
- **`guard-bash-writes.py`** (PostToolUse `Bash` + edit tools): git-status
  diff check that catches ANY shell write into a source file no tool edit and
  no `in_progress` task accounts for — the statically-undecidable residual of
  the PreToolUse text checks (#29709) — and tells the model in-band
  (non-blocking; needs a git repo; `bashWriteCheck.enabled`, default true).
- **State GC**: session state files (incl. forgotten armed bypasses) older
  than 7 days are garbage-collected on prompt submission;
  `detect-plan-skip.py` gains a selftest.
- CI: ten selftest suites (183 cases); GitHub Actions bumped off the
  deprecated Node 20 action majors; repo `.gitignore` covers the dogfood
  manifest's runtime artifacts (`*.lock`, `audit-report.*`).

### Changed
- `_config.py`: shared `source_exts()` (one definition of "source file" for
  the shell-write guards and the TDD nudge) and `bashWriteCheck` defaults.
- CONTRIBUTING: commands-vs-skills decision re-evaluated with agents shipped
  (still NO-GO — invocation surface unchanged); plugin evals documented as
  deferred while `claude plugin eval` is early access (schema not public).
- `remind-tdd.py` docstring: the throttle is per-session, not global
  (concurrent sessions throttle independently).

## [0.5.0] - 2026-07-07

Features for team use (Azure DevOps focus).

### Added
- **`/audit:sync`** (`push [bugs|tasks|all]` · `pull` · `status`): mirrors manifest
  bugs/tasks into Azure DevOps work items and back. Contract = the `az boards`
  CLI (headless-capable; azure-devops MCP tools as an optional fast-path);
  configured by the new `meta.ado` block; idempotent — the write-back
  `item.ado = {id, url, lastSyncedAt}` lands immediately after each create so
  interrupted runs converge; plan + confirmation before the first outward
  write; credentials never stored or printed (`az login` /
  `AZURE_DEVOPS_EXT_PAT`).
- **`scripts/audit-status.py`** — headless rollup + **CI gate**: `--json`
  (phases/tasks/bugs/ready summary), `--gate` exits 1 on tripped conditions
  (default `invalid,open-high-bugs,blocked-tasks`; also `open-bugs`,
  `in-progress` via `--fail-on`). Wired into this repo's CI against the
  dogfood manifest; `docs/examples/azure-pipelines.yml` shows the
  validate → gate → report pipeline for consuming repos.
- **`/audit report`** + **`scripts/render-report.py`** — self-contained
  HTML + Markdown status report (inline CSS, zero network fetches; every
  manifest string escaped, only http(s) URLs rendered as links), publishable
  as a CI artifact.
- **Concurrency lock**: mutating subcommands hold `<manifestPath>.lock` —
  a second session is refused with holder info; a stale lock (>60 min)
  offers a confirmed takeover; `status`/`report` never lock.
- Schema (additive): `meta.ado`, `task.ado`, `bug.ado` (`$defs/adoLink`);
  validator checks their shape and accepts the new keys.

### Fixed
- `require-plan` no longer gates the manifest itself or its lockfile when a
  custom `manifestPath` falls outside the exempt globs (previously the
  orchestrator's own manifest writes could be blocked).

## [0.4.0] - 2026-07-07

Release-quality envelope: docs, CI, policies, canonical hook protocol.

### Added
- **CI** (`.github/workflows/ci.yml`): ubuntu + windows matrix running all six
  `--selftest` suites, the launcher fail-loud check, the structural validator and
  ajv (draft 2020-12) over the starter **and** the dogfood manifest, and
  `claude plugin validate` for the marketplace + plugin.
- **Dogfood manifest** `docs/audit/audit-plan.json`: this repo's own roadmap as an
  audit manifest — P1 = shipped v0.3.0 (real commit SHAs), P2 = v0.4.0, P3 = the
  v0.5.0 plan, including a reciprocal `BUG-1 ↔ task` link. CI validates it with the
  plugin's own validator, so the roadmap doubles as a permanent integration fixture
  and a real-world manifest example.
- **Root `README.md`** (repo landing page), **`SECURITY.md`** (threat model,
  fail-mode table, known bypass classes, reporting), **`CONTRIBUTING.md`**
  (dev setup, test matrix, release rule, commands-vs-skills decision record),
  and this **`CHANGELOG.md`**.
- Plugin metadata: `repository` in `plugin.json`; `category`, `tags` and
  `strict: true` on the marketplace entry.

### Changed
- **Blocking hooks speak the canonical PreToolUse protocol**: `require-plan`,
  `guard-edits` and `guard-secrets-read` now emit
  `hookSpecificOutput.permissionDecision: "deny"` JSON with the reason and exit 0,
  instead of the deprecated exit-2 + stderr channel (which is indistinguishable
  from a hook crash). Decision cores are unchanged; selftests assert the JSON shape.
- **Plugin README overhauled**: Requirements section (Python via
  `python3`/`python`/`py`; Windows = Git Bash), runnable copy-paste snippets
  (the unresolvable `<plugin>` placeholder is gone), a prominent
  **"installing arms global hooks"** section with per-project scoping /
  disable / uninstall instructions, guidance for repos without tests, and a
  one-session-per-clone concurrency note.

### Fixed
- `PLUGIN-BUILD-GUIDE.md`: said "four guard hooks" while wiring five; stale note
  claiming the marketplace was renamed to `claude-plugins` (it is `quality-gates`);
  stale hook/validator descriptions predating 0.3.0.

### Release integrity note
Tags are never moved. The `v0.2.0` tag predates the marketplace rename commit
`433dd35` (tagged tree says marketplace `claude-plugins`; `main` after that commit
says `quality-gates`) and there is no `v0.1.0` tag. Fixed forward: from 0.3.0 on,
every release is one commit that bumps `plugin.json` + updates this changelog and
carries the annotated tag; tags are pushed only after CI is green.

## [0.3.0] - 2026-07-07

Hardening: every confirmed correctness defect from the v0.2.0 deep review fixed.

### Added
- `/audit resume` subcommand; `status` flags resumable phases.
- `hooks/py-launch.sh`: interpreter resolution `python3` → `python` → `py`;
  without any interpreter the blocking guards emit `permissionDecision: "ask"`
  JSON (fail-LOUD) instead of the previous silent fail-open on exit 127.
- `_config.py --selftest`; `_configError` marker for present-but-malformed config,
  surfaced once per session by `detect-plan-skip` (which now also announces when a
  `#no-plan` bypass is armed).
- Guard coverage: `NotebookEdit` everywhere; indirect secret reads
  (`git show`/`cat-file`, `source`/dot-source, `cp`/`mv`/`rsync`/`install`);
  shell writes into source files (`sed -i`, `tee`, `>`/`>>` redirects incl.
  heredoc redirects) unless covered by an `in_progress` task; self-edit
  protection for the installed plugin's files; `plan-bypass-*` forgery block.
- Validator: dependency-cycle detection, reciprocal `bug ↔ task` link checks,
  bidirectional `fileIndex ↔ task.files` reconciliation, tests-not-an-object
  finding, unknown-key warnings with did-you-mean, exit codes 0/1/2.
- `phase.desiredOutcome` wired: shown by `status`, given to task subagents,
  addressed by the sign-off summary; `/audit:init` generates it per phase.

### Changed
- **Transactional plan-bypass**: PreToolUse only observes state; PostToolUse
  (fires only after a successful edit) consumes the single-use bypass and records
  the free-file slot — a denied edit no longer burns them.
- Trivial-edit threshold uses **change magnitude** = max(added lines, chars/200,
  removed lines), closing the single-line-blob and mass-deletion loopholes.
- `run <taskId>` gained status guards (done → confirmed re-open; blocked →
  confirmed reset; in_progress → points to resume); phase entry (dev-branch
  verification, `baseRef`, branch creation, `phase.status = "in_progress"`) is
  unified across the `phase`/`next`/`run` paths.
- Test failure vs **infrastructure failure**: a gate that could not run does not
  consume attempts — it stops with a human action item.
- ff-merge fallback: when the development branch advanced, offer `--no-ff`
  (keeps recorded SHAs valid) or stop; rebase is never offered.
- High-risk confirmation is unconditional (the undefined "auto mode" gate is gone).
- Every hook entry has an explicit 10 s timeout (default was 600 s).
- Schema: canonical `$id`, `^BUG-\d+$` pattern on `bug.id`; never-read meta fields
  removed (`signOffChecklist`, `autoMode`, `modelPolicy`, `testPolicy`,
  `reviewPolicy`, `skillsPolicy`, `statusLegend`, `phase.signOff`) — legacy
  manifests still validate.

### Fixed
- **Resume worked on paper only**: it searched for `phase.status == "in_progress"`,
  which nothing ever wrote. The status is now written at phase entry (with a
  pre-0.3 fallback in resume).
- **YAML frontmatter in `commands/*.md` was silently dropped at runtime**
  (`audit.md`'s description contained `: `, so ALL its metadata — including
  `allowed-tools` — never applied; `init.md`'s argument-hint parsed as a YAML
  array). All frontmatter values are now quoted; `claude plugin validate` passes.
- Malformed `.claude/audit.config.json` no longer silently reverts custom secret
  patterns/rules/thresholds to defaults without a signal.
- `/audit` preflight: malformed config stops with the parse error; a missing
  manifest points to `/audit:init`; an unknown subcommand prints usage.
- `AskUserQuestion` added to `/audit`'s `allowed-tools` (it has ~6 human gates).

## [0.2.0] - 2026-07-06 _(tag `v0.2.0`)_

### Added
- `/audit:init` — multi-agent manifest generation (interview → recon → parallel
  read-only explorers → synthesized schema-valid phases/tasks).
- `/audit:task add` — interactive task creation (id allocation, full template,
  fileIndex maintenance, revalidation).
- `/audit:bug` — bug tracking in the manifest's top-level `bugs[]`;
  `fix` materializes a bug into a red-first TDD task (`expectRedFirst`);
  the orchestrator flips the bug to `fixed` + `fixedIn` on the task commit.
- `remind-tdd.py` — non-blocking PostToolUse TDD nudge (throttled,
  manifest-aware, configurable).
- Schema: top-level `bugs[]`, `task.bugId`; shared `reference/manifest-conventions.md`.

### Known issue (documented 0.4.0)
The `v0.2.0` tag was cut before the marketplace rename to `quality-gates`
(`433dd35`) with no version bump — the tagged tree and `main` disagree on the
marketplace name while both claim 0.2.0.

## [0.1.0] - 2026-07-06 _(untagged)_

### Added
- Initial public extraction of the internal audit tooling, IP-scrubbed and
  de-coupled: `/audit` orchestrator (manifest-driven phases/tasks, branch-per-phase,
  per-task model + skills subagents, TDD/regression/gate-only discipline, phase
  sign-off), guard hooks (`require-plan`, `detect-plan-skip`,
  `guard-secrets-read`, `guard-edits`), `_config.py` per-repo config layer,
  JSON Schema + dependency-free structural validator, starter templates,
  MIT license, marketplace `quality-gates`.
