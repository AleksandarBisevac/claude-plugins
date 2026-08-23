# Contributing

**Read in this order.** The reference documents here are long, and a second
contributor who opens the wrong one first spends an hour learning the architecture
before learning how to run the tests.

1. **This file** — the rulebook. The gates you must run before a PR, the hard rules
   that are enforced by lints rather than by review, and the Decision record at the
   end: settled questions, each with the trigger that would reopen it.
2. **`CLAUDE.md`** — the short version of what you must know *before* an edit. It
   restates no procedure from here on purpose.
3. **`PLUGIN-BUILD-GUIDE.md`** — the architecture, file by file. Reach for it when you
   need to know what a specific module does, not to get oriented.
4. **The skill for the language you are about to write** — the table is in
   `CLAUDE.md`. Each states the house dialect and the anti-patterns that have actually
   bitten here.

Writing a change a *user* will see? [COMPATIBILITY.md](COMPATIBILITY.md) is the
contract over the manifest and the config file they own, and
[QUICKSTART.md](QUICKSTART.md) is the one page a new user reads — a change that adds
a step to first-run belongs there and nowhere else.

## Dev setup

```bash
git clone https://github.com/AleksandarBisevac/claude-plugins
cd claude-plugins
```

Try your working copy in a throwaway repo (Claude Code session):

```
/plugin marketplace add /abs/path/to/claude-plugins
/plugin install audit@quality-gates
/reload-plugins        # after edits to the plugin
```

Note: `guard-edits` has a dev-mode exception — self-edit protection is off when
the plugin checkout IS the working repo, so you can develop the plugin under
its own hooks.

## Tests (run before every PR)

**One command runs all of it:**

```bash
tools/verify.sh                 # every gate CI runs
tools/verify.sh --fast          # iteration mode: narrower browser sweeps, NOT a gate
tools/verify.sh --release       # the full set, plus what a version bump owes
```

It exists because typing these by hand cost two red CI runs in one day: once by
skipping the `ajv` step, and once by bumping the version AFTER the sweep was green
— a bump stales the README's runnable `curl` pins and the rendered artifacts, both
of which are checked by name. `--release` is the guard for exactly that, and every
step runs even after an earlier one fails, so the summary is the whole truth rather
than the first thing that broke.

`--fast` narrows the width ladder and skips the two systematic accessibility
sweeps. It prints what it skipped and refuses to say the preconditions hold, and it
is never what CI runs.

The individual commands stay documented below, because they are the definition and
the script is only a caller:

```bash
# every selftest suite — stdlib only, no deps. Swept, never enumerated: a list
# drifted three ways once and CI silently stopped running one suite entirely.
#
# ONE RUNNER, and CI runs the same one. This was a `find` loop written out here, a
# second copy of it in ci.yml that checked MORE (the `N/M cases passed` contract and
# the `--covered` skip) and a third in verify.sh that checked LESS (the exit code
# alone) — so a file that exited 0 having asserted nothing was green locally and red
# in CI. The runner holds the union of all three rules and walks hooks/, scripts/,
# tests/ AND tools/ recursively through `_output.py_files`, so a file added one
# directory down is swept without anyone editing a glob.
#
# IT SWEEPS tests/ TOO, which is why the second `find` loop that used to sit here is
# gone: it re-ran the migrated suites the runner had just run. A migrated file exits 0
# printing where its cases went, and the runner requires that it NOT print the
# contract — the net under `selftest_coverage()`'s string-literal blind spot.
#
# `--jobs 1` gives the old serial shape for a bisect.
python3 tools/sweep-selftests.py

# ...and the runner's OWN cases, read directly rather than through itself: a `grade()`
# that always answered "ok" would report its own suite as passing while hiding it.
python3 tools/sweep-selftests.py --selftest

# the meta-gate: this list, verify.sh and ci.yml describe one gate set, and they had
# drifted in both directions at once before anything compared them. All THREE are
# compared now, and this document was the last one added — while claiming to be the
# definition, it carried seven of the thirteen gates. A gate named by one side and
# not another fails by name; a legitimate absence needs a row in ABSENT_BY_DESIGN
# with a reason, and a row that no longer describes the system fails too.
python3 tools/gate-parity.py

# the hook import budget. A hook runs on every matching tool call - seven of them on
# one edit - so its module-level imports are paid over and over. This diffs
# sys.modules after loading each hook against a measured floor and fails by name on
# a newcomer. The wall clock is NOT gated on purpose: it swings between repeats by
# more than a deferred import is worth. `tools/bench-hooks.py` with no flag prints
# that measurement for a human deciding whether an optimisation is worth doing.
python3 tools/bench-hooks.py --gate

# the JavaScript unit tests. They ran only in CI for a long time, so a change under
# scripts/ui/ could reach a push with none of the suites covering it having run.
npx vitest run

# manifests: structural validator + JSON Schema
python3 plugins/audit/scripts/manifest/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
python3 plugins/audit/scripts/manifest/validate-manifest.py docs/audit/audit-plan.json
npx --yes ajv-cli validate --spec=draft2020 -s plugins/audit/schema/audit-plan.schema.json \
  -d plugins/audit/templates/audit-plan.starter.json

# plugin/marketplace structure
claude plugin validate .
claude plugin validate plugins/audit

# the dialect and the 3.8 floor. `ruff` selects E9+F only (pyproject.toml); the AST
# lint in `_output.house_style_violations()` is what enforces the bans vermin cannot
# see — annotations, walrus, `typing`, `dataclasses`, `from __future__`.
ruff check plugins/audit tools
vermin -t=3.8- --no-tips --violations plugins/audit/scripts plugins/audit/hooks plugins/audit/tests

# the rendered artifacts, byte for byte against a fresh render, and the demo GIF's
# preconditions — the plan gate still refusing an unplanned edit, in its own words.
python3 tools/check-rendered-artifacts.py
python3 tools/capture-demo-gif.py --check

# the browser gates. NOTHING ELSE can prove the report paints and stays interactive,
# or that the panel's controls do what their labels say: a selftest asserts what the
# CSS SAYS. The panel leg is the long one.
node tools/check-report-interactive.mjs examples/acme-store/acme-store-audit.html
node tools/capture-screenshots.mjs --check
```

