# Working on this repo

A Claude Code plugin marketplace (`quality-gates` → plugin `audit`). Python here is **hooks and
CLI scripts**, not a package: there is no `[project]` table, nothing is installed, nothing is
published. It dogfoods its own plugin, so its hooks fire on your edits.

**Which tier the plan gate is in is not a property this file may assert.** The gate grades
itself on evidence — observe with no manifest, warn with a manifest holding no phase, deny past the
free file once it holds phases, running or not — and this sentence used to say edits "run under" it, which reads as the
denying tier while only the weakest reading was true: the dogfood manifest's phases were all
finished when that was written, so the gate was advisory here and had been for releases. That is
exactly the kind of fact a document cannot keep. A document that names a gate owes the reader its
tier or should not name the gate, and the tier is computed rather than written down — so ask the
thing that computes it:

```bash
/audit:doctor          # prints which tier is active and what put it there
```

The TDD reminder is unconditional and non-blocking, so it needs no tier.

`CONTRIBUTING.md` is the rulebook and `PLUGIN-BUILD-GUIDE.md` is the architecture. This file
states only what you must know *before* an edit; it deliberately restates no procedure, because
two copies of a procedure is one copy and one lie.

## Hard rules

- **Stdlib only** in `plugins/audit/{hooks,scripts}/`. A guard that needs `pip install` is a
  guard that is off on most machines. `py-launch.sh` stays POSIX-sh builtins only.
- **No `typing`, no `dataclasses`, no annotations, no walrus, no `from __future__`.** Not a style
  guide — `_output_lints.house_style_violations()` reads the AST and fails the build. The 3.8
  floor and hooks that must start fast on every tool call are the reason.
- **Python 3.8 floor**, held by `vermin -t=3.8-` in CI. Formatting is `%`-style throughout; the
  tree contains no f-strings.
- **Every `.py` under `hooks/` and `scripts/` is scanned wherever it sits** — the coverage classifier and
  the lints in `tools/lints/` (`_output_lints.py`, `_deps.py`) all walk recursively. The old rule
  saying files must stay one directory deep existed only because those scanners were flat, so a
  file in a subdirectory silently stopped being tested; that reason is gone. The one cost is that a `.py` **basename must
  be unique** across the whole of `scripts/`, since `import` and `_loader` both resolve by
  basename — `layer_violations()` reports a collision by name. `scripts/ui/` still holds no `.py`.
- **`_output.py` is the anchor and never moves.** `SCRIPTS_DIR`, `PLUGIN_ROOT`, `HOOKS_DIR`,
  `TESTS_DIR`, `LINTS_DIR` and `REPO_ROOT` live there and nowhere else; `install_path()` puts
  `scripts/` and every subdirectory of it holding a `.py` on `sys.path`. **The folders are labels, not
  namespaces** — one flat name-space, every module reached by bare basename. No other `.py` under
  `scripts/` may read `__file__` outside the pinned preamble (`depth_sensitive_paths()`).
- **Fail-open for advisory paths, fail-loud for guards** — the table is in `SECURITY.md`.
- **Every claim in output carries the basis that makes it true, and when the basis is missing,
  that is the thing to say.** Never fall back to a default to fill the gap; a basis with no claim
  is noise. See `CONTRIBUTING.md` for the worked example (cost, and the five surfaces that
  render it).
- **Do not write a number into prose when something already prints it.** This is the repo's
  most frequent defect (the same bug, found three separate times), and it is now a lint:
  `_output_lints.prose_number_claims()` over every `.py` this repo keeps and
  `_deps.doc_prose_numbers()` over every `.md` (both in `tools/lints/`) — both sets **derived**
  off what git tracks, or off `.gitignore` where git cannot answer, so a
  file added here is scanned by default and excluding one means a row in
  `_output_lints.PROSE_SCAN_EXEMPT` with a reason. They fail the build on a
  present-tense cardinality (`its N cases`), persistence (`` `NAME` stayed at N ``),
  completeness (`all N of them`, `all N … have`) or ratio (`N of M <noun>` — the tally a
  command prints, quoted with no command beside it) claim — and the number may be spelled as a
  word: `_numeral_span()` reads both spellings, for every shape it knows, from
  one fixed table — except that a bare word under ten (`one case`, `two cases`) is off by
  default, because it is ordinary English and only a shape that supplies its own bound
  (`N of M <noun>`) may ask for it; `_numeral_span()`'s docstring carries the measurement. Three things stay legal on purpose: **history** (`it stood at N that day`),
  a number **carrying the command that re-derives it** — the basis may sit on the next line,
  because prose wraps — and the repair itself, which is to delete the number and keep the
  pointer. `CONTRIBUTING.md`'s *Writing a count that is allowed* states those three
  affirmatively, with one example each; read it before writing a number rather than after a
  build refuses one. When a number really is informative, carry the basis; a basis makes a
  claim checkable, but only deleting the number stops it rotting.
