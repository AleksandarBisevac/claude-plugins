---
name: refactoring-the-assembled-ui
description: Edit, split or share the CSS and JavaScript under plugins/audit/scripts/ui/ — files Python concatenates into one inline <style> and one inline <script> carrying code, in a self-contained page opened over file://. Covers the assembly contract and the byte-level pins in plugins/audit/tests/ that guard it, why the split must be an order-preserving cut rather than a regrouping, the index-slice assertions that make section-marker comments load-bearing, the counts that currently enforce duplication, choosing a feature a report may use (Baseline plus a file:// gate), one dialect and one shared layer across both surfaces, CSS token and naming conventions, and the browser gates that must stay green. Use when touching anything under scripts/ui/ or _ui_theme.py, when extracting a shared partial or module, when a rule or helper exists twice, or when a selftest pin goes red after a UI edit.
---

# Refactoring the assembled UI

`scripts/ui/` does not hold standalone files. It holds **ordered parts of one artifact**.
`_report_ui.py`, `_panel_ui.py` and `panel-server.py` read them at import and join them into a
single self-contained HTML page. Almost every surprise in this area comes from forgetting that.

## The assembly contract

- **One inline `<style>`, and one inline `<script>` *carrying code*.** The tags live in the Python
  modules, never in the assets — selftests pin both, and pin that the `.js` files carry no
  `<script>` tags of their own.

  *Carrying code* is not hedging. The panel emits one of each; **the shipped report emits three
  `<script>` tags** — `window.AUDIT_USAGE` (2.6 KB of data), `window.AUDIT_MD_B64` (the 6.9 KB
  base64 Markdown twin), and the code (81 KB). Check the artifact, not this sentence:
  `grep -c '<script' examples/acme-store/acme-store-audit.html` prints 3.

  The pin that reads `SCRIPT.count("<script>") == 1` counts tags in a **Python string** — the code
  block alone — not in the page. It has never contradicted the above, which is exactly why the
  wrong version of this bullet survived: the pin that looked like it was guarding the claim was
  guarding something else.
- **No external resources, ever.** CI asserts the rendered report contains no `<script src`,
  `<img `, `<link `, `<iframe` or `url(http`. No CDN, no web font, no separate stylesheet.
- **A module script, but no cross-file `import`.** The report's code block is
  `<script type="module">`: that is where its scope and its strict mode come from, and it is why
  no IIFE wraps it. What a module does NOT buy here is loading — `import`/`export` cannot work on an
  opaque `file://` origin. There is no build step and there will not be one.
- **The panel is different in kind, and it has been measured.** It is served over
  `http://127.0.0.1`, where a real cross-file `import` DOES work — verified in Chromium against
  the panel server's exact response profile, with a `file://` control in the same run reproducing
  the report's `net::ERR_FAILED`. What blocks it is not the browser: `panel-server.py` has no
  static route (a module fetch gets 403 without the session token, 404 with it), a relative
  specifier inherits the path but never the `?t=` query, module scripts are strictly MIME-checked,
  and the `__*__` placeholders substituted into the script text would need a new home. The panel's
  script is also still a CLASSIC `<script>`, so it has neither module scope nor strict mode; it
  boots unchanged as `type="module"` (measured by rewriting only the response body), which removes
  every top-level `function` declaration from `window`. Until a route is decided, Python joins the
  parts — but do not repeat "ES modules are impossible here" as if it covered both surfaces.
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

The current statement order is a **machine-checked contract**, and the suites that hold it now
live in `plugins/audit/tests/`, not in the scripts that build the page — index-bounded slices,
counted per file by `python3 tools/count-ui-pins.py`. A figure here once read "47 and 39" because
it counted `.index()` CALLS, of which a slice takes two, so the count stays in the tool.

The shape is usually a *negative over a slice* rather than a simple "A before B" — for example
`"renderSettings()" not in UI_HTML[index("async function pollRunStatus") : index("// ----------
Overview")]`, which says the poller must not reach into Settings. That is stronger than an
ordering claim and it fails differently: move either endpoint and the window silently changes
size, so the assertion can keep passing while asserting something else entirely.

Several slice *between a function and a section-marker comment*, which makes those comment lines
load-bearing source — they are the reason a marker cannot be reworded casually. **Print the list
rather than trusting a count**, and use this query rather than writing your own:

```bash
grep -rn '\.index("//' plugins/audit/tests/
```

An AST scan written for this was worse than the grep and under-reported, because it filtered on
`UI_HTML[...]` and one slice is taken over an INTERMEDIATE VARIABLE
(`_rep = _rep[:_rep.index("// tabs")]`). That undercount then travelled into five agent briefs as
fact. The lesson is not "prefer grep": it is that a derivation is only as good as its assumption
about the shape of the thing, and this one has two shapes.

