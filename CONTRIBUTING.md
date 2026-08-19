# Contributing

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

```bash
# every selftest suite — stdlib only, no deps. Swept, never enumerated: a list
# drifted three ways once and CI silently stopped running one suite entirely.
# `find`, not `*.py`, and for the same reason — the glob was flat, so a file one
# directory down stopped being run here without anything going red.
for f in $(find plugins/audit/hooks plugins/audit/scripts -name '*.py' | sort); do
  python3 "$f" --selftest || exit 1
done

# ...and the suites that have MOVED OUT of the files they test. A migrated file still
# exits 0 on --selftest (it prints where its cases went), so the loop above stays green
# over a suite it no longer runs — this line is what actually runs it.
for f in $(find plugins/audit/tests -name '*.py' | sort); do
  python3 "$f" --selftest || exit 1
done

# manifests: structural validator + JSON Schema
python3 plugins/audit/scripts/manifest/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
python3 plugins/audit/scripts/manifest/validate-manifest.py docs/audit/audit-plan.json
npx --yes ajv-cli validate --spec=draft2020 -s plugins/audit/schema/audit-plan.schema.json \
  -d plugins/audit/templates/audit-plan.starter.json

# plugin/marketplace structure
claude plugin validate .
claude plugin validate plugins/audit
```

CI (`.github/workflows/ci.yml`) runs the selftest suite on ubuntu + windows —
the windows leg proves the `python3` → `python` → `py` interpreter fallback
(the manifest-validation and plugin-validate jobs run on ubuntu).

## Hard rules

- **Stdlib only** in hooks/scripts — a guard that needs `pip install` is a guard
  that is off on most machines. `py-launch.sh` stays POSIX-sh builtins-only.
- **Schema changes are additive** (or remove never-read optional fields). An
  existing manifest must keep validating across versions; prove it with a
  legacy-fields fixture when in doubt.
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

### typing/dataclasses/annotations stay banned (standing since P9.3's AST enforcement)

The 3.8 floor and hooks that must start fast on every tool call rule out the
import and parse cost of `typing`/`dataclasses`/annotations; enforcement is
`_output.house_style_violations`, not a style guide someone can forget to read.

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
  es2022,dom plugins/audit/scripts/ui/report.js` runs against the tree as it is
  today and immediately reports real things — `report.js:257` compares a `number`
  with a `string | number` using `>=`, `window.AUDIT_USAGE` is undeclared, the
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
