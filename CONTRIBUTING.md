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
# every selftest suite — stdlib only, no deps. Globbed, never enumerated: a list
# drifted three ways once and CI silently stopped running one suite entirely.
for f in plugins/audit/hooks/*.py plugins/audit/scripts/*.py; do
  python3 "$f" --selftest || exit 1
done

# manifests: structural validator + JSON Schema
python3 plugins/audit/scripts/validate-manifest.py plugins/audit/templates/audit-plan.starter.json
python3 plugins/audit/scripts/validate-manifest.py docs/audit/audit-plan.json
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
- **Fail-open for advisory paths, fail-loud for guards** — see `SECURITY.md`
  for the table; keep it true.
- Every command that mutates the manifest must revalidate
  (`scripts/validate-manifest.py`, exit codes 0/1/2).
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

## Release rule

One release = **one commit** that:
1. bumps `plugins/audit/.claude-plugin/plugin.json` `version`,
2. finalizes the `CHANGELOG.md` section for that version,
3. carries the annotated tag `v<version>` on that same commit.

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

### Plugin evals (evaluated 2026-07, v0.6.0): deferred — feature is early access

`claude plugin eval` (evals/**/case.yaml + graders) is the right tool for
testing the COMMAND PROSE (the orchestrator behavior CI cannot reach), but as
of v0.6.0 it prints "currently in early access" and `eval init` does not
scaffold — the case schema is not public. Adopt as soon as it opens up:
priority cases are `/audit:status` on a missing manifest, `run` guards on a
done task, and the `#no-plan` bypass round-trip.