- **The lint does not cover the whole class, and the part it leaves is yours.** A plain
  `the N <noun>` with an ordinary noun — `five claims deep` — is **author-enforced in both
  spellings**, and so is a ratio you wrote yourself rather than quoted (`N of the M <noun>`
  carries an article no formatter emits). This is a refusal, not a gap waiting to be closed:
  the noun is unbounded, so reading it means reading every count in every sentence, and both
  widenings were measured over this tree and found to report honest prose almost exclusively —
  which is how a lint gets routed around. `prose_number_claims()`'s *WHAT IT CANNOT SEE* is the
  full list with the measurement behind each refusal, and `pn31` is the case that goes red if
  somebody widens one. So a green build is not evidence that a number you wrote is safe; it is
  evidence that none of the shapes the lint knows matched.
- Every command that mutates the manifest revalidates via `scripts/manifest/validate-manifest.py`.
- **`COMPATIBILITY.md` is a contract, not a description.** It promises that a `meta.version`
  the plugin accepts keeps being accepted and that a config key it reads keeps being read. So
  removing either, or changing which of two keys wins, is no longer a judgement call — it is a
  major release. Adding is always free. The document also names what is deliberately *not*
  promised; extend that list rather than quietly widening the promise.

## Adding a `.py` under `hooks/` or `scripts/`

Five things beyond the code, and four of them fail CI *by name* if missed:

1. a suite at `tests/test_<name>.py`, printing the `N/M cases passed` contract — never a
   `--selftest` in the module itself, since a shipped module answers none. Hyphens become
   underscores (`a-b.py` → `test_a_b.py`, `_x.py` → `test__x.py`). The sweep fails, by name, a
   module with neither a suite nor a row with a reason in `_output_lints.COVERAGE_EXEMPT`;
2. `safe_stdio()` as the **first** statement in `__main__` — **`scripts/` only**, AST-enforced by
   `_output_lints.entries_missing_guard()`; hooks stay importless, and CI's cp1252 sweep covers them;
3. a layer assignment in `_deps.LAYERS` (`tools/lints/_deps.py`; the import-graph lint fails an
   unplaced file);
4. a tree line **and** a section in `PLUGIN-BUILD-GUIDE.md` (the enumeration lint);
5. **`scripts/` only** — `_output_lints.PATH_PREAMBLE`, pasted byte for byte after the stdlib
   imports and above the first sibling import. Copy it from any neighbour;
   `path_preamble_violations()` counts its LINES (once, never twice) and checks the
   ordering, and `depth_sensitive_paths()` fails any file that reads `__file__` outside
   it. **Lines, not the whole block** — a file repeating only the
   `import _output` / `install_path()` tail carries the text once and bootstraps twice,
   so a count of the block read it as compliant. `hooks/` gets none of this — hooks may
   not import `scripts/`, so they resolve by basename through
   `hooks/_config.find_script()` instead.

Name by role: `_underscore.py` for an importable helper, `hyphen-name.py` for an entry point.
Files of 400+ lines need at least two top-level `# --- name ---` markers to stay navigable.
New behaviour means new selftest cases — the selftests are this project's test suite.

## Which skill covers what

Read the one for the language before writing, not after — and the one for the job before
deciding how to do it. Each states the house dialect, the modular structure, the DRY rule, what
makes the code testable, and the anti-patterns that have actually bitten here. The last row is
not about a language: it is about where an optimisation is worth spending, which is a decision
taken before any code is written and is wrong most often when it is taken from a profile alone.