CI (`.github/workflows/ci.yml`) runs the selftest suite on ubuntu + windows —
the windows leg proves the `python3` → `python` → `py` interpreter fallback
(the manifest-validation and plugin-validate jobs run on ubuntu).

## Hard rules

- **Stdlib only** in hooks/scripts — a guard that needs `pip install` is a guard
  that is off on most machines. `py-launch.sh` stays POSIX-sh builtins-only.
- **Schema changes are additive** (or remove never-read optional fields). An
  existing manifest must keep validating across versions; prove it with a
  legacy-fields fixture when in doubt. This rule predates
  [COMPATIBILITY.md](COMPATIBILITY.md) and is now half of what that document
  promises — so a change that would break it is not a judgement call any more, it is
  a major release.
- **New behavior ⇒ new selftest cases.** Selftests are the plugin's test suite;
  every decision-core change lands with cases that pin it. **Every `.py` under
  `hooks/` and `scripts/` must carry a `--selftest`** — CI globs the directories
  rather than listing them, and fails a file that has none. Adding a file and
  remembering to register it were once two separate acts, and one suite went
  unrun for two releases as a result.
- **Every `.py` under `hooks/` and `scripts/` is scanned wherever it sits.** The
  selftest sweeps — the one above and CI's two — use `find`, and
  `_output.py_files()` is the single recursive walk behind both of `_output.py`'s
  AST lints and every scanner in `_deps.py`. A rule stood here requiring `.py` to
  stay flat, one directory deep, and its only reason was that all three of those
  scanners were non-recursive: a file dropped into a subdirectory silently
  stopped being tested. The hazard was the **silence**, not the subdirectory, and
  it is gone — so the constraint is gone with it, and a `.py` one level down is
  linted, layer-checked and selftested exactly like any other. What the recursion
  costs is one rule, enforced rather than requested: a `.py` **basename must be
  unique across the whole of `scripts/`**, because `import` and `_loader` both
  resolve by basename, so two files sharing one would be a single node in the
  layer graph wearing both files' edges — `_deps.layer_violations()` fails the
  build by name on it. Removing the constraint is not the same as wanting
  folders; whether `scripts/` should grow any is still the open question the
  Decision record below records. `scripts/ui/` remains non-Python regardless: it
  holds ordered parts of one assembled artifact rather than standalone files, and
  `_panel_ui.py` and `_report_ui.py` each carry a selftest pinning it as
  containing no `.py`.
- **The bootstrap that makes a subdirectory actually runnable.** `sys.path[0]` is
  the running script's own directory, so a file at `scripts/<area>/<name>.py`
  executed directly — which is exactly what CI does — used to die on
  `from _output import safe_stdio` before anything ran. Every `.py` under
  `scripts/` except `_output.py` now carries `_output.PATH_PREAMBLE` byte for
  byte: it walks UP to the directory holding `_output.py` (no `dirname(dirname(`,
  no magic constant, a named `ImportError` at the filesystem root), then calls
  `_output.install_path()`, which puts `scripts/` **and every subdirectory of it
  holding a `.py`** on the path — the root alone is not enough, because ~81
  module-level sibling imports need the directory the IMPORTED file sits in.
  `path_preamble_violations()` counts occurrences (a doubled preamble is as wrong
  as a missing one) and AST-checks that `install_path()` runs above the first
  sibling import. `depth_sensitive_paths()` then forbids any other read of
  `__file__` under `scripts/`, so the seventeen sites that used to derive a parent
  directory from their own location cannot come back. The directories to reach for
  instead are `_output.SCRIPTS_DIR` / `PLUGIN_ROOT` / `HOOKS_DIR` / `TESTS_DIR` /
  `REPO_ROOT`. `hooks/` is outside all of it — hooks may import nothing from
  `scripts/`, so they resolve a scripts file by basename through
  `hooks/_config.find_script()`, and `tests/test__config.py` pins that third copy
  against `_output.script_files()` by reading both rather than merging them.
- **One concern, one home, and the registry is what enforces it.**
  `_deps.SHARED_CONCERNS` names each shared concern, its single home under
  `ui/shared/` (or `panel/core.js` when only one surface reads it), the text that
  betrays a second implementation, and how many sites are allowed outside that
  home. `shared_concern_violations()` fails the build on growth. It is a **cap,
  never an equality** — that difference is the whole lesson of the three
  save/discard counts retired in `9f73b22`, which required the duplication to stay
  and so forbade the helper that would have removed it. A freed allowance is
  reported by `shared_concern_slack()` rather than failed, so improving the code
  can never turn this red. Comments are stripped before counting: three checks
  here have already been tripped by prose, and a registry that counted comments
  would punish documenting the rule.
  A **registry rather than a similarity score, measured rather than preferred**: a
  normalising token scanner over the same files reported 3,732 cross-file repeat
  groups, and 725 after preserving the shared vocabulary, topped by this
  codebase's own `el()` idiom. A gate at that noise level is one people learn to
  ignore, so similarity is at most a scout for rows to add here.
