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
# all ten selftest suites (hooks + scripts) — stdlib only, no deps
for f in plugins/audit/hooks/_config.py \
         plugins/audit/hooks/require-plan.py \
         plugins/audit/hooks/detect-plan-skip.py \
         plugins/audit/hooks/guard-edits.py \
         plugins/audit/hooks/guard-secrets-read.py \
         plugins/audit/hooks/guard-bash-writes.py \
         plugins/audit/hooks/remind-tdd.py \
         plugins/audit/scripts/validate-manifest.py \
         plugins/audit/scripts/audit-status.py \
         plugins/audit/scripts/render-report.py; do
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
  every decision-core change lands with cases that pin it.
- **Fail-open for advisory paths, fail-loud for guards** — see `SECURITY.md`
  for the table; keep it true.
- Every command that mutates the manifest must revalidate
  (`scripts/validate-manifest.py`, exit codes 0/1/2).

## Release rule

One release = **one commit** that:
1. bumps `plugins/audit/.claude-plugin/plugin.json` `version`,
2. finalizes the `CHANGELOG.md` section for that version,
3. carries the annotated tag `v<version>` on that same commit.

Push with `git push origin main --follow-tags` **only after CI is green** on the
commit. Tags are never moved or deleted (the `v0.2.0` tag/main mismatch is
documented in the changelog and fixed forward, not rewritten). For a
multi-plugin future, `claude plugin tag` (official `{name}--v{version}`
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

### Plugin evals (evaluated 2026-07, v0.6.0): deferred — feature is early access

`claude plugin eval` (evals/**/case.yaml + graders) is the right tool for
testing the COMMAND PROSE (the orchestrator behavior CI cannot reach), but as
of v0.6.0 it prints "currently in early access" and `eval init` does not
scaffold — the case schema is not public. Adopt as soon as it opens up:
priority cases are `/audit:status` on a missing manifest, `run` guards on a
done task, and the `#no-plan` bypass round-trip.