| Working on… | Skill |
|---|---|
| Python | `writing-python` |
| browser JavaScript | `writing-javascript` |
| CSS | `writing-css` |
| any `--selftest` case, guard or lint | `no-silent-pass` |
| splitting or sharing `ui/` parts | `refactoring-the-assembled-ui` |
| a sync/batch job against a remote API | `running-resumable-sync-jobs` |
| anything depending on an external API's behaviour | `verifying-external-behavior` |
| a check that passes locally and fails in CI | `reproducing-ci-locally` |
| making anything faster, or deferring a slow thing | `choosing-what-to-optimize` |
| any comment, docstring, document, check, guard, brief, or fix for a recorded fault | `before-you-claim` |

`grill-me` is deliberately not a row. The column is *what you are working on*, and that is
not what selects it: the user asks to be interviewed about a plan before it is written, and
the skill states nothing about this repo. It composes with a row above rather than replacing
one — the interview settles what to build, the row settles how to write it.

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

**Substring assertions guard the assembled output**, and they live in `tests/` —
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
part is for. Assets of 400+ lines also owe one section marker per 400 lines; nothing enforces
that for assets, so it is the author to keep.

## Tests

**`tools/verify.sh` runs every gate below in one command** — `--fast` for iteration
(narrower browser sweeps, prints what it skipped, never a gate), `--release` to add
the checks a version bump owes. Prefer it: running these by hand cost two red CI
runs in one day, both from a forgotten step rather than a broken change.

`sh tools/verify.sh --list` prints every slice, its tier and the steps it runs, read off
the same calls a run makes; that list is the gate set, and the block below is the
commands a change most often reruns by hand, not a second copy of it:

```bash
python3 tools/sweep-selftests.py           # tests/, tools/ AND .claude/hooks/, each in a scratch dir; hooks/ and scripts/ answer for a suite in tests/
python3 tools/sweep-selftests.py --selftest
python3 tools/sweep-selftests.py --encoding cp1252   # again, a legacy code page for stdio AND a non-UTF-8 locale only where the pin is Windows-shaped; prints which half ran; --fast skips it
python3 tools/sweep-selftests.py --spaced            # again, TMPDIR spaced + symlinked; posix only; --fast skips it
python3 tools/gate-parity.py               # ci.yml's slices against verify.sh --list, SECURITY.md's fail modes, job time bounds
python3 tools/bench-hooks.py --gate        # the hook import budget; no flag prints the measurement
python3 tools/measure-context.py --gate    # what each pipeline entry makes the main loop read, vs its ceiling
python3 tools/check-git-pipeline.py        # the write half, against a REAL git repo
npx vitest run                             # the JavaScript unit tests
ruff check plugins/audit tools tests
vermin -t=3.8- --no-tips --violations plugins/audit/scripts plugins/audit/hooks tests tools/lints
python3 tools/check-rendered-artifacts.py  # vs a fresh render AND vs HEAD; verify.sh's
                                           # plain run passes --before-commit (the render
                                           # only), and --release adds --against-commit
python3 tools/check-committed-pii.py       # ...and that none of them names a machine
python3 tools/check-example-ledgers.py     # ...and that no committed evidence row
                                           # records a verdict the runner cannot
                                           # produce, and that every commit
                                           # a committed manifest names resolves -
                                           # refusing on a clone too shallow to ask
python3 tools/demo/gen-demo-usage.py \
    examples/acme-store/audit-plan.json --out-dir <tmp>   # the committed ledger is
                                           # DERIVED, so it is diffed against a fresh
                                           # run; verify.sh does this for you
python3 tools/capture-demo-gif.py --check  # the demo GIF's preconditions
node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html
node tools/capture-screenshots.mjs --check
```

