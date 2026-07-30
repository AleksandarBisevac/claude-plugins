---
description: 'Audit pipeline: create (or remove) a git worktree for a phase so you can run it in a parallel session. Claude does the git worktree add + derives the phase branch; you just open a Claude session in the printed path and run /audit:phase there. Sharded manifests merge back conflict-free.'
argument-hint: '<phaseId> [--remove]'
allowed-tools: Read, Bash
---

# /audit:worktree — a git worktree for a phase (parallel runs)

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

Sets up an isolated **git worktree** so a phase can run in its own Claude session, in parallel with
other phases (best on a **sharded** manifest — run `/audit:migrate` first — where phase runs write
only their own shard and merge back without conflict). This only touches git worktrees/branches — it
**never edits the manifest**.

**Resolve first (read-only):** `manifestPath` + `gitRoot` from `.claude/audit.config.json`; read the
manifest and find `<phaseId>`. Derive the branch exactly as phase entry would (orchestrator →
Branch-per-phase): if `phase.branch` is already set, use it; otherwise
`<meta.branchPrefix|"audit">/<phaseId-lowercased>-<slug>` where `slug` is `phase.title` lowercased,
spaces→hyphens, alphanumeric+hyphens, ≤30 chars. Worktree path: `../<repo>-<phaseId>` (repo = the
git-root directory's basename). `<developmentBranch>` = `meta.developmentBranch` (default `main`).

**Create (default):**
```bash
git -C <gitRoot> worktree add "../<repo>-<phaseId>" -b <branch> <developmentBranch>
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
`<developmentBranch>` (ff, else `--no-ff`) and remove the worktree (below).

**Remove (`--remove`):**
```bash
git -C <gitRoot> worktree remove "../<repo>-<phaseId>"
```
(Use `--force` only if they confirm discarding uncommitted work; offer `git branch -d <branch>` after a
merged phase.)

**Preflight:** verify the git root is a repo and `<phaseId>` exists; if the target path already exists,
say so and stop (don't clobber). Never run a phase yourself — this command only prepares the worktree.
