---
description: 'Audit pipeline: the worktrees this plan owns — list them with their merge state, add one for a phase so it can run in a parallel session, remove one, or sweep the ones whose work has already landed. The sweep is read-only until you name a verb; a worktree is only ever reaped when its branch is contained in its parent AND its tree is clean.'
argument-hint: '<list|add|remove|sweep> [phaseId] [--path DIR] [--force] [--apply] [--remove-worktrees] [--delete-branches] [--prune] [--json]'
allowed-tools: Read, Bash
---

# /audit:worktree — the worktrees this plan owns

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

A **git worktree** lets a phase run in its own Claude session, in parallel with other phases (best
on a **sharded** manifest — `/audit:layout sharded` — where phase runs write only their own shard
and merge back without conflict). This command never edits the manifest.

**Every verb is one script call.** Do not compose `git worktree` commands yourself: this command
was prose until v2.1, and the prose composed a worktree path and then recorded it nowhere, so
nothing could enumerate what had been created and nothing ever cleaned up.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/manage-worktrees.py" \
    <list|add|remove|sweep> <manifestPath> [phaseId] --project <projectDir>
```

Resolve `manifestPath` and `gitRoot` from `.claude/audit.config.json` first (read-only).

## The verbs

**`list`** — every worktree, the phase it belongs to, the branch it holds, whether that branch is
**contained** in its parent, and whether the tree is dirty. It also names the worktrees the plan
expects that do not exist, and the ones git lists that this plan does not name (`stranger`).

**`add <phaseId>`** — creates the worktree and prints the next step for the human:

```
cd <path> && claude
/audit:phase <phaseId>
```

Preflight is the script's: a branch already checked out elsewhere, a non-empty target directory,
and whether the branch needs creating are all answered before git is called, because git's own
refusals here arrive with three different exit codes. `--path` names somewhere other than the
default `../<repo>-<phaseId>`.

**`remove <phaseId>`** — removes it, after asking the questions git does not. It refuses a dirty
tree, a tree git will not describe, and the tree the process is standing in. `--force` is the
explicit escape; state what it destroys before offering it.

**`remove --path <dir>`** — the same, for a worktree this plan does not name. It is the **only**
way to take down a worktree the plugin did not create, and that is not a loophole: a human named
one exact directory in an argument, which is what consent looks like. The sweep may never make
that decision on its own.

**`sweep`** — what may be reaped, and what stays and why. **Read-only unless `--apply`**, and
`--apply` needs at least one of `--remove-worktrees`, `--delete-branches`, `--prune`. Show the
read-only output to the human and let them choose; never pass `--apply` on your own initiative.

## What the sweep will and will not do

**Four conditions, and the first two are about permission rather than safety.** A worktree is
reaped only when **all** of these hold; anything else is kept with its reason printed beside it.

1. **The plugin created it.** `add` records that in the worktree's own admin directory, and only a
   worktree carrying that record is ever reaped. A worktree somebody opened by hand, or a
   colleague's, is indistinguishable from ours by branch name and merge state — so nothing but an
   explicit record can tell them apart, and guessing deletes other people's working copies.
2. **The phase is settled** — sign-off passed, no task still open, and `mergedAt` recorded. A
   branch can be contained in its parent while the phase is mid-flight; "the commits are safe" is
   not "the plugin has finished".
3. **The branch is contained in its parent.**
4. **The tree is clean**, and it is not locked.

Two consequences to say out loud rather than let the human discover:

- **Removal destroys ignored files.** `git worktree remove` deletes a `.env` or a `node_modules`
  under that path without complaint, and `git status` never mentioned them. Say this before the
  human answers, not after.
- **A repository can hold many worktrees and have none the sweep may touch.** That is a real state,
  not a failure, and the output says so in its own words rather than reporting a clean sheet.
  `remove --path` is how those come down.

## Exit codes

`0` it ran · `1` it could not, and the reason names a path · `2` usage · `4` git could not be
**asked** · `5` there was nothing to examine — which is **not** the same as "everything is clean",
and must not be reported as if it were.

## After a phase signs off

Cleanup normally happens inside sign-off (`close-phase.py`, orchestrator step 5) under
`meta.merge`. This command is for the worktrees that outlived it: a run interrupted before
sign-off, a phase abandoned, or a repository that accumulated them before `meta.merge` existed.
