---
description: Manifest-driven audit/fix pipeline orchestrator. Reads the audit manifest and executes phases/tasks with per-task model + skills, TDD gates, and optional review sign-off. Subcommands: status | next | run <taskId> | phase <id> | review <phaseId>.
argument-hint: status | next | run <taskId> | phase <id> | review <phaseId>
allowed-tools: Read, Edit, Bash, Agent, Skill, Glob, Grep
---

# /audit — manifest-driven execution orchestrator

**Source of truth:** the audit manifest. Its path comes from `.claude/audit.config.json`
→ `manifestPath` (default `docs/audit/audit-plan.json`). Read it FIRST on every invocation.

**ARGUMENTS:** `$ARGUMENTS` — first token is the subcommand (default `status` if empty), remainder are its parameters.

**Config resolution.** Everything project-specific comes from the manifest's `meta` block (with safe defaults);
never hardcode branch names, package ids, skills, or build tools here:
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

- **Git: read / pull / commit allowed.** Commit after each successful task and after phase sign-off.
  **NEVER `git push` or force-push.** All other `git reset`/`rebase`/`clean` require explicit human confirmation.
  If `meta.commit.coauthor` is set, end every commit message with it.
- **Branch operations pre-approved:** `git switch -c <prefix>/*`, `git switch <prefix>/*`,
  `git merge --ff-only <prefix>/*`, `git branch -d <prefix>/*`. All other branch/checkout ops need confirmation.
- **Never read secrets** and **never log tokens** — enforced by the plugin's guard hooks; do not work around them.
- If `meta.nodePreamble` is set, run it (un-piped) before any build/lint/test command.
- Every manifest write goes through `Edit` and must keep the JSON valid (re-parse after editing).
- **Task fields:** `commit` (SHA after task commit), `dependsOn` (task-id array), `attempts` (int, increment per
  execution), `startedAt`/`completedAt` (ISO), `risk` (`low`|`med`|`high`|null), `verifiedBy` (test names added),
  `maxAttempts` (int, default 3). Phase fields: `branch`, `mergedAt`. Treat missing fields as null/0.
- **`risk: "high"` tasks**: require explicit human confirmation before their commit in auto mode, and must
  **never** run on `haiku` regardless of `task.model`.
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
1. Per-phase line: `id — title — status (done/total tasks) — branch (if set)`.
2. Per-task rows grouped by phase: `id | title | status | model | unmet blockers | commit (short SHA or —)`.
3. A **"Ready now"** list: every ready task, with its model.
Do not modify anything.

## Subcommand: `next`
1. Find the first **ready** task (phase order, then task-id order).
2. If none ready: report why (what everything is blocked on) and stop.
3. Otherwise **Execute the task**, then report its outcome and what is ready next.

## Subcommand: `run <taskId>`
Execute exactly `<taskId>`. If its blockers are unmet, refuse and list them. Otherwise **Execute the task**.

## Subcommand: `phase <phaseId>`
1. If `phase.baseRef` is null, set it to `git rev-parse HEAD` (Bash) and write it back.
2. **Create or switch to the phase branch** (see Branch-per-phase below).
3. Execute every **ready** task in the phase in parallel where safe (disjoint `files` and satisfied `dependsOn`),
   sequentially otherwise.
4. Re-evaluate readiness and repeat until no task in the phase is ready.
5. When **all** tasks in the phase are `done`, run **Phase sign-off**.

## Subcommand: `review <phaseId>`
Run **Phase sign-off** for `<phaseId>` on demand (e.g. to re-run after fixes).

---

## Branch-per-phase

Each phase gets a **local** branch so work is isolated, reviewable, and resumable.

**Parent branch rule:** audit branches fork from `meta.developmentBranch` (default `main`) and ff-merge back into it.
**At phase start, verify the current branch is `meta.developmentBranch`; if it isn't, STOP and ask the human before branching.**

**At phase start** (first time `phase <phaseId>` runs, or when `phase.branch` is null):
1. Derive a short slug from `phase.title` (lowercase, spaces → hyphens, max 30 chars, alphanumeric + hyphens).
2. Compose the branch name: `<meta.branchPrefix>/<phaseId-lowercase>-<slug>` (default prefix `audit`).
3. If **new**: `git switch -c <branch>`. If **existing** (resume): `git switch <branch>`.
4. Write the branch name into `phase.branch` (Edit).

**During task execution:** all edits and commits happen on the phase branch. **Push remains FORBIDDEN** — local only.

---

## Execute the task

1. **Capture phase baseRef** if this is the phase's first started task and `phase.baseRef` is null →
   `git rev-parse HEAD`, write it back. Create the phase branch if not already done.
2. Set `task.status = "in_progress"`, `task.startedAt = <ISO now>`, `task.attempts += 1` (Edit the manifest).
   If `task.attempts > (task.maxAttempts or 3)`, do NOT spawn — set `status = "blocked"` and surface to the human.
