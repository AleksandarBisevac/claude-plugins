---
name: refactoring-the-assembled-ui
description: Edit, split or share the CSS and JavaScript under plugins/audit/scripts/ui/ — files Python concatenates into exactly one inline <style> and one inline <script> in a self-contained page opened over file://. Covers the assembly contract and the ~70 byte-level pins that guard it, why the split must be an order-preserving cut rather than a regrouping, the selftest counts that currently enforce duplication, choosing a feature a report may use (Baseline plus a file:// gate), one dialect and one shared layer across both surfaces, CSS token and naming conventions, and the browser gates that must stay green. Use when touching report.css, report.js, panel.css, panel.js or _ui_theme.py, when extracting a shared partial or module, when a rule or helper exists twice, or when a selftest pin goes red after a UI edit.
---

# Refactoring the assembled UI

`scripts/ui/` does not hold standalone files. It holds **ordered parts of one artifact**.
`_report_ui.py`, `_panel_ui.py` and `panel-server.py` read them at import and join them into a
single self-contained HTML page. Almost every surprise in this area comes from forgetting that.

## The assembly contract

- **Exactly one inline `<style>` and one inline `<script>`.** The tags live in the Python
  modules, never in the assets — selftests pin both, and pin that the `.js` files carry no
  `<script>` tags of their own.
- **No external resources, ever.** CI asserts the rendered report contains no `<script src`,
  `<img `, `<link `, `<iframe` or `url(http`. No CDN, no web font, no separate stylesheet.
- **No ESM, no bundler, no transpiler.** `import`/`export` cannot work in one inline script on an
  opaque `file://` origin. There is no build step and there will not be one.
- **Order is load-bearing.** `TOKEN_CSS` must come first — both stylesheets are *individually
  invalid* without it (undeclared custom properties, and `panel.css` alone fails the
  `color-scheme` check). Then base, then components, then the surface file, because
  `report.css`'s `@media (max-width:52rem) thead th{position:static}` beats the shared rule by
  source order alone.
- **Every part ends with `\n`.** `panel-server.py` runs a line-based lint over
  `UI_HTML.splitlines()`; a part without a trailing newline joins two lines and can hide a real
  offender or manufacture a false one.
- `.gitattributes` pins `scripts/ui/** text eol=lf` as a glob, so new parts inherit it. **No `.py`
  may ever land in `scripts/ui/`** — a selftest pins that directory as Python-free.

## Splitting: cut, never regroup

The current statement order is a **machine-checked contract**. `panel-server.py` carries 18
index-slice assertions and `render-report.py` two more — for example, `pollRunStatus` must appear
before the `// ---------- Overview` marker, which must appear before `refreshFromDisk`. Several
slice *between a function and a section-marker comment*, which makes those comment lines
load-bearing.

All of them survive an order-preserving split. **All of them die under any "logical" regrouping.**
So: cut at existing seams, keep the sequence, change nothing else in the same commit.

Concretely:

- **`panel.js` — number the filename prefixes.** Alphabetical ordering is not safe. Only 13
  top-level statements execute at parse time and every `function` hoists, but 134 top-level
  `const`/`let` sit in TDZ, and `$`, `el` and `api` (lines 3–7) are read by executable statements
  at lines 19–35. The core part must be first and `boot()` must stay last.
- **`report.js` — move the IIFE wrapper into `_report_ui._script()`.** It straddles the whole file
  (`(function () {` at line 2, `})();` at the end), so a naive split leaves every part
  individually unparseable, defeating the "real, editor-highlightable files" rationale. Wrapping
  in Python keeps zero globals and keeps every part brace-balanced. **Do not simply drop the
  IIFE** — that would dump ~130 bindings (`root`, `count`, `download`, `refresh`, `cell`, `q`…)
  into global scope on a page that already carries `window.AUDIT_USAGE`.
- **Repoint `tools/capture-screenshots.mjs`**, which reads `ui/panel.js` by literal path and
  slices from `async function pollRunStatus`. It fails loudly by design when that moves; point it
  at the assembled template instead.
- A split makes `node --check` per part possible for the first time. Add it.

