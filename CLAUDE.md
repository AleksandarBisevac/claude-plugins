# Working on this repo

A Claude Code plugin marketplace (`quality-gates` → plugin `audit`). Python here is **hooks and
CLI scripts**, not a package: there is no `[project]` table, nothing is installed, nothing is
published. It dogfoods its own plugin, so your edits run under its plan gate and TDD reminder.

`CONTRIBUTING.md` is the rulebook and `PLUGIN-BUILD-GUIDE.md` is the architecture. This file
states only what you must know *before* an edit; it deliberately restates no procedure, because
two copies of a procedure is one copy and one lie.

## Hard rules

- **Stdlib only** in `plugins/audit/{hooks,scripts}/`. A guard that needs `pip install` is a
  guard that is off on most machines. `py-launch.sh` stays POSIX-sh builtins only.
- **No `typing`, no `dataclasses`, no annotations, no walrus, no `from __future__`.** Not a style
  guide — `_output.house_style_violations()` reads the AST and fails the build. The 3.8 floor and
  hooks that must start fast on every tool call are the reason.
- **Python 3.8 floor**, held by `vermin -t=3.8-` in CI. Formatting is `%`-style throughout; the
  tree contains no f-strings.
- **Every `.py` under `hooks/` and `scripts/` is scanned wherever it sits** — CI's sweep and the
  lints in `_output.py` and `_deps.py` all walk recursively. The old rule saying files must stay
  one directory deep existed only because those scanners were flat, so a file in a subdirectory
  silently stopped being tested; that reason is gone. The one cost is that a `.py` **basename must
  be unique** across the whole of `scripts/`, since `import` and `_loader` both resolve by
  basename — `layer_violations()` reports a collision by name. `scripts/ui/` still holds no `.py`.
- **`_output.py` is the anchor and never moves.** `SCRIPTS_DIR`, `PLUGIN_ROOT`, `HOOKS_DIR`,
  `TESTS_DIR` and `REPO_ROOT` live there and nowhere else; `install_path()` puts `scripts/` and
  every subdirectory of it holding a `.py` on `sys.path`. **The folders are labels, not
  namespaces** — one flat name-space, every module reached by bare basename. No other `.py` under
  `scripts/` may read `__file__` outside the pinned preamble (`depth_sensitive_paths()`).
- **Fail-open for advisory paths, fail-loud for guards** — the table is in `SECURITY.md`.
- **Every claim in output carries the basis that makes it true, and when the basis is missing,
  that is the thing to say.** Never fall back to a default to fill the gap; a basis with no claim
  is noise. See `CONTRIBUTING.md` for the worked example (cost, and the five surfaces that
  render it).
- Every command that mutates the manifest revalidates via `scripts/manifest/validate-manifest.py`.

## Adding a `.py` under `hooks/` or `scripts/`

Five things beyond the code, and four of them fail CI *by name* if missed:

1. a `--selftest` printing the `N/M cases passed` contract — CI globs the directories and fails a
   file that has none;
2. `safe_stdio()` as the **first** statement in `__main__` (AST-enforced by `_output.py`);
3. a layer assignment in `_deps.LAYERS` (the import-graph lint fails an unplaced file);
4. a tree line **and** a section in `PLUGIN-BUILD-GUIDE.md` (the enumeration lint);
5. **`scripts/` only** — `_output.PATH_PREAMBLE`, pasted byte for byte after the stdlib
   imports and above the first sibling import. Copy it from any neighbour;
   `path_preamble_violations()` counts it (once, never twice) and checks the ordering, and
   `depth_sensitive_paths()` fails any file that reads `__file__` outside it. `hooks/` gets
   none of this — hooks may not import `scripts/`, so they resolve by basename through
   `hooks/_config.find_script()` instead.

Name by role: `_underscore.py` for an importable helper, `hyphen-name.py` for an entry point.
Files of 400+ lines need at least two top-level `# --- name ---` markers to stay navigable.
New behaviour means new selftest cases — the selftests are this project's test suite.

## Which skill covers what

Read the one for the language before writing, not after. Each states the house dialect, the
modular structure, the DRY rule, what makes the code testable, and the anti-patterns that have
actually bitten here.

| Writing… | Skill |
|---|---|
| Python | `writing-python` |
| browser JavaScript | `writing-javascript` |
| CSS | `writing-css` |
| any `--selftest` case, guard or lint | `no-silent-pass` |
| splitting or sharing `ui/` parts | `refactoring-the-assembled-ui` |
| a sync/batch job against a remote API | `running-resumable-sync-jobs` |
| anything depending on an external API's behaviour | `verifying-external-behavior` |
| a check that passes locally and fails in CI | `reproducing-ci-locally` |

## The front end is not ordinary files

`plugins/audit/scripts/ui/` holds **ordered parts of one artifact**, not standalone files: Python
concatenates them into **one inline `<style>` and one inline `<script>` carrying code**, in a
self-contained page opened over `file://`. No ESM, no bundler, no external resource of any kind.