3. **Spawn a subagent** via the `Agent` tool with `model = task.model`:
   - Tell it to **first invoke each skill in `task.skills`** via the `Skill` tool (load conventions before coding).
   - Give it `task.description`, `task.files`, `task.docs`, and the repo hard-rules (no token logging, no secret
     reads, plus any `meta`-level conventions). It must load project skills for domain rules.
   - **Test discipline by `task.tests.mode`:**
     - `tdd` → write a test asserting each item in `task.tests.add` that **FAILS on current code** first
       (run it, confirm red — proves the bug), THEN implement until green. (`tests.expectRedFirst` should be true.)
     - `regression` → implement the fix and add a test locking the corrected behavior (`task.tests.add`).
     - `gate-only` → no new test; only ensure `task.tests.gate` stays green.
   - It must run `task.tests.gate` (running `meta.nodePreamble` first, un-piped, if set) and report pass/fail per
     gate plus a structured **outcome** = `{ technical, descriptive }`.
   - The subagent does **not** commit — the orchestrator commits (step 4).
   - **The subagent must NEVER run `git stash`** (a stash in a shared working tree destroys sibling tasks' work).
     For baselines it should use `git diff`/`git show HEAD:<file>` instead. Put this in every subagent prompt.
4. On the subagent's return:
   - **success** (all gates green):
     a. **Risk gate first:** if `task.risk == "high"` and in auto mode, **stop and ask the human to confirm** first.
     b. Set `task.status = "done"`, `task.completedAt = <ISO now>`, fill `task.outcome` and `task.verifiedBy`.
        (The **orchestrator**, not the subagent, writes `outcome`.)
     c. **Commit the task's work** on the phase branch:
        - Stage the task's `files` plus the manifest.
        - Commit with `<meta.commit.type>(<taskId>): audit - <short subject>` (use a more specific conventional
          type when it fits — `fix`, `perf`, `test`, `docs`). Append `meta.commit.coauthor` if set.
        - Capture the SHA (`git rev-parse HEAD`) and write it into `task.commit` (Edit again).
        - The `task.commit` write rides along with the next task's commit (or the sign-off commit) — do NOT amend.
   - **failure** → leave `status = "in_progress"` (or `"blocked"` if attempts exhausted), put the reason in
     `task.outcome.technical`, and report it. Do not mark done, do not commit.
5. Manual gate items (e.g. `"manual: <checklist>"`) cannot be auto-run — surface them as **human action items**.

## Phase sign-off (Definition of Done — strict order)

Run only when **all** tasks in the phase are `done`. All review/test work runs on the phase branch.

1. **`reviewResolved`** — compute the phase's changed files (union of `files` across its tasks, cross-checked with
   the manifest's top-level `fileIndex`). **If `meta.reviewSkill` is set**, invoke that Skill scoped to `git diff <phase.baseRef> -- <files>`;
   record results in `phase.review.findings`, and for each actionable finding spawn a fix subagent
   (`model = phase.review.model`) that may edit implementation AND tests; loop until clean or each remaining finding
   is explicitly triaged with a written justification. **If `meta.reviewSkill` is null**, skip this step — tests are
   the signer.
2. **`testGateGreen`** — run the full `phase.testGate` (run `meta.nodePreamble` first, un-piped, if set). All commands
   must pass **after** any review-driven changes. Tests are the final signer. Surface manual items as human action items.
3. **`runtimeBootGreen`** — **only if `meta.runtimeBoot` is set** and the phase touched app source under
   `meta.runtimeBoot.appRootPath`. Cold-boot the app and verify the primary screen renders + one navigation
   away-and-back (jest mocks and tsc miss module-init/require-cycle boot crashes). Use the runtime steps in
   `meta.runtimeBoot`; if the runtime is unreachable, STOP and hand the human an explicit boot-check action item —
   the phase may NOT be signed off until the human confirms. If `meta.runtimeBoot` is null, skip this step.
4. Only if all applicable gates pass:
   a. Set `phase.status = "done"`, `phase.review.status = "passed"` (or `"skipped"`), write `phase.review.outcome`
      and `phase.summary` (short paragraph: what was done + impact).
   b. **Sign-off commit** on the phase branch (`<meta.commit.type>(<phaseId>): phase sign-off — …`, + coauthor).
   c. **Merge into `meta.developmentBranch`**: `git switch <developmentBranch>`; `git merge --ff-only <branch>`.
      If ff-merge fails (branch moved): **STOP, do not rebase, ask the human**.
   d. Write `phase.mergedAt = <ISO now>` (Edit on the now-merged branch).
   e. Optionally clean up: `git branch -d <branch>` (safe after ff-merge).

## Resume after interruption

1. Read the manifest. Find the phase with `status == "in_progress"` and a non-null `branch`; `git switch` to it.
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
