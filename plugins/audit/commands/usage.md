---
description: 'Audit pipeline: token spend attributed by phase, task, model, author and time — with cache economics, cost-per-task and a usage trend. Read-only (never mutates the manifest).'
argument-hint: '[--by phase|task|model|author|agent|day|month] [--phase <id>] [--author <who>] [--area <tag>] [--since 7d] [--format md|ascii] [--json] [--backfill]'
allowed-tools: Bash
---

# /audit:usage — where the tokens went

Run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-usage.py" <manifestPath> --format md $ARGUMENTS
```

**Print its stdout verbatim. Do NOT re-format, summarize, re-tabulate, or "improve" it — and do
NOT wrap it in a code fence.** The output is already markdown (pipe tables, bullets); a fence
would disable the table rendering it exists for. The script renders its own final output for a
reason: a usage tool that spends a pile of tokens laying out its own tables every time you ask
what you spent is self-defeating. Reading the numbers back to the user costs roughly as much as
the report describes. Just show it. (A user-supplied `--format ascii` in the arguments wins over
the default above — argparse takes the last occurrence; print that verbatim too, fenced.)

The only thing worth adding is a single line of interpretation when something in the output is
genuinely notable — a phase that cost several times its peers, a cache hit rate that collapsed, a
model routed somewhere it shouldn't be. Otherwise say nothing.

Read-only: this never takes the audit lock and never touches the manifest. The one exception is
`--backfill`, which rewrites the monthly ledger files and takes its own `usage.lock`.

## Arguments

Pass `$ARGUMENTS` through unchanged. Nothing here needs interpreting on your side.

| Flag | Effect |
|---|---|
| `--by phase\|task\|model\|author\|agent\|day\|month\|hour\|session\|branch\|attr` | one focused table instead of the dashboard |
| `--phase <id>` `--task <id>` `--model <name>` `--author <who>` | narrow the rows (`--model`/`--author` match on substring) |
| `--area <tag>` | only spend whose phase carries this area tag (`untagged` selects spend no area owns) |
| `--attr task\|phase\|window\|unattributed` | filter by attribution precision |
| `--since 7d\|2w\|3m\|YYYY-MM-DD`, `--until YYYY-MM-DD` | bound the window |
| `--top N` | cap TOP TASKS (default 10) |
| `--no-cost` | tokens only, no dollar figures |
| `--format md\|ascii` | `md` (the default above) renders pipe tables for this chat surface; `ascii` is the fixed-width terminal shape for pipes, logs and CI |
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
- **Area is a property of the plan, joined at read time** — a row carries a `phaseId` and the
  phase carries the tags, so re-tagging a phase re-attributes its whole ledger history on the next
  read, with no backfill. A phase tagged with several areas counts its rows under **each** tag, so
  the `BY AREA` rows can sum past the total — the output says so when it applies. `untagged` is
  where spend with no area lands (untagged phase, unknown phase, or no phase on the row).
- **`MONTHLY` appears once the rows in view span two calendar months** — one month would restate
  the totals line. Its ledger columns follow the filters; its plan columns (tasks done, bugs,
  fixed, merged) count the **whole project** by event month, and the footer says so. `--by month`
  is the same bucketing as a plain grouped table.

## When there is no data

The output says so and points at `--backfill`. Metering is a `Stop` / `SubagentStop` / `SessionEnd`
hook, so a brand-new install has nothing until a turn completes. `--backfill` reads the transcripts
already on disk and is idempotent — running it twice leaves identical totals.
