---
description: 'Audit pipeline: diagnose the setup before it bites — interpreter the hooks will use, git root, config, manifest + shard integrity, which plan-gate tier is active, submodule conflicts, build runners, whether hooks have ever fired, the usage ledger, whether the audit trail still holds, and whether the capability policy is inert, contradicted by the plan, or never enforced. Read-only, no locks, no mutations.'
argument-hint: '[--json]'
allowed-tools: Bash
---

# /audit:doctor — is this setup actually working?

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-doctor.py" --project "$(pwd)" $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**
It already renders plain ASCII with one line per check, an indented `->` fix under anything
actionable, and a totals line. Re-narrating it costs tokens and loses the alignment that
makes the output scannable.

Pass `$ARGUMENTS` through unchanged (`--json` for a machine-readable form). Nothing here
needs interpreting on your side.

## What to do with the result

Exit code is the summary: **0** healthy (warnings allowed), **1** one or more findings,
**2** a usage error. The three levels mean different things and should be treated
differently:

- **FINDING** — broken now. The named command or gate will fail. Fix these first; each one
  carries its own `->` fix line.
- **WARNING** — works today, will bite later. A missing manifest, no evidence the hooks have
  run, an empty ledger, a stale lock. Worth reading, not worth blocking on.
- **OK** — checked and healthy. Included deliberately: knowing the plan gate is in `warn`
  rather than `deny` is as useful as knowing something is broken.

If the run reports **no hook state**, the most likely cause is not a broken hook but a
plugin that is installed yet not enabled for this project — check `/plugin` → Installed.

This command is **read-only**: it takes no lock, writes nothing, and never executes a
`meta.buildCommands` entry (it resolves the program each one names and reports whether that
program exists). It is safe to run mid-phase, and safe to run in CI.

Do not modify anything. Related: `/audit:status`, `/audit:init`, `/audit:panel`,
`/audit:usage`, `/audit:migrate`.