All of them survive an order-preserving split. **All of them die under any "logical" regrouping.**
So: cut at existing seams, keep the sequence, change nothing else in the same commit.

**Both scripts have now been cut this way, and the order lives in exactly one place per
surface:** `_report_ui._SCRIPT_PARTS`, `_report_ui._CSS_PARTS` (declared as
`_ui_theme.REPORT_CSS_PARTS`, where the theme lints can see the shipping cascade) and
`_panel_ui._JS_PARTS`. A harness that needs the order reads it from there — `sandbox.mjs` parses
the tuple out of the Python rather than keeping a list of its own.

What each cut had to solve, kept because the next one will meet the same shapes:

- **`panel.js` — the first part declares, the last part boots.** Alphabetical ordering is not
  safe: every `function` hoists, but each top-level `const`/`let` is in TDZ until its own line
  runs, and `$`, `el` and `api` are read by executable statements a few lines below them. So
  `panel/core.js` is first and `panel/boot.js` last, and `test__panel_ui.py` pins both by NAME
  plus `list(_JS_PARTS) != sorted(_JS_PARTS)` — sorting the tuple would otherwise leave every
  Python suite green and the page dead.
- **`report.js` — the IIFE wrapper moved into `_report_ui._script()`.** It straddled the whole
  file, so a naive split left every part individually unparseable, defeating the "real,
  editor-highlightable files" rationale. Dropping it instead was never an option: ~130 bindings
  would land in the global scope of a page that already carries `window.AUDIT_USAGE`. (The block
  is now `type="module"`, and the module scope does that job natively.)
- **Byte-identity cannot see a part that nothing loads.** Both sides of `assembled == parts
  joined` are built from the same tuple, so dropping an entry shrinks both and the check stays
  green while the feature silently stops shipping. `declared_asset_drift()` compares the declared
  list against the DIRECTORY; the case that compares it against what the page is BUILT from is a
  separate one, and it is the only thing that fails. Write it, and prove it red by deleting an
  entry.
- **A guard that reads a part by path is a guard bound to a filing decision.**
  `tools/capture-screenshots.mjs` read `ui/panel.js` literally, with an argument at the site for
  why that could not go stale (a UI asset is not a script, so it cannot be relabelled). The
  argument was sound about relabelling and silent about the file simply ceasing to exist. It asks
  `_panel_ui.py` for the assembled page now, which was its subject all along.
- **Keep every part under the 400-line navigability threshold, or give it two section markers.**
  `_deps.ui_navigability_violations()` wants `max(2, ceil(lines/400))`. Cutting at author seams
  alone left three parts over 400 with one marker each, so those needed one further cut at a
  top-level boundary — taking the leading comment block WITH the function it introduces.
- `node --check` per part is possible after a split, and CI does it with `find`, not a glob:
  `ui/*.js` now matches nothing at all.

**The strongest reason to do the pure cut before anything else:**
`tools/check-report-interactive.mjs` never opens `report.js` — it drives the rendered artifact in
a browser. If the join preserves order, the output is byte-identical and all of its assertions
pass untouched. That makes the cut provably behaviour-free.

## The pins are the budget

Substring assertions guard the assembled artifacts, and they live in `plugins/audit/tests/`.
The split across targets is very uneven, so **budget by printing it, not by reading it here**:

```bash
python3 tools/count-ui-pins.py            # --json for a machine-readable shape
```

| target | a change to… |
|---|---|
| `UI_HTML` | anything in `panel.{css,js}` |
| `_SCRIPT` | `report.js` |
| `_CSS` | `report.css` |
| `TOKEN_CSS` | `_ui_theme.py` |

**The counts used to be in that table and every one of them rotted, repeatedly.** The total once
read "~70", which was roughly the CSS subtotal presented as if it covered everything; the
replacement written to fix that was wrong too; the four-way split was wrong on all four; and the
order figure had counted `.index()` CALLS when a slice takes two of them. A scoped number travels
without its scope, so the numbers are gone and the command stays.

The tool walks the AST, and the greps that preceded it could not. A line-based regex cannot see a
pin whose literal is split across lines — the closing line reads `in M.UI_HTML)` with no literal
on it — and cannot express a comparison whose left side is not a literal at all. It also separates
LITERAL left-hand sides from COMPUTED ones, which is the distinction both greps silently collapsed,
and counts the `.index()` slices that pin statement order separately, because those fail
differently.

Some pin multi-line source text *including newlines and leading spaces*, so reflowing a rule turns
them red.

Treat each red pin as a **review checkpoint, and update it on purpose**. A pin deleted rather than
updated is the failure this whole area is guarded against.

