---
description: 'Audit pipeline: create (or remove) a git worktree for a phase so you can run it in a parallel session. Claude does the git worktree add + derives the phase branch; you just open a Claude session in the printed path and run /audit:phase there. Sharded manifests merge back conflict-free.'
argument-hint: '<phaseId> [--remove]'
allowed-tools: Read, Bash
---

# /audit:worktree — a git worktree for a phase (parallel runs)

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

Sets up an isolated **git worktree** so a phase can run in its own Claude session, in parallel with
other phases (best on a **sharded** manifest — run `/audit:layout sharded` first — where phase runs write
only their own shard and merge back without conflict). This only touches git worktrees/branches — it
**never edits the manifest**.

**Resolve first (read-only):** `manifestPath` + `gitRoot` from `.claude/audit.config.json`. If
`phase.branch` is already set (the phase was started), use it. Otherwise ask — do NOT compose the
name here, because `meta.branch.template` has cases prose gets wrong:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/manifest/resolve-branch.py" <manifestPath> --phase <phaseId>
```

It prints the branch name AND `<parent>` — the phase's resolved parent branch,
`phase.parentBranch ?? meta.developmentBranch` — which is what the worktree must be cut from and
merged back into. Exit 1 means the composed name is not a legal git ref; stop and report.
Worktree path: `../<repo>-<phaseId>` (repo = the git-root directory's basename).

**Create (default):**
```bash
git -C <gitRoot> worktree add "../<repo>-<phaseId>" -b <branch> <parent>
```
(If `<branch>` already exists — the phase was started — drop `-b`: `git -C <gitRoot> worktree add "../<repo>-<phaseId>" <branch>`.)
Then print the next step for the user, e.g.:
```
Worktree ready at ../<repo>-<phaseId> on branch <branch>.
Open a session there and run the phase:
    cd ../<repo>-<phaseId> && claude
    /audit:phase <phaseId>
```
Remind them: run each phase in its **own** session/worktree; when done, merge the branch back into
`<parent>` (ff, else `--no-ff`) and remove the worktree (below). **When `<parent>` is not the
development branch, say so** — the work has not reached the development branch until that parent is
itself merged, and `resolve-branch.py` prints that sentence for you.

**Remove (`--remove`):**
```bash
git -C <gitRoot> worktree remove "../<repo>-<phaseId>"
```
(Use `--force` only if they confirm discarding uncommitted work; offer `git branch -d <branch>` after a
merged phase.)

**Preflight:** verify the git root is a repo and `<phaseId>` exists; if the target path already exists,
say so and stop (don't clobber). Never run a phase yourself — this command only prepares the worktree.