- **Never reach a file by absolute path.** A module specifier, or the first
  argument of a read/write call, must be relative — an absolute one encodes one
  machine's layout into a repository other people check out.
  `_refs.absolute_reach_violations()` fails the build on it, and the rule is
  deliberately about SYNTACTIC POSITION rather than about the literal: an absolute
  path is legitimate as *data* (`validate_registry` is handed
  `{"root": "/Users/me/proj"}` precisely to check that it warns) and as a *system*
  location (the demo tool's `/usr/share/fonts` fallbacks), and neither is a reach.
  Its stated limit is that a reach through a variable is invisible, so it
  under-reports rather than over-reports. Python already had the stronger half of
  this: `depth_sensitive_paths()` lets no `.py` under `scripts/` read `__file__`
  outside the pinned preamble, so no module may derive its own location at all.
  Throwaway probes are where this rule actually gets broken, because a script in a
  scratch directory cannot reach the repo relatively — run those as
  `node --input-type=module -e '…'` from the repo root, where a relative specifier
  resolves against the working directory.
- **Fail-open for advisory paths, fail-loud for guards** — see `SECURITY.md`
  for the table; keep it true.
- Every command that mutates the manifest must revalidate
  (`scripts/manifest/validate-manifest.py`, exit codes 0/1/2).
- **Every claim in output carries the basis that makes it true — and when the
  basis is missing, that is the thing to say.** The routing advisory stays
  silent without enough in-repo evidence; the projection is a range, suppressed
  below a sample gate; the ready list states the count it folded. The worked
  example is cost: a dollar figure is a claim, and its basis is the rate table
  it was priced from, so all five surfaces that render one — HTML report,
  Markdown twin, `/audit:usage`, `/audit:status`, the panel's Usage tab —
  print `rates as of <date>`, or `rates undated (set usage.pricingAsOf)`.
  - **Never fall back to a default to fill the gap.** `usage_cfg()` merges a
    default `pricingAsOf`, so a fallback would nearly always render a plausible
    date the project never chose. That is the argument against it. Where the
    merged value is all that is available (the panel), the server reports
    *whether the project declared it* as a separate fact rather than letting the
    client mistake a default for a declaration.
  - **A basis with no claim is noise** — the same rule backwards. All five stay
    silent under `showCost: false` and when there is no spend to price. The
    first version of this shipped a bug of exactly that kind, caught by an
    existing case: an empty usage block announced undated rates for costs that
    were never on screen.
  - **Consulted surfaces carry the basis; pushed ones carry the minimum.**
    `meter-usage.py`'s session-end line is deliberately exempt. You open a
    report and run a command; a hook line arrives uninvited and already hedged,
    and growing it is how it becomes the message people learn to skip.
  - A new surface that renders a number someone acts on inherits all of this,
    and the pattern to copy is `render-report._usage_context`.

### Adding a new script

Checklist for a new `.py` under `hooks/` or `scripts/`:

- **Name it by role.** An importable helper other files import from takes an
  underscore prefix (`_deps.py`, `_output.py`); an entry point invoked
  directly (by a hook, a command, or CI) takes a hyphenated name
  (`validate-manifest.py`).
- **Module docstring** stating why the file exists, not just what it does.
- **`--selftest`** that prints the `N/M cases passed` contract — CI sweeps every
  `.py` under `hooks/` and `scripts/`, at any depth, and fails one that has none.
- **`safe_stdio()` first in `__main__`**, before any other statement — this
  is AST-enforced by `_output.py`, not a convention.
- **A layer assignment in `_deps.LAYERS`** — the import-graph lint fails an
  unplaced file by name.
- **A tree line and a section in `PLUGIN-BUILD-GUIDE.md`** — the enumeration
  lint fails a missing one.

Most of this list is enforced by lints, not by review: the checklist is the
map, the lints are the territory.

## Release rule

One release = **one commit** that:
1. bumps `plugins/audit/.claude-plugin/plugin.json` `version`,
2. finalizes the `CHANGELOG.md` section for that version,
3. carries the annotated tag `v<version>` on that same commit.

If the release changed the report, re-render the example with
**`examples/report.sh`** rather than calling `render-report.py` directly: CI
requires `docs/index.html` to be a byte copy of the committed example report,
and the script makes that copy for you. The live demo went a month stale exactly
once, by re-rendering and forgetting it.

Push with `git push origin main --follow-tags` **only after CI is green** on the
commit. Verify that commit specifically — `gh workflow run ci.yml --ref main`
addresses a run by ref, so a commit whose push never produced one can still be
checked without an empty commit (which changes the sha you would tag).

**A tag that has been pushed is never moved or deleted** — the `v0.2.0` tag/main
mismatch is documented in the changelog and fixed forward, not rewritten. The
rule is about what other people may already have fetched, so it starts at the
push, not at `git tag`. A local tag on a commit CI then failed is not a release
that went wrong; it is a release that never happened, and deleting it is the
honest record. That is what became of `v0.20.0`: tagged locally, red on CI,
deleted unpushed, and the work re-cut as v0.21.0 once it also carried two
features the patch number would have concealed. There is no v0.20.0 tag and
never was one.

For a multi-plugin future, `claude plugin tag` (official `{name}--v{version}`
convention, cross-checks plugin.json ↔ marketplace entry) is the migration path.

## Decision record

### commands/ vs skills/ (evaluated 2026-07, v0.4.0): stay on `commands/`

Claude Code merged custom commands into skills and recommends `skills/<name>/SKILL.md`
for new plugins. We evaluated migrating and decided **NO-GO for now**:

- The invocation surface (`/audit`, `/audit:init`, `/audit:task`, `/audit:bug`)
  is the product's muscle memory; `commands/` remains fully supported.
- The skill-only frontmatter powers (`context`, `agent`, `once`,
  `disallowed-tools`) buy these four commands nothing today.
- Dual-shipping both layouts risks double registration and split docs.

**Revisit trigger:** when the plugin ships `agents/` (planned v0.5+/v0.6 —
skills can pin an `agent`), or if Claude Code deprecates `commands/`.

**Re-evaluated at v0.6.0 (agents/ shipped): still NO-GO.** The agents are
spawned by the commands via `subagent_type` — nothing about the invocation
surface changed, so the original rationale holds unchanged. Next trigger:
`commands/` deprecation only.

**Amended at v0.22.0: the trigger was watching the wrong thing, and both
layouts now ship.** Every revisit above asked "is `commands/` going away yet" —
a risk that may never arrive. The actual cost was already being paid: skills
**auto-trigger on what someone types**, and commands do not. Someone who says
"audit this codebase" gets nothing unless they already know to type
`/audit:init`. That is not a deprecation risk, it is a discoverability loss,
present in every version since v0.4.0, and a trigger set to "deprecation only"
cannot fire on it. Watching for the wrong signal is not the same as concluding
there is no signal — the NO-GO was defensible each time and still missed this,
because it only ever answered the question it was asked.

So the answer is neither NO-GO nor migrate: **keep every command and add thin
skills beside them.** `skills/audit-codebase` and `skills/audit-spend` carry a
triggering description and a routing table, and nothing else. They restate no
procedure — they name the command file to read — because two copies of a
procedure is one copy and one lie. The muscle memory keeps working, the natural
phrasing now lands somewhere, and the migration this ADR twice declined is still
declined.

The risk this introduces is over-triggering: a skill that fires on "review this
code" would make the plugin worse than silence, which is why `audit-codebase`
carries an explicit **do not use this for** section pointing one-shot diff review
back at `/review`. That is the same rule the routing advisory and the cost
projection already follow — say nothing rather than something unfounded.

**Next trigger:** evidence about the descriptions themselves — a skill firing on
work it should not touch, or the natural phrasing still not reaching it. Both are
observable in a transcript, which is what makes this trigger able to fire at all.

### Plugin name (evaluated 2026-08-07, before directory submission): keep `audit`

Asked deliberately at the last cheap moment — the community catalog pins an approved
plugin to a commit SHA, so after listing the name is a public install id and renaming
costs every user a reinstall. Right now it costs nothing but the edit.

Measured rather than assumed: the catalog holds **2287 plugins**, `audit` is **not
taken**, and 19 names contain "audit" (`audit-project` and `audit-suite` are the
alphabetical neighbours). `displayName` exists in the entry schema but **2 of 2287**
use it and neither differs from `name` — so the listing name IS the install name, and
there is no separate display lever. `category` is used by 152 entries and `tags` by
**one**, which means discovery there is name plus description, not taxonomy.

Kept anyway, in order of weight:

1. **The prefix is typed daily; the name is read once.** `/audit:run P2.1` against
   `/audit-gates:run P2.1` — every candidate that is more distinctive is also longer,
   and it charges that length on every invocation forever.
2. **The two-level naming is already right.** The marketplace is `quality-gates` — the
   thesis. The plugin is `audit` — the job. A gate-flavoured prefix would be wrong for
   half the surface: `/gate:usage`, `/gate:report` and `/gate:init` are not gates.
3. **`audit` is accurate**, and the names that would cut through 2287 entries buy
   memorability with precision. This repo derives names from what a thing does.

The discoverability problem is real and the answer to it is the **description**, which
is where a reader actually decides. Not the name.

**Revisit trigger:** someone reports they could not find the plugin while searching for
what it does, or a name collision appears in the catalog. Both are observable; "the name
feels generic" is not, and is not a reason to spend a rename.

### In-product help (decided 2026-08-10, v0.31.0): a static endpoint and an agent you invoke, never an auto-triggering skill

Help ships in two halves, and the split is the decision. `GET /api/help` extracts every field
description from the two schemas at request time and adds four concept pages derived from the
code that executes each rule — it costs nothing to ask and nothing to answer. `agents/guide.md`
answers the rest conversationally, from the plugin's own documents, with a citation per claim.

A third option was available and rejected: a skill, which would auto-trigger on "how does the
audit plugin…" and quietly bill a model for questions the endpoint answers for free. This plugin
already ships two thin skills, and both exist because a command cannot be reached by describing
what you want; help has no such problem, because the panel is already open in front of you. **You
choose when a question is worth a model.**

The guide is an agent rather than a command for the same reason `audit-explorer` is: its tool
list (`Read`/`Grep`/`Glob`) makes read-only a mechanical fact rather than an instruction. It is
also, by being in `agents/`, automatically part of the capability policy's REQUIRED set — a
deny-all policy cannot switch off the thing that explains the policy.

**Revisit trigger:** the drawer ships (panel c8) and people still ask the model things the drawer
shows — that would mean the static half is not being found, which is a UI problem, not an
argument for a skill.

### Plugin evals (evaluated 2026-07, v0.6.0): deferred — feature is early access

`claude plugin eval` (evals/**/case.yaml + graders) is the right tool for
testing the COMMAND PROSE (the orchestrator behavior CI cannot reach), but as
of v0.6.0 it prints "currently in early access" and `eval init` does not
scaffold — the case schema is not public. Adopt as soon as it opens up:
priority cases are `/audit:status` on a missing manifest, `run` guards on a
done task, and the `#no-plan` bypass round-trip.

**Re-checked 2026-08-19: still early access, still deferred.** `--help` is now
complete — it documents `case.yaml`, `prompt.md + graders/*.md`, `--ablation`,
`--threshold`, an HTML report — which reads exactly like a shipped feature.
Running it does not: both `claude plugin eval .` and `claude plugin eval init
--bare <name>` answer `` `plugin eval` is currently in early access `` and write
nothing. There is no flag, env var or setting that opens it.

Recorded because the help output nearly closed this entry on its own: **a
complete `--help` is not evidence that a command runs**, and that is the same
mistake as a green check that asserted nothing. Verify by invoking, not by
reading.

**What the gap cost in the meantime, and what was done instead.** The untested
half is real and it produced a defect: `/audit:sync` wrote work items that were
mechanically correct and did not conform to a client board's standard (**U4** in
the plan). The answer was not to wait for evals but to **move the rule out of the
prose**: `scripts/manifest/_ado_conventions.py` grades an item against the board's
conventions in Python, with cases, and the prose's only job is to call it. That
narrows the untestable surface to one question — *did the prose call it* — which
`/audit:doctor` can answer after the fact. Prefer that shape wherever it fits: a
rule a selftest can reach beats a rule an eval would have to observe.