**The sweep is one runner, and CI runs the same one.** It used to be a serial `for` loop
written out twice — here and inlined in `ci.yml` — and the two copies checked different
things: the local one asserted the exit code alone, so a file that exited 0 having asserted
nothing was green locally and red in CI. `tools/sweep-selftests.py` is the single copy, it
holds the union of both rules, and it runs the tree across all cores but two — every core
when `CI=true`, since nobody is typing on a runner. **CI does not run a leg as one job:** each
leg is a matrix cell split by `--shard I/N`, the parts balanced by the per-file costs in
`.github/sweep-costs.json` (re-record them with `--record-costs`) and their union pinned to the
whole tree by the runner's own cases, while `gate-parity.py`'s `shard_matrix_drift()` holds the
matrix to running every part. Locally a leg still runs whole. **The workers are one budget of
slots, and what it schedules is a block, not a suite:** a staged suite (its `__main__` is
`_harness.staged_main`) has each block of its `STAGES` table run as a job of its own on one slot,
then one replay that prints the suite's whole run, so the sweep's workers and a suite's blocks
never add up past the machine. That model — the submission order, a block's timeout, and the
fallback for a table the sweep cannot read — is stated once, in the `blocks, not suites` comment
above `work_items()` in `tools/sweep-selftests.py`; read it there rather than here. Each job's
timeout is a hang detector calibrated from the same table — the floor, or a multiple of the
file's recorded seconds when that is longer — and reaches the child as `SWEEP_FILE_TIMEOUT`. The loud form
prints every file's seconds, so a CI log can be recorded with `--costs-from-log`. Re-derive the
wall clock rather than trusting a figure written here; `--jobs 1` gives the old serial shape for
a bisect.

