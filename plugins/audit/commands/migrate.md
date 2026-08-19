---
description: 'Audit pipeline: switch the manifest from the single-file layout to the sharded layout (index + per-phase shards) — fewer tokens per phase, parallel-safe across worktrees. A layout CHOICE, not a version upgrade: both shapes are current and a single-file manifest never goes out of date. Opt-in and backed up, but one-directional — there is no reverse command.'
argument-hint: '[--dry-run] [--renumber] [--force]'
allowed-tools: Read, Bash, AskUserQuestion
---

# /audit:migrate — single-file → sharded layout

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

This converts `<manifestPath>` from one JSON file into an **index** (meta · bugs · fileIndex) plus one
**shard per phase** at `phases/<phaseId>.json`. Reading is already transparent for both layouts, so
this is **opt-in**: nothing else in the plugin reads a manifest differently afterwards.

**A layout choice, not a version upgrade — say so plainly if the user asks why they are being
told to "migrate".** Single-file and sharded are two current shapes of the same schema, and
`meta.version` (2 single-file, 3 sharded) encodes the **layout**, not the age. Installing a newer
plugin never makes this due, skipping it never makes a manifest legacy, and `/audit:doctor`'s
`layout` line is reporting which shape is in use rather than nominating one to fix. The command is
named for the direction it moves in, and that is the whole of what the name means.

**What actually decides it** — ask about this, not about version numbers:
- **sharded** — phases run in parallel from separate worktrees, or the plan has grown big enough
  that loading every phase in order to run one costs real context;
- **single-file** — one session at a time, a handful of phases. One file, one diff, no index.

**One direction only, and this is the part to say BEFORE running.** The script's flags are all
forward — `--dry-run`, `--force`, `--renumber`, `--out=<index>` — and nothing anywhere in the plugin
assembles shards back into a single file. "Backed up" means the pre-migration
`<manifestPath>.bak-<UTC>` is left on disk; going back is a manual copy of that file, which
**discards every manifest write made after the migration**. It is an undo for the migration itself,
not an undo for a plan that has since been worked on.

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
`phases/*.json` are **new files** — tell the user to `git add` them, and that the `.bak-*` is the only
route back to single-file: safe to delete once they are happy, and no longer a useful undo the moment
the manifest is written to again. From here, `/audit:phase P2` loads only `phases/P2.json` (fewer
tokens) and two phases run in parallel from separate worktrees without a manifest merge conflict.