### ~~Folders under scripts/ declined (2026-08-10): stay flat~~ — REVERSED (2026-08-18, v0.40.0)

`scripts/` is now eight domain directories — `config/`, `demo/`, `governance/`,
`manifest/`, `panel/`, `report/`, `status/`, `usage/` — plus `ui/` and seven
cross-cutting modules at the root. The original text is kept below, struck where
it stopped being true, because a decision record that quietly rewrites itself
teaches nothing.

**The trigger never fired, and it still has not.** It said "`scripts/` exceeds 40
`.py` files". There were 30 the day this was written, 32 at `v0.39.0`, and **38
today** — the reversal happened at no point on that curve. So this is not a
trigger firing; it is the second ADR in this file to discover that **its trigger
was watching a proxy rather than the cost.**

That makes it the same failure as the `commands/` vs `skills/` entry above, which
spent three revisits asking "is `commands/` deprecated yet" while the real cost —
discoverability — was being paid the whole time. Here the proxy was a **count**.
A count cannot express the thing that actually hurt: from a flat listing you
cannot tell which subsystem a file serves, and the layer lint that was offered as
the substitute answers a *different question*. A layer says when a file may be
imported. It says nothing about what the file is about. Thirty-eight files sorted
by an accident of naming is not navigable at ten, let alone forty.