*Carrying code* is the load-bearing half of that sentence. The panel really does emit one of
each; **the report emits three `<script>` tags** — `window.AUDIT_USAGE`, the base64 Markdown twin,
and the code. The pin that reads `SCRIPT.count("<script>") == 1` counts tags in a **Python
string**, not in the page, so it does not contradict this and never did.

**723 exact substring assertions guard the assembled output**, and they live in
`plugins/audit/tests/` — not in the scripts that build it. Some *require* duplication to stay as
it is. What a UI change has to budget for, by what it pins:

| target | pins | built by |
|---|---:|---|
| `UI_HTML` | 564 | the panel page |
| `_SCRIPT` | 100 | the report's code block |
| `_CSS` | 48 | the report's stylesheet |
| `TOKEN_CSS` | 11 | `_ui_theme.py` |

Only **59 are CSS-shaped** (`_CSS` + `TOKEN_CSS`); the other 664 pin JavaScript. A further
**113 assertions slice by `.index()` for statement *order*** — 47 in `test__panel_page.py`, 39 in
`test_render_report.py`.

This figure stood at "~70", which is roughly the **CSS** count (49 on the day it was written, 59
now) presented as if it covered everything — the two files it named held 1,022 pins between them
at that commit. A number is only as good as the scope attached to it, and this one lost its scope
in transit. **Re-derive it rather than trusting the table**: a count in prose rots, and the first
replacement written here was itself off by 73 because it matched only double quotes and missed
`not in`.

```bash
grep -rhoE '("[^"]*"|'"'"'[^'"'"']*'"'"') (not )?in M\.(UI_HTML|_SCRIPT|_CSS|TOKEN_CSS)' \
  plugins/audit/tests | wc -l
```

**Read the `refactoring-the-assembled-ui` skill before editing `report.{css,js}`,
`panel.{css,js}` or `_ui_theme.py`.** Assets of 400+ lines also owe one section marker per 400
lines, enforced by `_deps.ui_navigability_violations()`.

## Tests

```bash
for f in $(find plugins/audit/hooks plugins/audit/scripts -name '*.py' | sort); do python3 "$f" --selftest || exit 1; done
for f in $(find plugins/audit/tests -name '*.py' | sort); do python3 "$f" --selftest || exit 1; done
ruff check plugins/audit tools
vermin -t=3.8- --no-tips --violations plugins/audit/scripts plugins/audit/hooks plugins/audit/tests
```

**The second line is not optional and not decoration.** Every `--selftest` block has moved out
of the module it tests into `plugins/audit/tests/`, all 48 of them; a migrated file still exits
0 on `--selftest` and prints where its cases went, so the first line stays green over suites it
no longer runs. `_output.selftest_coverage()` is what keeps the two halves honest — the
migration is finished, so `covered` is the only clean class: a file with a suite INLINE, with
both, or with neither is a defect it names.

`CONTRIBUTING.md` has the manifest and plugin-structure checks that complete the pre-PR set. The
browser-level gates (`tools/capture-screenshots.mjs --check`,
`tools/check-report-interactive.mjs`) are the only thing that can prove the report actually
paints and stays interactive — a selftest can only assert what the CSS *says*.

A check that has only ever been seen passing may be asserting nothing. Break the thing it guards
and confirm it goes red before trusting it.

## Releasing

One release is **one commit** that bumps `plugin.json`, finalizes the `CHANGELOG.md` section, and
carries the annotated `v<version>` tag. Push only after CI is green **on that commit**. A pushed
tag is never moved or deleted — fix forward.

**Do not commit, push, tag or release without being asked.** Permission to commit is not
permission to push.

## Recommending between options

**The recommended option is the structurally correct one** — the one that produces the better
structure, the better-established practice, the clearer syntax, the better-optimised code. Effort,
blast radius and risk are reported as **facts about** an option, in numbers, and never as the reason
it is recommended. When the correct option is expensive, that is a schedule problem to state plainly
— not grounds for relabelling the cheap one.

A cost that is not merely effort but a real consequence — a published URL breaking, a user's CI
failing on upgrade — is named as a consequence to publish, not as a reason to retreat.

`plugins/audit/{commands,skills,agents,hooks}/` are the plugin's **product**, not this project's
configuration. They share their names with `.claude/`'s directories and answer a different question:
`commands/status.md` is what a user invokes as `/audit:status`. Advice about organising `.claude/`
does not apply to them.

## Before proposing a change

`CONTRIBUTING.md` ends with a **Decision record** — settled questions, each with an observable
revisit trigger: `commands/` alongside thin skills, flat `scripts/`, the `typing` ban, in-product
help as an endpoint plus an invoked agent rather than an auto-triggering skill. Read it before
re-opening one of them, and if a trigger has genuinely fired, say which.

Bugs found along the way go into the plan's Faults section when one is active, rather than being
fixed inline in an unrelated change.
