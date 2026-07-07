---
description: 'Manifest-driven audit/fix pipeline orchestrator. Reads the audit manifest and executes phases/tasks with per-task model + skills, TDD gates, and optional review sign-off. Subcommands: status | next | run <taskId> | phase <id> | review <phaseId> | resume | report.'
argument-hint: 'status | next | run <taskId> | phase <id> | review <phaseId> | resume | report'
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep, AskUserQuestion
---

# /audit — manifest-driven execution orchestrator

**Source of truth:** the audit manifest. Its path comes from `.claude/audit.config.json`
→ `manifestPath` (default `docs/audit/audit-plan.json`). Read it FIRST on every invocation.

**ARGUMENTS:** `$ARGUMENTS` — first token is the subcommand (default `status` if empty), remainder are its parameters.

## Preflight (every invocation)

1. If `.claude/audit.config.json` exists but is NOT valid JSON: **STOP** and report the parse
   error. A malformed config silently disables the project's custom guard rules (the hooks fall
   back to defaults), so it must be fixed before any audit work.
2. If no file exists at `manifestPath`: **STOP**. Point to `/audit:init` (generates the manifest)
   or to copying the plugin's `templates/audit-plan.starter.json`. Never invent a manifest.
3. Unknown subcommand → print the subcommand list with one-line descriptions and STOP.
4. **Git-root check** (before any mutating subcommand). Resolve the git root (see below) and run
   `git -C <gitRoot> rev-parse --show-toplevel`. If it fails (the git root is not a git repo):
   **STOP** and tell the human: set `meta.gitRoot` to the path of the git repo relative to the
   project directory (e.g. `"test"` for a workspace-in-a-subdir), OR run `/audit:init` from inside
   the git repo. Do NOT run git operations from a non-repo — that is the failure the check prevents.
   Also: if `<manifestPath>` resolves OUTSIDE `<gitRoot>`, WARN that the manifest's status history
   cannot be committed alongside task work (resume's git reconstruction is limited) and recommend
   moving the manifest under the git root.

**Config resolution.** Everything project-specific comes from the manifest's `meta` block (with safe defaults);
never hardcode branch names, package ids, skills, or build tools here:
- `meta.gitRoot` — path (relative to the project dir) of the git repository root, where ALL git
  operations and build/gate commands run. Default `.` (the project dir IS the git root — the normal
  case). **Back-compat:** if `meta.gitRoot` is absent, fall back to `meta.workspaceRoot`, else `.`.
  When it is not `.`: run every git command as `git -C <gitRoot> …`, run gates from `<gitRoot>`, and
  when staging strip the `<gitRoot>/` prefix from each `task.files` entry (they are project-dir-relative)
  to get its git-root-relative path.
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

- **All git and gate commands run in `<gitRoot>`** (resolved above; `.` = project dir). Use
  `git -C <gitRoot> …` for every git call, and run build/gate commands from `<gitRoot>` (do NOT add a
  `cd <subdir>` of your own — the manifest's gate commands are already relative to the git root). When
  staging `task.files`, convert each to git-root-relative by stripping the `<gitRoot>/` prefix.
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

---

## Subcommand: `status`
Read the manifest and print:
1. Per-phase line: `id — title — status (done/total tasks) — branch (if set) — desiredOutcome (if set)`.
2. Per-task rows grouped by phase: `id | title | status | model | unmet blockers | commit (short SHA or —)`.
3. A **"Ready now"** list: every ready task, with its model.
4. If any phase is `in_progress` with a non-null `branch` (or contains an `in_progress` task):
   flag it as **resumable** — "interrupted? run `/audit resume`".
5. If `bugs[]` exists and is non-empty: counts by bug status, plus every non-closed bug whose
   materialized task (`taskId`) is ready now.
Do not modify anything. Related commands: `/audit:init` (generate this manifest),
`/audit:task` (add a task), `/audit:bug` (track bugs), `/audit:sync` (Azure DevOps work items).

## Subcommand: `next`
1. Find the first **ready** task (phase order, then task-id order).
2. If none ready: report why (what everything is blocked on) and stop.
3. Otherwise **Execute the task**, then report its outcome and what is ready next.

## Subcommand: `run <taskId>`
Execute exactly `<taskId>`, with status guards:
1. `status == "done"` → refuse: report its `commit`/`outcome`. Offer (AskUserQuestion) an explicit
   **re-open**: on confirmation, reset `status = "pending"`, `attempts = 0`, clear `commit`,
   `outcome`, `completedAt`, `verifiedBy` — then execute. Never silently re-run a done task.
2. `status == "blocked"` → refuse: report why (exhausted attempts / blockers). Offer a confirmed
   reset of `attempts` to 0 (back to `pending`), then execute.
3. `status == "in_progress"` → warn: likely an interrupted run — point to `/audit resume`.
   Proceed only if the human explicitly confirms re-execution.
4. Unmet blockers → refuse and list them.
5. Otherwise **Execute the task**.

## Subcommand: `phase <phaseId>`
1. If the phase is `done` → refuse; point to `review <phaseId>` for a re-run of sign-off.
2. Execute every **ready** task in the phase in parallel where safe (disjoint `files` and satisfied
   `dependsOn`), sequentially otherwise. (**Execute the task** performs phase entry — branch,
   `baseRef`, phase status — on its first run.)
3. Re-evaluate readiness and repeat until no task in the phase is ready.
4. When **all** tasks in the phase are `done`, run **Phase sign-off**.

## Subcommand: `review <phaseId>`
Run **Phase sign-off** for `<phaseId>` on demand (e.g. to re-run after fixes).

## Subcommand: `resume`
Run **Resume after interruption** (below). Use after a crash, a lost session, or any interrupted
`phase`/`next`/`run` — `status` flags when this applies.

## Subcommand: `report`
Read-only. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render-report.py" <manifestPath>`
(artifacts land next to the manifest; pass `--out-dir <dir>` through when the human asks)
and print the written paths. The report is self-contained HTML + Markdown — shareable as a
CI artifact. Never locks, never mutates.

---

## Concurrency lock

Two sessions mutating one manifest/working tree corrupt each other. Every **mutating**
subcommand (`next`, `run`, `phase`, `review`, `resume`) holds `<manifestPath>.lock`:

1. **Acquire (at subcommand start).** If the lock file exists, read it
   (`{hostname, startedAt, note}`):
   - `startedAt` younger than **60 minutes** → REFUSE: print the holder info and stop —
     another session is (or very recently was) working this manifest.
   - older → stale (a crashed run): ask the human (AskUserQuestion) to confirm **takeover**,
     then overwrite the lock.
   Otherwise create it via Bash:
   `printf '{"hostname":"%s","startedAt":"%s","note":"audit orchestrator"}' "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > <manifestPath>.lock`
2. **Release** — delete the lock at the END of the subcommand, including failure paths you
   control (a refusal that never acquired it releases nothing). Human-confirmation pauses
   (AskUserQuestion) keep the lock — that is still your run.
3. `status` and `report` never lock and never wait for one.
4. Never commit the lock file (do not `git add` it); recommend `.gitignore`-ing
   `*.lock` under the manifest directory.

---

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

---

## Execute the task

1. **Phase entry** (first started task of the phase, or after an interruption):
   a. Set `phase.status = "in_progress"` if it isn't already (Edit) — resume depends on this write.
   b. If `phase.baseRef` is null → `git rev-parse HEAD` (Bash), write it back.
   c. Create or switch to the phase branch per **Branch-per-phase** (including the
      development-branch verification — it applies on the `run` and `next` paths too).
2. Set `task.status = "in_progress"`, `task.startedAt = <ISO now>`, `task.attempts += 1` (Edit the manifest).
   If `task.attempts > (task.maxAttempts or 3)`, do NOT spawn — set `status = "blocked"` and surface to the human.
3. **Spawn the plugin's executor agent** via the `Agent` tool —
   `subagent_type: "audit:audit-executor"`, `model = task.model`. Its tool list is pinned
   (no web tools, no nested agents) and its system prompt carries the invariants; if that
   agent type is unavailable (older Claude Code), fall back to a general-purpose subagent
   and restate every rule below inline. In the spawn prompt:
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
4. On the subagent's return:
   - **success** (all gates green):
     a. **Risk gate first:** if `task.risk == "high"`, **stop and ask the human to confirm**
        (AskUserQuestion) before committing — always, no exceptions.
     b. Set `task.status = "done"`, `task.completedAt = <ISO now>`, fill `task.outcome` and `task.verifiedBy`.
        (The **orchestrator**, not the subagent, writes `outcome`.)
     c. **Commit the task's work** on the phase branch (all git via `git -C <gitRoot>`):
        - Stage the task's `files` (each stripped of the `<gitRoot>/` prefix). Stage the manifest too
          **only if it lives inside `<gitRoot>`**; if it is outside (e.g. at the project dir while the
          git repo is a subdir), it cannot be committed — proceed without it (the preflight already
          warned that status history isn't versioned in that layout).
        - Commit with `<meta.commit.type>(<taskId>): audit - <short subject>` (use a more specific conventional
          type when it fits — `fix`, `perf`, `test`, `docs`). Append `meta.commit.coauthor` if set.
        - Capture the SHA (`git rev-parse HEAD`) and write it into `task.commit` (Edit again).
          **If `task.bugId` is set**, in that same Edit also flip the linked bug in the top-level
          `bugs[]`: `status = "fixed"`, `fixedIn = <that SHA>`.
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
      the summary must state how the phase met — or didn't meet — it).
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
   report "nothing to resume" and suggest `status`. Otherwise `git switch` to its branch.
2. Compare committed work: `git log --oneline <phase.baseRef>..HEAD`.
3. Find the resume point: the **first task whose `commit` field is null/missing**:
   - `status == "done"` but no `commit` → the commit step was interrupted; re-commit its files now (standard message, record SHA).
   - `status == "in_progress"` and no `commit` → working-tree changes are **untrusted**; run `git status`. If complete and
     gates pass, finish + commit; if partial, **ask the human** whether to discard (`git checkout -- <files>`) and re-run.
     Never discard without confirmation.
   - `status == "pending"` → resume normally (Execute the task).
4. Continue normal execution from the resume point.

---

## Reporting
After any mutating subcommand, print: tasks completed this run (with one-line outcomes), the phase sign-off result if
reached, and the next ready task(s). Keep the manifest the single source of truth — never track status elsewhere.
