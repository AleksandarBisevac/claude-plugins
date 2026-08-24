---
description: 'Audit pipeline: choose how the manifest is stored — `sharded` (an index plus one file per phase: fewer tokens per phase run, parallel-safe across worktrees) or `single-file` (one file, one diff, no index). A layout CHOICE, not a version upgrade: both shapes are current, neither goes out of date, and this command moves in either direction under one lock, one backup and a re-validate-or-restore.'
argument-hint: '<sharded|single-file> [--dry-run] [--renumber] [--force]'
allowed-tools: Read, Bash, AskUserQuestion
---

# /audit:layout — pick the manifest layout, in either direction

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

Two shapes of the same schema, and every script and hook in this plugin **reads both
transparently**:

- **`sharded`** — `<manifestPath>` is an *index* (`meta` · `bugs` · `fileIndex` · phase stubs)
  and each phase's body lives in `phases/<phaseId>.json`.
- **`single-file`** — the whole manifest is that one file.

**Neither is legacy and neither is a stage.** Installing a newer plugin never makes a layout
change due, staying on single-file never makes a manifest out of date, and `/audit:doctor`'s
`layout` line reports which shape is in use rather than nominating one to fix. If the user asks
why the old name for this command was `migrate`, that is the answer: the name described a
direction and read as an age.

**What actually decides it** — ask about this, never about version numbers:

- **sharded** when phases run in parallel from separate worktrees, or when the plan has grown big
  enough that loading every phase in order to run one costs real context;
- **single-file** when it is one session at a time and a handful of phases. One file, one diff, no
  index to keep in step.

## 0. Which direction

`$ARGUMENTS` begins with `sharded` or `single-file`. Read the manifest first (conventions →
Locating the manifest) and say which layout is in use **before** anything else, because that is
what makes the request meaningful:

- **Already in the requested layout** → say so and stop. Nothing to do is a result, not a no-op.
- **No direction in `$ARGUMENTS`** → ask (AskUserQuestion), naming the current layout in the
  question and phrasing the options by the criterion above — *parallel phases across worktrees, or
  a manifest big enough that per-phase context hurts* vs *solo work, few phases*. Never guess a
  direction from the current layout: "the other one" is not a decision the user made.

Everything below runs for **both** directions unless a step says otherwise.

## 1. Preflight (this command mutates — hold the index lock)

1. Resolve `manifestPath` and read the manifest (conventions → Locating the manifest).
2. Preflight the git root (orchestrator → Preflight): the lock lives in the shared git dir.
3. Acquire the **index lock**:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" acquire index \
           --project <gitRoot> --note "layout <direction>"
   ```
   **0** → proceed. **3** → a live run holds it: print the output verbatim and STOP. **4** → the
   holder is not alive: print the output, ask the user to confirm (AskUserQuestion), then rerun
   with `--takeover`.
4. **Refuse a mid-run or dirty-tree change.** If any phase is `in_progress`, stop and ask the user
   to finish or pause it first (the script enforces this too; `--force` overrides). Prefer a
   **clean working tree**, so the layout change lands in its own commit and is reviewable as one.

### 1a. Extra preflight for `single-file` only — the index lock is not enough here

The forward direction reads **one** file, so it sees one moment. The reverse reads the index **and
every shard**, and those are governed by different locks: a phase run holds `phase-<phaseId>` for
its whole duration and writes only its own shard, which the index lock you just took does not
cover. Assemble while one is running and the single file you write is a *mix of moments* — one
phase from before its last write, another from after — and nothing downstream will ever say so.

1. **List every lock, not just the one you hold:**
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" status \
           --project <gitRoot> --json
   ```
   Any `phase-*` lock in the output → **STOP**, name the holder and its phase, and release the
   index lock. A live one means a run is writing a shard right now. An abandoned one means a run
   died mid-write, so that shard may be *half* a write; that is a repair to make before the
   layout changes, not a lock to take over.
2. **Say what other worktrees are about to lose,** and ask before proceeding:
   ```bash
   git -C <gitRoot> worktree list
   git -C <gitRoot> branch --list 'audit/*'
   ```
   A phase branch created for the sharded layout edits `phases/<phaseId>.json`. Merged into a
   branch that no longer reads shards, those edits land in a file nothing assembles — the merge
   succeeds and the work disappears from the plan. If any phase worktree or unmerged `audit/*`
   branch exists, list it, say that plainly, and get an explicit confirmation. This is the cost
   the sharded layout was bought with, being sold back.
3. **A value sitting where nothing reads it is a refusal, not a warning.** In the sharded layout
   the index owns `priority` outright and a copy in a shard body is ignored; assembling would
   promote that ignored value into the only file there is. `validate-manifest.py` reports it as a
   finding, the script validates the source before writing, so this shows up as a refusal — relay
   it as *decide which value is right and put it in the index first*, not as a validation quirk.

## 2. Run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/migrate-manifest.py" <manifestPath> --to=<direction>
```

Pass `--dry-run` (preview the result, write nothing), `--renumber` (repair duplicate `BUG-` ids
from a cross-machine collision before the layout changes — bugs live in the index in both
layouts, so it applies to either direction) or `--force` through from `$ARGUMENTS`. Bare, with no
`--to=`, the script still means `sharded`: that is the spelling in older runbooks and transcripts.

Either direction: the script validates the **source** first, backs the manifest up to
`<manifestPath>.bak-<UTC>`, writes atomically, then **re-validates the result and restores the
backup on any failure**.

**To `sharded`, one more refusal, and `--dry-run` hits it too.** Two phase ids that sanitise to
the same shard FILENAME would be written to one file and the second body would silently replace
the first — the index would still list both stubs, both pointing at the survivor, and the phase
that was overwritten would be gone from disk. That is exit 1 with the colliding ids named, and
the relay is *rename one of them, then run this again*, never `--force` (which overrides the
in-progress check and not this one). **Filenames are compared without case on every platform**,
including Linux: a split that is clean on a case-sensitive volume loses a phase the first time a
colleague on macOS or Windows saves the plan, and a document that travels has to refuse in the
same place everywhere. `--dry-run` refuses it as well, deliberately — a preview that listed the
shard files and said nothing about two of them being one file would send the user into the real
run to find out.

## 3. After — release, then report what changed on disk

Release the index lock (`audit-lock.py release index --project <gitRoot>`), including on the
failure paths you control. A release that exits **3** means you were taken over: stop and tell the
user rather than `--force`-ing past it.

Report the backup path in both directions, and say what it is: `.bak-<UTC>` is a **restore point
for this command**, not an undo for the plan. Restoring it discards every manifest write made
since, and stops being a useful route back the moment the manifest is written to again. Safe to
delete once the user is happy.

**To `sharded`:** the index and every `phases/*.json` are **new files** — tell the user to
`git add` them. From here `/audit:phase P2` loads only `phases/P2.json`, and two phases run in
parallel from separate worktrees without a manifest merge conflict.

**To `single-file`:** the assembled file is the only one anything reads now, and **the shard files
are still on disk** — no longer read by anything, still committed, still looking authoritative to
the next person who opens one. Name every path that is now dead, and say the repair is one commit:
`git rm` the `phases/` shards and `git add` the assembled manifest together. A tree carrying both
is a tree where a hand-edit can land in the file that is ignored.