**The strongest reason to do the pure cut before anything else:**
`tools/check-report-interactive.mjs` never opens `report.js` — it drives the rendered artifact in
a browser. If the join preserves order, the output is byte-identical and all of its assertions
pass untouched. That makes the cut provably behaviour-free.

## The pins are the budget

`render-report.py` and `panel-server.py` hold **~70 exact substring assertions** against the
assembled stylesheet, plus negative ones. Two pin multi-line source text *including newlines and
leading spaces*, so reflowing a rule turns them red.

Treat each red pin as a **review checkpoint, and update it on purpose**. A pin deleted rather than
updated is the failure this whole area is guarded against.

Negative pins worth memorising: no hand-tuned sticky offset may reappear; the name `--chip-ink`
is forbidden; and `report.js` may contain **no wall-clock call at all** (`Date.now()`, `new
Date()`), which constrains what a shared date helper may contain.

### Some pins currently enforce the duplication

`panel-server.py` asserts `UI_HTML.count("'data-discard':'") == 4` and
`count("discard.disabled=!n;") == 3`. The five copy-pasted save/discard footers are therefore
*required to be five*. Factoring them into one helper turns the suite red — correctly, because the
pin is doing its job. **Deduplication here is always a paired change with `panel-server.py`,
never a JS-only edit.** Same for the other count pins.

## Which features a shipped report may use

Two gates, both required.

1. **Baseline.** Look the feature up in `references/baseline-snapshot.md` by feature id — never
   from memory, because statuses change and widely-known features can still be Limited. *Widely
   Available* may be used freely; *Newly Available* needs `@supports` (CSS) or an existence check
   (JS) plus a fallback; *Limited* must not be used. A feature missing from the snapshot, or newer
   than its header date, is uncertain — treat it as Limited.

   ```bash
   grep -E '^\| (cascade-layers|light-dark|has) ' \
     .claude/skills/refactoring-the-assembled-ui/references/baseline-snapshot.md
   ```

   The table is a reference to grep, not to read. As of the 2026-07-08 snapshot this settles a few
   live questions: `cascade-layers` and `container-queries` are **widely**, so `@layer` is
   available and worth adopting; `light-dark()` and `view-transitions` are **newly**, so they need
   detection plus a fallback; `anchor-positioning` is **limited** and must not be used at all.
2. **`file://`.** Baseline measures engine support, not scheme restrictions, and will report
   *widely* for things that are blocked or inconsistent on an opaque origin. The snapshot lists
   `js-modules` as widely available since 2020 — and they are still impossible here. That single
   row is why this second gate exists; do not skip it because the first one was green. The report
   is opened from disk, so it must additionally avoid or guard: ES modules and dynamic `import()`;
   `localStorage`/`sessionStorage`/cookies (inconsistent to blocked — the report already treats
   storage as best-effort inside `try`/`catch`, keep that); `fetch` of a sibling file and
   `XMLHttpRequest`; service workers; `crypto.subtle` and anything else gated on a secure context.

The panel is served over `http://localhost` and is not subject to gate 2 — but anything in a
**shared** part must satisfy both, because it ships inside the report too.

## One dialect, one shared layer

The two surfaces are currently written in different dialects — `panel.js` in modern ES with an
`el()` DOM builder used at hundreds of sites, `report.js` in ES5 with `var`, `function ()` and
hand-rolled `createElement`. Nothing was ever recorded about why. The consequence is that the same
feature exists twice and cannot be shared: two `isDark()`, two tooltip placers, two CSV quoters,
two blob downloaders, two heatmap calendars — and the two token formatters **already disagree**
(one rounds, one truncates) while both claim in comments to mirror the same Python function.

Rules going forward:

- **One dialect for anything shared**, chosen once and written into the decision record with the
  Baseline justification. A shared part may use only what passes both gates above.
- **Extract the helper rather than retyping it.** Anything both surfaces need — DOM building,
  escaping, number and date formatting, theme state, tooltip placement, chip toggling, blob
  download, CSV quoting — belongs in `shared/`, defined once.
- **A number rendered by more than one surface has one implementation**, and its cases pin it
  against the Python that renders the same number elsewhere. That agreement is a claim; test it.
