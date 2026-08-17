---
description: 'Manage parked phase proposals in the audit manifest — list them, materialize one (or all) into live phases, or drop one. Proposals are parked by /audit:init when the user declines (some of) the synthesized plan; materialization is a move, not a re-synthesis.'
argument-hint: 'list | materialize <PROP-id>|--all | drop <PROP-id>'
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

## Subcommand: `list`

Read-only. Print a table `id | status | reserved phase (task count) | name | openQuestions`.
Legacy free-form entries (no `payload`) render `-` for the payload columns.
Default filter: `proposed` only; `list all` shows materialized/dropped history too.
Empty result → say so; if the plan also has zero phases, point to `/audit:init`.

## Subcommand: `materialize <PROP-id> | --all`

1. **Refuse when**: the id is unknown; status is `materialized` (point at its
   `materializedAs` phase); status is `dropped` (say why it was dropped, from
   `notes`); or the proposal has no `payload.phase` (legacy free-form entry —
   nothing to materialize; suggest `/audit:task add` or a fresh `/audit:init`).
2. **Collision guard**: the payload phase id is *reserved*, so normally it is
   free. If it (or any payload task id) now collides with a live id (a manifest
   merged from elsewhere, or an old plugin version minted over the reservation):
   allocate the next free `P<n>` — counting live phases AND every still-parked
   payload id — remap the payload's task ids and its intra-payload refs, and say
   so in the report.
3. **Dependency resolution**: for each `blockedBy`/`dependsOn` ref in the payload
   that does not resolve to a live id:
   - ref names another still-parked proposal's payload → with `--all`,
     materialize in dependency order; for a single id, ask (AskUserQuestion):
     **also materialize that dependency** (Recommended) / **drop the edge**
     (record it in the phase's `description`) / **abort**.
   - ref names nothing anywhere → drop the edge and note it in the report (the
     validator already warned about it while parked).
4. **Append the phase**: single-file layout (`meta.version: 2`) → append
   `payload.phase` to `phases[]`. Sharded layout (`meta.version: 3`) → write the
   phase as `phases/<id>.json` next to the index and append the stub
   `{id, title, shard: "phases/<id>.json"}` to the index's `phases[]` (same
   format `/audit:migrate` produces).
5. **Extend `fileIndex`** with every entry in every task's `files`
   (conventions → fileIndex maintenance; never remove other tasks' ids).
6. **Flip the proposal**: `status: "materialized"`, `materializedAs: "<phaseId>"`,
   `materializedAt: <ISO now>`. The record stays — materialized proposals are
   history, like closed bugs.
7. Revalidate; release the lock; report `PROP-<n> → <phaseId> (<k> tasks)` per
   materialized proposal and the handoff: `/audit:status`, then
   `/audit:phase <phaseId>` (with `--all`: the first phase in dependency order).

## Subcommand: `drop <PROP-id>`

1. Refuse if status is `materialized` — its phase is live; dropping the record
   would orphan the history trail.
2. Set `status: "dropped"` and record a one-line `notes` justification (ask if
   not given). The reserved payload ids are released — future allocation ignores
   dropped proposals.
3. Revalidate and report. A dropped proposal is history, not deleted — a later
   reader should find WHY the work was declined.
