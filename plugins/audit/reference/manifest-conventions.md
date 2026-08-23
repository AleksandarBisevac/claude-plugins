# Manifest conventions

Shared rules for every command that reads or mutates the audit manifest
(the `/audit:*` execution commands plus `/audit:init`, `/audit:task`, `/audit:bug`,
`/audit:propose`, `/audit:sync`).
Read this file FIRST. The execution commands also read `orchestrator.md`.

## Locating the manifest

Read `.claude/audit.config.json` in the consuming repo → `manifestPath`
(default `docs/audit/audit-plan.json`). The manifest is the single source of
truth — never track phase/task/bug state anywhere else.

If `.claude/audit.config.json` exists but is **not valid JSON**, STOP and report
the parse error before any read or write — a malformed config silently drops the
project's guard-hook customizations (the hooks fall back to defaults).

## Edit-and-revalidate rule

Every manifest mutation goes through `Edit`/`Write` and must keep the JSON valid.
After EVERY mutation, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/validate-manifest.py" <manifestPath>
```

Exit 0 = valid. On findings: fix the manifest and re-run before doing anything else.

## Concurrency lock

Locks live in the **shared git dir**
(`$(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks`), not the working
tree — so they coordinate across worktrees and never show up in `git status`.
The full protocol and the two tiers (index lock vs per-phase-shard lock) are in
`orchestrator.md`. The structural commands here — `init`, `task`, `bug`,
`propose`, `sync` — take the **index lock** (they mutate the shared index: phase
directory, `bugs[]`, `proposals[]`, `fileIndex`, id counters). Before your
**first** index write:

1. Take it with the script — never by hand:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" acquire index \
           --project <gitRoot> --note "<command>"
   ```
   **0** → proceed. **3** → another `/audit:*` session is mutating this manifest:
   print the output and STOP. **4** → the holder is not alive: ask the human
   (AskUserQuestion) to confirm, then rerun with `--takeover`.
2. **Release** at the END of the command, including failure paths you control:
   `audit-lock.py release index --project <gitRoot>`. AskUserQuestion pauses keep
   the lock (still your run). A release that exits **3** means you were taken
   over — stop and tell the human rather than `--force`-ing past it.
3. **Read-only subcommands never lock** (`/audit:bug list`, `/audit:sync status`
   perform no write). The lock dir is inside the git dir → never committed; no
   `.gitignore` needed. (No git repo? fall back to `<manifestPath>.lock` — that
   coordinates within a single clone only.)

`/audit:init` **regenerate/append** is the most destructive write — it rewrites
the whole manifest. It MUST hold the **index lock**, refuse while another
session's lock is fresh (never clobber an in-flight run), and back up before
overwriting.

## ID allocation

Allocate ids **while holding the index lock** (see `orchestrator.md` → Concurrency
lock): read the current maximum from the assembled manifest, add one, write, release —
so two sessions on one machine can never mint the same id (the lock serializes the
read‑modify‑write). Across machines (no shared lock) a rare duplicate can still arise on
divergent branches; `validate-manifest.py`'s repo‑wide unique‑id check catches it after
merge, and `/audit:layout <sharded|single-file> --renumber` repairs it (either direction —
bugs live in the index in both layouts).

- **Task**: `<phaseId>.<n>` where `n` = highest existing numeric suffix in that phase + 1 (`P2.4` → next is `P2.5`).
- **Bug**: `BUG-<n>` where `n` = highest existing bug number + 1, repo-wide (`BUG-3` → next is `BUG-4`).
- **Bugfix phase**: `BF<n>` where `n` = highest existing `BF` number + 1 (`BF1`, `BF2`, …).
- **Proposal**: `PROP-<n>` where `n` = highest existing proposal number + 1, repo-wide.

The "highest existing" is computed over the **whole** manifest — every phase shard plus
the index — which the `/audit:*` commands already load assembled (so a task suffix sees
every task in its phase, and a `BUG-`/`BF` number sees every bug/bugfix phase repo-wide).

**Reserved ids.** A still-parked proposal (`status: "proposed"` with a payload)
RESERVES its `payload.phase` id and task ids: `P<n>` allocation counts them
alongside live phases, so materialization is a lossless move and inter-proposal
`blockedBy` refs stay meaningful. Materialized and dropped proposals release
their reservations (a materialized payload id IS the live phase; a dropped one
is free to re-mint).

## Status enums

- Phase/task: `pending | in_progress | blocked | done`
- Bug: `open | triaged | in_progress | fixed | wontfix`
- Proposal: `proposed | materialized | dropped` (enforced on payload-bearing
  proposals; legacy free-form entries are tolerated as-is)
- `tests.mode`: `tdd | regression | gate-only` · `risk`: `low | med | high`

## New task template

Every newly created task MUST be initialized with ALL of:
`status: "pending"`, `attempts: 0`, `maxAttempts: 3`, `commit: null`,
`outcome: {technical: null, descriptive: null}`, `startedAt: null`,
`completedAt: null`, `verifiedBy: []`, plus explicit `blockedBy: []` /
`dependsOn: []` (empty when none) and a `tests` object with `mode`, `add`,
`expectRedFirst`, `gate`.

## New phase template

A newly created phase MUST be initialized with: `status: "pending"`,
`baseRef: null`, `branch: null`, `mergedAt: null`,
`review: {tool: null, model: "sonnet", status: "pending", findings: []}`,
`summary: null`, a one-line `desiredOutcome` (what success looks like — `/audit:status`
shows it, task subagents receive it, and sign-off must address it), and a
`testGate` derived from `meta.buildCommands` keys. Optionally `reviewSkill` (a phase-specific
sign-off reviewer, overriding `meta.reviewSkill`) and `area` — a label, or a **list** of
labels for cross-cutting concerns (`"backend"` or `["backend","security"]`; any vocabulary —
devops/security/embedded/data/ml/…) — for grouping/filtering in status/report/panel. Both default to absent.

## Phase priority (`phase.priority`)

An optional positive integer saying which phase to reach for first **among the tasks
that are already ready**. It never makes an unready task ready and never skips a
dependency — a pinned phase whose `blockedBy` is unsatisfied is skipped, and
`/audit:status` prints the note naming what it waits on and which task ran instead.

- **Tier 1 is unique.** Higher tiers are shared. A second holder of tier 1 is refused at
  write time (the refusal names the current holder), and if one is forced anyway the
  validator warns and the phase that comes FIRST in the manifest wins.
- **Absent means unprioritised** — not tier 0, not a middle tier. Such a phase sorts after
  every pinned one and keeps its written position among its peers, so a manifest with no
  `priority` anywhere runs exactly as it always did.
- **Never hand-write it.** `/audit:task priority <phaseId> <tier|--clear>` takes the index
  lock, revalidates and journals a `phase.priority` row; hand-editing loses all three.
- **Index-only in the sharded layout.** It belongs on the index stub — which already carries
  `status`, so the order is computable without opening a shard, and one writer under one lock
  means two parallel phase runs can never collide on it. A copy found in a shard body is
  ignored, and the validator reports that it was.
- **`priority.maxTier`** (`.claude/audit.config.json`) is advisory. Nothing is clamped to it.

## Areas (`meta.areas`)

A tag on a phase groups it. Registering that tag in `meta.areas` gives it properties:

```json
"areas": {
  "api": {"root": "services/api", "description": "Django service",
          "reviewSkill": "backend-review", "skills": ["python-conventions"]},
  "mobile": {"root": "apps/mobile", "description": "Expo app"}
}
```

`root` is relative to the **project dir**, the same origin as `task.files` and the `fileIndex`
keys (so it carries the `meta.gitRoot` prefix when the workspace is in a subdirectory).

**Registration is optional in both directions.** A phase tag with no entry stays legal — free text
is the v0.16 behaviour and is not deprecated; the validator warns only when the manifest registers
areas at all, where an unregistered tag is nearly always a typo. An entry no phase uses is legal too.

Two things resolve against it, and they are **stated identically here, in `orchestrator.md`
(config resolution, the executor spawn, Phase sign-off step 1) and in `review.md`**:

- **Review skill** — `phase.reviewSkill ?? meta.areas[tag].reviewSkill ?? meta.reviewSkill`. The
  first level that is **present** answers, and an explicit `null` **is** an answer (skip review;
  tests are the signer) rather than a fall-through.
- **Executor skills** — each tag's `meta.areas[tag].skills` first, then `task.skills`, deduped,
  **area first**.

When a phase carries **several tags**, WRITTEN ORDER decides: the first tag whose area declares the
field answers. `/audit:status` prints the resolved reviewer with the basis it came from
(`review: backend-review (area api)`), and `/audit:doctor` warns when a root is not a directory or a
phase tag has no entry. Never re-derive any of this by hand when the output is in front of you.

An area may also declare an advisory **`owner`** (v0.34) — who to coordinate with, written the
way `usage.authorMode` records authors (git `user.email` under the default mode). An explicit
`null` is an answer ("nobody owns this"), not a fall-through, and across several tags written
order decides here too. Advisory only: when someone else edits a covered file in an owned area,
the plan gate adds a once-per-session heads-up; `/audit:status` and the panel display the owner;
nothing gates on it and nothing is assigned by it.

## Proposals (parked phases)

`proposals[]` holds phases that were synthesized but not (yet) approved —
`/audit:init`'s park path writes them, `/audit:propose` lists/materializes/drops
them. A payload-bearing proposal is:

```json
{"id": "PROP-1", "name": "<phase title>", "status": "proposed",
 "origin": "audit:init", "createdISO": "<ISO>",
 "scope": "<main dirs>", "benefit": "<desiredOutcome>", "openQuestions": [],
 "materializedAs": null, "materializedAt": null,
 "payload": {"phase": { ...the full phase... }}}
```

Rules:
- `payload.phase` must be **fully template-initialized** (new-task + new-phase
  templates above) so materialization is a move, not a rebuild.
- The payload's phase/task ids are **reserved** while parked (see ID allocation).
- `fileIndex` covers **live** tasks only — parked tasks enter it at materialize
  time, derived from `payload.phase.tasks[].files`.
- `materializedAs`/`materializedAt` are written by `/audit:propose materialize`
  together with `status: "materialized"` — never by hand, and the record is kept
  as history (like closed bugs).
- Legacy free-form entries (no payload) are tolerated: the validator warns at
  most, `/audit:propose list` renders them with `-` columns, nothing can
  materialize them.

## fileIndex maintenance

Adding a task with `files` MUST add/extend the matching top-level `fileIndex`
entries (`"<file>": [..., "<taskId>"]`). Never remove other tasks' ids.

## Immutable history

Phases with `status: "done"` are history — never append tasks to them.
Route new work to an open phase or create a new one.

## Moving a task (`/audit:task move`)

`/audit:task move <taskId> --to <phaseId>` is the only sanctioned way to relocate a
task. It allocates a fresh `<targetPhase>.<n>` id under the index lock (counting
reserved proposal ids), writes `movedFrom: {id, phase, at}` on the task, rewrites every
`blockedBy`/`dependsOn`/`fileIndex`/`bugs[].taskId` reference across the index and all
shards, and appends a chained `task.move` journal row with
`{fromId, toId, fromPhase, toPhase}`. A hand-drag keeps the old id, which the validator
flags (`id does not follow its phase's prefix` — a warning, never a finding).

**Ledger attribution:** historical usage-ledger rows keep the OLD taskId — history is
never rewritten. New spend attributes to the new id. `movedFrom` plus the `task.move`
row are what let a reader join the two halves.

## Tamper evidence and completion records

Absolute immutability of local files does not exist — the user owns the disk. The
ceiling is **tamper-evidence plus three cross-anchors**: (1) the hash-chained journal
(`scripts/governance/audit-journal.py`), (2) git history, into which the journal is staged with
every task commit (so its committed past must stay a byte-prefix of the working copy —
`verify` checks exactly that), and (3) the usage ledger, re-derivable from Claude
Code's read-only transcripts via `/audit:usage --backfill`. A forger must rewrite all
three consistently; any single-surface forgery is a `/audit:doctor` FINDING
(`check_completions` + the journal check). The journal directory must stay **tracked** —
never add it to `.gitignore`; anchor (2) only pins committed history.

The journal's **completion-record actions**:

- `task.complete` — a task's status moved to done (details: taskId, phaseId, from, to, completedAt)
- `task.blocked` — a task's status moved to blocked (details: taskId, phaseId, from, attempts)
- `task.commit` — a task's commit moved null → SHA (details: taskId, phaseId, commit)
- `phase.signoff` — a phase's status moved to done (details: phaseId, from, to, mergedAt)
- `ado.link` — an item's `ado.id` moved null → id, i.e. /audit:sync linked it to a
  work item (details: taskId?, phaseId, adoId). `lastSyncedAt` bumps deliberately
  draw NO row — the plan did not move (see tracker-sync.md → Journal)
- `task.move` — a task was renumbered into another phase (details: fromId, toId, fromPhase, toPhase)

All but `task.move` are emitted by the `journal-writes` hook and by NOTHING else — never
append them by hand; two writers means duplicate rows and a doctor that can no longer
trust the count. `task.move` is written by `/audit:task move` via the journal CLI.
Tokens are deliberately absent from these rows (metering lands on Stop/SessionEnd);
spend is joined from the ledger by `taskId`.
