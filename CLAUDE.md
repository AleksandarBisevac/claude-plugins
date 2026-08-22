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
- **Do not write a number into prose when something already prints it.** This is the repo's
  most frequent defect (F29, F39, F43 are one bug three times), and it is now a lint:
  `_output.prose_number_claims()` over `hooks/` + `scripts/` and `_deps.doc_prose_numbers()`
  over this file, `CONTRIBUTING.md` and `PLUGIN-BUILD-GUIDE.md` fail the build on a
  present-tense cardinality (`its N cases`), persistence (`` `NAME` stayed at N ``) or
  completeness (`all N of them`, `all N … have`) claim. Three things stay legal on purpose:
  **history** (`it stood at N that day`), a number **carrying the command that re-derives it**
  — the basis may sit on the next line, because prose wraps — and the repair itself, which is
  to delete the number and keep the pointer. When a number really is informative, carry the
  basis; a basis makes a claim checkable, but only deleting the number stops it rotting.
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
self-contained page opened over `file://`. The report's code block is a **module script**
(`<script type="module">`), which is where its scope comes from — but `import` between files
is impossible on an opaque origin, so Python still does the joining. No bundler, no external
resource of any kind.

*Carrying code* is the load-bearing half of that sentence. The panel really does emit one of
each; **the report emits three `<script>` tags** — `window.AUDIT_USAGE`, the base64 Markdown twin,
and the code. The pin that reads `SCRIPT.count("<script>") == 1` counts tags in a **Python
string**, not in the page, so it does not contradict this and never did.

**Substring assertions guard the assembled output**, and they live in `plugins/audit/tests/` —
not in the scripts that build it. Some *require* duplication to stay as it is. What a UI change
has to budget for is the pins against the surface it touches, so **print them before you start**:

```bash
python3 tools/count-ui-pins.py            # add --json for a machine-readable shape
```

It reports each target separately, because that is what a change budget needs: `UI_HTML` is the
panel page, `_SCRIPT` the report's code block, `_CSS` the report's stylesheet, `TOKEN_CSS`
`_ui_theme.py`. It also separates the **literal** left-hand sides from the **computed** ones, and
counts the `.index()` slices that pin statement *order* — which fail differently, because moving
an endpoint silently changes what the window covers.

**This section used to carry those numbers, and every one of them rotted.** Six figures were wrong
at once here, twice: a total, a four-way table, a CSS subtotal, and an order figure that had
counted `.index()` CALLS when a slice takes two of them. Two of those were already scars — the
total once stood at "~70", which was roughly the CSS number presented as if it covered everything,
and the replacement written to fix that was wrong too. So the numbers are gone and the command
stays, which is what this file's own rule about numbers in prose prescribes.

The tool walks the AST, which is what the greps before it could not do. A line-based regex cannot
see a pin whose literal is split across lines — the closing line reads `in M.UI_HTML)` with no
literal on it — and cannot express a comparison whose left side is not a literal at all
(`json.dumps(M._cfg_enums(), sort_keys=True) in M.UI_HTML`). Those two blind spots are why a
documented grep under-reported by dozens and why a third regex was never the answer.

**Read the `refactoring-the-assembled-ui` skill before editing anything under `scripts/ui/`, or
`_ui_theme.py`.** Neither surface is a single file any more — the report's script and stylesheet
and the panel's script are each a directory of ordered parts, and `ui/*/README.md` says what each
part is for. Assets of 400+ lines also owe one section marker per 400 lines, enforced by
`_deps.ui_navigability_violations()`.

## Tests

**`tools/verify.sh` runs every gate below in one command** — `--fast` for iteration
(narrower browser sweeps, prints what it skipped, never a gate), `--release` to add
the checks a version bump owes. Prefer it: running these by hand cost two red CI
runs in one day, both from a forgotten step rather than a broken change.

The commands it calls, which remain the definition:

```bash
python3 tools/sweep-selftests.py           # hooks + scripts + tests, in parallel
python3 tools/sweep-selftests.py --selftest
python3 tools/gate-parity.py               # this list, verify.sh and ci.yml, compared
npx vitest run                             # the JavaScript unit tests
ruff check plugins/audit tools
vermin -t=3.8- --no-tips --violations plugins/audit/scripts plugins/audit/hooks plugins/audit/tests
```

**The sweep is one runner, and CI runs the same one.** It used to be a serial `for` loop
written out twice — here and inlined in `ci.yml` — and the two copies checked different
things: the local one asserted the exit code alone, so a file that exited 0 having asserted
nothing was green locally and red in CI. `tools/sweep-selftests.py` is the single copy, it
holds the union of both rules, and it runs the tree across all cores but two. Re-derive the
wall clock rather than trusting a figure written here; `--jobs 1` gives the old serial shape
for a bisect.

**`gate-parity.py` is why that cannot come back.** This list, `tools/verify.sh` and
`.github/workflows/ci.yml` were three hand-maintained copies of one gate set and had drifted
in both directions at once — the sweep above, `vitest` (which ran only in CI, so a change under
`scripts/ui/` could reach a push with none of its suites having run), and `vermin`'s directory
list. A gate added to one side and not the other now fails the build by name, and every
declared exemption carries a reason that is itself checked.

**Every `--selftest` block lives in `plugins/audit/tests/`, not in the module it tests**
(`73042a1` — count them with
`python3 -c "import sys;sys.path.insert(0,'plugins/audit/scripts');import _output;print(len(_output.selftest_coverage()['covered']))"`).
A migrated file still exits 0 on `--selftest` and prints where its cases went;
`_output.selftest_coverage()` is what keeps the two halves honest — the migration is finished,
so `covered` is the only clean class: a file with a suite INLINE, with both, or with neither is
a defect it names. The runner enforces the other half of that, which the old loop could not: a
migrated file that STILL prints the contract is red, because the classifier reads string
literals and a file assembling the line would otherwise slip past both.

`CONTRIBUTING.md` has the manifest and plugin-structure checks that complete the pre-PR set. The
browser-level gates (`tools/capture-screenshots.mjs --check`,
`tools/check-report-interactive.mjs`) are the only thing that can prove the report actually
paints and stays interactive — a selftest can only assert what the CSS *says*.

A check that has only ever been seen passing may be asserting nothing. Break the thing it guards
and confirm it goes red before trusting it — `tools/redfirst.sh` does that for one check, and

```bash
python3 tools/prove-gates.py          # --list to see the table without running it
```

does it for every load-bearing lint at once, naming the case that must fail. It mutates the tree
and restores each time, so it is minutes rather than seconds and is not a per-commit gate. Its
table is derived from the three lint modules by name, so a lint added without a row fails the
sweep — which is how the annotation half of `house_style_violations()` was found unenforced
after the document had claimed it for a long time.

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
revisit trigger: `commands/` alongside thin skills, **domain directories under `scripts/`**, the
`typing` ban, in-product help as an endpoint plus an invoked agent rather than an auto-triggering
skill. Read it before re-opening one of them, and if a trigger has genuinely fired, say which.

**Two of those entries were reversed with their trigger still green**, and for the same reason
both times: the trigger was a threshold on something incidental — a deprecation that might never
come, a file count — while the cost being paid was discoverability and navigability. So a green
trigger is not evidence that a decision is still right. When you propose one, phrase it as a
property of the system that *is* the cost, not as a proxy you can count.

Bugs found along the way go into the plan's Faults section when one is active, rather than being
fixed inline in an unrelated change.
