---
name: writing-javascript
description: How browser JavaScript is written in this repo — both surfaces now speak one modern dialect and this says what that means for the code you type, where ES modules are impossible and where they are merely unused, and how to pick a feature (Baseline plus a file:// gate). Covers functional idiom over imperative DOM work, the shared helper layer, modular structure without a bundler, DRY across the report and the panel, keeping features isolated so one failure cannot blank a page, readability, testability through the black-box browser gates, and the anti-patterns that have already shipped bugs here. Use when planning, writing, reading, reviewing or refactoring anything under scripts/ui/report/ or scripts/ui/panel/, when adding a UI behaviour, or when a helper is about to exist twice.
---

# Writing JavaScript here

There is no bundler, no npm, no TypeScript and no build step. The ordered parts under
`ui/report/` and `ui/panel/` are concatenated by Python into exactly one inline `<script>` per
page. The mechanics of that — ordering, the byte pins, splitting — belong to
`refactoring-the-assembled-ui`. This file is about the code you type.

## Which dialect

**Modern ES, in both — and both surfaces now speak it.** This section used to carry a table
showing `report.js` as strictly ES5 against a modern `panel.js`; that gap was closed, and the
table went on describing it. Re-derive rather than reading a number here:

```bash
for d in report panel; do
  printf '%s: var=%s function()=%s\n' "$d" \
    "$(grep -rho '\bvar ' plugins/audit/scripts/ui/$d/ | wc -l | tr -d ' ')" \
    "$(grep -rho 'function *(' plugins/audit/scripts/ui/$d/ | wc -l | tr -d ' ')"
done
```

Both are at zero `var` and zero `function ()`. What is NOT yet symmetric is JSDoc — the report's
parts carry a block per exported behaviour and the panel's parts carry almost none — and since
this project has no TypeScript, JSDoc is the type system it gets. Types must be specific
(`{HTMLTableRowElement}`, `{(a: string, b: string) => number}`), never `{Object}`; when the type
and the code disagree, fix the CODE.

`let-const` has been Baseline *widely available* since 2019-03-20, and every other modern
construct this code would use is in the same bracket. Check before assuming, though —
`grep '^| let-const '` in
`.claude/skills/refactoring-the-assembled-ui/references/baseline-snapshot.md`.

Two gates before using any feature. **Baseline**: widely = free, newly = feature-detect with a
fallback, limited = no. **`file://`**: Baseline measures engines, not schemes — `js-modules` is
widely available since 2020 and still impossible here, and `localStorage` is widely available and
inconsistent from disk (which is why every storage call in the tree is already wrapped in
`try`/`catch`). A feature must pass both.

**ES modules: not available in the report, and available-but-unused in the panel.** Do not
compress this into "modules are impossible here", which is what the previous version of this line
said and what kept the question closed. In the REPORT they are impossible: the block IS
`type="module"` — a module scope is the point — but `import`, `export` and dynamic `import()` all
need loading, and loading is what an opaque `file://` origin refuses. The PANEL is served over
`http://127.0.0.1`, where a cross-file import works; it is measured, with a `file://` control in
the same run failing as the report does. Writing one still needs a static route in
`panel-server.py` and a new home for the `__*__` placeholders, so until that lands the panel's
parts contain no `import` either — but the reason is a missing route, not the platform. See
`refactoring-the-assembled-ui` for what adopting it would cost.

## Functional idiom

`panel.js` already reads this way and it is the target for both surfaces.

- **`map`/`filter`/`reduce` when the result is a value**; a `for` loop when the point is a side
  effect. Do not force either.
- **Build DOM with the `el()` helper, not `createElement` + `appendChild`.** `el()` is used at
  693 sites in the panel and takes `(tag, attrs, ...children)`, handling `class`, `on*` handlers
  and text nodes. Hand-rolled DOM assembly is longer, easier to get wrong, and cannot be shared.
- **A render function takes state and returns a node.** Do not have it also fetch, also persist,
  and also toast. The panel's six tab renderers are where this has drifted — seven functions over
  100 lines account for a third of that file — so a new one should not join them.
- **`const` by default, `let` when it is reassigned, `var` never.**
- **No classes.** There are zero in either file and no reason to introduce the first.
- **Do not mutate a caller's object.** Return a new one, the way the Python side does.

## Structure, and the shared layer

Every top-level name in the concatenated script shares **one global scope** — the panel currently
leaks around 302 names. The advice "module scope encapsulates" is false here.

- **Prefix by feature**, as the panel already does (`u*` usage, `p*` policy, `t*` theme, `ov*`
  overview). The file itself records the near-miss this prevents: `manifestFindingsBox` is named
  that way only because a second `findingsBox` would have hoisted over the first and broken every
  config save.
- **Group by feature, not by artifact.** `report.* / panel.*` is a split by output file, which is
  exactly why the same feature exists twice.
- **Anything both surfaces need goes in the shared layer, once.** Today the duplication is real
  and measured: two `isDark()`, two tooltip placers, two CSV quoters, two blob downloaders, two
  heatmap calendars — roughly 430 lines of the same logic retyped into the other dialect, with
  the comments copied verbatim.
- **Reach elements through dedicated `data-` attributes, not styling classes.** The hook is then
  explicit and greppable, and renaming a CSS class cannot silently break behaviour.
- **Wrap each independent feature so its failure is contained.** A report is opened from a CI
  artifact by someone who cannot fix it; one throwing feature must not blank the page:

  ```js
  for (const feature of [themeToggle, filterBar, heatmap]) {
    try { feature(); }
    catch (cause) { console.error('feature failed: ' + feature.name, cause); }
  }
  ```

## Readability

- Name handlers for **what happens**, not for the event: `clearFilters`, not `onClick`.
- Extract a multi-statement callback into a named function; keep inline callbacks to one
  expression.
- Name the predicate rather than inlining a three-term condition.
- Comment the constraint, not the mechanism — the comments worth keeping in this tree say what
  broke once.
- No `*Utils` / `*Helper` names.

## Testability

The real test is a browser. `tools/check-report-interactive.mjs` drives the rendered report over
`file://` and never opens the source — which is what makes it trustworthy, and what makes an
order-preserving change provably behaviour-free. `tools/capture-screenshots.mjs --check` drives
the panel.

So: **write behaviour that is observable from the DOM.** A feature whose only evidence is an
internal variable cannot be checked by either gate. State that a reader can see — a class, an
`aria-pressed`, a row count, a `data-` attribute — is state a test can assert.

Prefer **event delegation on a container** over a listener per element. The report does this
deliberately for 1000+ marks; the panel re-derived the same conclusion locally for a 168-cell
grid rather than adopting the mechanism.

## Anti-patterns and pitfalls

- **`innerHTML` with anything derived from the manifest.** Escaping is systematic on the Python
  side; do not open a new hole on the client. Use `textContent`, or the `el()` builder.
- **Implicit globals** — always declare. One stray assignment lands in the shared scope.
- **`var`**, and relying on hoisting. Every top-level `const`/`let` is in TDZ until its line runs,
  which is also why part order is load-bearing.
- **A listener per element** at scale.
- **`Date.now()` / `new Date()` in `report.js`** — pinned as forbidden, because a wall-clock call
  makes the rendered artifact non-reproducible.
- **Two implementations of one number.** The token formatters already disagree: `uTok(2.6)`
  gives `"3"`, `fmtTokens(2.6, 1)` gives `"2"`, and both claim to mirror the same Python.
- **Adding a feature the platform already has.** `<details>`/`<summary>` for disclosure,
  `<dialog>` for modals, `:target` for deep links. Deleted JavaScript is the cheapest JavaScript.
- **Loading anything external** — no CDN, no font, no image URL. CI asserts the report contains
  no `<script src`, `<img `, `<link `, `<iframe` or `url(http`.