The lesson is not "pick a better number". It is that a trigger phrased as a
threshold on something incidental will sit green while the cost accrues — and
both times, the NO-GO was defensible on the day and still wrong in aggregate.

Of the three original reasons, one was already dead when this was written, one
was false in a way nobody had checked, and one survived and was preserved:

- ~~The CI selftest glob (`hooks/*.py scripts/*.py`) and `_output.py`'s own
  guard are both non-recursive by design — a file in a subdirectory silently
  stops being tested.~~ **Dead before the reversal.** Every scanner is recursive
  and the last three flat sweeps were converted in `cf50f9f`. Worth stating
  plainly: a flat glob does not *report* a nested file as untested, it **exits 0
  over a partial tree** — a green build over work it never ran.
- **Every file stays directly runnable** — this one held, and was the constraint
  the migration was built around rather than a cost it paid. A `.py` at any depth
  still runs: `python3 plugins/audit/scripts/demo/gen-demo-usage.py --selftest`
  exits 0. What makes that true is `_output.py` as a fixed anchor plus a pinned
  path preamble that walks up to find it, so no file computes a path from its own
  depth (`depth_sensitive_paths()` fails one that tries).
- ~~Hooks reach scripts by flat basename paths, and a folder would mean updating
  every one of those paths for no behavior change.~~ **False, and by a wide
  margin.** "Every one of those paths" is **two invocations** —
  `_config.py:274` inside the wrapper every hook goes through, and
  `meter-usage.py:86` — and both pass a **basename**, which is
  depth-independent. Not one needed updating; the same holds for
  `_loader.script_path()` and `tools/`'s two resolvers. The reason described a
  cost that did not exist, in the plural, and nobody counted it because the
  conclusion was already agreed. Counting it takes one `grep`.

**Directories are labels, not namespaces.** A `.py` basename must stay unique
across the whole of `scripts/` — `import`, `_loader` and `_deps.LAYERS` all
resolve by basename, so two files sharing one would be a single node in the layer
graph wearing both files' edges. `layer_violations()` fails a collision by name.
Nothing outside a domain has to know which domain a file sits in.

The layer lint did not go away; it now answers its own question instead of two.
It still fails an unplaced or wrongly-layered file by name, and
`KNOWN_LAYER_DEBT` still records the runtime edges that are not strictly
downward.

**What stays at the root**, decided by rule rather than by habit: modules with
**no domain**, never modules with a low layer. Measured by importer domain,
`_output`, `_loader`, `_ui_theme`, `_fmt` and `_cli_fmt` are each reached from
two or more domains; `_deps` and `_refs` have zero importers because they are
build-time lints whose subject *is* every domain. `_output.py` is additionally
pinned there by construction — the preamble walks up until it finds it.

**Revisit trigger:** a domain directory whose files no importer outside it
reaches — that domain has become a private implementation of one entry point and
should be collapsed into it. Observable by running `_deps.py --render` and
reading the cross-domain edges, which is a property of the graph rather than a
count of anything.

### ~~usage_ledger.py split deferred (2026-08-10)~~ — DONE (`91af1ae`)

This trigger **did** fire, was acted on, and the record was left stale for eight
days — which is its own small lesson about who updates an ADR after the work.

The file was ~1,939 lines and the largest in the plugin. It is now **681**, split
into three that mean what they are named: `usage/usage_ledger.py`,
`usage/_usage_core.py` and `usage/_usage_analytics.py`. The extraction the
trigger named — the analytics section — is exactly what came out.

"Read by hooks by path" was the deferral's stated cost, and it turned out not to
be one: hooks resolve by **basename** through `find_script()`, so neither the
split nor the later move into `usage/` touched a hook.

The largest file is `_deps.py`, and the count of files over 500 lines under
`scripts/` + `hooks/` is deliberately **not written here** — print it with
`python3 tools/count-ui-pins.py`, which reports it split by directory. The
figure lived in this sentence twice and was wrong both times: it read **26** for
eight days after the split that changed it, and its replacement read **21**
against a real 22 while naming the very command that would have said so. That is
the whole argument for deleting a number rather than annotating it — a basis
makes a claim checkable, and nothing runs a command on a reader's behalf. The
scope was the other half of the failure: neither spelling said which directories
it counted, and adding `tests/` gives a different answer again, so the numbers
were not merely stale, they were unscoped. What remains is the standing split
list, tracked as work rather than as a decision — there is nothing left to
decide here.

