# Where these skills came from

Dev-time skills for working *on* this repo. They are **not** part of the shipped plugin — that is
`plugins/audit/skills/`, which stays thin routers per the `commands/ vs skills/` decision record.
Nothing here reaches anyone who installs `audit`.

Recording provenance so a later refresh is a diff rather than archaeology, and so the licence
terms travel with the text.

## Copied

Source: <https://github.com/wdm0006/python-skills> at commit `45b073a8872b` (2026-08-12).
Licence: **MIT, © 2025 Will McGinnis**. Upstream ships them as `@dev-skills`; copied rather than
installed so they stay version-controlled, editable, and scoped to this repo.

| Here | Upstream path | Changed |
|---|---|---|
| `verifying-external-behavior/` | `skills/common/verifying-external-behavior/SKILL.md` | verbatim, except one cross-reference retargeted to `no-silent-pass` |
| `running-resumable-sync-jobs/` | `skills/common/sync-jobs/SKILL.md` | dropped the reserved-quota / SaaS-metering section and its checklist item (no billing surface here); description trimmed to match; cross-references retargeted |
| `reproducing-ci-locally/` | `skills/common/reproducing-ci-locally/SKILL.md` | dropped the `uv`/venv environment-building section and rewrote its checklist block as *Pinning* — this repo is stdlib-only with nothing to install, so that third of the file was actively misleading; description trimmed to match |

Upstream directory names differ from the frontmatter `name:` in one case
(`sync-jobs` → `running-resumable-sync-jobs`); directories here match the `name:`.

**To refresh:** re-fetch at a newer ref, diff against the upstream file at `45b073a8872b`, and
re-apply the trims above rather than overwriting.

```bash
gh api "repos/wdm0006/python-skills/contents/skills/common/<dir>/SKILL.md?ref=45b073a8872b" \
  --jq .content | base64 -d
```

## Copied from airails

Source: <https://github.com/AdamBien/airails> at `main`, fetched 2026-08-16.
Licence: **MIT, © 2025 Adam Bien**.

| Here | Upstream path | Changed |
|---|---|---|
| `refactoring-the-assembled-ui/references/baseline-snapshot.md` | `web/web-conventions/references/baseline-snapshot.md` | verbatim |

1,177 rows of `feature id | name | status | newly since | widely since`, header-dated
**2026-07-08**, generated from `api.webstatus.dev` by [zbaseline](https://github.com/AdamBien/zbaseline).
It is a table to grep, not to read. **Never edit it in place** — refresh by replacing the whole
file from a newer upstream fetch, and update the date referenced in the skill.

Its skills themselves were *not* vendored. `web-conventions` bans inline styles and
token-translation tooling, both of which this repo requires; `javascript-conventions` and
`web-sprinkles` mandate ES modules, which are structurally impossible in a single inline script
over `file://`; `web-performance-reviewer` needs a Chrome DevTools MCP and its two largest
sections are vacuous for an artifact with zero external requests. Their transferable rules —
failure-isolated feature registration, `data-` attribute hooks, organize-by-feature, no
`*Utils`/`*Helper` names, per-directory responsibility docs — are written into
`refactoring-the-assembled-ui` in this repo's own terms. One rule is deliberately **inverted**:
their "avoid `#private`, module scope already encapsulates" is false in a concatenated script,
where every top-level name shares one scope.

## Written here

- **`no-silent-pass/`** — original text, not a copy. Distilled from the reasoning sections of
  upstream's `testing-strategy`, `code-quality` and `api-design`, which each carry roughly 40%
  advice this repo forbids (pytest, mypy, type hints, `src/` layout) and overlap heavily with one
  another. Rewritten for `--selftest` suites and the stdlib-only, annotation-free house style, and
  anchored on defects this repo has actually had.
- **`writing-python/`**, **`writing-javascript/`**, **`writing-css/`** — original text, one per
  language, written to fire at *write* time rather than at review time. Nothing off the shelf
  fits: every Python best-practice skill in the registry opens by mandating `typing`,
  `dataclasses` and annotations — precisely what `_output.house_style_violations()` fails the
  build for — and the JS/CSS ones assume a bundler, ESM, TypeScript or a framework. Each is
  written from a measurement of this tree rather than from received wisdom: 734 free functions
  against 6 classes in the Python, 590 arrow functions in `panel.js` against 0 in `report.js`,
  605 `var(--…)` references against 13 raw hex in `panel.css`. Re-measure before rewriting them.
- **`refactoring-the-assembled-ui/`** — original text. No public skill covers a front end that a
  build-less pipeline concatenates into one inline `<style>` and one inline `<script>`; across
  ~1,100 lines of airails guidance there is no file-size rule, no decomposition heuristic, no
  strategy for sharing between two entry points, and no CSS naming convention. Written from a
  direct audit of `ui/` and of the assertions in `render-report.py` and `panel-server.py` that
  guard it — including the count pins that currently *require* the duplicated save/discard
  footers, and the index-slice pins that make the present statement order a checked contract.

## Deliberately not taken

Upstream's Python half assumes a PyPI library: `uv`/`hatch` setup, `ruff` + `mypy`, `pytest` +
`hypothesis`, Click/Typer, Sphinx, trusted publishing. `typing`/`dataclasses`/annotations are
AST-enforced bans here (`_output.house_style_violations()`), so `code-quality`'s headline advice
is the thing that fails this build. `rendering-untrusted-content` — the best topical fit for the
HTML report — rests entirely on `nh3` + `markupsafe`, neither of which may be imported.

`derived-metrics`, `build-artifacts`, `cross-surface-changes`, `git-hygiene` and `github-actions`
describe disciplines already enforced mechanically here (`cost_bands`' sample gate,
`_deps.guide_enumeration`, the `docs/index.html` byte-compare, `guard-secrets-read`), so copying
them would add a second, weaker statement of rules that already have lints behind them.
