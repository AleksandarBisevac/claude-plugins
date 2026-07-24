# Audit orchestrator — shared execution logic

Read this FIRST from every `/audit:*` execution command (`status`, `next`, `run`, `phase`,
`review`, `resume`, `report`) together with `manifest-conventions.md`. Each command does its
own slice and defers all the shared rules — config resolution, preflight, guardrails,
readiness, the lock, branch-per-phase, Execute-the-task, Phase sign-off, resume — to this file.

## At a glance

- **Verbs:** `status`/`report` are read-only (no lock); `next`/`run`/`phase`/`review`/`resume`
  mutate (full preflight + lock + progress output).
- **Invariants (never violate):** never `git push`/force-push/`stash`; commit only a task's own
  `files` + the phase's manifest file (the single file, or its `phases/<id>.json` shard); git runs
  via `git -C <gitRoot>`, gates run from the project dir verbatim; `risk:"high"` → human confirm
  before commit and never on `haiku`; every manifest write is re-validated; the manifest is the
  single source of truth.
- **A phase run:** preflight → phase branch off `developmentBranch` → Execute each ready task
  (parallel where `files` disjoint) → Phase sign-off (review? → test gate → runtime boot?) → merge
  back (ff, else confirmed `--no-ff`) → release lock.
- **On trouble:** unmet blockers → skip; gates red → retry to `maxAttempts` → `blocked`; gates
  can't run (infra) → don't burn an attempt, human action item; interrupted → `/audit:resume`.

**Source of truth:** the audit manifest. Its path comes from `.claude/audit.config.json`
→ `manifestPath` (default `docs/audit/audit-plan.json`). Read it FIRST on every invocation.

**Manifest layout (single-file vs sharded) — where writes go.** The manifest reads the same in
either layout (the scripts and hooks assemble transparently), but WRITES must target the right file:

- **Sharded layout** (`meta.version: 3` — `manifestPath` is an *index* whose phases are
  `{id, title, shard}` stubs pointing at `phases/<phaseId>.json`): every per-phase / per-task
  **runtime** field — phase `status`/`branch`/`baseRef`/`mergedAt`/`review`/`summary`/`claim` and
  task `status`/`attempts`/`startedAt`/`completedAt`/`outcome`/`commit` — lives in that phase's
  **shard**. Edit the SHARD, never the index. **Structural** writes (adding a phase/task/bug,
  `fileIndex`, `bugs[]`) go to the **index** under the index lock. A phase run therefore touches
  **only its own shard** — which is exactly why two phase branches merge without a manifest conflict.
- **Single-file layout** (`meta.version: 2` or absent): it's all one file, as before.
- If a legacy single-file manifest is in play, a mutating command should note **once** that
  `/audit:migrate` converts it to the sharded layout (fewer tokens per phase, parallel-safe) — a
  non-blocking suggestion; the single-file layout keeps working indefinitely.

Below, "**Edit the phase's manifest file**" means the shard in the sharded layout, the one file otherwise.

## Preflight

Run the checks relevant to the command. **Read-only commands (`status`, `report`) run only 1–2;
mutating commands (`next`, `run`, `phase`, `review`, `resume`) run all of 1–5 before acting.**

1. If `.claude/audit.config.json` exists but is NOT valid JSON: **STOP** and report the parse
   error. A malformed config silently disables the project's custom guard rules (the hooks fall
   back to defaults), so it must be fixed before any audit work.
2. If no file exists at `manifestPath`: **STOP**. Point to `/audit:init` (generates the manifest)
   or to copying the plugin's `templates/audit-plan.starter.json`. Never invent a manifest.