### Writing a count that is allowed

The rule above is stated as a prohibition, and that is half of it. Every repair in this class
deletes a number, and authors keep writing them because nothing says what the permitted form
looks like — so here it is, three shapes, and a lint reads all three.

**Delete it and keep the pointer.** The default, and the only one that cannot rot. Name the thing
that holds the answer and the command that prints it, and say nothing about how many:

> The largest file is `_deps.py`; `python3 tools/count-ui-pins.py` reports the split by directory.

**Carry the basis on the same claim.** Legal when the figure is genuinely informative — a ratio a
reader needs, a threshold an argument turns on. The command may sit on the following line, because
prose wraps, and the scanner joins one line each way to find it:

> Roughly a third of the suites reach the browser gates:
> `grep -rln capture-screenshots plugins/audit/tests | wc -l`

A basis makes a claim checkable. It does not make it true, and nothing runs a command on a
reader's behalf — which is why this is the second choice and not the first.

**Put it in the past.** A measurement is a fact about a moment, and a moment does not rot. Say
when, and the tense carries it:

> Two consecutive captures agreed on every image the day this shipped.

The scanner reads the SENTENCE the number sits in, not the line, so a past marker earlier in the
same sentence covers a number further along it — and a marker in the previous sentence does not.
That is F76, and it cuts both ways on purpose.

**What none of these buys you.** A unit is not a count and is not read at all: a duration, a byte
size or a line count passes the lint whatever tense it is in, because the family was surveyed over
this tree and refused — honest prose outnumbered real claims in every cut of it, and `pn27` holds
the measurement that decided so. A stale measurement is therefore YOUR job, not the build's. The
same is true of `the N <noun>` with an ordinary noun, which is the shape F59's own instance wore.

### typing/dataclasses/annotations stay banned (standing since P9.3's AST enforcement)

The 3.8 floor and hooks that must start fast on every tool call rule out the
import and parse cost of `typing`/`dataclasses`/annotations; enforcement is
`_output.house_style_violations`, not a style guide someone can forget to read.

### The report's script is a module (decided 2026-08-20)

`<script type="module">`, and no IIFE. The wrapper existed to keep about a hundred and thirty
top-level bindings out of a page that already carries `window.AUDIT_USAGE`; a module scope does
that natively, so the wrapper was doing a job the platform does better.

**Measured before deciding, because this is a scheme restriction and not a preference.** An inline
module script DOES run from a page opened over `file://`. A cross-file `import` from the same page
does NOT — it fails with `net::ERR_FAILED`, because module scripts are fetched with CORS semantics
and a page opened from disk has an opaque origin. So the parts are still joined by Python, and no
part contains `import` or `export`.

**What it costs, stated rather than discovered later.** A module is strict, and it is deferred.
Both are verified rather than assumed: 154/154 interactive checks against the rendered artifact,
and the assembled body is parsed a second time under `'use strict'` in the Node suite, where a
sloppy parse would accept octal literals, duplicate parameter names and assignments to undeclared
names. The remaining exposure is an embedder that permits `<script>` and not
`<script type="module">` — the same class as the IDE preview pane that strips inline scripts
entirely, and the `audit-nojs` banner is what tells a reader either has happened.

**Revisit if** an embedder is found that runs classic inline scripts and refuses module ones, or if
the report ever needs to be readable with scripting disabled beyond what the banner covers.

### Browser JavaScript dialect (decided 2026-08-19): modern ES, and still no build step

The two surfaces speak different languages. `report.js` is strictly ES5 — 293 `var`,
118 `function ()`, and **zero** `const`, `let` or arrow functions in code (the 35
backticks and the `class`/spread hits in it are all comment prose; measured, not
assumed). `panel.js` is modern — 968 `const`, 594 arrows, an `el()` builder used at
hundreds of sites. The consequence is that the same feature exists twice and cannot
be shared: two `isDark()`, two tooltip placers, two CSV quoters, two blob
downloaders — and the two token formatters **already disagree** while both claiming
in comments to mirror the same Python function.

**One dialect: modern ES.** In order of weight:

1. **The `file://` gate constrains APIs, not syntax.** ES modules are impossible here
   because of the opaque origin — a *module-loading* restriction. `const`, `let`,
   arrows, template literals, destructuring and spread are syntax the engine parses;
   the origin cannot reach them. The one row that made that gate exist (`js-modules`,
   widely available since 2020-11-09 and still unusable here) does not generalise
   from loading to syntax, and reading it as if it did is what kept ES5 in place.
2. **Baseline, from the 2026-07-08 snapshot rather than memory.** `let-const` widely
   since 2019-03-20; `destructuring`, `spread` and `template-literals` since
   2022-07-15; `async-await` since 2019-10-05; `nullish-coalescing` since
   2023-03-16. The newest is three years settled.
3. **The direction of the rewrite is the argument, not the line count.** Choosing ES5
   would mean rewriting 4,895 modern lines *backwards* to match 1,768 — and going
   backwards forfeits block scoping, which is a **correctness** property in a script
   that is concatenated into one scope where every identifier is global. This file
   already records the near-miss: a second `findingsBox` would have hoisted over the
   first and broken every config save. `var` is how that happens; `const` is how the
   engine catches it.
4. **ES5 was never chosen.** Nothing was ever recorded about why, so there is no
   constraint being preserved here — only an accident that had been propagating.

