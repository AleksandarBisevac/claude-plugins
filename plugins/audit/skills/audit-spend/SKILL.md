---
name: audit-spend
description: Use when someone asks what their Claude Code work has cost — "what did that cost", "how much have we spent", "where did the tokens go", "which model is burning the budget", "is the cache actually helping" — and wants it attributed to the work rather than a session total. Routes to /audit:usage.
---

# What the work cost

Read `${CLAUDE_PLUGIN_ROOT}/commands/usage.md` and follow it. This file only exists so the
question finds the command.

## The free first move

**`/audit:usage --backfill` needs no manifest, no setup and no agents.** It reads the
transcripts already on disk and attributes past spend by phase, task, model, author and
day. If someone is asking what things cost, run this — do not first propose installing a
pipeline. It is the cheapest true answer available and it uses data they already have.

## What this answers that `/cost` does not

`/cost` and `/stats` are session-scoped totals. This is spend attributed to **plan units** —
which phase, which task, which model, which person, with cache economics and cost-per-task.
Native OpenTelemetry has no phase or task in its attribute set, so this is not a nicer
rendering of the same numbers; it is a different join.

## Print it, do not re-render it

`audit-usage.py` renders its own ASCII output. Print it verbatim. Laying the tables out
again costs tokens to answer a question about token cost, which is self-defeating — the
command file says this too, and it is the rule the rest of this plugin's output follows.

## When a number would be a guess, there will not be one

If you are asked something the ledger cannot support — whether a cheaper model would do,
what the next phase will cost — check what the output actually says. The routing advisory
stays silent without enough in-repo evidence, and projections are suppressed below a sample
gate. That silence is the answer, not a gap to fill in with a price list.
