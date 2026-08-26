# The shared layer

Parts here are concatenated into **both** surfaces — the report's script and the
panel's — ahead of every part that reads them. `_report_ui._SCRIPT_PARTS` and
`_panel_ui._JS_PARTS` both list this directory first, and that order is the
dependency direction made mechanical: a shared part cannot call a surface helper,
because the surface has not been declared yet.

## What belongs here, as a rule you can check

**One reader, stays put. Two readers, moves here.** A helper used by one feature
lives in that feature's part. The moment a second feature needs it, it moves here
and the first call site starts calling it. That is the whole rule, and it is
phrased this way because the previous phrasing — "anything both surfaces need goes
in the shared layer, once" — was in force while fifteen rules were retyped, for a
reason worth recording: **it named a directory that did not exist.** Complying
meant inventing this folder, registering it in `_ui_theme.UI_ASSETS`, threading it
into two `_PARTS` tuples in two modules and satisfying
`declared_asset_drift()`. Retyping ten lines was one edit. A rule that makes the
wrong thing cheaper loses, however plainly it is written.

**Business-agnostic only.** Primitives, formatting, platform adapters. A rule
about phases, tasks, bugs or policies is business logic and belongs in the surface
that renders it, even when both surfaces render it — in that case the shared thing
is the *number or string format*, held equal by a differential test, not the
decision behind it.

**Two readers on ONE surface is not this directory.** Three panel parts sharing a
date helper promote it to `panel/core.js`, which is the panel's own shared layer.
Only a cross-surface reader reaches this far. Putting a panel-only helper here
ships it inside the report as dead weight, and subjects it to the report's gates
for no benefit.

## Both feature gates apply, and the second one is the one people skip

A part here ships inside the report, which is opened from disk over `file://`, so
it must satisfy **Baseline** *and* the `file://` list — not just Baseline. In
practice that means, for anything written here:

- **No `import`, `export` or dynamic `import()`.** Python joins these files. A
  module script is fetched with CORS semantics and a page opened from disk has an
  opaque origin, so a cross-file import fails outright. (The panel is served over
  `http://127.0.0.1` and *could* import — measured — which is exactly why the rule
  has to be stated for the shared layer rather than per surface.)
- **No wall-clock call.** `Date.now()` and `new Date()` — the argument-less form —
  are pinned as absent from the report's assembled script, because a wall-clock
  read makes the rendered artifact differ between runs and nothing could then
  compare a committed report to a fresh one. Take a timestamp as an argument
  instead.

  What is *forbidden* is READING THE CLOCK, not the `Date` type: `dates.js` and
  `calendar.js` are full of `new Date(x)` with an explicit argument, which is
  arithmetic on a value the caller supplied and is reproducible by construction.
  The pin is written as the two argument-less spellings for exactly that reason,
  and a shared part that needs "now" takes it as a parameter.
- **No `fetch`, no `XMLHttpRequest`, no service worker, nothing gated on a secure
  context.** The panel has an origin and the report does not.
- **Storage is best-effort.** Wrap it; a page opened from disk may refuse.
- **No external resource** — no CDN, font, image URL or stylesheet link.
- **Not even the four letters `http`, in code OR in a comment.** `x5` in
  `test_render_report.py` asserts the rendered report contains no `http` at all,
  excluding only the ADO link and the embedded Markdown blob. It reads text, so a
  comment mentioning a URL scheme fails it — which is how this line came to be
  written. Say "a real origin" rather than naming the scheme.

## Naming, because the scope is shared and so are the collisions

Both pages put every top-level name in one scope, so a name here must be free in
`report/*.js` **and** in `panel/*.js`. Check both before adding one:

```bash
grep -rnE '^\s{0,2}(function|const|let) NAME\b' plugins/audit/scripts/ui/
```

A name that is already taken by the implementation being promoted is the good
case: delete the local one in the same commit and every existing call site starts
resolving here. Leaving both is not a shadowing bug you will find later — the
report's block is a module, so a duplicate top-level declaration is a
`SyntaxError` and the whole page dies.

Written at column 0. The report's own parts sit two spaces in, which is a leftover
of an IIFE that no longer wraps them; new code does not inherit it.

A row per part, because the wiring's fourth step asks for one — and four parts
had landed here without theirs, which is how `calendar.js` grew a second
responsibility with nothing in this table to grow with it.

| part | one responsibility |
|---|---|
| `theme.js` | Whether the document is painting dark: the `data-theme` attribute if one is set, else the OS. Both surfaces answered this separately and disagreed on one thing — whether `matchMedia` is guarded before it is called — which is what a second implementation is for. |
| `dates.js` | A UTC day as an integer, and back: `DAY_MS`, `dnum`, `dayIso`. Every date helper above it is arithmetic on these, so they sit at least as high as their readers. |
| `calendar.js` | The heatmap's calendar: which period a day falls in, how to step to the next one that holds data, and **what rows a granularity draws**. The second half is why Month shows the month's own dates rather than the seven weekday rows it once shared with Year and All. |
| `plural.js` | A count and its noun, agreeing — including the clause where the verb agrees too. A mirror of `_fmt.plural`, held equal to it by a test that asks the live Python. |
| `clipboard.js` | Copying text, and BOTH of the ways it fails from disk — one browser throws, another rejects. The remedy stays the caller's: the panel toasts, the report selects in place. |
| `download.js` | Handing the viewer a file: one object-URL revoke policy, and the text wrapper so no caller picks a charset. |
| `lookup.js` | Reading a table the code wrote as a literal with a key that did not: one own-property read, so an inherited member name is a MISS rather than `Object.prototype`'s function. The panel owned it while the report carried the identical class and threw on `#!v=constructor`, which is what a second surface is for. It says in full what it does NOT cover — a map the code BUILDS from outside keys needs `Object.create(null)` instead, and then needs no read helper at all. |
| `storage.js` | Remembering something across reloads when the page is allowed to. Fourteen sites carried their own `try`/`catch`; the report may be opened from disk, where storage is refused. |
