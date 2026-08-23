---
description: 'Manage parked phase proposals in the audit manifest — list them, materialize one (or all) into live phases, or drop one. Proposals are parked by /audit:init when the user declines (some of) the synthesized plan; materialization is a move, not a re-synthesis.'
argument-hint: 'list | materialize <PROP-id>|--all | drop <PROP-id> | revive <PROP-id>'
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

# /audit:propose — parked phases, materialized on demand

Proposals live in the manifest's top-level `proposals[]`, OUTSIDE phases — a parked
phase is not yet a plan (the same shape bugs have: `bugs[]` → `/audit:bug fix`).
Each payload-bearing proposal carries the FULL synthesized phase (`payload.phase`,
tasks initialized per the new-task template), so `materialize` moves it into
`phases[]` without re-planning anything.
Proposal lifecycle: `proposed → materialized | dropped`.

**`$ARGUMENTS`**: first token is the subcommand. Unknown/empty → print usage and stop.

## 0. Conventions

Read `${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` FIRST. Resolve and read
the manifest. If it doesn't exist, stop and point to `/audit:init`.
After EVERY mutation: revalidate with
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>` —
on findings, fix and re-run until clean.
`materialize` and `drop` hold the **index lock** (conventions → Concurrency lock)
around their writes — they mutate the phase directory and `fileIndex`; `list` is
read-only and never locks.

## The rule is a script, not this file

`list`, `materialize`, `drop` and `revive` are one implementation, in
`${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py`. The three writers
hold the index lock, revalidate before they write, and refuse rather than guess;
`list` is read-only and prints its own table. **Do not re-derive any of it here** —
the panel calls the same script and its Proposals tab reads the same rows, and two
readings of one rule are two answers the first time either is edited.

What stays YOURS is the conversation: printing what the script returns, asking the
one question it deliberately will not ask itself, and reporting the handoff.

## Subcommand: `list`

Read-only; no lock. Run it and **print the output verbatim** — the table is what the
script prints, not a shape to reproduce from this file:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py" \
  <manifestPath> list [all]
```

`list all` adds the materialized/dropped history to the default view; `--json` hands
back the rows instead of the render. An empty result answers itself, including the
case where there is no plan to park anything in.

Yours is what follows it: reading an `openQuestions` cell back when it is what blocks
a decision, and pointing at `materialize` or `drop` for the row the user picks.

## Subcommand: `materialize <PROP-id> | --all`

1. **Plan first — it writes nothing:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py" \
     <manifestPath> plan <PROP-id>|--all --json
   ```

   Exit 1 means every named proposal was refused; print the reasons verbatim and
   stop. The refusals are already worded for a reader (an already-materialized one
   points at its phase, a dropped one quotes why it was dropped).

2. **Print the plan** as the script reports it — one line per proposal
   (`PROP-n -> P<id> (k tasks)`, plus `[renamed from …]` when the collision guard
   allocated a new id), and each `waits on …, still parked` / `edge to … resolves to
   nothing` under it.

3. **`needsDecision: true` is the ONE question the script leaves to you.** It means a
   single materialization waits on a still-parked proposal. Ask (AskUserQuestion):
   **also materialize it** (Recommended → `--with-deps`) / **cut the edge**
   (→ `--drop-edges`, which records the cut in the phase's `description`) /
   **abort**. `--all` implies `--with-deps`, in dependency order.

4. **Execute with the answer:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py" \
     <manifestPath> materialize <PROP-id>|--all [--with-deps|--drop-edges]
   ```

   The script appends the phase in whichever layout the manifest uses, extends
   `fileIndex`, flips the proposal to `materialized` with `materializedAs` and
   `materializedAt`, revalidates, and writes nothing at all if the result would be
   invalid.

5. **Report the handoff**: `/audit:status`, then `/audit:phase <phaseId>` (with
   `--all`: the first phase in dependency order).

## Subcommand: `drop <PROP-id>`

A drop is an ARCHIVE, not a deletion — the payload stays and a later reader must find
why the work was declined. So the reason is required, and the validator enforces it
rather than trusting this file to have asked.

1. Ask for the one-line reason if `$ARGUMENTS` did not carry one.
2. ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py" \
     <manifestPath> drop <PROP-id> --reason "<why>"
   ```
   It refuses a materialized proposal (its phase is live; dropping the record would
   orphan the history trail) and a blank reason. It sets `status: "dropped"`, `notes`,
   and `droppedAt`, then revalidates.
3. Report the reason back, so the terminal carries what the archive now says.

## Subcommand: `revive <PROP-id>`

Puts a dropped proposal back in play — `dropped → proposed` — and **keeps the drop
reason as history**. Archiving that could not be undone would be a tombstone, and a
revived proposal that forgot it was ever declined has lost the point of the archive.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/materialize-proposal.py" \
  <manifestPath> revive <PROP-id>
```

Only a dropped proposal can be revived; anything else is refused by name.
