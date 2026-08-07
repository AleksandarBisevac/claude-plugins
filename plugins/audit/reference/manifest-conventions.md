# Manifest conventions

Shared rules for every command that reads or mutates the audit manifest
(the `/audit:*` execution commands plus `/audit:init`, `/audit:task`, `/audit:bug`, `/audit:sync`).
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
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>
```

Exit 0 = valid. On findings: fix the manifest and re-run before doing anything else.

## Concurrency lock

Locks live in the **shared git dir**
(`$(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks`), not the working
tree — so they coordinate across worktrees and never show up in `git status`.
The full protocol and the two tiers (index lock vs per-phase-shard lock) are in
`orchestrator.md`. The structural commands here — `init`, `task`, `bug`, `sync`
— take the **index lock** (they mutate the shared index: phase directory,
`bugs[]`, `fileIndex`, id counters). Before your **first** index write:

1. Take it with the script — never by hand:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-lock.py" acquire index \
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
merge, and `/audit:migrate --renumber` repairs it.

- **Task**: `<phaseId>.<n>` where `n` = highest existing numeric suffix in that phase + 1 (`P2.4` → next is `P2.5`).
- **Bug**: `BUG-<n>` where `n` = highest existing bug number + 1, repo-wide (`BUG-3` → next is `BUG-4`).
- **Bugfix phase**: `BF<n>` where `n` = highest existing `BF` number + 1 (`BF1`, `BF2`, …).

The "highest existing" is computed over the **whole** manifest — every phase shard plus
the index — which the `/audit:*` commands already load assembled (so a task suffix sees
every task in its phase, and a `BUG-`/`BF` number sees every bug/bugfix phase repo-wide).

## Status enums

- Phase/task: `pending | in_progress | blocked | done`
- Bug: `open | triaged | in_progress | fixed | wontfix`
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
sign-off reviewer, overriding `meta.reviewSkill`) and `area` — a free-text label, or a **list** of
labels for cross-cutting concerns (`"backend"` or `["backend","security"]`; any vocabulary —
devops/security/embedded/data/ml/…) — for grouping/filtering in status/report/panel. Both default to absent.

## fileIndex maintenance

Adding a task with `files` MUST add/extend the matching top-level `fileIndex`
entries (`"<file>": [..., "<taskId>"]`). Never remove other tasks' ids.

## Immutable history

Phases with `status: "done"` are history — never append tasks to them.
Route new work to an open phase or create a new one.