### Read the label against the clauses before you update

**A pin whose label names a BEHAVIOUR while its clauses assert HOW the code is written keeps
passing after the behaviour is gone.** Three went red on one day for this reason, and all three
were right to: one labelled "a tip whose anchor was re-rendered away is hidden" asserted that
`boot` ended with `startTipPlacement();`; one labelled "the topbar names the identity a write will
be recorded under" asserted the spelling of the render sequence; one labelled "the refresh defers
while a control in a CLEAN form is focused" asserted a hand-typed CSS selector. Each clause was a
fair proxy the day it was written, and none of them would have failed if the behaviour it was
named for had been deleted.

So when a pin goes red, ask which of the two it was really holding:

- **A behaviour** — move it to a suite that can execute the behaviour (`tools/ui-tests/*.test.mjs`
  for a pure function or a control-flow claim, the browser gates for anything painted), and leave
  behind only the construct that suite depends on, labelled as a construct.
- **A property of the source** — "there is no second list of view ids", "these three sites call one
  function", "this file contains no wall-clock call". Source text is the right instrument for those
  and nothing else can check them. Say so in the label.

A slice endpoint that stops resolving is the good outcome, not the bad one: it raises. The bad
outcome is an endpoint that still resolves somewhere else, because the window then silently
changes size and the assertion goes on passing about a different span.

Negative pins worth memorising: no hand-tuned sticky offset may reappear; the name `--chip-ink`
is forbidden; and `report.js` may contain **no wall-clock call at all** (`Date.now()`, `new
Date()`), which constrains what a shared date helper may contain.

### Some pins currently enforce the duplication

`plugins/audit/tests/test__panel_page.py:501` asserts `UI_HTML.count("'data-discard':'") == 4` and
`count("discard.disabled=!n;") == 3`. The five copy-pasted save/discard footers are therefore
*required to be five*. Factoring them into one helper turns the suite red — correctly, because the
pin is doing its job. **Deduplication here is always a paired change with `test__panel_page.py`,
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
- **Extract the helper rather than retyping it**, into
  `plugins/audit/scripts/ui/shared/`, which now EXISTS. That sentence used to name a
  directory that did not, and it lost: complying meant inventing the folder and wiring it,
  none of which was written down, while retyping ten lines was one edit. Fifteen rules were
  retyped under that instruction. The rule to apply is a promotion rule — **one reader stays
  put, two readers move up** — and the wiring is four steps, so it is no longer the expensive
  option:

  1. add the part to `plugins/audit/scripts/ui/shared/`, at column 0;
  2. list it in `_ui_theme.UI_ASSETS` (sorted) — `declared_asset_drift()` checks both ways;
  3. add it to **both** `_report_ui._SCRIPT_PARTS` and `_panel_ui._JS_PARTS`, before every
     surface part — a case in each assembly suite asserts that precedence, which is what
     makes "a shared part may not call a surface helper" mechanical;
  4. give it a row in `ui/shared/README.md`.

  The rule is enforced, not requested: `_deps.SHARED_CONCERNS` lists each concern
  with its home and a cap on copies outside it, and `shared_concern_violations()`
  fails the build when a second implementation appears. Add a row when you extract
  something; add a row with today's count when you find duplication you are not
  extracting yet, and the cap can then only go down.

  Check the name is free on **both** surfaces first — one scope per page, and the report's
  block is a module, so a duplicate top-level declaration is a `SyntaxError`, not a shadowing
  bug you find later:
  `grep -rnE '^\s{0,2}(function|const|let) NAME\b' plugins/audit/scripts/ui/`.
  A shared part may use only what passes BOTH gates above, and `ui/shared/README.md` lists the
  `file://` consequences — including that the four letters `http` may not appear even in a
  comment, because `x5` reads text.
- **A number rendered by more than one surface has one implementation**, and its cases pin it
  against the Python that renders the same number elsewhere. That agreement is a claim; test it.
- **Wrap each independent feature in its own `try`/`catch`** at the registration point, so one
  broken feature cannot blank a report someone opened from a CI artifact:

  **The panel already has this as a function** — `runContained` in `ui/panel/core.js`, which
  returns the names that threw rather than reporting them itself. `boot()` routes its view
  renderers, then the initial-tab restore, then the pollers through it — separate calls rather
  than one list, because the order between those groups is load-bearing. Call it; a retyped loop is a second
  implementation of the same rule.

  ```js
  const broke = runContained([themeToggle, filterBar, heatmap]);
  if (broke.length) toast('these are not up: ' + broke.join(', '), 'err');
  ```

  It has one reader today, so it sits in the panel's core rather than `shared/` — the report wires
  its features individually and has no registration point to route through.

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
python3 tools/sweep-selftests.py
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