3. **Git-root check** (mutating commands). Resolve the git root (see below) and run
   `git -C <gitRoot> rev-parse --show-toplevel`. If it fails (the git root is not a git repo):
   **STOP** and tell the human: set `meta.gitRoot` to the path of the git repo relative to the
   project directory (e.g. `"test"` for a workspace-in-a-subdir), OR run `/audit:init` from inside
   the git repo. Do NOT run git operations from a non-repo — that is the failure the check prevents.
   Also: if `<manifestPath>` resolves OUTSIDE `<gitRoot>`, WARN that the manifest's status history
   cannot be committed alongside task work (resume's git reconstruction is limited) and recommend
   moving the manifest under the git root.
4. **Submodule check** (mutating commands). If `<gitRoot>/.gitmodules` exists, run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit-status.py" <manifestPath> --submodules "<gitRoot>/.gitmodules" --git-root "<gitRoot>"`
   (omit `--git-root` when gitRoot is `.`). Exit 1 means one or more `task.files` live inside a git
   **submodule** — a separate nested repo the parent CANNOT stage/commit (`git add` fails with
   "Pathspec is in submodule"). **STOP** and relay its output: point `meta.gitRoot` at that submodule
   (to audit it directly), or remove those files from the task(s). Do not start a run that will fail
   at commit time.
5. **Acquire the lock** (mutating commands) — see **Concurrency lock**.

**Config resolution.** Everything project-specific comes from the manifest's `meta` block (with safe defaults);
never hardcode branch names, package ids, skills, or build tools here:
- `meta.gitRoot` — path (relative to the project dir) of the git repository root, where ALL git
  operations and build/gate commands run. Default `.` (the project dir IS the git root — the normal
  case). **Back-compat:** if `meta.gitRoot` is absent, fall back to `meta.workspaceRoot`, else `.`.
  When it is not `.`: run every GIT command as `git -C <gitRoot> …`, and when staging strip the
  `<gitRoot>/` prefix from each `task.files` entry (they are project-dir-relative) to get its
  git-root-relative path. **Build/gate commands are NOT rewritten** — they run from the project dir
  exactly as the manifest gives them (the manifest, or `/audit:init`, already includes any
  `cd <gitRoot> && …` prefix needed to reach the workspace). Do not add or strip a `cd` of your own.
- `meta.developmentBranch` — the parent branch audit branches fork from and merge back into (default `main`).
- `meta.branchPrefix` — prefix for per-phase branches (default `audit`).
- `meta.reviewSkill` — skill invoked at phase sign-off (default **null** → skip; tests are the signer).
- `meta.runtimeBoot` — object `{appRootPath, launch, verify}` for a runtime smoke gate (default **null** → skip).
- `meta.nodePreamble` — shell prefix to run before build gates, e.g. `source ~/.nvm/nvm.sh && nvm use`
  (default **null** → run gates directly). Do NOT pipe it — run it as its own statement, then chain the command.
- `meta.commit` — `{type, coauthor}` for commit messages (default `{type:"chore", coauthor:null}`).
- `meta.buildCommands` — optional template map `{lint,test,typecheck}`; gate entries like `"test:<project>"`
  resolve against it, else a gate string is run verbatim.

## Non-negotiable guardrails

- **Git commands run via `git -C <gitRoot>`; build/gate commands run from the PROJECT dir verbatim.**
  Every git call is `git -C <gitRoot> …` (`.` = project dir). Gate commands are run exactly as the
  manifest specifies, from the project directory — the manifest already carries any `cd <gitRoot> && …`
  prefix it needs (older `/audit:init` output and hand-written manifests both do this). Do NOT add or
  remove a `cd` of your own. When staging `task.files`, convert each to git-root-relative by stripping
  the `<gitRoot>/` prefix.
- **Git: read / pull / commit allowed.** Commit after each successful task and after phase sign-off.
  **NEVER `git push` or force-push.** All other `git reset`/`rebase`/`clean` require explicit human confirmation.
  If `meta.commit.coauthor` is set, end every commit message with it.
- **Branch operations pre-approved:** `git switch -c <prefix>/*`, `git switch <prefix>/*`,
  `git merge --ff-only <prefix>/*`, `git branch -d <prefix>/*`. All other branch/checkout ops need confirmation.
- **Never read secrets** and **never log tokens** — enforced by the plugin's guard hooks; do not work around them.
- If `meta.nodePreamble` is set, run it (un-piped) before any build/lint/test command.
- Every manifest write goes through `Edit` and must keep the JSON valid — after each mutation run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate-manifest.py" <manifestPath>` and fix any findings
  before proceeding (exit 0 = valid, 1 = findings, 2 = unreadable; `WARNING:` lines are advisory).
- **Task fields:** `commit` (SHA after task commit), `dependsOn` (task-id array), `attempts` (int, increment per
  execution), `startedAt`/`completedAt` (ISO), `risk` (`low`|`med`|`high`|null), `verifiedBy` (test names added),
  `maxAttempts` (int, default 3). Phase fields: `branch`, `mergedAt`, `desiredOutcome`. Treat missing fields as null/0.
- **`risk: "high"` tasks**: ALWAYS require explicit human confirmation (AskUserQuestion) before their
  commit, and must **never** run on `haiku` regardless of `task.model`.
- **`attempts >= maxAttempts`**: stop retrying, set `task.status = "blocked"`, and surface to the human.

## Readiness rule

A task is **ready** when ALL of:
1. its `status == "pending"`;
2. its **own** `blockedBy` is fully satisfied;
3. its **own** `dependsOn` is fully satisfied — every listed task-id must be `status == "done"`;
4. its **phase's** `blockedBy` is fully satisfied.

"Satisfied": a **task id** → that task's `status == "done"`; a **phase id** → that phase's `status == "done"`.

A phase becomes `done` only after **Phase sign-off**. Phase order follows the manifest; within a phase, order by task id.

**Parallel safety:** tasks whose `files` sets are disjoint AND whose `dependsOn` lists are mutually satisfied may
run in parallel (spawn multiple Agents in one message). Tasks sharing a file or linked via `dependsOn` run sequentially.

## Concurrency lock

Locks live in the **shared git directory**, not the working tree — so they coordinate across git
**worktrees/clones on one machine** AND never appear as a working-tree change (no `git status` /
hook noise). Resolve the lock directory once, at command start:

```bash
LOCKDIR="$(git -C <gitRoot> rev-parse --git-common-dir)/audit-locks"   # shared by all worktrees
mkdir -p "$LOCKDIR"
```
(If `git rev-parse` fails — no git repo — fall back to `<manifestPath>.lock` in the working tree;
that path coordinates within a single clone only. The git-root preflight normally guarantees a repo.)

**Two tiers — take the narrowest lock that covers your writes:**

- **Index lock** `"$LOCKDIR/index.lock"` — held **briefly** for STRUCTURAL writes and id allocation:
  `init`, `task`, `bug`, `sync`, allocating a new phase/task/bug id, and the phase **status-mirror**
  write in the index. Acquire → edit the index → release, within that step.
- **Phase-shard lock** `"$LOCKDIR/phase-<phaseId>.lock"` — held for the DURATION of a phase run by
  `next`/`run`/`phase`/`review`/`resume` on that phase. Two DIFFERENT phases take two different
  locks → they run in **parallel** (separate worktrees), each writing only its own shard. A run that
  must also allocate an id or touch the index takes the index lock too, briefly (nested), then releases it.

**The protocol for EITHER lock file:**

1. **Acquire (at command start).** If the lock file exists, read it (`{hostname, startedAt, note}`):
   - `startedAt` younger than **60 minutes** → REFUSE: print the holder info and stop —
     another session holds this lock (this manifest's index, or this specific phase).
   - older → stale (a crashed run): ask the human (AskUserQuestion) to confirm **takeover**,
     then overwrite the lock.
   Otherwise create it via Bash:
   `printf '{"hostname":"%s","startedAt":"%s","note":"<verb> <scope>"}' "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCKDIR/<lockfile>"`
2. **Release** — delete the lock file at the END of the command, including failure paths you control
   (a refusal that never acquired it releases nothing). Human-confirmation pauses (AskUserQuestion)
   keep the lock — that is still your run.
3. `/audit:status` and `/audit:report` never lock and never wait for one.
4. The lock directory is inside the git dir — it is NEVER committed or shown by `git status`, so no
   `.gitignore` entry is needed. (The legacy `<manifestPath>.lock` fallback still wants `*.lock` ignored.)

## Branch-per-phase

Each phase gets a **local** branch so work is isolated, reviewable, and resumable.

**Parent branch rule:** audit branches fork from `meta.developmentBranch` (default `main`) and merge back into it.

**Phase entry** happens on EVERY execution path (`phase`, `next`, `run`) via **Execute the task** step 1:
- **If `phase.branch` is already set** (resume/continue): `git switch <phase.branch>` if not already on it.
- **If `phase.branch` is null** (first task of the phase):
  1. **Verify the current branch is `meta.developmentBranch`; if it isn't, STOP and ask the human before branching.**
  2. Derive a short slug from `phase.title` (lowercase, spaces → hyphens, max 30 chars, alphanumeric + hyphens).
  3. Compose the branch name: `<meta.branchPrefix>/<phaseId-lowercase>-<slug>` (default prefix `audit`).
  4. `git switch -c <branch>`, then write the branch name into `phase.branch` (Edit).

**During task execution:** all edits and commits happen on the phase branch. **Push remains FORBIDDEN** — local only.

## Execute the task

1. **Phase entry** (first started task of the phase, or after an interruption):
   a. Set `phase.status = "in_progress"` if it isn't already (Edit the phase's manifest file — the
      shard when sharded) — resume depends on this write.
   b. If `phase.baseRef` is null → `git rev-parse HEAD` (Bash), write it back.
   c. Create or switch to the phase branch per **Branch-per-phase** (including the
      development-branch verification — it applies on the `run` and `next` paths too).
   d. **Claim the phase** (sharded layout only): write `phase.claim = {sessionId, host, branch, at}`
      into the shard — optimistic cross-machine coordination, so a same-phase double-claim on another
      branch surfaces as a shard merge conflict. The FS phase-lock is the same-machine guard; the
      claim is the durable, pushed record for other machines. It is released at sign-off.
2. Set `task.status = "in_progress"`, `task.startedAt = <ISO now>`, `task.attempts += 1` (Edit the manifest).
   If `task.attempts > (task.maxAttempts or 3)`, do NOT spawn — set `status = "blocked"` and surface to the human.
3. **Spawn the plugin's executor agent** via the `Agent` tool —
   `subagent_type: "audit:audit-executor"`, `model = task.model`. Pass **only** the model;
   do **not** set reasoning effort — effort is pinned in each audit agent's own definition
   (`effort:` in its frontmatter), deliberately **decoupled from the calling session** so an
   audit's cost/latency is reproducible no matter what effort the invoking session runs at.
   (There is no per-spawn effort override anyway; the frontmatter is the only lever. On the
   general-purpose fallback below, effort cannot be pinned and reverts to the session's — an
   accepted degradation.) Its tool list is pinned (no web tools, no nested agents) and its
   system prompt carries the invariants; if that agent type is unavailable (older Claude
   Code), fall back to a general-purpose subagent and restate every rule below inline. In the
   spawn prompt:
   - Tell it to **first invoke each skill in `task.skills`** via the `Skill` tool (load conventions before coding).
   - Give it `task.description`, `task.files`, `task.docs`, the phase's `desiredOutcome` (so the work
     aims at the phase's stated goal), and the repo hard-rules (no token logging, no secret
     reads, plus any `meta`-level conventions). It must load project skills for domain rules.
   - **Test discipline by `task.tests.mode`:**
     - `tdd` → write a test asserting each item in `task.tests.add` that **FAILS on current code** first
       (run it, confirm red — proves the bug), THEN implement until green. (`tests.expectRedFirst` should be true.)
     - `regression` → implement the fix and add a test locking the corrected behavior (`task.tests.add`).
     - `gate-only` → no new test; only ensure `task.tests.gate` stays green.
   - It must run `task.tests.gate` (running `meta.nodePreamble` first, un-piped, if set) and report pass/fail per
     gate plus a structured **outcome** = `{ technical, descriptive }`. It must distinguish
     **"gates ran and failed"** from **"gates could not run"** (command not found, runner crashed
     before executing tests, zero tests collected where `tests.add` expects some).
   - The subagent does **not** commit — the orchestrator commits (step 4).
   - **The subagent must NEVER run `git stash`** (a stash in a shared working tree destroys sibling tasks' work).
     For baselines it should use `git diff`/`git show HEAD:<file>` instead. Put this in every subagent prompt.
   - **No usable return** (the subagent died, timed out, or came back with no parseable outcome / no
     file changes) is a **failure**, not a success — handle it exactly like a test failure in step 4
     (leave `in_progress`, do not commit; retry until `attempts >= maxAttempts`, then `blocked`).
4. On the subagent's return:
   - **success** (all gates green):
     a. **Risk gate first:** if `task.risk == "high"`, **stop and ask the human to confirm**
        (AskUserQuestion) before committing — always, no exceptions.
     b. Set `task.status = "done"`, `task.completedAt = <ISO now>`, fill `task.outcome` and `task.verifiedBy`.
        (The **orchestrator**, not the subagent, writes `outcome`.)
     c. **Commit the task's work** on the phase branch (all git via `git -C <gitRoot>`):
        - Stage the task's `files` (each stripped of the `<gitRoot>/` prefix). Stage the phase's
          manifest file too — the shard `phases/<phaseId>.json` when sharded, else the single manifest —
          **only if it lives inside `<gitRoot>`**; if it is outside (e.g. at the project dir while the
          git repo is a subdir), it cannot be committed — proceed without it (the preflight already
          warned that status history isn't versioned in that layout). **Do NOT stage the index** — a
          task commit changes only its own phase's shard.
        - Commit with `<meta.commit.type>(<taskId>): audit - <short subject>` (use a more specific conventional
          type when it fits — `fix`, `perf`, `test`, `docs`). Append `meta.commit.coauthor` if set.
        - Capture the SHA (`git rev-parse HEAD`) and write it into `task.commit` (Edit the phase's manifest file again).
          **Do NOT write `bugs[]`.** A bug materialized into this task (`bug.taskId` ↔ `task.bugId`)
          reads as **fixed** automatically once the task is `done` — the rollup derives it (with
          `fixedIn` = this `task.commit`) — so the shared index stays untouched and parallel phases
          merge clean. (`/audit:bug close` still records a human `wontfix`/`fixed` on the index, under
          the index lock — a structural decision, not part of a run.)
        - The `task.commit` write rides along with the next task's commit (or the sign-off commit) — do NOT amend.
   - **test failure** (gates RAN and are red) → leave `status = "in_progress"` (or `"blocked"` if attempts
     exhausted), put the reason in `task.outcome.technical`, and report it. Do not mark done, do not commit.
   - **infrastructure failure** (gates could NOT run: missing command, runner crash before tests,
     zero tests collected where `tests.add` expects some) → this is NOT the task's failure:
     **revert the `attempts` increment from step 2** (Edit it back down), record the cause in
     `task.outcome.technical`, leave `status = "in_progress"`, and **STOP with a human action item**
     (fix `meta.buildCommands` / `tests.gate` first). Never burn retries on missing infrastructure.
5. Manual gate items (e.g. `"manual: <checklist>"`) cannot be auto-run — surface them as **human action items**.

## Phase sign-off (Definition of Done — strict order)

Run only when **all** tasks in the phase are `done`. All review/test work runs on the phase branch.

1. **`reviewResolved`** — compute the phase's changed files (union of `files` across its tasks, cross-checked with
   the manifest's top-level `fileIndex`). **If `meta.reviewSkill` is set**, spawn the plugin's reviewer agent
   (`subagent_type: "audit:audit-reviewer"`, `model = phase.review.model`) with the diff scope
   (`git diff <phase.baseRef> -- <files>`), the phase's `desiredOutcome`, and the skill name — it invokes the
   skill itself and returns structured findings (it has no edit tools by design, and the diff stays out of YOUR
   context). Record results in `phase.review.findings`; for each actionable finding spawn an
   `audit:audit-executor` fix run (`model = phase.review.model`) that may edit implementation AND tests; loop until
   clean or each remaining finding is explicitly triaged with a written justification. Fall back to a
   general-purpose subagent with the same rules if the agent type is unavailable. **If `meta.reviewSkill` is
   null**, skip this step — tests are the signer.
2. **`testGateGreen`** — run the full `phase.testGate` (run `meta.nodePreamble` first, un-piped, if set). All commands
   must pass **after** any review-driven changes. Tests are the final signer. Surface manual items as human action items.
3. **`runtimeBootGreen`** — **only if `meta.runtimeBoot` is set** and the phase touched app source under
   `meta.runtimeBoot.appRootPath`. Cold-boot the app and verify the primary screen renders + one navigation
   away-and-back (jest mocks and tsc miss module-init/require-cycle boot crashes). Use the runtime steps in
   `meta.runtimeBoot`; if the runtime is unreachable, STOP and hand the human an explicit boot-check action item —
   the phase may NOT be signed off until the human confirms. If `meta.runtimeBoot` is null, skip this step.
4. Only if all applicable gates pass:
   a. Set `phase.status = "done"`, `phase.review.status = "passed"` (or `"skipped"`), write `phase.review.outcome`
      and `phase.summary` (short paragraph: what was done + impact; when `phase.desiredOutcome` is set,
      the summary must state how the phase met — or didn't meet — it). **Clear `phase.claim`** if set —
      the run is finishing, release the claim. (All these are shard writes in the sharded layout.)
   b. **Sign-off commit** on the phase branch (`<meta.commit.type>(<phaseId>): phase sign-off — …`, + coauthor).
   c. **Merge into `meta.developmentBranch`**: `git switch <developmentBranch>`; `git merge --ff-only <branch>`.
      **If ff-merge fails** (the development branch advanced during the phase — the normal case on team
      repos), ask the human (AskUserQuestion) to choose:
      1. **`git merge --no-ff <branch>`** (recommended) — preserves the phase branch history and keeps every
         `task.commit` / `bug.fixedIn` SHA recorded in the manifest valid.
      2. **Stop** — leave the branch unmerged for manual resolution.
      **Never rebase the phase branch** — rebasing rewrites the SHAs recorded in the manifest.
   d. Write `phase.mergedAt = <ISO now>` (Edit on the now-merged branch).
   e. Optionally clean up: `git branch -d <branch>` (safe after a completed merge).

## Resume after interruption

1. Read the manifest. Find the phase with `status == "in_progress"` and a non-null `branch`.
   **Pre-0.3 manifests fallback:** if no phase is `in_progress`, use the phase with a non-null `branch`
   whose status != `"done"`, else the phase containing an `in_progress` task. If none of these exist,
   report "nothing to resume" and suggest `/audit:status`. Otherwise `git switch` to its branch.
2. Compare committed work: `git log --oneline <phase.baseRef>..HEAD`.
3. Find the resume point: the **first task whose `commit` field is null/missing**:
   - `status == "done"` but no `commit` → the commit step was interrupted; re-commit its files now (standard message, record SHA).
   - `status == "in_progress"` and no `commit` → working-tree changes are **untrusted**; run `git status`. If complete and
     gates pass, finish + commit; if partial, **ask the human** whether to discard (`git checkout -- <files>`) and re-run.
     Never discard without confirmation.
   - `status == "pending"` → resume normally (Execute the task).
4. Continue normal execution from the resume point.

## Progress output

A phase can run many tasks, gates, and a merge — don't go silent. Emit a short **progress line as each
step happens** so a long run stays legible (not one dump at the end):

- **Phase entry:** `> PHASE <id> "<title>" — branch <branch> — N tasks ready`.
- **Each task, at start:** `  > <taskId> "<title>" (model, tests.mode) — running`; when tasks run in
  parallel, print the group first (`  > parallel: <id>, <id>`).
- **Each task, on return:** `  [OK] <taskId> — gates green, committed <shortSHA>` /
  `  [FAIL] <taskId> — <gate> failed (attempt k/max)` / `  [BLOCKED] <taskId> — attempts exhausted` /
  `  [INFRA] <taskId> — <gate> could not run (human action item)`.
- **Sign-off:** one line per gate — `  - review: <passed|skipped|N findings>`, `  - testGate: <green|red>`,
  `  - runtimeBoot: <green|skipped|manual>` — then `[SIGNED OFF] PHASE <id> — merged into <branch>` (or
  `[MERGE] ff failed — <no-ff|stopped>`).

Use simple ASCII markers (`>` `[OK]` `[FAIL]` `-`) so it reads in any terminal. Keep each line to one sentence.

## Dry-run / preview

`next`, `run`, and `phase` accept a **`--dry-run`** token in their arguments. In dry-run:

- Run only the read-only preflight (config parse + manifest exists + resolve gitRoot); **do NOT
  acquire the lock, create branches, spawn subagents, run gates, edit the manifest, or commit.**
- Print the plan the real run would follow and STOP:
  - the resolved **gitRoot** and **developmentBranch**, and the **phase branch name** that would be created;
  - the **ready tasks** in execution order, with the **parallel groups** (disjoint `files` + satisfied
    `dependsOn`) vs the ones that must run sequentially, each with its `model`, `tests.mode`, and gate(s);
  - any task that is NOT ready and why (unmet `blockedBy`/`dependsOn`);
  - the **eventual merge target** (`<developmentBranch>`) and whether a fast-forward is currently possible
    (`git -C <gitRoot> merge-base --is-ancestor` check — informational only);
  - a closing `DRY RUN — nothing was changed.`
- `status` and `report` are already read-only previews; `--dry-run` is for the mutating verbs.

## Reporting

After any mutating command, print a final summary: tasks completed this run (with one-line outcomes), the
phase sign-off result if reached, and the next ready task(s) (`/audit:next` / `/audit:phase <id>`). Keep
the manifest the single source of truth — never track status elsewhere. Release the lock.
