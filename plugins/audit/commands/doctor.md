---
description: 'Audit pipeline: diagnose the setup before it bites — interpreter the hooks will use, git root, config, manifest + shard integrity, which plan-gate tier is active, submodule conflicts, build runners, whether hooks have ever fired, the usage ledger, whether the audit trail still holds, and whether the capability policy is inert, contradicted by the plan, or never enforced. Read-only, no locks, no mutations.'
argument-hint: '[--json] [--color auto|always|never]'
allowed-tools: Bash
---

# /audit:doctor — is this setup actually working?

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/status/audit-doctor.py" --project "$(pwd)" $ARGUMENTS
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
  run, an empty ledger (told apart from a ledger nothing ever created — that one reads
  `no ledger yet` and names the path metering will write), a stale lock, journal files
  uncommitted for over a week (the git anchor only pins committed history), an area owner
  the ledger's author column has never seen (usually an identity written differently from
  what `usage.authorMode` records). Worth reading, not worth blocking on.
- **OK** — checked and healthy. Included deliberately: knowing the plan gate is in `warn`
  rather than `deny` is as useful as knowing something is broken. The plan-gate line names
  the tier **and what put it there** — `planGate`, legacy `enforce`, or the graded ladder —
  and pinning `planGate: "observe"` while a phase is running is the one setting that warns,
  because it holds the gate below what the evidence would enforce.

If the run reports **no hook state**, the most likely cause is not a broken hook but a
plugin that is installed yet not enabled for this project — check `/plugin` → Installed.

This command is **read-only**: it takes no lock, writes nothing, and never executes a
`meta.buildCommands` entry (it resolves the program each one names and reports whether that
program exists). It is safe to run mid-phase, and safe to run in CI.

Do not modify anything. Related: `/audit:status`, `/audit:init`, `/audit:panel`,
`/audit:usage`, `/audit:migrate`.
