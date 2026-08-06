---
description: 'Audit pipeline: token spend attributed by phase, task, model, author and time — with cache economics, cost-per-task and a usage trend. Read-only (never mutates the manifest).'
argument-hint: '[--by phase|task|model|author|agent|day] [--phase <id>] [--author <who>] [--since 7d] [--json] [--backfill]'
allowed-tools: Bash
---

# /audit:usage — where the tokens went

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-usage.py" <manifestPath> $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it.**
The script renders its own final ASCII output for a reason: a usage tool that spends a pile of
tokens laying out its own tables every time you ask what you spent is self-defeating. Reading the
numbers back to the user costs roughly as much as the report describes. Just show it.

The only thing worth adding is a single line of interpretation when something in the output is
genuinely notable — a phase that cost several times its peers, a cache hit rate that collapsed, a
model routed somewhere it shouldn't be. Otherwise say nothing.

Read-only: this never takes the audit lock and never touches the manifest. The one exception is
`--backfill`, which rewrites the monthly ledger files and takes its own `usage.lock`.

## Arguments

Pass `$ARGUMENTS` through unchanged. Nothing here needs interpreting on your side.

| Flag | Effect |
|---|---|
| `--by phase\|task\|model\|author\|agent\|day\|hour\|session\|branch\|attr` | one focused table instead of the dashboard |
| `--phase <id>` `--task <id>` `--model <name>` `--author <who>` | narrow the rows (`--model`/`--author` match on substring) |
| `--attr task\|phase\|window\|unattributed` | filter by attribution precision |
| `--since 7d\|2w\|3m\|YYYY-MM-DD`, `--until YYYY-MM-DD` | bound the window |
| `--top N` | cap TOP TASKS (default 10) |
| `--no-cost` | tokens only, no dollar figures |
| `--json` | machine-readable, for CI |
| `--backfill` | re-read every transcript and rebuild the ledger |

## What the numbers mean

- **Attribution.** Subagent spend is matched to a task exactly (each subagent owns its own
  transcript). Orchestrator spend is matched to whichever phase claimed the session. Anything else
  — ad-hoc edits, `#no-plan` work, sessions predating the ledger — lands in `unattributed` and is
  still counted. A run showing everything as `unattributed` is normal on a repo that has not run a
  phase since metering was installed.
- **Cost is labelled `equiv`** because it is computed from a price table, not from a bill.
  Subscription plans carry no per-token charge, so treat it as "what this would have cost on the
  API", not as money spent.
- **Cache read dominating the token total is healthy** — it is the cheapest tier by a factor of
  fifty. A high cache hit rate means the prompt prefix is stable and being reused.

## When there is no data

The output says so and points at `--backfill`. Metering is a `Stop` / `SubagentStop` / `SessionEnd`
hook, so a brand-new install has nothing until a turn completes. `--backfill` reads the transcripts
already on disk and is idempotent — running it twice leaves identical totals.
