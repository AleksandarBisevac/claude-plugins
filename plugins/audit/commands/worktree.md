---
description: 'Audit pipeline: the worktrees this plan owns — list them with their merge state, add one for a phase so it can run in a parallel session, remove one, or sweep the ones whose work has already landed. The sweep is read-only until you name a verb; a worktree is only ever reaped when its branch is contained in its parent AND its tree is clean.'
disable-model-invocation: true
argument-hint: '<list|add|remove|sweep|task-add|task-remove> [phaseId|taskId] [--path DIR] [--force] [--apply] [--remove-worktrees] [--delete-branches] [--prune] [--json]'
allowed-tools: Read, Bash
---

# /audit:worktree — the worktrees this plan owns

Read `${CLAUDE_PLUGIN_ROOT}/reference/orchestrator.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/manifest-conventions.md` first.

A **git worktree** lets a phase run in its own Claude session, in parallel with other phases (best
on a **sharded** manifest — `/audit:layout sharded` — where phase runs write only their own shard
and merge back without conflict; anything that ADDS a record still lands in the index, which
`/audit:layout merge-driver install` merges by record). This command never edits the manifest.

**Every verb is one script call.** Do not compose `git worktree` commands yourself: this command
was prose until v2.1, and the prose composed a worktree path and then recorded it nowhere, so
nothing could enumerate what had been created and nothing ever cleaned up.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git/manage-worktrees.py" \
    <list|add|remove|sweep|task-add|task-remove> <manifestPath> [phaseId|taskId] --project <projectDir>
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

**A new worktree has no installed dependencies.** Git checks out tracked files only, so an ignored
`node_modules/`, a virtualenv or a build cache is not there. Say so in the next step, and install
inside the worktree with the project's own command before the phase runs its test gate. Do not
symlink the main checkout's `node_modules` in: the link resolves to a path outside the worktree,
and a dev server that confines file access to the project root — Vite's `server.fs.allow`, for
one — refuses to serve through it.

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

**`task-add <taskId> --base <sha>`** — a worktree for one task of a parallel wave: **detached** at
the given commit (the phase HEAD, resolved to a full SHA first), created **outside** the project
directory, and marked with the task, its phase, the base and the phase tree. A root inside the
project (or the git root) is refused, because the plan gate judges a tree under the project as the
project. `--path` names somewhere else than the default `../<repo>-<taskId>`. Harness-made
isolation is not a substitute: it lives under the exempt `.claude/` and branches from the default
branch.

**`task-remove <taskId>`** — removes the tree whose marker names **that** task; a marker for
another task is not ours and is named in the refusal. It refuses a dirty tree, an unreadable one
and the tree the process is standing in; `--force` is the explicit escape.

**The sweep never removes a task tree.** It lists each one as kept, names the task, and names any
dirty path — the wave driver takes the tree down with `task-remove` once its work is integrated.

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

## The lock worktree tooling shares

Worktrees of one clone share a single git directory, and the plugin's lock lives there
(`$(git rev-parse --git-common-dir)/audit-locks`), so a claim taken from any worktree is seen from
every other. Tooling of your own that must not run twice at once across worktrees — an e2e guard
driving one backend, a shared dev database — can take that same lock under a namespaced name
instead of inventing a lockfile per worktree, which each worktree would see only in its own tree.
Take it, run, and give it back **in one shell**, with an identity that belongs to this run alone:

```bash
audit_lock() { python3 "${CLAUDE_PLUGIN_ROOT}/scripts/governance/audit-lock.py" "$@"; }
audit_lock acquire user-e2e --session "e2e-$$" --pid $$ --wait 30 --project <worktreeDir>
taken=$?
[ "$taken" -eq 0 ] || exit "$taken"      # 3 held, 4 abandoned, 2 bad name, 1 error
rc=0
<the run that must be alone> || rc=$?
audit_lock release user-e2e --session "e2e-$$" --pid $$ --project <worktreeDir>
exit "$rc"
```

**It is a POSIX-shell recipe.** It runs unchanged under `sh`, `bash` and `zsh` — zsh is the macOS
default and the shell Claude Code's Bash tool uses there. That is why the command is a function and
not a variable (zsh does not split an unquoted variable into words) and why the exit status is `rc`
(`status` is read-only in zsh). `test__refs.py` runs this block under each of them that is
installed, and records a skip for each that is not. **Git Bash on Windows is not covered**: its
`$$` is an MSYS pid, not the Windows pid the lock probes for liveness, so a held lock there can read
as abandoned. The test skips that shell for that reason.

`--wait 30` waits out a live holder for that many seconds before refusing; `0` refuses at once.

**A `user-` lock excludes by holder.** A second `acquire` of the same name is refused while the
first holds it even when both carry one identity — and inside Claude Code they do: parallel
subagents in different worktrees share `$CLAUDE_CODE_SESSION_ID` and `$CLAUDE_PID`, the defaults
`--session` and `--pid` fall back to. The plugin's own names answer that case as re-entry ("already
yours"); a user lock never does. `release` still compares identities only, so **release only after
your own acquire succeeded**, as the early `exit` above ensures — a run sharing the holder's identity would
otherwise remove a claim it never took.

**Why `e2e-$$` and `$$`.** The pid is what liveness is judged on, and `$$` is the shell that lives
exactly as long as the hold. Recorded that way, a crashed run's lock reads as abandoned at once;
with no pid recorded, the claim falls back to the age rule and is not offered for takeover until it
is old. The same pair on acquire and release is what lets the release through.

**When the lock is refused**, `audit-lock.py` answers with its own exit codes, not the ones in the
next section, which are `/audit:worktree`'s: `3` a live run holds it — wait, or stop; `4` the holder is gone — confirm no run is
live, then `acquire user-e2e --takeover` retakes it; `2` the name broke the rules. `release
--force` removes any holder's claim, a user lock or the plugin's own, so it is for a lock you have
confirmed is dead, never a way past a live one.

**The name rules are the library's, not this page's.** `_locks.valid_name` decides and
`_locks.USER_NAME_RULES` states them; a refused name prints that sentence, from `acquire` and
`release` alike. The `user-` prefix is what keeps the namespace apart: the plugin's own names are
`index`, `usage` and `phase-<id>`, every reader that decides something from a name keys on those,
and a user name whose own part would read as one of them (`user-index`, `user-phase-p1`) is refused
as well, so no user lock can pass for the plugin's. `audit-lock.py status`, `/audit:status` and
`/audit:doctor` list user locks beside the plugin's by name; the doctor's advice for an abandoned one
is the `--takeover` above, since no `/audit` command takes a user lock over.

## Exit codes of `/audit:worktree`

`0` it ran · `1` it could not (for `task-add`: a root inside the project, a base that is no commit, a non-empty target; for `task-remove`: no tree marked for the task, or a dirty one), and the reason names a path · `2` usage (an unknown task included) · `4` git could not be
**asked** · `5` there was nothing to examine — which is **not** the same as "everything is clean",
and must not be reported as if it were.

## After a phase signs off

Cleanup normally happens inside sign-off (`close-phase.py`, orchestrator step 5) under
`meta.merge`. This command is for the worktrees that outlived it: a run interrupted before
sign-off, a phase abandoned, or a repository that accumulated them before `meta.merge` existed.