**Excluded regardless, because the `file://` gate still applies to a shared part:**
ES modules and dynamic `import()`, `localStorage`/`sessionStorage`/cookies (the
report treats storage as best-effort inside `try`/`catch` — keep that), `fetch` of a
sibling file, `XMLHttpRequest`, service workers, `crypto.subtle`. And `report.js`
still may contain no wall-clock call at all.

**THIS DOES NOT INTRODUCE A BUILD STEP, AND THAT IS LOAD-BEARING.** Modern ES runs
natively; Python still concatenates the assets and still ships what is in the tree.
"What you read is what ships" survives this decision intact. A plugin install fetches
the repository at a commit SHA and runs nothing — no `npm install`, no compile — so
anything that needed building would have to be **committed as generated output**,
and the tree would stop being the thing it appears to be. That is the cost **step D
(TypeScript) would actually charge**, and it is a consequence to publish rather than
a detail: it converts `plugins/audit/scripts/ui/` from source into build product, and
it reverses this repo's *"there is no build step and there will not be one"* — which
must be done by argument if it is done at all, never as a side effect of adopting a
compiler.

**That cost was put to the owner and ACCEPTED (2026-08-19): shipping a build to the
marketplace is fine.** So step D is no longer gated on this objection, and what
remains is only *where the built output lives*, which is a real choice with two
shapes and they are not equivalent:

- **Build committed to `main`.** Simplest to publish — the marketplace already
  installs by fetching the repo at a commit SHA, so nothing about install changes.
  The cost is that `scripts/ui/` in the branch people read and review is generated,
  every UI diff shows compiler output, and the byte pins begin asserting the
  compiler's formatting rather than anything a person wrote.
- **Build published to a separate target** (a `dist` branch, or its own repository)
  with the marketplace entry pointing there. `main` stays source-only and "what you
  read is what ships" survives *for the repository people work in*. The cost is a
  release step that can go stale, which this project has already had happen once —
  `docs/index.html` drifted from the committed example report and went a month
  unnoticed — so it needs the same byte-equality check that fixed that.

- **`// @ts-check` + JSDoc types over plain `.js`.** No `.ts`, no compiler output,
  no dist target, nothing generated — `tsc --noEmit` reads the `.js` that already
  ships and fails CI on a type error. **Measured, not assumed (2026-08-19):**
  `npx -p typescript@5 tsc --noEmit --allowJs --checkJs --target es2022 --lib
  es2022,dom plugins/audit/scripts/ui/report/*.js` runs against the tree as it is
  today and immediately reports real things (the path was `ui/report.js` when this was
  measured, one file before the cut) — one comparison of a `number`
  with a `string | number` using `>=`, `window.AUDIT_USAGE` undeclared, the
  expando pattern this codebase relies on (`__tip`, `__detail`) is unmodelled, and
  several `HTMLElement` reads want a cast. A run needs `skipLibCheck` and
  node_modules excluded, or it picks up `@types/chai` from the dev tree and reports
  its resolution failures as ours. `panel.js` additionally needs the Python-
  substituted placeholders (`__AUDIT_TOKEN__`, `__SETTINGS__`,
  `__COST_BAND_PARAMS__`) declared, since to a checker they are undefined names.
  The cost is JSDoc annotations, one tsconfig and one CI step; the ceiling is lower
  than real TypeScript (no generics worth the name, weaker inference across the
  concatenation boundary).

**This third option is the one to try first, and it was missing from this entry
until the ecosystem was actually looked at.** Five installed marketplaces —
Anthropic's official one included — ship **zero** `node_modules` between them, and
their content is overwhelmingly markdown (61–226 files each) with code in the
minority; the only file that looked like a bundle was hand-written source with one
very long object literal. Shipping a build artifact would make this repo the first
of those five to do it, which is not an argument against it but does mean the dist
branch sets a convention here rather than following one. `--checkJs` buys most of
the type safety while keeping the property every neighbouring plugin has: what is
installed is what was written.

**Between the two BUILD shapes the second is the structurally correct one**: it
keeps source and artifact distinct, which is the property being traded away, and the staleness it introduces
is mechanically checkable where "is this diff mine or the compiler's" is not. Decide
it when step D is actually scheduled, not before — and note it must be decided
BEFORE any `.ts` lands, because the answer determines what CI builds and what the
pins point at.

**Sequencing, because this cannot be executed first.** The 100 `_SCRIPT` pins assert
**text**, so rewriting 293 `var` and 118 `function ()` turns a large fraction of them
red mechanically — and they would then be updated to match a rewrite instead of
reviewed. The order is **U3.3 step C (pins → behaviour) → dialect unification → step
D**. The decision is still worth making now: it takes effect immediately for **new**
code, so nothing further is written in the dialect being retired.

**Revisit trigger:** a helper is written twice because the two surfaces could not
agree on syntax. That is the cost itself rather than a proxy for it — the previous
two reversals in this record both happened because the trigger was a threshold on
something incidental while the real cost was discoverability or navigability, and a
green trigger is not evidence a decision is still right.

### Real ES modules in the panel (measured 2026-08-20): possible, and not adopted yet

The panel is served over `http://127.0.0.1` by `panel-server.py`, so the reason the report
cannot have cross-file `import` — an opaque `file://` origin refusing a CORS-mode module fetch —
does not apply to it. That was the standing assumption in both directions, and it has now been
put to a browser instead of argued.

**What was measured**, four probes, each declaring the outcome it expected and several expecting
failure, with a `file://` control in the same run reproducing the report's `net::ERR_FAILED` so
that a probe which could only pass was not mistaken for evidence:

- A cross-file `import` **works** over this origin, against the panel server's exact response
  profile (`Content-Type` + charset, `Content-Length`, `Cache-Control: no-store`, no CORS header,
  Host check), both from an external module script and from an inline one.