**And every child runs in scratch directories it is expected to leave unchanged.** Each
child has these pointed away from your machine: its cwd and `TMPDIR` at one scratch
directory, its HOME at a second — under every name a home lookup reads, not just `HOME` —
`PYTHONPYCACHEPREFIX` at a third, so a bytecode cache the interpreter writes under the
HOME it was handed cannot convict the suite that triggered it, and `GIT_CONFIG_GLOBAL` at a
runner-owned git config in a fourth, for the one git the switches below cannot otherwise
reach. The rest of the environment is
filtered rather than pointed anywhere: the Claude session's variables — every `CLAUDE_` name,
plus `CLAUDECODE` and `AUDIT_LOCK_TOKENS` — are dropped, and so is any identity the caller
exports (`GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `EMAIL`); git runs with
`GIT_CONFIG_NOSYSTEM` set and `user.useConfigOnly` refusing a guessed identity. No branch and no
identity are supplied in their place, so a suite leaning on the host's git fails here the way it
fails on a bare runner; that is what let a local sweep stay green over suites CI's ubuntu runner
turned red. The same `GIT_CONFIG_COUNT` set turns `maintenance.auto` and `gc.auto` off for
every git a suite starts, through a fixture prefix or bare, but one: git's local transport
drops that protocol (and any `-c`) before it starts receive-pack, so a push to a local path
ends in a detached housekeeping run on the receiving side. The `GIT_CONFIG_GLOBAL` file
carries `receive.autogc` off — only that key, so a suite that takes the pairs out to measure
its own prefix still sees a spawn — and does reach receive-pack, so no git a suite
starts leaves a detached housekeeping run working in a fixture it is about to read or delete —
unless the suite points `GIT_CONFIG_GLOBAL` elsewhere for its own git, which then reads what
the suite chose. The file sits outside every watched directory and is checked back like their
planted files, because a suite's `git config --global` now writes there. The caller's own pairs
in that protocol are dropped first, so the runner's set is the whole of it. **The working directory and
the home directory are the watched pair**, each holding one file the suite did not put
there, and a suite is red if anything was added to either — or, the destructive half a
strays-only check would call spotless, if that planted file was deleted or rewritten.
Findings name which of the two channels they came from, and the three outcomes are worded
apart because they are three different bugs. Suites here leaked git fixtures into whatever
directory `TMPDIR` named for a long time and no gate could see it, because `TMPDIR` is
normally the system temp and a stray fixture there is somebody else's problem; the home
channel is the one that caught a suite shelling out to the real `az`, which writes into the
operator's home directory on any machine that has it — CI's ubuntu runner included. A suite
that needs scratch space builds it under `tempfile.mkdtemp()` and removes it in `finally`.

**The checkout's own `.claude/` is watched as well**, because a suite whose scratch sits under
a checkout resolves that checkout as its project and writes its restore points there with
the watched pair spotless. Only the names the live session itself writes under `state/` are
left out, each with its writer, and a finding is still told when the suite also failed or
timed out. The prevention half comes first: the runner refuses to start when its temp
directory has a `.git` above it. `CONTRIBUTING.md` carries the attribution rule.

**And this paragraph is not checked against the runner.** A lint once compared the runner's own
constants with the documents that describe the isolation — this one, `CONTRIBUTING.md`, and the
docstring beside `_harness.fixture_root()` — and was retired with the other lints whose measured
catch was nothing, so a family added to the runner owes its mention in each of them to whoever
adds it. Print the runner's constants rather than trusting this paragraph.

**`tools/verify.sh` is the one description of the gate set, and `gate-parity.py` holds the
workflow to it.** The gate set used to be described by hand in the runner,
`.github/workflows/ci.yml`, `CONTRIBUTING.md` and this list, and the copies drifted in both
directions at once (the sweep, `vitest`, `vermin`'s directory list). Now every CI job is setup
plus one `tools/verify.sh --only <slices>` call and the documents point at `--list`, so there
are no copies left to compare. What `gate-parity.py` checks is what the workflow says *about*
the slices: every slice a job names is one `verify.sh --list` prints, every per-run slice has
a job outside the release tier, and a sharded slice's matrix runs every part on every runner.
It also holds rules that are not parity questions: every check `--affected` names is one the
runner can dispatch, `SECURITY.md`'s fail-mode table is the one `hooks.json` registers, every
CI job carries a time bound backed by a measured `longest` line, and every reason-carrying
exemption table names who audits it. It no longer compares documents against the runner.
Its docstring is the current statement of those rules; `python3 tools/gate-parity.py --list`
prints only the slices and the jobs running them, so run it for that half and read the
docstring for the rest, rather than trusting this paragraph.

**Every suite lives in `tests/`, and a shipped module answers no `--selftest` at all**
(`73042a1` moved the cases, `c403486b` deleted the stubs that pointed at them — count the
covered modules with
`python3 -c "import sys;sys.path.insert(0,'tools/lints');import _output_lints as L;print(len(L.selftest_coverage()['covered']))"`).
`_output_lints.selftest_coverage()` asks one question of every module under `scripts/`,
`hooks/`, `tools/lints/` and `tools/demo/`, and of `tools/bench-report.py` and
`tools/_usage_bench.py`: is there a `tests/test_<name>.py` for it. `covered` is the clean class
and `exempt` a debt with its reason in `COVERAGE_EXEMPT`; `uncovered`, `stale_exempt` (an
exemption naming no module, or one that has a suite after all), `orphans` (a `tests/test_*.py` naming nothing that exists) and `collisions`
(two modules wanting one test name) are defects, and the sweep reports each by name and refuses
a classification that looked at nothing. The sweep no longer walks `hooks/` or `scripts/` —
there is nothing there to run — and a `.py` reappearing under the retired
`plugins/audit/tests/` is red, because it would ship in every install and run nowhere.

`CONTRIBUTING.md` has the manifest and plugin-structure checks that complete the pre-PR set,
and the reasoning for the gates; `verify.sh --list` is the list. The browser gates at the
bottom of the block above are the only thing that can prove the report actually paints and
stays interactive — a selftest can only assert what the CSS *says*.

A check that has only ever been seen passing may be asserting nothing. Break the thing it guards
and confirm it goes red before trusting it — `tools/redfirst.sh` does that for one check, and

```bash
python3 tools/prove-gates.py          # --list to see the table without running it
```

does it for every load-bearing lint at once, in both directions — the case that must fail
when the guarded thing breaks, and the allow case that must fail when the guard is weakened until
it over-fires. It never writes the checkout: each row mutates and restores a **worker tree** — a
detached `git worktree` at HEAD carrying the checkout's uncommitted edits and untracked files,
under a scratch directory outside every checkout — and the rows run concurrently on the sweep's
core count, reported in the table's order. The trees are removed when the run ends, or by the
next run when one was killed. It is still minutes rather than seconds and is not a per-commit gate. Its
tables are derived from the files that hold a lint, so a lint added without a row fails the
sweep — which is how the annotation half of `house_style_violations()` was found unenforced
after the document had claimed it for a long time.

**Derived two ways, because a name is a convention.** A lint whose name ends in one of the
reporting shapes is reached by that shape; one whose name says nothing is reached by what it
*does* — no required argument, and a walk of the tree through one of the shared walks. That
second arm exists because a lint with a row in neither table was invisible to the coverage rule
itself: a check it never derives can never be reported missing, so the table went on looking
complete. A walk that is not a verdict declares itself in `NOT_A_GATE`, with a reason that is
checked in both directions.

## Releasing

One release is **one commit** that bumps `plugin.json`, finalizes the `CHANGELOG.md` section, and
carries the annotated `v<version>` tag. Push only after CI is green **on that commit**. A pushed
tag is never moved or deleted — fix forward.

**A release does not go out over an open bug, and that is enforced rather than remembered.**
`.claude/hooks/guard-release.py` refuses the publishing commands — creating a tag, pushing one,
`gh release create` — while the plan carries an open bug, and `verify.sh --release` asks the same
question early. Ordinary work is untouched: `git push origin main` is not a release, and a guard
that fired on it would be routed around inside a day.

**A merged phase the plan's own evidence still calls provisional holds a release the same way,
beside the open bugs rather than folded into that one list.** A phase is provisional when no
full-scope run this repository has recorded — measured, clean, verbatim against the declared
gate — has yet been taken with a head containing the commit that phase merged into; `/audit:review
<phase> --full` (or the pre-push/CI step that runs the same command) is what settles one. A plan
naming no third place (`meta.fullGate` absent) has nothing provisional to ask about, and the guard
behaves exactly as it did before that question existed. The tree it judges comes from the
plugin's own `_config.tree_for`, asked about the release command's own working directory, so a
release typed from a linked worktree answers to that worktree's plan rather than to wherever
`CLAUDE_PROJECT_DIR` happened to point.

The way past it is **yours alone**: type `#release-with-bugs` in your own message, which arms a
single-use, one-hour slot through `.claude/hooks/arm-release-bypass.py` and prints which bugs and
which provisional phases you are shipping over, through the guard's own reading of both. Nothing
the model writes can arm it — that is why the switch reads the prompt and not the command.

This exists because it already failed: a bug reported *during* the v2.0.1 release was written into
a scratch plan file no gate reads, and the release went out. Twenty-one gates were green and every
one was honest — none of them asked about the tracker. So **a bug belongs in the manifest**
(`/audit:bug`), never in a session note; a bug the tooling cannot see is a bug that stops nothing.
`open` there means the plugin's own *effective* status (`_manifest_io.effective_bug_status`), so a
bug whose fix task is `done` is already closed and blocks nothing.

A Release is created **for** a tag, so it comes after the push. The tag is a git object;
the Release is the page a reader lands on, and the README's `curl` pins make the tag a
published claim — the Releases page had drifted to presenting a long-superseded version
as Latest while the README pinned a far newer tag. `CONTRIBUTING.md` carries the
step; what belongs here is that it is now checked, that the check lives in the **release**
set alone because it asks a remote, and that it refuses rather than passing when it cannot
ask:

```bash
python3 tools/check-release-published.py   # the newest published tag has a Release, and Latest names it
python3 tools/check-example-pins.py        # every plugin script an example calls exists at the tag it pins
```

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
skill, **documentation split by audience** (which is why `QUICKSTART.md` is a page and not a
section, and why a first-run step goes there and nowhere else). Read it before re-opening one of
them, and if a trigger has genuinely fired, say which.

**Two of those entries were reversed with their trigger still green**, and for the same reason
both times: the trigger was a threshold on something incidental — a deprecation that might never
come, a file count — while the cost being paid was discoverability and navigability. So a green
trigger is not evidence that a decision is still right. When you propose one, phrase it as a
property of the system that *is* the cost, not as a proxy you can count.

Bugs found along the way go into the plan's Faults section when one is active, rather than being
fixed inline in an unrelated change.
