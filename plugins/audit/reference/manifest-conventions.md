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

Two sessions mutating one manifest corrupt each other, so every command that
WRITES the manifest takes `<manifestPath>.lock` — the same lock the execution
commands (`orchestrator.md`) use. Before your **first** manifest write:

1. If `<manifestPath>.lock` exists, read it (`{hostname, startedAt, note}`):
   - `startedAt` younger than **60 minutes** → **REFUSE**: print the holder and
     stop — another `/audit:*` session is (or just was) on this manifest.
   - older → stale (a crashed run) → ask the human (AskUserQuestion) to confirm
     **takeover**, then overwrite it.
   Otherwise create it via Bash:
   `printf '{"hostname":"%s","startedAt":"%s","note":"<command>"}' "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > <manifestPath>.lock`
2. **Release** it (delete the file) at the END of the command, including failure
   paths you control. AskUserQuestion pauses keep the lock (still your run).
3. **Read-only subcommands never lock** (`/audit:bug list`, `/audit:sync status`
   perform no write). Never `git add` the lock; `.gitignore` `*.lock`.

`/audit:init` **regenerate/append** is the most destructive write — it rewrites
the whole manifest. It MUST hold the lock, refuse while another session's lock
is fresh (never clobber an in-flight run), and back up before overwriting.

## ID allocation

- **Task**: `<phaseId>.<n>` where `n` = highest existing numeric suffix in that phase + 1 (`P2.4` → next is `P2.5`).
- **Bug**: `BUG-<n>` where `n` = highest existing bug number + 1, repo-wide (`BUG-3` → next is `BUG-4`).
- **Bugfix phase**: `BF<n>` where `n` = highest existing `BF` number + 1 (`BF1`, `BF2`, …).

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
`testGate` derived from `meta.buildCommands` keys.

## fileIndex maintenance

Adding a task with `files` MUST add/extend the matching top-level `fileIndex`
entries (`"<file>": [..., "<taskId>"]`). Never remove other tasks' ids.

## Immutable history

Phases with `status: "done"` are history — never append tasks to them.
Route new work to an open phase or create a new one.