- The browser is not what blocks it. The **real** server has no static route at all: a module
  fetch of `/ui/panel.js` answers 403 without the session token and 404 with it, and `/api/state`
  cannot double as a module because module scripts are strictly MIME-checked.
- A **relative specifier inherits the path but never the `?t=` query**, so a token-guarded module
  graph must either be open (host-check only — which is what `/` already is, and `/` already hands
  the token to any loopback client) or chain the credential through `import.meta.url`. Both were
  confirmed working.
- The panel's script is still a **classic** `<script>`, not `type="module"` like the report's. It
  boots unchanged as a module — measured by rewriting only the response body through route
  interception, so no tracked file was touched and every `/api` call still went to the real
  server — and the change removes every top-level `function` declaration from `window`.

**Not adopted, and the reason is not the effort.** Adopting it is behaviour change: a static
route, and a new home for the `__*__` placeholders substituted into the script text. Neither can
ride in a commit whose whole safety argument is that the assembled page is byte-identical, which
is what made the cut into `ui/panel/` provably behaviour-free. So the order is: cut first (done),
then decide the route.

**What the decision will actually cost, stated now rather than discovered during it.** Most of
`test__panel_page.py`'s literal `UI_HTML` pins have their literal in the panel's script, so they
stop seeing the code the moment it leaves the page — count them with
`python3 tools/count-ui-pins.py` and the JS-bearing share with a one-off scan of the suite against
the parts. That is not an edit budget; it changes what those pins ASSERT, from "the page contains"
to "a file contains", and the browser gate becomes the only thing left proving the page loads what
it claims. Worse, the negative (`not in`) pins mostly name text that is absent from the script
today, so they stay green whether or not the script is in the page at all — they cannot detect it
leaving. Any adoption has to convert those deliberately, not discover them going quietly green.

**Revisit trigger:** the placeholder question gets an answer that does not need a route — for
instance the panel already serving its per-request values from an endpoint the page reads — or the
one-scope collision hazard actually bites again (the `findingsBox` near-miss is the recorded one).
The `type="module"` half needs no trigger at all: it is available now, costs a route nothing, and
is held back only by wanting the cut reviewed on its own.

### Documentation split by audience (decided 2026-08-23): a landing page that hands off, one page per audience, and a lint that holds the hand-off

The reference documents in this repository had become a wall for two different readers
at once — a new user and a second contributor — and the symptom was not their length.
It was that **the first-run path existed twice**: once in the root `README.md` as a
command list, and once in `plugins/audit/README.md` under its own `## Quick start`,
which a reader reaches only after the TL;DR, the enforcement tables, the command
reference, the requirements and the install notes. Two copies of a first-run path is
one copy and one lie, and the second copy was behind the wall it was supposed to spare
you.

**The cut is by audience, and each document now has one job:**

- `README.md` — the pitch. What is enforced versus what is merely followed, the demo,
  install, and one link per audience. No procedure.
- `QUICKSTART.md` — a new user's first session: install, one audited task, one report.
  Nothing else, ever.
- `COMPATIBILITY.md` — what a version number promises about the manifest and the
  config file the user owns, and where the promise stops.
- `plugins/audit/README.md` — the deep product reference, for a reader who is already
  running it. It now says so in its first screen.
- This file — the contributor's first stop, with the reading order at the top.
- `PLUGIN-BUILD-GUIDE.md` — the architecture, reached from that reading order.

**A lead section inside `README.md` was rejected, and not on effort.** A landing page's
job is to make someone want the thing; a first-run path's job is to get them working.
Kept in one page those two compete, and the path is what loses — every new command
appends a line and nothing says it should not, which is exactly how the list there grew
past first success into a tour. A separate page can be held to *install, one task, one
report* because that is its entire scope, and the failure mode is legible on the page
itself rather than buried in a section of a longer one.

**A reading order alone was rejected for the user and adopted for the contributor**,
because the two readers want different things from the wall. A reading order tells you
which wall to climb; it does not shorten the climb. A new user does not want to climb
any of it — they want their first success — so they get a page instead. A contributor
*is* going to read the reference documents; the walls are the product for them, and
what they were missing was the order.

**`PLUGIN-BUILD-GUIDE.md` was not cut, and the reason is mechanical.** Its own lints
locate sections with a bare text search on literal headings, with no line anchor, and
the guide's path is hardcoded. A reading-order pointer at the top that quoted one of
those headings verbatim would silently retarget the extractor and make every module
under `hooks/` and `scripts/` a finding — the pointer would look like documentation and
behave like a rename. So the guide is reached by name from the reading order above and
is otherwise untouched.

**The split owed a check, and here is the argument.** Nothing in this tree enumerated
the root-level documents, nothing counted them, and nothing asserted that one is linked
from anywhere; there was no Markdown link checker at all. So a split that adds pages
adds pages whose discoverability is held by a human habit — and the whole point of the
split is that a reader's path to first success is short, which is a property of the
link graph. `_refs.doc_link_drift()` was therefore written *with* the split rather than
after it, while the graph was still clean, which is the only cheap moment to start
holding one. It reports both directions: a root document nothing links to, and a link
that points at a path which is not there. Each exemption is declared with its reason,
and a reason that has stopped describing the tree is itself reported — the same shape
`EXCLUDED` and `ABSENT_BY_DESIGN` already use here.

**Revisit trigger, on the user side:** when `QUICKSTART.md` stops being a path and
starts being a reference — when it explains a config key, offers a second way to do a
step, or when a step a first run actually needs is missing from it. Both are read off
the page. Deliberately **not** a length: a document can double in lines and still be
one path, or stay short and carry two, and a line budget is exactly the kind of proxy
the reversals above are about.

**Revisit trigger, on the contributor side:** when a question a contributor hits in
their first hour is answered in none of the reading order's stops, or is answered in
two of them differently. Both are observable the next time someone new lands here,
which is what makes this able to fire at all.