- **Wrap each independent feature in its own `try`/`catch`** at the registration point, so one
  broken feature cannot blank a report someone opened from a CI artifact:

  ```js
  for (const feature of [themeToggle, filterBar, heatmap]) {
    try { feature(); }
    catch (cause) { console.error('feature failed: ' + feature.name, cause); }
  }
  ```

- **Identifiers are global in a concatenated script.** There is no module scope to rely on — the
  advice "module scope already encapsulates" is false here. Prefix by feature, the way the panel's
  existing `u*` / `p*` / `t*` / `ov*` conventions already do, and keep the discipline: the file
  already documents one near-miss where a second `findingsBox` would have hoisted over the first
  and broken every config save.
- **Organize by feature, not by artifact.** `report.* / panel.*` is organization by artifact,
  which is why the same feature lives twice. Each feature directory carries a short `README.md`
  saying its one responsibility and *why* — not a file listing.
- **Reach elements through dedicated `data-` attributes, not styling classes.** The hook is then
  explicit and greppable, and renaming a class cannot silently break behaviour.
- **Name helpers after what they do.** No `*Utils`, `*Helper`, `*Manager`, `*Impl`.
- Before writing a handler, check whether markup already does it: `<details>`/`<summary>` for
  disclosure, `<dialog>` for modals, `:target` for deep-linked panels. Deleted JavaScript is the
  cheapest JavaScript.

## CSS

- **Tokens are the source of truth.** `_ui_theme.py` declares them once; component rules reference
  `var(--…)` and never raw values. The compiler *substitutes into* `TOKEN_CSS` rather than
  regenerating it, and `compile_theme(DEFAULT_THEME) == TOKEN_CSS` byte-for-byte is pinned — so
  no comment inside `TOKEN_CSS` may contain a brace, and a new token must also be placed in a
  theme group or the neutral list.
- **Finish the spacing migration rather than widening it.** The `--sp-*` scale exists and is used
  in some regions while the same values are written raw in others. Prefer the token; when a value
  has no token and is shared by both surfaces, add one.
- **A metric that both surfaces use is a token, or it will drift** — this has already happened to
  the shell width, the budget grid, the nav breakpoint and the triangle glyph. Media queries
  cannot read `var()`, so a shared breakpoint is either one agreed literal in the shared part or a
  Python-side substitution.
- **Name a component once.** Do not ship `.utip` here and `.rtip` there, or `.mut` and `.muted`.
  Where the same name currently means two different things, **rename before extracting** —
  touching the emitters in the same commit — or the merge silently breaks one surface.
- **Prefer `:where()` for shared base rules** so specificity stays at zero and surface overrides
  keep winning without change. A single focus ring belongs in the base part.
- **Never define a colour only inside a media query.** A token declared only in a dark block
  vanishes in light mode; `theme_asymmetric_vars()` checks both directions because that shipped
  once as invisible bars.
- `@media print` is outside the theme compiler's reach, so a palette hard-coded there cannot be
  themed. If print needs different colours, they still belong in the token layer.

## What must stay green

Run all of it; the browser gates are the only ones that can catch a cascade-order regression a
substring pin cannot see.

```bash
for f in $(find plugins/audit/hooks plugins/audit/scripts -name '*.py' | sort); do python3 "$f" --selftest || exit 1; done
node tools/capture-screenshots.mjs --check
node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html
```

`_ui_theme.py`'s five lints — undeclared vars, unterminated declarations, theme asymmetry, mangled
escapes, missing `color-scheme` — all run against the **assembled** string. Keep assembling before
linting; a part that is valid alone proves nothing.

## Checklist

- [ ] The change is a cut or an edit, not a reordering of statements
- [ ] Parts joined in the same sequence; core first, `boot()` last; each ends with `\n`
- [ ] `TOKEN_CSS` still first; shared CSS before surface CSS
- [ ] Every red pin read and updated deliberately — none deleted to go green
- [ ] Count pins that guard duplication updated in the same commit as the dedup
- [ ] Any new feature checked against Baseline **and** the `file://` list
- [ ] Anything shared defined once, in `shared/`, and reachable from both surfaces
- [ ] Each feature wrapped so its failure cannot blank the page
- [ ] New class and identifier names unique across both surfaces
- [ ] Both browser gates run, not just the Python suites
