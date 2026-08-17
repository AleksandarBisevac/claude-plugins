---
description: 'Audit pipeline: migrate the manifest from the single-file layout to the sharded layout (index + per-phase shards) — fewer tokens per phase, parallel-safe across worktrees. Opt-in, backed up, reversible; legacy manifests keep working without it.'
argument-hint: '[--dry-run] [--renumber] [--force]'
allowed-tools: Read, Bash, AskUserQuestion
---

# /audit:migrate — single-file → sharded layout

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

This converts `<manifestPath>` from one JSON file into an **index** (meta · bugs · fileIndex) plus one
**shard per phase** at `phases/<phaseId>.json`. Reading is already transparent for both layouts, so
this is **opt-in** and **reversible** (a timestamped backup is written); a legacy manifest never needs it.

**Preflight (this command mutates — hold the index lock):**
1. Resolve `manifestPath` and read the manifest (conventions → Locating the manifest). If it is
   **already sharded**, say so and stop (nothing to do).
2. Preflight the git root (orchestrator → Preflight): the lock lives in the shared git dir.
3. Acquire the **index lock** (`audit-lock.py acquire index`, conventions → Concurrency lock):
   exit 3 → stop, a live run holds it; exit 4 → offer a confirmed takeover via AskUserQuestion.
4. **Refuse a mid-run or dirty-tree migration.** If any phase is `in_progress`, stop and ask the user
   to finish/pause it first (the script also enforces this; `--force` overrides). Prefer a **clean
   working tree** so the new shard files land in their own commit.

**Run:**
```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/migrate-manifest.py" <manifestPath>
```
Pass `--dry-run` (preview the split, write nothing), `--renumber` (repair duplicate `BUG-` ids from a
cross-machine collision before migrating), or `--force` through from `$ARGUMENTS`. The script validates
the source first, backs it up to `<manifestPath>.bak-<UTC>`, writes the index + shards atomically, then
**re-validates the result and restores the backup on any failure**.

**After:** release the index lock. Report the written paths and the backup. The index and every
`phases/*.json` are **new files** — tell the user to `git add` them (and that the `.bak-*` backup can be
deleted once they're happy). From here, `/audit:phase P2` loads only `phases/P2.json` (fewer tokens) and
two phases run in parallel from separate worktrees without a manifest merge conflict.
